# Tushare 每日涨跌停价格（`stk_limit`）数据集开发说明

## 1. 目标与边界

- 目标：新增 `stk_limit` 数据集，完成 Tushare 接口拉取、`raw_tushare` 落库、`core_serving` 对外服务与 Ops 运维打通。
- 本期边界：
  - 纳入现有工作流 `daily_market_close_maintenance`（收盘后自动流程覆盖）。
  - 维护动作必须显式传时间参数（`trade_date` 或 `start_date+end_date`），禁止“无时间全量”。

## 2. 上游接口

- 文档：<https://tushare.pro/document/2?doc_id=183>
- API：`stk_limit`
- 描述：获取全市场每日涨跌停价格（A/B 股与基金）。
- 限制：单次最多约 5800 行，支持循环调取。

## 3. 参数与字段

### 3.1 输入参数（上游）

- `ts_code`（可选）
- `trade_date`（可选）
- `start_date`（可选）
- `end_date`（可选）
- `limit`（可选）
- `offset`（可选）

### 3.2 本期运维参数策略

- `stk_limit.maintain`：`trade_date` 或 `start_date+end_date`，可选 `ts_code`
- 维护动作禁止无时间参数启动。

### 3.3 输出字段（全量落库）

- `trade_date`
- `ts_code`
- `pre_close`
- `up_limit`
- `down_limit`

## 4. 落库设计

### 4.1 原始层

- 表：`raw_tushare.stk_limit`
- 主键：`(ts_code, trade_date)`
- 字段：`pre_close`, `up_limit`, `down_limit`
- 审计字段：`api_name`, `fetched_at`, `raw_payload`
- 索引：`idx_raw_tushare_stk_limit_trade_date(trade_date)`

### 4.2 服务层

- 表：`core_serving.equity_stk_limit`
- 主键：`(ts_code, trade_date)`
- 字段：`pre_close`, `up_limit`, `down_limit`
- 系统字段：`created_at`, `updated_at`
- 索引：`idx_equity_stk_limit_trade_date(trade_date)`

## 5. 同步实现策略

### 5.1 日常同步（INCREMENTAL）

- 必传 `trade_date`。
- 按单交易日请求，使用 `limit/offset` 分页拉取直至无数据。

### 5.2 历史同步（FULL）

- 允许：
  - 单日（`trade_date`）
  - 区间（`start_date+end_date`）
- 区间模式按交易日历扇出到每日（非一把区间请求），每个交易日内部再分页，避免单次返回上限导致截断。
- 若区间内无交易日，返回可读提示，不报错中断。

## 6. Ops 打通

- DatasetDefinition action：
  - `stk_limit.maintain`
- Freshness 元数据：
  - `dataset_key`: `stk_limit`
  - `display_name`: `每日涨跌停价格`
  - `domain`: `股票`
  - `observed_date_column`: `trade_date`

## 7. 测试覆盖

- `tests/test_sync_stk_limit_service.py`
  - 增量参数校验
  - 分页与落库
  - 历史同步显式时间约束
  - 区间按交易日历扇出
- `tests/test_sync_registry.py`
  - 注册表包含 `stk_limit`
- `tests/test_ops_action_catalog.py`
  - action catalog 参数契约
- `tests/test_fields_constants.py`
  - `STK_LIMIT_FIELDS` 常量覆盖
- `tests/test_extended_models.py`
  - `equity_stk_limit` 主键与索引
