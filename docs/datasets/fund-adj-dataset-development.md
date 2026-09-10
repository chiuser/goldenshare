# 基金复权因子（`fund_adj`）维护说明

- 状态：已接入 Prod 数据集维护链路；当前为 Raw/Core 双写，不是 Raw-only/Serving view。
- 更新时间：2026-09-10（按当前代码校准文档；未重新请求源端或核验生产）。
- 本篇只描述 Prod 实现，不代表其他同名数据链路的字段与存储合同。

## 1. 当前维护合同

事实源：[DatasetDefinition：`fund_adj`](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_fund.py)。通用日期与执行规则见 [日期模型指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md) 和 [执行计划基线](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)。

| 项目 | 当前实现 |
| --- | --- |
| 动作与入口 | `fund_adj.maintain`；支持手动、调度、重试，已纳入 `daily_market_close_maintenance` 工作流 |
| 时间输入 | 单日 `trade_date` 或区间 `start_date + end_date`；正式维护动作只支持 point/range |
| 日期模型 | `trade_open_day / every_open_day / point_or_range`；观测字段为 `trade_date` |
| 对象过滤 | 运营可选填 `ts_code`；builder 去首尾空格并转大写。不填时按交易日请求全市场，不按基金对象池逐只拉取 |
| 执行单元 | 区间按交易日历展开为每日 unit；每个 unit 发送单个 `trade_date`，不直接发送整个区间 |
| 分页 | 内部固定 `limit=2000`，`offset` 从 0 逐页递增；短页（行数小于 2000，含空页）结束，满页继续；不向运营暴露分页参数 |
| 写入与观测 | `raw_core_upsert`、按 unit 提交；目标表和 freshness 观测目标为 `core.fund_adj_factor`；运维目录归类为 ETF/Fund |

实现入口：[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)、[unit planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)、[source client](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)、[writer](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)。

`no_pool` 表示默认源请求不通过对象池扇出，不表示禁止人工传 `ts_code`。本链路不按 ETF Basic 过滤返回数据；显式代码入口及保护边界见 [ETF Basic 下游治理 LLD §7.5](/Users/congming/github/goldenshare/docs/architecture/etf-basic-rebuild-and-downstream-data-audit-cleanup-low-level-design-v1.md)。不能因本数据集位于 ETF/Fund 分类，就将事实范围缩成当前 ETF Basic 代码集合。

## 2. 来源与当前接入字段

本地来源：Tushare **doc_id=199**，[基金复权因子](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0199_基金复权因子.md)。源文档的可选参数、样例和历史实测保留在该处，不重复作为本仓运营输入规则。

当前 Prod 每页显式请求并保存 `ts_code, trade_date, adj_factor` 三字段，**不是源接口全部可用字段**。本地资料的 2026-09-02 实测补充还记录了显式请求 `discount_rate` 的返回；当前 Prod Definition 与两层 ORM 均未接入该字段。本次只纠正文档，不新增字段，也不把其他链路的实测当成本链路已实现的证明。

## 3. 物理表与保留边界

两层业务身份均为 `(ts_code, trade_date)`，由各自物理主键约束；业务字段均为上述三列。

| 物理表 | 附加字段与差异 |
| --- | --- |
| [`raw_tushare.fund_adj`](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_fund_adj.py) | 审计字段 `api_name / fetched_at / raw_payload`；`adj_factor` 为 Numeric(20,8)，允许空值 |
| [`core.fund_adj_factor`](/Users/congming/github/goldenshare/src/foundation/models/core/fund_adj_factor.py) | 系统字段 `created_at / updated_at`；`adj_factor` 为 Numeric(20,8)，不允许空值；日期索引 `idx_fund_adj_factor_trade_date` |

两个 DAO 均由现行 writer 使用，并被 [ETF Basic 下游只读审计脚本](/Users/congming/github/goldenshare/scripts/sql/etf-basic-downstream-readonly-audit.sql)列为保护表。Raw/Core 空值约束不同，不能只凭业务列同名就认定可直接改成 Raw-backed view；本篇不授权表清退或存储迁移。

## 4. 回归与后续修改

- [ORM 测试](/Users/congming/github/goldenshare/tests/test_extended_models.py)：`FundAdjFactor` 主键、日期索引。
- [动作目录测试](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)：Definition 派生动作与工作流引用。
- [下游审计脚本测试](/Users/congming/github/goldenshare/tests/test_etf_basic_downstream_audit_runbook.py)：只读边界及 Raw/Core 保护表清单。

上述测试不证明源端实时返回、生产数据完整性或生产开关状态。后续若修改字段、过滤或长任务执行方式，须重新审计消费者，并按 [开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)补齐相应设计与验收；不得把现有逐 unit 提交写成已经具备持久化断点续跑。
