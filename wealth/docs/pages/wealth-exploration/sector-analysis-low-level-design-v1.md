# 财势探查｜板块分析低层设计 v1

## 0. 文档状态

- 状态：v1.35；既有动量排名 M0～M4、双动量 M5～M8 与相对轮动 M9～M12R 均已完成并关闭；成员广度 M14 后端、M15 前端、M16R 等价计算内核纠偏及 M16I 趋势查看均已完成本地代码与自动化收口。成员广度仍须部署 M16R+M16I 同一版本并完整重跑 M16，尚未交付。
- 编写日期：2026-08-30。
- 适用仓库：`/Users/congming/github/goldenshare`，当前开发分支 `dev-interface`。
- 产品依据：[财势乾坤板块分析产品交互基线文档](./sector-analysis-product-interaction-baseline-v1.md)。
- 技术依据：[财势探查｜板块分析技术实施方案 v1](./sector-analysis-implementation-design-v1.md)。
- Figma：`Goldenshare Web`，file key `RADlZzREU4lPVviYfkLy6x`，页面 `14 Wealth Exploration - Sector Analysis`（`965:2`）。
- 目标路由：`/wealth/exploration/sector-analysis/momentum-ranking`、`/wealth/exploration/sector-analysis/dual-momentum`、`/wealth/exploration/sector-analysis/relative-rotation`、`/wealth/exploration/sector-analysis/member-breadth` 四条精确路由均已实现。
- 目标 API：既有八只板块分析 API 保持不变；M14 新增 `/member-breadth/meta|rankings|details` 三只只读 API。
- 待拍板项：无。成员广度的日期检查、三指标独立缺失、复权因子边界、自动／历史日期语义和 MA60 两秒门禁均已确认；M14 不得自行扩大范围。

本文定义财势探查页面结构、已完成的“横截面动量排名”、M3A 三级行业成分股明细、“双动量”“相对轮动”和第四个独立方法“成员广度”的代码级方案。成员广度只描述成分股数量、成交额和均线位置三项客观参与度，不做综合分、预测、信号或发布。M14 已完成后端与三只只读 API，M15 已完成精确前端路由、controller 和正式工作区；M16 已验证生产事实与 payload，但真实性能失败并停止，M16R 已完成本地等价计算纠偏，M16I 已完成本地代码、自动化和浏览器验收。最终部署性能与页面验收仍未执行。量价分布继续不在本需求。M3A 成分股明细只是已选三级行业的事实下钻，不属于“成员广度”。

---

## 1. 冻结口径与开发约束

| 硬口径 | 编码落点 | 必须证明的正反例 |
|---|---|---|
| 只建设已批准的四个行业方法 | 四个独立 method feature 与 API | 只包含动量排名、双动量、相对轮动和成员广度；没有概念、地域、申万、Heat、预测、量价分布结果页或 QTF 依赖 |
| Prod 是唯一在线事实源 | 既有三个方法 Query + M3A 成员 Query + M14 成员广度 Query | 公共来源只含 `TradeCalendar`、`WealthSectorHierarchy`、`DcDaily`；`DcMember/EquityDailyBar` 用于 M3A 与成员广度，`EquityAdjFactor` 只允许成员广度的均线位置指标读取；不得放宽其它方法来源 |
| 公共业务日期唯一 | `MarketPageContextQuery` + URL `tradeDate` | Pre-M2 将内部访问收敛为 1 条 SQL；20:00 默认口径、显式历史严格命中和公开合同不变；前端无本机业务日计算 |
| 历史缺口必须可见 | Meta 日期覆盖 DTO + 日期选择器 | 覆盖区间内全部 SSE 开市日均返回；COMPLETE/PARTIAL/MISSING 不被过滤 |
| 五类比较池固定 | `SectorMomentumScope` + `resolve_scope_pool()` | 全体一级/二级/三级与两类直属子级集合完全正确 |
| 周期固定为 1/5/10/20/30 | `SectorMomentumPeriod` | 未批准周期和任意整数被拒绝 |
| 1 日读取 `pct_change`，多日读取完整 N+1 收盘窗口 | `SectorMomentumCalculator` | 缺任一日期、空值、非正收盘均不可计算，不补值 |
| 涨/跌只改变展示顺序 | `sort_ranking_rows()` | 同行业 `returnPct/strengthRank/percentile` 在两方向完全一致 |
| `strengthRank` 是唯一历史排名 | `rank_strength()` | 最高收益第 1，竞赛排名，历史接口无 direction |
| 完整列表，不做 TopN | rankings DTO + table | 返回当前比较池全部对象，null 行仍保留在末尾 |
| 三级成员使用来源全集 | members DTO + member table | 不套 Heat 有效池；B 股、停牌或行情缺口行保留并显示 `--` |
| 成员收益公式独立 | `SectorMemberReturnCalculator` | 1 日取 `pct_chg(t)`；多日逐日连乘；禁止复用行业首尾收盘价算法 |
| 成员事实版本一致 | members 必填 `hierarchyVersion` | 版本不一致返回 409；禁止把不同层级版本的榜单和成员拼接 |
| 成员局部状态隔离 | 独立 member controller/state | 成员 Loading/Empty/Error 不改变整页 READY/DELAYED，不遮蔽行业榜单和右侧详情 |
| 当前行业尽量保留 | URL reducer + controller | 日期、周期、方向、显示范围变化不擅自换行业 |
| 两图同时展示并联动 | `MomentumDetailPanel` | 同一交易日索引、独立纵轴、缺点断线、排名第 1 在顶部 |
| 1600 仅是像素基线，运行时必须等宽适配 | `sector-momentum.css` | 1600px 为 `776+12+776`；1512px 自动收缩且无裁剪；不得把 1564px 写成运行时固定宽度 |
| 页面状态只用五态 | API 四态 + 前端 LOADING | READY/DELAYED/EMPTY/ERROR；PARTIAL 只能作为日期覆盖元数据，不能成为第六种页面状态 |
| 双动量是独立方法 | 独立 route、Meta/Results、controller 和工作区 | 动量排名与双动量不能同时挂载；不得复制收益/排名公式或解释旧页面 DTO |
| 双动量周期与阈值固定 | period `5/10/20/30`；threshold `70/80/90` | 1 日、任意周期、任意阈值均拒绝；阈值相等时计入领先 |
| 双动量只描述当前状态 | `sector-dual-momentum@1` 分类器 | 不输出综合分、预测、信号、成功率、Lift 或发布状态 |
| 相对轮动是第三个独立方法 | `sector-relative-rotation@1` + 独立 route/API/controller | 不使用传统 RRG、不读取宽基、不与前两种方法混算 |
| 相对轮动只复用冻结动量事实 | `SectorMomentumCalculator.calculate_for_dates()/rank_strength()` | 不复制区间收益、百分位公式；前端不得计算 X/Y 或象限 |
| 相对轮动参数固定 | `period=5/10/20/30`、`lookback=5`、`trail=20/30/60`、`minGroup=3` | 1 日、任意 lookback/trail、任意分界值和页面自定义公式均拒绝 |
| 相对轮动原子响应 | Results 同时返回当前全量快照与一条选中轨迹 | 选中切换不能先换名称再显示旧轨迹；搜索/象限筛选/hover/放大零请求 |
| 成员广度三项事实独立 | `sector_member_breadth_calculator.py` | 数量、成交额、均线分别计算分母、资格和缺失；复权因子缺失不得污染前两项 |
| 成员广度日期检查随计算发生 | Meta 复用公共行业日期覆盖；Rankings／Details 使用公共页面日期并在合并窗口／成员 SQL 校验覆盖边界 | 禁止复制20:00规则、信任前端日期或让 Meta 扫描成员／行情／因子全历史；所选日期缺口按指标返回 |
| 成员广度复权均线 | `close × adj_factor` + 完整 N 日窗口 | 5/10/15/20/30/60；缺任一日只使该股票均线不可计算；现有 M3A 不读取因子 |
| 自动日期与历史日期分离 | Meta `dateContext` + URL 是否存在 `tradeDate` | 同一日期在自动回退时显示 Delayed，用户显式选择时不显示自动回退提示 |
| 成员广度性能分层 | Meta／非MA60 1秒，MA60 2秒 | Rankings 只算所选指标；MA60 放宽不得扩散到其他请求 |
| 未建设方法零副作用 | `SectorAnalysisMethodBar` | M15 前成员广度和量价分布只 toast；M15 后只剩量价分布 toast |
| 不新增持久化能力 | 复用既有 ORM；无迁移、表、缓存服务 | Alembic head 不变；无新 ORM model、Redis 或后台任务 |

公式身份固定：

```text
formulaKey = sector-cross-sectional-momentum
formulaVersion = 1
```

本版本描述当前和历史表现，不输出预测、信号、成功率、持续性或未来解释。

成员广度公式身份固定：

```text
formulaKey = sector-member-breadth
formulaVersion = 1
```

## 2. 当前实现审计

### 2.1 CodeGraph 与代码影响面

M1 开发前使用仓库根 CodeGraph 索引完成了入口、调用方、被调用方、共享契约、测试和前端消费者核验。索引状态为 healthy；M1 前基线主链为：

```text
WealthRouter
  -> routerState.isWealthExplorationPath
  -> WealthExplorationPage
      -> MarketPageContext API
      -> MajorIndices API
      -> TurnoverInsight controller

MarketOverviewPage
  -> market-overview/layout/ShortcutBar

sector-overview API
  -> MarketSectorOverviewQueryService
      -> SectorHierarchyQuery
      -> SectorSelectionResolver(SectorHierarchyNode)
```

M1 完成后的当前主链为：

```text
WealthRouter
  -> resolveWealthExplorationRoute
      -> WealthExplorationLandingPage
      -> TurnoverInsightPage
      -> SectorAnalysisPage
  -> WealthExplorationShell
      -> MarketPageContext API
      -> MajorIndices API

MarketOverviewPage
  -> MarketShortcutBar
      -> shared/ui/shortcut-bar
```

结论：页面结构、精确路由和共享 Shortcut 已完成；M2 已提供 meta/rankings/history 三个真实接口，M3 已实现动量排名结果工作区，M3A 已实现 members 第四接口、独立成员计算主链、成员局部 controller/state 和左栏下半区。M3 与 M3A 已于 2026-08-28 通过用户验收。

### 2.2 前端真实现状

1. `routerState.ts` 使用判别联合解析四个精确地址；未知 `/wealth/exploration/**` 不会被宽松吞入模块路由。
2. `/wealth/exploration`、`/turnover-insight` 和 `/sector-analysis/momentum-ranking` 分别由 landing、turnover、sector 三页承载；板块根地址以 `replace` 保留 query 后进入动量地址。
3. `WealthExplorationShell` 只加载公共时间和主要指数 ticker；入口首页没有成交额或板块业务请求。
4. `TurnoverInsightPage` 独占既有 `TurnoverInsightSection/controller`，接口、超时和 adapter 合同未变。
5. `SectorAnalysisPage` 已挂载真实动量排名 controller/workspace；一个 active 方法和四个“待建设”按钮仍保持，四按钮只产生本地 toast，不改变 URL，不发对应方法请求。
6. 市场总览六项数据已移入 `MarketShortcutBar`；共享卡片外层改为原生 button，内部 DOM/class、6 等分、10px 列距、12px 底距、最小高 72px 和内边距保持不变。
7. 旧 `WealthExplorationPage`、旧私有 Shortcut、零高度 `sector-radar` 节点和对应历史门禁已经删除，不留 wrapper 或 re-export。
8. `TopMarketBar`、`PageBreadcrumb`、market context 和主要指数 ticker 继续复用既有公共能力，没有复制或改契约。

### 2.3 后端真实现状

1. `DcDaily` 映射 `core_serving.dc_daily`，业务键为 `(ts_code, trade_date, category)`；本需求使用 `close/pct_change`，已有 `trade_date` 及 `(trade_date, category)` 索引。
2. `WealthSectorHierarchy` 映射 `core_serving.wealth_sector_hierarchy`，包含本需求所需层级、父级、root、路径、排序、版本和发布时间字段；已有 level/parent/root 三组查找索引。
3. `TradeCalendar` 映射 `core_serving.trade_calendar`，业务键 `(exchange, trade_date)`，已有 `trade_date` 索引。
4. `MarketPageContextQuery` 已实现 SSE 交易日和 20:00 默认切换。Pre-M2 已将显式模式最坏 2 条、默认模式最坏 4 条 SQL 收敛为 1 条只读 SQL；20:00 规则、公开方法、返回字段和消费者语义保持不变。
5. 当前工作区已把 `SectorHierarchyQuery` 移到 `queries/wealth/market/common/sector_hierarchy_query.py`，补齐父／root 名称、`is_leaf` 和最大 `published_at`；两个直接消费者均已切换到公共绝对 import，首页板块速览与架构回归 33 项通过。该独立完成项不等于 M2 API 已开始或完成。
6. 现有 `sector-overview` DTO 绑定首页 Top5、概念、地域、成员、资金和 Heat，不能扩写为本页 DTO。
7. `src/app/api/v1/router.py` 逐模块 include `src.biz.api.wealth.market.*`；板块分析只需新增一个 Biz router include，App 不承载业务逻辑。
8. `sector_analysis.py` 当前提供 meta、rankings、history 和 members 四类事实；members 使用独立 DTO、Query、Calculator、QueryService 和前端局部状态，不改变既有三类事实。
9. `DcMember` 已映射 `core_serving.dc_member`，业务键为 `(trade_date, ts_code, con_code)`，名称字段允许为空；`EquityDailyBar` 已映射 `core_serving.equity_daily_bar`，业务键为 `(ts_code, trade_date)`，`close/pct_chg` 均允许为空。M3A 复用现有 ORM，不新增模型或迁移。
10. 首页 `SectorMemberQuery.load_top()` 还会连接证券和停牌事实、最多返回 5 行并按单日涨跌幅排序；它只被首页板块速览消费，M3A 禁止修改、扩写或复用该 DTO。
11. 现有 `SectorMomentumCalculator` 的多日行业收益使用首尾收盘价比，不符合 M3A 已拍板的逐日 `pct_chg` 连乘；M3A 必须新增独立纯计算器。

### 2.4 当前状态与目标状态的差异

| 事项 | 当前代码 | 本期目标 | 处理方式 |
|---|---|---|---|
| 财势探查根页 | 纯入口首页（M1 已完成） | 纯入口首页 | 保持 landing 零业务请求 |
| 成交额路由 | `/turnover-insight`（M1 已完成） | 独立子页 | 保持既有业务合同 |
| 板块分析 | M2 三接口 + M3 动量工作区已实现 | 增加三级行业成员下钻 | 插入独立 M3A，不修改既有三个 endpoint 和右侧详情 |
| Shortcut | 共享展示 + 两个 feature wrapper（M1 已完成） | 零漂移共享能力 | 后续不得回写 feature 私有副本 |
| 行业层级 Query | Biz 公共 Query（当前工作区已移动） | Biz 公共 Query | M2 收口时再次回归首页板块速览，不再重复移动 |
| 动量事实 | meta/rankings/history 已实现 | 增加 members 第四个只读 API | 独立 query/calculator/service/DTO，不复用首页 Top5 |
| 页面异常态 | 整页五态已实现 | 增加成员局部四态 | 局部失败不得升级为整页 ERROR |
| 左栏 | 所有 scope 只有单行业榜单 | 两个三级 scope 使用上下双滚动 | 其他三个 scope 的 DOM、请求和尺寸保持不变 |

### 2.5 Prod DuckDB 只读覆盖证据

2026-08-27 用 DuckDB 1.5.5 `postgres` 扩展，通过现有 Web 只读连接直接附加 Prod，白名单只包含 `trade_calendar/wealth_sector_hierarchy/dc_daily`。审计没有写库、导出来源行或建立快照。

1. 当前层级为一级 31、二级 128、三级 337，共 496 个行业。
2. `2024-01-02..2026-08-26` 有 642 个 SSE 开市日、317,825 条当前行业池行情；重复业务键、非开市日行情、无效 close 和无效 pct_change 均为 0。
3. 20 个开市日存在 607 个行业日缺口：2026-05-20 缺 484、2026-05-18 缺 97、2026-05-25 缺 9，其余 17 日各缺 1。完整日期表见技术方案第 5.5 节。
4. 另有 14 个不属于当前发布层级的历史行情代码、7,216 行；它们不得进入当前行业池、覆盖分母或排名。
5. 以 2026-08-26 为结束日审计最近 60 个结束点：5 日完整窗口 29,760/29,760；10 日 29,249/29,760；20 日 24,391/29,760；30 日 19,531/29,760。历史缺口会真实传导到 N+1 可计算性。

这项审计关闭“是否存在缺口”的事实问题，但不关闭 M2 的实现验收：编码仍必须用同一门禁生成日期覆盖状态、空值行和断点，并通过正反例证明没有补值或隐藏缺口。

### 2.6 M3A Prod 成分事实审计

2026-08-28 使用现有 Web 只读连接审计当前 337 个三级行业、最近 30 个 SSE 开市日和目标日成员行情；只返回聚合数量和少量代码样本，没有写库、导出来源行或建立副本。

1. 最近 30 个开市日 `2026-07-17..2026-08-27` 共 10,110 个三级行业组日，成员快照缺失为 0。
2. 单行业成员数最小 1、P50 11、P95 约 55、最大 139；139 行冻结 DTO 估算约 `13.5KB`，低于 `256KB`，因此完整返回且不分页。
3. 目标日 5,641 条来源成员中 5,547 条有日行情，94 条无目标日行情：78 条 B 股、3 条停牌、13 条其他缺口。全部保留为来源成员并显示 `--`，不引入证券池、停牌补零或前向填充。
4. 1/5/10/20/30 日严格可计算数量为 `5,547/5,537/5,529/5,508/5,487`。
5. 两张来源表未发现重复业务键；目标日名称无空白，但 ORM 允许名称为空，DTO 必须允许 null。

该证据冻结 Members `<=4 SQL` 和完整列表设计；实现后仍需验证真实 API P95，不能用聚合审计替代部署态性能结论。

### 2.7 M5～M7 双动量代码与消费者审计

2026-08-28 在仓库根的最新 CodeGraph 索引上复核了后端 API、QueryService、Calculator、schema、前端路由、方法栏、URL 状态、controller、页面消费者和测试。索引状态为 up to date，共 2,787 个文件、49,059 个节点和 124,757 条边。

1. `SectorMomentumQueryService.build_rankings()` 已改为消费 `SectorMomentumSnapshotQueryService` 的不可变单日快照，只增加 `direction/listPosition` 和旧 Rankings DTO；双动量直接消费同一快照，不依赖旧页面响应。
2. `SectorMomentumCalculator` 已正确实现本需求所需的区间收益、竞赛排名和并列平均百分位。M6 必须复用该纯计算器；禁止复制公式、修改 `formulaVersion=1` 或在双动量分类器里重算收益和百分位。
3. 单日快照已一次加载公共日期、层级、比较池和行情，按 `(display_order, sector_code)` 保留全量事实行；既有 Rankings service 负责方向排序与旧 DTO，新 Dual service 负责状态分类与新 DTO。History 继续走原多日网格，未进入快照重构。
4. 公共 Meta service 已只输出日期、层级和覆盖事实；既有 Meta 与双动量 Meta 分别映射自己的 strict DTO，旧 Meta 的 `period=1/directions/historyRanges` 未泄漏到双动量。
5. 前端已具有 `sector-analysis-momentum` 与 `sector-analysis-dual-momentum` 两个精确路由；`SectorAnalysisPage` 通过显式方法判别只挂载一个 controller，`SectorAnalysisMethodBar` 对两个已建设方法执行真实导航，其余三个按钮继续仅触发“待建设”提示。
6. 现有动量 URL/parser/API/adapter/controller 都在 `momentum-ranking` feature 内，含方向、历史范围和成员事实；不得扩成带 method 分支的通用大 controller。双动量建立 feature-local 的 Meta/Results、URL 和状态边界。
7. CodeGraph 影响面确认 `SectorMomentumQueryService` 变化会传导到既有 meta/rankings/history API 与查询测试，`SectorMomentumCalculator` 会传导到 rankings/history 和计算测试；因此 M6 的硬回归是四个既有 endpoint 响应零变化和 calculator 全量测试，而不是只测新接口。
8. `SectorAnalysisMethodBar` 当前唯一页面消费者是 `SectorAnalysisPage`；`parseSectorMomentumUrlState` 的直接消费者是现有 controller 和测试。新增双动量独立 parser 可避免污染现有 URL 合同。
9. 双动量不需要 history、members、成分股、资金、Heat、QTF、DG/Lake 或数据库写入；其列表、摘要和散点图都由同一个 Results 全量响应派生。M5 没有发现需要新增配置、依赖、迁移、缓存、结果表或账号的理由。

### 2.8 M9 相对轮动代码、消费者与性能审计

2026-08-28 使用仓库根最新 CodeGraph 索引（up to date，2,816 files、49,716 nodes、126,302 edges）和当前源码完成实现前影响面核验。审计覆盖 `SectorMomentumCalculator`、`SectorMomentumQuery`、`SectorMomentumSnapshotQueryService`、动量／双动量 QueryService、Biz router/schema、`SectorAnalysisPage`、方法栏、前端路由、双动量独立 controller／adapter／SVG 以及全部直接测试消费者。

1. `SectorMomentumCalculator.calculate_for_dates()` 已能在一个内存事实索引上批量生成多个目标交易日的完整 N 日收益；`rank_strength()` 已固定最强 100、最弱 0、并列平均百分位和 0.1 精度。相对轮动只能组合这两项公开纯计算能力，不能调用 `SectorMomentumQueryService` 的私有 `_rank_by_date()`，也不能复制公式。
2. `SectorMomentumSnapshotQueryService.prepare_for_context()` 已按“公共日期→层级版本→比较池→目标日解析”返回不可变准备事实。相对轮动可以复用该公开方法完成前三项 SQL 与版本前置门禁，但不能循环调用 `build_prepared()`，否则会为每个轨迹日期重复读取开市日和行情。
3. `SectorMomentumQuery.load_open_dates()` 当前明确拒绝 `count>90`；M10 只允许把该上限和错误文案精确改为95，并增加96拒绝反例。既有 History 最大请求仍为90，不得改变其输出或允许任意窗口。
4. 正常 Results 的真实 SQL 形态可以固定为5条：公共 page context 1条、层级 1条、目标日解析 1条、95日交易日 1条、当前比较池行情 1条。`dc_daily` 必须只出现一条集合查询，禁止按日期、行业或轨迹点循环读取。
5. `SectorMomentumQueryService.build_history()` 已有多日网格思路，但还会为了详情摘要并入全层级／父级池，且 DTO 是单行业收益与排名趋势，不符合相对轮动的“当前全池 + 一条轨迹”原子合同；不得复用或扩写该 endpoint。
6. `SectorDualMomentumQueryService`、schema、adapter、URL 和 controller 提供了专属方法分层、strict DTO、5秒超时、409重载、过期响应丢弃和按需挂载范式。相对轮动应复制职责形态而不是复制业务字段或在其中增加 method 分支。
7. M9 审计时，`SectorAnalysisPage` 和 `SectorAnalysisMethodBar` 的可用方法类型只包含 `momentum-ranking | dual-momentum`，`WealthRouter/routerState` 也只有两个精确方法路由；因此 M11 必须一次性增加第三个判别分支，并在当时继续让成员广度和量价分布保持零请求 toast。该历史事实已由 M11 和 M15 依次推进为当前四条正式方法路由，只有量价分布仍保持 toast。
8. `tests/architecture/test_wealth_sector_analysis_guardrails.py` 已把板块分析来源全集冻结为五张表，但相对轮动方法级白名单仍需单独限制为前三张；同时需要把相对轮动文件加入禁止 QTF/DG/Lake/预测/持久化扫描。
9. 中央注册表原先把 `SA_FACT_VERSION_MISMATCH` 写成“双动量专用”，与技术方案要求的同语义复用冲突。本轮已把它收敛为双动量／相对轮动 Results 共用的页面级层级版本冲突；成员局部请求仍单独使用 `SA_MEMBER_FACT_MISMATCH`，没有新增异常码。
10. 配置审计结论为“不适用”：period、5日改善、trailLength、最小组规模、X轴范围和分界线都是版本化公式合同；本期不增加 env、Settings、数据库配置、配置文件、运营开关或页面常量的第二事实源。

M9 最大窗口使用现有 Web 只读连接做了有界核验：只读当前发布的337个三级行业、最近95个 SSE 开市日，事实行31,614条；不导出来源行、不保存快照。结果如下：

| 证据 | 结果 | 结论 |
|---|---:|---|
| SQL 数 | 5 | 通过 |
| `dc_daily` 行数 | 31,614（理论上限32,015） | 有界 |
| 目标计算日期 | 65（60轨迹+5比较前沿） | 与公式一致 |
| 冻结 DTO 估算最大响应 | 159,859 bytes | 通过256KB |
| 数据库5条 SQL 的 `EXPLAIN ANALYZE` 执行合计 | 91.868ms | 通过分段预算 |
| 纯计算+DTO/JSON 50次 P95 | 107.363ms | 通过分段预算 |
| 同拓扑核心链路估算 P95 | 199.231ms | 低于500ms，允许进入 M10 |
| 本机跨网络全链20次 P95 | 2,343.531ms | 只记录网络诊断，不冒充部署态 P95 |

分段估算只关闭 M10 的“方案是否明显不可行”门禁，不代替 M12 的部署态真实 HTTP P95。M10 不得以该结果为由删减行业、轨迹或字段，也不得引入缓存、索引、结果表或分页。

### 2.9 M13 成员广度代码、消费者与性能审计

2026-08-29 使用仓库根最新 CodeGraph 索引（up to date，2,833 files、50,270 nodes、126,705 edges）、当前源码和 Prod 只读 `EXPLAIN ANALYZE` 完成编码前审计。影响面只包括 Biz 板块分析 API／schema／query／service、中央异常注册表、Wealth 板块分析路由／方法栏／页面及新增 feature；Foundation 模型、同步、Ops、QTF、DG/Lake、首页板块速览和三个已完成方法不需要修改。

1. M13 审计时没有成员广度 API、schema、query、calculator、service、route、controller 或运行页面；M14 已新增独立后端合同与三只 API，M15 已新增第四条精确 route、独立 API/adapter/URL/controller/feature，并从 `SectorAnalysisMethodBar` 移除成员广度“待建设”行为。既有方法 DTO 未被偷渡成员广度字段。
2. `SectorMemberDetailQueryService` 只服务 M3A 三级行业成员明细：最多30日，只读取目标日成员和 `close/pct_chg`，区间涨跌幅使用逐日 `pct_chg` 连乘，不读取复权因子。它没有五类比较池、历史逐日成员、成交额或均线语义，M14 必须建立独立链路。
3. `core.equity_adj_factor` 是本需求唯一复权因子表；均线位置使用 `close × adj_factor`。任何窗口日缺价格或因子，只使对应股票的均线事实不可计算，不影响该股票的数量／成交额事实，也不使整个日期回退。
4. 现有 `SectorTradeDateAvailabilityDto` 只能表达当前行业 `dc_daily` 的 `COMPLETE/PARTIAL/MISSING`，不能同时表达“三项成员指标各自可用性”。成员广度 Meta 只复用它作为公共交易日期覆盖；Rankings／Details 使用自己的指标可用性合同，禁止改写这个既有公开 DTO。
5. URL 中是否存在 `tradeDate` 是自动日期与显式历史的唯一判别。Meta 根据公共行业日期覆盖返回 `expectedTradeDate/defaultTradeDate/defaultStatus`；Rankings／Details 只计算显式传入的实际日期，不根据相同日期值猜用户意图。
6. Meta 若按410个历史交易日逐日检查496个行业成员，数据库阶段约8.95秒；即使改成逐键探测也约3.11秒。该设计已否决。Meta 只能执行公共日期、层级和 `dc_daily` 覆盖三条 SQL，零成员／行情／因子历史扫描。
7. 目标日496行业成员覆盖检查约6ms；真正计算时做所选日期和有界窗口检查不会增加无意义的全表预扫。成员数和成交额只需要目标日；MA 需要成员股票的 N 日价格和因子。
8. 最新三级全榜5,641只成员的 MA60 原始窗口约331,327股票日行；数据库 join 约3.99秒，按目标投影聚合约1.54秒。用户已接受 MA60 部署稳态 P95 `<=2,000ms`；Meta、非MA60 Rankings／Details 仍为 `<=1,000ms`。
9. Rankings 必须只计算请求中的一个指标，不能为了“顺便返回三项可用性”让数量榜或成交额榜等待均线。Details 的正式交互同时展示三项组成与趋势，因此按所选 `maPeriod` 计算三项事实，MA60 使用两秒门禁。
10. 最大来源成员 Details 为625只；119日价格／因子窗口查询约366ms，具备按请求集合计算可行性。M14 不新增索引、缓存、结果表、分页、截断、迁移或后台任务。

## 3. Figma 开发交付审计

### 3.1 正式节点基线

| 状态 | 节点 | 尺寸 | 用途 |
|---|---|---:|---|
| Ready／一级总榜涨幅 | `965:55` | 1600×1292.390625 | 默认视觉基线 |
| Ready／一级总榜跌幅 | `971:352` | 1600×1292.390625 | 方向切换 |
| Ready／二级总榜 | `1051:951` | 1600×1292.390625 | 全部二级、所属一级路径和双排名摘要 |
| Ready／三级总榜 | `1051:1251` | 1600×1292.390625 | 全部三级；左栏上下双滚动，成员面板 `1085:1268` |
| Ready／一级内二级 | `987:476` | 1600×1292.390625 | 单父级选择器及下钻结果 |
| Ready／二级内三级 | `987:776` | 1600×1292.390625 | 两级联动；左栏上下双滚动，成员面板 `1088:1268` |
| Ready／双图 Hover | `1053:5261` | 1600×1292.390625 | 两图同日期十字线和联合 Tooltip |
| Ready／交易日选择器 | `1062:2` | 1600×1292.390625 | COMPLETE/PARTIAL/MISSING 可见且均可选择 |
| Loading | `1036:634` | 1600×1292.390625 | 稳定骨架加载态 |
| Delayed | `1036:1014` | 1600×1292.390625 | 保留上一完整交易日内容 |
| Empty | `1036:1386` | 1600×1292.390625 | 全部不可计算或显式日无数据 |
| Error | `1036:1762` | 1600×1292.390625 | 错误与重试 |

`1292.390625px` 是现有 Figma 内容边界形成的画板高度，不是运行时固定高度合同。编码只把 `1600px` 作为桌面截图验收宽度，并按下文整数尺寸实现内部骨架；页面根节点不得写死 `height:1292.390625px`，应由内容高度和现有页面 Shell 自然撑开。

双动量旧草稿 `967:72` 已冻结并移出正式画板区域，不得作为编码依据。双动量唯一正式基线为：

| 状态 | 节点 | 编码用途 |
|---|---|---|
| Ready／符合条件 | `1096:1267` | 默认一级总榜、20 日、80% 阈值 |
| Ready／全部行业 | `1101:5478` | 同一 Results 本地切换完整列表 |
| Ready／一级内二级 | `1103:1425` | 所选一级直属二级池 |
| Ready／二级内三级 | `1104:1898` | 所选二级直属三级池 |
| Ready／二级总榜 | `1105:1583` | 全部二级同组比较 |
| Ready／三级总榜 | `1105:1938` | 全部三级同组比较 |
| Ready／Hover | `1106:1741` | 散点 Hover 与列表联动 |
| Ready／Partial Data | `1106:2109` | 有可用事实时的局部覆盖提示 |
| Loading | `1106:2528` | 稳定工作区骨架 |
| Delayed | `1106:7209` | 上一完整交易日事实与实际日期提示 |
| Empty | `1106:2713` | 比较池零个可计算对象 |
| Error | `1106:2894` | 合同或查询失败与重试 |
| Ready／Small Group | `1107:2216` | 可计算对象少于 3，只展示事实不判定资格 |
| Ready／No Qualified | `1115:2295` | 有可计算事实但零符合条件对象 |
| Ready／Missing Selected Coordinate | `1115:2571` | 所选行业可保留，但散点不伪造坐标 |

上述 15 张正式页面均为 `1600×1292.390625`，双动量工作区实例为 `1564×1006`，组件集为 `1132:9777`，交互说明节点为 `1137:422`。运行时继续使用等宽弹性 Grid，不把 1564px 写成固定宽度。

相对轮动旧草稿 `967:158` 已冻结并移出正式交付区；成员广度和量价分布的 `967:244/967:330` 继续只是 Draft 按钮占位。相对轮动唯一正式基线为：

| 状态 | 节点 | 编码用途 |
|---|---|---|
| Ready／一级总榜 | `1150:5870` | 默认一级总榜、20日强度、20日轨迹 |
| Ready／二级总榜 | `1152:6286` | 全部二级行业同组轮动 |
| Ready／三级总榜 | `1152:7139` | 337个三级行业密集点与完整列表 |
| Ready／一级内二级 | `1152:7994` | 所选一级直属二级池 |
| Ready／二级内三级 | `1152:8838` | 两级联动后的直属三级池 |
| Ready／Hover | `1154:7772` | 单点 Tooltip，不常驻全部名称 |
| Ready／Small Group | `1155:8264` | 坐标可绘制但不解释象限 |
| Ready／Missing Selected Coordinate | `1156:8578` | 全池保留、选中轨迹断线／不可绘制 |
| Delayed | `1156:13471` | 最近完整盘后日与实际日期提示 |
| Ready／放大图 | `1157:9236` | 与普通图共用同一坐标范围 |
| Loading | `1158:9938` | 保留方法栏和工具栏的稳定骨架 |
| Empty | `1158:10319` | 显式缺失或全池无当前百分位 |
| Error | `1158:10707` | 安全文案与重试 |
| Ready／Filtered | `1161:10430` | 列表局部搜索／象限过滤，图中全量点不变 |

相对轮动组件交付根为 `1148:5611`，状态徽标集为 `1148:5622`，列表行集为 `1148:5647`。14张页面均为 `1600×1292.390625`，工作区为 `1564×1006`；页面普通布局使用 Auto Layout，四象限绘图区和放大图内部坐标保留绝对定位。

### 3.2 结构与 Design System 结论

1. 正式画板直接复用 `TopMarketBar` 实例、`PageBreadcrumb` 实例、`ShortcutCard` 实例和方法 Tab 组件实例。
2. PageShell 使用纵向 Auto Layout；`1600px` 验收基线下左右工作区为 `776 + 12 + 776 = 1564px`，运行时两列使用等分弹性轨道，不得固定为 776px。
3. `1600px` 基线下工具栏为 `1564×128`、正文为 `1564×866`；运行时宽度均为当前 PageShell 内容宽度的 `100%`，高度不变。
4. 一级、二级和一级内二级继续使用单榜单左栏：`1600px` 基线下榜单滚动 viewport 为 `776×772`；运行时宽度随左列变化，高度仍为 772px。固定表头高 40px、行高 56px、`clipsContent=true`、`overflowDirection=VERTICAL` 不变。
5. 三级总榜和二级内三级的左栏包装节点分别为 `1085:1267/1088:1267`，均为 `776×866` 纵向 Auto Layout：上部行业榜单 `776×390`、间距 `12`、下部成员面板 `776×464`。成员面板包含 54px 标题、40px 固定表头和 370px 纵向滚动 viewport，成员行高 48px。
6. 图表、涨跌数据条和滚动条叠层保留绝对坐标。它们是几何绘图区，不应改成 Auto Layout。
7. 页面普通容器、工具栏、行、摘要卡、状态面板均使用 Auto Layout；不存在用补偿坐标模拟页面布局的新增节点。
8. 核心颜色已绑定 `CSQ / Market Overview / M0 / Color` 变量；Delayed 新增语义变量 `System/Warning`（`VariableID:1033:2`，`#f59e0b`），Web syntax 为 `var(--cs-color-warning)`，scope 覆盖 Frame/Shape/Text Fill 和 Stroke。
9. Shortcut 外层容器已从原始色值绑定到 `Background/Panel` 和 `Border/Subtle`。
10. Loading skeleton 已绑定 `Background/PanelSoft`；Error 重试复用 `Button / Neutral / M0`。
11. 模块自有正式文本已绑定可精确匹配的本地 Text Style；共享 TopMarketBar 和 ShortcutCard 内仍有少量继承自既有组件的原始色值和无 textStyleId 文本。它们是现有共享组件债务，本期不修改，否则会扩大到全站；其实际颜色与 Web Token 一致，不阻塞本模块编码。

### 3.3 已修正的问题

| ID | 原问题 | 严重度 | 修正结果 |
|---|---|---|---|
| F01 | 列表“排名”与详情“当前排名”混淆展示序号和业务排名 | 高 | 改为“序号”与“同组强度排名” |
| F02 | 上下两图各有一套 20/30/60 控件，可能形成两套显示范围 | 高 | 每张 Ready 画板只保留上图一套共用控件 |
| F03 | viewport 只有手绘滚动条，没有 Figma 纵向滚动语义 | 高 | 六类 Ready 榜单画板均设置 `VERTICAL` overflow |
| F04 | 只有 Ready，没有 Loading/Delayed/Empty/Error 正式页 | 高 | 新增四张完整正式状态画板 |
| F05 | 图题“历史排名”未说明范围，滚动收益未显示计算周期 | 中 | 标题改为周期和比较范围专属文案 |
| F06 | Shortcut 外层未绑定变量 | 中 | 绑定 Panel/Subtle Token |
| F07 | 本地 Breadcrumb 组件横向溢出 section 32px | 中 | `966:55.x` 从 32 改为 0 |
| F08 | Loading skeleton 继承白色底和原始灰 | 中 | 清除白底并绑定 PanelSoft |
| F09 | 涨跌榜把展示序号误当业务排名，百分位端点不符合公式 | 高 | 跌幅最弱示例改为 `31/31、0.0%`，涨幅最强示例改为 `100.0%`；方向只改变展示顺序 |
| F10 | 缺二级／三级总榜和双排名摘要 | 高 | 新增 `1051:951/1051:1251`；二／三级同时表达全层级和直属父级排名 |
| F11 | 四个待建设按钮跳草稿，行选择与下钻边界不清 | 高 | 清除草稿导航；行点击只选中，独立箭头下钻，三级明确无下钻 |
| F12 | 两图共用范围和 Hover 无正式编码状态 | 高 | 六张 Ready 均标注“两图共用”；新增 `1053:5261` 展示共享十字线和联合 Tooltip |
| F13 | 一级排名轴只到 20，无法表达 31 个对象 | 高 | 涨／跌与 Hover 纵轴完整覆盖 `1..31`；二／三级总榜分别覆盖 `1..128`、`1..337` |
| F14 | Warning Token 和模块文字样式未完成开发交付绑定 | 中 | 补 Web syntax/scope；模块自有正式文本绑定本地 Text Style，不拆共享实例 |
| F15 | 日期字段只表达当前值，无法看到缺口日 | 高 | 新增 `1062:2`；Popover 使用真实覆盖示例显示日期、完整／部分缺失／无数据图例及 `valid/expected`，所有状态均可选择 |
| F16 | 选中三级行业后无法继续查看成分明细 | 高 | `1051:1251/987:776` 左栏改为 `390+12+464` 双滚动；下部四列显示完整来源成员、目标日收盘价和当前周期涨跌幅 |

### 3.4 Figma 基线与运行时响应式映射

| Figma 区域 | 代码约束 |
|---|---|
| 1600 根画板 | 设计验收宽度，不是运行时固定宽度；运行时外壳使用现有 content max/min Token，不做 CSS scale，不写死 Figma 小数画板高度 |
| PageShell | `padding: 14px 18px 34px`，纵向 12px 基础节奏 |
| ShortcutBar | 1600 基线宽 1564px，运行时跟随 PageShell 为 `width:100%`；卡间 10px、当前两卡保持卡宽约 252.33px，不强制两卡拉满整行 |
| 方法栏 | 高 48px、内边距 4px、按钮间 4px |
| 工具栏 | 1600 基线为 1564×128；运行时 `width:100%`，16px 内边距、两行各 44px、行间 8px |
| 分析正文 | 1600 基线为两列各 776px；运行时 `repeat(2,minmax(0,1fr))`、列间 12px、高 866px |
| 单榜单左栏 | 仅一级、二级、一级内二级；运行时宽度等于左列；标题 54px、固定表头 40px、viewport 高 772px、行 56px |
| 三级双列表左栏 | 仅三级总榜、二级内三级；总高 866px，上榜单 390px、间距 12px、下成员 464px；两个 viewport 独立纵向滚动 |
| 成员表 | 标题 54px、固定表头 40px、viewport 370px、行 48px、左右内边距 12px；表头与行共用同一响应式 Grid |
| 详情摘要 | 1600 基线 776×112；运行时 `width:100%`、高度 112px |
| 趋势图 | 1600 基线每图 776×365；运行时 `width:100%`、高度 365px、图间 12px |
| 状态面板 | 运行时 `width:100%`、高 866px，替换正文但保留工具栏及页面骨架 |

Figma 是视觉和布局事实源；交互状态、数据语义、缺失处理和请求边界以产品基线与本 LLD 为准。不得从示例文字、示例日期或示例行业推导生产默认值。

运行时宽度计算固定为：

```text
shellOuterWidth = min(max(viewportWidth, 1460), 1840)
contentWidth = shellOuterWidth - 36
columnWidth = (contentWidth - 12) / 2
```

在 1600px 下列宽为 776px；约 1512px 下列宽为 732px。低于全局 1460px 最小宽度时沿用全站页面级横向滚动，不允许本模块另加 CSS scale、固定 1564px 宽度或独立响应式断点。

Selected Summary 的 Identity 额外使用 `ResizeObserver` 观察自身尺寸，并以真实 DOM 溢出决定字号，不读取浏览器视口宽度：

1. 每次行业、层级路径或 Identity 宽度变化时，先移除 compact/extra-compact，以设计稿字号测量行业名和完整层级路径的 `scrollWidth/clientWidth`。
2. 两者均完整容纳时维持行业名 `17px`、层级路径 `11px`；任一文本溢出时设置 compact，行业名改为 `14px`、层级路径改为 `9px`，等级标签同步收紧为 `10px` 和 `2px 5px` 内边距。
3. compact 应用后必须立即再次测量；若行业名或路径仍溢出，则增加 extra-compact，行业名改为 `12px`、路径改为 `8px`，等级标签改为 `9px` 和 `2px 4px` 内边距。
4. 容器再次变宽时必须从设计稿字号重新测量；宽度足够后自动退出两级 compact，不能永久停留在小字号。
5. 等级标签始终 `white-space:nowrap` 且不得参与 flex 收缩；行业名和层级路径在 extra-compact 后仍保留 Tooltip/省略保护，只用于防御超过当前正式名称长度的异常数据。

成分股四列在 Figma `776px` 基线内为 `240/176/144/192`，只定义相对比例。代码统一使用：

```css
grid-template-columns:
  minmax(0, 240fr)
  minmax(0, 176fr)
  minmax(0, 144fr)
  minmax(0, 192fr);
```

同一声明必须同时用于表头和每一行。名称列单行省略并提供 Tooltip；代码、收盘价和涨跌幅禁止换行，后三列右对齐。运行时不得写死 752px，否则在 1512px 视口下左栏内容宽约 708px 时会溢出。

## 4. 目标调用链

```mermaid
flowchart LR
  A[WealthRouter] --> B[resolveWealthRoute]
  B --> C[WealthExplorationShell]
  C --> D[SectorAnalysisPage]
  D --> E[useMomentumRankingController]
  E --> F[sectorAnalysisApi]
  F --> G[sector_analysis Biz router]
  G --> H[SectorMomentumQueryService]
  H --> I[MarketPageContextQuery]
  H --> J[SectorHierarchyQuery]
  H --> K[SectorMomentumQuery]
  K --> L[TradeCalendar + DcDaily]
  H --> M[SectorMomentumCalculator]
  M --> N[Status + strict DTO]
  N --> O[Adapter + view model]
  O --> P[Ranking table + linked SVG charts]
```

页面壳只加载 page context 和 ticker；业务 controller 只由对应子页挂载。Backend API 不访问 Ops、TaskRun、QTF、DG 或 Lake。

## 5. 文件级编码矩阵

### 5.1 前端移动与共享提取

| 操作 | 文件 | 精确要求 |
|---|---|---|
| 新增 | `wealth/src/shared/ui/shortcut-bar/shortcutBarTypes.ts` | 定义 `ShortcutItem` 和 key/path/title/description；无 feature 常量 |
| 新增 | `wealth/src/shared/ui/shortcut-bar/ShortcutCard.tsx` | 外层使用真实 `<button type="button">`；保留既有内部 DOM/class；接收 selected/disabled/onSelect |
| 新增 | `wealth/src/shared/ui/shortcut-bar/ShortcutBar.tsx` | 接收 items/activeKey/onNavigate；不决定业务路由 |
| 新增 | `wealth/src/shared/ui/shortcut-bar/shortcut-bar.css` | 原样迁移 `.shortcut-*` 视觉；补 button reset、focus-visible，不改尺寸 |
| 删除 | `wealth/src/features/market-overview/layout/ShortcutBar.tsx` | 全部消费者切换后彻底删除，不留 wrapper/re-export |
| 修改 | `wealth/src/pages/market-overview/market-overview-page.css` | 只删除已迁移 Shortcut 规则；其它 CSS 字节级保持 |
| 新增 | `wealth/src/features/market-overview/layout/MarketShortcutBar.tsx` | 保留当前六项数据和 toast 行为 |
| 修改 | `wealth/src/pages/market-overview/MarketOverviewPage.tsx` | 仅切换 wrapper import；渲染顺序不变 |

共享组件只把最外层 `article` 更正为 `button`，内部两层 DOM、全部 class、选中伪元素和视觉尺寸必须不变。CSS 必须增加 `appearance:none; color:inherit; font:inherit; text-align:left; width:100%`，避免浏览器默认按钮样式造成漂移。技术方案所称“保留 DOM”在编码中具体指保留内部结构和 CSS 选择器，不保留缺少键盘语义的错误外层标签。

### 5.2 财势探查页面结构

| 操作 | 文件 | 精确要求 |
|---|---|---|
| 新增 | `wealth/src/pages/wealth-exploration/layout/WealthExplorationShell.tsx` | TopBar、context、ticker、breadcrumb、shortcut、toast 和 children slot |
| 新增 | `wealth/src/pages/wealth-exploration/layout/useWealthExplorationShell.ts` | 迁移现页 context/ticker 两段请求；不加载业务模块 |
| 新增 | `wealth/src/features/wealth-exploration/navigation/explorationNavigation.ts` | 两个入口的唯一配置和正式 path |
| 新增 | `wealth/src/features/wealth-exploration/navigation/ExplorationShortcutBar.tsx` | 组合共享 Shortcut；入口首页 activeKey=null |
| 新增 | `wealth/src/pages/wealth-exploration/WealthExplorationLandingPage.tsx` | 只渲染 Shell，无业务请求 |
| 新增 | `wealth/src/pages/wealth-exploration/TurnoverInsightPage.tsx` | Shell + 既有 `TurnoverInsightSection/controller` |
| 新增 | `wealth/src/pages/wealth-exploration/SectorAnalysisPage.tsx` | Shell + 方法栏 + 当前动量工作区 |
| 删除 | `wealth/src/pages/wealth-exploration/WealthExplorationPage.tsx` | 三个新页面接管全部用途后删除，不保留兼容页面 |
| 修改 | `wealth/src/pages/wealth-exploration/wealth-exploration-page.css` | 删除零高度 slot，增加 Shell/shortcut/method/workspace 布局；复用 Token |

### 5.3 前端路由

| 操作 | 文件 | 精确要求 |
|---|---|---|
| 修改 | `wealth/src/app/routes/routerState.ts` | 新增正式常量、路径 builder 和有界 route resolver |
| 修改 | `wealth/src/app/routes/WealthRouter.tsx` | 按判别联合类型渲染三个页面；sector-analysis 根 path replace 到 momentum path |
| 修改 | `wealth/src/app/routes/routerState.test.ts` | 正反例覆盖精确路径、未知子路径、query 保留和 replace |

不得继续扩写一个返回 boolean 的宽松 `isWealthExplorationPath()`。目标解析器：

```ts
type WealthExplorationRoute =
  | { kind: "landing" }
  | { kind: "turnover-insight" }
  | { kind: "sector-analysis-redirect" }
  | { kind: "sector-analysis-momentum" }
  | { kind: "not-exploration" };

resolveWealthExplorationRoute(pathname: string): WealthExplorationRoute
```

精确路由常量：

```text
/wealth/exploration
/wealth/exploration/turnover-insight
/wealth/exploration/sector-analysis
/wealth/exploration/sector-analysis/momentum-ranking
```

未知 `/wealth/exploration/**` 必须返回 `not-exploration`，证明它没有被误识别为本模块路由；本期继续保留 Router 当前既有 fallback，不顺手新增全站 404 或错误路由框架。

### 5.4 后端公共查询移动（M2 已完成，不得重复执行）

| 操作 | 文件 | 精确要求 |
|---|---|---|
| 新增 | `src/biz/queries/wealth/market/common/sector_hierarchy_query.py` | 原类完整移动；Node 补齐父/root 名称和 `is_leaf`，Snapshot 增加 `published_at` 元数据 |
| 删除 | `src/biz/queries/wealth/market/sector_overview/sector_hierarchy_query.py` | 消费者和测试改完后删除，无兼容 re-export |
| 修改 | `sector_overview/sector_overview_query_service.py` | 相对 import 改为 common 绝对 import；行为不变 |
| 修改 | `sector_overview/sector_selection_resolver.py` | `SectorHierarchyNode` 改为 common import |

上述移动已经完成。M3A 只复用公共查询的单一版本、代码唯一、一级 root、父级层次、root 闭包和稳定排序结果，并以现有 `baseline_version` 校验 members 请求；不得再次移动文件、增加兼容 re-export 或改变首页选择和错误语义。

### 5.4A Pre-M2 公共日期查询收敛

| 操作 | 文件 | 精确要求 |
|---|---|---|
| 修改 | `src/biz/queries/wealth/market/context/market_page_context_query.py` | 保持公开合同和 20:00 语义不变，把单次 `resolve_context()` 收敛为 1 条只读 SQL |
| 新增 | `tests/test_wealth_market_page_context_query.py` | 注入固定北京时间，覆盖时间边界、显式／默认、日历缺失和 SQL 数量 |
| 修改 | `tests/web/test_wealth_market_context_api.py` | 保持公共 context HTTP 响应合同不变，补充 20:00 前后和无日历记录反例 |

Pre-M2 不修改任何调用方 API，不新增模型、迁移、缓存或配置。CodeGraph 当前确认的 9 个直接调用入口全部继续调用同一个 `resolve_context()`；实施后必须回归公共 context、个股详情、指数详情／K 线／权重、成交额洞察、个股九转和指数九转。

### 5.5 后端新增

```text
src/biz/api/wealth/market/sector_analysis.py
src/biz/schemas/wealth/market/sector_analysis.py
src/biz/queries/wealth/market/sector_analysis/
  __init__.py
  sector_analysis_meta_query.py
  sector_momentum_query.py
  sector_momentum_query_service.py
src/biz/services/wealth/market/sector_analysis/
  __init__.py
  sector_analysis_exception_builder.py
  sector_analysis_status_resolver.py
  sector_momentum_contract.py
  sector_momentum_calculator.py
```

只使用一个 Biz router 文件，避免两个 endpoint 文件分别复制参数验证。`src/app/api/v1/router.py` 只增加一次 import 和 include。

### 5.6 前端板块分析新增

```text
wealth/src/features/wealth-exploration/sector-analysis/
  navigation/
    SectorAnalysisMethodBar.tsx
  momentum-ranking/
    api/
      sectorMomentumApi.ts
      sectorMomentumAdapter.ts
    model/
      sectorMomentumTypes.ts
      sectorMomentumUrlState.ts
      useMomentumRankingController.ts
    ui/
      MomentumRankingWorkspace.tsx
      MomentumControlBar.tsx
      MomentumRankingPanel.tsx
      MomentumRankingTable.tsx
      MomentumRankingRow.tsx
      MomentumReturnBar.tsx
      MomentumDetailPanel.tsx
      SelectedSectorSummary.tsx
      RollingReturnChart.tsx
      HistoricalRankChart.tsx
      MomentumLinkedTooltip.tsx
      MomentumStateSurface.tsx
      sector-momentum.css
```

首个消费者保持 feature-local，不提前沉到 shared。只有 Shortcut 是当前已经存在两个消费者且视觉合同相同的真正共享组件。

### 5.7 M3A 文件级增量矩阵

| 操作 | 文件 | 精确要求 |
|---|---|---|
| 修改 | `src/biz/api/wealth/market/sector_analysis.py` | 新增第四个 `GET /momentum/members`；继续 strict unknown/duplicate 参数；不得改变三个既有 endpoint |
| 修改 | `src/biz/schemas/wealth/market/sector_analysis.py` | 新增严格 Members DTO 和计数不变量；不改既有 DTO |
| 新增 | `src/biz/queries/wealth/market/sector_analysis/sector_member_detail_query.py` | 集合读取精确开市日窗口、来源成员和批量股票行情；禁止 N+1 SQL |
| 新增 | `src/biz/queries/wealth/market/sector_analysis/sector_member_detail_query_service.py` | 版本/层级校验、调用 Query/Calculator、局部状态和 DTO 组装 |
| 新增 | `src/biz/services/wealth/market/sector_analysis/sector_member_detail_contract.py` | 输入事实、结果事实、缺失原因和固定枚举；不引入任意表达式 |
| 新增 | `src/biz/services/wealth/market/sector_analysis/sector_member_return_calculator.py` | 纯计算每日 `pct_chg` 连乘、Decimal 取舍、稳定排序和覆盖计数；无 IO |
| 修改 | `tests/architecture/test_wealth_sector_analysis_guardrails.py` | 精确新增两张允许表/模型和第四 endpoint；删除只针对 `dc_member` 的旧禁止项，继续禁止其他股票衍生表、资金、Heat、DG/Lake/QTF |
| 修改 | `wealth/docs/system/exception-code-registry.md` | 登记三个 Members 专用异常码；与本文和技术方案完全一致 |
| 修改 | `wealth/src/features/wealth-exploration/sector-analysis/momentum-ranking/api/sectorMomentumApi.ts` | 新增 members URL/fetch；请求必带 observedTradeDate 和 hierarchyVersion |
| 修改 | `wealth/src/features/wealth-exploration/sector-analysis/momentum-ranking/api/sectorMomentumAdapter.ts` | 严格校验响应、计数、可空字段和请求事实一致性；不计算收益或重排 |
| 修改 | `wealth/src/features/wealth-exploration/sector-analysis/momentum-ranking/model/sectorMomentumTypes.ts` | 新增 Member DTO/ViewModel 和局部四态 |
| 修改 | `wealth/src/features/wealth-exploration/sector-analysis/momentum-ranking/model/useMomentumRankingController.ts` | 增加独立 member requestId/AbortController/retry；不把 member 状态并入整页五态 |
| 修改 | `wealth/src/features/wealth-exploration/sector-analysis/momentum-ranking/ui/MomentumRankingWorkspace.tsx` | 两个三级 scope 使用 `MomentumLeftWorkspace`；其他 scope 保持既有渲染 |
| 新增 | `wealth/src/features/wealth-exploration/sector-analysis/momentum-ranking/ui/SectorMemberPanel.tsx` | 54px 标题、40px 表头、370px viewport、48px 行和局部四态 |
| 修改 | `wealth/src/features/wealth-exploration/sector-analysis/momentum-ranking/ui/sector-momentum.css` | 冻结 `390+12+464`、共享响应式四列 Grid、独立滚动；不改右栏 |

明确禁止修改：`sector_overview/sector_member_query.py`、`SectorMomentumCalculator`、`MomentumDetailPanel` 两图业务、TopMarketBar、Shortcut、数据库模型、迁移、配置和第三方依赖。

### 5.8 M6／M7 双动量文件级增量矩阵

M6 后端只允许下列增量：

| 操作 | 文件 | 精确要求 |
|---|---|---|
| 新增 | `src/biz/queries/wealth/market/sector_analysis/sector_analysis_meta_query_service.py` | 一次加载公共 context、当前层级和日期覆盖，返回页面无关事实；不返回任何 DTO，不增加 SQL |
| 新增 | `src/biz/queries/wealth/market/sector_analysis/sector_momentum_snapshot_query_service.py` | 解析比较池、业务日期和单日窗口，调用现有 Calculator，输出不可变事实快照；正常路径最多 5 SQL |
| 新增 | `src/biz/queries/wealth/market/sector_analysis/sector_dual_momentum_query_service.py` | 组合专属 Meta/Results、状态、计数、稳定排序和安全异常；不访问 members/history |
| 新增 | `src/biz/services/wealth/market/sector_analysis/sector_dual_momentum_contract.py` | 冻结公式、周期、阈值、分类／坐标／展示状态及不可变分类结果；不含 ORM、Session 或 DTO |
| 新增 | `src/biz/services/wealth/market/sector_analysis/sector_dual_momentum_classifier.py` | 只根据快照的 return/rank/percentile 分类，纯函数、无 IO、不重算收益或排名 |
| 新增 | `src/biz/schemas/wealth/market/sector_dual_momentum.py` | 双动量专属 strict Meta/Results DTO 与跨字段 validator；不扩写旧 Formula/Ranking DTO |
| 修改 | `src/biz/queries/wealth/market/sector_analysis/sector_momentum_query_service.py` | `build_meta/build_rankings` 改为消费公共 Meta／单日快照；旧 response model 与 JSON 事实必须零变化；`build_history` 计算链保持不变 |
| 修改 | `src/biz/api/wealth/market/sector_analysis.py` | 在同一 router 增加双动量 Meta/Results；继续 strict query、quote auth 和安全错误映射 |
| 修改 | `wealth/docs/system/exception-code-registry.md` | 登记 `SA_FACT_VERSION_MISMATCH`；不复用成员专用版本冲突码 |
| 新增 | `tests/test_wealth_sector_momentum_snapshot_query_service.py` | 快照、SQL 数、缺口、比较池、日期和旧 Rankings 等价性 |
| 新增 | `tests/test_wealth_sector_dual_momentum_classifier.py` | 公式边界、小组、缺值、状态组合和排序纯函数测试 |
| 新增 | `tests/test_wealth_sector_dual_momentum_query_service.py` | Meta/Results 状态、计数、版本、性能预算和来源门禁 |
| 修改 | `tests/web/test_wealth_sector_analysis_api.py` | 新增两个 endpoint 正反例；四个旧 endpoint response dump 回归 |
| 修改 | `tests/architecture/test_wealth_sector_analysis_guardrails.py` | 方法级证明双动量只读前三张表，禁止成员、股票、资金、Heat、QTF、DG/Lake、迁移和配置 |

M7 前端只允许下列增量：

| 操作 | 文件 | 精确要求 |
|---|---|---|
| 修改 | `wealth/src/features/wealth-exploration/navigation/explorationNavigation.ts` | 新增双动量正式 path 常量；入口卡仍默认进入动量排名 |
| 修改 | `wealth/src/app/routes/routerState.ts` | 增加 `sector-analysis-dual-momentum` 判别值、path builder 和精确反例 |
| 修改 | `wealth/src/app/routes/WealthRouter.tsx` | 向同一 `SectorAnalysisPage` 传显式 method；根地址仍 replace 到动量排名 |
| 修改 | `wealth/src/pages/wealth-exploration/SectorAnalysisPage.tsx` | 按 method 只挂载一个 controller/workspace；公共 Shell、context 和 toast 不变 |
| 修改 | `wealth/src/features/wealth-exploration/sector-analysis/navigation/SectorAnalysisMethodBar.tsx` | 改为受控 activeMethod/onSelect；两个可用方法导航，另外三个只 toast |
| 新增 | `wealth/src/features/wealth-exploration/sector-analysis/dual-momentum/api/sectorDualMomentumApi.ts` | 专属 Meta/Results URL、fetch 和专属有界错误类 |
| 新增 | `wealth/src/features/wealth-exploration/sector-analysis/dual-momentum/api/sectorDualMomentumAdapter.ts` | strict 读取、数量／状态／排序／请求事实校验；不计算资格、收益或百分位 |
| 新增 | `wealth/src/features/wealth-exploration/sector-analysis/dual-momentum/model/sectorDualMomentumTypes.ts` | 独立 DTO、ViewModel、URL、主状态和局部展示类型 |
| 新增 | `wealth/src/features/wealth-exploration/sector-analysis/dual-momentum/model/sectorDualMomentumUrlState.ts` | 十个 URL key、默认值、枚举、父级状态和 canonical search |
| 新增 | `wealth/src/features/wealth-exploration/sector-analysis/dual-momentum/model/useSectorDualMomentumController.ts` | Meta→Results、竞态、409、选择、resultView 和本地排序；不请求 history/members |
| 新增 | `wealth/src/features/wealth-exploration/sector-analysis/dual-momentum/ui/**` | 严格实现 Toolbar、ResultPanel/List、SelectedSummary、ScatterPlot、StateSurface 和正式 CSS |
| 修改／新增 | 对应 route、page、feature 测试 | 覆盖精确路由、按需挂载、URL、两请求、15 个状态、散点、响应式和三个待建设按钮 |

禁止在 M6/M7 修改 `SectorMomentumCalculator` 公式、Members 查询／controller、`MomentumRankingWorkspace` DOM、首页板块速览、TopMarketBar、Shortcut、Foundation/Ops/QTF/DG/Lake、ORM、Alembic、配置、依赖或构建脚本。若共享快照无法保持旧 Rankings JSON 和测试零变化，M6 必须停止，不能退回复制公式或兼容分支。

### 5.9 M10／M11 相对轮动文件级增量矩阵

M10 后端只允许下列增量：

| 操作 | 文件 | 精确要求 |
|---|---|---|
| 新增 | `src/biz/services/wealth/market/sector_analysis/sector_relative_rotation_contract.py` | 公式身份、四周期、固定5日、三轨迹长度、状态枚举、不可变日期切片／坐标事实和 parser；不得导入 Session、ORM、schema 或 API |
| 新增 | `src/biz/services/wealth/market/sector_analysis/sector_relative_rotation_calculator.py` | 只消费按日期的 `SectorRankFact`，计算 X/Y、样本解释、象限、缺失原因和 canonical 顺序；无 IO、无文案、不重算收益／排名 |
| 新增 | `src/biz/queries/wealth/market/sector_analysis/sector_relative_rotation_query_service.py` | 复用公共 Meta、snapshot preparation、MomentumQuery/Calculator/StatusResolver；5 SQL 内批量生成当前全池和选中轨迹并映射 DTO |
| 新增 | `src/biz/schemas/wealth/market/sector_relative_rotation.py` | 专属 strict Meta/Results DTO、状态组合、计数、日期槽、选择、排序和请求事实 validator；不扩写旧 schema |
| 修改 | `src/biz/queries/wealth/market/sector_analysis/sector_momentum_query.py` | 仅把 `load_open_dates()` 上限90改为95并同步错误文案；96继续拒绝，其他 SQL 不变 |
| 修改 | `src/biz/api/wealth/market/sector_analysis.py` | 增加相对轮动 Meta/Results 两只 GET；复用 quote auth、unknown/duplicate 检查和安全异常映射 |
| 修改 | `tests/architecture/test_wealth_sector_analysis_guardrails.py` | 相对轮动只允许前三张 Prod 表和既有共享查询；禁止成员、股票、资金、Heat、指数、QTF、DG/Lake、写入、迁移和配置 |
| 新增 | `tests/test_wealth_sector_relative_rotation_calculator.py` | 公式、并列、象限边界、小组、缺失、断点、排序和未来扰动纯计算正反例 |
| 新增 | `tests/test_wealth_sector_relative_rotation_query_service.py` | Meta/Results、5 SQL、95日、选择、日期状态、计数、轨迹槽、版本和异常正反例 |
| 修改 | `tests/test_wealth_sector_momentum_query_service.py` | 95允许／96拒绝，同时证明既有 History 90日事实不变 |
| 修改 | `tests/web/test_wealth_sector_analysis_api.py` | 新增两只真实 endpoint、strict query、401/400/409/500 和旧六只 endpoint response 回归 |

M11 前端只允许下列增量：

| 操作 | 文件 | 精确要求 |
|---|---|---|
| 修改 | `wealth/src/app/routes/routerState.ts` | 增加 path 常量／builder 和 `sector-analysis-relative-rotation` 判别值；未知子路由仍失败闭合 |
| 修改 | `wealth/src/app/routes/WealthRouter.tsx` | 第三个精确分支向同一页面传 `method="relative-rotation"` |
| 修改 | `wealth/src/pages/wealth-exploration/SectorAnalysisPage.tsx` | 第三个独立 content 分支；按 method 只挂载一个 controller，公共 Shell/context 不变 |
| 修改 | `wealth/src/features/wealth-exploration/sector-analysis/navigation/SectorAnalysisMethodBar.tsx` | `SectorAnalysisMethod` 增加第三项；相对轮动正式导航，成员广度／量价分布仍 toast |
| 新增 | `.../relative-rotation/api/sectorRelativeRotationApi.ts` | 专属 Meta/Results GET、5秒超时所需 signal 和安全错误类 |
| 新增 | `.../relative-rotation/api/sectorRelativeRotationAdapter.ts` | 精确字段、枚举、数量、canonical 顺序、日期槽和请求事实校验；不得计算百分位、差值或象限 |
| 新增 | `.../relative-rotation/model/sectorRelativeRotationTypes.ts` | 独立 wire/view/url/controller 类型和判别联合状态 |
| 新增 | `.../relative-rotation/model/sectorRelativeRotationUrlState.ts` | 十一个 URL key、默认值、父级闭包、canonical search 和非法输入失败闭合 |
| 新增 | `.../relative-rotation/model/useSectorRelativeRotationController.ts` | Meta→Results、request key、Abort、409一次重载、原子选中轨迹、本地搜索／象限过滤和 URL 恢复 |
| 新增 | `.../relative-rotation/model/relativeRotationPlotGeometry.ts` | 仅处理 SVG 像素映射、对称Y轴、刻度、避让和一份不可变 `plotScale`；不得产生业务坐标 |
| 新增 | `.../relative-rotation/ui/**` | Toolbar、SelectedSummary、Plot、IndustryList、StateSurface、ExpandedDialog 和正式 CSS |
| 新增／修改 | 对应 route/page/feature 测试 | 覆盖精确路由、按需挂载、URL、14状态、图表、完整列表、响应式、可访问性和两个待建设按钮 |

前端目录中的 `...` 固定展开为：

```text
wealth/src/features/wealth-exploration/sector-analysis/relative-rotation/
```

禁止在 M10/M11 修改 `SectorMomentumCalculator` 现有公式、动量／双动量 schema 和 DTO、Members 主链、首页板块速览、TopMarketBar、Shortcut、Foundation/Ops/QTF/DG/Lake、ORM、Alembic、依赖、配置或构建／部署脚本。若实现需要超出本矩阵，必须停止并回到方案层，不得“顺手”扩写。

### 5.10 M14／M15 成员广度文件级增量矩阵

M14 后端只允许下列增量：

| 操作 | 文件 | 精确要求 |
|---|---|---|
| 新增 | `src/biz/services/wealth/market/sector_analysis/sector_member_breadth_contract.py` | 公式身份、五 scope、两方向、三指标、六均线、三趋势范围、`5+80%`、日期／来源事实、资格和缺失原因；无 Session、ORM、schema 或 API |
| 新增 | `src/biz/services/wealth/market/sector_analysis/sector_member_breadth_calculator.py` | 三项独立分母、复权均线、资格、竞争排名、趋势、成员明细和稳定排序；纯内存、Decimal、无 IO／DTO／文案 |
| 新增 | `src/biz/queries/wealth/market/sector_analysis/sector_member_breadth_query.py` | 批量读取 SSE 窗口、指定行业逐日成员及股票行情+复权因子；唯一性检查；禁止逐行业／逐日期／逐股票 SQL |
| 新增 | `src/biz/queries/wealth/market/sector_analysis/sector_member_breadth_query_service.py` | 复用公共 Meta／hierarchy／scope；编排 Meta、Rankings、Details、409、状态和 DTO；Meta 零成员／行情／因子历史扫描 |
| 新增 | `src/biz/schemas/wealth/market/sector_member_breadth.py` | 专属 strict Meta/Rankings/Details DTO 与跨字段 validator；不得扩写既有公开 DTO |
| 修改 | `src/biz/api/wealth/market/sector_analysis.py` | 增加三只 GET，复用 quote auth、unknown/duplicate 拒绝和安全异常映射；Rankings/Details 的 `tradeDate` 必填 |
| 修改 | `wealth/docs/system/exception-code-registry.md` | 登记 `SA_BREADTH_FACT_MISMATCH/SA_BREADTH_SOURCE_EMPTY/SA_BREADTH_QUERY_FAILED`，不得新增同义码 |
| 新增 | `tests/test_wealth_sector_member_breadth_calculator.py` | 三公式、三分母、六均线、缺值独立、资格、排名、趋势、成员排序和未来扰动 |
| 新增 | `tests/test_wealth_sector_member_breadth_query_service.py` | Meta零预扫、自动／显式日期、五scope、3/4/4 SQL、指标按需、状态、409、payload和性能门禁 |
| 修改 | `tests/web/test_wealth_sector_analysis_api.py` | 新增三只 endpoint 的 strict/401/400/409/500 正反例；既有八只 endpoint 响应零变化 |
| 修改 | `tests/architecture/test_wealth_sector_analysis_guardrails.py` | 只给成员广度新增 `EquityAdjFactor` 白名单；证明其他三个方法不读取成员／股票／因子，全部方法无写入／迁移／缓存／QTF／DG/Lake |

M15 前端只允许下列增量：

| 操作 | 文件 | 精确要求 |
|---|---|---|
| 修改 | `wealth/src/app/routes/routerState.ts` | 增加 `sector-analysis-member-breadth` 精确判别和 path builder；未知子路由失败闭合 |
| 修改 | `wealth/src/app/routes/WealthRouter.tsx` | 第四个精确分支向同一页面传 `method="member-breadth"` |
| 修改 | `wealth/src/pages/wealth-exploration/SectorAnalysisPage.tsx` | 第四个独立 content 分支；只挂载当前 controller，公共 Shell/context 不变 |
| 修改 | `wealth/src/features/wealth-exploration/sector-analysis/navigation/SectorAnalysisMethodBar.tsx` | `SectorAnalysisMethod` 增加成员广度；量价分布继续 toast |
| 新增 | `.../member-breadth/api/sectorMemberBreadthApi.ts` | 三只 GET、5秒请求超时、Abort 和安全错误边界 |
| 新增 | `.../member-breadth/api/sectorMemberBreadthAdapter.ts` | strict 枚举、日期模式、数量、组成和、百分比、资格、排名、趋势槽和请求事实校验；不重算业务公式 |
| 新增 | `.../member-breadth/model/sectorMemberBreadthTypes.ts` | 独立 wire/view/url/controller 类型和五态／局部状态 |
| 新增 | `.../member-breadth/model/sectorMemberBreadthUrlState.ts` | `market/tradeDate/scope/level1Code/level2Code/direction/metric/maPeriod/historyRange/sectorCode`；URL 有日期即显式历史 |
| 新增 | `.../member-breadth/model/useSectorMemberBreadthController.ts` | Meta→实际日期；合法选中行业时 Rankings+Details 并发，无合法选中行业时 Rankings→规范默认行业→Details；request key、Abort、409一次重载、选择保持和默认延迟提示 |
| 新增 | `.../member-breadth/ui/**` | Toolbar、RankingPanel、SelectedSummary、CompositionBars、TrendChart、MemberTable、StateSurface 和正式 CSS |
| 新增／修改 | 对应 route/page/feature 测试 | 覆盖精确路由、零隐藏挂载、自动／历史日期、13状态、滚动、四档宽度、可访问性和量价分布零副作用 |

前端目录中的 `...` 固定展开为：

```text
wealth/src/features/wealth-exploration/sector-analysis/
```

M14/M15 禁止修改现有 M3A 成员明细、三个已完成方法的 API／DTO／公式／DOM、首页板块速览、TopMarketBar、Shortcut、Foundation 模型／同步、Ops、QTF、DG/Lake、Alembic、依赖、配置或部署脚本。若需要新增索引、缓存、结果表、分页、截断或后台任务，立即停止。

M16I 只允许下列前端增量：

| 操作 | 文件 | 精确要求 |
|---|---|---|
| 修改 | `.../member-breadth/ui/MemberBreadthWorkspace.tsx` | 持有趋势查看的局部 UI 状态；按 Details 身份、trend 替换和非 Ready 状态清除，排名 metric 刷新造成的正文短暂卸载不得清除；不得进入 controller／URL／跨页面存储 |
| 修改 | `.../member-breadth/ui/MemberBreadthTrendChart.tsx` | 受控消费 `IDLE/ACTIVE` 局部状态，增加真实容器到 viewBox 坐标映射、最近交易日吸附、十字线、轴浮标、三线有效交点、同日 Tooltip和空白单击／Esc退出；不得改折线事实或请求 |
| 修改 | `.../member-breadth/ui/sector-member-breadth.css` | 只增加交互层、Tooltip、浮标、交点和 focus-visible 样式；全部使用现有 `--cs-*` token，图表卡尺寸、viewBox、plot padding和页面骨架不变 |
| 新增 | `.../member-breadth/ui/MemberBreadthTrendChart.test.tsx` | 组件级正反例覆盖单击进入、日期吸附、左右／上下移动、null、Tooltip避让、离开保留、空白单击／Esc退出、身份变化清除、响应式坐标映射和零请求 |
| 修改 | `.../member-breadth/ui/MemberBreadthWorkspace.test.tsx` | 只补工作区切换行业／日期／方向／MA／历史范围时清除交互，以及切换排名指标不误清除、不新增请求的集成断言 |

上表中的 `...` 固定展开为 `wealth/src/features/wealth-exploration/sector-analysis`。M16I 不修改 API、DTO、adapter、URL、controller、后端、数据库、迁移、Figma 页面骨架、其他分析方法或量价分布；若实现需要扩大范围，立即停止并回到方案层。

## 6. 后端合同与纯计算设计

### 6.1 代码枚举

```python
SectorMomentumScope = Literal[
    "LEVEL_1", "LEVEL_2", "LEVEL_3",
    "LEVEL_1_CHILDREN", "LEVEL_2_CHILDREN",
]
SectorMomentumDirection = Literal["GAINERS", "LOSERS"]
SectorMomentumPeriod = Literal[1, 5, 10, 20, 30]
SectorHistoryRange = Literal[20, 30, 60]
SectorAnalysisStatus = Literal["READY", "DELAYED", "EMPTY", "ERROR"]
```

API 接受大写枚举，前端 URL 使用小写短值；转换只允许在前端 adapter/request builder 一处完成。

### 6.2 查询数据结构

```python
@dataclass(frozen=True, slots=True)
class SectorDailyFact:
    sector_code: str
    trade_date: date
    close: Decimal | None
    pct_change: Decimal | None

@dataclass(frozen=True, slots=True)
class SectorReturnFact:
    sector_code: str
    trade_date: date
    return_pct: Decimal | None
    missing_reason: Literal[
        "NONE", "HISTORY_INSUFFICIENT", "DATE_MISSING",
        "CLOSE_MISSING", "CLOSE_NON_POSITIVE", "PCT_CHANGE_MISSING",
    ]

@dataclass(frozen=True, slots=True)
class SectorRankFact:
    sector_code: str
    return_pct: Decimal | None
    strength_rank: int | None
    percentile: Decimal | None
```

`missing_reason` 只用于服务内部和有界 debug，正式行不新增解释字段；页面统一显示 `--`。

### 6.3 比较池解析

`resolve_scope_pool(snapshot, scope, level1_code, level2_code)` 必须是纯函数：

1. `LEVEL_1`：全部 `industry_level=1`。
2. `LEVEL_2`：全部 `industry_level=2`。
3. `LEVEL_3`：全部 `industry_level=3`。
4. `LEVEL_1_CHILDREN`：`parent_sector_code=level1Code` 且 level=2。
5. `LEVEL_2_CHILDREN`：先验证 level2 是 level1 直属子级，再取其直属 level=3。
6. 返回次序固定为 `(display_order, sector_code)`；不因行情值变化改变对象池顺序。
7. 缺父级、错层、跨父级分别抛有界合同异常，API 映射 `SA_SCOPE_INVALID`。

### 6.3.1 Pre-M2 单语句日期锚点

`MarketPageContextQuery.resolve_context()` 保持现有入口：

```python
resolve_context(
    session: Session,
    *,
    market: str,
    requested_trade_date: date | None,
) -> MarketPageContext
```

内部只允许执行一条 SQL。Python 端先且只生成一次 `local_now=datetime.now(ZoneInfo("Asia/Shanghai"))`，SQL 使用绑定参数 `local_date`、`before_eod_switch` 和可选 `requested_trade_date`，不得使用数据库 `CURRENT_DATE/current_timestamp` 推导业务时间。

单条 SQL 必须通过标量子查询或 CTE 同时构造以下事实：

```text
latest_open_date      = max(SSE open trade_date <= local_date)
today_calendar        = SSE calendar row at local_date
previous_open_before_today = max(SSE open trade_date < local_date)
requested_calendar    = SSE calendar row at requested_trade_date（显式模式）
resolved_trade_date   = 显式日期；否则在今天开市、20:00前且存在 previous_open_before_today 时取该值，其余取 latest_open_date
resolved_calendar     = SSE calendar row at resolved_trade_date
previous_open_fallback = max(SSE open trade_date < resolved_trade_date)
```

结果映射规则冻结为：

1. 显式模式：`trade_date=requested_trade_date`。若 `resolved_calendar` 存在，`is_trading_day=resolved_calendar.is_open`、`prev_trade_date=resolved_calendar.pretrade_date`；若不存在，`is_trading_day=false`、`prev_trade_date=previous_open_fallback`。
2. 默认模式：今天开市、`local_now.hour < 20` 且 `previous_open_before_today` 非空时使用该日期；否则使用 `latest_open_date`。必须保持当前 `max(open trade_date < local_date)` 语义，不改为信任 `today_calendar.pretrade_date`。
3. 默认模式没有任何开市日时，继续使用 `local_date`。若该日存在日历记录，仍读取其 `is_open/pretrade_date`；若不存在，返回 `is_trading_day=false` 和有界 fallback。
4. `session_status` 继续按现有 `_resolve_session_status(local_now=local_now, is_trading_day=is_trading_day)` 原样计算；Pre-M2 不额外引入“最终日期必须等于 local_date”的判断，避免改变现有显式日期与调用方合同。
5. `source` 仍严格为 `explicit/default`，`generated_at` 必须等于本次唯一的 `local_now`。
6. 禁止第二次查询最终日历行、禁止再次查询上一开市日、禁止在调用方复制20:00分支、禁止服务端全局缓存。

SQLAlchemy event counter 必须证明所有正反例都是恰好 1 条 SQL。参数或市场在发 SQL 前即可判定非法时允许 0 条；不得为了满足计数跳过合法日期事实。

### 6.4 日期解析

服务同时接收 `trade_date: date | None`，不能只接收 context 的日期结果，因为必须区分默认和显式模式：

1. 先用 `MarketPageContextQuery.resolve_context()` 得到 `expectedTradeDate`。
2. 显式模式：只查 `expectedTradeDate`；`COMPLETE` 和 `PARTIAL` 日都严格命中该日，`MISSING` 日返回 EMPTY，不回退。
3. 默认模式：先计算 expected 日的当前 496 行业来源覆盖；只有 `COMPLETE` 才直接使用 expected。若为 `PARTIAL/MISSING`，向前取最近一个 `COMPLETE` SSE 开市日作为 observed 并返回 DELAYED，不能把“当天只来了几行”误当当日数据已经发布完整。
4. observed 必须同时位于 SSE 开市日；非开市脏日期不能成为页面日期。
5. history 的结束日期固定为 observed，rankings 与 history 不得分别选择日期。
6. 显式日期早于 `coverageStartDate` 或晚于 `coverageEndDate` 是范围非法，不作为来源缺失；Meta 不把覆盖起始日前的历史交易日伪装成 MISSING。

### 6.5 交易日窗口

`SectorMomentumQuery.load_open_dates(end_date, count)` 使用：

```sql
SELECT trade_date
FROM core_serving.trade_calendar
WHERE exchange = 'SSE'
  AND is_open = true
  AND trade_date <= :end_date
ORDER BY trade_date DESC
LIMIT :count
```

取回后在内存反转为升序。rankings 最大 `count=31`；history 最大 `count=90`（60 个显示日 + 最早显示点之前 30 个交易日，最早一日已经是分母日）。禁止自然日减法或再多取第 91 日。

Meta 的日期覆盖查询使用当前层级 496 个代码作为固定分母，对 `coverageStartDate..coverageEndDate` 的全部 SSE 开市日做日级聚合并左连接有效行情计数。结果必须按日期升序返回：`valid=expected` 为 COMPLETE，`0<valid<expected` 为 PARTIAL，`valid=0` 为 MISSING。当前层级外代码不参与计数；不能用 `INNER JOIN dc_daily` 过滤掉缺口日。

### 6.6 行情查询

一个请求只发一次有界行情查询：

```sql
SELECT ts_code, trade_date, close, pct_change
FROM core_serving.dc_daily
WHERE category = '行业板块'
  AND ts_code IN :sector_codes
  AND trade_date BETWEEN :start_date AND :end_date
ORDER BY trade_date, ts_code
```

禁止逐行业、逐日期回查。返回行先验证业务键唯一；虽然数据库有主键，单元测试仍必须覆盖重复输入反例，纯计算内核不得静默后写覆盖前写。

### 6.7 区间收益计算

1 日：

```text
returnPct = pct_change(t)
```

N 日：

```text
requiredDates = [t-N, ..., t] 共 N+1 个 SSE 交易日
returnPct = (close(t) / close(t-N) - 1) * 100
```

门禁：

1. 每个 required date 必须有且只有一条该行业行。
2. 每条 `close` 必须非空、有限且大于 0；中间日期虽不进入除法，也作为完整窗口门禁。
3. 任一门禁失败返回 `null`，不连乘 `pct_change`、不跳过停牌日、不补零、不前向填充。
4. 内部使用 `Decimal`；DTO 边界按 `0.0001`、`ROUND_HALF_UP` 输出 4 位小数并转 JSON number。

### 6.8 强度排名与百分位

对同日同一比较池的非空收益：

```text
strengthRank(x) = 1 + count(returnPct > x)
```

因此并列值为竞赛排名 `1,2,2,4`。

百分位使用并列平均名次：

```text
greater = count(returnPct > x)
equal = count(returnPct == x)
averageRank = greater + (equal + 1) / 2      # 1-based
percentile = (n - averageRank) / (n - 1) * 100
```

1. `n=1` 时返回 `100.0`。
2. 最强为 100，最弱为 0；并列对象返回相同值。
3. DTO 按 `0.1`、`ROUND_HALF_UP` 输出 1 位小数。
4. null 行的 rank/percentile 都为 null，且不进入 `calculableCount`。

### 6.9 展示排序与榜单序号

1. GAINERS：非空收益 `desc`。
2. LOSERS：非空收益 `asc`。
3. 同值使用 `sector_code asc`。
4. null 永远在所有有效值之后，并按 `sector_code asc`。
5. 排序完成后才赋值 `listPosition=1..totalCount`。
6. `direction` 不传入 `rank_strength()`，也不传入 history Query/Calculator。

### 6.10 历史序列

一次 history 请求取得 `historyRange + period` 个不同交易日；其中 period 个日期位于最早显示点之前，最早一个就是该点的分母日。然后：

1. 对每个显示日重新计算当前比较池每个行业的 returnPct。
2. 对当日非空值重新计算 strengthRank 和 percentile。
3. 只输出当前 `sectorCode` 的两条同日期序列。
4. 两数组必须长度相同、日期严格升序且日期集合完全相同。
5. 当前行业缺值时，`returnPct/strengthRank/percentile=null`，但保留日期槽；`calculableCount` 仍表达该日其他可计算对象数量。
6. `totalCount` 是当前发布层级下比较池大小，每个点都返回，不能把它误作 calculableCount。
7. 历史不足 20/30/60 时返回现有全部显示日，不伪造前序日期。

### 6.11 查询数量预算

| Endpoint | 正常路径最大 SQL 数 |
|---|---:|
| meta | 3：公共日期 1、层级（含发布时间）1、可用日期 1 |
| rankings | 显式／默认日期均最多 5：公共日期 1、层级 1、observed 1、窗口日历 1、行情事实 1 |
| history | 显式／默认日期均最多 5；行情仍为一次有界集合查询 |
| members | 4：当前层级 1、精确开市日及窗口 1、来源成员 1、成员集合批量日行情 1 |

实现测试使用 SQLAlchemy event counter 记录数量；Pre-M2 已证明公共日期查询严格为 1 条，M2 已证明 Meta/Rankings/History 分别不超过 3/5/5 条。M3A 必须证明 Members 不超过 4 条，且成员数和周期变化不会增加 SQL 数。允许同一请求内复用已经加载的 hierarchy snapshot，不允许增加服务端全局缓存。

### 6.12 Members 输入事实与窗口

```python
@dataclass(frozen=True, slots=True)
class SectorMemberSourceFact:
    stock_code: str
    stock_name: str | None

@dataclass(frozen=True, slots=True)
class SectorMemberDailyFact:
    stock_code: str
    trade_date: date
    close: Decimal | None
    pct_change: Decimal | None

@dataclass(frozen=True, slots=True)
class SectorMemberReturnFact:
    stock_code: str
    stock_name: str | None
    close: Decimal | None
    return_pct: Decimal | None
    return_missing_reason: Literal[
        "NONE", "DATE_MISSING", "PCT_CHANGE_MISSING",
        "HISTORY_INSUFFICIENT",
    ]
```

1. 成员关系固定读取 `dc_member.trade_date=tradeDate` 且 `dc_member.ts_code=sectorCode`；不连接 `Security`、停牌表或 Heat 有效池。
2. 1 日和多日都使用截至 `tradeDate` 的最近 N 个 SSE 开市日；成员多日公式需要 N 个每日 `pct_chg`，不是行业公式的 N+1 个收盘价。
3. 行情查询使用全部成员代码集合和窗口日期集合一次读取，按 `trade_date, ts_code` 稳定排序；同一业务键重复立即失败，不取第一条。
4. 目标日收盘价只读取 `close(tradeDate)`，与区间收益是否可计算相互独立：收益缺失时仍可显示收盘价，收盘价缺失时若必要 `pct_chg` 完整仍可显示区间收益。

### 6.13 Members 收益纯计算

1 日：

```text
memberReturnPct(1,t) = pct_chg(t)
```

N 日，其中 `N ∈ {5,10,20,30}`：

```text
requiredDates = 截至 t 的最近 N 个 SSE 开市日
memberReturnPct(N,t) = (Π[d ∈ requiredDates](1 + pct_chg(d) / 100) - 1) × 100
```

门禁：

1. 每个必要日期必须有且只有一条该股票行情；任一日期缺行返回 `DATE_MISSING`。
2. 每个必要 `pct_chg` 必须非空且有限；否则返回 `PCT_CHANGE_MISSING`。
3. 开市日窗口不足 N 个返回 `HISTORY_INSUFFICIENT`。
4. 目标日 `close` 非空、有限且大于 0 时保留原值，否则 `close=null`；收盘价缺失不写入 `return_missing_reason`，避免覆盖独立的收益缺失原因。
5. 内部使用 Decimal；`returnPct` 按 `0.0001/ROUND_HALF_UP` 输出，禁止在前端重新连乘。
6. 不补零、不前向填充、不借用最近有价日、不按停牌自动视为 0，也不保留首尾收盘价的第二运行分支。

### 6.14 Members 排序和覆盖计数

```text
GAINERS: returnPct 非空 desc, stockCode asc
LOSERS:  returnPct 非空 asc,  stockCode asc
null:    始终末尾, stockCode asc
```

服务必须满足：

```text
rows.length == totalMemberCount
0 <= calculableCount <= totalMemberCount
0 <= closeAvailableCount <= totalMemberCount
```

`calculableCount` 与 `closeAvailableCount` 彼此不要求包含关系，因为目标日收盘价和区间 `pct_chg` 的完整性是两项独立事实；这避免错误拒绝“有收益但目标 close 缺失”的合法来源行。

### 6.15 Members 层级版本和状态

1. 请求必须携带 rankings 返回的 `hierarchyVersion`；服务重新加载当前唯一层级快照并要求完全相等。
2. 版本不一致返回 HTTP 409 `SA_MEMBER_FACT_MISMATCH`，不执行成员和行情查询；前端必须清空四类短期事实并从 meta 重载。
3. `sectorCode` 必须在该版本中存在且 `industry_level=3`；否则 HTTP 400 `SA_SELECTION_INVALID`，不静默替换行业。
4. 来源成员数大于 0 时始终返回局部 `READY`，即使全部 `close/returnPct` 为 null。
5. 来源成员数为 0 返回局部 `EMPTY/SA_MEMBER_SOURCE_EMPTY`；查询、重复键或计算合同失败返回局部 `ERROR/SA_MEMBER_QUERY_FAILED`。

### 6.16 Members Query/Service 伪代码

```python
def build_members(session, request):
    hierarchy = hierarchy_query.load_current(session)                  # SQL 1
    require_version_and_level3(hierarchy, request)
    open_dates = member_query.load_open_window(session, request)       # SQL 2
    members = member_query.load_members(session, request)              # SQL 3
    if not members:
        return empty_response(request, hierarchy)
    daily = member_query.load_daily_facts(                             # SQL 4
        session, codes={row.stock_code for row in members}, dates=open_dates
    )
    facts = member_calculator.calculate(members, daily, open_dates, request)
    rows = member_calculator.sort(facts, direction=request.direction)
    return build_strict_dto(rows, request, hierarchy)
```

Query 不返回 DTO，Calculator 不访问 Session，Service 不在循环中执行 SQL。任一层不得调用首页 `SectorMemberQuery.load_top()`。

### 6.17 双动量公式与固定枚举

双动量不是新收益算法。它依赖既有公式：

```text
basisFormulaKey = sector-cross-sectional-momentum
basisFormulaVersion = 1
formulaKey = sector-dual-momentum
formulaVersion = 1
minimumGroupSize = 3
periods = [5, 10, 20, 30]
leadingThresholds = [70, 80, 90]
```

输入只接受五类既有 `SectorMomentumScope`、一个固定 period 和一个固定 leadingThreshold。`1` 日、列表方向、historyRange、成员参数、任意阈值或任意公式版本均不属于双动量合同。

分类公式固定为：

```text
absoluteStatus = POSITIVE       iff returnPct > 0
                 NOT_POSITIVE  iff returnPct <= 0
                 UNAVAILABLE   iff returnPct is null

relativeStatus = SAMPLE_INSUFFICIENT
                   iff returnPct/percentile 可计算且 calculableCount < 3
                 LEADING
                   iff calculableCount >= 3 and percentile >= leadingThreshold
                 NOT_LEADING
                   iff calculableCount >= 3 and percentile < leadingThreshold
                 UNAVAILABLE
                   iff returnPct or percentile is null

qualificationStatus = QUALIFIED
  iff absoluteStatus=POSITIVE and relativeStatus=LEADING
qualificationStatus = NOT_QUALIFIED
  iff absoluteStatus in {POSITIVE, NOT_POSITIVE}
      and relativeStatus in {LEADING, NOT_LEADING}
qualificationStatus = NOT_EVALUATED
  otherwise

coordinateStatus = PLOTTABLE iff returnPct and percentile are both non-null
                   UNAVAILABLE otherwise
```

`returnPct=0` 明确属于 `NOT_POSITIVE`。小于 3 个可计算对象时，既有排名和百分位仍是客观事实，但所有可计算对象的 `relativeStatus=SAMPLE_INSUFFICIENT`、`qualificationStatus=NOT_EVALUATED`，不能产生伪 `QUALIFIED`。

`displayStatus` 由上述事实唯一映射：

```text
QUALIFIED
UP_NOT_LEADING
NOT_UP_LEADING
NOT_UP_NOT_LEADING
SAMPLE_INSUFFICIENT
DATA_INSUFFICIENT
```

前四项分别对应绝对／相对的四种完整组合；小组与事实缺失使用后两项。前端不得自行重算或覆盖该状态。

### 6.18 页面无关 Meta 事实与单日快照

公共 Meta service 输出不可变 `SectorAnalysisMetaFacts`：

```python
@dataclass(frozen=True, slots=True)
class SectorAnalysisMetaFacts:
    context: MarketPageContext
    hierarchy: SectorHierarchySnapshot
    coverage_start_date: date
    coverage_end_date: date
    trade_dates: tuple[SectorTradeDateAvailability, ...]
```

公共 Meta 事实仍只执行 3 条 SQL：公共日期 1、层级 1、日期覆盖 1。既有动量 Meta 映射原 `SectorAnalysisMetaResponseDto`；双动量 Meta 映射专属 DTO。公共 service 不包含公式、方向、历史范围、默认筛选或页面文案。

单日快照输出：

```python
@dataclass(frozen=True, slots=True)
class SectorMomentumSnapshotRow:
    node: SectorHierarchyNode
    return_fact: SectorReturnFact
    rank_fact: SectorRankFact

@dataclass(frozen=True, slots=True)
class SectorMomentumSnapshot:
    context: MarketPageContext
    hierarchy: SectorHierarchySnapshot
    resolution: SectorTradingDateResolution
    scope: SectorMomentumScope
    period: SectorMomentumPeriod
    level1_code: str | None
    level2_code: str | None
    rows: tuple[SectorMomentumSnapshotRow, ...]
```

不变量：

1. `rows` 与 `resolve_scope_pool()` 一一对应，次序固定为 `(display_order, sector_code)`；缺行情对象不能丢行。
2. `return_fact.sector_code == rank_fact.sector_code == node.sector_code`；return/rank/percentile 只能同空或同有。
3. 快照只加载一个业务日期和一个比较池，正常路径最多 5 条 SQL；不访问 history 或 members。
4. `SectorMomentumQueryService.build_rankings()` 只在快照之上增加 direction 排序、listPosition 和旧 DTO；旧 JSON、状态、异常、SQL 上限和测试必须不变。
5. 双动量 service 只在快照之上调用分类器、计算数量并映射专属 DTO；不得调用 `build_rankings()`、解析旧 DTO、访问其私有方法或第二次读 Prod。
6. `build_history()` 继续使用现有历史网格算法；M6 不把历史链路强行改造成快照，也不改变其查询计划。

### 6.19 双动量结果计数、排序和主状态

对快照全量行计算：

```text
totalCount       = rows.length
calculableCount  = count(returnPct and percentile are non-null)
qualifiedCount   = count(qualificationStatus=QUALIFIED)
insufficientCount= count(qualificationStatus=NOT_EVALUATED)
plottableCount   = count(coordinateStatus=PLOTTABLE)
```

必须满足：

```text
0 <= qualifiedCount <= calculableCount <= totalCount
0 <= insufficientCount <= totalCount
0 <= plottableCount <= calculableCount <= totalCount
qualifiedCount + count(NOT_QUALIFIED) + insufficientCount = totalCount
items.length = totalCount
```

规范响应排序固定为：可计算行在前，`percentile desc`、`returnPct desc`、`sectorCode asc`；缺值行在末尾并按 `sectorCode asc`。服务不接收 resultView 或本地 sort 参数。

页面主状态继续复用 `READY/DELAYED/EMPTY/ERROR`：

1. `calculableCount>0` 且 observed=expected 为 READY。
2. 默认目标日不完整、已回退最近 COMPLETE 日且 `calculableCount>0` 为 DELAYED。
3. `calculableCount=0` 为 EMPTY。
4. 查询、层级、公式、DTO 或内部合同失败为 ERROR。
5. `qualifiedCount=0`、`calculableCount<3`、部分行缺坐标都仍是 Ready/Delayed 内容状态，不得改成 Empty/Error。

### 6.20 层级版本与查询时序

双动量 Results 必须携带 Meta 返回的 `hierarchyVersion`，最长 128 个字符、trim 后非空；服务加载当前唯一发布层级后先比较版本，再读取窗口日历和行情。版本不一致立即返回 HTTP 409 `SA_FACT_VERSION_MISMATCH`，不得继续读取行情或返回新旧混合结果。

正常 Results 查询顺序固定为：公共日期、层级、observed 覆盖／回退、窗口日历、一次行业行情集合查询，最多 5 条 SQL。显式 MISSING 日不回退；默认 PARTIAL/MISSING 才按既有公共延迟规则回退。双动量不得增加第二套日期规则、自然日减法、逐行业 SQL、缓存、快照副本或结果表。

### 6.21 相对轮动合同与不可变事实

`sector_relative_rotation_contract.py` 固定声明：

```python
SectorRelativeRotationPeriod = Literal[5, 10, 20, 30]
SectorRelativeRotationTrailLength = Literal[20, 30, 60]
SectorRelativeRotationStatus = Literal[
    "LEADING_IMPROVING",
    "WEAK_IMPROVING",
    "STRONG_NOT_IMPROVING",
    "WEAK_NOT_IMPROVING",
    "SAMPLE_INSUFFICIENT",
    "DATA_INSUFFICIENT",
]
SectorRelativeCoordinateStatus = Literal["PLOTTABLE", "UNAVAILABLE"]
SectorRelativeGroupInterpretation = Literal["QUADRANT", "SAMPLE_INSUFFICIENT"]

FORMULA_KEY = "sector-relative-rotation"
FORMULA_VERSION = 1
BASIS_FORMULA_KEY = "sector-cross-sectional-momentum"
BASIS_FORMULA_VERSION = 1
IMPROVEMENT_LOOKBACK_DAYS = 5
MINIMUM_GROUP_SIZE = 3
X_DOMAIN = (Decimal("0.0"), Decimal("100.0"))
X_SPLIT = Decimal("50.0")
Y_SPLIT = Decimal("0.0")
ALLOWED_PERIODS = (5, 10, 20, 30)
ALLOWED_TRAIL_LENGTHS = (20, 30, 60)
```

parser 只接受上述枚举；缺字段、bool 冒充 int、非整数、1日、90日、任意改善周期和任意分界值均拒绝。公式常量只在该 contract 中定义；schema Meta 和前端 adapter 必须校验服务端返回值，不再各维护一套可执行常量。

纯计算中间事实：

```python
@dataclass(frozen=True, slots=True)
class SectorRelativeRotationRankSlice:
    trade_date: date
    returns: tuple[SectorReturnFact, ...]
    ranked: tuple[SectorRankFact, ...]
    calculable_count: int

@dataclass(frozen=True, slots=True)
class SectorRelativeRotationPointFact:
    sector_code: str
    trade_date: date
    return_pct: Decimal | None
    strength_rank: int | None
    percentile: Decimal | None
    percentile_delta_5d: Decimal | None
    current_calculable_count: int
    comparison_calculable_count: int
    rotation_status: SectorRelativeRotationStatus
    coordinate_status: SectorRelativeCoordinateStatus
    current_missing_reason: MissingReason | None
    comparison_missing_reason: MissingReason | None
```

`SectorRelativeRotationRankSlice` 中两组事实来自同一次 `calculate_for_dates()` 与紧随其后的 `rank_strength()`：`returns` 保留精确缺失原因，`ranked` 保留排名和百分位。构造及纯计算入口必须验证两组事实数量一致、行业代码唯一且顺序一致、`return_pct` 一致；有收益时缺失原因必须为 `NONE`，无收益时缺失原因不得为 `NONE`，否则立即拒绝。计算器不得重算收益、排名或猜测缺失原因。

`MissingReason="NONE"` 在 PointFact 中规范化为 null；不得新增同义缺失原因。PointFact 不持有 ORM、DTO、页面文案或 CSS 状态。

### 6.22 批量输入、日期槽与查询编排

`SectorRelativeRotationQueryService.build_results()` 的正常路径固定为：

```python
context = context_query.resolve_context(session, market="CN_A")       # SQL 1
preparation = snapshot_service.prepare_for_context(                    # SQL 2 + 3
    session,
    context=context,
    trade_date=request.trade_date,
    scope=request.scope,
    level1_code=request.level1_code,
    level2_code=request.level2_code,
    period=request.period,
    expected_hierarchy_version=request.hierarchy_version,
    date_errors_are_selection=True,
)

if observed is None or observed.availability == "MISSING":
    return EMPTY

required_count = request.period + IMPROVEMENT_LOOKBACK_DAYS + request.trail_length
open_dates = momentum_query.load_open_dates(                            # SQL 4
    session, end_date=observed.trade_date, count=required_count
)
facts = momentum_query.load_facts(                                      # SQL 5
    session,
    sector_codes=pool_codes,
    start_date=open_dates[0],
    end_date=open_dates[-1],
)
fact_index = momentum_calculator.index_facts(facts)

candidate_display_dates = open_dates[-request.trail_length:]
display_dates = tuple(
    day for day in candidate_display_dates
    if day >= preparation.resolution.coverage_start_date
)
comparison_dates = tuple(
    open_dates[open_dates.index(day) - IMPROVEMENT_LOOKBACK_DAYS]
    for day in display_dates
)
calculation_dates = tuple(sorted(set(display_dates + comparison_dates)))
returns_by_date = momentum_calculator.calculate_for_dates(
    sector_codes=pool_codes,
    open_dates=open_dates,
    target_dates=calculation_dates,
    period=request.period,
    fact_index=fact_index,
)
rank_slices = {
    day: make_rank_slice(
        day,
        returns_by_date[day],
        momentum_calculator.rank_strength(returns_by_date[day]),
    )
    for day in calculation_dates
}
points_by_date = relative_calculator.calculate_grid(
    sector_codes=pool_codes,
    open_dates=open_dates,
    display_dates=display_dates,
    rank_slices=rank_slices,
)
return build_atomic_response(current=display_dates[-1], selected=request.sector_code)
```

实现细节：

1. `required_count` 范围为30～95；`load_open_dates()` 返回实际存在的 SSE 开市日，按升序。不能因为行情缺失而删交易日。
2. `calculation_dates` 必须按 `open_dates` 的位置取值并去重、升序；不得使用 `date - timedelta(days=5)`。
3. `display_dates` 只有在来源覆盖起点晚于请求轨迹起点时才缩短；覆盖区间内的 PARTIAL/MISSING 日必须继续保留为 null 槽。
4. `calculate_for_dates()` 每请求只调用一次；`rank_strength()` 每个 calculation date 调用一次但只操作内存，不产生 SQL。`make_rank_slice()` 同时保留两组同源事实并执行第6.21节的一致性门禁，不允许只传排名事实而丢失缺失原因。
5. `SectorMomentumSnapshotQueryService.prepare_for_context()` 是唯一允许复用的 snapshot 方法；不得调用 `build()` 或 `build_prepared()`，避免重复日历／行情 SQL。
6. `SectorRelativeRotationQueryService` 不调用 `SectorMomentumQueryService.build_history()`、`SectorDualMomentumQueryService` 或任何页面 DTO。
7. 只要进入行情读取，`load_facts()` 必须恰好一次；异常和409前置路径可以少于5条 SQL，但不能多于5条。

### 6.23 X/Y、样本解释与四象限纯计算

对每个展示日 `d` 和行业 `s`：

```text
current     = ranks[d][s]
comparison  = ranks[open_date_index(d)-5][s]
X           = current.percentile
Y           = quantize_0_1(current.percentile - comparison.percentile)
```

分类顺序必须先处理缺失，再处理样本，最后处理象限：

```python
if current.percentile is None:
    X = None
    Y = None
    coordinate = "UNAVAILABLE"
    status = "DATA_INSUFFICIENT"
elif comparison.percentile is None:
    X = current.percentile
    Y = None
    coordinate = "UNAVAILABLE"
    status = "DATA_INSUFFICIENT"
elif current_count < 3 or comparison_count < 3:
    X = current.percentile
    Y = quantized_delta
    coordinate = "PLOTTABLE"
    status = "SAMPLE_INSUFFICIENT"
elif X >= 50 and Y > 0:
    status = "LEADING_IMPROVING"
elif X < 50 and Y > 0:
    status = "WEAK_IMPROVING"
elif X >= 50 and Y <= 0:
    status = "STRONG_NOT_IMPROVING"
else:
    status = "WEAK_NOT_IMPROVING"
```

边界不允许解释漂移：`X=50` 属于较强侧；`Y=0` 属于未增强；`Y` 在 Decimal 中计算并以 `ROUND_HALF_UP` 量化到0.1个百分点。前端只展示数值和服务端状态，不得用浮点重新分类。

当前日的 `groupInterpretation` 只由当前与5日前两个截面的 `calculable_count` 决定：二者均不少于3为 `QUADRANT`，否则为 `SAMPLE_INSUFFICIENT`。它不由选中行业决定。小组不足时所有有二维坐标的行都必须是 `SAMPLE_INSUFFICIENT`，四个象限计数全为0。

### 6.24 当前快照、选中轨迹和规范选择

当前快照对应 `observedTradeDate`，必须包含比较池全部行业。规范选择规则：

1. 请求显式 `sectorCode`：必须在当前比较池；否则抛 `SectorSelectionInvalidError` 并返回400，不静默换行业。
2. 请求缺省 `sectorCode`：先取 canonical 顺序第一只 `PLOTTABLE` 行；若没有可绘制行但页面仍有可计算 X，则取第一只当前百分位存在的行；否则主状态为 EMPTY，不构造 analysis。
3. READY/DELAYED 的 `analysis.selectedSectorCode` 必须有值，`selectedTrail` 必须存在并与其代码一致。Missing Selected Coordinate 通过轨迹点内 null 和 `coordinateStatus=UNAVAILABLE` 表达，不把整个 `selectedTrail` 设为 null。
4. `selectedTrail.points` 与 `display_dates` 一一对应、严格升序、日期唯一；每个日期槽都保留，即使 X/Y 均为空。
5. `requestedLength` 等于请求枚举，`dateSlotCount == points.length <= requestedLength`。只允许因 `coverageStartDate` 较晚而缩短；不得按可绘制点数压缩。
6. 轨迹只返回所选行业；不得为全部行业返回60日历史，以免扩大 payload 和前端状态。

当前 items canonical 顺序：

```text
PLOTTABLE:
  percentile desc, percentileDelta5d desc, sectorCode asc
current percentile exists but Y missing:
  percentile desc, sectorCode asc
current percentile missing:
  sectorCode asc
```

`SAMPLE_INSUFFICIENT` 有二维坐标，因此属于第一组。排序只能在 service 中执行一次；schema 和 adapter 只验证，不另行排序。

### 6.25 数量、状态与时间前沿不变量

```text
totalCount = len(items) = len(resolve_scope_pool())
currentCalculableCount = count(item.percentile is not null)
plottableCount = count(item.coordinateStatus == PLOTTABLE)
missingCoordinateCount = totalCount - plottableCount
```

当 `groupInterpretation=QUADRANT`：

```text
sum(four quadrantCounts) == plottableCount
every PLOTTABLE row has one quadrant status
```

当 `groupInterpretation=SAMPLE_INSUFFICIENT`：

```text
sum(four quadrantCounts) == 0
every PLOTTABLE row has SAMPLE_INSUFFICIENT
```

主状态：

1. 当前日 `currentCalculableCount>0` 且 observed=expected：READY。
2. 默认日回退且 `currentCalculableCount>0`：DELAYED。
3. 显式 MISSING、没有 display date 或当前日 `currentCalculableCount=0`：EMPTY，`analysis=null`。
4. 层级、查询、纯计算或 DTO 不变量失败：ERROR，`analysis=null`。
5. `plottableCount=0` 但 `currentCalculableCount>0` 仍为 Ready/Delayed 的 Missing Coordinate 内容态，因为一维 X 事实仍可展示。

时间前沿反例必须证明：修改任意计算日 `d` 之后的 `dc_daily` 输入，不改变 `d` 的 return、rank、percentile、Y、状态和缺失原因；把未来行加入 fact_index 也不能改变已计算日期。任何基于响应末日回填旧点、用当前排名替代历史排名或连接 null 两端的实现都判为失败。

### 6.26 Meta、Results 组合和异常顺序

相对轮动 Meta 直接复用 `SectorAnalysisMetaQueryService.load()` 的不可变事实并映射专属 DTO；正常路径3条 SQL，不读取轮动结果。

Results 的异常顺序固定为：

1. API 校验 unknown/duplicate、格式和固定枚举；失败0条业务 SQL。
2. 公共 context 与层级加载后立即校验 `hierarchyVersion`；不一致返回409，行情 SQL为0。
3. `resolve_scope_pool()` 校验父级闭包；非法范围返回400，不加载窗口行情。
4. 解析日期；显式非法日期返回400，显式 MISSING 返回200 EMPTY，默认延迟按公共规则回退。
5. 批量读取日历和行情，执行纯计算与 strict DTO。
6. 已知 scope/selection/version 异常必须透传；层级不可用映射 `SA_HIERARCHY_UNAVAILABLE`，其余未分类内部异常映射 `SA_QUERY_FAILED`。不得用大范围 `except` 把400/409吞成200 ERROR。

### 6.27 M10 后端伪代码停止点

```python
class SectorRelativeRotationQueryService:
    def build_meta(...) -> SectorRelativeRotationMetaResponseDto: ...

    def build_results(...) -> SectorRelativeRotationResultsResponseDto:
        # 只执行第6.22节主链，不处理前端 search/quadrant。
        ...

class SectorRelativeRotationCalculator:
    def calculate_grid(
        *,
        sector_codes: tuple[str, ...],
        open_dates: tuple[date, ...],
        display_dates: tuple[date, ...],
        rank_slices: Mapping[date, SectorRelativeRotationRankSlice],
    ) -> dict[date, tuple[SectorRelativeRotationPointFact, ...]]: ...

    def canonical_sort(
        rows: Iterable[SectorRelativeRotationPointFact],
    ) -> tuple[SectorRelativeRotationPointFact, ...]: ...
```

`rank_slices` 中每个切片必须同时携带已经计算好的 `SectorReturnFact` 和 `SectorRankFact`。计算器只做对齐校验、X/Y、样本与四象限计算；不得从排名事实反推或猜测缺失原因。

M10 完成后必须停止：只允许后端、测试、异常注册表／两份既有设计文档的状态对账；不增加前端路由，不把方法按钮改成可用，不修改 Figma，不部署、不读写新数据源。

### 6.28 成员广度不可变合同

```python
SectorMemberBreadthMetric = Literal["MEMBER_COUNT", "TURNOVER", "MA_POSITION"]
SectorMemberBreadthDirection = Literal["UP", "DOWN"]
SectorMemberBreadthMaPeriod = Literal[5, 10, 15, 20, 30, 60]
SectorMemberBreadthHistoryRange = Literal[20, 30, 60]
SectorMemberBreadthQualification = Literal["ELIGIBLE", "INELIGIBLE"]
SectorMemberBreadthAvailability = Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE"]

MEMBER_BREADTH_FORMULA_KEY = "sector-member-breadth"
MEMBER_BREADTH_FORMULA_VERSION = 1
MEMBER_BREADTH_MINIMUM_CALCULABLE_COUNT = 5
MEMBER_BREADTH_MINIMUM_COVERAGE_PCT = Decimal("80")
```

五类 scope 直接复用 `SectorMomentumScope/resolve_scope_pool()`；不得复制父级闭包算法。`direction=UP` 选择 `upMemberPct/upAmountPct/aboveMaPct`，`DOWN` 选择 `downMemberPct/downAmountPct/belowMaPct`。平盘／等于均线是中性组成，进入分母但不进入上涨或下跌值。

来源事实至少拆成下列不可变值对象：

```python
MemberRelationFact(sector_code, trade_date, stock_code, stock_name)
MemberMarketFact(stock_code, trade_date, close, pct_change, amount_thousand_yuan, adj_factor)
MetricCoverageFact(source_count, calculable_count, coverage_pct, eligible, reason_codes)
MemberBreadthCompositionFact(metric, up_count, flat_count, down_count, up_pct, flat_pct, down_pct, coverage)
MemberBreadthRankFact(sector_code, metric_value_pct, rank, rank_total, coverage, reason_codes)
MemberBreadthTrendPointFact(trade_date, member_pct, turnover_pct, ma_position_pct, per_metric_reasons)
MemberBreadthMemberFact(stock_code, stock_name, daily_pct_change, amount_thousand_yuan, amount_contribution_pct, ma_relation, ma_distance_pct, reason_codes)
```

结构化原因至少包含：`SOURCE_MEMBER_EMPTY/MARKET_ROW_MISSING/PCT_CHANGE_MISSING/AMOUNT_MISSING/AMOUNT_NON_POSITIVE/ADJ_FACTOR_MISSING/ADJ_FACTOR_NON_POSITIVE/MA_HISTORY_INSUFFICIENT/MINIMUM_COUNT_NOT_MET/COVERAGE_NOT_MET`。原因属于指标或成员事实，不得升级成技术异常。

### 6.29 三项纯计算和资格

对行业 `s`、事实日 `t`、来源成员集合 `S(s,t)`：

```text
C_member = pct_chg(t) 有限的成员
member up/flat/down = 按 pct_chg 正/零/负计数 ÷ count(C_member)

C_amount = pct_chg(t) 有限且 amount(t) 有限并 >=0 的成员
amount up/flat/down = 对应方向 amount 合计 ÷ sum(C_amount.amount)

adjustedBasis(i,d) = close(i,d) × adj_factor(i,d)
MA_N(i,t) = 最近 N 个 SSE 开市日 adjustedBasis 的平均值
C_ma = N 日 close>0 与 adj_factor>0 全部存在的成员
ma above/equal/below = 对应关系计数 ÷ count(C_ma)
```

每项单独计算：

```text
coveragePct = calculableCount / sourceCount × 100
eligible = calculableCount >= 5 and coveragePct >= 80
```

不变量：

1. 三项的 `sourceCount` 相同，均来自 `S(s,t)`；`calculableCount/coveragePct/eligible/reasonCodes` 独立。
2. `adj_factor` 缺失或无效只影响 `C_ma`，不得删除成员、减少 `C_member/C_amount` 或改变它们的资格。
3. `totalAmount=0` 时成交额指标不可计算，不能返回 `0%`。
4. 组成百分比在有分母时合计100%，量化误差只允许来自 DTO 最终精度；中间计算全部使用 `Decimal`。
5. 资格不通过的行业仍进入完整列表；`metricValuePct/rank/rankTotal` 为 null，原因必须可解释。
6. 合格行业按所选方向和指标值降序使用标准竞争排名 `1,2,2,4`；并列行按 `sectorCode` 升序显示但不打破名次。
7. Rankings 只调用所请求指标的计算入口；禁止生成未请求指标，特别是数量／成交额请求不得计算 MA。
8. Details 为同一选中行业同时计算三项组成、趋势和成员明细；趋势点缺失保留日期槽并断线，不补零或前向填充。
9. 每个趋势点使用该日 `dc_member`，并且只读取该点及以前的价格／因子。改变未来成员、价格或因子不得改变过去结果。

### 6.30 Query 集合边界与 SQL

`SectorMemberBreadthQuery` 只暴露集合读取，不返回 ORM 实例。日期窗口与成员关系必须由同一条 SQL 返回，避免在增加公共页面日期查询后突破4条上限：

```python
load_window_relations(
    session,
    *,
    target_date,
    coverage_end_date,
    hierarchy_sector_codes,
    relation_sector_codes,
    open_date_count,
    relation_date_count,
) -> MemberBreadthWindowRelationsFact
load_market_facts(session, *, stock_codes, start_date, end_date) -> tuple[MemberMarketFact, ...]
```

`MemberBreadthWindowRelationsFact` 至少包含 `coverage_start_date/coverage_end_date/open_dates/relation_dates/relations`。合并 SQL 必须：

1. 只用当前 hierarchy 全部代码和有效 `dc_daily(category='行业板块')` 事实计算公共 `coverageStartDate`，不返回全历史覆盖序列。
2. 验证 `coverageStartDate <= targetDate <= coverageEndDate` 且目标日是 SSE 开市日；范围或休市日非法时抛出 `SectorSelectionInvalidError`。
3. 返回截至目标日升序的最多 `open_date_count` 个 SSE 开市日；上限119，120必须在 SQL 前拒绝。
4. 只为最后 `relation_date_count` 个显示日期读取 `relation_sector_codes` 的来源成员；Rankings 固定1个关系日，Details 最多60个关系日。
5. 即使某个显示日期没有成员，也保留该日期槽；不得用成员表内连接删除交易日。
6. 对 `(trade_date, sector_code, stock_code)` 做唯一性校验；不得静默去重。

SQL 边界：

1. Meta 固定复用 `SectorAnalysisMetaQueryService.load()` 的三条 SQL：公共业务日、层级、当前行业 `dc_daily` 日期覆盖。不得调用 `load_window_relations/load_market_facts`。
2. Rankings 最多四条：层级1条、既有 `MarketPageContextQuery.resolve_context(requested_trade_date=None)` 1条、目标窗口／公共覆盖起点／当前比较池成员合并查询1条、去重股票的日行情与复权因子批量读取1条。`metric=MEMBER_COUNT/TURNOVER` 时窗口收缩到1日且不投影复权列；`MA_POSITION` 使用 `maPeriod` 日。
3. Details 最多四条：层级1条、既有公共页面日期1条、最多 `historyRange + maPeriod - 1`（上限119）个开市日／公共覆盖起点／当前行业逐日成员合并查询1条、去重股票的行情与因子批量读取1条。
4. `hierarchyVersion` 必须在成员和股票事实查询前核验；不一致立即抛出版本冲突。
5. 成员业务键 `(trade_date, sector_code, stock_code)`、行情／因子键 `(stock_code, trade_date)` 必须唯一；重复行属于合同失败，不得静默去重。
6. Query 不判断资格、不生成页面状态、不拼 DTO；Calculator 不访问 Session。禁止按行业、趋势日或股票循环查询。
7. 现有 `SectorMemberDetailQuery/Service/Calculator` 零修改；不得复用其30日上限或 `pct_chg` 连乘返回值。
8. 禁止在新 Query 中复制 `MarketPageContextQuery` 的20:00算法；`coverage_end_date` 只能来自该公共查询。禁止为保持旧方法签名而额外执行分离的 `load_open_dates/load_relations` 两条 SQL。

### 6.31 Meta、Rankings、Details 编排

```python
class SectorMemberBreadthQueryService:
    def build_meta(self, session, *, market):
        facts = common_meta_service.load(session, market=market)  # 恰好3条SQL
        expected = facts.context.trade_date
        default = expected if expected对应公共COMPLETE else 最近公共COMPLETE
        return method_meta_dto(dateCoverageBasis="INDUSTRY_DAILY", ...)

    def build_rankings(self, session, *, request):
        hierarchy = hierarchy_query.load(session)
        assert_version_before_source_reads(hierarchy, request.hierarchy_version)
        pool = resolve_scope_pool(...)
        context = context_query.resolve_context(                 # 公共20:00口径
            session, market=request.market, requested_trade_date=None
        )
        window = query.load_window_relations(
            ...,
            target_date=request.trade_date,
            coverage_end_date=context.trade_date,
            hierarchy_sector_codes=all_current_hierarchy_codes,
            relation_sector_codes=pool_codes,
            open_date_count=1 or request.ma_period,
            relation_date_count=1,
        )
        market = query.load_market_facts(..., requested metric projection)
        rows = calculator.rank_requested_metric(...)
        return rankings_dto(...)

    def build_details(self, session, *, request):
        hierarchy = hierarchy_query.load(session)
        assert_selected_node_and_version(...)
        context = context_query.resolve_context(
            session, market=request.market, requested_trade_date=None
        )
        window = query.load_window_relations(
            ...,
            target_date=request.trade_date,
            coverage_end_date=context.trade_date,
            hierarchy_sector_codes=all_current_hierarchy_codes,
            relation_sector_codes=(request.sector_code,),
            open_date_count=request.history_range + request.ma_period - 1,
            relation_date_count=request.history_range,
        )
        market = query.load_market_facts(..., full bounded window)
        facts = calculator.build_details(...)
        return details_dto(...)
```

Meta 在内存中从公共 `tradeDates` 找默认日期，不增加第四条 SQL。`defaultTradeDate=None` 时默认模式为 Empty。Rankings／Details 的 `tradeDate` 都是实际计算日期且必填；它们不接受 `isDelayed/dateMode`，也不从日期值反推用户意图。计算接口通过公共页面日期获得覆盖上界，通过合并窗口／成员 SQL 获得当前层级覆盖起点和 SSE 开市日校验，因此既不信任前端 Meta 结果，也不重复 Meta 的完整日期覆盖扫描。

M14 完成后停止：只允许后端、测试、异常注册表及两份设计文档状态对账；不启用前端按钮、不注册前端 route、不修改 Figma、不部署、不进入 M15。

## 7. API 与 DTO 冻结

### 7.1 Router 形态

一个 router：

```python
router = APIRouter(prefix="/wealth/market/sector-analysis", tags=["wealth-market"])
```

既有六个 `GET` 与 M10 新增两个 `GET` 均复用 `require_quote_access` 和 `get_db_session`。每个请求先显式检查 unknown/duplicate query 参数，再做类型和闭包校验；不得依赖 FastAPI 默认忽略未知参数。

### 7.2 Meta

```http
GET /api/v1/wealth/market/sector-analysis/meta?market=CN_A
```

```python
class SectorTradeDateAvailabilityDto(StrictDto):
    tradeDate: date
    availability: Literal["COMPLETE", "PARTIAL", "MISSING"]
    expectedSectorCount: int
    validSectorCount: int

class SectorAnalysisMetaResponseDto(StrictDto):
    formula: SectorFormulaDto
    hierarchy: SectorHierarchyDto
    coverageStartDate: date
    coverageEndDate: date
    tradeDates: list[SectorTradeDateAvailabilityDto]
```

Meta 的 `tradeDates` 日期严格升序、无重复，且必须等于覆盖闭区间内 SSE 开市日全集。`expectedSectorCount` 从本次请求加载的 hierarchy snapshot 节点数动态取得，本次审计值为 496，禁止写成代码常量；`validSectorCount` 只统计当前层级代码中业务键唯一、close 有限且大于 0、pct_change 有限的行。`COMPLETE/PARTIAL/MISSING` 分别对应 `valid=expected`、`0<valid<expected`、`valid=0`。

`SectorHierarchyNodeDto` 字段：

```text
sectorCode, sectorName, industryLevel,
parentSectorCode, parentSectorName,
rootSectorCode, rootSectorName,
hierarchyPath, displayOrder, isLeaf
```

Meta 只存在成功 DTO。层级空、多版本或闭包非法时 API 返回 HTTP 500、业务 code `SA_HIERARCHY_UNAVAILABLE`；前端进入 ERROR，不使用空 hierarchy 猜默认值。

### 7.3 Rankings 请求

```text
market=CN_A
tradeDate?=YYYY-MM-DD
scope=LEVEL_1|LEVEL_2|LEVEL_3|LEVEL_1_CHILDREN|LEVEL_2_CHILDREN
level1Code?=BKxxxx.DC
level2Code?=BKxxxx.DC
period=1|5|10|20|30
direction=GAINERS|LOSERS
debug=0|1
```

响应：

```python
class SectorMomentumRankingsResponseDto(StrictDto):
    status: Literal["READY", "DELAYED", "EMPTY", "ERROR"]
    tradingDay: SectorAnalysisTradingDayDto
    pageStatus: SectorAnalysisPageStatusDto
    ranking: SectorRankingDto | None
    message: str | None
    exceptionCode: str | None
    debugInfo: SectorAnalysisDebugInfoDto | None
```

`SectorAnalysisTradingDayDto` 固定字段：

```text
expectedTradeDate, observedTradeDate,
expectedAvailability, expectedSectorCount, expectedValidSectorCount,
observedAvailability, observedValidSectorCount
```

显式完整／部分缺失日的 expected 与 observed 相同；默认目标日不完整时，expected 保留目标日及其 PARTIAL/MISSING 覆盖，observed 指向最近 COMPLETE 日。这样页面既能展示回退事实，也不会隐藏当天为何回退。

`SectorRankingDto`：

```text
formulaKey, formulaVersion, hierarchyVersion,
scope, period, direction, parentSelection,
totalCount, calculableCount, rows
```

`SectorRankingRowDto`：

```text
listPosition: int
strengthRank: int | null
sectorCode: string
sectorName: string
industryLevel: 1|2|3
parentSectorCode: string|null
parentSectorName: string|null
hierarchyPath: string
returnPct: number|null
percentile: number|null
canDrillDown: boolean
```

### 7.4 History 请求

history 参数与 rankings 相同，删除 `direction`，增加：

```text
historyRange=20|30|60
sectorCode=BKxxxx.DC
```

重复或未知 `direction` 必须返回 400，不能接收后忽略。

```python
class SectorMomentumHistoryResponseDto(StrictDto):
    status: Literal["READY", "DELAYED", "EMPTY", "ERROR"]
    tradingDay: SectorAnalysisTradingDayDto
    pageStatus: SectorAnalysisPageStatusDto
    detail: SectorMomentumDetailDto | None
    rollingReturns: list[RollingReturnPointDto]
    historicalRanks: list[HistoricalRankPointDto]
    message: str | None
    exceptionCode: str | None
    debugInfo: SectorAnalysisDebugInfoDto | None
```

Detail 字段：

```text
sectorCode, sectorName, industryLevel, hierarchyPath, scopeTitle,
returnPct, percentile,
currentScopeStrengthRank/currentScopeCalculableCount/currentScopeTotalCount,
globalLevelStrengthRank/globalLevelCalculableCount/globalLevelTotalCount,
parentStrengthRank/parentCalculableCount/parentTotalCount,
formulaKey/formulaVersion/hierarchyVersion
```

一级的 parent 三字段为 null。二级/三级按产品合同同时返回全层级和直属父级内摘要；当前 scope 摘要始终对应历史线的分母。

### 7.5 状态校验器

Pydantic 全部 `ConfigDict(extra="forbid")`，并增加模型级校验：

1. READY/DELAYED rankings 必须有 ranking 且 `calculableCount>0`，rows 数等于 totalCount。
2. EMPTY/ERROR rankings 的 ranking 可保留规范化选择和空 rows，但不得带伪造可计算值；首版统一设 `ranking=null`，减少歧义。
3. READY/DELAYED history 必须有 detail，两数组日期一一对应。
4. EMPTY/ERROR history 必须 detail=null、两数组为空。
5. DELAYED 必须 `observedTradeDate < expectedTradeDate`、`expectedAvailability in {PARTIAL,MISSING}` 且 `observedAvailability=COMPLETE`；READY 必须日期相等且 expectedAvailability 不得为 MISSING。
6. 所有 count 非负且不大于 expectedSectorCount；COMPLETE/PARTIAL/MISSING 与 count 关系必须满足 Meta 的同一判定式。
7. exceptionCode 与状态一致；READY 为 null。
8. debugInfo 只在现有 local/dev/test debug 门禁下出现。

### 7.6 HTTP 与异常映射

| 情况 | HTTP | code | 页面状态 |
|---|---:|---|---|
| 启用行情登录门禁后未登录 | 401 | `require_quote_access` | 全页权限壳 |
| 未知/重复参数、非法市场 | 400 | `SA_SCOPE_INVALID` 或通用请求错误 | 不发后续请求 |
| scope/父级闭包非法 | 400 | `SA_SCOPE_INVALID` | 保留当前页面并提示修正 |
| sectorCode 不在比较池 | 400 | `SA_SELECTION_INVALID` | URL 状态无效，不静默换行业 |
| 默认目标日 PARTIAL/MISSING | 200 | `SA_SOURCE_DELAYED` | DELAYED，保留最近 COMPLETE 日内容并说明目标日覆盖 |
| 显式 MISSING 日或当前周期全部不可计算 | 200 | `SA_SOURCE_EMPTY` | EMPTY；日期缺口仍保留在选择器 |
| 层级不可用 | 500(meta) / 200(业务响应) | `SA_HIERARCHY_UNAVAILABLE` | ERROR |
| 未分类查询/计算异常 | 200 | `SA_QUERY_FAILED` | ERROR |
| members 层级版本过期 | 409 | `SA_MEMBER_FACT_MISMATCH` | 成员局部 ERROR；清空四类事实并从 meta 重载 |
| members 来源成员为空 | 200 | `SA_MEMBER_SOURCE_EMPTY` | 成员局部 EMPTY；上榜单和右详情保留 |
| members 查询/计算失败 | 200 | `SA_MEMBER_QUERY_FAILED` | 成员局部 ERROR；仅重试 members |

Meta 无法构建页面对象池时返回 500；rankings/history 已有稳定响应壳时返回 200 ERROR；members 使用自己的严格响应壳和局部状态。三类都由同一异常 builder 生成安全文案，不返回 SQL、堆栈、连接信息或源凭据。

### 7.7 Members 请求与 DTO

```http
GET /api/v1/wealth/market/sector-analysis/momentum/members
  ?market=CN_A
  &tradeDate=2026-08-27
  &hierarchyVersion=dc-industry-v1
  &sectorCode=BKyyyy.DC
  &period=20
  &direction=GAINERS
```

所有参数均必填；不接受 `scope/level1Code/level2Code/historyRange/range/limit/offset/sort/debug`。`market` 只允许 `CN_A`，`tradeDate` 必须是显式 ISO 日期和 SSE 开市日，`sectorCode` 必须是 `BKxxxx.DC` 且属于指定层级版本的三级行业。

```python
class SectorMemberRowDto(StrictDto):
    stockName: str | None
    stockCode: str
    close: Decimal | None
    returnPct: Decimal | None

class SectorMemberDetailResponseDto(StrictDto):
    status: Literal["READY", "EMPTY", "ERROR"]
    message: str | None
    exceptionCode: str | None
    tradeDate: date
    hierarchyVersion: str
    sectorCode: str
    sectorName: str
    period: Literal[1, 5, 10, 20, 30]
    direction: Literal["GAINERS", "LOSERS"]
    totalMemberCount: int
    closeAvailableCount: int
    calculableCount: int
    rows: list[SectorMemberRowDto]
```

模型级校验：

1. `rows` 股票代码唯一，顺序满足第 6.14 节；`rows.length=totalMemberCount`。
2. 三个 count 均非负且不大于 total；`calculableCount` 与 `closeAvailableCount` 互不要求包含。
3. READY 必须 `totalMemberCount>0`，允许 `closeAvailableCount=0` 或 `calculableCount=0`；exceptionCode 为 null。
4. EMPTY 必须 `totalMemberCount=closeAvailableCount=calculableCount=0`、rows 为空、exceptionCode=`SA_MEMBER_SOURCE_EMPTY`。
5. ERROR 不返回来源行，三个 count 为 0、rows 为空；exceptionCode 只允许 `SA_MEMBER_QUERY_FAILED`。版本不一致在 HTTP 409 错误壳返回 `SA_MEMBER_FACT_MISMATCH`，不伪造 200 ERROR DTO。
6. `stockCode` 保留完整 `ts_code`；`stockName/close/returnPct` 可空。API 使用 Decimal JSON number，不返回格式化字符串。

### 7.8 双动量 Meta 请求与 DTO

```http
GET /api/v1/wealth/market/sector-analysis/dual-momentum/meta?market=CN_A
```

只接受 `market`，未知或重复参数返回 400。专属 schema 可以复用既有 `SectorHierarchyDto`、`SectorTradeDateAvailabilityDto`、`SectorAnalysisTradingDayDto`、`SectorAnalysisPageStatusDto` 和安全 Debug DTO，但不能复用 `SectorFormulaDto`。

```python
class SectorDualMomentumFormulaDto(StrictDto):
    formulaKey: Literal["sector-dual-momentum"]
    formulaVersion: Literal[1]
    basisFormulaKey: Literal["sector-cross-sectional-momentum"]
    basisFormulaVersion: Literal[1]
    periods: list[Literal[5, 10, 20, 30]]
    leadingThresholds: list[Literal[70, 80, 90]]
    minimumGroupSize: Literal[3]
    scopes: list[SectorMomentumScopeValue]

class SectorDualMomentumDefaultsDto(StrictDto):
    scope: Literal["LEVEL_1"]
    period: Literal[20]
    leadingThreshold: Literal[80]
    resultView: Literal["QUALIFIED"]

class SectorDualMomentumMetaResponseDto(StrictDto):
    status: Literal["READY", "DELAYED"]
    tradingDay: SectorAnalysisTradingDayDto
    pageStatus: SectorAnalysisPageStatusDto
    message: str | None
    exceptionCode: str | None
    debugInfo: SectorAnalysisDebugInfoDto | None
    formula: SectorDualMomentumFormulaDto
    defaults: SectorDualMomentumDefaultsDto
    hierarchy: SectorHierarchyDto
    coverageStartDate: date
    coverageEndDate: date
    tradeDates: list[SectorTradeDateAvailabilityDto]
```

Meta 的 `status/tradingDay` 只描述公共默认业务日期当前是否回退，用于首屏提示；用户选中的历史日期以 Results 为权威。Meta 构建失败继续使用 HTTP 500 安全错误壳，不伪造带空层级的 ERROR DTO。`periods/leadingThresholds/scopes` 必须按上面顺序精确返回，不能混入 1 日、direction 或 historyRange。

### 7.9 双动量 Results 请求与 DTO

```http
GET /api/v1/wealth/market/sector-analysis/dual-momentum/results
  ?market=CN_A
  &tradeDate=2026-08-27
  &scope=LEVEL_1
  &period=20
  &leadingThreshold=80
  &hierarchyVersion=dc-industry-v1
  &debug=0
```

请求字段严格为：

```text
market=CN_A
tradeDate?=YYYY-MM-DD
scope=LEVEL_1|LEVEL_2|LEVEL_3|LEVEL_1_CHILDREN|LEVEL_2_CHILDREN
level1Code?=BKxxxx.DC
level2Code?=BKxxxx.DC
period=5|10|20|30
leadingThreshold=70|80|90
hierarchyVersion=<non-empty, max 128>
debug=0|1
```

`market/scope/period/leadingThreshold/hierarchyVersion` 必填；`tradeDate` 缺省时使用公共业务日期。父级字段仍按既有 scope 闭包校验。请求禁止 `resultView/sectorCode/sort/direction/historyRange/range/limit/offset`，收到即 400，不能接收后忽略。

```python
AbsoluteStatus = Literal["POSITIVE", "NOT_POSITIVE", "UNAVAILABLE"]
RelativeStatus = Literal[
    "LEADING", "NOT_LEADING", "SAMPLE_INSUFFICIENT", "UNAVAILABLE"
]
QualificationStatus = Literal["QUALIFIED", "NOT_QUALIFIED", "NOT_EVALUATED"]
CoordinateStatus = Literal["PLOTTABLE", "UNAVAILABLE"]
DisplayStatus = Literal[
    "QUALIFIED", "UP_NOT_LEADING", "NOT_UP_LEADING",
    "NOT_UP_NOT_LEADING", "SAMPLE_INSUFFICIENT", "DATA_INSUFFICIENT",
]

class SectorDualMomentumRowDto(StrictDto):
    sectorCode: str
    sectorName: str
    industryLevel: Literal[1, 2, 3]
    parentSectorCode: str | None
    parentSectorName: str | None
    hierarchyPath: str
    canDrillDown: bool
    returnPct: float | None
    strengthRank: int | None
    percentile: float | None
    absoluteStatus: AbsoluteStatus
    relativeStatus: RelativeStatus
    qualificationStatus: QualificationStatus
    coordinateStatus: CoordinateStatus
    displayStatus: DisplayStatus
    missingReason: Literal[
        "HISTORY_INSUFFICIENT", "DATE_MISSING", "CLOSE_MISSING",
        "CLOSE_NON_POSITIVE", "PCT_CHANGE_MISSING",
    ] | None

class SectorDualMomentumAnalysisDto(StrictDto):
    formulaKey: Literal["sector-dual-momentum"]
    formulaVersion: Literal[1]
    basisFormulaKey: Literal["sector-cross-sectional-momentum"]
    basisFormulaVersion: Literal[1]
    hierarchyVersion: str
    scope: SectorMomentumScopeValue
    period: Literal[5, 10, 20, 30]
    leadingThreshold: Literal[70, 80, 90]
    minimumGroupSize: Literal[3]
    parentSelection: SectorParentSelectionDto
    totalCount: int
    calculableCount: int
    qualifiedCount: int
    insufficientCount: int
    plottableCount: int
    items: list[SectorDualMomentumRowDto]

class SectorDualMomentumResultsResponseDto(StrictDto):
    status: SectorAnalysisStatusValue
    tradingDay: SectorAnalysisTradingDayDto
    pageStatus: SectorAnalysisPageStatusDto
    analysis: SectorDualMomentumAnalysisDto | None
    message: str | None
    exceptionCode: str | None
    debugInfo: SectorAnalysisDebugInfoDto | None
```

模型级校验必须重算并证明第 6.19 节全部计数、代码唯一、规范排序及状态组合：

1. `returnPct/strengthRank/percentile` 只能同空或同有；同有必须 `coordinateStatus=PLOTTABLE`，同空必须 `UNAVAILABLE` 且 `missingReason` 非空。
2. `QUALIFIED` 必须同时 `POSITIVE + LEADING + PLOTTABLE`；小组和缺数据只能 `NOT_EVALUATED`。
3. READY/DELAYED 必须有 `analysis` 且 `calculableCount>0`；EMPTY/ERROR 必须 `analysis=null`。
4. No Qualified、Small Group、Partial Data 和 Missing Selected Coordinate 都通过 READY/DELAYED 的 `analysis` 表达，不增加响应状态。
5. Decimal 输出沿用既有收益 4 位、百分位 1 位 JSON number；不返回格式化字符串、综合分或预测文案。

### 7.10 双动量 HTTP 与异常映射

| 情况 | HTTP | code | 处理 |
|---|---:|---|---|
| 未登录 | 401 | 认证层 | 全页权限壳 |
| 未知／重复参数、非法枚举或闭包 | 400 | `SA_SCOPE_INVALID` | 不执行后续事实查询 |
| 选中日期非法 | 400 | `SA_SELECTION_INVALID` | 保留输入并提示修正 |
| hierarchyVersion 过期 | 409 | `SA_FACT_VERSION_MISMATCH` | 清空双动量 Meta/Results 并从 Meta 重载 |
| 默认目标日延迟 | 200 | `SA_SOURCE_DELAYED` | DELAYED，保留最近 COMPLETE 日全量结果 |
| 当前池零个可计算对象 | 200 | `SA_SOURCE_EMPTY` | EMPTY |
| 层级不可用 | 500 Meta／200 Results | `SA_HIERARCHY_UNAVAILABLE` | 稳定 ERROR |
| 未分类查询／合同失败 | 500 Meta／200 Results | `SA_QUERY_FAILED` | 稳定 ERROR |

`SA_MEMBER_FACT_MISMATCH` 只能用于成员请求，不能承担双动量版本冲突；两者恢复范围不同。409 必须发生在行情 SQL 之前。

### 7.11 相对轮动 Meta 请求与 DTO

```http
GET /api/v1/wealth/market/sector-analysis/relative-rotation/meta?market=CN_A
```

只接受一个且仅一个 `market=CN_A`；重复、未知或其他市场返回400。DTO：

```python
class SectorRelativeRotationFormulaDto(StrictDto):
    formulaKey: Literal["sector-relative-rotation"]
    formulaVersion: Literal[1]
    basisFormulaKey: Literal["sector-cross-sectional-momentum"]
    basisFormulaVersion: Literal[1]
    periods: list[Literal[5, 10, 20, 30]]
    improvementLookbackDays: Literal[5]
    trailLengths: list[Literal[20, 30, 60]]
    minimumGroupSize: Literal[3]
    scopes: list[SectorMomentumScopeValue]
    xDomain: tuple[Literal[0], Literal[100]]
    xSplit: Literal[50]
    ySplit: Literal[0]

class SectorRelativeRotationDefaultsDto(StrictDto):
    scope: Literal["LEVEL_1"]
    period: Literal[20]
    trailLength: Literal[20]
    quadrantFilter: Literal["ALL"]

class SectorRelativeRotationMetaResponseDto(StrictDto):
    status: Literal["READY", "DELAYED"]
    tradingDay: SectorAnalysisTradingDayDto
    pageStatus: SectorAnalysisPageStatusDto
    message: str | None
    exceptionCode: str | None
    debugInfo: SectorAnalysisDebugInfoDto | None
    formula: SectorRelativeRotationFormulaDto
    defaults: SectorRelativeRotationDefaultsDto
    hierarchy: SectorHierarchyDto
    coverageStartDate: date
    coverageEndDate: date
    tradeDates: list[SectorTradeDateAvailabilityDto]
```

列表枚举顺序必须与 contract 完全一致；Meta 不返回 search、用户当前 quadrant、行业坐标或轨迹。状态、交易日、日期覆盖和 hierarchy validator 复用双动量 Meta 的公共 DTO，不复制校验函数。

### 7.12 相对轮动 Results 请求与 DTO

```http
GET /api/v1/wealth/market/sector-analysis/relative-rotation/results
  ?market=CN_A
  &scope=LEVEL_1
  &period=20
  &trailLength=20
  &hierarchyVersion=dc-industry-v1
```

严格请求字段：

```text
market=CN_A                                      required
tradeDate=YYYY-MM-DD                             optional
scope=LEVEL_1|LEVEL_2|LEVEL_3|LEVEL_1_CHILDREN|LEVEL_2_CHILDREN required
level1Code=BKxxxx.DC                              conditional
level2Code=BKxxxx.DC                              conditional
period=5|10|20|30                                required
trailLength=20|30|60                             required
sectorCode=BKxxxx.DC                              optional
hierarchyVersion=<trimmed non-empty, max 128>     required
debug=0|1                                         optional
```

禁止 `improvementLookbackDays/minimumGroupSize/xSplit/ySplit/quadrant/search/direction/threshold/historyRange/resultView/range/limit/offset/sort`；出现即400，不能接收后忽略。

```python
RelativeRotationStatusValue = Literal[
    "LEADING_IMPROVING", "WEAK_IMPROVING",
    "STRONG_NOT_IMPROVING", "WEAK_NOT_IMPROVING",
    "SAMPLE_INSUFFICIENT", "DATA_INSUFFICIENT",
]
RelativeCoordinateStatusValue = Literal["PLOTTABLE", "UNAVAILABLE"]
RelativeMissingReasonValue = Literal[
    "HISTORY_INSUFFICIENT", "DATE_MISSING", "CLOSE_MISSING",
    "CLOSE_NON_POSITIVE", "PCT_CHANGE_MISSING",
]

class SectorRelativeRotationRowDto(StrictDto):
    sectorCode: str
    sectorName: str
    industryLevel: Literal[1, 2, 3]
    parentSectorCode: str | None
    parentSectorName: str | None
    hierarchyPath: str
    canDrillDown: bool
    returnPct: float | None
    strengthRank: int | None
    percentile: float | None
    percentileDelta5d: float | None
    rotationStatus: RelativeRotationStatusValue
    coordinateStatus: RelativeCoordinateStatusValue
    currentMissingReason: RelativeMissingReasonValue | None
    comparisonMissingReason: RelativeMissingReasonValue | None

class SectorRelativeRotationTrailPointDto(StrictDto):
    tradeDate: date
    returnPct: float | None
    percentile: float | None
    percentileDelta5d: float | None
    rotationStatus: RelativeRotationStatusValue
    coordinateStatus: RelativeCoordinateStatusValue
    currentMissingReason: RelativeMissingReasonValue | None
    comparisonMissingReason: RelativeMissingReasonValue | None

class SectorRelativeRotationTrailDto(StrictDto):
    sectorCode: str
    requestedLength: Literal[20, 30, 60]
    dateSlotCount: int
    points: list[SectorRelativeRotationTrailPointDto]

class SectorRelativeRotationQuadrantCountsDto(StrictDto):
    leadingImproving: int
    weakImproving: int
    strongNotImproving: int
    weakNotImproving: int

class SectorRelativeRotationAnalysisDto(StrictDto):
    formulaKey: Literal["sector-relative-rotation"]
    formulaVersion: Literal[1]
    basisFormulaKey: Literal["sector-cross-sectional-momentum"]
    basisFormulaVersion: Literal[1]
    hierarchyVersion: str
    scope: SectorMomentumScopeValue
    period: Literal[5, 10, 20, 30]
    improvementLookbackDays: Literal[5]
    trailLength: Literal[20, 30, 60]
    minimumGroupSize: Literal[3]
    parentSelection: SectorParentSelectionDto
    selectedSectorCode: str
    groupInterpretation: Literal["QUADRANT", "SAMPLE_INSUFFICIENT"]
    totalCount: int
    currentCalculableCount: int
    plottableCount: int
    missingCoordinateCount: int
    quadrantCounts: SectorRelativeRotationQuadrantCountsDto
    items: list[SectorRelativeRotationRowDto]
    selectedTrail: SectorRelativeRotationTrailDto

class SectorRelativeRotationResultsResponseDto(StrictDto):
    status: SectorAnalysisStatusValue
    tradingDay: SectorAnalysisTradingDayDto
    pageStatus: SectorAnalysisPageStatusDto
    analysis: SectorRelativeRotationAnalysisDto | None
    message: str | None
    exceptionCode: str | None
    debugInfo: SectorAnalysisDebugInfoDto | None
```

跨字段 validator 必须逐项重算：

1. READY/DELAYED 必须有 analysis、至少一个当前百分位、合法选中代码和完全匹配的 selectedTrail；EMPTY/ERROR 必须 `analysis=null`。
2. items 行业代码唯一，长度等于 totalCount，且严格满足第6.24节 canonical 顺序；selected code 必须存在于 items。
3. `returnPct/strengthRank/percentile` 同空同有；当前缺失时三个值全空且 currentMissingReason 非空。比较百分位不直接返回，`percentileDelta5d` 为空时 comparisonMissingReason 必须说明原因，除非当前本身已缺失。
4. `PLOTTABLE` 必须 `percentile` 与 `percentileDelta5d` 同有，missing reasons 均空，rotationStatus 不能 DATA_INSUFFICIENT；`UNAVAILABLE` 必须不能伪造完整二维坐标。
5. `groupInterpretation=QUADRANT` 时可绘制行只能属于四象限且计数之和等于 plottable；`SAMPLE_INSUFFICIENT` 时可绘制行全为该状态且四计数为0。
6. `missingCoordinateCount=totalCount-plottableCount`，全部 count 非负且不超过 total。
7. trail 日期严格升序、唯一，`dateSlotCount=points.length<=requestedLength`，最后一个槽必须等于 `observedTradeDate`；所有点 sector 隐含等于 trail sector，不重复返回代码。
8. Response 的 scope/period/trailLength/hierarchyVersion 和父级选择必须与规范化请求一致；adapter 在前端再次校验，不接受服务端静默改参数。
9. JSON 数值必须有限；return 保留4位、percentile/delta保留1位，不返回 Decimal 字符串、格式化百分号、综合分或前端文案。

### 7.13 相对轮动 HTTP 与异常映射

| 情况 | HTTP | code | 处理 |
|---|---:|---|---|
| 未登录 | 401 | 认证层 | 公共权限壳；不验证不存在的403路径 |
| unknown/duplicate、非法枚举／格式／父级闭包 | 400 | `SA_SCOPE_INVALID` | 停止，不执行后续事实查询 |
| 显式 sectorCode 不在池或日期非法 | 400 | `SA_SELECTION_INVALID` | 不静默换行业／日期 |
| hierarchyVersion 过期 | 409 | `SA_FACT_VERSION_MISMATCH` | 丢弃相对轮动 Meta/Results，只重载相对轮动 Meta |
| 默认目标日延迟 | 200 | `SA_SOURCE_DELAYED` | DELAYED，事实终点使用 observed 日 |
| 显式 MISSING 或当前百分位全空 | 200 | `SA_SOURCE_EMPTY` | EMPTY，不借旧日 |
| 层级不可用 | 500 Meta／200 Results | `SA_HIERARCHY_UNAVAILABLE` | 稳定 ERROR |
| 未分类查询／计算／DTO失败 | 500 Meta／200 Results | `SA_QUERY_FAILED` | 稳定 ERROR，可重试 |

相对轮动与双动量复用 `SA_FACT_VERSION_MISMATCH` 的同一层级版本语义，但恢复状态必须按当前方法隔离；不得清空另一方法或动量排名状态。成员请求继续使用 `SA_MEMBER_FACT_MISMATCH`。

### 7.14 成员广度 Meta DTO

```http
GET /api/v1/wealth/market/sector-analysis/member-breadth/meta?market=CN_A
```

```python
class SectorMemberBreadthDateContextDto(StrictDto):
    expectedTradeDate: date
    defaultTradeDate: date | None
    defaultStatus: Literal["READY", "DELAYED", "EMPTY"]
    displayText: str

class SectorMemberBreadthDefaultsDto(StrictDto):
    scope: Literal["LEVEL_1"]
    direction: Literal["UP"]
    metric: Literal["MEMBER_COUNT"]
    maPeriod: Literal[20]
    historyRange: Literal[20]

class SectorMemberBreadthMetaResponseDto(StrictDto):
    formulaKey: Literal["sector-member-breadth"]
    formulaVersion: Literal[1]
    dateCoverageBasis: Literal["INDUSTRY_DAILY"]
    dateContext: SectorMemberBreadthDateContextDto
    hierarchy: SectorHierarchyDto
    coverageStartDate: date
    coverageEndDate: date
    tradeDates: list[SectorTradeDateAvailabilityDto]
    scopes: list[SectorMomentumScopeValue]
    directions: list[Literal["UP", "DOWN"]]
    metrics: list[Literal["MEMBER_COUNT", "TURNOVER", "MA_POSITION"]]
    maPeriods: list[Literal[5, 10, 15, 20, 30, 60]]
    historyRanges: list[Literal[20, 30, 60]]
    minimumCalculableCount: Literal[5]
    minimumCoveragePct: Literal[80]
    defaults: SectorMemberBreadthDefaultsDto
```

Validator 必须证明：枚举顺序与 contract 完全一致；`tradeDates` 仍是公共行业 `dc_daily` 覆盖且闭区间升序；`defaultTradeDate` 只能是 `tradeDates` 中最近的 COMPLETE 日期；预期日 COMPLETE 时默认日必须等于预期日且状态 READY；预期日不完整但存在更早 COMPLETE 时状态 DELAYED；不存在默认日时状态 EMPTY。Meta 不返回成员、股票或因子覆盖字段。

### 7.15 成员广度 Rankings DTO

请求必填：`market/tradeDate/scope/direction/metric/maPeriod/hierarchyVersion`；父级字段按 scope 条件必填。`tradeDate` 必须是 ISO SSE 开市日且位于 Meta 公共覆盖区间；API 不接受 `dateMode/isDelayed`。

```python
class SectorMemberBreadthAvailabilityDto(StrictDto):
    metric: SectorMemberBreadthMetricValue
    calculableSectorCount: int
    eligibleSectorCount: int
    status: Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE"]
    reasonCodes: list[SectorMemberBreadthReasonValue]

class SectorMemberBreadthRankingRowDto(StrictDto):
    listPosition: int
    rank: int | None
    rankTotal: int | None
    sectorCode: str
    sectorName: str
    industryLevel: Literal[1, 2, 3]
    hierarchyPath: str
    sourceMemberCount: int
    calculableCount: int
    coveragePct: float
    metricValuePct: float | None
    qualificationStatus: Literal["ELIGIBLE", "INELIGIBLE"]
    reasonCodes: list[SectorMemberBreadthReasonValue]

class SectorMemberBreadthRankingsResponseDto(StrictDto):
    status: Literal["READY", "EMPTY", "ERROR"]
    message: str | None
    exceptionCode: str | None
    tradeDate: date
    hierarchyVersion: str
    formulaKey: Literal["sector-member-breadth"]
    formulaVersion: Literal[1]
    scope: SectorMomentumScopeValue
    parentSelection: SectorParentSelectionDto
    direction: Literal["UP", "DOWN"]
    metric: SectorMemberBreadthMetricValue
    maPeriod: Literal[5, 10, 15, 20, 30, 60]
    totalSectorCount: int
    eligibleSectorCount: int
    ineligibleSectorCount: int
    availability: SectorMemberBreadthAvailabilityDto
    defaultSelectedSectorCode: str | None
    rows: list[SectorMemberBreadthRankingRowDto]
```

Validator 必须证明完整列表、连续 `listPosition`、资格计数、标准竞争排名、同值稳定顺序、百分比0..100、`rank/rankTotal/metricValuePct` 同空同有。响应只允许出现请求的一个 metric；不得返回 `metricAvailability[]` 或三项预计算结果。ERROR 安全壳只允许 `SA_HIERARCHY_UNAVAILABLE` 或 `SA_BREADTH_QUERY_FAILED`，且列表和计数必须为空。

`availability` 的生成规则冻结为：

1. `calculableSectorCount` 统计本指标能够得到有效客观百分比的行业数；它不要求行业同时达到 `minimumCalculableCount=5` 和 `minimumCoveragePct=80`。
2. `eligibleSectorCount` 统计在可计算基础上进一步达到上述两项排名资格的行业数。
3. `calculableSectorCount == 0` 时 `status=UNAVAILABLE`。
4. `calculableSectorCount == totalSectorCount` 时 `status=AVAILABLE`。
5. `0 < calculableSectorCount < totalSectorCount` 时 `status=PARTIAL`。
6. `calculableSectorCount > 0 && eligibleSectorCount == 0` 仍返回 `status=READY`、完整行和逐行不可排名原因；只有可计算行业数为 0 才返回 Empty。不得把“小样本不能排名”误写成“没有客观数据”。

### 7.16 成员广度 Details DTO

请求必填：`market/tradeDate/sectorCode/direction/maPeriod/historyRange/hierarchyVersion`。`sectorCode` 必须属于当前层级；Details 不接收 scope/父级/metric，身份由 hierarchy 验证，三项详情同时返回。

```python
class SectorMemberBreadthCompositionDto(StrictDto):
    metric: SectorMemberBreadthMetricValue
    sourceCount: int
    calculableCount: int
    coveragePct: float
    eligible: bool
    positiveCount: int
    neutralCount: int
    negativeCount: int
    positivePct: float | None
    neutralPct: float | None
    negativePct: float | None
    reasonCodes: list[SectorMemberBreadthReasonValue]

class SectorMemberBreadthTrendPointDto(StrictDto):
    tradeDate: date
    memberPct: float | None
    turnoverPct: float | None
    maPositionPct: float | None
    memberReasonCodes: list[SectorMemberBreadthReasonValue]
    turnoverReasonCodes: list[SectorMemberBreadthReasonValue]
    maPositionReasonCodes: list[SectorMemberBreadthReasonValue]

class SectorMemberBreadthMemberRowDto(StrictDto):
    stockName: str | None
    stockCode: str
    dailyPctChg: float | None
    amountThousandYuan: float | None
    amountContributionPct: float | None
    maRelation: Literal["ABOVE", "EQUAL", "BELOW"] | None
    maDistancePct: float | None
    reasonCodes: list[SectorMemberBreadthReasonValue]

class SectorMemberBreadthDetailsResponseDto(StrictDto):
    status: Literal["READY", "EMPTY", "ERROR"]
    message: str | None
    exceptionCode: str | None
    tradeDate: date
    hierarchyVersion: str
    formulaKey: Literal["sector-member-breadth"]
    formulaVersion: Literal[1]
    sectorCode: str
    sectorName: str
    industryLevel: Literal[1, 2, 3]
    hierarchyPath: str
    direction: Literal["UP", "DOWN"]
    maPeriod: Literal[5, 10, 15, 20, 30, 60]
    historyRange: Literal[20, 30, 60]
    compositions: list[SectorMemberBreadthCompositionDto]
    trend: list[SectorMemberBreadthTrendPointDto]
    members: list[SectorMemberBreadthMemberRowDto]
```

Validator 必须证明 compositions 精确三项且顺序固定；有分母时三部分数量和、百分比和正确；趋势日期升序、唯一、最多等于 historyRange 且最后为 tradeDate；成员代码唯一、完整不分页、方向和同值次序稳定。复权因子缺失时 member/turnover 组成仍可 READY，只有 `maPositionPct/maRelation/maDistancePct` 为空并携带原因。ERROR 安全壳只允许 `SA_HIERARCHY_UNAVAILABLE` 或 `SA_BREADTH_QUERY_FAILED`，且组成、趋势和成员列表必须全部为空。

### 7.17 成员广度 HTTP 与异常映射

| 情况 | HTTP | code | 处理 |
|---|---:|---|---|
| 未登录 | 401 | 认证层 | 复用 quote access；不虚构403 |
| unknown/duplicate、非法枚举／格式／父级闭包 | 400 | `SA_SCOPE_INVALID` | 停止，不读取成员或股票事实 |
| 显式日期非法或 sectorCode 不存在 | 400 | `SA_SELECTION_INVALID` | 不静默换日期／行业 |
| hierarchyVersion 过期 | 409 | `SA_BREADTH_FACT_MISMATCH` | 只清空成员广度事实并重载成员广度 Meta |
| 层级为空、多版本或闭包非法 | 500 Meta／200 Rankings/Details | `SA_HIERARCHY_UNAVAILABLE` | Meta 阻断；业务接口返回安全 Error 壳，不混同成员广度计算失败 |
| 选中行业目标日无来源成员 | 200 Details | `SA_BREADTH_SOURCE_EMPTY` | Details 局部 Empty；Rankings 和页面骨架保留 |
| 当前排名指标全池不可计算 | 200 Rankings | `SA_SOURCE_EMPTY` | Rankings Empty；不借用上一日或其他指标 |
| 个别股票／单项指标缺数据 | 200 | 无技术异常码 | READY 中返回覆盖、资格和 reasonCodes |
| 查询／合同失败 | 200 Rankings/Details 或 500 Meta | `SA_BREADTH_QUERY_FAILED` | 安全 Error；不泄露 SQL、表名、堆栈或连接信息 |

`DELAYED` 不是 Rankings／Details 的计算状态：只有 URL 没有 `tradeDate` 且 Meta 的 `defaultStatus=DELAYED` 时，前端把实际日期内容渲染为 Delayed 页面。URL 显式选择同一天时保持普通历史复盘状态。

## 8. 前端低层设计

### 8.1 Shell 状态

`useWealthExplorationShell(search)` 按 M1 前 `WealthExplorationPage` 的既有请求语义迁移：

```ts
interface WealthExplorationShellModel {
  contextState: "loading" | "ready" | "error";
  pageContext: MarketPageContextViewModel | null;
  tickers: readonly TopMarketTicker[];
  retryContext(): void;
}
```

1. context 成功后才加载主要指数 ticker。
2. ticker 失败只清空 ticker，不阻断子页。
3. 子页业务请求必须等待 context ready。
4. landing 不挂载任何业务 controller。
5. turnover 子页继续复用现有 controller 的 5 秒超时和业务状态，不改成交额接口。

### 8.2 URL 状态

```ts
interface SectorMomentumUrlState {
  tradeDate: string | null;
  scope: "level1" | "level2" | "level3" | "level1-children" | "level2-children";
  level1Code: string | null;
  level2Code: string | null;
  period: 1 | 5 | 10 | 20 | 30;
  direction: "gainers" | "losers";
  range: 20 | 30 | 60;
  sectorCode: string | null;
}
```

`parseSectorMomentumUrlState()` 只做语法解析和固定枚举检查；层级闭包和比较池归属由 meta/rankings 事实校验。非法语法不发业务请求，并显示可恢复错误。

写入规则：

1. 选择榜单行只 `replaceState` sectorCode。
2. scope、父级、周期、方向、范围、历史日期和下钻使用 `pushState`。
3. 默认值不强制写入 URL；服务返回规范化选择后，只在需要恢复用户选择时写入。
4. 浏览器 popstate 重新解析全部状态，不保留组件私有旧值。

### 8.3 Controller 状态机

```ts
type MomentumViewState =
  | { kind: "loading"; meta?: MetaVm }
  | { kind: "ready"; meta: MetaVm; ranking: RankingVm; history: HistoryVm; selectedCode: string }
  | { kind: "delayed"; meta: MetaVm; ranking: RankingVm; history: HistoryVm; selectedCode: string }
  | { kind: "empty"; meta: MetaVm; message: string }
  | { kind: "error"; meta?: MetaVm; message: string; retryable: boolean };

type MemberViewState =
  | { kind: "idle" }
  | { kind: "loading"; key: string }
  | { kind: "ready"; key: string; data: MemberVm }
  | { kind: "empty"; key: string; message: string }
  | { kind: "error"; key: string; message: string; retryable: boolean };
```

请求阶段：

1. context ready 后请求 meta。
2. meta 成功后构造覆盖闭区间内的完整交易日选择器：COMPLETE/PARTIAL/MISSING 均保留并显示状态，不允许过滤缺口日。
3. 按 URL/default 请求 rankings；显式 MISSING 日仍发送请求并由真实 EMPTY 响应驱动页面，不能在前端静默改成别的日期。
4. rankings READY/DELAYED 后确定选中行业：保留池内现值；否则首条可计算；否则第一行。
5. 只对选中行业请求 history。
6. direction 变化只刷新 rankings；history key 不含 direction。
7. range 变化只刷新 history。
8. scope/父级/period/tradeDate 变化刷新 rankings 和 history。
9. 每个请求使用 AbortController 和规范化 requestKey；旧响应必须在 reducer 前丢弃。
10. rankings 与 history 的 observedDate、hierarchyVersion、formulaVersion 或日期覆盖计数任一不一致时进入 ERROR，不拼接不同事实。
11. 只有 scope 为 `level3/level2-children` 且整页已经有 rankings READY/DELAYED 和合法 selectedCode 时派生 members 请求；请求事实固定取 rankings 的 `observedTradeDate/hierarchyVersion`，不得使用浏览器时间或 URL 原始目标日。
12. members requestKey 为 `observedTradeDate|hierarchyVersion|sectorCode|period|direction`；`range` 不在 key 中。切换到非三级 scope 立即 abort 并置 idle。
13. members 使用独立 `memberRequestId/memberRetryVersion/AbortController`；局部 loading/empty/error 不改变 MomentumViewState，局部重试只增加 memberRetryVersion。
14. 普通旧响应或请求事实不匹配时只丢弃；收到 HTTP 409 `SA_MEMBER_FACT_MISMATCH` 时清空 meta/rankings/history/member 状态并重新启动 meta 请求。

### 8.4 Adapter 边界

Adapter 允许：

1. 枚举大小写映射。
2. 数值显示文本、`--`、百分号和“第 N / M 名”。
3. 把 Meta 的 COMPLETE/PARTIAL/MISSING 映射为日期控件的完整、部分缺失和整日缺失标记，并展示 `valid/expected`；不得重新判断覆盖状态。
4. 按 API 有效 min/max 生成 ReturnBar 几何。
5. 把两历史数组按日期 zip 为图表 view model，并在不一致时拒绝。
6. 校验 Members `tradeDate/hierarchyVersion/sectorCode/period/direction` 与请求完全一致，校验代码唯一、排序、count 和状态不变量。
7. 把 `stockName/close/returnPct` 的 null 映射为 `--`，收盘价和涨跌幅显示 2 位小数；保留原始 Decimal 数值用于颜色和已由后端确定的顺序。

Adapter 禁止：

1. 计算 returnPct、strengthRank、percentile 或父级排名。
2. 过滤 null 行或重新做业务排序。
3. 根据 direction 生成另一套历史排名。
4. 补日期、补零、前向填充或用最近点延长曲线。
5. 过滤 B 股、停牌、缺行情或空名称成员，重新排序成员，或在前端连乘 `pct_chg`。

ReturnBar 只做视觉几何：有效值的 `maxAbs=max(abs(min),abs(max))`，零点固定 50%，端点为 `50% + value/maxAbs*50%`；全为 0 时只显示零线。红涨绿跌来自 CSS Token，数值文本永远保留。

### 8.5 组件职责

1. `SectorAnalysisMethodBar`：一个 active 按钮；四个未建设按钮只调用页面 toast。
2. `MomentumControlBar`：scope、父级选择器、日期、period、direction 和 DataStatus；不承载计算。
3. `MomentumRankingPanel`：标题、总数、固定表头和滚动区域。
4. `MomentumRankingRow`：真实 button/row 选择语义；下钻是独立 button，阻止事件冒泡。
5. `SelectedSectorSummary`：行业身份、路径、同组强度排名、收益、百分位和二/三级双排名摘要。
6. `RollingReturnChart`、`HistoricalRankChart`：纯 SVG；不引入图表库。
7. `MomentumLinkedTooltip`：由父级 detail panel 持有一个 hoverIndex，两图共享。
8. `MomentumStateSurface`：Loading/Empty/Error；Delayed 不替换内容，只在 DataStatus 显示实际日期。
9. `MomentumLeftWorkspace`：只根据 scope 选择单榜单或 `390+12+464` 双列表骨架，不持有数据计算。
10. `SectorMemberPanel`：成员标题与总数、四列表头、局部四态和滚动行；不增加股票跳转或操作列。

### 8.6 榜单滚动和长文本

1. 非三级 scope 的外层 `MomentumRankingPanel` 高 866px；两个三级 scope 中该 panel 高 390px，外层 `MomentumLeftWorkspace` 高 866px。
2. viewport 使用 `overflow-y:auto; min-height:0; scrollbar-gutter:stable`。
3. rows 容器不做虚拟化；当前层级对象规模可在一个 panel 内完整渲染。若真实 DOM 性能超预算，必须回 LLD，不自行增加 TopN。
4. 行业和路径 `white-space:nowrap; overflow:hidden; text-overflow:ellipsis`。
5. 只有 `scrollWidth > clientWidth` 时才提供 title/Tooltip，避免所有行都重复朗读。
6. `SectorMemberPanel` 高 464px：header 54px、固定表头 40px、viewport 370px、行 48px；成员 viewport 与上部行业 viewport 完全独立。
7. 成员表头和行共享 `240fr 176fr 144fr 192fr` Grid；名称单行省略，后三列禁止换行且右对齐。不得复制 Figma 的固定 752px 内容宽。
8. 成员请求 key 变化后 `viewport.scrollTop=0`；相同 key 的局部重试不要求保留失败前滚动位置。

### 8.7 双图几何

SVG 使用固定的 `776×365` 内部坐标系，但由浏览器按实际容器宽度缩放；页面不使用固定 1600px 坐标：

1. 1600px 基线下图外容器为 776×365；运行时宽度随右列变化、高度保持 365px。SVG 固定使用 `viewBox="0 0 776 365"`，plot padding 固定 left 58/right 28/top 76/bottom 53，与 Figma 基线一致。
2. x 使用共同日期索引均匀分布；显示 20/30/60 时只减少标签密度，不删事实点。
3. return y domain 包含 0；全为同值时增加最小视觉 padding，但 Tooltip 保留真实值。
4. rank y domain 为 `1..max(calculableCount)`，SVG range 从 top 到 bottom，使第 1 名在顶部。
5. null 点切断 path；不跨缺口连线。
6. hover/focus 以最近 x 索引定位，两图同时画 crosshair 和同日期 marker。
7. Tooltip 显示日期、N 日收益、`第 strengthRank 名 / calculableCount 个可计算行业`；同时可显示 totalCount。
8. 只有上图一套 20/30/60 显示范围控件，控制两图共同范围。

### 8.8 可访问性

1. 方法栏使用 `role=tablist` 或 button group；只允许一个 `aria-selected/aria-pressed`。
2. scope/period/direction/range 都用原生 button；父级和日期使用有 label 的 select/date control。
3. 行使用 button 或 roving tabindex；Enter/Space 选择。
4. 下钻按钮的 accessible name 包含行业名和目标层级。
5. SVG 提供 title/desc；键盘 focus 可以更新 Tooltip。
6. 所有 focus-visible 使用 Brand Token 描边，颜色不是唯一涨跌表达。

### 8.9 样式 Token

只允许使用现有 Web Token：

```text
--cs-color-bg / panel / panel-soft / surface-card
--cs-color-text-primary / secondary / muted
--cs-color-market-up / down / flat
--cs-color-brand / warning / error
--cs-color-border-subtle / default / strong
--cs-radius-panel / card / control
--cs-space-*
--cs-font-family-number
```

禁止把 Figma RGB 值复制为新的页面常量。图表颜色也从 CSS custom property 读取后传入 SVG。

### 8.10 双动量路由和方法装配

路由判别联合增加：

```ts
| { kind: "sector-analysis-dual-momentum" }
```

正式路径固定为 `/wealth/exploration/sector-analysis/dual-momentum`。`SectorAnalysisPage` 接收：

```ts
type SectorAnalysisMethod = "momentum-ranking" | "dual-momentum";
```

该段记录 M7 完成时的双动量装配基线：页面只根据路由判别值创建一个 controller 和一个工作区，不得用 CSS 隐藏其他方法。M11 已在第 8.16 节既定联合类型上增加相对轮动第三分支；当时三个已完成方法分别导航到自己的 path，并只保留跨方法共享的 `market/debug/tradeDate`，成员广度和量价分布仍 toast“待建设”。该句只记录 M11 历史状态；M15 已增加成员广度第四分支，当前仅量价分布继续保持零 URL、controller、请求和图表副作用的“待建设”状态。板块分析根地址仍 replace 到动量排名。

### 8.11 双动量 URL 状态

```ts
interface SectorDualMomentumUrlState {
  market: "CN_A";
  debug: boolean;
  tradeDate: string | null;
  scope: "level1" | "level2" | "level3" | "level1-children" | "level2-children";
  level1Code: string | null;
  level2Code: string | null;
  period: 5 | 10 | 20 | 30;
  threshold: 70 | 80 | 90;
  resultView: "qualified" | "all";
  sectorCode: string | null;
}
```

默认值是 `level1 / 20 / 80 / qualified`，日期取公共 context。白名单严格为这 10 个 key；未知、重复、非法日期、代码或枚举进入可恢复的 URL Error，不发 Results。`threshold` 只在前端 URL 使用，API 唯一映射为 `leadingThreshold`。

父级状态规则：全局 scope 切换时可以继续保留 URL 中最近合法的 `level1Code/level2Code`，便于返回父级内 scope；Results request builder 必须按当前 scope 省略无关父级参数。一级选择改变后，原二级不属于新一级时重置为新一级首个合法二级；不得顺带重置日期、周期、阈值或 resultView。

scope、父级、日期、period、threshold 和独立下钻使用 `pushState`；自动规范化失效 `sectorCode` 使用 `replaceState`。浏览器前进／后退重新解析完整 URL，不保留与 URL 冲突的组件旧状态。

### 8.12 双动量 controller 状态与请求

```ts
type DualMomentumViewState =
  | { kind: "loading"; meta?: DualMomentumMetaVm }
  | { kind: "ready"; meta: DualMomentumMetaVm; results: DualMomentumResultsVm; selectedCode: string | null }
  | { kind: "delayed"; meta: DualMomentumMetaVm; results: DualMomentumResultsVm; selectedCode: string | null }
  | { kind: "empty"; meta: DualMomentumMetaVm; message: string }
  | { kind: "error"; meta?: DualMomentumMetaVm; message: string; retryable: boolean };
```

1. 公共 context ready 后请求双动量 Meta；Meta 成功后规范化父级和 URL，再携带其 `hierarchyVersion` 请求 Results。
2. Meta request key 为 `market|debug`；Results key 为 `market|tradeDate|scope|active parents|period|threshold|hierarchyVersion|debug`。
3. `resultView/sectorCode/本地排序` 不在 Results key；这三类交互请求数必须增加 0。
4. Meta 与 Results 各自使用 AbortController、单调 requestId 和 5 秒既有网络超时；旧请求完成后必须在 adapter 和 reducer 前双重校验 key。
5. 409 `SA_FACT_VERSION_MISMATCH` 只允许执行一次“废弃 Meta/Results→重新加载 Meta”；重载后的同一版本再次 409 进入 Error，禁止无限重试。
6. QUALIFIED 视图保留仍 `QUALIFIED` 的 sectorCode，否则选规范结果第一只 Qualified；零符合条件时清空选择。ALL 视图保留仍在比较池的 sectorCode，否则选规范结果第一行。
7. 列表行和散点选择同一个 sectorCode；自动选择写 URL 使用 replace，用户主动选择也使用 replace，避免长列表点击污染浏览器历史。
8. 本地排序初始为 `percentile desc`；只允许 `percentile` 与 `returnPct`，同列点击切换升降序，换列默认降序。排序偏好只在当前挂载周期内保留，刷新重置，不改后端数组和资格。

### 8.13 strict adapter 不变量

Adapter 除格式化和映射外，必须拒绝：未知字段／枚举、错误公式版本、Meta 固定数组缺项或乱序、响应事实与 request 不一致、重复行业代码、计数不一致、错误规范排序、非法状态组合、Ready 无 analysis、Empty/Error 带 analysis。

Adapter 可以生成数字文本、颜色 class、筛选后的展示数组和散点几何输入；不得计算 returnPct、rank、percentile、absolute/relative/qualification/displayStatus，不得把缺值变为 0，也不得用 resultView 解释为新的比较池。

### 8.14 列表、摘要和散点图

1. Result list 使用固定表头和内部纵向滚动，完整展示当前视图；QUALIFIED 只过滤后端 `QUALIFIED`，ALL 保留全部行业和缺值行。
2. 表头本地排序只影响行序；显示序号由当前展示数组 index 派生，不作为业务事实或 API 字段。
3. 名称、路径单行省略且仅溢出时 Tooltip；数值使用 `tabular-nums`，缺值显示 `--`。
4. 选择摘要只消费已选 row；行业名称响应式字号继续使用既有长名称规则，不因双动量复制一套不一致规则。
5. Scatter 使用响应式 SVG，x=`returnPct`，y=`percentile`，y 域固定 `[0,100]`。x 域令 `extent=max(abs(min),abs(max))`；`extent=0` 时为 `[-1,1]`，否则为 `[-1.08*extent,1.08*extent]`。绘制 0% 竖线、阈值横线和右上资格区域。
6. 图中始终绘制全量 `PLOTTABLE` 行，与 resultView 无关。符合条件用填充表达；选中用更大点和品牌描边表达；小组不足使用中性填充。
7. 只有选中行业常驻名称。Pointer/键盘在 10px 命中半径内选择最近点；距离并列时优先当前选中点，再按 sectorCode。Hover 展示名称、路径、收益、排名和百分位。
8. 缺坐标行业不绘点；被选中时摘要保留，图内显示“当前行业坐标不可计算”，不得放在 `(0,0)`。
9. 放大按钮打开同页可访问 dialog，只复用当前全量结果和选择，不发请求、不新增轨迹；Escape、关闭按钮和焦点回归必须可用。

### 8.15 双动量响应式和 Design System

工作区根固定使用：

```css
grid-template-columns: minmax(0, 1fr) 12px minmax(0, 1fr);
```

1600px 命中 `776+12+776`；1512px、1460px 连续等宽收缩并对所有 Grid 子项设置 `min-width:0`；1366px 仅允许公共 `min-width:1460px` 产生页面级横向滚动。不得固定 `width:1564px`、CSS scale 或模块级横向滚动。

颜色、边框、圆角、字体、字号、间距和阴影只使用现有 `--cs-*` Token 与板块分析公共 class。M7 不新增 Design Token、不修改 TopMarketBar/Shortcut、不从 Figma 复制十六进制值，也不引入图表库。

### 8.16 相对轮动路由、方法装配与 URL 状态

路由判别联合新增：

```ts
type WealthExplorationRoute =
  | /* existing */
  | { kind: "sector-analysis-relative-rotation" };

export const WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH =
  "/wealth/exploration/sector-analysis/relative-rotation";

export type SectorAnalysisMethod =
  | "momentum-ranking"
  | "dual-momentum"
  | "relative-rotation";
```

根 `/sector-analysis` 仍 replace 到动量排名；未知方法继续 `not-exploration`。方法切换只保留跨方法公共 query：`market=CN_A`、`debug=1`、合法 `tradeDate`；不得把 period、scope、父级、行业或列表过滤状态带到另一种公式。

相对轮动 URL 状态：

```ts
interface SectorRelativeRotationUrlState {
  market: "CN_A";
  debug: boolean;
  tradeDate: string | null;
  scope: "level1" | "level2" | "level3" | "level1-children" | "level2-children";
  level1Code: string | null;
  level2Code: string | null;
  period: 5 | 10 | 20 | 30;
  trailLength: 20 | 30 | 60;
  sectorCode: string | null;
  quadrant: "all" | "leading-improving" | "weak-improving"
    | "strong-not-improving" | "weak-not-improving";
  search: string;
}
```

默认值为 `CN_A / debug=false / tradeDate=null / level1 / 20 / 20 / sector=null / quadrant=all / search=""`。parser 必须：

1. 只允许上述11个 key，重复 key 失败；代码匹配 `BK[0-9]{4}.DC`，日期做真实 ISO 校验。
2. `search` 先 trim，空字符串不写 URL，长度上限64个 Unicode code points；超限失败而不是截断。
3. 全层级 scope 不接受父级；一级内二级只接受 level1；二级内三级同时接受闭包内 level1/level2。
4. canonical builder 省略默认值和 null；用户改变日期／scope／父级／period／trail 使用 push，行业／象限／搜索使用 replace。
5. URL 不合法进入不可重试 Error，Meta/Results 请求均为0；不得偷偷恢复默认值掩盖坏书签。

### 8.17 相对轮动 controller 状态机

状态分层：

```ts
type RelativeMetaState = Idle | Loading | Ready(metaKey, meta) | Error;
type RelativeResultsState = Idle | Loading | Ready(resultsKey, data)
  | Empty(resultsKey, message) | Error;
type RelativeViewState = Loading | Ready | Delayed | Empty | Error;
```

请求键：

```text
metaKey = market
resultsKey = market|debug|tradeDate|scope|level1|level2|period|trailLength|
             sectorCode|hierarchyVersion
```

`quadrant/search` 不进入 resultsKey。controller 顺序：

1. method 未激活或公共 context 尚未匹配 URL 时维持 idle，API请求0；卸载时 abort Meta/Results。
2. Meta strict 成功后，用 Meta 层级和默认值规范 URL；闭包不合法进入 Error，不发 Results。
3. 生成 Results 请求。每次事实参数变化递增 requestId 并 abort 旧请求；只有 `requestId + resultsKey + 当前URL` 全部一致的响应可提交。
4. 初始 sectorCode 缺省时由服务端规范选择；成功后用 replace 把 response 的 `selectedSectorCode` 写回 URL，不再补发同 key 请求。
5. 行／圆点选择先把新 sectorCode 写入 URL并发 Results；等待期间继续渲染上一份完整“selectedCode + summary + trail + plotScale”，只显示局部 pending，不得把新名称配旧轨迹。新原子响应成功后一次切换。
6. scope/父级切换时，若旧 sector 仍在新池则保留，否则置 null；一级变化先选择其第一直属二级，再校验二级内三级闭包。
7. 搜索和象限过滤用 `useMemo` 派生 `visibleRows`，只影响列表；`plotRows` 始终来自全量 items，当前选择即使被过滤也保留。
8. 409 只允许一次“清相对轮动 Meta/Results→重载相对轮动 Meta”；同一轮再次409进入可重试 Error，禁止无限循环，也不清其他方法状态。
9. 超时固定5000ms；Abort 与旧响应不显示错误。401交公共权限壳；普通错误安全重试当前阶段。

### 8.18 strict adapter 与 ViewModel 边界

`sectorRelativeRotationAdapter.ts` 必须从 `unknown` 开始逐层执行 exact-record 校验，字段白名单与第7.11/7.12节完全一致。它可以生成：

```text
returnText / percentileText / deltaText
statusText / statusClass
scopeTitle / dateLabel
```

但不得：

1. 从 returnPct 重算 percentile／rank。
2. 从两个 percentile 重算 delta。
3. 根据 X/Y 重算象限或小组状态。
4. 删除缺失行、删除 null 日期槽、压缩轨迹或改变 canonical items 顺序。
5. 为缺坐标生成0、上一个值或屏幕中心。

adapter 必须复算全部计数、日期槽、状态组合和排序；任一不变量失败进入 Error，不展示部分解析结果。

### 8.19 组件职责和事件边界

| 组件 | 唯一职责 |
|---|---|
| `RelativeRotationWorkspace` | 组合 toolbar、主状态和 Ready 主区，不计算业务事实 |
| `RelativeRotationToolbar` | scope/父级/日期/period/trail 控件和数据日期提示 |
| `RelativeRotationSelectedSummary` | 当前行业名称、路径、X/Y、区间涨跌幅与状态；长名称单行保护 |
| `RelativeRotationPlot` | 全量当前圆点、选中轨迹、Hover、键盘选择和放大入口 |
| `RelativeRotationIndustryList` | 搜索、象限筛选、完整滚动列表、当前选中行 |
| `RelativeRotationStateSurface` | Loading/Empty/Error 稳定正文骨架 |
| `RelativeRotationExpandedDialog` | 复用相同 points/trail/plotScale，仅改变容器尺寸 |

行点击和圆点点击都调用 `selectSector(code)`；列表中的下钻箭头只对 `canDrillDown=true` 生效并 stopPropagation，按现有父级规则切 scope。搜索框、象限 chip、Hover、放大、关闭弹层不得调用 API。

### 8.20 SVG 几何、坐标范围和标签避让

Figma 正式实例实际属性已在 M9 只读核验：主图工作区 `1088×866`，Chart Header `1088×56`，Selected Summary `1088×75`，Quadrant Plot `1088×733`；绘图区边界为 `left=68/right=36/top=44/bottom=56`，即 `984×633`。实现固定内部 viewBox：

```ts
const VIEWBOX = { width: 1088, height: 733 } as const;
const PLOT = { left: 68, right: 36, top: 44, bottom: 56 } as const;
```

像素映射：

```text
x(value) = left + value / 100 * plotWidth
y(value) = top + (yMax - value) / (yMax - yMin) * plotHeight
```

`plotScale` 在 controller/useMemo 中由“当前全量 PLOTTABLE items + selectedTrail PLOTTABLE points”的有限 delta 生成：

```ts
raw = max(abs(all finite deltas), 0)
extent = raw === 0 ? 1 : niceCeil(raw * 1.08)
yMin = -extent
yMax = extent
xMin = 0
xMax = 100
```

`niceCeil` 只能使用 `1/2/5 × 10^n` 的向上刻度；纵轴固定5条刻度 `[-extent, -extent/2, 0, extent/2, extent]`，显示到最多1位小数；横轴固定 `[0,25,50,75,100]`。普通图和放大图接收同一个 frozen `plotScale` 对象，放大不得重算。

绘制顺序：背景象限→网格/轴→全量普通点→选中轨迹分段线／轨迹点→选中当前点→常驻选中标签→Hover Tooltip。null 轨迹点把 path 切成多段，不跨缺口连线。Small Group 使用中性点，但位置不变。

名称策略：

1. 只有当前选中行业显示常驻标签；其他337个点只在 hover/focus 时显示 Tooltip。
2. 标签宽度按 Canvas/SVG `getComputedTextLength()` 的实测值加左右12px，不按字符数猜；最大宽220px，超出时名称视觉省略且 Tooltip保留全名。
3. 标签候选依次尝试右上、左上、右下、左下，和 viewBox 四边保持至少8px；若与 Tooltip 冲突，Tooltip优先并把常驻标签移到下一个候选。
4. 指针位置用 `getBoundingClientRect()` 映射到 viewBox；命中半径按实际宽度换算，重叠点优先当前选中，再按距离、sectorCode稳定决定。

### 8.21 响应式布局和滚动

Figma 1600基线：Toolbar `1564×128`（内边距12、两行48、行距8）；正文 `1564×866`，主图1088、间距12、列表464。CSS：

```css
.relative-rotation-workspace {
  display: flex;
  flex-direction: column;
  gap: var(--cs-space-12);
  min-width: 0;
  width: 100%;
}

.relative-rotation-ready-grid {
  display: grid;
  grid-template-columns:
    minmax(0, 2.344827586fr)
    12px
    minmax(360px, 1fr);
  height: 866px;
  min-width: 0;
  width: 100%;
}
```

右侧 Industry List 高866：Header 52、过滤区120、Viewport 694，viewport 设置 `overflow-y:auto; scrollbar-gutter:stable`，表头／行共用同一 CSS Grid。完整337行不分页、不虚拟截断；搜索无结果只显示列表局部空态，左图不变。

1512/1460 时主图和列表连续收缩，所有 flex/grid 子项 `min-width:0`；1366只允许公共 `body min-width:1460px` 产生页面级横向查看。模块不能固定1564、增加第二层横向滚动或 CSS scale。

### 8.22 Design System 与可访问性

1. 只使用现有 `--cs-*` 颜色、字体、圆角、阴影和4px间距节奏；不新增 Design Token，不复制 Figma 十六进制值。
2. 数字使用 `var(--cs-font-family-number)` 与 `font-variant-numeric:tabular-nums`；状态不能只靠颜色，必须带中文文本。
3. SVG 圆点可聚焦，Enter/Space选择；搜索、filter、放大和关闭均为原生 button/input。focus-visible 使用现有品牌轮廓。
4. 弹层 `role=dialog aria-modal=true`，打开聚焦关闭按钮，ESC／遮罩／按钮关闭，关闭后焦点回到放大按钮。
5. `prefers-reduced-motion` 下禁用轨迹/点过渡；数据更新不得用动画掩盖旧新事实切换。
6. 行业全名、层级路径和状态都有可访问名称；视觉省略不影响 `title/aria-label` 完整内容。

### 8.23 成员广度路由、URL 与日期模式

新增精确 path `/wealth/exploration/sector-analysis/member-breadth`，只在 M15 注册。`SectorAnalysisMethod` 增加 `member-breadth`；页面使用显式第四分支，只挂载 `useSectorMemberBreadthController` 和 `MemberBreadthWorkspace`。

```ts
interface SectorMemberBreadthUrlState {
  market: "CN_A";
  tradeDate: string | null;
  scope: "level1" | "level2" | "level3" | "level1-children" | "level2-children";
  level1Code: string | null;
  level2Code: string | null;
  direction: "up" | "down";
  metric: "member-count" | "turnover" | "ma-position";
  maPeriod: 5 | 10 | 15 | 20 | 30 | 60;
  historyRange: 20 | 30 | 60;
  sectorCode: string | null;
}
```

`tradeDate=null` 是自动模式，不能在 Meta 返回后立即把默认日期写进 URL；否则刷新后会被误判成用户主动历史复盘。用户操作交易日选择器后才写入 `tradeDate`。清除历史选择时删除该 key 并重新使用 Meta 的 `defaultTradeDate/defaultStatus`。

### 8.24 成员广度 controller 请求状态机

请求顺序：

```text
enter route
  -> GET Meta
  -> actualDate = URL.tradeDate ?? Meta.defaultTradeDate
  -> actualDate null => EMPTY
  -> URL sectorCode 合法且仍属于当前比较池
       => parallel GET Rankings(actualDate) + GET Details(actualDate, sectorCode)
  -> URL 无合法 sectorCode
       => GET Rankings(actualDate)
       => selected = defaultSelectedSectorCode ?? rows[0]?.sectorCode
       => selected null => EMPTY
       => GET Details(actualDate, selected)
```

1. 自动模式的页面主状态由 `Meta.defaultStatus + Rankings/Details` 合成；Meta DELAYED 时使用实际默认日内容和延迟提示。显式历史模式忽略 Meta 的默认延迟提示。
2. Meta、Rankings、Details 各自使用完整 request key、AbortController 和 generation；旧响应不得覆盖当前 URL。
3. scope、父级、日期或 maPeriod 改变时刷新 Rankings 和 Details；direction 改变刷新二者；metric 只刷新 Rankings；historyRange 或 sectorCode 只刷新 Details。
4. controller 只能根据 Rankings 返回的完整池判断当前 sectorCode 是否仍有效；仍在池内时保持选择，退出比较池时选择 `defaultSelectedSectorCode`，没有资格行业则保留第一行并允许 Details 显示样本不足。Meta 不提供排名资格，禁止用层级顺序猜默认选择；无合法选择时不得提前发一次无效 Details。
5. 409 只清空成员广度短期事实，最多自动重载一次 Meta；不得清空或重发其他三个方法。
6. Rankings Ready 而 Details Empty/Error 时保留左榜和右侧局部状态；Details 慢不得使已完成 Rankings 回退到 Loading。
7. 未进入成员广度路由时三只请求数均为0，DOM 和趋势图实例均为0。

### 8.25 strict adapter 与组件职责

adapter 必须复核第7.14～7.16节全部枚举、数量、日期、组成和、百分比、资格、排名、完整成员、请求参数回显和 formula/version。禁止：

1. 在前端计算上涨／下跌、成交额贡献、复权价格、均线、覆盖率、资格或行业排名。
2. 把缺值转成0、前值、最近值或另一指标结果。
3. 依据 Meta 的公共 `tradeDates.availability` 推断成员／行情／因子完整性。
4. 因某项不可用删除行业行、成员行或趋势日期槽。

| 组件 | 唯一职责 |
|---|---|
| `MemberBreadthWorkspace` | 组合 toolbar、主状态和 Ready Grid；M16I 持有不进入 controller／URL 的趋势查看局部状态，以跨越排名指标刷新造成的 Ready 正文短暂卸载 |
| `MemberBreadthToolbar` | scope/父级/日期/方向/metric/maPeriod/historyRange 控件与实际日期提示 |
| `MemberBreadthRankingPanel` | 完整行业榜、固定表头、选中和样本不足表达 |
| `MemberBreadthSelectedSummary` | 当前行业身份、路径、三项覆盖摘要 |
| `MemberBreadthCompositionBars` | 三项独立组成条；只消费 DTO 百分比 |
| `MemberBreadthTrendChart` | 20/30/60 日期槽和三条事实线；null 断线；M16I 受控消费工作区局部查看状态并负责事件、坐标映射和绘制 |
| `MemberBreadthMemberTable` | 完整成员明细、固定表头和内部滚动 |
| `MemberBreadthStateSurface` | Loading/Empty/Error 和 Details 局部 Empty/Error |

#### 8.25.1 M16I 趋势图交互状态机与几何

Figma 状态映射固定为：默认 `IDLE` 视觉依据 `1186:11797`；单击进入后的 `ACTIVE` 视觉依据 `1190:15904`，其中视觉叠层子节点为 `1190:15918`（`1004×232`）。`1190:15904` 是静态视觉验收画板，只冻结横纵十字线、三项交点、浮动轴标签、Tooltip 层级和右侧日期左向避让；鼠标连续移动、Tooltip 右向分支、null 单项和退出行为继续以本节合同及自动化为准，不得从单张静态画板自行推断。

开工审计事实：`MemberBreadthTrendChart.tsx` 是无事件处理器的静态 SVG；排名 metric 变化虽然不刷新 Details，但 `useSectorMemberBreadthController` 会把 Rankings 暂时置为 Loading，`MemberBreadthWorkspace` 因而卸载整个 Ready 正文。若状态只存在于 TrendChart，组件卸载必然违反“metric变化不清除”。M16I 因此把状态提升到持续挂载的 Workspace，仍属于当前方法内部的局部 UI 状态；不得修改 controller，也不得使用模块级缓存或全局状态。股票详情 `DetailChartWorkspace` 已有十字线、浮动轴标签和 Tooltip 左右避让，但其交互由图表库的 pointer move 直接驱动。M16I 只借鉴后者的视觉与边界处理，不复用多面板图表组件，也不改变“单击后才进入查看”的批准语义。

局部状态固定为：

```ts
type MemberBreadthTrendInspection = null | {
  index: number;
  pointerY: number;
};
```

- 该状态由 `MemberBreadthWorkspace` 的 React state 持有，通过受控属性传给 TrendChart；`null` 即 `IDLE`，非空即 `ACTIVE`。
- `index` 是 `details.trend` 的真实日期下标，不保存任意 x 值，也不插值日期或三项指标。
- `pointerY` 是 clamp 后的 viewBox 绘图区 y 坐标，只用于横向辅助线和纵轴浮动标签，不写入 URL、controller 或业务状态。

几何与事件顺序固定为：

1. 继续使用 `VIEW = 920×244`、`left=48/right=18/top=22/bottom=30`；SVG 固定 `preserveAspectRatio="none"`，指针坐标通过 `svg.getBoundingClientRect()` 按实际宽高分别映射到 viewBox，禁止使用浏览器默认等比留白，也禁止假设 CSS 像素等于 viewBox 单位。
2. 主按钮单击落在有效 plot 内时，先计算 `rawIndex = (x-left)/plotWidth×(pointCount-1)`，再 `Math.round()` 并 clamp 到 `0..pointCount-1`；同时 clamp y 到 `top..top+plotHeight`，写入一个新的原子状态。
3. `ACTIVE` 后的 `pointermove` 只有在 plot 内才更新；左右移动重复上述最近日期吸附，上下移动只改变 `pointerY`。`pointerleave` 不清除状态。
4. SVG 内但 plot 外的空白／坐标轴区域再次单击，或可聚焦图表交互面接收 `Escape`，统一置为 `null`。进入 `ACTIVE` 的单击必须把焦点交给图表交互面，使 Esc 有明确作用域；退出后不修改当前行业或页面其他焦点状态。
5. Workspace 收到新的交互身份时清除：`tradeDate + sectorCode + direction + maPeriod + historyRange` 任一变化、Details 非 Ready、页面 Empty/Error 或 trend 被替换均回到 `IDLE`。排名 `metric` 不属于 Details 身份；其刷新期间允许 TrendChart 随 Ready 正文短暂卸载，完成后必须恢复同一状态，不得清除。

`ACTIVE` 绘制顺序固定为：既有网格／轴 → 三条折线 → 纵向日期线与横向百分比线 → 三个有效系列交点 → x/y 浮动轴标签。Tooltip 使用 SVG 外同一图表 body 内的绝对定位 HTML，位于所有绘图层之上：

1. x 浮标显示吸附日 `MM-DD`，Tooltip 标题显示完整 `YYYY-MM-DD`；y 浮标显示由 `pointerY` 反算的 `0..100%` 一位小数。
2. 交点读取同一 `trend[index]` 的 `memberPct/turnoverPct/maPositionPct`。有效值以系列色实心圆和面板色描边高亮；null 不画圆点。
3. Tooltip 三行顺序固定为“成分股占比／成交额占比／均线位置占比”，有效值一位小数百分比，null 为 `--`；只格式化 DTO，不计算业务事实。
4. 吸附 x 超过 plot 宽度62%时 Tooltip 放左侧，否则放右侧；最终位置对图表 body 四边 clamp。Tooltip 使用 `pointer-events:none`，不得阻断移动、单击或退出。
5. 十字线使用 `--cs-color-chart-crosshair-line`，Tooltip 使用 `--cs-color-chart-tooltip-bg/border`，交点继续使用 `member/turnover/ma` 三系列 token；不得新增十六进制颜色或第二套 tooltip 样式。
6. `details.trend` 为空时保持静态空图语义且不可进入 `ACTIVE`；全日三项都为 null 时日期仍可吸附，三点均不画，Tooltip 三项均显示 `--`。

该交互完全使用已加载 Details：点击、移动、退出、Tooltip 避让和焦点操作的成员广度 API 请求增量必须严格为0。

Figma Active 画板中的视觉叠层 `1190:15918` 为 `1004×232`，仅代表1600px设计基线下的视觉比例。运行时仍以本节既有 `VIEW = 920×244` 和 `svg.getBoundingClientRect()` 做真实容器到 viewBox 的映射；不得复制 Figma 绝对 x/y、不得把 `1004×232` 写成固定尺寸，也不得为匹配静态画板改写第8.26节的响应式骨架。

### 8.26 成员广度响应式与 Design System

1600设计基线正文为 `548 + 12 + 1004`，运行时：

```css
.member-breadth-ready-grid {
  display: grid;
  grid-template-columns:
    minmax(480px, 548fr)
    12px
    minmax(0, 1004fr);
  width: 100%;
  min-width: 0;
}
```

榜单和成员表分别使用固定表头+内部纵向滚动，表头与行必须共用同一 CSS Grid 声明。1600/1512/1460 连续收缩且模块无横向滚动；1366遵守公共 `body min-width:1460px`，不得缩放整个页面或把1564写成固定宽度。趋势图使用稳定 viewBox 和容器映射；长名称单行省略并保留 Tooltip/aria-label。颜色、字号、圆角、边框、间距、行情红涨绿跌和数字字体只使用现有 `--cs-*` token。

## 9. 状态、缺失与交互规则

### 9.1 五态

| 前端态 | 来源 | UI |
|---|---|---|
| LOADING | 任一当前 request pending | `1036:634`，保留 shell/method/toolbar，正文 skeleton |
| READY | 至少一个可计算行业且 observed=expected | 对应六类 Ready 榜单画板；共享 Hover 见 `1053:5261` |
| DELAYED | 默认请求 observed<expected | `1036:1014`，保留内容并显示实际日期 |
| EMPTY | 显式日无数据或当前池全部不可计算 | `1036:1386`，不展示旧事实 |
| ERROR | meta、query、合同或组合失败 | `1036:1762`，安全文案和重试 |

`PARTIAL` 只描述交易日来源覆盖，不是页面态。显式 PARTIAL 日仍使用 READY 骨架，缺值行业继续存在，`returnPct/strengthRank/percentile` 显示 `--`，并展示 `validSectorCount/expectedSectorCount`；默认目标日为 PARTIAL 时按公共延迟体验进入 DELAYED 并回退最近 COMPLETE 日。

### 9.2 默认与保留选择

1. 默认：一级总榜、1 日、涨幅榜、20 日显示范围。
2. 第一次没有合法 sectorCode：首条可计算行，否则第一行。
3. tradeDate/period/direction/range 变化：当前行业仍在对象池就保留，即使当前值为 null。
4. scope/父级变化：当前行业仍在新池则保留；退出时才重选。
5. 一级父级变化时，二级父级必须重置为新一级的第一直属子级，再验证 sectorCode。
6. 下钻保留日期、周期、方向和显示范围。

### 9.3 方法按钮

M15 前三个已完成方法进入各自正式路由，只挂载目标方法；成员广度／量价分布执行下列零副作用。M15 完成后成员广度改为第四个正式路由，只剩量价分布执行：

```text
toast = 待建设
route unchanged
URL query unchanged
controller unchanged
network requests +0
chart instances +0
```

不得创建禁用按钮，因为产品已确认需要可点击提示；也不得切到 Draft Figma 工作区。

### 9.4 Members 局部四态

| 局部态 | 条件 | UI 与恢复 |
|---|---|---|
| IDLE | 非两个三级 scope，或整页尚未形成合法选中三级行业 | 不挂载成员面板、不发请求 |
| LOADING | 当前 members key 请求中 | 固定标题/表头和 370px skeleton；上榜单与右详情保留 |
| READY | 来源成员数大于 0；允许全部数值为空 | 完整行、覆盖计数和 `--`；可继续滚动和切换行业 |
| EMPTY | 来源成员数为 0 | 只在下半区显示“暂无成分股数据” |
| ERROR | 查询、合同或版本失败 | 只在下半区显示安全文案；普通失败仅重试 members，版本冲突重载全部事实 |

成员局部状态不是第六种页面状态。整页 READY/DELAYED 只由既有 ranking/history 决定；member Loading/Empty/Error 不得改变工具栏日期状态、清空行业榜单、隐藏右侧详情或自动切换行业。

### 9.5 双动量 Ready 内容状态

| 内容状态 | 判定 | 展示规则 |
|---|---|---|
| 普通 Ready | `calculableCount>=3` 且 `qualifiedCount>0` | 列表、摘要、散点完整展示 |
| Partial Data | `0<calculableCount<totalCount` | 保留全部行；缺值显示 `--`，散点只画可绘制对象，明确缺失数量 |
| No Qualified | `calculableCount>=3` 且 `qualifiedCount=0` | 符合条件列表局部空提示；允许切换全部行业；散点仍展示全量可绘制对象 |
| Small Group | `0<calculableCount<3` | 展示收益、排名、百分位和散点；不做资格填充，说明样本不足 |
| Missing Selected Coordinate | 选中 row 的 `coordinateStatus=UNAVAILABLE` | 列表和摘要保留，图内局部提示，无伪点 |

以上状态可以同时出现，例如 Partial Data + No Qualified；它们只由 Results 事实派生，不增加网络请求、页面主状态或异常码。Delayed 也可以携带这些内容状态，但页面必须优先明确实际盘后日期。

### 9.6 相对轮动 Ready 内容状态

| 内容状态 | 判定 | 展示规则 |
|---|---|---|
| 普通 Ready | 当前组两截面均不少于3且选中坐标可绘制 | 四象限、全量圆点、列表、摘要和轨迹完整展示 |
| Partial Data | `0<currentCalculableCount<totalCount` 或 `missingCoordinateCount>0` | 缺失行业保留在列表；无坐标不绘点，计数明确可见 |
| Small Group | `groupInterpretation=SAMPLE_INSUFFICIENT` | 有坐标行业使用中性点；四象限计数为0，不给象限解释 |
| Missing Selected Coordinate | 选中行业当前或5日前百分位缺失 | 其他圆点／列表保留；摘要显示可用事实，轨迹保留日期槽并断线，不造点 |
| Filtered | `quadrant!=all` 或 search 非空 | 只过滤右侧列表；图中全量当前快照、选中点和轨迹不变；零请求 |
| Hover | 圆点或行获得 pointer/focus | 只出现一个 Tooltip；不常驻其他行业名称，不发请求 |
| Enlarged | 打开放大图 | 复用相同坐标和 plotScale；不请求、不重算业务坐标 |

以上内容态可以与 DELAYED/Partial Data 同时存在；主状态仍只有 Loading/Ready/Delayed/Empty/Error。搜索无匹配不是整页 Empty，Missing Selected Coordinate 不是 Error，Small Group 不是“没有数据”。

### 9.7 成员广度主状态与局部缺失

| 状态 | 判定 | 展示 |
|---|---|---|
| Loading | 当前方法 Meta 尚未完成；或首次 Rankings/Details 均未完成 | 保留 Shell、方法栏和 toolbar 骨架 |
| Ready | 显式历史模式，或自动模式 defaultStatus=READY；当前排名指标至少一个行业可计算 | 完整榜单；详情允许单项 `--` |
| Delayed | 仅自动模式且 Meta defaultStatus=DELAYED | 使用 defaultTradeDate 内容并显示“当前展示某日盘后数据” |
| Empty | Meta 无 defaultTradeDate；或当前排名指标全池不可计算 | 不借用其他指标或旧日结果；可恢复选择日期／指标 |
| Error | Meta／Rankings 合同或查询失败 | 安全文案；按当前 request key 重试 |

Details 另有局部 Loading/Empty/Error，不能清空左榜。三项指标的 `AVAILABLE/PARTIAL/UNAVAILABLE` 是内容状态，不是第六种页面主状态：

1. 复权因子局部缺失时，成员数量和成交额继续显示，MA 显示可计算覆盖或 `--`。
2. 某行业未达到5只／80%只使该指标不合格；完整行业行、其他指标和成员行均保留。
3. 趋势某日不可计算保留日期槽并断线；不得删除日期形成伪连续。
4. 公共 `tradeDates` 的 PARTIAL/MISSING 只说明行业 `dc_daily` 覆盖；显式历史选择后仍让 Rankings／Details 按成员事实计算，不把公共状态直接映射成成员广度 Empty。
5. 同一实际日期：自动模式可以是 Delayed，显式历史模式必须是普通历史内容态。adapter/controller 以 URL 是否存在 `tradeDate` 判断，不比较日期值。

## 10. 异常码与安全

`wealth/docs/system/exception-code-registry.md` 已使用模块 `sectorAnalysis` 完成编码前登记；业务代码只能引用下列现有条目：

| code | severity | debugOnly | 恢复动作 |
|---|---|---:|---|
| `SA_SOURCE_DELAYED` | warn | true | 显示实际盘后日期 |
| `SA_SOURCE_EMPTY` | warn | true | 空态，不回退显式历史 |
| `SA_HIERARCHY_UNAVAILABLE` | error | true | 错误态，禁止猜层级 |
| `SA_SCOPE_INVALID` | warn | false | HTTP 400，修正 URL/选择 |
| `SA_SELECTION_INVALID` | warn | false | HTTP 400，保留当前输入 |
| `SA_FACT_VERSION_MISMATCH` | warn | false | 双动量／相对轮动 Results HTTP 409；只清空当前方法 Meta/Results 并重新加载该方法 Meta |
| `SA_MEMBER_FACT_MISMATCH` | warn | false | HTTP 409，清空四类短期事实并从 meta 重载 |
| `SA_MEMBER_SOURCE_EMPTY` | warn | true | 成员局部 EMPTY，不影响整页 |
| `SA_MEMBER_QUERY_FAILED` | error | true | 成员局部 ERROR，仅重试当前请求 |
| `SA_BREADTH_FACT_MISMATCH` | warn | false | HTTP 409，只清空成员广度短期事实并重载成员广度 Meta |
| `SA_BREADTH_SOURCE_EMPTY` | warn | true | Details 局部 EMPTY，榜单保留 |
| `SA_BREADTH_QUERY_FAILED` | error | true | 当前成员广度 endpoint ERROR，安全重试 |
| `SA_QUERY_FAILED` | error | true | 错误态，可重试 |

安全边界：

1. 复用 `require_quote_access`；不新增用户、角色或账号。当前公共依赖只定义未登录 401，本需求不增加权限模型，也不验证不存在的 403 路径。
2. market 首期只允许 CN_A；代码只允许 `BK[0-9]{4}.DC` 规范形态；`tradeDate` 必须是 SSE 开市日，开市日无来源事实进入 EMPTY。
3. 用户不可输入 SQL、字段名、表名、排序表达式或任意窗口。
4. debug 只在 local/dev/test 生效，details 只含计数、日期、scope 和最多 5 个 sectorCode。
5. 页面不出现 DC、数据源品牌、表名或技术堆栈。
6. Members 不返回 SQL、缺失原因内部枚举、停牌判断、来源表名或连接信息；用户只看到完整成员行、空值和覆盖计数。
7. 双动量只暴露第 7.9 节批准的有界 `missingReason`；相对轮动只暴露第 7.12 节的 current/comparison 缺失原因。两者都不返回 SQL、表名、连接、计算堆栈、原始异常或 debug 技术 payload。
8. `SA_FACT_VERSION_MISMATCH` 与成员版本冲突码不得互换；相对轮动409只重载相对轮动短期事实，不清空双动量或动量排名状态。
9. 三只成员广度专属异常码只能由成员广度链路使用；普通股票／因子缺值是结果 reasonCode，不得被包装成技术异常或泄露表名。

## 11. 测试设计

### 11.1 后端单元测试

既有测试继续保留；M14 再增加成员广度两项：

```text
tests/test_wealth_market_page_context_query.py
tests/test_wealth_sector_analysis_contract.py
tests/test_wealth_sector_momentum_calculator.py
tests/test_wealth_sector_momentum_query_service.py
tests/test_wealth_sector_member_return_calculator.py
tests/test_wealth_sector_member_detail_query_service.py
tests/test_wealth_sector_momentum_snapshot_query_service.py
tests/test_wealth_sector_dual_momentum_classifier.py
tests/test_wealth_sector_dual_momentum_query_service.py
tests/test_wealth_sector_relative_rotation_calculator.py
tests/test_wealth_sector_relative_rotation_query_service.py
tests/test_wealth_sector_member_breadth_calculator.py
tests/test_wealth_sector_member_breadth_query_service.py
tests/web/test_wealth_sector_analysis_api.py
tests/architecture/test_wealth_sector_analysis_guardrails.py
```

必须覆盖：

1. Pre-M2 公共日期查询在交易日 19:59／20:00、周末／节假日、显式开市／休市／缺行、空日历下保持原语义；每个合法调用严格 1 条 SQL，9 个直接消费者无回退。
2. 五个 scope 的精确 code 集合和父子闭包反例。
3. 1/5/10/20/30 公式与 N+1 日期；缺中间日也必须 null。
4. 日期覆盖全集：COMPLETE/PARTIAL/MISSING 三类、左连接缺口不丢日、当前层级外代码不计数、coverage 边界和稳定日期排序。
5. Decimal 取舍、非正收盘、pct_change 空、重复业务键。
6. GAINERS/LOSERS 全列表、null 末尾、sectorCode 稳定 tie-break。
7. `listPosition` 随方向变化；`strengthRank/percentile` 不变。
8. 竞赛排名、平均百分位、最强 100.0、最弱 0.0、n=1 和全部 null。
9. 二/三级全局与父级内摘要。
10. 20/30/60 历史、预热、缺点日期槽、分母变化和方向参数拒绝。
11. 默认 COMPLETE 为 READY、默认 PARTIAL/MISSING 回退为 DELAYED、显式 PARTIAL 为 READY、显式 MISSING 为 EMPTY、层级 ERROR、query ERROR。
12. Meta/rankings/history 未知参数、重复参数、非法日期/market/code。
13. 启用行情登录门禁后的未登录 401、debug 环境门禁和敏感信息反例；不构造不存在的 403 权限场景。
14. Meta/Rankings/History SQL 数分别不超过 3/5/5，且不随行业数和历史点线性增长。
15. 公共层级 Query 移动后 `/sector-overview` 响应与既有测试零回退。
16. Members 只接受必填 market/tradeDate/hierarchyVersion/sectorCode/period/direction；未知、重复、一级/二级、非开市日和未批准周期均拒绝。
17. hierarchyVersion 匹配成功；不匹配时 409 `SA_MEMBER_FACT_MISMATCH`，成员和行情 SQL 均为 0。
18. 1 日 `pct_chg(t)` 和 5/10/20/30 日每日连乘；缺首日、中间日、末日、空值、非有限值和历史不足均返回 null，不补零。
19. 目标 close 与 returnPct 独立可空；有 return/无 close、有 close/无 return、两者皆无都保留来源行。
20. GAINERS/LOSERS、null 末尾、同值 stockCode 升序；B 股、停牌和其他缺行情样本不被过滤。
21. READY 允许 calculableCount=0；EMPTY 只允许来源成员为 0；三个 count、代码唯一和 rows 长度的 DTO 反例全部拒绝。
22. Members 正常路径最多 4 SQL，且 1/139 个成员、1/30 日窗口 SQL 数相同；禁止逐股票查询。
23. 现有三个 endpoint、行业 `SectorMomentumCalculator` 和首页 `/sector-overview` Top5 成员响应零回退。
24. 快照 rows 与比较池一一对应、缺值不丢行、事实代码一致；既有 Rankings 在抽取前后 response dump、状态和 SQL 数完全相同。
25. 双动量 5/10/20/30、70/80/90、阈值相等、return=0、四种完整组合、缺值、小组 1/2/3 和 displayStatus 全矩阵。
26. total/calculable/qualified/insufficient/plottable 五个计数、代码唯一、规范排序和 strict DTO 反例。
27. 五个 scope、父子闭包、显式／默认日期、Partial/Delayed/Empty/Error、No Qualified、Missing Coordinate 和 Small Group。
28. hierarchyVersion 匹配；过期返回 409 `SA_FACT_VERSION_MISMATCH` 且行情 SQL 为 0；重用成员专用 code 的反例失败。
29. 双动量 Meta/Results 分别不超过 3/5 SQL，且只使用 `TradeCalendar/WealthSectorHierarchy/DcDaily`；成员、股票、资金、Heat、QTF、DG/Lake、迁移、配置和预测词门禁保持 0。
30. 既有四个 endpoint、现有 Calculator、首页板块速览及完整后端冻结套件零回退。
31. 相对轮动合同只接受五类 scope、`period=5/10/20/30`、`trailLength=20/30/60`、`improvementLookbackDays=5`、`minimumGroupSize=3`；未知值、未知字段、重复 query、错误父子闭包和越界行业代码全部拒绝。
32. `X=P(d,N)`、`Y=P(d,N)-P(d-5,N)` 使用既有区间收益和平均并列百分位；覆盖 `X/Y` 为零、四象限边界、同值、负值、全 null 和稳定 `sectorCode` tie-break。
33. 每个目标日期独立排名；修改 `d+1` 以后事实不改变 `d` 的收益、百分位、坐标、状态或轨迹槽，跨 scope、跨父级和跨层级事实不能进入比较池。
34. 当前和比较截面分别覆盖可计算行业数为 2/3 的边界：小组不足仍返回中性客观坐标但象限计数为零；组规模达到3才允许象限解释。
35. 当前缺失、5日前缺失、轨迹中间缺失、覆盖开始日晚于窗口、完整窗口不足、非正或非有限收盘均保留明确 null 槽；不得补零、前向填充、压缩交易日或跨缺口连线。
35A. 日期切片中的收益事实与排名事实必须数量、代码、顺序和收益值一致；重复代码、错序、错值、可计算事实带缺失原因、不可计算事实缺失原因丢失均立即失败，不允许计算器猜测原因。
36. 未显式选择行业时选 canonical 第一只可绘制行业，否则第一行；显式选择必须属于当前比较池。READY/DELAYED 的 `selectedTrail` 必须存在、代码一致、日期升序唯一、末槽等于 `observedTradeDate`。
37. `total/currentCalculable/plottable/missingCoordinate/quadrantCounts`、唯一代码、canonical 排序、`groupInterpretation`、状态组合和 strict DTO 全部有篡改反例。
38. Results 只允许最大95个开市日，96拒绝；一次请求严格为5条 SQL，行情只读取一次，SQL 数不随行业数、目标日期数或轨迹长度增长。
39. 层级版本冲突在任何行情 SQL 前返回409 `SA_FACT_VERSION_MISMATCH`；401、400、409、500 均使用安全 DTO，Prod debug 不泄露 SQL、表名、连接或堆栈。
40. 相对轮动只读取前三张 Prod 表；成员、股票、资金、Heat、宽基、申万、QTF、DG/Lake、写事务、迁移、配置、缓存、结果表和第三方依赖保持0。
41. 相对轮动加入后，既有动量排名三只、成员一只、双动量两只共六只 endpoint，以及 Calculator、首页板块速览和冻结后端套件必须零变化。

### 11.2 前端测试

新增/修改：

```text
wealth/src/app/routes/routerState.test.ts
wealth/src/shared/ui/shortcut-bar/ShortcutBar.test.tsx
wealth/src/pages/market-overview/MarketOverviewPage.test.tsx
wealth/src/pages/wealth-exploration/WealthExplorationLandingPage.test.tsx
wealth/src/pages/wealth-exploration/TurnoverInsightPage.test.tsx
wealth/src/pages/wealth-exploration/SectorAnalysisPage.test.tsx
wealth/src/features/wealth-exploration/sector-analysis/**/**.test.ts(x)
tests/test_wealth_turnover_insight_static_gates.py
```

关键断言：

1. landing 只请求 context/ticker，零 turnover/sector 请求。
2. turnover 子页继续展示既有真实模块；旧业务 adapter/controller 测试不变。
3. sector 根地址 replace 到 momentum；刷新、前进、后退恢复 query。
4. 市场总览 Shortcut 提取前后 class、顺序、选中、hover/focus 和视觉不漂移。
5. 入口两卡顺序、active、breadcrumb 和直达切换正确。
6. 默认控件和首条可计算选择正确。
7. 日期选择器完整显示覆盖区间内全部 SSE 开市日及三类覆盖标记；PARTIAL/MISSING 不被禁用或隐藏。
8. 五 scope、父级级联、行选择、独立下钻和三级无下钻。
9. 全列表固定表头和内部滚动；null 行显示 `--`。
10. direction 只导致 rankings 请求，history 请求数不增加。
11. 两图同时存在，共享 hover index；rank 1 在顶部，null 断线。
12. 选择保留规则覆盖日期、周期、方向、range、scope 和父级。
13. 双动量按钮进入正式 route 并只挂载双动量 controller；另外三个待建设按钮只 toast，零路由/请求/图表副作用。
14. 五态真实 API 驱动；显式 PARTIAL 使用 READY 骨架并展示缺失数，显式 MISSING 进入 EMPTY；重试只重发失败链路。
15. 快速切换时旧响应不能覆盖当前 URL 状态。
16. 只有 level3/level2-children 请求 members；其他三个 scope 请求数为 0，且保持既有 866px 单榜单。
17. members key 精确包含 observedTradeDate/hierarchyVersion/sectorCode/period/direction；range 变化请求数不增加，direction 变化只刷新 ranking/member，不刷新 history。
18. 成员局部 Loading/Ready/Empty/Error 只替换下半区；上榜单、右详情和整页 READY/DELAYED 保留。
19. HTTP 409 层级版本冲突重载 meta；普通成员失败的重试只重发 members。
20. 表头和行共用相同 Grid；1512px 下不横向溢出，长名称省略有 Tooltip，代码和数字不换行。
21. `390+12+464`、成员 54/40/370/48 高度、上下独立滚动和请求 key 变化回顶均有 DOM/CSS 断言。
22. 双动量 URL 十个 key、默认值、五 scope、父级保留／省略、日期、周期、阈值、resultView、sectorCode 和历史导航恢复。
23. Meta→Results 时序、未选方法零请求、旧响应丢弃、5 秒超时、409 单次重载和重复 409 停止。
24. resultView、行业选择、列表排序均零请求；QUALIFIED/ALL 的选择保留和规范化写 URL 正确。
25. strict adapter 拒绝未知字段、公式版本、固定数组乱序、请求事实错代、计数、规范排序和状态组合错误；前端源码无资格公式。
26. 列表／散点双向选择、选中与资格视觉分离、10px Hover 命中、缺坐标无伪点、Small Group 中性点、放大 dialog 零请求。
27. 15 个双动量正式状态和 1600/1512/1460/1366 四档宽度；长名称、完整长列表和密集散点无新增换行、裁剪、重叠或模块级横向溢出。
28. 相对轮动第三条精确 route、方法栏 active 和按需挂载正确；进入 M11 前仍是“待建设”零请求，进入 M11 后只挂载相对轮动 controller，其他两个 controller 不运行。
29. 相对轮动 URL 十一个 key、默认值、五 scope、父级保留／省略、日期、周期、轨迹长度、象限筛选、搜索、sectorCode 和浏览器前进／后退完整恢复；非法组合失败闭合。
30. Meta→Results 时序、5秒超时、401、409单次 Meta 重载、重复409停止、请求 key 与旧响应丢弃；比较池／日期／周期／轨迹／行业切换原子替换当前快照和选中轨迹。
31. strict adapter 拒绝未知字段、公式版本、固定数组乱序、请求事实错代、重复行业、计数、canonical 顺序、错误象限、伪坐标、丢失日期槽和状态组合错误；前端源码无收益、百分位、改善值或象限公式。
32. 搜索、象限筛选、Hover 和放大均为零业务请求；筛选只改变右侧可见行，不删除主图中的全量当前圆点，不改变服务端计数或选中对象。
33. 行与圆点双向选择；只有选中行业显示常驻名称和轨迹，其他行业只在 Tooltip 显示；缺坐标不生成 `(0,0)`，null 轨迹槽断线，小组不足使用中性样式。
34. 普通图与放大图共享同一 `plotScale`；横轴固定 `0..100`、50分界，纵轴围绕0对称并使用 `1/2/5×10^n` nice ceiling 与5个刻度。
35. 逐一覆盖相对轮动14个正式状态和 `1600/1512/1460/1366` 四档宽度；最长三级行业名、337个密集圆点、完整滚动列表、Tooltip避让、键盘焦点、ESC／遮罩关闭均无新增换行、裁剪、重叠或模块级横向溢出。

### 11.3 删除旧门禁的安全步骤

1. 先新增 landing/turnover/sector 三页测试，证明新页面职责。
2. 再修改 `WealthExplorationPage.test.tsx`：拆成三页测试后删除旧文件，不简单删除覆盖。
3. 修改 `test_wealth_turnover_insight_static_gates.py`：
   - 删除 `sector-radar` slot 必须存在的断言；
   - 改为 Turnover 只被 `TurnoverInsightPage` 消费；
   - 新增 landing 不 import Turnover、SectorAnalysis 的反例；
   - 保留 turnover feature 无跨 feature 依赖、无预测和后端数学门禁。
4. 新门禁全部通过后才删除旧 `WealthExplorationPage.tsx` 和零高度 CSS。

### 11.4 Figma/浏览器验收

1. 1600px 对照 12 个正式节点。
2. 1512px 验证两列等宽收缩且无横向裁剪；1460px 验证内容最小宽度无内部重叠；1366px 仅允许全局 `min-width:1460px` 产生页面级横向滚动，不允许模块自身再固定为 1564px，也不允许 CSS scale、文字裁剪或列间重叠。
3. Ready 默认/跌幅/二级总榜/三级总榜/一级内二级/二级内三级/Hover/交易日选择器分别验收。
4. 长列表验证真实固定表头和内部滚动，不以短 fixture 替代。
5. Tooltip、键盘、focus-visible、下钻事件隔离和双图 hover 联动人工验收。
6. 普通 UI 相对 Figma 允许误差不超过 2px；图表坐标轴、plot padding 和零线不得无依据移动。
7. `1051:1251/987:776` 单独验收：左栏总高 866px、上榜单 390px、间距 12px、下成员 464px；四列表头/行在 1600/1512/1460 三档严格对齐且无横向溢出。
8. 双动量逐一对照第 3.1 节 15 个正式节点和组件集 `1132:9777`；旧草稿 `967:72` 不得出现在截图依据或代码注释中。
9. 双动量 1600px 工作区命中 `1564×1006` 和 `776+12+776`；1512/1460 连续等宽收缩，1366 只出现页面级横向滚动。
10. No Qualified、Small Group、Missing Selected Coordinate 和 Partial Data 必须在 Ready 骨架内验收；不能用 Empty/Error 画板替代。
11. 相对轮动逐一对照第3.1节14个正式节点；默认 Ready 根节点 `1150:5870` 必须命中 `1600×1292.390625`，工作区 `1150:6227` 为 `1564×1006`。
12. 相对轮动工具栏 `1564×128`、主体 `1564×866`、图表列 `1088×866`、列表列 `464×866`、列间距12px；1512/1460连续收缩，1366只允许公共页面级滚动。
13. 主图 `1088×733` 内绘图区固定 `left=68/right=36/top=44/bottom=56`；普通图和放大图使用同一坐标范围，Small Group、Missing Selected Coordinate、Filtered、Delayed、Loading、Empty、Error 均按正式画板单独验收。
14. 相对轮动旧草稿 `967:158`、Archive 区域以及传统 RRG 术语／宽基字段不得进入实现、fixture、截图或验收说明。

### 11.5 成员广度 M14～M16 专项矩阵

后端正反例：

1. Meta 恰好复用公共3条 SQL，查询计划和源码均不得出现 `DcMember/EquityDailyBar/EquityAdjFactor`；410日×496行业历史完整性扫描必须有静态反例。
2. 自动模式 Meta 在预期 COMPLETE／PARTIAL／MISSING 下分别给出 READY／最近公共 COMPLETE 的 DELAYED／无默认日的 EMPTY；同一默认日期作为显式 URL 日期时不携带自动延迟语义。
3. 五 scope 和父级闭包；hierarchyVersion 过期在公共日期、成员／行情／因子 SQL 前409；合法版本后必须调用既有公共页面日期，目标日期早于当前层级覆盖起点、晚于公共页面日期或不是 SSE 开市日均在行情 SQL 前拒绝。
4. 三项独立分母：缺复权因子只改变 MA；缺 amount 只改变成交额；缺 pct_chg 同时影响数量／成交额但不删除成员或复权窗口事实。
5. 5/10/15/20/30/60 均线、`close×adj_factor`、等于均线中性、缺首／中／末日、因子非正、历史不足和未来扰动。
6. `5+80%` 两个边界分别等于／低于；小行业保留；标准竞争排名和完整列表。
7. Rankings 的 MEMBER_COUNT/TURNOVER 路径不得调用 MA 计算器或投影因子；MA_POSITION 才允许读取／计算因子。
8. Details 三项同时返回；趋势20/30/60升序槽、null断线；最大119日允许、120拒绝。
9. 成员表完整无分页；方向排序、成交额贡献统一分母、MA距离、null末尾、同值稳定。
10. strict API 的 unknown/duplicate、非法日期／枚举／code、401、409、局部 Empty/Error、安全异常和敏感信息反例。
11. SQL 固定 Meta/Rankings/Details `3/4/4`；计算接口四段固定为层级、公共页面日期、窗口覆盖成员合并查询、行情因子；1个／496个行业、1个／625个成员、5／60／119日不出现 N+1，源码不得保留分离的窗口／成员查询主链。
12. 性能分别验收非MA60一秒、MA60两秒，不能用平均值掩盖 P95；既有八只 endpoint 响应、SQL和来源白名单零回退。

前端正反例：

1. 第四条精确 route、方法栏、前进／后退；未进入成员广度时三请求和图表实例为0。
2. URL 无 tradeDate 保持自动模式且不把 defaultTradeDate 写回；用户选历史才写入，清除后恢复自动模式。
3. 同一日期在自动回退时显示 Delayed，显式历史时不显示自动回退；页面不得根据日期相等自行判断。
4. Meta→实际日期后，有合法 sectorCode 时 Rankings/Details 并发且允许局部先完成；无合法 sectorCode 时必须由 Rankings 解析 `defaultSelectedSectorCode ?? rows[0]` 后再发 Details。两条路径均覆盖5秒超时、Abort、request key、409一次重载和旧响应丢弃，并证明没有猜测行业或无效 Details 预请求。
5. 五 scope、父级级联、两方向、三指标、六均线、三历史范围、选择保持和默认第一资格行业。
6. metric 变化只请求 Rankings；historyRange/sectorCode 只请求 Details；maPeriod/scope/父级/日期刷新二者。
7. 复权因子缺失只使 MA 内容 `--`；成员／成交额卡、榜单和趋势仍显示真实 DTO。
8. 完整行业榜与成员表固定表头、独立滚动；趋势 null 断线；前端不计算公式或补值。
9. 13张正式 Figma 状态逐一对照；1600基线 `548+12+1004`，1512/1460连续收缩，1366仅公共页面级滚动。
10. 长行业／股票名、最大列表、MA60慢请求、Details局部失败、键盘、focus-visible、Tooltip和重试无裁剪／串代／整页误清空。
11. `MemberBreadthTrendChart` 初始无十字线；plot 内主按钮单击按真实容器映射并吸附最近交易日，不能命中日期间的任意像素或插值值。
12. `ACTIVE` 的日期纵线、百分比横线、x/y浮标、三项有效交点和Tooltip必须来自同一状态；左右移动切换日期，上下移动只改变横线。
13. null 系列不画交点且Tooltip显示 `--`；全null日期仍允许查看日期，但不得生成0值或伪点。
14. Tooltip 在62%边界切换左右侧并对四边clamp；pointerleave保留最后读数，plot外空白／轴区域再次单击和Escape都回到 `IDLE`。
15. `tradeDate/sectorCode/direction/maPeriod/historyRange` 或Details状态变化清除；单改排名metric不清除。以上交互不改变URL、controller或任何成员广度请求数。
16. 1600/1512/1460/1366四档都使用 `getBoundingClientRect()` 映射到同一viewBox；交互层不得改变图表卡高度、plot padding、null断线、成员表或其他三个方法DOM。

## 12. 性能与验收门禁

| 项目 | 门禁 |
|---|---:|
| Meta P95 | <= 300ms |
| Rankings P95 | <= 500ms |
| History P95 | <= 700ms |
| Members P95 | <= 500ms |
| 双动量 Meta P95 | <= 500ms |
| 双动量 Results P95 | <= 500ms |
| 相对轮动 Meta P95 | <= 500ms |
| 相对轮动 Results P95 | <= 1,000ms |
| 相对轮动 Results 最大开市日窗口 | 95；96 必须拒绝 |
| 成员广度 Meta P95 | <= 1,000ms；零成员／行情／因子历史扫描 |
| 成员广度 Rankings/Details 非MA60 P95 | <= 1,000ms |
| 成员广度 Rankings/Details MA60 P95 | <= 2,000ms |
| 成员广度最大开市日窗口 | 119；120 必须拒绝 |
| 当前工作区可用 | <= 1.5s，不含异常网络 |
| 单 endpoint payload | 既有/Rankings/Meta <=256KB；成员广度 Details <=512KB |
| 同一 query key 有效请求 | 1 |
| 未选工作区请求/图表 | 0 |

M2 Prod 只读验收已经证明现有索引满足既有三接口查询：最重 History 查询的数据库服务端执行约 `116.8ms`，同规模完整 service DTO 与 JSON 组装 P95 为 `99.721ms`。M3A 聚合审计证明最大成员数 139，不需要分页或虚拟列表；实现后以 `2026-08-27` 最大真实组日 `BK1444.DC` 的 138 行、30 日窗口连续执行 20 次本地同拓扑 GET，P95 为 `334.279ms`，响应 `12,126 bytes`，满足 Members `500ms/256KB` 门禁。M6 使用当前完整 496 节点层级 Meta 与最大 337 行比较池 Results，各执行 20 次本地同拓扑 GET：双动量 Meta 为 3 SQL、P95 `14.646ms`、`150,638 bytes`，Results 为 5 SQL、P95 `158.317ms`、`157,518 bytes`，均满足 `500ms/256KB`；没有新增缓存、索引、结果表或迁移。

M9 使用现有 Web 只读连接对当前发布337个三级行业和最近95个 SSE 开市日做了有界审计：行情事实实际返回31,614行，理论上限32,015行；不导出来源行、不保存快照。跨网络完整链路20次 P95 为 `2343.531ms`，只用于识别网络环境差异；数据库端5条 SQL 的执行时间合计 `91.868ms`，其中行情事实查询 `45.847ms`，纯计算、DTO 与 JSON 50次 P95 为 `107.363ms`。按同部署拓扑核心链路估算 P95 为 `199.231ms`，当时据此关闭 M10 的可行性门禁。M12/M12R 已用真实部署 HTTP 覆盖最终验收效力；M12R 两轮 P95 为 `848.025/847.416ms`，均通过用户最终确认的 `1,000ms` 门禁。M9 分段结果不得替代部署验收，也不能作为增加缓存、索引、结果表或删减返回事实的理由。

M13 的 Prod 只读 EXPLAIN 证明：成员广度 Meta 若做全历史完整性聚合约8.95秒，逐键探测约3.11秒，已从运行合同删除；目标日496行业成员检查约6ms，可随实际计算完成。三级全榜 MA60 约331,327股票日原始行，聚合投影数据库阶段约1.54秒，因此 MA60 单独使用2秒门禁；MA20聚合约557ms，其他请求继续保持1秒。最大625成员、119日 Details 的行情+因子读取约366ms。以上只关闭 M14 编码可行性，不冒充部署 HTTP P95；M16 必须分别复测 Meta、非MA60和MA60。

前端不引入新第三方依赖。图表用 SVG/CSS，列表先使用原生滚动。首次实现禁止为了预期性能增加虚拟列表、服务端缓存或结果表。

### 12.1 M12 真实部署性能审计

审计对象为远程部署提交 `6b07ae96c9dab353f801c80c9d77006e12ecc404`。服务健康和真实事实合同正常；最大 Results 使用 `LEVEL_3 + period=30 + trailLength=60`，返回337个行业、60个选中轨迹日期槽、5条 SQL 和 `158,749 bytes`。Meta 为3条 SQL、`207,265 bytes`、HTTP P95 `207.985ms`，通过预算。

Results 连续两轮、每轮20次部署 localhost 认证 HTTP 的稳态 P95 分别为 `1250.883ms` 和 `1275.006ms`。两轮都超过当时有效的 `500ms` 门禁，因此触发 M12R；该结论是 M12R 前的历史审计事实，不代表当前最终门禁或当前状态。

CodeGraph 和当前代码逐项审计覆盖：

| 入口／实现 | 当前真实行为 | 影响面结论 |
|---|---|---|
| `src/biz/api/wealth/market/sector_analysis.py` | route 只校验参数并同步调用 `SectorRelativeRotationQueryService.build_results()` | 公共 HTTP DTO 无需修改 |
| `sector_relative_rotation_query_service.py` | 读取最多95日、构造最多65个完整排名切片和60个完整坐标切片，最后只返回当前全榜与选中轨迹 | M12R 的主要编排纠偏点 |
| `sector_momentum_query.py::load_facts()` | 一次查询并把31,614行 `ts_code/trade_date/close/pct_change` 转成 `SectorDailyFact` | 最大单阶段；当前仍保持一次读取和共享事实语义 |
| `sector_momentum_calculator.py::calculate_for_dates()` | 为最多65个目标日计算全部337行业收益 | 相对轮动、动量排名、双动量共享；不得改变公式 |
| `sector_momentum_calculator.py::rank_strength()` | 每个日期构造整个比较池的 `SectorRankFact` | 共享消费者影响面；只能共用公式后增加稀疏投影 |
| `sector_relative_rotation_calculator.py::calculate_grid()` | 60个展示日逐日构造337个坐标事实 | 生产路径存在明确过度物化 |
| `tests/test_wealth_sector_relative_rotation_query_service.py` | 最大窗口性能用预制 facts 和 stub query 测纯计算／DTO／JSON | 保留内核门禁，但不能替代部署 HTTP 门禁 |
| 前端 `useSectorRelativeRotationController`／strict adapter | 一次消费整个 Results，5秒超时，不重算业务事实 | M12R 不改前端和响应合同 |

CodeGraph 影响面确认：`SectorMomentumCalculator.calculate_for_dates()` 和 `rank_strength()` 同时被动量排名、双动量、相对轮动及各自测试消费；`SectorRelativeRotationCalculator.calculate_grid()` 只被相对轮动及其测试消费；Results 的公开消费者为相对轮动 API 和前端 strict adapter。因此共享排名实现的任何内部重构都必须回归三个方法，公开 DTO 变化则会直接影响前端，本轮禁止 DTO 变化。

真实方法级剖析共5次，范围如下：

| 阶段 | 观测范围 |
|---|---:|
| 公共日期上下文 | `4～6ms` |
| 快照准备 | `73～113ms` |
| 开市日读取 | `1.5～2ms` |
| 31,614行事实读取与物化 | `305～456ms` |
| 事实索引 | `10～20ms` |
| 65日收益事实计算 | `76～121ms` |
| 65次全量横截面排名 | `95～134ms` |
| 60×337完整坐标网格 | `82～196ms` |
| DTO JSON | `1.2～2.1ms` |

一次 `cProfile` 最大窗口记录737,398次函数调用：`load_facts` 累计约 `0.357s`、`calculate_for_dates` 约 `0.188s`、65次 `rank_strength` 约 `0.161s`、`calculate_grid` 约 `0.155s`；其中20,220个点对象的构造约 `0.126s`。这些数据确认 JSON 不是瓶颈，也不能仅凭 SQL server event 时间把结果读取和 SQLAlchemy 行物化成本忽略掉。

当前数据库模型已具备 `(ts_code, trade_date, category)` 主键，以及 `trade_date`、`(trade_date, category)` 索引。现有证据不支持把失败归因于缺索引。三字段／四字段读取实验也没有得到稳定差异，不能把删除 `pct_change` 写成解决方案。

### 12.2 M12R 文件级编码方案

M12R 只删除无输出价值的中间事实物化，不改变任何公开业务事实。允许改动文件固定如下：

| 文件 | 允许改动 | 禁止项 |
|---|---|---|
| `src/biz/services/wealth/market/sector_analysis/sector_momentum_calculator.py` | 把现有并列排名查找逻辑提取为单一内部 helper；既有 `rank_strength()` 和新增“只投影一个行业排名”的方法共用同一个 helper | 不改收益、竞赛排名、平均并列百分位、量化精度或已有返回顺序；不复制第二套公式 |
| `src/biz/services/wealth/market/sector_analysis/sector_relative_rotation_contract.py` | 新增只供内部轨迹计算使用的不可变“单行业日期排名切片”，严格校验日期、收益、排名、缺失原因和可计算数量 | 不进入 schema、API 或前端 DTO |
| `src/biz/services/wealth/market/sector_analysis/sector_relative_rotation_calculator.py` | 新增“当前日全池坐标”和“选中行业历史轨迹”两个有界入口，共用现有单点公式；生产路径切换后安全删除全量 `calculate_grid()` | 不改象限、5日差值、缺失、小组或 canonical sort 语义；不保留生产兼容入口 |
| `src/biz/queries/wealth/market/sector_analysis/sector_relative_rotation_query_service.py` | 当前日和其5日前只构造两个完整排名切片；先生成当前337行并决定默认／显式选择，再为其余日期只投影选中行业排名和轨迹 | 不改5 SQL、一次 facts 读取、响应选择规则、状态、计数、DTO 或 debug |
| 三个 calculator/query service 测试文件 | 增加旧／新输出等价、调用数量、缺失、小组、并列、选择和未来前沿反例；迁移已有 `calculate_grid()` 测试后删除旧入口测试 | 不降低现有断言，不用仅计时断言代替事实等价 |

安全删除顺序：

1. 先为现有最大窗口和边界样本保存稳定 response dump／事实断言，作为公开结果基线；不保存生产来源行。
2. 提取共享排名 helper，让原 `rank_strength()` 原样走新 helper；先跑动量排名、双动量和相对轮动回归，证明这一步零行为变化。
3. 增加单行业排名切片、当前快照和选中轨迹入口；用当前 `calculate_grid()` 作为临时测试 oracle，对五类 scope、四周期、三轨迹长度和边界样本逐项比较。
4. QueryService 切换为稀疏编排：最大窗口全量 `rank_strength()` 调用严格从65次降为2次；其余最多63个日期只生成选中行业排名；坐标产出从20,220个收敛为当前337行与60个选中轨迹槽。
5. 全部等价门禁通过后，从生产代码删除 `calculate_grid()`，将其既有测试迁移到两个新入口；不得保留兼容 alias、废弃分支或无法到达的旧网格路径。
6. 最后运行全量共享消费者、API、架构和前端 contract 回归；任一公开 dump、SQL 数、计数、状态或选择变化即回退 M12R，不进入部署。

当前 `calculate_for_dates()` 仍会计算历史横截面收益，因为选中行业在每个历史日期的百分位必须与当日全部同组行业比较。M12R 不得为了少建对象而改写该共享收益公式；事实读取／物化的进一步缩减没有完成独立方案与等价证明，明确不属于本轮。

### 12.3 M12R 正反例、性能与停止门禁

自动化必须同时证明：

1. 五类 scope、`5/10/20/30`、`20/30/60`、默认和显式 sectorCode 的旧／新 Results DTO 完全相等。
2. 并列平均百分位、只有一个可计算对象、2个／3个小组、当前缺失、比较日缺失、轨迹中间断点和不可计算行业完全相等。
3. 修改未来事实不影响历史结果；不同父级、scope 或层级代码不进入当前比较池。
4. 最大窗口全量排名严格2次，单行业排名最多63次，坐标事实不超过337个当前行加60个轨迹槽；`load_facts()` 仍严格1次，Results 仍最多5 SQL。
5. 动量排名、成员、双动量、相对轮动 API response dump 与前端 strict adapter 全部通过；公开 schema、URL、异常和 Figma 零变化。
6. 当前纯计算性能测试改名或增加注释，明确其范围是“预制 facts 后的内核预算”，不得再把它描述为部署 HTTP 证明。

代码门禁通过后才允许部署。部署验收固定为同一 Git commit、同一最大请求、localhost 认证 HTTP，Meta／Results 各预热一次后执行两轮、每轮20次。两轮 Results P95 都必须 `<=1,000ms`，并同时满足5 SQL、337行、60槽、256KB和事实逐项对账。

如果任一轮仍超过1,000ms，M12R 结论为不通过并立即停止。不得在同一轮继续修改 SQL、增加缓存／索引／结果表／分页／截断／迁移；只能先做一个新的只读事实投影可行性审计，明确需要哪些行、如何保持缺失窗口和共享消费者语义、真实 SQL/物化耗时及旧新事实对账，再由用户批准是否进入下一轮。当前两轮均低于1,000ms，该失败分支未触发。

## 13. 开发里程碑

### M0：合同和治理收口

状态：`PASS (2026-08-27)`。

1. 用户确认本 LLD 和 Figma 交付节点。
2. 核对统一注册表中已登记的 `SA_*` 与本文 COMPLETE/PARTIAL/MISSING、DELAYED 和 EMPTY 语义一致；不得重复登记同义码。
3. 新增静态架构门禁，冻结三张来源表、无迁移、无 QTF/DG/Lake/预测。
4. 停止点：文档与门禁通过，不改页面和业务。
5. 验收证据：`tests/architecture/test_wealth_sector_analysis_guardrails.py` 的 6 项门禁通过；M0 没有新增页面、API、查询、计算、模型或迁移。

### M1：页面结构与共享 Shortcut

状态：`PASS (2026-08-27)`。

1. 提取共享 Shortcut，完成市场总览零漂移测试。
2. 建立 Shell、landing、turnover、sector 三页和精确路由。
3. 移动既有成交额入口，不改其 API/feature 合同。
4. 删除旧页面和 sector-radar 占位及历史门禁。
5. 停止点：三个地址可独立刷新；sector 只有稳定壳和方法栏，无板块 API。
6. 验收证据：46 项 M1 前端定向测试、16 项静态/架构门禁、TypeScript 检查和生产构建通过；未新增 API、查询、模型、迁移、依赖或板块请求。

### Pre-M2：公共业务日期查询单语句化

状态：`PASS (2026-08-27)`。

1. 保持 `MarketPageContextQuery` 公开方法、返回合同、20:00规则和消费者调用方式不变。
2. 将显式最坏 2 条、默认最坏 4 条 SQL 统一收敛为 1 条只读 SQL。
3. 补齐固定北京时间、交易／休市、显式缺行、空日历、SQL event counter 和 9 个消费者回归。
4. 验收证据：Pre-M2 与全部直接消费者、首页板块速览及架构定向回归共 106 项通过；所有合法调用恰好 1 条 SQL，不支持市场为 0 条，公共 context HTTP 合同和消费者结果零回退。
5. 停止点已满足；Meta 后续正常路径 SQL 预算固定为最多 3 条。

### M2：后端动量事实

状态：`PASS (2026-08-27)`。

1. 移动公共 hierarchy Query，修改全部消费者并回归首页板块速览。
2. 实现 strict schema、纯计算内核、meta/rankings/history。
3. 完成状态、异常、鉴权、真实路由和 SQL 数测试。
4. 执行只读 EXPLAIN 和性能预算。
5. 停止点：真实 API 可独立验收，不进入前端。
6. 自动化证据：五类 scope、五个周期、N+1 完整窗口、全列表、方向无关强度排名、并列百分位、历史时间前沿、覆盖缺口、默认／显式日期状态、严格 query、未登录 401 和安全异常映射均有正反例；定向与回归共 156 项通过。
7. SQL 与 Prod 证据：Meta/Rankings/History 分别不超过 3/5/5 条 SQL；当前层级 496 个节点、三级 337 个，行情覆盖 `2024-01-02..2026-08-27`、643 个交易日；Meta P95 `260.439ms`、Rankings P95 `374.495ms`，payload 分别为 `206533/99715` bytes。History 服务端查询与应用计算分段预算通过，部署态端到端 P95 留给 M4。

### M3：前端动量工作区

状态：`PASS (2026-08-28)`。

1. 实现 URL 状态、API/adapter/controller。
2. 实现控件、全列表、详情摘要和两张联动 SVG 图。
3. 实现五态，并回归 M1 已完成的四个待建设 toast 保持零副作用。
4. 停止点：全部使用真实 API，仓库无 Mock 兜底。
5. 1600px 命中 Figma 固定尺寸；1512px 和 1460px 按第 3.4 节连续等宽收缩；当前页面已通过用户验收。

### M3A：三级行业成分股明细

状态：`PASS (2026-08-28)`。

1. 先同步中央异常码和静态架构护栏合同，再实现 members DTO、Query、独立 Calculator 和 QueryService；既有三个 endpoint、行业 Calculator 和首页 Top5 Query 不得修改语义。
2. 后端先完成正反例、4 SQL 门禁和真实 API 测试，再接前端；不允许先在页面 mock 成员数据。
3. 前端增加独立 member 状态和请求链，只在两个三级 scope 挂载 `390+12+464` 左栏；右侧摘要和图表保持不变。
4. 依次验收 hierarchyVersion 冲突、来源全集、逐日连乘、空值保留、局部四态、快速切换、响应式四列和首页零回退。
5. 自动化证据：139 成员×30 日仍为 4 条 SQL；过期成员响应、普通局部重试、409 全量重载、范围键隔离、完整列表和空值保留均有正反例。
6. 浏览器证据：1600/1512/1460 三档页面和模块横向溢出均为 0，左右栏连续等宽收缩，`390+12+464` 与 370px 成员视口不变，四列表头与内容列偏差为 0。
7. 当前页面已于 2026-08-28 通过用户验收；按用户指令进入 M4 自动化联调门禁。

### M4：联调和交付

状态：`AUTOMATED GATES PASS / FIGMA FINAL ACCEPTANCE UNDECIDED (2026-08-28)`。

1. 后端、前端、架构、typecheck、build 和 docs 检查已完成：冻结后端套件 `179 passed`，前端全量 `379 passed`，TypeScript 与生产构建通过；Alembic 单一 head 为 `20260828_000154`，文档完整性与 `git diff --check` 通过。
2. 12 节点 Figma 像素/交互验收及 1366 宽验证先不执行；先向用户说明工作内容、复杂度和消耗，再由用户另行决定。
3. 按用户 2026-08-28 的决定，不做周边页面专项人工回归；第 1 项现有自动化套件仍必须覆盖其既有回归用例。
4. 按用户 2026-08-28 的决定，不做部署后生产只读 API 和页面验收。

### M5：双动量 LLD 与编码门禁

状态：`PASS (2026-08-28)`。

1. 已将产品基线 v1.4、技术方案 v1.19 和 15 张正式 Figma 状态映射到文件、类、DTO、路由、URL、状态、交互和测试。
2. CodeGraph 已覆盖 `SectorMomentumQueryService`、`SectorMomentumCalculator`、Meta/Rankings API/schema、`SectorAnalysisPage`、方法栏、路由、现有 URL/controller 及测试消费者。
3. 已冻结“公共 Meta 事实 + 单日动量事实快照 + 独立双动量分类器”的复用边界；禁止复制公式或解释旧 Rankings DTO。
4. 已冻结两只 endpoint、3/5 SQL、五类比较池、四周期、三阈值、计数和状态不变量、409 版本恢复、前端按需挂载和 15 状态验收。
5. 已登记 `SA_FACT_VERSION_MISMATCH`；配置审计结论为“不适用”，M5/M6/M7 不新增配置、依赖、迁移、缓存、账号或结果表。
6. M5 只修改文档和异常码注册表，没有实现接口、页面、测试代码或 Figma；下一步只允许 M6 后端。

### M6：双动量后端

状态：`PASS (2026-08-28)`。

1. 先抽取公共 Meta 事实和单日动量事实快照，证明四个既有 endpoint JSON、SQL 和测试零变化。
2. 再实现版本化分类器、专属 strict schema、Meta/Results 及异常映射。
3. 第 11.1 节正反例已覆盖五 scope、四周期、三阈值、四组合、阈值相等、零值、小组、缺值、Partial/Delayed/Empty/Error、五计数、strict DTO、409 和来源门禁。
4. LLD 冻结后端套件 `217 passed`；完整 496 节点 Meta 与最大 337 行 Results 的 SQL、P95 和 payload 均通过；既有四 endpoint、Calculator 和首页板块速览零回退。
5. 未修改前端、Figma、数据库、迁移、配置、依赖或生产数据；M6 完成后停止，没有自动进入 M7、提交、推送或部署。

### M7：双动量前端

状态：`PASS (CODE + AUTOMATED TESTS, 2026-08-28)`。

1. 已新增正式 route、受控方法栏、独立 API／adapter／十项 URL／controller 和工作区；两个方法只挂载当前 controller。
2. 已实现 15 个 Figma 状态、完整滚动列表、摘要、响应式散点、放大 dialog、键盘／指针选择及 `minmax(0,1fr) 12px minmax(0,1fr)` 骨架。
3. 已覆盖五 scope、四周期、三阈值、历史恢复、局部零请求交互、5 秒超时、401、409、过期响应和快速连续筛选竞态；M7 定向 82 项、前端全量 436 项、typecheck/build 通过。
4. 未修改 M6 后端、数据库、迁移、配置、依赖、TopMarketBar、Shortcut、既有 `MomentumRankingWorkspace` 或 Members 主链；M7 已停止，未进入 M8。

### M8：双动量联调与交付

状态：`COMPLETE (2026-08-28)`。

1. 真实只读 API 以 `2026-08-27` 返回完整 496 节点 Meta 和 337 行 `LEVEL_3` Results；SQL event counter 为 `3/5`，payload 为 `207,102/154,491 bytes`。
2. 三组各 20 次真实 HTTP 的 Meta／Results P95 依次为 `672.030/347.204ms`、`280.642/391.372ms`、`307.458/372.163ms`。两轮稳态通过 500ms，冷启动 Meta 另观测到单次 `610.89ms`；用户于 2026-08-28 明确接受当前冷启动性能，该项作为已知非阻断表现保留证据，不再新增优化任务。
3. 15 个正式状态均已完成浏览器视觉与结构对照；六类 Ready、Hover、Partial、Empty、Small Group、No Qualified 和 Missing Coordinate 共十二个状态使用真实接口，Loading 使用真实请求过程，Delayed 和可重试 Error 使用浏览器传输层受控合同响应。受控状态只验证前端正式 DTO 和视觉，不作为生产数据状态证据。
4. 四档 `clientWidth` 下工作区为 `1564/1476/1424/1424px`，列宽为 `776/732/706/706px`，间距均为 `12px`；1600/1512/1460 无页面或模块溢出，1366 只有公共最小宽导致的页面级横向滚动，模块内部溢出为 0。
5. 真实交互验证结果视图、选择、排序、放大和待建设按钮零双动量请求；周期切换与浏览器返回恢复正确。完整后端套件 `203 passed`、前端全量 `436 passed`、typecheck 和生产构建通过。
6. 用户已完成页面验收并接受冷启动性能现状，M8 与本次双动量需求正式关闭；不自动开始相对轮动或其他方法。

### M9：相对轮动 LLD 与编码门禁

状态：`PASS (2026-08-28)`。

1. 已将产品基线 v1.8、技术方案 v1.25 和 Figma 14个正式节点逐项映射到第5.9、6.21～8.22、11～17节的文件、类、DTO、查询、状态、URL、SVG几何和测试合同。
2. CodeGraph 已覆盖现有动量 Calculator、Query、Snapshot QueryService、双动量 service、API/schema、页面/router/method/controller/adapter/SVG 与测试消费者；未发现必须改变既有公式或六只 endpoint 的实现障碍。
3. 已冻结两只只读 endpoint、3/5 SQL、最大95个开市日、一次行情批量读取、当前全量快照和选中轨迹的原子响应、409恢复及六只既有 endpoint 零变化门禁。
4. 已核对中央异常码：相对轮动复用既有 `SA_*`，只把 `SA_FACT_VERSION_MISMATCH` 的适用范围从双动量扩为双动量／相对轮动，不增加新码；配置审计结论为“不适用”。
5. 最大337个三级行业、95个开市日的有界只读审计和分段性能测量已通过 M10 可行性门禁；跨网络耗时不冒充部署态结论，M12 仍须做真实 HTTP P95。
6. M9 仅修改既有技术方案、LLD 和异常码注册表，没有编码、注册路由、修改 Figma、增加迁移／依赖／配置或写入生产数据。

### M10：相对轮动后端

状态：`PASS (2026-08-28)`。

1. 已严格按第5.9、6.21～7.13节实现公式合同、纯计算器、QueryService、strict DTO 和两只只读 API。
2. 既有开市日查询上限已从90精确扩为95并保留96拒绝；一次 Results 请求只读取一次行情事实，最多5条 SQL。
3. 日期切片按批准纠偏同时携带同源收益事实与排名事实，并校验日期、代码、顺序、数量、收益值和缺失状态；精确缺失原因不再从排名空值猜测。
4. 第11.1节正反例、来源架构门禁、既有六只 endpoint 零变化和最大337行业×95日结构／payload门禁均已通过；冻结后端回归为 `261 passed`。
5. 自动化性能门禁覆盖纯计算、DTO 与 JSON P95 不超过400ms，并为同进程数据库链路保留约100ms预算；部署同拓扑真实 HTTP P95 仍在 M12 验收，不用本地 SQLite／TestClient 冒充。
6. M10 没有新增前端 route、启用方法按钮、修改 Figma、迁移、配置、依赖、缓存或结果表，也没有部署或提交；完成后按停止点停在 M11 之前。

### M11：相对轮动前端

状态：`PASS (2026-08-28)`。

1. 已严格按第5.9、8.16～8.22节增加第三条精确路由、独立 API／strict adapter／URL／controller 和响应式工作区；三个已完成方法只挂载当前 controller，成员广度／量价分布继续零副作用 toast。
2. 已落实正式 Figma 14个状态的稳定骨架与状态表达；搜索、象限筛选、Hover 和放大均为零业务请求，参数或行业切换以完整 Results 原子替换当前快照和选中轨迹。
3. 相对轮动定向62项、前端全量473项、typecheck、production build、20项架构／静态门禁均通过；长名称、密集圆点、完整列表、共享坐标、键盘选择、ESC和焦点恢复均有自动化证据。
4. 浏览器已确认第三路由、公共骨架和相对轮动工作区按需挂载；现有本地后端在页面上下文请求阶段超时，因此真实 API 数据、部署态 HTTP P95 和四档最终人工视觉验收不计入 M11，继续留在 M12。
5. 停止点已遵守：只交付前端、测试和两份既有文档状态；未修改 M10 后端合同，未部署、未提交、未进入 M12。

### M12：相对轮动联调与交付

状态：`PASS (2026-08-29)`。

1. 远程部署、服务健康、真实 Meta、最大337行／60槽 Results、3/5 SQL、payload 和事实完整性已经通过首轮对账。
2. 首轮 Results 两轮20次稳态 localhost HTTP P95 为 `1250.883ms/1275.006ms`，曾触发原 `500ms` 门禁；M12R 部署后降至 `848.025/847.416ms`，两轮均通过用户最终确认的 `1,000ms` 门禁。
3. 相对轮动前端自动化、响应式布局和既有页面交互验收结论继续有效；用户确认页面验收无问题，并在性能门禁调整通过后明确 M12 完成。
4. 不得用 M9 估算或 M10 预制 facts 单测替代上述部署实测；当前 M12 已依据真实部署证据和用户验收关闭。

### M12R：相对轮动 Results 性能纠偏

状态：`PASS (2026-08-29)`。

1. 按第12.2节提取唯一排名 helper、增加单行业排名投影和稀疏当前快照／轨迹入口，删除生产全历史全行业网格路径。
2. 以旧路径为临时 oracle 完成全矩阵等价，再安全删除 `calculate_grid()`；共享三方法、API、schema 和前端合同必须零变化。
3. 部署提交 `a110f6a952ed73119ddedc8236aa789fe17b8234` 已完成固定复测：公共业务日 `2026-08-28`，Meta 为3条 SQL、`207,265 bytes`、两轮 P95 `246.014/206.779ms`；最大 Results 为5条 SQL、337行、337行可计算、60槽、`158,749 bytes`、两轮 P95 `848.025/847.416ms`。
4. 用户结合当前机器性能，将相对轮动 Results 的最终部署稳态门禁调整为 `P95 <= 1,000ms`；两轮均通过，M12R 关闭，M12 最终验收随后完成，不再进入独立查询投影方案。
5. 已完成代码证据：唯一排名 lookup 同时服务 `rank_strength()` 与 `rank_selected()`；生产 `calculate_grid()` 已删除；最大请求每次固定2次完整排名、最多63次单行业排名，只构造337个当前点和60个轨迹点。测试内旧网格 oracle、五类 scope、四周期、三轨迹长度、默认／显式选择、并列、缺失、小组和未来前沿门禁全部通过。
6. 已完成工程证据：定向65项、冻结后端274项、前端473项、typecheck、production build、Alembic 单一 head `20260829_000157` 均通过；未修改 API、schema、SQL、事实源、前端、迁移、配置或依赖。部署同一提交的两轮20次 HTTP P95 已完成并通过现行门禁；结合既有页面与交互验收，G37 已关闭。

### M13：成员广度 LLD 与编码门禁

状态：`PASS (2026-08-29)`。

1. 已按第2.9、5.10、6.28～9.7节完成当前代码、消费者、API、DTO、查询、公式、状态、前端和13张 Figma 的代码级对账。
2. 已否决 Meta 全历史成员／行情／因子完整性扫描；Meta 固定3条公共 SQL，实际缺口跟随 Rankings／Details 计算并按三指标独立返回。
3. 已确认 M3A 成员明细不使用 adj_factor，成员广度 MA 使用 `core.equity_adj_factor`；因子缺失只影响 MA。
4. 已冻结自动／显式日期、Rankings 单指标计算、Details 三项详情、3/4/4 SQL、119日、5+80%、异常码和正反例；M14 开工审计已将计算接口4条 SQL 修正为层级、公共页面日期、窗口覆盖成员合并查询、行情因子，消除服务端日期范围无法验证的问题。
5. 已以 Prod 只读 EXPLAIN 冻结性能门禁：Meta／非MA60一秒，MA60两秒；不新增索引、缓存、结果表、分页、迁移或后台任务。
6. M13 只修改技术方案与 LLD，没有修改运行代码、测试、异常注册表、Figma、生产或部署状态。

### M14：成员广度后端

状态：`PASS (2026-08-29)`。

1. 已确认 Alembic 单一 head 且未新增迁移；三只成员广度异常码已登记。
2. 已按第5.10、6.28～7.17节新增独立 contract、calculator、合并窗口／覆盖／成员 query、QueryService、strict schema 和三只只读 API。
3. 已完成第11.5节后端正反例，证明3/4/4 SQL、公共20:00口径、日期上下界／休市日拒绝、119/120边界、payload、性能预门禁及既有八只 endpoint 零回退。
4. 层级不可用已统一为 Meta HTTP500、Rankings/Details HTTP200 Error 的 `SA_HIERARCHY_UNAVAILABLE`；普通查询／合同失败继续使用 `SA_BREADTH_QUERY_FAILED`。
5. 后端冻结回归317项通过；没有修改前端、启用成员广度按钮、部署或进入 M15。

### M15：成员广度前端

状态：`PASS (2026-08-29)`。

1. 已按第5.10、8.23～9.7节新增第四 route、独立 API／strict adapter／九字段 URL／controller 和正式工作区；成员广度只在精确路由挂载，量价分布继续待建设。
2. 已落实两条请求顺序：合法 `sectorCode` 在 Meta 后并发 Rankings/Details；没有合法选择时先 Rankings，再按 `defaultSelectedSectorCode ?? rows[0]` 请求 Details，禁止猜测行业或无效预请求。
3. 已覆盖自动／历史日期、三项独立缺失、主 Empty/Error、局部 Details 状态、5秒超时、401、409一次重载、旧响应丢弃、固定表头独立滚动、趋势断点和四档宽度。
4. 前端全量 `501 passed`，新增成员广度工作区 `16 passed`，typecheck、production build及冻结后端317项通过；1600/1512/1460/1366四档受控 fixture 浏览器验收通过。真实认证 API、496行业、最大 Details、SQL、payload和P95没有在 M15 冒充完成，继续属于 M16。
5. 没有修改既有三个方法、后端 API、数据库、迁移、Foundation、Ops、QTF、配置、依赖或部署；M15 在此停止。

### M16：成员广度联调与交付验收

状态：`NOT PASS / STOPPED (2026-08-29)`。

1. 已在生产部署提交 `dc1911358dd71b42ddae924f6b5c68f666e9024b` 上使用认证 localhost HTTP 完成事实与载荷对账：公共业务日 `2026-08-28`、496行业（31/128/337）、五 scope、两方向、三指标、六均线、三历史范围均符合合同；最大行业 `BK1205.DC` 返回625只成员、60个趋势槽和三项组成，Meta／Rankings／Details payload 均在门禁内。
2. Meta 两轮20次 P95 为 `211.896ms/209.411ms`，通过一秒门禁。三级 MA20 Rankings 的已完成请求约为 `19.926～22.471s`；三级 MA60 Rankings 单次服务端日志耗时 `64.580s`，明确超过两秒门禁。最大 Rankings 失败后停止其余性能采样，不用不完整样本伪造 P95。
3. 全部请求结束后，Web 实时线程采样为0% CPU、健康检查正常，无需重启。M13 的生产查询计划已给出 MA60 数据库阶段约1.54秒，而完整 HTTP 达64.58秒；虽然当前没有逐阶段运行时计时、不能编造各阶段占比，但代码已确认 `rank_requested_metric()` 对337个行业逐一调用 `calculate_composition()`，而后者每次都对同一批行情重建 `market_index`；`build_details()` 又对当前三项和每个趋势日三项重复扫描关系并重建行情索引。现有成员广度 HTTP 性能测试只有2个行业、每个5只成员，只证明了小样本合同与 SQL 数，没有覆盖生产337行业和约16,923条目标日关系。这是必须先补齐的测试缺口和必须删除的重复计算；纠偏后仍需分段计时确认是否存在第二瓶颈。
4. 因真实性能失败，13张正式 Figma、真实页面交互和四档宽度验收没有继续执行；M15 fixture 证据仍有效但不能代替 M16，G47 保持失败开放，成员广度不得关闭。
5. 严格触发第17节停止条件：不得自行放宽门禁，不得新增缓存、索引、结果表、分页或截断，不得自动进入量价分布。该问题已由 M16R 完成本地等价纠偏，M16I 也已完成本地收口；完整 M16 仍须部署二者的同一版本后从头执行。

#### M16R：等价计算内核纠偏

状态：`CODE PASS / DEPLOYMENT PENDING (2026-08-30)`。

1. API、DTO、公式版本、三项分母、5+80%、逐日来源成员、4 SQL、完整列表与缺失语义全部保持不变；不修改前端、Figma、数据库、查询字段或产品门禁。
2. `rank_requested_metric()` 已在单次请求中只构建一次 `market_index`，并把目标日成员关系按 `sector_code` 一次分组；337个行业只消费自己的关系桶，不再每个行业重建同一全量索引或扫描全部关系。空行业池继续直接返回空结果，保持旧语义。
3. `build_details()` 已在单次请求中只构建一次 `market_index`，并把成员关系按 `trade_date` 一次分组；当前组成、60个趋势点和成员明细共享该只读索引，不再为每个日期、每项指标重复处理整批行情。
4. 已增加旧／新结果全矩阵等价 oracle，覆盖成员数量／成交额／均线位置、上涨／下跌及5/10/15/20/30/60均线；已增加337行业、16,923目标日关系、60日行情，以及625成员、119日行情、60个趋势槽的现实规模生成数据门禁。两类请求均断言完整行情索引只构建一次，本地纯计算分别约 `1.16s` 和 `1.03s`。
5. 纠偏通过后重新部署，从 Meta、非MA60 Rankings/Details、MA60 Rankings/Details 两轮20次开始完整重跑 M16，再执行13状态、五scope、两方向、三指标、六均线、三趋势范围和四档页面验收。未通过原一秒／两秒门禁时再次停止，不得继续叠加方案。

实现仅修改 `sector_member_breadth_calculator.py` 与对应计算器测试；冻结后端回归 `347 passed`，未新增迁移、依赖、配置、缓存、持久化表或跨子系统依赖。本地现实规模时间只用于证明重复工作已被删除，不能代替部署后的完整 HTTP 门禁。M16R 完成后停在本地代码收口，不自动部署、不提前关闭 G47。

#### M16I：成员广度趋势图十字线交互增量

状态：`LOCAL CODE + AUTOMATION + BROWSER PASS / DEPLOYMENT PENDING (2026-08-30)`。

1. 产品口径和正式 Figma Active 状态 `1190:15904` 已完成；按第5.10和8.25.1节，只修改 Workspace 局部状态、趋势图组件、局部样式、组件测试和最小工作区集成测试。
2. 实现 `IDLE/ACTIVE`：单击plot进入、最近交易日吸附、日期纵线、百分比横线、x/y浮标、三条有效交点和同日Tooltip；null不造点，Tooltip显示 `--`。
3. pointerleave保留最后读数；SVG内plot外空白／坐标轴区域再次单击或Escape退出。Details身份／状态变化清除，排名metric变化不清除。
4. 全部交互必须零请求、零URL变化、零controller变化；不得修改API/DTO/adapter、后端、数据库、迁移、Figma页面骨架、其他方法或量价分布。
5. 第11.5节新增正反例、定向23项、前端全量508项、typecheck、build和四档浏览器验收均已通过；已停止在本地验收，不自动提交、部署或关闭G47。下一步是部署M16R+M16I并完整重跑M16。

每个里程碑完成后停止，不自动进入下一阶段，不自动提交、推送、迁移或部署。

## 14. 验证命令

编码阶段按切片执行，最终至少包括：

```text
uv run pytest -q \
  tests/test_wealth_market_page_context_query.py \
  tests/web/test_wealth_market_context_api.py \
  tests/web/test_wealth_stock_detail_api.py \
  tests/web/test_wealth_index_detail_api.py \
  tests/web/test_wealth_turnover_insight_api.py \
  tests/web/test_wealth_stock_nine_turn_api.py \
  tests/web/test_wealth_index_nine_turn_api.py \
  tests/test_wealth_sector_analysis_contract.py \
  tests/test_wealth_sector_momentum_calculator.py \
  tests/test_wealth_sector_momentum_query_service.py \
  tests/test_wealth_sector_member_return_calculator.py \
  tests/test_wealth_sector_member_detail_query_service.py \
  tests/test_wealth_sector_momentum_snapshot_query_service.py \
  tests/test_wealth_sector_dual_momentum_classifier.py \
  tests/test_wealth_sector_dual_momentum_query_service.py \
  tests/test_wealth_sector_relative_rotation_calculator.py \
  tests/test_wealth_sector_relative_rotation_query_service.py \
  tests/test_wealth_sector_member_breadth_calculator.py \
  tests/test_wealth_sector_member_breadth_query_service.py \
  tests/web/test_wealth_sector_analysis_api.py \
  tests/web/test_wealth_market_sector_overview_api.py \
  tests/test_wealth_turnover_insight_static_gates.py \
  tests/architecture/test_wealth_sector_analysis_guardrails.py \
  tests/architecture/test_subsystem_dependency_matrix.py

cd wealth && npm test -- --run
cd wealth && npm run typecheck
cd wealth && npm run build
uv run alembic heads
uv run python scripts/check_docs_integrity.py
git diff --check
```

本期无迁移；`alembic heads` 只证明未意外制造迁移分叉，不等于生产验收。

## 15. 编码门禁矩阵

| Gate | 通过条件 | 当前状态 |
|---|---|---|
| G01 产品范围 | 动量排名、双动量、相对轮动、成员广度是独立方法；量价分布待建设 | PASS (docs/Figma) |
| G02 Figma Ready | 八张 Ready/交互画板覆盖六类榜单状态、共享 Hover 和交易日覆盖选择器；尺寸、术语、单 range、滚动正确 | PASS |
| G03 Figma states | Loading/Delayed/Empty/Error 正式画板 | PASS |
| G04 Design System | 公共组件复用、核心 Token、Auto Layout/绝对坐标边界正确 | PASS；共享组件遗留原始色值不扩改 |
| G04A M0 治理门禁 | 三张 Prod 来源、无迁移、无 QTF/DG/Lake/预测、统一异常码 | PASS (M0 static guardrail) |
| G04B M3A 治理增量 | 精确增加 DcMember/EquityDailyBar 与第四 endpoint；仍无迁移、无其他股票表/资金/Heat/QTF | PASS (M3A code/guardrail) |
| G05 路由 | 精确四 path、未知子路由反例 | PASS (M1) |
| G06 页面请求边界 | landing 零业务请求、模块按需挂载 | PASS (M1) |
| G07 Shortcut 零漂移 | 市场总览 DOM/视觉/交互回归 | PASS (M1) |
| G07A 公共日期单语句 | 20:00与显式日期语义零变化；所有合法调用恰好1条 SQL；9个消费者回归 | PASS (Pre-M2) |
| G08 事实源 | 只读三张 Prod 表 | PASS (M2) |
| G08A 成员事实源 | 后两张表只服务两个三级 scope 的成员明细；来源全集不被过滤 | PASS (Prod audit/M3A code) |
| G09 公式 | 1/5/10/20/30 与 N+1 完整窗口；真实缺口不得被隐藏或补值 | PASS (M2) |
| G10 排名语义 | listPosition/strengthRank/percentile 分离 | PASS (M2) |
| G11 时间前沿 | 历史逐日只读截至当日事实 | PASS (M2) |
| G12 API strict | unknown/duplicate/闭包/状态 validator | PASS (M2) |
| G13 异常码 | 统一注册表已登记并由安全 API builder 映射 | PASS (M2) |
| G13A 成员异常码 | 三个成员码已登记；409/局部 EMPTY/局部 ERROR 映射正确 | PASS (docs/M3A code) |
| G14 前端真实合同 | adapter 无业务计算、无 Mock | PASS (M3 code/user acceptance) |
| G15 选择保持 | URL 可恢复和切换规则全矩阵 | PASS (M3 code/user acceptance) |
| G16 双图联动 | 同日期、独立 y、rank1 顶部、null 断线 | PASS (M3 code/user acceptance) |
| G17 性能 | SQL 数、P95、payload、按需加载 | PASS (M2/M3A local same-topology)；按用户决定不追加生产部署验收 |
| G18 回归 | 现有自动化套件覆盖首页、成交额、板块速览、股票/指数详情既有合同 | PASS (M4 automated gates) |
| G19 用户验收 | 当前真实 API 页面完成用户验收；本阶段不要求部署后复验 | PASS (2026-08-28) |
| G20 成员公式 | 1 日 pct_chg、多日逐日连乘、完整 N 日、无补值、独立于行业算法 | PASS (M3A code/tests) |
| G21 成员局部状态 | 独立 request key/retry/abort；不污染整页五态 | PASS (M3A code/tests) |
| G22 成员响应式 | `390+12+464`、共享四列 Grid、三档无溢出、双滚动 | PASS (Figma/M3A browser) |
| G23 双动量产品与 Figma | 产品基线 v1.4、15 状态、组件集和旧草稿冻结一致 | PASS (M5 docs/Figma) |
| G24 双动量代码边界 | 公共 Meta 事实、单日快照、分类器、页面 service 职责及禁止项冻结 | PASS (M5 LLD/M6 code) |
| G25 双动量 API 合同 | 专属 Meta/Results、strict DTO、五计数、状态和 409 语义 | PASS (M6 code/tests) |
| G26 双动量公式 | 复用 basis@1；5/10/20/30、70/80/90、min group 3、零值边界 | PASS (M6 classifier/tests) |
| G27 双动量事实源 | 只读前三张 Prod 表，无 members/股票/资金/Heat/QTF/DG/Lake | PASS (M6 guardrail) |
| G28 双动量路由与按需挂载 | 两个方法精确路由，只挂载当前 controller，三按钮零副作用 | PASS (M7 code/tests) |
| G29 双动量前端事实边界 | adapter 无分类计算，resultView/选择/排序零请求，散点无伪点 | PASS (M7 code/tests) |
| G30 双动量交付 | 后端、前端、性能、15 状态和四档宽度全量验收 | PASS (M8 技术证据、用户验收与冷启动性能决策已完成) |
| G31 相对轮动产品与 Figma | 产品基线 v1.8、14个正式节点、旧草稿冻结及非传统 RRG 边界一致 | PASS (M9 docs/Figma) |
| G32 相对轮动代码影响面 | Calculator、Query、Snapshot、API、前端消费者、测试和六只冻结 endpoint 已逐项审计 | PASS (M9 CodeGraph/current code) |
| G33 相对轮动性能可行性 | 337行业×95开市日、5 SQL、一次行情读取、分段同拓扑估算低于500ms | HISTORICAL PASS (M9 estimate)；M12 部署实测已证明该估算不能代替 HTTP 门禁 |
| G34 相对轮动异常与配置 | 复用既有异常码且注册表已对账；无运营配置、环境变量或第二套常量 | PASS (M9 docs/registry audit) |
| G35 相对轮动后端 | 专属合同／计算器／QueryService／DTO／两只 API、95/96门禁及零回退 | PASS (M10 code/tests) |
| G36 相对轮动前端 | 第三路由、独立 controller、strict adapter、11项 URL、14状态和响应式 SVG | PASS (M11 code/tests) |
| G37 相对轮动交付 | 真实 API、3/5 SQL、payload/P95、四档宽度、交互与用户验收 | PASS：部署性能、既有前端证据与用户验收已完成 |
| G38 相对轮动架构边界 | 只读前三张 Prod 表；无 QTF/DG/Lake/宽基/申万/成员/迁移/配置/依赖 | PASS (M10 backend)；M11/M12 继续保持该边界 |
| G39 M12R 纠偏合同 | 真实瓶颈证据、稀疏等价方案、旧路径安全删除、共享回归和失败停止门禁完整 | PASS：两轮 HTTP P95 `848.025/847.416ms`，通过现行1,000ms门禁 |
| G40 成员广度产品与 Figma | 三独立指标、五scope、六均线、三趋势范围、13个既有正式状态和1个趋势查看Active状态与Design System一致 | PASS (M13 baseline + M16I product/Figma) |
| G41 成员广度代码影响面 | M3A不可复用、独立后端／前端链、既有八endpoint和三方法零变化 | PASS (M13 CodeGraph/current code) |
| G42 成员广度日期合同 | Meta零成员历史扫描；公共日期默认回退；URL显式历史不回退 | PASS (M14 backend + M15 frontend) |
| G43 成员广度公式与缺失 | 三分母、`close×adj_factor`、5+80%、缺因子只影响MA | PASS (M14 code/tests) |
| G44 成员广度 API/SQL | 三只strict API、3/4/4 SQL；计算接口复用公共页面日期并合并窗口／覆盖／成员查询；Rankings单指标、Details三项 | PASS (M14 code/tests) |
| G45 成员广度后端 | contract/calculator/query/service/schema/API与正反例 | PASS (M14 code/tests) |
| G46 成员广度前端 | 第四route、URL/controller、13态、响应式和按需挂载 | PASS (M15 code/tests/browser fixture) |
| G46A 成员广度趋势图交互 | 单击进入、日期吸附、十字轴、三交点、同日Tooltip、null、避让、保留／退出、身份清除和零请求 | PASS (M16I code/tests/browser)：定向23项、前端508项、typecheck/build和四档浏览器验收通过 |
| G47 成员广度交付 | 真实事实、payload、非MA60一秒、MA60两秒、四档宽度和用户验收 | OPEN：事实与payload通过；M16R与M16I本地收口通过，等待部署后性能／页面验收 |

### 15.1 例外白名单

当前白名单为空。Figma 图表和数据条使用绝对坐标是批准的正确结构，不属于代码或架构例外。

## 16. 计划对账

### 16.1 已完成的编码前工作

1. 产品口径、技术方案、当前代码和测试消费者已完成对账。
2. CodeGraph 影响面已覆盖路由、页面、Shortcut、MarketPageContext、hierarchy Query、sector-overview 消费者及测试。
3. Figma 已收口为六类 Ready 榜单状态、一个共享 Hover、一个交易日覆盖选择器和四个异常态，共 12 张正式交付画板。
4. Figma 已消除排名／百分位语义、缺失同级总榜、父级双排名、草稿跳转、下钻边界、重复显示范围、无共享悬停、纵轴裁剪、滚动语义和模块 Token/Text Style 问题。
5. LLD 已冻结文件、DTO、查询、算法、状态、交互、测试和里程碑。
6. DuckDB 只读审计已证明生产历史存在 20 个缺口日和 N+1 传导影响；Meta 覆盖 DTO 与计算完整性门禁已据此冻结。
7. M0 静态门禁已冻结三张 Prod 来源表、无迁移、禁用 QTF/DG/Lake/预测范围和统一 `SA_*` 异常码；6 项架构测试通过。
8. M1 已完成三个页面、四个精确路由、公共 Shell、共享 Shortcut、成交额入口迁移、方法栏和旧占位安全删除；板块业务请求仍为 0。
9. 公共行业层级 Query 已移动到 `market/common`，两个既有消费者与板块速览回归通过；没有保留旧路径兼容层。
10. Pre-M2 已把公共业务日期查询收敛为 1 条 SQL；固定北京时间、日期边界、空日历、合法／非法市场和 9 个直接消费者均通过自动化回归。
11. M2 已实现三个只读 API、strict schema、纯计算内核、五类比较池、日期状态、异常映射和 SQL 数门禁；定向与回归共 156 项通过。
12. Prod 只读审计、EXPLAIN 和应用计算基准已完成；现有索引满足本期范围，无迁移、缓存或结果表。
13. M3A 产品基线、D01-D05、两张 Figma 正式画板和 Prod 成分聚合审计已完成；最大 139 行和约 `13.5KB` 已证明完整返回不需要分页。
14. M3A LLD 已冻结第四 endpoint、必填 hierarchyVersion、独立 Query/Calculator/Service、局部状态、响应式 Grid、异常码、4 SQL 和测试矩阵。
15. M3A 已实现第四只读 endpoint、独立成员计算主链、局部 controller/state、响应式双列表、竞态保护和三类异常映射；后端 179 项、前端 379 项、typecheck/build 均通过。
16. 139 成员×30 日 SQL 门禁、最大真实组日 API P95/payload 和 1600/1512/1460 浏览器三档均通过；没有新增迁移、模型、配置、依赖、缓存或分页。
17. 双动量产品基线 v1.4、技术方案 v1.19、15 张正式画板和当前代码／消费者已经完成 M5 对账。
18. M5 已冻结公共 Meta 事实、单日动量快照、专属分类器、两只 API、strict DTO、五计数、URL/controller、散点和全矩阵测试；`SA_FACT_VERSION_MISMATCH` 已完成编码前登记。
19. M6 已实现公共 Meta、单日快照、双动量分类器、专属 strict DTO 和两只只读 API；217 项冻结后端回归、3/5 SQL、完整 496 节点 Meta／最大 337 行 Results P95/payload 与来源架构门禁均通过。
20. M7 已实现双动量精确路由、受控方法栏、独立 API／adapter／URL／controller、15 个正式状态和响应式工作区；定向 82 项、前端全量 436 项、typecheck/build 均通过，未修改后端合同或既有动量 DOM。
21. 相对轮动产品基线 v1.8、技术方案 v1.25、Figma 14个正式节点及当前前后端消费者已完成 M9 代码级对账；本 LLD 已冻结 M10/M11 的精确文件、类、DTO、请求、响应、查询、公式、URL、状态和 SVG 几何。
22. M9 CodeGraph 影响面覆盖现有 Calculator、Query、Snapshot、双动量 service、API/schema、页面/router/method/controller/adapter/SVG 与测试；相对轮动不需要修改既有公式、页面 DTO 或跨子系统依赖。
23. M9 有界只读审计使用当前337个三级行业、最近95个 SSE 开市日和31,614条行情事实；5条 SQL 执行合计 `91.868ms`、纯计算与 DTO/JSON P95 `107.363ms`、同拓扑核心估算 P95 `199.231ms`，允许进入 M10。
24. 中央异常码、无配置结论、六只既有 endpoint 零变化、95允许／96拒绝、一次行情读取及 M10～M12 停止点均已落入文档；M9 没有代码、路由、Figma、迁移、依赖、配置或生产写入。
25. M10 已实现版本化内部合同、纯计算器、专属 QueryService／strict DTO／两只只读 API；日期切片的收益与排名事实具备完整对齐反例，精确缺失原因直接来自同源收益事实。
26. M10 最大337行业×95日结构门禁证明 Results 为5条 SQL、一次行情读取、完整337行、60个轨迹日期槽且 payload 不超过256KB；纯计算、DTO 与 JSON 自动化 P95 不超过400ms，部署态真实 HTTP P95 仍留在 M12。
27. M10 冻结后端回归 `261 passed`；没有新增前端、迁移、配置、依赖、缓存、结果表或跨子系统反向依赖，下一步只允许进入 M11。
28. M11 已实现第三条精确路由、独立 API／strict adapter／11项 URL／controller、14态工作区、共享坐标 SVG 和完整滚动列表；相对轮动定向62项、前端全量473项、typecheck/build及20项静态／架构门禁通过。真实 API、部署态 P95 和四档最终人工视觉验收继续严格留在 M12。
29. M12 已完成远程部署和真实 API 首轮审计：Meta、3/5 SQL、payload、337行和60槽事实完整性通过；首轮 Results 两轮 P95 `1250.883/1275.006ms` 触发原门禁并进入 M12R，属于历史审计事实。
30. M12R 已完成稀疏计算、旧网格安全删除和部署复测：两个完整排名切片服务当前全榜，其余最多63日只投影选中行业，坐标对象收敛为337个当前点与60个轨迹点；测试内旧路径 oracle、共享消费者、全 API 矩阵和前端 strict adapter 零变化门禁通过。部署提交 `a110f6a9` 的两轮最大 Results P95 为 `848.025/847.416ms`，通过用户确认的1,000ms门禁；结合既有页面与交互验收，M12/M12R 均已关闭。
31. 成员广度产品基线、13张既有正式状态Figma和技术方案已完成对账；M16I 另新增趋势查看 Active 状态 `1190:15904`，不改变既有页面骨架。M14 已按冻结的精确文件、类、三只 API、strict DTO 和三项公式落地，M15 已完成第四路由、strict adapter、九字段 URL、controller、正式状态和响应式布局。
32. M13 CodeGraph 影响面确认成员广度只能新增独立 Biz／Wealth 链；现有 M3A 只读 close/pct_chg 且不读复权因子，禁止复用或改写。
33. M13 性能审计已否决 Meta 全历史成员完整性扫描，冻结公共3 SQL；实际缺口随计算返回。三级 MA60 数据库聚合约1.54秒，用户确认该路径两秒门禁，其他请求保持一秒。
34. 自动日期／显式历史、复权因子只影响MA、Rankings只算所选指标、Details三项独立事实、3/4/4 SQL、119日和 M14～M16 停止点均已落档；M15 按合法选择是否存在分别采用“并发 Rankings/Details”和“先 Rankings 后 Details”，没有猜测默认行业。M15 没有修改后端、异常注册表、Figma或生产状态。
35. M16 生产事实、范围和 payload 已通过，Meta 稳态 P95 通过；MA20 Rankings 约19.9～22.5秒、MA60 Rankings 单次64.58秒，代码已确认同一请求内存在重复构建整批行情索引和重复扫描成员关系。第17节停止条件已触发，G47 保持开放。
36. M16R 已删除上述重复工作：Rankings 每请求只建一次行情索引并按行业分组，Details 按日期分组且组成／趋势／成员共享索引；旧／新全矩阵等价、两类现实规模及冻结后端347项通过。部署后完整 M16 复测仍是关闭 G47 的必要条件。
37. M16I 已按最新批准交互实现为纯前端零请求增量：Workspace 局部状态跨排名指标刷新保留，TrendChart 完成单击后十字线查看、交易日吸附、三线交点、同日Tooltip、离开保留及空白单击／Escape退出；非等比例容器按固定 viewBox 精确映射。定向23项、前端508项、typecheck/build和四档浏览器验收通过，G46A关闭。

### 16.2 已接受的非阻断项与历史记录

1. M4 的 12 节点最终 Figma 像素/交互及 1366 宽专项验收按用户此前决定不执行，不再作为本期关闭条件。
2. 周边页面专项人工回归和部署后生产验收按用户此前决定不执行，不再作为本期关闭条件。
3. M3A 代码已提交为 `e13eab20`，M4 自动化门禁已通过，本期没有迁移。
4. 双动量 M8 的真实 API、SQL/payload、15 状态、四档宽度、真实交互和全量门禁已经完成；用户已验收页面并接受当前冷启动性能，本需求不存在待执行收口项。
5. 相对轮动 M9 的跨网络完整链路 P95 `2343.531ms` 和同拓扑 `199.231ms` 分段估算都只保留为历史可行性证据；M12 已用真实部署 HTTP 覆盖其最终验收效力，不能再引用 M9 估算宣称性能通过。

## 17. 风险、回滚与停止条件

| 风险 | 预防 | 回滚 |
|---|---|---|
| 根路由语义变化 | M1 测试三个精确地址和浏览器历史 | 恢复前一提交；不保留双语义兼容分支 |
| Shortcut 提取漂移 | 原 class/尺寸、MarketOverview screenshot/DOM 门禁 | 回退 M1，共享组件不带入 M2 |
| hierarchy Query 移动影响首页 | 全消费者 import 清单 + sector-overview 真实 API 回归 | 回退 M2 整体移动；不留 re-export |
| 多日计算误用自然日 | 只从 SSE calendar 取窗口 | calculator 单测失败即停止 |
| direction 污染历史排名 | history schema 无 direction；纯函数分离 | API 契约测试失败即停止 |
| 历史 SQL 变 N+1 | 有界一次查询 + SQL event counter | 性能门禁失败，回到 Query 设计 |
| 成员收益误用行业公式 | 独立 `SectorMemberReturnCalculator` 和反例；禁止复用首尾 close 计算器 | 回退 M3A，不修改 M2 行业算法 |
| 成员广度请求出现 N+1 | 四条 SQL event counter，行情按代码/日期集合批量查询 | 停止 M14，回到成员广度 Query 设计 |
| 层级版本串代 | 请求必带 hierarchyVersion；409 后从 meta 重载 | 丢弃当前四类缓存，不拼接响应 |
| B 股/停牌被静默过滤 | Query 只按 dc_member 来源关系，空行情保留行 | 测试发现行数减少即否决 M3A |
| 固定四列在窄宽度溢出 | 表头/行共享 fr Grid；1600/1512/1460 三档验收 | 回退成员 CSS，不改变整页宽度合同 |
| Figma 示例被写死 | LLD 明确示例非默认，默认由层级/排行事实产生 | code review/测试禁止固定行业代码 |
| 1600 基线被误作运行时固定宽度 | 工作区、工具栏、状态面板使用 `width:100%`，两列使用等分弹性轨道；在 1600/1512/1460 三档实测 | 任一非 1600 宽度出现裁剪或模块级横向溢出即不通过 M3 |
| 共享组件遗留 Token 债务 | 本期只记录，不扩大全站修改 | 不影响本模块；另立 Design System 任务 |
| 双动量复制公式 | 分类器自行重算收益／排名或解析旧页面 DTO | 只消费不可变快照；发现第二套公式即停止 M6 |
| 抽取快照改变旧接口 | Rankings 的排序、DTO、状态或 SQL 被公共化重构污染 | response dump + 四 endpoint 全量回归；不能保持零变化则回滚 M6 |
| 小组产生伪资格 | 1～2 个对象仍按百分位高亮 | minimumGroupSize=3；只保留中性客观事实 |
| 前端自行分类 | 页面依据收益／百分位重算资格 | strict adapter 只读服务端状态；源码静态门禁禁止公式 |
| 方法切换双请求 | 两个 controller 同时挂载或隐藏 DOM | route 判别只渲染一个 feature；请求计数反例 |
| 旧草稿进入开发 | 引用 `967:72` 而非 15 张正式画板 | 设计节点测试清单和 code review 拒绝 |
| 相对轮动被误写成传统 RRG | 引入宽基指数、RS-Ratio 或 RS-Momentum | 只允许 `sector-relative-rotation@1` 的同组百分位与5日变化；来源门禁直接拒绝 |
| 前端复制轮动公式 | 页面自行计算区间收益、百分位、5日变化或象限 | 后端返回全部业务事实；strict adapter 和源码门禁只校验、展示 |
| 95日窗口出现 N+1 | 按行业、轨迹日期或目标日期循环查行情 | 开市日、层级和行情各批量一次；SQL event counter 固定 Results 最多5条 |
| 当前快照和轨迹串代 | 切换行业或参数时旧轨迹覆盖新快照 | 单个 Results 原子返回；完整 request key + AbortController + generation 丢弃旧响应 |
| 缺失事实形成伪坐标 | null 被补为0、前值或连接缺口两端 | DTO保留日期空槽和缺失原因；adapter拒绝伪点，SVG按 null 分段 |
| 小组被赋予象限含义 | 2个可计算行业仍按强弱状态着色 | `minimumGroupSize=3`；小组只画中性客观坐标，象限计数必须为0 |
| 普通图与放大图漂移 | 两处分别计算纵轴或刻度 | controller/useMemo 只生成一份 plotScale，两处复用同一坐标合同 |
| 密集点和长名重叠 | 337行业全部常驻名称或按字符硬截断 | 仅选中行业常驻；其他名称只在 Tooltip，按真实文字宽度测量和边界避让 |
| 预制 facts 性能测试被误解 | 内核测试不含真实 SQL、结果传输和 ORM 行物化 | 明确测试证明范围；最终只认部署 localhost 认证 HTTP 两轮 P95 |
| 中间事实过度物化 | 只返回当前全榜和选中轨迹，却生成65个全排名切片与60个全坐标切片 | M12R 稀疏投影并以旧路径等价；完成后删除生产全网格入口 |
| 稀疏修正后仍超预算 | 31,614行读取／物化可能使 P95 超过1,000ms | 立即停止；另立只读查询投影可行性审计，不在同一轮加索引或缓存 |
| Meta 重复扫描全历史成员 | 为日期选择逐日验证496行业、股票和因子 | Meta 只复用公共 `dc_daily` 覆盖3条 SQL；成员缺口跟随实际计算返回 |
| 复权缺口连坐全部指标 | 因 MA 缺因子而回退或清空成员数量／成交额 | 三项独立 coverage/eligibility；因子原因只进入 MA |
| 普通榜单等待 MA60 | Rankings 为了三项可用性计算全部指标 | Rankings 只计算请求 metric；数量／成交额路径不得调用 MA |
| 自动回退被历史复盘误报 | 仅比较 tradeDate 是否等于默认回退日 | URL 是否存在 tradeDate 是唯一模式判别；默认日不自动写 URL |
| MA60 超时被无限放宽 | 把2秒门禁扩散到其他周期和接口 | 只有 MA60 Rankings/Details 为2秒；Meta和其他请求仍1秒 |

必须停止并等待确认的情况：

1. 当前表字段或索引与本文不一致，且会改变查询/迁移范围。
2. 真实 API 性能超预算，需要新增索引、缓存、结果表或虚拟列表。
3. 产品要求在成员广度中引入概念、地域、申万、更多成员字段、资金、Heat、预测、综合分或 QTF。
4. Figma 需要改变页面尺寸、左右栏比例、字段、颜色、字号或图表结构。
5. 公共 hierarchy 移动无法保持 sector-overview 行为零变化。
6. 单日快照抽取不能保持既有四 endpoint response、SQL 数或 Calculator 语义零变化。
7. 双动量需要新增数据库、索引、缓存、配置、依赖、结果表、成员／股票事实或产品未批准字段。
8. Figma 正式节点与本文 DTO、状态或响应式合同出现无法消除的冲突。
9. 最大95日窗口在部署同拓扑仍超过5 SQL、256KB或稳态 P95 1,000ms；当前 M12R 复测未触发该条件。
10. 相对轮动实现需要修改既有动量／成员／双动量六只 endpoint、现有 `SectorMomentumCalculator` 公式或首页板块速览语义。
11. 必须引入宽基、申万、成员、股票、资金、Heat、QTF、DG/Lake、写事务、新配置、新依赖或数据库迁移才能完成相对轮动。
12. `selectedTrail`、当前快照、日期槽、计数或状态无法在一次 Results 响应内保持同一 hierarchyVersion、observedTradeDate 和参数事实。
13. M12R 稀疏计算部署后任一20次稳态轮次 P95 仍超过1,000ms；必须停下并等待新的查询投影方案批准。
14. M14 需要让 Meta 读取成员／股票／因子历史，或需要修改既有 `SectorTradeDateAvailabilityDto` 的公开语义。
15. M14 需要新增索引、缓存、结果表、分页、截断、迁移、后台任务、配置或依赖才能达到门禁。
16. 非MA60 任一成员广度 endpoint 部署 P95 超过1秒，或 MA60 超过2秒；必须先分段剖析并等待方案确认，不能自行放宽。
17. 成员广度实现无法保持三项缺失独立、Rankings 单指标计算、Details 119日上限或既有八只 endpoint 零变化。

## 18. 结论

既有动量排名 M0～M4、双动量 M5～M8 和相对轮动 M9～M12R 保持原验收结论。成员广度 M14 后端已经完成，三只 strict 只读 API、独立合同与计算、集合查询、3/4/4 SQL、119日边界、异常和正反例均通过自动化门禁。

成员广度 M15 前端已经完成：已消费冻结的三只 API 合同，建立第四条独立路由、strict adapter、URL/controller、正式状态工作区和四档响应式布局，并通过前端全量、类型、构建、冻结后端和受控 fixture 浏览器验收。

M16 已使用部署后的真实认证 API 核对生产日期、496行业、资格分布、最大625成员 Details 和 payload，事实部分通过；但 MA20／MA60 Rankings 性能明确失败。M16R 已完成本地等价计算内核纠偏：完整行情索引在每个请求内只构建一次，关系按行业或日期一次分组，旧／新全矩阵结果一致，现实规模测试和347项冻结后端回归通过。M16I 趋势查看已完成产品、Figma、代码、自动化与四档浏览器验收。成员广度当前仍不能关闭，下一步固定为部署 M16R+M16I 并完整重跑 M16 性能与页面验收。

### 18.1 版本记录

| 版本 | 日期 | 变更摘要 |
|---|---|---|
| v1.35 | 2026-08-30 | 完成M16I本地收口：Workspace持有纯局部查看状态并跨排名指标刷新保留，TrendChart实现单击进入、交易日吸附、横纵十字线、三系列交点、同日Tooltip、null、左右避让、离开保留、空白单击／Escape退出和身份变化清除；显式`preserveAspectRatio="none"`保证非等比例容器与固定viewBox一致。定向23项、前端508项、typecheck/build和四档浏览器验收通过，G46A关闭；G47等待部署后完整M16 |
| v1.34 | 2026-08-30 | 校准M16I产品、Figma和代码阶段：默认IDLE引用`1186:11797`，Active视觉引用`1190:15904`；明确Active只是静态视觉基线，运行时继续以真实容器映射既有`920×244` viewBox，不复制Figma绝对坐标；G40更新设计证据，G46A改为DESIGN PASS/CODE OPEN，代码与验收仍未执行 |
| v1.33 | 2026-08-30 | 按用户确认增加M16I编码方案：当前静态成员广度趋势图新增IDLE/ACTIVE状态、真实容器到viewBox映射、最近交易日吸附、横纵十字线与浮动轴标签、三线有效交点、同日三值Tooltip、null语义、62%左右避让、离开保留、plot外空白单击或Escape退出，以及Details身份变化清除；限定四个前端文件、零请求、零URL/controller/API/DTO/后端/数据层变化，G46A保持OPEN等待实现 |
| v1.32 | 2026-08-30 | 完成成员广度 M16R 本地代码收口：Rankings 单次索引＋按行业分组，Details 单次索引＋按日期分组并由组成／趋势／成员共享；新增三指标／两方向／六均线旧新全矩阵等价，以及337行业／16,923关系和625成员／119日／60趋势槽现实规模门禁，纯计算约1.16s／1.03s，冻结后端347项通过。对外合同、SQL、前端和数据层未变；G47继续开放，等待部署后完整M16复测 |
| v1.31 | 2026-08-29 | 执行成员广度 M16 生产验收：公共日期、496行业、五scope、资格分布、最大625成员、六均线、三趋势范围和payload通过，Meta两轮P95约212/209ms通过；三级MA20约19.9～22.5秒、MA60单次64.58秒，明确不通过性能门禁。代码审计确认排名／详情重复重建整批行情索引并重复扫描关系；按停止条件中止，记录待确认的M16R等价内核纠偏范围，G47保持失败开放 |
| v1.30 | 2026-08-29 | 完成成员广度 M15 前端：新增第四条精确路由、strict adapter、九字段 URL、独立 controller 与正式工作区；落实合法选择并发、无选择先 Rankings 后 Details、5秒超时、401、一次409重载、局部错误、竞态丢弃、完整滚动列表、趋势断点及四档自适应；前端501项、工作区16项、typecheck/build、后端317项和受控 fixture 浏览器验收通过，下一步固定M16真实联调与性能验收 |
| v1.29 | 2026-08-29 | 完成成员广度 M14 后端：新增不可变合同、纯计算器、窗口覆盖成员合并查询、行情因子查询、QueryService、strict DTO、三只只读 API 和正反例；证明3/4/4 SQL、119允许/120拒绝、六均线、三项独立缺失、5+80%、竞争排名、完整成员、401/409/payload及既有消费者零回退；统一层级不可用的 Meta HTTP500／业务HTTP200安全 Error 语义；317项冻结回归通过，下一步固定M15 |
| v1.28 | 2026-08-29 | 修正 M14 开工审计发现的日期校验与4 SQL冲突：Meta维持公共日期／层级／日期覆盖3条；Rankings／Details 固定为层级、既有公共页面日期、SSE窗口＋当前层级dc_daily覆盖起点＋成员关系合并查询、行情＋因子4条；冻结 `MemberBreadthWindowRelationsFact`、合并查询入参／输出、日期上下界与休市日反例，不复制20:00算法、不信任前端Meta、不增加历史成员预扫描，尚未编码 |
| v1.27 | 2026-08-29 | 完成成员广度 M13 代码级 LLD：基于 CodeGraph、当前代码和 Prod EXPLAIN 否决 Meta 全历史成员完整性扫描，冻结公共日期覆盖3 SQL、自动／显式日期模式、三指标独立缺失、`close×adj_factor` 六均线、Rankings单指标、Details三项、3/4/4 SQL、119日、非MA60一秒／MA60两秒、精确文件／DTO／前后端状态／测试／G40～G47及M14～M16顺序；尚未编码 |
| v1.26 | 2026-08-29 | 校准相对轮动最终状态：既有页面与交互验收无问题，M12R 两轮部署 P95 通过1,000ms门禁后已解除唯一剩余阻断；M12、M12R、G37、G39 全部关闭，本需求结束且不自动进入后续方法 |
| v1.25 | 2026-08-29 | 用户结合当前机器性能，将相对轮动 Results 的部署同拓扑稳态门禁由 `500ms` 调整为 `1,000ms`；提交 `a110f6a9` 的两轮 P95 `848.025/847.416ms` 因此通过，M12R/G39 关闭并取消事实投影审计分支，M12/G37 仅剩四档宽度、完整交互和最终用户验收 |
| v1.24 | 2026-08-29 | 完成 M12R 部署复测：提交 `a110f6a9` 保持3/5 SQL、337行、337行可计算、60槽和 `158,749 bytes`，Results 两轮20次 P95 为 `848.025/847.416ms`，仍未通过500ms；按第12.3节立即停止，下一步仅允许先审计只读事实投影／行物化缩减方案并等待批准 |
| v1.23 | 2026-08-29 | 完成 M12R 稀疏计算代码与本地门禁：提取唯一排名 lookup、新增单行业排名和内部切片，当前仅构造两个完整排名切片、337个当前点与60个选中轨迹点，旧生产 `calculate_grid()` 安全删除；测试 oracle、274项后端、473项前端、typecheck/build和单一 Alembic head 通过，部署两轮20次 Results P95 仍待执行 |
| v1.22 | 2026-08-29 | 完成 M12 真实部署首轮审计和 M12R 代码级纠偏 LLD：Results 两轮20次稳态 P95 为 `1250.883/1275.006ms`，确认全历史全行业排名／坐标过度物化及31,614行事实读取／物化成本，排除 JSON 与无证据索引判断；冻结唯一排名 helper、单行业排名投影、稀疏当前快照／轨迹、旧 `calculate_grid()` 安全删除、共享回归、部署复测和失败即停门禁，尚未修改业务代码 |
| v1.21 | 2026-08-28 | 完成相对轮动 M11 前端：第三条精确路由、独立 API／strict adapter／11项 URL／controller、14态响应式工作区、共享坐标 SVG、完整滚动列表、原子选择和零请求本地交互落地；定向62项、前端全量473项、typecheck/build及20项静态／架构门禁通过，下一步固定为 M12 真实 API 联调与交付验收 |
| v1.20 | 2026-08-28 | 完成相对轮动 M10 后端：实现版本化合同、纯计算器、QueryService、strict DTO 和两只只读 API；落实收益／排名事实对齐纠偏，95允许／96拒绝、3/5 SQL、一次行情读取、最大337×95结构／payload、精确缺失、状态、来源边界及261项冻结回归通过，下一步固定为 M11；部署态真实 HTTP P95仍留在M12 |
| v1.19 | 2026-08-28 | M10 开工纠偏：日期切片同时保留同源收益事实和排名事实，冻结两者对齐门禁，使 current/comparison 缺失原因可由真实输入直接传递；不改变产品、公式、API、SQL 或里程碑边界 |
| v1.18 | 2026-08-28 | 完成相对轮动 M9 代码级 LLD：对账当前代码与消费者、冻结 M10/M11 文件和类、两只 strict API、95日单次批量查询、公式／状态／URL／SVG几何、异常和测试矩阵；最大337行业×95日的有界只读分段性能门禁通过，下一步固定为 M10 后端，尚未编码 |
| v1.17 | 2026-08-28 | 用户确认页面验收无重大问题并接受当前冷启动性能；双动量 M8/G30 关闭，本需求结束，不再新增性能优化任务，也不自动进入其他分析方法 |
| v1.16 | 2026-08-28 | 完成双动量 M8 技术联调：真实 496 节点／337 行 API、3/5 SQL、payload、15 正式状态、1600/1512/1460/1366 四档宽度、零请求交互、203 项后端与 436 项前端回归均已对账；两轮稳态 P95 通过但冷启动 Meta 曾超过 500ms，最终用户验收和性能结论仍待确认 |
| v1.15 | 2026-08-28 | 完成双动量 M7 前端：精确路由与按需挂载、独立 strict adapter／URL／controller、15 个状态、完整列表与响应式散点、历史恢复、超时／401／409／竞态保护及零请求交互均完成自动化；定向 82 项、前端全量 436 项、typecheck/build 通过，下一步 M8 |
| v1.14 | 2026-08-28 | 完成双动量 M6 后端：公共 Meta、单日快照、分类器、专属 DTO、Meta/Results、409、3/5 SQL、完整 496 节点 Meta／最大 337 行 Results 性能和 217 项冻结回归通过；下一步 M7，未编码前端 |
| v1.13 | 2026-08-28 | 完成双动量 M5：基于当前代码和 CodeGraph 冻结公共 Meta／单日事实快照、独立分类器、Meta/Results DTO、异常、URL/controller、散点、15 状态、性能、测试和 M6～M8 顺序；下一步 M6，未编码 |
| v1.12 | 2026-08-28 | 记录既有动量排名 M4 自动化门禁与用户验收状态 |
