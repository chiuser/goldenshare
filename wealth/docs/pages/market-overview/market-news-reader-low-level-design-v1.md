# 市场总览｜新闻速览、新闻通讯与阅读器低层设计 v2（LLD）

> 稳定文档路径沿用 `market-news-reader-low-level-design-v1.md`，正文版本升级为 v2。
> 状态：已实现并结案（2026-09-01 用户确认）；N01～N19 均已完成。
> 日期：2026-08-24；标题提取及新闻通讯展示策略确认日期：2026-08-27；结案日期：2026-09-01。
> 技术方案：[market-news-implementation-design-v1.md](./market-news-implementation-design-v1.md)。
> 视觉与 modal 合同：[market-news-reader-implementation-design-v1.md](./market-news-reader-implementation-design-v1.md)。

## 1. 开发前结论（历史基线）

开发开始前，代码已经完成新闻弹窗阅读器，但列表和详情仍绑定旧的 `news + channels` 分流。本 LLD 随后一次性完成了以下合同迁移：

```text
新闻速览: NewsLight 全频道
个股新闻: 删除
新闻通讯: MajorNewsLight
详情身份: newsId -> (contentSource, newsId)
major_news 正文: HTML/TEXT，URL 仅 originalUrl
```

不允许只换 UI 标题、不换详情查询；不允许只换列表表名、保留无来源详情路由；不允许保留 `/stocks` 或旧字段做兼容。

## 2. 编码硬口径矩阵

| ID | 硬口径 | 代码落点 | 正向测试 | 负向测试 |
|---|---|---|---|---|
| N01 | 新闻速览覆盖 `news` 全频道 | `market_news_query.py` | 公司/非公司/NULL 均返回 | SQL 不出现 `channels` predicate |
| N02 | 新闻通讯只查 `major_news` | `major_news_query.py` | 返回 MajorNews fixture | News fixture 不能进入通讯 |
| N03 | 两列不做跨源去重 | 两个独立 query | 同标题可分别出现 | 禁止 join/union 两表做相似度 |
| N04 | 详情来源由列表显式下发 | list DTO/TS types | item 有 `contentSource` | 缺来源合同失败 |
| N05 | 详情只查指定表 | reader query/service | 两种来源各命中 | 指定表缺失不回退另一表 |
| N06 | major 正文不用 URL | source-specific resolver | HTML 返回 HTML | 非空 `major_news.url` 不得返回 URL mode |
| N07 | major URL 仅溯源 | reader DTO | `originalUrl` 保留 | UI 不渲染链接、不导航 |
| N08 | news 解析规则不回退 | existing resolver | URL/HTML/TEXT fixture | 脚本 scheme、超大正文拒绝 |
| N09 | 旧 stock 合同清零 | API/schema/frontend | `/communications` 正常 | `/stocks`、`stockNews` 不再注册/引用 |
| N10 | 面板独立状态 | page/service | 一列失败另一列保留 | 禁止整组清空 |
| N11 | 阅读器 modal 行为不变 | shared dialog/hook | focus、Escape、close restore | 背景不能点击，刷新不能关窗 |
| N12 | 性能有界 | query/detail | list limit 300、detail limit 1 | 禁止正文进入列表、跨表扫描 |
| N13 | 股票详情不受影响 | stock-detail files/tests | 原测试通过 | 本轮不得改 stock-detail news |
| N14 | 无兼容层 | router/types/files | 新合同唯一 | 无 alias route/re-export/旧 DTO |
| N15 | 畸形 iframe 不吞正文 | `SanitizedHtmlContent` | 自闭合 iframe 后段落保留 | iframe/属性仍不得进入 DOM |
| N16 | 新闻速览开头 `【...】` 标题在列表和详情统一提取 | `news_display_title.py`、list query、reader service | 非空 `title` 与空 `title` 正文开头示例两端一致 | 尾部摘要不得进入任一标题 |
| N17 | 标题提取严格回退且不扩散 | title normalizer、major query/reader | 畸形括号回退原逻辑 | `title` 非空时不得检查正文；不得扫描正文中部；不修改 major/stock-detail |
| N18 | 新闻通讯排除新浪财经 | major list/observed/detail query | 其它来源正常返回 | 新浪记录不进列表、不推进观测时间、详情 404 |
| N19 | 同花顺固定推广文字仅在展示层移除 | major display policy/resolver | HTML/TEXT 主体保留 | 不回写 DB、不修改其它来源、不按文章尾部截断 |

## 3. 影响面审计

### 3.1 后端调用链

```text
src/app/api/v1/router.py
  -> src/biz/api/wealth/market/news_briefs.py
  -> src/biz/api/wealth/market/stock_news.py
  -> src/biz/api/wealth/market/news_item.py
  -> MarketNewsQueryService / NewsReaderQueryService
  -> MarketNewsQuery / StockNewsQuery / NewsReaderQuery
  -> NewsLight
```

目标调用链：

```text
router.py
  -> news_briefs.py -> MarketNewsQuery -> NewsLight
  -> news_communications.py -> MajorNewsQuery -> MajorNewsLight
  -> news_item.py -> source dispatch
       news -> NewsReaderQuery -> NewsLight
       major_news -> MajorNewsReaderQuery -> MajorNewsLight
```

### 3.2 前端调用链

```text
MarketOverviewPage
  -> marketNewsApi
  -> marketNewsAdapter
  -> MarketNewsPanelGroup / MarketNewsPanel
  -> useMarketNewsReader
  -> marketNewsReaderApi / Adapter
  -> shared NewsReaderDialog
```

共享 `NewsReaderDialog` 不需要感知数据库来源，只消费已经解析好的 `readerMode` 和互斥正文载荷。

### 3.3 明确不在影响面

1. `src/biz/queries/wealth/market/stock_detail/news_query.py`。
2. `wealth/src/features/stock-detail/news/**`。
3. 新闻采集 DatasetDefinition、raw/core model 和迁移。
4. 首页非新闻模块。

## 4. 后端文件级方案

### 4.0 `news_display_title.py`

新增市场总览新闻专属标题归一化模块：

```text
src/biz/queries/wealth/market/news/news_display_title.py
```

它只承载 `contentSource=news` 的展示标题语义，并提供同一份规则的两种入口：

```python
extract_leading_bracket_title(title: str | None) -> str | None
build_news_display_title(title: str | None, content: str | None, fallback_title: str) -> str
build_news_display_title_expr(title_column, content_column)
```

确定性算法：

```text
normalized_title = trim(title)
normalized_content = trim(content)
candidate = normalized_title 非空 ? normalized_title : normalized_content

if candidate 以“【”开头:
    close = 第一个“】”的位置
    if close 存在且 trim(candidate[1:close]) 非空:
        return trim(candidate[1:close])

return normalized_title 非空 ? normalized_title : 既有 content 前 80 字 fallback
```

约束：

1. `title` trim 后非空时只检查 `title`；`title` 为空时才检查 trim 后原始 `content`，并且只识别候选开头第一组全角 `【...】`，不识别半角 `[]`，也不扫描正文或标题中部的括号。
2. 缺右括号、`【】`、`【   】` 均回到原逻辑，不返回空标题。
3. 原始 `NewsLight.title` 不更新、不覆盖；归一化只发生在查询响应层。
4. `build_news_display_title_expr()` 供列表 SQL 的最终展示标题与 `partition_by` 共同使用；Python 入口供详情 service 使用。两种入口必须共享括号常量和 case table，并用参数化测试证明非空标题、空标题正文开头、畸形和不命中分支完全一致；未命中时既有无标题正文前 80 字 fallback 保持不变。
5. 不把规则放进前端 adapter、Panel 或 shared reader；否则列表、loading header、详情 ready header 和重试路径会出现漂移。
6. 不修改 `MajorNewsQuery`、`MajorNewsReaderQuery` 和股票详情新闻 query。
7. SQLAlchemy 表达式通过方言编译保持现有运行环境一致：PostgreSQL 使用 `strpos`，SQLite 合同测试使用 `instr`；两者都只生成当前查询中的字符串表达式，不创建数据库函数或兼容表。

### 4.1 `market_news_query.py`

保留 `MarketNewsQuery`，修改如下：

1. 删除 `or_` import 和两处 `channels` predicate。
2. `NewsQueryRow` 增加：

```python
content_source: Literal["news", "major_news"]
```

3. `MarketNewsQuery` 固定写入 `content_source="news"`。
4. 保留：时间窗、非空 content、展示标题 fallback、标题去重、稳定排序、limit、reader mode SQL hint。
5. `load_observed_at()` 只按非空 content 取 `max(news_time)`。

目标 SQL 语义：

```sql
WITH deduped AS (
  SELECT
    row_key_hash,
    news_time,
    NEWS_DISPLAY_TITLE(title, content) AS display_title,
    src,
    reader_mode,
    ROW_NUMBER() OVER (
      PARTITION BY display_title
      ORDER BY news_time DESC, row_key_hash ASC
    ) AS content_rank
  FROM core_serving_light.news
  WHERE news_time BETWEEN :start AND :end
    AND LENGTH(TRIM(content)) > 0
)
SELECT ...
FROM deduped
WHERE content_rank = 1
ORDER BY news_time DESC, row_key_hash ASC
LIMIT :query_limit;
```

`NEWS_DISPLAY_TITLE(title, content)` 是本文对 SQLAlchemy 表达式 `build_news_display_title_expr()` 的语义占位，不是新增数据库函数。表达式继续只使用当前行的 `title/content`，不新增 join、子查询、配置或数据库 migration。

标题提取必须先于 `ROW_NUMBER() PARTITION BY display_title`。因此两条原始标题分别为 `【同一标题】摘要 A`、`【同一标题】摘要 B` 时，最终只返回时间最新的一条；不得先按原始标题去重、再在 Python 或前端改成两个相同标题。

SQL 和测试中都不得再出现 `channels='公司'` 或排除公司频道的表达式。

### 4.2 删除 `stock_news_query.py`

删除：

```text
src/biz/queries/wealth/market/news/stock_news_query.py
```

新增：

```text
src/biz/queries/wealth/market/news/major_news_query.py
```

定义 `MajorNewsQuery`，复用 `NewsQueryResult/NewsQueryRow` 数据结构，但不复用 `NewsLight` 专属 SQL helper。

目标规则：

```python
display_title = func.trim(MajorNewsLight.title)
has_title = func.length(display_title) > 0
has_content = func.length(func.trim(MajorNewsLight.content)) > 0
reader_mode = case(
    (func.trim(MajorNewsLight.content).regexp_match(NEWS_READER_HTML_PATTERN), literal("HTML")),
    else_=literal("TEXT"),
)
```

窗口字段使用 `pub_time`，列表来源显示字段使用 `src`。不得使用技术来源字段 `source` 作为用户可见来源。

去重和排序：

```text
partition_by = trim(title)
order_by = pub_time DESC, row_key_hash ASC
final limit = strategy.query_limit
content_source = "major_news"
```

`MajorNewsQuery` 不选取 `content` 或 `url`，避免列表响应携带正文。

新增统一展示策略模块：

```text
src/biz/services/wealth/market/news/major_news_display_policy.py
```

冻结常量与纯函数：

```python
MAJOR_NEWS_EXCLUDED_SOURCE = "新浪财经"
THS_MAJOR_NEWS_SOURCE = "同花顺"
THS_PROMOTION_TEXT = "关注同花顺财经（ths518），获取更多机会"

strip_major_news_promotional_text(
    *, source: str, content: str | None
) -> str | None
```

`MajorNewsQuery.load_rows()` 的候选条件和 `load_observed_at()` 必须共同增加：

```python
func.trim(MajorNewsLight.src) != MAJOR_NEWS_EXCLUDED_SOURCE
```

不得只过滤最终 300 条结果，否则新浪记录会抢占候选名额；不得遗漏 `load_observed_at()`，否则通讯状态会被不可展示来源错误推进。

### 4.3 schema 迁移

修改：

```text
src/biz/schemas/wealth/market/news_briefs.py
```

新增公共类型文件：

```text
src/biz/schemas/wealth/market/news_common.py
```

由该文件唯一声明：

```python
NewsCategoryValue = Literal["brief", "communication"]
NewsPanelKeyValue = Literal["newsBriefs", "newsCommunications"]
NewsContentSourceValue = Literal["news", "major_news"]
```

`news_briefs.py`、`news_communications.py`、`news_reader.py` 和 query row 全部从 `news_common.py` 导入，不得在多个文件复制 Literal。

`NewsPanelItemDto` 目标字段：

```python
class NewsPanelItemDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    newsId: str
    contentSource: NewsContentSourceValue
    publishTime: datetime
    displayTime: str
    title: str
    category: NewsCategoryValue
    source: str | None = None
    readerMode: Literal["URL", "HTML", "TEXT"]
    clickable: Literal[True] = True
```

删除 `NewsSubjectRefDto`、`subject` 和 `priority`。`NewsListPanelDto.sortRule` 改为：

```python
sortRule: Literal["publishTime_desc"] = "publishTime_desc"
```

删除：

```text
src/biz/schemas/wealth/market/stock_news.py
```

新增：

```text
src/biz/schemas/wealth/market/news_communications.py
```

```python
class NewsCommunicationsResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    newsWindow: NewsWindowDto
    pageStatus: PageStatusDto
    newsCommunications: NewsListPanelDto
    debugInfo: MarketNewsDebugInfoDto | None = None
```

### 4.4 `news_query_service.py`

类型改为：

```python
PanelKey = Literal["newsBriefs", "newsCommunications"]
Category = Literal["brief", "communication"]
```

对象成员：

```python
self._market_news_query = MarketNewsQuery()
self._major_news_query = MajorNewsQuery()
```

方法：

```python
build_news_briefs(...)
build_news_communications(...)
```

`build_news_communications()` 固定：

```python
_PanelRequest(
    panel_key="newsCommunications",
    module_key="newsCommunications",
    category="communication",
)
```

DTO 组装必须把 `row.content_source` 写入 `contentSource`。删除 `subject=None` 和 `priority=0`。

`_load_query_result()` 只做明确二选一，不允许 default 分支把未知 key 静默路由到 major：

```python
if panel_key == "newsBriefs": ...
if panel_key == "newsCommunications": ...
raise AssertionError(...)
```

### 4.5 API 文件和 router

保留：

```text
src/biz/api/wealth/market/news_briefs.py
```

删除：

```text
src/biz/api/wealth/market/stock_news.py
```

新增：

```text
src/biz/api/wealth/market/news_communications.py
```

路由：

```python
@router.get("/communications", response_model=NewsCommunicationsResponseDto)
```

`src/app/api/v1/router.py` 同步删除 `stock_news` import/include，新增 `news_communications`。不保留旧路由。

## 5. 详情查询和内容解析

### 5.1 来源枚举

来源类型只允许定义在：

```text
src/biz/schemas/wealth/market/news_common.py
```

列表和详情必须导入同一个类型定义，禁止复制字符串 union。

### 5.2 `news_reader_query.py`

保留 `NewsReaderQuery`，返回结构增加：

```python
content_source="news"
original_url=None
```

继续只查 `NewsLight` 主键，字段为 `row_key_hash/news_time/title/src/content`。

### 5.3 新增 `major_news_reader_query.py`

新增：

```text
src/biz/queries/wealth/market/news/major_news_reader_query.py
```

按主键查询：

```python
select(
    MajorNewsLight.row_key_hash,
    MajorNewsLight.pub_time,
    MajorNewsLight.title,
    MajorNewsLight.src,
    MajorNewsLight.content,
    MajorNewsLight.url,
).where(
    MajorNewsLight.row_key_hash == news_id,
    func.trim(MajorNewsLight.src) != MAJOR_NEWS_EXCLUDED_SOURCE,
).limit(1)
```

不 join `NewsLight`，不按标题 fallback。新浪财经详情按现有未找到语义返回 404，不新增异常码，也不在 service 读取后再丢弃整行。

### 5.4 source-specific resolver

现有 `resolve_news_reader_content()` 保持 `news` 的 URL > HTML > TEXT 语义。

在同一 resolver 模块新增：

```python
def resolve_major_news_reader_content(
    content: str | None,
    *,
    source: str,
) -> ResolvedNewsReaderContent:
    text = validate_nonempty_and_size(content)
    text = strip_major_news_promotional_text(source=source, content=text)
    text = validate_nonempty(text)
    if re.search(NEWS_READER_HTML_PATTERN, text):
        return ResolvedNewsReaderContent(mode="HTML", url=None, html=text, content=None)
    return ResolvedNewsReaderContent(mode="TEXT", url=None, html=None, content=text)
```

原始正文必须先执行共享的非空和 256 KiB 校验，避免尾注清理绕过载荷上限；清理后只需重新确认非空。推广文字按有句号、无句号两个固定 literal 顺序替换，不使用模糊正则、不按字符串末尾切片，也不删除后续 HTML。`resolve_major_news_reader_content()` 不调用 URL classifier。

### 5.5 `news_reader_query_service.py`

签名改为：

```python
build_news_reader_item(
    session: Session,
    *,
    content_source: NewsContentSourceValue,
    news_id: str,
) -> NewsReaderItemDto
```

明确 dispatch：

```python
if content_source == "news":
    row = self._news_query.load_by_id(...)
    resolved = resolve_news_reader_content(row.content)
elif content_source == "major_news":
    row = self._major_news_query.load_by_id(...)
    resolved = resolve_major_news_reader_content(row.content, source=row.source)
else:
    raise AssertionError(...)
```

`major_news` DTO：

```python
NewsReaderItemDto(
    newsId=row.news_id,
    contentSource="major_news",
    title=trimmed_title,
    source=row.source,
    publishTime=row.publish_time,
    readerMode=resolved.mode,
    url=None,
    html=resolved.html,
    content=resolved.content,
    originalUrl=(row.original_url or "").strip() or None,
)
```

`news` DTO 的 `originalUrl=None`。

标题规则：

1. `news` 先调用 `build_news_display_title()`：`title` 非空时检查 `title`，`title` 为空时检查 trim 后原始 `content`；完整命中候选开头第一组 `【...】` 时只返回括号内非空文本，且结果必须与列表 `title` 完全一致。
2. `news` 未命中标题提取时继续允许由正文构造最多 80 字 fallback title；正文中部的括号不得被提取。
3. `major_news` 列表已要求标题非空；详情若标题为空则受控 `NOT_FOUND`，不从 HTML 正文拼标题，也不应用 `【...】` 提取。

### 5.6 `NewsReaderItemDto`

新增：

```python
contentSource: NewsContentSourceValue
originalUrl: str | None = None
```

现有 `url/html/content` 三者互斥 validator 保持。新增来源约束 validator：

```text
contentSource=news:
  originalUrl 必须为 null

contentSource=major_news:
  readerMode 只能为 HTML/TEXT
  url 必须为 null
```

### 5.7 详情 API

`news_item.py` 路由改为：

```python
@router.get("/items/{content_source}/{news_id}")
```

`content_source` 和 `news_id` 都以 `str` 接收并在 route 内显式校验，以保证非法来源统一返回 `NEWS_READER_REQUEST_INVALID`，而不是落入 FastAPI 默认 422。来源只允许 `news/major_news`，`news_id` 继续使用 `[A-Za-z0-9_-]{1,64}`。

日志必须同时带 `content_source` 和 `news_id`。不得记录正文或 URL。

## 6. 前端文件级方案

### 6.1 `marketNewsApi.ts`

目标类型：

```ts
export type NewsContentSource = "news" | "major_news";

export interface NewsPanelItemResponse {
  newsId: string;
  contentSource: NewsContentSource;
  publishTime: string;
  displayTime: string;
  title: string;
  category: "brief" | "communication";
  source?: string | null;
  readerMode: NewsReaderMode;
  clickable: true;
}
```

删除 `subject`、`priority` 和旧 category。接口改为：

```ts
fetchMarketNewsBriefs(...)
fetchNewsCommunications(...)
```

`buildNewsUrl` 的 path union 改为 `"/briefs" | "/communications"`。

### 6.2 `marketNewsAdapter.ts`

`MarketNewsViewItem` 增加 `contentSource`。面板标题 union 改为：

```ts
"新闻速览" | "新闻通讯"
```

删除 `buildStockNewsViewModelFromApi`，新增：

```ts
buildNewsCommunicationsViewModelFromApi(payload)
```

### 6.3 页面状态全量迁移

`MarketOverviewPage.tsx` 必须在一次修改中完成以下 rename：

```text
stockNews -> newsCommunications
stockNewsViewState -> newsCommunicationsViewState
stockNewsErrorMessage -> newsCommunicationsErrorMessage
stockNewsDebugInfo -> newsCommunicationsDebugInfo
fetchStockNews -> fetchNewsCommunications
buildStockNewsViewModelFromApi -> buildNewsCommunicationsViewModelFromApi
个股新闻 -> 新闻通讯
/news/stocks -> /news/communications
```

不得留下局部旧变量名承载新语义。

### 6.4 Panel 组件

`MarketNewsPanel.tsx` 标题 union 改为“新闻速览/新闻通讯”。

`MarketNewsPanelGroup.tsx` prop 改为：

```ts
newsCommunications: ReactNode;
```

布局和 CSS class 不变，不因改名调整模块尺寸。

### 6.5 Reader API 和 hook

`marketNewsReaderApi.ts`：

```ts
fetchMarketNewsReaderItem(
  contentSource: NewsContentSource,
  newsId: string,
  options?: { signal?: AbortSignal },
)
```

请求：

```ts
`/api/v1/wealth/market/news/items/${encodeURIComponent(contentSource)}/${encodeURIComponent(newsId)}`
```

response 增加 `contentSource` 和 `originalUrl`。

`marketNewsReaderAdapter.ts` 必须校验：

1. active payload 互斥。
2. `major_news` 不能是 URL mode。
3. `major_news` 的 active `url` 必须为 null。
4. `news` 的 `originalUrl` 必须为 null。

`originalUrl` 只保留在后端 API response contract。前端 adapter 必须校验该字段的来源约束，但不得把它复制到共享 `NewsReaderViewModel`；`NewsReaderDialog` 和 `newsReaderTypes.ts` 不增加 `originalUrl`，从类型边界上保证本轮 UI 不可能渲染、跳转或把它写入 DOM。

`useMarketNewsReader.ts`：

1. 在市场总览新闻 feature 内定义统一请求身份 `MarketNewsReaderIdentity = { contentSource, newsId }`；该类型不得下沉到 shared reader。
2. `selectedItemRef` 继续保存重试所需的完整列表项，同时新增或派生 feature-local identity；共享 `NewsReaderDialogState` 的 loading/empty/error 结构保持不变，不增加数据库来源字段。
3. 每次详情请求、响应校验、过期响应隔离和重试都使用同一份 feature-local identity，响应必须同时核对来源和 ID。
4. 焦点恢复同时使用 `data-news-source` 和 `data-news-id`，禁止只按 ID 查找替代触发项。

`MarketNewsPanel.tsx` 的 button 增加：

```tsx
data-news-source={item.contentSource}
```

标题提取增量不修改上述前端合同。`marketNewsAdapter.ts`、`useMarketNewsReader.ts` 和 `NewsReaderDialog.tsx` 继续原样传递、展示后端 `title`，禁止新增正则、字符串切片或第二个 fallback。

### 6.6 畸形自闭合 iframe 容错

正式 `major_news.content` 已确认存在如下源端 HTML：

```html
<p><iframe src="..."/></p><p>正常正文</p>
```

`iframe` 不是 HTML void element，浏览器不会把 `/>` 视为真正闭合；若直接交给 DOM parser，后续正文会被吸收为 iframe 子内容，再随禁止标签一起被 DOMPurify 删除。

`SanitizedHtmlContent.tsx` 必须在 DOMPurify 之前执行唯一一项有界预处理：删除 `<iframe .../>` 自闭合起始标签。实现要求：

1. 匹配大小写不敏感，并允许单引号/双引号属性值。
2. 只处理明确以 `/>` 结束的 iframe，不改写普通段落、链接或规范闭合标签。
3. 预处理后仍必须经过原有 DOMPurify allowlist；不得把 iframe 或任何属性加入 allowlist。
4. 不请求 iframe 的 `src`，不生成替代链接，不修改 URL/TEXT 阅读模式。
5. 回归测试必须证明 iframe 后的正文保留，同时 DOM 中不存在 iframe 和 `src` 属性。

## 7. 旧代码删除清单

开发完成后以下内容必须为 0：

```text
src/biz/api/wealth/market/stock_news.py
src/biz/schemas/wealth/market/stock_news.py
src/biz/queries/wealth/market/news/stock_news_query.py
GET /api/v1/wealth/market/news/stocks
stockNews（市场总览新闻 feature 内）
build_stock_news
fetchStockNews
buildStockNewsViewModelFromApi
MarketNewsPanel 标题“个股新闻”
NewsLight.channels == "公司"（市场总览新闻 query 内）
旧 /items/{news_id} 路由
```

股票详情 feature 中的 `stockNews` 或“个股新闻”不属于上述清零范围。

## 8. 异常码

继续使用：

```text
NEWS_CONFIG_MISSING
NEWS_CONFIG_INVALID
NEWS_SOURCE_EMPTY
NEWS_SOURCE_DELAYED
NEWS_QUERY_FAILED
NEWS_READER_NOT_FOUND
NEWS_READER_REQUEST_INVALID
NEWS_READER_CONTENT_INVALID
NEWS_READER_CONTENT_TOO_LARGE
NEWS_READER_QUERY_FAILED
```

退役：

```text
NEWS_CHANNEL_RULE_INVALID
```

不新增 `MAJOR_NEWS_*` 异常码。来源差异是查询实现细节，统一归入现有新闻列表和阅读器异常合同。

## 9. 测试方案

### 9.1 后端列表测试

修改 `tests/web/test_wealth_market_news_api.py`：

1. 同时创建 `NewsLight`、`MajorNewsLight` 表。
2. 新闻速览 fixture 包含公司、非公司、NULL channels，全部应返回。
3. 新闻通讯 fixture 只写 `MajorNewsLight`。
4. 两表存在同标题，两个接口各自返回，证明没有跨源去重。
5. major 标题重复只保留最新。
6. major 空标题、空正文不返回。
7. 断言 `contentSource/category/panelKey/root field/sortRule`。
8. 断言 `/stocks` 为 404，`/communications` 正常。
9. 参数化覆盖：非空标题完整开头 `【标题】摘要`、空标题正文完整开头 `【标题】正文`、前后空白、多个括号、缺右括号、空括号、标题中部括号、正文中部括号和普通空标题正文 fallback。
10. 示例新闻的列表 `title` 精确等于 `商务部等9部门：支持航空保税维修绿色化发展`，且响应中不包含右括号后的摘要。
11. 两条新闻的括号候选无论来自非空 `title` 还是空标题正文，只要提取后的标题相同，就按最终展示标题去重并保留最新记录。
12. `major_news` 中形似 `【标题】摘要` 的原始标题保持不变，证明规则没有扩散到新闻通讯。
13. 新浪财经 fixture 不进入列表；更晚的新浪记录不改变 `observed_at`；同一主键详情返回 404。

### 9.2 后端详情测试

修改 `tests/web/test_wealth_market_news_reader_api.py`：

1. `news` URL/HTML/TEXT 三态继续通过。
2. `major_news.content` 为 HTML 且 `url` 非空时：
   - `readerMode=HTML`
   - `html` 非空
   - active `url=null`
   - `originalUrl` 等于数据库事实
3. major 纯文本返回 TEXT。
4. major content 恰好为 URL 字符串时返回 TEXT，不进入 URL mode。
5. 指定 `major_news` 来源但 ID 只存在于 `news` 时返回 404，反向同理。
6. 非法来源、非法 ID、空正文、超大正文和查询异常受控。
7. 旧 `/items/{news_id}` 为 404。
8. `contentSource=news` 的详情 `title` 与列表同一新闻的 `title` 完全一致，并只包含括号内标题。
9. 缺右括号、空括号和非开头括号继续使用原有标题或正文前 80 字 fallback；仅当 `title` 为空且正文候选以完整非空 `【...】` 开头时才从正文构造标题，不得扫描正文中部。
10. `contentSource=major_news` 详情标题保持原始 trim 规则。
11. 同花顺 HTML 和 TEXT fixture 均移除有/无句号的固定推广文字并保留正文主体。
12. 财联社等其它来源即使包含相同文案也保持原文，证明清理规则没有扩散。

### 9.3 前端测试

修改：

```text
wealth/src/test/market-overview-news-real-api.test.tsx
wealth/src/pages/market-overview/MarketOverviewPage.test.tsx
wealth/src/features/market-overview/news/**/*.test.ts(x)
wealth/src/shared/ui/news-reader/**/*.test.ts(x)
```

覆盖：

1. 页面请求 briefs 和 communications。
2. UI 标题“新闻通讯”。
3. 两列独立 refresh/error/empty。
4. 点击 briefs 传 `news`，点击 communications 传 `major_news`。
5. 响应来源或 ID 不一致时 contract error。
6. major HTML 进入 HTML renderer，`originalUrl` 不出现在 DOM。
7. 列表刷新时打开的 reader 不关闭。
8. close 后按 source+id 恢复焦点。
9. stock-detail 相关测试不改 fixture、不改断言。
10. 真实 API 展示测试承接后端 `【标题】摘要 -> 标题` 合同，fixture 只提供后端归一化后的 API `title`；断言列表按钮与阅读器 `<h2>` 都显示 `标题`，DOM 中不出现尾部摘要，前端不负责解析原始标题。

### 9.4 静态门禁

增加或扩展目标静态测试，限定市场总览新闻路径：

1. 禁止 `/news/stocks`。
2. 禁止 `StockNewsQuery` 和 `build_stock_news`。
3. 禁止在 `MarketNewsQuery` 中出现 `channels`。
4. 禁止 `major_news` reader 调用 URL resolver 分支。
5. 禁止前端用 `originalUrl` 生成 `href/src/window.open`。
6. 禁止 reader query 同时 import 两个 model 后做 fallback scan；source dispatch 必须在 service 层显式完成。

## 10. 性能门禁

| 项 | 上限/口径 |
|---|---|
| 列表 SQL | 每个接口 1 次主查询 + 1 次 observed 查询，均为有界窗口 |
| 列表候选 | 每个接口最多 300 条 |
| 列表正文 | 不 select、不序列化 |
| 标题归一化 | 现有单次列表 SQL 内完成；常量级字符串操作，0 次额外查询 |
| 来源过滤 | 进入窗口候选和 observed 聚合前完成；不新增查询 |
| 详情 SQL | 1 次主键查询，`LIMIT 1`，只查指定来源 |
| 同花顺尾注 | 已加载单篇正文上的两个固定 literal 替换；不扫描其它新闻、不访问外网 |
| 外部 URL 请求 | major 路径 0 次 |
| 模糊匹配 | 0 次 |
| 前端请求 | 每面板独立，沿用现有节奏；详情一次只请求一条 |
| 详情载荷 | 256 KiB 上限 |

不得为此次改源新增缓存、后台抓取、数据库迁移或额外轮询。

## 11. 开发顺序与每步验收

1. **合同先行**：新增来源 enum、communications response、reader `contentSource/originalUrl`；schema 测试先红后绿。
2. **列表后端**：去除 briefs 频道过滤，新增 major query/API，删除 stock query/API；列表测试通过。
3. **详情后端**：来源路由、major query、source-specific resolver；详情测试通过。
4. **router 清理**：删除旧 route import/include；OpenAPI/路由测试确认旧路径 404。
5. **前端 type/API**：一次性替换 stock contract 和 route；TypeScript 无旧别名。
6. **页面状态和组件**：全量 rename，保持布局不变；页面测试通过。
7. **reader identity**：按 source+id 请求和恢复焦点；reader 回归通过。
8. **标题提取增量**：新增统一 normalizer，列表表达式先归一化再去重，详情复用 Python 入口；列表/详情/真实展示测试通过。
9. **通讯展示策略增量**：来源常量与尾注纯函数先落测试，随后接入 major list/observed/detail 和 resolver；不改 API/前端。
10. **静态门禁与全量目标验证**：执行目标后端测试、Wealth 测试、typecheck、build、diff check。
11. **文档收口**：代码完成后再把 API 当前基线和异常码状态改为已生效，不能提前宣称上线。

## 12. 验证命令

```bash
cd /Users/congming/github/goldenshare

uv run python -m pytest \
  tests/web/test_wealth_market_news_api.py \
  tests/web/test_wealth_market_news_reader_api.py

cd /Users/congming/github/goldenshare/wealth
npm run test -- market-overview-news-real-api MarketOverviewPage news-reader
npm run typecheck
npm run build

cd /Users/congming/github/goldenshare
python3 scripts/check_docs_integrity.py
git diff --check
```

原开发轮次不启动服务、不部署、不访问浏览器做视觉验收；部署和最终 UI 验收由用户另行执行。该交付边界保留为历史记录，并已随 2026-09-01 结案关闭。

2026-08-27 当前开发验证结果：后端目标测试 41 项通过；市场总览与阅读器目标前端测试 50 项通过；Wealth 全量测试 335 项、架构依赖测试 4 项、`typecheck`、`build` 通过；文档完整性与 `git diff --check` 通过。构建仅保留既有大 chunk 警告，不影响本增量。

2026-08-28 空标题正文提取补充验证结果：后端新闻列表与阅读器目标测试 50 项通过；Wealth 全量测试 370 项、`typecheck`、`build` 通过；架构依赖护栏 16 项通过；文档完整性与 `git diff --check` 通过。扩大到 `tests/web` 后为 834 项通过、1 项跳过、1 项失败；唯一失败是未改动的板块总览地域详情仍返回 `hierarchyPath: null`，与其测试要求字段不存在冲突。仓库级 `pytest -q` 还在收集阶段被既有 Lake Console 缺失模块和两个同名 `test_tushare_client.py` 冲突阻断，未进入测试执行；这些阻断均不来自本次改动，未越界修复。

## 13. 计划对账模板

开发收口时必须逐项填写：

| ID | 代码文件 | 测试 | 结果 |
|---|---|---|---|
| N01-N03 | `market_news_query.py`、`major_news_query.py`、`news_query_service.py`、新闻列表 DTO | `test_wealth_market_news_api.py` | 已完成：news 全频道、major_news 独立查询、跨源同名保留且源内去重 |
| N04-N09 | 双源 reader query/service/resolver、`news_item.py`、前后端 API/adapter、router 与旧 stock 合同删除 | `test_wealth_market_news_reader_api.py`、`market-news-reader-controller.test.tsx`、`market-overview-news-real-api.test.tsx` | 已完成：双维身份、major HTML/TEXT、originalUrl 仅溯源、旧路由/字段清零 |
| N10-N14 | `MarketOverviewPage.tsx`、`MarketNewsPanelGroup.tsx`、`useMarketNewsReader.ts`，shared reader 保持不变 | `MarketOverviewPage.test.tsx`、`news-reader-dialog.test.tsx`、静态清零门禁 | 已完成：独立状态刷新、modal 行为不变、10 分钟窗口与无兼容层 |
| N15 | `SanitizedHtmlContent.tsx` | `news-reader-dialog.test.tsx` | 已完成：移除畸形自闭合 iframe，保留后续正文且安全边界不放宽 |
| N16-N17 | `news_display_title.py`、`market_news_query.py`、`news_reader_query_service.py`；前端只消费合同 | `test_wealth_market_news_api.py`、`test_wealth_market_news_reader_api.py`、`market-overview-news-real-api.test.tsx` | 已完成：空标题正文开头与非空标题统一提取并参与最终标题去重；畸形回退、正文中部不扫描及 major/stock-detail 作用域隔离保持不变 |
| N18-N19 | `major_news_display_policy.py`、`major_news_query.py`、`major_news_reader_query.py`、major resolver 调用链 | `test_wealth_market_news_api.py`、`test_wealth_market_news_reader_api.py` | 已完成：新浪列表/观测/详情统一过滤；同花顺固定推广文字按来源清理且正文主体保留 |

本需求已结案。后续若任何正式数据事实与本 LLD 冲突，先停下审计并更新方案，不允许临时回退 URL 或恢复旧 `/stocks` 兜底。
