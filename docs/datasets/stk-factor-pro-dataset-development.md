# Tushare 股票技术面因子（专业版，`stk_factor_pro`）数据集开发说明

## 1. 目标与边界

- 目标：新增 `stk_factor_pro` 数据集，完成 Tushare 接口拉取、`raw_tushare` 落库、`core_serving` 服务层直出与 Ops 任务打通。
- 本期边界：
  - 纳入 `daily_market_close_maintenance` 每日工作流。
  - 支持单日维护与区间维护。
  - 维护动作必须显式给时间参数（`trade_date` 或 `start_date+end_date`）。

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

- `stk_factor_pro.maintain`：`trade_date` 或 `start_date + end_date`，可选 `ts_code`

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

- 入口：`core_serving.equity_factor_pro`
- 形态：普通 view，直接读取 `raw_tushare.stk_factor_pro`
- 系统字段：view 中补充 `source`, `created_at`, `updated_at`，用于保持现有服务层查询模型可读
- 写入策略：不再写第二份 serving 物理表，writer 只执行 `raw_only_upsert`

## 5. 同步策略

### 5.1 单日维护

- 必传 `trade_date`。
- 执行前必须先确认当日 `core.equity_adj_factor` 已更新；否则失败并提示“先更新复权因子”。
- 单交易日请求，内部 `limit/offset` 分页直至无数据。

### 5.2 区间维护

- 支持：
  1. 单日（`trade_date`）
  2. 区间（`start_date + end_date`）
- 区间模式按交易日历扇出到交易日，再逐日分页拉取。
- 每个目标交易日都必须先通过复权因子门禁。
- 若区间早于可用起点，返回可读提示，不报错中断。

## 6. Ops 打通

- DatasetDefinition action：
  - `stk_factor_pro.maintain`
- Freshness：
  - `dataset_key`: `stk_factor_pro`
  - `display_name`: `股票技术面因子(专业版)`
  - `domain`: `股票`
  - `observed_date_column`: `trade_date`
- 工作流：
  - `daily_market_close_maintenance` 新增步骤 `stk_factor_pro.maintain`

## 7. 测试覆盖

- `tests/test_dataset_action_resolver.py`
  - 单日/区间执行计划
  - 复权因子门禁
  - 区间按交易日历扇出
- `tests/test_dataset_definition_registry.py`
  - DatasetDefinition 存储口径、时间模型、完整性口径
- `tests/test_dataset_runtime_registry.py`
  - runtime registry 注册校验
- `tests/test_ops_action_catalog.py` / `tests/web/test_ops_catalog_api.py`
  - action catalog 参数契约与目录输出
- `tests/test_fields_constants.py`
  - `STK_FACTOR_PRO_FIELDS` 常量覆盖
- `tests/test_dataset_writer_stk_factor_pro.py`
  - 只写 raw DAO，不写 serving DAO
