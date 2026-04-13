# BIYING 股票日线数据集开发说明

## 1. 目标与边界

- 目标：接入 BIYING 源股票日线接口，完成 **raw_biying** 层落库与运维可触发能力。
- 本期边界（严格）：
  - 仅实现建表与拉取写入 `raw_biying`。
  - 不做与 Tushare 的融合、比对、mapping、std/serving 发布。
  - 不修改现有 Tushare 数据链路行为。

## 2. 上游接口

- 文档：`https://api.biyingapi.com/hsstock/history/{dm}/{freq}/{adj_type}/{token}?st=...&et=...&lt=...`
- 本期固定：
  - `freq = d`（日线）
  - `adj_type in {n, f, b}`（不复权、前复权、后复权）
- 股票池来源：`raw_biying.stock_basic(dm, mc)`。

## 3. 表设计

### 3.1 Raw 表

- 表：`raw_biying.equity_daily_bar`
- 主键：`(dm, trade_date, adj_type)`
- 字段：
  - 业务字段：`dm`, `trade_date`, `adj_type`, `mc`, `quote_time`, `open`, `high`, `low`, `close`, `pre_close`, `vol`, `amount`, `suspend_flag`
  - 审计字段：`api_name`, `fetched_at`, `raw_payload`

### 3.2 索引

- `idx_raw_biying_equity_daily_bar_trade_date(trade_date)`
- `idx_raw_biying_equity_daily_bar_dm_trade_date(dm, trade_date)`

## 4. 同步逻辑

### 4.1 历史同步

- 任务：`sync_history.biying_equity_daily`
- 入参：`start_date`, `end_date`
- 执行流程：
  1. 读取 `raw_biying.stock_basic` 股票池。
  2. 对每个 `dm` 依次拉取 `adj_type = n/f/b`。
  3. 对日期区间按窗口切片请求（防止单次结果截断）。
  4. 归一化后 upsert 到 `raw_biying.equity_daily_bar`。

### 4.2 日常同步

- 任务：`sync_daily.biying_equity_daily`
- 入参：`trade_date`
- 执行流程：按单日窗口对全股票池拉取 `n/f/b` 三种复权类型。

## 5. 运维展示约定

- 进度文案使用业务语义，不暴露内部编码：
  - `复权类型=不复权/前复权/后复权`
- 进度定位字段：
  - `证券={dm} {mc}`
  - `窗口={start_date}~{end_date}`

## 6. 测试覆盖

- `tests/test_biying_connector.py`
  - 覆盖 `equity_daily_bar` URL 拼装与返回解析。
- `tests/test_sync_biying_equity_daily_service.py`
  - 覆盖历史同步主路径与增量参数校验。
- `tests/test_raw_multi_schema_mapping.py`
  - 覆盖新 raw 多源表 schema 与主键定义。
- `tests/test_ops_specs.py`
  - 覆盖新任务规格与参数暴露。
