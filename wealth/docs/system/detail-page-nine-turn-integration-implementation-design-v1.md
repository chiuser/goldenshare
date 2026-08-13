# 股票与主要指数详情页九转接入总方案 v1

> 状态：M0、M1、M2 已收口；M3-A/M3-B 门禁已完成。Gold 日线修复与全历史验收已完成；生产 serving 发布至 1,113/3,066 个交易日、2,770,508 行后因内存与超大控制台输出风险暂停。发布器修正及正式只读内存验收已通过，恢复发布仍待用户确认。分钟未执行，浏览器真实日线验收和 sensor 启用仍未完成。
>
> 评审基线日期：2026-08-13。
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
8. 股票 Gold 资产已存在不等于页面已接入；指数九转资产、九转 API 和页面接入当前仍未实现。

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
4. 指数 `supportsNineTurn=false`、技术右栏占位和十指数 universe。

React 动态调用边由 CodeGraph explore/import 结果和真实消费者代码补充核验。按本文边界实施不改变现有子系统依赖方向。

## 3. 当前真实进度

| 能力 | 当前状态 | 说明 |
|---|---|---|
| 股票日线自主九转 Gold | 已实现 | `gold_stock_daily_qfq_nineturn` 已注册且有正式历史文件 |
| 股票 30/60/90/120 分钟自主九转 Gold | 已实现 | 四个资产已注册且有正式历史文件 |
| 股票九转详情 API/页面 | M2 代码已实现 | 日线 serving 查询、本地四频率 Reader、独立 HTTP、共享 registry、局部状态和页面图层均已落地；尚未生产发布 |
| 股票日线 serving 发布门禁 | M3-B 部分执行 | Gold 修复已完成；serving 已发布 1,113/3,066 日。发布器已收紧到 DuckDB 128MB/1线程、单进程最多200日，并移除恢复时全历史深扫和超大输出；只读内存复验已通过，全历史和浏览器验收未完成 |
| 指数日线九转 Gold | 未实现 | 需要新资产 |
| 指数 5/15/30/60/90/120 分钟九转 Gold | 未实现 | 需要六个新资产；不创建 1 分钟资产 |
| 指数九转详情 API/页面 | 未实现 | 当前 capability 仍为 false，右栏仍是 `--` 占位 |
| 共享九转绘图组件 | M2 代码已实现 | 单一 `NineTurnMarkerPrimitive` 已接入日线和分钟图表；不参与 autoscale，数据更新不重建图表 |
| 九转正式 Figma | 本轮完成 | Loaded、Components、States 已补齐，见第 5 节 |

### 3.1 M0 收口结论

2026-08-13 已按产品矩阵、算法、Figma 节点树、正式数据事实、生产 serving 和本地分钟边界完成 M0 评审：

1. 六个正式 Figma 页面、共享 marker 组件和局部状态可以直接用于开发。
2. 股票五个 Gold 资产是已实现事实；指数七个资产仍是后续实施项，未被提前标为完成。
3. 物理 11-code 与产品 10-code 的分层、`899050.BJ` 分钟空态和生产分钟 404 均无歧义。
4. 原状态稿可见标题中的“M6”和股票根节点错误尺寸名称已修正为长期职责名称；节点 ID、尺寸和视觉未改变。
5. M0 无剩余 P0 阻塞，可以进入 M1；M0 通过不表示页面功能已经接入。

截至 2026-08-13 的只读物理审计：股票五个自主 Gold 资产均有 3,066 个交易日分区，覆盖 2014-01-02 至 2026-08-12。Definitions 能发现五个资产和五个 blocking integrity checks。执行前正式 instance 中 Gold 日线 sensor 实际为 `RUNNING`，但最近 10 个 tick 均为 SKIPPED 且没有并发 run；本轮已将其停止。serving sensor 从未启用。两者都必须继续保持停用，不能把历史完整误写成每日自动更新已经投产。

## 4. 产品与算法合同

### 4.1 统一公式

九转 v1 使用当前 bar 收盘价与前第 4 根 bar 收盘价比较：

1. `close[t] > close[t-4]`：上序列连续计数。
2. `close[t] < close[t-4]`：下序列连续计数。
3. 相等、历史不足或方向为 0：不生成 marker。
4. 方向切换后，新方向从 1 开始。
5. 只使用当前及历史 bar，不读取未来数据，不重绘历史结果。

股票价格唯一使用 `close_qfq`。指数没有复权概念，日线使用正式指数日线 close，分钟使用主要指数 Silver 同频 close。

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
3. `899050.BJ` 日线九转可以建设；当前主要指数分钟 Silver 明确排除该代码，因此分钟九转返回局部 `EMPTY/SOURCE_NOT_READY`。
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

页面接入不改变已稳定的资产公式。M1 已只读复核最新四频率正式文件：关闭 DuckDB Hive 路径推断后，文件内 `freq` 的真实物理类型为 `INTEGER`，与 writer 和声明合同一致；此前 `BIGINT` 是路径 `freq=<value>` 被自动推断并覆盖同名列造成的审计假象。所有新 Reader/check 必须显式 `hive_partitioning=false`，无需改写正式文件。

### 6.2 指数：新建七个资产

建议新资产：

```text
gold_major_index_daily_nineturn
gold_major_index_mins_nineturn_5m
gold_major_index_mins_nineturn_15m
gold_major_index_mins_nineturn_30m
gold_major_index_mins_nineturn_60m
gold_major_index_mins_nineturn_90m
gold_major_index_mins_nineturn_120m
```

不创建 1 分钟九转资产。日线上游使用正式指数日线因子/行情事实；分钟上游使用对应 `silver_major_index_mins_<freq>m`。指数资产必须独立形成方案与 LLD，冻结路径、schema、source key、十指数投影、check、历史构建、readiness、性能和自动化。

指数资产建议输出与股票自主 Gold 同构的核心语义：

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
3. 日线目标是正式生产可用。自主 Gold 当前位于正式 Lake，而生产 Web 不能直接读取本机 Lake；本轮已完成专项架构审计，并冻结为下述 PostgreSQL serving 路径。LLD 负责复核表结构、迁移 head、权限、发布编排和回读门禁。
4. 禁止生产 Web 直接挂载开发机本地 Lake，也禁止以现有 Tushare `core_serving.equity_nineturn` 代替自主结果。

生产日线 serving 冻结为 PostgreSQL 路径，复用仓库已经存在的“Gold -> 独立 prod serving asset -> 事务内按交易日替换 -> read-back 校验”边界，而不是让 Gold asset 自身直接写生产库。参考模式为 `prod_core_wealth_market_turnover`。详情页查询是固定代码、小日期范围、低延迟有序读取，与当前股票/指数日 K 的 PostgreSQL 查询形态一致；本期不增加 ClickHouse 跳转。未来如建设全市场九转筛选，可另建 ClickHouse 查询副本，但 Gold Parquet 仍是唯一事实源。

建议新建两张物理表：

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

建议 serving assets：

```text
prod_core_stock_daily_qfq_nineturn
prod_core_index_daily_nineturn
```

每个 serving asset 先验证 Gold schema、分区日期、唯一键、值域、源键覆盖，并逐键比较九转 `close_qfq` 与当前 QFQ 行情 `close`；再在单一 PostgreSQL 事务中删除目标 `trade_date`、批量写入完整新分区、read-back 行数/键集合/内容 hash。任一差异 rollback。股票单日约 5,500 行，使用 `execute_values` 每 1,000 行一页，禁止 Python 单行 insert；Gold scoped rebuild 与历史千万级 serving 发布都使用独立只读计划、1～3 分区 sample、最多 20 个分区一个逻辑 batch和逐分区 checkpoint。Gold 修复单次最多 200 个 batch；serving 固定 DuckDB 128MB/1线程，单进程最多 10 个 batch。plan 只读取 SQL 聚合诊断，不把整分区 rows 装入 Python；恢复时核对全部源文件元数据并流式回验已完成 Prod hash，只对本次待发布日重做深度门禁。CLI 只输出固定大小摘要和逐 batch 进度，不能伪装成普通日常 backfill。

股票表 migration `20260813_000135` 已在生产执行，表结构、主键、索引和 DML 权限与设计一致；截至本轮暂停前最后一次只读审计，目标表为 1,113 个交易日、2,770,508 行。指数表仍属于 M4，当前不存在。迁移和部分数据只代表容器与局部事实就绪，不代表股票全历史已发布。

M3-A 对正式数据的只读审计记录：股票日线九转与 QFQ 行情均有 3,066 个交易日、11,638,636 个键，键集合完全一致；但 18 只股票、3,065 个交易日合计 45,442 行 `close_qfq` 与当前 QFQ close 不一致，属于复权因子变化后的持久化价格漂移。按冻结 lag=4 公式重算这些股票共比较 45,483 行，计数与信号差异为 0。这意味着 marker 语义当前仍正确，但 Gold 每行价格事实已经过期，正式发布必须 fail closed，先执行另行审批的 scoped rebuild。

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
| M2 | 股票查询与 shared primitive：Reader/API/正式日线 serving/共享几何及最小页面接入 | 代码与隔离验收已通过；生产表已迁移但为空 |
| M3-A | 发布前事实收口 | 已完成只读数据/权限/迁移审计，登记 45,442 行收盘价漂移和正式修复前置条件 |
| M3-B | 发布门禁与日常链路 | Gold 修复和全历史对账已完成；serving 发布至1,113/3,066后暂停。serving 固定128MB/1线程、20日batch、单进程最多10批次；plan/resume/CLI 放大点已修正，正式只读 plan 峰值约237MiB、恢复回验峰值约156MiB并通过；剩余历史发布仍待用户确认，最终对账未完成 |
| M3-C | 股票详情真实环境与视觉收口 | 待 Gold 修复和历史 serving 发布后，完成生产日线 API、浏览器、缩放与局部故障验收；不建第二套控制器 |
| M4 | 新建指数日线和六个分钟九转资产及查询 API | 7 assets/checks 被 Definitions 发现；历史覆盖、对齐、性能通过；1 分钟无资产 |
| M5 | 指数图表和 Technical 摘要接入 | 十指数、北证50空态、趋势双 primitive、右栏摘要和竞态通过 |
| M6 | 日常自动化、全链路验收与最终发布 | 生产日线、本地分钟、生产分钟 404、freshness、性能和视觉验收全部通过 |

先做股票纵向切片，因为正式资产已经存在，可以先验证 API、共享 primitive 和产品映射；指数数据资产随后建设，避免把数据生产问题与 UI 机制混在同一阶段。

正式 Lake 写入、历史 backfill、runless event 和 sensor 启用仍须按各阶段单独审批，不能因本文批准而自动获得执行授权。

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
9. sensor 初始 STOPPED、M6 自然触发验收后再启用的发布门禁。
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
| 正式 Lake 有数据但生产 Web 不可访问 | 股票 PostgreSQL 仅发布1,113/3,066日；只有全历史发布和生产回验通过后才开放生产日线 |
| Gold key 完整但持久化价格已漂移 | 45,442 行漂移已完成 scoped rebuild；Gold blocking check 与 serving loader 继续比较源 close，防止再次漂移 |
| 历史批量发布中断、内存增长或计划变化 | 只读计划指纹、最多20日批次、逐日事务与checkpoint；DuckDB固定128MB/1线程；plan不用全量row loader，恢复不重建全历史深度计划，Prod采用server cursor流式hash；单进程最多10批次并退出释放内存；CLI固定大小输出 |
| 历史文件齐全但每日不更新 | 独立 serving job/sensor 已注册且默认 STOPPED；历史发布、自然触发和 freshness 验收后另行审批启用 |
| 指数 Lake 额外代码泄漏到页面 | API 每次按 `majorIndices` allowlist 校验 |
| 北证50分钟被补造 | 固定 SOURCE EMPTY 测试与可见局部状态 |
| 九转失败清空 K 线 | 独立 endpoint、controller 和局部状态测试 |
| marker 改变纵轴或缩放跳回默认 | primitive autoscale 空贡献、`dataKey`/range 回归 |
| 文档早于代码漂移 | 本轮只新增总方案和入口回链；API/异常码在 LLD 冻结后再更新 |

## 16. 文档治理

本方案是九转详情接入专项的上游事实源。历史文档中“九转不在本期、显示 `--`、supportsNineTurn=false”描述的是九转立项前已经完成的阶段，不追溯性改写为错误；后续实现必须引用本文和新 LLD，而不能继续把旧阶段占位当作目标状态。

M3-A/M3-B 已同步本方案、LLD 和独立发布门禁。股票 `NT_*` 已进入 active-code 状态；指数仍为 planned。index page-init 当前仍保持 `supportsNineTurn=false`。Gold scoped rebuild 已完成，但 serving 仍是 1,113/3,066 的部分发布；发布器内存与输出修正已通过正式只读复验，恢复写入仍待用户确认。只有全历史发布、生产 API、Figma 浏览器截图和 Dagster 自然触发验收完成后，才可把股票能力标为 production-ready。

## 17. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-08-13 | 基于当前代码、CodeGraph、正式 Lake、Definitions 与六个正式 Figma 页面形成股票/指数日线与分钟九转总方案评审基线 | Codex |
| v1.1 | 2026-08-13 | M0 评审收口；修正 Figma 状态命名；关闭 freq 类型误判；回链 M1 LLD、异常码与最终实施门禁 | Codex |
| v1.2 | 2026-08-13 | M2 编码门禁与股票纵向切片代码收口；登记日线 serving、四频率 Reader、共享 primitive、股票页面接入和未执行生产发布边界 | Codex |
| v1.3 | 2026-08-13 | 收口 M3-A 数据事实与 M3-B 发布门禁：登记生产空表、45,442 行 close 漂移、20 日可续跑发布器、serving check 和 STOPPED 日常 sensor | Codex |
| v1.4 | 2026-08-13 | 同步 Gold 修复完成、serving 893 日部分发布、内存暂停和 256MB/1线程/单进程10批次门禁 | Codex |
| v1.5 | 2026-08-13 | 同步 serving 1,113 日检查点；修正 plan/resume/CLI 内存与输出放大链路，冻结 128MB、流式恢复回验和逐 batch 摘要；正式只读验收通过，生产恢复仍待用户确认 | Codex |
