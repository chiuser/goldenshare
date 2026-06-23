# Dagster Index Daily Raw By-Date Prod DB Migration Plan

状态：方案设计，未实现。

LLD：[`dagster-index-daily-raw-by-date-prod-db-migration-low-level-design.md`](./dagster-index-daily-raw-by-date-prod-db-migration-low-level-design.md)。

## 目标

将指数日线 `index_daily` 从当前的 `raw_tushare_index_daily_by_code[ts_code]` 迁移为 `raw_index_daily[trade_date]`：

1. Dagster 从远程 prod DB 的 `core_serving.index_daily_serving` 按 prod `ops.index_series_active(resource='index_daily')` 指数代码集合同步指数日线到 raw 层。
2. raw 层与 silver 层使用同一个冻结后的 Lake 期望 code set。raw 不再按代码拆分物理资产，但代码覆盖范围必须由该 code set 和 `core_serving.index_daily_serving` 当日完整性共同约束。
3. `core_serving.index_daily_serving` 在目标交易日没有覆盖完整 Lake 期望 code set 时，不允许向 Lake 发起更新；sensor 必须 fail closed，返回明确 skip/block 原因。
4. 只有在 `raw_index_daily[trade_date]` 历史文件生成、校验和 runless materialization/check event 补录全部成功后，才删除 active `raw_tushare_index_daily_by_code` 资产、checks、job、sensor 依赖和物理旧文件。
5. 历史补录必须使用 runless event；必须先 dry-run、再样本 apply、再分批 full apply、最后只读验收。性能门禁是硬门禁。

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
| `lake_console/backend/app/services/prod_core_db.py` | 已有 `prod-core-db` 白名单导出能力：`index_daily/index_weekly/index_monthly` 映射到 `core_serving.index_*_serving`，禁止 `select *`，禁止 `source/created_at/updated_at`，并已有 `change_amount AS change` 字段映射。 | LLD 不能重新发明一套同义 resource/source contract；Dagster 实现必须对齐已落地字段白名单和安全门禁。 |
| `catalog/lake_assets.py` | catalog 记录当前 raw-by-code path 和 checks。 | 迁移时必须同步 catalog，旧资产删除后 active catalog 不得残留旧口径。 |

旧设计文档 `dagster-phase-3-index-daily-refactor-design.html` 曾将 raw 改为 by-code，是为了适配 Tushare 单 code 请求和单 code 修复；本方案是新的替代方案。by-code 在迁移期只作为审计参考，最终不再是 active 资产。

当前只读样本事实：

| 项 | 观测值 |
| --- | --- |
| 旧 raw-by-code parquet 文件数 | 约 946 个 `part-000.parquet` |
| 旧 raw-by-code 行数 | 约 3,419,161 行 |
| 旧 raw distinct trade dates | 约 6,792 个 |
| 旧 raw distinct ts_code | 约 946 个 |
| 当前 silver by-date parquet 文件数 | 约 6,410 个 |
| 本机 Dagster `cn_a_index_ts_codes` dynamic partitions | 946 个 code |
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

但追加对账发现：DG 当前管理 946 个 code，其中 86 个不在 prod `core_serving.index_daily_serving` 全历史中。因此，本迁移不能直接把 prod `index_daily` active pool 写成 Lake 期望集合，也不能直接假设 prod serving 已覆盖本地 DG 管理集合。正式实现前必须先冻结 Lake 期望 code set：

1. 若继续按当前实现，以 `cn_a_index_ts_codes` dynamic partitions 作为 DG 管理集合，则 source completeness gate 必须检查 prod serving 是否覆盖这 946 个 code；当前 86 个缺口是硬阻断。
2. 若决定改为 prod `index_daily` active pool，则必须设计 DG dynamic partitions、旧 raw/silver 文件、checks、runless events 的迁移和清理，不能只改 source gate。

## 目标口径

### 资产与分区

| 层级 | 目标资产 | 分区 | 物理路径建议 | 说明 |
| --- | --- | --- | --- | --- |
| Raw | `raw_index_daily[trade_date]` | `cn_a_index_trade_days` | `raw/index_daily/trade_date=<YYYY-MM-DD>/part-000.parquet` | source-neutral raw 路径；本迁移只允许 prod-core-db 写入该 raw 契约。 |
| Silver | `silver_index_daily[trade_date]` | `cn_a_index_trade_days` | 不变 | 从同日 raw by-date 文件生成 silver。 |

不建议继续使用 `raw/tushare/index_daily/...` 作为新路径。原因是正式来源会切到 prod-core-db；路径名不应谎称唯一来源是 Tushare。来源信息放在 asset metadata 和 materialization metadata 中。

### 代码集合

`cn_a_index_ts_codes` 不再作为 raw asset partition key，但它是当前实现里 DG 管理的指数代码集合事实源。代码集合不能再凭设计猜测，必须先按当前实现和 prod source 对账后冻结：

1. 当前实现读取 `context.instance.get_dynamic_partitions(cn_a_index_ts_codes.name)`，本机 Dagster 当前为 946 个 code。
2. 更新前必须只读校验 `core_serving.index_daily_serving[trade_date]` 的 distinct code 集合覆盖已冻结的 Lake 期望 code set。
3. 若 source 少 code、多个 code、重复 key、目标日期没有数据或查询失败，sensor 不提交 Lake 更新 run。
4. `index_daily_raw` 请求池只说明旧 Tushare 请求范围，不参与本迁移的 raw by-date 更新门禁。
5. 不使用 `silver_index_basic list_date/exp_date` 计算 raw 更新的“有效 code 集合”；该设计会把源数据齐备性检查偷换成指数生命周期推断。

这里的“raw 层和 silver 层 code 数量一致”指二者共享同一个已冻结 Lake 期望 code set 和同一套 prod source 完整性门禁，不表示由 Lake 本地 `silver_index_basic` 重新推导 code universe。

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

### 来源优先级

正式日更默认走 prod-core-db：

1. source table 只允许 `core_serving.index_daily_serving`。
2. 只读连接使用 `ProdPostgresResource`。
3. 远端 SQL 必须显式列字段、按 `trade_date` 和已冻结 Lake 期望 code set 过滤。
4. 任何 schema/字段名不确定，先做 prod-core-db 只读 profiling，不得猜字段。
5. 更新触发前必须先执行 source completeness gate：`core_serving.index_daily_serving` 当日 code 集合必须完整覆盖已冻结 Lake 期望 code set；不一致时不发起 Lake 更新。

本方案不实现 Tushare fallback。若未来需要 fallback，必须单独设计、单独性能评审、单独审批，不能混入本迁移。

## 实现阶段

### M0：只读 Profiling 与 LLD 前置

只读验证以下事实：

1. prod-core-db `core_serving.index_daily_serving` 的列名、类型、日期范围、代码范围。
2. 本机 Dagster `cn_a_index_ts_codes`、prod `ops.index_series_active(resource='index_daily')`、prod `core_serving.index_daily_serving` 三个 code set 的差异。
3. 冻结本迁移 Lake 期望 code set，并说明是否沿用当前 DG dynamic partitions。
4. 每个目标交易日 `core_serving.index_daily_serving` 是否完整覆盖已冻结 Lake 期望 code set。
5. 当前 prod serving 缺口的开始日期、截止日期、缺失 code 样本。
6. 从 prod DB 生成历史 by-date raw 文件的日期数、行数、重复键、异常样本、预计文件数和 runless event 数。

禁止写 prod DB、禁止写 lake、禁止写 Dagster event。

### M1：新 Raw By-Date 契约与 Source Adapter

新增或重命名以下契约：

1. `RAW_INDEX_DAILY_SCHEMA`：字段与当前 `RAW_TUSHARE_INDEX_DAILY_BY_CODE_SCHEMA` 一致，但命名不再绑定 Tushare/by-code。
2. `raw_index_daily_path(root, trade_date)` 与 staging path。
3. `raw_index_daily[trade_date]` asset。
4. prod-core-db source adapter：从 `core_serving.index_daily_serving` 读取目标 trade date 和已冻结 Lake 期望 code 集合，写 raw by-date parquet。

`SourceSystem` 需要新增稳定枚举，例如 `PROD_CORE_DB = "prod_core_db"`。catalog ingestion source 优先复用现有 `IngestionSource.PROD_DB_READONLY`，不得新增近义重复枚举。

### M2：Raw By-Date Checks

新增 raw by-date blocking checks：

| Check | 语义 |
| --- | --- |
| `raw_index_daily_file_exists` | 目标 by-date 文件存在。 |
| `raw_index_daily_row_count_positive` | 文件行数大于 0。 |
| `raw_index_daily_required_columns_and_types` | 字段和类型符合 `RAW_INDEX_DAILY_SCHEMA`。 |
| `raw_index_daily_partition_date_matches` | 文件内 `trade_date` 全部等于 partition trade date 的 `YYYYMMDD`。 |
| `raw_index_daily_unique_ts_code_trade_date` | `ts_code + trade_date` 唯一。 |
| `raw_index_daily_registered_code_coverage` | 目标日期 prod source code 集合覆盖完整；期望集合来自已冻结 Lake 期望 code set，并且必须已通过 source completeness gate。 |

不把 silver 的标准化检查提前到 raw，例如不检查 `trade_date DATE`、不要求 `change_amount` 字段。

### M3：历史 Prod DB 到 By-Date 文件生成

历史 by-date raw 文件正式来源是远程 prod DB，不直接复用旧 Lake by-code 文件。旧 Lake by-code 文件只允许作为只读参考和对账样本，不允许跨区引用或直接作为新 Lake 物理文件输入。

使用 DuckDB set-based SQL 或等价批量方式从 prod DB 生成，不允许 Python 逐行循环：

1. 读取 prod `core_serving.index_daily_serving`，字段显式白名单，禁止系统字段。
2. 每个目标交易日先校验 prod source 覆盖完整已冻结 Lake 期望 code set。
3. 按 `trade_date` 写入新路径。
4. 批量策略按年份或月份执行，避免一次性写全历史造成大内存和大量小文件异常。
5. 先写 staging root，校验通过后再替换正式目标。

验收必须覆盖：

- prod source 行数等于目标总行数；
- `distinct(ts_code, trade_date)` 不变；
- 每个 target date 文件 schema 正确；
- 每个 target date code coverage 与已冻结 Lake 期望 code set 一致；
- 失败样本输出到 `/private/tmp`，不进入 repo。

### M4：Runless Event Dry-Run 与补录

历史文件生成成功后才允许 runless event 补录。

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
3. prod-core-db source readiness 必须证明当日 serving code 集合完整覆盖已冻结 Lake 期望 code set；不齐备时 skip，不提交 run。
4. 每个 tick 最多提交少量 date-level run，日常建议 1 个。
5. run key 由统一 builder 生成，目标格式为 `raw_index_daily:<trade_date>`。
6. 不再使用 `next_pending_offset` 轮转 code。
7. 不再生成 `index_daily:<trade_date>:<ts_code>`。

`silver_index_daily_sensor` 改为：

1. 先检查 `raw_index_daily[trade_date]` readiness。
2. raw by-date ready 后，选择最早 silver not-ready 日期。
3. 不再扫描 raw-by-code 文件集合。

`index_daily_update_job` selection 改为 `raw_index_daily` + new raw checks。

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
- old by-code source IO helper；
- old by-code sensor gap/readiness helper；
- old tests 和 catalog entries。

物理路径 `raw/tushare/index_daily_by_code` 的删除必须单独审批，不与代码提交混在一起。

## 性能门禁

| 场景 | 性能口径 |
| --- | --- |
| prod-core-db 日更 | 每个 trade date 一次 bounded query；只读、显式字段、按日期和 code set 过滤；禁止全表扫描。 |
| prod-core-db 更新门禁 | 更新触发前必须校验 serving 当日 code 集合完整覆盖已冻结 Lake 期望 code set；缺口存在时不发起 Lake 更新。 |
| 历史生成 | 从远程 prod DB 读取并写 by-date raw；DuckDB set-based SQL；按年份/月批；不 Python 行循环；不一次性把全历史加载到 Python 内存。 |
| 文件写入 | staging root 写入 + 校验 + 受控替换；失败不得污染正式路径。 |
| runless event | dry-run、样本、分批、final audit；记录事件数量、批次耗时和失败样本。 |
| sensor 热路径 | 只看最近 continuity 窗口；不能读全历史 raw 文件；不能逐 code 提交大量 run。 |
| checks | by-date checks 只读目标日文件和必要 code universe，不扫描全历史。 |

停止条件：

1. prod-core-db 单日读取无法在可接受时间内完成，或必须扫全表。
2. prod source 当日没有完整覆盖已冻结 Lake 期望 code set。
3. 历史生成发现源/目标行数不一致、重复键无法解释、schema 不兼容。
4. runless dry-run 待写 event 数显著超出估算。
5. 新 sensor 需要恢复 per-code run 才能运行。
6. 任何实现需要在 raw 层输出 silver 字段或承担 silver 标准化职责。

## 测试与验收

### 本地测试

1. prod-core-db adapter 使用 fake connection 验证 SQL：
   - 显式字段；
   - 无 `SELECT *`；
   - 无 forbidden columns；
   - `trade_date` 和已冻结 Lake 期望 code set filter 必须存在。
   - source completeness gate 缺 code、extra code、重复 key、source 异常时都必须 fail closed。
2. raw by-date writer：
   - `trade_date` 是 `YYYYMMDD` 字符串；
   - 字段名是 `change`，不是 `change_amount`。
3. raw by-date checks：
   - 文件缺失、schema 错、日期错、重复键、coverage 缺失均 fail closed。
4. historical generator：
   - prod DB 样本生成 by-date；
   - 行数、唯一键、日期分区全部保持；
   - 旧 Lake by-code 文件只可作为对账参考，不参与正式写入。
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

1. prod-core-db source row count 与旧 raw/silver 可解释。
2. 已冻结 Lake 期望 code set 与 `core_serving.index_daily_serving` 每日覆盖可解释；缺口必须先补齐或显式阻断。
3. prod DB 到 by-date dry-run 预计文件数、行数、event 数。
4. 删除旧 by-code 前，active Dagster definitions 不再引用旧 asset。

## 需要单独审批的动作

以下动作不能随代码提交自动执行：

1. prod-core-db 正式只读 profiling。
2. 正式 lake 历史 by-date 文件生成 sample/full。
3. runless event sample/full 写入。
4. 正式 Dagster definitions 重载。
5. 旧 `raw/tushare/index_daily_by_code` 物理文件删除。

## 最终验收标准

1. `raw_index_daily[trade_date]` 是指数日线唯一 active raw asset。
2. raw 与 silver 共享已冻结 Lake 期望 code universe。
3. raw 文件仍是 raw 契约，不混入 silver 字段。
4. 日更默认从 prod-core-db 同步，且 prod source 不齐备时不触发 Lake 更新。
5. 历史 by-date 文件从 prod DB 生成，旧 Lake 文件只作为参考对账；runless events 补录完成。
6. `raw_tushare_index_daily_by_code` active 代码与 catalog 口径清零。
7. sensors 不再 per-code 提交指数日线 raw run。
8. 性能报告记录 prod-core-db 单日读取、历史生成、runless event 写入和 sensor tick 耗时。
