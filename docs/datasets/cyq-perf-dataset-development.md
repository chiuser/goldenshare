# 每日筹码及胜率（cyq_perf）维护说明

更新时间：2026-09-10。代码已实现；本文说明 Prod 数据集现行链路，历史实测单列，不代表本次重新完成生产验收。仅 Tushare 单源，不引入 Std、多源融合或 Lake 导出。

## 1. 入口与实现依据

维护入口为 `cyq_perf.maintain`，主链是 DatasetDefinition → DatasetExecutionPlan → IngestionExecutor → Raw upsert，Ops 通过 TaskRun 编排与观测。旧 Sync V1 服务、sync registry 和 daily/history job spec 不再是开发路线。

| 事实 | 当前实现 |
| --- | --- |
| 定义、输入、日期与存储 | [market_equity.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py) 中 `cyq_perf` |
| 日期展开 | [unit_planner.py](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)，`generic / no_pool` |
| 源请求 | [request_builders.py](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py) 中 `_cyq_perf_params` |
| 分页、写入 | [source_client.py](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)、[writer.py](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py) 的 `raw_only_upsert` |
| Raw 直出视图 | [000124 迁移](/Users/congming/github/goldenshare/alembic/versions/20260803_000124_make_cyq_perf_nineturn_raw_views.py) |
| Ops 展示与工作流 | [dataset_catalog_views.py](/Users/congming/github/goldenshare/src/ops/catalog/dataset_catalog_views.py)、[action_catalog.py](/Users/congming/github/goldenshare/src/ops/action_catalog.py) |

## 2. 输入、执行与日期观测

| 维度 | 当前口径 |
| --- | --- |
| 运营输入 | 单日 `trade_date`，或闭区间 `start_date/end_date`；可选单个 `ts_code` |
| 单日执行 | 一个交易日 unit；请求 `trade_date=YYYYMMDD`，有代码过滤才附加 `ts_code` |
| 区间执行 | 按交易日历展开开市日，逐日请求；不将原始 start/end 直接传给源端，不按股票池展开 |
| 分页 | `offset_limit / page_limit=5000`；source client 追加 limit/offset，返回不足一页时结束，满页继续 |
| 观测 | `trade_open_day / every_open_day`，业务日期 `trade_date`，freshness 为 `continuous_open_day`，`audit_applicable=True` |
| Ops | 默认展示组 `technical_indicators / 技术指标`；底层 domain 为 `equity_market / 股票行情` |
| 调度 | 支持手动、普通自动任务与重试；已纳入 `daily_market_close_maintenance` |

分页没有 `has_more` 结束信号。恰好整页时还需要下一次请求确认结束，不能保证每个交易日永远只需 1～2 次调用。分页参数不开放为运营输入，任务进度使用实际日期、页和行数，不预先伪造总页数。

## 3. 字段与存储

显式请求 11 个字段：

`ts_code, trade_date, his_low, his_high, cost_5pct, cost_15pct, cost_50pct, cost_85pct, cost_95pct, weight_avg, winner_rate`。

- `raw_tushare.cyq_perf` 是物理表，主键为 `(ts_code, trade_date)`，另存 `api_name/fetched_at/raw_payload`；日期转 Date，九个数值字段转 Decimal。
- Raw 的日期及代码/日期索引保留；按 Raw DAO upsert，同键重复请求更新已有行。
- `core_serving.equity_cyq_perf` 是从 Raw 直出的普通 view，不再有独立 Serving 物理表、主键或索引，不进行第二次写入。
- 000124 同时处理 nineturn；不能把该共享迁移当成 cyq_perf 专属脚本重跑。它不使用 CASCADE，也不提供自动 downgrade。普通 view 不等于已配置数据库 DML 拒绝触发器。
- Definition 的拒绝策略为 `record_rejections`；验收仍须解释拒绝原因，不能把“任务成功”当成全量无拒绝证明。Ops 状态失败不得回滚已提交业务数据。

## 4. 源说明与历史实测

来源：doc_id=293，[本地每日筹码及胜率说明](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/特色数据/0293_每日筹码及胜率.md)。该文档记载数据从 2018 年开始、约 18～19 点更新、单次最大 5000 行；积分档位决定额度，不能将历史账户每日约 20,000 次当成当前账户保证。

**源说明差异保留：**本地文档将 `ts_code` 标为必填；原接入实测记录支持不传代码、按交易日拉全市场，当前 builder 也按这一行为实现。本轮没有重新请求 Tushare，不修改源文档或参数合同，也不把历史样本冒充当前接口验证。

以下保留原方案的 2026 年 4 月样本口径（统计范围截至 2026-04-16；原文没有完整执行时间戳）：

| 项目 | 历史记录 |
| --- | --- |
| 股票基础表 | distinct code 5,829；上市股票 5,505 |
| 2018-01-01～2026-04-16 日历 | 2,009 个交易日 |
| `trade_date=20260415`、不传代码 | 5,494 行；offset=0 返回 5,000，offset=5000 返回 494 |
| `ts_code=000001.SZ`、不传日期 | 返回 2,009 行 |
| 日线数据估算 | 2,006 个有数据交易日、日均 4,567.74 只股票，含分页约 2,827 次请求 |
| 当时策略比较 | 按股票约 5,733～5,829 次；按交易日约 2,827～4,018 次 |

这解释了选择 date-loop 的原因，不证明它在任意未来规模下都是最优。限额、网络、重试、整页终止探测和写库成本不包含在上述估算内。

## 5. 回归与验收边界

- [resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)：point/range、代码过滤及计划参数。
- [定义测试](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)：字段、日期、存储与能力。
- [Raw view 迁移测试](/Users/congming/github/goldenshare/tests/test_cyq_perf_nineturn_raw_view_migration.py)：共享迁移及视图定义。
- 源分页、Raw 行数、拒绝原因、view 读回、手动/自动任务及状态展示仍是实际变更后的验收项，不能用文档链接检查替代。

本轮仅校准文档；没有运行工作流、同步、迁移或生产查询。
