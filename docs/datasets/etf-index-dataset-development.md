# ETF 基准指数列表（`etf_index`）数据集开发说明

## 1. 背景与目标

为数据基座新增 `etf_index` 数据集（ETF 基准指数列表），并打通到运营管理台，满足：

- 字段全量落库（raw/core）。
- 可在运营台手动执行与自动调度。
- 归类到“基础主数据”。
- 数据状态页按“最近同步日期”观测（该数据集无交易日主键）。

## 2. 接口来源

- Tushare 文档：`ETF基准指数列表`
- 文档链接：<https://tushare.pro/document/2?doc_id=386>
- API 名称：`etf_index`

## 3. 接口字段与输入参数

### 3.1 输入参数（上游能力）

- `ts_code`：指数代码（可选）
- `pub_date`：发布日期（YYYYMMDD，可选）
- `base_date`：指数基期（YYYYMMDD，可选）

### 3.2 本期运营侧参数策略

按产品约束，运营台不暴露“指定日期”类参数，因此本期 `sync_history.etf_index` 仅暴露：

- `ts_code`（可选）

`pub_date`、`base_date` 保留在同步服务参数构建能力中，但不在运营台表单中展示。

### 3.3 输出字段（全量落库）

- `ts_code`
- `indx_name`
- `indx_csname`
- `pub_party_name`
- `pub_date`
- `base_date`
- `bp`
- `adj_circle`

## 4. 表设计

### 4.1 `raw.etf_index`

- 业务字段：与接口输出字段 1:1 对齐
- 审计字段：
  - `api_name`（默认 `etf_index`）
  - `fetched_at`
  - `raw_payload`

### 4.2 `core.etf_index`

- 业务字段：与接口输出字段 1:1 对齐
- 系统字段：
  - `created_at`
  - `updated_at`
- 索引：
  - `idx_etf_index_pub_date`
  - `idx_etf_index_base_date`

## 5. 当前已支持的数据集与来源说明（摘要）

当前数据基座已覆盖：

- 基础主数据：`stock_basic`、`trade_cal`、`etf_basic`、`index_basic`、`hk_basic`、`us_basic`、`etf_index`
- 行情/指标/榜单/板块：详见 `docs/datasets/dataset-catalog.md`

统一来源：

- 主数据与行情：Tushare Pro 各资源接口
- 运维状态：基于 `ops` 任务状态与目标表观测聚合

## 6. 运维接入约束

- 数据状态分类：`基础主数据`
- 观测列：无业务日期列，页面显示“最近同步日期”
- 任务规格：`sync_history.etf_index`（支持手动、支持调度、支持重试）
