# Dagster Index Daily Raw By-Date Prod DB Migration Plan

状态：方案设计，未实现。

LLD：[`dagster-index-daily-raw-by-date-prod-db-migration-low-level-design.md`](./dagster-index-daily-raw-by-date-prod-db-migration-low-level-design.md)。

## 目标

将指数日线 `index_daily` 从当前的 `raw_tushare_index_daily_by_code[ts_code]` 迁移为 `raw_index_daily[trade_date]`：

1. 历史数据先在当前 Dagster 新湖内完成原地物理布局转换：把开发前只读 profiling 确认的现有 `raw_tushare_index_daily_by_code[ts_code]` 全部历史文件，无损转换为 `raw_index_daily[trade_date]` 文件；当前审计样本范围是 `2000-01-04` 到 `2026-06-22`，不得写成实现里的固定日期常量。
2. 日更默认源从 Tushare 切换到远程 prod DB 后，Dagster 从当前 Lake `raw_index_daily` 最新已就绪交易日之后的第一个 expected trade date 开始，从 `core_serving.index_daily_serving` 同步指数日线到 raw 层；起点由文件事实和交易日历计算，不硬编码具体日期。
3. raw 层与 silver 层使用同一个运行时 Lake 期望 code set。raw 不再按代码拆分物理资产；日更每次运行时读取本机 Dagster `cn_a_index_ts_codes` dynamic partitions，当前迁移审计基线是 946 个指数代码。
4. `core_serving.index_daily_serving` 在目标交易日没有覆盖本次运行的 Lake 期望 code set 时，不允许向 Lake 发起日更；prod 上存在额外 code 不阻断，DG 只读取和校验自己本次要的 code。sensor 必须 fail closed，返回明确 skip/block 原因。
5. 只有在 `raw_index_daily[trade_date]` 历史文件转换、校验和 runless materialization/check event 补录全部成功后，才删除 active `raw_tushare_index_daily_by_code` 资产、checks、job、sensor 依赖和物理旧文件。
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

2026-06-23 本轮重新只读审计确认的事实：

| 项 | 观测值 |
| --- | --- |
| 当前 DG raw-by-code parquet 文件数 | 946 个 `part-000.parquet` |
| 当前 DG raw-by-code 行数 | 3,419,656 行 |
| 当前 DG raw distinct trade dates | 6,792 个 |
| 当前 DG raw distinct ts_code | 946 个 |
| 当前 DG raw 日期范围 | `2000-01-04` 到 `2026-06-22` |
| 当前目标 by-date raw 路径 | `/Volumes/datasource/data_lake/raw/index_daily` 不存在，`trade_date=*/part-000.parquet` 为 0 |
| 当前 silver by-date parquet 文件数 | 6,411 个 |
| 本机 Dagster `cn_a_index_ts_codes` dynamic partitions | 946 个 code |
| 本机 Dagster code set hash | `6f8f560f11cdce10e4cd5a096c64a4c9`，按 code 排序后 `md5(string_agg(code, ','))` |
| 远程 prod `ops.index_series_active(resource='index_daily')` | 1130 个 code |
| 远程 prod `ops.index_series_active(resource='index_daily_raw')` | 3052 个 code，仅是历史请求池，不是本迁移 raw 更新门禁 |
| 远程 prod `core_serving.index_daily_serving` 日期范围 | `2020-01-02` 到 `2026-06-22` |
| 远程 prod `core_serving.index_daily_serving` distinct code | 1130 个 |
| 远程 prod 最近 10 个交易日 serving 当日 code | 每日 1126 个，较 `index_daily` active pool 缺 4 个 |
| DG code 与当前 prod serving 4 个缺口交集 | 0 个 |
| DG code 不在 prod serving 全历史中的数量 | 86 个 |
| prod serving 全历史 code 不在 DG 中的数量 | 270 个 |

这些数量只作为方案规模估算。正式开发前必须重新执行只读 dry-run，不能直接相信历史样本。

2026-06-23 只读审计发现的当前 prod serving 缺口：

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
3. 对新增进入 prod `index_daily` active pool 的 DG 缺口代码，先把 prod 端历史 `raw_tushare.index_daily` 与 `core_serving.index_daily_serving` 补齐，再允许本迁移从 prod serving 读取。

2026-06-23 只读审计得到的当前缺口：

| 项 | 当前观测 |
| --- | ---: |
| DG `cn_a_index_ts_codes` | 946 个 |
| DG 管理但不在 prod serving 全历史中的 code | 86 个 |
| 这 86 个在 `ops.index_series_active(resource='index_daily')` 中 | 0 个 |
| 这 86 个在 `ops.index_series_active(resource='index_daily_raw')` 中 | 86 个 |
| 这 86 个当前 prod raw 行数 | 2,837 行 |
| 这 86 个当前 prod serving 行数 | 0 行 |
| 这 86 个 `index_basic.list_date` 范围 | `2023-03-13` 到 `2025-07-21` |
| 按各自 `list_date` 到 `2026-06-22` 开市日估算的历史 serving 行数 | 47,656 行 |
| 当前估算 raw 缺口 | 44,819 行 |
| 当前估算 serving 缺口 | 47,656 行 |

注意：`2026-05-06` 到 `2026-06-22` 的 33 个交易日只是 prod raw 当前已有的局部缓存窗口，不是历史补齐范围。正式补齐范围必须按每个 code 的 `core_serving.index_basic.list_date` 到批准的目标交易日计算；若未来出现 `exp_date`，截止日期取 `min(exp_date, 目标交易日)`。

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
   - 对每个待补 code 读取 `core_serving.index_basic.list_date/exp_date`。
   - 用 `core_serving.trade_calendar where is_open = true` 计算 `[list_date, target_trade_date]` 的 expected trade dates。
   - 对比 `raw_tushare.index_daily` 和 `core_serving.index_daily_serving` 已有行，输出 raw gap、serving gap、缺失样本。
   - 当前已知样本：`970051.CNI` 在 `2026-05-20` 的 Tushare `index_daily` 源端有数据，但 prod raw 缺失，该类缺口必须按源端事实补齐。
4. 补 prod active pool：
   - 仅在用户批准后执行生产写入。
   - 写入 `ops.index_series_active(resource='index_daily')` 的待补 code。
   - `first_seen_date/last_seen_date/last_checked_at` 是审计字段，不参与 Lake 期望集合定义；写入值必须来自本次补齐计划中的实际 source 覆盖范围和执行时间。
   - 不得把 `index_daily_raw` resource 行当作 `index_daily` resource 复用或改名。
5. 补 prod raw 与 serving 历史：
   - 使用现有生产 `index_daily` 维护链路，按 explicit `ts_code` 和 `[list_date, target_trade_date]` 执行 `range_rebuild`；不得依赖默认 `index_daily_raw` 请求池隐式展开。
   - 当前代码依据必须逐项对齐：`src/foundation/ingestion/request_builders.py::_index_daily_params(...)` 已支持 explicit `ts_code` + `start_date/end_date`；`src/foundation/ingestion/unit_planner.py::_resolve_index_codes(...)` 在传入 explicit `ts_code` 时优先使用该 code；`src/foundation/ingestion/writer.py::_write_index_daily_serving(...)` 先 upsert `raw_tushare.index_daily`，再按 `ops.index_series_active(resource='index_daily')` active gate 写 `core_serving.index_daily_serving`。
   - serving 写入必须走当前 `index_daily` active gate 语义，保持 `change -> change_amount` 映射和 `(ts_code, trade_date)` 幂等 upsert；不得直接绕过现有字段转换口径。
   - 目标不是只补 33 个交易日，而是补到每个 code 的完整历史范围。
6. 最终只读验收：
   - `dg_codes - prod_index_daily_active_pool = empty`。
   - `dg_codes - prod_index_daily_serving_distinct_codes = empty`。
   - 对 86 个待补 code，按 `index_basic.list_date` 到目标交易日的 expected trade dates 与 prod raw/serving 对账，missing pair 为 0；若 Tushare 源端确无数据，必须有逐 code/date 的源端实测证据和人工批准。
   - 目标交易日 `core_serving.index_daily_serving` 必须完整覆盖运行时 Lake 期望 code set。

停止条件：

1. prod active pool 仍缺任何 DG code。
2. 86 个历史补齐后 prod serving 仍缺任何应有 code/date。
3. 无法解释 source 无数据、重复 key、字段映射或 row count 差异。
4. 补齐计划试图改用 prod active pool 反向定义 DG/Lake 同步集合。

只有该前置步骤最终验收通过，才允许进入本迁移的 M0。

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

1. 历史转换阶段：范围由 P0 只读 profiling 扫描当前 DG raw-by-code 文件得到，当前样本为 `2000-01-04` 到 `2026-06-22`；正式转换输入是当前 Dagster 新湖内的 `raw/tushare/index_daily_by_code/ts_code=<TS_CODE>/part-000.parquet`。转换目标是新的 `raw/index_daily/trade_date=<YYYY-MM-DD>/part-000.parquet`。这一步只是物理布局迁移，`raw_index_daily` 的 source system 仍统一记为 `PROD_CORE_DB`。
2. 日更阶段：默认源切到 prod-core-db 后，从当前 Lake `raw_index_daily` 最新已就绪交易日之后的第一个 expected trade date 开始，正式输入是 prod-core-db 的 `core_serving.index_daily_serving`。

历史转换阶段的 coverage check 证明 by-code 输入 facts 被完整搬到 by-date；日更阶段的 coverage check 证明 prod serving 当日完整覆盖运行时 Lake 期望 code set。二者使用同一个 check 名称和 metadata 结构，但 metadata 必须写明 `coverage_basis`，避免把历史转换误判为“每天必须 946 个 code”。

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
3. 按每个 code 的 `core_serving.index_basic.list_date` 到批准的目标交易日补齐 prod `raw_tushare.index_daily` 与 `core_serving.index_daily_serving`。
4. 验证 prod source 已能完整覆盖运行时 Lake 期望 code set。

禁止：

- 禁止在该阶段修改 Dagster/Lake 代码。
- 禁止把 33 个当前 raw 缓存交易日当作历史补齐范围。
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

新增 raw by-date blocking checks：

| Check | 语义 |
| --- | --- |
| `raw_index_daily_file_exists_check` | 目标 by-date 文件存在。 |
| `raw_index_daily_row_count_positive_check` | 文件行数大于 0。 |
| `raw_index_daily_required_columns_and_types_check` | 字段和类型符合 `RAW_INDEX_DAILY_SCHEMA`。 |
| `raw_index_daily_partition_date_matches_check` | 文件内 `trade_date` 全部等于 partition trade date 的 `YYYYMMDD`。 |
| `raw_index_daily_unique_ts_code_trade_date_check` | `ts_code + trade_date` 唯一。 |
| `raw_index_daily_registered_code_coverage_check` | 统一覆盖检查。历史转换段校验 by-code 输入 facts 到 by-date 目标 facts 无损；日更段校验 prod source 覆盖本次运行的 Lake 期望 code set。 |

不把 silver 的标准化检查提前到 raw，例如不检查 `trade_date DATE`、不要求 `change_amount` 字段。

### M3：历史 DG By-Code 到 By-Date 文件转换

历史 by-date raw 文件的正式生成输入是当前 Dagster 新湖内已经存在的 `raw_tushare_index_daily_by_code[ts_code]`。这一步是同一新湖内的物理布局重排，不是跨区复用旧湖文件，也不是从 prod DB 重拉历史；但 catalog 和 asset definition 的 source system 统一按 `PROD_CORE_DB` 记录。

转换范围由 P0 只读 profiling 扫描当前 DG raw-by-code 已覆盖的历史范围得到。当前审计样本为：

```text
2000-01-04 <= trade_date <= 2026-06-22
```

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
| Materialization event | 约 6,792 条 |
| Raw checks，5 个基础 check | 约 33,960 条 |
| 如果加入 code coverage check | 约 40,752 条 check event |
| 总计，含 6 checks | 约 47,544 条 event |

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
- 删除历史 event。

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

## 性能门禁

| 场景 | 性能口径 |
| --- | --- |
| prod-core-db 日更 | 每个 trade date 一次 bounded query；只读、显式字段、按日期和 code set 过滤；禁止全表扫描。 |
| prod-core-db 更新门禁 | 更新触发前必须校验 serving 当日 code 集合完整覆盖运行时 Lake 期望 code set；缺口存在时不发起 Lake 更新。 |
| 历史转换 | 从当前 DG raw-by-code parquet 读取并写 by-date raw；DuckDB set-based SQL；按年份/月批；不 Python 行循环；不一次性把全历史加载到 Python 内存。 |
| 文件写入 | staging root 写入 + 校验 + 受控替换；失败不得污染正式路径。 |
| runless event | dry-run、样本、分批、final audit；记录事件数量、批次耗时和失败样本。 |
| sensor 热路径 | 只看最近 continuity 窗口；不能读全历史 raw 文件；不能逐 code 提交大量 run。 |
| checks | by-date checks 只读目标日文件和必要 code universe，不扫描全历史。 |

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
   - 文件缺失、schema 错、日期错、重复键、coverage 缺失均 fail closed。
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

## 需要单独审批的动作

以下动作不能随代码提交自动执行：

1. prod-core-db 正式只读 profiling。
2. 正式 lake 历史 by-code 到 by-date 转换 sample/full。
3. runless event sample/full 写入。
4. 正式 Dagster definitions 重载。
5. 旧 `raw/tushare/index_daily_by_code` 物理文件删除。

## 本轮重新审计后的新增问题与修正

1. catalog helper 风险：当前 `_tushare_raw_entry(...)` 会自动写 Tushare source system。新 `raw_index_daily` 必须使用新增 prod-core-db catalog helper 或直接 `_entry(...)`，字段级写成 `SourceSystem.PROD_CORE_DB`、`DataContractSource.PROD_SERVING_CONTRACT`、`IngestionSource.PROD_DB_READONLY`、`EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL`。
2. check 命名偏差：高层方案原来没有 `_check` 后缀，已统一到 LLD 的长期命名。实现和 tests 必须用新名称，不得让 readiness 同时支持新旧 raw check。
3. backend prod-core-db 只能参考不能复用：已有 backend 导出能力证明字段白名单和 `change_amount AS change` 口径，但它不带 DG code set filter，且属于 backend/sync 区域。orchestrator 必须建立自己的只读 adapter。
4. sensor 激活顺序风险：当前 `raw/index_daily` by-date 路径不存在。未完成 M3/M4 前启用新日更 sensor，会没有“最新已就绪 raw_index_daily”基线，必须显式阻断。
5. bootstrap 与静态门禁冲突：P3/P4 bootstrap 可以临时读取当前 DG 新湖 by-code 文件；P7 后 bootstrap 代码必须删除或移出 active source，否则会和“生产代码旧 by-code 符号清零”门禁冲突。
6. 硬编码日期风险：`2026-06-22`、`2026-06-23` 只能出现在审计事实、测试 fixture 或文档中；生产代码不得把它们作为日更起点、历史终点或 cutover 常量。
7. coverage 语义风险：`raw_index_daily_registered_code_coverage_check` 是统一 check 名，但必须用 `coverage_basis` 区分历史转换和日更。历史转换看 by-code input pair 是否无损，日更看 prod serving 是否覆盖运行时 Lake 期望 code set。

## 建议推进步骤

1. 先完成 P-1 prod source 基线修复：重新导出 DG 946 code、prod active pool、prod serving distinct code；把 86 个 DG 缺口加入 `ops.index_series_active(resource='index_daily')`；按各自 `list_date` 到批准目标交易日补齐 prod raw 与 serving；只读验收缺口为 0。
2. 再做 P0 只读 profiling：冻结 prod 字段、单日读取性能、DG code hash、by-code 历史输入规模、by-date event 数量估算；若数字变化，先更新本文档。
3. P1/P2 只开发新契约和新 raw by-date asset/check/job，不启用 sensor，不删除旧 by-code。
4. P3 单独申请 lake 写入审批，执行历史 by-code 到 by-date 文件转换，先 sample 后 full。
5. P4 单独申请 Dagster event 写入审批，执行 runless materialization/check event 补录，先 sample 后 full。
6. P5/P6 再切 silver、major indices 和 raw/silver sensor；新 sensor 默认仍保持 STOPPED，完成只读验证后再正式启用。
7. P7 清零 active by-code 代码和 catalog；P8 在用户单独批准后再删旧物理文件。

## 遗留拍板项

1. P-1 prod 补数的批准目标交易日：必须不早于 P0 扫描到的当前 DG by-code 历史最大交易日；若开发期间 by-code 继续增长，以正式执行前最新 profiling 为准。
2. 86 个 code 补数遇到 Tushare 源端确无数据时，是否允许带人工批准的 source gap 白名单继续推进。
3. `raw_index_daily_registered_code_coverage_check` 的长期名称是否保持 `registered` 字样；语义已限定为运行时 Lake 期望 code set，不再表示“按生命周期推导有效 code”。若要进一步降歧义，可在实现前改名为 `raw_index_daily_expected_code_coverage_check`。
4. P3/P4 bootstrap 代码在 P7 的处理方式：删除，还是移到 active static gate 不扫描的离线工具目录。无论选哪种，生产 `src/orchestrator/defs/**` 旧 by-code 符号必须清零。
5. 新 `raw_index_daily` catalog 是否新增专用 `_prod_core_raw_entry(...)` helper；若不新增 helper，也必须直接用 `_entry(...)` 写全字段，禁止套 `_tushare_raw_entry(...)` 或 `_derived_entry(...)`。

## 最终验收标准

1. `raw_index_daily[trade_date]` 是指数日线唯一 active raw asset。
2. raw 与 silver 共享运行时 Lake 期望 code universe。
3. raw 文件仍是 raw 契约，不混入 silver 字段。
4. 日更默认从 prod-core-db 同步，起点由当前 Lake 最新已就绪交易日之后的 expected trade date 计算，且 prod source 对本次期望 code 不齐备时不触发 Lake 更新。
5. P0 profiling 确认的历史 by-date 文件从当前 DG raw-by-code 文件无损转换；runless events 补录完成。
6. `raw_tushare_index_daily_by_code` active 代码与 catalog 口径清零。
7. sensors 不再 per-code 提交指数日线 raw run。
8. 性能报告记录 prod-core-db 单日读取、历史转换、runless event 写入和 sensor tick 耗时。
