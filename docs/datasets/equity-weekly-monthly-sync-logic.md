# 股票周/月线同步逻辑说明（stk_weekly_monthly / stk_week_month_adj）

## 1. 适用数据集

- `stk_period_bar_week`（股票周线）
- `stk_period_bar_month`（股票月线）
- `stk_period_bar_adj_week`（股票复权周线）
- `stk_period_bar_adj_month`（股票复权月线）

对应接口：

- `stk_weekly_monthly`
- `stk_week_month_adj`

## 2. 参数与锚点规则

### 2.1 日常同步（`sync_daily.*`）

- 运行入口：`sync_daily.<resource>`
- 参数：`trade_date`（可显式传入，不传时由调度层兜底）
- 调度兜底：若未传 `trade_date`，由调度器取“默认交易所最近开市日”。
- 重要说明：
  - 目前周/月线资源未加入自动任务可选列表（`DAILY_SYNC_RESOURCES`），因此默认不会出现在自动任务创建页。
  - 但底层 `sync_daily` 任务链路本身可执行。

### 2.2 历史回补（`backfill_equity_series.*`）

- 运行入口：`backfill_equity_series.<resource>`
- 参数：`start_date`、`end_date`（可带 `offset/limit` 做分段）
- 执行锚点（本次已统一优化）：
  - 周线/复权周线：在 `[start_date, end_date]` 内按自然周生成每周五日期序列。
  - 月线/复权月线：在 `[start_date, end_date]` 内按自然月生成每月最后一天日期序列。
- 每个锚点日期调用一次对应 `run_incremental(trade_date=...)`。

## 3. 与交易日历关系

### 3.1 周/月线回补不做交易日校验

根据接口特性，周/月线请求锚点应使用“周五/每月最后一天”，该日期可能是休市日。  
因此周/月线回补链路不再基于交易日历筛选开市日，也不校验“是否交易日”。

### 3.2 其他数据集不受影响

- `daily`、`adj_factor` 仍按交易日历开市日逐日回补。
- 基金、榜单、板块等其它回补模式保持原有逻辑。

## 4. 执行流程（回补）

1. 接收 `start_date/end_date`。
2. 依据资源类型生成锚点序列（周五或月末）。
3. 应用 `offset/limit`。
4. 对每个锚点执行 `service.run_incremental(trade_date=anchor)`。
5. 累加 `rows_fetched/rows_written`，写入进度消息：
   - `resource: i/total trade_date=YYYY-MM-DD fetched=x written=y`
6. 完成后刷新资源状态快照。

## 5. 当前实现位置

- 回补主逻辑：`src/operations/services/history_backfill_service.py`
- 周/月线 sync service：
  - `src/foundation/services/sync/sync_stk_period_bar_week_service.py`
  - `src/foundation/services/sync/sync_stk_period_bar_month_service.py`
  - `src/foundation/services/sync/sync_stk_period_bar_adj_week_service.py`
  - `src/foundation/services/sync/sync_stk_period_bar_adj_month_service.py`

## 6. 测试覆盖

已覆盖以下关键场景：

- 周线回补走“周五锚点”且不读取交易日历开市日。
- 月线回补走“月末锚点”且不读取交易日历开市日。
- 周/月线（含复权）回补进度与计数正确。

对应测试文件：`tests/test_history_backfill_service.py`
