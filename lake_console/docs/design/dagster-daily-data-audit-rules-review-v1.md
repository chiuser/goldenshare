# 本地 DG 数据审计：逐资产规则与触发评审 v1

状态：一期审计口径已确认。按 187 个资产盘点记录处理方式，同时保留原先分到独立审计或待定的 73 项逐条规则。初版优先跑通正常日更后复用 Check、生成每日汇总和展示明细的流程。版本绑定、独立审计调度和性能在详细设计中确认和验收。 [每日数据审计方案](dagster-daily-data-audit-wealth-data-center-plan-v1.md)

## 1. 谁触发，谁执行，什么时候算完成

**通用指数分钟线由本机 DG 在独立进程中核验，财势乾坤展示汇总结果。** 先在 DG 验证单日代表资产。自动提交仍待评审，以下是通过评审后由现有 Dagster daemon 周期性评估审计传感器的方式。传感器读取已有记录，独立任务读取文件并核对数据，每日总结汇总结果。[Dagster 传感器官方说明](https://dagster.io/docs/guides/automate/sensors)

| 步骤 | 负责人和实际动作 | 页面状态 |
|---|---|---|
| ① 发现当天需要审计的产出 | **本机 Dagster daemon** 每轮评估审计传感器。传感器先看允许运行的时间窗口，再限量批读已批准自动审计的资产和业务日的产出、上游完成及审计记录。每轮复查仍未提交的候选，不依赖某一个新事件再次出现；没有日更要求或已有同版有效结论则不提交。 | 已更新/超期等仍独立显示；齐备未核验的可显示「等上游」「等待审计窗口」或「规则未确认」。未提交不是已排队。 |
| ② 提交独立任务 | **审计传感器**在目标产出、必需上游和规则版本可绑定，且读取预算允许时，提交对应资产、分区/截至日和频度的独立审计 job。 | 页面继续显示「待确认」，直到取得有效齐备结论。 |
| ③ 正式开跑 | **DG 的独立审计 job**走本机队列，按同日同版核定文件范围，在这一步才读取业务文件。 | 待确认原因随已有证据展示。运行进度查 DG。 |
| ④ 发布和吸收结果 | **独立审计 job**完成唯一键、差集或已批准的其他核验后留下同版结论。**每日总结**按上海时间独立生成，完成后的结果补入同一业务日的最新总结，并保留核验时间。 | 齐备栏按四项汇总，原因与依据在明细和详情中展示。 |

- 自动提交的同一审计身份是资产、业务日/分区/实际截至日、频度、目标及所需上游的稳定发布版本、规则版本。复用同身份有效结果。`run_key` 用于同一传感器去重，执行参数由已确认范围显式传入。参考[运行去重和身份约束](dagster-run-key-governance-low-level-design.md)。
- 每项通过业务规则、版本证据和读取预算评审后才可加入自动清单。无法重建过去某日的旧版本，就不以今天新版本替代。传感器默认不回扫历史；停机或错过窗口，保留未核验。失败不自动另开一个同身份任务；需要重试时在原范围上重新核对版本，次数与允许条件由 LLD 审批。诊断进度只保留小型游标，不把明细装进游标或反复搜历史事件。
- 轮询间隔、单轮最多发起多少任务、独立任务允许窗口和余量不能凭想象给定；以实际记录批量读取成本、已知日更结束时间和审计文件规模定。窗口到期仍未完成就如实显示，**不承诺都在当晚完成**。验收要覆盖「没有新事件但窗口打开」「同一版没有重复任务」「排队后换版」「启动前日更又占用资源」「网页关闭仍能触发」。

### 1.1 上游先审，下游复用结果

依赖上游齐备结论的独立审计按实际输入顺序进行。按业务日、频度及发布版本检查必需的上游证据。已有合格结果时直接复用。上游还没审完或版本对不上时，下游显示「等待上游核验」；上游已经确认缺口时，下游显示「上游有缺口」及受影响的依赖。两种情况都不提交下游审计，也不读取下游文件。下游的更新状态仍按本身的发布记录展示。只有上游补齐并通过核验，且新的证据与下游实际输入版本相符，才继续核验受影响的下游。

股票分钟线按这条顺序执行。**本地 Raw 五频在生产 Check 核当天应有交易股票的代码覆盖和常规时段总根数，停牌记录和盘后记录的交付另按第 3.1 节处理。** Silver、股票分钟线前复权 Gold、MACD/KDJ 指标和递推状态、股票分钟线前复权九转等下游按实际输入复用同版齐备结果，再按本层转换规则核股票覆盖、总行数及原有生产检查。优先复用已生成的同版统计，缺项在现有生产 Check 的读取中补齐。上游齐备证据未到时先等待，所需数据和证据就绪后由生产调度执行当天的覆盖 Check。页面读当次结果，更新状态照常按发布记录展示。

按本层实际输入判断影响。股票 5 分钟 Silver 同时依赖 5 分钟和 1 分钟 Raw。股票 15 分钟前复权 Gold 读取 5 分钟 Silver，120 分钟前复权 Gold 读取 60 分钟 Silver。停牌、身份映射、复权因子及前序状态等必要输入也按各资产实际版本确认。已明确获准的历史替代使用该次实际输入和范围。验收应覆盖上游未核验或有缺口时零下游文件读取、上游换版后下游证据尚未更新，以及其他输入已齐备的频度可继续。 [Silver 输入](../../orchestrator/src/orchestrator/defs/assets/stk_mins.py#L3191) · [前复权 Gold 输入频度](../../orchestrator/src/orchestrator/defs/run_contracts/cn_a_derived_minute_bars.py#L11)

## 2. 怎么评审每条规则

页面统一显示「已确认齐备」「已确认缺口」「待确认」「不适用」。下文的「仅与上游一致」「未核验」描述已具备的证据或当前核验进度，在页面同归「待确认」。明细和详情保留各自原因，依赖上游齐备的执行条件继续按第 1.1 节判断。[四项状态与筛选](dagster-daily-data-audit-wealth-data-center-plan-v1.md#32-齐备有多少是该有的哪些确实经过验收)

- **合同范围可评审**：能从现有合同构造应有集合；还须核实产出版本和实际读量。**相对规则可评审**：能独立于待验产物，从同版输入和转换合同构造输出；单独只得「仅与上游一致」。**只明确部分**：已有日期、请求或发布证据，但更广的应有对象/时点没有依据。**待应有依据**：没找到可独立判整套覆盖的合同依据，不执行凑数式审计。
- `D` 为所选资产口径的业务日，`F` 为该资产频度。需要检查分钟键的资产按业务键报缺键、多键和重复。股票分钟线下游采用第 1.1 节的上游齐备、原有检查、股票覆盖及总行数组合口径。来源允许的例外须有依据。资源不可读、版本无法关联或缺少判定证据时，相关范围标为未核验。上线时按适用规则验收正反例。

## 3. 原方案 73 项：逐资产待评审规则

原 73 项中，股票分钟 Raw 与 Silver 共 10 项、通用指数分钟 Raw 与 Silver 共 12 项、股票前复权分钟 MACD/KDJ 与递推状态共 14 项、主要指数周线与月线 Raw 与 Silver 共 4 项已确认审计口径。东方财富板块分类 Raw、Silver 共 2 项在生产 Check 核覆盖，东方财富板块成分 Raw、Silver 共 2 项直接复用现有 Check。ETF 分钟 Raw 5 项、股票复权因子 Raw、ETF 日线行情 Raw 和基金复权因子 Raw 各 1 项优先复用已有检查。国际指数日线 Raw 和 Silver 共 2 项纳入二期，一期显示「不适用」。第 3.5–3.7 节这批 19 项中，11 项确定在生产时补 Check，5 项复用现有检查或发布证据，3 项只查更新。第 5.2 节另有 2 项在现有生产 Check 补同日对账，确认有键差异时沿用阻断行为。

| 章节 | 已确定在生产时补 Check | 复用现有检查或发布证据 | 只查更新 |
|---|---:|---:|---:|
| 3.5 资金流向 | 5 | 0 | 0 |
| 3.6 交易日历、基础信息、曾用名、身份和生命周期 | 5 | 4 | 1 |
| 3.7 停复牌及事件型资产 | 1 | 1 | 2 |

### 3.1 股票原始分钟线与 Silver（10 项）

**Raw 和 Silver 均在生产 Check 核当天股票代码覆盖和总根数。**

- **Raw 常规时段齐备。** 按本次同步采用的上市股票名单及当天最终停牌事实，确定应有交易股票。从应有名单和实际统计中同时排除已确认全天停牌的股票，实有根数统计至 15:00。盘中临时停牌按完整应有根数计，实有零成交分钟记录也计入。正常交易日五个频度的应有总根数，分别为应有股票数量乘以各自常规根数（1、5、15、30、60 分钟分别为 241、49、17、9、5 根）。股票代码集合相同且总根数相符即通过本项。历史补录用该次批准的范围和源规则。取不到同日适用的名单、最终停牌事实或产出版本时显示「待确认」。 [日更采用的股票名单](../../orchestrator/src/orchestrator/defs/asset_guards/stk_mins_stock_universe.py#L18) · [已核对的五频应有根数](dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#recovery-20261102-lld)
- **Raw 中的全天停牌记录。** Raw 保留 Prod 实际交付的全天停牌记录。常规交易齐备的应有根数和实有根数均不计这些记录，避免零成交占位补足其他股票短缺的根数。Raw 原有的写前代码覆盖仍按本次请求的上市名单执行，名单中包含全天停牌股票。交付采用同次来源和本地产出的记录，常规齐备结论适用于应有交易股票范围。 [Raw 写前代码覆盖](../../orchestrator/src/orchestrator/defs/assets/stk_mins.py#L1006)
- **Silver 常规时段齐备。** 等必需输入齐备后，用已核验的当天股票日线、生命周期和最终停牌事实确定应有股票，全天停牌必须为零根。按同版 Raw 和正式转换规则核应有股票覆盖与总行数。现有 Silver 对日线的引用检查只验证已见代码，应补整股覆盖统计。 [Silver 日线引用检查](../../orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py#L2429)

2026-10-23 至 2026-11-19 共 20 个交易日，按最终停牌 Silver 的停牌类型 `S` 和空停牌时段识别出 133 个沪深股票与全天停牌日期的组合。每个组合在本地分钟线 Raw 中的 1、5、15、30、60 分钟分别有 241、49、17、9、5 根，成交量和成交额均为零，盘后均无记录。Silver 五个频度全部为零根，与现行全天停牌过滤一致。可复查 11 月 19 日的 `002717.SZ` 或 `688496.SH`。样本期没有北交所全天停牌组合。 [停牌范围依据](../../orchestrator/src/orchestrator/defs/stock_trading_universe.py#L13) · [Silver 全天停牌过滤](../../orchestrator/src/orchestrator/defs/assets/stk_mins.py#L1614)

复核 2026-10-23 至 2026-11-19 的 20 个交易日，以本地最终停牌 Silver 中注明盘中停牌时段的记录为范围。`301718.SZ`（10 月 23 日 11:01–11:11）、`920285.BJ`（10 月 23 日 11:03–11:13）、`001381.SZ`（11 月 3 日 10:33–10:43、10:45–10:55）、`920309.BJ`（11 月 17 日 13:16–13:26）共 4 个股票与交易日组合。它们的 Raw 在截至 15:00 的常规时段，1、5、15、30、60 分钟分别有 241、49、17、9、5 根。

**常规时段决定列表的齐备状态，盘后交付看详情。** 股票分钟线 Raw 的应交易股票代码和截至 15:00 的总根数一致，列表显示「已确认齐备（常规时段）」，归入「已确认齐备」的汇总和筛选。Raw 保留 Prod 同次实际交付的盘后记录，详情按同日、同频、同批证据单独显示盘后交付结果，证据缺失时显示「待确认」。例如 `920000.BJ` 在 2026-11-19 的 1 分钟 Raw 为常规 241 根、盘后 30 根。若常规时段实际少一根，即使盘后 30 根都在，常规齐备也判缺口。Silver 在共同输入入口滤除 15:00 之后的记录，按同版常规时段结论判断上游齐备。 [盘后数据合同](stk-mins-bse-post-close-raw-retention-plan.md#42-dg-raw-合同)

Silver 应有行数按正式转换规则确定，包含按有效期映射代码、全天停牌和 `15:00` 之后的行的剔除、去重、获准冻结历史及粗频合成。日常 5/15/30/60 分钟只在某股当天同频 Raw 经基础过滤后全无记录且有合格的 1 分钟整日输入时整日合成。原生粗频坏价重算保留原时间键。复用日更已算的同版统计。缺少有效应有根数或版本证据的范围标为「待确认」，历史补录按当次获准范围核。 [Silver 基础过滤](../../orchestrator/src/orchestrator/defs/assets/stk_mins.py#L1518) · [粗频合成及重算](../../orchestrator/src/orchestrator/defs/assets/stk_mins.py#L1684) · [冻结保留](../../orchestrator/src/orchestrator/defs/assets/stk_mins.py#L1997)

用 2026-11-19 的 1 分钟 Raw 举例，文件实存 5,580 只股票、1,355,460 根。统计常规齐备时，扣掉 7 只全天停牌股票的 1,687 根和盘后 10,680 根，得到 5,573 只股票、1,343,093 根。当天 Silver 读回也是 5,573 只股票、1,343,093 根。此前对当天 Raw 文件只读 `ts_code` 的分组计数约 9 毫秒，完整 Check 的时段过滤、应有根数计算及版本关联仍须验收。

生产 Check 优先复用同日同频的写前名单、停牌事实及本次生产已算的计数。统计不足时在现有读取中按代码和 `trade_time` 聚合，仅读当天该频度的目标和必要参照。验收时用全天停牌 Raw 有占位、盘中临时停牌保留完整根数、交易股票少根但有停牌占位、实有盘后记录及停牌依据缺失的情形核对结果。

| 资产键 | 本项应有范围与检查 | 仍要定的事 |
|---|---|---|
| `raw_stk_mins_1m` | 核 `D` 的 1 分钟常规应有代码和总根数。全天停牌从应有和实有统计一并排除，盘中临时停牌按完整根数计。 | 待开发并验收同版统计、盘后交付证据、耗时和内存。 |
| `raw_stk_mins_5m` | 按 `D` 的 5 分钟应有代码和总根数执行同样规则。 | 同上。 |
| `raw_stk_mins_15m` | 按 `D` 的 15 分钟应有代码和总根数执行同样规则。 | 同上。 |
| `raw_stk_mins_30m` | 按 `D` 的 30 分钟应有代码和总根数执行同样规则。 | 同上。 |
| `raw_stk_mins_60m` | 按 `D` 的 60 分钟应有代码和总根数执行同样规则。 | 同上。 |
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

**指标七项。** 先确认同日、同频、同版股票前复权分钟线 Gold 的齐备 Check 通过，再核 MACD/KDJ 与该次输入的股票代码一致、总行数相同。每根前复权 K 线应产出一行指标。复用已有的产物合同检查和来源行数、指标行数对账。代码证据不足时合并到现有 Check 的读取中，优先使用生产已读的数据和统计，避免再打开一遍股票年度文件。 [指标覆盖检查](../../orchestrator/src/orchestrator/defs/checks/stk_mins_qfq_macd_kdj_checks.py#L227) · [指标按股票、年份存储](../../orchestrator/src/orchestrator/defs/paths.py#L576)

**状态七项。** 同版上游齐备后，在生产 Check 核递推状态的股票代码及总行数。应有代码是前一交易日应承接状态的股票加上当天有指标的股票，去重后每只一行。已有状态的股票全天停牌时沿用上一交易日状态。比如上一交易日 10 只股票都有状态，今天 1 只全天停牌，其余 9 只各有 5 根分钟线，则指标应有 45 行，递推状态应有 10 行。首次初始化按当次规则确定前序范围，历史修复按获准范围核对。现有检查只要求状态行数至少达到当天有指标的股票数，须补完整的应有代码和精确总行数。复用当日生产已读入的前序状态和当日输入统计。缺少能绑定到该版的证据时显示「待确认」。 [状态生成规则](../../orchestrator/src/orchestrator/defs/stk_mins_qfq_macd_kdj.py#L676) · [前序交易日规则](../../orchestrator/src/orchestrator/defs/assets/stk_mins_qfq_macd_kdj.py#L289) · [现有状态检查](../../orchestrator/src/orchestrator/defs/checks/stk_mins_qfq_macd_kdj_checks.py#L417)

| 资产键 | 应有总行数 | 状态 |
|---|---|---|
| `gold_stk_mins_qfq_macd_kdj_1m` | 同版前复权 Gold 1 分钟当日 K 线总数。 | 口径已确认，优先复用已有检查记录。 |
| `gold_stk_mins_qfq_macd_kdj_5m` | 同版前复权 Gold 5 分钟当日 K 线总数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_15m` | 同版前复权 Gold 15 分钟当日 K 线总数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_30m` | 同版前复权 Gold 30 分钟当日 K 线总数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_60m` | 同版前复权 Gold 60 分钟当日 K 线总数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_90m` | 同版前复权 Gold 90 分钟当日 K 线总数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_120m` | 同版前复权 Gold 120 分钟当日 K 线总数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_state_1m` | 1 分钟当日有指标及前序应承接状态的合并去重股票数。 | 口径已确认，生产 Check 补核应有代码和总行数。 |
| `gold_stk_mins_qfq_macd_kdj_state_5m` | 5 分钟当日有指标及前序应承接状态的合并去重股票数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_state_15m` | 15 分钟当日有指标及前序应承接状态的合并去重股票数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_state_30m` | 30 分钟当日有指标及前序应承接状态的合并去重股票数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_state_60m` | 60 分钟当日有指标及前序应承接状态的合并去重股票数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_state_90m` | 90 分钟当日有指标及前序应承接状态的合并去重股票数。 | 同上。 |
| `gold_stk_mins_qfq_macd_kdj_state_120m` | 120 分钟当日有指标及前序应承接状态的合并去重股票数。 | 同上。 |

### 3.4 指数周月、板块分类/成分和国际指数日线（10 项）

**主要指数周线和月线 Silver 的更新状态按每个交易日判定。** 对所选交易日 `D`，分别确认本周周线和本月月线有实际截至日 `trade_date = D` 的成功交付。比如周三，两项都应更新到周三。月初首个交易日即使上月正式行情已补入 Silver，也要分别核对本周、本月截至当天的交付。查历史日期时使用当日交付记录。对象覆盖另行给出齐备状态。 [日更触发与完成判定](../../orchestrator/src/orchestrator/defs/sensors/index_period_update_job_sensors.py#L168) · [Silver 截至日记录](../../orchestrator/src/orchestrator/defs/assets/index_period.py#L214)

**主要指数周线和月线的取数范围。** Raw 与 Silver 共用仓库固定的 11 个主要指数代码，均无动态激活池。Raw 在各自发布日逐代码向 Tushare 请求当期最后交易日，北证 50（`899050.BJ`）也请求并允许为空，其余代码每个应有一行。Silver 用指数基础信息的上市日期筛出截至当天已上市的指数，平时以本地指数日线 Silver 合成当期行情。期末正式 Raw 到达后，按代码覆盖原周期。有正式 Raw 的用该记录，源端合法为空的代码在正式覆盖时可保留已经合成到期末的 Silver。北证 50 已上市时仍须有 Silver。 [固定名单](../../orchestrator/src/orchestrator/seeds/market/major_indices.cn_a.csv) · [Raw 请求及返回核验](../../orchestrator/src/orchestrator/defs/io/index_period_writer.py#L70) · [Silver 取数及覆盖](../../orchestrator/src/orchestrator/defs/io/index_period_writer.py#L461) · [发布日判定](../../orchestrator/src/orchestrator/defs/sensors/index_period_update_job_sensors.py#L79)

| 资产键 | 本项规则 / 检查方法 | 足以判定什么、仍缺什么 |
|---|---|---|
| `raw_index_weekly` | 本周最后交易日，按固定名单核 `(ts_code, 期末日)`。北证 50 可空，其余必有且唯一。 | 正常交付复用生产者逐代码核验及同版 Check。 |
| `silver_index_weekly` | 每个交易日在现有 Check 核本次生成的本周数据。当天已上市的主要指数各一行，每行实际截至日等于当天。 | 方案已确认，待实现。每日审计复用与当次产出关联的 Check。 |
| `raw_index_monthly` | 下月首个交易日考核交付。按固定名单核 `(ts_code, 上月最后交易日)`。北证 50 可空，其余必有且唯一。 | 正常交付复用生产者逐代码核验及同版 Check。 |
| `silver_index_monthly` | 每个交易日在现有 Check 核本次生成的本月数据。当天已上市的主要指数各一行，每行实际截至日等于当天。 | 方案已确认，待实现。每日审计复用与当次产出关联的 Check。 |
| `raw_tushare_dc_index` | 按行业、地域、概念分别核对当天的板块代码，采用下文的本地标准集。 | 首份板块名单以 2026-11-19 为准，供后续交易日比较。采集时的 Prod 对账可解释差异。 |
| `silver_dc_index` | 以同版 Raw 按[标准化和拒绝规则](../../orchestrator/src/orchestrator/defs/assets/dc_board_silver.py#L143)产生预期分类键，与 Silver 对照；只排除明确允许的拒绝项。 | 相对规则可评审；上游没有的板块不能靠 Silver 推断。 |
| `raw_tushare_dc_member` | 复用所选业务日、当前 Raw 产出对应的 `raw_tushare_dc_member_core_check`。 | Check 通过即按一期口径判通过。 |
| `silver_dc_member` | 复用所选业务日、当前 Silver 产出对应的 `silver_dc_member_core_check`。 | Check 通过即按一期口径判通过。 |
| `raw_index_global` | 一期不适用。二期按该指数适用的市场日历、覆盖范围和到期时间核 `(ts_code, trade_date)`。 | [本机按阶段发起任务](../../orchestrator/src/orchestrator/defs/run_contracts/index_global.py#L139)，二期待确认各市场休市及迟报依据。 |
| `silver_index_global` | 一期不适用。二期按实际使用的同版 Raw 和正式转换规则核对业务键。 | 二期待确认如何证明同版 Raw 的齐备范围和 Silver 的交付。 |

#### 主要指数周线和月线的检查结果复用

- **Raw 正常交付。** 生产者已逐一检查全部 11 个请求是否完整返回、代码和期末日是否正确、是否缺记录或重复。北证 50 是唯一允许返回零行的代码。对所选期末，复用同一次正常生产的成功产出及通过的关联 Check。匹配资产、分区、运行及 Check 指向的产出记录。 [逐代码校验](../../orchestrator/src/orchestrator/defs/io/index_period_writer.py#L70) · [关联 Check 的匹配规则](../../orchestrator/src/orchestrator/defs/sensors/index_period_daily_readiness.py#L32)
- **Silver 日更已确认在现有 Check 补核。** `D` 取本次更新配置指定的业务日期，补跑也取本次指定日期。按指数基础信息的上市日期，从固定名单取 `list_date <= D` 的应有代码。写入前检查本次生成的当期数据，实有代码应与应有代码一致，每个代码各一行，且每行 `trade_date = D`。合并到现有当期键检查，复用已算出的应有名单。应有范围每项最多 11 个，新增文件读取和源请求均为零，额外内存限当期键和有界差异。沿用原 Check 及本次产出的关联，审计页面和下游直接复用其覆盖与截至日结论。 [Silver 应有名单及截至日](../../orchestrator/src/orchestrator/defs/io/index_period_writer.py#L461) · [本次增量和写入入口](../../orchestrator/src/orchestrator/defs/io/index_period_writer.py#L554) · [现有 Check](../../orchestrator/src/orchestrator/defs/checks/index_period_checks.py#L98)
- **验收看实际键。** 正常日更、北证 50 已上市、名单中有指数尚未上市均应按 `D` 正确判定。需拦住用其他代码补齐行数、代码重复及实际截至日与 `D` 不符。补跑早于期末的日期时，若部分数据取自已到的期末 Raw，即使批次记录标为 `D`，仍要报出日期不符的代码。失败沿用现有 Check 的失败路径，在正式文件提升前拦截。
- **已有历史证据。** 原有纯日线合成或实际期末交付在能从同版产出、来源和 Check 证明规则成立时仍可复用。历史初始化只按分区登记行数和最大日期，不能单独证明逐行齐备。证据不足时优先用同版的代码和日期对账。仍需读文件时只核目标期末或目标周期的代码与实际截至日。历史 Silver 已换版且无留存证据时显示「待确认」，原因写「缺少所选日的齐备证据」。 [产出记录的模式与来源](../../orchestrator/src/orchestrator/defs/assets/index_period.py#L214) · [历史初始化分区统计](../../orchestrator/src/orchestrator/defs/bootstrap/index_period_history.py#L144)

已有正式验收样本包含周、月 Raw 各交付 10 行，北证 50 合法空，相应期末 Silver 各 11 行。2026-11-18 的周、月 Silver 纯日线合成也均通过关联检查，并读回 11 个代码均截至当天。以上是现有验收记录，新增 Silver 核验待实现和验收。 [Raw 与期末 Silver 验收](dagster-index-period-onboarding-plan-and-low-level-design-v1.md#1116-小数搬运修复及-e-人工重跑2026-11-18) · [Silver 日更验收](dagster-index-period-onboarding-plan-and-low-level-design-v1.md#1118-f-人工接续启用及独立审计结果2026-11-19-凌晨)

#### 东方财富板块分类标准集

东方财富板块分类的 Raw、Silver 在现有生产 Check 中记录审计覆盖结果，生产检查通过条件照旧。每次只核所选交易日、本次产出和适用的分类标准集。标准集以当日 Raw 产出确认。Silver 复用 Raw 确认的标准集，并核验与其实际使用的同版 Raw 的转换。更新状态按实际产出单独展示。首次分类标准集及概念板块增减由人工确认。

- **行业和地域**分别采用经人工确认的本地板块代码名单。每天同步完成后按类别对代码，显示缺少和多出的板块。确认正常调整后，发布新版本。齐备结论适用于生效的标准集范围。Raw 的源端占位记录按现行规则处理。
- **东方财富概念板块**在资产明细中单独显示一个审计项，归属「东方财富板块分类」数据集。按所选业务日可查看参照标准集、当天新增和减少的板块，以及已确认的当日标准集。更新状态仍按当天产出展示。
- 每个交易日保留一份概念板块标准集。同步完成后，用**上一交易日**的标准集比较当天有效名单。名单一致时为当天保存相同内容的副本。有新增或减少时显示「需要人工核查」。核查后确认属于正常调整时，可点击确认生成当天标准集。确认应能查回所用的当天产出及上一交易日标准集。
- 上一交易日缺少已确认的标准集时，当天审计失败并显示「参照标准集缺失」。恢复时从缺失的交易日继续，以便保留连续可追溯的日版本。
- **分类资产汇总**对行业、地域和概念分别保留明细，再给分类资产一个齐备状态。任一项有已确认缺口时汇总为「已确认缺口」。其余情况下，有待确认项则汇总为「待确认」，适用项全齐备则汇总为「已确认齐备」，所有项均不适用则汇总为「不适用」。每日总结按分类资产计一次。

首份板块分类标准集采用 2026-11-19 的 Raw 名单，从下一交易日逐日接续到启用日，并联验依赖当日标准集的东方财富板块资金流向。当天 Tushare 与本地 Raw、Silver 的分类代码一致，分别为 496 个行业、31 个地域和 554 个概念板块。当天两层的 1,081 个板块均有成分记录，抽查的机械设备、半导体、广东、浙江四个板块成分名单与源端一致。

##### 概念板块名单的 Tushare 复核

1. 运营在东方财富板块分类 Raw 的「概念板块名单核查」弹窗点击「核查 Tushare」，按当前业务日期和当前待确认的新增、减少板块代码发起一轮只读复核。按这些代码复查当天的板块分类，并单独显示同一组板块的源端成分查询结果。板块是否在名单内以分类查询为依据。成分返回零条只说明此次成分查询结果为空。
2. 等待时显示加载圈、「正在核查 Tushare」和本次请求范围。锁定弹窗，禁用重复核查、查看参照标准集、确认、取消和关闭，屏蔽 Esc 和点击弹窗外关闭。所有请求完成、失败或达到超时后解除锁定。
3. 保留原本地差异，逐条并列显示 Tushare 当天名单、成分结果及本次核查时间。若核查确认该板块属于当天源端的有效分类名单，而本地当前产出缺少该板块，显示「源端有，本地缺少」，当天分类审计记「已确认缺口」。查询成功但此次未返回相应板块时显示「源端本次未返回」，留待人工判断。请求失败单列「核查失败」并支持只重试失败项。全部超时则保留原差异，显示原因和重试入口。
4. 当天存在已确认缺口时，禁用「确认并生成标准集」，保存入口也拒绝生成。用现有同步入口补齐该业务日后，按补齐后的产出重新核对当天名单。缺口解除后，名单一致则保存当天副本，有真实调整则按人工确认流程保存。标准集关联当天产出和上一交易日参照的版本，次日使用已确认的当天标准集。Tushare 复核本身为只读。

验收覆盖名单一致时保存当天副本、正常变更经人工确认后保存，以及源端证实本地漏采时显示缺口并禁止生成、补齐后按新产出恢复。另验只请求待确认的板块、核查时锁定弹窗、结束后恢复操作，以及有效空返回与超时分别处理。

#### 东方财富板块成分审计规则

**一期直接复用现有生产 Check。** 东方财富板块成分覆盖行业、地域和概念。Raw、Silver 分别读取所选业务日与当前正式产出对应的核心 Check，通过即按一期口径显示「已确认齐备」，详情写明「现有生产 Check 通过」。缺少同日同版结果时显示「待确认」，失败时展示 Check 的具体原因，并按已有证据判断是否存在已确认缺口。更新状态单独按当天实际产出判断。 [Raw 核心 Check](../../orchestrator/src/orchestrator/defs/checks/dc_board_checks.py#L297) · [Silver 核心 Check](../../orchestrator/src/orchestrator/defs/checks/dc_board_silver_checks.py#L286)

现有 Check 结论适用于文件、日期、业务键及成分所属板块等已验证范围。成分标准集、相邻日数量波动、额外代码对账和独立审计均在一期范围之外。下列内容保留为历史核查记录。

补齐后的 2026-11-18，昨日连板从 12 只变为 5 只，昨日触板从 46 只变为 23 只，昨日连板（含一字）从 15 只变为 6 只。两日数量都与 Tushare 一致，18 日股票代码也逐一匹配。比例只能描述成分变化，无法定位本地缺失的股票。当天广东板块的分类记录显示上涨和下跌合计 894 家，而 Tushare 成分名单为 870 只，且与本地两层按代码完全一致。同日涨跌家数如用于发现异常，须先确认覆盖范围，只作源端复核线索。

2026-10-22 至 2026-11-18 的本地数据按相邻交易日比较，只比较两天都存在的同一板块。行业、地域、概念每天观察到成分差异的板块数中位数分别为 3、0、73。概念有 108 次比较的总数相同但股票名单有差异。两层成分关系在这 20 天逐日一致。这些统计记录的是本地文件差异。

2026-11-18 的 Raw 和 Silver 同时缺少 31 个概念板块的全部成分，记为本地成分缺失。2026-11-19 对这 31 个代码逐一查询 Tushare `dc_member`，都返回了 11 月 18 日的成分，共 1,848 对关系。另抽查同日 2 个行业和 2 个地域板块，机械设备、半导体、广东板块比本地多出 1、3、2 条关系，浙江板块名单一致。首次同步时源端是否尚未齐备，需用当时的请求记录确认。

#### 国际指数日线二期

Raw 和 Silver 一期都显示「不适用」，原因是「国际指数日线审计纳入二期」。两项分别出现在明细并计入「不适用」汇总。一期跳过这两项的专门审计。

二期按市场核实交易日历、各指数的源端覆盖和数据到期时间，再核查已发现的本地缺口及 Silver 的同版 Raw 交付。`HSHKCI` 原对应的恒生香港综合指数已于 2010 年 3 月 8 日停算，Tushare 后续返回记录的实际指数身份仍待核实，二期据此确定 Silver 保留范围和每日应有名单。 [港交所停算公告](https://www.hkex.com.hk/-/media/hkex-market/services/circulars-and-notices/participant-and-members-circulars/sehk/2010/ctmo00410e)

### 3.5 股票复权因子、ETF 日线行情、基金复权因子和资金流向（8 项）

[ETF 日线行情 Raw 和基金复权因子 Raw 生产者](../../orchestrator/src/orchestrator/defs/assets/etf_daily.py#L141)记录请求、来源行数和候选文件等交付信息，可用于核对当次接口返回的记录是否完整保存。预期覆盖的代码由各资产的业务规则另定。资金流向的[业务键和请求范围](../../orchestrator/src/orchestrator/defs/run_contracts/moneyflow_daily.py#L53)按源区分。下列均按当天单分区评审。

| 资产键 | 本项规则 / 检查方法 | 仍需确认 |
|---|---|---|
| `raw_tushare_adj_factor` | 按业务日期有效的上市 A 股名单核当天因子，全天停牌股票也应有。 | 口径已确认，优先复用同版覆盖与对账证据。 |
| `raw_tushare_fund_adj` | 按本次绑定的 ETF 基础信息快照核当天沪深上市 ETF 的复权因子覆盖。 | 口径已确认，优先复用现有 Check 的应有代码数与 Raw 命中数。 |
| `raw_tushare_fund_daily` | ETF 日线行情 Raw。按本次绑定的 ETF 基础信息快照核当天沪深上市 ETF 日线覆盖。 | 口径已确认，优先复用现有 Check 的应有代码数与 Raw 命中数。 |
| `raw_tushare_moneyflow` | 已确认按所选日已上市的沪深京 A 股逐代码核对，纳入全天停牌及上市首日。最近 20 个交易日应有代码全部覆盖。 | 在现有 Check 中补单日覆盖比对并记录结果。日常审计复用该结果。 |
| `raw_tushare_moneyflow_dc` | 已确认一期按当天已上市且有成交的沪深京 A 股代码核覆盖。以已核验的当日股票日线确认应有交易代码，全天停牌及 B 股不计入应有名单。 | 在现有生产 Check 补覆盖。当日日线尚未就绪时显示「待确认」，就绪后自动执行当天 Check。2026-10-30 Raw、Silver 已补齐并验收。 |
| `raw_tushare_moneyflow_cnt_ths` | 已确认以审计样本中连续 20 天稳定出现的 386 个同花顺概念代码为基线。增减时逐代码列出，标为「待确认」，人工确认后才更新基线。 | 在现有生产 Check 补单日代码核对。目录另有 4 个概念的发布范围待核实。 |
| `raw_tushare_moneyflow_ind_ths` | 已确认按同花顺 A 股行业目录中的 90 个 `881` 代码核对，同目录增减、资金流向生效日经确认后更新名单。 | 在现有生产 Check 补当天代码比对和缺码统计，日常读取结果。 |
| `raw_tushare_moneyflow_ind_dc` | 已确认按生效的东方财富板块标准集，分行业、概念、地域核板块代码。名称变化不影响代码覆盖结论。概念等待当日标准集确认后再判。 | 在现有生产 Check 补覆盖。资金流向已产出而标准集晚到时，等标准集就绪后自动执行当天的覆盖 Check。 |

#### 股票复权因子与 ETF 日线行情已确认口径

- **股票复权因子 Raw、Silver。** 以所选交易日 `D` 的股票生命周期为依据，上市日期不晚于 `D`、退市尚未生效的 A 股都应有当天因子。全天停牌仍算应有。已退市股票的真实源记录按现有规则保留，并从退市生效当天起移出应有名单。复用 `silver_adj_factor_lifecycle_coverage_check`。现行 Check 对 2026-10-28 起的交易日同时核生命周期覆盖及与同版 Raw 的双向差异。复用时要确认名单适用，绑定交易日及当次 Raw、Silver 和股票生命周期版本。覆盖和双向对账均通过时，Raw 与 Silver 的应有股票覆盖均可判齐备。更早交易日的 Raw 或历史应有名单超出现行 Check 覆盖范围时，需有当期的单独覆盖证据。 [股票生命周期和现行筛选边界](../../orchestrator/src/orchestrator/defs/duckdb_sql.py#L344) · [覆盖与 Raw 对账](../../orchestrator/src/orchestrator/defs/stock_factor_price_checks.py#L49) · [正式 Check](../../orchestrator/src/orchestrator/defs/checks/adj_factor_checks.py#L944)
- **ETF 日线行情 Raw、Silver。** 选用当次产出绑定的 `silver_etf_basic` 快照。取交易所与代码后缀一致、状态为已上市、上市日期不晚于 `D` 的沪深 ETF，逐代码核当天日线。直接复用 `silver_etf_daily_basic_coverage_check`。应有代码数减 Raw 命中数是 Raw 在该名单下的缺码数，Silver 使用该 Check 记录的缺码和多码结果。Raw 的齐备范围为沪深上市 ETF 名单。该 Check 的覆盖差异仍为非阻断告警，更新状态单独展示。所选日的名单、Raw 或 Silver 版本无法关联时，相关覆盖状态保留为「待确认」。 [ETF 应有名单与代码对账](../../orchestrator/src/orchestrator/defs/io/etf_daily_silver_writer.py#L658) · [现有检查证据与级别](../../orchestrator/src/orchestrator/defs/checks/etf_daily_checks.py#L1083) · [非阻断规则](../../orchestrator/src/orchestrator/defs/checks/etf_daily_checks.py#L1172)

股票复权因子只读样本覆盖 2026 年 11 月 13 日及 16–19 日共 5 个交易日。其中 36 个全天停牌的股票与交易日组合在 Raw、Silver 均有复权因子。另用 Tushare 核对了 11 月 18 日的 `000635.SZ` 和 `002717.SZ`，两只当天均返回复权因子。

#### 基金复权因子 Raw 与 ETF 复权因子 Silver 已确认口径

- **应有 ETF 范围。** 对交易日 `D`，取本次产出关联的 `silver_etf_basic` 快照。应有代码是交易所与代码后缀一致、已上市且上市日期不晚于 `D` 的沪深 ETF。每个应有代码在 `D` 应有一条复权因子。当天没有日线的应有 ETF 仍需覆盖。历史已批准的例外按原指定日期、代码和依据处理。 [ETF 应有名单](../../orchestrator/src/orchestrator/defs/io/etf_daily_silver_writer.py#L658)
- **基金复权因子 Raw（`fund_adj`）。** 齐备审计只核当日沪深上市 ETF 的复权因子覆盖。复用 `silver_etf_adj_factor_basic_coverage_check` 中的 `expected_code_count` 和 `raw_matching_code_count`，两者之差是该名单下的 Raw 缺码数。 [Raw 覆盖统计](../../orchestrator/src/orchestrator/defs/checks/etf_daily_checks.py#L1083)
- **ETF 复权因子 Silver（`silver_etf_adj_factor`）。** 复用同次 `silver_etf_adj_factor_basic_coverage_check` 和同版 Raw 转换对账。逐代码核应有范围，缺码和多出代码按现行阻断检查处理，更新状态仍按实际产出独立展示。 [Silver 取数与名单版本](../../orchestrator/src/orchestrator/defs/assets/etf_daily.py#L363) · [Silver 阻断检查](../../orchestrator/src/orchestrator/defs/checks/etf_daily_checks.py#L1202)

#### 复用与单日补核

1. 日常先读现有 DG Check 和交付记录。复用 ETF 覆盖统计时，按业务日期核实覆盖检查确已执行，日期和主键检查有效，并匹配 ETF 基础信息快照及 Raw 文件版本。判断 Silver 时还要匹配本次 Silver 产出。有些历史验收或检查失败路径没有执行覆盖统计，读取到缺省计数零时，须先核实实际执行的规则。历史日期沿用该次生产或历史验收绑定的快照。 [检查的覆盖统计和名单版本](../../orchestrator/src/orchestrator/defs/checks/etf_daily_checks.py#L1083)
2. 缺少可复用的覆盖证据且需要补核时，只读所选交易日对应的名单和文件所需键。股票复权因子对当日上市股票生命周期，ETF 日线行情和 ETF 复权因子对该日适用的 ETF 名单。先核 Raw 所需的代码及交易日，再核需确认的 Silver。已核实范围内的缺码记为「已确认缺口」。找不到适用于当日的名单或文件版本时，保留「待确认」及原因。三组资产的日常汇总直接读取有效证据。
3. ETF 日线行情 Raw 和基金复权因子 Raw 的齐备详情显示「沪深上市 ETF 覆盖」，列出当日名单版本、应有数、实际命中数及缺码。审计范围限定在该名单内。 [DG ETF 名单来源](../../orchestrator/src/orchestrator/defs/catalog/lake_assets.py#L3727)

2026 年 11 月 18 日的样本验证了这两个判断。Tushare 的 ETF 日线行情和基金复权因子接口，以及 DG 对应的两份 Raw，均有场内代码 `158008.SZ` 的记录。同一基金的 `158008.OF` 也出现在 ETF 日线行情 Raw，当天 `fund_adj` 未返回 `.OF` 的复权因子。场内 ETF 覆盖按 `.SZ` 判定。同日 `530080.SH` 属于应有 ETF，Tushare 和 DG 的 `fund_adj` 各有 2,219 个代码与日期组合，双向对账一致，两边都没有该代码。该日的两个结论分别是「代码和日期交付一致」和「应有 ETF 复权因子覆盖有缺口」。 [ETF 日线源记录中的 `.OF` 行为](../../../docs/sources/tushare/ETF专题/0127_ETF日线行情.md#dg-接入-p0-实测补充2026-09-02) · [基金复权因子缺口对账](dagster-etf-daily-data-onboarding-plan-v1.md#2026年11月18日基金复权因子缺口判断更正2026-11-19只读)

#### 五类资金流向 Raw 的审计口径与实测

2026 年 10 月 23 日至 11 月 19 日共 20 个交易日的本地审计结果如下。现有 Check 和发布记录继续提供文件字段、日期、业务键、分页和交付证据。日更覆盖判断建议在现行文件查询中同时取当天代码，再和当日采用的名单比较。普通个股使用当日适用的股票生命周期名单。东方财富个股若依赖当天股票日线确定实有成交的范围，须先确认该日股票日线已核验。两项同花顺板块直接使用已确认的名单。名单或上游证据缺失时，覆盖显示「待确认」。建议将覆盖结果和更新结果分别记录。 [现有文件检查](../../orchestrator/src/orchestrator/defs/checks/moneyflow_daily.py#L38) · [现有来源及发布对账](../../orchestrator/src/orchestrator/defs/io/moneyflow_daily_update.py#L146)

- **普通个股资金流向。** 20 个交易日均覆盖当天已上市的沪深京 A 股，包括 133 个全天停牌的股票与交易日组合，以及 6 只首日上市且有成交的股票。样本没有出现全天未停牌且日线零成交的个案。已确认在现有 Check 中补当天代码覆盖，使用当日适用的股票生命周期，记录所用版本、应有数与缺码。日常复用该 Check 结果。缺少可用名单或历史证据时显示「待确认」，按需补核所选日。
- **东方财富个股资金流向。** 2026-10-30 的原版 Raw、Silver 各 5,667 个代码。2026-11-20 源端复核有 6,031 个，其中 364 个原版缺失，含 263 只当天有成交的 A 股。补齐后同日 Raw、Silver 各 6,031 个唯一代码，364 个原缺码全部补回，当天成交 A 股缺码为零。两层 Check 均通过，读回的正式文件与 Check 对应的版本一致。修复验收记录的 Raw 与源、Silver 与本次 Raw 全字段对账均无差异。此后的每日覆盖按当天已上市且有成交的沪深京 A 股判断。
- **同花顺概念板块资金流向。** 目录有 395 个候选，20 天及 11 月 19 日的直接源端复核均使用同一组 386 个代码。目录中另有 5 个成份股集合和 WiFi6、AI PC、中国AI 50、2026一季报预增 4 个概念未出现。已确认以 386 个作为日常核查基线，新增或减少进入人工确认，缺少的 4 个概念的发布原因继续核实。
- **同花顺行业资金流向。** 目录含 90 个 `881` 行业代码，20 天每天完全覆盖，11 月 19 日直接复核也一致。目录的 `700`、`884` 代码在这些样本中均未出现。日常在现有生产 Check 中比较当天代码与生效的 90 项名单。 [现有行业资金流向 Check](../../orchestrator/src/orchestrator/defs/checks/moneyflow_ind_ths.py#L82)
- **东方财富板块资金流向。** 有本地文件的 19 天，行业、概念、地域均与当日板块分类代码一致。2026-11-20 重新查询 Tushare 的 `dc_index` 和 `moneyflow_ind_dc`。对这四个代码，资金流向从 11 月 11 日起返回新名称，板块分类从 11 月 12 日起返回新名称。例：`BK0509.DC` 在 11 月 11 日的板块分类中叫「网络游戏」，在资金流向中叫「游戏概念」。到了 11 月 12 日，板块分类也返回「游戏概念」，资金流向继续返回「游戏概念」。另外三个代码变化日期相同，`BK0524.DC` 从「参股期货」变为「期货概念」，`BK0891.DC` 从「国产芯片」变为「芯片概念」，`BK1189.DC` 从「腾讯云」变为「腾讯概念」。从 10 月 23 日到 11 月 19 日逐日对照同一交易日的两个接口，只有 11 月 11 日出现这四处名称差异。11 月 11 日 DG 两端各与自己的源一致。建议以板块代码判断覆盖，名称差异显示在详情。

### 3.6 日历、基础信息、曾用名、身份和生命周期（10 项）

实际单位是某次发布的**快照版本**，不是把全表当作 `D` 单日文件。某些快照本身有日更要求（如股票基础信息），应按该资产更新合同判新鲜，不等于每天重审历史明细。未换版复用有效结果；旧版不存在时不得将新版当旧日证据。

| 资产键 | 本项规则 / 检查方法 | 足以判定什么、仍缺什么 |
|---|---|---|
| `raw_tushare_trade_calendar` | 已确认复用[发布时的 SSE 日期覆盖校验](../../orchestrator/src/orchestrator/defs/assets/calendar.py#L93)，核已发布区间每个自然日恰好一行，包括休市日。 | 按发布版本复用；一期不额外逐日对照交易所公告。 |
| `silver_trade_calendar` | 已确认复用[发布时与当次 Raw 的双向对账](../../orchestrator/src/orchestrator/defs/assets/calendar.py#L328)，包含交易日期、开休市标记、上一交易日。 | 绑定发布版本后沿用 Raw 覆盖结论和 Silver 对账结果，无需独立审计。 |
| `raw_tushare_index_basic` | 发布前核对本批源端分页响应与 Raw 候选的代码和字段。 | 读取当日 Raw 产出对应的[原文件合同、主键和日期 Check](../../orchestrator/src/orchestrator/defs/checks/index_basic_checks.py#L562)及文件合同 Check 明细中的覆盖证据。 |
| `silver_index_basic` | 发布前用实际使用的 Raw 和本次采用的交易日算出应保留的指数，双向核对 Silver 候选代码及终止日期。 | 复用本次 Silver 产出对应的原有 Check，以及生命周期 Check 明细中的同批对账证据。原阻断条件继续供下游使用。 |
| `raw_tushare_stock_basic` | 已确认核所选交易日更新成功，以及更新后的总记录数较上一交易日成功版本的净增减绝对值不超过 20 条。范围是 Raw 的 `L/D/P/G` 全状态。[发布计数](../../orchestrator/src/orchestrator/defs/assets/stock_basic.py#L129) | 复用现有成功 Check 和两日发布计数，记录所比较的版本及增减值。超过 20 条或缺少参照版本显示「待确认」，无需独立核逐股名单。 |
| `silver_stock_basic` | 对同版 Raw 应用[当前上市人民币股票投影](../../orchestrator/src/orchestrator/defs/duckdb_sql.py#L186)，按 `ts_code` 双向核对。 | 已确认在生成快照时补 Check。 |
| `raw_tushare_namechange` | 已确认只核所选日是否有成功更新，复用当次发布及已有 Check。 | 一期齐备列显示「不适用」，理由为「仅考核更新」。无需独立审计曾用名事件覆盖。 |
| `silver_namechange` | 用本次 Raw、股票基础信息和正式身份种子，按[支持代码及获准的时间线规则](../../orchestrator/src/orchestrator/defs/assets/namechange.py#L264)核应保留的曾用名事件、生效区间及合法开区间。 | 已确认在生成快照时补 Check。优先复用生成环节已得到的时间线。 |
| `silver_stock_identity_map` | 对照本次生命周期核源代码的自映射，按[批准的历史代码映射](../../orchestrator/src/orchestrator/defs/assets/stock_identity_map.py#L76)及同版曾用名证据核历史映射和有效边界。 | 已确认在生成快照时补 Check。 |
| `silver_stock_lifecycle` | 以本次 Raw 股票基础信息及[生命周期投影规则](../../orchestrator/src/orchestrator/defs/duckdb_sql.py#L247)核代码、上市日、退市日和状态，覆盖应保留的历史对象。 | 已确认在生成快照时补 Check。 |

#### 指数基础信息日更审计

Raw、Silver 分层核验。更新状态按业务交易日记录各层实际交付。若只发布了 Raw，保留 Raw 的交付状态，Silver 和全链仍未完成。齐备状态读取各层产出对应的正式 Check 及其中的发布前覆盖证据。缺少当日产出、对应检查结果或同版证据时显示「待确认」并给出原因。候选对账失败在本次运行明细展示，已发布快照仍按其自身证据判定。只对旧快照重跑 Check 无法证明日更成功。审计页面复用已有结果，无需独立审计或单独跑 Check。 [指数基础信息发布与审计 LLD](dagster-phase-3-major-indices-low-level-design.html#index-basic-refresh-lld)

#### 指数及股票基础信息近 20 个交易日的实测

2026-10-23 至 2026-11-19 共 20 个已结束交易日。指数基础信息 Raw、Silver 均无新发布。DG 最近的两层物化及当时文件更新时间都为 2026-07-10，Raw 有 12,367 条，分属 8 个市场分类，Silver 有 11,581 条且记录的适用交易日为 2026-07-09。当时文件记录数与 DG 最近一次发布一致。这段时期没有逐日采集的快照，无法从现存文件判断 20 天里源端各市场指数名单的变化。

2026-11-20 通过 Tushare MCP 对照 DG 的 7 月 10 日快照。单次查询触及 8,000 条上限，因此按 DG 现有 8 个市场查询，中证指数再按 DG 已有的 11 个类别查询。各组未触及上限，合并覆盖了两份达到上限的初次结果。该范围内，Tushare 有 12,648 个唯一代码，DG Raw 有 12,367 个。源端有而 DG 没有 431 个，DG 有而本次源端未返回 150 个，双方共有的代码中 164 个在简称、发布日期或终止日期上存在差异。未返回的 150 个均属南华，逐代码抽查的 `NHADR.NH`、`NHAGR.NH`、`NHALR.NH` 返回为空，终止原因仍未核实。将本次源名单套用 Silver 的终止日期规则，以 11 月 19 日为终止日期比较基准，得到 11,848 个代码，较当时的 Silver 多见 431 个、少见 164 个。少见的 164 个含源端未返回的 150 个及已届终止日期的 14 个。 [Silver 筛选规则](../../orchestrator/src/orchestrator/defs/duckdb_sql.py#L665)

同期股票基础信息 Raw 每个交易日都有成功的发布任务。发布计数由 5,919 增至 5,924，窗口内相邻两次发布的总量净变化最大为 1 条，满足 20 条的数量稳定口径。

#### 五个 Silver 快照生成时检查

每次生产新 Silver 时，对照**这次生产实际使用的输入**及当次规则，核应有记录有没有漏写、多写或写错关键字段。优先使用写入过程已生成的应有结果和现有 Check 已读取的列，避免为核对再次计算完整历史时间线。结果记录本次输入、适用日期或规则版本及 Silver 产出。指数基础信息 Silver 在候选发布前完成对账，日审计按所选交易日复用与产出对应的 Check 明细，下游准入沿用原规则。其余四项按适用的快照版本复用本次 Check。旧版证据缺失时显示「待确认」，需要补核时须先确认原输入和产出版本。

这五项检查证明 Silver 对同版上游的转换与交付。上游齐备已确认时可以继承其范围。上游仍待确认时，Silver 详情记「仅与上游一致」，页面显示「待确认」。更新状态继续独立判断。

### 3.7 停复牌及事件型资产（4 项）

| 资产键 | 本项规则 / 检查方法 | 足以判定什么、仍缺什么 |
|---|---|---|
| `raw_tushare_suspend_d` | 已确认只核所选日是否有成功更新，复用当次发布和已有 Check。源确认无事件时允许零行。 | 一期齐备列显示「不适用」，理由为「仅考核更新」。无需独立审计停复牌事件。 |
| `silver_stock_suspend_daily` | 已确认只核所选日是否有成功更新，复用当次发布和已有 Check。 | 一期齐备列显示「不适用」，理由为「仅考核更新」。现有写入校验随生产运行。 |
| `raw_tushare_stk_nineturn` | 应有范围为当日已上市且按股票日线口径应有行情的股票。全天停牌不计入，盘中停牌当天仍有日线的计入，应有 `freq=daily` 的九转记录。无九转信号时信号字段可空。 | 已确认在 Raw 生产检查时补覆盖 Check，用当天已核验的股票日线名单核代码、日期及频度，单列缺码。日常直接读取 Check 结果。 |
| `gold_major_index_quantitative_structure` | 已确认所选交易日有产出且计算完成即通过，复用当次[计算完成 Check](../../orchestrator/src/orchestrator/defs/checks/major_index_quantitative_structure_checks.py#L62)。完成时事件列表允许为空。 | 日常直接读取所选日的完成结果，无需独立审计或复算事件。 |

#### 股票日线神奇九转的无信号记录与覆盖实测

2026-11-19 的 `000001.SZ` 有日频九转记录，上行计数 0、下行计数 1，两个九转信号均为空。该日 Raw 共 5,572 条，其中 5,175 条两个九转信号均为空。已确认在 Raw 生产检查阶段补覆盖 Check，计算当天已核验日线代码减去实际日频九转代码的差集，记录缺码和所用的日线、九转版本。日线未核验时显示「待确认」，日线就绪后只补查当天。日常复用这一结果，无需另跑独立审计。 [现有内容检查](../../orchestrator/src/orchestrator/defs/checks/stk_nineturn_checks.py#L198)

前次核对 2026-10-23 至 2026-11-19 的 20 个交易日，Raw 和 Silver 的缺码情况相同。3 天零缺口，16 天每天少 1 至 3 个代码，11 月 18 日应有 5,573 个代码、两层各有 4,221 个，缺 1,352 个。重查 Tushare，11 月 18 日的 `603499.SH` 和 `603501.SH` 均有无信号的日频记录，本地两层均缺。11 月 19 日少 `920309.BJ`，该股于 11 月 17 日上市，当时按该代码查询 11 月 17 日至 19 日尚无结果。以上为前次观测，补数验收按补齐后版本核对。

停牌复核覆盖同一 20 日的 133 个全天停牌股票与交易日组合，DG 日线和九转两层均无记录。另查 Tushare 11 月 19 日全天停牌的 `000635.SZ`、`002717.SZ`、`688496.SH`，均无日频九转返回。两个盘中停牌但当天仍有日线的样本 `301718.SZ`（10 月 23 日）和 `001381.SZ`（11 月 3 日）均有日频九转返回，两个信号字段均为空。全天和盘中停牌按上表所列方式计入应有名单。

## 4. 评审如何关单

每个资产要确认业务日和适用起止、目标版本及上游身份、应有对象和关键时间、合法空与例外、反例、读取的文件和键列以及触发方式。主要指数周线和月线按第 3.4 节区分可复用的交付及需要补核的情况。交易日历后续先用同版发布记录验证能否直接复用。任何自动执行须在业务规则、版本证据和读取预算通过后单独确认。

按每类规则选择验收反例。按键对账的资产应覆盖总行数相同但有缺失、重复或多出。第 3.3 节应覆盖上游有缺口但行数相同、目标总数不符、缺少前序状态承接计数和版本换版。其他资产按适用情况覆盖整只股票或板块缺失、休市、有效空事件、合法分钟例外与周期交付窗口。结论限定在已核验的资产范围。

## 5. 其他 114 项：逐资产复用口径、轻量补项与范围外

### 5.1 原 105 项复用候选

以下保留原 105 项的复用依据。另有第 3.2 节 5 个 ETF 分钟 Raw、第 3.3 节 7 个股票前复权分钟 MACD/KDJ 指标、第 3.4 节 2 个主要指数周线和月线 Raw 及东方财富板块成分 Raw、Silver，第 3.5 节股票复权因子 Raw、ETF 日线行情 Raw 和基金复权因子 Raw 各 1 项，以及第 3.6、3.7 节上交所交易日历两层、指数基础信息 Raw、股票基础信息 Raw、主要指数量化结构 Gold 优先使用现有检查或发布证据，共 129 项。每行所列范围是可接受结论的上限，使用时须核对同版证据和频度。

| 资产键 | 可复用结论的范围 | 不能据此推断 | 代码 |
|---|---|---|---|
| `silver_adj_factor` | **合同范围**：按生命周期定义必需与允许代码范围，核对缺码、多码，并对照筛选后 Raw。 | 以合同启用日期、生命周期与 Raw 版本为限，不是停牌表或所有历史日期均齐备的证明。 | [依据](../../orchestrator/src/orchestrator/defs/checks/adj_factor_checks.py#L760) |
| `raw_tushare_stock_daily` | **合同范围**：按验收时 Silver 股票基础信息的当前上市人民币股票、上市起日及同日全天停牌，核对缺码和多码。 | Raw 把退市日期置空且源名单只取当前上市，不代表历史日期当时应有的全部股票；不能代替 Silver 历史生命周期规则。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stock_daily_checks.py#L41) |
| `silver_stock_daily` | **合同范围**：按正式股票生命周期、市场起点和同日全天停牌计算应有范围，实际代码名单双向比对。 | 以对应版本的生命周期和停牌事实为前提；不能替代其他周期或数据层检查。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stock_daily_checks.py#L1135) |
| `silver_dc_industry_hierarchy` | **合同范围**：按固定三级行业基线与指定板块分类参考双向匹配，再与输出节点双向比对。 | 只证明这份基线及参考范围齐备；不证明每日板块行情或板块成分。 | [依据](../../orchestrator/src/orchestrator/defs/checks/dc_industry_hierarchy_checks.py#L132) |
| `silver_etf_adj_factor` | **合同范围**：复用同次上市 ETF 覆盖 Check 及同版 Raw 标准化对账。 | 结论以绑定的 ETF 基础信息快照、Raw 版本和交易日为限。覆盖差异按现有阻断规则处理。 | [依据](../../orchestrator/src/orchestrator/defs/checks/etf_daily_checks.py#L1212) |
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
| `silver_etf_daily` | **合同范围**：按绑定的 ETF 基础信息快照核当天沪深上市 ETF 覆盖，并与 ETF 日线行情 Raw 标准化结果对账。 | 齐备复用覆盖 Check 的实际结果。覆盖差异为非阻断告警，更新状态按产出另判。 | [依据](../../orchestrator/src/orchestrator/defs/checks/etf_daily_checks.py#L962) |
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

### 5.2 日更轻量检查

主要指数周线 Silver 和月线 Silver 两项已确认增补到现有 Check，规则见[第 3.4 节](#主要指数周线和月线的检查结果复用)。下列两项复用生产 Check 的现有读取做同日对账。已确认缺码或多码时，本项 Check 失败并沿用现有规则阻断受影响的下游生产。仅缺少本次对账所需的同日同版证据时，新增对账记未核验，页面显示「待确认」。原有生产门禁按各自规则判断。验收覆盖代码或业务键一致、总数相同但一缺一多，以及只有审计证据缺失三种情况。

| 资产键 | 新增的齐备性判定 | 代码 |
|---|---|---|
| `gold_stock_daily_qfq` | 同日目标 Gold 和同日 Silver 股票日线逐 `ts_code` 对账；复用正式生产已有复权因子门禁，不读前序日线。 只证明当天目标相对同版上游，源不齐不继承。 | [依据](../../orchestrator/src/orchestrator/defs/checks/stock_daily_qfq_checks.py#L59) |
| `ch_dc_daily_technical` | 在既有同日 Gold 与本机 ClickHouse 返回数据上比较 `(ts_code, trade_date, category)`；不增加数据库查询。 只证明当天目标相对同版上游，源不齐不继承。 | [依据](../../orchestrator/src/orchestrator/defs/checks/dc_daily_technical_serving_checks.py#L141) |

### 5.3 一期齐备不适用（原 9 个）

第 3.6、3.7 节另有股票曾用名 Raw、停复牌 Raw 和 Silver 共三个仅考核更新的资产。一期齐备不适用共 12 项。

| 资产键 | 说明 |
|---|---|
| `prod_core_index_daily_nineturn` | Prod 发布目标，不连接远端做本地审计。 |
| `prod_ch_dc_daily_technical` | Prod 发布目标，不连接远端做本地审计。 |
| `prod_ch_share_fact_market_breadth_daily` | Prod 发布目标，不连接远端做本地审计。 |
| `prod_core_stock_daily_qfq_nineturn` | Prod 发布目标，不连接远端做本地审计。 |
| `prod_core_wealth_sector_hierarchy` | Prod 发布目标，不连接远端做本地审计。 |
| `prod_core_wealth_market_turnover` | Prod 发布目标，不连接远端做本地审计。 |
| `lake_root_health` | 环境健康，不判断业务记录齐备。 |
| `raw_index_global` | 国际指数日线 Raw 审计纳入二期。 |
| `silver_index_global` | 国际指数日线 Silver 审计纳入二期。 |
