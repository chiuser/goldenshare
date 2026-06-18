# Dagster Orchestrator 编码规范

本文档是 `lake_console/orchestrator` 的长期编码规范入口。后续新增编码规则优先追加到本文档；`AGENTS.md` 只保留硬门禁和指向关系。

## 命名与组织原则

正式代码命名必须表达长期业务含义和稳定技术职责，禁止表达临时阶段、开发过程、个人理解或一次性任务。

## Dagster Definition 命名规则

新增或改名正式 Dagster definition 时，必须先在设计方案中列清 asset、job、sensor、check 的最终名称，并按以下规则对账。已有正式 check 名称不得为了追求命名整齐而改名；只有新增 check 才执行新规则，避免旧分区 check event 全量失效。

规则：

1. asset 名称必须表达稳定事实身份，通常采用 `layer + asset name`。raw 层如源系统是事实身份的一部分，可以包含 source，例如 `raw_tushare_stock_daily`；silver/gold/serving 层优先使用业务事实名，例如 `silver_stock_daily`、`gold_market_breadth_daily`。
2. job 名称固定采用 `layer + asset name + mode + job`，例如 `raw_stock_daily_update_job`、`silver_stock_daily_update_job`、`prod_ch_share_fact_market_breadth_sync_job`。job 名称必须表达写入层级、资产族和执行模式。
3. sensor 名称固定 follow job，采用 `job name + sensor`，例如 `raw_stock_daily_update_job_sensor`、`silver_stock_daily_update_job_sensor`。
4. 新增 check 名称固定采用 `asset name + function + check`，例如 `raw_tushare_stock_daily_source_contract_check`。`function` 必须表达单一质量属性，不得写成宽泛的 `quality`、`validate`、`daily`。
5. 已存在的 check 名称禁止仅因不符合新命名规则而改名；确需改名时必须先单独评估历史 check event、readiness helper、sensor、job selection、UI 状态和补跑成本，并等待用户确认。
6. 不得新增一个同语义新名 check 来替代旧 check；新增 check 必须代表新增质量语义。

## Run Key 与 Upstream Batch ID 规范

Dagster `run_key` 只用于 sensor / schedule 提交 `RunRequest` 时的幂等去重身份，不承载执行参数。

规则：

1. 正式 sensor 的 run key 必须通过 `orchestrator.defs.run_contracts.run_keys` 中的统一 builder 生成。
2. 禁止在 sensor 文件中手写 `run_key=f"..."`、字符串拼接模板或局部 run key helper。
3. 禁止为单个数据集新增专属 run key 函数；只能复用通用类型，例如 asset update、repair attempt、upstream-triggered run key。
4. 禁止解析 `run_key` 生成 `run_config`；执行参数只能来自显式 `run_config`、`partition_key`、上游 metadata/status，或正式定义的 `upstream_batch_id`。
5. 上下游触发场景必须由上游提供 opaque `upstream_batch_id`，下游 run key 只使用 `consumer + upstream_batch_id`。
6. Dagster `event_storage_id`、`storage_id` 或其集合不得进入正式 run key、正式 run config、upstream batch id payload 或 completion identity。
7. M7 后 legacy bridge 已退出；旧 event storage id 字段不得进入生产代码的 run key、run config、upstream batch id payload 或 completion identity，也不得恢复只读旧 completion metadata 防重复逻辑。测试只允许保留负向断言或静态门禁样本。
8. 修改 run key 口径时，必须同步更新 `lake_console/docs/design/dagster-run-key-governance-optimization-plan.md` 和 `lake_console/docs/design/dagster-run-key-governance-low-level-design.md`。

## 股票分钟线连续性规范

股票分钟线 raw / silver / qfq 日常链路必须以交易日历 expected dates 作为权威日期来源，dynamic partitions 只表示 Dagster 已注册状态，不能替代权威交易日历。

已落地规则：

1. 股票分钟线日常 sensor 不得用 latest registered partition 作为正式目标；目标必须来自 expected calendar + first missing registered / first not ready / first repair not completed 口径。
2. `stock_mins_trade_day_sensor` 保留 18:00 同日注册窗口，但停机恢复后必须能按 expected calendar 补最早缺失 raw trade day。
3. `stock_mins_silver_trade_day_sensor`、`stock_mins_silver_sensor`、`stock_mins_qfq_daily_sensor`、`stock_mins_qfq_factor_repair_sensor` 不得越过更早 expected date 的注册缺口、未 ready 状态或 blocking check failure。
4. qfq factor repair op/helper 的 previous date 与 selected repair range 必须来自 expected calendar；不得恢复 registered-only 的 `_previous_trade_date(...)` 或 `_select_repair_partition_keys(...)` 口径。
5. 已 materialized 但 blocking checks 未绿的股票分钟线目标日期，不得自动重跑并推进后续日期；必须按现有人工处理口径 fail/skip closed。

MACD/KDJ 连续性已落地规则：

1. MACD/KDJ daily run-status sensor、daily asset write 和 repair op 都必须使用 expected calendar 口径；不得恢复 previous registered、registered-only range 或任意更早 state fallback。
2. MACD/KDJ daily asset write 非 baseline 日期必须要求上一 expected trade date 的 state 文件精确存在；只有 `STK_MINS_MACD_KDJ_BASELINE_START_DATE` 且无上一 expected date 时，才允许无 previous state 初始化。
3. MACD/KDJ repair op 的 target dates 必须来自 qfq factor repair metadata/status 的 start/end 闭区间 expected range；range 内 expected date 未注册、qfq source 缺失或上一 expected state 缺失时必须 fail closed，且失败路径不得写 completion checks。
4. 连续性专项 M1-M11 已完成；后续修改必须保持静态门禁和测试覆盖，不能恢复 latest registered / previous registered / registered-only range / latest-before-state 口径。

## Asset Schema Contract 与 Metadata 规范

正式 Dagster asset 的稳定字段契约必须在 asset definition metadata 中注册，禁止只靠某次 materialization metadata 承载。

规则：

1. 新增或修改正式 asset 时，必须在 `build_asset_definition_metadata(...)` 中显式传入 `column_schema=...`。
2. 字段契约统一定义在 `defs/run_contracts/asset_column_schemas.py`，使用 `ColumnContract(name, type, description)` 表达字段名、类型和中文说明。
3. `dagster/column_schema` 只允许出现在 definition metadata 中，表示“这个资产应该是什么字段契约”。
4. materialization metadata 只记录本次运行观察结果，例如 `dagster/uri`、`dagster/row_count`、`goldenshare/observed_columns`、样本和统计。
5. 禁止重新引入 `build_materialization_metadata(columns=...)`；运行时字段列表必须使用 `observed_columns=...`。
6. check metadata 如需记录字段观察结果，也必须使用 `observed_columns` 或显式 `goldenshare/observed_columns`，禁止裸写 `columns`。
7. raw、silver、gold、serving 的字段类型必须反映对应层级真实契约，不能为了 UI 好看改写实际数据类型。例如 raw 层 Tushare 日期字符串仍是 `VARCHAR`，silver/gold 标准日期才是 `DATE`。

## Lake Asset Catalog Registry 规范

正式 active asset 的资产事实必须登记在 `orchestrator.defs.catalog.lake_assets.LAKE_ASSET_CATALOG`，禁止回到测试、asset 文件、job 文件或 bootstrap helper 各自维护事实表。

规则：

1. 新增或修改正式 active asset 时，必须同步更新 `LakeAssetCatalogEntry`。
2. entry 至少覆盖：asset key、dataset id/name、layer、domain、group、source system、data contract、data contract source、column schema、path template、partition model、source/ingestion/bootstrap sources、blocking checks、write policy、event policy、performance contract。
3. 新增 partition model 时，必须同步登记 `PartitionModelDefinition`；命名采用“分区维度 + layer + 资产名”的层级方式，例如 `trade_date_partition_raw_stock_daily`。物理布局特例可以在名称尾部补充，例如 `trade_date_partition_gold_stock_mins_qfq_stock_year_file`。
4. entry 必须与 `build_asset_definition_metadata(...)`、`build_asset_tags(...)`、path helper、`dagster/column_schema` 和 active blocking check specs 对账一致。
5. `lake_root_health` 这类 platform health asset 可以无 table column schema；其它 table-like/parquet/serving assets 必须有稳定字段契约。
6. `LAKE_ASSET_CATALOG` 是 C1 只读 registry，不自动生成 asset/check/job/sensor，不替代底层 path/schema helper。业务运行逻辑消费 catalog 必须另行设计，不得临时耦合。
7. catalog 模块不得 import `src.foundation`、`lake_console.backend`、Dagster instance、DuckDB、数据库、网络客户端或 lake 扫描逻辑。
8. 禁止恢复 `ASSET_CONTRACTS`、`ASSET_PATH_TEMPLATES`、`ASSET_COLUMN_SCHEMAS` 这类隐形 catalog；测试和静态门禁必须从 registry 反查事实。

## DuckDB 连接规范

正式 `src/orchestrator/defs/**` 生产路径禁止直接调用 `duckdb.connect()`。

规则：

1. 只有 `orchestrator.defs.duckdb_connection.connect_configured_duckdb(...)` 可以直接创建 DuckDB 连接。
2. asset、check、bootstrap helper、qfq helper、repair op/helper、sensor readiness helper 必须通过 `DuckDBResource` 或统一连接 helper 获取连接。
3. DuckDB 默认连接参数固定为：`temp_directory=/Volumes/datasource/.goldenshare_duckdb_tmp`、`max_temp_directory_size=512GB`、`memory_limit=16GB`、`threads=4`、`preserve_insertion_order=false`。
4. 正式输出排序必须由 SQL `ORDER BY` 显式保证，不能依赖 DuckDB insertion order。
5. 测试文件可以直接创建临时 DuckDB 连接；离线 `audits/**` 工具暂不纳入本规则强制范围，但如果未来写正式 lake 或正式 Dagster event，必须改走统一连接 helper。
6. 新增 DuckDB 配置项前必须先做配置项审计；不得把 DuckDB 参数临时散落到 env、run config、脚本常量或文档口径中。

## Asset 写前 Guard 规范

正式 asset 写入函数默认不得混入定制化写前 guard；普通质量与完整性要求必须通过 blocking asset checks 表达。

已确认例外：`silver_stock_daily` 写入前必须调用 `assert_silver_stock_basic_fresh_for_stock_daily(...)`。这是生产前置事实门禁，用来防止人工 Launchpad、CLI 或补录绕过 `stock_daily_sensor` 后，在 stale `silver_stock_basic` 下静默过滤新股；它不等同于把普通质量 check 混入 asset 写入逻辑。

### 禁止阶段编号进入正式代码

阶段编号只允许出现在设计文档、开发计划和提交说明中，不允许进入正式代码主概念。

禁止在正式文件名、函数名、变量名、asset/job/check/sensor/resource 名中使用以下语义：

```text
phase3
slice_301
poc
temp
new
old
final
```

示例：

```text
不合格：ensure_phase3_tables()
合格：  ensure_index_metadata_tables()
```

原因：`phase3`、`slice_301` 这类名字只对当前开发过程有意义，不能表达长期业务职责。半年后维护者不应该靠回忆开发阶段来理解代码。

### 文件名按数据域或职责命名

文件名必须体现数据集、数据域或稳定职责，不能只表达“装东西的盒子”。

示例：

```text
合格：  bootstrap/dataset_spec.py
合格：  jobs/index_daily_update.py
合格：  checks/market_major_indices_checks.py

不合格：bootstrap/types.py
不合格：jobs/update.py
不合格：utils.py
不合格：helpers.py
不合格：common.py
```

例外：如果目录本身已经限定得非常窄，且文件职责仍然一眼明确，可以使用较短名称；否则禁止使用宽泛文件名。

### 函数名必须表达动作和对象

函数名必须说明“对什么对象做什么事”。

示例：

```text
合格：  ensure_index_metadata_tables()
合格：  write_market_major_indices_snapshot()
合格：  load_market_major_indices_seed()

不合格：process_data()
不合格：sync_all()
不合格：handle_config()
不合格：ensure_phase3_tables()
```

### 变量名必须表达业务语义

变量名必须让读代码的人知道它承载的业务含义。

示例：

```text
合格：  active_pool_rows
合格：  major_indices_items
合格：  effective_index_codes

不合格：data
不合格：result
不合格：tmp_list
不合格：items2
```

例外：极短作用域内的通用局部变量可以使用短名称，但不能影响理解，也不能逃避业务语义。

### 一次性迁移来源不得污染长期主概念

一次性迁移、bootstrap、历史来源可以出现在设计文档、source method、materialization metadata 或审计记录中，但不能污染长期 asset/job 命名。

示例：

```text
合格 asset：raw_tushare_stock_daily
合格 metadata：source_method=old_lake_bootstrap

不合格 asset：old_lake_stock_daily_asset
```

### 面向未来维护者命名

正式代码名应优先服务未来维护者，而不是当前开发者。

一个名字半年后看，应该仍能判断：

1. 属于哪个数据域。
2. 维护什么资产或能力。
3. 是正式链路、初始化入口、维护入口，还是测试替身。

如果一个名字需要靠解释“这个 phase/slice 当时是什么意思”才能理解，它就是不合格名字。
