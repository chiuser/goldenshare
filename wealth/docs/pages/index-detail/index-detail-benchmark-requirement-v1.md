# 指数详情页标杆需求 v1

> 状态：草案，待评审。
> 用途：冻结“财势乾坤 / 指数详情页”的产品范围、数据口径、交互边界与验收标准。
> 本文是业务与体验事实源，不是实现代码。

关联文档：

1. [指数详情页技术实施方案 v1](./index-detail-implementation-design-v1.md)
2. [指数详情页 M2 编码前门禁 v1](./index-detail-m2-coding-gate-v1.md)
3. [主要指数标杆需求 v1](../market-overview/major-indices-benchmark-requirement-v1.md)
4. [上证指数日线趋势通道实时计算方案 v1](../../../../docs/architecture/sse-daily-trend-channel-realtime-computation-plan-v1.md)
5. [主要指数分钟数据集开发文档](../../../../docs/datasets/major-index-mins-dataset-development.md)

---

## 1. 目标与定位

1. 从市场总览的 10 张主要指数卡片进入对应指数详情页。
2. 默认展示指数最新已完成交易日的日线行情、技术因子、趋势通道和右侧信息栏。
3. 右侧信息栏固定提供“基本行情 / 权重股 / 技术分析走势”三个可切换页签。
4. 页面只展示客观行情、确定性指标和明确标注的估算值；不提供买卖建议，不自动触发交易动作。
5. API 命名空间固定为 `/api/v1/wealth/market/index-detail/*`，不由前端拼装事实字段。

## 2. 设计与决策依据

### 2.1 Figma 依据

设计文件：`Goldenshare web`，file key `RADlZzREU4lPVviYfkLy6x`。

| 设计对象 | 当前节点 | 用途 |
|---|---|---|
| 08 Index Detail - Desktop Loaded | page `412:2` | 指数详情 Loaded 设计页；当前页内只有 Basic 根画板与评审标签 |
| Index Detail / Root / Weights | `423:2` | 1600×1200 Loaded 页面、权重页签、图表工具栏 |
| Index Detail / Root / Technical | `423:910` | 技术分析页签 Loaded 页面 |
| 08.5 Index Detail - Components | page `412:3` | 指数详情组件集合 |
| Index Detail / Info Rail | `414:449` | 三页签右侧信息栏组件集 |
| Basic / Weights / Technical | `414:446` / `414:447` / `414:448` | 三种页签状态 |
| Index Weights / Scroll Viewport | `437:178` | 固定 10 行可视区、表头固定、纵向滚动 |
| Loaded Weights / Scroll Viewport | `438:178` | Loaded 权重态的同口径滚动视窗 |
| Chart / Trend Channel Overlay | `413:25` | 日线趋势通道叠加层 |
| 09 Index Detail - States and Interaction Notes | page `412:4`，frame `425:178` | 页签、权重滚动、页面级与模块级异常说明 |

`08` 与 `09` 两个独立页面均已确认存在。当前仍有一个 Figma 结构问题：Weights/Technical 两个 Loaded 根画板实际挂在 `00 Cover and Source Rules`，`08` 页面只有 Basic 根画板和评审标签。该问题不改变交互语义，但在最终像素台账冻结前应把两个根画板归位或显式登记其跨页位置。

### 2.2 已拍板口径

1. 趋势通道使用现有 25/90 高低价 EMA 公式与后端计算能力；前端不计算。
2. 技术结论首期为空，后续由独立策略 API 提供。
3. 九转序列首期为空，后续由独立 API 提供。
4. 权重运行时选取不晚于贡献交易日的最新完整批次；当前生产验收基线是 `2026-07-31`。
5. 默认且正式支持日线；生产环境分钟周期置灰，不允许切换。
6. 本地环境在 Lake 能力通过门禁后支持 `1/5/15/30/60/90/120` 分钟。
7. 加载、错误、空数据、部分缺失和权限状态沿用股票详情页的交互语言。
8. 指数详情页不保留“前复权”按钮，也不接受复权选择。
9. 市场总览 10 张主要指数卡片分别跳转到对应指数详情页。
10. 右侧三个页签在当前页面内切换，已加载数据保留，不重复请求。
11. “+交易计划”仅是用户主动点击的独立入口；技术结论、趋势通道和九转不得触发或推荐交易动作。
12. 权重列表加载当前有效批次的全部成分；表头固定，列表视窗固定显示 10 行，列表内部纵向滚动，全量成分均可到达。

## 3. 本期覆盖

### 3.1 页面与导航

1. 路由：`/wealth/market/index/:tsCode`。
2. 允许进入的标的是 `majorIndices` 策略配置中的 10 个指数。
3. 市场总览卡片点击后使用指数代码导航，不再只弹 toast。
4. 页面复用当前 `TopMarketBar`、暗色行情视觉、红涨绿跌规则和现有路由鉴权壳。

### 3.2 日线主图

1. 默认周期为 `day`。
2. 展示 OHLC、成交量、成交额、MA、BOLL、MACD、KDJ。
3. 叠加短期与长期趋势通道；趋势通道数据由后端返回。
4. 九转标记不展示伪数据；API 未接入时图表中不出现九转数字。
5. 分时、周 K、月 K 首期保留 Figma 控件位置但置灰。
6. 生产环境所有分钟周期置灰；本地能力开启后只解锁 API 宣布可用的分钟频率。

### 3.3 右侧基本行情

展示：

1. 指数名称、代码、分类、市场/交易所标签。
2. 点位、涨跌额、涨跌幅。
3. 今开、昨收、最高、最低、振幅、成交量、成交额。
4. “较昨日”固定为成交额相对上一完成交易日的变化率：`(amount_t / amount_t-1 - 1) × 100%`；任一值为空或非正数时返回空。
5. “成交状态”属于策略化解释，首期显示 `--`，不得由前端根据阈值临时分类。
6. 行情说明改为“展示指数盘后行情；成交量和成交额沿用指数日线源口径”。不得把所有指数的 `amount` 统一宣称为“全市场成交汇总”。

### 3.4 右侧权重股

1. 展示当前有效权重批次的全部成分股，按权重降序排列；同权重按 `conCode` 升序，不截断、不提供前端任意 limit。
2. 列固定为：名称、权重、涨跌幅、贡献点。表头固定，列表视窗固定为 10 行高，内部纵向滚动。
3. 权重不做归一化，原始权重总和不强制修正为 100%。
4. 当前运行口径：选取 `weightTradeDate <= contributionTradeDate` 的最新权重批次；当前验收应解析到 `2026-07-31`。
5. 贡献点是估算值：

```text
estimatedContributionPoint
= indexPreClose
  × weight / 100
  × constituentPctChg / 100
```

6. `constituentPctChg` 必须来自与 `contributionTradeDate` 相同日期的股票日线。
7. 缺少股票日线、指数昨收或权重时，贡献点返回 `null` 并进入 PARTIAL；不得按 0 处理。
8. 不按指数实际涨跌点对贡献点求和做二次缩放或对账修正。
9. 标题可保留“贡献点”，说明文字固定为“基于最新月度权重估算，非指数公司官方归因”。
10. API 必须返回 `isEstimated=true`、`weightTradeDate`、`contributionTradeDate` 和缺失覆盖情况。
11. 分钟周期切换不改变权重页签的日频语义；首期不提供盘中贡献点。

### 3.5 右侧技术分析走势

1. 保留 Figma 的技术分析页签与卡片结构。
2. “技术分析结论”首期所有策略字段为空，显示 `--`，不使用 mock 文案。
3. 多周期矩阵中的九转、MACD/KDJ 解释性文案首期为空。
4. 日线趋势通道可显示后端返回的客观状态和轨道值。
5. 当前建议映射：右侧“上轨 / 中轴 / 下轨”使用最新短期通道的 `upper / (upper+lower)/2 / lower`；长期通道仅在主图作为次级轨道展示。该映射必须在编码门禁评审时最终签字。
6. 生产环境的 60 分钟、30 分钟技术行显示 `--`；本地分钟数据可用也不自动生成技术结论文案。

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
| 日线报价 | `core_serving.index_daily_serving` | 最新已完成交易日 | 无行 EMPTY |
| 日线技术因子 | `core_serving.index_factor_pro` | bfq/指数无复权 | 缺列或缺行 PARTIAL，不补 0 |
| 权重 | `core_serving.index_weight` | 最新批次且不晚于贡献日 | 无批次 EMPTY |
| 成分股名称 | `core_serving.security_serving` | 按 `con_code` 补名 | 展示 code |
| 成分股涨跌幅 | `core_serving.equity_daily_bar` | 与贡献日同日 | contributionPoint 为 null |
| 趋势通道 | `core_serving.index_daily_serving` + 后端计算器 | 日线 25/90 EMA 双通道 | 模块 PARTIAL/ERROR |
| 本地分钟行情 | Lake Silver `major_index_mins` | 仅 local capability 开启 | 模块 EMPTY/DELAYED |
| 本地分钟指标 | Lake Gold `major_index_mins_technical` | 仅 local capability 开启 | 指标缺失保持 null |

日线技术因子在进入编码前必须完成 10 指数生产覆盖审计；未通过时不得以 API 内临时计算或前端计算替代。

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
| LOADING | 保留页面骨架与顶部栏，主图和右栏显示加载态 |
| READY | 日线主图与当前右栏页签可用 |
| PARTIAL | 主事实可展示，缺失因子/贡献点/趋势模块显示 `--` 和局部提示 |
| DELAYED | 展示最近可用数据及数据日期，不伪装为当前日 |
| EMPTY | 保留页面结构，显示无数据，不回填 mock |
| ERROR | 显示可重试错误态，不回填 mock |
| FORBIDDEN | 进入无权限状态；未登录沿用登录跳转 |

页签状态彼此独立：权重接口失败不得清空已加载日线；趋势通道失败不得阻断基本行情；page-init 找不到标的或无权限属于页面级失败。页面级错误提供整页重试；权重、趋势和分钟错误只在对应模块提供局部重试。权重 PARTIAL 保留可用行并将缺失贡献显示为 `--`，不得删除整行或补 0。

## 7. API 需求层契约

正式路由：

```text
GET /api/v1/wealth/market/index-detail/page-init
GET /api/v1/wealth/market/index-detail/kline
GET /api/v1/wealth/market/index-detail/weights
GET /api/v1/wealth/market/index-detail/trend-channel
```

本地条件路由：

```text
GET /api/v1/wealth/market/index-detail/minutes
GET /api/v1/wealth/market/index-detail/minute-indicators
```

要求：

1. DTO 使用 lowerCamelCase。
2. `kline` 不接受 `adjustment` 参数，也不返回复权选项。
3. `weights` 不接受 `limit`，一次返回选定 `weightTradeDate` 的完整批次；`rows.length` 必须等于 `coverage.totalCount`，禁止静默截断。
4. `trend-channel` 只接受名单内指数与 `period=day`。
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

## 9. 验收标准

1. 10 张主要指数卡都能进入正确路由，浏览器前进/后退可用。
2. 默认日线加载真实数据，页面中不存在“前复权”。
3. 生产环境除日线外的周期不可切换；本地只解锁 capability 宣布的分钟频率。
4. 三个右侧页签可切换，并保留各自已加载状态。
5. 权重按源值降序展示完整批次，表头固定、首屏 10 行、内部滚动可达末行；生产验收的权重批次为 `2026-07-31`。
6. 贡献点公式、空值、估算标识、日期字段与说明文字全部可见且可复算。
7. 技术结论与九转没有 mock、默认文案或自动交易动作。
8. 趋势通道由后端输出，前端只对齐日期并绘制。
9. loading/error/empty/partial/permission 均有真实接口测试和前端展示测试。
10. Figma Loaded 页在 1600×1200 基准下通过像素验收，且不破坏当前股票详情页。

## 10. 待评审项

1. 确认“通道关键位置”采用短期通道 `upper / midpoint / lower`，长期通道只作为主图次级轨道。
2. 确认“较昨日”表示成交额环比，而不是成交量环比。
3. 确认最终像素台账是否把 Weights/Technical Loaded 根画板从 Cover 页归位到 `08` 页面；这不改变上述状态语义。

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1.1 | 2026-08-11 | 权重改为完整批次、固定 10 行视窗与内部滚动；确认 09 页面并补异常状态口径 | Codex |
| v1 | 2026-08-10 | 基于 Figma、当前代码、生产权重审计与用户已拍板口径形成首版草案 | Codex |
