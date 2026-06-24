# Dagster Asset Check 增量治理专项方案

更新时间：2026-06-24

低层设计：[`dagster-asset-check-incremental-governance-low-level-design.md`](./dagster-asset-check-incremental-governance-low-level-design.md)

## 1. 背景

股票分钟线历史 event retention 已经把分钟线普通历史 check event 压到最近 20 个交易日窗口内，但 Dagster DB 膨胀的根因还没有完全解决。当前剩余压力主要来自非分钟线普通 asset checks，以及部分历史 check event 没有正确 partition 归属。

本专项目标不是继续靠“事后删除”解决问题，而是治理增量写入模型：

1. 判断每类 check 是否还有必要继续作为 Dagster Asset Check 写入 DB。
2. 可以合并的 check 合并。
3. 意义弱、重复或只服务排障的 check 退出正式 DB 写入。
4. sensor 热路径需要的 readiness 优先迁到 DuckDB lake readiness。
5. 运行详情类事实写入 asset materialization metadata。
6. 重型历史一致性验证改为离线审计报告。
7. 普通质量 check 只保留最近 N 天 Dagster check event。

本方案只做设计与分阶段治理，不删除数据、不修改生产代码、不运行 Dagster job/sensor/backfill。

## 2. 当前只读审计事实

审计来源：

1. `LAKE_ASSET_CATALOG` 当前 active asset 事实。
2. `orchestrator.defs.sensors.readiness.AssetReadinessSpec` 与各 readiness specs。
3. `defs/checks/**`、`defs/jobs/**`、`defs/catalog/lake_assets.py`。
4. 本机正式 Dagster Postgres 只读统计 `asset_check_executions`。

范围说明：

1. 全量资产清单以 `LAKE_ASSET_CATALOG` 中 active assets 为准。
2. 表格中的当前 blocking check 数来自 catalog 的 `blocking_check_names`。
3. 非 blocking / WARN 观测 check 也会写入 Dagster DB；它们不参与 readiness 阻断，默认不应长期保留，后续按 materialization metadata 或离线审计报告收敛。
4. repair/status/completion 类通过 op helper 上报的特殊 check 不属于 ordinary quality check，按保护账本单独处理。

当前 `asset_check_executions` 高基数分布如下：

| 资产族 | check rows | asset 数 | check name 数 | distinct partition 数 | null partition rows | 最近 7 天新增 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| other | 256,058 | 18 | 127 | 4,215 | 180,188 | 543 |
| market_breadth / return / serving | 111,799 | 4 | 24 | 4 | 111,779 | 122 |
| index_daily | 45,358 | 2 | 10 | 20 | 45,318 | 70 |
| raw_stk_mins | 1,372 | 5 | 7 | 0 | 1,372 | 140 |
| gold_qfq | 1,330 | 7 | 12 | 20 | 840 | 763 |
| silver_stk_mins | 1,000 | 5 | 10 | 4 | 800 | 200 |
| MACD/KDJ indicator | 861 | 7 | 5 | 21 | 168 | 357 |
| MACD/KDJ state | 469 | 7 | 3 | 21 | 84 | 189 |

当前最大来源已经不是分钟线历史，而是以下资产：

| asset | check rows | check names | null partition rows | 说明 |
| --- | ---: | ---: | ---: | --- |
| `gold_market_major_indices_daily` | 66,370 | 11 | 66,370 | 多个普通质量 check，历史 partition 归属为空 |
| `silver_stock_daily` | 61,560 | 14 | 61,560 | 日线 silver 质量 check 较多，历史 partition 归属为空 |
| `silver_index_daily` | 45,316 | 8 | 45,316 | 指数日线 silver 质量 check 较多，历史 partition 归属为空 |
| `silver_adj_factor` | 42,430 | 10 | 280 | 正常分区较多，check 颗粒度偏细 |
| `ch_share_fact_market_breadth_daily` | 39,656 | 6 | 39,656 | ClickHouse 本地 serving 对账 check 历史较多 |
| `raw_tushare_adj_factor` | 33,952 | 8 | 232 | 正常分区较多，check 颗粒度偏细 |
| `gold_market_breadth_daily` | 30,851 | 8 | 30,851 | 衍生指标 check 与重算对账 check 混在一起 |
| `prod_ch_share_fact_market_breadth_daily` | 23,100 | 4 | 23,080 | 已知历史 batch check 归属问题，不再做全量补录 |
| `raw_tushare_stock_daily` | 20,665 | 8 | 20,665 | raw 日线普通质量 check 颗粒度偏细 |
| `raw_tushare_suspend_d` | 20,534 | 5 | 20,534 | raw 停牌日线普通质量 check 颗粒度偏细 |
| `gold_stock_return_distribution` | 18,192 | 6 | 18,192 | 衍生分布指标 check 与重算对账 check 混在一起 |
| `silver_stock_suspend_daily` | 10,278 | 3 | 10,278 | silver 停牌日线普通质量 check |

结论：

1. 继续只做历史删除无法根治，因为高基数 ordinary checks 仍会持续新增。
2. 许多 check 的语义是必要的，但不必继续以“每个细项一条 Dagster DB check event”的形态长期存在。
3. 大量 `partition is null` 的历史 check event 会降低 UI 和 retention 的可解释性；后续新实现必须确保 partitioned asset check 归属正确。

## 3. 治理原则

### 3.1 Dagster DB 只保留控制面需要的状态

继续写 Dagster Asset Check 的条件：

1. 该 check 是 sensor / run-status sensor / repair gate / completion gate 必须直接消费的状态。
2. 该 check 是用户在 Dagster UI 里需要看到的当前资产健康摘要。
3. 该 check 是少量高价值、低频、不可由 materialization metadata 表达的契约。

不满足以上条件的细粒度检查，不应继续长期写 Dagster DB。

### 3.2 数据正确性语义不能删除，只能换承载位置

本专项不是降低质量，而是把质量语义放到更合适的位置：

| 目标 | 推荐承载位置 |
| --- | --- |
| sensor 判断某天能不能推进 | DuckDB lake readiness |
| 记录本次产物行数、路径、字段、样本 | materialization metadata |
| 历史长窗口重算、跨系统对账 | 离线审计报告 |
| 当前资产是否可消费 | 少量 Dagster blocking check |
| repair / completion 状态账本 | Dagster check metadata，长期保留 |

### 3.3 普通历史 check event 默认只保留最近 N 天

普通数据质量 check 的 Dagster 历史事件只用于近期运维判断，不再永久保存 2014 年以来全部绿灯证明。

默认口径：

1. 股票分钟线：继续保留最近 20 个 `cn_a_stock_mins_trade_days`。
2. 股票日线 / 复权因子 / 停牌 / 指数日线 / 市场宽度：后续阶段按对应资产族交易日分区保留最近 20 个交易日。
3. full snapshot 资产：保留 latest state 和少量最近 materialization/check，不保留全历史每次运行细项。
4. repair/status/completion check：不进入普通 retention。

## 4. Check 处理方式定义

### A. 必须继续写 Dagster DB

这类 check 是控制链路账本或当前健康锚点。

必须保留：

1. `gold_stk_mins_qfq_factor_repair_plan_evaluated`
2. `gold_stk_mins_qfq_macd_kdj_repair_completed_check`
3. `lake_root_health` 的平台健康 check。
4. 每个 active asset 的少量“当前可消费摘要 check”，但应逐步合并为更粗粒度 check。

规则：

1. repair/status/completion check 永久保护，不参与普通历史清理。
2. 当前健康摘要 check 可以保留 latest + 最近 N 天，不要求永久保留全历史。
3. 新增 check 必须有明确消费者或 UI 价值，不能为了把 metadata 拆细而新增。

### B. 迁到 sensor hot path DuckDB lake readiness

适用语义：

1. 文件存在。
2. row count。
3. schema / required columns。
4. partition date / freq path match。
5. unique key。
6. price / volume / amount sanity。
7. code coverage / universe coverage。
8. qfq formula / derived source / source window。
9. stock lifecycle coverage。

要求：

1. DuckDB readiness 必须复刻正式 blocking check 语义，不能只用文件存在和 row count 冒充 ready。
2. batch helper 必须是真 batch，不能把逐日期重 SQL 包一层 batch 名字。
3. sensor 热路径只看最近 10 个 expected dates；长窗口走离线审计。
4. readiness 迁移完成前，不得删除原 Dagster check 消费口径。

### C. 改为 materialization metadata

适用语义：

1. 本次输出路径。
2. 输出文件数。
3. row count。
4. observed columns。
5. min/max trade_date。
6. code_count / missing code samples。
7. source row count。
8. elapsed_ms / source_method。

这些字段对排障有价值，但不应拆成多条 check event。

### D. 改为离线审计报告

适用语义：

1. 长历史重算。
2. 跨系统 ClickHouse/local 对账。
3. 大范围 rank/order 连续性。
4. serving 表与 gold 表全字段对账。
5. 历史完整性巡检。

离线审计输出 JSON/CSV 报告，不在日常 job 中对每个历史 partition 写 check event。

### E. 只保留最近 N 天 Dagster check event

适用语义：

1. 普通 raw/silver/gold quality check。
2. 非 repair/status 的 daily partition checks。
3. 分钟线普通 checks。
4. 指数日线、股票日线、复权因子、停牌、市场宽度等 ordinary checks。

## 5. 可合并 Check 类型

以下合并方向是后续开发的默认目标。合并前必须同步更新 catalog、readiness specs、jobs、tests、文档和 retention 白名单。

| 当前细项 | 合并后建议 | 去向 |
| --- | --- | --- |
| file exists / row count positive / required columns / schema | `*_contract_check` | Dagster DB 保留 current/latest；历史保留 N 天 |
| partition date matches / freq path match | 并入 `*_contract_check` | DuckDB readiness + metadata |
| unique key / conflicting duplicate absent | `*_key_integrity_check` | Dagster DB current/latest 或 DuckDB readiness |
| price sanity / volume sanity / amount sanity | `*_value_domain_check` | DuckDB readiness，必要时 current summary check |
| row count matches expected / coverage complete / registered code coverage | `*_coverage_check` | DuckDB readiness |
| lifecycle/listed/CNY coverage | `*_universe_membership_check` | DuckDB readiness，事实源统一 `silver_stock_lifecycle` |
| formula matches / derived formula / source window | `*_lineage_consistency_check` | DuckDB readiness；重型历史抽样进入离线审计 |
| cross-system row matches local/gold | `*_serving_consistency_audit` | 离线审计报告，latest 可保留一个摘要 check |

注意：已有 check 名称不能为了好看直接改名。后续阶段若需要新增合并后 check，必须在同一阶段移除旧 check 消费口径，不能长期双轨。

## 6. 全量资产族处置矩阵

### 6.1 Calendar / Basic Full Snapshot

| asset | 当前 blocking checks | 当前 DB 行数 | 治理口径 |
| --- | ---: | ---: | --- |
| `raw_tushare_trade_calendar` | 3 | 3 | 保留 Dagster DB；低频 full snapshot，后续可合并为 `raw_tushare_trade_calendar_contract_check` |
| `silver_trade_calendar` | 2 | 2 | 保留 Dagster DB；低频 full snapshot，后续可合并为 `silver_trade_calendar_contract_check` |
| `raw_tushare_stock_basic` | 4 | 8 | 保留 latest + 少量历史；file/columns/row count 合并为 source contract |
| `silver_stock_basic` | 6 | 12 | 保留 latest；current-listed-only 语义继续作为 stock basic 自身事实，不做历史生命周期事实 |
| `silver_stock_lifecycle` | 6 | 24 | 保留 latest；这是历史生命周期正式事实源，下游不得各自读 raw_stock_basic 拼口径 |
| `raw_tushare_namechange` | 7 | 41 | 保留 latest；普通 contract check 可合并 |
| `silver_namechange` | 10 | 60 | 保留 latest；区间一致性 check 有价值，但历史全量不长期保留 |
| `silver_stock_identity_map` | 12 | 60 | 保留 latest；身份映射是多个链路前置，check 可合并但不删除语义 |
| `raw_tushare_index_basic` | 5 | 5 | 保留 latest；低频 full snapshot |
| `silver_index_basic` | 6 | 6 | 保留 latest；低频 full snapshot |

处置步骤：

1. P1 优先不动这些资产的功能语义，因为当前 DB 行数低。
2. 后续统一把 contract 类细项合并为 1 到 2 个 check。
3. full snapshot 历史 event 只保留 latest + 最近少量运行，不保留全历史细项。

### 6.2 Stock Daily / Suspend / Adj Factor

| asset | 当前 blocking checks | 当前 DB 行数 | 当前问题 | 治理口径 |
| --- | ---: | ---: | --- | --- |
| `raw_tushare_suspend_d` | 5 | 20,534 | 细项多，历史 partition 为空 | 合并 contract check；热路径 readiness 用 DuckDB |
| `silver_stock_suspend_daily` | 3 | 10,278 | 普通质量 check 历史多 | 保留 compact current check，历史 keep20 |
| `raw_tushare_stock_daily` | 8 | 20,665 | 细项多，历史 partition 为空 | 合并 raw contract/coverage/key check；sensor readiness 用 DuckDB |
| `silver_stock_daily` | 11 | 61,560 | 当前最大来源之一，细项过多 | 合并 contract/key/value/universe checks；历史 keep20 |
| `raw_tushare_adj_factor` | 8 | 33,952 | 分区多，细项多 | 合并 contract/key/value check；热路径 readiness 用 DuckDB |
| `silver_adj_factor` | 10 | 42,430 | 分区多，细项多 | 合并 contract/coverage/value/key check；历史 keep20 |

处置步骤：

1. 先建立 daily family DuckDB lake readiness，覆盖现有完整 blocking semantics。
2. sensor 不再依赖逐日 Dagster check history 判断 readiness。
3. materialization metadata 记录 row_count、expected_count、missing samples。
4. Dagster DB 只保留少量 compact checks 和最近 20 个交易日普通历史。

### 6.3 Stock Minutes

| asset family | assets | 当前 DB 行数 | 治理口径 |
| --- | --- | ---: | --- |
| raw_stk_mins | `raw_stk_mins_1m/5m/15m/30m/60m` | 1,372 | 已有 keep20 retention；继续保留 compact ordinary checks，hot path 用 DuckDB readiness |
| silver_stk_mins | `silver_stk_mins_1m/5m/15m/30m/60m` | 1,000 | 已有 keep20 retention；生命周期语义已从 namechange/current-listed-only 收敛到 `silver_stock_lifecycle` |
| gold_stk_mins_qfq | `gold_stk_mins_qfq_1m/5m/15m/30m/60m/90m/120m` | 1,330 | 已有 keep20 retention；effective readiness 继续处理 repair-adjusted qfq |
| MACD/KDJ indicator | `gold_stk_mins_qfq_macd_kdj_1m/5m/15m/30m/60m/90m/120m` | 861 | 已有 keep20 retention；普通 check 可继续保留最近窗口 |
| MACD/KDJ state | `gold_stk_mins_qfq_macd_kdj_state_1m/5m/15m/30m/60m/90m/120m` | 469 | 已有 keep20 retention；state 是递推链关键状态，latest/current check 必须保留 |

处置步骤：

1. 分钟线暂不作为第一优先级，因为存量已被压住。
2. 后续可以把 raw/silver/qfq 的多个普通 check 合并为 compact check，但必须先确认 readiness helper 已完全替代旧 check 消费。
3. repair/status/completion check 永久保护，不纳入普通清理。

### 6.4 Index Daily / Major Indices

| asset | 当前 blocking checks | 当前 DB 行数 | 当前问题 | 治理口径 |
| --- | ---: | ---: | --- | --- |
| `raw_index_daily` | 2 | 42 | 新 by-date raw 口径，当前量低 | 保留 Dagster DB；后续按 index daily retention |
| `silver_index_daily` | 7 | 45,316 | 高基数，历史 partition 为空 | 建 DuckDB readiness；合并 contract/key/value/coverage check；历史 keep20 |
| `gold_market_major_indices_daily` | 10 | 66,370 | 当前最大来源，历史 partition 为空 | 使用已规划的 major indices batch selector；rank/seed 历史验证转离线审计 |

处置步骤：

1. 优先治理 `gold_market_major_indices_daily` 和 `silver_index_daily`。
2. `gold_market_major_indices_daily_rank_matches_active_seed_order`、seed/index basic coverage 等历史长链检查，转成 latest compact check + 离线报告。
3. sensor hot path 只读 batch selector / DuckDB readiness，不扫 Dagster 历史 check。

### 6.5 Market Breadth / Return Distribution / Serving

| asset | 当前 blocking checks | 当前 DB 行数 | 当前问题 | 治理口径 |
| --- | ---: | ---: | --- | --- |
| `gold_market_breadth_daily` | 8 | 30,851 | 重算对账和普通质量混合 | 普通质量合并；`matches_silver_recompute` 转离线审计或 latest 摘要 |
| `gold_stock_return_distribution` | 6 | 18,192 | 重算对账和普通质量混合 | 普通质量合并；`recomputed_from_silver` 转离线审计或 latest 摘要 |
| `ch_share_fact_market_breadth_daily` | 6 | 39,656 | serving 对账高基数 | 保留 latest serving health；历史全量对账转离线报告 |
| `prod_ch_share_fact_market_breadth_daily` | 4 | 23,100 | 历史 batch check 归属问题 | 不做 3,007 历史补录；日常 single-partition 归属修复后只保留 latest/recent |

处置步骤：

1. serving 对账类 check 不再长期逐日全量保留。
2. ClickHouse/local/gold row match 作为离线审计主路径。
3. Dagster DB 保留最新发布是否健康的摘要 check。
4. `prod_ch_share_fact_market_breadth_daily` 继续排除历史清理的高风险候选，直到单独证明 latest state 完整安全。

### 6.6 Platform

| asset | 当前 blocking checks | 当前 DB 行数 | 治理口径 |
| --- | ---: | ---: | --- |
| `lake_root_health` | 4 | 48 | 保留 Dagster DB；这是平台健康观测，不进入普通历史 retention 第一批 |

## 7. 分阶段推进计划

### P0：专项方案与静态审计

状态：P0.1 治理矩阵与静态门禁已完成。

目标：

1. 落本方案文档。
2. 建立全量 asset/check 分类清单。
3. 禁止新增高基数 check 前不写治理归属。

已落地：

1. 新增 `tests/test_asset_check_incremental_governance.py`，覆盖 `LAKE_ASSET_CATALOG` 当前 56 个 active assets 的 blocking checks。
2. 新增 protected repair/status/completion check 治理矩阵，禁止被普通 retention 候选误删。
3. 增加 checks-only 维护 job 静态门禁：`*_check_refresh_job` 只能选择 `AssetSelection.checks_for_assets(...)`，不得选择 materializable assets。
4. `gold_wealth_market_turnover` 已确认是正式 catalog asset，已纳入治理矩阵。
5. 本阶段不改生产运行逻辑、不运行 Dagster、不读写正式 Dagster instance。

验证结果：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_asset_check_incremental_governance.py \
  tests/test_run_contract_static_gates.py
```

结果：`56 passed`。

### P1：非分钟线 ordinary check retention dry-run

状态：dry-run 工具与本地测试已完成；正式 Dagster Postgres dry-run 尚未执行。

目标：

1. 复用分钟线 retention 的安全思想，但按非分钟线资产族重新设计 dry-run。
2. 不碰 repair/status/protected checks。
3. 对 `silver_index_daily`、`gold_market_major_indices_daily`、`stock_daily`、`adj_factor`、`market_breadth` 等资产生成 keep20 候选报告。

注意：存在大量 `partition is null` 历史 check，不能直接套分钟线按 partition 删除逻辑；必须先设计 latest-state 保护和时间窗口保护。

已落地：

1. 新增 `asset_check_event_retention.py` 与 `asset_check_event_retention_cli.py`，只提供只读 `dry-run`。
2. 默认候选范围排除股票分钟线资产；`prod_ch_share_fact_market_breadth_daily`、`lake_root_health` 进入 `excluded_asset_samples`，不进入候选。
3. keep window 按资产实际 partition set 分组保护最近 20 个动态分区。
4. 候选 SQL 排除 latest materialization、latest-bound checks、protected checks、keep window 和 null partition event。
5. 本地测试已覆盖只读 SQL、范围白名单、active runs 阻断、keep window 保护和无写入口门禁。

本地验证结果：`tests/test_asset_check_event_retention.py`、`tests/test_asset_check_incremental_governance.py`、`tests/test_run_contract_static_gates.py` 共 `64 passed`。

### P2：High-cardinality Index / Major Indices 治理

状态：已完成。

目标资产：

1. `gold_market_major_indices_daily`
2. `silver_index_daily`

改动方向：

1. 建立或补强 DuckDB lake readiness / batch selector。
2. 合并普通 check。
3. rank/seed 语义并入 `gold_market_major_indices_daily_seed_coverage_check`
   与 `gold_market_major_indices_daily_ranking_consistency_check`。
4. 只保留 latest/current compact check 和最近 20 日普通 check event。

落地事实：

- `silver_index_daily` 正式 Dagster checks 收敛为
  `contract/key_integrity/value_domain/registered_code_coverage` 4 个。
- `gold_market_major_indices_daily` 正式 Dagster checks 收敛为
  `contract/value_domain/seed_coverage/ranking_consistency` 4 个。
- `silver_index_daily_sensor` 与 `market_major_indices_daily_sensor` 热路径均走
  DuckDB lake readiness，不再用 Dagster latest-check 深扫选择目标日期。

### P3：Stock Daily / Suspend / Adj Factor 治理

状态：分阶段推进。P3A `adj_factor` 已完成；`stock_daily` 与
`suspend` 后续单独推进。

目标资产：

1. `raw_tushare_stock_daily`
2. `silver_stock_daily`
3. `raw_tushare_suspend_d`
4. `silver_stock_suspend_daily`
5. `raw_tushare_adj_factor`
6. `silver_adj_factor`

改动方向：

1. 统一 daily family lake readiness。
2. 合并 contract/key/value/coverage checks。
3. `silver_stock_lifecycle` 作为生命周期事实源，不允许各资产各自拼 raw_stock_basic。
4. 普通历史 check event 只保留最近 20 个交易日。

P3A 已落地事实：

- `raw_tushare_adj_factor` 正式 Dagster checks 收敛为
  `contract/key_value_integrity/partition_allowed` 3 个。
- `silver_adj_factor` 正式 Dagster checks 收敛为
  `contract/key_value_integrity/lifecycle_coverage/partition_allowed` 4 个。
- 旧细粒度 adj factor 函数只作为内部 helper，不再注册为 Dagster check。

### P4：Market Breadth / Return / Serving 治理

目标资产：

1. `gold_market_breadth_daily`
2. `gold_stock_return_distribution`
3. `ch_share_fact_market_breadth_daily`
4. `prod_ch_share_fact_market_breadth_daily`

改动方向：

1. 普通 contract check 合并。
2. 重算对账和跨系统对账转离线审计。
3. Dagster DB 保留 latest serving/current health 摘要。
4. `prod_ch_share_fact_market_breadth_daily` 不做历史补录，避免写入成本大于收益。

### P5：Full Snapshot / Basic Assets 合并收口

目标资产：

1. calendar。
2. stock basic / lifecycle / namechange / identity map。
3. index basic。
4. lake root health。

改动方向：

1. 低频资产不优先优化，但需要把 contract 类细项合并。
2. full snapshot 保留 latest 和少量最近运行，不保留全历史细项。

### P6：分钟线普通 check 合并与最终门禁

目标：

1. 在不破坏现有 keep20 和 batch readiness 的前提下，评估分钟线普通 check 是否进一步合并。
2. repair/status/completion checks 永久保护。
3. 完成全局静态门禁：新增 check 必须声明治理归属。

## 8. 开发门禁

后续每一阶段必须满足：

1. 先做只读 DB 统计和代码消费者审计。
2. 先改 readiness 消费口径，再退役旧 check。
3. 每个被合并或退役的 check 必须回答：语义迁到哪里、谁消费、如何验证。
4. 所有 sensor hot path 不得回流 Dagster event/check history 深扫。
5. 所有 DuckDB readiness 必须有完整 check 语义映射表。
6. 所有历史删除必须先 dry-run、备份、sample、post dry-run。
7. 不删除 `runs`、`run_tags`、`dynamic_partitions`、`instigators`。
8. 不删除 repair/status/completion checks。
9. 不执行 `VACUUM FULL`、`REINDEX`、`pg_repack`，除非单独维护窗口审批。

## 9. 需要后续拍板的问题

当前建议如下：

1. 普通非分钟线 daily partition checks 的历史保留窗口：建议统一最近 20 个对应交易日。
2. full snapshot 历史保留：建议保留 latest + 最近 5 次运行。
3. ClickHouse/local/gold 跨系统对账：建议日常只保留 latest 摘要 check，历史明细进入离线报告。
4. 合并 check 命名：建议新增合并后 check 必须以稳定业务语义命名，旧 check 不长期双轨。
5. 历史 `partition is null` check event：建议不做补 partition 的大规模 runless backfill；只用 retention 和新实现正确归属来解决。

## 10. 验收标准

专项完成后应满足：

1. Dagster DB check event 增长速度明显下降。
2. Asset UI Status 不再因为大量历史细粒度 check 卡顿。
3. 日常 sensor 不依赖历史 check event 深扫。
4. 当前资产健康状态仍能在 Dagster UI 看懂。
5. repair/status/completion 链路不受影响。
6. 数据质量语义没有降低，只是迁移到 DuckDB readiness、metadata 或离线审计。
7. 新增 check 必须有治理归属，不能再无上限膨胀。
