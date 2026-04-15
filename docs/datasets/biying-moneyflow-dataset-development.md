# BIYING 资金流向数据集开发说明

## 1. 目标与边界

- 目标：接入 BIYING 资金流向接口，完成 `raw_biying.moneyflow` 的建表、拉取、落库与运维可触发能力。
- 本期边界（严格）：
  - 仅实现 BIYING 源拉取与 raw 层存储。
  - 不做和 Tushare `moneyflow` 的字段对齐、融合、std、serving。
  - 不改变现有 Tushare 资金流向链路。

## 2. 上游接口

- 接口：`/hsstock/history/transaction/{dm}/{token}?st=YYYYMMDD&et=YYYYMMDD&lt=...`
- 股票池来源：`raw_biying.stock_basic(dm, mc)`。
- 请求参数：
  - `dm`：BIYING 股票代码（本期直接使用 `dm` 原值）。
  - `st` / `et`：区间日期。
  - `lt`：本期不用于历史回补，避免结果截断风险。
- 无数据返回：`{"error":"数据不存在"}`，按空结果处理，不视作任务失败。

## 3. 表设计

### 3.1 Raw 表

- 表：`raw_biying.moneyflow`
- 主键：`(dm, trade_date)`
- 审计字段：`api_name`, `fetched_at`, `raw_payload`
- 数据字段：按 BIYING 返回字段全量落库（保留原字段名），包含：
  - 主买/主卖统计：`zmbzds`, `zmszds`, `zmbzdszl`, `zmszdszl`, `cjbszl`
  - 动向指标：`dddx`, `zddy`, `ddcf`
  - 各档位成交金额/成交量/成交总额/成交量增量（`...cje`, `...cjl`, `...cjzl`, `...cjzlv` 全量）

### 3.2 数值类型

- 计数字段：`BIGINT`
- 金额/比例字段：`NUMERIC(30, 4)`（动向指标 `dddx/zddy/ddcf` 使用 `NUMERIC(18,4)`）
- 时间字段：
  - `quote_time`：来自接口 `t`
  - `trade_date`：`quote_time.date()`

### 3.3 索引

- `idx_raw_biying_moneyflow_trade_date(trade_date)`
- `idx_raw_biying_moneyflow_dm_trade_date(dm, trade_date)`

## 4. 同步逻辑

### 4.1 历史同步

- 任务：`sync_history.biying_moneyflow`
- 入参：`start_date`, `end_date`
- 策略：
  1. 从 `raw_biying.stock_basic` 读取股票池；
  2. 区间按 100 天窗口拆分；
  3. 按 `dm × 窗口` 扇出请求并 upsert；
  4. 窗口内不传 `lt`。

### 4.2 日常同步

- 任务：`sync_daily.biying_moneyflow`
- 入参：`trade_date`
- 策略：把 `trade_date` 映射为 `st=et` 单日，按股票池扇出请求。

## 5. 运维展示约定

- 进度文案：
  - `证券={dm} {mc} 窗口={start}~{end} 获取={fetched} 写入={written}`
- 数据状态：
  - 数据集 key：`biying_moneyflow`
  - 展示名：`BIYING 资金流向`
  - 观测日期列：`trade_date`

## 6. 测试覆盖

- `tests/test_biying_connector.py`
  - 覆盖 `moneyflow` URL 拼装、空数据响应处理。
- `tests/test_sync_biying_moneyflow_service.py`
  - 覆盖 FULL 路径、INCREMENTAL 参数校验、字段归一化。
- `tests/test_raw_multi_schema_mapping.py`
  - 覆盖 `raw_biying.moneyflow` 的 schema 与主键。
- `tests/test_ops_specs.py`
  - 覆盖 `sync_history.biying_moneyflow` / `sync_daily.biying_moneyflow` 规格。
