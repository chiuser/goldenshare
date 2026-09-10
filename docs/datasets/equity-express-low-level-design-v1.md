# A股业绩快报（`express`）当前设计与维护说明

更新时间：2026-09-10。状态：代码已支持源端修订覆盖；历史部署、回补与待验收事项按日期单列。原文路径保留，旧开发流水已精简；本次不重新连接生产或认证部署状态。

## 1. 当前合同

`express` 调用 `express_vip`，按公告自然日维护全市场当前披露事实。只使用 `core_serving.equity_express` 一张物理表，不建 Raw、Std、observation、版本历史或 JSON 影子表。

```text
手动 / cron maintain → DatasetActionResolver
  → build_natural_day_point_units → _express_vip_params
  → DatasetSourceClient（完整分页）
  → normalizer（33 个源字段、三元身份、同批去重）
  → serving_revisable_fact_scope_upsert（公告日范围锁、完整性核对）
  → GenericDAO → core_serving.equity_express
```

当前代码不是不可变事实写入：同一身份的源数据修订会覆盖当前行。旧内容冲突拒绝、ImmutableFactDAO 注册等实现只属于历史，不可按旧步骤恢复。

依据：[Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/low_frequency.py)、[Tushare doc 46](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/财务数据/0046_业绩快报.md)、[执行计划基线](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)。

## 2. 时间、请求与观测

| 维度 | 当前行为 |
| --- | --- |
| 输入 | 单点 ann_date 或 start_date/end_date 自然日闭区间；无 filters、无 no-time |
| unit | 一个公告自然日、全市场；包含周末，不按股票池或交易日扇出 |
| 源参数 | builder 只传 ann_date=YYYYMMDD；不透传 period、股票或宽区间参数 |
| 分页 | offset_limit，page_limit=5000；满页继续，短页终止，每页显式带全部 33 fields |
| 规模 | fetch_concurrency=1，单次最多 366 unit；第 367 日在预检阶段拒绝 |
| 提交 | 完成该日全分页、归一化、范围核对后在 unit 业务事务内写入 |
| freshness | event_run_trace，观测 ann_date；不要求每天都有公告 |
| 日期审计 | bucket_rule=not_applicable、audit_applicable=False；不生成连续日期缺口 |
| Ops | “A股财务数据”分组；底层仍为 low_frequency 域；不接 workflow/probe/fallback |

`not_applicable` 不表示没有日期输入，也不表示退出现行 dataset cards/status snapshot 投影。

[planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)和[plan helper](/Users/congming/github/goldenshare/src/foundation/ingestion/plan_helpers.py)生成的首个单日 unit 示例：

```json
{
  "unit_id": "express:2025-04-08:0",
  "request_params": {"ann_date": "20250408"},
  "progress_context": {"ann_date": "2025-04-08", "date_field": "ann_date"},
  "pagination_policy": "offset_limit",
  "page_limit": 5000
}
```

日期对象在 unit 的 trade_date 槽位保存，但业务语义为公告日；进度与源请求分别使用 ISO 日期和 YYYYMMDD。页面不按 express 私造 object/window 字段。[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)、[source client](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)是当前真实文件。

## 3. 身份、字段与存储

完整 33 个源字段由 Definition 的 `EXPRESS_SOURCE_FIELDS` 固定，含原默认未返回的 `update_flag`。字段含义引用 doc 46，类型与系统列以 [EquityExpress ORM](/Users/congming/github/goldenshare/src/foundation/models/core_serving/equity_express.py)为准，不复制另一份 33 行清单。

| 字段组 | 保存方式 |
| --- | --- |
| ts_code、ann_date、end_date | 三元业务身份；日期为 DATE，代码原值保存，仅生成身份时 trim/upper |
| revenue 至 open_bps 的 26 个指标 | 归一化为 Decimal 后写入现有 DOUBLE PRECISION；不在本次统一改 Numeric |
| perf_summary、remark、update_flag | 可空文本；update_flag 不作为身份或修订开关 |
| is_audit | 可空 INTEGER；保留 0/1/2 及未知整数，不强制布尔化 |
| source_entity_key | 三元身份 JSON 的 SHA256，加 express 前缀；TEXT 主键 |
| source_content_hash | 归一化后全部 33 源字段的指纹，不含 ingested_at |
| identity_basis | 三元身份依据说明 |
| ingested_at | 当前内容版本入库时间；首次插入和内容修订会更新，同内容重跑保持不变 |

共 37 列。沿用原命名主键和三个索引：公告日/代码、代码/报告期/公告日、报告期/代码；不分区。历史迁移 [20260811_000132](/Users/congming/github/goldenshare/alembic/versions/20260811_000132_add_equity_express_table.py)在建表前验证 `gs_raw_cold_hdd`，heap、主键及二级索引都显式落该 tablespace，缺失即失败；downgrade 拒绝删除事实。PostgreSQL WAL 是实例共享日志，不随这张表迁移。

## 4. 写入、失败和重跑

当前 [writer](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)使用 `serving_revisable_fact_scope_upsert`；[DAOFactory](/Users/congming/github/goldenshare/src/foundation/dao/factory.py)注册 `GenericDAO(session, EquityExpress)`。不新增迁移或历史表。

1. [normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)与 [row transform](/Users/congming/github/goldenshare/src/foundation/ingestion/row_transforms.py)验证身份、公告日和必需源字段；同批相同身份相同内容去重，不同内容失败。
2. writer 对公告日取得事务级范围锁，读已有身份和指纹；源端缺少任一既有身份时拒绝，不能以新结果覆盖成更小范围。
3. 新身份插入；同身份指纹变化时覆盖全部源字段、内容指纹和 ingested_at；同内容不写入，不保留旧版本。
4. 写后核验影响行数及整个公告日身份—指纹集合。分页失败、拒绝行、同批冲突、范围回退或写后不一致，都不能发布部分结果。
5. 源端空且目标空是合法空日；源端空而目标非空属于范围回退。不能概括为“所有空结果都失败”。
6. 同一 unit 事务失败回滚；此前已提交日期保留。重试同范围依赖当前事实幂等，而不是删除、清空或还原旧版本。

常见错误：`write.revisable_fact_scope_regression`（源端范围回退）、`write.revisable_fact_rows_rejected`（存在拒绝）、`write.revisable_fact_persistence_incomplete`（写后核对失败）。出现这些错误须核验源端和已存范围，不能忽略或自动删行。

对账必须区分写入执行量、新增、修订和同内容匹配；旧不可变 writer 的“全部写入=新增+匹配”不能照搬到当前修订路径。内容哈希在 Decimal 归一化阶段生成，不能用数据库 FLOAT 读回结果重算后把类型差异判作损坏，应比较源归一化指纹与保存指纹。

## 5. 自动任务和运行边界

`since_last_success_day_range` 已是共享策略，不是待开发的 Express 特例：

- 支持普通 cron 的 daily/weekly/monthly；运营填写 `initial_start_date`，存入 `OpsSchedule.params_json.schedule_policy_params`，不作为 filter 或固定 time_input。
- 结束日为排程时区触发日减一天；开始日为 initial_start_date 与同一 schedule、express maintain 最后成功窗口 end_date+1 的较晚者。失败、取消、其他 schedule 不推进游标；retry 保留原 schedule 和范围。
- 无待补日期则跳过；窗口超过 366 日的 runtime 预检会暂停该 schedule，由运营明确分段处理后恢复，不自行拆分推进。
- 当前排程实现用 `FOR UPDATE SKIP LOCKED` 领取到期行，TaskRun 建立与排程推进在同一事务中完成；无需重复开展原 M1 调度重构。
- 自动窗口只向前推进，不重扫已成功的旧公告日。晚到和历史修订由运营手动选择点或区间重跑，不擅自增加滚动重叠窗口。

实现：[TaskRun 窗口](/Users/congming/github/goldenshare/src/ops/services/task_run_service.py)、[排程 service](/Users/congming/github/goldenshare/src/ops/services/operations_schedule_service.py)、[能力 resolver](/Users/congming/github/goldenshare/src/ops/services/dataset_schedule_time_policy_resolver.py)、[自动任务页面](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-auto-tab.tsx)。

每个自然日至少一次源请求；5,000 是页大小，366 是 unit 数上限，均不等于单 unit 内存硬上限。当前聚合一个 unit 的分页后写入，SQL batch 不改变事务边界。大范围运行须按[模板长任务合同](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)重新评估请求量、内存、取消及续跑证据，不沿用历史机器水位或容量假设。

## 6. 回归入口

[Express 专项测试](/Users/congming/github/goldenshare/tests/test_equity_express_dataset.py)覆盖：33 fields、自然日规划、366/367 边界、禁止 filters、逐页字段、后页失败、同批去重/冲突、新增/no-op/修订、范围回退、拒绝行、10,000 行合成容量和模型合同。

公共回归还需覆盖 schedule API/runtime、成功游标与失败取消、并发领取、catalog/freshness/卡片及前端策略参数。具体测试范围按代码改动选择，不把原历史测试数量当成今天必须重复执行的固定清单。生产迁移、部署、同步或 schedule 操作仍须独立授权。

<a id="express-history"></a>

## 7. 历史证据摘要：不是当前操作清单

### 7.1 2026-08-10 源端依据

- 普通 express 按单股请求；VIP 用于全市场。默认约 15 字段，显式 33 字段可返回；is_audit 出现 2，不能强制为布尔。
- ann_date=20250408/09/10 分别 14/11/9 行；区间并集为 34 行。period=20241231 为 1,409 行，500/500/409 分页键集合一致。
- 无参数宽范围记录为 29,590 行，5000×5+4590；不同字段组合曾出现分页重叠。该样本不能证明全历史完整，也不作为当前维护路径。

### 7.2 M1/M2：实现、配置事故与隔离验收

原 M1 验证记载后端 419 passed、1 deselected（当时已有进度标题 guardrail 冲突）、成功游标定向 5 passed、前端 138 passed。它们属于当时版本，不是当前测试基数。

**必须保留的配置事故**：M2 试图用环境变量 DATABASE_URL 指向隔离库，但 `GOLDENSHARE_ENV_FILE=.env.web.local` 的设置加载优先级覆盖了该地址，导致 Prod 提前应用迁移 000132。当时只读复核 Express 仍为 0 行、无该数据集 TaskRun/schedule，五个 relation 均在预期 tablespace；未调用源端、未写业务行。不能把误迁移算作隔离或生产验收通过，也未用 destructive downgrade 删表。

恢复时使用不加载生产地址的隔离配置，在同一进程同时校验应用解析的目标与数据库服务端 host/port/database；非隔离目标的负向样例在连接前拒绝。后续类似验收不能只看命令行变量。

原 M2 目标为 PostgreSQL 18.4、127.0.0.1:55410/goldenshare_express_m2：

- 隔离环境五个 relation 均显式在 gs_raw_cold_hdd；本机外置介质实际为 SSD，未将 tablespace 名称当成机械盘证明。
- 合成 10,001 输入，去重 1，插入 10,000；3.976 秒，验收进程峰值 RSS 448.12 MiB。RSS 含后续回滚样本构造，不是单 unit 增量或生产性能承诺。
- 第二批 INSERT 前故障注入后目标日期为 0 行；同公告日范围锁竞争返回 55P03；双会话 scheduler SKIP LOCKED 只创建一个 TaskRun。
- 对 20250408 仅请求两次，各 14 行；首次插入 14，再跑匹配 14、插入 0，身份/源指纹一致且 ingested_at 不变。
- Prod 前后 revision、Express 行数与任务指纹不变。本节不证明该临时环境今天仍存在，也不授权重建或安装环境。

<a id="206-m3-生产验收记录"></a>

### 7.3 M3：2026-08-11 生产验收

- 生产版本 55a460713725c50d6f33492f68a26b772f068336，迁移 000132；五个 relation 的实际冷盘路径为 /data/disk/postgresql/tablespaces/gs_stk_mins_hdd。
- 正式 TaskRun #7923 首次同步 2025-04-08：1/1 unit，读取/写入/拒绝/去重为 14/14/0/0；目标全表与身份数均为 14。
- #7928 幂等再跑成功：新增 0、匹配 14、目标仍 14；源指纹与 M2 已冻结证据一致，没有为对账再次请求源站。
- 内容指纹及包含 ingested_at 的指纹均未变化，原值如下：

```text
source_identity_content: bbd09c0b291d7c8128d3604cabdfe83a
with_ingested_at: a5931861d7b392ddf7f9c1548c7433a4
```

- TaskRun 页面 /app/ops/tasks/7923、数据源页 /app/ops/v21/datasets/tushare、卡片/freshness 验收通过，无伪 Raw 表；这是当时不可变写入版本的页面证据。
- 两次同步间等待其他任务完成，其中 **idx_factor_pro #7924 和 news #7925 均成功**；保留这项旁证供其他数据集引用，不替代它们自身完整验收。
- 地址误判、服务环境缺失等失败尝试均在写入前停止，最终使用与 Web 服务一致的配置并核验服务端目标。未修改 sudoers 或扩大配置权限。

### 7.4 M4a/M4b：2010 起历史回补

管理员选择 2010-01-01，不采用 1990 起点；截至 2026-08-10 按年度串行维护，每批正式 TaskRun 对账后才继续。M4a 未调用 Tushare；512 MiB HDD、2 GiB WAL 余量是当时压力假设和操作预留，不是长期性能阈值。旧磁盘水位与全系统空队列不作为今天的运行事实。

| TaskRun | 窗口 | unit/页 | 读取/写入 | 新增 | 匹配既有 |
| ---: | --- | ---: | ---: | ---: | ---: |
| 7957 | 2010 | 365 | 726 | 726 | 0 |
| 7959 | 2011 | 365 | 1,199 | 1,199 | 0 |
| 7961 | 2012 | 366 | 1,443 | 1,443 | 0 |
| 7962 | 2013 | 365 | 1,594 | 1,594 | 0 |
| 7963 | 2014 | 365 | 1,479 | 1,479 | 0 |
| 7964 | 2015 | 365 | 1,633 | 1,633 | 0 |
| 7965 | 2016 | 366 | 1,749 | 1,749 | 0 |
| 7968 | 2017 | 365 | 1,910 | 1,910 | 0 |
| 7969 | 2018 | 365 | 2,323 | 2,323 | 0 |
| 7970 | 2019 | 365 | 2,256 | 2,256 | 0 |
| 7974 | 2020 | 366 | 2,280 | 2,280 | 0 |
| 7975 | 2021 | 365 | 1,807 | 1,807 | 0 |
| 7976 | 2022 | 365 | 1,644 | 1,644 | 0 |
| 7977 | 2023 | 365 | 1,609 | 1,609 | 0 |
| 7978 | 2024 | 366 | 1,579 | 1,579 | 0 |
| 7979 | 2025 | 365 | 1,514 | 1,500 | 14 |
| 7980 | `2026-01-01..2026-08-10` | 222 | 1,226 | 1,226 | 0 |
| **合计** | `2010-01-01..2026-08-10` | **6,066** | **27,971** | **27,957** | **14** |

原汇总：17/17 TaskRun 成功，6,066/6,066 unit，每日第一页短页结束，实际 6,066 次页面请求；读取/写入 27,971，新插入 27,957、匹配 14，拒绝/去重/issue 为 0。目标 27,971 行及三元身份数一致，非空身份完整，实际记录 ann_date 为 2010-01-05～2026-08-08；请求日期窗口则完整覆盖至 2026-08-10。两者不能混淆。

该阶段没有创建 schedule、重部署、额外源扫描或直接清表；2010 年以前不属于批准范围。以上新增/匹配对账公式只解释当时的不可变 writer。

### 7.5 2026-08-11 M4c 配置记录及未闭环证据

当时 Schedule #35 已 active，cron 为北京时间工作日 20:03（3 20 * * 1,2,3,4,5），策略 since_last_success_day_range；管理员在 20:45 将 initial_start_date 从 2026-08-12 校正为 2026-08-11，与历史回补截止日连续。

截至该记录，尚未触发；当时预期 2026-08-12 20:03 首次创建 2026-08-11 单日窗口。原文没有补首次触发及五段对账结果，因此这里只保留“当时待验收”，不继续把过期触发时间写成今天下一步，也不猜测当前 schedule 状态或重复创建配置。

### 7.6 2026-08-29 修订覆盖收口

TaskRun #10110 的首日 2026-08-24 失败于旧 write.immutable_fact_conflict：同身份 300124.SZ / 2026-08-24 / 2026-06-30，已存 is_audit=2、源端改为 0，两次 update_flag 都为 0。由此确认需比较完整内容哈希，而非依靠 update_flag 判断是否修订。

当日已实现本文 §4 的当前版本覆盖，不改表、身份、日期、分页或自动策略；旧版内容不保留。当日状态记录为“已实现、待部署”，原范围 2026-08-24～2026-08-31 可在部署确认后由运营重新提交。本文没有新的部署/重跑证据，不将它们升级为已完成，也不授权立即重跑。

## 8. 文档维护边界

现行规则只在 §1–6 维护；§7 保留事故、关键决策、验收与未闭环证据，旧逐步操作全文通过 Git 追溯。代码变更须同步本文件并重新选择所需验收；应用回滚不删除业务事实，迁移、数据清理和自动任务配置不随文档优化执行。
