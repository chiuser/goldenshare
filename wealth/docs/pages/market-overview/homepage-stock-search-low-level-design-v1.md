# 首页股票搜索低层设计 v1（LLD）

> 状态：D1-D4 本地开发与验证已完成，无待拍板项；待用户部署与验收。
> 日期：2026-09-02
> 上层方案：[首页股票搜索技术实施方案 v1](./homepage-stock-search-implementation-design-v1.md)
> 视觉事实源：[Goldenshare Web / M8 首页](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1264-471)

## 1. 完成结论

本 LLD 把已拍板的首页股票搜索收敛到代码符号、查询语义、状态转换和可执行测试。没有需要继续向用户确认的产品项。

本轮冻结：

1. 只新增 Wealth 自有搜索链路，不导入、不调用、不包装 Ops 或其它子项目搜索能力。
2. 搜索框只由市场总览首页挂载；搜索本体是 feature 级标准组件。
3. 候选池只包含当前上市 A 股：EQUITY、L、CNY、SSE/SZSE/BSE 四项必须同时满足。
4. 只支持股票代码、完整 tsCode、股票拼音首字母的前缀搜索。
5. 停止输入 500ms 后请求；Enter 或点击候选进入股票详情；详情既有默认日 K 合同保持不变。
6. 不新增数据库表、迁移、配置项、缓存、搜索引擎、历史搜索或热门搜索。

本文完成后可以按第 15 节顺序进入实现，但本次文档任务不授权或执行代码、数据库、部署变更。

## 2. 编码硬口径矩阵

| ID | 硬口径 | 代码落点 | 正向测试 | 负向测试 |
|---|---|---|---|---|
| S01 | API 只能属于 Wealth | src/biz/**/wealth/market/stock_search* | Wealth 路由返回候选 | 静态检查无 src.ops import |
| S02 | 只在首页出现 | MarketOverviewPage | 首页存在 combobox | 探查页和详情页无实例 |
| S03 | 标准组件 | features/stock-search/ui/StockSearch.tsx | 独立组件状态测试 | 页面不得复制输入与菜单 DOM |
| S04 | 500ms 防抖 | useStockSearchController | 499ms 无请求、500ms 一次 | 连续输入不得多发旧关键词 |
| S05 | 当前上市 A 股 | StockSearchQuery | 四项资格均满足时返回 | B 股、退市、非股票、其它交易所不返回 |
| S06 | 代码前缀 | StockSearchQuery | symbol/tsCode 前缀命中 | 任意中间子串不命中 |
| S07 | 拼音首字母前缀 | StockSearchQuery | cnspell 前缀命中 | name 命中不得返回 |
| S08 | 通配符隔离 | StockSearchPolicy + Query | 普通字符前缀正常 | 百分号、下划线不能扩大结果集 |
| S09 | 排序稳定 | StockSearchQuery | 完全匹配优先 | 同分不得依赖数据库隐式顺序 |
| S10 | 有界结果 | Policy + Query | 默认 8、最大 20 | limit 21 拒绝 |
| S11 | Wealth 鉴权 | API Depends | quote access 正常 | 无权限沿用统一 401/403 |
| S12 | 无静默回退 | API client/controller | 错误进入 Error | 不调用 mock、Ops 或本地全量池 |
| S13 | 旧响应失效 | Controller requestId | 最新关键词结果可见 | 旧请求晚到不得覆盖 |
| S14 | Enter 提交 | Controller + StockSearch | ready 选中项立即跳转 | empty/error 不使用旧候选跳转 |
| S15 | 等待期 Enter | Controller pendingCommit | 立即请求并在结果返回后跳转第一项 | 不重复请求、不打开旧结果 |
| S16 | 点击提交 | StockSearch option | pointer 选择后跳转 | blur 不得吞掉选择 |
| S17 | 路由唯一 | MarketOverviewPage | 调用 buildStockDetailPath | 组件不得拼接 URL |
| S18 | 默认日 K | 既有 StockDetailPage | 首请求 day/forward 回归 | 本模块不得改详情周期 |
| S19 | 无障碍完整 | StockSearch | combobox/listbox/option 关联 | 焦点不得移入不可控浮层 |
| S20 | 设计系统一致 | stock-search.css + Figma | M8 宽桌面视觉 smoke | 不新增第二套颜色或尺寸 token |

## 3. 当前代码与影响面

### 3.1 已核验事实

| 事实 | 当前证据 | 设计动作 |
|---|---|---|
| 首页编排 | wealth/src/pages/market-overview/MarketOverviewPage.tsx | 唯一挂载 StockSearch |
| 共享面包屑 | wealth/src/shared/ui/page-breadcrumb/PageBreadcrumb.tsx | 增加可选 centerSlot |
| 面包屑消费者 | MarketOverviewPage、WealthExplorationShell | 非首页不传 centerSlot |
| 路由构造 | wealth/src/app/routes/routerState.ts::buildStockDetailPath | 直接复用，不修改 |
| 详情默认周期 | StockDetailPage 的 activePeriod=day 与首请求 day/forward | 只做回归测试 |
| 认证 client | wealth/src/shared/api/wealthApiClient.ts::wealthFetch | 搜索 API client 复用 |
| 证券 ORM | src/foundation/models/core_serving/security_serving.py::Security | 查询唯一事实表 |
| Biz 路由装配 | src/app/api/v1/router.py | 只新增 import 与 include_router |
| Ops 搜索 | ReviewCenterQueryService::suggest_equities | 仅作重复能力审计，不复用 |

### 3.2 CodeGraph 结论

CodeGraph 索引根为仓库根，检查时为最新状态。已查询 PageBreadcrumb、buildStockDetailPath、get_major_indices 和 suggest_equities，并核对：

1. PageBreadcrumb 当前两个生产消费者都必须进入回归范围。
2. buildStockDetailPath 已是首页股票实体跳转的统一入口。
3. Wealth 模块路由使用 require_quote_access、get_db_session 和模块 DTO。
4. Ops suggestion 绑定 require_admin、Ops DTO 和 Review Center 语义，且缺少本需求的上市/B 股筛选，因此不得复用。

依赖方向保持：

~~~text
wealth frontend -> /api/v1/wealth/market/stock-search
src.app -> src.biz
src.biz -> src.foundation
~~~

禁止产生 src.biz -> src.ops 或 foundation -> biz 的反向依赖。

## 4. 目标调用链

~~~text
MarketOverviewPage
  -> PageBreadcrumb(centerSlot=<StockSearch />)
  -> StockSearch
  -> useStockSearchController
  -> fetchStockSearch
  -> wealthFetch
  -> GET /api/v1/wealth/market/stock-search
  -> get_stock_search
  -> StockSearchQueryService.search
  -> StockSearchPolicy.normalize
  -> StockSearchQuery.search
  -> core_serving.security_serving
  -> StockSearchResponseDto
  -> stockSearchAdapter
  -> StockSearchOption[]
  -> Enter/pointer select
  -> MarketOverviewPage.openStockDetail
  -> buildStockDetailPath
  -> StockDetailPage(day, forward)
~~~

## 5. 后端文件与符号设计

### 5.1 目标文件

~~~text
src/biz/api/wealth/market/stock_search.py
src/biz/queries/wealth/market/stock_search/__init__.py
src/biz/queries/wealth/market/stock_search/stock_search_query.py
src/biz/queries/wealth/market/stock_search/stock_search_query_service.py
src/biz/schemas/wealth/market/stock_search.py
src/biz/services/wealth/market/stock_search/__init__.py
src/biz/services/wealth/market/stock_search/stock_search_policy.py
src/app/api/v1/router.py
tests/web/test_wealth_market_stock_search_api.py
~~~

不修改 Security ORM，不新增 Alembic migration。只有第 12 节的真实 EXPLAIN 证明现有查询无法达标时，才另立索引变更范围并先检查真实 Alembic head。

### 5.2 DTO

src/biz/schemas/wealth/market/stock_search.py 定义：

~~~python
class StockSearchItemDto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tsCode: str
    name: str

class StockSearchResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keyword: str
    items: list[StockSearchItemDto] = Field(max_length=20)
~~~

约束：

1. symbol 与 cnspell 只参与匹配，不进入响应。
2. 候选行代码固定展示完整 tsCode，不从 tsCode 拆分或拼造 symbol。
3. 响应不包含内部 score、exchange、currType、listStatus 或 debug 数据。
4. 空结果固定为 HTTP 200 与 items=[]。

### 5.3 Policy

stock_search_policy.py 定义：

~~~python
DEFAULT_STOCK_SEARCH_LIMIT = 8
MAX_STOCK_SEARCH_LIMIT = 20
MAX_STOCK_SEARCH_KEYWORD_LENGTH = 32
A_SHARE_EXCHANGES = ("SSE", "SZSE", "BSE")

class StockSearchRequestError(ValueError): ...

@dataclass(frozen=True, slots=True)
class NormalizedStockSearchRequest:
    keyword: str
    escaped_prefix: str
    limit: int

class StockSearchPolicy:
    def normalize(self, *, keyword: str, limit: int) -> NormalizedStockSearchRequest: ...
~~~

normalize 固定执行：

1. keyword.strip().upper()。
2. 空值或长度大于 32 抛 StockSearchRequestError。
3. limit 必须在 1..20，否则抛 StockSearchRequestError。
4. 依次把反斜线、百分号、下划线转义，最后追加百分号构造前缀 pattern。
5. 不把中文、连字符或其它字符改写成名称查询；它们只会按普通字符进入三个批准字段，未命中即空结果。

500ms 属于前端交互合同，不进入后端 Policy。

### 5.4 Query

stock_search_query.py 定义：

~~~python
@dataclass(frozen=True, slots=True)
class StockSearchRow:
    ts_code: str
    name: str

class StockSearchQuery:
    def search(
        self,
        session: Session,
        *,
        keyword: str,
        escaped_prefix: str,
        limit: int,
    ) -> list[StockSearchRow]: ...
~~~

查询只返回 Security.ts_code、name；symbol、cnspell 和资格字段只参与 WHERE/ORDER BY。禁止 select 整行 ORM、禁止访问 raw/core 源表。

### 5.5 Query service

stock_search_query_service.py 定义：

~~~python
class StockSearchQueryService:
    def __init__(
        self,
        *,
        policy: StockSearchPolicy | None = None,
        query: StockSearchQuery | None = None,
    ) -> None: ...

    def search(
        self,
        session: Session,
        *,
        keyword: str,
        limit: int = DEFAULT_STOCK_SEARCH_LIMIT,
    ) -> StockSearchResponseDto: ...
~~~

职责顺序固定为 normalize -> query -> DTO mapping。Query service 不吞数据库异常、不回退其它数据源。

### 5.6 API 与路由

stock_search.py 定义：

~~~python
router = APIRouter(prefix="/wealth/market", tags=["wealth-market"])

@router.get("/stock-search", response_model=StockSearchResponseDto)
def get_stock_search(
    keyword: str = Query(...),
    limit: int = Query(DEFAULT_STOCK_SEARCH_LIMIT),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> StockSearchResponseDto: ...
~~~

异常映射：

1. StockSearchRequestError -> HTTP 400 / SS_REQUEST_INVALID。
2. 未捕获查询或 DTO 错误 -> HTTP 500 / SS_QUERY_FAILED，用户消息固定为“股票搜索暂不可用”，不得回传 SQL、表名或原始异常。
3. keyword 缺失或 limit 无法解析为整数时，由 FastAPI 统一返回 HTTP 422 / validation_error。
4. 认证错误沿用全局 401/403。

本模块不返回 pageStatus、moduleStatus 或 debugInfo，因此不新增状态 resolver 和模块异常 builder。SS_* 仅是 HTTP transport error，由 API 层统一映射为现有 WebAppError；这不改变异常码注册表的唯一性。

src/app/api/v1/router.py 只新增：

~~~python
from src.biz.api.wealth.market import stock_search as wealth_market_stock_search
router.include_router(wealth_market_stock_search.router)
~~~

## 6. SQL 合同

### 6.1 候选池

~~~sql
security_type = 'EQUITY'
AND list_status = 'L'
AND curr_type = 'CNY'
AND exchange IN ('SSE', 'SZSE', 'BSE')
~~~

四项身份条件缺一不可。禁止使用代码前缀识别 A/B 股，也禁止因为存在日线行情就推断上市资格。

### 6.2 匹配

对 symbol、ts_code、cnspell 使用 upper(coalesce(column, ''))。三个字段只做 escaped prefix LIKE：

~~~sql
upper(symbol) LIKE :escapedPrefix ESCAPE '\'
OR upper(ts_code) LIKE :escapedPrefix ESCAPE '\'
OR upper(coalesce(cnspell, '')) LIKE :escapedPrefix ESCAPE '\'
~~~

SQLAlchemy 必须通过 ColumnElement.like(pattern, escape="\\") 表达，不拼接 SQL 字符串。name 不进入 WHERE。

### 6.3 排序

CASE 等级固定：

1. symbol 或 ts_code 完全匹配：0。
2. symbol 前缀：1。
3. ts_code 前缀：2。
4. cnspell 前缀：3。
5. 其它：4，理论上已被 WHERE 排除。

最终顺序固定为 score ASC、Security.ts_code ASC，再 LIMIT。完全匹配的 symbol 与 tsCode 同级；同级只按 tsCode 稳定排序。

### 6.4 SQL 边界

1. 单表、单次、只读查询。
2. 不做 count、不分页、不 join、不在应用层加载全候选池后过滤。
3. 不使用 ILIKE 的隐式通配语义；用户百分号和下划线必须先转义。
4. SQLite 集成测试与 PostgreSQL 正式环境都使用 upper/case/like 基础表达式。

## 7. API 合同

请求：

~~~http
GET /api/v1/wealth/market/stock-search?keyword=PAYH&limit=8
Authorization: Bearer <token>
~~~

成功：

~~~json
{
  "keyword": "PAYH",
  "items": [
    {
      "tsCode": "000001.SZ",
      "name": "平安银行"
    }
  ]
}
~~~

核心字段清单为 keyword、items[].tsCode、items[].name。前端不得依赖未列字段。

错误：

~~~json
{
  "code": "SS_QUERY_FAILED",
  "message": "股票搜索暂不可用",
  "request_id": "<request-id-or-null>"
}
~~~

响应不引入旧 WealthApiResponse 包裹；遵循当前已实现 Wealth 模块的直接 DTO 事实。历史 api-contract-baseline 中的“建议包裹”不覆盖当前代码事实。

## 8. 前端文件与组件设计

### 8.1 目标文件

~~~text
wealth/src/features/stock-search/
  api/stockSearchApi.ts
  api/stockSearchApiTypes.ts
  api/stockSearchAdapter.ts
  api/stockSearchApi.test.ts
  model/useStockSearchController.ts
  model/useStockSearchController.test.tsx
  ui/StockSearch.tsx
  ui/StockSearch.test.tsx
  ui/stock-search.css

wealth/src/shared/ui/page-breadcrumb/
  PageBreadcrumb.tsx
  PageBreadcrumb.test.tsx
  page-breadcrumb.css

wealth/src/pages/market-overview/
  MarketOverviewPage.tsx
  MarketOverviewPage.test.tsx

wealth/src/test/
  market-overview-stock-search-real-api.test.tsx
~~~

不新增 moduleSources key。搜索是首页新增真实能力，不存在需要从 mock 切 real 的旧模块；增加 mock source 反而会制造静默回退面。

### 8.2 API client 与 adapter

stockSearchApiTypes.ts：

~~~ts
export interface StockSearchItemDto {
  tsCode: string;
  name: string;
}

export interface StockSearchResponseDto {
  keyword: string;
  items: StockSearchItemDto[];
}
~~~

stockSearchApi.ts：

~~~ts
export function buildStockSearchUrl(keyword: string, limit = 8): string;
export function fetchStockSearch(
  keyword: string,
  options?: { signal?: AbortSignal; limit?: number },
): Promise<StockSearchResponseDto>;
~~~

必须复用 wealthFetch，并按现有 API client 规则解析 code/message。禁止直接使用 fetch 绕过认证续签。

stockSearchAdapter.ts 把 DTO 映射为：

~~~ts
export interface StockSearchOption {
  tsCode: string;
  name: string;
  codeText: string;
}
~~~

codeText 直接取 tsCode；adapter 不拆 tsCode、不猜证券类型。

### 8.3 Controller 状态

~~~ts
type StockSearchState =
  | { kind: "idle" }
  | { kind: "closed"; keyword: string }
  | { kind: "debouncing"; keyword: string }
  | { kind: "loading"; keyword: string }
  | { kind: "ready"; keyword: string; options: StockSearchOption[]; activeIndex: number }
  | { kind: "empty"; keyword: string }
  | { kind: "error"; keyword: string; message: string };
~~~

closed 是控制器内部状态，视觉映射为已有 Focused/Default 输入框且菜单关闭，不新增第八个 Figma 组件变体。

useStockSearchController 内部持有：

1. inputValue。
2. state。
3. debounceTimerRef。
4. abortControllerRef。
5. requestIdRef。
6. pendingCommitRef。
7. inputRef 与 listboxId。

组件不接收 debounceMs；常量 STOCK_SEARCH_DEBOUNCE_MS=500 只定义在 controller 文件中。

### 8.4 状态转换

| 事件 | 当前状态 | 动作 | 新状态 |
|---|---|---|---|
| 输入为空 | 任意 | cancel timer/request，清 pendingCommit | idle |
| 输入非空 | 任意 | cancel timer/request，requestId+1，启动 500ms | debouncing |
| 500ms 到期 | debouncing | 发当前 keyword 请求 | loading |
| 请求有结果 | loading | 第一项 activeIndex=0 | ready |
| 请求空结果 | loading | 清 active | empty |
| 请求失败 | loading | Abort 因新输入时忽略；超时/网络/API 显示错误 | error |
| ArrowDown/Up | ready | 在 options 内循环 | ready |
| Escape/外部失焦 | 菜单打开 | 关闭菜单、保留 inputValue | closed |
| Enter | ready | 提交 active option | 导航 |
| Enter | debouncing | 取消 timer，pendingCommit=true，立即请求 | loading |
| Enter | loading | pendingCommit=true，不重复请求 | loading |
| Enter | closed | pendingCommit=true，立即请求当前 keyword | loading |
| 结果返回且 pendingCommit | loading | 提交第一项并清标记 | 导航 |
| Enter | empty/error | pendingCommit=true，重试当前 keyword | loading |
| Enter | idle | 无动作 | idle |

每次请求捕获 currentRequestId；then/catch/finally 只有在 currentRequestId 等于 requestIdRef.current 时才允许写状态。组件卸载必须清 timer 并 abort。

ready 候选超过 5 条时，ArrowUp/ArrowDown 必须调用 scrollIntoView({ block: "nearest" }) 保持 active option 可见。

请求超时固定 2000ms。由 timeout 主动 abort 时进入 Error；因新输入、清空或卸载导致的 abort 不显示 Error。

### 8.5 StockSearch 组件

~~~ts
interface StockSearchProps {
  onSelect: (tsCode: string) => void;
}
~~~

职责：

1. 渲染输入、图标、Loading/Results/Empty/Error 菜单。
2. 把输入、键盘、pointer 和失焦事件交给 controller。
3. 展示 adapter 提供的 name/codeText，不读取 API 原始对象。
4. onSelect 只上报 tsCode，不感知 router。

固定文案与输入属性：

1. aria-label：“搜索股票”。
2. placeholder：“搜索股票代码 / 拼音首字母”。
3. maxLength=32、autoComplete=off、spellCheck=false。
4. Loading：“搜索中…”。
5. Empty：“未找到匹配的当前上市 A 股”。
6. Error：“搜索暂不可用，请稍后重试”。
7. Results footer：“↑↓ 选择　Enter 打开　Esc 关闭”。

option 使用 role=option，输入保留 DOM focus。pointerdown 阶段阻止默认失焦并完成选择，随后关闭菜单。

### 8.6 PageBreadcrumb 与首页

PageBreadcrumbProps 增加：

~~~ts
centerSlot?: ReactNode;
~~~

DOM 固定三列：

~~~text
.breadcrumb | .breadcrumb-center | .breadcrumb-meta
~~~

CSS 使用 max-content minmax(0, 1fr) max-content，并显式指定 breadcrumb、breadcrumb-center、breadcrumb-meta 分别位于第 1、2、3 列。breadcrumb-center 在中列 justify-self:center，因此搜索框中心位于“左路径之后、右时间之前”的可用区域中心，与 Figma M8 的 x=557、width=360 对齐。breadcrumb-row 保持 overflow:visible，breadcrumb-center 作为浮层定位容器。

MarketOverviewPage 唯一传入：

~~~tsx
centerSlot={<StockSearch onSelect={openStockDetail} />}
~~~

WealthExplorationShell 不改调用参数，centerSlot 缺省时不产生空 DOM 占位。StockDetailPage、IndexDetailPage 和 TopMarketBar 不增加搜索实例。

## 9. 视觉与响应式合同

| 项 | 合同 |
|---|---|
| 输入尺寸 | 360 × 36px |
| 菜单宽度 | 360px |
| Results 总尺寸 | 360 × 285px；最多 5 行可见，其余候选内部滚动 |
| 展开方向 | 输入框下方 6px，绝对定位，不推开首页内容 |
| 背景 | --cs-color-bg-panel-soft / --cs-color-surface-panel |
| 默认边框 | --cs-color-border-default |
| 聚焦边框 | --cs-color-border-strong |
| 主文字 | --cs-color-text-primary |
| 次文字 | --cs-color-text-secondary |
| 弱文字 | --cs-color-text-muted |
| 品牌强调 | --cs-color-brand |
| 系统错误 | --cs-color-danger-system |
| 代码字体 | --cs-font-family-number |
| 面板阴影 | --cs-shadow-panel |

禁止使用 market-up/market-down 表达搜索状态。默认、Hover、Focused、Loading、Results、Empty、Error 七态分别对齐 Figma 组件集 1262:155；候选 Default/Hover/Selected 对齐 1261:90。

当前页面已有 min-width=1460 的宽桌面合同，本模块不新增移动端折叠、隐藏或换行规则。菜单必须有独立 z-index，且不被面包屑或首个模块裁切。

## 10. 可访问性合同

1. input：role=combobox、aria-autocomplete=list、aria-expanded、aria-controls。
2. ready 时设置 aria-activedescendant；其它状态移除。
3. menu：role=listbox；候选：role=option 与 aria-selected。
4. Loading/Empty/Error 使用 aria-live=polite 的单一状态区，不逐字播报输入。
5. 键盘只处理 ArrowDown、ArrowUp、Enter、Escape，不拦截 Tab。
6. Tab 或点击外部进入 closed 并保留输入；重新聚焦不自动发请求，继续输入重新计时，按 Enter 立即查询。
7. 可点击候选必须同时支持 pointer 与键盘，不以颜色作为唯一选中信号。

## 11. 测试设计

### 11.1 后端真实 API

tests/web/test_wealth_market_stock_search_api.py 必须创建 Security 表并经 TestClient 访问真实路由，不 mock Query 或 QueryService。

| Test ID | 数据/动作 | 核心断言 |
|---|---|---|
| B01 | keyword=600 | keyword 归一化、字段完整、前缀排序 |
| B02 | keyword=600000.sh | tsCode 完全匹配第一 |
| B03 | keyword=payh | 平安银行由 cnspell 命中 |
| B04 | name 仅中文命中 | items=[] |
| B05 | symbol 中间子串 | items=[] |
| B06 | CNY A 股与 USD/HKD B 股同关键词 | 只返回 CNY |
| B07 | L/D/P 三状态 | 只返回 L |
| B08 | EQUITY/INDEX/ETF | 只返回 EQUITY |
| B09 | SSE/SZSE/BSE/其它 | 只返回前三者 |
| B10 | 同 rank 多行 | tsCode ASC 稳定 |
| B11 | 百分号、下划线、反斜线 | 不产生通配扩张 |
| B12 | limit=1/8/20/21 | 截断正确，21 为 SS_REQUEST_INVALID |
| B13 | 空白、33 位 keyword | SS_REQUEST_INVALID |
| B14 | 无 quote access | 统一 401/403 |
| B15 | Query 抛异常 | 500 SS_QUERY_FAILED，不泄露原始错误 |
| B16 | keyword 缺失、limit 非整数 | 422 validation_error |

### 11.2 前端单元测试

1. stockSearchApi：URL 编码、limit、wealthFetch 错误 code/message、AbortSignal。
2. adapter：字段一一映射且不推导新字段。
3. controller：499/500ms、连续输入、timeout、主动取消、乱序响应、pendingCommit。
4. StockSearch：七态 DOM、三态候选、键盘循环、Esc、Tab、pointerdown、ARIA。
5. PageBreadcrumb：不传 centerSlot 时旧 DOM 行为不变；传入时中间槽只出现一次。
6. MarketOverviewPage：onSelect 调用统一路由；不自行拼 path。

### 11.3 真实 API 展示 smoke

wealth/src/test/market-overview-stock-search-real-api.test.tsx 必须：

1. 渲染 MarketOverviewPage，而不是孤立 mock 页面。
2. 让 stock search 走真实 stockSearchApi + wealthFetch 调用链。
3. 只 stub HTTP 响应，不调用任何 mock adapter。
4. 输入 payh，推进 500ms，断言请求 URL、Loading、平安银行和 000001.SZ。
5. 按 Enter 或 pointer 选择后断言 location 为 /wealth/market/stock/000001.SZ。
6. 同文件断言首页有搜索、WealthExplorationShell 与详情页无搜索。

### 11.4 既有回归

1. PageBreadcrumb.test.tsx。
2. MarketOverviewPage.test.tsx。
3. routerState.test.ts。
4. StockDetailPage.test.tsx 中 day/forward 首请求。
5. tests/architecture/test_subsystem_dependency_matrix.py。

## 12. 性能与数据库门禁

### 12.1 预算

1. API P95 <= 200ms。
2. API P99 <= 350ms。
3. payload <= 8KiB。
4. 前端请求超时 2000ms。
5. 单次最多 20 行，默认 8 行。

### 12.2 编码前只读验证

在正式同类 PostgreSQL 环境对冻结查询执行：

1. EXPLAIN (ANALYZE, BUFFERS)。
2. 数字代码、完整 tsCode、常见拼音首字母、无结果四类样本。
3. 各样本至少 30 次，记录 P50/P95/P99、返回行数和 payload。
4. 核对候选池总数及 cnspell 非空覆盖率；只用于判断搜索可用性，不改变候选池合同。

若预算不达标，停止实现验收。不得在本轮直接加缓存或迁移；先确认真实瓶颈，再另立功能索引方案。

### 12.3 实测结果（2026-09-02）

1. 正式数据库候选池 5,553 只，`cnspell` 非空 5,553 只。
2. `600`、`600000.SH`、`PAYH`、`ZZZZ` 各 30 次：P95 为 27.423ms、157.893ms、98.940ms、26.203ms；P99 为 103.050ms、217.454ms、175.092ms、102.650ms。
3. 四类样本均满足 P95/P99 预算；默认 8 条代表性 payload 为 439B。
4. `EXPLAIN (ANALYZE, BUFFERS)` 单次约 6.3-7.5ms。当前表约 5,894 行、约 5.9MiB，顺序扫描已满足预算，不新增索引或 Alembic migration。

## 13. 通用清单逐项映射

| 通用项 | 结论 | 本模块落点 | 验证 |
|---|---|---|---|
| 2.1 交付事实链 | 适用 | Figma + implementation design + 本 LLD | 文档链接和节点核对 |
| 2.2 后端事实归一 | 适用 | Security + Wealth DTO | B01-B10 |
| 2.3 状态机 | 适用 | 七种内部状态；无时间语义，不设 delayed/partial | 前端状态测试 |
| 2.4 显示/数据语义 | 不适用行情方向 | 仅名称与代码，不展示涨跌 | DTO 字段静态检查 |
| 2.5 行为过程测试 | 适用 | debounce/loading/ready/error/navigation | controller + UI |
| 2.6 文档实现同步 | 适用 | 两份方案、baseline、registry | 提交前 diff 对账 |
| 2.7 渐进替换 | 部分适用 | 新能力无 mock/source key；回滚粒度仍为 stock-search | 无 mock/ops fallback 静态检查 |
| 2.8 契约先行 | 适用 | 第 7 节 DTO | B01 + smoke |
| 2.9 图表坐标 | 不适用 | 本模块无图表 | 文件范围检查 |
| 2.10 统计/传输边界 | 适用 | SQL 过滤排序 LIMIT，无应用层全量池 | EXPLAIN + Query 测试 |
| 2.11 配置语义 | 不适用 | 本模块不新增配置 | env/Settings/config diff 为零 |
| 2.12 映射矩阵 | 适用 | 本节 | 文档检查 |
| 2.13 例外白名单 | 适用 | 第 14 节明确无例外 | 文档检查 |
| 2.14 图表参数优先级 | 不适用 | 无图表 | 文件范围检查 |
| 2.15 双图对齐 | 不适用 | 无图表 | 文件范围检查 |
| 2.16 卡片单行 | 不适用 | 无指标卡 | Figma 节点检查 |
| 2.17 核心测试 | 适用 | B01-B16 + real API smoke | 指定命令通过 |
| 2.18 八原则 | 适用 | 下表 | 文档与测试映射 |

八原则：

| 原则 | 落点 | 验证 |
|---|---|---|
| 事实源单一 | Security | B06-B09 |
| 契约先行 | StockSearchResponseDto | B01 + TS type |
| 配置一致 | 无配置项，常量只在 Policy/Controller 各自职责内 | diff 检查 |
| 默认显式 | 500ms、limit=8、首项选中 | fake timer + B12 |
| 排序筛选确定 | 四项资格 + CASE + tsCode | B05-B11 |
| 性能预算前置 | 第 12 节 | EXPLAIN 与分位数 |
| 异常标准化 | SS_REQUEST_INVALID、SS_QUERY_FAILED | B12-B16 |
| 用户可见结果 | 名称、代码、状态、跳转、日 K | real API smoke |

## 14. 模块例外白名单

无例外白名单。

以下“不适用”是业务形态不涉及，不是偏离规则：

1. 搜索不展示行情方向和图表。
2. 搜索不替换既有 mock 模块，因此不新增 moduleSources key。
3. 搜索无日期、新鲜度和 delayed/partial 语义。
4. 搜索无运营配置项。

## 15. 实施切片

| Slice | 范围 | 完成证据 |
|---|---|---|
| D0 | Figma、implementation design、LLD、异常码 | 已完成 |
| D1 | 后端 DTO/Policy/Query/Service/API/router | 已完成；B01-B16 通过，无 Ops import |
| D2 | 前端 API/adapter/controller/组件 | 已完成；单元测试通过，七态与 ARIA 完整 |
| D3 | PageBreadcrumb 可选槽与首页唯一挂载 | 已完成；首页与其它消费者回归通过 |
| D4 | 真实 API 展示、性能、视觉与详情日 K 回归 | 已完成；第 12 节、浏览器 smoke 和全量命令通过 |

D1-D4 必须顺序完成。任一门禁失败即停在当前 Slice，不进入下一步。

## 16. 验证命令

~~~bash
pytest -q tests/web/test_wealth_market_stock_search_api.py
pytest -q tests/architecture/test_subsystem_dependency_matrix.py
cd wealth && npm run typecheck
cd wealth && npm run test
cd wealth && npm run build
python3 scripts/check_docs_integrity.py
git diff --check
~~~

页面交付还必须执行真实后端 API 的浏览器 smoke，并与 Figma M8、组件集 1262:155、交互板 1267:81 对照。

## 17. 回滚边界

回滚单元：

1. 移除 stock-search Biz router 与模块目录。
2. 移除 frontend stock-search feature。
3. 移除 MarketOverviewPage 的 centerSlot 实例。
4. 本版本只有首页使用 centerSlot，因此同轮撤销 PageBreadcrumb 可选槽。

回滚不修改 Security、股票详情路由、StockDetailPage、其它首页模块或 moduleSources。

## 18. 完成标准

只有同时满足以下条件才可认定代码交付完成：

1. S01-S20 都有对应代码和测试证据。
2. B01-B16 全部通过。
3. 真实 API 展示 smoke 通过。
4. PageBreadcrumb 两个现有消费者无回归。
5. 详情首个 K 线请求仍为 day/forward。
6. P95/P99/payload 达标。
7. 浏览器视觉与 Figma M8 无结构漂移。
8. 无 Ops import、无 mock fallback、无新增配置或迁移。

## 19. 待拍板项

无。

实现中若出现必须改变候选池、搜索字段、API 路径、500ms、组件挂载范围、Figma 尺寸或详情默认周期的情况，属于方案偏离，必须先停止并重新提交差异，不得现场发挥。

## 20. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-09-02 | 冻结代码符号、SQL、前端状态机、18 项通用门禁、测试与回滚；无待拍板项 | Codex |
| v1.1 | 2026-09-02 | 完成 D1-D4 开发、全量回归、正式数据库只读性能门禁与本地真实页面 smoke；待用户部署验收 | Codex |
