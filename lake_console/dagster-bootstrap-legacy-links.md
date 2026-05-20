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
3. `source_method=old_lake_bootstrap` 只允许进入 Dagster materialization metadata，不允许进入 Parquet 业务字段。
4. 后续日常生产必须走 `TushareResource` 或对应正式资源，不允许继续依赖旧湖 bootstrap 链路。
5. 清理旧链路前必须做引用审计、Definitions 审计、运行记录审计和路径契约审计。

## 当前旧链路清单

| 数据集 | 旧湖输入 | 新湖 raw 目标 | 专用 spec / template | migration-only job | 当前状态 |
|---|---|---|---|---|---|
| `suspend_d` | `/Volumes/datasource/goldenshare-tushare-lake/raw_tushare/suspend_d/trade_date={partition_key}/part-000.parquet` | `/Volumes/datasource/data_lake/raw/tushare/suspend_d/trade_date={partition_key}/part-000.parquet` | `suspend_d_bootstrap_spec` / `SUSPEND_D_BOOTSTRAP_SELECT_TEMPLATE` | 暂未新增独立 job，当前通过 asset selection 验证 | 已完成 Slice 2.0.3 单日验证 |
| `trade_calendar` | `/Volumes/datasource/goldenshare-tushare-lake/raw_tushare/trade_cal/current/part-000.parquet` | `/Volumes/datasource/data_lake/raw/tushare/trade_calendar/full/part-000.parquet` | `trade_calendar_bootstrap_spec` / `TRADE_CALENDAR_BOOTSTRAP_SELECT_TEMPLATE` | `bootstrap_calendar_job` | 已完成 Slice 2.0.4 验证 |
| `stock_basic` | `/Volumes/datasource/goldenshare-tushare-lake/raw_tushare/stock_basic/current/part-000.parquet` | `/Volumes/datasource/data_lake/raw/tushare/stock_basic/full/part-000.parquet` | `stock_basic_bootstrap_spec` / `STOCK_BASIC_BOOTSTRAP_SELECT_TEMPLATE` | `bootstrap_basic_update_job` | 已完成 Slice 2.0.4 验证 |
| `stock_daily` | `/Volumes/datasource/goldenshare-tushare-lake/raw_tushare/daily/trade_date={partition_key}/part-000.parquet` | `/Volumes/datasource/data_lake/raw/tushare/stock_daily/trade_date={partition_key}/part-000.parquet` | `stock_daily_bootstrap_spec` / `STOCK_DAILY_BOOTSTRAP_SELECT_TEMPLATE` | `bootstrap_quote_daily_job` | 已完成 Slice 2.0.5 验证 |

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

## 清理门禁

清理某个具体数据集旧链路前，必须至少完成以下审计：

1. 代码静态审计：搜索该数据集的 spec 名称、template 名称、旧湖路径、migration job 名称、`old_lake_bootstrap` 引用。
2. Dagster Definitions 审计：确认没有 sensor、schedule、ongoing job、declarative automation 或 readiness gate 引用该旧链路。
3. 运行记录审计：确认该数据集历史 bootstrap 已完成，materialization metadata 中能查到迁移记录。
4. 路径契约审计：确认正式 asset path 中没有旧湖路径概念，Parquet 字段中没有 `source_method`、旧湖路径或 bootstrap 系统字段。
5. 验证审计：删除或调整后必须通过 `uv run dg check defs`，并通过相关 raw/silver assets 和 checks 验证。

## 保留策略

默认保留通用 bootstrap 引擎。

具体数据集旧链路是否保留，按以下原则处理：

- 若后续还有相似数据集需要参考迁移写法，可以保留 spec/template/job 作为迁移审计和模板。
- 若该数据集已经完全进入 Tushare 日常更新链路，且旧链路不再需要重跑，可以在完成清理门禁后删除具体 spec/template/job。
- 删除旧链路不得影响通用 bootstrap 引擎，也不得影响新湖 raw/silver/gold 正式资产。
