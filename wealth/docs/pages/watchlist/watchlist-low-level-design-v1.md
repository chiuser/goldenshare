# 财势乾坤｜我的自选低层设计 v1（LLD）

> 状态：首版已提交 `d143dec4`；第 18 节五项展示修正开发与自测完成；本次未提交、未部署
>
> 日期：2026-09-03
>
> 产品与交互基准：[我的自选产品与交互基准 v1](./watchlist-benchmark-requirement-v1.md)
>
> 上层方案：[我的自选技术实施方案 v1](./watchlist-implementation-design-v1.md)

## 0. Figma 实现基准

第 18 节为用户最新明确修正，优先于以下首版画板的对应细节：按钮/状态格居中、最新价跟随涨跌色、PE/PB 拆列、资金显示单位为千万。本轮不修改 Figma；其余布局、搜索、增删、滚动和详情交互继续沿用首版基准。

编码时以以下节点作为视觉与状态事实，不允许只凭本文文字自行发挥：

1. 主列表：[`1277:82`](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1277-82)。
2. 状态与交互交付板：[`1282:754`](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1282-754)。
3. 可点击原型起点：[`1293:289`](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1293-289)。
4. 添加初始/结果/成功：[`1290:185`](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1290-185)、[`1282:82`](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1282-82)、[`1293:625`](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1293-625)。
5. 删除确认/完成：[`1282:418`](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1282-418)、[`1291:237`](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1291-237)。
6. 日 K 去向：[`1293:1004`](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1293-1004)。

Figma 自检结果：无缺失字体；左侧代码/名称固定区为 `260px`，中部行情与所属板块区为 `1194px` 可视区承载 `1302px` 内容的真实横向溢出结构，右侧仅操作固定区为 `110px`；所属板块位于横向内容末列并随内容滑动；所有表头与对应单元格均使用相同左边界和左对齐；固定搜索结果区已覆盖空、加载、结果、无结果与错误状态；原型共登记 16 个交互连接。实现验收必须同时对照画板和第 10 节测试，不得把示意图降级为自由发挥参考。

## 1. LLD 结论

本文将已拍板需求细化到代码符号、持久化约束、API DTO、查询顺序、组件状态、测试和编码门禁。

硬约束：

1. 添加弹窗上方搜索、下方固定结果区；初始结果正文为空。
2. 搜索 hint 固定为“输入名称首字母或代码”。
3. 结果项只有代码、名称、状态三列；未添加显示 `+`，已添加显示“已添加”。
4. 用户—股票唯一约束是重复添加幂等的最终防线。
5. 删除必须经过页面正中的轻量确认弹窗，不锚定行内按钮。
6. 列表纵向滚动至最后一项，允许横向滚动查看全部字段。
7. 行情使用同一最近可用交易日，不做盘中实时混搭。
8. 新添加股票放在列表最后。
9. 股票详情页“+自选”接入相同幂等添加能力。
10. 只允许当前上市 A 股进入新增候选池。
11. 股票代码、股票名称为独立列，顺序固定为代码在前、名称在后。
12. 表头承担单位；成交量以万手、资金净流入以千万、涨跌幅与换手率以百分比展示，单元格不重复单位。
13. 市盈率（PE TTM）与市净率（PB）分成两个独立列，每格只有单项数值，不显示 `PE xx` 或 `PB xx`，禁止估值组合列。
14. 量比和换手率各自成列，不存在“活跃度”组合列。
15. 所属板块是横向滑动区的最后一列，业务顺序位于操作左侧但不得冻结；只有操作列固定在右侧。
16. 数据列表头和对应单元格内容统一左对齐；所属板块标签文字左对齐且在每行内垂直居中。操作列、搜索状态列和按钮内容按用户最新要求居中。
17. 最新价与涨跌幅使用相同 `quote.direction` 行情色；缺失价格显示中性的 `--`。

## 2. 开发约束映射

| 需求硬口径 | 后端落点 | 前端落点 | 必须测试 |
|---|---|---|---|
| 用户私有列表 | 所有 Query/Command 必传 `user_id` | 不传 `userId` | 双用户隔离 |
| 添加幂等 | 唯一约束 + nested transaction | 单行 pending | 重复/并发 PUT |
| 新增置尾 | `id ASC`、`afterId` | 只 append，不重排 | 添加前后顺序 |
| 当前上市 A 股 | 复用 StockSearchPolicy/Query 四项条件 | 只展示服务端候选 | B 股/退市/非股票负例 |
| 同日行情 | 单一 `observedTradeDate` | 展示服务端日期 | 跨日数据不得补入 |
| 分页日期变化 | 沿用当前列表 DTO | 丢弃不同日期批次，整表重载并回到顶部 | 分页/尾部补读日期变化、null→日期 |
| 固定搜索区 | 有界 Top N | 固定 body 高度 | 初始/ready/empty/error 截图与 DOM |
| 三列状态 | `AVAILABLE/ADDED` | 代码/名称/状态 | 已添加不能重复提交 |
| 删除确认 | DELETE 幂等 | centered dialog | 取消、确认、失败、非 anchor 定位 |
| 横向滚动 | DTO 不删列 | `overflow-x:auto` | scrollWidth > clientWidth |
| 列冻结边界 | 无后端影响 | 仅代码/名称 sticky left、操作 sticky right；所属板块不 sticky | computed style + 横向滚动截图 |
| 列内对齐 | 无后端影响 | 数据列统一左对齐；操作/搜索状态列与按钮内容居中 | DOM 左边界/中心断言 + 截图 |
| 原子列与单位 | 数值字段保持原始单位 | 表头换算单位、单元格纯数值 | 列顺序、换算、无旧组合列 |
| 详情页联动 | membership + PUT | `+自选/已自选` | 状态加载与添加 |
| 详情默认日 K | 不改既有 Kline contract | 复用 buildStockDetailPath | 首请求 `day + forward` |

## 3. 数据模型与迁移

### 3.1 ORM

新增 `src/biz/models/wealth/watchlist_item.py`：

```python
class WealthWatchlistItem(TimestampMixin, Base):
    __tablename__ = "wealth_watchlist_item"
    __table_args__ = (
        UniqueConstraint("user_id", "ts_code", name="uq_wealth_watchlist_item_user_stock"),
        Index("idx_wealth_watchlist_item_user_id_id", "user_id", "id"),
        {"schema": "app"},
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("app.app_user.id", ondelete="CASCADE"),
        nullable=False,
    )
    ts_code: Mapped[str] = mapped_column(String(16), nullable=False)
```

`created_at/updated_at` 由 `TimestampMixin` 提供。模型不定义关系加载和业务方法。

### 3.2 注册

`src/app/model_registry.py` 的 `MODEL_MODULES` 新增：

```python
"src.biz.models.wealth.watchlist_item",
```

只做 ORM metadata 注册，不把自选规则写入组合根。

### 3.3 Alembic

编码前执行：

```bash
alembic heads
```

方案审计时 head 为 `20260831_000168`，但不得据此跳过开工时复查。迁移只允许：

1. 创建 `app.wealth_watchlist_item`。
2. 创建唯一索引和列表索引。
3. 创建到 `app.app_user.id` 的级联外键。
4. 不插入默认自选，不修改任何行情表、账户字段或配置表。

模型测试必须证明唯一约束和用户删除级联；迁移 downgrade 只删除本表及其索引，不删除 `app` schema。

## 4. 后端代码级设计

### 4.1 Policy

文件：`src/biz/services/wealth/market/watchlist/watchlist_policy.py`

符号：

```python
DEFAULT_WATCHLIST_PAGE_SIZE = 100
MAX_WATCHLIST_PAGE_SIZE = 200

class WatchlistRequestError(ValueError): ...

class WatchlistPolicy:
    def normalize_ts_code(self, ts_code: str) -> str: ...
    def normalize_page(self, *, limit: int, after_id: int | None) -> WatchlistPageRequest: ...
```

规则：

1. `tsCode` trim + upper，长度 `1..16`。
2. 不通过代码前缀猜测市场或 A/B 股资格。
3. A 股资格必须查询 `Security` 并满足既有四项合同。
4. 本模块不复制 `A_SHARE_EXCHANGES` 常量，直接复用 `stock_search` 模块公开 Policy 常量。

### 4.2 Repository / Query

文件：`src/biz/queries/wealth/market/watchlist/watchlist_query.py`

符号：

```python
class WatchlistQuery:
    def count(self, session, *, user_id: int) -> int: ...
    def contains(self, session, *, user_id: int, ts_code: str) -> bool: ...
    def list_memberships(self, session, *, user_id: int, limit: int, after_id: int | None) -> list[WatchlistMembershipRow]: ...
    def load_snapshot(self, session, *, memberships, observed_trade_date) -> list[WatchlistSnapshotRow]: ...
    def resolve_observed_trade_date(self, session, *, expected_trade_date: date) -> date | None: ...
    def load_added_codes(self, session, *, user_id: int, ts_codes: Sequence[str]) -> set[str]: ...
    def load_eligible_security(self, session, *, ts_code: str) -> EligibleSecurityRow | None: ...
```

`list_memberships` 查询：

```sql
SELECT id, ts_code, created_at
FROM app.wealth_watchlist_item
WHERE user_id = :user_id
  AND (:after_id IS NULL OR id > :after_id)
ORDER BY id ASC
LIMIT :limit_plus_one
```

取 `limit + 1` 判断 `nextCursor`，响应只返回 `limit` 行。

`load_snapshot` 必须一次有界查询完成，禁止 N+1：

```sql
SELECT
  w.id,
  w.ts_code,
  w.created_at,
  s.name,
  s.industry,
  s.list_status,
  d.close,
  d.pct_chg,
  d.vol,
  b.pe_ttm,
  b.pb,
  b.volume_ratio,
  b.turnover_rate,
  m.net_mf_amount
FROM bounded_memberships w
LEFT JOIN core_serving.security_serving s
  ON s.ts_code = w.ts_code
LEFT JOIN core_serving.equity_daily_bar d
  ON d.ts_code = w.ts_code AND d.trade_date = :observed_trade_date
LEFT JOIN core_serving.equity_daily_basic b
  ON b.ts_code = w.ts_code AND b.trade_date = :observed_trade_date
LEFT JOIN core_serving.equity_moneyflow m
  ON m.ts_code = w.ts_code AND m.trade_date = :observed_trade_date
ORDER BY w.id ASC
```

实现可用 SQLAlchemy CTE 或以已取出的有界 `ts_code` 集合做单次 `IN` 查询后按 membership id 组装；无论采用哪一种，都必须保持固定两次以内数据查询且最终按 `id ASC`。

### 4.3 QueryService

文件：`src/biz/queries/wealth/market/watchlist/watchlist_query_service.py`

符号：

```python
class WatchlistQueryService:
    def get_page(..., user_id, requested_trade_date, limit, after_id) -> WatchlistPageResponseDto: ...
    def get_summary(..., user_id) -> WatchlistSummaryResponseDto: ...
    def get_membership(..., user_id, ts_code) -> WatchlistMembershipResponseDto: ...
    def search(..., user_id, keyword, limit) -> WatchlistSearchResponseDto: ...
```

`get_page` 顺序固定：

1. Policy 校验分页。
2. `MarketPageContextQuery.resolve_context(market="CN_A", ...)`。
3. `count(user_id)`。
4. total=0 时返回 EMPTY，不查询行情表。
5. `list_memberships(user_id, limit, afterId)`。
6. `resolve_observed_trade_date(expectedTradeDate)`。
7. 对本批 membership 执行同日 snapshot 查询。
8. FieldMapper 映射 DTO、missingFields 和结构化方向。
9. 归并 page dataStatus。

`search` 顺序固定：

1. 使用现有 `StockSearchPolicy.normalize`。
2. 使用现有 `StockSearchQuery.search` 得到有界候选。
3. 一次查询当前用户在候选中的已添加代码。
4. 映射 `AVAILABLE/ADDED`；不修改首页 stock-search DTO。

### 4.4 FieldMapper

文件：`src/biz/services/wealth/market/watchlist/watchlist_field_mapper.py`

符号：

```python
def resolve_direction(value: Decimal | None) -> Literal["UP", "DOWN", "FLAT", "UNKNOWN"]: ...
def build_watchlist_item(row, *, observed_trade_date) -> WatchlistItemDto: ...
def build_watchlist_status(...) -> WatchlistDataStatusDto: ...
```

要求：

1. `changePct` 和 `netAmount` 分别产出独立方向字段。
2. `None` 为 `UNKNOWN`，不得按 0 处理。
3. `missingFields` 使用冻结 DTO 字段键，不输出 SQL 列名。
4. 不格式化为“亿/万”文案，不在后端加颜色 class。

### 4.5 CommandService

文件：`src/biz/services/wealth/market/watchlist/watchlist_command_service.py`

符号：

```python
class WatchlistCommandService:
    def add(self, session, *, user_id: int, ts_code: str) -> WatchlistMutationResponseDto: ...
    def remove(self, session, *, user_id: int, ts_code: str) -> WatchlistMutationResponseDto: ...
```

`add`：

1. 归一化 code。
2. `load_eligible_security` 复核资格，不合格抛 `WatchlistStockNotEligibleError`。
3. 在 `session.begin_nested()` 中 `add + flush`。
4. 唯一冲突只回滚 savepoint，随后确认关系存在并返回 `created=false`。
5. 其它异常回滚事务并上抛。
6. 成功后 `session.commit()`，再查询 totalCount。

不得使用“先查不存在再插入”作为唯一幂等保证；它不能抵御并发。

`remove`：

1. 执行 `DELETE WHERE user_id=:user_id AND ts_code=:ts_code`。
2. `rowcount > 0` 为 `removed=true`，否则 false。
3. commit 后返回总数。

### 4.6 API Router

文件：`src/biz/api/wealth/market/watchlist.py`

所有 handler 参数必须包含：

```python
user: AuthenticatedUser = Depends(require_authenticated)
session: Session = Depends(get_db_session)
```

路由：

```text
GET    /wealth/market/watchlist
GET    /wealth/market/watchlist/summary
GET    /wealth/market/watchlist/search
GET    /wealth/market/watchlist/items/{ts_code}
PUT    /wealth/market/watchlist/items/{ts_code}
DELETE /wealth/market/watchlist/items/{ts_code}
```

具体路径必须把 `/summary`、`/search` 注册在 `/{ts_code}` 之前，避免动态路径吞掉固定段。

异常映射：

| 异常 | HTTP | code |
|---|---:|---|
| 参数非法 | 400 | `WL_REQUEST_INVALID` |
| 股票不符合添加资格 | 422 | `WL_STOCK_NOT_ELIGIBLE` |
| 只读查询失败 | 500 | `WL_QUERY_FAILED` |
| 写入失败 | 500 | `WL_WRITE_FAILED` |
| 未登录/失效登录 | 401 | 复用认证层 |

API 层记录异常但不返回 SQL、表名或用户 id。

## 5. DTO 冻结

文件：`src/biz/schemas/wealth/market/watchlist.py`，所有模型 `extra="forbid"`。

### 5.1 列表响应

```json
{
  "pageContext": {
    "market": "CN_A",
    "tradeDate": "2026-09-03",
    "prevTradeDate": "2026-09-02",
    "isTradingDay": true,
    "sessionStatus": "CLOSED",
    "timezone": "Asia/Shanghai",
    "generatedAt": "2026-09-03T20:10:00+08:00",
    "source": "default"
  },
  "dataStatus": {
    "status": "READY",
    "expectedTradeDate": "2026-09-03",
    "observedTradeDate": "2026-09-03"
  },
  "items": [
    {
      "id": 11,
      "addedAt": "2026-09-01T10:00:00+08:00",
      "stock": {
        "tsCode": "000001.SZ",
        "name": "平安银行",
        "industry": "银行",
        "listStatus": "L"
      },
      "quote": {
        "price": 12.34,
        "changePct": 1.73,
        "direction": "UP",
        "vol": 1234567.0
      },
      "valuation": {"peTtm": 5.62, "pb": 0.71},
      "activity": {"volumeRatio": 1.08, "turnoverRate": 0.92},
      "moneyFlow": {"netAmount": 2189.4, "direction": "UP"},
      "missingFields": []
    }
  ],
  "totalCount": 18,
  "nextCursor": 110
}
```

冻结类型：

1. `status`: `READY | DELAYED | PARTIAL | EMPTY | ERROR`。
2. `direction`: `UP | DOWN | FLAT | UNKNOWN`。
3. 所有行情数值可空；身份的 `tsCode/name` 不可空，若 security 缺失则 name 固定回退 `--` 并进入 PARTIAL。
4. `nextCursor=null` 表示最后一批。
5. `id` 只用于游标和稳定 React key，不作为可编辑业务编号。

### 5.2 搜索响应

```json
{
  "keyword": "PAYH",
  "items": [
    {"tsCode": "000001.SZ", "name": "平安银行", "status": "AVAILABLE"}
  ]
}
```

### 5.3 成员与写响应

```json
{"tsCode": "000001.SZ", "isAdded": true}
```

```json
{
  "tsCode": "000001.SZ",
  "isAdded": true,
  "created": false,
  "removed": false,
  "totalCount": 18
}
```

PUT 响应只使用 `created`，DELETE 响应只使用 `removed`；Pydantic 可分别定义 Add/Remove DTO，避免同一对象出现无意义字段。

## 6. 股票详情能力合同调整

### 6.1 后端

`StockDetailCapabilitiesDto` 删除：

```text
supportsUserActions
unsupportedActions
```

新增：

```python
class StockDetailUserActionsDto(BaseModel):
    watchlist: bool = True
    alert: bool = False
    tradePlan: bool = False
    diagnosis: bool = False

class StockDetailCapabilitiesDto(BaseModel):
    ...
    userActions: StockDetailUserActionsDto
```

必须同步更新：

1. `src/biz/schemas/wealth/market/stock_detail.py`
2. `StockDetailQueryService.build_page_init`
3. `wealth/src/features/stock-detail/api/stockDetailApiTypes.ts`
4. 后端 stock-detail API 测试 fixtures
5. `StockDetailPage.test.tsx`
6. `stockDetailViewModelAdapter.test.ts`

不得保留旧字段别名或兼容解析。

### 6.2 前端

`StockInfoRailProps` 调整为：

```ts
interface StockInfoRailProps {
  viewModel: StockDetailViewModel;
  watchlistState: "loading" | "available" | "added" | "error";
  onAddToWatchlist: () => void;
  onAction: (message: string) => void;
}
```

按钮：

1. loading：`处理中`，disabled。
2. available：`+自选`，点击 `onAddToWatchlist`。
3. added：`已自选`，disabled。
4. error：保留 `+自选`，再次点击可重试；同时使用 toast 说明上次失败。
5. “+提醒”和“+交易计划”仍调用既有 placeholder，不受影响。

## 7. 前端代码级设计

### 7.1 路由

`routerState.ts` 新增：

```ts
export const WEALTH_WATCHLIST_PATH = "/wealth/market/watchlist";

export function buildWatchlistPath(): string {
  return WEALTH_WATCHLIST_PATH;
}

export function isWatchlistPath(pathname: string): boolean {
  return pathname === WEALTH_WATCHLIST_PATH || pathname === "/market/watchlist";
}
```

`WealthRouter` 在股票/指数详情分支之前匹配 watchlist，渲染：

```tsx
<WatchlistPage search={location.search} />
```

未知路径 fallback 行为不变。

### 7.2 首页入口

`MarketShortcutBarProps`：

```ts
interface MarketShortcutBarProps {
  watchlistCount: number | null;
  onAction: (message: string) => void;
  onNavigate: (path: string) => void;
}
```

watchlist entry：

1. path 改为 `WEALTH_WATCHLIST_PATH`。
2. badge 为真实 count；请求中/失败时显示 `--`，不回退固定 `18`。
3. description 改为本期真实能力，不出现未实现的“分组与提醒”。
4. `onNavigate` 对 watchlist 使用真实导航，其它占位卡片行为保持不变。

`MarketOverviewPage` 使用 `fetchWatchlistSummary`，错误只影响 badge，不阻塞首页其它模块。

### 7.3 API Client

文件 `wealth/src/features/watchlist/api/watchlistApi.ts` 导出：

```ts
fetchWatchlistPage(params, options)
fetchWatchlistSummary(options)
searchWatchlistCandidates(params, options)
fetchWatchlistMembership(tsCode, options)
addWatchlistItem(tsCode, options)
removeWatchlistItem(tsCode, options)
```

全部调用 `wealthFetch`。GET 构造 `URLSearchParams`；路径股票代码使用 `encodeURIComponent(trim().toUpperCase())`。

### 7.4 Page Controller

`useWatchlistController` 状态：

```ts
interface WatchlistControllerState {
  viewState: "loading" | "ready" | "empty" | "error";
  dataStatus: "READY" | "DELAYED" | "PARTIAL" | "EMPTY" | "ERROR" | null;
  items: WatchlistRowViewModel[];
  totalCount: number;
  nextCursor: number | null;
  isLoadingMore: boolean;
  removingTsCode: string | null;
  errorMessage: string | null;
}
```

方法：

```ts
loadInitial()
loadMore()
appendAddedItem(tsCode)
requestRemove(row)
confirmRemove()
cancelRemove()
retry()
```

追加规则：

1. PUT 成功后若 item 已在本地，不重复追加。
2. 若全部页已加载，以已读最大 id（独立于删除后的行数组保留）做有界尾部补读；空列表请求首批。沿用现有列表 DTO，不向 PUT 响应添加完整行情 item。
3. 若尚有未加载页，不把新行插到当前批末尾冒充全局末尾；只更新 count 并提示“已添加到列表末尾”，滚动加载后按服务端 id 顺序出现。
4. Controller 不按行情值重排。
5. 分页或尾部补读的 `observedTradeDate` 与当前列表不同（包含 null 与日期互变）时，丢弃该响应，取消旧批次请求并重新加载首批；滚动位置回到顶部。新批次不得与旧日期行合并；重载失败进入可重试 error，不伪装完成。

### 7.5 添加弹窗 Controller

`useWatchlistSearchController` 状态：

```ts
type SearchState = "idle" | "debouncing" | "loading" | "ready" | "empty" | "error";
```

状态转换：

```text
open -> idle(items=[])
keyword empty -> idle(items=[])
keyword changed -> debouncing(500ms)
timer -> loading
success(items>0) -> ready
success(items=0) -> empty
failure -> error
click + -> item pending -> PUT -> item ADDED
close -> abort + reset idle
```

`AddWatchlistDialog` DOM：

```tsx
<div role="dialog" aria-modal="true" aria-labelledby="watchlist-add-title">
  <input placeholder="输入名称首字母或代码" />
  <div className="watchlist-search-results">
    <div role="row">代码 / 名称 / 状态</div>
    <div role="rowgroup">固定高度结果正文</div>
  </div>
</div>
```

初始 `idle` 的 rowgroup 不渲染提示文案或推荐行；列头仍保持可见。

每个 `AVAILABLE` 行的 `+` 必须是有可读 `aria-label="添加 {name} {tsCode}"` 的真实 button。“已添加”使用文本，不伪装可点击按钮。

### 7.6 表格和滚动

`WatchlistTable`：

1. 使用语义 table；表头 sticky top。
2. 外层 `.watchlist-table-scroll` 同时提供 `overflow-x:auto` 和纵向 viewport。
3. 表格最小宽度由页面 CSS 自定义属性集中声明，不把数值散落到单元格。
4. `.stock-code-column`、`.stock-name-column` 依次 sticky left；`.action-column` sticky right；`.sector-column` 不设置 sticky，作为横向滚动内容的最后一列；三个固定列背景跟随 row hover。
5. 数据列 `th`、`td` 统一左对齐，表头和表体通过同一列宽与左侧内边距保证内容左边界一致；数值列使用 `.num`、`font-variant-numeric: tabular-nums`。操作列及搜索状态列居中，按钮内容双轴居中。
6. 正/负/零/缺失分别使用结构化 direction 对应 `.up/.down/.flat` 和中性占位。最新价复用涨跌幅的 direction；价格自身缺失时不渲染带涨跌色的 `--`。
7. 底部 sentinel 进入视区且 `nextCursor != null` 时调用 `loadMore()`；请求中不重复触发。
8. 最后一批加载后移除 sentinel，最后一行可以完整滚入视区。
9. 可见列严格按以下顺序渲染：`tsCode`、`name`、`price`、`changePct`、`vol`、`peTtm`、`pb`、`volumeRatio`、`turnoverRate`、`netAmount`、`industry`、操作。
10. 表头文案严格为：股票代码、股票名称、最新价（元）、涨跌幅（%）、成交量（万手）、市盈率（PE TTM）、市净率（PB）、量比、换手率（%）、资金净流入（千万）、所属板块、操作，共 12 列。
11. `vol` 源单位手，显示值为 `vol / 10000`；`netAmount` 源单位万元，显示值为 `netAmount / 1000`；表体不追加“万手”“千万”或 `%`。
12. `peTtm` 与 `pb` 各占一个独立单元格，只显示单行格式化数值；删除旧 `valuation-column` 与两行布局，不保留兼容组合列。
13. `.sector-column` 内标签使用 flex 垂直居中，标签文字保持左对齐；不得使用水平居中覆盖整列左对齐合同。

### 7.7 删除确认弹窗

`RemoveWatchlistDialog` props：

```ts
interface RemoveWatchlistDialogProps {
  stock: { tsCode: string; name: string };
  open: boolean;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}
```

弹窗挂载在页面级 overlay 中，使用 viewport 居中布局，不接收 anchor 坐标。行内移除按钮必须 stopPropagation；弹窗内容区阻止遮罩关闭事件冒泡。Esc、取消按钮和点击遮罩均取消；pending 时禁止二次确认和遮罩关闭。

## 8. 状态与并发

### 8.1 页面状态优先级

```text
HTTP/contract failure -> error
totalCount == 0 -> empty
items loaded -> ready shell + dataStatus badge
```

`DELAYED/PARTIAL` 不替换 ready 表格，只改变状态标识和缺失显示。

### 8.2 请求竞争

1. 页面卸载取消 list/summary/search/membership 请求。
2. 搜索旧响应不得覆盖新 keyword。
3. `loadMore` 同一 cursor 只允许一个在途请求。
4. 删除与添加同一 `tsCode` 时，前端锁定该股票的 mutation；服务端唯一约束和 owner 条件仍是最终一致性保证。
5. Mutation 成功以服务端 `totalCount/isAdded` 为准，不在前端自行 `+1/-1` 推断。

## 9. 异常码

异常码先登记在 `wealth/docs/system/exception-code-registry.md`：

| code | 用途 | 前端行为 |
|---|---|---|
| `WL_REQUEST_INVALID` | code、limit、cursor、日期非法 | 当前局部显示不可重试输入错误 |
| `WL_STOCK_NOT_ELIGIBLE` | 目标不是当前上市 A 股 | 搜索行/详情 toast，列表不变 |
| `WL_QUERY_FAILED` | 列表、summary、search、membership 查询失败 | 对应局部 error，可重试 |
| `WL_WRITE_FAILED` | 添加或删除事务失败 | 保留当前 UI 事实并提示重试 |

认证层 401/403 不重复登记为 `WL_*`。

## 10. 测试设计

### 10.1 模型与迁移

`tests/test_wealth_watchlist_model.py`：

1. 同一用户同一 tsCode 第二次插入触发唯一约束。
2. 不同用户可以添加同一 tsCode。
3. 删除用户级联删除关系。
4. id 随新增递增，删除不改变剩余 id。
5. metadata 由 `register_all_models()` 正确注册。

### 10.2 后端真实 API

`tests/web/test_wealth_market_watchlist_api.py` 必须走真实 FastAPI router 和测试 DB session，不 mock QueryService：

1. 未登录六个端点均为 401。
2. summary 只统计当前用户。
3. list 按 id ASC，afterId 分批无重无漏。
4. list 核心可见字段逐项有值且同一日期。
5. basic/moneyflow 缺行时行保留、字段 null、状态 PARTIAL。
6. prior-day facts 不得补到 observed day。
7. PUT 首次 `created=true`，重复 `created=false`，总数不增。
8. 两个并发逻辑路径最终只有一条唯一关系。
9. DELETE 首次 `removed=true`，重复 `removed=false`。
10. 搜索结果 AVAILABLE/ADDED 与当前用户一致。
11. B 股、退市、非股票、其它交易所 PUT 返回 `WL_STOCK_NOT_ELIGIBLE`。
12. 非法 cursor/limit/code 映射 `WL_REQUEST_INVALID`。
13. DB 查询/写异常分别映射 `WL_QUERY_FAILED/WL_WRITE_FAILED`，不泄露内部文本。

### 10.3 前端单元与页面测试

1. `watchlistApi.test.ts`：路径、query、method、编码和错误解析。
2. `useWatchlistController.test.tsx`：初始、游标、去重、置尾、mutation 和乱序。
3. `AddWatchlistDialog.test.tsx`：hint、固定空 body、三列、500ms、abort、`+`、已添加、保持打开。
4. `RemoveWatchlistDialog.test.tsx`：页面居中、无 anchor、取消、确认、Esc、遮罩、pending、stopPropagation。
5. `WatchlistPage.test.tsx`：六态、原子列顺序、单位表头、数值换算、横向容器、代码/名称/操作三个 sticky 列、所属板块非 sticky 且为滑动区末列、数据列表头与单元格左对齐及左边界一致、操作控件居中、板块标签垂直居中、load-more、行跳详情。
6. `MarketOverviewPage.test.tsx`：真实 count、`--` 降级、入口路径，不改变其它卡片。
7. `StockDetailPage.test.tsx`：membership 状态、PUT、其它动作仍 placeholder、K 线参数不变。
8. `stockDetailViewModelAdapter.test.ts`：新 userActions contract，无旧字段。

### 10.4 核心真实展示 case

固定样例必须至少包含：

1. 上涨且净流入。
2. 下跌且净流出。
3. 平盘。
4. PE 为空。
5. basic 和 moneyflow 局部缺失。
6. 已添加和未添加搜索结果同时存在。

浏览器验收：

1. 1600px 宽桌面打开 `/wealth/market/watchlist`。
2. 验证对话框 fixed body 不跳高。
3. 验证横向滚动时股票代码、股票名称和操作列保持可见，所属板块随行情内容移动，并能在滑动到末端时完整显示在操作列左侧。
4. 验证数据列表头与内容左边界一致；操作列和搜索状态列中心一致，按钮内文字/加号双轴居中。
5. 验证纵向滚动到最后一项并停止请求。
6. 验证详情跳转后默认日 K 和“已自选”。
7. 检查 console 无错误、network 无重复循环请求、401 能回登录。

## 11. 性能验收

代码完成后必须记录：

1. 0、20、100、200 条单批响应体大小。
2. list/summary/membership/search/PUT/DELETE 各 30 次代表样本 P95。
3. list SQL `EXPLAIN (ANALYZE, BUFFERS)` 是否命中 `(user_id,id)` 和三张事实表主键。
4. 首屏从页面请求到 100 行 ready 的耗时。
5. 横向/纵向滚动期间是否产生长任务或明显卡顿。

门槛：列表、summary、membership、mutation P95 `<=300ms`，搜索 P95 `<=200ms`，单批 payload `<=256KiB`，前端不得一次加载全市场股票。

## 12. 编码门禁矩阵

| 通用清单项 | 适用 | 本模块落点 | 验证方式 | 状态 |
|---|---|---|---|---|
| 交付事实链先行 | 是 | benchmark + design + LLD + Figma | 文档与节点互链 | 用户已确认，D0 通过 |
| 后端事实归一 | 是 | WatchlistQueryService/DTO | 真实 API 字段断言 | 开发自测通过 |
| 模块状态机 | 是 | 页面/搜索/mutation 状态 | 状态过程测试 | 开发自测通过 |
| 显示与数据语义绑定 | 是 | direction 字段 | 红涨绿跌/缺失测试 | 开发自测通过 |
| 测试覆盖过程 | 是 | Controller/AddDialog/RemoveDialog | loading→ready/error | 开发自测通过 |
| 文档实现同轮同步 | 是 | 三份文档 + registry + README | diff 审核、第 17 节 | 已同步开发事实 |
| 模块级渐进替换 | 是 | 独立 watchlist real API | 无 mock/silent fallback | 开发自测通过 |
| 契约先行 | 是 | 第 5 节 DTO | schema/type 对账 | 开发自测通过 |
| 图表坐标 | 否 | 本模块无图表 | 无图表组件 | 不适用 |
| 统计下推 | 是 | count/joins SQL | 无应用层全量统计 | 开发自测通过 |
| 配置生效语义 | 否 | 无配置项 | env/Settings 静态审计 | 不适用 |
| 显式图表参数 | 否 | 本模块无图表 | 无 | 不适用 |
| 双图对齐 | 否 | 本模块无双图 | 无 | 不适用 |
| 卡片单行文案 | 否 | 不是指标卡模块 | 无 | 不适用 |
| 核心测试 case | 是 | 第 10.4 节 | 后端真实 API + 前端真实展示 | 开发自测通过，正式验收待用户执行 |
| 跨模块 8 原则 | 是 | 第 12.1 节 | 第 17 节代码/测试对账 | 开发自测通过 |

### 12.1 跨模块八原则门禁

| 原则 | 落地位置 | 测试 |
|---|---|---|
| 事实源单一 | watchlist table + serving DTO | 不读 mock/其它项目 API |
| 契约冻结 | Pydantic + TS 类型 | extra forbid + 旧字段清零 |
| 配置一致 | 无新增配置 | 静态搜索 |
| 默认显式 | 100/200、500ms、id ASC、同日快照 | 边界测试 |
| 排序筛选确定 | id cursor + A 股 Policy | 顺序与负例 |
| 性能预算 | 第 11 节 | EXPLAIN/P95/payload |
| 可观测标准 | `WL_*` + dataStatus | 异常与局部状态 |
| 用户结果优先 | 数量、列表、弹窗、增删、跳转 | 真实 API smoke |

### 12.2 模块例外白名单

无。横向滚动是用户明确要求，不属于设计系统例外；图表类门禁因本模块没有图表而不适用。

### 12.3 开工前签字

1. [x] 产品与交互基准已确认（用户本轮明确授权按方案开发）。
2. [x] Figma 交互设计已交付并完成结构、字体与原型自检。
3. [x] 技术实施方案已确认。
4. [x] 本 LLD 与编码门禁矩阵已确认，含分页日期变化整表重载。
5. [x] 异常码已登记。
6. [x] 开工时 Alembic head 已复查：`20260831_000168`。
7. [x] 无新增配置项。
8. [x] 当前工作区无与计划文件重叠的用户改动；无关文件保持不动。

当前结论：D0—D4 开发及隔离测试环境自测完成；本轮不提交、不推送、不部署，不代替用户正式验收。开发证据见第 17 节。

## 13. 验证命令

```bash
APP_ENV=test JWT_SECRET=watchlist-isolated-test-key-never-for-production \
WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED=false \
WEALTH_LOCAL_LAKE_STOCK_DAILY_TREND_CHANNEL_API_ENABLED=false \
.venv/bin/pytest -q tests/test_wealth_watchlist_model.py \
  tests/test_wealth_watchlist_postgres.py \
  tests/web/test_wealth_market_watchlist_api.py \
  tests/web/test_wealth_market_stock_search_api.py \
  tests/web/test_wealth_stock_detail_api.py \
  tests/architecture/test_subsystem_dependency_matrix.py
cd wealth && npm run typecheck
cd wealth && npm run test
cd wealth && npm run build
python3 scripts/check_docs_integrity.py
git diff --check
```

页面可视行为须提供真实 API 开发 smoke 证据；仅 mock 不算开发验证通过。部署及正式页面验收由用户执行，未执行项必须单独列明，不能标为已验收。

## 14. 回滚边界

1. D1/D2 未接前端时，可回滚 watchlist router/model/migration；不得影响行情表。
2. D3 前端失败时，只回滚 watchlist page、入口和 API 挂载，不修改其它首页模块。
3. D4 详情联动失败时，只回滚详情自选 props 和 granular capability contract，同一轮保持契约一致，不保留兼容字段。
4. 已产生的用户自选数据不得在普通代码回滚中自动删除；如需 drop 表必须单独获得明确授权和数据处置方案。

## 15. 待拍板项

无。

## 16. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-09-03 | 冻结代码符号、数据模型、API、状态、测试与编码门禁 | Codex |
| v1 开发对账 | 2026-09-03 | D0 同步分页日期变化规则；D1—D4 落地，记录隔离开发验证，保留部署和正式验收边界 | Codex |
| v1 展示修正 | 2026-09-03 | 按用户反馈修正两个按钮居中、最新价着色、PE/PB 拆列与资金千万单位；重新完成前端及真实 API 浏览器自测 | Codex |

## 17. 开发交付记录（2026-09-03）

本节为 `d143dec4` 首版开发时的历史测试证据；其中 11 列、估值组合列、资金亿元和全列左对齐口径已被第 18 节取代，不作为本次展示修正的通过依据。

### 17.1 代码与硬口径对账

所有路径以仓库根为基准。下表中的测试名均指仓库内可执行测试，不以截图替代行为断言。

| 硬口径 / 阶段 | 实现落点 | 验证落点与结果 |
|---|---|---|
| D0：冻结日期变化规则、修正回归路径、真实 head | 本文 7.4/12.3/13 及原技术方案 | head 从 `20260831_000168` 接到唯一 `20260903_000169`；保留当前 `dev-interface` 和所有无关改动 |
| D1：用户私有、唯一、级联、id 递增 | `src/biz/models/wealth/watchlist_item.py`、`src/app/model_registry.py`、迁移 `20260903_000169_add_wealth_watchlist_item.py` | `tests/test_wealth_watchlist_model.py`：唯一约束、双用户、级联、删除后 id 不复用、注册与迁移范围 |
| 并发幂等、提交失败回滚、只修改关系表 | `watchlist_command_service.py`：资格复核、savepoint、特定唯一约束识别、owner 条件 DELETE | `tests/test_wealth_watchlist_postgres.py`：8 并发 PUT 仅一条；外键错误不伪装重复；提交失败独立 session 读回无关系 |
| D2：六接口强制认证、用户隔离、安全错误 | `src/biz/api/wealth/market/watchlist.py`、Query/Command、`src/app/api/v1/router.py` | `tests/web/test_wealth_market_watchlist_api.py`：六接口 401、双用户读写隔离、重复增删、400/422/500、不泄露内部错误 |
| 当前上市 A 股候选，不按代码前缀猜资格 | 复用 `StockSearchPolicy/Query`；`WatchlistQuery.load_eligible_security` 复核四项条件 | API 测试覆盖 SSE/SZSE/BSE 正例及 B 股、退市、暂停上市、ETF、指数、其它市场负例；搜索后退市再次 PUT 被拒绝；首页 stock-search 原契约回归通过 |
| 同日行情、缺失不跨日、不补零、空自选不查行情 | `watchlist_query.py` 单一 observed date + 三表精确左连接；`watchlist_field_mapper.py` | API 逐字段断言价格/成交量/估值/量比/换手/资金/身份/行业；前日反例、无行情日期、缺 Security、零值与方向、PARTIAL/DELAYED/EMPTY |
| id ASC、有界 100/200、无 N+1、全局置尾 | `WatchlistPolicy`、`list_memberships/load_snapshot`、`useWatchlistController` | API 游标边界与追加；PostgreSQL 两次有界数据查询及索引；Controller 部分页不提前插新行、已读最大 id 删除后保留、重复项不追加 |
| 后续分页/尾读不同日期整表重载、回顶部 | `useWatchlistController.readMore/loadInitial`、`WatchlistTable` | Controller 测试含日期→日期、日期→null、null→日期、添加尾读变化、重载失败不保留旧表；旧请求取消和乱序保护 |
| D3：真实数量、独立页面、六态，不混用其它产品接口 | `WatchlistPage`、`useWatchlistSummary`、`watchlistApi`、`MarketShortcutBar`、`WealthRouter` | `WatchlistPage.test.tsx`、`MarketOverviewPage.test.tsx`、API client 测试；首页数量失败只显示 `--`，其它入口不改；浏览器真实 summary→200→进入自选页 |
| 添加弹窗固定空结果区、hint、三列、500ms、+ / 已添加 | `AddWatchlistDialog`、`useWatchlistSearchController` | 弹窗测试覆盖 499/500ms、IME、请求取消、乱序、关闭重置、失败重试、单行 pending、成功不关闭；浏览器初始/结果均为 560px 高 |
| 删除居中确认、取消/失败保留、pending 禁止二次操作 | `RemoveWatchlistDialog`、`useWatchlistDialog`、Controller | 弹窗及 Controller 测试覆盖 Esc/遮罩/取消/失败/防冒泡/锁定；浏览器 380×168 弹窗中心为视口中心 |
| 11 列顺序、单位在表头、估值纯数值、独立量比/换手、左对齐 | `WatchlistTable`、`watchlistViewModelAdapter`、`watchlist.css` | 页面测试 + 浏览器逐列文本断言：成交量 `/10000`、资金 `/10000`、PE/PB 无前缀；表头与内容实际文字左边界误差小于 1px |
| 代码/名称固定左侧、板块末列可滑动、仅操作固定右侧 | `watchlist.css` + 语义 table | 浏览器 computed style 仅三列 sticky；横滚后板块移动且完整停在操作左侧；板块标签垂直中心误差不超过 1px，行高 60px |
| 纵向加载至末行、同游标不重复请求 | `WatchlistTable` sentinel + Controller 单在途请求 | Controller 过程测试；真实浏览器 100→200 行后停止列表请求，添加 201 后尾部补读，移除回到 200 |
| D4：详情成员状态和幂等添加；默认日 K 不变 | `useStockWatchlist`、`StockInfoRail`、`StockDetailPage` | `StockDetailPage.test.tsx` 覆盖读取/添加/已添加/失败，重复点击只一次 PUT；真实浏览器行跳转后已自选，K 线首请求 `period=day&adjustment=forward` |
| 逐项能力合同、旧消费者清零、未开通动作不变 | `StockDetailUserActionsDto`、QueryService、TS API 类型与 fixtures | 后端/前端回归；全仓 `src`、`wealth/src`、`tests` 搜索旧字段，只剩证明字段不存在的负向断言；提醒、计划、诊股仍未开通 |

### 17.2 测试结果与隔离边界

1. 第 13 节后端组合：**60 passed**，含真实 PostgreSQL 4 项；随后补充 summary/membership EXPLAIN 断言再次 **4 passed**。
2. `wealth`：`npm run typecheck` 通过，`npm run test` **93 files / 610 tests passed**，`npm run build` 通过。
3. 新增后端/迁移/测试文件的 Ruff 检查通过；无新依赖、env、Settings 或配置中心项。
4. 开发数据库由 `tests/wealth_watchlist_postgres_support.py` 在新建空临时目录启动独立 PostgreSQL，仅监听随机本地端口。它不接受既有数据库地址；只创建白名单测试表并执行本次迁移，测试结束停止自身进程。不连接生产数据库，不清空或重建既有表。
5. 真实浏览器入口为 `tests/wealth_watchlist_browser_fixture.py`，前端使用正常构建产物、真实认证及业务路由，不使用 mock adapter。`wealth/scripts/watchlist-browser-smoke.mjs` 验证上涨/下跌/平盘、PE 缺失、指标/资金缺失、搜索 AVAILABLE/ADDED、增删、冻结/对齐、默认日 K 和 401 回登录。
6. 首页浏览器部分只验本轮数量及入口：真实 summary 返回 200 只，点击进入自选页。隔离服务未挂载的其它首页模块返回 404，明确不计为那些模块的验收，不伪造成功响应；自选及详情主流程 console/pageerror 为零。
7. 浏览器截图和量测 JSON 位于本次临时目录 `/private/tmp/wealth-watchlist-browser-evidence/`；可使用上述 fixture 和 smoke 脚本重新生成，不依赖把合成数据或截图提交为生产资源。

浏览器复跑方式：先构建 Wealth，在仓库根以第 13 节相同测试环境变量运行 `.venv/bin/python -m tests.wealth_watchlist_browser_fixture`。使用其输出的本地 URL、已创建的证据目录和本机 Playwright 模块绝对路径作为 `node wealth/scripts/watchlist-browser-smoke.mjs` 的三个参数。完成后 Ctrl-C 停止 fixture，它会停止自己创建的 PostgreSQL。

### 17.3 性能开发证据

样本为隔离 PostgreSQL 中 5,000 个合成股票、54 个测试用户；不是生产库数据或生产网络性能结论。每种接口 30 次顺序请求，列表按默认 100 行。

| 测量 | 结果 | 预算 |
|---|---:|---:|
| 0 / 20 / 100 / 200 行响应 | 362 / 8,243 / 40,208 / 80,286 字节 | 单批 ≤256KiB |
| list P95 | 10.15ms | ≤300ms |
| summary P95 | 2.72ms | ≤300ms |
| membership P95 | 2.90ms | ≤300ms |
| search P95 | 5.82ms | ≤200ms |
| PUT P95 | 4.57ms | ≤300ms |
| DELETE P95 | 3.07ms | ≤300ms |

`EXPLAIN (ANALYZE, BUFFERS)`：游标列表命中 `idx_wealth_watchlist_item_user_id_id`；同日有界关联命中三张事实表主键；summary 命中用户索引，membership 命中用户—股票唯一索引。对应执行时间为 0.024 / 0.250 / 0.025 / 0.017ms。浏览器 1600×980 首批 100 行 ready 多次自测约 140—195ms；横向/纵向滚动未观测到长任务。

### 17.4 影响面、风险与下一步

CodeGraph 开工使用 `codegraph_status`、`codegraph_explore`、`codegraph_search`、`codegraph_impact`，覆盖首页入口、路由、搜索 Query/Policy、认证、行情模型与详情 capability 全部当前消费者；开发后 `codegraph sync` 与状态检查通过。业务规则归属 `src.biz`，`src.app` 只挂路由和注册模型，行情继续只读 `foundation` 模型；没有修改依赖矩阵，没有引入 ops、legacy 或 qtf 反向依赖。

当前没有未落地的 D1—D4 编码项。尚未执行且由用户负责：迁移部署、后端与前端同批发布、真实账号/真实行情的正式验收及生产性能复核。详情 capability 是替换契约，不保留旧字段，发布时不可长期混用新旧前后端。

构建仍提示单个 JS chunk 大于 500KB（当前约 954.86KB，gzip 284.53KB）；本轮未扩展为全站拆包重构。测试运行有现有依赖的弃用警告，不影响通过。所有无关工作区改动保留；本轮未提交、未推送、未部署。

## 18. 用户反馈展示修正（2026-09-03）

### 18.1 本次冻结范围

仅修改 `wealth/src/features/watchlist` 的展示与格式化、对应页面测试、浏览器 smoke 和本页面三份文档。不改后端 DTO、SQL、持久化、搜索/分页、默认日 K、共享主题或其它模块；不提交、不推送、不部署。

| 用户要求 | 当前证据 / 根因 | 编码落点 | 必须验证 |
|---|---|---|---|
| 移除按钮采用按钮样式，文字居中 | 已是原生 button，但 `padding-left:11px;text-align:left` 刻意把文字推向左侧 | `watchlist.css` 删除单侧偏移，暗底/描边沿用 token；操作列和按钮内容居中，补 hover | 浏览器按钮与单元格中心、文字与按钮中心误差 ≤1px；点击仍只开确认弹窗 |
| 添加按钮水平/垂直居中 | 状态格没有居中布局，加号按字体基线排列 | `AddWatchlistDialog` 状态格 flex 居中；按钮 inline-flex；对称 SVG 加号避免字体基线偏移 | 真实搜索结果状态格、按钮、加号三者双轴中心一致；pending/已添加不偏移 |
| 最新价跟随涨跌百分比字色 | `price-column` 没有使用现成的 `priceDirection` | `WatchlistTable` 使用相同行情色 class；缺价仍中性 | UP/DOWN/FLAT/UNKNOWN、缺价负例；实际 computed color 与涨跌幅相同 |
| PE/PB 拆列 | DTO/view model 已是两个字段，仅表格合并展示 | 独立 `pe-column`/`pb-column`，宽度 156/134px；原 194px 组合列删除，总表宽 1768px | 12 列顺序、数值独立、无旧组合列；PE/PB 缺失不影响彼此；原冻结边界和横滚保持 |
| 资金净流入改为千万 | API `netAmount` 是万元，当前 adapter 除以 10000 | 仅 adapter 改为 `/1000`，表头“资金净流入（千万）” | 2189.4→+2.19、-2189.4→-2.19、0→0.00、null→--；成交量仍除以 10000 |

数据列继续左对齐；操作/搜索状态列的居中是本次用户要求对首版全列左对齐的明确局部替换，不扩散到其它列。按钮仍使用已有原生语义与 feature 样式，不新建全站 Button 框架。

### 18.2 开发验证记录

1. 本次重新执行 `wealth` 全量前端测试：**94 files / 626 tests passed**；自选专项为 **6 files / 42 tests passed**。新增 adapter 测试 9 项，页面补充涨跌方向、缺价和独立估值反例；添加弹窗断言状态格及加号结构，原 pending/幂等/搜索时序测试保留。
2. `npm run typecheck`、`npm run build`、文档完整性及 `git diff --check` 通过。构建仍有单个 JS chunk 超过 500KB 的既有提醒（当前约 955.19KB，gzip 284.64KB）；未扩展为全站拆包工作。
3. 使用首版隔离 fixture 的全新临时 PostgreSQL、真实认证、真实 API 和本次构建产物重新跑浏览器 smoke；只操作隔离合成数据，未连接既有或生产数据库。12 列顺序、PE/PB 独立缺失、资金正负值与千万换算、数据列左对齐、冻结边界、所属板块横滚、增删及默认日 K 全部通过；100→200 行后停止分页，添加置尾到 201、移除回到 200。
4. 浏览器双轴量测：添加按钮相对状态格中心偏差 **(0, 0)px**，加号相对按钮中心偏差 **(0, 0)px**；移除按钮相对单元格中心偏差 **(0.5, -0.5)px**，文字相对按钮中心偏差 **(0, 0)px**，均满足 ≤1px。添加初始/结果弹窗同为 560px 高；删除确认仍在页面中心。截图人工复核通过。
5. 最新价与涨跌幅 computed color 完全一致：上涨 `rgb(255, 77, 90)`、下跌 `rgb(21, 199, 132)`、平盘 `rgb(203, 213, 225)`；缺价中性由页面负向测试覆盖。主流程 console/pageerror 为零；其它未挂载的首页模块仍仅作为隔离边界记录，不算其验收。
6. 复现方式沿用第 17.2 节。本次截图及量测 JSON 位于 `/private/tmp/wealth-watchlist-ui-review.ySIy5B/`，为本机临时开发证据，不作为生产资源提交。
7. 编码前使用 `codegraph_explore` 核验 `WatchlistTable`、`AddWatchlistDialog`、`buildWatchlistRow` 及页面消费者；开发后执行 `codegraph sync` 与状态检查。改动仅在第 18.1 节范围，无共享契约、后端或依赖矩阵变更，所有无关工作区修改保留。本次未重跑后端单元套件，不把首版 60 项结果写成本轮结果；后端连通及主流程由上述真实 API smoke 验证。

本次开发与自测已完成；未提交、未推送、未部署。后续由用户部署并进行真实账号、真实行情的正式验收。Figma 保留首版，本次明确修正以三份同步文档为准。
