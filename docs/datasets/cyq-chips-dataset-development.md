# 每日筹码分布（cyq_chips）维护说明

更新时间：2026-09-10。代码已实现；历史源端验证与生产验收分开说明。本数据集为 Tushare 单源 Raw/view，不做 Std、多源融合、Lake 导出或新增用户侧功能。

## 1. 现行链路与依据

`cyq_chips.maintain` → DatasetActionResolver → 股票与日期窗口 units → Tushare 分页 → normalizer → Raw upsert → Serving view。任务观测沿用 TaskRun，不另造“补数/离线补数”动作或恢复系统。

| 事实 | 实现 |
| --- | --- |
| 定义、字段、能力 | [market_equity.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py) 中 `cyq_chips` |
| 规划、股票选择 | [unit_planner.py](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)：`_build_cyq_chips_units / _resolve_cyq_chips_targets` |
| 请求、分页 | [request_builders.py](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)：`_cyq_chips_params`；[source_client.py](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py) |
| Raw/view | [000114 迁移](/Users/congming/github/goldenshare/alembic/versions/20260530_000114_add_cyq_chips_dataset.py) |
| 展示、freshness | [dataset_catalog_views.py](/Users/congming/github/goldenshare/src/ops/catalog/dataset_catalog_views.py)、[freshness_policies.py](/Users/congming/github/goldenshare/src/foundation/datasets/freshness_policies.py) |

## 2. 输入、股票范围与执行

- 运营提交单日 `trade_date` 或闭区间 `start_date/end_date`；`ts_code` 可选、多值，支持代码列表或逗号分隔。不暴露 limit/offset。
- 显式代码去空白、转大写、去重排序，只维护这些代码；名称通过主数据查询补充，不要求代码必须属于默认上市池。
- 未指定代码时，从 `core_serving.security_serving` 的证券主数据读取默认范围，筛选 `list_status='L'`。来源回退差异见下节；默认当前上市池不能证明退市股票历史全覆盖。
- 单日：每只股票一个 `ts_code + trade_date` unit。
- 区间：每只股票按**最多 1095 个自然日的闭区间**切窗，每窗一个 `ts_code + start_date + end_date` unit；不是固定三个日历年，也不是股票×交易日逐日请求。
- `offset_limit / page_limit=2000`：source client 追加分页参数，满页继续，短页结束；一个 unit 分页完成后归一化、写入并按 unit 提交。
- 专用 builder 已注册为 `build_cyq_chips_units`；不能用不展开股票池的 generic planner 替换它，也不能套分钟线的频率模型。

<a id="pool-source-deviation"></a>

### 独立代码差异：股票池来源回退尚未修复

原方案“只取 Tushare 上市股票”与代码有差异：`_resolve_cyq_chips_targets` 优先取 Tushare 的 L 股票；该集合为空时回退到所有来源的 L 股票代码，仍调用 Tushare 接口；两者均为空才报 `universe_empty`。存在 Tushare 股票时不会同时混入其他来源补足池。

2026-09-10 离线样本已复现“只有非 Tushare 上市股票也能生成 Tushare 请求”。这只是确认代码行为，不将回退升级为已批准的业务规则。本轮只记录；是否取消回退及对应消费者/测试修改，须作为独立代码事项确认。

## 3. 字段、存储与观测

| 字段 | 保存及规范化 |
| --- | --- |
| `ts_code` | 股票代码，身份字段 |
| `trade_date` | 转 Date，身份字段 |
| `price` | 成本价格，Numeric(18,4)，身份字段 |
| `percent` | 价格占比（%），Numeric(10,4) |

- Raw：`raw_tushare.cyq_chips`，主键必须为 `(ts_code, trade_date, price)`；另有 `api_name/fetched_at/raw_payload`，索引为日期、代码+日期。只用代码+日期会覆盖同日不同价格档位。
- 写入：`raw_only_upsert`，raw/core DAO 名均为 `raw_cyq_chips`；实际只写 Raw。拒绝策略为 `record_rejections`，验收须单独核对拒绝行，不能把成功状态等同零拒绝。
- Serving：`core_serving.equity_cyq_chips` 是四个源字段直出的普通 view，无第二份物理 Serving 数据。
- 日期模型：`trade_open_day / every_open_day / point_or_range`，业务字段 `trade_date`；freshness 为 `continuous_open_day`。
- `audit_applicable=False`，原因是“每日筹码分布本期只接 freshness，不接日期-股票完整性审计”。有交易日输入和新鲜度判断，不等于接入日期或日期×股票完整性审计。
- Ops 默认组为 `technical_indicators / 技术指标`。支持手动、普通自动任务与重试；**未加入 `daily_market_close_maintenance` 工作流**。低频长区间维护不混入每日工作流，任务展示实际股票、窗口和行数，不提供提交前耗时预估保证。
- 状态写入失败不得影响已提交 Raw 业务数据。

## 4. 历史源端证据与性能边界

来源：doc_id=294，[本地每日筹码分布说明](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/特色数据/0294_每日筹码分布.md)。本地说明记载 2018 年起、约 18～19 点更新、每次最多 2000 行、源请求需带代码；5000 积分档为每日 20,000 次、每分钟 200 次。额度是来源说明，不是本轮核验的当前账户能力。

以下来自原接入记录，样本涉及 2026 年 4～5 月；原文未提供全部请求的执行时间戳。本轮没有重跑 MCP 或 connector。原 MCP schema 要求代码且不暴露分页，分页证据来自当时生产 connector 请求，不等于生产数据库写入验收。

| 请求形态 | 实际请求参数 | 返回情况 | 是否分页 | 样本字段 | 结论 |
| --- | --- | --- | --- | --- | --- |
| 不传业务参数 | MCP schema 不允许省略 `ts_code`；源文档也标记 `ts_code` 必填 | 无法发起 | 不适用 | 不适用 | 该 MCP schema 无法验证省略代码；现行实现逐股请求。 |
| 只传对象过滤 | `ts_code=600000.SH`，显式字段 `ts_code/trade_date/price/percent` | 返回多日筹码分布，输出过长被 MCP 截断，可见从最近交易日向历史日期返回 | 源文档说单次最大 2000，MCP 不暴露分页参数 | `600000.SH / 20260515 / price / percent` | 支持按股票代码取历史，但生产实现应优先使用明确时间输入，避免无上界请求。 |
| 只传时间点 | `ts_code=600000.SH, trade_date=20260424` | 返回 139 行价格档位 | 单日单股未触发分页 | `ts_code, trade_date, price, percent` | 单日维护按股票池展开后，每只股票使用这种请求形态。 |
| 传时间区间 | `ts_code=600000.SH, start_date=20260420, end_date=20260424` | 返回多个交易日的价格档位，输出较长 | 可能需要分页 | `ts_code, trade_date, price, percent` | 区间维护按股票池展开后，每只股票使用这种请求形态。 |
| 分页第二页 | 生产 connector：`ts_code=000001.SZ, start_date=20180102, end_date=20260529, limit=2000, offset=2000` | 返回 2000 行 | 是 | `ts_code, trade_date, price, percent` | 源端支持 `limit/offset`。 |
| 深分页可用样本 | 生产 connector：同上，`offset=100000` | 返回 2000 行 | 是 | `ts_code, trade_date, price, percent` | 该样本在 10 万 offset 时可返回。 |
| 深分页边界 | 生产 connector：同上，`offset=150000` | 返回 Tushare 参数错误 | 是 | 不适用 | 该超长区间的深分页失败，是现行切窗策略的依据。 |

历史规模估算保留其决策意义：

| 场景 | 原估算与限制 |
| --- | --- |
| 约 5500 只股票的全市场单日 | 约 5500 次请求；按 200 次/分钟约 27.5 分钟，不含写库/重试 |
| 一年按股票×约 240 个交易日逐日拉 | 约 132 万次、110 小时，故不采用 |
| 一年按股票×窗口分页拉 | 按每股每日约 139 行、每页 2000 行估算约 17 页/股，约 9.35 万次、7.8 小时 |
| 2018-01-02～2026-05-29、5525 只股票 | 1095 日窗口约 3 窗/股、16,575 units；365 日窗口约 49,725 units |
| 显式单股一年 | 原样本估算约 17 次请求，不是固定耗时保证 |

窗口数不等于分页请求数。1095 日切窗用于降低深 offset 风险，不保证任意股票/窗口都不会遇到源端上限；价格档位密度、配额、重试与写入会改变成本。运营可用同一 maintain 动作分段执行，不凭上述估算自动启动全市场长任务。

## 5. 回归与历史验收状态

- [定义测试](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)：字段、分页、日期及观测边界。
- [resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)：显式多代码、默认股票池、point/range、1095 日切窗与请求参数。
- [writer 测试](/Users/congming/github/goldenshare/tests/test_dataset_writer_cyq_chips.py)：三字段身份、只写 Raw。
- 通用分页测试应验证 offset 递增、短页终止和中间页失败，不仅验证能返回第一页。

原 M1～M5 记录 ORM/迁移、Definition、planner、测试及不接工作流已完成；M6 证明单股源请求和分页边界，**不等于以下 Raw/TaskRun 联合验收已经全部完成**。原最小验收清单继续保留为核验要求，而非自动执行授权：

1. `600000.SH + 2026-04-24` 单日样本（当时 139 行）及 2026-04-20～24 短区间。
2. 2～3 股单日和短区间，核对 unit、TaskRun、卡片与 freshness。
3. 单股超过 1095 日的区间，确认多窗口参数而非原始超长区间。
4. 对账 fetched、normalized、Raw written、rejected、reason code、Raw 与 view 实际行数。

本轮未核验这些生产执行结果，也未新增 checkpoint、快照或备份能力。
