# 上证徐小明研究指标 V0.1 实施方案与 LLD

日期：2026-10-14。状态：**用户已批准规则、Figma、完整历史读取调整及仅指数详情页的 1280／1440px 适配；M0/M1/M2 技术验收完成，10 月 14 日标记视觉修订已同步四周期并通过技术验收，M3 等用户复看；未部署。**

代码级设计及实施（2026-10-16）：**用户已确认§17，B组唯一h1内核、查询／恢复／DTO及Wealth消费者已实施。冻结、正式预算及整页／双标签306请求全部通过，后端209项／前端1179项及类型／构建通过，交付见§18及[实施报告](/Users/congming/github/goldenshare/reports/xxm_bottom_history_h1_implementation_20261016/README.md)。§16工作规则与B1旧证据保留；页面由用户验收，未提交／部署。**

最新状态（2026-10-16）：**B组原三日线漏报及两处120分钟映射已在正式h1内核和API中补齐；A组同段问题继续待审。§16.10及其前文的“未实现”是B1研究时点记录，以§18本次交付为准。**

此前方案修订记录（2026-10-16）：**底部同段结构消失、参照保留、重新钝化及预测的LLD见§15，待用户确认，产品代码未修改。§1—§14保留现行实现和历史验收，§15拟议合同尚未生效。原三处跨柱色底部消失漏报及两条疑似顶部多报未解决，状态以算法方案§12.1为准；修订分组和补证优先级统一见算法方案§12.8、本LLD§15.8。**

预测扩展状态：**旧单参考价版已实现，用户反馈价格前提与“确认价”不清楚；用户已确认价格范围、前置收盘关联及失效修订；R1原型/Figma同步完成，新版模型与v0.2页面消费已落码，读取优化获准并完成，最终四周期正式计算/接口/预算技术验收通过，页面待用户验收。本文件原识别层规则及验收记录保持，扩展设计见 §14 和预测方案 §15。**

2026-10-15展示修订：**用户已确认预测方案§18、60样本／95分位规则及Figma，四周期预检后已实现近期条件展示；局部价格适用域反例、190项后端／57项前端测试及最终产品接口预算全部通过。页面仍由用户验收。原识别、生命周期及v0.2数学合同不变。**

2026-10-15时间口径纠正：**已按统一业务日期完成修正：交易日20:00前使用上一交易日，20:00起使用当日，四周期共同切换。先修方案再修代码，相关回归及真实日期／预算核验已通过，详见§14.4和预测方案§19。页面待用户验收，未提交或部署。**

当前性能修订：**统一调度／共享加载及获准扩围的字段投影／配对读取均已完成。后端385项、前端全量1172项及类型／构建通过；最终产品178次预算＋4次最新请求全部通过，最慢2.976秒；16组整页／双标签页306请求全部通过，最大2.859秒，96份完整响应与原版一致。原算法、全部校验、4秒和依赖方向保持；页面由用户验收，未提交或部署。详见§14.6和预测方案§20.7。**

本文同时承担 implementation design 和 LLD，内嵌编码门禁。用户已确认的规则和范围以[算法方案](/Users/congming/github/goldenshare/docs/product/xxm-direction-algorithm-plan-v0.1.md)为准；用户可见呈现以[独立展示基准](./index-detail-xxm-benchmark-requirement-v0.1.md)为准。两份既有指数详情设计保留已验收内容，本专项是新增图层。

2026-10-15 新图证核查：2024-08-22 上证日线原图及用户讲解稿已明确绿色标记为底部“结构消失”；当前实现仅跟踪顶部历史，因此该处缺少输出。精确触发公式仍未确定，本次只补充证据，不改变内核、Spec、顶部专用 DTO／前端关联字段或编码门禁，不把底部历史撤销写成已实现。90／120 分钟仅通过口述收盘底钝化状态对照，不能记作精确事件验收。详见[新案例及区分节点](/Users/congming/github/goldenshare/reports/xxm_software_indicator_crosscheck_20261015/case_20240822_semantics_20261015.md)与算法方案 §7。

同日追加 2026-08-03 双周期核查：日线四处可辨认的普通事件对应；120 分钟按柱位映射的 7/10 15:00 绿色消失，当前内核仅输出再次底钝化，账本缺少绿色事件。保存源价格尚未跌破原结构低点，简单价格镜像不能解释；简单镜像顶部生命周期又会先因新底钝化截尾。黄色残片遮挡，不能确认同柱关系或认定再次钝化时序错误；当日讲解也未明确命名历史绿色。底部触发与生命周期仍待核，尚无可实施的新契约，不改顶部专用字段、页面或算法。完整回放和证据限制见[8/3 核查](/Users/congming/github/goldenshare/reports/xxm_software_indicator_crosscheck_20261015/case_20260803_events_20261015.md)。

**最新补证取代上一段的身份和同柱保留项：** 7/10 当日讲解明确是结构消失、还没有再次钝化，下一交易日上午到 3959 才重出。当前 `STRUCTURE → DULL / dif_return` 因未重新检查价格而提前激活，并漏记结构消失；同一负柱段内这类消失与跨柱色的历史撤销须分开设计，不能只新增底部历史价格镜像或在前端换字。现有预测将 DULL 视为已激活，DTO 又不允许 NONE 携带 activeReference，后续修正必须一起审计参照保留、重新激活、预测入口和全部事件消费者。这里只记录已确认缺陷及待修方向，不批准新契约或改变实现；精确消失门槛仍未知，日线／60／90／120 分钟和顶部行为不能仅凭本例宣布验证。详见[7/10 核查](/Users/congming/github/goldenshare/reports/xxm_software_indicator_crosscheck_20261015/case_20260710_structure_disappearance_20261015.md)。

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

**执行结果：** 该表五项已实现并验收。`adapter.test.tsx` 覆盖短标签／详情方向及禁止底部历史消失；`markerGeometry.test.ts` 覆盖左侧、边界、邻点、同柱 +2、点坐标及实际 canvas 字重／半径。Wealth 全量以两个 worker 运行，162 文件／1156 项通过，typecheck／build 通过；四周期真实 API 均 HTTP 200，10 个真实布局样例均无文字重叠、裁切或覆盖圆点。两类指数 adapter、两类股票 adapter 与 shared 交互回归通过。CodeGraph 开发后 `sync/status` 正常，`impact(layoutXxmLabels)`只涉及几何与 primitive；无依赖矩阵变更。详细字段、截图和当前代码哈希见[本轮验收报告](/Users/congming/github/goldenshare/reports/xxm_ui_revision_20261014/README.md)。目前供用户复看，未提交、推送或部署。

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

[完整核验报告](/Users/congming/github/goldenshare/reports/xxm_source_audit_20261013_213852/README.md)和[证据 manifest](/Users/congming/github/goldenshare/reports/xxm_source_audit_20261013_213852/manifest.json)保留只读范围、字段投影、行数、SHA256、连续性、旧输入对照及真实现有接口响应。

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

[实施与验收报告](/Users/congming/github/goldenshare/reports/xxm_implementation_20261013/README.md)保存连续基线、API 响应、软件读数、P95 明细、页面截图、逐项对账及文件哈希。当前结果：

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

用户曾确认 Figma 并授权补齐五项审计问题后实现。来源／未来日历和单参考路径预检见 [M0报告](../../../../reports/xxm_forecast_precheck_20261014/README.md)，预测后端／文字区及真实接口验证见 [旧版报告](../../../../reports/xxm_forecast_implementation_20261014/README.md)。原识别规则及接口未改变。用户明确改为自行页面验收，助手不再启动新自动验收服务或索取登录密钥配置。

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

用户已确认；R1预检与原Figma文字同步后已迁移新模型/合同/页面。正式接口曾因60分钟来源超过4s暂停，用户已批准优化；同次metadata复用及原1000根批次真实状态缓存已实现，152项回归及最终四周期160次冷暖/18次两并发预算通过。门禁与当前证据见[本轮实施记录](../../../../reports/xxm_forecast_range_implementation_20261014/README.md)，最终成绩来自产品代码及完整接口门禁，页面仍待用户手动验收。依赖仍为App→Biz→Foundation，Wealth经HTTP；不新增反向依赖、读取链、配置来源、正式预测表或源指标补偿。原生产分钟、数据只读及发布授权边界继续有效。

### 14.3 近期简明文案与展示筛选LLD（2026-10-15）

唯一详细规则入口为[预测方案§18](./index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md#18-近期关键条件的简明展示2026-10-15)。日线及60／90／120分钟都采用“触发、未触发、推算失效、结构成立”，正文用实际日期和分钟收盘时间；过远的背离边界及备选路线可省略，相邻未触发区间、MACD变色／零柱及已钝化后的取消规则强制保留。3457点省略不意味着3951点也省略。

近期范围由同周期、同结束时刻、同目标跨度的最近60个真实历史变化的绝对幅度95分位生成；参数已确认，只用于展示，不是未来概率或评分。日线以开市日、分钟以原ENDPOINTS计数；历史回放只用截至asOf的样本。统计复用原load_entry的完整bars，不新建读取链、不增数据库／Lake写入。完整数学有效域、最近时点和原严格比较保持，不能将省略后的单边文字变成无界触发条件。

改动落点仅为ForecastSpec内部展示策略参数、IndexDetailXxmForecastQueryService给文本的同源上下文、forecast_text的选择和中文模板、对应测试；Card继续消费后端display并使用Figma新页脚。v0.2结构化范围／关联／例子和HTTP合同不删改，不需要前端计算或新的公共配置。正文整数结构区间必须向内收缩，窄区间回退2／4位；局部适用域必须注明实际日期和价格范围，不能因其覆盖近期波动带就概括为全部激活价；无可靠价格不写确定判断。正文去掉三个示例、重复范围和临界提示。

门禁在预测方案§18.7，最新执行证据见[本轮实施记录](../../../../reports/xxm_forecast_display_implementation_20261015/README.md)：四周期因果样本、隐藏下界仍失效、保护条件、跨参照／精度空隙、状态区别、原数据和数学结果不变、真实API及200ms／4s／32KiB预算均单独核验。历史或候选成绩不替代最终产品代码的成绩；页面仍由用户验收。本次不改变原识别Spec、历史结构生命周期、分层或依赖矩阵。

### 14.4 统一业务日期接入修正（2026-10-15）

本轮唯一规则和验收矩阵见[预测方案§19](./index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md#19-统一业务日期与20点切换修正2026-10-15)。预测与原XXM图层共用load_entry，因此共同迁移取数、签名、计算前缀与滞后判定；20点前已有昨天数据应正常计算，20点后缺今天完整源才滞后，不保留另一套盘中门禁或静默降级结果。

复用MarketPageContextQuery，不复制20点规则；仅增加内部可选now供同请求时钟注入，默认既有调用方行为不变。load_entry的第二返回项为共享MarketPageContext，两个正式build同步迁移；asOf历史回放仍受业务日上限约束。原公开DTO／HTTP码、算法参数、读取分页、缓存预算和前端四行不改，无新增配置。

本轮实施已完成：相关后端301项、前端57项及类型检查／构建通过；48次真实日期边界验证四周期20点前READY／20点后缺当前源才DELAYED，178次预算＋4次最新请求通过，最慢3.296秒、计算最大79.94毫秒、最大10779B。12份固定快照完整响应与前版一致，既有20个导入文件／26处context调用保持，CodeGraph已同步。真实源未发布10/15的完整源，完整发布正例及未来数据反例使用隔离源验证；证据见[本轮报告](../../../../reports/xxm_business_date_alignment_20261015/README.md)。页面仍由用户手动验收，未提交、推送、部署、安装、重启用户服务或写正式数据。

### 14.5 整页调度与共享加载LLD（2026-10-15，已授权）

唯一详细设计、参数审计和硬门禁见[预测方案§20](./index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md#20-整页请求调度与共享加载2026-10-15已授权实施)。本轮只做其两项，不进入发布后预计算／持久化快照。日线和60／90／120均覆盖，算法、正式Reader校验、Spec、业务日期、DTO及Figma保持。

前端新增指数详情专用调度模块，五类消费者统一接入：两个分钟client、页面指数九转loader、XXM识别及预测。最多2个轻请求，全历史任务独占；按图表、九转、识别、预测顺序，同级FIFO。排队可取消，5秒网络等待只从实际发送起计，JSON／adapter结束后释放名额；预测hook移除局部配额但保留周期去重、原轮询、隐藏／焦点／重试规则。股票共享hook和wealthFetch不改，无新视觉或公开参数。

后端原XxmCache拥有进行中加载协调；同bind／Lake／周期／Spec／业务日／日历截至／完成端点只执行一次真实加载，等待者不占2个源名额且保留各自4秒截止。源工作结束就释放名额，yield后只读共享entry；追加／修订使用copy-on-write，不修改其他请求持有的entry。独立请求仍查两路完整signature或日线实际值；源、完成上限和开市日历全相同才跳过已完成的连续性和内存遍历，变化则原完整校验／重建。失败不发布、不缓存成功替代。

预测完整DTO按前缀指纹、未来日历、Spec、expected与asOf复用，命中前仍核验当前来源与日历，深拷贝返回。同一个64MiB／16项LRU管理源和响应，进行中也复用16项上限；无TTL、后台任务、数据库、文件产物或新配置。原4s／200ms／32KiB和全部源范围不变。

编码前门禁R1～R7已映射真实client／load_entry／cache／forecast与测试，继承§10全部适用清单，不新增例外；必须补整页混合和双标签页使用实际JS调度器的技术验收。UI排队时间另计，不能宣称整页4秒完成；页面最终由用户验收。若发现范围内无法达标，先保留证据并按根规则确认，不自行进入下一项快照建设。

执行结果：317项相关后端、165文件／1172项前端全量、类型检查及构建通过；四周期单／双标签页冷暖16组306个真实HTTP全成功且≤4秒，预测最大2.519秒，96份响应与原同快照全字段相同。后续原160次冷暖和前8组／16次并发通过，但末组90分钟build4.0095秒、HTTP4.0541秒503，未进入模型；后4次最新未执行。只读诊断6次均2.78～3.88秒，不能抵消正式失败。原代码／阈值未因失败而修改；详见[方案§20.5](./index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md#205-实施结果与未通过的预算门禁)及[报告](../../../../reports/xxm_request_reuse_20261015/README.md)。两项代码保留，当前等待是否扩到读取层确认，不能称全部完成。


### 14.6 读取层扩围（用户已批准，先只读预检）

详细约束与代码／测试门禁统一见[预测方案§20.6](./index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md#206-已批准的读取层扩围及预检门禁)，覆盖上节末尾“等待确认”状态。Foundation Reader预检等价SQL组织，减少非目标指数的中间表物化，仍扫描并检查所有文件行；公开分页、完整历史、完整字段及所有错误拒绝条件保持。原两路签名／时间键／连续性、20000行和5000文件上限、4秒与DuckDB512MB／2线程不动，无新配置。候选先通过三周期完整数据／非目标错误反例／HTTP预算，再修改唯一正式读取实现，最后重跑四周期及混合／双标签页门禁。保留§20.5原失败与候选证据，不用成功诊断抵消正式失败；页面由用户验收。


预检进一步限定为内部字段投影：完整历史read增加默认None的value_columns，自动保留四键，仅允许原数据集输出字段，非法或重复列拒绝。source两次读取显式只要close／macd_dif、macd_dea、macd；全文件schema和合同谓词、重复键、全历史行数与source对齐不改。公开分页及默认完整历史仍返回全部原字段，不另建Reader或兼容支路。该参数不持久化、不对用户开放，来源是source静态消费字段；测试与四周期预算见方案§20.6。


字段投影单独候选未通过全部HTTP预算，正式代码仍不改；继续预检配对读取。拟新增Foundation内部完整历史pair入口，在2个worker中各用256MB／1线程，与单路原512MB／2线程总额相同，源请求名额仍2。两路以同一开始时间扣除实际排队，读取Timer／finally、bars错误优先次序和两路清理均保持，source取pair后仍做原完整时间键、MACD有限性及连续性检查。单路公开分页与默认历史行为保持。配置策略审计和反例统一落方案§20.6；候选达标后才迁移唯一实现。


读取扩围最终已实现并验收，当前状态覆盖上文预检阶段。唯一校验实现收敛在Reader `_read_complete_history`，原单路方法与配对方法共享它；source使用配对＋close／三MACD投影，原SQL合同谓词与全键对齐不变。相关后端385项、三周期4316分区全历史对照、正式178＋4接口预算及306次混合／双标签页全部通过。最终HTTP最大2.976秒，混合计算最大136.72ms，96份完整响应与原版相等；配对只重新分配原DuckDB512MB／2线程总额。代码、参数、正反例与R1～R7逐条对账见[预测方案§20.7](./index-detail-xxm-key-point-forecast-implementation-plan-v0.1.md#207-最终产品实施与计划对账)及[报告](../../../../reports/xxm_request_reuse_20261015/README.md)，历史失败保留。依赖矩阵、公开HTTP／DTO、算法、Figma及页面验收安排保持，未提交或部署。

## 15 底部同段结构消失与重新钝化LLD（2026-10-15，待确认，未实现）

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

8/5当日新材料进一步确认不能混同两层：7/31结构后有8/1、8/2红柱，8/5首根绿柱尚无新钝化，图中却有绿色消失；作者纠正交易标准为钝化消失，并说尚未出现。当前清空普通参照后没有底部旧结构后续记录，§15同段等待候选仍不覆盖此例；不能把等待记录跨红柱复用来替代历史设计。当前385根历史前缀的投影校准被既有保护拒绝，未获取合法预测价格域，未放宽容差；8/6仅作独立事后源回放。证据及限定见[8/5补证](/Users/congming/github/goldenshare/reports/xxm_software_indicator_crosscheck_20261015/case_20240805_semantics_20261015.md)。这里只更新证据，不改变待审合同、规则或编码范围。

后续8/6原图及讲解已提供当日软件观察，日线／90／120分钟末端底钝化对应；120分钟还新增8/5下午绿色缺少输出的图证。DIF参照比较、日线旧参照移出范围均获定性说明，不能将近似口述当精确游标或两段选峰公式证明。真正钝化失效后须经红柱再绿柱两根的口述，新增为待核约束，不能直接套到同段结构消失；当前是否存在反例尚未完成审计，本节候选及合同仍待确认。下一份优先2024-09-02的120分钟，具体时点与冻结分歧见[8/6核查及选材](/Users/congming/github/goldenshare/reports/xxm_software_indicator_crosscheck_20261015/case_20240806_semantics_and_next_nodes_20261015.md)。

后续[9/2、9/3补证](/Users/congming/github/goldenshare/reports/xxm_software_indicator_crosscheck_20261015/case_20240902_03_semantics_20261015.md)取得两张日线，9/2无DULL、9/3新DULL；9/3讲稿明确90分钟钝化已消失、120分钟保持，当前回放分别为CANCEL/dif_break和DULL。分钟只有口述，不能把模型9/3 14:00或参照DIF写成软件精确真值；60无新软件证据。9/2开场概括不能代替120分钟上午旧结构的标签观察，原预登记11:30分歧仍待补图。原三处日线漏报仍未修复，本节结构消失候选、合同及预测分支不因日末状态相容而自动批准。

再补[9/3的90分钟原图](/Users/congming/github/goldenshare/reports/xxm_software_indicator_crosscheck_20261015/case_20240903_m90_image_20261015.md)后，8/30结构、9/2新钝化、9/3钝化消失三处已有图证，柱位映射与当前事件对应，27次几何检查稳定；软件精确参照和游标时刻仍未取得，当前DIF／DEA／柱值的小差异保留不拟合。原三漏、跨柱色结构消失公式及120分钟9/2上午分歧仍未解决，本节候选未因此获批，不再索取已补齐的90分钟图。

随后[9/4的120分钟图及讲解](/Users/congming/github/goldenshare/reports/xxm_software_indicator_crosscheck_20261015/case_20240904_m120_semantics_20261015.md)已补齐9/2上午，不再索取该区间。六次结构和9/4上午CANCEL对应，作者明确此前多次结构并无真正钝化失效；8/5及新增约8/14下午旧绿色仍无输出。9/2上午纯DIF解释未获预期绿色正支持，价格型两种解释及新DULL接替优先级仍是待核候选，不把静态未见当确定无事件；未新增历史合同或扩展§15范围。120分钟末端指标按显示精度一致；9/4日线2777口述门槛仅作外部观察，该历史前缀投影CALIBRATION_FAILED，不绕过保护，不声明预测价已复现。原三处日线漏报仍未修复。

2026-10-16补齐[7/10模拟前后原图](/Users/congming/github/goldenshare/reports/xxm_software_indicator_crosscheck_20261015/case_20260710_simulation_pair_20261016.md)：收3959.16的模拟柱确实在旧绿色之后新增黄色钝化。验收新增该正样本；3960仍只是模型反例，不能写成软件已验证不触发。模拟低3946.16也同时改变，收盘与OHLC依赖、严格边界仍待核；日期7/13为7/10创建的假设柱，不是真实后来行情。8508根前缀及原保护投影通过，候选谓词通过不等于本节新内核已实现。原三漏、1%门槛、同柱次序和跨柱色缺口未因此解决，合同及编码范围不变。

再补[7/13五图及完整聊天讲稿](/Users/congming/github/goldenshare/reports/xxm_software_indicator_crosscheck_20261015/case_20260713_multi_period_simulations_20261016.md)：日线／90／120分钟真实DULL对应；120分钟7/13重新激活仍被当前7/10提前DULL吞掉。新增验收样本为下一根120分钟3892.79应CANCEL、90分钟3944.79应保持DULL；分别绑定7/14 11:30／11:00，后一个不是取消样本。原投影均通过且结果对应，模型额外邻价只是反例探针；口述整数不作精确门槛，日线3966仅近似口述。失效价不作结构价，后续端点按真实中间收盘重算。讲稿少数“结构消失后还跟钝化消失”未给出无中介DULL的具体图序，S4继续是待审候选，不能将其说成已排除所有软件例外。原合同、范围及未修复状态保持。

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

后续7/23讲稿补证只更新材料状态：1:49—2:12讨论后续可能新日线钝化，10:48—11:45讨论假如分钟失效而日线仍钝化，不能据此构造当天DULL／CANCEL验收。当前原内核完整源前缀376／15116／11337／7558根，末端分别NONE／NONE／NONE／DULL；没有新软件图，90分钟“钝化级别大”也不强转为末端软件状态。原三漏及本节待审合同均未因此改变，详见[7/23核查](/Users/congming/github/goldenshare/reports/xxm_software_indicator_crosscheck_20261015/case_20240723_transcript_semantics_20261016.md)。

用户随后明确只能从视频取材，并要求先逐项处理7/23。当前R4顶部取材暂停；7/23跨柱色历史跟踪的最小案例候选及逐根复核放在原专项记录§5，尚不构成本LLD的底部历史合同或编码授权。A组同段等待记录不得因此跨红柱复用；没有可区分证据时如实列假设，不要求用户操作原软件或继续找随机日期。

继续核查仅收窄B组约束：若7/23绿色关联7/9结构，历史上下文须跨过红柱并保留到第10根；不能将其转成固定TTL、新DTO或A组等待记录的跨段保留规则。价格破低、DIF反向及开始检查时机在此例仍有多种同日命中的组合，不能确定priceLow字段真值或照搬顶部谓词。完整已有历史中分钟候选出现分叉，共用结束策略也影响输出，需在未来B组方案中分别定义触发与结束、补独立反例，而不是本轮新增在线逻辑。同期本人公开材料未给公式；日线原预测校准失败单独保留，实际源指标回放不替代预测保护。详见[7/23专项反例审查](/Users/congming/github/goldenshare/reports/xxm_software_indicator_crosscheck_20261015/case_20240723_counterexample_audit_20261016.md)。无新预算验收或产品变更，原三漏仍未修复。

### 15.9 B组研究收敛后的实施限制（2026-10-16，待评审）

原V0.1§12.9新增工作修订，未增加正式字段、历史枚举或批准B组落码。42种预先固定的临时研究组合与已有五处正观察对照后，价格型三种解释均相容；仅DIF至少1%的一次性旧记录解释在120分钟8/2已先触发，不能再生成8/5那处正观察。原背离参照价格、确认收盘两种候选也无法同时对齐，原结构段最低收盘因而得到更多支持，但不等于已证明为软件唯一字段。

B组以后必须分别评审：旧结构身份／原段价格与当前普通参照；触发与结束优先级；快照恢复和过去时点；事件关联与预测所有消费者。旧历史仍在不得当DULL，历史消失不得伪造CANCEL或新DULL。A组等待记录仍在原段内释放，不因B组跨色历史而改变。附加DIF门槛、两种开始时机和E1／E2的区别继续待核；E3与9/2静态可见标签冲突的预测保留为争议，不宣称软件绝无该事件。

后续真实内核验收仍须覆盖日线及60／90／120、已有五处绿字及负证据、价格破低但DIF未回落的反例、同柱新信号接替、普通状态独立、完整前缀／恢复及原200ms／4秒混合负载。当前仅执行研究脚本，60／90无新增历史绿色软件真值。16组旧诊断、1008次诊断前缀检查及来源／保护哈希详见[本轮专项](/Users/congming/github/goldenshare/reports/xxm_software_indicator_crosscheck_20261015/case_20240723_candidate_matrix_20261016.md)，不替代产品门禁。原三漏未修复，不新增配置或依赖边界。

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

用户已确认本节工作规则，独立候选通过本次只读预检，完整证据见[本轮报告](/Users/congming/github/goldenshare/reports/xxm_bottom_history_precheck_20261016/README.md)及算法方案§12.10.6。实现仍为原V0.1，不新增正式字段或改前端。CodeGraph及真实代码审计范围保持§16.2；无架构／依赖变化。

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

审计证据及源文件SHA见[代码级LLD审计记录](/Users/congming/github/goldenshare/reports/xxm_bottom_history_code_lld_audit_20261016/README.md)。下述签名、字段和伪代码保留已确认的编码约束；真实实施按§18对账，原行号仅定位审计基线，以当前函数为准。

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

已审计实际入口`xxm_page_request_audit.py/.mjs`及[原混合验收记录](/Users/congming/github/goldenshare/reports/xxm_request_reuse_20261015/README.md)。实际清单为：四行预测＋所选周期K线（日线一路、分钟价格／指标两路）＋日线及15／30／60／90／120六路九转＋所选周期XXM识别。日线每页12请求、分钟每页13请求；四周期×单／双标签×冷暖16组，总306请求。Python现有包装只做计数、只读会话、明确正式源装配和计时，并未注入研究FastReader；不能把它误认为旧临时prototype。带FastReader的旧reports/http_precheck.py继续冻结，禁止拿来当新正式验收。

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
.venv/bin/python -m scripts.research.index_market.xxm.bottom_history_acceptance --mode frozen --source reports/xxm_source_audit_20261013_213852 --output reports/xxm_bottom_history_h1_acceptance_<本轮唯一批次>
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

T01—T16对应代码及正反例、各模式新目录、正常鉴权及只读范围、两次脚本失败重跑记录、130份旧证据保护和未改边界见[本轮实施报告](/Users/congming/github/goldenshare/reports/xxm_bottom_history_h1_implementation_20261016/README.md)及execution／validation。验收脚本的startDate仍为必填，混合请求用1990-01-01＋原500上限覆盖实际图表，endDate来自每轮真实业务context；不改产品读取或日期。页面由用户自行验收。
