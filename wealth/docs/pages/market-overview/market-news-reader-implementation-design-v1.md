# 市场总览｜新闻弹窗阅读器技术实施方案 v1

> 对应模块：市场总览中的“新闻速览”与“个股新闻”。
> 视觉依据：Figma `RADlZzREU4lPVviYfkLy6x`，`News Reader` 页面（node `876:2`）。
> 阶段：首轮部署反馈修正开发完成，待用户重新部署与视觉复验。
> 产物性质：阅读器实现与首页接入的技术设计及开发验收基线。
> 代码级设计：[market-news-reader-low-level-design-v1.md](./market-news-reader-low-level-design-v1.md)。

---

## 1. 文档目的

本方案将已确认的 Figma 阅读器设计转为可实施的前后端方案，完整覆盖两部分：

1. 实现一个可复用的 PC Web 弹窗阅读器，支持 URL、HTML 和纯文本三种内容。
2. 将阅读器接入市场总览的“新闻速览”和“个股新闻”，使两个列表的新闻 item 均可点击阅读。

本轮冻结的内容优先级为：

```text
URL > HTML > 纯文本 content
```

含义是：服务端先判断新闻内容是否是可用 URL，其次判断是否是 HTML，最后按纯文本处理。前端只消费服务端已经判定好的 `readerMode`，不得再次猜测内容类型。

## 2. 范围与边界

### 2.1 本期覆盖

1. 市场总览“新闻速览” item 点击打开阅读器。
2. 市场总览“个股新闻” item 点击打开同一个阅读器。
3. 阅读器支持：
   - URL 页面；
   - HTML 内容；
   - 纯文本内容；
   - loading、ready、empty、error 状态；
   - 右上角关闭按钮；
   - `Escape` 关闭和关闭后的焦点恢复。
4. 阅读器以大尺寸 PC 弹窗覆盖当前页面，不创建新闻详情路由，不改变浏览器地址。
5. 列表接口继续保持轻量；新闻正文只在用户点击后通过独立详情接口查询。

浏览器交互实现冻结为原生 `<dialog>.showModal()`：modal 进入 top layer 后，由浏览器阻断背景指针和键盘交互；代码额外负责背景滚动锁定及关闭后的触发 item 焦点恢复。不得使用普通遮罩 `div` 冒充 modal，也不得把整个 app root 手工设为 `inert` 后误伤 dialog 自身。

### 2.2 本期明确不做

1. 不实现移动端或窄屏全屏阅读器。Figma 中已有移动端稿仅保留为未来设计参考，不进入本期代码、测试和验收。
2. 不接入股票详情页中的新闻模块。
3. 不实现独立新闻详情页或前后页切换。
4. 不实现收藏、分享、字号设置、主题切换、阅读进度和站内搜索。
5. 不实现后端 URL 代理、网页抓取、正文抽取或 SSRF 访问链路。
6. 不修改 `core_serving_light.news` 表结构，不新增数据库迁移。
7. 不修改新闻采集、新闻关联、排序、十分钟刷新和来源分类逻辑。
8. 不修改市场总览其它模块。

## 3. 已冻结产品与交互口径

### 3.1 弹窗尺寸

1. 阅读器只面向 PC Web。
2. 弹窗宽度：`min(1440px, calc(100vw - 64px))`。
3. 弹窗高度：`min(900px, calc(100vh - 64px))`。
4. 视口四周至少保留 `32px` 安全距离。
5. 弹窗头部固定，正文区独立纵向滚动。
6. 禁止使用 CSS `scale` 模拟响应式；只允许真实布局收缩。

### 3.2 关闭与焦点

1. 右上角使用唯一明确的 `X` 关闭按钮，点击后关闭弹窗。
2. 支持键盘 `Escape` 关闭。
3. 不支持点击遮罩关闭，避免用户阅读过程中误关。
4. 打开后焦点进入弹窗；关闭后焦点回到原新闻 item。
5. 弹窗打开时禁止页面背景滚动和背景交互。

### 3.3 内容状态

阅读器状态固定为：

```text
closed
loading-url | loading-html | loading-text
ready-url | ready-html | ready-text
empty
error
```

1. 用户点击后立即打开弹窗，根据列表返回的 `readerMode` 展示对应 loading 骨架。
2. 详情接口成功后进入对应 ready 状态。
3. 新闻不存在或没有可读内容时进入 empty。
4. 网络、契约、内容安全或 URL 加载失败时进入 error。

## 4. 当前代码与数据审计

### 4.1 前端现状

当前实现文件：

```text
wealth/src/features/market-overview/news/api/marketNewsApi.ts
wealth/src/features/market-overview/news/api/marketNewsAdapter.ts
wealth/src/features/market-overview/news/MarketNewsPanel.tsx
wealth/src/pages/market-overview/MarketOverviewPage.tsx
```

当前事实：

1. `NewsPanelItemResponse.clickable` 被固定为 `false`。
2. `clickablePolicy` 被固定为 `disabled`。
3. adapter 丢弃来源和内容线索，只保留时间、标题与不可点击状态。
4. `MarketNewsPanel` 使用 `div aria-disabled="true"` 渲染 item。
5. 页面已经分别管理两组新闻列表状态，但没有详情请求和弹窗状态。
6. `wealth/src/shared/ui` 当前没有可复用的 modal/dialog/focus-trap 阅读器。
7. `wealth/package.json` 当前没有 HTML sanitizer 依赖。

### 4.2 后端现状

当前接口：

```text
GET /api/v1/wealth/market/news/briefs
GET /api/v1/wealth/market/news/stocks
```

当前事实：

1. 两个接口都使用 `require_quote_access`。
2. 查询层只投影列表所需的 id、时间、标题和来源，不返回正文。
3. 服务端强制输出 `url=null`、`clickable=false`。
4. 正式模型 `core_serving_light.news` 已包含 `row_key_hash/title/content/src/news_time`，但没有独立 `url` 或 `html` 列。
5. `row_key_hash` 是现有新闻 item 的稳定 `newsId`，可直接作为详情查询键。

### 4.3 正式数据只读抽样

2026-08-23 对正式 `core_serving_light.news` 最近 1,000 条非空正文做了只读、有界分类审计：

| 类型 | 行数 |
|---|---:|
| 纯 URL | 0 |
| HTML-like | 0 |
| 纯文本 | 1,000 |

正文长度最小 `10`、中位数 `145`、最大 `1,721` 字符。

结论：当前正式数据以纯文本为主；URL/HTML 是需要提前设计好的兼容能力，但不能因此把全部正文塞进首页列表接口，也不能引入全量网页抓取或代理链路。

### 4.4 CodeGraph 影响面

CodeGraph 已覆盖：

1. 市场总览页面到两个新闻列表接口的真实调用链。
2. `MarketNewsPanel`、adapter、API 类型和 `MarketOverviewPage` 消费关系。
3. FastAPI route、query service、两个列表 query、Pydantic schema 和 `NewsLight` model。
4. 共享 UI 目录及现有 modal/dialog 能力缺口。
5. 后端 API 测试、前端页面测试和真实 API smoke 测试。

本轮影响范围仅为新闻列表契约、新闻详情接口、共享阅读器和市场总览接入，不扩散到股票详情新闻或其它页面。

## 5. 总体架构

```text
首页列表加载
  -> briefs/stocks 列表接口
  -> 仅返回轻量列表字段 + readerMode
  -> 用户点击 item
  -> 页面级 reader controller 立即打开 loading 弹窗
  -> GET /api/v1/wealth/market/news/items/{newsId}
  -> 后端按 URL > HTML > TEXT 分类并返回唯一正文载荷
  -> shared NewsReaderDialog 按 readerMode 渲染
```

核心原则：

1. 列表接口负责“有什么新闻”和 loading 类型提示。
2. 详情接口负责“这条新闻具体如何阅读”。
3. 前端 feature 负责请求和状态。
4. shared reader 只负责展示，不依赖 market-news API。
5. 新闻来源事实仍只来自 `core_serving_light.news`。

## 6. 后端方案

### 6.1 新增独立详情接口

```text
GET /api/v1/wealth/market/news/items/{newsId}
```

要求：

1. 使用 `require_quote_access`，认证规则与列表接口一致。
2. `newsId` 做长度、字符集和空值校验，不允许路径穿透或无界输入。
3. 使用 `NewsLight.row_key_hash` 主键精确查询，最多返回一行。
4. 只投影详情需要的字段，不扫描新闻窗口，不复用列表排序查询。
5. 不允许按标题模糊查询或回退到另一条新闻。

### 6.2 详情响应契约

```json
{
  "newsId": "64-char-id",
  "title": "新闻标题",
  "source": "来源",
  "publishTime": "2026-08-23T18:52:50+08:00",
  "readerMode": "TEXT",
  "url": null,
  "html": null,
  "content": "新闻正文"
}
```

字段规则：

| 字段 | 类型 | 规则 |
|---|---|---|
| `newsId` | string | 与列表 item 完全一致 |
| `title` | string | `title` 非空优先，否则由正文摘要生成 |
| `source` | string/null | 沿用当前列表的 `NewsLight.src` 口径，不擅自切换为 `NewsLight.source` |
| `publishTime` | datetime | 使用源新闻时间 |
| `readerMode` | `URL/HTML/TEXT` | 服务端唯一判定 |
| `url` | string/null | 仅 `URL` 模式非空 |
| `html` | string/null | 仅 `HTML` 模式非空 |
| `content` | string/null | 仅 `TEXT` 模式非空 |

DTO 使用 `extra="forbid"`。三种载荷必须严格互斥，不允许同时返回两种正文。

### 6.3 内容分类规则

对 `content.strip()` 按固定顺序判断：

1. **URL**：完整字符串符合 `http://` 或 `https://` URL，且没有附加正文。
2. **HTML**：包含可识别的 HTML 文档或正文标签结构。
3. **TEXT**：其它非空内容全部按纯文本处理。

额外规则：

1. `javascript:`、`data:`、`file:` 等 scheme 不得进入 URL 模式。
2. 类似“链接：https://...，正文……”的混合内容不是纯 URL，按 TEXT 处理。
3. 空白正文不可进入 ready，返回受控 empty/not-found 语义。
4. 内容超过 `256 KiB` 时 fail closed，不截断成看似完整的正文。
5. URL/HTML/TEXT 解析逻辑放在独立 resolver；列表 SQL hint 与详情 resolver 必须使用同一组模式常量和同一套正反 fixture，禁止两套规则各自演化。

### 6.4 列表契约调整

两个列表接口不返回正文，仅更新以下字段：

```text
clickable: true
clickablePolicy: "reader"
readerMode: "URL" | "HTML" | "TEXT"
```

现有始终为 null 的 `url` 从列表 DTO 删除，避免列表消费者绕过详情接口直接加载。列表 query 使用 SQL `CASE` 生成轻量 `readerMode`，不把 300 条正文加载到前端。

### 6.5 建议代码落点

```text
src/biz/api/wealth/market/news_item.py
src/biz/queries/wealth/market/news/news_item_query.py
src/biz/schemas/wealth/market/news_reader.py
src/biz/services/wealth/market/news/news_reader_content_resolver.py
src/app/api/v1/router.py
```

同步修改现有列表 schema/query/service，使列表和详情共享内容类型判定规则。

## 7. 阅读器实现方案

### 7.1 组件边界

新增共享、纯展示组件：

```text
wealth/src/shared/ui/news-reader/NewsReaderDialog.tsx
wealth/src/shared/ui/news-reader/news-reader.css
wealth/src/shared/ui/news-reader/newsReaderTypes.ts
```

`NewsReaderDialog` 不得 import market-overview feature、请求函数或后端 DTO。它只接收已经适配好的 view model 与 `onClose`。

建议使用原生 `<dialog>` top layer，并由组件封装：

1. `showModal()` 与 close 生命周期。
2. `onCancel` 的 Escape 关闭。
3. 焦点进入和返回。
4. 背景滚动锁定。
5. 固定头部与独立正文滚动。

### 7.2 URL 模式

1. 使用 `iframe` 加载服务端返回的 URL。
2. 固定 `referrerPolicy="no-referrer"`。
3. 使用受限 sandbox，允许网页基本脚本执行，但禁止 top navigation、popup、download 和 same-origin 权限提升。
4. iframe 只存在于 URL ready/loading 状态，关闭后立即卸载。
5. 设置有界加载超时；超时或明确加载错误进入 error。

已知边界：外部站点可能通过 `X-Frame-Options` 或 CSP 拒绝 iframe 嵌入。浏览器对此也不总能提供可靠的跨域失败事件。本期不通过后端代理绕过站点安全策略；遇到这类 URL 时显示受控错误态。这是浏览器安全边界，不是数据回退理由。

### 7.3 HTML 模式

1. 新增显式前端依赖 `dompurify`。
2. HTML 必须在进入 DOM 前按固定 allowlist 清洗，禁止直接渲染源 HTML。
3. 必须移除：
   - `script/style/form/iframe/object/embed/video/audio`；
   - `on*` 事件属性；
   - 危险 URL scheme；
   - 可改变页面外层导航或提交数据的能力。
4. 本期 HTML 内链接不提供交互跳转，保留可读文本和基础排版。
5. 禁止自行编写正则 sanitizer。

### 7.4 纯文本模式

1. 使用 React 文本节点渲染，禁止 `dangerouslySetInnerHTML`。
2. 保留换行和段落空白。
3. 长文本只在正文区滚动，不撑高弹窗和页面。

### 7.5 状态与视觉

1. 所有颜色、边框、圆角、阴影、字号和间距只使用现有 Design Token。
2. loading 使用 Figma 对应 URL/HTML/TEXT 骨架，不闪现上一条正文。
3. empty/error 使用同一弹窗结构，头部和关闭按钮保持稳定。
4. 切换 item 时不得让弹窗尺寸抖动。
5. 本期没有移动端 media query 和移动端组件分支。

## 8. 首页接入方案

### 8.1 Feature 内请求与控制器

新增：

```text
wealth/src/features/market-overview/news/api/marketNewsReaderApi.ts
wealth/src/features/market-overview/news/api/marketNewsReaderAdapter.ts
wealth/src/features/market-overview/news/model/useMarketNewsReader.ts
```

职责：

1. `marketNewsReaderApi` 只负责详情 HTTP 请求和错误合同。
2. adapter 将后端 DTO 转为 shared reader view model。
3. `useMarketNewsReader` 管理 selected id、状态、AbortController、触发 item 和焦点恢复目标。
4. shared reader 不拥有 API 请求。

### 8.2 两类新闻统一接入

`MarketOverviewPage` 只挂载一个阅读器实例：

```text
新闻速览 item ─┐
               ├─ onItemOpen(item) -> one reader controller -> one dialog
个股新闻 item ─┘
```

规则：

1. 两个 panel 都传入同一个 `onItemOpen`。
2. item 改为语义化 `button type="button"`，支持鼠标、Enter 和 Space。
3. item 使用 `aria-haspopup="dialog"`。
4. 滚动列表中的复制 item 使用相同 `newsId`，打开同一条详情。
5. 点击不改变当前 URL，不触发首页路由跳转。
6. 打开另一条新闻前取消上一条详情请求。
7. 关闭阅读器时取消未完成请求并清空正文状态。
8. 列表每十分钟自动刷新时，不关闭已经打开的阅读器，也不替换其正文。

### 8.3 失败隔离

1. 详情请求失败只影响弹窗，不清空新闻列表和其它首页模块。
2. 列表请求失败时不影响已经打开并完成加载的阅读器。
3. 详情 404 显示 empty/not-found 状态，不尝试用同标题其它新闻替代。
4. 不缓存失败响应；用户重新点击时允许重新请求。

## 9. 安全、性能与可观测性

### 9.1 安全门禁

1. 详情接口必须鉴权。
2. 禁止后端请求用户提供或新闻正文包含的任意 URL。
3. URL 只允许 `http/https`。
4. HTML 必须经 DOMPurify 严格清洗。
5. 纯文本不得进入 HTML 渲染路径。
6. 错误响应不得泄露 SQL、表名、文件路径或堆栈。
7. iframe 不得获得 top navigation、popup、download 或 same-origin 权限。

### 9.2 性能门禁

| 项目 | 口径 |
|---|---|
| 列表接口 | 不返回正文；保留现有有界候选量 |
| 详情查询 | 每次点击最多一次主键查询 |
| 详情正文 | 最大 `256 KiB` |
| 详情 API | 本地/测试目标 P95 `< 200ms`，硬门禁 `< 300ms` |
| 前端请求 | 只在点击时发起，不预取全部新闻详情 |
| 并发 | 同一页面同一时刻最多一个有效详情请求 |
| 内存 | 关闭或切换 item 后释放旧正文和 iframe |
| 列表刷新 | 不重复获取已打开正文，不中断阅读器 |

### 9.3 异常码

实现前在统一注册表启用：

| code | 语义 | 用户行为 |
|---|---|---|
| `NEWS_READER_NOT_FOUND` | 指定新闻不存在或已不可读 | 阅读器 empty |
| `NEWS_READER_REQUEST_INVALID` | 新闻标识长度或字符合同非法 | 阅读器 error，不发起数据库回退查询 |
| `NEWS_READER_CONTENT_INVALID` | 正文类型或安全合同非法 | 阅读器 error |
| `NEWS_READER_CONTENT_TOO_LARGE` | 正文超过上限 | 阅读器 error |
| `NEWS_READER_QUERY_FAILED` | 详情查询或未分类服务失败 | 阅读器 error，可重试 |

URL 被外站拒绝嵌入属于前端 reader error state，不伪装成后端查询异常码。

## 10. 测试方案

### 10.1 后端

1. URL/HTML/TEXT 优先级与互斥载荷。
2. `javascript/data/file` 不进入 URL。
3. 混合 URL 正文按 TEXT。
4. 空正文、超大正文、非法 id、新闻不存在和查询失败。
5. 详情 API 使用真实 SQLAlchemy session、真实 route 和真实 `NewsLight` model。
6. 详情查询只有一次主键访问，无窗口扫描。
7. 列表新增 `readerMode/clickablePolicy`，但不返回正文和 URL。
8. 两个列表原有分类、排序、状态和刷新合同不回退。

### 10.2 前端

1. shared reader 的 URL/HTML/TEXT loading 与 ready。
2. empty/error 状态。
3. URL iframe sandbox、referrer policy 和卸载。
4. HTML sanitizer 删除脚本、事件属性和危险 URL。
5. TEXT 中的 HTML 字符串只显示为文字。
6. 关闭按钮、Escape、焦点进入/返回、背景滚动锁定。
7. 新闻速览和个股新闻都能打开同一个 reader。
8. item 使用 button 语义，重复滚动 item 映射同一 `newsId`。
9. 打开/关闭不改变路由。
10. 连续点击会取消旧请求；关闭会取消未完成请求。
11. 十分钟列表刷新不会关闭 reader。
12. 详情失败只影响弹窗。
13. PC `1920×1080`、`1440×900`、`1280×720` 布局无裁切。
14. 本期不新增移动端测试。

### 10.3 静态门禁

1. shared reader 不得 import market-overview feature 或 API。
2. 列表响应不得出现 `content/html/url` 正文载荷。
3. feature adapter 不得自行判断 URL/HTML/TEXT。
4. 禁止原始 HTML 直接进入 `dangerouslySetInnerHTML`。
5. 禁止新增后端 URL fetch/proxy。
6. 禁止修改股票详情新闻消费者。
7. 禁止新增移动端实现分支。

## 11. 实施里程碑

### M1：契约与后端详情

1. 冻结详情 DTO、列表增量字段和异常码。
2. 实现共享内容 resolver、主键 query、详情 service/API。
3. 更新列表 hint 与 clickable 契约。
4. 完成后端测试和性能门禁。

### M2：共享阅读器

1. 增加 DOMPurify 依赖。
2. 实现 PC dialog、三类内容、五类状态和无障碍行为。
3. 完成 shared component 测试。

### M3：首页接入

1. 实现 reader API/adapter/controller。
2. 两个新闻 panel 接入语义化点击。
3. 页面挂载单一 reader。
4. 完成请求取消、失败隔离和刷新回归。

### M4：收口

1. 运行后端与 Wealth 目标测试、typecheck、build、静态门禁。
2. 按 Figma 做 PC 页面人工视觉验收。
3. 回填技术方案和后续 LLD 状态。

## 12. 风险与处理

| 风险 | 处理 |
|---|---|
| 外站拒绝 iframe | 显示受控 error；本期不做代理绕过 |
| 源 HTML 含脚本或危险链接 | DOMPurify 严格 allowlist，失败不渲染 |
| 列表载荷膨胀 | 正文只走点击后的独立详情接口 |
| 快速点击响应串线 | AbortController + 请求身份校验 |
| 列表刷新打断阅读 | reader 状态独立于列表 refresh state |
| 弹窗遮罩下页面仍可操作 | native dialog top layer + 背景滚动锁定 |
| 新旧文档 clickable 口径冲突 | 本文覆盖旧文档中的“不可点击”条款，旧文档保留为历史基线 |

## 13. 开发收口

2026-08-23 已按本文和代码级 LLD 完成开发：

1. 新增独立新闻详情 API，正文按 `URL > HTML > TEXT` 返回唯一载荷。
2. 两个首页列表改为轻量 `readerMode` 提示和可点击 button，不返回正文、HTML 或 URL。
3. 页面只挂载一个原生 `<dialog>` 阅读器；X/Escape、滚动锁、请求取消、焦点恢复和列表刷新隔离均已实现。
4. URL 使用受限 sandbox iframe；HTML 仅由 DOMPurify 固定 allowlist 清洗后渲染；纯文本使用 React 文本节点。
5. 后端目标测试、Wealth 目标测试、Wealth 全量测试、typecheck、build 和静态门禁均已通过。

开发自动化不能替代浏览器 top-layer、真实背景 inert、外站 iframe 策略和 PC 三个目标视口的视觉验收；这些仍由用户部署后确认。

## 14. 首轮部署反馈修正

2026-08-23 首轮部署确认阅读器主链可用，同时暴露出头部信息呈现问题。本轮修正冻结如下：

1. 标题继续使用详情接口返回的 `title`。该字段直接来自 `NewsLight.title`；仅当源标题为空时，后端才使用正文摘要兜底。本轮不改数据事实和标题生成规则。
2. 标题区必须展示完整标题，允许按容器宽度自然折行；禁止单行 `ellipsis` 截断。头部高度随标题行数自适应，正文区继续占用剩余高度。
3. 元信息固定按“发布时间、来源”顺序展示，格式为：`2026年8月23日 19:19:52 来源：sina`。来源为空时只展示发布时间，不出现空标签或分隔点。
4. 关闭按钮不再使用字体字符 `×`。采用通过 Supericons 检索并确认的 Material Symbols `material:close` 图标，保持现有按钮点击区域、焦点语义、`aria-label` 和关闭行为不变。
5. 图标以当前色继承的内联 SVG 固化在共享组件中，不新增图标运行时依赖，不引入第二套按钮组件。
6. 正文内容、URL/HTML/TEXT 渲染、弹窗尺寸、焦点管理、背景锁定和请求状态机均保持不变。

修正已完成：目标阅读器测试 `21 passed`，Wealth 全量回归 `52` 个测试文件、`334 passed`，typecheck 和 build 均通过。真实标题折行高度、时间与来源的视觉间距及关闭图标观感仍由用户重新部署后验收。

外站是否允许 iframe 由来源站点控制。本期接受“可加载则阅读、被站点拒绝则受控报错”的浏览器安全边界；若未来要求所有 URL 都必须站内展示，需要另立网页代理与 SSRF 安全专项，不得在本方案中顺手加入。
