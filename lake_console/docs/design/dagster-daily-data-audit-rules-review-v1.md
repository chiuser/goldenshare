# 本地 DG 数据审计：逐资产规则与触发评审 v1

状态：第 3.1 节股票分钟线、第 3.2 节通用指数分钟线 Raw、Silver，以及第 3.3 节股票前复权分钟 MACD/KDJ 及递推状态的审计口径已确认。对应[每日数据审计方案](dagster-daily-data-audit-wealth-data-center-plan-v1.md)。范围沿用 187 个资产的盘点，保留原先分到独立审计或待定的 73 项逐条记录。实际版本、数据齐备和性能待验证。

## 1. 谁触发，谁执行，什么时候算完成

**建议用本机 DG 的一个审计传感器，由现有 Dagster daemon 周期性评估。是轮询，但轮询的是 DG 已有记录，不是行情文件。** 传感器发现需要审计的版本时提交独立审计任务，实际读文件和核对数据的是这个任务。财势乾坤不启动轮询、不运行审计；每日总结的定时任务只汇总结果，也不是独立审计的触发者。[Dagster 传感器官方说明](https://dagster.io/docs/guides/automate/sensors)

| 步骤 | 负责人和实际动作 | 页面状态 |
|---|---|---|
| ① 发现当天需要审计的产出 | **本机 Dagster daemon** 每轮评估审计传感器。传感器先看允许运行的时间窗口，再限量批读已批准自动审计的资产和业务日的产出、上游完成及审计记录。每轮复查仍未提交的候选，不依赖某一个新事件再次出现；没有日更要求或已有同版有效结论则不提交。 | 已更新/超期等仍独立显示；齐备未核验的可显示「等上游」「等待审计窗口」或「规则未确认」。未提交不是已排队。 |
| ② 提交独立任务 | **审计传感器**在目标产出、必需上游和规则版本可绑定，且读取/并发预算允许时，提交对应资产、分区/截至日和频度的独立审计 job。它不触发生产资产、补数或重跑更新，也不注册新分区。手动提交是例外入口，走同一范围、权限和重复提交检查。 | 已排队，不冒充运行中。 |
| ③ 正式开跑 | **DG 的独立审计 job**取得获准的并发名额后，复核版本、实际能读取的范围及窗口；如果日更仍占用同一资源、剩余窗口不足或文件已换版，不能开始重读。只在这一步读取业务文件。 | 运行中；未开跑可注明资源冲突/超窗，被新版本替代注明原因。 |
| ④ 发布和吸收结果 | **独立审计 job**完成唯一键、差集或已批准的其他核验，再检查输入输出版本未变，才留下可消费的结论。**每日总结**按上海时间独立生成，不等全部审计；完成后的结果补入同一业务日的最新视图，保留核验时间，不改写当晚原总结的时点。 | 已完成是任务状态；结果另列合同范围齐备、仅与上游一致、已确认缺口或未核验。失败/取消不产生齐备结论。 |

- 自动提交的同一审计身份是资产、业务日/分区/实际截至日、频度、目标及所需上游的稳定发布版本、规则版本；与手动入口也要查同身份在途或已有结果。`run_key` 只用于同一传感器的去重，不从中解析执行参数，不把 DG 事件存储 ID 当业务版本。执行参数由已确认范围显式传入。参考[运行去重和身份约束](dagster-run-key-governance-low-level-design.md)。
- 每项通过业务规则、版本证据和读取预算评审后才可加入自动清单。无法重建过去某日的旧版本，就不以今天新版本替代。传感器默认不回扫历史；停机或错过窗口，保留未核验。失败不自动另开一个同身份任务；需要重试时在原范围上重新核对版本，次数与允许条件由 LLD 审批。诊断进度只保留小型游标，不把明细装进游标或反复搜历史事件。
- 轮询间隔、单轮最多发起多少任务、独立任务允许窗口和余量不能凭想象给定；以实际记录批量读取成本、已知日更结束时间和审计文件规模定。窗口到期仍未完成就如实显示，**不承诺都在当晚完成**。验收要覆盖「没有新事件但窗口打开」「同一版没有重复任务」「排队后换版」「启动前日更又占用资源」「网页关闭仍能触发」。

### 1.1 上游先审，下游复用结果

依赖上游齐备结论的独立审计按实际输入顺序进行。按业务日、频度及发布版本检查必需的上游证据。已有合格结果时直接复用。上游还没审完或版本对不上时，下游显示「等待上游核验」；上游已经确认缺口时，下游显示「上游有缺口」及受影响的依赖。两种情况都不提交下游审计，也不读取下游文件。下游的更新状态仍按本身的发布记录展示。只有上游补齐并通过核验，且新的证据与下游实际输入版本相符，才继续核验受影响的下游。

股票分钟线按这条顺序执行。**本地 Raw 五频负责核应有股票及逐根时点，Silver、股票分钟线前复权 Gold、MACD/KDJ 指标和递推状态、股票分钟线前复权九转等下游复用同版上游结果。** 下游独立审计只核本层应有股票是否覆盖、应有总行数与实有是否匹配，并复用原有生产检查结论。股票范围和行数按本层正式转换规则计算。汇总类产物按自身合同核总数，并使用其实际必需输入的齐备结论。证据优先读已有的检查与发布记录，只有所需统计缺失时才评估有界补充。

按本层实际输入判断影响。股票 5 分钟 Silver 同时依赖 5 分钟和 1 分钟 Raw。股票 15 分钟前复权 Gold 读取 5 分钟 Silver，120 分钟前复权 Gold 读取 60 分钟 Silver。停牌、身份映射、复权因子及前序状态等必要输入也按各资产实际版本确认。已明确获准的历史替代使用该次实际输入和范围。验收应覆盖上游未核验或有缺口时零下游文件读取、上游换版后下游证据尚未更新，以及其他输入已齐备的频度可继续。 [Silver 输入](../../orchestrator/src/orchestrator/defs/assets/stk_mins.py#L3191) · [前复权 Gold 输入频度](../../orchestrator/src/orchestrator/defs/run_contracts/cn_a_derived_minute_bars.py#L11)

## 2. 怎么评审每条规则

- **合同范围可评审**：能从现有合同构造应有集合；还须核实产出版本和实际读量。**相对规则可评审**：能独立于待验产物，从同版输入和转换合同构造输出；单独只得「仅与上游一致」。**只明确部分**：已有日期、请求或发布证据，但更广的应有对象/时点没有依据。**待应有依据**：没找到可独立判整套覆盖的合同依据，不执行凑数式审计。
- `D` 为所选资产口径的业务日，`F` 为该资产频度。需要检查分钟键的资产按业务键报缺键、多键和重复。股票分钟线下游采用第 1.1 节的上游齐备、原有检查、股票覆盖及总行数组合口径。来源允许的例外须有依据。资源不可读、版本无法关联或缺少判定证据时，相关范围标为未核验。上线时按适用规则验收正反例。

## 3. 原方案 73 项：逐资产待评审规则

原 73 项中，股票分钟 Raw 与 Silver 共 10 项、通用指数分钟 Raw 与 Silver 共 12 项、股票前复权分钟 MACD/KDJ 与递推状态共 14 项已确认审计口径，ETF 分钟 Raw 5 项优先复用已有检查。**其余 32 项仍需评审**，其中 17 项要先核实应有对象、时点或事件，15 项已有可评审的比较对象，需确认如何取得同版证据和完成对账。15 项含 5 项有固定合同范围、10 项可做同版输入对账。第 5.2 节另有 2 个轻量日更候选。

| 章节 | 还需核实应有范围 | 还需确认审计方法 |
|---|---:|---:|
| 3.4 指数周月线、东方财富板块分类与成分、国际指数日线 | 3 | 7 |
| 3.5 股票复权因子、基金源数据、资金流向 | 8 | 0 |
| 3.6 交易日历、基础信息、曾用名、身份和生命周期 | 3 | 7 |
| 3.7 停复牌及事件型资产 | 3 | 1 |

### 3.1 股票原始分钟线与 Silver（10 项）

**Raw 逐根，Silver 查股票覆盖和总行数。** 常规 Raw 日更优先复用已绑定到当次名单、频度及正式文件版本的代码覆盖证据。独立审计按各市场、来源和频度的应有时点逐键核对 Raw，仅读该日该频度所需列。同版证据不足的范围保留未核验，补录按获准范围核对。Silver 等必需输入齐备后，用已核验的当日股票日线、生命周期和最终停牌事实确认应有股票覆盖。再按同版 Raw 和 Silver 转换规则核应有与实有总行数。现有 Silver 对日线的引用检查只验证已见代码，整股缺失证据需要另行确认。 [Raw 写前代码覆盖](../../orchestrator/src/orchestrator/defs/assets/stk_mins.py#L1006) · [Silver 日线引用检查](../../orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py#L2429)

Silver 应有行数按正式转换规则确定，包含按有效期映射代码、全天停牌和 `15:00` 之后的行的剔除、去重、获准冻结历史及粗频合成。日常 5/15/30/60 分钟只在某股当天同频 Raw 经基础过滤后全无记录且有合格的 1 分钟整日输入时整日合成。原生粗频坏价重算保留原时间键。统计优先复用日更已记录的同版证据，缺少覆盖或计数证据时仅评估补该项统计。Raw 各来源的应有时点、合法空、历史例外、版本可用性及实际读量仍要核实。 [Silver 基础过滤](../../orchestrator/src/orchestrator/defs/assets/stk_mins.py#L1518) · [粗频合成及重算](../../orchestrator/src/orchestrator/defs/assets/stk_mins.py#L1684) · [冻结保留](../../orchestrator/src/orchestrator/defs/assets/stk_mins.py#L1997)

| 资产键 | 本项应有范围与检查 | 仍要定的事 |
|---|---|---|
| `raw_stk_mins_1m` | `D` 的 1 分钟请求对象与 1 分钟原生时点，逐键核对。 | 待应有依据：开收盘时点、停牌时点和零成交是否应回。 |
| `raw_stk_mins_5m` | `D` 的 5 分钟对象及原生时间标签。 | 待应有依据：分段边界和部分成交窗口是否应有。 |
| `raw_stk_mins_15m` | `D` 的 15 分钟对象及原生时间标签。 | 待应有依据：本频度缺报与运输完成怎么区分。 |
| `raw_stk_mins_30m` | `D` 的 30 分钟对象及原生时间标签。 | 待应有依据：本频度部分交易窗口、停复牌例外。 |
| `raw_stk_mins_60m` | `D` 的 60 分钟对象及原生时间标签。 | 待应有依据：本频度午间断点、盘中停牌例外。 |
| `silver_stk_mins_1m` | 同版 1 分钟 Raw 齐备后，核标准化及获准保留后的应有股票覆盖和总行数。 | 方法已确认，待验证同版覆盖和计数证据。 |
| `silver_stk_mins_5m` | 同版 5 分钟和 1 分钟 Raw 齐备后，核应有股票覆盖及标准化与整日合成的总行数。 | 同上。 |
| `silver_stk_mins_15m` | 同版 15 分钟和 1 分钟 Raw 齐备后，核应有股票覆盖及标准化与整日合成的总行数。 | 同上。 |
| `silver_stk_mins_30m` | 同版 30 分钟和 1 分钟 Raw 齐备后，核应有股票覆盖及标准化与整日合成的总行数。 | 同上。 |
| `silver_stk_mins_60m` | 同版 60 分钟和 1 分钟 Raw 齐备后，核应有股票覆盖及标准化与整日合成的总行数。 | 同上。 |

### 3.2 通用指数分钟线和 ETF 原始分钟线（17 项）

**通用指数 Raw 已确认。** 常规日更按交易日和 1、5、15、30、60 分钟分别判断。应有指数来自 DG 当次导入实际采用的 `ops.index_series_active(resource='index_mins')` 名单。Prod 默认用这个激活池逐指数、频度发请求，DG 导入也读这个池。历史补录使用当次获准的有效代码范围。已绑定到同日、同频和同一正式文件版本的发布结果可以证明代码覆盖，直接复用。名单哈希用于确认是哪一版。当次名单和有效覆盖证据均无法取得时，代码覆盖标为「未核验」。 [Prod 取码](../../../src/foundation/ingestion/unit_planner.py#L1972) · [DG 导入名单](../../orchestrator/src/orchestrator/defs/assets/index_mins_raw.py#L79) · [发布记录字段](../../orchestrator/src/orchestrator/defs/assets/index_mins.py#L68) · [现有代码差集](../../orchestrator/src/orchestrator/defs/assets/index_mins.py#L453)

常规交易日每只应有指数的分钟时点按下表分段生成。上海时间上午从 `09:30` 起每隔该频度取一点至 `11:30`，下午从 `13:00` 加一个频度开始至 `15:00`。根数按两个 120 分钟时段计算，上午含开盘时点，合计 `120 ÷ 频度分钟数 + 1 + 120 ÷ 频度分钟数`。2026-11-02 的 Prod 源验收对当批 530 只指数逐频核查过实际分钟时点。历史补录沿用当次已记录的合同。15、30、60 分钟仅在历史正式记录明确确认相应日期、频度的源在应有范围内全空并获准豁免时，才记为历史例外。缺文件或部分返回不足以证明源全空。 [分钟时点样本](../../orchestrator/tests/test_index_mins_replace_existing.py#L269) · [历史源端逐键验收](dagster-minute-raw-silver-staging-write-plan-and-low-level-design.md#106-任务18007及完成后源审计结果) · [历史源全空合同](dagster-index-mins-data-onboarding-low-level-design.md#L188)

同版分钟时点证据已齐全时直接复用。需要补核时由本机 DG 独立任务读取所选日、频度的本地 Raw 文件，只投影 `(ts_code, freq, trade_time)`。按已确认的代码范围逐键核对缺失、多出和重复。已有代码覆盖结论可用于确认实有代码集合与当次池完全一致。单次补核最多读一个该日该频度的行情文件，期望键数为当次审计范围内的指数数乘以该频度的每指数时点数，实际文件读取量及耗时待验证。齐备和更新分别记录。验收覆盖正常完整、代码全但缺 `14:00`、总数相同但时点错位、激活池换版、历史明确豁免和无证据缺档。 [Raw 日频文件路径](../../orchestrator/src/orchestrator/defs/paths.py#L1078)

**通用指数 Silver 已确认。** 正常交易日，1、5、15、30、60 分钟各继承对应 Raw 当次激活池的应有指数范围，按同版 Raw 标准化后的键对账。90 分钟继承同版 30 分钟 Silver 的应有范围，120 分钟继承同版 60 分钟 Silver 的应有范围，均逐指数检查合成需要的输入时点、开盘竞价锚点和输出结束键。五个 Raw 频度使用同一份 530 只指数的名单时，七个 Silver 频度各应有 530 只。上游少一只时，应有名单和数量仍以当次有效范围为准。 [Silver 写入和输入绑定](../../orchestrator/src/orchestrator/defs/assets/index_mins_silver.py#L115) · [90/120 分钟窗口合同](dagster-derived-minute-bars-90-120-contract-rebuild-low-level-design.md#22-90m-窗口)

缺口按同版证据判断。输入已有该键但 Silver 缺失，记 Silver 转换缺口。应有范围已确认且上游和 Silver 均缺该指数或时点，记录上游缺口及受影响的 Silver。只能证明与已绑定上游一致时，记录「仅与上游一致」。目标与输入版本无法关联时，转换对账记「未核验」。历史 15、30、60 分钟确有同频源全空的获准例外时，使用该次历史有效代码范围与同日 5 分钟 Raw 的实际绑定版本，按原合成规则核对。 [历史替代来源](../../orchestrator/src/orchestrator/defs/assets/index_mins_silver_repair.py#L235)

优先复用同版已有的输入、窗口和唯一键检查。现有检查对输出主要核对行数与生成窗口数，仍需证据证明具体输出键。需要补核时由本机 DG 独立任务只读当天的目标及对应来源文件，按 `(ts_code, freq, trade_time)` 验缺失、多出和重复，复用同版上游覆盖证据。单个频度按两份行情文件估算，已取得等价证据时可少读，实际读量和耗时待验证。验收覆盖漏整只指数、行数相同但时点错位、派生缺输入窗口以及获准的历史替代范围。 [现有 Silver 检查](../../orchestrator/src/orchestrator/defs/checks/index_mins_checks.py#L238) · [Silver 日频文件路径](../../orchestrator/src/orchestrator/defs/paths.py#L1227)

**ETF Raw 改为优先复用。** 之前只看了冻结股票池核验，漏了[五频度正式检查](../../orchestrator/src/orchestrator/defs/checks/etf_mins_checks.py#L315)。该检查在各频度使用当次冻结的 ETF 基础信息范围核整只缺失，并按[已注册时间规则](../../orchestrator/src/orchestrator/defs/run_contracts/etf_mins.py#L164)对实有代码检查分钟时点双向差异和重复键。应有代码缺失或时点差异为阻断项，整日零成交等符合合同的情况有单独告警。复用时须核同日、同频、目标发布版本、文件身份、基准快照和规则版本，同时保留原判定与告警。“检查通过”单独不足以说明是哪种结果。旧版本缺等价证据时记未核验。 [缺失与时点判定](../../orchestrator/src/orchestrator/defs/asset_guards/etf_mins_lake_readiness.py#L2242) · [检查与产出绑定](../../orchestrator/src/orchestrator/defs/asset_guards/etf_mins_lake_readiness.py#L1574)

| 资产键 | 本项应有范围与检查 | 仍要定的事 |
|---|---|---|
| `raw_index_mins_1m` | 当次指数名单 × `09:30–11:30`、`13:01–15:00`，每分钟一个时点，每只 241 个。 | 口径已确认，待验同版证据和读取开销。 |
| `raw_index_mins_5m` | 当次指数名单 × `09:30–11:30`、`13:05–15:00`，每 5 分钟一个时点，每只 49 个。 | 同上。 |
| `raw_index_mins_15m` | 当次指数名单 × `09:30–11:30`、`13:15–15:00`，每 15 分钟一个时点，每只 17 个。 | 同上；历史源全空按当次已确认例外处理。 |
| `raw_index_mins_30m` | 当次指数名单 × `09:30–11:30`、`13:30–15:00`，每 30 分钟一个时点，每只 9 个。 | 同上；历史源全空按当次已确认例外处理。 |
| `raw_index_mins_60m` | 当次指数名单 × `09:30`、`10:30`、`11:30`、`14:00`、`15:00`，每只 5 个。 | 同上；历史源全空按当次已确认例外处理。 |
| `silver_index_mins_1m` | 同日同版 1 分钟 Raw 应有指数及标准化后的业务键。 | 口径已确认，待验同版证据和读取开销。 |
| `silver_index_mins_5m` | 同日同版 5 分钟 Raw 应有指数及标准化后的业务键。 | 同上。 |
| `silver_index_mins_15m` | 同日同版 15 分钟 Raw 应有指数及标准化后的业务键。 | 同上；获准的历史替代按同日 5 分钟 Raw 对账。 |
| `silver_index_mins_30m` | 同日同版 30 分钟 Raw 应有指数及标准化后的业务键。 | 同上；获准的历史替代按同日 5 分钟 Raw 对账。 |
| `silver_index_mins_60m` | 同日同版 60 分钟 Raw 应有指数及标准化后的业务键。 | 同上；获准的历史替代按同日 5 分钟 Raw 对账。 |
| `silver_index_mins_90m` | 同版 30 分钟 Silver 应有指数，按合同核每个合成窗口及 `11:00`、`14:00`、`15:00` 输出键。 | 口径已确认，待验同版证据和读取开销。 |
| `silver_index_mins_120m` | 同版 60 分钟 Silver 应有指数，按合同核每个合成窗口及 `11:30`、`15:00` 输出键。 | 同上。 |
| `raw_etf_mins_1m` | 复用本版 ETF 基础信息范围及 1 分钟时点检查。 | 合同范围复用候选，待验同版运行证据。 |
| `raw_etf_mins_5m` | 复用本版 ETF 基础信息范围及 5 分钟时点检查。 | 同上。 |
| `raw_etf_mins_15m` | 复用本版 ETF 基础信息范围及 15 分钟时点检查。 | 同上。 |
| `raw_etf_mins_30m` | 复用本版 ETF 基础信息范围及 30 分钟时点检查。 | 同上。 |
| `raw_etf_mins_60m` | 复用本版 ETF 基础信息范围及 60 分钟时点检查。 | 同上。 |

### 3.3 股票前复权分钟 MACD/KDJ 及状态（14 项）

**已确认采用股票覆盖和总行数核对。** 按第 1.1 节先取得同版上游的齐备证据。上游齐备后，复用原有计算及发布检查，核对本层应有股票覆盖与总行数。缺少本层统计证据时，记录相关范围待核验。

**指标七项。** 每根前复权 K 线应产出一行指标。应有总行数取同日、同频、同版股票前复权分钟线 Gold 的当日 K 线行数，实际取该版 MACD/KDJ 的当日行数。复用已有的产物合同检查，以及来源行数和指标行数比较结果。 [指标覆盖检查](../../orchestrator/src/orchestrator/defs/checks/stk_mins_qfq_macd_kdj_checks.py#L227)

**状态七项。** 上游包括同版当日指标和实际使用的前一应有交易日状态。日常应有行数为「前序应承接状态的股票」与「当天有指标的股票」合并去重后的股票数，每股一行。已有状态的股票当天无行情时仍计一行，首次初始化按当次规则确定前序范围。历史修复按获准的日期、频度和股票范围核对同一口径的应有与实际行数。现有正式检查已核当日指标的末条时间及状态文件，但行数只要求不少于当天有指标的股票数，尚缺计入承接状态后的预期总行数。先找能绑定到该版的计数证据。需要补充证据时，评估从日更已读入的前序状态和当日输入中算出并记录预期总数。缺该证据的版本显示未核验。 [状态生成规则](../../orchestrator/src/orchestrator/defs/stk_mins_qfq_macd_kdj.py#L676) · [前序交易日规则](../../orchestrator/src/orchestrator/defs/assets/stk_mins_qfq_macd_kdj.py#L289) · [现有状态检查](../../orchestrator/src/orchestrator/defs/checks/stk_mins_qfq_macd_kdj_checks.py#L417)

| 资产键 | 应有总行数 | 状态 |
|---|---|---|
| `gold_stk_mins_qfq_macd_kdj_1m` | 同版前复权 Gold 1 分钟当日 K 线总数。 | 口径已确认，优先复用已有检查记录。 |
| `gold_stk_mins_qfq_macd_kdj_5m` | 同版前复权 Gold 5 分钟当日 K 线总数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_15m` | 同版前复权 Gold 15 分钟当日 K 线总数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_30m` | 同版前复权 Gold 30 分钟当日 K 线总数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_60m` | 同版前复权 Gold 60 分钟当日 K 线总数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_90m` | 同版前复权 Gold 90 分钟当日 K 线总数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_120m` | 同版前复权 Gold 120 分钟当日 K 线总数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_state_1m` | 1 分钟当日有指标及前序应承接状态的合并去重股票数。 | 口径已确认，待核可复用的应有总行数。 |
| `gold_stk_mins_qfq_macd_kdj_state_5m` | 5 分钟当日有指标及前序应承接状态的合并去重股票数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_state_15m` | 15 分钟当日有指标及前序应承接状态的合并去重股票数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_state_30m` | 30 分钟当日有指标及前序应承接状态的合并去重股票数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_state_60m` | 60 分钟当日有指标及前序应承接状态的合并去重股票数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_state_90m` | 90 分钟当日有指标及前序应承接状态的合并去重股票数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_state_120m` | 120 分钟当日有指标及前序应承接状态的合并去重股票数。 | 同上。 |

### 3.4 指数周月、板块分类/成分和国际指数日线（10 项）

**对先前笼统表述的补正。** 指数周月线的正式文件检查主要验增量字段、键及行数，但[Raw 生产者](../../orchestrator/src/orchestrator/defs/io/index_period_writer.py#L70)已经逐个验证请求对象的返回，固定名单来自[周期合同](../../orchestrator/src/orchestrator/defs/run_contracts/index_period.py#L86)，合同明示 `899050.BJ` Raw 可合法为空；[Silver 生产者](../../orchestrator/src/orchestrator/defs/io/index_period_writer.py#L428)按有效上市名单及 `daily/period/repair` 模式处理。它们不是「没有应有名单」，而是还要确认能否从本次发布证据绑定所验键而无需回读 `full` 文件。分区触发时间以[周期任务现行调度](../../orchestrator/src/orchestrator/defs/sensors/index_period_update_job_sensors.py#L66)为依据：周 Raw 到实际周末，月 Raw 在下月首个交易日交付上月；不要和 Silver 日更混用。

| 资产键 | 本项规则 / 检查方法 | 足以判定什么、仍缺什么 |
|---|---|---|
| `raw_index_weekly` | 本周最后交易日，按本版周期名单查 `(ts_code, 期末日)`；已授权可空代码可有可无，其他请求必有且唯一。 | 合同范围可评审；先验证交付记录能否证明同一版增量的键，不能以文件总行数代替。 |
| `silver_index_weekly` | 以周内第一交易日标识当期，查 `ts_code` 与实际截至日；按当天上市有效名单及生成模式，区分期末正式 Raw、已保留期末数据和按日线合成。 | 合同范围可评审；核实版本与模式，后续更晚周内产出不能替所选日原样验收。 |
| `raw_index_monthly` | 上月最后交易日，按本版周期名单查月 Raw 期末键；允许可空代码，其余必有；在下月首交易日才考核交付。 | 合同范围可评审；自然月最后一天不自动当期末交易日或发布日。 |
| `silver_index_monthly` | 按月内第一交易日及所选有效截至日核同版有效上市指数键；正式、保留、合成分别按模式验。 | 合同范围可评审；不能用新月覆盖状态替代历史截至快照。 |
| `raw_tushare_dc_index` | 同日板块分类键 `(ts_code, trade_date)`；按冻结的应发布板块名单和合约认可的占位规则对照。 | 待应有依据：现行类别与合法性检查不提供独立全量板块名单。 |
| `silver_dc_index` | 以同版 Raw 按[标准化和拒绝规则](../../orchestrator/src/orchestrator/defs/assets/dc_board_silver.py#L143)产生预期分类键，与 Silver 对照；只排除明确允许的拒绝项。 | 相对规则可评审；上游没有的板块不能靠 Silver 推断。 |
| `raw_tushare_dc_member` | 对同日目标板块和冻结来源的 `(trade_date, ts_code, con_code)` 成分关系逐键核对。 | 待应有依据：同日分类表可限制板块范围，不能告诉我们每个板块全部成分或合法空板块。 |
| `silver_dc_member` | 同版 Raw 成分按实际规范化、去重和拒绝规则形成应有关系，查缺、多键；同日分类只作关联合法性依据。 | 相对规则可评审；需验证同版 Raw 和拒绝政策，不能拿引用通过替代成分覆盖。 |
| `raw_index_global` | 按每市场的本地交易归属与批准发布阶段确定哪些 `(ts_code, trade_date)` 应有；按市场分别验。 | 只明确部分：[本机按阶段发起任务](../../orchestrator/src/orchestrator/defs/run_contracts/index_global.py#L139)，阶段执行/空响应不证明各市场均已完成；仍缺逐市场合法休市、迟报依据。 |
| `silver_index_global` | 按与本批关联的 Raw、同一目标日期及实际标准化字段、键对账；只用已规定过滤。 | 相对规则可评审；若 Raw 只完成部分市场，不把 Silver 一致写成全市场齐备。 |

### 3.5 复权因子、基金源数据和资金流向（8 项）

[基金日线/基金复权因子生产者](../../orchestrator/src/orchestrator/defs/assets/etf_daily.py#L141)留有请求、来源行数和候选文件等交付信息。先看能否复用同版完整分页交付及实际文件绑定；这仅证明收到的结果没有丢失，不证明源没漏产品。资金流向的[业务键和请求范围](../../orchestrator/src/orchestrator/defs/run_contracts/moneyflow_daily.py#L53)按源区分；两次返回相同、数量正常或覆盖到几个类别，都不等于每个对象必有。下列均按当天单分区估算；缺依据的任务不能先上后台扫一遍找「应有」。

| 资产键 | 本项规则 / 检查方法 | 仍需确认 |
|---|---|---|
| `raw_tushare_adj_factor` | 同日比较 `(ts_code, trade_date)`；如仅有冻结源批次，先验发布保全，不套用 Silver 生命周期过滤当 Raw 范围。 | 待应有依据：源端对象池、停牌/上市退市日期和该源是否预期出因子。 |
| `raw_tushare_fund_adj` | 同日实际键与冻结的完整分页交付键对账；不可拿基金日线的实有代码做应有因子。 | 只明确部分：分页完成与全体应出因子的基金名单是两回事。 |
| `raw_tushare_fund_daily` | 同日实际键与冻结的完整分页交付键对账；保留基金全集与 ETF 子集的区别。 | 只明确部分：基金日线实际发布范围、停牌和合法空仍需源依据。 |
| `raw_tushare_moneyflow` | 按同日 `(trade_date, ts_code)`；复用收到的范围和发布证据，再与批准的个股源名单核对。 | 待应有依据：普通个股资金流向的应发布证券范围及例外，不套同花顺或股票日线名单。 |
| `raw_tushare_moneyflow_dc` | 同日 `(trade_date, ts_code)` 对照东方财富个股资金流向自身版本化范围。 | 待应有依据：东方财富个股覆盖与停牌/适用市场，不用另一来源补名单。 |
| `raw_tushare_moneyflow_cnt_ths` | 同日 `(trade_date, ts_code)` 与本次可发布的同花顺概念板块列表核对。 | 待应有依据：同花顺概念范围、板块上线与合法缺报；不用东方财富板块清单。 |
| `raw_tushare_moneyflow_ind_ths` | 同日 `(trade_date, ts_code)` 与这一接口适用的同花顺行业列表核对。 | 待应有依据：行业层级、变更及可空例外；不用概念名单。 |
| `raw_tushare_moneyflow_ind_dc` | 行业、概念、地域分别核收到的对象；业务键 `(trade_date, content_type, name)`，不能用一个类别多出来的记录抵另一个类别缺失。 | 待应有依据：三类各自应有名称、改名/合并及合法空；只请求了三类不证明对象全。 |

### 3.6 日历、基础信息、曾用名、身份和生命周期（10 项）

实际单位是某次发布的**快照版本**，不是把全表当作 `D` 单日文件。某些快照本身有日更要求（如股票基础信息），应按该资产更新合同判新鲜，不等于每天重审历史明细。未换版复用有效结果；旧版不存在时不得将新版当旧日证据。

| 资产键 | 本项规则 / 检查方法 | 足以判定什么、仍缺什么 |
|---|---|---|
| `raw_tushare_trade_calendar` | [现行生产合同](../../orchestrator/src/orchestrator/defs/assets/calendar.py#L105)请求 SSE、以本次记录的起止自然日为闭区间，验 `(exchange, cal_date)` 每天一条；休市也要有日历行，开休市标志和首尾边界按合同验。 | 合同范围可评审；可以证明覆盖日期没有漏，不证明开闭市值与交易所公告完全相同。无需等市场收盘才审发布的日历，也不拿新年度区间覆盖旧版。 |
| `silver_trade_calendar` | 用同版 Raw 标准化日期后验 `(exchange, trade_date)` 逐日一致，并覆盖该版批准区间。 | 相对规则可评审；Raw 区间校验通过后可继承；可先确认只需读日期投影而不是日级全表复跑。 |
| `raw_tushare_index_basic` | [现行请求](../../orchestrator/src/orchestrator/defs/assets/index_basic.py#L163)无市场筛选；校验冻结交付的指数键、范围与重复，不自行按某个市场缩小。 | 待应有依据：源镜像和全市场有效/终止指数覆盖不是同一结论，需明确该版源合同。 |
| `silver_index_basic` | 同版 Raw 按标准化身份、市场、生命周期转换，比较目标唯一指数键与应保留状态。 | 相对规则可评审；原始上市/终止错误不由 Silver 对账证明。 |
| `raw_tushare_stock_basic` | [本次源范围](../../orchestrator/src/orchestrator/defs/assets/stock_basic.py#L129)含 `L/D/P/G`，不是只取当前上市；若有冻结交付先按 `ts_code` 校验该版保全。 | 待应有依据：源名单对各状态是否完整及同一股票的状态冲突，不能用当前上市 Silver 反推 Raw。 |
| `silver_stock_basic` | 对同版 Raw 应用[当前上市人民币股票投影](../../orchestrator/src/orchestrator/defs/duckdb_sql.py#L186)，按 `ts_code` 双向核对。 | 相对规则可评审；不能误排除实际应上市对象，也不能把此表解释为历史生命周期齐备。 |
| `raw_tushare_namechange` | 按本次公告日期窗口检查采集范围可连续、切窗无遗漏；按实际合同去完全重复行，复用冻结来源交付对账。见[生产者](../../orchestrator/src/orchestrator/defs/assets/namechange.py#L195)。 | 只明确部分：窗口完成不证明该范围内所有公告事件都被源发布；某窗口无事件可合法为空，不能用当前简称反推所有曾用名。 |
| `silver_namechange` | 同版 Raw、当前股票基础信息和正式身份种子，按[支持代码及获准的时间线规则](../../orchestrator/src/orchestrator/defs/assets/namechange.py#L264)生成应有事件和区间，再对目标。 | 相对规则可评审；保留合法开区间/公告优先级，不用 Raw 总行数核准标准时间线。 |
| `silver_stock_identity_map` | 同版生命周期中的每个源代码自映射，加[种子批准的历史代码映射](../../orchestrator/src/orchestrator/defs/assets/stock_identity_map.py#L76)，并使用同版曾用名证据；对照映射对及有效边界。 | 相对规则可评审；没有种子/事实的历史身份不得自己推断；不把代码数相等当映射正确。 |
| `silver_stock_lifecycle` | 以同版 Raw 股票基础信息及[生命周期投影规则](../../orchestrator/src/orchestrator/defs/duckdb_sql.py#L247)核各代码上市、退市有效边界与类别。 | 相对规则可评审；保留历史和已终止对象，不能按 `silver_stock_basic` 当前名单作基准；Raw 缺对象不证明下游全。 |

### 3.7 停复牌及事件型资产（4 项）

| 资产键 | 本项规则 / 检查方法 | 足以判定什么、仍缺什么 |
|---|---|---|
| `raw_tushare_suspend_d` | 按 `D` 对照当次可信发布的停复牌事件集合；类型及停牌时段是判别事件的组成项。生产[读取单日源](../../orchestrator/src/orchestrator/defs/assets/suspend_d.py#L490)。允许真实无事件；必须有来源交付完成证据才能区分合法零行和未读到。 | 只明确部分：需要独立停复牌事件依据才能确认源漏报。不能把全市场股票都设为应有停复牌记录。 |
| `silver_stock_suspend_daily` | 以同日同版 Raw、命中该日的已批准历史全日停牌事实、停牌时段修正规则得到最终输出，双向核事件及修正。先复用[写入时已有的结果与输入身份](../../orchestrator/src/orchestrator/defs/assets/suspend_d.py#L372)，有结论且能绑定就不再次运行。 | 相对规则可评审；完全对上只证明最终标准化和规则合成，不能证明 Raw 源端没漏报；禁止复用已退役的历史修正入口。 |
| `raw_tushare_stk_nineturn` | 按源码[当天日频源交付](../../orchestrator/src/orchestrator/defs/assets/stk_nineturn.py#L79)核所属日期、频度和正式业务键；如果有可信冻结源收据才验相对交付。 | 待应有依据：该源应覆盖的股票/信号范围，不能把所有上市股票都当必须有或反过来假定整日合法为空。 |
| `gold_major_index_quantitative_structure` | 现有[产物规则](../../orchestrator/src/orchestrator/defs/io/major_index_quantitative_structure.py#L237)证明指定日唯一结果行、成功标记与已记录事件合法。要证明事件无遗漏须另有可信期望事件或经独立验证的输入/执行证据；不从结果自己生成期望。 | 只明确部分：可复用单日结果已交付；成功与空事件不等于验过应有事件。不能为每日摘要全量重跑跨期算法。 |

## 4. 评审如何关单

每个资产要确认业务日和适用起止、目标版本及上游身份、应有对象和关键时间、合法空与例外、反例、读取的文件和键列以及触发方式。已有确定范围的指数周月线和交易日历，后续先用同版发布记录验证能否直接复用。任何自动执行须在业务规则、版本证据和读取预算通过后单独确认。

按每类规则选择验收反例。按键对账的资产应覆盖总行数相同但有缺失、重复或多出。第 3.3 节应覆盖上游有缺口但行数相同、目标总数不符、缺少前序状态承接计数和版本换版。其他资产按适用情况覆盖整只股票或板块缺失、休市、有效空事件、合法分钟例外与周期交付窗口。结论限定在已核验的资产范围。

## 5. 其他 114 项：逐资产复用口径、轻量补项与范围外

### 5.1 原 105 项复用候选

以下保留原 105 项的复用依据。另有第 3.2 节 5 个 ETF 分钟 Raw 和第 3.3 节 7 个股票前复权分钟 MACD/KDJ 指标优先复用，共 117 项。每行所列范围是可接受结论的上限，使用时须核对同版证据和频度。

| 资产键 | 可复用结论的范围 | 不能据此推断 | 代码 |
|---|---|---|---|
| `silver_adj_factor` | **合同范围**：按生命周期定义必需与允许代码范围，核对缺码、多码，并对照筛选后 Raw。 | 以合同启用日期、生命周期与 Raw 版本为限，不是停牌表或所有历史日期均齐备的证明。 | [依据](../../orchestrator/src/orchestrator/defs/checks/adj_factor_checks.py#L760) |
| `raw_tushare_stock_daily` | **合同范围**：按验收时 Silver 股票基础信息的当前上市人民币股票、上市起日及同日全天停牌，核对缺码和多码。 | Raw 把退市日期置空且源名单只取当前上市，不代表历史日期当时应有的全部股票；不能代替 Silver 历史生命周期规则。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stock_daily_checks.py#L41) |
| `silver_stock_daily` | **合同范围**：按正式股票生命周期、市场起点和同日全天停牌计算应有范围，实际代码名单双向比对。 | 以对应版本的生命周期和停牌事实为前提；不能替代其他周期或数据层检查。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stock_daily_checks.py#L1135) |
| `silver_dc_industry_hierarchy` | **合同范围**：按固定三级行业基线与指定板块分类参考双向匹配，再与输出节点双向比对。 | 只证明这份基线及参考范围齐备；不证明每日板块行情或板块成分。 | [依据](../../orchestrator/src/orchestrator/defs/checks/dc_industry_hierarchy_checks.py#L132) |
| `silver_etf_adj_factor` | **合同范围**：现有必过检查包含冻结 Basic 范围的代码覆盖与 Raw 标准化双向差集。 | 只证明覆盖规则所要求的 ETF 及相应日期，不代表全部基金或所有历史快照。 | [依据](../../orchestrator/src/orchestrator/defs/checks/etf_daily_checks.py#L962) |
| `raw_tushare_idx_factor_pro` | **合同范围**：使用按日期生效的独立指数技术因子代码范围，对目标选择结果验缺码。 | 仅指支持名单及该原生交易日，不指全市场指数。 | [依据](../../orchestrator/src/orchestrator/defs/checks/idx_factor_pro_checks.py#L214) |
| `raw_index_daily` | **合同范围**：实际指数代码与 DG 当时已登记的指数代码双向比对，缺码和多码均不允许。 | 不是全市场指数，也不证明旧日期采用了当时应有的名单；要保留本次名单范围。 | [依据](../../orchestrator/src/orchestrator/defs/checks/index_daily_checks.py#L387) |
| `silver_index_factor_pro` | **合同范围**：同一次 Silver 检查重新用有效指数名单严格验证 Raw，验证 Silver 范围，再检查两边主键、字段和数值转换。 | 只证明合同支持的指数技术因子名单；仍须绑定该次 Raw 和 Silver 版本。 | [依据](../../orchestrator/src/orchestrator/defs/checks/idx_factor_pro_checks.py#L104) |
| `gold_major_index_mins_120m` | **合同范围**：向 Gold 校验显式传入按日期生效的主要指数名单，按频度固定时点双向验键。 | 不是全市场指数，也不等于价格和上游所有原始分钟都被证明正确。 | [依据](../../orchestrator/src/orchestrator/defs/checks/major_index_mins_gold_checks.py#L27) |
| `gold_major_index_mins_15m` | **合同范围**：向 Gold 校验显式传入按日期生效的主要指数名单，按频度固定时点双向验键。 | 不是全市场指数，也不等于价格和上游所有原始分钟都被证明正确。 | [依据](../../orchestrator/src/orchestrator/defs/checks/major_index_mins_gold_checks.py#L27) |
| `gold_major_index_mins_1m` | **合同范围**：向 Gold 校验显式传入按日期生效的主要指数名单，按频度固定时点双向验键。 | 不是全市场指数，也不等于价格和上游所有原始分钟都被证明正确。 | [依据](../../orchestrator/src/orchestrator/defs/checks/major_index_mins_gold_checks.py#L27) |
| `gold_major_index_mins_30m` | **合同范围**：向 Gold 校验显式传入按日期生效的主要指数名单，按频度固定时点双向验键。 | 不是全市场指数，也不等于价格和上游所有原始分钟都被证明正确。 | [依据](../../orchestrator/src/orchestrator/defs/checks/major_index_mins_gold_checks.py#L27) |
| `gold_major_index_mins_5m` | **合同范围**：向 Gold 校验显式传入按日期生效的主要指数名单，按频度固定时点双向验键。 | 不是全市场指数，也不等于价格和上游所有原始分钟都被证明正确。 | [依据](../../orchestrator/src/orchestrator/defs/checks/major_index_mins_gold_checks.py#L27) |
| `gold_major_index_mins_60m` | **合同范围**：向 Gold 校验显式传入按日期生效的主要指数名单，按频度固定时点双向验键。 | 不是全市场指数，也不等于价格和上游所有原始分钟都被证明正确。 | [依据](../../orchestrator/src/orchestrator/defs/checks/major_index_mins_gold_checks.py#L27) |
| `gold_major_index_mins_90m` | **合同范围**：向 Gold 校验显式传入按日期生效的主要指数名单，按频度固定时点双向验键。 | 不是全市场指数，也不等于价格和上游所有原始分钟都被证明正确。 | [依据](../../orchestrator/src/orchestrator/defs/checks/major_index_mins_gold_checks.py#L27) |
| `raw_major_index_mins_15m` | **合同范围**：按有效主要指数名单和来源交易时段对规定严格覆盖的代码核对缺键、多键。 | 按 Raw 合同排除历史替代／放宽代码的必齐要求；不是所有许可代码均具有完整源分钟。 | [依据](../../orchestrator/src/orchestrator/defs/io/major_index_mins_quality.py#L314) |
| `raw_major_index_mins_1m` | **合同范围**：按有效主要指数名单和来源交易时段对规定严格覆盖的代码核对缺键、多键。 | 按 Raw 合同排除历史替代／放宽代码的必齐要求；不是所有许可代码均具有完整源分钟。 | [依据](../../orchestrator/src/orchestrator/defs/io/major_index_mins_quality.py#L314) |
| `raw_major_index_mins_30m` | **合同范围**：按有效主要指数名单和来源交易时段对规定严格覆盖的代码核对缺键、多键。 | 按 Raw 合同排除历史替代／放宽代码的必齐要求；不是所有许可代码均具有完整源分钟。 | [依据](../../orchestrator/src/orchestrator/defs/io/major_index_mins_quality.py#L314) |
| `raw_major_index_mins_5m` | **合同范围**：按有效主要指数名单和来源交易时段对规定严格覆盖的代码核对缺键、多键。 | 按 Raw 合同排除历史替代／放宽代码的必齐要求；不是所有许可代码均具有完整源分钟。 | [依据](../../orchestrator/src/orchestrator/defs/io/major_index_mins_quality.py#L314) |
| `raw_major_index_mins_60m` | **合同范围**：按有效主要指数名单和来源交易时段对规定严格覆盖的代码核对缺键、多键。 | 按 Raw 合同排除历史替代／放宽代码的必齐要求；不是所有许可代码均具有完整源分钟。 | [依据](../../orchestrator/src/orchestrator/defs/io/major_index_mins_quality.py#L314) |
| `silver_major_index_mins_120m` | **合同范围**：按有效主要指数名单及频度时段核对缺码、多码、缺时点和额外时点。 | 只覆盖已批准名单、合约时点、频度及当次日期。 | [依据](../../orchestrator/src/orchestrator/defs/io/major_index_mins_quality.py#L441) |
| `silver_major_index_mins_15m` | **合同范围**：按有效主要指数名单及频度时段核对缺码、多码、缺时点和额外时点。 | 只覆盖已批准名单、合约时点、频度及当次日期。 | [依据](../../orchestrator/src/orchestrator/defs/io/major_index_mins_quality.py#L441) |
| `silver_major_index_mins_1m` | **合同范围**：按有效主要指数名单及频度时段核对缺码、多码、缺时点和额外时点。 | 只覆盖已批准名单、合约时点、频度及当次日期。 | [依据](../../orchestrator/src/orchestrator/defs/io/major_index_mins_quality.py#L441) |
| `silver_major_index_mins_30m` | **合同范围**：按有效主要指数名单及频度时段核对缺码、多码、缺时点和额外时点。 | 只覆盖已批准名单、合约时点、频度及当次日期。 | [依据](../../orchestrator/src/orchestrator/defs/io/major_index_mins_quality.py#L441) |
| `silver_major_index_mins_5m` | **合同范围**：按有效主要指数名单及频度时段核对缺码、多码、缺时点和额外时点。 | 只覆盖已批准名单、合约时点、频度及当次日期。 | [依据](../../orchestrator/src/orchestrator/defs/io/major_index_mins_quality.py#L441) |
| `silver_major_index_mins_60m` | **合同范围**：按有效主要指数名单及频度时段核对缺码、多码、缺时点和额外时点。 | 只覆盖已批准名单、合约时点、频度及当次日期。 | [依据](../../orchestrator/src/orchestrator/defs/io/major_index_mins_quality.py#L441) |
| `silver_major_index_mins_90m` | **合同范围**：按有效主要指数名单及频度时段核对缺码、多码、缺时点和额外时点。 | 只覆盖已批准名单、合约时点、频度及当次日期。 | [依据](../../orchestrator/src/orchestrator/defs/io/major_index_mins_quality.py#L441) |
| `gold_major_index_mins_technical_state_120m` | **合同范围**：对按日生效的主要指数名单双向验状态代码，并核对各状态最后时点和适用的递推连续性。 | 本资产齐备粒度是当日、频度、指数代码的状态行；不是行情或指标逐根分钟覆盖。 | [依据](../../orchestrator/src/orchestrator/defs/checks/major_index_mins_technical_checks.py#L249) |
| `gold_major_index_mins_technical_state_15m` | **合同范围**：对按日生效的主要指数名单双向验状态代码，并核对各状态最后时点和适用的递推连续性。 | 本资产齐备粒度是当日、频度、指数代码的状态行；不是行情或指标逐根分钟覆盖。 | [依据](../../orchestrator/src/orchestrator/defs/checks/major_index_mins_technical_checks.py#L249) |
| `gold_major_index_mins_technical_state_1m` | **合同范围**：对按日生效的主要指数名单双向验状态代码，并核对各状态最后时点和适用的递推连续性。 | 本资产齐备粒度是当日、频度、指数代码的状态行；不是行情或指标逐根分钟覆盖。 | [依据](../../orchestrator/src/orchestrator/defs/checks/major_index_mins_technical_checks.py#L249) |
| `gold_major_index_mins_technical_state_30m` | **合同范围**：对按日生效的主要指数名单双向验状态代码，并核对各状态最后时点和适用的递推连续性。 | 本资产齐备粒度是当日、频度、指数代码的状态行；不是行情或指标逐根分钟覆盖。 | [依据](../../orchestrator/src/orchestrator/defs/checks/major_index_mins_technical_checks.py#L249) |
| `gold_major_index_mins_technical_state_5m` | **合同范围**：对按日生效的主要指数名单双向验状态代码，并核对各状态最后时点和适用的递推连续性。 | 本资产齐备粒度是当日、频度、指数代码的状态行；不是行情或指标逐根分钟覆盖。 | [依据](../../orchestrator/src/orchestrator/defs/checks/major_index_mins_technical_checks.py#L249) |
| `gold_major_index_mins_technical_state_60m` | **合同范围**：对按日生效的主要指数名单双向验状态代码，并核对各状态最后时点和适用的递推连续性。 | 本资产齐备粒度是当日、频度、指数代码的状态行；不是行情或指标逐根分钟覆盖。 | [依据](../../orchestrator/src/orchestrator/defs/checks/major_index_mins_technical_checks.py#L249) |
| `gold_major_index_mins_technical_state_90m` | **合同范围**：对按日生效的主要指数名单双向验状态代码，并核对各状态最后时点和适用的递推连续性。 | 本资产齐备粒度是当日、频度、指数代码的状态行；不是行情或指标逐根分钟覆盖。 | [依据](../../orchestrator/src/orchestrator/defs/checks/major_index_mins_technical_checks.py#L249) |
| `gold_market_major_indices_daily` | **合同范围**：按日期确定适用固定主要指数名单，检查是否全覆盖并核对行数、唯一性。 | 只证明主要指数名单，不证明全部指数行情。 | [依据](../../orchestrator/src/orchestrator/defs/checks/market_major_indices_checks.py#L353) |
| `silver_stock_suspend_confirmed` | **合同范围**：校验目标版本绑定的正式文件与审批确认内容／指纹一致。 | 只证明已批准的固定停牌事实按批准版本发布；不是全历史停牌全集。此资产无命名产出任务。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stock_suspend_confirmed_checks.py#L143) |
| `raw_tushare_anns_d` | **相对交付**：按公告日期对冻结的来源分页记录和实际交付文件对账，验证发布与文件身份；合同允许合法空结果。 | 只能证明已取得的冻结分页按规则交付，不能独立证明源端没有漏披露。 | [依据](../../orchestrator/src/orchestrator/defs/checks/anns_d_checks.py#L153) |
| `ch_share_fact_market_breadth_daily` | **相对交付**：核对当日唯一汇总行及与 Gold／本地 ClickHouse 的发布内容。 | 证明汇总行交付，不证明上游市场股票键齐全。 | [依据](../../orchestrator/src/orchestrator/defs/checks/clickhouse_serving_checks.py#L534) |
| `raw_tushare_daily_basic` | **相对交付**：日更覆盖当前验证过的股票日线代码，并检查必需涨跌停状态及文件指纹；历史分支验证 Prod 导出交付证据。 | 两种更新方式的证据不一样；历史通过不是逐股对独立名单重新核验。 | [依据](../../orchestrator/src/orchestrator/defs/daily_basic_raw_io.py#L96) |
| `gold_dc_daily_technical` | **相对交付**：逐日与 Silver 板块行情比较业务键双向差集，另验输出及预热规则。 | 板块行情本身如缺板块，本检查不能证明市场覆盖。 | [依据](../../orchestrator/src/orchestrator/defs/asset_guards/dc_daily_technical_quality.py#L194) |
| `raw_tushare_etf_basic` | **相对交付**：按已接收来源快照的行数、内容指纹和键核对发布文件。 | 来源响应本身漏了哪些 ETF，指纹无法发现。 | [依据](../../orchestrator/src/orchestrator/defs/checks/etf_basic_checks.py#L330) |
| `silver_etf_basic` | **相对交付**：绑定特定 Raw 快照审核过滤、键和内容指纹。 | 只保证绑定的 Raw 快照按规则标准化，不是历史逐日 ETF 名单。 | [依据](../../orchestrator/src/orchestrator/defs/checks/etf_basic_checks.py#L526) |
| `silver_etf_daily` | **相对交付**：逐日与 ETF Basic 过滤后的 Raw 基金日线双向对账。 | ETF Basic 代码覆盖另有非阻断警告，任务成功不保证这项无缺口；即使警告通过也要限定该次范围。 | [依据](../../orchestrator/src/orchestrator/defs/checks/etf_daily_checks.py#L962) |
| `silver_etf_mins_15m` | **相对交付**：Silver 与绑定 Raw 的主键和 11 个字段双向等价。 | Raw 允许有已记录缺口，Silver 等价不能消除这些缺口。 | [依据](../../orchestrator/src/orchestrator/defs/checks/etf_mins_checks.py#L494) |
| `silver_etf_mins_1m` | **相对交付**：Silver 与绑定 Raw 的主键和 11 个字段双向等价。 | Raw 允许有已记录缺口，Silver 等价不能消除这些缺口。 | [依据](../../orchestrator/src/orchestrator/defs/checks/etf_mins_checks.py#L494) |
| `silver_etf_mins_30m` | **相对交付**：Silver 与绑定 Raw 的主键和 11 个字段双向等价。 | Raw 允许有已记录缺口，Silver 等价不能消除这些缺口。 | [依据](../../orchestrator/src/orchestrator/defs/checks/etf_mins_checks.py#L494) |
| `silver_etf_mins_5m` | **相对交付**：Silver 与绑定 Raw 的主键和 11 个字段双向等价。 | Raw 允许有已记录缺口，Silver 等价不能消除这些缺口。 | [依据](../../orchestrator/src/orchestrator/defs/checks/etf_mins_checks.py#L494) |
| `silver_etf_mins_60m` | **相对交付**：Silver 与绑定 Raw 的主键和 11 个字段双向等价。 | Raw 允许有已记录缺口，Silver 等价不能消除这些缺口。 | [依据](../../orchestrator/src/orchestrator/defs/checks/etf_mins_checks.py#L494) |
| `silver_index_daily` | **相对交付**：逐日与 Raw 当日实有代码对照，查缺码及多码。 | 不能仅凭 Silver 通过推断 DG 登记的指数全覆盖；还要验对应 Raw。 | [依据](../../orchestrator/src/orchestrator/defs/checks/index_daily_checks.py#L849) |
| `gold_index_mins_120m` | **相对交付**：从来源实有指数代码展开 Gold 的规范分钟时点，核对目标缺键、多键与合法性。 | 来源没有的整个指数不会进入预期范围；不证明来源覆盖所有指数。 | [依据](../../orchestrator/src/orchestrator/defs/checks/cn_a_gold_minute_checks.py#L39) |
| `gold_index_mins_15m` | **相对交付**：从来源实有指数代码展开 Gold 的规范分钟时点，核对目标缺键、多键与合法性。 | 来源没有的整个指数不会进入预期范围；不证明来源覆盖所有指数。 | [依据](../../orchestrator/src/orchestrator/defs/checks/cn_a_gold_minute_checks.py#L39) |
| `gold_index_mins_1m` | **相对交付**：从来源实有指数代码展开 Gold 的规范分钟时点，核对目标缺键、多键与合法性。 | 来源没有的整个指数不会进入预期范围；不证明来源覆盖所有指数。 | [依据](../../orchestrator/src/orchestrator/defs/checks/cn_a_gold_minute_checks.py#L39) |
| `gold_index_mins_30m` | **相对交付**：从来源实有指数代码展开 Gold 的规范分钟时点，核对目标缺键、多键与合法性。 | 来源没有的整个指数不会进入预期范围；不证明来源覆盖所有指数。 | [依据](../../orchestrator/src/orchestrator/defs/checks/cn_a_gold_minute_checks.py#L39) |
| `gold_index_mins_5m` | **相对交付**：从来源实有指数代码展开 Gold 的规范分钟时点，核对目标缺键、多键与合法性。 | 来源没有的整个指数不会进入预期范围；不证明来源覆盖所有指数。 | [依据](../../orchestrator/src/orchestrator/defs/checks/cn_a_gold_minute_checks.py#L39) |
| `gold_index_mins_60m` | **相对交付**：从来源实有指数代码展开 Gold 的规范分钟时点，核对目标缺键、多键与合法性。 | 来源没有的整个指数不会进入预期范围；不证明来源覆盖所有指数。 | [依据](../../orchestrator/src/orchestrator/defs/checks/cn_a_gold_minute_checks.py#L39) |
| `gold_index_mins_90m` | **相对交付**：从来源实有指数代码展开 Gold 的规范分钟时点，核对目标缺键、多键与合法性。 | 来源没有的整个指数不会进入预期范围；不证明来源覆盖所有指数。 | [依据](../../orchestrator/src/orchestrator/defs/checks/cn_a_gold_minute_checks.py#L39) |
| `gold_major_index_daily_nineturn` | **相对交付**：对照指定 Gold 指数行情，检查九转输出源键缺失和多出等。 | 只能继承对应频度、行情范围和版本的源覆盖。 | [依据](../../orchestrator/src/orchestrator/defs/major_index_nineturn_integrity.py#L157) |
| `gold_major_index_mins_nineturn_120m` | **相对交付**：对照指定 Gold 指数行情，检查九转输出源键缺失和多出等。 | 只能继承对应频度、行情范围和版本的源覆盖。 | [依据](../../orchestrator/src/orchestrator/defs/major_index_nineturn_integrity.py#L157) |
| `gold_major_index_mins_nineturn_15m` | **相对交付**：对照指定 Gold 指数行情，检查九转输出源键缺失和多出等。 | 只能继承对应频度、行情范围和版本的源覆盖。 | [依据](../../orchestrator/src/orchestrator/defs/major_index_nineturn_integrity.py#L157) |
| `gold_major_index_mins_nineturn_30m` | **相对交付**：对照指定 Gold 指数行情，检查九转输出源键缺失和多出等。 | 只能继承对应频度、行情范围和版本的源覆盖。 | [依据](../../orchestrator/src/orchestrator/defs/major_index_nineturn_integrity.py#L157) |
| `gold_major_index_mins_nineturn_5m` | **相对交付**：对照指定 Gold 指数行情，检查九转输出源键缺失和多出等。 | 只能继承对应频度、行情范围和版本的源覆盖。 | [依据](../../orchestrator/src/orchestrator/defs/major_index_nineturn_integrity.py#L157) |
| `gold_major_index_mins_nineturn_60m` | **相对交付**：对照指定 Gold 指数行情，检查九转输出源键缺失和多出等。 | 只能继承对应频度、行情范围和版本的源覆盖。 | [依据](../../orchestrator/src/orchestrator/defs/major_index_nineturn_integrity.py#L157) |
| `gold_major_index_mins_nineturn_90m` | **相对交付**：对照指定 Gold 指数行情，检查九转输出源键缺失和多出等。 | 只能继承对应频度、行情范围和版本的源覆盖。 | [依据](../../orchestrator/src/orchestrator/defs/major_index_nineturn_integrity.py#L157) |
| `gold_major_index_mins_technical_120m` | **相对交付**：对同频 Gold 行情按主键查缺键、多键，并检查预热、日期和唯一性。 | 不能仅凭指标通过去证明 Gold 行情覆盖或源历史时间完整。 | [依据](../../orchestrator/src/orchestrator/defs/io/major_index_mins_technical_writer.py#L903) |
| `gold_major_index_mins_technical_15m` | **相对交付**：对同频 Gold 行情按主键查缺键、多键，并检查预热、日期和唯一性。 | 不能仅凭指标通过去证明 Gold 行情覆盖或源历史时间完整。 | [依据](../../orchestrator/src/orchestrator/defs/io/major_index_mins_technical_writer.py#L903) |
| `gold_major_index_mins_technical_1m` | **相对交付**：对同频 Gold 行情按主键查缺键、多键，并检查预热、日期和唯一性。 | 不能仅凭指标通过去证明 Gold 行情覆盖或源历史时间完整。 | [依据](../../orchestrator/src/orchestrator/defs/io/major_index_mins_technical_writer.py#L903) |
| `gold_major_index_mins_technical_30m` | **相对交付**：对同频 Gold 行情按主键查缺键、多键，并检查预热、日期和唯一性。 | 不能仅凭指标通过去证明 Gold 行情覆盖或源历史时间完整。 | [依据](../../orchestrator/src/orchestrator/defs/io/major_index_mins_technical_writer.py#L903) |
| `gold_major_index_mins_technical_5m` | **相对交付**：对同频 Gold 行情按主键查缺键、多键，并检查预热、日期和唯一性。 | 不能仅凭指标通过去证明 Gold 行情覆盖或源历史时间完整。 | [依据](../../orchestrator/src/orchestrator/defs/io/major_index_mins_technical_writer.py#L903) |
| `gold_major_index_mins_technical_60m` | **相对交付**：对同频 Gold 行情按主键查缺键、多键，并检查预热、日期和唯一性。 | 不能仅凭指标通过去证明 Gold 行情覆盖或源历史时间完整。 | [依据](../../orchestrator/src/orchestrator/defs/io/major_index_mins_technical_writer.py#L903) |
| `gold_major_index_mins_technical_90m` | **相对交付**：对同频 Gold 行情按主键查缺键、多键，并检查预热、日期和唯一性。 | 不能仅凭指标通过去证明 Gold 行情覆盖或源历史时间完整。 | [依据](../../orchestrator/src/orchestrator/defs/io/major_index_mins_technical_writer.py#L903) |
| `gold_market_breadth_daily` | **相对交付**：该日一行，并用同日 Silver 股票日线按规则重算汇总做对账。 | 如果 Silver 少股票，汇总一致不能发现源遗漏。 | [依据](../../orchestrator/src/orchestrator/defs/checks/market_breadth_checks.py#L477) |
| `silver_moneyflow` | **相对交付**：以当日 Raw 为输入按业务键和全部投影字段双向对账。 | 只能证明标准化没有丢失 Raw 的内容；要另有 Raw 同版覆盖证据。 | [依据](../../orchestrator/src/orchestrator/defs/checks/moneyflow_daily.py#L80) |
| `silver_moneyflow_cnt_ths` | **相对交付**：以当日 Raw 为输入按业务键和全部投影字段双向对账。 | 只能证明标准化没有丢失 Raw 的内容；要另有 Raw 同版覆盖证据。 | [依据](../../orchestrator/src/orchestrator/defs/checks/moneyflow_daily.py#L80) |
| `silver_moneyflow_dc` | **相对交付**：以当日 Raw 为输入按业务键和全部投影字段双向对账。 | 只能证明标准化没有丢失 Raw 的内容；要另有 Raw 同版覆盖证据。 | [依据](../../orchestrator/src/orchestrator/defs/checks/moneyflow_daily.py#L80) |
| `silver_moneyflow_ind_dc` | **相对交付**：以当日 Raw 为输入按业务键和全部投影字段双向对账。 | 只能证明标准化没有丢失 Raw 的内容；要另有 Raw 同版覆盖证据。 | [依据](../../orchestrator/src/orchestrator/defs/checks/moneyflow_daily.py#L80) |
| `silver_moneyflow_ind_ths` | **相对交付**：以当日 Raw 为输入按业务键和全部投影字段双向对账。 | 只能证明标准化没有丢失 Raw 的内容；要另有 Raw 同版覆盖证据。 | [依据](../../orchestrator/src/orchestrator/defs/checks/moneyflow_daily.py#L80) |
| `silver_moneyflow_mkt_dc` | **相对交付**：以当日 Raw 为输入按业务键和全部投影字段双向对账。 | 只能证明标准化没有丢失 Raw 的内容；要另有 Raw 同版覆盖证据。 | [依据](../../orchestrator/src/orchestrator/defs/checks/moneyflow_daily.py#L80) |
| `silver_moneyflow_ths` | **相对交付**：以当日 Raw 为输入按业务键和全部投影字段双向对账。 | 只能证明标准化没有丢失 Raw 的内容；要另有 Raw 同版覆盖证据。 | [依据](../../orchestrator/src/orchestrator/defs/checks/moneyflow_daily.py#L80) |
| `raw_tushare_stk_factor_pro` | **相对交付**：内嵌发布检查绑定已通过文件审计的产物和指纹；日更生产过程中另有独立覆盖门禁及交付记录。 | 原生 check 通过不能脱离对应发布方式和覆盖记录独立宣称全量；历史与日更口径需分开。 | [依据](../../orchestrator/src/orchestrator/defs/assets/stk_factor_pro.py#L715) |
| `gold_stk_mins_qfq_120m` | **相对交付**：源覆盖检查对照 Silver 分钟／派生来源、复权因子与目标键。 | 证明相对当前输入的前复权交付，不独立证明 Silver 分钟没有漏股票或漏分钟。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py#L576) |
| `gold_stk_mins_qfq_15m` | **相对交付**：源覆盖检查对照 Silver 分钟／派生来源、复权因子与目标键。 | 证明相对当前输入的前复权交付，不独立证明 Silver 分钟没有漏股票或漏分钟。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py#L576) |
| `gold_stk_mins_qfq_1m` | **相对交付**：源覆盖检查对照 Silver 分钟／派生来源、复权因子与目标键。 | 证明相对当前输入的前复权交付，不独立证明 Silver 分钟没有漏股票或漏分钟。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py#L576) |
| `gold_stk_mins_qfq_30m` | **相对交付**：源覆盖检查对照 Silver 分钟／派生来源、复权因子与目标键。 | 证明相对当前输入的前复权交付，不独立证明 Silver 分钟没有漏股票或漏分钟。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py#L576) |
| `gold_stk_mins_qfq_5m` | **相对交付**：源覆盖检查对照 Silver 分钟／派生来源、复权因子与目标键。 | 证明相对当前输入的前复权交付，不独立证明 Silver 分钟没有漏股票或漏分钟。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py#L576) |
| `gold_stk_mins_qfq_60m` | **相对交付**：源覆盖检查对照 Silver 分钟／派生来源、复权因子与目标键。 | 证明相对当前输入的前复权交付，不独立证明 Silver 分钟没有漏股票或漏分钟。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py#L576) |
| `gold_stk_mins_qfq_90m` | **相对交付**：源覆盖检查对照 Silver 分钟／派生来源、复权因子与目标键。 | 证明相对当前输入的前复权交付，不独立证明 Silver 分钟没有漏股票或漏分钟。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py#L576) |
| `gold_stk_mins_qfq_nineturn_120m` | **相对交付**：九转输出相对前复权源行情的缺、多键及基本结果语义。 | 只能复用被核对的原生频度和对应源行情版本。 | [依据](../../orchestrator/src/orchestrator/defs/checks/qfq_nineturn_checks.py#L30) |
| `gold_stk_mins_qfq_nineturn_30m` | **相对交付**：九转输出相对前复权源行情的缺、多键及基本结果语义。 | 只能复用被核对的原生频度和对应源行情版本。 | [依据](../../orchestrator/src/orchestrator/defs/checks/qfq_nineturn_checks.py#L30) |
| `gold_stk_mins_qfq_nineturn_60m` | **相对交付**：九转输出相对前复权源行情的缺、多键及基本结果语义。 | 只能复用被核对的原生频度和对应源行情版本。 | [依据](../../orchestrator/src/orchestrator/defs/checks/qfq_nineturn_checks.py#L30) |
| `gold_stk_mins_qfq_nineturn_90m` | **相对交付**：九转输出相对前复权源行情的缺、多键及基本结果语义。 | 只能复用被核对的原生频度和对应源行情版本。 | [依据](../../orchestrator/src/orchestrator/defs/checks/qfq_nineturn_checks.py#L30) |
| `raw_tushare_stk_period_bar_adj_month` | **相对交付**：文件、周期、键和发布记录绑定，按实有范围验证本次交付。 | 不能只靠交付／指纹检查推断本来应有的所有股票都收到；生产者的源覆盖是另项证据。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stock_weekly_checks.py#L22) |
| `raw_tushare_stk_period_bar_adj_week` | **相对交付**：文件、周期、键和发布记录绑定，按实有范围验证本次交付。 | 不能只靠交付／指纹检查推断本来应有的所有股票都收到；生产者的源覆盖是另项证据。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stock_weekly_checks.py#L22) |
| `gold_stock_daily_qfq_nineturn` | **相对交付**：九转输出相对前复权源行情的缺、多键及基本结果语义。 | 只能复用被核对的原生频度和对应源行情版本。 | [依据](../../orchestrator/src/orchestrator/defs/checks/qfq_nineturn_checks.py#L30) |
| `gold_stock_daily_trend_channel` | **相对交付**：结果与当日股票日线前复权对账；输入覆盖检查还联合状态、生命周期和上一适用日。 | 依赖前复权行情对应版本，不替代上游全股票覆盖。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stock_daily_trend_channel_checks.py#L118) |
| `silver_stock_factor_pro` | **相对交付**：内嵌发布检查绑定已通过文件审计的 Silver 版本，并记录 Raw 来源身份。 | 要证明全部应有股票均覆盖，须连对应源批次与覆盖依据一起使用。 | [依据](../../orchestrator/src/orchestrator/defs/asset_guards/stk_factor_pro_readiness.py#L1951) |
| `silver_stock_monthly` | **相对交付**：按当期实际截止日，对对应 Raw 和生命周期／身份参考重建输出投影并核验。 | 限当期和该截止日；需有独立 Raw 源范围才谈市场级齐备。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stock_period_silver_checks.py#L21) |
| `silver_stock_nineturn_daily` | **相对交付**：标准层与 Raw 和身份映射按应有标准化结果对账。 | 不能反推 Raw 自身覆盖。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stk_nineturn_checks.py#L396) |
| `gold_stock_return_distribution` | **相对交付**：该日一行，并用同日 Silver 股票日线按规则重算汇总做对账。 | 如果 Silver 少股票，汇总一致不能发现源遗漏。 | [依据](../../orchestrator/src/orchestrator/defs/checks/market_breadth_checks.py#L477) |
| `silver_stock_weekly` | **相对交付**：按当期实际截止日，对对应 Raw 和生命周期／身份参考重建输出投影并核验。 | 限当期和该截止日；需有独立 Raw 源范围才谈市场级齐备。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stock_period_silver_checks.py#L21) |
| `gold_wealth_market_turnover` | **相对交付**：检查汇总输出合同，并由同日股票日线及股票分钟输入重算对账。 | 不能替代分钟线／日线自身的源覆盖证明。 | [依据](../../orchestrator/src/orchestrator/defs/checks/wealth_market_turnover_checks.py#L16) |
| `raw_tushare_dc_daily` | **相对分类**：按同日 Raw 分类比行情键，复用已区分首次无报价、历史不可核实和过去有报价后缺失的证据。 | 只证明相对已绑定分类的范围，不能外推所有板块。 | [依据](../../orchestrator/src/orchestrator/defs/asset_guards/dc_board_relations.py#L64) |
| `silver_dc_daily` | **相对分类**：按同日 Silver 分类比行情键，复用同版所记录的合法未报价和无法核实原因。 | 不能证明分类、源行情或板块成分全集。 | [依据](../../orchestrator/src/orchestrator/defs/asset_guards/dc_board_relations.py#L64) |
| `raw_tushare_moneyflow_mkt_dc` | **合同范围**：当日大盘资金流向合同要求唯一一行；校验日期、键及数值后可判该汇总行齐备。 | 不证明个股资金流覆盖。 | [依据](../../orchestrator/src/orchestrator/defs/checks/moneyflow.py#L16) |
| `raw_tushare_moneyflow_ths` | **本次冻结范围**：复用发布时按冻结名单已生成的缺失代码；合法允许少量缺项的门禁通过不是齐备。 | 使用当次名单及最终文件版本；历史未绑定时不复用。 | [依据](../../orchestrator/src/orchestrator/defs/io/moneyflow_ths_raw_merge.py#L96) |
| `gold_stock_daily_trend_channel_state` | **相对输入**：复用同链结果资产的输入覆盖检查验证该版状态，绑定前序状态、生命周期和当天输入。 | 仅状态合同绿灯不够；跨资产版本对不上不复用。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stock_daily_trend_channel_checks.py#L118) |

### 5.2 两个日更轻量候选

| 资产键 | 拟新增的齐备性判定 | 代码 |
|---|---|---|
| `gold_stock_daily_qfq` | 同日目标 Gold 和同日 Silver 股票日线逐 `ts_code` 对账；复用正式生产已有复权因子门禁，不读前序日线。 只证明当天目标相对同版上游，源不齐不继承。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stock_daily_qfq_checks.py#L59) |
| `ch_dc_daily_technical` | 在既有同日 Gold 与本机 ClickHouse 返回数据上比较 `(ts_code, trade_date, category)`；不增加数据库查询。 只证明当天目标相对同版上游，源不齐不继承。 | [依据](../../orchestrator/src/orchestrator/defs/checks/dc_daily_technical_serving_checks.py#L141) |

### 5.3 七个不计入本地业务齐备

| 资产键 | 说明 |
|---|---|
| `prod_core_index_daily_nineturn` | Prod 发布目标，不连接远端做本地审计。 |
| `prod_ch_dc_daily_technical` | Prod 发布目标，不连接远端做本地审计。 |
| `prod_ch_share_fact_market_breadth_daily` | Prod 发布目标，不连接远端做本地审计。 |
| `prod_core_stock_daily_qfq_nineturn` | Prod 发布目标，不连接远端做本地审计。 |
| `prod_core_wealth_sector_hierarchy` | Prod 发布目标，不连接远端做本地审计。 |
| `prod_core_wealth_market_turnover` | Prod 发布目标，不连接远端做本地审计。 |
| `lake_root_health` | 环境健康，不判断业务记录齐备。 |
