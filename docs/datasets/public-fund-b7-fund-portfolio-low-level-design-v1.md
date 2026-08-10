# 公募基金 B7：基金持仓（`fund_portfolio`）低层设计 v1

状态：**B7-M1 编码与本地门禁、B7-M2 隔离 PostgreSQL 验收、B7-M3 生产 migration/HDD 物理落点/首次正式 TaskRun/五段对账/幂等复跑均已通过。尚未回补历史或创建 schedule；下一门禁仅能是独立授权的 B7-M4a 历史规模与配额只读预估，或转入其他未开发数据集。**

确认日期：2026-08-08；M1 实现与本地验收：2026-08-10；M2 隔离验收：2026-08-10；M3 生产验收：2026-08-10

## 1. 结论先行

B7 的 M1/M2/M3 已完成，实现并验证了 `fund_portfolio` 的季度报告期接入，以及它必需的两项显式 opt-in 能力：

1. 自然季度末输入：运营选择一个报告期，或用起止日期展开为离散季度末；禁止把季度报告期伪装成逐日任务。
2. 页级暂存、整期发布：源端每 2,000 行读取并归一化到非服务暂存表，收到 short page 且完成全量校验后，才在一个业务事务中发布该报告期。

M3 生产首次小窗验收已通过。下列事项继续后置，不影响当前已上线能力：

- 历史回补是否从 2014Q1 开始；LLD 只提供按季度末、单任务最多四期的能力，不自动回补。
- 自动任务最终采用每周还是每月 cron；LLD 只允许普通 weekly/monthly cron 或 once，不创建任何 schedule。
- `stk_float_ratio` 的业务单位；首版只保存源值，不缩放、不解释。

主链固定为**全市场 `period` 单遍分页**。不做 A/B 双遍；`period + ts_code` 只用于已有报告期的单基金定向补录。最终只有一张 serving 事实表，没有 current/observation，也不创建 raw/core 镜像。

## 2. 目标、范围与明确不做

### 2.1 目标

- 完整保存 Tushare `fund_portfolio` 当前返回的全部 E/O 源事实，不按基金池、状态、后缀、市场或证券类型裁剪。
- 每个请求页显式传入全部 8 个 `source_fields`，固定 `limit=2000`，递增 `offset`，只以 short page 结束。
- 支持单季度与季度范围输入；一个 `period` 是一个逻辑 unit 和一个业务发布 scope。
- 页级读取、归一化、暂存后释放 Python 行内存，禁止把 1,312,798 行攒进 `rows_raw`。
- 同一完整身份、相同内容只保留一行；同一完整身份、不同内容时整个 scope fail-closed。
- 业务表、32 个叶分区、暂存表和全部索引显式落 `gs_raw_cold_hdd`；共享 WAL 保持 SSD。
- 接入 Ops“公募基金”分组，支持手动、普通自动任务和重试；无 probe、无 workflow、无自动任务 seed。

### 2.2 本期明确不做

- 不执行广泛、逐期或大规模 Tushare 探测；M2 仅对 `19980630` 做 1 次 MCP 样本请求和 1 次项目连接器最小真实同步。
- 不实现 A/B 双遍、snapshot ID 或“源端绝对静止”声明。
- 不按 `ann_date`、`start_date/end_date`、`symbol` 切全量主请求。
- 不按 `fund_basic_current` 展开 32,342 个基金请求；`fund_basic` 也不作为全市场结果的过滤器。
- 不保存 `source_occurrence_count`；完全相同的重复行只在 TaskRun diagnostics 计数。
- 不创建 observation 表，不静默覆盖同身份内容冲突。
- 不创建历史任务、生产 schedule、probe 规则或 workflow step。
- 不新增业务查询页面；Ops 只接入既有维护任务与数据集卡片契约。

## 3. 依据与当前基线

### 3.1 文档与源端依据

- [数据集接入开发模板](../templates/dataset-development-template.md)
- [B7 发现审计](fund-portfolio-onboarding-discovery-audit.md)
- [公募基金九数据集总计划](public-fund-nine-dataset-onboarding-program-plan-v1.md)
- [本地 Tushare 接口文档](../sources/tushare/公募基金/0121_公募基金持仓数据.md)
- `src/AGENTS.md`、`src/foundation/AGENTS.md`、`src/foundation/datasets/AGENTS.md`、`src/foundation/ingestion/AGENTS.md`、`src/foundation/dao/AGENTS.md`
- `docs/architecture/dataset-date-model-consumer-guide-v1.md`
- `docs/architecture/dataset-definition-single-source-refactor-plan-v1.md`
- `docs/architecture/dataset-execution-plan-refactor-plan-v1.md`

B7-M0 已有实测证据：

- `period=20250630` 全市场 1,312,798 行；按 2,000 行需要 657 个请求。
- 114 个候选季度末中，`19980331` 为空，`19980630..20260630` 连续 113 期非空。
- `start_date/end_date` 实际按公告日窗口过滤，不能表达报告期范围。
- 默认字段与显式 8 字段在样本中行多重集一致，但生产仍必须显式传 fields。
- 源接口没有 snapshot ID；单遍 offset 分页期间是否发生源端变化无法被绝对证明。

### 3.2 M1 编码前代码依据

CodeGraph 索引根为仓库根，当前为 2,123 个文件、36,288 个节点、82,257 条边。已审计：

- `DatasetDateModel.selection_rule` -> Ops Catalog/API -> 手动/自动任务前端日期控件。
- `DatasetUnitPlanner` -> resolver -> `PlanUnitSnapshot` -> request builder。
- `DatasetSourceClient` -> `IngestionExecutor` 串行/并发 fetch -> normalizer -> writer -> unit commit。
- `DatasetPlanningDefinition`、`DatasetStorageDefinition` -> Definition builder/linter/registry。
- `DatasetScheduleTimePolicyResolver` -> schedule capability、schedule 校验、TaskRun 时间生成。
- `ManualActionQueryService` -> manual action API -> `ops-v21-task-manual-tab.tsx`。

M1 编码前事实：

- `DatasetSourceClient._fetch_rows_with_pagination()` 使用 `rows_raw.extend(rows)`，不适合 131 万行 unit。
- `IngestionExecutor` 只接受完整 `SourceFetchResult`，随后整批 normalize/write/commit。
- `serving_immutable_fact_insert` 要求完整批次在内存中，只支持既有自然日不可变事实；不能直接复用。
- normalizer 已支持 `source_multiplicity_policy=deduplicate_identical` 和 batch unique 冲突，但只能发现当前内存批次内的冲突；跨页冲突必须由暂存表约束补齐。
- 当前 `DateField` 只支持自然日、自然周五和月末；当前 planner/schedule resolver 没有季度末语义。
- M1 编码前重新确认 Alembic head 为 `20260807_000130`；新 migration `20260810_000131` 已线性连接该真实 head。本文不把 migration 文本检查冒充 PostgreSQL 应用验收。

## 4. 源端请求契约

### 4.1 输入矩阵

| 场景 | 源端参数 | 结论 |
| --- | --- | --- |
| 主同步 | `period=YYYYMMDD` | 唯一全市场主路径；返回该报告期全部基金持仓披露事实。 |
| 定向补录 | `period=YYYYMMDD, ts_code=<single code>` | 只允许已有正式报告期中的一个基金；不能创建一个新的部分报告期。 |
| 禁止 | 仅 `start_date/end_date` | 实测按公告日期窗口过滤，会漏报告期事实。 |
| 禁止 | `ann_date` | 只得到一个披露批次，不是完整报告期。 |
| 禁止 | `symbol` | 缩小全市场事实范围。 |
| 禁止 | 逗号拼接多个 `ts_code` | 实测无批量语义，已知两个有效代码拼接返回空集。 |
| 禁止 | 无 `period` 的单基金历史 | 可能触发单页上限，且不能成为报告期原子发布 scope。 |

### 4.2 显式字段

生产每一页都必须显式请求并保存：

```text
ts_code, ann_date, end_date, symbol, mkv, amount, stk_mkv_ratio,
stk_float_ratio
```

请求 builder 只生成业务参数 `period`，定向补录时额外生成单个 `ts_code`。`fields/limit/offset` 继续由 source client 统一传递。任何页缺少上述字段之一都产生 `normalize.source_field_missing:<field>`，整个 scope 不发布。

### 4.3 分页

- `pagination_policy=offset_limit`
- `page_limit=2000`
- 第一页 `offset=0`，后续严格加 2,000。
- 无 `max_pages`、无总行数截断、无“达到预计行数即停止”。
- `len(page) < 2000` 才是结束；满 2,000 行后必须再请求下一页，空页是合法 short page。
- 每页都携带相同的 8 个 fields、`period` 和可选单个 `ts_code`。
- 请求失败按既有 source retry 契约处理；重试耗尽后整个 scope 失败。

## 5. 三层时间语义

### 5.1 时间输入语义

运营看到的是“报告期”：

- point：选择一个自然季度末。
- range：填写开始/结束日期，系统只展开区间内的自然季度末，不逐日请求。
- 合法季度末只有 `03-31`、`06-30`、`09-30`、`12-31`。
- 内部 TaskRun 时间 envelope 暂继续使用既有 `trade_date/start_date/end_date` 字段承载锚点；API/UI 的 label、description 和 selection rule 必须显示“报告期”，不得向运营显示“交易日”。

### 5.2 执行 / unit 语义

一个季度末生成一个 unit：

```text
unit identity = fund_portfolio:<period>
source request = {period: YYYYMMDD}
business publish scope = end_date == period
```

示例：

- point `2025-06-30` -> 一个 unit，源参数 `period=20250630`。
- range `2014-01-01..2014-12-31` -> `20140331/20140630/20140930/20141231` 四个 unit。
- range `2014-04-01..2014-06-29` -> 没有季度末，planning fail-closed，不生成空任务。

一个 TaskRun 最多四个季度 unit，即最多一个自然年的工作量。超出时返回 `planning.units_exceeded`，历史回补按年拆任务。所有 unit 串行，`fetch_concurrency=1`。

### 5.3 freshness / audit 语义

Definition 固定：

```text
date_axis = natural_day
bucket_rule = calendar_quarter_end
window_mode = point_or_range
input_shape = trade_date_or_start_end
observed_field = end_date
audit_applicable = false
```

`calendar_quarter_end` 只约束运营输入和 unit 展开，并不表示季度结束当天源端已经完整披露。首版不做连续 freshness/date-completeness audit，因为缺少权威发布完成窗口和 snapshot ID；数据集卡片只显示 TaskRun 成功时间与已发布报告期。

## 6. `DatasetDefinition` 设计

### 6.1 `fund_portfolio` Definition

| 维度 | 固定值 |
| --- | --- |
| dataset/domain | `fund_portfolio` / `public_fund` / 公募基金 |
| api/doc | `fund_portfolio` / `tushare.fund_portfolio` |
| source fields | 全部 8 字段，顺序固定 |
| request builder | `_fund_portfolio_params` |
| time | 自然季度末 point/range，observed `end_date`，audit false |
| filter | 可选单个 `ts_code`，只用于 point 定向补录 |
| universe | `no_pool`；主路径不读取 `fund_basic` 对象池 |
| pagination | `offset_limit` / 2,000 / short page / 无最大页数 |
| unit builder | `build_calendar_quarter_end_units` |
| page processing | `staged_stream`，显式 opt-in |
| delivery | `single_source_serving` / direct-serving |
| serving | `core_serving.fund_portfolio` |
| staging | `foundation.fund_portfolio_stage`，非服务、UNLOGGED |
| write path | `serving_staged_immutable_scope_publish` |
| conflict columns | `end_date, ts_code, ann_date, symbol` |
| multiplicity | `deduplicate_identical` |
| transaction | stage page persistence；business commit 仍为 unit |
| capability | manual/schedule/retry；无 probe/workflow |

### 6.2 最小共享契约，不做“基金持仓框架”

只新增三项通用、默认关闭的能力：

1. `DatasetPlanningDefinition.page_processing_mode`：默认 `buffer_all`；B7 显式为 `staged_stream`。
2. `DatasetStorageDefinition.stage_dao_name/stage_table`：默认 `None`；只有 staged write path 可填写。
3. source client 的 page iterator 与 staged publisher 协议。

B7 专属内容保持专属：字段、身份、表、分区、SQL、DAO、报告期校验、定向补录语义都不放入共享基类。禁止：

- `if definition.dataset_key == "fund_portfolio"` 出现在 source client/executor/UI。
- 改变其他数据集默认 `buffer_all` 行为。
- 把 B7 stage 做成全数据集 JSONB/EAV 公用表。
- 复用 B0 observed-snapshot 或 B4 `fund_div` 内存整批 writer。

### 6.3 Definition linter 门禁

`staged_stream` 不是一个自由字符串。linter 必须要求：

- `pagination_policy=offset_limit` 且 `page_limit > 0`。
- `fetch_concurrency=1`。
- `transaction.commit_policy=unit`。
- `write_path=serving_staged_immutable_scope_publish`。
- `stage_dao_name/stage_table/core_dao_name/serving_table/conflict_columns` 全部存在。
- direct-serving，不得同时配置 raw/std/observation。
- `source_multiplicity_policy=deduplicate_identical`。
- identity fields 全属于 `normalization.required_fields`。

反向门禁同样必须存在：非 staged write path 不得填写 stage DAO/table；既有 Definition lint 全量通过，证明其他数据集没有被隐式切换。

## 7. planner、request builder 与输入验证

### 7.1 季度 unit builder

在 `src/foundation/ingestion/unit_planner.py` 注册 `build_calendar_quarter_end_units`：

- point 必须是自然季度末，否则 `planning.quarter_end_required`。
- range 只枚举闭区间内的季度末，稳定升序。
- unit request params 只含 `period` 和可选单个 `ts_code`。
- progress context 显示 `period`，不写成 `trade_date`。
- 范围超过四期拒绝。

### 7.2 定向补录

可选 `ts_code` 不用于主路径 fan-out。填写后必须同时满足：

- 只允许 point；range 拒绝为 `planning.scoped_repair_point_required`。
- 只允许一个去首尾空格、转大写后的代码；包含逗号、空白列表或多个值时拒绝。
- 不按 `.OF/.SH/.SZ` 白名单裁剪主数据；输入仅做单值和安全字符校验。
- `core_serving.fund_portfolio` 中必须已经存在该 `period` 的任意正式事实，否则 `planning.scoped_repair_scope_missing`。
- 返回页的 `end_date` 必须等于 period，`ts_code` 必须等于请求值。

定向补录只能向已有报告期补充该基金的不可变事实；不能删除同报告期其他基金，也不能用局部结果替换全市场 scope。

### 7.3 request builder

`_fund_portfolio_params(request, anchor_date, enum_values)`：

- `anchor_date` -> `period=YYYYMMDD`。
- 可选单个 `ts_code` 归一化后透传。
- 不生成 `ann_date/start_date/end_date/symbol/market/status`。
- `period` 不是新增存储字段；源返回 `end_date` 必须与它一致。

## 8. 页流式暂存与整期原子发布

### 8.1 source client page iterator

`DatasetSourceClient` 新增通用 iterator，逐页返回：

```text
page_number, offset, rows_raw, retry_count, latency_ms, is_short_page
```

既有 `fetch()` 改为消费 iterator 并继续聚合 list，所以其他数据集行为不变。B7 executor path 直接消费 iterator，每次只持有一页原始行和一页归一化行。

### 8.2 非服务暂存事务

staged publisher 为本次 execution 持有一条专用 PostgreSQL connection；原因是页级 stage commit 后仍要保持 advisory session lock，不能让连接返回 pool。

执行开始时：

1. 用稳定 64-bit key 调用 `pg_try_advisory_lock`，锁名由 staged write path + dataset key 派生，禁止使用 Python 随机 `hash()`。
2. 锁覆盖整个 B7 execution，避免两个季度任务同时消耗配额或共用 stage。
3. 在锁内清理 B7 上次异常遗留的 stage rows，生成新的 `stage_run_id`。

每页：

1. 检查取消信号。
2. 校验 8 字段都存在、`end_date=period`；定向补录还校验 `ts_code`。
3. normalizer 转换日期/数值，页内 exact duplicate 去重，页内同身份不同内容拒绝。
4. stage DAO 用 `(stage_run_id,end_date,ts_code,ann_date,symbol)` 唯一约束写入。
5. 跨页同身份同 hash 是 exact duplicate；跨页同身份不同 hash 产生 `write.stage_identity_content_conflict`。
6. stage page transaction 提交，释放 Python 行对象。

这里的 page commit 只保存 UNLOGGED 非服务中间态，**不是业务数据 commit**：

- `rows_committed` 仍为 0。
- serving 表完全不可见这些行。
- 失败、取消或进程崩溃后不得把 stage 行显示为已完成事实。

### 8.3 full-market finalize

收到 short page 且 `rows_rejected=0` 后，在一个最终业务事务中执行集合校验和发布：

1. stage unique count 必须大于 0。
2. stage 内身份唯一且所有内容 hash 可重算一致。
3. 正式表同 `end_date=period` 的已有身份必须全部存在于 stage；否则 `write.immutable_scope_regression`。
4. 相同身份的正式 hash 与 stage hash 必须相同；否则 `write.immutable_content_conflict`。
5. 用 `INSERT ... SELECT` 一次性插入 stage 中不存在的身份；不逐行 ORM insert。
6. 通过双向 `NOT EXISTS`、冲突 count 和 scope count 证明最终正式集合与 stage 完全一致。
7. 只有上述 SQL 全部成功才 commit；首次报告期整期可见，重跑新增披露事实也整批可见。

这不是“删除后替换”：既有不可变事实不删除。所谓原子发布，是指本次新增事实只在最终事务 commit 后一起可见；源端若回退或同身份改值则整期失败。

### 8.4 定向补录 finalize

定向补录以 `(period,ts_code)` 为比较子 scope：

- stage 必须非空。
- 正式子 scope 不能有 stage 缺失身份，不能有内容冲突。
- 只插入该代码的新身份，不触碰其他代码。
- 业务提交后，正式子 scope 与 stage 集合一致。
- 不能借定向补录创建全新 period。

### 8.5 失败、取消与清理

- 任一 source/page/normalize/stage/finalize 失败：正式表不变，unit 失败。
- stage rows 在 `finally` 中 best-effort 清理；清理失败只形成 diagnostics，不能回滚已提交业务事实。
- 进程崩溃后的遗留 stage 在下次取得同一数据集锁后清理。
- advisory lock 必须在 `finally` 显式释放，再关闭专用 connection，防止连接池锁泄漏。
- stage 是 UNLOGGED；数据库 crash 后被清空是可接受行为，重试从 offset 0 重建。
- staged publisher 使用专用 data connection 完成最终业务 commit；executor 原有 session 不得再次提交或回滚该业务事务。最终 commit 后的 progress/TaskRun 状态写入仍是独立观测事务，失败只能影响任务观测，不能回滚 `core_serving.fund_portfolio`。

## 9. 字段、身份与归一化

### 9.1 端到端字段映射

| source field | 语义 | PostgreSQL | nullable | 处理 |
| --- | --- | --- | --- | --- |
| `ts_code` | 基金代码 | `TEXT` | 否 | trim + upper 只用于身份/校验；保存源值的规范化代码。 |
| `ann_date` | 公告日期 | `DATE` | 否 | `YYYYMMDD` -> date。 |
| `end_date` | 报告期末 | `DATE` | 否 | 必须等于请求 period。 |
| `symbol` | 持仓证券代码 | `TEXT` | 否 | 不按市场或后缀过滤。 |
| `mkv` | 持仓市值 | `NUMERIC` | 是 | 不限定 precision/scale，保留源十进制值。 |
| `amount` | 持仓数量 | `NUMERIC` | 是 | 同上。 |
| `stk_mkv_ratio` | 占基金净值比例 | `NUMERIC` | 是 | 原值保存，不缩放。 |
| `stk_float_ratio` | 源端比例字段 | `NUMERIC` | 是 | 原值保存；已见异常大值，不解释百分比。 |

采用不限定精度的 PostgreSQL `NUMERIC`，是为了避免源端浮点/异常大值因本地 precision/scale 限制被舍入或拒绝。M2 必须验证实际行宽与索引大小。

### 9.2 身份与内容

事实身份固定为：

```text
(ts_code, ann_date, end_date, symbol)
```

- 不同 `ann_date` 是不同披露事实，必须并存。
- 全部 8 个 source fields 参与 `source_content_hash`。
- 同身份、同 hash：exact duplicate，只保留一条并增加 diagnostics 的 `rows_deduplicated`。
- 同身份、不同 hash：整个 full period 或 repair sub-scope fail-closed，不发布、不保留 observation 版本。

最终表使用四字段复合主键，不额外保存大体积 `source_entity_key/identity_basis`。保留 `source_content_hash CHAR(64)` 用于跨页、重跑和数据库集合校验。

## 10. 表、分区、DAO 与 migration

### 10.1 正式事实表

`core_serving.fund_portfolio`：

- 8 个源字段。
- `source_content_hash CHAR(64) NOT NULL`。
- `ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()`。
- 主键 `(end_date, ts_code, ann_date, symbol)`；顺序以 period 为首便于 scope scan，语义仍是已拍板的四字段身份。
- `PARTITION BY HASH (end_date)`，固定 32 个叶分区。

选择 hash 分区而不是按年 range：

- 任意未来季度自动进入既有叶分区，不需要每年运行 DDL。
- 单 period 查询只命中一个叶分区。
- 以 148,346,174 行容量场景折算，32 个叶分区平均约 463 万行；真实分布和大小由 M2 测量。
- 不需要 DEFAULT 分区，也不会把未来自动增量落回默认 SSD。

二级索引只建查询所需的 `(ts_code,end_date DESC,ann_date DESC,symbol)`。首版不为 `symbol` 单独建索引，避免在尚无消费查询证据时放大 1.48 亿行场景的存储和 WAL。

### 10.2 暂存表

`foundation.fund_portfolio_stage`：

- `UNLOGGED`、非 serving、非数据集卡片事实源。
- `stage_run_id UUID NOT NULL`。
- 8 个源字段、`source_content_hash`、`staged_at`。
- 主键 `(stage_run_id,end_date,ts_code,ann_date,symbol)`。
- 清理索引 `(end_date,stage_run_id)`。
- 不分区；任何时刻只容纳当前 B7 execution 的页级中间态。

UNLOGGED stage 不承担事实持久性，数据库 crash 丢失只会导致 TaskRun 重试；它用于减少页级中间写入对 SSD WAL 的消耗。正式表发布仍产生正常 WAL，WAL 仍位于集群现有 SSD。

### 10.3 ORM/DAO 落点

- `src/foundation/models/core_serving/fund_portfolio.py`
- `src/foundation/models/staging/fund_portfolio_stage.py`（ORM schema 为 `foundation`，但不得进入 serving catalog）
- `src/foundation/dao/fund_portfolio_dao.py`
- `src/foundation/dao/factory.py`
- 模型注册文件与相关 registry test

`FundPortfolioDAO` 只负责：stage 批量写入/冲突比较、scope 集合 SQL、set-based publish、计数与 anti-join。连接、锁、重试、commit/rollback 和 TaskRun 进度仍由 ingestion publisher/executor 控制。

### 10.4 migration

M1 migration 必须：

1. 编码前读取真实 Alembic head，并把 `down_revision` 接到该 head。
2. 在创建任何对象前校验 `gs_raw_cold_hdd` 存在，否则整个 migration 失败。
3. 创建 partitioned parent、32 个叶分区、每个主键/二级索引、UNLOGGED stage 及其索引。
4. 对每个物理 heap/index 显式指定或 `SET TABLESPACE gs_raw_cold_hdd`。
5. 不允许默认 tablespace fallback。
6. `downgrade()` 不自动删除业务事实，直接报错。

M2/M3 必须从 `pg_class/pg_namespace/pg_tablespace/pg_partition_tree` 验证 parent、32 leaves、所有 leaf indexes 和 stage 的物理 tablespace；不能只看 ORM 或 migration 文本。

## 11. Ops、UI、schedule、workflow 与 probe

### 11.1 Catalog 与手动任务

- 在 `OPS_DATASET_DEFAULT_VIEW` 的“公募基金”中新增 `fund_portfolio`，`item_order=70`，位于 `fund_div` 之后。
- 手动任务显示“基金持仓”“报告期”“报告期范围”。
- 后端 `selection_rule=calendar_quarter_end` 是唯一事实；前端 `DateField` 增加通用 `quarter_end` 规则。
- `DateField` 只允许自然季度末；页面不得按 `fund_portfolio` action key 特判。
- 填写 `ts_code` 后，API 返回 conditional time rule，只允许 point，并解释“单基金补录只适用于已有报告期”。

### 11.2 自动任务

Definition 声明 `latest_completed_calendar_quarter` policy：

- schedule type：`cron`、`once`。
- cron repeat mode：仅 `weekly`、`monthly`；拒绝 daily/intraday，防止重复消耗数百次分页额度。
- explicit time input：forbidden。
- 生成 point 时间，内部仍放入 TaskRun `trade_date` envelope，resolver/request builder 最终生成 `period`。
- 触发日在季度末当天，仍取上一个季度；从季度末次日起取刚结束季度。例如：`2026-06-30 -> 2026-03-31`，`2026-07-01 -> 2026-06-30`。

重复定时执行是幂等的，并可原子补入后续公告事实。频率与 cron 表达式由运营后续拍板并手工创建；B7 不 seed schedule。

### 11.3 禁止能力

- 不声明 probe condition。
- schedule capability 只返回 `schedule`，后端拒绝 `probe/schedule_probe_fallback`。
- 不加入任何 workflow；现有 workflow registry 不增加 B7 step。
- 工作流和 probe 的前端无新增白名单。

## 12. 进度、对账与错误码

### 12.1 有界 diagnostics

TaskRun 保存聚合值，不保存 657 条 page 明细：

- request/page/retry count
- terminal offset、terminal page rows、observed short page
- rows fetched
- rows normalized before dedupe
- rows deduplicated
- rows staged unique
- rows inserted / matched
- rows committed
- rows rejected 与 reason counts/samples
- final scope count

在 final business commit 前 `rows_committed=0`。成功后：

```text
rows_fetched
= rows_normalized_before_dedupe + rows_rejected

rows_normalized_before_dedupe
= rows_staged_unique + rows_deduplicated

rows_committed
= rows_staged_unique
= rows_inserted + rows_matched
= final scope count（full-market）
```

定向补录最后一项改为 final `(period,ts_code)` sub-scope count。

### 12.2 新增结构化错误

- `planning.quarter_end_required`
- `planning.scoped_repair_point_required`
- `planning.scoped_repair_code_invalid`
- `planning.scoped_repair_scope_missing`
- `write.staged_scope_busy`
- `write.staged_scope_empty`
- `write.stage_identity_content_conflict`
- `write.immutable_scope_regression`
- `write.immutable_content_conflict`
- `write.staged_scope_reconciliation_failed`

错误必须进入 ingestion codebook，携带 period、可选 ts_code、page/offset 和有限样本；不得记录 token 或全页 payload。

## 13. 配置项审计

B7-M1 不新增 env/Settings/数据库运行配置。

| 项 | 来源/持久化 | 值 | 消费者 | 生效方式 |
| --- | --- | --- | --- | --- |
| source fields | Definition 代码 | 固定 8 字段 | source client、normalizer、hash | 随部署 |
| page limit | Definition 代码 | 2,000 | planner/source client | 随部署 |
| max units | Definition 代码 | 4 | planner | 随部署 |
| page mode | Definition 代码 | `staged_stream` | executor/linter | 随部署 |
| partition modulus | migration | 32 | PostgreSQL | migration |
| tablespace | migration | `gs_raw_cold_hdd` | PostgreSQL | migration，缺失即失败 |
| schedule policy | Definition 代码 | latest completed quarter；weekly/monthly/once | Ops API/TaskRun | 随部署 |
| cron/once 实例 | Ops DB，后置 | 未创建 | scheduler | 运营另行创建 |

现有 source retry 仍为共享行为；本期不擅自增加“B7 专用限速配置”。M2 先测真实请求速率，再决定是否需要独立配置审计。

## 14. 代码改动清单与影响边界

### 14.1 Foundation

- `src/foundation/datasets/models.py`
- `src/foundation/datasets/definitions/public_fund.py`
- `src/foundation/datasets/public_fund_contracts.py`
- `src/foundation/datasets/definitions/_builder.py`
- `src/foundation/ingestion/linter.py`
- `src/foundation/ingestion/unit_planner.py`
- `src/foundation/ingestion/request_builders.py`
- `src/foundation/ingestion/row_transforms.py`
- `src/foundation/ingestion/source_client.py`
- `src/foundation/ingestion/executor.py`
- `src/foundation/ingestion/writer.py` 或新建同目录的 `staged_scope_publisher.py`
- `src/foundation/ingestion/codebook.py`
- `src/foundation/dao/fund_portfolio_dao.py`
- `src/foundation/dao/factory.py`
- 两个 ORM 文件、模型注册、一个 Alembic migration

边界：保持 `foundation` 内闭环，不新增 `foundation -> ops/biz/app` 依赖；`platform/operations` legacy 目录不改。

### 14.2 Ops/API

- `src/ops/catalog/dataset_catalog_views.py`
- `src/ops/queries/manual_action_query_service.py`
- `src/ops/services/dataset_schedule_time_policy_resolver.py`
- `src/ops/services/operations_schedule_service.py`
- `src/ops/services/schedule_automation_capability_resolver.py`
- `src/ops/services/task_run_service.py`

只扩展 Definition 驱动的季度 selection/calendar policy；不加 action-key 白名单。

### 14.3 前端

- `frontend/src/shared/ui/date-field.tsx`
- `frontend/src/pages/ops-v21-task-manual-tab.tsx`
- `frontend/src/pages/ops-v21-task-auto-tab.tsx`
- 对应 component/page tests

前端只识别通用 `quarter_end`/calendar policy；不写 `fund_portfolio` key 分支，不增加第二套日期组件。

### 14.4 不受影响

- 既有数据集仍走 `buffer_all`。
- B0 observed snapshot、B4 fund_share/fund_div writer 语义不变。
- probe/workflow registry 不增加 B7。
- 业务 API 和终端用户页面不变。
- 依赖矩阵方向不变；因新增 opt-in ingestion contract，需更新对应执行架构说明，但无需修改全仓 architecture snapshot，除非 M1 实现改变主要入口。

## 15. 测试与本地门禁

### 15.1 Definition / planner / request

- 8 fields 顺序和逐页显式 fields。
- point 季度末成功；非季度末拒绝。
- range 只展开季度末；空范围和超过四期拒绝。
- 主请求只有 `period`；定向补录只有 `period+ts_code`。
- ann_date/start/end/symbol/market/status 不进入源请求。
- 单个 ts_code 只允许 point；逗号、多值、无已有 period 拒绝。

### 15.2 分页 / source client

- offsets `0,2000,4000...`。
- 每页相同显式 fields。
- short page 终止。
- 最后一页恰好 2,000 时继续请求空页。
- staged iterator 不累积历史页；既有 `fetch()` 仍聚合并保持回归。
- retry/错误/取消不发布。

### 15.3 normalizer / stage / identity

- 所有字段端到端落库；四个数值字段允许 null。
- wrong period、repair wrong ts_code、缺字段、空身份拒绝。
- 页内、跨页 exact duplicate 只留一条。
- 页内、跨页同身份不同内容均 fail-closed。
- 不生成 `source_occurrence_count`，diagnostics 只记 deduplicated count。

### 15.4 publisher / DAO / transaction

- 首次 full scope 原子插入。
- 同一 scope 重跑全部 matched、0 inserted。
- 新公告身份增量插入。
- 源 scope 回退、内容冲突、空 scope 均不改正式表。
- final publish SQL 失败完整 rollback。
- stage page commit 后 serving 仍为 0 行且 rows_committed=0。
- stage cleanup 失败不回滚已提交 serving；下次 execution 可清理遗留。
- advisory lock 防止两个 B7 execution 重叠，异常路径释放连接锁。
- repair 只影响一个 `(period,ts_code)`，不能创建新 period。

### 15.5 ORM / migration / HDD

- final parent、32 leaves、stage、PK 和二级索引字段一致。
- stage 为 UNLOGGED，final 为 LOGGED。
- 32 leaves 与全部 indexes 位于 HDD。
- 缺 tablespace 时 migration 全失败，无半成品。
- downgrade 不删事实。
- table registry/DAO factory 可解析 final/stage，但 Catalog 只暴露 final target。

### 15.6 Ops / UI / schedule

- Catalog“公募基金”顺序新增 item 70。
- manual API 返回报告期 point/range 和 quarter selection rule。
- 前端只允许季度末，labels 不显示“交易日”。
- 填 ts_code 后只保留 point。
- latest completed quarter 在季度末当天/次日边界正确。
- cron 只允许 weekly/monthly，once 允许；daily/intraday 拒绝。
- probe/fallback/workflow 均拒绝。
- 无 schedule seed。

### 15.7 回归命令

M1 至少执行：

```text
pytest -q tests/test_public_fund_b7_fund_portfolio_dataset.py
pytest -q tests/test_public_fund_b7_migration.py
pytest -q tests/test_dataset_source_client.py tests/test_dataset_unit_planner.py tests/test_ingestion_linter.py
pytest -q tests/web/test_ops_manual_actions_api.py tests/test_ops_automation_capability.py tests/web/test_ops_catalog_api.py
python scripts/check_docs_integrity.py
git diff --check
npm --prefix frontend run typecheck
npm --prefix frontend run check:rules
npm --prefix frontend run test
npm --prefix frontend run build
```

若改动页面交互，补浏览器验收：手动 point/range、ts_code 条件、自动任务能力、错误文案和网络请求。

## 16. 隔离与生产验收

### 16.1 B7-M2 隔离 PostgreSQL（2026-08-10 已通过）

本轮使用全新的本地 PostgreSQL 18.4 隔离集群，未连接生产库。隔离 tablespace `gs_raw_cold_hdd` 的真实路径为 `/private/tmp/goldenshare_b7_m2.d1Oasv/hdd_tablespace`。从全量历史 migration 建空库时，旧迁移触发 PostgreSQL `max_locks_per_transaction` 不足；仅对该临时集群调到 `2048` 后完成，未修改本机正式实例或生产配置。生产 M3 仍必须从当时真实 head 独立预检。

迁移与物理落点结果：

- 缺失 `gs_raw_cold_hdd` 时，B7 migration 按预期 fail-closed；Alembic version 保持 `20260807_000130`，未留下 B7 表。
- tablespace 恢复后，隔离库到达 `20260810_000131`。
- 32 个 final 叶分区、64 个叶索引、2 个 parent partitioned index、stage 表及其 2 个索引均实际位于 `gs_raw_cold_hdd`；stage `relpersistence=u`，final parent `relpersistence=p`。

1,312,798 行纯合成容量门禁结果（0 次 Tushare 调用）：

| 指标 | 首次完整发布 | 同源完整重跑 |
| --- | ---: | ---: |
| 页数 / 页上限 | 657 / 2,000 | 657 / 2,000 |
| stage 行数 | 1,312,798 | 1,312,798 |
| stage 用时 | 478.790 秒 | 492.363 秒 |
| final 发布用时 | 8.242 秒 | 1.979 秒 |
| inserted / matched | 1,312,798 / 0 | 0 / 1,312,798 |
| stage→final / final→stage 差集 | 0 / 0 | 0 / 0 |
| Python RSS | 146.67 MiB 起步，199.73 MiB 峰值；40 万行后不再增长 | 199.73 MiB 峰值 |

首次完整发布的物理测量：

- stage 峰值 `359,432,192` bytes；final 叶表 `227,459,072` bytes，叶索引 `276,070,400` bytes。
- 隔离 HDD tablespace 从 `2,722,112` 增至 `864,846,752` bytes；这是包含 stage、final、索引和该 tablespace 其他隔离对象的实测增量，不外推为生产永久容量。
- UNLOGGED stage 阶段 WAL LSN 差量 `256,832` bytes；首次 final 发布 WAL LSN 差量 `643,120,480` bytes。WAL 仍位于 PostgreSQL 全局 WAL 目录，不随业务表 tablespace 迁移。
- 同身份异内容返回 `immutable_content_conflict`，final 行数保持 1,312,798；模拟第 3 页后中断时已提交 stage 6,000 行、final 0 行；注入 final insert 失败后事务回滚，final 0 行。
- 两条独立物理连接并发验证：第二会话得到 `staged_scope_busy`；第一会话释放后第二会话可获得 advisory lock。

真实最小同步固定 `period=19980630`，调用预算为 1 次 MCP 样本请求加 1 次项目连接器请求；容量门禁没有调用源站。项目连接器请求明确携带全部 8 个 fields，参数为 `period=19980630, offset=0, limit=2000`，首个 short page 返回 42 行，因此未产生第二页请求。五段对账如下：

- 源端 42 行；归一化唯一 42 行；exact duplicate 0；reject 0、reason `{}`。
- stage/finalize scope 42 行；写入并提交 42 行；正式目标表 42 行；发布后 stage 清理为 0 行。
- 源身份与 final 身份双向差集均为 0；final 42 行按规范算法只读重算 `source_content_hash`，不一致 0 行。
- 初版审计脚本曾直接读取 normalizer 行中的不存在的 `source_content_hash`，产生 42/42 的伪差集；该指标已判为验证脚本错误，不作为数据结论，并由上述只读重算结果纠正。未为纠正脚本再次请求源站。

### 16.2 B7-M3 生产（2026-08-10 已通过）

生产只读预检时，远程代码为 `56779912`，Alembic head 为 `20260807_000130`；无 queued/running/canceling TaskRun，无正在运行的日期完整性审计，无非 idle 应用会话。`fund_portfolio` 的 schedule 和 probe rule 均为 0，target/stage 表尚不存在。`gs_raw_cold_hdd` 真实路径为 `/data/disk/postgresql/tablespaces/gs_stk_mins_hdd`；SSD/WAL 所在根盘剩余约 `21.25 GB`（使用率 91%），HDD 剩余约 `342.55 GB`。应用角色无权执行 `pg_ls_waldir()`，因此 M3 记录的是 WAL 所在根文件系统剩余容量，不把它误写成已测得精确 WAL 目录字节数。

生产部署后远程代码为 `3d9c9811`，工作区干净，Alembic 成功从 `20260807_000130` 到达 `20260810_000131`；六个 systemd 服务和两个健康检查均通过。部署通用默认源治理 seed 为新数据集创建了 1 条 mapping rule、1 条 cleansing rule、1 条 resolution policy 和 1 条 source status；它们是源治理元数据，不是 schedule、probe 或 TaskRun。

物理落点从 PostgreSQL system catalog 核验：

- `core_serving.fund_portfolio` 包含 1 个 partition parent、32 个物理叶分区、2 个 parent partitioned index 和 64 个物理叶索引。
- `foundation.fund_portfolio_stage` 为 1 个 UNLOGGED 表，带 2 个物理索引。
- 上述所有对象均显式属于 `gs_raw_cold_hdd`；所有可物理定位的 leaf/index/stage 对象都能解析到 `pg_tblspc` 路径，非 HDD 对象数为 0。

正式验收固定 `period=19980630`。本次 M3 只产生 3 次 Tushare 请求：1 次生产 connector 只读基线、1 次首次 TaskRun、1 次幂等 TaskRun；每次都是 1 个 short page，未扫描历史。只读基线显式请求全部 8 个 fields，参数仅为 `period=19980630`，`limit=2000`、`offset=0`：源端 42 行，归一化前 42，唯一 42，deduplicated 0，reject 0，reason `{}`。按排序后的“完整身份 + 内容散列”计算的规范摘要为 `bf447451342cb7b8ba20f64e8446c5743977d1f5ddab633287e741dbce3a652c`。

首次正式 TaskRun `#7813` 成功：

- unit `1/1/0`，fetched/saved/deduplicated/rejected 为 `42/42/0/0`，reject reason `{}`，TaskRun issue 0。
- diagnostics 记录 1 页、terminal offset 0、terminal rows 42、retry 0、以 short page 结束。
- persistence 为 `normalized_before_dedupe=42`、`inserted_new=42`、`matched_existing=0`、`scope_existing_count=0`、`scope_source_unique_count=42`、`final_scope_count=42`。
- 源端与目标表均为 42 个唯一身份，规范摘要一致，目标表重算 `source_content_hash` 不一致为 0，stage 清理后为 0。

幂等复跑 TaskRun `#7814` 成功：

- unit `1/1/0`，fetched/saved/deduplicated/rejected 仍为 `42/42/0/0`，reject reason `{}`，TaskRun issue 0。
- `inserted_new=0`、`matched_existing=42`、`scope_existing_count=42`、`scope_source_unique_count=42`、`final_scope_count=42`。
- target 仍为 42 行，所有 `ingested_at` 保持首次写入时间 `2026-08-10 11:53:32.502846+08`，摘要不变，stage 为 0。

源端与目标端的规范集合计数均为 42且摘要相同，因而本次有界单页 scope 的双向集合差异为 0。该证据仅验收了这个单页 period；它不是 A/B 快照证明，也不消除长分页中源端变动导致 offset 漂移的已知风险。M3 未创建 schedule、probe 或 workflow，未回补历史。

## 17. 里程碑与授权边界

| 里程碑 | 范围 | 状态/授权 |
| --- | --- | --- |
| B7-M0 | 源端、历史存在性、分页、容量、代码影响面 | 已完成 |
| B7-LLD | 本文与硬口径审计 | 本轮完成 |
| B7-M1 | Definition、季度契约、staged stream、表/DAO/migration、Ops/UI、测试 | 已完成编码与本地门禁 |
| B7-M2 | 隔离 migration、HDD、真实小窗、131 万行容量/回滚/锁 | 已完成并通过（2026-08-10） |
| B7-M3 | 生产预检、migration、首次 period、对账/幂等 | 已完成并通过（2026-08-10，TaskRun `#7813/#7814`） |
| B7-M4a | 历史起点、逐期规模/额度只读预算 | 待独立授权；不能按日扫描 |
| B7-M4b | 按年、每任务最多四期历史回补 | 待独立授权；不得与 B6 大回补并发 |
| B7-M5 | 运营手工创建 weekly/monthly cron 或 once | 频率拍板后另行授权 |

若历史从 2014Q1 到 2026Q2，共 50 个季度；按 2025Q2 的保守统一场景约 32,850 次请求。该数字是容量场景，不是逐期精确请求量，也不授权实际请求。

## 18. 硬需求追溯账本

| 硬口径 | 代码落点 | 测试/验收 |
| --- | --- | --- |
| 全市场单遍 `period` 主路径 | Definition/request builder/planner | 请求参数负向测试、M2 真实 scope、M3 `#7813/#7814` |
| 8 fields 显式请求并保存 | contracts/source client/normalizer/ORM | 每页 fields、缺字段、E2E schema、M3 生产 connector 基线 |
| 2,000 分页、无页上限、short page | Definition/source iterator | offset/空尾页/长分页测试、M3 单页 diagnostics |
| 页级暂存、unit 业务发布 | executor/staged publisher/stage DAO | 中途失败 final 不变、rows_committed=0 |
| 不做 A/B 双遍 | source path 仅一条 iterator | request count 与 diagnostics |
| 一季度一个 unit，范围只展开季度末 | date model/unit planner | point/range/非法日期/最多四期 |
| ts_code 仅定向补录 | input model/planner/request/publisher | point-only、已有 period、子 scope |
| 同身份同内容去重 | normalizer/stage unique/hash | 页内/跨页 duplicate |
| 同身份异内容 fail-closed | stage/final conflict SQL | 冲突 final 不变 |
| 单事实表，无 observation/raw/core 镜像 | storage/ORM/migration | registry/schema audit |
| 32 个 HDD hash leaves，stage/index HDD | migration | M2/M3 `pg_class/pg_tablespace/pg_partition_tree` 物理落点 |
| WAL 留 SSD，stage UNLOGGED | migration/运行审计 | M2 relpersistence/LSN 差量；M3 SSD 根盘水位 |
| 公募基金分组，手动+普通定时，无 probe/workflow | catalog/capability/UI | API/前端正反向测试；M3 TaskRun 正式主链 |
| 不自动创建任务 | 无 schedule/probe seed | M3 schedule/probe 表只读检查均为 0 |

## 19. 发布、回滚与剩余风险

### 19.1 发布门禁

- M1 全部测试与计划对账通过。
- M2 真实小窗、131 万行容量、HDD、WAL、回滚、锁已全部通过。
- M3 已确认生产无冲突任务、磁盘水位和 migration head，并完成发布验收。
- 任一 reject、集合差异、scope regression 或 content conflict 都不得放行。

### 19.2 回滚

- 代码可回滚到部署前版本。
- 未使用的数据表保留，不自动 downgrade 删除源事实。
- 失败的 stage 可在锁内清理；正式表只通过业务事务提交，不用手工删表回滚。
- 若已发布数据存在经证实的错误，必须另立修复方案、列出 scope 和备份，不在本 LLD 中授权删除。

### 19.3 剩余风险

1. **单遍 offset 漂移**：源端没有 snapshot ID；长分页期间新增/排序变化可能导致首次同步遗漏或重复。exact duplicate 和既有 scope regression 能发现一部分问题，但不能证明首次单遍绝对静止。这是用户选择不做 A/B 后保留的已知风险，文档和验收不得把“可能完整”写成“绝对证明”。
2. **首次大事务 WAL**：M2 的 1,312,798 行合成首次发布产生 `643,120,480` bytes WAL，而 M3 只验收了 42 行小 scope。历史回补前必须重新实测 SSD 水位并保留停止阈值；M2 数据不能直接等同生产行宽与压缩效果。
3. **真实历史容量未知**：113 期存在性已证明，但逐期精确行数未扫描。历史回补前仍需 M4a 预算，不能每天或逐基金浪费额度。
4. **比例字段语义**：`stk_float_ratio` 已见异常大值；只保真，不向终端用户解释为百分比。
5. **自动任务成本**：一次最新季度可能约 657 次请求；因此 contract 禁止 daily/intraday，最终 weekly/monthly 频率仍需运营拍板。

## 20. M3 之后的待拍板项

1. 历史起点是否正式定为 2014Q1；若是，M4a/M4b 以 50 个离散季度、按年四期执行。
2. schedule 采用 weekly 还是 monthly，以及具体 cron 时间；不得在 B7-M1/M2/M3 自动创建。

## 21. B7-M1 实现对账（2026-08-10）

M1 已逐项落地：

- `DatasetDefinition` 固定季度末 point/range、单任务最多四期、显式 8 fields、`limit=2000`、单个可选 `ts_code` 定向补录与 `staged_stream` opt-in。
- 通用 source page iterator 保留既有 `fetch()` 聚合行为；B7 executor 逐页归一化，只把当前页交给 stage，不累计完整报告期 Python list。
- B7 专属 DAO 负责跨页 exact duplicate、同身份异内容拒绝、既有 scope 回退、内容冲突、集合发布与最终行数对账；共享 publisher 只负责专用连接、session advisory lock、页级 stage commit、unit 最终事务和清理。
- final/stage 显式列 ORM、DAO factory、table registry 与 migration 已完成；migration 定义 32 个 HDD hash leaves、HDD indexes 和 HDD UNLOGGED stage，缺 tablespace fail-closed，downgrade 不删事实。
- Ops Catalog、手动报告期控件、通用 `quarter_end` 前端规则、Definition 驱动的 weekly/monthly cron 与 once 能力已经接入；没有数据集 action-key 白名单、probe、workflow 或 schedule seed。
- 定向后端测试覆盖分页、planner、normalizer、executor、DAO、迁移文本、Catalog/manual/schedule API 与既有公募基金回归；前端 typecheck、规则检查、全量 Vitest 与 production build 通过。PostgreSQL DDL、真实 HDD placement、advisory lock 并发、131 万行容量和真实源五段对账已在 B7-M2 独立完成。

## 22. B7-M2 验收结论（2026-08-10）

B7-M2 通过。M1 的 staged stream、集合发布、不可变冲突、事务回滚、advisory lock、HDD fail-closed 与物理落点均获得真实 PostgreSQL 证据；最小真实同步的五段数量一致且没有 reject。M2 在当时只放行独立授权的 B7-M3，不曾授权生产 migration、生产同步、历史回补或 schedule 创建；M3 后续已在独立授权下完成，见第 23 节。

## 23. B7-M3 生产验收结论（2026-08-10）

B7-M3 通过。生产 migration 已到达 `20260810_000131`，final parent/32 leaves/66 个 final indexes 与 UNLOGGED stage/2 个 stage indexes 全部物理落于 `gs_raw_cold_hdd`。TaskRun `#7813/#7814` 完成了 42 行单页 scope 的首次写入和幂等复跑：源端、归一化、业务提交、reject 和目标表对账一致，无 reject、无 TaskRun issue、无 hash 不一致，stage 最终为 0。

本结论只放行已部署的单季度同步能力，不授权历史规模扫描、历史回补或 schedule 创建。长分页 offset 漂移、生产历史行宽/容量和 SSD/WAL 水位仍是 M4a/M4b 的独立门禁。
