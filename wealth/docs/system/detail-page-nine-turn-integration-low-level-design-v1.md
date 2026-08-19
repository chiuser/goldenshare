# 股票与主要指数详情页九转接入低层设计（LLD）v1

> 状态：M0～M5、M6-0、M6-A、M6-B 与 M6-C 已完成；M6-D 最终全链路验收尚未完成。2026-08-16 指数 Technical 固定六周期九转摘要补充需求的 Figma、文档、前端代码与本地验收已完成，仍待纳入 M6-D 的生产专项复验。生产仓库与 Web 已运行 `9fec9a26f09e5ff72dbd75572bf6af24f72f8410`，日线九转路由受认证保护，分钟九转路由保持 404。M3-C-Minute 页面/API/视觉行为与“股票分钟 QFQ 九转去价格字段”S0～S5 均已完成。股票日线 QFQ 九转去价格专项 D0～D6 已完成：两个日线 writer 已按 serving→Gold 顺序恢复为唯一 `RUNNING`，`2026-08-13/14/17` 三天 Gold 与 serving 共六个自然 run 全部 `SUCCESS`，16,619 行 Lake/Prod、六列/八列合同和 blocking checks 全部通过。21:34 的 D6-3 DELAYED 发生在当日 `stk_factor_pro` 工作流实际执行前，22:54 后 `equity_factor_pro` 已覆盖 `2026-08-17` 共 5,538 行，生产 `603806.SH` READY 页面复验通过。三个指数 sensor 当前也均为唯一 `RUNNING`，`2026-08-17` 日线、六分钟与 serving 三个自然 run 全部 `SUCCESS`。
>
> 上游方案：[股票与主要指数详情页九转接入总方案 v1](./detail-page-nine-turn-integration-implementation-design-v1.md)
>
> 异常码：[异常码注册表](./exception-code-registry.md)
>
> M2 门禁：[股票详情九转纵向切片 M2 编码前门禁 v1](./detail-page-nine-turn-m2-coding-gate-v1.md)
>
> 正式设计：[Goldenshare Web](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?m=dev)

---

## 1. 目的、范围与结论

本文把已确认的九转产品合同和正式 Figma 细化为可逐文件编码、逐项测试和逐阶段验收的低层设计。

本文最初只形成设计，M2 至 M4-B 及 2026-08-15 股票分钟 schema 修正 S0～S5 已按分阶段授权实施并完成各自验收。执行边界为：

1. S2 先生成并评审只读计划；只有计划 `should_stop=false`，才依次执行 S3 正式 Lake、S4 runless event 和 S5 sensor/Reader 恢复。本轮执行没有跨阶段并行或跳过门禁。
2. 当前正式事实以第 20.7 节的最终报告为准；下文 S0～S5 的审批语句保留为已执行门禁，不再表示待授权工作。
3. 2026-08-17 股票日线去价格专项已完成 D0～D6；D3 已完成 staging candidate、全量审计、3,066 个正式文件原子提升与六列物理终验，D4 已完成 Gold events，D5-A 已部署 `9fec9a26...` 并执行生产 migration `20260816_000137`，D5-B 已完成 serving events、认证请求/DTO 与生产页面视觉验收，D6-0 已纠正 Gold sensor 合同，D6-1 已完成正式只读门禁，D6-2 已恢复两个 writer并让三个缺口交易日通过自然链路完成 Gold 与 serving 发布，D6-3 已在正常上游产出后通过 READY 页面复验。
4. 正式全量重建只允许使用已冻结计划、正式 staging candidate、聚合审计和逐文件原子替换；禁止预删正式文件、旧 Lake、Kopia 或 Python 逐行处理。
5. M4-B 指数资产、正式 Lake、Dagster events、生产 migration 和日线 serving 已完成；本专项不得顺带修改指数九转资产。

最终实现结构冻结为：

1. 股票沿用五个自主前复权 Gold 九转 asset key；日线和四个分钟资产最终都只保存业务键、计数和信号，不保存任何价格或量额字段；不消费 Tushare 九转事实。
2. 指数已建成日线一个、分钟六个 Gold 九转资产；不创建 1 分钟资产。
3. 所有分钟 K 线的业务消费与下游指标计算统一使用规范化 Gold：股票为 `gold/quote/stk_mins_qfq`，主要指数为 `gold/quote/major_index_mins`；Silver 只作为 Gold 上游，不能成为 Web、九转 Reader 或九转资产的直接事实源。
4. 日线九转由独立 PostgreSQL serving 表向所有 Web 环境提供；Web 不直读生产 Lake。
5. 分钟九转只在本地开发能力满足时读取正式 Lake 的 Gold；生产不 import Reader，路由为 404。
6. 四个 HTTP 入口共享一套 DTO、marker 映射、状态和异常语义。
7. 前端复用一个请求注册表、一个 `NineTurnMarkerPrimitive` 和现有 `DetailChartWorkspace`。
8. 九转图层与 K 线、分钟技术指标、趋势通道独立降级；失败不清空其它内容。

## 2. M0 评审收口

### 2.1 退出条件结果

| M0 门禁 | 结果 | 证据与结论 |
|---|---|---|
| 产品周期矩阵 | 通过 | 股票 day/30/60/90/120；指数 day/5/15/30/60/90/120；其余周期九转零请求 |
| 公式与展示映射 | 通过 | lag=4、threshold=9、formulaVersion=1；资产可计数 10+，页面只画 1～9 |
| 股票事实源 | 通过 | 五个自主 QFQ Gold 资产、五个 blocking checks 与正式历史文件已存在；日线和四个支持分钟周期的页面接入及分钟八列物理合同迁移均已完成；日线 3,066 个正式文件、新版 Gold/serving events、生产 serving 无价格 migration、代码部署、认证请求/DTO 与生产页面视觉验收也已完成 |
| 指数建设边界 | 通过 | 七个资产、正式历史和日线 serving 已完成；物理 11-code seed 不变，产品严格按 Wealth 10-code allowlist |
| 北证50边界 | 通过 | `899050.BJ` 支持日线；分钟源不覆盖时返回局部 SOURCE EMPTY，不补造 |
| 生产与本地边界 | 通过 | 日线走 PostgreSQL serving；分钟仅 local/dev 读取正式 Lake 的规范化 Gold；生产分钟路由 404 |
| 正式视觉 | 通过 | 股票/指数 Loaded、Components、States 六个页面和共享 marker 组件均可作为开发事实源 |
| 状态与降级 | 通过 | Loading/Empty/Error/Partial/Forbidden/Unsupported/Source Empty 均只影响九转模块 |
| 交易边界 | 通过 | 九转不触发买卖、机会、仓位、风险评级或交易计划 |

M0 通过表示产品、视觉和架构合同可以进入 LLD，不表示指数资产、API 或页面功能已经实现。

### 2.2 Figma 收口记录

M0 节点树审计确认：

1. 股票 Loaded 根 `345:3`、股票组件合同 `629:516`、股票状态矩阵 `631:516`。
2. 指数 Basic/Weights/Technical 根 `417:2`、`423:2`、`423:910`。
3. 指数组件合同 `633:545`、指数状态矩阵 `634:558`。
4. 共享 marker component set 为 `406:10`，variants 为 `406:2/4/6/8`。

本轮只修正了四个不会改变视觉的命名漂移：

| 节点 | 修改后 |
|---|---|
| `631:516` | `Nine Turn / Stock / Layer States` |
| `631:517` | `股票详情 · 九转图层状态` |
| `634:558` | `Nine Turn / Index / Layer States` |
| `634:559` | `指数详情 · 九转图层状态` |

原可见标题中的“M6”会与本方案最终发布阶段 M6 混淆；股票状态根名称中的 `1600x1000` 也与实际节点高度不一致。修改未改变节点尺寸、布局、颜色、字体或业务内容。

## 3. 不可变硬口径

| 编号 | 硬口径 | 实现落点 | 负向测试 |
|---|---|---|---|
| C01 | 股票只读自主 QFQ Gold/serving | stock Reader、publisher、SQL | Tushare view 不得出现在查询或 fallback |
| C02 | 指数使用不复权 close | index asset、serving、DTO | 不得使用 qfq 字段或客户端复权 |
| C03 | 资产保留 10+，页面只画 1～9 | asset schema、Biz marker mapper | 10、11、19 不生成 marker |
| C04 | 股票 1/5/15 不提供九转 | capability、controller、API validation | 三周期网络请求数为 0 |
| C05 | 指数 1 分钟不提供九转 | capability、controller、API validation | 1 分钟网络请求数为 0 |
| C06 | 九转独立请求、独立缓存、独立状态 | 四个 endpoint、series registry | 九转失败不重新请求或清空 K 线 |
| C07 | 产品指数只认运行时 10-code 配置 | universe service | `000680.SH` HTTP 404 |
| C08 | 物理指数 seed 仍为 11 code | Orchestrator asset | 九转专项不得修改现有 seed |
| C09 | `899050.BJ` 分钟不补造 | minute Reader、status resolver | 六分钟频率均局部 EMPTY/SOURCE_NOT_READY |
| C10 | 日线生产只读 PostgreSQL serving | daily query、ORM | Web 不读取本机 Lake 或旧 Tushare view |
| C11 | 分钟只读正式 Lake 的规范化 Gold | capability、Reader | Silver、旧 Lake、staging、technical state、任意路径均拒绝 |
| C12 | 生产不挂分钟九转路由 | App composition root | 生产四个分钟 URL 均 404 |
| C13 | 前端不计算九转 | adapter、primitive | 前端无 lag/segment/count 公式 |
| C14 | marker 不参与纵轴 autoscale | primitive | `autoscaleInfo()` 始终返回 null |
| C15 | 上证日线允许双 primitive | Index chart adapter | 趋势通道任一状态不阻塞九转，反之亦然 |
| C16 | 没有交易动作 | UI、事件测试 | marker、摘要无 click/交易 handler |
| C17 | 所有分钟业务事实只认规范化 Gold | stock/index minute Reader、index minute 九转 asset deps | Web 与九转代码不得引用 Silver 分钟路径或 asset key |
| C18 | 股票日线和分钟九转正式资产均不保存价格或量额 | daily/minute schema、writer、catalog、check、Reader、serving | `close_qfq/open/high/low/vol/amount/change/pct_chg` 不得出现在正式股票九转 Gold、serving 或 API 内部结果 |
| C19 | 股票日线与分钟公式仍读取对应 Gold QFQ `close` | formula adapter、history context | 禁止从目标九转文件、Silver、旧 Lake、serving 或前端取得价格输入 |
| C20 | 股票九转 check 只校验结构、键、源键覆盖和九转值域 | daily/minute integrity、readiness、serving check | 不检查目标价格、不比较源价格、不在生产 check 重算公式 |
| C21 | 前复权重算不触发股票九转 repair | factor repair、sensor、history planner | 禁止以 QFQ 价格值变化、size/mtime 变化或价格差异作为九转历史重建条件 |
| C22 | 正式股票九转不得新旧 schema 混存 | rebuild planner、candidate audit、atomic promotion、Reader、publisher | 任一旧 schema 文件、字段差异、键/行数/计数/信号异常立即停止，禁止对外开放部分切换结果 |
| C23 | 股票日线历史迁移只做列投影 | daily migration planner、candidate builder、audit | 禁止在去价格迁移中重算公式、改写计数或信号；迁移前后键/计数/信号必须逐项一致 |

### 3.1 分钟 K 线数据集白名单

股票分钟 K 线允许读取的正式 Dagster asset key 只有：

```text
gold_stk_mins_qfq_1m
gold_stk_mins_qfq_5m
gold_stk_mins_qfq_15m
gold_stk_mins_qfq_30m
gold_stk_mins_qfq_60m
gold_stk_mins_qfq_90m
gold_stk_mins_qfq_120m
```

物理根固定为 `gold/quote/stk_mins_qfq`。股票九转 Reader 虽只消费30/60/90/120分钟，但必须与页面 K 线共用上述同频 Gold 数据集；不得为九转另选行情源。

主要指数分钟 K 线允许读取的正式 Dagster asset key 只有：

```text
gold_major_index_mins_1m
gold_major_index_mins_5m
gold_major_index_mins_15m
gold_major_index_mins_30m
gold_major_index_mins_60m
gold_major_index_mins_90m
gold_major_index_mins_120m
```

物理根固定为 `gold/quote/major_index_mins`。指数分钟九转只消费5/15/30/60/90/120分钟对应的同频 Gold；1分钟 Gold 只供 K 线等已获支持的业务消费，不创建1分钟九转资产。

代码门禁必须按以上十四个 asset key 做白名单断言，并对 `silver_stk_mins_*`、`silver_major_index_mins_*` 以及可由请求选择数据层的实现做负向扫描。

## 4. 当前代码审计

### 4.1 CodeGraph 影响面

本轮使用仓库根 CodeGraph 索引审计了：

1. `StockDetailPage -> stock page-init/kline/minute clients -> StockChartWorkspace/StockMinuteChartWorkspace`。
2. `IndexDetailPage -> useIndexDetailController/useIndexMinuteSeries -> IndexChartWorkspace/IndexMinuteChartWorkspace/IndexTechnicalTab`。
3. `DetailChartWorkspace -> mainPrimitives -> TrendChannelPanePrimitive -> viewport/zoom/crosshair`。
4. 四组现有 stock/index daily/minute FastAPI、query service、schema、local capability 和 Lake Reader。
5. 股票 QFQ 九转 assets/checks/jobs/sensors、主要指数分钟技术资产族和 prod serving publisher 模式。
6. 股票日线 `GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA -> writer/integrity/history -> prod publisher/table/model/query -> NineTurnSeriesDto` 的完整价格字段消费者链。

影响面结论：

1. 不修改 `src/platform` 或 `src/operations`，依赖方向保持 `foundation <- biz <- app`。
2. Web 代码不能 import `lake_console/orchestrator`；路径和物理合同必须在 Foundation 独立冻结。
3. Orchestrator 不能 import Web 的 schema、universe service 或 React 类型。
4. `IndexDetailCapabilitiesDto.supportsNineTurn` 与前端 TS 已在 S7/M5 升级为 `true`；`nineTurnPeriods` 由 page-init 和 router 共用的 capability resolver 生成，生产只有 day，local/dev 能力满足时增加 5/15/30/60/90/120。
5. 股票 page-init 已在 M2 增加九转 capability：日线常驻；正式本地 Gold 能力满足时增加 30/60/90/120。

### 4.2 可复用能力

| 现有能力 | 复用方式 |
|---|---|
| `gold_stock_daily_qfq_nineturn` 与四个分钟资产 | 继续作为股票九转事实；公开 asset key、路径和公式语义不变。分钟已完成无价格迁移；日线按第 21 节从七列切换为六列无价格合同 |
| `prod_core_wealth_market_turnover` 发布模式 | 复用“Gold 校验 -> 事务替换 -> read-back”边界，不复用业务 schema |
| `resolve_local_minute_capability` | 复用环境、开关、Lake 和 DuckDB 基础门禁；九转增加正式根和目标目录检查 |
| `IndexDetailUniverseService` | 指数四个九转 endpoint 的唯一产品 allowlist |
| stock/index minute Reader 的分页模式 | 复用 limit+1、日期裁剪、稳定 cursor、5MB 门禁原则 |
| `DetailChartWorkspace.mainPrimitives` | 同时挂趋势和九转；shared workspace 不理解九转公式 |
| `TrendChannelPanePrimitive` | 复用 primitive 生命周期和可见范围测试模式，不复用 autoscale 行为 |
| `useIndexMinuteSeries` | 复用 AbortController、request id、按 code/freq/endDate 缓存思想 |

### 4.3 已发现缺口

1. 股票与指数日线/分钟九转 Reader、DTO、endpoint 和页面消费均已实现；S7/M5 已完成指数 capability、日线/分钟图层、Technical 摘要与局部状态接入。
2. S1 已将 `GOLD_STK_MINS_QFQ_NINETURN_SCHEMA`、分钟 writer、asset metadata、合并 integrity helper、历史 bootstrap/canonical audit、Foundation Reader 和测试一次性切换为八列合同；asset key、path、job、sensor、DTO 与 API 合同未改变。
3. `audit_qfq_nineturn_integrity(...)` 仍按 `freq is None` 分流日线和分钟 schema/时间键，但两个股票周期族现已统一只验证精确 schema、分区、源/目标唯一键、源键覆盖、计数和信号值域；日线价格正值、`source_value_consistency` 和生产公式重算均已删除，源重复键继续 fail closed。
4. 分钟 Reader 的 column specs、校验 SQL、join 投影和内部 rows 已删除 `close_qfq`；K 线价格仍只来自 `gold_stk_mins_qfq`。含价格的旧九列分钟文件会被明确拒绝，不存在兼容分支。
5. 历史 bootstrap 的 compact context 继续保存前四根 `close_qfq`，这是公式跨批计算所需的 staging sidecar，不是正式资产；candidate/final audit 不再读取或比较目标价格。
6. 正式分钟九转文件已全部切换为八列 schema。最终范围为四频各 3,068 个文件、覆盖 2014-01-02～2026-08-14，共 12,272 个目标文件、197,753,897 行；旧九列规模只保留为 S2 前预算基线。
7. 股票日线 Gold、ORM、publisher、hash、check 和 Biz 查询已切换为无价格合同；正式 3,066 个 Lake 文件与生产 `core_serving.equity_qfq_nineturn_daily` 也已完成无价格物理迁移，生产 Web 已部署 `9fec9a26...`。页面 DTO 始终不输出价格；D5-B serving events、认证请求/DTO 与生产页面视觉验收均已通过。

### 4.4 `freq` 物理类型门禁结论

2026-08-13 对四个最新正式股票分钟九转文件做了只读复核：

1. `read_parquet(path)` 自动开启 Hive 路径推断时，路径 `freq=30` 会生成 `BIGINT` 分区列并覆盖同名文件列。
2. `read_parquet(path, hive_partitioning=false)` 读取真实 Parquet schema 时，四个频率的 `freq` 均为 `INTEGER`。
3. 真实物理文件、writer 的 `CAST(freq AS INTEGER)` 与 `GOLD_STK_MINS_QFQ_NINETURN_SCHEMA` 一致。

该结论只证明 `freq INTEGER` 无需调整。2026-08-15 去价格专项已重写四频正式文件并删除 `close_qfq`；所有 Reader、check 和验收 SQL继续显式使用 `hive_partitioning=false`。

### 4.5 当前 sensor 状态与解释口径（快照截至 2026-08-15 12:58，Asia/Shanghai）

本轮通过正式 `DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home` 只读核验六个九转 sensor。代码中的六个定义都固定 `default_status=STOPPED`，但这只是没有持久化实例状态时的初始值：

本节保留 2026-08-15 12:58 的历史实例快照，不是本文更新时的实时状态。当时的文档审计没有获批读取正式 Dagster instance，因此未运行 `dg` 或 instance 查询；静态代码中的六个 `default_status=STOPPED` 只证明默认合同没有变化，不能用来覆盖下列历史持久化状态。M6-B 第一段已在当天 19:39 后完成新的只读刷新，当前指数状态和启用计划以第 15.7 节为准。

1. 三个股票 sensor 当前都有持久化 `RUNNING`：`gold_stock_daily_qfq_nineturn_update_job_sensor`、`gold_stk_mins_qfq_nineturn_update_job_sensor`、`prod_core_stock_daily_qfq_nineturn_sync_job_sensor`。
2. 最近 tick 分别为：日线 Gold 12:56:45，仍因 2026-08-03 目标 check 未通过而 `SKIPPED`；分钟 Gold 12:13:01，`SKIPPED — 最近 5 个分钟前复权九转分区均已 ready`；日线 serving 12:58:33，空结果 `SKIPPED`。三者 run 数均为 0。
3. 三个指数 sensor 均无持久化启动状态，因此实际沿用定义默认 `STOPPED`：`gold_major_index_daily_nineturn_update_job_sensor`、`gold_major_index_mins_nineturn_update_job_sensor`、`prod_core_index_daily_nineturn_sync_job_sensor`。
4. 去价格专项按批准范围停止并恢复了分钟 sensor，reload 后只保留正式 workspace origin；没有改变日线或指数 sensor。分钟 sensor 已完成一次自然评估并确认最近 5 日 ready；2026-08-15 为周六，下一交易日新增分区继续作为运维观察点，不把周末空窗伪装成新分区验收。日线 2026-08-13/14 因子修订后的价格漂移和自然更新阻塞已按用户决定移交后续专项，不属于本轮 M3-C 前端退出条件，但也不得写成已恢复。

正式实例的详细逐 sensor 快照以[总方案第 3.3 节](./detail-page-nine-turn-integration-implementation-design-v1.md)为准。本文其余章节出现的“默认 `STOPPED`”只描述定义合同；出现的历史启停记录只描述当时动作。未重新执行实例只读审计前，不得把本节快照改写成实时状态。

## 5. 目标架构

```text
Dagster Gold
  stock daily + 30/60/90/120m (existing)
  index daily + 5/15/30/60/90/120m (implemented)
       |
       +-- daily -> dedicated prod serving assets -> PostgreSQL tables
       |                                               |
       |                                               v
       |                                      DailyNineTurnQuery
       |
       +-- minute -> formal Lake -> local-only NineTurnLakeReader
                                                   |
                                                   v
FastAPI four endpoints -> NineTurnSeriesDto -> useNineTurnSeriesRegistry
                                              |               |
                                              v               v
                                 NineTurnMarkerPrimitive   Index Technical summary
```

职责边界：

1. Orchestrator 计算、检查、分区并发布九转事实。
2. Foundation 只读取 PostgreSQL 或正式 Lake，输出内部 row/page，不生成页面文案。
3. Biz 校验对象池、归一 marker、对齐时间键、决定数据状态和 DTO。
4. App 只装配常驻日线路由和条件分钟路由。
5. Wealth 管理请求、缓存、竞态、局部状态和绘图。

## 6. 数据资产与物理合同

### 6.1 统一公式内核

新增纯 SQL 公式内核：

```text
lake_console/orchestrator/src/orchestrator/defs/nineturn_formula.py
```

输入规范化为：

```text
subject_code, bar_date, bar_time, close_value
```

输出语义为：

```text
up_count, down_count, nine_up_turn, nine_down_turn
```

实施约束：

1. 只抽取现有 `qfq_nineturn.py` 的纯 CTE 公式，不改变 lag、方向、segment 或 seed 语义。
2. 现有股票 public function、asset key、path 和测试名称保持不变；schema 只按已批准的去价格合同收窄，不改资产身份。
3. 股票日线和分钟 adapter 都把对应 Gold QFQ `close` 映射到内部 `close_value`，但正式股票九转结果均不再投影价格；指数 adapter 继续把不复权 `close` 映射到 `close_value` 并按既有指数合同输出。
4. 抽取前后现有股票 golden 输出必须逐行完全相同；不允许复制第二份公式。

M4-A 实施结果：

1. `nineturn_formula.py` 已提供唯一的 `build_nineturn_formula_select_sql`，只使用上述四个规范化行情字段；日线、分钟、全历史、目标窗口和 compact seed 共用同一套 direction、segment、count 与 signal CTE。
2. `qfq_nineturn.py` 保留全部既有 public function，只负责把 `ts_code/trade_date/bar_time/close_qfq` 投影为规范化输入，并把内核结果投影回各自 schema；分钟已只输出业务键、计数和信号，日线将在第 21 节实现后采用相同无价格结果边界。
3. 公式 SQL 已从股票模块清零；静态门禁要求 `LAG(close_value)`、`segment_start`、`continued_count` 在共享内核中各只有一份，防止未来重新分叉。
4. 新增共享合同、seeded window 和股票 adapter 逐行对账测试；原受保护 golden、历史批次、fallback、writer、asset、check、job 与 readiness 回归保持通过。
5. 本阶段没有新增指数 asset/check/job/sensor/path，没有读取或写入正式 Lake，也没有运行 Dagster Definitions、materialize、backfill 或 sensor。

### 6.2 股票资产

沿用：

```text
gold_stock_daily_qfq_nineturn
gold_stk_mins_qfq_nineturn_30m
gold_stk_mins_qfq_nineturn_60m
gold_stk_mins_qfq_nineturn_90m
gold_stk_mins_qfq_nineturn_120m
```

日线最终 schema 冻结为：

```text
ts_code VARCHAR
trade_date DATE
up_count INTEGER
down_count INTEGER
nine_up_turn VARCHAR nullable
nine_down_turn VARCHAR nullable
```

分钟最终 schema 独立冻结为：

```text
ts_code VARCHAR
freq INTEGER
trade_date DATE
trade_time TIMESTAMP
up_count INTEGER
down_count INTEGER
nine_up_turn VARCHAR nullable
nine_down_turn VARCHAR nullable
```

股票日线和分钟正式资产都不保存 `close_qfq/open/high/low/vol/amount/change/pct_chg`。日线与分钟唯一键分别为 `(ts_code, trade_date)` 与 `(ts_code, freq, trade_time)`。

日线计算仍从 `gold_stock_daily_qfq.close`、分钟计算仍从同频 `gold_stk_mins_qfq_<freq>m.close` 读取前复权收盘价，统一公式内核内部继续使用 `close_value`。上一分区正式九转文件只提供 `up_count/down_count` seed；跨批所需前四根价格从 QFQ 源或 `/Volumes/datasource/data_lake_staging` 下的 compact context sidecar 取得。sidecar 可保存 `close_qfq`，但它不是正式资产、不得被 Web 或业务查询读取。

分钟合并 blocking check 固定检查：

1. 文件存在、非空且 schema 与上述八列精确一致。
2. `trade_date/freq/trade_time` 与目标分区一致，`trade_time` 属于 `trade_date`。
3. `(ts_code, freq, trade_time)` 非空且唯一，QFQ 源键与输出键集合完全一致。
4. `up_count/down_count` 非负且不能同时大于零。
5. `nine_up_turn` 只能是 `+9` 或空，`nine_down_turn` 只能是 `-9` 或空；信号与计数值域一致且两类信号不能同时存在。

股票日线和分钟 check 都删除 `close_qfq` 正数检查、`source_value_consistency` 价格比较和生产环境公式重算。公式正确性由受保护 golden/fixture 保证；生产 check 只验证本次文件与源键事实。指数日线/分钟合同不随本专项改变。

### 6.3 指数资产

现有正式资产：

```text
gold_major_index_daily_nineturn
gold_major_index_mins_nineturn_5m
gold_major_index_mins_nineturn_15m
gold_major_index_mins_nineturn_30m
gold_major_index_mins_nineturn_60m
gold_major_index_mins_nineturn_90m
gold_major_index_mins_nineturn_120m
```

上游：

1. 日线依赖 `gold_market_major_indices_daily`，直接沿用已版本化 11-code seed 投影和不复权 close。
2. 分钟分别依赖同频 `gold_major_index_mins_<freq>m`；不得直接依赖 Silver。九转与详情页当前分钟 K 线共享同一个规范化 Gold 时间键和 close 事实。
3. 不创建 1 分钟九转 asset、check、job、sensor、path 或 API 支持。

路径：

```text
gold/indicator/major_index_daily_nineturn/trade_date=<date>/part-000.parquet
gold/indicator/major_index_mins_nineturn/freq=<freq>/trade_date=<date>/part-000.parquet
```

日线 schema：

```text
ts_code VARCHAR
trade_date DATE
close DOUBLE
up_count INTEGER
down_count INTEGER
nine_up_turn VARCHAR nullable
nine_down_turn VARCHAR nullable
```

分钟 schema：

```text
ts_code VARCHAR
freq INTEGER
trade_date DATE
trade_time TIMESTAMP
close DOUBLE
up_count INTEGER
down_count INTEGER
nine_up_turn VARCHAR nullable
nine_down_turn VARCHAR nullable
```

分区与范围：

1. 日线使用 `cn_a_index_trade_days`，物理输出当前 seed 的有效 11 code。
2. 分钟使用 `cn_major_index_mins_trade_days`，物理输出规范化 Gold 实际覆盖代码；当前明确排除 `899050.BJ`，可包含 `000680.SH`。
3. API 不从文件反推产品名单，始终再次执行 Wealth 10-code allowlist。

每个资产对应一个 blocking integrity check，共七个。check 只验证文件、schema、分区、唯一键、值域、源键覆盖和公式版本元数据，不在 check 内重新计算公式。

### 6.4 job、sensor 与历史构建

正式名称：

```text
gold_major_index_daily_nineturn_update_job
gold_major_index_mins_nineturn_update_job
gold_major_index_daily_nineturn_update_job_sensor
gold_major_index_mins_nineturn_update_job_sensor
```

约束：

1. 分钟 job 精确选择六个资产和六个 checks。
2. sensor 以同分区上游 materialization + blocking checks 通过为唯一触发门禁。
3. sensor 定义初始默认 `STOPPED`；正式实例持久化状态是独立运行事实，当前状态见第 4.5 节。M6 仍必须完成自然触发验收。
4. 历史构建使用有界批次、compact seed、逐文件原子提升和 checkpoint；不全历史单 SQL 常驻内存。
5. 本文不授权任何历史写入、动态分区登记或 runless event。

## 7. 日线 PostgreSQL serving

### 7.1 最终表结构

正式使用两张独立物理表，不复用旧 Tushare view：

```text
core_serving.equity_qfq_nineturn_daily
core_serving.index_nineturn_daily
```

股票表：

```text
ts_code VARCHAR(16) NOT NULL
trade_date DATE NOT NULL
up_count INTEGER NOT NULL
down_count INTEGER NOT NULL
nine_up_turn VARCHAR(2) NULL
nine_down_turn VARCHAR(2) NULL
formula_version SMALLINT NOT NULL
published_at TIMESTAMPTZ NOT NULL
PRIMARY KEY (ts_code, trade_date)
INDEX (trade_date, ts_code)
```

指数表继续包含自己的 `close DOUBLE PRECISION`，其余字段与主键同既有指数合同；股票日线去价格专项不得修改指数表。

约束：

1. 表不保存 OHLC、量额、无意义的 nullable `freq` 或页面 marker。
2. lag=4、threshold=9 在 definition/API meta 冻结，不逐行重复。
3. `formula_version` 必须为 1；混合版本分区拒绝发布。
4. 真正创建 migration 前重新读取当前 Alembic head；不得照抄 M0 快照。
5. `lake_raw_writer` 只获得该表 `SELECT, INSERT, DELETE`；不授予 UPDATE、TRUNCATE、建表或角色管理权限。
6. 股票表通过新的 Alembic migration 删除 `close_positive` 约束和 `close_qfq` 列；实现前必须重新确认真实单一 head。迁移保留既有行，不执行全表 delete/reinsert，也不新增兼容列或双表。

### 7.2 publisher

新建：

```text
prod_core_stock_daily_qfq_nineturn
prod_core_index_daily_nineturn
```

单分区流程：

1. 读取 Gold 时固定投影并设置 `hive_partitioning=false`。
2. 验证 schema、分区日期、唯一键、计数/信号值域、formulaVersion 和源键覆盖；股票 publisher 不再读取、写入、hash 或比较 `close_qfq`。
3. 在一个 PostgreSQL 事务内按 `trade_date` 删除旧分区。
4. 使用 `execute_values` 有界批量写入，不做 Python 单行 insert。
5. read-back 比较行数、完整键集合和规范化内容 hash。
6. 任一差异 rollback；状态写入失败不得污染已提交的业务表事务。

历史发布实现冻结为：

```text
stock_daily_qfq_nineturn_serving_history.py
stock_daily_qfq_nineturn_serving_history_cli.py
```

1. `plan` 只读扫描准确交易日范围，冻结 Gold 文件的相对路径、size、mtime、行数和计划指纹；QFQ 文件仅作为日常新增计算输入，不再作为去价格迁移或 serving 发布的价格一致性门禁。价格值变化、QFQ size/mtime 变化均不得触发九转 repair。
2. Gold scoped rebuild 和 serving 发布的 `sample` 均仅允许显式选 1～3 个计划内分区；单个 `batch` 最多 20 个分区。Gold 修复单次最多 200 个 batch；serving 单进程最多 10 个 batch，并在进程退出后从 checkpoint 续跑。
3. 每个交易日独立事务并完成 read-back 后，才把业务内容 hash 原子写入 checkpoint。
4. checkpoint 固定在 `/Volumes/datasource/data_lake_staging` 下；续跑前对冻结的 Gold 候选/正式文件核对路径、size、mtime，并以 PostgreSQL server cursor 流式验证已完成分区的无价格业务内容 hash；禁止盲跳，也禁止恢复时重新深扫 3,066 日内容。
5. scoped plan 只扫描目标资产族；本轮 daily 修复不得顺带扫描四个分钟资产。
6. 日线去价格迁移每个分区只把既有正式九转文件投影为六列候选，复刻新的无价格 blocking check、原子提升并写 checkpoint；禁止重新计算公式，失败后按 checkpoint 续跑。
7. 候选和 checkpoint 均位于独立 staging 根；正式 Lake 内不新增 `_staging`、`_quarantine` 或恢复副本，不使用 Kopia。
8. plan/sample/batch/resume 代码与隔离测试完成，不构成真实 Gold 修复或生产发布授权。
9. plan 每个分区只消费完整性聚合诊断和 `checked_row_count`，不得调用返回全量 Python rows 的 loader；每 20 个分区关闭并重建 DuckDB 连接。
10. publish 只对本次最多 200 个待发布日执行无价格 Gold 内容门禁。计划明细只写 JSON 文件；CLI 固定大小摘要，发布进度每个逻辑 batch 一条，最终输出不含完整日期数组。
11. 历史发布 DuckDB 固定 `memory_limit=128MB`、`threads=1`、`preserve_insertion_order=false`。

日常链路独立为：

```text
prod_core_stock_daily_qfq_nineturn_sync_job
prod_core_stock_daily_qfq_nineturn_sync_job_sensor
prod_core_stock_daily_qfq_nineturn_partition_check
```

serving check 使用只读事务对比 Gold 与 PostgreSQL 行数、键和业务内容 hash。sensor 只监听 Gold job 成功且 Gold blocking check 就绪的同分区，定义初始状态固定 `STOPPED`；当前正式实例状态见第 4.5 节。

### 7.3 Web 查询

所有环境的日线 endpoint 都只读 PostgreSQL serving。不存在以下回退：

1. 不在 local/dev 自动改读 Lake。
2. 不在 serving 缺失时改读 `core_serving.equity_nineturn`。
3. 不在查询异常时由前端重算。

查询以现有 K 线事实为窗口基表：

1. 股票基表为 `core_serving.equity_factor_pro`。
2. 指数基表为 `core_serving.index_factor_pro`。
3. 先按 code、日期和 cursor 取得最近 `limit+1` 根 bar，再左连接九转 serving。
4. `limit` 表示 bar 窗口大小，不表示 marker 数量。
5. bar 有而九转行全部没有为 `EMPTY/NT_SOURCE_NOT_READY`；部分没有为 `PARTIAL/NT_ALIGNMENT_PARTIAL`。

## 8. 分钟本地 Reader

### 8.1 capability

不新增环境变量。复用并审计以下现有配置：

| 配置 | 来源 | 九转用途 |
|---|---|---|
| `APP_ENV` / `Settings.app_env` | env/Settings | 只允许 `dev|local` 挂分钟九转路由 |
| `WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED` | env/Settings | 复用本地分钟总开关 |
| `GOLDENSHARE_LAKE_ROOT` | env/Settings | 必须精确解析为 `/Volumes/datasource/data_lake` |
| DuckDB optional dependency | Python runtime | 缺失时 capability 不成立 |

新增两个 subject-specific resolver：

```text
resolve_stock_nine_turn_minute_capability
resolve_index_nine_turn_minute_capability
```

二者复用基础门禁，再分别校验目标 Gold 根目录。股票能力就绪不等待指数资产；指数能力不反向影响股票分钟九转。

### 8.2 Reader 合同

新增 Foundation 内部合同：

```python
NineTurnReadRequest(
    subject_type,
    ts_code,
    period,
    start_date,
    end_date,
    limit,
    cursor,
)

NineTurnReadPage(
    rows,
    source_row_count,
    matched_row_count,
    missing_row_count,
    has_more,
    next_cursor,
    observed_start_date,
    observed_end_date,
    scanned_file_count,
    elapsed_ms,
)
```

Reader 先建立 bar 窗口，再连接同窗口九转文件，因此分页边界与 K 线而不是稀疏 marker 对齐。

安全和性能约束：

1. 只接受固定 subject、code、period 和相对数据集路径。
2. 每个路径 `resolve()` 后必须仍位于固定 dataset root；拒绝符号链接、`_staging`、旧 Lake 和 technical state。
3. 固定列投影，所有 Parquet 调用显式 `hive_partitioning=false`。
4. 先按日期/年份裁剪，再集合查询；不使用 `SELECT *`、OFFSET 或逐行 Python 全历史扫描。
5. 查询 `limit+1` 生成稳定 cursor；最多扫描 5,000 个分区文件。
6. 超过 5MB 拒绝响应，不截断 JSON。
7. `trade_time` 必须属于 `trade_date`，结果时间键严格升序且唯一。
8. 全市场分区的完整 schema、全量键覆盖和值域由绑定当前 materialization 的 blocking check 负责；Web Reader 仍逐文件校验 schema 与安全路径，但分区、值域和重复键只扫描本次请求的 `tsCode`，不得为查询一只股票反复扫描同窗口全市场行。
9. 股票分钟九转 Reader 由本地 composition root 按正式 Lake root 复用；内部 DuckDB 连接固定 `memory_limit=256MB`、`threads=1`、`preserve_insertion_order=false`，并通过进程内锁串行使用。不得每个 HTTP 请求重新创建一个全市场校验连接。
10. 股票分钟九转 Reader 的正式九转列投影只包含八列新 schema，不读取、验证或返回 `close_qfq`；内部 join 只按 `ts_code + freq + trade_time` 对齐并返回计数、信号和 matched 状态。
11. 股票分钟 K 线 OHLC 和价格始终来自 `gold/quote/stk_mins_qfq`，九转文件不得成为价格事实源；移除九转价格不改变 API marker、分页、cursor、状态或 5MB 合同。

股票分钟 bar 只从 `gold/quote/stk_mins_qfq` 按现有 QFQ code/year 合同枚举，九转路径按 trade_date 枚举；指数 bar 只从 `gold/quote/major_index_mins` 枚举，指数九转按 trade_date 枚举。公共的路径验证、cursor 和最近分区扩展逻辑放在 Foundation 内核，不能从 Biz 复制；任何 Reader 均不得接受 Silver 根或由请求参数选择数据层。

## 9. HTTP 与 DTO 合同

### 9.1 路由

常驻日线：

```http
GET /api/v1/wealth/market/stock-detail/nine-turn
GET /api/v1/wealth/market/index-detail/nine-turn
```

local/dev 条件分钟：

```http
GET /api/v1/wealth/market/stock-detail/minute-nine-turn
GET /api/v1/wealth/market/index-detail/minute-nine-turn
```

四个入口都使用 `require_quote_access`。股票与指数、日线与分钟可以共享 service 内核，但不能合并环境装配边界。

### 9.2 参数

日线参数：

```text
tsCode       required
startDate    optional YYYY-MM-DD
endDate      optional YYYY-MM-DD
limit        optional, default 300, 1..2000
cursor       optional opaque v1
debug        optional 0|1
```

分钟在日线参数基础上增加必填 `freq`；默认 limit=500，范围 1..10000。

支持频率：

1. 股票 minute endpoint 只接受 30/60/90/120。
2. 指数 minute endpoint 只接受 5/15/30/60/90/120。
3. 未知参数和重复参数一律 HTTP 400 `NT_REQUEST_INVALID`。
4. cursor exact-key 解码后必须绑定 endpoint dataset、subject、code、period、startDate、endDate 和上一页时间边界；任一错配拒绝。
5. cursor 是分页绑定工具，不是鉴权令牌；鉴权仍由 HTTP auth 负责。

### 9.3 最终响应

```ts
type NineTurnSubjectType = "stock" | "index";
type NineTurnPeriod = "day" | "5" | "15" | "30" | "60" | "90" | "120";
type NineTurnDirection = "UP" | "DOWN";
type NineTurnSequenceNumber = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9;

interface NineTurnMarkerDto {
  tradeDate: string;
  tradeTime: string | null;
  direction: NineTurnDirection;
  sequenceNumber: NineTurnSequenceNumber;
  completed: boolean;
}

interface NineTurnDataStatusDto {
  status: "READY" | "DELAYED" | "EMPTY" | "PARTIAL";
  code: string | null;
  message: string | null;
  expectedEndDate: string | null;
  observedEndDate: string | null;
}

interface NineTurnMetaDto {
  sourceRowCount: number;
  matchedRowCount: number;
  missingRowCount: number;
  markerCount: number;
  limit: number;
  hasMore: boolean;
  nextCursor: string | null;
  startDate: string | null;
  endDate: string;
  observedStartDate: string | null;
  observedEndDate: string | null;
  comparisonLag: 4;
  signalThreshold: 9;
  formulaVersion: 1;
}

interface NineTurnSeriesDto {
  subjectType: NineTurnSubjectType;
  tsCode: string;
  period: NineTurnPeriod;
  markers: NineTurnMarkerDto[];
  latestMarker: NineTurnMarkerDto | null;
  dataStatus: NineTurnDataStatusDto;
  meta: NineTurnMetaDto;
  debugInfo: Record<string, unknown> | null;
}
```

DTO 规则：

1. 日线 `tradeTime=null`；分钟输出带 `+08:00` 的 Asia/Shanghai 时间。
2. `completed` 等价于 `sequenceNumber===9`，由后端输出。
3. markers 按时间升序，且都必须对应同窗口 bar。
4. 最新源 bar 的 count 为 1～9 时 `latestMarker` 才非空；0、null、10+ 或缺行均为 null。
5. 窗口存在完整九转行但没有 1～9 时，API 仍为 READY、`markers=[]`；前端可显示“当前窗口暂无九转标记”的局部 EMPTY 视觉。
6. 只有源没有任何可用九转行时，API 才返回 `dataStatus=EMPTY`。
7. required + nullable；不在 DTO 中使用 `--`、0 或 `any` 表示缺失。

### 9.4 状态优先级

```text
request/auth/not-found HTTP error
  > source contract/query HTTP error
  > EMPTY
  > PARTIAL
  > DELAYED
  > READY
```

HTTP 200 状态：

| 条件 | status/code |
|---|---|
| bar 窗口存在，九转完全匹配 | READY / null |
| 完全匹配但 observedEndDate 落后显式 endDate | DELAYED / NT_SOURCE_NOT_READY |
| bar 窗口存在，九转零匹配 | EMPTY / NT_SOURCE_NOT_READY |
| 部分 bar 缺九转行 | PARTIAL / NT_ALIGNMENT_PARTIAL |
| 数据完整但当前窗口没有 1～9 | READY / null，前端派生局部 EMPTY 视觉 |

## 10. 异常码

M1 在统一注册表登记以下 planned code；实现阶段对应模块落地后再改为 active：

| code | HTTP/状态 | 恢复动作 |
|---|---|---|
| `NT_REQUEST_INVALID` | 400 | 不重试，保留已加载页面 |
| `NT_NOT_FOUND` | 404 | 股票/指数详情 not-found 行为 |
| `NT_SOURCE_NOT_READY` | 200 EMPTY/DELAYED | 局部空态/延迟，不回退 |
| `NT_SOURCE_CONTRACT_INVALID` | 500 | 九转局部 error，可重试，不返回可疑 marker |
| `NT_ALIGNMENT_PARTIAL` | 200 PARTIAL | 只画已确认对齐 marker，显示局部缺失 |
| `NT_QUERY_FAILED` | 500 | 九转局部 error，可重试 |

401/403 沿用认证层，不登记同义业务码。响应超过 5MB、limit、日期和 cursor 非法统一属于 `NT_REQUEST_INVALID`。

## 11. page-init capability

目标 capability：

```ts
supportsNineTurn: boolean;
nineTurnPeriods: Array<"day" | "5" | "15" | "30" | "60" | "90" | "120">;
```

环境结果：

| 页面 | production | local/dev 且分钟九转能力就绪 |
|---|---|---|
| 股票 | `day` | `day,30,60,90,120` |
| 指数 | `day` | `day,5,15,30,60,90,120` |

规则：

1. `supportsNineTurn=true` 表示日线接口能力已经部署，不表示当前窗口一定有 marker。
2. `nineTurnPeriods` 表示当前环境可调用的周期，不表示 K 线所有周期。
3. 股票 1/5/15、指数 1 永不进入列表。
4. page-init 与 App router 必须调用相同 capability resolver，防止按钮可用但路由不存在。
5. 指数 page-init 合同已在 S7/M5 升级为 1.3.0；后端 `Literal[True]`、前端 `supportsNineTurn=true` 与 `nineTurnPeriods` 已由测试和浏览器实际响应确认。

## 12. 前端结构

### 12.1 目标目录

```text
wealth/src/features/nine-turn/
  api/
    nineTurnApiClient.ts
    nineTurnApiTypes.ts
  model/
    nineTurnTypes.ts
    nineTurnAdapter.ts
  controller/
    useNineTurnSeriesRegistry.ts
    nineTurnSeriesReducer.ts
  ui/
    NineTurnLayerStatus.tsx

wealth/src/shared/charts/detail-workspace/
  NineTurnMarkerPrimitive.ts
  nineTurnMarkerGeometry.ts
  nineTurnMarkerTypes.ts
```

`features/nine-turn` 是股票和指数共同消费的业务 feature；`shared/charts` 只保存与 API、对象类型和公式无关的绘图 primitive。

### 12.2 请求注册表

`useNineTurnSeriesRegistry` 接受 subject、code、endDate、capability 和 loader，返回：

```ts
stateFor(period)
ensure(period)
retry(period)
clear()
```

缓存键完整包含：

```text
subjectType + tsCode + period + startDate + endDate + limit + cursor
```

每个 key 独立保存：

```text
phase, data, errorCode, errorMessage, requestId, AbortController
```

约束：

1. 切 code、period、日期或组件卸载时 abort 旧请求。
2. 即使 abort 未及时生效，也用递增 request id 拒绝旧响应覆盖。
3. 相同 key READY/EMPTY/PARTIAL 命中缓存，不重复请求。
4. retry 只清理目标九转 key，不清 K 线、分钟技术指标、权重或趋势缓存。
5. unsupported period 直接生成 UNSUPPORTED 视图状态，网络调用数为 0。

### 12.3 页面接入

股票：

1. day/30/60/90/120 切换时 `ensure(activePeriod)`。
2. 1/5/15 保留 K 线能力，但九转显示 UNSUPPORTED 且不请求。
3. 日线和分钟 workspace 都只接收归一后的 `NineTurnLayerViewModel`。

指数：

1. active chart 周期调用 `ensure(activePeriod)`。
2. Technical Tab 首次打开时，按固定摘要周期 `day/15/30/60/90/120` 与 `nineTurnPeriods` 求交后调用 `ensure`；不得包含 1 分钟或 5 分钟。
3. 为复用图表缓存，摘要请求使用与图表相同的窗口 limit，不单独创建 summary endpoint。
4. production 只请求 day；15/30/60/90/120 五行仍固定保留并显示 `--`，不尝试分钟 URL。
5. local/dev 中已请求的 15/30/60/90/120 可在切图时直接复用；5 分钟图表九转缓存不进入右栏摘要。
6. 九转状态不并入整页 `partialReasons`，只在图层和 Technical 九转卡中表达。

### 12.4 局部状态

| 视图状态 | 来源 | 行为 |
|---|---|---|
| IDLE | 支持但尚未 ensure | 不画 marker |
| LOADING | 请求中 | K 线立即显示，轻量局部状态 |
| READY | API READY 且有 marker | 绘制 marker |
| EMPTY | API READY 且 markers 空 | 不报错，显示当前窗口无标记 |
| SOURCE_EMPTY | API EMPTY | 显示数据源不覆盖；北证50分钟使用此态 |
| PARTIAL | API PARTIAL | 只画已对齐 marker并显示缺失提示 |
| ERROR | HTTP/query/contract error | K 线保留，显示局部重试 |
| FORBIDDEN | 403 | 只隐藏九转并提示权限 |
| UNSUPPORTED | period 不在 capability | 禁用且零请求 |

## 13. `NineTurnMarkerPrimitive`

### 13.1 输入

API marker 不携带锚点价格。chart adapter 通过同一时间键连接当前 K 线：

```ts
interface NineTurnRenderMarker {
  time: Time;
  direction: "UP" | "DOWN";
  sequenceNumber: 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9;
  anchorPrice: number; // UP=high, DOWN=low
}
```

找不到 K 线、high/low 非有限值或时间键重复时不绘制，并把该项计入前端对齐诊断；不能猜价格。

### 13.2 几何

1. marker 画布尺寸固定 18×18 CSS px。
2. UP：marker 底边位于 high 上方 8px，即 `top = priceY - 8 - 18`。
3. DOWN：marker 顶边位于 low 下方 8px，即 `top = priceY + 8`。
4. 水平中心与 bar 时间坐标一致。
5. 1～8 为普通数字；9 使用方向色数字、1px 描边和 2px 圆角。
6. 红涨绿跌，颜色取共享行情 token；不复用 success/error token。
7. 不添加 Tooltip、hover、click 或交易事件。

### 13.3 生命周期和层级

1. primitive 按 `dataKey` 创建稳定实例，响应到达后调用 `setMarkers()` 和 `requestUpdate()`。
2. marker 数据变化不替换 `mainPrimitives` 数组身份，避免触发 `DetailChartWorkspace` chart effect 重建。
3. `autoscaleInfo()` 始终返回 null；依赖现有 price scale margin 提供极值外空间，不用价格补偿扩大纵轴。
4. renderer 只遍历当前 logical visible range 内 marker。
5. SSE day 的数组顺序固定为 `[trendPrimitive, nineTurnPrimitive]`，二者使用 bottom pane layer，K 线在其上，Tooltip/十字线最高。
6. detached 后清空 attached parameters；重复 attach/detach 不泄漏 view、canvas 或 listener。

`DetailChartWorkspace` 只增加通用 `mainLayerAccessory?: ReactNode` 承载局部状态，不出现九转业务文案。

## 14. 指数 Technical 九转摘要

九转卡固定显示六行，顺序为 day、15、30、60、90、120：

```text
日线  上序 9
15分  --
30分  上序 3
60分  下序 6
90分  --
120分 --
```

映射规则：

1. 使用各响应 `latestMarker`，不在前端扫描历史推导“最近一次九转”。
2. 最新 bar count 1～9 才显示方向和序号。
3. 没有 `latestMarker`、count 0、10+、数据为空、能力未开放或请求失败时，值位都显示 `--`，并由旁侧局部状态说明原因；对应周期行始终保留。
4. Figma 示例数字不是测试金标。
5. 摘要不解释趋势、机会或交易动作。
6. 1 分钟和 5 分钟不进入摘要；5 分钟是否支持图表 marker 与摘要合同相互独立。

### 14.1 2026-08-16 补充需求修改范围

Figma 事实源：

- `08 Index Detail - Desktop Loaded` 的 Technical 根画板 `423:910`，通过右栏实例同步主组件改动。
- `08.5 Index Detail - Components` 的 Technical 主组件 `414:448`，九转卡 `414:417` 固定为六行 Auto Layout。
- `08.5` 的合同说明 `633:545`，明确固定顺序、缺 marker 的 `--` 以及 1/5 分钟排除规则。
- `09 Index Detail - States and Interaction Notes` 的九转状态矩阵 `634:558`，明确各局部状态只替换值与状态说明，不删除周期行。

前端修改限定为：

```text
wealth/src/features/index-detail/model/indexTechnicalNineTurnSummary.ts
wealth/src/features/index-detail/sidebar/IndexTechnicalTab.tsx
wealth/src/features/index-detail/sidebar/IndexInfoRail.tsx
wealth/src/pages/index-detail/IndexDetailPage.tsx
wealth/src/pages/index-detail/index-detail-page.css
wealth/src/features/index-detail/sidebar/IndexTechnicalTab.test.tsx
wealth/src/pages/index-detail/IndexDetailPage.test.tsx
```

实现必须建立单一 `INDEX_TECHNICAL_NINE_TURN_PERIODS` 常量与对应 summary 类型，页面预取、右栏 Props 和渲染顺序共同消费该合同，禁止在多个组件重复手写周期数组。现有 `useNineTurnSeriesRegistry`、九转 API DTO、Reader、Gold/serving、路由、共享图表和 marker primitive 均不修改；本需求不新增异常码、配置项、后端请求参数或数据迁移。

测试门禁：

1. Technical 卡严格按日线、15、30、60、90、120分钟渲染六行。
2. 各周期没有 `latestMarker` 时值位为 `--`，行仍存在；有 marker 时显示“上序 n / 下序 n”。
3. local/dev 首次进入 Technical 只对 capability 支持的六个摘要周期发请求；5分钟不因右栏摘要额外请求。
4. production capability 只有 day 时只发日线请求，另外五行保留且为 `--`/局部未开放状态。
5. 既有 active chart 周期请求、缓存、retry、abort/request-id、趋势通道与图表 marker 行为不回归。

### 14.2 补充需求执行结果

1. `INDEX_TECHNICAL_NINE_TURN_PERIODS` 成为唯一周期与文案合同，`IndexDetailPage` 预取、`IndexInfoRail` Props 和 `IndexTechnicalTab` 渲染共同消费；没有第二份顺序数组。
2. local/dev 首次打开 Technical 并发请求 15/30/60/90/120 五个分钟摘要并复用已加载的 day；测试证明 5 分钟不因摘要额外请求。production/default capability 只请求 day，另外五行由 registry 的 UNSUPPORTED 局部状态固定占位。
3. `IndexTechnicalTab` 对六个周期始终渲染行；`latestMarker` 缺失时值位为 `--`，EMPTY/READY 无 marker 的 Loaded 文案为“暂时空缺”，SOURCE_EMPTY/ERROR/FORBIDDEN 等继续显示各自局部原因与重试入口。
4. CSS 将周期列和值列冻结为 64px，行高 38px，六行间距 6px，使用现有 `--cs-color-surface-card`；与 Figma `414:417` 的 Auto Layout 一致，没有新增绝对坐标或补偿位移。
5. 定向测试为 30 passed；Wealth 全量为 34 files、232 passed，typecheck、production build 和 `git diff --check` 通过。1600×1200 浏览器上，上证六周期均显示真实值；北证50的 15/30/60/90/120 固定显示 `-- / 数据源未覆盖`。页面宽度保持 1600px，六行均无横纵溢出，console 无 warning/error。
6. 本轮没有修改 API/DTO、后端路由、异常码、Gold/serving、Lake、Dagster、共享 registry、共享图表或 marker primitive，子系统边界与依赖矩阵不变。

## 15. 文件级实施计划

### 15.1 M2：股票纵向切片与 shared primitive

后端/serving：

```text
alembic/versions/<current_head>_add_nine_turn_daily_serving.py
src/foundation/models/core_serving/equity_qfq_nineturn_daily.py
src/foundation/clients/local_lake/stock_nine_turn_contract.py
src/foundation/clients/local_lake/stock_nine_turn_reader.py
src/biz/schemas/wealth/market/nine_turn.py
src/biz/queries/wealth/market/stock_nine_turn/
src/biz/queries/wealth/market/stock_minute_nine_turn/
src/biz/api/wealth/market/stock_detail_nine_turn.py
src/app/api/v1/router.py
lake_console/orchestrator/src/orchestrator/defs/assets/stock_daily_qfq_nineturn_prod_core.py
lake_console/orchestrator/src/orchestrator/defs/prod_db/stock_daily_qfq_nineturn.py
```

前端：

```text
wealth/src/features/nine-turn/**
wealth/src/shared/charts/detail-workspace/NineTurnMarkerPrimitive.ts
wealth/src/shared/charts/detail-workspace/nineTurnMarkerGeometry.ts
wealth/src/pages/stock-detail/StockDetailPage.tsx
wealth/src/features/stock-detail/chart/StockChartWorkspace.tsx
wealth/src/features/stock-detail/chart/StockMinuteChartWorkspace.tsx
```

上述文件已按冻结边界实现。M2 没有创建指数资产或改指数页面，也没有修改既有股票 QFQ 九转公式、资产 key、路径或 sensor default status。

### 15.2 M3-A：发布前事实与文档收口

已完成：生产 migration/head/表结构/权限/空表审计；正式 Lake 3,066 个交易日、11,638,636 键的覆盖审计；登记 18 只股票、45,442 行 close 漂移及“marker 正确但价格事实过期”的边界。

### 15.3 M3-B：发布门禁

已实现：

```text
lake_console/orchestrator/src/orchestrator/defs/qfq_nineturn_integrity.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/qfq_nineturn_history.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/stock_daily_qfq_nineturn_serving_history.py
lake_console/orchestrator/src/orchestrator/defs/checks/stock_daily_qfq_nineturn_prod_core_checks.py
lake_console/orchestrator/src/orchestrator/defs/jobs/stock_daily_qfq_nineturn_prod_core_sync.py
lake_console/orchestrator/src/orchestrator/defs/sensors/stock_daily_qfq_nineturn_prod_core_sensor.py
```

M3-B 执行前复核发现旧 scoped rebuild 会一次性生成并整体提升 3,066 个分区，已改为目标资产窄扫描、1～3 分区 sample、20 分区 batch、单次最多 200 batch、逐分区 checkpoint/resume。经单独批准，Gold 修复与全历史对账已经完成。serving 在发布 1,113 日后因内存事件暂停；根因审计确认 plan 曾逐分区完整装载、publish 恢复时重新深扫全部历史且 CLI 输出超大对象。发布器已改为 DuckDB 128MB/1线程、plan 聚合诊断、20日连接重建、恢复只做源文件元数据核对与 Prod 流式 hash、待发布日期深度门禁及逐 batch 固定大小输出；每日独立事务与 checkpoint 语义不变。修正后先通过全历史 plan 与 1,113 日 checkpoint 只读内存验收，再以十个独立短进程发布余下 1,953 日。最终 checkpoint 为 3,066/3,066，生产表为 11,638,636 行，日期缺失/额外/逐日行数不符均为 0；十个进程最大 RSS 为 209～249MiB。当时的启停动作属于历史记录；2026-08-15 三个股票 sensor 的实例状态均为 `RUNNING` 但最近 tick 全部 `SKIPPED`，当前事实见第 4.5 节。

### 15.4 M3-C：股票页面完整验收

Gold 修复和 serving 历史发布后，完成生产日线、四个本地分钟、三个禁用周期、全部局部状态、缓存竞态、浏览器和视觉验收。M2 已包含页面接入，因此不重复建第二套控制器。

2026-08-13 已完成生产日线主体门禁：登录态 `600683.SH` API 返回 200/143.07ms，另一个 `688300.SH` 样本为 200/211.78ms；`600683.SH` 最近 300 根 serving 记录匹配 300、缺失 0、formulaVersion 漂移 0，包含 37 条 10+ 负向样本；1600×1200 页面实际绘出 1～9 和完成态 9，四窗格、坐标轴、右栏与缩放按钮无视觉漂移。两次 HTTP 只作为代表性样本，不宣称正式 P95；45/180 根边界已有共享组件自动化门禁。用户于 2026-08-15 取消补足正式 P95 样本和补拍生产边界截图的要求。

2026-08-15 S6 以正式 Lake 与 Dagster instance 做了只读复核：日线九转物理文件停在 2026-08-12，上游 QFQ 已覆盖至 2026-08-14；8 月 13/14 两次 factor repair 分别重写 9/11 个代码。对合计 20 个代码按当时 3,068 个源分区重算，既有可对齐 50,283 行全部只发生 `close_qfq` 差异，计数差异 0、信号差异 0，另有 40 行属于尚未生成的两个交易日。页面 DTO 不输出价格。用户当时明确不在 M3-C 页面阶段处理日线价格字段，因此 S6 阶段未删除字段、重建历史或修改 check/sensor/Prod；后续独立专项现已完成 D0～D5，真实进度以第 21.6 节为准。

同轮代码回归通过：股票日线九转 API 10 项、股票页面/共享九转图层/缩放控件 43 项、前端 typecheck 和 production build 均成功。结合已通过的真实接口、数据和 Loaded 视觉主体门禁，并按用户取消两项补充验收的决定，M3-C 页面切片收口。

2026-08-14 在四个分钟九转资产重建后完成过 M3-C-Minute 行为验收：30/60/90/120 分钟最新分区及 matching blocking checks 通过；三只股票四周期各 500 根 K 线、技术指标、九转逐键对齐；四周期 HTTP P95 为 362～500ms；Reader 修正“每请求新建 DuckDB + 重复扫描全市场”的内存根因后，第二批 40 请求 RSS 仅增加 12.78MiB；1600×1200 浏览器实测四支持周期均绘出 1～9，1/5/15 分钟九转零请求，缓存切回和放大均不重置图层。

该结果证明九转 marker、页面和 Reader 行为；2026-08-15 去价格专项 S2～S5 又完成了八列正式重建、事件恢复和运行验收，因此 M3-C-Minute 的页面行为与物理合同均已收口。生产分钟路由仍按产品合同保持 404，日线验收结论不受影响。

### 15.5 M4：指数资产、serving 与 API

```text
lake_console/orchestrator/src/orchestrator/defs/nineturn_formula.py
lake_console/orchestrator/src/orchestrator/defs/run_contracts/major_index_nineturn.py
lake_console/orchestrator/src/orchestrator/defs/major_index_nineturn.py
lake_console/orchestrator/src/orchestrator/defs/major_index_nineturn_integrity.py
lake_console/orchestrator/src/orchestrator/defs/asset_guards/major_index_nineturn.py
lake_console/orchestrator/src/orchestrator/defs/assets/major_index_nineturn.py
lake_console/orchestrator/src/orchestrator/defs/checks/major_index_nineturn_checks.py
lake_console/orchestrator/src/orchestrator/defs/jobs/major_index_nineturn_update.py
lake_console/orchestrator/src/orchestrator/defs/sensors/major_index_nineturn_sensor.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/major_index_nineturn_history.py
lake_console/orchestrator/src/orchestrator/defs/assets/index_daily_nineturn_prod_core.py
lake_console/orchestrator/src/orchestrator/defs/prod_db/index_daily_nineturn.py
lake_console/orchestrator/src/orchestrator/defs/checks/index_daily_nineturn_prod_core_checks.py
lake_console/orchestrator/src/orchestrator/defs/jobs/index_daily_nineturn_prod_core_sync.py
lake_console/orchestrator/src/orchestrator/defs/sensors/index_daily_nineturn_prod_core_sensor.py
alembic/versions/20260814_000136_add_index_nineturn_daily_serving.py
src/foundation/models/core_serving/index_nineturn_daily.py
src/foundation/clients/local_lake/index_nine_turn_contract.py
src/foundation/clients/local_lake/index_nine_turn_reader.py
src/biz/queries/wealth/market/index_nine_turn/**
src/biz/queries/wealth/market/index_minute_nine_turn/**
src/biz/api/wealth/market/index_detail_nine_turn.py
src/biz/api/wealth/market/index_detail_minute_nine_turn.py
```

以上结构已按资产计算、完整性、readiness、serving、Reader、query/service 与 API 职责拆分；后续不得合并成无法独立测试的单个大文件。

M4-A 已完成且退出条件为：

1. 共享公式文件已落地，股票三个计算入口（全历史、分区增量、年度历史批次）均只通过 adapter 消费共享内核。
2. 股票公开函数、资产 key、schema、路径、lag=4、threshold=9、10+ 持续信号、seed 与 fallback 语义未改变。
3. 独立共享内核测试与原股票受保护 golden 形成双门禁；测试只使用内存 DuckDB 和临时 Parquet。
4. M4-A 不创建指数资产、不生成指数历史。指数 asset/check/job/sensor/readiness、正式历史与性能验收从后续 M4-B 开始。

M4-B 编码前只读门禁（2026-08-14）已经冻结。以下七条是“编码前范围与当时授权”的历史快照，其中“待执行/不属于本轮授权”已由后文经单独批准的正式执行完成，不是当前待办：

1. 正式日线上游 `gold/market/major_indices_daily` 有 6,450 个交易日分区、42,633 行，范围为 2000-01-04～2026-08-14；最新分区含 11 个物理代码，同时包含 `899050.BJ` 和只允许物理存在的 `000680.SH`。
2. 正式分钟上游 `gold/quote/major_index_mins` 的 5/15/30/60/90/120 六频率各有 4,279 个交易日分区，范围为 2009-01-05～2026-08-14；全历史行数依次为 1,464,096、488,032、244,016、122,008、91,506、61,004。六频率唯一时间键重复数和 `trade_time`/`trade_date` 错配数均为 0。
3. 六频率物理代码均为 10 个：包含 `000680.SH`，不包含 `899050.BJ`。这是物理 Gold 上游事实；产品 API 仍只能按 Wealth 10-code allowlist 开放，因此 `000680.SH` 必须 404，`899050.BJ` 六频率必须返回局部 `EMPTY/NT_SOURCE_NOT_READY`。
4. 全历史只读聚合耗时约 0.6～1.0 秒，但 5 分钟频率一次枚举 4,279 个碎文件时进程最大 RSS 约 337MiB；该证据禁止七资产共用一个全历史常驻连接或一次性构建全量中间表。
5. 历史构建固定为单资产串行、20 个交易日一批、DuckDB `memory_limit=256MB`、`threads=1`、`preserve_insertion_order=false`，每批重建连接并写 compact context/seed 与 checkpoint。只读计划冻结所有 source/context 文件的相对路径、size 与 mtime；执行前逐批复核，checkpoint 恢复必须逐文件校验已提升目标的 SHA-256，禁止盲跳。任一批次 RSS 超过 512MiB、单批超过 30 秒、目标文件数或行数不等于源窗口时立即停止。
6. 预计新增 32,124 个目标分区文件（日线 6,450 + 六分钟 25,674）；对应 materialization 与 blocking-check event 各 32,124 个。物理文件生成、正式 Lake 提升、runless event、生产 migration/serving 发布和 sensor 启用都不属于本轮编码授权，必须另行提交只读 plan 并取得执行批准。
7. 本轮编码只允许新增 7 个 asset、7 个 blocking check、2 个 job、2 个默认 `STOPPED` sensor、readiness、历史 planner、日线 serving/publisher 和日线/本地分钟 API；负向门禁必须证明不存在 1 分钟九转 asset/check/job/sensor/path/API 支持，且指数九转不得直接引用任何 Silver 分钟 asset key 或路径。

M4-B 编码结果（2026-08-15）：

1. 7 个 Gold asset、7 个聚合 blocking check、2 个 job、2 个默认 `STOPPED` sensor、readiness 与有界历史构建器已实现；Definitions 可发现全部对象，且不存在 1 分钟九转对象。
2. 历史构建器已落实 20 日批次、256MB/1线程、512MiB RSS 与 30 秒停止门禁，并增加源文件身份复核、候选完整性、逐文件原子提升、目标 SHA-256 checkpoint 恢复回验；测试只写临时目录。
3. `core_serving.index_nineturn_daily` migration、事务 publisher、serving check/job/默认 `STOPPED` sensor 及常驻日线 API 已实现；当前 Alembic head 为 `20260814_000136`，`down_revision` 精确连接 `20260813_000135`。
4. 本地分钟 Reader/API 已实现六频率、Gold bar 窗口分页、严格 cursor、5,000 文件/5MB 门禁、10-code allowlist、`000680.SH` 404 和 `899050.BJ` 局部 EMPTY；Reader 使用单个受锁 256MB/1线程 DuckDB 连接。
5. 共享 DTO 只投影 1～9；10+ 不重复绘制 9。股票日线/分钟消费者已同步迁移到 subject-aware cursor/DTO，并通过回归。
6. 本节仅记录编码交付；物理历史、Dagster event、生产 migration、serving 发布和正式验收的后续执行事实见下方“M4-B 正式执行结果”。
7. 编码验收通过 121 个 Web/Foundation 回归，以及 122 个 Orchestrator 测试和 14 个 subtests；`dg list defs` 实测发现 7 个 Gold assets/checks、1 个 serving asset/check、3 个 jobs 和 3 个默认停止的 sensors。现有 Pydantic、Dagster Preview/Deprecation warning 未新增失败。

M4-B 正式执行结果（2026-08-15）：

1. 执行前生成并复核了只读历史计划 `major_index_nineturn_history_plan_20260814_164959.json`，指纹为 `fbd7c70f452b222dd7c7bc6570f2ee1c2597b6fe79b369578eddebc392015d5f`。计划冻结 7 个资产、1,607 个批次、32,124 个源文件/目标分区和 2,513,295 行，执行前目标文件数为 0，无 stop reason。
2. 正式 Lake 已生成 32,124/32,124 个目标分区。最终只读报告为 `/Volumes/datasource/data_lake_staging/major_index_nineturn_history/final-audit.json`，物理指纹为 `4c4e84b0878d76107356f6563a2090fe0053865a25769c8b7871cd90f524a7d7`；目标文件、行数、checkpoint SHA、唯一键、分区日期、值域、源键和源值错配均为 0，不存在 1 分钟九转文件。日线为 6,450 分区/42,633 行；5/15/30/60/90/120 分钟各为 4,279 分区，行数依次为 1,464,096、488,032、244,016、122,008、91,506、61,004。
3. Dagster event 计划为 `major_index_nineturn_events_plan_20260814_171420.json`，指纹为 `cc18b38cec1f0c1e3d0d48652d7978f1203160e5fd3433ca87e32a7ca6bc3009`。已登记 32,124 条 materialization 和 32,124 条绑定当前 materialization 的 blocking-check event，共 64,248 条。最终 post-audit 确认 32,124/32,124 完成，missing materialization 和 missing ready check 均为 0。
4. 生产 Alembic 已从 `20260813_000135` 升级到 `20260814_000136`，`core_serving.index_nineturn_daily` 已按 9 列合同、主键/检查约束和索引创建。迁移后首次只读检查确认表为空，历史 serving 发布之前没有旧数据混入。
5. 日线 serving 只读计划为 `major_index_daily_nineturn_serving_plan_20260814_173735_793613.json`，指纹为 `ca9ec89ed4a7ad19c2ed8211291d9b103b97e4c93048d3ee8ed57b86b6902cbd`，冻结 6,450 个交易日和 42,633 行。发布期间一次建连超时发生在批次之间，已提交的单日事务和 checkpoint 保持一致，按原计划断点续跑后完成 6,450/6,450。最终零写入回验重新流式校验全部 checkpoint hash，结果为 resumed 6,450、remaining 0、failed 0。
6. 生产表最终为 42,633 行、6,450 个交易日、11 个物理代码，范围 2000-01-04～2026-08-14，与冻结 Lake 计划的每日业务 hash 全量一致。十个产品指数最近 300 根均为 300/300 对齐、missing 0；`899050.BJ` 日线 READY，`000680.SH` 仍严格 404。正式表有 4,353 条 count > 9 的真实记录，API 全窗口 marker 仍只包含 1～9，没有重复绘制 9。
7. 性能验收通过：物理全量对账 33.956 秒、峰值 RSS 约 390.5MiB；Dagster event post-audit 8.71 秒、峰值 RSS 约 422.9MiB；serving 全 checkpoint 哈希回验 3.59 秒、峰值 RSS 约 158.9MiB。生产数据库回源的 FastAPI in-process HTTP 对十个指数执行 50 次、每次 300 根，P95 为 148.605ms、最大 262.141ms、全部 HTTP 200。该数值包含查询、DTO 与 JSON 序列化，不包含公网或生产 Web 主机网络延迟。
8. 本地正式 Lake Reader 对六频率各执行 10 次、每次 500 根，P95 依次为 308.266/316.656/373.010/418.199/447.895/555.982ms，均为 500/500 对齐。5 分钟 10,000 根为 818.571ms、1,103,808 bytes、419 个扫描文件；120 分钟全历史 10,000 根请求按合同命中 5,000 文件门禁并返回 `NT_REQUEST_INVALID`，没有截断或返回不完整 JSON。`899050.BJ` 六频率保持 `EMPTY/NT_SOURCE_NOT_READY`。
9. 7 个 Gold assets/checks、1 个 serving asset/check、3 个 jobs 和 3 个 sensors 仍能被 Definitions 发现，不存在 1 分钟九转定义。2026-08-15 重新审计确认三个指数 sensor 仍无持久化启动状态，因此实际沿用定义默认 `STOPPED`；本轮没有启用指数日常调度。

### 15.6 M5：指数页面接入

修改现有 index page-init capability、index page/controller、两类 chart adapter、`IndexTechnicalTab` 和测试。不得复制 `NineTurnMarkerPrimitive`、series registry 或 API DTO。

S7 编码边界及 2026-08-16 固定六周期摘要补充边界：

1. page-init 与 App router 复用同一指数分钟九转 capability resolver；生产只声明 `day`，local/dev 能力就绪时声明 `day,5,15,30,60,90,120`，指数 1 分钟永不请求。
2. 指数日线与分钟图表复用共享 registry、`NineTurnMarkerPrimitive` 和 `NineTurnLayerStatus`；上证日线 primitive 顺序固定为趋势通道在前、九转在后。
3. Technical 首次打开只 ensure capability 支持的 day/15/30/60/90/120，并只读取 API `latestMarker` 形成“上序 N/下序 N”；六行固定保留，无 marker、未开放、源空或失败均显示 `--` 和局部原因；1 分钟和 5 分钟零摘要请求。
4. 九转 LOADING/EMPTY/SOURCE_EMPTY/PARTIAL/ERROR/FORBIDDEN/UNSUPPORTED 只影响九转图层和摘要，不进入整页 `partialReasons`，不清空 K 线、趋势、技术指标或右栏其它模块。
5. `899050.BJ` 分钟保持 `SOURCE_EMPTY`，`000680.SH` 仍由产品 allowlist 拒绝；不增加 fallback、Mock、客户端现算、Tooltip、点击或交易动作。
6. registry 必须允许 day/15/30/60/90/120 六个独立 key 并发加载；切 code/日期/卸载才统一 abort，单周期 retry 不清理其它周期缓存。

S7/M5 正式执行结果（2026-08-15）：

1. page-init 已按同一 capability resolver 输出 `supportsNineTurn=true` 与环境相关 `nineTurnPeriods`；生产仅 day，local/dev 开放 day/5/15/30/60/90/120，指数 1 分钟显示 UNSUPPORTED 且浏览器日志确认九转请求数为 0。
2. 指数日线与分钟均复用共享 registry、`NineTurnMarkerPrimitive`、`NineTurnLayerStatus` 和 `DetailChartWorkspace`；上证日线趋势通道与九转按冻结顺序并存，没有复制第二套图表或请求控制器。
3. S7 初始版本只读取 day/60/30；2026-08-16 补充合同将其替换为固定 day/15/30/60/90/120 六行。真实值仍只读取 API `latestMarker`，文案固定为“客观序列 · 非交易信号”，无点击或交易动作；缺 marker 的值位显示 `--`。
4. `899050.BJ` 60 分钟浏览器验收为局部 EMPTY“当前分钟数据源暂不覆盖该指数”，右栏继续展示，切回日线立即恢复；指数九转状态不进入整页 `partialReasons`。
5. 浏览器验收发现并修复共享图表的未操作视窗竞态：分钟技术指标或九转图层到达后，异步旧回调不再把最新 120 根改成最早 120 根；用户主动缩放/拖拽的范围仍保持。60 分钟复验显示最新窗口及 1～9 marker。
6. 后端 index page-init/daily/minute 九转回归 37 项通过；前端全量 34 个测试文件 232 项、typecheck、production build、`git diff --check` 通过。1600×1200 日线双 primitive、Technical 摘要、60 分钟 marker、指数 1 分钟 UNSUPPORTED、北证50分钟空态和切回日线均完成浏览器验收，页面 console 无 warning/error。

### 15.7 M6：发布、自然更新与最终验收

M6 不再增加页面功能，而是把已完成的 M0～M5 代码安全发布，并证明日常链路在真实环境持续工作。必须按以下顺序执行：

1. **M6-0 发布准备评审（已完成并通过）**
   - 只读核对本地 5 个未推送提交、`origin/dev-interface@99f1f2f5`、生产版本、配置、路由矩阵和回滚点。
   - 形成逐提交发布清单和受影响文件清单；不得推送、部署、写 Lake/数据库、读取 Dagster instance 或启停 sensor。
   - 退出条件：代码、文档、远端和生产差异可解释，回滚步骤明确，无未登记的配置或 schema 变更。
2. **M6-A 推送、部署与生产页面验收（已完成并通过）**
   - 六个评审提交已推送并部署为生产 `dev-interface@58fb5b62`；生产只挂股票/指数日线九转，生产分钟九转路由保持 404。
   - 已验收上证日线趋势通道与九转双 primitive、Technical 日线摘要、生产周期禁用、认证/权限和控制台；页面无横向溢出。
   - 退出条件已满足：生产版本与审定提交一致，没有分钟路由泄漏，日线 K 线和既有页面骨架无可见漂移。
3. **M6-B 指数 sensor 发布计划与启用（已完成并通过）**
   - 先单独批准只读实例刷新，核对 readiness、blocking check、cursor/run key、最大单 tick 工作量、失败停止和恢复方案。
   - 只读计划通过后仍须再次批准，才可启用 `gold_major_index_daily_nineturn_update_job_sensor`、`gold_major_index_mins_nineturn_update_job_sensor`、`prod_core_index_daily_nineturn_sync_job_sensor`。
   - 退出条件：一次启用只改变批准的三个 sensor，不产生未计划 backfill，不以定义默认值代替实例状态。
4. **M6-C 下一交易日自然更新观察（已完成并通过）**
   - 对账指数日线和六分钟新分区、7 个 blocking checks、指数日线 serving、页面 freshness；同步观察股票四分钟自然新增。
   - 不手工补分区来伪装自然调度成功。出现失败立即按 M6-B 计划停止，不扩大到股票日线独立治理范围。
5. **M6-D 最终全链路验收**
   - 验收 HTTP P95、响应体、十指数 allowlist、`899050.BJ` 分钟空态、`000680.SH` 404、生产分钟 404、1600×1200 视觉、浏览器控制台、监控和回滚记录。
   - 只有发布版本、自然更新、freshness、性能和视觉全部通过，才可把指数九转标记为生产完成。

并行的股票日线冗余价格与自然更新问题已在第 21 节 D0～D6 完成治理，不再构成 M6-D 前置缺口；但 M6-D 未通过前仍不得把股票与指数九转专项声明为最终交付完成。

M6-0 正式审计结果：

1. **版本与提交边界**
   - 审计基线时本地为 `dev-interface@4c426fd6`，远端与生产均为 `dev-interface@99f1f2f5`；生产工作区干净，本地领先 5 个提交。
   - 前五个提交顺序冻结为 `6ba34c72`、`43372c89`、`96998ccc`、`99f24480`、`4c426fd6`；本轮 M6-0 收口增加第 6 个测试/文档提交，最终候选相对远端共影响 54 个文件。
   - 没有新增 Alembic migration、systemd unit、部署脚本、依赖清单或配置项。Orchestrator 八列 schema 修正是已完成 S2～S5 的事实合同，不在 M6 重跑迁移、事件或 Lake 写入。
2. **生产只读基线**
   - `goldenshare-web.service`、`goldenshare-ops-worker.service`、`goldenshare-ops-scheduler.service` 均为 `active`；Web 入口仍为 `python -m src.app.web.run`。
   - `/api/health`、`/api/v1/health` 为 200；股票/指数日线九转未登录访问为 401，股票/指数分钟九转为 404。
   - `APP_ENV=prod`；`WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED` 与 `GOLDENSHARE_LAKE_ROOT` 未配置。page-init 与 router 共享的 capability 判定不会在生产挂载分钟 Reader/DuckDB。
3. **回归证据**
   - 后端/API/架构定向 84 项通过；Orchestrator 合同 56 项及 16 个子测试通过，Ruff 通过；M5 前端定向 76 项、typecheck、Wealth production build 通过。
   - `scripts/release-preflight.sh` 通过：后端 146 项、架构边界 3 项、主前端 production build 全绿。
   - 初次 Wealth 全量为 231/232。根因是板块测试先等待加载阶段已存在的标题，再同步读取异步请求完成后才出现的行业列，形成竞态。测试改为逐列 `findByLabelText` 后，板块专项 36/36、Wealth 全量 232/232 和 typecheck 通过；没有修改页面、controller、API 或超时，也不再需要发布豁免。
4. **M6-A 冻结命令**

   在生产仓库目录由正式部署用户执行：

   ```bash
   RUN_FRONTEND_BUILD=0 RUN_WEALTH_BUILD=1 \
     bash scripts/deploy-systemd.sh dev-interface \
     --platform-only \
     --skip-realtime \
     --skip-migration \
     --skip-seed-default-source \
     --skip-seed-moneyflow-multi-source \
     --skip-sync-units
   ```

   该命令仍会 fast-forward 拉取审定分支、安装当前后端包、构建 Wealth、重启 Web 并执行通用只读自检；它不得重启 Foundation worker、Ops scheduler、任务完成副作用 worker 或 Realtime，不得执行 migration、seed 或 unit 写入。M6-A 执行前必须再次核对远端 HEAD、生产工作区干净和最终提交清单。
5. **回滚冻结**
   - 页面/API 紧急回滚只对 `4c426fd6` 创建新的 revert commit，推送后运行同一 platform-only 命令；不在生产主机直接 checkout 历史提交。
   - `43372c89` 对应正式分钟无价格物理合同，不能跟随 Web 回滚；回滚不得删除 Lake、Dagster event、migration 或生产表。
   - 回滚后重新核对生产日线 401、分钟 404、两个 health 200 和 Web/worker/scheduler 状态。

M6-0 退出判断：范围、配置、路由、测试、发布和回滚链路均已通过门禁；M6-0 正式完成。该段是发布前历史结论；用户随后已明确批准并完成 M6-A。

M6-A 正式执行结果：

1. M6-A 当次 `origin/dev-interface` 和生产运行提交均为 `58fb5b6232068a86ece1d47ef36f17fc0aa29890`，生产工作区干净。第一次部署受 GitHub→Gitee 镜像延迟影响仍运行旧提交，独立版本复核及时识别；按既定重试规则同步后重新执行冻结命令，未在生产打补丁。当前生产版本已由第 21.6 节 D5-A 更新为 `9fec9a26...`。
2. 最终命令只构建 Wealth、安装当前后端包并重启 Web；旧前端、migration、两个 seed、unit 同步、Realtime、Foundation/Ops/日期完整性/任务完成 worker 均未重启或执行写入。
3. Web 入口保持 `python -m src.app.web.run`，相关服务均为 `active`；`/api/health` 和 `/api/v1/health` 为 200，股票/指数日线九转未登录为 401，股票/指数分钟九转为 404。
4. 这是 v1.25 固定六周期摘要改动前的 M6-A 历史生产验收：上证日线九转 1～9 marker 与趋势通道共存；Technical 当时为“日线 下序 2 / 最新标记”，60/30 分钟为“当前环境未开放”；分时、周/月及全部分钟周期 disabled，日 K active。页面无横向溢出，console 无 warning/error。固定六周期摘要尚未重新发布生产，本地执行结果见第 14.2 节。
5. 本轮没有执行 migration、seed、Lake/数据库写入、Dagster materialize/backfill/runless event、实例读取或 sensor 启停。M6-A 已完成；其后要求的 M6-B 第一段只读发布计划现已完成并记录在下文，但仍不授权第二段启用。

M6-B 第一段只读审计结果与第二段执行门禁：

1. **调用链与 Definitions**
   - `gold_major_index_daily_nineturn_update_job_sensor` 调用 `_evaluate(..., minute=False)`，单次只选择一个 `cn_a_index_trade_days` 分区，对应日线 asset 与一个 blocking check。
   - `gold_major_index_mins_nineturn_update_job_sensor` 调用同一 evaluator 的分钟分支，单次只选择一个 `cn_major_index_mins_trade_days` 分区，对应六频 assets 与六个 blocking checks。
   - `prod_core_index_daily_nineturn_sync_job_sensor` 只监听日线 Gold job 的 `SUCCESS`，再次核验同分区 Gold materialization/check 后，提交一个 serving 分区 run。
   - `dg list defs --json` 当前能发现 8 个资产、8 个 checks、3 个 jobs 和 3 个 sensors。CodeGraph 覆盖了两个 sensor 文件、三个 job、两个 asset/check 家族、readiness helper、run key/cursor builder 和现有测试消费者；依赖仍全部留在 Orchestrator 内，没有改变 Web 或子系统依赖矩阵。
2. **正式 origin 与实例状态**
   - 唯一允许启停的 workspace selector 是 `repositoryLocationName=orchestrator`、`repositoryName=__repository__`。三个 sensor 当前 active workspace 状态均为 `STOPPED`、run 数 0、无持久化 cursor/tick，且具有启停权限。
   - 禁止使用 `dagster sensor list/start -m orchestrator.definitions` 作为正式状态或启停入口；该命令会创建临时代码 origin，无法代表正在运行的 `orchestrator` workspace。第二段必须通过当前 Dagster UI/GraphQL selector 操作，并在每步后用正式实例只读复核。
   - 日线上游分区/raw/silver/major-index Gold 四个 sensor和分钟上游分区/raw/silver/Gold 四个 sensor 均为持久化 `RUNNING`，最近 tick 全为 `SKIPPED/all ready`，最新 run key 到 2026-08-14。
3. **分区、数据与 checks**
   - `cn_a_index_trade_days` 共有 6,450 个注册分区，最近 10 日为 2026-08-03～2026-08-14，无缺口；`cn_major_index_mins_trade_days` 共有 4,279 个注册分区，最近 5 日为 2026-08-10～2026-08-14，无缺口。
   - 2026-08-14 的日线九转、六频分钟九转及六个同频分钟 Gold 上游均为 materialized + latest blocking check passed。日线最近 10 日物理 readiness 为 10/10 ready、44ms；分钟最近 5 日为 30/30 目标文件 ready、120ms。
   - 最新日线目标/源均为 11 行/11 code；六频分钟目标/源分别为 480、160、80、40、30、20 行，均为 10 code，合计 810 行。日线和六频目标与源 Parquet 单日合计 70,422 bytes。
   - 生产 `core_serving.index_nineturn_daily` 只读事务确认 2000-01-04～2026-08-14、6,450 日、42,633 行，最新日 11 行/11 code。历史批量发布未登记 serving asset 的 runless events，因此正式实例里 2026-08-14 serving materialization/check 为空；该差异不授权补历史事件，也不阻塞首次自然 serving run。
4. **run key 与 cursor**
   - 两个 Gold sensor 的 run key 分别为 `gold_major_index_daily_nineturn_update:<trade_date>` 和 `gold_major_index_mins_nineturn_update:<trade_date>`；同一交易日只能提交一次自动 run，失败后不得通过变造 run key 自动重试。
   - serving run key 使用 `consumer + upstream_batch_id`，batch id 绑定 producer run id 和 partition，不包含 Dagster storage id；同一个上游成功 run 幂等，新一次合法上游重跑可生成新的 serving batch。
   - run-status sensor 无历史 cursor 时，Dagster 1.13.6 会把首次 tick 的系统 cursor初始化为启动时最新成功事件并返回 `SKIPPED/Initiating`，不会回放历史成功 run。该首次行为必须作为启用验收，不得用手工设置 cursor 代替。
   - 日线/分钟稳态只读评估各 10 次，P95 为 233/179ms、最大 367/193ms；结果均 `all_ready`、0 run，cursor 分别 650/657 bytes。
5. **单 tick 与并发上限**

   | sensor | 最大读取 | 最大输出 |
   |---|---|---|
   | 日线 Gold | 10 个目标 + 10 个源文件；一个目标上游/latest-check batch；必要时再核验 1 个前序目标 | 1 个交易日、1 个 RunRequest、1 asset + 1 check |
   | 分钟 Gold | 30 个目标 + 30 个源文件；六个目标上游/latest-check batch；必要时再核验前序六频目标 | 1 个交易日、1 个 RunRequest、6 assets + 6 checks |
   | serving | 一个新的日线 Gold 成功事件；一个 Gold materialization/check；11 行 source/read-back | 1 个交易日、1 个 RunRequest、1 serving asset + 1 check |

   Dagster 当前 `max_concurrent_runs=1`，所有 run 串行。sensor tick 预算固定为 5 秒，常规 cursor 预算固定为 2KB，任何超限 fail closed。
6. **启用前隔离测试门禁**
   - 已新增 `tests/test_major_index_nineturn_sensors.py`：日线与分钟 Gold sensor 通过同一参数矩阵覆盖 missing registration、all ready、target integrity failed、upstream not ready、previous partition not ready、exception fail-closed、单 RunRequest、精确 run key 和 cursor ≤2KB。
   - serving sensor 已覆盖首次 cursor 初始化、非法 partition、Gold not ready、producer run id 幂等、合法重跑新 identity 和历史不回放；首次 tick 使用 `DagsterInstance.ephemeral()` 中预置的历史成功 run，断言只返回 `Initiating`、0 run，第二次 tick 仍为 0 run。
   - 新增 18 项隔离测试全部通过；与 M4-B/serving/sensor-tag/run-key 回归合并执行为 64 passed、35 subtests passed。测试只使用 `tmp_path`、Fake resource 和 ephemeral instance，不访问正式 Lake、Prod DB、正式 Dagster instance 或网络。
   - 测试没有暴露生产缺陷，因此未修改 sensor、asset/check/job、公式、路径、分区、run key/cursor builder、Definitions、资源或调度配置。启用前编码门禁已完成。
7. **获批后的启用顺序**
   - 启用前再次确认 active workspace selector、三个 sensor 均 `STOPPED`、无相关 active/queued run、最新窗口和 production serving 未漂移。
   - 先启用 serving run-status sensor；首 tick 必须只初始化 cursor，0 run。
   - 再启用日线 Gold sensor；当前基线首 tick 必须 `all_ready`，0 run。
   - 最后启用分钟 Gold sensor；当前基线首 tick 必须 `all_ready`，0 run。
   - 每一步都立即复核同一正式 origin 的 state/tick/cursor/run；前一步不满足时停止，不进入下一步。三者完成后才进入 M6-C，观察下一个交易日 2026-08-17。
8. **失败停止与恢复**
   - 启用阶段任一 non-zero run、错误 tick、错误 origin、历史回放、未知分区、cursor 异常、tick 超 5 秒或多 RunRequest，立即停止已启用三者。
   - 日线 Gold 失败时停止日线与 serving；分钟失败只停止分钟；公共 Lake/Dagster/resource 异常停止三者。恢复前重新出只读报告并再次批准，不能自动换 run key。
   - serving 的删除/插入/read-back 在单事务内，异常 rollback；Gold 成功但 serving 失败时保留 Gold 文件与事件，修复后只重跑 serving。
   - 回滚只把批准的三个 sensor 恢复为 `STOPPED`；不得删除 Lake 文件、Dagster events、生产行，不得 backfill、materialize、补 runless event、migration 或手工补分区。

M6-B 第一段和启用前隔离测试完成时停在第二次批准前；该句只记录当时的审批边界。后续启用与自然日验收已经按冻结顺序获批并完成：

9. **M6-B 第二段与 M6-C 正式结果（2026-08-17）**
   - `prod_core_index_daily_nineturn_sync_job_sensor`、`gold_major_index_daily_nineturn_update_job_sensor`、`gold_major_index_mins_nineturn_update_job_sensor` 当前均只有一个 active workspace state 且为 `RUNNING`，没有同名重复状态。
   - `2026-08-17` 三个自然 run 均为 `SUCCESS`：日线 Gold `31ef3c4e-cd79-4dff-97e3-6bb853e0dcd8`、日线 serving `e93e13f7-146f-4e2a-ad03-54c817714248`、六分钟 Gold `4f01133c-d67c-470e-8763-4c08e125736c`。这些运行由已启用 sensor 自然提交，不是手工 backfill、materialize 或 runless event。
   - `2026-08-17` 日线九转文件和 5/15/30/60/90/120 六个分钟九转文件均已存在；日线文件于 17:55 形成，六分钟文件于 18:16 形成。
   - 23:46～23:47 的日线/分钟 Gold 最新 tick 均为 `SKIPPED/all_ready`、0 run、无错误；23:51 的 serving 最新 tick 为空结果 `SKIPPED`、0 run、无错误。M6-B 与 M6-C 据此完成，M6-D 仍需独立收口最终 HTTP、产品边界、视觉和运维矩阵。

## 16. 测试矩阵

### 16.1 公式与资产

1. count 0、1～9、10+。
2. equal 重置、UP→DOWN、DOWN→UP。
3. 前四根历史不足、跨日、跨年、分钟跨日延续。
4. compact seed、缺旧 seed 精确 fallback、新标的从 0 开始。
5. 指数日线一个、分钟六个资产正向，1 分钟资产不存在的负向。
6. schema、分区、唯一键、源键覆盖、错误代码/频率、validate-then-promote。
7. 物理 11-code 与产品 10-code 边界；`000680.SH` 只允许物理存在。
8. 四个股票分钟 schema 精确等于既有八列合同，股票日线 schema 精确等于六列新合同；五个正式股票九转 schema 均不含 `close_qfq`。
9. 日线与分钟 writer 输入 fixture 均含 Gold QFQ `close`，正式输出不含任何价格字段，计数和信号与修正前 golden 逐行一致。
10. history batch 的 compact context 可以继续保存每只股票最多四根价格，日线最终 candidate 只输出六列，分钟 candidate 只输出八列。
11. 日线与分钟 check 接受各自新 schema、拒绝含 `close_qfq` 的旧 schema；源键缺失、重复键、错误分区、非法计数和非法信号继续失败。
12. 静态负向测试证明股票正式 asset/catalog/check/publisher/serving/model/query 不再读取或保存九转价格；指数日线 `close` 合同保持不变。
13. 日线列投影迁移前后 `(ts_code, trade_date)`、`up_count/down_count`、`nine_up_turn/nine_down_turn` 完全一致；测试不得在迁移路径调用公式重算。
14. QFQ factor repair、价格文件 size/mtime 变化和价格值差异都不会生成股票九转 repair 请求。

### 16.2 serving 与 API

1. 事务 delete/批量 insert/read-back/hash 任一失败 rollback。
2. 日线 SQL 只读新表，不含旧 Tushare view。
3. 四路严格未知/重复参数、日期、limit、cursor exact keys 与错配。
4. bar 窗口全匹配、零匹配、部分匹配、delayed、无 1～9 marker。
5. markers 升序、1～9、latestMarker、10+ null。
6. 股票 1/5/15 与指数 1 返回请求非法或根本不发请求。
7. `000680.SH` 404；`899050.BJ` 日线正向、六个分钟频率 source empty。
8. 生产分钟路由 404；local 能力矩阵逐项通过。
9. 响应 5MB、最大 limit、文件数上限和 P95 门禁。
10. 股票分钟 Reader 不要求、不查询、不返回九转 `close_qfq`；API markers、分页、状态和与 Gold QFQ K 线的时间键对齐保持不变。
11. 股票日线 ORM、query 和 serving publisher 均不选择 `close_qfq`；对外日线 DTO、markers、分页、状态和异常合同保持不变。
12. Alembic migration 只删除股票 serving 的 `close_positive` 约束和 `close_qfq` 列，保留主键、索引、计数/信号约束、formulaVersion、权限和全部既有行。

### 16.3 前端

1. shared registry 按完整 key 缓存，AbortController + request id 防串标。
2. 支持周期发一次请求；不支持周期零请求。
3. READY/EMPTY/SOURCE_EMPTY/PARTIAL/ERROR/FORBIDDEN/UNSUPPORTED。
4. 九转失败时 K 线、MA/BOLL、MACD、KDJ、趋势、权重和右栏其它项仍在。
5. 只画 1～9；10+ 不重复画 9。
6. marker 时间键、方向锚点、18×18、8px、极值、密集序列和分钟时区。
7. stable primitive 更新不改变 `dataKey`、120 根默认视窗或当前缩放范围。
8. 上证日线趋势 + 九转双 primitive attach/detach。
9. Index Technical production 只请求 day；local 复用 day/15/30/60/90/120 缓存。六行固定渲染，1分钟和5分钟不进入摘要且零摘要预取请求。

### 16.4 浏览器与视觉

1. 1600×1200 保存股票/指数日线基线。
2. 股票日线及 30/60/90/120 代表状态。
3. 指数日线及 5/15/30/60/90/120 代表状态。
4. 北证50分钟 SOURCE EMPTY、禁用周期、错误重试、趋势双图层。
5. 普通 UI 相对基线偏差不超过 2px；图表、坐标轴、Tooltip、工具栏和右栏不位移。
6. 无新增换行、裁剪、重叠、横向溢出或 marker 参与 autoscale。

## 17. 性能预算

1. 日线默认 300、分钟默认 500；页面默认只显示约 120 根，历史余量供缩小和拖拽。
2. 单 endpoint 正式 P95 目标不高于 1.5 秒，硬门禁 5 秒。
3. 最大 10,000 分钟 bar 单独验证响应大小、扫描文件数和 cursor；不作为页面默认请求。
4. Reader 文件上限 5,000；超过时 `NT_REQUEST_INVALID` 要求缩小窗口。
5. primitive 每次 render 只处理 visible logical range；不得每帧遍历全历史。
6. 同一缓存 key 不重复请求；切右栏 Tab 不重建 chart。
7. 股票分钟九转连续执行两批、每批 40 次默认 500 根请求；第一批允许建立 DuckDB 高水位，第二批 Web RSS 增量目标不高于 32MiB，超过 64MiB 必须停止验收并定位，不得只记录平均延迟。
8. 分钟去价格正式重建按 `freq + year` 串行执行 set-based DuckDB 计算，单个审计动作必须在 5 分钟内完成；超过预算立即停止并缩小批次，不得继续扩大扫描。
9. S2 执行前只读预算基线为四频各 3,067 个正式文件，共 12,268 个目标分区文件、约 1.39GiB；正式计划已重新冻结为后文记录的 12,272 个目标，旧数字不代表当前物理规模。执行计划必须冻结 ready 日期集合、源/目标行数、candidate 文件数、磁盘空间和 event 数，任何差异均 `should_stop=true`。
10. 去价格 canonical plan/build/audit 专用 DuckDB 固定 `memory_limit=2GB`、`threads=1`，年度批次结束后关闭连接；管理员批准的进程峰值 RSS 上限为 16GiB。plan、candidate build 和 candidate audit 都必须把真实 `observed_peak_rss_bytes` 写入报告，超限即 `should_stop=true`。首次 4GB/2线程试跑约 6.40GiB，2GB/1线程试跑降至约 4.42GiB；两份试跑计划均因合同继续修订而作废，不能用于 S3。
11. 股票日线去价格当前只读基线为 3,066 个正式文件、2014-01-02～2026-08-12、约 157MiB；历史已验收 11,638,636 行。正式执行前必须刷新文件数、日期、总行数、schema、正式/候选空间和 event 数，任一值未冻结时不得开始写入。
12. 日线迁移只执行六列列投影，按年度串行生成 candidate；DuckDB 固定 `memory_limit=2GB`、`threads=1`，进程峰值 RSS 上限为 16GiB，单批超过 5 分钟或计划/输出键、计数、信号不一致时立即停止。

## 18. 发布顺序与回滚

上线顺序：

1. 已完成既有 migration、Gold/serving、日线 API、shared primitive、股票接入和 M4-B 指数后端发布。
2. 先实施股票分钟去价格代码与隔离测试，不触碰正式 Lake 或 Dagster runtime。
3. S2 新鲜只读计划全绿后，进入 S3 停止相关分钟 sensor 和本地 Reader，在正式 staging 生成并全量审计 candidate。
4. candidate 全绿后逐文件原子替换正式分钟九转 Parquet；不得先删除正式文件，不得在正式 Lake 内生成临时文件。
5. 物理验收通过后补全部四资产 materialization events，只补最近 20 个交易日 checks；验证 latest state/readiness 后再恢复 sensor 和 Reader。
6. M5 指数页面接入、M6-A 生产发布、M6-B 三个指数 sensor 启用以及 M6-C `2026-08-17` 自然触发均已完成；后续只剩 M6-D freshness/最终验收。
7. M6 必须严格按第 15.7 节执行；已完成的 M6-B/M6-C 不自动授权未来 Dagster instance 写入、sensor 启停、backfill、materialize 或 runless event。
8. 股票日线去价格按第 21 节独立执行：先代码与隔离测试，再只读计划、staging candidate、正式 Lake 原子提升、events、生产 migration/部署和 sensor 恢复；任一阶段不自动授权下一阶段。

回滚：

1. 前端先将 page-init `nineTurnPeriods` 置空并停止请求。
2. 回滚 API/router 不删除事实表或 Lake 文件。
3. publisher 停止调度，保留最后成功 serving 分区供审计。
4. 不用 Tushare、Mock 或客户端计算作为应急替代。
5. 分钟 schema 回滚只能恢复经过冻结和校验的旧正式文件集合；不删除历史 Dagster events，不修改日线或 Prod PostgreSQL。
6. 日线去价格是删除冗余事实的前向合同变更，不恢复 `close_qfq`。失败时停止日线 Gold/serving writer 和 Web 日线九转读取，按 checkpoint 完成前向修复；价格事实始终从 `gold_stock_daily_qfq` 读取，不建立兼容列、旧表或 Tushare fallback。

## 19. M1 退出评估

M1 已完成：

1. M0 正式收口，无未解释的 P0 产品或架构冲突。
2. 代码影响面、依赖边界、复用点和当前缺口已审计。
3. 股票/指数资产、路径、分区、job、sensor 和 universe 已冻结；2026-08-15 已完成四个股票分钟资产去价格迁移，2026-08-17 又在第 21 节完成股票日线六列无价格合同 D0～D6 的代码、正式 Lake、Gold/serving events、生产 migration/部署、认证 DTO、三日自然发布和 READY 页面视觉；指数合同不变。
4. 两张 serving 表、publisher、查询基表和无 fallback 边界已冻结。
5. 四个 endpoint、参数、DTO、状态、异常、cursor 和性能预算已冻结。
6. 前端 registry、capability、primitive 几何、右栏摘要和状态机已冻结。
7. `freq BIGINT` 疑点已证伪，正式物理类型确认是 INTEGER。

M3-B 已完成，M4-B 正式执行也已收口：

1. migration 已在生产执行；目标表最终只读确认有 3,066 个交易日、11,638,636 行，与冻结计划逐日行数一致，全历史发布已完成。
2. 45,442 行 close 漂移对应的 Gold scoped rebuild 已完成；11,638,636 行全历史键、价格、计数和信号差异均为 0。
3. 股票 serving sample、余下 1,953 日历史发布和最终全量对账均已完成。指数 32,124 个正式目标分区、64,248 条 Dagster events、生产 migration、6,450 日/42,633 行 serving 历史与全量对齐/性能验收也已完成。
4. 历史执行阶段曾停止股票 Gold sensor，serving sensor 当时未启用；这不是当前实例状态。2026-08-15 重新审计确认股票日线 Gold、股票分钟 Gold 和股票日线 serving 三个 sensor 当前均为持久化 `RUNNING`，最近 tick 全部 `SKIPPED` 且没有发起 run；完整状态和阻断原因见第 4.5 节。
5. Gold 历史发布基线已经完成；生产日线真实 API、数据样本与 Loaded 截图已通过主体门禁。用户已取消登录态正式 P95 与生产缩放边界截图两项补充验收，M3-C 据此完成。S6 新发现的日线冗余价格漂移及自然链路阻塞不属于前端退出条件；第 21 节独立专项已完成 D0～D6，包括代码、正式 Lake、Gold/serving events、生产 migration/部署、认证请求/DTO、三日自然发布和 READY 页面视觉。
6. M3-C-Minute 的严格 API、性能/内存、缓存/竞态、1/5/15 禁用周期和 1600×1200 浏览器行为门禁已通过；2026-08-15 去价格专项又完成四个正式分钟资产的八列迁移、事件恢复、Reader/readiness 与分钟 sensor 最近窗口自然评估，因此分钟页面行为和物理合同均已收口。下一交易日新增分区只作为运维观察；该结论不扩展到日线或指数九转。
7. S7/M5 已完成指数 page-init capability、日线/分钟共享 marker、Technical 摘要、局部状态和浏览器验收；2026-08-16 补充合同把 Technical 摘要替换为固定 day/15/30/60/90/120 六行。M6-A 已完成生产窄发布和生产浏览器验收，M6-B 已完成三个指数 sensor 启用，M6-C 已完成 `2026-08-17` 日线、六分钟和 serving 自然运行验证；M6-D 最终全链路验收仍待完成。

## 20. 股票分钟 QFQ 九转去价格字段专项

### 20.1 目标与边界

本节记录 2026-08-15 股票分钟去价格专项在当时批准范围内的设计和正式执行事实。其中“日线完全排除”仅表示该次分钟迁移没有越界修改日线，不再代表本文当前最终合同；股票日线的新合同与后续执行门禁以第 21 节为准。

本专项只修改以下四个正式资产：

```text
gold_stk_mins_qfq_nineturn_30m
gold_stk_mins_qfq_nineturn_60m
gold_stk_mins_qfq_nineturn_90m
gold_stk_mins_qfq_nineturn_120m
```

目标是从正式分钟九转 Parquet 中删除唯一价格字段 `close_qfq`。公式仍读取同频 `gold_stk_mins_qfq.close`，最终资产只保存业务键、九转计数和九转信号。asset、check、job、sensor 名称和物理路径保持不变，不新增配置或自动 repair sensor。

`gold_stock_daily_qfq_nineturn` 及其 Lake、Prod PostgreSQL、publisher、Reader、API、事件、check、job、sensor 和历史工具完全排除在本专项之外。指数九转资产同样不在本专项范围内。

### 20.2 代码与合同落点

| 合同 | 修改要求 | 日线隔离门禁 |
|---|---|---|
| `GOLD_STK_MINS_QFQ_NINETURN_SCHEMA` | 删除 `close_qfq`，冻结为八列 | 2026-08-15 当时未改日线；当前日线六列合同见第 21 节 |
| `qfq_nineturn.py` | 内部 `close_value` 和公式不变；分钟最终 projection 删除价格 | 当时日线仍输出价格；当前由第 21 节删除最终价格 projection |
| writer/asset/catalog | observed/definition schema 使用八列合同，asset key/path 不变 | 当次执行未改日线；当前日线落点见第 21.3 节 |
| `qfq_nineturn_integrity.py` | 分钟分支删除价格值域和源值比较；保留 schema/分区/键/覆盖/计数/信号 | 当时日线仍校验价格；当前由第 21 节删除价格门禁 |
| readiness/event helper | 复用新的分钟 check 诊断，不新增 check 名 | 当次执行未改日线；当前 event recovery 见第 21.5 节 |
| `qfq_nineturn_history.py` | candidate/final audit 使用八列；compact context 可保留四根价格 | 当次执行未改日线；当前日线只做列投影迁移 |
| `StockNineTurnLakeReader` | column specs、校验 SQL、join projection、内部 row 删除 `close_qfq` | 分钟 Reader 与日线 Prod 查询隔离；当前日线查询去价格见第 21.3 节 |
| Biz/API | marker、分页、cursor、状态和异常合同不变 | 日线 endpoint 对外合同始终不变；内部查询按第 21 节去价格 |

生产 check 不负责重新证明九转公式。lag=4、方向切换、segment、seed、10+ 计数和 `+9/-9` 信号由共享内核的独立 golden fixture 负责；正式分钟 check 只验证本次真实文件事实。明确不做全历史“前复权等比例缩放前后九转一致”扫描。

### 20.3 Bootstrap 与正式重建

代码与隔离测试完成不代表正式数据已经迁移。正式重建必须单独审批，并采用 `Direct Lake Bootstrap + Runless Event Backfill`，不是 Dagster backfill：

1. 停止覆盖这四个分钟资产的相关 sensor；停止或关闭持有本地 DuckDB Reader 连接的 Web 进程，不新增临时配置开关。
2. 以四频 `gold_stk_mins_qfq_<freq>m` 上游各自 blocking checks 通过的 source-ready 交易日交集冻结重建范围，同时冻结 source 路径、预期目标文件数、源键行数、size/mtime 和计划指纹；不得用旧九列目标资产的 check 状态裁掉本应重建的日期。
3. 在 `/Volumes/datasource/data_lake_staging` 按 `freq + year` 串行生成 candidate；每批使用 DuckDB set-based SQL，不把分钟明细装入 Python，不逐行写 Parquet。
4. compact context sidecar 可在 staging 保存每只股票最近四根 `close_qfq`；它只用于下一批公式计算，不进入 candidate 最终 schema，不被 Reader/API 读取。
5. candidate 审计使用聚合集合差异和代表性样本，验证八列 schema、文件数、行数、分区、唯一键、源键覆盖、计数和信号；不比较价格，不重算全量公式。
6. 全部 candidate 通过后，逐文件执行同文件系统原子替换。不得先删除正式文件，不得把 candidate、临时文件或 checkpoint 写进正式 Lake。
7. 任一 schema、键、行数、信号、源身份或计划指纹异常立即停止；已替换文件按 checkpoint 保留，可续跑，未替换正式文件保持原样。
8. 正式替换结束后必须确认四频所有目标文件均为八列合同；任何新旧 schema 混存都视为失败，Reader 不得恢复。

S2 执行前只读预算基线（不代表当前物理规模）：

| 频率 | 当前文件数 | 当前日期范围 | 当前目录大小 |
|---:|---:|---|---:|
| 30m | 3,067 | 2014-01-02～2026-08-13 | 约 626MiB |
| 60m | 3,067 | 2014-01-02～2026-08-13 | 约 335MiB |
| 90m | 3,067 | 2014-01-02～2026-08-13 | 约 267MiB |
| 120m | 3,067 | 2014-01-02～2026-08-13 | 约 192MiB |
| 合计 | 12,268 | 执行前重新冻结 | 约 1.39GiB |

正式只读计划还必须输出源行数、candidate 预计行数、批次数、预计临时空间和替换成本；这些值未冻结或任一审计动作预计超过 5 分钟时，禁止进入写入阶段。

### 20.4 Dagster Event Recovery

物理重建验收通过后才能补事件：

1. 为冻结范围内四个资产的全部分区追加新的 materialization event。
2. 只为每个资产最近 20 个交易日追加绑定新 materialization 的 passed check event；当前基线预计最多 80 条，正式计划按冻结日期集合精确计算。
3. 不扫描完整 Dagster event history，不删除、覆盖或修改历史 run、materialization、check event 或 PostgreSQL 记录。
4. event helper 必须复用新的八列 blocking check 语义，只对已通过物理验收的文件写绿事件。
5. 补录后只使用聚合 event count、latest state、partition 归属和少量 readiness 样本验收；不得逐分区深扫全部历史。
6. latest state 和最近 20 日 readiness 通过后，才能恢复 sensor 和本地 Reader。

### 20.5 测试与退出条件

代码阶段至少通过：

1. 当次分钟专项验收四频 schema 无 `close_qfq`，日线仍有 `close_qfq`；后者是 2026-08-15 历史事实，当前目标由第 21 节替换为日线六列无价格合同。
2. 分钟 writer 输入有 close、输出无价格，既有公式 fixture 计数与信号不变。
3. history batch context 可延续前四根价格，candidate 只输出八列。
4. 分钟合并 check 接受新 schema、拒绝旧 schema，并继续拒绝缺源键、重复键、错误分区、非法计数/信号。
5. 当次执行证明日线 check、writer、serving/publisher 和 Prod 未被分钟专项误改；当前日线专项按第 21 节独立修改并重新建立相应门禁。
6. 本地分钟 Reader 不读取 `close_qfq`；marker、分页、状态、K 线时间键对齐和 API 回归通过。
7. 静态门禁证明正式分钟 asset/Reader/catalog/check 不再引用输出 `close_qfq`，compact context 是唯一允许的分钟历史内部价格 sidecar。

专项退出条件已满足：代码合同通过，12,268 旧基线由正式计划重新冻结为 12,272 个目标，四频 candidate 全绿，正式文件无新旧 schema 混存，materialization/最近 20 日 checks 补录数量准确，latest state/readiness 与 Reader/API 通过，sensor 恢复后自然评估确认最近 5 日 ready。周六没有新增交易日，下一交易日新增分区只作为运维观察，不改变本次完成结论。

### 20.6 明确不做

以下条目是 2026-08-15 分钟专项的历史非目标，用于证明当次执行没有越界；第 1 条已由 2026-08-16 新批准的独立日线专项接续，不得用于阻止第 21 节实施。

1. 当次分钟专项不修改日线 `close_qfq`、日线历史、日线 Prod serving 或日线事件；当前已由第 21 节另立日线专项。
2. 不访问 Tushare 或生产数据库，不执行 migration。
3. 不新增 QFQ repair → 九转 repair sensor，不改变既有 job/sensor 名称。
4. 不扫描或删除 Dagster event history。
5. 不删除任何正式文件；正式文件只允许由完整 candidate 原子替换。
6. 不修改指数九转、不开放生产分钟 API、不改变页面 marker 合同。

### 20.7 正式执行结果

1. S2 计划 hash 为 `01d63b246a602f7c0b511beee19695bb85d07159c1ad815d5573c31e68d03757`，冻结 2014-01-02～2026-08-14、3,068 个交易日、12,272 个目标文件、52 个年度批次和 197,753,897 行；源范围、代码/文档 manifest、12,268 个旧 preimage 与 4 个新目标空位均通过复核。
2. S3 四频 candidate 分别为 93,044,536、46,531,692、34,898,769、23,278,900 行。四份 manifest 全绿后才按 30/60/90/120 顺序原子提升；正式聚合审计的缺失、schema、重复键、空键、分区、频度和非法值均为 0。最高单进程 RSS 10.61GB，低于 16GiB 门禁。
3. S4 为 event helper 增加显式资产选择并进入计划/fresh-plan/物理指纹；正式计划 fingerprint `2140016f3d4e29384bb78dfd01838c389a5907e132059fa3e30d22dd9affa7f5` 只包含四个分钟资产。实际追加 12,272 条 materialization 和 80 条最近 20 日 check，日线候选 0，post-plan 候选 0。
4. S5 正式 Reader 对 `000001.SZ` 四频各执行 10 次，全部逐根匹配、缺失 0、返回字段无价格；P95 为 150/32/29/25ms。最近 5 日 readiness 检查 20/20 文件、470,832 行，失败行 0，耗时 2.11 秒。Orchestrator 专项 61 项和 16 个子测试、Foundation/API 32 项通过，Definitions 加载成功。
5. `orchestrator` code location reload 后，分钟 sensor 当前为正式 origin 单一 `RUNNING` 状态；12:13:01 最近自然 tick 为最近 5 日均 ready，0 run。执行未访问 Prod DB/Tushare，未执行 migration/Kopia/Dagster backfill，未修改日线或指数数据。

## 21. 股票日线 QFQ 九转去价格字段专项

### 21.1 目标与不可变边界

本专项只修改股票日线自主 QFQ 九转链路：

```text
gold_stock_daily_qfq_nineturn
prod_core_stock_daily_qfq_nineturn
core_serving.equity_qfq_nineturn_daily
股票日线九转 ORM / query / publisher / check / history 工具
```

最终业务合同：

1. 前复权收盘价只作为统一九转公式内核的计算输入，不属于正式九转结果事实。
2. 前复权价格重算是同比例变化，不改变任意两根 K 线的大小关系，因此不改变 lag=4 方向、segment、连续计数或九转信号；价格重算不构成九转 repair 条件。
3. 历史迁移只删除冗余价格列并保持现有键、计数和信号，不重新执行九转公式。
4. `gold_stock_daily_qfq_nineturn` 的 asset key、路径、分区、check、job 和 sensor 名称不变；生产 serving asset/table 身份不变。
5. 不新增 QFQ factor repair → 九转 repair sensor，不新增配置、兼容列、兼容表、旧 schema Reader 或 Tushare fallback。
6. 不修改四个已完成迁移的股票分钟资产，不修改指数日线/分钟九转的 `close` 合同，不修改 API DTO、前端、Figma 或页面 marker。

日线 Gold 最终六列合同：

```text
ts_code VARCHAR
trade_date DATE
up_count INTEGER
down_count INTEGER
nine_up_turn VARCHAR nullable
nine_down_turn VARCHAR nullable
```

生产 serving 最终八列合同：

```text
ts_code VARCHAR(16) NOT NULL
trade_date DATE NOT NULL
up_count INTEGER NOT NULL
down_count INTEGER NOT NULL
nine_up_turn VARCHAR(2) NULL
nine_down_turn VARCHAR(2) NULL
formula_version SMALLINT NOT NULL
published_at TIMESTAMPTZ NOT NULL
PRIMARY KEY (ts_code, trade_date)
INDEX (trade_date, ts_code)
```

### 21.2 当前事实与影响面

2026-08-16 分阶段审计与执行确认：

1. D2 正式计划已重新冻结 3,066 个七列旧 schema 文件，覆盖 2014-01-02～2026-08-12，共 11,638,636 行、158,269,066 bytes；每个文件的相对路径、size、mtime、SHA-256 和行数均已进入计划。13 个年度批次的 schema、重复键、空键、分区和值域检查全部通过，无额外正式文件。
2. D1 已将 `GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA`、writer 最终 projection、partition validator、catalog、合并 integrity check 和日常历史工具切换为六列；旧七列只允许出现在专用列投影迁移工具的 legacy 输入合同中。
3. D1 已将 `PROD_CORE_STOCK_DAILY_QFQ_NINETURN_SCHEMA`、publisher、read-back、content hash、checkpoint audit 和生产 blocking check 切换为无价格业务内容；D5-A 已将这些代码随 `9fec9a26f09e5ff72dbd75572bf6af24f72f8410` 部署生产。
4. D5-A 已执行 migration `20260816_000137`。正式 `core_serving.equity_qfq_nineturn_daily` 现为八列无价格合同，不再包含 `close_qfq` 与 `ck_equity_qfq_nineturn_daily_close_positive`；初始建表 migration 作为不可修改的历史记录继续保留旧列定义。
5. 生产 Biz 日线 query 已不再选择 `close_qfq`。`NineTurnSeriesDto`、marker 映射和页面始终不使用或输出价格，对外 API 合同不变；D5-B 已通过认证请求链路、远程只读 DTO 和独立生产页面视觉验收。
6. 日常增量已经从 `gold_stock_daily_qfq` 的有限窗口读取计算价格，上一九转分区只提供 `up_count/down_count` seed；正式九转结果删除价格不会破坏增量连续性。

CodeGraph 影响面固定为：

```text
asset_column_schemas
  -> qfq_nineturn writer / validation / history
  -> qfq_nineturn_integrity / readiness / events
  -> lake asset catalog / definition metadata
  -> stock daily prod publisher / hash / checks
  -> Alembic / ORM model / Biz query
  -> NineTurnSeriesDto（外部合同不变）
```

### 21.3 代码与合同落点

| 落点 | 必须修改 | 禁止事项 |
|---|---|---|
| `GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA` | 删除 `close_qfq`，冻结六列和字段说明 | 不改 asset key、路径或分区 |
| `qfq_nineturn.py` | source 继续把 QFQ `close` 映射为内部 `close_value`；日线最终 projection 删除价格 | 不复制公式，不改变 lag/segment/seed/fallback |
| writer / asset / catalog | definition schema、observed columns、描述改为六列无价格事实 | 不新增第二个日线资产或兼容 schema |
| `qfq_nineturn_integrity.py` | 日线删除价格正值、`source_value_consistency` 和价格 failure sample；保留文件、分区、键、源键覆盖、计数/信号值域 | 不以价格值或 QFQ 文件变化阻断 ready |
| history / migration helper | 新增独立日线列投影 plan/candidate/audit/promote/checkpoint 流程 | 不调用公式重算，不复用分钟全历史公式 rebuild |
| readiness / event helper | 消费六列新 check；支持显式日线 asset 事件恢复范围 | 不删除或改写历史 events |
| prod publisher / DB helper | 删除 row normalize、SQL、insert、select、hash、read-back 中的 `close_qfq` | 不从 QFQ 表补回价格，不做全历史 reinsert |
| serving schema / ORM / query | 删除 `close_qfq` 字段和选择；`nine_turn_matched` 继续只由 `formula_version` 判断 | 不改变 DTO、cursor、状态或 API 路由 |
| Alembic migration | 从真实当前 head 新增 migration，删除 `close_positive` 约束与 `close_qfq` 列 | 不猜 `down_revision`，不新增兼容列/影子表 |
| 测试与静态门禁 | 更新 schema、writer、check、history、publisher、ORM、query、API 和文档指纹 | 不修改分钟/指数业务合同 |

本专项不新增环境变量或运行时开关。Lake root、staging root、DuckDB 连接参数、Prod 写资源和既有权限来源保持现有集中配置；配置项审计结果为“无新增配置”。

2026-08-16 D1 实施结果：

1. Gold 日线最终 projection、schema、writer、validator、catalog、integrity/readiness/event metadata 已切换为六列；公式仍只从规范化 Gold QFQ `close` 取得内部 `close_value`，lag、segment、seed、fallback 和分钟/指数合同未改。
2. 新增独立日线列投影 plan/candidate/audit/promote/checkpoint 工具与 CLI。计划只冻结旧九转文件身份，不绑定 QFQ 价格文件；candidate 按年度 set-based 投影，固定 DuckDB `2GB/1 thread`、单批 5 分钟和进程峰值 16GiB 门禁。
3. serving publisher/DB helper/content hash/read-back、SQLAlchemy ORM 和 Biz query 已删除 `close_qfq`；新增 `20260816_000137` migration，真实 `down_revision` 为 `20260814_000136`，只删除目标约束和列，未执行 migration。
4. Definitions 只读发现确认 Gold/serving 两个既有 asset 和两个 blocking check 仍可发现；94 项 Orchestrator 专项测试、35 项 Foundation/Biz/API 回归、两组 Ruff/compile 门禁全部通过。
5. D1 没有读取或写入正式 Lake、正式 Dagster instance 或生产数据库，没有启动 job/sensor、生成 candidate、登记 event、执行 migration 或部署代码。正式物理数据仍为旧合同，须从 D2 只读计划继续。

2026-08-16 D2 只读执行与停写门禁结果：

1. 初始 Lake 计划 hash 为 `085c6f4e6cb6496651ffca5fdf97b44c4f7771e0f3e785594b686dad689ea489`，当时唯一停止原因为 `writer_not_stopped`。用户随后批准停写门禁；12:13～12:15 通过正在运行的 active workspace `orchestrator / __repository__` 精确停止 `gold_stock_daily_qfq_nineturn_update_job_sensor` 和 `prod_core_stock_daily_qfq_nineturn_sync_job_sensor`，停止前后关联 job 的 `NOT_STARTED/QUEUED/STARTING/STARTED/CANCELING` run 均为 0。不得用 `dagster sensor list -m orchestrator.definitions` 创建的临时代码位置状态替代 active workspace 事实。
2. 停写后重新生成的全绿 Lake 计划 hash 为 `9f8835a36931f11f46d1ec589110bb2e83e6cd70b14e267fd5e41f0a1b840f60`，`should_stop=false`、`stop_reasons=[]`。计划仍精确冻结 3,066 个七列旧文件、2014-01-02～2026-08-12、11,638,636 行和 158,269,066 bytes；新旧计划的分区路径、size、mtime、SHA-256 与行数集合指纹同为 `921c32b8aa7766eb43c29c39810f147da2553d9e8c9821e266a4d84742203f03`，证明停写期间源文件没有漂移。
3. 13 个年度批次全部 ready；schema、重复键、空键、分区和值域失败数均为 0。年度合同聚合最慢 0.381 秒，计划总耗时 5.035 秒，峰值 RSS 386,416,640 bytes，DuckDB 保持 `2GB/1 thread`；staging 可用 2,520,214,380,544 bytes，预计最低需要 1,232,010,890 bytes。独立业务字段聚合仍确认最大上/下计数 44/47，`up_count>9/down_count>9` 为 368,312/468,502 行，`+9/-9` 为 507,156/631,453 行，非法计数和信号均为 0。
4. D2 阶段的 Gold event 预计划 fingerprint 为 `6887d486335ca4f83abcd15c9c1609a71a09fa3aa660f818279bd08186ec7ece`，当时预计追加 3,066 条新版 materialization 和最近 20 日 20 条新版 blocking check，共 3,086 条。D3 已改变正式文件身份，因此该旧预计划保持不可执行并已作废；D4 必须以 D3 提升后的新文件身份重新生成 fresh plan，不能直接复用该 fingerprint。
5. 生产只读事务确认真实 Alembic 单一 head 为 `20260814_000136`；`core_serving.equity_qfq_nineturn_daily` 仍是 9 列旧合同，含 `close_qfq` 和 `ck_equity_qfq_nineturn_daily_close_positive`，共有 3,066 个交易日、11,638,636 行，范围 2014-01-02～2026-08-12。重复键、空键、非法计数/信号、非 v1 版本和非法价格均为 0；主键、`(trade_date, ts_code)` 索引和现有权限已冻结。
6. serving event 预计划 fingerprint 为 `076a9b79ca1e317aac6279879afc01f2adc3032c562e980354836264d951cd50`：当前 Dagster instance 对 serving asset 没有历史 materialization/check 事件；DDL/部署后预计追加 3,066 条 materialization 和最近 20 日 20 条 check。它仍须在 D5 维护窗口内按迁移后生产表与部署版本重新生成。
7. 新 D2 计划的写计数仍全部为 0：candidate、正式 Lake、Dagster event、Prod 行均未写；staging phase/candidate 目录未生成，migration 和部署未执行。本轮唯一正式变更是停止两个 writer sensor。D2 已满足进入 D3 的前置条件，但 D3 仍需单独批准，不能因本次停写与计划批准自动开始。

### 21.4 正式 Lake 列投影迁移

正式迁移采用 `Direct Lake Bootstrap + Runless Event Backfill`，不是 Dagster backfill。原因是 3,000+ 个既有日分区只需进行确定性 schema 投影，逐分区启动 Dagster run 会放大调度和事件成本，且没有公式计算价值。

阶段固定为：

1. **只读计划**
   - 冻结 `gold_stock_daily_qfq_nineturn` 正式旧文件的相对路径、日期集合、size、mtime、schema、行数和 SHA-256 身份。
   - 聚合统计源文件数、总行数、唯一键、空键、计数/信号值域、年度批次、candidate 空间和正式 event 数。
   - 计划不得扫描或绑定 `gold_stock_daily_qfq` 价格值；价格差异、价格文件 size/mtime 变化不得进入 `stop_reasons`。
   - `should_stop=true`、范围未封闭、正式 writer 未停止或 staging 空间不足时禁止生成 candidate。
2. **样本 candidate**
   - 只允许 1～3 个显式计划内分区。
   - 使用 DuckDB `COPY (SELECT ts_code, trade_date, up_count, down_count, nine_up_turn, nine_down_turn ...) TO parquet` 写入 `/Volumes/datasource/data_lake_staging`。
   - 验证六列 schema、行数、键、分区、计数、信号，以及新旧文件的六个非价格业务字段逐项一致。
3. **全量 candidate**
   - 按年度串行，DuckDB set-based 执行；Python 只负责路径规划、批次、checkpoint、摘要和失败样本。
   - 不读取 QFQ 价格，不调用共享公式内核，不创建价格 sidecar，不把明细 `fetchall()` 到 Python。
   - 每个年度结束关闭 DuckDB 连接并记录行数、文件数、字节数、耗时和峰值 RSS。
4. **全量 candidate 审计**
   - 使用按年度集合差异和聚合计数验证文件集合、总行数、唯一键、分区、计数和信号。
   - 迁移前后 `(ts_code, trade_date, up_count, down_count, nine_up_turn, nine_down_turn)` 必须完全一致；任一差异立即停止。
   - 分区超过 100 时禁止逐分区深扫作为主验收；代表性分区仅用于失败样本和人工复核。
5. **正式提升**
   - 全部 candidate 通过且计划指纹仍一致后，才逐文件执行同文件系统 `os.replace()` 原子提升。
   - 不预删正式文件，不在正式 Lake 内生成临时文件，不使用 Kopia，不创建恢复副本。
   - 每个成功替换文件立即写 checkpoint；失败时停止，Reader/writer 保持关闭，按 checkpoint 继续前向完成，禁止对外开放新旧 schema 混存结果。
6. **物理终验**
   - 正式文件集合、行数、键、计数、信号与已审计 candidate 一致，旧七列文件数必须为 0。
   - 只在物理终验全绿后进入 Dagster event recovery。

2026-08-16 D3 正式执行结果：

1. 执行前 active workspace 中 `gold_stock_daily_qfq_nineturn_update_job_sensor` 与 `prod_core_stock_daily_qfq_nineturn_sync_job_sensor` 均为 `STOPPED`，关联 job 活跃运行数为 0；正式提升前停止 PID `86261` 托管的本地 Web/前端，本地 Reader 未恢复。
2. 样本阶段选择 2014-01-02、2020-04-17、2026-08-12 三个计划内分区，共 11,300 行。六列 schema、唯一键、分区、计数、信号及六个业务字段集合差异全部通过，样本审计峰值 RSS 为 183,730,176 bytes。
3. 全量 candidate 绑定计划 hash `9f8835a36931f11f46d1ec589110bb2e83e6cd70b14e267fd5e41f0a1b840f60`，按 13 个年度批次生成 3,066 个文件、11,638,636 行；生成耗时 4.682 秒，最慢年度批次 0.457 秒，峰值 RSS 790,364,160 bytes。
4. 全量 candidate 审计 13/13 年度 READY，源减候选与候选减源均为 0，manifest SHA-256 为 `7d8873bc3d4e1338133e4bd7beac0f6836865d1c67133c87115b6f8ab17190ca`；审计耗时 17.017 秒，峰值 RSS 1,015,595,008 bytes。
5. 全绿后通过同文件系统 `os.replace()` 原子提升 3,066/3,066 个正式文件，剩余 0，耗时 2.955 秒；每文件 checkpoint 已落盘，没有预删、Kopia、备份或正式 Lake 临时文件。
6. 正式终验确认 3,066 个文件、11,638,636 行全部为六列合同；hash 差异 0、candidate 残留 0、13/13 年度 READY、`should_stop=false`。本阶段 Dagster event 写入 0、Prod 写入 0，D4 event recovery 未开始。

### 21.5 Dagster event recovery

1. 先生成只读 event plan，冻结资产、分区集合、正式文件身份、预期 materialization 数、最近 20 个交易日 check 数和计划指纹。
2. 为全部已替换日线分区追加新的 materialization event；只为最近 20 个交易日追加绑定新 materialization 的 passed blocking check event。
3. 只对已经通过同一六列 blocking check 语义的正式文件写绿事件；任一失败分区不写 event，并阻止恢复 writer。
4. 不扫描、删除、覆盖或修改历史 Dagster run、materialization、check event 或数据库记录。
5. 通过聚合 event count、latest state、partition 归属和最近窗口 readiness 验收，不以全历史逐分区 readiness 深扫作为主门禁。
6. D4 只能使用 `stock_daily_qfq_nineturn_no_price_events.py` 与同名 CLI。旧 D2 preflight 显式不可执行，旧通用 history event plan 也没有绑定 D3 六列 formal audit；两者都不得作为本阶段输入。
7. 只读 plan 必须同时绑定：D3 Lake plan hash、`candidate-audit-full.json`、`formal-audit.json`、3,066 个正式文件的路径/size/mtime/SHA-256/行数、动态分区登记、两个 writer sensor 状态、两个关联 job 在途数和当前事件状态。任一输入漂移即重新生成 fingerprint，不允许继续 apply。
8. plan 的 Dagster 读取固定为一次目标 asset materialization 集合查询和最多 500 条目标 check history；不得逐分区读取全历史 event/readiness。Lake 侧只哈希约 157MiB 正式文件，并只对最近 20 日执行当前六列 `audit_qfq_nineturn_integrity`；不得重新运行全历史公式或读取价格事实。单计划硬上限为 4,000 条 materialization 和 20 条 check，超过即 `should_stop=true`。
9. event writer 仍唯一集中在 `qfq_nineturn_events.py`。专用 helper 只能调用该追加式入口，禁止直接写 event log、删除旧事件或创建 synthetic run。materialization 固定记录 `event_revision=stock_daily_qfq_nineturn_v2_no_price` 和逐文件 SHA-256；check 必须 passed、blocking 并绑定同 revision 的当前 materialization。
10. apply 前必须按原始参数重生成 fresh plan，比较 plan fingerprint、文件身份、候选集合和实例状态。若中途失败，重新生成计划仅选择未完成 revision；不得回删已追加事件。完成后 post-plan 候选必须为 0，current revision materialization 必须覆盖全部目标分区，current revision check 必须覆盖最近 20 日。
11. 隔离实例门禁已于 2026-08-16 通过：完整 plan/apply、二次空计划、文件漂移、未登记分区、显式 apply 与唯一 writer 的定向回归共 30 passed、97 deselected、2 subtests passed。另以真实 3,066 个正式文件配合临时实例完成 3,086 条全规模演练，post-plan 候选 0，墙钟 17.978 秒、apply 16.519 秒、峰值 RSS 279,003,136 bytes。该演练未连接正式 `DAGSTER_HOME`，临时 fingerprint 不可执行；正式 instance 的只读 plan 和 apply 当时仍须按命令级门禁单独批准，随后已按第 12～14 项完成。
12. 正式执行已于 2026-08-16 按命令级门禁完成。初次正式 plan 因 Gold writer 持久化状态仍为 `RUNNING` 而以 `writer_sensor_running` 停止；核验确认并不存在同名多记录，正式实例只有一个该名称的 sensor state。两个关联 job 活跃运行数均为 0 后，按精确 `origin_id/selector_id` 将其停止并复核两个日线 writer 均为 `STOPPED`。
13. 最终全绿 plan fingerprint 为 `acb325dd047a6d56f7d6ff7956289756a31ca1b17d764f4024b61650904c1d9f`，包含 3,066 个 materialization 和最近 20 日 20 个 check 候选，`should_stop=false`、`stop_reasons=[]`；plan 阶段正式事件、Lake、Prod 写计数均为 0，耗时 1.623 秒、峰值 RSS 267,255,808 bytes。
14. 经批准执行的 apply batch id 为 `e2736d05-bf1b-4b82-86ed-b4d7dc79b526`，实际向正式 instance 追加 3,066 条 `stock_daily_qfq_nineturn_v2_no_price` materialization 与 20 条绑定当前 revision 的 blocking-check event，耗时 33,569.71ms。自动 post-plan 确认候选 0、当前 revision materialization 3,066、check 20；两个日线 writer 继续为 `STOPPED`，未写 Lake 或 Prod，未删除历史 event。D4 据此完成。

### 21.6 生产 serving migration 与部署

生产变更必须使用独立维护窗口，顺序不可调整。2026-08-16 当次远程 sudo 白名单只允许 `restart`、不允许 `stop` Web，因此 D5-A 已按“新代码先行、DDL 随后”执行，不能按旧设想先停 Web：

1. 只读确认真实 Alembic 单一 head、生产表 schema/约束/索引/权限、交易日数、行数、重复键和最近 serving readiness。
2. 停止 `prod_core_stock_daily_qfq_nineturn_sync_job_sensor`，确认 Gold/serving 两个 writer sensor 均为 `STOPPED` 且关联 job 无在途 run；先以 `--skip-migration` 发布已删除价格消费者的新 Web 代码并重启。新代码只查询八列无价格合同，旧九列表是其严格超集，因此此步不需要双 schema、兼容查询或运行时探测列。D5-A 已完成版本与健康接口验证；认证日线九转 API 未在该阶段完成，明确保留为 D5-B 验收项，不能追溯性写成已通过。
3. 确认远程进程已加载新代码后执行 Alembic migration：删除 `ck_equity_qfq_nineturn_daily_close_positive` 和 `close_qfq`；保留全部既有行、主键、索引、计数/信号约束、`formula_version`、`published_at` 与权限。
4. migration 完成后立即重启并验收新 Web；禁止旧版本进程、双 schema、兼容查询或运行时探测列。若第一段代码发布或健康检查失败，禁止执行 DDL；若 DDL 后验收失败，按前向修复原则保持 writer 停止并修正新代码，不得恢复价格列。
5. 不重发 11,638,636 行历史 serving。迁移后使用无价格业务字段做全历史聚合对账，确认交易日、行数、键、计数、信号和 formulaVersion 不变。
6. 生成 serving event 只读计划；为受 DDL 影响的全部交易日追加新 materialization，最近 20 日追加新版 blocking check。不得删除旧 events。
7. D5-A 完成生产表精确 schema、权限和全历史聚合验收后已保持 Web 运行；D5-B 随后通过 serving events、认证 API、markers/分页/状态、无 `close_qfq` SQL 静态门禁和生产页面视觉验收。D6-2 已恢复 serving 与 Gold sensor 并完成三日自然发布；`equity_factor_pro` 于 2026-08-17 22:54 覆盖当日数据后，D6-3 READY 页面复验通过。

D5 使用正式、可复用的两段门禁，不再执行 D2 的 `/private/tmp` 估算脚本：

1. `stock_daily_qfq_nineturn_no_price_serving_events_cli snapshot` 只通过仓库唯一远程数据库入口 `scripts/psql-remote.sh` 执行 `BEGIN READ ONLY`，一次性冻结生产 `alembic_version`、列定义、命名业务约束、索引、权限、owner、行数和日期范围；系统生成且对象 ID 不稳定的 PostgreSQL 18 `NOT NULL` 约束名不进入名称合同，非空语义由 `columns.is_nullable` 精确冻结。报告写入 `/private/tmp`，不写生产库或 Dagster，也不得直连或为审计扩大账号权限。
2. migration 与新代码部署后，`plan` 必须同时绑定迁移前快照、D4 零候选计划和实际部署的完整 Git SHA；逐分区读取六列 Gold 业务字段生成无价格 hash，并仅通过 `scripts/psql-remote.sh` 的 `COPY` 流式读取生产七个无价格业务/版本字段，对账全部 3,066 日和 11,638,636 行。进程任一时刻只保留一个交易日的 SHA-256 状态，不把全表装入内存。计划只有在列精确删除一项、约束精确删除一项、索引/权限/owner/行数/日期范围完全不变、两个 writer sensor 均停止、无在途 run 且 D4 Gold 事件仍为当前版本时才可执行。
3. `apply --apply` 必须先重新生成同指纹计划，随后只经共享 runless-event writer 追加 serving materialization 与最近 20 日 blocking check；不调用历史 publisher、不删除旧事件、不写 Lake 或 Prod。写后只复核事件状态，物理数据已在 fresh plan 中再次全量只读对账，避免第三次无意义扫描 11,638,636 行。
4. 正式实现文件固定为 `stock_daily_qfq_nineturn_no_price_serving_events.py` 及其 CLI；event metadata 必须包含 `stock_daily_qfq_nineturn_serving_v2_no_price`、migration revision、部署 revision、Gold 文件 SHA 与无价格业务 hash，保证后验计划候选为 0 且不会把旧 serving 事件误认成新合同。

#### 21.6.1 D5-A 已执行事实与迁移纠错

1. GitHub→Gitee 镜像确认到完整提交 `9fec9a26f09e5ff72dbd75572bf6af24f72f8410` 后，生产先通过 `--skip-migration` 部署该版本；独立复核生产仓库 SHA、systemd active 和两个 health endpoint 后才进入 migration。
2. 首次 migration 尝试在第一条 DDL 失败：Alembic 命名约定把已存在的物理约束名再次改写，PostgreSQL 报目标约束不存在。PostgreSQL transactional DDL 回滚了该次事务，生产表没有部分变更，原 Web 进程也未被 migration 失败重启。
3. migration 已改为以 `op.f(_CLOSE_CONSTRAINT)` 标记既有物理名称，并增加真实 PostgreSQL dialect 的离线 DDL 编译测试；修复提交即上述 `9fec9a26...`。修复后 migration `20260816_000137` 执行成功，Web 健康。
4. migration 后只读验收确认：Alembic head 为 `20260816_000137`；列精确为 `ts_code/trade_date/up_count/down_count/nine_up_turn/nine_down_turn/formula_version/published_at`；目标价格约束已删除，其余 9 个约束和索引不变；11,638,636 行、3,066 个交易日、2014-01-02～2026-08-12、owner `goldenshare_user` 与 10 条权限均未漂移。
5. D5-A 没有写 Lake 或 Dagster events，没有恢复任何 sensor。该时点 D5-B 尚未执行；后续 serving event plan/apply、认证生产 API 与浏览器验收已按第 21.6.3 节完成，因此 D5 现已整体完成。

#### 21.6.2 已纠正的执行命令与审批边界

以下部署和 migration 命令记录 D5-A 已执行口径，仅用于审计，不得因为写入本文而重复执行。GitHub→Gitee 校验必须在部署前通过；镜像不一致时最多按仓库规则重试三次（立即、30 秒后、再 30 秒后），不得在生产直接补丁：

```bash
cd /Users/congming/github/goldenshare
test "$(GIT_TERMINAL_PROMPT=0 git ls-remote https://gitee.com/chiuser/goldenshare.git refs/heads/dev-interface | cut -f1)" = "9fec9a26f09e5ff72dbd75572bf6af24f72f8410"
```

已执行的第一段无 migration 部署与独立验证为：

```bash
ssh goldenshare-prod 'sudo -n -u goldenshare /bin/bash -lc "cd /opt/goldenshare/goldenshare && bash scripts/deploy-systemd.sh dev-interface --platform-only --skip-migration --skip-build --skip-seed-default-source --skip-seed-moneyflow-multi-source --skip-sync-units --skip-realtime"'

ssh goldenshare-prod 'sudo -n -u goldenshare /bin/bash -lc "cd /opt/goldenshare/goldenshare && git rev-parse HEAD"; sudo -n systemctl is-active goldenshare-web.service; curl -fsS http://127.0.0.1:8000/api/health; printf "\n"; curl -fsS http://127.0.0.1:8000/api/v1/health; printf "\n"'
```

已执行的第二段 migration 部署为：

```bash
ssh goldenshare-prod 'sudo -n -u goldenshare /bin/bash -lc "cd /opt/goldenshare/goldenshare && bash scripts/deploy-systemd.sh dev-interface --platform-only --skip-build --skip-seed-default-source --skip-seed-moneyflow-multi-source --skip-sync-units --skip-realtime"'
```

D5-B 执行时先运行下列**只读计划**。依据 `lake_console/orchestrator/AGENTS.md`，必须从 `lake_console/orchestrator` 使用 `uv run python`；全局参数必须放在 `plan` 子命令之前。该命令读取正式 Dagster instance、3,066 个 Gold 分区，并经 `scripts/psql-remote.sh` 逐日流式读取生产表；只向 `/private/tmp` 写报告，不写 Prod、Lake 或 Dagster events。该命令已经按完整 `cwd`、`DAGSTER_HOME`、读取范围和停止条件完成审批与执行，保留如下供审计，禁止无新计划重复执行：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home \
uv run python -m orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_no_price_serving_events_cli \
  --lake-root /Volumes/datasource/data_lake \
  --output-dir /private/tmp \
  plan \
  --baseline-snapshot-report /private/tmp/stock_daily_qfq_nineturn_no_price_serving_contract_snapshot_fb10e5fbd49a84358a242f2316067cda1f77f8e5b827fcce0d5bbcc6aff6c9a2.json \
  --d4-event-plan-report /private/tmp/stock_daily_qfq_nineturn_no_price_event_plan_4d1b1e0cba85537f86b18e429a57f4bf34f2f9c034fd031441c5d7aad2838985.json \
  --d4-plan-fingerprint 4d1b1e0cba85537f86b18e429a57f4bf34f2f9c034fd031441c5d7aad2838985 \
  --deployed-revision 9fec9a26f09e5ff72dbd75572bf6af24f72f8410
```

`acb325dd...` 是 D4 写入前含 3,086 个 Gold event 候选的 apply plan；D5-B 实际绑定 D4 完成后的零候选后验计划 `4d1b1e0c...`，没有混用。只读计划生成 `should_stop=false` 并经人工审核后，另行获得 apply 批准；实际执行命令固定为：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home \
uv run python -m orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_no_price_serving_events_cli \
  --lake-root /Volumes/datasource/data_lake \
  --output-dir /private/tmp \
  apply \
  --plan-report /private/tmp/stock_daily_qfq_nineturn_no_price_serving_event_plan_575672fb90baac73d596962d0152fcd0d79f804efdb9f990b30e7cdf15fa48b9.json \
  --plan-fingerprint 575672fb90baac73d596962d0152fcd0d79f804efdb9f990b30e7cdf15fa48b9 \
  --apply
```

`plan` 的批准没有自动授权 `apply`；本次 `apply` 在第二次明确批准后才执行，并重新生成、核对同指纹 fresh plan 后向正式 Dagster instance 追加 events。任何未来重跑仍必须重新生成计划并单独批准；本文中的已执行命令不能当作持续授权。

#### 21.6.3 D5-B 完成事实与 D6 边界（2026-08-17）

1. 只读计划报告为 `/private/tmp/stock_daily_qfq_nineturn_no_price_serving_event_plan_575672fb90baac73d596962d0152fcd0d79f804efdb9f990b30e7cdf15fa48b9.json`，fingerprint 为 `575672fb90baac73d596962d0152fcd0d79f804efdb9f990b30e7cdf15fa48b9`。计划冻结 3,066 个正式分区、11,638,636 行、3,066 个 serving materialization 与最近 20 日 20 个 blocking-check 候选；`should_stop=false`、`stop_reasons=[]`。两个日线 writer 均为 `STOPPED`，关联 job 活跃 run 为 0；计划阶段 Lake/Prod/Dagster event 写入均为 0。
2. apply 报告为 `/private/tmp/stock_daily_qfq_nineturn_no_price_serving_event_apply_575672fb90baac73d596962d0152fcd0d79f804efdb9f990b30e7cdf15fa48b9.json`，batch id 为 `ecd61144-a0d2-4f78-96a5-3a41a08e4da3`。正式实例精确追加 3,066 条 `stock_daily_qfq_nineturn_serving_v2_no_price` materialization 与 20 条当前 revision blocking-check event；自动 post-plan 候选为 0，当前 revision 计数为 3,066/20。apply 未写 Lake/Prod，未启动 job/sensor，未删除历史 event。
3. 认证请求链路由生产真实页面证明：`603806.SH` 页面请求日线九转接口返回 HTTP 200、27,912 bytes；无登录日线路由返回 401，生产股票/指数分钟九转路由返回 404。
4. 当前生产代码连接远程数据库并在 `BEGIN READ ONLY` 中执行 DTO：第一页 `limit=45` 为 `PARTIAL`，`source/matched/missing/marker=45/43/2/40`，第二页为 `45/45/0/43`，两页日期严格不重叠；marker 序号覆盖且仅为 1～9，递归检查响应无 `close_qfq`。
5. 两根缺失是 2026-08-13、2026-08-14；日线九转观察截止 2026-08-12。维护窗口内两个 writer 仍停止，因此该差异进入既有局部 `PARTIAL` 合同并留给 D6 自然恢复，不得在 D5-B 擅自启动 sensor。
6. 后端 API/Reader 回归 24 passed，前端 adapter/registry/status/shared primitive 回归 26 passed。重新建立独立浏览器验收页后，生产 `603806.SH` 截图确认日 K 线和九转 1～9 标记同时可见；“九转与 K 线有 2 个时间键未对齐。”按局部 `PARTIAL` 合同显示，MACD、成交量、KDJ、右栏和页面骨架仍正常展示；生产分钟周期保持置灰，无新增裁剪、重叠或横向溢出，控制台 `error/warn` 均为 0。D5-B 视觉门禁据此通过，D5 整体完成；D6 sensor/freshness 未执行、未获本次验收授权。

#### 21.6.4 D6-0 启用前代码门禁与后续执行顺序（2026-08-17）

启用前代码审计发现，日线九转 Gold sensor 仍调用历史 QFQ factor-repair plan/status，并可因相邻交易日复权因子变化阻断新增九转分区。这与本节 C21 和第 21.7 节冻结合同冲突，必须先于任何正式状态变更修正。

D6-0 已实施以下唯一代码变化：

1. `gold_stock_daily_qfq_nineturn_update_job_sensor` 不再 import、读取或调用 `stock_daily_qfq_factor_repair`、`silver_adj_factor_path`、`GoldStockDailyQfqFactorRepairPlan`、`build_gold_stock_daily_qfq_factor_repair_plan`。
2. 删除 factor-repair plan/status 阻断分支，以及 cursor 中的 `factor_repair` gate、`repair_required` 和 `repair_required_code_count`；sensor description 同步为“日线前复权行情和上一九转分区就绪”。
3. 保留 10 日 expected window、动态分区缺口、first-not-ready、目标 blocking check、同日 `gold_stock_daily_qfq` readiness、上一九转分区 readiness、每 tick 最多一个请求、原 run key、600 秒最小间隔和默认 `STOPPED`。
4. 测试新增源码级负向门禁，旧 factor-repair 测试和 fixture 清零；上游未 ready 仍在上一分区查询前阻断，上游与上一分区就绪时只提交一个请求，cursor 继续小于 2 KiB。定向测试共 22 passed。
5. CodeGraph 影响面仅为该 Gold sensor 及其测试；serving run-status sensor、资产、check、job、schema、路径、分区、API 和前端均不变。热路径减少两份复权因子文件读取和一次可选 repair 状态查询。

D6 后续严格拆分，任一批准不授权下一步：

1. D6-1 正式只读计划：使用正式 `DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`，核对当前 definitions revision、两个日线 writer 实时状态、关联活跃 run、最近 Gold/serving materialization/check、动态分区和待补交易日；只向 `/private/tmp` 写带指纹报告。
2. D6-2 definitions reload 与 sensor 恢复：先 reload 并确认正式 code location 已加载 D6-0 代码，再先恢复 `prod_core_stock_daily_qfq_nineturn_sync_job_sensor`，最后恢复 `gold_stock_daily_qfq_nineturn_update_job_sensor`。禁止 `--start-all`，禁止同时启动其它 sensor。
3. D6-3 自然链路验收：观察 first-not-ready 对 2026-08-13 起缺口逐日生成 Gold，Gold blocking check 通过后由 serving sensor 发布；每次最多一个交易日，不手工补造 run。验收 Lake 六列、serving 八列、event/readiness、API `PARTIAL→READY` 和页面 marker；任一失败立即停止两个 writer 并保留现场。

D6-0 只改本地代码、测试和文档，没有访问正式 Dagster instance、reload definitions、启动 sensor 或写 Lake/Prod/events。D6-1 必须在完整命令、`cwd`、读取范围、输出路径和停止条件审核后单独执行。

D6-1 使用下列冻结只读命令执行；本命令保留为审计证据，禁止据此推导 D6-2 写入授权：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
set -euo pipefail
d6_audit_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
d6_audit_report="/private/tmp/stock_daily_qfq_nineturn_d6_readonly_${d6_audit_stamp}.log"
{
  git -C /Users/congming/github/goldenshare rev-parse HEAD
  git -C /Users/congming/github/goldenshare status --short -- \
    lake_console/orchestrator/src/orchestrator/defs/sensors/stock_daily_qfq_nineturn_sensor.py \
    lake_console/orchestrator/tests/test_stock_daily_qfq_nineturn_sensor.py \
    wealth/docs/system/detail-page-nine-turn-integration-implementation-design-v1.md \
    wealth/docs/system/detail-page-nine-turn-integration-low-level-design-v1.md
  shasum -a 256 \
    src/orchestrator/defs/sensors/stock_daily_qfq_nineturn_sensor.py
  DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home \
    uv run dg check defs
  DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home \
    uv run python - <<'PY'
import json

import dagster as dg

sensor_names = (
    "prod_core_stock_daily_qfq_nineturn_sync_job_sensor",
    "gold_stock_daily_qfq_nineturn_update_job_sensor",
)
job_names = (
    "prod_core_stock_daily_qfq_nineturn_sync_job",
    "gold_stock_daily_qfq_nineturn_update_job",
)
in_flight = (
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
)
with dg.DagsterInstance.get() as instance:
    states = {name: [] for name in sensor_names}
    for state in instance.all_instigator_state():
        name = getattr(state, "name", None) or getattr(
            state, "instigator_name", None
        )
        if name not in states:
            continue
        data = getattr(state, "instigator_data", None)
        states[str(name)].append(
            {
                "status": str(
                    getattr(getattr(state, "status", None), "value", "UNKNOWN")
                ),
                "origin_id": str(
                    getattr(state, "instigator_origin_id", "") or ""
                ),
                "selector_id": str(getattr(state, "selector_id", "") or ""),
                "last_tick_timestamp": getattr(data, "last_tick_timestamp", None),
                "cursor_bytes": len(
                    str(getattr(data, "cursor", "") or "").encode("utf-8")
                ),
            }
        )
    active_runs = {
        job_name: instance.get_runs_count(
            filters=dg.RunsFilter(job_name=job_name, statuses=list(in_flight))
        )
        for job_name in job_names
    }
    trade_dates = tuple(
        sorted(instance.get_dynamic_partitions("cn_a_stock_trade_days"))
    )

payload = {
    "sensor_states": states,
    "active_run_counts": active_runs,
    "registered_trade_date_count": len(trade_dates),
    "registered_trade_date_tail": list(trade_dates[-12:]),
}
print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
for sensor_name, matches in states.items():
    if len(matches) != 1 or matches[0]["status"] != "STOPPED":
        raise SystemExit(f"STOP: unexpected sensor state for {sensor_name}")
if any(active_runs.values()):
    raise SystemExit("STOP: stock daily nine-turn writer run is in flight")
PY
  DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home \
    uv run dagster sensor list -m orchestrator.definitions
  DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home \
    uv run dagster sensor preview \
      gold_stock_daily_qfq_nineturn_update_job_sensor \
      -m orchestrator.definitions
} 2>&1 | tee "${d6_audit_report}"
shasum -a 256 "${d6_audit_report}"
```

读取范围仅包括当前工作区 revision/目标文件状态、正式 Dagster definitions/instigator/run/dynamic-partition/event 状态，以及 Gold sensor preview 所需的正式 Lake 最近 10 日文件；写入仅为 `/private/tmp` 的日志报告。`sensor preview` 不登记 tick、不提交 run、不修改 cursor。以下任一情况立即停止 D6-1：Definitions 加载失败；同名 sensor 状态不是唯一 `STOPPED`；任一目标 job 存在活跃 run；preview 不是预期的单个 first-not-ready 日期；源码 SHA 或目标文件状态与审核基线不一致。D6-1 的通过不授权 `sensor start`。

D6-1 于 2026-08-17 完成，正式结果如下：

1. 主报告为 `/private/tmp/stock_daily_qfq_nineturn_d6_readonly_20260817T125215Z.log`，SHA-256 为 `2b822f358a877a2c7d6b18225517eade9558b62f3849f794edbcef7f00f57297`。审计时仓库 HEAD 为 `874f647b6a42e707d30f64f1d7038920b9117448`，D6-0 sensor 源码 SHA-256 为 `1b0add0ee85d9c87c197249687f135098ad6db56ba0e5c485b9c090b0b905bd7`；目标代码、测试和两份文档仍是待提交修改，未把工作区状态伪装成已提交 revision。
2. `dg check defs` 全部通过；两个目标 sensor 各只有一个持久化 state 且均为 `STOPPED`，两个关联 job 的 `QUEUED/STARTING/STARTED/CANCELING` run 数均为 0。`cn_a_stock_trade_days` 共 3,069 个分区，尾部已登记到 `2026-08-17`。
3. Dagster CLI preview 只显示“1 个 run request”和空 run config `{}`，没有输出 partition key，不能单独满足 first-not-ready 取证。因此增加同范围、无 tick/无 cursor 持久化的结构化 `_raw_fn` 只读评估；报告为 `/private/tmp/stock_daily_qfq_nineturn_d6_preview_detail_20260817T125411Z.json`，SHA-256 为 `d00388055541d1cd3ecac5cc07d3f769a18c16b4552d9d06d869ef5250b5f251`。
4. 结构化结果精确返回一个请求：partition `2026-08-13`，run key `gold_stock_daily_qfq_nineturn_update:2026-08-13`，cursor decision `request_runs`。最近 10 日窗口为 `2026-08-04～2026-08-17`，目标 readiness 批量查询耗时约 33.55ms；同日 `gold_stock_daily_qfq` ready，上一分区 `2026-08-12` 的 Gold 九转和 serving materialization/check 均 ready，`2026-08-13` 两层均尚无 materialization。
5. 结构化评估前后两个 sensor 的 status/origin/selector/tick/cursor 完全一致，两个 job 在途数仍为 0；没有写 Lake、Prod、Dagster event、tick、cursor 或 run。当前 `dg dev`/active code location 于 D6-0 sensor 文件修改之后启动，已加载当前源码。D6-1 据此通过；D6-2 仍必须使用 active workspace origin，按 serving→Gold 顺序逐个启动，禁止通过新的 `-m` 临时 origin 启动或使用 `--start-all`。

D6-2 启动前规模与停止门禁已经只读测量：当前缺口精确为 `2026-08-13`、`2026-08-14`、`2026-08-17` 三个已登记交易日；同日 `gold_stock_daily_qfq` 源文件均存在，行数分别为 5,540、5,540、5,539，合计 16,619 行，三个源文件合计约 0.87MB；三个日线九转目标文件均不存在。自然链路预计逐日生成 3 个六列 Parquet、3 组 Gold materialization/check、3 个 serving PostgreSQL 分区及 3 组 serving materialization/check。每个 Gold tick 最多处理一个日期，最小间隔 600 秒；单次只扫描目标、上一分区和同日 QFQ 小文件，使用中央 DuckDB 连接和 staging 校验后原子替换，不进入历史全量扫描。任一日期源文件缺失、输出行数不等于同日源键数、出现重复/空键、check 失败、同名 state 重复、单 job 多于一个在途 run或非目标 sensor 状态变化，均立即停止两个 writer 并保留现场。

D6-2 与 D6-3 正式执行结果如下：

1. D6-2 按冻结顺序先启动 `prod_core_stock_daily_qfq_nineturn_sync_job_sensor`，再启动 `gold_stock_daily_qfq_nineturn_update_job_sensor`；两者继续绑定 active workspace 的唯一 origin/selector，分别为 `45cf93f39b0c6d98520f9833a898d550b4436419 / e7540ba0ce20e12685df5602e25ff75ed4c93cfe` 和 `f374f85f34bc4a1f7168d4371952ca4e38a5f90a / 63419d07f713bcc9dca7aae7a3b2a5529c4e7ad9`。正式实例终验时两者均为唯一 `RUNNING`，两个目标 job 在途 run 为 0；代码定义的 `default_status=STOPPED` 不能替代实例持久化运行态。
2. 自然链路没有手工补造 run。Gold 三个 run 分别为 `9cf3ed0d-c30d-42d0-b6b9-5d72d7480e2e`、`3ad7f3a0-e77b-41f6-8bed-c463233a9b9a`、`a995e12a-090c-4bd6-8941-15a10f674063`；serving 三个 run 分别为 `6c938bc5-9802-4462-a502-3103d8997c06`、`aeb5e536-5dca-40c5-b184-fe1ea65f9f82`、`f1f19127-ea49-42ae-a548-3116600fa2de`。六个 run 均为 `SUCCESS`，分区依次且仅为 `2026-08-13`、`2026-08-14`、`2026-08-17`，监控未触发源缺失、check 失败、重复 state、多在途 run 或意外分区停止条件。
3. 三份正式 Lake 文件 schema 精确为 `ts_code/trade_date/up_count/down_count/nine_up_turn/nine_down_turn` 六列，行数为 5,540/5,540/5,539；逐日正式 integrity audit 的源重复键、目标重复键、空键、非法值、缺源键和多余键全部为 0。Gold materialization storage id 为 `7249809/7249865/7249959`，serving 为 `7249837/7249893/7249987`；六组对应 blocking check 均通过并返回 `ready`。
4. 生产 `core_serving.equity_qfq_nineturn_daily` 只读验收为八列无价格合同；三日行数同为 5,540/5,540/5,539，重复 `ts_code` 为 0，`formula_version` 最小/最大均为 1，`published_at` 空值为 0。生产页面在 21:34:12 对 `/api/v1/wealth/market/stock-detail/nine-turn?tsCode=603806.SH&endDate=2026-08-17&limit=300` 的真实认证请求返回 HTTP 200、28,209 bytes。
5. 21:34 的首次 `PARTIAL→READY` 页面退出条件未通过，但原因不是九转缺键：按 API 完全相同的 300 根窗口只读对账，`source/matched/missing=300/300/0`、版本固定为 1，窗口实际末日和九转观测末日均为 `2026-08-14`。页面期望日是 `2026-08-17`；当时 `core_serving.equity_factor_pro` 最大交易日为 `2026-08-14`，所以 response policy 正确返回 `DELAYED / NT_SOURCE_NOT_READY`。后续时间线证明这不是独立 freshness 故障：18:30 和 21:02 的两个收盘维护任务虽已触发，但分别到 22:43、22:52 才实际开始，`stk_factor_pro` 节点在 22:45、22:54 成功完成。
6. 22:54 后生产 `core_serving.equity_factor_pro` 已有 `2026-08-17` 共 5,538 行。真实登录页 `603806.SH` 复验不再出现 DELAYED、时间键未对齐或九转错误提示，日线 K 线与九转 1～9 标记正常共存，无横向溢出，控制台 warning/error 为 0。因此 D6-3 READY 视觉门禁通过，D6 整体完成；本次没有补写上游、修改 `expectedEndDate` 或放松状态判定。

生产回滚采用前向修复：停止 writer/reader，修正 migration 或代码后继续完成无价格合同。不得重新引入 `close_qfq`、兼容表或 Tushare fallback；价格事实始终从 `gold_stock_daily_qfq` 获取。

### 21.7 测试与验收矩阵

代码阶段：

1. 日线 Gold schema 精确为六列且不含 `close_qfq`；四个分钟 schema 仍为八列；指数日线 schema 仍含自己的 `close`。
2. 日线 writer 输入含 QFQ `close`、正式输出无价格；全历史、增量、fallback、seed 与 golden 的计数/信号不变。
3. 日线 check 接受六列、拒绝旧七列；继续拒绝缺文件、空文件、错误分区、重复/空键、源键不全和非法计数/信号。
4. 历史列投影路径不调用共享公式内核；candidate 与旧正式文件的键、计数和信号完全一致。
5. factor repair、价格值差异和 QFQ price file 身份变化不会生成九转 repair 计划或 RunRequest；源码静态门禁禁止日线九转 Gold sensor 再引用 repair 类型、状态、计划或复权因子路径。
6. catalog、definition metadata、observed columns、readiness 和 event helper 全部消费六列合同。
7. prod publisher、DB helper、content hash、checkpoint audit、ORM 和 Biz query 均不出现 `close_qfq`。
8. migration 删除目标约束/列并保留其它约束、索引、权限和行；`down_revision` 精确连接实施时真实 head。
9. 股票日线 API 的 marker、latestMarker、分页、Partial/Empty/Delayed、5MB 和认证回归不变；页面不修改。

正式执行退出条件：

1. 正式 Lake 旧七列文件为 0，所有目标文件为六列；文件数、日期、行数、键、计数和信号与冻结计划一致。
2. materialization/check event 实际数与 event plan 一致，latest state 和最近 20 日 readiness 通过。
3. 生产表不含 `close_qfq` 和 `close_positive`，无历史 delete/reinsert；全历史行数、键、计数、信号和 formulaVersion 不变。
4. 日线 Gold 与 serving sensor 恢复后只处理新增交易日，不因前复权历史价格重算发起 repair。
5. 生产日线 API 和页面 marker 正常，分钟和指数九转没有回归。

### 21.8 性能、安全和审批门禁

| 项目 | 当前基线/目标 | 停止条件 |
|---|---|---|
| 正式文件 | 全绿 D2 已冻结 3,066 个、158,269,066 bytes；与停写前文件身份集合完全一致 | 文件/日期集合无法冻结或出现额外目标 |
| 正式行数 | D2 已聚合 11,638,636；candidate 必须完全一致 | candidate 与旧正式总行数不一致 |
| 计算方式 | 仅六列投影，无公式重算、无 QFQ join | 迁移路径调用公式或扫描价格事实 |
| 批次 | 按年度串行，单连接单年度 | 单批超过 5 分钟或出现无界扫描 |
| DuckDB | `memory_limit=2GB`、`threads=1` | 进程峰值 RSS 超过 16GiB |
| staging | 只用 `/Volumes/datasource/data_lake_staging` | 空间不足或路径落入正式 Lake |
| 提升 | 候选全绿后逐文件 `os.replace()` + checkpoint | 任一 hash/schema/键/计数/信号差异 |
| 生产 DDL | 删除一列和一个约束，保留全部行 | head、约束、权限或维护窗口未确认 |
| 生产发布 | 不全量 reinsert，只做 DDL 后聚合验收 | 行数、键、计数、信号或版本漂移 |

审批拆分：

1. D0：本节 LLD 冻结，仅文档修改。
2. D1：代码、migration 文件和隔离测试；不触碰正式 Lake、Dagster instance 或生产数据库。
3. D2：正式只读 Lake/event/Prod 计划；只读，不写入。
4. D3：staging candidate、审计和正式 Lake 原子提升。
5. D4：Dagster Gold event recovery。
6. D5：D5-A 生产 maintenance、migration 与代码部署，及 D5-B serving event recovery、认证请求/DTO 与生产页面视觉验收均已完成。
7. D6：D6-0 本地启用前合同修正、D6-1 正式只读计划、D6-2 active workspace serving→Gold sensor 恢复和 D6-3 自然日/READY 页面验收均已完成；21:34 的 DELAYED 仅记录为上游当日任务尚未实际执行的正常等待。

任一阶段的批准不自动授权下一阶段；当前 D0～D6 已完成。两个日线 writer 已是 active workspace 的唯一 `RUNNING` state，三个缺口交易日已由自然链路生成并发布，READY 页面复验通过。此次收口没有授权或执行任何 `equity_factor_pro` 修复、回补或状态口径调整。

## 22. 版本记录

下表记录各版本发布当时的阶段事实，较早版本中的“待执行/未授权”可能已在后续版本完成；当前状态只以文首状态、第 4.5 节和第 15 节最新执行结果为准。

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-08-13 | 完成 M0 收口、CodeGraph/current code 审计、物理 freq 复核，冻结资产、serving、DTO、Reader、前端与验收设计 | Codex |
| v1.1 | 2026-08-13 | 同步 M2 实现事实、真实 Lake 四频率只读验收、生产权限边界及未执行 migration/历史发布/浏览器验收项 | Codex |
| v1.2 | 2026-08-13 | 收口 M3-A/M3-B：生产空表和 close 漂移事实、独立 staging、20 日批次 checkpoint、serving blocking check 与 STOPPED 日常链路 | Codex |
| v1.3 | 2026-08-13 | 同步 Gold 修复完成、serving 893 日部分发布、内存暂停与 256MB/1线程/10批次恢复门禁 | Codex |
| v1.4 | 2026-08-13 | 同步 serving 1,113 日检查点；收口 plan/resume/CLI 内存与输出放大根因，冻结 128MB、聚合 plan、源元数据核对、Prod 流式 hash 和逐 batch 摘要门禁 | Codex |
| v1.5 | 2026-08-13 | M3-B 完成：以十个有界短进程发布余下 1,953 日，生产表 3,066 日、11,638,636 行逐日对账通过，峰值 RSS 最高约 249MiB；M3-C 与自然日常链路仍待验收 | Codex |
| v1.6 | 2026-08-13 | M3-C 生产日线主体门禁通过：登录态 API、真实 300 行样本和 1600×1200 Loaded 视觉已验收；正式 P95、45/180 根生产边界截图与分钟验收继续待完成 | Codex |
| v1.7 | 2026-08-14 | 冻结所有分钟业务事实统一读取规范化 Gold；将指数分钟九转依赖改为同频 `gold_major_index_mins_*`，并增加禁止直接消费 Silver 的 C17 门禁 | Codex |
| v1.8 | 2026-08-14 | 增加十四个分钟 K 线 Gold asset key 白名单、物理根和支持频率边界，并冻结针对 Silver asset key 的负向静态门禁 | Codex |
| v1.9 | 2026-08-14 | 完成 M4-A：提取唯一规范化九转 SQL 内核，股票全历史、分区与年度批次改为薄适配器，并以受保护 golden、逐行对账和禁止公式复制的静态门禁证明结果无漂移 | Codex |
| v1.10 | 2026-08-14 | M3-C-Minute 收口：四资产/check/物理覆盖、逐键对齐、严格接口、P95、Reader 复用连接内存门禁、缓存/禁用周期和 1600×1200 浏览器验收通过 | Codex |
| v1.11 | 2026-08-15 | M4-B 编码收口：实现指数日线与六分钟九转的 7 assets/checks、jobs/sensors/readiness、有界历史构建、日线 serving/API 和本地分钟 API；登记源身份与 checkpoint 回验门禁，并明确正式历史、migration、serving 发布仍未获执行授权 | Codex |
| v1.12 | 2026-08-15 | M4-B 正式执行收口：生成并全量对账 32,124 个分区，登记 64,248 条 Dagster events，执行生产 migration，发布 6,450 日/42,633 行日线 serving，完成产品边界、全量 hash、日线 API 和六分钟 Reader 性能验收；三个指数 sensor 当时未启用 | Codex |
| v1.13 | 2026-08-15 | 冻结股票分钟 QFQ 九转去价格字段专项：四个分钟资产改为八列无价格合同，日线完全隔离；细化 writer/check/Reader/bootstrap、12,268 文件 staging 原子替换、全量 materialization/最近 20 日 check event 恢复与分阶段审批门禁。本版本只改文档，未进入代码或正式执行 | Codex |
| v1.14 | 2026-08-15 | 文档漂移收口：重新确认 M4-B 正式物理/事件/生产完成事实；区分 sensor 定义默认值与实例持久化状态，登记三个股票 sensor 实际 RUNNING/最近 tick 均 SKIPPED、三个指数 sensor 实际沿用默认 STOPPED，并清除“当前仍全部停止”的错误表述 | Codex |
| v1.15 | 2026-08-15 | 去价格专项 S1 收口：分钟 schema/writer/check/history/Reader 切换为八列无价格合同，日线价格与 serving 合同不变；增加旧 schema、源重复键、值域、内存/线程和文档指纹门禁。代码与专项回归通过，正式 Lake/events 仍待 S2～S5 | Codex |
| v1.16 | 2026-08-15 | 去价格专项 S2～S5 收口：12,272 个正式分钟分区切换为八列合同，登记 12,272 materialization/80 check，完成 Reader/readiness/性能与 sensor 自然评估；日线与 Prod 不变 | Codex |
| v1.17 | 2026-08-15 | S6 只读复核确认日线 20 个代码的 50,283 个既有价格值漂移、计数和信号零差异；按用户决定将日线价格信息及自然链路阻塞移交后续专项，本轮仅继续 M3-C 前端 marker API 性能与 45/180 根视觉验收 | Codex |
| v1.18 | 2026-08-15 | 用户取消登录态正式 P95 与生产 45/180 根截图两项 M3-C 补充验收，M3-C 收口；冻结 S7/M5 指数 capability、共享图层、Technical 摘要、局部状态与并发缓存门禁 | Codex |
| v1.19 | 2026-08-15 | S7/M5 当时按 day/60/30 三行摘要收口；该历史基线后续由 v1.25 的固定六周期摘要合同替代，其余 page-init capability、共享九转图层、局部状态与缓存竞态结论保持 | Codex |
| v1.20 | 2026-08-15 | 进度收口：确认 M0～M5 完成、M6 尚未开始；新增 M6-0～M6-D 文件级执行门禁，区分本地提交、推送部署、sensor 只读计划与启用审批，并把 sensor 状态标记为非实时快照 | Codex |
| v1.21 | 2026-08-15 | M6-0 发布准备审计完成并通过：记录六提交/54 文件范围、生产路由配置、全部定向门禁、platform-only 命令及 M5 定向回滚；修复板块测试异步等待竞态后专项 36/36、Wealth 232/232 与 typecheck 通过 | Codex |
| v1.22 | 2026-08-15 | M6-A 完成：六个评审提交推送并以 platform-only 路径部署到生产 `58fb5b62`；复核版本、服务、health、日线 401/分钟 404，并通过上证日线双 primitive、Technical 摘要、生产周期禁用和控制台浏览器验收 | Codex |
| v1.23 | 2026-08-15 | M6-B 第一段只读计划收口：核验 active workspace、三个 STOPPED sensor、八个 RUNNING 上游、最新 7 个 Gold 分区/check、生产 serving、run key/cursor 和单 tick 性能；冻结启用顺序、失败停止/恢复及启用前 sensor 决策测试门禁，未启动 sensor | Codex |
| v1.24 | 2026-08-15 | M6-B 启用前隔离测试收口：新增 18 项日线/分钟 Gold 与 serving sensor 决策测试，相关回归合计 64 passed、35 subtests passed；未修改生产 sensor 口径，三个指数 sensor 仍为 STOPPED | Codex |
| v1.25 | 2026-08-16 | 指数 Technical 固定六周期摘要完成本地开发：Figma `414:417`、`633:545`、`634:558` 与前端单一周期合同、预取、右栏渲染、CSS 和测试已同步；Wealth 232 tests、typecheck、build、上证真实六周期与北证50缺值本地浏览器验收通过，不改 API/DTO/Gold/Lake/Dagster，尚未发布生产 | Codex |
| v1.26 | 2026-08-16 | 冻结股票日线 QFQ 九转去价格专项 LLD：Gold 改为六列、serving 改为八列；价格仅作计算输入，历史只做列投影且前复权重算不触发 repair；细化代码消费者清零、staging 原子迁移、events、生产 DDL/部署、16GiB 门禁和 D0～D6 分阶段审批。本版本仅完成文档合同同步，未进入代码或正式执行 | Codex |
| v1.27 | 2026-08-16 | 股票日线去价格 D1 编码完成：Gold/serving/ORM/query/check 切换无价格合同，新增年度列投影工具、CLI 和前向 Alembic migration 文件；Definitions、94 项 Orchestrator 与 35 项 API/Reader 回归通过。未触碰正式 Lake、Dagster instance 或生产数据库，D2～D6 仍待审批 | Codex |
| v1.28 | 2026-08-16 | 股票日线去价格 D2 只读计划完成：冻结 3,066 文件/11,638,636 行及 3,086 条 Gold event 规模，确认生产 9 列旧表、真实 Alembic head 和 3,086 条 serving event 规模；两个日线 writer 均为 RUNNING，计划 `should_stop=true`，未发生任何正式写入，D3 被门禁阻止 | Codex |
| v1.29 | 2026-08-16 | 经批准停止 active workspace 中两个日线 writer，确认关联 job 无在途 run；重新生成 `should_stop=false` 的 D2 Lake 计划 `9f8835a3...`，3,066 文件/11,638,636 行及文件身份均未漂移。未生成 candidate、未写 Lake/events/Prod、未执行 migration/部署；D3 前置门禁已满足但仍待独立批准 | Codex |
| v1.30 | 2026-08-16 | 股票日线去价格 D3 完成：3 个样本与 3,066 个全量 candidate 审计全绿，原子提升正式 Lake 并完成六列物理终验；11,638,636 行、hash 差异 0、candidate 残留 0、旧七列混存 0。两个 writer 与本地 Reader 保持关闭，未写 Dagster events/Prod，D4～D6 仍待独立批准 | Codex |
| v1.31 | 2026-08-16 | 股票日线去价格 D4 编码门禁完成：新增绑定 D3 plan、candidate/formal audit、正式文件 SHA 和实例状态的专用 event helper/CLI；唯一 writer、fresh-plan、revision 续跑和最近20日 check 已通过隔离测试。尚未访问正式 Dagster instance 或写正式 events，D4 正式计划/执行仍待命令级批准 | Codex |
| v1.32 | 2026-08-16 | 股票日线去价格 D4 正式完成：核验并停止唯一 Gold writer 持久化状态，按全绿计划 `acb325dd...` 向正式 Dagster instance 追加 3,066 条新版 materialization 和最近 20 日 20 条 blocking-check event；post-plan 候选 0、两个日线 writer 保持 STOPPED，未写 Lake 或 Prod。D5～D6 仍待独立批准 | Codex |
| v1.33 | 2026-08-16 | 股票日线去价格 D5-A 收口并纠正后续命令：生产已部署 `9fec9a26...`，migration `20260816_000137` 已删除价格列与目标约束，11,638,636 行/3,066 日及索引、owner、权限只读验收无漂移；记录首次 DDL 名称错误的事务回滚与 `op.f(...)` 修复。D5-B 正式计划统一改为 orchestrator 目录下 `uv run python`，绑定 D4 零候选后验计划 `4d1b1e0c...` 和实际部署 SHA；plan/apply 继续分开审批 | Codex |
| v1.34 | 2026-08-17 | 股票日线去价格 D5-B 数据/API 门禁收口：全绿 plan `575672fb...` 经批准追加 3,066 条 serving materialization 与 20 条 blocking-check event，batch `ecd61144...`，post-plan 候选 0；生产登录页真实请求 200、未登录日线 401、分钟 404，远程只读 DTO 分页/marker/无价格合同通过。当前因两个日线 writer 仍停止而缺 2026-08-13/14，返回局部 `PARTIAL`；独立生产页面 DOM/视觉复核和 D6 sensor 恢复仍待完成 | Codex |
| v1.35 | 2026-08-17 | 股票日线去价格 D5 完整收口：生产 `603806.SH` 页面确认日 K、九转 1～9、局部 `PARTIAL` 提示及其他图表/右栏可同时正常显示，生产分钟周期继续置灰，无新增裁剪、重叠、横向溢出或控制台 error/warn。D6 sensor 恢复仍未授权 | Codex |
| v1.36 | 2026-08-17 | D6-0 启用前合同修正完成：删除日线九转 Gold sensor 的 factor-repair plan/status、复权因子路径、阻断与 cursor 依赖；同日 QFQ、上一九转分区、first-not-ready、单请求和小 cursor 门禁保持不变，22 项定向回归通过。冻结 D6-1 只读计划、D6-2 serving→Gold 恢复顺序和 D6-3 自然日验收；尚未访问正式实例 | Codex |
| v1.37 | 2026-08-17 | D6-1 正式只读计划完成：Definitions 通过，两个日线 writer 唯一且 STOPPED、两个 job 零在途，3,069 个交易日分区登记到 2026-08-17；结构化无副作用评估确认 first-not-ready 为 2026-08-13、上一 Gold/serving 分区 ready，报告前后实例状态不变。D6-2 sensor 恢复仍待独立批准 | Codex |
| v1.38 | 2026-08-17 | D6-2 正式完成并收口 D6-3 边界：serving→Gold 两个 writer 已恢复为唯一 RUNNING，三日六个自然 run 全部 SUCCESS；16,619 行 Lake/Prod、六列/八列合同和六组 readiness/check 全绿，生产认证请求 200。READY 页面仍因 `equity_factor_pro` 全表最大交易日停在 2026-08-14 而返回 DELAYED；300 根窗口九转 300/300 对齐、缺键为 0，禁止把上游 freshness 问题误报为九转缺失或 D6 完成 | Codex |
| v1.39 | 2026-08-17 | 纠正 D6-3 时间口径并同步实时进度：21:34 的 DELAYED 发生在当日收盘维护任务实际执行前，不是 freshness 故障；22:54 后 `equity_factor_pro` 已覆盖 2026-08-17 共 5,538 行，生产 `603806.SH` READY 页面复验通过，股票日线去价格 D6 完成。三个指数 sensor 均为唯一 RUNNING，2026-08-17 日线、六分钟与 serving 自然 run 全部 SUCCESS，M6-B/M6-C 完成；只剩 M6-D 最终验收 | Codex |
