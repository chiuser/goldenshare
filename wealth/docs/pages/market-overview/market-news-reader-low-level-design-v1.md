# 市场总览｜新闻弹窗阅读器低层设计 v1（LLD）

> 状态：首轮部署反馈修正开发完成，待用户重新部署与视觉复验。
> 日期：2026-08-23
> 技术方案：[market-news-reader-implementation-design-v1.md](./market-news-reader-implementation-design-v1.md)
> 视觉依据：Figma `RADlZzREU4lPVviYfkLy6x`，`13 News Reader - Components and States`（node `876:2`）。
> 实施范围：PC Web 的共享新闻阅读器，以及市场总览“新闻速览/个股新闻”接入。

---

## 1. 开工结论

本 LLD 已把技术方案、Figma、当前代码与开发结果逐项对齐。实现严格沿本文规定的文件、契约、状态机和测试推进，部署与浏览器视觉验收仍由用户完成。

本轮只做：

1. 新增新闻详情 API，按 `URL > HTML > TEXT` 返回唯一正文载荷。
2. 将两个首页新闻列表改为可点击，并返回轻量 `readerMode` 提示。
3. 新增一个 PC Web 共享阅读器，支持 URL、HTML、纯文本、loading、empty 和 error。
4. 使用原生 modal dialog 获得焦点、阻断背景交互，并显式完成滚动锁定和焦点恢复。

本轮不做：

1. 不新增新闻详情路由，不改变浏览器地址。
2. 不接入股票详情新闻。
3. 不实现移动端。
4. 不修改新闻采集、列表分类、排序或十分钟刷新。
5. 不修改数据库结构，不做代理抓取，不访问任意外部 URL。

## 2. 计划硬口径与代码映射

| ID | 硬口径 | 代码落点 | 必须测试的反例 |
|---|---|---|---|
| G01 | 内容优先级固定为 URL > HTML > TEXT | `news_reader_content_resolver.py` | 混合 URL 文本不得判为 URL；脚本 scheme 不得判为 URL |
| G02 | 列表轻量，正文点击后再取 | `market_news_query.py`、`stock_news_query.py`、列表 DTO | 列表 JSON 不得出现正文、HTML 或 URL 载荷 |
| G03 | 详情只按稳定 ID 精确查询一行 | `news_reader_query.py` | 不存在 ID 返回 404；不得按标题回退 |
| G04 | 两个列表共用一个阅读器 | `MarketOverviewPage.tsx`、`useMarketNewsReader.ts` | 两个 panel 均能打开；页面只挂载一个 dialog |
| G05 | 弹窗获得焦点，背景不可点击 | `NewsReaderDialog.tsx` 的原生 `showModal()` | 不得使用普通绝对定位 div 冒充 modal |
| G06 | 关闭后回到触发 item | controller 保存 trigger；dialog 关闭后恢复 | X、Escape、请求失败后关闭均恢复焦点 |
| G07 | 弹窗打开时背景不可滚动 | `useModalScrollLock.ts` 或 dialog 内部 effect | 关闭/卸载后必须恢复原 inline style |
| G08 | 遮罩点击不关闭 | dialog 只处理 X 和 `cancel` | 点击 backdrop 不触发 `onClose` |
| G09 | HTML 必须安全清洗 | `SanitizedHtmlContent.tsx` + DOMPurify | script、事件属性、危险链接不得进入 DOM |
| G10 | URL 不经过后端代理 | iframe 直接消费已校验 http/https URL | 后端不得出现 `httpx/requests/urlopen` |
| G11 | 快速切换不会串线 | `AbortController` + monotonically increasing request id | A 后返回不得覆盖 B |
| G12 | 列表刷新不打断阅读 | reader state 与 list state 分离 | 十分钟 refresh 后 dialog 仍保留原正文 |
| G13 | PC 自适应大弹窗 | `news-reader.css` | 1920×1080、1440×900、1280×720 不裁切 |
| G14 | 不扩散到无关模块 | 文件白名单和静态门禁 | stock-detail news、其它首页模块不得被修改 |

## 3. 当前代码审计

### 3.1 当前调用链

```text
MarketOverviewPage
  -> fetchMarketNewsBriefs / fetchStockNews
  -> GET /api/v1/wealth/market/news/briefs|stocks
  -> MarketNewsQueryService
  -> MarketNewsQuery / StockNewsQuery
  -> core_serving_light.news
  -> NewsListPanelDto
  -> marketNewsAdapter
  -> MarketNewsPanel
  -> div[aria-disabled=true]
```

当前不存在详情请求、reader controller、modal/dialog 或 sanitizer。

### 3.2 后端代码事实

| 文件 | 当前事实 | 本轮改动 |
|---|---|---|
| `src/foundation/models/core_serving_light/news.py` | `row_key_hash` 为 `String(64)` 主键；正文只在 `content`；来源展示当前使用 `src` | 不改模型和表 |
| `market_news_query.py` | 非公司新闻；按展示标题去重；只投影 id/time/title/src | 增加 SQL 侧 `reader_mode` hint，不返回正文 |
| `stock_news_query.py` | 公司频道新闻；复用 `NewsQueryRow` | 同步投影 `reader_mode` |
| `news_query_service.py` | DTO 强制 `url=None`、`clickable=False` | 改为 `clickable=True` 并传 `readerMode` |
| `news_briefs.py` / `stock_news.py` | 两个列表路由均使用 `require_quote_access` | 行为不变 |
| `src/app/api/v1/router.py` | 显式装配两个新闻列表 router | 新增详情 router |

正式 ingestion 的 `_news_row_transform()` 使用 SHA-256 生成 64 位 `row_key_hash`。但是现有 API 测试使用 `market-news-001` 等可读 ID。为了不把测试表达和当前路由契约无理由收窄，详情路径参数采用“1 至 64 个 URL-safe 字符”，而不是只允许 64 位十六进制；正式数据仍自然使用 SHA-256 ID。

### 3.3 前端代码事实

| 文件 | 当前事实 | 本轮改动 |
|---|---|---|
| `marketNewsApi.ts` | `clickable:false`、`clickablePolicy:"disabled"`、`url:null` | 改为 reader 合同；增加独立详情 client 文件 |
| `marketNewsAdapter.ts` | 丢弃来源和内容模式 | 保留 `readerMode`，不自行分类 |
| `MarketNewsPanel.tsx` | item 是不可点击 `div`；滚动时复制 items | 改为语义化 button；复制项仍使用同一 ID |
| `MarketOverviewPage.tsx` | 两列表独立加载；共用 5 秒超时；每十分钟刷新；刷新失败保留旧列表 | 只装配一个 reader controller/dialog；不改列表刷新语义 |
| `market-overview-page.css` | 新闻卡片 CSS 与页面其它样式共处 | 只增加 item button 接入样式；reader 样式独立文件 |
| `wealth/src/shared/ui` | 没有 modal/dialog | 新建共享 reader 目录 |
| `wealth/package.json` | 无 sanitizer | 增加 `dompurify` 直接依赖并更新 lockfile |

### 3.4 测试影响面

1. 后端现有回归：`tests/web/test_wealth_market_news_api.py`。
2. 前端真实接口回归：`wealth/src/test/market-overview-news-real-api.test.tsx`。
3. Vitest 使用 jsdom；当前 setup 没有 `HTMLDialogElement.showModal/close` polyfill。
4. native dialog 的 top-layer/inert 是浏览器行为，jsdom 单测只能验证调用和组件状态；真实背景点击阻断留作浏览器验收门禁，不能伪称单测已验证浏览器 top layer。

### 3.5 CodeGraph 影响面

CodeGraph 已检查：

1. 页面到列表 API、query、model 的完整调用链。
2. `MarketNewsPanel`、adapter、API type 和 `MarketOverviewPage` 的消费者关系。
3. shared UI 当前没有 dialog 基础设施。
4. 市场总览真实 API 测试和后端路由测试。
5. 股票详情新闻是另一套 API/view model，本轮保持不变。

依赖方向不变：`biz -> foundation`，`app` 只负责 router 装配；前端 shared reader 不反向依赖 feature。

## 4. 目标文件清单

### 4.1 新增文件

```text
src/biz/api/wealth/market/news_item.py
src/biz/queries/wealth/market/news/news_reader_query.py
src/biz/queries/wealth/market/news/news_reader_query_service.py
src/biz/schemas/wealth/market/news_reader.py
src/biz/services/wealth/market/news/news_reader_content_resolver.py

wealth/src/shared/ui/news-reader/NewsReaderDialog.tsx
wealth/src/shared/ui/news-reader/SanitizedHtmlContent.tsx
wealth/src/shared/ui/news-reader/newsReaderTypes.ts
wealth/src/shared/ui/news-reader/news-reader.css
wealth/src/features/market-overview/news/api/marketNewsReaderApi.ts
wealth/src/features/market-overview/news/api/marketNewsReaderAdapter.ts
wealth/src/features/market-overview/news/model/useMarketNewsReader.ts

tests/test_wealth_market_news_reader_content_resolver.py
tests/web/test_wealth_market_news_reader_api.py
wealth/src/test/news-reader-dialog.test.tsx
wealth/src/test/market-news-reader-controller.test.tsx
```

### 4.2 修改文件

```text
src/app/api/v1/router.py
src/biz/queries/wealth/market/news/market_news_query.py
src/biz/queries/wealth/market/news/stock_news_query.py
src/biz/queries/wealth/market/news/news_query_service.py
src/biz/schemas/wealth/market/news_briefs.py

wealth/package.json
wealth/package-lock.json
wealth/src/features/market-overview/news/api/marketNewsApi.ts
wealth/src/features/market-overview/news/api/marketNewsAdapter.ts
wealth/src/features/market-overview/news/MarketNewsPanel.tsx
wealth/src/pages/market-overview/MarketOverviewPage.tsx
wealth/src/pages/market-overview/market-overview-page.css
wealth/src/test/setup.ts
wealth/src/test/market-overview-news-real-api.test.tsx
```

禁止修改 `NewsLight` model、迁移、stock-detail news、新闻 ingestion、市场总览其它 feature。

## 5. 后端详细设计

### 5.1 内容模式类型与常量

`news_reader_content_resolver.py` 定义：

```python
NewsReaderMode = Literal["URL", "HTML", "TEXT"]
NEWS_READER_MAX_CONTENT_BYTES = 256 * 1024
NEWS_READER_URL_PATTERN = r"(?is)^https?://[^\s]+$"
NEWS_READER_HTML_PATTERN = (
    r"(?is)<(?:!doctype\s+html|html\b|head\b|body\b|article\b|section\b|"
    r"div\b|p\b|h[1-6]\b|ul\b|ol\b|li\b|table\b|blockquote\b|br\b)[^>]*>"
)
```

数据对象：

```python
@dataclass(frozen=True, slots=True)
class ResolvedNewsReaderContent:
    mode: NewsReaderMode
    url: str | None
    html: str | None
    content: str | None
```

函数签名：

```python
def classify_news_reader_mode(content: str) -> NewsReaderMode: ...
def resolve_news_reader_content(content: str | None) -> ResolvedNewsReaderContent: ...
```

执行顺序：

1. `None` 或 `strip()` 后为空：抛 `NewsReaderContentEmptyError`。
2. 用 `len(text.encode("utf-8"))` 校验 256 KiB；超限抛 `NewsReaderContentTooLargeError`。
3. URL full-match 成功时，用 `urlsplit()` 二次确认 scheme 为 `http/https` 且 `netloc` 非空。
4. 否则 HTML pattern search 成功为 HTML。
5. 其余为 TEXT。

不做 URL 连通性检查，不下载网页，不在后端清洗 HTML。

### 5.2 列表 SQL hint

在 `market_news_query.py` 增加私有表达式：

```python
def _reader_mode_expr():
    normalized = func.trim(NewsLight.content)
    return case(
        (normalized.regexp_match(NEWS_READER_URL_PATTERN), literal("URL")),
        (normalized.regexp_match(NEWS_READER_HTML_PATTERN), literal("HTML")),
        else_=literal("TEXT"),
    )
```

`NewsQueryRow` 增加：

```python
reader_mode: NewsReaderMode
```

两个列表 query 都必须：

1. 在 deduped subquery 中投影 `reader_mode`。
2. 在外层 select 中读取该列。
3. 保持现有 window、channel、title dedupe、sort、limit、observed_at 逻辑完全不变。

SQL hint 与 Python resolver 共用两个 pattern 常量。`regexp_match()` 在正式 PostgreSQL 编译为原生正则匹配，在 Web 测试 SQLite 编译为 SQLAlchemy 注册的 `REGEXP`，不得为测试数据库维护第二套分类逻辑。测试对同一 fixture 分别运行 SQL 和 Python 分类，结果必须一致。

### 5.3 列表 DTO 破坏性更新

`NewsPanelItemDto`：

```python
class NewsPanelItemDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    newsId: str
    publishTime: datetime
    displayTime: str
    title: str
    category: NewsCategoryValue
    source: str | None = None
    subject: NewsSubjectRefDto | None = None
    priority: int | None = 0
    readerMode: Literal["URL", "HTML", "TEXT"]
    clickable: Literal[True] = True
```

删除 `url`。`NewsListPanelDto.clickablePolicy` 改为唯一值 `Literal["reader"]`。

`MarketNewsQueryService._build_panel_dto()` 只透传 `row.reader_mode`。error panel 继续返回空 items，结构无需假造正文模式。

### 5.4 详情 query

`news_reader_query.py`：

```python
@dataclass(frozen=True, slots=True)
class NewsReaderQueryRow:
    news_id: str
    publish_time: datetime
    title: str | None
    source: str
    content: str | None

class NewsReaderQuery:
    def load_by_id(self, session: Session, *, news_id: str) -> NewsReaderQueryRow | None: ...
```

SQL 固定为：

```python
select(
    NewsLight.row_key_hash,
    NewsLight.news_time,
    NewsLight.title,
    NewsLight.src,
    NewsLight.content,
).where(NewsLight.row_key_hash == news_id).limit(1)
```

禁止 join、窗口函数、模糊查询和同标题回退。

### 5.5 详情 DTO

`news_reader.py`：

```python
class NewsReaderItemDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    newsId: str
    title: str
    source: str | None
    publishTime: datetime
    readerMode: Literal["URL", "HTML", "TEXT"]
    url: str | None
    html: str | None
    content: str | None
```

增加 `model_validator(mode="after")`：

1. `URL` 时仅 `url` 非空。
2. `HTML` 时仅 `html` 非空。
3. `TEXT` 时仅 `content` 非空。
4. 任意多载荷、零载荷或模式错配拒绝创建 DTO。

标题规则：`row.title.strip()` 非空则使用；否则从去标签/纯文本后的正文取前 80 个 Unicode 字符；仍为空则进入 not-found。

### 5.6 Query service 与异常映射

`NewsReaderQueryService`：

```python
class NewsReaderQueryService:
    def build_news_reader_item(
        self,
        session: Session,
        *,
        news_id: str,
    ) -> NewsReaderItemDto: ...
```

service 只编排主键 query、resolver 和 DTO，不吞 SQL 异常。API 将异常映射为：

| 场景 | HTTP | code |
|---|---:|---|
| ID 长度/字符非法 | 400 | `NEWS_READER_REQUEST_INVALID` |
| 主键不存在/正文为空 | 404 | `NEWS_READER_NOT_FOUND` |
| 内容类型或 URL 合同非法 | 422 | `NEWS_READER_CONTENT_INVALID` |
| 正文大于 256 KiB | 413 | `NEWS_READER_CONTENT_TOO_LARGE` |
| 未预期查询/服务异常 | 500 | `NEWS_READER_QUERY_FAILED` |

500 响应使用固定用户文案；异常细节只写服务日志，不进入 HTTP body。

### 5.7 详情 route

`news_item.py`：

```python
router = APIRouter(prefix="/wealth/market/news", tags=["wealth-market"])

@router.get("/items/{news_id}", response_model=NewsReaderItemDto)
def get_news_reader_item(
    news_id: str,
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> NewsReaderItemDto: ...
```

route 内显式执行：

```python
normalized_news_id = news_id.strip()
if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", normalized_news_id):
    raise WebAppError(
        status_code=400,
        code="NEWS_READER_REQUEST_INVALID",
        message="新闻标识无效",
    )
```

不增加 `debug`、market 或日期参数。router 由 `src/app/api/v1/router.py` 显式装配。

## 6. 前端数据合同

### 6.1 列表合同

`marketNewsApi.ts`：

```ts
export type NewsReaderMode = "URL" | "HTML" | "TEXT";

export interface NewsPanelItemResponse {
  // existing fields unchanged
  readerMode: NewsReaderMode;
  clickable: true;
}

export interface NewsListPanelResponse {
  // existing fields unchanged
  clickablePolicy: "reader";
}
```

删除列表 item 的 `url` 字段。adapter 输出：

```ts
export interface MarketNewsViewItem {
  newsId: string;
  publishTime: string;
  displayTime: string;
  title: string;
  readerMode: NewsReaderMode;
  clickable: true;
}
```

adapter 只透传 `readerMode`，禁止解析正文或猜测模式。

### 6.2 详情合同

`marketNewsReaderApi.ts`：

```ts
export interface NewsReaderItemResponse {
  newsId: string;
  title: string;
  source: string | null;
  publishTime: string;
  readerMode: NewsReaderMode;
  url: string | null;
  html: string | null;
  content: string | null;
}

export function fetchMarketNewsReaderItem(
  newsId: string,
  options?: { signal?: AbortSignal },
): Promise<NewsReaderItemResponse>;
```

使用 `encodeURIComponent(newsId)` 和现有 `wealthFetch`。非 2xx 解析统一 `{code,message}` 并抛 `MarketNewsReaderApiError`。

adapter 必须再做一次防御性互斥校验；后端 payload 不符合模式时转为 `NEWS_READER_CONTRACT_INVALID` 前端错误，不把可疑载荷传给 shared reader。

## 7. Reader controller 状态机

### 7.1 状态类型

`useMarketNewsReader.ts`：

```ts
type ReaderState =
  | { status: "closed" }
  | {
      status: "loading";
      newsId: string;
      title: string;
      publishTime: string;
      readerMode: NewsReaderMode;
      requestId: number;
    }
  | { status: "ready"; requestId: number; item: NewsReaderViewModel }
  | {
      status: "empty";
      newsId: string;
      title: string;
      publishTime: string;
      message: string;
    }
  | {
      status: "error";
      newsId: string;
      title: string;
      publishTime: string;
      message: string;
      retryable: boolean;
    };
```

controller API：

```ts
interface MarketNewsReaderController {
  state: ReaderState;
  open(item: MarketNewsViewItem, trigger: HTMLElement): void;
  close(): void;
  retry(): void;
}
```

### 7.2 请求一致性

1. `open()` 先 abort 旧请求，再递增 `requestSequence`。
2. 立即写入 loading state；不等待详情响应才打开。
3. 响应回来时必须同时满足：未 abort、requestId 等于当前值、newsId 等于当前 loading item。
4. 404/`NEWS_READER_NOT_FOUND` -> empty。
5. 内容 invalid/too-large、iframe error -> error。
6. timeout/network/query failed -> retryable error。
7. `close()` abort、递增 sequence、清空正文，最后恢复焦点。
8. 页面卸载时 abort；列表 refresh 不调用 controller.close。

详情 fetch timeout 固定 `5_000ms`。该常量只在 controller 内使用，不新增 env、Settings 或运营配置。

### 7.3 触发元素与焦点恢复

`open()` 保存：

```ts
triggerRef.current = trigger;
triggerNewsIdRef.current = item.newsId;
```

关闭后在下一 animation frame：

1. 原 trigger 仍 `isConnected`：调用 `focus({preventScroll:true})`。
2. 原 trigger 因十分钟刷新被替换：查询首个 `[data-news-reader-trigger][data-news-id="..."]` 并聚焦。
3. 找不到替代元素：不强行把焦点放到 body，也不滚动页面。

## 8. 原生模态弹窗与浏览器交互

### 8.1 为什么使用 `<dialog>`

组件必须用原生 `<dialog>` 并调用 `showModal()`，不能用普通 `div role="dialog"` 模拟。浏览器会把 modal dialog 放进 top layer，并让 dialog 外的文档进入 inert 状态，因此：

1. 背景控件不能获得指针或键盘交互。
2. Tab 焦点留在 modal 范围。
3. reader 获得当前交互焦点。
4. `::backdrop` 可按 Figma 绘制遮罩。

禁止同时给整个 app root 手工设置 `inert`；reader 通过 portal 挂到 `document.body`，错误的 root inert 容易把 dialog 一并禁用。native modal 已负责背景交互阻断。

### 8.2 组件生命周期

`NewsReaderDialog.tsx` 使用 `createPortal(..., document.body)`。核心 effect：

```ts
useEffect(() => {
  const dialog = dialogRef.current;
  if (!dialog) return;
  if (open && !dialog.open) dialog.showModal();
  if (!open && dialog.open) dialog.close();
}, [open]);
```

打开后：

1. close button 带 `autoFocus`，作为初始焦点。
2. `aria-labelledby` 指向标题。
3. `aria-describedby` 根据状态指向正文状态描述。

关闭路径只有：

1. 右上角 X。
2. `<dialog onCancel>` 捕获 Escape，`preventDefault()` 后调用统一 `onClose("escape")`。

不得给 dialog/backdrop 注册“点击空白处关闭”。

### 8.3 背景滚动锁定

native dialog 负责交互 inert，但不保证所有浏览器都禁止页面滚动。dialog 打开时额外：

1. 保存 `document.body.style.overflow` 与 `paddingRight` 原值。
2. 计算 `scrollbarGap = window.innerWidth - document.documentElement.clientWidth`。
3. 设置 `body.style.overflow="hidden"`。
4. gap 大于 0 时补等值 `padding-right`，避免背景布局横向跳动。
5. effect cleanup 精确恢复原 inline style，不写死为空字符串。

切换 loading/ready/error 不重复加锁；只有 closed -> open 和 open -> closed 改变锁状态。

### 8.4 尺寸和层级

```css
.news-reader-dialog {
  width: min(1440px, calc(100vw - 64px));
  height: min(900px, calc(100vh - 64px));
  max-width: none;
  max-height: none;
  padding: 0;
}
```

1. 头部固定高度，正文 `min-height:0; overflow:auto`。
2. 四周至少 32px。
3. 使用现有 `--cs-*` token；不硬编码另一个设计系统。
4. `::backdrop` 使用深色半透明遮罩。
5. z-index 只处理 reader 内部层次；top layer 不依赖页面 z-index 竞争。
6. 不增加移动端 media query。

## 9. 三类内容渲染

### 9.1 URL

`URL` ready 使用：

```tsx
<iframe
  src={item.url}
  title={item.title}
  referrerPolicy="no-referrer"
  sandbox="allow-scripts"
/>
```

不允许：`allow-same-origin`、`allow-forms`、`allow-popups`、`allow-downloads`、`allow-top-navigation`。

iframe loading 独立于详情 loading：

1. 详情返回 URL 后进入 `loading-url-frame`。
2. `onLoad` 后显示 iframe ready。
3. 12 秒未 load 进入受控 error。
4. close 或切换 item 时 clear timeout 并卸载 iframe。

浏览器无法可靠区分 CSP/X-Frame-Options 拒绝和部分跨域页面异常，不能把 12 秒超时描述为精确的外站拒绝检测。

### 9.2 HTML

新增 `dompurify` 依赖。只有 `SanitizedHtmlContent.tsx` 可以使用 `dangerouslySetInnerHTML`，输入必须是 DOMPurify 输出。

固定 allowlist：

```ts
const ALLOWED_TAGS = [
  "article", "section", "header", "footer",
  "h1", "h2", "h3", "h4", "h5", "h6",
  "p", "br", "hr", "blockquote", "pre", "code",
  "strong", "em", "b", "i", "u", "s",
  "ul", "ol", "li",
  "table", "thead", "tbody", "tr", "th", "td",
  "span", "div",
];
const ALLOWED_ATTR: string[] = [];
```

因此脚本、样式、表单、iframe、对象、音视频、SVG、图片、链接行为及全部源属性都不会进入 reader DOM。链接文字可保留，链接本身不具备跳转能力。

### 9.3 TEXT

纯文本用普通 React text node，样式 `white-space: pre-wrap; overflow-wrap:anywhere`。任何 `<script>` 字符串都必须按文字显示。

## 10. 首页接入

### 10.1 News item

`MarketNewsPanel` 增加：

```ts
onItemOpen?: (item: MarketNewsViewItem, trigger: HTMLButtonElement) => void;
```

item 改为：

```tsx
<button
  type="button"
  className="market-news-item"
  data-news-reader-trigger
  data-news-id={item.newsId}
  aria-haspopup="dialog"
  onClick={(event) => onItemOpen?.(item, event.currentTarget)}
>
```

保留 22px 行高、两列布局、ellipsis 和 hover 暂停滚动。新增明确的 `:focus-visible` 品牌色 outline。button reset 只作用于 `.market-news-item`。

### 10.2 Page 装配

`MarketOverviewPage`：

1. 调用一次 `useMarketNewsReader()`。
2. 两个 `MarketNewsPanel` 传同一个 `reader.open`。
3. 在页面根节点最后渲染一次 `NewsReaderDialog`。
4. 不把 reader state 混进两个列表 useEffect。
5. 不因 `newsBriefs/stockNews` refresh setState 关闭或替换 reader。
6. 页面卸载时 controller cleanup 请求与 dialog。

不得为了 reader 拆改首页其它模块或重构整页状态。

## 11. 状态与错误映射

| 来源 | reader 状态 | 用户表现 | 首页影响 |
|---|---|---|---|
| 点击 item | loading + mode hint | 对应 Figma 骨架 | 无 |
| 详情成功 | ready-url/html/text | 正文 | 无 |
| 404/not found | empty | 内容暂不可读 | 无 |
| 400 invalid | error/non-retryable | 新闻标识无效 | 无 |
| 413/422 | error/non-retryable | 内容无法安全展示 | 无 |
| 500/network/timeout | error/retryable | 重试按钮 | 无 |
| iframe 12s timeout | error/retryable | 页面无法嵌入 | 无 |
| 关闭 | closed | dialog 卸载并恢复焦点 | 无 |

error/empty 保持相同 header、尺寸和关闭按钮，不用 toast 代替 reader 状态。

## 12. 配置与常量审计

本轮不新增 env、Settings、数据库配置或运营开关。

| 常量 | 默认值 | 持久化 | 消费者 | 生效方式 |
|---|---:|---|---|---|
| `NEWS_READER_MAX_CONTENT_BYTES` | 262144 | 后端源码常量 | resolver | 发布后生效 |
| `NEWS_READER_FETCH_TIMEOUT_MS` | 5000 | feature 源码常量 | controller | 前端构建后生效 |
| `NEWS_READER_IFRAME_TIMEOUT_MS` | 12000 | shared 源码常量 | URL renderer | 前端构建后生效 |
| dialog safe gutter | 32px | shared CSS | reader layout | 前端构建后生效 |

这些是安全/布局硬边界，不对用户或运营开放。本轮不得把它们散落复制到 page 和 tests；测试从行为验证，不另造第二套业务常量。

## 13. 测试矩阵

### 13.1 Resolver 单元测试

1. 完整 http/https URL -> URL。
2. 大小写 scheme、首尾空格 -> 规范化 URL。
3. `javascript/data/file/ftp` -> TEXT 或 invalid，不得 URL。
4. “说明 + URL” -> TEXT。
5. HTML document/body/article/p/table -> HTML。
6. 小于号普通文字不误判 HTML。
7. 普通正文 -> TEXT。
8. 空白 -> empty exception。
9. UTF-8 字节数超过 256 KiB -> too-large。
10. 三种 resolved payload 严格互斥。

### 13.2 后端真实路由测试

1. 三类正文各返回正确 `readerMode` 和唯一载荷。
2. source 取 `NewsLight.src`，不取 `source`。
3. 无 title 时摘要标题稳定。
4. 不存在 ID -> 404 stable code。
5. 非法 ID -> 400 stable code。
6. query 异常 -> 500 且不泄露内部信息。
7. 未鉴权按现有环境合同拒绝。
8. SQL 只按主键读取一行。
9. 列表返回 reader hint/clickable，但 JSON 不含正文载荷。
10. briefs/stocks 原分类、去重、排序、300 条候选和 debug 行为不变。

### 13.3 Shared reader 测试

`wealth/src/test/setup.ts` 增加最小 dialog mock：

```ts
HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
```

测试：

1. open 调用 `showModal()`，close 调用 `close()`。
2. close button 是初始焦点。
3. Escape cancel 被 `preventDefault` 并关闭。
4. dialog/backdrop click 不关闭。
5. body overflow/padding 精确恢复。
6. URL iframe sandbox/referrer/title 正确。
7. HTML script/style/form/event attrs 不进入 DOM。
8. TEXT 的 HTML 字符串不解析。
9. empty/error/loading DOM 结构稳定。
10. 1280×720 下 CSS 仍保留 32px gutter（静态布局断言）。

注意：jsdom 不实现浏览器 top layer 和真实 inert。浏览器验收必须确认背景控件确实不可点、Tab 不逃逸、关闭后焦点返回；单测报告不得把这三项写成浏览器已验收。

### 13.4 Controller 与页面集成测试

1. briefs item 和 stocks item 都是 button。
2. 鼠标、Enter、Space 均能打开同一个 dialog。
3. 点击即显示与 list hint 一致的 loading。
4. 快速 A -> B 时 A 请求 abort，晚到响应不覆盖 B。
5. close abort 未完成请求。
6. X/Escape 后焦点回原 button。
7. 触发 button 被 refresh 替换时，按 ID 找新 button 恢复焦点。
8. 十分钟刷新替换列表时 reader 内容保持。
9. detail error 不清空列表，不影响其它首页模块。
10. open/close 不改变 `window.location`。

### 13.5 静态门禁

1. shared reader 不得 import `features/market-overview`。
2. backend reader 不得 import HTTP client、DuckDB、Lake 或 Dagster。
3. 列表 response 类型不得有 `url/html/content`。
4. `dangerouslySetInnerHTML` 只允许在 `SanitizedHtmlContent.tsx`，且输入变量必须为 sanitized result。
5. `MarketNewsPanel` 不得保留 `aria-disabled=true`。
6. `MarketOverviewPage` 只能挂载一个 `NewsReaderDialog`。
7. stock-detail news 文件不得出现在本轮 diff。
8. 不得出现 reader 移动端 media query。

## 14. 性能门禁

| 项 | 门禁 |
|---|---|
| 列表 SQL | 保持现有窗口、limit 和单次查询；只增加 bounded SQL CASE |
| 列表 payload | 不增加正文、HTML、URL；每 item 只增加枚举和布尔值 |
| 详情 SQL | 单主键查询、`LIMIT 1`、五列投影 |
| 详情正文 | UTF-8 最大 256 KiB |
| 前端并发 | 页面同时最多一个有效详情请求 |
| 详情超时 | 5 秒 |
| iframe 等待 | 12 秒 |
| DOM | 同时只保留当前一条正文和一个 iframe |
| 列表 refresh | 不重复详情请求、不打断 reader |

后端目标测试可用 SQL statement 计数证明详情只有一次业务查询。不得为性能测试访问正式生产库。

## 15. 实施顺序

### M1：后端合同

1. 异常码和 schema。
2. resolver 正反例。
3. 主键 query/service/API。
4. 列表 hint 和 clickable 破坏性更新。
5. 后端完整回归。

### M2：共享 reader

1. 安装 DOMPurify。
2. view model、dialog、scroll lock、三类 renderer。
3. dialog/jsdom 测试。

### M3：首页接入

1. 详情 client/adapter/controller。
2. 新闻 item button。
3. 页面单实例装配。
4. 请求竞态、刷新隔离、焦点恢复测试。

### M4：开发收口

1. 后端目标测试与列表回归。
2. Wealth 目标测试、`npm run typecheck`、`npm run test`、`npm run build`。
3. 静态门禁和 `git diff --check`。
4. 文档状态更新为“开发完成，待用户部署与视觉验收”。

## 16. 开发验收清单

| ID | 验收项 | 关闭证据 |
|---|---|---|
| A01 | 三类详情合同与互斥载荷 | resolver + route tests |
| A02 | 两个列表轻量可点击 | API tests + payload negative assertion |
| A03 | 单主键详情查询 | SQL query/statement test |
| A04 | 单一 shared reader | page DOM test |
| A05 | native modal lifecycle | dialog unit test + browser acceptance pending |
| A06 | 背景 inert/不可点击 | native showModal code fact + browser acceptance pending |
| A07 | 背景滚动锁定与恢复 | unit test |
| A08 | X/Escape 与焦点恢复 | controller/dialog tests |
| A09 | HTML 清洗 | DOMPurify security fixtures |
| A10 | URL sandbox | iframe attribute tests |
| A11 | 请求竞态和取消 | controller tests |
| A12 | 十分钟刷新不打断 | existing real API integration test extension |
| A13 | PC 布局 | CSS contract + user visual acceptance pending |
| A14 | 无关边界未变 | staged file list + static gate |

## 17. 风险与停机点

1. 若当前 `content` 中出现超出本分类规则的新格式，先补真实样本和规则测试，不在前端猜测。
2. 若产品要求被 CSP/X-Frame-Options 阻断的 URL 也必须站内显示，立即停止；那是独立代理/SSRF 专项。
3. 若 DOMPurify allowlist 无法表达实际 HTML 样本，先审计样本，再调整技术方案；不得临时放开 style、iframe 或 event attrs。
4. 若实现需要修改数据库、ingestion、stock-detail news 或移动端，立即停止等待 review。
5. native dialog 的 top-layer/inert 只能在真实浏览器最终验收；开发阶段不得用 jsdom 结果冒充。

## 18. 当前无待拍板项

本 LLD 没有新增业务拍板项。已冻结：

1. 只做 PC Web。
2. 内容优先级为 URL > HTML > TEXT。
3. 使用独立详情接口和单一 shared reader。
4. 使用 native modal dialog；背景不能点击，背景不能滚动。
5. X/Escape 关闭，不支持 backdrop 点击关闭。
6. URL 被外站拒绝时显示受控 error，不做代理绕过。

## 19. 开发完成记录

### 19.1 G01-G14 对账

| 门禁 | 开发事实 |
|---|---|
| G01-G03 | resolver、列表 SQL hint、单主键详情 query/service/API 已实现；列表无正文载荷 |
| G04 | `MarketOverviewPage` 只挂载一个 `NewsReaderDialog`，两个 panel 共用同一 controller |
| G05-G08 | native `showModal()`、X/Escape、背景滚动锁和焦点恢复已实现；backdrop 点击不关闭 |
| G09-G10 | DOMPurify 固定 allowlist；URL 仅由受限 iframe 直连，后端没有 URL fetch/proxy |
| G11-G12 | AbortController、递增 request id 和 reader/list state 隔离已实现 |
| G13 | PC 32px safe gutter CSS 合同已实现；真实三视口视觉验收待用户部署后完成 |
| G14 | 未修改 NewsLight、迁移、ingestion、stock-detail news、移动端或其它首页 feature |

### 19.2 自动化结果

1. 后端目标与列表回归：`24 passed`。
2. Wealth 阅读器目标：`19 passed`。
3. Wealth 全量回归：`52` 个测试文件、`332 passed`。
4. `npm run typecheck`：通过。
5. `npm run build`：通过；保留既有 bundle size warning，不在本需求中扩散修改。
6. Python compile、Ruff 和 `git diff --check`：通过。

### 19.3 待用户验收

1. 真实浏览器确认 modal top layer 下背景控件不可点击、Tab 不逃逸。
2. `1920×1080`、`1440×900`、`1280×720` 三种 PC 视口视觉验收。
3. 对实际 URL 新闻验证外站 iframe 允许/拒绝时的 ready/error 表现。
4. 用户验收完成前，本文状态保持“开发完成，待用户部署与视觉验收”。

## 20. 首轮部署反馈修正 LLD

### 20.1 根因与边界

部署截图对应的标题确实来自 `NewsReaderQueryService` 返回的 `row.title`，即 `NewsLight.title`。只有该字段为空时才会调用 `_build_content_title()`。本轮不修改后端 query、service、schema 或 API。

显示不完整的直接原因位于 `news-reader.css`：

1. `.news-reader-shell` 将头部固定为 `76px`。
2. `.news-reader-heading h2` 使用 `white-space: nowrap`、`overflow: hidden` 和 `text-overflow: ellipsis`。
3. `.news-reader-meta` 当前按“source、圆点、publishTime”顺序渲染。
4. 关闭按钮正文仍是字体字符 `×`，没有使用正式图标资产。

允许修改的实现文件仅为：

```text
wealth/src/shared/ui/news-reader/NewsReaderDialog.tsx
wealth/src/shared/ui/news-reader/news-reader.css
wealth/src/test/news-reader-dialog.test.tsx
```

以及本技术方案和 LLD。禁止修改新闻数据、详情 API、列表契约、controller、正文 renderer 和其它页面。

### 20.2 标题与头部布局

1. `.news-reader-shell` 改为 `grid-template-rows: auto minmax(0, 1fr)`。
2. `.news-reader-header` 保留最小高度 `76px`，实际高度由标题自然折行撑开。
3. `.news-reader-heading` 占据剩余宽度并继续设置 `min-width: 0`。
4. 标题删除单行截断三件套，改为 `white-space: normal` 和 `overflow-wrap: anywhere`，不得设置行数截断。
5. 关闭按钮保持固定尺寸和 `flex-shrink`，不得被长标题挤压。

### 20.3 元信息合同

`NewsReaderDialog` 的 ready 头部固定渲染：

```tsx
<time>{displayPublishTime}</time>
{source ? <span>来源：{source}</span> : null}
```

删除中间圆点元素，不保留“来源在前”的兼容分支。loading/empty/error 没有来源时只显示发布时间。

### 20.4 关闭图标

通过 Supericons 检索并冻结 `material:close`：

1. 使用工具返回的原始 `viewBox` 和 path。
2. SVG 使用 `fill="currentColor"`，尺寸由 `.news-reader-close svg` 固定为 `20px × 20px`。
3. SVG 设置 `aria-hidden="true"` 和 `focusable="false"`；可访问名称继续由 button 的 `aria-label="关闭新闻阅读器"` 提供。
4. button 的点击、焦点、Escape、hover 和 focus-visible 行为全部保持不变。
5. 不新增图标 npm 依赖，不手写另一种关闭符号。

### 20.5 测试门禁

1. 长标题完整进入 heading，CSS 不得出现 `white-space: nowrap` 或 `text-overflow: ellipsis`。
2. `time` 必须排在 `来源：sina` 之前，且不得出现圆点分隔元素。
3. 来源为空时只显示时间。
4. 关闭按钮必须包含 `data-icon-ref="material:close"` 的 SVG，不得再包含文本字符 `×`。
5. 原有 native dialog、Escape、焦点、scroll lock、URL sandbox、HTML sanitizer 和 PC 安全边距测试继续通过。
6. 验证命令固定为阅读器目标测试、`npm run typecheck`、`npm run test`、`npm run build` 和 `git diff --check`。

### 20.6 修正完成记录

1. `NewsReaderDialog` 已按“发布时间、来源”顺序渲染元信息，并移除圆点分隔。
2. 标题已取消单行截断，头部改为最小 `76px`、内容自适应高度。
3. 关闭按钮已替换为 Supericons 检索确认的 `material:close` SVG，关闭与可访问行为不变。
4. 阅读器目标测试：`3` 个文件、`21 passed`。
5. Wealth 全量回归：`52` 个测试文件、`334 passed`。
6. `npm run typecheck`、`npm run build` 通过；保留既有 bundle size warning，不扩散到本轮范围。
7. 用户重新部署前，真实 PC 视口下的标题折行和头部高度仍标记为待视觉复验。

## 21. 第二轮部署反馈修正 LLD：头部居中

### 21.1 影响面与禁止项

CodeGraph 与源码复核确认，本轮唯一运行时修改点为：

```text
wealth/src/shared/ui/news-reader/news-reader.css
wealth/src/test/news-reader-dialog.test.tsx
```

`NewsReaderDialog.tsx` 的 DOM 已满足“标题在上、元信息在下、关闭按钮为独立兄弟节点”的语义，不需要修改 JSX。禁止修改后端 API、新闻字段、adapter、controller、正文 renderer、弹窗状态机和其它页面。

### 21.2 精确布局合同

1. `.news-reader-header` 改为相对定位容器，不再使用关闭按钮参与分配宽度的横向 flex 布局。
2. Header 左右内边距必须对称，使 `.news-reader-heading` 的几何中心与整个阅读器中心一致。
3. `.news-reader-heading` 占满 Header 可用宽度并设置对称安全内边距，安全区至少覆盖右上角 `36px` 关闭按钮及其间距；长标题不得与关闭按钮重叠。
4. `.news-reader-heading h2` 使用 `text-align: center`，继续保留 `white-space: normal` 与 `overflow-wrap: anywhere`。
5. `.news-reader-meta` 使用 `justify-content: center`；时间和来源仍保持“发布时间、来源”的 DOM 顺序。
6. `.news-reader-close` 使用 `position: absolute` 固定在 Header 右上角；其大小、SVG、hover、focus-visible 和点击行为保持不变。
7. Header 继续保持最小高度 `76px`，多行标题通过内容自然撑高；正文仍由 `grid-template-rows: auto minmax(0, 1fr)` 使用剩余高度。

推荐实现口径：

```css
.news-reader-header {
  position: relative;
  padding: 14px 18px;
}

.news-reader-heading {
  box-sizing: border-box;
  padding-inline: 52px;
  text-align: center;
  width: 100%;
}

.news-reader-meta {
  justify-content: center;
}

.news-reader-close {
  position: absolute;
  right: 18px;
  top: 14px;
}
```

### 21.3 测试门禁

1. CSS 必须同时包含 Header `position: relative`、Close `position: absolute`、Heading `text-align: center` 和 Meta `justify-content: center`。
2. Heading 必须具有左右对称的关闭按钮安全区，禁止只给右侧留白造成视觉偏移。
3. 标题完整展示、时间在来源之前、来源为空、关闭图标、native dialog、scroll lock、URL sandbox 和 HTML sanitizer 现有测试继续通过。
4. CSS 继续禁止 `text-overflow: ellipsis`、`white-space: nowrap` 和移动端 media branch。
5. 验证只运行阅读器目标测试、Wealth typecheck、全量测试、build 和 `git diff --check`；不启动服务或执行浏览器验收。

### 21.4 完成记录

1. Figma `13 News Reader - Components and States` 的 8 个桌面 Modal 状态已改为标题、元信息全宽居中，关闭按钮固定右上。
2. `.news-reader-header` 已改为相对定位；Heading 使用对称安全区，Close 使用绝对定位，不再影响视觉中心。
3. 标题完整折行、元信息顺序、关闭图标和全部既有 reader 行为保持不变。
4. 阅读器目标测试：`10 passed`。
5. Wealth 全量回归：`52` 个测试文件、`334 passed`。
6. `npm run typecheck`、`npm run build` 通过；保留既有 bundle size warning，不扩散到本轮范围。
7. 当前状态为“开发完成，待用户部署与视觉复验”。
