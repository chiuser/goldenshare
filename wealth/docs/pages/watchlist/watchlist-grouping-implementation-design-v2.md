# 财势乾坤｜我的自选分组能力技术实施方案 v2

> 状态：前后端代码已实现；第二阶段前端开发自测见 LLD 第 23 节，停在交互与真实 API 验收之前。本轮前端未提交、未部署、未迁移正式数据库
>
> 日期：2026-09-08（初稿 2026-09-07）
>
> 产品依据：[我的自选分组能力产品需求文档 v2](./watchlist-grouping-product-requirement-v2.md)
>
> 交互依据：[我的自选分组能力交互设计 v2](./watchlist-grouping-interaction-design-v2.md)
>
> Figma：[Watchlist V2 / Interaction Board](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare?node-id=1383-82)
>
> 开发前历史基线：[我的自选技术实施方案 v1](./watchlist-implementation-design-v1.md)
>
> 低层设计：[我的自选分组能力低层设计 v2](./watchlist-grouping-low-level-design-v2.md)

## 0. 结论与实施边界

本方案把当前“一个用户一张自选清单”升级为“一个用户多个分组、一个股票可以属于多个分组”的正式业务模型。

技术结论如下：

1. 使用独立的分组表和分组成员表，替代当前 `app.wealth_watchlist_item` 单表模型。
2. “我的自选”也是数据库中的正式分组记录，通过 `is_default` 标识，不依赖名称判断身份。
3. 现有自选关系一次性、无损迁移到每个用户的默认分组，保留原加入顺序。
4. 分组、成员、置顶、颜色和排序事实全部由后端合同产出；前端不自行拼装跨分组事实。
5. 数值排序在数据库中对当前组全量成员生效，并继续使用确定性游标分页；禁止只对前端已加载行排序。
6. 移动、添加到分组、移出、详情页归属替换和删除分组均为单事务原子操作。
7. 首页 summary 路径和响应形状保持不变，但其计数语义改为只统计默认分组。
8. v2 前后端与迁移在同一发布窗口切换；删除旧模型和旧成员 API，不保留双写、旧接口别名或兼容代码。

两轮修订对账见 LLD 第 21.1～21.2 节，名称依赖准入见第 21.3 节。用户随后分阶段授权后端和前端开发：后端实现与隔离 PostgreSQL 验证记录在第 22 节，前端实现与开发自测记录在第 23 节。工作区运行时代码已统一为 v2，交互与真实 API 浏览器验收、发布顺序演练仍待阶段三；本文不代表完整产品已验收或正式库已升级。

## 1. 文档目的

### 1.1 要解决的问题

1. 冻结分组、成员和置顶的唯一数据事实源。
2. 冻结默认分组创建、历史数据迁移和用户删除级联规则。
3. 冻结页面、首页、详情页所需 API 及事务语义。
4. 冻结置顶优先、八个数值列排序、缺失值和分页稳定性规则。
5. 明确前端展示态、编辑态、批量操作和详情页选择器的状态边界。
6. 给出性能、鉴权、异常、测试、发布和回滚门禁。

### 1.2 本方案不做

1. 不设计分组改名 API。
2. 不设计分组或成员拖拽排序。
3. 不持久化数值排序偏好。
4. 不支持表头全选、跨页全选或整组全选。
5. 不扩大当前上市 A 股的准入范围。
6. 不改造行情来源、统一交易日和缺失值语义。
7. 不新增 Redis、消息队列、配置中心开关或后台运营配置。
8. 不修改 `src.foundation` 数据事实、`src.ops`、`qtf` 或 lake 链路。

### 1.3 跨模块抽象门禁原则适配

| 原则 | 本模块结论 | 设计落点 | 计划测试 |
|---|---|---|---|
| 事实源单一原则 | 分组与成员只认两张新表；行情继续只认 `core_serving` | `wealth_watchlist_group`、`wealth_watchlist_membership`、现有 serving 表 | ORM 约束、真实 API、迁移前后对账 |
| 契约先行与冻结原则 | 本文先冻结资源、动作和 DTO 边界，LLD 再冻结逐字段实现 | `schemas`、API 路径、前端 API 类型 | Pydantic extra forbid、前后端合同测试 |
| 配置一致性原则 | 分组上限、名称上限和色板是后端产品常量，不是运行配置 | `WatchlistPolicy` 返回 `rules`，前端直接消费 | 固定顺序、上限和非法颜色测试 |
| 默认行为显式原则 | 默认组实体化、默认进入、默认计数、默认排序均有唯一规则 | 迁移、用户创建事务、summary、列表查询 | 新旧用户、首页、无参数进入测试 |
| 排序与筛选确定性原则 | 置顶分区优先，区内排序稳定，缺失值恒后置 | SQL 排序注册表、版本化游标 | 八列双向排序、同值、空值、跨页测试 |
| 性能预算前置原则 | 分组最多 10，列表默认 100/最大 200，批量最多 200 | 索引、集合 SQL、游标分页、无 N+1 | PostgreSQL EXPLAIN、P95、payload 实测 |
| 可观测与异常标准化原则 | 用户可修复冲突和系统失败使用不同 `WL_*` 错误码 | Policy/Service/API 错误映射 | 400/404/409/422/500 与回滚测试 |
| 测试以用户可见结果为中心原则 | 测试最终 Tab、数量、选择、排序和按钮状态，不只测内部调用 | 真实后端路由、前端页面和浏览器 smoke | 首页、自选页、详情页三条端到端链 |

## 2. 当前代码审计

本节保留开发前的 v1 审计快照，用于说明替换依据；并非当前后端状态。当前实现及旧后端清退证据见 LLD 第 22 节。

### 2.1 后端现状

| 当前能力 | 真实代码落点 | 当前语义 | v2 处理 |
|---|---|---|---|
| ORM | `src/biz/models/wealth/watchlist_item.py` | `user_id + ts_code` 唯一 | 由分组表和成员表彻底替代 |
| 查询 | `src/biz/queries/wealth/market/watchlist/watchlist_query.py` | 按用户、成员 `id ASC` 分页后关联同日行情 | 改为按 `group_id` 查询，并支持置顶与八列排序 |
| 查询编排 | `watchlist_query_service.py` | 列表、summary、全局 membership、全局搜索状态 | 拆为分组元数据、分组列表、组内搜索、单股分组归属 |
| 写服务 | `watchlist_command_service.py` | 单股全局添加/删除，服务内 commit/rollback | 改为分组 CRUD、单股组内添加和批量原子动作 |
| API | `src/biz/api/wealth/market/watchlist.py` | 列表、summary、search、membership、PUT、DELETE 共 6 个合同 | 保留前缀与 summary，其他合同按 v2 资源重建 |
| Schema | `src/biz/schemas/wealth/market/watchlist.py` | 单列表 DTO、整数 `nextCursor` | 增加 group/member/mark/rules；游标改为不透明字符串 |
| 迁移 | `20260903_000169_add_wealth_watchlist_item.py` | 创建当前单表；当前真实 Alembic head 为 `20260903_000169` | 新迁移开工前再次核验 head，再做一次性结构转换 |
| 鉴权 | 所有 watchlist 路由使用 `require_authenticated` | 用户 ID 只能来自登录身份 | 保持不变；所有 group/member 查询都追加所有者验证 |

当前 `WatchlistQueryService.get_page()` 先读取一批成员 ID，再关联行情。该结构只能支持加入顺序，不能正确支持“对当前组全部股票按行情数值排序”。v2 必须把排序表达式和分页条件下推到完成行情关联后的同一条查询中。

### 2.2 前端现状

| 当前能力 | 真实代码落点 | v2 缺口 |
|---|---|---|
| 页面 | `wealth/src/pages/watchlist/WatchlistPage.tsx` | 只有一个 Panel，没有 Tab 和编辑态 |
| 表格 | `features/watchlist/ui/WatchlistTable.tsx` | 有行内“移除”操作列，不支持颜色条、选择列和表头排序 |
| 控制器 | `features/watchlist/model/useWatchlistController.ts` | 只管理一个列表、整数游标、单股增删队列 |
| 添加弹窗 | `AddWatchlistDialog.tsx` | 搜索状态判断的是全局是否已添加 |
| 详情页 | `useStockWatchlist.ts`、`StockInfoRail.tsx` | “+自选”直接写入；“已自选”置灰不可点 |
| 首页数量 | `useWatchlistSummary.ts`、`MarketOverviewPage.tsx` | 独立请求 summary，具备局部失败隔离 | 路径和组件可复用，只改后端计数语义 |
| API 防线 | `watchlistApi.ts` | 手写运行时响应校验，当前只接受 v1 DTO | 必须随 v2 DTO 一次性替换，不能宽松接受两套形状 |

### 2.3 现有测试资产

当前已有并应继续复用的测试层：

1. SQLite ORM 约束和 model registry 测试。
2. PostgreSQL 真实迁移、并发幂等、EXPLAIN 和响应耗时测试。
3. FastAPI 真实路由、身份隔离、行情同日合同、搜索资格和回滚测试。
4. 前端 API 运行时合同、Controller 请求竞争、列表状态、添加弹窗、首页数量和股票详情页测试。

v2 不另起一套测试框架；在这些真实测试入口上替换旧单列表断言并增加分组场景。

### 2.4 CodeGraph 影响面

本轮以仓库根 `/Users/congming/github/goldenshare` 为索引根，使用了 `codegraph_explore`、`codegraph_search`、`codegraph_callers` 和 `codegraph_impact`，覆盖：

1. `WealthWatchlistItem -> WatchlistQuery -> WatchlistQueryService/CommandService -> watchlist API`。
2. watchlist API 在 `src/app/api/v1/router.py` 的组合入口。
3. `watchlistApi -> useWatchlistController -> WatchlistPage/WatchlistTable`。
4. `addWatchlistItem -> useStockWatchlist -> StockInfoRail/StockDetailPage`。
5. `fetchWatchlistSummary -> useWatchlistSummary -> MarketOverviewPage`。
6. `AppUser` 的注册、管理员创建和命令行创建入口，用于默认分组初始化设计。
7. 后端 ORM/API/PostgreSQL 测试与前端页面/API/Controller/详情页/首页测试。

未发现 `foundation -> biz` 反向依赖、`ops` 消费者或 `qtf` 消费者。本方案只形成 `src.app -> src.biz` 的组合调用和 `src.biz -> src.foundation` 的既有行情读取，不改变依赖矩阵。

## 3. 目标领域模型与持久化

### 3.1 分组表

新增 `app.wealth_watchlist_group`：

| 字段 | 类型 | 约束 | 语义 |
|---|---|---|---|
| `id` | bigint | PK，自增 | 分组稳定身份；同一用户内 `id ASC` 即创建顺序 |
| `user_id` | integer | not null，FK `app.app_user.id`，cascade delete | 分组所有者 |
| `name` | text | not null | NFC + 统一 trim 后的展示名称，业务长度由后端字素簇校验 |
| `is_default` | boolean | not null，默认 false | 默认分组身份；不能由名称推断 |
| `color` | varchar(7) | nullable | 默认组必须为空；自定义组必须来自固定色板 |
| `created_at` | timestamptz | not null | 展示与审计时间；不作为排序键 |
| `updated_at` | timestamptz | not null | 改色更新时间 |

约束：

1. 只存 NFC + trim 后的 `name`，同时用于展示和重名判断；`UNIQUE(user_id, name)` 的约束名为 `uq_wealth_watchlist_group_user_name`，不另存重复规范化键。
2. 每个用户通过部分唯一索引保证最多一个 `is_default=true` 的分组。
3. 默认组固定名称“我的自选”、`color is null`。
4. 自定义组 `name` 不能等于“我的自选”，且 `color` 必须属于固定八色。
5. 名称 1～6 个用户可见字符按扩展字素簇计数，NFC、trim 字符集合与测试向量见 LLD 第 7.2 节。不额外限制为字母/数字白名单；普通标点可以使用。数据库不以 `length <= 6` 或短 varchar 冒充同一校验。
6. 不增加 `position` 字段；分组创建顺序由不可复用的 `id` 确定。
7. 默认组保护分工：数据库保证最多一个默认组及合法身份属性；迁移/用户开通保证至少一个；Service 禁止默认组删除、改名和改色。不新增删除保护触发器，删除用户时仍允许级联清理。

### 3.2 成员表

新增 `app.wealth_watchlist_membership`：

| 字段 | 类型 | 约束 | 语义 |
|---|---|---|---|
| `id` | bigint | PK，自增 | 当前分组内成员稳定身份和最终排序 tie-break |
| `group_id` | bigint | not null，FK group，cascade delete | 所属分组 |
| `ts_code` | varchar(16) | not null | 股票代码 |
| `is_pinned` | boolean | not null，默认 false | 仅对当前成员关系生效 |
| `created_at` | timestamptz | not null | 加入记录的展示与审计时间，不参与基础排序 |
| `updated_at` | timestamptz | not null | 置顶状态更新时间 |

约束与索引：

1. 唯一约束 `(group_id, ts_code)`，保证同一股票在同一组中只出现一次。
2. 索引 `(group_id, is_pinned, id)` 支持默认列表和组内写入。
3. 索引 `(ts_code, group_id)` 支持单股归属和行颜色条集合查询。
4. 成员表不重复保存 `user_id`；所有权只从分组表得出，避免两个所有者字段漂移。
5. 不保存行情、分组色、排序字段快照或前端位置。

### 3.3 基础顺序和置顶

1. 未置顶区默认按 membership `id ASC`。
2. 置顶区默认按 membership `id DESC`，符合“后加入当前组的在前”。这里的 ID 是成员关系流水号，不是股票代码。
3. 同组新增成员在组锁内分配不可复用的 ID，ID 允许跳号；同一批新增成员按源 membership ID 升序分配目标关系 ID，详情页多目标按 group ID 升序处理。
4. 置顶、取消置顶只修改 `is_pinned` 和 `updated_at`，不修改 ID 或 `created_at`，因此取消置顶后能回到原基础位置。
5. 移动或添加到目标组时，新建关系获得新 ID；目标已存在时按幂等成功处理，保留原 ID、时间和置顶状态。不区分新旧用户使用两套排序算法。

### 3.4 默认分组生命周期

1. 迁移时为 `app.app_user` 中每个现有用户创建一个默认组，而不是只为已有自选的用户创建。
2. 新用户创建事务在取得 `user.id` 后、commit 前写入默认组，用户和默认组同成同败。
3. 组合入口覆盖公开注册、管理员创建和 `src/scripts/create_user.py`；三条入口统一改走 `src/app/user_provisioning_service.py`，不得继续直接创建 `AppUser`。
4. 用户删除先由现有 FK 删除分组，再级联删除成员。
5. 业务查询不通过 GET 请求懒创建默认组，不引入“读请求发生写入”的隐藏行为。
6. 查询发现默认组缺失时返回明确异常，不把缺失视为空组，也不现场补造。

### 3.5 历史数据迁移

迁移必须在一个受控发布窗口内完成：

1. 开工前再次执行 `alembic heads`；新迁移的 `down_revision` 只能连接执行当时的真实 head。本文记录的当前 head `20260903_000169` 不是未来编码时的替代证据。
2. 创建分组表，为全部现有用户插入默认组。
3. 创建成员表，把 `wealth_watchlist_item` 的每行映射到所属用户的默认组。
4. 保留旧 `id`、`ts_code`、`created_at`、`updated_at`，并写入 `is_pinned=false`；随后校准新表序列。
5. 用旧表与新表默认组做双向数量、用户—股票集合对账；另按用户比较旧 `id ASC` 与新 membership `id ASC` 的完整有序序列，覆盖 ID 与时间戳先后不一致的样本。任一不一致必须让迁移失败并回滚。
6. 对账成功后删除旧表；代码中删除 `WealthWatchlistItem` 和旧模型模块，不保留别名。
7. downgrade 只能在 v2 尚未开放新写入前使用；一旦产生自定义组或多组关系，旧单表无法无损表达，生产回退必须走前向修复方案。

## 4. 分层架构与目录落点

```text
src/biz/
  models/wealth/
    watchlist_group.py
    watchlist_membership.py
  api/wealth/market/
    watchlist.py
  schemas/wealth/market/
    watchlist.py
  queries/wealth/market/watchlist/
    watchlist_group_query.py
    watchlist_item_query.py
    watchlist_query_service.py
  services/wealth/market/watchlist/
    watchlist_policy.py
    watchlist_cursor.py
    watchlist_group_initializer.py
    watchlist_command_service.py
    watchlist_field_mapper.py

src/app/
  user_provisioning_service.py
  model_registry.py

wealth/src/features/watchlist/
  api/
    watchlistApi.ts
    watchlistApiTypes.ts
  model/
    useWatchlistGroupsController.ts
    useWatchlistItemsController.ts
    useWatchlistEditController.ts
    useStockWatchlistGroups.ts
    watchlistViewModelAdapter.ts
  ui/
    WatchlistTabs.tsx
    WatchlistTable.tsx
    WatchlistEditToolbar.tsx
    CreateWatchlistGroupDialog.tsx
    WatchlistGroupTargetDialog.tsx
    ConfirmWatchlistRemoveDialog.tsx
    ConfirmWatchlistGroupDeleteDialog.tsx
    ChangeWatchlistGroupColorDialog.tsx
    StockWatchlistGroupPicker.tsx

wealth/src/pages/watchlist/
  WatchlistPage.tsx
  watchlist-page.css
```

职责边界：

1. `Policy` 是名称、颜色、数量、批量上限、股票代码和排序字段的唯一业务规则入口。
2. `Cursor` 只负责编解码和验证版本化游标，不查询数据库。
3. `GroupQuery` 读取用户私有分组、数量和单股归属。
4. `ItemQuery` 负责当前组成员、统一交易日行情、颜色标记和排序分页。
5. `QueryService` 组合页面上下文、数据状态和 DTO，不执行写入。
6. `CommandService` 持有写事务，统一做所有权校验、行锁、幂等、commit 和 rollback。
7. `src.app.user_provisioning_service` 只编排 `AppUser` 创建和 Biz 默认组初始化，不承载 watchlist 规则；`src.app.auth` 继续只做认证、授权和用户入口校验。
8. 前端 Controller 管请求、竞争和页面状态；组件只渲染和上报用户意图。

## 5. API 合同

统一前缀：`/api/v1/wealth/market/watchlist`。所有接口继续使用 `require_authenticated`。

所有分组/成员 ID 在请求、响应和 cursor 中统一为 `1..9007199254740991` 的安全正整数；数据库仍为 bigint，前端仍为 number。JSON ID 及数组元素使用 StrictInt 加上下界，拒绝 bool、数字字符串、浮点数及超界值，结构错误沿用 `422 / validation_error`；URL 的十进制整数显式解析后校验同一范围。`extra="forbid"` 不能代替严格类型检查。响应 ID 在提交前构造 DTO 时验证，前端使用 `Number.isSafeInteger`；不新增 BigInt 传输或兼容合同。

### 5.1 分组元数据

```http
GET /api/v1/wealth/market/watchlist/groups
```

响应：

```json
{
  "groups": [
    {
      "id": 11,
      "name": "我的自选",
      "isDefault": true,
      "color": null,
      "memberCount": 18,
      "createdAt": "2026-09-07T08:00:00Z"
    }
  ],
  "rules": {
    "maxGroups": 10,
    "maxCustomGroups": 9,
    "nameMaxVisibleChars": 6,
    "nameMaxUtf8Bytes": 1024,
    "maxBatchMemberships": 200,
    "palette": [
      "#F7C76B", "#5AA7FF", "#A78BFA", "#2DD4BF",
      "#FB923C", "#F472B6", "#A3E635", "#22D3EE"
    ]
  }
}
```

规则：

1. 默认组永远第一；自定义组按 `id ASC`。
2. `memberCount` 是各组独立数量，同一股票在多个组中分别计数。
3. 前端色板和上限直接消费 `rules`，不得另写一份可漂移的业务常量。

### 5.2 创建、改色和删除分组

```http
POST   /api/v1/wealth/market/watchlist/groups
PATCH  /api/v1/wealth/market/watchlist/groups/{groupId}/color
DELETE /api/v1/wealth/market/watchlist/groups/{groupId}
```

请求：

```json
{ "name": "新能源", "color": "#5AA7FF" }
```

```json
{ "color": "#A78BFA" }
```

创建和改色均返回 `{ "group": WatchlistGroupDto }`，group 含完整元数据及 `createdAt`。删除返回：

```json
{
  "deletedGroupId": 14,
  "deletedMemberCount": 23,
  "nextGroupId": 15
}
```

`nextGroupId` 由后端在删除事务内、取得默认组锁并重新读取和锁定其余组之后，按当前用户分组顺序计算：右侧有分组时返回右侧相邻组；当前组是最右侧时返回默认组。默认组的改色和删除均拒绝。

本期不提供名称 PATCH/PUT 路由。

### 5.3 当前分组行情列表

```http
GET /api/v1/wealth/market/watchlist/groups/{groupId}/items
  ?limit=100
  &cursor=
  &tradeDate=
  &sortBy=changePct
  &direction=desc
```

`sortBy` 可选值：

```text
price | changePct | vol | peTtm | pb | volumeRatio | turnoverRate | netAmount
```

规则：

1. 不传 `sortBy/direction` 表示默认顺序。
2. 传入 `sortBy` 时 `direction` 只能为 `desc|asc`。
3. `limit` 默认 100、范围 `1..200`。
4. `cursor` 是版本化不透明字符串；整数 `afterId` 合同删除。
5. `tradeDate` 和行情状态沿用 v1 的 `MarketPageContext` 合同。

响应主结构：

```json
{
  "group": {
    "id": 12,
    "name": "新能源",
    "isDefault": false,
    "color": "#5AA7FF",
    "memberCount": 23,
    "createdAt": "2026-09-07T08:00:00Z"
  },
  "pageContext": {},
  "dataStatus": {},
  "items": [
    {
      "membershipId": 101,
      "addedAt": "2026-09-07T08:00:00Z",
      "isPinned": true,
      "groupMarks": [
        { "groupId": 12, "name": "新能源", "color": "#5AA7FF" }
      ],
      "stock": {},
      "quote": {},
      "valuation": {},
      "activity": {},
      "moneyFlow": {},
      "missingFields": []
    }
  ],
  "totalCount": 23,
  "nextCursor": "opaque-v1-token"
}
```

`groupMarks` 只包含该股票所属的自定义分组，按分组创建顺序排列；同色分组分别返回，默认组不返回颜色标记。

### 5.4 当前组搜索和单股添加

```http
GET /api/v1/wealth/market/watchlist/groups/{groupId}/search?keyword=PAYH&limit=8
PUT /api/v1/wealth/market/watchlist/groups/{groupId}/items/{tsCode}
```

1. 搜索继续复用当前上市 A 股候选池和排序。
2. `AVAILABLE|ADDED` 只相对当前组计算；股票只在其他组时仍是 `AVAILABLE`。
3. PUT 对当前组幂等，目标已存在返回 `created=false`。
4. 仅在目标关系缺失、需要新增时复检当前上市 A 股资格，不能信任搜索结果；已有关系即使后来退市仍返回幂等成功，不改 ID、时间或 pin。
5. 添加成功后前端重新加载当前组首批；存在数值排序时由数据库把新成员放入正确位置。
6. 搜索响应固定为 `{groupId, keyword, items}`，groupId 必填且与请求组相等；前端同时检查 generation。缺字段、非法 ID 或请求组不匹配作为查询合同错误，过期响应直接丢弃；不得兼容 v1 无 groupId 响应或在前端补造字段。

### 5.5 编辑态批量动作

```http
POST /api/v1/wealth/market/watchlist/groups/{groupId}/actions/move
POST /api/v1/wealth/market/watchlist/groups/{groupId}/actions/add-to-groups
POST /api/v1/wealth/market/watchlist/groups/{groupId}/actions/remove
POST /api/v1/wealth/market/watchlist/groups/{groupId}/actions/pin
POST /api/v1/wealth/market/watchlist/groups/{groupId}/actions/unpin
```

请求示例：

```json
{ "membershipIds": [101, 102], "targetGroupId": 13 }
```

```json
{ "membershipIds": [101, 102], "targetGroupIds": [13, 14] }
```

通用规则：

1. `membershipIds` 必须为 1～200 个去重正整数，并且当前仍全部属于 URL 中的当前组。
2. 移动目标是单个；添加目标是一个或多个；当前组不能出现在目标中。
3. 目标分组必须全部属于当前用户。
4. 服务按 group ID 升序锁定涉及的分组，避免并发批量操作形成死锁。
5. 添加使用集合 INSERT + 唯一约束收敛重复；移动在同一事务中先确保目标存在，再删除源关系。
6. 任一成员已被其他会话移出时整批拒绝为 stale selection，不允许静默只操作剩余部分。
7. 每个请求只 commit 一次；提交前完成 flush、实际计数和返回 DTO 构造，提交后不回读。事务保持原子性；客户端是否已经获知结果按第 7.5 节区分。
8. 成功统一返回 `action`、`requestedCount`、`createdCount`、`removedCount`、`updatedCount` 和涉及分组的最新数量；各计数含义由 LLD 冻结，前端不得从本地选择数反推数据库结果。
9. 前端清空选择并重新加载当前组，但保持编辑态。
10. move/add-to-groups 先计算实际缺失目标关系，仅对这些关系涉及的股票一次集合复检资格；任一不合格整批失败，移动不得先删除源关系。仅保留/移除已有关系不被资格校验阻挡。

### 5.6 股票详情页分组归属

```http
GET /api/v1/wealth/market/watchlist/stocks/{tsCode}/groups
PUT /api/v1/wealth/market/watchlist/stocks/{tsCode}/groups
```

GET 一次返回按正确顺序排列的全部分组及 `selected` 状态：

```json
{
  "tsCode": "000001.SZ",
  "isAdded": true,
  "groups": [
    {
      "groupId": 11,
      "name": "我的自选",
      "isDefault": true,
      "color": null,
      "selected": false
    }
  ]
}
```

PUT 请求使用最终集合语义：

```json
{ "groupIds": [12, 14] }
```

规则：

1. `groupIds` 必须为 1～10 个当前用户分组，不能为空。
2. 服务在一个事务中计算 diff：新增新勾选关系、删除取消勾选关系、保留未变化关系。
3. 股票不自动加入默认组；最终集合中没有默认组就不创建默认组关系。
4. 空集合由后端拒绝，与前端置灰共同保证详情页不能移除最后一个归属。
5. 成功返回最终 `groupIds` 和 `isAdded=true`；取消、点外部或 Escape 不调用 PUT。
6. 先计算 diff，仅 to_add 非空时校验当前上市 A 股资格；仅保留或减少既有归属时不复检。若新增资格失败，整次 diff 回滚。

### 5.7 首页数量

```http
GET /api/v1/wealth/market/watchlist/summary
```

路径和 `{ "totalCount": number }` 响应保持不变。查询只统计认证用户默认分组成员；自定义组和“属于任意组”的去重股票数都不参与首页徽标。

### 5.8 删除的 v1 合同

以下 v1 合同不再保留：

1. `GET /watchlist`。
2. `GET /watchlist/search`。
3. `GET /watchlist/items/{tsCode}`。
4. `PUT /watchlist/items/{tsCode}`。
5. `DELETE /watchlist/items/{tsCode}`。

v2 前端不得继续调用这些路径；后端不得以别名或适配器继续提供旧语义。

## 6. 查询、排序与游标

### 6.1 查询主链

1. 按 `user_id + group_id` 校验当前组所有权并取得组元数据。
2. 由 `MarketPageContextQuery` 得到 `expectedTradeDate`。
3. 空组返回完整上下文和 EMPTY，不执行行情查询；非空组沿用 v1 规则解析全页唯一 `observedTradeDate`。
4. 从当前组成员出发，一次左连接证券、日行情、每日指标和资金流。
5. 在数据库完成置顶分区、数值排序、缺失后置、稳定 tie-break 和 `limit + 1` 截断。
6. 对最终本批股票集合查询其全部自定义分组标记并按 group ID 聚合；禁止逐行查询颜色。
7. FieldMapper 只做 DTO 映射，不改变排序和颜色顺序。

### 6.2 排序注册表

后端建立固定白名单，把 API 的八个 `sortBy` 映射到已有数值列；严禁把客户端字段名直接拼入 SQL。

| sortBy | 数据字段 |
|---|---|
| `price` | `equity_daily_bar.close` |
| `changePct` | `equity_daily_bar.pct_chg` |
| `vol` | `equity_daily_bar.vol` |
| `peTtm` | `equity_daily_basic.pe_ttm` |
| `pb` | `equity_daily_basic.pb` |
| `volumeRatio` | `equity_daily_basic.volume_ratio` |
| `turnoverRate` | `equity_daily_basic.turnover_rate` |
| `netAmount` | `equity_moneyflow.net_mf_amount` |

统一排序键：

1. 第一键：`is_pinned DESC`。
2. 数值排序第二键：数值是否缺失，非空在前、空值在后。
3. 数值排序第三键：目标数值按请求方向。
4. 同值稳定键：置顶区用 membership `id DESC`；未置顶区用 membership `id ASC`。
5. 默认排序没有数值键，直接使用第一键和对应分区的 membership ID 顺序，`created_at` 不参与排序。

因此，数值排序下取消置顶会把成员放入未置顶区的正确数值位置；默认排序下会回到原加入位置。

### 6.3 版本化游标

`nextCursor` 改为不透明字符串，至少绑定：

1. 游标版本。
2. `groupId`。
3. `sortBy/direction` 或默认排序标记。
4. `observedTradeDate`。
5. 最后一行的置顶分区、缺失标记、排序数值和 `membershipId`；不携带创建时间。

要求：

1. 游标字段经过严格解码和类型校验；游标与本次 group/sort/date 不一致时返回 `WL_CURSOR_INVALID`。
2. Decimal 排序值以无损字符串编码，不转成浮点数。
3. 下一页使用与 ORDER BY 完全同构的 seek predicate，不使用 offset。
4. 行情实际日期变化时，后续页拒绝拼接，前端清空旧列表并从首批重载，继续沿用 v1 的日期一致性行为。
5. 任何排序切换和 Tab 切换都取消旧请求、清空旧游标和列表，再加载目标首批。
6. 跨页无重复/遗漏以成员、pin 和排序行情值不变为前提；本页写成功清空 cursor，保持当前排序从首批重载。其它会话修改或同日行情原地更新可能越过旧 cursor，用户刷新后重新收敛；日期绑定不是跨请求快照，前端去重不能补漏。本期不新增快照表、版本缓存或实时订阅。

## 7. 写事务与并发控制

### 7.1 分组创建

1. 锁定当前用户的默认分组行，作为 watchlist 域内的用户级创建互斥点；禁止为了加锁让 `src.biz` import `src.app.models.AppUser`。
2. 读取当前自定义组数；达到 9 时返回上限冲突。
3. 后端规范化名称并校验固定色板。
4. 唯一约束处理同名并发；重复名称返回业务冲突而不是 500。
5. 插入后 flush、查询真实数量并构造 DTO，再一次 commit；直接返回已构造 DTO，不在提交后访问 ORM 属性触发回读。

### 7.2 删除分组

1. 先独立锁定当前用户默认组，再读取并按 ID 升序锁定该用户其余分组；创建和删除都遵守这一入口，避免拿到过期组清单。校验当前组所有权及 `is_default=false`。
2. 在锁定的分组清单中计算右侧相邻组；没有右侧时选择默认组。
3. 统计成员数。
4. 显式删除成员，再删除组；FK cascade 只作为完整性兜底。
5. 两步执行后在提交前构造包含删除数量和 `nextGroupId` 的 DTO，一次 commit 后直接返回。

### 7.3 批量动作

1. 按 ID 排序锁定当前组和全部目标组。
2. 一次查询并锁定选中成员；要求返回数量与请求去重数量完全一致。
3. 统一先锁组、再锁成员；使用集合 SQL，不按股票循环 commit。新成员 ID 必须在目标组锁内分配。
4. move/add-to-groups 锁内读取已有目标关系，求出缺失关系后一次查询校验待新增股票资格；最多 1800 个候选关系、200 只股票。无新增则跳过资格查询；任一不合格整批回滚，已有目标成员顺序和置顶不变。
5. pin/unpin 只更新当前组成员。
6. remove 只删除当前组关系；即使成为零归属也允许，这是自选页的明确能力。
7. 单股添加、move/add-to-groups 和详情新增统一使用 CommandService 内部 `_insert_missing_memberships`。PostgreSQL 只忽略 `uq_wealth_watchlist_membership_group_stock` 冲突，SQLite 使用同一唯一列；`RETURNING id` 产出真实新增数。helper 不 commit、不建 savepoint、不做资格校验；不沿用 v1 nested transaction 分支，不吞 FK/check 等其它错误。

### 7.4 详情页最终集合

1. 先锁默认组，再读取并按 ID 升序锁定其余分组，避免提交过程中分组清单发生变化。
2. 验证请求集合非空且全部归属当前用户。
3. 加载现有归属并计算 diff；仅实际 to_add 非空时验证股票仍是当前上市 A 股，既有关系的保留/移除不复检。
4. 用一组 INSERT 和一组 DELETE 应用 diff；flush、构造最终集合及实际计数 DTO，再一次 commit 并直接返回。
5. 提交前失败回滚并保留输入；提交结果未知按下一节处理，不能声称已经回滚。

### 7.5 写结果与刷新结果分离

1. 明确未提交且已回滚：使用业务错误或 `WL_WRITE_FAILED`，保留输入、选择并允许用户重试。
2. 提交已成功且收到合法成功响应：按成功处理并清选择；后续刷新失败单独提示“操作已成功，列表刷新失败”，只重试 GET，不重放写请求。
3. 提交期间连接中断等无法判断最终结果：后端尽可能返回 `503 / WL_WRITE_OUTCOME_UNKNOWN`；rollback 只能清理 Session，不能当作服务器未提交的证据。
4. 前端写请求超时、响应丢失、成功响应无法解析，或收到无法证明回滚的错误时，标记“结果未知”。先重新读取真实组清单、成员或股票归属；读成功后允许用户基于最新状态重新操作，不自动重放原请求，不把一次 GET 当成原请求成功证明。
5. 结果未知且回读失败时只提供读取重试，保留上下文并禁止原动作一键重试。本期不引入请求幂等键、任务队列或跨端自动合并。

## 8. 前端交互状态落地

### 8.1 页面控制器

页面状态拆为三层：

1. Groups Controller：分组列表、规则、当前组、创建、改色和删除后的 Tab 决策。
2. Items Controller：当前组行情、排序、游标加载、日期一致性和单股 `addToCurrentGroup` 提交及写后重载。
3. Edit Controller：展示/编辑模式、已加载成员选择、动作弹层；只提交 move/add-to-groups/remove/pin/unpin，组级改色/删除调用 Groups，不重复持有其写状态。

另保留现有 Search Controller，按 groupId/open/keyword 隔离请求与 ADDED 状态；不新增第五个通用控制器。Page 把 Items 的单股添加入口和动作派生状态传给 AddWatchlistDialog，删除旧 `appendAddedItem/pendingCodes/memberships` 接线。搜索切组/关闭/关键词变化时取消旧读并校验 generation；成功提示“已添加到「分组名」”，不能再提示或执行末尾追加。成功后 Page 协调 groups 与当前排序首批各刷新一次，Search 自己刷新一次；旧组响应不得污染新组。

每个写动作只有一个所有者、一个带动作上下文/结果/错误的判别联合：idle/pending/succeeded/failed/unknown。pending 等 UI 状态由它派生，不并存重复的 pendingAction、writeOutcome 或 reconcilePending。读取 loading/error 独立保留以表达“写成功但刷新失败”；只共享必要类型，不建立通用框架或队列。单股结果未知还需回读搜索归属；搜索未包含目标时复用 stock-groups GET，不能凭首批缺行判断未添加。所有必要回读完成才恢复基于当前事实的操作，不自动重放 PUT。

边界：

1. 路由仍为 `/wealth/market/watchlist`，不保存 groupId；首次进入、刷新和从首页进入都选择默认组。
2. 切换 Tab 先取消旧请求，再清空排序和选择，目标组按默认顺序加载。
3. 编辑态冻结进入时的当前 groupId；其他 Tab 和“+ 新建分组”不可点击。
4. 写成功清空选择、保持编辑态并重新读取真实列表；“完成”只退出编辑态。
5. 当前组被其他会话删除时，刷新分组并回到默认组，不保留失效选择。
6. 选择达到 `rules.maxBatchMemberships` 后，只禁止新增选择并提示“单次最多选择 200 只”；始终允许取消已选、加载更多和浏览。加载更多不是切换分页，不清除已选；只允许选择已加载行，不提供未加载数据选择。

### 8.2 表格

1. 删除现有最右“操作”列及所有行内移除代码。
2. 展示态最左为颜色标记区，之后保持现有股票身份列和行情列。
3. 编辑态颜色标记仍最左，复选框列位于颜色区右侧；表头不渲染全选框。
4. 展示态整行进入详情；编辑态整行只切换该 `membershipId` 的选择。
5. 数值表头使用按钮和 `aria-sort` 表达未排序、降序、升序。
6. 首次点击新列请求 `desc`，再次点击同列切换方向。
7. 颜色段按 `groupMarks` 顺序等分行高；相同颜色不合并；每段使用独立 tooltip/可访问名称显示组名。
8. 编辑态保留面板原头部、组名、数量和数据日期；“添加自选”禁用，“操作”显示“编辑中”；原头部下方、表头上方追加 52px 操作栏，完成后恢复原头部按钮，不以操作栏替换头部。

### 8.3 弹层

1. 创建和改色共用同一份后端 palette 数据，但保持两个明确业务组件。
2. 移动和添加到分组复用目标选择组件，通过单选/多选模式区分；当前组不出现在目标列表。
3. 移出本组和删除分组使用独立确认弹窗，分别显示股票数和组内成员数。
4. 写请求期间锁定提交交互，防止重复提交；明确回滚的失败保留弹层和输入。结果未知、写后刷新失败分别执行第 7.5 节，不统一显示“操作失败”。

### 8.4 股票详情页

1. `useStockWatchlist` 由 `useStockWatchlistGroups` 替代，不再暴露直接 `add()`。
2. 初始化 GET 决定按钮文案；每次打开选择器重新 GET 最新分组和归属，成功后才建立 draft，不能直接使用初始化缓存预选。
3. “已添加”保持可点击。
4. 选择器以按钮为锚点向下展开，行数随 1～10 个实际分组增长，不设内部滚动。
5. 本地 draft 与服务器 committed 集合分离；取消、点外部和 Escape 只丢弃 draft。
6. 刷新中、刷新失败或 draft 为空时确认置灰；读取失败在弹层内重试。关闭或换股票取消旧 GET，旧响应不得重新打开弹层。
7. draft 建立后不使用后台刷新覆盖用户勾选；成功后以 PUT 响应覆盖 committed 集合并关闭。仍按最终集合提交，不新增实时订阅或多端自动合并；写失败/未知按第 7.5 节处理。
8. Detail 独占最终集合 PUT 的 mutation；读取 status 不再含 saving，saving 从 mutation.pending 派生。committed/draft 继续分离，不另存同义写状态。

### 8.5 首页

首页 `useWatchlistSummary`、入口路径和错误隔离逻辑保持不变。只调整测试 fixture，证明自定义组变化不影响徽标，默认组变化才影响徽标。

## 9. 状态、错误与安全

### 9.1 页面数据状态

`pageContext`、`dataStatus` 和 `missingFields` 继续沿用 v1：

1. 当前组无成员：`EMPTY`，不查询行情事实表。
2. 有成员但没有行情日期：身份仍返回，模块为 `PARTIAL`。
3. `observedTradeDate < expectedTradeDate`：至少 `DELAYED`。
4. 同日字段缺失：`PARTIAL` 优先，不跨日期回填，不补零。
5. SQL/DTO 失败：返回 `WL_QUERY_FAILED`，前端不展示 mock 行情。

### 9.2 错误码

| HTTP | code | 场景 |
|---:|---|---|
| 400 | `WL_REQUEST_INVALID` | 名称、颜色、排序、批量参数非法 |
| 400 | `WL_CURSOR_INVALID` | 游标损坏或与 group/sort/date 不匹配 |
| 404 | `WL_GROUP_NOT_FOUND` | 分组不存在或不属于当前用户 |
| 409 | `WL_GROUP_NAME_CONFLICT` | 规范化后同名 |
| 409 | `WL_GROUP_LIMIT_REACHED` | 已有 9 个自定义组 |
| 409 | `WL_DEFAULT_GROUP_IMMUTABLE` | 尝试删除、改色或作为可变对象操作默认组 |
| 409 | `WL_SELECTION_STALE` | 选中成员已不再全部属于当前组 |
| 422 | `WL_TARGET_GROUP_INVALID` | 目标包含当前组、重复、为空或越权 |
| 422 | `WL_MEMBERSHIP_REQUIRED` | 详情页最终分组集合为空 |
| 422 | `WL_STOCK_NOT_ELIGIBLE` | 不是当前上市 A 股 |
| 500 | `WL_QUERY_FAILED` | 未预期查询失败 |
| 500 | `WL_WRITE_FAILED` | 明确未提交且已回滚的未预期写入失败 |
| 503 | `WL_WRITE_OUTCOME_UNKNOWN` | 提交期间通信异常等导致提交结果无法确认；先回读、不自动重放 |

404 不区分“真实不存在”和“属于其他用户”，避免泄露其他用户资源。

### 9.3 鉴权与防误用

1. 所有请求强制登录，不接收请求体中的 `userId`。
2. 每个 groupId 必须与认证用户在同一 SQL 条件中校验。
3. membershipId 必须通过当前组和当前用户反查，不能单独按 ID 更新。
4. 排序字段只允许注册表枚举；SQL 全部使用绑定参数。
5. 请求体使用严格 DTO，拒绝额外字段、重复 ID、超限集合和空集合。
6. 默认组保护按第 3.1 节分工：数据库约束属性及最多一个默认组，初始化保证存在，Service 禁止删除/改名/改色。无需删除触发器；不能只靠按钮置灰，也不能声称 CHECK 会阻止 DELETE。

## 10. 性能与配置审计

### 10.1 性能预算

| 链路 | 预算 |
|---|---|
| groups / summary / 单股分组 GET | P95 `<= 200ms` |
| 当前组首批列表（默认 100） | P95 `<= 300ms`，payload `<= 256KiB` |
| 最大 200 行列表 | P95 `<= 500ms`，payload `<= 512KiB` |
| 搜索 | P95 `<= 200ms`，前端 2s 超时 |
| 单组创建/改色/单股添加 | P95 `<= 300ms` |
| 最大 200 成员、最多 9 目标组批量写 | P95 `<= 800ms`，单事务、常驻内存有界 |

首版不引入缓存：

1. 分组、成员和首页数量属于用户即时写后读数据，Redis 会增加失效复杂度。
2. 行情继续直接读取 serving 表，沿用 v1 查询策略。
3. 分组最多 10；颜色标记使用一次集合查询，禁止 N+1。
4. 完成开发后必须使用真实 PostgreSQL 对默认列表、八种排序代表列、颜色聚合、summary、详情归属和最大批量做 EXPLAIN/耗时验证。

### 10.2 配置项审计

本模块不新增 env、Settings、数据库配置表或运营开关。

| 口径 | 默认值 | 唯一来源与持久化 | 消费者 | 生效方式 | 测试门禁 |
|---|---:|---|---|---|---|
| 分组总上限 | 10 | 后端 `WatchlistPolicy` 常量，API rules 返回 | 后端校验、前端创建态 | 随版本发布 | 9 自定义正反例、并发创建 |
| 名称上限 | 6 可见字符 | 后端 Policy，API rules 返回 | 创建弹窗、后端最终校验 | 随版本发布 | 中英数、trim、边界向量 |
| 名称技术输入保护 | 1024 UTF-8 字节 | 后端 Policy，API `rules.nameMaxUtf8Bytes` 返回 | 分段前原始输入和规范值校验、前端提示 | 随版本发布 | 超长组合符输入；不能代替 1～6 字素簇业务规则 |
| 固定色板 | 8 色固定顺序 | 后端 Policy，API rules 返回 | 创建、改色、颜色条 | 随版本发布 | 非法色、重复色、顺序 |
| 列表批次 | 100/最大 200 | 后端 Policy | API、Items Controller | 请求参数 | 边界与 payload |
| 批量成员上限 | 200 | 后端 Policy，API `rules.maxBatchMemberships` 返回 | 五个批量动作、前端选择控制和提示 | 随版本发布 | 0/1/200/201；达到上限仍可取消/浏览 |
| 搜索防抖 | 500ms | 交互合同、前端常量 | 添加弹窗 | 页面加载 | fake timer |

这些口径不允许散落为互不校验的前后端业务常量；前端展示型规则由 groups API 返回，后端始终具有最终裁决权。

## 11. 测试与验证计划

### 11.1 单元测试

1. 名称 trim、1～6 可见字符、规范化重名键和“我的自选”禁名。
2. 固定八色、重复颜色允许、非法颜色拒绝。
3. group/member ORM 唯一、check、FK cascade 和 model registry。
4. 默认排序和八列数值排序注册表。
5. 游标编解码、版本、Decimal、空值、group/sort/date 绑定。
6. 前端 API 严格 DTO 校验，不接受 v1 或缺字段形状。
7. Groups/Items/Edit/Detail Controller 的取消、竞态、失败保留和写后重载。
8. 名称字素簇与首尾空白共享向量，数据库可以存储通过业务校验的组合字符；算法依赖选型与环境准入见 LLD 第 7.2 节，不擅自安装依赖。

### 11.2 后端真实 API 集成测试

1. 全部路由要求身份，不能通过参数选择其他用户。
2. 每用户恰有一个默认组；新用户三类创建入口都在同一事务生成默认组。
3. 创建第 9 个自定义组成功，第 10 个失败；PostgreSQL 并发创建也不能越过上限。
4. 默认组不能删除、改色或改名；自定义组没有改名路由。
5. 同名、trim 后同名、禁名和名称边界返回确定错误。
6. 同股票可进入多个组，同组重复添加幂等。
7. 组内 search 只按当前组标记 `ADDED`。
8. move 单目标、add 多目标、remove、pin、unpin 的正常、幂等、越权和 stale selection。
9. 为批量服务注入中途失败，证明成员和计数全部回滚。
10. 删除含成员分组只删除本组关系，并返回正确右侧/default `nextGroupId`。
11. 详情页 GET 真实预选；PUT 精确应用最终非空集合；空集合拒绝且无写入。
12. summary 只统计默认组；自定义组增删不改变首页数量。
13. 颜色标记排除默认组、按创建顺序、同色不合并。
14. 八个数值列均覆盖首次降序、升序、置顶分区、空值后置、同值 tie-break；数据不变时验证跨页无重复无遗漏。外部 pin/同日行情变化测试只保证刷新后恢复当前事实，不承诺跨请求快照。
15. 空组不访问行情表；行情统一日期、DELAYED/PARTIAL 和零值语义继续通过 v1 回归。
16. 创建与删除先取得默认组锁再读取清单；并发创建/删除时组数与 next group 正确；成员分配 ID 发生在组锁内。
17. 所有写方法提交后零 SQL；提交前 DTO 失败回滚；提交结果未知不能伪装为已回滚，也不能自动重放。
18. 所有新增关系入口共测资格与统一插入 helper；已退市的既有关系可保留/移除，新关系不合格整批零变化。JSON 严格 ID 类型、URL/cursor 范围、响应安全整数与迁移超界均有反例，详见 LLD 第 16 节。

### 11.3 迁移验证

1. 在隔离的真实 PostgreSQL 从实际 `down_revision` 对应 fixture 升级到新 head；初稿审计基线为 `20260903_000169`，不能代替编码时核验。
2. 对每个用户验证旧成员数等于新默认组成员数。
3. 用双向集合差验证 `(user_id, ts_code, created_at, id)` 无丢失、无新增、无重复。
4. 验证没有旧自选的用户也获得默认组。
5. 验证成员 sequence 大于迁移后最大 ID。
6. 验证旧表、旧约束、旧索引和旧 ORM 引用全部清零。
7. 逐用户比较完整 `(id, ts_code)` 有序序列，包含时间戳倒序、相同时间、ID 跳号样本；默认排序及 pin/unpin 后顺序均以 ID 为准。
8. 旧成员及新组 ID 必须位于 API 安全整数范围，超界中止，不重排 ID、不删除旧表。

### 11.4 前端用户可见测试

1. Tab 顺序、默认组、当前组数量和“+ 新建分组”文案。
2. 创建、改色、删除及达到上限状态。
3. 展示态无操作列；编辑态有逐行勾选、无表头全选、其他 Tab 不可点。
4. 编辑态整行只勾选，展示态整行进入详情。
5. 移动单选、添加多选、移出/删除确认、成功清空选择并保持或退出正确模式。
6. 置顶/取消置顶和八列排序的请求、图标、`aria-sort`、Tab 切换重置。
7. 多段颜色条等高、按序、同色不合并、悬停提示组名。
8. 详情页“+自选/已添加”都可点；已有归属预选；零选择禁用；取消/点外部/Escape 不写入。
9. 首页仍进入默认组并只显示默认组数量。
10. 第 200/201 次选择边界、上限后取消、加载更多保持已选；详情重复打开重新 GET、读取失败不可提交、过期 GET 被丢弃。
11. 明确回滚、成功后刷新失败、结果未知三种反馈和重试路径不同；结果未知只能先回读，不能一键重放。
12. 单股添加接线、当前组搜索隔离、写后按当前排序重载；一个动作只提交/刷新一次，旧响应不污染新组。搜索响应 groupId 缺失、非法、不匹配均拒绝，groupId 正确但 generation 过期也丢弃。已成功但搜索/列表刷新失败不重发 PUT，未知结果不靠首批缺行推断未添加。

### 11.5 真实前后端与浏览器 smoke

开发完成后的最低验证：

```bash
pytest -q tests/web/test_wealth_market_watchlist_api.py \
  tests/test_wealth_watchlist_model.py \
  tests/test_wealth_watchlist_postgres.py

npm --prefix wealth test -- \
  src/features/watchlist \
  src/pages/watchlist/WatchlistPage.test.tsx \
  src/pages/stock-detail/StockDetailPage.test.tsx \
  src/pages/market-overview/MarketOverviewPage.test.tsx

npm --prefix wealth run typecheck
npm --prefix wealth run build
```

随后启动本地真实 Web + Wealth 前端，以两个用户和至少三个自定义组验证：

1. 用户数据完全隔离。
2. 首页 → 默认组、自选页多 Tab、股票详情页选择器三条链路。
3. create/move/add/remove/pin/unpin/recolor/delete 的真实 network 和 UI 结果。
4. 数据不变时多页排序无重复、无遗漏；本页写后从首批重载，外部变化刷新收敛；请求失败没有假成功或 mock 数据。
5. 浏览器 console 无错误，弹层焦点、Escape、键盘选择和 tooltip 可用。

## 12. 发布、回滚与风险

### 12.1 发布顺序

由于本方案不保留兼容层，必须使用受控的同窗口切换：

1. 合并前完成 LLD、迁移 rehearsal、真实 PostgreSQL 和前端全量验证。
2. 发布窗口暂停旧版本 watchlist 写入。
3. 执行一次性迁移并完成自动对账。
4. 同窗口发布 v2 后端和 v2 前端。
5. 验证 migration head、groups、summary、默认组列表和详情归属后再恢复用户访问。

本次发布前提：用户明确确认当前不会有新注册。本期不为此新增注册开关、排空框架或专门封禁管理员/CLI 的机制，也不将该并发场景列为当前开工阻塞项。迁移后仍做“全部用户恰有一个默认组”的对账；新版本三种用户创建入口仍须正确初始化默认组。若实际发布条件变化，应更新发布安排，而不是临时补写或 GET 懒创建。

不得先让旧前端调用新后端，也不得让新前端依赖旧后端。

### 12.2 主要风险与缓解

| 风险 | 触发条件 | 缓解动作 |
|---|---|---|
| 历史成员迁移丢失 | 用户—股票映射或 sequence 转换错误 | 同事务双向集合和数量对账；失败回滚 |
| 并发越过分组上限/删除后清单过期 | 同用户创建与删除交错 | 创建/删除先锁默认组，再读取清单；其余组按 ID 升序加锁 |
| 批量操作部分成功 | 循环写入或多次 commit | 集合 SQL、一次 commit、故障注入回滚测试 |
| 排序跨页漂移 | 只按数值、缺少 tie-break 或游标未绑定日期 | 完整排序元组、版本化 seek 游标、日期变化重载 |
| 颜色查询 N+1 | 每行单独查所属组 | 对当前页 tsCode 一次集合聚合查询 |
| 首页数量口径污染 | summary 统计全部组或去重股票 | 只解析默认 group ID 后 count membership |
| 详情页过期预选或误清空 | 重复打开使用缓存或空集合提交 | 每次打开重新 GET、前后端非空校验、分组行锁；不做跨端自动合并 |
| 写已成功但提示失败并重试 | commit 后回读或写响应丢失 | 提交前构造 DTO；成功刷新失败只重试读，未知结果先对账不重放 |
| 混合版本不可用 | 迁移与前后端分批发布 | 暂停写入、同窗口切换、不保留兼容路径 |

## 13. 分期里程碑

1. M0：PRD、交互稿、代码审计、技术方案和 LLD；两轮修订及两项准入处理已落档。
2. 开发阶段一：完整后端闭环，包括 ORM、迁移脚本、默认组开通、Policy、DTO、Query/Command、v2 API 和后端测试；这些相互依赖的替换在一个可验收阶段完成。
3. 开发阶段二：前端 API/Controller/组件、首页和股票详情页接入及前端测试。
4. 开发阶段三：真实 PostgreSQL 迁移演练与性能验证、全量回归、浏览器联调和文档对账。
5. 发布：经用户独立授权后才执行生产迁移、部署和生产验收；任何开发阶段都不构成后端单独发布许可。

三个开发阶段分别验收；阶段内部按依赖次序编码，不对删除旧模型但尚未替换消费者的半成品设置独立运行门禁。不得把“方案完成”视为“功能已开发”。

## 14. 待拍板项

用户已确认首轮十项及复审七项修订，无新增产品拍板项。已统一 ID 排序、严格安全整数、新增关系资格和分页边界，并补齐单股接线、简化重复字段/状态及插入路径；逐项对账见 LLD 第 21 节。

名称依赖准入已于 2026-09-08 获用户授权并完成：根 pyproject.toml/uv.lock 固定 `regex==2025.7.34`，仅向现有 `.venv` 新增该包。该版本使用 Unicode 16.0；后端字符类别使用 regex Unicode 属性，不能混用当前 Python unicodedata 15.1 的 category 判断。共享 JSON 的 24 例加 25 个 trim 字符和两例字节边界，共 51 例在 Python、Node 与本机 Chrome 上全部通过。详细版本、命令和验证边界见 LLD 第 21.3 节。

搜索 groupId 合同已统一到第 5.4 节，无新增产品拍板项。后端和前端已分别获开发授权并实现；正式 Policy、API 与隔离数据库验证见 LLD 第 22 节，前端开发自测及未执行验收见第 23 节。完整页面与发布验收仍留给阶段三。其它依赖安装/升级仍须另行报批，不能扩大环境变更范围。

## 15. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v2.6 | 2026-09-08 | 回填第二阶段前端状态；实现与自动化证据集中引用 LLD 第 23 节，停在交互验收之前，未提交或发布前端 | Codex |
| v2.5 | 2026-09-08 | 回填第一阶段后端实现状态；实际迁移链为 000169 → 000170，测试及边界统一引用 LLD 第 22 节；未进入前端或发布 | Codex |
| v2.4 | 2026-09-08 | 同步名称依赖安装/锁定与跨运行时准入证据，冻结搜索 groupId 必填和双重上下文检查；不进入业务编码 | 用户 / Codex |
| v2.3 | 2026-09-08 | 同步 LLD 复审七项：资格、单股接线、安全整数、分页边界、规范化名称单字段、单一写状态及统一插入 helper | 用户 / Codex |
| v2.2 | 2026-09-08 | 落实用户确认的十项修订：统一锁/事务、编辑头部、字素簇名称、三阶段、发布前提、ID 稳定序、批量上限、详情刷新及默认组分层保护 | 用户 / Codex |
| v2.1 | 2026-09-07 | 根据当前代码审计补充 LLD 链接，明确默认组初始化组合层、域内锁和批量返回计数合同 | Codex |
| v2 | 2026-09-07 | 基于已确认 PRD、交互稿和当前代码影响面，形成分组模型、API、排序游标、原子批量操作、迁移、前端状态和验收方案 | Codex |
