# ETF 基准指数列表（`etf_index`）维护说明

更新：2026-09-10。本文按当前代码校准，不代表本轮执行过生产同步或源接口复测。

## 1. 用途与合同

维护 ETF 跟踪指数主数据，不是 ETF 产品名单。当前 catalog 归入 `etf_fund`（ETF/Fund），不是“基础主数据”。

| 项目 | 当前行为 |
| --- | --- |
| 数据集 / Tushare API | `etf_index` |
| 时间模型 | `none / not_applicable`；没有连续业务日期桶，不参加日期完整性审计 |
| 运营过滤器 | 可选单值 `ts_code`、`pub_date`、`base_date`，均由 Definition 派生 |
| 维护能力 | 手动、调度、重试；时间模式 `none` |
| 请求 / 分页 | `_etf_index_params`；`offset_limit`，每页 5,000 |
| 写入 | `raw_core_upsert`，按 unit 提交 |

`pub_date/base_date` 是日期类型的过滤器，不是任务的日期范围。无时间模式不等于“运营不能填写日期过滤”。`ts_code` 指跟踪指数代码；当前 Definition 的描述仍写“ETF 代码”，这是标签不准确，本轮不修改代码或关闭过滤器。builder 将代码转大写，日期去掉连字符后发给源端。

## 2. 字段与存储

源端八字段：`ts_code, indx_name, indx_csname, pub_party_name, pub_date, base_date, bp, adj_circle`。

- Raw：`raw_tushare.etf_index`，保存业务字段和 `api_name/fetched_at/raw_payload`。
- Serving：`core_serving.etf_index`，保存业务字段及 `created_at/updated_at`；主键为 `ts_code`，保留发布日期、基期日期索引。
- `pub_date/base_date` 归一化为日期，`bp` 为 Decimal；观测字段为空，不能把这两个属性日期当作“每天应有数据”的依据。

## 3. 核验入口

- [本地源文档 0386](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0386_ETF基准指数列表.md)：接口资料，不替代真实请求验证。
- [Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/index_series.py)、[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)。
- [Raw 模型](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_etf_index.py)、[Serving 模型](/Users/congming/github/goldenshare/src/foundation/models/core/etf_index.py)。
- [运营过滤器投影](/Users/congming/github/goldenshare/src/ops/queries/manual_action_query_service.py)、[catalog 分类](/Users/congming/github/goldenshare/src/ops/catalog/dataset_catalog_views.py)。

新增或调整合同遵循[数据集开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)，本文不再维护无关的全仓接入清单。
