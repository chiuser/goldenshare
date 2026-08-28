# 市场总览｜板块速览低层设计 v2（LLD）

> 状态：Slice 14 已由 `2026-08-27` 真实开放日自然链完成自动发布、read-back/hash 与同日防重复验收，结论 PASS；下一步仅可在独立授权后进入 Slice 15。2026-08-15 用户另行批准板块速览聚焦纠偏：先修正式 Figma，再原子修正行业双榜、概念固定列和可见范围 `PARTIAL`；不扩展其它功能。
> 日期：2026-08-28
> 需求基线：[sector-overview-benchmark-requirement-v2.md](./sector-overview-benchmark-requirement-v2.md)
> 实施方案：[sector-overview-implementation-design-v2.md](./sector-overview-implementation-design-v2.md)
> 编码门禁：[sector-overview-m2-coding-gate-v2.md](./sector-overview-m2-coding-gate-v2.md)

---

## 1. 结论与开工边界

### 1.1 本 LLD 冻结的实现结论

1. V2 仍使用现有 `GET /api/v1/wealth/market/sector-overview`，前后端在同一发布单元原子替换旧 DTO；不保留 V1/V2 双契约、别名字段或兼容 adapter。
2. 行业层级通过 `silver_dc_industry_hierarchy -> prod_core_wealth_sector_hierarchy -> core_serving.wealth_sector_hierarchy` 发布，Web 不读 Parquet。
3. 概念热度由 biz prod-native 物化服务只读生产 PostgreSQL 正式表，在质量 contract 通过后按交易日直接发布到 `core_serving.wealth_sector_heat_daily`；不生成 DG Gold 或第二份 Heat 事实，Web 请求不计算 Heat。
4. Heat 的行情、成员、资金、证券资格、停牌、涨停和前序 Heat 全部来自 prod；DG/Lake 只保留行业层级输入，不参与 Heat 计算、回放或 API 查询。
5. `biz` 承载 Heat 来源查询、有效池、公式、质量和事务发布；`ops` 只承载任务意图、计划快照、TaskRun/节点/问题/进度和失败观测。
6. `ops -> biz` 被依赖矩阵禁止；`ops` 通过窄执行端口调用，`app` 组合根负责把该端口绑定到 biz Heat 服务。业务事务与 TaskRun 状态事务必须分离。
7. 新 ORM 必须进入 `src/foundation/models/core_serving/**`，并在 `core_serving/__init__.py`、`all_models.py` 和模型注册测试中登记；不放入 legacy 或错误的 `models/core/**` 路径。
8. Heat 不使用 Dagster asset、dynamic partition、asset check、sensor、Gold 路径、runless event 或 DG history CLI；60 日回放是 prod-native TaskRun。
9. hierarchy、60+25 日 prod 来源、Heat/app 执行装配、事务与访问边界、60 日生产回放已经通过并继续作为有效基础；前后端 V2 只能记为“已实现、未验收”，不能再表述为完成。
10. 2026-08-13 对照需求基线、implementation design、M2 Gate、正式 Figma 节点树与当前代码复审后，确认存在 API 展示契约不足、有效池字段口径、成员名称来源、排序空值、来源状态、默认日期、错误态、三工作台结构、详情结构、Heat 表达、交互、六态骨架、自动化测试、像素、性能与发布门禁等偏差；完整台账见第 2.5 节。
11. 新修正步骤从 Slice 9 连续编号。Slice 9-14 已完成设计、后端、前端、生产 Heat v2、全矩阵自动化与真实开放日 Heat 自动发布验收；剩余工作依次为 Slice 15 像素、Slice 16 候选部署/性能和 Slice 17 最终对账。
12. Slice 14 不修改 Heat 公式、hierarchy、回放语义或数据库结构。用户于 2026-08-15 单独批准的行业双榜、概念固定列和状态误报纠偏作为原子前后端修正先行，不改变 Slice 15-17 的像素、候选部署和最终对账顺序。

### 1.2 当前事实快照

| 项目 | 当前结论 |
|---|---|
| Git 分支 | `dev-interface` |
| Alembic head（2026-08-28 只读复核） | 生产当前单 head 为 `20260827_000153`；本需求 revision `20260813_000134` 位于有效链上并已完成生产结构/授权验收 |
| 当前 API | 前后端均已破坏性拆为 Industry/Concept/Region view-specific rank 与 detail；概念/地域固定列由后端直接返回，旧前端通用业务 rank/detail 契约已清零 |
| 当前后端来源 | hierarchy、Heat、行情、成员与资金均读 Prod；DG 只发布 hierarchy。成员展示名已切到 `dc_member.name`，有效行情统一为 `close + pct_chg` |
| 当前前端 | 已完成正式 header/tabs/toolbar、三个 view-specific workspace/rank/detail、七行滚动、20 日断点、地域 breadth、股票导航、默认日期和穷尽状态骨架；本轮须同步正式 Figma 的概念固定五列与行业双榜，正式整页像素仍后移到 Slice 15 |
| 行业层级 Lake | 现有单文件正式 Silver，契约要求 496 行、31/128/337 |
| Heat prod 来源 | `trade_calendar/dc_index/dc_daily/dc_member/board_moneyflow_dc/equity_daily_bar/equity_limit_list/security_serving/equity_suspend_d` 与前序 Heat |
| 当前来源审计 | 目标窗 `2026-05-20..2026-08-12`、warm-up `2026-04-10..2026-05-19` 已冻结并完成整窗复核；资金流对目标概念 100% 覆盖、有效池无真实缺行情；`dc_daily@2026-05-18/20/22/25` 的 88/448/1/2 个缺行在 Prod Raw/Core 一致，按逐概念 `INVALID` 处理 |
| 当前运行缺口 | v2 PLAN `8208`、APPLY `8210`、幂等重放 `8213` 与 `2026-08-27` 真实开放日单日 condition-only schedule 自然发布均已通过；Slice 14 已闭环，仍有 Slice 15 像素、Slice 16 候选部署/性能和 Slice 17 最终对账 |

### 1.3 禁止项

1. 不在页面、adapter 或 API handler 里计算热度、层级、有效池或排序事实。
2. 不按名称模糊关联资金流，不按股票代码前缀判断 A/B 股，不用“有行情”反推上市或停牌。
3. 不把 DG/Lake 或本地文件当成 Heat 事实源；Heat 必须可由冻结的 prod 输入、配置版本/hash和来源 hash 独立重建。
4. 不增加 Redis、实时行情、分钟刷新、20 分钟变化或盘中加速度。
5. 不新增 Kopia、旧 Lake 路径或来源业务表写入。
6. 不在迁移中回填数据、删除来源表、`drop-before-create` 或调用 DG/Lake/Tushare。
7. 不在 ops dispatcher、worker 或 action catalog 中实现 Heat 公式或直接 import `src.biz`。
8. 不新增板块专用数据库账号、DSN、engine 或环境变量；Web/Heat 复用现有应用连接，DG hierarchy 复用现有 prod write resource，但各执行链只能访问本文规定的对象。
9. 不继续向已超过 400 行的 `MarketOverviewPage.tsx` 堆叠板块交互状态。

---

## 2. 当前代码审计

### 2.1 当前调用链

```text
MarketOverviewPage
  -> useSectorOverviewController
  -> fetchMarketSectorOverview
  -> GET /api/v1/wealth/market/sector-overview
  -> MarketSectorOverviewQueryService
  -> SectorOverviewStateQuery
  -> SectorHierarchyQuery / SectorMetricsQuery / SectorHeatQuery
  -> EffectiveAStockPoolQuery / SectorMemberQuery
  -> core_serving Prod tables

MarketSectorOverviewResponse
  -> useSectorOverviewController status/selection state
  -> SectorOverviewPanel
  -> current generic Workspace / RankCard / DetailPanel
```

### 2.2 后端差距

| 当前文件 | 已有实现 | 审计确认的未完成项 |
|---|---|---|
| `src/biz/api/wealth/market/sector_overview.py` | 严格 view/rank/selection 参数与同一路由 V2；后端默认/显式日期正反例已通过 | Slice 11 前端默认请求已停止附带页面日期，仅 URL 显式选日时传值 |
| `src/biz/schemas/wealth/market/sector_overview.py` | 已拆分三类 view-specific rank DTO，旧 `SectorRankItemDto` 已删除 | Slice 11 前端三类类型已对齐并清零旧通用业务类型 |
| `effective_a_stock_pool_query.py` / `sector_heat_source_query.py` | 两条链均显式读取并以 `close + pct_chg` 判定有效行情；`close` 已进入 Heat canonical source hash | v2 60 日生产回放已由 Slice 12 完成（A02 生产部分） |
| `sector_member_query.py` | 成员 Top5 展示名严格取同日 `dc_member.name`，security 异名反例通过 | 无 |
| `sector_overview_query_service.py` | 行业/概念 TopN 截断前排除 null；地域 31 项 null 置底；默认/显式日期语义已区分 | Slice 11 前端已按 view-specific 事实消费 |
| `sector_metrics_query.py` / 状态归并 | 以三来源候选并集识别 daily/index/moneyflow/member 缺行并降级 PARTIAL；合法无领涨保持 READY | Slice 11 已实现保留可用事实的状态骨架和无领涨文案 |
| Heat config/contract tests | 配置升为 `2.0.0 / concept-heat-eod-v2`，批准 hash 门禁阻止同版本语义漂移，v1 跨版本趋势返回 UNKNOWN | 生产回放已由 Slice 12 完成 |
| `tests/web/test_wealth_market_sector_overview_api.py` | 已覆盖 A01-A07 后端固定列、全部排序字段、来源缺失、null、名称、日期、ERROR、有效行情与无子级正反例 | Slice 13 后端真实路由矩阵已通过 |

### 2.3 前端差距

| 当前文件 | 已有实现 | 审计确认的未完成项 |
|---|---|---|
| `MarketOverviewPage.tsx` | 页面只装配 feature，并仅将 URL 显式 `tradeDate` 传给板块 controller | 无；首页其它模块未改 |
| `useSectorOverviewController.ts` | Tab 独立状态、abort/request id、timeout/retry；PageStatus 穷尽映射，未知值 fail closed | Slice 13 三 view×七状态矩阵已通过 |
| `api/marketSectorOverviewApi.ts` | 已拆为 view-specific Industry/Concept/Region rank/detail 类型；旧通用业务类型清零 | 无 |
| `SectorOverviewPanel.tsx` 与三个 workspace | 正式 header/tabs/toolbar、三个独立 rank/detail、同尺寸 skeleton/overlay、Partial/Delayed 保留可用事实 | Slice 15 正式像素尚未验收 |
| `market-overview-page.css` | 1600px 视口下模块为 `1564 × 680`；行业 3 列、概念/地域 930/600 双区、七行内部滚动已落地 | 普通 UI `<=2px` 差异待 Slice 15 |
| `market-overview-sector-overview-real-api.test.tsx` | 36 项真实响应专项覆盖结构、固定列、20 日断点、地域分布、导航、无领涨、默认/显式日期、stale、403、ERROR/未知、超时、三 view×七状态、长文本/null/大金额、滚动、键盘与刷新无 mock fallback | 正式像素留待 Slice 15 |

### 2.4 CodeGraph 影响面

CodeGraph 已覆盖 API/前端板块链，并为 Slice 14 补充审计 `SectorHeatTaskExecutor`、`ProbeRuntimeService`、`ScheduleAutomationCapabilityResolver` 的影响面；结合当前代码继续追到 `OperationsScheduleService`、`OperationsScheduler`、CLI 和 app worker factory。现有通用 ProbeRule 明确只绑定 dataset action，不能直接拿来做 Heat maintenance readiness；因此本 LLD 选择 schedule service 专用条件分支和 app scheduler factory。`index-detail`、turnover、money-flow 等页面契约不受影响。共享边界结论：

1. `foundation` 新增两张 serving ORM。
2. `lake_console/orchestrator` 只新增 hierarchy serving 发布链，不新增 Heat 定义。
3. `biz` 继续只依赖 `foundation`。
4. `ops` 增加 Heat TaskRun 意图、抽象执行端口和 Heat readiness 调度端口，但不依赖 biz。
5. `app` 增加 worker/scheduler 装配适配器，但不增加业务规则。
6. 现有 app worker factory、Heat executor 注入和双 Session 边界继续成立；Slice 14 新增 scheduler factory，影响 schedule/capability/runtime/CLI 测试，但不修改 Heat 公式、API 或前端。

### 2.5 2026-08-13 文档对账审计问题台账

本节是 Slice 9-17 的唯一缺口入口。Slice 10 仅完成 A01-A08 的后端代码/测试部分；同一问题若还要求前端或生产 Heat v2 证据，整体状态仍为 `OPEN`。严重度定义：`阻断` 表示不得认定 V2 交付完成，`高` 表示会造成事实、状态或主要交互错误，`中` 表示验收、文档或运维证据不完整。

#### 2.5.1 后端、数据语义与契约

| ID | 严重度 | 冻结口径 | 审计时实现与偏差 | 修正要求 | 关闭证据 | 修正 Slice |
|---|---|---|---|---|---|---|
| A01 | 阻断 | 行业排行展示当前排序主指标与领涨股；正式概念排行同一行展示热度等级、趋势、热度分、日变化、涨跌幅和领涨股；地域同一行展示上涨/成分、主力净流入、涨跌幅和领涨股 | 后端/前端共用一个 `SectorRankItem`，只有 `primaryMetric + leader + heat`；该结构只勉强覆盖行业，无法表达正式概念/地域固定多列 | 破坏性拆为 view-specific rank DTO：行业保留显式 `primaryMetric`，概念/地域返回稳定固定事实字段；前端不得按当前排序自行拼装；不保留通用旧别名 | 三类 schema、真实路由、前端真实 API 测试逐列断言；旧通用不足契约静态清零 | 10、11 |
| A02 | 高 | 有效报价必须同时满足同日 `equity_daily_bar.close IS NOT NULL` 与 `pct_chg IS NOT NULL` | `EffectiveAStockPoolQuery` 与 Heat `SectorHeatSourceQuery` 只读取/校验 `pct_chg`；当前生产窗口未出现 `pct_chg` 非空而 `close` 为空，只能证明现存结果暂未受影响，不能证明实现合规 | 两条查询链共享同一 `close + pct_chg` 资格语义；close 缺失必须计入缺行情并影响覆盖/有效性。新增 `close` 会改变 Heat canonical 来源字段集合，必须升级 `scoreVersion` 后重放，不得沿用 v1 | close-null/pct-nonnull 负例同时覆盖详情和 Heat；真实只读样本复核；新版本 60 日 PLAN/APPLY/read-back/幂等重放 | 10、12 |
| A03 | 高 | 成分股展示名严格来自同日 `dc_member.name` | `SectorMemberQuery` 当前使用 `Security.name`，与批准来源不一致 | 查询显式选择 `dc_member.name`；不得以 security 名称回退或补齐 | 同一股票两表名称不同的反例证明响应取 dc_member；空名称按契约返回，不偷偷 fallback | 10 |
| A04 | 高 | 行业 Top5、概念 Top20 的排名字段为 null 时不参与排名 | 行业 `_rank_nodes(... )[:5]` 仅把 null 放末尾；概念 CHANGE/FLOW 也可能把 null 截入榜单 | 排序前过滤当前排名指标 null；稳定 tie-break 继续按冻结规则；地域固定 31 项的 null 置底语义单独保留，不混用 TopN 过滤 | 行业不足 5、概念不足 20 和 null 混排负例；地域 31 项 null 置底正例 | 10 |
| A05 | 高 | 当前 view 的必需来源缺失必须进入 PARTIAL/DELAYED/EMPTY/ERROR 规定状态，不能伪装 READY | 查询已有 `has_moneyflow`，但状态归并主要检查 index；板块资金流缺失可能仍返回 READY | 建立 view×字段来源矩阵；资金流缺失、Heat INVALID、成员缺失、领涨缺失分别按文档状态归并，不把合法无领涨误判异常 | 每种来源单独缺失的真实路由负例；状态、issues、仍可用字段同时断言 | 10 |
| A06 | 阻断 | 不传 `tradeDate` 使用最新公共完成交易日；只有用户显式选日才执行精确日期语义 | 首页把页面上下文日期无条件传入；后端收到日期后若来源公共日不等于请求日直接 EMPTY，可能把默认来源延迟错误表现为空 | controller 区分默认日期和用户显式日期；默认请求不伪造成显式选日；后端继续严格区分默认/显式路径 | 默认来源落后一日返回 DELAYED/最近完成日；显式无完整事实返回 EMPTY；请求参数断言 | 10、11 |
| A07 | 阻断 | `ERROR` 必须是类型安全且带稳定骨架的终态 | controller 将任意后端状态 lower-case 后强制断言为少数状态；后端 `ERROR` 会形成 TypeScript 声明外的运行时值，并可能丢失 message/骨架 | 用穷尽映射处理所有 PageStatus；未知枚举 fail closed 到 error；不得类型断言掩盖未处理值 | ERROR、未知状态、网络错误、超时、403 分别测试，且均保留固定尺寸 | 11 |
| A08 | 中 | Heat 配置语义或 canonical 来源字段改变时必须升级 `scoreVersion`，历史不同版本不得比较趋势 | 已有 golden/no-lookahead 等测试，但没有足够证据证明“配置内容变化但版本未升”被阻断；A02 明确新增 canonical `close` 字段 | 增加版本升降门禁；本轮 Heat 升级为 `concept-heat-eod-v2`，重新生成 config/source/content hash，禁止与 v1 跨版本计算 delta/trend | 配置/字段变化未升版负例、跨版本趋势 UNKNOWN、v2 同版本幂等正例；60 日回放对账 | 10、12 |

Slice 10 后端关闭记录（2026-08-13）：

| ID | 后端代码/测试结果 | 后续仍需 |
|---|---|---|
| A01 | 三类 rank DTO 已破坏性拆分；真实路由逐字段断言通过；后端旧 `SectorRankItemDto` 清零 | Slice 11 清理前端通用类型并接新字段 |
| A02 | 有效池和 Heat source 同时要求 `close + pct_chg`；`close` 进入 canonical source hash；close-null 负例通过。生产 v2 PLAN `8208`、APPLY `8210`、read-back 和重放 `8213` 已覆盖 60 日，逐日来源/内容 hash 0 差异 | 生产事实部分完成；整体随最终对账关闭 |
| A03 | 成员名改取同日 `dc_member.name`；与 `Security.name` 异名的真实路由反例通过 | 无 |
| A04 | 行业/概念 null 在 TopN 前排除；地域固定 31 项保留并 null 置底 | Slice 11 前端消费与展示 |
| A05 | daily/index/moneyflow/member 缺行分别返回 PARTIAL 和明确 `SO_*`；合法无领涨返回 READY + `leader=null` | Slice 11 状态骨架与文案 |
| A06 | 后端默认请求使用最近公共完成日并可返回 DELAYED；显式开放日无完整事实返回 EMPTY，且不附加误导性 DELAYED issue | Slice 11 停止把默认请求伪装成显式日期 |
| A07 | 后端 `PageStatusValue` 继续穷尽 `READY/DELAYED/PARTIAL/EMPTY/ERROR`；未知值被 Pydantic 拒绝，层级错误稳定返回 ERROR | Slice 11 完成前端穷尽映射、403/超时/网络状态骨架 |
| A08 | 配置升为 `2.0.0 / concept-heat-eod-v2`；批准语义 hash 门禁阻止同版本参数漂移；v1 前序与 v2 不计算 delta/trend；60 日回放和 0 写入重放通过 | 生产事实部分完成；整体随最终对账关闭 |

#### 2.5.2 Figma、前端结构与交互

| ID | 严重度 | 冻结口径 | 当前实现与偏差 | 修正要求 | 关闭证据 | 修正 Slice |
|---|---|---|---|---|---|---|
| A09 | 阻断 | 正式节点 `538:517`、行业 `538:520`、概念 `538:521`、地域 `571:516` 均为 `1564 × 680`；三工作台使用各自结构 | 当前 `SectorOverviewPanel` 使用通用 `Panel`、通用 `SectorRankCard`、通用 `DetailPanel`；模块 DOM 层级和视觉结构不是正式 Figma | 不一次性重建整页；只重构板块模块，拆出正式 header、tabs、ranking toolbar、三个 workspace、三个 rank item 和三个 detail 组合；其余首页模块不动 | 节点结构对照表、三工作台浏览器截图、首页回归截图与 DOM/CSS 结构审查 | 9、11、15 |
| A10 | 阻断 | 行业每级 5 行；概念/地域单列 7 行可视并内部滚动 | 当前概念/地域复用两列卡片网格，约可同时展示 14 项，不是正式表格行和七行视窗 | 行业三列采用 Figma 固定列宽；概念/地域独立单列表头与行；列表容器表达固定表头、七行可视区和内部滚动 | 首屏精确 7 行、滚动后剩余行、固定表头、键盘/焦点测试；截图尺寸不变 | 11、13、15 |
| A11 | 阻断 | 行业/概念/地域详情各有批准的四指标结构；概念额外 Heat 历史，地域额外上涨/下跌分布 | 当前统一展示六个通用数字，且把停牌/覆盖率等质量字段放成正式 Figma 未批准的主卡 | 建立 view-specific detail metric layout；只展示该 view 批准字段，辅助质量信息只能放已批准位置；地域保留两段 breadth | 三视图四指标字段映射、地域分布、概念历史和无多余主卡断言 | 11、13 |
| A12 | 高 | 热度等级只显示沸腾/高热/活跃，低于 60 不显示；趋势为升温/平稳/降温，等级和趋势是独立标签 | 当前 `STABLE` 显示“稳定”，`NONE` 显示 `--`，且等级/趋势合成一个 badge | 分离 `HeatLevelBadge` 与 `HeatTrendBadge`；严格 enum 映射，不从 score/delta 推导；NONE 不渲染等级标签 | 全枚举正例、未知枚举负例、NONE 不存在标签的 DOM 断言与截图 | 11、13 |
| A13 | 阻断 | 产品冻结概念 Heat 历史为最近 20 个已发布交易日；无效点保留日期并断开 | Slice 9 前正式 Figma 只有 7 个历史槽；当前代码虽循环 20 点，但 null 被最小高度柱显示，且缺少范围/变化表达 | Figma 已在 Slice 9 冻结为 20 日；代码仍须按新稿实现 20 点、日期顺序、无效断点和批准的当前值/变化表达 | Figma 节点属性复核已完成；20 点/断点 DOM 测试、INVALID 中段截图与 API 对账仍待 Slice 11/15 | 9、11、15 |
| A14 | 高 | 领涨股和成分股名称进入股票详情；无领涨显示“暂无领涨股” | 排名卡整体按钮导致领涨股点击只选择板块；详情领涨股为普通文本；缺失值显示 `--` | 板块选择与股票跳转使用独立可访问交互目标，禁止嵌套 button；领涨和成员统一调用批准的股票详情导航 | 点击传播、键盘激活、无领涨文案、成员/领涨路由参数测试 | 11、13 |
| A15 | 阻断 | Loading、Ready、Partial、Delayed、Empty、Error、Forbidden 共用稳定页面骨架；普通 UI 不因状态换位 | Loading 使用通用 `SkeletonBlock`，Empty/Error/Forbidden 是简单居中层，不包含三工作台对应表头/行/详情骨架 | 为三个 view 构建相同尺寸 skeleton；状态 overlay 覆盖而不替换 grid；refreshing 保留旧数据；Partial/Delayed 保留可用事实 | 各 view×状态同尺寸截图、容器尺寸断言、无布局跳动；ERROR 同时覆盖 A07 | 11、13、15 |
| A16 | 阻断 | 用户最新批准范围不新增板块详情页/路由；Figma 与文档必须先一致 | Slice 9 前正式 Figma 含三个未批准的板块详情路由控件，交互说明也把板块名定义为详情入口 | Slice 9 已移除三个控件；Slice 11 前端仅保留板块选择/联动和股票详情导航，无板块详情入口 | Figma/文档节点复核、前端静态扫描及导航负例已通过；最终关闭仍待 Slice 17 对账 | 9、11、17 |

#### 2.5.3 测试、性能、文档与发布治理

| ID | 严重度 | 冻结口径 | 当前实现与偏差 | 修正要求 | 关闭证据 | 修正 Slice |
|---|---|---|---|---|---|---|
| A17 | 阻断 | 自动化必须覆盖三工作台、六态、长文本/null、INVALID、七行滚动、跳转、禁止项和真实 API 字段 | 当前前端专项只有 5 个 jsdom 用例，主要断言文字/数量；没有证明正式结构、全部状态、长文本、断点、跳转和像素 | 先建立可执行验收矩阵，再补后端正反例、前端真实 API 与浏览器用例；每个 A01-A16 至少对应一个正例和一个必要反例 | 问题 ID 到测试 ID 映射为 100%，规定命令全部通过 | 10、13 |
| A18 | 阻断 | 发布前必须完成同机房 P50/P95/P99、SQL/payload、三视图和全部状态像素、首页无漂移、监控与回滚证据 | M2 Gate 的性能和视觉表为空；已部署前没有完成正式截图/像素签字；单元测试、typecheck、build 被错误当成交付依据 | 部署候选版本后执行同窗口真实首页验收；普通 UI `<=2px`；记录 `SO_*`、Heat 覆盖率、回滚演练；任一缺失不得关闭 | 完整性能表、截图基线/差异图、监控查询、回滚记录和角色签字 | 15、16、17 |
| A19 | 阻断 | LLD/M2 状态必须反映事实；固定命令必须可归因、可执行 | 旧文档把 Slice 6/7 写成完成并把剩余项缩成截图/性能；全目录 `ruff check src/orchestrator/defs ...` 当前产生 487 个既有错误，而 sector hierarchy 文件级 Ruff 通过 | 保留 Slice 0-5 事实，撤销 Slice 6-8 验收结论；将 Ruff 门禁收窄为本需求文件并另记全目录基线债务；所有完成状态以证据表为准 | 文档完整性、diff check、问题台账与 M2 Gate 对账；不得存在“未勾选却写完成” | 9、13、17 |

#### 2.5.4 正式设计节点事实清单（Slice 9 基线）

| 节点 | 当前已审计结构 | LLD 固定用途 | 当前冲突/动作 |
|---|---|---|---|
| `538:517` | 板块速览 V2 正式总览，`1564 × 680` | 模块外框、header、tabs、日期与工作区基线 | Slice 11 已落地正式模块结构；像素待 Slice 15 |
| `538:520` | 行业：左侧 3 列层级区约 1008px，右侧详情约 522px；每列最多 5 行 | Industry workspace 与四指标详情 | Slice 11 已落地；真实三级直属只有 4 行时不伪造占位事实 |
| `538:521` | 概念：左侧约 930px、右侧约 600px；单列 7 行表格；Heat 与详情 | Concept workspace、Heat badge/history 与成员 | Slice 11 已落地 20 日空槽断点；生产 v2 Heat 已由 Slice 12 发布 |
| `571:516` | 地域：左侧约 930px、右侧约 600px；单列 7 行表格；详情含两段 breadth | Region workspace 与上涨/下跌分布 | Slice 11 已落地，真实 31 行内部滚动与分布已验收 |
| `538:522` | Tab 记忆、三级联动、排序范围、状态骨架、名称导航说明 | 正式交互事实源 | Slice 11 已完成结构和核心状态验收；Slice 13 已完成全矩阵自动化 |
| `554:516` | Heat 标签/趋势与量化说明 | Heat 文案、标签和历史表现 | 必须与 20 日、NONE 隐藏、STABLE=平稳一致 |

Slice 9 执行后事实：正式根仍为 `1700 × 3242` 且子节点顺序不变；行业、概念、地域仍分别为 `1564 × 680`，交互契约为 `1564 × 360`，Heat Model 为 `1564 × 520`。概念节点 `543:540` 保持 `556 × 42`、6px 间距并由 7 根柱扩为 20 个日期槽；三个工作台的“进入××行情”控件已删除；`538:522` 已补齐 view-specific 字段、长文本/null、无领涨、20 日 INVALID 断点与 Ready + 六种非正常状态口径。完整 before/after 与属性清单见 `figma-pixel-artifacts/20260813-sector-overview-v2-slice9/`。

2026-08-16 Heat 坐标表达后续修正：上述 `556 × 42` 是 Slice 9 当时的柱体基线，当前正式稿以本条为准。概念 Heat 容器 `543:536` 调整为 `576 × 108`，绘图区 `543:540` 调整为 `556 × 55`，原 20 根柱节点保留并按 `0..100 -> 0..42px` 重校高度；新增柱顶值节点 `699:2..699:21`，均与对应柱水平居中且垂直间距为 `3px`；新增日期容器 `698:2`（`556 × 12`）及日期节点 `699:23..699:27`，分别对齐第 `1/5/10/15/20` 槽。概念正式画板 `538:521` 仍为 `1564 × 680`，详情区 `541:546` 仍为 `600 × 540`，内部内容底边为 `448px`，无裁剪或溢出。

普通 UI 以节点树与实际属性验收，不得只看截图；图表绘图区内部可保留绝对定位，页面骨架、tabs、toolbar、列表、详情指标卡和状态骨架使用正常流/Auto Layout 等价结构。Figma 修改必须先保存同尺寸截图，按节点逐个修改并立即复核，不能一次性重建整个板块区域。

### 2.6 审计确认仍成立、不得重复开发的范围

1. Alembic、两张 serving 表和既有连接复用设计继续成立；后续若不新增迁移，不得为了本轮 UI 修正另建表或账号。
2. DG 只发布 hierarchy，生产 496 行与 31/128/337 层级计数继续成立；不得新增 DG Heat、Gold、sensor、动态分区或 history CLI。
3. Prod-native Heat 60 日 PLAN/APPLY/幂等重放证据继续成立，但 A02/A08 修正后必须判断是否需要新 `scoreVersion` 和重新回放，不能直接沿用旧内容结论。
4. `biz/ops/app` 依赖方向、Heat/Ops 双 Session 和来源表只读边界继续成立。
5. 已实现的三级联动、Tab 独立状态、AbortController/request-id stale 防护、服务端 selection 修正可以复用，但必须纳入修正后回归；不得因前端重构而退化。

---

## 3. 目标文件结构

```text
src/foundation/models/core_serving/
  wealth_sector_hierarchy.py
  wealth_sector_heat_daily.py
  __init__.py
src/foundation/models/all_models.py
alembic/versions/20260813_000134_add_wealth_sector_overview_serving.py

lake_console/orchestrator/src/orchestrator/defs/
  assets/wealth_sector_hierarchy_prod_core.py
  prod_db/wealth_sector_hierarchy.py

src/biz/
  api/wealth/market/sector_overview.py
  schemas/wealth/market/sector_overview.py
  queries/wealth/market/sector_overview/
    sector_overview_state_query.py
    sector_hierarchy_query.py
    sector_metrics_query.py
    sector_heat_query.py
    sector_heat_source_query.py
    effective_a_stock_pool_query.py
    sector_member_query.py
    sector_overview_query_service.py
  services/wealth/market/sector_overview/
    sector_heat_config_resolver.py
    sector_heat_contract.py
    sector_heat_materialization_service.py
    sector_heat_replay_planner.py
    sector_heat_models.py
    sector_selection_resolver.py
    sector_overview_status_resolver.py
    sector_overview_exception_builder.py

src/biz/services/wealth/config/
  definitions/sector_overview.cn_a.v1.json
  strategy_config_models.py
  strategy_config_registry.py

src/ops/
  action_catalog.py
  runtime/maintenance_executor.py
  runtime/heat_readiness.py
  runtime/scheduler.py
  runtime/task_run_dispatcher.py
  runtime/worker.py
  services/sector_heat_upstream_readiness_service.py
  services/operations_schedule_service.py
  services/schedule_automation_capability_resolver.py

src/app/
  runtime/sector_heat_task_executor.py
  runtime/sector_heat_readiness_evaluator.py
  runtime/ops_scheduler_factory.py
  runtime/ops_worker_factory.py

src/cli.py
src/cli_parts/ops_handlers.py

tests/
  test_extended_models.py
  test_foundation_table_model_registry.py
  test_wealth_sector_serving_constraints.py
  test_wealth_sector_serving_migration.py
  test_wealth_sector_heat_contract.py
  test_wealth_sector_heat_materialization_service.py
  test_wealth_sector_heat_task_execution.py
  test_wealth_sector_database_access_boundaries.py
  test_cli_ops_runtime.py
  test_sector_heat_readiness_evaluator.py
  web/test_wealth_sector_heat_automation.py

wealth/src/features/market-overview/sectors/
  SectorOverviewPanel.tsx
  SectorOverviewTabs.tsx
  SectorRankingToolbar.tsx
  useSectorOverviewController.ts
  model/sectorOverviewViewModel.ts
  api/marketSectorOverviewApi.ts
  industry/IndustryHierarchyWorkspace.tsx
  industry/IndustryLevelColumn.tsx
  industry/IndustryRankItem.tsx
  concept/ConceptHeatWorkspace.tsx
  concept/ConceptRankItem.tsx
  concept/ConceptDetailPanel.tsx
  concept/HeatLevelBadge.tsx
  concept/HeatTrendBadge.tsx
  concept/HeatHistoryChart.tsx
  region/RegionRankingWorkspace.tsx
  region/RegionRankItem.tsx
  region/RegionDetailPanel.tsx
  region/RegionBreadthBar.tsx
  detail/IndustryDetailPanel.tsx
  detail/SectorMetricGrid.tsx
  detail/SectorLeaderStock.tsx
  detail/SectorMemberStockList.tsx
  states/SectorWorkspaceSkeleton.tsx
  states/SectorStateOverlay.tsx
```

文件名可因最近目录命名规则做等价收敛，但职责不得合并回 handler、页面、通用 `SectorRankCard`、通用六指标详情或单个巨型 service。三个 workspace 可以复用无业务语义的 primitives，不得复用会抹平正式 Figma 列结构的业务组件。

---

## 4. 持久化 LLD

### 4.1 `WealthSectorHierarchy`

ORM：`src/foundation/models/core_serving/wealth_sector_hierarchy.py`。

| 字段 | SQLAlchemy | 约束 |
|---|---|---|
| `sector_code` | `String(16)` | PK |
| `sector_name` | `String(128)` | not null |
| `industry_level` | `SmallInteger` | not null, check 1..3 |
| `industry_level_name` | `String(32)` | not null |
| `parent_sector_code/name` | `String(16/128)` | 一级同时为空，二三级同时非空 |
| `root_sector_code/name` | `String(16/128)` | not null |
| `hierarchy_path` | `String(512)` | not null |
| `is_leaf` | `Boolean` | not null |
| `display_order` | `Integer` | not null, >=0 |
| `baseline_version` | `String(128)` | not null |
| `source_received_date` | `Date` | not null |
| `code_reference_trade_date` | `Date` | not null |
| `published_at` | `DateTime(timezone=True)` | not null |

索引：

1. `(industry_level, display_order, sector_code)`。
2. `(parent_sector_code, industry_level, display_order, sector_code)`。
3. `(root_sector_code, industry_level, display_order, sector_code)`。

表内不存 JSON children；父子路径由规范字段表达。应用读取后可按 `baseline_version` 构建不可变内存索引。

### 4.2 `WealthSectorHeatDaily`

ORM：`src/foundation/models/core_serving/wealth_sector_heat_daily.py`。

字段、精度、枚举和可空规则沿 implementation design 第 4.2 节；补充数据库约束：

1. PK `(trade_date, sector_code)`。
2. `heat_status IN ('VALID','INVALID')`。
3. `heat_level IN ('BOILING','HOT','ACTIVE','NONE')`。
4. `heat_trend/raw_heat_trend IN ('HEATING','STABLE','COOLING','UNKNOWN')`。
5. `VALID` 必须有五分量、`base_heat_score/rank`、`heat_score/rank`，且 `invalid_reason IS NULL`。
6. `INVALID` 必须有固定 `invalid_reason`，不可计算分数允许为空；不得用 0 代替缺失。
7. 分数范围、计数非负、`suspended_count <= member_count`、`quote_eligible_count = member_count - suspended_count`、`missing_quote_count = quote_eligible_count - valid_quote_count`。
8. `source_dates_json` 是只读证据，不作为查询排序字段。
9. `config_hash/source_hash` 固定为 64 位小写十六进制 SHA-256；`source_row_counts_json` 必须包含每个输入来源的有界读取行数。

索引：

1. `(trade_date, heat_score DESC, sector_code)`。
2. `(trade_date, heat_delta_1d DESC, sector_code)`。
3. `(sector_code, trade_date DESC)`。

### 4.3 模型登记

实现必须同时修改：

1. `src/foundation/models/core_serving/__init__.py`。
2. `src/foundation/models/all_models.py`。
3. `tests/test_extended_models.py`：表名、schema、PK、数值精度、check/index。
4. 如表卡注册依赖自动扫描，增加 table registry 测试，不能仅凭 import 成功判定完成。

### 4.4 Alembic

1. 本需求 revision 创建时本地与生产均为单 head `20260812_000133`，因此已正确接为 `20260813_000134`；部署后复核仓库与生产当前单 head 均为 `20260813_000135`。任何后续 revision 仍必须重新读取真实 head。
2. upgrade 顺序：create hierarchy -> constraints/indexes -> create heat -> constraints/indexes -> 给既有 `lake_raw_writer` 增加 hierarchy 单表 `SELECT/INSERT/DELETE`；不得创建 login、密码或新连接配置。
3. migration 不做 `DROP TABLE IF EXISTS`、数据回填、外部访问或来源表 DML。
4. downgrade 仅删除本次两张表，先 heat 后 hierarchy。
5. SQLite 单测若不支持某些 PostgreSQL check 表达式，测试数据库兼容只能在测试装配层解决，不能弱化生产约束。

### 4.5 现有连接复用与事务边界

本需求不新增数据库账号、DSN、engine 或板块专用环境变量。publisher、materializer、reader 是逻辑职责，不是三个数据库身份。

| 逻辑职责 | 复用的当前连接 | 代码访问范围 |
|---|---|---|
| migration | 现有 Alembic `DATABASE_URL` | 创建两表、约束和索引；只给既有 `lake_raw_writer` 增加 hierarchy 单表授权 |
| DG hierarchy publisher | `ProdPostgresWriteResource` / `PROD_POSTGRES_WRITE_*`，当前账号 `lake_raw_writer` | 仅对 `wealth_sector_hierarchy` 执行 `SELECT/DELETE/INSERT` |
| Heat materializer | `DATABASE_URL` / `SessionLocal` 新开的 business session | 只读冻结的 prod 来源表；仅对 `wealth_sector_heat_daily` 执行 `SELECT/DELETE/INSERT` |
| Wealth Web reader | `DATABASE_URL` / 现有 `get_db_session` | 只读取 V2 所需来源、hierarchy 与 Heat 表 |

1. migration 不创建 login 或 secret；只对既有 `lake_raw_writer` 执行 `GRANT SELECT, INSERT, DELETE ON core_serving.wealth_sector_hierarchy`，不新增 `UPDATE/CREATE/TRUNCATE`，也不改变该账号其它表的既有授权。
2. Web V2 handler 继续使用通用 `get_db_session`，不得新增 `WEALTH_SECTOR_READ_DATABASE_URL` 或板块专用 engine。
3. Heat executor 每个日期从现有 `SessionLocal` 工厂新开一个 `heat_session`；Ops worker 的 `ops_session` 与 `heat_session` 可以使用同一 DSN/账号，但不得共享 Session、connection 或 transaction。
4. Heat 业务提交完成后，Ops 状态写入失败不得回滚 Heat；Heat 回滚后，Ops 使用自己的事务记录失败。测试必须覆盖两个方向。
5. DG hierarchy 沿用现有 `ProdPostgresWriteResource` 的成功 commit、异常 rollback 语义，不新增 hierarchy resource 或 `WEALTH_SECTOR_HIERARCHY_POSTGRES_*`。
6. 应用现有数据库账号权限较宽，因此 Heat/Web 的“只读/只写”是 DAO、固定 SQL、显式字段和事务测试约束；全站数据库账号拆分不扩大进本需求。
7. 现有 URL/password 仍不得写入日志、TaskRun 或异常文本；这是通用 secret 规则，不是新增专用连接的理由。
8. PostgreSQL 集成测试验证两表约束、DG 既有账号对 hierarchy 的精确授权、事务回滚和 read-back；静态/单元测试验证 Heat/Web/DG 的 SQL 目标范围、Web 无 DML、运行时代码无 DDL/`TRUNCATE`。

---

## 5. DG hierarchy 与 prod-native Heat LLD

### 5.1 DG hierarchy 发布

`prod_core_wealth_sector_hierarchy` 是本需求唯一 DG asset：

1. 输入固定为 `/Volumes/datasource/data_lake/silver/board/dc_industry_hierarchy/full/part-000.parquet`；沿用现有单文件、无分区、手工 seed 身份。
2. 发布前调用层级文件 contract，验证 schema、唯一 `sector_code`、496 行、31/128/337、父子闭包和版本。
3. 复用现有 `ProdPostgresWriteResource` / `PROD_POSTGRES_WRITE_*` 和 `lake_raw_writer`；在单事务中 `DELETE + INSERT + read-back`，不使用 `TRUNCATE`。
4. read-back 验证 496、31/128/337、父子闭包、版本和 canonical hash，不一致回滚。
5. 显式人工运行或纳入部署步骤；不新增自动重建 sensor，也不与 Heat 任务建立依赖。

### 5.2 prod Heat 输入适配与范围

| 事实 | prod 表 | 范围 |
|---|---|---|
| 交易日 | `core_serving.trade_calendar` | `exchange='SSE' AND is_open=true`；解析 `t`、25 日 warm-up、5 日复算窗 |
| 板块目录/领涨 | `core_serving.dc_index[t-5..t]` | 逐日概念集合；目标日同时提供领涨事实 |
| 板块日线 | `core_serving.dc_daily[t-25..t]` | 已完成交易日窗口 |
| 板块成员 | `core_serving.dc_member[t-5..t]` | 仅概念代码 |
| 资金流 | `core_serving.board_moneyflow_dc[t-9..t]` | 复算前 5 日基础热度各自的 5 日窗口；概念、非空 `ts_code` |
| 股票资格 | `core_serving.security_serving` | 按每个计算日投影 |
| 停牌 | `core_serving.equity_suspend_d[t-5..t]` | `suspend_type='S'` |
| 股票日线 | `core_serving.equity_daily_bar[t-5..t]` | 仅相关成员 |
| 涨停 | `core_serving.equity_limit_list[t-5..t]` | `limit_type='U'`、相关成员 |
| 历史 Heat | `core_serving.wealth_sector_heat_daily` | 前序最多 2 个连续且 `scoreVersion/configHash` 相同的成功交易日；仅 delta/trend，跨版本/断点不比较 |

`SectorHeatSourceQuery` 使用 ORM/显式 SQL，一次返回 `SectorHeatSourceBundle`：交易日集合、逐来源行、逐来源日期、逐来源行数和 canonical source hash。禁止 `SELECT *`、自然日替代、逐概念 N+1、Parquet、DuckDB、DG resource 或 Tushare。

hash 规范固定：

1. `config_hash = SHA256(canonical_json(strict_strategy_payload))`，canonical JSON 使用 UTF-8、键排序、稳定十进制表示且不含 envelope 的更新时间/操作者。
2. `source_hash` 依次编码查询边界和每张表实际参与计算/资格判定的显式字段；按表名、交易日、表主键或文档冻结的稳定键排序，空值使用独立 token。
3. `created_at/updated_at/calculated_at`、数据库物理顺序、查询耗时和摄取批次等不改变业务结果的元数据不得进入 source hash；来源字段集合变化必须升级 `scoreVersion`。
4. `content_hash` 对候选 Heat semantic rows 按 `(trade_date, sector_code)` 排序后计算，排除 `calculated_at`；TaskRun 保存该 hash，表 read-back 现场复算，不新增第二份事实表。

完成性证据边界：

1. app `SectorSourceCompletionEvidenceProvider` 用独立 Ops read session 查询已有 TaskRun/日期完整性事实，输出中立 DTO：`dataset_key, trade_date, status, evidence_type, evidence_id, evidence_hash`。
2. biz `SectorHeatSourceBundle` 可接收该 DTO，但不得 import ops ORM；证据只参与来源就绪判定，不能提供或覆盖任何行情、成员、资金、停牌或涨停数值。
3. 非空来源仍按 prod 行、唯一键和覆盖校验；`equity_limit_list/equity_suspend_d` 等空集只有在对应日期存在成功完成证据时才解释为合法 0，否则整日进入 gap ledger。
4. 合法零行证据的 dataset/date/status/id/hash 进入 plan snapshot 和 `source_hash`；状态变化或证据缺失触发 `HEAT_PLAN_DRIFT/SOURCE_NOT_READY`，不得静默沿用旧证据。
5. provider 的 Ops read session、外层 TaskRun write session 和 Heat business session 三者职责分开；任一观测写失败不得影响已提交 Heat。

### 5.3 `EffectiveAStockPool` 单一语义

对每个 `calculation_date + sector_code`：

```text
sourceMembers = DISTINCT dc_member.con_code

eligibleMembers = sourceMembers
  INNER JOIN security_serving ON ts_code = con_code
  WHERE security_type = 'EQUITY'
    AND curr_type = 'CNY'
    AND list_status IN ('L', 'D')
    AND list_date <= calculation_date
    AND (delist_date IS NULL OR delist_date > calculation_date)

suspendedMembers = eligibleMembers
  INNER JOIN equity_suspend_d ON same ts_code/date AND suspend_type = 'S'

quoteEligibleMembers = eligibleMembers - suspendedMembers
validQuoteMembers = quoteEligibleMembers INNER JOIN equity_daily_bar ON same ts_code/date
missingQuoteMembers = quoteEligibleMembers - validQuoteMembers
```

1. Heat 物化与 Web 详情复用同一个 `EffectiveAStockPoolQuery`，不再保留 Lake/PostgreSQL 双 adapter。
2. 固定案例覆盖 B 股、未来上市、退市生效日、全日停牌、复牌、可报价但无日线和重复成员。
3. 六类计数必须由同一关系查询产出，禁止在 Python 用分散计数猜差值。

### 5.4 Heat 配置与纯 contract

1. 在策略配置中心注册 `moduleKey=sectorOverview, market=CN_A, definition_file=sector_overview.cn_a.v1.json`。
2. `SectorOverviewHeatStrategyPayload` 使用 `extra='forbid'`，完整表达五个主权重、价格/广度/资金流/持续性内部权重、窗口、TopN、winsor、等级/趋势/质量阈值和 `scoreVersion`；逐组校验权重和、阈值顺序、正整数窗口/TopN 与覆盖率。
3. `SectorHeatConfigResolver` 只通过 `StrategyConfigService` 读取配置，生成 canonical payload SHA-256；禁止业务模块直接打开 JSON。
4. `SectorHeatContract` 提供纯函数：winsor、平均秩 percentile、线性斜率、五分量、base/final score 与 rank、level、delta 和两日趋势确认。
5. 所有排序最终追加 `sector_code ASC`；配置非法严格失败，不使用代码默认值或旧版本回退。

### 5.5 单日计算、质量和事务发布

`SectorHeatMaterializationService.materialize_trade_date(session, trade_date, expected_plan_hash)`：

1. 用 prod 交易日历解析目标日、25 日 warm-up 和 5 日复算窗口。
2. `SectorHeatSourceQuery` 有界读取全部 prod 输入；结合 app 传入的中立完成性 DTO，验证来源日期、唯一键、概念代码覆盖及合法零行证据。来源整日缺失或零行且无完成证据时阻断该交易日；Prod Raw/Core 一致的局部概念缺行只使该概念因缺少主分量成为 `INVALID`，不得补 0、跨日填充、删除候选或阻断其它概念。
3. 构造逐日有效池与六类计数；复算前 5 日横截面 base rank，不读取未来输入。
4. 使用纯 contract 计算目标日五分量、persistence、final score/rank、level、delta 和 trend。
5. 为当日所有概念生成候选行；质量不足保留 `INVALID + reason`，不伪造 0 分、不补权。
6. 发布前运行内存/SQL contract：schema、状态不变量、来源日期、identity、公式抽样、rank/等级分布、no-lookahead 与有效池恒等式。
7. 在同一业务事务中 `DELETE WHERE trade_date=:date`、批量 `INSERT`、显式列 read-back；比较 semantic `content_hash`、行数、`scoreVersion/configHash/sourceHash/tradeDate`。
8. read-back 不一致或任一质量门禁失败则回滚；成功后提交该日 Heat。来源表全程只读。
9. 返回 `SectorHeatMaterializationResult`：日期、读写行数、有效/无效分布、来源证据、配置/hash、内容 hash、耗时和质量结果。
10. PLAN 的业务 session 以 PostgreSQL `REPEATABLE READ, READ ONLY` 启动；单日发布以 `REPEATABLE READ` 启动，保证来源 bundle、有效池聚合、公式与 source hash 使用同一数据库快照。
11. APPLY/续跑传入 `expected_plan_hash + expected_content_hash`；若重新计算无漂移且现存 semantic content 已等于计划，则返回 `skipped_existing=true` 且不执行 DML。

### 5.6 Ops 执行端口与 app 组合

`src/ops/runtime/maintenance_executor.py` 定义不含 biz 类型的通用端口：

```python
class MaintenanceExecutor(Protocol):
    def plan(self, request: MaintenanceExecutionRequest) -> MaintenanceExecutionPlan: ...
    def execute_unit(self, unit: MaintenanceExecutionUnit) -> MaintenanceExecutionResult: ...
```

dispatcher 语义固定：replay `PLAN` 调用 `plan()` 后只持久化 snapshot 并成功结束，不调用 `execute_unit()`；replay `APPLY` 读取并校验被引用 snapshot 后直接按冻结 units 调用 `execute_unit()`，不重新选择日期；单日 action 构造一个日期 unit。通用端口 DTO 只含 JSON 可序列化标量/映射，不引用 biz 或 ops ORM。

1. `ops.action_catalog` 登记 `maintenance.materialize_wealth_sector_heat_daily` 与 `maintenance.replay_wealth_sector_heat_history`，两者的 `executor_key` 均为 `wealth_sector_heat`。
2. `TaskRunDispatcher` 只按 executor key 调用端口、创建逐日 TaskRunNode、记录进度/结果/issue；不得 import `src.biz` 或读取 Heat 配置。
3. `src/app/.../sector_heat_task_executor.py` 实现该端口：plan 委托 biz replay planner，execute_unit 为每个日期打开独立 business session 并调用 materialization service。
4. `src/app/runtime/ops_worker_factory.py` 是生产 worker 唯一装配入口；向 `OperationsWorker` 注入 executor registry。`src/cli.py` 的 `ops-worker-run/serve` 必须使用该 factory，`src/cli_parts/ops_handlers.py` 接收 callable factory；不得直接构造未装配的 worker。执行器缺失时 Heat action 失败关闭。
5. Ops session 与 business session 不共享 transaction。Heat 已提交后，即使 TaskRun 节点/终态写入失败，也不得回滚 Heat；重试先按 plan/config/source/content hash 做 read-back，再幂等覆盖或确认完成。
6. `biz` 不读写 TaskRun；app 适配器只做参数映射、session 生命周期和结果映射，不实现公式/SQL。
7. replay PLAN snapshot 保存逐日 `source_dates/source_row_counts`、期望行数、config/source/plan/content hash，并增加通用 `snapshot_integrity_hash`；APPLY 必须同时校验成功 PLAN 身份、日期窗、提交的 plan hash 与 snapshot integrity。

ActionDefinition 参数：

| action | 参数 | 规则 |
|---|---|---|
| `maintenance.materialize_wealth_sector_heat_daily` | `trade_date: date` | 人工提交时必填；自动提交时由 Heat readiness window 生成；`manual_enabled=true`，Slice 14 改为 condition-only schedule |
| `maintenance.replay_wealth_sector_heat_history` | `execution_mode: enum(PLAN,APPLY)` | 必填；`schedule_enabled=false` |
| replay PLAN | `start_date/end_date: date` | 必填且连续打开日不少于 60；禁止 `plan_task_run_id/plan_hash`；只写 Ops plan snapshot/issue，不写 Heat |
| replay APPLY | `plan_task_run_id: integer`, `plan_hash: string` | 必填；禁止 start/end；引用同 action、成功 PLAN TaskRun 的 immutable snapshot |

1. ops 负责从所引用 PLAN TaskRun 读取并校验 snapshot；传给 executor 的是通用 plan units/expected hashes，不暴露 ops ORM。
2. app/biz 在每个日期执行前复算配置与来源 hash；与 plan 不一致时以 `HEAT_PLAN_DRIFT` 停止，不自动重规划或跳日。
3. PLAN、APPLY 和单日 action 都使用 TaskRun/TaskRunNode 正式状态链；不另建 Heat run 表。
4. 单日 schedule 仅按第 5.9 节的 condition-only 方式启用；不新增 sensor、代码内隐藏 cron 或无门禁普通 schedule。

### 5.7 60 个有效交易日 plan/apply

1. replay PLAN 从 prod 交易日历选择候选日期，对每一日执行来源日期、数量、唯一键、合法零行、代码覆盖和配置可用性审计；只写 Ops `plan_snapshot_json` 与 issue，不写 Heat。
2. plan 先从 prod 交易日历选择连续至少 60 个 `exchange='SSE' AND is_open=true` 的目标交易日；只有全部必需 prod 来源在日期级通过的日期才是“有效交易日”。日期级失败包括整日缺失、枚举/唯一键非法或零行无完成证据；源站现状导致的单概念特征缺行归入该概念 `INVALID`，不把日期整体移出窗口。不完整日期进入 gap ledger，修复并复核前不得跳过或用窗外日期凑数。
3. plan 固定该连续目标窗、额外 25 个前置 warm-up 交易日、逐日来源证据、预计读写行数、配置版本/hash 和 canonical plan hash。
4. APPLY 必须携带成功 PLAN 的 `plan_task_run_id + plan_hash`，从旧到新逐日执行；每个日期独立 business transaction 和 TaskRunNode。
5. 首个失败日立即停止；续跑根据 plan hash 与 Heat read-back 从最后成功日继续。warm-up 不计入 60 日验收。
6. 当前审计事实写入 plan 说明：`dc_daily/dc_member` 按源站现状判定；`board_moneyflow_dc@2026-07-09` 已补齐但仍需整窗复核。
7. 不提供 DG history CLI，不生成 runless event；历史回放通过正式 Ops TaskRun 提交与观察。

### 5.8 DG Heat 清零静态门禁

仓库扫描必须断言本需求未新增或引用：`gold_wealth_sector_heat_daily`、Heat dynamic partition、Heat asset check、Heat sensor、Heat Gold/Parquet 路径、Heat runless event、Heat history CLI、DG Heat 配置文件或 DG Heat 计算 contract。DG 只允许 hierarchy 发布文件出现在本模块改动清单中。

### 5.9 Heat 每日条件调度 LLD

#### 5.9.1 端口与装配

`src/ops/runtime/heat_readiness.py` 定义不含 biz 类型的窄端口：

```python
@dataclass(frozen=True, slots=True)
class HeatReadinessRequest:
    trade_date: date
    checked_at: datetime

@dataclass(frozen=True, slots=True)
class HeatReadinessResult:
    ready: bool
    reason_code: str
    message: str
    evidence: Mapping[str, object]
    config_version: str | None = None
    config_hash: str | None = None
    source_hash: str | None = None
    plan_hash: str | None = None
    content_hash: str | None = None

class HeatReadinessEvaluator(Protocol):
    def evaluate(self, session, *, request: HeatReadinessRequest) -> HeatReadinessResult: ...
```

1. `ops` 的 `SectorHeatUpstreamReadinessService` 只查询 Ops TaskRun/TaskRunNode，核验同目标交易日的必需工作流节点；不读取来源业务表，不 import biz。
2. `app` 的 `SectorHeatReadinessEvaluator` 先调用上述 Ops 服务，再新开独立 business session，加载 `limit_list_d/suspend_d` 合法零行证据并调用 `SectorHeatMaterializationService.preview_trade_date`。
3. app 只合并两个 readiness 结果和中立证据；公式、有效池、来源 SQL 仍只在 biz。preview session 固定 `REPEATABLE READ, READ ONLY`，无 commit 业务数据。
4. 新增 `build_operations_scheduler(session_factory=...)`，把 evaluator 注入 `OperationsScheduler`；`src/cli.py` 的 `ops-scheduler-tick/serve` 与 `OpsRuntimeCommandService` 改为消费该 factory。生产调度器不得继续直构未装配的 `OperationsScheduler`。
5. worker 路径继续使用既有 `build_operations_worker`，计算前再次执行当前来源/contract 校验；scheduler preview 和 worker materialization 是两次独立校验，防止检查后来源变化。
6. 不修改 `ProbeRule/ProbeRunLog/ScheduleProbeBindingService/ProbeRuntimeService` 的数据集探针语义；Heat 条件直接在 `OperationsScheduleService` 的 maintenance action due 分支执行。禁止用虚构 dataset key 绑定通用 ProbeRule，也不新增 readiness 表。

#### 5.9.2 Action 与 schedule contract

`MaintenanceActionDefinition` 为单日 Heat 增加系统声明的条件调度策略，不新增环境变量：

```text
schedule_enabled = true
readiness_condition = wealth_sector_heat_sources_ready
initial_check_local_time = 21:15
upstream_workflow_not_before_local_times = {
  daily_market_close_maintenance = 21:00,
  daily_moneyflow_maintenance = 20:00
}
retry_interval_seconds = 600
deadline_next_day_local_time = 00:30
timezone = Asia/Shanghai
```

1. 上述系统值由 action catalog 单一定义；Ops Schedule 只保存 `cron_expr/timezone/status/next_run_at` 和目标 action，不允许页面把间隔、截止时间或门禁键改成任意值。`upstream_workflow_not_before_local_times` 不设环境变量、数据库副本或代码默认值，唯一消费者是 app scheduler factory 装配的 Ops readiness service；修改后必须重启 scheduler 才生效，并由 action catalog 与 readiness 正反向测试守护。
2. 生产 schedule 的 cron 为工作日 `21:15`，目标为 `maintenance_action:maintenance.materialize_wealth_sector_heat_daily`；`params_json` 不固定日期，trade date 由 Heat 条件调度器按检查窗口解析。
3. 当地时间 `21:15..23:59` 使用当天日期；`00:00..00:30` 使用前一天日期。只有 `trade_calendar(exchange='SSE', is_open=true)` 才继续核验；非开放日直接推进到下一次 cron。
4. readiness 未命中且未过 deadline 时，schedule 保持 active，将 `next_run_at` 设为 `checked_at + 10min`，但不得超过次日 `00:30`。命中并 stage TaskRun 后立即按 cron 推进到下一个工作日 `21:15`；计算终态由现有 worker/TaskRun 观测，scheduler 不继续轮询，也不自动重提失败/取消任务。
5. `OperationsScheduleService.enqueue_due_schedules` 锁定 due schedule 后分支：普通目标沿用现有逻辑；仅当 maintenance action 声明 Heat readiness condition 时先求值。miss 时在同一 Ops transaction 更新 `next_run_at`；hit 时在同一 transaction stage TaskRun、更新 `last_triggered_at/next_run_at` 后提交；同一 schedule/action/trade_date 已有任一自动 TaskRun 时不再 stage，并直接按 cron 推进。
6. 并发 scheduler 必须由现有 `FOR UPDATE SKIP LOCKED` 加去重查询保证同日最多一个有效 TaskRun；进程重启后以持久化 `next_run_at` 恢复复查，不依赖内存计时器。

#### 5.9.3 上游执行证据判定

对目标日 `D`，Ops 查询必须按语义键而非生产 ID 识别：

1. `daily_market_close_maintenance`：TaskRun 为 `success` 或其 Heat 必需节点均成功，且 `requested_at` 换算到 `Asia/Shanghai` 后不早于 `D 21:00`。必需节点为 `daily/dc_index/dc_member/dc_daily/limit_list/suspend_d`；每个必需节点的 `time_input_json.trade_date` 都必须为 `D`。
2. `daily_moneyflow_maintenance`：TaskRun 的 `requested_at` 换算到 `Asia/Shanghai` 后不早于 `D 20:00`，且 `moneyflow_ind_dc` 节点成功、节点交易日为 `D`。该时间与生产固定工作流 schedule #4 的 20:00 合同一致，不要求为满足 Heat 再重复执行一次资金工作流。
3. 同一个 workflow 的必需节点必须来自同一个 TaskRun，禁止把多次 partial run 拼成成功；每个 workflow 早于自身门槛的 TaskRun 只作为历史记录，不作为 readiness 证据。不得把两个门槛重新压缩成一个全局时间，否则会让资金流永远不满足，或错误放宽收盘工作流。
4. Heat 无关节点失败时，只要 TaskRun 中全部必需节点成功即可继续 biz preview；必需节点缺失、失败、仍运行或被取消均返回 `HEAT_UPSTREAM_NOT_READY`。
5. readiness evidence 记录 workflow key、TaskRun ID、node key/status、requested/ended time 和证据 hash；不得记录连接信息或敏感参数。
6. 父 TaskRun 只保存调度意图，生产 point 工作流的真实结构是 `{"mode":"point"}`，不得要求或伪造父级 `trade_date`。`TaskRunDispatcher` 在 resolver 解析日期后，把规范化 time input 写入数据集 `TaskRunNode`；节点缺日期、日期错误或非法日期均不得成为 readiness 证据。

#### 5.9.4 Biz 内容预检与 reason code

Ops 证据通过后，app 调用已有 `preview_trade_date`。结果分类固定：

| reason code | 含义 | 行为 |
|---|---|---|
| `HEAT_READY` | 上游与 biz preview 均通过 | 创建一次正式 Heat TaskRun |
| `HEAT_NON_TRADING_DAY` | 目标日不是 SSE 开放日 | 不创建任务，推进下次 cron |
| `HEAT_UPSTREAM_NOT_READY` | 必需工作流/节点未完成 | 10 分钟后复查 |
| `HEAT_SOURCE_NOT_READY` | 日期、整日来源、唯一键、零行证据或覆盖门禁未通过 | 10 分钟后复查 |
| `HEAT_PREVIEW_FAILED` | 配置、contract 或预检发生非输入等待类错误 | 继续到 deadline，但必须以 error 级结构化日志记录 |
| `HEAT_AUTOMATION_SOURCE_TIMEOUT` | 次日 00:30 仍未齐备 | 创建一个 failed TaskRun/issue，不写 Heat |
| `HEAT_AUTOMATION_ALREADY_ATTEMPTED` | 同一 schedule/action/trade_date 已有自动 TaskRun | 不重复创建，推进下次 cron；失败/取消走人工恢复 |

单个概念形成 `INVALID` 仍属于成功 preview；自动化不得把 `invalid_count > 0` 当成整日失败。

#### 5.9.5 TaskRun、幂等与超时记录

1. 命中时用 `TaskRunCommandService` 创建标准 `maintenance_action` TaskRun，`trigger_source='scheduled'`、`schedule_id` 指向 Heat schedule、`time_input={'mode':'point','trade_date':D}`。
2. `request_payload_json` 增加 `readiness` 快照：检查时间、上游 evidence、config/source/plan/content hash；dispatcher/worker 仍以实际重算为准，hash 漂移失败关闭。
3. 自动去重语义为 `(schedule_id, action_key, trade_date)`：已有任一自动 TaskRun（`queued/running/success/failed/canceled`）时返回 `HEAT_AUTOMATION_ALREADY_ATTEMPTED`，不创建新任务并推进下次 cron。人工单日 TaskRun 不冒充自动验收证据；自动任务失败/取消后由运营按既有人工入口判断是否恢复，scheduler 不自动重提。
4. deadline 时若始终没有达到 readiness，通过同一 TaskRun service stage 一个标准 Heat TaskRun，立即置为 `failed`，写一个 `TaskRunIssue(code='HEAT_AUTOMATION_SOURCE_TIMEOUT')`，并保存最后 readiness 证据；同一 schedule/日期只允许一个超时 TaskRun。若当日已经 stage 过自动计算 TaskRun，则不适用来源超时，也不额外创建记录。
5. readiness miss 只写结构化 scheduler 日志并更新 `next_run_at`，避免每 10 分钟制造失败 TaskRun；日志至少含 schedule/action/trade_date/reason/next_check/缺失依赖。
6. schedule 更新、TaskRun 创建和超时 issue 在 Ops transaction 中原子提交；Heat business transaction 与其独立。
7. 新分支不得改变既有普通 cron/once、dataset probe/fallback、workflow、日期完整性或非 Heat maintenance action 的行为；对应回归是 Slice 14 必过门禁。

---

## 6. 后端 LLD

### 6.1 请求模型与 handler

API handler 使用显式 enum/格式校验，禁止把互斥规则分散到 query：

1. 默认 `market=CN_A, view=INDUSTRY`。
2. 行业默认 `CHANGE_PCT_UP`，地域默认 `CHANGE_PCT`，概念默认 `HEAT_SCORE`；行业不再接受旧 `CHANGE_PCT`。
3. `selected*Code` 使用 `^BK[0-9]{4}(?:\.DC)?$`；进入查询前规范化为存储格式，响应保持统一格式。
4. 当前 view 之外的 rank/selection 参数立即返回 `400001`。
5. 显式 `tradeDate` 非交易日或无完整事实返回 `EMPTY`，不回退。
6. 403 仍由统一 `require_quote_access` 产生，不伪装为 HTTP 200。
7. 默认首页加载不得把页面上下文推导出的交易日伪装成用户显式 `tradeDate`；不传日期时由后端选择当前 view 最新公共完成交易日，落后页面期望日时返回 `DELAYED`。只有明确的用户选日动作才能触发第 5 条精确日期语义。

### 6.2 查询职责与 SQL 边界

| 类 | SQL/职责 | 上限 |
|---|---|---:|
| `SectorOverviewStateQuery` | 视图所需来源的最近共同完成日 | 1 round trip 或受控的固定查询 |
| `SectorHierarchyQuery` | 当前层级版本全部节点；校验单版本 | 496 行 |
| `SectorMetricsQuery` | 候选代码集同日行情 + 资金流 | 行业 496 / 概念约百 / 地域 31 |
| `SectorHeatQuery` | 同日 Heat 排名；所选概念最近 20 发布日 | Top20 + 20 点 |
| `EffectiveAStockPoolQuery` | 单板块成员资格、停牌、行情和计数 | 单板最大成员数，按 code/date 有界 |
| `SectorMemberQuery` | 单板块有效成员 Top5 | 5 行 |
| `SectorSelectionResolver` | 纯内存路径修正 | 无 SQL |

全部 SQL：

1. 使用显式列名、确定排序和有界候选集合。
2. `board_moneyflow_dc` 只按 `trade_date + non-null ts_code` 关联。
3. 领涨股只取 `dc_index.leading/leading_code/leading_pct`，不从 member Top1 反推。
4. 成员 Top5 按 `pct_chg DESC NULLS LAST, stock_code ASC`，展示名必须显式取同日 `dc_member.name`；不得使用 `security.name` 回退。
5. 行业 `CHANGE_PCT_UP` 按 `change_pct DESC`，`CHANGE_PCT_DOWN` 按 `change_pct ASC`；两者均排除空值、不按正负号删行。`MAIN_NET_INFLOW` 空值末尾；所有主排序同分最终 `sector_code ASC`。
6. 不做逐板块成员 N+1；仅为最终详情节点查一次成员。
7. 行业 Top5 与概念 Top20 在截断前排除当前排名指标为 null 的候选；不得以 `NULLS LAST` 代替“不参与 TopN”。地域必须保留固定生产枚举 31 项，null 指标只置底，不删除地域。
8. 有效行情资格统一为同日 `close IS NOT NULL AND pct_chg IS NOT NULL`；详情聚合与 Heat 来源查询必须消费同一语义，不能各自定义。

### 6.3 层级缓存

`SectorHierarchyQuery` 可维护进程内只读缓存：

```text
cache key   = baseline_version
cache value = nodesByCode + childrenByParent + roots
invalidate  = DB 查询发现 baseline_version 改变
fallback    = 不允许使用旧版本掩盖当前表空/闭包失败
```

不设置运维可调 TTL。缓存只是 496 行结构优化，不是事实来源。

### 6.4 选择算法

`SectorSelectionResolver` 输入候选树、排名结果和可选请求 code，输出完整 selection 与可选 `SO_SELECTION_INVALID`：

1. 先确定一级 Top5；请求节点 root 不在 Top5 时回到榜首。
2. 再确定所选一级直接二级 Top5；请求祖先不在榜内时回到榜首。
3. 再确定所选二级直接三级 Top5；请求三级不在榜内时回到榜首。
4. 请求一级/二级时向下补榜首；无子级时停在最深合法节点并返回后续空列。
5. `detailSectorCode` 始终等于最深合法选择，不由前端拼装。

概念/地域：请求 code 在当前确定候选中则保留，否则选择榜首并记录 debug；概念热度排序未就绪时不改用涨跌幅。

### 6.5 状态归并

| 条件 | panel status | 页面内容 |
|---|---|---|
| 当前 view 必需事实同日完整 | READY | 正常 workspace |
| Heat 整日未发布，或当前可见榜单/当前详情 Heat 无效、成员覆盖不足 | PARTIAL | 可用事实保留，缺失显示 `--`/`UNKNOWN` |
| 未进入当前榜单且未被选中的其它概念 Heat 为 `INVALID` | READY | 不显示全局质量提示；该行事实仍保留在 Heat 表 |
| 最近共同完成日落后期望日 | DELAYED | 显示真实旧日，不冒充当日 |
| 显式日无候选/全部基础源合法空 | EMPTY | 稳定空态 |
| 层级闭包、SQL、配置契约失败 | ERROR | 当前模块错误态 |
| HTTP 403 | 前端 FORBIDDEN | 稳定无权限态 |

`pageStatus` 沿用首页现有聚合器；模块异常不得让其它首页模块丢失。

状态归并还必须使用明确的 view×来源矩阵，至少覆盖 `dc_daily`、`dc_index`、`board_moneyflow_dc`、`dc_member`、hierarchy 和 Heat。某个板块合法没有领涨股不等于来源缺失；概念页质量聚合只检查当前返回榜单和当前详情所需代码，不得用全量概念池中无关板块的 `INVALID` 污染页面状态。

### 6.6 响应构建

1. response 只出现当前 view 对应的 `industry/concept/region`。
2. `MetricValue.value=null` 时 `displayText='--', direction='UNKNOWN'` 由后端 formatter 产出。
3. `leader` 三字段均缺失时返回 `null`；不产出半真半假的占位股票。
4. Heat `INVALID` 保留质量计数和原因；`heatScore/heatRank` 为 null。
5. `heatHistory` 日期升序、最多 20 点，断点/无效点保留日期与 null，不向前填充。
6. `asOf` 是响应组装时间，`calculatedAt` 是 Heat 物化时间，两者都不能写成实时行情时间。
7. 排名项按 view 判别，不再共享一个会抹平列结构的 DTO。行业的 `primaryMetric` 随排序维度变化；概念和地域的固定展示列不得因 rank 改变而消失。
8. 正式 rank item 最小字段集合：

| view | 固定展示事实 |
|---|---|
| INDUSTRY | `sectorCode/sectorName/industryLevel/rank/primaryMetric/leader`；`primaryMetric` 与 `CHANGE_PCT_UP/DOWN/MAIN_NET_INFLOW/UP_COUNT` 当前维度严格对应 |
| CONCEPT | `sectorCode/sectorName/rank/changePct/leader/heatStatus/heatLevel/heatTrend/heatScore/heatDelta1d`；资金排序所需值以明确字段返回 |
| REGION | `sectorCode/sectorName/rank/changePct/mainNetInflow/memberCount/upCount/leader` |

字段必须复用 `MetricValueDto` 或等价强类型事实，不允许引入动态 `Record<string, any>`。前后端同提交破坏性替换；不保留一个通用于三 view、只含 `primaryMetric` 的旧兼容分支。

### 6.7 2026-08-15 聚焦纠偏实施顺序

1. 正式 Figma：概念排行表头与数据行改为同一五列固定网格；行业排序工具栏增加“涨幅榜/跌幅榜”；交互契约明确 `PARTIAL` 只看当前可见榜单/详情。
2. 后端破坏性替换行业枚举：删除行业 `CHANGE_PCT`，新增 `CHANGE_PCT_UP/CHANGE_PCT_DOWN`；涨榜降序、跌榜升序、同分代码升序。
3. 后端概念状态聚合：整日 Heat 未发布仍为 `PARTIAL`；只有可见行或当前详情缺 Heat 才局部降级；不可见 `INVALID` 不返回 `SO_HEAT_NOT_READY`。
4. 前端同步请求类型、默认值和页签文案；概念 CSS 使用共享固定列定义与显式对齐，不在渲染层计算或修补数据。
5. 正例：涨榜/跌榜顺序、页签请求、固定列 DOM/CSS、不可见 `INVALID => READY`。反例：旧行业 `CHANGE_PCT` 返回 400、可见 `INVALID => PARTIAL`、Heat 整日缺失仍 `PARTIAL`。
6. 后端、前端、typecheck、build、文档一致性与本地页面截图全部通过后，才允许形成提交；不改 Heat 公式、表结构、调度、地域或其它首页模块。

---

## 7. 前端 LLD

### 7.1 状态控制器

`useSectorOverviewController` 持有：

```ts
type SectorTabState = {
  industry: { rankMetric: IndustryRankMetric; selectedCode?: string };
  concept: { rankMetric: ConceptRankMetric; selectedCode?: string };
  region: { rankMetric: RegionRankMetric; selectedCode?: string };
};

type SectorRequestState =
  | { kind: "initial-loading" }
  | { kind: "refreshing"; data: SectorOverviewPanelV2 }
  | { kind: "ready"; data: SectorOverviewPanelV2 }
  | { kind: "empty"; data?: SectorOverviewPanelV2 }
  | { kind: "partial" | "delayed"; data: SectorOverviewPanelV2 }
  | { kind: "forbidden" }
  | { kind: "error"; message: string };
```

请求纪律：

1. 首次、Tab、rank、selection、tradeDate 变化均走同一 controller。
2. 每次新请求 abort 上一个请求，并以递增 request id 二次防止 stale response 回写。
3. 超时保持现有 5 秒；timeout -> error，不切 mock。
4. 切 Tab 恢复该 Tab 自己的 rank/selection；服务端纠正后的 selection 回写对应 Tab。
5. retry 重发当前完整请求，不重置用户选择。
6. 默认页面加载不传用户显式 `tradeDate`；controller 必须接收“用户是否显式选日”或等价不可混淆的输入。页面上下文日期只能用于显示期望日/判断 DELAYED，不能自动改变后端精确日期语义。
7. 后端 PageStatus 使用穷尽 `switch` 映射到前端状态；`ERROR`、未知枚举、网络异常、超时和 403 必须分流，禁止 `toLowerCase() + 类型断言`。

### 7.2 组件边界

1. `SectorOverviewPanel`：固定 `1564 × 680` 外框和状态 overlay，不持有事实排序，也不套用会改变正式 header/内边距的通用 `Panel` 结构。
2. `SectorOverviewTabs`：可访问的 tablist/tab，键盘左右切换。
3. `SectorRankingToolbar`：只展示排序维度和对应页签并发送 rank enum；不常驻展示“排名范围”“热度规则”“地域口径”等说明性文字，也不在前端改变排序候选。
4. 三个 workspace：只渲染各自 DTO，不接收其它 view 字段；必须分别存在 `IndustryRankItem`、`ConceptRankItem`、`RegionRankItem`，不得继续以通用 `SectorRankCard` 抹平列结构。
5. 详情只复用无业务语义 primitives；必须分别组合 `IndustryDetailPanel`、`ConceptDetailPanel`、`RegionDetailPanel`，每个 view 的四指标由本 LLD 和正式 Figma 冻结。地域增加 breadth，概念增加 Heat 历史。
6. `HeatLevelBadge` 和 `HeatTrendBadge` 分离；只映射后端 enum 到“沸腾/高热/活跃”和“升温/平稳/降温”，不从 score/delta 二次推导。`NONE` 不渲染等级 badge，`UNKNOWN` 不伪造趋势。
7. `SectorLeaderStock` 和 `SectorMemberStockList` 使用独立、可访问的股票导航目标；点击领涨股不得触发板块选择，禁止嵌套 button。无领涨时固定显示“暂无领涨股”。
8. `SectorWorkspaceSkeleton` 按当前 view 保留正式 header、列表/层级、详情栅格；`SectorStateOverlay` 只覆盖内容，不替换骨架。

### 7.3 布局约束

1. 外框 `1564 × 680`，高度不因状态或列表长度变化。
2. 行业左侧三列每列固定 5 行；概念/地域使用单列表格结构、固定表头、7 行可视和内部 `overflow-y:auto`，禁止两列卡片网格。
3. 排名项中板块名、固定展示指标、Heat 标签和领涨股各自有真实容器；名称和领涨股单行省略，tooltip 提供全文。列宽不能随排序维度变化。
4. 工具栏、Tab、列表、详情使用 flex/grid 正常流；Heat 迷你趋势图内部坐标可绝对定位。
5. A 股红涨绿跌只由 `direction` enum 驱动；Heat 标签使用独立 token，不复用 success/error。
6. Loading/Empty/Error/Partial/Delayed/Forbidden 共用同一 grid 骨架，overlay 不导致布局跳动。
7. 行业正式左右区尺寸以节点 `538:520` 为准；概念节点 `538:521`、地域节点 `571:516` 各自使用正式左右区尺寸。不得用一套 `fr` 比例近似三个 view。
8. 三个 view 的详情指标均为两列等宽、统一行列间距和内边距；不得把停牌/覆盖率等质量字段擅自升级为 Figma 未批准的主指标卡。
9. 概念 Heat 历史固定最近 20 个已发布交易日。无效点保留横向位置并形成断点，不允许以最小高度柱伪装数值。
10. 概念 Heat 历史图固定使用 20 个等宽日期槽并按 `tradeDate ASC` 从左到右展示。每个有效点必须在柱顶正上方 `3px`、与柱水平居中的位置显示 `heatScore`；展示值最多保留两位小数并去除末尾 `0`，不得改写分数或以排名代替。柱高继续把 `0..100` 线性映射到固定绘图区，超出范围只做显示侧 clamp，不改变 API 事实。
11. 横轴日期固定显示第 `1/5/10/15/20` 个日期槽，共 5 个刻度；刻度必须与对应柱中心对齐，格式为 `MM-DD`。其余 15 个槽不显示日期文字，不得另建一个与柱槽错位的独立平均分布坐标轴。
12. `INVALID/null` 点保留完整日期槽，不显示柱和柱顶数值，也不得前向填充；如果该槽命中五个日期刻度之一，底部日期仍须显示。视觉值标签不替代可访问文本，每个槽的 `aria-label/title` 继续保留完整 `YYYY-MM-DD` 和原始分值或“无有效热度”。
13. Heat 图内部可增加柱顶数值区与日期刻度区，但概念工作台外框继续保持 `1564 × 680`，详情区宽度不变；空间从详情内部正常流重新分配，成员列表按既有内部滚动承接，不允许溢出、重叠或压缩其它工作台。

### 7.4 类型与 adapter

1. API 类型按 view 判别，禁止可选字段堆叠后由组件猜 view。
2. adapter 只做日期/金额/百分比显示格式，不排序、不补 0、不修 selection、不算标签。
3. 删除所有 `columns/heatMapItems`、旧 fixture、旧 `SectorRankMatrix/SectorHeatmap`。
4. `null` 永远映射 `--/UNKNOWN`；空数组保留 empty 语义。
5. V2 rank item 按 view 使用明确类型，不使用动态字典，也不继续保留三 view 共用的 `primaryMetric-only` 前端兼容类型。

---

## 8. 测试 LLD

### 8.1 Foundation / migration

1. 两个 ORM 的 schema、PK、index、numeric 和 check 约束。
2. migration upgrade/downgrade 仅影响两张目标表。
3. Alembic 单 head、metadata 与数据库表一致。

### 8.2 层级发布、Heat 业务 contract 与执行链

| 组 | 必测正例 | 必测反例 |
|---|---|---|
| DG hierarchy | Silver 496 行、层级计数、写后 hash 对账 | 非法层级、重复键、计数/hash 不一致时不得发布 |
| 配置中心 | V1 canonical config/hash，注册表可解析 | 权重不为 1、阈值逆序、未知版本、版本未升 |
| prod 来源查询 | 每个来源按冻结字段和窗口有界读取 | `SELECT *`、自然日凑数、逐板块 N+1、访问 DG/Lake/Tushare |
| 有效池 | CNY 上市 A 股、停牌扣分母 | B 股、未来上市、退市生效日、重复成员、两套 adapter 口径 |
| 行情覆盖 | 有效报价、合法零停牌 | 可报价无行情、必需来源缺失或错日仍计算 |
| Heat contract | golden 五分量/总分/rank/level | 缺分量补权、低覆盖仍有效、未来数据影响历史结果 |
| prod 发布 | 单日 delete+insert+read-back hash 同事务成功 | read-back 不同、数据库写入失败或 contract 失败时保留旧成功日 |
| Ops/app/CLI 装配 | TaskRun 计划 60 个有效交易日，生产 CLI 经 app factory 注入 executor 并调用 biz | ops import biz、CLI 直构未装配 worker、TaskRun session 与业务 session 共事务、失败跳日 |
| Heat 条件调度 | 21:15 开放日检查，上游节点 + biz preview 通过后只创建一个单日 TaskRun | 非交易日、18:30 早场、必需节点未完成或 preview 未通过仍触发计算 |
| Heat 等待/截止 | 未齐每 10 分钟复查，跨午夜仍锁定原交易日，00:30 超时只生成一个 issue | 每轮制造失败 TaskRun、目标日漂移、超时后继续等待或用旧日数据 |
| Heat 自动幂等 | queued/running/success 与相同内容 read-back 去重；failed 修复后可重试 | 同日重复任务/重复 DML，失败任务永久阻止修复后重跑 |
| Scheduler 装配 | CLI/runtime 经 app scheduler factory 注入 readiness evaluator | ops import biz、Web 执行 scheduler、生产 CLI 直构未装配 scheduler |
| 访问边界 | DG/Heat/Web 只操作各自规定对象，Heat 与 Ops 使用独立 Session/事务 | DG 写 Heat、Heat 写来源/hierarchy、Web 产生 DML、运行时代码执行 DDL/`TRUNCATE` |
| 静态清零 | DG 仅存在 hierarchy 发布实现 | 出现 DG Heat asset/partition/check/sensor/Gold/history CLI |

### 8.3 后端真实 API

`tests/web/test_wealth_market_sector_overview_api.py` 至少拆分：

1. 三个 view 的 happy path，断言用户实际看到的字段。
2. 行业三级 Top5、父子范围、默认/保留/纠正/无子级。
3. 概念四种排序、Heat INVALID、历史 20 点和未就绪不回退。
4. 地域三种排序、精确 31 项、无 hierarchy/Heat。
5. 领涨字段严格来自 `dc_index`；成员 Top5 和覆盖计数。
6. 互斥参数、非法 market/date/code、403。
7. READY/PARTIAL/DELAYED/EMPTY/ERROR。
8. response/schema 明确不存在 V1 `columns/heatMapItems` 旧根语义。
9. rank item 按 view 判别：行业显式返回当前排序 `primaryMetric`；概念/地域同时包含正式排行行固定列且不因 rank 改变丢失；旧三 view 通用 `primaryMetric-only` 契约清零。
10. 有效行情必须 `close + pct_chg` 同时非空；成员名称严格取 `dc_member.name`。
11. 行业/概念 null 排名指标不进入 TopN；地域仍返回固定 31 项并将 null 置底。
12. `board_moneyflow_dc` 缺失不能返回 READY；合法无领涨不等于来源缺失。
13. 默认未传日期的来源延迟返回 DELAYED，用户显式无完整事实的日期返回 EMPTY。

### 8.4 前端真实 API 与组件

1. `loading -> ready`、refreshing 保留旧数据、timeout/error/retry、403。
2. 三 Tab 独立 rank/selection，三级联动、服务端 selection 纠正。
3. 快速切换时旧响应不能覆盖新响应。
4. 名称、主指标、领涨、Heat、成员和地域 breadth 的可见断言。
5. 长名称、null、负数、大金额和 `INVALID`。
6. 7 行可视区/内部滚动、稳定高度和键盘操作。
7. mock source 关闭时绝不 fallback 到 mock。
8. 行业、概念、地域使用各自 rank item 和 detail 结构；概念/地域不得出现两列卡片网格。
9. Heat 等级/趋势分离，`STABLE -> 平稳`，`NONE` 不显示等级标签；20 日历史中的 null 点形成断点。
10. 领涨股和成分股分别进入股票详情；点击领涨股不触发板块选择；无领涨显示“暂无领涨股”。
11. READY/PARTIAL/DELAYED/EMPTY/ERROR/FORBIDDEN/Loading 在三个 view 下均保持相同外框和 grid；ERROR 与未知枚举不能落入类型声明外状态。
12. 默认页面请求与用户显式日期请求的 query string 不同，前端不得无条件附带 `tradeDate`。
13. Heat 历史正例必须断言 20 个日期槽、每个有效点的柱顶值、柱顶 `3px` 间距规则以及第 `1/5/10/15/20` 槽的 5 个 `MM-DD` 日期；负例必须证明 `INVALID/null` 槽没有柱和数值、不补值，但命中日期刻度时仍保留日期。浏览器验收同时检查柱顶值与柱中心对齐、日期与对应槽中心对齐、图表和概念详情无横向/纵向溢出。

#### 8.4.1 审计问题到自动化测试的强制映射

测试 ID 中 `P` 表示批准行为正例，`N` 表示禁止项反例；既有测试名未强行重命名，以下以完整 pytest/Vitest node 名作为稳定 ID。Slice 13 只关闭既有页面/契约自动化部分；新增的 Heat 每日自动化由 Slice 14 单独验收。A18 的像素、性能、候选部署、监控和签字顺延到 Slice 15-17。

| 问题 | 正例测试 ID | 禁止项反例测试 ID | Slice 13 结论 |
|---|---|---|---|
| A01 | `test_s13_a01_p01_all_rank_metrics_preserve_view_specific_row_facts`；前端三个 Ready 基线用例逐列断言 | `test_s13_a01_n01_generic_rank_item_contract_cannot_return`；`test_sector_overview_rejects_unknown_irrelevant_or_invalid_parameters` | 三类 rank DTO、全部排序下固定列和旧通用契约清零均已自动化 |
| A02 | `test_effective_pool_requires_close_and_pct_chg_for_a_valid_quote`；Slice 12 v2 同版本重放 | `test_s13_a02_a03_n01_close_null_is_not_valid_and_member_name_has_no_security_fallback`；`test_missing_comparable_previous_heat_returns_unknown_without_filling` | `close + pct_chg` 详情/Heat 双链正反例完整 |
| A03 | `test_industry_workspace_resolves_three_levels_and_uses_frozen_fields` | `test_s13_a02_a03_n01_close_null_is_not_valid_and_member_name_has_no_security_fallback` | `dc_member.name` 可见，空名不回退 `security.name` |
| A04 | `test_rank_null_rules_filter_industry_and_concept_before_topn_but_keep_all_regions` | 同一测试证明行业/概念 null 不占 TopN，地域不得错误删行；前端 `S13-A03-A04-A11-A12-A13-PN01` 证明 null 显示 `--` | TopN 过滤与地域置底语义均自动化 |
| A05 | `test_legal_missing_leader_remains_ready_and_returns_null`；前端 `S13-A05-A15-P01` | `test_s13_a05_n01_moneyflow_gap_is_partial_in_every_workspace`；daily/index/member/Heat 单独缺失既有路由用例 | 三 view 来源缺失、合法无领涨和 refreshing 事实保留均已覆盖 |
| A06 | `test_default_date_reports_delayed_without_cross_date_join`；前端默认/显式日期两个既有用例 | `test_explicit_trading_date_without_bundle_returns_empty_not_previous_day`；`test_explicit_non_trading_or_missing_date_returns_empty_without_fallback` | 默认日期不伪装显式日期，显式缺事实不回退 |
| A07 | `test_industry_hierarchy_unavailable_is_stable_error`；前端 `S13-A15-P01` 三 view×ERROR/FORBIDDEN | `test_page_status_contract_rejects_unknown_backend_values`；前端未知状态、403、timeout/retry 既有用例 | ERROR、未知、网络超时和权限均 fail closed 且保留骨架 |
| A08 | `test_sector_heat_strategy_config_is_registered_and_hashed_deterministically`；`test_replay_resume_skips_existing_content_after_revalidating_plan` | `test_sector_heat_config_rejects_semantic_change_without_version_upgrade`；`test_previous_heat_from_v1_is_not_comparable_with_v2` | 同版本幂等、未升版漂移和跨版本趋势均自动化 |
| A09 | 三个 Ready 基线用例；`S13-A15-P01` 三 view 全状态 | `test_s13_a10_p02_fixed_seven_row_scroll_contract_remains_explicit` 防止 680px 外框/正式滚动结构被移除 | 结构回归已自动化；像素仍留 Slice 15 |
| A10 | `test_industry_workspace_resolves_three_levels_and_uses_frozen_fields`；前端 `S13-A10-A11-P01` | `test_s13_a10_n01_industry_leaf_without_children_returns_an_empty_third_column`；滚动测试证明表头不在滚动容器 | 行业 3×5、无子级、概念/地域七行滚动与固定表头完成 |
| A11 | 三个 Ready 基线用例；前端 `S13-A10-A11-P01` 每 view 四指标 | 前端 `S13-A03-A04-A11-A12-A13-PN01` 证明 null/大金额不产生多余主卡 | 三类专属详情结构与地域 breadth/概念历史完成 |
| A12 | 前端 `renders the concept fixed columns, separate badges and a real 20-day gap`；`S13-A03-A04-A11-A12-A13-PN01` | 同一 `PN01` 证明 `NONE` 不显示、UNKNOWN 不伪造分数/趋势；`test_s13_a12_n01_concept_heat_contract_rejects_unknown_level_and_trend` | 等级/趋势独立、STABLE=平稳、NONE/UNKNOWN 负例完整 |
| A13 | `test_concept_workspace_supports_heat_sort_history_and_member_detail`；前端概念 Ready 基线 | 前端 `S13-A03-A04-A11-A12-A13-PN01` 证明第 9 槽断点无样式、不补值 | 20 个已发布日、升序和 INVALID 断点完成；像素仍留 Slice 15 |
| A14 | 前端 `S13-A14-A16-PN01`；既有领涨导航与无领涨用例 | 同一测试断言板块选择不改路由、股票导航不嵌套 button；无领涨不生成目标 | Tab/板块/领涨/成员键盘焦点和股票路由完成 |
| A15 | 前端 `S13-A15-P01` 参数化覆盖 3 view × 7 状态共 21 例 | 前端未知状态/403/timeout 与 `S13-A05-A15-P01` 刷新失败用例 | 全状态稳定骨架、Partial/Delayed 事实保留和 refreshing 完成；同尺寸像素留 Slice 15 |
| A16 | 三个 Ready 基线均断言无板块详情入口 | `test_s13_a16_n01_sector_detail_routes_and_entry_copy_cannot_return`；`S13-A14-A16-PN01` | 板块名称仅选择/联动，详情路由及文案静态清零 |
| A17 | 本表 A01-A16 映射、后端专项、前端 36 项专项和完整门禁命令 | `test_s13_a17_n01_real_sector_feature_cannot_import_or_fallback_to_mock` | 问题到测试映射达到 100%，适用禁止项均有反例 |
| A18 | `test_s13_a18_a19_n01_automation_cannot_claim_pixel_or_release_acceptance` 证明后续门禁仍在 | 同一测试禁止 Slice 13 冒充像素/候选发布完成 | 仅完成自动化映射；A18 本体保持 `OPEN`，进入 Slice 15/16 后执行 |
| A19 | 固定命令、文件级 Ruff、docs integrity、`git diff --check` | `test_s13_a18_a19_n01_automation_cannot_claim_pixel_or_release_acceptance`；全目录 Ruff 存量不得混入本模块结论 | 自动化与文档门禁完成；最终状态对账仍留 Slice 17 |

### 8.5 性能与像素

1. API 同机房 P95 `<250ms`、P99 `<500ms`、payload `<120KB`、SQL round trips `<=8`。
2. 单日 Heat P95 `<60s`；60 个有效交易日回放记录每日日志、均值/P95 和失败恢复。
3. 行业/概念/地域与所有状态保存 `1564 × 680` 截图；普通 UI 偏差 `<=2px`。
4. 首页 `1600 × 1200` 截图确认其它模块宽度/图表位置未变化；板块模块增高只改变后续文档流位置。
5. 截图至少覆盖：三个 Ready 默认排序、每个非默认排序、行业 L1/L2/L3 选择、概念 Heat INVALID/断点、地域分布、Loading/Partial/Delayed/Empty/Error/Forbidden、长名称、无领涨。
6. 每张截图记录 Figma node id、viewport、设备像素比、数据 fixture/交易日、基线文件、候选文件和差异结论；不接受口头“看起来接近”。

实现完成后的固定命令：

```bash
# Foundation / biz Heat / app-ops 装配 / 访问边界 / 后端真实路由 / 架构边界
uv run pytest -q \
  tests/test_extended_models.py \
  tests/test_foundation_table_model_registry.py \
  tests/test_wealth_sector_serving_constraints.py \
  tests/test_wealth_sector_serving_migration.py \
  tests/test_wealth_sector_heat_contract.py \
  tests/test_wealth_sector_heat_materialization.py \
  tests/test_wealth_sector_heat_replay_planner.py \
  tests/test_sector_heat_task_executor.py \
  tests/web/test_wealth_sector_heat_ops_runtime.py \
  tests/test_cli_ops_runtime.py \
  tests/web/test_wealth_market_sector_overview_api.py \
  tests/architecture/test_wealth_sector_heat_guardrails.py \
  tests/architecture/test_wealth_sector_overview_slice13_guardrails.py \
  tests/architecture/test_subsystem_dependency_matrix.py

# Wealth 类型、真实 API 行为与构建
cd wealth
npm run test -- market-overview-sector-overview-real-api
npm run typecheck
npm run build

# DG 仅验证 hierarchy 发布（实现时创建对应测试）
cd ../lake_console/orchestrator
uv run python -m pytest -q tests/test_wealth_sector_hierarchy_prod_core.py
uv run ruff check \
  src/orchestrator/defs/assets/wealth_sector_hierarchy_prod_core.py \
  src/orchestrator/defs/prod_db/wealth_sector_hierarchy.py \
  tests/test_wealth_sector_hierarchy_prod_core.py

# 仓库文档与补丁完整性
cd ../..
.venv/bin/python scripts/check_docs_integrity.py
git diff --check
```

`uv run dg check defs` 只用于确认 hierarchy Definitions 可加载，按 DG 运维规则单独执行并记录结果；它不授权 job、materialize、backfill、runless event 或任何数据写入。仓库静态门禁还必须确认没有任何 Heat DG 定义被加载。全目录 `uv run ruff check src/orchestrator/defs ...` 在本次审计时包含 487 个与本模块无关的既有问题，不能伪记为本需求已通过，也不能把这些存量问题混入板块修正提交；本需求 Ruff 门禁仅使用上面的三文件范围，存量基线另行治理。

---

## 9. 性能与查询预算

### 9.1 API 最多 8 次数据库往返

| 次数 | 查询 |
|---:|---|
| 1 | trading day / source state |
| 2 | hierarchy（行业；缓存命中可省） |
| 3 | 当前 view 候选 metrics + leader |
| 4 | Heat ranking/association（概念） |
| 5 | 最终详情板块有效池 +聚合计数 |
| 6 | 最终详情成员 Top5 |
| 7 | Heat history（概念） |
| 8 | 预留 debug/source audit；非 debug 应尽量省略 |

不得用 N+1 消耗预算。行业 15 行、概念 20 行、地域 31 行均在 SQL 排序后有界返回。

### 9.2 prod-native Heat 读取与计算预算

1. 所有输入只读 prod 正式表，并按目标概念、交易日和 25/6/5 日等冻结窗口有界查询；不得扫描全历史。
2. 资金流读取 `t-9..t` 共 10 个有效交易日，涨停读取 `t-5..t` 共 6 个有效交易日；窗口由交易日历解析，不能用自然日替代。
3. 大型成员代码集合使用临时值关系、数组绑定或数据库等价批量方式，禁止每个概念一次 SQL。
4. 每日 TaskRun 节点记录逐来源行数与 canonical source hash，以及 SQL、计算、写入和 read-back 耗时；不记录文件数或 Gold 元数据。
5. 单日计算应复用已加载的来源 bundle，不允许 contract 内部重新访问数据库。
6. 生产只读验收表明 85 日有效池单次聚合超过 60 秒，而 10 日批次约 7.4-16.7 秒；正式物化必须按单交易日查询，历史 plan 审计批次不得超过 10 个交易日，并设置数据库 statement timeout，禁止整窗大查询。

---

## 10. 分阶段实现与提交边界

### Slice 0：文档冻结与生产只读证据

1. 复核层级 496/31/128/337。
2. 记录 member pair、重复率、最大单板成员。
3. 按 prod 有效池唯一口径对账证券资格、停牌、日线和成员固定样本。
4. 验证 `board_moneyflow_dc`、`equity_limit_list` 等全部必需来源的目标日期、唯一键、零行完成证据、代码覆盖率和有界查询计划。
5. 输出 60 个有效交易日、warm-up 日期与缺口台账；缺口日期不得计入 60 日。

未通过时停止，不进入 Heat 计算、回放或应用切换。

### Slice 1：实施日迁移基线

本需求迁移创建时重新查询 Alembic head，本地仓库与生产均为单 head `20260812_000133`，因此 revision 使用 `down_revision = 20260812_000133`。2026-08-13 部署后再次只读验收，仓库与生产当前单 head 已推进为 `20260813_000135`；`000134` 两张表迁移已位于有效链上，后续新增迁移必须接真实 head `000135`，不得继续引用本需求创建时的旧 head。

### Slice 2：Foundation + migration 与现有连接复用

只新增两表模型、注册、迁移和模型测试；迁移给既有 `lake_raw_writer` 增加 hierarchy 单表 `SELECT/INSERT/DELETE`。Web/Heat 复用现有应用连接，DG 复用现有 prod write resource；完成双 Session 事务隔离、组件 SQL 范围、DG 精确对象授权和 secret 不泄漏测试，不新增账号、DSN 或配置项。

实施记录（2026-08-13）：已新增两表 ORM、模型注册、revision `20260813_000134`、约束正反例和迁移范围测试。部署后生产只读验收确认当前 head 为 `20260813_000135`，hierarchy/Heat 分别为 15/31 列、4/18 个约束、各 4 个索引且迁移验收时均为 0 行；既有 `lake_raw_writer` 对 hierarchy 的 `SELECT/INSERT/DELETE` 为真，`UPDATE/TRUNCATE` 为假。hierarchy 随后在 Slice 3 正式发布，Heat 随后在 Slice 5 正式发布。

### Slice 3：DG hierarchy -> prod hierarchy

实现唯一 DG hierarchy asset、prod write contract、read-back 和测试；先本地/测试库，再单独生产发布验收。DG 不得出现 Heat 计算、存储或自动化。

实施记录（2026-08-13）：已新增 `prod_core_wealth_sector_hierarchy`、固定 Silver 文件读取/校验、hierarchy-only SQL contract、单事务全表替换和 canonical hash read-back；已登记 serving schema、catalog 和无分区模型。隔离测试覆盖 496/31/128/337、唯一键、父子/根/路径/叶节点闭包、版本、写入失败、read-back 篡改回滚，以及 DG Heat/job/sensor/check/bootstrap 清零。`dg check defs` 通过后，正式 Run `e875b632-dfb4-4898-a577-944ffa51de95` 已发布 496 行；生产 read-back 为 31/128/337、闭包全绿，source/prod hash 均为 `5094c9f1b0cfd51890351a8d6ecb6d2e0dc7ee4d1de816b5cb3ccf9946ce3525`。

### Slice 4：60 日 prod 来源缺口闭环

按缺口台账修复或补齐生产来源，重新核验来源表枚举、日期、数量、唯一键、零行完成证据和资金流代码覆盖率；冻结 60 个有效交易日及 warm-up 集合。

实施记录（2026-08-13）：目标窗冻结为 `2026-05-20..2026-08-12` 共 60 个连续 SSE 开放日，warm-up 为 `2026-04-10..2026-05-19` 共 25 日。九张 prod 来源完成只读对账：概念成员与资金流每日覆盖全部目标概念，资金流代码覆盖率为 100%，成员 pair 为 31,717-71,132、单板最大 3,850；所有可报价成分均有股票日线，真实缺行情为 0；涨停每日 29-152、停牌每日 1-57，无物理零行日，停牌 `(trade_date, ts_code, suspend_type)` 重复为 0。`BK0636.DC/B股` 每日无有效 A 股成分，按 `INVALID` 处理。`dc_daily` 四个日期的局部缺行与 Prod Raw 完全一致，按已批准源站现状口径归入逐概念 `INVALID`，没有可补写的 Goldenshare 落库缺口。Slice 4 据此闭环，不写来源表。

### Slice 5：prod-native Heat 与回放

实现 biz 来源查询、配置解析、有效池、纯计算 contract 和原子发布；实现 ops generic executor port 与 app 装配；通过正式 TaskRun 完成至少 60 个有效交易日的 plan/apply、read-back、重放一致性与性能验收。

实施记录（2026-08-13）：本地实现与专项回归已通过；生产正式 PLAN TaskRun `8149` 冻结 `2026-05-20..2026-08-12` 共 60 units、0 gaps、`apply_ready=true`。首次 APPLY TaskRun `8152` 从旧到新完成 60/60、0 失败，发布 29,665 行，其中 16,756 `VALID`、12,909 `INVALID`；60 个节点全部成功、issue 为 0，逐日行数、状态数、config/source/content hash 均与 PLAN 一致。单日平均 `9.806s`、P95 `11.253s`、最大 `11.421s`。幂等重放 TaskRun `8153` 再次完成 60/60、0 失败、`rows_saved=0`；Heat 行数、日期范围和 `calculated_at` 范围不变，最终全量 canonical content hash 复算仍为 60 日 0 差异。最新日 `2026-08-12` 为 503 行、477 `VALID`、26 `INVALID`，最近 20 日有效率 `94.50%`。

### Slice 6：后端 V2

先冻结 schema 与真实路由测试，再替换 query/service/status；只读 prod hierarchy/Heat/行情/成员事实，不得保留 V1 DTO 或运行时 Heat 计算。

实施记录（2026-08-13，审计纠偏）：同一路由和判别式 V2 已部署，三级联动、四种/三种排序入口、20 日 Heat、地域 31 项、领涨来源与基础 SQL/payload 预算已有实现；但 Slice 6 **撤销验收完成结论**。A01-A08 证明 rank DTO、有效行情、成员名称、null 排名、资金流状态、默认日期、ERROR 映射和 Heat 版本门禁尚未完整满足本文。相关 86 项回归只能证明已有测试通过，不能关闭上述未覆盖语义。

### Slice 7：前端三工作台

先 controller 和稳定骨架，再行业、概念、地域、详情；最后删除旧结构并做真实 API/像素验收。

实施记录（2026-08-13，审计纠偏）：判别式 API、独立 controller、Tab 状态、AbortController/request id、基础三级联动、地域 breadth 和真实 API 接入可复用；但 Slice 7 **撤销验收完成结论**。A09-A17 证明当前通用 RankCard/DetailPanel、两列卡片网格、Heat badge/history、领涨交互和通用状态块均不符合正式 Figma/LLD；192 项历史全量测试、当前 5 项专项测试、typecheck 和 build 不能替代未完成的结构、浏览器与像素验收。

### Slice 8：发布

历史发布已发生，但因 A01-A19 未关闭，Slice 8 **不视为 V2 发布验收完成**。迁移、hierarchy 与 Heat 数据不回滚；应用版本作为待修正现状。不得在问题关闭前把版本记录、M2 Gate 或对外结论写成“正式交付完成”。

### Slice 9：设计与文档纠偏冻结（新增，修正序号 1）

1. 将 Figma 概念 Heat 历史统一为最近 20 个已发布交易日，并保留 `1564 × 680`、现有左右栏和正式节点结构。
2. 按当前批准范围从本版 Figma 移除三个板块详情路由控件及相应导航说明；板块名称本期只承担选择/三级联动，不新增板块详情路由。只有用户后续明确扩大范围时才重新设计入口。
3. 在 Figma interaction/data contract 中补齐概念、地域多列排行所需字段、长文本/null、无领涨、Heat INVALID/断点和六态骨架说明。
4. 同步 benchmark、implementation design、M2 Gate 与本 LLD 的状态：Slice 1-5 完成，Slice 6-8 已实现未验收，A01-A19 OPEN；同时把 implementation design 中的 `SectorRankItem` 从 `primaryMetric-only` 改为第 6.6 节固定展示事实字段，把目标组件树改为三个 view-specific detail 组合。
5. 保存正式节点同尺寸基线截图与节点属性清单；本 Slice 结束前不改代码。

执行记录（2026-08-13）：**PASS，仅设计与文档纠偏**。

1. Figma `543:538` 已改为“近 20 个交易日热度”；`543:540` 保持 `556 × 42` 与 6px 间距，原 7 个柱节点保留并新增 `666:2..666:14`，最终形成 20 个日期槽。
2. 已删除行业 `539:528/539:529`、概念 `541:528/541:529`、地域 `571:529/571:530` 三组“进入××行情”入口；三个 header meta 仍使用原水平 Auto Layout，并保留原 `219 × 26` Fixed 边界，日期元信息 x/y 不变，没有新增节点或补偿坐标。
3. `545:528` 已冻结为板块只选择/联动、股票可导航、无领涨不跳转；字段列和状态列在原三列等宽容器中使用 6px 间距，补齐 view-specific snake_case 字段、长文本/null、无领涨、20 日/INVALID 断点和 Ready + 六种非正常状态。
4. 正式根、三个工作台、交互契约和 Heat Model 的尺寸与子节点顺序通过属性复核；Heat Model 前后 PNG SHA-256 相同。修改前后截图、属性清单和节点 ID 见 `figma-pixel-artifacts/20260813-sector-overview-v2-slice9/`。
5. benchmark、implementation design、M2 Gate 与本 LLD 已同步为 Slice 1-5 完成、Slice 6-8 已实现未验收、A01-A19 OPEN；implementation design 已改为 Industry/Concept/Region view-specific rank 与 detail 目标契约。

阶段证据：Slice 9 完成 A09、A13、A16、A19 的设计/文档部分，Slice 10 完成 A01-A08 后端部分，Slice 11 完成 A01/A06/A07/A09-A16 前端结构部分，Slice 12 完成 A02/A08 的生产事实部分，Slice 13 完成 A10-A15/A17/A19 的自动化部分；这些问题仍需后续正式像素、候选部署/性能和最终对账证据，整体状态继续保持 `OPEN`。当前优先处理运行缺口，下一步固定为 Slice 14 Heat 盘后自动化。

### Slice 10：后端事实口径与 V2 契约修正（新增，修正序号 2）

1. 先新增 A01-A08 的后端正反例，再修改查询、状态和 DTO；禁止先改实现后补测试。
2. 统一 `close + pct_chg` 有效行情，成员名切到 `dc_member.name`，TopN 截断前过滤 null，补齐 moneyflow/readiness 状态矩阵。
3. 区分默认最新公共日与用户显式日期，穷尽 PageStatus；合法无领涨仍是可用事实。
4. 破坏性拆分 view-specific rank item 并全量审计前端消费者：行业保留当前排序主指标，概念/地域返回固定展示字段；不保留三 view 通用的 `primaryMetric-only` 兼容类型或 adapter。
5. 有效池新增 `close` 会改变 Heat canonical 来源字段集合；本 Slice 冻结 `concept-heat-eod-v2`、新配置/source hash 字段契约与 60 日回放范围，交给 Slice 12 执行，不在本 Slice 写生产 Heat。

执行记录（2026-08-13）：**PASS，A01-A08 的后端代码/测试部分完成**。专项及扩展回归 70 项通过，Ruff 与 `git diff --check` 通过；生产只读 close/pct 60 日聚合核验通过。没有执行生产 Heat v2 写入，也没有修改前端。下一步固定为 Slice 11。

### Slice 11：前端三工作台结构重构（新增，修正序号 3）

1. 按 Slice 9 冻结节点与 Slice 10 新契约，实现正式 header、tabs、toolbar，不修改首页其它模块。
2. 分别实现 Industry/Concept/Region workspace、rank item 和 view-specific detail；删除通用业务 RankCard 和通用六指标详情，不留兼容分支。
3. 实现概念/地域固定表头、单列七行可视和内部滚动；行业三列各五行。
4. 分离 Heat 等级/趋势；实现 20 日断点图；实现地域 breadth；补齐领涨/成员导航和无领涨文案。
5. 修正默认日期请求与 ERROR/未知状态映射；为三个 view 建立同尺寸状态 skeleton/overlay。
6. 每完成一个 workspace 立即做组件和浏览器局部截图，不一次性重建整页。

关闭问题：A01、A06、A07、A09-A16 的前端部分。交付为独立提交。

执行记录（2026-08-13）：**PASS，A01/A06/A07/A09-A16 的前端结构部分完成**。

1. API 类型破坏性拆为 `IndustryRankItem / ConceptRankItem / RegionRankItem` 与各自 detail；删除前端通用业务 rank/detail 组件，不保留 adapter 或别名。行业 `primaryMetric` 仅保留为该 view 批准的当前排序事实。
2. `SectorOverviewPanel` 只重构板块模块，新增正式 header/tabs/toolbar，以及 `IndustryWorkspace / ConceptWorkspace / RegionWorkspace` 和各自 rank/detail；没有改首页其它模块、API、后端、数据库、配置、Figma 或 Slice 12 代码。
3. 1600×1200 本地真实页面核验模块为 `1564 × 680`：行业三列各最多 5 行；概念/地域固定表头、七行视窗和内部滚动；地域真实 31 行；三工作台没有板块详情入口。生产三级行业当前只有 4 个直属节点时按事实展示 4 行，不伪造第 5 行。
4. Heat 等级/趋势独立渲染，`STABLE -> 平稳`、`NONE` 不显示等级；20 日历史 null 点为空槽；地域详情由 `up_count/down_count` 表达同日涨跌分布；领涨股和成员股使用独立股票导航，无领涨显示“暂无领涨股”。
5. 默认请求不附带 `tradeDate`，仅 URL 显式选日时传日期；controller 穷尽 READY/PARTIAL/DELAYED/EMPTY/ERROR，未知枚举 fail closed；403、ERROR、未知值和超时均保留稳定 skeleton/overlay。
6. 自动门禁：真实响应专项 11 项通过；Wealth 全量 33 个文件、198 项通过；`npm run typecheck`、`npm run build` 通过。构建只有既有 Vite 大 chunk 提示，无新增失败。
7. 浏览器门禁：行业、概念、地域三个工作台均在本地真实页面完成局部截图和 DOM/CSS 核验，控制台无 error/warn。截图为本地临时验收物，不替代 Slice 15 的 Figma `<=2px` 正式像素证据。
8. Slice 11 实施时生产仅有 Heat v1；该时点概念默认 Heat 排序按合同返回 Partial。Slice 12 已发布正式 v2 60 日事实，后续候选验收必须使用真实 v2，不得保留 v1 缺失假设。

Slice 11 未关闭 A01-A19 整体问题；Slice 12 已完成 A02/A08 生产事实部分，Slice 13 已完成 A10-A15/A17/A19 自动化部分。每日 Heat 运行自动化优先进入 Slice 14；A09-A16 的正式像素后移到 Slice 15，A18/A19 的候选部署、性能、监控、签字和最终对账后移到 Slice 16-17。

### Slice 12：Heat V2 与 60 日回放（新增，修正序号 4）

1. 将 Heat `scoreVersion` 升级为 `concept-heat-eod-v2`；canonical `equity_daily_bar` 输入显式加入 `close`，配置 hash、source hash 与 content hash 按新版本重算。
2. 先执行正式 PLAN，再执行 APPLY、逐日 read-back 与幂等重放，至少覆盖原 60 个有效交易日；不得用旧 v1 行证明 v2 完成。
3. 新旧版本不得比较 `heatDelta1d/heatTrend`；v2 窗口首日及任何跨版本前序均为 UNKNOWN。
4. 对比 v1/v2 行数、VALID/INVALID、invalid reason、分数/等级变化和 hash，解释每一类变化；即使当前 60 日内容数值恰好一致，也必须保留版本升级与重放证据。
5. 生产写入仍使用现有 TaskRun 和事务，不新增表、账号、DG Heat 或第二份事实。

关闭问题：A02、A08 的生产事实部分。本 Slice 为强制步骤，不得改成“无需重放”。

执行记录（2026-08-13）：**PASS，A02/A08 的生产事实部分完成**。

1. 正式 PLAN TaskRun `8208` 冻结 `2026-05-20..2026-08-12` 共 60 units、0 gaps、`apply_ready=true`；plan hash 为 `6e6b855af3d479aea391c288772e52d4a5c3a4b0b026c898c7e6505aa2f7d390`。60/60 单元均为 `2.0.0 / concept-heat-eod-v2`，批准 config hash 唯一，PLAN 期间 Heat 表仍为 v1 29,665 行，证明 PLAN 未写业务数据。
2. 首次 APPLY TaskRun `8210` 从旧到新完成 60/60、0 失败、0 issue，发布 29,665 行，其中 16,756 `VALID`、12,909 `INVALID`；单日平均约 `9.975s`、P95 `11.284s`、最大 `11.428s`。
3. 逐日 read-back 对 PLAN 的行数、VALID/INVALID、scoreVersion、config/source/content hash 均为 0 差异。v2 首日 `2026-05-20` 的 486 行全部为 `heat_delta_1d=NULL`、`heat_trend/raw_heat_trend=UNKNOWN`，未跨 v1 比较。
4. v1/v2 的 29,665 个主键和全部业务数值、状态、invalid reason、分数、等级、趋势完全一致；29,665 行的 `scoreVersion/configHash/sourceHash` 全部变化，60 日 content hash 全部变化。原因是本窗口的 `close` 均满足有效行情资格，未改变成分池，但 canonical 字段集合已经变化，必须升版并重算摘要。
5. 幂等重放 TaskRun `8213` 继续引用 PLAN `8208`，完成 60/60、0 失败、0 issue、`rows_saved=0`；重放前后 `calculated_at` 精确保持 `2026-08-13 22:27:15.102214+08` 至 `2026-08-13 22:37:06.490427+08`，逐日 PLAN 对账仍为 0 差异。
6. 本 Slice 未修改代码、数据库结构、账号、配置、DG、前端或 Figma；仅使用既有 TaskRun/worker/业务事务链执行生产回放并同步文档。该 Slice 完成时下一步为 Slice 13；现已由后续执行记录确认 Slice 13 通过。

### Slice 13：自动化回归补齐（新增，修正序号 5）

1. 完成第 8.4.1 节 A01-A19 到测试 ID 的映射，所有适用行同时具备正例和禁止项反例。
2. 后端真实路由覆盖三 view、完整 rank 字段、来源状态、默认/显式日期、ERROR、null、名称与有效行情。
3. 前端真实 API 与浏览器覆盖三工作台、全部状态、七行滚动、长名称、null、大金额、INVALID 断点、领涨/成员导航和无 mock fallback。
4. 执行模块专项、typecheck、全量 Wealth test/build、架构护栏、sector hierarchy 文件级 Ruff、文档与 diff 检查。
5. 任一失败不得进入像素验收；不得通过删除断言、放宽类型或改文档来迁就实现。

关闭问题：A10-A15、A17、A19 的自动化部分。

执行记录（2026-08-13）：**PASS，A10-A15/A17/A19 的自动化部分完成**。

1. 第 8.4.1 节已将 A01-A19 全部映射到完整测试 ID；每个适用问题均有批准行为正例和禁止项反例。A18 只完成“不得提前认定像素/发布完成”的自动化门禁，其像素、性能、候选部署和签字仍保持 `OPEN`。
2. 后端真实路由新增全部排序下三类固定字段、`close=null` 有效行情反例、`dc_member.name` 无 security 回退、三 view 资金流缺失 PARTIAL、行业无子级及 Heat 未知枚举拒绝测试；专项共 25 项通过。
3. 前端真实响应专项由 11 项扩为 36 项，其中参数化覆盖 Industry/Concept/Region × Ready/Partial/Delayed/Empty/Error/Forbidden/Loading 共 21 例；另覆盖七行滚动/固定表头、四指标、长名称 Tooltip、null、`+1234亿`、NONE/UNKNOWN、20 日 INVALID 断点、Tab/板块/领涨/成员键盘焦点、刷新保留旧事实与无 mock fallback。
4. 新增 `test_wealth_sector_overview_slice13_guardrails.py` 5 项静态门禁，禁止恢复通用 `SectorRankItem`、板块详情路由/文案和 mock fallback，并固定 680px/内部滚动；其中阶段文字必须在 Slice 14 开发时同步调整为新的 Slice 14-17 顺序。
5. 固定总门禁结果：后端/Heat/Ops/架构核心 109 项与静态护栏 5 项合计 114 项通过；Wealth 全量 33 文件 223 项通过；`npm run typecheck`、`npm run build` 通过；DG hierarchy 9 项与三文件 Ruff 通过；`uv run dg check defs` 只读 Definitions 加载通过；文档完整性和 `git diff --check` 通过。
6. 本 Slice 仅修改板块测试和四份 V2 文档，没有修改业务实现、API、数据库、迁移、配置、依赖、Figma 或首页其它模块。其后产品将 Heat 每日自动化提为最高优先级，下一步改为 Slice 14 Heat 盘后自动化。

### Slice 14：Heat 盘后自动化（新增，修正序号 6）

开发范围严格限定为第 5.9 节，不修改 Heat 公式/API/前端/Figma/数据库结构：

1. 将单日 Heat action 改为带系统固定 readiness condition 的可调度目标；历史 replay 继续不可调度。
2. 实现 Ops 上游 TaskRun/节点核验、app readiness adapter、biz `preview_trade_date` 只读预检，以及 scheduler app factory；CLI/runtime 不得直构未装配 scheduler。
3. 实现 `21:15` 首检、开放日解析、10 分钟复查、次日 `00:30` 截止、跨午夜目标日锁定和 schedule `next_run_at` 推进。
4. 命中时只创建一个标准单日 Heat TaskRun；同一 schedule/action/trade_date 的任何自动 TaskRun 均阻止重复创建，失败/取消不自动重提；deadline 只允许一个 `HEAT_AUTOMATION_SOURCE_TIMEOUT` issue。
5. 补齐第 8.2 节全部正反例和静态边界测试；固定门禁命令至少覆盖 action catalog、automation capability、schedule/runtime、app scheduler factory、Heat executor/materialization、CLI 和依赖矩阵。
6. 部署后由运营创建唯一生产 schedule：工作日 `21:15`、`Asia/Shanghai`、目标单日 Heat action；不得新增 systemd timer、crontab、DG sensor 或外部脚本。
7. 生产验收必须覆盖：schedule/capability 可见；至少一个真实开放日从 readiness miss/hit 到 TaskRun success 和 Heat read-back；随后同日重放不重复建任务/不写数据。若当日 21:15 已错过，可先做只读 readiness 与人工受控时钟验证，但 Slice 14 仍保持 OPEN，直到真实开放日完整链路通过。
8. 记录目标日、上游 TaskRun/节点、各次 reason code、触发 TaskRun、Heat 行数、VALID/INVALID、config/source/content hash、耗时和幂等结果；不得记录 secret。

Slice 14 PASS 标准：代码/自动化测试全部通过、生产 schedule 唯一且 active、真实开放日完成一次成功自动发布与一次同日幂等核验、没有重复 TaskRun/DML、超时/缺源反例可观测。任一条件缺失均不得进入 Slice 15。

执行记录（截至 2026-08-28）：**首次生产验收失败事实保留；修复代码、生产形态回归、双上游时间契约发布与新开放日自然验收均 PASS，Slice 14 已闭环**。

1. `MaintenanceActionDefinition` 已声明唯一 Heat readiness policy；历史 replay 仍不可调度。
2. Ops 已实现 SSE 开放日、收盘工作流 21:00/资金流工作流 20:00 的独立门槛、同一 TaskRun 必需节点、10 分钟复查、跨午夜目标日锁定、00:30 单一超时以及同一 schedule/action/trade_date 单次自动尝试。
3. app scheduler factory 已装配 Ops 上游证据与独立 `REPEATABLE READ, READ ONLY` biz preview；worker 继续在独立业务事务二次校验。`limit_list_d/suspend_d` 合法零行以来源节点自身成功为准，即使同一工作流因无关节点失败，仍可读取完成证据。
4. CLI `ops-scheduler-tick/serve` 已统一使用 app factory；未新增表、迁移、账号、连接、环境变量、ProbeRule、DG sensor 或外部 timer。
5. 2026-08-14 生产 schedule `36` 持续误判上游未齐，并于 2026-08-15 00:30 创建超时 TaskRun `8327`；生产上游节点和7张来源表实际齐备，Heat 结果仍停在 8 月 12 日。根因是旧 readiness 查询父 TaskRun `trade_date`，而19条生产工作流父意图均只有 `{"mode":"point"}`；旧测试 fixture 伪造该字段，原“本地通过”结论不再作为有效生产契约证据。
6. 修复后父 TaskRun 保持意图不变，dispatcher 将 resolver 解析后的真实日期写入数据集节点，readiness 逐节点核验日期；缺日期、错日期、早场、失败节点和跨 TaskRun 拼接均失败关闭。Heat/Ops/运行时/API/架构相关修复回归 115 项与文件级 Ruff 已通过。
7. 2026-08-27 发现第二个根因：原单值 `21:00` 同时约束收盘与 20:00 资金流工作流，导致后者自然成功仍永远不具备 readiness。现已改为收盘 `21:00`、资金流 `20:00` 的按 workflow 合同，缺失键、未知键和门槛前证据均 fail-closed；233 项受影响测试通过。
8. commit `6c16ac31` 已于 `2026-08-27 18:47+08` 在开放 TaskRun 为 0 的窗口发布；跳过 migration、前端构建、seed 与全部业务 worker 重启，仅重启 scheduler。生产 Alembic 保持 `20260827_000153`，schedule #4/#36 仍分别为工作日 20:00/21:15，运行时 factory 装配通过。该发布时点尚缺新的真实开放日自动 TaskRun、Heat read-back/hash 与同日幂等，现已由下一项自然证据关闭。
9. `2026-08-28` 只读验收确认 `2026-08-27` 自然链完整通过：schedule #4 的资金工作流 TaskRun `9633` 于 20:00 后成功，`moneyflow_ind_dc` 节点读取/保存 `1,031/1,031` 行、拒绝和去重均为 0；schedule #2 的收盘工作流 TaskRun `9644` 中 Heat 依赖节点 `daily/dc_index/dc_member/dc_daily/limit_list/suspend_d` 均成功且日期一致。schedule #36 随后仅创建一个 Heat TaskRun `9645`，readiness 为 `HEAT_READY` 并明确引用 `9633/9644`；任务成功发布 504 个板块事实，其中 476 个 `VALID`，28 个按业务质量契约保留为 `INVALID`（12 个 `HISTORY_INSUFFICIENT`、16 个 `MEMBER_COUNT_LOW`），不是 ingestion 源行丢失。表内 504 个板块代码唯一、只有一个 `calculated_at`，readiness/task 的 config/source/plan/content hash 一致；21:15 后连续 scheduler tick 均未再次建 TaskRun 或写出第二版。同日防重复与 read-back 因此通过，Slice 14 结论为 PASS。

### Slice 15：Figma 与首页像素验收（原 Slice 14，修正序号 7）

1. 使用 Slice 9 保存的同尺寸基线，按行业、概念、地域逐模块验收；每次只验一个 workspace，失败即回到 Slice 11 修正。
2. 覆盖三个 Ready 默认排序、全部非默认排序、三级选择、Heat INVALID/断点、地域 breadth、长名称、无领涨和全部状态。
3. 每张模块截图固定 `1564 × 680`，普通 UI 偏差 `<=2px`；图表内部绝对定位可保留，但不能改变外部 grid。
4. 保存 `1600 × 1200` 首页对照，确认左右栏、其它模块宽度和图表位置无视觉漂移；板块增高只影响后续文档流。
5. 输出节点 ID、基线、修改后图、差异图、偏差值和结论；没有截图证据不得签字。

关闭问题：A09-A16、A18 的视觉部分。

### Slice 16：候选版本部署、性能与观测验收（原 Slice 15，修正序号 8）

1. 前后端作为同一候选发布单元部署；部署前重新确认 Alembic 单 head，但没有新迁移时不得制造空迁移。
2. 同机房测量三 view 的 P50/P95/P99、payload、SQL round trips；门禁仍为 P95 `<250ms`、P99 `<500ms`、payload `<120KB`、SQL `<=8`。
3. 验收真实首页 smoke、`SO_*`、Heat 最新日/有效率/INVALID 原因、TaskRun/DG hierarchy 观测和错误/回滚路径。
4. 观测写入失败仍不得影响业务事务；应用失败不删除 serving 数据。

关闭问题：A18 的性能、生产与观测部分；同时复核 Slice 14 Heat schedule、最近开放日 TaskRun 与 Heat 覆盖持续正常。

### Slice 17：最终对账与 V2 验收关闭（原 Slice 16，修正序号 9）

1. 逐项复核 A01-A19：代码、测试、Figma、生产和文档证据缺一不可；不存在“部分关闭”。
2. 对账 benchmark、implementation design、LLD、M2 Gate 与实际实现，清零过时完成状态和相互冲突文案。
3. 完成产品、设计、前端、后端、数据、QA/发布签字；未签字不得写“完成”。
4. 最终交付修改节点、改动文件、仍保留绝对坐标区域、Auto Layout 范围、截图、性能、已知风险和是否具备 Web 正式发布条件。
5. 只有本 Slice 全部通过，才能把 Slice 6/7/8 和板块速览 V2 状态更新为“验收完成”。

关闭问题：A01-A19 全量。

---

## 11. 发布、回滚与观测

### 11.1 发布前硬门禁

1. 实施日 Alembic 单 head 已记录。
2. 全部生产来源真实只读对账通过，60 个有效交易日与 warm-up 集合已冻结；日期级缺口已清零，源站局部缺行已冻结为逐概念 `INVALID` 证据。
3. 层级 prod read-back 为 496/31/128/337 且 hash 一致。
4. Heat 至少 60 个有效交易日全部通过业务 contract、TaskRun 节点验收和 prod read-back；不以自然日、缺口日或 warm-up 凑数。
5. 最近交易日 Heat 来源日期一致、有效率/等级分布/日度跳变已人工审阅。
6. Slice 14 的单日 Heat 条件调度测试、唯一 active 生产 schedule、真实开放日自动发布/read-back 和同日幂等证据全部通过。
7. 现有连接复用、DG hierarchy 对象授权、组件访问边界和 Heat/Ops 双 Session 事务隔离测试通过，app 已注入 Heat executor/readiness evaluator，且依赖测试证明没有 `ops -> biz`。
8. 后端和前端真实 API、性能、六态和像素测试通过。
9. A01-A19 必须全部关闭并链接到代码/测试/Figma/生产证据；仅标记“已修复”而没有证据不算关闭。
10. Slice 9-17 必须按序完成。后置 Slice 失败时回到对应责任 Slice，不得通过跳过 Heat 自动化生产验收、截图、放宽像素、删除测试或倒改需求完成发布。
11. Figma 与需求仍有 7/20 日、板块详情入口或字段契约冲突时禁止构建候选版本。

### 11.2 回滚

1. 应用回滚到切换前版本；新表保留诊断，不删除、不清空。
2. Heat 单日业务事务失败时整日回滚，保留此前成功交易日；不得用 TaskRun 状态事务回滚业务数据。
3. TaskRun 遇到来源、contract、数据库写入或 read-back 失败时停止后续日期，记录失败节点；修复后按相同 plan hash 从最后成功日续跑。
4. 不恢复旧 DTO 别名，不让 V2 前端连接 V1 后端或反向混用。
5. Slice 14 自动化异常时先暂停唯一 Heat schedule，保留人工单日 TaskRun 作为运营恢复入口；不得删除 Heat 数据、关闭来源任务或另建 cron/sensor 绕过门禁。

### 11.3 观测

1. DG hierarchy：运行标识、Silver/prod 行数、31/128/337 层级计数、source hash 与 prod read-back hash。
2. Ops TaskRun：plan hash、目标/有效/warm-up/缺口日期、逐日节点状态、来源行数/hash、失败 reason 和续跑位置。
3. Heat 自动化：schedule 状态/next run、目标日、readiness reason、缺失上游节点、下一检查时间、触发/超时 TaskRun、同日去重和最近成功自动发布日。
4. API：`SO_*` 数量、view/status、响应耗时、SQL round trips、payload。
5. 数据：有效/无效 Heat 比例、invalid reason 分布、member/coverage 分布、等级分布和 score 日跳变。
6. 观测写入失败不得回滚、阻断或污染 Heat 及其它业务数据事务；仅影响本次观测状态。

---

## 12. 计划硬口径到代码与测试的映射

| 硬口径 | 代码落点 | 必须测试 |
|---|---|---|
| 盘后、非实时 | biz Heat materialization + API `tradeDate/asOf` | 无分钟字段、无盘中回退 |
| 行业三级各 Top5 | selection resolver + hierarchy query | 父子范围、5 行、无子级 |
| 概念 Top20/地域 31 | metrics/heat query | 精确上限/数量与稳定排序 |
| 领涨只来自 dc_index | metrics query | member Top1 不得覆盖 leader |
| 有效 A 股池 | prod query + 单一 golden contract | B 股/上市/退市/停牌/缺行情，不得访问 Lake |
| Heat EOD V1 | 策略配置中心 + pure contract | golden、缺分量、不补权、no-lookahead、未知配置严格失败 |
| Web 不算事实 | response DTO + presentation-only adapter | null 不补 0、badge 不推导 |
| 来源同日 | prod source query + quality contract | 错日必须阻断，不得以其它日期替代 |
| 原子发布 | 单日 prod DB transaction + read-back | 失败保留旧成功交易日 |
| Heat 每日自动化 | Ops 条件调度端口 + app readiness adapter + biz preview + scheduler factory | 21:15/10m/00:30、上游节点、非交易日、跨午夜、去重、超时和生产真实开放日 |
| biz/ops/app 边界 | ops executor port + app adapter + CLI factory consumer | ops 不得 import biz，CLI 不得直构未装配 worker，状态事务不得影响业务事务 |
| 现有连接复用与访问边界 | Web/Heat 使用 `DATABASE_URL`，DG 使用 `ProdPostgresWriteResource`；Heat/Ops 独立 Session/事务 | DG 写 Heat、Heat 写来源/hierarchy、Web DML、运行时 DDL/`TRUNCATE` 被测试阻止 |
| DG Heat 清零 | hierarchy-only Definitions + 静态扫描 | asset/partition/check/sensor/Gold/history CLI 不存在 |
| V1 清零 | schema/API/frontend 同提交 | 旧字段/旧组件/旧 fixture 不存在 |
| 60 日回放 | Ops TaskRun plan/apply | 旧到新、checkpoint、缺口/warm-up 不计数、失败停止 |
| Alembic 真 head | 实施步骤 | 单 head 与真实 down_revision |
| 排名行完整事实 | view-specific V2 rank DTO + metrics/heat query | 行业主指标随排序正确；概念/地域固定列在任意排序下都存在；旧通用 primary-only 清零 |
| 成员名称来源 | member query `dc_member.name` | security 同码异名不能覆盖 |
| 有效行情 close+pct | effective pool + Heat source query | 任一字段缺失均不算有效报价，两条链一致 |
| 默认/显式日期 | page/controller + query service | 默认延迟为 DELAYED，显式无事实为 EMPTY |
| 穷尽状态 | status resolver + controller | READY/PARTIAL/DELAYED/EMPTY/ERROR/FORBIDDEN/未知枚举 |
| Figma 三工作台 | 三个 workspace/rank/detail | 七行、四指标、Heat/breadth、长文本和同尺寸六态 |
| 股票交互 | leader/member navigation | 点击传播、键盘、无领涨文案，不新增板块详情入口 |
| 发布证据 | M2 Gate + 截图/性能/监控 | `<=2px`、P95/P99、SO_*、签字，缺一不得完成 |

---

## 13. 当前修正状态与拍板边界

1. Slice 9-14 已全部通过；这不等于新版 V2 整体完成。下一项只能在独立授权后进入 Slice 15 像素验收，候选部署/性能与最终对账依次保留在 Slice 16-17，不得跳步扩展其它新功能。
2. 已确认不需要重新拍板的修正：20 日 Heat 历史、三工作台正式结构、地域保留、四指标详情、独立 Heat 标签、有效池 `close + pct_chg`、`dc_member.name`、null 排名排除、默认/显式日期、六态骨架、股票详情跳转、像素与性能门禁。
3. 按现有批准范围，板块详情页和三个“进入××行情”入口不在本版本实现；Slice 9 已从正式 Figma 和文档删除该表达。只有用户明确改变范围时才重新设计路由。
4. A02 改变 Heat canonical 来源字段集合后的 `concept-heat-eod-v2` 与 60 日重放已完成；后续验收不得沿用旧 v1 作为当前生产证据。
5. 前后端修正后仍必须作为同一候选发布单元；最终证据包括真实 API smoke、同机房 P50/P95/P99、三视图/全状态同尺寸截图、`SO_*`/Heat 观测和角色签字。
6. 若真实数据与冻结产品口径出现新的冲突（例如地域枚举不再为 31、有效池无法用正式字段表达、Heat 大面积无效），停止对应 Slice 并回到产品评审；不得自行修改 Figma 或实现口径。

---

## 14. 版本记录

| 版本 | 日期 | 变更摘要 |
|---|---|---|
| v2.23 | 2026-08-28 | 记录 `2026-08-27` 真实开放日自然链：资金/收盘上游 TaskRun `9633/9644`、唯一 Heat TaskRun `9645`、504 行 read-back/hash 与连续 scheduler tick 防重复均通过；Slice 14 关闭为 PASS，下一步为独立授权的 Slice 15 |
| v2.22 | 2026-08-16 | 冻结概念 20 日 Heat 图坐标表达：每个有效柱顶上方 3px 显示原始热度值，第 1/5/10/15/20 槽显示 `MM-DD` 日期；INVALID 保留槽和刻度但不伪造柱/数值，外框尺寸不变 |
| v2.21 | 2026-08-16 | 按最新产品口径删除三个工作台排序工具栏中的说明性上下文，仅保留排序维度与页签；同步正式 Figma、前端结构和负向测试 |
| v2.20 | 2026-08-15 | 记录并冻结聚焦纠偏：Figma 概念五列固定网格、行业涨幅榜/跌幅榜、概念可见范围 `PARTIAL`；新增对应破坏性契约、实施顺序和正反测试门禁 |
| v2.19 | 2026-08-15 | 记录生产 TaskRun `8327` 超时与测试伪通过根因；父 TaskRun 保留 point 意图，dispatcher 将解析后的日期写入节点，readiness 逐节点核验目标日，生产形态正反例与修复回归通过，部署/恢复/下一开放日验收仍 OPEN |
| v2.18 | 2026-08-14 | Slice 14 代码与本地回归完成：Heat 条件调度、上游 TaskRunNode 证据、app 只读 preview、跨午夜/超时/去重、CLI factory 和零行证据已落地；固定总门禁 307 项通过，生产 schedule 与真实开放日验收继续 OPEN |
| v2.17 | 2026-08-14 | 新增 Slice 14 Heat 盘后自动化 LLD：21:15 首检、10 分钟复查至 00:30、Ops 上游节点 + biz preview 两层门禁、app scheduler factory、幂等与超时 issue；原 Slice 14-16 后移为 Slice 15-17 |
| v2.16 | 2026-08-13 | 完成 Slice 13：A01-A19 测试 ID 100% 映射，后端/Heat/Ops/架构核心 109 项与静态护栏 5 项合计 114 项、Wealth 223 项、DG 9 项及 typecheck/build/Ruff/Definitions/docs/diff 全通过；下一步固定 Slice 14 |
| v2.15 | 2026-08-13 | 完成 Slice 12：正式 PLAN `8208`、APPLY `8210`、逐日 read-back 与幂等重放 `8213`；60 日 29,665 行、逐日版本/计数/hash 0 差异、重放 0 写入，下一步固定 Slice 13 |
| v2.14 | 2026-08-13 | 完成 Slice 11 前端纠偏：view-specific 类型与三工作台、正式模块骨架、七行滚动、20 日断点、地域 breadth、股票导航、默认日期和穷尽状态通过 11 项专项、198 项全量、typecheck/build 与本地真实页面浏览器验收；下一步固定 Slice 12 |
| v2.13 | 2026-08-13 | 完成 Slice 10 后端纠偏：三类 rank DTO、`close + pct_chg`、`dc_member.name`、TopN null、来源状态、默认/显式日期、后端 ERROR 契约和 Heat v2 版本门禁已实现；70 项回归和生产只读 60 日 close/pct 核验通过，下一步固定 Slice 11 |
| v2.12 | 2026-08-13 | 完成 Slice 9：保存六个正式节点同尺寸 before/after 与属性清单；概念 Heat 改为 20 日、移除三个板块详情入口、补齐 view-specific 字段和稳定状态说明；同步四份 V2 文档，A01-A19 保持 OPEN，下一步固定 Slice 10 |
| v2.11 | 2026-08-13 | 文档对账审计纠偏：保留 Slice 1-5 生产事实，撤销 Slice 6-8 验收完成结论；登记 A01-A19 后端、数据、Figma、前端、测试、性能与发布偏差；新增 Slice 9-16 修正顺序、逐项关闭证据和禁止跳步门禁；将 DG Ruff 收窄为本需求文件范围 |
| v2.10 | 2026-08-13 | 记录 Slice 7 前端 V2 实施：判别式 API 类型、独立 controller、三工作台、地域涨跌分布、六态、键盘与 stale 防护完成，V1 DTO/adapter/fixture 清零；Wealth 192 项测试、typecheck/build 通过，真实页面像素/同机房性能待部署后验收 |
| v2.9 | 2026-08-13 | 记录 Slice 6 后端 V2 实施、86 项回归和生产只读三视图验收；应用 SQL 7/8/6、payload 均达标，同机房 P95 待原子发布；后端禁止单独部署 |
| v2.8 | 2026-08-13 | 记录正式 PLAN `8149`、首次 APPLY `8152` 与幂等重放 `8153` 的生产结果：60 日 29,665 行、逐日 hash 0 差异、重放 0 写入、物化 P95 约 11 秒；Slice 5 完成，下一步为后端 V2 |
| v2.7 | 2026-08-13 | 记录首次正式 PLAN TaskRun `8147` 的门禁未通过结果：生产资金流 85 日完整，根因是代码把 `content_type='概念'` 错写成 `概念板块`；修正来源过滤与测试 fixture，并新增错误枚举负例，待重新部署复跑 PLAN |
| v2.6 | 2026-08-13 | 记录 Slice 5 本地实现：严格 Heat 配置、prod 来源与有效池、两位最终分、REPEATABLE READ、单日发布/read-back、PLAN/APPLY 与 snapshot integrity、断点跳过、Ops/app/CLI 双事务装配及本地回归；生产回放仍待部署后分阶段验收 |
| v2.5 | 2026-08-13 | 记录 hierarchy 正式 Run 与 hash read-back、Slice 4 冻结 60+25 日并完成九张 prod 来源审计；日期级缺口清零，源站现状局部缺行改为逐概念 `INVALID`，并将历史审计限制为最多 10 日批次 |
| v2.4 | 2026-08-13 | 记录生产已升级至单 head `20260813_000135`，两表结构与 hierarchy 精确授权验收通过；Slice 3 hierarchy publisher 已实施并通过隔离测试，正式生产发布仍待部署后单独执行 |
| v2.3 | 2026-08-13 | 记录 Slice 1/2 已实施的 ORM、模型注册、revision `20260813_000134` 与本地约束/迁移测试；本提交 head 为 `000134`，生产仍为 `000133`，生产迁移与后续阶段未执行 |
| v2.2 | 2026-08-13 | 撤回三账号/三 DSN 设计；Web/Heat 复用现有应用连接，DG 复用现有 prod write resource；保留 Heat/Ops 双 Session 事务隔离和既有 `lake_raw_writer` hierarchy 单表授权 |
| v2.1 | 2026-08-13 | Heat 改为 biz prod-native 计算与直接发布；ops 仅承载执行意图/状态/观测，由 app 注入执行器；删除 DG Heat、Gold 双份事实和 Lake/prod 双 adapter；三账号/三 DSN 门禁已由 v2.2 撤回 |
| v2 | 2026-08-12 | 历史基线：曾按 DG Heat/Gold 与 Lake 优先设计，已被 v2.1 全面替代，不得用于实施 |
