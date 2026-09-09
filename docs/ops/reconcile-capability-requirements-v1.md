# 多源对账工具与后续需求

- 状态：现有 CLI 机制说明＋未实施需求；不代表生产基线已验收。
- 核对日期：2026-09-09；原需求日期：2026-04-12。保留原文路径，不把原验收清单的未勾选状态等同于“没有实现”。
- 范围：股票基础信息双源对账；资金流工具通过专题链接说明。日期完整性审计和多源字段比较是不同能力。

## 1. 股票基础信息对账

入口为 `goldenshare reconcile-stock-basic`：[CLI](/Users/congming/github/goldenshare/src/cli.py) → [命令处理](/Users/congming/github/goldenshare/src/cli_parts/ops_handlers.py) → [StockBasicReconcileService](/Users/congming/github/goldenshare/src/ops/services/operations_stock_basic_reconcile_service.py)。

读取 `core_multi.security_std` 中 `source_key=tushare/biying` 的已有标准化记录，按 `ts_code` 配对。不是实时请求源站，也不是校验融合后的 Serving 输出。当前只按来源筛选，不额外按日期或上市状态过滤；命令不写业务表，也不将结果持久化为审计 run。

固定比较规则：

| 项 | 当前实现 |
|---|---|
| 名称 | 去除全部空白；空值按空字符串；不做大小写、全半角或公司名称同义归并 |
| 交易所 | 去两端空白、转大写，再映射 SZSE→SZ、SSE→SH、BSE→BJ；空值为空字符串，其他值按转大写结果比较 |
| 差异判定 | 两源都有同一代码时，上述任一字段不同即计一个 comparable_diff；不是按不同字段数量累计 |

输出 `total_union`（两源代码并集）、`comparable`（共同代码）、`only_tushare/only_biying/comparable_diff` 三类差异计数及样例。`comparable` 不代表双方字段都非空或已通过质量校验；双方同为空的字段不产生差异。样例包含原值和归一化值，按代码排序后每类保留前 N 条。

## 2. 参数、退出码与使用边界

| 参数 | 默认值／含义 |
|---|---|
| `--sample-limit` | 20，CLI 范围 0–200；0 不打印样例，不影响汇总和扫描范围 |
| `--threshold-only-tushare` | -1，关闭该类门禁 |
| `--threshold-only-biying` | -1，关闭该类门禁 |
| `--threshold-comparable-diff` | -1，关闭该类门禁 |

设为非负数时，只有计数**严格大于**阈值才失败；等于阈值不失败。任一门禁失败时打印失败原因并退出 1；无门禁失败且命令正常执行则退出 0。默认三个门禁全部关闭，不能把默认退出 0 解读为“两源一致”。

还需注意：

- 输入为空、共同代码为零没有独立失败门禁；三类计数均为零也可能是两源都没有数据。先确认读库、两源数据范围及数量，再解释结果。
- 样例限制只控制输出，不限制 SQL 读取量。当前服务一次读取两源记录并在内存比较，不是分批扫描或可续跑作业。
- 上游字段语义可比性、源数据是否最新以及目标范围是否齐全，不由此 CLI 自动证明。发现差异先解释来源和规则，不能直接据此覆盖数据。
- 可用于开发回归、规则变更核验或发版前检查；“可作门禁”不代表已经接入自动发布流程，也不在本文指定新的业务阈值。原样例值、历史差异数不能直接变成正式阈值。

## 3. 已有资金流对账入口

当前另有 `goldenshare reconcile-moneyflow`，并非只有股票基础信息工具。该命令比较两源 Raw 资金流记录，有日期范围、金额容差及方向差异口径；与股票基础信息比较标准层不同。

使用与领域规则见[资金流专题 §5.3](/Users/congming/github/goldenshare/docs/datasets/moneyflow-multi-source-fusion-strategy-v1.md#53-已落地的对账命令mvp)，实现见[MoneyflowReconcileService](/Users/congming/github/goldenshare/src/ops/services/operations_moneyflow_reconcile_service.py)。本轮只补入口，不复制容差算法、不扩大股票基础 CLI 的职责，也不宣称源站语义已经重新实测。

## 4. 未实施的完整平台需求

以下保留为后续需求，不是现行模型、已批准开发排期或必须立即补齐的基础设施：

| 原设想对象 | 需要解决的问题 |
|---|---|
| `reconcile_rule` | 版本化规则：数据集、来源、可比字段、归一化和阈值 |
| `reconcile_run` | 可追溯运行：状态、摘要、耗时和错误 |
| `reconcile_result` | 可筛选差异明细 |
| `reconcile_issue` | 跟踪异常处理 |
| `reconcile_fix_action` | 人工纠偏操作审计与回放 |

其他保留方向：持久化后自动调度、Ops 展示／人工纠偏，以及扩展到 equity_daily_bar、adj_factor、daily_basic。新增对账必须先证明字段语义可比，不可比字段不得参与判定；规则要有文档和测试。是否使用上述对象、如何与现行 TaskRun 配合，需重新评审，不能把这些旧名字当成已定表结构。

## 5. 验证与历史

[服务测试](/Users/congming/github/goldenshare/tests/test_stock_basic_reconcile_service.py)覆盖归一化及三类计数；[CLI 测试](/Users/congming/github/goldenshare/tests/test_cli_reconcile_stock_basic.py)覆盖正常输出和阈值失败，三个测试在 2026-09-09 文档审计时通过。测试使用替身，不访问生产数据库，不证明源数据一致或发版门禁已经配置。

后续若改工具行为，应补阈值相等／关闭、空输入、单边数据和样例截断等边界回归，并单独取得真实数据验证授权；本轮没有改行为、增加空输入拦截或调整阈值。

旧需求全文可从提交 `39d957f4` 追溯；本轮保留有效需求，去掉重复背景和过时施工状态，未取消未来平台方向。
