# 上证徐小明研究指标 V0.1 实施方案与 LLD

> P5整理说明（2026-11-03）：本文保留原设计、开发及验收记录的历史含义，不是当前开工或运行入口。旧执行代码和过程产物已按清单清退；原路径文字仅作出处。现行规则与阶段见[产品文档](../../../../docs/product/wealth-top-bottom-recognition-product-v1.md)，有效原材料见[资料索引](../../../../reports/xxm/README.md)。

## 当前阅读入口（2026-10-22，四项澄清后的文档修订）

下一轮四项工作以[算法方案§12.94](../../../../docs/product/xxm-direction-algorithm-plan-v0.1.md#xxm-next-round-plan)定义规则与待决项，以[本LLD§72](#xxm-next-round-lld)定义实现位置、输入/输出、恢复、预算及验收。本轮仅审计和完善这两份文档，没有开发、回放或算法验证。现程序仍为r2固定1%；DIF最高已确认，04批次没有完成整套结构回测。完整新算法仍有待决规则和输入前段缺口，不能据文档修订直接开工或集成。详见本轮审计（原记录：`reports/xxm_plan_lld_audit_20261021_01/README.md`）。

最新明确决定见[方案§12.94.13](../../../../docs/product/xxm-direction-algorithm-plan-v0.1.md#xxm-four-decisions)及[本LLD§72.15](#xxm-four-decisions-lld)：首次顶部须旧红柱→绿柱→当前红柱，底部反之。同一连续同色阶段的小峰在首次价格/DIF比较前排除，101变102只更新本段；旧同色A/B保留供反色后新C按顺序比较。已有钝化继续固定原参照，结构确认看两位DIF转折，不要求再次等反色。本轮只改文档，未编码或回测。

此前小样本合同及已有函数核验按§72.13保留；100/101提问撤回。首次阶段资格的最新更正见记录08（原记录：`reports/xxm_plan_lld_audit_20261021_01/colour_stage_comparison_08.md`），06/07只作历史，不能继承“先用同段峰比较、价格自然失败”的处理。其余计数/时序、独立观察及输入缺口继续补齐，文档一致不证明算法通过。

四项答复后的具体状态见决定记录06（原记录：`reports/xxm_plan_lld_audit_20261021_01/decision_update_20261022_06.md`），提问清单05（原记录：`reports/xxm_plan_lld_audit_20261021_01/development_clarifications_05.md`）按原时点保留。固定原参照、本轮已定项目不重开；最新同色柱至少两根和结构消失后不能自动再次钝化已有资料，由开发侧补齐验收，不要求管理员重新解释。

## 历史进展与既有实现（以下按各记录时点保留）

以下旧段落中的“最新、当前、待确认、已批准”限于各自历史范围，不覆盖上述当前入口；旧h1/a1/R1/r2及页面/接口验收分别保留，历史全量读取批准不自动成为下一轮授权。新规则统一到算法§12.94，本LLD§72不重复制定另一套算法。

2026-10-21接续：§71.5—6已按管理员确认的DIF最高口径做合并对照。85项隔离/直接回归、212前缀独立复核通过；未检查起伏幅度，未完成完整DIF参考池/价格/状态回测。最新04批次（原记录：`reports/xxm_near_first_review_20261021_04/README.md`）。

2026-10-21最新：§71对应算法§12.93。每根重检12点与212根柱形检查完成，81项隔离/直接局部回归通过；最高峰合并及完整结构状态仍未执行。报告见本轮回放（原记录：`reports/xxm_near_first_review_20261021_02/README.md`）。

2026-10-21盘口两课补充按§66只学习/取证：比较范围和近峰不成立时可用隔峰已有原话实例，具体图中峰与DIF迁移未核，未改现实现或验收标签。当前学习入口为研究§8.147。

2026-10-21“结构对应关系”课程按§65仅作资料与模型说明，学习摘要见研究§8.146；没有改变产品周期支持、环境判断或结构检测合同。

2026-10-21接续：管理员本轮要求先整理课程学习成果，当前按§64只维护文档，不实施§63待开发内容。两项成果和未决边界统一见[研究主文档§8.145](../../../../docs/product/xxm-macd-structure-research-v1.md)，现有实现及既往验收范围保持。

2026-10-19材料更正：**1/8收盘重新确认为2887.54，与本地显示一致；此前截图顶栏读数不能直接绑定当日末根，§33/33.1中的差异判断由§33.2更正，原比较文件保留。当前无新增内核开发需求，下一项研究建议尚未正式执行。**

2026-10-19接续结果：**§31两项真实数据接口正确性与性能验收已通过（368业务请求）。现存2010起日线来源完整；实际页面／整页仍TODO。此前提交f035a9e6c，本轮验收记录未另提交；未部署，非远端网络／登录或浏览器验收。**

2026-10-19当前状态：**首次TOP及必要预测／身份／消费者联动已落码，唯一检测器v0.1-r2、预测v0.3-r2；最终逐条对账见§30.8及[本轮报告](../../../../reports/xxm/conclusions/xxm_top_activation_r2_implementation_20261019/README.md)。底部与已激活信号保持原规则。原冻结预期分类经管理员批准更正为711＋504，旧文件不改；正式数据库／网络／整页和更早日线TODO继续保留，未提交／部署。下方早期状态均按当时记录保留。**

2026-10-17最新状态：**用户已确认§24并授权开发，R1唯一内核及v0.3-r1预测已落工作区；离线和夹具路由通过，正式整体验收因日线来源缺口暂停。当前交付边界及逐项对账见§25；未提交／部署，不宣称R1正式验收完成。§23保留研究轨迹。**

2026-10-16 A组当前状态：**用户已确认[§21](#xxm-same-segment-a1-code-lld)，先提交方案基线`f44c7bde`后，已实施唯一a1内核及全部合同／消费者。正式技术验收和逐条对账见§22；页面由用户验收，本轮开发改动按用户要求提交；未推送或部署。下方h1及旧“待确认／未实施”段落均为历史时点；§15为失败草案，不能继续作为编码依据。**

日期：2026-10-14。状态：**用户已批准规则、Figma、完整历史读取调整及仅指数详情页的 1280／1440px 适配；M0/M1/M2 技术验收完成，10 月 14 日标记视觉修订已同步四周期并通过技术验收，M3 等用户复看；未部署。**

代码级设计及实施（2026-10-16）：**用户已确认§17，B组唯一h1内核、查询／恢复／DTO及Wealth消费者已实施。冻结、正式预算及整页／双标签306请求全部通过，后端209项／前端1179项及类型／构建通过，交付见§18及实施报告（原记录：`reports/xxm_bottom_history_h1_implementation_20261016/README.md`）。§16工作规则与B1旧证据保留；页面由用户验收，未提交／部署。**

B组交付时点（历史，2026-10-16）：**B组原三日线漏报及两处120分钟映射已在正式h1内核和API中补齐；A组同段问题继续待审。§16.10及其前文的“未实现”是B1研究时点记录，以§18本次交付为准。**

此前方案修订记录（2026-10-16）：**底部同段结构消失、参照保留、重新钝化及预测的LLD见§15，待用户确认，产品代码未修改。§1—§14保留现行实现和历史验收，§15拟议合同尚未生效。原三处跨柱色底部消失漏报及两条疑似顶部多报未解决，状态以算法方案§12.1为准；修订分组和补证优先级统一见算法方案§12.8、本LLD§15.8。**

预测扩展状态：**旧单参考价版已实现，用户反馈价格前提与“确认价”不清楚；用户已确认价格范围、前置收盘关联及失效修订；R1原型/Figma同步完成，新版模型与v0.2页面消费已落码，读取优化获准并完成，最终四周期正式计算/接口/预算技术验收通过，页面待用户验收。本文件原识别层规则及验收记录保持，扩展设计见 §14 和预测方案 §15。**

2026-10-15展示修订：**用户已确认预测方案§18、60样本／95分位规则及Figma，四周期预检后已实现近期条件展示；局部价格适用域反例、190项后端／57项前端测试及最终产品接口预算全部通过。页面仍由用户验收。原识别、生命周期及v0.2数学合同不变。**

2026-10-15时间口径纠正：**已按统一业务日期完成修正：交易日20:00前使用上一交易日，20:00起使用当日，四周期共同切换。先修方案再修代码，相关回归及真实日期／预算核验已通过，详见§14.4和预测方案§19。页面待用户验收，未提交或部署。**

当前性能修订：**统一调度／共享加载及获准扩围的字段投影／配对读取均已完成。后端385项、前端全量1172项及类型／构建通过；最终产品178次预算＋4次最新请求全部通过，最慢2.976秒；16组整页／双标签页306请求全部通过，最大2.859秒，96份完整响应与原版一致。原算法、全部校验、4秒和依赖方向保持；页面由用户验收，未提交或部署。详见§14.6和预测方案§20.7。**

本文同时承担 implementation design 和 LLD，内嵌编码门禁。用户已确认的规则和范围以[算法方案](/Users/congming/github/goldenshare/docs/product/xxm-direction-algorithm-plan-v0.1.md)为准；用户可见呈现以[独立展示基准](./index-detail-xxm-benchmark-requirement-v0.1.md)为准。两份既有指数详情设计保留已验收内容，本专项是新增图层。

2026-10-15 新图证核查：2024-08-22 上证日线原图及用户讲解稿已明确绿色标记为底部“结构消失”；当前实现仅跟踪顶部历史，因此该处缺少输出。精确触发公式仍未确定，本次只补充证据，不改变内核、Spec、顶部专用 DTO／前端关联字段或编码门禁，不把底部历史撤销写成已实现。90／120 分钟仅通过口述收盘底钝化状态对照，不能记作精确事件验收。详见新案例及区分节点（原记录：`reports/xxm_software_indicator_crosscheck_20261015/case_20240822_semantics_20261015.md`）与算法方案 §7。

同日追加 2026-08-03 双周期核查：日线四处可辨认的普通事件对应；120 分钟按柱位映射的 7/10 15:00 绿色消失，当前内核仅输出再次底钝化，账本缺少绿色事件。保存源价格尚未跌破原结构低点，简单价格镜像不能解释；简单镜像顶部生命周期又会先因新底钝化截尾。黄色残片遮挡，不能确认同柱关系或认定再次钝化时序错误；当日讲解也未明确命名历史绿色。底部触发与生命周期仍待核，尚无可实施的新契约，不改顶部专用字段、页面或算法。完整回放和证据限制见8/3 核查（原记录：`reports/xxm_software_indicator_crosscheck_20261015/case_20260803_events_20261015.md`）。

**最新补证取代上一段的身份和同柱保留项：** 7/10 当日讲解明确是结构消失、还没有再次钝化，下一交易日上午到 3959 才重出。当前 `STRUCTURE → DULL / dif_return` 因未重新检查价格而提前激活，并漏记结构消失；同一负柱段内这类消失与跨柱色的历史撤销须分开设计，不能只新增底部历史价格镜像或在前端换字。现有预测将 DULL 视为已激活，DTO 又不允许 NONE 携带 activeReference，后续修正必须一起审计参照保留、重新激活、预测入口和全部事件消费者。这里只记录已确认缺陷及待修方向，不批准新契约或改变实现；精确消失门槛仍未知，日线／60／90／120 分钟和顶部行为不能仅凭本例宣布验证。详见7/10 核查（原记录：`reports/xxm_software_indicator_crosscheck_20261015/case_20260710_structure_disappearance_20261015.md`）。

## 1 目标、阶段与授权

只做 `000001.SH + day/m60/m90/m120`。交付包括一份计算内核、可复现的规则验收、连续日线基线、已有视频指标读数对照，以及财势乾坤真实 API 与图上显示。其他视频在版本冻结后用于后续验证。

本设计建议先完成开发态四周期显示，再单列发布验收。当前生产指数分钟路由及前端能力均受门禁限制；不能因本专项私自开放生产分钟、安装依赖、生成正式 Gold、改源指标或部署。读库／读湖核验属于来源审计，写库、写湖、DG 操作不在本次范围。

实施顺序：

1. M0：评审展示与接口设计，核验日线／分钟正式来源，冻结最小真实样本及来源差异。
2. M1：实现单一内核及因果／续接测试，复现冻结分钟基线，补连续日线验收和已有视频读数对照。
3. M2：独立 XXM 查询/API、前端消费及 MACD 图层；以真实 API 和浏览器验收。
4. M3：用户验收开发态结果；再决定发布阶段及后续新视频验证。每阶段结果落回原方案，不以 M1 通过宣称整个交付完成。

## 2 当前实现审计及影响面

本轮使用 CodeGraph `codegraph_status`、`codegraph_search`、`codegraph_explore`、`codegraph_impact`；查询覆盖指数 chart adapter、分钟 controller、日线与分钟 API 入口。模糊查询返回的同名／无关符号不作链路依据，补读当前实现确认如下：

| 当前链路 | 核实事实 | 本专项影响 |
| --- | --- | --- |
| `index_detail.py -> IndexDetailKlineQueryService -> IndexDetailQuery.load_kline_rows` | 日线取 `IndexFactorPro`，ORM schema 是 `core_serving`；默认 300 根、上限 2000 | 增加独立 XXM 查询，不向现有 K 线 DTO 塞研究字段 |
| `index_detail_minutes.py -> IndexDetailMinutesQueryService -> MajorIndexMinsLakeReader` | bars 与 indicators 独立只读正式 Gold；默认 500 根；各有 cursor | 使用相同源和值，增加完整历史前缀读取及严格对齐，不把两个 API 页面结果直接当完整算法输入 |
| `src/app/api/v1/router.py._include_local_minute_router` | 指数分钟 router 按 local capability 挂载 | 新分钟 XXM router 用相同 capability；生产分钟入口维持原门禁 |
| `useIndexMinuteSeries` | DEV 门禁；bars 先显示，indicators 独立结算；身份及时间错位可降级为仅 K 线 | 研究图层独立加载及失败，不阻塞 K 线，不从缺指标状态生成 NONE |
| `IndexChartWorkspace`／`IndexMinuteChartWorkspace -> DetailChartWorkspace` | 四窗格共享生命周期；目前 primitive 只接到主图 | 只新增 MACD primitive 接口，两个指数 adapter 消费；两个股票 adapter 默认空图层，须一起回归 |
| `indexMinuteViewModelAdapter` | 校验代码、freq、时间键、参数键及指标版本 | XXM adapter 同样严格匹配，不能按数组位置猜时间 |
| 旧研究 `replay_color_flip.py` 与冻结 JSON | 普通候选及历史跟踪定义是研究依据，无当前产品消费链 | 新产品内核不 import 报告脚本；验收可对照其冻结结果 |

CodeGraph 的 shared impact 结果未穷尽 React 间接消费者；实际消费者以上述四个 chart adapter 及其测试核实。新增 DTO 无既有消费者；潜在消费者仅本专项 client、adapter、controller、日线／分钟指数图表与测试。既有日线/分钟/九转/趋势 DTO 和参数行为不迁移、不保留第二套 XXM 口径。

目标依赖：`src.app` 装配 `src.biz`；`biz` 查询依赖既有 `foundation` 模型、Lake reader 与 capability；`wealth` 只经 HTTP 消费。没有 `foundation -> biz`、`biz -> qtf` 或生产模块依赖研究脚本。无依赖矩阵变更。

## 3 单一计算内核及文件落点

以下文件与职责已落地，实际代码及验收对应见 §13：

| 落点 | 拟议符号与职责 |
| --- | --- |
| `src/biz/services/wealth/market/index_detail_xxm/spec.py` | 不可变 `XxmSpec`、算法版本、Spec 哈希；算法参数只在此定义 |
| 同目录 `calculator.py` | `XxmCalculator.step/snapshot/restore`；完成柱顺序处理，普通状态与历史记录分离；不做 IO |
| 同目录 `runtime.py` | `XxmRuntimeBudget` 集中读取／响应／缓存／并发预算，不新增 env 或运营参数 |
| 同目录 `types.py` | 内部 Bar、Wave、Reference、OrdinaryEvent、TopHistoryRecord 和完整恢复状态；区别事件参照与活动参照 |
| `src/biz/queries/wealth/market/index_detail_xxm/` | 日线显式字段 query、分钟历史加载器、`IndexDetailXxmQueryService`；决定来源、连续性、窗口及状态 |
| `src/biz/schemas/wealth/market/index_detail_xxm.py` | 独立 DTO，extra forbid，数值及身份校验 |
| `src/biz/api/wealth/market/index_detail_xxm.py`／`index_detail_minute_xxm.py` | 日线／分钟独立 route，沿用 quote 鉴权；分钟仅 capability 装配 |
| `scripts/research/index_market/xxm/` 及主题 `tests/` | 验收入口、冻结输入 manifest 和基线对照；调用同一内核，输出新报告目录 |
| `wealth/src/features/index-detail/xxm/` | client/types、DTO adapter、`useIndexXxmLayer`、图层状态及业务 primitive |
| shared `detailChartTypes.ts`、`DetailChartWorkspace.tsx` | 可选 `macdPrimitives` 接到 DIF series，生命周期与原图表一致；不放 XXM 业务规则 |

只有指数日线和指数分钟两个真实消费者才抽取本图层共同部分；不建立通用策略框架、第二套四窗格引擎或新的配置中心。其他三个周期共享同一算法，状态按周期隔离。

## 4 来源、连续历史与完成柱

### 4.1 日线查询草案

```sql
SELECT ts_code, trade_date, close,
       macd_dif_bfq, macd_dea_bfq, macd_bfq
FROM core_serving.index_factor_pro
WHERE ts_code = :ts_code
  AND trade_date <= :last_completed_date
  AND (:after_date IS NULL OR trade_date > :after_date)
ORDER BY trade_date ASC
LIMIT :batch_size;
```

首批不传 `after_date`，从核查过的来源起点读取；后续按最后交易日续接。显式参数绑定，不使用宽泛字段或范围末尾限页来替代完整前缀。`startDate` 是显示起点，不进入初始化历史的下限。独立查询逐批读取 1000 根；完成日期按现有市场上下文、交易日历和上海时区判断，不能将今天未收盘的日线当已完成。

### 4.2 分钟来源

正式根仅 `/Volumes/datasource/data_lake`：`gold/quote/major_index_mins/freq={freq}` 和 `gold/indicator/major_index_mins_technical/freq={freq}`。复用 `MajorIndexMinsLakeReader` 的物理合同及路径校验，新增 `read_complete_history` 完整前缀入口，一次组织每路扫描；再按 1000 根分批计算。原 bars／indicators 分页及 cursor 保持原行为；不从 raw/Silver/旧 Lake/staging 兜底，不在本专项重新聚合 90 分钟。

bars 取 `close`，indicators 取 `macd_dif/macd_dea/macd`。完整键为 `(ts_code, freq, trade_date, trade_time)`，指标参数键及 `indicator_version` 须符合 reader 当前 Gold 合同。现有 bars／indicators 两条 cursor 仍各自使用，完整历史入口不接受 cursor；严格连接同一时间集合，并按旧到新输出。

先由统一市场上下文选业务日期，再只纳入该日期以内的已完成端点；20:00前不把当天已入库分钟纳入快照，四周期均使用上一交易日收盘，详见§14.4。严格核验正式来源实际60/90/120端点、交易日覆盖及中间缺口。不能仅用“相邻时间差很大”判缺失，也不能只验证两侧数量相等便忽略双方一起缺失的交易日。非有限指标、缺少源字段或无法解释的中间缺口拒绝计算，不跨缺口重新暖机。

### 4.3 数值与前缀身份

直接消费源值，不按画面小数位重算 MACD。日线因子可能按源精度保存，分钟有自己的初始化历史；M0 单列两者与冻结输入的差异，不能拼接成一份指标序列。`H = 2(D-A)` 用于来源对照，源独立取整不反向改写 H；任何来源精度容差只属于核验，不能进入算法的严格比较。

来源身份含对象、周期、参数／指标版本、历史起点、已处理时间和有序数值指纹。冷启动从连续起点处理；同源同版本追加先核对旧前缀再续接；既有1000根批次保存原真实snapshot（最多20个，计入原64MiB），过去可从不晚于请求的副本独立恢复再重放剩余部分，禁止最新/未来回填；旧历史修订、起点变化、版本变化则作废整个缓存及批次副本并重放，不能让旧锚点混入新输入。计算起点不随图表 limit 或滚动窗口改变。

内核工作状态有界；事件和逐柱显示状态另保存。缓存只是可重建的进程内查询加速，不是正式数据库事实，也不写 Lake。查询过去的 endDate 必须返回截至该柱的状态，不能把当前最终历史状态带回过去。

## 5 拟议独立 API / DTO 合同

用户本次指令已授权以下新合同；**已实现并通过真实 API 验收，现有行情接口行为保留**：

| 路由 | 参数 | 默认和限制 |
| --- | --- | --- |
| `GET /api/v1/wealth/market/index-detail/xxm-signals` | `tsCode` 必填；`period=day`；可选 `startDate/endDate/limit` | 默认 day、300 根；limit 1～2000，日期 YYYY-MM-DD |
| `GET /api/v1/wealth/market/index-detail/minute-xxm-signals` | `tsCode/freq` 必填；可选 `startDate/endDate/limit` | freq 仅 60/90/120；默认 500 根；limit 1～2000；仅既有本地 capability |

代码规范化后必须为 `000001.SH`。未知／重复参数、反向日期、非法 limit、其他频度返回 400；合法但本版不支持的其他标的返回 404。不接受算法门槛、参照宽度或历史到期参数。鉴权沿用现有 quote 权限，未授权按既有 401/403 合同处理。日期及 limit 限制返回窗口，后端仍保留窗口前的历史。

```ts
type XxmPeriod = "day" | "m60" | "m90" | "m120";
type XxmTime = string; // 日线 YYYY-MM-DD；分钟 ISO8601 +08:00
interface XxmResponse {
  tsCode: "000001.SH";
  period: XxmPeriod;
  algorithmVersion: string;
  specHash: string;
  source: {
    kind: "daily_factor" | "minute_gold";
    inputId: string; // 有序输入指纹，不暴露路径
    startTime: XxmTime | null;
    computedThrough: XxmTime | null;
    initialHistoryIncomplete: boolean;
    indicatorVersion: number | null;
  };
  points: Array<{
    time: XxmTime;
    close: number; dif: number; dea: number; hist: number;
    ordinaryState: "NONE" | "DULL" | "STRUCTURE";
    ordinaryDirection: "TOP" | "BOTTOM" | null;
    activeReference: { startTime: XxmTime; endTime: XxmTime; price: number; dif: number } | null;
    pendingTopHistoryId: string | null;
  }>;
  events: Array<{
    id: string; time: XxmTime; direction: "TOP" | "BOTTOM";
    type: "DULL" | "STRUCTURE" | "CANCEL" | "RESEARCH_HISTORICAL_WITHDRAWAL";
    route: "activation" | "dif_turn" | "dif_return" | "color_flip" | "dif_break" | "dif_break_on_flip" | "historical_price_break";
    fromState: "NONE" | "DULL" | "STRUCTURE";
    eventReference: { startTime: XxmTime; endTime: XxmTime; price: number; dif: number } | null;
    relatedTopHistoryId: string | null;
  }>;
  topHistories: Array<{
    id: string; confirmedAt: XxmTime;
    confirmationRoute: "dif_turn" | "color_flip";
    pricePeak: number; pricePeakAt: XxmTime;
    originalReference: { startTime: XxmTime; endTime: XxmTime; price: number; dif: number };
    status: "PENDING" | "ENDED";
    endedAt: XxmTime | null;
    endReason: "original_reference_break" | "new_top_DULL" | "new_top_STRUCTURE" | "historical_price_break" | null;
    observedThrough: XxmTime;
    ageBars: number;
  }>;
  meta: { count: number; responseStart: XxmTime | null; responseEnd: XxmTime | null };
  dataStatus: { status: "READY" | "DELAYED" | "EMPTY"; message: string | null; asOf: XxmTime | null };
}
```

`points` 与返回窗口内已完成 K 线逐点对应；`events` 按时间、普通事件优先、id 稳定排序。`topHistories` 包含窗口内活动／结束或事件关联的记录，哪怕确认时间在窗口外；其观察及结束状态只能使用截至本次 endDate 的事实。挂起记录在窗口末端仍为 PENDING。当前 NONE 的方向及活动参照为 null，但同柱旧方向结构事件不能丢失。

主结果只用 1% Spec，敏感性结果仅进离线报告。响应不提供两套算法结果供页面挑选。无事件不是 EMPTY：有合法输入、全部 state=NONE 也返回 READY。真实 API 样例须在 M0/M2 分别冻结输入和实际响应，下面只冻结必要情景，不冒充实测：

| 情景样例 | 必须验证的字段与行为 |
| --- | --- |
| 正常变色确认 | 当柱 points 为 NONE/null；events 为旧方向 STRUCTURE/color_flip；history 指向原目标 |
| 正常研究撤销 | events 引用旧 history；history ENDED/historical_price_break；原结构仍在账本 |
| 延迟 | dataStatus=DELAYED，computedThrough/asOf 为实际末端，不填请求日期后的 points |
| 空源 | EMPTY，points/events/topHistories 为空，computedThrough/asOf 为 null |
| 无事件 | READY，points 有值，events 可为空，不写“暂无数据” |
| 错误 | 非 200 的现有 WebAppError envelope，研究图层 error；不给伪造空结果 |

## 6 参数、缓存与性能预算审计

算法参数表及影响关系统一引用算法方案 §3；这里仅登记新增运行／渲染预算。运行预算已在 runtime.py 及 Foundation 完整历史入口集中定义；前端超时及图层样式各有单一来源。实测见 §13；不是新 env、Settings 或运营开关。

| 名称／默认值 | 来源及持久化位置 | 消费者／依赖 | 生效、可见性及测试 |
| --- | --- | --- | --- |
| `source_batch_rows=1000` | 后端单一运行预算定义 | 日线 query、分钟历史加载器 | 随代码版本；debug 计批数，验证批次不改变事件 |
| `max_source_rows=20000`／`max_source_partitions=5000` | 同一运行预算；分钟分区上限复用现有 reader | 源加载器；先核查规模，超限拒绝 | 不截掉旧历史后继续算；正反边界测试 |
| `response_default_day=300`／`response_default_minute=500`／`max_response_rows=2000` | 同一运行预算 | 两 route、service、client 请求；与原图表窗口对齐 | 缺参及临界测试；字段不在页面自行定义 |
| `max_response_bytes=1MiB` | 同一运行预算 | DTO 序列化门禁 | 超限明确失败，不截事件或丢关联记录 |
| `cache_max_bytes=64MiB`／`cache_max_series=16` | 同一运行预算；当前执行详见§14.5 | 服务进程内一个LRU，源entry和预测响应共用字节／项数上限；key含Spec和来源身份 | 超限驱逐可重建项；历史修订、过去endDate、续接、响应副本和驱逐测试 |
| 完整历史扫描 `memory_limit=512MB`／`threads=2` | Foundation reader 中单一定义；仅新完整历史入口的 DuckDB 连接配置，不持久化、不增加 env | XXM 分钟源加载器；不作用于原分页方法 | 每连接生效；真实扫描及运行配置断言。沿用 M0 临时只读扫描已测的资源设置，避免默认高并行的内存峰值；512MB 是 DuckDB 管理内存限额，不是进程 RSS 硬限额 |
| 请求超时 5s | 前端 API client 的单一定义 | 本专项 controller；须 AbortController | 明确失败和重试，保留其他模块 |
| 标记视觉参数 | 展示基准 §5／§9，`markerGeometry.ts.XXM_MARKER_STYLE` 单一定义：字号 12px、字重 700、行高 16px、行距 18px、点半径 4px、点边与文字间隔 8px、边界 padding 3px；无持久化、env 或用户开关 | 日线和分钟同一 primitive；字号影响测字、行高影响碰撞范围，半径与间隔共同决定左侧文字位置 | Figma 已获用户确认；style、实际绘制字重／圆点、左侧／边界／同柱／邻点避让及四周期真实页面验证；颜色和字体仍取现有 token |
| 指数详情页最小宽度 1280px | `index-detail-page.css` 仅在 `body:has(.index-detail-app)` 覆盖既有 `--cs-layout-content-min-width`；全站 token 原值 1460px 保留 | global.css 的 body 最小宽度；只在指数详情页生效，无持久化、无 env | 用户已确认该范围；实际 1280／1440px 无横向滚动、切到其他页面恢复原值。指数页内的三层图表 grid 显式用 `minmax(0,1fr)` 单列，避免旧 canvas 固有宽度撑住容器导致坐标轴裁切；不改 shared Shell 或其他页面 |

后端暖缓存P95目标≤1s，冷缓存P95目标≤3s；当前按§14.5最多两个实际XXM加载工作同时执行，同源等待者不占名额，单请求包括等待／读源／计算不超过4s，超过预算显式失败。M0测得请求量、分页次数、文件数及数据量；M2及本轮补测真实API P95、响应字节数、进程峰值内存和端到端耗时，追加整页混合／双标签页。预算未过不得通过删历史、用固定暖机或伪造ready解决，须先调整设计。

源读取只做只读 SELECT／Parquet 查询，按批推进，无覆盖全历史写事务、业务表持久化或 TaskRun 状态写入。计算有界输入及缓存预算，不能把小范围冻结研究耗时当作正式来源性能成绩。不新增依赖安装。

## 7 前端 LLD：请求、适配、绘制

1. `useIndexXxmLayer` 仅在上证及四个受支持周期启动；取得实际 K 线窗口后请求对应 XXM endpoint。其他周期／标的零 XXM 请求。缓存 key 含对象、周期、窗口及响应版本；局部重试作废本图层缓存。
2. 旧请求在切换对象、周期、窗口及卸载时取消，request id 防止旧响应覆盖新图。XXM 不进入首屏 K 线阻塞链，失败不覆盖页面 ready。
3. adapter 验证响应对象、周期、唯一时间、完成末端及每个显示点的 close/DIF/DEA/hist 与当前图表事实一致。日线用业务日期，分钟使用既有分钟时间转换；不加减小时“校正”坐标。错位则整层拒绘，不静默丢掉异常 marker。
4. 只有格式化、时间转换、标签映射和像素几何发生在前端；活动参照、普通状态、历史结束和事件全部由后端给出。接口数值可原精度在详情核对，既有 MACD 标题格式不改算法输入。
5. 新 `macdPrimitives` 可选为空，挂到真实 DIF series。attach/detach、销毁及更新复用共享工作台；新增业务 layer 不新建 chart、fitContent 或改 logical range。切换 MA/BOLL/趋势时不重置视图。
6. 图层异步完成应仅更新 primitive 数据及详情索引；不能因 effect 依赖加入整份响应而重建四张图或导致已拖动窗口跳回默认。共享部分不读取 XXM 事件类型或参数。
7. 原指标数据决定 MACD 动态纵轴，mark 文案不进入 autoscale。标记不能覆盖标题、右轴或跨 pane；同柱及密集事件按展示基准避让，详情完整保留。

### 7.1 2026-10-14 已批准视觉修订的执行约束

依据为用户已确认的 Figma `2010:2173` 与展示基准 §9。本轮在当前 `dev-interface` 修改 XXM 图层，不改后端、DTO、数据范围、算法或 shared 图表合同。CodeGraph `codegraph_explore` 已覆盖 `eventLabel → layoutXxmLabels → XxmMacdPrimitive`、详情及日线／分钟两个 adapter；`codegraph_impact(eventLabel)`确认详情还依赖完整方向标签，因此增加图上短标签格式化，保留详情原文字。索引未识别测试关系，以当前对应测试文件补核。

| 硬口径 | 实现点 | 正向与反例验收 |
| --- | --- | --- |
| 8px 点、12px 加粗、16px 行高，点边间隔 8px | `XXM_MARKER_STYLE` 与 primitive 的 canvas font／arc／文本行定位 | 实际 draw 断言半径 4、700 字重；不得沿用 1.5 半径或普通字重；浏览器检查真实绘制 |
| 图上无顶底前缀，详情仍有方向 | `adapter.eventMarkerLabel`；几何布局使用短标签，`eventLabel` 继续用于详情 | 七类方向／事件组合短文字覆盖；详情仍显示底钝化／顶结构消失，底部历史研究消失仍拒绝 |
| 标签尽量放左侧，同柱／密集时避让 | `layoutXxmLabels`，先同一行再上下，左边不够时才右侧 | 中部／右边界必须左侧；左边界右侧但不裁切；同柱、邻点、极窄空间不碰撞、不覆盖事件点 |
| 点时间与 DIF 不动，保留全部事件 | primitive 仍由 timeScale／DIF series 取坐标 | 输入位置不变；全部 arc 保留，autoscaleInfo 为 null；不因标签减少而删事件 |
| 日线及 60／90／120 分钟一起同步 | 两个 adapter 继续使用同一 `useIndexXxmLayer`／primitive，无私有样式分叉 | 既有两类 adapter 与 shared 交互回归；四周期真实 API 页面及 1280／1440px 验收 |

标记是已有动态 canvas 图形，Figma 导出的圆点 SVG 与现有实心圆 primitive 对应；DIF／DEA／柱形继续按真实 API 数据绘制，不引入设计样例或静态行情图片。中文字体沿用当前页面基础字体 token，按设计统一尺寸和字重。未新增安装、配置项、接口或架构依赖。

**执行结果：** 该表五项已实现并验收。`adapter.test.tsx` 覆盖短标签／详情方向及禁止底部历史消失；`markerGeometry.test.ts` 覆盖左侧、边界、邻点、同柱 +2、点坐标及实际 canvas 字重／半径。Wealth 全量以两个 worker 运行，162 文件／1156 项通过，typecheck／build 通过；四周期真实 API 均 HTTP 200，10 个真实布局样例均无文字重叠、裁切或覆盖圆点。两类指数 adapter、两类股票 adapter 与 shared 交互回归通过。CodeGraph 开发后 `sync/status` 正常，`impact(layoutXxmLabels)`只涉及几何与 primitive；无依赖矩阵变更。详细字段、截图和当前代码哈希见本轮验收报告（原记录：`reports/xxm_ui_revision_20261014/README.md`）。目前供用户复看，未提交、推送或部署。

## 8 状态与异常方案

页面已有 ready 不被 XXM 局部失败覆盖。XXM 状态为 unsupported/loading/ready/empty/delayed/error，禁止本版用 PARTIAL 来跳过内部历史缺口；已核验前缀但末端落后可 delayed，中间断档或对齐失败则 error。

当前异常注册表没有 XXM 码。以下为**待评审登记方案**；编码前须同步 `exception-code-registry.md`，不能先在代码中发明未登记码：

| 拟议 code | HTTP／状态 | 触发及恢复 |
| --- | --- | --- |
| `XXM_REQUEST_INVALID` | 400 | 参数非法；不重试非法请求 |
| `XXM_NOT_SUPPORTED` | 404 | 合法对象超出上证范围；不启用图层 |
| `XXM_SOURCE_NOT_READY` | 200 EMPTY/DELAYED | 无输入或合法前缀的末端落后；说明实际覆盖 |
| `XXM_SOURCE_CONTRACT_INVALID` | 500 | 非有限值、身份/时间/参数版本错误、中间缺口；停止本图层，排查来源 |
| `XXM_BUDGET_EXCEEDED` | 503 | 源规模、响应、并发或时限超预算；明确失败，不截历史 |
| `XXM_QUERY_FAILED` | 500 | IO、查询或计算失败；保留行情，允许局部重试 |

鉴权沿用既有机制；分钟能力未配置沿用 local capability 的现有码，未挂 route 的生产分钟保持 404。错误 envelope 由既有 WebAppError 生成。客户端对齐异常只产生本图层 error，不伪造服务端 reason code。

## 9 核心测试与验收

算法规则逐条映射原方案 I1/W1/A1～A3/T1～T2/F1/H1～H5/O1；不得只验证事件总数。新增案例：

| 编号 | 要证明的用户可见结果 | 计划落点 |
| --- | --- | --- |
| S1 | 连续日线和三类分钟源按显式字段、版本和时间键进入同一内核 | query/source loader tests；真实只读样本 |
| S2 | 可见窗口前的峰及结构正确关联；300/500/不同 startDate 交叠部分一致 | query/API tests，窗口前缀对照 |
| S3 | 今日未完成日线、未完成分钟柱均无确认标记；未知日期不补柱 | completion/source tests，API 端点样本 |
| S4 | 原历史修订使缓存失效；连续追加、分批、恢复与全回放一致；过去 endDate 无未来状态 | calculator/cache tests |
| A1 | 走真实日线及分钟路由，非 mock service/query，逐点核对 DTO、Spec、源值和事件 | 新 `tests/web/test_wealth_index_detail_xxm_api.py`；开发态真实端到端 |
| A2 | 参数、鉴权、超预算、空源、延迟、源违约走规定状态；原接口行为保持 | web tests/profile matrix；原 index_detail API 回归 |
| U1 | 四周期正确显示黄钝化、紫结构、灰取消和绿研究消失；原结构标记保留 | 新 feature/chart tests + 真实浏览器截图及 Tooltip 核对 |
| U2 | 同柱两层事件、窗口外参照、变色确认的 NONE 与旧方向结构事件不丢失 | adapter/chart tests + 代表性真实 case |
| U3 | 切换、拖动、缩放、异步图层完成、鼠标离开、失败重试不串状态或重置视图 | hook/shared tests；浏览器交互验收 |
| U4 | 未支持对象和周期零请求；两类股票图表及其他指数无新增图层 | shared 四 adapter 回归 |
| V1 | 旧视频逐项对照 C/DIF/DEA/H、游标时间和精度，差异不以调参抹平 | 新报告，素材及输入哈希，逐条对照表 |
| V2 | 后续其他视频检验冻结版本，保留反例和无法评分项 | 后续独立验证账本，不混入 M1 回归样本 |
| P1 | 后端、传输、缓存、真实页面超时符合 §6；无连续全历史重算作为追加主路径 | 真实开发态性能记录 |

计划命令为现有环境 `python -m pytest` 指定新算法／query／web 测试及原指数接口测试；Wealth 用已安装工具运行 `npm run test -- --run` 指定 hook/chart/shared 用例，再运行 `npm run build`。具体新测试路径在落码时登记。不得触发隐式安装或将单测 mock 成绩替代真实 API 与页面验收。

## 10 LLD 编码门禁矩阵

此矩阵逐项映射通用交付清单 §2.1～§2.18；当前是设计映射，**不是测试已通过**。

| 通用项 | 适用性及落地 | 验证方式 |
| --- | --- | --- |
| 2.1 事实链先行 | 适用；算法方案＋独立展示基准＋本文 | 新增展示/API 评审及 M0 样本冻结后才开工 |
| 2.2 后端事实归一 | 适用；calculator/query/DTO；前端仅适配 | I1～O1、A1、U2 |
| 2.3 状态机 | 适用；§8、5s 超时、独立 hook | A2、U3 |
| 2.4 显示与数据语义 | 适用；顶底文字、事件类型、绿色消失专用语义 | U1/U2；例外白名单 E1 |
| 2.5 行为过程 | 适用；前缀、续接、切换、异步及交互 | H5、S4、U3 |
| 2.6 文档同步 | 适用；原算法、研究进度、原指数设计及索引同步 | 本轮链接校验；每阶段计划对账 |
| 2.7 渐进替换 | 适用；新增独立图层，无 mock 回退；一份内核 | A2/U4，活动引用审计 |
| 2.8 契约及消费者 | 适用；§5 新 DTO，消费者见 §2/§7 | schema、TS、真实 API及两指数 adapter |
| 2.9 坐标与文案 | 适用；MACD 保留带符号动态轴，说明进 Tooltip | U1/U3；marker 不影响 autoscale |
| 2.10 统计与传输 | 不涉及分位统计；状态递推在应用层，源投影／过滤在 query | S1/P1；无全市场大表拉回 |
| 2.11 策略配置生效 | 不适用；无策略中心或运营输入，新预算见 §6 | Spec 来源唯一与不接受门槛参数测试 |
| 2.12 清单映射 | 适用；本矩阵 | 18 项逐项有依据及验证 |
| 2.13 例外及断言 | 适用；E1 色彩语义，其余无例外 | U1，颜色／文字及研究身份断言 |
| 2.14 参数优先级 | 适用；不修改已有轴语义；标记坐标不影响值 | shared autoscale/range tests |
| 2.15 并排双图 | 不适用；本专项没有并排双图；四 pane 对齐仍适用 | U3，轴及时间键同步回归 |
| 2.16 指标卡片长度 | 不适用；没有新指标卡片；紧凑标题和 Tooltip 要避让 | U1，1280/1440/1600px 浏览器核对 |
| 2.17 核心真实用例 | 适用；核心字段来自 §5 和展示基准 §4 | A1、U1/U2；仅 mock 不可交付 |
| 2.18 八条抽象原则 | 适用；下表 | 对应原理及用例必须逐项通过 |

| 抽象原则 | 落点 | 测试 |
| --- | --- | --- |
| 事实源单一 | 每周期同源前缀、单一内核、后端状态 | S1/S2/A1 |
| 契约先行与冻结 | §5 新接口及 DTO，编码前评审 | A1/A2/TS 构建 |
| 配置一致 | 原方案 §3 Spec；§6 运行预算单一定义 | Spec 哈希与非法参数测试 |
| 默认行为显式 | 1% 主结果、日线/分钟默认窗口、独立局部加载 | A2/U1/U4 |
| 排序与筛选确定 | 时间递增、普通事件优先、未完成柱排除 | S2/S3/U2 |
| 性能预算前置 | §6 批量／规模／并发／payload／超时 | P1/A2 |
| 可观测与异常标准化 | §8 注册码、实际计算末端、独立失败状态 | A2/U3 |
| 用户可见结果中心 | 真实 API、图上标记及逐项详情 | A1/U1/U2 |

例外白名单 **E1（呈现方向及 Figma 具体稿均已获用户确认）**：仅 XXM 事件标记允许绿色表达历史结构消失，依据为已有软件观察的事件文字语义；本图层必须同时给文字和研究身份，所有行情涨跌色保持不变。没有其他例外。待跟踪记录的详情用紫色／中性文字，不用绿色误表示已消失。

## 11 门禁状态

| 门禁 | 当前证据／状态 | 关闭方法 |
| --- | --- | --- |
| 四项算法取舍及交付目标 | 已确认，见原方案 §10 | 不重复申请确认 |
| 新增展示及接口事实链 | Figma 的 8 个完整页面状态及 2 份状态／响应式板已获用户确认；“顶消失”文案已修正，具体节点见展示基准 §1.1；本次指令授权按本文新合同实现；现有行情接口已真实核验 | 视觉及新 XXM 接口技术验收已关闭，见 §13；等 M3 用户验收 |
| 日线连续来源及分钟正式源样本 | 已核验日线 912 根及分钟 17260／12945／8630 根；无交易日缺口，输入已留证 | 来源门禁已关闭，详情见 §12；完成柱／初始化／过去窗口测试通过，见 §13 |
| 核心真实样例及异常登记 | M0 输入及响应已冻结；六个 XXM 异常码已登记并实现 | 真实日线／分钟响应、异常参数、鉴权、缺源、预算错误及重试已验收 |
| 运行及渲染预算 | 规模未超行数／分区预算；现有分页读完整历史超过 4 秒，批量扫描可行性约 1.94～2.32 秒 | 读取调整已确认且落实；最终冷／暖 P95 均达标，完整请求硬预算保持 4 秒 |
| 编码及后续验收 | M1/M2 技术验收完成，M3 待用户 | 用户验收后另定发布阶段；新视频与原软件真值继续未确认 |

本版不声称已满足全部开工门禁或已还原原软件公式。用户要求先完成 Figma，本轮已完成该交付，设计示例不作指标对照样本。用户已确认设计并授权按方案实施；来源及现有接口核验已完成，用户已确认一次扫描、1000 根批次的调整，已同步本设计并进入编码；若真实来源与方案冲突，保存差异并讨论修改，禁止临时兜底。

## 12 M0 实测结论与待确认读取调整（2026-10-13）

[完整核验报告](/Users/congming/github/goldenshare/reports/xxm/conclusions/xxm_source_audit_20261013_213852/README.md)和[证据 manifest](/Users/congming/github/goldenshare/reports/xxm/sources/xxm_source_audit_20261013_213852/manifest.json)保留只读范围、字段投影、行数、SHA256、连续性、旧输入对照及真实现有接口响应。

| 核查项 | 实际结果 | 结论／实施约束 |
| --- | --- | --- |
| 日线来源 | serving 视图直接映射 `raw_tushare.idx_factor_pro`；2023-01-03～2026-10-13 共 912 根，开市日无缺口 | 直接消费 BFQ 指标；保留初始历史不完整，不自行补早期因子 |
| 三类分钟来源 | 2009-01-05～2026-10-13，各 4315 个交易日；60／90／120 分钟 17260／12945／8630 根 | 完整正式前缀均小于 20000 行；两数据集各小于 5000 日分区；不截旧历史 |
| 数值、键和版本 | 无重复、非有限必需值、端点／日期／两路键错位；参数键及版本符合现有合同 | 不把错误项过滤成无事件；按独立日历核对两路共同缺失 |
| 来源精度 | 日线 H 与 `2(D-A)` 最大差 0.002；分钟为零；最新日线／分钟 C 差 0.0001 | 源精度差异分别保留，不在算法加入 epsilon 或重算 H |
| 冻结来源对照 | 保存的 3161 根分钟都在正式 Gold 中；C 差为零，D/H 差小于 `1e-8`；两份日线 251 行四个读数均相等 | 原冻结回归仍从原起点开始，正式更长前缀另做连续基线 |
| 现有接口 | 实际 GET 7 次均 HTTP 200；21 行 C/DIF/DEA/H、时间和版本逐项匹配 | 原接口可信；新 XXM API 和盘中完成柱边界尚未验收 |
| 原读取预算 | 60 分钟 reader 每次 1000 行，4.028 秒时 bars 仅 7000 行、指标仅 6000 行，均未读完 | §4.2 分页方式与 §6 的 4 秒预算冲突，按根 AGENTS 先确认调整，未编码 |
| 单次扫描可行性 | 临时复用现有路径／schema／行校验，两路完整读取 60／90／120 分钟约 2.325／2.088／1.945 秒 | 只是读取可行性，非新接口 P95；算法、缓存及 HTTP 开销待验证 |

**用户已确认的调整（本次回复，同意调整读取方式并继续实现）：** 给 XXM 增加有界完整历史读取入口，一次组织每个数据集的前缀扫描，再按 1000 根推进内核。复用现有路径、schema 和数据校验，严格核对两路时间集合及 SSE 日历；保持 20000 行、每数据集／周期 5000 日分区的上限及 4 秒完整请求预算。原公开分页方法、cursor 和现有消费者不迁移、不改变行为。不得写湖、增正式状态资产／持久缓存、截取暖机窗口或调算法参数。§3／§4／§6 及配置审计已同步，再编码；性能未达标仍停止并复审。

本轮 CodeGraph `codegraph_explore` 覆盖日线 query、分钟 reader 及依赖注入，`codegraph_impact(MajorIndexMinsLakeReader)` 覆盖现有分钟 query service 和 reader 测试。新增来源入口不会改变子系统方向；其消费者审计及四类 chart adapter 的完整回归在对应实施阶段完成。

实施约束：新增读取能力位于 `src/foundation/clients/local_lake/major_index_mins_reader.py`，仅被 XXM 历史加载器消费，物理行数上限在该 reader 定义并由运行预算引用。原公共分页方法及消费链不改变；原报告 §12 的超预算测量保留为调整依据，不写成调整后验收成绩。


## 13 实施与技术验收（2026-10-13）

用户批准完整历史读取调整后，所有新代码在原 dev-interface 工作区实现。分钟每路组织一次完整扫描，再以 1000 根作为计算检查批次；路径、schema、身份／日期／频度／版本、重复键、两路时间集合及 SSE 日历检查保留。文件共同祖先只验证一次，每个文件和日期目录仍逐项检查符号链接；原公共分页、cursor 及其他消费者保持原行为。新完整扫描仅用其单独的 512MB／2 线程连接设置。

API 采用 Biz router factory，由 App 注入 Session、既有鉴权、异常工厂及本地 Lake 来源；Biz 不新增对 App 的 import。新增 DTO 只有本专项消费者。共享图表仅新增可选 macdPrimitives 并挂到 DIF series，图层数据更新不触发图表重建；四类指数／股票 adapter 均已回归。新图层状态区显式接收鼠标事件，解决原标题栏 pointer-events:none 导致重试点不到的问题。

用户已批准仅指数详情页的 1280／1440px 修正：body 的 token 覆盖仅在该页存在时生效，页内三层 grid 用 minmax(0,1fr) 防止旧 canvas 宽度撑住布局。实测 body 在 1280／1440px 不横向滚动，图表坐标轴完整；离开到市场总览后恢复 1460px。保留现有 1320px 以下右栏 344px 规则及自适应坐标轴宽度，设计中的 56px 是原最小轴宽，当前宽标签可能增至 66px。

[实施与验收报告](/Users/congming/github/goldenshare/reports/xxm/conclusions/xxm_implementation_20261013/README.md)保存连续基线、API 响应、软件读数、P95 明细、页面截图、逐项对账及文件哈希。当前结果：

| 门禁 | 实现与验证 |
| --- | --- |
| I1/W1/A1～A3 | spec/types/calculator；最近价前置、原始两段池、最强合格峰／并列、锁定、独立极值、零柱及异色分段正反例；冻结三组门槛逐柱回归 |
| T1/T2/F1 | 严格比例门槛／零分母／镜像、有效状态资格、目标突破优先、直接反色事件后状态 NONE；恰达／等价／微小变化负例 |
| H1～H5/O1 | 历史创建峰、跨段保留、竞争截尾、价格严格突破、同柱底部事件、无到期及 snapshot/restore；已保留所有事件和结束原因 |
| 连续来源及 S1～S4 | 日线 912 根、60／90／120 分钟 17260／12945／8630 根；2615 个事件及生命周期变化前缀独立重放，15 处前缀／恢复检查；过去窗口不泄漏未来状态，源修订作废缓存 |
| A1/A2 | 真实 FastAPI 路由／SQL／两路 Parquet reader 集成；参数与鉴权、完成柱、空源、无事件、共同缺口、超预算等正反例；真实 API 窗口 1800 个逐柱对象、事件和关联历史与同源离线内核逐字段相等 |
| U1/U2 | 真实四周期页面；2025-03-14 90 分钟 11:00 同柱底结构＋顶结构消失，普通状态为 NONE，两份事件参照及结束记录完整；120 分钟原紫色结构与后续绿色消失同屏保留 |
| U3/U4 | 缩放、拖动、切换、离开、异步 primitive 更新；真实 API 503 时保留 28 个画布／四窗格，按钮重试恢复；30 分钟无 XXM 图层／请求；两类股票 adapter 回归无新图层 |
| V1 | 26 个分钟、1 个日线末端对账；不可读柱值留空，不反推；正式源保留原精度，不用固定偏移或调门槛消除差异 |
| P1 | 四周期各 20 冷＋20 暖真实 HTTP 样本，nearest-rank P95；冷缓存 0.46／2.58／2.18／1.99s，已预热缓存 0.52／0.68／0.72／0.69s；冷组最大 3.05s，低于 4s 硬预算。暖组第一条可能实际填充缓存，已在报告注明 |
| 架构与原消费链 | CodeGraph 开发前 status/search/explore/impact，开发后 CLI sync/status/impact；手工审计真实四个 adapter 弥补索引间接调用不全；边界测试及原指数 API／reader 回归通过，无依赖矩阵变更 |

后端及边界回归 86 项通过；Wealth 16 个测试文件共 98 项通过，typecheck/build 通过。Vite 仍报告约 1.44MB 主 chunk 的体积提示，没有为本专项安装依赖。完整命令、各类证据及限制见实施报告。

未关闭的是 M3 用户验收、V2 新视频独立验证与生产发布。原软件公式、60／90 分钟数值差异、日线事件完整软件时间线、底部镜像和长历史寿命仍未确认。应用加 DuckDB 的单进程实测峰值约 1.17GiB；512MB 是 DuckDB 管理内存设置，64MiB 是查询缓存对象预算，不能宣称进程 RSS 不超过它们。上线前需在目标环境复测并发与资源，不在本轮开放生产分钟或部署。

## 14 关键高低点预测扩展（已确认修订；技术验收通过，页面待用户验收）

[预测技术方案与 LLD](./index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md)是此扩展的唯一详细设计入口。范围继续为上证日线及60／90／120分钟、每周期一个最近候选时点、技术面底部文字、真实新收盘后重算，评分后置。预测复用本文件的来源及原内核独立副本；不向活动参照、真实事件账本或图层塞入假设结果。

### 14.1 旧版开工与实现（历史记录）

用户曾确认 Figma 并授权补齐五项审计问题后实现。来源／未来日历和单参考路径预检见 M0报告（原记录：`reports/xxm_forecast_precheck_20261014/README.md`），预测后端／文字区及真实接口验证见 旧版报告（原记录：`reports/xxm_forecast_implementation_20261014/README.md`）。原识别规则及接口未改变。用户明确改为自行页面验收，助手不再启动新自动验收服务或索取登录密钥配置。

该版会选一个参考收盘价，固定中间走势再求目标价格范围。用户查看页面后指出，这不能完整说明“哪些收盘价会钝化、不同前置价如何改变后续条件”。旧版技术验收不证明完整价格范围和关联关系已经实现，也不算本次需求验收通过。

### 14.2 本次修订的 LLD 边界（已落码，技术验收通过）

详细计算、合同、符号和门禁在[预测方案 §15](./index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md#15-本轮冻结的预测-lld2026-10-14)，以下只声明与原识别层的接口关系：

| 事项 | 预测扩展的约束 |
| --- | --- |
| 钝化触发范围 | 从真实状态投影下一根的全部正有限收盘价；原 step 的 DULL/activation 事件决定合格范围和实际参照，不能只试两个参考价 |
| 不同前置价 | 每个有效前置收盘 P 独立递推 EMA、指标及状态；目标收盘 C 的条件必须与 P 关联，不复制同一范围给其他 P |
| 原识别语义 | 两段历史池、最强合格参照、独立极值、最少两根、1%转向及反色规则沿用；钝化后不再要求每根价格创新极值 |
| 失效优先级 | DIF 参照突破先取消；零柱清空当前候选；直接反色形成结构时按事件保留，不能误说成全部失效 |
| 最近单时点 | 完整范围上先证明更早无解，返回唯一目标及它适用的前置子范围；精度疑义不能跳更远 |
| 合同隔离 | 预测响应已迁移v0.2，DTO/query/text与全部前端消费者同时迁移，移除旧scenarios口径；原识别API、图层、事件／历史合同不迁移 |
| 文案 | “出现钝化的收盘范围”“形成结构的收盘条件”“不成立／消失／重算”；充分条件取全域交集，无统一范围则用明确标注的逐项例子 |
| 精度／预算 | 同源校准、日线中点疑义及保守显示继续；新关联求解重新预检200ms新增/4s总/32KiB，不用旧性能成绩替代 |
| 验收 | 日线及60/90/120各自验收范围、关联、失效、边界、真实API和新行情重算；页面由用户手动，评分另行设计 |

用户已确认；R1预检与原Figma文字同步后已迁移新模型/合同/页面。正式接口曾因60分钟来源超过4s暂停，用户已批准优化；同次metadata复用及原1000根批次真实状态缓存已实现，152项回归及最终四周期160次冷暖/18次两并发预算通过。门禁与当前证据见本轮实施记录（原记录：`reports/xxm_forecast_range_implementation_20261014/README.md`），最终成绩来自产品代码及完整接口门禁，页面仍待用户手动验收。依赖仍为App→Biz→Foundation，Wealth经HTTP；不新增反向依赖、读取链、配置来源、正式预测表或源指标补偿。原生产分钟、数据只读及发布授权边界继续有效。

### 14.3 近期简明文案与展示筛选LLD（2026-10-15）

唯一详细规则入口为[预测方案§18](./index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md#18-近期关键条件的简明展示2026-10-15)。日线及60／90／120分钟都采用“触发、未触发、推算失效、结构成立”，正文用实际日期和分钟收盘时间；过远的背离边界及备选路线可省略，相邻未触发区间、MACD变色／零柱及已钝化后的取消规则强制保留。3457点省略不意味着3951点也省略。

近期范围由同周期、同结束时刻、同目标跨度的最近60个真实历史变化的绝对幅度95分位生成；参数已确认，只用于展示，不是未来概率或评分。日线以开市日、分钟以原ENDPOINTS计数；历史回放只用截至asOf的样本。统计复用原load_entry的完整bars，不新建读取链、不增数据库／Lake写入。完整数学有效域、最近时点和原严格比较保持，不能将省略后的单边文字变成无界触发条件。

改动落点仅为ForecastSpec内部展示策略参数、IndexDetailXxmForecastQueryService给文本的同源上下文、forecast_text的选择和中文模板、对应测试；Card继续消费后端display并使用Figma新页脚。v0.2结构化范围／关联／例子和HTTP合同不删改，不需要前端计算或新的公共配置。正文整数结构区间必须向内收缩，窄区间回退2／4位；局部适用域必须注明实际日期和价格范围，不能因其覆盖近期波动带就概括为全部激活价；无可靠价格不写确定判断。正文去掉三个示例、重复范围和临界提示。

门禁在预测方案§18.7，最新执行证据见本轮实施记录（原记录：`reports/xxm_forecast_display_implementation_20261015/README.md`）：四周期因果样本、隐藏下界仍失效、保护条件、跨参照／精度空隙、状态区别、原数据和数学结果不变、真实API及200ms／4s／32KiB预算均单独核验。历史或候选成绩不替代最终产品代码的成绩；页面仍由用户验收。本次不改变原识别Spec、历史结构生命周期、分层或依赖矩阵。

### 14.4 统一业务日期接入修正（2026-10-15）

本轮唯一规则和验收矩阵见[预测方案§19](./index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md#19-统一业务日期与20点切换修正2026-10-15)。预测与原XXM图层共用load_entry，因此共同迁移取数、签名、计算前缀与滞后判定；20点前已有昨天数据应正常计算，20点后缺今天完整源才滞后，不保留另一套盘中门禁或静默降级结果。

复用MarketPageContextQuery，不复制20点规则；仅增加内部可选now供同请求时钟注入，默认既有调用方行为不变。load_entry的第二返回项为共享MarketPageContext，两个正式build同步迁移；asOf历史回放仍受业务日上限约束。原公开DTO／HTTP码、算法参数、读取分页、缓存预算和前端四行不改，无新增配置。

本轮实施已完成：相关后端301项、前端57项及类型检查／构建通过；48次真实日期边界验证四周期20点前READY／20点后缺当前源才DELAYED，178次预算＋4次最新请求通过，最慢3.296秒、计算最大79.94毫秒、最大10779B。12份固定快照完整响应与前版一致，既有20个导入文件／26处context调用保持，CodeGraph已同步。真实源未发布10/15的完整源，完整发布正例及未来数据反例使用隔离源验证；证据见本轮报告（原记录：`reports/xxm_business_date_alignment_20261015/README.md`）。页面仍由用户手动验收，未提交、推送、部署、安装、重启用户服务或写正式数据。

### 14.5 整页调度与共享加载LLD（2026-10-15，已授权）

唯一详细设计、参数审计和硬门禁见[预测方案§20](./index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md#20-整页请求调度与共享加载2026-10-15已授权实施)。本轮只做其两项，不进入发布后预计算／持久化快照。日线和60／90／120均覆盖，算法、正式Reader校验、Spec、业务日期、DTO及Figma保持。

前端新增指数详情专用调度模块，五类消费者统一接入：两个分钟client、页面指数九转loader、XXM识别及预测。最多2个轻请求，全历史任务独占；按图表、九转、识别、预测顺序，同级FIFO。排队可取消，5秒网络等待只从实际发送起计，JSON／adapter结束后释放名额；预测hook移除局部配额但保留周期去重、原轮询、隐藏／焦点／重试规则。股票共享hook和wealthFetch不改，无新视觉或公开参数。

后端原XxmCache拥有进行中加载协调；同bind／Lake／周期／Spec／业务日／日历截至／完成端点只执行一次真实加载，等待者不占2个源名额且保留各自4秒截止。源工作结束就释放名额，yield后只读共享entry；追加／修订使用copy-on-write，不修改其他请求持有的entry。独立请求仍查两路完整signature或日线实际值；源、完成上限和开市日历全相同才跳过已完成的连续性和内存遍历，变化则原完整校验／重建。失败不发布、不缓存成功替代。

预测完整DTO按前缀指纹、未来日历、Spec、expected与asOf复用，命中前仍核验当前来源与日历，深拷贝返回。同一个64MiB／16项LRU管理源和响应，进行中也复用16项上限；无TTL、后台任务、数据库、文件产物或新配置。原4s／200ms／32KiB和全部源范围不变。

编码前门禁R1～R7已映射真实client／load_entry／cache／forecast与测试，继承§10全部适用清单，不新增例外；必须补整页混合和双标签页使用实际JS调度器的技术验收。UI排队时间另计，不能宣称整页4秒完成；页面最终由用户验收。若发现范围内无法达标，先保留证据并按根规则确认，不自行进入下一项快照建设。

执行结果：317项相关后端、165文件／1172项前端全量、类型检查及构建通过；四周期单／双标签页冷暖16组306个真实HTTP全成功且≤4秒，预测最大2.519秒，96份响应与原同快照全字段相同。后续原160次冷暖和前8组／16次并发通过，但末组90分钟build4.0095秒、HTTP4.0541秒503，未进入模型；后4次最新未执行。只读诊断6次均2.78～3.88秒，不能抵消正式失败。原代码／阈值未因失败而修改；详见[方案§20.5](./index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md#205-实施结果与未通过的预算门禁)及报告（原记录：`reports/xxm_request_reuse_20261015/README.md`）。两项代码保留，当前等待是否扩到读取层确认，不能称全部完成。


### 14.6 读取层扩围（用户已批准，先只读预检）

详细约束与代码／测试门禁统一见[预测方案§20.6](./index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md#206-已批准的读取层扩围及预检门禁)，覆盖上节末尾“等待确认”状态。Foundation Reader预检等价SQL组织，减少非目标指数的中间表物化，仍扫描并检查所有文件行；公开分页、完整历史、完整字段及所有错误拒绝条件保持。原两路签名／时间键／连续性、20000行和5000文件上限、4秒与DuckDB512MB／2线程不动，无新配置。候选先通过三周期完整数据／非目标错误反例／HTTP预算，再修改唯一正式读取实现，最后重跑四周期及混合／双标签页门禁。保留§20.5原失败与候选证据，不用成功诊断抵消正式失败；页面由用户验收。


预检进一步限定为内部字段投影：完整历史read增加默认None的value_columns，自动保留四键，仅允许原数据集输出字段，非法或重复列拒绝。source两次读取显式只要close／macd_dif、macd_dea、macd；全文件schema和合同谓词、重复键、全历史行数与source对齐不改。公开分页及默认完整历史仍返回全部原字段，不另建Reader或兼容支路。该参数不持久化、不对用户开放，来源是source静态消费字段；测试与四周期预算见方案§20.6。


字段投影单独候选未通过全部HTTP预算，正式代码仍不改；继续预检配对读取。拟新增Foundation内部完整历史pair入口，在2个worker中各用256MB／1线程，与单路原512MB／2线程总额相同，源请求名额仍2。两路以同一开始时间扣除实际排队，读取Timer／finally、bars错误优先次序和两路清理均保持，source取pair后仍做原完整时间键、MACD有限性及连续性检查。单路公开分页与默认历史行为保持。配置策略审计和反例统一落方案§20.6；候选达标后才迁移唯一实现。


读取扩围最终已实现并验收，当前状态覆盖上文预检阶段。唯一校验实现收敛在Reader `_read_complete_history`，原单路方法与配对方法共享它；source使用配对＋close／三MACD投影，原SQL合同谓词与全键对齐不变。相关后端385项、三周期4316分区全历史对照、正式178＋4接口预算及306次混合／双标签页全部通过。最终HTTP最大2.976秒，混合计算最大136.72ms，96份完整响应与原版相等；配对只重新分配原DuckDB512MB／2线程总额。代码、参数、正反例与R1～R7逐条对账见[预测方案§20.7](./index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md#207-最终产品实施与计划对账)及报告（原记录：`reports/xxm_request_reuse_20261015/README.md`），历史失败保留。依赖矩阵、公开HTTP／DTO、算法、Figma及页面验收安排保持，未提交或部署。

## 15 底部同段结构消失与重新钝化LLD（2026-10-15，待确认，未实现）

2026-10-16预检更新：本节“下一根起重入”的组合已在§20.1发现8/22日线反例；这是早期草案，不可直接编码。用户辨认后的当根资格分流及新预检结果见§20.2，h1实现保持。

本节保留A组早期草案。最新建议先实施B组，完整定义见§16；确认§16不代表同时批准本节的新等待记录、同段循环或预测字段。

### 15.1 依据、范围和当前影响面

规则唯一入口为[算法方案§12](/Users/congming/github/goldenshare/docs/product/xxm-direction-algorithm-plan-v0.1.md)。7/10当日讲解确认120分钟结构消失后还没有新钝化，3959后才重出。本节设计实现这一状态关系，1%仍为工作候选。日线及60／90／120分钟共用内核、分别保存状态；不补跨柱色底部历史价格撤销，不凭本例改顶部循环或过滤9/24／25。

已使用CodeGraph `codegraph_explore`、`codegraph_impact(XxmCalculator, depth=2)`和`codegraph_callers`。impact返回64个相关符号，覆盖内核、查询／SeriesEntry、预测和回归；callers未解析出构造调用，不能据此认定无消费者。补读当前代码核验如下；历史报告脚本不是产品依赖。

| 当前实现／消费者 | 现有行为 | 本轮迁移 |
| --- | --- | --- |
| `calculator.py`／`types.py`／`spec.py` | 底部反向直接DULL，快照无等待参照 | 新结构消失事件、等待记录、当根重入、恢复和版本 |
| `queries/.../xxm/query_service.py` | 保存point／event／顶部history，按前缀恢复和裁窗口 | 保存新记录账本；as-of投影和窗口外原结构关联，禁止未来状态回填 |
| `forecast.py`／`forecast_entry.py`／`forecast_detector.py`／`forecast_joint.py` | NONE首次选峰，DULL直接算结构，边界证明含累计极值 | 新等待情景固定参照；价格切点、重入签名及精度证明同步，不只改最外层分支 |
| `forecast_query_service.py`／`forecast_text.py` | 从真实状态判已确认／条件结果和失效文字 | 当前有效结构判定、等待先激活再确认、失效后重算 |
| 两XXM schema、两类API及Wealth client／types／adapter | 固定版本、extra-forbid、枚举白名单 | 同轮迁移新版本、事件及关联校验；URL／请求参数／鉴权／分钟门禁不改 |
| 指数日线／分钟adapter、`useIndexXxmLayer`、primitive、`XxmLayerUi` | 共用真实图层和详情 | 新绿色事件及原结构关联；等待不能画成钝化，不改既有点大小／字重／布局 |
| `XxmForecastCard`、预测adapter／types／`useXxmForecast` | 消费后端display和条件域 | 新上下文和等待说明，页面不自行计算3959或重选参照 |
| 研究回放与Python／TS测试及fixture | 冻结旧事件、显式版本和类型 | 保留旧证据，另产新版逐事件差异，不能覆盖旧基线掩盖变动 |

仍为App装配Biz、Biz只读Foundation、Wealth经HTTP消费；无Foundation改动、正式数据写入或依赖矩阵变化。只迁移唯一内核及全部消费者，不新增兼容引擎和两套在线结果。

### 15.2 每根柱的执行顺序

1. 沿用输入校验，确定柱色，更新真实段极值。已有等待记录遇红柱／零柱先结束并留原因；没有有效DULL时不因此补CANCEL。原活动DULL的变色确认／取消次序保留。
2. 同负柱段有活动参照时先检查原DIF严格突破，满足则原规则取消。否则底部STRUCTURE的反向达到暂定门槛，输出 `STRUCTURE_DISAPPEARED / dif_return`，状态NONE、活动参照为空，并创建等待记录；本根结束普通事件判断。
3. 同负柱段有等待记录时，先检查保存参照被DIF严格突破，突破则结束且本根不重选。否则同时检查：当前柱晚于消失柱、当前收盘严格低于保存参照价格及最近价格门槛、段最低DIF严格高于参照、段柱数满足原要求。满足才报 `DULL / reactivation`、恢复活动参照并结束记录；不满足继续等待。
4. 无等待记录才沿用首次激活及其他既有规则；顶部原普通和历史跟踪独立执行。每根最多一个普通事件，独立顶部历史事件仍可共存；重新激活当根不再确认结构。

原段低点仍是真实累计事实，不人为切成新段，但它不能代替步骤3的当根收盘。等待记录固定原参照，不重新执行最强两段选择；记录结束后才按真实新状态重新选参照，不在同一预测关系里静默换峰。

### 15.3 内部记录、拟议DTO与恢复

保持 `ordinaryState=NONE/DULL/STRUCTURE`。等待时NONE、ordinaryDirection及activeReference均为空，新增pendingRearmId指向另存记录；不放宽NONE的活动参照不变量，也不误写DULL。

| 对象／字段 | 拟议定义及约束 |
| --- | --- |
| `RearmRecord.id` | 新Spec、对象、周期、原结构事件ID和消失时间组成稳定身份，每周期最多一个WAITING |
| `direction/structureEventId/structureConfirmedAt/structureRoute` | 本轮direction仅BOTTOM；保留原紫色结构身份，事件账本不删 |
| `reference/nearestPriceGate/segmentStart` | 原参照价格／DIF／起止时间、原最近价格门槛、当前负柱段起点，均深拷贝 |
| `disappearedAt/observedThrough` | 消失晚于结构确认，观察时间不晚于请求端点 |
| `status/endedAt/endReason` | WAITING后两项为空；REACTIVATED、INVALIDATED、SEGMENT_ENDED分别因price_requalified、reference_dif_break、color_flip／zero结束并留时间 |
| `XxmPoint.pendingRearmId` | 新增必有可空字段，仅NONE时允许非空，其他状态为空；不能与活动参照并存 |
| `XxmEvent` | 增加type STRUCTURE_DISAPPEARED、route reactivation及可空relatedRearmId；结构消失仍用dif_return，DULL以activation／reactivation区分；未关联事件字段为空 |
| `XxmStep.rearmRecords`／响应 `rearmRecords` | 返回记录变化或当前观察副本，查询返回窗口相关记录集合；避免逐根重复完整参照，无记录为空数组 |
| snapshot | 新增当前有效结构事件ID及唯一等待记录；已结束记录由调用方账本保存，不常驻内核；restore验证新版Spec、来源、对象和周期 |

记录自带原结构时间／身份及参照，因此原结构在显示窗口之外也可核对，无需页面猜日期。事件relatedRearmId必须解析到返回集合；对应结构也在窗口时交叉核验。结构消失只能由BOTTOM的STRUCTURE创建记录；重入只能由NONE＋有效记录产生并结束它；不接受TOP等待记录，不将其塞进顶部专用relatedTopHistoryId。

SeriesEntry的新账本与point／event／topHistories共用原64MiB／16项LRU。`_response`按请求endDate投影：当时未结束必须WAITING；窗口前创建但窗口内有效、结束或被事件引用的记录仍需返回，不从最终记录泄漏未来。原顶部history继续表达另一种独立语义，不与等待记录混同。

### 15.4 技术面预测与文案

预测响应拟增 `rearmContext: RearmRecord | null`，只允许携带截至真实端点WAITING的记录。NONE＋该记录走固定参照的条件激活。`solve_entry_ranges/entry_partition/stable_reference_on_band/reason_for/activation_signature`均须区分首次和重入：重入切点来自保存参照价格与nearestPriceGate，采用候选当根收盘，签名接受reactivation；不能复用首次“累计低点已经满足”的证明。

未来P若造成参照DIF突破、红柱或零柱，旧情景终止，不在同一关系中换峰。P重入后用独立副本求后续C，保持原目标确认数学及中间DULL存续约束。完整激活范围分区必须包含触发、未触发和失效，日线取整保护及分钟全精度不变，不能用有限价格抽样证明完整域。

| 真实状态 | 合法预测结果 |
| --- | --- |
| 当前结构仍有效 | CONFIRMED，身份必须属于当前有效结构，不能只向后找到任意历史STRUCTURE |
| NONE＋WAITING | 有激活及结构解为CONDITIONAL_ENTRY；仅激活解为ENTRY_ONLY；无激活解为NO_CANDIDATE；禁止DULL专用READY |
| 新DULL已被实际行情触发 | READY，rearmContext为空，不再要求用户重复满足已经实现的触发条件 |
| 记录结束／新段 | 不带旧context，按首次路径重算，不复用旧3959条件 |
| 数据／精度／预算不满足 | 原DELAYED／EMPTY／PRECISION_PENDING或明确错误，不能用NONE掩盖失败 |

重新激活与结构至少相隔一根完成柱，只给最近一个有解结构时点。两个schema及前端保持原status集合，新增上下文组合校验：CONDITIONAL_ENTRY内参照必须等于WAITING参照；context不出现在READY、CONFIRMED或来源未就绪结果。无结构解时不生成结构日期或确认价。

后端display示意：“原底部结构已消失。后续收盘满足所列范围，可重新钝化；随后满足条件，可形成新结构。”价格和日期从解域及既有向内格式化生成，不硬编码3959。继续展示近期未触发和失效，远端边界按原95分位筛选；旧结构消失与新钝化失效分别表达。图上新事件沿用绿色消失，详情明确底部结构消失，等待不画黄色点；不改Figma、版式或评分。预测原方案同步见其§21。

### 15.5 版本、配置审计与一次迁移

| 既有字段／拟值 | 唯一来源、消费者 | 生效和测试门禁 |
| --- | --- | --- |
| algorithm_version：xxm-direction-v0.1-r1 | 原spec.py不可变Spec；内核ID、cache、snapshot、schema／adapter、回放 | 用户确认后随代码生效；新hash作废旧缓存，旧snapshot拒绝续接 |
| forecast_version：xxm-key-point-forecast-v0.2-r1 | 原forecast_spec.py；预测cache、schema、client adapter | 与内核同轮切换，旧响应不能混入新消费者 |
| dif_turn_pct：1%；0.75%／1.2%离线 | 原XxmSpec；原确认／顶部再钝化、本轮底部消失候选及预测 | 无新增数值门槛、env／Settings／数据库或页面开关；软件真值未知，见算法方案§12.6 |
| 原运行／精度／展示预算 | BUDGET、FORECAST_SPEC及原调度器 | 4s总请求、200ms模型、32KiB预测／1MiB识别响应、64MiB缓存及完整校验均保持 |

实施方和消费者清单：types／calculator／snapshot；SeriesEntry、识别／预测query；两个schema和API实际响应；forecast入口／entry／detector／joint／text；两组Wealth client／types／adapter／hook及fixture；XxmLayerUi／primitive／ForecastCard；四周期实际入口及Python／TS回归。URL、参数和鉴权保持，新语义和响应一次迁移，extra-forbid和枚举白名单继续严格。不得保留底部旧dif_return报DULL支路或两套在线结果；顶部原语义不是底部兼容支路。

### 15.6 硬口径—实现—验收矩阵

以下是后续门禁，**本轮未执行新模型、产品测试或预算验收**。

| ID／硬口径 | 落点 | 正向与反例 |
| --- | --- | --- |
| S1 消失与重入分离 | calculator／event DTO／adapter | 7/10完整8508根：保留原结构、新绿色、NONE＋等待；不得新报DULL或CANCEL |
| S2 原参照＋当根价格 | calculator／snapshot | 3959.16软件重入正样本、3960模型等待反例；旧3952最低收盘不能使3996激活，7/13须输出新的重入事件；新收盘不必再低于原最低收盘，OHLC依赖仍待核 |
| S3 严格边界及次序 | calculator／entry | 价格等于参照不重入；DIF等号不激活、严格突破结束；前根DIF为0不制造比例；消失同柱不重入 |
| S4 释放不伪造取消 | RearmRecord／schema | 红柱、零柱、DIF突破均结束并留原因；没有有效DULL不得补CANCEL，不跨段恢复旧记录 |
| S5 预测共用真实内核 | 全部forecast分支及两schema | 等待不得READY；边界内外、P—C、精度／无解／仅激活独立重放；不换成首次选峰或累计价门槛 |
| S6 四周期与统一日期 | source原合同／calendar／query | day/m60/m90/m120全测；20点前后、周末、跨日／午休端点；其他周期合成结果不当软件观察 |
| S7 因果与恢复 | calculator_at／_response／cache | 消失前、等待中、重入后三个断点与完整前缀相等；过去asOf、后缀扰动、来源／Spec变化，无未来状态回填 |
| S8 合同关联完整 | 两DTO／两adapter／详情 | 窗口外结构可核对；悬空ID、错误方向、旧版本、NONE带活动参照、DULL带pendingRearm均拒绝；图与文字一致 |
| S9 冻结与缺陷对账 | 研究／API／Wealth回归 | 保留旧输入及52标签，解释新版底部差异；顶部和首次激活语义不变；原三漏及两疑点不能报已解决 |
| S10 性能与整页负载 | 原runtime／cache／scheduler／真实API | 四周期各20冷＋20暖、两并发、整页混合及双标签页；4s含后端排队／读源／计算、模型≤200ms；完整校验、响应／内存上限和共享加载保持 |

测试落点为研究目录的 `test_xxm_calculator.py/test_xxm_key_point_forecast.py/test_xxm_forecast_display.py`、`tests/web/test_wealth_index_detail_xxm_api.py/test_wealth_index_detail_xxm_forecast_api.py/test_xxm_shared_loads.py`及Wealth两组adapter／hook／图层／预测回归和typecheck／build。首次激活的旧累计低点测试仍有效，不能为新增重入规则删除；ID随版本变化时按关联语义对账，不要求旧ID字节相同。

### 15.7 先评审，再预检和实现

本轮只交文档，等待用户确认候选范围、暂定门槛和同柱次序。确认后先只读预检S1—S7及四周期预算，通过后才修改唯一内核及全部合同消费者，再完成S1—S10产品验收。冲突按根规则反馈，不删历史、跳校验或放宽预算；页面由用户自行验收，不要求重新配置登录服务。

原2024-07-23／08-05／08-22跨柱色底部消失仍是独立未解决缺口，2024-09-24／25仍是疑似多报。其公式明确后再修订范围；本轮技术通过也不等于全软件一致，不安装、部署或写正式数据。

8/5当日新材料进一步确认不能混同两层：7/31结构后有8/1、8/2红柱，8/5首根绿柱尚无新钝化，图中却有绿色消失；作者纠正交易标准为钝化消失，并说尚未出现。当前清空普通参照后没有底部旧结构后续记录，§15同段等待候选仍不覆盖此例；不能把等待记录跨红柱复用来替代历史设计。当前385根历史前缀的投影校准被既有保护拒绝，未获取合法预测价格域，未放宽容差；8/6仅作独立事后源回放。证据及限定见8/5补证（原记录：`reports/xxm_software_indicator_crosscheck_20261015/case_20240805_semantics_20261015.md`）。这里只更新证据，不改变待审合同、规则或编码范围。

后续8/6原图及讲解已提供当日软件观察，日线／90／120分钟末端底钝化对应；120分钟还新增8/5下午绿色缺少输出的图证。DIF参照比较、日线旧参照移出范围均获定性说明，不能将近似口述当精确游标或两段选峰公式证明。真正钝化失效后须经红柱再绿柱两根的口述，新增为待核约束，不能直接套到同段结构消失；当前是否存在反例尚未完成审计，本节候选及合同仍待确认。下一份优先2024-09-02的120分钟，具体时点与冻结分歧见8/6核查及选材（原记录：`reports/xxm_software_indicator_crosscheck_20261015/case_20240806_semantics_and_next_nodes_20261015.md`）。

后续9/2、9/3补证（原记录：`reports/xxm_software_indicator_crosscheck_20261015/case_20240902_03_semantics_20261015.md`）取得两张日线，9/2无DULL、9/3新DULL；9/3讲稿明确90分钟钝化已消失、120分钟保持，当前回放分别为CANCEL/dif_break和DULL。分钟只有口述，不能把模型9/3 14:00或参照DIF写成软件精确真值；60无新软件证据。9/2开场概括不能代替120分钟上午旧结构的标签观察，原预登记11:30分歧仍待补图。原三处日线漏报仍未修复，本节结构消失候选、合同及预测分支不因日末状态相容而自动批准。

再补9/3的90分钟原图（原记录：`reports/xxm_software_indicator_crosscheck_20261015/case_20240903_m90_image_20261015.md`）后，8/30结构、9/2新钝化、9/3钝化消失三处已有图证，柱位映射与当前事件对应，27次几何检查稳定；软件精确参照和游标时刻仍未取得，当前DIF／DEA／柱值的小差异保留不拟合。原三漏、跨柱色结构消失公式及120分钟9/2上午分歧仍未解决，本节候选未因此获批，不再索取已补齐的90分钟图。

随后9/4的120分钟图及讲解（原记录：`reports/xxm_software_indicator_crosscheck_20261015/case_20240904_m120_semantics_20261015.md`）已补齐9/2上午，不再索取该区间。六次结构和9/4上午CANCEL对应，作者明确此前多次结构并无真正钝化失效；8/5及新增约8/14下午旧绿色仍无输出。9/2上午纯DIF解释未获预期绿色正支持，价格型两种解释及新DULL接替优先级仍是待核候选，不把静态未见当确定无事件；未新增历史合同或扩展§15范围。120分钟末端指标按显示精度一致；9/4日线2777口述门槛仅作外部观察，该历史前缀投影CALIBRATION_FAILED，不绕过保护，不声明预测价已复现。原三处日线漏报仍未修复。

2026-10-16补齐7/10模拟前后原图（原记录：`reports/xxm_software_indicator_crosscheck_20261015/case_20260710_simulation_pair_20261016.md`）：收3959.16的模拟柱确实在旧绿色之后新增黄色钝化。验收新增该正样本；3960仍只是模型反例，不能写成软件已验证不触发。模拟低3946.16也同时改变，收盘与OHLC依赖、严格边界仍待核；日期7/13为7/10创建的假设柱，不是真实后来行情。8508根前缀及原保护投影通过，候选谓词通过不等于本节新内核已实现。原三漏、1%门槛、同柱次序和跨柱色缺口未因此解决，合同及编码范围不变。

再补7/13五图及完整聊天讲稿（原记录：`reports/xxm_software_indicator_crosscheck_20261015/case_20260713_multi_period_simulations_20261016.md`）：日线／90／120分钟真实DULL对应；120分钟7/13重新激活仍被当前7/10提前DULL吞掉。新增验收样本为下一根120分钟3892.79应CANCEL、90分钟3944.79应保持DULL；分别绑定7/14 11:30／11:00，后一个不是取消样本。原投影均通过且结果对应，模型额外邻价只是反例探针；口述整数不作精确门槛，日线3966仅近似口述。失效价不作结构价，后续端点按真实中间收盘重算。讲稿少数“结构消失后还跟钝化消失”未给出无中介DULL的具体图序，S4继续是待审候选，不能将其说成已排除所有软件例外。原合同、范围及未修复状态保持。

### 15.8 本轮整理后的范围、证据与验收口径（2026-10-16）

本轮仅修文档。用户可以评审的实现范围为算法方案§12.8的A组，即本节同段底部循环与预测联动。原三处日线及8/5、约8/14的120分钟历史绿色缺项属于B组，尚未定义其完整触发、寿命或新DTO；C组的顶部疑报和来源数值问题分别核查。三组不能共用一个“问题已解决”状态，A组测试通过也不使B／C组通过。

| 涉及门禁 | 整理后的精确含义 |
| --- | --- |
| S1、S2：已观察的生命周期 | 7/10只有结构消失、没有新钝化；模拟3959.16新增钝化；7/13实盘有新钝化。必须核对新事件及关联，不能只比较末端DULL |
| S2、S3：候选输入与门槛 | 当根收盘、严格比较和1%是明确工作假设，不是软件公式真值。若后来证实最低价／最高价参与，需回到输入合同和全部消费者评审，不在现有close-only类型中偷偷增加判定 |
| S3、S4：次序与少数例外 | 每根一个普通事件、无有效DULL不补CANCEL维持待审处理；7/13“极少”描述尚无具体例外，不能将测试通过写成原软件绝无双事件 |
| S5：边界和已观察模拟 | 原120分钟模型分界3893.7212，模拟3892.79取消；90分钟模型分界3943.8887，模拟3944.79保持。两个原图步长均为1，已观察结果相容，不将模拟输入与数学根直接相减当算法误差，不要求补特定邻价图 |
| S6：四周期事实与实现验证分开 | 日线及60／90／120全部验证同一候选；60分钟缺少新循环的软件材料仍标未观察。90分钟已有7/13实盘／模拟和9/3取消图文，不能继续写成这几项缺图，也不能因此声明全精度一致 |
| S9：原历史漏项 | 9/4的120分钟图经用户辨认：紫色结构与黄色钝化之间没有“消失”，绿色在最右、黄色右下方。只关闭可见位置歧义，不将静态无字当作永无历史事件，不补一条9/2上午旧绿色来拟合DIF规则 |
| S10：后续性能 | 仍是四周期200ms模型、4s请求、混合／双标签页门禁；本轮没有新计算或产品预算成绩，旧读取优化成绩不替代新内核验收 |

补充证据只维护在算法方案§12.8的R1—R5，不在LLD再另列一套日期。R1已由本轮用户回答关闭图中文字辨认；R2的7/23完整讲稿已取得，但未说明旧结构消失公式或寿命，不再重复索取同日讲稿；R3需要公式或有区分力的模拟而非普通截图，R4先任一天9/24／25日线，R5先由开发侧核已有来源。R2或R3若仍无法唯一确定规则，保留B组待研究及A组暂定参数，不新增模糊兜底或双引擎。

CodeGraph本轮使用`codegraph_explore`和`codegraph_impact(XxmCalculator, depth=2)`，后者覆盖64个内核、查询／恢复、预测与测试符号；预测schema和消费入口同步核对。当前代码、已有测试、图文原件与旧JSON分开记账，不改变依赖矩阵、配置、Figma、数据或已确认页面验收安排。文档完整性和保护文件核对不等于新算法或页面验收。

后续7/23讲稿补证只更新材料状态：1:49—2:12讨论后续可能新日线钝化，10:48—11:45讨论假如分钟失效而日线仍钝化，不能据此构造当天DULL／CANCEL验收。当前原内核完整源前缀376／15116／11337／7558根，末端分别NONE／NONE／NONE／DULL；没有新软件图，90分钟“钝化级别大”也不强转为末端软件状态。原三漏及本节待审合同均未因此改变，详见7/23核查（原记录：`reports/xxm_software_indicator_crosscheck_20261015/case_20240723_transcript_semantics_20261016.md`）。

用户随后明确只能从视频取材，并要求先逐项处理7/23。当前R4顶部取材暂停；7/23跨柱色历史跟踪的最小案例候选及逐根复核放在原专项记录§5，尚不构成本LLD的底部历史合同或编码授权。A组同段等待记录不得因此跨红柱复用；没有可区分证据时如实列假设，不要求用户操作原软件或继续找随机日期。

继续核查仅收窄B组约束：若7/23绿色关联7/9结构，历史上下文须跨过红柱并保留到第10根；不能将其转成固定TTL、新DTO或A组等待记录的跨段保留规则。价格破低、DIF反向及开始检查时机在此例仍有多种同日命中的组合，不能确定priceLow字段真值或照搬顶部谓词。完整已有历史中分钟候选出现分叉，共用结束策略也影响输出，需在未来B组方案中分别定义触发与结束、补独立反例，而不是本轮新增在线逻辑。同期本人公开材料未给公式；日线原预测校准失败单独保留，实际源指标回放不替代预测保护。详见7/23专项反例审查（原记录：`reports/xxm_software_indicator_crosscheck_20261015/case_20240723_counterexample_audit_20261016.md`）。无新预算验收或产品变更，原三漏仍未修复。

### 15.9 B组研究收敛后的实施限制（2026-10-16，待评审）

原V0.1§12.9新增工作修订，未增加正式字段、历史枚举或批准B组落码。42种预先固定的临时研究组合与已有五处正观察对照后，价格型三种解释均相容；仅DIF至少1%的一次性旧记录解释在120分钟8/2已先触发，不能再生成8/5那处正观察。原背离参照价格、确认收盘两种候选也无法同时对齐，原结构段最低收盘因而得到更多支持，但不等于已证明为软件唯一字段。

B组以后必须分别评审：旧结构身份／原段价格与当前普通参照；触发与结束优先级；快照恢复和过去时点；事件关联与预测所有消费者。旧历史仍在不得当DULL，历史消失不得伪造CANCEL或新DULL。A组等待记录仍在原段内释放，不因B组跨色历史而改变。附加DIF门槛、两种开始时机和E1／E2的区别继续待核；E3与9/2静态可见标签冲突的预测保留为争议，不宣称软件绝无该事件。

后续真实内核验收仍须覆盖日线及60／90／120、已有五处绿字及负证据、价格破低但DIF未回落的反例、同柱新信号接替、普通状态独立、完整前缀／恢复及原200ms／4秒混合负载。当前仅执行研究脚本，60／90无新增历史绿色软件真值。16组旧诊断、1008次诊断前缀检查及来源／保护哈希详见本轮专项（原记录：`reports/xxm_software_indicator_crosscheck_20261015/case_20240723_candidate_matrix_20261016.md`），不替代产品门禁。原三漏未修复，不新增配置或依赖边界。

<a id="16-跨柱色底部历史消失的推荐lld2026-10-16待确认未实现"></a>

## 16 跨柱色底部历史消失LLD（2026-10-16，工作规则已确认，未实现）

### 16.1 范围、依据和明确选择

规则唯一入口为[算法方案§12.10](/Users/congming/github/goldenshare/docs/product/xxm-direction-algorithm-plan-v0.1.md#1210-本次提交确认的主方案先补跨柱色底部历史消失2026-10-16未实现)。用户已确认先采用B组H1—S2—E1工作规则，当前仅完成只读预检：结构形成时锁定已知负柱段最低收盘，离开原段后才检查价格；原DIF突破、新底部信号优先结束，否则完成收盘严格破低记录一次历史消失，不加相对DIF转向门槛。五处既有绿色提供候选支持，不是唯一软件公式证明。

范围仅000001.SH的日线及60／90／120分钟。原普通事件、顶部历史规则和来源指标保持；不落地§15的A组dif_return修订、RearmRecord及rearmContext，不新增评分、历史消失价格预测、图层布局或参数开关。A组以后实施时须重新定义其消失如何关闭同一结构，不能让一份结构在A／B中重复消失。

### 16.2 当前影响面与迁移清单

本轮使用CodeGraph `codegraph_explore`、`codegraph_impact(XxmCalculator, depth=2)`，后者返回64个内核、恢复、预测及测试符号。另逐项核对真实schema、查询、Wealth字段引用和严格版本／枚举校验；CodeGraph模糊同名结果不作为消费者清单。

| 当前落点 | 必须迁移的内容 | 保持及反例 |
| --- | --- | --- |
| `services/.../index_detail_xxm/{types,calculator,spec}.py` | 底部历史状态、原段离开时间、step变化账本、snapshot／restore、新Spec身份 | 普通state／reference／两段池与原事件逐根相同；不引入另一个在线检测器 |
| `queries/.../index_detail_xxm/query_service.py` | SeriesEntry底部账本、完整／增量加载、检查点、_response按截至时点投影与窗口关联 | 不改源读取、共享加载、缓存总量及4秒计时；窗口外原结构不悬空 |
| `schemas/.../index_detail_xxm.py`、识别API | 下面§16.4的新增字段和历史方向关联校验 | URL／请求参数／鉴权保持，extra-forbid保持；底部不得塞入relatedTopHistoryId |
| `forecast_detector.py`、`forecast.py`及forecast查询／schema | 克隆恢复包含底部状态；检测器hash进入原缓存／响应；显式验证历史事件不冒充STRUCTURE | 不增状态或改范围数学、forecastVersion及forecastSpecHash；不得受“仍有历史记录”影响而输出CONFIRMED／READY |
| `wealth/.../xxm/{types,adapter,apiClient,useIndexXxmLayer}`及fixture／测试 | 新字段、底部关联、版本校验、EMPTY空集合、同柱事件和窗口详情 | 不放松旧校验，不从价格自行推算消失；顶部原字段不是底部别名 |
| `XxmMacdPrimitive.ts`、`XxmLayerUi.tsx` | 允许BOTTOM历史事件，绿色“消失”及底部历史详情；view model另存底部详情集合 | 保持已确认点大小、字重、左侧文字及布局；顶部和底部同柱事件独立；图上“消失”和详情“底部结构消失”分别映射，不能机械删首字产生“部结构消失” |
| `wealth/.../xxm-forecast/{types,adapter,useXxmForecast,XxmForecastCard}`及测试 | 核实检测器新hash与旧预测版本可消费，fixture同步身份 | 不新增预测字段、文案状态或等待逻辑；技术面内容按同源原版语义对照 |
| 研究回放、Python API／TS回归 | 保留原冻结账本和图文，产新版本差异及预算证据 | 普通／顶部差异不能以“版本变了”略过；未标记的候选输出不自动称误报 |

仍是Biz唯一内核、Biz只读Foundation、Wealth经HTTP消费，不改变依赖矩阵。本表合同设计已确认，尚未修改实现和全部消费者；本次研究不替代正式迁移验收。

### 16.3 内核每根柱的顺序

1. 原样执行输入校验及普通step；保留处理前原段和前一根数据。产生的普通事件及普通状态先固定，不因后面的B组历史判断改写。
2. 对已存在底部记录：若当前柱不再属于原负柱段，第一次登记`leftOriginAt`，之后不回退；零柱也是原段结束，但不单独结束历史记录。
3. 先检查当前DIF严格小于原DIF参照，满足则结束；否则若普通内核产生新的BOTTOM DULL／STRUCTURE（含当前dif_return类DULL），以新信号接替原因结束。两者均不追加历史消失事件。TOP新事件不是底部接替。
4. 若记录仍未结束、已有`leftOriginAt`、当前柱晚于确认柱，且完成收盘严格小于锁定低点，追加一次BOTTOM历史消失并结束。当前hist可以为正、零或新负柱；不额外检查DIF反向比例。原参照有效性已由步骤3约束。
5. 若本根普通事件是BOTTOM STRUCTURE，再为这个新结构创建记录。确认若在负柱段内，用截至当前的本段最低收盘；确认若由变色产生，用处理前的原负柱段最低收盘并登记本根为`leftOriginAt`。创建当根不再触发B组消失。
6. 原顶部历史处理独立，合并事件和历史变化后输出point。每周期至多一条待跟踪底部记录，无固定TTL；已结束记录由调用方账本保存，内核不积攒完整历史集合。

步骤3的优先级使9/2新DULL先接替，不同时追加旧绿；原普通CANCEL若存在仍只保留原事件，没有当前有效钝化时不补造CANCEL。原段内不运行步骤4，因此本轮不会改变7/10同段错误行为，这是明确保留的未修复项。

### 16.4 拟议记录与响应字段

本表为已确认、待实施的合同设计。顶部`topHistories/pendingTopHistoryId/relatedTopHistoryId`保持其原定义，新增底部字段表达另一方向的独立账本，不是兼容别名或两套结果。

| 对象／字段 | 定义与不变量 |
| --- | --- |
| `BottomHistory.id/structureEventId` | 新Spec、对象、周期及原结构事件形成稳定身份；结构事件账本保留，不靠前端倒找最近紫色 |
| `confirmedAt/confirmationRoute` | 原结构确认时点及dif_turn／color_flip；只能由BOTTOM STRUCTURE创建 |
| `originSegmentStart/leftOriginAt` | 原负柱段身份和第一次离开时点；未离开为null，离开后不重置。变色确认可等于confirmedAt |
| `priceLow/priceLowAt/originalReference` | 形成时已知的原段最低收盘、其时间及当时锁定DIF参照深拷贝；priceLowAt不晚于confirmedAt，后续不回写 |
| `status/endedAt/endReason` | PENDING时后两项null；ENDED后原因限定original_reference_break／new_bottom_DULL／new_bottom_STRUCTURE／historical_price_break |
| `observedThrough/ageBars` | 观察时点不超过请求截止，年龄按已完成柱计数；不是到期条件 |
| `XxmPoint.pendingBottomHistoryId` | 新增必有可空字段，指向截至本根仍PENDING的底部记录；可与独立顶部记录共存，不改变普通state不变量 |
| `XxmEvent.relatedBottomHistoryId` | 新增必有可空字段；BOTTOM结构和相应底部历史消失关联，其他不相关事件为null；单事件不得同时指向顶、底两份历史 |
| `RESEARCH_HISTORICAL_WITHDRAWAL` | 复用原历史事件type及historical_price_break route；原TOP必须关联topHistories，新BOTTOM必须关联bottomHistories；不能仅放宽direction而省关联校验 |
| `XxmStep.bottom_histories`／响应`bottomHistories` | 内核只交变化，查询交窗口相关记录；无记录为空数组。底部历史消失在图上仍标“消失”，详情标明“底部结构消失” |
| snapshot | 新增唯一`pendingBottomHistory`的独立深拷贝；restore校验Spec、来源、对象、周期、原段及时间次序；旧Spec快照不续接 |

当前事件type集合不增加A组的STRUCTURE_DISAPPEARED，本轮也不新增pendingRearmId、rearmRecords、rearmContext。普通源指标及历史池不从BottomHistory反推或重置。

**待审API新增字段示例。** 以下为7/23情景的字段片段，省略原有字段，不是完整响应；ID仅为示意，不是原软件ID或当前接口实测返回。

```json
{
  "points": [{"time": "2024-07-23", "pendingBottomHistoryId": null}],
  "events": [{
    "id": "333333333333333333333333", "time": "2024-07-23", "direction": "BOTTOM",
    "type": "RESEARCH_HISTORICAL_WITHDRAWAL", "route": "historical_price_break", "fromState": "NONE",
    "eventReference": {"startTime": "2024-05-23", "endTime": "2024-07-01", "price": 2945.8524, "dif": -35.168},
    "relatedTopHistoryId": null, "relatedBottomHistoryId": "111111111111111111111111"
  }],
  "bottomHistories": [{
    "id": "111111111111111111111111", "structureEventId": "222222222222222222222222",
    "confirmedAt": "2024-07-09", "confirmationRoute": "dif_turn",
    "originSegmentStart": "2024-07-05", "leftOriginAt": "2024-07-11",
    "priceLow": 2922.4498, "priceLowAt": "2024-07-08",
    "originalReference": {"startTime": "2024-05-23", "endTime": "2024-07-01", "price": 2945.8524, "dif": -35.168},
    "status": "ENDED", "endedAt": "2024-07-23", "endReason": "historical_price_break",
    "observedThrough": "2024-07-23", "ageBars": 10
  }]
}
```

7/22历史响应中的同一记录应为PENDING，结束信息为空；7/9响应还应隐藏未来leftOriginAt。原结构在窗口外时仍可由记录核对身份，不要求前端获得整个窗口外事件账本。

### 16.5 查询、过去时点与缓存

SeriesEntry为底部保存按ID索引的变化账本及检查点。`calculator_at`完整恢复或从真实检查点重放，必须与从源头重放一致；未来候选克隆深拷贝底部记录，不能修改真实记录。新增状态计入既有64MiB／16项缓存，源修订、Spec变化及LRU淘汰沿用原失效／重建策略，不扩容。

响应底部记录取窗口内point／event所引用、窗口内结束或截至请求仍待跟踪者的并集。原结构位于窗口外时，记录自带原事件身份／确认时间／价格参照；不能要求前端从可见窗口重新选峰。事件及point关联必须解析到返回集合，EMPTY时两方向集合均为空。

按真实请求`through`投影：确认在其后则不返回；`leftOriginAt > through`时返回null；结束在其后则返回PENDING并清空结束信息；观察时间和age按当时重算。不得把最终记录的未来离段时间／结束原因回填到历史页面。源码源指标校验及指纹仍完整执行，不借此改读源或过滤历史。

### 16.6 版本和不可变策略审计

| 字段及本次拟值 | 来源、作用范围及全部消费者 | 生效／运维可见性／测试门禁 |
| --- | --- | --- |
| `algorithm_version=xxm-direction-v0.1-h1` | 原`spec.py`唯一Spec；calculator事件／记录ID、快照、识别／预测query缓存、识别schema响应、Wealth版本校验、研究／测试fixture | 用户确认后代码发布生效；API可见版本及hash，旧缓存失效／旧快照拒绝；不是env或运营选项。A组草案r1不在本轮启用 |
| 新`bottom_history_policy=closed_origin_close_break_v1` | 同一不可变Spec；calculator步骤2—5、Spec身份／所有派生缓存和快照、研究对账 | 固定单一策略标识，不提供候选列表或动态开关；单独篡改策略／版本的快照必须拒绝，运维通过版本及hash识别 |
| 原`historical_price_only=True/fixed_expiry=None` | 原Spec字段及身份；当前TOP行为由calculator固定实现，不能误认成现成的BOTTOM能力 | 保持原值；B规则须显式实现纯价格及无固定到期，不借字段命名宣称已有实现，不新增TTL配置 |
| `dif_turn_pct=1%、max_refs=2、min_bars=2`等原普通参数 | 原Spec，普通step／首次激活、预测与测试 | 保持；1%不被引作B组历史门槛；0.75%／1.2%仅原研究候选，不新增线上分支 |
| `forecast_version=xxm-key-point-forecast-v0.2`及预测Spec | 原`forecast_spec.py`、forecast schema、Wealth严格版本校验及原缓存 | 保持预测合同和数学；detectorSpecHash采用新版内核hash，原缓存键已有该维度，不复用旧检测器结果；forecastId变化不能当数值差异 |
| 原预算／日期／展示策略 | 原BUDGET、FORECAST_SPEC、20点统一上下文及请求调度 | 4秒、200ms、1MiB识别／32KiB预测响应、64MiB缓存及完整校验保持；无新env、Settings、数据库或页面参数 |

本表是新增内部策略标识与既有字段的审计，不是已修改配置。实施时须同步唯一Spec的不可变校验和所有严格消费者，不能同一版本偷换策略或保留旧字段别名。B组仅版本身份变化，预测数值／日期／状态应保持原语义。

### 16.7 硬口径、正反例及编码门禁

| ID／硬口径 | 实现落点 | 必须通过的正向／反例 |
| --- | --- | --- |
| B01 锁定形成时的原段最低收盘 | calculator／BottomHistory | 7/9锁2922.4498；确认收盘、背离参照价不同不得替代；未来更低收盘不回写；color_flip不纳入新红柱收盘 |
| B02 原段结束后检查 | calculator／leftOriginAt | 跨7/11红柱保留到7/23；原段未结束即使破价不新增B事件；变色确认、零柱、再负柱、确认当根不触发 |
| B03 纯价格严格比较 | calculator／event | 五处已给绿色；等价不触发，严格低于触发；价格破低但DIF上升／未达1%仍按本工作规则输出；只DIF转弱未破价不触发 |
| B04 结束优先级与独立状态 | calculator／step | 原DIF突破、新底部DULL／STRUCTURE优先；9/2新黄不叠旧绿；原CANCEL保留；新TOP事件可与底部历史共存；不得改普通状态或伪造CANCEL |
| B05 关联及过去时点 | 两schema／query／Wealth adapter | 窗口外结构仍可查；悬空／跨方向ID、双关联、错误版本、未来leftOriginAt／endedAt、EMPTY非空均拒绝 |
| B06 恢复与因果 | snapshot／SeriesEntry／forecast clone | 7/9、7/11、7/22、7/23断点及四周期抽样恢复等于完整前缀；后缀修改不影响过去；候选不污染真实缓存；无10／24根固定到期 |
| B07 行为和预测不变 | 原冻结回放／forecast全链 | 普通事件／顶部历史逐项相同，四周期预测status／日期／范围／文案相同；ID／hash变化独立核对；A组旧缺陷仍显式保留 |
| B08 对照和预算 | API／整页／多标签 | 先7/23再其他四处，所有新增输出列差异；四周期20冷＋20暖、两并发、整页混合、双标签；原4秒／200ms、响应和内存门禁全部通过 |

测试路径落在现有`test_xxm_calculator.py`、预测／显示研究测试、两XXM API测试、`test_xxm_shared_loads.py`及Wealth图层／adapter／hook／forecast回归；先核实路径和真实数据权限。产品验收须走真实API，页面由用户自行验收，不重新要求登录配置。前端类型、相关测试及构建保持既有门禁；纯文档本轮不运行这些产品门禁。

对[通用交付清单](../../system/module-delivery-checklist-v1.md)逐项映射如下，不以“默认继承”省略条目：

| 清单项 | 适用性、落点及验证 |
| --- | --- |
| 2.1 事实链 | 适用；原已确认Figma视觉＋V0.1§12.10及本节B组规则已确认；函数级细化§17待Review，B01—B08和T01—T16为门禁 |
| 2.2 后端事实 | 适用；16.3—16.5产出事件／关联，adapter只展示；B03／B05和下述真实API核心字段断言 |
| 2.3 页面状态／超时 | 适用；保留两hook的loading／ready／empty／delayed／error及撤销旧请求；API实际发送后5秒前端超时，识别“研究指标加载超时，请重试”、预测“关键点预判加载超时，请重试”；后端总预算4秒。B08及现有client／hook测试，队列等待仍按原调度，不擅改计时边界 |
| 2.4 显示语义 | 适用；event的type／direction／关联驱动图上绿色“消失”和底部历史详情；B05，禁止按文案猜方向 |
| 2.5 行为过程 | 适用；hook／apiClient测试loading到结果、切周期取消、错误／超时文案；保留1280／1440原布局；B08 |
| 2.6 同轮同步 | 适用；原四文档、16.4示例及Python／TS断言同轮迁移。视觉布局未变，不要求本轮重画Figma；B05／B07 |
| 2.7 模块替换 | 部分适用；只改指数XXM历史能力，real→real而非mock切换，source开关新增／变更不适用，不增开关。回退须整套检测器／schema／前端版本回退并重建缓存，不能在线双引擎或mock兜底；B07 |
| 2.8 合同消费者 | 适用；16.2—16.5及API字段片段、B05，确认后再一次迁移。示例是待审合同，不伪装当前响应 |
| 2.9 坐标／说明 | 保持原行为；本轮不改MACD坐标／刻度，不把MACD强制设非负；新增绿色定位采用后端事件当根DIF，无新常驻说明。primitive／markerGeometry原回归＋B05 |
| 2.10 统计／传输 | 聚合下推和DB特有函数不适用：本轮无新增统计查询或SQL函数，已有完整源读取和逐根检测保持。端到端性能适用，B08约束新增状态、响应字节和4秒总预算 |
| 2.11 策略中心 | 不适用；不增加运营配置文件或策略中心注册键。内部不可变Spec身份的来源／生效／拒绝行为已在16.6单独审计 |
| 2.12 映射矩阵 | 适用；本表与B01—B08须随方案评审，无空白默认项 |
| 2.13 例外／语义断言 | 本轮无新坐标例外。新增底部价格、方向、一次触发及原段判断须有B01—B06正反例；用户自验页面的既有安排见下方门禁说明 |
| 2.14 参数原值生效 | 保持既有图表坐标传参，不改底层引擎和自动域；primitive原回归验证新增事件不影响原坐标，B05 |
| 2.15 双图对齐 | 并排双图同域不适用，本轮只在既有MACD面板新增事件；原坐标轴／标签避让及1280／1440回归仍保持，不新增双图 |
| 2.16 文案长度 | 新卡片或单行布局约束不适用；新增事件使用短标签“消失”，详情不改容器／字号，用户页面自验与原布局测试保留 |
| 2.17 真实核心case | 适用；核心字段、路由测试命令及真实展示标准见下方。单元fixture不替代真实接口或用户页面验收 |
| 2.18-1 单一事实源 | 适用；calculator→query→DTO为唯一事实，adapter不推导破价，B03／B05 |
| 2.18-2 合同冻结 | 适用；16.4含字段、可空及示例，16.2全消费者；B05前后端拒绝反例 |
| 2.18-3 配置一致 | 适用；16.6唯一Spec、身份和所有派生缓存；篡改策略／旧版本恢复拒绝 |
| 2.18-4 默认显式 | 适用；无底部记录为null／空数组，原段内不判B，缺源／超时保持原错误，不回退mock；B02／B05／B08 |
| 2.18-5 排序筛选 | 适用；原time升序和event产生次序保持，关联集合按确认时点及ID稳定排序；只按16.3因果优先级筛选，B04／B05 |
| 2.18-6 性能前置 | 适用；B08覆盖真实请求与5秒前端阈值；新记录深拷贝／状态去重耗时也计入200ms模型预算 |
| 2.18-7 异常标准 | 适用；沿用既有XXM异常码／dataStatus和用户文案，无新异常码、调试面板或生产debug信息；API／hook错误用例 |
| 2.18-8 可见结果 | 适用；真实API断言底部事件＋低点＋关联＋截止状态，真实展示应有绿色“消失”及底部结构详情；B05／B08 |

**真实核心case字段与命令。** 识别API逐项断言`period/algorithmVersion/specHash/source.computedThrough/dataStatus`、point的普通状态／指标／pendingBottomHistoryId、event的时间／方向／type／route／双向关联、bottomHistories的原结构身份／锁定低点／离段／结束信息；同时断言topHistories、普通事件及原源值未变。预测API逐项对照`detectorSpecHash/ordinaryState/status/confirmedAt/targetEndpoint/activation/relations/commonConditions/display`，只允许声明过的身份派生差异。

确认后执行：`.venv/bin/python -m pytest scripts/research/index_market/tests/test_xxm_calculator.py scripts/research/index_market/tests/test_xxm_key_point_forecast.py scripts/research/index_market/tests/test_xxm_forecast_display.py tests/web/test_wealth_index_detail_xxm_api.py tests/web/test_wealth_index_detail_xxm_forecast_api.py tests/web/test_xxm_shared_loads.py`；Wealth执行`npm --prefix wealth run typecheck`、`npm --prefix wealth run test -- src/features/index-detail/xxm src/features/index-detail/xxm-forecast`及`npm --prefix wealth run build`。真实资源冷暖／混合验收另按B08执行，不将测试数据库路由成绩冒充正式源性能。

沿用用户明确的“页面我自己验收”，不由代理自动操作页面；真实API驱动展示的可见门禁仍需由用户确认并记录，未确认前只能标技术验证通过、页面待验。应看到四周期新增历史绿色、正确结构详情和与原版相同的技术面结论，不得以mock fixture代替。无其他新增例外，不安装、部署、写库／Lake或恢复旧登录配置。

### 16.8 当前状态和确认后的顺序

上轮仅交主方案及拟议合同，未执行新B预检；该历史状态现由§16.10的本轮结果更新。产品迁移和正式API验收仍未进行，原页面三漏仍未修复；不把原42组合／1008次诊断或本轮研究成绩冒充B2／B3完成。

价格附加DIF、S2开始时机、E1接替、零柱及close-only仍是显式工作假设。若新预检与软件图文冲突、普通／顶部或预测改变、预算失败，先回方案评审，不按日期补丁、放宽保护或增加隐藏阈值。A组同段及顶部疑报继续单列，不能把B组覆盖已知样本说成全软件一致。

### 16.10 用户确认后的B1研究结果与未实施门禁（2026-10-16）

用户已确认本节工作规则，独立候选通过本次只读预检，完整证据见本轮报告（原记录：`reports/xxm_bottom_history_precheck_20261016/README.md`）及算法方案§12.10.6。实现仍为原V0.1，不新增正式字段或改前端。CodeGraph及真实代码审计范围保持§16.2；无架构／依赖变化。

| 门禁 | 本轮已验证 | 正式实施后仍须验证 |
| --- | --- | --- |
| B01—B04 规则 | 五处已知映射、9/2优先级、9/4真取消；四周期39747根原普通／顶部不变，95条新增底部事件完整列出；严格边界与受控反例 | 将同样证据映射到唯一产品内核及回归测试，未知的软件附加条件不冒充已证明 |
| B05 合同及展示 | 研究记录和关联图、单柱窗口关联窗口外原结构、过去投影不泄漏未来 | 新版严格Python／TS DTO、版本／枚举、悬空／双向关联及EMPTY反例；真实API和图层未验收 |
| B06 恢复因果 | 75个完整前缀／过去投影／恢复切点，后缀扰动及克隆深拷贝，原版本／来源拒绝 | 正式SeriesEntry、检查点、过去查询及cache回收在新版本中逐项回归 |
| B07 行为预测 | 356组完整数学／时间／范围／文案相同；18个日线校准保护保持；7/10 A组缺陷明确未变 | 正式预测query／schema／adapter新检测器hash，同一内核替换后再次验证 |
| B08 预算负载 | 正式源每周期20冷＋20暖单请求共160次研究包络，均小于4秒；356组模型最慢93.196ms；原始拟议识别最大775180字节 | 真实新HTTP／严格DTO／共享LRU，两并发、整页混合和双标签页；60分钟首冷3.895秒须重点复测，不能把本轮包络当全部验收 |

原普通内核、源校验、20点逻辑、预测Spec、原4秒／200ms均未变。本轮只读事务读取正常配置PostgreSQL白名单字段与正式Lake，四周期输入逐值等于冻结来源；不启动服务、不复用原进程密钥，不写数据库或Lake。页面仍由用户自验。B2及B3未开展，最初三漏只在独立候选中补中，正式页面仍未修复。

<a id="xxm-bottom-history-code-lld"></a>

## 17 B组代码级LLD：唯一内核及全链迁移（2026-10-16，已确认并实施）

### 17.1 本节权限、依据与审计结论

本节由逐函数审计形成，细化§16／算法方案§12.10，不改变H1—S2—E1工作规则。用户本轮已确认按本节编码，B2唯一内核及消费者已实施；下文保留设计约束，实际代码／测试与验收对账见§18。B1研究证据独立保留；A组7/10同段循环、重新激活及顶部疑报继续排除，无DB／Lake写入。

审计使用仓库根CodeGraph `codegraph_search`、`codegraph_explore(XxmCalculator)`、`codegraph_impact(XxmCalculator, depth=2)`；影响分析返回68个符号，其中包含历史研究脚本，不能把68解释为68个生产改动点。再核当前完整calculator、query／schema、三个路由、预测克隆、严格adapter、两图表调用和现有测试。事实与设计分开：

| 编号 | 编码前审计事实／缺口 | 已确认编码决策 |
| --- | --- | --- |
| K1 | calculator.py:93—126只维护TOP历史，普通变色分支清state／reference | 普通及TOP分支原样保留，增加独立BOTTOM记录及后处理；不导入研究CandidateCalculator或启动第二个在线引擎 |
| K2 | types.py的XxmStep只有point／events／histories | 增加必传的内部bottom_histories；histories继续只指TOP，不改名混合 |
| K3 | query_service.py:223、228两处SeriesEntry位置参数构造；新历史没有账本落点 | 增加独立bottom_histories，改这两处为显式关键字构造，增量时复制容器再发布 |
| K4 | _response只投影TOP；旧记录最终ENDED状态不能直接用于过去查询 | 新增BOTTOM专用过去投影与窗口选择，返回集合覆盖point／event关联，保留窗口外原结构身份 |
| K5 | Python DTO未定义BOTTOM记录，Wealth adapter历史事件必须relatedTopHistoryId非空，eventLabel还断言TOP | 后端字段、方向关联校验、TS类型／adapter／详情一次迁移；只改calculator会在当前消费者处失败 |
| K6 | forecast_detector.clone及calculator_at都实例化同一XxmCalculator再restore | 函数签名和数学不变；新snapshot／restore自动携带底部状态，补克隆隔离与过去恢复测试，不写第二条克隆逻辑 |
| K7 | 识别adapter固定algorithmVersion旧值；预测adapter固定forecastVersion v0.2，但detectorSpecHash仅校验64位十六进制格式 | 识别改为唯一h1版本；预测版本／hash格式合同保持，实际API断言其detectorSpecHash等于新MAIN_SPEC，不虚称前端已有精确hash白名单 |
| K8 | 原冻结回归最后统计所有RESEARCH_HISTORICAL_WITHDRAWAL，与TOP旧manifest比较 | 普通断言保持，旧TOP统计显式限定direction=TOP；另新增BOTTOM95条基线，不改旧manifest来掩盖差异 |

审计证据及源文件SHA见代码级LLD审计记录（原记录：`reports/xxm_bottom_history_code_lld_audit_20261016/README.md`）。下述签名、字段和伪代码保留已确认的编码约束；真实实施按§18对账，原行号仅定位审计基线，以当前函数为准。

### 17.2 文件级改动清单与不改边界

下表统一定位：S=`src/biz/services/wealth/market/index_detail_xxm/`，Q=`src/biz/queries/wealth/market/index_detail_xxm/`，D=`src/biz/schemas/wealth/market/`，W=`wealth/src/features/index-detail/`。

| 文件／对象 | 具体修改或核验 | 下游及对应测试 |
| --- | --- | --- |
| S/types.py | 新XxmBottomHistory类型；XxmStep新增bottom_histories | calculator、Q账本；T01—T04 |
| S/spec.py | 修改algorithm_version默认h1，增加不可变bottom_history_policy；原参数与hash算法不变 | ID／snapshot／cache／响应；T05 |
| S/calculator.py | __init__、step、snapshot、restore及17.4私有函数 | 识别与预测共享唯一内核；T01—T06 |
| Q/query_service.py | SeriesEntry字段；_load_series两构造和底部upsert；_response及新增底部投影helper | 两识别API／预测calculator_at；T06—T09 |
| D/index_detail_xxm.py | 新XxmBottomHistoryDto及point／event／response字段；方向关联、时间和窗口校验 | 日线与分钟共同DTO；T08—T10 |
| S/forecast_detector.py、Q/forecast_query_service.py | 默认不改算法代码；验证clone／calculator_at恢复、确认事件筛选、新Spec缓存及响应身份 | 预测schema／adapter；T11—T12 |
| W/xxm/types.ts、adapter.ts | 新底部类型／明细集合，唯一新版本，严格关联与文字分支 | primitive／详情；T13—T15 |
| W/xxm/XxmLayerUi.tsx | 独立渲染底部原结构／低点／离段／结束原因；TOP详情不改 | 两tooltip共用；T14 |
| W/xxm/xxmFixtures.test-support.ts及相关测试 | 每个point／event补必有可空字段，response补bottomHistories，版本改h1；加真实新类型case | adapter／hook／geometry；T13—T15 |
| scripts/research/index_market/xxm/acceptance.py、新bottom_history_acceptance.py及scripts/research/index_market/README.md | 收集底部账本和新差异，保留原TOP对照；新增验收入口说明，输出到新版本目录，保持acceptance.py原参数名 | 冻结四周期及真实API样本；T16 |
| scripts/research/index_market/xxm_page_request_audit.py／.mjs | 保留现有306请求实际TS调度与只读真实HTTP；去掉硬编码历史日期，加底部合同／adapter断言及身份记录，不新造另一套混合runner | T16／17.11 |
| 现有六个Python测试文件及Wealth相关测试 | 按17.10增补／调整断言；不删除旧普通／TOP断言 | 正反例与全链门禁 |

以下为审计过的调用方，**本轮设计无需生产代码修改**：三个Biz路由index_detail_xxm.py／index_detail_minute_xxm.py／index_detail_xxm_forecast.py、App装配src/app/api/v1/router.py、Q/source.py／shared_loads.py、S/runtime.py／projection.py／forecast_spec.py／forecast_math.py／forecast_entry.py／forecast_joint.py／forecast_text.py、W/xxm/{apiClient,useIndexXxmLayer,XxmMacdPrimitive,markerGeometry}.ts及IndexChartWorkspace.tsx／IndexMinuteChartWorkspace.tsx、W/xxm-forecast的生产类型／adapter／hook／卡片及页面请求调度。若实现必须修改这些文件的行为，应先说明原因和影响，不能借B组改来源、日期、数学、鉴权、布局或调度。

Biz仍只读Foundation，Wealth仍经HTTP消费；不把计算搬进QTF、Foundation或前端，不新增SQL、DB表／迁移、env／Settings、运营开关或依赖。原内部Spec配置审计沿用§16.6；新增策略只有一个固定值，不提供旧／新算法切换。

### 17.3 类型、身份与原字段兼容边界

**S/types.py。** 新增`XxmBottomHistory(TypedDict)`，字段完整对应§16.4的BottomHistory；不是Pydantic模型，不依赖API层。`originalReference`为原四字段参照的独立深拷贝。`status`固定PENDING／ENDED，`endReason`固定四种原因或null；原结构／段／低点字段建立后不再修改。TOP继续使用既有dict及histories。

```python
# 新签名；无默认空值以迫使所有生产构造方迁移
@dataclass(frozen=True, slots=True)
class XxmStep:
    point: dict[str, Any]
    events: tuple[dict[str, Any], ...]
    histories: tuple[dict[str, Any], ...]       # 原TOP变化
    bottom_histories: tuple[XxmBottomHistory, ...]
```

此前§16及研究候选的`XxmStep.bottomHistories`在正式Python实现中统一拼写为`bottom_histories`；**外部JSON仍是bottomHistories**。这只是内部命名细化，不增加别名，不同时保留两种内部属性。旧研究候选、脚本和报告原样保留；正式代码及测试不得import研究CandidateCalculator。

**S/spec.py。** 在唯一XxmSpec中设`algorithm_version="xxm-direction-v0.1-h1"`并增`bottom_history_policy="closed_origin_close_break_v1"`。保持现有fields／asdict不可变校验、允许的三个研究dif_turn_pct值及spec_hash规范化算法。默认主Spec的值集合与B1候选相同，应得到候选hash `b2ebada1a7ef0f013cf2b9a447a6a9fee8c73ac660c3fee41a9be13e3ca290e5`；若不同先对账字段和值，不修改旧证据或忽略差异。测试可用候选hash核身份，生产消费者不得各自硬编码这份hash作配置。

身份生成明确复用`_id`：

| 对象 | 构造 |
| --- | --- |
| 原普通／TOP事件和TOP历史 | 原_id参数顺序原样保留，只因新Spec自然换ID |
| 新BOTTOM记录 | `_id("bottom-history", structure_event["id"])` |
| 新BOTTOM历史消失事件 | `_id(bar.time, "RESEARCH_HISTORICAL_WITHDRAWAL", history_id)` |

所有事件新增必有可空`relatedBottomHistoryId`，默认null；只有BOTTOM STRUCTURE和其BOTTOM历史消失填底部ID，其他事件为null。TOP原关联保持，单个事件禁止双向关联。每个point新增必有可空`pendingBottomHistoryId`，与普通状态独立。不增加A组事件枚举、等待字段或预测字段。

### 17.4 calculator.py逐函数修改

#### 17.4.1 __init__及step的插入位置

`__init__`仅新增`self.pending_bottom_history: XxmBottomHistory | None = None`。保留`pending`作为原TOP状态，不重命名、不改其含义；每周期至多一条待跟踪BOTTOM记录。结束记录交调用方账本，内核不保存全量历史。

`step(bar)`保持当前31—85行的输入校验、段池更新、普通状态转换和选参照顺序，尤其不改72—73行dif_return。保留现有`old_wave`引用即可：变色后它指向旧段，新段另建；创建底部记录时复制标量与参照。**不复制整颗calculator，不每根深拷贝完整wave来取得一个未使用的旧段**。本优化只去掉研究wrapper成本，不改变采样时点。

固定执行顺序：

```text
校验bar → 保存old_wave/old_state → 原普通分支
→ 创建原普通event（新增relatedBottomHistoryId=null）
→ 执行原TOP历史分支和TOP记录创建，保持事件原顺序
→ 处理此前pending_bottom_history（DIF优先、新BOTTOM信号其次、价格最后）
→ 若本根普通event为BOTTOM STRUCTURE，创建并关联新的底部记录
→ point加入本根最终pendingBottomHistoryId
→ previous/processed更新 → 返回XxmStep四个字段
```

`ordinary_event = events[0] if event_type else None`在普通事件生成后固定，不从已追加的历史事件中猜“第一条”。BOTTOM历史事件排在原普通／TOP事件之后；同柱TOP、BOTTOM各自独立。新增后处理不得修改`state/reference/history/wave`或任何原普通事件字段（新增底部关联除外）。

#### 17.4.2 新增私有函数及精确职责

| 签名 | 读取／修改 | 返回及限制 |
| --- | --- | --- |
| `_advance_bottom_history(self, bar: XxmBar, ordinary_event: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[XxmBottomHistory]]` | 只读bar、原普通事件和普通state；只修改pending_bottom_history | 返回本根新增历史事件及旧记录变化；不创建新结构记录 |
| `_start_bottom_history(self, bar: XxmBar, structure_event: dict[str, Any], negative_wave: Wave) -> XxmBottomHistory` | 读取已确认普通BOTTOM结构和选定原负段；设置新pending，填structure_event.relatedBottomHistoryId | 返回新记录深拷贝；要求negative_wave.sign==-1、eventReference非空 |
| `_validate_bottom_history_snapshot(self, raw: Any, *, previous: XxmBar | None, wave: Wave | None, processed: int) -> XxmBottomHistory | None` | 校验并独立复制，不修改self | 无效抛ValueError；不靠assert作运行校验，不补缺字段或修正数值 |

`_advance_bottom_history`伪代码：

```python
if pending is None:
    return [], []
r = pending
r["observedThrough"] = bar.time
r["ageBars"] += 1
if r["leftOriginAt"] is None and bar.hist >= 0:
    r["leftOriginAt"] = bar.time
reason = None
if bar.dif < r["originalReference"]["dif"]:
    reason = "original_reference_break"
elif ordinary_event and ordinary_event["direction"] == "BOTTOM" and ordinary_event["type"] in ("DULL", "STRUCTURE"):
    reason = "new_bottom_" + ordinary_event["type"]
elif r["leftOriginAt"] is not None and bar.time > r["confirmedAt"] and bar.close < r["priceLow"]:
    reason = "historical_price_break"
    append_one_bottom_history_event(r)  # 原state，不是CANCEL/DULL
if reason is not None:
    r.update(status="ENDED", endedAt=bar.time, endReason=reason)
    self.pending_bottom_history = None
return new_events, [deepcopy(r)]
```

`append_one_bottom_history_event`只是伪代码动作，不另建公共API：在函数内构造当前type／historical_price_break route、direction=BOTTOM、fromState=self.state、eventReference=deepcopy(r.originalReference)、relatedTopHistoryId=null、relatedBottomHistoryId=r.id及17.3的ID。没有价格等号epsilon、额外DIF相邻跌幅或TTL。精确零柱登记离段；若同根还满足价格和优先级条件，可以触发价格事件，零柱本身不能单独触发。

创建规则由step明确选段：`negative_wave = wave if sign == -1 else old_wave`，仅在已知普通BOTTOM STRUCTURE时调用。dif_turn含当前确认负柱已更新的最低收盘；color_flip取刚结束负段，**不纳入确认红柱收盘**，并令leftOriginAt=bar.time。填originSegmentStart、priceLow／priceLowAt、结构ID／时点／route和独立原参照，ageBars=0、observedThrough=confirmedAt、PENDING／null结束信息。创建当根不再执行价格消失；同柱旧记录结束、新记录创建时返回两份不同ID的底部变化。

#### 17.4.3 snapshot与restore

`snapshot()`在原完整快照中增加必有`pendingBottomHistory`，值为新pending的深拷贝或null；原TOP pending及history两池定义不变。保存的只有一条未结束记录，不能把调用方底部账本塞进每1000根检查点。

`restore(snapshot)`先核原四元身份，再把原wave／history／previous等解码到局部变量，沿用原段池上限校验；用新私有校验器检查底部，全部通过后再赋给self，避免无效底部快照使一个已有calculator处于半恢复状态。新增key缺失、旧Spec、字段错误均ValueError，不使用`.get(..., None)`兼容旧快照。

底部快照至少校验：字段集合完整且无多余项；状态只能PENDING且结束信息为空；低点有限且大于零、原参照有限、age为非负整数且不超过processed；previous存在、observedThrough等于previous.time；originSegmentStart≤priceLowAt≤confirmedAt≤observedThrough；参照start≤end<originSegmentStart；leftOriginAt为空或confirmedAt≤leftOriginAt≤observedThrough。时间按对应period的现有XxmBar时间规则校验，不在services反向import查询层ENDPOINTS。未离段时快照wave必须是同一起点负段；离段信息在单次前向step中不得回退，但合法的过去快照允许恢复到离段前，不能拿恢复前self的最终状态拒绝它。记录ID与structureEventId非空并符合17.3派生关系。没有完整源数据时不猜age或低点是否为真实极值，完整真实性由前缀重放测试证明。

### 17.5 query_service.py：底部账本、发布与过去查询

#### 17.5.1 SeriesEntry及_load_series

在`SeriesEntry`新增必传`bottom_histories: dict[str, XxmBottomHistory]`；既有`histories`继续只保存TOP。calculator、points、events及checkpoints仍只有一套。两处构造必须按关键字显式填写全部已有字段和新字段，不能在旧位置参数末尾随意插值：

- 全量重建分支（当前223行）：bottom_histories={}，沿用原source_identity及processed空前缀；不从旧TOP账本派生底部记录。
- 增量分支（当前228行）：新calculator从旧完整snapshot恢复；points／events／histories／fingerprints／checkpoints按原方式复制，增加`bottom_histories=dict(entry.bottom_histories)`，不能让另一个请求看到容器被原地追加。
- 逐根循环：原TOP upsert不动，新增`entry.bottom_histories.update({h["id"]: h for h in step.bottom_histories})`。这些h都是step交出的独立副本；后续只替换账本同ID的值，不能原地修改已发布记录或嵌套参照。
- 每1000根checkpoint仍取`calculator.snapshot()`；新pending自动包含，不能额外保存整份底部账本。`replace(entry, processed=..., ...)`仍在完整验证后发布，失败路径不发布半成品。
- 来源修订、原点改变和已处理前缀不匹配时，沿用原全量重建条件，底部账本随同重建，不残留旧来源的记录。相同signature／raw／完成端点／日历可复用的早返条件保持原样。

`calculator_at(count, check)`签名及两条恢复路径保持：最新从当前snapshot克隆，过去从`floor(count/1000)*1000`检查点重放最多999根；新增pending由唯一restore处理。不从最终bottom_histories倒灌过去calculator，不为了修图绕过source prefix或重新选峰。

`_deep_size`已递归dataclass字段／dict，不加第二套估算器；新字段会自动纳入64MiB／16项LRU。单条内核状态有限不代表总账本不占内存；缓存超限沿用现有不缓存／淘汰行为，不靠TTL删除历史事实。

#### 17.5.2 _response与新增底部投影helper

内部`_response`增加必传`check`回调，`build`现有唯一生产调用传入remaining。保留原points、events、sourceInputId、dataStatus和TOP集合的输出语义；在TOP和BOTTOM账本遍历中每1000项检查预算，最后仍校验1MiB及remaining，不改变4秒起点或前端5秒起点。

新增两个静态私有函数，放在同一query_service.py，不引入新通用历史框架：

```python
_project_bottom_history(record: XxmBottomHistory, *, through: str,
                        times: list[str]) -> dict[str, Any] | None
_bottom_histories_for_response(entry: SeriesEntry, *, points: list[dict],
    events: list[dict], first: str | None, last: str | None,
    through: str | None, times: list[str], check) -> list[dict[str, Any]]
```

`_project_bottom_history`定义：

1. `record.confirmedAt > through`返回None。
2. 独立深拷贝；若leftOriginAt在through之后，清为null。
3. 若endedAt在through之后，投影为PENDING并清endedAt／endReason；已在through或之前结束则保留ENDED。
4. observedThrough设为有效endedAt或through；ageBars=`bisect_right(times, observedThrough)-bisect_right(times, confirmedAt)`，计完整来源柱，不按日历天数或可见窗口长度计算。
5. 只取XxmBottomHistoryDto定义字段返回；不改entry内记录。

`_bottom_histories_for_response`：first／last／through任一无值时返回[]，保持“有来源但请求窗口无柱”的现有行为；否则先收集所返point的pendingBottomHistoryId和event的relatedBottomHistoryId。记录确认不晚于through，且满足以下任一项才返回：被上述ID引用；截至through仍PENDING；或有效结束时间在[first,last]内。判断PENDING时先考虑未来endedAt应被隐藏；只对入选记录深拷贝投影，避免每次响应复制整本无关历史。按`(confirmedAt,id)`稳定排序。

原结构在窗口外不要求把窗口外STRUCTURE事件塞进events；BottomHistory自身携带structureEventId、confirmedAt、原段低点和原参照。响应中的全部关联必须能解析到对应集合；不存在记录时由DTO严格失败，不能删掉关联或绿字兜底。

注意：**point.pendingBottomHistoryId表示该point当时的状态，而记录status按整个请求through投影。** 因而前一根point合法引用一条在窗口后面已经结束的记录；校验应要求`confirmedAt <= point.time < endedAt`（未结束时无右界），不能要求该记录在整个响应末尾仍PENDING。

#### 17.5.3 原缓存和共享加载保持

load_entry的key已含MAIN_SPEC.spec_hash，flight_key还含业务日期、now日期和完成端点；预测key也含检测器Spec、预测Spec、来源指纹和未来日历。新Spec自然隔离旧结果，不加bottom_history_policy之外的第二组配置、不省略源校验，也不新增一个B专用在线cache。部署换进程时重建；同进程不可命中旧Spec记录，旧项按原LRU回收，禁止回退旧引擎结果。

完整历史仍按1000根计算，源读取层／两并发槽位／SharedLoads／统一20点语义保持。共享leader完成发布后才向waiter交entry；waiter超时不得取消leader。正式计时需覆盖排队、源检查和完整读取、普通与底部计算、快照、缓存计费及响应构造。

### 17.6 Python API合同：新增字段与拒绝条件

D/index_detail_xxm.py保持XxmDto的extra=forbid／禁止NaN。新增必有字段，不给None或[]默认值来接受旧响应；同一URL以新algorithmVersion明示语义变化。

| 类／方法 | 必须修改 |
| --- | --- |
| XxmPointDto | 新`pendingBottomHistoryId: str | None`；consistent_state原NONE／活动参照约束不变，底部历史存在不能使NONE携带activeReference |
| XxmEventDto | 新`relatedBottomHistoryId: str | None`；新增事件关联validator，规则见下表 |
| 新XxmBottomHistoryDto | 按§16.4全部14项字段：id、structureEventId、confirmedAt、confirmationRoute、originSegmentStart、leftOriginAt、priceLow、priceLowAt、originalReference、status、endedAt、endReason、observedThrough、ageBars；以此显式字段列表为准 |
| XxmResponseDto | 新`bottomHistories: list[XxmBottomHistoryDto]`；consistent_window新增版本／两集合关联和时间校验，保留原窗口约束 |

上表BottomHistory字段以列出的**14个字段名**为准，不包含方向字段，也不复制TOP的negativeBars／zeroBars／colorChanges。底部方向由集合和事件关联表达。`priceLow > 0`且有限，ageBars为非负整数；status／endReason、原段与时间顺序和snapshot一致。PENDING要求结束字段均null；ENDED要求endedAt／endReason都非null且observedThrough=endedAt，不能用空字符串代替null。

| 事件 | relatedTopHistoryId | relatedBottomHistoryId | 额外条件 |
| --- | --- | --- | --- |
| TOP STRUCTURE | 对应TOP记录ID | null | 保留现有创建／关联 |
| BOTTOM STRUCTURE | null | 对应BOTTOM记录ID | 记录structureEventId=事件id、confirmedAt=事件time |
| TOP历史消失 | 必有TOP ID | null | type为RESEARCH_HISTORICAL_WITHDRAWAL且route=historical_price_break |
| BOTTOM历史消失 | null | 必有BOTTOM ID | 同type／route，记录ENDED／historical_price_break／endedAt=事件time，eventReference等于该记录originalReference |
| 其他普通事件 | null | null | 不把普通CANCEL伪装成历史消失；新增两个方向各自历史事件仍可同柱 |

`consistent_window()`在原约束后校验：

1. algorithmVersion等于MAIN_SPEC.algorithm_version，specHash等于MAIN_SPEC.spec_hash（来自唯一Spec，不维护第二份后端版本配置）。
2. 两集合ID各自唯一且不交叉；event ID唯一；空ID、悬空ID、双关联、错误方向或historical_price_break配普通type均拒绝。
3. 每条底部记录confirmedAt／leftOriginAt／endedAt／observedThrough不晚于source.computedThrough；先由query作过去投影，再校验，schema不负责自动修正未来字段。记录originalReference和低点时间顺序合法。
4. point引用底部记录时，记录已在该point形成且未在该point或更早结束；TOP原语义保留。不能只检查ID存在，也不能以最后status=ENDED否定早先合法point。
5. STRUCTURE事件位于窗口内时，记录必须反向对应id／时点／route；位于窗口外时允许仅记录自带身份，不要求events越界。
6. 截至through最多一条PENDING底部记录。PENDING.observedThrough=through；ENDED.observedThrough=endedAt。年龄精确值由完整源计算，DTO不能靠可见窗口虚算。
7. dataStatus为EMPTY时points／events及顶底历史集合全空、computedThrough=null；普通READY且零事件仍合法。完成源非空但窗口无柱时，两历史集合空，不改成SOURCE_EMPTY。

两个识别路由的response_model自然使用新DTO，URL／请求参数／权限／错误码／分钟能力门禁保持；App装配不改。非法关联或投影经既有load_entry的ValueError捕获映射XXM_SOURCE_CONTRACT_INVALID，不吞字段继续返回READY。新增validator必须用ValueError，不能将assert当合同保护。

### 17.7 预测链的具体保持点与回归

S/forecast_detector.py的`clone(c)`继续用唯一XxmCalculator及`restore(c.snapshot())`，不加CandidateCalculator工厂、模块级替换或另一套历史克隆。`event_options`按指定type＋direction查普通事件，`confirmed_options`仍只以普通state／reference及CANCEL／STRUCTURE决定情景是否继续；新历史事件不得冒充普通事件。

Q/forecast_query_service.py的`build`继续按当前ordinaryState或当根真实STRUCTURE判CONFIRMED，不从bottom_histories找一条旧结构充数；调用calculator_at时自动取得完整底部状态。cache_key、响应detectorSpecHash采用新MAIN_SPEC；forecastVersion及ForecastSpec hash保持，forecastId可因检测器身份变化而不同。D/index_detail_xxm_forecast.py、W/xxm-forecast/adapter.ts的字段及v0.2合同不加新字段，不新增精确检测器hash白名单或rearmContext。

需要迁移的是测试／fixture和恢复保证，不是另写预测数学：

- 新pending有无、是否已离段、结构确认当根及历史消失当根，分别验证clone前后真实snapshot不变；候选结束只发生在独立克隆中。
- 继续用完整snapshot作状态去重，不能删掉底部状态来降低计时；新增state可能改变去重成本，因此纳入200ms。
- 原356组场景对照完整数学结果和display。只允许detectorSpecHash、forecastId及识别事件／记录ID等声明过的身份差异；参考段、status、目标日期、区间、排除原因、文案不能忽略。
- 原18个日线历史校准失败仍返回原PRECISION_PENDING／CALIBRATION_FAILED；不能把失败数减少当作B组收益，不能调MACD参数或容差来补绿字。

### 17.8 Wealth严格消费与可见结果

#### 17.8.1 types.ts与buildXxmViewModel

保留现有`XxmHistory`名称及TOP定义，新增`XxmBottomHistory`对应JSON的14字段；在XxmPoint／XxmEvent／XxmResponse分别增加必有可空底部ID／必有可空底部关联／必有底部数组。`XxmDetail.histories`仍只存TOP，新增`bottomHistories: XxmBottomHistory[]`，不把两个形状不同的记录塞进无方向union。

`buildXxmViewModel`按以下位置迁移，不改`timeKey`的日线字符串／分钟秒时间映射，也不改当前图表原值逐根对账：

1. algorithmVersion的唯一允许值由旧v0.1改h1，不写`old || new`；specHash仍校验格式。显式断言新增字段存在且类型正确，不能以`?? []`／`?? null`接受旧响应。
2. EMPTY分支要求两历史集合均为空；所有point按原顺序校验close／DIF／DEA／hist与主图原值，底部历史不能掩盖源指标不一致。
3. 与原TOP map并列创建BOTTOM map。依17.6的时间／状态／唯一性／关联条件验证；两个ID域不交叉。**对所有response.points校验底部引用后**再按chartByTime选择可见明细，不能因API窗口含更早的分钟端点而略过合同校验。
4. byTime初始化同时带histories和bottomHistories；按各自pending ID加入。结束于窗口内的底部记录也加入其结束时点明细，采用ID去重；同柱旧记录结束、新记录创建时两份都保留。
5. events循环保留event ID唯一、route／方向／参照及窗口检查，历史事件改为按方向解析对应集合，禁止双关联；事件所在端点在API窗口但早于当前已加载图表时保持原“验证后跳过绘制”逻辑。
6. BOTTOM STRUCTURE及其历史消失加入对应底部详情；marker仍使用事件当根point.dif和chart time，不能用priceLow作MACD坐标。markers按后端原事件次序生成，不由前端补“消失”、重新配最近结构或去掉同柱其他事件。

#### 17.8.2 标签、详情及原视觉

`eventLabel`保留原普通事件和TOP历史文字；增加BOTTOM历史显式返回“底部结构消失”。`eventMarkerLabel`对**新增BOTTOM历史**显式返回“消失”，其他事件保持当前逻辑，避免机械去“底”后剩“部结构消失”。本轮不顺手改变现有TOP图上标签或其他普通标签。

`XxmLayerUi.tsx`的XxmResearchDetails在原TOP详情后单独渲染bottomHistories：关联底部结构confirmedAt、保存最低收盘priceLow及priceLowAt、已知时的离开原柱段leftOriginAt、跟踪状态／原因、结束时间及截至／ageBars。新增底部私有状态文字函数，不给现有historyStatus硬塞TOP没有的字段：

| 底部记录状态／原因 | 详情文字 |
| --- | --- |
| PENDING | 仍在跟踪 |
| original_reference_break | 已结束 · 原DIF参照失效 |
| new_bottom_DULL | 已结束 · 新底部钝化接替 |
| new_bottom_STRUCTURE | 已结束 · 新底部结构接替 |
| historical_price_break | 已结束 · 收盘跌破原低点 |

这些均为历史记录状态，不替代“普通状态”，不把无价格绿字的接替写成“钝化失效”。已确认详情容器、样式和坐标保持，不新增配置或常驻说明。

`XxmMacdPrimitive.color`现已按type给历史消失绿色，方向无关，原则上无需改；`markerGeometry`现已支持按同柱分组避让和紧凑+N，保持圆点半径4、字号12／字重700及左侧优先。新增BOTTOM事件由adapter正确进入markers后自然绘制。日线和分钟两个Workspace都复用同一hook／primitive／XxmResearchDetails，调用签名不变，不分别重写实现。

`useIndexXxmLayer`现有缓存身份含algorithmVersion|specHash。新adapter会拒绝旧版本响应并清掉本hook旧缓存后按原逻辑重取，不能放宽校验来显示旧结果。请求取消、指标未就绪、loading／ready／empty／delayed／error和重试保持。技术面卡片只验证新检测器响应仍符合v0.2合同，不新增文案／评分或历史消失预测。

### 17.9 当前消费者全集及逐项处置

| 消费组／真实入口 | 实施处置与必须证明的结果 |
| --- | --- |
| 识别HTTP：三个路由文件中的日线／分钟识别两个handler | 使用同一新DTO和唯一query；日线走xxm-signals，分钟走minute-xxm-signals；参数、鉴权及分钟能力判断不改 |
| App：src/app/api/v1/router.py的三路由装配 | 无实现修改；依赖注入／现有本机分钟开放边界保持，禁止为了验收开启新能力 |
| 预测HTTP：index_detail_xxm_forecast.py的get_forecast | 同一load_entry和calculator_at；错误前缀仍XXMF_，不接第二套来源或额外预测字段 |
| Q：完整／增量SeriesEntry、两个识别API共用的_response、预测state恢复、共享LRU | 所有构造／复制／checkpoint／source revision／淘汰路径都带底部，不能只在冷重建有结果 |
| W：xxm types、adapter、fixture、hook、两Workspace、tooltip、primitive和geometry | 改类型／adapter／详情及fixture，其他逐项回归；不在图表消费者推导事实 |
| W：xxm-forecast types／adapter／client／hook／card | 生产合同不变，验证新detectorSpecHash和旧预测数学可消费；不因预测hash格式校验而声称软件规则已验证 |
| 研究：acceptance.py、原calculator／forecast／display测试 | 原TOP基线显式按方向统计；新增底部账本与同源差异，写新OUT；不改旧报告或import旧研究wrapper在线运行 |
| 历史reports下的CandidateCalculator／原回放和预检脚本 | 冻结保留，无生产迁移，不批量改这些脚本的构造或旧版本字符串；需要复现旧版本时记录其原源码／hash条件 |

引用审计至少覆盖`XxmStep(`、`SeriesEntry(`、`.histories`、`topHistories`、`pendingTopHistoryId`、`relatedTopHistoryId`、旧algorithmVersion及RESEARCH_HISTORICAL_WITHDRAWAL。生产XxmStep现有一处构造、SeriesEntry现有两处构造，全部迁移；旧版本字面量保留在旧报告和明确拒绝旧版本的测试是正确行为，不要求全仓盲目清零。

### 17.10 函数级正反例与测试落点

T01—T16是本轮实施的测试组，当前运行成绩与具体映射见§18；组号不是独立用例数量。采用现有测试文件，不把临时研究probe当作正式回归。日期例子只在测试数据和验收期望中出现，生产算法禁止日期特判。

| 组 | 文件／目标函数 | 正向与负向断言 |
| --- | --- | --- |
| T01 | scripts/research/index_market/tests/test_xxm_calculator.py：step／_start_bottom_history | 日线7/9锁7/8的2922.4498；dif_turn包含确认负柱已知低点，color_flip排除确认红柱；后续新低不回写；字段不可与确认收盘或原背离参照价混用 |
| T02 | 同文件：_advance_bottom_history | 五处已知绿字对齐；相等／高于不触发、严格破低触发一次；仅DIF转弱未破价不触发；价格破低且DIF改善仍按工作规则触发 |
| T03 | 同文件：step优先级与段边界 | 原段未结束不判B；红／零登记离段、不单独结束；再负柱仍按历史观察；原DIF严格突破优先、等号未突破；新BOTTOM DULL／STRUCTURE优先，TOP不接替BOTTOM；旧结束和新创建同柱保留两记录 |
| T04 | 同文件：普通／TOP不变及范围 | 四周期普通state／reference／两池／TOP历史语义与原基线相同；TOP普通＋BOTTOM历史事件可共存；不修改7/10现有dif_return行为；非上证／非法周期／未完成bar继续拒绝 |
| T05 | 同文件：Spec／_id／snapshot | 默认h1及固定policy计算预期hash；改策略值拒绝；原Spec快照／其他来源／对象／周期拒绝；新ID稳定且两个方向关联独立；不靠日期分支命中 |
| T06 | 同文件和tests/web/test_wealth_index_detail_xxm_forecast_api.py：restore／calculator_at | 有／无pending、未离段／已离段、超过24根恢复等于完整前缀；缺字段／ENDED pending／未来时间／错误派生ID拒绝且不污染旧实例；999／1000／1001切点及来源修订后重建 |
| T07 | tests/web/test_wealth_index_detail_xxm_forecast_api.py：_load_series增量发布 | 保留test_published_entry_is_not_mutated_when_another_request_appends并断言旧bottom_histories／nested reference／checkpoint均未变；冷／追加／复用／来源修订／淘汰重建的底部输出一致 |
| T08 | tests/web/test_wealth_index_detail_xxm_api.py：_response／helper | through分别7/9、7/11、7/22、7/23；隐藏未来离段／结束，年龄按全历史柱计数；只返消失一根仍带窗口外原结构记录；旧记录末尾ENDED时前序pending引用仍合法 |
| T09 | 同文件和预测API测试：DTO／数据状态 | 必有新增字段；EMPTY全空；READY零事件合法；有源但请求窗口无柱保持原READY语义且无历史；DELAYED不伪装最新；原20点四周期边界测试全部保留 |
| T10 | 同文件：XxmEventDto／XxmResponseDto校验 | 悬空／重复／双向／错方向／错版本／未来时点拒绝；BOTTOM历史对应ENDED记录及同参照；结构事件可见时反向ID／time／route一致；记录在窗口外可自带身份；不要求point引用记录在末尾仍PENDING |
| T11 | scripts/research/index_market/tests/test_xxm_key_point_forecast.py：clone／event_options／forecast | 结构前后和历史消失前后克隆包含底部且不改真实状态；历史事件不当普通STRUCTURE／CANCEL；相同输入完整数学／日期／范围一致；默认最近单时点规则不变 |
| T12 | scripts/research/index_market/tests/test_xxm_forecast_display.py及预测API测试 | display全文和远端筛选不变；18个既有日线校准失败保护保留；实际API新detectorSpecHash=MAIN_SPEC，forecastVersion／Spec hash不变；forecast cache由新检测器身份隔离 |
| T13 | wealth/.../xxm/adapter.test.tsx、xxmFixtures.test-support.ts | 旧响应／缺bottom字段／悬空／双关联／错误方向／未来结束拒绝；图表原值不符仍拒绝；新增底部历史正确出marker与详情；API较早分钟端点验证后才跳过绘制 |
| T14 | 同adapter.test.tsx：eventLabel／eventMarkerLabel／XxmResearchDetails | 详情“底部结构消失”，图上“消失”，无“部结构消失”；低点及结构日期来自记录；接替不是钝化失效；TOP旧详情／普通标签保持 |
| T15 | wealth/.../xxm/{useIndexXxmLayer.test.tsx,markerGeometry.test.ts,apiClient.test.ts}和xxm-forecast测试 | 新版本刷新／旧结果取消、超时／失败／独立重试；双方向同柱避让与+N／点大小字重不变；预测新hash被当前v0.2严格字段合同接受，仍拒绝额外字段与错周期 |
| T16 | scripts/research/index_market/xxm/acceptance.py及新bottom_history_acceptance.py | 39747根普通／TOP语义、五处映射、95条完整新增清单、356组预测结果；旧TOP与新BOTTOM分别统计，旧manifest／源SHA／研究报告不修改；正式API／预算见17.11 |

原`test_entire_frozen_ordinary_and_historical_baseline`最后的TOP历史数量断言必须加direction=TOP过滤，期望仍取原manifest；不是删除断言或把manifest数字改成新合计。原普通事件比较保持。新增BOTTOM另核已冻结95条发生时点、原结构、低点和结束原因；60／90没有软件正观察的事实仍注明，不能把95条当95条软件正确率样本。

### 17.11 验收脚本、命令和计时边界

新增**仅供开发验收**的`scripts/research/index_market/xxm/bottom_history_acceptance.py`，与产品代码同轮Review。只import正式XxmCalculator、query／schema和真实路由，不import或注入B1 CandidateCalculator／FastReader。支持`--mode frozen|api|budget --source <冻结源目录> --output <新报告目录>`；budget显式加`--formal-source`才可访问正常配置DB和正式Lake；mixed复用现有xxm_page_request_audit入口，不复制其后端和JS调度器。source目录／输出目录是审计输入，不是用户或运营配置；预算、对象、周期、批次、重复次数都取本节固定口径／原预算，不提供改预算、截历史、关闭校验或换policy的参数。新增输出目录不得等于旧证据目录。 `--mode/--source/--output`均必传、无隐含默认；`--formal-source`默认false，仅budget可设true，budget缺此标记或其他模式误带时拒绝。来源必须含有效manifest，OUT必须尚不存在；不持久化参数到env／Settings／数据库，生效范围仅本次验收进程，输出记录参数及来源SHA。

| 模式 | 调用与记录 | 判定 |
| --- | --- | --- |
| frozen | 校验源manifest，正式内核回放完整四周期；与冻结旧普通／TOP及B1底部逐项对照；75个前缀、边界／恢复及356组预测 | 所有语义断言通过；ID变化按原结构／事件键映射后核关联，不全局删掉关联字段了事 |
| api | 真实日线／分钟／预测Biz路由、query和Pydantic DTO；冻结源在隔离测试资源中装配；负向鉴权另覆盖 | 实际序列化响应断言底部关键字段与版本；fixture路由成绩不冒充正式源预算 |
| budget --formal-source | 正常配置只读session、正式完整源、真实路由与严格DTO；日线及三分钟每周期20冷＋20暖，共160次；另最新业务日期四请求 | 每次后端总耗时≤4s、预测模型≤200ms，不能只看平均／P95；请求超时保存失败阶段后停止门禁，不放宽预算 |
| 现有xxm_page_request_audit | 现有Python隔离真实路由／只读DB／正式Reader＋实际TS客户端／调度器，按下述函数级修订；无B1 CandidateCalculator或FastReader注入 | 两并发、16组整页／双标签原306请求全部无预算错误；新旧普通／TOP及预测对照，新增底部差异另解释；共享源复用及LRU总量不超预算 |

budget和既有mixed入口通过正常应用依赖取DB连接，先SET TRANSACTION READ ONLY，结束关闭会话；不装App lifespan／worker、不触发任务和写入。鉴权保留正常配置／现有授权会话，不读取其他进程密钥、不新建账号或改权限。若只能在隔离ASGI fixture注入测试身份，必须在报告注明并独立验证拒绝鉴权分支，不能称已通过现有受保护服务验收；正常访问条件不足的部分记为未验收，不能用B1直接服务包络替代。

已审计实际入口`xxm_page_request_audit.py/.mjs`及原混合验收记录（原记录：`reports/xxm_request_reuse_20261015/README.md`）。实际清单为：四行预测＋所选周期K线（日线一路、分钟价格／指标两路）＋日线及15／30／60／90／120六路九转＋所选周期XXM识别。日线每页12请求、分钟每页13请求；四周期×单／双标签×冷暖16组，总306请求。Python现有包装只做计数、只读会话、明确正式源装配和计时，并未注入研究FastReader；不能把它误认为旧临时prototype。带FastReader的旧reports/http_precheck.py继续冻结，禁止拿来当新正式验收。

对现有负载入口的计划修改限定为验收本身，命令仍只接受原`--output`，不改产品路由或CLI参数：

1. Python main的隔离app新增受原require_quote_access保护的`/__audit__/context`，在readonly_session中调用原MarketPageContextQuery.resolve_context，返回businessDate／generatedAt及新MAIN_SPEC版本／hash，不返回账号或密钥。每轮前后记录上下文；跨20点导致业务日期变化的轮次显式记为日期切换，不能把旧日期强行当READY。
2. `.mjs`去掉`const endDate="2026-10-14"`；每轮从上述真实上下文取日期，传入runTab作本轮endDate，原四行预测仍LATEST。期望computedThrough按本轮日期判断，来源未更新仍失败／DELAYED，不注入假行情或放宽20点规则。上下文／reset／metrics属于审计控制请求，不计入原306业务请求。
3. `.mjs`现有entry打包增加导出真实`xxm/adapter.ts:buildXxmViewModel`和`api/indexMinuteViewModelAdapter.ts:buildIndexMinuteChartViewModel`；API客户端、两个独立模块实例与调度器不替换。runTab取得values中chart和最后的layer，保存原始识别响应，断言版本／hash等于audit context并校验bottomHistories、关联与null策略。
4. 分钟图用真实buildIndexMinuteChartViewModel合并原bars／indicators，取其time／close／dif／dea／macd传给buildXxmViewModel并传真实indicatorVersion；日线从K线bars投影tradeDate、close、factors.macd三原值作相同对照。此处只投影测试所需原字段，不重算指标／历史事件，也不得用XXM响应本身伪造chart输入。其他DetailChartPoint展示字段不参与该适配器校验，不为测试修改生产Workspace。
5. 将真实adapter产出的markers和byTime明细序列化到新OUT，对照底部历史事件／关联；最新窗口没有底部事件时允许零marker，五处正观察另由api模式的历史窗口覆盖。预测96份响应继续保存并只排除声明过的身份差异作对照。
6. 原计数Reader、实际客户端取消／超时、两独立标签模块、每路完整读取次数、最大cache／compute及HTTP计时保持。新增上下文读取开销单列，不能把整页含排队时长误写成每HTTP4秒；保留所有慢样本与失败。

budget对当前真实源保留完整历史，不要求最新尾部行数仍等于10/13冻结文件；记录实际根数／through／指纹，已冻结重叠区逐值对账。若源修订改变重叠值须单列差异，不能硬改旧CSV或把有效新增行当错误；356组模型基准仍以冻结源重放为准。

冷指应用series／forecast缓存清空，保留OS与DB buffer cache；暖指同源重复，第一请求建缓存计入原统计，不删除慢样本。4秒从后端原load_entry开始计，覆盖源槽位排队、来源检查／全读、内核／底部账本、checkpoint、cache大小、DTO序列化；另记录HTTP全程（连接／鉴权等开销），不能混作模型耗时。模型200ms沿用forecast_query_service中原compute_start范围，包含calculator_at／投影校准／求解／文案；**完整历史的源加载／全量识别不冒充200ms预测模型**。前端队列调度保持，5秒客户端计时从实际发送开始。

响应≤2000根、识别≤1MiB／预测≤32KiB、共享LRU≤64MiB／16项、两槽位、1000根批次、完整源和全部校验不变；全历史新增记录及快照深拷贝／状态去重成本计入。B1的60分钟首冷3.895s余量很小，应保存冷读分阶段耗时；若正式新路径不达标，说明测量差异并回评审，不能截历史或把页面超时调大。

实施验收命令（均从仓库根运行，当前结果见§18）：

```sh
.venv/bin/python -m pytest scripts/research/index_market/tests/test_xxm_calculator.py scripts/research/index_market/tests/test_xxm_key_point_forecast.py scripts/research/index_market/tests/test_xxm_forecast_display.py tests/web/test_wealth_index_detail_xxm_api.py tests/web/test_wealth_index_detail_xxm_forecast_api.py tests/web/test_xxm_shared_loads.py
npm --prefix wealth run typecheck
npm --prefix wealth run test -- src/features/index-detail/xxm src/features/index-detail/xxm-forecast
npm --prefix wealth run build
.venv/bin/python -m scripts.research.index_market.xxm_page_request_audit --output reports/xxm_bottom_history_h1_page_<本轮唯一批次>
# 旧执行命令已移除；当前入口见 scripts/research/index_market/README.md
```

api／budget使用新runner，mixed使用既有入口；各自新OUT。两个正式源入口需正常访问权限，不在本次文档任务执行。页面仍由用户验收：7/23等绿字、原结构关联／低点和四周期技术面内容为核对点；不重新要求用户为自动化浏览器配置服务，不以截图代替API／算法验收。

### 17.12 编码顺序、门禁映射与停点

| 顺序 | 可Review成果 | 必须先通过 |
| --- | --- | --- |
| C0 本次文档 | 本节函数级方案、真实消费者、测试矩阵及审计报告 | 本轮只做文档／引用／保护哈希检查，未运行新产品代码 |
| C1 内核与回归 | types／Spec／calculator及T01—T06，单一h1内核 | 五处映射、严格边界／优先级、快照、旧普通／TOP；不接受只复制研究wrapper |
| C2 查询与合同 | SeriesEntry／过去投影／DTO及T07—T10，fixture同步 | 全量／增量／来源修订／过去请求、全部关联、真实路由关键字段；不能发布只有后端新字段而前端仍拒绝的半版本 |
| C3 预测与消费 | 同一内核克隆、严格adapter／底部详情及T11—T15 | 预测数学及文案不变、原视觉／取消／超时保持，两Workspace使用同一事实 |
| C4 完整技术验收 | T16及17.11各模式新证据，文档逐条对账 | 新正式接口四周期冷暖／并发／混合／双标签、4s／200ms及源保护；页面待用户验收单独列 |

这些为同一B组原子发布范围中的Review顺序，不是多套在线实现；C1／C2中间态不可作为交付。最终替换唯一Spec／内核及全部消费者，旧报告保留，不保留线上旧算法fallback。若需回退，整套代码／合同／前端版本一起回退并重建缓存，不进行新旧结果拼接。

§16.7门禁与代码级测试明确对应如下，不能只按列表位置猜映射：

| 原门禁 | 本节落点／测试 |
| --- | --- |
| B01 锁定原段低点 | 17.4.2；T01 |
| B02 原段结束后检查 | 17.4.1—17.4.2；T03 |
| B03 纯价格严格比较 | 17.4.2；T02 |
| B04 结束优先级及普通独立 | 17.4.1—17.4.2；T03—T04 |
| B05 关联及过去时点 | 17.5.2、17.6、17.8；T05、T08—T10、T13—T14 |
| B06 恢复与因果 | 17.4.3、17.5.1、17.7；T05—T07、T11 |
| B07 行为及预测不变 | 17.4.1、17.7；T04、T11—T12 |
| B08 正式负载与预算 | 17.11；T15—T16 |

§16完整通用交付矩阵仍适用：后端事实与合同见17.4—17.6，UI状态／显示见17.8，配置身份见17.3／16.6，排序／因果见17.5，性能／异常／可见结果见17.10—17.11；没有新增例外或省略项。旧矩阵“本节待审／用户确认前”指原§16评审阶段，已由B0确认；**本次§17已获用户确认并实施，实际验收与未完成项以§18为准**。

剩余未知仍是软件公式可信度边界：附加DIF门槛、精确零柱／OHLC依赖及软件寿命，并非本节隐含参数。A组同段重钝化以后若实施，必须重新审计其是否先结束同一历史记录，防止A／B重复消失；本轮不预先写等待分支或预测r1。发现源／方案冲突、普通或TOP变化、预测价格变化、预算失败，应保留证据并回评审，禁止日期补丁或降低校验。


## 18 B组h1实施对账（2026-10-16）

已完成§17的唯一内核及全链迁移；普通／TOP、预测数学、来源读取、业务日期及预算保持。原三处日线及两处120分钟软件映射已补齐，95条新增／328记录与B1一致；其余90条无软件真值。完整39747根、75个前缀恢复、356个预测全文对照通过；18个历史日线校准失败保护保持。后端209项、架构16项、前端全量1179项／165文件及类型／构建通过。

正式源160轮冷暖预测及160配对识别、另4次LATEST全通过，最大HTTP2.623秒，模型保守包络94.499ms；正式源当前至10/15，冻结重叠无差异。16组整页／双标签306请求全200，最大HTTP2.824秒、模型包络17.763ms、LRU最大42478077字节／8项。实际TS客户端／调度器、24份严格识别adapter明细、96份预测均保存，暖完整读为0，冷每分钟周期两流各一次。四秒／200ms与全部来源校验未放宽。

T01—T16对应代码及正反例、各模式新目录、正常鉴权及只读范围、两次脚本失败重跑记录、130份旧证据保护和未改边界见本轮实施报告（原记录：`reports/xxm_bottom_history_h1_implementation_20261016/README.md`）及execution／validation。验收脚本的startDate仍为必填，混合请求用1990-01-01＋原500上限覆盖实际图表，endDate来自每轮真实业务context；不改产品读取或日期。页面由用户自行验收。

## 19 密集标注与节点对应修复（2026-10-16）

用户已授权展示基准§10的局部修复。根因是`layoutXxmLabels`按pane高度无限扩展避让行，且`XxmMacdPrimitive.draw`没有连线；7/15及7/20取消文字因此远离真实事件点。CodeGraph explore／impact已核对几何→primitive及共享hook消费者，影响只限本前端图层；索引未识别的测试由当前`markerGeometry.test.ts`补核。没有算法、DTO、API、数据读取、预测或架构依赖变更。

现有视觉配置审计追加：`markerGeometry.ts.XXM_MARKER_STYLE`仍是唯一来源，无env、Settings、数据库或运营输入。新增`maxVerticalShift=40`、`maxHorizontalShift=48`、`horizontalStep=12`及`leaderWidth=1`，沿用点半径4、边距3、行高16、点字间隔8、行距18；消费者只为`layoutXxmLabels`和`XxmMacdPrimitive.draw`，随前端版本生效。它们是局部像素布局参数，不是识别门槛。

| 约束 | 代码级落点 | 验证 |
| --- | --- | --- |
| 有限近端避让，不能把文字推到pane远端 | `layoutXxmLabels`按同柱组的上下边界余量排序；枚举原位／上下20、40px及原侧0—48px水平位移，边界夹紧后以距离排序，过滤越界、文字和圆点冲突；同组仍顺序安排，结果恢复输入组顺序 | 截图四事件在114／114.5／115px pane全部保留原文字、无碰撞，位移不超限；普通左右边界、上下边界及极窄空间反例 |
| 同柱密集事件不跨日期合并，不改变点和详情 | 同柱不做额外水平分散；无空间仍回退原`+N`，单事件不改成`+1` | 同柱`+2`及全部原始点保留；不同日期四标签不合并，输入time／DIF／x／y不变 |
| 移位标签明确连回自己的节点 | `MarkerLabel`增加仅前端内部的可空`leader`及`via`折点；文字全部安排后，`routeLeader`枚举近端边缘起点、直线及横／纵绕行，选择不穿其他文字及圆点的最短路线，终点停在原圆点半径处；无路线时保留自身直连，不删除文字。`draw`先画线再画圆点／文字，沿用事件颜色、1px及pane clip | 各段端点／绕行、颜色／线宽、实际canvas调用；截图四事件无文字或圆点穿越；未移位无线，不能把线连到其他事件或改autoscale |
| 四周期同一实现 | 保持`useIndexXxmLayer`及日线／分钟Workspace消费者不变 | 真实API四周期响应驱动现有adapter和primitive，事件点逐一对应；完整Wealth测试、类型及构建；页面仍由用户复看 |

测试与技术绘制结果在本节追加，不覆盖§7.1或§18历史验收。用户当前授权只修标注，普通“取消”等原文案与识别事件均保持；不提交、推送或部署。

执行结果：几何10项、Wealth全量165文件／1183项、typecheck／build及文档完整性通过。复用本轮内核升级已保存的四周期真实API和严格adapter输出，完成24个尺寸场景及3个截图坐标场景的当前primitive绘制检查；全部圆点坐标／数量不变，截图四条文字完整保留，取消文字上下偏移由约38／56px缩为20／9.5px。引线路径不通过该截图中其他文字或圆点；同柱数量及极窄边界回归保持。受限空间下仍可只保留点和完整详情，不能宣称所有缩放下每条文字都有空间。

证据及命令见标注修复记录（原记录：`reports/xxm_label_alignment_20261016/README.md`）。本轮是离线真实响应重放，不是新实时API或浏览器验收：现有5175端口连接被拒绝，没有启动／重配服务；浏览器状态读取也被自动审批按用户自行验收的要求拒绝，没有绕过。CodeGraph开发后sync／status正常。页面由用户复看，算法及后端预算不受本次改动影响。

## 20 A组同段循环研究预检（2026-10-16，本节不批准产品编码）

用户已授权按“锁定案例→修订规则与LLD→离线预检→确认后编码”继续研究。§15是早期A组草案，须基于已落地h1修订；本节是本轮执行约束，结果另附，不将候选输出当作原软件公式或正式合同。

本轮只读封存源`reports/xxm_source_audit_20261013_213852`及7/10、7/13原图文、既有h1／B1报告；日线及60／90／120分钟完整39747根，不取未来值修正过去状态。原生产calculator、Spec、query、schema、forecast、Wealth代码和已有报告先记录SHA，结束逐字节核对；不操作浏览器、配置账号、读写数据库／Lake或启动服务。新离线脚本放`scripts/research/index_market/xxm/`，隔离测试放本主题`tests/`，结果写独立新报告目录且拒绝覆盖。

| 硬口径／候选 | 本轮研究落点 | 验证 |
| --- | --- | --- |
| 同段结构反向先消失，不能直接DULL | 基于当前h1的研究候选，仅替换BOTTOM dif_return分支；真实代码不变 | 7/10 15:00绿色、NONE及等待；无新DULL／CANCEL；7/9结构保留 |
| 保留原参照和最近价门槛，以当根价格重入 | 独立等待记录，冻结原结构关联、负柱段、reference与nearestPriceGate | 模拟3959.16为软件正样本；3960仅模型反例；7/13真实首根3934.74新激活，不用旧3952.4917低点自动代替当根条件 |
| 等待释放与同柱次序 | 参照严格突破、红柱／零柱结束等待；同柱只报消失，下一根起重入 | 严格等号、变色、DIF反例；无活动DULL时不伪造CANCEL；恢复／截断及原状态不可被假设计算修改 |
| 与已落地底部历史对接 | 同段消失关闭相应h1历史，另保留重新钝化参照；重入后新结构生成新历史 | 同一结构不得重复报A／B消失；逐项核五处软件映射，全部B差异列原因，不能强行保留95这个旧计数 |
| 预测先激活再结构 | 离线独立函数命名空间复用现有投影、区间数学及严格精度保护，clone保留候选等待状态；入口分区改用当根价格和固定参照 | 原356组抽查点与新增等待端点对照；完整解域切点和内核探针核对，等待不得READY；实际与模拟数据分开；7/13两个模拟结果对应 |
| 改动范围可解释 | 四周期完整新旧事件／状态差异；顶部全量语义不变、普通首次逻辑不改 | 新增、删除、改期／改类分别列账，不把全部与旧版一致作为成功；五处已确认修复保持 |

本轮参数审计：研究主门槛1%，敏感性0.75%／1.2%，仍来自现有不可变`XxmSpec.dif_turn_pct`，无新增env、Settings、数据库、前端开关或产品配置。候选研究标识与h1区分记录，不能用原h1版本宣称已上线新规则。原`max_refs=2`、`min_bars=2`、MACD(12,26,9)、源精度、端点／20点业务日期、预测20根最近有解时点及完整范围保持。新等待关系、历史关闭原因、as-of投影、事件关联和全部消费者的正式迁移待本轮结果确认后细化，旧§15版本号不直接用于发布。

验收分层：离线研究测试和封存全量回放可证明候选逻辑及样本相容；离线模型200ms实测只记实际范围和失败，不替代正式4秒源读取／并发预算。正式API、source/cache／DTO新增账本、过去请求、整页混合与多标签页仍须在产品实现前后分别过门禁。无软件真值的60分钟及其他新差异只算技术回归。精确门槛、收盘／最低价依赖、同柱极少例外仍未知；不会要求用户再找不存在的相邻点数截图。

### 20.1 执行结果：候选不通过，正式迁移暂停

研究代码已按脚本目录规则落入`xxm/same_segment_candidate.py`和`same_segment_precheck.py`，11项隔离测试通过；首次研究方法动态编译有缩进匹配错误，数据运行前已修正。它们只在独立函数命名空间复用当前h1／区间数学，未改变产品模块绑定；研究配置／代码哈希见新报告run.json。

三门槛四周期39747根全量回放完成；主参数72次新同段消失、52次重新激活，51个前缀／恢复截点通过，顶部信号关键语义保持，同一结构无A／B重复消失。356个旧预测点加70个新等待点共426组计算，原网格仅两处核心变化；当前封存数据模型包络最大约80.69ms，仍不包含正式读取／HTTP／schema／展示文案。没有执行新的正式4秒、混合／双标签或页面验收。

五处已核实软件观察只有4处保留，失败的是2024/8/22日线。原h1在8/14报DULL、8/15变色确认新结构，后者形成8/22历史消失的关联；草案8/14强制NONE＋等待，8/15红柱结束记录，故8/22整根无事件。这是执行链冲突，不是枚举改名或ID比对造成的假失败。主门槛下72次消失有58次当根已符合候选重入的价格和背离条件，不能把它们无差别强制等待；0.75%／1%／1.2%均未消除此反例。

因此20节表格中“当根只消失、下一根才重入”及“同段消失关闭历史后一定等待”的组合只保留为失败候选，不再作为正式编码硬口径。待核方向是按当根是否仍满足钝化条件分流；当根已满足时是否同时报消失、新DULL或者只显示新DULL，现有精确证据不足。本轮没有实现该替代规则，也不添加模糊兜底、第二在线引擎、日期过滤或新门槛。

原§15的DTO、RearmRecord、结束原因、预测版本均未生效。后续需先确认当根分支，再明确是否允许同柱多个事件、新旧结构身份与h1历史接替、严格snapshot／as-of投影、全部schema和Wealth消费者，更新函数级门禁后才能产品编码。研究中“一结构不重复消失”没有替代这些合同审计。

现有8/22原图黄／绿字辨认已请求用户确认；若不可辨，只需2024/8/14收盘上证日线覆盖8/12—8/15及当日相关讲稿。原产品及之前标注修复、封存源与旧证据180份SHA全部保持。两次新报告均保存：_01在软件观察断言处失败，_02只调整研究runner的结果收集并补完模拟，候选未变、退出码仍1。详见反例与逐根报告（原记录：`reports/xxm_same_segment_precheck_20261016_02/README.md`），不覆盖§18或原研究结论。

### 20.2 用户辨认后的条件分支预检

用户已确认8/22日线原图“两次紫色之间有黄色‘钝化’，没有绿色‘消失’”。据此修订离线假设，规则以算法方案§12.12为准；不把静态字序当成精确逐根软件游标。§20及§20.1的无条件等待是已失败历史，本节取代它作为本轮研究执行口径，尚非产品合同。

| 代码点 | 本轮候选变更 | 正反例／保护 |
| --- | --- | --- |
| `SameSegmentCandidate`隔离`step` | 仅在BOTTOM结构反向、当根不再满足钝化资格时改为STRUCTURE_DISAPPEARED＋NONE＋等待；资格满足则保留原DULL／dif_return，不添绿色 | 7/10不够格须等待；8/14够格应当根DULL；价格与DIF严格等号不得偷偷放宽 |
| `_qualifies_current_bar`与`_advance_rearm` | 共享负柱、min_bars、当根close＜原参照价和nearestPriceGate、段最低DIF＞原参照DIF的判定；进入等待后仍只在后来根重入 | 不因累计旧低点自动重入；不重新选参照；参照突破优先；红柱／零柱释放不伪报CANCEL |
| h1历史接替 | 够格的DULL走原`new_bottom_DULL`，不另补消失；不够格的结构消失才显式结束原记录并另存等待 | 原结构无A／B双消失；再次结构新身份；8/15—8/22历史链不丢 |
| 预测与恢复 | 使用相同候选clone及已有区间数学；真实DULL直接求结构，只有等待才先求重新钝化 | 四周期旧356点＋所有新等待端点；逐根／恢复一致、原状态不被模拟污染、保留日线精度失败 |
| 研究身份与范围 | 研究ID更新为`a-same-segment-h1-research-2`；1%主门槛及0.75%／1.2%仍取同一XxmSpec，无新配置来源 | 正式Spec／schema／API／Wealth不改；旧失败报告不覆盖；新run记录实际源码SHA |

新输出独立目录`reports/xxm_same_segment_precheck_20261016_03`，先记录这条人工观察，再运行全量、五处B保护和7/10／7/13模拟。结果未通过不得进入产品；通过也只表明现有材料相容，精确阈值、OHLC、历史寿命、其余无真值新差异仍单列。正式迁移必须另补字段白名单、历史as-of、状态缓存和全部消费者函数级对账及4秒／混合加载验收，不能借本次研究成绩省略。

执行已完成：_03新候选通过；随后_04候选保持，增加`audit_differences`逐事件因果追溯和每根`wave/history/TOP histories`相同断言。四周期39747根×三门槛全部通过；主参数14次同段消失／7次后来重入，五处B映射全保留，29删／21增均找到唯一等待或被移除后续结构。93条历史底部绿色较h1少2条，仅涉及未有软件真值的90分钟2022/3/7和2023/8/16，不是旧三处漏报复发。

45个前缀／恢复截点、369组预测（旧356＋新13）及四个独立模拟通过；最大离线模型包络79.99ms。旧网格只有120分钟7/10 READY→CONDITIONAL_ENTRY，日线8/15 CONFIRMED与18个旧校准失败保持。63项内核／预测／研究测试、281份SHA保护通过；详细逐条证据见本轮报告（原记录：`reports/xxm_same_segment_precheck_20261016_04/README.md`）。未做正式4秒源／HTTP、DTO、整页并发或页面验收，未修改产品依赖或合同。

本节把研究判定落实到隔离函数，不批准§15的旧DTO／版本直接编码。后续代码级LLD需将“够格直接DULL、无绿色”与“不够格消失＋等待”分别映射到产品step、历史结束原因、snapshot／cache、as-of响应、识别／预测schema及两类Wealth消费者，再提交确认。1%精确公式、OHLC、历史寿命、顶部疑报仍单列；无需为当前分流再找重复日线截图。

<a id="xxm-same-segment-a1-code-lld"></a>

## 21 A组产品代码级LLD：当根资格分流及全链迁移（2026-10-16，已确认并实施）

### 21.1 目标、依据与开发准备度

用户要求补齐代码级LLD并审计能否开发。本节是A组产品实施的唯一代码级入口，**替代§15的失败草案及旧版本／字段示例**；§17—§18仍是已实施B组的历史约束，不批准修改本节排除项。规则唯一依据为算法方案§12.12和用户对8/22原图的辨认；研究候选2及四周期完整证据见预检报告（原记录：`reports/xxm_same_segment_precheck_20261016_04/README.md`）。该句原为LLD审计时点；用户随后确认并授权实施，结果见§22。

**审计结论：已具备按本节有限范围进入开发的技术条件，用户确认本节后可开工。** 研究已经解决“当根够格是否也强制等待”的反例，不需要再找重复截图。进入开发不等于所有软件公式已明确，也不等于正式4秒／DTO／整页验收通过。1%仍为原工作参数；OHLC依赖、原软件历史寿命、两处无软件真值的90分钟历史差异及顶部9/24—9/25疑报继续单列，不顺手修正。

审计使用CodeGraph explore／impact（XxmCalculator深度2，80个相关符号含研究和测试），再核当前源码补足：App动态分钟路由、两个图表入口、严格TS白名单及研究脚本的h1源码依赖。查询和测试消费关系已明确，无新增架构边界；Biz复用Foundation，Wealth经HTTP，不引入QTF／Ops依赖。

本节路径缩写：S=`src/biz/services/wealth/market/index_detail_xxm/`；Q=`src/biz/queries/wealth/market/index_detail_xxm/`；D=`src/biz/schemas/wealth/market/`；W=`wealth/src/features/index-detail/`；R=`scripts/research/index_market/`。

### 21.2 硬口径与文件计划

| ID／硬口径 | 具体落点 | 必须验证的反例 |
| --- | --- | --- |
| A01 当根够格直接钝化，无新绿色 | S/calculator.step及共享资格函数 | 8/14再次DULL，8/15新结构、8/22历史消失保留；不能一律NONE |
| A02 当根不够格才消失并等待 | step、独立等待记录；_advance_bottom_history关闭同一原结构 | 7/10收3996.1616不能用旧最低收盘直接报DULL；不得同一结构A／B各报一次绿色 |
| A03 固定原参照、用后来当根收盘重入 | _advance_rearm、snapshot、forecast_entry | 3959.16可重入、3960只作模型反例；等价低点不要求再破原最低收盘，价格／DIF等号不得激活 |
| A04 等待结束不冒充钝化失效 | _end_rearm；首根参照突破阻止同柱重选 | 等待中DIF突破、红柱／零柱均留结束原因，不伪造CANCEL或结构确认 |
| A05 普通首次、TOP及B组既定规则保持 | 既有选峰／TOP代码；新DULL继续按E1接替历史 | 三门槛完整回放、选峰池／TOP历史逐根不变、五处B映射全保留 |
| A06 响应截至请求端点，关联能解析 | Q账本／投影、D、W/xxm adapter | 窗口外原结构、过去等待记录、单柱结束窗口；不泄漏未来结束，不接受悬空ID |
| A07 预测和图层共用唯一真实内核 | S/forecast_*、Q/forecast_query_service、两DTO／adapter | 等待不得READY／CONFIRMED；当前钝化不得继续带等待context；不得由前端猜参照 |
| A08 唯一新版合同一次迁移 | Spec、hash、cache、schema／TS类型／fixture | 旧h1快照和旧版本响应拒绝；不补默认字段混用旧合同 |
| A09 四周期、完整输入及原预算 | 原source／runtime／scheduler不改 | 20点／跨日端点、完整历史与错误拒绝；200ms模型、4秒及响应／内存上限不放宽 |
| A10 研究退场且证据可追溯 | R/xxm与主题测试／README | 升级step后不得残留依赖旧源码片段的活跃入口；不删证据或引入第二在线内核 |

| 文件／现有符号 | 拟改内容 | 直接消费者 |
| --- | --- | --- |
| S/types.py：XxmStep、XxmBottomHistory | 新XxmRearmRecord内部类型，新增必传rearm_records；底部结束原因增加structure_disappeared | calculator、Q、正式验收runner |
| S/spec.py：XxmSpec／MAIN_SPEC | 新算法版本和一个不可变同段策略标识；原数值参数不改 | ID、snapshot、两级cache、两schema及TS版本 |
| S/calculator.py：__init__／step／_advance_bottom_history／snapshot／restore | 新pending_rearm、四个生命周期helper及严格恢复校验，见21.4—21.5 | 识别、calculator_at、forecast_detector.clone |
| Q/query_service.py：SeriesEntry、_load_series、_response | rearm_records账本；全部新建／增量复制点迁移；新增等待投影及窗口选择，B记录补等待关联 | 日线／分钟识别、预测真实前缀 |
| D/index_detail_xxm.py | XxmRearmRecordDto；point／event／response字段及双向关联校验 | 两识别路由、forecast DTO共用等待类型 |
| S/forecast_detector.py | clone完整恢复；activation_signature按实际等待状态接受reactivation | entry、joint／主求解器 |
| S/forecast_entry.py | 固定参照切点、当根价格整段证明、失败原因和入口保护，见21.7 | forecast.solve_entry_ranges |
| S/forecast.py／forecast_joint.py | 实施时核共用克隆、原P—C几何与survival语义；不新增第二数学模型 | Q预测、完整域回放 |
| S/forecast_spec.py、forecast_text.py | 新预测版本；等待文案和原近期筛选共存，不改60样本／95分位 | 预测DTO、技术面四行 |
| Q/forecast_query_service.py：build | 截至时点等待context、当前结构关联、payload身份与后端display | 预测API及缓存 |
| D/index_detail_xxm_forecast.py | 新必有可空rearmContext、唯一版本及状态／参照组合校验 | adaptForecast |
| W/xxm/types.ts、adapter.ts、XxmLayerUi.tsx、XxmMacdPrimitive.ts | 等待类型与明细；A事件关联、绿色“消失”、等待不能显示成钝化 | 日线及分钟共同图层 |
| 新W/xxm/rearmContract.ts | 只做共享等待记录结构／时间校验，不计算信号；供两adapter复用 | XXM和预测adapter，无反向循环import |
| W/xxm-forecast/types.ts、adapter.ts | 引用同一等待类型；rootKeys、版本及状态关联同步 | fetchForecast、hook、卡片 |
| 现有Python／TS测试和fixture | 新字段必传、正反例迁入正式测试，旧普通总数断言按新语义拆分 | T01—T15及21.11门禁 |
| R/xxm：acceptance、bottom_history_acceptance、same_segment_*；R/README | 既有收集器接新字段；封存临时候选、将runner迁为正式同段验收入口，见21.10 | 不成为产品依赖 |

已审计、默认不改行为：三个Biz路由、App/api/v1/router.py、Q/source.py／shared_loads.py、S/runtime.py／projection.py／forecast_math.py、W两API client／两hook／请求scheduler、IndexChartWorkspace／IndexMinuteChartWorkspace／IndexDetailPage及XxmForecastCard。除后文明确的签名接线与fixture更新，不改URL、请求参数、鉴权、分钟开放门禁、源查询、4秒、20点、调度、布局、markerGeometry或此前标注避让修复。不新增配置中心、数据库表、迁移、依赖或来源写入。

### 21.3 新记录与对外合同

内部仅新增`pending_rearm: XxmRearmRecord | None`；**不再增加一份长期active_structure_id**。创建等待时从当前pending_bottom_history复制原结构身份，随后关闭该历史；不必把研究候选为挂接h1而设的私有字段全部搬进产品。

| 字段 | 内部记录／对外DTO | 约束 |
| --- | --- | --- |
| id | 两者同名 | `_id("rearm", structureEventId, disappearedAt)`；沿用现有版本／Spec／对象／周期身份 |
| direction | 两者同名，固定BOTTOM | 不接受TOP等待 |
| bottomHistoryId／structureEventId | 两者同名 | 指向被本次A事件结束的B记录和原紫色事件，禁止塞入relatedTopHistoryId |
| structureConfirmedAt／structureRoute | 两者同名 | 原结构确认时间；本轮同负柱段来源只允许dif_turn，不能把变色确认结构伪作同段活动结构 |
| segmentStart | 两者同名 | 原负柱段起点，不重切真实柱段 |
| nearestPriceGate | 两者同名，有限正数 | 创建时保存`history[-1][-1].price`，之后不随新假设重选 |
| referenceWave | **仅内部／snapshot** | 原Wave的8字段完整深拷贝；恢复活动参照不能丢count／极值时间 |
| reference | **仅对外DTO** | 由referenceWave明确投影成现有startTime／endTime／price／dif四字段；DTO拒绝referenceWave泄漏 |
| disappearedAt／observedThrough | 两者同名 | 原结构确认＜消失≤观察；只观察至真实请求端点 |
| status | 两者同名 | WAITING、REACTIVATED、INVALIDATED、SEGMENT_ENDED |
| endedAt／endReason | 两者同名 | WAITING均null；其余精确配对price_requalified、reference_dif_break、color_flip／zero |

内部类型保留referenceWave，对外只在Q的投影helper生成reference；不在内核重复保存两份可漂移参照。没有额外公共“临时原始字段”或字段别名。每周期至多一个活动等待，已结束记录归调用方账本。

同时一次迁移以下字段，均**必有，不靠默认空值兼容旧响应**：

| 对象 | 变化 |
| --- | --- |
| XxmStep | 新`rearm_records: tuple[XxmRearmRecord, ...]`，返回本根新建／观察／结束副本；无变化为显式空tuple |
| XxmPoint／XxmPointDto／TS XxmPoint | 新pendingRearmId：string或null；非空只允许NONE、方向及activeReference为空、pendingBottomHistoryId为空 |
| XxmEvent／DTO／TS | 新type STRUCTURE_DISAPPEARED，route增加reactivation，新relatedRearmId必有可空；原type／route不改名 |
| BottomHistory | endReason增加structure_disappeared；这种结束只能在原负柱段内，leftOriginAt必须null |
| XxmResponse | 新rearmRecords数组；EMPTY必须为空，记录标识与TOP／BOTTOM／事件集合不碰撞 |
| XxmDetail | 新rearmRecords数组，供tooltip展示；只绑定后端给定的point／event关系 |
| ForecastResponse | 新rearmContext：XxmRearmRecordDto或null，只有真实端点WAITING的公开投影；不包含已结束记录或referenceWave |

### 21.4 calculator.step的唯一执行顺序

新helper拟定签名；函数位于现有calculator.py，不复制整套引擎：

```python
_qualifies_bottom_close(self, bar: XxmBar, reference: Wave, nearest_price: float) -> bool
_start_rearm(self, bar: XxmBar, reference: Wave, original: XxmBottomHistory) -> XxmRearmRecord
_end_rearm(self, bar: XxmBar, status: str, reason: str) -> XxmRearmRecord
_advance_rearm(self, bar: XxmBar) -> tuple[bool, Wave | None, tuple[XxmRearmRecord, ...]]
# bool：本根是否阻止普通首次判断；Wave非空：本根成功重入，用于生成DULL/reactivation。
```

`_qualifies_bottom_close`只判断：hist＜0、wave.sign=-1、count≥原min_bars、**bar.close**＜min(reference.price, nearest_price)、wave.dif＞reference.dif。无epsilon、整数近似、旧累计最低价代入、重新选峰或最低价输入。

1. 沿用输入校验、变色分段、历史池更新和当根极值更新。活动DULL原变色确认／取消照旧；等待时state/reference本来为空，不会借旧参照报变色结构。
2. 若原先有等待，先执行_advance_rearm。红柱／零柱或原段结束：记录SEGMENT_ENDED并释放，不伪造CANCEL；同柱普通规则可继续。原段内先阻止普通首次选择，再检查当根DIF＜保存参照DIF：INVALIDATED并释放，**本根仍阻止重选**。等号不失效，但段DIF等号也不得重入。
3. 原等待仍有效，且本柱晚于disappearedAt、共享资格通过：恢复原完整Wave参照，报DULL/reactivation；记录REACTIVATED并结束。本根不得立即确认结构。未通过则只更新观察副本，仍NONE。
4. 没有等待干预时，先执行原活动参照严格DIF突破规则。真正突破仍CANCEL，优先于结构反向；不创建等待。
5. 底部STRUCTURE同段DIF反向达到原门槛时，使用共享资格分流：够格→原DULL/dif_return，无等待／绿色；不够格→从当前未离段B记录复制等待，报STRUCTURE_DISAPPEARED/dif_return，state=NONE、reference=null。原结构记录缺失／参照不一致应失败，不能补造历史。TOP反向仍走原DULL/dif_return。
6. 其他普通规则、首次激活及TOP跟踪保持。A事件和h1的_advance_bottom_history衔接：A绿显式结束同一B记录，reason=structure_disappeared；不再由它报B绿。直接DULL和后来reactivation仍按既有new_bottom_DULL接替规则处理；新的STRUCTURE再建立独立B身份。
7. 生成point时写真实pendingRearmId，所有事件显式补relatedRearmId。结束记录以深拷贝放入XxmStep，更新previous／processed；不得留下跨step隐式的last_rearm_changes作为产品合同。

普通事件关联矩阵：

| 事件 | relatedBottomHistoryId | relatedRearmId | 当根输出状态 |
| --- | --- | --- | --- |
| 够格DULL/dif_return | null | null | DULL |
| STRUCTURE_DISAPPEARED/dif_return | 被结束的原B记录ID | 新等待ID | NONE，pendingRearmId=新等待ID |
| DULL/reactivation | null | 被结束的等待ID | DULL，pendingRearmId=null |
| 新BOTTOM STRUCTURE | 新B记录ID | null | 按原dif_turn／color_flip状态规则 |
| B历史价格消失 | 原B记录ID | null | 不改普通状态 |
| 其他原事件／TOP | 保留既定方向关联 | null | 原规则 |

等待参照突破只结束等待，不新增CANCEL；没有活动钝化就不能报告“钝化取消”。“最早下一根重入”仅约束已经进入等待的分支，不能再把8/14这类当根够格情况强制等待。每根至多一个普通事件，独立TOP历史仍可共存；保留原事件，不移动紫色的日期或删除历史。

### 21.5 snapshot／restore与因果性

snapshot增加必有可空`pendingRearm`，使用内部完整记录；所有可变嵌套对象深拷贝。现有pendingBottomHistory等字段继续保留。forecast_detector.clone和SeriesEntry.calculator_at继续构造同一XxmCalculator／同一Spec再restore，不导入研究候选。

新增`_validate_rearm_snapshot(raw, *, previous, wave, state, reference, bottom_history, processed, history)`。history为恢复时已解析的局部原参照池。先把所有字段解析到局部变量，全部通过后才发布到self，包括在已有实例上回退到旧真实前缀。至少校验：

- 键集合精确匹配内部TypedDict，referenceWave八字段完整、有限值／正价／合法sign、严格整数count及各时间关系；不得接受公共reference代替完整Wave。
- 仅WAITING可出现在活动snapshot；结束字段为空，观察时间等于previous.time；previous／processed一致，state=NONE、reference=null、bottom_history=null、wave.sign=-1且segmentStart=wave.start。
- referenceWave来自保存的原负柱参照，end早于segmentStart；与该snapshot历史池的原参照一致，nearestPriceGate与该段最近参照价一致。当前wave.dif允许等于、不得严格低于原参照；等号不表示可重入。
- segmentStart≤structureConfirmedAt＜disappearedAt≤observedThrough；原结构route=dif_turn。structureEventId、bottomHistoryId、rearm.id均按同一新版_id参数重建核对，不用窗口可见事件猜关联。
- 旧Spec／来源／对象／周期、未知键、伪结束记录、未来参照、等待与活动结构并存全部拒绝；失败不污染原对象，clone不共享引用。

直接够格回DULL时pendingRearm始终null，原B结束原因仍new_bottom_DULL；下一次结构重新建记录。研究测试中通过手工拼state却没有原结构记录的fixture，应改为合法前缀，不能为测试放松产品不变量。

### 21.6 SeriesEntry、窗口与严格DTO

SeriesEntry新增`rearm_records: dict[str, XxmRearmRecord]`。_load_series中首次重建设空dict；增量复制时复制账本容器，记录值只接收step返回的独立副本，不原地修改旧entry。逐根upsert，1000根checkpoint自动带等待。_deep_size已支持dataclass／dict，新增内容进入原64MiB／16项共同LRU；不新开不计费缓存。历史数据修订继续整段重建，源／Spec身份变化不能接旧等待；指纹算法不改。

新增纯投影helper：

```python
_project_rearm_record(record: dict, *, through: str) -> dict | None
_rearm_records_for_response(entry, *, points, events, first, last, through, check) -> list[dict]
```

公开投影在创建时间晚于through时返回None；结束晚于through时改为WAITING／null结束字段；observedThrough=已到达的endedAt或through。referenceWave投影为四字段reference，其余冻结字段不重算。窗口选择包含：point.pendingRearmId、event.relatedRearmId引用的记录；以及创建不晚于窗口末、生命区间与窗口相交的记录。按(disappearedAt,id)稳定排序，最多一个截至through的WAITING；没有points时返回空集合。

_response先选择／投影等待记录，再把其中bottomHistoryId传给_bottom_histories_for_response，使**原结构在窗口外也有B记录可核对**。不扩展返回全部旧K线／旧事件，记录自带结构时间与ID。过去请求必须从同一截止点投影，而不是直接返回最终ENDED状态；已有BOTTOM投影也须遮掉截止点之后的leftOriginAt／ending。

D/XxmResponseDto新增一致性断言，W完整API窗口亦验证，不能只检查图上当前已加载的分钟点：

- 新必有字段缺失、未知枚举、重复／碰撞ID、非法时间／非有限数、EMPTY带记录均拒绝；现有source／点值对齐保持。
- point.pendingRearmId指向记录时，disappearedAt≤point.time，且结束存在则point.time＜endedAt；等待point的state／活动参照／底部pending组合符合21.3。不能只要求最终record.status=WAITING，否则会拒绝合法旧点。
- A绿必须BOTTOM、fromState=STRUCTURE、route=dif_return；两个关联ID均能解析，B记录结束原因／时间=structure_disappeared／事件时间，leftOriginAt=null；两份参照与原结构身份相同。
- reactivation必须BOTTOM、fromState=NONE、DULL；等待record结束原因／时间=price_requalified／本事件时间，事件参照等于record.reference；同一等待不能多次结束。同根点为DULL且pendingRearmId=null。
- 够格dif_return不能携等待关联或A绿；TOP、普通首次、B历史价格绿等其他事件relatedRearmId必须null。visible原紫色存在时做双向核验；不可见时用记录冻结身份核对，不制造伪事件。
- B的structure_disappeared结束和等待的disappearedAt／bottomHistoryId一一对应；窗口选中B结束时也须选中对应等待，防单向悬空。相同原结构不得再出现B价格绿。

tooltip的“当柱待重新钝化”仅来自该点pendingRearmId这一后端事实。记录最终状态另注明“记录截至／结束时间”，不能用后续ENDED状态改写旧点的当柱判断；不在前端重新按价格推导钝化。

### 21.7 技术面预测：真实状态、完整域与文字

**Q/forecast_query_service.build。** 从`entry.points[n-1]`的pendingRearmId取得账本，复用公开投影helper按computedThrough产生context；不为拿context对全历史额外重放。仅dataStatus=READY且真实NONE＋等待时携带，包含PRECISION_PENDING／NO_CANDIDATE等尚无范围结果；READY预测（真实DULL）、CONFIRMED、EMPTY、DELAYED一律null。context加入payload后再计算forecastId；不从假设副本生成真实context。

新增`_active_confirmation(entry, count, check)`只负责核对当前结构身份：当根确有STRUCTURE事件可直接使用，包括变色后ordinaryState=NONE；否则ordinaryState=STRUCTURE时，以当点pendingTopHistoryId／pendingBottomHistoryId、方向核对原STRUCTURE。不能拿最近任意历史紫色覆盖当前NONE＋等待。合法CONFIRMED继续跳过未来投影校准；缺失应有关联视为合同错误，不静默挑另一结构。

**数学函数逐项迁移：**

| 当前函数 | 新分支／保持项 |
| --- | --- |
| forecast_detector.clone | 完整复制pendingRearm，继续唯一产品类；不得仅复制ordinaryState/reference |
| activation_signature | 有真实等待时只接受DULL/reactivation，否则只接受DULL/activation；所有来源取整分支必须同一参照，保留PRECISION_UNRESOLVED |
| forecast_entry.entry_partition | 保留原完整切点，并加入等待reference.price、nearestPriceGate、原DIF界限对应的仿射根／日线±0.0005／GUARD与浮点误差包络；切点仍覆盖正价格全域，不做价格网格代替证明 |
| stable_reference_on_band | 等待固定唯一参照；以区间**当根收盘上界**严格小于两价门槛、min(真实wave.dif,投影DIF保守下界)＞原DIF、负柱／min_bars证明；不采用累计旧低点满足价格条件 |
| reason_for | 等待先判变色／零柱、根数，再判整个段DIF严格背离，最后价格；原因仍用既有WRONG_COLOR_OR_ZERO／INSUFFICIENT_BARS／DIF_NOT_DIVERGENT／PRICE_NOT_EXTREME，不新增无来源错误码 |
| solve_entry_ranges／forecast入口 | 等待有自己的固定参照，不因首次选择路径重选历史；无等待的首次逻辑不改；等待仍属于NONE条件预测而非READY |
| forecast_joint：build_relation／domains_for_target／close_bounds等 | 复用原P—C几何和目标确认门槛；P的资格由新entryRange证明，P后必须DULL存续；若需改数学规则而非接线，停下评审 |
| confirmed_options／forecast中间存续 | 实际clone逐根核对参照与DULL，出现取消／提前结构／变色／零柱等按既有规则排除；等待释放不能在同一关系里切到另一参照 |

未来P为最近一个端点的假设收盘，C为随后最早可形成结构的目标端点；P—C中间按原entry_range_then_flat。重新钝化和形成结构至少相隔一根，最多搜索20根，只返回最近一个有解时点。原完整域、开放／闭合边界、精度保护及200ms预算不改；3959／3892／3944不是常量，更不能把不失效点位写成结构成立价。

D/ForecastResponseDto和W/adaptForecast同轮增加rearmContext与严格根键白名单：context须WAITING／BOTTOM、截止真实computedThrough、普通NONE、数据READY；activation.ranges、relations、commonConditions内出现的参照均等于该固定参照。若有解但引用其他峰、context在READY／CONFIRMED／源未就绪中出现、缺必有null字段或内部referenceWave泄漏均拒绝。无范围和精度保护结果可以保留真实等待context，但不能假造日期或点位。

S/forecast_text.make_display在原四个display字段中分流，不改变卡片结构或让前端拼文案：

- 等待且有近期条件：状态“待重新钝化”；先说明“原底部结构已消失”，再按解域给“重新钝化条件／未触发／推算失效／后续结构条件”。时间、区间均取真实求解及既有格式化。
- 等待但近期无可展示解：仍说明当前在等待，只给暂无近期重新钝化条件／新收盘后更新；不得写“当前底钝化有效”。PRECISION_PENDING仍保留精度状态，不伪造确定点位。
- 实际DULL：保留当前钝化有效、结构成立条件；context=null。实际新结构：CONFIRMED核对本次真实身份。源未就绪：原EMPTY／DELAYED，不借旧context显示新预测。

build_display_context／reference_band／select_display保留最近60个同跨度样本绝对涨跌幅95分位、完整触发／未触发／失效域及远端边界省略规则；不截断数学域、不添加评分。display、applicabilityText与invalidationText对等待使用“原结构消失／参照仍待重新满足”的口径，避免将结构消失写成钝化失效。

### 21.8 版本、配置审计与全部消费者

| 名称／拟定值 | 来源、持久化及消费者 | 生效与拒绝 |
| --- | --- | --- |
| algorithm_version=`xxm-direction-v0.1-a1` | S/spec.py的不可变默认；ID／snapshot、SeriesEntry／共享加载key、识别DTO／TS adapter、验收 | 随同一代码包生效；新Spec自然作废h1状态，旧snapshot拒绝，不做默认填字段 |
| same_segment_bottom_policy=`current_close_rearm_v1` | 新增XxmSpec固定策略标识，进入asdict/hash和既有不可变校验；只供内核身份／审计 | 无env／Settings／数据库／运营输入；仅此一个值，非可切换策略 |
| forecast_version=`xxm-key-point-forecast-v0.2-a1` | S/forecast_spec.py默认；Q预测key、D Literal、W类型／adapter／fixture | 与检测器同轮生效，旧v0.2响应拒绝 |
| dif_turn_pct=1%，离线0.75%／1.2% | 原Spec不变；既有转向及本轮分流共用 | 不新增第二消失阈值，不按日期调参 |
| 原预算／显示参数 | BUDGET、FORECAST_SPEC、原scheduler／client；无新持久化来源 | 4秒、200ms、64MiB／16项、1000根批次、1MiB识别／32KiB预测、前端5秒及60样本／95分位保持 |

当前h1运行hash为b2ebada1a7ef0f013cf2b9a447a6a9fee8c73ac660c3fee41a9be13e3ca290e5；a1 hash在字段和值冻结后由原算法生成并记录，不现在手写猜测。TS继续校验版本和hash格式，不把一份后端hash散落为多处配置。新旧版本不能共存在线返回；回滚需整套代码／合同版本回退并丢弃不匹配cache，不保留运行期旧算法分支。

全部实现／消费者包括：S/types／calculator／Spec；Q/SeriesEntry的首次构造／增量复制／replace发布三条路径、calculator_at、识别／预测build；D两schema和三条真实Biz路由；S detector／entry／joint／forecast／text；W两types／adapter、两个apiClient、两个hook、XxmLayerUi／primitive／ForecastCard、日线／分钟Workspace、IndexDetailPage、fixture与Python／TS回归。apiClient／hook／Workspace默认无需行为修改，但必须用新响应验收，不因文件不改就跳过消费者。

W/rearmContract.ts只共用结构校验；W/xxm-forecast/types.ts引用同一XxmRearmRecord类型，不复制近似类型。XxmMacdPrimitive.color将A事件映射到现有绿色；eventLabel输出“底部结构消失”，eventMarkerLabel输出“消失”；取消继续按当前既有文案。既有点大小、加粗、左置／引导线／密集避让与轴域不改。useIndexXxmLayer已有版本验证失败重取逻辑，useXxmForecast按周期／日期隔离，均不添加隐藏缓存或请求并发。

### 21.9 核心测试case与字段断言

| 测试ID | 落点／核心case | 正向与必须拒绝的反例 |
| --- | --- | --- |
| T01 | R/tests/test_xxm_calculator.py：7/10和8/14分流 | 不够格→A绿／NONE／等待；够格→DULL无绿／无等待；8/15新结构及8/22B绿保留 |
| T02 | 同文件：共享资格、三既有门槛 | 当前价等于任一门槛不重入、段DIF等号不重入、严格突破先取消；旧最低价不能代当前价，原min_bars不放宽 |
| T03 | 同文件：等待全生命周期 | 重入／突破／红／零及连续循环；无活动DULL不报CANCEL；新STRUCTURE另建B；同原结构不重复A／B绿 |
| T04 | 同文件：快照恢复 | 等待前／中／重入后与完整前缀一致、回退原子／深拷贝；坏键／错ID／旧Spec／未来时间／伪结束均拒绝 |
| T05 | tests/web/test_wealth_index_detail_xxm_api.py | 新账本增量复制、源修订重建、1000根checkpoint／回收后恢复；单柱原结构在窗口外关联可解 |
| T06 | 同文件：过去窗口及严格DTO | 结束在未来应投影WAITING；旧点pendingID能引用截至响应已结束的记录；反向关联、EMPTY、缺字段、错误方向／枚举、同结构双绿拒绝 |
| T07 | R/tests/test_xxm_key_point_forecast.py | 等待完整激活／排除域，根及一ULP两侧、P—C／共同充分区间独立clone核对；不得换峰或把旧累计价当新收盘 |
| T08 | 同文件：已有软件模拟及时间 | 3959.16重入、3892.79失效、3944.79保留；3960仅模型反例；真实／模拟分别建副本；最近端点与四周期不混用 |
| T09 | tests/web/test_wealth_index_detail_xxm_forecast_api.py | 真路由→真实query／calc→DTO：等待不是READY／CONFIRMED；rearmContext及参照一致；真实DULL清context、真实变色STRUCTURE可CONFIRMED；坏context组合拒绝 |
| T10 | 同文件及R/tests/test_xxm_forecast_display.py | 7/10只有“先重入后结构”；8/15仍CONFIRMED；原18个日线校准失败、远端筛选及近期三类条件保持；无解不造点位 |
| T11 | W/xxm/adapter.test.tsx／新增rearmContract.test.ts／fixture | 四周期新响应、完整窗口先校验、坏关联拒绝；A绿是“消失”，等待无黄点；tooltip当柱与记录截止分开 |
| T12 | W/xxm/markerGeometry.test.ts、useIndexXxmLayer.test.tsx | A绿也用现有大点／粗字／左置／引导线，密集标签锚点不漂；坏版本／错数据→error、不显示旧钝化 |
| T13 | W/xxm-forecast/forecast.test.tsx、apiClient.test.ts | 新真实响应驱动四行；未知键／旧版本／错误context拒绝；loading／ready／error、切周期日期／隐藏／重试／过期响应不串行 |
| T14 | tests/web/test_xxm_shared_loads.py及原调度器测试 | 同周期多消费者共享真实加载；不同源／日期／Spec不合并；等待超时不取消leader；总并发、取消与重试不改 |
| T15 | 正式验收runner及现有xxm_page_request_audit.py／.mjs | 新旧逐事件关联、冻结差异可解释；四周期4秒／200ms、整页混合和双标签；保留所有源错误拒绝 |

核心识别API字段清单：algorithmVersion／specHash、source.inputId／computedThrough、point三种状态与pendingRearmId、A事件type／route／fromState／eventReference／两关联ID、B的structureEventId／endReason、rearmRecords全部公开字段。预测清单：forecastVersion／两Spec hash、computedThrough／ordinaryState／status、rearmContext、activation完整域、targetEndpoint／barsAhead、relations／commonConditions、display四字段；异常仍用原XXM／XXMF登记码。

例示响应片段（ID为占位，实际fixture从正式路由生成，不手填伪hash）：

```json
{
  "point": {"time":"2026-07-10T15:00:00+08:00","ordinaryState":"NONE","ordinaryDirection":null,"activeReference":null,"pendingBottomHistoryId":null,"pendingRearmId":"<rearm-id>"},
  "event": {"type":"STRUCTURE_DISAPPEARED","route":"dif_return","direction":"BOTTOM","fromState":"STRUCTURE","relatedBottomHistoryId":"<original-bottom-history-id>","relatedRearmId":"<rearm-id>"},
  "forecast": {"ordinaryState":"NONE","status":"CONDITIONAL_ENTRY","targetEndpoint":"2026-07-13T15:00:00+08:00","rearmContext":{"id":"<rearm-id>","status":"WAITING"}}
}
```

这是便于阅读的局部片段，不是可直接提交DTO的完整payload；完整字段以21.3为准。实施时从真实路由对固定封存案例导出识别与预测JSON，经两DTO校验、写入新交付目录，并让TS adapter／组件测试读取这些原响应；不用手写mock假装真实API联通。

### 21.10 研究封存、旧测试迁移及证据对账

当前SameSegmentCandidate._isolated_step按h1源码片段精确编译；新step一旦迁移，它会在import时失败，不能留在默认主题测试中。该临时注入方法只用于研究，**禁止搬进产品**。

1. 产品修改前在本次新的a1实施报告目录封存三份研究源码（same_segment_candidate.py、same_segment_precheck.py、test_xxm_same_segment_research.py）及将被改写的calculator／forecast测试原文，为ZIP及逐文件SHA；记录h1依赖源码SHA／Git基线、_04输入与结果SHA。旧_01—_04报告不改；旧复现需按manifest恢复原h1依赖，不能声称升级后的当前环境仍能直接执行旧命令。ZIP仅作历史证据，不成为产品或默认测试依赖。
2. 从现有17项研究测试中，将规则／恢复正反例迁入正式calculator／forecast测试；仅证明独立研究命名空间绑定的临时用例随候选清退，正式测试不再import候选。研究runner迁名为R/xxm/same_segment_acceptance.py，直接使用产品类，读取_04冻结输出对账，不动态替换源码。清退原候选及旧runner入口，引用审计覆盖import、测试发现和主题README，不保留转发入口。
3. R/xxm/acceptance.py收集新账本；bottom_history_acceptance的frozen_mode等原“普通全相等”断言须拆成TOP／选峰不变、B五处保护及已登记A差异，不靠删除反例使测试变绿。其API／budget模式继续复用真实读取和两流校验；原B1／h1报告与成绩不覆盖，不按旧95条总数强保新信号。
4. 原test_entire_frozen_ordinary_and_historical_baseline中“所有普通状态／事件及计数等于旧内核”不再是A组可用验收条件。保留旧输入／TOP历史／首次资格测试，将会变化的BOTTOM部分改为与_04逐事件语义及因果差异对账。旧测试完整源码随本轮前置封存保存，不重写历史manifest。
5. a1身份与研究v2不同，按周期／时点／类型／route／参照及原结构锚点比较，再核新ID双向关联；允许新增元数据，不允许靠忽略参照或状态掩盖误差。冻结主参数应保持14次A消失／7次重入、五处B保护、29删／21增；日线事件不变、旧356预测仅7/10的120分钟变更。其余2条90分钟B绿差异仍无软件真值，逐条保留解释。

验收runner沿用只读白名单、原预算和显式新输出目录，拒绝覆盖；不新建另一个通用研究框架。已有页请求混合runner继续用真实TS调度和HTTP，不操作用户浏览器；增补新字段／版本断言，不重造并发算法。

### 21.11 实施里程碑、验收命令与停止条件

| 阶段 | 开工／完成条件 | 交付 |
| --- | --- | --- |
| A1 内核与身份 | 用户确认本节后开工；先冻结源码，再迁唯一step／快照／新Spec和正式单测 | T01—T04；独立研究实现清退 |
| A2 query／DTO／预测 | A1规则与_04相容后同步全部字段、缓存及完整域；不能留下半新合同 | T05—T10／T14，四周期真实路由原响应 |
| A3 Wealth消费 | 严格类型／白名单、绿色标签与详情、技术面后端display；沿用已确认设计 | T11—T13、真实响应驱动展示；不改布局和评分 |
| A4 产品验收 | 新版完整回放及所有反例通过，再跑源／接口／混合预算 | T15及逐条计划对账；页面由用户验收 |

实施验收命令，实际结果见§22；不以先前h1成绩代替：

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -B -m pytest -q -p no:cacheprovider scripts/research/index_market/tests/test_xxm_calculator.py scripts/research/index_market/tests/test_xxm_key_point_forecast.py scripts/research/index_market/tests/test_xxm_forecast_display.py tests/web/test_wealth_index_detail_xxm_api.py tests/web/test_wealth_index_detail_xxm_forecast_api.py tests/web/test_xxm_shared_loads.py
npm --prefix wealth run typecheck
npm --prefix wealth run test
npm --prefix wealth run build
```

same_segment_acceptance已提供--help及frozen／api／budget模式，实测命令和新输出目录见实施报告与研究README。API模式用隔离SQLite及封存行情字段传输fixture走真实router／query／calc／DTO，不mock核心服务；分钟物理读取由同轮临时Parquet集成测试及正式只读预算共同验证。冻结39747根×三门槛、45恢复切点及369预测对照是最低保留范围，新增字段／合同反例仍须另跑，不以旧63项代替。

性能设计不增加来源请求／分页／数据库计算，仍读取同一完整历史。新资格与活动等待均为每根O(1)，活动状态O(1)；已结束记录只在原受行数／LRU限制的SeriesEntry账本中，不在每个point重复塞完整参照。context直接按point ID取记录，不为了显示上下文再做全量回放；窗口组装和JSON新增开销须由下述实测验证，不能靠复杂度判断称已达4秒。

正式读取预算使用正常只读配置和原已完成端点，不读旧验收进程密钥：四周期各20冷＋20暖预测，配对识别，另测LATEST／两并发；记录源检查、读源、重放、模型、DTO／HTTP、响应字节与共享LRU实际占用。每请求4秒含后端排队／shared等待／来源／计算，新增模型≤200ms；前端5秒网络timer仍在调度后启动，不改调度排队语义。整页／双标签沿用16组306请求组合，图表／指标／九转／识别／四周期预测混合，所有响应身份及字段一致。source全历史／全部校验、行数／文件上限、1MiB／32KiB、64MiB与2个源槽位不得裁减或放宽。

保留源错误、0值／等号／缺口、取消／超时反例；任何模型、来源、DTO、四周期保护或预算冲突都停止后续迁移，回到本方案说明，不做按日期补丁、兼容双轨或暗中放大阈值。真实数据不可用时先完成隔离技术验证，明确欠缺项；不能把它标成完整交付。浏览器页面由用户手动验收，不自动登录、截图或要求新服务配置。

### 21.12 通用清单映射与例外白名单

按wealth/docs/system/module-delivery-checklist-v1.md逐项映射，列“不适用”也须说明理由。用户本轮已确认本节作为编码门禁；没有授予部署／发布权限。

| 通用条目 | 适用性、落点 | 验证 |
| --- | --- | --- |
| 2.1 事实链先行 | 适用；原Figma／展示基准＋算法§12.12＋本节 | 本节确认后编码；仅内容映射，无新布局 |
| 2.2 后端事实归一 | 适用；calc／Q／DTO，前端仅校验与显示 | T06／T09／真实响应驱动T11—T13 |
| 2.3 状态机 | 适用；NONE＋等待与DULL分开、明确各终态 | T01—T04、loading／error等T13 |
| 2.4 显示绑定语义 | 适用；A绿／取消灰／钝化黄沿用原token | T11—T12，等待无黄点 |
| 2.5 行为过程 | 适用；消失→等待→重入、源修订／重试 | T03—T05／T13—T14 |
| 2.6 同轮同步 | 适用；原三方案及§21、API原响应与测试 | 文档检查、SHA、提交前对账 |
| 2.7 渐进替换 | 适用；只迁上证XXM，唯一版本、不静默mock回退 | Spec／消费者白名单、完整代码包回退；source开关例外见下 |
| 2.8 合同先行 | 适用；21.3—21.8冻结类型／null／关联 | 两DTO、两adapter正反例 |
| 2.9 坐标／说明文案 | 适用；原MACD正负轴和tooltip／卡片槽位保持 | geometry／primitive测试；不加常驻图下注释 |
| 2.10 统计／传输 | 部分适用；源查询不改，已有序列内核与显示分位不搬数据库 | 完整字段／全历史、4秒／200ms；SQL下推例外见下 |
| 2.11 策略中心配置 | 不适用可编辑配置中心；仅21.8不可变代码Spec | 非法Spec拒绝，hash／版本同步 |
| 2.12 映射矩阵 | 适用；本表及下方8原则 | 无未映射条目 |
| 2.13 例外／语义断言 | 适用；下表仅两项沿用性例外 | 用户确认本节；不放宽坐标或预算 |
| 2.14 显式坐标参数 | 本轮不改坐标实现，沿用原优先级 | 原图表／geometry回归，不因标记扩域 |
| 2.15 并排双图 | 不适用；此模块无新增同语义并排双图 | 不改变现有Workspace布局 |
| 2.16 单行文案 | 部分适用；周期／状态原样，conditionsText允许原换行 | 卡片字段一一显示；不为塞文案压缩其他栏 |
| 2.17 核心case | 适用；21.9字段与21.11命令、真实路由原响应驱动前端 | 新版核心字段齐全、禁止mock service代交付；页面人工验收 |
| 2.18八原则 | 全部适用；见下方 | 逐项无默认留空 |

| 2.18原则 | 落地与测试 |
| --- | --- |
| 1 单一事实源 | calc→Q→DTO→adapter，T01／T09／T11 |
| 2 契约冻结 | 21.3—21.8及版本一次迁移，缺字段／旧版本拒绝 |
| 3 配置一致 | 21.8单一Spec，无env／页面阈值 |
| 4 默认显式 | 无等待字段必传null／[]；非上证／非四周期仍拒绝，EMPTY不造状态 |
| 5 排序确定 | rearmRecords按(disappearedAt,id)，原参照／最早时点规则不改，T06—T08 |
| 6 性能前置 | 21.11四层计时、缓存字节和整页混合，失败停止 |
| 7 异常标准化 | 原XXM／XXMF码继续，不新增debug字段或吞掉合同错误 |
| 8 用户可见结果 | 真路由JSON驱动两adapter／标签／四行文字，错误与等待不能混成有效钝化 |

| 例外规则 | 模块／生效范围 | 理由与门禁 |
| --- | --- | --- |
| 2.7不新增source开关 | 仅本次XXM算法升级，沿用原分钟开放门禁 | 没有数据来源切换；新增开关会制造双算法在线路径。以唯一版本／Spec身份和整套回退证明范围 |
| 2.10不把顺序内核及既有显示分位改成SQL聚合 | 四周期同一完整序列内的因果识别／预测及已批准60样本分位 | 本轮不增加大结果集读取或数据库统计查询；复用完整已校验序列，保持200ms／4秒，禁止新增数据库特有函数或SQLite兜底 |

页面人工验收安排来自用户持续授权，优先于通用自动浏览器建议；技术层仍须真实API及其原响应驱动展示，不能只做mock。未新增其他例外。

### 21.13 开发前审计记录（历史）与停止线

规则、数据范围、字段、函数、全部消费者、版本／配置来源、研究退场和正反例门禁均已明确；没有需要先补软件截图才能写本轮有限候选的技术阻塞。尚需用户确认本节及其中合同／暂定规则后，方进入A1—A4。正式预算、接口／页面结果仍是实施后的交付门禁；若实测不符按根AGENTS开发执行链第7条说明并等待决定。

本轮实际补核：当前h1的两组真实路由／query／DTO及共享加载隔离测试125项通过；对现有候选2的39747根×三门槛核查，所有A消失均可由当时未离段的B记录取得合法原结构锚点，所有等待快照的保存参照／最近价／段DIF前提相容。该检查支持21.3不另存active_structure_id的设计，不是新增a1实现验收或重跑正式4秒。

详细审计、实际代码SHA及文档校验见本轮LLD审计报告（原记录：`reports/xxm_same_segment_a1_lld_audit_20261016/README.md`）。当前正式产品仍为h1，没有写数据库／Lake、创建分支／worktree、部署、安装或提交。


## 22 A组a1内核实施对账（2026-10-16）

用户确认§21并要求“提交修改，然后推进开发”，已先按白名单提交方案与研究基线`f44c7bde`，然后按A1—A4实施。当前唯一算法为`xxm-direction-v0.1-a1`，预测为`xxm-key-point-forecast-v0.2-a1`；不保留h1合同或独立候选在线分支。原门槛、来源、选峰、TOP、20点、调度与预算保持。

calculator使用原B记录建立等待锚点；恢复helper补传已解析的history作一致性核验，不新增active_structure_id。完整Wave只在内核与snapshot中保存；公开记录只投影四字段reference。增量账本、过去投影、窗口外B关联、两schema／adapter与预测context同步，旧快照与旧版本响应拒绝。预测沿用forecast／forecast_joint的原P—C几何，只迁入口分区、真实确认身份和等待文字；图层沿用原几何、token和四行布局。

临时候选与旧runner、临时研究测试已清退，17项研究参数化用例中的规则／恢复／入口内容迁入正式测试；仅临时命名空间绑定用例退场，TOP改用封存oracle及四周期三门槛完整对照。95份旧源码及输入／旧报告SHA已封存，旧失败报告不改写；当前same_segment_acceptance只运行产品类、读_04冻结语义，不动态编译或替换产品源码。

冻结39747根×三门槛、45前缀／恢复、369预测及已有模拟全部通过；主参数14次A消失／7次重入、B绿93条，与研究候选语义相同。日线事件保持，五处既有B保护全部保留；7/10的120分钟由提前READY改为先重入的CONDITIONAL_ENTRY、最近结构由7/13上午改下午，8/15日线仍CONFIRMED，18个日线校准保护不变。

后端261项、前端全量1186项／最终XXM聚焦43项、类型／构建及16项架构护栏通过；13组真实路由原响应驱动TS adapter／详情／卡片，临时Parquet和正式源各有独立读取验证。整页／双标签16组306请求通过，HTTP最大3.041秒；最终正式预算及A01—A10逐项代码／测试对账见[实施报告](../../../../reports/xxm/conclusions/xxm_same_segment_a1_implementation_20261016/README.md)。CodeGraph explore／impact覆盖80符号、sync／status正常；无依赖矩阵改变。页面由用户验收，本轮开发改动按用户要求提交；未推送或部署。

最终正式源截至10/15、冻结重叠无差异；四周期20冷＋20暖预测及配对识别共320请求、另4次LATEST和8次两并发均通过，单请求HTTP最大2.128秒、模型包络93.074ms。原响应、LRU和4秒／200ms均保持；后端40项最终文案回归通过（与261项主回归有重叠）。验收步骤按§21完成，未以旧h1预算代替。

## 23 真正CANCEL后的重新选峰研究（2026-10-16，产品无改动）

依据[V0.1§12.14](../../../../docs/product/xxm-direction-algorithm-plan-v0.1.md#1214-真正钝化失效后的重启研究2026-10-16仅研究)及研究报告（原记录：`reports/xxm_cancellation_restart_20261016_01/README.md`），不加全局“CANCEL后必须红→两根绿”锁。`calculator.step`先以`dif_break`清空原活动参照；同柱不重选，后续NONE由原历史池／最近价门槛和strongest_eligible重新选择。DIF已突破的旧参照不会恢复；另一个更低DIF参照仍可能合格。该路径与`_advance_rearm`固定参照恢复不同，A／B生命周期、快照、Spec、DTO及消费者不变。

四周期39747根的221次取消有16次同绿段换参照重启；其中8次在取消后跨价，8次在锁定期间已跨价。日线7/15—7/17有既存软件图形对应，其余分钟15次只计模型样本。若段DIF已不高于全池最低DIF，同段自然无解；不据此扩成跨零柱软件定律。研究工具排除STRUCTURE_DISAPPEARED、RESEARCH_HISTORICAL_WITHDRAWAL和等待INVALIDATED，不以它们建立CANCEL事件。

预测继续使用唯一内核的克隆，原参照的失效价不代表所有新钝化永久失效。当前正式代码／合同不变，故本轮只跑离线核查及隔离测试，不用本轮约514ms工具耗时代替既有4秒／200ms正式验收；未重跑服务或浏览器。分钟精确重选时序、软件精确池宽、零柱／等号仍留待核，不作为新增功能。

### 23.1 同根竞争与普通首次激活用价的待核边界

续查见[V0.1§12.15](../../../../docs/product/xxm-direction-algorithm-plan-v0.1.md#1215-参照重选顺序及价格资格续查2026-10-16仅研究)和第二轮报告（原记录：`reports/xxm_cancellation_restart_20261016_02/README.md`）。16例另一参照首次合格为BEFORE 2／SAME 6／AFTER 8；12/16的90分钟属于SAME，原资料不能区分先取消、先重选或同柱双事件，不能把它用于证明所有活动期间锁定。

`step`第69—99行仍为原参照突破优先清空、`elif`阻止同根首次选择、后来按段最低收盘与段DIF选择。12/16 14:00仅旧段低收盘满足新参照价，本根close不满足；这项与`_qualifies_bottom_close`在A组固定参照等待中使用本根close分开。原软件精确时序／普通用价仍待独立标签与数值，禁止据此直接改产品或预测。

旧§5.31补图暂停保持；新读作者三篇文字只补收盘／情境证据，无新定时软件事件。32份SHA及四周期事件不变，87项隔离／内核回归通过，本轮无合同、依赖、页面或正式预算变化。

### 23.2 新90分钟图的事件链对账尚未通过

用户随后提供12/16原图并确认四个标记的顺序／数量，状态更新见[V0.1§12.16](../../../../docs/product/xxm-direction-algorithm-plan-v0.1.md#1216-1216的90分钟图已收到链条仍待逐柱对齐2026-10-16)及新图核查（原记录：`reports/xxm_software_case_20251216_m90_20261016/README.md`）。不再将此图列为缺失；四条软件观察与当前12/11—16六步模型链未一一对应，12/15的A消失／重入和12/16的CANCEL／首次激活必须分开核，不能只比收盘DULL。

末端close显示对应而三项MACD字段仍有差异。用户仅能给出绿色更像15日、末黄在16日的大致定位，精确柱位／绿色身份仍待核，不再要求继续辨柱；改核对应讲解，已有ASR不足以命名绿色。尚无确定代码修正结论，不改`_advance_rearm`的重入条件、首次选峰、事件优先级、Spec、DTO及预测。保留新证据与源SHA，本轮文档／观察核查不等于新增产品验收通过。

### 23.3 资格诊断保留研究态，不增加新的运行门禁

**后续更正：** §23.4的新图已确认15日重新钝化，本节H2b作为该次重入必要条件的解释撤下；不再作为待开发门禁或继续索取15日图。

见[V0.1§12.17](../../../../docs/product/xxm-direction-algorithm-plan-v0.1.md#1217-1215重入资格续查新dif线索尚不构成编码依据2026-10-16)及辨别报告（原记录：`reports/xxm_rearm_discrimination_20261016_01/README.md`）。不在`_qualifies_bottom_close`／`_advance_rearm`加再次破原结构最低收盘或两根等待。待核H2b涉及**当根bar.dif与原结构确认时的wave.dif**，不是当前累计wave.dif与自身旧极值相比；后者不可能回升。当前产品没有额外保存／判断H2b锚点，本轮也不新增字段、Spec、状态机或预测分区。

H2b只是本轮关键样本上未被排除的事后条件，不能当作已批准编码设计。需用12/15收盘90分钟图先区分重入提前或次日参照切换问题，再决定是否形成候选和新的代码级LLD。39747根事件与a1账本、32份SHA保持，98项离线／内核回归通过，不替代软件识别验收或正式预算。

### 23.4 12/15截止图确认：保留A组，研究取消／重选次序

当前结论见[V0.1§12.18](../../../../docs/product/xxm-direction-algorithm-plan-v0.1.md#1218-1215新图确认重入日期转查16日参照切换2026-10-17)和证据（原记录：`reports/xxm_software_case_20251215_m90_20261016/README.md`）。新图15日已有消失后新钝化，`_advance_rearm`当根重入的日期／顺序得到支持，不增加H2b、等待根数或新的原结构字段。

实际`step`仍先以旧活动参照突破输出CANCEL，再由后续NONE走首次选择；16日11:00另一参照其实已经合格，是研究先重选候选的代码分歧点。该分歧属于活动DULL参照竞争，不是A等待与B历史绿，不能用同柱双事件或图层删字代替内核解释。若后续形成并批准候选，再补全快照／身份／缓存／预测及所有消费者LLD；本轮不新增运行字段、策略开关、版本或实现，不以单例推定顶部／STRUCTURE也须重选。

12354根同前缀事件及16日三根条件核对、32份SHA保持；产品／边界／依赖与正式预算不变。旧98项测试是上一轮工具证据，本轮未重跑，不用于宣称软件参照公式已验证。

### 23.5 R1代码级研究实现及产品迁移缺口

研究依据及结果统一见[V0.1§12.19](../../../../docs/product/xxm-direction-algorithm-plan-v0.1.md#1219-r1隔离研究先转用仍合格参照再取消2026-10-17)与报告（原记录：`reports/xxm_reference_rescue_20261017_01/README.md`），不是新增已批准产品合同。

| 实际研究代码点 | 本轮内容 | 保留边界 |
| --- | --- | --- |
| scripts/research/index_market/xxm/reference_rescue.py::rescue_reference | 对下一根更新后的段极值检查旧参照严格突破，按原池资格选另一参照 | BOTTOM DULL、同负柱段、无等待；不扩大池或价格定义 |
| BottomDullRescueCalculator.step | 先校验输入，再只替换合格活动参照，其余super.step | 研究子类，不改生产XxmCalculator或Spec；诊断日志不参与决策 |
| collect／evidence_checks | 原产品与R1全源对照、切换归因、软件保护、前缀及restore | 原产品必须等于a1账本；候选差异不生成软件expected |
| child_of／price_probe | 显式研究副本、同一端点下一根局部价格分支 | 不调用正式forecast假称R1预测验收；父状态保持 |

9次切换对应18个差异端点，八组往返不再产生、一次真取消延后一根。真实范围TOP、池／分段及全部底部历史／A事件相同，45前缀／恢复与120测试通过。22项新增字面测试包含“救回后下一根再取消”和“救回后提前结构”；后者在真实范围未出现，但说明不能仅迁图层或承诺所有未来B链不变。

**迁移前仍需补齐：** R1下固定参照关系如何分支、切换后哪些原条件作废／如何求新结构、预测完整价格域与边界、唯一版本／缓存／快照身份以及全部消费者的代码／测试映射。当前forecast_detector.clone显式构造正式类；未来若R1进入唯一正式类，clone可继续共用该类，无须双引擎，但forecast与forecast_joint目前的固定参照约束不能自动代表新规则。公开字段是否足够或需调整，须先审计，当前不新增字段或策略开关。

原软件唯一规则、其余8次切换的软件真值、STRUCTURE／TOP／提前主动换峰仍未知；当前只取得有限识别候选的解释与工程证据。正式三门槛／完整预测／4秒／API／混合页面验收均未在本轮声明通过。继续方案细化，未获新确认前不迁产品。

## 24 R1预测与唯一内核迁移代码级LLD（2026-10-17，待确认）

### 24.1 范围、现状及审计链

2026-10-17开发授权补充：用户已同意按本节开发；其余8处视频难以取得，不再作为开发前置条件，仍如实保留未核实状态。先完成P2数学／预算预检，再迁入唯一产品内核；实际冲突继续按根规则说明，不以缺图推定原软件规则已证实。

本节细化[预测方案§30](./index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md#30-r1预测修订方案2026-10-17待确认未开发)，只允许R1限定的BOTTOM DULL同负柱段分支。**本轮只修改文档；以下“新增／修改”均是拟编码事项，产品仍为a1。** 已有研究实现只支持候选可行性，不替代预测预检或产品放行。

本轮用CodeGraph `codegraph_explore`追`confirmed_options／build_relation／ForecastResponseDto／adaptForecast`，`codegraph_impact(XxmCalculator,depth=1)`覆盖42符号。结果同时命中历史报告的同名函数，故按实际文件核清生产源码，不将报告里的旧函数作为实现。实际链为：`src/app/api/v1/router.py`装配Biz路由→`IndexDetailXxmForecastQueryService.build`→共享SeriesEntry／`calculator_at`→投影→`forecast`／`forecast_joint`→严格DTO→TS `fetchForecast/adaptForecast`→`useXxmForecast`→`XxmForecastCard`。识别日线／分钟路由和图层也消费同一检测器版本。Biz只依赖Biz及Foundation；不改变依赖矩阵、不修改QTF、数据集或读取层。

下表路径前缀：S=`src/biz/services/wealth/market/index_detail_xxm/`；Q=`src/biz/queries/wealth/market/index_detail_xxm/`；D=`src/biz/schemas/wealth/market/`；W=`wealth/src/features/index-detail/`；R=`scripts/research/index_market/`。

| 当前真实代码点 | 已核实的约束／缺口 | 拟改动 |
| --- | --- | --- |
| S/calculator.py::step | 更新段极值后立即按旧参照取消，后续`elif`阻止同柱重选 | §24.2只在取消前增加限定的重选，不复制step |
| S/forecast_detector.py::clone | 明确构造XxmCalculator，再restore；不会保留研究子类 | 正式迁移后仍用唯一类；不增加在线工厂 |
| S/forecast.py::forecast | 真实DULL中间模拟要求reference完全不变；conditional用单一ref求域 | 改为逐条已证明的参照路径，不删断言后直接放行 |
| S/forecast_joint.py | `branch_points/survival_reason/target_lines/close_bounds/common_interval/displayable_witness`都固定ref | 完整分割路径；目标几何按该路径最终ref求解，交集／示例不得跨路径拼接 |
| S/forecast_detector.py::confirmed_options | 中间根ref必须始终等于最终ref，目标STRUCTURE也用同ref | 校验每根应使用的ref和转换，目标事件必须匹配最终ref |
| D/index_detail_xxm_forecast.py::ForecastResponseDto.consistent | rearmContext强制所有未来关系仍用保存ref；example仅关联entryRangeId | 改为固定初始激活参照，后续路径显式；共同条件／示例关联确切关系 |
| Q/forecast_query_service.py::build | 以两Spec、来源指纹、asOf、日历等缓存；先事实再forecastId | 新事实在ID前入payload；统一新版本隔离缓存；沿用真实确认关联 |
| W/xxm-forecast/adapter.ts、types.ts | 根key白名单、唯一a1版本、等待ref约束，尚无参照路径 | 一次迁移严格新合同；错误关联拒绝，不在前端重算 |
| W/xxm-forecast/XxmForecastCard.tsx | 四周期行只消费后端display四字段 | 保留布局；触发、失效、换参照文案由后端产生 |

### 24.2 唯一内核的精确插入点与快照

正式迁移时，在`step`输入验证、符号／段处理、段极值更新和`_advance_rearm`之后、原`dif_break`分支之前调用拟新增私有`_rescue_bottom_dull_reference(bar, old_wave, old_state)`。只在`event_type`为空、`blocked`为假、未发生reactivation时调用；内部同时要求：

1. `old_state == self.state == 'DULL'`，`old_wave is self.wave`且sign为-1，`bar.hist < 0`；已有ref且`pending_rearm is None`。NONE刚重入这一根不调用，不跨段。
2. 更新后的`wave.dif < old_ref.dif`，严格等号不切换。旧ref仍有效时立即返回，不主动择优。
3. 原负柱历史池、原`min_bars`及最近段价格门槛；`wave.price < candidate.price`且`wave.dif > candidate.dif`。价格与DIF用段最低收盘／最低DIF，不能用OHLC低点、当前close或原结构低点替代。
4. 抽取私有纯选择器`_select_eligible_reference(wave, pool)`供现有首次激活和R1共用：先按原`reversed(pool)`确定最近价门槛，再保持现行稳定排序挑最强合格者，调用方deepcopy。抽取前后首激活账本必须一致，不改变等DIF时的原稳定顺序。
5. 若有合格替代，只改`self.reference`，继续原step，无新普通事件／图层文字；无替代继续原CANCEL。不得把取消改成仅删标记，也不加“等下一根再试”的隐藏状态。

原波段池、B历史原参照及A等待记录不由R1改写。新STRUCTURE仍由原step登记B历史，只是其确认参照可能已变化；不能要求所有未来B账本永远相同。无须新增“上次切换”持久状态：已有snapshot保存完整当前reference、wave与两段池；新SpecHash拒绝旧快照，SeriesEntry重建checkpoint。切换条件保证`newRef.dif < wave.dif < oldRef.dif`，故同绿段不能回到旧ref；两段池下至多一次。

### 24.3 预测路径和完整数学分区

拟新增S/`forecast_paths.py`，与原`forecast_math`的Affine／Interval和源精度工具组合；它是本模块纯计算，不是新共享平台。内部不可变记录：`ReferencePath(initial_reference, transitions, final_reference)`、`PathCell(domain, path, prefix_conditions)`；转换记录为`(endpoint, from_reference, to_reference)`。源身份、周期、spec及真实截止state都不变，假设运行不能写回SeriesEntry。

拟函数及职责：

| 函数 | 输入→输出 | 必须满足 |
| --- | --- | --- |
| `partition_prefix_paths(c, projection, seed, stamps, check)` | 初始P域／ref、完整中间端点→PathCell集合及有原因的排除域 | 先真实首次／重新激活，再逐根DULL；首次CANCEL／提前STRUCTURE／零柱即结束这条路径，不跳过后再找结构 |
| `path_branch_points(...)` | 所有候选ref和每根仿射DIF／柱值→完整切点及精度保护带 | 同时覆盖两ref的DIF、最近及候选价格、原wave极值、DIF零点、1%转向、柱色零点和日线量化边界；不能只加旧ref根 |
| `prove_path_cell(...)` | 分割后的P单元→一致路径／排除原因／精度未决 | 各谓词在整单元有符号证明；中点回放只给路径命名，不构成全域证明；多种源取整路径不同则保留未决 |
| `solve_next_bar_outcomes(...)` | 当前真实BOTTOM DULL及下一端点→全部正价域结果 | 完整并集覆盖C>0；互斥、边界按严格性归属；无目标结构也保留 |
| `validate_path_options(...)` | 真实内核副本及给定P／C／path→bool | 每根检查普通事件、参照、状态；包含全部source_options、去重及check，不改真实状态 |

`partition_prefix_paths`固定原中间走势假设：NONE的P来自`solve_entry_ranges`，第一根按activation/reactivation真实形成DULL；已DULL的P是当前close退化域。每次只在仍存活的单元上继续下一根，并用该单元当时的ref判断R1。普通首次激活原pool排序不改；等待阶段不能凭另一ref绕过保存ref。已经真正重入后，后续DULL可按相同R1切换。

分钟分支用Affine精确求根、分割前DIF正负及上下界交点；日线枚举相关DIF／柱值的三位量化台阶及GUARD两侧，再计算每台阶上的线性域。浮点代数重排误差沿用entry_partition的向外包络思想：不能将误差带认定为已经证明的有效或取消域，也不能在识别器加epsilon。涉及min的比较需同时检查所有前缀DIF与原段最低DIF；涉及价格只用该前缀更新后的段最低收盘。边界独立作点单元，用真实运算次序核验。

每个单元有且仅有一个完整路径或排除原因。只合并路径、ref、端点及所有条件相同的相邻单元；精度空隙不能跨越。路径数量随“是否切换及在哪根切换”有限增长，不按价格网格抽样；日线量化单元数量另计，不能用路径少来声称预算已满足。

#### 目标根及最近端点

沿用`project_affine_prefix(projection,n)`，第j目标的前j-1根全部验证，结构条件只用目标前的`final_reference`。`build_relation`生成该路径各阶段对应的前置不等式：真实DULL从`ds[0]`开始验证，conditional的第一根由activation证明、其后从`ds[1]`验证；不能直接保留当前统一从1起算的循环。`target_lines/close_bounds`接受最终ref。`domains_for_target`按PathCell分别求可行域，不把不同ref的并集当成一个固定ref域；当前`n==1`的快速路径也须先有一致路径证明。`common_interval`在同一路径完整P域上求交；`displayable_witness`也只从确切关系取点。

R1目标根不能直接形成结构的证明：触发前旧段最低DIF≥旧ref.dif且最低DIF≤previous.dif；触发后必是当前bar.dif<旧ref.dif，故bar.dif<previous.dif，不可能满足底部向上转折。若目标变红则不适用R1，仍按原flip优先级；零柱原样重置。由此，目标为STRUCTURE的分支不允许在同一根追加换ref；救回的目标根只列入下一根结果分区，后续端点再按新ref判断。必须有独立字面反例验证这一结论，不能仅凭函数名认定。

`forecast`按j=1…20顺序，只在该j至少一个完整关系有确定解时返回最近目标。未决分支可能在更早j有解时，沿用PRECISION_PENDING保护，不跳过未知j宣称较晚是“最早”。空域、提前结构、真实取消、零柱、精度原因全记录。不得把“保持钝化但该目标无结构解”标为CANCEL。真实STRUCTURE／当前根变色确认仍由`_active_confirmation`优先处理，不从任意旧历史找CONFIRMED。

### 24.4 下一根的结果域

仅在真实源READY、ordinaryState=DULL且direction=BOTTOM时求下一根C的完整结果；其他状态返回null。投影校准失败时也为null，保留原失败原因。只要投影成功，即使20根内NO_CANDIDATE也要求给出此域。

| outcome | 判定及reference含义 | route |
| --- | --- | --- |
| PRESERVED | 仍DULL且未切换；reference为原活动ref | null |
| REFERENCE_SWITCHED | R1转ref且仍DULL，无新DULL／CANCEL；reference为新活动ref | null |
| STRUCTURE_CONFIRMED | 当根真实STRUCTURE；reference为事件确认ref，变色后普通ref可已清空 | dif_turn或color_flip |
| CANCELLED | 真实普通CANCEL，reference为取消事件原ref，不是全部池的抽象最强ref | dif_break或dif_break_on_flip |
| ZERO_RESET | 零柱，原普通状态重置，不能称为结构确认／CANCEL；reference=null | null |
| PRECISION_UNRESOLVED | 全部源取整／浮点包络不能一致定性，reference=null | null |

按C的所有原池价格根、两ref的DIF根、1%向上转折、零／变色及取整保护带分割，再用唯一内核分类和全域谓词证明。与§24.3共用分割／证明原语，避免第二套失效计算。下一根的previous DIF是已知常数，日线仅需求这些判定门槛的量化边界，不在无界C域枚举无限个DIF台阶；只有有界P域上涉及变化的previous DIF时才展开相关台阶。CANCELLED可以是不连通的几段，REFERENCE_SWITCHED也不是“从此永不失效”；禁止强制压成单个向下阈值。12/15下一根约3838.39取消、3821.73切换继续的已有探针仅是内部点，不把它们当精确边界金样本。

### 24.5 拟议合同：字段、null和关系约束

版本拟为检测器`xxm-direction-v0.1-r1`、预测`xxm-key-point-forecast-v0.3-r1`，一次迁移，不双读a1。HTTP路径、参数、周期、status／reasonCode、原assumption.policy及display四字段不改。以下是**新合同设计**，并非当前API示例。原Dto仍`extra='forbid'`，TS须对新增嵌套对象同步做key及关联校验。

| 对象／字段 | 类型与必有性 | 跨字段条件 |
| --- | --- | --- |
| 根`nextBarOutcomes` | 必有，可空；非空为`{endpoint,initialReference,branches}` | endpoint必须是computedThrough后的第一个本周期端点；适用状态见§24.4；与结构targetEndpoint是两件事 |
| `branches[]` | 非空，元素`{branchId,priceRange,outcome,reference,route}` | ID唯一；outcome／ref／route按§24.4；所有正价域互斥且穷尽，包括未决带；不要求前端重算覆盖性 |
| `RelationDto.initialReference` | 必有、非空XxmReferenceDto | READY为真实截止活动ref；conditional为关联entryRange的ref；不能填最终ref冒充初始ref |
| `RelationDto.referenceTransitions` | 必有数组，0或1条`{endpoint,fromReference,toReference}` | 只允许BOTTOM；初始ref→from一致，to.dif<from.dif；端点属于intermediateEndpoints，严格晚于首次激活且早于目标；不得原地／回切 |
| `RelationDto.reference` | 原必有字段，明确为最终确认ref | 无转换时等于initialReference；有转换时等于toReference；targetConditions绑定此ref |
| `CommonConditionDto.relationId` | 新必有、非空字符串 | 指向同response的relation；原entryRangeIds、entryDomain、reference、route与其相同，closeRanges为该关系全域充分区间 |
| `ExampleDto.closeRanges[]` | 改用`ExampleCloseRangeDto`，在原CloseRangeDto增加必有relationId | 每段指向确切relation；例子entryRangeId属于该关系且preClose在其entryDomain及targetEntryRanges内；route也匹配 |
| `rearmContext` | 保留必有可空及原WAITING／NONE约束 | activation.ranges及relations.initialReference等于保存ref；允许重入后未来中间端点再R1切换；不再强制最终ref始终等于保存ref |

`nextBarOutcomes`的initialReference指真实截止ref；每个切换分支的reference必须不同且DIF更低。取消分支仍用事件原ref。结构分支可以保留原ref，零／未决不能携带伪ref。JSON interval沿用严格正价／无界端点不能inclusive规则；`forecastId`覆盖所有新事实。共同区间和例子不因结构route相同而跨参照路径引用。branchId／relationId采用当前结果内稳定序号，排序按价格下界、端点、原池稳定顺序、route，不能使用随机数。Example仍只用于conditional，entryRangeId仍非空；READY无可展示确定区间时保留PRECISION_PENDING，不制造`entryRangeId=null`示例。真实交易日的“下一端点”由backend日历断言，TS只验证周期合法端点及时间／关联，不自行推算节假日。

伪结构示意：`relation{initialReference:弱参照,referenceTransitions:[{endpoint:中间完成端点,fromReference:弱参照,toReference:强参照}],reference:强参照,...}`。正式可执行JSON正反例由P2生成、另以独立字面断言验证；本轮没有用手填价格伪装真实API成功样本。

### 24.6 身份、配置及消费者迁移清单

| 项目 | 默认／来源／持久化 | 消费者、生效及验证 |
| --- | --- | --- |
| `XxmSpec.algorithm_version` | 拟r1，唯一代码不可变Spec；不写env／DB | 事件／历史／rearm ID、snapshot、SeriesEntry、识别DTO、TS两个指数入口；新进程／重新载入代码后生效，旧spec快照拒绝 |
| 新`XxmSpec.bottom_dull_reference_policy` | 拟`prebreak_strongest_eligible_v1`；与version同一dataclass和hash | 只定义唯一正式语义，不做可选分支；step、cache及报告身份，单测禁止任意改值 |
| `ForecastSpec.forecast_version` | 拟v0.3-r1，代码及原spec_hash | forecast DTO／TS／fixtures、forecastId与缓存；不增加用户设置、运营配置或动态参数 |
| 原所有预算／池宽／精度／日期／刷新 | runtime、XxmSpec、ForecastSpec现有来源不改 | 不新增散落常量，不修改读取层；正式计时证明确实保持 |

须同步清点：S/spec.py、forecast_spec.py、calculator.py、forecast.py、forecast_detector.py、forecast_entry.py的激活一致性检查、forecast_joint.py、forecast_text.py、新forecast_paths.py；Q/query_service.py的checkpoint／缓存与forecast_query_service.py；D两个schema；Biz `index_detail_xxm.py`、`index_detail_minute_xxm.py`、`index_detail_xxm_forecast.py`三个路由；App原装配只核不改依赖。

前端为W/xxm与xxm-forecast各自types／adapter／apiClient／hook、rearmContract、XxmForecastCard及图层详情消费者；数值事实只接受后端。图表事件种类／坐标算法本次不变，不新增“切换”标记。识别adapter改唯一algorithmVersion；预测adapter改唯一forecastVersion及根key、嵌套形状、路径／relationId、等待初始参照规则；拒绝旧版、不缺字段兜底。detectorSpecHash当前前端只验证格式，不能写成已有hash白名单；后端真实路由必须断言其等于新MAIN_SPEC。

维护中的验收工具也需迁移：R/xxm_page_request_audit.mjs的版本断言、xxm_forecast_display_audit.py、xxm/bottom_history_acceptance.py、xxm/same_segment_acceptance.py及相关测试／fixtures。冻结a1历史报告与原观测不批量替换版本；报告明确记录当时版本。研究子类不进入产品import链，迁入后不保留第二套在线状态机。

`forecast_query_service.build`继续共享加载／来源校验，projection只恢复一次，传给路径及下一根结果求解。新字段在digest之前写入，仍按两SpecHash、来源指纹、period、asOf、expected及calendar缓存；`get_forecast/put_forecast`继续deepcopy，缓存／等待调用不能共享可变分支。业务时间20点切换、回放未来截止、分钟最后完成端点仍由统一context和source决定。

### 24.7 预检、独立预期及逐项测试

先P2、后P4。P2拟在R/xxm/`reference_rescue_forecast.py`集中编写新路径求解研究，不在reports放代码、不以字符串替换／exec／monkeypatch改生产forecast，不调用其固定base clone冒充R1。显式离线副本调用已有R1候选及现有纯数学工具，新求解代码在确认迁移时收敛到S/forecast_paths.py和原求解器；不能长期维护两套正式公式。新研究身份／代码SHA与run_01分开保存，输出新目录，不改现有policy、账本或38份保护文件。

| 编号 | 代码点／验收输入 | 必须证明的结果及独立依据 |
| --- | --- | --- |
| R01 | calculator两个私有函数及step，四周期39747根×原三门槛 | 首次选择和禁入分支不变；1%九处变化与既有候选逐条一致；另两门槛真实结果另记，不继承旧a1成绩 |
| R02 | 字面构造TOP／STRUCTURE／NONE／WAIT、旧ref未破、无替代、等号、变色／零柱、非法bar | 应禁止的救回确实不发生；输入失败不先改ref；等DIF稳定顺序保持 |
| R03 | 独立小序列：救回→转强／再下破、clone／snapshot | 下一根可以真实STRUCTURE或CANCEL；不能切换当根报STRUCTURE；旧ref不能复活、同绿段≤一次、父状态不变 |
| R04 | 独立Fraction／Decimal EMA小样本及字面日线台阶 | 不调用待测分割helper生成expected；手算两个ref根／价门槛／1%根，逐根独立判断P—C域；源精度与校准错误分开 |
| R05 | prefix paths、branch_points、nextBarOutcomes | 全正价域无遗漏／重叠，根、前后各一ULP及日线±GUARD／三位等号；取消可不连通；精度带不能混入确定范围 |
| R06 | 两ref价／DIF先后、初始NONE／A等待、真实DULL | 切换发生在哪根决定最终ref；等待不能换ref，重入后可切；禁止根据目标ref反写初始激活资格 |
| R07 | 结构P—C／共同区间／示例／最近端点 | 每条域有符号证明及唯一内核options回放；不同路径不混；提前STRUCTURE、真取消／零柱即截断；最近有解、20根无解与精度保护保持 |
| R08 | 原369预测点＋每次切换前一根／当根／后一根及后续结构端点去重 | 日线虽0次切换仍全覆盖；9例按发生机制解释预测差异；2023/9/20失效延后一根仍记未获软件验证；18个原日线校准保护不放宽 |
| R09 | 原软件五处B保护、7/10—13及3959.16／3892.79／3944.79 | 依据独立已有观察；不得由R1回放制造expected。3960只为模型反例；其余8处新图另记观察层 |
| R10 | strict DTO／TS正反例 | 漏字段、错版本、切换在目标根／WAIT期间、from断链、toDIF不更低、错relationId、终ref错、零柱带ref全部拒绝；合法等待重入后切换可接受 |
| R11 | 真路由→原JSON→两TS adapter／组件 | 日线及60／90／120、新旧版本隔离、nextBar／路径／四项display一致；loading→ready、timeout→error、delayed、切日期／旧请求、隐藏恢复不串行状态 |
| R12 | 真实截止snapshot／cache／asOf及20点前后 | 过去结果不含未来切换；源修订全前缀重建；冷暖结果相同、不同period／版本／asOf不串；返回副本不可污染缓存 |
| R13 | 真实源读取／HTTP／实际TS整页混合与双标签 | 保留完整历史及全部校验，4秒请求、200ms模型、32768字节响应、64MiB／16项LRU、并发2与原读取上限均保持 |

P2只用已有M0冻结输入及已登记源／软件观察，不新读Lake／DB。保留SHA及预检protocol，完整域证明、回放检查、软件相容性、预算四类结论分开。新增材料一旦冲突先归因，不能为凑9个“正确”改变图意或直接改标签。其余八处检索范围见取证清单（原记录：`reports/xxm_reference_rescue_20261017_01/screenshot-verification-guide.md`）。

### 24.8 展示规则与文案草案

保留技术面最下面四周期行，不加新面板、参照编号、评分或概率。`forecast_text`统一处理结构关系和`nextBarOutcomes`：先以`reference_band`求下一根及结构目标各自同跨度的60样本／95分位，`select_display`保留近期结果，`make_display`只输出确定分支。没有样本／精度未决不产生触发承诺，不添加“临界点附近暂不能确定”等噪声。

保留现行未触发的价格门槛和色变／零柱重新判断说明；背离远端可以省略，但如果省略会把CANCELLED与REFERENCE_SWITCHED混成同一个“低于X”的区间，就不能省去内部边界。合并只允许相邻同结果且同参照路径；完全远离近期的内部分支不展示，完整事实不删。

以下是句式模板，方括号由真实求解结果填入，不是承诺的新点位：

- `当前底钝化有效。`
- `结构成立：[最近完成时间]收盘[近期结构区间]，可形成底部结构。` 多步关系必须附准确且简短的中间收盘／初始激活条件，不能把“某些P成立”写成全范围都成立。
- `钝化失效：[下一完成时间]收盘[近期CANCELLED区间]，底钝化消失。` 多段分别写，不合成单阈值。
- 近期确有换参照分支时：`钝化延续：[下一完成时间]收盘[近期切换区间]，底钝化仍有效，结构条件需重新计算。` 不向用户解释内部波峰编号。
- 等待态继续`原底部结构已消失；当前未重新形成底钝化。` 随后为“重新钝化”范围；不能在此状态展示已有钝化失效。

换ref使**旧关系**失效；旧预测不会自动变成新ref的承诺。新真实完成根到达后按新快照计算新forecastId和关系。无结构解仍可展示近期下一根失效／延续域；未达到结构区间不等于钝化消失。Figma既有布局不改，新的确切分支文案在预检输出后同步原Figma供review；本轮不写Figma，不造真实点位示例。页面由用户验收。

### 24.9 预算、命令及失败处理

模型计时覆盖calculator_at、projection恢复、路径／下一根域、全域证明、全部源精度options、核验、近期筛选及文字；HTTP另含真实完整读取、日历、DTO、序列化与缓存写入，端到端≤4秒。客户端沿用XXM_TIMEOUT_MS=5000ms且发送后起算，不能用这5秒代替后端4秒；统一调度队列和双标签页仍按现行规则测排队／请求分别耗时。沿用现有计时点并对新阶段分别计时，不扣掉最慢分支来报200ms。复用一份仿射系数和切点、按完整状态去重、尽早关闭已结束路径；不减历史、删校验、截价格域、舍弃边界／路径或扩大预算。

P2记录四周期每点耗时、路径／台阶数量、最大内存、响应字节估算及最慢case。P4后正式源四周期20冷＋20暖预测及配对识别、LATEST、两并发和原16组整页／双标签模式全部重测，不用a1的306次或原R1的120项测试冒充新验收；请求数由实际清单记录。现有审计过程使用真实只读服务和TS clients，无浏览器自动验收；若原工具登录配置不可用，报告缺项，不读取其他进程密钥。

拟开发后命令（本轮未执行；只使用已有环境，禁止隐式安装）：

```bash
# 旧执行命令已移除；当前入口见 scripts/research/index_market/README.md
npm --prefix wealth test -- src/features/index-detail/xxm src/features/index-detail/xxm-forecast src/features/index-detail/api
npm --prefix wealth run typecheck
npm --prefix wealth run build
.venv/bin/python -B -m scripts.research.index_market.xxm_forecast_display_audit --output reports/<新的R1正式预算批次>
.venv/bin/python -B -m scripts.research.index_market.xxm_page_request_audit --output reports/<新的R1混合验收批次>
```

新路径专项测试归入现有R/tests/test_xxm_key_point_forecast.py；若大小需要拆分，只在同目录新增明确的`test_xxm_forecast_reference_paths.py`并纳入命令／发现清单。真实预算工具必须先迁移唯一版本和事实断言，再运行；没有服务权限或材料时准确标记未验，不通过skip／mock宣称正式验证。

算不完、响应过大或单元无法证明时沿用已注册错误／精度保护，禁止回退旧公式或输出半份确定域。若需改变方案语义／资源预算，依根AGENTS先说明并待确认。未验收不替换当前a1交付；正式回退通过单一整体版本恢复及缓存清理，不新增运行中双轨或可选策略。

### 24.10 编码门禁矩阵与放行结论

| 通用清单条款 | 本轮适用及落地 | 计划证据 |
| --- | --- | --- |
| 2.1 事实链 | 原Figma布局＋预测§30＋本节；新语义／文案待确认 | P1 review、P2实算、P3规则选择；当前未放行产品 |
| 2.2 事实归一 | 唯一内核、路径与nextBarOutcomes由后端产出 | R04—R11 |
| 2.3 状态机 | 原状态枚举及loading/error保持；无伪READY | R06／R07／R11 |
| 2.4 展示语义 | §24.8明确结构、钝化延续、真取消 | R09／R11，四项display逐字核对 |
| 2.5 过程测试 | 日期／周期、超时／隐藏／恢复及新旧请求 | R11／R12 |
| 2.6 同轮同步 | 实现后本节、预测方案、V0.1最后表及Figma文字对账 | P4／P5，不提前写已实现 |
| 2.7 渐进替换 | 已real模块语义升级，source开关不变，不新增mock回退 | R10—R13；适配理由是非mock→real迁移 |
| 2.8 合同 | §24.5唯一新DTO／TS及全部消费者 | R10／R11，旧a1拒绝 |
| 2.9 坐标 | 不改图表坐标；卡片事实和标记事件口径保持 | 原markerGeometry回归；新nextBar不画模拟K线 |
| 2.10 统计边界 | 仅已有完整序列上因果投影和60样本统计，无新增扫库／大结果传前端 | R08／R13 |
| 2.11 配置 | §24.6不可变Spec，非策略中心动态配置 | R01／R10／R12，无新env／持久配置 |
| 2.12 映射 | 本表逐项覆盖，不默认继承 | 文档及review检查 |
| 2.13 例外 | 无新增规则例外；沿用既有适用性说明 | 严格DTO、文案、几何回归 |
| 2.14 参数 | 未改图表域／刻度／参数优先级 | 原图表回归；本次无新轴参数 |
| 2.15 双图 | 本次未新增并排图，故不新增共享域策略 | 原布局保持，用户人工验收 |
| 2.16 文案 | 既有多行条件卡，不增加单行挤压；§24.8 | R11及用户页面验收，禁止以省略号丢失失效区间 |
| 2.17 真实API及展示 | §24.9真路由JSON驱动adapter／卡片，非只mock service | R11／R13及上述命令 |
| 2.18 八原则 | 单事实源；冻结合同；单Spec；显式默认；稳定排序；预算；注册异常；可见结果 | 分别R01、R10、R12、R06／11、R05／07、R13、R10／13、R11 |

**结论：设计已细化到拟函数、字段、分区算法、全部消费者和可反驳的验收；可供review，尚未证明完整预测数学／预算达标，不能据此直接宣布可迁产品。** 外部八处取证与P2数学预检可分别推进；S01若证实旧模型的20日取消才对，必须先修订R1范围再迁移。未解决的原软件池宽、普通首激活用价、零柱／精确等号和STRUCTURE／TOP动态选峰继续独立登记；本轮沿用原工作模型，不新增未经证实门槛。

## 25 R1开发态对账与正式来源阻塞（2026-10-17）

用户授权后，先完成隔离P2：四周期原369点＋36个切换端点／邻点，每门槛405组，共1215组，三门槛完整识别和预测、精度保护、预算估算通过，再迁入唯一产品类。不是先改产品后补预检。`_select_eligible_reference`与`_rescue_bottom_dull_reference`位置按§24.2；`forecast_paths`保存路径并完整划分下一根，`confirmed_options`按显式转换逐根核验，forecast保留单目标及原中间走势假设。普通最强首次激活持平时不可能后来多出更强资格，已写成有限路径的快速证明分支；A等待第一根仍锁保存ref，后续DULL另作分区。

唯一版本为检测器v0.1-r1／预测v0.3-r1，新增不可变策略及SpecHash；DTO／TS字段、严格关系引用、原确认解析、缓存身份和统一调度消费者已迁移。预测旧a1原响应继续作为拒绝反例，不改写旧文件。原先22项隔离候选的字面用例迁成唯一产品测试，保留原研究代码／测试原件档案；尚未完成工作树研究原型清退和Figma写入，不能把收尾算已完成。

产品1215组数学及display与预检逐项相同，45恢复通过，18组真实路由夹具及负向权限通过；57项前端、类型／构建、后端286＋4项分批及19项共享加载／架构护栏通过。真实路由夹具显式替代分钟读取器，不是正式服务验收。

正式只读预算在进入预测前因日线历史不连续失败。源已有2020起的数据，但截至本次只读检查仍缺2021-02-25至2022-12-30内452个开市日；此前观察首缺2/8，随后增加8行，输入仍在变化。三个分钟源可完整加载至10/16；这只证明来源完整读取，不能代替正式模型／HTTP预算。依据根AGENTS“实测冲突先说明并等待确认”，暂停后续交付，不修改来源起点／校验、4秒／200ms或正式数据。

完整代码／测试／证据映射、失败记录和剩余事项见[本轮报告](../../../../reports/xxm/conclusions/xxm_reference_rescue_r1_implementation_20261017/README.md)。需要确认是等日线回补后统一验收，还是先独立完成分钟线预算、保留日线和整页门禁待后续；未完成项不转成通过。页面仍由用户验收，未提交、推送或部署。

### 25.1 分钟线先行验收（2026-10-17，用户已授权）

用户确认日线历史正在下载，并要求先验收分钟线。仅为验收工具增加`--periods m60 m90 m120`显式范围；不传时仍为原日线＋三个分钟周期，空值、未知周期或重复周期拒绝。该参数只控制技术验收用例选择，不是产品配置、API参数或来源过滤，不能修改完整历史起点、数据校验、内核或预算。

正式只读预算按三个分钟周期各20冷＋20暖预测及配对识别、LATEST、两并发执行；核对冻结重叠、完整输入、唯一Spec、4秒HTTP／200ms模型、32KiB预测及64MiB／16项缓存。混合验收仍使用实际TS客户端和每标签独立调度器，分钟预测三行＋当前分钟图／指标＋九转请求＋识别层，三个选中周期×单／双标签×冷暖共12组；保留九转等其他已存在的页面请求，不用mock代替真实路由／只读源。范围、实际请求清单与失败都写入新报告目录，不能覆盖历史四周期失败。

本轮不请求日线预测，因此仅能声明“分钟范围混合／双标签验收”，不能冒称完整四周期页面通过。日线及原四周期整体验收待用户通知下载完成后恢复。页面仍由用户人工验收，不读取其他进程登录密钥、不安装或启动产品服务，不写正式数据。只启动运行后自动关闭的隔离只读HTTP验收进程。

另以`--mode replay-budget --formal-source --periods m60 m90 m120`重验本轮已保存的13个分钟路由场景，每例新建空缓存，使用正式完整来源与原鉴权，核对完整预测数学／display和明确状态。原`api_02`只提供冻结输入语义对照，不作为软件真值或正式来源证明；正式输入与M0重叠逐值一致由本轮budget记录另证。保存新原响应、单请求／模型／字节／缓存计时及失败，不用最新时点的短响应代替等待、R1结果域与真正取消等历史分支。

计时分组审计发现旧工具在进入暖组时又清一次缓存，导致20次暖组中首轮实际冷加载。保留已生成的`minutes_budget_01`，不把它说成20次纯暖；修正工具为沿用最后冷轮已完成的同源缓存，逐次断言冷轮确实完整读源、20次暖轮均不完整重读。该修正只涉及验收工具，严格分组成绩另存`minutes_budget_02`，不能修改旧记录来凑数量。

### 25.2 分钟范围验收结果与剩余边界（2026-10-17）

| 计划约束 | 代码／证据 | 结果 |
| --- | --- | --- |
| 显式范围、默认四周期不变 | `bottom_history_acceptance.main`及page audit Python／JS；13项测试覆盖默认、分钟选择、重复／空／未知拒绝、非正式模式不得缩样本、FastAPI只读会话进入／关闭 | 只改工具，产品／API／配置无改动 |
| 完整输入与冻结重叠 | `minutes_budget_02/result.json` | 17272／12954／8636根，至10/16 15:00；M0重叠17260／12945／8630根无差异 |
| 真冷20／真暖20、识别配对、LATEST与并发 | `minutes_budget_02`，249业务请求 | 每冷轮完整读取、每暖轮零完整重读；三周期最新READY，配对sourceInputId／computedThrough一致 |
| 历史R1分支 | `minutes_replay_budget_02`，13场景26请求 | 7/10等待、7/13再激活、12/15—16及真取消等完整数学／display与`api_02`相同；每例空缓存、正式只读源，非软件新增验证 |
| 实际客户端、混合／双标签 | `minutes_page_mix_01`，12组216业务请求 | 54份完整预测与本轮LATEST逐字段相同；冷每周期行情／指标各一次完整读取、暖无完整重读；无日期切换／响应串用 |
| 预算 | 三主批次合计491业务请求；`minutes_acceptance_summary.json` | HTTP最大3.291s、模型包络34.861ms、预测12666B；混合缓存48910335B／6项，均在4s／200ms／32KiB／64MiB／16项内 |
| 失败及工具真实性 | `minutes_budget_01`、`minutes_replay_budget_01/run.json` | 前者分组含一冷首轮，后者注入错误在首个有效请求前退出；均保留，当前以02新批次为准 |

实际HTTP使用原鉴权依赖和当前配置（`QUOTE_API_AUTH_REQUIRED=false`），未读取其他进程密钥，也未声称已验证要求登录的部署。混合验收含队列的冷整组8.83—13.05秒、暖整组4.33—9.62秒，不能说整页4秒完成；4秒为单次HTTP。分钟技术门禁通过不等于日线或完整四周期页面通过，页面仍由用户验收。

完整报告与命令（原记录：`reports/xxm_reference_rescue_r1_implementation_20261017/minutes_acceptance.md`）。本轮仅修改验收工具、其测试和状态文档，没有产品／架构依赖变化、正式写入、安装、提交、推送或部署。日线仍待用户通知下载完成，随后补原四周期门禁；Figma文字和研究原型清退仍按整体交付清单保留。

### 25.3 日线补齐后的恢复验收（2026-10-17，已获用户通知）

用户通知2020年1月起上证日线指标已补齐。13:31只读同一快照核查：2020-01-02至2026-10-16共1643条，与SSE开市日逐日相同，零缺口、零额外日期，必需字段无NULL；原262／452缺口记录仍保留，不能改写为当时完整。

恢复范围：沿用现有工具`--mode budget --formal-source --periods day`完成20真冷／20真暖、配对识别、LATEST和两并发，保持完整来源及原4秒／200ms／32KiB／64MiB／16项门禁；`--mode replay-budget --formal-source --periods day`补5个日线原路由历史场景；page audit默认四周期完成原16组整页／双标签混合。此前分钟独立预算仅在产品／工具源码身份无变化、完整混合中分钟输入身份及响应仍一致时沿用，不为凑同批次无意义重复已通过的独立门禁。

原日线输入新增更早历史，需独立检查M0冻结重叠值以及已有历史场景的普通状态、事件及完整预测语义；不假设扩历史后必然相同。若完整性、重叠或关键语义不符，保存失败并按根规则说明，不通过裁剪回2023、改预期或改算法掩盖。所有结果放新目录，页面仍由用户验收；本轮仅只读验收及文档对账，不扩大为产品改动、正式写入、安装、部署、Figma修改或原型清退。

### 25.4 恢复验收发现更早来源片段（2026-10-17）

2020年以来1643条的日期／必需字段预检通过。正式`daily_budget_01`却在预先核源阶段拒绝，未进入预测：当前`read_daily`无日期下界，已读到2017-01-03起片段；13:36有1724条、缺650个开市日，13:39一致快照1748条、应2374条、缺626个（2017年139、2018年243、2019年244），所有缺失均早于2020。来源仍在补入，不推断任务或完成时间。

因此本轮未取得日线HTTP预算或历史预测成绩，也未运行必然受同源影响的四周期整页验收。产品／工具／消费者30份源码与上轮分钟身份相同；没有修改算法或完整历史边界来通过验收。已向用户询问等更早来源完整，或先做2020起隔离计算预检（不算正式接口／页面通过）；未获选择前暂停后续依赖步骤。依据及完整缺失日期见恢复验收报告（原记录：`reports/xxm_reference_rescue_r1_implementation_20261017/daily_resume_acceptance.md`）。

### 25.5 2020起隔离日线预检（2026-10-17，用户已选择）

用户明确先做2020年起，并要求记录更早历史待补齐后再做。本轮只增加离线工具`xxm.daily_window_precheck`及主题内测试，不改产品来源／API／配置／算法；正式全历史入口及失败原件保留。范围固定为2020-01-01至当前统一业务日，早于2020的数据库记录只在本隔离输入中排除，不能进入产品读取代码。

| 约束 | 代码点／验证 |
| --- | --- |
| 真实输入与精确边界 | `capture → read_window`只读投影IndexFactorPro日期／close／DIF／DEA／MACD，限定代码000001.SH；SSE日历从2020起、预测需要的90日上界；1000行批次、最多2000日线行／3000日历行。日期必须等于整个显式范围的开市日，范围首端缺一天也拒绝，另执行原XxmBar／assert_continuous校验。来源、CSV／日历及SHA一同冻结 |
| 独立夹具合同 | 读取当前真实生产者ORM／字段后构造临时SQLite core_serving的相同投影表；只在内存建表／写入，供原真实路由／query／唯一内核／DTO消费，明确fixtureOnly／formalApiAccepted=false，不冒充真实PG／部署性能 |
| 完整识别与因果性 | 全部日线逐根回放并留事件账本；事件／原案例／1000根边界等前缀重放、恢复验证，假设预测前后真实状态不变 |
| 逐时点预测与预算 | 每个已完成日线端点走原预测路由，保留原校准／取整保护；200ms计算及32KiB、4秒局部请求／64MiB／16项仍生效。冷暖各20次、LATEST、识别配对及两并发属于隔离链成绩，不代表PG读源或全历史正式验收 |
| 旧样例与新增历史 | 核对M0重叠值，三个日线历史消失及8/15确认等独立已确认事件硬断言；5个旧API场景记录完整数学／display差别。2020新增前缀可能使旧CALIBRATION_FAILED解除，按实际恢复结果解释，不放宽250根校准／0.0005门槛，不为相同JSON裁剪前缀或改预期；第一阶段不足校准时保持PRECISION_PENDING |
| 反例与记录 | 测试2019行排除、2020首日／中间缺日、非有限值／重复、无未来日历、不可覆盖旧目录及内存只读接口输入。新增前缀造成旧普通状态／已确认事件变化时保存并说明，不把软件未知改成已证实 |

预算测试与其他本任务构建／回归不并行；不安装或改产品服务。输出新目录，保留全部原记录。更早历史清单另记为待办，恢复条件为用户通知后对当时实际最早源日到业务日的全量连续性／字段核验，通过后补正式日线及四周期16组整页／双标签。该待办不自动轮询、写源或发起下载。页面仍由用户验收，Figma文字及原型清退不在本轮扩围。

### 25.6 2020起隔离日线预检结果（2026-10-17）

§25.5已执行：14:05:59真实只读一致快照冻结1643条日线及2571条SSE日历，范围2020-01-02至2026-10-16，原M0的912条重叠相同。逐根93事件、97处完整前缀／恢复、四条独立截图事件及1643个预测端点通过，预测前后真实状态相同。最大模型包络159.519ms／响应13222B；隔离20冷每轮1691次step、20暖每轮0次，缓存1577017B／2项，LATEST及两并发通过。24项主题工具测试通过，字段投影、首日缺失、非有限值、固定时钟和缺未来日历拒绝均覆盖。

1643份中442份保留PRECISION_PENDING／CALIBRATION_FAILED，其余为24 CONFIRMED、431 NO_CANDIDATE、647 CONDITIONAL_ENTRY、99 READY。旧7/23、8/5、8/22日线案例解除校准保护，由更长2020前缀改善EMA初始化而非改算法／容差；50位Decimal独立复算最近250根全部回到0.0005内。8/15和10/13完整数学／display无差异，四条截图事件保持。不能把保护响应或模型相容当软件准确率。

代码级落点：`daily_window_precheck.read_window／validate_window`冻结真实字段及精确日期范围；`isolated_client`只替代存储／时钟／鉴权并关闭写入；`replay_checks`核事件字面金样本及恢复；`check`逐时点调用原路由、比较旧场景、记录包络与缓存。该模块不被产品import。源码对账25份产品／前端消费者均未变，无业务依赖／配置／合同调整。

原工具`bottom_history_acceptance.verify_cache_mode`同步纠正日线暖核验：日线设计每次读取SQL投影核源，缓存复用体现为零内核重算，不能要求零SQL读取；分钟仍同时要求暖轮零完整读源。14项范围／工具测试含此正反例，与10项隔离工具测试合计24项。只改验收判据以匹配已核代码，保留冷读确实加载、暖轮不得重算以及全部原预算。

详见完整结果及边界（原记录：`reports/xxm_reference_rescue_r1_implementation_20261017/daily_2020_precheck.md`）。以上是SQLite／固定时钟／鉴权替身的隔离链成绩，不是正式PG／网络API或整页成绩。14:13来源快照仍缺2018年52／2019年244日，合计296，原626／650记录保留；更早历史待办（原记录：`reports/xxm_reference_rescue_r1_implementation_20261017/before_2020_pending.md`）列出逐日清单和恢复条件。用户通知后再验当时完整来源、正式日线及四周期16组混合／双标签；页面由用户验收，Figma和原型清退不提前转为完成。

### 25.7 顶部9/24—25疑点研究执行设计（2026-10-17，只研究）

依据算法§12.25—12.26及用户“专注这里、先现有资料研究”。真实代码依据：`XxmCalculator.step`按原两段池、当前至少两根及`_select_eligible_reference`选择，`min_bars`不限制历史参照；9/24选8/30单根段，9/25走`dif_break`。CodeGraph explore已核唯一类及标记消费者，产品代码与API不改，研究子类不得注册产品。

| 执行约束 | 研究落点及验证 |
| --- | --- |
| 复用既有来源／证据 | `scripts/research/index_market/xxm/top_daily_ambiguity.py`只读现有冻结CSV／manifest及旧52标签来源；哈希核对、XxmBar校验、日线912重叠；日线最多2000、各分钟最多20000根，总40500根以内，禁止新查库／Lake或抓取网页 |
| 唯一变化、无双引擎上线 | `ReferenceGateCalculator`继承真实唯一类，只覆盖选择器；BASE直接返回原选择结果。T2／S2仅对原池中的候选加count>=2，保留最近原段价门槛与两段占位；ZC检查当根DIF>0，ZR检查参照DIF>0，均仅TOP。不改原min_bars、切段、池宽、DIF门槛或R1救回规则 |
| 原始证据与候选分离 | 字面保存52条旧标签及20 direct／32 mapped，时间仅转成当前ISO格式、case映射period，不重选锚点。另核底部历史三日线、2024/8/15及2025/3/17—19／2026/5/11—14等已观察顶部对照，旧未匹配点与新丢失点分列；保留有限来源差异及非独立性质 |
| 结果与因果性 | `audit`逐周期×BASE及四候选保存事件、差异、标签结果、池／段不变对账。日线9/24和9/25及每周期终点做完整前缀／恢复；不回填标签、不裁剪前缀。候选若局部去掉目标信号但破坏既有观察，记录反证，不修改预期 |
| 保护与输出 | 新目录`reports/xxm_top_daily_ambiguity_20261017_01`；事前protocol和保护清单覆盖产品／消费者、冻结CSV、旧标签及原图，事后SHA相同。每个周期／候选完成一个报告单元并打印进度，60秒墙钟上限，内存只存有界四源及当前单元；失败不覆盖旧证据、不自动恢复执行 |
| 必要测试 | 纯人工Wave与XxmBar字面样本分别证明：单根仍占池、最近门槛不被重算、不补第三段、TOP限定与S2底部反例、ZC当根而非段峰、ZR参照、严格零边界、原对象不被改写、BASE等于原类；预期不由待测选择器生成 |

研究只证明指定候选在已知输入／观察上的后果。不存在候选与当前输出不同即等于软件更正确的假设，也不计算软件识别准确率。若四种都被现有材料排除或仍有多种相容，原样报告；无软件当日直接证据时保留历史文字消失／参照资格／输入差异等未知。只同步研究结果到原方案，不迁产品、不重新做HTTP预算或更早来源正式验收。

### 25.8 顶部疑点研究执行结果（2026-10-17，无产品迁移）

§25.7按事前方案完成：日线1643、分钟17260／12945／8630共40478根，五种模式×四周期20单元，6.169秒；30前缀／恢复、分段与池保持、12字面测试通过。研究BASE另与真实`XxmCalculator`逐step及末快照相同，195份既有产品／消费者／源／旧研究及原图SHA不变。完整事件／参照、旧52标签、差异与补充来源见研究报告（原记录：`reports/xxm_top_daily_ambiguity_20261017_01/README.md`）。

T2、S2、ZC、ZR都去掉9/24—25且不丢旧52标签，说明旧集合无足够辨别力；新增12/15已确认整条链约束后，S2丢失结构及重入，不能作通用修法。T2、ZC、ZR仍相容。后续只读回查已有4/23的60分钟图，发现4/8区间同样未见模型那对文字；此处28根历史参照且DIF为正，ZC能同时解释、T2／ZR不能。它只提升ZC研究优先级，没有把静态缺省改造成软件NONE真值。

四候选分别有197／789／400／350个step输出差异端点，其中事件账本差异57／100／30／17；不是软件误报数量。ZC会连带改变旧TOP历史终止／消失，不是前端去掉两条文字，未来若采纳须重新设计预测／生命周期和Spec迁移，本轮不提前实施。现仍缺原软件当日明确状态、历史文字机制及精确数值；没有新配置、产品注册、源裁剪或正式写入。API／页面与原预算未改，本轮不重跑并冒称正式验收；2020前TODO继续等待数据补齐。

### 25.9 1/6日线原件核查设计（2026-10-18，无产品编码）

本步对应算法§12.28。只归档用户新给1/6日线及讲稿、读取旧`followup_trace.json`，按当前真实代码核验，不增加研究类或测试夹具。产品选择器仍在`calculator.py::_select_eligible_reference`；TOP首次激活／突破取消沿`step`原分支。四候选仍使用§25.7已冻结定义，禁止因新图临时改变T2／S2的单根段占位或ZC／ZR零轴定义。

| 核查项 | 代码／证据位置 | 独立依据与验收 |
| --- | --- | --- |
| 末端事件及三指标 | 新原图／讲稿、旧`followup_trace.json::day` | 软件当日明确DULL为预期；图上读数人工抄录，与源按显示精度核对 |
| 当前结果及参照 | `XxmCalculator.step`、`_select_eligible_reference` | 仅已有2020/1/2—2026/1/6日线前缀，最多1500根；与旧BASE完整step锚点对照，不将软件参照当作已知 |
| 次日口述点位 | `ProjectionState.advance/recover_projection`、独立Decimal递推 | 原MACD(12,26,9)与三位日线口径不变；只验证模型边界与“约4087”的接近程度，不能虚造软件分位点／严格等号 |
| 影响及保护 | 源、现产品、旧研究SHA | 原件逐字节保存；只写新证据目录及原方案／LLD状态，旧标签／运行／产品源码不变 |

无新参数、配置或消费者迁移；不查库、读Lake、联网或写正式数据。核查上限60秒，中断保留原件及已得结果但标不完整，不自动恢复／扩大样本。文档完整性、改动链接与差异检查后再汇报；日线2020前TODO和4秒／200ms技术门禁不在本步执行范围。4/8及附近60分钟已登记用户无法找到，不再重复提出该材料请求。

**核查结果：** 1/6新证据报告（原记录：`reports/xxm_software_case_20260106_day_20261018/README.md`）保存原图及完整讲稿，确认直接TOP DULL阳性；四项显示值与源一致。1457根原前缀、真实产品及四候选与旧1/6锚点相同，T2／S2漏此阳性，BASE／ZC／ZR相容。候选定义及旧52标签未调整；只在冻结其余规则前提下排除T2修法，不声称读到软件内部11/13参照。

50位Decimal递推与真实投影一致。模型下一根严格日线三位DIF取消边界约4087.60919954，两位首个取消4087.61；4087.00及4087.60仍DULL，4087.61输出CANCEL。作者口述约4087是近似条件，不能当精确软件边界或实际次日事件。运行约0.10秒，4份产品、2份研究代码和4份旧研究证据SHA保持，无产品配置／DTO／消费者／预测编码变更。后续只从现有差异证据区分ZC／ZR，不在本步迁移公式；1/8重复补图不再要求，原预算及更早TODO不变。

### 25.10 ZC／ZR分歧证据审计（2026-10-18，无算法编码）

对应算法§12.29；只复用原`top_daily_ambiguity.py::ReferenceGateCalculator`定义及旧`run_01/{day,m60,m90,m120}_{ZC,ZR}.json`，不修改或重跑候选。`calculator.py::step`先把本根DIF纳入段最高值，`_select_eligible_reference`要求TOP段最高DIF严格低于参照；结合`wave.dif≥bar.dif`证明ZC资格蕴含ZR资格。此证明以原分段、段最高比较、两段池及选择顺序固定为前提，不推断软件源码。

| 核查项 | 实际落点及读取 | 验收与禁止 |
| --- | --- | --- |
| 事件差异 | 旧8份结果的`events`，按time聚合列表 | 保留普通事件及历史撤销，分类DULL首次差异／传播；不以每时点只留一条覆盖多事件 |
| 时点数值 | 旧`differences::{basePoint,point}`；必要时原冻结日线6/23—26、60分钟6/23—25少量行 | 只取明确字段／日期；软件精确数值未取得时保留偏差风险，不新查库、湖或读新全局数据 |
| 讲稿与图片 | 已归档6/24字幕、6/25—26原图及本主题其他既有稿 | 引用原始上下文及所属周期；“日线DF负值、没红脚线”不得直接当成60分钟DIF零轴门禁 |
| 独立约束 | 当前选择器不等式＋字面示例 | 段峰与当根分开；不把逻辑关系、相似图或当前模型标签当软件新真值 |
| 输出／保护 | 新研究目录、原方案／LLD及研究记录 | 旧结果／观察及相关产品SHA保持；无配置、API、预测、前端或消费者迁移 |

每次本地核查最多60秒，中断不覆盖旧证据，不自动扩大时间／对象；源文件只作原件身份及少量投影读取。研究无法定式也须输出剩余最小证据，不新增猜测公式。文档完整性／链接及差异检查后交付；正式4秒／200ms、更早验收TODO和开发授权均不在本步推进。

**核查结果：** 本轮报告（原记录：`reports/xxm_top_zero_axis_discrimination_20261018_01/README.md`）保存8份旧结果完整按time分组的事件及point对照。事件差异时点0／6／5／2，point差异0／3／21／20；13个事件分歧不是13组软件误报。首次TOP资格有`bar.dif≤wave.dif<ref.dif`，因此ZC蕴含ZR，不能用普通正DIF阳性判别；不把门禁移到持续DULL或历史标签。

2023后唯一未暂停的可取证区间是6/24的60分钟：10:30本系统DIF -0.075073、柱+7.733491，ZR DULL／ZC NONE；11:30二者同为DULL且后续同点取消。已有37份文字无明确零轴关键词，6/24稿无60分钟首根说明；6/25—26原图实际选中120分钟。6/24“DF负值”转写不能直接解释为DIF门槛，次日稿说明昨日DIF约10.7，与源+10.741／负柱自洽。软件10:30读数和首次标记仍缺，不以当前模型负号代替软件负号。

本轮只提取既有CSV少量16行及旧输出，不新增源／重跑候选；64份相关代码、输入和旧证据SHA保持，新外部材料／软件标签／产品改动均为0。待关键外部证据后再讨论首次激活及预测／历史传播的实现迁移，本步不改配置、DTO、消费者或预算，不启动更早TODO。

### 25.11 6/24的90分钟补图核对（2026-10-18，不改计算代码）

对应算法§12.30。读取旧90分钟三份结果中6/24当天事件，核当前`calculator.py`、`spec.py`及原CSV未变；从旧CSV只摘取6/23—24六根的时间、收盘、DIF、DEA、MACD，保存软件人工读数、每项差值及原图校验值。原图末端钝化可确认，绿色消失的确切身份和时刻不按模型自动填写；两种待核规则在该日结果相同，不能拿本图决定首次顶钝化是否要求当根DIF>0。

新材料和报告只写`reports/xxm_software_case_20250624_m90_20261018/`，旧计算结果不覆盖。核查最多60秒，失败留下原图／异常并标未完成，不自动恢复或扩源；没有新代码、参数、配置、API、预测或前端改动。所需60分钟用户已确认未找到，原§25.10补图请求停止；后续等明确规则说明或有时刻和读数的软件记录，不继续要求类似但不能区分的图片。文档、链接及原文件检查通过只代表本图核对完成，不等于剩余公式明确或产品验收通过。

**核对结果：** 90分钟补图报告（原记录：`reports/xxm_software_case_20250624_m90_20261018/README.md`）保存原图及人工读数。软件末端钝化与当天模型相容，但软件DIF5.585、DEA-0.078、MACD11.326和源5.607457／-0.047738／11.310390不同；不按取整解释、不自动校正。两个待核规则及当前算法的当天事件相同，模型11:00／14:00不写成软件已确认时刻。仅核六根旧记录和6份文件，未改计算代码或消费者；原§25.10所需6/24的60分钟也已未找到，停止重复请求，不因缺图进入开发。

### 25.12 查找作者公开规则说明（2026-10-18，不改计算代码）

对应算法§12.31。本步只查公开文章，保存能读到的原文出处、发布时间及短摘录，不新增计算或抓取脚本。每条资料说明它是否直接回答“DIF≤0时能否首次顶钝化”；只解释价格和DIF是否创新高、柱色、4浪或结构转向的文字，不充当这个问题已解决。

保存位置为`reports/xxm_public_rule_search_20261018_01/`；旧图片、文字和计算文件保留。只用现有网页工具，不登录、安装、下载软件或访问数据库／Lake。网页正文缺失、只有搜索摘要、作者身份未确认、年代或参数不同，均单独写明；不靠换网址或错误转写补出作者没说的话。相关计算代码前后检查，原方案及研究记录同步，文档／链接／差异检查后交付。没有代码、参数、配置、接口、消费者、预测或依赖改动；不能从找到相似说法直接进入开发，更早验收TODO不启动。

**查找结果：** 来源及取舍（原记录：`reports/xxm_public_rule_search_20261018_01/README.md`）已记录。没有直接规则可迁入`calculator.py`：2014年概括定义未写DIF零轴限制，不能据此断定没有；2015年4浪穿轴用的是5、34、5参数；2018年0.082／4.888原文摘要说MACD值，不能改成DIF。官网2017-01-06“去除重复钝化”未给实现，不新增合并／过滤；官网2016-09-19选股当根、预警下一根的说明不用于平移指标窗标记。代码及旧研究前后检查另存报告，不新增软件已确认事件、配置或测试预期；两种DIF大于0条件均未得到确认，本步研究完成不等于允许修改计算内核。

### 25.13 核对9/24、9/25当日日线图（2026-10-18，不改计算代码）

对应算法§12.32。沿用当前`calculator.py::step`、`_select_eligible_reference`及`spec.py`，只核文件与原结果是否一致；从既有日线三份结果按2024/9/24和9/25摘录六个记录，不运行新候选、不读取正式行情。原件顺序为9/25在前、9/24在后，必须按图片页头日期归档，不按附件编号推测日期。

只写本步报告目录和原方案／LLD／研究记录。记录指标窗目标文字是否可见，与模型DULL／CANCEL分开；不能把未显示文字直接写成原软件`ordinaryState=NONE`，不能把我们的8/30参照写成软件已确认参照，也不把MACD红柱或侧栏高9当成顶部钝化。软件读数与模型逐项比较，未读清的末位留空，旧标签不改。本步无配置、API、预测或消费者迁移，原核心代码及旧计算文件前后保持。

单次本地检查60秒内，失败保留文件及异常，不扩大读取或改数值；检查原图复制、代码／旧结果校验值、文档、相对链接及差异。报告必须分别说明“与当日图多出标记”和“缺少哪个计算条件尚未确定”，不以两张图批准DIF零轴条件。2023/9/25的90分钟已未找到，停止重复请求，更早日线验收TODO不启动。

**核对结果：** 当日原图和六个记录（原记录：`reports/xxm_software_case_20240924_25_day_20261018/README.md`）已保存。两天当前输出比当日图多出顶部钝化／钝化消失；9/24指标三值相同，9/25 DIF差0.001，未强行改成相同。`step`的首次DULL与随后`dif_break`关联同一8/30参照；1%结构转向不参与，不能改页面或转向比例代替研究首次资格。两种DIF正负限制的旧结果在此均无事件，尚不能判定哪种条件正确；截图未见字不填成软件内部NONE，原代码、配置、接口和测试预期不变。

### 25.14 两个深市指数的日线取证日期筛选（2026-10-18，研究执行）

对应算法§12.33，研究对象399006.SZ、399001.SZ，视频候选仅2022/9/13—2024/8/30。产品仍只允许000001.SH。CodeGraph query／impact定位`ReferenceGateCalculator`及原审计调用方；已读`XxmCalculator.__init__/step/_id/snapshot/restore`、原读取、两种选择限制及测试。新增编排不改它们，不恢复旧算法；现产品对象限制、底部修正、严格价格和DIF比较、原始最近两段、单根历史占位全部继续生效。

#### 实现和读取

1. 新研究模块`scripts/research/index_market/xxm/cross_index_daily.py`只负责采集、校验、逐指数比较、候选分类和保存；复用原研究类BASE／ZC／ZR，不增公式或门槛。旧`audit/new`写死研究身份，旧`read_window`写死上证／最新日期，不能直接用于本步，故编排另写；旧算法与原文件不改。
2. `capture_source`经已有只读session进入当前生产goldenshare库，投影白名单`core_serving.index_factor_pro`六列，两个代码分别读取2020/1/1—2024/8/30，按日期每批500，逐指数最多1200；沪深共用SSE日历仅日期和开市标志，同区间最多2000行。先核列、计数和小样本的真实合同。`validate_rows`拒绝对象不符、日期乱序／重复／缺口、NULL、非有限值、非正收盘及超限；使用同一真实日历核所有开市日，不假装指数停牌补空。
3. 产品构造器限制保持不动。离线数值计算保留现构造方式，只传包含真实代码／源校验值的独立`source_identity`；`step`算法不按指数身份分支。产品内部事件编号、关联编号和`tsCode`不得充当外层真实指数身份，不进入报告或API。结果另存真实`ts_code`、输入校验值、数值、日期、类型、原因及历史参照；不得把深市行情标成上证行情。恢复在同来源同指数内完成，跨来源拒绝。
4. `scan`每根同时推进原规则与两种条件；输出普通首次顶钝化的直接分歧及相关后续事件，检查柱段和历史池相同；原规则与直接`XxmCalculator`逐根比较。按2020起与2021起输入分别核目标区间普通事件，若有差异，列为起始历史不足，不给用户当作可靠候选。只报告普通事件及数值／参照，不将历史记录的编号差别计作规则分歧。
5. `classify`优先保存当根DIF≤0、历史DIF>0且两种条件首次事件不同的日期；另存当前规则有首次顶钝化、两种条件都无的多报核对日期。标记为模型预测，不推断软件NONE；给出需要查哪根、DIF是否可读、后续是持续还是消失。最多推荐三日，无差异如实报告。原软件参数和版本仍需截图确认，不因跨指数比较就宣称软件全指数公式相同。

#### 保存、恢复与预算

本步唯一研究设置在模块不可变Spec中，保存到报告；没有env／Settings／数据库／页面新配置。源、结果逐指数保存，完成后写校验值；完整manifest只在两份源都通过后生成。新目录拒绝覆盖，显式resume只复用设置、代码和文件校验值都相同的完成单元；失败不删除已完成证据，半文件不作为输入。连接5秒、每查询15秒、采集总60秒，计算含前缀／恢复60秒；中断后复核与最多一个指数重算60秒，测试／报告最后检查60秒，整体240秒上限，单指数1200根／20MB。超过预算、缺行或源变动必须失败留原因，不自动放大查询或重试循环。

#### 测试及本步验收

新增主题隔离测试：正常不同收盘可通过；外来代码、NULL、缺开市日、重复、逆序、越界、超限被拒；两类候选用独立字面事件判定，不调用待测分类生成expected；内部产品对象限制仍拒绝深市代码，真实外层身份不被内部编号覆盖，来源不同不能恢复；中断后保留完成指数，改过的源／结果拒绝复用。继承运行原选择器字面测试，使用真实生产列／小样本核读取合同，完整读取严格限两对象日期，不把合成数据或程序彼此相同称为软件验证。

执行前先完成上述代码与方案审计、真实合同核对和离线测试；采集后读回文件校验值、交易日数量／NULL及预算，再做两指数候选筛选。输出`reports/xxm_cross_index_daily_20261018_01/`；相关产品、原研究类和既有软件图证前后保持，旧52项标签不改。最后运行文档、链接、差异及源／代码校验，报告日期的作用和限制；不提交、不部署、不启动更早日线验收TODO。

**执行前检查及纠正：** 实际生产视图六列类型与ORM相符，但视图列均声明可NULL，所以仍须逐行拒绝NULL；两个代码各1132行、必需值无NULL，四行样本已保存。2026/10/18管理员纠正：沪深A股统一开休市，现有SSE日历直接核对两个指数，不要求SZSE独立记录。本步按根AGENTS新规则继续，日历SQL固定`exchange='SSE'`，范围和最多2000行不变；核验自然日连续、布尔开市值及全部应有交易日。不调用Tushare、不改正式数据集或request builder。原选择器12项字面测试通过，仍不能算作两个新指数的软件验证。

**本步执行结果（2026/10/18）：** `cross_index_daily`及主题测试已落地，源实际采集2264条行情、1704条SSE共用日历（1132开市）。目标区间每指数478根，三组所有状态／事件相同，首次顶部钝化共3次且两DIF皆正；两条件区分候选0。每指数六次前缀／恢复与跨来源拒绝、原规则逐根等于产品、分段／参照池一致、2021起普通结果相同均通过。完整完成文件可原样继续，已实测再次运行不查询生产库、不重算指数、不覆盖已完成源／结果；首次采集0.695秒、计算0.231秒。源合同真实核验与隔离程序测试分别记录，不声称原软件新标签通过；本轮未放开产品指数身份、未改内核／预测／API。详见本步`findings.json`、`first_execution.json`、`run_01/`及最后验证记录。

### 25.15 核对2023/1/6深成指日线原图（2026-10-18，不改计算代码）

对应算法§12.34。只从`xxm_cross_index_daily_20261018_01/run_01/result_399001.SZ.json`及同目录源摘录目标日期，先验证完成文件及相关代码校验值。原图人工读数独立记录：顶部身份／日线／日期、末端是否有黄色钝化及各数值；图上历史文字不当作当日事件，右侧高9／低9与钝化分开。内部状态和软件参照未知，不从模型填写软件字段。

审计当前`calculator.py::step/_select_eligible_reference`和`spec.py`，核原始最近两段、当前两根、最近段价格先检查以及价／DIF严格比较。模型最近段与更早段的价及DIF只用字面算术对照；不写新选择器、不重放、更不将“若省略最近价格检查则旧段符合条件”直接确认为软件实际分支。软件指标值和源分别保存，允许记录0.001差异，不重新计算MACD或修改容差。

只写新报告目录、原方案／本LLD及研究记录，原图字节复制，完成后验证哈希；相关产品代码、跨指数源／结果和旧图证保持。预算60秒，失败留异常及已完成文件，不扩大输入或重试；文档完整性、相对链接及差异检查通过仅说明本图核查完成，不能声称零轴条件已区分或软件公式唯一。没有API、消费者、依赖、配置或测试预期变更，2020前验收TODO不启动。

**本图结果：** 末端未见黄字与三组计算无事件相容，不新增软件内部NONE标签；四数中收盘／DIF／DEA按显示精度相同，柱值相差0.001。模型最近段价格先检查失败，更早段价与DIF单独均满足，支持保留最近价格先检查；不新增省略检查的候选代码，不宣称软件唯一算法。原件与一个日期摘录及算术在`xxm_software_case_20230106_sz_day_20261018/`，原产品、跨指数来源／结果及旧图证保持。零轴两条件仍未区分。

### 25.16 2023/1/6上证50与沪深300图文核对（2026-10-18，研究执行）

对应算法§12.35。先查`IndexBasic`当前生产者字段及三个代码真实名称、`IndexFactorPro`六列的有界计数／NULL／目标日样本，确定实际可用两指数身份。沪深300图号399300，数据库代码必须单独确认，不把名称相近直接当同源MACD。共用日历从上一研究冻结文件校验后裁出2020/1/1—2023/1/6；只有全部应有交易日、对象、数字有限／非NULL／正收盘、顺序唯一、最大800根均成立才进入计算。

补充代码审计后直接复用已有能力，不新增执行模块或修改旧Spec：`bottom_history_acceptance.readonly_session`执行固定两代码、六列、日期键分页500的只读SQL；逐行先核真实代码、NULL、最多800行，构造XxmBar后交给`daily_window_precheck.validate_window`核共用日历连续性及数值；`cross_index_daily.seal/read_unit`保存并校验逐指数源／完成结果，`calculate`复用原三条件获取目标日及两根前记录、同段首次TOP激活日期，核2021起目标结果。保留BASE逐根等于产品、分段／池一致及前缀恢复／跨来源拒绝。实际读取范围、图片代码和源代码对应写入本步执行审计JSON，不新增env／Settings配置。结果只存真实代码、数值、日期、参照和文字，禁止把内部产品编号当真实证券身份。

旧固定代码入口不改、旧manifest／结果保护不放宽。源／结果及源合同计数逐个保存校验值，完整结果按同设置／代码／输入可继续；半文件／变动文件失败保留，单次新输出拒绝覆盖。查询／采集／比较／中断继续／最后检查预算及20MB／800根限额见原方案本步；无Settings／API配置或DB／Lake写入。来源不符或缺行不兜底、不重算MACD、不自动用另一个代码顶替。

主题隔离测试只用独立字面数据，覆盖两身份正常波动、缺日／NULL／错对象／重复／越界／超限拒绝，软件有字／无字原样记录、源码身份不放开，原图复制和完成文件被改不能复用；预期软件上证50末端黄字、沪深300末端未见字来自原图，不能用模型结果倒填。执行前完成CodeGraph query／impact和上述真实代码、方案审核及测试，再作有界读取；最后核原图SHA、读数、真实源完整性、代码／旧证据不变、文档／链接／差异。仅该图比较，不启动新日期筛选、产品迁移或更早历史验收。

**执行前源检查：** 三个预检代码名称已核，上证50代码000016.SH、沪深300两代码均有732条且四必需数值NULL为0；1/6两个300代码数值相同。实际只取图号对应的399300.SZ及000016.SH，不混用上海300历史。收盘／DIF／DEA／柱值已取得单日实样，与图逐项比较保留末位差异。复用通用日线校验和原计算，无新增脚本／参数；先运行原输入／选择器／保存及日线连续性隔离测试，再有界读取。

**本步结果：** 两张原图分别黄字／未见字，与当前上证50首次TOP DULL、399300.SZ无事件相容；不由模型倒填软件首次时刻。两个图号对应各732条源，无空值／缺日，沪深300原399300.SZ历史直接可用，无代码替换。复用既有连续性校验、三条件计算和完成文件能力，无新增执行代码或配置；41隔离测试、每指数六次前缀／恢复、跨来源拒绝、原规则逐根相同、2021起目标相同均通过。上证50未超过更早段价却有钝化，条件性反对对两段一律要求破价；DIF两个条件依旧未分。各0.001显示差异、原图／源／代码校验保留于新报告，不改产品内核或测试预期。

### 25.17 上证50、沪深300的日线日期筛选（2026-10-18，只研究）

对应算法§12.36及管理员继续授权，固定000016.SH、399300.SZ，不改沪深300代码；候选2022/9/13—2024/8/30，输入2020起。先用`cross_index_daily.read_unit`核§25.16两份各732源与完成标记，原件及旧结果保留。`IndexFactorPro`六字段合同沿原真实schema和样本；只读session先COUNT／NULL及明确日期样本，再按两个代码、2023/1/6—2024/8/30、日期游标分页500，尾部每指数最多500。1/6重叠按六列字面逐项相同才可组合；原prefix加尾部第二行起，最多1200，拒绝错代码／NULL／bool／非有限数／非正收盘／缺日／重复／乱序／越界。数值构造XxmBar后复用`daily_window_precheck.validate_window`核完整共用日历。

不新增模块或修改原`ResearchSpec`的代码／范围；原`calculate`支持任意独立日线数值，仍按同一2022/9/13筛选下界和原三条件复用，`classify`提取两类首次分歧，不能按每根最后事件抹掉同根历史事件。BASE直接与产品逐根相等、三组wave／history相同、同输入前缀／恢复及来源错配拒绝均沿用。2021起再计算目标区间普通状态／事件／参照；不相同则该指数不推荐。1/6结果须与已有两图研究的逐组数值输出一致，不以只核新候选跳过已有修正。结果外层实际代码及源哈希绑定，产品内部编号不出现。

范围与预算集中保存本步审计JSON，固定参数不暴露运营或用户；无配置／contract变更。尾部、合成源、结果分代码`seal`原子完成、`read_unit`读回；完整汇总仅在两对象完成后保存。恢复先核本步范围、全部代码／源身份及完成标记；只补未完成文件或一个未完成指数，旧完成结果不覆盖，任何变动拒绝，不扩大日期／对象／读取。源采集、比较含恢复、继续复核、最后验收各60秒合计240秒，查询15秒／连接5秒、每指数1200根及20MB；原图／旧计算／旧源哈希前后相同。

测试复用已核独立真实字段合同的输入与选择器字面测试、文件篡改与保存恢复、日历完整性，41项与本轮有关的检查；两个无关未来预测／Web测试不作本步门禁。实际有界验证全部源行、重叠六列、目标日期数量、1/6旧对照、候选首次事件及字面DIF正负和价格条件；最多推荐三日、重复链不当新案例，不把模型事件写成软件已证实。输出完整分歧列表与优先日期，无差异如实报告；文档完整性／链接／差异通过只证明研究记录可复查，不证明软件公式正确。产品、预测、API、页面、原52标签与更早TODO不改。

**本步结果：** 每指数旧732＋尾401－重叠1＝1132，重叠六列相同、全应有日一致；读回源及完成文件校验，1/6旧记录同值。每指数478根目标三组状态／事件相同，两类候选均0，2021起普通结果无差异；原规则逐根等于产品、分段／池不变、每指数六次前缀恢复与错来源拒绝通过。上证502次、沪深3002次首次TOP激活均当根／参照DIF正，故未给新补图日期。41相关隔离测试通过，未扩读新日期或分钟，未改代码／配置／合同／产品。旧资料／代码前后保持，详见本步报告与verification.json。

### 25.18 2024/9—2026/9两指数日线候选筛选（2026-10-18，只研究）

对应原方案§12.37和管理员扩范围／多给候选授权，实际两代码和六列同§25.17。复用其2020起各1132条源及完成校验，尾部日期改为2024/8/30—2026/9/30，日期游标500分页，每代码最多600；先有界计数／空值和指定样本，8/30重叠六列不同时拒绝。合成每指数最多1800条，真实身份逐行核，拒绝NULL／bool／非有限／非正收盘／缺日／重复／乱序／越界。复用`daily_window_precheck.validate_window`，其MAX_ROWS2000及MAX_CALENDAR3000足够本步1800／2600上限，不放宽旧保护。共用日历从R1采集manifest核SHA后裁到2026/9/30，日期和开市逐项检查，无日历源接口调用。

数值与保存原函数复用，不新增程序或改旧Spec／源码；`calculate`原2022/9/13之后输出完整保存，在外层仅对2024/9/1之后调用`classify`，这样原2022/9—2024/8全部记录须与旧结果相等，原修正不因扩大日期失效。原BASE逐根等于产品、三组wave／history相同、每指数六次前缀／恢复及错来源拒绝、2021起新增区间普通输出相同均沿用。外层真实代码及源哈希绑定，产品内部编号不输出；源／结果完成文件改动拒绝复用。

本步审计JSON统一记录实际范围／批次／上限／代码身份和单步预算，无新Settings／API配置。源尾部、完整源、结果、汇总逐对象原子完成，新输出目录拒绝覆盖；继续先核设置和代码／来源、完成标记，不重算已完成对象，失败／半文件保留但不当输入。采集、计算含恢复、继续复核／一个未完对象、最后检查各60秒，总240秒；连接5秒／查询15秒，单指数1800根／20MB，日历2600日。

候选不限三日：第一类为当根DIF≤0、所用历史DIF>0、两个条件首次激活不同；第二类是原规则首次DULL且两个限制无普通钝化。每条保存真实日期、当根／段最高DIF、最近及所用历史段、三组事件／状态、随后十根；后续取消或延后激活只能标同案例对照日，不能把它们充成新独立案例。已知上证9/24—25和两指数1/6原图不替代新标签；新增软件标签仍0，模型候选待图核。

复用41项相关隔离测试，实际源重叠／全日历、旧窗口逐字段相同、候选价及DIF字面资格、首次事件与结构返回区分、源代码身份及旧证据SHA为真实有界验证。输出全部候选及按作用的优先列表，无第一类则明确，不能以第二类多报核验当唯一公式确认。文档／新链接／差异检查和引擎表最后位置均核，不改产品／预测／API／页面／旧52标签／更早验收TODO。

**本步结果：** 每指数新范围504根，ZC与ZR全部记录相同，无直接二选一候选。原规则只在上证509/25首次DULL不同（两个限制无），9/26取消及9/27旧结构历史输出是同链后果，单独标观察日；沪深300无任何差异。历史参照8/16—8/30为11根，负DIF-7.869，当根-9.096，价资格严格成立，更早正DIF段价不合格；字面比较及事件类型已核，不把后续当新首次候选。所有1＋2观察日期已输出，无固定三日截断或正DIF凑数。

实际补每代码505条、重叠同值，组合1636条对应共用1636开市，无NULL／缺日，原旧窗口478根逐字段相同。原计算及分段／池、12次前缀／恢复与跨来源拒绝、2021起新增区间普通结果均通过，41相关隔离测试通过；没有新增执行代码／配置／合同。源、结果、候选、软件待核限制与旧资料校验保存在`xxm_50_300_daily_dates_20261018_02/`，不改产品。

### 25.19 改筛创业板、深成指2024/9—2026/9日线（2026-10-18，只研究）

对应原方案§12.38，用户明确上证50目标区间无资料，原9/25—27不再请求；材料不可得不写软件NONE，旧结果不覆盖。改查399006.SZ与399001.SZ尚未筛选的后半日线，候选2024/9/1—2026/9/30；输入2020起。先`read_unit`验证原深市研究各1132源及完成标记，复用上一轮SSE日历2465自然日。真实生产者仍IndexFactorPro六列及相同合同；只读session先两代码有界count／NULL／边界实样，再日期游标500分页尾部2024/8/30—2026/9/30，各最多600。8/30重叠六列须相同，组合最多1800，逐行对象／日期／NULL／bool／有限数／正收盘和全日历经原`validate_window`检查。

不复制选择器或修改原Spec：调用原`calculate`（同三条件、原底部修正、原两段池及价资格），BASE逐根等于产品，wave／history相同、每指数六次前缀／恢复及跨来源拒绝；2021起新增区间普通事件／状态／参照相同，原2022/9—2024/8全部记录与旧研究相同。外层只对新范围调用`classify`，保存所有独立首次差异与后十根，原同根历史事件不丢。按DIF≤0／所用历史DIF>0区分第一类与原规则对两个限制的多报第二类；没有第一类明确写0，后续取消／历史消失只能标辅助，不伪装独立首次。

范围和预算单一审计JSON，无新env／Settings／API配置、无运行入口变更。原`seal/read_unit`逐源／结果原子完成并读回，完成汇总仅在两指数完成后保存；继续先核范围／代码／源／完成SHA，复用完整对象，不重算已完，半文件／变化失败留存，不自动扩源。1800根／20MB每指数、日历2600日，查询15秒／连接5秒，源／计算含恢复／继续复核一个对象／最后验收各60秒总240秒。

复用41相关字面与合同检查，实际重叠／完整性／旧窗口不变及候选价／DIF资格独立算术复核；软件新标签仍0，截图只在拿到后独立记录。最后核旧图证／源／结果／代码不变、原图可得性单独追加、文档／新链接／差异和引擎表最后。无新代码、公式、配置、依赖或产品内核／预测／API／页面变更，更早TODO保留。

**执行前补充：** 如深市日线仍只给2024年9月，直接读原上证m90／m120各BASE、ZC、ZR旧结果；先核同算法specHash及原受保护产出代码，六份文件单份≤20MB，逐周期处理，候选日期2022/9/13—2026/9/30。按时点合并events与differences中全部事件，首次DULL需route=activation且direction=TOP；与ZC／ZR当根ordinaryState和events核对，不能取最后事件覆盖或把history差别当首次。明确当根DIF、历史ref和价来自旧模型，不充软件真值。排除已缺2023/9/25 m90及2024/9同批，60分钟完全不查。仅旧证据摘要，不访问Lake／分钟库、不重跑、改代码或参数；顺序读释放，成本计入本地60秒阶段，结果和旧文件前后SHA检查。

**本步结果：** 两独立首次区分候选：399006.SZ 2026/3/12（当根-1.841、近段12.380）与399001.SZ 2026/4/13（-0.002／59.454）。六关联观察日及模型状态／事件／参照保存，3/13和4/14为当根条件延迟首次，4/15／16为深成指取消时间分歧；不充六个独立案例。逐项字面价格／DIF和实际事件核，软件仍未核。近零读数、创业板累计价而非当根价、单根历史及其他参照规则的限制已列清，不直接把候选变软件真值。

各1132旧＋505尾－1＝1636，对应全部开市日；旧478窗口、源重叠完全相同，原数值／分段／池、12次前缀恢复／错来源拒绝、2021起新普通结果及41相关隔离检查通过。上证50缺图不再请求；日线已够目标，旧分钟后备仅核清单未启用，不读Lake／分钟库或重跑。无新代码／配置／合同／内核／预测／API／页面变更，旧资料保持。

### 25.20 4月16日深成指原图与四个旧观察日核对（2026-10-18，只研究）

对应原方案§12.39。只读新附件和`xxm_sz_daily_dates_20261018_02`的399001.SZ源／结果，先按完成文件核SHA，再摘4/13—16既有记录，不调用计算器重算。代码核对仅限现`ReferenceGateCalculator._select_eligible_reference`两种DIF条件及产品首次选择／突破分支；原规则和历史DIF条件13日激活、15日取消，当根DIF条件14日激活、16日取消，是待比较的模型预测，不当作软件日期。

原图、软件独立读数及黄／绿文字可见性单独保存；图中字从所在K线向右展开的可能性与具体日期分开。参考已存1/6图只能辅助理解排字，不能代替本图日期确认。若出现“14日钝化、15日消失”的组合且独立确认，则两种原候选均不能完整解释，后续须先审计历史参照选择，不得只取其中一个事件宣称候选通过。本步不提前增加第三种公式，也不因为末位差异改源或参数。

新报告按原件SHA、旧完成校验、四行摘录及文字未知项验收；原源／结果、代码、软件旧标签前后保持。文件缺失／SHA不同拒绝继续比较，保留未完成证据；中断继续先核已存原件和旧完成身份。单文件20MB、本地60秒、最后校验60秒，管理员答复未到保持待确认，不自动补读。无DB／Lake读写、无新增脚本／运行入口／配置／API／消费者变更、无需新内核回归；只做文档和证据文件检查，更早验收TODO不启动。

**本步结果：** 新原图及四日摘录（原记录：`reports/xxm_software_case_20260416_sz_day_20261018/README.md`）独立确认黄／绿文字存在；16日收盘按显示精度相同，DIF140.086对140.087、DEA2.066对2.067、柱276.041相同，不用末位差异反推13日符号。软件事件日期仍未确认，文字起点初步像14日／15日，待管理员确认绿色对应阴线还是最后阳线。两条件到16日均无钝化，不能将本图直接判某候选通过；若14日／15日组合被确认，须重新核参照选择，不能只增加DIF条件。旧源／结果完成SHA与四日事件核对通过，原代码、旧图证及冻结文件保持，无重放或产品变更。

### 25.21 4月16日讲稿补证及日期修正（2026-10-18，只研究）

对应原方案§12.40。用户全文中的日期及“深成指今天钝化消失”独立于模型，按4/16登记当日事件，撤回上步偏向15日的文字位置推测。首次黄色钝化日期、4/13软件DIF及实际选中参照仍未知；不能把模型4/14激活反填为软件事实。原文字稿仅保存与本题有关的逐字段落，标明摘录、未核原音频。

先核既有399001.SZ源／结果完成SHA，再摘3/11—13和4/13—16七个既有日期：核三日柱色、3/13历史中单根进入前后两段变化、两候选消失事件及各自锁定参照。当前`XxmCalculator.step`把完整旧段写入`history[old_sign]`再按`max_refs`截取，单根也占一段；`_select_eligible_reference`先核近段价，再在两段中挑选合格DIF参照；研究仅在此基础加当根／历史DIF条件。不修改这些实现或另写计算器。

产品／历史DIF候选4/15突破59.454，当根DIF候选4/16突破124.162；数值对照只验证旧输出能解释哪一天。若假设跳过单根而让1月286.512继续占位，16日140.087尚未越过它，这是算术比较，不能反过来断言软件具体用了124.162。讲稿“一根红柱”的具体日期仍属模型对应，不由作者未点明的文字确认为3/12。

新资料与结论只写原报告`transcript_update/`、原报告最新状态和三份原文档；旧JSON、原件／裁剪、完成文件及代码SHA保持。单文件20MB、七日期、本地60秒／最后60秒，失败保留、续核身份、不补源或重跑；无新代码／配置／消费者／契约／DB／Lake读写。最后核关键句、字面事件和独立不等式、旧证据未改、文档／链接及引擎表最后位置。仅本例支持当根条件，不能据此开放开发或撤销其他未决项。

**本步结果：** 新讲稿补证（原记录：`reports/xxm_software_case_20260416_sz_day_20261018/transcript_update/README.md`）按用户全文的日期与“今天”记录4/16当日钝化消失，旧15日视觉推测撤回而原JSON保留历史。当前／历史DIF条件4/15突破59.454，当根DIF条件4/16突破124.162，后者与讲稿日期相容。3/11—13柱值负／正／负，单根进入后历史从1月286.512、2月底124.162变为124.162、59.454；不忽略单根的模型范围与讲稿理由相容。具体单根日期、参照124.162及首次黄字仍不是软件直接事实。七行、完成SHA及不等式核查通过，不查库、重放或改产品；后续先用既有样本查当根条件反例，再决定开发。

### 25.22 首次当根DIF条件的已有样本回核（2026-10-18，只研究）

对应原方案§12.41。CodeGraph已定位现`ReferenceGateCalculator`及调用父类选择器，源码核`audit/read_inputs`可复用；不另写计算或维护入口。原`audit(period,bars,variant,observations,deadline)`每次同时运行BASE与指定候选、保留全部事件／差异／标记／段池、做前缀及恢复；只调用现ZC、ZR各四周期，52项obs复用旧完成记录并核来源一致。所有8单元与原同名结果逐字段一致，新增软件真值不反填旧52项。

输入只用原两个冻结source目录，经`read_inputs`原manifest校验；日线1643、m60 17260、m90 12945、m120 8630，总40478。原研究代码SHA与旧报告、当前产品版本核对，旧原规则逐根等于产品证据只有对应代码仍相同时复用。新保护按原`reference_rescue.evidence_checks`十项日期及12/15链的独立字面要求检查新事件，分别保留模型时刻、软件只确认日期或顺序的限制，不能直接调用依赖旧研究类快照的该函数冒充新类验收。

模拟仍用原四个固定输入：7/10后m120收3959.16重新钝化、3960模型反例无钝化；7/13后m120收3892.79消失、m90收3944.79仍钝化。复用`recover_projection`／投影bar及当前研究类快照，TOP条件不对BOTTOM增新要求；同源新计算器restore后做一步、核父快照未变，结果与既有模拟bar逐字段对照。前缀、源身份、段池与所有BOTTOM事件相对BASE比较；若存在差异单列，不通过隐藏事件或改预期使之通过。

后续新图分别按状态或当日事件使用：上证1/6保留钝化、三指数1/6价资格对照、6/24 m90末端钝化，不声称软件精确首次时刻；深成指4/16只按讲稿确认当天消失，原完成结果通过SHA复用，不重算跨指数。9/24—25只核移除TOP事件与两张当日图可见性相容，不伪造软件NONE。新报告逐项标注直接、按图映射、仅模型、待确认等原等级，相关重复不算独立样本。

审计JSON集中实际范围和代码／源／旧结果SHA，复用`cross_index_daily.seal/read_unit`，逐单元拒绝覆盖、原子落盘及读回；中断恢复先核同身份，只做未完成单元，半文件／变更拒绝。每文件20MB、源40500上限、各阶段60秒共240秒（含继续和最后验收），不访问真实DB／Lake、不新设配置。12项现选择器测试及真实冻结输入回核分别报告，不把模拟或测试通过写成软件公式已证。原件／旧52项／旧结果／产品代码保持，最后文档和相对链接／差异检查及引擎表最后；本步不编码或放宽预测／API／消费者，更早TODO保留。

**跨版本编号比较修正（继续前）：** 原模拟报告Spec明确a1／f0bf6da2…，现Spec为r1／533a9b44…；`XxmCalculator._id`将版本／hash纳入输入。首轮仅因两条非空模拟事件的编号和重新钝化关联编号不同而失败，bar及非编号字段相同。旧执行状态保存为第一次尝试，不改旧golden或吞失败。继续独立按hashlib计算旧版／新版事件ID、结构ID及rearm ID，校验各自版本和关联；现版BASE／ZC／ZR模拟完整事件必须相同，父快照不变且restore成功。跨版仅机械编号按各自版本校验，其余字段全部相等；旧返回state、route及投影bar不变。不修改产品或旧模拟文件，8个已完成单元不重算，先校验完成文件再继续剩余检查。

**本步结果：** 新报告（原记录：`reports/xxm_top_current_dif_recheck_20261018_01/README.md`）8个单元全部与旧同候选输出相同，两个候选各52/52、底部1179事件完整相同、10日期和12/15链保留，4输入（3软件／1模型反例）在现BASE及两个候选均通过，12前缀／恢复及父快照不变通过。首轮跨版编号误比较已独立核版本和关联后纠正，原失败留档；无业务字段或旧预期变动，8单元续读未重算。深成指4/16讲稿仍仅当根条件吻合，可优先编制最小产品修订LLD。

只读`forecast_entry`、`forecast_detector`、`forecast`及`forecast_paths`得到下一步必须审计的代码点：首次价格分界、`stable_reference_on_band`和`reason_for`的新资格、日线舍入边界、克隆原产品类的真实行为、已DULL路径无需重复首次限制。当前分界里的0是价格端点，不证明已覆盖DIF过零；仅改识别或将研究子类直接传现预测器不足验收。下一步还须核算法版本／缓存、API与前端消费者是否受影响；本轮未修改或运行预测，不宣布开发完成。原52项、278文件、更早TODO保持。


## 26 首次顶部钝化的当根DIF资格：代码级LLD（2026-10-18，拟修订，未实施）

### 26.1 本轮目标、依据和范围

管理员本轮只要求细化这一步，不授权修改产品或测试代码，不展开预测设计。拟定规则是：**只有准备产生TOP、DULL、activation的新事件时，才额外要求该根已完成K线的`bar.dif > 0`。** 其他资格仍须全部满足。首次指一次新的激活，不是某指数历史上只能发生一次；取消后在后续K线上再次走到首次激活分支，也检查当根DIF。

四周期`day/m60/m90/m120`复用同一实现。对象身份仍由现构造函数限制为000001.SH，不因深成指研究而扩大正式产品范围。不新增参数、配置开关、状态、事件类型或接口字段，不另写计算器，不导入研究类到产品。

依据为原方案§12.41及已有样本回核（原记录：`reports/xxm_top_current_dif_recheck_20261018_01/README.md`）：52项条件性标记、1179条底部事件、10项日期保护和4个既有模拟输入保持；4/16深成指当日讲稿支持当根条件。严格大于0是当前拟采用的研究口径，不宣称软件的零值规则已被证明。首次黄字日期及软件实际参照仍按原报告保留未知。

### 26.2 当前代码审计与拟改位置

| 当前文件／函数 | 已核实的行为 | 本节安排 |
| --- | --- | --- |
| [calculator.py](../../../../src/biz/services/wealth/market/index_detail_xxm/calculator.py) `XxmCalculator.step`，当前34—97行 | 先验证输入、处理柱色和段极值，再处理重新钝化、取消、结构转换，最后才首次选参照 | 只在当前92行开始的最后一个`elif`增加TOP当根DIF条件 |
| 同文件 `_select_eligible_reference`，当前160—170行 | 先查最近历史段价格，再按DIF选合格参照；没有当根bar参数 | 保持函数签名、排序、价格／DIF严格比较不变 |
| 同文件 `_rescue_bottom_dull_reference`，当前172—180行 | 底部旧参照将失效前也调用同一选择器 | 保持不变；不得把当根正DIF条件加在共享选择器里 |
| 同文件 `step` 的98—158行及 `_advance_bottom_history` | 生成事件，推进旧顶部／底部历史，更新previous和processed | 即使拒绝首次TOP也必须继续执行，禁止提前return |
| 同文件 `_advance_rearm/_qualifies_bottom_close` | 独立管理底部结构消失后的等待和重新钝化 | 保持不变，不增加DIF正负条件 |
| top_daily_ambiguity.py（原记录：`scripts/research/index_market/xxm/top_daily_ambiguity.py`） `ReferenceGateCalculator` | 研究类暂存incoming，在选参照后检查当根DIF | 仅作研究依据；不迁入产品、不新增incoming字段 |
| [test_xxm_calculator.py](../../../../scripts/research/index_market/tests/test_xxm_calculator.py) | 已有真实`step`、历史跟踪、恢复和三组转向比例测试 | 在此文件补本节字面用例；旧全量顶部不变断言按§26.7处理 |

CodeGraph本轮使用`codegraph_explore`和`codegraph_callers(_select_eligible_reference)`；已核实该函数由首次激活及底部参照切换共同调用。构造函数的调用方查询未完整返回，已阅读真实查询入口补核：[query_service.py](../../../../src/biz/queries/wealth/market/index_detail_xxm/query_service.py)负责重放及`SeriesEntry.calculator_at`恢复同一产品类；DTO和前端消费它的事件／状态，不自行计算新资格。没有目录迁移或依赖方向变化。

### 26.3 拟实现的唯一改动

下面是未来修改的示意，本轮不写入代码：

```python
# 原有ref分支、重新钝化及其他处理保持原顺序。
elif (
    sign
    and wave.count >= self.spec.min_bars
    and self.history[sign]
    and (sign != 1 or bar.dif > 0)
):
    candidate = self._select_eligible_reference(wave, self.history[sign])
    if candidate is not None:
        self.reference = deepcopy(candidate)
        event_type, route, direction, event_ref = (
            "DULL", "activation", sign, self.reference
        )
        self.state = "DULL"
```

为什么放这里：走到本分支时，已有参照的取消／结构转换、底部重新钝化均已先处理；只加这里的条件，不会把已有信号重新当作首次识别。共享选择器是只读选择，因TOP当根条件直接跳过它，与研究候选先选到候选再拒绝的结果一致；必须用固定旧研究结果核这项等价，不能只凭函数名断言。

取的是输入`bar.dif`，不取本段最高`wave.dif`，不取历史参照DIF、DEA或MACD柱。红柱只说明`bar.hist > 0`，不能替代正DIF条件。日线使用源已给出的DIF；分钟使用现有DIF，不在此再取整、不加epsilon或容差、不重算MACD。`0.0`及`-0.0`均不满足严格大于0。是否符号转换仍由原hist判断，不改分段。

条件未满足时，不产生本次`DULL/activation`，不赋值reference或新增普通状态；但本根段计数、价格／DIF极值、旧历史记录、previous、processed仍正常推进。仍可能输出另一条合法的旧结构历史消失，不能把本根全部事件清空。

### 26.4 逐项约束与状态结果

| 情况／约束 | 应有结果 | 代码点和测试要求 |
| --- | --- | --- |
| 首次TOP、其他资格满足、当根DIF负或零 | 普通状态仍NONE，不生成DULL／不保存活动参照 | 首次`elif`；正段峰值不能替代当根，用例见§26.5第一组 |
| 首次TOP、当根DIF正 | 继续执行原价格、最少根数和历史DIF资格；不是见正即报 | 同分支＋原选择器；保留价格不够、段数不够、DIF相等反例 |
| 前一根被拒绝，后一根同段DIF转正且资格满足 | 后一根即可激活；不强制等待新红柱段或额外冷却 | 不新增记忆字段；§26.5第二组 |
| 已有TOP DULL | 原DIF转向、突破取消和变色处理继续，不重复首次正值检查 | 原71—89行；§26.5第三／四组及已有取消／变色测试 |
| TOP STRUCTURE返回DULL，route=dif_return | 即使当根DIF为负，也按原转换规则决定 | 不是activation；§26.5第三组 |
| 首次BOTTOM／底部参照切换／底部重新钝化 | 不增加正DIF或镜像负DIF限制 | 原底部函数不改；正DIF的BOTTOM字面样例及现有BOTTOM用例 |
| 单根历史、两段数量、近段价格检查、最强合格参照排序 | 原样保留，不删单根、不补第三段、不换成只选最近段 | 原选择器及现有`test_raw_two_pool_strongest_eligible_tie_and_nearest_price_gate` |
| 首次TOP被拒绝时的旧历史跟踪 | 原因和日期继续判断；不得提前返回或隐藏历史消失 | §26.5第六组；检查关联及previous／processed |
| 无效或未完成输入 | 仍先按原validate拒绝，不能因DIF条件而静默跳过 | 原35行及既有非法输入测试 |

不把新增限制放在`step`开头、所有TOP事件的输出层、DTO或前端；不修改`_qualifies_bottom_close`，不对DULL／STRUCTURE全局执行DIF>0。

### 26.5 可人工核算的测试输入与独立预期

这些都是人工单元样例，不是原软件标签。复用现测试文件的`bars(values)`：每项为`(close, dif, hist)`，DEA由`dif-hist/2`得到，符合真实`XxmBar`字段合同；时间按现helper生成。分钟沿用既有周期测试补`T15:00:00+08:00`的方法，只验证内核，不冒充连续分钟行情。正式日期／交易日完整性继续由源层负责。

下列用例在未来实现前先用未改动的旧产品和现研究候选核算；预期先写成字面，不调用待改产品生成expected。四周期参数化，转向比例仍覆盖现支持的0.75／1.0／1.2，不以新资格改1%的默认值。

1. **首次TOP以当根为准。** 输入`[(100,10,2),(99,0,-2),(101,2,2),(102,x,2)]`；`x=-0.001、0、-0.0`均无普通事件，NONE且reference为空；`x=0.001`产生TOP DULL／activation，参照为首根的价格100、DIF10。当前红柱段最高DIF仍为2，故该样例能抓住误用wave.dif的错误。分钟另以±1e-12核不加容差，日线不人为制造源没有的额外精度。拟增`test_first_top_activation_requires_current_dif_positive`。
2. **同段后续转正可激活。** 上例取`x=-0.001`，再加`(103,0.001,2)`；第五根才产生TOP DULL，本段从第三根延续，历史参照仍为首根，第四根也必须计入processed／段计数。拟增`test_first_top_can_activate_on_later_positive_bar`。
3. **已有信号不重查首次资格。** 输入`[(100,10,2),(99,0,-2),(101,2,2),(102,1,2),(102.5,-2,2),(102.5,-1.9,2)]`；第四根TOP DULL，第五根TOP STRUCTURE／dif_turn，第六根TOP DULL／dif_return；后两根DIF均负，参照仍为第一根，不能因新增限制拒绝。拟增`test_existing_top_transitions_do_not_recheck_activation_dif`。
4. **原零基值转换规则保留。** 上例第四根之后改接`(102.5,0,2)、(102.5,-0.001,2)`；第五根形成STRUCTURE，第六根因原转向基值为0不发生新普通转换，仍STRUCTURE。现`test_turn_exact_threshold_zero_basis_mirror_and_independent_extremes`里的旧零值样例会不再首次激活，单靠其“最后无事件”不能继续证明零基值转换；须补本例，不把测试静默改成失去原覆盖。
5. **BOTTOM也可在正DIF时激活。** 输入`[(100,2,-2),(105,6,2),(99,4,-2),(98,3,-2)]`；第四根BOTTOM DULL／activation，参照首根DIF2，当前负柱段最低DIF3仍高于它；不施加镜像DIF<0限制。负DIF的BOTTOM继续复用现`BOTTOM`及`same_segment_setup`用例。拟增`test_bottom_activation_has_no_new_zero_axis_gate`。
6. **拒绝TOP不停止旧历史。** 输入`[(100,10,2),(99,0,-2),(101,2,2),(102,1,2),(102.5,-2,2),(101,-3,-2),(102,-2,2),(103,-1,2)]`；第五根旧TOP结构锁住价格102.5，最后一根不报新的TOP DULL，但旧结构因103超过102.5输出TOP历史消失。普通状态NONE、活动参照为空、processed为8，previous为第八根、当前段count为2。历史关联必须指向第五根结构，结束原因historical_price_break。拟增`test_rejected_top_still_advances_original_history`。

保留现有价格／DIF严格等号、最近段价格不可绕过、单根占位、变色、真取消、底部等待／重入和恢复反例。新测试必须直接调用真实产品`step`；现研究类的选择器测试只证明候选定义，不能代替产品分支测试。任何手算例不符先解释并修正文档依据，不能改expected迎合实现。

### 26.6 既有真实材料的回归要求

复用§25.22冻结来源：52项原观察（20直接／32映射）、10日期、12/15四词链、4模拟输入、上证1/6阳性、9/24—25当日图及4/16深成指讲稿。保持来源、日期和等级，不累计成独立盲测。

- 9/24—25拟去除的两个TOP事件不再输出；不能将“图上未见字”升级为软件内部NONE。
- 4/16深成指讲稿支持当日消失。正式产品仍只支持上证；不得为跑此例放开正式指数身份，跨指数核验继续走既有研究入口并保持来源绑定。首次4/14和具体参照124.162仍是模型结果，不写成软件独立真值。
- 全部底部业务结果保持，既有1179条是本轮同版本研究的逐字段证据；未来若算法版本更新，编号按各自真实版本单独核验，日期／类型／路径／参照及关联的业务含义仍须全部相同。不能为通过跨版比较而无条件删编号字段。
- 主参数拟改后应等于本轮冻结当根候选，而不是等于旧原规则。新增或消失的顶部及历史跟踪结果须逐条列出；400个状态／事件差异时点不当作400个软件错误。

本轮只引用已有研究成绩，没有重跑此项正式验收或增加软件真值。

### 26.7 必须同步处理的现测试断言

现有两项测试明确要求全部TOP与旧规则相同，与这次修订目标冲突，未来编码时不能原封不动地宣称它们仍是验收依据：

| 现测试 | 输入和旧要求 | 未来应怎样处理 |
| --- | --- | --- |
| `test_entire_frozen_ordinary_and_historical_baseline` | `load_frozen_inputs(ROOT)`，三组比例；检查旧TOP状态、事件、历史锚点及数量 | 保留旧源／旧账本，改为核明确锁定的拟修订TOP结果；不可仅删计数／历史断言 |
| `test_full_four_period_top_oracle_and_first_activation_are_preserved` | `xxm_source_audit_20261013_213852`，四周期三组比例；原规则所有首次激活都必须保留 | 改为“符合新增当根资格的激活保留，被拒绝及后续变化均与独立冻结结果相符”；覆盖原其他资格不变 |
| `test_turn_exact_threshold_zero_basis_mirror_and_independent_extremes` | 组合了转向阈值、零基值及镜像用例 | 原正向阈值／底部断言保留，补§26.5第四组真正进入已激活状态后的零基值检查 |

不能直接把当前40478根报告当作上述两个不同输入集合的通用expected。未来在改产品代码之前，先针对各测试真实生产者／manifest／输入SHA和0.75／1.0／1.2分别锁定现研究候选的业务输出；当前1.0主源结果可复用，其他输入或比例须各自准备并核身份。测试来源文件保持原字节，按对应源逐项解释差异。

特别限制：产品修改后，研究`ReferenceGateCalculator`会继承新的父类`step`，其BASE不再代表旧产品；不能届时重新调用该子类生成expected再与产品比较。独立期望必须在旧父类仍未修改时形成并锁SHA，已有软件字面预期另行保留。夹具准备及完整回归属于未来执行，本轮不生成新全量期望、不改旧测试、不skip或吞异常。

### 26.8 调用方、版本及后续工作登记

字段和枚举形状不需要为这个条件新增内容；被拒绝的普通激活自然不出现在事件集合中，前端不得自行过滤负DIF文字。但事件内容、旧结构后续、恢复点及预测输入可能改变，不能仅按“响应字段未改”认定没有影响。

现代码依据：识别查询以`MAIN_SPEC.spec_hash`组成key并创建／恢复产品类；DTO校验MAIN_SPEC版本；[adapter.ts](../../../../wealth/src/features/index-detail/xxm/adapter.ts)还明确校验当前r1版本字面值。算法变更不能复用旧语义的快照或缓存，也不能擅自继续沿用旧版本给正式页面。本节只登记这些后续影响，不选新版本字符串、不增加Spec字段／开关、不设计缓存迁移或双版本兼容。

预测解算及其分界、API／前端版本消费者的完整联动，按管理员限定留给下一步；本轮不展开实现或验收。现有源码读核只足以标出影响点，不等于完成了这些消费者的全量迁移审计。因此本节“规则代码落点明确”不等于整体开发／上线已经就绪，不能据此先把识别单独接入正在使用的页面。

### 26.9 读写、失败、继续与性能要求

本轮只改原方案、本文及研究进展记录；不写数据库／Lake、配置、API、源码、测试或旧报告。无新增参数的来源／持久化／生效方式需要配置化：资格直接使用现`XxmBar.dif`，单根多一次比较，不新增数组、历史长度或常驻状态。

本轮文档手算检查只可调用未修改的现产品／研究类，最多500个合成bar、60秒；不得借机重跑整段行情或改变候选。失败先保留输入及实际差别，纠正文档依据后再继续，不改产品使文档通过。文档中断后从原文件和受保护SHA核续，未完成的勾选保持未完成；最后文档／链接／文件不变检查预算60秒，本轮总程序执行预算120秒，阅读和人工评审不当作计算耗时。

未来开发仍遵守原请求4秒等现预算，不放宽`runtime.py`，不增加数据读取。完整冻结输入回归沿§12.41／25.22逐单元落盘、同身份继续及最后验收预算；§26.7的不同输入集先核各自manifest和真实数量，不把它们拼成一个40500根口径或扩大正式读取。跨版恢复应由现`restore`身份校验拒绝旧状态，重新从同源真实前缀构建；不得静默改hash后接旧快照。

### 26.10 本节完成条件及当前状态

| 本节交付项 | 当前状态 |
| --- | --- |
| 首次资格、四周期、当根字段与严格比较明确 | 文档已写明，拟采用口径；软件零值规则仍未完全确认 |
| 唯一代码落点、保持不改的分支、禁止提前return明确 | 已审计现代码并写明 |
| 正向、反向、已有状态及历史跟踪样例 | 已列独立字面输入；本轮仅允许小样例核算，产品新测试尚未实现 |
| 现有TOP全量不变测试及独立期望问题 | 已列必须调整的断言及改代码前准备要求，尚未执行 |
| 底部及已激活状态不追加新限制 | 已映射到原分支、字面反例和既有保护点 |
| 预测／版本／消费者联动 | 只登记后续影响，本轮未设计或实施 |
| 产品开发、正式验收、提交部署 | 本轮均未执行或授权 |

本节的确认范围仅为第一步代码级LLD，后续仍按管理员选定的步骤推进；不得将待完成项自动勾为通过。

**本轮小样例核查（文档检查）：** 使用未修改的现产品与既有当根DIF研究类，核对上述6类字面输入及分钟微小正负值，覆盖四周期，共42个合成样例输入、84次执行、408个bar。主转向比例1.0下，研究候选42/42符合预先写明的预期；现产品有23个样例与拟修订预期不同，说明反例能抓住现行为。这里不是软件实测、没有新增产品测试文件，也没有核验0.75／1.2的未来全量期望。174个受保护源码／测试／旧证据文件SHA保持，现有研究成绩未覆盖或改写。

## 27 首次顶部钝化当根DIF条件的预测代码级LLD（2026-10-18，拟修订，未实施）

### 27.1 目标、依据及本轮权限

本轮只落实管理员所选“细化预测部分方案和代码级LLD”，承接§26的首次TOP `bar.dif>0`规则及[预测方案§32](./index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md)。不修改识别／预测／API／前端代码、测试或配置，不进行行情扫描、正式API验收、提交部署。§26是上一轮识别设计；其“本轮不展开预测”由本节接续，不改写上一轮记录。

设计覆盖000001.SH的日线、60／90／120分钟；不扩大正式指数身份，不给底部或已有信号追加首次正DIF条件，不修改单根历史占位、两段池、原1%转向及R1规则。原20点业务日期、完成端点、20根搜索、中间平收、源精度、近期筛选与预算继续适用。

### 27.2 当前实现审计与影响面

| 当前代码点 | 已核实的现状 | 拟议处理 |
| --- | --- | --- |
| `forecast_entry.entry_partition`，当前8—36行 | 分界有价格、段DIF、参照DIF、MACD柱及等待参照；集合中的`0.`是价格域下界 | 仅NONE首次TOP增加当根DIF资格分界及原数值误差包络；不能往BOTTOM的共用分区加新条件 |
| 同文件 `stable_reference_on_band`，42—67行 | 证明柱色、段极值、参照排序；未证明当根DIF正 | 增加首次TOP整段范围内当根DIF为正的证明，等待分支保持 |
| 同文件 `reason_for/solve_entry_ranges`，70—132行 | 已有原因将其他失败归到DIF不背离；按开放区间／边界单点分区并核副本 | 单列新增资格的排除原因；保持完整覆盖、唯一归属及精度未决，禁止只试代表价判断整域 |
| `forecast_detector.clone/possible_bars/activation_signature`，8—44行 | clone显式构造产品类；日线独立枚举DIF／柱值舍入；真实step给事件和实际参照 | 继续唯一产品类，不改成动态子类构造；内核更新与分区同步后验收；不重新拼MACD柱 |
| `forecast.forecast`，15—116行 | NONE先求activation，再以每段真实ref求最近P—C关系；DULL不走激活求解 | 复用收窄后的入口，按新真实状态重算；不在返回结果末尾过滤 |
| `forecast_paths.partition_prefix_paths/_prefix_signature/build_path_relation` | NONE第一根资格由入口域承担，后续检查存活、R1路径；关系以entryRangeId关联入口 | 保持该分工，后续根及目标根不再追加DIF>0 |
| `forecast_joint.domains_for_target/target_lines/close_bounds/common_interval` | 求原参照下的存活、结构和共同条件；零前值转向独立处理 | 不加首次正DIF限制，不改变目标C与旧参照的原不等式 |
| `forecast_text.select_display/make_display` | DIF_NOT_DIVERGENT会写“指标也创新高”且可省略远端边界 | 新原因使用独立未触发文字；不参与该省略判断，不改变其他筛选 |
| `forecast_query_service.IndexDetailXxmForecastQueryService.build` | 从真实entry恢复calculator并校准；结果带检测器／预测Spec，最后DTO和display | 保持读源／校准／状态组装；身份缓存的完整迁移另审，不复用旧语义结果 |

以上文件均位于`src/biz/services/wealth/market/index_detail_xxm/`，query位于`src/biz/queries/wealth/market/index_detail_xxm/`。本轮CodeGraph使用`codegraph_explore`及`codegraph_impact(solve_entry_ranges, depth=2)`：返回产品forecast、主题测试及旧研究入口；同名旧报告函数混入，文件名查询亦含无关结果，已按实际导入直接补核上述当前源码、Python DTO及TS adapter。图中未列到测试或消费者不视为无依赖；本轮只核预测直接链，不声称已完成下一步全部消费者迁移审计。无目录迁移或子系统依赖变化。

### 27.3 首次激活的数学边界及来源精度

沿用`ProjectionState.advance`实际递推，记下一根原始DIF为`D(P)=b+K*P`，`b=E12*11/13-E26*25/27`，`K=28/351`。额外资格只在`c.state=='NONE'`、`c.wave.sign==1`、无底部等待时参与首次activation的域证明。

1. **分钟：** 新条件为`D(P)>0`。新增根`-b/K`，调用现`add_root(root,K)`登记分界及浮点误差包络；仍只在正有限P域内求解。解析根不能替代实际递推的浮点结果，精确根和两侧一ULP须核；不能在识别比较中加epsilon。
2. **日线：** 资格检查的是`possible_bars`提供的三位DIF。沿用`source_options(D(P), True)`；全体可能值>0才可确定激活，全体≤0则这项确定不合格。改变资格的原始DIF层级是`+0.0005`，新增`(+0.0005+g-b)/K`，`g∈{-GUARD,0,GUARD}`，每个根也有原误差包络。不能只补原始DIF=0根，也不必为该资格增加-0.0005根。
3. **多种日线取整结果：** 一种真实step能激活、另一种不能或参照不同，沿`activation_signature`返回`PRECISION_UNRESOLVED`；所有取整结果都因其他已知条件不能激活时，不把“靠近中点”自动说成有激活可能。DIF与hist各自取整，DEA继续不参与新资格。
4. `GUARD`继续来自现`FORECAST_SPEC.daily_rounding_guard=1e-10`。分钟不增加该guard；识别读取的真实bar不受预测来源包络影响。0和-0均不满足正值；极小正值若是分钟真实输入则仍按>0处理。

`entry_partition`未来插入示意，需和唯一内核一起实现，本轮只写设计：

```python
# b/K、既有add_root及其他原分界均保留。
if c.state == 'NONE' and w.sign == 1 and c.pending_rearm is None:
    levels = (0.0005,) if day else (0.0,)
    shifts = (-GUARD, 0.0, GUARD) if day else (0.0,)
    for level in levels:
        for shift in shifts:
            add_root((level + shift - b) / K, K)
```

BOTTOM下一根完整结果域也复用`entry_partition`，因此必须保留上述方向／状态限制；不能把增加分界当作无害改动后让底部未决范围变大。

### 27.4 稳定性证明与完整分区

`stable_reference_on_band`先保存两个端点原始DIF的向外误差界；对首次TOP，还要证明这个范围内**当根DIF的最小可能输入值>0**。分钟即原始下界>0；日线在原始下界应用现三位来源可能值，最小值>0。随后继续原柱色、段DIF最高值及最强参照资格证明。不能拿`max(w.dif, ...)`证明当根正值；本段曾经正、当根已负的例子必须被拒绝。

现日线背离证明用`floor(dlow*1000)/1000`作保守下界。新增正值证明须使用保存的原始界与真实`source_options`，不能直接照用这个floor：原始DIF为0.0006时，源已确定为0.001，floor却会给0，可能误把可证明的边界当作未决。原背离／柱色证明不用这次机会改写。

开放区间、精确边界单点、相邻浮点值和无上界尾部仍构成完整正价域；每个P恰落一条激活或排除记录。解析分界负责证明域，真实step副本负责核对；三点、网格或随机样本不能替代全域证明。新条件导致某参照域为空时去掉该域；不能跨参照、精度空隙或未触发空隙合并。拒绝首次激活也不得停止副本正常推进或吞掉合法历史事件。

### 27.5 排除原因的拟议合同与优先顺序

建议新增现`activation.exclusions[].reason`枚举值`CURRENT_DIF_NOT_POSITIVE`，仅表示本次首次TOP的可能输入DIF均不为正。该值是描述具体条件的拟议标识，不是新字段、status、事件或HTTP错误。当前Python的`EntryExclusionDto.reason`及TS adapter的`entryReasons`均不接受；完整消费者、版本和错误输入迁移仍须下一步审计确认，本轮不能先落码。与§26“不新增事件／字段”不冲突，但仍属于合同枚举变更，需先确认。

`solve_entry_ranges`优先以真实事件集合判断激活／未决：

| 分类 | 未来结果 |
| --- | --- |
| 所有可能输入都产生同参照的activation | 激活范围；不能同时登记新排除原因 |
| 有激活／无激活混合，或实际参照不一致 | PRECISION_UNRESOLVED；不能写成确定未触发 |
| 没有任何activation，柱色／零柱或根数已不合格 | 沿原WRONG_COLOR_OR_ZERO、INSUFFICIENT_BARS顺序 |
| 没有任何activation，首次TOP且所有可能DIF≤0 | CURRENT_DIF_NOT_POSITIVE；不冒称DIF也创新高 |
| 没有任何activation，可能DIF中有正值，但其他资格确定失败 | 继续原价格／背离原因；不能仅因正负取整混合强造激活未决 |
| 原数学分界误差包络仍不能可靠分类 | 沿原PRECISION_UNRESOLVED保护，不猜等号归属 |

`reason_for`只解释已经确定没有激活的区域；它不自行决定激活。保留底部等待分支在普通历史检查之前；BOTTOM不返回新原因。原`DIF_NOT_DIVERGENT`保留原义；不允许为了逃避枚举审计把新条件塞进它，或让前端按DIF猜原因。

### 27.6 P—C关系、最近端点与副本

1. `forecast.forecast`继续以`state=='NONE'`进入`solve_entry_ranges`，seeds直接取新有效范围及真实ref。全无有效范围且存在未决，仍返回`PRECISION_PENDING/ROUNDING_BOUNDARY`；确定无解则`NO_CANDIDATE/NO_ENTRY_RANGE`。不能拿旧seeds找日期后删例子，也不把未激活称为CANCEL。
2. 第一根通过资格后，中间各根及目标根仅检查原存活／取消／结构规则。`partition_prefix_paths`跳过NONE第一根重复判断、`build_path_relation`用entryRangeId关联激活范围的现分工保留。无需在`targetConditions`、`target_lines`或`close_bounds`添加DIF>0；否则会误删已钝化后DIF转负形成结构的合法C。
3. 最近性仍须从近到远检查完整允许P域；NONE最早第二根确认，DULL可检查下一根。更早端点存在未决时不跳到后来确定解。20根内无结构解仍保留确定的activation，不强造日期；新数据到达后从新真实状态重算。
4. `clone`继续构造唯一`XxmCalculator`并restore；不改为`type(c)`、传研究variant或另写TOP专用计算器。现研究候选的新增属性并不随现snapshot传入，给旧预测器喂研究类不能验收新规则；未来以已改唯一产品类核每个假设输入。父snapshot在所有分支、失败及重复调用后保持原样。
5. BOTTOM所有路径、等待固定初始ref、R1中间切换、relationId／entryRangeId关联及`nextBarOutcomes`保持原义。已有TOP DULL／STRUCTURE绕开首次域，不能因为当前DIF≤0直接返回NO_CANDIDATE。历史重放的普通状态必须来自新内核真实前缀，不从旧版point拼接。

### 27.7 页面解释与显示落点

`select_display`对新原因沿现近期范围筛选；它不是现价格／柱色两项强制保留原因，也不是可省略的远端背离原因。`make_display`为其新增明确分支，草案为“未触发：{时点}{范围}，DIF未转为正值，顶钝化条件不成立。”仍由后端生成四项display，前端只消费。

数学范围必须先满足新资格，`number_inside/display_range`再向有效范围内部取展示数值。不能把严格零边界四舍五入到外侧，不能用二位／四位文字填满未决空隙。实际展示端点须经真实副本核过，内部正价根、参照边界和未决域在合同中完整保留；近期省略不扩大真实激活域。已有顶部触发范围的下界不能因本次新原因被省略为“任意更低价格均可”。

全无激活范围时沿现NO_ENTRY_RANGE通用文字；不增加新的页面状态。STRUCTURE确认时间、已有DULL的维持／结构条件、底部R1“钝化延续／失效”和等待重入文字不变。页面布局、四行顺序和近期60样本／95分位不改；Figma文字同步继续作为未来开发交付项，不在本轮写设计平台。

### 27.8 独立数学样例与未来测试落点

以下均是隔离单元样例，不是软件图证或完整来源校准。真实`XxmBar`包含time、close、dif、dea、hist，按`dea=dif-hist/2`构造；四周期使用各自合法格式的递增完成时点。人工前缀`[(100,10,2),(99,0,-2),(105,2,8)]`形成NONE、当前红段count=1、历史TOP价100／DIF10、当前段最高价105／DIF2。投影起点取`E12=102,E26=100,DEA=-2`，与末根DIF2／DEA-2一致；不声称这个人工前缀已经通过250根校准。

以独立Fraction计算：`D(P)=(28P-2206)/351`，`H(P)=1.6*(D(P)+2)`。原红柱资格为`P>376/7`，原参照DIF资格为`P<1429/7`，本段价格已足够；新增分钟资格为`P>1103/14`，所以理想精确数值下新激活区间为`(1103/14,1429/7)`。浮点根附近另沿原未决保护，不把分数根强行当浮点等号。日线正值边界为`1103/14+351/56000`附近并带原guard；最终上界仍须原三位背离条件，不能沿用分钟上界。

| 独立预期／真实错误反例 | 未来测试位置与通过条件 |
| --- | --- |
| P=60，D=-526/351、H>0；旧产品会首次TOP，拟修订不应；P=100，D=22/13>0仍可激活；P=210虽D>0但突破历史DIF仍不可激活 | `test_xxm_key_point_forecast.py`新增当根资格测试，四周期；核实际事件及完整区间归属，不能只看DIF符号 |
| 分钟DIF恰0／±极小值，解析根及一ULP邻点，根与价格／历史DIF切口重合或在正价域外 | 同文件新增边界／分区测试，独立分数根＋字面预期；P=0仍不属于价格域，不凭一个float根断言所有附近点 |
| 日线原始DIF=-0.0005±2G、-0.0005、0、0.0004均因该项不合格；+0.0005±2G分别非正／正，+0.0005±G/2及中点可能为0／0.001，其他资格满足时才未决 | 同文件新增来源精度测试，先写独立字面预期，再核`source_options`／真实产品；不把helper自身输出当expected |
| 正DIF日线0.0006应为0.001，不能被floor到0误拒；本段DIF峰值2但当根负也不能通过稳定性证明 | 同文件新增`stable_reference_on_band`反例；原底部稳定性结果不变 |
| 已有TOP DULL前缀`[(100,10,2),(99,0,-2),(105,2,8),(106,1,6),(106.5,-2.1,3.8),(106.5,-2,4)]`；末根DIF=-2／DEA=-4，投影取E12=98／E26=100／DEA=-4；C=40时D=-758/117<-2、H<0，仍形成TOP color_flip结构 | 同文件／`test_xxm_forecast_reference_paths.py`，独立字面确认已有信号不被首次门槛误伤；并保留§26.5同色dif_turn／dif_return样例 |
| 新入口域只覆盖旧域一部分：所有relations、commonConditions、examples均在新入口内；最早端点只有无效旧P时不得继续报原日期 | 同文件扩最近时点测试，以预先独立算出的P—C不等式判预期；实际step仅作佐证，不用求解器自己产expected |
| 原BOTTOM正DIF激活、等待重入、R1非单调取消／继续域与display无变化 | `test_xxm_forecast_reference_paths.py`保留独立Fraction反例；现底部输入及三门槛回归按原manifest逐项核 |
| 新原因不写“指标也创新高／钝化消失”，不触发远端边界省略，不能跨未决域显示；全无入口不产生结构价 | `test_xxm_forecast_display.py`增加纯文字／边界用例；`test_wealth_index_detail_xxm_forecast_api.py`及TS合同／展示测试在下一步合同审计后同步 |
| 所有假设输入调用唯一产品副本，重复／失败不改父状态 | 预测单元测试保留snapshot比较；故意传研究类的隔离演示只证明旧clone限制，不作候选预测通过证据 |

未来测试比例仍覆盖0.75／1.0／1.2；本轮有界核算只检查主比例1.0的上述小样例和取整事实，不生成全量expected或新测试文件。已有真实52项、四个7月模拟、12/15链及新讲稿继续保持独立证据等级。

### 27.9 独立预期与真实验收安排

在修改父类前，按§26.7核每个现测试的真实输入生产者、manifest和SHA；不能用同一40478根报告替代912日线源或更早另一测试集。分别固定三组比例的拟修订识别结果，再独立求预测临界P／C及确认／无解预期；预测旧完整响应不因事件变化就直接删断言。现研究子类套旧forecast不能生成新版预测golden；预测预期须来自手算分数／不等式、独立舍入预期及已确认软件记录，完成产品迁移后再由真实step核对。

未来在同源、同身份下分别核：①新数学域、确定排除／未决及最近端点；②原BOTTOM完整结果；③真实DULL／STRUCTURE保持原规则；④Python DTO与TS消费／四项display；⑤真实路由及冷暖、LATEST／REPLAY、混合与双标签预算。只比较相同实际状态时才要求旧预测完全保持；新版历史状态已变的时点，逐项说明状态／ref导致的范围差异，不复制旧响应冒充新结果。

本轮不运行上述完整验收。先前分钟成绩和2020起日线隔离成绩仅适用于旧R1；不转成新规则已验收。更早正式日线及四周期整页TODO保留，数据补齐之前不能把隔离成绩写成正式全历史接口通过。

### 27.10 配置、读写、中断与性能

本次资格无新增配置，沿用现唯一Spec来源：20根、250校准尾、日线0.0005／分钟1e-8校准容差、GUARD=1e-10、展示2／4位、近期60／95分位均不改，不新增env／数据库设置／页面开关。算法／预测版本及Spec hash必须随未来语义改变，具体值、缓存／checkpoint／消费者迁移留下一步，不能沿用r1身份偷偷改变结果。

本轮只修改四份原文档：算法方案、本文、预测方案及研究记录。最多500个合成bar、少量Fraction／来源取整核算，不读行情或数据库／Lake；计算60秒，最后文档／链接／受保护文件检查60秒，总程序预算120秒。核算失败保存实际输入、结果与原因，不改产品消除失败；中断保留文档及临时审计输出，继续先核本轮保护SHA，未运行项不勾通过。

未来生产请求仍≤4秒、预测≤200ms、响应≤32KiB、共用缓存≤64MiB／16项、并发≤2。首次TOP的entry分界分钟最多新增一个根、日线最多三个根及各自原误差包络；后续P—C计算只消费收窄后的域，不新增价格网格、全历史重复读或超20根搜索。日线原量化分支仍可能影响开销，不能凭根数宣称性能已通过。计算／DTO超预算沿现XXM_BUDGET_EXCEEDED失败，不返回截断域、旧版缓存或跳过精度分支。

有界回归未来按输入集／比例／周期分单元保存实际身份、进度和结果；完成单元核SHA后读回，失败单元保留错误再继续。中断后继续与最后身份／完整域／文件保护检查都计入相应原验收预算，不从已完成单元无条件整轮重算。本轮不改执行脚本；正式路由验收范围及新单元确切数量在下一步完整审计和独立期望阶段锁定，不拿文档预算代替执行预算。

### 27.11 编码门禁、待明确项及建议

本节为§24.10／§21.12通用清单的本步补充，不替代原门禁；无新增例外白名单：

| 适用约束 | 本节落点及验证 | 当前状态 |
| --- | --- | --- |
| 单一事实源、默认行为、确定分区 | §27.3—27.6；唯一step副本、完整域和状态正反例 | 代码已审计，设计已写，产品未改 |
| 合同先确认、前端不拼事实 | §27.5／27.7；新原因、真实API四项display、TS接收及拒绝反例 | 直接影响明确，完整消费者／枚举确认留下一步 |
| 配置集中、范围与读写 | §27.1／27.10；原Spec不改预算，无正式写入 | 本轮保持；新身份迁移尚未设计完 |
| 性能与异常 | §27.10；deadline检查、精度／超预算失败，完整域不截断 | 原预算不变；新版性能未验收 |
| 测试独立、有用户可见结果 | §27.8／27.9；字面与Fraction预期、路由／TS／文字逐项断言 | 样例已列，预期冻结／新测试待后续 |
| 设计与交付同步 | 预测方案§32、原算法方案§12.43和末表；原页面布局保持 | 本轮文档同步；后续Figma／页面验收仍保留 |

待明确项分开登记，不能全部混称“还缺截图”：

| 待明确事项 | 现有依据／处理建议 | 是否挡住下一步方案审计 |
| --- | --- | --- |
| 软件真实DIF=0时究竟如何判定 | 已有候选采用严格>0；未取得原软件零值实验。继续保留研究边界，不能改成≥0或epsilon | 不挡住；若后续出现反例，回到原方案修订 |
| 软件首次黄字与内部实际ref，以及4/13极近零读数 | 4/16讲稿只支持消失日，当根候选不是唯一公式证明；继续使用现证据，不重复索取无图区间 | 不挡住；不把模型的首次日期／ref升为真值 |
| CURRENT_DIF_NOT_POSITIVE枚举及完整消费者 | 为避免错误文案建议单列；尚需下一步审计并确认合同变更 | 不挡住继续设计；挡住直接修改合同／编码 |
| 新算法／预测身份、缓存与恢复点 | 必须拒绝旧语义状态并同步全部消费者；本轮未选择版本字符串或设计迁移 | 不挡住继续设计；挡住产品接入 |
| 各真实输入集／三门槛独立期望与新版预测预算 | §26.7／27.9已列方法，尚未执行 | 不挡住下一步；开发前准备、开发后验收各有停点 |
| 2020以前正式日线及完整四周期整页 | 仍按原TODO等数据通知，不擅自扩读／裁剪 | 不挡住方案；仍限制正式整体验收结论 |

**建议下一步只完成身份、缓存及全部合同消费者的审计和迁移LLD，再准备独立预期；目前不进入产品编码。** 本节预测设计可供审阅，无须管理员再找同组图片。软件未知与工程待办分别保留，不用测试通过掩盖未知，也不因缺少零值图停止可继续的工程设计。

### 27.12 本轮文档核算结果

使用现有未修改产品及既有ZC研究类，按§27.8已先写明的输入／预期核算，四周期共24项首次激活对照、8项已有TOP DULL结构转换及11项日线取整检查均符合预期。实际调用step共156次；新预测执行次数0，不是新版forecast／真实API／性能验收，也没有新增软件真值或测试文件。

独立Fraction核得分钟新增理想分界`1103/14`，日线正值中点`4412351/56000`；P=60旧产品／研究候选分别激活／不激活，P=100都激活，P=210都不激活。已有TOP DULL在当根负DIF时继续按原color_flip确认，未误加首次门槛；日线0.0006的实际来源可能值为0.001。额外演示研究对象交给现`clone`后会成为产品类，P=60又激活，父snapshot保持；这证实旧clone不能证明新候选预测通过，而非要求改成动态子类。

本轮登记的176个源码、测试和旧证据文件SHA保持，临时核算保留在`/private/tmp/xxm_top_forecast_lld_literal_audit_20261018.json`。完整数学分区、新原因枚举、三门槛预期、产品迁移及预算检查仍为未来门禁，不能把这些字面核算计作已完成。

## 28 版本、缓存、保存状态及消费者迁移LLD（2026-10-18，拟修订，未实施）

### 28.1 本步目标和权限

管理员要求继续第二项。本轮只审计§26／§27所需的版本、缓存、snapshot／checkpoint、API、前端、测试与验收工具，并把迁移方式写到原文档。不是开发授权，不修改产品、测试、执行脚本、配置、历史报告或正式数据，不执行API／数据库／Lake请求，不重跑行情或生成全量期望。正式范围仍000001.SH的日线、60／90／120分钟；原底部、R1、来源、业务日期、端点和预算保持。

CodeGraph本轮使用`codegraph_explore(XxmSpec/ForecastSpec/SeriesEntry/IndexDetailXxmQueryService/IndexDetailXxmForecastQueryService)`和`codegraph_impact(XxmResponseDto, depth=2)`。返回的动态路由／TS消费者不完整，已按实际import、字段与版本引用补核。对`src`、`wealth/src`、主题研究及`tests`检索到82个含XXM引用的源码文件，22个直接含版本／双hash／排除原因；另对仓库代码做接口／模块／版本引用核查，55个直接引用文件均在上述范围，没有发现范围外消费者。非字面引用的forecast求解函数继续按§27覆盖，不把这82个文件误称为82个API或全都要修改。历史reports不是现行实现，保留原件与SHA。下面按真实职责列全部现行链路与直接迁移点；本轮没有改变目录或依赖矩阵。

### 28.2 实现方与消费者逐项处置

| 当前文件／链路 | 当前实际作用 | 未来处置 |
| --- | --- | --- |
| 服务目录 `spec.py::XxmSpec/MAIN_SPEC`、`forecast_spec.py::ForecastSpec/FORECAST_SPEC` | 唯一不可变产品身份及参数来源 | 仅升级版本字段默认值；其余规则／预算参数不变，不新增策略开关 |
| `calculator.py::_id/snapshot/restore` | 事件／历史／等待编号包含版本及specHash；恢复严格核hash、对象、周期、来源 | 保持公式与snapshot字段；新hash拒绝旧状态，不能修改旧snapshot的hash后复用 |
| 查询目录 `query_service.py::XxmCache/SeriesEntry/load_entry/_load_series/_response`、`shared_loads.py` | 共用序列缓存、重叠加载、1000根恢复点、源指纹、截至投影 | 保持现key结构及复用；新Spec产生新key，新序列从原完整真实前缀计算 |
| 查询目录 `forecast_query_service.py::build/_active_confirmation` | 从同一真实entry恢复状态，双Spec／源／日历组成预测key，组装DTO与display | 保持；不能用旧points拼新识别状态或改旧确认关联 |
| `src/biz/schemas/wealth/market/index_detail_xxm.py::XxmResponseDto` | 识别版本及完整specHash已等于MAIN_SPEC才接受；关联严格校验 | 继续由MAIN_SPEC驱动，不新增版本别名或双版本接受 |
| 同目录 `index_detail_xxm_forecast.py::EntryExclusionDto/ForecastResponseDto` | 预测版本Literal为r1；两个hash目前只是str，未核当前Spec；现枚举无新原因 | Literal升级拟定r2，根校验补完整双hash相等；新排除原因仅进activation原因，见§28.6 |
| `src/biz/api/wealth/market/index_detail_xxm.py`、`index_detail_minute_xxm.py`、`index_detail_xxm_forecast.py` | 三条路由／解析／鉴权／异常转换的唯一入口 | 路径、参数、状态码、分钟开放条件均不改；新版字段由原响应类输出 |
| `src/app/api/v1/router.py`及分钟装配 | 注入原DB、鉴权、分钟根与能力；不计算XXM | 保持注册及依赖；无新API／启动任务／配置 |
| `wealth/.../xxm/types.ts/adapter.ts` | 识别类型；adapter目前只比r1版本并检查hash格式，然后核价格／指标／关联 | 同步新身份；版本和完整hash都须相等；继续严格数据和关联校验 |
| `wealth/.../xxm/useIndexXxmLayer.ts/apiClient.ts` | 请求调度、5秒客户端超时、迟到隔离；hook内存缓存每次apply会走adapter | 原URL／调度／缓存结构保持；不从响应自行学一个新版本便放行 |
| `wealth/.../xxm-forecast/types.ts/adapter.ts/apiClient.ts` | 预测Literal、入口原因白名单、周期／回放／关系校验；hash目前仅格式 | 同步新预测身份和原因；完整双hash核对，不增加字段或前端计算 |
| `wealth/.../xxm-forecast/useXxmForecast.ts/XxmForecastCard.tsx` | 四周期生命周期／刷新；只有ready才显示条件，错误保留旧截至说明 | 保持四行、刷新、取消和错误状态，不把旧响应重新标成ready |
| 日／分钟 `IndexChartWorkspace`→识别hook→adapter→`XxmMacdPrimitive/markerGeometry/XxmLayerUi` | 画事件及详情；不执行识别资格 | 不改布局、标注规则或自行过滤负DIF事件；新编号整体关联 |
| `IndexDetailPage`→`IndexInfoRail`→`IndexTechnicalTab`→预测卡；共用`indexDetailRequestScheduler`、`wealthFetch` | 装配、调度和鉴权传输，无版本事实缓存 | 保持；不增加全局升级服务／新缓存／请求参数 |

`wealth/...`指`wealth/src/features/index-detail/`下对应目录；查询／服务目录仍为原`src/biz/**/wealth/market/index_detail_xxm/`。相邻九转、K线、分钟指标的合同与指标版本不受算法语义版本影响；不得顺便升级它们。

### 28.3 拟定的唯一新版身份及配置审计

建议沿既有r1继续递增为下表r2，尚未写入源码或对外生效；本次只改版本默认值，不新增`top_*_policy`等Spec字段。因为现specHash包含版本，改默认值已足以区分新语义；增加可选策略会违反本轮单一规则和不新增开关的范围。

| 字段／主产品1.0 | 当前r1 | 本次拟定r2 |
| --- | --- | --- |
| algorithm_version | xxm-direction-v0.1-r1 | xxm-direction-v0.1-r2 |
| MAIN_SPEC.spec_hash | `533a9b441e49c1b2c076482ad6815f61e49494f63ec2c8c922a03d868e4ce730` | `6db425730c72f22ea756c121a832f27c966d1324ef0a72a2312a3c572038724d` |
| forecast_version | xxm-key-point-forecast-v0.3-r1 | xxm-key-point-forecast-v0.3-r2 |
| FORECAST_SPEC.spec_hash | `983eae6fffebc5b76e3fa2cac210bb10e5f68db080af4fdb927baecde360dcae` | `add5e3636e6972e267bdda81c05e0e864f600f9e67d658b6a560445e39dda6d8` |

以上拟定hash由当前全部字段的独立字典仅替换版本后按现序列化规则核算：检测器使用`json.dumps(...,sort_keys=True,separators=(',',':'))`；预测使用`json.dumps(...,sort_keys=True)`，其空格格式与检测器不同，不能“顺手统一”导致身份漂移。XxmSpec的0.75／1.0／1.2三组hash各不相同；拟定0.75为`ddc241ad701a483a0e1659ed1a70ef46e695499199776c13694a29ddda3c1a04`，1.2为`81992335d6bd197e56cc2ff6d02b35fe46ddc61cfbeb282fb3e5e375bd3d2021`。正式API仍只用MAIN_SPEC=1.0，不开放参数选择。

| 名称／来源 | 持久化／消费者／生效 | 本次安排与验证 |
| --- | --- | --- |
| algorithm_version、spec_hash；`spec.py` | 代码默认值、不可变Spec；内核、恢复、query/cache、识别DTO、研究验收；未来新进程使用新值 | 仅版本默认值拟变；XxmSpec仍拒绝自行传其他版本／规则；独立字典hash及三门槛测试 |
| forecast_version、forecastSpecHash；`forecast_spec.py` | 代码Spec；forecast/query/cache、预测DTO和验收 | 仅版本默认值拟变；20根、250尾部、精度、200ms等不变；不加Settings/env |
| 前端所接受的版本／hash | 是固定API合同值，不是运营配置；从上述Python Spec核算后同步到现types模块，由adapter和测试导入 | `xxm/types.ts`拟导出`XXM_ALGORITHM_VERSION/XXM_SPEC_HASH`；`xxm-forecast/types.ts`拟导出`XXM_FORECAST_VERSION/XXM_FORECAST_SPEC_HASH`；不另建配置模块 |
| CURRENT_DIF_NOT_POSITIVE | 是固定原因枚举，不是参数；后端EntryExclusionDto、根校验、求解和文案；前端adapter | 只允许activation原因，未知原因继续拒绝；不增页面开关或HTTP异常码 |

前端保留现类型形状：`XxmResponse.algorithmVersion`仍可为string，以便原非法响应测试表达错误输入；预测forecastVersion的Literal随合同升级。版本和hash字面值不再散落在多个adapter／正向夹具；放在现types中统一导入，测试另有独立字面hash断言，不能只让两端引用同一错误常量后自证。Python DTO仍从正式Spec核身份；预测版本Literal保留OpenAPI枚举并同步新值，不为少写一个字面值改成任意string。

### 28.4 缓存、共享加载与来源身份

本轮审计确认均为进程／hook内存状态，无XXM数据库表或持久化计算缓存需要迁移：

| 现key／数据 | 已有隔离依据 | 新版安排 |
| --- | --- | --- |
| 序列key | `(bind identity,lake_identity,period,MAIN_SPEC.spec_hash)` | 新hash必为新key；旧entry不能作为新序列增量前缀 |
| 重叠加载flight_key | 序列key＋业务日期、自然日期、完成端点提示 | 保持；两个算法身份不能等同共享一次业务计算；完成flight会删除，不是另一层TTL缓存 |
| 预测key | bind、lake、period、检测器hash、预测hash、真实前缀指纹、expected、asOf、日历身份 | 两个新hash共同隔离；LATEST／REPLAY、截至和日历继续隔离，不改key结构 |
| source.inputId／sourceInputId | origin＋每根时间和四个数值的连续hash，与算法版本分开 | 同源同前缀应保持，不能为了算法升级伪造源修订 |
| calendarInputId／指标indicatorVersion | 真实日历和来源指标的身份 | 不改；算法版本与来源版本不能混同 |
| forecastId | 现`digest(payload)`，包含当时的双hash和计算事实；在display／refreshAfterMs加入前计算 | 公式和时序不改；不得声称该ID现已逐字覆盖display |

正常新进程会自然产生空缓存；同一测试缓存里可以留下旧key作拒绝反例，但新请求只查询新key。无需清业务表、换Lake、改Redis或增加清缓存接口。`XxmCache`仍按64MiB／16项淘汰，预测读写仍深复制；`SharedLoads`沿原失败传播和重试。失败不把旧hash改成新hash兜底，也不把新旧两个算法暴露给用户选择。

### 28.5 snapshot、checkpoint和事件关联

`snapshot`仍只存原字段，specHash已足以绑定新算法；不额外添加algorithmVersion字段。`restore`继续先解析和验证，再原子更新对象：旧r1 hash、错来源／周期／对象均须拒绝且不改变已有状态。主API不能接收外部snapshot；旧状态的正确处理是从原完整真实来源重新计算，而不是把元数据改成r2后续算。

`SeriesEntry.checkpoints`仅属于该entry，按现1000根保存。新hash缓存未命中应新建空entry，沿同一来源从头计算，生成新恢复点；同版过去查询继续使用最近不晚于目标的checkpoint，剩余最多999根，不能把未来point或旧版确认关联带入。内核副本继续用真实spec／来源恢复，不改成研究子类。

`_id`含版本和hash，所以即使底部业务事件完全保持，它们的id也会全部随新身份变化。普通事件、顶部历史、底部历史、structureEventId和rearm编号必须以新内核一次生成并相互对应，不从旧响应复制部分编号。跨版回归分两层：日期／方向／类型／路径／参照／结束原因及关联含义保持；每个版本的编号按原独立hash公式分别核验，并将同一结构的新旧关联逐项对应。禁止简单删除所有id字段后宣称一致，也不能要求跨版全部JSON字节相等。

### 28.6 Python与TS合同的具体改动

识别DTO保留`consistent_window`对MAIN_SPEC两个值的严格比较；前端`buildXxmViewModel`改为同时等于本轮拟定的版本常量与完整MAIN hash，替换当前“版本相同＋hash格式正确即可”。价格／MACD／窗口／关联校验全部保留。

预测DTO的`forecastVersion`改Literal r2，`consistent`开头增加`forecastSpecHash==FORECAST_SPEC.spec_hash`及`detectorSpecHash==MAIN_SPEC.spec_hash`；参数为纯代码Spec，不由请求或payload给出期待值。前端`adaptForecast`以同一产品1.0身份的两个常量作相等校验，保留hash格式、周期、asOf、mode和全部关系检查。不能只把字段改名／版本文字升为r2而继续接受r1 hash。

新原因按§27建议纳入本次拟议合同：

| 所在位置 | 未来要求 |
| --- | --- |
| `EntryExclusionDto.reason`及TS adapter的entryReasons | 在原五项上加CURRENT_DIF_NOT_POSITIVE，其他未知值仍拒绝 |
| `ForecastResponseDto.consistent`及`adaptForecast` | 若activation排除中出现该值，必须dataStatus READY、ordinaryState NONE、direction TOP、rearmContext null；沿原状态合法性允许CONDITIONAL_ENTRY／ENTRY_ONLY／NO_CANDIDATE／PRECISION_PENDING |
| 根reasonCode、targetEntryExclusions.reason、nextBarOutcomes.outcome | 不增加这个值；出现在这些位置须拒绝 |
| activation有效范围和价格分区 | 新原因只说明确定未激活，不得与有效范围重叠；数值完整性仍由求解／测试证明，DTO不重算指标 |
| `forecast_text.make_display` | 单独写“DIF未转为正值，顶钝化条件不成立”；select_display不把它视为可省略远端背离边界 |

本节是完整调用方审计后的**合同变更提案**，不是管理员已批准修改API。没有新字段、请求参数、status、事件类型或HTTP错误码；路径和现错误处理不变。只有方案／LLD经确认且获得开发授权后才同步修改Python、TS及全部当前测试，不保留旧版接受分支。

### 28.7 前端缓存、迟到响应和页面边界

识别hook的`version.current`来自响应，cache.version与它相等只能证明“这是刚存过的响应”，不能证明它是当前算法；真正拒绝由每次apply中的adapter完成。因此复用现缓存结构、在adapter核固定新身份即可，不需再加浏览器持久缓存、版本请求或自动升级服务。缓存apply失败仍先清本地缓存再请求，网络响应身份错误则进入error、data=null、标注清空；只重试本层。

预测client在返回hook前已调用adaptForecast；新版本／hash／原因不合法应拒绝。hook现catch可以保留旧response作截至说明，但phase为error，Card不显示旧targetText和conditionsText；不得将旧条件继续显示为ready。保留取消控制及generation隔离，切换指数、日期、周期或隐藏后迟到的旧响应不能写回当前行。

完整新构建需与新后端共同验收；旧浏览器页不会自动加载新的JavaScript，不能承诺旧页面无刷新即跨版本升级。发布和页面刷新另按获准发布流程执行，本轮不部署、不改静态资源缓存策略，也不为此增加双版本兼容。API客户端、Scheduler、5秒客户端超时与4秒后端预算保持，页面布局、分钟开放条件不扩展。

### 28.8 测试夹具与历史证据不能批量改版本

| 当前消费者 | 未来迁移方式与保留项 |
| --- | --- |
| `test_xxm_calculator.py`两个全量TOP不变测试、版本／hash字面断言及恢复测试 | 按§26.7先固定各自真实源／三门槛独立新预期；再改产品／当前身份断言。保留旧源和旧账本；补r1恢复拒绝、新版成功恢复／回退正例 |
| `tests/web/test_wealth_index_detail_xxm_api.py`、`test_wealth_index_detail_xxm_forecast_api.py` | 当前正向响应使用新身份；旧版／混配hash、新原因错位及非法关联继续作反例；不把旧价格／状态断言全删掉 |
| TS `xxmFixtures.test-support.ts`、`adapter.test.tsx`、`useIndexXxmLayer.test.tsx`、预测`forecast.test.tsx/apiClient.test.ts` | 人工结构夹具明确标注，正向身份用当前常量；'a'／'b'任意hash不能继续当正常身份；另保留独立字面hash断言和旧版拒绝 |
| TS `xxm/rearmContract.test.tsx`、`xxm-forecast/r1Contract.test.tsx`及forecast.test中真实路由成功案例 | 目前直接读R1 `api/`／`api_02/`旧响应。旧JSON永久原样作为历史／拒绝依据；新的成功案例必须从修改后的真实路由生成独立新目录并核来源、事件和display，不可复制旧JSON仅改版本／hash／id |
| `test_xxm_forecast_display.py`旧payload及旧规则文字测试 | 纯文案／几何样例可继续引用注明历史的旧事实，不经当前DTO冒充当前API；新增当根原因用独立字面。若调用当前adapter则换真实新版响应 |
| 现研究子类及日期筛选测试 | 父类更新后BASE不再是旧R1；改前固定原产物和身份。原结果不重写、不用改后研究类自生成新版expected；这些入口不再用作新版产品验收 |

合法旧版本反例文字（包括v0.1／h1／a1／r1）继续存在，不能用“旧版本字符串清零”误删它们；应清零的是产品及当前正向消费者对旧语义的接受。R1纯软件观察、52项等级、10日期保护、四次模拟及底部业务结果仍逐项验收，不能以版本变化为由放宽。源指标版本和身份不改；跨版业务关联及新id均须独立核验。

### 28.9 现验收工具复用与迁移位置

已阅读实际委派：`reference_rescue_acceptance.main`调用`bottom_history_acceptance.main`；其frozen模式再委派`reference_rescue_acceptance.frozen_mode`，replay-budget委派同模块`formal_replay_mode`。不是按文件名猜有两套当前引擎。本次拟复用这条有界来源／路由／预算链，不新增另一套计算器或临时验收入口。

| 当前工具 | 已核实的约束／问题 | 未来安排 |
| --- | --- | --- |
| `xxm/reference_rescue_acceptance.py` | frozen_mode绑定R1预检目录及1215组旧数学结果；formal_replay_mode绑定R1 api_02响应 | 在第三步准备新独立预期manifest后，原函数一次迁到该已批准manifest／真实源身份；不再拿旧TOP数学结果当新expected，不保留运行时旧引擎分支；旧R1证据原样保存 |
| `xxm/bottom_history_acceptance.py` | 原路由／读取／预算可复用；api_mode硬编码预测r1，另有历史观察断言 | 版本比较统一取FORECAST_SPEC；业务观察断言保留；新输出必须新目录，原frozen委派及显式periods范围保护不变 |
| `xxm_page_request_audit.py/.mjs` | Python audit_context给MAIN身份，JS硬编码预测r1；运行实际TS client／adapter | 审计context补预测版本和hash，JS核完整身份及同批sourceInputId；复用实际TS代码。不能让context报什么就信什么，还须过TS固定新身份校验 |
| `xxm_forecast_display_audit.py` | product模式走当前真实query／DTO；candidate模式仅换显示，不是新识别预测 | 只复用product模式；不能以candidate参数绕过新算法身份校验或冒充新内核性能 |
| `xxm/daily_window_precheck.py::check` | 捕获源manifest带采集时r1 specHash，当前直接要求等于MAIN；接口／源保护齐全 | 复用源须核已批准原manifest SHA、文件SHA、窗口和真实合同；将“源采集时身份”与“本轮计算身份”分别记录。不得直接删校验或改旧manifest的hash，不需重新采集相同行情 |
| `same_segment_acceptance/acceptance`、旧R1原型及日期筛选入口 | 针对旧研究／旧数值定义；导入当前父类并不等于仍能重放旧算法 | 保留历史入口说明和已冻结证据，退出新版成功验收清单；不加旧算法兼容。现研究工具清退仍按原TODO另做，不在此顺手删文件 |
| `scripts/research/index_market/README.md` | 当前混有R1／A1运行记录 | 未来开发时更新当前入口／新manifest，原命令明确为历史；本轮不改命令或执行脚本 |

上述工具的模式、默认四周期、显式分钟选择及正式只读标志均保持；不借迁移隐藏日线缺口或在产品裁剪历史。新预期manifest的结构、真实输入数量和所覆盖预测样本数由下一步先审计并落原方案，再生成；本轮不自动改工具去跑未知数量。

### 28.10 必须具备的正反例及代码落点

| 硬要求 | 正向测试 | 反向测试／验收位置 |
| --- | --- | --- |
| 唯一新版Spec及三组比例 | 各自独立字典算hash、MAIN=1.0，双版本常量符合§28.3 | 非默认算法字段仍被拒绝；不能用同一Spec helper产expected；calculator测试 |
| 旧状态不得继续算 | r2同源同周期snapshot恢复、过去查询和1000根checkpoint继续一致 | r1 hash／错源／错周期恢复拒绝且父对象不变；不伪造仅改hash的旧状态；calculator／API测试 |
| 缓存与共享加载隔离 | 同版同源暖命中、同版两请求共用加载；正常源修订及业务日期变化仍重建 | r1序列／forecast key不能命中新key；单独更改检测器或预测hash也隔离；`test_xxm_shared_loads.py`及两个API测试 |
| 预测必须使用完整双身份 | r2 Literal＋两Spec精确hash通过；识别和预测同前缀源指纹相同 | r2文字＋r1或任意合法格式hash拒绝；错误hash不能靠格式蒙混；Python和TS合同测试 |
| 新原因只能是首次TOP激活排除 | NONE／TOP有合法activation时接收，文字明确未触发 | BOTTOM、已有DULL、rearmContext、根reasonCode、target原因及next outcome中的同值拒绝；未知原因继续拒绝 |
| 旧响应不展示为新版事实 | 新版真实路由输出驱动日／分钟图层与四周期display | 原R1 JSON直接交新adapter须拒绝；迟到／错hash／旧缓存与重试不得显示旧标注／条件；hook／Card测试 |
| 跨版底部修正保持且编号自洽 | 原业务日期／事件／ref相同，新结构／历史／等待关联指向新编号 | 混入旧structureEventId／relatedRearmId拒绝；不能只比去id后的JSON；DTO／TS关联及独立hash核验 |
| 来源与预算保护保留 | 正常追加、修订、同批LATEST／REPLAY、冷暖和两并发、分钟范围正常通过 | 错manifest／source SHA、缺交易日、超预算、取消／超时保持失败；不多读正式源补证；原验收工具 |

本节补充§21.12／24.10／27.11的编码门禁：事实源／合同／默认行为／确定性落在§28.2—28.7，配置审计落§28.3，性能／异常落§28.11，用户可见结果落上述hook、Card及实际TS验收。无新通用清单例外。目录和架构未变，无需改架构快照。

### 28.11 读写、失败、中断和预算

本轮只修改原四份XXM文档；静态引用／hash核算及小量现DTO／缓存／restore核验最多60秒，最多读取两份原API JSON（各≤1MiB）、≤500个合成bar，不调用HTTP／DB／Lake。最后文档、链接及保护文件核查60秒，继续审计核已完成清单60秒，总程序预算180秒；人工阅读评审不计程序耗时。本轮不运行pytest全套、不改测试，也不安装依赖。失败保留实际输入／输出，继续先核源代码和证据SHA；不修改现错误使它通过，不把文档检查称为新版验收。

未来仍为每请求≤4秒、预测≤200ms、预测响应≤32KiB、识别≤1MiB／2000点、缓存≤64MiB／16项、服务两并发、客户端5秒；不扩大历史读取，不放宽校准／连续性。新身份触发完整计算后的冷加载也须纳入4秒，不能只测暖缓存。恢复点按原1000根，续跑及最后hash／关系／完整域检查仍计入对应执行预算。超时／取消不得发布未完成的新entry／预测；旧版命中不可作为失败兜底。

未来新期望／验收按源manifest、代码SHA、版本／双hash、输入集／比例／周期保存完整单元，完成后读回并校验。中断保留已完成单元及失败，继续只补未完成且身份完全相同的单元；代码或期望有变化用新批次，不覆盖旧报告。正式数据全局读取仍需单独批准，本设计不自动扩大已有只读授权；较早日线及整页待办沿原记录，本轮未重查当前数据库是否补齐。

### 28.12 本步结论和后续停点

版本／缓存／恢复／消费者的修改方式已明确，可供管理员审阅；算法和预测仍是r1现实现，r2是完整迁移提案。新原因枚举、预测双hash严格校验及拟定版本需要随方案确认后才能落码，本轮不视为已改合同。

建议下一步只准备并锁定独立验收预期：先按§26.7逐个核原测试真实输入／manifest、数量和三组比例，再将拟修订识别业务结果与独立预测边界／预期分开保存；父类仍未改变时完成，不能修改后用研究子类生成自己的expected。该准备完成后，对§26—§28逐条审计，再申请／依据明确开发授权实施最小升级。当前不需要新增截图；软件零值、首次黄字和实际ref未知不与工程待办混为一项。

本步不能宣称产品已升级、四周期新版验收通过或原软件已完全还原。旧日线2020起隔离及分钟技术成绩保留为旧R1历史结果，2020以前正式日线／四周期整页／Figma／原型清退仍保留原TODO。

### 28.13 本轮有界核验结果

独立字典核算了当前r1及拟定r2的两Spec和三组检测器比例，未创建可运行的新Spec或修改源码。复用两份原R1真实路由JSON核现DTO：基线均通过；单独把预测forecastSpecHash改成64位a、detectorSpecHash改成64位b仍被接受，复现两项当前校验缺口；识别错hash、当前预测DTO收到拟定r2版本、新原因枚举均按现合同拒绝。后面三项是当前拒绝行为，不能称r2已接受或修复完成。

原`XxmCache`同key命中、返回深复制不污染缓存通过；在同源／同截至下，单改检测器hash、单改预测hash及同时改二者三种key都不命中旧预测。四周期各两根合成输入共8次step，同版snapshot恢复一致，8次不同hash恢复均拒绝且父状态不变。现XxmSpec拒绝临时传r2版本，证实未来必须改唯一默认值而非调用时注入策略。

本步登记的195个源码／测试／旧证据文件及两份API原件保持；临时审计为`/private/tmp/xxm_identity_lld_inventory_20261018.json`、`/private/tmp/xxm_identity_lld_audit_20261018.json`和仓库引用核查JSON。没有新算法执行、TS执行、行情／正式API／性能验收或全量预期生成。本节的结论是迁移方案有代码依据，仍须下一步独立预期和开发前确认。


## 29 首次TOP修订的独立验收预期准备（2026-10-18，产品开发前）

### 29.1 本步目标与边界

管理员授权继续第三项：在旧父类尚未改变时，锁定§26—§28未来测试所用的识别结果和独立预测预期。本步允许修改本节列明的研究准备工具、新报告和原四份文档；不改产品内核、Spec、API／TS合同、现有测试、旧报告和运行入口，不调用HTTP、数据库或Lake，不安装依赖。当前产品仍为r1；生成的r2编号只是按已设计公式独立计算的预期，不能称产品已运行r2。

既有`top_daily_ambiguity.audit`固定主比例且不输出每根完整XxmStep，不能直接覆盖现测试另外两套来源和三比例；因此增加同主题`xxm/top_activation_expectations.py`，只负责来源核验、调用既有ZC研究类和保存结果，不另写识别／预测引擎。现验收入口保持不动，未来开发按§28.9接入本步manifest。

### 29.2 已审计的真实来源与范围

| 输入集／现消费者 | 周期及实际根数 | 来源规则 |
| --- | --- | --- |
| 旧分钟拼接，`test_entire_frozen_ordinary_and_historical_baseline` | m60 1316、m90 1107、m120 738，共3161 | 原`load_frozen_inputs`；原历史报告列11份CSV的SHA、重叠一致，缺DEA仅按原测试规则推得，不能作正式源验收 |
| 原source audit，`test_full_four_period_top_oracle_and_first_activation_are_preserved`及原1215预测样本 | day 912、m60 17260、m90 12945、m120 8630，共39747 | 原`load_source`，manifest和真实字段保持；日线2023-01-03起，与2020起源不能互换 |
| 2020起日线，后续日线隔离验收 | day 1643 | 原daily_2020_source_01／manifest，2020-01-02至2026-10-16；与source audit日线912根重叠逐字段一致 |

三套共44551根，分钟长源被主报告复用，不重复计为新来源。每个实际周期×0.75／1.0／1.2，共24个识别单元、133653根计算输入。旧原件、manifest、研究父类和产品代码均先锁SHA。CodeGraph本步使用`codegraph_explore(load_frozen_inputs, ReferenceGateCalculator, test_full_four_period_top_oracle_and_first_activation_are_preserved)`；图包含无关同名符号，已按真实导入补核两项测试、来源loader、原预测预检和当前父类，不把图中遗漏视为无消费者。

### 29.3 逐条执行约束与保存位置

| 必须保持的口径 | 工具落点／验收 |
| --- | --- |
| 旧父类未变，候选仅ZC，不再筛其他假设 | 启动核r1默认及代码SHA；每单元BASE／ZC并行逐根；波段和历史池逐根相等 |
| 预期不是开发后现算 | 新目录`reports/xxm_top_activation_expectations_20261018_01/`保存manifest、24个完成单元及SHA；未来测试读取冻结文件，禁止调用研究子类产expected |
| 保留完整输出，不只锁事件计数 | 每根保存完整point／events／histories／bottom_histories／rearm_records；流式gzip，另存最终snapshot、历史记录、差异和计数。BASE每根摘要及所有变化留档 |
| 底部、等待和历史修正保持 | 逐根BOTTOM事件、bottom_histories、rearm_records完全相等；不能删ID后比较；主源1.0与原ZC报告全部事件核同 |
| 新编号独立且关联自洽 | 按§28.7的字面hash公式核每个r1编号、计算r2编号，依赖原事件／历史／等待记录建立一一对应；保留对应表，不丢关联字段或只改版本标签 |
| 继续与失败不能覆盖证据 | 复用`cross_index_daily.seal/read_unit`；gzip文件先临时文件再原子完成，元数据带压缩文件SHA。完成单元先读回和校验；半文件／身份变化拒绝，失败另记，不通过改旧预期消除错误 |
| 预测预期独立于求解器 | `top_activation_math.py`只用Fraction和字面来源精度算式，保存分钟／日线激活、严格边界、P—C、确认／无解和已有钝化负DIF反例；不调用forecast／solve_entry_ranges生成expected |
| 原1215样本不被一笔删掉 | 原结果SHA、真实prefix与新旧普通状态／参照／等待逐项登记；区分可复用、首次TOP域须重核、状态变化须重核。旧结果保持，不把待重核项写成新版通过 |

识别单元的r2预期是ZC旧父类业务结果加独立编号公式转换。它与未来产品实现独立，但不是第二份原软件真值；软件52项、模拟和讲稿的证据等级不升级。恢复检查每单元末100根，同源同版restore后完整step及snapshot相等；完成产物读回核每行、总数、最后时点及摘要。

### 29.4 预测数学的具体交付与限制

承接§27.8的字面前缀及投影，先锁`D(P)=(28P-2206)/351`，分钟有效域`(1103/14,1429/7)`；日线首次正值界`4412351/56000`及原guard，日线上界另按参照10的三位取整严格条件。P=60不激活、100激活、210不激活；已有TOP DULL负DIF仍可color_flip；BOTTOM不加限制。独立按递推算第二根D(P,C)、H(P,C)，写出转向比例三组下完整C不等式及正价／参照存活交集，锁最早第二根和无入口则无确认，不调用旧预测器套研究类。

1215个真实预测原结果的完整迁移，必须按实际新状态判断。BOTTOM及已激活状态只有全部预测上下文等价时才可复用；NONE TOP即便当前状态没变，未来激活范围仍可能变，必须标为需新域核验。新结果中依赖旧状态的确认／无解、最近端点、完整display不得凭旧JSON或本步小样例宣称已验收。分类后若存在尚无独立P—C／最近性依据的真实项，明确列数量和日期，下一步先补这部分，不直接进入产品编码。

**首次分类后的继续范围（先补设计）：** 24单元完成后，原1215项分为693项可保留旧完整预期、522项NONE TOP需重核，无普通预测上下文变化项。522项中210项的所有可用历史DIF均不大于0或不大于当前段DIF，新增资格与原背离不等式已不可能同时成立；另312项均为分钟。继续只对这522项准备独立不等式预期：新增`top_activation_real_math.py`，读取已锁定prefix和来源，经原`recover_projection`取得并验证投影起点，将其值作为输入常量，使用Fraction推导首次入口和第二根完整C条件，不调用产品forecast、entry、joint或研究预测器。它只产验收的数学依据，不新增运行计算器／产品入口。

分钟对每个原池参照分别求`P>0`、当根D(P)>0、H(P)>0、两根数量、原段／最近历史价格严格门槛、`max(段DIF,D(P))<参照DIF`的交集。按原最强DIF／最近优先扣除已归属参照的范围，保存完整区间及开闭边界。第二根为`D2(P,C)=aP+KC+b`，`A1(P)=.8*A0+.2*D1(P)`；color_flip为D2<A1且C>0，dif_turn为A1<D2≤(1-q/100)D1且C>0。D1>0、A1<D1使这些区间中的D2不突破原参照；已有负DIF信号另用字面例核，不套这条首次推导。

逐个有效P区间证明存在正C：优先证明整区间D2(P,0)<0，便有0<C足够小形成第二根结构；不成立则保留未解决项，不猜最早时点或另扫20根。NONE最早第一根只能激活，故第二根可行即最早。210项空域证明、312项实际入口是否为空及最早性分别落新完成单元；仅在全部有证明时撤销“真实预测预期待补”停点。精确分数预期不冒认产品浮点根归属；未来仍须核原浮点包络及实际step，完整域外不允许借容差扩大范围。日线只有空域证明时无需另造三位P—C；日线非空P—C的小样例完整覆盖仍是开发测试要求，不宣称本步已产生该类真实样本。

新数学补证保留最初分类及所有冻结识别单元，不改其manifest或旧summary；另锁新工具、已完成分类／源SHA及独立补证的完成标记。新增常量运算／校准读取仍在29.5的总480秒和原本地数据范围内，≤522项、≤200个独立前缀，不增加step额度，失败／中断沿原规则。不得用旧forecast产新expected。

### 29.5 配置、性能和最后验收

无新增运行配置，比例沿现XxmSpec三值；所有路径固定上述本地冻结报告，输出只在新报告目录。输入≤44551根、24单元；BASE＋ZC共267306次step，恢复／继续总额外≤12000次，合成佐证≤500次，整步≤300000次；不增加正式读取。常驻内存≤256MiB，单压缩文件≤20MiB、解压内容≤128MiB，总产物≤512MiB。单单元60秒、全部计算240秒，继续校验120秒，最后完整读回／SHA／文档120秒，总程序预算480秒，人工阅读不计；超限失败保留，不自动放宽。

小量工具测试只验证独立数学字面值、编号公式与坏文件／恢复规则，不更改旧产品测试。最后核24单元完整、三比例、各源数量和SHA、BOTTOM保护、ID映射、1215项分类及未知项、原文件未变和§13引擎表仍在原方案末尾。此步是预期准备；正式新版识别、预测、API、页面与冷暖性能仍在后续开发／验收阶段。

### 29.6 本步执行结果

开发前预期报告（原记录：`reports/xxm_top_activation_expectations_20261018_01/README.md`）已完成24单元、133653根逐根预期和三组比例，三套源各自SHA／数量／真实转换保持。每根完整point／事件／两类历史／等待均保存，全部BOTTOM事件及底部历史／等待逐根相等。每单元恢复末100根一致，共2400根；11293项编号映射独立核r1／拟定r2及全部关联，完整文件读回和输入字段相符。主比例主源四周期事件与原ZC事件全字段相等；912根日线另起源，不冒认与1643根历史状态完全一样。

1215项分类为693项可保留旧完整数学／display预期、522项首次TOP域需新依据，预测普通上下文没有差异项。初始summary保留待核状态；后续另存12个数学完成单元：210项由历史DIF条件证明无域，另312项共104个独立分钟前缀校准投影后，9项价格／DIF交集为空，303项有域。最终219项无入口，303项有完整参照及P—C不等式并证明最早第二根；每周期／比例和实际日期见`forecast_inventory.json`及`independent_real_*`，没有删除原1215项或让旧预测器产新答案。

独立字面算式覆盖分钟严格入口、三门槛P—C、11个日线舍入例、已有负DIF钝化与无入口。96个四周期三比例小例、456次现候选step佐证通过，两个新增准备工具测试文件7项通过；未修改旧产品测试。一次初始C=100预期写错、一次新测试系数抄错，均在各自冻结前按独立分数重算纠正，保留两份correction JSON；未依据产品结果改预期，未改旧夹具。

计算11.17秒、真实数学补证0.76秒、最后全文件／编号／字面佐证2.59秒；压缩逐根文件13762847字节，最大解压文件小于128MiB。BASE＋ZC 267306次step、恢复2400次、小例456次，总270162次，低于300000上限。61个原代码／测试和36个源／旧证据及准备工具SHA保持；无HTTP／数据库／Lake或配置写入，产品仍r1。

本步完成的是开发前可独立读取的预期。剩余工作是按§26—§28最终对账并实施单一r2修订，随后核真实浮点分界／日线非空P—C、完整输出／原因文字、DTO／TS、恢复缓存及正式路由／预算；这些仍未验收。软件零值／首次黄字／实际ref未知不影响将工作假设进入工程验证，但不能升级为软件公式已证。无新增截图需求，原更早日线／整页等TODO保留。


## 30 首次TOP资格修订的最终对账与开发（2026-10-19，已获本轮开发授权）

### 30.1 本步目标、范围及当前审计

管理员授权：先对识别、预测、版本和消费者逐条对账，通过后按LLD开发。依据§26—§29及原方案§12.46；本次授权包括§28的r2版本、严格双hash及CURRENT_DIF_NOT_POSITIVE枚举同步，保持现路径／参数／字段形状。只改首次TOP及必要联动，不改原选择器、BOTTOM、等待重入、已有信号转换、来源或页面布局，不增加参数／开关／备用引擎，不提交／推送／部署。

开工核dev-interface及现脏文件，保持既有工作。原预期manifest内61个代码／测试、36个源／旧证据及准备工具当前SHA全部吻合。CodeGraph核solve_entry_ranges、query／calculator／DTO及impact depth 2，补读真实路由、schema、cache、TS adapter／hook／Card和验收委派。图含旧报告同名函数且部分消费缺失，以真实导入补核，不视作无依赖。before_code_manifest及pre_development_audit保存在`reports/xxm_top_activation_r2_implementation_20261019/`。

### 30.2 硬口径落点与正反例

| 约束 | 本轮实现落点 | 验收 |
| --- | --- | --- |
| 只对首次TOP检查真实当根DIF>0 | calculator.step最后activation分支；selector不改 | 负／零／微小正值、段峰正而当根负、同段稍后转正；原历史消失不被提前return吞掉 |
| BOTTOM和已有钝化保持 | 原分支及同一唯一内核 | 三源三门槛24单元133653根完整step、历史、等待、r2关联等于原冻结预期，零基值仍从真实已激活状态验证 |
| 首次域完整收窄 | forecast_entry分界／稳定证明／原因 | 分数边界、完整正价分区、日线+.0005／guard／.0006、分钟根／ULP，504份独立证据（分类更正见§30.6）；不得旧预测末尾删例子 |
| 后续确认不加首次条件 | 原forecast／paths／joint与唯一产品clone | 负DIF已有TOP可形成结构，BOTTOM完整数学和R1反例保持；父snapshot不变 |
| 原因和身份统一迁移 | 两Spec、DTO／TS现types与adapter、make_display | r2独立hash、完整双hash；新原因只允许NONE TOP activation，错位置和未知值拒绝，原r1 JSON拒绝 |
| 旧状态不继续算 | 原cache key及restore校验不变 | 旧hash／错源／错周期拒绝且对象不变；同版继续／过去查询、正常追加和修订不被误拦 |
| 原测试预期不能被改写 | 两全量测试读取§29冻结文件，原源和账本保留 | 同样输入逐字段、计数和历史关联核验；原零基值例修成先激活，不能用不再激活冒充转向规则通过 |
| 真实路由产生新正向夹具 | 原api_mode、真实三路由／query／DTO | 新目录api样本驱动TS，旧JSON原字节保留；类型／hook／Card含错hash／旧版／迟到错误保护 |
| 验收入口继续原链 | reference_rescue_acceptance原frozen/replay函数；daily_window原check；page audit双身份 | frozen改用§29清单及独立数学；原源采集身份与现计算身份分开并核原manifest；不新增另一条产品入口 |

准备工具中IdMap的旧版样例须用冻结r1数据记录，不能因当前XxmSpec已r2而试图构造可执行r1。原研究子类选择器的字面测试仍可验证不变selector，但不得再用其BASE生成旧预期；本轮不清退原研究代码。

### 30.3 读写、配置及执行计划

无新配置：只改唯一两个Spec版本默认值，三比例和所有运行预算／精度参数保持；TS常量是固定合同，不是运营参数。只读原三个本地冻结输入、日历、§29文件和旧JSON；隔离SQLite只创建本次临时fixture，生产者字段按原源合同，不读取／写入正式DB、Lake或DG。

沿原`reference_rescue_acceptance --mode frozen/api`生成新子目录，失败原样保留；frozen的每个周期／比例完整单元完成后保存，读回核SHA；同代码／输入／预期身份可在原新报告内读回完成单元，只重做未完成单元，变更代码用新批次不覆盖。原命令拒绝已存在输出目录的行为不改；继续检查由内部已完成单元读取负责，若入口拒绝或身份变化则保留原失败并明确新批次重跑范围，禁止偷改completed数据。API和正式验收仍保持mode／formal-source边界；本轮不主动执行formal-source模式。

单次来源仍44551根、完整识别24单元；原1215预测按§30.6已确认更正为711旧完整预期、213无入口和291第二根P—C独立条件。验证helper只读取expected，不调用研究类。forecast未改变的旧711响应保留全部MATH_KEYS及display断言；changed504核完整入口域、参照、精度空隙、完整目标不等式和最近时点及展示值在真域中，不能只比status或三个样本。

程序执行预算：Python主题／API测试及24冻结单元合计600秒；1215预测／恢复／读回300秒；隔离真实API和日线检查300秒；Wealth typecheck／test／build600秒；中断继续身份核验及最后对账180秒，总1980秒，不包含编辑阅读。每单元预测保持原200ms、路由4秒、响应32KiB／1MiB、64MiB／16项缓存、两并发及5秒客户端。超限保留失败，不放宽参数。输出单文件≤20MiB、逐根gzip沿原20MiB／解压128MiB、总报告≤512MiB、常驻≤256MiB（构建工具独立进程不算内核常驻）；不全量重复扫描正式数据。新源码／断言变化后只重跑受影响检查，已通过且无影响的检查复用。

### 30.4 完成条件

逐条记录实际改动、测试、24单元／1215结果、真实隔离路由响应、TS当前正向消费／旧版拒绝及最后文件保护。正式全历史日线／四周期整页、Figma和原型清退保持原TODO，本轮不把冻结fixture计时写成正式数据库／部署／页面验收。若发现与方案矛盾，先记录具体冲突并停相应实现；不得靠改旧预期或吞错误通过。完成结果见§30.8。


### 30.5 验收发现的预期分类冲突（2026-10-19，后续已确认更正）

首次frozen_01在2024-08-15日线0.75处失败：原分类按NONE＋红段将本根视为首次TOP候选，但原完整结果及原／新context均有当根BOTTOM STRUCTURE，query及原验收均先返回CONFIRMED。审计发现四周期共6时点×3比例18项同类错误，均应保留原完整已确认响应。详见更正提案（原记录：`reports/xxm_top_activation_r2_implementation_20261019/expected_classification_correction_proposal.md`）及逐项JSON／原源SHA。

拟议更正为711项原完整保持、504项首次TOP独立验证（213无入口、291第二根），总1215不变。原§29的693／522／219／303分类不能再当作完整API预期已证；原冻结文件全部保留，不反写。此处是分类漏掉既有确认优先，不是要改底部规则，也不需要新截图。

根AGENTS“若发现计划口径与当前实现、真实数据或源接口行为冲突，必须停下来说明冲突点，等待确认”适用。暂停该项预测验收及后续依赖验证，准备更正后等待确认；不改内核迎合错误NO_CANDIDATE。识别与独立小例105项已通过，另一个新零基值测试错误把合法历史价格消失也当成无事件，依据形成峰103、下一根104补为明确历史事件预期；原普通转向仍为STRUCTURE，没有修改产品规则。


### 30.6 分类更正已确认（2026-10-19）

管理员明确“同意更正并继续”。只新增`forecast_classification_correction.json`及完成SHA，引用原inventory／18项原响应SHA和原确认事件；不改原冻结目录。将这18项移入完整旧响应保持，总711；余504按原独立证据核213无入口／291第二根。frozen入口以原清单加此已确认更正为唯一口径，原三比例／四周期／总1215不变，不保留一个绕开错误的备用模式。原frozen_01失败保留，修正验收工具后用frozen_02批次；现产品的底部确认优先未改。后续执行已恢复授权。


验收数值核对补充：frozen_03在分钟完整域检查发现，独立分数根与现浮点算式根中心相差约4e-12；原8ULP包络并未扩大，错误是验证器将该差值也计作越界。验证器改为分别核浮点中心与独立分数根的误差、原中心±8ULP的实际端点，产品分界／比较／预算均不改。原失败及输入保存，不放宽产品精度或重写独立预期。

### 30.7 最后读回检查

复核§30.3的继续执行路径发现：若某周期三个比例均从完整单元读回，原汇总仍引用本次未计算的events。完成单元须同时封存该单元的事件，读回时使用其中事件生成汇总；单元身份／SHA、拒绝不同代码和不覆盖目录的入口行为保持。仅修研究验收函数，产品／API／来源不动。补一个完整读回的隔离测试，禁止重新调用识别和预测；再以新批次完成原1215项，原frozen_05成绩和文件保留。额外程序预算120秒，含该测试、完整冻结复核和最后文件对账；原单次模型200ms及全部产品预算不变。


### 30.8 开发完成后的逐条对账（2026-10-19）

本轮开发和冻结／隔离技术验收完成，正式全历史／网络／页面边界仍按§30.4。完整证据、逐文件清单和失败记录见[本轮报告](../../../../reports/xxm/conclusions/xxm_top_activation_r2_implementation_20261019/README.md)。

| §26—§30要求 | 当前代码／消费者 | 完成证据 |
| --- | --- | --- |
| 仅首次TOP用当根DIF>0，非段峰；稍后转正可激活，旧历史继续 | calculator.step末activation分支；selector及此前分支原样 | 四周期负／±0／微小正值、已有负DIF信号、零基值及旧历史价格消失字面；24单元133653完整step等于封存预期 |
| BOTTOM、R1切换／等待及已激活信号不加条件 | 原calculator／forecast／paths／joint不改 | 原完整BOTTOM业务及新版本关联逐根；4软件模拟、45处前缀／恢复；18项当根BOTTOM确认优先保持 |
| 完整激活域和精度、新原因 | forecast_entry分界／稳定证明／reason_for，forecast_text | 分数根与现浮点根分开核；原guard／8ULP不变；504完整入口／参照／目标条件，分钟零根、日线.0004/.0005/.0006；独立字面文案保留下界 |
| 双版本及双hash、旧缓存／snapshot拒绝 | 两Spec；ForecastResponseDto、两TS types／adapter | r2字面hash；真实query下旧series及三种旧／混合forecast key不命中；同版暖缓存深复制保持；旧r1响应、错hash、新原因错位／未知值拒绝 |
| 新路由响应作当前正向夹具 | 原api_mode、Python／TS真实API合同测试 | 新api目录18场景及401／403；原冻结117文件及36份源／旧证据SHA不改，旧API JSON保留，禁止只换版本冒充 |
| 原验收入口及继续执行 | frozen_mode、frozen_inputs、forecast_expectations、daily_window；page audit身份 | frozen_06全1215＋45恢复通过；已完成单元读回事件且不重算、SHA损坏／身份变化拒绝测试通过；日线旧采集身份单独核SHA，正常新采集正例通过 |
| 原预算／来源边界及消费者 | 同query／路由、hook／Card／client | 冻结模型最长82.94ms；1643日线隔离最长171.51ms，20冷／20暖及并发、响应／缓存原限制通过；前端1191项、类型／构建通过，正式PG／Lake／网络和整页未执行 |

Python最终主题及API共434项通过，包含6项收尾新增用例；无新增运行配置／依赖／业务写入，未提交或部署。本轮使用CodeGraph explore及impact后补核真实导入，未修改子系统边界／依赖矩阵；未确认的软件内部公式不因本轮通过而视为已证明。

资源核验补充：完成原数据检查后，用现有两个CLI新批次单独测量进程峰值；frozen_08_memory为221921280字节（约212MiB），daily_2020_02_memory为124387328字节（约119MiB），均小于256MiB。两批次原数值／响应门槛继续通过，日线模型最长171.51ms；没有拿被测进程外的构建内存作内核内存。系统time工具读取kern.clockrate被当前执行环境拒绝，frozen_07_memory的产品结果通过但统计命令退出1；失败日志保留，随后仅用wait4取得该子进程实际资源使用，无需增加权限或安装工具。目录总量及单文件最后核验保持512MiB／20MiB预算。

### 30.9 r2后续验收TODO（2026-10-19，管理员要求先记录）

本节先按管理员要求登记TODO；后续管理员已批准前两项并在§31完成，勾选和结果以§31.5为准，第三项实际页面仍待办。最初登记时只补待办、不执行检查；§30.8已完成的开发、冻结／隔离测试和原证据保留。后续安排执行前，按本LLD核对届时的代码、数据范围和执行条件；原性能上限不变。

- [x] **真实数据接口的正确性验收。** 对上证日线、60／90／120分钟，使用系统实际数据调用识别和预测接口，核对数据截至时间、事件、参照、预测条件及两接口使用的来源是否一致。覆盖已有历史场景和当前查询，记录实际结果；底部和已激活钝化不追加限制。
- [x] **真实数据接口的性能验收。** 分别检查首次查询、重复查询和识别／预测同时查询时的耗时、内存、响应大小及缓存复用，沿用§30.3的4秒请求、200毫秒预测等现有上限。保存实测报告后再勾选，不能用冻结／隔离环境成绩代替。
- [ ] **四周期实际页面验收。** 在实际页面逐项检查日线、60／90／120分钟的标注位置、事件日期与悬停内容、预测文字是否与接口一致，以及切换周期／日期、刷新和请求失败后的显示。记录页面证据与发现的问题，未通过项保持待办。

2020年以前日线继续引用原TODO（原记录：`reports/xxm_reference_rescue_r1_implementation_20261017/before_2020_pending.md`）：本次§31核实现存2010起来源无缺口，完整来源日线接口与性能已补验；其完整整页部分仍待办，原旧快照保留。本节只登记后续验收，不改算法、API、架构边界、原测试结果或历史验收记录。

## 31 r2真实数据接口的正确性与性能验收（2026-10-19，本轮获准）

### 31.1 目标、范围与现有代码依据

管理员要求先提交此前修改，并开始§30.9前两项验收。此前代码／研究／证据已提交为`f035a9e6c`，无推送／部署。本轮仅运行真实数据接口的正确性及首次、重复、并发查询性能检查；四周期实际页面、Figma、原型清退和2020以前日线专项TODO仍保留，不扩展算法规则。

CodeGraph explore核`formal_replay_mode`、`budget_mode`、三路由、query／read_daily／future_calendar及正式分钟reader，并补读当前实现和字段生产者。已有入口为`xxm.reference_rescue_acceptance`委派`bottom_history_acceptance.main`；`--mode replay-budget|budget --formal-source`真实路由调用正常鉴权、现有数据库依赖与唯一r2内核。不是已部署远端HTTP服务验收：使用本机TestClient调用同一三路由，正式来源及当前鉴权配置保持，并单独说明网络／部署边界。

现工具日线回放预期来自912根旧夹具；较长源前缀曾影响投影校准，因此不能未经来源核对就把旧短前缀响应当完整日线金样本。先做下述有界来源预检；若存在缺口，保留失败并继续有条件的分钟验收，不截成2020起绕过。若来源范围／值变化，先列出差异及现方案处理依据，再决定原工具是否适用；不修改产品迎合旧预期。

### 31.2 数据读取与禁止项

- 连接：应用现有Settings指定的数据库，经原`get_db_session`进入`SET TRANSACTION READ ONLY`；只记录主机／端口／库名，不输出连接串、口令或token，不改配置／鉴权。
- PostgreSQL白名单：`core_serving.index_factor_pro`，仅`ts_code='000001.SH'`，字段`trade_date, close, macd_dif_bfq, macd_dea_bfq, macd_bfq`；共用`core_serving.trade_calendar`仅`exchange='SSE'`的`trade_date,is_open`，历史从1990-01-01至统一业务日／当前日期，预测未来90个自然日，沿当前FORECAST_SPEC.future_calendar_days，不增大上限。
- 分钟：只读`/Volumes/datasource/data_lake`下正式Gold主要指数bars／indicators的60／90／120频度，过滤`000001.SH`；只取身份、日期／时间、close及macd_dif/macd_dea/macd。沿现reader列投影、完整历史及两数据集端点对账。不得使用退役Lake、DG事件／任务状态或临时夹具代替。
- 范围与上限：单指数、四周期，旧源分别912／17260／12945／8630根；正式新增部分按实际业务日读取，单周期上限20000根，日线原1000根按日期继续读取的批次，识别响应最多2000点；日历不超过1990至当前加既有未来窗口。不读全市场明细，不导出无关字段。
- 第一阶段仅SQL聚合计数／缺失日期统计与必要元数据，不导出历史明细。正式API执行前仍检查该来源完整性。没有正式DB／Lake／DG写入、下载、服务重启、依赖安装或部署。

### 31.3 分步执行、预算与失败处理

1. 只读预检：当前单指数日线最早／最晚／总行数／NULL、SSE开市日对照及2020前后缺口统计；同时核当前配置和正式根。使用临时审计脚本，只输出白名单聚合，单SQL15秒、全阶段60秒，无重试循环。
2. 正确性：适用的原`replay-budget`场景逐周期运行，每个场景保存识别和预测响应，核日期、完整数学／display、普通状态、确认／等待及来源身份。来源有变化或日线短前缀不适用时单列，不能删除差异或默默降为只比status；必要调整验收工具须先在本节补代码级设计和测试。
3. 性能：原`budget`每周期20首次＋20重复预测，配对识别、LATEST及一组两并发；最多四周期332个业务请求，原回放18场景另36请求。首次指新应用缓存，操作系统／数据库缓存不清空。原4秒／200ms／32KiB／1MiB／64MiB与16项／两并发保持，不放宽。预计正常性能执行≤360秒，回放≤120秒，完整预检／中断后重做未完成周期／最终核验各60／240／120秒，总≤900秒；报告≤128MiB，单响应／记录文件≤20MiB。
4. 中断／失败：输出必须新批次目录；原工具逐请求原子保存记录，失败原件保留。新批次只重做失败／未完成周期，已通过周期复用其代码／输入／身份相符证据，不覆盖原结果；每周期前后核r2双hash。停止领取新请求即结束本批，不启动后台任务。
5. 完成：两项只有在真实来源对应范围全部通过后才勾选；有缺口、来源变化、鉴权／连接限制或超时则明确哪个周期／哪项未通过。正式数据正确性、原软件公式证明和实际浏览器页面分开记录。原测试、旧文件与冻结预期不改；本轮验收结果随后写回本节及原方案／预测方案。

### 31.4 日线回放对照的审计与修订

预检实际通过：应用库`152.136.106.251:5432/goldenshare`，只读事务；统一业务日2026-10-16，日线实际2010-01-04起4074根，SSE应有4074、缺0、必需字段NULL为0。原工具仍读取912根API夹具，其中2024/7/23等被旧投影校准保护；本轮既有2020起1643根r2隔离产物已在相同场景解除保护并解释过。不能改正式来源、不能继续拿912根结果判完整日线。

修订只落研究验收工具`reference_rescue_acceptance.py`：新增一个读取既有对照响应的函数，日线唯一使用已提交的`daily_2020_02_memory/case_<index>_forecast.json`，三个分钟周期继续原r2 `api/`响应。日线必须核该批run／result通过、原采集manifest SHA与既有冻结清单相符、真实r2 DTO身份及场景日期；文件不存在／身份错／来源错均拒绝，不回退旧912根结果。回放记录保存实际对照路径／SHA，仍比较全部MATH_KEYS、display及普通／确认／等待语义，数值断言不降级、不改变产品或原expected文件。这只验证真实来源接入与既有隔离路由一致，不把该产物说成独立软件公式证据。

正向测试读取五个既有完整日线场景，独立字面断言7/23、8/5的CONDITIONAL_ENTRY、8/22的NO_CANDIDATE、8/15的CONFIRMED，以及三个分钟周期原路径；反向测试核错日期／错hash／未通过记录／缺文件拒绝。先完成该测试再正式回放；§31.3预算与CLI不变。正式2010完整前缀若仍造成业务差异，保存双方字段和来源，不修改对照来迎合；该场景不得标为通过。2020以前专项TODO先记“输入缺口本次已核消除”，不凭聚合预检直接勾选全部历史语义验收。

§31.4识别侧补充：`formal_replay_mode`还须读取同一批对应识别响应（日线case_<index>_recognition、分钟api_<index>_<period>），核r2身份及场景当根唯一完整point、全部当根events，并保存对照文件SHA。不能把endDate返回的当日最后一根误当上午asOf根，必须按through准确查找。比较封装在研究工具的独立函数，新增纯字面正／反测试：正常未来附加行不误拦，错当根值、漏事件、重复或缺当根均拒绝。正式来源更长导致响应窗口不同，不比较窗口总点数；该边界不豁免当根状态／参照／关联字段。此处只补真实识别消费验证，产品不变。


### 31.5 本轮执行结果与TODO更新

两项均通过，统一业务日2026-10-16。正式日线当前2010-01-04起4074根，分钟60／90／120分别17272／12954／8636根；原冻结重叠全相符，无裁剪。当前正式来源日期／必需字段核验和日线完整前缀执行通过，2010以前不在现存范围，不扩大结论。

- 正确性18个既有场景、36业务请求：全MATH_KEYS及display、普通／确认／等待语义、through当根完整point和全部事件相符。五个日线使用原已提交的完整2020起r2隔离参考，4074根正式前缀在场景中与其相符；未改expected。旧原软件观察仍非新增盲测。
- 性能332业务请求：四周期各20首次＋20重复预测及配对识别320次，4 LATEST、4组两并发8次；单请求最长2.503738秒，已记录模型89.134ms，低于4秒／200ms。预测最大9208B、识别694143B；已记录缓存20311953B／2项，低于32KiB／1MiB／64MiB与16项。重复零内核重算、分钟零完整重读、并发来源／截至时间相符。首次只清应用缓存，未清OS／数据库缓存。
- 29项验收工具测试通过；产品源码及原frozen_mode计算体不变，117份原预期与36源／旧证据SHA保持。原CLI、鉴权和门槛不变，未写正式数据／安装／重启／部署，架构边界不变。

详见[本轮报告](../../../../reports/xxm/conclusions/xxm_top_activation_r2_formal_20261019/README.md)及summary／两批结果／日志。本轮由本机TestClient调用当前真实路由读取正式PG与Gold，当前正常配置quoteAuthRequired=false；未验远端已部署服务网络、登录权限或实际浏览器。前两项据此勾选，四周期实际页面及完整整页混合／双标签、Figma／原型清退仍未完成。2020以前旧TODO补记输入缺口消除和日线正式API通过，不用旧缺口继续阻塞，也不把页面部分勾选。

此前改动已提交`f035a9e6c`，本轮新增验收工具、测试、报告及TODO更新尚未另行提交。原性能执行208.4秒、正确性约35秒，含29测试及最终核验仍在§31.3总预算内，无中断／重试。

## 32 历史结构消失的找图日期筛选（2026-10-19，本轮已授权）

### 32.1 目标、依据与当前代码审计

对应算法§12.52，仅筛选上证四周期尚无外部确认的历史结构消失，优先日线及视频存在的日期。CodeGraph已查看产品`XxmCalculator._advance_bottom_history`及现行验收委派链；原代码确认顶部与底部历史记录分别关联结构，普通取消、同段结构消失不能混入历史消失。`reference_rescue_acceptance.frozen_mode`保存三组完整事件；`daily_window_precheck.replay_checks`保存2020起完整points/events。现有工具还会跑大量预测，不适合只补本次候选关联信息，因此另增`xxm/history_disappearance_screen.py`，所有事件仍由产品step产生。

复用`acceptance.load_source`核CSV原SHA，复用`daily_window_precheck.validate_capture_identity/validate_window`核获准旧日线采集及完整日历；分钟使用`frozen_inputs.expected_unit`的来源身份。封存r2结果按原完成标记核SHA。新入口串行执行四周期主参数，不修改或执行旧候选。每周期完整events与原r2逐字段相同，日线points亦须相同，否则停止并保留差异，不自行修改expected。

### 32.2 函数、字段和筛选范围

`history_record`从同一次step产物联接消失与原历史记录、结构事件，验证方向、身份、结束时间和原因；找出该结构之前最近一次同参照钝化。输出原结构时刻、价格锚点及时间、原DIF参照、消失时刻/价格/DIF、前一根DIF、保存根数、日历天数及价格严格突破余量。`dif_diagnostics`只按字面不等式记录当根DIF是否同向变化及是否至少达到原1%；前值为零明确不可作相对比例比较，不能偷偷增加识别限制。

`select_candidates`只接受2022-09-13起事件，排除本轮显式列出且有来源说明的已研究日期/周期。先保留全部有界事件清单，再给出日线、新的底部例、同根DIF对照有分歧、长保留或同日多周期的选择理由，不以命中率排名。三组已有事件通过发生时间、方向、所关联结构及参照比较；同日不同周期只算相关对照，不重复称独立样本。首次黄字/绿色无法准确定位时保持未知。新图到达后再单独逐项对账，本步不算新增软件真值。

读入4份来源、原manifest/日历及r2对应结果，白名单固定在脚本，不新增env、Settings、数据库或页面配置；只写新`reports/xxm_history_disappearance_screen_20261019_01`。每周期原子保存完成单元和SHA，identity记录全部来源、旧结果、产品和筛选源码SHA。继续同目录前必须核identity及完成单元；已完成只读，不重算、不覆盖；半成品不算完成。结果目录不允许是来源、仓库根或正式数据目录。结束再次核旧文件SHA。

### 32.3 性能、测试与验收

40478根一次串行主参数推进，每周期60秒、四周期240秒；三组旧结果逐周期读取后释放，不重算预测。测试与最终核验120秒，同身份中断后读回及最终对账另预留120秒。进程内存不超过256MiB，单文件20MiB、总新结果40MiB，超限失败，不扩读正式源。

隔离测试使用可人工核算的字面历史记录/事件：顶底联接及严格价格方向；丢关联/错方向/错结束时间拒绝；DIF反向和比例不足与等号、零基数；旧软件样本排除、视频起日边界、同日多周期不重复算独立样本；三组同日但关联结构不同不得标为一致；变更完成文件及继续身份拒绝。真实封存输入核完整事件一致、日线点位一致、三处底部原例保持及四周期输出数量/来源/候选关系，验证最终建议每条有实际计算依据。纯研究，不适用页面/API/鉴权验收，不修改其已通过结论；产品源码及旧证据保持是交付门禁。

### 32.4 本步结果

四周期40478根完整事件与已通过r2相同，日线1643点也相同；历史消失分别9/109/73/46，合计237，视频起日以后47条。四组优先图证为上证2024-01-08日线、2023-05-08日线、2024-05-10的90分钟及2024-03-11的120分钟，备用三组及完整关联见报告（原记录：`reports/xxm_history_disappearance_screen_20261019_01/README.md`）。后两组本地DIF在价格破高时仍回落，有附加DIF条件的辨别作用，但须先核软件读数。四组在三比例下事件时间/原结构/参照一致。

主筛选约0.638秒，进程峰值149504000字节，19项隔离测试通过，含中断后续读完成单元及拒绝变更身份/文件。旧输入、旧结果和产品SHA保持；新图0项，未知项未关闭。代码只新增离线筛选及其隔离测试，未改变产品、来源接入、接口、前端或架构依赖；未读正式源、提交或部署。

## 33 事前两处日线候选的新图证核对（2026-10-19，仅研究）

对应算法§12.53；复用当前r2与§32产物，仅读两张附件、封存日线CSV、day.json及daily_2020_02_memory/recognition_ledger.json。`calculator.py`中历史价格突破仍为当前产品事实；本步不调用新的竞争计算器，不改任何源码/消费者。原候选必须已在§32完成文件中，原事件链不得按图改写。

处理顺序：新目录保存两张原图同字节副本及SHA、用户视频链接；逐项人工登记软件显示和位置，对照源中同日close/DIF/DEA/hist及原ledger中从此前DULL到STRUCTURE到历史消失的事件。数值差用Decimal直接相减，显示位相等/非等与事件位置分别记账。1/8收盘使用管理员确认2869.34，不能用与本地接近的2889.34猜读替代；保留本地2887.5379。图中黄/紫字按当日柱位与原模型事件链作相容对照，不因此确认软件内部参照或首次精确发生公式。

仅新写reports/xxm_new_daily_evidence_20261019_01的原件、comparison.json、来源/完整性记录及README，原三文档补进展。旧产品、封存CSV/manifest、ledger及§32完成结果SHA在前后核验；不改旧软件52标签。无新配置/合同、数据库/Lake、安装、提交或部署，架构依赖不变。只读数值与既有记录的核对不新增测试文件；以字面相减、身份/日期/事件唯一性、原件同字节与SHA保存作为实际验收。MCP余额0与网页读取失败单独记来源获取限制，不称已取得讲稿。

图片/比较单文件20MiB、新结果总40MiB，比较保存60秒、最终核验60秒，继续身份核对60秒。中断保留原件和已完成结果，继续先核来源和输出SHA，禁止覆盖原件或已完成比较；证据不足字段为未确认，不将它填成NONE。结论最多为两处新观察与预先候选相容，不能据此确定价格是否还须附加DIF或软件数值差异原因。

本步结果：两张原图同字节保存，已存在的两条日线候选和三事件链保持。5/8收盘到显示位相同，DIF/DEA各差0.001、柱相同；1/8用户确认收2869.34，源2887.5379，差-18.1979，DIF/DEA/柱差+0.143/+0.028/+0.230。两图绿字存在和大致末端位置相容，软件实际参照、黄紫准确日期及1/8数值差原因未明，不宣称完整输入复现。取稿受MCP余额0限制，网页读取也失败；未取得讲稿，不编造口述。旧软件标签0改写，新图2、新稿0，报告见新证据（原记录：`reports/xxm_new_daily_evidence_20261019_01/README.md`）；产品、旧源及候选结果SHA保持，没有新代码、合同、页面或正式数据变更。

### 33.1 1/8全文到达后的补证步骤（2026-10-19）

对应算法§12.54，只有用户全文和原图/比较/候选读入；无新执行器、测试或产品代码。新建原证据目录transcript_update，原文同字节复制，摘录保存原文本、字符偏移和行号，不能伪造视频时间码。核全文有无直接“消失”、具体报价和截图时点；日期用2024-01-08星期一独立核周二/周三。仅从既有r2 ledger读1/8—1/10事件及原候选，不重算或把作者有条件展望写成已发生标签。

语义分别保存：十二月底存在第一次结构；1/8以后才谈新的日线钝化；绿色的精确触发未必在稿内；“无卖出理由”是作者操作判断，不能反推软件无消失；末尾16:01只证明授课结束在收盘之后，不证明截屏时点/价格来源相同。原稿后段“上證指應該是明天”与开头“最快周三”的差别按原文保留，先记对象/转写未核，不修订原话或产品来消除差别。

写入限新原稿、摘录JSON、比较和README；原报告仅追加已收到1/8稿的导航，保留旧comparison/source_access/final_checks等历史原件。当前原图、旧比较、候选、CSV/ledger及产品源码前后核SHA；原52标签保持。单文件/总新结果上限20MiB；保存/核文本30秒，最终60秒，继续读回身份30秒，中断保留已存原件，不覆盖完成记录。验收用原文逐字/定位一致、原件同字节、事件/日期身份、限制和输入差异未被抹去、文档/引用和SHA检查；不把这些检查称原软件公式验收。

本步补证：14690字节/121行原稿同字节保存，7段原文定位；旧比较/候选/图及产品保持。模型当日无新底钝化、周三1/10的新DULL与开头条件性判断相容，当前负柱两根前提给出一种解释，不据此确立软件普遍规则。稿中唯一“消失”非旧上证结构命名，讲课16:01不确认截屏时点，报价差异未解；“明天/周三”对象歧义未核。原稿取得1份但原精确标签不变，无新代码/测试或正式读取。见报告（原记录：`reports/xxm_new_daily_evidence_20261019_01/transcript_update/README.md`）。

### 33.2 管理员重新确认收盘后的更正（2026-10-19）

管理员明确2024/1/8收盘为2887.54，既有源2887.5379按两位显示一致。撤回§33/33.1将2869.34作为当日最终收盘及据此判定输入有18.1979点差的当前结论；原报告/比较/manifest和补稿均保留，不覆盖历史文件。截图光标可能对应旧柱，具体是哪根尚未确认；不追查其旧读数来阻塞研究。未绑定当日末根的DIF/DEA/柱差值也不作为已确认的当日算法误差，不能靠收盘更正推导指标已全部一致。

本步仅新增用户确认与更正说明，原三文档及报告导航补最新状态；以Decimal核2887.5379显示2887.54、2898.8787减2887.5379为11.3408。核旧manifest保护文件SHA及文档引用，不运行模型或改原候选/52标签，不改产品/合同/API/页面、正式数据或配置。纯文本保存/核对与最终检查各60秒，中断保留已有原件，不覆盖旧完成文件。后续新同方向钝化接替旧结构的研究另补对应方案/LLD后执行，本节不授权试算、读取新来源或开发。

## 34 3/11上证120分钟：历史消失与附加DIF条件（2026-10-19，仅研究）

对应算法§12.55。产品`calculator.py`历史顶部分支按原目标/新顶部事件优先，再检查已完成收盘严格破锁定高点；本轮只读该实现与封存结果，不改代码。输入仅新图、§32 m120.json及完成标记、原120分钟CSV/manifest与r2 frozen_m120_<比例>完整单元。原候选须已存在、完整单元SHA须符合标记；旧代码/源/结果SHA先后核验。

核对步骤：原图同字节保存；登记对象/周期/日期、末端四项数值，用Decimal/ROUND_HALF_UP按2位/3位核等；记录首绿字的原图位置与倒数两根K线对应，用户确认与视觉推测分开。软件末端数值只绑定3/11 15:00，上午精确值未知，不固定偏移反推。原模型3/8 15:00、3/11 11:30/15:00逐项列close/DIF/DEA/柱；前根DIF比较必须相邻，不能把3/11收盘直接与3/8收盘比较当作下午变化。

复用封存事件核3/1 activation、3/6结构、3/11上午历史消失与三组原比例的发生时点/关联结构/参照相同。局部诊断分别核两个时点的严格价格突破、原DIF未破、新TOP事件未接替及当根DIF变化是否>=0.75%/1%/1.2%；仅该局部其他条件固定的比较，不运行竞争状态机。上午DIF下降、下午回升，故若绿字实际挂下午，就不能声称附加条件已被排除。若挂上午，写条件性支持并保留软件历史数值/内部参照未知，不提升成全周期公式证明。

结果只新写reports/xxm_software_case_20240311_m120_20261019原件、manifest/比较/README；原方案/研究/LLD追加。5/10的90分钟用户未找到记材料不可得，不继续索同图，不新增无依据日期。无新执行器/测试/配置/合同/API/页面、DB/Lake/网络/安装或提交部署。单文件20MiB、合计30MiB，比较60秒、最终60秒、继续核身份60秒，中断保留完成产物不覆盖。验收为原件SHA、四项显示位、原候选/事件唯一性、相邻DIF及价格字面核算、三比例关联、旧文件保持和文档检查；未有软件历史读数的结论须保留条件，不能靠工具检查数量补足图证。

### 34.1 用户位置确认及新稿补证

管理员确认绿色首字对应上午小阳线，随后提供完整稿。只新增transcript_update/原稿同字节副本、逐字/行号摘录、用户确认与结论；初始comparison.json的待核状态保留，以新补证接续。重点核“为什么120分钟结构消失不加回来—所有按结构卖出都是敦化消失买回来—不是结构消失买回来”的完整问答，不单取提问作作者断言；还未红柱/未来二次顶部钝化分别记录。

结论范围为：旧顶部结构的消失身份、用户确认的3/11上午柱位与当前r2事件相符，末端4项数值按显示精度一致。在现有来源/同一结构参照与普通事件不变的局部比较中，附加DIF回升使时点由11:30延至15:00，故不追加该门槛、保留现行价格规则。软件上午精确DIF/真实参照未知、历史时点数值未独立核到，不把这项对照写成唯一完整软件公式。股市仓位和买回原话只用于事件语义区分，无功能/合同变更。

保存文本60秒、最后核对60秒、继续身份60秒；单文件20MiB、全部30MiB；原稿、旧compare、原图、封存源/事件和产品SHA保持，追加完成记录、不覆盖。验收为语义摘录上下文完整及行号正确、用户确认原字保留、既有数字/三比例事件与身份一致、旧文件和文档检查；不新增代码/测试/正式资源访问或部署。

本步结果：新图1、新完整稿1（14017字节/535行，4段原文定位），管理员确认上午11:30柱位；作者问答给出结构消失/钝化消失的明确区分。图末端四项按精度相同，原三比例事件/结构/参照相同；本地上午DIF-1.829%、下午+1.485%的局部比较支持保留价格主规则，不追加DIF回升。软件上午精确值及实际ref仍未直接取得，不写唯一公式。旧comparison待确认状态保留，由新补证接续；源/旧结果/产品保持，无代码或合同变化。详见报告（原记录：`reports/xxm_software_case_20240311_m120_20261019/README.md`）。

## 35 新同方向钝化接替旧结构的研究（2026-10-19，执行前设计）

目标和边界见算法§12.57；用户已批准该研究，未批准产品修改。CodeGraph已读当前XxmCalculator.step/_advance_bottom_history及研究load_bars/read_unit/expected_unit的真实实现：顶部历史在step内，底部独立推进，原参照失效和新同方向事件均先于历史破价；研究入口没有产品调用方。旧history_disappearance_screen只输出已实际消失的237条记录，缺被新DULL结束而未输出绿色的记录，无法直接完成本项。复用它的固定输入、身份及完成记录读回，新增history_replacement_screen.py及主题内隔离测试；产品和旧工具不改。

函数与数据：`local_followup`只接旧记录、原STRUCTURE、新DULL、按时序的既有bar及普通事件，校验id/方向/时间/结束原因/原参照一致。顶部是否已离原红柱段由确认后非正柱判断；底部沿用leftOriginAt并核实际非负柱。保存当根价格、原低/高点、同根破价与原DIF、DULL route、是否同原段；随后逐根先查原DIF严格突破，再查同方向STRUCTURE，跳过同方向DULL的该根破价，其余满足历史破价时登记首个后续时点和局部条件，不产生正式事件。无触发则保存原DIF结束/新结构接替/输入末端截尾的真实原因。必须区分同段dif_return，不能把它混入跨段历史问题；反向事件不终止本方向旧记录。

`screen_period`复用load_bars、BASELINE/FROZEN和read_unit；唯一当前内核只跑四周期主参数一次，收集完整事件/日线points及每条历史最后状态；核旧r2完整账本后，仅对new_top_DULL/new_bottom_DULL结束记录作局部后续。原STRUCTURE按关联id唯一查找，结束DULL按方向/time唯一查找，错误拒绝。每条输出原结构、新钝化、原锚点/参照、同段/跨段分类、同根诊断和后续首分歧/结束原因。`select_candidates`只接受视频起日后、已离开原段、有后续分歧者，日线先于分钟、90/120先于60，保留同日相关项不称独立样本。已有图片另以人工核对表对照，不将算法字段变成软件标签。

`run`复用旧identity与verify_protected，并将新入口源码、旧筛选完成文件和已用图文来源加入本批保护清单。身份/每周期/summary均用seal原子完成；续跑先核身份，已完成只读，损坏或变化拒绝，不重新生成旧预期。各周期前后及最后核旧源/产品/证据SHA；输出仅专用reports子目录，禁止来源或旧目录。无新增env/Settings/数据库/产品配置，不使用网络、正式API/Lake，也不改预测和消费链。

预算：4周期40478根主参数step不超过240秒；每周期局部比较上限1000000次bar检查/60秒，超限停止不改范围。测试及完整性核验120秒，续跑及最后重新核验120秒，全部480秒；每周期完成后释放bar/账本，常驻不超过256MiB；单文件20MiB、全报告40MiB。保存失败保留partial，完成标记未写成不算完成，不后台补跑或覆盖。

隔离测试以可人工核算的字面旧记录/价格/事件为预期：TOP/BOTTOM后续触发、严格等号不触发、原DIF与破价同根原DIF优先、新结构与破价同根新结构优先、后续新DULL同根不报但下一根仍能触发、反向事件不终止、同段与已离段分类、底部未离段不触发、截尾不冒充永久结束；错id/时间/方向/结束原因/重复普通事件及乱序拒绝。正常文件续读不重算，错完成SHA/身份拒绝。真实冻结验收核四周期完整events和日线points相等、9/2新黄/9/4取消原结果保持、逐条分歧算术和可找图日期依据、旧资料/产品不变。没有正式API/页面改动，无须重跑已通过接口和页面测试；本步成绩不当软件公式验收。

### 35.1 阶段结果与取证停止点

四周期40478根、日线1643points/完整events与原r2一致；433条新DULL结束旧记录中244条离原段，局部保留144条会有后续破价，73条先新STRUCTURE、27条先原DIF失效，无截尾。视频起日后分歧34条，非60分钟19条。24新测试及原19项共43通过；正常1.764秒、峰值164052992B、局部23727次bar检查；已完成单元续读不重算及旧SHA保持通过。单元测试替身只用于输出/恢复边界，真实冻结一致性由四周期执行单独完成。

原9/4资料纳入运行身份保护，随后人工重看9/3的90分钟和5/8日线，分别按其既有原件manifest核SHA，另保存material_review.json；不重写初次完成身份/summary。三处较晚静态观察与现规则相容，但没有把旧结构存在/当根标签和之后的保留机制都独立核清，不能当确定无事件。现在需2023/4/17上证日线覆盖3/7旧结构、4/14新钝化和4/17末端，4/18/4/19可备，先于4/21新结构。依管理员要求停止在取证处，产品与预测不改。完整报告（原记录：`reports/xxm_history_replacement_screen_20261019_01/README.md`）含逐条条件、限制和旧来源保护；无新正式数据读取/写入、安装、提交或部署。

### 35.2 4/18材料已到与交接（2026-10-19）

用户已提供备选2023/4/18上证日线，随后要求先整理线程交接。只保存原PNG同字节副本及receipt到本报告new_image_20230418/，记录SHA、尺寸、原路径和“已收待核”；不改原identity/summary/final_checks，不继续模型或图证结论，不把父报告旧等待状态当当前缺图。新图可正常打开；用户反馈的报错缺少错误信息，未定位原因，不登记为已修复。

本步只写[交接入口](../../../../docs/product/xxm-research-handoff-20261019.md)并补原文档导航，核现代码/提交、已保存验收成绩、59份旧保护SHA、新图同字节、链接及文档完整性。复制/核验与最后检查各60秒，中断保留新原件，存在文件只有字节一致才能复用，不覆盖旧记录。无新执行脚本/测试、正式数据读写、产品/合同/配置或提交部署；43测试等数字均引用前一步完成记录，不称本次重跑。

### 35.3 4/18原图继续核对的步骤（2026-10-19，研究获准）

管理员已授权继续本图研究，并允许看不清时针对具体位置求助。目标和范围见算法§12.57.1；现有`history_replacement_screen`已经保存原结构、新DULL、锁定价/原DIF及后续首个破价，本步直接复用，不新增入口或改脚本。当前内核已在接手时经CodeGraph `codegraph_explore`及真实源码核对，顶部step和底部_advance_bottom_history都把原DIF、新同向事件放在旧价格检查前；本步仅检验图片能否区分该工作规则，不触碰调用链、消费者或配置。

1. 先核PNG与receipt SHA、原day/summary/final_checks及complete文件、相关三比例记录、日线CSV来源manifest和产品文件身份，保存本步开始清单。原receipt的RECEIVED_PENDING_REVIEW是历史接收事实，不回写为新结论。
2. 查看原图，不裁剪、缩放后覆盖原件。记录对象、周期、画面日期、游标位置；以K线中心与下方柱端点对应，分别登记旧紫/新黄/末端绿色的文字、像素范围、可读程度和可对应日期。截图顶栏若不能确认属于末根，保留归属未知，不强算软件末端误差。
3. 从现有日线CSV仅投影3/1—4/21的日期/收盘/DIF/DEA/柱，并读取day.json中3/7结构—4/14新钝化对应记录和同版已保存事件；不重新初始化EMA或推进内核。已有0.75/1/1.2事件链只核身份/已存关联，不能按新图调比例。
4. 在新`review_20261019_01/comparison.json`分别保存软件实际观察、旧模型事件/数值、两种处理在4/17的原先差异、读数归属、未确认项及其原因。用户若确认文字/柱位，另存`user_confirmation.json`和补充结论，不覆盖初次待核文件。静态未见不能登记为软件从未输出；旧结构不在图内或标记重叠则先说明该处，必要时只询问现图位置。
5. 新目录保存来源/代码/原证据SHA的manifest、人工记录、README及最后核验；完成结果先写临时文件再同文件系统原子改名，存在结果拒绝覆盖。失败/中断保留，续读先核身份，仅补未完成材料。原父目录identity/day/summary/final_checks及完成标记、原PNG/receipt不改。最后向原方案、研究记录、交接及本接收目录导航追加新状态，不能把收图成功当结论完成。

无新增env/Settings/数据库配置或产品参数，无正式DB/Lake/网络读取、下载、依赖安装、业务写入、提交/部署。预算沿算法§12.57.1：读取/比较60秒、保存60秒、最后核验60秒、继续及重核60秒，总240秒；单文件20MiB、总30MiB、内存256MiB。只使用现有Python/工具读数和有界字面算术，不编写新研究算法；旧43项工程测试无需为人工图证重跑。验收分别核原图身份与读数时点、旧紫/新黄/绿色是否能对应、原条件算术、原保护SHA、追加文档及链接；若不能确定，明确保留未知，不修改产品和预期来迎合图片。

#### 35.3.1 原图初次核对与待确认位置

原图日期/周期及末价3393.33可读，按可见日期、末价和形态将读数对应4/18末根，未操作软件游标逐根核验。软件收盘/DIF/DEA与封存源按显示精度一致，柱20.174较源20.175少0.001，不记四项全同。旧紫色结构与3/7首根负柱形态对应；右端新黄色首字暂对应倒数第三根4/14，文字靠近相邻柱，已请管理员确认这处位置及后两根是否同样未见绿字。无清楚独立绿色的静态观察，不等于软件历史从未输出。

新comparison/来源37行/事前三比例事件和开始保护清单已保存到本图核对目录（原记录：`reports/xxm_history_replacement_screen_20261019_01/new_image_20230418/review_20261019_01/README.md`）。原三比例3/6—3/7—4/14—4/21链及参照相同，4/17旧价差57.2168、原DIF仍低18.633；没有新模型推进。原59份和本图/父完成记录等合计71份SHA保持，文档检查通过；用户位置确认未返回前，不结束该待核项或作通用公式结论，旧43测试未重跑。

### 35.4 4/14补图和管理员确认的保存/核对（2026-10-19）

本步获准范围见算法§12.57.2。当前已核实现与调用顺序沿§35.3，不改代码或依赖；复用原source_window.json的37行及prior_model.json中旧记录/三比例事件，已有办法足以完成，不新增入口。管理员新图是本题补证，不扩大到固定到期、其他R1案例或产品开发。

1. 在原review目录新增user_confirmation.json，逐字保存管理员回答；分别标注“应该是4/14”暂定、“4/17、18附近没有消失两字”明确，但只限所提供静态画面。原确认前comparison和final_checks不改。
2. 新建supplement_20230414/，先记录原71份保护及初次review各文件SHA，再把附件同字节保存到sources/day_20230414.png；记录原路径、尺寸、字节数和SHA，现有文件拒绝覆盖。未改4/18PNG/receipt或父day/summary/完成标记。
3. 直接读原图及必要临时局部像素，核对象/日线、顶部可见日期片段、右轴末价和末根，分别登记旧紫色/最右黄色的文字与柱位。若画面边缘截掉完整日期，按管理员所给日期、可见片段和对应收盘作说明，不能虚构完整日期可见。先确认读数归属，再与已保存4/14行比收盘/DIF/DEA/柱；差值原样保留，不反算或更正源。末根有黄字可证明当日图内已经钝化，不额外证明前一天必无黄字。
4. supplement_20230414/comparison.json分别保存新图观察、旧图用户确认、初次观察路径/SHA、37行来源路径/SHA、事前4/14—4/18价/DIF条件和局部结论。只做字面核对，不推进内核、预测或另写竞争公式。若两图支持当前工作规则，明确支持到本次上证日线案例；不把未见字计入原52标签准确率，不排除隐藏文字/更早显示/不同参照等尚未取得的证据。
5. 新README和最后核验追加到新目录，文件先.partial再同文件系统原子改名，存在结果拒绝覆盖；中断先核同一原件/身份，仅补未完成项。原文档追加当前结果和下一步，不覆盖历史待确认记录，不提交/部署。

配置/读写/预算：无新配置、产品/合同/API/页面变化，不读正式DB/Lake、不联网/下载/安装，不重跑43项旧测试。仅读已保存37行、旧事件与原件保护；附件≤20MiB、新输出≤30MiB、内存≤256MiB。复制核验60秒、比较保存60秒、最终核验60秒、继续及重核60秒，总240秒，包含中断和末次检查。验收须有原字节/确认原话、两图身份和读数归属、所有差值、事前记录不变、原保护与文档检查；只有本题材料核对完成，不宣称完整软件规则验收。

#### 35.4.1 两图及管理员确认的核对结果（2026-10-20）

4/14新PNG同字节保存，2796×1582/2532782B，SHA为85280879aa3ab33350c8eeee29d14ed805d229f5f3077946d848e2c965b16172。新图显示上证/日线，可见04/14片段、2023刻度及末价3338.15，完整顶部日期被边缘截掉，不虚构全日期可见。末根黄色“钝化”可见，旧紫仍在，补强当日已钝化的依据；没有4/13逐日阴性序列，不把管理员“应该”升级为首次发生日唯一证明。管理员另明确4/18画面4/17—18附近无“消失”，确认原话单存，初次comparison/final_checks/README不改。

软件4/14末端3338.15/17.648/12.043/11.211与源3338.1525/17.649/12.043/11.212对照，收盘和DEA按显示相同，DIF/柱各差-0.001；4/18原核对的柱差-0.001继续保留。未推断软件历史精确值或调整源。复用37行来源/事前旧记录/三比例事件，4/17旧价差57.2168、原DIF仍低18.633，继续留旧比较与现处理的分歧不变，没有新step/预测。

本组材料对当前“新钝化后停止这份旧结构比较”的工作选择增加局部支持；沿用同一记录/参照和文字会保留显示的前提下，不支持只跳过4/14而4/17继续自动显示旧绿。历史是否曾短暂显示/隐藏/删除、软件真实参照、永久有效期、全方向/周期仍未知，不称通用公式通过。新图/用户确认/comparison/README/最后核验见补证目录（原记录：`reports/xxm_history_replacement_screen_20261019_01/new_image_20230418/review_20261019_01/supplement_20230414/README.md`）。原77份保护不改、产品保持；本组材料核对可收束，无需再索同图，不扩大其他研究或开发。

## 36 旧结构有效期的首阶段记录整理（2026-10-20，研究获准）

目标/范围见算法§12.58。现Spec.fixed_expiry为None，TOP在step中、BOTTOM在_advance_bottom_history中按原DIF/新同向信号/破价结束，ageBars只计数；这是当前实现，不是软件真值。开工已用CodeGraph codegraph_explore核history_record/screen_period/read_unit/底部推进，补读顶部step和Spec；研究结果消费者为本轮报告/文档，产品没有新调用方，API/前端不改。

已有办法审计：history_disappearance_screen的四完成单元保存237条历史消失，含原结构/参照/ageBars和日历跨度，足以先选候选。重新调其CLI会重跑已通过识别，history_replacement_screen只含新DULL终止项，均不直接运行。以一次性临时只读整理处理已有JSON，复用read_unit的完成文件SHA语义；不复制/重写检测状态机，不新增持久研究入口。未结束、其他结束原因和全历史寿命分布不在本步，明确集合偏差，不把237条当全部结构。

1. 新目录保存开始manifest：原筛图identity/四周期JSON与complete/summary/final_checks、现r2主比例事件及必要其他比例/日线账本、原输入manifest/CSV及产品文件SHA。核与原保护和完成标记一致；状态/字段/版本错立即拒绝，不创建新expected。原完成记录不改。
2. 只读237条JSON，核period/方向/structureAt/time/价格参照和ageBars，按原结构及观察日都不早于2022-09-13筛视频候选；记录已用资料和不可得限制。分别列日线/分钟最长保留，候选只是模型数值，不作软件判断。复查旧69/136/102根线索是否在当前r2同一结构/参照中出现，若已被新信号/原DIF结束或旧版本差异改变，明确撤回其当前候选资格。
3. 拟选最多两组，先读同周期r2已存events及完成SHA，将绿色唯一关联原STRUCTURE/历史id/原参照，列期间同方向DULL/STRUCTURE/原DIF失效和反方向事件。再从已存CSV只取该结构到候选发生的时间/close/DIF/DEA/柱，最多每组2000行；列投影、对象/周期身份和日期边界来自原manifest及真实header。所选窗口的顺序/唯一、首尾、ageBars（不含确认当根）/自然日/色变、原DIF严格突破优先/同向新信号优先/首次严格破价核对；TOP按已保存锁定峰、BOTTOM还核离原段。遇竞争/错关联/缺行拒绝该项，不吞异常或按结果修字段；无状态机重放。
4. 对照已保存相关图片/完整稿/位置确认，逐项注明直接看到、按柱位映射、讲稿是否直接命名旧结构、旧紫是否可见、软件真实参照未知。现有材料不足时，报告至多两组最有用日期/周期/原结构/等待根数/应看范围；优先日线及90/120，60或已不可得材料不重复索取。不存在能区分的案例则停在此处说明，不能预设24根或永久保留去强配图片。
5. 新目录输出inventory/candidates/必要两组窗口及比较、material_review/README/final_checks，记录读取范围/实际次数及原保护SHA，写临时文件后同文件系统原子改名，完成文件拒绝覆盖；继续只在身份及原文件一致时读取完成结果、补未完成单元。不改原证据、产品、参数或旧52标签。结果回写原方案/LLD/研究/交接及主题导航，提交/部署另行授权。

没有新增env/Settings/数据库/产品参数或配置，不访问正式DB/Lake/网络、运行预测或新竞争引擎。程序预算：237条整理60秒、至多两组窗口各60秒、既有材料及保存60秒、最终60秒、继续与重核60秒，总360秒；常驻256MiB，单文件20MiB，总40MiB。文件SHA是身份保护，不解析未选分钟明细；仅提取至多两组有界源窗口，不为接手全读40478根。不新增算法代码，因此本步不重跑43项旧测试；核完成文件/实际生产者header和独立字面算术，人工查两组事件先后及等号/方向条件。若现记录不满足模型条件，按真实依据保存冲突并暂停该项，不迎合错误数据。最终结论只到“已核哪些候选、已有图能给何种最低有效期证据、具体还缺什么”，不作原软件通用有效期通过。

### 36.1 已有记录整理结果（2026-10-20）

237条完成JSON/完成SHA核验后，视频范围47条；只对90分钟23根、120分钟69根候选摘取24/70行，共94行。按真实CSV字段及已有manifest绑定000001.SH/周期，结构与绿色按历史id/参照唯一关联；三比例已存事件相符。独立SSE日历加原来源说明的90分钟11:00/14:00/15:00、120分钟11:30/15:00端点核两窗口缺0/多0，ageBars不含确认当根。无新内核step/预测/正式读取。

90分钟6/12 14:00—6/24 11:00跨23根/12天/两次变色，旧价3406.0967被3412.122破高6.0253，DIF0.0015755282656755298低于原23.498217554217263。120分钟11/14 15:00—次年1/6 11:30跨69根/53天/三次变色，旧价4029.5012被4069.376破高39.8748，DIF32.61195822721447低于原36.045260398387654。两组期间均无同向新DULL/STRUCTURE或严格原DIF突破；120分钟两条BOTTOM普通事件不结束TOP旧记录。

现有6/24的90分钟图重新核过，旧紫/末端绿黄可见，但原绿色时刻/身份未确认，数值差保留；已请管理员确认末绿首字11:00和最后旧紫6/12 14:00，答案未返回不设软件寿命下限。现有1/6原图为日线，旧全文不直接命名120分钟11月旧结构绿色，所以69根仍是最有价值的备用取证候选，未请求新图。原日线视频范围最大10根，既有137根在2021年排除。旧60/90分钟136/102根的结构/原参照/旧价及1/5新DULL结束可与r2对应，根数未额外重核，不当纯到期证据。

证据和边界见本步报告（原记录：`reports/xxm_history_lifetime_review_20261020_01/README.md`）：包含inventory、两窗口、calendar检查、旧记录核对及材料/候选。只有临时只读整理，不新增源码/测试或调用方，原产品/配置/合同/API/页面及原完成记录保持，旧43测试未重跑。当前首阶段已整理出具体候选，软件有效期结论等待既有图的柱位/事件关系证据，不宣称全量寿命分布或永久保留。

### 36.2 管理员回复与6/12新图/全文的核对（2026-10-20）

获准目标和边界见算法§12.58.2。继续复用本步m90_window_review/source_headers及现r2完成事件，当前代码结束顺序不变，不新增工具/算法入口。管理员原话分别保存“第一点，我认为是的”“第二点，可能对应的是15点那根”；绿色11:00和旧紫15:00都是带措辞的判断，不写成无条件精确标签。新6/12截图与全文是用户主动补的同组材料，不扩大研究题目。

1. 新jun12_followup_20261020/开始manifest核首阶段final_checks的81份保护及首阶段全部完成文件/原6/24图；保存新PNG与完整原稿同字节、来源路径/SHA/尺寸/字节数，并单存用户回复。原阶段README/compare/candidates/final_checks均不改。
2. 查看6/12原图，确认000001/90分钟/可见日期和末价；按末根及90分钟11:00/14:00/15:00端点逐柱定位右端黄/紫的首字，不用整词中心推日期。必要临时局部图只用于观察，原件不改。登记近似像素范围、各柱中心、映射依据和读不清处；没有游标就不称软件逐柱时刻已直接读取。
3. 原CSV新增投影仅6/12三根time/close/DIF/DEA/柱，核对象/周期/日期/时间与原字段；14/15与首阶段已有行逐值相同。用独立Decimal字面计算14相对11、15相对14的DIF变化百分比，按原0.75/1/1.2门槛作数值解释；原三比例事件仍读完成文件，不重放。分别记录如果旧紫在14/15，至6/24 11:00的条件根数23/22；不把计算反填为图片答案。软件当日末端数值对照保留差值，不平移到前两根。
4. 完整原稿按行号/原有时间码摘录：12:56附近90分钟再次钝化/结构、13:41附近二次结构、16:34附近采用与纠错语义；核是否明确14:00/15:00或旧绿色归属。4:22—6:59的120分钟参照/速度/30周期属于预计钝化消失和大小讲解，不能用作旧结构固定有效期。原转写“动画”等保持，不独立核听、不联网取稿，不把其他谈话变成本研究规则。
5. 新comparison/evidence/README/final_checks保存结果，原保护不变；首阶段待确认结果保留历史。若图/用户判断与模型时间尚不一致，明确当前差异，不改软件精确标签/参数/预期，必要时仅询问首个紫字对应末根还是前根。原方案/LLD/研究/交接追加当前停点，不触发其他寿命或门槛开发。

无产品/合同/配置/API/页面或新源码/测试变化；无DB/Lake/网络/安装/提交部署。新增源仅三行（两行复用、一行补前根），原已有94行不再全取；文件原子新增、拒绝覆盖，同身份续读只补未完成项。程序预算300秒含继续与末次核验，内存256MiB、单文件20MiB/总40MiB。验收为原件/全文/回复原话、实际字段与重复行对账、位置/讲稿/模型分层、原SHA及文档检查，不把工程核对称软件完整有效期通过。

#### 36.2.1 本步结果与剩余确认

新PNG与159行完整稿同字节保存。截图身份/末价已核，原图和未缩放局部图中紫色首个“顶”更接近14:00蓝色K线；管理员此前可能15:00的措辞保留，无游标不写精确时刻已取得，已只问现图首字。完整稿确认90分钟二次结构，不给出准确柱位或6/24绿色归属。120分钟“30周期”是按当时速度估算钝化消失，原14/0.4字面35，不能成为固定有效期参数。

三行来源与原窗口两行一致；独立Decimal核14/15的相邻DIF降幅为2.0400%/1.6183%，均超过已保存三比例；原模型14:00不改。软件末端DIF/DEA/柱与本地分别约差-0.03199/-0.03363/+0.00428，不平移到前根。依据原已核完整的窗口，14起23根、15起22根，均只作绿色在6/24 11:00且原结构映射成立时的条件结果，不据此登记软件有效期下限。

原96份模型/来源/完成记录及首阶段文件SHA保持，新原件保存与附件一致；新增比较、原文证据及核验（原记录：`reports/xxm_history_lifetime_review_20261020_01/jun12_followup_20261020/README.md`）保留待确认状态。只新增材料报告和进展，没有新调用方或产品行为变更，也未重跑原43测试。当前停点仅为图上首字位置确认，120分钟69根仍是备用候选。

### 36.3 6/24全文中22/24周期的当时核对（固定24根分支已在§36.5撤回）

目标及禁止项见原算法§12.58.4。只用临时只读文字/JSON整理，不新建研究入口、不重放状态机。输出jun24_transcript_20261020/：manifest保存6/24附件路径/字节/SHA和原96份加6/12补证文件保护；原全文逐字节保存sources/transcript_20250624_user.txt；evidence按行保留12:09—12:38、13:04—13:44、15:09—15:45及16:36—17:01上下文，并记录没有明确起算时点/软件到期行为的限制。

计数只读本步m90_window_review.json的time：6/12 14/15两起点，按严格晚于结构当根、包含目标当根数至6/23 15与6/24 11；按已核固定端点依次补6/24 14/15作为条件延伸，不声称新取实际行情。比较“若22指当天11、24指当天15”的两起点相容性；因原稿未明确22观察点、“下午”的哪根及是否计形成当根，只可登记倾向，不用它替代图片首字确认。旧绿色关联及原参照未知保持。README用日常语言分别说明直接文字、条件计数、软件规则未证及下一核对点。

新输出只增不覆盖，失败保留已完成原件，续读先验SHA；性能与读写边界沿用本步240秒/256MiB/20MiB单文件/40MiB总预算，包含中断继续及最终保护检查。验收全文同字节、159行6/12及6/24完整转写未改、两起点计数独立于内核、原SHA/文档检查。无新单元/算法测试，不把材料核验称24根自动失效已通过；无产品、配置、合同、API、前端或正式数据变化。

本步结果：156行6/24原稿同字节保存，22/24个周期与第二个90分钟结构的关联有直接文字，软件停止旧比较/删标签/绿色身份没有直接说明。若22指6/24 11、24指15，则6/12 15起更吻合；原稿未明这两个观察点或计数包含关系，不能替代6/12首字确认。原窗口到6/24 11分别23/22根，顺延当天下午14/15分别24/23与25/24根，仅条件延伸，无新行情读取。原106份SHA保护保持；补证与核验（原记录：`reports/xxm_history_lifetime_review_20261020_01/jun24_transcript_20261020/README.md`）保留图像偏14、文字条件偏15两项依据。未改产品/精确标签或重跑旧测试。

### 36.4 6/12当时的15:00确认（已由§36.6复核更正为14:00）

范围与预算见算法§12.58.6。只新增jun12_confirmation_20261020/的manifest、confirmation、README及最后核验，保护此前113份原件/报告/源码。confirmation按原问题/回复记录“最右细红色（15:00）”，以管理员明确确认替代助手此前偏14的初判；原冻结模型14和其23根记录保留，差异登记为模型早一根、原因未定位，不能为了消差调参。已有conditional_counts中15起分支22/23/24直接复核，不读新行情、不重放模型；下午两点仍沿用已核端点的计数延伸，不声称新提源。绿色11:00的初步判断和实际旧结构关联未知保持。

原完成记录不覆盖，新输出原子新增；中断核SHA后只补缺失文件，预算含继续/末次120秒、256MiB、20MiB单文件/40MiB总量。验收为确认措辞、图上位置结论更新、软件/模型一根差异、已核计数、原保护与文档检查。无产品/合同/配置/API/前端、软件52标签或正式数据修改，旧43测试不重跑；不再等待或重复询问这处首字。

本步结果：管理员确认首字在15:00，先前偏14的图像初判已更正，首字问题关闭。confirmation保存原话及精确图位、模型14早一根的差异、已核22/23/24计数和仍未知的绿色关联/自动到期；旧报告及113份保护保持，无新数据读取、模型重跑或参数修改。确认与最后核验（原记录：`reports/xxm_history_lifetime_review_20261020_01/jun12_confirmation_20261020/README.md`）只证明材料更新，不是差异根因或24根公式验收。

### 36.5 讲稿24只作本例对应数字，不衍生固定到期条件（2026-10-20）

管理员澄清24不是某种条件必走的周期数，本研究按当时行情的具体前后对应关系理解。撤回§36.3等此前文字由本稿延伸的固定24根到期研究分支，不将其列作软件待验证公式，不为此索图或改参数。既有计数、6/12软件15:00确认、原模型早一根和其他独立未决事项保留。

本步仅原研究文档的解释更正，无新实现步骤、配置、合同、调用方或实验。原截图/全文/完成记录不反写，旧报告中的该延伸以更正说明（原记录：`reports/xxm_history_lifetime_review_20261020_01/interpretation_clarification_20261020.md`）为准；文档检查不宣称软件公式验收。

### 36.6 管理员再次复看采用14:00，撤回模型早一根（2026-10-20）

本步是材料时间更正，范围见算法§12.58.8。保存“按照14点”“结字是从14点开始的”原话，当前图位采用14:00，取代§36.4此前15:00确认；原冻结模型同为14:00，不再登记或追查模型早一根。复用原窗口和端点，至6/24 11/14/15为23/24/25根；不强行用讲稿22/24反推时点，通用24根期限分支不恢复。

只新增[更正说明](../../../../reports/xxm/conclusions/xxm_history_lifetime_review_20261020_01/jun12_time_correction_20261020.md)并同步原文档，旧报告/原件/冻结结果不覆盖。无新实现、数据提取、模型重跑、参数/合同/API或页面修改；文档检查不代替软件参照或绿色关联验证。

## 37 已确认新案例的自动回归（2026-10-20，本步获准）

### 37.1 当前实现依据与范围

目标/禁止项见算法§12.59。CodeGraph explore已追到history_disappearance_screen.load_bars、read_unit、assert_expected_recognition及相关读取/测试关系；当前产品step中原DIF/新同向信号先结束旧TOP记录，底部在_advance_bottom_history中推进。原frozen_mode/expected_steps负责旧封存全状态及1215预测，现有筛图程序负责候选，不直接覆盖本轮新增材料的独立断言。最小改动仅新增test_xxm_confirmed_cases.py，复用既有pytest、load_bars和产品XxmCalculator，不新增runner/CLI、计算器、配置或生产调用方。

### 37.2 真实来源与独立预期

读取load_bars当前实现：day使用daily_2020_source_01/daily_source.csv、manifest和calendar，字段trade_date/close/macd_dif_bfq/macd_dea_bfq/macd_bfq；分钟使用xxm_source_audit_20261013_213852的90/120 CSV及manifest，字段trade_time/close/macd_dif/macd_dea/macd。原reader核000001.SH、行数、唯一顺序、完成端点及日历；本步不另写宽松reader。源CSV还绑定已知SHA：日线8b0f62ff…、90分钟9b169049…、120分钟dcaf1206…。旧前缀是预先计算的MACD输入，不是用本步模型生成的expected。

独立断言逐项映射：

| 依据 | 输入与代码落点 | 正向及反向验收 |
| --- | --- | --- |
| 3/11原图、transcript_update/evidence的用户确认及README逐柱表 | m120推进至3/11 15:00，保留3/6 15:00起相关step | 3/6结构的关联旧记录在3/11 11:30产生TOP历史消失；当根close3052.2827>旧价3051.3457，DIF低于前根；15:00不再次产生该旧绿色，不追加DIF回升前提 |
| 4/14补图、4/18图及用户无字确认；事前旧价/事件链 | day推进至4/21，保留3/7起step | 3/7结构旧价3328.3927，4/14新TOP DULL结束该记录；4/17虽close3385.6095且DIF22.553<41.186，4/17—18不输出关联旧id绿色；4/21正常产生新结构，防止一律阻止后续变化 |
| jun12_time_correction_20261020原话及6/12图 | m90推进至6/12 15:00，保留当日step | 14:00产生TOP结构并登记历史，15:00不重复产生TOP结构；预期不是旧15:00确认或讲稿22/24推算 |

同一案例的内部history id关联、锁定值及结束原因是现产品工作规则的回归，不称软件内部实际参照已读取。4月静态无字仅支持本例，不写全方向永久结论。6/24绿色归属、软件精确历史DIF、通用有效期和持仓规则均不写断言。

### 37.3 测试实现、输出与失败规则

测试使用模块级fixture，三个周期各读一次原冻结输入、从既有来源起点推进至必要终点，只保留相关窗口steps/bars，不在测试中创建expected快照或调用研究候选类。测试文件列明独立证据路径/SHA与限制，源/证据SHA检查和明确事件时间是不同断言；无skip/默认值/网络替身。原52/原全状态预期不修改，旧任意软件未知不补成金样本。

新报告目录记录开工文件身份、实际前缀行数、测试命令和日志、产品/原预期保护及最后核验。既有内核回归限test_xxm_calculator.py，若需要增加测试或实现范围先同步本节；不重跑预测1215/正式API或已完成全筛图。日志及XML从临时文件完成后改名，失败日志原样保留，不覆盖已有完成批次；同身份继续只重跑失败/未完成项。若真实观察与当前代码冲突，保留差异并停在该案例，不改产品或expected。

性能/配置边界沿算法§12.59：最多23218行读取、仅三必要前缀计算，300秒包含继续和末次；256MiB、20MiB单文件/40MiB总输出，无新增运行配置。完成条件为三案例明确断言及正常变化通过、源/证据/原保护保持、相关既有内核回归和文档检查。只声称本次冻结输入下的案例回归通过，实际页面、远端网络/登录/部署及通用公式仍分别验收。

### 37.4 本步执行结果

新13项/原68项均通过，实际命令/日志/资源及源证据见阶段报告（原记录：`reports/xxm_confirmed_case_regression_20261020_01/README.md`）。正向事件、下午不重复绿色、4/17—18无关联旧绿、6/12不延到15、4/21正常新结构均有明确断言；源和图片/确认10个SHA单独检查。案例输入共读23218行，推进20155根，只留43个案例step，原144份保护保持。无模型expected生成、旧标签更新、源码/参数/API/配置或正式数据变化；300秒/256MiB/40MiB预算内，无中断重试。自动回归的工程通过不替代软件内部参照或实际页面验收。

## 38 四周期实际页面阶段验收（2026-10-20，本步获准）

### 38.1 范围、当前代码与读写边界

依据算法§12.60，接续管理员批准的三步顺序。已通过的13新/68旧回归不重复运行。当前页IndexDetailPage以tradeDate查询历史，技术面才启用useXxmForecast；识别图层由useIndexXxmLayer→apiClient→adapter→XxmMacdPrimitive消费，预测由useXxmForecast→apiClient→XxmForecastCard消费display。共享indexDetailRequestScheduler按既定队列限制请求。当前分钟仍DEV，后端forecast路由按分钟能力拒绝未开放环境，本步不修改这些条件。

复用现有Chrome本地页，CUA原生/Playwright只操作可见UI，CDP只观察同源请求、读取已发生的XXM响应和进行局部失败试验。请求只为000001.SH、四周期及固定日期；正式数据仍经现有只读API读取，不绕过页面直接重算/扫库。不保存Cookie/token/请求头，无生产写入/安装/重启/部署。

### 38.2 逐项场景和独立对照

| 场景 | 操作与证据 | 验收 |
| --- | --- | --- |
| 当前日线/60/90/120 | 依次点周期，打开技术面；保存可见文字、截图及对应已完成API响应 | 图层代码/周期/起止时间、版本/sourceInputId与图表数据相符；四条预测显示等于各自响应display，非同一周期复制 |
| 2025/6/12 m90 | 按tradeDate进入，切90分，检查末端MACD及结构附近 | 14:00结构标记/悬停与已确认事件及真实响应对应，不能按整词中心认时刻；画布截图与悬停分别记录 |
| 2024/3/11 m120 | 历史日期/120分，查看最后两根 | 旧绿在上午11:30，与响应time/类型/关联一致；不拿15:00顶栏当上午 |
| 2023/4/18 day | 日线历史页及末端 | 新黄与旧结构可区分，4/17—18不出现关联该旧记录的新绿；不声称软件历史内部状态 |
| 切换/刷新/失败恢复 | 四周期切换和一次刷新；本标签XXM路径临时阻断后触发加载/重试，随后恢复 | 无旧周期/日期残留、失败明示，重试成功后恢复；临时阻断已清除 |

使用实际同源Network响应作为页面消费对照，先核responseURL参数与computedThrough/period/版本/sourceInputId再比display或标记，不能用另一时点/旧源的相近值代替。页面指标数值/画布/悬停分别观察。当前页已有非XXM数据缺失提示单列，不把所有页面问题混成识别缺陷。发现冲突保存双方，定位当前producer/consumer后补本节修复设计，不迎合截图改源值。

### 38.3 执行、限制及保存

开始建新报告目录与源码身份。CUA截图和DOM/文字、过滤后的同源XXM响应逐项保存，不记录其他标签数据；每动作后读状态，先核已存在服务，不启动备用服务或换接口。单标签验完后按需用第二标签核切换独立性，不将普通两标签观察称专项负载验收。前端沿现node_modules运行typecheck、XXM/预测/请求队列相关测试和build；如果缺依赖只报告，不安装。

错误试验可在CDP设置本标签同源xxm-signals/xxm-key-point-forecast临时阻断，事后必须清空并确认正常请求恢复，不持久改页面/网络。原用户标签最终恢复原URL/周期/页签；临时新标签关闭，证据文件保留。检查失败/中断保存已完成记录，按同身份只补缺失项；新文件不覆盖旧完成记录，截图/响应先临时文件再完成改名。范围/请求/时限/文件预算按算法§12.60，包含重做未完成项及最后核验。

本步没有预定UI代码或API合同改动。只有发现真实缺陷且完成根因/影响面/具体测试设计后才修，禁止为通过验收隐藏错误或增加新功能。最终分别报告可见页面、接口消费、前端检查、错误恢复、未覆盖边界；本地浏览器通过不能替代远端网络/登录/发布或Figma/原型清退。


### 38.4 提示遮挡的具体修复设计（编码前）

实际partial提示被IndexInfoRail放在tabpanel外，index-detail-page.css的absolute/bottom:302px使其与正文叠放，挡住预测条件；复用IndexDetailPartialNotice即可解决，不需要另建组件或改pagePhase。修改仅IndexInfoRail.tsx、index-detail-page.css与既有IndexDetailPage.test.tsx：将partial/delayed条件渲染整体移到tabpanel第一个位置；notice删除position/bottom/left/right/z-index，增加margin-bottom:var(--cs-space-10)，其余外观/内容原样。原指数方案§7.5与LLD同步本次不遮挡约束。

编码门禁：CodeGraph已核IndexDetailPage→IndexInfoRail→IndexDetailPartialNotice，当前源码/CSS/测试已读；没有跨子系统依赖或API/DTO变更。通用清单2.1/2.5/2.6/2.12/2.17及原则8由本节、先失败后通过的Partial/Delayed页签断言、真实API驱动截图和几何核验承担；2.2/2.3/2.4/2.8保持当前字段/状态/颜色，不新增语义；2.7/2.9—2.11/2.13—2.16及原则3/5/6/7无数据源切换、图轴、排序、配置、查询或异常码变更，沿用原矩阵，不新增例外。原则1/2/4仍仅消费原状态和文案，Ready无提示有反例断言。核心实际验收为partial notice的文案/tabpanel归属、position=static、与正文矩形不相交及四条预测display；Delayed无现成实际源时仅声称自动测试覆盖。预算/中断/继续及保存沿§38.3和算法§12.60，不写数据库/Lake，不改算法/合同。


### 38.5 本步结果

本地四周期及三历史场景、刷新/阻断/局部重试完成，8行预测的四个display字段逐项相同；10份识别响应4000点与对应行情/指标0差异，含重复加载。提示修复前2项失败，修复后完整1191项、类型、构建通过；真实partial普通占位且正文间隔10px，截图与数值见报告（原记录：`reports/xxm_page_acceptance_20261020_01/README.md`）。52源/144旧保护SHA保持；仅3个UI/测试文件变化，无新组件、API/配置或算法变更。调试初始缓冲/非目标日线body缺失使完整冷启动统计不充分；Delayed没有实际源状态，远端/登录/发布/Figma/原型与专项负载不在通过范围。临时阻断清空、标签关闭、原标签恢复，未提交部署。

## 39 120分钟长间隔案例取证准备（2026-10-20）

沿算法§12.61，只读既有报告m120_window_review.json/material_review.json及其已核SHA；不再重放或访问数据库/Lake。保存候选日期、70行窗口/69根计数、旧结构/新绿色均为模型推算的区分，准备单张软件图请求及不充分证据的处理条件。原记录字段confirmedAt/structureAt/relatedTopHistoryId/priceAnchor/originalReference语义沿当前内核和已完成窗口审查，不用本次说明生成自动测试expected。软件确认前不修改52标签、内核、参数、预测或消费者。

验收为取证说明明确标的/周期/两个时点、已有材料缺口、需要看哪几个字及可能结果；原件/旧结果不覆盖。范围最多读取上述两个小JSON及对应SHA，输出1MiB、总60秒含继续/末次核验，无新运行配置。旧紫和绿同屏仍须核中间新同向信号/原参照，绿色缺席不能直接证明到期。没有实际新图则停在待材料，不能将准备完成写成寿命公式已验证。


### 39.1 替代取证与未证边界（2026-10-20）

管理员未找到1/6上证120分钟图，停止该项重复索取，原69根case仍AWAITING_SOFTWARE_IMAGE且不覆盖历史请求记录。依算法§12.61.1，复用日线已提供图；新增候选优先2024/1/16 m90，1/11 14:00结构至1/16 14:00消失9根；备用2023/3/1 m120，2/23 15:00结构至3/1 11:30消失7根。候选来自已有完成记录，原SHA已核，尚非软件标签；只核对现有输出，不访问正式源或执行内核。短案例、其他周期或不明周期讲稿不能替代长保留证明；模型保持现状，无代码/配置/合同变更。既有小文件/只读边界继续适用，当前只调整取材顺序。

## 40 两份讲稿及2023/3/1新图核对（2026-10-20）

依据算法§12.62及管理员本次材料。当前案例/事件的producer仍为唯一r2，复用已封存m120_1.0事件、m90候选、日线recognition_ledger及原minute_120_source.csv，不运行XxmCalculator/预测或接口。只核新材料与原事前结果，产品不读取本次报告，没有新增调用方/配置或依赖。

先归档两稿与PNG，manifest绑定SHA及原附件路径。提取原稿行号/视频时间和短原文，分别记对象/周期是否明确及ASR歧义；主题提到日线的内容不绑定为90分钟1/16绿。日线ledger仅1/8—18窗口；m120只2/01—3/1源字段时间/close/macd_dif/macd_dea/macd，核ts_code/freq/params/indicator_version，事件仅2/01—3/1及其原参照；优先复用事前结果，禁止用新算法生成expected或替软件补字。新图顶栏可能随游标，若无法绑定末根则该数值比较只保留条件性。

圈内字不可辨处已请管理员确认；文字缺席与模型事件冲突只记录，不能据静态没有字直接改内核/删旧预期。核对后若新差异成立，先区分首次钝化/结构时间、绿色关联及输入精度，再写下一步根因方案；本步不编码。读写/预算/中断与三材料验收沿算法§12.62，300秒包含补缺及末次，128MiB/20MiB输出，无正式读写或新运行配置。


### 40.1 本步结果与停点

见两稿及新图报告（原记录：`reports/xxm_alternative_evidence_20261020_01/README.md`）：两稿支持日线1/16结构后1/17重新钝化的口述解释，不能确认未命名的1/16 m90历史绿色，未将钝化消失与旧结构消失混同。ASR原件/行号/时间/解释单列；1/18一天半属于行情条件估计，不推固定寿命。

m120原42行/8事件显示两条不同旧结构：2/16→2/21，及候选2/23→3/1，不能将圈左绿色配给后者。新图右圈未辨认到候选新标记，已问管理员确认，当前UNRESOLVED_VISIBLE_DIFFERENCE_NOT_PASS。末根数值条件比较小差保留，不证明全输入/实际参照同一。9日线point/4事件与19份源SHA检查完成，无新step/预测/产品合同或旧预期变化；没有为新图增加通过测试。确认后若差异成立，另按最早差异做根因方案再行动，本步不编码。

### 40.2 圈内无字已确认，模型来源审计范围

管理员确认圈内没有这些文字。只更新新观察状态，原40.1及初核报告留历史。沿算法§12.62.2，CodeGraph追当前TOP activation/choose_reference及历史结束，使用已摘取源和原事件，核2/22为什么出现新TOP DULL及后续结构/旧绿依赖；当前实现事实与软件未知分别列出。不从缺字擅设最小段长/新高/同段次数/期限等规则，不改内核/配置/合同或测试expected。最多两次8文件、120秒/128MiB/2MiB补充输出，无正式读取/新step。可见字确认不等同软件内部状态确认，若无足够证据则停在差异及需区分原因，不继续编码。

2026-10-20后续确认：管理员明确“圈内没有这些文字”。确认及模型来源核对（原记录：`reports/xxm_alternative_evidence_20261020_01/confirmation_20261020/README.md`）接续原待确认状态，不记命中。CodeGraph/current Spec表明2/22新DULL使用2/21的段内高收3306.524，超过最近段3305.854；当根3298.13低于最近段高点，但当前资格没有这一项要求，选中更早2/1—2/2参照31.4063505后产生新DULL，后续2/23结构及3/1绿依赖这轮。当前只确定模型来源和圈内缺字，尚未证明软件应采用当根破近高、其他参照或不同显示；下一步应先区分这轮新钝化资格/比较对象，不先归因期限或只修绿色。无新重放、规则选择、产品/旧预期或软件标签变化。

## 41 同一天90/120分钟末端对照（2026-10-20）

沿算法§12.63，保存新90分钟PNG及管理员“最右有钝化”原话；复用m90_1.0冻结事件和90源2/01—3/1最多80行，再与上一份120分钟42行/事件对照。先核实际周期、当天末端/游标归属和读数，标记位置以图证/管理员为准，不以模型产生标签。当前XxmCalculator.step的首次TOP激活以min_bars=2和DIF>0等原条件处理；代码SHA应保持。只说明现存模型末端为何可有差别，不加入新例外、周期特判或日期特判。

核验字段为time/close/DIF/DEA/柱色、当段开始及根数、最近同色段高点、eventReference及事件time/type；日终状态只复用已完成证据，不新增模型step或预测。90末端黄保留为后续研究对照，不能因此把120的缺字记通过。源/原件/旧报告及产品保护、失败/中断/补缺与预算沿§12.63，纯报告无消费者/配置/合同变化；软件精确时点/参照未确认继续标未知。原稿尚未到，不调外网查稿或重复索图。


### 41.1 新图结果及进一步区分点

原模型3/1 15:00新TOP DULL与新90图最右钝化相容，仅确认当天末端存在；精确首字柱位仍未独立定。63行/10事件及20保护SHA保持，末端三红对120一红与现行min_bars=2相容，不据此证明软件门槛。最右读数DIF/DEA/柱小差单列，不平移到历史。无代码/配置/合同/预测或新step，未增加模型expected。

已询大红圈内绿字右侧黄字是否对2/21 14或15，日期可纠正。原模型14发黄时当根3294.037未过近高3304.952，但段高3305.988已过；15当根3306.524才过。若软件也14黄，将反对前一步当根破近高猜想，须保留输入/柱位依据；若15仍只是相容。当前只保存事前两种判定，不等待答案自行选新公式，也不把90相容替120差异消账。本步报告（原记录：`reports/xxm_same_day_m90_m120_20230301_20261020_01/README.md`）。

## 42 近似确认及红柱缩短条件核对（2026-10-20）

沿算法§12.64，不把管理员“更像14:00、也看不清”变成精确标签；“印象里红柱开始下降第一根”保留为用户提供的待核解释。当前calculator.step 92—98首次TOP激活及161—171参照选择没有hist下降检查，75—89的DIF转折另管结构/重新钝化；当前Spec/产品SHA应保持。只用已存63/42行及原事件做严格正柱相邻缩短的字面核对，解释现实现，不执行修改版或生成新expected。

按2/21起及3/1起两段分别列前后hist、DIF与现黄/紫事件；3/1已确认90末端黄必须作为检验记忆的现有约束。源末端DIF/DEA/柱小差及实际软件此前读数未知保留；本地不满足不直接断言用户记忆错误或软件公式错误。读写/中断/继续/验收与预算见§12.64，无正式数据或配置/消费者变更，不实施新条件。


### 42.1 本步结果

近似答复保留不精确，规则记忆不升级合同。当前首次TOP无hist递减检查；只对现存63+42行作相邻正柱比较：90原黄2/21 14、首次缩2/22 14；120原黄2/22 11:30、首次缩2/22 15且DIF仍升。3/1 90已确认末端黄对应本地三柱逐增，对无前提增加首次缩柱必要条件构成约束；不把本地差异直接当原软件公式已证错误。原软件前根/参照未知、小差及位置不精确保持，原稿未到不推内容。报告见补充（原记录：`reports/xxm_same_day_m90_m120_20230301_20261020_01/feb21_followup_20261020/README.md`），无新step/预测/源码/参数或测试预期变更。

## 43 2/21三周期图文证据整理（2026-10-20）

沿算法§12.65。原件为本次三PNG和转录全文；日期按管理员说明及稿件题目确认，截图顶部日期裁切不冒充可读日期。保存原件路径、尺寸、SHA及管理员原话，逐项区分截图可见、转录解释、条件预计与事前模型事件。引用01:15/02:32段时保留转录原文；影响比较对象的词待核听，不能擅自纠正后选择参照公式。

当前calculator首次TOP激活在step的段根数/段高及DIF条件中，历史消失另按原记录判断；本步仅读，不修改实现/调用方/配置。三个周期只截事前frozen_08_memory事件2/13—22；90/120数值仅用已存窗口2/20—22，不新增源读取或内核运行。不以软件2/21末端一致宣称精确时点、关联结构和完整历史均通过；2/22新黄仍是模型与条件预计，未取得次日软件实证。

读写边界、预算、失败/继续规则与验收沿§12.65；保护三个冻结输出、当前产品与原两个窗口，新增文件只写新报告目录，完成后核SHA/原件字节/文档链接。整理结果同步本节和原方案，不改旧报告与旧预期；未核清的关键原词继续待管理员答复。

### 43.1 本步结果

四原件保存同字节，截17旧事件及15既有数值行，19输入/源码SHA保持。2/21三个周期当天情况由新图文支持，具体首字时间与关联旧结构仍不提升为确认。120只有一根红柱所以未新黄，支持现行两根门槛与本例相容；次日上午为条件预计，非2/22软件已出现新黄。最新结构计时不证明删除旧参照，不新增缩柱或固定有效期规则。

比较旧峰的原词及中间无红柱的原词已请管理员核听，未返保留未知。日线价格足够不搬到分钟线；“只需时间”也不证明实际下跌后的价格资格。后续先核旧峰比较和历史文字保留，再判断原2/22—3/1新黄/紫/绿差异，不由后来缺字直接推定此前未发生。核对材料（原记录：`reports/xxm_feb21_three_period_evidence_20261020_01/README.md`）接续旧待稿状态；产品/参数/合同/旧预期不变，无新内核运行或正式数据访问。

## 44 邻峰原词确认及旧参照核对（2026-10-20）

沿算法§12.66，原始答复全文另存，只将临风解释更新为邻峰、红角线与红柱线同义；不改原转录/旧完成报告。管理员画图指向1/30附近仍是大致日期，未指定精确DIF值，也不把一次指向自动绑定全部周期。参照先读取原2/21三个周期和2/22 m120事件的eventReference，分别记生成时间/区间/DIF；参考值是模型已有记录，不能冒充软件已量定峰值。

当前step在柱色变化后只保留最近max_refs个同色段，_select_eligible_reference先检查最近段价格，再按候选DIF选择，故需区分邻峰原意与当前程序段划分。最多96行三CSV的1/20—31投影，只核原参照峰日期；2月中间正柱资料复用已有120窗口和正柱段记录、已有90窗口2/1—8的18行，若与图上无红柱的解释不同，只记输入/分段待核，不先断言软件错或修改实现。字段身份/保护/失败续跑/预算沿§12.66，本步不新增配置/合同/调用方，不重放内核或更改测试预期。

### 44.1 本步结果

管理员原词及1/30附近指向已记录，红角线不是该处转录错误。原三周期2/21事件参照DIF匹配本地1/30，27行/35保护保持；准确时分仍只是本地来源，120为旧历史消失的参照。2/22模型新120钝化参照2/1—2/2，因本地另有2/14—2/16正柱段、当前max_refs=2，1/30旧段已退出新候选，但旧历史记录仍保存原参照。

90图及其本地2/1—8的18根无红柱与讲稿相容，90当前旧峰选择无此项冲突；120另有小红柱，不能搬用90解释。中间无红柱所指区间未被精确确认，不自动判定本地哪个正柱段应删除或合并；尚不能用此解释3/1缺字，也没有运行替换参照的新模型。后续核实际中间区间、来源/分段与参照选择，保留2/22只是条件预计、90首字模糊和软件完整输入未知。本步结果（原记录：`reports/xxm_feb21_three_period_evidence_20261020_01/neighbor_confirmation_20261020/README.md`）接续原词待确认状态；产品/参数/消费者/测试预期不变。

## 45 120分钟红柱分段和参照选择的只读核查（2026-10-20）

沿算法§12.67及管理员继续核查授权。真实来源为已封存CSV合同ts_code/freq/trade_date/trade_time/close/macd_dif/macd_dea/macd/params_key/indicator_version/observation_count，时间不截为日期；仅指定窗口投影，核SSE开市日期和11:30/15:00两根，使用十进制核指标恒等式及严格正负。观察每次柱色改变的前后行，把代码何时append旧段、截去第三段写成可人工核对的时间表，开头截断段如存在必须标明，不以残段新跑信号。

正柱段保存当前代码使用的最高收盘和最高DIF及各自发生时间；与1/30原参照和已存120正柱段核一致。2/22逐项列当前段根数/当根DIF、截至当时段高、最近段高、两候选最高DIF/价格；先核最近价格前置，再核候选资格和最高DIF顺序，不使用2/23后值。只对照已有冻结事件，不执行XxmCalculator或用自身结果生成预期，也不以参照切换自动解释3/1缺字。

图片复核仅使用已提供2/21/3/1的120分钟图，日期/周期/中间三根位置难辨时请管理员确认；不把90讲稿的无红柱搬作120软件数值。输入/完成记录/源码保护、失败续读、预算、输出与验收沿§12.67；产品/API/前端及依赖方向无变化，本步不新增配置或测试。

### 45.1 本步核查结果

72行/36开市日无缺重，MACD恒等式差至多6e−15。当前严格符号分段下，2/1上午负柱−0.437864隔开前后红柱，随后三正柱独立成段；2/3上午入最近两段，2/16下午下一红柱段完成才将1/30所在旧段挤出。保留过程起初更早历史未知，连续两段完成后最近两段已确定；未从空历史运行内核或把说明当完整恢复。

2/16黄/紫及2/21历史消失锁定原参照另存，2/22是新一轮重新选择；段高/近高余量0.670，两候选都合格，DIF31.406351较16.076542高而被选。与原事前eventReference的区间/价格/DIF及结构关联核一致，不使用2/22下午/之后值。程序选择理由已查清，软件是否同分段/同保留未证，短负柱已请管理员核现有图，偏蓝颜色已澄清。完整核对（原记录：`reports/xxm_m120_reference_trace_20261020_01/README.md`）保存43保护和证据；无模型/产品/参数/配置/消费者变化，原3/1差异未消账。

### 45.2 软件短负柱已确认，内部规则仍未证

管理员答“能看见一根短绿柱隔开”，结束柱色待确认；图中偏蓝负柱与本地变化相容。此前“决定软件单独算段”的问题措辞撤回，图证只确认柱色，不证明软件采用当前单根异色分段、两段范围或最高DIF。无需重复索图或追问本柱，下一项转向分段/选峰规则、价格及文字保留差异。原话与边界（原记录：`reports/xxm_m120_reference_trace_20261020_01/image_confirmation_20261020/README.md`）接续父报告，不改原完成记录/模型/参数/合同/测试预期；3/1缺字仍未解决。

## 46 短负柱的算法假说与单项原因核查（2026-10-20）

沿算法§12.68，新增120画线原图先同字节归档，日期由管理员说明及同场景2/21图文确认，图顶日期裁切不冒充可读日期。读当前CodeGraph step/参照选择，输入来自既存有界JSON而非正式源；120最多100行、90最多80行，投影trade_time/close/macd_dif/macd_dea/macd/params/version，逐重叠字段一致才去重。旧比较报告保留旧候选/旧来源/置信限制，只作为原有约束，不声称本轮已重跑全部52项。

假说分开列红绿分段与保留/选参照、以及结构记录是否沿用原峰；提出沿用时必须核原峰被突破如何结束，不能新增永久参照兜底。忽略单根负柱仅可用于已发生历史的比较范围假说，完整实时判断需另定义因果时序。只替换2/22新钝化的原参照时，2/21以前已确认状态/分段及当前DIF转向1%保持，逐时刻代入三旧峰；表中结果是固定其他条件的反事实，不当作软件真实标签或完整合并候选测试。

具体核2/22黄、2/23紫与3/1绿的分支依赖：原参照DIF阈值、当时段高、后续DIF最大值、新同向信号与历史价格突破，不能仅比较参照日期就断言标记改变。读取/写入/续跑/预算/保护及验收沿§12.68。产品/API/页面/配置/合同/消费者不变；假说待证，不修改实现或测试预期。

首次TOP当根价格的既有猜想另作单项表：逐根取当前段已到达最高收盘/DIF、最近两个已结束同色段及现有资格，比较新增bar.close同时大于最近段价和候选价。只列五段的最早资格时刻/没有合格根，不把首次资格表冒充完整识别结果，也不影响已激活后结构或历史绿的规则。范围沿原有界82/72行，无新来源或门槛拟合；是否值得开发需保留旧52标签及其他消费者验收，不能仅凭本例采用。

### 46.1 本步结果与未证范围

120新图和管理员答复确认讲解亦指1/30附近；日期依用户上下文，精确程序参照/2/22新黄未直接取得。82/72行去重及32重叠相同。三参照限定代入均在2/22够格，后续最大DIF低于三个参照，转向/本段高收/3/1突破一致；只换峰不会消掉当前链。沿用原峰假说需定义何时结束，合并单根负柱需定义当时可知时序，均未运行完整候选。

五段逐根资格表增加当根收盘过近高/参照价格后，120 2/21起一段无首次资格，其他120两段和90 3/1首次资格时点保持；90 2/21改为15而非14，旧软件位置模糊不记匹配。它是后续候选方向，未作全局/旧52回归，不声明端到端通过。旧六组合与3/11等原证据保持置信限制，不因新猜想改旧预期。见假说及限定核算（原记录：`reports/xxm_short_negative_bar_hypotheses_20261020_01/README.md`），产品/参数/配置/合同/消费者不变。

## 47 当根价格猜想的旧标记只读审计（2026-10-20）

沿算法§12.68.2—12.69，先更正因果描述：已有负柱后实际再次出现正柱，才有前后分段的研究对象，不是负柱让正柱出现。更正另存并接续原完成报告，不改原件或完成校验。

真实标签生产者为top_daily_ambiguity/run_01/observations.json，当前分类依据为r2 frozen_m120_1.0、frozen_m90_1.0及daily_2020_01/recognition_ledger的已存事件，仅读不执行calc。按事件type/direction/route映射10条首次TOP，其他DULL分支单独列明；不按文件名或见黄字就当首次。分钟输入按原CSV合同核身份；日线用同一当前producer已存points的time/close/dif/dea/hist，保留实际三位指标值，避免另读原数值时改变日线精度。

每例窗口起点为原参照startTime−14天，至事件当根，独立检查符号变化、最近正柱段闭合时刻及段内最高收盘；保留原参照和本根收盘，算两个严格大于条件。只评价当根是否被新增条件排除，不能据此推导新状态机后续一定相同，direct/mapped分开计数。source近高不能按当前选中参照价格反推，必须从真实窗口最近已完成正柱段取得；相关段越过窗口起点则该例停止，不把截断极值当完整。

保护、预算/失败续跑与验收沿§12.69。产品/API/前端/配置/合同/依赖方向无变化，不新增维护脚本或候选内核。CodeGraph已核当前首次激活/参照选择及标签读取生产者；旧标签与原报告不因本步结果更改。

### 47.1 本步结果

旧52及direct/mapped原样保留。15个DULL中10 TOP activation纳入，4 dif_return/1 BOTTOM明确不适用；10当根价均过实际最近完成正柱段高及原参照价，1 direct/9 mapped，未发现当根条件反例。该结论不覆盖新状态机此前/后续变化、原52完整回归或软件公式确认。

494个来源行经有界窗口投影，各例近段无左截断、日历/时点无缺重；76输入/旧报告/源码保持。因果表述按管理员意见更正为行情驱动指标、仅研究已有柱色序列如何分段，不暗示绿柱导致红柱。记录及结果（原记录：`reports/xxm_current_close_old_case_audit_20261020_01/README.md`）接续原报告；无产品/参数/合同/配置/消费者或测试预期修改。

## 48 首次顶部当根价格的完整研究候选（2026-10-20，编码前）

对应算法§12.70，管理员批准仅研究。目标、输入范围、预算、失败和验收以该节为准，不改变产品合同。CodeGraph已读取XxmCalculator.step、_select_eligible_reference、snapshot及研究入口关系；同名audit/step返回的其他业务无关，不据它扩大修改。实际源码核实首次TOP只在step的activation调用selector，底部参照修正也调用selector但sign=-1，因此研究过滤必须显式只处理sign=1；dif_return不会经过此处。

新增TopCurrentCloseCalculator，step在原验证及顺序检查通过后保存当前bar，再调用super.step；selector先调用super取得原选参照，sign=-1或无候选直接原样返回，sign=1仅在当前close同时严格过history[-1].price与selected.price时保留。失败不换峰、不写伪造事件；后续原step继续执行。临时当前bar不进入持久状态，恢复后下一次step重新赋值。工厂为基线与候选生成不同source_identity，候选恢复先要求本候选身份前缀，再调用原restore；产品恢复也按原sourceIdentity拒绝研究状态。spec不新增开关/配置；研究条件固定、报告记录说明与代码SHA，CLI仅接收新报告目录。

输入复用history_disappearance_screen.load_bars，真实生产者为既有日线/分钟CSV与manifest，字段和日线原精度不重算、不改列。基线与候选各从空状态读取完整封存前缀，基线事件与现r2 frozen_08_memory分钟账本及daily_2020_02_memory日线账本逐字段相等（日线含points）；不将候选假设反写为金样本。旧52直接读top_daily_ambiguity_20261017_01/run_01/observations.json，若缺period/endpoint仅按原case与日期格式映射，不移动时间。direct/mapped分开输出，新观察证据路径与可见范围另存。

每周期保存两组完整事件及差异；指定窗口保留bar、point、event、wave、history、pending和首次选择诊断，覆盖2023/2/1—3/1与2024/3/6—11、2023/4/14—18、2025/6/12—24。所有已知确认与未知边界分别列出，尤其2/21 90分钟14/15不能评分。保持wave/history、全部底部事件/历史/重新等待记录相同的逐根断言；顶部不同允许后续状态自然变化。保存截点后独立重跑前缀，与原截点snapshot相等，再比较恢复后3根的完整step；禁止读未来值构造当前判定。

测试落scripts/research/index_market/tests/test_xxm_top_current_close.py；人工输入由XxmBar真实合同及可手算的旧高/峰构造，错误与正常变化均测试，expected不调用候选生成。真实冻结源完整运行是输入接入证据，纯人工单测不冒充真实验证。原13新案例与68项旧核心回归按已有入口运行一次，仅证明产品保持；候选的52项及新确认对照另列，不将程序通过混成软件还原。研究报告完成后才判断是否值得下一阶段产品设计。

### 48.1 执行结果与产品边界

实现为top_current_close.py与test_xxm_top_current_close.py，原产品及旧实验未改。40478条四周期从原始起点运行；基线事件等于r2完整账本，日线精度/points相等。候选52/52保留，10项新观察按原确认范围相容；wave/history及全部底部输出逐根相等，前缀/恢复相等。88项隔离回归通过（7本研究/13既有新例/68旧核心）；产品/API/页面/预测未实施或重验。

1.33秒完整实验、约5.6MB主输出、80保护保持，见本轮报告（原记录：`reports/xxm_top_current_close_20261020_01/README.md`）。689根差异待软件资料判断。2023/5/9—10日线是下一项反证点，候选不产生原程序黄/紫，尚无软件实际有无，不因原52保持而迁产品。2/21 90分钟模糊时刻、6/24绿色关联及1%软件门槛保持未证。CodeGraph已核step/selector/snapshot和研究调用关系，同名其他模块不在范围。

## 49 5月9日新材料与当根价格候选核对（2026-10-20）

沿算法§12.71，仅证据与文档。归档新原图、转录研究段原文（不是全文）及管理员“没有钝化”答复；标记日线日期/末端缺黄确认，与截图时刻未答分别保存。完整旧run/summary/interpretation/complete和final_checks原样保护，不把新证据补写到旧完成结果。只保存新目录的独立结论。

日线三点由现r2 daily_2020_02_memory/recognition_ledger.points按time投影5/5、5/8、5/9，补一负柱只为核首/次红柱，原已完成两点投影不覆盖；两组逐根结果由top_current_close完成day.json的5/9差异及5/8—10事件读取。2月重复模式仅读已完成m120.json的2/21—22窗口wave.count，不增来源。原图数字人工记录、精度/未核字符明确，不用于重算输入。分钟流式投影旧CSV的5/8—9共10行，核对象/freq/参数/版本及来源SHA，保留close/DIF/DEA/hist。已存m90/m120事件只核相应两天，算法不执行。

当前候选过滤仍为TopCurrentCloseCalculator原方法，产品无差。CodeGraph检出目标继承/调用关系但source扩展误选同名其他模块，不能把该输出当目标源码；另核目标当前方法与原80文件SHA一致，不改索引或运行无关代码。90分钟14点前后以相邻封存DIF/柱值区分：缩柱不必DIF下降；与讲稿14点无结构、15点有结构相容，不宣称软件精确指标值已核或1%唯一。日线没有新黄不等于程序普通状态NONE的全部内部含义已证，也不推出5/10结果。预算、失败续跑及保护按算法§12.71，产品/API/预测/页面/配置/合同均不修改，不重复运行已通过的88工程回归。

### 49.1 本步结果

管理员“没有钝化”确认5/9日线此图末端无新黄；原实验候选原样与之相容，5/10、截图精确时刻/软件旧峰仍未知。图收3356.95与本地3357.6707小差单列，未重算输入。13行投影及已存两组事件核90/120均在5/9 15点结构；讲稿明确90分钟14点无、15点有，封存14点仅柱缩而DIF仍升，说明第一根缩柱不足确认结构，不能据此锁1%。120“闪烁”时点仍待核听。

证据目录（原记录：`reports/xxm_top_current_close_20261020_01/may9_evidence_20261020/README.md`）保存原图、原文节选（非全文）、用户答复、读数差异/重复模式；96份原保护保持。无候选/产品代码、预测、接口、页面、参数或预期修改，无新检测器执行；新观察相容不等于公式通过，不重复88项已有工程回归。

## 50 120分钟未形成的更正与5月10日日线（2026-10-20）

沿算法§12.72，仅新增证据目录，原完成产物不可变。保存管理员“闪烁”“当时还没有结构”原话，撤回LLD§49.1中120分钟已获软件确认的部分；90分钟确认保持，最终120收盘状态未证。读取may9_evidence的minute_diagnostics和saved_comparison，追到程序当根17.179169→16.593780下降3.408%超过现1%所以报结构，但这是本地输入/实现解释，不等于软件应报。不用单例把门槛改4%或其他数值。

5/10图只核日线新紫有无；软件数字人工记录及精度限定，日线对照来自旧day.json的5/9—10差异/point，不新跑模型、不重选旧峰或改价格。只判可见标记，不将缺紫扩大为软件全部状态/内部历史已知；将用户明确确认、直接图读及推断分别标注。新目录保护原5/9 final_checks及全部文件，旧来源/代码继续按原80保护；预算和失败规则沿§12.72。新观察只审计，不新增自证式测试或修改已有88工程预期，无接口/预测/页面/参数/合同影响。

### 50.1 本步结果

5/10日线末端无新紫的图读支持原样候选，软件收盘按两位一致，指标末位小差保留；5/9无新黄仍是管理员明确确认。原程序因5/9已钝化而5/10报结构，候选保持未首次钝化故不报，与有效钝化前提相容。

120分钟核听为当时尚未形成，不能再将本地15点报结构当软件通过；最终同一完成时点未知。90分钟14无15有保持，120待核差异不通过改1%消除。补图及更正（原记录：`reports/xxm_top_current_close_20261020_01/may10_and_flash_clarification_20261020/README.md`）保存原话/撤回范围/原图/本地对照，109保护保持，无新检测器执行或产品/候选/预期修改。

## 51 120分钟临界价格及画面时点核查（2026-10-21，仅算术审计）

沿算法§12.73。CodeGraph读取当前ProjectionState.advance/project与调用关系，已核当前step中有效DULL的DIF转向分支及TopCurrentCloseCalculator只覆盖首次selector，当前Spec仍1%。不修改服务/消费者/合同，不运行预测器。仅从旧10行投影取每周期5/9的前根DIF/DEA与末根C/DIF/DEA/H，所锁定参照用旧saved_comparison的5/8激活事件，不反推软件实际旧峰。

用十进制原文转有理数，k=28/351，先独立解D(P)与相对1%方程，再用ProjectionState.advance的EMA方程作一致性核算（只作算术，不调用产品函数）。恢复前根E26=C0+((11/13)*Dprev−D0)/k、E12=E26+Dprev，核D(C0)、DEA=.8*DEAprev+.2*D、H=2(D−DEA)与封存误差。逐个检查临界值±0.01及共同区间中点，核历史参照未破、红柱和DULL前提在此区间不另改变；浮点等号边界不当精确软件跳变价，给出条件意义及误差限制。

保存“若同一120画面也是3356.95时”的条件结论，不将两屏同价当事实；核听只确认讲解当时120未形成，原文开头收盘说法与该句时点仍未明。软件最终同一时点状态和数值待证。范围/读写/失败续跑/预算依§12.73，旧源/原完成文件/候选与产品SHA保护；本轮无新CLI、测试夹具或参数，不重跑原88工程回归。

日线显示精度核算只读旧image_numeric_check：封存收盘3357.6707与图3356.95，δD=(28/351)δC、δDEA=.2δD、δH=1.6δD。分别将源/图三位显示转成半开舍入区间（远离正好半单位边界选内部可行点），求D0、DEA0及H0=2(D0−DEA0)是否同时可行。输出交集/可行原值是条件数学见证，不重写输入、不当成软件真实EMA，也不由可行性认定截图具体时点或所有历史一致。

### 51.1 固定价格条件的核查结果

现1%下90临界3380.342973、120临界3362.855738；两者之间存在90转向成立而120不成立的区间，已核正柱/原峰未破及邻点，EMA重写和有理数计算一致。3356.95则两者都成立，因此不能单用日线截图0.72点小差解释120尚未形成；120实际画面同价/同时点仍未知。日线DIF/DEA/H显示差同时与价格差及0.001精度相容，可行原值不冒充软件值。

结果及约束（原记录：`reports/xxm_may9_m120_time_price_audit_20261021_01/README.md`）保存117保护、已问的120画面具体文字/价格及未证范围，无新模型/预测器或源读取，无实现/接口/消费者/参数/预期修改。不能以数学区间恢复撤回的120软件通过结论，资料到达前保持待核。

## 52 120分钟紫字与真实收盘价的确认（2026-10-21）

沿算法§12.74，仅原话归档与结论接续。管理员明确画面为紫色“结构形成”，实际收盘3357.67，截图“应该”在收盘前；事实/推断/未知分别保存。只比较旧投影末根close=3357.671及旧日线point=3357.6707的两位显示，不运行calc、ProjectionState或预测器。当前已有钝化后的step及研究子类只过滤activation的代码已核，不因新答改变实现。

更新软件观察为“120画面有结构形成文字”，结束字样待答；此前闪烁解释不能当成无字/最终无结构标签。两组本地15点结构方向相容，最终固定时刻、软件数值/旧峰仍非本次确认，不将可见文字变成完整收盘状态测试夹具。原价格区间与原撤回记录保存，不反写旧完成文件。不再索同屏/重复问紫字，后续研究可回到首次价格候选的其他反例；若以后独立验收收盘固定状态，再另限定取材。保护/预算/失败续查沿§12.74，无接口、预测、页面、参数或消费者变化。

### 52.1 本步确认完成

已归档原答复、两位价格显示/旧事件对照，125保护保持。紫字可见与本地结构方向相容，不再把该画面作为已确认无结构反例；最终固定状态与1%公式未另验收。截图精确时刻/120实际顶栏数字未知，不重复问已确认内容或套日线价。无候选/产品/参数/源码或原测试预期改动、无新模型/预测执行。当前确认（原记录：`reports/xxm_may9_m120_time_price_audit_20261021_01/screen_confirmation_20261021/README.md`）为本题当前口径。
## 53 先用当根价格筛选旧段，再选择首次TOP参照（2026-10-21）

执行范围和独立观察按算法§12.75。新图/稿将旧候选“先选中1月峰再整体拒绝”的不足具体化；不是证明软件采用本地两段池或收盘价。实现前已核产品selector/step及旧候选：前者以wave.price选最强eligible，后者只过滤已选结果，无回选；现事件/底部/旧历史结束分支仍由产品类负责。CodeGraph explore覆盖产品类、研究子类/工厂/执行器/测试，文本反查src/wealth无研究入口消费者。

新增PriceBeforeSelectionCalculator继承旧候选step的校验/当根保存，覆盖selector：BOTTOM直接用XxmCalculator原selector；TOP对同一history先核incoming.close>最近段price，再将反序旧段按DIF降序稳定排序，取第一个incoming.close>ref.price且wave.dif<ref.dif者。原selector返回仅作对照记录，不把其已选失败作为停止搜索的理由。重复价格/DIF相等均严格拒绝；两峰都合格仍选强峰。诊断保存两峰资格、原选择/新选择及当根价；不用末端未来极值，也不把wave.price重新加回筛选条件。

研究身份独立于旧候选/产品，仍携原baseSpec/hash并明确不是产品新版本；不新增Settings/env/数据库配置、页面开关或正式入口。继承step每根重设临时incoming/check，snapshot仍为产品合同，sourceIdentity阻止跨候选恢复；锁定后的参照不改。新增独立runner因旧run_period固定factory不可直接复用，只组织三组执行和账本比较，共用load_bars、ordinary、trace、check_time、new_observations及seal/read_unit。旧模块/测试/产物只读，维护代码不放reports。

先冻结证据和125旧保护加最新确认目录，记录原图稿字节、封存来源SHA、63行投影和独立日期级黄/近峰观察。新runner运行四周期40,478行，产品对原r2账本（日线02精度版）、旧候选对旧sealed全部事件；新候选每根核分段/底部、完整52字面标签、后来10项及5/9无黄/5/10无紫/2/25有黄，未知14/15不评分。另保存含2/25两峰的窗口诊断和完整三组事件/差异，首尾sourceIdentity与prefix/restore相等。原标签和旧候选不可因失败修改；新旧近期峰定性独立列，不用所选结果生成expected。

预算/中断/续跑沿§12.75：固定来源≤256MiB，20秒/周期、60秒全步含重算/末验、20MB/文件64MB总输出，拒绝复用旧目录；失败保留RUNNING/FAILED及已封存周期，不覆盖完成物，下一新批次重算。测试用独立字面价格120/110、DIF12/10、当根115而段高125，预期新选近110、旧无黄；另核两峰都可选时仍选强120、未过近高、无DIF资格、同强先近、最少两根与DIF正、已有状态不重筛、底部逐根相同、恢复身份及非法输入无变更。最后源/旧结果/代码保护、测试、文档链接和CodeGraph同步；未调参、不写正式源、不跑预测，不声明公式或产品迁移完成。

### 53.1 本步结果

新增离线覆盖类/三组比较入口及13字面测试，旧候选源码/7测试/完成结果只读；13新加原88共101通过，入口帮助正常。完整40,478行约1.86秒，峰值约135MiB、初始结果9.44MB；139保护保持，产品原r2事件/日线points及旧候选原sealed事件一致，BOTTOM/分段/池、截断与恢复保持。原52条全部相容（置信不变），后来13项新候选全部相容，但后者已参与研究，不作独立验证。无正式源/网络/安装/预测/API/页面执行或产品变化。

2/25本地新参照为2/5—13正柱段，DIF峰2/12，14点首次钝化；与讲稿近峰定性相容，软件具体首字/旧段数值未知。新旧候选实际不同仅m60三根、m90二十六根，其余day/m120逐根相同；三处首次选择差异带来5去/9增事件，不判软件已通过。下一反例2017/3/28 m90的模型分歧见算法§12.75.1及完整报告（原记录：`reports/xxm_top_current_close_selection_20261021_01/README.md`）。现有转换仍为产品实现，不据有限图稿称1%、两段池或全部消失规则已证明；产品迁移另议。

## 54 近期选材与固定近远峰阈值交叉核查（2026-10-21）

按算法§12.76停止2017/2015取材。旧sealed事件中2026/1/27 m60和2024/7/19 m90的差异首先只作为首次当根价条件候选，不称先筛后选已另获支持。仅读既有四周期来源与新候选：首次TOP且近/远两段价格及DIF都合格、当前锁定远峰时保存当根bar、history两个reference、原event；其后只有同一正柱段和同一锁定ref继续时才检测wave.dif>近峰DIF且wave.dif<=远峰DIF的第一根，保存前根/本根/当前ordinaryState/事件。参照或柱色退出即停止该例。全部事件仍与§53完成账本逐项相等；这是阈值区分度筛选，不冒充近峰完整状态机模拟或已验证软件消失。

同日跨周期只保存2/25末根bar/point、近两段、现段与讲稿原词及其时态限制；4188仅近似口述，未做调参/反求强行匹配。新结果目录、预算、保护、失败后新批次重算沿§12.76，原方案先限定再执行，无新维护脚本、配置或产品影响。只读真实冻结输入/账本和算术核验足以覆盖本步，不重跑与此无改动的101工程测试；准确记录新近日期是否确有区分力、仍缺哪处图稿，不将本地一致性当软件独立验证。

补充复用已保护4/18日线原图和管理员确认，不把旧结构停止价格比较与新钝化选择哪个峰混成同一结论。取原day完成窗口4/14—18及两旧段：只验证24.935<26.754<41.186与图面未见新消失的相容；最近段两根可能不构成软件合格参照，身份和历史数值仍未知。继续对6/25两个分钟案例按时间边界计数来源行、逐行核正柱、核收盘DIF区间与参照在本地未退出；不计算另一模型的最终状态，不把软件缺图填成期望。

### 54.1 筛选结果及交叉核查范围

原40,478来源、三组完整事件与§53原sealed全部相等；156旧保护保持，无维护代码/配置/接口/产品变更。36处两峰都合格选远峰，16处随后只越近峰，按原锁定/柱色退出边界截断；首个越界前根最高DIF仍未越，当前严格大于近峰且不大于远峰，不等式及来源段计数另核。新近但只盘中有区分的案例不优先要求收盘图；选6/25 m90近段28根、收盘仍在区间，m120近段14根可同视频顺带核，不模拟另一完整模型/事后补黄绿预期。

已用4/18图给新钝化选峰增加限制，但两根近段资格仍可另解，未新增独立软件案例；2/25四周期与口述4188方向相容，同样不升级公式真值。备用1/27 m60单独检验当根价格，不冒充选峰顺序的独立反例。旧101工程测试无改不重跑，新验收仅原账本一致/独立算术/156保护/文档与文件校验。取材与未知范围详报告（原记录：`reports/xxm_recent_reference_crosscheck_20261021_01/README.md`），2017/2015不再索取。

## 55 6月25日新图稿与近远峰判断边界（2026-10-21）

按算法§12.77先归档新90图和全文ASR，原件不改错字；09:59后90收盘钝化为直接口述，60已消失只作讲解时状态，120约12/7/26是数值/比较对象线索，日线约15.64/23独立保存不搬周期。图末端黄与左侧绿的精确首字/旧绿日期不在本步评分，当前口述足以结束反复辨字。新材料仅一组，不改变旧52/13预期，也不把三个周期算成三次独立行情。

读旧recent_reference_cases/first_cross_arithmetic/april_and_june_crosscheck和原三组sealed事件，来源仍沿其SHA保护，不跑calc或重读源。保存90软件当前显示与本地差；验10.557<14.491<23.498、120的11.886<12.049<26.115及口述26更接近远峰，60本地6/25 11:30 CANCEL与口述当时已无钝化的方向相符；软件60具体时点和120最终固定状态不另造标签。

当前已核step CANCEL清ref而同段下一根可再进入activation，故固定两峰算术需要保留“14点若近峰被越，15点仍能满足远峰首次条件”的替代解释。只核现成15点正柱、DIF>0、价过近/远高及本段最高DIF仍低于远峰，不构造完整假设状态或变更原selector。结论限定为支持有资格时使用较远强峰、反对机械永远最近；起始选峰/锁峰/重选的唯一软件规则未证。24周期语句和预计未来消失原词存档，不新增期限/调参。预算、失败保护和下一独立取材按§12.77；本步仅证据与文档，不新增维护入口、测试、产品或API影响。

### 55.1 本步结果和未证项

原图全文同字节保存、169旧保护保持，9行旧投影/三组已存事件和独立不等式核验，不运行calc/新CSV/预测或新测试。90明确收盘仍钝化，120口述26更接近本地远峰26.115而非近峰11.886；60讲解时已消失与本地11:30取消方向相符但软件分钟未知。90图DIF/DEA/H存在小差，不改源，日线23不可当90峰的口述确认。

本轮新材料只算同日一组，原52/13不重写、不追加三项独立通过。支持有资格时远峰参与，仍未区分起始锁远与中途换峰，当前代码允许取消后下一根再选，15点资格算术不能充当另一模型的完整模拟。未据24周期口述加失效期限或据未来预测造标签。材料已收齐，不再问同日图稿/模糊首字；后续首次价格与锁峰问题分别验证，产品保持。当前报告（原记录：`reports/xxm_jun25_reference_evidence_20261021_01/README.md`）为本题交接。

## 56 近峰先选、取消后重选的完整离线比较（2026-10-21）

执行边界按算法§12.78。代码/影响面已核：现PriceBeforeSelectionCalculator筛资格后按DIF排序，继承step只在没有参照时选择；原CANCEL清ref且同根不再activation，下一根可再选。旧ReferenceGateCalculator不是本次语义（旧段长/零轴与wave.price），两个当前run_period也都是固定工厂；因此只新增独立离线选择覆盖与两组执行组织，不复制产品状态转换、不改已保护旧模块，不把Dagster同名run_period当依赖。

新NearFirstCalculator继承PriceBeforeSelectionCalculator，sourceIdentity用其研究前缀下新的nearest-qualified-v1身份，拒绝其他工厂恢复。TOP先调用父类保留相同资格诊断，再在同一history反序中选首个close>ref.price且wave.dif<ref.dif的段，仍要求父类的最近价检查/最少根数；BOTTOM直接返回父类。已有状态的取消、结构、历史处理全继承，不增加当前ref每根重选。diagnostic保留strongestEligible与实际selected。新入口只接收新reports目录，完整输出强/近两组事件、固定52/后来观察、逐根差异、近年收盘不同/同状态不同过程清单和6/25已知范围；源用已有load_bars/manifest SHA，保存复用seal/read_unit/save。

两组同一源起点并行逐根算，强组对原candidateEvents；wave/history及底部事件/历史/rearm每根相等。原52 ordinary事件严格按字面endpoint评分；后13仅沿已封存观察范围，6/25收盘DULL单列状态直接观察，60讲解状态/120口述26不变成精确时刻。收盘筛选以15点或日线完成bar的ordinaryState/方向差异为准，activeReference不同但同状态另列，不先假定软件CANCEL画绿。结果丢旧观察只登记，不能修改期望。两组分别核截断及恢复，记录中间取消后重选的实际链，而不是只用末态算术猜过程。

独立测试、配置/写入边界、预算/失败/下一新批次重算按§12.78；runner必须在所有预算/保护末验后才写COMPLETE，异常/中断尽力写FAILED保留完成单元。没有新增Settings/env/正式参数，算法Spec仍现原值并另标研究身份；仅离线模块和同主题测试有影响，未调预测/接口/页面。新近材料优先仅一份，无法在已保存源与可见观察中区分时保留未知，不靠任意调门槛补出结论。

补充原始依据复核：8/18 direct若受影响，回看原图且核holdout.source.sha；8/15字幕3750仅作反复一致的近似口述。当前m120冻结CSV按8/6—18过滤≤20行，manifest/SHA及字段沿原合同，独立恢复8/15 EMA状态并计算下一根对近/远DIF峰的价格边界，核3750与哪一峰相容；不把两个门槛和三个比例重复比较计成独立样本，不执行历史reports脚本。原近峰尚未破时已口述远峰门槛，可以限制“必须先破近峰后才换”的解释，但仍不排除其他更换规则或宣称全算法唯一。

历史replay_color_flip同名两策略已经原码核验，但使用wave.price且缺现产品状态链，不替代本步带当根价资格的完整比较。若需要继续区分初始远峰与未取消前换峰，优先已有库未收录的8/7 120讲稿首次比较对象；先核存档。对8/7末根下一周期作同一EMA条件算术仅辅助确定应听哪个数，不改检测器、不当软件实际阈值或预测。

### 56.1 本步验收与结论范围

9个新字面测试加原101共110通过，入口帮助正常。两组40,478行约1.9秒，强组原sealed事件逐项一致；底部/原始分段/池、两组前缀与恢复相等，180保护保持。原52对照强52、近49，原13后来观察按既定范围均相容；近组8/18下午漏direct取消，另外两处是mapped无事件不符，标签/置信未修改。6/25 m90近组实际14点取消、15点远峰再钝化，末态相同；m120近组下午取消、强组仍钝化，不把语境口述补成精确软件分钟。

旧图和字幕独立复核支持进一步限制：8/18下午绿色原图/holdout.sha一致；8/15约3750与远峰下一根价3750.733相符，而近峰为3715.211，当前截至8/15最大DIF28.851未过近峰29.635。复用原证据不新增独立样本，旧stage2脚本未执行。当前同一资格/转换下近峰优先且只能取消后再选方案不相容；未取消前换峰、短段资格等其他解释未证，不能宣布最强峰/永久锁定完整公式。

收盘不同仅4个近期点，其余同状态不同过程不能索普通收盘图强分；已有材料已足以反证这一具体近峰方案。下一只缺8/7当日120分钟讲稿初始比较对象/消失价，存档未收，不重复索8/18或6/25。只新增离线模块/测试/报告及原文档，产品/预测/API无变化。CodeGraph用explore核原研究类继承与固定工厂影响，实际源补核历史selector区别；新模块同步与末验记录见报告（原记录：`reports/xxm_top_reference_priority_20261021_02/README.md`）。

交付审查把新增负向测试远峰价120改100，以100<109≤110验证漏近价检查会错误回选，不改拒绝预期/算法/原101。原测试字节和审查依据留01，当前110与固定源两组重新封存02，完整事件须逐项等同01；不改旧已完成报告或借此调整业务标签。

8/7原稿优先通过已有vidIQ公开工具有界取材，原“零网络”仅对此取材按算法§12.78补充放开；最多2次同频道日期搜索/2份字幕，先核余额与实际成本，不购买/接新账户/发布/下载音视频。标题、频道、开头日期、原返回与SHA归档02子目录，失败如实记录请求管理员缺失资料；取到后只核原有近/远峰边界，不重写已经完成两组结果或参数。具体插件技能与工具权限按当次可用能力执行，不以历史工具成功代替本次实测。

实测仅余额查询，返回消耗0；两项付费公开工具未获积分消耗授权，遵技能规则未调用。普通公开搜索两次未定位精确日期目标，不把错日/无关内容当证据，不据此称无视频。8/7稿仍需管理员补，公开取材记录保存在02/online_material_lookup，计算器/模型输出不变。

## 57 8月7日材料与价格对参照资格的作用（2026-10-21，只读研究）

实施范围由算法§12.79限定：材料原字节归档至新reports/xxm_aug07_price_reference_evidence_20261021_01，转录原文不润色覆盖。图读末端黄及close/DIF/DEA/MACD按三位精度核；无指峰/消失价则初始参照继续未知，不把两组相同DULL当排序已证。日线再一根红柱语境只作最少两根的支持，不将明日预计当实际发生；90序列按收盘失效与钝化比较分别登记。

只读取现selector及其产品继承、§56 sealed结果和18行既存投影；m120冻结源额外只保存7/21—28及7/30旧段≤16行。通过原close/DIF字段独立求两段最高收盘及其时点、DIF峰及当根收盘，直接对照激活诊断中的price和dif，不复制step或重跑检测器。14行8/7—15逐根核close是否持续过两旧价，说明价格资格有无改变。2/25近峰已由当根价排除远峰的证据直接复用，不重新读另一周期或添加新真值。缺high字段明确只能核最高收盘口径，不补字段或调用外部接口。

保持原180及02全部完成文件SHA，核4份周期marker、新原件/冻结源身份及SHA；输出单次新目录、失败保留、原范围重核≤60秒，内存≤256MiB、输出≤10MB，预算包含中断后再核和最后验收。不新增配置、产品/API/预测修改，不访问正式库/Lake/网络、不安装/提交/部署，不重跑原110或将工程通过作为公式证明。交付只更新原算法/LLD/研究/交接及主题导航，附有界算术、来源哈希和仍需区分的规则，不继续索8/7已齐材料。

### 57.1 本步结果与下一疑点

新图稿只确认8/7 120新钝化及90亦有，初始比较峰/消失价未给；原材料请求已结束。末端close及DIF/DEA/H按显示精度相容，截图精确时点/完整输入未证。两旧段14行独立重算与原参照相等：远段最高收3608.5757、DIF32.468749；近段最高收3628.53、DIF29.635070，按价格较高与DIF较高指向相反。远段DIF最高在7/24下午，价格最高在7/23上午，不能拿同一根假定替代。8/7—15复用14行全部收盘过两旧价，最高DIF仍未过近峰，故单纯价格后来达标不能解释本段中途更换；缺high继续不推广至软件最高价定义。

回读既存8/15全文，120“又重新钝化了啊，新的钝化”及3750/涨54点可作为下一步检验结构回到钝化时是否重选的动机，尚不证明软件换峰，也未开发另一候选。199旧文件与四周期完成marker保持，原52/13未改，未重跑110/40,478；当前只更新证据/原文档，CodeGraph核现价格更新与两层研究继承，无API/产品边界变化。见本步材料与数值（原记录：`reports/xxm_aug07_price_reference_evidence_20261021_01/README.md`）。

## 58 三组结构回转参照实验（2026-10-21，实施前限定）

范围/硬条件以算法§12.80为准。A复用PriceBeforeSelectionCalculator，B复用NearFirstCalculator，C新增ReturnReferenceCalculator继承B；只在同一正柱段已有STRUCTURE、未越原参照、满足原正向1%回转时重选强峰。所有数值条件/同强先近/当根价资格复用PriceBeforeSelectionCalculator._select_eligible_reference。没有合格峰则NONE/无参照、无新DULL；既存TOP历史仍由原step更新，不造新事件或静默保留黄。原CANCEL优先；下一根普通activation仍最近优先。原始段色不是后续行情原因，价格和DIF峰分别保存。

现产品step在wave极值更新后、读取ref作普通转换前逐根调用_rescue_bottom_dull_reference；现实现只改BOTTOM。离线C覆盖该方法，先super保留BOTTOM，再对TOP上述时点替换ref，让原step产出一致事件/id/历史/point，不复制step或事后修改事件。step仅增加合法性检查后清空本根return_check，保持无效输入原子性；保存原ref、候选资格、选择及无合格原因，回转诊断与首次activation诊断分开。独立source_identity前缀满足继承链但不能与A/B快照互换。此诊断不更改产品快照schema，跨前缀恢复和断点恢复按原合同检验。

旧runner为固定工厂和两组完成对照，变更会触碰旧代码/历史SHA。故新增xxm/top_return_reference.py作C和三组有界编排，测试集中tests/test_xxm_top_return_reference.py；旧两个模块/产品/参数/110测试不改。CodeGraph已核inheritance和当前hook/selector；没有前端/API/运行链消费者迁移或架构快照更新。原52/13观察函数尽量复用，C映射为另一组后只添加结果字段，不改原标签。

门禁落点：字面旧峰price120/DIF12、price110/DIF10与实际XxmBar恒等式构造回转序列；必须证明无回转不换、强峰价格不合格不选、低/等近高无新黄、重新达标可激活、越旧峰先取消且当根不再选、同强先近、底部/历史和source身份保持。用独立字面expected核事件ref及关联，不调用待测函数造预期。原110一起回归；三组固定40,478行A/B事件必须与§56_02sealed完全相等，逐根wave/history/BOTTOM保持，C截断和恢复一致。

输出新reports/xxm_top_return_reference_*，保护§57原199+全部报告原件及新代码/测试；周期≤20秒、总≤60秒含源校验/全计算/恢复/输出/最后保护，≤256MiB，20MB/文件及64MB/总。run先RUNNING，周期原子封存，预算/检查失败FAILED保留；下一新批次原范围重算≤60秒，不覆盖已完成物。保存回转检查、完整事件、固定观察、已用案例及2023以来A/C差异，选材要注明已使用/状态差异或仅参照差异。新证据缺口明确后只问一个必要问题并停止；不得把8/15好转当普遍规则。正式源、网络、安装、预测/API/产品/配置/提交部署均不进入本步。

### 58.1 实际检查及待核范围

15新字面加旧110共125通过，入口帮助正常；一个样本混入历史新高消失，依现合同将130改125保持原断言/算法，记录原失败依据，另补精确1%包含性。三组40,478行约2.32秒、188MiB、初始17MB；A/B全部事件对旧sealed、分段/池/底部与C截断恢复相等，214保护保持。原52 A52/B49/C51，C仅丢6/26 m120上午mapped无事件；13旧确认按原可见范围相容，不扩大为完整状态/算法通过。

C在8/15 m120重选远峰，下午取消与已有8月证据相容；但6/24—26 m120无回转机会，C同B在6/25下午取消、6/26上午重进。6/25稿明确120的DIF12/7/旧26及后续预计消失，所需120图尚未取得；6/26缺字原图回看，mapped锚点限制保持，不单凭此否定。下一只核6/25视频07:05—09:59的120最新黄/绿及DIFF可读值，提出后停止等答复；不重索已有90图或全文、不加日期特例。A/C近期差异已存但不继续索一串材料。新模块/测试和原文档为唯一改动范围，产品/API/预测未迁，CodeGraph影响面/资源/来源和完整记录见三组报告（原记录：`reports/xxm_top_return_reference_20261021_01/README.md`）。

## 59 6月25日120字样答复归档（2026-10-21，只读补证）

按算法§12.81归档原话：右端“消失”在“钝化”左侧、DIFF无法读，年份2025已纠正。确认范围止于可见文字和空间顺序，不填精确分钟/软件指标/已完成收盘或同轮关联；未有新图文件，不写已自行核图。只投影原sealed m120六根及事件/历史：6/24上午旧结构绿、下午新黄三组都有，A在25日续钝化而B/C取消。该字序单独不能唯一判A或否定B/C，也不意味着普通CANCEL必显示绿；须结合原稿12/旧26/未来消失的语境登记A更相容及C当前不足。

无新计算器/模型或测试执行，不改125测试、原52/13、参数/API/产品。新reports/xxm_jun25_m120_confirmation_20261021_01保存用户原话/旧窗口投影/来源SHA/限制，保护§58全部214加上轮完成文件；≤60秒/256MiB/10MB含末验，失败新目录保留、下一新批次固定范围重核，不覆盖历史。只更新原研究文档/导航，完成原话范围、4份sealed、保护和链接/文档检查；该请求结束不再索同字或DIFF，后续首次选峰/旧段资格另按计划，不直接迁产品。

归档核查后确认保护共231，旧m120六行中三组都具前一旧绿/后一新黄，仅25日后续取消不同。答复本身不构成唯一选峰或软件15点完整状态的直接确认；仍结合原稿约26语境登记A更相容、C当前不足。无新测试或模型执行，旧52/13不改，结束待回复状态，DIFF未知保留。本次答复与边界（原记录：`reports/xxm_jun25_m120_confirmation_20261021_01/README.md`）为当前接续。

## 60 6月25日120原图读值与6月24日初始比较语境（2026-10-21，只读研究）

按算法§12.82，原图同字节保存至新reports/xxm_jun25_m120_image_evidence_20261021_01。新图身份/黄色绿色/5月红圈及三位DIFF、DEA、MACD独立读值，原文字答复不覆盖。只投影§58 sealed m120行/原两段历史和8月12/2根，保存每个读数与本地差/严格不等式，不写已核软件完整输入或精确时点。若图显12.048高于本地11.886但仍有黄，结合原稿旧26可限制B/C当前实现；软件近峰值/显示语义未知保持，不单靠字位推状态。

原14根近段与8月被比较12根远段的同一最少根数N条件仅列N>14和N≤12的矛盾，不开发新短段过滤器。回读已归档6/24原稿15:09—15:35及同日旧ASR，只保存“格峰/隔风”原词，不以别日“邻峰”答复代替；若需要核听只问该时间段并停止。确认原词后仍不自动等同软件两段池/排序或唯一初始参照。

保护§59原231+全部报告文件/三组4sealed/新旧材料SHA，输出≤10MB、核对≤60秒/256MiB含末验及失败原范围重核；不覆盖旧完成结果。无新模型/工程测试/正式源或网络，未改维护代码/产品/参数/预测/API/配置，不安装/提交部署。当前selector语义已由实际代码核；验收为新图读值/精度边界、有界已存极值/段长/原文、原文件/文档链接，不把图面相容当完整公式证实。

结果：原图四值分别3455.97/12.048/4.513/15.069，与本地差<0.01或0.001，未强作四舍五入相等。末端黄/左绿/5月手绘圈已图读，软件旧峰与精确时点未证；12.048跨本地11.886而未跨26.115，使A和讲稿旧26的解释更连贯，B/C仍不足，不将字位变成同轮关联或唯一公式。固定段长单条件N>14和N≤12不能同时成立。已存6/24原稿“格峰/隔风”旧解释未获核听确认，只问15:09—15:35原词后停止。237保护/四sealed及原标签保持，无模型或125测试重跑，新原图及原词语境（原记录：`reports/xxm_jun25_m120_image_evidence_20261021_01/README.md`）接续原未知阶段。

## 61 6月24日“隔峰”答复归档（2026-10-21，只读补证）

按算法§12.83，管理员已确认120和90分钟两处均为“隔峰”。新增报告保存原答复、问题日期/时段/周期、原稿SHA及已存窗口投影；不修改ASR、不宣称自行核听。此前待核状态作为历史保留，本步结束该请求。

复用现有三组结果，不执行新计算器：6/24已有隔峰比较讲解，不能只靠6/25越近峰后的换峰或更晚的结构回转来解释作者为何已谈远峰。只支持较远峰当时可参与，不证明精确初始软件参照或最大DIF普遍优先；原52/13不改。保护上一报告237及全部文件、四周期sealed，资源与失败规则从算法§12.83；验收为原话范围、原稿哈希、既存窗口来源与文档检查。无代码/测试/产品/API/配置变化，不重复运行125测试或40,478行模型。

归档已完成，245保护、四周期sealed及原稿SHA保持；只复用90/120共十根窗口。两处隔峰已确认，精确首次软件参照仍未知，未新增算法规则。答复与既存对照（原记录：`reports/xxm_jun24_gefeng_confirmation_20261021_01/README.md`）为当前接续。

## 62 定量结构课程的模型与实现对照（2026-10-21，仅建模文档）

按算法§12.84，先归档管理员课程转录并建立逐条可追溯的规则模型，输出新reports/xxm_quantitative_structure_lesson_20261021_01。逐对记录峰的分隔、价格/DIF关系、转折与换色两个观察，不预设唯一参照；软件最终显示/采用哪一对另留问题，不修改现单一reference合同。价格字段、零柱、相等、幅度与收盘时点未明时须显示未知，不以默认值补齐。

当前代码依据：calculator.py:35—55按hist符号分段；:47—48钝化遇异色可直接发结构；:75—79前一根DIF反向达到spec.dif_turn_pct则发结构；:157—170按两段历史及价格/DIF选择；types.py的XxmBar只有close；spec.py当前1%、max_refs=2、min_bars=2、flip_requires_turn=False。以上是现实现事实，课程只补充分隔及方向原理，不证明所有数值/确认路径。已有A/B/C保持不动，当前翻色确认与本课75%/25%的关系需核清后才讨论开发。

后续若实现，必须先确定确认逻辑及price/峰的合同，再以独立字面样本验红绿红/绿红绿单根分隔、未分隔不能作两个峰、钝化但未转折、转折但未换色、换色但未达原1%、多旧峰分别达标等边界；本步仅列验收问题，不编造已通过测试。原125、52/13、三组账本和四周期sealed保持，保护/资源/失败续核按算法§12.84；无新模型执行、代码、参数、API、正式源或产品写入。归档与模型完成后就13:06—14:43的确认含义提出单一问题并停止，缺图/缺后续课不当成算法结论。

### 62.1 第二段课程接续后的模型条件

新到自述2015/3/11的第二课已明确DIF转折可在换色前形成结构，撤下上段原词/含义请求，按算法§12.84.1一并归档。模型区分钝化持续、转折形成但未换色、已换色三个进度及两类纠错；形成点与后续有效状态分开记录，不改现事件历史。新段至少两根由第二课直接支持；两峰之间异色一根足以分隔由第一课支持，两者不能混成同一个根数条件。

DIF两位取数规则须先核图才能确定截取/舍入、负数和跨量级处理；当前1%与完整浮点比较保持为现实现事实，不升级为原课规则。新报告记录旧峰和当下DIF两种比较的取数缺口；不改spec或另造可执行计算器。当前程序零柱切段亦须与“异色分隔”区分，本课未明确零值口径。

后续数值验收须补：原DIF微变但前两位改变、原变化超过1%但前两位不变、负DIF、零附近及9.9到10附近的量级边界，并独立核对课堂原图数值；本步只列问题不预造软件真值。只请求第二课13:18—13:28和21:10—21:30两幅取数画面后停止，不重问DIF转折是否可先确认。两段课程不自动成为现代软件新金样本，原52/13/三组成绩及产品保持。

结果已保存于课程模型与代码对照（原记录：`reports/xxm_quantitative_structure_lesson_20261021_01/README.md`）：两份原件、17个时间段、14条规则；252保护及四周期已完成文件保持。新旧峰关系、确认进度及纠错分别记录，现有数值实现未替换。只待第二课两处DIF取数截图，无新工程测试或模型执行，不将文字建模当产品验收通过。

## 63 DIF两位截取的图示及算术（2026-10-21，仅数值建模）

按算法§12.85，收到的第一图DIF-8.086对应课稿8.0/80，第二图DIF40.057对应字幕41→40；归档图像及用户时间说明，不填前根41.xxx的精确值。首图支持截取而非四舍五入，但零、量级边界、等值条件及现代软件同版仍未由图独立证明。

研究定义保留符号和量级、首个非零数字起两位，之后舍去；零定义为0仅为候选算术完整。保存原值和截取值，比较的中间值不覆盖原始MACD三值，不调整分段/柱色。当前calculator.py:75—79以原始前根DIF的1%作门槛、spec.py:11固定1%，本步用独立字面反例说明两者不等价，不声称已经替换代码。

只读已有90/120共十根窗口作DIF比较投影，近远峰与当前值分别截取并保持原模型身份；不重新选择参照、不产生新结构事件。正负反例、跨量级和图示算术在新报告保存明确输入/期望/实际，属于数值检查而非现状态机或新软件金样本。后续若开发，须先设计比较落点及确认/回转语义，不能改一处1%就称全部采用两位规则。写入/保护/资源/失败续核按算法§12.85，仅原文档和新报告变更，原125测试及52/13保持。

结果：图示与数值模型（原记录：`reports/xxm_two_digit_dif_images_20261021_01/README.md`）已保存两原图、19字面例/4正负反例和十根窗口20次比较。原值-8.086按-8.0讲，较明确支持截取；第二图40.057按40，前根41.xxx仍未知。1%与截取后变化不等价，但6月近远峰大小关系未变，不能称已解决选峰。261保护/四周期完成文件保持，产品/参数/125测试/52及13不改；本次不是检测器重放或新规则验收。原两处截图请求结束，下一只针对DIF比较落点准备独立候选设计，暂不需补材料。

## 64 两项学习成果的文档整理（2026-10-21）

按管理员最新要求及算法§12.86，本轮只整理两段课程的学习成果，不承接上段待开发事项。唯一学习摘要为研究主文档§8.145：一项是钝化/结构/换色前后纠错关系，一项是DIF从首个非零数字起保留两位的比较方式。每条保留原课时间及截图依据，区分课程标准已明确、截取模型解释和仍需材料/软件验证的边界。

当前产品原始DIF固定1%实现保持其现状，不再把它称作作者两位规则的等价公式；本轮无计算器、参数、配置、接口或消费者变更。选峰材料由管理员继续寻找，不主动索图或开展选峰实验。只更新原五文档并新增整理核验记录，来源/代码/原52及13/四周期sealed保护与资源、失败重核按算法§12.86；仅做文档/链接/哈希检查，不重跑原125工程测试或既有数值检查。

学习摘要已完成，270保护及原材料/已审代码/四周期结果保持；本轮没有新检测器或数值检查。记录见整理核验（原记录：`reports/xxm_course_learning_summary_20261021_01/README.md`），成果正文只从研究§8.145读取，后续收到选峰材料再限定下一步。

## 65 结构对应关系的课程说明（2026-10-21，仅文档）

按算法§12.87，新增第三份课程资料在研究§8.146整理。上升：较大周期顶部→一半周期底部；下降：较大周期底部→一半周期顶部；震荡按同周期对应理解。只记录原稿明确的日→120、120→60、60→30例子和方向，不把90→60或45支持编入现产品。

这是结构识别之后的跨周期对应标准，各周期的DIF峰选择/形成算法继续独立。可用于后续设计的记录包括环境及其依据、原结构方向/周期、对应方向/周期、课程依据与未决项；本次不修改合同或新增接口字段。环境的判别周期/数值定义未给，不绑定现趋势通道；“一半即可”不是排除其他周期或保证未来必有该信号的硬过滤。

原图是折线示意，没有软件指标读值；不登记真实行情标签或成绩。聊天文字归档与图文件SHA分开，播放器时间不强对齐转录时间。写入/保护/资源/失败续核按算法§12.87，仅五原文档和新报告；旧四周期结果/原52及13/产品/测试保持，无新模型执行，不因本课继续选峰研究或索材料。

资料及限定解释已归档，274保护与原完成结果保持；无新实现、数值模型或测试运行。来源见课程记录（原记录：`reports/xxm_structure_correspondence_lesson_20261021_01/README.md`），后续若采用须先补环境定义及独立验收，本次不进入编码。

## 66 两段盘口课程的比较范围（2026-10-21，仅学习与取证）

按算法§12.88，合并附件《纠错及综合应用》和聊天《盘口结构》。核心新依据是“可以隔一个、只能隔一个”，以及第二课23:37—23:51近峰不形成背离、隔峰形成背离的明确例子。整理相邻/跳一个同向峰的比较范围，逐对判断，不要求近峰先成立，不由此直接证明唯一最高DIF优先或精确软件锁峰。

盘口柱、MACD DIF、背后5/15分钟K线结构分别记录，共同原理用于形成待验证的比较模型，原始数值/周期/计算合同不互换。识别成立、级别评估和作者是否报点分开，原文深成指速度导致没给不能直接作上证无背离的阴性标签。当前产品及A/B/C不修改，旧52/13亦不重标。

新报告保存两份原话、精确片段、共同原理及差异、截图请求；不制作可执行计算器/测试夹具，不读正式源。边界/保护/资源和失败续核按算法§12.88。只索第一课36:31—36:50、第二课23:25—23:57的完整价线/柱峰画面，确认旧峰编号与比较两端后再判断DIF迁移，本轮提出后停止。

两完整稿/18段语境与解释已保存于合并学习记录（原记录：`reports/xxm_peak_comparison_lessons_20261021_01/README.md`），284保护及既有四周期结果保持；未执行模型、测试或改合同。待两处截图，不因没报点而重标无背离。

## 67 盘口选峰两图的资料核对（2026-10-21）

按算法§12.89，归档管理员对应请求1/2的两张原图，原文件和SHA/尺寸分别保存，原请求状态由新记录接续，不回写旧报告。第一图反色柱按原课语境理解，字幕“但是只能隔一个”与原词一致；不将两次同色放大误数成独立两峰，也不将手绘线算成异色柱。第二图绿色手绘遮挡部分极值，先保存三个待核位置及画面定性关系，不读取精确柱值或给时间标签。

当前无可执行实现变化，既有calculator.py/spec.py及A/B/C候选只做哈希保持检查，不把原1%或选峰次序称为本图已验证。图片可以帮助理解共同比较原理，不能直接替代DIF数值输入。仅更新原五文档与新报告，无配置/接口/行情读写、模型/工程测试；保护、性能预算、中断处理和验收按算法§12.89。

若三个比较位置不能独立辨清，只请管理员核第二张已有图中的对应，确认前不判定近对失败的具体原因，不索同图或DIF。研究§8.148记录本次解释及未决项。

两图原字节、来源及有限观察已归档；293保护及四周期已完成结果保持，无数值模型、测试或接口变化。两图记录（原记录：`reports/xxm_peak_comparison_images_20261021_01/README.md`）保存问题，后续以管理员确认接续，不将暂定峰位置写入测试预期。

## 68 三峰确认与同色段内两次下跌（2026-10-21，仅文档）

按算法§12.90，管理员红/橙/蓝圈分别确认为当前/近/隔峰，并用第二图说明价格创新低、绿角线未创新低。蓝橙无红柱分隔仍可分别看待，与第二课22:48—22:56原话相符；§67位置问题结束，旧报告保持原状态，新记录接续。

修正研究解释：本例的可比较峰不能一律按连续同色柱段数来编号。因此课程“可以隔一个”不能直接证明现max_refs=2的完整柱段合同；原课异色分隔表述也不删除或改成无条件可拆同色段。何时可以把同色段内两次下跌分别用于比较，尚无可执行阈值；保存价格波段位置、相应柱峰和是否异色分隔，之后再验证条件。

异色分隔按每一对判断：本图蓝/橙之间没有红柱，当前/橙与当前/蓝之间有红柱。旧峰之间没有异色，不能误写成当前与旧峰之间没有异色；本例与比较两端需要分隔并不直接冲突。应撤回“这三个峰必须各属独立色段”的推论，不撤回前课DIF分隔原话，也不把本例当同色段内任意两位置可背离的验收样本。即使只保留蓝峰可能得到相同最终结论，也未复现作者对近峰的那一步比较，二者不能混称。

本轮不调整calculator.py的符号分段、段内极值、参照历史或A/B/C选择，不将盘口柱样例转成DIF测试输入/预期，也不以图示替代两位DIF算术。只有资料与五原文档更新，保护、性能预算、读写/中断/验收按算法§12.90，无API/配置/依赖变化或数值模型执行。当前原话、两图及修正边界由新报告保存，研究§8.149为解释入口；后续开发需先解决分峰条件，另行完成方案与验证，不能把此次确认当代码授权。

原话、两图、四段已有课程语境及逐对比较已保存于圈图确认（原记录：`reports/xxm_peak_annotation_confirmation_20261021_01/README.md`）。301项保护和四周期结果保持，位置问题结束；未新增标签、数值模型或测试结果。

### 68.1 比较位置不另加未经证实的资格门槛

接算法§12.90.1。当前没有反例证明已辨认出的同色柱内两次下跌不能分别供后续比较。第一课两个位置不构成5分钟高点，不等于这些位置以后不能分别作为旧参照；此前把二者混在一起的提法撤回。

研究模型先保留已辨认的两次下跌，再在允许近/隔范围内逐对判断实际分隔及价格—指标关系，不新增仅因同色而排除的条件。自动怎样辨认下跌边界、取对应极值仍需核清；这是输入位置怎样取得的问题，不是凭空多设资格检查。本次只澄清文档，不改现有分段、参照合同或实现，不重跑检测器/测试，原报告保持。

## 69 先用局部转折找峰的研究候选（2026-10-21，仅方案）

接算法§12.91。基础方案先扫描已完成盘口柱：绿柱长度为负柱的绝对长度，只在绿色范围内用其增减找局部最长处；后续回收再放大可形成下一候选，不要求经过红柱。红柱方向对称，但本次未独立验证上升样例。连续同高合成一个区间，保留全部起止位置，不用平台中的任意一根反推作者取价。

峰位置在第一次已完成回收柱到来时才被确认，发生位置与确认时间分开；实时尾部候选可更新，不能读取未来柱或将确认回填为发生时就已知。该确认只是局部极值识别，不改钝化形成条件、DIF转折确认结构或课程取数，也不等同于等待未来才能登记当前钝化。

先不添加过滤、平滑或配置，只拟将输出全部候选与管理员三圈对应；有额外峰必须解释，不为拟合三圈静默过滤。相邻峰间的柱回收位置可以辅助整理，但不预设为价格下跌的唯一边界；价格低点与指标峰可不同根，对应窗口另核。本方法若用于DIF研究需作用于DIF序列，盘口柱与MACD柱不能代替DIF。

本次没有可执行实现、测试或行情读取，仅原五文档补充思路；保护、性能预算及中断/验收按算法§12.91，研究§8.150为说明入口。不声称原图已自动取数、三圈已通过程序验收或新规则已获产品采纳。

## 70 局部转折离线试验实现（2026-10-21）

对应算法§12.92及管理员继续试验授权，开发目标只为把原始局部转折变成可检查的逐点结果。CodeGraph已核继承/调用和旧测试，新代码不继承或接入XxmCalculator及A/B/C，不改其合同或状态。新文件均位于scripts/research/index_market/xxm与同主题tests；报告和只读复查notebook位于新试验目录。

### 70.1 逐点识别

local_extrema.py提供独立扫描器。输入为严格递增的位置/时间键、Decimal可表示的有限原值和completed布尔值。未完成输入不改变已完成状态；错误输入在变更状态前拒绝。保存上一同值平台起止、其值、之前非零增减方向及已消费数量。新值与平台相同仅延长平台；方向从增加变减少发MAX，从减少变增加发MIN。第一段缺左边邻值不作确认，末端缺右边邻值保留候选而不自动补事件。每次输出最多一处，旧输出不可变。

记录包含kind、value、峰平台起止位置、索引和confirmed_at/确认索引。峰确认只依赖本次及之前的已完成输入，不能读取未来；末端候选可更新。MAX/MIN是原数列数学转折，盘口筛选负值MIN/正值MAX表示柱长峰，DIF保留自身MAX/MIN。两者独立扫描，不用DIF截取值覆盖原序列，不在这一步产生DULL/STRUCTURE/CANCEL。

不设浮点相等容差、平滑、最小幅度、最少回收根数；源字符串用Decimal避免二进制误差凭空制造转折。批量数学复核独立按平台压缩后比较左右邻值实现，不调用逐点扫描器生成expected；关键测试仍使用独立字面峰值/时点。所有前缀核确认事件是否在其确认输入到来时出现；未来修改不能改变此前事件。

### 70.2 固定数据与报告

local_extrema_study.py只接受新输出目录，固定读取下列来源并核完整SHA，单文件≤100KB、合计≤300行：

| 文件 | 行数 | SHA256 |
| --- | --- | --- |
| reports/xxm_m120_reference_trace_20261020_01/source_window.json | 72 | 044f3b22b341f8b408bc0da430bbf4fe141e21d2aba92d8406020cf076754e18 |
| reports/xxm_same_day_m90_m120_20230301_20261020_01/m90_source_window.json | 63 | 95d09af15e5305383a4f88ecdad3d9a3a28135e090b5ed2cea55bc143ccd4797 |
| reports/xxm_feb25_m90_reference_evidence_20261021_01/source_projection.json | 63 | 82729d85e277215b54a425d721a1dc393253a3af27c0b46754d1332047917938 |

先核真实必需字段、字符串数值、时间与trade_date一致、重复/顺序、频率时点、日内完整与MACD=2*(DIF-DEA)，不重算MACD。第二文件无ts_code/freq字段，身份来自其原提取manifest，不能编造列；如其他文件显式字段与身份冲突则拒绝。日历完整性只复用旧检查边界，不声称本次独立补齐。保存全部DIF和柱转折、确认时点、候选尾端及同色段内数量，不按旧软件事件筛掉额外峰。

字面真实相邻例子至少覆盖：120分钟2023-02-02 11:30 DIF31.406350532954093大于前30.36598897743761及后31.1586753923134；90分钟2026-02-10 14:00柱16.82494919314902、2/10 15:00柱16.21976063733584、2/11 11:00柱16.320756935051918、2/11 14:00柱15.383612065674516显示两次柱峰。同期DIF继续上升，至2/12 15:00为11.1189143667998，2/13 11:00降为9.659975404064426；不得把柱峰时点当DIF峰。以上预期来自本步编码前读取的实际字面值，不由新函数反推。

### 70.3 图片与可靠性边界

peak_image_measurement.py独立读取原02_near_and_skipped_peak.png，延迟导入已存在Pillow；原图尺寸/SHA必须匹配。固定零轴附近及三圈覆盖的区域测绿柱，可测颜色与鲜绿手绘分别识别。固定三套邻近像素口径做敏感性比较，所有结果保存，不选最合意的一套；参数只属于图片测量，不是找峰过滤配置。若底部/顶部被手绘遮住、柱缺失或相邻柱不能清楚分开，保存censored/unknown，不插值、不用手画横线代替底值。无可靠完整序列就不能宣称自动找到了三峰，只提供可见部分和缺口。

测试输入包含已知像素颜色/遮挡的人工小图（图像合同反向检查）及真实图片最小运行，说明两者覆盖差异。原圈图用于独立位置对照，不能由新检测结果反画圈或反选ROI。Notebook作为试验产物只导入维护代码、重算三个小窗口并读取图片测量结果；无Jupyter依赖时用现有Python从上到下执行单元并保存执行输出/方式，不安装内核，不声称Jupyter服务已验证。

图片测量固定口径单独落档：MeasurementSpec只在peak_image_measurement.py定义，默认零轴y=833、x范围980—1385、y终点1000、绿色通道差15、起始探测14像素、允许2像素空隙；三组依次为(833,15)、(832,12)、(834,18)。绿色柱像素要求R/B在70—220、G≥100且比R/B至少大指定通道差；鲜绿手绘为G≥160、R/B<70，触及测量路径时标未知。蓝/橙/红区域x分别1045—1123、1124—1210、1270—1385，来自编码前圈图位置。消费者仅测量函数、试验入口及对应测试；参数执行时生效，完整写入image_measurement.json和代码SHA，无env/Settings/数据库/运营输入/前端开关。相邻柱组间距超中位数1.75倍记断点而不插值。以上是像素读取约定，不是行情峰过滤条件；三组测量必须全部交付。

### 70.4 资源、验证及失败处理

按算法§12.92预算，三小窗口依次处理，图片≤4M像素，最多100,000人工性能输入。报告分单元原子写入且新目录拒绝覆盖；失败保留已完成单元，另新批次重跑，有界计算无正式业务状态恢复。新主实现与测试记录CodeGraph依据、独立样本出处及当前代码SHA；旧301项加上轮全部11个完成文件保持，四周期原SHA不变。pytest原125不为本步重复全跑，按本步新模块/测试及必要直接边界运行；文档、相对链接、CLI、原始图/SHA和notebook执行同验。工程通过不证明作者一致，结论保留未知项及失败项，不迁移产品或新增调参。

### 70.5 执行结果与约束对账

| 约束 | 已有证据与范围 |
| --- | --- |
| 无换色要求、无幅度过滤、同高合并 | 52项新测试中的字面/正负镜像/微小回收/平台样本；3,280组整数序列独立批量数学对照通过 |
| 输入与因果时间 | 原子拒绝重复/倒序/非有限/错误completed，未完成点不推进；每一前缀及不同未来序列通过；198根真实数据402次前缀重放通过 |
| 真实合同与反向覆盖 | 三个固定SHA/198行、MACD误差≤6E-15；真实行改缺列/空/错类型/日期/频率/重复/恒等式应拒绝，正常价格变化不误拦；4个预先读定相邻峰位置通过 |
| 不隐藏额外峰 | 三窗口46个DIF转折、36柱长峰均保存，10/20可见同色段含多峰；未加阈值，未调整旧52/13 |
| 原图 | 三个固定像素口径均在三圈各找到一峰、蓝>红>橙；整ROI局部峰5/4/4、柱组25/18/25，说明全序列/根数仍不稳，不算作者精确数值验收 |
| 写入与保护 | 新目录拒绝/已有单元拒绝测试通过，完成记录另存completion.json；312旧文件/四周期保持，未触及产品、配置、接口或依赖 |
| 资源与复查 | 实测约0.221秒/81.8MiB，100k生成点约0.066秒；CLI帮助通过，notebook三个单元顺序执行成功，未运行Jupyter内核或安装依赖 |

当前交付的是局部极值试验，不是新DULL/STRUCTURE检测器。原DIF26.912→26.871的微小转折在课程两位读法下同为26，可能影响近/隔计数；对应价格与DIF峰时点不同，源又无high/low，不能直接用同根收盘认定价格资格。两者均已给真实行证据，未偷偷修正规则。

CodeGraph覆盖原计算器与A/B/C继承/调用、旧研究测试；新模块只由新研究入口/主题测试消费，无生产/API/前端影响。sync/status已完成。后续需人工确认的仍是作者怎样计额外峰、DIF两位取数应用次序及价格对应窗口，不影响本轮基础数学行为结论。详细结果见[试验报告](../../../../reports/xxm/conclusions/xxm_local_extrema_trial_20261021_01/README.md)、[复查notebook](../../../../reports/xxm/local-extrema/review.ipynb)及研究§8.151；旧125测试未重跑。

## 71. 每根先近后远回放与反向峰计数（对应算法§12.93）

本步已有管理员“先回测看看”的执行授权。目标、禁止项、性能和中断规则按原算法§12.93，不扩展为新结构状态机或产品迁移。编码前已读NearFirstCalculator的首次选择及其继承关系，旧入口带完整历史源读取与1%状态转换，不能直接执行；局部扫描器可复用，前次合同校验可直接复用。CodeGraph explore返回旧选择/继承/调用，局部模块需针对性核当前源，不凭摘要编码。无跨子系统契约变更，影响只有新研究模块及主题测试。

### 71.1 确切输入与读写

- 复用§70固定SHA的3个原始窗口，共198根，local_extrema_study.CASES/read_case负责原合同核验。
- reports/xxm_aug07_price_reference_evidence_20261021_01/old_segment_source_projection.json，SHA c343d17da79542ea7ea0b45eac577ae448985be0bc05c4316088883f184fabfa，真实对象含rows，共14根120分钟，2025/7/21—30；不能误当完整8/7窗口。
- reports/xxm_jun25_reference_evidence_20261021_01/saved_comparison.json，SHA 4d0dcb434bb2976796c12e36f53b005a8afc34ce0c2e759c457d533c6a81ad88；真实结构按m60/m90/m120分组，每组有activation、sourceBars、localNearest和localSelected。输入是已完成旧报告的浮点投影，共12个点，非完整连续分钟序列，不能在这些稀疏点上计算DIF转折或声称周期完整性。

写入只允许reports/xxm_near_first_review_<新批次>，每次新建且拒绝覆盖。单元分别为6月条件回放、4个原始窗口的柱峰计数、汇总及completion。保护原报告312项加上次全部完成产物、新源/旧研究代码和4周期SHA；不保存执行脚本到reports。

### 71.2 实现、配置及适用范围

near_first_review.py中quantize_dif采用Decimal截取左起首个非零的两位，保留正负及数量级，零映射零是本试验约定。choose_reference只接收已排序近/远的价格和DIF参考；TOP当前价大于对应旧价且当前DIF小于旧DIF，BOTTOM对称，等值按严格候选不成立；每个输入独立执行，不保存绑定。maxReferences=2、maxOppositePeaks=1由本模块单一Spec定义，运行时只读，无env/Settings/数据库/运营输入；消费者仅本模块回放及主题测试，报告记录实际值与代码SHA。

inspect_histogram使用LocalExtremaScanner识别完整H序列MAX>0为红柱峰、MIN<0为绿柱峰，逐对相邻同向峰计反向峰，保留所有峰位置及confirmed_at；按hist符号连续块统计同色超过2峰的位置。这里确认的是柱形位置/峰数，不赋予DIF参照资格，不替代价格波段划分。最高DIF位置与最长柱位置分别记录供核对，未确认“最高”含义和小起伏标准时禁止自动合并或发布合并成绩。

### 71.3 编码门禁及验收

| 硬要求 | 实现点 | 独立预期/反向检查 |
| --- | --- | --- |
| 每根重检，近不成立再远 | choose_reference/6月逐点回放 | 近成立、近价不成立但远成立、近DIF超过后远仍成立、两者不成立字面值；旧绑定不输入函数 |
| 最多两个旧参考 | Spec及选择函数 | 第3个才成立也不得选；近已成立不再计算远 |
| 两位DIF，非固定1% | quantize_dif | -8.086→-8.0、40.057→40、26.912/26.871→26、跨数量级及12.01→11.99字面例 |
| 反向峰0/1允许、2拒绝 | 柱峰相邻关系 | 已确认峰的字面位置/数量，正负镜像；同色多峰和整段多反向峰不能混同 |
| 不用未来确认 | 复用扫描器并检查所有前缀 | 已确认峰在附加未来后位置及确认时间不变；未确认尾部不计已确认峰 |
| 固定真实输入 | SHA/合同/投影核验 | 缺列、坏恒等式、重复时刻、未完成点拒绝；正常价格变化不误拦 |
| 结果范围不越界 | 报告与原标签保护 | 不生成正式DULL/STRUCTURE/CANCEL、收益或新软件标签；最高峰合并待定义 |

预算≤60秒/256MiB，212个原始行的全部前缀复查和12个稀疏点回放是固定小范围；单文件≤4MB、总≤16MB。单元完成后原子保存，最终completion才确认全部结束；失败保存已完成项，新目录重做，不覆盖旧报告或恢复正式数据。测试只跑新测试与直接复用局部扫描测试，文档完整性、链接、差异及历史SHA同验。工程检查与作者规则验证分别说明，不把12点当12份独立软件证据。


### 71.4 本轮验收与剩余边界

12个6月保存点独立重检，原值/两位选择及判断一致；收盘60无支持参考、90/120为远峰。212个原始行核合同及212次前缀；独立批量峰定义与逐点结果一致，32对反向峰0/1/2/3各20/6/3/3，21段中7段多于2峰、14段柱/DIF极值时刻不同。最高峰合并未执行，价格波段划分、6月反向峰拓扑和完整状态连续性未验收，不声称作者方法通过。

81项隔离及直接局部回归测试通过；前后两次试验只因摘要差异字段纠正而另存新批次，01历史不覆盖，02判断差异为0。新增配置消费者仅研究/主题测试，无运行时配置或消费者迁移。约0.121秒/44.2MiB，335历史保护，4周期SHA及旧52/13保持。CodeGraph核旧选择继承与当前代码，新实现不调用旧完整历史入口；sync/status同验，未改共享契约或产品依赖。报告见本轮条件回放（原记录：`reports/xxm_near_first_review_20261021_02/README.md`），原125测试本轮未重跑。

### 71.5 DIF最高确认后的合并对照（编码前补充）

按算法§12.93.2，新图与用户回答已归档，最高定义已解决；红组取最高DIF、绿组对称取最低。near_first_review.py增加merge_for_review(rows, shape)，只在当前前缀已有3个以上确认柱峰时用整组当前DIF极值代表；保留全部原始成员、代表时点、knownAt与组是否仍开放。其他组原位保留，合并列表只用来重新统计同向位置间反向位置数量，不将柱峰同根DIF当成合格指标峰，也不输出完整技术状态。Spec单一来源追加merge_more_than=2、merge_basis=DIF；无env/数据库/前端消费者。

“起伏不大”未定义，故这是全部合并的宽松对照，不是完整规则；不擅设百分比过滤。源和数据范围不变，图像仅保存原字节/人眼图证，无OCR数值或软件新标签。全历史读取、收益/胜率、产品及旧A/B/C仍禁止。每个前缀重新计算代表并保存该时点，不以最终组极值回写历史；开放组明确候选可更新，不能称稳定确认DIF峰。独立字面测试2/3峰、最长柱与最高DIF错位、镜像、确认时点和不改原输出后，运行新03批次并保护两次旧报告。

### 71.6 DIF极值合并对照验收

最高定义由管理员及定量结构（12）图证确认为DIF；merge_for_review和Spec已按§71.5实现。85项隔离/直接局部回归通过，其中2峰不合并、3峰确认后才合并、最长柱与DIF最高错位、绿组最低、开放组更新及不改旧快照都有字面例。独立批量方法重新核全部212个前缀代表/峰数，未调用待测函数生成预期。

7组取DIF极值后32对变16对，中间0/1/2反向位置各4/9/3对；3对仍拒绝，未获作者逐对确认。“起伏不大”未检查，输出显式smallFluctuationConditionEvaluated=false；列表也标completeDifReferencePool=false，不能用于完整技术事件。12点参考条件判断与前轮相同，原值/两位差异0。约0.138秒/52.8MiB，357历史保护与四周期保持。新报告04批次（原记录：`reports/xxm_near_first_review_20261021_04/README.md`），DIF图证（原记录：`reports/xxm_dif_peak_confirmation_20261021_01/README.md`）。CodeGraph及当前代码核研究/测试消费者，产品/API无依赖变化；原125未重跑。


<a id="xxm-next-round-lld"></a>
## 72. 下一轮四项工作的实现方向、输入与验收（2026-10-21，本轮只审计文档）

### 72.1 适用范围、当前代码与准备程度

本节落实[算法方案§12.94](../../../../docs/product/xxm-direction-algorithm-plan-v0.1.md#xxm-next-round-plan)，规则及U1—U7的唯一维护位置在该节；本节不另定义相反的算法。四项分别是完整离线计算、已有软件标记核对、时序/恢复/成本核查、差异报告与集成判断。最初两轮只更新文档，本次追加编码前只读合同与已有基础函数检查，范围见§72.13；未开发/回测新算法，不改API/CLI、Spec、预测、前端、数据库或Lake。

**本轮审计前不能直接开发完整算法；收盘价/逐峰不合并/首次严格比较/同一轮固定原参照等已定。** 价格区间、A/B限制位置、已有钝化等值保持及首次同根形成见方案§12.94.13和本节§72.15；100/101误提的卡点已撤回。计数对象、其余时序与输入继续补齐。工作规则与软件核验分开，不将已答项目继续标待定。

| 已查当前实现 | 对本阶段设计的约束 |
|---|---|
| `src/biz/services/wealth/market/index_detail_xxm/calculator.py`的`XxmCalculator.step` | 同段形成/纠错使用1%；换色可单独形成；还维护顶部/底部历史及等待参照。不能只覆盖选峰函数或改门槛数值，就称课程规则已实现 |
| 同目录`spec.py`、`types.py` | `MAIN_SPEC`为r2，参数不可任意变；输入使用float，`Wave`的价格极值与DIF极值分开。现`XxmBar.validate`不替代新入口的分钟端点/日历检查 |
| `calculator.py`的`snapshot/restore` | 恢复包含旧波段、参照、历史和等待状态；新候选不能接收r2快照。未来新候选也要核规则、代码和来源身份 |
| `scripts/research/index_market/xxm/local_extrema.py` | 可复用原值局部转折/平台和发生/确认时间；不含完整价格范围、参考池或状态规则 |
| 同目录`near_first_review.py` | `quantize_dif`可作实现依据，需独立字面预期复核；`choose_reference`只重检提供的两处，旧Spec也最多2参照且有合并，也不保存选中关系。与新方案首次逐峰检查/同一轮固定参照不同，只保留旧试验身份，不直接作为新完整选择器 |
| `calculator.py`的`_rescue_bottom_dull_reference` | 当前r2在已有底部钝化时可替换参照；这项行为只可留在r2/明确继承它的课程单项对照。完整新方案禁止继承或调用它替换本轮原峰，不能笼统把当前程序描述为全方向固定参照 |
| 同目录`acceptance.py:load_source`、`history_disappearance_screen.py:load_bars`、`scripts/research/index_market/tests/test_xxm_confirmed_cases.py` | 先读全CSV再留窗口；下一阶段不直接运行这些入口，不把少量输出当有界输入 |
| `src/biz/queries/wealth/market/index_detail_xxm/query_service.py`及`forecast_query_service.py` | 识别查询创建/恢复计算器；预测依赖识别及Spec/缓存。另有`src/biz/schemas/wealth/market/index_detail_xxm.py`严格身份、API及Wealth消费者，集成不能只替换一个函数 |

CodeGraph已核节点/Spec影响；调用方查询未完整返回，另用当前代码搜索补齐上述链路。无依赖调整，不改架构快照。路径与符号为本轮静态核对结果；以下新文件/函数均为拟实现，当前不存在，不称已落码。

### 72.2 工作一：拟实现位置与分步执行链

已有办法的限制：产品计算器将门槛、换色、参照和历史处理写在同一`step`中；旧A/B/C继承它仍保留1%，无法完成“只改课程确认方式”的核验。现近峰检查只返回条件，不能给完整事件；旧加载器又读全源。因此只在现有研究包增加离线实现，不另建产品入口或在`reports`维护执行脚本。

| 拟实现位置（均在`scripts/research/index_market/`下） | 拟符号与职责 | 可复用/禁止复用 |
|---|---|---|
| `xxm/course_rules.py` | `two_digit_dif(value)`、`compare_turn(previous,current,direction)`；返回两位值及方向，不返回软件真值 | 复用`near_first_review.quantize_dif`的算术含义，独立字面测试；不截取DEA/柱，不重算MACD |
| `xxm/dif_references.py` | `DifReferenceBuilder.step(bar)`记录全部不同DIF候选及可用时间；`select_reference(bar,candidates,policy)`只用于首次/新一轮，在允许范围内先近后远，首个严格成立即采用 | 可复用`LocalExtremaScanner`，不筛小峰/不合并/不截两峰；价格区间、计数和U7顺序需先具体化。活动原参照由计算器独立保存，不依靠候选列表持续保有该项 |
| `xxm/offline_replay.py` | `OfflineReviewSpec`、`OfflineXxmCalculator.step/snapshot/restore`、`replay_case`；保存每根状态/事件/历史记录 | r2由原计算器只作对照；课程单项版显式保留原参考/价格/历史政策。禁止调用旧`step`后删改输出假装改变了内部状态 |
| `xxm/software_observations.py` | `load_observations`、`resolve_corrections`、`compare_observation`；来源期望与模型输出分开读取 | 旧JSON只摘来源字段；不得把其中模型事件/id当期望 |
| `xxm/software_mark_review.py` | `precheck_manifest`、`read_saved_case`、`run_case`、`resume_run`、`finalize_run`；只读白名单窗口，组织各版本、写新报告 | 复用保存窗口读取的校验思路，不调用全CSV入口；不访问产品服务/DB/网络 |
| `tests/test_xxm_course_rules.py`、`tests/test_xxm_offline_replay.py`、`tests/test_xxm_software_mark_review.py` | 分别承担算术与确认、完整状态/恢复、观察/范围/落盘测试 | 不修改旧测试预期迎合新版本；单元测试不靠真实数据库或全历史 |

调用顺序：先校验规则决策及输入清单 → 读/校验原软件独立观察 → 逐案读取已获准且新旧共用的窗口 → r2对照 → 课程确认单项版 → 完整候选（仅已具备条件时） → 原软件/旧算法/新算法三方对照及额外事件 → 时序/恢复检查 → 分案完成 → 最终汇总。原观察与旧算法输出均不传入新计算器，也不能按某一日期或期待标记改变规则。

开发前再核同名文件是否已出现及当前调用方；如已有实现能满足本表，直接复用并更新本表，不能重复创建第二个入口。不得在本轮创建上述文件。

拟接口的输入/输出进一步限定为：`precheck_manifest(path) -> ReviewManifest`先返回通过校验的清单，失败不开始读行情；`read_saved_case(case) -> list[OfflineBar]`只读取该案白名单文件；`DifReferenceBuilder.step(bar) -> tuple[ReferenceCandidate, ...]`只新增当时已确认项并另保留尾候选；`OfflineXxmCalculator.step(bar) -> ReviewStep`返回本根前后状态、逐对比较、全部事件及历史变化；`compare_observation(observation, case_result) -> Comparison`只返回相容/冲突/资料不足与原因。`run_case(manifest, case_id)`保存一个完整案，`resume_run(output_path)`先核身份，`finalize_run(output_path)`只汇总已固定计划范围。以上均为研究包内部接口，不是已存在的类或产品合同。

### 72.3 单项版的具体转换与完整候选的停止条件

#### 72.3.1 两位确认与纠错

`two_digit_dif`按方案§12.94.2、§12.94.3：读取原数字文本为Decimal，按绝对值首位非零起保留两位后恢复符号/小数位置；相等不转折。零、负数与跨量级的完整行为列候选约定，不称所有边界均获软件验证。空值、布尔值、NaN/Infinity拒绝，不能补0。来源DIF/DEA/柱及原文同时保留。

课程单项版只改变形成/未换色纠错判断及换色单独确认路径。原资格判断继续使用r2同样的原始数值与取价处理，避免把精度/选峰变化混进单项结论；两位值只用于本步转折。原值转float的对照输入和两位所用原数字文本均记入输出，边界差异不能归咎于选峰。完整候选首次资格用两位DIF严格高低，相等继续下一允许参照；已有钝化固定原参照，两位等值保持，顶部严格高于原峰/底部严格低于原谷才因DIF突破消失，不能以原值突破或某候选资格失败取消原轮。结构形成后的纠错按U6/U7另判。

需明确继承的r2控制项包括：同色段至少2根；TOP首次激活检查当根DIF>0；历史参照先有近段价格资格再按DIF强弱择合格旧段；每段价格极值与DIF极值独立累计；原值DIF突破可取消、底部有参照救援/等待重激活；新同向信号和历史价格突破按当前代码顺序结束历史。底部不能凭对称想象补一个TOP的DIF符号条件。这些保留项逐一写入单项版政策清单及代码身份；完整候选是否保留须经U项决定，不能因单项版沿用而自动升级为作者规则。

上述继承只适用于r2/课程确认单项对照；完整新候选按U5固定原参照，明确排除`_rescue_bottom_dull_reference`的活动轮内替换逻辑。不能复用旧`step`后靠修改输出隐藏已经换峰的事实。

完整新方法的首次资格须按第二课05:18—06:20检查最新红柱/绿柱至少两根，计数不得从读取窗口或每个DIF小峰重置；零柱归属依U7补表。已采用的首次TOP修正及结构消失后再次钝化的价格修正，也必须列入完整方法回归；不沿用旧具体判断时须说明怎样保留已确认的修正结果，不能因重写入口遗漏。软件预期仍来自独立材料，不由r2输出生成。

| 本根开始状态/条件 | 单项版拟处理 | 必须输出的区别 |
|---|---|---|
| 已有DULL且原参照关系仍有效，两位DIF顶部下降/底部上升 | 当前完成根记录STRUCTURE；可以尚未换色 | 保存此前钝化依据、原参照、原始/两位DIF、确认时间 |
| 已有DULL但两位相等、无反向变化 | 保持；即便柱换色也不得仅据换色补形成 | 与r2的`color_flip`差异单列，不继续调用旧路径补发 |
| 已有STRUCTURE、未换色，两位DIF向原方向转回 | 记录一次结构纠错；背离仍成立则DULL，否则NONE/按旧等待政策 | “结构纠错”和“钝化是否消失”分别列，不改写旧形成点 |
| NONE或本根首次出现钝化 | 单项对照可按保留的旧条件激活DULL，不在同根自动接着形成 | 此限制仅保留单项对照身份；完整方法按本轮决定同根先DULL后STRUCTURE，不再列待定，也不冒称已核软件 |
| 当前有效参照被原值DIF突破、旧等待重激活或换色后历史处理 | 单项版按r2控制政策处理，原样列原因 | 这部分相容只说明该控制假设相容，不说明作者历史公式已证 |
| 未完成根/错误输入 | 入口拒绝，不改变已完成根状态 | 与盘中画面未知不混同 |

上表仅为课程单项对照。该对照在换色根同时转折时仍要求进入本根前已有钝化；完整方法允许本根首次成立钝化后同根形成，须分别保存两项依据和同一原参照。同根不得先由DIF、再由换色发两次结构形成。新形成用本根真正完成时间，不回填盘中闪烁时刻。

#### 72.3.2 逐根顺序、事件与历史

完整候选拟记录顺序：校验本根 → 更新本段价格/DIF和局部峰、确认当时可用旧峰 → 允许开始新一轮时，先排除与当前同一连续同色阶段的峰，确认旧同向色阶段与当前阶段间已有反色分隔 → 在允许范围先近后远检查价格和两位DIF，首个成立保存原参照及阶段/分隔依据并记录DULL → 检查本根两位DIF反向转折，符合可同根STRUCTURE → 处理已有活动记录的保持/形成/纠错或消失、换色及旧历史结束 → 保存状态和事件。已有活动记录不重选、不重新套首次资格；各实际状态分支及新旧轮同根次序依U6/U7补表。未完成根不推进，旧峰确认时间不晚于当前。

课程单项版的波段更新、历史价格锚点、等待和新同向结束旧记录依当前r2原顺序，逐一记录继承来源；上段完整候选顺序不授权重排r2对照。完整候选须列明同根“原参照失效/原轮结束/旧结构结束/新一轮钝化/新结构”的先后与可共存事件；顺序尚未写全时入口拒绝完整执行。U5已明确同一轮固定最初参照，不再试验活动轮内改用其他峰保持连续；仍须用独立软件标记核验这项工作规则，缺证据不能宣布改善。

普通状态继续用NONE/DULL/STRUCTURE，但**普通状态、结构曾经形成、历史有效性、图上文字可见性分别记录**。同根可有旧历史结束与新普通事件，输出为列表，不能限制总共只出一个；不把一个绿色字与所有CANCEL原因强行对应。每个事件保留该轮原参照，同一轮从钝化到形成/纠错均不改换，新一轮选择不覆盖旧事件；原结构按课程纠错条件处理，不能用另一个峰判断它消失，也不能以其他峰仍支持背离为由保留已需纠错的原结构。

管理员本轮明确：钝化后可能形成结构、结构消失后可再次钝化；新一轮同方向钝化接续后关注新一轮形成/消失，旧结构不再持续参与后续判断，原历史记录留存。新一轮须按实际状态变化记录，不能通过活动轮内换参照暗中产生。停止旧跟踪本身不补绿色事件，结构纠错而原参照钝化仍在也不强制经过NONE；同根顺序在U7写全。

上句“钝化仍在”不能省掉结构消失后再次钝化的价格检查。已有7/10底部材料（原记录：`reports/xxm_software_indicator_crosscheck_20261015/case_20260710_structure_disappearance_20261015.md`）与后续模拟明确结构消失当时没有新钝化，价格重新达到条件后才重出；完整方法必须覆盖这条正反例。不能因DIF相对原峰仍背离、或过去累计价格已突破，就直接自动回DULL；保存原参照可用的等待上下文与当前状态分开。顶部/其他未验证情形仍按U6补具体表，不把本例扩大为全部软件公式。

#### 72.3.3 完整DIF参考池的实现方向

候选记录至少包含DIF极值的原值/两位值、发生区间、确认时间、连续同色段编号、价格区间和独立收盘价极值时间。原始DIF不同局部转折分别保留；原值完全相等的平台记录一个峰区间及前/后端，当前尾峰单列未确认。两位显示相同不用于合并/删除原始峰，连续同色也不合并；新方法不再需要“小起伏”幅度门槛或合并后的候选列表。

“最多0/1反向峰”的作用位置已明确：限制两旧峰A、B之间，不是当前峰C到远峰A总间隔。连续异色柱段与其内部多个局部柱峰怎样计数仍须按U2核清；不能仅沿旧`inspect_histogram`/测试按局部柱峰数量实现。不得把A/B关系自行递推为无限回看，也不再要求管理员重复确认两端。

首次或新一轮选峰时，先按上述阶段条件排除当前段内候选，再将允许范围内的历史候选由近到远排序，另记录中间反向**柱峰**数及发生/确认时间，按此前最多0/1反向角线峰的范围规则检查。旧参照价格取其对应区间最高/最低close；从最新完成根向过去检查价格严格突破，DIF按方案U4用当前波段两位DIF峰值与旧参照DIF峰值严格比较，相等继续下一峰。价格与DIF极值的范围和时间分别保存，区间未定义时不能以本根DIF暗中代替波段峰值。首个成立即记录原参照、首次时点和当时价格/DIF依据，余下记“已有更近合格参照，未继续计算”，不能伪造失败。已有钝化/结构时不重复调用这一选择过程；后续价格回落低于旧峰不撤销此前突破，不以任何其他峰替换本轮参照。全部失败与池不完整分开。不得先按价格筛掉峰再重命名近峰；不得仅取前两个，也不把先成立改成全池取最大DIF。

旧峰DIF极值与收盘价极值分别记录。旧峰须来自与当前已有反色分隔的历史同向色阶段，首次价格/DIF比较前排除当前阶段内的小峰；这些小峰仍保存，供未来阶段使用。顶部旧红柱A/B→绿柱→新红柱C，底部镜像；A/B同色可分别参照，A/B间0/1限制单独处理。旧价从DIF峰后至首次反色柱前取最高/最低close，反色柱排除，区间结束后停止扩大；不同峰可同终点/同价但不合并。当前同段101→102不调用首次价格比较，不靠取价包含自己才判失败，不截前根制造成立。禁止未来数据回填，已有钝化的转折确认不要求再次等反色。

候选列表和当前活动原参照分开保存。新峰加入、旧候选移除或首次比较范围的计数变化，都不是原轮的失效条件；原轮未按明确条件结束时，仍读取选中时的原峰及价格/DIF依据。不能因为当前候选列表已不含该峰就取消、重选或用其他峰补齐。

已定收盘价、逐峰不合并、首次严格高低、固定原参照、A/B限制位置、已有钝化等值保持和首次同根形成不重复索决定；100/101提问撤回，不截两峰。完整候选仍须补计数对象/其余时序和足够前段，再核软件标记；本轮不开发或执行算法。

### 72.4 离线配置审计与身份

不增加env、Settings、数据库、运营输入或用户开关。唯一拟配置对象为`offline_replay.py:OfflineReviewSpec`，每次运行将完整值保存到新报告`run.json`，命令行仅接收已经审定的清单路径、全新输出路径和恢复路径，不开放随手改数值拟合标记。以下均为拟配置，不修改现`XxmSpec`合同。

| 配置/约束 | 默认值与来源 | 消费者/依赖/生效与测试 |
|---|---|---|
| `experiment`、规则决策清单、代码身份 | 无默认，必须显式指定r2对照/课程确认单项/完整候选；决策取方案§12.94及本节 | 入口、计算器、对照、恢复；改变须重建结果/状态，错身份拒绝 |
| `turn_policy`、`correction_policy` | r2对照读取`MAIN_SPEC`现值；课程单项按§72.3.1，无1%回退；完整候选沿用课程确认 | 计算器、规则测试；不同时保留另一产品开关 |
| `reference_policy`、`price_policy`、`dif_comparison_policy`、`equality_policy` | 单项对照记录旧政策；完整方法首次先检查跨反色分隔的同向色阶段，排除当前同段峰，再按允许范围先近后远检查严格收盘价/两位DIF。旧价为DIF峰后至反色柱前最高/最低close；已有钝化固定原参照、两位等值保持/严格越过才消失 | 阶段资格及其依据写入既有规则身份，无新env/用户开关；不以同段101→102激活，不每根重套首次资格，也不把首次阶段分隔误用于要求结构确认再等反色 |
| `max_opposite_peaks`、`merge_policy`及候选数量 | 0/1限制明确作用于旧峰A、B之间，不以C到A总间隔替代；计数对象依U2核清，不按变量名补含义。`merge_policy`不合并，无`max_references=2`；候选量由获准范围约束，不截第3峰。单项版保留旧Spec | 完整方法计数未明确时拒绝执行；A/B关系不自动等于无限搜索。旧柱峰计数测试及04合并不作新默认 |
| 同段/换色/历史/零柱/同时发生政策 | 单项版保留原身份；完整版按已定循环及新轮接续停止旧判断，首次同根先DULL后STRUCTURE、最终STRUCTURE；其余同根/零柱依U6/U7补表 | 同根双事件与相同原参照进入规则身份、计算、输出和恢复；不能缺省继承单项版“上根须有DULL”，也不重复发形成 |
| `source_manifest`、`observation_manifest` | 无默认；固定路径、SHA、schema、范围、完整性和覆盖观察 | 输入、对照、恢复；观察/源不能由计算器生成 |
| `max_cases`、`max_rows_per_case`、`max_input_bytes_per_case` | 拟单批8案、每案含前段≤1000行/1MiB，来源本节有界执行预算 | 入口/读入/最终检查；超限先修方案，不靠分批绕过全局读取审批 |
| `case_timeout_seconds`、`max_rss_mib`、恢复/最终检查限额、输出上限 | 拟60秒/256MiB；其余统一§72.9，不在脚本/测试另写默认 | 执行、恢复、验收；尚未实测，需正常变化不误拦与超限反例 |

完整配置、选定决策及引用依据作规范化JSON并计算SHA；代码身份用本次实际参与执行的文件SHA，不能只用Git commit（工作区可能有未提交变更）。输入、观察与两位规则身份共同进入案例结果/检查点。不得通过给旧Spec填课程新字段复用旧hash。

### 72.5 工作二的输入：已有来源清单与尚缺部分

#### 72.5.1 已有小型窗口与本次只读合同核验

以下SHA为已有代码/报告记录的固定身份。前两轮只核元数据，本次编码前只读了前4份白名单文件，实际212根/81879字节，SHA、字段/类型、排序唯一、日内端点和MACD代数误差通过；没有重算DIF/新信号、没有独立日历验收或证明历史足够。6月12点未在本次重做回放。逐文件合同和起止见`reports/xxm_plan_lld_audit_20261021_01/precode_inputs_03.json`；后续读入仍核大小与SHA，变化停止，不改expected迎合文件。

| 来源（仓库相对路径） | 已记录行数/SHA | 允许声称的范围与缺口 |
|---|---|---|
| `reports/xxm_m120_reference_trace_20261020_01/source_window.json` | 72；`044f3b22b341f8b408bc0da430bbf4fe141e21d2aba92d8406020cf076754e18` | 2023年120分钟局部轨迹；左边可能截断，不能直接初始化完整历史 |
| `reports/xxm_same_day_m90_m120_20230301_20261020_01/m90_source_window.json` | 63；`95d09af15e5305383a4f88ecdad3d9a3a28135e090b5ed2cea55bc143ccd4797` | 2023年90分钟同日对照；同样先核必要前段 |
| `reports/xxm_feb25_m90_reference_evidence_20261021_01/source_projection.json` | 63；`82729d85e277215b54a425d721a1dc393253a3af27c0b46754d1332047917938` | 2026年90分钟局部轨迹，不含所有旧结构起源 |
| `reports/xxm_aug07_price_reference_evidence_20261021_01/old_segment_source_projection.json` | 14；`c343d17da79542ea7ea0b45eac577ae448985be0bc05c4316088883f184fabfa` | 仅7/21—7/30旧峰，不能冒充8/7—15整段回放 |
| `reports/xxm_jun25_reference_evidence_20261021_01/saved_comparison.json` | 12个比较点；`4d0dcb434bb2976796c12e36f53b005a8afc34ce0c2e759c457d533c6a81ad88` | 既有模型提供的比较输入，不是完整连续K线/新模型参考池；仅作诊断 |

实际覆盖缺口已核清：72根120分钟只到2023/2/22，不能验3/1；2023年90分钟从2/1开始，没有1/30旧峰；2026年90分钟覆盖1/22—2/27，含2/25但历史状态仍须独立重建；8月14根是两旧正柱投影，不能拿作包含中间反向柱的连续输入。上述4文件没有日线/m60连续数据，而原52条包含13条日线和2条m60。12点是稀疏的旧比较池，不是完整新池。

原52/追加13仍须以最终确认去重/更正后逐案配源。清单要写观察id、范围、必要前段、行数/字段/版本/时区、SHA、容器/行路径、日历及左截断、支持事件或仅可见性。先查现有保存窗口，缺失范围明确后有界补齐；不能笼统宣称全部具备，不能由入口隐式读大文件或直接让管理员补视频。

| 已核真实容器 | 读取要求 |
|---|---|
| 前3份文件顶层为数组 | 明确按顶层数组读取，校验对应行字段/身份 |
| 8月文件顶层为对象，14行在`rows` | 保留`source/sha256/columns/rowCount`元数据，按`rows`解包并核14行；旧`near_first_review.run`已有此分支，不得套顶层数组读取或补造列 |

本次审计首次按统一数组读8月文件时被行数检查阻止，核对生产者后修正读取；原件不改、14行合同通过，不把审计读取假设错误写成源坏数据。缺`ts_code/freq`的窗口由已核源元数据声明身份，不能凭文件名或造字段通过；完整交易日检验仍用已有SSE日历另做必要范围核对。

#### 72.5.2 大文件只作来源定位，不能自动加载

`reports/xxm_source_audit_20261013_213852/manifest.json`记录分钟60/90/120各17260/12945/8630行；`reports/xxm_reference_rescue_r1_implementation_20261017/daily_2020_source_01/manifest.json`记录日线1643行。它们均超过本节单案限额，不进入新入口白名单，原`load_source`不得被间接调用。旧回归报告只证明当时执行，不能给新算法传旧状态或代替新输入核验。

需要前段时，先在每案清单列明确日期和字段、已有保存证据能否满足、预计读取量与方式。确需全局读取按仓库规则另获批准；一般继续研究授权或历史批准不能替代。后续补取若需DB/Lake/网络，应先修本节读写范围和预算，不由新入口隐式访问。已有SSE日历可核沪深A股，不另索SZSE日历。

#### 72.5.3 输入字段与足够性

复用窗口生产者字段：`trade_time/trade_date/close/macd_dif/macd_dea/macd/params_key/indicator_version`，有`ts_code/freq`则同样核对；当前数值字段按生产者原数字字符串读取，不静默补`high/low`。规范化离线输入保留原值、Shanghai时区、period和`completed`，不修改原件。日线日期为YYYY-MM-DD；分钟保留时刻，不截成日期。

核对000001.SH、MACD(12,26,9)及柱乘2、复权/计算版本与来源一致；`H=2*(DIF-DEA)`容差须沿源精度合同，现小窗口校验为`1e-10`，不能拿截图三位四舍五入代替源精度。重复、倒序、非有限值、非正价格、错标的/周期/日期、缺完整根拒绝；分钟60端点10:30/11:30/14:00/15:00，90端点11:00/14:00/15:00，120端点11:30/15:00。日历要求由已保存完整范围的SSE日历核所需交易日，缺日历不能自行补假交易日或把窗口内日数当日历验收。

每案分别判：指标是否已由连续源算好、算法所需前段是否足够、历史记录是否可重建、观察时间是否落在覆盖内。前者成立不能代替后三项。无同版本检查点时从获准前段起算；不得从局部首根NONE强行出发称全状态正确。旧模型参照仅能作为有标签的条件诊断输入，不能成为新模型自动产生的旧峰。

本轮决定以close为唯一取价字段，缺high/low不再是验证阻塞。新旧算法读取同一个固定文件/同一行范围、同一套已连续计算的DIF/DEA/柱及close；`inputs.json`保存输入身份与范围，逐版本结果声明共用输入，不允许各自重算MACD或换起点。旧内部状态/参照不作为新算法输入。原软件截图读数若与本地源不同，另列来源差异，不为某版本补改数值。

### 72.6 软件观察读取、更正与对照规则

固定原始来源：

- 原52条：`reports/xxm_top_daily_ambiguity_20261017_01/run_01/observations.json`，SHA `2d6cb9f58514f8e1a3dad0436fdd5c7e2627bb174dc16be377e3ecf61ff07e12`，字段`case/time/expected/confidence/source/period/endpoint`，20 direct/32 mapped。`source`可能只是编号，必须解析到具体原图/原话，不能默认都有可查图片。
- 追加13条：`reports/xxm_top_return_reference_20261021_01/summary.json`的`laterObservations`，文件SHA `783f056dfd71672c65d26a01f0eb5457bab38dee8b1759746d76f615545b218e`。仅摘`label/period/time/type/expectedVisible/basis`等来源含义，`strong/near/reselect`及内部事件/参照id不作期望。
- 上述清单未完整涵盖的6月、8月、5月更正及课程图，按方案§12.94.5逐一增加来源引用；不改原清单。5/9以`reports/xxm_may9_m120_time_price_audit_20261021_01/screen_confirmation_20261021/README.md`的后续确认取代早期待确认理解；6/12以最终14:00确认取代15:00，均保留更正链。

拟`observations.json`逐项字段：`observation_id/source_refs/raw_text/period/direction/observation_kind/expected/precision/window_start/window_end/confidence/supersedes/episode_id/used_for_rule_adjustment`。来源引用含原件路径/SHA、视频时间或用户确认出处；未知方向/根/范围明确unknown，不按模型补齐。`observation_kind`区分准确形成/消失时点、收盘状态、画面文字可见/不可见；画面未知拍摄时刻不得设成15:00。

去重键用同一观察主张（来源、更正链、周期、方向、类型及范围），不是仅按日期。重复原图合并引用，同一日期不同周期/事件保留；被取代的记录保留但不双计评分。去重前后数量、direct/mapped/日期/画面级数量、同一行情组数分别报告，不能报“65个独立案例”。

`compare_observation`只在证据精度内比较：

| 原观察 | 可以比较 | 禁止的推论 |
|---|---|---|
| 准确某根事件 | 同周期/方向/类型与该根时间 | 用附近另一根命中替代，或因模型一致升级mapped |
| 当日收盘仍钝化 | 最后完成根状态及该背离依据是否持续 | 强制当天新发DULL事件、据此反推首次根 |
| 某张图可见/不见某字 | 该画面位置与时间范围的显示观察；先有事件到显示的独立对应资料 | 不见字就断言内部状态NONE/全日从无事件；将历史旧字当当天新事件 |
| 讲解当时消失、确切根未知 | 在已知讲解范围保留方向和事实；时间不足标资料不足 | 6/25的60分钟直接变成收盘无钝化；将“可能收盘前”设成确切时刻 |

无软件内部参照/价格锚点资料时，即使字样和事件相容，也不能写内部id已验证。模型结果与软件预期存不同字段，对照器不得调用待测选择器生成expected。

### 72.7 每案输出和整轮交付

拟输出目录由调用方显式给全新路径，不覆盖旧报告；至少包括：

| 文件 | 内容与关键字段 |
|---|---|
| `run.json`、`inputs.json`、`observations.json` | 完整离线配置/代码/源/观察身份；固定范围和依据；读取许可及缺口 |
| 每案`points.jsonl` | 每根时间、completed、原始/两位DIF、原始价格/柱、计算前后普通状态；候选发生/确认时间、各价格区间；首次逐对条件、固定原参照及首次依据；原轮结束/新轮开始分别记录，同一轮不得变更参照 |
| 每案`events.jsonl` | 全部形成/纠错/钝化/消失及历史结束；事件时间、方向、原因、当时参照、原结构id及原价格锚点；旧事件不可回写 |
| 每案`comparison.json` | 主表原软件独立预期/精度/来源、旧算法、新算法、输入一致性及改善/退化/保持/两者均冲突/资料不足；确认单项版另列解释原因；无材料的额外事件单列待核 |
| 每案`checkpoint.json`、`case_complete.json` | 同版本可恢复状态及已处理输入前缀身份；前者不代表案例完成，后者含结果文件SHA/数量/范围和检查结果 |
| 整轮`summary.json`、`README.md`、`completion.json` | 版本间差异、覆盖/缺失/额外事件、时间/恢复/成本检查、下一最小材料需求；只有全部计划案例及最终检查完成才能有completion |

字段为离线内部记录，不新增现产品DTO。每案可声明只完成r2或课程单项，完整候选列“未执行/阻塞”；不能用空事件列表表示未执行后计为无冲突。未覆盖日期不算负样本。课程原话、人工算术、隔离测试、真实软件事件核对分别计数。

新候选检查点须保存：schema版本、完整规则/代码/观察/输入清单hash，标的/周期/来源身份，已处理行数、末根时间及输入前缀hash，上一根原值/两位值，当前柱色及各峰价格窗口的起止/是否结束/独立极值，DIF/柱形扫描器的已确认与尾候选状态，候选池及各自可用时间、候选/当前连续同色阶段编号、当时已发生的反色分隔记录，当前普通状态/固定原参照/钝化起点及首次价格/DIF依据，结构原参照/形成时间/价格锚点，全部仍在跟踪的历史结构和等待参照状态，以及各输出文件已提交行数/hash、事件计数和同根事件序号。固定原参照及选中时依据必须独立保存完整内容，不能只存候选列表中的位置，也不能用后来最终价格覆盖首次快照。恢复必须沿用同一轮原参照；缺失或身份不符拒绝，不重新选择补齐。首次同根DULL/STRUCTURE及其最终状态须完整保存，不得只存最后一个事件或最后两个峰声称已恢复全部历史。

事件id由规则身份、来源身份、周期、方向、事件时刻及同根稳定序号确定，不用随机数或运行开始时间；同一输入重做必须一致。恢复先验证检查点对应的已提交输出前缀，只从下一未处理根追加；不匹配则拒绝，不能吞错或重复追加。原子文件替换的检查点只能指向已落盘的输出前缀，不能指向尚在内存中的事件。

### 72.8 工作三：独立测试与时间检查映射

以下为未来测试设计，本轮不创建或执行测试。预期来自已确认规则、独立字面例与来源观察，不由待测helper生成。新测试放研究包现有`tests`目录，原产品/历史夹具不改。

| 验证内容/对应规则 | 必要的正向及反向例 | 拟测试文件 |
|---|---|---|
| 两位截取与1%非等价，§12.94.2 | -8.086→-8.0、40.057→40；12.01→11.99应两位下降但不足1%；12.99→12.80虽超1%两位未变；底部负数镜像；等值、跨量级、0及非法值 | `test_xxm_course_rules.py` |
| 有钝化才形成，§72.3.1 | 已有效DULL时反向形成；NONE且本根也不满足钝化者不形成；完整版首次同根满足钝化和转折时依次DULL/STRUCTURE、同一原参照、最终STRUCTURE；缺任一条件不连发。单项对照仍不首次同根形成；两位等值不重复，未完成根拒绝，换色不独立/重复形成 | 同上与`test_xxm_offline_replay.py` |
| 同段纠错及历史，U5已定、U6/U7顺序补齐后 | 纠错但钝化仍在、纠错且背离已失效、再次形成均使用原参照；旧事件不可回写；同根旧历史结束与新信号均保存；不造24根到期 | `test_xxm_offline_replay.py` |
| DIF池/收盘价/顺序，计数对象固定后 | 同段价格101→102、局部DIF峰也在首次比较前排除；旧红→绿→新红及底部镜像可进入检查，再分别满足/不满足价格与DIF条件。旧同色A/B不合并；已知分隔不可由未来补齐。反色前末根计入/首根反色排除，不回填；A/B限制两端与当前阶段资格分开，第1峰即停、第3峰成立、相等继续、池缺失/全失败分开 | 同上 |
| 已有钝化等值及严格突破，U4 | 固定顶部原峰26.92读26，当前26.50/26.93仍26保持，当前27才因DIF突破消失；首次等26不成立，继续后峰。底部镜像：原谷-8.086读-8.0，当前-8.099仍-8.0不因原值突破消失，-8.1才严格跌破；结构纠错不可被该保持规则跳过 | `test_xxm_course_rules.py`与`test_xxm_offline_replay.py`；以上独立字面例尚未执行，不当软件案例 |
| 同一轮固定原参照及价格回落，U5 | 首次近峰失败再选远峰后，较近其他峰被突破不得报原轮消失；原参照失效不得换其他峰保原轮连续；价格已突破后回落而DIF未转保持、DIF按规则转折形成、原轮结束后新一轮重新选择。新候选加入/原峰被移出候选列表、结构形成/纠错及保存恢复后原参照均不变；原记录缺失须拒绝，不能重选补齐 | 同上；预期来自管理员明确决定，软件对照仍需独立材料，不以自造例通过当软件相容 |
| 已有课程条件和旧问题回归，U6 | 最新同色柱1根拒绝、2根且其余资格成立可检查；两种输入从足够前段计数。7/10结构消失时未再次钝化、7/13模拟价格重新满足后出现；不能用过去累计突破重出。首次TOP已采用修正也纳入，独立预期与r2输出分开 | 同上及`test_xxm_software_mark_review.py`；本轮只写要求，不执行测试或重跑原案例 |
| 因果时间 | 后续完成根才确认旧峰，确认前不能参照；每个前缀从相同初始状态独立算，与整段该前缀的已确认输出比较；尾峰不倒填 | 同上；expected选用可手算小序列与已固定时间规则 |
| 恢复与防错 | 连续、分批、恢复一致；重复/倒序/错端点/缺字段/错hash拒绝；新旧算法快照互拒；正常跨交易日、午休/节假日按日历不会误拦 | 同上与`test_xxm_software_mark_review.py` |
| 观察精度、三方核对与读入限制 | 6/12更正链、5/9画面与收盘未知、日期无字不作全段否定；混入旧模型expected拒绝；旧错新对/旧对新错均能报告；新旧同源同范围，换DIF/截窗重算拒绝；表外/超限文件及旧全CSV入口不得调用，正常白名单小窗可读 | `test_xxm_software_mark_review.py` |
| 落盘与取消 | 文件写一半、中断于检查点前后、已完成案保留、恢复后无重复、缺最终检查不写completion；输出/身份/读入超限拒绝且正常小案通过 | 同上 |

真实软件观察的预期与数学/工程测试分开。旧85项/212前缀是旧局部实验成绩，不能在本轮或新版本里直接复用为通过。最后按来源足够的案例做最小真实离线链路（读取→计算→对照→落盘→恢复读回）；未做这一项只能报隔离测试，不能报真实案例集成通过。

### 72.9 分案执行、失败恢复与性能预算

只读明确清单、仅写新报告目录。每批最多8案、每案含前段≤1000行/1MiB，常驻只保留一案；预先限制每案输出≤16MiB，超限停止，不截掉额外事件。上述限额为拟定、未经本轮实测；若完整重建需要更长前段，先调整方案/读取范围再执行，不压缩输入使结果看似完成。

| 范围 | 拟上限（包含的步骤） | 超限与中断处理 |
|---|---|---|
| 每案 | ≤60秒、进程峰值RSS≤256MiB；包括读入/hash、各选定版本计算、必要时序/续算检查、序列化、文件hash和案完成写入 | 超限标失败，保留已完成案；未完成案不生成完成标志。内存平台单位先统一，不能漏计执行中峰值 |
| 一次恢复审计 | ≤30秒；只读清单、配置/代码hash、输入前缀和已完成案产物hash，不重扫表外源 | 身份不一致拒绝，不降级沿用旧状态；超限不跳过核验 |
| 整批最终检查 | ≤60秒；核≤8案的完成文件/数量/SHA、所有计划观察结果、额外事件和保护范围，生成汇总与最终完成文件 | 缺案/不一致/资料不足不能声称完整验证通过；完成执行与算法通过分别列 |
| 整批总计 | 正常≤8×60+60=540秒；一次中断的恢复审计加至多一案重做≤30+60，合计≤630秒 | 多次中断分别记录，不声称无限重试仍在该预算；预算不足先停并修改设计 |

性能核验和逐前缀计算在每案60秒内，不因其为测试就排除；可用预先固定的小序列核工程性质，但真实案例的未做项要列缺口，不能因超时改成自造例后声称真实案通过。计时分别列读入/计算/前缀/恢复/输出/最终检查，数据量、输出量同时记录；当前无实测成绩。

每案完成文件先写同目录临时文件，校验后用`os.replace`原子落为正式名；一个案例全部产物完成才写`case_complete.json`，整批最后写`completion.json`。它是执行完成记录，不代表相容性通过。中断保留完整案和可校验检查点，半文件不视为完成；恢复核配置/代码/观察/原始输入前缀身份，缺可用检查点时只重做该未完成案，计入上表。不得用r2快照初始化课程版/完整候选，也不能以新全文件hash变化为由忽略源前缀被改。

新实现每处理一根/每写一个产物检查取消；单个不可分割步骤预计超30秒则拆分。运行中按阶段/当前案/完成案数/总案数/当前处理根数/最后更新时间更新，至少每5秒一次，最长不超过30秒；进度不可把心跳当处理完成，不给虚构ETA。检查只读产品/旧报告保护清单，不重新hash整份行情CSV来“保护旧结果”。

### 72.10 工作四：报告、集成影响与停止条件

差异按方案§12.94.8逐条解释，不用“全部通过N项”代替真实结果。主表以原徐小明视频/截图/最终确认作独立预期，旧算法、新算法共用DIF逐条对照；分别报告旧错新对、旧对新错、均相容、均冲突或资料不足，不用命中总数掩盖退化。确认单项版只解释原因，不能替换原软件这一方。报告同时给每个版本是否执行、证据缺口及内部参照是否未知，不能因未运行完整版而填相容。额外事件待核且可能影响拟交付行为时，不能过集成门槛。先冻结规则，再取未参与规则调整的新材料；已有材料先做回归，不重复索8/8等已供图。

符合方案的全部门槛后，才另行设计产品改动：`XxmSpec`版本/身份、计算/历史/保存恢复、识别与预测query/cache、严格schema/API、Wealth适配和显示、对应测试与迁移。届时按CodeGraph加当前消费者审计确认范围；未经明确批准不改现API/CLI/合同，不在页面补计算，不将研究包带入产品运行，不新增用户参数。已有当前产品性能要求不能被本节离线60秒预算替代。

具体停止点：U项未固定而请求完整候选、观察来源不独立/精度不足、必要前段缺失、超出读取/写入范围、身份或原件变化、预算超限、未解释软件冲突。停止后报告发生在哪一步、缺什么、下一最小动作；不删负例、不调参试到一致，不因停止而宣称任务已验收。缺资料时向管理员提出针对该问题的最少图/讲稿时间段，本轮不启动取证或算法试验。

### 72.11 本轮审计结论与后续顺序

本轮仅修改两份原文档的当前入口和本节/算法§12.94，并增加审计记录（原记录：`reports/xxm_plan_lld_audit_20261021_01/README.md`）。四项已有对应的实现位置、输入/输出、失败恢复、预算和验收方向；未定算法、来源前段不足仍明确列为完整候选的开工条件，不标成已解决。

下一轮补U2计数对象、U6/U7其余时序和案例输入清单，再核软件标记；U1的100/101提问撤回。已定价格范围、A/B位置、钝化等值保持、首次同根形成及此前收盘价/不合并/固定参照不重复索决定。先完善该步设计，再按有界范围试验；成果交付后才讨论集成，本轮不执行。

### 72.12 管理员批注落实与待回测边界（2026-10-21）

本节为2026-10-21时点记录；其中换参照连续保留假设已被§72.14及方案§12.94.12取代，不再作为当前实现方向。

本节对应算法§12.94.10及11条决定记录（原记录：`reports/xxm_plan_lld_audit_20261021_01/decision_update_20261021_02.md`）。收盘价极值和DIF极值分别保存；所有不同DIF峰在允许范围内由近到远检查，首个严格成立即采用；撤回合并和幅度筛选，也不复用旧两峰截断。相等继续后峰，不能直接宣布全部钝化/旧结构消失。

换参照后钝化连续保留是管理员同意先试、先回测的假设，不是已经验证的产品规则。先用相同DIF输入作原软件/旧算法/新方法三方核对，再判断是否采用；当前产品不因此改变。钝化形成/结构形成/消失/再次钝化可循环，新一轮接续后旧结构停止判断但历史留存，普通换参照不自动创建新一轮。

软件视频不足与选定行情片段不足分别列。优先复用已有6/24—25、8/7—8等资料，行情前段先由开发侧核查；只有具体分歧缺独立标记时再给管理员明确日期/周期/要核字样。本轮只更新两份文档及决定记录，不执行回测、开发或行情读取。

### 72.13 再次编码前核验的结论与门槛（2026-10-21）

本节保留当时核验和提问的历史；“当前价待答复”和“换参照连续性先回测”的现行处理已由§72.14更正，不再要求管理员对2/25回落例选择A/B。

管理员追加编码前核验后，本次做了§72.5的4份小样本合同/覆盖检查，以及已有两位取数10个字面例、原始微峰保留/后根确认、旧函数第三峰限制的小例。结果见再次审计（原记录：`reports/xxm_plan_lld_audit_20261021_01/precode_audit_03.md`）。这些是既有基础能力与输入检查，不是新完整算法/软件案例回测；先前各轮“只文档、未读行情”按原时点保留。

| 编码前事项 | 当前状态与下一动作 |
|---|---|
| 已定规则 | 收盘价字段、旧峰最高/最低close、不同峰不合并、先近后远首个成立、严格等号、同套DIF/三方对照已确定，不重复索决定 |
| 当前价格 | 上轮扩大为累计极值；已给2/25本根4147.2305与累计4160.4526对远峰4157.9844的差异，向管理员询问。答复前不按累计价实现；建议本根close先作候选核查 |
| 每峰价格区间 | U1尚缺左右端点/冻结时点，不能共享整段同色极值。开发侧先给具体候选/差异例，不靠命名让编码者补规则 |
| 比较范围/同根顺序 | 0/1反向柱峰规则不重开，但计数端点、零柱、尾峰确认本根资格、同根旧消失/新钝化/形成必须补成输入/顺序/预期表 |
| 换参照连续性 | 6/25收盘黄不区分连续与途中失效后重出；先定位两路径分歧时点，再找独立软件证据。不能宣布已回测通过，不重复索相同收盘图 |
| 独立观察及输入 | 按§72.5的具体覆盖缺口配每案；52/13原JSON不能当已更正/去重的执行清单。缺独立观察、必要前段或日历时结果资料不足 |
| 复用现代码/测试 | 原`choose_reference`确实不查第三峰，原测试也要求此行为，合并测试属旧试验；新逐峰方法须独立字面预期，不能拿旧通过数当新验收或改旧报告 |

当前完整研究方法和产品仍未获编码就绪结论。先完成当前价澄清、逐峰价格区间/同根表、最小独立观察/输入清单，再进入有界离线验证；换参照假设先验证后采用。已核基础函数可以复用，但不证明全链正确。本次没有新增算法源码、修改旧测试、全CSV/DB/Lake/网络访问或产品变更。

<a id="xxm-fixed-reference-lld"></a>
### 72.14 同一轮原参照的保存、判断与验收（2026-10-22）

本节固定原参照继续有效；后续价格区间、等值退出和首次同根形成的落实见§72.15，对应方案§12.94.13。

采用方案§12.94.12的管理员最新明确决定：首次找参照与后续跟踪分开。第一次可在允许范围内先近后远逐个检查；一旦形成钝化，本轮保持、结构形成、消失及形成后的纠错均围绕原参照判断，不再每根重选。旧“换参照连续保留”仅为历史试验方向，不进入完整候选。

实现方向同步为：首次选中时保存原峰身份/当时价格区间及DIF值、钝化起点、首次价格突破及DIF比较依据；后续完成根读取这些记录，按原参照判保持、结构形成或失效。产生结构时继续携带同一原参照；保存/恢复也不得另选。原轮结束及新一轮选择分别记录，具体同根先后仍须依U6/U7写成表。

这份原参照记录与候选列表分开保存：未达到原轮明确的结束条件时，候选更新/移除和范围计数变化不自动结束原轮；保存恢复缺原记录或身份不符须拒绝，不另选补齐。完整新方案禁止继承r2底部救援换参照；该旧行为只作为r2/单项对照，不能在新方案中作为兜底。

| 场景 | 要检查什么 | 禁止的处理 |
|---|---|---|
| 已与旧峰形成顶部钝化，最新收盘回落到旧峰之下，DIF未达到形成/失效条件 | 保持原轮钝化和原参照，保留此前突破事实 | 重新用本根价格资格失败取消；以回落本身确认顶部结构 |
| 上述钝化有效，DIF按课程两位取数规则向下转折，当前根完成 | 以原参照确认顶部结构 | 等换色才首次确认；改拿近峰给该结构判资格 |
| 原参照达到既定失效条件 | 按原轮记录失效及原因；新一轮是否同根允许另依U7处理 | 换用另一个仍支持背离的峰，伪装原轮始终有效 |
| 较近其他峰先被突破，原参照仍有效 | 仍按原参照检查保持或形成条件 | 以较近其他峰突破宣布远峰钝化消失 |
| 新峰加入、候选范围变化或原峰已不在当前候选列表，原轮未达到结束条件 | 独立保存的原峰继续参与判断；保存恢复一致 | 因列表变化丢掉活动原峰，或用新候选替代 |

保持钝化、形成结构、钝化消失三种去向仅用于当前处于钝化的阶段；结构形成后的保持/纠错/消失按原课程及U6/U7另判，原参照不变。顶部价格下跌不等于结构自动形成，底部反之；没有达到形成或失效条件时保持钝化。已有钝化两位等值保持、严格越过原参照才因DIF突破消失，以及首次同根形成，均已由§72.15落实；其余顺序依U6/U7补表。不能将首次资格失败当作后续失效条件，也不据2/25例补造软件首次时点/内部参照。

本次仅改两份方案/LLD，补充的是保存与判断方向及独立测试要求，未创建算法或测试、未运行回测；仍需完善逐峰价格区间、范围计数/同根表及必要独立观察/输入后，才能进入原定下一阶段。

再次审计的逐条对应及修订检查见原参照复审（原记录：`reports/xxm_plan_lld_audit_20261021_01/reference_tracking_audit_04.md`）；本LLD只落实方案§12.94.12，不另定义新的参照规则。

<a id="xxm-four-decisions-lld"></a>
### 72.15 四条澄清及首次比较阶段条件的更正（2026-10-22）

本节仅落实[方案§12.94.13](../../../../docs/product/xxm-direction-algorithm-plan-v0.1.md#xxm-four-decisions)，不另造规则。采用决定仍待软件验证；本轮仅改文档，现r2、旧实验和测试不变。

| 方案决定/范围 | 拟实现位置与保存内容 | 独立检查与停止条件 |
|---|---|---|
| 首次比较须跨反色分隔 | `dif_references.py`首次选择先检查旧峰/当前的连续同色阶段及已发生分隔，排除当前段内小峰，再检查价格/DIF；原局部峰仍保存供未来使用 | 顶部旧红→绿→新红、底部旧绿→红→新绿；同段101→102不进入比较。阶段资格与A/B之间0/1限制分开，已有钝化不每根重选 |
| DIF峰出现后到反色柱前取最高/最低close | `dif_references.py`保存DIF发生/确认、连续同色阶段、价格起止/极值及区间结束；反色柱结束旧区间且不计入旧价 | 同段101→102不进入首次比较，只更新当前段；旧同色A/B可供反色后新C使用。开发侧补边界例，禁止未来价回填 |
| 0/1限制在旧峰A和B之间 | `dif_references.py`候选间保存明确两端和反向角线记录，首次选择按已定先近后远 | A→反向→B→反向→C不拿C到A总间隔替代。计数对象/搜索范围未明不得继承旧局部柱峰测试或自动无限回看 |
| 已有钝化的两位DIF等值保持 | `course_rules.py`分开首次严格资格与活动钝化退出，后者顶部两位>原峰、底部两位<原谷才因DIF突破退出；`offline_replay.py`始终读取本轮固定原参照 | 26.92/26.93均26，虽原值越过也不取消；27越过才取消。首次等值不创建，两位同值不产生转折，已有结构纠错继续单独判 |
| 首次钝化和转折同根 | `offline_replay.py`先保存DULL依据，再核形成条件，输出同完成时间DULL、STRUCTURE，稳定序号、同一原参照、最终STRUCTURE；原子保存完整事件和状态 | 无初始DULL但本根也无有效背离者不能仅凭转折形成；两项同根成立则不得拖至下一根。换色不重复发STRUCTURE；连续/分批/恢复结果一致 |

首次资格必须先检查阶段关系：顶部旧红柱→绿柱→新红柱，底部反之。同一连续同色阶段内的小峰在价格/DIF比较前排除，101换成102也不会激活；不采用07的“先比较、自然失败”。局部峰保存供未来阶段使用，历史同色A/B仍可被新C按顺序比较。首次分隔资格与已有钝化跟踪分开：后者固定原参照、两位DIF转折可形成结构，不要求钝化后再等反色或穿越DEA；同根新轮及零柱/平台按U6/U7补表。

最新更正依据见记录08（原记录：`reports/xxm_plan_lld_audit_20261021_01/colour_stage_comparison_08.md`）；06/07原提问及检查按历史保留，其中“同段先比较再失败”和未分清首次分隔/结构确认的说法均不作当前实现依据。

本轮更新的政策必须进入§72.4规则身份，价格范围和同根双事件进入§72.7保存恢复记录，独立正反例进入§72.8。不修改现`XxmSpec`、API/DTO或旧试验预期，不把两份文档一致性检查说成新算法通过。原始软件标记仍为三方核对独立预期，下一步先补尚存设计/输入，再按原预算有界核验。
