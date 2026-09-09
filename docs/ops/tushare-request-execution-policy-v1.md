# Tushare 请求执行规则阅读入口

更新时间：2026-09-10。状态：现行导航，不是逐数据集契约或接入数量清单。

原“全量 54 个数据集”表实际含 55 项，已随实现演进产生默认参数、日期、分页和过滤规则冲突。本轮移除这份重复规则表，旧全文从 Git 历史追溯。保留原路径供现有引用使用；不得继续按旧表新增或改造请求。

本文面向本仓 Prod ingestion 的 Tushare 链路，不定义 Biying 或 DG/Lake 执行规则，不授权同步、补数或数据清理。

## 1. 要查什么，去哪里看

| 问题 | 维护入口 |
| --- | --- |
| 新增或修改数据集要验证什么 | [数据集开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)：源行为、三层时间语义、消费者、请求量与验收；具体方案落在各数据集自己的开发文档 |
| 当前有哪些数据集、接受哪些输入 | [DatasetDefinition 职责](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md)、[registry](/Users/congming/github/goldenshare/src/foundation/datasets/registry.py) 与 [definitions](/Users/congming/github/goldenshare/src/foundation/datasets/definitions)；不在本文手工维护数量 |
| 时间输入、执行窗口与 freshness 如何区分 | [日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)；字段名 `trade_date` 不能替代日期模型 |
| 默认枚举、对象池、分页、事务如何执行 | [执行计划说明](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)；实际追到 [unit planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)、[request builders](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)、[source client](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py) |
| Tushare 接口参数、字段和限额如何核验 | [本地源文档索引](/Users/congming/github/goldenshare/docs/sources/tushare/docs_index.csv)定位对应接口；按[根 AGENTS 的本地 Tushare 能力](/Users/congming/github/goldenshare/AGENTS.md#本地-tushare-能力)完成所需实测 |

当前代码证明已实现行为，已批准方案说明目标，源文档与实测说明外部接口事实；三者有差异时必须明确记录，不能把历史方案或接口可选参数直接当成运营输入合同。

## 2. 不再沿用的旧概括

1. **不再统一要求“未填写就不补默认枚举”。** `planning.enum_fanout_defaults` 和专用 planner 可能有明确默认展开；例如 KPL 标签、新闻来源和热榜组合。查询实际展开后的 unit，不凭参数是否可选推断请求范围。
2. **全选不等于统一删除该参数。** 按真实枚举集合及当前 planner 处理；停复牌 `S/R` 全选生成两个单值请求。不得恢复“全选折叠”总规则，也不得把列表字符串或 `__ALL__` 哨兵发送到源端。
3. **运营意图不是源参数原样透传。** 只接受已声明输入，由 Resolver/planner 归一化、request builder 映射；ETF Basic 完整快照的现行 builder 明确拒绝业务过滤，不能因源接口支持过滤就重新开放。
4. **区间不等于逐交易日请求。** 指数日线按代码和日期窗口请求；股票周/月线与指数周/月线锚点不同。时间输入、unit 粒度与连续日期审计分别按合同确认。
5. **源文档上限不等于统一工程 page_limit。** 读取 Definition、专用 planner 与 unit 的有效分页配置；只在相应策略下使用 offset/limit。短页结束不能单独证明全量完整，分页、完整性与请求量验证统一按开发模板，不再复制另一套参数表。

以上是纠正旧文档的阅读提示，不授权修改当前代码以迎合某条总规则。

## 3. 原表特殊规则的承接位置

以下只保留容易在删表时丢失的边界与入口，不再复刻逐数据集字段、限额和参数示例。链接中的执行阶段、历史记录与验收状态仍须分别阅读，不能由本文推导已全部上线或验收。

| 专题 | 承接位置与需保留的边界 |
| --- | --- |
| 指数日/周/月线 | [现行机制](/Users/congming/github/goldenshare/docs/datasets/index-series-active-sync-mechanism.md)、[Raw/Serving 分层方案](/Users/congming/github/goldenshare/docs/datasets/index-raw-serving-layer-alignment-plan-v1.md)：日线请求池与 Serving active 池不同；保留 Raw 返回事实、Serving 筛选及周/月线派生来源边界 |
| 股票周/月线 | [维护说明](/Users/congming/github/goldenshare/docs/datasets/equity-weekly-monthly-sync-logic.md)：自然周五/自然月末锚点，频率按对应数据集内部固定；不套用指数锚点 |
| 股票分钟线 | [正式开发文档](/Users/congming/github/goldenshare/docs/datasets/stk-mins-dataset-development.md)：对象范围、频率、datetime 窗口及分页在该文档与当前 planner 维护；不要在本入口再次抄写 |
| 指数权重、月度荐股 | [日期指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)、[对象池合同](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md#universe-contract)、[荐股开发文档](/Users/congming/github/goldenshare/docs/datasets/broker-recommend-dataset-development.md)：自然月窗口、月份键和代码池分别处理 |
| KPL 与停复牌 | [KPL 方案](/Users/congming/github/goldenshare/docs/ops/ops-kpl-list-next-day-release-plan-v1.md)：发布目标日、五标签要求及已知过滤缺口；[停复牌开发文档](/Users/congming/github/goldenshare/docs/datasets/suspend-d-dataset-development.md)：S/R 单值扇出与幂等写入 |
| 神奇九转 | [开发文档](/Users/congming/github/goldenshare/docs/datasets/stk-nineturn-dataset-development.md)：当前 `freq=daily` 为内部固定参数，不重新开放成运营选项 |
| ETF Basic | [原专项 LLD](/Users/congming/github/goldenshare/docs/architecture/etf-basic-rebuild-and-downstream-data-audit-cleanup-low-level-design-v1.md)、[现行 Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/reference_master.py)、[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)：无日期、无业务过滤的完整快照；方案中的单对象核验不等于正式维护支持单对象 |
| 股票基础信息 | [专用 planner 的 `_build_stock_basic_units`](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)：Tushare 分支未填 `list_status` 时按 `L/D/P/G` 展开，不是一个逗号拼接的默认源参数；不得因精简文档缩成仅上市股票 |
| 热榜美股开关 | [Settings](/Users/congming/github/goldenshare/src/foundation/config/settings.py) 与 [Definition 构建器](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/_builder.py)：`TUSHARE_ENABLE_US_HOT_MARKETS` 默认 false；关闭时从 `dc_hot/ths_hot` 可选市场与默认展开中排除美股；不是取消其余市场的默认展开 |

其余逐数据集参数、分页值和源文档路径不在此重复维护，按 §1 从对应 Definition、开发文档与源索引查找。新增或修订合同须同步原开发文档与模板；只有导航位置改变或出现必须保留的阅读边界时才更新本页。分钟开发文档中原“实现时向本表补条目”的要求同步撤销。

本轮仅整理文档，并依据当前代码、相关测试及上轮已读本地源资料校准入口；未对全部数据集重新实测源接口，未运行业务任务，也不将旧表移除视作现有数据已完成完整性验收。
