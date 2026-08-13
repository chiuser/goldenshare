# 指数详情页标杆需求 v1

> 状态：M1–M5-B 与 P10 业务读取切换已完成；正式 bars/indicators 都只读 Gold，Mock 清零和浏览器回归均已通过验收。
> 用途：冻结“财势乾坤 / 指数详情页”的产品范围、数据口径、交互边界与验收标准。
> 本文是业务与体验事实源，不是实现代码。

关联文档：

1. [指数详情页技术实施方案 v1](./index-detail-implementation-design-v1.md)
2. [指数详情页 M2 编码前门禁 v1](./index-detail-m2-coding-gate-v1.md)
3. [主要指数标杆需求 v1](../market-overview/major-indices-benchmark-requirement-v1.md)
4. [上证指数日线趋势通道实时计算方案 v1](../../../../docs/architecture/sse-daily-trend-channel-realtime-computation-plan-v1.md)
5. [主要指数分钟数据集开发文档](../../../../docs/datasets/major-index-mins-dataset-development.md)
6. [指数详情页正式 API / DTO 合同 v1](./index-detail-api-contract-v1.md)
7. [指数详情页 M0 生产因子审计 v1](./index-detail-m0-production-audit-v1.md)
8. [指数详情本地分钟 API / DTO 合同 v1](./index-detail-minutes-api-contract-v1.md)
9. [股票与主要指数详情页九转接入总方案 v1](../../system/detail-page-nine-turn-integration-implementation-design-v1.md)

> 九转专项说明：M1–M5-B 的“九转为空、`supportsNineTurn=false`、不发请求”是九转立项前的历史验收事实。后续指数日线及 5/15/30/60/90/120 分钟九转，以九转总方案和新 LLD 为唯一开发入口；本专项尚未完成前不得把目标口径冒充成当前实现。

---

## 1. 目标与定位

1. 从市场总览的 10 张主要指数卡片进入对应指数详情页。
2. 默认展示指数最新已完成交易日的日线行情、技术因子和右侧信息栏；仅上证指数额外展示日线趋势通道。
3. 右侧信息栏固定提供“基本行情 / 权重股 / 技术分析走势”三个可切换页签。
4. 页面只展示客观行情、确定性指标和明确标注的估算值；不提供买卖建议，不自动触发交易动作。
5. 本页自有 API 命名空间固定为 `/api/v1/wealth/market/index-detail/*`，不由前端拼装事实字段；上证指数趋势通道是唯一例外，直接消费既有 Quote API。

## 2. 设计与决策依据

### 2.1 Figma 依据

设计文件：`Goldenshare web`，file key `RADlZzREU4lPVviYfkLy6x`。

| 设计对象 | 当前节点 | 用途 |
|---|---|---|
| 08 Index Detail - Desktop Loaded | page `412:2` | 指数详情 Basic Loaded 设计页 |
| Index Detail / Root / Basic | `417:2` | Basic Loaded 根画板，`1600×1200` |
| Index Detail / Root / Weights | `423:2` | 1600×1200 Loaded 页面、权重页签、图表工具栏 |
| Index Detail / Root / Technical | `423:910` | 技术分析页签 Loaded 页面 |
| 08.5 Index Detail - Components | page `412:3` | 指数详情组件集合 |
| Index Detail / Info Rail | `414:449` | 三页签右侧信息栏组件集 |
| Basic / Weights / Technical | `414:446` / `414:447` / `414:448` | 三种页签状态 |
| Index Weights / Scroll Viewport | `437:178` | 固定 10 行可视区、表头固定、纵向滚动 |
| Loaded Weights / Scroll Viewport | `438:178` | Loaded 权重态的同口径滚动视窗 |
| Chart / Trend Channel Overlay | `413:25` | 日线趋势通道叠加层 |
| 09 Index Detail - States and Interaction Notes | page `412:4` | 交互说明与完整状态画板 |
| Index Detail / Interaction Specification | `425:178` | 交互说明根画板；已扩展为 `1600×1438`，背景卡片不再叠放 |
| Loading / Empty / Error / Partial / Forbidden | `498:516` / `499:579` / `501:761` / `502:1625` / `504:1009` | 五个 `1600×1200` 完整状态视觉稿 |

`08` 与 `09` 两个独立页面均已确认存在。Weights/Technical 两个 Loaded 根画板已于 2026-08-13 从 `00 Cover and Source Rules` 归位到 `08 Index Detail - Desktop Loaded`，节点 ID 与 1600×1200 尺寸保持不变。

九转专项新增正式节点：股票共享 marker component set `406:10`；指数继续复用该组件，不新建第二套。指数 Loaded 交付说明 `632:728`、指数组件合同 `633:545`、指数局部状态矩阵 `634:558`；完整节点台账见九转总方案第 5 节。

Figma 仍有一处历史概述文案需要清理：`425:190` 仍写有“振幅”和“较昨日成交变化”。它与当前 Basic 组件 `414:446`、详细口径 `425:219` 以及用户最新确认冲突，不作为开发依据。当前唯一有效合同是本文 3.3 节冻结的 15 项基本行情字段。

### 2.2 已拍板口径

1. 趋势通道仅支持 `000001.SH`（上证指数）日线，直接消费现有 `/api/v1/quote/detail/trend-channel`；其余 9 个指数不展示入口、不发起请求，也不开发十指数适配层。
2. 技术结论首期为空，后续由独立策略 API 提供。
3. 九转序列在 M1–M5-B 首期为空；后续已另立九转专项，产品合同与独立 API 边界统一见九转总方案。在专项代码完成前当前实现仍保持 `supportsNineTurn=false`。
4. 权重运行时选取不晚于贡献交易日的最新完整批次；当前生产验收基线是 `2026-07-31`。
5. 默认且正式支持日线；生产环境分钟周期置灰，不允许切换。
6. 本地环境在正式 Gold canonical bars 与 Lake capability 通过门禁后支持 `1/5/15/30/60/90/120` 分钟；Gold indicators 失败只使技术图层 PARTIAL，不阻塞真实 Gold K 线，也不得回退 M5-A Mock 或 Silver。
7. 加载、错误、空数据、部分缺失和权限状态以 `09` 的五个完整状态画板为视觉事实源；股票详情页仅提供既有恢复行为和样式语言参考，不能覆盖指数详情最新设计。
8. 指数详情页不保留“前复权”按钮，也不接受复权选择。
9. 市场总览 10 张主要指数卡片分别跳转到对应指数详情页。
10. 右侧三个页签在当前页面内切换，已加载数据保留，不重复请求。
11. “+交易计划”仅是用户主动点击的独立入口；技术结论、趋势通道和九转不得触发或推荐交易动作。
12. 权重列表加载当前有效批次的全部成分；表头固定，列表视窗固定显示 10 行，列表内部纵向滚动，全量成分均可到达。
13. 基本行情固定展示 15 项：昨收、今开、总量、最高、最低、金额、市盈率、TTM 市盈率、市净率、换手率、流通市值、总市值、上涨数、平盘数、下跌数；缺值显示 `--`，删除“成交状态”和“较昨日”。
14. 页面尺寸固定为 `1600×1200` 设计基准：TopMarketBar 56px、面包屑 42px、工具栏 44px、主内容区 1058px；主内容左右内边距 10px、两栏间距 10px，左栏宽 `1193.1953125px`、右栏宽 `376.796875px`。
15. 五个状态画板共享 TopMarketBar、面包屑和周期工具栏；错误、空数据、权限和部分缺失不得用旧行情或 mock 冒充 Loaded。M5-B 删除 M5-A 的“模拟指标”例外；页面身份、日线、Gold 分钟 K 线、Gold 技术指标、权重和趋势均禁止 mock/fallback。
16. 指数详情的“成分股”只提供 A 股：源权重批次中的 B 股不进入基本行情涨跌统计、权重列表、贡献 coverage 或缺失数；A 股官方原始权重保留，不因排除 B 股而重新归一化。

## 3. 本期覆盖

### 3.1 页面与导航

1. 路由：`/wealth/market/index/:tsCode`。
2. 允许进入的标的是 `majorIndices` 策略配置中的 10 个指数。
3. 市场总览卡片点击后使用指数代码导航，不再只弹 toast。
4. 页面复用当前 `TopMarketBar`、暗色行情视觉、红涨绿跌规则和现有路由鉴权壳。

### 3.2 日线主图

1. 默认周期为 `day`。
2. 展示 OHLC、成交量、成交额、MA、BOLL、MACD、KDJ。
3. `000001.SH` 可叠加后端返回的短期 25 与长期 90 双趋势通道；其余指数不展示趋势通道入口。
4. 九转标记不展示伪数据；API 未接入时图表中不出现九转数字。
5. 分时、周 K、月 K 首期保留 Figma 控件位置但置灰。
6. 生产环境所有分钟周期置灰；本地能力开启后只解锁 API 宣布可用的分钟频率。

趋势通道绘制与颜色规则：

1. 每个交易日分别取得短期上轨、短期下轨、长期上轨、长期下轨。
2. 每个交易日都连接当日上轨和下轨形成竖线，不能抽样省略；相邻交易日分别连接上轨与上轨、下轨与下轨。
3. 每个交易日单独判色。短期通道：`close_t < shortLower_t` 时为绿色，否则为红色；长期通道：`close_t < longLower_t` 时为蓝色，否则为粉色。等于下轨归入红色/粉色。
4. 交易日 `t` 的竖线和从 `t` 连到 `t+1` 的上下轨线段使用交易日 `t` 的颜色；到 `t+1` 重新判定，颜色可在交易日边界切换。最后一个交易日只绘制当日竖线。
5. 不绘制中轴和辅助分区；现有 API 的趋势 `state` 保留为客观输出，但不作为页面通道颜色依据。

### 3.3 右侧基本行情

展示：

1. 指数名称、代码、分类、市场/交易所标签。
2. 点位、涨跌额、涨跌幅。
3. 基本行情按两列、八行排列，字段顺序固定为：昨收、今开、总量、最高、最低、金额、市盈率、TTM 市盈率、市净率、换手率、流通市值、总市值、上涨数、平盘数、下跌数；最后一行左侧以半宽卡片展示下跌数，右侧半宽留空。
4. 任一字段没有对应事实值时，该字段显示 `--`；不得用 0、上一日值或前端计算结果填补。
5. 删除“成交状态”和“较昨日”。“成交状态”后续由独立策略页签承载；“较昨日”因语义不清不进入首期合同。
6. 行情说明固定为“基础行情来自指数日线及日度指标；上涨、平盘、下跌按当日 A 股成分涨跌情况统计，缺失字段显示 --。”不得把所有指数的 `amount` 统一宣称为“全市场成交汇总”。
7. A 股成分由 `security_serving.security_type=EQUITY`、`exchange in (SSE,SZSE,BSE)`、`curr_type=CNY` 识别，禁止用代码前缀判断。源权重批次中的 B 股不属于页面成分范围，不计入总数或缺失数。
8. 上涨数、平盘数、下跌数优先按目标交易日 A 股成分 `pct_chg > 0`、`= 0`、`< 0` 聚合；没有同日行情但同日停牌表命中 `suspend_type=S` 的 A 股按 0% 计入平盘。只有既无有效 `pct_chg`、又无停牌依据的 A 股才计入 missing 并触发 PARTIAL。

#### 3.3.1 截图字段与当前生产数据审计（2026-08-11）

生产只读审计以 10 个 `majorIndices`、最新日 `2026-08-10` 为界。10 个指数的 `index_daily_serving` 自 `2026-07-01` 起均有 29 行，以下日线字段全部非空；`index_daily_basic` 只覆盖 6 个指数：`000001.SH`、`399001.SZ`、`399006.SZ`、`000300.SH`、`000905.SH`、`000016.SH`。

| 截图字段 | 当前是否有 | 当前事实源/实现条件 | 结论 |
|---|---|---|---|
| 昨收 | 10 个指数都有 | `index_daily_serving.pre_close` | 可直接展示 |
| 今开 | 10 个指数都有 | `index_daily_serving.open` | 可直接展示 |
| 总量 | 10 个指数都有 | `index_daily_serving.vol`，源单位为手 | 可直接展示；例如 `542118110` 格式化为 `5.42亿手` |
| 最高 | 10 个指数都有 | `index_daily_serving.high` | 可直接展示 |
| 最低 | 10 个指数都有 | `index_daily_serving.low` | 可直接展示 |
| 振幅 | 10 个指数可计算 | `(high - low) / preClose × 100%` | 不进入当前 15 项基本行情；不得因旧 Figma 概述重新加入 |
| 金额 | 10 个指数都有 | `index_daily_serving.amount`，源单位为千元 | 可直接展示；例如 `1166893282.35` 千元格式化为 `1.17万亿` |
| 市盈率、TTM 市盈率 | 仅 6 个指数有 | `index_daily_basic.pe`、`pe_ttm` | 分成两个明确字段；无值显示 `--` |
| 市净率 | 仅 6 个指数有 | `index_daily_basic.pb` | 展示；无值显示 `--` |
| 换手率 | 仅 6 个指数有 | `index_daily_basic.turnover_rate` | 展示；无值显示 `--` |
| 流通市值 | 仅 6 个指数有 | `index_daily_basic.float_mv` | 展示；无值显示 `--` |
| 总市值 | 仅 6 个指数有 | `index_daily_basic.total_mv` | 展示；无值显示 `--` |
| 现量 | 没有 | 日线与每日指标表均无此字段 | 需要独立实时行情口径/API |
| 量比 | 没有 | 日线与每日指标表均无此字段 | 需要独立计算口径/API |
| 委卖、委买 | 没有 | 不属于指数日线/每日指标 | 需要独立实时盘口口径/API |
| 卖额、买额 | 没有 | 不属于指数日线/每日指标 | 需要独立实时成交方向口径/API |
| 上涨数、平盘数、下跌数 | 没有现成指数日线字段 | 取 `weightTradeDate <= asOfTradeDate` 的最新完整成分批次，关联同日 `equity_daily_bar.pct_chg` 后聚合 | 已确认按指数成分口径开发；缺失成员不计入三类并标记 PARTIAL |

2026-08-12 生产只读复核显示，10 个指数的有效权重批次均为 `2026-07-31`。上证源权重批次共 2224 行，其中 2184 行满足 A 股身份，40 行为当前系统不提供行情的沪市 B 股；其它 9 个指数的源批次与 A 股子集相同。以页面最新交易日 `2026-08-11` 复算：2184 个上证 A 股成分中，648 只上涨、49 只有效行情平盘、1485 只下跌，另有建设机械 `600984.SH`、爱丽家居 `603221.SH` 两只确认停牌。两只停牌股按 FLAT 计入后，最终为上涨 648、平盘 51、下跌 1485、matched 2184、missing 0，基本行情不因 B 股或正常停牌进入 PARTIAL。

### 3.4 右侧权重股

1. 展示当前有效源权重批次中的全部 A 股成分，按权重降序排列；同权重按 `conCode` 升序，不截断、不提供前端任意 limit。B 股不返回，也不占 coverage。
2. 列固定为：名称、权重、涨跌幅、贡献点。表头固定，列表视窗固定为 10 行高，内部纵向滚动。
3. 权重不做归一化，原始权重总和不强制修正为 100%；排除 B 股后也不得把 A 股权重子集重新归一化。
4. 当前运行口径：选取 `weightTradeDate <= contributionTradeDate` 的最新权重批次；当前验收应解析到 `2026-07-31`。
5. 贡献点是估算值：

```text
estimatedContributionPoint
= indexPreClose
  × weight / 100
  × constituentPctChg / 100
```

6. `constituentPctChg` 优先来自与 `contributionTradeDate` 相同日期的 A 股日线；当日无行情但存在同日 `suspend_type=S` 时按 0% 处理。
7. 真正缺少 A 股日线且无停牌依据、缺少指数昨收或权重时，贡献点返回 `null` 并进入 PARTIAL；不得把无法解释的缺失按 0 处理。
8. 不按指数实际涨跌点对贡献点求和做二次缩放或对账修正。
9. 标题可保留“贡献点”，说明文字固定为“基于最新月度权重估算，非指数公司官方归因”。
10. API 必须返回 `isEstimated=true`、`weightTradeDate`、`contributionTradeDate` 和缺失覆盖情况。
11. 分钟周期切换不改变权重页签的日频语义；首期不提供盘中贡献点。

### 3.5 右侧技术分析走势

1. 保留 Figma 的技术分析页签与卡片结构。
2. “技术分析结论”首期所有策略字段为空，显示 `--`，不使用 mock 文案。
3. 多周期矩阵中的九转、MACD/KDJ 解释性文案首期为空。
4. 仅上证指数日线可显示后端返回的客观通道数据；其余指数该区域显示不支持，不调用趋势通道接口。
5. 右侧固定展示“短期上轨 / 短期下轨 / 长期上轨 / 长期下轨”四项，不再展示中轴。
6. 生产环境的 60 分钟、30 分钟技术行显示 `--`；本地分钟数据可用也不自动生成技术结论文案。

### 3.6 五个完整页面状态

五个状态均复用 Loaded 的页面外壳、TopMarketBar 主组件 `97:2`、面包屑和周期工具栏。状态差异只能发生在主内容区，不得重做导航或改变页面尺寸。

| 状态 | Figma 根节点 | 固定视觉与交互 |
|---|---|---|
| LOADING | `498:516` | 左侧为 K 线/MACD/成交量/KDJ 骨架，右侧为信息栏骨架；主文案显示“正在加载指数行情”。Figma 上证指数样例的副文案为“正在读取日线、技术指标与趋势通道”；其余 9 个指数改为“正在读取日线与技术指标”，不得声称读取不支持的趋势通道；不得显示上一次指数的详情数据 |
| EMPTY | `499:579` | 保留指数身份、工具栏、右侧三 Tab 和基本行情结构；主图显示“暂无指数日线数据”，提供“重新加载 / 查看最近交易日”；右侧主价格、涨跌和 15 个指标值全部显示 `--` |
| ERROR | `501:761` | 主内容区改为单个全宽错误面板，显示“指数详情加载失败 / 行情服务暂时不可用，请稍后重试。 / ERROR · 请求未完成”，提供“重新加载 / 返回指数首页” |
| PARTIAL | `502:1625` | 保留完整 Loaded 图表和所有可用数据；仅实际缺失字段显示 `--`，右栏显示琥珀色“部分数据缺失”说明。Figma 示例缺失项是金额、TTM 市盈率、平盘数，运行时必须根据接口真实缺失字段生成，不得写死这三项 |
| FORBIDDEN | `504:1009` | 主内容区改为单个全宽权限面板，显示“暂无访问权限 / 403 · FORBIDDEN”，提供“返回指数首页”；使用信息色，不伪装为空数据 |

状态颜色必须使用系统语义：ERROR 使用 `--cs-color-danger-system`，PARTIAL 使用 `--cs-color-warning`，FORBIDDEN 使用 `--cs-color-info`；不得复用行情上涨红或行情下跌绿。

当前完整视觉稿不包含独立的 404、DELAYED 及权重/趋势模块局部状态画板。404 复用 ERROR 的全宽页面壳并替换为“指数不存在”文案；DELAYED 保留 Loaded 数据并明确显示观测日期；模块级 loading/empty/error/partial 只替换对应 Tab 或图层。它们必须按 `425:178` 的交互说明实现，但不声称已有独立像素稿。

## 4. 本期不覆盖

1. 技术结论策略 API 与策略文案。
2. 九转序列 API、九转计算与九转标记。
3. 自选、提醒、交易计划的持久化或真实业务流程。
4. 分时、周 K、月 K。
5. 生产环境分钟线。
6. 盘中权重贡献、官方指数归因或贡献点强制对账。
7. 指数详情之外的主要指数名单、数量和排序调整。

## 5. 业务对象与数据来源

| 对象/字段 | 事实源 | 口径 | 缺失策略 |
|---|---|---|---|
| 允许访问的指数名单 | `majorIndices` 策略配置 | 固定 10 个 code | 非名单标的 404 |
| 指数身份 | `core_serving.index_basic` | `ts_code/name/market/category/publisher` | 名称缺失时展示 code |
| 日线报价日期与价格 | `core_serving.index_daily_serving` | 最新已完成交易日；不使用其量额 | 无行 EMPTY |
| 指数日度指标 | `core_serving.index_daily_basic` | 与 `asOfTradeDate` 同日的 PE/PE TTM/PB/换手率/流通市值/总市值 | 单字段无值显示 `--`，不回填 |
| 日线 K 线与技术因子 | `core_serving.index_factor_pro` | bfq/指数无复权；日期、OHLC、涨跌、量额与 MA/BOLL/MACD/KDJ | 缺列或缺行 PARTIAL，不补 0 |
| 基本行情总量/金额 | 同日 `core_serving.index_factor_pro` | 与 Kline 使用同一 factor 量额事实 | 同日行/字段缺失为 null + PARTIAL，不 fallback/换算 |
| 权重 | `core_serving.index_weight` | 最新批次且不晚于贡献日 | 无批次 EMPTY |
| A 股成分范围与名称 | `core_serving.security_serving` | `security_type=EQUITY`、交易所为 SSE/SZSE/BSE、币种 CNY；按 `con_code` 补名 | B 股不进入页面成分范围 |
| 成分股涨跌幅 | `core_serving.equity_daily_bar` + `core_serving.equity_suspend_d` | 与贡献日同日；日线优先，确认停牌时为 0% | 无日线且无停牌依据时 contributionPoint 为 null |
| 指数成分涨跌统计 | `index_weight` + `security_serving` + `equity_daily_bar` + `equity_suspend_d` | 最新有效批次中的 A 股；日线涨跌分组，确认停牌计 FLAT | 仅真实 A 股缺失触发基本行情 PARTIAL |
| 趋势通道 | 现有 `/api/v1/quote/detail/trend-channel` | 仅 `000001.SH` 日线 25/90 EMA 双通道 | 上证模块 PARTIAL/ERROR；其余指数不请求 |
| 本地分钟行情 | Lake Silver `major_index_mins` | 仅 local capability 开启 | 模块 EMPTY/DELAYED |
| 本地分钟指标 | Lake Gold `major_index_mins_technical` | 仅 local capability 开启 | 指标缺失保持 null |

M0 已完成 10 指数当前生产快照覆盖审计。审计时 `000510.SH` 有 182 行 MA250 前缀空值，但 2024 技术因子正在同步，该现象只作为时点记录，不是合法 warm-up 的固定 code/date 规则。MA 是否因历史不足为 null 必须按同一 code 截至该交易日的实际有效历史根数动态判断。深证成指、创业板指 factor 量额与 daily 分叉；外部数据源核对确认 factor 准确，因此基本行情和 Kline 的量额统一取 factor。不得用倍率修正、daily fallback、API 临时计算或前端换算替代。

## 6. 时间与状态语义

### 6.1 最新已完成交易日

1. 页面期望日期直接复用 `MarketPageContextQuery.pageContext.tradeDate`，不得再根据 `sessionStatus` 二次回退一天。现有 context query 已按交易日、非交易日和晚间数据就绪时间解析默认日期。
2. 显式 `tradeDate` 只用于可复现查询和测试，不在首期 UI 暴露日期选择器。
3. 日线报价查询 `tradeDate <= pageContext.tradeDate` 的最近一行；该行日期作为 `asOfTradeDate` 和 `observedTradeDate`。
4. 权重贡献锚定 `asOfTradeDate`，确保指数昨收、成分涨跌幅和权重批次属于同一可展示日；若它早于 pageContext 期望日期，页面明确标记 DELAYED。
5. 日线技术因子和趋势通道都以 `pageContext.tradeDate` 为查询上界，各自返回 observed date，不做未来回填。

### 6.2 页面与模块状态

| 状态 | 用户可见行为 |
|---|---|
| LOADING | 保留顶部栏、面包屑和工具栏；主图与右栏显示骨架，不显示旧详情数据 |
| READY | 日线主图与当前右栏页签可用 |
| PARTIAL | 保留 Loaded 骨架与所有可用事实；仅缺失字段/图层显示 `--` 或断点，并显示琥珀色局部说明 |
| DELAYED | 展示最近可用数据及数据日期，不伪装为当前日 |
| EMPTY | 保留指数身份、工具栏和三 Tab；主图显示无数据，指数专属值显示 `--`，不回填 mock |
| ERROR | 保留页面外壳，主内容显示全宽可重试系统错误，不回填 mock |
| FORBIDDEN | 保留页面外壳，主内容显示全宽 403 权限状态；未登录沿用登录跳转 |

页签状态彼此独立：权重接口失败不得清空已加载日线；趋势通道失败不得阻断基本行情；page-init 找不到标的或无权限属于页面级失败。页面级错误提供整页重试；权重、趋势和分钟错误只在对应模块提供局部重试。权重 PARTIAL 保留可用 A 股行并将真正缺失的贡献显示为 `--`，不得删除异常行或补 0；确认停牌行按 0%/FLAT 展示。日度指标缺字段时只把对应指标显示为 `--`；成分涨跌统计存在无法由日线或停牌解释的 A 股缺失时保留已分类计数并标记 PARTIAL。B 股排除和确认停牌均不得触发 PARTIAL。

## 7. API 需求层契约

正式路由：

```text
GET /api/v1/wealth/market/index-detail/page-init
GET /api/v1/wealth/market/index-detail/kline
GET /api/v1/wealth/market/index-detail/weights
```

趋势通道不新增 Wealth 适配接口；仅当 `page-init.capabilities.supportsTrendChannel=true` 时调用现有接口：

```text
GET /api/v1/quote/detail/trend-channel
```

本地条件路由：

```text
GET /api/v1/wealth/market/index-detail/minutes
GET /api/v1/wealth/market/index-detail/minute-indicators
```

要求：

1. DTO 使用 lowerCamelCase。
2. `kline` 不接受 `adjustment` 参数，也不返回复权选项。
3. `weights` 不接受 `limit`，一次返回选定 `weightTradeDate` 的完整 A 股子集；`rows.length` 必须等于 `coverage.totalCount`，禁止静默截断。
4. `supportsTrendChannel` 仅在 `tsCode=000001.SH` 且 `period=day` 时为 true；其余指数前端不得调用趋势通道接口。
5. 生产 profile 不挂载分钟路由，直接访问应为 404。
6. 真实 API 失败后禁止回退 mock。

## 8. 性能预算

| 接口 | P95 目标 | 默认体量 |
|---|---:|---:|
| page-init | 200ms | 1 个标的、1 个完成交易日 |
| kline | 400ms | 最近 300 根，最大 2000 根 |
| weights | 500ms | 当前有效批次全量；响应体目标不超过 1 MiB |
| trend-channel | 热缓存 100ms；冷计算 500ms | 最近 300 根 |
| local minutes/indicators | 1.5s | 默认 500 根 |

M5-A 的 1.5s 目标只验收真实 Silver bars；M5-B 使用相同目标验收真实 Gold indicators。`limit=10000` 是参数上限，响应仍必须优先满足 5MB 门禁；最大响应验收同时覆盖 10000 根正确拒绝语义和固定 5000 根正常分页。

M5-B 正式 Gold 验收使用同一 1.5s P95 目标、5s 硬门禁，并固定分成两层：

1. `--runs 10`：七频率最新共同分区做 schema、唯一键、Silver/Gold 时间键对齐，并对页面可用指数执行 500 根 Query Service + DTO 序列化性能矩阵。
2. `--full-alignment --include-max`：逐个共同分区执行全量时间键对齐；代表性的 1 分钟 `limit=10000` 若超过 5MB，必须正确返回 `ID_REQUEST_INVALID`，再以固定 `limit=5000` 验证响应大小、`hasMore/nextCursor`、下一页时间顺序和 5s 硬门禁；其余频率继续受 5000 分区扫描上界保护。
3. 正式 Gold 根或任一频率无文件时必须报告 `SOURCE_NOT_READY / IM_SOURCE_NOT_READY`，不得产生性能通过结论。
4. 验收工具固定只读 `/Volumes/datasource/data_lake`，不执行 Dagster，不读取旧 Lake/staging，不写文件或运行状态。

2026-08-12 首次执行正式只读预检：Silver 七频率各 4,276 个分区，Gold technical 七频率均 0 个分区；结果为 `SOURCE_NOT_READY / IM_SOURCE_NOT_READY`，性能阶段按门禁未启动。该记录只描述当日物理事实，正式文件形成后必须重跑，不能复用为后续结论。

2026-08-13 最终重跑：Silver/Gold technical 七频率各 4,277 个分区，29,939 个频率-日期分区对全历史对齐零失败；Technical/state 共 59,878 个正式文件、10,150,506 行。页面可用九个指数 × 七频率 × 10 次的 630 个默认 500 根样本全部 READY，频率级 P95 为 282.243–322.982ms。代表性 `limit=10000` 因超过 5MB 正确拒绝，固定 `limit=5000` 返回 3,181,443 bytes、cursor 有效且耗时 334.441ms。前端真实 Gold 指标、bars-only Partial、Mock 清零与 1600×1200 浏览器验收同步通过。

## 9. 验收标准

1. 10 张主要指数卡都能进入正确路由，浏览器前进/后退可用。
2. 默认日线加载真实数据，页面中不存在“前复权”。
3. 生产环境除日线外的周期不可切换；本地只解锁 capability 宣布的分钟频率。
4. 三个右侧页签可切换，并保留各自已加载状态。
5. 权重按源值降序展示完整 A 股子集，表头固定、首屏 10 行、内部滚动可达末行；生产验收的权重批次为 `2026-07-31`，上证响应应为 2184 行且不包含 B 股。
6. 贡献点公式、空值、估算标识、日期字段与说明文字全部可见且可复算。
7. 技术结论与九转没有 mock、默认文案或自动交易动作。
8. 上证指数趋势通道由现有后端接口输出，前端逐交易日按相对下轨规则着色；每个交易日都有上下轨竖线，颜色可在交易日边界切换；其余 9 个指数不出现入口和请求。
9. Loading/Empty/Error/Partial/Forbidden 均按 `498:516`、`499:579`、`501:761`、`502:1625`、`504:1009` 完成真实接口测试和前端展示测试；状态文案、动作、颜色和数据保留规则与视觉稿一致。
10. Figma Loaded 与五个状态页在 1600×1200 基准下通过像素验收，且不破坏当前股票详情页；普通 UI 偏差不超过 2px，图表/趋势通道/坐标轴不得位移。
11. 基本行情严格展示已确认的 15 项；缺值为 `--`，不存在“成交状态”和“较昨日”；成分涨跌三项只基于 A 股成分，确认停牌计入平盘，只有无法解释的 A 股缺失触发 PARTIAL。
12. M5-B 本地七频率按 code/frequency/date 独立缓存，bars 与 indicators 使用同窗口且旧响应不能串标；北证50只显示左侧分钟 EMPTY，切回日线恢复；分钟 Tooltip 只显示冻结的七项字段，不再出现“模拟指标”标识。bars READY 且 indicators 异常时，K 线保留、技术线为空并显示局部 PARTIAL。

## 10. 待评审项

1. Weights/Technical Loaded 根画板已物理归位到 `08` 页面，原节点 ID 和页面尺寸未改变；该整理不改变既有交互或业务口径。
2. `425:190` 的旧基本行情概述文案需在后续 Figma 清理中删除或改写；开发和测试不得引用该节点。

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1.19 | 2026-08-14 | 完成 P10：本地指数 bars 切换为正式 Gold canonical bars，无 Silver fallback；七频业务合同、tooltip 与有限只读性能验收通过 | Codex |
| v1.18 | 2026-08-13 | 登记九转专项总方案与正式 Figma；Weights/Technical 根画板从 Cover 归位到 08 页面；保留 M1–M5-B 的九转空值为历史实现事实 | Codex |
| v1.17 | 2026-08-13 | 完成 M5-B 真实 Gold provider 与 Mock 清零；回填 4,277×7 全历史重跑、630 样本性能、最大响应和 1600×1200 浏览器验收 | Codex |
| v1.16 | 2026-08-13 | 回填 M5-B 正式 Gold 全历史覆盖/对齐与 630 样本性能证据；冻结 10000 参数上限受 5MB 优先门禁、5000 根正常分页验收，以及真实指标失败保留 bars/禁止 Mock fallback 的体验口径 | Codex |
| v1.15 | 2026-08-12 | 增加 M5-B 正式 Gold 两层只读验收矩阵：七频率默认 500 根、全分区时间键对齐和 10000 根响应门禁；缺文件统一报告 SOURCE_NOT_READY | Codex |
| v1.14 | 2026-08-12 | 成分范围收敛为 Security 事实字段识别的 A 股；B 股不进入涨跌统计、权重列表或 missing；确认停牌的 A 股按 0%/FLAT 参与涨跌统计和贡献，真实缺失才触发 PARTIAL；回填 2026-08-11 生产复算证据 | Codex |
| v1.13 | 2026-08-11 | 完成 M5-A：正式 Silver 七频率、本地条件路由、北证50局部空态、开发态 Mock 指标、共享分钟时间模式、缓存/竞态与 1600×1200 浏览器验收通过；M5-B Gold 仍未完成 | Codex |
| v1.12 | 2026-08-11 | 冻结 M5-A：正式 Silver 决定本地分钟 K 线能力；Gold 指标暂用可见开发态 Mock 且不作 fallback/验收证据；真实 Gold、70 checks 与物理对齐保留 M5-B | Codex |
| v1.11 | 2026-08-11 | 回填 M4 完成状态：五个 Figma 主状态、404、Delayed、页面/模块状态分层与局部重试已落地；真实 Partial、逐状态拦截截图、1600×1200 尺寸和无溢出验收通过，并通过 100 项 Wealth 与 82 项后端相关回归；M5 分钟保持后置边界 | Codex |
| v1.10 | 2026-08-11 | 回填 M3 Loaded 完成状态：10 卡进入独立指数路由、真实日线、三 Tab、15 项基本行情、完整权重虚拟滚动与 SSE-only 趋势通道已落地；M4 五态与 M5 分钟仍保持后置边界 | Codex |
| v1.9 | 2026-08-11 | 回填 M2 shared chart 完成状态；股票视觉与交互零回归，未引入指数页面、趋势实现或新的产品字段 | Codex |
| v1.8 | 2026-08-11 | 回填 M1 后端完成状态；实现未改变产品字段、趋势边界、权重公式或状态口径，真实 2000 行与前端像素验收继续保留 | Codex |
| v1.7 | 2026-08-11 | 外部核对确认 factor 量额准确；基本行情与 Kline 的成交量、成交额统一取 factor，禁止 daily fallback；DTO 合同提升为 1.1.0 | Codex |
| v1.6 | 2026-08-11 | 修正 MA null 口径：A500 空值仅为生产快照观察；删除 code/date 特例，改为按实际有效历史根数动态判断 | Codex |
| v1.5 | 2026-08-11 | 完成 M0 数据/合同冻结：记录深市量额分叉与当时 A500 MA250 空值现象；量额最终来源已由 v1.7 修订 | Codex |
| v1.4 | 2026-08-11 | 登记最新 Loaded/Components/States 节点树；冻结五个完整状态的页面骨架、文案、动作、颜色和数据保留规则；登记 Figma 旧基本行情概述文案冲突 | Codex |
| v1.3 | 2026-08-11 | 趋势通道改为逐交易日判色并要求每日竖线；基本行情冻结 15 项，删除成交状态/较昨日；冻结成分涨跌统计与缺失处理，并补生产复核证据 | Codex |
| v1.2 | 2026-08-11 | 趋势通道收敛为仅上证指数直接消费现有 API；冻结双通道绘制/颜色规则、四轨展示和成交状态占位；补生产日线/每日指标字段审计 | Codex |
| v1.1 | 2026-08-11 | 权重改为完整批次、固定 10 行视窗与内部滚动；确认 09 页面并补异常状态口径 | Codex |
| v1 | 2026-08-10 | 基于 Figma、当前代码、生产权重审计与用户已拍板口径形成首版草案 | Codex |
