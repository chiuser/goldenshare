# 财势探查｜主要ETF（国家队）监测技术实施方案 v1

2026-11-27。桌面 Figma、本文与[低层设计](./major-etf-monitor-low-level-design-v1.md)已获管理员确认。第 1 阶段授权为本机 DG 后端、接口和真实数据对账。管理员已补充确认将共享客户端并发续期修复列为[阶段 2 开工前置](#major-etf-monitor-phase-2-prerequisite)。

第 1 阶段本地后端、接口回归和真实 DG 对账已完成。[第 1 阶段对账记录](./major-etf-monitor-low-level-design-v1.md#major-etf-monitor-phase-1-result)

共享客户端并发续期修复已通过本机回归及独立审计。第 2 阶段桌面前端已完成并通过独立审计。第 3 阶段由管理员验收并确认整体通过，本期交付已收尾。[前置修复的验证结果](./major-etf-monitor-low-level-design-v1.md#major-etf-monitor-phase-2-gate) · [第 2 阶段审计记录](./major-etf-monitor-low-level-design-v1.md#major-etf-monitor-phase-2-result) · [第 3 阶段验收记录](./major-etf-monitor-low-level-design-v1.md#major-etf-monitor-phase-3-result)

## 1. 目标与评审依据

在「ETF 动态」桌面页的全市场成交额趋势和排行榜下方新增一组双栏。左侧「主要ETF（国家队）成交额趋势」展示固定 14 只场内 ETF 的每日成交额合计，默认 1 个月，可切换 3 个月。右侧「主要ETF（国家队）行情」展示最新一个已有 DG ETF 日线的交易日，按图稿顺序显示 14 只 ETF 的五列行情。区间切换仅影响新模块左图。

[1 个月桌面稿](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2303-3761) · [3 个月桌面稿](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2303-3896) · [交易日读数](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2302-3658) · [加载](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2304-6026) · [暂无数据](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2304-6168) · [读取失败](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2304-5989)

图稿数值用于评审。正式数据仅读取 DG 本地 ETF 日线和 ETF 基础信息。模块名称沿用已确认图稿，页面只展示日线行情和成交额。

## 2. 当前实现与落位

| 已核对的现行实现 | 本模块的做法 |
| --- | --- |
| `EtfActivityPage` 在 `WealthExplorationShell` 内装配全市场趋势和排行榜，使用 `useEtfActivity` 与 `/api/v1/wealth/market/etf-activity`。 | 在同一个页面追加独立模块，沿用页面壳、快捷卡、桌面双栏、`Panel`、`RangeSwitch`、数值格式和行情色。新模块有自己的请求、区间选择和重试。 |
| `query_etf_activity` 使用交易日历确定开市日、预热均线并取前一交易日排名。它的趋势已汇总全市场，榜单只返回前 50。 | 新增模块接口 `GET /api/v1/wealth/market/major-etf-monitor`。以 ETF 日线分区确定日期，向 DG 只查询这 14 个代码。全市场接口的字段、计算和调用方继续按其[技术实施方案](./etf-activity-implementation-design-v1.md)执行。 |
| `EtfDailyLakeReader` 已实现正式路径枚举、同日基础信息快照定位、Parquet 列类型核对、带截止时间的 DuckDB 查询。 | 复用本地读取能力。App 按现有本地开关挂载新接口并注入行情认证与读取依赖，Biz 负责名单、日期区间、聚合和响应，Foundation 负责文件读取。 |

已用 CodeGraph `codegraph_explore` 核对页面、请求 hook、图表和表格消费者，以及 App 装配、Biz 查询和 Foundation 读取链。另核对了现有[接口测试](../../../../tests/web/test_wealth_market_etf_activity_api.py)和[页面测试](../../../src/pages/wealth-exploration/EtfActivityPage.test.tsx)。新增接口仅供页内新模块消费。具体代码位置见 LLD。

## 3. 标的、数据与计算

### 3.1 固定标的和表格顺序

按已确认画板从上到下展示。ETF 名称在运行时取 DG ETF 基础信息，下表用于标明评审对象。

| 顺序 | ETF 代码 | ETF 名称 |
| --- | --- | --- |
| 1 | `510300.SH` | 华泰柏瑞沪深300ETF |
| 2 | `510310.SH` | 易方达沪深300ETF |
| 3 | `510330.SH` | 华夏沪深300ETF |
| 4 | `159919.SZ` | 嘉实沪深300ETF |
| 5 | `510050.SH` | 华夏上证50ETF |
| 6 | `510500.SH` | 南方中证500ETF |
| 7 | `512500.SH` | 华夏中证500ETF |
| 8 | `512100.SH` | 南方中证1000ETF |
| 9 | `159845.SZ` | 华夏中证1000ETF |
| 10 | `560010.SH` | 广发中证1000ETF |
| 11 | `159629.SZ` | 富国中证1000ETF |
| 12 | `159915.SZ` | 易方达创业板ETF |
| 13 | `159977.SZ` | 天弘创业板ETF |
| 14 | `588000.SH` | 华夏上证科创板50成份ETF |

名单及顺序是本模块本版的产品定义，在 Biz 维护一份有序名单。浏览器按 API 返回的顺序渲染。改动名单须重新评审本节及对应画板，随版本发布。运营侧和页面均无对象池或排序配置。

### 3.2 数据来源和窗口

| 业务数据 | 正式 DG 路径（相对 `/Volumes/datasource/data_lake`） | 投影 |
| --- | --- | --- |
| ETF 日线（`etf_daily`） | `silver/quote/etf_daily/trade_date=YYYY-MM-DD/part-000.parquet` | `trade_date`、`ts_code`、`amount`、`close`、`pct_chg` |
| ETF 基础信息（`etf_basic`） | `silver/basic/etf_basic/snapshot_id=<hash>/part-000.parquet` | `ts_code`、`csname`、`extname`、`cname` |

1. 行情日期 `tradeDate` 取上海时间当天及以前存在正式日线文件的最新分区日期。两段区间都以该日期为右端点，向前推 1 或 3 个自然月，起止均包含。目标月份无同日时取该月末。横轴按区间内已有 DG ETF 日线分区的交易日期等距排列，由早到晚。只有这两个业务数据集可读。整个分区缺失时，页面无法据此区分休市和缺档，该日不生成点。
2. 左图只画一条成交额线。DuckDB 按日期筛选并汇总固定 14 个代码，当日每个代码恰有一条有效成交额且齐全时，`amountYuan = SUM(amount) × 1000`。任一码当日无记录时，该已有分区的合计为 `null`，图上断线。有效的 `0` 成交额参与加总。纵轴从 0 开始，正向上限和刻度随可见数据变化。悬停或用方向键查看交易日和当日合计，缺值显示「—」。
3. 右表以该最新分区为准。代码用 `ts_code`，名称按同日引用的基础信息依次取 `csname`、`extname`、`cname` 的首个非空白值。现价取 `close`（当日收盘价，元），涨跌幅取 `pct_chg`（原值已是百分数），成交额取 `amount × 1000`（千元转元）。价格三位小数，涨跌幅两位小数，成交额按亿元展示两位小数。名称缺失用「—」。最新分区只有部分标的有日线时，保留 14 条对象行，缺失行的三个行情值显示「—」。
4. 本机 DG `silver_etf_daily` 最新一笔同日物化元数据只用于定位其引用的 ETF 基础信息快照。沿用现有 `basic_file` 校验日线分区、文件路径和快照标识。每次至多一次 `127.0.0.1:3000` 的读取。所有行情与名称取自表中两个正式 Parquet 数据集。交易日历、其他数据集、Prod 与写入操作均在本模块授权范围外。

来源合同已对照 DG 的[日线写入](../../../../lake_console/orchestrator/src/orchestrator/defs/io/etf_daily_silver_writer.py)、[日线资产](../../../../lake_console/orchestrator/src/orchestrator/defs/assets/etf_daily.py)、[基础信息资产](../../../../lake_console/orchestrator/src/orchestrator/defs/assets/etf_basic.py)及[现行读取实现](../../../../src/foundation/clients/local_lake/etf_daily_reader.py)。单位依据本地[ETF 日线行情字段说明](../../../../docs/sources/tushare/ETF专题/0127_ETF日线行情.md)。

## 4. 模块接口、状态及本地隔离

- 接口仅返回新模块的行情日、1 个月起日、状态、3 个月的有序趋势和最新行情。客户端首次进入发一次请求，切换时用服务端返回的 `oneMonthStartDate` 截取同一序列，右表的交易日、内容和纵向滚动位置保持一致。详细字段见 LLD。
- 加载、空结果和读取失败按 Figma 呈现。窗口内缺失标的时，按 §3.2 显示局部缺值。源目录、引用、Parquet 或合同异常，以及服务端读超时，按失败状态处理。同日文件和引用逐份发布期间，单次读取可能遇到引用未就绪，手动重试会重新定位文件和引用。
- 沿用 `APP_ENV` 显式为 `dev` 或 `local` 的后端装配开关，以及 Development 或 `local-dg` 的 ETF 动态前端入口。正式根只接受 `/Volumes/datasource/data_lake`。非本地后端无该 API，直接请求返回 404。使用现有行情认证，本机验证使用本机认证配置。HTTP 响应走 `Cache-Control: no-store`。
- 配置项沿用现有 `APP_ENV`（默认值不足以启用，须显式设置）、`GOLDENSHARE_LAKE_ROOT`（默认空，读取时须是正式根）和既有前端构建模式。均维持现有来源和生效方式，后端配置变更后重启，前端随构建模式生效。新旧 ETF 模块共用 App 本地入口的判定；本轮没有新增开关、策略配置、持久状态或远程配置请求。

## 5. 读取规模与验收预算

| 操作 | 数量及依据 |
| --- | --- |
| 首次请求 | 新模块 1 次 Web API。ETF 日线目录枚举只读路径元数据，数据查询仅打开 3 个月内选中的分区。三个连续自然月日期差至多 92 天，计入两端至多 93 个日期分区；按每个日期 14 个目标对象，至多 1,302 条符合主键口径的输入行。实际 Parquet 页读取量需实测。 |
| 基础信息与查询 | 最近分区至多查一次同日 DG 引用、打开一个 ETF 基础信息文件。一条批量 DuckDB 查询共享筛选后的日线输入，左图、右表金额从同一批结果生成。现有 reader 按文件检查 Parquet 投影字段与类型。响应至多 93 个趋势点和 14 行行情。 |
| 切换、重试与退出 | 区间切换新增请求 0 次。手动重试每次重新走一次同等范围的读取，重试时重新取得截止时间。退出页面取消客户端请求，服务端依自身截止时间结束读数。无续跑记录。 |
| 时间标准 | 沿用 ETF 动态 5 秒客户端时限，包含响应体读取。后端源读取共用 5 秒预算，覆盖目录、DG 引用、Parquet 核对与 SQL。各阶段用同一代表窗口实测首次请求、手动重试、两模块同页首次打开。以真实浏览器在客户端时限内出现可用状态为最终标准。 |

2026-11-26 有界只读样本：`2026-08-26` 至 `2026-11-26` 找到 61 个正式日线文件，61 个分区都各有 14 条有效目标日线，同日引用的基础信息快照查到 14 个非空名称。最新日合计 `44,382,245,742.60` 元，展示 `443.82` 亿元。目录当时有 460 个日期目录名，窗口文件合计 3,247,691 字节，基础信息快照 119,193 字节。单次本地只读探查从路径枚举到有界 SQL 约 425 毫秒。本次记录是样本体量和文件读取证据，端到端耗时、并发首次打开及重试随实现实测。本样本依据已有分区，未判断整个窗口有无缺失的交易日分区。

## 6. 分阶段开发与验收

| 阶段 | 交付与门槛 |
| --- | --- |
| 1. 本地后端与 API | 先实现两份 DG 文件读取、投影、字段映射和相关集成测试。走真实 API 路由，对最新一个交易日的 14 行和代表性窗口成交额独立核对，检查非本地返回 404、没有其他行情数据访问。管理员确认第 1 阶段结果。 |
| 2. 桌面前端 | [开工前置](#major-etf-monitor-phase-2-prerequisite)通过后接入同一页新模块。核对 Figma 位置、两栏比例、5 列、固定表头、14 行滚动、1/3 个月切换、新旧模块的请求与状态独立。执行类型、测试及两种构建，审核本地入口和非本地构建。 |
| 3. 本机真实验收 | 用本机登录和真实 API 对照 DG 验收，记录数据日、样本值、首次打开、重试和区间切换请求。针对本模块做回退时，撤下新面板和新增接口注册即可，DG 无写入或迁移。管理员确认整体验收后记录结果。 |

<a id="major-etf-monitor-phase-2-prerequisite"></a>

### 6.1 阶段 2 开工前置

ETF 动态的全市场模块与主要 ETF 模块会并行请求。访问令牌过期并同时收到 `401` 时，现有共享客户端会用同一刷新令牌续期两次，可能导致模块报错或登录状态被清除。管理员确认先完成 Wealth 共享客户端修复，再开始 ETF 桌面前端。修复在 `wealthFetch` 统一落地，现有页面消费方式沿用。详见[认证方案](../login/login-page-auth-design-v1.md#wealth-concurrent-auth-refresh-plan)与[认证 LLD](../login/login-page-auth-low-level-design-v1.md#wealth-concurrent-auth-refresh-lld)。

第 1 阶段结果经管理员确认，且共享修复的实现及回归结果已记录，方可开始阶段 2。共享修复的验收须证明同一会话的两个行情请求遇到 `401` 时只续期一次且都能继续，单个请求取消不影响另一个请求，交易助手原写请求只发送一次。ETF 两模块仍各自管理状态、取消和 5 秒时限。ETF 接口与 DG 本地只读来源沿用已确认的边界，禁止连接 Prod。该修复是开工前置，阶段编号仍为 1 至 3。

## 7. 跨模块门禁原则

| 原则 | 设计落点与证据 |
| --- | --- |
| 事实源单一 | §3.2 两个 DG 数据集，后端产出名称、金额和顺序。用两份真实源文件对 API 结果。 |
| 契约先行 | LLD 固定 DTO、可空项和异常语义，集成和页面用例按合同逐项对账。 |
| 配置一致 | §4 复用已有本地开关；§3.1 在 Biz 只维护一份固定名单。测试误配根目录及全量顺序。 |
| 默认行为 | 最新已有日线、1 个月默认、3 个月切换、缺值与重试见 §3–4，分别验证。 |
| 排序与筛选 | 后端按 14 个全代码筛选并按表中固定顺序输出；样本混入大额名单外 ETF，验证排除。 |
| 性能预算 | §5 有界文件与响应、同页实测、无切换请求；记录正常、失败后重试和最终验收。 |
| 可观测与异常 | 使用 Web 既有错误结构与 request ID，记录耗时、异常阶段及交易日，不向页面暴露路径。 |
| 用户可见结果 | 真实路由和真实浏览器分别校验图表交易日、总额、右表 5 列以及布局和状态。 |

管理员已确认已有分区定义、缺一只时该日合计留空、右表按图稿固定顺序，以及新增独立的本地模块接口。上述口径按 LLD 的对应验收条件执行。
