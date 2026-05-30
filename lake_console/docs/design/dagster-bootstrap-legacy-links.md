# Dagster Bootstrap 旧链路记录

## 定位

本文档专门记录 Dagster bootstrap 过程中产生的“具体数据集旧链路”。

这里的旧链路指：

- 某个数据集从旧湖读取的输入路径。
- 某个数据集专用的 `BootstrapDatasetSpec`。
- 某个数据集专用的 bootstrap `select_sql_template` / cast 规则。
- 某个数据集专用的 migration-only bootstrap job。

它不等于通用 bootstrap 引擎。

通用 bootstrap 引擎是长期迁移能力，会继续服务后续数据集迁移；具体数据集的旧链路通常只服务一次历史拉齐，完成后不进入日常生产、不被 sensor/schedule/declarative automation 触发。

## 总原则

1. 新湖正式资产路径只允许位于 `data_lake/raw`、`data_lake/silver`、`data_lake/gold`。
2. 旧湖路径只允许出现在本文档、bootstrap spec、migration-only job 或迁移审计记录中。
3. `source_method=old_lake_bootstrap` 只允许进入迁移审计 metadata，不允许进入 Parquet 业务字段，也不能作为下游业务判断条件。
4. 后续日常生产必须走 `TushareResource` 或对应正式资源，不允许继续依赖旧湖 bootstrap 链路。
5. 清理旧链路前必须做引用审计、Definitions 审计、运行记录审计和路径契约审计。

## 当前旧链路清单

| 数据集 | 旧湖输入 | 新湖目标 | 专用 spec / template | migration-only job | 当前状态 |
|---|---|---|---|---|---|
| `suspend_d` | `/Volumes/datasource/goldenshare-tushare-lake/raw_tushare/suspend_d/trade_date={partition_key}/part-000.parquet` | `/Volumes/datasource/data_lake/raw/tushare/suspend_d/trade_date={partition_key}/part-000.parquet` | `suspend_d_bootstrap_spec` / `SUSPEND_D_BOOTSTRAP_SELECT_TEMPLATE` | 暂未新增独立 job，当前通过 asset selection 验证 | 已完成 Slice 2.0.3 单日验证 |
| `trade_calendar` | `/Volumes/datasource/goldenshare-tushare-lake/raw_tushare/trade_cal/current/part-000.parquet` | `/Volumes/datasource/data_lake/raw/tushare/trade_calendar/full/part-000.parquet` | `trade_calendar_bootstrap_spec` / `TRADE_CALENDAR_BOOTSTRAP_SELECT_TEMPLATE` | `bootstrap_calendar_job` | 已完成 Slice 2.0.4 验证 |
| `stock_basic` | `/Volumes/datasource/goldenshare-tushare-lake/raw_tushare/stock_basic/current/part-000.parquet` | `/Volumes/datasource/data_lake/raw/tushare/stock_basic/full/part-000.parquet` | `stock_basic_bootstrap_spec` / `STOCK_BASIC_BOOTSTRAP_SELECT_TEMPLATE` | `bootstrap_basic_update_job` | 已完成 Slice 2.0.4 验证 |
| `stock_daily` | `/Volumes/datasource/goldenshare-tushare-lake/raw_tushare/daily/trade_date={partition_key}/part-000.parquet` | `/Volumes/datasource/data_lake/raw/tushare/stock_daily/trade_date={partition_key}/part-000.parquet` | `stock_daily_bootstrap_spec` / `STOCK_DAILY_BOOTSTRAP_SELECT_TEMPLATE` | `bootstrap_quote_daily_job` | 已完成 Slice 2.0.5 验证 |
| `adj_factor` | `/Volumes/datasource/goldenshare-tushare-lake/raw_tushare/adj_factor/trade_date={partition_key}/part-000.parquet` | `/Volumes/datasource/data_lake/raw/tushare/adj_factor/trade_date={partition_key}/part-000.parquet` | `adj_factor_bootstrap_spec` / `ADJ_FACTOR_BOOTSTRAP_SELECT_TEMPLATE` | 未新增独立 job；M5 使用受控 Python 命令直接调用现有 bootstrap executor；M6B 使用 runless events 补录 Dagster 事件事实 | M5 raw 迁移已完成；M6B raw event 补录已完成；M6C silver 文件生成已完成；M6D silver event 补录已完成；A7 已补齐至 `2026-05-29` |
| `stk_mins` | `/Volumes/datasource/backup/research/stk_mins_by_date_clean_next/freq={freq}/trade_date={partition_key}/*.parquet` | `/Volumes/datasource/data_lake/raw/tushare/stk_mins/freq={freq}/trade_date={partition_key}/part-000.parquet` | `stk_mins_bootstrap_spec` / `STK_MINS_BOOTSTRAP_SELECT_TEMPLATE` | 未新增 active job；M3 使用受控 CLI/helper 执行 dry-run、样本、全量迁移、分区注册和 runless event 补录 | M3 raw 迁移、分区注册和 event 补录已完成 |
| `stock_identity_map` | `/Volumes/datasource/goldenshare-tushare-lake/manifest/security_identity/security_identity_map.parquet` | `/Volumes/datasource/data_lake/silver/basic/stock_identity_map/part-000.parquet` | `stock_identity_map_bootstrap_spec` / `STOCK_IDENTITY_MAP_BOOTSTRAP_SELECT_TEMPLATE` | 未新增 active job；M3 使用 dataset-specific helper 写 full snapshot，并通过 runless events 补录 UI/readiness 事实 | M3 初始化写入和 event 补录已完成 |

## 已确认的迁移纠偏规则

### `suspend_d`

- 旧湖 `trade_date` 可能是 Parquet `DATE`，新湖 raw 必须写成 Tushare 源站镜像的 `YYYYMMDD` 字符串。
- 旧湖 `suspend_timing` 存在类型漂移：全空分区可能被 DuckDB 推断为 `INTEGER/NULL`，有值分区可能是 `VARCHAR`。
- bootstrap 读取旧湖时必须使用 `union_by_name=true`，并显式 `cast(suspend_timing as varchar)`。
- `empty_policy=allow_empty`，因为某个交易日可能没有停复牌记录，但仍需要一个合法空 parquet 表示“已确认无记录”。

### `trade_calendar`

- 旧湖实际路径是 `raw_tushare/trade_cal/current/part-000.parquet`，不是文档示例里的 `trade_calendar/full`。
- 旧湖 `is_open` 是 boolean，新湖 raw 必须纠偏为 Tushare 源站镜像的 `0/1`。
- 旧湖 `cal_date/pretrade_date` 可能是 `YYYY-MM-DD` 字符串，新湖 raw 必须写成 `YYYYMMDD` 字符串。
- `empty_policy=require_positive`。

### `stock_basic`

- 旧湖实际路径是 `raw_tushare/stock_basic/current/part-000.parquet`。
- 新湖 raw 只保留 Tushare `stock_basic` 显式字段全集。
- `list_date/delist_date` 保持 `YYYYMMDD` 字符串或 null；日期标准化只在 silver 层做。
- `empty_policy=require_positive`。

### `stock_daily`

- 旧湖实际路径是 `raw_tushare/daily/trade_date={partition_key}/part-000.parquet`，不是 `stock_daily` 目录。
- 旧湖 `trade_date` 是 Parquet `DATE`，新湖 raw 必须纠偏为 Tushare 源站镜像的 `YYYYMMDD` 字符串。
- 新湖 raw 字段名保留 Tushare `daily` 源字段 `change`；silver 层再标准化为 `change_amount`。
- `empty_policy=require_positive`，因为已完成交易日的股票日线 raw 不应为空。
- `STOCK_DAILY_BOOTSTRAP_SELECT_TEMPLATE` 会经过 Python `str.format(...)` 渲染；SQL 正则中的 `{8}` 必须写成 `{{8}}`，否则会被误识别成 format 占位符。
- Slice 2.0.5 已用正式 `DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home` 跑通 2026-04 全月 21 个交易日。
- 2026-04 验证结果：`bootstrap_quote_daily_job` 全部分区成功，raw/silver blocking checks 全部通过，`silver_stock_daily_covers_expected_tradable_universe` 全部通过，`unexplained_missing_count=0` 且 `unexplained_extra_count=0`。

### `adj_factor`

- 旧湖实际路径是 `raw_tushare/adj_factor/trade_date={partition_key}/part-000.parquet`。
- 旧湖 `trade_date` 是 Parquet `DATE`，但新湖 raw 契约必须写成 Tushare 源站镜像的 `YYYYMMDD` 字符串。
- `ADJ_FACTOR_BOOTSTRAP_SELECT_TEMPLATE` 同时兼容旧湖 `DATE` 和 `YYYYMMDD` 字符串输入。
- `empty_policy=require_positive`，因为已完成交易日的复权因子 raw 不应为空。
- M5 已完成正式旧湖 raw 迁移：`4215` 个分区，范围 `2009-01-05` 至 `2026-05-15`，总行数 `14,959,706`。
- M5 已把上述 `4215` 个日期注册到正式 `cn_a_stock_current_trade_days`。
- M5 不等同于 Dagster materialization：它没有补 raw asset materialization event，也没有生成 raw asset check event。
- M6B 已通过 `DagsterInstance.report_runless_asset_event(...)` 对已迁移 raw 文件补录 `raw_tushare_adj_factor` materialization 与 raw blocking check events；最终 `4215` 个 raw 分区可见，8 个 raw blocking checks 均为 `succeeded=4215, failed=0`。
- M6 的 silver 历史文件生成属于 bootstrap 收尾，不能使用 `stock_adj_factor_update_job` 跑历史，因为该 job 会重新请求 Tushare raw。
- M6C 已生成 `silver_adj_factor` 历史文件：`4215` 个分区，范围 `2009-01-05` 至 `2026-05-15`，总行数 `13,908,872`，全量只读审计失败分区数 `0`。
- M6D 已补录 `silver_adj_factor` 的 runless materialization 与 silver blocking check events；最终 `4215` 个 silver 分区可见，10 个 silver blocking checks 均为 `succeeded=4215, failed=0`。
- M6B runless events 不产生 Runs 页面记录，也不会触发飞书 run status 通知。
- M6D 之后，已补注册并通过人工 `stock_adj_factor_update_job` 补齐 `2026-05-18` 至 `2026-05-29` 这 10 个交易日分区。
- 最新只读核验：`cn_a_stock_current_trade_days`、raw 文件、silver 文件、raw materialization、silver materialization 均为 `4225` 个分区，范围 `2009-01-05` 至 `2026-05-29`；raw 8 个 blocking checks 和 silver 10 个 blocking checks 均为 `succeeded=4225, failed=0`。

### `stk_mins`

- backup 输入不属于正式新湖路径，只是历史 raw 初始化来源。
- backup 目录中部分分区文件名为 `part-00000.parquet`；bootstrap 来源按 `*.parquet` 解析，但每个 `freq + trade_date` 必须恰好一个 parquet 文件。
- 新湖 raw 目标统一为 `part-000.parquet`，不得继承 backup 文件名差异。
- `empty_policy=require_positive`，因为已完成交易日的分钟线 raw 不应为空。
- M2 已实现 spec/helper 与临时目录测试；M3 已完成正式迁移、`cn_a_stock_mins_trade_days` 注册和 runless event 补录。
- M3 最终结果：五个频度各 `4209` 个 raw 文件，合计 `21045` 个；动态分区 `4209` 个，范围 `2009-01-05` 至 `2026-05-07`；五个 raw asset 各 `4209` 个 materialized 分区，7 个 raw blocking checks 均为 `succeeded=4209, failed=0`。
- M3 执行中发现 backup clean_next 历史存在 `low=0`、`vwap=0`、停牌结构行全 0、少量 OHLC 区间残留。raw event check 正式口径为只拦空值、负值和空代码，保留 backup 原始 clean_next 事实；更强的价格逻辑治理留给后续 silver 标准化。
- M3 执行过程中外挂盘曾短暂掉挂载，导致一次全量 event 补录在审计阶段失败；恢复挂载后先做断点审计，确认 raw 文件、动态分区和样本 events 一致，再继续补录。

### `stock_identity_map`

- 来源是旧湖 `manifest/security_identity/security_identity_map.parquet`，只作为 `silver_stock_identity_map` 初始 full snapshot bootstrap 来源。
- 该数据集不是 raw 层，因此不复用 `BootstrapDatasetSpec`；M2 使用 dataset-specific helper 写入 `data_lake/silver/basic/stock_identity_map/part-000.parquet`。
- 写入时显式归一日期字段和 `created_at` 类型，并验证行数为正、字段顺序符合 `SILVER_STOCK_IDENTITY_MAP_SCHEMA`。
- M3 已写入 `silver_stock_identity_map` full snapshot：`6089` 行；已补录 1 个 runless materialization 与 9 个 blocking check events，最终 checks 均为 `succeeded=1, failed=0`。
- 长期生成逻辑后续必须由新湖基础事实重建，不允许继续把旧湖 manifest 作为日常依赖。

## 清理门禁

清理某个具体数据集旧链路前，必须至少完成以下审计：

1. 代码静态审计：搜索该数据集的 spec 名称、template 名称、旧湖路径、migration job 名称、`old_lake_bootstrap` 引用。
2. Dagster Definitions 审计：确认没有 sensor、schedule、ongoing job、declarative automation 或 readiness gate 引用该旧链路。
3. 运行记录审计：确认该数据集历史 bootstrap 已完成，materialization metadata 中能查到迁移记录。
4. 路径契约审计：确认正式 asset path 中没有旧湖路径概念，Parquet 字段中没有 `source_method`、旧湖路径或 bootstrap 系统字段。
5. 验证审计：删除或调整后先做静态编译、单元测试、文档完整性检查和引用扫描；如确需运行 `dg check defs` 或相关 Dagster 验证，必须按正式 Dagster 环境执行门禁单独列命令和影响范围，并取得明确批准。

## 保留策略

默认保留通用 bootstrap 引擎。

具体数据集旧链路是否保留，按以下原则处理：

- 若后续还有相似数据集需要参考迁移写法，可以保留 spec/template/job 作为迁移审计和模板。
- 若该数据集已经完全进入 Tushare 日常更新链路，且旧链路不再需要重跑，可以在完成清理门禁后删除具体 spec/template/job。
- 删除旧链路不得影响通用 bootstrap 引擎，也不得影响新湖 raw/silver/gold 正式资产。
