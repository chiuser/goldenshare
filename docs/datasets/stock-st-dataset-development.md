# ST 股票列表（`stock_st`）维护说明

状态：当前代码说明；2026-09-10 文档治理核对。本文只描述现行日名单维护，不执行历史重建、不宣称生产数据已补齐。

## 1. 范围与依据

Tushare `stock_st`，doc_id=397，[本地源说明](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/基础数据/0397_ST股票列表.md)。源文档描述每天约 09:20 更新、数据从 2016-01-01 起，属于来源说明，不是本轮时效或数据完整性证明。

与 [st 风险警示事件](/Users/congming/github/goldenshare/docs/datasets/st-dataset-development.md)不同：`stock_st` 表示每日名单，`st` 表示事件历史，两者类型字段、时间模型、写入路径均不能互换。事实定义见 [market_equity Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py)，公共流程见 [开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)。

## 2. 日期输入与执行

- 入口 `stock_st.maintain` 必须显式提供 point 单日或 range 起止日期；不支持无时间全量。
- point 生成该日期一个 unit；range 按交易日历开市日逐日展开。不要把“区间查日历”外推为所有 point 都会另做开市日过滤。
- 每个源请求只发送 `trade_date=YYYYMMDD` 和可选 `ts_code`；区间不原样传给源端，不按股票池展开。
- `generic / no_pool / offset_limit`；SourceClient 注入 `limit=1000/offset`，空页或短页结束。当前 `buffer_all + commit_policy=unit`，每个交易日全部分页读完后归一化、写入并提交。
- **当前没有自动裁剪到 2016-01-01 的逻辑。** 源端历史起点与本仓保护行为必须区分；模拟交易日历返回 2015-12-31 时，现行规划器仍生成 `trade_date=20151231`。这是离线规划证据，不表示源端能返回该日数据。
- 日历返回空集合时 planner 生成零 unit；本文不把它扩大承诺为所有任务入口一定“不报错且有特定提示”。

代码依据：[Resolver](/Users/congming/github/goldenshare/src/foundation/ingestion/resolver.py)、[unit planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)、[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)。本次只撤掉不存在的自动裁剪承诺，不新增裁剪或放开输入合同。

## 3. 字段、身份与存储

| 字段 | 含义与约束 |
| --- | --- |
| `ts_code` | 股票代码，必填 |
| `trade_date` | 名单日期，必填并转 Date |
| `type` | 风险类型，必填，不自行映射为事件字段 st_type |
| `name` | 股票名称，可空 |
| `type_name` | 类型名称，可空，保留源口径 |

- 五个业务字段显式请求，Raw 与 Serving 主键均为 `(ts_code, trade_date, type)`，避免覆盖同一股票同一天不同类型记录。
- Raw 物理表 `raw_tushare.stock_st`，保留 `api_name/fetched_at/raw_payload`；[Raw ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_stock_st.py)。
- Serving 物理表及 `target_table` 为 `core_serving.equity_stock_st`，含 `created_at/updated_at`；[Serving ORM](/Users/congming/github/goldenshare/src/foundation/models/core/equity_stock_st.py)。
- **仍为 `raw_core_upsert` 双物理写入**，不是 Raw-backed view。物理索引以现行模型/数据库为准，不保留旧“建议索引”作为建库指令。

## 4. 工作流、观测与消费者

- 已纳入 `daily_market_close_maintenance` 的 `stock_st` 步骤，见 [action_catalog](/Users/congming/github/goldenshare/src/ops/action_catalog.py)；支持手动、定时、重试，不代表本轮确认了 schedule 开关。
- 日期模型为 `trade_open_day / every_open_day`，观测 `trade_date`，freshness 为 `continuous_open_day`，日期完整性审计适用。
- 当前消费者包括 [市场情绪](/Users/congming/github/goldenshare/src/biz/services/market_mood_calculator.py)、[涨停摘要](/Users/congming/github/goldenshare/src/biz/queries/wealth/market/limit_up/limit_up_summary_query.py)和 [涨停结构](/Users/congming/github/goldenshare/src/biz/queries/wealth/market/limit_up/limit_up_structure_query.py)；不能因为文档过期而删除服务表或改变类型口径。

## 5. 历史缺失日期专题与回归

原接入记录指出源站某些历史日快照为空；相关处理仍单列在 [历史缺失日期重建方案](/Users/congming/github/goldenshare/docs/datasets/stock-st-missing-date-reconstruction-plan-v1.md)，对应 [重建服务](/Users/congming/github/goldenshare/src/foundation/services/migration/stock_st_missing_date_repair/service.py)和独立 CLI。它不是普通 `stock_st.maintain` 的自动回退，本轮不执行，也不根据方案标题判断当前生产是否已修复。

当前回归入口：

- [Definition 注册](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[Ops 工作流](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)、[五字段清单](/Users/congming/github/goldenshare/tests/test_fields_constants.py)、[Serving 主键与索引](/Users/congming/github/goldenshare/tests/test_extended_models.py)。
- 独立修复工具：[服务回归](/Users/congming/github/goldenshare/tests/test_stock_st_missing_date_repair_service.py)、[CLI 回归](/Users/congming/github/goldenshare/tests/test_cli_repair_stock_st_missing_dates.py)；这些不证明普通同步具有 2016 年自动裁剪。

旧 `tests/test_sync_stock_st_service.py`、`tests/test_sync_registry.py` 已不存在，撤下其覆盖承诺。大范围任务的请求量、内存、取消、提交与续跑仍按开发模板独立验收；本轮未请求 Tushare、修改业务表或验证历史完整性。
