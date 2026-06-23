# Dagster Asset UI Status 性能诊断

更新时间：2026-06-23

## 1. 结论

本诊断只回答两个问题：

1. Dagster UI `/assets` 页面 Status 相关的真实查询与本机指标是什么。
2. 哪些 asset / check / event 是当前 Dagster storage 的高基数来源。

本轮不提出最终修复方案，不修改 Dagster 代码，不运行 job、sensor、backfill、asset check 或 materialization，不写 Dagster DB，不写数据湖文件。

当前结论：

1. `/assets` HTML shell 和资产 definition 列表不是慢点；本机 GraphQL 读取 definition 约 0.009s。
2. Status 相关字段属于 GraphQL + Dagster instance storage 查询。当前复测中，`partitionStats`、`assetChecksOrError`、`executionForLatestMaterialization` 等后端查询没有稳定复现 45s 级耗时，但这些查询依赖的底层表已经是高基数：`event_logs` 约 642 万行，`asset_check_executions` 约 125 万行。
3. `/assets` 页面需要处理的资产分区规模已经较大：55 个 asset，共约 146,408 个 partitions。全量 `partitionKeysByDimension` 响应约 1.9MB，说明前端渲染和 GraphQL payload 体积也可能成为 Status 列迟迟显示的原因之一。
4. 高基数来源主要集中在旧 `raw_tushare_index_daily_by_code`、指数日线、主要指数日线、股票分钟线 raw/silver/qfq/MACD/KDJ、多 check 的日频资产。
5. 当前问题不是简单调大 timeout 或 pool 参数能解决的。调参只能缓解偶发超时；随着 partitions、asset checks、event logs 继续增长，全局 Asset Catalog 的 status 查询会继续承压。

## 2. 外部依据

Dagster 官方文档说明：

1. Dagster webserver 提供 Dagster UI，并响应 GraphQL queries；Assets 页面列出 deployment 内资产，并可进入 asset details 查看 partitions、events、checks 等信息。参考：[Dagster webserver and UI](https://docs.dagster.io/guides/operate/webserver)。
2. Dagster instance storage 会持久化 runs、event logs、schedule/sensor ticks 等元数据；Postgres storage 通过 `dagster.yaml` 配置。参考：[Instance configuration](https://docs.dagster.io/deployment/oss/oss-instance-configuration)。
3. Asset checks 是资产质量检查，会随 asset materialization 执行，也会出现在 UI 中。参考：[Asset checks](https://docs.dagster.io/dagster-basics-tutorial/asset-checks)。
4. Dagster 不会在底层数据删除时自动清理 partition metadata；官方建议用 retention / synchronization sensor 防止 UI 资产视图积累无用 partition metadata。参考：[Data retention for partitioned assets](https://docs.dagster.io/guides/build/partitions-and-backfills/data-retention)。

Dagster 上游曾处理过同类问题：

1. PR [#25718](https://github.com/dagster-io/dagster/pull/25718) 记录了 `200k+ partitions` 资产导致 UI 冻结 `30+ seconds` 的问题，修复方向是避免遍历 partition space，改用 `liveData.partitionStats`。
2. PR [#10822](https://github.com/dagster-io/dagster/pull/10822) 引入 / 调整 partition status cache 和 `partitionStats` resolver，用缓存/汇总数据支撑 UI。

这些依据说明：高 partition / 高 event / 高 check 数量导致 Dagster UI 状态查询变慢，不是 Goldenshare 独有问题。

## 3. 本机环境

| 项 | 当前值 |
| --- | --- |
| Dagster 版本 | 1.13.8 |
| 官方文档最新版本 | 1.13.10 |
| Dagster UI | `http://127.0.0.1:3000` |
| Dagster storage | Postgres |
| DB URL | `postgresql://congming@localhost:5432/goldenshare_dagster` |
| `DAGSTER_HOME` | `/Users/congming/.goldenshare/dagster_home` |

本轮只读命令类型：

1. 本机 Dagster GraphQL POST 查询。
2. 本机 Postgres 只读聚合 SQL。
3. 本机 package / GraphQL schema introspection。

未执行：

1. 未运行 `dg`。
2. 未提交 run。
3. 未触发 sensor。
4. 未 materialize asset。
5. 未执行 asset check。
6. 未写 Dagster DB。
7. 未写数据湖文件。

## 4. GraphQL 查询指标

### 4.1 本次复测结果

| 查询 | 目的 | 耗时 | 响应大小 | 结论 |
| --- | --- | ---: | ---: | --- |
| `{ __typename }` | webserver / GraphQL 基础连通 | 0.033s | 31 B | 不慢 |
| `assetNodes` basic fields | asset definition 列表 | 0.009s | 8,133 B | 不慢 |
| `assetNodes.partitionStats` | 全资产分区统计 | 0.972s | 9,298 B | 当前未复现慢，但依赖高基数 partition metadata |
| `assetNodes.assetChecksOrError` | 全资产 check definitions | 0.907s | 48,728 B | 当前未复现慢 |
| `assetNodes.executionForLatestMaterialization` | check 最新执行状态 | 1.952s | 78,824 B | 可接受，但已明显重于 definition 查询 |
| `assetNodes.staleStatus + freshnessStatusInfo + partitionStats` | Status 常见组合字段 | 0.646s | 11,993 B | 当前未复现慢 |
| `assetNodes.partitionKeysByDimension` | 全资产 partition keys | 0.172s | 1,917,625 B | 后端不慢，但 payload 大，可能造成前端渲染压力 |
| `assetNodes.assetPartitionStatuses.__typename` | partition status union 类型 | 0.455s | 8,431 B | 当前未复现慢 |

### 4.2 已观察过的慢查询

此前同一问题排查中曾观察到：

| 查询 | 观察耗时 | 现象 |
| --- | ---: | --- |
| `assetNodes.partitionStats` | 约 45s | 全资产分区统计曾明显变慢 |
| `assetNodes.assetChecksOrError` 相关查询 | 约 98s | 曾触发 SQLAlchemy pool timeout |

本次复测未稳定复现上述 45s / 98s 结果，因此本文不把它们写成“当前必然慢查询”。更准确的表述是：

1. Dagster 全局资产 Status 查询存在高基数结构性风险。
2. 当前后端查询有缓存或状态变化时可恢复到秒级以内。
3. 一旦缓存失效、并发查询叠加、UI 拉取更完整字段、或 event/check 表继续增长，就可能重新出现 30s 到 60s 级延迟或 pool timeout。

## 5. Dagster Storage 总量

本机 Postgres 只读统计：

| 表 | 行数 |
| --- | ---: |
| `event_logs` | 6,423,756 |
| `asset_check_executions` | 1,253,712 |
| `runs` | 71,144 |
| `asset_keys` | 58 |

`asset_check_executions` 分区归属：

| 项 | 数量 |
| --- | ---: |
| total check events | 1,253,712 |
| `partition is null` | 504,829 |
| `partition is not null` | 748,883 |

解释：

1. `asset_check_executions` 已超过 125 万行，是 Status / Checks 相关查询的核心压力源。
2. 约 50.5 万条 check event 没有 partition 归属，主要来自历史非分区 check 或旧定义口径。这类 event 会继续留在 Dagster storage 中参与全局历史规模。
3. `event_logs` 约 642 万行，其中 asset check evaluation 是最大事件类型。

## 6. Dynamic Partitions 规模

| partition set | partition count | min | max |
| --- | ---: | --- | --- |
| `cn_a_trade_days` | 8,665 | 1990-12-19 | 2026-06-22 |
| `cn_a_index_trade_days` | 6,411 | 2000-01-04 | 2026-06-22 |
| `cn_a_stock_mins_trade_days` | 4,240 | 2009-01-05 | 2026-06-22 |
| `cn_a_stock_current_trade_days` | 4,240 | 2009-01-05 | 2026-06-22 |
| `cn_a_stock_trade_days` | 3,029 | 2014-01-02 | 2026-06-22 |
| `cn_a_stock_mins_silver_trade_days` | 3,028 | 2014-01-02 | 2026-06-18 |
| `cn_a_index_ts_codes` | 946 | 000001.SH | CN2850.CNI |

资产级 `partitionStats` 汇总：

| 项 | 数量 |
| --- | ---: |
| asset count | 55 |
| total partitions | 146,408 |
| total materialized | 146,400 |

Top partitioned assets：

| asset | partitions | materialized |
| --- | ---: | ---: |
| `gold_market_major_indices_daily` | 6,411 | 6,411 |
| `silver_index_daily` | 6,411 | 6,411 |
| `raw_stk_mins_1m/5m/15m/30m/60m` | 4,240 each | 4,239 each |
| `raw_tushare_adj_factor` | 4,240 | 4,240 |
| `silver_adj_factor` | 4,240 | 4,240 |
| `raw_tushare_stock_daily` | 3,029 | 3,029 |
| `silver_stock_daily` | 3,029 | 3,029 |
| `gold_stk_mins_qfq_*` | 3,028 each | 3,028 each |
| `gold_stk_mins_qfq_macd_kdj_*` | 3,028 each | 3,028 each |

## 7. Event Log 高基数来源

### 7.1 Event 类型分布

| event type | count |
| --- | ---: |
| `ASSET_CHECK_EVALUATION` | 1,273,675 |
| `ASSET_CHECK_EVALUATION_PLANNED` | 492,593 |
| `STEP_OUTPUT` | 481,844 |
| `STEP_START` | 481,801 |
| `STEP_SUCCESS` | 480,605 |
| `RESOURCE_INIT_SUCCESS` | 474,782 |
| `RESOURCE_INIT_STARTED` | 474,782 |
| `LOGS_CAPTURED` | 474,721 |
| `STEP_WORKER_STARTED` | 471,524 |
| `STEP_WORKER_STARTING` | 471,524 |
| `ENGINE_EVENT` | 249,174 |
| `ASSET_MATERIALIZATION` | 222,456 |
| `ASSET_MATERIALIZATION_PLANNED` | 96,165 |
| `PIPELINE_ENQUEUED` | 68,008 |
| `PIPELINE_START` | 62,883 |
| `PIPELINE_SUCCESS` | 61,706 |

结论：

1. 最大事件类型是 `ASSET_CHECK_EVALUATION`，说明 asset check 数量是 UI Status/Checks 压力的主因之一。
2. 其次是大量 step/resource/run 生命周期事件，来自高 run count 的历史任务。

### 7.2 按 asset 聚合的 event log 来源

| asset | event count | partition count |
| --- | ---: | ---: |
| `raw_tushare_index_daily_by_code` | 48,515 | 946 |
| `silver_index_daily` | 28,431 | 6,411 |
| `prod_ch_share_fact_market_breadth_daily` | 19,960 | 3,028 |
| `raw_tushare_index_daily` | 19,792 | 8,572 |
| `ch_share_fact_market_breadth_daily` | 15,710 | 3,028 |
| `raw_tushare_suspend_d` | 14,262 | 3,029 |
| `silver_stock_suspend_daily` | 14,262 | 3,029 |
| `gold_market_major_indices_daily` | 13,048 | 6,411 |
| `gold_stock_return_distribution` | 12,121 | 3,029 |
| `raw_tushare_stock_daily` | 8,359 | 3,029 |
| `silver_stock_daily` | 8,355 | 3,029 |

### 7.3 按 job 聚合的 run 来源

| job | run count | partition count |
| --- | ---: | ---: |
| `index_daily_update_job` | 24,741 | 949 |
| `clickhouse_share_fact_market_breadth_update_job` | 9,622 | 3,019 |
| `market_major_indices_daily_update_job` | 6,635 | 6,410 |
| `silver_index_daily_update_job` | 6,531 | 6,411 |
| `stock_return_distribution_daily_job` | 6,037 | 3,020 |
| `prod_clickhouse_share_fact_market_breadth_sync_job` | 5,749 | 3,019 |
| `bootstrap_quote_daily_job` | 5,162 | 3,004 |
| `daily_market_breadth_job` | 3,009 | 3,009 |
| `__ephemeral_asset_job__` | 2,987 | 2,983 |

结论：

1. `index_daily_update_job` 是 run 数量第一大来源，主要对应旧 by-code 指数日线模式。
2. 多个日频 / 指数 / 市场宽度 job 已经产生数千到数万 run。
3. 这些 run 不直接等于 `/assets` Status 慢点，但会放大 `event_logs` 和 run history 的整体体积。

## 8. Asset Check 高基数来源

### 8.1 按 asset 聚合

| asset | check event count | distinct partition count | check name count |
| --- | ---: | ---: | ---: |
| `silver_index_daily` | 124,234 | 6,391 | 8 |
| `raw_tushare_index_daily_by_code` | 123,684 | 0 | 5 |
| `gold_market_major_indices_daily` | 66,360 | 0 | 11 |
| `silver_stock_daily` | 62,596 | 1 | 16 |
| `ch_share_fact_market_breadth_daily` | 57,852 | 0 | 6 |
| `silver_adj_factor` | 42,520 | 4,215 | 10 |
| `gold_stock_return_distribution` | 36,366 | 0 | 6 |
| `raw_tushare_adj_factor` | 33,944 | 4,215 | 8 |
| `gold_market_breadth_daily` | 31,009 | 0 | 8 |
| `silver_stk_mins_1m/5m/15m/30m/60m` | 30,280 each | 3,014 each | 10 each |
| `raw_stk_mins_1m` | 29,757 | 4,209 | 7 |
| `raw_stk_mins_5m/15m/30m/60m` | ~29,715 each | 4,209 each | 7 each |
| `gold_stk_mins_qfq_*` | ~24,348 each | 3,028 each | 9 each |

说明：

1. `raw_tushare_index_daily_by_code` 是旧 by-code 资产，check event 数量极高，且 `partition_count=0`，说明其 check event 没有按当前常规日期 partition 归属。
2. `gold_market_major_indices_daily`、`ch_share_fact_market_breadth_daily`、`gold_stock_return_distribution` 等资产 check event 也大量存在 `partition_count=0` 的情况，需要后续单独审计是历史定义问题，还是当前 check definition 仍未继承 partition。
3. 分钟线资产单个 asset 的 check event 不一定排第一，但频度多，整体叠加后规模大。

### 8.2 按 check name 聚合

| check name | count | asset count | partition count |
| --- | ---: | ---: | ---: |
| `raw_index_daily_by_code_file_exists` | 24,738 | 1 | 0 |
| `raw_index_daily_by_code_required_columns_and_types` | 24,737 | 1 | 0 |
| `raw_index_daily_by_code_partition_code_matches` | 24,737 | 1 | 0 |
| `raw_index_daily_by_code_unique_ts_code_trade_date` | 24,736 | 1 | 0 |
| `raw_index_daily_by_code_row_count_positive` | 24,736 | 1 | 0 |
| `gold_stk_mins_qfq_*` structural checks | 21,278 each | 7 | 3,019 |
| `gold_stk_mins_qfq_macd_kdj_*` checks | 21,266 each | 7 | 3,028 |
| `raw_stk_mins_*` checks | 21,231 each | 5 | 4,209 |
| `silver_index_daily_required_columns_and_types` | 20,955 | 1 | 6,391 |
| `silver_index_daily_row_count_positive` | 20,955 | 1 | 6,391 |

结论：

1. 旧指数日线 by-code check 是最明显的高基数单点。
2. qfq、MACD/KDJ、raw 分钟线属于“单 check 数量中等，但资产频度多”的高基数组。
3. `silver_index_daily` 属于“单 asset 长历史 + 多 check”的高基数组。

## 9. 本轮确认的真实问题

### 9.1 可以确认

1. Dagster `/assets` Status 类查询依赖 GraphQL 和 Dagster instance storage，不是纯前端静态展示。
2. 当前 Dagster storage 已经积累到百万级 check event、百万级 event log 的规模。
3. 高基数来源清楚：旧 by-code index daily、index daily、major indices、stock mins raw/silver/qfq/MACD/KDJ、多 check 日频资产。
4. 当前全局资产列表需要处理约 14.6 万 partition 统计，以及最大 1.9MB 的 partition keys payload。
5. Dagster 上游也承认并修过 `100k+ / 200k+ partitions` 级 UI 性能问题；这类问题会随着历史增长自然出现。

### 9.2 本轮没有确认

1. 本次复测没有稳定复现 `partitionStats` 45s 和 `assetChecksOrError` 98s。
2. 本轮没有抓取浏览器 DevTools waterfall，因此还不能断言 Status 列迟迟显示完全是某一个 GraphQL resolver。
3. 本轮没有做 Postgres `EXPLAIN ANALYZE`，因此还不能把慢点归因到某个 SQL plan 或索引缺失。
4. 本轮没有修改或清理任何历史 event，因此没有验证清理后的 UI 变化。

## 10. 后续诊断建议

下一步如果继续确认根因，应先做只读 browser waterfall + Postgres query profiling，而不是直接改代码：

1. 用浏览器 DevTools 或自动化 HAR 捕获 `/assets` 页面打开时的全部 GraphQL 请求，记录每个请求的 query name、字段、耗时、响应大小。
2. 对最慢 GraphQL 请求在 Postgres 侧做只读 `EXPLAIN ANALYZE`，确认是 event log、check executions、partition stats、run history，还是 client payload/render 造成。
3. 单独审计 `partition_count=0` 但 check event 数量很大的资产，确认是否仍有 partitioned check definition 归属问题。
4. 单独列出可退出 active definitions 的旧资产，尤其是 `raw_tushare_index_daily_by_code` 这类计划迁移/删除的历史资产。
5. 在修复方案前，不做数据库删除、不做 event 清理、不写 runless event、不修改 Dagster startup 参数作为正式解决方案。
