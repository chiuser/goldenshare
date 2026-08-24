# 市场总览｜新闻速览、新闻通讯与阅读器低层设计 v2（LLD）

> 稳定文档路径沿用 `market-news-reader-low-level-design-v1.md`，正文版本升级为 v2。
> 状态：开发完成，待用户部署与页面验收。
> 日期：2026-08-24。
> 技术方案：[market-news-implementation-design-v1.md](./market-news-implementation-design-v1.md)。
> 视觉与 modal 合同：[market-news-reader-implementation-design-v1.md](./market-news-reader-implementation-design-v1.md)。

## 1. 开工结论

当前代码已经完成新闻弹窗阅读器，但列表和详情仍绑定旧的 `news + channels` 分流。本 LLD 的开发目标是一次性完成以下合同迁移：

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
    COALESCE(NULLIF(TRIM(title), ''), SUBSTR(TRIM(content), 1, 80)) AS display_title,
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
).where(MajorNewsLight.row_key_hash == news_id).limit(1)
```

不 join `NewsLight`，不按标题 fallback。

### 5.4 source-specific resolver

现有 `resolve_news_reader_content()` 保持 `news` 的 URL > HTML > TEXT 语义。

在同一 resolver 模块新增：

```python
def resolve_major_news_reader_content(content: str | None) -> ResolvedNewsReaderContent:
    text = validate_nonempty_and_size(content)
    if re.search(NEWS_READER_HTML_PATTERN, text):
        return ResolvedNewsReaderContent(mode="HTML", url=None, html=text, content=None)
    return ResolvedNewsReaderContent(mode="TEXT", url=None, html=None, content=text)
```

应抽取共享的非空和 256 KiB 校验，避免两套上限漂移。`resolve_major_news_reader_content()` 不调用 URL classifier。

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
    resolved = resolve_major_news_reader_content(row.content)
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

1. `news` 继续允许由正文构造最多 80 字 fallback title。
2. `major_news` 列表已要求标题非空；详情若标题为空则受控 `NOT_FOUND`，不从 HTML 正文拼标题。

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
| 详情 SQL | 1 次主键查询，`LIMIT 1`，只查指定来源 |
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
8. **静态门禁与全量目标验证**：执行目标后端测试、Wealth 测试、typecheck、build、diff check。
9. **文档收口**：代码完成后再把 API 当前基线和异常码状态改为已生效，不能提前宣称上线。

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

不启动服务、不部署、不访问浏览器做视觉验收；部署和最终 UI 验收由用户另行执行。

## 13. 计划对账模板

开发收口时必须逐项填写：

| ID | 代码文件 | 测试 | 结果 |
|---|---|---|---|
| N01-N03 | `market_news_query.py`、`major_news_query.py`、`news_query_service.py`、新闻列表 DTO | `test_wealth_market_news_api.py` | 已完成：news 全频道、major_news 独立查询、跨源同名保留且源内去重 |
| N04-N09 | 双源 reader query/service/resolver、`news_item.py`、前后端 API/adapter、router 与旧 stock 合同删除 | `test_wealth_market_news_reader_api.py`、`market-news-reader-controller.test.tsx`、`market-overview-news-real-api.test.tsx` | 已完成：双维身份、major HTML/TEXT、originalUrl 仅溯源、旧路由/字段清零 |
| N10-N14 | `MarketOverviewPage.tsx`、`MarketNewsPanelGroup.tsx`、`useMarketNewsReader.ts`，shared reader 保持不变 | `MarketOverviewPage.test.tsx`、`news-reader-dialog.test.tsx`、静态清零门禁 | 已完成：独立状态刷新、modal 行为不变、10 分钟窗口与无兼容层 |

未完成项不得默认为完成；若任何正式数据事实与本 LLD 冲突，先停下审计并更新方案，不允许临时回退 URL 或保留旧 `/stocks` 兜底。
