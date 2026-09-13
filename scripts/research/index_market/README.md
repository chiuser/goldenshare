# 指数大势研究：统一代码入口

目录整理日期：2026-09-09。规则见[研究目录 AGENTS](/Users/congming/github/goldenshare/scripts/research/AGENTS.md)。这里是离线研究，不接入产品或生产运行时。

## 目录

```text
index_market/
  statistics/                 四轮统计研究及来源校验
  chan/                       缠论教学、M0事件账本与独立复核
  tests/                      本主题全部隔离测试
  migration_20260909.json      旧/新路径、代码哈希与历史结果清单
  README.md                   当前运行方法
```

主方案、教材留在 `docs/product/`，历史输出留在 `reports/`；这里不复制报告和数据，也不另建产品配置。

## 当前研究状态

2026-09-13资料清理：[旧实验统一归档](../../../reports/index_market_history_20260913/README.md)。四类旧实验668份原件已封存为四个ZIP，33份原Markdown合并供阅读，教材两张图保留。旧目录移出，仅A目录保留现行source_gate仍需的manifest；下文旧实验的运行/复核命令须先按归档库存恢复完整来源链，不是当前可直接运行的入口。当前十股六轮仍直接读StockResearchStore，无解压或旧路径回退；算法及历史成绩未改。

当前十股资料已统一到[一个目录入口](../../../reports/stock_chan_research_20260912/README.md)：六轮621个散文件收敛为15个文件，人读结论/案例单列，机器证据单包去重。五个依赖入口已改为StockResearchStore直接读取；旧六目录已移入废纸篓，无旧路径回退。旧目录缺失不代表数据缺失，后续从统一入口读取，不重新复制行情。

2026-09-12卖点漏用审计：[诊断报告及六笔案例](../../../reports/stock_chan_research_20260912/sell_usage.md)。原134次到期中100次无任何账本卖点，34次其他类型被配对过滤且可执行；成交受限/记录异常0，163笔独立重建一致。只诊断，不运行任意卖点策略；优先核查无卖点识别链，尚未执行。入口`python -B -m scripts.research.index_market.chan.stock_sell_usage_audit --output reports/stock_chan_sell_usage_NEW`，只读封存资料，设计见原方案第24节。

2026-09-12退出对照最新结果：[固定买点退出报告](../../../reports/stock_chan_research_20260912/exits.md)。固定10股/60分钟，163个共同机会，对应卖点均值4.83%，固定60日4.85%；只有29笔实际卖点退出，134笔到期，未证明卖点增益。结构退出均值1.02%、平均MAE -3.25%，降低不利波动但未提高收益。470项测试通过；不是股数账户回测。设计见原股数方案第22节，复现入口为`python -B -m scripts.research.index_market.chan.stock_exit_study --output reports/stock_chan_exit_study_NEW`，只读封存输入，不访问DG。以下记录保留各轮历史口径。

2026-09-12最新：按用户纠正的**统一前复权、不额外处理分红送股**口径，已完成[蔚蓝锂芯002245.SZ五年30分钟策略回测](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_qfq_002245_30m_20260912--report-md)。主模型累计24.34%、最大回撤36.43%，同股买入持有75.12%/69.09%；6轮已完成、53笔成交、另有未平仓，五类信号检查通过。不是券商账户仿真，成本/成交假设及代码入口见主方案第14节。旧P0公司行为/原始价阻塞不再适用于这轮。

历史实现记录：[P0只读核验](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_share_002245_p0_20260912--report-md)与[P1合成金样本](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_share_p1_synthetic_20260912_verified--report-md)保留当时事实，不再作为当前前复权模型的阻塞项。B1/B2/B3买20%/30%/50%，S1/S2/S3卖50%/30%/20%，比例按固定股数基准；不使用指数窗口。原指数共振研究暂停扩批，下列旧记录和命令保留供复核，不自动启动原下一批。

2026-09-12最新：[首批等价提速](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_chan_parallel_first10_20260912--report-md)完成：1/2/4进程125.5/66.4/39.8秒，4进程快3.15倍，231项全字段结果比较一致，五项检验全部保留。[原首批10只个股回放](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_chan_g2b_first10_20260912--report-md)完成11席，真实暂停恢复通过；仅中国天楹有两笔提前买点。全量2189文件超过原2000上限，剩余279只未执行；约59分钟是优化前串行估算，不是当前运行状态。[首只试跑](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_chan_g2a_replay_20260912--report-md)和[沪深未退市股票排名](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_chan_shsz_r1_surviving_20260912--report-md)保留；三段对照50/48/50，排除已退市者及北交所，存续池有幸存者偏差。以下旧运行和清理记录是历史，不代表当前仍暂停在G1。

- [个股缠论独立方案](/Users/congming/github/goldenshare/docs/product/stock-chan-index-window-research-plan-v1.md)：沪深A股、最近五年的市场背景共振研究，不研究指数成员关系。[G1修正后报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_chan_shsz_r1_source5_20260910--report-md)已完成8月窗口5203只排名与50对50匹配，2月/4月存在未解释数据缺口，G2未执行。用户正在处理缺数，研究暂停；本轮仅做[废弃代码与报告清理](../../../reports/research_cleanup_20260910/report.md)。
- [四轮统计研究方案及历史结论](/Users/congming/github/goldenshare/docs/product/index-next-day-probability-backtest-plan-v1.md)：代码已运行过，方法结论以原报告为准。
- [缠论教学](/Users/congming/github/goldenshare/docs/product/chan-theory-csi300-teaching-guide-v1.md)：只完成结构回放，不是盈利回测。
- [买点预判与买卖盈利实验方案](/Users/congming/github/goldenshare/docs/product/chan-signal-prediction-and-profit-experiment-plan-v1.md)：分钟基准、A、F1、S1、C1、C2及第20节B0闭环可行性检查已完成。C2未证明次日增益；B0的18个组合全部不足30笔自然退出，按停止条件收尾。不进入产品、不继续调参，正式账户回测未实施。此前[M0交付复核](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_m0_csi300_20260909--review-md)为日线历史工程记录，不代表方法有效。

## 无真实数据访问的验证

从仓库根执行，使用现有 `.venv`，不自动安装依赖：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider scripts/research/index_market/tests
.venv/bin/python -B -m scripts.research.index_market.statistics.index_probability_backtest --help
.venv/bin/python -B -m scripts.research.index_market.chan.build_cases --help
.venv/bin/python -B -m scripts.research.index_market.chan.stock_share_synthetic --help
```

根 `pyproject.toml` 的 pytest `testpaths` 已纳入本主题测试；默认发现不会因搬离根 `tests/` 而遗漏它们。

股数账户的入口只接受固定合成样本，不接受股票代码或真实行情输入；不会读Lake或产生订单。复现使用全新报告目录：

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.stock_share_synthetic --output reports/stock_share_synthetic_NEW
.venv/bin/python -B -m scripts.research.index_market.chan.stock_share_synthetic --verify reports/stock_share_synthetic_NEW
```

`--verify`除校验代码/文件哈希，还重算固定样本并逐字段比较。当前有效验收目录是`stock_share_p1_synthetic_20260912_verified`；不带`_verified`的首轮重复副本已在[中间产物清理](../../../reports/research_cleanup_20260912/report.md)中移出，CLI序列化失败原因仍保留于原方案。

## 实验入口（需要另有执行授权）

当前前复权入口固定蔚蓝锂芯30分钟、五年、A配置与股数策略，只接受新输出目录；不访问原始价格或公司行为，不写Lake：

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.stock_qfq_run --help
.venv/bin/python -B -m scripts.research.index_market.chan.stock_qfq_run --output reports/stock_qfq_002245_reproduction_NEW
```

输出全部信号、四种模型账户、年度统计、信号/账户检查和manifest。当前结果目录为`reports/stock_qfq_002245_30m_20260912`，不可覆盖。

首批等价提速测量只消费已封存的G2b输入及其暂停目录引用，不重读Lake；固定1/2/4进程，保留五项检验，不能改股票池或缠论参数。设计及预算见个股方案第13节：

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.stock_chan_parallel --help
.venv/bin/python -B -m scripts.research.index_market.chan.stock_chan_parallel --output reports/stock_chan_parallel_reproduction_NEW
```

输出逐股等价哈希回执、三组耗时和最终manifest。完整旧事件继续引用G2b报告，不复制三套相同大文件。此入口是首批性能实验，不是全量调度器；只完成本轮测量也不等于剩余279只获得执行授权。

G2b仅固定首批10只，不能通过CLI改批次或选股；恢复总是写新目录并校验前序封存结果：

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.stock_chan_batch --output reports/stock_chan_g2b_pause_NEW --pause-after-first-unit
.venv/bin/python -B -m scripts.research.index_market.chan.stock_chan_batch --output reports/stock_chan_g2b_resume_NEW --resume-from reports/stock_chan_g2b_pause_NEW
.venv/bin/python -B -m scripts.research.index_market.chan.stock_chan_batch_audit --report reports/stock_chan_g2b_first10_20260912
```

个股G2a试跑及只读产物复核（参数固定、不会启动289只批量）：

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.stock_chan_replay --output reports/stock_chan_g2a_NEW
.venv/bin/python -B -m scripts.research.index_market.chan.stock_chan_replay_audit --report reports/stock_chan_g2a_replay_20260912
```

四个统计模块分别为：

```text
scripts.research.index_market.statistics.index_probability_backtest
scripts.research.index_market.statistics.index_condition_statistics
scripts.research.index_market.statistics.index_single_condition_backtest
scripts.research.index_market.statistics.index_risk_baseline_backtest
```

授权后用 `python -B -m <完整模块名> --output reports/<全新目录>`。参数、数据窗口和预算仍以原方案为准，不能因为目录整理而调参。

缠论教学脚本同样只接受新输出目录：

```bash
python3 -B -m scripts.research.index_market.chan.build_cases --chan-source /absolute/path/to/frozen/chan.py --output reports/chan_teaching_reproduction_NEW
```

实际计算/绘图需已有 DuckDB CLI、Python与Pillow及固定提交的第三方源码；`--help` 不要求这些外部计算资源。研究脚本不会下载或安装它们。教学输入窗口、结构参数和图片算法未改；原报告目录不能作为新输出。

## 本次整理与历史来源

以下为目录整理当时的记录；之后新增的M0见本页当前研究状态，不改写原迁移哈希。

- 原 `scripts/research/index_*.py` 四文件移至 `statistics/`。
- 原根 `tests/test_index_*` 中本研究的四文件移至 `tests/`，未动其他业务测试。
- 原 `reports/chan_theory_csi300_teaching_20260908/build_cases.py` 移至 `chan/`。
- 旧位置不留转发脚本、模块别名或双份实现；使用上面的新命令。
- 历史报告、数字、参数、输入清单和代码哈希保持原样。历史报告中旧命令代表当时入口，不能直接用于当前目录；以本页为当前复现入口。
- 后几轮原本要求当前依赖脚本的字节哈希等于旧报告哈希。搬目录修改了导入与路径，因此增加精确的迁移来源映射：仅登记的旧哈希、新哈希、目标路径组合被接受；任何未登记代码变化仍拒绝。新运行另保存 `prior_source_checks`，不篡改旧报告。
- `migration_20260909.json` 是一次目录迁移的证据，不是通用哈希豁免。不要为了让以后代码通过而重新生成此记录；算法改变必须按新的实验版本处理。

## 影响面与核验

整理前使用 CodeGraph explore/impact 检查研究入口、`safe_output` 调用与测试；再逐项核对内部导入、根路径计算、后续实验的哈希依赖、文档和pytest配置。图谱结果需结合当前文件判断，不代表已完成统计有效性验证。

核验包括：原62项隔离测试；新增目录、入口帮助、输出保护与来源校验测试；核心计算函数/Spec的AST迁移前后比对；历史结果逐文件哈希检查；文档检查。实际运行结果见主方案的目录整理记录。

只改变离线工具组织、当前命令及相应来源记录，无架构依赖矩阵、API、服务、DG或Lake变更。不重跑历史实验，不产生新策略成绩，不提交推送。其他主题的研究脚本保持原样。

## 个股缠论当前入口（G1已复核，G2未执行）

### 当前沪深G1排名入口

新实现为`chan/stock_chan_rank.py`，测试为`tests/test_stock_chan_rank.py`。范围和参数见独立方案；固定Gold30，源端点依据正式Silver5归并合同核对。只做排名和事前成交额匹配，不运行个股引擎。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.stock_chan_rank --help
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -B -m scripts.research.index_market.chan.stock_chan_rank --output reports/stock_chan_shsz_r1_reproduction_NEW
```

CLI只接受新报告目录。当前版本固定验证日2026-09-12排除已退市股，其余参数见方案；真实运行读取正式Lake，测试不读取。`blocked_data_quality`不等于程序崩溃或方法无效；`rank_complete`也不保证50个对照都齐备，应查看paired和缺席原因。禁止按结果自动删股或混源兜底，不自动进入G2。

G0废弃入口及成员/市值门禁已清理。当前排名仍需的B0认证和时间窗口选择原样保留在`chan/stock_chan_reference.py`，测试在`tests/test_stock_chan_reference.py`；读取白名单反例由现用排名连接的测试覆盖。不留旧入口转发，不修改历史manifest。

## 买卖闭环可行性B0入口（2026-09-10）

已完成，见[B0报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_minute_roundtrip_b0_20260910--report-md)，固定设计与验收在原方案第20节。新增`chan/minute_roundtrip.py`及主题内`tests/test_chan_roundtrip.py`；复用A原始首次事件，不使用C2次日去重样本，不改旧入口或信号。只检查B1/B2/B3分别入场、首个新S1/S2/S3退出的可行性，不计算正式账户或退出对照。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.minute_roundtrip --help
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -B -m scripts.research.index_market.chan.minute_roundtrip --output reports/chan_minute_roundtrip_b0_reproduction_NEW
```

CLI只接收新输出目录。结果含六组数量表、18组完整买点处置/持仓账本、七个事前按时间选定案例、独立事件配对/SQL路径核验及来源哈希。所有组合未过样本门槛，不自动进入账户回测；不读写正式Lake/DB/DG、不联网/安装/提交/部署。

## 次日非重叠取样C2入口（2026-09-10）

已完成，见[C2报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_minute_nonoverlap_c2_20260910--report-md)，固定设计与验收在原方案第19节。新增`chan/minute_nonoverlap.py`与`tests/test_chan_nonoverlap.py`，复用并认证C1/A保存证据和未改动的评分/验证模块。唯一变化为次日观察不重叠，不改信号、背景或统计门槛。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.minute_nonoverlap --help
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -B -m scripts.research.index_market.chan.minute_nonoverlap --output reports/chan_minute_nonoverlap_c2_reproduction_NEW
```

参数全部冻结，只接受新输出目录；旧C1的20日冷却仍保留为历史对照。输出包含原始/C1/C2统计、入选/重叠账本、身份变化、共同支持与区块缺失、年度/删除敏感性、独立SQL取样/评分核验。新结果称`nonoverlap`，不是改写旧`cooldown`；不访问正式Lake/DB/DG、第三方引擎或网络，不安装/部署/提交。

## 简单形态与三买C1对照入口（2026-09-09）

已完成，见[C1报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_minute_comparison_c1_20260909--report-md)，固定规则与验收在原方案第18节。新增`chan/minute_comparison.py`，独立DuckDB/候选核验为`chan/verify_comparison.py`；合成测试为`tests/test_chan_comparison.py`。只读已认证A保存投影和事件，不访问正式Lake/DG或第三方引擎，不应用F1/S1，不改原冷却与评分。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.minute_comparison --help
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -B -m scripts.research.index_market.chan.minute_comparison --output reports/chan_minute_comparison_c1_reproduction_NEW
```

输出必须为新目录；不接受窗口/容差/匹配阈值调参。保存候选、全部事件、背景/标签、共同支持、区块缺失率、年度/日期敏感性、邻近配对和核验。旧A基线字段不直接拿来当新背景基线；统计问题未解决不等于工程未完成，也不授权继续自动优化。

## 上层结构S1验证入口（2026-09-09）

已完成，见[S1报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_minute_structure_s1_20260909--report-md)，固定口径与验收在原方案第17节。`chan/minute_structure.py`使用A固定源码/配置及保存行情，重放全部事件并在B3触发时保存同频率上层结构值快照；不是跨周期过滤器，也不应用F1。测试为 `tests/test_chan_structure.py`。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.minute_structure --help
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -B -m scripts.research.index_market.chan.minute_structure --chan-source /absolute/path/to/frozen/chan.py --output reports/chan_minute_structure_s1_reproduction_NEW
```

需要既有隔离源码，拒绝版本/哈希/配置差异，不自动下载或安装。全事件必须等于A，快照端点不得超过当前柱；新目录保存事件、结构分类、前缀核验和manifest。代码不修改原回放/评分及第三方文件，不访问正式数据或服务。

## 背景过滤F1入口（2026-09-09）

已完成，见[F1报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_minute_background_f1_20260909--report-md)，固定规则/验收在原方案第16节。`chan/minute_background.py`只在原A事件上增加“距近期高点超过2倍前20日平均TR则跳过”，不重画信号、不改变冷却次序；测试为 `tests/test_chan_background.py`。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.minute_background --help
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -B -m scripts.research.index_market.chan.minute_background --output reports/chan_minute_background_f1_reproduction_NEW
```

新目录保存全部柱背景、保留/跳过事件、原始/冷却对照、同背景基线、完整交易日区块区间和manifest。事件文件中的baseline/lift仍保留原A字段，新背景基线成绩在`metrics.json`的`modes.*.after`。只读固定研究证据，不访问正式数据或第三方引擎；CLI不开放其它阈值。

## A后续诊断入口（2026-09-09）

已完成收益集中与高位失败诊断，见[诊断报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_minute_diagnostics_20260909--report-md)。固定方法与执行记录在原缠论实验方案第15节。新增 `chan/minute_diagnostics.py`，隔离测试 `tests/test_chan_diagnostics.py`；只消费固定A报告，不重放信号、不读湖、不挑过滤阈值。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.minute_diagnostics --help
.venv/bin/python -B -m scripts.research.index_market.chan.minute_diagnostics --output reports/chan_minute_diagnostics_reproduction_NEW
```

输出必须为新目录。`events.json`保存四项当时可知特征及原评分，`diagnostics.json`保存六组原始/冷却统计与日期聚类，`validation.json`保存无未来输入和独立复算证据，`manifest.json`固定来源与代码；人工解读报告后追加，不重写计算manifest。诊断发现尚不构成新策略有效性证据。

## 单变量试验A入口（2026-09-09）

已完成，见[A复核报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_minute_variant_a_20260909--review-md)和[原版/A对照](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_minute_variant_a_20260909--comparison-md)。仅取消买入侧三买的前置关联；使用第13节保存投影及固定manifest，禁止更改时间/对象/其它参数或覆盖基准。原运行器只增加显式校验器/输入加载器注入，默认入口不变；新模块 `chan/minute_variant_a.py` 管理配置、单变量完整对账、基准重放和结果对比，测试为 `tests/test_chan_variant_a.py`。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.minute_variant_a --help
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -B -m scripts.research.index_market.chan.minute_variant_a --chan-source /absolute/path/to/frozen/chan.py --output reports/chan_minute_variant_a_reproduction_NEW
```

输出的`comparison.md`是原版与A的对照入口，`comparison_manifest.json`记录基准重放、单变量来源及新旧输入一致性；`manifest.json`仍记录核心分钟运行产物。仅研究文件读写，不重新访问DG/Lake或源API，不自动安装依赖。

## 分钟基准入口（2026-09-09）

用户已停止日线方向，改测五年30/60分钟。当前范围、初始化和评分以原方案第13节为准；分钟A预判测试已跑完，结果见[五年分钟复核报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#chan_minute_5y_20260909--review-md)。未完成B账户盈利测试。

代码仍在 `chan/`：`minute_data.py` 冻结配置及只读Gold输入，`minute_replay.py`逐根分钟事件，`minute_score.py`交易日标签与基线/区块统计，`run_minute.py`六组入口，`verify_minute.py`从保存变化独立重建事件。测试在 `tests/test_chan_minute.py`。日线M0源文件及历史结果不变。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.run_minute --help
.venv/bin/python -B -m scripts.research.index_market.chan.verify_minute --report reports/chan_minute_5y_20260909
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -B -m scripts.research.index_market.chan.run_minute --chan-source /absolute/path/to/frozen/chan.py --output reports/chan_minute_reproduction_NEW
```

最后一条会执行获准范围的真实只读研究；输出必须为新目录。两个线程环境变量仅限制现有数值库并行度，不是信号参数或产品配置。无需安装、启动DG或写湖。

## M0入口（日线历史，2026-09-09新增）

实现：`chan/m0_data.py`管理固定Spec和只读输入；`chan/event_ledger.py`管理首次事件及变化；`chan/run_m0.py`执行核验；`chan/verify_m0.py`用另一条第三方迭代入口对保存的结果独立复核。隔离测试为 `tests/test_chan_m0.py`，默认不依赖真实Lake或第三方源码。

```bash
.venv/bin/python -B -m scripts.research.index_market.chan.run_m0 --help
.venv/bin/python -B -m scripts.research.index_market.chan.verify_m0 --report reports/chan_m0_csi300_20260909 --chan-source /absolute/path/to/frozen/chan.py
```

重新执行M0须按获准范围使用`run_m0 --chan-source <已核对源码> --output reports/<全新目录>`；仍为固定三指数输入核验与沪深300回放，不接受日期或信号参数开关。M0不是预测评分，不能将其事件数或测试通过解释成策略有效。
# 买点机会评估补充（2026-09-12）

60分钟对照已完成：[最终审计报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_opportunity_002245_60m_20260912_audited--report-md)，原方案第17节。入口：`.venv/bin/python -B -m scripts.research.index_market.chan.stock_timeframe_opportunity --output reports/stock_timeframe_reproduction_NEW`。只聚合封存30分钟行情并重做60分钟信号。

DG现有90分钟已直接回放：[结果报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_opportunity_002245_90m_dg_20260912--report-md)，原方案第18节。入口：`.venv/bin/python -B -m scripts.research.index_market.chan.stock_dg90_opportunity --output reports/stock_dg90_reproduction_NEW`。只读六个指定年度Gold文件，不重采样，不改行情，未显示比60分钟更好的效果。

四组过滤实验已按原方案第16节完成：[过滤对照报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_opportunity_filters_002245_30m_20260912--report-md)。顺势无改善，不追高小幅表面改善但未通过非重叠稳定性检查。入口：`.venv/bin/python -B -m scripts.research.index_market.chan.stock_opportunity_filters --output reports/stock_opportunity_filters_reproduction_NEW`；固定配置，不覆盖历史、不读取Lake。

蔚蓝锂芯30分钟买点的5/10/20日表现与大涨区间早期覆盖见[机会报告](/Users/congming/github/goldenshare/reports/index_market_history_20260913/README.md#stock_opportunity_002245_30m_20260912--report-md)。口径见原股数回测方案第15节，不改历史识别及账户代码。

复现：`.venv/bin/python -B -m scripts.research.index_market.chan.stock_opportunity --output reports/stock_opportunity_reproduction_NEW`。只读已封存研究报告，拒绝覆盖输出；不读Lake，不调参。配置集中在该模块不可变OpportunitySpec，实际值保存在manifest。

固定随机10股60分钟第一轮：[报告](../../../reports/stock_chan_research_20260912/initial.md)。5股完成，5股待停牌/零成交语义核对，禁止将结果称为10股全完成。入口：`.venv/bin/python -m scripts.research.index_market.chan.stock_random10 --output reports/stock_random10_reproduction_NEW`；只读固定名单30/60分钟年度文件，规则及名单不调优。

后续已按市场日历正常处理停牌，原10股全部完成：[完整报告](../../../reports/stock_chan_research_20260912/calendar.md)。当前入口：`.venv/bin/python -m scripts.research.index_market.chan.stock_calendar_run --output reports/stock_calendar_reproduction_NEW`。不填价格、不压缩停牌日期，零成交端点不假设成交；依赖第一轮封存材料，未改旧报告。结果仍未显示稳定优势。

核心买侧参数单变量实验：[优化报告](../../../reports/stock_chan_research_20260912/parameters.md)。基线、背驰0.8、回撤0.6、MACD面积法共40单元完成，三个新参数均未过预设可靠性筛查。入口：`.venv/bin/python -m scripts.research.index_market.chan.stock_parameter_study --output reports/stock_parameter_reproduction_NEW`；只读封存材料，不读DG、不修改旧参数入口，按原方案第20节执行。

类型与确认滞后实验：[结果](../../../reports/stock_chan_research_20260912/timing.md)。全部/B1/B2/B3/滞后<=4/<=8六组未找到可靠候选；类型表现有阶段反转，简单过滤长滞后没有稳定改善。入口：`.venv/bin/python -m scripts.research.index_market.chan.stock_signal_timing --output reports/stock_timing_reproduction_NEW`，仅读封存材料，原方案第21节。
