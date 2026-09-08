# 财势乾坤｜我的自选分组能力低层设计 v2（LLD）

> 状态：两轮修订已确认；开发准入两项已处理（名称依赖准入、搜索合同勘误）；尚未进入业务代码、数据库迁移、部署或功能验收
>
> 日期：2026-09-08（初稿 2026-09-07）
>
> 产品依据：[我的自选分组能力产品需求文档 v2](./watchlist-grouping-product-requirement-v2.md)
>
> 交互依据：[我的自选分组能力交互设计 v2](./watchlist-grouping-interaction-design-v2.md)
>
> 上层方案：[我的自选分组能力技术实施方案 v2](./watchlist-grouping-implementation-design-v2.md)
>
> Figma：[Watchlist V2 / Interaction Board](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare?node-id=1383-82)

## 0. 结论与开工边界

本文把已确认产品行为和技术方案细化到迁移、ORM、事务、SQL 排序、游标、API DTO、前端状态、逐文件改动和测试门禁。

结论如下：

1. `app.wealth_watchlist_item` 由 `app.wealth_watchlist_group` 和 `app.wealth_watchlist_membership` 一次性替代；迁移后删除旧表、旧 ORM 和五个旧成员接口，不保留双写、别名或兼容 adapter。
2. 默认组是正式分组记录，使用 `is_default` 识别；名称固定为“我的自选”，无颜色，不可删除、改名或改色，但可以正常增删成员。
3. 新用户默认组初始化从上层方案中的 `src.app.auth` 候选落点修正到 `src/app/user_provisioning_service.py`。公开注册、管理员建用户和命令行建用户统一通过组合层服务创建用户与默认组，认证模块不承载 watchlist 规则。
4. 分组创建使用默认组行作为 watchlist 域内的用户级互斥点，不让 `src.biz` import `src.app.models.AppUser`，因此不产生 `biz -> app` 反向依赖。
5. 当前组列表必须先关联统一交易日行情，再在数据库对该组全部成员执行“置顶分区 + 数值方向 + 缺失后置 + 稳定键”排序；禁止前端只排序已加载行。
6. 游标是无签名、版本化、严格校验的 base64url JSON。它不是授权凭证；资源所有权始终由认证用户和 group 条件校验。
7. 所有批量写、详情页最终集合替换和删除分组均为单事务；提交前构造完整 DTO，提交后不回读。数据库修改保持原子性；明确回滚、结果未知、成功后刷新失败分别处理，不能混为一类错误。
8. 首页 `summary` 路径与响应不变，只统计默认组。`useWatchlistSummary`、首页入口和 `MarketShortcutBar` 不需要重写。
9. 用户已确认两轮修订及开发准入两项处理，逐项回填见第 21.1～21.3 节；本次仅处理文档、名称依赖安装/锁定和验证样本，不提交、不进入业务编码。获得后续开发授权后按第 18 节三个完整阶段推进。

初稿代码审计事实快照（2026-09-07；不是本次修订时的 HEAD）：

| 项目 | 审计结论 |
|---|---|
| 工作分支 | `dev-interface` |
| 审计基线提交 | `d59b7980` |
| Alembic head | `20260903_000169`，于 2026-09-07 实际执行 `alembic heads` 核验 |
| 当前后端 | 单用户—股票表、整数 `afterId`、六个 v1 路由 |
| 当前前端 | 单 Panel、行内移除、详情页直接 PUT、已添加后按钮禁用 |
| 初稿及前两轮修订范围 | watchlist 文档、相关索引与异常码注册表；本次新增依赖准入结果另见第 21.3 节 |

## 1. 当前代码审计与影响面

### 1.1 审计方法

按仓库规则使用仓库根 `/Users/congming/github/goldenshare` 的 CodeGraph 索引，执行了：

1. `codegraph_explore`：读取后端 watchlist 主链、前端页面/详情/首页链和用户创建链。
2. `codegraph_search`：定位 `WealthWatchlistItem`、`WatchlistQueryService`、`WatchlistCommandService`、`useWatchlistController`、`addWatchlistItem`、`useStockWatchlist`、`fetchWatchlistSummary`。
3. `codegraph_callers`：确认直接调用方。
4. `codegraph_impact`：确认替换影响面。
5. 对 CodeGraph 因 `selects` 等通用符号产生的无关测试候选，以精确 import/路径搜索排除；对 FastAPI 动态路由未识别出的 `test_auth_registration_api.py`，又以注册路径精确搜索补齐。未把模糊命中当作真实消费者，也未把“未发现测试”直接当成无测试。

### 1.2 当前后端调用链

```text
GET/PUT/DELETE /api/v1/wealth/market/watchlist/**
  -> src.biz.api.wealth.market.watchlist
  -> WatchlistQueryService / WatchlistCommandService
  -> WatchlistQuery / WatchlistPolicy / WatchlistFieldMapper
  -> app.wealth_watchlist_item
  -> Security + EquityDailyBar + EquityDailyBasic + EquityMoneyflow
```

当前事实：

| 文件/符号 | 当前行为 | v2 动作 |
|---|---|---|
| `src/biz/models/wealth/watchlist_item.py` | `(user_id, ts_code)` 唯一；`id` 是全局加入顺序 | 删除，由 group/membership 两模型替代 |
| `watchlist_query.py` | 先按 `id ASC` 分页，再查行情 | 删除，拆成 GroupQuery 与 ItemQuery |
| `WatchlistQueryService.get_page()` | `afterId` 整数游标；分页发生在行情 join 前 | 重写为 group-scoped、行情 join 后排序分页 |
| `WatchlistCommandService` | `add/remove` 内部 commit | 重写为分组 CRUD、单股组内添加和五种批量动作 |
| `src/biz/api/wealth/market/watchlist.py` | 六个路由，`_respond` 只映射四类错误 | 路由破坏性替换并完整映射 v2 错误 |
| `src/app/model_registry.py` | 注册旧 watchlist item | 删除旧模块，注册两个新模型 |
| `src/app/api/v1/router.py` | 组合现有 watchlist router | 保持，不新增第二个 router |

当前行情模型的 `(ts_code, trade_date)` 复合主键已经支持从有界成员集合按同日关联。数值排序会对当前组完成 join 后的候选做排序；不需要为本功能修改 `src.foundation` 模型或事实表索引，最终是否需要额外索引必须由真实 PostgreSQL EXPLAIN 决定，不能在 LLD 阶段猜测添加。

### 1.3 当前用户创建链

```text
AuthService.register
  -> UserRepository.create_user
  -> roles/token/audit
  -> commit

AdminUserService.create_user
  -> UserRepository.create_user
  -> roles/audit
  -> commit

src/scripts/create_user.py
  -> UserRepository.create_user
  -> commit
```

`UserRepository.create_user()` 目前有三个生产调用入口和两个 repository 测试调用。v2 必须移除该公开创建方法，由 `UserProvisioningService.create_user()` 统一创建 `AppUser`、flush 得到 ID、调用 Biz 默认组初始化器，但不自行 commit。这样三个上层入口继续掌握原事务，且没有第四条可绕过默认组的正式创建路径。

### 1.4 当前前端调用链

```text
WatchlistPage
  -> useWatchlistController
  -> watchlistApi
  -> WatchlistTable / AddWatchlistDialog / RemoveWatchlistDialog

StockDetailPage
  -> useStockWatchlist
  -> fetchWatchlistMembership / addWatchlistItem
  -> StockInfoRail

MarketOverviewPage
  -> useWatchlistSummary
  -> fetchWatchlistSummary
  -> MarketShortcutBar
```

影响结论：

1. `useWatchlistController` 只有 `WatchlistPage` 一个页面消费者，可直接删除并拆分，不需要兼容 wrapper。
2. `addWatchlistItem` 的两个消费者是列表 Controller 和详情页 hook；二者都要切到新合同，旧函数必须删除。
3. `useStockWatchlist` 由 `StockDetailPage` 使用，`StockInfoRail` 只消费其状态类型；两处必须同提交替换。
4. `fetchWatchlistSummary` 只有 `useWatchlistSummary` 消费，合同不变。
5. 前端路由 `WEALTH_WATCHLIST_PATH=/wealth/market/watchlist` 保持不变；首页点击仍自然进入默认组。

### 1.5 精确测试消费者

后端现有测试入口：

1. `tests/test_wealth_watchlist_model.py`
2. `tests/test_wealth_watchlist_postgres.py`
3. `tests/wealth_watchlist_postgres_support.py`
4. `tests/web/test_wealth_market_watchlist_api.py`
5. `tests/web/test_user_repository.py`
6. `tests/web/test_auth_services.py`
7. `tests/web/test_auth_registration_api.py`
8. `tests/web/test_admin_user_management_api.py`
9. `tests/web/conftest.py`
10. `tests/wealth_watchlist_browser_fixture.py`

前端现有测试入口：

1. `wealth/src/features/watchlist/api/watchlistApi.test.ts`
2. `wealth/src/features/watchlist/model/useWatchlistController.test.tsx`
3. `wealth/src/features/watchlist/model/watchlistViewModelAdapter.test.ts`
4. `wealth/src/features/watchlist/ui/AddWatchlistDialog.test.tsx`
5. `wealth/src/features/watchlist/ui/RemoveWatchlistDialog.test.tsx`
6. `wealth/src/pages/watchlist/WatchlistPage.test.tsx`
7. `wealth/src/pages/stock-detail/StockDetailPage.test.tsx`
8. `wealth/src/pages/market-overview/MarketOverviewPage.test.tsx`

未发现 `src.ops`、`qtf`、Lake 或其它前端产品消费 watchlist 业务合同。CodeGraph 对两个无关测试文件的通用符号命中不是依赖，本需求不修改它们。

## 2. 产品硬口径到实现与测试

| 已确认硬口径 | 后端唯一落点 | 前端唯一落点 | 必须覆盖的反例 |
|---|---|---|---|
| 默认组唯一、首位、无色、不可删除/改名/改色 | group 约束、Initializer、Policy、GroupQuery | Groups Controller、Tabs、Toolbar | 构造第二默认组；对默认组 DELETE/PATCH |
| 总组数最多 10，自定义最多 9 | 默认组行锁 + count + 约束 | rules 驱动创建按钮 | 第 10 个自定义组；并发越界 |
| 名称 trim、1～6、用户内不重名、禁用“我的自选” | `normalize_group_name` + `(user_id, name)` 唯一 | 创建弹窗即时提示 | 空白、7 字、控制字符、trim 后冲突 |
| 自定义组不可改名、可改色、颜色可重复 | 无 name PATCH；color 白名单 | 只有改色弹层 | 伪造改名路由；非法颜色；同色两组不得冲突 |
| 一个股票可属于多组 | `(group_id, ts_code)` 唯一 | 目标多选、详情多选 | 同组重复；跨组被错误去重 |
| 首页只数默认组 | SummaryQuery | 现有 Summary hook | 只改自定义组时徽标变化 |
| 展示态与编辑态两套列表 | API 返回 membership ID/pin | Page/Edit Controller/Table | 编辑态行跳详情；展示态出现操作列 |
| 编辑态禁止切组和新建 | 无额外后端状态 | Tabs 与创建按钮 disabled | 点击禁用 Tab 触发请求 |
| 不支持表头全选 | 无 | Table 不渲染 header checkbox | 查询不到表头复选框 |
| move 单目标、add 多目标、remove 当前组 | 原子批量 Command | Target/Confirm dialogs | 当前组作为目标；空目标；部分成功 |
| 写成功清选择、留在编辑态 | 返回真实计数 | Edit Controller | 成功后仍选中；错误后丢选择 |
| 删除当前自定义组 | 删除事务和 `nextGroupId` | 删除确认 | 默认组删除；最右组返回左邻而非默认 |
| 最右组删除回默认组，否则去右邻 | GroupQuery 在锁内计算 | Groups Controller 使用响应 | 前端自行猜 next group |
| 置顶后加入在前；取消不改基础顺序 | membership ID 为基础序；pin 不改 ID/created_at | Toolbar 与重载 | 时间戳倒序导致换位；取消后乱序 |
| 八列数值排序；首次降序；缺失恒后 | 排序注册表 + SQL + cursor | Table header + Items Controller | 前端本地排序；NULL 随方向跑到前面 |
| 切 Tab 恢复默认顺序；不保存排序 | 请求状态无持久化 | Groups/Page 协调 | 把上一组 sort 带到下一组 |
| 多色条按组创建顺序，同色不合并 | GroupMarksQuery | ColorMarks | 按颜色排序；同色合并 |
| 详情页任意分组决定“已添加” | stock-groups GET | Detail hook | 仅自定义组时显示“+自选” |
| 详情页不强制默认组，最终集合不可空 | replace diff + nonempty Policy | draft 为空确认 disabled | 空 PUT；未勾默认却自动加入 |
| 详情选择器 1～10 行自适应、不滚动 | groups GET 有界 | Picker CSS | 固定六行或内部滚动 |

## 3. 目标文件结构与逐文件动作

### 3.1 后端与迁移

```text
alembic/versions/<next>_upgrade_wealth_watchlist_groups.py       [新增]

src/biz/models/wealth/
  watchlist_group.py                                             [新增]
  watchlist_membership.py                                        [新增]
  watchlist_item.py                                              [删除]

src/biz/queries/wealth/market/watchlist/
  watchlist_group_query.py                                       [新增]
  watchlist_item_query.py                                        [新增]
  watchlist_query_service.py                                     [重写]
  watchlist_query.py                                             [删除]

src/biz/services/wealth/market/watchlist/
  watchlist_policy.py                                            [重写]
  watchlist_cursor.py                                            [新增]
  watchlist_group_initializer.py                                 [新增]
  watchlist_command_service.py                                   [重写]
  watchlist_field_mapper.py                                      [修改]

src/biz/schemas/wealth/market/watchlist.py                       [重写]
src/biz/api/wealth/market/watchlist.py                           [重写]
src/app/model_registry.py                                        [修改]
src/app/user_provisioning_service.py                             [新增]
src/app/auth/user_repository.py                                  [删除 create_user 方法]
src/app/auth/services/auth_service.py                            [改走 provisioning]
src/app/auth/services/admin_user_service.py                      [改走 provisioning]
src/scripts/create_user.py                                       [改走 provisioning]

pyproject.toml / uv.lock                                         [准入已登记 regex==2025.7.34]
tests/fixtures/wealth_watchlist_group_names.json                  [准入已新增共享名称向量]
```

`src/app/api/v1/router.py` 不改；仍组合同一个 watchlist router。`src.foundation`、`src.ops`、`qtf` 不改。

### 3.2 前端

```text
wealth/src/features/watchlist/api/
  watchlistApiTypes.ts                                           [重写]
  watchlistApi.ts                                                [重写]

wealth/src/features/watchlist/model/
  useWatchlistGroupsController.ts                                [新增]
  useWatchlistItemsController.ts                                 [新增]
  useWatchlistEditController.ts                                  [新增]
  useStockWatchlistGroups.ts                                     [新增]
  useWatchlistSearchController.ts                                [修改]
  watchlistViewModelAdapter.ts                                   [修改]
  watchlistTypes.ts                                              [修改]
  watchlistGroupName.ts                                          [新增 NFC/统一 trim/字素簇校验]
  useWatchlistController.ts                                      [删除]
  useStockWatchlist.ts                                           [删除]

wealth/src/features/watchlist/ui/
  WatchlistTabs.tsx                                              [新增]
  WatchlistEditToolbar.tsx                                       [新增]
  CreateWatchlistGroupDialog.tsx                                 [新增]
  ChangeWatchlistGroupColorDialog.tsx                            [新增]
  WatchlistGroupTargetDialog.tsx                                 [新增]
  ConfirmWatchlistRemoveDialog.tsx                               [新增]
  ConfirmWatchlistGroupDeleteDialog.tsx                          [新增]
  StockWatchlistGroupPicker.tsx                                  [新增]
  WatchlistColorMarks.tsx                                        [新增]
  WatchlistTable.tsx                                             [重写]
  AddWatchlistDialog.tsx                                         [修改]
  RemoveWatchlistDialog.tsx                                      [删除]
  watchlist.css                                                  [重写相关样式]

wealth/src/pages/watchlist/WatchlistPage.tsx                     [重写装配]
wealth/src/pages/watchlist/watchlist-page.css                    [修改]
wealth/src/pages/stock-detail/StockDetailPage.tsx                [修改]
wealth/src/features/stock-detail/sidebar/StockInfoRail.tsx       [修改]
wealth/src/pages/stock-detail/stock-detail-page.css               [修改]
```

`useWatchlistSummary.ts`、`MarketOverviewPage.tsx`、`MarketShortcutBar.tsx` 和路由常量不改业务代码，只更新测试 fixture 与断言。

## 4. 持久化 LLD

### 4.1 `WealthWatchlistGroup`

```python
class WealthWatchlistGroup(TimestampMixin, Base):
    __tablename__ = "wealth_watchlist_group"

    id: Mapped[int]                       # bigint / sqlite integer PK
    user_id: Mapped[int]                  # FK app.app_user.id CASCADE
    name: Mapped[str]                     # Text, NFC + 统一 trim 后展示值
    is_default: Mapped[bool]              # server_default=false
    color: Mapped[str | None]             # String(7)
```

物理约束与索引名固定：

| 名称 | 定义 |
|---|---|
| `uq_wealth_watchlist_group_user_name` | `UNIQUE(user_id, name)` |
| `uq_wealth_watchlist_group_user_default` | `UNIQUE(user_id) WHERE is_default` |
| `idx_wealth_watchlist_group_user_id_id` | `(user_id, id)` |
| `ck_wealth_watchlist_group_name_nonempty` | `length(name) > 0`；不使用码点长度约束替代可见字符校验 |
| `ck_wealth_watchlist_group_identity` | 默认组 name 为“我的自选”且 color IS NULL；自定义组 name 非默认名且 color IS NOT NULL 且属于八色 |

名称只保存一个规范化后的 `name`，展示和重名判断使用同一值，不另存规范化键。部分唯一索引在 ORM 同时声明 `postgresql_where` 与 `sqlite_where`，使真实 PostgreSQL 和 SQLite 模型测试保持同一不变量。最多 10 组不能靠单行 CHECK 表达，由事务锁和计数实现。

保护边界：唯一索引只保证“最多一个”，不保证存在，也不阻止 DELETE。迁移与用户开通事务保证每用户至少一个默认组；Service 拒绝默认组删除、改名和改色；查询发现缺失报错，不懒创建。不新增数据库删除触发器，删除用户时仍允许级联清理。名称 1～6 个字素簇由 Policy 校验，数据库 Text 避免合法组合字符被短 varchar 或 length<=6 二次误拒；输入有界保护见第 7.2 节。

### 4.2 `WealthWatchlistMembership`

```python
class WealthWatchlistMembership(TimestampMixin, Base):
    __tablename__ = "wealth_watchlist_membership"

    id: Mapped[int]                       # bigint / sqlite integer PK
    group_id: Mapped[int]                 # FK group.id CASCADE
    ts_code: Mapped[str]                  # String(16)
    is_pinned: Mapped[bool]               # server_default=false
```

物理约束与索引名固定：

| 名称 | 定义 |
|---|---|
| `uq_wealth_watchlist_membership_group_stock` | `UNIQUE(group_id, ts_code)` |
| `idx_wealth_watchlist_membership_group_pin_id` | `(group_id, is_pinned, id)` |
| `idx_wealth_watchlist_membership_stock_group` | `(ts_code, group_id)` |

成员表不保存 `user_id`、分组颜色、行情值或手工位置。所有权只能经 group 得出；同一股票在不同组形成不同 membership ID、加入时间和置顶状态。

### 4.3 时间与顺序

1. 默认未置顶：membership `id ASC`。
2. 默认置顶：membership `id DESC`。
3. ID 是不可变、不可复用的成员关系流水号，允许跳号，不是股票代码。所有插入都先持有目标组锁再分配 ID，同组写入按该锁串行化，保证新加入的关系在旧关系之后。
4. pin/unpin 只显式更新 `is_pinned` 与 `updated_at=now()`，禁止修改 ID/created_at。时间字段仅用于展示和审计，不能进入 ORDER BY 或 cursor。同批 source 按 membership ID 升序分配目标 ID；目标已存在时保留原 ID、时间和 pin。
5. group 排序固定为 `is_default DESC, id ASC`；颜色标记只取自定义组并按 `group.id ASC`。

## 5. Alembic 迁移 LLD

### 5.1 Revision 门禁

当前真实 head 是 `20260903_000169`。开发开始时必须再次执行：

```bash
alembic heads
```

若 head 仍为 `20260903_000169`，候选 revision 可使用 `20260907_000170`；若已经变化，文件名、`revision` 和 `down_revision` 必须连接当时真实单 head，禁止沿用本文候选值。

### 5.2 Upgrade 顺序

单个事务中的固定顺序：

1. 创建 `wealth_watchlist_group`、约束和索引。
2. 为 `app.app_user` 每一行插入默认组，包括没有旧自选的用户。
3. 断言每个用户恰有一个默认组，且默认组总数等于用户总数。
4. 创建 `wealth_watchlist_membership`、约束和索引。
5. 将旧表每行映射到该用户默认组；复制旧 `id/ts_code/created_at/updated_at`，`is_pinned=false`。
6. 校准 membership sequence，使下一 ID 严格大于当前最大 ID；空表时保持首次 ID 为 1。
7. 执行第 5.3 节全部对账。
8. 只有全部对账通过，才删除 `app.wealth_watchlist_item`。

迁移不得调用应用 Service、网络、Tushare、Redis 或前端；只允许确定性 SQL 与迁移内只读断言。

### 5.3 Upgrade 对账

迁移在 drop 旧表前必须验证：

```text
old_count == new_default_membership_count

old(user_id, id, ts_code, created_at, updated_at)
EXCEPT ALL
new_default(user_id, id, ts_code, created_at, updated_at)
== empty

new_default(...)
EXCEPT ALL
old(...)
== empty
```

另行验证：

1. 没有默认组或有多个默认组的用户数为 0。
2. 自定义组数为 0。
3. `is_pinned=true` 成员数为 0。
4. 旧表最大 ID 与新成员表最大 ID 一致。
5. sequence 的下一次值不会与已有 ID 冲突。
6. 逐用户比较旧 `ORDER BY id` 和新默认组 `ORDER BY membership.id` 的 `(id, ts_code)` 完整有序序列；两边必须完全相等，集合对账不能替代此项。
7. 迁移测试包含旧 ID 递增但 created_at 倒序、同时间、ID 跳号样本；迁移后默认顺序以及 pin/unpin 恢复结果都必须保持原 ID 序，不改写历史时间来凑顺序。
8. 迁移保留的成员 ID 和新建组 ID 均在第 7.3 节 API 安全整数范围内；超界则中止迁移，不重排历史 ID，也不继续删除旧表。

任一断言失败直接抛错，让 Alembic 事务 rollback；不得记录 warning 后继续 drop。

### 5.4 Downgrade 保护

旧单表不能表达自定义组、多组关系或置顶。downgrade 必须先检查：

1. 不存在自定义组。
2. 不存在 `is_pinned=true`。
3. 每个成员都属于默认组。

任一条件不满足就抛出明确异常，拒绝有损 downgrade。满足时才重建旧表、复制默认组成员并保留 ID/时间、做双向对账、校准旧表 sequence，最后删除新表。生产一旦开放 v2 写入，只允许前向修复，不以 downgrade 作为回滚手段。

## 6. 新用户默认组初始化

### 6.1 Biz 初始化器

新增：

```python
class WatchlistGroupInitializer:
    def initialize_default_group(
        self,
        session: Session,
        *,
        user_id: int,
    ) -> WealthWatchlistGroup:
        ...
```

规则：

1. 只构造默认组并 `session.flush()`，不 commit、不 rollback。
2. 名称使用 Policy 的 `DEFAULT_GROUP_NAME`；`is_default=true`、`color=None`。
3. 唯一约束是错误兜底，不把重复初始化吞成正常流程；正式用户创建只能调用一次。
4. 初始化器不 import `AppUser`，不做认证、角色、token 或审计逻辑。

### 6.2 App 组合服务

新增：

```python
class UserProvisioningService:
    def create_user(self, session: Session, **validated_fields: object) -> AppUser:
        user = AppUser(...)
        session.add(user)
        session.flush()
        self.watchlist_initializer.initialize_default_group(
            session,
            user_id=user.id,
        )
        return user
```

调用改造：

1. `AuthService.register()`：完成用户名、邮箱、密码和邀请校验后调用 provisioning；后续角色、token、audit 与默认组由现有单次 commit 一起提交。
2. `AdminUserService.create_user()`：完成管理员输入校验后调用 provisioning；角色和 audit 仍在同一 commit。
3. `src/scripts/create_user.py`：直接调用 provisioning，并保留现有显式 commit/rollback。
4. `UserRepository.create_user()` 删除；Repository 只保留读取和 `update_last_login`。
5. `tests/web/conftest.py` 的 `user_factory` 也改走 provisioning，并在 AppUser 之后创建 group/membership 测试表；测试 fixture 不再绕过生产用户不变量。

必须测试在角色写入、audit 写入或最终 commit 故障时，用户和默认组都不存在；不能出现“用户创建成功但没有默认组”。

## 7. Policy 与名称规范化

### 7.1 常量唯一来源

`watchlist_policy.py` 冻结：

```python
DEFAULT_GROUP_NAME = "我的自选"
MAX_GROUPS = 10
MAX_CUSTOM_GROUPS = 9
MAX_GROUP_NAME_CHARS = 6
MAX_GROUP_NAME_UTF8_BYTES = 1024
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 200
MAX_BATCH_MEMBERSHIPS = 200
MAX_API_ID = 9007199254740991
PALETTE = (
    "#F7C76B", "#5AA7FF", "#A78BFA", "#2DD4BF",
    "#FB923C", "#F472B6", "#A3E635", "#22D3EE",
)
SORT_FIELDS = (
    "price", "changePct", "vol", "peTtm", "pb",
    "volumeRatio", "turnoverRate", "netAmount",
)
```

前端展示上限、名称长度和 palette 只从 `GET /groups.rules` 读取，不复制这些业务常量。前端可保留搜索防抖、请求超时和 CSS 尺寸等交互常量。

### 7.2 名称算法

保持已确认的正常可见文字范围，不追加 isalpha/isdecimal 白名单或普通标点禁用规则；`AI-组` 可以使用。可见字符固定解释为 Unicode 扩展字素簇，不能用 Python len 或 Array.from 码点数替代。

统一步骤：

```text
1. 对 raw 做 NFC 规范化。
2. 只从首尾移除 TRIM_CODEPOINTS 中的字符；内部空白不折叠。
3. 空串拒绝；规范值中剩余的控制字符（Cc）、行/段分隔符（Zl/Zp）、
   格式控制符（Cf，字素组成所需的 U+200C/U+200D 除外）及非法 surrogate 拒绝。
4. 按扩展字素簇分段；每个非空白段必须含 Unicode 类别 L/N/P/S 的正常可见内容，
   独立连接符或孤立组合符不能充当名称；内部普通空格算一段。
5. 字素簇数必须为 1..6。
6. 自定义组 value == "我的自选" 时拒绝；name = value。
```

`TRIM_CODEPOINTS` 固定为下面的 ECMAScript trim 空白集合，后端不能直接用默认 `str.strip()`：

```text
0009 000A 000B 000C 000D 0020 00A0 1680
2000..200A 2028 2029 202F 205F 3000 FEFF
```

顺序决定了首尾换行会被 trim，内部换行拒绝；U+0085 不在 trim 集合中，作为控制字符拒绝。前端使用同一集合，不能随意添加另一份空白规则。

不做大小写折叠、NFKC 全角折叠、拼音或内部空格折叠；`AI` 与 `ai`、`A股` 与 `A 股` 分别视为不同名称。同名只比较完全相同的 NFC + trim 结果。

实现落点：后端 Policy 调用 `normalize_group_name` / `count_visible_graphemes`，采用已锁定 `regex==2025.7.34` 的 `\X`；字符类别 L/N/P/S、Cc/Cf/Zl/Zp 等也用该库 Unicode 属性判断。当前 Python `unicodedata` 为 Unicode 15.1，不能用其 `category()` 代替 Unicode 16 的类别判断；NFC 仍使用 `unicodedata.normalize`。前端 `watchlistGroupName.ts` 使用 `Intl.Segmenter("zh", {granularity:"grapheme"})` 和 Unicode 属性正则。共享向量验证后端最终裁决，不能退回码点长度。依据：[Unicode UAX #29](https://www.unicode.org/reports/tr29/)、[regex 2025.7.34 发布说明](https://pypi.org/project/regex/2025.7.34/)。

环境门禁：2026-09-08 用户已授权处理依赖准入；`regex==2025.7.34` 已登记至根 pyproject.toml/uv.lock 并安装到现有 `.venv`，未升级或卸载其它包。该版本支持 Unicode 16.0，无额外运行依赖，有 Python 3.13/macOS arm64 wheel。51 个样本在 Python、Node 与本机 Chrome 上通过，具体证据见第 21.3 节。该结论只证明本机依赖和样本可用，正式 Policy、API、数据库和目标浏览器页面回归仍在开发阶段执行；不得因此声称全部 Unicode 或所有浏览器已验证。

技术输入保护与业务长度分开：原始名称最多 1024 UTF-8 字节，先于分段执行，规范值同样不超过该上限；前后端使用同一规则。它用于防止单个字素含异常大量组合符，不能宣传成“最多 1024 字”。该固定保护上限通过 groups.rules 返回 `nameMaxUtf8Bytes`，不另设运行配置；数据库存 Text，不再用码点数截断。字段、Policy、前端提示与反例测试必须同时落地。

共享测试向量：

| 输入 | 规范值 | 结果 |
|---|---|---|
| `"  新能源  "` | `新能源` | 通过，3 |
| `"AI成长1"` | `AI成长1` | 通过，5 |
| `"A 股"` | `A 股` | 通过，3 |
| `"123456"` | `123456` | 通过，6 |
| `"1234567"` | 同输入 | 拒绝，7 |
| `"   "` | 空 | 拒绝 |
| `"我的自选"` | 同输入 | 自定义组拒绝 |
| `"AI-组"` | 同输入 | 通过，4 |
| `"q\u0301"` | 同输入 | 通过，1 个字素簇、2 个码点 |
| `"q\u0301q\u0301q\u0301q\u0301q\u0301q\u0301"` | 同输入 | 通过，6 个字素簇；数据库不得按 12 个码点拒绝 |
| `"e\u0301"` 与 `"é"` | `é` | 各为 1；同用户内视为同名 |
| `"\nAI\n"` | `AI` | 通过，2 |
| `"A\nI"` | 同输入 | 拒绝内部换行 |
| `"\uFEFFAI\uFEFF"` | `AI` | 通过，2 |
| `"\u0085AI\u0085"` | 同输入 | 拒绝控制字符，不被 trim |
| `"A\u200BI"` | 同输入 | 拒绝零宽空格 |
| 仅一个连接符或孤立组合符 | 同输入 | 拒绝无正常可见内容 |
| 单字素携带组合符使原始 UTF-8 超过 1024 字节 | — | 分段前拒绝技术输入超限 |

这些向量集中在 `tests/fixtures/wealth_watchlist_group_names.json`，pytest、Vitest 共读同一文件，不分别复制预期结果。补充上限字节边界、七个字素拒绝、长组合字符数据库写入和目标浏览器测试；记录实际依赖版本和 Unicode 版本，不能把两个 API 名称写在文档里就算等价性验证通过。

### 7.3 其它规范化

1. `tsCode` 沿用 trim + uppercase + 1..16。单股添加、move、add-to-groups、详情最终集合替换统一先计算实际缺失的目标关系；仅对需要新增关系的股票重新查询当前上市 A 股资格。不合格则整次请求失败，不能先移除源关系。仅保留或移除已有关系，以及 pin/unpin，不受该资格校验阻挡；这明确调整了 v1 重复添加也复检资格的行为。
2. API 中所有分组/成员 ID 为 `1..9007199254740991`（`Number.MAX_SAFE_INTEGER`）的安全正整数，数据库仍用 bigint，不改为前端 BigInt。JSON 请求 ID 必须严格为整数，拒绝布尔值、数字字符串和浮点数；路径/query 的十进制整数字符串显式解析后校验同一范围。cursor 的 `g/i` 也遵守此界限。
3. ID 数组长度必须在合法范围，且输入自身无重复；禁止静默去重。
4. move 仅一个目标；add-to-groups 为 1..9 个目标；详情最终集合为 1..10 个组。
5. `sortBy` 只接受注册表；存在 `sortBy` 时 `direction` 必须显式为 `desc|asc`，二者均不传才表示默认顺序。

资格查询复用当前证券候选条件：`security_type=EQUITY`、`list_status=L`、`curr_type=CNY`、交易所属于 SSE/SZSE/BSE。在取得相关组锁并确认当前关系后，对实际待新增股票去重，用一次有界集合查询校验；不是逐条调用单股 Service。已有目标关系保留原 ID、时间和置顶，不能因股票退市而被重建或强制删除。

## 8. API 与 DTO LLD

统一前缀：`/api/v1/wealth/market/watchlist`。所有字段保持 lowerCamel，所有 Pydantic DTO 使用 `ConfigDict(extra="forbid")`。

### 8.1 公共 DTO

请求体 ID 及 ID 数组元素、响应中的分组/成员 ID 统一复用以下类型；仅 `extra="forbid"` 不会阻止 Pydantic 自动转换类型：

```python
from typing import Annotated
from pydantic import Field, StrictInt

ApiId = Annotated[StrictInt, Field(ge=1, le=MAX_API_ID)]
```

下表所有 ID 位置的 `int` 均指 `ApiId`，包括 group 的 `id`、`groupId`、`membershipId`、删除响应 ID、`nextGroupId`、最终归属 ID 和颜色标记 ID。URL 参数先校验十进制数字形式，再转整数并检查范围，不能直接用 StrictInt 拒绝合法 URL 字符串。请求体类型/范围错误沿用 `422 / validation_error`；cursor 错误使用 `WL_CURSOR_INVALID`。响应在 commit 前构造并验证，数据库分配超界 ID 时回滚，不返回会被 JS 舍入的数字；GET 超界按查询错误处理。计数是非负安全整数，前端继续使用 `Number.isSafeInteger` 校验 ID 和计数，不接受隐式转换。

```text
WatchlistGroupDto
  id: int
  name: str
  isDefault: bool
  color: str | null
  memberCount: int
  createdAt: datetime

WatchlistGroupRulesDto
  maxGroups: int
  maxCustomGroups: int
  nameMaxVisibleChars: int
  nameMaxUtf8Bytes: int
  maxBatchMemberships: int
  palette: list[str]

WatchlistGroupCountDto
  groupId: int
  memberCount: int

WatchlistGroupMarkDto
  groupId: int
  name: str
  color: str
```

`WatchlistStockDto`、`WatchlistQuoteDto`、`WatchlistValuationDto`、`WatchlistActivityDto`、`WatchlistMoneyFlowDto`、`WatchlistDataStatusDto` 和 `MarketPageContextDto` 沿用 v1 字段和语义。

### 8.2 路由合同

| Method/Path | Request | Response |
|---|---|---|
| `GET /groups` | — | `WatchlistGroupsResponseDto {groups, rules}` |
| `POST /groups` | `{name, color}` | `WatchlistGroupMutationResponseDto {group}` |
| `PATCH /groups/{groupId}/color` | `{color}` | `WatchlistGroupMutationResponseDto {group}` |
| `DELETE /groups/{groupId}` | — | `{deletedGroupId, deletedMemberCount, nextGroupId}` |
| `GET /groups/{groupId}/items` | `limit,cursor,tradeDate,sortBy,direction` | `WatchlistPageResponseDto` |
| `GET /groups/{groupId}/search` | `keyword,limit` | `{groupId, keyword, items}` |
| `PUT /groups/{groupId}/items/{tsCode}` | — | `{groupId, tsCode, isAdded, created, memberCount}` |
| `POST /groups/{groupId}/actions/move` | `{membershipIds,targetGroupId}` | `WatchlistBatchActionResponseDto` |
| `POST /groups/{groupId}/actions/add-to-groups` | `{membershipIds,targetGroupIds}` | 同上 |
| `POST /groups/{groupId}/actions/remove` | `{membershipIds}` | 同上 |
| `POST /groups/{groupId}/actions/pin` | `{membershipIds}` | 同上 |
| `POST /groups/{groupId}/actions/unpin` | `{membershipIds}` | 同上 |
| `GET /stocks/{tsCode}/groups` | — | `WatchlistStockGroupsResponseDto` |
| `PUT /stocks/{tsCode}/groups` | `{groupIds}` | `WatchlistStockGroupsReplaceResponseDto` |
| `GET /summary` | — | 现有 `{totalCount}` |

旧 `GET /watchlist`、`GET /search`、`GET|PUT|DELETE /items/{tsCode}` 全部删除。

### 8.3 列表响应

```text
WatchlistItemDto
  membershipId: int
  addedAt: datetime
  isPinned: bool
  groupMarks: list[WatchlistGroupMarkDto]
  stock: WatchlistStockDto
  quote: WatchlistQuoteDto
  valuation: WatchlistValuationDto
  activity: WatchlistActivityDto
  moneyFlow: WatchlistMoneyFlowDto
  missingFields: list[str]

WatchlistPageResponseDto
  group: WatchlistGroupDto
  pageContext: MarketPageContextDto
  dataStatus: WatchlistDataStatusDto
  items: list[WatchlistItemDto]
  totalCount: int
  nextCursor: str | null
```

列表中的 group `memberCount` 必须等于 `totalCount`。`groupMarks` 排除默认组，颜色非空，并按 group ID 升序；后端不把同色条合并。

### 8.4 批量响应计数

```text
WatchlistBatchActionResponseDto
  action: "MOVE" | "ADD_TO_GROUPS" | "REMOVE" | "PIN" | "UNPIN"
  requestedCount: int
  createdCount: int
  removedCount: int
  updatedCount: int
  groupCounts: list[WatchlistGroupCountDto]
```

计数语义：

1. `requestedCount` 是通过 stale 校验的源 membership 数。
2. `createdCount` 是实际新建的目标 membership 行数；幂等已存在不计。
3. `removedCount` 是实际删除的源 membership 行数。
4. `updatedCount` 是 pin 状态实际发生变化的行数。
5. `groupCounts` 覆盖源组和所有目标组，按 group ID 升序，值为事务 flush 后真实 count。
6. 前端成功文案以这些字段为准，不显示本地推算的“成功 N 条”。

### 8.5 详情页 DTO

```text
WatchlistStockGroupDto
  groupId: int
  name: str
  isDefault: bool
  color: str | null
  selected: bool

WatchlistStockGroupsResponseDto
  tsCode: str
  isAdded: bool
  groups: list[WatchlistStockGroupDto]

WatchlistStockGroupsReplaceResponseDto
  tsCode: str
  isAdded: true
  groupIds: list[int]
  createdCount: int
  removedCount: int
```

`isAdded` 等于当前股票是否至少存在一条用户所属分组关系，不等于是否在默认组。PUT 响应 `groupIds` 按默认组优先、其余 group ID 升序。

### 8.6 结构错误与业务错误

1. JSON 语法错误、缺字段或基础类型无法解析由平台统一请求校验返回 422。
2. 已进入 watchlist Policy 的语义错误必须返回第 15 节 `WL_*`，不得落到通用 500。
3. URL path/query 中的正整数、日期和 cursor 继续显式解析，避免 FastAPI 自动 422 绕过 watchlist 错误合同。

## 9. 查询 LLD

### 9.1 GroupQuery

提供以下有界方法：

```text
list_groups(user_id) -> groups + grouped counts
get_owned_group(user_id, group_id, for_update=False)
get_default_group(user_id, for_update=False)
lock_all_groups(user_id) -> lock default first, then read/lock remaining groups by id
list_stock_groups(user_id, ts_code)
count_memberships(group_ids)
find_right_neighbor_or_default(locked_groups, current_id)
```

所有 group ID 查询把 `user_id` 放在同一 SQL where 中。不存在和越权统一返回 `WL_GROUP_NOT_FOUND` 或目标场景的 `WL_TARGET_GROUP_INVALID`，不先按 ID 查询再暴露所有者。

### 9.2 ItemQuery 主查询

固定步骤：

1. 验证当前组所有权并取得成员数。
2. 使用 `MarketPageContextQuery` 解析 expected trade date，空组也构造完整 pageContext。
3. 成员数为 0 时返回 EMPTY、空 items/null cursor，不访问行情事实表；只跳过行情查询，不跳过响应必填上下文。
4. 沿用 v1 `max(EquityDailyBar.trade_date) <= expectedTradeDate` 得到唯一 observed trade date。
5. 以 membership 为驱动，左连接 Security、DailyBar、DailyBasic、Moneyflow，所有行情表只使用同一 observed date。
6. 应用第 10 节排序、seek 和 `limit + 1`。
7. 对最终返回的至多 200 个 tsCode 再执行一次颜色标记集合查询；最多返回 `200 × 9` 行，在 Python 按 tsCode 分桶但不改变组顺序。
8. FieldMapper 构造 DTO；禁止跨日期补值、空值补零或从其它接口拼板块/行情。

一次列表请求允许固定数量 SQL，不允许随行数增长：group/total、page context、observed date、主列表、group marks。真实测试记录 SQL 数，并验证 1 行与 200 行不会出现 N+1。

### 9.3 Summary、搜索与归属

1. Summary：子查询取得用户默认 group ID，再 count membership；找不到默认组视为 `WL_QUERY_FAILED`，不在 GET 中懒创建。
2. 组内搜索：复用 `StockSearchPolicy/StockSearchQuery` 候选池，一次查询当前 group 对候选代码的 membership，生成 `ADDED|AVAILABLE`。
3. 单股归属：一次读取全部用户分组并左连接该 tsCode 的 membership；最多 10 行。
4. 颜色标记：只返回自定义组；默认组不制造透明色或伪色。
5. 写前资格集合查询放在 `watchlist_item_query.py`：`load_eligible_ts_codes(session, ts_codes)` 返回满足第 7.3 节条件的代码集合，最多 200 只；空输入不查 SQL。Command 比较实际待新增代码集合，缺任一股票即整批拒绝；不保留旧的逐股资格查询循环。

## 10. 排序与游标 LLD

### 10.1 排序注册表

固定映射：

| API 字段 | SQLAlchemy 列 |
|---|---|
| `price` | `EquityDailyBar.close` |
| `changePct` | `EquityDailyBar.pct_chg` |
| `vol` | `EquityDailyBar.vol` |
| `peTtm` | `EquityDailyBasic.pe_ttm` |
| `pb` | `EquityDailyBasic.pb` |
| `volumeRatio` | `EquityDailyBasic.volume_ratio` |
| `turnoverRate` | `EquityDailyBasic.turnover_rate` |
| `netAmount` | `EquityMoneyflow.net_mf_amount` |

请求字符串不得进入 `text()` 或动态列名拼接。

### 10.2 ORDER BY

定义：

```text
pin_rank     = CASE WHEN is_pinned THEN 0 ELSE 1 END
missing_rank = CASE WHEN sort_column IS NULL THEN 1 ELSE 0 END
```

默认顺序：

```text
pin_rank ASC,
CASE WHEN is_pinned THEN id END DESC,
CASE WHEN NOT is_pinned THEN id END ASC
```

数值顺序：

```text
pin_rank ASC,
missing_rank ASC,
sort_column <request direction>,
CASE WHEN is_pinned THEN id END DESC,
CASE WHEN NOT is_pinned THEN id END ASC
```

显式 `missing_rank` 保证 NULL 在升序和降序都位于各自 pin 分区末尾。

### 10.3 Cursor payload

canonical JSON 字段固定：

```json
{
  "v": 1,
  "g": 12,
  "s": "changePct",
  "d": "desc",
  "o": "2026-09-07",
  "p": 0,
  "m": 0,
  "x": "3.1400",
  "i": 101
}
```

语义：

1. `s/d` 在默认排序时均为 null。
2. `o` 是 observed trade date，可为 null。
3. `p` 是 `pin_rank`，只允许 0/1。
4. `m` 是 missing rank；默认排序固定 0。
5. `x` 是 Decimal 无损字符串；默认排序或缺失值为 null。
6. `i` 是最后一行 membership 的 ID；payload 不包含创建时间或 `a` 键。

编码使用 UTF-8 canonical JSON（固定短键、无多余空白、键顺序固定）后 base64url 且去 padding。token 最大 1024 字符；解码时恢复 padding、严格校验 exact keys、类型、版本和 Decimal，不接受未知版本、非有限 Decimal 或额外字段。DTO 中 addedAt/createdAt 继续采用 UTC ISO-8601，但时间不是分页身份。v2 尚未发布，不为早期文档中的含时间游标增加兼容解码。

不使用 HMAC：cursor 只描述当前用户已获授权 group 的分页位置，篡改不会扩大访问权限；引入签名会新增密钥配置，且不替代 group 所有权校验。

### 10.4 Seek predicate

“某值排在 cursor 之后”定义：

```text
after(value, cursor, asc)  = value > cursor
after(value, cursor, desc) = value < cursor
```

完整逻辑：

```text
pin_rank > cursor.p
OR (
  pin_rank = cursor.p
  AND (
    missing_rank > cursor.m
    OR (
      missing_rank = cursor.m
      AND (
        non-null numeric value is after cursor.x in requested direction
        OR (
          numeric values equal, or both are null/default sort
          AND id is after cursor.i
        )
      )
    )
  )
)
```

同一 pin 分区中，membership ID 的 after 方向固定：置顶为 `<`，未置顶为 `>`。默认排序跳过 missing/value 两层。实现必须由同一个 `WatchlistSortSpec` 同时生成 ORDER BY、cursor values 和 predicate，禁止三处手写导致漂移。

### 10.5 Cursor 失效

以下任一不一致返回 `WL_CURSOR_INVALID`：

1. group ID。
2. sortBy/direction。
3. 当前重新解析的 observed date。
4. 版本、字段、类型、Decimal 或 observed date 格式。

前端收到该错误时只自动清空 cursor 并重载首批一次；首批没有 cursor，若仍失败则进入正常 error，不循环重试。

### 10.6 跨页一致性边界

1. 成员集合、置顶状态和参与排序的行情值在翻页期间不变时，保证完整遍历无重复、无遗漏。
2. 本页面写成功后，取消旧列表请求并清空 cursor，从当前排序的首批重载；不把写前、写后页面直接拼接。
3. 其它会话增删成员、调整置顶或同一 observed date 的行情值原地更新，可能让行越过旧 cursor，产生重复或遗漏。例如首批返回未置顶的 1、2 后，另一会话把 3 置顶，后续页可能看不到 3；刷新首批后重新收敛到当前事实。
4. 日期绑定不等于行情/成员快照。前端按 membershipId 去重只能避免重复展示，不能补回遗漏；本期不承诺跨请求快照一致性，不增加快照表、结果缓存、版本状态或实时订阅。外部变化在用户刷新时重新读取。

## 11. 写事务与锁顺序

### 11.1 通用纪律

1. CommandService 的每个公开动作只 commit 一次，统一 try/rollback。
2. Query/Policy/Initializer 不 commit。
3. DTO 所需 ID、计数和 next group 必须在 commit 前完成 flush、查询与 DTO 构造；commit 后不再执行可能失败的 SQL，避免“写已成功却因回读失败返回 500”。
4. 需要多个 group 时，按 group ID 升序 `SELECT ... FOR UPDATE`。
   创建/删除/详情集合替换涉及分组清单，必须先单独取得默认组锁，再查询和锁定其余组，不能先缓存清单再等锁。默认组在迁移/开通时先于自定义组创建；测试验证默认组 ID 最小。批量操作只锁源/目标组，统一先组后成员；不得在持有自定义组锁后反向追加默认组锁。
5. 当前成员一次 `WHERE group_id=:current AND id IN (...) FOR UPDATE`，返回数必须等于输入数，否则整批 `WL_SELECTION_STALE`。
6. membership ID 和 group ID 都不能脱离认证用户上下文直接更新。
7. 集合上限 200、目标上限 9，因此单次笛卡尔候选最多 1800，常驻内存有界。
8. 单股和批量新增统一调用 CommandService 内部的 `_insert_missing_memberships`，不增加新服务文件。PostgreSQL 使用 `on_conflict_do_nothing(constraint="uq_wealth_watchlist_membership_group_stock")`；SQLite 使用 `(group_id, ts_code)` index elements。通过 `RETURNING id` 计算真实 createdCount；helper 不 commit、不建 savepoint、不做资格校验、不吞其它 IntegrityError。调用者先锁组、求缺失关系并完成资格校验；FK/check/其它唯一约束错误均让整个事务失败。锁与并发结论只由真实 PostgreSQL 测试证明。
9. DTO 必须是提交前物化的值，不能保留需要在 commit 后读取的 ORM 属性。提交失败时丢弃预构造 DTO，不返回假成功。
10. 新 ID 只能在取得目标组锁后由数据库分配；同批 source 以源 membership ID 升序输入 INSERT，多个目标以 group ID 升序处理。禁止在锁外预分配 ID。目标已有关系不变更 ID，默认组迁移继续保留原 ID。

写结果判定：

| 情形 | 后端/前端处理 |
|---|---|
| 提交前校验、SQL、DTO 错误，或能确认事务未提交的失败 | rollback；业务错误或 `WL_WRITE_FAILED`；保留输入和选择，可由用户重试 |
| commit 时通信异常，无法确认数据库最终结果 | 清理 Session，但不能声称 rollback 撤销了可能已提交的事务；能响应时返回 `503 / WL_WRITE_OUTCOME_UNKNOWN` |
| 已收到合法成功 DTO，后续 GET 失败 | 保持成功结论，只提示“操作已成功，列表刷新失败”；只重试 GET，不重放写入 |
| 前端写请求超时/响应丢失/成功响应校验失败，或不能证明回滚的错误 | mutation outcome=`UNKNOWN`；先读取最新事实，禁止原请求一键重试或自动重放 |

未知结果回读范围：组动作读 groups，成员动作读 groups 和当前组首批，详情动作读该股票 groups；单股添加还必须刷新当前搜索结果的组内归属，不能因股票未出现在首批就认定未添加。成功回读后清除失效选择，让用户基于最新状态重新操作；若回读失败，只允许继续重试读。回读不是原请求的成功证明，不补造成功 toast。本期不新增幂等键、后台任务或跨端状态自动合并。

### 11.2 创建组

```text
lock default group row
count all groups for user
if total >= 10 -> WL_GROUP_LIMIT_REACHED
normalize name/color
insert custom group
flush; map uq_wealth_watchlist_group_user_name -> WL_GROUP_NAME_CONFLICT
read count and build response DTO
commit
return prebuilt DTO
```

默认组行是唯一且始终存在的域内互斥点。缺失默认组是数据不变量损坏，返回 `WL_WRITE_FAILED` 并记录异常，不在这里补建。

### 11.3 改色与删除组

改色：锁定 owned group；默认组返回 immutable；验证 palette；更新 color/updatedAt；flush、查询 count、构造 group DTO；commit 后直接返回 DTO。

删除：

```text
lock default group first
read and lock remaining user groups ordered by id
resolve current group from locked rows
reject default
next = first custom group whose id > current.id, else default
count current memberships
delete current memberships
delete current group
flush; build DTO(deletedGroupId, deletedMemberCount, nextGroupId)
commit
return prebuilt DTO (do not read next.id from ORM after commit)
```

显式删除成员是业务步骤，FK cascade 是完整性兜底。删除最右自定义组必须回默认组，不回左邻。

### 11.4 单股组内添加

1. 锁定当前 owned group，避免与删除并发。
2. 查询目标关系；已存在则直接作为幂等成功，不复检资格，也不重置 ID、时间或 pin。
3. 仅当目标关系缺失时校验证券资格，再调用统一 `_insert_missing_memberships`；以实际返回行数决定 `created`，不沿用 v1 的 nested transaction/异常兜底路径。
4. 只有指定组内股票唯一冲突可以忽略；其它 FK/检查/提交失败不得误判为幂等。
5. flush 后查询当前组真实 count 并构造添加响应 DTO，再 commit，直接返回 DTO；提交后零 SQL。

### 11.5 Move

```text
validate target != current
lock [current,target] sorted
lock and validate source memberships
read existing target memberships for selected tsCodes
to_add = missing target pairs, ordered by source.id ASC
validate eligibility once for unique tsCodes in to_add; failure aborts whole request
_insert_missing_memberships(to_add)
DELETE all validated source memberships
flush + count groups + build batch DTO
commit
return prebuilt DTO
```

即使目标已存在某股票，也必须删除其源关系；已有目标成员的 ID/createdAt/pin 不变。若没有待新增关系，不查资格；若任一待新增股票不合格，源关系全部保留。

### 11.6 Add to groups

```text
validate 1..9 unique targets; none is current
lock current + targets sorted
lock and validate source memberships
read existing target memberships for selected tsCodes
to_add = missing source tsCodes × target IDs, ordered by target.id/source.id ASC
validate eligibility once for unique tsCodes in to_add; failure aborts whole request
_insert_missing_memberships(to_add)
flush + count groups + build batch DTO
commit
return prebuilt DTO
```

源关系不删除。任一目标越权、消失、非法，或实际待新增股票资格不合格，整批失败。最多 1800 个候选关系、200 只待校验股票；已存在关系不参与资格复检和 createdCount。

### 11.7 Remove、Pin、Unpin

1. Remove：锁定并验证后一次 delete；允许股票变成用户零归属。
2. Pin：一次 update `is_pinned=true, updated_at=now()`，只统计原 false 行。
3. Unpin：一次 update `is_pinned=false, updated_at=now()`，只统计原 true 行。
4. 幂等未变化行不计 `updatedCount`，但请求整体成功。
5. 三个动作均先锁当前 owned group，再锁定成员；flush、统计组数量和真实变更数量、构造 DTO 后只 commit 一次，再直接返回。

### 11.8 详情最终集合替换

```text
normalize tsCode and nonempty groupIds
lock default group first
read and lock remaining user groups ordered by id
validate every requested group belongs to user
load existing memberships for user + tsCode FOR UPDATE
to_add    = requested - existing
to_remove = existing - requested
if to_add is nonempty: validate current-listed A-share eligibility
_insert_missing_memberships(to_add ordered by group id ASC)
bulk delete to_remove
flush; build DTO(ordered final ids, actual createdCount, removedCount)
commit
return prebuilt DTO
```

请求不包含默认组时不自动加入。空集合在任何 SQL 写入前返回 `WL_MEMBERSHIP_REQUIRED`。仅保留/移除既有关系时不复检资格；保留关系不改 ID、时间或 pin，新增不合格则连同移除一起回滚。

## 12. 前端 API 与 Controller LLD

### 12.1 API client

`watchlistApi.ts` 必须：

1. 扩展 request helper 支持 JSON body，只在有 body 时设置 `Content-Type: application/json`。
2. 继续使用 `wealthFetch`，不自行读 token 或创建第二套 auth client。
3. 普通请求 5 秒、搜索 2 秒；外部 abort 与 timeout 都正确清理 listener/timer。
4. 每个响应使用 exact-key 运行时校验；拒绝 v1 `id/afterId`、缺字段、额外字段、NaN/Infinity 和非法枚举。
5. 保留后端 `code/message`；GET 响应合同失败为 `WL_QUERY_FAILED`。写成功响应无法解析、网络超时/响应丢失使用前端 `outcome="UNKNOWN"`，不伪造 `WL_WRITE_FAILED` 或“已回滚”；后端 `WL_WRITE_OUTCOME_UNKNOWN` 同样进入回读流程。
6. 删除 `itemUrl`、`fetchWatchlistMembership`、旧 `addWatchlistItem/removeWatchlistItem`。

写状态统一约定：每个写动作只有一个 Controller 所有者，持有一个带动作上下文的判别联合，形态为 `idle | pending(action) | succeeded(action, result) | failed(action, error) | unknown(action)`。组内动作记录发起时的组 ID，单股添加再记录 tsCode；详情动作记录 tsCode 和提交的最终集合，创建动作记录提交的名称/颜色。结果与错误只能出现在对应分支。只在 `watchlistTypes.ts` 共享必要类型，不引入通用 mutation 框架、额外 Controller 或队列。

`pending`、禁用状态和成功提示均从这一对象派生，不再平行保存 `pendingAction/writeOutcome/reconcilePending` 等同义字段。列表、分组和 picker 已有的 GET loading/error 独立保留：写成功但刷新失败是合法组合，不是新的写失败。unknown 保留动作上下文，通过既有读取状态显示回读进度；必要回读全部完成后转 idle，不补造原动作成功。Page 只负责一次协调刷新，不能与各 Controller 重复触发同一组 GET。

### 12.2 Groups Controller

状态：

```ts
type GroupsState =
  | { kind: "loading" }
  | { kind: "ready"; groups: WatchlistGroupDto[]; rules: WatchlistGroupRulesDto; currentGroupId: number }
  | { kind: "error"; message: string; canRetry: boolean };
```

独占 create/color/delete 的 mutation 状态与提交入口。Edit 只展示组级按钮/弹层并调用 Groups，不再持有第二份组级写状态。成功后的刷新错误归属于 GET 状态，不覆盖成功的 mutation。

规则：

1. 首次成功总是选择 `isDefault=true`，不从 URL、本地存储或上一会话恢复。
2. create 收到成功 DTO 即关闭弹层并记录响应 group 为目标，再刷新 groups；刷新失败不恢复创建弹窗或再次 POST，只重试 GET。
3. color 成功用服务端 group 覆盖本地项。
4. delete 成功退出编辑态、清选择、刷新 groups，并选择后端 `nextGroupId`。
5. 当前 group 在其它会话消失时刷新并回默认组。
6. 每次切组由页面协调 Items Controller reset sort/cursor/list；编辑态拒绝调用 `selectGroup`。
7. create/color/delete 的明确失败、成功后刷新失败、结果未知也执行第 11.1 节；未知结果先回读 groups，不直接重交旧名称、颜色或删除请求。

### 12.3 Items Controller

持有：`groupId`、`sortState|null`、items、total、page/data status、cursor、initial/more/error、generation、AbortController、scrollResetKey；独占单股添加 `addToCurrentGroup(tsCode)` 的 mutation，动作绑定发起时的 groupId/tsCode。添加弹窗每次只提交一个添加请求，pending 禁止重复提交，不保留旧控制器的 mutation queue。

规则：

1. groupId、tradeDate 或 sort 改变时 abort 旧请求，清列表/cursor，首批加载。
2. 新列第一次点击 `{sortBy, direction:"desc"}`；同列在 desc/asc 间切换。
3. Tab 切换调用 `resetSort()`，不把 sort 写 URL 或 storage。
4. load more 一次只允许一个请求，按 `membershipId` 去重只作为竞态防线，不替代服务端稳定排序。
5. observed date 改变或 cursor invalid 时重载首批。
6. 所有写成功后 cancel 旧读并重载首批；禁止本地猜测移动后的排序位置。
7. `addToCurrentGroup` 调用当前组 PUT；收到合法成功 DTO 后，Page 统一协调 groups 和当前排序首批刷新，不调用旧 `appendAddedItem`，不重置当前数值排序、不向末尾直接追加。刷新失败只重试读，不再次 PUT。
8. 添加请求的组/股票上下文不可被后来的切组覆盖；旧组写响应不能改变新组搜索状态、列表或弹窗。写请求 pending 时锁住添加弹窗交互；已经发出的写入不能靠关闭或 abort 当作撤销。

#### 12.3.1 搜索与单股添加接线

1. `WatchlistPage -> AddWatchlistDialog` 显式传入当前 groupId/name、`onAdd=Items.addToCurrentGroup` 和该动作派生的 pending/结果；旧 `useWatchlistController` 的 `appendAddedItem/pendingCodes/memberships` 接线全部删除。
2. 保留并修改 `useWatchlistSearchController(groupId, open)`。请求键至少含 groupId、keyword 和 generation，调用 `/groups/{groupId}/search`；切组、关闭、关键词改变或卸载都 abort 旧 GET 并提升 generation，重置对应结果。响应必须按第 8.2 节携带合法 `groupId`；接受前同时核验 `response.groupId === request.groupId` 和 generation/请求上下文仍有效。缺失、非法或不匹配的 groupId 按 `WL_QUERY_FAILED` 合同错误处理，不使用 URL、本地状态或 v1 响应兜底补字段；已过期的请求直接丢弃，不污染新组结果或错误态。
3. `ADDED` 只来自当前组搜索事实或当前组单股添加的合法成功结果。成功结果可立即标记这只股票，再刷新搜索；不得把其它组的状态复用过来，也不能把当前组首批中找不到的股票当成未添加。
4. 添加成功提示改为“已添加到「分组名」”，删除现有“已添加到列表末尾”。搜索刷新由现有 Search Controller 执行，groups/items 由 Page 协调一次；每类请求只有一个发起者。
5. 结果未知时，回读 groups、当前组首批和当前搜索归属，必要读取完成后才恢复添加；搜索关闭或股票不在当前结果中时，用 `GET /stocks/{tsCode}/groups` 只读核验原组归属，不新增查询接口或新 Controller。若待核验组已消失，以 groups 事实清除旧上下文，不向失效组继续搜索。没有合法成功响应，不显示添加成功提示。

### 12.4 Edit Controller

持有：

```text
isEditing: boolean
selectedIds: Set<number>
dialog: null | move | add | remove | color | delete
mutation: 第 12.1 节判别联合，仅覆盖 move/add-to-groups/remove/pin/unpin
```

规则：

1. 进入时冻结 current group ID；编辑态页面不接受切组。
2. 只选择当前已加载 membership；无表头全选、未加载数据选择。加载更多是追加当前组行，不是切换分页，已选保留；切组/退出/成功写后重载才清空选择。
3. 股票级操作在 `selectedIds.size===0` 时 disabled；组级改色/删除不依赖选择。
4. 成功：用服务端计数显示反馈，清选择、关当前弹层、保持编辑态并 reload groups/items。
5. 删除组成功是例外：当前组已不存在，退出编辑态并切到响应 next group。
6. 明确回滚的失败：保留选择、弹层和输入，mutation 转 failed；stale selection 则清选择并 reload。成功后的 GET 失败只进入对应读取错误状态，不恢复原选择或重试写入；未知结果进入第 11.1 节回读流程。
7. “完成”只清选择并退出，不发写请求。
8. 达到 `rules.maxBatchMemberships` 后，未选行的 checkbox 和 row toggle 都禁止新增选择，提示“单次最多选择 {上限} 只”；已选行始终可取消，加载更多和浏览不受影响。解除一个选择后立即允许补选。提交时再次校验，后端仍拒绝 201 条及超限请求。
9. 写请求与成功后的 GET 使用分开的错误处理，不能共用一个 catch 把刷新失败判为写失败。`unknown` 时保留提示并暂停当前写入口，由既有 GET 状态表达回读进度；读取失败只允许重试读取，成功后清旧选择并基于当前事实恢复操作，不报告原请求成功。
10. 改色/删除只调用 Groups 的提交函数并消费其 mutation；不在 Edit 中再次请求或复制 outcome。由 Page 按唯一写结果协调清选择、退编辑及刷新，避免一个点击触发两次 mutation 或两轮重载。

### 12.5 详情页 Controller

`useStockWatchlistGroups(tsCode, enabled)` 分离 committed 与 draft：

```text
status: "idle" | "loading" | "ready" | "error"  // 只描述读取
groups: StockGroupDto[]
committedIds: Set<number>
draftIds: Set<number>
open: boolean
mutation: 第 12.1 节判别联合，仅覆盖当前股票最终集合 PUT
generation: number
abortController: AbortController | null
```

提交中（saving）只由 `mutation.kind === "pending"` 派生，不再放入读取 status。committed 与 draft 分别表示服务器事实和未提交选择，二者不是重复写状态。

1. enabled 后 GET 决定按钮“+自选/已添加”，两者都可点击；缓存仅用于按钮，不作为下一次打开的真实预选。
2. 每次 open 增加请求 generation 并 GET 最新 groups/selected；显示 loading，读取成功才更新 committed 和本次 draft。加载中和失败时不可勾选/提交；失败在 picker 内提供读取重试。
3. draft 建立后 toggle 只改 draft，后台读取不得覆盖用户勾选；draft 为空时确认 disabled。不新增实时订阅或跨端自动合并，确认仍提交本次最终集合。
4. cancel、outside pointer、Escape 还原 draft 并关闭，不发 PUT。
5. confirm PUT 最终集合；成功用响应覆盖 committed 并关闭，明确回滚的失败保持打开和 draft。结果未知先回读最新归属，不自动重放；回读成功后重建可编辑选择，不把旧 draft 直接再提交。
6. 关闭、tsCode 改变或组件卸载都 abort 旧 GET 并递增 generation；旧响应不得重新打开 picker、覆盖新股票或后来打开的草稿。取消读取不是写入，取消始终不发 PUT。

## 13. 组件与交互 LLD

### 13.1 页面装配

页面层只协调 controllers 和路由：

```text
PageBreadcrumb
WatchlistTabs
Panel
  persistent header: group/name/count/date + 添加自选 + 操作/编辑中
  WatchlistEditToolbar (editing only, inserted below header, 52px)
  data notice/state
  WatchlistTable
dialogs
toast/status
```

面包屑、TopMarketBar、行情日期状态和当前列表视觉基线沿用 v1。Tabs 位于面包屑下、Panel 上；“+ 新建分组”是文字按钮，不退回纯 `+`。

编辑态不替换 66px 面板头部：保留组名/数量/日期，“添加自选”禁用，“操作”显示“编辑中”。操作栏出现在原头部下方、表头上方；完成后隐藏操作栏和 checkbox 列，恢复头部按钮。

### 13.2 Table

1. 删除 action column 和行内移除。
2. 最左 `color-marks` 固定列始终存在；展示态其右直接是代码/名称，编辑态插入 checkbox 固定列。
3. 表头 checkbox 单元格为空，不渲染 checkbox 控件。
4. 代码/名称继续 sticky；取消右侧 action sticky。所属板块仍为横向内容末列。
5. 展示态 row click 跳详情；编辑态 row click toggle，内部 checkbox 阻止重复触发。
6. 八个表头渲染 button 与 `aria-sort=none|descending|ascending`；非数值列无排序交互。
7. row key 使用 membershipId。

### 13.3 颜色条

`WatchlistColorMarks` 使用 CSS grid：`grid-template-rows: repeat(n, 1fr)`，占满 60px 行高。每个段独立 DOM、`title` 和 `aria-label="属于分组：{name}"`；同色不合并。无自定义组时渲染空占位，不制造默认色。

### 13.4 Toolbar 与 dialogs

操作顺序固定：

```text
已选择 N 只｜移动分组｜添加到分组｜移出本组｜置顶｜取消置顶｜修改颜色｜删除分组 …… 完成
```

1. Move 目标单选；Add 目标多选；当前组从目标列表排除。
2. Remove 文案：“将 N 只股票移出「分组名」？”并说明其它分组不变。
3. Delete 显示当前组名和真实 memberCount。
4. Color/Create 消费 API palette；颜色选择有 radio 语义和非颜色的选中描边。
5. 默认组的改色/删除按钮不提供可执行状态。
6. 所有 modal 复用现有 native dialog 焦点/ESC/pending 锁纪律；pending 时防重复提交。

### 13.5 详情页 picker

1. `StockInfoRail` 的 watchlist action 外包一层 `position:relative`，picker 绝对定位在按钮下方。
2. picker 每组一行：checkbox、可选色点、组名；默认组第一且无色点。
3. 高度由实际 1..10 行自然撑开，不设 `height/max-height/overflow-y`，不保留六行空位。
4. 底部固定在内容之后显示取消/确认；不是滚动区内 sticky footer。
5. 打开时焦点进入弹层，读取成功后进入第一项；读取失败时可聚焦重试。Escape/外点关闭并恢复触发按钮焦点；saving 时锁交互，不能把关闭弹层误当作撤销已提交写入。

## 14. 前端可见状态与反馈

| 场景 | 页面行为 |
|---|---|
| groups 初始失败 | 页面级 error，可重试；不猜默认组 |
| 当前组空 | 保留 Tabs/头部；展示“当前分组还没有股票”与添加入口 |
| 行情 DELAYED/PARTIAL | 沿用 v1 notice 与 `--`，不隐藏成员 |
| list 首批失败 | 当前组局部 error；其它 Tab 仍可切 |
| load more 失败 | 保留已加载行，底部重试 |
| group name conflict/limit | 创建弹窗保留输入和颜色，显示后端信息 |
| batch stale | 清选择、刷新列表，提示列表已变化 |
| 明确回滚的 batch/write failed | 保留选择/弹层，解除 pending |
| 写成功后刷新失败 | 保持成功反馈、选择已清；单独提示刷新失败，只重试 GET |
| 写结果未知 | 保留上下文，禁止重放原请求；先读取最新事实，回读失败只重试读 |
| picker 每次打开 | 重新读取真实预选；loading/error 禁止提交，error 可重试 GET |
| group deleted elsewhere | 刷新 groups，回默认组 |
| summary failed | 首页徽标 `--`，不阻塞首页 |

成功反馈必须含服务端真实数量；例：“已将 2 只股票移动到「新能源」”“已从「成长」移出 3 只”“已删除「观察」，移除 12 条组内关系”。

## 15. 异常、安全与日志

### 15.1 异常映射

| HTTP | code | 前端动作 |
|---:|---|---|
| 400 | `WL_REQUEST_INVALID` | 保留输入，提示修正；非 cursor 场景不自动重试 |
| 400 | `WL_CURSOR_INVALID` | 清 cursor，首批重载一次 |
| 404 | `WL_GROUP_NOT_FOUND` | 刷新 groups；当前组失效则回默认 |
| 409 | `WL_GROUP_NAME_CONFLICT` | 创建弹窗保留输入 |
| 409 | `WL_GROUP_LIMIT_REACHED` | 刷新 groups/rules，禁用创建 |
| 409 | `WL_DEFAULT_GROUP_IMMUTABLE` | 刷新 groups，提示默认组不可操作 |
| 409 | `WL_SELECTION_STALE` | 清选择并刷新当前组 |
| 422 | `WL_TARGET_GROUP_INVALID` | 保留目标弹层，刷新可选组 |
| 422 | `WL_MEMBERSHIP_REQUIRED` | 详情 picker 保持打开，确认禁用 |
| 422 | `WL_STOCK_NOT_ELIGIBLE` | 保留上下文，提示当前仅支持上市 A 股 |
| 500 | `WL_QUERY_FAILED` | 对应读模块 error，不回退 mock |
| 500 | `WL_WRITE_FAILED` | 明确未提交且已回滚；保留输入/选择，可由用户重试 |
| 503 | `WL_WRITE_OUTCOME_UNKNOWN` | 不声称未保存；先回读最新事实，不自动重放原请求 |

这些 code 同轮登记到系统异常码注册表。`_respond` 按具体业务异常先匹配，最后才归并 query/write 500。

### 15.2 安全边界

1. 所有路由使用 `require_authenticated`，请求不得携带或选择 userId。
2. group 所有权和资源存在性用同一条件查询；404 不暴露别人的 group。
3. target 越权和不存在统一为 target invalid。
4. membership 更新必须包含当前 owned group 条件。
5. 排序仅白名单 expression；所有值绑定参数。
6. cursor 不承载授权，解码后的 group 仍与 URL 和认证用户双重校验。
7. 日志记录 code、action、userId、groupId、数量和异常类型；不记录 token、密码或完整请求身份材料。

## 16. 测试 LLD

### 16.1 ORM 与迁移

重写 `tests/test_wealth_watchlist_model.py`：

1. 两模型注册成功，旧模型模块不存在。
2. 用户内默认组唯一、名称唯一；不同用户可同名。
3. 默认组 identity check、颜色非空/色板 check、名称非空 check；业务字素簇长度由 Policy 验证，合法六字素多码点名称可以实际入库。
4. 同股票跨组允许、同组重复拒绝。
5. 删除 group 级联自己的 memberships；删除 user 级联全部组/成员。
6. SQLite ID 不复用。
7. 明确不测试“数据库拒绝直接 DELETE 默认组”这一不存在的能力；API 层拒绝默认组删除、用户删除级联、新用户初始化和缺失默认组报错分别测试。

真实 PostgreSQL：

1. 从 `000169` 等价 fixture upgrade。
2. 无旧自选用户也有默认组。
3. 数量、双向 `EXCEPT ALL`、ID/时间和 sequence 对账。
4. upgrade 后旧表不存在。
5. 无 v2 写入时 downgrade 可还原；有 custom/pin 时 downgrade fail closed。
6. 历史时间与 ID 逆序、时间相同和 ID 跳号均不影响迁移前后有序序列；pin/unpin 不改变 ID 或基础位置。

### 16.2 用户开通

1. 公开注册创建一个默认组。
2. 管理员创建创建一个默认组。
3. CLI 服务级测试创建一个默认组。
4. 角色/audit/commit 故障回滚用户和默认组。
5. `test_auth_registration_api.py` 和 `test_admin_user_management_api.py` 分别断言真实入口结果。
6. repository 不再暴露 create_user；旧创建测试迁到新增 `tests/web/test_user_provisioning_service.py`，repository 测试只保留读与登录时间更新。
7. 全局 `user_factory` 走 provisioning 后执行完整 `tests/web` 回归，确认额外默认组事实不污染其它模块测试。

### 16.3 API 与并发

`tests/web/test_wealth_market_watchlist_api.py` 破坏性替换 v1 断言，覆盖：

1. 全部 15 个 v2 route/method（含 summary）的身份要求和 exact path；五个被删除的 v1 路径为 404/405。
2. groups 默认顺序、rules、count、双用户隔离。
3. 创建 9 个成功、第 10 个失败；并发创建不越界。
4. 名称向量、trim 冲突、默认禁名、非法颜色、重复颜色。
5. 默认组 delete/color 拒绝；不存在改名路由。
6. 当前组 search 资格过滤；单股 PUT 新关系复检资格，既有关系幂等成功（含已退市股票）。move/add-to-groups/详情 diff 同测：无新增时可保留/移除；任一待新增股票不合格则整批零变化，移动源关系不得先删除。
7. move/add/remove/pin/unpin 的正常、幂等、越权、stale 和故障注入 rollback。
8. 删除右邻/最右默认回退和仅当前组关系删除。
9. 详情预选、最终 diff、非空、无默认强加。
10. summary 只统计默认组。
11. 颜色标记顺序、同色不合并、默认无标记。
12. 八列 desc/asc、pin 两分区、null 后置、同值 tie；数据不变的 fixture 上验证 cursor 跨页无重复/遗漏。另测外部置顶/同日行情变化可越过旧 cursor、刷新首批后恢复当前事实，不伪造跨请求快照保证。
13. cursor 损坏、版本、group/sort/date 不匹配。
14. 空组不查行情；v1 同日、DELAYED/PARTIAL、zero/null 回归。
15. 创建/删除先锁默认组再读清单；验证并发交错时 nextGroupId 和组数正确。新增关系在组锁内分配 ID，批量目标关系分配顺序稳定。
16. 每个写动作提交后 SQL 数量为 0；提交前计数或 DTO 失败全部回滚；已知回滚与提交通信失败的未知结果返回不同 code。
17. Policy 和真实数据库共测名称共享向量；1～6 字素边界、普通标点、trim 控制字符、1024 字节保护、NFC 重名一致；后端拒绝 0/201 条批量输入。
18. JSON ID 覆盖 1、安全整数上界通过；上界加一、0、负数、true、数字字符串、浮点数拒绝；数组元素同样严格且重复拒绝。URL 十进制整数按同一范围验证，cursor g/i 超界拒绝；迁移超界不得 drop，响应 ID 超界在提交前失败回滚。
19. 单股、移动、多组添加及详情新增都走同一插入 helper；验证空集合、已存在关系、实际 createdCount、目标已有 ID/pin 不变。SQLite 与 PostgreSQL 均验证只忽略指定唯一冲突，其它完整性错误整批失败；资格校验只查询实际待新增股票一次。

PostgreSQL 并发测试还要证明 unique conflict 只识别目标约束，不能把 FK/check/commit 故障误判为幂等。

### 16.4 前端 API 与 Controller

1. `watchlistApi.test.ts`：全部方法、URL encoding、body、auth client、timeout、abort、exact DTO 和 v1 shape 拒绝。
2. Groups Controller：默认选择、create 切组、delete 使用 next、组消失回默认、竞争取消。
3. Items Controller：首批/更多、同列切向、新列降序、Tab reset、日期/cursor 重载、卸载 abort。
4. Edit Controller：逐行选择、0/200/201 边界、达到上限仍可取消/浏览/加载更多、保留已加载选择；成功清空留编辑、明确失败保留、stale 刷新、delete 退出。
5. Detail Controller：每次打开都有新 GET、真实预选、任意组 isAdded、draft/committed、读取失败禁用提交、关闭后旧 GET 无效、零选择禁用、取消/外点/Escape 零 PUT、明确失败保留。
6. 写失败已回滚、成功后刷新失败、网络超时/响应丢失/响应校验失败三组样本：成功不变失败、未知不假称回滚、未知先回读且无自动写重放，回读失败只重试 GET。
7. pytest/Vitest 共读名称 JSON；目标浏览器分段/trim 与后端结果一致，不用两个语言各写一份测试向量。
8. 单股添加端到端接线：Page/Dialog/Items/Search 不依赖旧 Controller；当前组 ADDED 隔离、关键词/关闭/切组旧响应丢弃、成功在当前排序重载而非末尾追加。写成功但任一刷新失败不重发 PUT；结果未知且目标股票不在首批/搜索结果时只读核验归属。
9. 一个点击只触发一个写请求，groups/items/search 各只刷新一次；改色/删除状态由 Groups 独占。pending 与禁用从 mutation 派生，success + GET error 可同时表达，unknown + GET error 只能重试读。ID 响应超过安全整数范围即合同失败，不可舍入后进入 Set。
10. 本页添加、批量与详情写成功后的列表更新均清除旧 cursor/请求，使用当前排序首批；外部变化只在刷新时重新读取，不把按 ID 去重当作补漏机制。
11. 搜索响应的 groupId 正确时才接受；缺失、越界、类型非法或与请求不一致均拒绝。另测“groupId 正确但 generation 过期”仍丢弃，禁止只有一层检查；不得恢复 v1 无 groupId 合同。

### 16.5 组件与页面

1. Tabs 顺序和 `+ 新建分组`；编辑态其它 Tab/新建禁用。
2. 展示态无操作列，编辑态无表头全选；整行行为互斥。
3. Toolbar 顺序、股票级/组级 disabled 和危险色。
4. Move 单选、Add 多选、Remove/Delete 文案和确认层级。
5. 八列表头 `aria-sort` 和请求参数。
6. 多色段等高、按创建顺序、同色两个 DOM、tooltip/aria 名称。
7. picker 1/2/10 组自然高度且 computed `overflow-y` 非 scroll/auto。
8. “+自选/已添加”均可点击，saving 才禁用。
9. 首页自定义组变化不改徽标，默认组变化才改。
10. 编辑态原头部始终存在，数量/日期不消失；添加禁用、编辑中标签和新增 52px 操作栏位置正确，完成后恢复原头部。

### 16.6 真实 API 浏览器 smoke

更新 `tests/wealth_watchlist_browser_fixture.py`，至少准备两个用户、默认组、三个自定义组、同色组、跨组股票、pin 与 null 行情样本。真实浏览器验证：

1. 首页 → 默认组。
2. Tab/创建/改色/删除。
3. 展示/编辑、move/add/remove/pin/unpin。
4. 数值排序与多页加载。
5. 详情 picker 的预选、取消和最终提交。
6. 网络响应无 v1 字段，console 无错误，键盘/焦点/Escape 可用。

## 17. 通用编码门禁矩阵

| 通用清单 | 适用 | 本 LLD 落点 | 开发验收 |
|---|---|---|---|
| 2.1 交付事实链先行 | 是 | PRD → 交互/Figma → 技术方案 → LLD → 代码 | 文档状态不冒充开发完成 |
| 2.2 后端事实归一 | 是 | group/membership 与 serving 为唯一事实 | 前端不拼 membership/count/sort |
| 2.3 模块状态机清晰 | 是 | Groups/Items/Edit/Detail 四状态域 | 六类读写失败和竞态测试 |
| 2.4 显示语义绑定 | 是 | DTO 数值/null/direction/groupMarks | `--`、颜色、count 不伪造 |
| 2.5 测试行为过程 | 是 | 选择、确认、取消、写后重载 | Controller + 页面事件测试 |
| 2.6 文档实现同轮 | 是 | 四份 v2 文档、README、异常码 | 每完整阶段更新对账 |
| 2.7 渐进替换纪律 | 是 | 完整后端 → 前端 → 联调验收；同窗口发布 | 不保留 v1 双合同，不验收依赖断裂的半成品 |
| 2.8 契约先行/消费者 | 是 | 第 8 节 exact DTO；第 1 节消费者 | 旧调用/字段精确搜索清零 |
| 2.9 图表坐标/文案 | 否 | 本模块无图表 | 标记 N/A，不新增图表 |
| 2.10 计算与传输边界 | 是 | 排序/计数/颜色后端产出 | 禁止前端全量排序/聚合 |
| 2.11 配置生效语义 | 是 | 无运行配置；Policy rules 单源 | 无 env/Settings/config 表新增 |
| 2.12 通用清单映射 | 是 | 本表 | 开发前逐项复核 |
| 2.13 例外白名单 | 是 | 第 17.1 节 | 未登记例外为 0 |
| 2.14 图表参数优先级 | 否 | 无图表参数 | N/A |
| 2.15 双图坐标对齐 | 否 | 无双图 | N/A |
| 2.16 卡片文案单行 | 部分 | Tabs/Toolbar/Toast 控制长文案 | 6 字组名和 10 Tab 溢出测试 |
| 2.17 核心真实 API + 展示 | 是 | 第 16.3～16.6 节 | 后端路由 + 前端 real smoke |
| 2.18 跨模块抽象门禁 | 是 | app provisioning 组合 biz；无反向依赖 | import/CodeGraph 复核 |

### 17.1 例外白名单

当前没有模块例外。

特别说明：`src.app.user_provisioning_service -> src.biz...WatchlistGroupInitializer` 是 `src.app` 组合业务能力的正式依赖方向，符合依赖矩阵，不是例外；`src.app.auth` 不直接实现 watchlist 规则。

### 17.2 编码前 Gate

| Gate | 当前状态 | 通过条件 |
|---|---|---|
| 产品需求 | 已确认 | 保持 v2.6 的加入顺序、资格及一致性边界 |
| 交互/Figma | 已确认 | 节点 `1383:82` 及 comment 修订有效 |
| 技术方案 | 两轮修订及准入勘误已回填 | v2.4 与本文一致 |
| LLD | 两轮修订及准入勘误已回填 | v2.3；后续业务开发须另获明确授权 |
| 名称分段依赖 | 本机准入已完成 | regex 已安装锁定，51 个跨运行时样本通过；正式模块测试在开发阶段补齐 |
| Alembic head | 当前已核验 | 编码迁移前再次核验 |
| 当前代码/消费者 | 已审计 | 开发开始前 CodeGraph 状态无 stale |
| 数据库/部署授权 | 未授权 | 本期开发不等于生产迁移授权 |

## 18. 三个完整开发阶段

每个阶段形成可独立验证的完整结果后停下验收，不跨阶段进入下一项。阶段内部按真实依赖次序编码，不要求删掉旧模型但仍留旧导入的半成品独立运行。当前分支不变，不创建临时分支/worktree，不新增兼容层。

### 阶段一：完整后端闭环

1. 复核已完成的名称依赖准入，先定义 Policy、异常和 v2 DTO，供后续服务引用；将共享样本接入正式模块测试。
2. 新增 group/membership ORM、迁移脚本、Initializer、UserProvisioningService，接好三种用户创建入口与测试 fixture。
3. 完成 GroupQuery、ItemQuery、Cursor、FieldMapper、QueryService/CommandService、v2 router 和错误映射。
4. 在这一完整阶段内替换所有后端消费者并删除旧模型、查询、DTO 和五个旧接口；不得以临时 alias 让中间状态通过测试。
5. 完成模型、迁移测试、用户开通、名称、ID 排序、并发原子性、写结果分类和真实 API 回归。

停止条件：完整应用可加载；三类用户入口与全部 v2 route 真实测试通过，旧接口不可用；测试数据库迁移及顺序对账通过。迁移脚本开发和隔离验证不代表获准迁移正式数据库。此阶段未改前端，不能单独部署后端。

### 阶段二：前端 API、状态与页面

1. 重写类型/API client。
2. 拆分四个 Controller。
3. 完成 Tabs、Table、Toolbar、dialogs 和样式。
4. 接入 stock detail picker；首页只更新测试。
5. 删除旧 hooks/dialog/行内操作代码。

停止条件：组件/页面/typecheck/build 通过，用户可见行为与 Figma 对齐。

### 阶段三：真实联调、迁移演练与最终对账

1. 更新 browser fixture，完成双用户真实 API smoke。
2. PostgreSQL EXPLAIN、P95、payload、SQL 数量和最大批量验收。
3. CodeGraph impact 复核旧消费者清零。
4. 文档逐条对账并记录未完成项。
5. 用候选版本完成完整发布顺序的隔离迁移演练，核验用户—默认组、历史序列、详情每次打开刷新、200 只选择上限及三类写结果反馈。

停止条件：只形成候选版本；部署和生产迁移仍需独立授权。

## 19. 验证命令与证据

开发后最低命令：

```bash
alembic heads

pytest -q \
  tests/test_wealth_watchlist_model.py \
  tests/test_wealth_watchlist_postgres.py \
  tests/web/test_wealth_market_watchlist_api.py \
  tests/web/test_user_repository.py \
  tests/web/test_user_provisioning_service.py \
  tests/web/test_auth_services.py \
  tests/web/test_auth_registration_api.py \
  tests/web/test_admin_user_management_api.py

pytest -q tests/web

npm --prefix wealth test -- \
  src/features/watchlist \
  src/pages/watchlist/WatchlistPage.test.tsx \
  src/pages/stock-detail/StockDetailPage.test.tsx \
  src/pages/market-overview/MarketOverviewPage.test.tsx

npm --prefix wealth run typecheck
npm --prefix wealth run build
```

不得因测试路径不存在而把命令成功当成覆盖；开发时先用 `rg --files` 复核实际路径。真实 PostgreSQL、浏览器和性能证据需要记录样本规模、SQL 数、P95、payload、EXPLAIN 摘要、浏览器 URL、network 与 console 结果。

## 20. 发布、回滚与风险

发布保持上层方案的同窗口切换：暂停旧 watchlist 写入 → 迁移和自动对账 → 同窗口发布后端/前端 → 验证用户—默认组一一对应、summary、列表、详情 → 恢复访问。

用户已经明确当前不会有人新注册，本次将其记录为发布前提，不再作为开工阻塞，不新增注册开关、排空框架或管理员/CLI 专门封禁机制。迁移后保留用户—默认组对账；未来正常开通用户的三条入口仍按第 6 节同事务初始化默认组。若实际发布条件变化，先调整发布安排，不临时引入补写或查询懒创建。

风险与编码防线：

| 风险 | 防线 |
|---|---|
| 默认组创建入口遗漏 | 删除 repository.create_user，三入口统一 provisioning |
| biz 反向依赖 app | 用默认组行加锁；app 组合 Biz initializer |
| 名称前后端计数漂移 | NFC + 同一 trim 集合 + 扩展字素簇；共享 JSON、依赖/浏览器版本验证；数据库不按码点限六 |
| 历史基础顺序变化 | ID 稳定序，时间仅展示/审计；逐用户有序序列对账 |
| 游标与排序漂移 | 单一 SortSpec 生成 order/cursor/predicate |
| 翻页期间外部数据变化 | 不承诺跨请求快照；本页写后重载，外部变化刷新收敛 |
| JS ID 舍入或请求类型被转换 | 全链路安全整数边界；JSON StrictInt、URL 显式解析、DTO 提交前校验 |
| 添加入口资格或幂等语义分叉 | 缺失目标关系统一资格校验；一个插入 helper，真实计数 |
| 单股添加断链或写状态重复 | Items 独占单股 PUT、Search 按组隔离；动作唯一所有者、Page 单次刷新协调 |
| 并发批量部分成功 | 组/成员锁、集合 SQL、单 commit、故障注入 |
| 删除后切错组 | 先锁默认组再读并锁清单；提交前构造 nextGroupId DTO |
| 详情过期预选或误清空 | 每次打开 GET，读取成功才建 draft；disabled + nonempty + 单事务 diff |
| 写已成功却报失败 | commit 前构造 DTO；写成功与刷新失败分开，未知结果先回读不重放 |
| 选择超过批量上限 | API rules 单源；第 201 次新增选择被阻止，取消/浏览始终可用 |
| downgrade 丢多组事实 | custom/pin guard，生产只前向修复 |
| 混合版本不可用 | 暂停写入、同窗口发布、无兼容层 |

## 21. 待拍板与版本记录

两轮修订及本次两项准入处理均已获用户确认。本次仅完成名称依赖准入、共享样本及搜索合同勘误，不提交，不把准入验证表述成业务功能完成。

### 21.1 十项修订对账

| 编号 | 已确认处理 | 技术方案章节 | 本 LLD 落点 | 后续开发必须验证 |
|---|---|---|---|---|
| 1 | 创建/删除先锁默认组，再读清单；其余组按 ID，先组后成员 | 7.1～7.4、12.2 | 9.1、11 | 创建/删除/批量并发、next group、上限 |
| 2 | 保留原头部，下方追加操作栏 | 8.2 | 13.1、16.5 | 头部内容、按钮状态、52px 操作栏和退出恢复 |
| 3 | commit 前 DTO；失败/刷新失败/未知分别处理 | 7.5、9.2 | 11.1、12、14、15 | 提交后零 SQL、失败回滚、丢响应、只重试读 |
| 4 | 扩展字素簇、统一 trim、不加标点白名单、修正数据库校验 | 3.1、10.2、14 | 4.1、7.2、16、17.2 | 共享向量、组合字符入库、实际依赖和浏览器 |
| 5 | 完整后端、前端、联调三个可验收阶段 | 13 | 18 | 完整应用加载和后端真实 API 不依赖下一阶段 |
| 6 | 本次无新注册作为发布前提，不新增封禁机制 | 12.1 | 20 | 迁移后用户—默认组对账；未来开通仍正确 |
| 7 | ID 表达稳定加入序，时间不参与排序/游标 | 3.3、3.5、6 | 4.3、5.3、10、16 | 历史有序序列、pin/unpin、同值分页 |
| 8 | rules 返回批量上限；上限后可取消/浏览 | 5.1、8.1、10.2 | 8.1、12.4、16.4 | 0/200/201、加载更多保留已选、后端反例 |
| 9 | 详情每次打开 GET，成功后建立 draft | 8.4 | 12.5、14、16.4 | 重复打开、读取失败、旧响应、无额外 PUT |
| 10 | 数据库约束/初始化/Service 各负其责，不增触发器 | 3.1、3.4、9.3 | 4.1、6、16.1 | 默认组禁删改、用户级联、缺组报错 |

上表是设计和计划测试对账，不是测试已执行记录。名称依赖准入现已完成，见第 21.3 节；后续业务开发与生产操作仍分别授权。

### 21.2 复审七项修订对账

| 编号 | 已确认处理 | 技术方案章节 | 本 LLD 落点 | 后续开发必须验证 |
|---|---|---|---|---|
| 1 | 只对实际新增目标关系复检资格，不合格整批回滚 | 5.4～5.6、7.3～7.4 | 7.3、11.4～11.8 | 退市既有关系可保留/移除；新增拒绝、源不丢失 |
| 2 | Items 接管单股添加；现有 Search 按组隔离 | 8.1 | 12.3、16.4 | 旧接线清零、当前排序刷新、搜索与未知回读 |
| 3 | JSON 严格整数，API ID 上限与 JS 安全整数一致 | 5、11.3 | 5.3、7.3、8.1、16.3 | 类型/上下界、迁移超界中止、提交前 DTO 校验 |
| 4 | 分页完整性以数据不变为前提，不引入快照机制 | 6.3、11～12 | 10.6、16.3～16.4 | 静态完整遍历、本页写后重载、外部变化刷新收敛 |
| 5 | 只存规范化 name，用 user_id/name 唯一约束 | 3.1 | 4.1、6.1、7.2 | NFC/trim 同名约束与默认身份一致 |
| 6 | 每个动作一个所有者、一个判别联合写状态 | 8.1、8.4 | 12、16.4 | 无重复提交/刷新，成功与读取失败可并存 |
| 7 | 单股/批量共用窄插入 helper，不另建 savepoint 路径 | 7.3 | 11.1、11.4～11.8、16.3 | 指定唯一冲突幂等，其它错误回滚，真实计数 |

以上是已确认的设计修订与待实施测试，不是代码或运行验收结果。七项修订本身不包含安装授权；后续用户单独授权的名称依赖准入记录如下。

### 21.3 开发准入处理记录（2026-09-08）

| 项目 | 实际结果 |
|---|---|
| 授权与范围 | 用户要求处理审计两项；仅依赖准入、文档勘误和验证样本，不含业务编码、生产操作或提交 |
| 安装位置 | 仓库现有 `.venv`，Python 3.13.5；未创建新环境 |
| 版本选择 | regex 2025.7.34，官方标明 Unicode 16.0；与当前 Node Unicode 16.0 基线对齐，固定版本避免无审计升级 |
| 安装与锁定 | `uv lock --no-python-downloads`；`uv pip install --python .venv/bin/python --no-deps --only-binary :all: regex==2025.7.34`；环境前后对账仅新增 regex，锁文件既有包版本不变 |
| 共享样本 | `tests/fixtures/wealth_watchlist_group_names.json` 已新增 24 例；raw/normalized/graphemeCount/accepted/reason 为测试预期，reason 不是新增 API 错误码 |
| 准入探针 | 24 例 + 25 个 trim 字符 + 1024/1025 字节边界，共 51 例；Python regex、Node Intl.Segmenter、本机真实 Chrome 三端全部匹配预期，覆盖 NFC、组合字素、标点、控制字符、孤立连接符/组合符、emoji、Unicode 16 新字母及非法 surrogate |
| 运行时 | Python 3.13.5 / unicodedata 15.1.0；regex Unicode 16.0；Node 24.5.0 / Unicode 16.0；Chrome 152.0.7977.82，console/pageerror 为 0 |
| 搜索合同 | 第 8.2、12.3.1、16.4 节一致要求 groupId 必填且匹配请求；generation 检查同时保留 |
| 安装后回归 | 现有 watchlist 模型、三个架构护栏、自选 API、用户仓储及三组认证/管理员测试共 63 项通过；仅有既有 Starlette/Alembic 弃用警告。`uv lock --check --offline`、文档完整性和 `git diff --check` 通过 |
| 验证边界 | 准入探针不是正式业务实现；模块代码、API groupId 校验、数据库名称写入及完整页面 smoke 均待开发，不宣称 v2 功能验收 |

本次临时探针位于 `/private/tmp/watchlist-name-admission.GjCkZh/probe.py` 和 `probe.mjs`，执行 `node /private/tmp/watchlist-name-admission.GjCkZh/probe.mjs`。它们只是本机准入证据，不作为生产依赖或永久测试入口；开发时 pytest/Vitest 必须消费工作区中的同一份 JSON 验证正式实现。

### 21.4 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v2.3 | 2026-09-08 | 完成 regex 本机准入和 51 例跨运行时验证，新增共享名称样本；明确搜索 groupId 必填/匹配与 generation 双重检查 | 用户 / Codex |
| v2.2 | 2026-09-08 | 回填复审七项：统一新增关系资格与插入路径，补齐单股添加链路，冻结严格安全整数及分页边界，删除重复名称字段和写状态 | 用户 / Codex |
| v2.1 | 2026-09-08 | 回填用户确认的十项修订，同步 ID 排序/游标、名称算法与存储、锁/写结果、前端状态、三阶段和逐项验证门禁 | 用户 / Codex |
| v2 | 2026-09-07 | 初稿：基于当前代码、CodeGraph 影响面、PRD/交互和技术方案形成低层设计；当时的五 Slice 安排由 v2.1 三阶段替代 | Codex |
