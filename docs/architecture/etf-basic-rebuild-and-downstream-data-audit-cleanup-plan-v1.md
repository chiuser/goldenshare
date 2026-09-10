# ETF 基础信息与下游身份边界

更新：2026-09-10（文档治理，未改代码或生产数据）。创建：2026-08-28。
本文是已确认业务决策入口；实现、退场与带日期验收统一见 [配套 LLD](./etf-basic-rebuild-and-downstream-data-audit-cleanup-low-level-design-v1.md)。原主方案的重复实现步骤已合并，旧全文从 Git 追溯。

## 1. 现状与阅读边界

- 代码已完成完整 Basic 快照替换、统一 selector、下游消费者迁移和旧 ETF 激活池退场；不是仍待实施的 upsert 改造。
- 历史生产账本截至 **2026-08-29**：Basic 重建、旧表 drop、指定分钟区间补拉、沪市申赎与 fund daily 验收完成；当时 SZ 自然调度与实时开市批次仍缺补充验收证据。本轮未核实其后生产状态，不能据此说今天未运行或全部结案。
- 不重建旧池，不恢复旧 Review/Submit，不以本次文档合并触发同步、迁移、清表或补拉。
- 请求、事务、生命周期与回归定位看 LLD §3–9、§14；分钟操作看 [ETF 分钟维护文档](/Users/congming/github/goldenshare/docs/datasets/etf-mins-dataset-development.md)；历史过程与未验边界看 LLD §13。

## 2. 三个不能混淆的范围

| 范围 | 回答的问题 | 边界 |
| --- | --- | --- |
| Raw 当前快照 | 源端本次完整返回了什么 | 完整保存，包括源端实际返回的 .OF；不先按 ETF 身份裁剪 |
| Serving ETF 主数据 | 当前有哪些沪深 ETF 身份 | Raw 中 .SH/.SZ 全状态行，可含 L/P/D；不等于可请求集合 |
| 当前可请求 ETF | 本次可对哪些 ETF 发起新增请求 | L、上市日非空且不晚于本次固定中国自然日、后缀与 exchange 一致 |

两份主数据表都只保存当前态；抓取/更新时间不构成历史版本，不新增 SCD、每日快照、历史资格接口或第二个持久化池。当前主数据不能还原历史上市状态，不能凭代码消失、上市日后移或名称相似，把既有历史删掉或合并。

首次发布的 snapshot hash 和统计只是一次发布审计基准，不是长期选择器或删除 manifest。字段缺失、源端身份差异仍须按本地源文档与实测核验，不能由这些历史样本推断今天接口行为。

## 3. 已确认业务决策（D1–D20）

下表保留原决策编号与业务边界；带数量的审计结论只对应注明日期，实施细节以现行 LLD 为准。

| 编号 | 已确认规则 |
|---|---|
| D1 | `raw_tushare.etf_basic` 是 Tushare 当前返回的完整快照，不主动过滤 `.OF`。 |
| D2 | `core_serving.etf_basic` 只包含当前 raw 中的 `.SH/.SZ` 行。 |
| D3 | 首次重建采用“先完整取数并校验，再在一个业务事务内先删后写”的方式；不得先清空数据库再请求源端。 |
| D4 | `.OF` 不改名、不合并；2026-08-28/29 审计中下游旧 `.OF` 候选为 0。以后若在 ETF 专用代码拉取结果或需要 ETF 主数据对齐的 serving 中发现旧 `.OF`，必须按精确表和代码另行评审，获批后删除并按 `.SH/.SZ` 重新拉取；按日期返回源端全集的 raw/core 及其同口径直出 view 不按 ETF Basic 删除。 |
| D5 | 凡源接口需要按 ETF 代码展开请求，代码、状态与上市日必须以 `core_serving.etf_basic` 为身份依据；按日期全市场请求不做逐代码展开。 |
| D6 | `L + list_date 有效且不晚于执行日` 才能发起新增历史请求；`P` 和 `L + list_date 为空` 不请求。 |
| D7 | `D` 不再发起新增请求；既有历史保留，不因当前状态或当前 `list_date` 追溯删除。 |
| D8 | 以后按代码新增请求不得早于执行时的 `list_date`；既有事实早于当前 `list_date` 时只报告，不作为自动删除依据。保存源端全集的 raw/core 及其同口径直出 view 同样不按 ETF Basic 删除。 |
| D9 | 本次采用的接口合同没有 `delist_date`，因此暂不按退市日做上界裁剪。 |
| D10 | 公募基金域中的合法 `.OF` 不因 ETF 主数据重建被删除。 |
| D11 | 2026-08-28 源样本中的 3 条 `.OF` 可以保留在 raw，但不得进入 serving 和后续同步链路。 |
| D12 | `ops.etf_series_active` 整套激活池机制彻底退场；所有需要判断 ETF 身份或发起新增请求的下游统一以 `core_serving.etf_basic` 为身份上游。运行时请求消费者只使用统一的“当前可请求 ETF”契约；全状态主数据只供受控审计，不再做第二个运行时清单接口。 |
| D13 | 2026-08-28/29 Prod 审计中已确认删除候选为 0，本方案不建设通用事实清理 CLI、删除 manifest、apply 或备份/恢复能力；重建后复核若出现非零明确候选，另行按精确表和代码评审。 |
| D14 | `etf_basic` 继续只保存当前态，不新增历史表、SCD 字段或每日快照表；TaskRun 只保留行数、hash 和变更摘要。 |
| D15 | `etf_basic` 重建后，若某代码以后从主数据消失，或其 `list_date` 被改晚，只停止该代码后续请求并记录差异，不删除已经验收并落库的历史数据。 |
| D16 | 删除 `ops.etf_series_active` 属于高风险迁移；编码前必须先完成独立 LLD、全量消费者映射、迁移顺序和回归门禁，禁止把“计划已列影响面”当成可以直接删表的依据。 |
| D17 | `fund_daily`、`fund_adj`、`etf_share_size` 默认保持按交易日一次拉取源端全集，不按 ETF Basic 扇出请求；显式单代码入口按 LLD §7.5 保留为人工探测/修复，不用于自动逐 ETF 扇出。 |
| D18 | `raw_tushare.fund_daily`、`raw_tushare.fund_adj`、`core.fund_adj_factor`、`raw_tushare.etf_share_size` 永久保留源端返回范围，不做“不在 ETF Basic 即删除”；`core_serving.etf_share_size` 继续逐列直出 raw，不过滤、不重命名、不派生。 |
| D19 | `core_serving.fund_daily_bar` 改用当前可请求 ETF 清单做写入白名单，并校验 `trade_date >= list_date`；`fund_adj` 在出现明确 ETF serving 消费者前不新建 ETF 过滤层；`etf_share_size` 不接入 ETF 主数据门禁，也不新建物理 core/serving 表。 |
| D20 | `etf_rt_daily` 继续使用固定沪深通配符获取源端批次，ETF Basic 只替代其 health/业务候选中的旧池口径，不改变 provider 请求段。 |

## 4. 当前消费者职责

| 能力 | 实际使用方式 | 不得误改的内容 |
| --- | --- | --- |
| Basic maintain | 无业务筛选完整拉取，校验后同事务替换 Raw/Serving | 不能先删表再请求源端，不能用部分返回替换完整快照 |
| ETF 分钟 | Basic 可请求集合；单代码查 target，多代码/全量查 snapshot；上市日裁剪后切窗 | 一次普通 TaskRun 可扇开多代码，不能恢复 alignment Submit |
| 沪深申赎 | Basic 同一资格规则，加固定 SH/SZ scope | 不因分钟允许多代码而放宽这两个入口 |
| fund daily | 默认按日拉源端全集，Raw 先提交，Serving 再按 Basic 与 trade_date/list_date 发布 | Serving 失败保留 Raw，不能把源请求变成逐 ETF |
| fund adj / share size | 默认按日源端全集；各自单代码修复入口仍在 | 不接 Basic 筛选，不删合法基金事实；share size 继续 Raw 直出 view |
| ETF 实时 provider | 固定沪深通配符请求段 | 不改成 Basic 逐代码请求 |
| Health / monitor | Health 读一次资格 snapshot；候选用 subquery；运行时取 enabled monitor pool 与 Basic 资格交集 | provider 批次、Basic 资格、业务监控池不是同一个集合 |
| 旧 ETF Review / seed / active pool | 已退场，没有 alias、回退或 Basic 替代审查页 | 不是待清理的当前消费者 |
| ETF 基准指数、公募基金、指数 active pool | 各有独立身份与用途 | 不因名称含 ETF/active/.OF 而纳入本专项删除 |

资格集中在 EtfBasicDAO，具体实现分为 SQL 筛选和内存分类，两者必须一致。一次操作固定日期/资格，不代表所有调用方共享一个全局数据库快照。

## 5. 删除与恢复边界

- 下游代码不在当前 Basic、处于 P/D、缺上市日或事实早于当前上市日：只报告，不自动删除。
- ETF 专用代码拉取结果或需要 ETF 主数据对齐的 Serving 若新发现旧 .OF：先核实源端交易所代码可用性和精确表/代码/行数，另行评审获准后才处理；不得原地改名或合并两个身份。源端尚不可用则记录 SOURCE_NOT_READY，不制造替代行。
- 源端全集型 Raw/core 及同口径直出 view、公募基金合法 .OF、历史 alert/stat 均不因 Basic 过滤而删除。
- 旧池物理 drop 已是历史动作；历史 create/drop migrations 保留，禁止恢复旧表或回滚到依赖它的代码。不涉及 Kopia、旧 Lake 或备份能力。
- 本专项无通用事实清理 service/CLI、delete manifest 或 apply。任何新物理删除都需要新的精确范围与授权。

## 6. 历史结果与后续核验

| 日期/对象 | 已记录结果 | 不能外推 |
| --- | --- | --- |
| 2026-08-28 源端与下游基线 | Basic 1,825 行，其中 .SH 1,030、.SZ 792、.OF 3；下游批准删除候选为 0 | 不是今天数量，不能把 3 条 .OF 固化为永久规则 |
| 2026-08-29 Basic TaskRun 9837 | Raw 1,829、Serving 1,826；14 字段集合/hash 对账通过 | 不代表未来每次发布已验收 |
| 2026-08-29 旧池退场 | 旧 5,708 行随整表删除；指数池保留 | 不是删除 monitor pool 或其他 active 模型的授权 |
| 分钟 TaskRun 10117 | 181 代码、1,336 units；指定区间补后 Preview 前后缀/action/unit 为 0 | 不是全历史、内部逐日或逐分钟完整性证明 |
| 消费者补验 | SH 10126、fund daily 10127 已通过；当时 SZ 自然调度和实时开市批次待验 | 不猜今天 Schedule/collector 状态，不为补文档自动执行任务 |

生产执行顺序、失败/取消留下的已提交数据、hash 和完整数值保留在 LLD §13；未来新范围补拉另用新 Preview 和独立生产授权，不沿用历史计划文件。

## 7. 维护与验证

修改此链须同步 D1–D20、LLD、受影响数据集文档和真实消费者；Definition/source 合同变化另按根 AGENTS 做全量审计。文档治理只做代码/测试/引用对账，既不改变子系统依赖矩阵，也不宣称完成上述缺证据的生产验收。

2026-09-10 合并范围与逐项迁移记录见 [治理账本](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md#architecture-three-batches-20260910)。
