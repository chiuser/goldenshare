# Dagster Batch Readiness Hot Path 性能治理专项方案

更新时间：2026-06-21

状态：P0 已完成。P0A、P0B、P0C、P0D、P0E、P0F、P0G 均已完成并提交。本文档记录问题定义、代码审计、治理方案和阶段验收口径；本专项所有正式验证均禁止运行 `dg`，禁止写 Dagster runtime，禁止写正式 lake。

对应 LLD：[Dagster Batch Readiness Hot Path 性能治理 LLD](dagster-batch-readiness-hotpath-governance-low-level-design.md)

## 0. 当前阶段状态

| 阶段 | 状态 | 当前事实 |
| --- | --- | --- |
| P0A | 已完成 | qfq daily / qfq factor repair sensor 已在运行窗口前轻量 skip，窗口前不再进入重 DuckDB readiness。提交：`b1dcc7b3`。 |
| P0B | 已完成 | 已做 qfq gold readiness 只读 profiling，旧实现 10 天窗口耗时约 `176.8s`，确认根因是 qfq gold readiness 日期乘频度重复重扫。 |
| P0C | 已完成 | `batch_gold_stk_mins_qfq_lake_readiness(...)` 已改为窗口级 true batch；正式 lake 只读 profiling 降至约 `13.6s`。提交：`78d66458`。 |
| P0D | 已完成 | qfq daily sensor 已分层短路：silver 阻断时不加载 adj/gold，adj 阻断时不加载 gold。提交：`7c7eb0e6`。 |
| P0E | 已完成 | 全部 sensor hot path batch helper 的门禁测试与性能回归已落地；其它 helper 的性能测试固定在本阶段并已执行。提交：`b70c51c0`。 |
| P0F | 已完成 | 本地目标回归、静态检查和性能结果落档已完成。本轮文档提交记录最终结果。 |
| P0G | 已完成 | 长期编码规范和关联性能文档状态已同步；P0 收口完成。 |

其它 helper 的性能测试不放在 P0B。P0B 只服务 qfq gold 根因定位；P0E 才是全 helper 性能回归和防回流门禁阶段。

### 0.1 P0E / P0F 验收结果

P0E 已新增 `tests/test_batch_readiness_hotpath_performance.py`，并扩展 `tests/test_stk_mins_continuity_performance.py` 与 `tests/test_run_contract_static_gates.py`。本阶段没有修改生产运行逻辑，目标是证明所有 sensor hot path batch helper 没有同等级超时风险，并用静态门禁阻止 qfq gold 回流为日期乘频度重扫。

本地临时性能样本结果如下，全部使用临时目录、临时 Parquet、in-memory DuckDB 或 fake client，不读取正式 lake，不读取或写入正式 Dagster runtime：

| Helper | 窗口 / 范围 | 本地样本耗时 | 结论 |
| --- | --- | ---: | --- |
| `batch_raw_stk_mins_lake_readiness` | 10 个交易日 × 5 频度 | `27.43 ms` | 通过，未发现同类高危重扫。 |
| `batch_silver_stk_mins_lake_readiness` | 10 个交易日 × 5 频度 | `47.74 ms` | 通过，覆盖 lifecycle 等完整语义路径。 |
| `batch_gold_stk_mins_qfq_lake_readiness` | 10 个交易日 × 7 频度 | `119.37 ms` | 通过，已是窗口级 batch，不再由 batch body 调用单日 qfq helper。 |
| `batch_raw_adj_factor_lake_readiness` | 10 个交易日，raw/silver 样本文件 | `19 ms` | 通过。 |
| `batch_silver_adj_factor_lake_readiness` | 10 个交易日，raw/silver 样本文件 | `16 ms` | 通过。 |
| `batch_adj_factor_lake_readiness` | 10 个交易日，combined 状态 | `17 ms` | 通过。 |
| `batch_market_major_indices_lake_readiness` | 10 个交易日 | `9 ms` | 通过。 |
| `batch_gold_market_breadth_lake_readiness` | 10 个交易日 | `15 ms` | 通过。 |
| `batch_gold_stock_return_distribution_lake_readiness` | 10 个交易日 | `20 ms` | 通过。 |
| `batch_clickhouse_market_breadth_readiness` | 10 个交易日，fake client | `6 ms`，`execute_count=1` | 通过，partition set 级别读取。 |
| `batch_prod_clickhouse_market_breadth_readiness` | 10 个交易日，fake local/prod client | `0 ms`，local/prod 各 `1` 次 | 通过，未回退逐日查询。 |

P0F 本地目标回归命令已执行：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_stk_mins_lake_readiness.py \
  tests/test_stk_mins_continuity_performance.py \
  tests/test_batch_readiness_hotpath_performance.py \
  tests/test_stock_mins_daily_continuity_sensors.py \
  tests/test_stk_mins_qfq_m9a_sensor_contracts.py \
  tests/test_stk_mins_qfq_m9c_sensor_contracts.py \
  tests/test_run_contract_static_gates.py
```

结果：`119 passed, 5 warnings in 5.12s`。warnings 来自 Dagster / Pydantic 依赖，不影响本专项验收。

补充静态检查结论：

1. `git diff --check` 通过。
2. `_gold_qfq_status_for_trade_date`、`_gold_qfq_native_counts_for_trade_date`、`_gold_qfq_derived_counts_for_trade_date` 只保留为旧单日 helper 定义和旧单日 helper 内部调用；`batch_gold_stk_mins_qfq_lake_readiness(...)` body 不调用这些单日 helper，该口径由静态门禁测试守住。

P0G 文档收口结果：

1. `lake_console/orchestrator/CODING_STANDARDS.md` 已新增 Sensor Hot Path Batch Readiness 长期规范。
2. `dagster-stk-mins-qfq-sensor-hotpath-performance-fix-plan.md` 已标记 S1/S2/S3 已由本专项及连续性性能优化完成。
3. `dagster-stk-mins-continuity-performance-optimization-plan.html` 与 LLD 已补充本专项 P0 完成事实和性能门禁结果。
4. 本专项主方案与 LLD 状态均更新为 P0 已完成。

## 1. 背景

2026-06-21 19:48 左右，后台出现：

```text
Sensor daemon caught an error for sensor stock_mins_qfq_factor_repair_sensor
DagsterUserCodeUnreachableError: The sensor tick timed out due to taking longer than 60 seconds to execute the sensor function.
```

直接现象是 sensor tick 超过 Dagster user-code gRPC 60 秒超时。初步止血点是：`stock_mins_qfq_factor_repair_sensor` 在 20:05 运行窗口前仍会执行重型 readiness 查询，窗口判断位置过晚。

但这不是根因。根因是 `batch_gold_stk_mins_qfq_lake_readiness(...)` 名称叫 batch，实际实现仍然包含按日期、按频度重复执行重 SQL 的模型。窗口前 early skip 只能避免未到时间窗口时白跑；一旦到了 20:05，如果这个 readiness 本身超过 60 秒，sensor 仍会 timeout。

因此本专项目标不是只修窗口判断，而是治理所有 sensor hot path 中“名为 batch，实为逐日重扫”的实现。

## 2. 本轮代码审计范围

本轮只读审计覆盖以下当前代码：

| 类型 | 文件 / 符号 | 审计结论 |
| --- | --- | --- |
| 股票分钟线 readiness | `asset_guards/stk_mins_lake_readiness.py` | `batch_raw_stk_mins_lake_readiness`、`batch_silver_stk_mins_lake_readiness`、`batch_gold_stk_mins_qfq_lake_readiness`。其中 qfq gold 高危。 |
| 复权因子 readiness | `asset_guards/adj_factor_lake_readiness.py` | `_batch_readiness` 与 raw/silver/combined wrapper。当前是批量 path planning + 汇总 metrics，暂未发现 qfq gold 同类重扫。 |
| 主要指数 readiness | `asset_guards/market_major_indices_lake_readiness.py` | 小对象日频文件，按窗口集中 metric rows，风险低。 |
| 市场宽度 readiness | `asset_guards/market_breadth_lake_readiness.py` | lake 侧部分有 `_batch_from_status_factory` per-date wrapper，但对象小；ClickHouse 侧是按 partition set 一次 fetch，风险低。 |
| qfq bootstrap event audit | `bootstrap/stk_mins_qfq_bootstrap_events.py`、`bootstrap/stk_mins_qfq_derived_bootstrap_events.py` | 离线 bootstrap 路径按 freq/year batch 后 fan out，比当前 qfq sensor hot path 更接近真正 batch，可作为重构参考。 |
| qfq repair write batches | `stk_mins_qfq_factor_repair.py` | 写入批次按 stock/year 组织，属于 job/op 写入路径，不是 sensor hot path。本专项仅做命名与性能审计，不纳入 P0 热修。 |
| history bootstrap batches | `bootstrap/stk_mins_qfq_history.py`、`bootstrap/stk_mins_qfq_derived_history.py`、`bootstrap/stk_mins_qfq_macd_kdj_history.py` | 离线历史生成批次，不在日常 sensor 60 秒预算内；不纳入 P0 热修。 |

## 3. Batch 名称准入标准

以后在 sensor hot path 中，函数名使用 `batch_*_readiness` 必须满足下面的标准。

### 3.1 允许称为 batch 的实现

1. 一次性接收完整窗口日期集合，例如最近 10 个 expected trade dates。
2. 一次性完成路径规划，不在业务判断中反复发现同一类路径。
3. 对大体量 Parquet 读取，必须尽量按文件集合或日期集合集中执行 SQL，并通过 `GROUP BY trade_date`、`GROUP BY trade_date, freq` 等方式回填单日 status。
4. 允许在已经聚合出的结果上做 Python fan-out，把结果映射成 `status_for_trade_date(...)`。
5. 允许对小对象、小文件、低频资产做有限 per-date path existence 或 schema check，但必须有上界和性能预算。
6. cursor 只能记录小型 batch summary，例如 `expected_count`、`scanned_file_count`、`elapsed_ms`，不得塞逐文件明细。

### 3.2 不允许称为 batch 的实现

以下模型在 sensor hot path 中不允许继续叫 batch，也不允许进入正式链路：

```text
for trade_date in expected_dates:
  for freq in freqs:
    build SQL
    scan large parquet files
    compute full formula / coverage diagnostics
```

尤其禁止：

1. 按日期重复扫描同一年 stock-year 文件。
2. 按日期重复构造 derived qfq diagnostics / formula SQL。
3. 在 10 天窗口内执行 `日期数 * 频度数 * 多条重 SQL`。
4. 先完整扫描所有日期，再决定其实只需要最早缺口日期。
5. 用“文件存在 + row count”冒充完整 blocking check 语义。

## 4. 当前高危问题

### 4.1 `batch_gold_stk_mins_qfq_lake_readiness(...)` 名不副实

当前实现：

```text
batch_gold_stk_mins_qfq_lake_readiness
  -> for trade_date in expected_trade_dates
       -> _gold_qfq_status_for_trade_date
            -> for native freq in 1/5/15/30/60
                 -> _gold_qfq_native_counts_for_trade_date
            -> for derived freq in 90/120
                 -> _gold_qfq_derived_counts_for_trade_date
```

其中 derived 90/120 会反复：

1. 发现 source freq 的 stock-year qfq paths。
2. 构造 `build_gold_stk_mins_qfq_derived_select_sql(...)`。
3. 执行 `build_gold_stk_mins_qfq_derived_diagnostics_sql(...)`。
4. 计算 expected target paths。
5. 读取 target gold files。
6. 执行 derived formula comparison。

这会把本应窗口级批量完成的工作，拆成 `日期 * 频度` 的重复重查询。

### 4.2 直接影响的 sensor

| Sensor | 当前调用 | 影响 |
| --- | --- | --- |
| `stock_mins_qfq_daily_sensor` | 同一 tick 内依次调用 silver batch、adj factor batch、gold qfq batch | 到 19:50 后可能被 gold qfq readiness 拖到 60 秒以上。 |
| `stock_mins_qfq_factor_repair_sensor` | 调用 gold qfq batch 后再决定是否读 factor repair status | 到 20:05 后仍可能 timeout；窗口前也会白跑重查询。 |

### 4.3 为什么 10 天窗口不是根治

10 天窗口降低了数据量，但 qfq gold 的 derived 90/120 是 stock-year 文件组织，不是简单的 `trade_date` 小分区文件。即使只看 10 天，只要每个日期都重复扫描同一批 year files，仍然可能超过 sensor 60 秒预算。

所以真正修复必须改变读取模型，而不是继续缩短窗口或只前置窗口判断。

## 5. 其它 batch 操作审计结论

| 符号 | 所在路径 | 当前模型 | 风险级别 | 本专项处理 |
| --- | --- | --- | --- | --- |
| `batch_raw_stk_mins_lake_readiness` | `asset_guards/stk_mins_lake_readiness.py` | 路径集合规划、row count / metrics 批量 SQL、按日期 fan-out；schema 仍按文件检查。 | 中 | 暂不重写；纳入性能回归和命名准入门禁。 |
| `batch_silver_stk_mins_lake_readiness` | 同上 | 路径集合规划、核心 metrics 批量 SQL、stock daily / suspend / lifecycle 批量 SQL、按日期 fan-out；schema 仍按文件检查。 | 中 | 暂不重写；纳入性能回归。 |
| `batch_gold_stk_mins_qfq_lake_readiness` | 同上 | 按日期、按频度重复跑 native/derived 重 SQL。 | 高 | P0 必须重写。 |
| `batch_raw_adj_factor_lake_readiness` | `asset_guards/adj_factor_lake_readiness.py` | 共用 `_batch_readiness`，先规划窗口 path，再汇总 metrics。 | 中低 | 暂不重写；后续性能回归防回退。 |
| `batch_silver_adj_factor_lake_readiness` | 同上 | 同上。 | 中低 | 暂不重写。 |
| `batch_adj_factor_lake_readiness` | 同上 | raw + silver combined status，复用同一次 metrics。 | 中低 | 暂不重写。 |
| `batch_market_major_indices_lake_readiness` | `asset_guards/market_major_indices_lake_readiness.py` | 小对象日频文件，集中 metric rows；有有限 per-date schema。 | 低 | 暂不重写。 |
| `batch_gold_market_breadth_lake_readiness` | `asset_guards/market_breadth_lake_readiness.py` | `_batch_from_status_factory` 包装 per-date status，单文件小对象。 | 中低 | 暂不重写，但标记为“batch wrapper”，后续若对象扩大必须重构。 |
| `batch_gold_stock_return_distribution_lake_readiness` | 同上 | 同上。 | 中低 | 暂不重写。 |
| `batch_clickhouse_market_breadth_readiness` | 同上 | ClickHouse 按 partition set 一次 fetch，再内存逐日期判断。 | 低 | 合格。 |
| `batch_prod_clickhouse_market_breadth_readiness` | 同上 | local/prod ClickHouse 分别按 partition set 一次 fetch。 | 低 | 合格。 |
| qfq bootstrap event batch helpers | `bootstrap/stk_mins_qfq*_bootstrap_events.py` | 按 freq/year batch audit，一次 SQL 后按日期 fan-out。 | 低 | 离线路径；可作为 qfq gold sensor 重构参考。 |
| qfq history / derived history / MACD-KDJ history batches | `bootstrap/stk_mins_qfq*_history.py` | 离线生成批次，不在 sensor hot path。 | 低 | 不纳入 P0。 |
| qfq factor repair write batches | `stk_mins_qfq_factor_repair.py` | job/op 写入批次，按 stock/year 或 derived freq 组织。 | 低 | 不纳入 P0。 |

审计结论：目前发现的严重“名为 batch，实际是重型逐日重复扫描”的核心问题集中在 `batch_gold_stk_mins_qfq_lake_readiness(...)`。其它 batch 操作要进入门禁和性能回归，但不需要和 qfq gold 一起重写。

## 6. P0 修复方案

### P0A：窗口前轻量 skip

目标：避免未到窗口时进入重 readiness。

改造对象：

1. `stock_mins_qfq_daily_sensor`
2. `stock_mins_qfq_factor_repair_sensor`

正式顺序：

```text
1. evaluated_at = now()
2. if run window not started:
     return lightweight SensorResult / SkipReason
3. load expected calendar
4. read dynamic partitions
5. registered gap guard
6. batch readiness
7. selected-date gate
8. run request or skip
```

窗口前禁止：

1. 读取 qfq gold lake readiness。
2. 读取 silver / adj factor batch readiness。
3. 读取 qfq factor repair status。
4. 写入重型 continuity cursor。

### P0B：qfq gold readiness profiling

只读 profiling，禁止写 Dagster / lake。

必须拆分耗时：

| 维度 | 需要记录 |
| --- | --- |
| native 1/5/15/30/60 | path planning、schema、row count、path/freq/date、unique、price、coverage、formula。 |
| derived 90/120 | source path discovery、diagnostics、expected path、target counts、formula comparison。 |
| 10 天窗口 | 文件数、SQL 数、总耗时、最慢 SQL。 |
| 单日 vs 窗口级 | 证明当前 per-date 模型的重复扫描成本。 |
| bootstrap batch 对照 | 对比离线 qfq bootstrap batch audit 的 SQL 组织方式。 |

Profiling 输出必须写入 `/private/tmp`，不进入 repo，不写正式环境。

### P0C：重写 `batch_gold_stk_mins_qfq_lake_readiness`

目标：把 qfq gold readiness 从 per-date loop 改成真正窗口 batch。

建议实现方向：

1. 先一次性规划 10 天窗口内 native expected paths、derived expected paths、existing paths。
2. native 频度按 `freq` 或 `freq + date range` 集中读取 silver/gold/factor files。
3. derived 90/120 按 `target_freq + source_freq + year` 集中构造一次 derived diagnostics SQL，`partition_keys` 传入窗口内所有日期。
4. 所有 SQL 输出都必须带 `trade_date`，在内存里按 `trade_date` 聚合成 status。
5. 缺文件 / 缺上游的日期应先 fail closed，避免对明显缺失日期继续跑公式重查。
6. 保留完整 blocking check 语义，不允许用 row count 替代公式、coverage、derived source window 检查。

可以复用或抽取的参考：

1. `audit_stk_mins_qfq_bootstrap_batch(...)`
2. `audit_stk_mins_qfq_derived_bootstrap_batch(...)`
3. `_batch_silver_counts(...)`
4. `_batch_gold_counts(...)`
5. `_batch_factor_coverage_counts(...)`
6. `_batch_formula_counts(...)`
7. `_batch_derived_diagnostics_counts(...)`
8. `_batch_derived_formula_counts(...)`

注意：上述 bootstrap helper 是离线事件补录路径，不能直接把 runless event 写入逻辑带进 sensor。只能复用 SQL 组织思想或抽取纯只读统计函数。

### P0D：sensor 分层短路

qfq daily sensor 的检查顺序必须保持业务语义，但执行应短路：

```text
registered gap
  -> silver batch
  -> adj factor batch
  -> gold qfq batch
  -> selected target run decision
```

如果 silver 或 adj factor 在最早日期 already not ready，原则上不应再跑 gold qfq 重查。

qfq factor repair sensor：

```text
registered gap
  -> gold qfq batch
  -> only selected target qfq factor repair status
```

如果 gold qfq 在最早日期 not ready，不得读取后续日期 repair status。

当前落地对账：P0D 新增代码修改集中在 qfq daily sensor 的 silver -> adj factor -> gold lazy load；qfq factor repair sensor 当前代码已经满足 gold qfq 未 ready 时不读取 repair status，且 status 读取使用 `include_event_storage_ids=False`。P0E 必须继续用静态门禁和性能回归守住该口径。

### P0E：静态门禁和性能回归

必须新增或更新测试：

1. 窗口前 qfq daily 不调用任何 batch helper。
2. 窗口前 qfq factor repair 不调用 gold qfq batch helper。
3. qfq daily 当 silver 最早日期 not ready 时，不调用 gold qfq batch helper。
4. qfq factor repair 只在 gold qfq selected target ready 后读取 factor repair status。
5. `batch_gold_stk_mins_qfq_lake_readiness` 的单测必须证明窗口级调用不是日期×频度重复调用。
6. 性能测试必须记录默认 10 天窗口 qfq gold readiness elapsed ms；`stock_mins_qfq_daily_sensor` 另有正式例外，日常 tick 只扫最近 5 个 expected trade dates。
7. raw/silver stk mins、adj factor、major indices、market breadth、ClickHouse readiness helper 必须实际跑一遍本地性能样本或 fake-client 调用次数测试。
8. 所有性能测试只能使用临时目录、临时 Parquet、in-memory DuckDB、fake ClickHouse client；不得读取正式 lake、正式 Dagster runtime 或运行 `dg`。

静态门禁：

1. qfq sensors 禁止在窗口未到分支前调用重 batch helper。
2. qfq gold batch helper 禁止出现外层 `for trade_date in expected_trade_dates` 再调用 native/derived per-date count helper 的结构。
3. 日常 sensor hot path 禁止使用 `instance.get_event_records(... limit=500)` 这类无界或大 limit event history 回填。
4. sensor hot path batch helper 禁止依赖 Dagster instance；只能消费 DuckDB/lake 文件事实、fake client 或显式传入的 bounded 状态。
5. ClickHouse readiness helper 必须证明是 partition-set 级别调用，不得退回逐日查询。

## 7. 性能预算

| 项 | 预算 |
| --- | --- |
| qfq daily sensor 稳态 tick | 最近 5 个 expected trade dates 下目标 < 10s，硬上限 < 30s；2026-06-26 dry-run 为约 17.33s，已低于硬上限但仍需继续优化 gold qfq readiness。 |
| qfq factor repair sensor 稳态 tick | 目标 < 10s，硬上限 < 30s。 |
| qfq gold readiness formal lake full semantics | qfq daily sensor 只按最近 5 个 expected trade dates 执行；目标 < 10s，硬上限 < 25s。10 天窗口只保留为离线/测试性能回归参考，不进入 qfq daily sensor hot path。 |
| sensor gRPC timeout | 绝对不能接近 Dagster 60s 默认超时。 |
| Dagster event/check history hot path | 0 次无界深扫。 |
| 新增持久化状态实体 | 禁止，除非另起方案证明 DuckDB batch 和 Dagster metadata batch 都无法满足。 |

如果 profiling 证明完整 qfq gold semantics 在不新增持久化实体的前提下无法进入预算，必须停下重新设计，不得降低 check 语义。

## 8. 不做事项

P0 不做：

1. 不改 run key。
2. 不改 run config。
3. 不新增 asset、job、sensor、check、resource。
4. 不新增 status manifest、readiness asset、summary asset、数据库表或配置项。
5. 不运行 `dg`。
6. 不读取或写入正式 Dagster runtime，除非后续单独审批只读 profiling。
7. 不写正式 lake。
8. 不把文件存在、row count 当作完整 ready。
9. 不把离线 bootstrap event 写入逻辑接入日常 sensor。

## 9. 开发推进顺序

| 顺序 | 阶段 | 内容 | 是否需要审批 |
| --- | --- | --- | --- |
| 1 | P0A | qfq daily / qfq factor repair 窗口前 early skip。 | 需要用户批准代码修改。 |
| 2 | P0B | 只读 profiling 当前 qfq gold readiness，拆 native / derived / formula 耗时。 | 如读取正式 lake，仅只读；仍需用户明确批准。 |
| 3 | P0C | 重写 qfq gold readiness 为真正 batch。 | 需要用户批准代码修改。 |
| 4 | P0D | qfq daily / repair sensor 分层短路，避免不必要 gold qfq 重查。 | 需要用户批准代码修改。 |
| 5 | P0E | 全部 batch helper 门禁测试与性能回归；qfq gold 必须证明已改成真正 batch，其它 helper 必须证明没有同类高危模型。 | 需要用户批准代码/测试修改。 |
| 6 | P0F | qfq daily / qfq factor repair 本地回归、本地 pytest、性能结果落档。 | 需要用户批准代码/测试修改。 |
| 7 | P0G | 更新相关长期规范和既有性能文档状态。 | 文档修改。 |

### 9.1 全部 batch helper 门禁与性能测试范围

P0E 必须覆盖所有当前 sensor hot path 可调用的 batch readiness helper，不能只测 qfq gold。

其它 helper 的性能测试固定放在 P0E，而不是 P0B。P0B 只定位 qfq gold 当前实现的 native / derived / formula 耗时，用来指导 P0C 重写；P0E 是 qfq gold 重写和 sensor 分层短路后的统一验收阶段，必须把其它 helper 一起跑完，证明它们没有同类高危模型。

| Helper | 测试目标 | 门禁口径 |
| --- | --- | --- |
| `batch_raw_stk_mins_lake_readiness` | 10 天窗口、五频度、完整语义本地性能样本；确认没有 Dagster event history 读取。 | 允许集中 path planning + metrics SQL；禁止改回逐日 Dagster readiness wrapper。 |
| `batch_silver_stk_mins_lake_readiness` | 10 天窗口、五频度、stock daily / suspend / lifecycle 完整语义本地性能样本。 | 必须保留完整 blocking check 等价语义；禁止 row count 冒充 ready。 |
| `batch_gold_stk_mins_qfq_lake_readiness` | qfq gold P0 重写后的 10 天 native + derived full semantics 性能样本。 | 禁止日期×频度重复重 SQL；必须真正窗口级 batch。 |
| `batch_raw_adj_factor_lake_readiness` | 10 天窗口 raw 复权因子完整语义性能样本。 | 禁止逐日 Dagster readiness；生命周期事实源保持正式口径。 |
| `batch_silver_adj_factor_lake_readiness` | 10 天窗口 silver 复权因子完整语义性能样本。 | 同上。 |
| `batch_adj_factor_lake_readiness` | raw + silver combined 性能样本。 | 应复用同一次 `_batch_readiness`，不得重复扫描 raw/silver 两遍。 |
| `batch_market_major_indices_lake_readiness` | 10 天主要指数 gold readiness 性能样本。 | 小对象可以有限 per-date schema，但 metrics 必须批量读取。 |
| `batch_gold_market_breadth_lake_readiness` | 10 天市场宽度 gold readiness 性能样本。 | 当前允许小对象 per-date wrapper；若耗时接近预算，必须升级为真正 batch。 |
| `batch_gold_stock_return_distribution_lake_readiness` | 10 天涨跌分布 gold readiness 性能样本。 | 同上。 |
| `batch_clickhouse_market_breadth_readiness` | 10 天 ClickHouse serving readiness 调用次数与耗时。 | 必须按 partition set 一次 fetch，不得逐日查 ClickHouse。 |
| `batch_prod_clickhouse_market_breadth_readiness` | 10 天 prod/local ClickHouse 对账调用次数与耗时。 | prod/local 各一次 partition set fetch，不得逐日查。 |

P0E 的性能测试必须记录：

1. helper 名称。
2. 窗口起止日期和 expected date 数量。
3. 文件数或外部查询次数。
4. DuckDB / ClickHouse / Python 总耗时。
5. 最慢阶段或最慢 SQL。
6. 是否触发完整 blocking check 语义。
7. 是否存在日期×频度重复重扫。

若任何非 qfq helper 在 10 天窗口内出现接近 30 秒的 sensor hot path 风险，不能只记录为“待观察”，必须回到 P0C/P0D 同级别方案中追加修复阶段。

当前落地对账：P0E 已完成并提交 `b70c51c0`。所有当前 sensor hot path batch helper 已通过本地临时性能样本、fake client 调用次数测试和静态门禁；未发现需要新增同级别修复阶段的 helper。其它 helper 的性能测试已经在 P0E 完成，不再另设独立阶段。

## 10. 需要拍板的事项

以下口径已经拍板，P0 后续实现必须按表执行：

| 问题 | 已定口径 |
| --- | --- |
| qfq gold readiness 是否作为 P0 必修？ | 是。它是当前 60 秒 sensor timeout 的核心根因。 |
| 是否只做窗口前 early skip？ | 否。early skip 只是止血，必须同步推进真正 batch 重写。 |
| 是否允许降低完整 blocking check 语义换性能？ | 不允许。只能改读取模型，不能改语义。 |
| 是否新增持久化 readiness 实体？ | 当前不允许。必须先证明真正 batch 方案仍不达标。 |
| 是否把其它 batch helper 全部重写？ | 不全量重写。当前只有 qfq gold 是高危；其它 helper 必须纳入门禁和性能回归，并且必须实际跑一遍测试。 |
| 是否把离线 bootstrap batch helper 直接接进 sensor？ | 不允许直接接。可以抽取纯只读 SQL 统计能力，不能引入 event 写入逻辑。 |

## 11. 验收标准

P0 完成后必须满足：

1. qfq daily / qfq factor repair 窗口前不执行任何重 batch readiness。
2. `batch_gold_stk_mins_qfq_lake_readiness(...)` 不再是日期×频度重复重扫。
3. qfq daily / repair sensor 在 10 天窗口下稳定远离 60 秒 gRPC timeout。
4. qfq gold readiness 保留 native + derived 全部正式 blocking check 语义。
5. 所有 sensor hot path batch helper 都完成一次本地性能回归，并记录结果。
6. 静态门禁能阻止名不副实 batch 回流。
7. 文档、测试、代码口径一致。
