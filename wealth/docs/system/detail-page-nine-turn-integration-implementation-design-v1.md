# 股票与主要指数详情页九转接入总方案 v1

> 状态：M0～M5 已完成；M6-0 发布准备审计与测试稳定性修复已于 2026-08-15 完成并通过，M6-A 尚未开始。2026-08-15 用户取消登录态正式 P95 与生产 45/180 根缩放边界截图两项 M3-C 补充验收，已通过的接口、权限、真实数据、Loaded 视觉以及完整分钟验收共同构成 M3-C 最终结论。股票分钟 QFQ 九转去价格 S0～S5 已完成；S6 发现的股票日线冗余价格漂移和自然更新阻塞已移交独立专项，不属于页面退出条件。本地 `dev-interface` 的前五个运行/文档提交与本轮 M6-0 收口提交均尚未推送或部署；M6-A 仍须用户另行明确批准。六个九转 sensor 的最近一次实例快照见第 3.3 节。
>
> 评审基线日期：2026-08-13。
>
> 分钟事实源口径修订日期：2026-08-14。
>
> 正式设计文件：[Goldenshare Web](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?m=dev)。
>
> 低层设计：[股票与主要指数详情页九转接入低层设计 v1](./detail-page-nine-turn-integration-low-level-design-v1.md)。

---

## 1. 目的与结论

本方案统一治理股票与主要指数详情页的日线、分钟线九转数据、接口、共享图表和页面状态，为后续 LLD 提供唯一上游合同。

最终结论：

1. 股票支持日线、30、60、90、120 分钟九转；股票 1、5、15 分钟不提供九转。
2. 主要指数支持日线、5、15、30、60、90、120 分钟九转；指数 1 分钟不提供九转。
3. 股票只使用自主计算的前复权 Gold 九转，不能用 Tushare `stk_nineturn` 或现有 `core_serving.equity_nineturn` 静默替代。
4. 指数只支持 `majorIndices/CN_A` 配置中的 10 个主要指数。`000680.SH` 即使存在 Lake 数据也不得进入页面。
5. 后端输出已经归一的可展示 marker；前端只绘制，不重新计算九转。
6. 股票、指数、日线、分钟线统一复用一个 `NineTurnMarkerPrimitive` 和现有 `DetailChartWorkspace`，不复制图表引擎。
7. 九转是客观序列标记，不生成机会、买卖、风险评级、仓位或交易计划动作。
8. 股票与指数九转 Gold/API 及详情页消费均已完成；后续 M6 只负责日常自动化、freshness 与最终发布验收。
9. 所有分钟 K 线的业务消费和下游指标计算统一使用规范化 Gold：股票使用 `gold/quote/stk_mins_qfq`，主要指数使用 `gold/quote/major_index_mins`；Silver 只属于 Gold 之前的数据生产链，Web、九转 Reader 和九转资产不得直接消费 Silver 分钟线。
10. 股票日线九转继续保存 `close_qfq` 并维持现有 Lake/Prod/查询/事件合同；四个股票分钟九转资产最终只保存业务键、计数和信号，不保存价格或量额。分钟公式仍从同频 `gold_stk_mins_qfq.close` 读取价格输入。

### 1.1 分钟 K 线 Gold 数据集完整清单

股票详情页及股票分钟九转使用以下七个规范化前复权 K 线数据集：

```text
gold_stk_mins_qfq_1m
gold_stk_mins_qfq_5m
gold_stk_mins_qfq_15m
gold_stk_mins_qfq_30m
gold_stk_mins_qfq_60m
gold_stk_mins_qfq_90m
gold_stk_mins_qfq_120m
```

共同物理根目录为 `gold/quote/stk_mins_qfq`，正式文件按 `freq=<freq>/ts_code=<code>/year=<year>/part-000.parquet` 组织。

主要指数详情页及指数分钟九转使用以下七个规范化 K 线数据集：

```text
gold_major_index_mins_1m
gold_major_index_mins_5m
gold_major_index_mins_15m
gold_major_index_mins_30m
gold_major_index_mins_60m
gold_major_index_mins_90m
gold_major_index_mins_120m
```

共同物理根目录为 `gold/quote/major_index_mins`，正式文件按 `freq=<freq>/trade_date=<date>/part-000.parquet` 组织。

这里的七频率清单是 K 线事实源范围，不扩大九转产品范围：股票 1/5/15 分钟不提供九转，主要指数 1 分钟不提供九转。九转计算只能从上述对应同频 Gold K 线中选择已获产品支持的频率。

## 2. 依据与事实优先级

发生冲突时按以下顺序处理：

1. 用户最新确认的产品口径。
2. 本方案登记的正式 Figma 节点与视觉合同。
3. 当前代码、正式 Lake 物理文件和当前 Dagster Definitions。
4. 股票自主 Gold 方案、指数分钟合同和详情页现有方案。
5. 历史 Tushare 九转文档、旧 Figma capture 和旧阶段门禁。

本文使用 CodeGraph 审计了以下影响面：

1. 五个股票自主九转 asset、checks、jobs、sensors、path 和 schema。
2. 股票/指数详情的日线与分钟 API、capability 和 router。
3. `DetailChartWorkspace` 及股票日线、股票分钟、指数日线、指数分钟四个消费者。
4. 指数 capability、技术右栏和十指数 universe；S7/M5 已将 `supportsNineTurn` 升级为 true，并由 `nineTurnPeriods` 表达环境可用周期。

React 动态调用边由 CodeGraph explore/import 结果和真实消费者代码补充核验。按本文边界实施不改变现有子系统依赖方向。

## 3. 当前真实进度

| 能力 | 当前状态 | 说明 |
|---|---|---|
| 股票日线自主九转 Gold | 已实现 | `gold_stock_daily_qfq_nineturn` 已注册且有正式历史文件 |
| 股票 30/60/90/120 分钟自主九转 Gold | 已完成八列正式迁移 | 四个 asset key、路径和公式不变；四频各 3,068 个正式文件，共 12,272 文件、197,753,897 行，不保存 `close_qfq` |
| 股票分钟 K 线 Gold | 已就绪 | 页面与九转 Reader 统一读取 `gold/quote/stk_mins_qfq`；专项正式范围已覆盖至 2026-08-14 |
| 股票九转详情 API/页面 | M3-C 已完成 | 本地四周期 marker、对齐、性能、内存、缓存、禁用周期和浏览器行为已通过；生产日线接口、权限、真实数据与 Loaded 视觉主体门禁通过。用户已取消正式 P95 和生产缩放边界截图两项补充验收；日线价格漂移与自然更新阻塞另立专项 |
| 股票日线 serving 发布门禁 | M3-B 已完成，后续价格专项待立项 | Gold 历史发布基线已完成；S6 复核发现 2026-08-13/14 上游因子修订后产生新的冗余价格漂移，九转计数/信号不漂移。用户确认本轮不处理价格字段及其自然链路阻塞，不得把该后续项误写为已修复 |
| 主要指数分钟 K 线与技术指标 Gold | 已就绪 | 七频率均已覆盖至 2026-08-14；指数九转消费的 5/15/30/60/90/120 六频率各有 4,279 个分区，页面统一读取规范化 Gold |
| 指数日线九转 Gold | 已完成 | 正式资产、历史、blocking check、生产 serving 和日线 API 已完成 |
| 指数 5/15/30/60/90/120 分钟九转 Gold | 已完成 | 六个资产、正式历史、checks 和本地分钟 API 已完成；不创建 1 分钟资产 |
| 指数九转详情 API/页面 | S7/M5 已完成 | page-init capability、日线/分钟共享 marker、Technical day/60/30 摘要、局部状态、北证50空态与 1 分钟零九转请求均通过；未复制 shared primitive、registry 或 DTO |
| 共享九转绘图组件 | M2 代码已实现 | 单一 `NineTurnMarkerPrimitive` 已接入日线和分钟图表；不参与 autoscale，数据更新不重建图表 |
| 九转正式 Figma | 本轮完成 | Loaded、Components、States 已补齐，见第 5 节 |

### 3.1 M0 历史收口记录

2026-08-13 已按产品矩阵、算法、Figma 节点树、正式数据事实、生产 serving 和本地分钟边界完成 M0 评审：

1. 六个正式 Figma 页面、共享 marker 组件和局部状态可以直接用于开发。
2. 在 2026-08-13 的 M0 时点，股票五个 Gold 资产是已实现事实，指数七个资产仍是后续实施项；该条只记录当时的评审边界，指数资产的当前完成状态以第 3 节进度表和第 3.2 节为准。
3. 物理 11-code 与产品 10-code 的分层、`899050.BJ` 分钟空态和生产分钟 404 均无歧义。
4. 原状态稿可见标题中的“M6”和股票根节点错误尺寸名称已修正为长期职责名称；节点 ID、尺寸和视觉未改变。
5. M0 无剩余 P0 阻塞，可以进入 M1；M0 通过不表示页面功能已经接入。

截至 2026-08-13 的只读物理审计：股票五个自主 Gold 资产均有 3,066 个交易日分区，覆盖 2014-01-02 至 2026-08-12。Definitions 能发现五个资产和五个 blocking integrity checks。当时 Gold 日线 sensor 曾由 `RUNNING` 停止，serving sensor 尚未启用。该段是 M0 的历史操作记录，不代表 2026-08-15 的正式实例状态；当前状态以第 3.3 节的重新审计为准。

### 3.2 M4-B 正式完成事实复核（2026-08-15）

本轮在继续开发前重新做了只读对账，结果与 M4-B 正式执行记录一致：

1. 当前 Definitions 可发现 7 个指数 Gold 九转 assets/checks、1 个指数日线 serving asset/check、3 个 jobs 和 3 个 sensors，不存在指数 1 分钟九转对象。
2. 正式 Lake 当前有日线 6,450 个、六分钟合计 25,674 个九转 Parquet，合计 32,124 个；最终只读报告记录 2,513,295 行、1,607 个批次、所有七个资产通过，缺失/额外分区、重复键、分区错配、源键/源值错配和 1 分钟文件均为 0。
3. event checkpoint 已完成 32,124 个目标分区；冻结计划为每分区 1 条 materialization 和 1 条 blocking-check event，共 64,248 条。
4. 生产只读事务确认 Alembic head 为 `20260814_000136`；`core_serving.index_nineturn_daily` 为 42,633 行、6,450 个交易日，范围 2000-01-04～2026-08-14。

因此，32,124 个正式分区、Dagster event 登记、生产 migration、指数日线 serving 和 M5 指数页面接入都是已完成事实，不再属于待执行项。股票分钟去价格专项也已于 2026-08-15 完成；当前尚未完成的是 M6 日常自动化与最终发布。

### 3.3 六个九转 sensor 当前状态快照（截至 2026-08-15 12:58，Asia/Shanghai）

代码中的 `default_status=STOPPED` 只决定“正式实例没有持久化状态时”的初始值；Dagster instance 一旦保存了 `RUNNING/STOPPED`，持久化状态优先。两者必须分开记录：

本节是 2026-08-15 12:58 的历史快照，不是本文更新时重新读取的实时状态。本次文档审计没有获批读取正式 Dagster instance，因此没有运行 `dg` 或 instance 查询；当前静态代码仍把六个 sensor 的 `default_status` 定义为 `STOPPED`，但静态默认值不能覆盖下表已经记录的持久化状态。M6 若需要刷新实时状态，必须先单独批准只读命令、`DAGSTER_HOME` 和读取范围。

| Sensor | 定义默认值 | 正式实例持久化状态 | 最近一次 tick | 当前结论 |
|---|---|---|---|---|
| `gold_stock_daily_qfq_nineturn_update_job_sensor` | `STOPPED` | `RUNNING` | 12:56:45，`SKIPPED`，0 run；2026-08-03 目标聚合 check 未通过 | 当前物理九转停在 2026-08-12；价格漂移及自然更新阻塞按用户决定移交后续专项，本轮不修改 |
| `gold_stk_mins_qfq_nineturn_update_job_sensor` | `STOPPED` | `RUNNING` | 12:13:01，`SKIPPED`，0 run；最近 5 个分钟前复权九转分区均已 ready | 去价格专项运行恢复通过；周六无新增交易日，下一交易日继续观察 |
| `prod_core_stock_daily_qfq_nineturn_sync_job_sensor` | `STOPPED` | `RUNNING` | 12:58:33，空结果 `SKIPPED`，0 run | 上游没有新的合格 Gold run，因此没有发布；本轮不据此声明自然 serving 链路通过 |
| `gold_major_index_daily_nineturn_update_job_sensor` | `STOPPED` | 无 | 无持久化启动状态 | 实际沿用定义默认值 `STOPPED` |
| `gold_major_index_mins_nineturn_update_job_sensor` | `STOPPED` | 无 | 无持久化启动状态 | 实际沿用定义默认值 `STOPPED` |
| `prod_core_index_daily_nineturn_sync_job_sensor` | `STOPPED` | 无 | 无持久化启动状态 | 实际沿用定义默认值 `STOPPED` |

去价格专项按批准范围停止并恢复了分钟 sensor，reload 后只保留正式 workspace origin；没有改变日线或指数 sensor，也没有产生 run。分钟最近 tick 已证明最近 5 日物理与 check 状态 ready；这不替代 M6 的下一交易日新增分区和最终发布验收。日线价格字段和由此造成的 Gold/serving 自然更新阻塞已按用户决定移交独立后续专项，不属于本轮 M3-C 前端验收退出条件；三个指数 sensor 仍未进入日常自动化。

### 3.4 股票分钟去价格专项正式完成事实（2026-08-15）

1. S2 计划 hash 为 `01d63b246a602f7c0b511beee19695bb85d07159c1ad815d5573c31e68d03757`，冻结 2014-01-02～2026-08-14、3,068 个交易日、12,272 个目标文件、52 个年度批次和 197,753,897 行；`should_stop=false`。
2. S3 四频 candidate 行数为 93,044,536、46,531,692、34,898,769、23,278,900，四份 manifest 全绿后才原子提升。正式聚合审计的缺失、schema、重复键、空键、分区、频度和非法值均为 0；最高单进程 RSS 为 10.61GB，低于 16GiB 门禁。
3. S4 event plan fingerprint 为 `2140016f3d4e29384bb78dfd01838c389a5907e132059fa3e30d22dd9affa7f5`，只包含四个分钟资产。实际追加 12,272 条 materialization 和 80 条最近 20 日 check，日线候选 0，post-plan 候选 0。
4. S5 对 `000001.SZ` 四频各执行 10 次正式 Reader，逐根匹配、缺失 0、返回无价格字段；观测 P95 为 150/32/29/25ms。最近 5 日 readiness 检查 20/20 文件、470,832 行，失败行 0，耗时 2.11 秒。Orchestrator 专项 61 项和 16 个子测试、Foundation/API 32 项通过。
5. 执行未访问 Prod DB/Tushare，未执行 migration、Kopia 或 Dagster materialize/backfill，未修改日线或指数数据。周六没有新增交易日，不伪造新分区触发；下一交易日只做运维观察。

### 3.5 本次进度收口（2026-08-15）

| 层级 | 状态 | 当前事实 |
|---|---|---|
| 产品与视觉合同 | 已完成 | 支持周期、1～9 展示、10+ 不重复画 9、局部降级、Figma Loaded/状态稿已冻结 |
| 股票数据、API 与页面 | M3-C 已完成 | 日线与 30/60/90/120 分钟纵向切片、共享 primitive、权限、数据、分钟性能和浏览器验收已收口 |
| 指数数据与 API | M4-B 已完成 | 7 个 Gold 资产/check、32,124 个分区、64,248 条 events、生产日线 serving 和日线/本地分钟接口已收口 |
| 指数页面 | M5 已完成 | capability、日线/分钟 marker、上证趋势双 primitive、Technical day/60/30、局部状态和浏览器验收已收口 |
| 本地版本 | 已提交，尚未推送 | 当前 M5 提交为 `4c426fd6`；连同其前置工作和 M6-0 收口，本地 `dev-interface` 相对 `origin/dev-interface@99f1f2f5` 有 6 个提交尚未推送 |
| 发布与运维 | M6-0 已通过 | 已完成本地/远端/生产版本、配置、路由、测试、部署参数和回滚点审计；板块测试竞态已修复并通过全量回归。尚未执行 push、部署、生产登录态页面验收、指数 sensor 启用或下一交易日自然更新观察 |
| 股票日线数据治理 | 独立待办 | 冗余 `close_qfq` 漂移及由此造成的自然链路阻塞不影响页面读取，但阻止把股票全链路自动化声明为健康 |

因此，“九转需求开发完成”的准确含义是 M0～M5 的产品、数据、API 和页面代码已完成；整个专项仍未发布完成，也尚未通过 M6 的自然更新和生产验收。股票日线治理可与指数 M6-A 发布准备分开推进，但在该治理问题解决前，不能宣布股票与指数九转的整体日常自动化全部健康。

## 4. 产品与算法合同

### 4.1 统一公式

九转 v1 使用当前 bar 收盘价与前第 4 根 bar 收盘价比较：

1. `close[t] > close[t-4]`：上序列连续计数。
2. `close[t] < close[t-4]`：下序列连续计数。
3. 相等、历史不足或方向为 0：不生成 marker。
4. 方向切换后，新方向从 1 开始。
5. 只使用当前及历史 bar，不读取未来数据，不重绘历史结果。

股票日线和分钟公式唯一使用规范化 Gold QFQ 行情中的 `close` 作为前复权价格输入；公式内统一命名为 `close_value`。日线九转正式资产继续把该输入保存为 `close_qfq`，四个分钟九转正式资产不再保存价格。指数没有复权概念，日线和分钟都使用对应规范化 Gold 的不复权 `close`。Silver 只负责生产规范化 Gold 的上游过程，不属于九转计算或页面读取事实源。

### 4.2 数据计数与页面标记

数据资产保留真实累计计数，允许出现 10、11 以及更大值；页面只显示 1 至 9：

| 数据计数 | 页面 marker |
|---:|---|
| 0 / null | 不绘制 |
| 1～8 | 绘制普通序号 |
| 9 | 绘制带方向色描边的完成态 9 |
| 10 及以上 | 不继续绘制，也不重新从 1 开始 |

这是强制展示映射。不能依据 `nine_up_turn/nine_down_turn` 非空直接重复绘制 9；2026-08-12 股票日线正式文件已有 1,018 行累计计数大于 9，真实数据已经证明该误用风险。

### 4.3 支持矩阵

| 对象 | 日线 | 1 分 | 5 分 | 15 分 | 30 分 | 60 分 | 90 分 | 120 分 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 股票 | 支持 | 不提供 | 不提供 | 不提供 | 支持 | 支持 | 支持 | 支持 |
| 主要指数 | 支持 | 不提供 | 支持 | 支持 | 支持 | 支持 | 支持 | 支持 |

不提供的周期仍可按现有能力展示 K 线，但九转状态为 `UNSUPPORTED`，不发起九转请求，不显示伪造的 `--` marker。

### 4.4 指数对象池和北证50

指数九转的唯一页面对象池是运行时 `majorIndices/CN_A` 的 10 个代码：

```text
000001.SH  399001.SZ  399006.SZ  000688.SH  000300.SH
000905.SH  000852.SH  899050.BJ  000510.SH  000016.SH
```

约束：

1. 数据资产可以有自己的源范围，但 HTTP 接口必须再次执行页面十指数 allowlist。
2. `000680.SH` 不属于页面对象池，必须返回 404，不能因 Lake 有数据而绕过配置。
3. `899050.BJ` 日线九转已建成并可由正式日线 API 返回；当前规范化主要指数分钟 Gold 不覆盖该代码，因此分钟九转返回局部 `EMPTY/SOURCE_NOT_READY`。
4. 北证50分钟不得用日线、其它指数、旧 Lake 或第三方数据补造。

这里必须区分两层 universe：

1. Orchestrator 当前 `major_indices.cn_a.csv` 是 11 个物理代码，额外包含 `000680.SH`；这是主要指数日线、分钟和技术资产已在使用的计算范围。
2. Wealth `majorIndices/CN_A` 是 10 个产品代码，不含 `000680.SH`；这是详情 API 唯一开放范围。
3. 本专项不修改既有 11-code 物理 seed，避免无审计地改变其它主要指数资产；指数九转资产可沿用物理范围计算，但 API 必须按运行时 10-code 配置投影。
4. 若未来要求物理层也只保留 10 个，必须另立影响面审计，不能在九转 LLD 中静默裁掉第 11 个。

## 5. 正式 Figma 评审合同

### 5.1 页面与新增节点

| 页面 | 节点 | 用途 |
|---|---|---|
| 06 Stock Detail - Desktop Loaded | page `345:2`、root `345:3` | 股票日线九转 READY 主画板 |
| 同页交付说明 | `630:602` | 股票支持/禁用周期、局部故障与交互口径 |
| 06.5 Stock Detail - Components | page `358:2` | 股票详情组件页 |
| 共享 marker component set | `406:10` | 唯一九转标记组件；四 variant 为 `406:2/4/6/8` |
| 股票九转组件合同 | `629:516` | 1～9 映射、周期矩阵、几何、状态合同 |
| 07 Stock Detail - States | page `385:2` | 股票状态页 |
| 股票九转局部状态矩阵 | `631:516` | READY/LOADING/EMPTY/ERROR/PARTIAL/FORBIDDEN/UNSUPPORTED |
| 08 Index Detail - Desktop Loaded | page `412:2` | 指数三个 Loaded Tab 的正式页面 |
| Basic / Weights / Technical | `417:2` / `423:2` / `423:910` | 三个 1600×1200 主画板；Weights/Technical 已从 Cover 归位 |
| 指数 Loaded 交付说明 | `632:728` | 支持周期、指数范围、北证50、趋势通道共存 |
| 08.5 Index Detail - Components | page `412:3` | 指数组件页 |
| 指数九转组件与右栏合同 | `633:545` | 复用共享 marker、周期矩阵、Technical 摘要 |
| 09 Index Detail - States and Interaction Notes | page `412:4` | 指数状态页 |
| 指数九转局部状态矩阵 | `634:558` | 含 SOURCE EMPTY 的完整模块状态 |

### 5.2 视觉与几何

1. marker 固定为 18×18；普通 1～8 使用中性数字样式，第 9 根使用方向色数字和 1px 描边、2px 圆角。
2. 上序列 marker 锚定对应 K 线最高价上方 8px；下序列锚定最低价下方 8px。8px 是屏幕像素，不随价格轴缩放。
3. marker 不参与 price autoscale，不得为了容纳 marker 改变 K 线价格范围。
4. marker 位于图表绝对坐标绘图区；页面骨架、工具栏、右栏和状态卡继续使用流式布局。
5. 图层顺序固定为：Tooltip/十字线 > K 线 > 九转 > 趋势通道 > 网格。
6. 九转不增加独立 Tooltip、点击态或交易动作；缩放、拖拽和默认 120 根窗口变化时按时间键贴附。
7. 上证指数日线的趋势通道和九转可以同时存在，二者都不得遮挡 K 线、坐标轴或 Tooltip。

### 5.3 指数技术右栏

指数 Technical Tab 可展示日线、60 分钟、30 分钟三个周期的最新客观九转摘要：

```text
上序 9 / 下序 6 / 上序 3
```

Figma 中的数值只作 Loaded 视觉 fixture，不能成为接口或测试金标。真实摘要取对应周期最新 bar：计数 1～9 显示方向与序号；计数 0、10 以上、无数据或不可用显示 `--`。摘要不解释为买卖信号。

股票详情本轮不增加右栏 Tab，九转只进入共享图表。

## 6. 数据资产方案

### 6.1 股票：复用现有自主 Gold

正式资产：

```text
gold_stock_daily_qfq_nineturn
gold_stk_mins_qfq_nineturn_30m
gold_stk_mins_qfq_nineturn_60m
gold_stk_mins_qfq_nineturn_90m
gold_stk_mins_qfq_nineturn_120m
```

正式路径：

```text
gold/indicator/stock_daily_qfq_nineturn/trade_date=<date>/part-000.parquet
gold/indicator/stk_mins_qfq_nineturn/freq=<freq>/trade_date=<date>/part-000.parquet
```

页面接入不改变已稳定的资产公式。M1 已只读复核最新四频率正式文件：关闭 DuckDB Hive 路径推断后，文件内 `freq` 的真实物理类型为 `INTEGER`，与 writer 和声明合同一致；此前 `BIGINT` 是路径 `freq=<value>` 被自动推断并覆盖同名列造成的审计假象。该结论只说明 `freq` 无需调整；所有 Reader/check 继续显式使用 `hive_partitioning=false`，而下述去价格合同仍要求正式重写四频分钟九转文件。

2026-08-15 新增正式合同修正：

1. `gold_stock_daily_qfq_nineturn` 的 schema、`close_qfq`、Lake、Prod serving、查询和事件完全不变。
2. 四个分钟资产最终 schema 固定为 `ts_code/freq/trade_date/trade_time/up_count/down_count/nine_up_turn/nine_down_turn`，删除 `close_qfq`，且不新增其它价格、量额或涨跌字段。
3. 分钟公式仍从 `gold/quote/stk_mins_qfq` 的同频 `close` 取输入；compact context sidecar 可以在正式 staging 内保存计算所需的最近四根价格，但正式资产和 Reader 不得读取该 sidecar。
4. 分钟合并 blocking check 保留 schema、分区、唯一键、源键覆盖、计数和信号值域，删除目标价格正值和 `source_value_consistency`；日线 check 保持原样。
5. 当前四频各 3,068 个正式文件、共 12,272 个文件均为八列新 schema，覆盖 2014-01-02～2026-08-14。S2～S5 已按 LLD 完成，正式聚合审计确认无新旧 schema 混存。

### 6.2 指数：七个正式资产

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

不创建 1 分钟九转资产。日线上游使用正式指数日线因子/行情事实；分钟上游只能使用对应 `gold_major_index_mins_<freq>m`。这些 Gold K 线也是指数详情页分钟图实际消费的规范化事实，九转与页面 K 线保持同源、同频和逐时间键对齐。路径、schema、source key、十指数投影、check、历史构建、readiness、性能和自动化均已在 M4-B 收口。

指数资产输出与股票自主 Gold 同构的核心语义：

```text
ts_code, trade_date, [freq, trade_time], close,
up_count, down_count, nine_up_turn, nine_down_turn
```

公式版本、lag 和 threshold 放在 asset definition/materialization metadata 与 API meta，不在每行重复存储。页面 API 仍只消费计数并归一 marker，不直接使用持续 `+9/-9` 字段绘图。

### 6.3 旧 Tushare 九转隔离

`raw_tushare_stk_nineturn`、`silver_stock_nineturn_daily` 与 `core_serving.equity_nineturn` 是 Tushare 源站事实链。生产只读审计确认 `core_serving.equity_nineturn` 是直接读取 `raw_tushare.stk_nineturn` 的普通 view，不是自主 QFQ 物理表。它们只可用于离线对照，不能作为自主前复权九转的生产输入或页面 fallback。两种语义必须在代码、表、DTO、监控和文档中彻底分离；禁止改写旧 view 语义或建立兼容 union view。

## 7. 服务与 API 边界

### 7.1 子系统职责

```text
Dagster/Orchestrator -> 计算并发布版本化九转事实
Foundation           -> 只读正式 Lake 或正式 serving，不理解页面状态
Biz                  -> universe、查询、时间键对齐、marker DTO 和数据状态
App                  -> 鉴权与 local/prod 条件路由装配
Wealth               -> 请求、缓存、状态和共享 primitive
```

依赖方向保持 `foundation <- biz <- app`；Wealth 只消费 HTTP。禁止生产代码 import orchestrator，禁止业务 API 读取旧 Lake 或 `_staging`。

### 7.2 独立接口

LLD 应冻结四个独立查询入口：

```http
GET /api/v1/wealth/market/stock-detail/nine-turn
GET /api/v1/wealth/market/stock-detail/minute-nine-turn
GET /api/v1/wealth/market/index-detail/nine-turn
GET /api/v1/wealth/market/index-detail/minute-nine-turn
```

为什么不塞入 Kline 或 `minute-indicators`：

1. 九转有独立数据就绪、权限、空值和错误状态。
2. K 线必须先显示，九转失败不能阻塞 bars。
3. 支持周期与 MA/BOLL/MACD/KDJ 不同。
4. 独立缓存和局部重试可避免重新请求大 K 线 payload。

LLD 可以在保持四个产品入口语义的前提下评估是否共享 schema/service 内核，但不得把股票/指数或日线/分钟的路由环境边界混在一起。

### 7.3 冻结 DTO 方向

后续 LLD 至少定义：

```ts
interface NineTurnMarkerDto {
  tradeDate: string;
  tradeTime: string | null;
  direction: "UP" | "DOWN";
  sequenceNumber: 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9;
  completed: boolean;
}

interface NineTurnSeriesDto {
  subjectType: "stock" | "index";
  tsCode: string;
  period: "day" | "5" | "15" | "30" | "60" | "90" | "120";
  markers: NineTurnMarkerDto[];
  dataStatus: NineTurnDataStatusDto;
  meta: NineTurnMetaDto;
}
```

硬约束：

1. marker 时间键必须与 K 线 bar 一一对齐，返回时间升序。
2. 日线 `tradeTime=null`；分钟时间统一按 Asia/Shanghai 解释和输出。
3. API 不返回 count 10 以上的 marker；debug/meta 可以保留源累计计数统计，但不能让前端重新映射。
4. 严格拒绝未知/重复参数；cursor 必须绑定 subject、code、period 和日期窗口。
5. DTO 使用 required + nullable，不能用 `--`、0 或 `any` 代替缺失。

### 7.4 本地与生产

1. 分钟九转严格跟随现有分钟 capability：只在 `APP_ENV=dev|local`、本地分钟开关、正式 Lake 根和 DuckDB 条件同时满足时挂路由。
2. 生产环境不 import 分钟 Reader，分钟九转 endpoint 必须 404。
3. 日线已通过下述 PostgreSQL serving 路径实现正式生产读取。自主 Gold 位于正式 Lake，生产 Web 不直接读取本机 Lake；表结构、迁移 head、权限、发布编排和回读门禁均已在 LLD 与 M3-B/M4-B 验收中收口。
4. 禁止生产 Web 直接挂载开发机本地 Lake，也禁止以现有 Tushare `core_serving.equity_nineturn` 代替自主结果。

生产日线 serving 冻结为 PostgreSQL 路径，复用仓库已经存在的“Gold -> 独立 prod serving asset -> 事务内按交易日替换 -> read-back 校验”边界，而不是让 Gold asset 自身直接写生产库。参考模式为 `prod_core_wealth_market_turnover`。详情页查询是固定代码、小日期范围、低延迟有序读取，与当前股票/指数日 K 的 PostgreSQL 查询形态一致；本期不增加 ClickHouse 跳转。未来如建设全市场九转筛选，可另建 ClickHouse 查询副本，但 Gold Parquet 仍是唯一事实源。

正式使用两张物理表：

```text
core_serving.equity_qfq_nineturn_daily
core_serving.index_nineturn_daily
```

股票表字段：

```text
ts_code, trade_date, close_qfq,
up_count, down_count, nine_up_turn, nine_down_turn,
formula_version, published_at
```

指数表使用 `close` 替代 `close_qfq`。两表主键均为 `(ts_code, trade_date)`，另建 `(trade_date, ts_code)` 索引服务单日发布、read-back 和 freshness 审计。股票和指数不混表：二者价格口径、对象池、历史构建和异常状态不同；daily 表不保存无意义的 nullable `freq`，也不复制 OHLC、量额。

正式 serving assets：

```text
prod_core_stock_daily_qfq_nineturn
prod_core_index_daily_nineturn
```

每个 serving asset 先验证 Gold schema、分区日期、唯一键、值域、源键覆盖，并逐键比较九转 `close_qfq` 与当前 QFQ 行情 `close`；再在单一 PostgreSQL 事务中删除目标 `trade_date`、批量写入完整新分区、read-back 行数/键集合/内容 hash。任一差异 rollback。股票单日约 5,500 行，使用 `execute_values` 每 1,000 行一页，禁止 Python 单行 insert；Gold scoped rebuild 与历史千万级 serving 发布都使用独立只读计划、1～3 分区 sample、最多 20 个分区一个逻辑 batch和逐分区 checkpoint。Gold 修复单次最多 200 个 batch；serving 固定 DuckDB 128MB/1线程，单进程最多 10 个 batch。plan 只读取 SQL 聚合诊断，不把整分区 rows 装入 Python；恢复时核对全部源文件元数据并流式回验已完成 Prod hash，只对本次待发布日重做深度门禁。CLI 只输出固定大小摘要和逐 batch 进度，不能伪装成普通日常 backfill。

股票表 migration `20260813_000135` 已在生产执行，表结构、主键、索引和 DML 权限与设计一致；最终只读审计确认目标表为 3,066 个交易日、11,638,636 行，与冻结计划的逐日行数完全一致。指数表 migration `20260814_000136` 也已在生产执行，当前表为 6,450 个交易日、42,633 行，范围 2000-01-04～2026-08-14。两张表的全历史发布完成都不代表页面接入与日常自动更新已经全部验收。

M3-A 的历史只读审计曾发现：股票日线九转与 QFQ 行情均有 3,066 个交易日、11,638,636 个键，键集合完全一致，但 18 只股票、3,065 个交易日合计 45,442 行 `close_qfq` 与当时 QFQ close 不一致；按冻结 lag=4 公式重算 45,483 行后计数与信号差异为 0。该发现当时使正式发布 fail closed；随后 M3-B 已完成当时范围的 scoped rebuild、全历史价格/计数/信号零差异对账和 serving 发布。

2026-08-15 S6 只读复核发现了新的、独立于 M3-B 历史范围的漂移：2026-08-13 的 QFQ factor repair 重写 9 个代码，2026-08-14 重写 11 个代码，合计 20 个代码。按当前 3,068 个 QFQ 源分区重算后，既有日线九转可对齐 50,283 行的 `close_qfq` 全部与当前源值不同，但 `up_count/down_count` 差异为 0、`nine_up_turn/nine_down_turn` 差异为 0；另有 40 行属于尚未生成的 20 个代码 × 2 个交易日。页面 DTO 不暴露该价格字段。用户已明确本轮不处理价格信息，不删除字段、不重建历史、不改 check/sensor/生产表，后续另立数据合同专项；本文不得把该漂移写成已修复，也不得让它阻塞 M3-C 的前端 marker、性能和视觉验收。

## 8. 前端与共享图表设计

### 8.1 目标结构

```text
wealth/src/shared/charts/detail-workspace/
  NineTurnMarkerPrimitive.ts
  nineTurnMarkerGeometry.ts
  nineTurnMarkerTypes.ts

wealth/src/features/nine-turn/
  api/  model/  controller/  ui/

wealth/src/features/stock-detail/
  chart/  page/  # 只保留股票页面适配

wealth/src/features/index-detail/
  chart/  sidebar/  # 只保留指数页面与技术面摘要适配
```

四个 chart adapter 只把归一 marker 作为 `mainPrimitives` 传给 shared workspace。指数日线可同时传趋势通道 primitive 与九转 primitive；shared workspace 不理解股票、指数或算法公式。

### 8.2 请求、缓存与竞态

缓存键固定包含：

```text
subjectType + tsCode + period + startDate + endDate
```

切换股票/指数、代码、周期或窗口时：

1. 使用 `AbortController` 取消旧请求。
2. 使用递增 request id 防止已返回的旧响应覆盖新页面。
3. K 线和九转缓存独立；九转局部重试不重复请求 K 线。
4. 切指数右栏 Tab 不重新请求九转，不重置缩放和滚动位置。
5. `dataKey` 仍由现有 shared viewport 控制；九转图层变化不能把默认 120 根窗口重置。

### 8.3 状态机

| 九转状态 | 页面行为 |
|---|---|
| IDLE | 支持周期尚未触发请求；不显示占位 marker |
| LOADING | 已有 K 线立即显示；九转仅用轻量局部骨架 |
| READY | 绘制所有已对齐的 1～9 marker |
| EMPTY | 窗口内没有可显示 marker；不报错 |
| PARTIAL | 只绘制确认对齐的 marker，并显示局部缺失提示 |
| ERROR | 保留 K 线和其它指标，九转显示局部重试 |
| FORBIDDEN | 只隐藏九转并显示权限提示，不升级整页 403 |
| UNSUPPORTED | 禁用且不请求；指数 1 分钟、股票 1/5/15 分钟 |
| SOURCE_EMPTY | 北证50分钟等上游 K 线源不覆盖；不得补造 |

整页 Loading/Empty/Error/Forbidden 继续复用现有页面骨架；只有整页主数据失败时才进入整页状态。九转自身失败不能清空 K 线、趋势通道、MA/BOLL、MACD、成交量、KDJ 或右栏其它数据。

## 9. 异常与安全口径

异常码已在 M1 登记到 `wealth/docs/system/exception-code-registry.md`，实现前保持 `planned`：

| code | 语义 |
|---|---|
| `NT_REQUEST_INVALID` | 参数、limit、cursor、日期窗口非法 |
| `NT_NOT_FOUND` | 股票/指数不在允许对象池 |
| `NT_SOURCE_NOT_READY` | 正式源尚未覆盖请求窗口 |
| `NT_SOURCE_CONTRACT_INVALID` | schema、类型、路径、代码、周期或时间键违约 |
| `NT_ALIGNMENT_PARTIAL` | 部分 marker 无法与同窗口 bar 一一对齐 |
| `NT_QUERY_FAILED` | Reader/SQL/IO/映射失败 |

股票、指数、日线和分钟共享同一恢复语义，因此统一使用 `NT_*`；具体 subject、period 和数据源由 DTO/meta 区分。代码落地并通过对应测试后才改为 `active`。

安全门禁：

1. Reader 只允许固定正式相对路径，不读取 `_staging`、technical state、旧 Lake 或任意用户路径。
2. 固定字段投影，不使用 `SELECT *`，不逐行 Python 扫描全历史。
3. 先按日期分区裁剪，再集合查询；限制最大文件数、响应大小和日期窗口。
4. 禁止 materialize、backfill、sensor、runless event 或 Lake 写操作混入 Web 查询路径。
5. 所有正式验收以只读方式执行。

## 10. 性能与数据门禁

LLD 必须给出可执行预算，至少覆盖：

1. 日线默认查询 300 根、分钟默认查询 500 根 bar 对应的 marker 候选范围；单接口 P95 目标不高于 1.5 秒，硬门禁不高于 5 秒。
2. 查询只扫描必要日期分区，不随全历史增长线性退化。
3. marker primitive 单次 render 只处理当前可见范围，不因历史 marker 总量增加而每帧全量绘制。
4. 切周期、缩放、拖拽不创建新 chart、不重建 K 线 series、不重新请求相同缓存键。
5. 上证趋势通道与九转双 primitive 同时启用时，交互和绘制仍满足现有图表性能门禁。

数据门禁：

1. 股票日线和 30/60/90/120 分钟正向；股票 1/5/15 分钟负向。
2. 指数日线和 5/15/30/60/90/120 分钟正向；指数 1 分钟负向。
3. 覆盖计数 0、1～9、10+、相等、UP→DOWN、DOWN→UP、跨日、跨年、历史不足、重复时间键、源/目标身份错配。
4. `000680.SH` 接口拒绝；`899050.BJ` 分钟局部 EMPTY。
5. 股票分钟 `freq` 真实物理类型已确认是 `INTEGER`；严格 Reader 必须关闭 Hive 路径推断并按该合同验收。

## 11. 测试与视觉验收

### 11.1 数据资产

1. 公式 golden：相等清零、方向切换、计数超过 9、跨日/跨年、缺少前 4 根。
2. schema/path/writer：唯一键、空键、重复键、错误代码/频率、validate-then-promote。
3. checks/readiness：失败关闭、窗口有界、source key 覆盖、不得在 check 中重算公式。
4. 指数 7 个新资产的 Definitions、catalog、job、sensor 和性能测试。

### 11.2 API

1. allowlist、严格参数、分页/cursor、防篡改、时间升序和 bar 时间键对齐。
2. `SOURCE_NOT_READY/CONTRACT_INVALID/ALIGNMENT_PARTIAL/QUERY_FAILED` 与认证矩阵。
3. 九转失败不影响 K 线、分钟技术指标或趋势通道响应。
4. local/prod router 矩阵；生产分钟 endpoint 404。

### 11.3 前端与共享图表

1. 只渲染 1～9；10+ 绝不重复画 9。
2. 不支持周期禁用且网络请求数为 0。
3. 快速切 code/period 时旧响应不串标；缓存键完整。
4. 局部 loading/empty/error/partial/forbidden/unsupported/source-empty。
5. 上证日线趋势通道与九转双 primitive；marker 不影响 autoscale。
6. 缩放、拖拽、默认 120 根和图层切换不重置，日线/分钟时间键正确。

### 11.4 浏览器与像素

1. 股票日线、股票 30/60/90/120 分钟；指数日线、指数 5/15/30/60/90/120 分钟。
2. 北证50分钟 SOURCE EMPTY；指数 1 分钟和股票 1/5/15 分钟 UNSUPPORTED。
3. 1600×1200 页面骨架、右栏、工具栏、图表绘图区相对现有基线偏差不超过 2px。
4. 无新增换行、裁剪、重叠、横向溢出或坐标轴位移。
5. marker 在极值、密集序列和缩放边界仍保持固定像素间距且不被裁剪。

现有相关基线已只读实跑 98 项通过，另有 14 个子测试通过；该结果只证明可复用基线稳定，不代表九转详情接入已完成。

## 12. 分阶段实施顺序

| 阶段 | 工作 | 退出条件 |
|---|---|---|
| M0 | 固化产品合同、补齐正式 Figma、形成总方案评审基线 | 已通过；六个正式页面、产品矩阵和架构边界已冻结，未进入代码 |
| M1 | 编写 LLD；细化并复核生产 serving；冻结 DTO、异常码、Reader、缓存和物理合同 | 已完成并评审通过 |
| M2 | 股票查询与 shared primitive：Reader/API/正式日线 serving/共享几何及最小页面接入 | 代码与隔离验收已通过；后续 M3-B 已完成生产表全历史发布 |
| M3-A | 发布前事实收口 | 已完成只读数据/权限/迁移审计，登记 45,442 行收盘价漂移和正式修复前置条件 |
| M3-B | 发布门禁与历史发布 | 历史发布已完成：Gold 修复和全历史对账通过，serving 以20日batch、单进程最多10批次发布到3,066/3,066日、11,638,636行；十个恢复进程峰值RSS最高约249MiB，最终逐日行数对账差异为0。自然日常链路仍未验收；当前三个股票 sensor 均为实例 `RUNNING` 但最近 tick 全部 `SKIPPED`，见第 3.3 节 |
| M3-C | 股票详情真实环境与视觉收口 | 已完成。分钟页面/API/性能行为及去价格 S0～S5 已完成；生产日线接口、权限、数据与 Loaded 视觉主体门禁通过。用户取消登录态正式 P95、生产 45/180 根截图两项补充验收；日线冗余价格漂移及自然更新阻塞移交后续专项 |
| M4 | 指数日线和六个分钟九转资产及查询 API | M4-B 已完整完成：7 个 Gold assets/checks、1 个 serving asset/check、3 个 jobs/sensors、32,124 个正式分区、64,248 条 Dagster events、生产 migration、6,450 日/42,633 行 serving、日线/本地分钟 API 及正式性能验收均已收口；不存在 1 分钟九转对象 |
| M5 | 指数图表和 Technical 摘要接入 | S7 已完成：十指数 capability、北证50空态、趋势双 primitive、右栏 day/60/30 摘要、局部状态、缓存竞态、1分钟零九转请求和浏览器验收均通过 |
| M6 | 日常自动化、全链路验收与最终发布 | M6-0 已完成并通过；M6-A 仍须另行批准，M6-B～M6-D 尚未开始 |

先做股票纵向切片，因为正式资产已经存在，可以先验证 API、共享 primitive 和产品映射；指数数据资产随后建设，避免把数据生产问题与 UI 机制混在同一阶段。

正式 Lake 写入、历史 backfill、runless event 和 sensor 启用仍须按各阶段单独审批，不能因本文批准而自动获得执行授权。

股票分钟去价格专项不是普通日常 backfill。它已按 [LLD 第 20 节](./detail-page-nine-turn-integration-low-level-design-v1.md#20-股票分钟-qfq-九转去价格字段专项) 完成代码合同、正式只读计划、candidate 全绿、原子替换、事件恢复和运行验收；这次已执行授权不自动授权未来任何 rebuild、event refresh 或 sensor 操作。

### 12.1 M6 后续任务与审批边界

1. **M6-0 发布准备评审（已完成并通过）**：已只读核对本地提交、远端基线、生产版本、日线/分钟路由矩阵、配置和回滚点，并修复审计发现的测试异步等待竞态；本阶段没有推送、部署、Lake/数据库写入、Dagster instance 读取或 sensor 启停。详细结论见第 12.2 节。
2. **M6-A 推送、部署与生产页面验收**：获得明确批准后推送 `dev-interface` 并部署。生产只开放股票/指数日线九转，分钟九转路由保持 404；验收十个指数日线 marker、上证趋势通道与九转共存、Technical 支持周期、权限和页面局部状态。
3. **M6-B 指数 sensor 发布计划**：先在单独批准的只读范围内刷新 Dagster 实例状态，审核 readiness、blocking check、run key/cursor、最大单 tick 工作量、失败停止和回滚方案；计划通过后仍须再次批准，才可启用三个指数 sensor。
4. **M6-C 下一交易日自然更新观察**：观察指数日线、六分钟 Gold/check、指数日线 serving 和页面 freshness；同时观察股票四分钟自然新增。不得用手工 backfill 冒充自然触发成功。
5. **M6-D 最终验收与交付**：收口 HTTP P95、响应体、allowlist、`899050.BJ` 空态、`000680.SH` 404、生产分钟 404、1600×1200 视觉、控制台、回滚演练和运维记录。
6. **并行独立专项**：股票日线冗余价格和自然更新阻塞另立方案处理；它不阻塞指数 M6-0/M6-A，但阻塞“股票与指数全部自动化健康”的最终结论。

上述每一步的批准只覆盖该步，不自动授权下一步，也不自动授权 Lake/数据库写入、Dagster runless event、materialize、backfill 或 sensor 启停。

### 12.2 M6-0 发布准备审计结果（2026-08-15）

1. 审计基线时本地 `dev-interface@4c426fd6` 相对 `origin/dev-interface@99f1f2f5` 领先 5 个提交；生产仓库同样位于 `dev-interface@99f1f2f5` 且工作区干净。发布提交依次为：
   - `6ba34c72`：冻结股票分钟九转无价格合同文档；
   - `43372c89`：落实股票分钟九转八列无价格合同；
   - `96998ccc`：同步去价格执行结果；
   - `99f24480`：登记 M3-C S6 审计边界；
   - `4c426fd6`：完成指数详情 M5 九转接入。
2. 本轮 M6-0 收口另增加一个测试/文档提交；最终候选相对 `origin/dev-interface` 共 6 个提交、54 个文件。范围包含既有 Orchestrator 分钟合同修正、M5 Web 运行代码、板块测试稳定性修复和进度文档；没有新增生产数据库 migration、systemd unit、部署脚本、依赖清单或新配置项。`43372c89` 对应的正式 Lake 合同已在 S2～S5 完成迁移，不属于 M6 再次执行的数据动作。
3. 生产三个核心服务均为 `active`，`/api/health` 与 `/api/v1/health` 均为 200。生产 `APP_ENV=prod`，本地分钟开关及 Lake 根未配置；股票/指数日线九转路由为 401，证明路由存在并受认证保护；两个分钟九转路由为 404，符合生产隔离合同。
4. 发布相关后端/API/架构回归 84 项通过；Orchestrator 隔离合同 56 项及 16 个子测试通过，Ruff 通过；M5 前端定向 76 项、typecheck 和 Wealth production build 通过；正式发布预检为 146 项后端回归、3 项架构边界与前端 production build 全部通过。
5. 初次 Wealth 全量测试为 231/232。根因是板块速览测试等待了加载阶段即存在的常驻标题，随后同步查询异步响应后才出现的“一级行业”容器；该测试竞态由板块专项提交 `9929c6aa` 引入，与九转运行代码无关。修复后改为逐列异步等待真实工作台，板块专项 36/36、Wealth 全量 232/232 和 typecheck 均通过，不再需要发布豁免。
6. M6-A 必须使用 platform-only 窄发布：只构建 Wealth、只重启 Web，显式跳过旧前端、migration、两个 seed、unit 同步、Realtime、Foundation worker、Ops scheduler 和任务完成副作用 worker。完整命令和回滚步骤冻结在 LLD 第 15.7 节。
7. 回滚只针对 M5 运行提交 `4c426fd6` 生成新的 revert commit，再按同一 platform-only 路径部署；不得回滚已完成物理迁移的 `43372c89`，不得删除 Lake、Dagster event 或生产表。

M6-0 的结论为“发布范围可解释、测试门禁全绿、发布路径和回滚路径明确”。M6-0 已通过；推送和部署仍需用户另行明确批准，不能因本文收口自动进入 M6-A。

## 13. M1 LLD 解决结果

[低层设计 v1](./detail-page-nine-turn-integration-low-level-design-v1.md) 已冻结：

1. 两张 serving 表、批量发布、read-back、角色权限和历史发布边界。
2. `freq` 真实物理类型及 `hive_partitioning=false` 强制读取口径。
3. 指数七资产的上游、路径、schema、物理/产品代码池、checks、jobs、sensors 和历史构建。
4. 四个 endpoint、严格参数、分页、最终 DTO、异常和认证。
5. Reader 日期裁剪、5,000 文件上限、5MB 响应上限和性能预算。
6. `NineTurnMarkerPrimitive` 的 18×18、8px、visible range、空 autoscale 和双 primitive 生命周期。
7. 共享请求 registry、缓存、取消、request id、状态优先级和右栏摘要。
8. 日线常驻、分钟条件挂载的 capability/router 单一判定。
9. sensor 定义默认 `STOPPED`、M6 自然触发验收后再进入正式运维的发布门禁；实例持久化状态是独立运行事实，当前值见第 3.3 节。
10. 物理 11-code 与产品 10-code 的投影及负向测试。

M2 开工时已重新核验 Alembic 单一 head 为 `20260813_000134`，九转 migration `20260813_000135` 已按该 head 串接。M2 coding gate 已形成、评审并完成代码对账。

## 14. 非目标

本专项不做：

1. 股票 1/5/15 分钟九转和指数 1 分钟九转。
2. 周 K、月 K 九转。
3. 九转买卖建议、多周期共振、机会筛选、技术结论或交易计划联动。
4. 修改已稳定的股票自主 Gold 公式。
5. 复用或改造 Tushare `stk_nineturn` 作为产品事实。
6. 让前端从 K 线计算或补齐九转。
7. 生产分钟路由开放。
8. 与本专项无关的详情页重构或视觉改版。

## 15. 风险与发布门禁

| 风险 | 门禁 |
|---|---|
| 直接按持续 `+9/-9` 字段画图，10+ 重复出现 9 | DTO 只生成 1～9 marker，并用正式 10+ 样本测试 |
| 自主 Gold 与 Tushare 九转混用 | 独立路径、表、DTO、监控；禁止 fallback |
| 正式 Lake 有数据但生产 Web 不可访问 | 股票 PostgreSQL 全历史已发布并完成逐日对账；仍须通过 M3-C 生产 API、权限、性能和浏览器验收后才开放生产日线 |
| 股票日线 Gold key 完整但持久化价格漂移 | S6 已确认 20 个代码的 50,283 个既有价格值漂移而计数/信号零差异；用户决定本轮不处理，因为前端不消费该价格。当前字段、check、sensor 和生产表保持原样，阻塞事实登记到后续独立专项，不得静默弱化门禁或伪报自然更新已恢复 |
| 股票分钟九转重复保存价格，QFQ 回溯修正后反复触发伪故障 | 四个分钟正式资产删除 `close_qfq`；check 只做源键覆盖和九转值域，K 线价格只读 `gold_stk_mins_qfq`。正式迁移必须 candidate 全绿、逐文件原子替换且禁止新旧 schema 混存 |
| 历史批量发布中断、内存增长或计划变化 | 日线 serving 继续使用128MB/1线程与有界批次；分钟去价格 canonical 链路独立固定2GB/1线程、年度批次释放连接，并在 plan/build/audit 报告真实峰值 RSS，超过管理员批准的16GiB自动停止；所有执行继续绑定只读计划指纹、checkpoint 和固定大小输出 |
| 历史文件齐全但每日不更新 | 独立 job/sensor 已注册且定义默认 `STOPPED`；分钟 sensor 当前实例为 `RUNNING` 且最近 5 日 ready，自然评估已通过；日线仍被既有 check 阻断，三个指数 sensor 实际仍为 `STOPPED`。下一交易日新增分区与 M6 freshness 仍需观察，不能把“RUNNING”或历史齐全直接等同于全链路发布完成 |
| 指数 Lake 额外代码泄漏到页面 | API 每次按 `majorIndices` allowlist 校验 |
| 北证50分钟被补造 | 固定 SOURCE EMPTY 测试与可见局部状态 |
| 九转失败清空 K 线 | 独立 endpoint、controller 和局部状态测试 |
| marker 改变纵轴或缩放跳回默认 | primitive autoscale 空贡献、`dataKey`/range 回归 |
| 单股票分钟查询重复扫描全市场九转分区，导致 Web 内存随请求增长 | 全市场事实由当前 materialization 的 blocking check 保证；Reader 只校验请求股票行并复用 256MB/单线程受锁连接，连续两批 40 请求执行 RSS 增量门禁 |
| 文档早于代码漂移 | 本轮只新增总方案和入口回链；API/异常码在 LLD 冻结后再更新 |

## 16. 文档治理

本方案是九转详情接入专项的上游事实源。历史文档中“九转不在本期、显示 `--`、supportsNineTurn=false”描述的是九转立项前已经完成的阶段，不追溯性改写为错误；后续实现必须引用本文和新 LLD，而不能继续把旧阶段占位当作目标状态。

M0～M5、M6-0 与股票分钟去价格 S0～S5 已同步本方案和 LLD。指数 M4-B 的正式历史、Dagster events、生产 migration/serving、API 与性能验收以及 M5 页面 capability、共享图层、Technical 摘要和局部状态均已完成。用户已取消股票日线正式 P95 与缩放边界截图两项补充验收；日线价格漂移与自然触发阻塞已明确移交后续专项，不得在本轮伪报解决。M6-0 只完成只读发布准备审计，M6-A 仍须按第 12.1～12.2 节结清前置条件并另行授权。第 3.3 节只能作为带时间戳的最近实例快照引用，不能写成未经刷新确认的实时状态。

## 17. 版本记录

下表记录各版本发布当时的阶段事实，较早版本中的“待执行/未授权”可能已在后续版本完成；当前状态只以文首状态、第 3 节进度表和第 3.2～3.3 节的最新事实复核为准。

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-08-13 | 基于当前代码、CodeGraph、正式 Lake、Definitions 与六个正式 Figma 页面形成股票/指数日线与分钟九转总方案评审基线 | Codex |
| v1.1 | 2026-08-13 | M0 评审收口；修正 Figma 状态命名；关闭 freq 类型误判；回链 M1 LLD、异常码与最终实施门禁 | Codex |
| v1.2 | 2026-08-13 | M2 编码门禁与股票纵向切片代码收口；登记日线 serving、四频率 Reader、共享 primitive、股票页面接入和未执行生产发布边界 | Codex |
| v1.3 | 2026-08-13 | 收口 M3-A 数据事实与 M3-B 发布门禁：登记生产空表、45,442 行 close 漂移、20 日可续跑发布器、serving check 和 STOPPED 日常 sensor | Codex |
| v1.4 | 2026-08-13 | 同步 Gold 修复完成、serving 893 日部分发布、内存暂停和 256MB/1线程/单进程10批次门禁 | Codex |
| v1.5 | 2026-08-13 | 同步 serving 1,113 日检查点；修正 plan/resume/CLI 内存与输出放大链路，冻结 128MB、流式恢复回验和逐 batch 摘要；正式只读验收通过，生产恢复仍待用户确认 | Codex |
| v1.6 | 2026-08-13 | M3-B 收口：生产 serving 完成 3,066 日、11,638,636 行全历史发布与逐日对账；十个恢复进程峰值 RSS 最高约 249MiB，M3-C 与自然日常链路继续待验收 | Codex |
| v1.7 | 2026-08-13 | M3-C 生产日线主体门禁通过：登录态 API、真实样本和 1600×1200 Loaded 视觉已验收；正式 P95、生产缩放边界截图与分钟验收继续待完成 | Codex |
| v1.8 | 2026-08-14 | 冻结所有分钟业务事实统一消费规范化 Gold；指数分钟九转上游由旧 Silver 设计修正为同频 `gold_major_index_mins_*`，并登记当前 Gold 覆盖事实 | Codex |
| v1.9 | 2026-08-14 | 完整列出股票与主要指数各七个分钟 K 线 Gold asset key、物理根和分区布局，明确 K 线频率范围不扩大九转支持矩阵 | Codex |
| v1.10 | 2026-08-14 | M3-C-Minute 收口：登记四资产最新 checks、三只股票逐键对齐、严格接口、四周期 P95、Reader 内存根因修正、两批 40 请求门禁及 1600×1200 浏览器验收 | Codex |
| v1.11 | 2026-08-15 | M4-B 编码收口：7 个指数九转 Gold assets/checks、jobs/sensors/readiness、有界历史构建、日线 serving/API 和本地分钟 API 已实现；正式历史、生产 migration/serving 发布和 M5 页面仍待后续授权与验收 | Codex |
| v1.12 | 2026-08-15 | M4-B 正式执行收口：生成并验收 32,124 个正式分区、64,248 条 Dagster events，执行生产 migration，发布 6,450 日/42,633 行指数日线 serving，并完成日线/六分钟 API 和性能验收 | Codex |
| v1.13 | 2026-08-15 | 同步股票分钟 QFQ 九转去价格字段合同：四个分钟资产改为八列无价格 schema，日线完全不变；当时仅冻结文档，代码与正式迁移尚未执行 | Codex |
| v1.14 | 2026-08-15 | 文档漂移收口：重新确认指数 32,124 个正式分区、64,248 条 events、生产 migration 和 42,633 行 serving 已完成；区分 sensor 定义默认值与实例持久化状态，登记三个股票 sensor 实际 RUNNING/最近 tick 均 SKIPPED、三个指数 sensor 实际沿用默认 STOPPED | Codex |
| v1.15 | 2026-08-15 | 去价格专项 S1 收口：分钟 schema/writer/check/history/Reader 已实现八列无价格合同，日线完全隔离；Definitions 与专项回归通过，正式旧九列 Lake、events 和运行链路留给 S2～S5 | Codex |
| v1.16 | 2026-08-15 | 去价格专项 S2～S5 收口：12,272 个正式分钟分区切换为八列合同，登记 12,272 materialization/80 check，完成 Reader/readiness/性能与分钟 sensor 自然评估；日线、Prod 与指数不变 | Codex |
| v1.17 | 2026-08-15 | S6 只读复核：确认 2026-08-13/14 因子修订使日线 20 个代码的 50,283 个既有价格值漂移，但计数与信号均零差异；按用户决定将价格字段及自然链路阻塞移交后续专项，M3-C 仅继续收口前端实际消费的 marker API 性能与 45/180 根视觉边界 | Codex |
| v1.18 | 2026-08-15 | 用户取消登录态正式 P95 与生产 45/180 根截图两项 M3-C 补充验收，M3-C 收口；冻结 S7/M5 仅接入指数 capability、共享 marker、Technical 摘要与局部状态 | Codex |
| v1.19 | 2026-08-15 | S7/M5 收口：指数 capability、日线/分钟共享 marker、Technical day/60/30 摘要、局部状态与并发缓存已实现；修复分钟未操作视窗旧回调竞态，并完成北证50空态、1分钟零九转请求及 1600×1200 浏览器验收 | Codex |
| v1.20 | 2026-08-15 | 进度收口：确认 M0～M5 完成、M6 尚未开始；区分本地提交与推送部署，给出 M6-0～M6-D 执行顺序，并将 sensor 状态改为带时间戳的非实时快照 | Codex |
| v1.21 | 2026-08-15 | M6-0 发布准备审计完成并通过：冻结六提交/54 文件发布清单、生产版本/路由/配置基线、platform-only 发布与 M5 定向回滚；修复板块测试异步等待竞态，专项 36/36、Wealth 全量 232/232 与 typecheck 通过 | Codex |
