# Tushare 每日涨跌停价格（`stk_limit`）数据集开发说明

- 状态：现有数据集已运行；`P1-B4-stk_limit-M0/M1/M2/M3a/M3b` 全部通过并结案，生产已 raw 直出
- 更新时间：2026-08-31
- 专项依据：[生产 PostgreSQL raw 直出一期低层设计 v1](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-raw-direct-serving-phase-one-lld-v1.md)

## 1. 目标与边界

- 既有目标：完成 Tushare 接口拉取、`raw_tushare` 落库、`core_serving` 对外服务与 Ops 运维打通。
- 当前治理目标：在保持原 `core_serving.equity_stk_limit` 读取名称和业务字段不变的前提下，把重复物理存储收敛为 Raw 唯一物理事实表与只读 Serving view。
- 既有运行边界：
  - 纳入现有工作流 `daily_market_close_maintenance`（收盘后自动流程覆盖）。
  - 维护动作必须显式传时间参数（`trade_date` 或 `start_date+end_date`），禁止“无时间全量”。

## 2. 上游接口

- 文档：<https://tushare.pro/document/2?doc_id=183>
- API：`stk_limit`
- 描述：获取全市场每日涨跌停价格（A/B 股与基金）。
- 限制：单次最多约 5800 行，支持循环调取。

## 3. 参数与字段

### 3.1 输入参数（上游）

- `ts_code`（可选）
- `trade_date`（可选）
- `start_date`（可选）
- `end_date`（可选）
- `limit`（可选）
- `offset`（可选）

### 3.2 本期运维参数策略

- `stk_limit.maintain`：`trade_date` 或 `start_date+end_date`，可选 `ts_code`
- 维护动作禁止无时间参数启动。

### 3.3 输出字段（全量落库）

- `trade_date`
- `ts_code`
- `pre_close`
- `up_limit`
- `down_limit`

## 4. 落库设计

### 4.1 原始层

- 表：`raw_tushare.stk_limit`
- 主键：`(ts_code, trade_date)`
- 字段：`pre_close`, `up_limit`, `down_limit`
- 审计字段：`api_name`, `fetched_at`, `raw_payload`
- 索引：`idx_raw_tushare_stk_limit_trade_date(trade_date)`

### 4.2 服务层

- 读取名称：`core_serving.equity_stk_limit`
- M1/M2 已验证合同：revision `20260830_000162` 应用后成为显式 Raw-backed 只读 view；生产在 M3a 前仍是原物理表
- 主键：`(ts_code, trade_date)`
- 字段：`pre_close`, `up_limit`, `down_limit`
- 系统字段：`created_at`, `updated_at` 均由 Raw `fetched_at` 投影
- 查询索引：下推到 Raw 的 `idx_raw_tushare_stk_limit_trade_date(trade_date)` 与主键；view 自身不再拥有索引或主键

## 5. 同步实现策略

### 5.1 单日维护（point）

- 必传 `trade_date`。
- 按单交易日请求，使用 `limit/offset` 分页拉取直至无数据。

### 5.2 日期范围维护（range）

- 允许：
  - 单日（`trade_date`）
  - 区间（`start_date+end_date`）
- 区间模式按交易日历扇出到每日（非一把区间请求），每个交易日内部再分页，避免单次返回上限导致截断。
- 若区间内无交易日，返回可读提示，不报错中断。

## 6. Ops 打通

- DatasetDefinition action：
  - `stk_limit.maintain`
- Freshness 元数据：
  - `dataset_key`: `stk_limit`
  - `display_name`: `每日涨跌停价格`
  - `domain`: `equity_market / 股票行情`
  - `observed_date_column`: `trade_date`

## 7. 测试覆盖

- `tests/test_dataset_definition_registry.py`
  - Definition、目标表与日期主体完整性事实
- `tests/test_ops_action_catalog.py`
  - action catalog 与工作流步骤
- `tests/test_fields_constants.py`
  - `STK_LIMIT_FIELDS` 常量覆盖
- `tests/test_extended_models.py`
  - Raw/Serving 主键与索引
- `tests/test_ops_freshness_snapshot_query_service.py`
  - freshness target 投影
- `tests/web/test_ops_date_completeness_api.py`
  - 日期主体矩阵审计
- `tests/architecture/test_dataset_runtime_registry_guardrails.py`
  - Definition/runtime registry 边界
- `tests/test_stk_limit_raw_view_m1.py`
  - storage-only Definition、`ts_code` filter、5,800 行分页逐页显式 fields、Raw-only writer、模型/索引、ServingPublish 旁路、migration SQL 和禁止自动 downgrade

M1 已独立固化 `_stk_limit_params` 的 resolver 结果、5,800 行分页逐页 fields 与 Raw-only writer；生产历史 TaskRun 只作为 M0 源端行为证据，不替代自动化门禁。

## 8. `P1-B4-stk_limit-M0` 只读复审与 M1 准入合同（2026-08-29）

本阶段只读取当前代码、CodeGraph、生产 PostgreSQL catalog、汇总数据、查询计划和既有 TaskRun 诊断。没有修改代码或生产配置，没有部署、migration、暂停 schedule、创建 TaskRun、调用 Tushare 或写业务数据。

1. 当前 Definition 显式请求全部 5 个源字段：`trade_date, ts_code, pre_close, up_limit, down_limit`。point/range 由交易日历展开为逐交易日 unit，request builder 每个 unit 只生成 `trade_date` 和可选 `ts_code`；source client 每一页都传完整 `source_fields`，按 `offset/limit=5800` 请求，只有短页才结束，没有任意最大页数。生产 schedule #24/#2 对 `2026-08-28` 的两个自然 node 均执行 `5800+1968=7768` 两页，最终短页、无截断、重试、reject 或去重；M0 没有重复请求 Tushare。
2. 当前 storage 仍是 `raw_stk_limit + equity_stk_limit + raw_core_upsert`。共享 writer 对同一 normalized batch 仅按两套 ORM 列过滤后分别 upsert，未发现 Serving 专属转换、过滤、聚合、冲突消解、`ServingPublish` mapping 或显式 Serving DML 旁路。M1 只允许修改本数据集 storage delivery，不改 resolver、request builder、normalizer、source client、分页、日期模型、filter、工作流或共享 writer。
3. 生产为 PostgreSQL 16.13、revision `20260829_000161`。Raw/Serving OID 为 `21604/21614`，均由 `goldenshare_user` 持有，都是 SSD `pg_default` 普通物理表；Raw 总大小 `661,782,528 B`，Serving 总大小 `664,354,816 B`（633.58 MiB），后者是当前可释放 catalog 毛量。两层 5 个业务列的名称、顺序、类型和 nullability 一致，主键都是 `(ts_code, trade_date)`，并各有等价 `(trade_date)` 索引；四个索引全部 valid/ready 且位于 `pg_default`。
4. Raw 独有 `lake_raw_reader SELECT`，Serving 只有 owner 权限；relation/column comments 均为空。未发现非主键约束、外键、用户 trigger、RLS/policy、外部 view/materialized view、function dependency或仓库内旁路写入。M0 时没有开放 TaskRun、目标 relation 锁或超过 30 秒的事务。
5. Raw/Serving 各 `4,608,112` 行和同数唯一 `(ts_code, trade_date)`，日期范围均为 `2024-01-02..2026-08-28`，空身份与异常 Raw `api_name` 均为 0。32 个自然月逐月比较全部 5 个业务字段，Raw-only/Serving-only 差异全部为 0；最大业务行宽 61 B。
6. 自然月峰值为 `2026-07` 的 177,009 行。独立 migration 的容量门禁固定为 **220,000 行/层/月**：按实测峰值上浮约 20% 后向上取整；M2 必须证明 220,000 行通过、220,001 行在任何 Serving DDL 前 fail-closed。迁移继续使用 `work_mem=16MB`、`statement_timeout=300s` 按自然月有界对账，禁止无界全表差集，也不得复制其它数据集的行数阈值。
7. Raw `fetched_at` 与 Serving `updated_at` 对全部 4,608,112 行一致；514,328 行历史 `created_at` 与 `fetched_at` 不同。仓库内没有发现 `EquityStkLimit.created_at/updated_at` 消费者，因此 view 继续采用一期固定投影 `fetched_at AS created_at/updated_at`，但只承诺已登记消费者的 5 个业务字段透明，不承诺历史 `created_at`、relation OID/relkind 或约束 catalog 透明。
8. 仓库内 Serving 业务消费者只有 `MarketMoodCalculator` 的日期范围复合键外连接，以及 `MarketMoodWalkForwardValidationService` 的按交易日存在性检查；对应入口是 Ops CLI 走查与集成测试，没有发现前端、QTF 或 DG 直接读取 Serving。Lake Console 已显式从 Raw 导出同一 5 字段。代表查询结果由全量等价和相同 join key 保证一致；计划分别命中两层等价日期/主键索引。20 日市场情绪 join 的 Raw/Serving 单次执行约 `628.8/657.1 ms`；64 个交易日存在性查询交错热样本中位约 `0.849/0.770 ms`，Raw 退化约 10.3%，低于本项 20% 停止线。两层 all-visible 为 93.91%/94.28%，没有先执行 vacuum 的依据。
9. 自动入口不是一个 schedule：同一个 `daily_market_close_maintenance` workflow 当前有 schedule #24（工作日 18:30）和 #2（工作日 21:02），`stk_limit` 是第 9 个 step。M3a 必须同时暂停并原样恢复二者，停止 scheduler 与会领取该 workflow 的 generic worker；M3b 必须在切换后的首个自然交易日分别核验两个父任务内的 `stk_limit` node，不允许用其中一个替代另一个。M0 快照时二者下一次分别为 `2026-08-31 18:30/21:02+08`。
10. M1 只允许：把 Definition storage 改为 `raw_stk_limit` 双 DAO 名、`raw_tushare.stk_limit` target、`raw_with_serving_view / raw->serving_view / raw_only_upsert`；新增接编码时真实 Alembic head 的独立 migration；新增专项与共享回归测试。Raw ORM 已声明生产现有 `(trade_date)` 索引，不需要补 ORM 索引，不得创建、重建或移动 Raw 表/索引。
11. migration 必须在所有 Serving DDL 前校验 relation/owner/SSD/列/主键/索引/ACL/comments/依赖及 220,000 行月容量；按 Raw `SHARE` → Serving `SHARE` → 32 月身份和五字段双向差集 → Serving `ACCESS EXCLUSIVE` 的顺序执行。view 只能显式投影 `ts_code, trade_date, pre_close, up_limit, down_limit, fetched_at AS created_at, fetched_at AS updated_at`，恢复 metadata 并挂本 view 独立三类 DML 拒写 trigger；禁止 `CASCADE`、Raw DDL/DML、共享函数重建和自动 downgrade。

结论：`P1-B4-stk_limit-M0` **通过**，具备 M1 编码准入。M1 仍需单独授权；本结论不授权隔离 PostgreSQL、生产 migration、TaskRun、schedule 修改或任何 Tushare 请求。仓库外 SQL、BI、人工脚本和依赖 OID/relkind/catalog/历史 `created_at` 的工具仍是残余运营风险。

## 9. `P1-B4-stk_limit-M1` 实现与验证（2026-08-30）

M1 严格限定为代码、独立 Alembic revision、测试和文档；没有连接 PostgreSQL、应用 migration、部署、创建 TaskRun、修改 schedule 或请求 Tushare。

1. `DatasetDefinition` 只修改 storage delivery：`raw_dao_name/core_dao_name` 均为 `raw_stk_limit`，`target_table=raw_tushare.stk_limit`，`delivery_mode=raw_with_serving_view`，`layer_plan=raw->serving_view`，`write_path=raw_only_upsert`。五个 source fields、日期模型、point/range、可选 `ts_code`、5,800 行分页、能力和工作流未修改。
2. 独立 revision `20260830_000162` 接编码时真实 head `20260829_000161`。它不创建或修改 Raw 表/索引，不触碰 Raw 数据；所有 Serving DDL 前先校验双方物理关系、owner、列、主键、唯一一个日期二级索引、Raw SSD tablespace、Raw `lake_raw_reader SELECT`、Serving ACL/comment、依赖和每层每月 220,000 行上限。
3. migration 锁序固定为 Raw `SHARE` → Serving `SHARE` → 自然月身份和五业务字段双向 `EXCEPT ALL` → Serving `ACCESS EXCLUSIVE`。切换只执行无 `CASCADE` 的 Serving table 删除与同名显式 view 创建；投影严格为 `ts_code, trade_date, pre_close, up_limit, down_limit, fetched_at AS created_at, fetched_at AS updated_at`，复用既有受保护拒写函数并为本 view 创建独立三类 DML trigger。自动 downgrade 明确禁止。
4. freshness 与日期主体完整性继续由 Definition 派生，但物理审计目标改为 `raw_tushare.stk_limit`；Biz 两个市场情绪消费者仍通过原 `EquityStkLimit` ORM 读取 `core_serving.equity_stk_limit`，无需改消费者代码。
5. 专项测试覆盖 storage-only 变更、未知 filter 拒绝、Raw/Serving 五字段类型与索引、ServingPublish 不存在、每页完整 fields、`5800+1` 短页结束、Raw-only writer 不调用 Serving DAO、migration 顺序/禁止项/offline SQL 和 downgrade 拒绝；共享测试覆盖 registry、freshness、日期主体矩阵、resolver 与架构边界。

结论：`P1-B4-stk_limit-M1` **通过**，下一步只能在独立授权后进入 M2。M1 只证明代码合同和静态/自动化门禁，不代表 migration 已在任何 PostgreSQL 实例应用，也不代表生产已释放空间。

## 10. `P1-B4-stk_limit-M2` 隔离 PostgreSQL 验收（2026-08-30）

M2 在本轮创建的 PostgreSQL 18.4 一次性实例执行。实例只监听 `/private/tmp` 下随机 Unix socket，`listen_addresses=''`、`inet_server_addr()` 为空；应用角色 `stk_limit_m2_app` 为非超级用户，也没有建库、建角色或复制权限。每次 Alembic 前都通过只含目标 URL 的独立 env 文件核对数据库、用户、socket、端口、恢复状态和 data directory，未读取仓库 `.env.web.local`。本轮没有连接 Prod、请求 Tushare、部署、创建 TaskRun 或修改 schedule/workflow。

1. 220,000 行单月正向边界库成功从 revision 161 升级到 162。Raw relation OID 与主键/日期索引 OID、定义、valid/ready 状态全部保持不变并留在 `pg_default`；Serving 成为 0 B 普通 view。Raw/view 均为 220,000 行和 220,000 个唯一身份，五业务字段双向差异及 `fetched_at -> created_at/updated_at` 投影差异均为 0。
2. Raw 的 `lake_raw_reader SELECT`、Serving reader 的 `SELECT WITH GRANT OPTION`、owner、relation/column comments 和独立 DML trigger 全部恢复。Serving `INSERT/UPDATE/DELETE` 均返回 SQLSTATE `55000`；Raw 插入、更新、删除立即由 view 可见且事务回滚后无残留。
3. 正式 `DatasetWriter` 只写 `raw_tushare.stk_limit`，在同一事务内可从 view 读到更新值和时间戳；回滚后 Raw/view 都恢复原值，报告目标表和保存行数分别为 `raw_tushare.stk_limit`、1。
4. 220,001 行、业务字段差异、身份差异、Raw 列类型漂移、未知依赖、缺失 Raw 日期索引和额外 Raw ACL 七类负向场景全部在 Serving DDL 前失败；revision、relation/OID、索引、列、ACL、comments、trigger 和行数快照均保持不变。另一个数据库在完成 `DROP TABLE -> CREATE VIEW -> trigger` 后注入错误，事务完整回滚到 revision 161 和原两张物理表。
5. 20 日市场情绪复合键 join 与按交易日存在性查询在切换前后结果行数和 hash 一致，切换后分别下推 Raw 主键和 `idx_raw_tushare_stk_limit_trade_date`，无临时块。隔离样本耗时约为 `0.214 -> 0.194 ms`、`0.069 -> 0.062 ms`，只作为计划与索引形态证据，不替代生产 SLA。

隔离实例已停止，临时数据目录已删除；完整报告保留在 `/private/tmp/goldenshare_stk_limit_m2_report.json`。`P1-B4-stk_limit-M2` **通过**，revision 162 和业务代码无需修改。生产仍为 revision 161、Raw/Serving 双物理表和旧双写部署，尚未释放 664,354,816 B；下一阶段只能在独立授权后进入生产 M3a。

## 11. `P1-B4-stk_limit-M3a` 生产即时验收（2026-08-30）

M3a 于 `06:50..06:59+08` 按维护窗口顺序完成。生产切换、即时查询与唯一一次受控 TaskRun 均通过；没有创建额外 workflow、历史任务或 schedule，也没有重复执行失败任务。

1. 实时预检确认 PostgreSQL 16.13、revision 161、远端旧 commit `dc191135`。Raw/Serving 均为 SSD `pg_default` 物理表，各 4,608,112 行和同数身份，日期范围 `2024-01-02..2026-08-28`；32 个自然月五字段双向差异为 0，月峰值 177,009，低于 220,000 停止线。开放 TaskRun、目标 node、完整性审计 run、目标锁、等待锁和超过 30 秒事务均为 0；根盘可用 53,501,075,456 B。
2. schedule #24/#2 通过正式 `OpsScheduleCommandService` 分别暂停，config revision `131/132` 留痕；cron、时区、next/last timing 均未被改写。scheduler 与 generic worker 逐个停止并回查后，32 月锁前最终对账仍为 4,608,112/4,608,112、五字段差异 0。
3. `--maintenance-migration` 只拉取并安装包含 M1/M2 的 `da84a32a`，应用 revision `161→162`；前端/Wealth 构建、seed、unit 同步、TaskRun 创建和服务自动恢复全部跳过。Raw relation OID `21604`、主键/日期索引 OID `21611/21613` 保持不变且继续位于 SSD；Serving 变为 OID `2041913` 的 0 B view，确定性 catalog 毛释放量为原 Serving relation 的 664,354,816 B。
4. view 显式投影 5 个业务字段与 `fetched_at AS created_at/updated_at`；owner、Raw `lake_raw_reader SELECT`、Serving ACL 和独立拒写 trigger 正确。Raw/view 全表行数、身份、日期范围、32 月五字段与审计时间投影全部一致；Serving `INSERT/UPDATE/DELETE` 均以 SQLSTATE `55000` 拒绝，回滚测试行残留为 0。
5. 20 日市场情绪 join 与 64 日日期存在性查询的 Raw/view 结果 hash 一致。切换后 view 被优化器下推到 Raw；20 日 join 约 575 ms，相对切换前 Serving 约 567 ms 为约 1.5% 波动；64 日存在性约 0.76 ms，使用 `idx_raw_tushare_stk_limit_trade_date`，均无临时块或超过 20% 的结构性退化。
6. Web、日期完整性 worker、TaskRun 收尾 worker 与 generic worker 逐个回收连接池后，通过正式 `ManualActionCommandService → DatasetActionResolver → TaskRun` 创建唯一 TaskRun `10182`，目标为 point `2026-08-28`。第一次远端 Python 命令在解释阶段因引号错误失败，服务方法没有执行；回查 TaskRun 最大 ID 和开放任务确认没有创建任务或请求 Tushare 后，才执行正式创建。
7. TaskRun `10182` 为 `success`、`1/1/0`；源端两页 `5800+1968`、terminal offset 5,800、最终短页、无截断和重试。读取/保存 `7,768/7,768`，reject、去重均为 0。Raw/view 当日各 7,768 行和身份，五字段差异 0；7,768 行的 `fetched_at` 全部位于 node `15895` 的执行窗口内，全表仍为 4,608,112 行，证明已有日期重跑幂等。
8. schedule #2/#24 经 config revision `133/134` 原样恢复 active，下一次仍分别为 `2026-08-31 21:02/18:30+08`；scheduler 恢复后开放任务、目标 node、完整性审计 run、目标锁、等待锁和长事务均为 0。Web、generic worker、scheduler、日期完整性、TaskRun 收尾、两类分钟线、QTF 与 realtime 服务全部 active，两个健康端点正常；终态根盘可用 55,182,610,432 B，文件系统瞬时变化不作为确定性释放量。
9. 维护期间远端在 `06:56:04+08` 另有一次 fast-forward 到 `4e54dec8`。该提交是 `da84a32a` 的后继，只新增/更新 8 份财务数据集文档，没有修改代码、migration、Definition 或运行契约；本并发事实保留在验收记录中，但不改变本项结论。

`P1-B4-stk_limit-M3a` **通过**。生产现为 revision 162、Raw 唯一物理事实表和 0 B Serving view。`P1-B4-stk_limit-M3b` 已登记为后续 TODO：必须分别核验 `2026-08-31 18:30+08` 的 schedule #24 与 `21:02+08` 的 schedule #2 父 TaskRun 中 `stk_limit` node；不得用一个自然入口替代另一个，也不得为 M3b 创建额外任务或重复请求源端。

## 12. `P1-B4-stk_limit-M3b` 双自然工作流验收与结案（2026-08-31）

1. schedule #24 于 `18:30+08` 创建 TaskRun `10343`，父任务为 `success`。目标 node `16064` 成功处理 `2026-08-31`，两页为 `5,800+1,968`，最终短页结束；读取/保存 `7,768/7,768`，reject、去重、重试均为 0，未截断。父任务中的 `irm_qa_sh` 有 1 行独立 reject，不属于本节点。
2. schedule #2 于 `21:02+08` 创建 TaskRun `10371`。父任务因无关的 `anns_d` 节点失败而是 `partial_success`，但目标 node `16135` 独立为 `success`，同样两页 `5,800+1,968`、读取/保存 `7,768/7,768`，reject、去重、重试为 0，未截断。
3. 最终目标日 Raw/view 各 7,768 行和 7,768 个唯一 `(ts_code, trade_date)`；五个源业务字段双向差异为 0，Raw 7,768 行的 `fetched_at` 全部位于第二个 node 执行窗口内。两次自然执行结果相同且最终行数未增加，证明同日重跑为幂等刷新。
4. 两个自然入口均已分别闭环，没有用一个父任务替代另一个，也没有创建额外 TaskRun、重复源端请求或修改 schedule。`irm_qa_sh` reject 与 `anns_d` 失败作为独立 TODO 保留，不重新打开本数据集结论。

`P1-B4-stk_limit-M3b` **通过**。本数据集 M0/M1/M2/M3a/M3b 全部完成并结案。
