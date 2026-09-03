# 财势乾坤｜我的自选技术实施方案 v1

> 状态：Figma 交互设计已完成并完成自检，待用户评审；代码未实现
>
> 日期：2026-09-03
>
> 产品与交互基准：[我的自选产品与交互基准 v1](./watchlist-benchmark-requirement-v1.md)
>
> 代码级设计：[我的自选低层设计 v1](./watchlist-low-level-design-v1.md)

## 0. Figma 到实现的交付映射

Figma 主页面为 [`1277:82`](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1277-82)，状态与交互交付板为 [`1282:754`](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1282-754)，可点击原型从 [`1293:289`](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1293-289) 开始。

| 设计事实 | 实现约束 |
|---|---|
| 复用现有顶部行情栏、面包屑、深色 Panel 与金色强调 | 前端不得为本页另建一套主题或页面壳 |
| 股票代码、股票名称固定在左侧；所属板块是横向滑动区最后一列；仅操作固定在右侧 | 使用两个左侧固定身份列、一个含所属板块的横向滚动区和一个右侧固定操作列；不得把所属板块实现为 sticky 列 |
| 所有列表头与对应单元格内容左对齐 | 表头和表体复用同一列宽及左侧内边距；数值列只使用等宽数字，不改成右对齐 |
| 正文纵向连续滚动，滚动条可见 | 游标分页追加，直到最后一只股票；不得展示传统分页器 |
| 添加弹窗上方搜索、下方固定高度结果区 | 空态不请求；输入停顿 500ms 后请求；请求期间弹窗高度不变 |
| 搜索结果只有代码、名称、状态三列 | `AVAILABLE` 显示 `+`，`ADDED` 显示“已添加”，请求中仅当前行进入 pending |
| 添加成功后弹窗不关闭、数量加一、股票置尾 | 前端局部更新必须保持后端 `id ASC` 顺序，不得插到首位 |
| 删除使用页面正中的轻量确认弹窗 | 不依赖按钮 anchor；取消不改变列表，确认成功后移除该行并更新数量 |
| 表头承担展示单位，单元格只显示数值 | 成交量按万手、资金净流入按亿元、涨跌幅与换手率按百分比格式化；不得在值后重复单位 |
| 量比、换手率各自成列，估值值不带字段前缀 | 移除“活跃度”组合列；估值表头说明 `PE / PB`，两行值只渲染数值 |
| 点击股票区域进入详情，操作区不冒泡 | 统一导航到现有股票详情路由，默认日 K；移除按钮不得触发行跳转 |
| 交付板覆盖 loading/empty/delayed/partial/error | 页面和局部组件必须实现这些状态，不得静默回退 mock |

关键状态画板：添加初始态 [`1290:185`](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1290-185)、搜索结果态 [`1282:82`](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1282-82)、添加成功态 [`1293:625`](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1293-625)、删除确认态 [`1282:418`](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1282-418)、删除完成态 [`1291:237`](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1291-237)、日 K 去向 [`1293:1004`](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=1293-1004)。

## 1. 文档目的

本文把“我的自选”冻结为一条用户私有持久化、统一交易日行情聚合和 Wealth 前端交互的正式链路。

实现目标：

1. 建立用户—股票唯一自选关系和幂等增删能力。
2. 建立自选列表、数量、添加弹窗搜索和单股成员状态 API。
3. 新增独立自选页，并接通首页入口和股票详情页“+自选”。
4. 复用当前上市 A 股搜索合同、`MarketPageContext` 和股票详情路由能力。
5. 所有行情字段由后端按统一交易日产出，前端只格式化和展示。

本期不做分组、提醒、排序编辑、批量操作、盘中实时行情或其它证券类型。

## 1.1 跨模块抽象门禁原则适配

| 原则 | 本模块结论 | 设计落点 | 计划测试 |
|---|---|---|---|
| 事实源单一 | 自选关系以数据库唯一表为事实源；行情以 serving 表为事实源 | `app.wealth_watchlist_item` + `core_serving` | 真实 API 字段和唯一约束测试 |
| 契约先行与冻结 | 本文与 LLD 先冻结 DTO、状态、排序和 API | `src/biz/schemas/**/watchlist.py` | schema extra forbid、前后端类型对账 |
| 配置一致 | 本模块不新增配置项 | 固定产品合同常量 | 静态审计无 env/Settings/配置中心改动 |
| 默认行为显式 | 新增置尾、同日快照、空搜索不请求、删除幂等 | Policy、Query、Controller | 默认与边界行为测试 |
| 排序筛选确定 | 自选按主键升序；候选沿用已冻结 A 股筛选与搜索排序 | Query + 既有 StockSearchPolicy | 顺序、B 股、退市、重复添加负例 |
| 性能预算前置 | 列表游标分页、查询字段有界、搜索结果有界 | `limit/afterId`、索引、SQL 下推 | EXPLAIN、P95、payload 实测 |
| 可观测标准化 | 使用登记后的 `WL_*` 异常码和 dataStatus | API + exception registry | 400/404/500、delayed/partial 测试 |
| 用户可见结果优先 | 测试首页数量、弹窗状态、列表字段、滚动和详情跳转 | 后端真实路由 + 前端真实响应 smoke | 核心 case 双门禁 |

## 2. 当前代码审计

### 2.1 已有能力

| 能力 | 当前落点 | 复用方式 |
|---|---|---|
| 首页快捷入口 | `wealth/src/features/market-overview/layout/MarketShortcutBar.tsx` | 替换固定数量和 toast 占位导航 |
| 路由 | `wealth/src/app/routes/WealthRouter.tsx`、`routerState.ts` | 增加 watchlist path builder 和页面分支 |
| 当前上市 A 股搜索 | `src/biz/**/stock_search*` | 复用 Policy 和 Query，不修改已结案首页搜索契约 |
| 前端认证请求 | `wealth/src/shared/api/wealthApiClient.ts` | 所有自选 API 统一携带登录凭据并处理续签 |
| 强制登录身份 | `require_authenticated` | 自选接口不使用可返回 `None` 的 `require_quote_access` |
| 页面交易日 | `MarketPageContextQuery` | 解析 expected trade date |
| 股票详情路由 | `buildStockDetailPath(tsCode)` | 自选行统一由页面上报 `tsCode` 后导航 |
| 详情页自选入口 | `StockInfoRail.tsx` | 把“+自选暂未开通”替换为真实局部状态 |

### 2.2 当前缺口

1. 首页自选卡片徽标固定为 `18`，路径为占位 `/watchlist`，点击只上报 toast。
2. `WealthRouter` 没有自选页面分支。
3. 仓库没有用户自选 ORM、迁移、Repository、API、DTO 或前端 feature。
4. `StockDetailCapabilitiesDto` 用一个笼统的 `supportsUserActions=false` 表达全部用户操作，接通自选后会失真。
5. 当前行情事实分散在日行情、每日指标和资金流表，需要后端按同日合同聚合。

### 2.3 CodeGraph 影响面

CodeGraph 索引根为仓库根，状态已确认最新。已分析：

1. `MarketShortcutBar -> MarketOverviewPage -> ShortcutBar` 首页入口链。
2. `WealthRouter -> StockDetailPage` 页面路由链。
3. `StockInfoRail -> StockDetailPage` 详情页操作消费者。
4. `StockDetailCapabilitiesDto -> StockDetailPageInitResponseDto -> QueryService -> 前端 API 类型与测试` 契约影响面。
5. `StockSearchQuery -> StockSearchQueryService -> 首页搜索 API`，确认可复用底层查询但不得修改既有响应。
6. `EquityDailyBasic`、`EquityMoneyflow` 的现有模型与消费者。

未发现 `ops` 消费者或跨 `qtf` 依赖；实现必须继续保持业务链路不导入 `src.ops`、`src.operations` 或 `qtf`。

## 3. 领域与持久化设计

### 3.1 业务事实表

新增 `app.wealth_watchlist_item`：

| 字段 | 类型 | 约束 | 语义 |
|---|---|---|---|
| `id` | bigint | PK，自增 | 稳定添加顺序和游标 |
| `user_id` | integer | not null，FK `app.app_user.id`，cascade delete | 自选所有者 |
| `ts_code` | varchar(16) | not null | 股票代码 |
| `created_at` | timestamptz | not null | 添加时间 |
| `updated_at` | timestamptz | not null | 标准更新时间 |

数据库约束：

1. 唯一约束 `uq_wealth_watchlist_item_user_stock(user_id, ts_code)`。
2. 列表索引 `idx_wealth_watchlist_item_user_id_id(user_id, id)`。
3. 不把价格、估值、成交或资金流冗余保存到自选表。
4. 不对 `core_serving.security_serving` 建外键，避免证券 serving 重建影响用户关系；添加时由业务服务校验资格。

代码模型放在 `src/biz/models/wealth/watchlist_item.py`，由 `src.app.model_registry` 在组合根注册。数据库使用 `app` schema 只表示“用户持久化数据”，不把业务规则放入 `src/app/models`。

### 3.2 新增顺序

1. 列表固定按 `id ASC`。
2. 新增记录取得更大的 `id`，自然追加到列表最后。
3. 游标使用最后一行 `id`，下一批查询条件为 `id > afterId`。
4. 删除后不重排其余记录，也不复用被删除 id。

### 3.3 幂等写入

添加：

1. 归一化 `tsCode=trim().upper()`。
2. 服务端校验目标是当前上市 A 股。
3. 在唯一约束保护下创建；并发冲突在 savepoint 内收敛为 `created=false`。
4. 成功返回当前关系状态和最新总数。

删除：

1. 只按认证用户和 `tsCode` 删除。
2. 不存在时返回 `removed=false`，仍为成功响应。
3. 添加或删除事务只修改用户自选表，不触碰行情表。

## 4. 后端分层与目录

```text
src/biz/
  models/wealth/
    watchlist_item.py
  api/wealth/market/
    watchlist.py
  schemas/wealth/market/
    watchlist.py
  queries/wealth/market/watchlist/
    watchlist_query.py
    watchlist_query_service.py
  services/wealth/market/watchlist/
    watchlist_policy.py
    watchlist_command_service.py
    watchlist_field_mapper.py

src/app/
  api/v1/router.py
  model_registry.py

alembic/versions/
  <current-head>_add_wealth_watchlist_item.py

tests/
  web/test_wealth_market_watchlist_api.py
  test_wealth_watchlist_model.py
```

职责：

1. API：鉴权、参数接收、异常映射、事务入口。
2. Query：只读 SQL、游标分页、同日行情关联、搜索成员状态。
3. QueryService：页面上下文、列表状态和 DTO 组合。
4. CommandService：资格复核、添加/删除、commit/rollback 和幂等结果。
5. Policy：固定页大小、代码归一化、当前上市 A 股判定合同。
6. App Router/Registry：只挂载路由和注册 ORM，不承载业务规则。

当前 Alembic head 在方案审计时为 `20260831_000168`；编码前必须再次执行 `alembic heads`，迁移 `down_revision` 只能连接当时真实 head。

## 5. API 设计

统一前缀：`/api/v1/wealth/market/watchlist`。所有接口使用 `require_authenticated`。

### 5.1 列表

```http
GET /api/v1/wealth/market/watchlist?limit=100&afterId=&tradeDate=
```

请求：

| 参数 | 默认 | 约束 |
|---|---:|---|
| `limit` | 100 | `1..200` |
| `afterId` | 无 | 正整数；用于自动加载下一批 |
| `tradeDate` | 无 | 可选回看日期；不传由 `MarketPageContext` 决定 |

响应包含：

1. `pageContext`
2. `dataStatus`
3. `items[]`
4. `totalCount`
5. `nextCursor`

`items` 严格按添加顺序升序。前端不得重新按涨跌或名称排序。

### 5.2 首页数量

```http
GET /api/v1/wealth/market/watchlist/summary
```

返回当前用户 `totalCount`。首页不为获取徽标而加载完整自选列表。

### 5.3 添加弹窗搜索

```http
GET /api/v1/wealth/market/watchlist/search?keyword=PAYH&limit=8
```

1. 复用 `StockSearchPolicy` 和 `StockSearchQuery` 的候选池、前缀匹配、转义与排序。
2. 再按当前用户关系补充 `status=AVAILABLE|ADDED`。
3. 不修改 `/stock-search` 的既有响应和首页消费者。
4. 默认 8、最大 20；空 keyword 由前端不请求，直接保持固定空白结果区。

### 5.4 单股成员状态

```http
GET /api/v1/wealth/market/watchlist/items/{tsCode}
```

返回 `tsCode` 和 `isAdded`，供股票详情页初始化“+自选/已自选”。

### 5.5 添加

```http
PUT /api/v1/wealth/market/watchlist/items/{tsCode}
```

返回：

```json
{
  "tsCode": "000001.SZ",
  "isAdded": true,
  "created": true,
  "totalCount": 19
}
```

重复添加返回 HTTP 200、`created=false`，不产生重复记录。

### 5.6 删除

```http
DELETE /api/v1/wealth/market/watchlist/items/{tsCode}
```

返回 `removed` 和最新 `totalCount`。关系已不存在时返回 HTTP 200、`removed=false`。

## 6. 列表行情查询

### 6.1 统一日期

查询顺序：

1. `MarketPageContextQuery` 得到 `expectedTradeDate`。
2. 查询 `max(core_serving.equity_daily_bar.trade_date) <= expectedTradeDate` 作为全页 `observedTradeDate`。
3. 先取得当前用户一批自选 `id/ts_code`。
4. 按 `ts_code + observedTradeDate` 精确左连接行情、每日指标和资金流。
5. 禁止对每只股票或每张事实表执行“各取最新一条”。

### 6.2 字段映射

| DTO | 来源 |
|---|---|
| `stock.tsCode/name/industry/listStatus` | `security_serving` |
| `quote.price` | `equity_daily_bar.close` |
| `quote.changePct` | `equity_daily_bar.pct_chg` |
| `quote.vol` | `equity_daily_bar.vol` |
| `valuation.peTtm/pb` | `equity_daily_basic.pe_ttm/pb` |
| `activity.volumeRatio/turnoverRate` | `equity_daily_basic.volume_ratio/turnover_rate` |
| `moneyFlow.netAmount` | `equity_moneyflow.net_mf_amount` |

源单位：`price=元`、`changePct=%`、`vol=手`、`netAmount=万元`、`turnoverRate=%`。后端只返回数值和结构化方向；前端将 `vol / 10000` 显示为万手、`netAmount / 10000` 显示为亿元，并把单位放在表头而不是单元格。

### 6.3 状态归并

1. 无自选关系：`EMPTY`。
2. 有关系但无任何可用行情日期：`PARTIAL`，身份仍展示。
3. `observedTradeDate < expectedTradeDate`：至少 `DELAYED`。
4. 同日任一自选行缺少身份或任一已确认指标：`PARTIAL` 优先于 `DELAYED`，同时保留日期事实。
5. SQL/DTO 失败：HTTP 500 + `WL_QUERY_FAILED`，前端进入 error，不回退 mock。

每行返回 `missingFields[]`，只用于局部 `--` 和辅助说明，不允许前端据此自行寻找其它日期回填。

## 7. 前端架构

```text
wealth/src/
  app/routes/
    WealthRouter.tsx
    routerState.ts
  pages/watchlist/
    WatchlistPage.tsx
    WatchlistPage.test.tsx
    watchlist-page.css
  features/watchlist/
    api/
      watchlistApi.ts
      watchlistApiTypes.ts
      watchlistApi.test.ts
    model/
      watchlistTypes.ts
      watchlistViewModelAdapter.ts
      useWatchlistController.ts
      useWatchlistController.test.tsx
    ui/
      WatchlistTable.tsx
      AddWatchlistDialog.tsx
      RemoveWatchlistDialog.tsx
      watchlist.css
  features/market-overview/layout/
    MarketShortcutBar.tsx
  features/stock-detail/sidebar/
    StockInfoRail.tsx
```

边界：

1. `WatchlistPage` 只负责页面编排、统一导航和页面状态。
2. `useWatchlistController` 负责游标加载、追加、删除、刷新数量和请求竞争控制。
3. API DTO 先经过 adapter 生成 ViewModel，组件不直接拼接数据事实。
4. `AddWatchlistDialog` 是 watchlist feature 专用组件；它复用搜索 API 语义，不复用首页 `StockSearch` 可见组件。
5. `WatchlistTable` 上报 `tsCode` 和 remove intent，不直接拼路由。
6. 首次只有一个消费者，不提前提升到 `shared/ui`。

## 8. 页面交互实现

### 8.1 页面列表

1. 页面复用 `TopMarketBar` 和 `PageBreadcrumb`。
2. 主 Panel 顶部展示标题、总数、实际数据日期和“+ 添加自选”。
3. 外层纵向 viewport 触发游标加载；表格容器 `overflow-x:auto`。
4. 表头 sticky；股票代码、股票名称依次 sticky left；所属板块保留在横向滚动内容中并作为最后一列；只有操作列 sticky right。
5. 表格设置高密度最小宽度，空间不足时滚动而不是隐藏列。
6. 行点击调用页面 `openStockDetail(tsCode)`；移除按钮 stopPropagation。
7. 可见列顺序固定为：股票代码、股票名称、最新价（元）、涨跌幅（%）、成交量（万手）、估值（PE / PB）、量比、换手率（%）、资金净流入（亿元）、所属板块、操作。
8. 估值单元格第一行展示 PE(TTM) 数值，第二行展示 PB 数值，不添加 `PE`/`PB` 前缀；所属板块标签在行内垂直居中。
9. 所有表头和对应单元格内容统一左对齐，并共享相同列内左边界；板块标签文字同样左对齐。

### 8.2 添加对话框

1. 初始 `keyword=""`、`items=[]`，结果正文完全为空。
2. hint 固定“输入名称首字母或代码”。
3. 500ms debounce，旧请求 abort，乱序响应不得覆盖最新搜索词。
4. 三列严格为代码、名称、状态。
5. `AVAILABLE` 渲染 `+` 按钮；`ADDED` 渲染“已添加”。
6. 添加成功后原位更新状态，同时把新行追加到当前列表末尾；对话框不关闭。
7. 结果区固定高度，loading/empty/error 在正文区内表达。

### 8.3 删除确认弹窗

1. 弹窗固定显示在页面正中，不以当前移除按钮为 anchor；支持取消、确认、Esc 和点击遮罩关闭。
2. 确认中保留行并锁定重复操作。
3. 成功后移除行、更新总数和搜索弹窗成员状态。
4. 失败后保留行，关闭 processing，并显示 toast。

### 8.4 详情页

1. `StockInfoRail` 增加结构化 watchlist props，不复用 `onAction(message)` 字符串解析。
2. 详情页加载独立成员状态；未添加显示“+自选”，已添加显示“已自选”。
3. 点击“+自选”使用同一个 PUT 接口，成功后原位变为“已自选”。
4. 不改变 K 线、周期、复权或其它右栏数据请求。

`StockDetailCapabilitiesDto` 将删除笼统的 `supportsUserActions/unsupportedActions`，改为逐项能力：

```json
{
  "userActions": {
    "watchlist": true,
    "alert": false,
    "tradePlan": false,
    "diagnosis": false
  }
}
```

所有后端 DTO、前端类型、fixture 和测试同轮修改，不保留旧字段别名。

## 9. 认证与安全

1. 所有 watchlist 接口强制 `require_authenticated`，从 `AuthenticatedUser.id` 取 owner。
2. 不接受 `userId` 参数，不允许前端选择 owner。
3. 列表、搜索状态、成员状态、添加和删除均带 `user_id` 条件。
4. 详情行情仍按现有 quote access 合同；只有自选成员状态和写操作要求强制身份。
5. SQL 参数全部绑定；搜索通配符继续沿用既有转义合同。

## 10. 性能与配置审计

### 10.1 性能预算

1. 列表默认 100、最大 200 行，游标分页，无 offset 深翻页。
2. 单批响应目标不超过 256KiB。
3. 列表、summary、membership 和写接口 P95 目标 `<= 300ms`。
4. 添加弹窗搜索沿用既有搜索 API 的 P95 `<= 200ms` 目标。
5. 前端请求超时 5s；搜索请求沿用 2s 局部超时。
6. 编码完成后必须对列表 SQL、summary 和 membership 做真实数据库 EXPLAIN 与代表性耗时验证。

### 10.2 配置审计

本模块不新增配置项：

| 口径 | 类型 | 唯一来源 | 对外配置 |
|---|---|---|---|
| 列表 100/200 | API 合同常量 | WatchlistPolicy | 否 |
| 搜索 500ms | 产品交互合同 | Controller + 本文 | 否 |
| 当前上市 A 股四项过滤 | 业务合同 | 既有 StockSearchPolicy/Query | 否 |
| 新增置尾 | 排序合同 | `id ASC` | 否 |
| 同日快照 | 数据合同 | QueryService | 否 |

不修改 env、Settings、数据库配置表或策略配置中心。

## 11. 测试与验收计划

### 11.1 后端

1. ORM 唯一约束、用户隔离、cascade delete。
2. 真实路由列表、summary、search、membership、PUT、DELETE。
3. 重复和并发添加只保留一条，`created=false`。
4. 删除不存在关系返回 `removed=false`。
5. 非 A 股、B 股、退市、非股票添加均失败。
6. 列表按 id 升序，分页无重无漏，新添加在最后。
7. 所有行情字段精确同日关联；缺失不跨日回填。
8. 401 与跨用户读取/写入隔离。

### 11.2 前端

1. 首页真实徽标和真实路由。
2. 空列表、加载、ready、delayed、partial、error。
3. 固定搜索结果区、初始空白、准确 hint 和三列。
4. 499ms 不请求、500ms 请求、abort 与乱序保护。
5. `+ -> processing -> 已添加`，对话框保持打开，新行置尾。
6. 居中删除确认弹窗的取消、确认、失败保留。
7. 横向滚动、左侧代码/名称固定、所属板块作为滑动区末列随内容移动、仅右侧操作固定、纵向加载到最后一行。
8. 各列表头和表体内容左边界一致且均左对齐。
9. 行跳详情且移除不误跳；详情页“+自选”状态正确。

### 11.3 核心测试 case

核心可见字段：`tsCode/name/price/changePct/vol/peTtm/pb/volumeRatio/turnoverRate/netAmount/industry/priceDirection/moneyFlowDirection/observedTradeDate/totalCount`。

门禁：

1. 后端真实 FastAPI 路由测试必须逐字段断言，禁止 mock QueryService。
2. 前端真实 API 展示 smoke 必须用真实后端响应驱动页面，禁止 mock adapter 冒充验收。
3. 浏览器检查 `/wealth/market/overview`、`/wealth/market/watchlist` 和一条股票详情路由的 console/network/视觉状态。

## 12. 分期

1. D0：交互基准、实施方案、LLD、异常码与迁移 head 门禁。
2. D1：ORM、迁移、Repository、幂等 CommandService。
3. D2：列表/summary/search/membership/增删 API 与真实集成测试。
4. D3：自选页、弹窗、滚动、首页入口与真实 API smoke。
5. D4：股票详情“+自选”、契约清理、全量回归和浏览器验收。

每个阶段只推进自选功能，不顺手修改其它首页卡片或详情动作。

## 13. 风险与缓解

| 风险 | 触发条件 | 缓解 |
|---|---|---|
| 用户数据串读 | 查询遗漏 user_id | Repository 方法强制 user_id，双用户负例 |
| 重复关系 | 并发 PUT | 数据库唯一约束 + savepoint 幂等处理 |
| 行情串日 | 每表各取 latest | 单一 observedTradeDate 精确左连接 |
| 列表太宽 | 字段超出视口 | 最新价至所属板块整体横向滚动 + 左侧代码/名称固定 + 仅右侧操作固定，不隐藏字段 |
| 新增顺序漂移 | DB 隐式排序 | `id ASC` + afterId cursor |
| 首页加载整表 | 只为数量请求列表 | 独立 summary 接口 |
| 已结案搜索被破坏 | 修改首页 stock-search DTO | 只复用 Policy/Query，新增 watchlist search DTO |
| 能力合同失真 | 仍保留 blanket user action 字段 | 同轮改成逐项能力并清零旧字段消费者 |

## 14. 待拍板项

无。

## 15. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-09-03 | 冻结自选持久化、API、统一日期行情、前端交互和详情联动；补充全列左对齐、所属板块随行情滑动且仅操作列右侧固定 | Codex |
