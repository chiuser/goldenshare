# ETF 日线行情（`fund_daily`）维护说明

更新：2026-09-10。现行链路保存基金日线 Raw，再按 ETF Basic 资格发布 Serving；本轮只校准文档，未执行生产同步。

## 1. 输入与请求

| 项目 | 当前行为 |
| --- | --- |
| 数据集 / API | `fund_daily` |
| 时间输入 | 单日 `trade_date`，或区间 `start_date/end_date` |
| 可选过滤 | 单个 `ts_code`；未填写时不加代码过滤 |
| unit | 交易日历中的每个开市日一个 unit，不按代码池展开 |
| 分页 | `offset_limit`，每页 5,000；从 offset=0 开始，短页结束，满页继续 |
| 运营能力 | 手动、调度、重试；分类 ETF/Fund |
| 观测 | `trade_date`；适用日期完整性审计 |

`ts_code` 会由 builder 转大写并传给源端。日期、代码是运营意图，`limit/offset` 是执行参数，不作为运营输入。不能继续使用“不展示代码过滤”的旧约定。

## 2. 字段与两阶段发布

源字段：`ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount`。日期归一化，数值按 Decimal 转换，`change` 映射为 `change_amount`。

| 阶段 | 目标与边界 |
| --- | --- |
| Raw | 经归一化校验的源行写入 `raw_tushare.fund_daily`，包含 Raw 审计信息；独立提交 |
| ETF 筛选 | 加载 `EtfBasicDAO` 当前可请求 snapshot，只保留合格 ETF 且行的交易日不早于其上市日 |
| Serving | 将筛选后的行写入 `core_serving.fund_daily_bar`；保留标准系统字段，独立于前一 Raw 提交 |

实际合同为 `storage.write_path=raw_fund_daily_etf_serving_publish`、`transaction.commit_policy=raw_then_serving`。不是一个 Raw/Serving 同生共死的大事务。

需要区分：

- 源端 `fund_daily` 返回范围不等于 ETF 集合；非 ETF 行仍可能是合法 Raw，不应当作垃圾删除。
- Basic selector 出错或集合为空会使 Serving 阶段失败；已经提交的 Raw 不因此回滚。
- ETF 资格/上市日排除是 Serving 筛选诊断，不是源行 normalization rejection。
- Raw 与 Serving 行数不要求相等。验收应对账 Raw 接纳量、Serving 排除原因及最终发布量，不能只比两表总行数。
- 2026-08-28 的既有源实测记录包含其他场内基金；这是带日期的历史证据，不是本轮复测，也不能推导源端永久只返回 SH/SZ。

## 3. 代码与回归入口

- [本地源文档 0127](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0127_ETF日线行情.md)。
- [Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_fund.py)、[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)。
- [writer 两阶段实现](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)、[executor 提交边界](/Users/congming/github/goldenshare/src/foundation/ingestion/executor.py)。
- [ETF 筛选测试](/Users/congming/github/goldenshare/tests/test_dataset_writer_fund_daily_master_gate.py)、[Raw 已提交而 Serving 失败等回归](/Users/congming/github/goldenshare/tests/test_ingestion_executor_fund_daily_two_phase.py)。

Basic 资格统一契约与历史重建见[ETF Basic 主方案](/Users/congming/github/goldenshare/docs/architecture/etf-basic-rebuild-and-downstream-data-audit-cleanup-plan-v1.md)；通用开发门禁见[数据集模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)。本轮不更改筛选、输入或事务规则。
