# 公募基金 B4：基金分红（`fund_div`）低层设计 v1

状态：**B4-FD-M0/M1/M2/M3 已完成；隔离与生产 migration/HDD placement、正式 TaskRun 首次同步、幂等重跑及完整对账均通过。历史回补与 schedule 仍未授权**
编写日期：2026-08-07
适用范围：`fund_div / 基金分红` 接入 Goldenshare Prod

## 1. 结论先行

`fund_div` 应设计成“按公告自然日维护的全市场不可变事件事实”：运营可输入一个 `ann_date`，也可输入自然日起止范围；range 在平台内部逐日展开。每个公告日完成全部分页、归一化、去重和既有事实对照后，在一个事务内只插入尚不存在的新事实，不更新或删除旧事实。

业务已确认：正式修订会重新发布一条公告，而不是原地改写旧公告。新公告以新的 `ann_date` 和事件身份插入事实表，旧公告永久保留。因此本数据集采用 **immutable fact ledger**：只建立 `core_serving.fund_div`，不建立 current 或 observation 表。若同一 `source_entity_key` 后续出现不同内容，系统必须失败并报告源端违反不可变契约，禁止覆盖旧事实。

下列口径已经有源端与当前代码证据，可以冻结：

1. 每页显式请求并保存全部 16 个 Tushare 字段。
2. 主请求只传一个 `ann_date`；不使用 `ex_date/pay_date/ts_code` 缩小全市场作用域。
3. 日期范围逐自然日展开，不能只走交易日；源端与目标 scope 均为空的真实空公告日是合法 no-op。
4. 分页使用 `offset_limit`、`page_limit=2000`、短页结束、无任意最大页数，并发 1。
5. direct-serving immutable fact；无 raw/std/EAV/JSON，也无 current/observation 表。
6. 业务表、主键索引和二级索引全部落 `gs_raw_cold_hdd`；共享 WAL 保持 SSD。
7. Ops 归入“公募基金”，支持手动、普通 cron/once 与 retry；无 probe、无 workflow、无自动 schedule seed。

历史源端存在 16 字段完全相同的重复行。业务已拍板：完全重复只保留一条业务事实，不保存逐行 `source_occurrence_count`，也不生成平台 occurrence 身份。运行级 `rows_deduplicated` 只用于解释“源端行数与唯一事实行数”的差额，不进入业务表。不可变事实、单表直出与去重口径已在 B4-FD-M1 按本文实现；真实 PostgreSQL/HDD/源端同步结论仍必须由 M2 独立验证。

## 2. 目标、范围与明确不做

### 2.1 本 LLD 目标

- 固定源端参数、显式字段、分页与完整性契约；
- 分开说明时间输入、执行 unit、freshness/audit 三层语义；
- 给出 Definition、planner、request builder、normalizer、writer、表、DAO、HDD migration、Ops/UI 和测试的准确落点；
- 审计 `fund_share` 已有共享能力是否真正适用，避免新增基金分红专用框架；
- 固定 exact duplicate 去重、不可变插入、源端回退防护、对账和验收口径。

### 2.2 B4-FD-M1 明确不做

- 不应用任何 migration，不连接或写入隔离/生产 PostgreSQL；
- 不创建、修改或触发 TaskRun、workflow、probe、schedule；
- 不执行隔离库或生产库写入；
- 不执行生产 migration、首次同步或历史回补；
- 不建设 `ts_code` 单基金精确修复；
- 不拍板实际 cron 时刻、D/D-1 或滚动修订窗口；
- 不把 `fund_div` 放入 Lake/Dagster。

## 3. 依据与当前基线

### 3.1 文档依据

- [数据集开发模板](../templates/dataset-development-template.md)
- [基金分红源文档](../sources/tushare/公募基金/0120_公募基金分红.md)
- [基金分红发现审计](fund-div-onboarding-discovery-audit.md)
- [公募基金九数据集总计划](public-fund-nine-dataset-onboarding-program-plan-v1.md)
- [B4 基金规模 LLD](public-fund-b4-fund-share-low-level-design-v1.md)
- [Dataset 日期模型消费者指南](../architecture/dataset-date-model-consumer-guide-v1.md)
- [DatasetDefinition 单一事实源方案](../architecture/dataset-definition-single-source-refactor-plan-v1.md)
- [DatasetExecutionPlan 方案](../architecture/dataset-execution-plan-refactor-plan-v1.md)

### 3.2 当前代码依据

CodeGraph 与逐文件核验覆盖：Definition/registry、validator/resolver、unit planner、request builder、source client、normalizer、writer/DAO、model/DAO registry、migration、Ops Catalog、手动任务、schedule capability、TaskRun、workflow/probe、freshness/audit 和前端时间表单。

可复用主链：

```text
DatasetDefinition
  -> validator / resolver
  -> build_natural_day_point_units
  -> fund_div 专用 request builder（只生成 ann_date）
  -> offset_limit source client（每页显式 fields）
  -> normalizer / exact duplicate deduplication
  -> serving_immutable_fact_insert
  -> ImmutableFactDAO（scope 加锁、既有身份/内容核验、只插入新事实）
  -> core_serving.fund_div
```

编码前 Alembic head 在 2026-08-07 只读核验为 `20260807_000128`。M1 已据此生成线性 revision：`20260807_000129` 增加有界 ingestion diagnostics，`20260807_000130` 增加 `core_serving.fund_div`；本地 migration graph 当前唯一 head 为 `20260807_000130`。本轮没有应用 migration，数据库真实 head、HDD placement 与升级原子性仍由 M2 核验。

工作区已有与本专项无关的脏文件，本轮不得触碰或纳入提交。

## 4. 源端契约复审

### 4.1 输入参数矩阵

| 形态 | 当前实测 | 设计结论 |
| --- | --- | --- |
| 无参数 | `50101`，四个参数至少一个 | 无法做无参快照。 |
| `ann_date` | 单公告日全市场 | 主执行参数。 |
| `ts_code` | 单基金跨公告日历史 | 只用于源端 A/B；首版不暴露。 |
| `ex_date` | 一个除息日聚合多个公告日 | 不作为完整维护 unit。 |
| `pay_date` | 一个派息日聚合多个公告日 | 不作为完整维护 unit。 |
| 多参数 | 按 AND 缩小结果 | 局部结果不得冒充完整公告日集合。 |
| `start_date/end_date` | 不支持 | range 只能由 planner 扇出。 |

`ex_date/pay_date` 不是额外完整性通道。抽样结果中的每条记录都能在其 `ann_date` 全市场结果中复现；若同时维护多个日期轴，会产生重叠请求和无法证明完整性的局部集合。

### 4.2 默认、显式与关键字段矩阵

固定 `source_fields`：

```text
ts_code, ann_date, imp_anndate, base_date, div_proc, record_date,
ex_date, pay_date, earpay_date, net_ex_date, div_cash, base_unit,
ear_distr, ear_amount, account_date, base_year
```

| 验证组 | `20260617` | `20201215` | 结论 |
| --- | ---: | ---: | --- |
| 默认字段 | 122 | 141 | 当前默认返回 16 字段。 |
| 显式 16 字段 | 122 | 141 | 与默认行多重集一致。 |
| 业务关键字段 | `ts_code/ann_date` 均非空；其他字段存在 null | 同左 | 不能因默认返回完整而省略 `fields`。 |

所有 16 个字段都是源事实，必须进入 Definition、归一化、ORM、migration、DAO 和对账；不能只保留页面展示字段。

### 4.3 分页

| 公告日 | `limit=50` 分页 | 不分页 | 多重集差异 |
| --- | --- | ---: | ---: |
| `20260617` | 50 / 50 / 22 / 0 | 122 | 0 |
| `20201215` | 50 / 50 / 41 / 0 | 141 | 0 |

MCP schema 未公开 `limit/offset`，但运行时和项目 connector 实测生效。该差异必须保留在源文档。实现契约为：

- `pagination_mode=offset_limit`；
- `page_limit=2000`；
- 每页都传完全相同的 16 个 `fields`；
- 满页后 offset 按固定 `page_limit` 递增；短页直接结束；
- 短页才结束；
- 不设置最大页数；
- 任一页失败则整个公告日 unit 失败，不得发布部分结果。

### 4.4 全市场与 `ann_date` 主轴

- `20260617` 共 122 行：OF 116、SZ 2、SH 4；所有市场后缀都必须保留。
- `000001.OF` 的 29 行历史，与其 25 个公告日全市场结果筛选后的多重集完全一致。
- `500001.SH` 的 12 行历史，与其 10 个公告日全市场结果筛选后的多重集完全一致。
- `ex_date=20260617` 的 130 行、`pay_date=20260618` 的 137 行，均能在各自公告日结果中复现。

这是有界 A/B 证据，不是源端永久 SLA。M2 最小真实同步仍须保留 A/B 差集验收。

### 4.5 自然日、空日与发布时间

- 周六 `20260613` 返回 40 行；周六 `20070414` 返回 7 行；
- `20260614` 返回 0 行；
- 2026-08-07 15:26 实测，`20260807` 当日已经有 3 行，但尚不能证明当日已完整。

因此：

1. range 必须逐自然日，不能改为交易日或工作日；
2. 首次读取为空且目标 scope 也为空时成功 no-op，不产生缺数告警；若目标已有事实则按源端回退失败；
3. 自动任务不能仅凭一次下午样本就拍板“当日一次请求足够”；
4. 首个 schedule 前必须做多时点发布/修订观察。

### 4.6 历史边界、请求量与性能

- 当前实测最早公告日候选：`19990329`；
- 安全历史扫描起点建议：当前最早基金成立日 `19980327`；
- 到 2026-08-07 约 10,000 个自然日基础 unit；
- 按当前 32,356 只基金逐只拉历史，至少需要 32,356 个起始请求，因此不作为全市场主路径；
- 当前抽样单日峰值为 160 行，不能外推为永久峰值；
- source client 当前会把单个公告日全部页先累积到内存，再统一归一化和写入。

工程验收使用 10,000 行合成单日作为容量门禁，约为当前抽样峰值的 62.5 倍；它是回归标准，不是源端 SLA。历史年度行数、总分页数、实际耗时、积分/限流、HDD/索引/WAL 水位在 B4-FD-M4a 单独只读测算。

源文档要求至少 400 积分。本轮研究凭据已能成功调用，只能证明当前审计环境具备权限，不能替代隔离/生产凭据预检。当前代码对 `fund_div` 没有接口专属限速，使用 `TUSHARE_MAX_CALLS_PER_MINUTE=280` 的默认值；若每个自然日仅一页，366 个串行请求的纯限速理论下界约 78.4 秒，尚未计网络、重试、归一化和事务时间。M2/M3 分别用对应环境凭据验证接口权限；真实年度请求量、耗时与资源水位属于 M4a 历史预算，不得在 M2 最小同步中越权执行，也不得把理论下界当成 SLA。

## 5. exact duplicate：已拍板为唯一事实去重

### 5.1 不是短键误判

`20260617` 中，`159816.SZ` 两行的短日期键相同，但 `net_ex_date/base_unit` 不同；完整事件日期签名能够区分，必须保存两行。

### 5.2 16 字段完全相同的重复

| 公告日 | 源行 | 完整唯一行 | exact duplicate 额外行 |
| --- | ---: | ---: | ---: |
| `20191104` | 12 | 6 | 6 |
| `20201215` | 141 | 74 | 67 |
| `20211215` | 160 | 82 | 78 |
| `20230110` | 36 | 21 | 15 |
| `20260617` | 122 | 122 | 0 |

`20201215` 连续三次请求均为 141 行/74 个完整唯一行，67 个重复组各出现两次。分页后的多重集也与不分页一致，因此不能把它解释成客户端翻页重叠。

### 5.3 固定处理口径

对一个公告日的完整分页结果，先用全部 16 个归一化源字段计算稳定 `source_row_hash`：

- `source_row_hash` 完全相同：只保留一条业务事实；
- 不保存 `source_occurrence_count`；
- 不生成 `source_occurrence_no`；
- 不依赖源返回顺序、页号或 row index；
- exact duplicate 不计 reject；
- 运行级记录 `rows_deduplicated`，只为对账和 Ops 解释，不进入 `core_serving.fund_div`。

固定对账恒等式：

```text
source_rows_fetched
  = normalized_unique_rows
  + rows_deduplicated
  + rows_rejected
```

以 `20201215` 首次同步为验收样本：`141 = 74 + 67 + 0`，成功确认保存 74 条唯一事实，目标日期范围内为 74 行。完全重复的两行没有可区分字段，保留一条不会丢失可用业务信息；源端重复次数仅在本次运行汇总中体现，不成为可查询的业务事实。

禁止把 exact duplicate 计为 reject、为副本制造 occurrence 身份，或沿用 B0 当前“批内重复实体即失败”的默认行为。

## 6. 三层时间语义

### 6.1 时间输入语义

| mode | 运营输入 | 含义 |
| --- | --- | --- |
| point | `ann_date` | 维护一个公告自然日的全市场记录。 |
| range | `start_date/end_date` | 维护闭区间内每个公告自然日。 |

不支持 no-time，不暴露 `ts_code/ex_date/pay_date` filters。

### 6.2 执行 / unit 语义

- 一个 unit = 一个 `ann_date` 的完整分页多重集；
- range 按自然日升序展开；
- 一个 unit 一个事务；
- 单 unit 并发锁作用域是 `fund_div + ann_date`；
- 任一页失败、任一字段缺失、跨日行、不可解释身份冲突或数据库失败，整个 unit 回滚；
- exact duplicate 按拍板后的策略处理，不算普通 reject。

### 6.3 freshness / audit 语义

- `date_axis=natural_day` 只描述输入与 unit 日期；
- `bucket_rule=not_applicable` 表示不按连续自然日判断“应该有数据”；
- `audit_applicable=false`；
- dataset card 使用事件运行轨迹，不把空公告日显示为缺数；
- 不进入 date completeness audit 或 snapshot rebuild 连续日期逻辑。

`not_applicable` 不等于无日期输入；本数据集明确支持公告日 point/range。

## 7. `DatasetDefinition` 设计

目标文件：`src/foundation/datasets/definitions/public_fund.py`。

| 契约段 | 固定设计 |
| --- | --- |
| identity | `dataset_key=fund_div`，`display_name=基金分红`，`domain_key=public_fund`，`source_api=fund_div` |
| source | 显式 16 字段；`offset_limit`；`page_limit=2000`；每页 fields；无最大页数 |
| date_model | `natural_day / not_applicable / point_or_range / ann_date_or_start_end / observed_field=ann_date / audit=false` |
| input | `ann_date,start_date,end_date`；无 filters |
| execution | `build_natural_day_point_units`；并发 1；range 自然日扇出 |
| normalization | 9 个 DATE 字段按当前日期规范归一化；`base_year` 保持 TEXT；4 个精确数值；fund_div 身份 transform；exact duplicate 按 16 字段去重 |
| storage | `serving_immutable_fact_insert`；单表 `core_serving.fund_div`；无 raw/std/current/observation |
| quality | `unit_date_field=ann_date`；`ts_code/ann_date/source_entity_key` 必填；`source_multiplicity_policy=deduplicate_identical`；批内冲突 fail-closed |
| capabilities | manual/schedule/retry；point/range；无 workflow/probe/fallback |
| freshness | event-run trace；不做连续日期 completeness |

### 7.1 共享 builder 与 write path

`src/foundation/datasets/definitions/_builder.py` 当前没有 immutable fact contract；已有 `serving_observed_fact_scope_refresh` 还把日期字段硬编码为：

```text
input_shape=trade_date_or_start_end
observed_field=trade_date
time_fields=trade_date,start_date,end_date
quality.unit_date_field=trade_date
```

M1 先将日期 unit scope 校验通用化为：

```text
trade_date_or_start_end -> scope field trade_date
ann_date_or_start_end   -> scope field ann_date
```

同时新增通用 `serving_immutable_fact_insert` contract，并强制：

- `observed_field == unit_date_field`；
- scope 字段同时存在于 source fields 和 normalization date fields；
- no pool/fanout、无运营 filters；
- `raw_dao_name/raw_table/std_table/observation_dao_name/observation_table` 必须为空；
- `serving_table == target_table == core_serving.fund_div`；
- `conflict_columns=("source_entity_key",)`；
- DAO 必须提供 scope 加锁、既有身份/内容查询和不可变批量插入；
- offset pagination 与唯一实体键门禁。

不能复用现有 `serving_direct_upsert`：`BaseDAO.bulk_upsert()` 会在冲突时更新可变列，并在批内相同冲突键时采用最后一行；direct writer 也不保证任一归一化 reject 时整 unit 零写入。不能复用 observed-fact scope refresh：它要求 current/observation 成对存在并执行删除重建。两者都与不可变公告事实冲突。

M1 新增的路径只能做“核验后插入”：不更新、不删除、不调用 `bulk_upsert()`、不调用 `bulk_insert_ignore_conflicts()` 静默吞掉冲突。它必须是声明式通用能力，不新增 `fund_div` key 分支，也不改变现有 observed snapshot、observed fact 或 direct upsert 数据集。

## 8. planner、request builder 与 source client

### 8.1 planner

复用 `src/foundation/ingestion/unit_planner.py` 的 `build_natural_day_point_units` 的 unit 展开算法：

- point 生成一个统一日期锚点；
- range 生成每个自然日锚点；
- `PlanUnit.trade_date` 是内部统一日期锚点名称，不代表源请求一定使用 `trade_date`。

但不能原样复用当前 progress context：`_build_generic_progress_context` 固定输出 `trade_date`。M1 必须让 progress context 从 Definition 的 `observed_field/input_shape` 派生主日期字段；fund_share 继续输出 `trade_date`，fund_div 输出 `ann_date`，并携带 `date_field` 供 TaskRun/Issue 详情显示正确标签。不得把公告日显示成“交易日期”，也不为 fund_div 写 key 特例。

不能复用股票 `dividend` 的 `_build_dividend_units`，它的输入和错误语义不同。

单 TaskRun 最大自然日数固定为 `366`：一个平年或闰年的闭区间可以作为一个运维批次，`367` 日及以上必须在 resolver/planner 前拒绝。该值只控制一次执行包含的基础 unit 数，不表示源端支持区间参数；历史回补仍由平台按公告自然日逐个请求，并按自然年拆成多个 TaskRun。M2 必须验证 366 个串行 unit 的实际耗时、配额和失败恢复；如结果不可接受，只能通过重新审计并修订本文下调上限，不能运行时静默截断。

### 8.2 request builder

在 `src/foundation/ingestion/request_builders.py` 新增 `_fund_div_params`：

```python
{"ann_date": anchor.strftime("%Y%m%d")}
```

禁止发送 `start_date/end_date/ts_code/ex_date/pay_date`。不能复用股票 `_dividend_params` 或通用源端区间 builder。

### 8.3 source client

复用当前 offset client；M1/M2 必须验证：

- offsets 为 0/2000/...；
- 每页 `fields` 完全一致；
- 短页结束；
- 第二页及以后失败时不进入 writer；
- exact duplicate 的出现次数跨页不丢失；
- 分页并集与无分页多重集一致。

当前 `DatasetSourceClient` 只返回总请求数与合并行数，`TushareHttpClient._summarize_params` 也没有记录 `ann_date/offset/limit`，尚不满足模板要求的分页可追踪性。M1 必须做一项与 dataset key 无关的最小通用化：

- 每次分页请求写结构化日志：`api_name/unit_id/ann_date/offset/limit/page_rows/is_short_page`；日志不得包含 token；
- 每个 unit 的 `SourceFetchResult` 精确返回：policy、page limit、page count、合并行数、终止 offset、终止页行数与是否观察到短页；
- 完整 offset/limit/每页行数序列保留在结构化日志；TaskRun/TaskRunNode 不复制 366 组明细，只保存下面 11.4 冻结的精确聚合和最多 3 个 unit 样本；
- `TushareHttpClient` 的安全参数摘要白名单补入 `ann_date/offset/limit`；
- 非分页数据集返回空摘要，现有 TaskRun/API/UI 行为保持不变。

这不是 fund_div 专用分页器，也不改变 source client 的结束条件。结构化日志或 TaskRun 状态写入失败只能影响观测，不能阻断、回滚或污染业务数据事务。

## 9. 字段、身份与归一化

### 9.1 16 字段端到端映射

| 字段 | 源文档与真实样本 | 显式 `source_fields` | 归一化 / ORM | migration 列 | nullable | 身份 / scope 作用 | raw / Lake |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ts_code` | 文档有；`20260617/20201215` 显式请求列存在且抽样非空 | 是 | trim/uppercase 仅用于身份；源值 TEXT | `fund_div` 同名 TEXT | 否 | 事件身份 | 不适用：direct-serving；本批不进 Lake |
| `ann_date` | 文档有；两组样本列存在且抽样非空 | 是 | `YYYYMMDD` → DATE | `fund_div` 同名 DATE | 否 | unit scope + 事件身份 | 同上 |
| `imp_anndate` | 文档有；两组显式样本列存在 | 是 | 可空日期 → DATE | `fund_div` 同名 DATE | 是 | 事件身份 | 同上 |
| `base_date` | 文档有；两组显式样本列存在 | 是 | 可空日期 → DATE | `fund_div` 同名 DATE | 是 | 事件身份 | 同上 |
| `div_proc` | 文档有；两组显式样本列存在 | 是 | TEXT，不改写 | `fund_div` 同名 TEXT | 是 | 内容哈希 | 同上 |
| `record_date` | 文档有；两组显式样本列存在 | 是 | 可空日期 → DATE | `fund_div` 同名 DATE | 是 | 事件身份 | 同上 |
| `ex_date` | 文档有；两组显式样本列存在 | 是 | 可空日期 → DATE | `fund_div` 同名 DATE | 是 | 事件身份 | 同上 |
| `pay_date` | 文档有；两组显式样本列存在 | 是 | 可空日期 → DATE | `fund_div` 同名 DATE | 是 | 事件身份 | 同上 |
| `earpay_date` | 文档有；两组显式样本列存在 | 是 | 可空日期 → DATE | `fund_div` 同名 DATE | 是 | 事件身份 | 同上 |
| `net_ex_date` | 文档有；两组显式样本列存在 | 是 | 可空日期 → DATE | `fund_div` 同名 DATE | 是 | 事件身份；区分短键碰撞 | 同上 |
| `div_cash` | 文档有；两组显式样本列存在 | 是 | `Decimal(str(value))` → NUMERIC(30,10) | `fund_div` 同名 NUMERIC(30,10) | 是 | 内容哈希 | 同上 |
| `base_unit` | 文档有；两组显式样本列存在 | 是 | `Decimal(str(value))` → NUMERIC(30,10) | `fund_div` 同名 NUMERIC(30,10) | 是 | 内容哈希；区分短键碰撞 | 同上 |
| `ear_distr` | 文档有；两组显式样本列存在 | 是 | `Decimal(str(value))` → NUMERIC(30,10) | `fund_div` 同名 NUMERIC(30,10) | 是 | 内容哈希 | 同上 |
| `ear_amount` | 文档有；两组显式样本列存在 | 是 | `Decimal(str(value))` → NUMERIC(30,10) | `fund_div` 同名 NUMERIC(30,10) | 是 | 内容哈希 | 同上 |
| `account_date` | 文档有；两组显式样本列存在 | 是 | 可空日期 → DATE | `fund_div` 同名 DATE | 是 | 事件身份 | 同上 |
| `base_year` | 文档有；两组显式样本列存在 | 是 | TEXT，不按整数年份解析 | `fund_div` 同名 TEXT | 是 | 事件身份 | 同上 |

2026-08-07 又对 6 个代表公告日的 476 个源行（包含 exact duplicate）做了只读字段剖面：

| 字段 | null / 476 | 样本长度或数值范围 |
| --- | ---: | --- |
| `ts_code` | 0 | 最大 9 字符 |
| `ann_date` | 0 | 8 字符 |
| `imp_anndate` | 14 | 非空均 8 字符 |
| `base_date` | 0 | 8 字符 |
| `div_proc` | 0 | 最大 2 个字符 |
| `record_date` | 14 | 非空均 8 字符 |
| `ex_date` | 14 | 非空均 8 字符 |
| `pay_date` | 14 | 非空均 8 字符 |
| `earpay_date` | 462 | 非空均 8 字符 |
| `net_ex_date` | 80 | 非空均 8 字符 |
| `div_cash` | 0 | 0 至 0.9；最多 1 个整数位、4 位小数 |
| `base_unit` | 21 | 0.0001 至 2,361,146.6081；最多 7 个整数位、4 位小数 |
| `ear_distr` | 17 | -4.44 至 1,819,455,552.75；最多 10 个整数位、2 位小数 |
| `ear_amount` | 362 | 0.28 至 136,129,807.78；最多 9 个整数位、2 位小数 |
| `account_date` | 178 | 非空均 8 字符 |
| `base_year` | 14 | 非空均 8 字符，样本表现为完整日期而非四位年份 |

样本日期为 `19990329/20191104/20201215/20211215/20230110/20260617`，覆盖最早候选、历史重复高发日和当前无重复日。它支持当前类型选择，但不是全历史永久上限。

DATE 归一化对 `YYYYMMDD` 是无损语义转换；源 null 必须保留为 null。只有 `ts_code/ann_date` 作为 required fields；其余字段即使本样本无 null，也因源文档没有非空保证而保持 nullable。四个数值使用 `Decimal(str(value))` 与 `NUMERIC(30,10)`：样本最大 10 个整数位、4 位小数，仍有显著余量。normalizer 必须在写入前验证能被该类型精确表示；超过 20 个整数位或 10 位小数时以 `normalize.numeric_precision_overflow:<field>` 拒绝整个 unit，禁止数据库静默舍入。若真实源扩展超过边界，先审计并扩表，不截断源事实。

### 9.2 逻辑事件键

固定字段顺序：

```text
ts_code, ann_date, imp_anndate, base_date, record_date, ex_date,
pay_date, earpay_date, net_ex_date, account_date, base_year
```

规则：

- `ts_code` 去首尾空格并转大写后参与身份，但源字段值不被覆盖；
- 日期使用统一 `YYYYMMDD`；
- optional 日期空字符串按现有日期归一化契约转为 null；其他非法非空日期拒绝；canonical 序列化对 null 使用显式标记；
- 用版本化 canonical 序列化后 SHA-256，形成 `source_event_key`；
- `source_row_hash` 覆盖全部 16 个归一化源字段，用于判定 exact duplicate，并作为 `source_content_hash`；
- `identity_basis=fund_div_full_event_dates_v1`。

`source_entity_key=source_event_key`，`source_content_hash=source_row_hash`。不追加 occurrence count 或 ordinal。

同一批内：

- 同 `source_event_key`、不同 `source_content_hash`：整个 unit fail-closed；
- 同 event、同 content：去重后保留一条，并增加运行级 `rows_deduplicated`。

跨次同步按已确认的披露语义处理：正式修订重新发布公告，新的 `ann_date` 形成新 `source_event_key`，旧公告事实保持不变。若 Tushare 对既有 `source_event_key` 返回不同 `source_content_hash`，writer 返回 `write.immutable_fact_conflict` 并使整个 unit 回滚；禁止覆盖、并存两个内容版本或静默忽略。系统不声称能恢复 Tushare 未提供的新旧公告关联关系。

## 10. 表、DAO 与 HDD migration

### 10.1 表结构

只新增 `core_serving.fund_div`，ORM 路径为 `src/foundation/models/core_serving/fund_div.py`。该表显式列保存 16 个源字段，并保存：

- `source_entity_key`：业务事件身份；
- `source_content_hash`：全部 16 个源字段的内容哈希；
- `identity_basis=fund_div_full_event_dates_v1`；
- `ingested_at`：该不可变事实首次写入时间。

`source_event_key/source_row_hash` 是归一化阶段的概念，分别直接落为 `source_entity_key/source_content_hash`，不再重复建同义列。不保存 `source_occurrence_count/source_occurrence_no/observed_at/updated_at`，不创建 current、observation、JSON/EAV、raw 或 std 表。

### 10.2 主键

- 主键：`source_entity_key`；
- `source_content_hash` 为非空 64 位内容哈希审计列，不作为历史版本主键；
- 同一批内同 `source_entity_key`、不同 `source_content_hash` 整 unit fail-closed；
- 同一批内两者均相同先去重，只插入一条；
- 数据库已存在同 identity、同 hash：幂等匹配，不执行 DML；
- 数据库已存在同 identity、不同 hash：`write.immutable_fact_conflict`，整 unit 回滚；
- 数据库同 `ann_date` 已存在 identity 在本次完整源集合中消失：`write.immutable_scope_regression`，整 unit 回滚；
- 仅对 source 中新增且数据库不存在的 identity 执行普通 INSERT；禁止 UPDATE、DELETE、UPSERT 和 `ON CONFLICT DO NOTHING`。

### 10.3 索引与分区

最小索引：

- `(ann_date DESC, ts_code)`；
- `(ts_code, ann_date DESC)`；

当前没有证据支持额外 `ex_date/pay_date` 查询索引，也没有容量证据要求分区。首版不分区；B4-FD-M4a 用真实历史规模复审，不因“历史事实表”名称提前复杂化。

### 10.4 migration

- 创建前断言 `gs_raw_cold_hdd` 存在，否则整个 migration 失败；
- `fund_div` 表、主键索引和 2 个二级索引共 4 个 relation 全部显式指定 HDD tablespace；
- 不回退默认 SSD；
- `down_revision` 连接实施时真实 head；
- downgrade 不得在未获明确授权时作为生产数据清理手段。

### 10.5 DAO

新增通用 `src/foundation/dao/immutable_fact_dao.py::ImmutableFactDAO`，由 DAO factory 注册 `fund_div` 实例。它只提供最小持久化原语：

1. `acquire_scope_lock(scope_field, scope_value)`：PostgreSQL transaction advisory lock；
2. `fetch_scope_identity_hashes(scope_field, scope_value)`：读取既有 identity/hash；
3. `insert_new_rows(rows)`：普通批量 INSERT。

DAO 不判断“修订必须新发公告”，不统计 TaskRun，也不提交事务；不可变冲突、源端回退和完整性决策留在 writer。不得复用名称和职责均属于观察版本协议的 `ObservedSnapshotDAO`，也不得把 immutable 语义塞进 `BaseDAO.bulk_upsert()`。

## 11. writer、事务与完整性

### 11.1 不可变事实写入算法

当前 writer 没有不可变事实写入协议。现有 `serving_direct_upsert` 会经 `BaseDAO.bulk_upsert()` 在冲突时更新可变列，并在批内冲突时采用最后一行；`serving_observed_fact_scope_refresh` 又要求 current/observation 成对存在并删除重建作用域。两者都不能用于 `fund_div`。

M1 新增通用 `serving_immutable_fact_insert`，但只抽象真正共享的不可变事实语义，不写 `fund_div` action-key 分支。一个 `ann_date` unit 的事务步骤固定如下：

1. 完成全部分页、字段校验、归一化、exact duplicate 去重和批内 identity 唯一性检查；任一 reject、页失败或跨 `ann_date` 行都在进入数据库写路径前使 unit 失败。
2. 由 `quality.unit_date_field=ann_date` 解析作用域，并取得同一 `ann_date` 的 PostgreSQL transaction advisory lock。
3. 通过 `ImmutableFactDAO.fetch_scope_identity_hashes()` 读取该公告日数据库已有的 `source_entity_key -> source_content_hash` 集合。
4. 若数据库已有 identity 不在本次完整源集合中，返回 `write.immutable_scope_regression`，整 unit 回滚；禁止删除数据库事实来迎合源端缩减。
5. 若相同 identity 的数据库 hash 与本次 hash 不同，返回 `write.immutable_fact_conflict`，整 unit 回滚；禁止覆盖旧事实或同时保留两个内容版本。
6. 将本次唯一事实拆为 `rows_matched_existing` 与 `rows_inserted_new`；仅对新增 identity 执行普通 INSERT。
7. INSERT 后重新读取该 scope，确认本次每个唯一 identity 都存在且 hash 一致；数量或 hash 不完整时返回 `write.immutable_fact_persistence_incomplete`，整 unit 回滚。
8. writer 返回 `rows_written=normalized_unique_rows`。这是“本次已成功对照并存在于事实表的唯一事实数”，用于现有 Ops `rows_saved`；真实新增数与幂等命中数分别进入持久化 diagnostics。
9. commit 仍由外层执行器统一控制；writer 和 DAO 都不得自行提交。

禁止在该路径中出现 UPDATE、DELETE、UPSERT、`ON CONFLICT DO NOTHING` 或 last-row-wins。普通 INSERT 的唯一约束异常也必须显式失败并回滚，不能吞掉后假报成功。

这是一条新增的并行 storage contract。既有 `serving_observed_snapshot_refresh`、`serving_observed_fact_scope_refresh`、`serving_direct_upsert` 及其数据集语义保持不变。

### 11.2 空结果与源端回退

空结果也必须加锁并查询目标 scope，不能在进入 writer 前直接无条件返回：

- 源端为空且数据库该 `ann_date` 也为空：成功 no-op，`rows_written=0`；
- 源端为空但数据库该 `ann_date` 已有事实：返回 `write.immutable_scope_regression`，表保持不变；
- 不把合法空公告日计为缺数或 reject。

这条规则同时防止瞬时空响应擦除历史，并把“已经保存的源事实突然消失”提升为必须人工审计的契约异常。首版不猜测源端删除语义，也不自动删除任何业务事实。

### 11.3 exact duplicate 阶段

去重必须发生在 `batch_unique_key_fields` 校验之前，并由 Definition 的 `source_multiplicity_policy=deduplicate_identical` 显式 opt-in；fund_share、fund_company 等现有数据集继续使用默认 `reject`，不得改变。

M1 的最小共享契约如下：

| 位置 | 新契约 | 门禁 |
| --- | --- | --- |
| `DatasetQualityPolicy` | `source_multiplicity_policy`: `reject` / `deduplicate_identical` | 默认 `reject`；仅 fund_div opt-in |
| normalizer 批级阶段 | 按全部 source fields 的 canonical hash 去重 | 先去 exact duplicate，再校验同 entity 不同 content |
| `NormalizedBatch` 到运行摘要 | 新增 `rows_deduplicated` | 非 reject；默认 0；不得改写 fetched/written/rejected |
| TaskRun/TaskRunNode/API/UI | 持久化并显示 `rows_deduplicated` | 只解释行数差额，不进入业务表或 reason code |

`rows_deduplicated` 必须贯通 `NormalizedBatch -> _RunState/IngestionRunSummary -> DatasetMaintainResult -> TaskRun ingestion context/dispatcher/model -> API/UI`。TaskRun schema migration 与业务表 migration 分开审计，状态写入失败不得影响业务事务。

固定错误与对账口径：

| 场景 | 口径 |
| --- | --- |
| `ts_code/ann_date` 缺失 | `normalize.required_field_missing:*` |
| 数值无法被 NUMERIC(30,10) 精确表示 | `normalize.numeric_precision_overflow:<field>`；整个 unit 失败 |
| unit 公告日不一致 | `normalize.unit_date_mismatch` |
| 同 event、不同 source row | `normalize.batch_unique_key_conflicting`；整个 unit 失败 |
| exact duplicate | 保留一条；`rows_deduplicated += N-1`；不计 reject |
| 数据库同 identity、不同 content | `write.immutable_fact_conflict`；整个 unit 失败 |
| 数据库既有 identity 从完整源集合消失 | `write.immutable_scope_regression`；整个 unit 失败 |
| INSERT 后事实数量或 hash 不完整 | `write.immutable_fact_persistence_incomplete`；整个 unit 失败 |

```text
source_rows_fetched
  = normalized_unique_rows
  + rows_deduplicated
  + rows_rejected

# 仅成功 unit；成功前提是 rows_rejected = 0
rows_saved / rows_written
  = normalized_unique_rows
  = rows_inserted_new + rows_matched_existing

COUNT(core_serving.fund_div WHERE ann_date = unit_date)
  = normalized_unique_rows
  = scope_existing_count_after_commit
```

若 `rows_rejected > 0`，上述保存/目标等式不成立：整个 unit 失败并回滚，`rows_saved=0`，事实表保持事务前集合。

首次同步 `20201215` 的目标口径是：`141 fetched / 74 saved / 67 deduplicated / 0 reject`，其中 `rows_inserted_new=74`、`rows_matched_existing=0`。相同完整结果重跑仍是 `74 saved`，但 `rows_inserted_new=0`、`rows_matched_existing=74`，目标 scope 仍为 74 行。这样既保持现有 `rows_saved` 健康语义，也能准确区分真实 INSERT 与幂等对照。

业务表不得出现 occurrence count、ordinal 或重复诊断列。

### 11.4 通用 ingestion diagnostics 载体

分页摘要仍放入一个结构化、受 schema 校验的 `ingestion_diagnostics` contract；exact duplicate 只使用独立数值 `rows_deduplicated`，不制造重复明细 JSON：

- `SourceFetchResult.source.pagination`：每个 unit 精确保存 page limit、page count、合并行数、终止 offset、终止页行数与 short-page 标志；
- TaskRun/TaskRunNode 的 `source.pagination` 只保存可求和/比较的精确聚合：`unit_count_with_pagination`、`total_page_count`、`total_rows_merged`、`multi_page_unit_count`、`max_pages_per_unit`、`short_page_unit_count`；另保存最多 3 个 `unit_samples`，样本含 `unit_id/page_count/terminal_offset/terminal_page_rows`；
- `NormalizedBatch`、`SourceFetchResult`、`IngestionRunSummary`、`ProgressSnapshot` 和 `DatasetMaintainResult` 只携带声明式诊断，不感知 `fund_div` key；
- TaskRun/TaskRunNode 持久化 `rows_deduplicated` 与分页 diagnostics；`persistence.immutable_fact` 额外保存 `rows_inserted_new`、`rows_matched_existing`、`scope_existing_count` 和 `scope_source_unique_count`；API 原样输出，前端详情显示源行、去重、已对照保存、新增插入、幂等命中与 reject；
- 不新增 exact duplicate diagnostic/reason code；existing datasets 的 `rows_deduplicated` 默认 0、pagination diagnostics 为空，不改历史业务记录、不要求重新配置 schedule。

诊断大小契约固定为：pagination 最多 3 个 unit sample，序列化后的 `ingestion_diagnostics_json` 最多 16 KiB。超限时只截断样本并写 `truncated=true`；TaskRun 的六个 pagination 聚合、`rows_deduplicated`、四个 immutable persistence 计数和 `SourceFetchResult` 的当前 unit 精确值不得截断。每个 unit 的 terminal 明细和完整分页序列仍在 `SourceFetchResult`/逐页结构化日志中，不承诺全部复制进 TaskRun JSON。

M1 编码前必须用 CodeGraph 再复核这些共享 contract 的全部调用方；如果发现已有通用 diagnostics 载体足够表达，优先复用并删去新增字段，不允许并存两套事实。

## 12. Ops、UI、schedule、workflow 与 probe

### 12.1 Catalog 与手动任务

- 在现有 `public_fund / 公募基金` 组新增 `fund_div`，排序紧随 `fund_share`，建议 `item_order=60`；
- 手动维护由 Definition 生成 `ann_date` point 与自然日 range；
- 无业务 filters；
- UI 不增加 dataset action-key 白名单。

当前手动任务 API 已能返回 ann_date DateField，前端按 API 字段渲染。M1 必须用浏览验收确认 point/range、请求 payload 和无 filters；若发现前端需要特殊 key 分支，先停止并回到 capability contract 评审。

### 12.2 自动任务能力

- 普通 `once`：运营选择固定 point/range；
- 普通 `cron`：Definition 显式声明 `trigger_day_point`，系统在触发时生成自然日 point；
- 不创建默认 schedule，不写 schedule seed；
- 实际 cron 频率和时刻不在 M1/M2/M3 自动决定。

当前代码不能原样满足前两项：自动任务前端只把 `trade_date` 识别为单日，once 固定提交 `trade_date`；`trigger_day_point` 的 TaskRun 生成逻辑也固定写 `trade_date`。validator 最终能把它转成 `ann_date` 不能证明调度意图、TaskRun 详情和 UI 契约正确。M1 必须完成一次 Definition 驱动的通用化，禁止只追加 `ann_date` 白名单：

1. 后端从 `DatasetDefinition.date_model + input_model` 派生唯一时间输入契约：

   ```text
   supported_modes = point, range
   point_field = ann_date
   range_start_field = start_date
   range_end_field = end_date
   granularity = day
   ```

2. `AutomationCapabilityResponse` 增加结构化 `time_input_contract`；`CalendarPolicyCapabilityResponse` 同时返回 `generated_time_field`，两者均由同一 resolver 生成，不由页面推断。
3. `src/ops/schemas/task_run.py::TaskRunTimeInput` 显式接收 `ann_date`，防止 Pydantic 请求模型在持久化前丢弃用户意图；TaskRun JSON 继续携带 `date_field=ann_date`。dispatcher 再把该值映射为 foundation 内部统一日期锚点，resolver 才生成源参数。
4. `TaskRunCommandService` 的 `trigger_day_point` 根据该 contract 生成 `time_input.ann_date`；fund_share 仍生成 `time_input.trade_date`。
5. `operations_schedule_service.py` 的创建、更新、resume 校验和 TaskRun runtime 都使用同一 contract；不能依赖当前分散的 `_has_fixed_ann_date/_has_explicit_time_boundary` 判断，也不能只靠 UI。
6. `frontend/src/shared/api/types.ts` 增加 time contract 类型；`frontend/src/shared/ops-time-capability.ts` 与自动任务页删除“单日必为 trade_date”的 `TIME_POINT_KEYS/TIME_PARAM_KEYS` 推断，按 API 的 point/range 字段构造 once params、filters 和 TaskRun `time_input`。
7. unit progress context 按 Definition 的 `observed_field` 输出 `ann_date` 和 `date_field=ann_date`；`executor.py`、`task_run_query_service.py`、`frontend/src/shared/ops-display.ts` 和任务详情共同显示“公告日期”，不能显示“交易日期”。

这项改造是共享时间契约修正，不是 fund_div 特例。必须回归 fund_share、news/major_news 等现有 `trigger_day_point` 数据集，并证明既有 schedule 持久化意图不被重写；无需重新配置现有 schedule。

### 12.3 发布时点与相对日期仍后置

现有 `trigger_day_point` 只能生成触发日，不能自动表达 D-1 或 N 日滚动。源端只证明公告当日已有数据，未证明何时完整。因此首个 cron 前有三种后续选择：

1. 晚间维护触发日；
2. 新增 Definition 驱动的相对日/lookback 通用能力；
3. 暂不创建 cron，只用手动/once 修订。

本 LLD 不为 fund_div 私自增加相对时间特例。

### 12.4 禁止能力

- probe：禁止；
- `schedule_probe_fallback`：禁止；
- workflow：不加入；
- `ts_code/ex_date/pay_date` 运营输入：首版禁止；
- 日期连续 completeness：不适用。

## 13. 配置项审计

| 配置 | 默认/建议 | 来源与持久化 | 消费者 | 生效方式 | 运维可见性 |
| --- | --- | --- | --- | --- | --- |
| `TUSHARE_TOKEN` | 现有环境凭据；`fund_div` 至少 400 积分 | env → `Settings.tushare_token`；只存在部署配置，不落业务表 | `TushareHttpClient` | 服务启动/重启 | 不展示 token；M2/M3 仅展示权限预检结果 |
| `TUSHARE_BASE_URL` | `https://api.tushare.pro` | env → `Settings.tushare_base_url` | `TushareHttpClient` | 服务启动/重启 | 不新增 fund_div 覆盖项 |
| `TUSHARE_MAX_CALLS_PER_MINUTE` | 280；fund_div 无专属 override | env → `Settings.tushare_max_calls_per_minute` | `_get_rate_limiter("fund_div")` | 服务启动/重启 | 运行日志、M2/M4a 耗时与限流报告 |
| 16 个 source fields | 固定 | Definition 代码 | source client、normalizer、writer | 部署 | Catalog/LLD/测试 |
| `page_limit` | 2000 | Definition 代码 | source client | 部署 | Definition 投影 |
| `max_units_per_execution` | 366 个自然日 unit | Definition 代码 | validator/planner | 部署 | Catalog 错误信息；367 日范围被拒绝 |
| `concurrency` | 1 | Definition 代码 | execution | 部署 | Definition 投影 |
| exact duplicate policy | `deduplicate_identical` | Definition 代码 | normalizer；运行级 `rows_deduplicated` 贯通 TaskRun/API/UI | 部署与独立 Ops migration | TaskRun 摘要/LLD |
| immutable conflict policy | 固定 fail-closed | storage Definition 代码 | writer、`ImmutableFactDAO`、codebook | 部署 | TaskRun reason code；无运营可编辑项 |
| pagination diagnostics 大小 | 3 个 unit sample；TaskRun JSON 最多 16 KiB | ingestion contract 代码常量 | source、TaskRun adapter/API | 部署 | 详情显示 `truncated`，聚合计数不截断 |
| HDD tablespace | `gs_raw_cold_hdd` | migration | PostgreSQL | migration | relation placement 审计 |
| schedule cron/once | 无默认 | `ops.schedule`，后续人工创建 | scheduler/TaskRun | 保存后 | Ops UI |

不新增 env/Settings/配置文件开关，不把分页、字段或重复策略散落到脚本和页面常量。

## 14. Definition 消费者与代码影响面

| 消费者 | 当前能力 | M1 影响 | 验收 |
| --- | --- | --- | --- |
| manual actions | ann_date point/range 已有 | 注册 Definition | API + 浏览测试 |
| Catalog | Definition + view | 新增 item 60 | 顺序/唯一性测试 |
| validator/resolver | 支持 ann_date input | 定向回归 | 正反向输入测试 |
| unit planner | natural day point builder 已有；progress 固定 trade_date | 复用展开算法，通用化 progress date field | 周六、空日、range、公告日标签 |
| request builder | 无 fund_div | 新增局部 builder | 只发送 ann_date |
| source client / Tushare client | offset/fields 已有；成功页轨迹与 ann_date 参数摘要不足 | 复用分页并补通用 diagnostics/log summary | 多页/短页/失败、无 token、状态失败隔离测试 |
| Definition builder | observed fact 写死 trade_date 且要求 observation；无 immutable fact contract | 通用化 scope 字段；新增 `serving_immutable_fact_insert` 的单表 DAO contract | fund_share observed 路径 + fund_div immutable 路径双回归 |
| normalizer | scope 字段通用；重复默认拒绝 | 身份 transform + 声明式 exact duplicate 去重 | 141/74/67、冲突、nullable 测试 |
| writer/DAO | direct upsert 会更新冲突行；observed writer 会删除重建并强制 current+observation | 新增声明式 immutable writer 与最小 `ImmutableFactDAO`；只读 scope、只 INSERT 新 identity，不改既有路径 | 首次插入、幂等命中、冲突、源端回退、空日、锁、回滚、既有 writer 全回归 |
| foundation 运行统计 | 只有 fetched/saved/rejected 主计数 | 统一增加 `rows_deduplicated`；`rows_written` 保持“唯一事实已成功对照存在”；pagination/persistence diagnostics 走受限结构化摘要 | 首次与重跑均 141=74+67+0；inserted/matched 分别 74/0 与 0/74；全部调用方构造回归 |
| TaskRun/TaskRunNode 统计 | 只有 fetched/saved/rejected 与 reject JSON | 两模型、ingestion context、dispatcher、query schema/API 增加 `rows_deduplicated` 与 pagination/immutable persistence diagnostics | API、节点/主任务一致、状态失败隔离、幂等重跑不触发“拉取非零但保存为零”健康异常 |
| freshness/cards | event trace 可用 | 注册不连续审计 | 空日不报缺数 |
| snapshot rebuild | 不应参与连续日期重建 | 明确排除 | 负向测试 |
| TaskRun create schema | `src/ops/schemas/task_run.py::TaskRunTimeInput` 无 ann_date，可能静默丢字段 | 增加 ann_date 并按 Definition 校验 date_field/point field | ann_date 不丢失；非法 trade_date 绕过拒绝 |
| schedule capability / binding | capability 无 point 字段 contract；`operations_schedule_service.py` 有分散的 ann/trade_date 检查 | schema/query/resolver 返回统一 time contract；create/update/resume/runtime 全部消费同一 contract | once/cron、持久化意图、绕过拒绝、既有 schedule 快照 |
| schedule TaskRun runtime | `task_run_service.py` 的 trigger-day point 固定 trade_date | 按 `generated_time_field` 生成 ann_date | fund_div ann_date、fund_share trade_date 双回归 |
| foundation progress 文案 | `executor.py::_build_progress_context_parts` 只读取 trade_date | 读取 `date_field` 指向的值并使用 Definition/结构化标签 | 公告日期文案；trade_date/month/week 回归 |
| TaskRun query/detail display | `task_run_query_service.py` 与 `frontend/src/shared/ops-display.ts` 的 unit label 没有 ann_date | 后端输出结构化 unit kind/label；shared display 增加通用消费，不写 dataset-key 分支 | Issue/current object/detail 显示公告日期 |
| workflow/probe | 后端拒绝能力已有 | 不注册 | 负向测试 |
| frontend manual | `ops-v21-task-manual-tab.tsx` 已按 DateField 支持 ann_date | 仅注册 Definition 与补回归 | point/range payload、无 filters、浏览验收 |
| frontend time capability / types | `frontend/src/shared/ops-time-capability.ts` 用 `TIME_POINT_KEYS` 推断，`shared/api/types.ts` 无新 time/diagnostics contract | 删除 point-key 推断，类型显式消费 API time contract、`rows_deduplicated` 与 pagination diagnostics | ann_date/day、trade_date/week/month 正反向单测 |
| frontend auto/detail | `ops-v21-task-auto-tab.tsx` once/cron 固定 trade_date；`ops-task-detail-page.tsx` 消费 shared display | 自动页按 contract 构造 payload；详情页按通用 diagnostics/日期标签渲染 | once point/range、cron、filters、详情、typecheck/test/build + 浏览验收 |

共享改动只允许通用化真实存在的声明式缺口；不修改 `foundation -> ops` 依赖方向，不新增 legacy `platform/operations` 主实现。

CodeGraph 的定向 impact 结果显示，`NormalizedBatch` 直接/间接影响 normalizer、writer 及 B3/B4 数据集测试，`IngestionRunSummary` 影响 executor 与 progress 汇总测试，`ProgressSnapshot` 影响 observer/executor；`serving_observed_fact_scope_refresh` 还被 fund_share 使用。`rows_deduplicated` 必须走同一条运行统计契约，不能只在 fund_div transform 内部吞掉；immutable writer 必须是新增并行 contract，不能修改既有 observed/direct 路径。`task_run_dispatcher.py` 将 `result.rows_written` 投影为 `rows_saved`，`operations_daily_health_report_service.py` 会把 fetched 非零但 saved 为零判为写入异常，因此幂等重跑必须返回已成功对照的唯一事实数，而不是数据库新增 INSERT 数。实施前再次审计全部调用方，并证明其他数据集默认去重数为 0、既有 current/observation/direct-upsert 写入不变。

## 15. 测试与验收

### 15.1 Definition 与输入

- ann_date point 生成一个 unit；
- range 逐自然日生成 unit，覆盖周六/周日；
- start>end、无时间、367 日及以上范围拒绝；365/366 日范围允许；
- `ts_code/ex_date/pay_date` 不出现在运营参数；
- Definition 字段恰为 16 个；
- `bucket_rule=not_applicable` 仍允许日期输入；
- fund_share 的 trade_date contract 不回归。

### 15.2 请求与分页

- 只生成 `ann_date=YYYYMMDD`；
- 每页 fields 完整且顺序稳定；
- 大于 2,000 行的合成 connector fixture 验证 2000/2000/短页、offset 为 0/2000/4000；
- 第二页失败时 writer 零调用；
- 项目 connector 以 `page_limit=50` 只读复现 122 与 141 两组真实源多重集；正式 `page_limit=2000` 下两组真实同步都是单页，不冒充真实多页证据；
- 366 个 unit 的 pagination diagnostics 聚合数值精确，TaskRun 只保留 3 个 unit sample 并正确标记 truncated；
- 无任意最大页数。

### 15.3 字段、身份与重复

- 16 字段逐列映射、null、Decimal 精度；
- `base_year` 按 TEXT；
- `net_ex_date` 能区分短键相同的两个事实；
- optional 日期空字符串转 null、非法非空日期拒绝，null 标记稳定；
- 同 event 不同 content 批内 fail-closed；
- exact duplicate 只保留一条，并验证 `141 fetched / 74 unique / 67 deduplicated / 0 reject`；
- `rows_deduplicated` 贯通 TaskRun/API/UI，但业务表没有 count/ordinal；
- 模拟“新公告修订”使用新 ann_date，新旧公告事实均永久保留；
- 源字段原值不因身份标准化被覆盖。

### 15.4 writer、DAO 与事务

- scope 只含当前 ann_date；
- unit 内跨 ann_date 行拒绝；
- 任一 partial reject 时 DAO 零写入、事实表不变；
- 源端和目标 scope 同为空时成功 no-op；源端为空但目标已有事实时以 `write.immutable_scope_regression` 失败；
- 首次同步只 INSERT 新 identity，禁止调用 `bulk_upsert/replace_current_scope`；
- 相同完整结果重跑零 INSERT、74 个幂等命中，`rows_saved` 仍为 74，事实表集合不变；
- 数据库同 identity、同 hash 视为幂等；同 identity、不同 hash 以 `write.immutable_fact_conflict` 失败且不覆盖；
- 数据库 scope 已有 identity 从本次完整源集合消失时以 `write.immutable_scope_regression` 失败且不删除；
- INSERT 后读取数量或 hash 不一致时以 `write.immutable_fact_persistence_incomplete` 失败；
- 新公告日的新修订事实普通 INSERT，旧公告事实永久保留；
- SQL 路径不得出现 UPDATE、DELETE、UPSERT 或静默 `ON CONFLICT DO NOTHING`；
- 数据库异常全事务回滚；
- 相同 ann_date advisory lock；不同 ann_date 互不使用同一锁键；
- 10,000 行单日容量与回滚。

### 15.5 ORM、migration 与 HDD

- 16 个显式列与 `source_entity_key/source_content_hash/identity_basis/ingested_at` 完整；
- model registry、DAO factory、表名正确；
- tablespace 缺失时 migration 在建表前失败；
- 表、主键索引和 2 个二级索引共 4 个 relation 全部在 HDD；
- 只有 `core_serving.fund_div`；无 current/observation/raw/std/EAV/JSON 表；
- migration 接实施时真实 head。

### 15.6 Ops/UI/边界

- Catalog 公募基金顺序稳定；
- 手动 point/range 无 filters；
- API time contract 对 fund_div 返回 `point_field=ann_date`，对 fund_share 保持 `trade_date`；
- once point 提交 `time_input.ann_date`，once range 提交 `start_date/end_date`；cron 触发日由同一 capability 生成 `ann_date`；
- TaskRun 持久化 intent、progress context、Issue/详情标签均为公告日，不残留伪 `trade_date`；
- Definition/API time contract 接入后的现有 trade_date/week/month 数据集回归通过；
- 部署前后既有 schedule 的 cron、启停、calendar policy 与 params 意图不被重写，无需重新配置；
- probe/fallback/workflow 请求被后端拒绝；
- 无自动 schedule seed；
- TaskRun 详情同时显示 `rows_saved`、`rows_deduplicated`、`rows_inserted_new` 和 `rows_matched_existing`；幂等重跑不触发 saved=0 健康异常；
- 前端 typecheck/test/build 与浏览验收；
- Definition lint、文档完整性和 `git diff --check`。

### 15.7 B4-FD-M1 实际门禁结果

2026-08-07 本地实现完成后，已执行并通过：

1. 公募基金 B0–B4、Definition registry/linter、source client、normalizer、writer、Ops Catalog、手动/自动任务与 runtime 定向回归：`274 passed`；
2. fund_div、schedule create/update/resume/runtime、TaskRun 公告日期展示等扩展回归：`187 passed`；两组有重叠，不合并虚报总数；
3. 前端时间 contract、自动任务页、任务详情页：`22 passed`；
4. 前端 TypeScript typecheck 与 production build 通过；build 仅保留既有大 chunk warning；
5. Ruff 定向检查、Python compile、`alembic heads`、文档完整性与 `git diff --check` 均通过；本地 migration graph 唯一 head 为 `20260807_000130`。

上述结论只证明 M1 代码与静态/本地行为。SQLite writer fixture 不替代 PostgreSQL 的 tablespace、advisory lock、NUMERIC round-trip、真实源同步或事务故障注入；这些仍严格留在 M2。

## 16. 隔离与生产真实验收

### 16.1 B4-FD-M2 隔离 PostgreSQL

经独立授权后：

1. 应用 migration，并核验 `fund_div` 表、主键索引和 2 个二级索引共 4 个 relation 的 tablespace；
2. 用大于 2,000 行的合成 connector fixture 验证正式 page limit 的第二页、短页、失败原子性与分页 diagnostics；这一步只证明代码路径，不冒充真实源多页；
3. 以 `page_limit=50` 对 `20260617` 做项目 connector 只读 A/B，再按正式 `page_limit=2000` 完成 122 行单页最小真实同步与对账；
4. 首次同步 `20201215`，验证 `141 fetched / 74 normalized unique / 67 deduplicated / 74 saved / 0 reject`，且 `rows_inserted_new=74`、`rows_matched_existing=0`、目标 scope 为 74 行；
5. 同步周六非空日与自然日空日；
6. 重跑 `20201215`，验证 `rows_inserted_new=0`、`rows_matched_existing=74`、`rows_saved=74`、事实集合和目标 scope 行数不变；
7. 用定向 fixture 验证批内 identity 冲突、数据库 immutable content 冲突、scope regression、INSERT 后不完整、任一 reject 均 fail-closed 且表不变；验证新公告保留旧公告、回滚、advisory lock 与 10,000 行容量；
8. 输出完整对账：源端、唯一归一化、去重、已对照保存、新增插入、幂等命中、拒绝原因与目标事实表。

`20201215` 的验收数字固定为：

| 运行 | fetched | normalized unique / saved | rows_deduplicated | inserted new | matched existing | reject | 目标 scope | 恒等式 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 首次 | 141 | 74 | 67 | 74 | 0 | 0 | 74 | `141 = 74 + 67 + 0`；`74 = 74 + 0` |
| 幂等重跑 | 141 | 74 | 67 | 0 | 74 | 0 | 74 | `141 = 74 + 67 + 0`；`74 = 0 + 74` |

#### 16.1.1 migration 与物理 placement（2026-08-07）

B4-FD-M2 在全新本机 PostgreSQL 18.4 隔离集群完成，连接固定为 `127.0.0.1:55408`，集群数据目录为 `/private/tmp/goldenshare_b4_fd_m2.yHxriF/data`，未连接生产数据库。

- 缺少 `gs_raw_cold_hdd` 的专用失败库先固定在 `20260807_000129`，再执行 `000130`；migration 在建 schema/table 前按预期失败，Alembic 版本仍为 `000129`，`core_serving` schema 和 `fund_div` 表均不存在。
- 创建隔离 tablespace 后，另一个全新数据库从零串行迁移到唯一 head `20260807_000130`。
- `core_serving.fund_div`、`pk_core_serving_fund_div`、`idx_fund_div_ann_date_ts_code`、`idx_fund_div_ts_code_ann_date` 共 4 个 relation 的有效 tablespace 均为 `gs_raw_cold_hdd`，relation path 均经 `pg_tblspc` 指向 `/private/tmp/goldenshare_b4_fd_m2.yHxriF/hdd_tablespace`。
- `pg_wal` 仍是隔离集群 data directory 下的普通目录，没有链接到 tablespace；没有 `fund_div_current/fund_div_observation` 表。

该路径只证明 migration 的 tablespace 绑定和 WAL 边界，不证明 `/private/tmp` 是机械盘。生产介质和 tablespace 真实挂载路径仍必须在 M3 单独核验。

#### 16.1.2 真实 connector、同步与完整对账

MCP 再次显式请求 16 字段得到：`20260617=122/122 unique`，`20201215=141/74 unique/67 exact duplicate`。项目 connector 的只读 A/B 结果如下，分页多重集与正式 2,000 行单页基线双向一致，每页 fields 完整且参数仅含 `ann_date/limit/offset`：

| 公告日 | `page_limit=50` | `page_limit=2000` | 多重集差异 |
| --- | --- | --- | --- |
| `20260617` | `50/50/22`，offset `0/50/100` | `122` | 0 |
| `20201215` | `50/50/41`，offset `0/50/100` | `141` | 0 |

正式 Definition 的 `page_limit=2000` 真实同步结果：

| 运行 | fetched | unique/saved | deduplicated | inserted | matched | reject | target scope |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `20260617` 首次 | 122 | 122 | 0 | 122 | 0 | 0 | 122 |
| `20201215` 首次 | 141 | 74 | 67 | 74 | 0 | 0 | 74 |
| `20201215` 重跑 | 141 | 74 | 67 | 0 | 74 | 0 | 74 |
| 周六 `20260613` | 40 | 40 | 0 | 40 | 0 | 0 | 40 |
| 空日 `20260614` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

每次均为一个短页、一个业务 commit、0 reject。源端唯一归一化集合与目标 `(source_entity_key, source_content_hash)` 集合相等，目标 16 字段重算 content hash 差异为 0。`20260617` 目标后缀为 OF/SH/SZ=`116/4/2`，没有市场裁剪；`20201215` 去重后的目标后缀为 OF/SH=`72/2`。整个隔离阶段 `fund_div` 的 TaskRun、schedule、probe 始终均为 0。

#### 16.1.3 容量、失败原子性与 PostgreSQL 门禁

- 10,000 行合成公告日经正式 source client、normalizer、writer、DAO 和单事务执行，页序为 `2000/2000/2000/2000/2000/0`，offset 为 `0/2000/4000/6000/8000/10000`。fetched/unique/saved/inserted/target 均为 10,000，deduplicated/reject/matched 均为 0，目标散列差异为 0。
- 本次数据库事务 `1.918s`，端到端 `2.510s`，峰值 RSS `276,873,216` bytes，WAL 增量 `6,912,280` bytes；均通过 60 秒事务、120 秒端到端和 512 MiB/可用内存 10% 门禁。该样本不外推历史回补容量。
- 第二页注入失败时只发生 offset `0/2000` 两次调用，目标 scope 为 0，全表指纹不变；合成普通 `RuntimeError` 按现有 codebook 归类为 `internal_error`，不影响“完整分页完成前零写入”的结论。
- 批内 identity 冲突、数据库同 identity 不同 content、scope regression、partial reject、INSERT 后数量不完整、INSERT 后数据库异常均得到预期结构化错误，失败前后全表指纹不变。
- 新公告日插入后旧公告日事实仍保留；`NUMERIC(30,10)` 的 `12345678901234567890.1234567890` 精确 round-trip，超限 fixture fail-closed。
- 相同 `ann_date` 的第二个事务在首事务释放前被 transaction-scoped advisory lock 阻塞，释放后取得锁；不同 `ann_date` 不互相阻塞。
- 注入 Ops progress 写入失败后，业务事实仍成功提交并可完整回查，符合“状态写失败不得影响业务事务”。

以上门禁全部通过，B4-FD-M2 没有发现需要修改生产代码的问题。

### 16.2 B4-FD-M3 生产

经独立授权，B4-FD-M3 已于 2026-08-08 完成。生产部署 HEAD 为 `56779912`，工作区干净，六个服务与两个健康接口均正常。预检时全局活动 TaskRun、活动日期完整性任务和非空闲业务会话均为 0；`fund_div` 历史 TaskRun、schedule、probe 和目标表行数均为 0。

#### 16.2.1 migration 与物理 placement

- 生产预检发现部署流程已经把 Alembic head 升到 `20260807_000130`，因此本轮没有重复执行 DDL。`ops.task_run/task_run_node` 的 `rows_deduplicated` 与 `ingestion_diagnostics_json` 均存在，`core_serving.fund_div` 的 20 个协议/源事实/审计列与 migration 一致；没有 `fund_div_current/fund_div_observation` 表。
- `core_serving.fund_div`、`pk_core_serving_fund_div`、`idx_fund_div_ann_date_ts_code`、`idx_fund_div_ts_code_ann_date` 共 4 个 relation 均显式位于 `gs_raw_cold_hdd`，路径均经 `pg_tblspc/31284` 指向该 tablespace。
- tablespace 真实路径为 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`；`/data/disk` 为 `/dev/vdb` 上的 ext4，验收时可用约 319 GiB。共享 WAL 未迁移。

#### 16.2.2 生产 connector 预检与首次 TaskRun

正式写入前，使用生产部署代码和生产 Tushare 凭据只读请求 `ann_date=20201215`：业务参数只有 `ann_date`，每页显式携带全部 16 个 source fields；唯一一页为 141 行，以 2,000 行短页结束，0 retry、0 缺字段键。归一化结果为 74 条唯一事实、67 条 exact duplicate、0 reject，市场 OF/SH=`72/2`，实体键+内容摘要为 `6c9e80c38bcacd81ec71e9e0a0c97cf1ebe5390410d67a687799538906af6b37`。

随后仅通过 `ManualActionCommandService` 创建正式 TaskRun `#7653`，未直接 SQL 写业务表：

| 项目 | 生产结果 |
| --- | --- |
| resource/action | `fund_div / maintain` |
| trigger/time input | `manual` / `point: ann_date=2020-12-15` |
| filters/schedule | `{}` / `null` |
| 状态与 unit | success；`1/1/0` |
| requested/started/ended | `10:06:34.913226` / `10:06:35.533271` / `10:06:35.722484`（Asia/Shanghai） |
| fetched/saved/deduplicated/rejected | `141 / 74 / 67 / 0` |
| immutable persistence | `74 inserted / 0 matched / scope=74` |

独立脚本重新拉源、重新归一化并读取目标表：source/target 的 74 组实体键和内容摘要完全相同，双向身份差集、同实体内容冲突和目标 16 字段重算 hash mismatch 均为 0；两侧市场分组均为 OF/SH=`72/2`。TaskRun issue 为 0。

#### 16.2.3 幂等重跑与终态边界

在确认无活动任务且目标 scope 为 74 行后，通过同一正式 Manual Action 主链创建 TaskRun `#7654`。该任务成功返回 `141 fetched / 74 saved / 67 deduplicated / 0 reject`，持久化诊断为 `0 inserted / 74 matched / scope=74`。终态独立对账仍得到相同摘要，三类差集和目标内容重算错误均为 0；目标仍为 74 行，全部 `ingested_at` 保持首次写入的 `2026-08-08 10:06:35.685797+08`，证明重跑没有 UPDATE 或新增事实。

数据状态快照显示 `target_table=core_serving.fund_div`、事件日期 `2020-12-15`、`freshness_note=最新事件日期来自真实目标表观测值。`，未生成连续自然日缺口。验收结束后全局活动 TaskRun、活动日期完整性任务、`fund_div` schedule/probe 均为 0；4 个 relation 仍在生产 HDD，表及索引总计 106,496 bytes。worker 自部署后的 `MemoryPeak=181,829,632` bytes，六个服务和双健康接口保持正常。

M3 未创建 schedule、未执行历史回补，也未修改共享 WAL。

## 17. 里程碑与授权边界

| 阶段 | 内容 | 当前状态 |
| --- | --- | --- |
| B4-FD-M0 | 源端请求矩阵、字段、分页、自然日、重复、不可变公告事实与 LLD | 源端复审、业务拍板和 LLD 审计已完成 |
| B4-FD-M1 | Definition、immutable fact contract、request/identity、单表 ORM/DAO、migration、Ops 与本地测试 | **已实现并通过本地门禁** |
| B4-FD-M2 | 隔离 PG migration、HDD、合成多页、真实单页/重复/空日、容量、锁、回滚与对账 | **已完成；全部门禁通过** |
| B4-FD-M3 | 生产只读预检、migration、真实 HDD、首次生产同步与对账 | **已完成；TaskRun `#7653/#7654` 首次插入与幂等重跑、完整对账均通过** |
| B4-FD-M4a | 历史逐年规模、配额、耗时、HDD/索引/WAL 只读预算 | 未授权 |
| B4-FD-M4b | 按年分批历史回补 | 未授权，须单独批准 |
| B4-FD-M4c | 多时点发布观察后拍板并创建 schedule | 未授权，须单独批准 |

编码、隔离写库、生产 migration/同步、历史回补、schedule 是五个独立授权边界，前一阶段完成不自动授权后一阶段。

## 18. 硬需求追溯账本

| ID | 硬需求与依据 | 影响层 / 消费者 | 后端权威约束 | 前端表现与直接消费者 | 实现文件 | 正向测试 | 反向测试 | 真实验证 / 浏览器路径 | 计划阶段 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FD-001 | 显式请求并保存全部 16 个源字段 | source、normalizer、ORM、DAO | Definition 的 `source_fields` 是唯一字段事实源，每页强制携带 | Catalog/详情只消费 Definition/TaskRun 投影，不自选源字段 | `definitions/public_fund.py`、`fund_div` model、新 migration | 16 字段逐列 E2E 与 null/Decimal/DATE | 缺字段或错字段阻断 unit | `20260617`、`20201215` 默认与显式多重集一致；M2 再跑项目 connector | M0/M1/M2 | M1 本地门禁与 M2 隔离真实验收均完成 |
| FD-002 | OF/SH/SZ 全市场，不按后缀裁剪 | request、normalizer、目标事实查询 | request 无市场参数；quality 不设后缀白名单 | 无市场筛选控件 | `public_fund.py`、`normalizer.py` | 混合 OF/SH/SZ fixture 全部保留 | 任一后缀被过滤即失败 | `20260617` 实测 OF 116、SZ 2、SH 4 | M0/M1/M2 | M1 本地门禁与 M2 隔离真实验收均完成 |
| FD-003 | 输入为 ann_date point 或自然日 range；range 逐日 fan-out | Definition、resolver、planner、manual/auto UI | `ann_date_or_start_end` + `build_natural_day_point_units` | 手动页显示“公告日期”单日/范围；自动页从 API time contract 渲染 | `public_fund.py`、`unit_planner.py`、manual/auto task pages | point 1 unit；含周末 range 逐自然日 | no-time、start>end、交易日过滤均拒绝 | 周六 `20260613=40`、`20070414=7`；浏览器提交 payload 验收 | M0/M1/M2 | M1 本地门禁与 M2 隔离真实验收均完成 |
| FD-004 | 每个 unit 的源请求只传 ann_date | request builder、connector | `_fund_div_params` 只产出 `ann_date=YYYYMMDD` | 不向运营暴露源参数 | `request_builders.py` | point/range unit 请求快照 | 禁止 `start/end/ts_code/ex_date/pay_date` 进入 source params | MCP 参数矩阵；M2 捕获真实 connector payload | M0/M1/M2 | M1 本地门禁与 M2 隔离真实验收均完成 |
| FD-005 | offset 分页；满页按 2000 递增，短页结束，无任意页数上限，页轨迹可追踪 | source client、执行器、TaskRun diagnostics | `offset_limit/page_limit=2000`；每页同 fields；完整页序列进无 token 结构化日志；每 unit 精确摘要留在 SourceFetchResult，TaskRun 存六个精确聚合+最多 3 个 unit samples | 详情通用展示聚合和有限样本，不伪装完整逐 unit 清单 | `public_fund.py`、`source_client.py`、`tushare_client.py`、ingestion diagnostics/API/detail UI | 0/2000/... 合成多页、短页、366-unit 聚合与截断 fixture | 第二页失败、漏 fields、提前上限、泄露 token、聚合丢数、状态写失败影响业务均不得发生 | M0 limit 50；M2 合成 2,000 多页与 service diagnostics；M3 TaskRun `#7653/#7654` 均记录 1 页、141 行、短页结束 | M0/M1/M2/M3 | M1/M2/M3 全部验证完成 |
| FD-006 | 任一页失败不得写入部分事实 | connector、executor、writer | 完整分页返回前不调用 writer；一个 unit 一个事务 | TaskRun 显示失败，不把部分行显示成已保存 | `source_client.py`、`executor.py`、`writer.py` | 全部分页成功后一次进入 immutable writer | 第二页/末页异常时 writer 零调用、事实表不变 | M2 故障注入并回查表 | M1/M2 | M1 本地门禁与 M2 隔离真实验收均完成 |
| FD-007 | 事件身份使用完整日期签名和显式 null 标记 | transform、normalizer、DAO | 版本化 canonical hash；源字段原值不改写 | TaskRun 冲突样本经 codebook 展示 | `row_transforms.py`、`normalizer.py` | hash 稳定、null/空值规则、跨次修订 | 短键碰撞、非法日期、缺 ts_code/ann_date 拒绝 | `159816.SZ` 短键相同但 net_ex/base_unit 不同的双行样本 | M0/M1/M2 | M1 本地门禁与 M2 隔离真实验收均完成 |
| FD-008 | exact duplicate 保留一条唯一事实 | multiplicity contract、normalizer、TaskRun | `deduplicate_identical`；业务表无 count/ordinal；运行级 `rows_deduplicated` | 详情区分 fetched、deduplicated、written、reject | `models.py`、`normalizer.py`、运行摘要、TaskRun schema/API/UI | 固定 fixture 验证 141/74/67/0 | 计为 reject、生成 occurrence、依赖页序编号均失败 | `20201215` 连续三次均 141/74/67；M2 目标表验收 74 | M0/M1/M2 | M1 本地门禁与 M2 隔离真实验收均完成 |
| FD-009 | 同 event、不同 source content 的批内冲突 fail-closed | normalizer、codebook、writer | multiplicity 阶段后执行 event 唯一性门禁；结构化 error | 详情页显示统一中文原因，不写 dataset-key 文案 | `normalizer.py`、`codebook.py`、TaskRun detail | 无冲突批正常发布 | 冲突 fixture 整 unit 失败且事实表不变 | M2 注入两条同 event 不同 content | M1/M2 | M1 本地门禁与 M2 隔离真实验收均完成 |
| FD-010 | 业务修订以新公告形成新事实；单表不可变保存 | storage Definition、writer、model | 只建 `core_serving.fund_div`；新公告普通 INSERT，旧公告永久保留；不建 current/observation | 数据状态显示源端公告事实，不伪造观察版本 | `public_fund.py`、fund_div model、`writer.py` | 新公告同步后新旧事实并存 | migration 不得创建 current/observation；不得 UPDATE/DELETE 旧事实 | M2 定向两公告日对账 | M1/M2 | M1 本地门禁与 M2 隔离真实验收均完成 |
| FD-011 | 按 ann_date 原子对照并只插入新事实，同日加 advisory lock | writer、`ImmutableFactDAO`、PostgreSQL | 新 `serving_immutable_fact_insert`；同 hash 幂等；不同 hash、scope regression、持久化不完整均 fail-closed；单 unit 单事务 | TaskRun 只显示提交后的保存与 inserted/matched 计数 | `writer.py`、`definitions/_builder.py`、`immutable_fact_dao.py` | 首次 INSERT、相同源重跑幂等、异日隔离 | 禁止 update/delete/upsert/ignore conflict；跨日行、reject、内容冲突、源端回退、DB 异常均回滚 | M2 并发锁、SQL 路径与表集合对账 | M1/M2 | M1 本地门禁与 M2 隔离真实验收均完成 |
| FD-012 | 真空公告日成功 no-op；既有事实不能因空/缩减源结果消失 | writer、DAO | 空源+空目标成功；空源+非空目标或源集合少 identity 均 `write.immutable_scope_regression` | 真空日显示成功 0；回退显示结构化失败 | `writer.py`、`immutable_fact_dao.py`、codebook | `20260614` 空源空目标成功 | 空响应或缩减集合删除/忽略既有事实必须失败 | M2 空日与回退 fixture 回查 | M0/M1/M2 | M1 本地门禁与 M2 隔离真实验收均完成 |
| FD-013 | 事件型数据不做连续自然日 completeness | freshness、cards、date audit、snapshot rebuild | `bucket_rule=not_applicable/audit=false`，排除连续桶审计/重建 | 卡片显示事件运行轨迹，不报“缺一天” | Definition/freshness projection、audit/rebuild guards、dataset card | 非空/空日均生成正确运行轨迹 | 空日不得生成缺数告警或连续桶 | M1 API/UI fixture；M2 真实空日/非空日；M3 生产状态快照显示真实事件日期与事件型 freshness note | M1/M2/M3 | M1/M2/M3 全部验证完成 |
| FD-014 | 表、主键和全部索引在 HDD；共享 WAL 留 SSD | ORM/migration/DB | migration 先断言 `gs_raw_cold_hdd`，不回退默认盘 | Ops 不提供存储位置编辑项 | fund_div models、`alembic/versions/<fund_div migration>` | migration metadata/placement | tablespace 缺失时零建表；禁止默认 SSD | M2 隔离 placement；M3 生产 4 relation 均在 `/dev/vdb` 的 `gs_raw_cold_hdd` | M1/M2/M3 | M1/M2/M3 全部验证完成 |
| FD-015 | 单 TaskRun 最多 366 个自然日 unit | Definition、validator、resolver、planner | `max_units_per_execution=366`，执行前完整拒绝超限 | 手动/自动表单显示后端错误，不静默截断 | `public_fund.py`、validator/resolver | 365/366 日范围允许 | 367 日拒绝且零 source 请求 | M1 验证 366/367 边界；M4a 量化真实年度耗时/配额/恢复 | M1/M4a | M1 边界门禁完成；真实年度预算未授权，不属于 M2 最小同步 |
| FD-016 | Ops 归入“公募基金”，排序紧随 fund_share | Catalog、manual/auto lists | Catalog view + Definition 注册是权威 | 手动/自动页均显示基金分红，分组不进 ETF基金 | `dataset_catalog_views.py`、Catalog query、两类任务页 | 顺序/唯一性 API 测试 | 不得出现重复分组或旧组 | 浏览器核对两个入口 | M1 | M1 本地实现与自动化门禁完成 |
| FD-017 | 手动任务支持 ann_date point/range | manual action query/service、frontend | Manual Action API 从 Definition 派生 DateField；TaskRun schema 保留 ann_date/date_field | `ops-v21-task-manual-tab.tsx` 按 DateField 渲染与提交 | `manual_action_query_service.py`、`manual_action_service.py`、`schemas/task_run.py`、manual page | point/range 提交正确 `time_input` | no-time、start>end、367 日绕过被拒绝 | 浏览器创建前检查请求 payload，不实际提交远程任务 | M1 | M1 本地实现与自动化门禁完成 |
| FD-018 | once/cron 的时间字段由 Definition contract 派生，不固定 trade_date | schedule capability、binding/runtime、auto UI | API 返回 `time_input_contract/generated_time_field`；create/update/resume/runtime 共同校验 | `ops-time-capability.ts` 与 auto page 按 contract 构造 ann_date | `schemas/catalog.py`、`schemas/task_run.py`、capability resolver/query、`operations_schedule_service.py`、`task_run_service.py`、`shared/api/types.ts`、`ops-time-capability.ts`、auto page | fund_div once/cron 生成 ann_date；fund_share 保持 trade_date | 伪造 trade_date、丢 ann_date、非法 mode 均拒绝 | 浏览器验收 once/cron payload；既有 schedule 快照不变 | M1 | M1 本地实现与自动化门禁完成 |
| FD-019 | progress、TaskRun 和 Issue 使用公告日期语义 | planner、executor、TaskRun query/API/detail | progress 从 `observed_field` 派生 `ann_date/date_field`；文案读取 date_field，后端输出结构化 unit kind | 详情显示“公告日期”，不得显示“交易日期” | `unit_planner.py`、`executor.py`、`task_run_query_service.py`、`shared/ops-display.ts`、`ops-task-detail-page.tsx` | ann_date progress/issue/current object | fund_div context 丢 ann_date 或残留伪 trade_date 即失败 | M1 浏览器 fixture；M3 TaskRun `#7653/#7654` 的 time input 与 plan operator object 均为 `ann_date/date_field=ann_date` | M1/M3 | M1/M3 全部验证完成 |
| FD-020 | 首版不暴露 ts_code/ex_date/pay_date filters | Definition input、manual/schedule validators/UI | filters 为空；后端拒绝额外参数 | 手动/自动页无这些控件 | `public_fund.py`、manual/schedule validators、task pages | 合法无 filter 请求 | 绕过 UI 提交任一 filter 被拒绝 | 源端 AND 缩小结果反例；浏览器无控件 | M0/M1 | M1 本地实现与自动化门禁完成 |
| FD-021 | 允许 manual、普通 once/cron 与 retry | Definition、Catalog、manual/schedule/retry API | 只声明三类能力，普通 schedule 使用 cron/once | 页面显示手动、普通自动与重试入口 | `public_fund.py`、Catalog/capability/retry services、task pages | 三类合法路径 capability/API 测试 | 未声明的 trigger mode 不得混入 | API + 浏览器能力浏览验收 | M1 | M1 本地实现与自动化门禁完成 |
| FD-022 | 禁止 probe 与 schedule_probe_fallback | Definition、schedule API/binding/runtime | capability 不声明 probe condition；API 与 runtime 防绕过 | 自动页不显示 probe/fallback | `public_fund.py`、capability resolver、schedule binding/runtime | 普通 schedule 仍可用 | probe/fallback 创建、更新和 runtime 绕过均拒绝 | API 反向请求 + 浏览器无入口 | M1 | M1 本地实现与自动化门禁完成 |
| FD-023 | 禁止加入 workflow | Definition、workflow registry/API/runtime | workflow eligibility/registry 均不包含 fund_div；运行时拒绝拼接 | 页面无 workflow 入口 | `public_fund.py`、workflow registry/service/API | 独立 manual/schedule 正常 | workflow 定义/执行绕过均拒绝 | registry 审计 + API 反向测试 | M1 | M1 本地实现与自动化门禁完成 |
| FD-024 | 不自动 seed schedule，不在 M1 猜 D/D-1/lookback | schedule storage、release process | 无 migration seed、无 fund_div 相对日特例；只保存后续运营明确意图 | 部署后默认无 fund_div 自动任务 | Definition/migration audit、schedule query | 部署后 dataset 可选但无 active schedule | 隐式 seed 或相对日期特例必须失败 | M3 前、中、后 `fund_div` schedule/probe 均为 0 | M1/M3/M4c | M1 与 M3 验证完成；M4c 仍未授权 |
| FD-025 | pagination、去重、immutable persistence 与 reject 分离 | source/normalizer/writer、summary/progress、TaskRun API/UI | 有界 pagination diagnostics + 独立 `rows_deduplicated` + inserted/matched/scope 计数；`rows_saved` 表示已成功对照的唯一事实 | 详情显示分页、源行、去重、已保存、新增、幂等命中、reject | source client、normalizer/executor/writer/progress/service、TaskRun model/schema/query、detail UI | 首次/重跑分别验证 74/0 与 0/74 inserted/matched，saved 均为 74 | 禁止无限 JSON、token 泄露、把去重当 reject、幂等重跑 saved=0 | M2 service diagnostics；M3 TaskRun `#7653=74/0`、`#7654=0/74` 且两次 saved=74/reject=0 | M1/M2/M3 | M1/M2/M3 全部验证完成 |
| FD-026 | Ops 状态/诊断写失败不得影响业务事务 | progress adapter、TaskRun/Node、business writer | 状态使用隔离 session，异常仅回滚状态事务；不得传播至 business commit | 页面可暂缺进度，但业务成功状态须可后续审计修复 | `task_run_ingestion_context.py`、executor/service、TaskRun models | 状态正常时主/节点同步 | 注入状态写失败后业务事实仍提交且可对账 | M2 故障注入并回查两类事务 | M1/M2 | M1 本地门禁与 M2 隔离真实验收均完成 |
| FD-027 | 历史回补必须先做独立预算并单独授权 | M4a/M4b、Ops TaskRun | 历史按自然年拆分，每批不超过 366；不随 M3 隐式执行 | 历史任务仅在授权后由运营创建/观察 | M4a 审计文档与后续 TaskRun 计划 | 年度计划覆盖闭区间且无重叠/遗漏 | 单 TaskRun 10,000 日或部署即回补必须被禁止 | M4a 源请求量、配额、HDD/索引/WAL、耗时预算 | M4a/M4b | 边界已冻结；预算未授权 |
| FD-028 | 四个数值字段必须精确保存，禁止 NUMERIC 静默舍入/溢出 | normalizer、ORM/migration、writer/codebook | `Decimal(str(value))`；NUMERIC(30,10) 写前精度门禁，超限结构化 reject 并使 unit fail-closed | TaskRun 通过 reason code 显示字段与处理建议 | `normalizer.py`、`codebook.py`、fund_div models/migration | 样本边界与 20 整数位/10 小数位精确写回 | 21 整数位、11 小数位及非数值输入拒绝，事实表不变 | 476 行字段剖面；M2 DB round-trip 与溢出 fixture | M0/M1/M2 | M1 本地门禁与 M2 隔离真实验收均完成 |

## 19. 发布、回滚与风险

### 19.1 发布门禁

- exact duplicate 去重、不可变公告事实和单表只插入协议已由业务拍板并回写本 LLD；
- 所有硬口径有代码点、测试和真实证据；
- Definition 全消费者审计无遗漏；
- migration head 与 HDD 真实路径复核；
- 无相关运行中任务；
- 本地、隔离、生产按阶段分别授权。

### 19.2 回滚

- 应用代码可回滚到 migration 前兼容版本，但不得自动删除已写源事实；
- migration downgrade、表删除或数据清理必须单独列清单并获授权；
- TaskRun/观测状态失败不得回滚或污染业务表事务；
- 首次生产同步或后续重跑失败时，整个 unit 回滚并保留事实表原集合；依 reason code 修复后重跑同一 ann_date。

### 19.3 剩余风险

1. Tushare 未提供稳定分红事件 ID；系统按公告事实保存，不自动关联新旧公告之间的修订关系。
2. 源端空结果或集合缩减会被 `write.immutable_scope_regression` 拦截；若未来源端确实允许撤销旧公告，需要新的、经业务授权的撤销事实模型，首版不会自动删除。
3. 当前最早日期和抽样峰值不是永久 SLA；历史回补前必须重新扫描。
4. 当日数据发布时间未定，自动任务策略仍需多时点证据。
5. exact duplicate 去重会主动放弃不可区分副本的出现次数；`rows_deduplicated` 只保留当次运行级数量，不形成长期业务事实。
6. 当前研究凭据具备 400 积分权限不代表隔离/生产凭据永久具备；权限不足必须在写事务前失败，不能留下部分事实。
7. 业务确认“修订必发新公告”是 immutable contract 的前提；若未来实测同一 identity 出现不同内容，系统将失败而不是静默改值，必须先人工核清源语义再变更设计。

## 20. 后续仍需拍板

B4-FD-M3 已完成。以下只阻塞对应后续阶段：

1. 历史安全起点是否采用 `19980327`，以及 HDD/索引/WAL、耗时和配额停止阈值；在 M4a 后决定。单 TaskRun 上限固定为 366 个自然日 unit。
2. 自动任务维护 D、D-1 还是滚动窗口，以及实际 cron 时刻；在 M4c 多时点观察后决定。

B4-FD-M3 已完成；下一独立授权边界是 B4-FD-M4a 历史规模、配额、耗时与 HDD/索引/WAL 只读预算。历史回补和 schedule 仍须分别授权。
