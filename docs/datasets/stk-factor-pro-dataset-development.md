# Tushare 股票技术面因子（专业版，`stk_factor_pro`）数据集开发说明

## 1. 目标与边界

- 目标：新增 `stk_factor_pro` 数据集，完成 Tushare 接口拉取、`raw_tushare` 落库、`core_serving` 服务层写入与 Ops 任务打通。
- 本期边界：
  - 纳入 `daily_market_close_sync` 每日工作流。
  - 支持日常同步、历史同步、按交易日回补三条路径。
  - 历史同步必须显式给时间参数（`trade_date` 或 `start_date+end_date`）。

## 2. 上游接口

- 文档：<https://tushare.pro/document/2?doc_id=328>
- API：`stk_factor_pro`
- 描述：股票日级技术面因子（含 bfq/qfq/hfq 口径）。
- 限量：单次最大 `10000` 行，可通过日期循环提取。
- 限速：每分钟不超过 `500` 次。

## 3. 参数与字段

### 3.1 上游输入参数

- `ts_code`（可选）
- `trade_date`（可选）
- `start_date`（可选）
- `end_date`（可选）
- `limit`（可选）
- `offset`（可选）

### 3.2 运维侧参数策略

- `sync_daily.stk_factor_pro`：`trade_date`，可选 `ts_code`
- `sync_history.stk_factor_pro`：`trade_date` 或 `start_date + end_date`，可选 `ts_code`
- `backfill_by_trade_date.stk_factor_pro`：`start_date + end_date`，可选 `ts_code`，支持 `offset/limit`

### 3.3 输出字段落库策略

- 全量输出字段落库，字段集与 `STK_FACTOR_PRO_FIELDS` 保持一致（`227` 列，含 `ts_code/trade_date`）。
- 数值列统一使用 `DOUBLE PRECISION`（SQLAlchemy `Float(53)`），降低宽表存储与写入成本。

## 4. 落库设计

### 4.1 原始层

- 表：`raw_tushare.stk_factor_pro`
- 主键：`(ts_code, trade_date)`
- 索引：
  - `idx_raw_tushare_stk_factor_pro_trade_date`
  - `idx_raw_tushare_stk_factor_pro_ts_code_trade_date`
- 审计字段：`api_name`, `fetched_at`, `raw_payload`

### 4.2 服务层

- 表：`core_serving.equity_factor_pro`
- 主键：`(ts_code, trade_date)`
- 索引：
  - `idx_equity_factor_pro_trade_date`
  - `idx_equity_factor_pro_ts_code_trade_date`
- 系统字段：`source`, `created_at`, `updated_at`

## 5. 同步策略

### 5.1 日常同步（INCREMENTAL）

- 必传 `trade_date`。
- 单交易日请求，内部 `limit/offset` 分页直至无数据。

### 5.2 历史同步（FULL）

- 支持：
  1. 单日（`trade_date`）
  2. 区间（`start_date + end_date`）
- 区间模式按交易日历扇出到交易日，再逐日分页拉取。
- 若区间早于可用起点，返回可读提示，不报错中断。

## 6. Ops 打通

- JobSpec：
  - `sync_daily.stk_factor_pro`
  - `sync_history.stk_factor_pro`
  - `backfill_by_trade_date.stk_factor_pro`
- Freshness：
  - `dataset_key`: `stk_factor_pro`
  - `display_name`: `股票技术面因子(专业版)`
  - `domain`: `股票`
  - `observed_date_column`: `trade_date`
- 工作流：
  - `daily_market_close_sync` 新增步骤 `sync_daily.stk_factor_pro`

## 7. 测试覆盖

- `tests/test_sync_stk_factor_pro_service.py`
  - 增量参数校验
  - 单日分页与写入
  - 历史同步显式时间校验
  - 区间按交易日历扇出
- `tests/test_sync_registry.py`
  - 资源注册校验
- `tests/test_ops_specs.py` / `tests/web/test_ops_catalog_api.py`
  - JobSpec 参数契约与目录输出
- `tests/test_fields_constants.py`
  - `STK_FACTOR_PRO_FIELDS` 常量覆盖
- `tests/test_extended_models.py`
  - `equity_factor_pro` 主键与索引

