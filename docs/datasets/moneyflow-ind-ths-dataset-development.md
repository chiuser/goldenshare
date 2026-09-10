# 行业资金流向（THS）（`moneyflow_ind_ths`）维护说明

状态：当前代码说明；2026-09-10 文档治理核对。历史生产验收单列，不代表本轮重新核验了部署、数据或 schedule 状态。

## 1. 范围与依据

单源 Tushare 数据集，属于资金流向域；不做 Std 映射或多源融合。本文只保留本数据集合同；通用接入、日期与运行门禁见[开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)和[日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)。

- 来源：Tushare `moneyflow_ind_ths`，doc_id=343；[本地接口说明](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/资金流向数据/0343_同花顺行业资金流向（THS）.md)。
- 事实源：[moneyflow Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/moneyflow.py)。
- 执行：[DatasetActionResolver](/Users/congming/github/goldenshare/src/foundation/ingestion/resolver.py) → [unit planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py) → [request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py) → SourceClient / Normalizer / Writer。

## 2. 输入、执行与观测

| 维度 | 当前口径 |
| --- | --- |
| 维护入口 | `moneyflow_ind_ths.maintain`；支持手动、定时与重试 |
| 时间输入 | point 单日；range 开始/结束日期。日期模型为 `trade_open_day / every_open_day` |
| unit | 单日生成一个 unit；区间按交易日历开市日逐日生成 |
| 对象选择 | `no_pool`；可选 `ts_code` 定向过滤，不按股票/板块池展开 |
| 源请求 | 每个 unit 发送 `trade_date=YYYYMMDD`及可选 `ts_code`；不把运营区间原样传给源接口 |
| 分页 | `offset_limit`，`page_limit=5000`；SourceClient 注入 `limit/offset`，空页或短页结束 |
| 持久化 | `commit_policy=unit`；一个 unit 读取完成后归一化、写入并提交，不是每页独立提交 |
| 观测 | 资金流向分组；`observed_field=trade_date`，启用日期完整性审计 |

每日资金流向维护工作流 `daily_moneyflow_maintenance` 已包含本数据集，定义见 [action_catalog](/Users/congming/github/goldenshare/src/ops/action_catalog.py)。保留“独立资金流向工作流、不并入其他工作流”的已确认边界；工作流定义不等于某台机器的 schedule 正在启用。

## 3. 字段与质量

以下按本地源文档列出业务字段；实际显式请求列表以 Definition 的 `source_fields` 为准。

| 字段名 | 类型 | 含义 | 是否落库 |
| --- | --- | --- | --- |
| `trade_date` | str | 交易日期 | 是 |
| `ts_code` | str | 板块代码 | 是 |
| `industry` | str | 行业名称 | 是 |
| `lead_stock` | str | 领涨股票名称 | 是 |
| `close` | float | 最新价 | 是 |
| `pct_change` | float | 涨跌幅（%） | 是 |
| `company_num` | int | 公司数量 | 是 |
| `pct_change_stock` | float | 领涨股涨跌幅 | 是 |
| `close_price` | float | 领涨股最新价 | 是 |
| `net_buy_amount` | float | 流入资金（亿元，源文档口径） | 是 |
| `net_sell_amount` | float | 流出资金（亿元，源文档口径） | 是 |
| `net_amount` | float | 净额（亿元，源文档口径） | 是 |

原开发说明将上述三项金额标为万元，与本地源文档的亿元冲突。本次按源文档纠正说明并保留来源；当前 normalizer 只做数值解析，没有万/亿换算。本轮没有重新实测源端金额单位，也不据此缩放或重写历史数值。

日期和数值解析、必填字段拒绝由现行 normalizer 执行；异常应查看实际 reason code 与样本，不以日志示例代替数据对账。

## 4. 存储与查询边界

- 唯一物理事实表及 `target_table`：`raw_tushare.moneyflow_ind_ths`；写入 `raw_only_upsert`。
- Raw 主键：`(trade_date, ts_code)`。审计字段为 `api_name/fetched_at/raw_payload`；物理索引以 [Raw ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_moneyflow_ind_ths.py)及实际数据库 catalog 为准。
- 读取出口：`core_serving.industry_moneyflow_ths` 普通视图，直接投影 Raw 业务字段，并将 `fetched_at` 投影为 `created_at/updated_at`。
- `delivery_mode=raw_with_serving_view`；没有第二份 Serving 物理写入，也不是待建的临时双表方案。
- 普通 view 不自带主键或实体索引；ORM 的身份列用于查询映射，访问依赖 Raw 索引。迁移不承诺 relation OID、relkind、旧 index catalog 或历史 `created_at` 值透明。
- 历史切换实现：[revision 20260824_000147](/Users/congming/github/goldenshare/alembic/versions/20260824_000147_make_moneyflow_ind_ths_raw_view.py)。原子迁移的依赖、权限、全字段对账和拒写护栏保留在迁移代码，不作为现在重建或回退表的授权。

## 5. 回归与运行边界

- 专项回归：[test_moneyflow_ind_ths_raw_view_m1.py](/Users/congming/github/goldenshare/tests/test_moneyflow_ind_ths_raw_view_m1.py)：存储合同、请求计划、writer、模型及迁移护栏。
- 本轮只校准文档，不修改字段、日期、分页、API/CLI 或 schedule；不执行生产迁移、全量回补或真实源请求。
- unit 提交不等于分页持久化或已经满足长任务门禁；扩大日期范围前仍需按开发模板核对请求量、单 unit 内存和恢复证据，不能凭本说明认定全历史执行安全。
