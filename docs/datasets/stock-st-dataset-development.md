# Tushare ST股票列表（`stock_st`）数据集开发说明

## 1. 目标与边界

- 目标：新增 `stock_st` 数据集，完成 Tushare 接口拉取、`raw_tushare` 落库、`core_serving` 对外服务与 Ops 运维打通。
- 本期边界：
  - 按交易日期维度同步，区间模式必须按交易日历扇出，不按自然日遍历。
  - `stock_st.maintain` 必须显式传时间参数（`trade_date` 或 `start_date+end_date`），禁止无时间全量。
  - 数据起点受上游限制为 `2016-01-01`，更早日期不做补齐。

## 2. 上游接口信息

- 接口文档：<https://tushare.pro/document/2?doc_id=397>
- API：`stock_st`
- 描述：获取 ST 股票列表，可按交易日期获取历史每日 ST 列表。
- 权限：3000 积分起。
- 更新频率：每天约 `09:20` 更新。
- 限量：单次最多 `1000` 行，可分页循环提取。

## 3. 参数设计

### 3.1 上游输入参数

- `ts_code`（可选）
- `trade_date`（可选）
- `start_date`（可选）
- `end_date`（可选）
- `limit`（可选，分页）
- `offset`（可选，分页）

### 3.2 运维侧参数策略（面向用户）

- `stock_st.maintain`
  - 参数：`trade_date` 或 `start_date + end_date`，可选 `ts_code`
- 分页参数 `limit/offset` 不暴露给用户，服务内部固定循环分页。
- 历史同步不允许无时间参数启动。

### 3.3 输出字段（全量落库）

- `ts_code`
- `name`
- `trade_date`
- `type`
- `type_name`

## 4. 落库设计

### 4.1 原始层

- 表：`raw_tushare.stock_st`
- 主键建议：`(ts_code, trade_date, type)`
  - 设计原因：同一标的同一交易日理论上可能存在不同风险类型状态，保守采用三列主键避免覆盖。
- 字段：`name`, `type`, `type_name`
- 审计字段：`api_name`, `fetched_at`, `raw_payload`
- 索引建议：
  - `idx_raw_tushare_stock_st_trade_date(trade_date)`
  - `idx_raw_tushare_stock_st_ts_code(ts_code)`

### 4.2 服务层

- 表：`core_serving.equity_stock_st`
- 主键：`(ts_code, trade_date, type)`
- 字段：`name`, `type`, `type_name`
- 系统字段：`created_at`, `updated_at`
- 索引建议：
  - `idx_equity_stock_st_trade_date(trade_date)`
  - `idx_equity_stock_st_ts_code(ts_code)`

## 5. 维护实现策略

### 5.1 单日维护

- 必传 `trade_date`。
- 请求参数：`trade_date (+ ts_code 可选)`。
- 单日请求内部使用 `limit=1000, offset` 分页，直到不足 1000 或无数据。

### 5.2 区间维护

- 允许：
  - 单日（`trade_date`）
  - 区间（`start_date + end_date`）
- 区间模式按交易日历开市日扇出（`trade_calendar.is_open=1`），逐交易日请求。
- 区间会裁剪到接口最早日期 `2016-01-01`。
- 若区间内无交易日，返回可读提示，不报错中断。

## 6. Ops 打通设计

- DatasetDefinition action：
  - `stock_st.maintain`
- Freshness 元数据建议：
  - `dataset_key`: `stock_st`
  - `display_name`: `ST股票列表`
  - `domain`: `股票`
  - `cadence`: `daily`
  - `observed_date_column`: `trade_date`

### 6.1 工作流接入

- 已纳入 `daily_market_close_maintenance` 工作流，步骤键：`stock_st`，动作键：`stock_st.maintain`。

## 7. 测试覆盖清单

- `tests/test_sync_stock_st_service.py`
  - 增量参数校验（`trade_date` 必填）
  - 单日分页循环（`limit/offset`）
  - 维护动作显式时间约束
  - 区间按交易日历扇出
  - 起始日期裁剪到 `2016-01-01`
- `tests/test_sync_registry.py`
  - 注册表包含 `stock_st`
- `tests/test_ops_action_catalog.py`
  - `stock_st.maintain` 参数契约
- `tests/test_fields_constants.py`
  - `STOCK_ST_FIELDS` 字段常量
- `tests/test_extended_models.py`
  - `raw_tushare.stock_st` 与 `core_serving.equity_stock_st` 主键/索引校验

## 8. 风险与注意事项

- 上游单日返回量可能触发分页，必须严格分页直到拉完，避免截断。
- `type/type_name` 口径属于业务语义字段，必须原样落库，不做值映射。
- 若区间很大，按交易日扇出会产生较多请求，应复用现有取消信号与进度上报机制，保证可中断、可观测。

## 9. 历史缺失日期补数专题

`stock_st` 已确认存在“源站日快照为空，导致历史交易日整日缺失”的专题问题。  
该问题不通过常规 `stock_st.maintain` 主链修复，而通过单独的历史重建方案处理，详见：

- [ST 股票列表历史缺失日期重建方案 v1（待评审）](/Users/congming/github/goldenshare/docs/datasets/stock-st-missing-date-reconstruction-plan-v1.md)
