# 运维工作流目录与实现清单（Workflow Catalog v1）

> 更新时间：2026-04-11  
> 代码基线：`src/operations/specs/registry.py`、`src/operations/runtime/dispatcher.py`  
> 目标：把当前所有复合型任务（workflow）做成可审计的实现清单，避免“记忆驱动运维”。

## 1. 当前工作流总览（共 5 个）

| 工作流 Key | 名称 | 支持自动调度 | 支持手动执行 | 默认调度策略 |
|---|---|---:|---:|---|
| `board_reference_refresh` | 板块主数据刷新 | 是 | 是 | 无 |
| `daily_market_close_sync` | 每日收盘后同步 | 是 | 是 | `trading_day_close` |
| `index_extension_backfill` | 指数扩展数据补齐 | 否 | 是 | 无 |
| `index_kline_sync_pipeline` | 指数K线全链路同步 | 否 | 是 | 无 |
| `reference_data_refresh` | 基础主数据刷新 | 是 | 是 | 无 |

来源：`WORKFLOW_SPEC_REGISTRY`（按 key 排序输出）。

## 2. 工作流运行机制（代码级）

### 2.1 入口与分发

- 调度/手动创建执行记录后，worker 会在 dispatcher 中根据 `spec_type=workflow` 进入 `_dispatch_workflow`。
- 每个工作流 step 会被落到 `ops.job_execution_step`，并写入 `step_started / step_succeeded / step_failed` 事件。

参考：
- `src/operations/runtime/dispatcher.py` `_dispatch_workflow`

### 2.2 步骤参数合成规则

每个 step 的执行参数是：
1. 先取 workflow 级执行参数（`execution.params_json`）
2. 再叠加 step 的 `default_params`
3. 同名字段以 step 默认值覆盖

这意味着 step 可以“局部改写”工作流公共参数。

### 2.3 失败语义

- 某一步失败时：
  - 若前面已有成功步骤，整体状态为 `partial_success`
  - 若一步都没成功，整体状态为 `failed`
- 取消请求会在当前单元结束后转为 `canceled`

## 3. 工作流明细

## 3.1 `reference_data_refresh`（基础主数据刷新）

- 描述：刷新股票、交易日历、ETF 与指数基础信息。
- 支持自动调度：是
- 支持手动执行：是
- 支持参数：无
- 适用场景：主数据初始化、主数据质量巡检后的补刷。

步骤（顺序执行）：

| 序号 | step_key | 显示名 | job_key | depends_on | default_params |
|---:|---|---|---|---|---|
| 1 | `stock_basic` | 股票主数据 | `sync_history.stock_basic` | - | `{}` |
| 2 | `trade_cal` | 交易日历 | `sync_history.trade_cal` | - | `{}` |
| 3 | `etf_basic` | ETF 基本信息 | `sync_history.etf_basic` | - | `{}` |
| 4 | `etf_index` | ETF 基准指数列表 | `sync_history.etf_index` | - | `{}` |
| 5 | `index_basic` | 指数基本信息 | `sync_history.index_basic` | - | `{}` |
| 6 | `hk_basic` | 港股列表 | `sync_history.hk_basic` | - | `{}` |
| 7 | `us_basic` | 美股列表 | `sync_history.us_basic` | - | `{}` |

## 3.2 `daily_market_close_sync`（每日收盘后同步）

- 描述：覆盖日线、日指标、资金流、榜单与基金/指数日线的每日同步工作流。
- 支持自动调度：是
- 支持手动执行：是
- 默认调度策略：`trading_day_close`
- 支持参数：无（各步骤按自身 job 规则消费参数）
- 适用场景：盘后日常批处理。

步骤（顺序执行）：

| 序号 | step_key | 显示名 | job_key |
|---:|---|---|---|
| 1 | `daily` | 股票日线 | `sync_daily.daily` |
| 2 | `equity_price_restore_factor` | 价格还原因子 | `sync_daily.equity_price_restore_factor` |
| 3 | `equity_indicators` | 股票技术指标 | `sync_daily.equity_indicators` |
| 4 | `adj_factor` | 复权因子 | `sync_daily.adj_factor` |
| 5 | `daily_basic` | 股票日指标 | `sync_daily.daily_basic` |
| 6 | `moneyflow` | 资金流 | `sync_daily.moneyflow` |
| 7 | `limit_list` | 涨跌停榜 | `sync_daily.limit_list_d` |
| 8 | `top_list` | 龙虎榜 | `sync_daily.top_list` |
| 9 | `block_trade` | 大宗交易 | `sync_daily.block_trade` |
| 10 | `fund_daily` | 基金日线 | `sync_daily.fund_daily` |
| 11 | `fund_adj` | 基金复权因子 | `sync_daily.fund_adj` |
| 12 | `index_daily` | 指数日线 | `sync_daily.index_daily` |
| 13 | `ths_daily` | 同花顺板块行情 | `sync_daily.ths_daily` |
| 14 | `dc_index` | 东方财富概念板块 | `sync_daily.dc_index` |
| 15 | `dc_member` | 东方财富板块成分 | `sync_daily.dc_member` |
| 16 | `dc_daily` | 东方财富板块行情 | `sync_daily.dc_daily` |
| 17 | `ths_hot` | 同花顺热榜 | `sync_daily.ths_hot` |
| 18 | `dc_hot` | 东方财富热榜 | `sync_daily.dc_hot` |
| 19 | `kpl_list` | 开盘啦榜单 | `sync_daily.kpl_list` |
| 20 | `limit_list_ths` | 同花顺涨跌停榜单 | `sync_daily.limit_list_ths` |
| 21 | `limit_step` | 涨停天梯 | `sync_daily.limit_step` |
| 22 | `limit_cpt_list` | 最强板块统计 | `sync_daily.limit_cpt_list` |
| 23 | `kpl_concept_cons` | 开盘啦题材成分 | `sync_daily.kpl_concept_cons` |

## 3.3 `board_reference_refresh`（板块主数据刷新）

- 描述：刷新同花顺板块主数据与同花顺板块成分。
- 支持自动调度：是
- 支持手动执行：是
- 支持参数：无
- 适用场景：板块体系补全、板块成分定期刷新。

步骤（顺序执行）：

| 序号 | step_key | 显示名 | job_key |
|---:|---|---|---|
| 1 | `ths_index` | 同花顺概念和行业指数 | `sync_history.ths_index` |
| 2 | `ths_member` | 同花顺板块成分 | `sync_history.ths_member` |

## 3.4 `index_extension_backfill`（指数扩展数据补齐）

- 描述：批量回补指数日线、周线、月线、日指标和成分权重。
- 支持自动调度：否
- 支持手动执行：是
- 支持参数：无
- 适用场景：历史修复、指数扩展数据一次性补齐。

步骤（顺序执行）：

| 序号 | step_key | 显示名 | job_key |
|---:|---|---|---|
| 1 | `index_daily` | 指数日线 | `backfill_index_series.index_daily` |
| 2 | `index_weekly` | 指数周线 | `backfill_index_series.index_weekly` |
| 3 | `index_monthly` | 指数月线 | `backfill_index_series.index_monthly` |
| 4 | `index_daily_basic` | 指数日指标 | `backfill_index_series.index_daily_basic` |
| 5 | `index_weight` | 指数权重 | `backfill_index_series.index_weight` |

## 3.5 `index_kline_sync_pipeline`（指数K线全链路同步）

- 描述：按日线→周线→月线→服务表补齐顺序执行。
- 支持自动调度：否
- 支持手动执行：是
- 支持参数：`start_date`、`end_date`
- 适用场景：指定区间重建指数 K 线链路。

步骤（顺序执行）：

| 序号 | step_key | 显示名 | job_key |
|---:|---|---|---|
| 1 | `sync_index_daily` | 同步指数日线 | `backfill_index_series.index_daily` |
| 2 | `sync_index_weekly` | 同步指数周线 | `backfill_index_series.index_weekly` |
| 3 | `sync_index_monthly` | 同步指数月线 | `backfill_index_series.index_monthly` |
| 4 | `rebuild_index_serving` | 补齐指数服务表 | `maintenance.rebuild_index_kline_serving` |

## 4. 运维排查建议（面向值守）

1. 先看 step 粒度状态，不要直接看总状态。
2. `partial_success` 说明前置步骤已有数据写入，重试前要确认幂等策略。
3. 带维护动作的 workflow（如 `index_kline_sync_pipeline`）失败时，要区分“采集失败”还是“重建失败”。
4. 盘后工作流建议按 step 输出进度，避免只看 rows_fetched/rows_written。

## 5. 变更治理规则（必须遵守）

新增或修改 workflow 时，必须同步完成以下事项：

1. 更新 `src/operations/specs/registry.py` 的 `WORKFLOW_SPEC_REGISTRY`。
2. 更新本文档（至少更新总览表 + 明细步骤）。
3. 更新文档索引 `docs/README.md`（如为新增文档或改名）。
4. 增加/更新测试：
   - 规格层测试（支持调度、支持手动、参数）
   - 运行时测试（成功/失败/取消语义）
5. 提交信息中明确写明“workflow 变更范围”，禁止隐式变更。
