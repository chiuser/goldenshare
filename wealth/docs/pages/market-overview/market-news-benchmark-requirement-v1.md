# 市场总览｜新闻速览与个股新闻标杆需求 v1（benchmark-requirement）

> 用途：冻结“新闻速览 + 个股新闻”模块的业务口径、页面位置、数据边界和验收规则。  
> 阶段：需求冻结前。  
> 产物性质：业务事实源（不是实现细节文档）。

---

## 1. 目标与定位

1. 模块目标：在市场总览首屏上方提供两组客观资讯列表，帮助用户快速看到市场新闻和个股新闻。
2. 用户价值：用户打开市场总览后，可以在不跳转的情况下快速扫到最新资讯标题，并继续观察下方行情模块。
3. 业务定位：新闻模块是市场总览页的客观事实补充，不承担新闻详情页、外链跳转、主观解读或交易建议。
4. 最新 UI 参考：`wealth/docs/reference/showcase/market-overview-v1.8.html`。旧 `market-overview-v8.html` 属于已废弃历史口径，不再作为新闻模块布局依据。

---

## 2. 范围与边界

### 2.1 本期覆盖

1. 新增两个独立新闻板块：
   - `新闻速览`
   - `个股新闻`
2. 页面位置：
   - `新闻速览` 位于 `今日市场客观总结` 正上方，并与其等宽；
   - `个股新闻` 位于 `主要指数` 正上方，并与其等宽；
   - 两个新闻板块高度一致。
3. 每个新闻板块展示新闻时间和新闻标题。
4. 默认可见条数为 10 条，条数由运营配置控制，用户不可配置。
5. 两个新闻板块默认向上滚动。
6. hover 当前新闻板块时，只暂停当前板块；另一个新闻板块继续滚动。
7. hover 当前新闻板块后，当前板块允许手动滚动查看超出可见范围的新闻。
8. 新闻标题单行展示，超出宽度显示省略号。
9. 新闻 item 本期不可点击，不跳转详情页，不打开外链。
10. 保持市场总览其它模块内部内容不变。
11. 面板视觉以 `wealth/docs/reference/showcase/market-overview-v1.8.html` 中 `.market-news-panel` / `.market-news-viewport` / `.market-news-item` 为参考：面板标题为横向标题，左侧有品牌色小圆点，右侧展示 `10 条可见` 这类可见条数说明，列表区域是深色内嵌 viewport，单行 item 使用 `时间 + 标题` 两列布局。

### 2.2 本期不覆盖

1. 不做新闻详情页。
2. 不打开外部新闻链接。
3. 不在 PageHeader 或 TopMarketBar 中放置统一快讯条。
4. 不保留 Review v8 的 `ICON 预留位 ｜ 新闻速览 ｜ 个股新闻` 横向结构。
5. 不显示竖排标题。
6. 不对新闻标题中的股票涨跌自动套用红绿行情色。
7. 不做新闻推荐、新闻优先级算法、个性化订阅。
8. 不做用户侧配置。
9. 不改动今日市场客观总结、主要指数、涨跌分布、市场风格、成交额总览、大盘资金流向、榜单速览、涨跌停统计与分布、连板天梯、板块速览内部逻辑。

### 2.3 与其他模块边界

1. 上游依赖：
   - 新闻模块统一查询出口：`core_serving_light.news`。
   - `core_serving_light.news` 是新闻快讯的 serving light 出口，底层来源为 Tushare `news`。
   - `个股新闻`：筛选 `channels = '公司'` 的新闻快讯。
   - `新闻速览`：筛选 `channels IS DISTINCT FROM '公司'` 的新闻快讯。
   - 运营配置中心：控制可见条数和源选择。
2. 下游消费者：
   - `MarketOverviewNewsPanelGroup`
   - 页面级 debug 面板
3. 与相邻模块职责分割：
   - `新闻速览` 只负责资讯标题流，不参与市场总结文案生成。
   - `个股新闻` 只负责 `core_serving_light.news.channels = '公司'` 的公司频道新闻标题流，不参与榜单、连板、个股行情卡片展示。
   - 新闻模块不改变 `summary` 与 `majorIndices` 的事实字段和 API 契约。

---

## 3. 核心原则（硬约束）

1. 规则归属：后端定义新闻来源、排序、截断、状态；前端只展示。
2. 契约归属：本三件套是新闻模块的当前事实源；历史 update 快照只作为一次性输入材料，不作为实现契约。
3. 配置归属：展示条数、源选择等运营配置必须走策略配置中心；不允许写死在组件里。
4. 禁止事项：
   - 禁止复活顶部统一快讯条；
   - 禁止 item 可点击；
   - 禁止前端自行混合、排序或截断新闻事实；
   - 禁止使用旧 `/api/market/home-overview` 或旧 `marketOverviewNewsBlocks` 聚合字段直接编码。

### 3.1 跨模块抽象门禁原则（需求层冻结）

1. 事实源单一：新闻速览与个股新闻分别由后端独立接口产出，前端不得自行从整页 mock 或其它模块拼装。
2. 契约冻结：`visibleItemCount/newsId/publishTime/displayTime/title/category/source/subject/clickable` 字段在本期冻结。
3. 配置一致性：配置文件、文档、代码读取的 key 必须一致，默认 `visibleItemCount=10`。
4. 默认行为显式：新闻不跟随页面全局交易日；查询窗口固定为“当前自然日的前一天 00:00:00 到当前服务器时间”，时区 `Asia/Shanghai`。
5. 排序筛选确定性：候选集必须先删除 `content` 为空的新闻，再按 `content` 严格去重，每个 `content` 只保留发布时间最新的一条，最后按 `publishTime desc` 排序。
6. 性能预算前置：单次接口 P95 `< 300ms`，payload `< 40KB`。
7. 可观测标准化：异常码统一登记，debug 输出结构与其它市场总览模块一致。
8. 用户可见结果优先：验收以两个新闻板块的标题、时间、省略、滚动和不可点击为主。

---

## 4. 业务对象模型（非代码，先语义）

### 4.1 `MarketNewsPanelGroup`

市场总览页面中的新闻组 ViewModel，由两个独立 API 响应组装而成。它不是后端单一接口的返回根对象。

| 字段 | 含义 | 单位 | 可空 | 产出方 | 缺失策略 |
|---|---|---|---|---|---|
| `newsWindow` | 本次新闻模块自然时间窗口 | 时间区间 | 否 | 后端 | 不允许缺失 |
| `visibleItemCount` | 每个新闻板块默认可见条数 | 条 | 否 | 运营配置 + 后端 | 配置缺失时模块 error |
| `updatedAt` | 新闻组前端组装时间或两个接口中较新的更新时间 | 时间 | 否 | 前端 adapter | 不允许缺失 |
| `newsBriefs` | 新闻速览列表，来自 `GET /api/v1/wealth/market/news/briefs` | - | 否 | 后端 | 可为空数组 |
| `stockNews` | 个股新闻列表，来自 `GET /api/v1/wealth/market/news/stocks` | - | 否 | 后端 | 可为空数组 |
| `sortRule` | 排序规则说明 | - | 否 | 后端 | 固定 `publishTime_desc_priority_desc` |
| `clickablePolicy` | 点击策略 | - | 否 | 后端 | 固定 `disabled` |

### 4.2 `NewsListPanel`

单个新闻板块 API 的返回对象。新闻速览和个股新闻共用结构，但接口路径与筛选规则不同。

| 字段 | 含义 | 单位 | 可空 | 产出方 | 缺失策略 |
|---|---|---|---|---|---|
| `windowStartAt` | 本次查询窗口开始时间 | 时间 | 否 | 后端 | 昨日 00:00:00，时区 `Asia/Shanghai` |
| `windowEndAt` | 本次查询窗口结束时间 | 时间 | 否 | 后端 | 当前服务器时间，时区 `Asia/Shanghai` |
| `panelKey` | 板块 key：`newsBriefs` 或 `stockNews` | - | 否 | 后端 | 不允许缺失 |
| `visibleItemCount` | 当前板块默认可见条数 | 条 | 否 | 运营配置 + 后端 | 配置缺失时模块 error |
| `updatedAt` | 当前板块数据组装时间 | 时间 | 否 | 后端 | 不允许缺失 |
| `items` | 当前板块新闻列表 | - | 否 | 后端 | 可为空数组 |
| `sortRule` | 排序规则说明 | - | 否 | 后端 | 固定 `publishTime_desc_priority_desc` |
| `clickablePolicy` | 点击策略 | - | 否 | 后端 | 固定 `disabled` |

### 4.3 `NewsPanelItem`

单条新闻展示对象。

| 字段 | 含义 | 单位 | 可空 | 产出方 | 缺失策略 |
|---|---|---|---|---|---|
| `newsId` | 新闻稳定标识 | - | 否 | 后端 | 缺失行丢弃 |
| `publishTime` | 新闻发布时间，标准 datetime | 时间 | 否 | 后端 | 缺失行丢弃 |
| `displayTime` | 前端展示时间，格式 `MM-DD HH:mm:ss` | 时间文本 | 否 | 后端或 adapter | 缺失时前端 formatter 从 `publishTime` 格式化 |
| `title` | 新闻标题 | 文本 | 否 | 后端 | 缺失行丢弃；不得由前端拼 |
| `category` | 新闻类别：`market` 或 `stock` | - | 否 | 后端 | 不允许缺失 |
| `source` | 新闻来源 | 文本 | 是 | 后端 | 本期不展示，debug 可见 |
| `subject` | 关联股票主体，仅个股新闻可有 | - | 是 | 后端 | 缺失时仍展示新闻标题 |
| `priority` | 排序辅助优先级 | 数值 | 是 | 后端 | 缺失按 `0` 处理 |
| `url` | 详情链接预留 | URL | 是 | 后端 | 本期不使用 |
| `clickable` | 是否可点击 | 布尔 | 否 | 后端 | 本期固定 `false` |

### 4.4 `NewsSubjectRef`

个股新闻关联主体对象。

| 字段 | 含义 | 单位 | 可空 | 产出方 | 缺失策略 |
|---|---|---|---|---|---|
| `subjectType` | 主体类型，固定 `stock` | - | 否 | 后端 | 不允许缺失 |
| `subjectCode` | 股票代码 | - | 否 | 后端 | 缺失则不返回 subject |
| `subjectName` | 股票名称 | - | 是 | 后端 | 缺失时只保留代码 |

---

## 5. 数据来源与映射（事实层）

| 业务字段 | 来源表 | 来源列 | 转换规则 | 备注 |
|---|---|---|---|---|
| `newsBriefs.newsId` | `core_serving_light.news` | `row_key_hash` | 原样 | 新闻快讯稳定 key |
| `newsBriefs.publishTime` | `core_serving_light.news` | `news_time` | datetime -> ISO/标准 datetime | 主排序字段 |
| `newsBriefs.title` | `core_serving_light.news` | `title` / `content` | 优先用非空 title；title 缺失时后端截取 content 前 80 字；前端不得拼标题 |
| `newsBriefs.category` | `core_serving_light.news` | `channels` | `channels IS DISTINCT FROM '公司'` 进入 `market` | 非公司频道进入新闻速览 |
| `newsBriefs.source` | `core_serving_light.news` | `src` | 原样 | 新闻来源，不是数据源 `source` |
| `stockNews.newsId` | `core_serving_light.news` | `row_key_hash` | 原样 | 新闻快讯稳定 key |
| `stockNews.publishTime` | `core_serving_light.news` | `news_time` | datetime -> ISO/标准 datetime | 主排序字段 |
| `stockNews.title` | `core_serving_light.news` | `title` / `content` | 优先用非空 title；title 缺失时后端截取 content 前 80 字；前端不得拼标题 |
| `stockNews.category` | `core_serving_light.news` | `channels` | `channels = '公司'` 进入 `stock` | 公司频道进入个股新闻 |
| `stockNews.source` | `core_serving_light.news` | `src` | 原样 | 新闻来源 |
| `updatedAt` | 后端组装 | `serverTime` 或查询最大时间 | 统一格式化 | 不代表源端每条新闻发布时间 |

补充：

1. `core_serving_light.news` 是 Tushare `news` 的 serving light 查询出口，接口文档见 `docs/sources/tushare/大模型语料专题数据/0143_新闻快讯.md`。
2. 本期新闻速览与个股新闻都只读 `core_serving_light.news`，不直接读 `raw_tushare.news`，不使用 `anns_d`、`major_news` 或其它新闻/公告源。
3. 查询候选集必须满足 `content` 非空；`content IS NULL` 或 trim 后为空字符串的记录直接剔除。
4. 去重以 `content` 为唯一口径；相同 `content` 只保留 `news_time` 最新的一条。
5. 最终返回顺序为去重后的 `news_time DESC`。
3. `channels = '公司'` 是个股新闻板块的唯一分类规则；非公司频道进入新闻速览。
4. 编码前必须确认线上 `core_serving_light.news.channels` 的真实取值包含 `公司`，并补充样本 SQL；若真实取值不同，必须先停下重新确认口径。

---

## 6. 状态语义

1. 页面级状态：沿用市场总览页面状态归并规则。
2. 模块级状态：仅 debug mode 展示。
3. `ready`：
   - 至少一个新闻板块有可展示项；
   - 配置有效；
   - 查询无异常。
4. `empty`：
   - 两个新闻板块均为空；
   - 不能用旧日新闻静默回填。
5. `delayed`：
   - 目标日期内无数据，但存在更早新闻可查时，仅在 debug 中标记，不自动混入旧新闻。
6. `partial`：
   - 两个板块中只有一个有数据；
   - 或配置要求 10 条但源端不足 10 条。
7. `error`：
   - 配置缺失/非法；
   - 查询失败；
   - 必需字段缺失导致无法构造任何可展示项。

---

## 7. 异常语义

1. 异常对象结构：`module/code/severity/message/details`。
2. 用户可见策略：正式页面不直接展示异常码；模块失败时展示 error 样式。
3. debug 可见策略：`debug=1` 时在页面调试面板展示结构化异常。
4. 异常码前缀：`NEWS_*`。

异常码必须登记到 `wealth/docs/system/exception-code-registry.md` 后才能进入代码。

---

## 8. API 契约（需求层）

1. 接口路径：
   - 新闻速览：`GET /api/v1/wealth/market/news/briefs`
   - 个股新闻：`GET /api/v1/wealth/market/news/stocks`
2. 请求参数：
   - `market?: "CN_A"`，默认 `CN_A`
   - `debug?: 0 | 1`
3. 响应结构：
   - `newsWindow`
   - `pageStatus`
   - 新闻速览接口返回 `newsBriefs`
   - 个股新闻接口返回 `stockNews`
   - `debugInfo?`
4. 字段命名规则：
   - lowerCamelCase；
   - 新闻主体对象 `subject` 为可选字段；本期基于 `core_serving_light.news` 不从标题解析股票代码，不强制返回 `subject`；
   - 不使用旧 `marketOverviewNewsBlocks` 作为新模块根对象；
   - 页面可把两个接口响应组装为 `MarketNewsPanelGroup`，但后端不提供单一 `marketNews` 大聚合接口。
5. 向后兼容策略：
   - 不兼容旧 `/api/market/home-overview`；
   - 不保留旧 `marketNewsFlash`、`iconType` 或顶部快讯字段。

---

## 9. 验收标准

1. 功能验收：
   - 页面首屏上方出现两个独立新闻板块；
   - `新闻速览` 正下方是 `今日市场客观总结`；
   - `个股新闻` 正下方是 `主要指数`；
   - 两个新闻板块等高、与下方对应模块等宽；
   - 默认可见 10 条，超过 10 条自动滚动。
2. 语义验收：
   - 新闻 item 只展示时间和标题；
   - 时间格式为 `MM-DD HH:mm:ss`；
   - item 不可点击、不显示 pointer；
   - 标题超长时单行省略。
3. 状态验收：
   - loading/ready/error 三态可见；
   - empty/partial/delayed 在 debug 中可追踪；
   - 真实 API 未返回前不得展示 mock 数据冒充 ready。
4. 异常验收：
   - 异常码全部来自注册表；
   - 配置缺失、源数据为空、查询失败均有明确表现。

### 9.1 `v1.8` 视觉校准点

1. 新闻面板容器：
   - 高度由 `visibleItemCount × itemHeight` 推导；
   - `visibleItemCount=10` 时列表高度为 `220px`；
   - item 高度为 `22px`；
   - 标题栏高度为 `28px`；
   - 面板内边距参考 `10px 12px`。
2. 新闻列表：
   - 时间列宽参考 `96px`；
   - 时间字号参考 `11px`；
   - 标题字号参考 `12px`；
   - item hover 仅改变当前 item 背景和文字强度，不进入点击态。
3. 滚动行为：
   - 默认向上滚动；
   - hover 当前 viewport 时，当前 viewport 可手动滚动；
   - hover 当前面板不得暂停另一个新闻面板。

### 9.2 参考 case（可复用）

1. 如果复活顶部统一快讯条，说明吸收了废弃方案，验收必须失败。
2. 如果 hover 一个新闻板块导致另一个也暂停，说明同步控制错误，验收必须失败。
3. 如果新闻 item 出现点击态或跳转，说明违反 P0 点击规则，验收必须失败。
4. 如果标题换行撑高板块，说明布局约束失效，验收必须失败。
5. 如果前端自行从 content 截标题，说明事实字段拼装下沉到了前端，验收必须失败。

---

## 10. 已确认清零项

1. 上一版顶部中间统一快讯条已作废。
2. 新闻板块不放在 PageHeader 中间区域。
3. 不需要 ICON 预留位。
4. 不使用竖排标题。
5. 默认展示 10 条，由运营配置控制。
6. P0 新闻 item 不可点击。
7. 后续如需新闻详情或外链跳转，必须重新开需求。

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-14 | 初版：吸收 Review v9 新闻板块有效需求，并按当前 wealth 模块化 API 口径重写 | Codex |
| v1.1 | 2026-05-14 | 校准最新 UI 参考为 `market-overview-v1.8.html`，补充新闻面板视觉和滚动验收点 | Codex |
