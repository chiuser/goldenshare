# M11: Gold stk_mins qfq 90/120 分钟资产设计方案

状态：M11 90/120 资产开发已完成；M11F 90/120 历史直写补录与 runless events 已全量执行；M11G quick/full audit 口径已落地并完成最终 full audit；M11H qfq daily/repair sensor readiness 性能修复已落地；M11H-2 cursor 快路径兼容修复已落地
日期：2026-06-06
范围：`lake_console/orchestrator` 正式 Dagster 新湖  

## 1. Summary

本方案新增两个 gold 层前复权股票分钟线资产：

- `gold_stk_mins_qfq_90m`
- `gold_stk_mins_qfq_120m`

90/120 不是 Tushare 或 prod DB 原生分钟频度，也不进入 raw/silver 源频度。它们是 gold qfq 资产族内的派生频度：

- `90m` 从 `gold_stk_mins_qfq_30m` 聚合生成。
- `120m` 从 `gold_stk_mins_qfq_60m` 聚合生成。

M11 代码、契约、测试和文档已收口；M11F 历史文件直写与 runless event 补录已按审批执行完成，不属于 Dagster backfill；M11H/M11H-2 已补齐 qfq daily/repair sensor readiness 性能路径和 cursor 快路径兼容。

## 1.1 已拍板口径

1. `90/120` 并入同一个 `dataset_id=stk_mins_qfq`，不拆新的 `stk_mins_qfq_derived` dataset id。
2. `stock_mins_qfq_daily_update_job` 和 `stock_mins_qfq_daily_sensor` 扩展为七频度 qfq：`1/5/15/30/60/90/120`。
3. `stock_mins_qfq_factor_repair_job` 在 repair 30/60 后必须同步重建受影响的 90/120，避免派生频度滞后。
4. M11 已完成 90/120 资产、契约和测试；M11F 已新增并执行 derived 专用历史直写补录与 runless event helper/CLI。M11G 后，年度 event 补录批次按 `dry-run -> report -> quick audit` 推进，全部年份完成后已执行一次 `full audit` 收口。M11H/M11H-2 已完成 qfq daily/repair sensor readiness 性能修复和 cursor submitted 判定兼容。
5. 90/120 使用 derived 专属 check name，不复用 native qfq 的 silver/adj_factor 对账 check name。

## 2. 依据与旧湖口径

旧湖实现位于：

- `lake_console/backend/app/services/stk_mins_derived_service.py`
- `tests/lake_console/test_stk_mins_derived_service.py`
- `docs/datasets/stk-mins-parquet-lake-plan-v1.md`
- `docs/datasets/stk-mins-macd-v2-recompute-and-incremental-plan.md`

旧湖事实：

1. `DERIVED_FREQ_MAP = {90: (30, 3), 120: (60, 2)}`。
2. `90/120` 是 derived，不写入 `raw_tushare/stk_mins_by_date`。
3. 旧湖 `90/120` 输入是 clean 30/60；新湖 qfq 版本对应输入应是 gold qfq 30/60。
4. 旧湖 `90m` 特殊跳过 `09:30` 的 30m bar，然后按有效日内 bar 分组。
5. 旧湖 `120m` 按 60m bar 两两成组，不输出不完整尾组。

## 3. 非目标

本方案不做以下事情：

1. 不新增 raw/silver 90m、120m asset。
2. 不把 `STK_MINS_FREQS` 从 `(1, 5, 15, 30, 60)` 直接扩成七频度并污染 raw/silver/Tushare/prod DB 路径。
3. 不读取 Tushare `stk_mins` 或 `pro_bar` 生成 90/120。
4. 不新增 summary asset、readiness asset、数据库表或 run tags。
5. 不改变 qfq 物理布局：继续使用 `freq/ts_code/year/part-000.parquet`。
6. 不改变现有五频度 qfq 公式、repair check event 语义和 writer pool 互斥口径。
7. 不在本阶段启用 sensor 或执行正式历史直写补录。

## 4. 资产与源数据选择

### 4.1 资产定义

新增两个 partitioned gold assets：

| asset | source asset | source freq | target freq | partition |
| --- | --- | ---: | ---: | --- |
| `gold_stk_mins_qfq_90m` | `gold_stk_mins_qfq_30m` | 30 | 90 | `cn_a_stock_mins_silver_trade_days` |
| `gold_stk_mins_qfq_120m` | `gold_stk_mins_qfq_60m` | 60 | 120 | `cn_a_stock_mins_silver_trade_days` |

资产 metadata：

- `dataset_id=stk_mins_qfq`，90/120 通过 metadata 标记 `calculation_model=derived_from_qfq_source`。
- `source_system=DERIVED`。
- `data_contract=qfq_stock_minute_bars_derived_from_qfq_source`。
- `column_schema` 使用 gold qfq schema，但字段说明必须扩展为允许 `1/5/15/30/60/90/120`，并说明 raw/silver 仍只允许五频度。
- `path_template` 使用 `gold_stk_mins_qfq_path(..., 90|120, {ts_code}, {year})`。
- `pool=GOLD_STK_MINS_QFQ_WRITER_POOL`，与五频度 qfq 和 factor repair 共用 writer pool。

### 4.2 为什么从 gold qfq 30/60 派生

同一 `ts_code + trade_date` 的 qfq 因子是日级常量：

```text
qfq_price = silver_price * adj_factor(trade_date) / latest_adj_factor(ts_code)
```

对同一天内的窗口：

- `open/high/low/close` 先 qfq 再聚合，与先聚合再 qfq 等价。
- `vol/amount/exchange` 与 qfq 无关，可从 source qfq bars 继承聚合。

因此 90/120 直接从 `gold_stk_mins_qfq_30m/60m` 聚合，避免重复读取 silver 和 adj_factor，也自然继承 factor repair 后的 qfq 结果。

## 5. 频度契约拆分

当前 `STK_MINS_FREQS = (1, 5, 15, 30, 60)` 同时服务 raw、silver、gold qfq 五频度。M11 不能直接扩展它。

拆成三组契约：

```python
STK_MINS_SOURCE_FREQS = (1, 5, 15, 30, 60)
STK_MINS_QFQ_NATIVE_FREQS = STK_MINS_SOURCE_FREQS
STK_MINS_QFQ_DERIVED_FREQS = (90, 120)
STK_MINS_QFQ_FREQS = STK_MINS_QFQ_NATIVE_FREQS + STK_MINS_QFQ_DERIVED_FREQS
```

保留或迁移口径：

- raw/silver/bootstrap migration/prod DB/Tushare/readiness probe 继续使用 `STK_MINS_SOURCE_FREQS`。
- 五频度 qfq daily、history、repair detection 可继续使用 native freq 集合。
- qfq asset registry、qfq checks、qfq daily job selection 可使用 `STK_MINS_QFQ_FREQS` 或显式资产 tuple。
- 路径函数 `gold_stk_mins_qfq_path` 应改为 qfq 专用 normalize，不再调用只允许五频度的 `normalize_stk_mins_freq`。

静态门禁必须证明：

1. `raw_stk_mins_*` 和 `silver_stk_mins_*` 仍只有五个。
2. Tushare/prod DB raw path 不接受 90/120。
3. 只有 gold qfq derived 路径接受 90/120。

## 6. 聚合口径

### 6.1 90m

输入：`gold_stk_mins_qfq_30m`

source 日内有效 bar：

```text
10:00, 10:30, 11:00, 11:30, 13:30, 14:00, 14:30, 15:00
```

其中 `09:30` 必须跳过。

输出窗口：

| target trade_time | source rows |
| --- | --- |
| `11:00` | `10:00,10:30,11:00` |
| `14:00` | `11:30,13:30,14:00` |
| `15:00` | `14:30,15:00` |

旧湖允许 90m 最后一个不完整窗口输出；新湖照此口径。

### 6.2 120m

输入：`gold_stk_mins_qfq_60m`

source 日内 bar：

```text
09:30, 10:30, 11:30, 14:00, 15:00
```

输出窗口：

| target trade_time | source rows |
| --- | --- |
| `10:30` | `09:30,10:30` |
| `14:00` | `11:30,14:00` |

`15:00` 单根尾组不输出。

### 6.3 OHLCV 聚合

每个 `ts_code + trade_date + window`：

- `open` = source window 第一根 open
- `close` = source window 最后一根 close
- `high` = source window high 最大值
- `low` = source window low 最小值
- `vol` = source window vol 求和
- `amount` = source window amount 求和
- `exchange` = source window 内唯一 exchange；不唯一则失败
- `freq` = target freq
- `trade_time` = source window 最后一根 trade_time

## 7. DuckDB 实现方案

新增 helper，例如：

- `build_gold_stk_mins_qfq_derived_select_sql(source_paths, source_freq, target_freq)`
- `write_gold_stk_mins_qfq_derived_asset_partition(lake_root, duckdb, target_freq, partition_key)`

执行模型：

1. 读取 source gold qfq stock-year files 中目标 `partition_key` 的 rows。
2. 在 DuckDB 中按 target freq 构造 window id。
3. 用窗口函数生成 first/last/open/close 和聚合 high/low/vol/amount。
4. 生成符合 `GOLD_STK_MINS_QFQ_SCHEMA` 的 replacement rows。
5. 复用 `write_gold_stk_mins_qfq_rows_to_year_files(...)` 写回 `freq=90|120/ts_code/year`。
6. 写入仍使用 `.tmp + os.replace` 原子替换，并受 `gold_stk_mins_qfq_writer` pool 保护。

禁止：

- Python 明细 row loop 聚合正式数据。
- Python 写 Parquet 明细。
- 为每只股票单独构造 DuckDB 查询。
- 在 job 文件中写 DuckDB SQL、路径拼接或业务逻辑。

## 8. Check 设计

90/120 不能原样复用 native qfq 的 8 个 check，因为 native qfq check 中有两项直接依赖同频度 silver：

- `gold_stk_mins_qfq_row_count_matches_silver`
- `gold_stk_mins_qfq_formula_matches_silver_adj_factor`

说人话：90/120 不是源头数据，要检查“它是不是从 30/60 qfq 正确聚合出来的”，而不是检查“它是不是直接按 silver + adj_factor 算出来的”。

M11 check 拆分为两类：

### 8.1 共用基础 checks

90/120 复用现有基础 check name，并通过 shared helper 参数化到 90/120：

1. file exists and row count positive
2. schema matches contract
3. freq/date/path match
4. unique `ts_code + trade_time`
5. price sanity

### 8.2 derived 专属 checks

新增 derived 专属 check name：

1. `gold_stk_mins_qfq_derived_source_ready`
   - source qfq asset 目标 partition 已 materialized。
   - source qfq blocking checks 全绿。
2. `gold_stk_mins_qfq_derived_row_count_matches_source_windows`
   - 90m 每个 source stock-day 正常期望 3 rows。
   - 120m 每个 source stock-day 正常期望 2 rows。
   - 若 source 缺 bar 或 suspended 结构导致可生成窗口减少，metadata 必须记录 missing/incomplete window 样本。
3. `gold_stk_mins_qfq_derived_formula_matches_source`
   - 用 source qfq rows 重算 target rows，与 target parquet 对比。
   - 对比 key：`ts_code + trade_time`。
   - 价格容差沿用 `GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE`。

### 8.3 check event 与 blocking

- 90/120 checks 仍为 blocking。
- check metadata 统一走治理 helper。
- derived check names 稳定使用 8.2 中三个名字。
- daily job selection 必须包含 derived 专属 checks。
- native qfq 的 `row_count_matches_silver` / `formula_matches_silver_adj_factor` 不挂到 90/120。

## 9. Daily job 与 sensor

### 9.1 daily job

`stock_mins_qfq_daily_update_job` 扩展为七个 qfq assets + checks。

边界不变：

- 不包含 raw/silver/source assets。
- 不包含 repair op。
- 不加 run tags/run config。
- 继续 `in_process_executor`。

执行依赖：

1. 30/60 native qfq 必须先于 90/120。
2. 通过 asset deps 表达 `90m -> 30m`、`120m -> 60m`。
3. 同一 run 内由于 in-process executor 和 deps，写入顺序应稳定。
4. 跨 run 互斥仍依赖 `gold_stk_mins_qfq_writer` pool。

### 9.2 daily sensor

`stock_mins_qfq_daily_sensor` 需要从“五频度 gold ready”升级为“七频度目标状态判断”，但门禁要分层：

1. 上游门禁仍只看目标日 silver 五频度 ready、adj factor ready。
2. 若七频度全 ready，skip。
3. 若 native 五频度未 ready，提交 daily job。
4. 若 native 五频度 ready 但 90/120 缺失，也提交同一个 daily job。
5. 若任一 gold asset 已 materialized 但 blocking checks 未全绿，skip 并要求人工修复。

第一版提交同一个 `stock_mins_qfq_daily_update_job`，让 selection 通过 asset deps 处理顺序，避免新增 derived-only sensor/job。

### 9.3 daily / repair sensor readiness 超时修复（M11H / M11H-2 已落地）

#### 9.3.1 问题定位

修复前，`stock_mins_qfq_daily_sensor` 和 `stock_mins_qfq_factor_repair_sensor` 都在 tick 内调用通用 readiness helper。该通用 helper 的单资产语义是：

1. 获取目标 asset partition 的 latest materialization。
2. 对该 asset 的每个 blocking check 调用一次 `get_asset_check_execution_history(limit=5000)`。
3. 在 check history 中寻找绑定该 latest materialization `storage_id` 的 check result。

这在单资产或少量 check 场景可接受，但 qfq daily / repair 的 fan-out 已经变成明显超时风险：

| sensor | asset count | blocking check count | 当前 check history 扫描量 |
| --- | ---: | ---: | ---: |
| `stock_mins_qfq_daily_sensor` | silver 5 + adj factor 2 + qfq gold 7 | silver 50 + adj factor 18 + qfq gold 56 | 约 108 次 |
| `stock_mins_qfq_factor_repair_sensor` | qfq gold 7 | qfq gold 56 | 约 56 次 |

已观测到两个 sensor tick 出现 60 秒超时。该问题不是 qfq 文件或 job 本身失败，而是 sensor readiness 查询路径过重。

#### 9.3.2 修复边界

- 保留 `asset_readiness_status(...)` 的单分区语义，不把通用 helper 改成历史或批量工具。
- 已新增仅服务 `stock_mins_qfq_daily_sensor` 与 `stock_mins_qfq_factor_repair_sensor` 的专用单分区批量 readiness helper。
- 不新增独立 repair sensor、readiness asset、summary asset、数据库表、配置项或状态实体。
- 不改 `stock_mins_qfq_daily_update_job`、`stock_mins_qfq_factor_repair_job` 的 selection、executor、pool、tags、run key、run config、asset/check definitions 或 partition definitions。
- 不用 DuckDB 加速 Dagster event log readiness；DuckDB 仍只用于 qfq 文件计算、repair 计算和 asset/check 内聚合校验。
- 不运行正式 Dagster job/sensor/backfill/materialization/check；如后续要做正式 instance 只读 dry-run，必须单独列命令、`DAGSTER_HOME`、读写范围、影响和回滚方式再审批。

#### 9.3.3 专用 helper 算法

M11H 实际落地 helper 为 `partition_dataset_readiness_status_from_latest_checks(...)`。原方案曾考虑按 `run_id` 读取 run event log，但 runless materialization/check event 的 `run_id` 为空字符串，不能依赖 `all_logs(run_id)` 做分组读取。因此固定算法修正为：

1. 输入为一个目标 `trade_date` 和一组明确的 readiness specs，调用方限定为 qfq daily / repair sensor。
2. 对每个 asset key 获取目标 partition 的 latest materialization。
3. materialization 缺失时返回 not ready，并标明该 asset 缺 materialization。
4. 对所有已 materialized asset 的 blocking check 组装 `AssetCheckKey(asset_key, check_name)` 集合。
5. 对这一组 check keys 调用一次 `event_log_storage.get_latest_asset_check_execution_by_key(..., partition_filter=PartitionKeyFilter(key=trade_date))`。
6. 对每个 blocking check 精确匹配 latest materialization 的 `target_materialization_data.storage_id`；旧 materialization 的 passed check 不能让新 materialization ready。
7. 只接受 terminal check evaluation；missing、failed、非 terminal、只存在 non-blocking passed event、target mismatch 都 fail closed。
8. 返回结构仍是现有 `DatasetReadinessStatus` / `AssetReadinessStatus`，cursor payload 结构不变。
9. `get_asset_check_execution_history(...)` 调用数必须为 `0`。

#### 9.3.4 sensor 行为

`stock_mins_qfq_daily_sensor`：

1. 23:00 前直接 skip，不调用 readiness。
2. 若 cursor 显示同一 `target_trade_date` 已提交过 qfq daily run，直接 skip，不再做 deep readiness；run_key 仍保持 `stock_mins_qfq_daily_update:{trade_date}`。
   - M11H-2 兼容新旧 cursor：新 cursor 认 `details.selected_trade_date == target_trade_date` 且 `details.already_submitted_for_trade_date == true`；旧 cursor 认 `target_date == target_trade_date`、`decision == request_runs`，并且 `selected_count > 0` 或 `sample_keys` 包含该日期。
   - `decision=skip`、`selected_count=0` 且无 sample、坏 JSON、schema 不匹配或不同目标日期都不触发快路径。
3. 先用专用批量 helper 判断 silver 五频度 ready。
4. 再判断 adj factor ready。
5. 上游任一不 ready 时 skip，不提交 qfq run。
6. 再判断七频度 qfq gold：
   - 七频度全 ready：skip。
   - 存在 missing materialization 且没有已 materialized 的 failed/missing blocking check：提交 `stock_mins_qfq_daily_update_job[trade_date]`。
   - 已 materialized 但 blocking checks 未全绿：skip，不自动重跑，要求人工修复。

`stock_mins_qfq_factor_repair_sensor`：

1. 23:15 前直接 skip，不调用 readiness。
2. 若 cursor 显示同一 `target_trade_date` 已提交过 repair run，直接 skip，不再做 deep readiness；run_key 仍保持 `stock_mins_qfq_factor_repair:{trade_date}`。
   - M11H-2 使用与 daily sensor 相同的新旧 cursor 兼容判定。
   - 快路径只以 sensor cursor 的 submitted 事实为准，不读取正式 Dagster instance 或 run history；若实际 run 失败，仍按人工 retry 或清 cursor 处理。
3. 只用同一个 qfq gold 批量 helper 判断七频度 gold ready。
4. 七频度全 ready 时提交 `stock_mins_qfq_factor_repair_job`，run config 仍只包含 typed `trade_date`。
5. gold missing、failed check 或 missing latest check result 时 skip，不自动触发 daily qfq，也不自动修复 gold。

#### 9.3.5 性能预算

| 场景 | 当前成本 | 目标成本 | 验证门槛 |
| --- | --- | --- | --- |
| qfq daily 首次决策 tick | 约 14 次 materialization 查询 + 108 次 check history 扫描 | 上游按顺序短路：silver 最多 1 次 latest-check batch，adj factor 最多 1 次 latest-check batch，qfq gold 最多 1 次 latest-check batch；0 次 check history 扫描 | fake instance 单测证明 check history 调用数为 0；经审批的正式只读 dry-run 小于 5 秒，超过 10 秒拒绝上线 |
| factor repair 首次决策 tick | 约 7 次 materialization 查询 + 56 次 check history 扫描 | qfq gold 最多 1 次 latest-check batch；0 次 check history 扫描 | fake instance 单测证明 check history 调用数为 0；经审批的正式只读 dry-run 小于 3 秒，超过 5 秒拒绝上线 |
| 同一目标日期已提交 run 后的稳定 tick | 仍可能重复 readiness 深查 | cursor 快路径直接 skip | 本地单测目标小于 1 秒，超过 2 秒拒绝上线 |

本性能预算的硬指标是“check history 扫描次数必须为 0”。如果实现只能把 108/56 次降成较少次数但仍依赖每个 check 的 history scan，则不接受。

#### 9.3.6 测试计划

单元测试必须覆盖：

1. daily sensor 在 23:00 前不调用 readiness。
2. daily sensor 在 silver 未 ready 时 skip，不查不提交 qfq gold。
3. daily sensor 在 adj factor 未 ready 时 skip。
4. daily sensor 在 qfq gold missing materialization 且上游 ready 时提交 daily run。
5. daily sensor 在七频度 qfq gold 全 ready 时 skip。
6. daily sensor 在 gold 已 materialized 但 blocking checks failed/missing 时 skip，不自动重跑。
7. daily sensor cursor 同日期已提交后的快路径不调用 readiness，必须覆盖新 cursor、旧 `request_runs + selected_count > 0` cursor 和旧 `sample_keys` cursor。
8. repair sensor 在 23:15 前不调用 readiness。
9. repair sensor 在 qfq gold missing/not ready 时 skip。
10. repair sensor 在 qfq gold 全 ready 时提交 repair run config。
11. repair sensor cursor 同日期已提交后的快路径不调用 readiness，必须覆盖新 cursor、旧 `request_runs + selected_count > 0` cursor 和旧 `sample_keys` cursor。
12. 专用 helper 忽略旧 materialization 的 passed check。
13. 专用 helper 对 missing latest check result fail closed。
14. 专用 helper 不把 non-blocking 历史 check event 视为通过。
15. 同一 latest materialization 多条 check result 时取最新结果。
16. cursor 负例必须覆盖 `decision=skip`、`selected_count=0` 且无 sample、坏 JSON、schema 不匹配和不同目标日期。
17. 静态回归确认未新增 summary/readiness asset，未扩大 job selection，未修改 sensor tags、run key、run config 和 cursor 主结构。

本地验证命令：

1. `lake_console/orchestrator/.venv/bin/python -m unittest tests.test_qfq_sensor_batch_readiness tests.test_stk_mins_qfq_m9a_sensor_contracts tests.test_stk_mins_qfq_m9c_sensor_contracts tests.test_run_contract_static_gates`
2. `lake_console/orchestrator/.venv/bin/python -m py_compile` 针对触达 Python 文件
3. `ruff check` 针对触达 Python 文件
4. `git diff --check`
5. `python3 scripts/check_docs_integrity.py`

## 10. Factor repair 影响

当前 `stock_mins_qfq_factor_repair_job` 修的是 native 五频度 qfq。新增 90/120 后，必须避免这种错误状态：

```text
30/60 已因复权因子变化 repair，90/120 仍保留旧聚合结果。
```

M11 第一版必须同步扩展 repair：

1. repair helper 完成 native 五频度批量写回后，基于被改写的 30/60 重新生成受影响股票历史 90/120。
2. 仍按 `freq/year` 批量执行，不回到 `stock_code -> freq -> year` 小循环。
3. repair check event 继续挂到所有 qfq assets 的目标 `trade_date` partition。
4. repair metadata 增加：
   - `derived_rewrite_required=true|false`
   - `derived_planned_batch_count`
   - `derived_rewritten_file_count`
   - `derived_rewritten_row_count`
5. repair 结果必须覆盖七个 qfq assets 的 check event；90/120 不能只靠日常 job 后补。

## 11. 历史初始化

历史 90/120 补齐采用 `Direct Lake Bootstrap + Runless Event Backfill`，不是 Dagster backfill。M11F 已实现并执行 derived 专用工具链：先完成历史文件直写，再按 `freq/year` 补 runless materialization/check events。M11G 后，runless event 补录的年度批次复核使用 quick audit，避免每年重复扫描持续变大的 check event history；全部年份完成后已执行一次 full audit 收口。

最终 full audit 结果（2026-06-06）：`selected_partition_count=3019`，`selected_target_freqs=[90,120]`，`planned_source_row_count=159422361`，`planned_target_file_count=105701`，`existing_target_file_count=105701`，`missing_input_count=0`，`materialized_partition_counts={90:3019,120:3019}`，16 个 derived checks 的 `check_success_counts` 均为 `3019`，样本 readiness 全部为 `true`。

注意：后续如需重跑或修正补录，性能评估阶段仍只能只读统计正式 lake 数据，不允许任何写入动作；正式湖写入和 runless event 补录必须再次单独审批。

阶段：

1. dry-run
   - 统计 30/60 source qfq 文件集合。
   - 统计目标 90/120 缺失文件集合。
   - 估算 source rows、target rows、target files、磁盘空间。
2. sample
   - 选择少量 `freq/year/ts_code` 或少量 trade_date 写入临时 lake。
   - 校验 schema、row count、窗口公式、path/freq/date。
3. full/batched file generation
   - 推荐按 `target_freq/year` 或 `target_freq/year/bucket` 批次。
   - DuckDB SQL 生成 replacement rows。
   - 复用 qfq stock-year writer。
4. runless event backfill
   - 只为文件事实和 checks 全绿的 partitions 补 materialization/check events。
   - 每个 `target_freq/year` 批次执行 `report-gold-qfq-derived-events --dry-run`；dry-run 的 `failed_partition_count=0` 后再执行正式 report。
   - 年度批次写完后执行 `audit-gold-qfq-derived-final --mode quick`，只看文件事实、materialized partition counts 和样本 readiness，不扫全量 check event history。
   - 全部年份完成后，已执行一次 `audit-gold-qfq-derived-final --mode full` 做最终 check success counts 收口。

禁止上千分区逐个 Dagster backfill，也禁止逐 partition 深扫 event history 作为主验收。

## 12. 性能门禁

### 12.1 具体评估只读门禁

M11 设计和开发前若需要用正式湖数据做具体规模评估，只允许只读动作：

1. 只能用 DuckDB `SELECT` / `count` / 聚合查询 / `EXPLAIN` 读取 Parquet 文件。
2. 不允许 `COPY TO`、`CREATE TABLE`、`INSERT`、`UPDATE`、`DELETE`、`EXPORT`、`os.replace` 或任何写文件动作。
3. 不允许写临时 lake、样本 parquet、event log、Dagster instance、数据库表或 reports 文件。
4. 不允许运行 `dg`、Dagster job、sensor、backfill、materialization、asset check 或 evaluator。
5. 只读评估输出只能记录在对话或后续设计文档中；若需要生成报告文件，必须单独说明并等待批准。

### 12.2 本轮开发日常路径门禁

| 项 | 口径 |
| --- | --- |
| target freqs | 2：`90/120` |
| source freqs | `30m/60m` qfq |
| raw/prod DB/Tushare request | 0 |
| enum expansion | 只扩 gold qfq freq contract，不扩 raw/silver/source freq |
| daily source rows | 约 `source_stock_day_count * (9 + 5)` |
| daily target rows | 约 `source_stock_day_count * (3 + 2)` |
| daily target files | 最多约 `source_stock_day_count * 2` 个 `freq/ts_code/year` 文件被重写 |
| DuckDB scan | 只扫 source qfq 30/60 的目标日期行；不得扫 raw/silver 全量历史 |
| DuckDB write | `COPY ... TO parquet`，按 stock-year 原子替换 |
| Python 职责 | 参数校验、批次规划、路径发现、结果汇总 |
| 并发保护 | `gold_stk_mins_qfq_writer` pool limit=1 |
| 不可接受阈值 | 出现 per-stock 查询主循环、Python 明细聚合、Python 明细写 Parquet、raw/silver 90/120 频度扩散 |
| 验收 | 单日实现的核心计算批次必须按 target freq 收敛，不能随股票数线性拆成 stock-level SQL |

### 12.3 M11F 历史补录性能门禁

历史 90/120 补录工具链已在 M11F 实现并正式执行完成；后续如需重跑、修正或新增范围，仍必须先通过只读规模评估，并按受控 CLI 的 dry-run / sample / full file generation / event report / quick audit / final full audit 顺序推进。M11G 后不得在每个年度批次后执行 full audit。

| 项 | 口径 |
| --- | --- |
| date count | 只读统计 source 30/60 qfq 已覆盖交易日集合 |
| object count | 只读统计 source `ts_code` 集合、stock-year 文件数、target 缺失文件数 |
| expected source rows | 只读按 `target_freq/year` 聚合估算，不逐股票深扫 |
| expected target rows | 90m 约每 stock-day 3 行；120m 约每 stock-day 2 行，异常窗口单独计数 |
| expected files | `freq=90|120 / ts_code / year` 维度估算 |
| DuckDB scan | 按 `target_freq/year` 或更粗批次聚合读 source qfq 30/60 |
| write granularity | 后续执行阶段才允许写；写入仍按 stock-year 原子替换 |
| retry cost | 失败重跑以 `target_freq/year` 或 approved batch 为单位，不得 date * stock 小循环 |
| disk space | 补录方案必须估算新增 parquet 大小与临时空间 |
| event backfill | 年度批次后只做 quick audit；只用文件事实、materialized partition counts 和样本 readiness，禁止每年重复 full audit 或逐 partition 深扫 event history |
| 拒绝策略 | 只读评估无法给出 date/object/row/file 上界，或实现需要 per-stock 主循环时，停止开发并重设方案 |

## 13. 实施步骤

### M11A 设计与契约

1. 更新本设计文档和 `dagster-stk-mins-asset-design.html`。
2. 拆分 source/native/derived/qfq freq constants。
3. 更新 schema 描述。
4. 增加静态门禁，确保 90/120 只出现在 gold qfq derived 路径。

### M11B DuckDB helper

1. 新增 qfq derived select SQL builder。
2. 新增 daily derived partition writer。
3. 单测覆盖 90/120 窗口、OHLCV、exchange 唯一性、缺 bar。
4. 验证不使用 Python 明细循环。

### M11C Assets 与 checks

1. 新增 `gold_stk_mins_qfq_90m/120m` assets。
2. 增加 deps 到 30/60 qfq。
3. 增加 derived checks。
4. 更新 asset governance / schema / path / pool tests。

### M11D Daily job/sensor

1. 扩展 daily job selection。
2. 扩展 daily sensor readiness payload。
3. 更新 sensor tags/count/static gates。
4. 确认 run key/cursor 不变或明确版本化。
5. M11H 已按 9.3 落地：qfq daily/repair sensor 使用专用单分区批量 readiness 路径，通用 helper 未扩展成历史批量 readiness 工具。

### M11E Repair

1. 扩展 factor repair 批量模型，在 native repair 后重建受影响 90/120。
2. 更新 repair metadata 与 tests。
3. 确认 check events 覆盖七个 qfq assets。

### M11F History bootstrap

1. 已新增 derived 专用历史生成 helper/CLI：`plan-gold-qfq-derived-history` 与 `generate-gold-qfq-derived-history`。
2. 已新增 derived 专用 runless event helper/CLI：`plan-gold-qfq-derived-events`、`report-gold-qfq-derived-events`、`audit-gold-qfq-derived-final`。
3. helper 只允许 `90/120`，按 `target_freq/year` 批次规划，默认拒绝已有目标 stock-year 文件；不注册 asset/job/sensor/check，不新增 summary entity。
4. M11G 已给 `audit-gold-qfq-derived-final` 增加 `--mode full|quick`：默认 `full` 保持全量 check success count；`quick` 跳过 check event history 扫描，输出 `check_success_counts={}` 与 `check_success_counts_skipped=True`。
5. `report-gold-qfq-derived-events` 的 dry-run 和正式 report 路径不再计算 `check_success_counts`；年度补录后只能用 quick audit 轻量复核，全部年份结束后再跑一次 full audit。
6. 正式执行已完成：full audit 读取 source rows `159422361`，历史直写目标文件 `105701/105701`，90/120 各 `3019` 个 materialized partitions，16 个 derived checks 均为 `3019` 绿；full audit 样本 readiness 覆盖 `2014-01-02`、`2020-03-13`、`2026-06-05`，全部为 `true`。

## 14. Test Plan

单元测试：

1. 90m 从 30m 生成 `11:00/14:00/15:00`。
2. 90m 跳过 `09:30`。
3. 90m 最后两个 30m bar 可以生成 `15:00`。
4. 120m 从 60m 生成 `10:30/14:00`。
5. 120m 不输出 `15:00` 单根尾组。
6. OHLCV 聚合正确。
7. exchange 不一致失败。
8. target rows freq/date/path/schema 正确。
9. raw/silver normalize 不接受 90/120。
10. qfq path normalize 接受 90/120。

契约/静态测试：

1. `stock_mins_qfq_daily_update_job` selection 覆盖七个 qfq assets + checks，不包含 raw/silver/source/repair。
2. `stock_mins_qfq_factor_repair_job` 仍只调用 repair op，job 文件无业务 SQL。
3. 90/120 assets 使用 `GOLD_STK_MINS_QFQ_WRITER_POOL`。
4. 不新增 summary asset/path/schema/catalog。
5. 不在 prod DB/Tushare request builder 中出现 90/120。

验证命令：

1. `python3 -m py_compile` 编译触达文件。
2. 运行 qfq M7/M8/M9/M11 相关 unittest。
3. 运行 static gates、asset governance、sensor classification。
4. `.venv/bin/ruff check` 触达 Python 文件。
5. `git diff --check`。
6. `python3 scripts/check_docs_integrity.py`。

明确不执行：

1. 不运行 `dg`、Dagster job/sensor/backfill/materialization/check。
2. 不读取正式 Dagster instance。
3. 不写 `/Volumes/datasource/data_lake`。

## 15. 已拍板口径

本节问题已完成拍板，执行口径如下：

1. `dataset_id` 共用 `stk_mins_qfq`，用 metadata 标明 `calculation_model=derived_from_qfq_source`。
2. daily job/sensor 一次性扩展为七频度，不新增 derived-only daily sensor。
3. factor repair 必须同步重建受影响的 90/120。
4. M11F 已实现并执行历史 90/120 直写补录工具链；正式补录不是随代码提交自动发生，而是按单独审批的 `Direct Lake Bootstrap + Runless Event Backfill` 流程完成。
5. 90/120 新增 derived 专属 check name：`gold_stk_mins_qfq_derived_source_ready`、`gold_stk_mins_qfq_derived_row_count_matches_source_windows`、`gold_stk_mins_qfq_derived_formula_matches_source`。

## 16. 初步结论

M11 应作为 gold qfq 资产族的派生频度扩展，而不是 stk_mins 源频度扩展。

最稳妥路径是：

```text
30/60 native gold qfq ready
-> DuckDB 聚合生成 90/120 gold qfq
-> 写入同一 qfq 物理布局
-> derived 专属 blocking checks
-> daily job/sensor 覆盖七频度
-> factor repair 同步重建派生频度
```

这样可以保持 raw/silver/Tushare/prod DB 边界稳定，同时让研究和指标侧最终拥有 `1/5/15/30/60/90/120` 的统一 qfq 输入。
