# Dagster Index Daily Raw By-Date Prod DB Migration Plan

状态：方案设计，未实现。

LLD：[`dagster-index-daily-raw-by-date-prod-db-migration-low-level-design.md`](./dagster-index-daily-raw-by-date-prod-db-migration-low-level-design.md)。

## 目标

将指数日线 `index_daily` 从当前的 `raw_tushare_index_daily_by_code[ts_code]` 迁移为 `raw_index_daily[trade_date]`：

1. 历史数据先在当前 Dagster 新湖内完成原地物理布局转换：把开发前只读 profiling 确认的现有 `raw_tushare_index_daily_by_code[ts_code]` 文件，无损转换为 `raw_index_daily[trade_date]` 文件；当前全量输入样本范围是 `2000-01-04` 到 `2026-06-23`，ready baseline cutoff 候选是 `2026-06-22`，不得写成实现里的固定日期常量。
2. 日更默认源从 Tushare 切换到远程 prod DB 后，Dagster 从当前 Lake `raw_index_daily` 最新已就绪交易日之后的第一个 expected trade date 开始，从 `core_serving.index_daily_serving` 同步指数日线到 raw 层；起点由文件事实和交易日历计算，不硬编码具体日期。
3. raw 层与 silver 层使用同一个运行时 Lake 期望 code set。raw 不再按代码拆分物理资产；日更每次运行时读取本机 Dagster `cn_a_index_ts_codes` dynamic partitions，当前迁移审计基线是 946 个指数代码。
4. `core_serving.index_daily_serving` 在目标交易日没有覆盖本次运行的 Lake 期望 code set 时，不允许向 Lake 发起日更；prod 上存在额外 code 不阻断，DG 只读取和校验自己本次要的 code。sensor 必须 fail closed，返回明确 skip/block 原因。
5. 只有在 `raw_index_daily[trade_date]` 历史文件转换、校验和 runless materialization/check event 补录全部成功后，才删除 active `raw_tushare_index_daily_by_code` 资产、checks、job、sensor 依赖和物理旧文件；Dagster DB 中旧 index daily 状态/事件清理由独立 P9 阶段处理，不能成为新日更链路启用前置条件。
6. 历史补录必须使用 runless event；必须先 dry-run、再样本 apply、再分批 full apply、最后只读验收。性能门禁是硬门禁。

本方案不让 raw 层提前承担 silver 职责：raw 仍保存源事实镜像字段，不做 silver 的日期类型、字段改名或业务标准化。

## 依据与代码审计

已审计当前实现：

| 模块 | 当前代码事实 | 迁移影响 |
| --- | --- | --- |
| `assets/index_daily.py` | `raw_tushare_index_daily_by_code` 使用 `cn_a_index_ts_codes` 分区，写 `raw/tushare/index_daily_by_code/ts_code=<TS_CODE>/part-000.parquet`；`silver_index_daily` 使用 `cn_a_index_trade_days` 分区，并读取所有 registered raw-by-code 文件。 | 需要新增/替换为 by-date raw asset；silver deps 与读取逻辑必须切到 by-date raw。 |
| `checks/index_daily_checks.py` | raw checks 全部围绕 by-code 文件，包括 file exists、row count、schema、partition code、unique key。 | 需要改为 by-date checks，并增加代码覆盖检查。 |
| `sensors/index_daily_sensor.py` | 读取 `cn_a_index_ts_codes`，对最早 raw 缺口日期选择一批缺失 code，最多每 tick 500 个 run；run key 当前是 `index_daily:<trade_date>:<ts_code>`。 | 需要改成每个 trade date 一个 raw run，不再提交 per-code run。 |
| `sensors/silver_index_daily_sensor.py` | 用 DuckDB 审计 raw-by-code 文件事实，确认目标交易日所有有效 code raw ready 后触发 silver。 | 需要改为读取 `raw_index_daily[trade_date]` readiness。 |
| `sensors/index_daily_raw_file_readiness.py` | 当前 raw gap/readiness helper 以 by-code 文件集合为事实。 | 需要替换为 by-date 文件事实 helper。 |
| `asset_guards/market_major_indices_lake_readiness.py` | 当前仍引用 `raw_index_daily_by_code_path`。 | 需要切到 silver 或 by-date raw，不能继续依赖旧物理布局。 |
| `jobs/index_daily_update.py` | `index_daily_update_job` selection 是 `raw_tushare_index_daily_by_code` + raw checks。 | 需要改为 `raw_index_daily` + raw by-date checks。 |
| `run_contracts/configs.py` | run config op key 是 `raw_tushare_index_daily_by_code`，只暴露 `trade_date/write_mode`。 | op key 要改为新 asset；配置字段可保持业务层简洁。 |
| `run_contracts/asset_column_schemas.py` | raw schema 字段为 Tushare 源镜像：`trade_date` 是 `VARCHAR YYYYMMDD`，字段名是 `change`。silver schema 才使用 `DATE` 和 `change_amount`。 | 新 by-date raw 必须沿用 raw 字段契约，不得输出 silver 字段。 |
| `resources.py` | 已有 `ProdPostgresResource`，通过 env 拼只读 Postgres 连接，并可供 DuckDB `postgres_query`/attach 模式复用。 | 新 prod-core-db source adapter 应复用该资源和只读连接模式。 |
| `lake_console/backend/app/services/prod_core_db.py` | 已有 `prod-core-db` 白名单导出能力：`index_daily/index_weekly/index_monthly` 映射到 `core_serving.index_*_serving`，禁止 `select *`，禁止 `source/created_at/updated_at`，并已有 `change_amount AS change` 字段映射；但当前 backend query 只按 trade date/range 取数，没有按 DG code set 过滤。 | LLD 不能重新发明近义字段口径；Dagster 实现必须对齐字段白名单和安全门禁，但不能跨区直接引用 backend 文件，必须在 orchestrator 内实现带 code set 过滤的只读 adapter。 |
| `run_contracts/metadata.py` / `catalog/lake_assets.py` | `SourceSystem` 目前没有 `PROD_CORE_DB`；`_tushare_raw_entry(...)` 会强制写 `SourceSystem.TUSHARE`、`DataContractSource.TUSHARE_RAW_CONTRACT` 和 `IngestionSource.TUSHARE_API`。 | `raw_index_daily` 不能继续套 `_tushare_raw_entry(...)`；需要新增 `SourceSystem.PROD_CORE_DB`，并用 `_entry(...)` 或新的 prod-core helper 写字段级 catalog 口径。 |
| `catalog/lake_assets.py` | catalog 记录当前 raw-by-code path 和 checks。 | 迁移时必须同步 catalog，旧资产删除后 active catalog 不得残留旧口径。 |

旧设计文档 `dagster-phase-3-index-daily-refactor-design.html` 曾将 raw 改为 by-code，是为了适配 Tushare 单 code 请求和单 code 修复；本方案是新的替代方案。by-code 在迁移期只作为审计参考，最终不再是 active 资产。

2026-06-23 P0 只读 profiling 重新确认的事实：

| 项 | 观测值 |
| --- | --- |
| 当前 DG raw-by-code parquet 文件数 | 946 个 `part-000.parquet` |
| 当前 DG raw-by-code 行数 | 3,419,666 行 |
| 当前 DG raw distinct `(ts_code, trade_date)` | 3,419,666 个 |
| 当前 DG raw distinct trade dates | 6,793 个 |
| 当前 DG raw distinct ts_code | 946 个 |
| 当前 DG raw 日期范围 | `2000-01-04` 到 `2026-06-23` |
| 当前 DG raw 重复 key / 空 key | 0 / 0 |
| 当前 DG raw OHLC/pre_close 任一为空 | 369,425 行；raw check 不得要求 OHLC 全非空 |
| 当前目标 by-date raw 路径 | `/Volumes/datasource/data_lake/raw/index_daily` 不存在，`trade_date=*/part-000.parquet` 为 0 |
| 本机 Dagster `cn_a_index_ts_codes` dynamic partitions | 946 个 code |
| 本机 Dagster code set hash | `6f8f560f11cdce10e4cd5a096c64a4c9`，按 code 排序后 `md5(string_agg(code, ','))` |
| 远程 prod `ops.index_series_active(resource='index_daily')` | 1216 个 code |
| 远程 prod `core_serving.index_daily_serving` 日期范围 | `2004-12-31` 到 `2026-06-22` |
| 远程 prod `core_serving.index_daily_serving` 总行数 / distinct pair | 1,827,704 / 1,827,704 |
| 远程 prod `core_serving.index_daily_serving` distinct code | 1216 个 |
| 远程 prod 最新 trade date | `2026-06-22`，当日 1212 个 code |
| `dg_codes - prod_index_daily_active_pool` | 0 个 |
| `dg_codes - prod_index_daily_serving_distinct_codes` | 0 个 |
| `dg_codes - prod_latest_trade_date_codes` | 0 个 |
| prod serving 全历史 code 不在 DG 中的数量 | 270 个 |
| prod latest trade date code 不在 DG 中的数量 | 266 个 |
| 全量 by-code 输入转换估算 | 6793 个 by-date 文件；materialization 6793 条、raw check 13,586 条、总 runless event 20,379 条 |
| ready baseline 建议估算 | 截止 `2026-06-22` 共 6792 个 by-date 文件、3,419,656 行；materialization 6792 条、raw check 13,584 条、总 runless event 20,376 条 |

P0 报告文件：

- `/private/tmp/index_daily_p0_20260623_dg_code_summary.tsv`
- `/private/tmp/index_daily_p0_20260623_code_set_summary.tsv`
- `/private/tmp/index_daily_p0_20260623_prod_serving_schema.tsv`
- `/private/tmp/index_daily_p0_20260623_prod_serving_summary.tsv`
- `/private/tmp/index_daily_p0_20260623_prod_serving_latest_summary.tsv`
- `/private/tmp/index_daily_p0_20260623_by_code_summary.tsv`
- `/private/tmp/index_daily_p0_20260623_by_code_cutoff_candidate.tsv`
- `/private/tmp/index_daily_p0_20260623_by_code_ready_baseline_estimate.tsv`

这些数量是 P0 时点的只读 profiling 基线。P1/P2 可以按该基线开发；P3/P4 在正式写 lake/event 前必须重新执行同类只读 profiling，不能直接沿用历史样本。

2026-06-23 P-1 执行前只读审计发现的 prod serving 缺口：

| ts_code | serving 最后有数日期 | 缺口开始 | 缺口截止 | 缺失交易日数 |
| --- | --- | --- | --- | ---: |
| `480055.CNI` | `2026-05-13` | `2026-05-14` | `2026-06-22` | 27 |
| `480056.CNI` | `2026-05-13` | `2026-05-14` | `2026-06-22` | 27 |
| `480057.CNI` | `2026-05-13` | `2026-05-14` | `2026-06-22` | 27 |
| `931598.CSI` | `2026-05-08` | `2026-05-11` | `2026-06-22` | 30 |

上述 4 个缺口不在本机 Dagster `cn_a_index_ts_codes` 中；如果本迁移的 Lake 期望集合继续沿用 DG dynamic partitions，这 4 个缺口本身不阻断 Lake raw 更新。

但追加对账发现：DG 当前管理 946 个 code，其中 86 个不在 prod `core_serving.index_daily_serving` 全历史中。因此，本迁移不能直接把 prod `index_daily` active pool 写成 Lake 期望集合，也不能直接假设 prod serving 已覆盖本地 DG 管理集合。正式实现前必须先形成迁移审计基线，并确认日更运行时 code set 来源：

1. 若继续按当前实现，以 `cn_a_index_ts_codes` dynamic partitions 作为 DG 管理集合，则 source completeness gate 必须检查 prod serving 是否覆盖这 946 个 code；当前 86 个缺口是硬阻断。
2. 若决定改为 prod `index_daily` active pool，则必须设计 DG dynamic partitions、旧 raw/silver 文件、checks、runless events 的迁移和清理，不能只改 source gate。

### 开发前强制前置步骤：prod active pool 与 86 个 DG 代码历史补齐

本步骤必须在任何迁移代码开发前完成。若本步骤未通过最终验收，本方案不得进入 M0 之后的开发阶段。

目标：

1. 确保 prod `ops.index_series_active(resource='index_daily')` 覆盖当前 DG 管理的全部指数日线代码。
2. 保持 Lake/DG 的日更同步集合仍为运行时 Lake 期望 code set；当前迁移审计基线为 `cn_a_index_ts_codes` 的 946 个代码。prod active pool 只是 prod source 门禁和生产 serving 写入门禁，不得反向定义 Lake 期望集合。
3. 对新增进入 prod `index_daily` active pool 的 DG 缺口代码，按新湖 `silver/index_daily` 的实际历史 pair 补齐 prod `core_serving.index_daily_serving`，再允许本迁移从 prod serving 读取。

2026-06-23 只读审计得到的当前缺口：

| 项 | 当前观测 |
| --- | ---: |
| DG `cn_a_index_ts_codes` | 946 个 |
| DG 管理但不在 prod serving 全历史中的 code | 86 个 |
| 这 86 个在 `ops.index_series_active(resource='index_daily')` 中 | 0 个 |
| 这 86 个在 `ops.index_series_active(resource='index_daily_raw')` 中 | 86 个 |
| 这 86 个当前 prod raw 行数 | 2,837 行 |
| 这 86 个 P-1 写入前 prod serving 行数 | 0 行 |
| 这 86 个 `index_basic.list_date` 范围 | `2023-03-13` 到 `2025-07-21`，仅作审计字段 |
| 已废弃的旧 `list_date` 口径估算 serving 行数 | 47,656 行 |
| 新湖 `silver/index_daily` 中这 86 个 code 的全量可补 serving 行数 | 154,160 行 |
| 其中早于旧 `list_date` 口径的行数 | 106,720 行 |
| P-1 写入前 prod serving 缺口 | 154,160 行 |

注意：`2026-05-06` 到 `2026-06-22` 的 33 个交易日只是 prod raw 当前已有的局部缓存窗口，不是历史补齐范围。`core_serving.index_basic.list_date` 也不再作为补 prod serving 的起始日期，因为已核实源站存在“指数日线早于 list_date”的真实情况。正式补齐范围改为：当前 DG 缺口 86 个 code 在新湖 `silver/index_daily` 中实际存在的全部 `(ts_code, trade_date)`，并按批准目标交易日做上界裁剪；新湖不存在的日期不补、不造数。

执行步骤：

1. 重新生成迁移审计基线快照：
   - 从本机 Dagster instance 只读导出 `cn_a_index_ts_codes`。
   - 从 prod 只读导出 `ops.index_series_active(resource='index_daily')`、`ops.index_series_active(resource='index_daily_raw')`、`core_serving.index_daily_serving` distinct code。
   - set diff 必须使用 SQL set operation 或统一 `LC_ALL=C sort` 后比较；禁止直接依赖不同数据库 `ORDER BY` 结果做 `comm`。
2. 生成待补 code 清单：
   - `dg_codes - prod_index_daily_active_pool` 必须列出明细。
   - `dg_codes - prod_index_daily_serving_distinct_codes` 必须列出明细。
   - 当前预期两者交集是 86 个；若重新审计数量变化，必须以最新只读报告为准，并先更新本方案。
3. 生成历史补齐计划：
   - 读取新湖 `silver/index_daily` 中待补 code 的全部实际 `(ts_code, trade_date)`，按批准目标交易日做上界裁剪。
   - `core_serving.index_basic.list_date/exp_date` 只进入审计报告，用于说明哪些行早于当前 prod 基础信息中的 list_date；不得用它过滤待补行。
   - 对比新湖 silver pair 与 prod `core_serving.index_daily_serving` 已有 pair，输出 serving gap、重复 key、字段空值和样本。
   - prod `raw_tushare.index_daily` 当前只有局部缓存窗口，本步骤不再要求补齐 prod raw；若未来要补 prod raw，必须另起专项方案和审批。
4. 补 prod active pool：
   - 仅在用户批准后执行生产写入。
   - 写入 `ops.index_series_active(resource='index_daily')` 的待补 code。
   - `first_seen_date/last_seen_date/last_checked_at` 是审计字段，不参与 Lake 期望集合定义；写入值必须来自本次补齐计划中的实际 source 覆盖范围和执行时间。
   - 不得把 `index_daily_raw` resource 行当作 `index_daily` resource 复用或改名。
5. 补 prod serving 历史：
   - 本 P-1 补数来源改为新湖 `silver/index_daily`，目标只补 prod `core_serving.index_daily_serving`；不要求同步补 prod `raw_tushare.index_daily`。
   - 写入前必须确认待补 code 已进入 prod `ops.index_series_active(resource='index_daily')`，保持 prod serving active gate 的业务含义。
   - 字段映射以当前 serving 表字段为准：新湖 silver 已是 `change_amount`，不得再套 raw `change -> change_amount` 转换；不得把 Lake 或 prod 的系统字段 `source/created_at/updated_at` 当成业务数据搬运。
   - 写入必须按 `(ts_code, trade_date)` 幂等 upsert，先 dry-run、再 sample、再 full；任何生产写入都必须单独审批。
   - 目标不是只补 33 个交易日，也不是按 list_date 截断，而是补齐新湖 silver 中 86 个 code 的完整实际历史 pair。
6. 最终只读验收：
   - `dg_codes - prod_index_daily_active_pool = empty`。
   - `dg_codes - prod_index_daily_serving_distinct_codes = empty`。
   - 对 86 个待补 code，新湖 `silver/index_daily` 中批准范围内的 `(ts_code, trade_date)` 与 prod `core_serving.index_daily_serving` 对账，missing pair 为 0。
   - 旧 `list_date` 口径只作为异常审计报告，不作为验收门槛。
   - 目标交易日 `core_serving.index_daily_serving` 必须完整覆盖运行时 Lake 期望 code set。

停止条件：

1. prod active pool 仍缺任何 DG code。
2. 86 个历史补齐后 prod serving 仍缺任何新湖 silver 已存在的 code/date。
3. 无法解释重复 key、字段映射或 row count 差异。
4. 补齐计划试图改用 prod active pool 反向定义 DG/Lake 同步集合。

只有该前置步骤最终验收通过，才允许进入本迁移的 M0。

2026-06-23 P-1 执行结果：

1. prod `ops.index_series_active(resource='index_daily')` 已覆盖 DG 当前 946 个 code；`dg_codes - prod_index_daily_active_pool = 0`。
2. 从新湖 `silver/index_daily` 导出的 86 个 repair code payload 为 154,160 行、86 个 code、154,160 个唯一 `(ts_code, trade_date)`，日期范围 `2004-12-31` 到 `2026-06-22`。
3. 其中 106,720 行早于旧 `index_basic.list_date` 口径；按最新确认口径，这些行已纳入 prod serving 补齐范围。
4. payload 无重复 key；`open/high/low/close/pre_close` 任一为空的行 85,600 行，`change_amount/pct_chg` 任一为空的行 42 行。prod `core_serving.index_daily_serving` 的业务行情字段均允许 NULL，因此不构成写入阻断。
5. 已将上述 154,160 行幂等 upsert 到 prod `core_serving.index_daily_serving`；不写 prod `raw_tushare.index_daily`，不写 Lake，不写 Dagster event。
6. 写后只读验收通过：prod serving distinct code 从 1130 变为 1216，`dg_codes - prod_index_daily_serving_distinct_codes = 0`；86 个 repair code 的 prod serving pair 为 154,160，和 payload pair 完全一致；字段级 diff 为 0。
7. 目标交易日 `2026-06-22` 验收通过：prod serving 当日有 1212 个 code，覆盖 DG 946 个 code 的缺口为 0；额外 266 个 prod code 不阻断 DG 日更。

## 目标口径

### 资产与分区

| 层级 | 目标资产 | 分区 | 物理路径建议 | 说明 |
| --- | --- | --- | --- | --- |
| Raw | `raw_index_daily[trade_date]` | `cn_a_index_trade_days` | `raw/index_daily/trade_date=<YYYY-MM-DD>/part-000.parquet` | source-neutral raw 路径；历史段由当前 DG raw-by-code 转换写入，日更切换后由 prod-core-db 写入。 |
| Silver | `silver_index_daily[trade_date]` | `cn_a_index_trade_days` | 不变 | 从同日 raw by-date 文件生成 silver。 |

不建议继续使用 `raw/tushare/index_daily/...` 作为新 by-date 路径。长期业务事实源统一认定为 prod-core-db，即 `SourceSystem.PROD_CORE_DB`；历史段从当前 DG raw-by-code 文件重排只是一次物理迁移输入，不进入 source system 语义。materialization metadata 只记录迁移方法、输入摘要和审计报告路径，不把历史 by-code/Tushare 写成数据来源。

### 代码集合

`cn_a_index_ts_codes` 不再作为 raw asset partition key，但它是当前实现里 DG 管理的指数代码集合事实源。代码集合不能再凭设计猜测，必须区分迁移审计基线和运行时集合：

1. 迁移审计基线：正式开发前只读导出一次 `cn_a_index_ts_codes`，当前样本为 946 个 code，用于 prod 86 个缺口补齐计划和迁移验收对账。
2. 运行时集合：每次日更运行前重新读取 `context.instance.get_dynamic_partitions(cn_a_index_ts_codes.name)`，作为本次 Lake 期望 code set。
3. 每次 materialization/check metadata 记录本次 `expected_code_count` 和按排序 code 计算的 `expected_code_set_hash`，用于事后解释“这次到底按哪批 DG code 跑的”；hash 只做审计，不反向定义 code 集合。
4. 日更更新前，必须只读校验 `core_serving.index_daily_serving[trade_date]` 覆盖本次运行的 Lake 期望 code set。
5. prod `ops.index_series_active(resource='index_daily')` 必须覆盖运行时 Lake 期望 code set，但不得反向定义 Lake 期望 code set。
6. 若本次期望 code 缺任意一个、重复 key、目标日期没有数据或查询失败，sensor 不提交 Lake 更新 run；prod source 存在额外 code 不阻断，因为 DG 查询必须只读取本次期望 code。
7. `index_daily_raw` 请求池只说明旧 Tushare 请求范围，不参与本迁移的 raw by-date 更新门禁。
8. 不使用 `silver_index_basic list_date/exp_date` 计算 raw 更新的“有效 code 集合”；该设计会把源数据齐备性检查偷换成指数生命周期推断。

这里的“raw 层和 silver 层 code 数量一致”指日更切换后二者共享同一个运行时 Lake 期望 code set 和同一套 prod source 完整性门禁，不表示由 Lake 本地 `silver_index_basic` 重新推导 code universe。历史转换段不能机械要求每个历史日期都有当前运行时 code 数；验收重点是当前 DG raw-by-code 输入事实到 by-date 文件的 `(ts_code, trade_date)` pair 无损转换。

### Raw 字段契约

新 `raw_index_daily` 仍使用 raw 契约：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ts_code` | `VARCHAR` | 指数代码 |
| `trade_date` | `VARCHAR` | `YYYYMMDD` 字符串 |
| `open/high/low/close/pre_close` | `DOUBLE` | 源行情字段 |
| `change` | `DOUBLE` | raw 层保留源字段名 |
| `pct_chg` | `DOUBLE` | 涨跌幅 |
| `vol/amount` | `DOUBLE` | 成交量/成交额 |

如果 prod-core-db 表中字段已经是 silver 风格，例如 `trade_date DATE` 或 `change_amount`，source adapter 必须映射回 raw 契约：

- `trade_date` 转为 `YYYYMMDD` 字符串；
- `change_amount AS change`；
- 禁止输出 `change_amount`、`source`、`created_at`、`updated_at` 等非 raw 契约字段；
- 禁止 `SELECT *`。

### 历史转换与日更读取边界

本迁移有两个执行阶段，不能混用：

1. 历史转换阶段：范围由 P0 只读 profiling 扫描当前 DG raw-by-code 文件得到，当前输入样本为 `2000-01-04` 到 `2026-06-23`；正式转换输入是当前 Dagster 新湖内的 `raw/tushare/index_daily_by_code/ts_code=<TS_CODE>/part-000.parquet`。转换目标是新的 `raw/index_daily/trade_date=<YYYY-MM-DD>/part-000.parquet`。这一步只是物理布局迁移，`raw_index_daily` 的 source system 仍统一记为 `PROD_CORE_DB`。
2. 日更阶段：默认源切到 prod-core-db 后，从当前 Lake `raw_index_daily` 最新已就绪交易日之后的第一个 expected trade date 开始，正式输入是 prod-core-db 的 `core_serving.index_daily_serving`。

历史转换阶段的 coverage check 证明 by-code 输入 facts 被完整搬到 by-date；日更阶段的 coverage check 证明 prod serving 当日完整覆盖运行时 Lake 期望 code set。二者使用同一个 check 名称和 metadata 结构，但 metadata 必须写明 `coverage_basis`，避免把历史转换误判为“每天必须 946 个 code”。

P0 发现当前 by-code 输入尾部存在一个半截日期：`2026-06-23` 只有 10 行、10 个 code；最新同时满足“DG 946 个 code 全覆盖、无重复 key、无空 key”的日期是 `2026-06-22`，并且 prod serving 最新日期也是 `2026-06-22`。因此：

1. P3 可以在 dry-run 中统计全部当前输入 facts，但 P3/P4 不得把 `2026-06-23` 这种尾部半截日期写成绿色 ready baseline。
2. 日更 first target 只能从已就绪 baseline cutoff 之后计算；baseline cutoff 必须由文件事实、code coverage 和 prod/latest 只读审计共同推导，不得直接取 raw-by-code 的 max trade_date。
3. 若正式 P3 执行时尾部仍有半截日期，默认策略是排除在 ready baseline 外，并让 prod-core-db 日更链路负责补该日期；若要把半截日期也转换成正式 by-date 文件，必须明确标记为 not-ready，不得写绿色 materialization/check event。

正式日更默认走 prod-core-db：

1. source table 只允许 `core_serving.index_daily_serving`。
2. 只读连接使用 `ProdPostgresResource`。
3. 远端 SQL 必须显式列字段、按 `trade_date` 和运行时 Lake 期望 code set 过滤。
4. 任何 schema/字段名不确定，先做 prod-core-db 只读 profiling，不得猜字段。
5. 更新触发前必须先执行 source completeness gate：`core_serving.index_daily_serving` 当日 code 集合必须完整覆盖运行时 Lake 期望 code set；不一致时不发起 Lake 更新。

本方案不实现 Tushare fallback。若未来需要 fallback，必须单独设计、单独性能评审、单独审批，不能混入本迁移。

## 实现阶段

### M-1：prod active pool 与 86 个 DG 代码历史补齐（开发前强制门禁）

该阶段不是 Dagster/Lake 代码开发阶段，而是 prod source 基线修复阶段。必须先完成并通过只读验收，才允许进入 M0。

范围：

1. 重新审计 DG code set、prod `index_daily` active pool、prod serving distinct code。
2. 将缺失的 DG code 加入 prod `ops.index_series_active(resource='index_daily')`。
3. 按新湖 `silver/index_daily` 中 86 个 code 的实际历史 pair 补齐 prod `core_serving.index_daily_serving`；`core_serving.index_basic.list_date` 不作为起始日期，prod `raw_tushare.index_daily` 不作为本阶段必补目标。
4. 验证 prod source 已能完整覆盖运行时 Lake 期望 code set。

禁止：

- 禁止在该阶段修改 Dagster/Lake 代码。
- 禁止把 33 个当前 raw 缓存交易日当作历史补齐范围。
- 禁止按 `index_basic.list_date` 截断新湖 silver 中已经存在的日线。
- 禁止把 prod active pool 直接变成 Lake 期望 code set。
- 禁止绕过现有 `index_daily` serving 字段映射和 active gate 语义。

### M0：只读 Profiling 与 LLD 前置

只读验证以下事实：

1. prod-core-db `core_serving.index_daily_serving` 的列名、类型、日期范围、代码范围。
2. 本机 Dagster `cn_a_index_ts_codes`、prod `ops.index_series_active(resource='index_daily')`、prod `core_serving.index_daily_serving` 三个 code set 的差异。
3. 记录本迁移 Lake code set 审计基线，并说明日更运行时是否沿用当前 DG dynamic partitions。
4. 默认源切到 prod-core-db 后，每个日更目标交易日 `core_serving.index_daily_serving` 是否完整覆盖本次运行的 Lake 期望 code set。
5. 当前 prod serving 缺口的开始日期、截止日期、缺失 code 样本。
6. 从当前 DG raw-by-code 转换历史 by-date raw 文件的日期数、行数、重复键、异常样本、预计文件数和 runless event 数。

禁止写 prod DB、禁止写 lake、禁止写 Dagster event。

### M1：新 Raw By-Date 契约与 Source Adapter

新增或重命名以下契约：

1. `RAW_INDEX_DAILY_SCHEMA`：字段与当前 `RAW_TUSHARE_INDEX_DAILY_BY_CODE_SCHEMA` 一致，但命名不再绑定 Tushare/by-code。
2. `raw_index_daily_path(root, trade_date)` 与 staging path。
3. `raw_index_daily[trade_date]` asset。
4. prod-core-db source adapter：从 `core_serving.index_daily_serving` 读取日更切换后的目标 trade date 和运行时 Lake 期望 code 集合，写 raw by-date parquet。

`SourceSystem` 需要新增稳定枚举，例如 `PROD_CORE_DB = "prod_core_db"`。catalog ingestion source 优先复用现有 `IngestionSource.PROD_DB_READONLY`，不得新增近义重复枚举。

### M2：Raw By-Date Checks

新增 raw by-date blocking checks 必须收敛为两个聚合 check，避免把文件存在、行数、schema、日期、唯一键等细项拆成多条 Dagster check event：

| Check | 语义 |
| --- | --- |
| `raw_index_daily_file_contract_check` | 聚合校验目标 by-date 文件存在、行数大于 0、字段和类型符合 `RAW_INDEX_DAILY_SCHEMA`、文件内 `trade_date` 全部等于 partition trade date 的 `YYYYMMDD`、`ts_code + trade_date` 唯一。metadata 记录每个子项结果、失败原因计数和样本。 |
| `raw_index_daily_code_coverage_check` | 统一覆盖检查。历史转换段校验 by-code 输入 facts 到 by-date 目标 facts 无损；日更段校验 prod source 覆盖本次运行的 Lake 期望 code set。metadata 必须写 `coverage_basis`、expected/actual count、code set hash、缺失/额外样本。 |

不把 silver 的标准化检查提前到 raw，例如不检查 `trade_date DATE`、不要求 `change_amount` 字段。

### M3：历史 DG By-Code 到 By-Date 文件转换

历史 by-date raw 文件的正式生成输入是当前 Dagster 新湖内已经存在的 `raw_tushare_index_daily_by_code[ts_code]`。这一步是同一新湖内的物理布局重排，不是跨区复用旧湖文件，也不是从 prod DB 重拉历史；但 catalog 和 asset definition 的 source system 统一按 `PROD_CORE_DB` 记录。

转换范围由 P0 只读 profiling 扫描当前 DG raw-by-code 已覆盖的历史范围得到。当前审计样本为：

```text
all input facts: 2000-01-04 <= trade_date <= 2026-06-23, 3,419,666 rows, 6,793 trade dates
ready baseline candidate: 2000-01-04 <= trade_date <= 2026-06-22, 3,419,656 rows, 6,792 trade dates
```

`2026-06-23` 当前只有 10 个 code，属于尾部半截输入。P3/P4 默认只能把 ready baseline 建到 `2026-06-22`；不得因为 raw-by-code max trade date 是 `2026-06-23`，就让新 sensor 从 `2026-06-24` 开始。

使用 DuckDB set-based SQL 从当前 by-code parquet 文件集合生成，不允许 Python 逐行循环：

1. 读取 `raw/tushare/index_daily_by_code/ts_code=*/part-000.parquet`，并明确 `hive_partitioning=false`，避免把目录分区列误当作文件字段。
2. 以输入文件内部的 `(ts_code, trade_date)` 为事实，按 `trade_date` 写入新路径。
3. 批量策略按年份或月份执行，避免一次性扫描全历史造成大内存和大量小文件异常。
4. 先写 staging root，校验通过后再替换正式目标。
5. 输出转换报告，记录源行数、目标行数、源 pair 数、目标 pair 数、重复 key、异常样本和每批耗时。

验收必须覆盖：

- by-code input 行数等于 target by-date 总行数；
- `distinct(ts_code, trade_date)` 不变；
- 每个 target date 文件 schema 正确；
- 每个 target date 的 code coverage 与 by-code input facts 一致；不能要求每个历史日期都有当前 946 个 code；
- 失败样本输出到 `/private/tmp`，不进入 repo。

### M4：Runless Event Dry-Run 与补录

历史转换文件写入并通过审计后，才允许 runless event 补录。

补录对象：

| 类型 | 数量估算 |
| --- | --- |
| Materialization event，全量当前输入 facts | 约 6,793 条 |
| Raw checks，2 个聚合 check，全量当前输入 facts | 约 13,586 条 check event |
| 总计，全量当前输入 facts | 约 20,379 条 event |
| Materialization event，ready baseline 建议范围 | 约 6,792 条 |
| Raw checks，2 个聚合 check，ready baseline 建议范围 | 约 13,584 条 check event |
| 总计，ready baseline 建议范围 | 约 20,376 条 event |

执行规则：

1. dry-run 统计已有 event、目标 event、缺文件、已绿、待写数量。
2. 样本 apply：先选 3 到 5 个 partition，写 materialization + checks。
3. 样本验收：Dagster UI、event log、readiness helper 都必须能看到正确 partition。
4. full apply 分批执行，记录每批耗时、失败数、event 写入速率。
5. final audit：全部目标 partition 的 materialization/check events ready。

禁止：

- 文件未通过本地 check 就写绿色 runless check event；
- 把 missing check event 自动扩成全历史补录；
- 写旧 by-code asset 的新 event；
- 在 P4 runless 补录阶段删除历史 event。

### M5：Sensor 与 Job 切换

`index_daily_sensor` 改为 date-level：

1. 从 `cn_a_index_trade_days` 找最早 raw by-date not-ready 日期。
2. 默认检查 prod-core-db source readiness。
3. prod-core-db source readiness 必须证明当日 serving code 集合完整覆盖运行时 Lake 期望 code set；不齐备时 skip，不提交 run。
4. 每个 tick 最多提交少量 date-level run，日常建议 1 个。
5. run key 由统一 builder 生成，目标格式为 `raw_index_daily:<trade_date>`。
6. 不再使用 `next_pending_offset` 轮转 code。
7. 不再生成 `index_daily:<trade_date>:<ts_code>`。

`silver_index_daily_sensor` 改为：

1. 先检查 `raw_index_daily[trade_date]` readiness。
2. raw by-date ready 后，选择最早 silver not-ready 日期。
3. 不再扫描 raw-by-code 文件集合。

`index_daily_update_job` selection 改为 `raw_index_daily` + new raw checks。

### M5.1：日更激活门禁

raw 日更 sensor 不能在 by-date 历史基线建立前启用。必须同时满足：

1. M3 历史 by-code 到 by-date 文件转换 full audit 通过；
2. M4 `raw_index_daily[trade_date]` materialization/check runless event full audit 通过；
3. readiness helper 能从 `raw_index_daily` 文件事实和 runless event 事实确认最新已就绪交易日；
4. first daily target 只能取该最新已就绪交易日之后的第一个 expected trade date；
5. 若 `raw/index_daily` 仍不存在或 by-date baseline 缺失，sensor 必须 skip/block，不能从固定日期或当前日期猜起点。

### M6：下游消费者迁移

必须清零所有 active 生产代码中的旧 by-code 依赖：

1. `silver_index_daily` deps 和 SQL 输入；
2. `checks/index_daily_checks.py` 的 silver source checks；
3. `sensors/index_daily_raw_file_readiness.py`；
4. `asset_guards/market_major_indices_lake_readiness.py`；
5. `catalog/lake_assets.py`；
6. `run_contracts/configs.py`；
7. tests 与 static gates。

迁移后，active `src/**` 中不得再出现：

- `raw_tushare_index_daily_by_code`；
- `raw_index_daily_by_code_path`；
- `index_daily_by_code`；
- `raw_index_daily_by_code_*` check 名称；
- `index_daily:<trade_date>:<ts_code>` run key。

历史文档可以保留旧口径，但必须明确标注为历史方案，不得写成当前代码事实。

### M7：旧资产删除

只有满足以下条件，才删除 active by-code 实现：

1. `raw_index_daily[trade_date]` 文件转换和 runless event 补录成功。
2. 新 raw/silver/major indices sensor 和 checks 本地回归通过。
3. 正式 Dagster readiness 已确认不再依赖旧 by-code asset。
4. active source code 旧依赖静态扫描为零。
5. 用户单独批准删除物理旧文件。

代码删除范围：

- `raw_tushare_index_daily_by_code` asset；
- old raw-by-code checks；
- old by-code path helper；
- old by-code IO helper；
- old by-code sensor gap/readiness helper；
- old tests 和 catalog entries。

物理路径 `raw/tushare/index_daily_by_code` 的删除必须单独审批，不与代码提交混在一起。

### M8：旧 Index Daily 状态与事件清理（对应 P9）

旧 index daily 的 Dagster DB 状态、run、materialization/check event、sensor cursor 清理不是新链路启用条件。只有在新 `raw_index_daily`、`silver_index_daily`、sensor、readiness、catalog 全部确认不再读取旧 by-code asset/check/job/sensor 记录后，才允许把它作为一次独立治理动作处理。

清理前必须先做 dry-run 报告，报告至少列出候选对象类型、精确 asset/check/job/sensor 名称、时间或 storage id 边界、预计删除数量、保留样本和回滚/备份方案。允许清理的对象只能是旧 by-code 链路记录，例如旧 `raw_tushare_index_daily_by_code` materialization/check event、旧 `index_daily_update_job` run、已删除旧 sensor 的 cursor/state。禁止清理 `cn_a_index_ts_codes` dynamic partitions、新 `raw_index_daily` 事件、新 `silver_index_daily` 历史、trade-day partitions、prod DB 数据和 by-date lake 文件。

如果 Dagster 当前没有安全、可审计、可回滚的精确删除路径，则只允许把旧记录归档/忽略，不允许为了“看起来干净”做宽泛 event history 清空。若新链路必须依赖清理旧 Dagster DB 事件才能运行，说明迁移设计仍有旧依赖，必须停止并修正设计。

## 性能门禁

| 场景 | 性能口径 |
| --- | --- |
| prod-core-db 日更 | 每个 trade date 一次 bounded query；只读、显式字段、按日期和 code set 过滤；禁止全表扫描。 |
| prod-core-db 更新门禁 | 更新触发前必须校验 serving 当日 code 集合完整覆盖运行时 Lake 期望 code set；缺口存在时不发起 Lake 更新。 |
| 历史转换 | 从当前 DG raw-by-code parquet 读取并写 by-date raw；DuckDB set-based SQL；按年份/月批；不 Python 行循环；不一次性把全历史加载到 Python 内存。 |
| 文件写入 | staging root 写入 + 校验 + 受控替换；失败不得污染正式路径。 |
| runless event | dry-run、样本、分批、final audit；记录事件数量、批次耗时和失败样本。 |
| sensor 热路径 | 只看最近 continuity 窗口；不能读全历史 raw 文件；不能逐 code 提交大量 run。 |
| checks | by-date raw blocking checks 收敛为 `file_contract` 与 `code_coverage` 两个聚合 check；只读目标日文件和必要 code universe，不扫描全历史，不拆出大量细碎 check event。 |

停止条件：

1. prod-core-db 单日读取无法在可接受时间内完成，或必须扫全表。
2. 日更切换后 prod source 当日没有完整覆盖本次运行的 Lake 期望 code set。
3. 历史转换发现 by-code 输入/目标行数不一致、pair 不一致、重复键无法解释、schema 不兼容。
4. runless dry-run 待写 event 数显著超出估算。
5. 新 sensor 需要恢复 per-code run 才能运行。
6. 任何实现需要在 raw 层输出 silver 字段或承担 silver 标准化职责。

## 测试与验收

### 本地测试

1. prod-core-db adapter 使用 fake connection 验证 SQL：
   - 显式字段；
   - 无 `SELECT *`；
   - 无 forbidden columns；
   - `trade_date` 和运行时 Lake 期望 code set filter 必须存在。
   - source completeness gate 对本次期望 code 缺失、重复 key、source 异常必须 fail closed；prod source 存在额外 code 不阻断，但查询结果在本地按期望 code 过滤后不得出现非期望 code。
2. raw by-date writer：
   - `trade_date` 是 `YYYYMMDD` 字符串；
   - 字段名是 `change`，不是 `change_amount`。
3. raw by-date checks：
   - `raw_index_daily_file_contract_check` 对文件缺失、空文件、schema 错、日期错、重复键 fail closed，并在 metadata 写清子项结果；
   - `raw_index_daily_code_coverage_check` 对 coverage 缺失 fail closed；
   - static gate 禁止重新新增 `file_exists/row_count/schema/partition_date/unique_key` 等细碎 raw blocking check 名称。
4. historical generator：
   - 当前 DG raw-by-code 样本生成 by-date；
   - 行数、唯一键、日期分区全部保持；
   - 历史转换只在当前 Dagster 新湖内使用现有 raw-by-code 资产，不读取旧 Lake Console 路径。
5. runless dry-run：
   - 不写 event；
   - 能统计 materialization/check 已有、缺失、待写。
6. sensor contract：
   - index daily sensor 提交 date-level run；
   - silver sensor 不再读 raw-by-code；
   - run key 不含 ts_code。
7. static gates：
   - active code 禁止旧 by-code symbol 回流；
   - source SQL 禁止 `SELECT *`；
   - runless apply 必须依赖 dry-run 报告。

### 正式只读验收

开发前和正式执行前都必须只读确认：

1. 当前 DG raw-by-code 到 by-date dry-run 预计文件数、行数、event 数。
2. by-code input pair 与 by-date target pair 的转换差异为 0。
3. 运行时 Lake 期望 code set 与 `core_serving.index_daily_serving` 在日更目标日期的覆盖可解释；本次期望 code 缺口必须先补齐或显式阻断。
4. 删除旧 by-code 前，active Dagster definitions 不再引用旧 asset。
5. 若执行旧 Dagster DB 状态/事件清理，必须先 dry-run 证明清理候选与新 `raw_index_daily`、`silver_index_daily`、sensor readiness 无交集。

## 需要单独审批的动作

以下动作不能随代码提交自动执行：

1. prod-core-db 正式只读 profiling。
2. 正式 lake 历史 by-code 到 by-date 转换 sample/full。
3. runless event sample/full 写入。
4. 正式 Dagster definitions 重载。
5. 旧 `raw/tushare/index_daily_by_code` 物理文件删除。
6. 旧 index daily Dagster DB 状态/事件清理 dry-run 与 apply。

## 本轮重新审计后的新增问题与修正

1. catalog helper 风险：当前 `_tushare_raw_entry(...)` 会自动写 Tushare source system。新 `raw_index_daily` 必须使用新增 prod-core-db catalog helper 或直接 `_entry(...)`，字段级写成 `SourceSystem.PROD_CORE_DB`、`DataContractSource.PROD_SERVING_CONTRACT`、`IngestionSource.PROD_DB_READONLY`、`EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL`。
2. check 过碎风险：高层方案原来把 file exists、row count、schema、partition date、unique key、coverage 拆成 6 个 raw blocking check，会给 Dagster DB 写入过多细碎 check event。已收敛为 `raw_index_daily_file_contract_check` 与 `raw_index_daily_code_coverage_check` 两个聚合 check；实现和 tests 必须用这两个名称，不得让 readiness 同时支持新旧 raw check。
3. backend prod-core-db 只能参考不能复用：已有 backend 导出能力证明字段白名单和 `change_amount AS change` 口径，但它不带 DG code set filter，且属于 backend/sync 区域。orchestrator 必须建立自己的只读 adapter。
4. sensor 激活顺序风险：当前 `raw/index_daily` by-date 路径不存在。未完成 M3/M4 前启用新日更 sensor，会没有“最新已就绪 raw_index_daily”基线，必须显式阻断。
5. bootstrap 与静态门禁冲突：P3/P4 bootstrap 可以临时读取当前 DG 新湖 by-code 文件；P7 后 bootstrap 代码必须删除或移出 active source，否则会和“生产代码旧 by-code 符号清零”门禁冲突。
6. 硬编码日期风险：`2026-06-22`、`2026-06-23` 只能出现在审计事实、测试 fixture 或文档中；生产代码不得把它们作为日更起点、历史终点或 cutover 常量。
7. coverage 语义风险：`raw_index_daily_code_coverage_check` 是统一 check 名，但必须用 `coverage_basis` 区分历史转换和日更。历史转换看 by-code input pair 是否无损，日更看 prod serving 是否覆盖运行时 Lake 期望 code set。
8. 旧数据清理风险：旧 by-code lake 文件删除与 Dagster DB 旧状态/事件清理都不能混入新链路开发。旧物理文件删除是 P8，旧 Dagster DB 状态/事件清理是独立 P9；二者都必须单独审批、先 dry-run、后 apply。
9. 2026-06-23 二次代码级审计确认：当前 active 代码仍完整依赖旧 `raw_tushare_index_daily_by_code`、旧 5 个 raw-by-code checks、旧 per-code sensor、旧 by-code readiness 和旧 catalog entry。因此 P9 现在只能 dry-run，不能 apply；必须等 P7 active by-code source 清零后重跑 dry-run。
10. 2026-06-23 P9 dry-run 结果确认：本机 Dagster DB 中新目标 `raw_index_daily` 当前没有 asset event、check event 或 asset key；旧 by-code raw asset 有 48,515 条 asset event 记录、123,684 条 raw check execution 记录，`index_daily_update_job` 有 24,741 个 run、1,634,475 条 event log、206,649 条 run tag。这个规模说明 P9 必须先明确“只清 asset/check 历史”还是“连 run history 一起治理”，不能直接宽泛删除。

## 建议推进步骤

1. 先完成 P-1 prod source 基线修复：重新导出 DG 946 code、prod active pool、prod serving distinct code；把 86 个 DG 缺口加入 `ops.index_series_active(resource='index_daily')`；按新湖 `silver/index_daily` 中 86 个 code 的实际历史 pair 补齐 prod serving；只读验收缺口为 0。
2. 再做 P0 只读 profiling：冻结 prod 字段、单日读取性能、DG code hash、by-code 历史输入规模、by-date event 数量估算；若数字变化，先更新本文档。
3. P1/P2 只开发新契约和新 raw by-date asset/check/job，不启用 sensor，不删除旧 by-code。
4. P3 单独申请 lake 写入审批，执行历史 by-code 到 by-date 文件转换，先 sample 后 full。
5. P4 单独申请 Dagster event 写入审批，执行 runless materialization/check event 补录，先 sample 后 full。
6. P5/P6 再切 silver、major indices 和 raw/silver sensor；新 sensor 默认仍保持 STOPPED，完成只读验证后再正式启用。
7. P7 清零 active by-code 代码和 catalog；P8 在用户单独批准后再删旧物理文件；P9 如确有必要，再独立审批旧 index daily Dagster DB 状态/事件清理。

## 遗留拍板项

1. P-1 prod 补数的批准目标交易日：必须不早于 P0 扫描到的当前新湖 silver 最大 trade date；若开发期间新湖继续增长，以正式执行前最新 profiling 为准。
2. 86 个 code 补数不再建立 Tushare source gap 白名单；正式可补集合就是新湖 `silver/index_daily` 中实际存在的 pair。若新湖数据本身被证明有污染，必须先停下单独审计数据来源。
3. P3/P4 bootstrap 代码在 P7 的处理方式：删除，还是移到 active static gate 不扫描的离线工具目录。无论选哪种，生产 `src/orchestrator/defs/**` 旧 by-code 符号必须清零。
4. 新 `raw_index_daily` catalog 是否新增专用 `_prod_core_raw_entry(...)` helper；若不新增 helper，也必须直接用 `_entry(...)` 写全字段，禁止套 `_tushare_raw_entry(...)` 或 `_derived_entry(...)`。
5. P9 旧 Dagster DB 状态/事件清理是否执行：若执行，必须另起专项 dry-run 和审批；若不执行，旧记录只能作为历史审计账留存，不能影响新链路状态。
6. P9 清理粒度：默认建议第一阶段只考虑旧 raw asset/check/index sensor cursor；`index_daily_update_job` run history 规模很大，是否清理 run、run_tags、run_id 关联 event_logs 必须单独拍板。

## 最终验收标准

1. `raw_index_daily[trade_date]` 是指数日线唯一 active raw asset。
2. raw 与 silver 共享运行时 Lake 期望 code universe。
3. raw 文件仍是 raw 契约，不混入 silver 字段。
4. 日更默认从 prod-core-db 同步，起点由当前 Lake 最新已就绪交易日之后的 expected trade date 计算，且 prod source 对本次期望 code 不齐备时不触发 Lake 更新。
5. P0 profiling 确认的历史 by-date 文件从当前 DG raw-by-code 文件无损转换；runless events 补录完成。
6. `raw_tushare_index_daily_by_code` active 代码与 catalog 口径清零。
7. sensors 不再 per-code 提交指数日线 raw run。
8. 性能报告记录 prod-core-db 单日读取、历史转换、runless event 写入和 sensor tick 耗时。
9. raw by-date blocking check 只有两个聚合 check，Dagster DB 不新增 file exists、row count、schema、partition date、unique key 等细碎 raw check event。
10. 旧 index daily 清理若已执行，dry-run/apply 报告证明没有删除新 by-date raw、silver、dynamic partitions、trade-day partitions 或 prod 数据；若未执行，旧记录不参与新 readiness 和日更状态。
