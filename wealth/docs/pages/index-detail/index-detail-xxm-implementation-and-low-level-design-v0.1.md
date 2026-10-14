# 上证徐小明研究指标 V0.1 实施方案与 LLD

日期：2026-10-14。状态：**用户已批准规则、Figma、完整历史读取调整及仅指数详情页的 1280／1440px 适配；M0/M1/M2 技术验收完成，10 月 14 日标记视觉修订已同步四周期并通过技术验收，M3 等用户复看；未部署。**

预测扩展状态：**旧单参考价版已实现，用户反馈价格前提与“确认价”不清楚；用户已确认价格范围、前置收盘关联及失效修订；R1原型/Figma同步完成，新版模型与v0.2页面消费已落码，读取优化获准并完成，最终四周期正式计算/接口/预算技术验收通过，页面待用户验收。本文件原识别层规则及验收记录保持，扩展设计见 §14 和预测方案 §15。**

本文同时承担 implementation design 和 LLD，内嵌编码门禁。用户已确认的规则和范围以[算法方案](/Users/congming/github/goldenshare/docs/product/xxm-direction-algorithm-plan-v0.1.md)为准；用户可见呈现以[独立展示基准](./index-detail-xxm-benchmark-requirement-v0.1.md)为准。两份既有指数详情设计保留已验收内容，本专项是新增图层。

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

只纳入已完成端点；严格核验正式来源实际 60/90/120 端点、交易日覆盖及中间缺口。不能仅用“相邻时间差很大”判缺失，也不能只验证两侧数量相等便忽略双方一起缺失的交易日。非有限指标、缺少源字段或无法解释的中间缺口拒绝计算，不跨缺口重新暖机。

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
| `cache_max_bytes=64MiB`／`cache_max_series=16` | 同一运行预算 | 服务进程内 LRU；key 含 Spec 和来源身份 | 超限驱逐可重建项；历史修订、过去 endDate、续接测试 |
| 完整历史扫描 `memory_limit=512MB`／`threads=2` | Foundation reader 中单一定义；仅新完整历史入口的 DuckDB 连接配置，不持久化、不增加 env | XXM 分钟源加载器；不作用于原分页方法 | 每连接生效；真实扫描及运行配置断言。沿用 M0 临时只读扫描已测的资源设置，避免默认高并行的内存峰值；512MB 是 DuckDB 管理内存限额，不是进程 RSS 硬限额 |
| 请求超时 5s | 前端 API client 的单一定义 | 本专项 controller；须 AbortController | 明确失败和重试，保留其他模块 |
| 标记视觉参数 | 展示基准 §5／§9，`markerGeometry.ts.XXM_MARKER_STYLE` 单一定义：字号 12px、字重 700、行高 16px、行距 18px、点半径 4px、点边与文字间隔 8px、边界 padding 3px；无持久化、env 或用户开关 | 日线和分钟同一 primitive；字号影响测字、行高影响碰撞范围，半径与间隔共同决定左侧文字位置 | Figma 已获用户确认；style、实际绘制字重／圆点、左侧／边界／同柱／邻点避让及四周期真实页面验证；颜色和字体仍取现有 token |
| 指数详情页最小宽度 1280px | `index-detail-page.css` 仅在 `body:has(.index-detail-app)` 覆盖既有 `--cs-layout-content-min-width`；全站 token 原值 1460px 保留 | global.css 的 body 最小宽度；只在指数详情页生效，无持久化、无 env | 用户已确认该范围；实际 1280／1440px 无横向滚动、切到其他页面恢复原值。指数页内的三层图表 grid 显式用 `minmax(0,1fr)` 单列，避免旧 canvas 固有宽度撑住容器导致坐标轴裁切；不改 shared Shell 或其他页面 |

后端暖缓存 P95 目标 ≤1s，冷缓存 P95 目标 ≤3s；最多两个 XXM 请求同时执行，单次计算包括读源不超过 4s，超过预算显式失败。M0 测得请求量、分页次数、文件数及数据量；M2 测真实 API P95、响应字节数、进程峰值内存和端到端耗时。预算未过不得通过删历史、用固定暖机或伪造 ready 解决，须先调整设计。

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
