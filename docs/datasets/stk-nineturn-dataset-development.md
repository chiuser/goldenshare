# Tushare 神奇九转指标（`stk_nineturn`）数据集开发说明

## 1. 目标与边界

- 目标：新增 `stk_nineturn` 数据集，完成 Tushare 接口拉取、`raw_tushare` 落库、`core_serving` 对外服务与 Ops 任务打通。
- 本期边界：
  - 不加入 `daily_market_close_sync` 工作流（按当前评审结论先不推进）。
  - `sync_history.stk_nineturn` 必须显式指定时间（`trade_date` 或 `start_date+end_date`），禁止无时间全量。

## 2. 上游接口信息

- 接口文档：<https://tushare.pro/document/2?doc_id=364>
- API：`stk_nineturn`
- 描述：神奇九转（TD 序列）指标，日线级指标每天约 21:00 更新。
- 数据起点：`2023-01-01`
- 限量：单次最多约 `10000` 行，可通过代码+日期循环获取历史。

## 3. 参数设计

### 3.1 上游输入参数

- `ts_code`（可选）
- `trade_date`（可选）
- `start_date`（可选）
- `end_date`（可选）
- `freq`（可选）

### 3.2 运维侧参数策略（面向用户）

- `sync_daily.stk_nineturn`
  - 参数：`trade_date`，可选 `ts_code`
- `sync_history.stk_nineturn`
  - 参数：`trade_date` 或 `start_date + end_date`，可选 `ts_code`
- `freq` 不暴露到用户交互层，后端固定传 `D`（日线）。
- 历史同步若不带时间参数直接报错（避免误触发全量）。

## 4. 输出字段（全量落库）

- `ts_code`
- `trade_date`
- `freq`
- `open`
- `high`
- `low`
- `close`
- `vol`
- `amount`
- `up_count`
- `down_count`
- `nine_up_turn`
- `nine_down_turn`

## 5. 落库设计

### 5.1 Raw 层

- 表：`raw_tushare.stk_nineturn`
- 主键：`(ts_code, trade_date)`
- 索引：`idx_raw_tushare_stk_nineturn_trade_date`
- 审计字段：`api_name`, `fetched_at`, `raw_payload`

### 5.2 Serving 层

- 表：`core_serving.equity_nineturn`
- 主键：`(ts_code, trade_date)`
- 索引：`idx_equity_nineturn_trade_date`
- 系统字段：`created_at`, `updated_at`

## 6. 同步策略

### 6.1 日常同步（INCREMENTAL）

- 必须传 `trade_date`。
- 请求参数：`trade_date + freq=daily (+ ts_code 可选)`。
- 单日请求内部使用 `limit/offset` 分页，避免大盘数据截断。

### 6.2 历史同步（FULL）

- 支持两种模式：
  1. `trade_date` 单日
  2. `start_date + end_date` 区间
- 区间模式按交易日历逐日扇出执行；每个交易日内部分页拉取。
- 自动截断到接口有效起点 `2023-01-01`。
- 若区间早于有效起点或区间内无交易日，返回可读提示，不报错中断任务链路。

## 7. Ops 接入

- JobSpec：
  - `sync_daily.stk_nineturn`
  - `sync_history.stk_nineturn`
  - `backfill_by_trade_date.stk_nineturn`
- Freshness 元数据：
  - `dataset_key`: `stk_nineturn`
  - `display_name`: `神奇九转指标`
  - `domain`: `股票`
  - `cadence`: `daily`
  - `observed_date_column`: `trade_date`

## 8. 测试清单

- `tests/test_sync_stk_nineturn_service.py`
  - 增量参数校验
  - 历史同步显式时间校验
  - 区间扇出与进度文案
  - 单日分页与落库
- `tests/test_sync_registry.py`
  - 注册表包含 `stk_nineturn`
- `tests/test_ops_specs.py`
  - 新任务参数契约
- `tests/test_fields_constants.py`
  - `STK_NINETURN_FIELDS` 字段常量
- `tests/test_extended_models.py`
  - `equity_nineturn` 主键与索引
- `tests/test_history_backfill_service.py`
  - `backfill_by_trade_date.stk_nineturn` 路径可执行
