# 股票与主要指数详情页九转接入低层设计（LLD）v1

> 状态：M0、M1、M2、M3-A、M3-B 已通过。Gold 日线修复、全历史对账和生产 serving 发布均已完成；生产表按冻结计划验收到 3,066 个交易日、11,638,636 行，逐日差异为 0。修正后的十个短进程峰值 RSS 最高约 249MiB，未复现内存爆炸。分钟未执行，M3-C 浏览器验收尚未开始。
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

本文最初只形成设计；M2 现已在用户确认 coding gate 后实施代码。以下运行态动作仍未获得授权且未执行：

1. `20260813_000135` 已由其它已授权操作执行；本轮不新增或回滚生产 migration。
2. 本轮不运行 materialize、backfill、runless event、正式 Lake 写入、Gold 修复或生产发布。
3. 本轮只注册独立 serving sensor，保持 `STOPPED`，不启用任何股票九转 sensor。
4. 不创建指数九转资产或修改指数页面。

最终实现结构冻结为：

1. 股票沿用五个自主前复权 Gold 九转资产；不消费 Tushare 九转事实。
2. 指数新建日线一个、分钟六个 Gold 九转资产；不创建 1 分钟资产。
3. 日线九转由独立 PostgreSQL serving 表向所有 Web 环境提供；Web 不直读生产 Lake。
4. 分钟九转只在本地开发能力满足时读取正式 Lake；生产不 import Reader，路由为 404。
5. 四个 HTTP 入口共享一套 DTO、marker 映射、状态和异常语义。
6. 前端复用一个请求注册表、一个 `NineTurnMarkerPrimitive` 和现有 `DetailChartWorkspace`。
7. 九转图层与 K 线、分钟技术指标、趋势通道独立降级；失败不清空其它内容。

## 2. M0 评审收口

### 2.1 退出条件结果

| M0 门禁 | 结果 | 证据与结论 |
|---|---|---|
| 产品周期矩阵 | 通过 | 股票 day/30/60/90/120；指数 day/5/15/30/60/90/120；其余周期九转零请求 |
| 公式与展示映射 | 通过 | lag=4、threshold=9、formulaVersion=1；资产可计数 10+，页面只画 1～9 |
| 股票事实源 | 通过 | 五个自主 QFQ Gold 资产、五个 blocking checks 与正式历史文件已存在；页面接入仍未实现 |
| 指数建设边界 | 通过 | 新建七个资产；物理 11-code seed 不变，产品严格按 Wealth 10-code allowlist |
| 北证50边界 | 通过 | `899050.BJ` 支持日线；分钟源不覆盖时返回局部 SOURCE EMPTY，不补造 |
| 生产与本地边界 | 通过 | 日线走 PostgreSQL serving；分钟仅 local/dev 正式 Lake；生产分钟路由 404 |
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
| C11 | 分钟只读正式 Lake | capability、Reader | 旧 Lake、staging、technical state、任意路径均拒绝 |
| C12 | 生产不挂分钟九转路由 | App composition root | 生产四个分钟 URL 均 404 |
| C13 | 前端不计算九转 | adapter、primitive | 前端无 lag/segment/count 公式 |
| C14 | marker 不参与纵轴 autoscale | primitive | `autoscaleInfo()` 始终返回 null |
| C15 | 上证日线允许双 primitive | Index chart adapter | 趋势通道任一状态不阻塞九转，反之亦然 |
| C16 | 没有交易动作 | UI、事件测试 | marker、摘要无 click/交易 handler |

## 4. 当前代码审计

### 4.1 CodeGraph 影响面

本轮使用仓库根 CodeGraph 索引审计了：

1. `StockDetailPage -> stock page-init/kline/minute clients -> StockChartWorkspace/StockMinuteChartWorkspace`。
2. `IndexDetailPage -> useIndexDetailController/useIndexMinuteSeries -> IndexChartWorkspace/IndexMinuteChartWorkspace/IndexTechnicalTab`。
3. `DetailChartWorkspace -> mainPrimitives -> TrendChannelPanePrimitive -> viewport/zoom/crosshair`。
4. 四组现有 stock/index daily/minute FastAPI、query service、schema、local capability 和 Lake Reader。
5. 股票 QFQ 九转 assets/checks/jobs/sensors、主要指数分钟技术资产族和 prod serving publisher 模式。

影响面结论：

1. 不修改 `src/platform` 或 `src/operations`，依赖方向保持 `foundation <- biz <- app`。
2. Web 代码不能 import `lake_console/orchestrator`；路径和物理合同必须在 Foundation 独立冻结。
3. Orchestrator 不能 import Web 的 schema、universe service 或 React 类型。
4. `IndexDetailCapabilitiesDto.supportsNineTurn` 当前是 `Literal[False]`，前端 TS 也冻结为 `false`；只能在指数 M5 接入时按目标合同升级。
5. 股票 page-init 已在 M2 增加九转 capability：日线常驻；正式本地 Gold 能力满足时增加 30/60/90/120。

### 4.2 可复用能力

| 现有能力 | 复用方式 |
|---|---|
| `gold_stock_daily_qfq_nineturn` 与四个分钟资产 | 原样作为股票九转事实；不改变公开 key、路径和公式语义 |
| `prod_core_wealth_market_turnover` 发布模式 | 复用“Gold 校验 -> 事务替换 -> read-back”边界，不复用业务 schema |
| `resolve_local_minute_capability` | 复用环境、开关、Lake 和 DuckDB 基础门禁；九转增加正式根和目标目录检查 |
| `IndexDetailUniverseService` | 指数四个九转 endpoint 的唯一产品 allowlist |
| stock/index minute Reader 的分页模式 | 复用 limit+1、日期裁剪、稳定 cursor、5MB 门禁原则 |
| `DetailChartWorkspace.mainPrimitives` | 同时挂趋势和九转；shared workspace 不理解九转公式 |
| `TrendChannelPanePrimitive` | 复用 primitive 生命周期和可见范围测试模式，不复用 autoscale 行为 |
| `useIndexMinuteSeries` | 复用 AbortController、request id、按 code/freq/endDate 缓存思想 |

### 4.3 已发现缺口

1. 现有 stock/index Web 中没有九转 Reader、DTO、endpoint、controller 或 primitive。
2. 股票分钟控制器有 AbortController，但没有独立 request id；九转不能复制这一缺口。
3. `DetailChartWorkspace` 的 chart effect 依赖 `mainPrimitives`；数组身份变化会重建图表。九转实现必须使用稳定 primitive 实例并通过 `setMarkers()` 更新，不能在每次响应时创建新实例。
4. `IndexTechnicalTab` 的九转仍固定显示 `-- / 后续由独立 API 提供`。
5. 指数九转 Gold 资产、正式文件、serving 和日常自动化均不存在。
6. 股票五个资产虽有历史，但两个 sensor 仍为 `STOPPED`；这属于 M6 发布门禁。

### 4.4 `freq` 物理类型门禁结论

2026-08-13 对四个最新正式股票分钟九转文件做了只读复核：

1. `read_parquet(path)` 自动开启 Hive 路径推断时，路径 `freq=30` 会生成 `BIGINT` 分区列并覆盖同名文件列。
2. `read_parquet(path, hive_partitioning=false)` 读取真实 Parquet schema 时，四个频率的 `freq` 均为 `INTEGER`。
3. 真实物理文件、writer 的 `CAST(freq AS INTEGER)` 与 `GOLD_STK_MINS_QFQ_NINETURN_SCHEMA` 一致。

因此不修改现有数据和合同。所有新 Reader、check 和验收 SQL 必须显式使用 `hive_partitioning=false`。

## 5. 目标架构

```text
Dagster Gold
  stock daily + 30/60/90/120m (existing)
  index daily + 5/15/30/60/90/120m (new)
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
2. 现有股票 public function、asset key、schema、path 和测试名称保持不变。
3. 股票与指数 adapter 分别把 `close_qfq`、`close` 映射到 `close_value`。
4. 抽取前后现有股票 golden 输出必须逐行完全相同；不允许复制第二份公式。

### 6.2 股票资产

沿用：

```text
gold_stock_daily_qfq_nineturn
gold_stk_mins_qfq_nineturn_30m
gold_stk_mins_qfq_nineturn_60m
gold_stk_mins_qfq_nineturn_90m
gold_stk_mins_qfq_nineturn_120m
```

日线 schema：

```text
ts_code VARCHAR
trade_date DATE
close_qfq DOUBLE
up_count INTEGER
down_count INTEGER
nine_up_turn VARCHAR nullable
nine_down_turn VARCHAR nullable
```

分钟在日线字段基础上增加 `freq INTEGER` 和 `trade_time TIMESTAMP`。唯一键分别为 `(ts_code, trade_date)` 与 `(ts_code, freq, trade_time)`。

### 6.3 指数资产

新建：

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
2. 分钟分别依赖同频 `silver_major_index_mins_<freq>m`。
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
2. 分钟使用 `cn_major_index_mins_trade_days`，物理输出正式 Silver 实际覆盖代码；当前明确排除 `899050.BJ`，可包含 `000680.SH`。
3. API 不从文件反推产品名单，始终再次执行 Wealth 10-code allowlist。

每个资产对应一个 blocking integrity check，共七个。check 只验证文件、schema、分区、唯一键、值域、源键覆盖和公式版本元数据，不在 check 内重新计算公式。

### 6.4 job、sensor 与历史构建

建议名称：

```text
gold_major_index_daily_nineturn_update_job
gold_major_index_mins_nineturn_update_job
gold_major_index_daily_nineturn_update_job_sensor
gold_major_index_mins_nineturn_update_job_sensor
```

约束：

1. 分钟 job 精确选择六个资产和六个 checks。
2. sensor 以同分区上游 materialization + blocking checks 通过为唯一触发门禁。
3. sensor 初始默认 `STOPPED`；M6 完成自然触发验收后才允许启用。
4. 历史构建使用有界批次、compact seed、逐文件原子提升和 checkpoint；不全历史单 SQL 常驻内存。
5. 本文不授权任何历史写入、动态分区登记或 runless event。

## 7. 日线 PostgreSQL serving

### 7.1 最终表结构

新建两张物理表，不复用旧 Tushare view：

```text
core_serving.equity_qfq_nineturn_daily
core_serving.index_nineturn_daily
```

股票表：

```text
ts_code VARCHAR(16) NOT NULL
trade_date DATE NOT NULL
close_qfq DOUBLE PRECISION NOT NULL
up_count INTEGER NOT NULL
down_count INTEGER NOT NULL
nine_up_turn VARCHAR(2) NULL
nine_down_turn VARCHAR(2) NULL
formula_version SMALLINT NOT NULL
published_at TIMESTAMPTZ NOT NULL
PRIMARY KEY (ts_code, trade_date)
INDEX (trade_date, ts_code)
```

指数表使用 `close DOUBLE PRECISION` 替代 `close_qfq`，其余字段与主键相同。

约束：

1. 表不保存 OHLC、量额、无意义的 nullable `freq` 或页面 marker。
2. lag=4、threshold=9 在 definition/API meta 冻结，不逐行重复。
3. `formula_version` 必须为 1；混合版本分区拒绝发布。
4. 真正创建 migration 前重新读取当前 Alembic head；不得照抄 M0 快照。
5. `lake_raw_writer` 只获得该表 `SELECT, INSERT, DELETE`；不授予 UPDATE、TRUNCATE、建表或角色管理权限。

### 7.2 publisher

新建：

```text
prod_core_stock_daily_qfq_nineturn
prod_core_index_daily_nineturn
```

单分区流程：

1. 读取 Gold 时固定投影并设置 `hive_partitioning=false`。
2. 验证 schema、分区日期、唯一键、值域、formulaVersion、源键覆盖，并逐键比较九转 `close_qfq` 与当前 QFQ 行情 `close`。
3. 在一个 PostgreSQL 事务内按 `trade_date` 删除旧分区。
4. 使用 `execute_values` 有界批量写入，不做 Python 单行 insert。
5. read-back 比较行数、完整键集合和规范化内容 hash。
6. 任一差异 rollback；状态写入失败不得污染已提交的业务表事务。

历史发布实现冻结为：

```text
stock_daily_qfq_nineturn_serving_history.py
stock_daily_qfq_nineturn_serving_history_cli.py
```

1. `plan` 只读扫描准确交易日范围，冻结 Gold/QFQ 两类文件的相对路径、size、mtime、行数和计划指纹；任何源值漂移使 `should_stop=true`。
2. Gold scoped rebuild 和 serving 发布的 `sample` 均仅允许显式选 1～3 个计划内分区；单个 `batch` 最多 20 个分区。Gold 修复单次最多 200 个 batch；serving 单进程最多 10 个 batch，并在进程退出后从 checkpoint 续跑。
3. 每个交易日独立事务并完成 read-back 后，才把业务内容 hash 原子写入 checkpoint。
4. checkpoint 固定在 `/Volumes/datasource/data_lake_staging` 下；续跑前对冻结的全部 Gold/QFQ 文件核对路径、size、mtime，并以 PostgreSQL server cursor 流式验证已完成分区的业务内容 hash；禁止盲跳，也禁止恢复时重新深扫 3,066 日内容。
5. scoped plan 只扫描目标资产族；本轮 daily 修复不得顺带扫描四个分钟资产。
6. scoped rebuild 每个分区单独生成候选、复刻完整 blocking check、备份、原子提升并写 checkpoint；失败只恢复当前未登记分区，已回验分区可续跑。
7. scoped rebuild 的候选、恢复副本和 checkpoint 均位于独立 staging 根；正式 Lake 内不再新增 `_staging` 或 `_quarantine`。
8. plan/sample/batch/resume 代码与隔离测试完成，不构成真实 Gold 修复或生产发布授权。
9. plan 每个分区只消费完整性聚合诊断和 `checked_row_count`，不得调用返回全量 Python rows 的 loader；每 20 个分区关闭并重建 DuckDB 连接。
10. publish 只对本次最多 200 个待发布日执行完整 Gold/QFQ 内容门禁。计划明细只写 JSON 文件；CLI 固定大小摘要，发布进度每个逻辑 batch 一条，最终输出不含完整日期数组。
11. 历史发布 DuckDB 固定 `memory_limit=128MB`、`threads=1`、`preserve_insertion_order=false`。

日常链路独立为：

```text
prod_core_stock_daily_qfq_nineturn_sync_job
prod_core_stock_daily_qfq_nineturn_sync_job_sensor
prod_core_stock_daily_qfq_nineturn_partition_check
```

serving check 使用只读事务对比 Gold 与 PostgreSQL 行数、键和业务内容 hash。sensor 只监听 Gold job 成功且 Gold blocking check 就绪的同分区，初始状态固定 `STOPPED`。

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

股票分钟 bar 路径按现有 QFQ code/year 合同枚举，九转路径按 trade_date 枚举；指数 bar 与九转均按 trade_date 枚举。公共的路径验证、cursor 和最近分区扩展逻辑放在 Foundation 内核，不能从 Biz 复制。

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
5. 指数现有 page-init 合同实现时需要从 1.2.0 升级；在代码完成前，当前 `Literal[False]` 仍是现状事实，不能提前写成已上线。

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
2. Technical Tab 首次打开时，仅对 `nineTurnPeriods` 中的 day/60/30 调用 `ensure`。
3. 为复用图表缓存，摘要请求使用与图表相同的窗口 limit，不单独创建 summary endpoint。
4. production 只请求 day；60/30 显示 `--`，不尝试分钟 URL。
5. local/dev 中已请求的 60/30 可在切图时直接复用。
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

九转卡只显示 day、60、30 三行：

```text
日线  上序 9
60分  下序 6
30分  上序 3
```

映射规则：

1. 使用各响应 `latestMarker`，不在前端扫描历史推导“最近一次九转”。
2. 最新 bar count 1～9 才显示方向和序号。
3. 最新 bar count 0、10+、缺行、未开放或源未就绪都显示 `--`，并由旁侧状态说明原因。
4. Figma 示例数字不是测试金标。
5. 摘要不解释趋势、机会或交易动作。

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

M3-B 执行前复核发现旧 scoped rebuild 会一次性生成并整体提升 3,066 个分区，已改为目标资产窄扫描、1～3 分区 sample、20 分区 batch、单次最多 200 batch、逐分区 checkpoint/resume。经单独批准，Gold 修复与全历史对账已经完成。serving 在发布 1,113 日后因内存事件暂停；根因审计确认 plan 曾逐分区完整装载、publish 恢复时重新深扫全部历史且 CLI 输出超大对象。发布器已改为 DuckDB 128MB/1线程、plan 聚合诊断、20日连接重建、恢复只做源文件元数据核对与 Prod 流式 hash、待发布日期深度门禁及逐 batch 固定大小输出；每日独立事务与 checkpoint 语义不变。修正后先通过全历史 plan 与 1,113 日 checkpoint 只读内存验收，再以十个独立短进程发布余下 1,953 日。最终 checkpoint 为 3,066/3,066，生产表为 11,638,636 行，日期缺失/额外/逐日行数不符均为 0；十个进程最大 RSS 为 209～249MiB。两个 sensor 仍不得启用。

### 15.4 M3-C：股票页面完整验收

Gold 修复和 serving 历史发布后，完成生产日线、四个本地分钟、三个禁用周期、全部局部状态、缓存竞态、浏览器和视觉验收。M2 已包含页面接入，因此不重复建第二套控制器。

### 15.5 M4：指数资产、serving 与 API

```text
lake_console/orchestrator/src/orchestrator/defs/nineturn_formula.py
lake_console/orchestrator/src/orchestrator/defs/major_index_nineturn.py
lake_console/orchestrator/src/orchestrator/defs/assets/major_index_nineturn.py
lake_console/orchestrator/src/orchestrator/defs/checks/major_index_nineturn_checks.py
lake_console/orchestrator/src/orchestrator/defs/jobs/major_index_nineturn_update.py
lake_console/orchestrator/src/orchestrator/defs/sensors/major_index_nineturn_sensor.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/major_index_nineturn_history.py
lake_console/orchestrator/src/orchestrator/defs/assets/index_daily_nineturn_prod_core.py
src/foundation/models/core_serving/index_nineturn_daily.py
src/biz/api/wealth/market/index_detail_nine_turn.py
```

实际拆文件时可以按仓库现有 daily/minute 命名规范细分，但不得合并成无法独立测试的单个大文件。

### 15.6 M5：指数页面接入

修改现有 index page-init capability、index page/controller、两类 chart adapter、`IndexTechnicalTab` 和测试。不得复制 `NineTurnMarkerPrimitive`、series registry 或 API DTO。

## 16. 测试矩阵

### 16.1 公式与资产

1. count 0、1～9、10+。
2. equal 重置、UP→DOWN、DOWN→UP。
3. 前四根历史不足、跨日、跨年、分钟跨日延续。
4. compact seed、缺旧 seed 精确 fallback、新标的从 0 开始。
5. 指数日线一个、分钟六个资产正向，1 分钟资产不存在的负向。
6. schema、分区、唯一键、源键覆盖、错误代码/频率、validate-then-promote。
7. 物理 11-code 与产品 10-code 边界；`000680.SH` 只允许物理存在。

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

### 16.3 前端

1. shared registry 按完整 key 缓存，AbortController + request id 防串标。
2. 支持周期发一次请求；不支持周期零请求。
3. READY/EMPTY/SOURCE_EMPTY/PARTIAL/ERROR/FORBIDDEN/UNSUPPORTED。
4. 九转失败时 K 线、MA/BOLL、MACD、KDJ、趋势、权重和右栏其它项仍在。
5. 只画 1～9；10+ 不重复画 9。
6. marker 时间键、方向锚点、18×18、8px、极值、密集序列和分钟时区。
7. stable primitive 更新不改变 `dataKey`、120 根默认视窗或当前缩放范围。
8. 上证日线趋势 + 九转双 primitive attach/detach。
9. Index Technical production 只请求 day；local 复用 day/60/30 缓存。

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

## 18. 发布顺序与回滚

上线顺序：

1. migration 和 ORM。
2. Gold/serving publisher 与只读回验。
3. 日线 API，保持前端 capability false。
4. shared primitive 和股票接入。
5. 指数资产、serving、API 和页面 capability。
6. 自然触发、freshness、性能和视觉验收后再启用 sensor。

回滚：

1. 前端先将 page-init `nineTurnPeriods` 置空并停止请求。
2. 回滚 API/router 不删除事实表或 Lake 文件。
3. publisher 停止调度，保留最后成功 serving 分区供审计。
4. 不用 Tushare、Mock 或客户端计算作为应急替代。

## 19. M1 退出评估

M1 已完成：

1. M0 正式收口，无未解释的 P0 产品或架构冲突。
2. 代码影响面、依赖边界、复用点和当前缺口已审计。
3. 股票/指数资产、schema、路径、分区、check、job、sensor 和 universe 已冻结。
4. 两张 serving 表、publisher、查询基表和无 fallback 边界已冻结。
5. 四个 endpoint、参数、DTO、状态、异常、cursor 和性能预算已冻结。
6. 前端 registry、capability、primitive 几何、右栏摘要和状态机已冻结。
7. `freq BIGINT` 疑点已证伪，正式物理类型确认是 INTEGER。

M3-B 已完成，后续仍未完成的运行与发布项：

1. migration 已在生产执行；目标表最终只读确认有 3,066 个交易日、11,638,636 行，与冻结计划逐日行数一致，全历史发布已完成。
2. 45,442 行 close 漂移对应的 Gold scoped rebuild 已完成；11,638,636 行全历史键、价格、计数和信号差异均为 0。
3. 股票 serving sample、余下 1,953 日历史发布和最终全量对账均已完成。指数七资产与正式历史仍未建设。
4. Gold sensor 在执行前发现实际为 RUNNING，审计确认近 10 个 tick 均 SKIPPED、无并发 run 后已停止；serving sensor 未启用。两者当前均不得启用。
5. Gold 修复和正式发布前置条件已完成；下一步必须用当前生产 serving 完成真实 API 与浏览器截图验收，不得用 SQLite fixture、本地 Lake 冒充生产就绪。

## 20. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-08-13 | 完成 M0 收口、CodeGraph/current code 审计、物理 freq 复核，冻结资产、serving、DTO、Reader、前端与验收设计 | Codex |
| v1.1 | 2026-08-13 | 同步 M2 实现事实、真实 Lake 四频率只读验收、生产权限边界及未执行 migration/历史发布/浏览器验收项 | Codex |
| v1.2 | 2026-08-13 | 收口 M3-A/M3-B：生产空表和 close 漂移事实、独立 staging、20 日批次 checkpoint、serving blocking check 与 STOPPED 日常链路 | Codex |
| v1.3 | 2026-08-13 | 同步 Gold 修复完成、serving 893 日部分发布、内存暂停与 256MB/1线程/10批次恢复门禁 | Codex |
| v1.4 | 2026-08-13 | 同步 serving 1,113 日检查点；收口 plan/resume/CLI 内存与输出放大根因，冻结 128MB、聚合 plan、源元数据核对、Prod 流式 hash 和逐 batch 摘要门禁 | Codex |
| v1.5 | 2026-08-13 | M3-B 完成：以十个有界短进程发布余下 1,953 日，生产表 3,066 日、11,638,636 行逐日对账通过，峰值 RSS 最高约 249MiB；M3-C 与自然日常链路仍待验收 | Codex |
