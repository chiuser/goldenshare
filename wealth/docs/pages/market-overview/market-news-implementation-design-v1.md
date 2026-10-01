# 市场总览｜新闻速览、新闻通讯与阅读器技术实施方案 v3

> 稳定文档路径沿用 `market-news-implementation-design-v1.md`，正文版本升级为 v3。
> 基线状态：已实现并结案（2026-09-01 用户确认）；双来源新闻、阅读器、标题提取、新闻通讯来源过滤与同花顺尾注清理均已完成。
> 图片增强状态：M2 本地实现、自动化测试与正式 PostgreSQL 只读校准已完成（2026-10-01）；登录后浏览器含图验收及部署尚未完成。
> 日期：2026-08-24；标题提取及新闻通讯展示策略确认日期：2026-08-27；空标题正文提取补充确认日期：2026-08-28；基线结案日期：2026-09-01；图片增强方案冻结日期：2026-10-01。
> 代码级设计：[market-news-reader-low-level-design-v1.md](./market-news-reader-low-level-design-v1.md)。
> 阅读器视觉与交互基线：[market-news-reader-implementation-design-v1.md](./market-news-reader-implementation-design-v1.md)。

## 1. 目标

本轮重组市场总览首页的两列新闻数据，并保持现有 PC Web 弹窗阅读体验：

1. `新闻速览` 展示 `core_serving_light.news` 当前自然时间窗口内的全部可读快讯，不再按 `channels` 分类过滤。
2. 原 `个股新闻` 更名为 `新闻通讯`，数据源切换为 `core_serving_light.major_news`。
3. 两列新闻均可点击打开同一个新闻阅读器。
4. `major_news` 优先展示数据库内的正文：正文是 HTML 时按 HTML 阅读；正文不是 HTML 时按纯文本阅读。
5. `major_news.url` 只作为原文溯源事实保留，不作为阅读器的主动网页载荷，不自动打开、不嵌入 iframe、不由后端抓取。
6. `news` 继续沿用现有正文识别规则：正文自身是 URL 时使用 URL 模式，否则依次识别 HTML 和纯文本。
7. `新闻速览` 优先使用源 `title`；源 `title` 为空时使用正文作为标题候选。候选文本若以完整的 `【...】` 开头，列表和阅读器标题只展示第一组括号内的非空文本，不展示右括号后的摘要正文。
8. `新闻通讯` 排除 `src` trim 后等于 `新浪财经` 的记录，列表、状态观测和详情直达均不得绕过该来源门禁。
9. `新闻通讯` 的同花顺正文仅在响应展示层移除固定推广文字“关注同花顺财经（ths518），获取更多机会”，兼容源端有无句号，不回写数据库。

本轮不是给原有 `channels='公司'` 分类打补丁，而是一次完整的数据源和契约替换。旧 `/stocks`、`stockNews`、`StockNewsQuery` 及相关前端命名必须在同一开发批次清零，不保留兼容路由或别名字段。

## 2. 已确认的产品口径

| 模块 | 标题 | 列表事实源 | 列表范围 | 阅读器正文 | URL 语义 |
|---|---|---|---|---|---|
| 左列 | 新闻速览 | `core_serving_light.news` | 现有自然时间窗口内全部频道 | `news.content` 按 URL > HTML > TEXT 识别 | 仅当 `content` 本身是 URL 时作为主动载荷 |
| 右列 | 新闻通讯 | `core_serving_light.major_news` | 现有自然时间窗口内且来源不是新浪财经的长篇新闻通讯 | 优先展示 `major_news.content` 中的 HTML；非 HTML 正文按 TEXT；同花顺固定推广文字在响应层移除 | `major_news.url` 仅作 `originalUrl` 溯源事实 |

其它冻结口径：

1. 两列继续使用“昨日 00:00 至当前服务器时间”的 `Asia/Shanghai` 自然时间窗口，不接收 `tradeDate`。
2. 两列继续按发布时间倒序，标题相同只保留最新一条；相同发布时间以 `row_key_hash ASC` 稳定选择。
3. 两列继续使用策略配置中的 `visibleItemCount=10` 和 `queryLimit=300`，不新增配置项。
4. 不跨 `news` 与 `major_news` 做标题相似度、正文相似度或 URL 去重。快讯与长篇通讯可以同时出现。
5. 首页列表只返回轻量标题信息，不返回正文 HTML。
6. 股票详情页现有“个股新闻”是另一个独立模块，本轮不改名、不换源、不改接口。
7. 阅读器的弹窗尺寸、焦点捕获、背景不可点击、Escape、关闭后焦点恢复、HTML 清洗和 URL sandbox 规则保持现状。
8. 标题提取只作用于 `contentSource=news` 的新闻速览：`title` 非空时只检查 `title`；`title` 为空时只检查 trim 后原始 `content` 的开头，不扫描正文中部。该规则不改变新闻通讯、股票详情新闻或数据库中的原始字段。
9. 来源过滤只采用 `trim(src) == '新浪财经'` 的确定性口径，不做别名、模糊匹配或配置化扩展。
10. 同花顺尾注清理只采用 `trim(src) == '同花顺'` 且正文包含固定推广文字的确定性口径；其它来源即使正文出现同一句话也不修改。

## 3. 开发前代码审计（历史基线）

本节记录双来源改造开始前的代码状态和目标差异，仅用于追溯，不代表结案后的当前实现。当前实现以第 5～11 节合同及对应代码、测试为准。

### 3.1 开发前后端

| 开发前代码 | 开发前事实 | 与目标的差异 |
|---|---|---|
| `market_news_query.py` | 查 `NewsLight`，排除 `channels='公司'` | 应删除频道过滤，改为所有可读 `news` |
| `stock_news_query.py` | 查 `NewsLight`，只取 `channels='公司'` | 应删除，替换为 `MajorNewsQuery` |
| `news_query_service.py` | `newsBriefs/stockNews` 两套 panel | `stockNews` 应完整替换为 `newsCommunications` |
| `news_briefs.py` / `stock_news.py` | 暴露 `/briefs` 和 `/stocks` | `/stocks` 应删除，新增 `/communications` |
| `news_reader_query.py` | 详情只按 ID 查 `NewsLight` | 无法读取 `major_news`，必须按显式来源查询 |
| `news_reader_content_resolver.py` | 所有正文统一按 URL > HTML > TEXT | 只适用于 `news`；`major_news` 必须禁止 URL 抢占 HTML 正文 |
| `news_item.py` | `/items/{news_id}` 不带来源 | 两表 ID 无法安全归属，必须增加来源路径参数 |

### 3.2 开发前前端

| 开发前代码 | 开发前事实 | 目标修改 |
|---|---|---|
| `marketNewsApi.ts` | `/briefs`、`/stocks`，`stockNews` | 改为 `/briefs`、`/communications`，`newsCommunications` |
| `marketNewsAdapter.ts` | 标题为“新闻速览/个股新闻” | 改为“新闻速览/新闻通讯” |
| `MarketOverviewPage.tsx` | 维护 `stockNews*` 状态和请求 | 全量重命名为 `newsCommunications*` |
| `MarketNewsPanelGroup.tsx` | 右列 prop 为 `stockNews` | 改为 `newsCommunications` |
| `useMarketNewsReader.ts` | 详情请求只传 `newsId` | 必须同时传 `contentSource` |
| `marketNewsReaderApi.ts` | 请求 `/items/{newsId}` | 改为 `/items/{contentSource}/{newsId}` |

当前阅读器共享 UI 本身不依赖具体新闻表，可以继续复用；需要变更的是列表合同、详情路由和来源解析，不需要重写弹窗。

## 4. 数据审计结论

审计时点为 2026-08-24，正式数据库只读统计以 2026-08-23 自然日为样本：

| 指标 | `news` | `major_news` |
|---|---:|---:|
| 当日行数 | 1,203 | 522 |
| 非空标题 | 780 | 522 |
| 标题缺失 | 423 | 0 |
| 平均正文大小 | 约 444 bytes | 约 11,398 bytes |
| URL 非空 | 无独立 URL 列 | 522 |
| 正文识别为 HTML | 非主要形态 | 522 |

补充证据：

1. `major_news` 正文大小中位数约 11.5 KiB，P95 约 21.6 KiB，最大约 55.6 KiB，样本均低于现有 256 KiB 阅读器上限。
2. `major_news` 522 条样本正文全部可识别为 HTML，说明库内正文足以承担主要阅读体验。
3. 两表精确标题交集只有 26 条，占 `major_news` 约 4.98%；相似度大于等于 0.85 的标题也只有约 6.5%。因此不能把 `major_news` 当作 `news` 的稳定子集，也不做跨源模糊去重。
4. 2026-08-23 `news.channels='公司'` 只有 180 条，其它频道 1,023 条。取消频道过滤后，新闻速览会覆盖完整快讯流。
5. 两个来源截至审计时点都在持续更新，适合继续沿用当前自然时间窗口和 10 分钟前端刷新节奏。

这些统计只证明本次来源选型和载荷预算，不作为永久业务阈值，也不进入运行时代码。

## 5. 目标数据流

```text
core_serving_light.news
  -> MarketNewsQuery（无 channels 过滤）
  -> GET /api/v1/wealth/market/news/briefs
  -> 新闻速览
  -> GET /api/v1/wealth/market/news/items/news/{newsId}
  -> news.content: URL > HTML > TEXT

core_serving_light.major_news
  -> MajorNewsQuery
  -> GET /api/v1/wealth/market/news/communications
  -> 新闻通讯
  -> GET /api/v1/wealth/market/news/items/major_news/{newsId}
  -> major_news.content: HTML > TEXT
  -> major_news.url: originalUrl only
```

详情查询禁止：

1. 只按 `newsId` 同时扫两张表。
2. 第一张表查不到后自动回退第二张表。
3. 按标题、URL 或发布时间猜来源。
4. 从 `major_news.url` 下载、代理或 iframe 加载原文。

来源必须由列表响应中的 `contentSource` 明确下发，并由前端原样带回详情路由。

## 6. 目标 API

### 6.1 新闻速览

```http
GET /api/v1/wealth/market/news/briefs?market=CN_A&debug=0
```

返回根字段保持 `newsBriefs`。

### 6.2 新闻通讯

```http
GET /api/v1/wealth/market/news/communications?market=CN_A&debug=0
```

返回根字段固定为 `newsCommunications`，不继续使用 `stockNews`。

### 6.3 新闻详情

```http
GET /api/v1/wealth/market/news/items/{content_source}/{news_id}
```

`content_source` 只允许：

```text
news
major_news
```

旧 `/items/{news_id}` 与 `/news/stocks` 在同一批次删除，不保留 alias。

### 6.4 列表项合同

```ts
interface NewsPanelItem {
  newsId: string;
  contentSource: "news" | "major_news";
  publishTime: string;
  displayTime: string;
  title: string;
  category: "brief" | "communication";
  source: string | null;
  readerMode: "URL" | "HTML" | "TEXT";
  clickable: true;
}
```

旧 `subject` 和恒定为 0 的 `priority` 不再属于首页新闻合同；`sortRule` 收敛为 `publishTime_desc`。前端没有消费者依赖这两个字段，开发时必须同时删除后端 DTO、前端 type 和 fixture，不保留兼容字段。

### 6.5 详情合同

```ts
interface NewsReaderItem {
  newsId: string;
  contentSource: "news" | "major_news";
  title: string;
  source: string | null;
  publishTime: string;
  readerMode: "URL" | "HTML" | "TEXT";
  url: string | null;
  html: string | null;
  content: string | null;
  originalUrl: string | null;
}
```

载荷互斥规则保持不变：`url/html/content` 中只能有一个与 `readerMode` 对应的非空字段。

`originalUrl` 是溯源元数据，不参与互斥载荷：

| 来源 | 主动载荷 | `originalUrl` |
|---|---|---|
| `news` | 由 `content` 识别出的 URL/HTML/TEXT | `null` |
| `major_news` | `content` 对应的 HTML 或 TEXT；绝不为 URL | `major_news.url` 的 trim 后值，可为空 |

当前 UI 不展示原文链接，不把 `originalUrl` 写入 DOM，不允许点击跳转。该字段仅用于保留来源事实和后续经单独评审的能力扩展。

## 7. 查询规则

### 7.1 新闻速览

1. 表：`NewsLight`。
2. 时间：`news_time` 位于统一 `newsWindow`。
3. 正文：trim 后非空。
4. 不再读取或判断 `channels`。
5. 展示标题：按 7.1.1 的统一规则处理；先使用 trim 后非空 `title` 作为候选，`title` 为空时改用 trim 后原始 `content` 作为候选。候选未命中开头 `【...】` 时，继续使用原有 `title` 或正文前 80 字 fallback。
6. 去重：按最终展示标题分组，只保留最新记录。
7. 排序：`news_time DESC, row_key_hash ASC`。
8. 上限：策略配置 `queryLimit`，当前为 300。

### 7.1.1 新闻速览开头全角方头括号标题提取

仅对 `core_serving_light.news` 使用以下确定性规则：

1. 先对原始 `title` 去除首尾空白；结果非空时，它是唯一标题候选，不再检查正文。
2. 原始 `title` 为空时，对原始 `content` 去除首尾空白，并把结果作为标题候选。
3. 只有候选文本以全角左方头括号 `【` 开头、并且后续存在第一个全角右方头括号 `】` 时，才进入提取分支。
4. 取第一组 `【` 与 `】` 之间的文本并再次去除首尾空白；结果非空时，它就是最终展示标题，右书名号后的摘要、来源提示或其它文本全部丢弃。
5. 缺少右书名号、括号内容为空、候选不是以 `【` 开头时，不做猜测：`title` 非空则继续使用原 `title`，`title` 为空则继续使用既有正文前 80 字 fallback。
6. 只检查候选开头，不扫描正文中部；正文中部的 `【...】` 不得被提取。
7. 标题提取必须发生在同来源标题去重之前。因此展示标题相同的新闻视为同一标题，只保留发布时间最新的一条。

示例：

```text
原始 title:
【商务部等9部门：支持航空保税维修绿色化发展】商务部等9部门发布关于促进航空保税维修高质量发展的意见。其中提到……

最终 title:
商务部等9部门：支持航空保税维修绿色化发展
```

对于命中该规则的同一新闻，列表接口和详情接口必须返回同一个最终 `title`。该规则由后端统一执行，API 不新增 `displayTitle` 字段；`MarketNewsPanel` 和 `NewsReaderDialog` 只渲染接口返回值，不在前端复制括号解析逻辑。

空标题生产数据示例：

```text
原始 title:
<empty>

原始 content:
【政策与资本加持 量子计算“AlphaGo时刻”越来越近】中国科学院院士、上海交通大学量子科技学院院长丁洪……

最终 title:
政策与资本加持 量子计算“AlphaGo时刻”越来越近
```

### 7.2 新闻通讯

1. 表：`MajorNewsLight`。
2. 时间：`pub_time` 位于统一 `newsWindow`。
3. 来源：排除 `trim(src) == '新浪财经'`；该条件同时用于列表候选、`observed_at` 和详情主键查询。
4. 标题：trim 后非空。
5. 正文：trim 后非空，且详情请求仍受 256 KiB 上限保护。
6. 去重：按 trim 后标题分组，只保留最新记录。
7. 排序：`pub_time DESC, row_key_hash ASC`。
8. 列表 `source` 使用 `src`，不得误用技术来源字段 `source`。
9. 上限：同一策略配置 `queryLimit`，当前为 300。
10. 不检查 URL 可达性，不访问外网。

### 7.3 状态

两个接口独立计算 `READY/DELAYED/EMPTY/ERROR`，一个来源失败不得清空另一个面板。现有 `MarketNewsStatusResolver`、自然时间窗口和 debug 结构继续复用，module key 改为：

```text
newsBriefs
newsCommunications
```

`NEWS_CHANNEL_RULE_INVALID` 随频道分类删除而退役。其它通用新闻和阅读器异常码继续使用，不新增来源猜测或跨表回退异常。

## 8. 阅读器内容策略

### 8.1 `news`

继续使用现有安全解析：

```text
content 自身是合法 HTTP(S) URL -> URL
否则包含允许识别的 HTML 结构 -> HTML
否则 -> TEXT
```

### 8.2 `major_news`

固定使用库内 `content`：

```text
content 包含 HTML 结构 -> HTML
否则 -> TEXT
```

在执行 HTML/TEXT 分类前，按以下顺序构造展示正文：

1. 先对数据库原始正文执行既有非空和 256 KiB 校验，不能通过清理尾注绕过安全上限。
2. 仅当 `trim(src) == '同花顺'` 时，移除固定可见文字“关注同花顺财经（ths518），获取更多机会”，并兼容紧随其后的中文句号。
3. 不截断整篇文章，不假设推广文字位于字符串末尾；正式数据中该文字后仍可能存在 HTML 标记和脚本。
4. 不解析、不重写数据库原文，其它来源保持逐字不变；清理后若正文不可读，按现有空正文错误处理。

即使 `major_news.url` 非空，也不得改变正文模式。若 `content` 本身恰好长得像 URL，也按 TEXT 处理，不把它升级为外部网页加载。

所有 HTML 仍由前端现有 DOMPurify allowlist 清洗后渲染。URL 模式只可能来自 `news.content`，继续使用受限 sandbox iframe。

## 9. 前端交互

1. 页面布局不变：左列新闻速览，右列新闻通讯；右列下方仍是主要指数。
2. 两个面板继续独立请求、独立 loading/error/empty/ready 状态和 10 分钟刷新。
3. 面板刷新不得关闭已经打开的阅读器，也不得替换当前正文。
4. 点击列表项时使用 `(contentSource, newsId)` 作为详情身份。
5. 焦点恢复 selector 同时包含来源和 ID，避免未来两表出现相同 ID 时恢复到错误按钮。
6. 弹窗标题、时间、来源、关闭按钮和正文区域的视觉不变。
7. 新闻通讯正文加载期间不先打开原文 URL，不显示外链 loading。
8. 新闻速览列表和阅读器标题都直接使用后端统一归一化后的 `title`；列表刷新、详情加载和重试不得重新拼接原始标题。

## 10. 性能与安全

| 路径 | 门禁 |
|---|---|
| 列表查询 | 每个面板一次有界 SQL，最多 300 条，不返回正文 |
| 详情查询 | 按来源和主键只查一张表，`LIMIT 1` |
| 正文大小 | UTF-8 最大 256 KiB，超限受控失败 |
| 外部网络 | `major_news` 路径 0 次；不探测 URL，不代理网页 |
| 跨源操作 | 0 次模糊匹配、0 次跨表回退、0 次跨表去重 |
| 前端刷新 | 沿用 10 分钟节奏，不增加轮询 |
| HTML 安全 | 继续使用现有 DOMPurify allowlist，不使用 `dangerouslySetInnerHTML` 直出未清洗正文 |

数据库已有按时间和来源的索引，当前有界窗口和主键详情查询不需要新增迁移。若后续真实查询计划不使用现有索引，必须单独审计，不在本轮凭猜测加索引。

## 11. 测试与验收

### 后端

1. 新闻速览包含 `channels='公司'`、其它频道和 `channels=NULL` 的记录。
2. 新闻速览不再生成频道分类异常。
3. 新闻通讯只来自 `MajorNewsLight`，不从 `NewsLight` 回退。
4. 两列标题去重、稳定排序、窗口和 300 条上限正确。
5. 列表项带正确 `contentSource`。
6. 详情来源为 `news` 时继续覆盖 URL/HTML/TEXT。
7. 详情来源为 `major_news` 时 HTML 正文优先，`url` 主动载荷始终为空，`originalUrl` 保留。
8. 来源非法、ID 非法、正文为空、正文过大、查询失败均受控返回。
9. 旧 `/stocks` 和旧无来源详情路由不再注册。
10. 新闻速览列表将示例 `【标题】摘要` 返回为 `标题`，详情接口返回完全相同的 `title`。
11. 缺少右书名号、空括号和非开头括号均保持既定回退语义；无标题且正文以完整非空 `【...】` 开头时，从正文候选提取标题，否则继续使用正文前 80 字 fallback。
12. 两条新闻无论括号候选来自原始标题还是空标题正文，只要最终展示标题相同，就按提取后的展示标题去重并只保留最新一条。
13. 新闻通讯标题不应用该提取规则。
14. `src='新浪财经'` 的新闻不进入通讯列表，不能成为 `observed_at`，详情直达返回既有 `NEWS_READER_NOT_FOUND`。
15. `src='同花顺'` 的 HTML/TEXT 正文移除固定推广文字且正文主体保留；其它来源的同文案不得被修改。

### 前端

1. 页面显示“新闻速览”和“新闻通讯”。
2. 请求 `/briefs` 与 `/communications`，不再请求 `/stocks`。
3. 两列点击均按来源请求详情。
4. 新闻通讯 HTML 进入现有清洗渲染路径，不进入 iframe。
5. `originalUrl` 不出现在 DOM，也不触发导航。
6. 刷新、超时、重试、取消、焦点恢复和阅读器 modal 回归通过。
7. 股票详情页新闻测试保持不变。
8. 真实 API 展示测试承接后端 `【标题】摘要 -> 标题` 合同，使用后端归一化后的 API `title` 断言新闻速览列表按钮和阅读器 `<h2>` 都只出现括号内标题，右括号后的摘要不进入标题 DOM。

## 12. 开发边界

本轮允许修改：

1. 市场总览首页新闻列表 query/service/schema/API。
2. 市场总览首页新闻前端 API、adapter、状态、面板命名和阅读器请求身份。
3. 共享新闻阅读器 DTO 中的来源与原文溯源字段。
4. 对应测试、异常码登记和本文档。

本轮禁止修改：

1. `news`、`major_news` 采集和数据库结构。
2. 股票详情页“个股新闻”。
3. 首页其它模块、布局和 Design System。
4. 新闻推荐、搜索、跨源聚合评分、原文代理、缓存或新配置。
5. 移动端阅读器。

## 13. 实施顺序

1. 先改后端 DTO 与来源枚举。
2. 修改两套列表 query 和 service，新增 `/communications`，删除 `/stocks`。
3. 改详情来源路由、两表 query 和 source-specific resolver。
4. 完成后端正反测试。
5. 一次性迁移前端 types、API、adapter、页面状态和 panel 命名。
6. 修改 reader hook，以 `(contentSource, newsId)` 请求并恢复焦点。
7. 完成前端测试、typecheck 和 build。
8. 更新当前 API 基线与异常码登记，确认旧词和旧路由只存在于明确标记的历史证据中。

标题提取增量已按最小范围落地：后端统一完成标题归一化，列表在去重前使用最终标题，详情复用同一规则，前端继续只消费 API `title`；未修改前端布局、阅读器视觉、数据库、采集链路、股票详情新闻或新闻通讯标题规则。

新闻通讯来源过滤与尾注清理增量已按后端展示策略落地：复用现有 `/communications` 和来源化详情 API，新浪财经在列表、状态观测和详情查询中统一排除，同花顺固定推广文字在 resolver 返回前清理；未新增参数、字段、配置、迁移或前端字符串处理。

后续维护若发现 `major_news.content` 在正式数据中不再是可读正文，必须停止相关变更并重新审计数据，不允许自动回退 URL 掩盖问题。

## 14. 2026-10-01 图片阅读增量 M1（方案冻结，未编码）

### 14.1 根因与正式数据证据

本增量不改变新闻来源选型。当前 `major_news.content` 已包含图片 HTML，但共享渲染器 `SanitizedHtmlContent.tsx` 的 DOMPurify allowlist 不允许 `img`，因此图片会被清洗掉；`news` 当前样本仍以纯文本为主，也没有独立图片字段。

2026-09-30 正式库只读审计（自然窗口为前一日 00:00 至审计时点）记录如下：

| 口径 | 结果 |
|---|---:|
| `major_news` 窗口行数 | 1,693 |
| 含实际 `<img>` 的 `major_news` | 1,074 |
| 当前产品精确查询口径（排除新浪、标题去重、`queryLimit=300`） | 300 篇 |
| 上述 300 篇含图片正文 | 115 篇（38.33%） |
| 上述 115 篇图片标签数 | 346；每篇 P95=8、最大=21 |
| `news` 窗口行数 / 含图片正文 | 7,168 / 0 |

Tushare `major_news` 没有独立 `image/images/pic/picture` 返回字段；图片事实位于 `content` HTML。现有 DatasetDefinition 已显式采集 `title/content/pub_time/src/url` 并保留正文，因此本增量不修改采集、DatasetDefinition、数据库结构或 API DTO。

另一个已确认问题是 HTML 分类表达式同时供 Python resolver 与 PostgreSQL 列表 SQL 使用，而 PostgreSQL 正则中的 `\b` 不是 Python 的单词边界。正式 PostgreSQL 校准证明 `<img\b` 不能命中 `<img src=x>`，导致列表 `readerMode` 可误报为 TEXT，而详情 Python resolver 又识别为 HTML。跨运行时的标签边界统一冻结为 `(?=\s|/|>)`。

### 14.2 图片安全与展示合同

1. 首期仅允许以下正式数据已验证的 CDN host，host 按小写精确匹配，不接受后缀模糊匹配：
   - `e.thsi.cn`
   - `u.thsi.cn`
   - `ftapi.10jqka.com.cn`
   - `image.cls.cn`
2. 仅输出 HTTPS 图片。协议相对 URL 统一补为 `https:`；白名单 host 的 HTTP URL 升级为 HTTPS。升级或校验失败时删除图片，不降级回 HTTP。
3. 拒绝 `data:`、`blob:`、`javascript:`、未知 host、localhost、私网/保留地址及相对路径。首期不使用 `originalUrl` 解析相对路径；新华网样本中的相对图片因此按失败关闭处理。
4. 每篇最多保留前 24 张合规图片，超过部分删除。该上限覆盖正式样本最大 21 张，并为数据波动留出小幅余量；不得把上限做成页面常量或新增配置项。
5. 源 HTML 的 `on*`、`style`、`class`、`id` 一律不保留。输入阶段只可读取 `src/data-src/data-original/alt`；源 `width/height` 也不进入最终 DOM，图片尺寸统一由响应式样式约束。最终由本系统只输出合规 `src`、清洗后的 `alt` 以及 `loading="lazy"`、`decoding="async"`、`referrerpolicy="no-referrer"`。
6. 单张图片加载失败只隐藏该图片或显示无外链的本地失败占位，不影响标题和正文继续阅读；不得保留源站内联 `onerror`。
7. 图片必须限制在正文宽度内并保持原比例，不改变现有 modal 尺寸、header、焦点、关闭和滚动合同。
8. 首期不新增后端图片代理、缓存或原文抓取。已验证的白名单 CDN 可直接加载；代理会额外引入 SSRF、带宽、缓存失效和版权边界，不属于本轮最短路径。

### 14.3 HTML 分类一致性合同

1. `NEWS_READER_HTML_PATTERN` 仍是列表 SQL 与详情 resolver 的唯一共享事实源，不允许前后端或不同 query 各自复制标签集合。
2. 所有 HTML 标签名后的 `\b` 改为 PostgreSQL 与 Python 均可解释的 `(?=\s|/|>)`；`<div>`、`<div class=x>`、`<br/>` 必须命中，`<divider>` 必须不命中。
3. 本修改不改变 `readerMode/url/html/content` DTO 结构，只纠正列表与详情的分类一致性；禁止前端根据正文再次猜测模式。
4. 自动化测试之外，实施验收必须在真实 PostgreSQL 上执行同一组正反样本，SQLite 或 Python 单元测试不能替代该证据。

### 14.4 增量边界与进入编码条件

允许的后续实现范围仅包括：共享 HTML 分类表达式及其三个现有消费者、`SanitizedHtmlContent` 的图片归一化/清洗/样式、对应后端与前端测试。禁止修改 API、DTO、采集、数据库、DatasetDefinition、阅读器 URL 模式、`originalUrl` UI 暴露、配置中心或股票详情新闻。

M1 只完成方案与 LLD 冻结。M2 已按 [market-news-reader-low-level-design-v1.md](./market-news-reader-low-level-design-v1.md) 的 N20～N23 完成本地代码、自动化测试和正式 PostgreSQL 只读校准；本地页面被现有登录门禁拦截，未使用测试账号、未绕过鉴权，因此真实文章图片加载、Network/DOM 浏览器验收和部署仍不宣称完成。
