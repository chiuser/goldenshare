# Dagster `dc_index` / `dc_member` / `dc_daily` 数据集接入技术方案

> 状态：M3 Raw 写入能力、M4 Raw Dagster definition、M5 Silver writer/asset/check 已完成；M6+尚未开始。M4 sensor 仍为 `STOPPED`，M5 只完成临时 lake 联调，未启用 Silver sensor，不写正式数据湖、Dagster materialization 或 check event。
>
> 依据：新增数据集接入模板、`lake_console/orchestrator/CODING_STANDARDS.md`、
> `dagster-data-pipeline-performance-governance.md`、现有 `index_daily` / `stk_nineturn`
> 实现，以及 2026-07-14 对 prod DB 和 Tushare 的只读审计。

## M3 实施状态

M3 已完成 Raw-only 写入能力：

- `defs/tushare_request_policy.py` 提供共享有界分页、重试、限流、请求/时间预算、跨页主键重复和首请求前代码数预算保护。
- `defs/assets/dc_board.py` 提供 `dc_index` 三类型合并、`dc_daily` 日期分页、`dc_member` 单代码分页和 DuckDB staging/回读 schema/行数校验/原子替换；无 Dagster decorator。
- `defs/bootstrap/dc_board_bootstrap.py` 提供 Prod `dc_member` named cursor + `fetchmany` 只读流式导出；不使用写资源、不执行 `fetchall`。
- `ProdPostgresResource.connect_readonly_transaction()` 提供只读、非 autocommit、退出 rollback 的独立 Bootstrap 连接语义，既有 `connect()` 保持不变。
- 测试覆盖策略边界、三类 Raw writer、失败不覆盖、字段/日期/主键校验、Prod chunk 边界和 rollback-only 约束。

性能样本：`/private/tmp/dc_board_m3_performance_20260714.json`。1,022 个 fake `dc_member` 代码请求为 1,022 次、1,022 页、0 retry，source/written 均为 1,022，DuckDB + Parquet staging 耗时约 394 ms；真实 Tushare 间隔仍由 M1C 固化的 `0.13s` 和 1,200/300s 预算控制。

M3 明确不新增 active Dagster asset/check/job/sensor，不执行正式 bootstrap，不写正式湖或 Dagster DB。

## M4 实施状态

M4 已完成 Raw Dagster 接入，但保持 sensor 默认关闭、未执行正式同步：

- `defs/assets/dc_board_raw.py` 创建三个单分区 Raw asset；`dc_member` 在 asset run 内从目标日 `raw_dc_index` 与最近可用 member 分区规划去重后的候选板块代码，缺历史基线或超过请求预算时在 Tushare 请求前 fail closed。
- `defs/checks/dc_board_checks.py` 创建三个显式绑定 `cn_a_index_trade_days` 的合并核心 blocking check；每次只接受一个 partition，并以 DuckDB set-based SQL 检查文件、schema、行数、日期、主键和身份字段。
- `defs/asset_guards/dc_board_lake_readiness.py` 创建内存态 batch readiness；单个 sensor tick 最近 10 个 expected dates 共用一个 DuckDB connection，不读取 Dagster event history、Prod DB 或 Tushare。
- `defs/jobs/dc_board.py` 创建三个只选择对应 Raw asset 与其 check 的 job；`defs/sensors/dc_board_sensor.py` 创建三个 `STOPPED` sensor，每 tick 最多一个 first-not-ready run request，并使用统一 run key/cursor builder。
- M4 本地验证包含完整 M3 回归、定义加载、候选 planner、core check、10 日 readiness、sensor 和静态门禁，共 `112 passed`；未运行 `dg launch`、未启动 daemon/webserver、未写正式 lake 或 Dagster DB。

M4 当前没有正式数据可供 readiness 触发是预期状态；M4 的三个 Raw sensor 继续保持 `STOPPED`，M5 不增加自动化入口，也不执行正式 Bootstrap。

## 1. 目标与范围

将东方财富板块三类事实纳入 Dagster 数据湖：

| 数据集 | 业务含义 | Tushare 接口 | Raw | Silver |
| --- | --- | --- | --- | --- |
| `dc_index` | 每日板块指数/板块概览事实 | `dc_index` | 源站返回镜像 | 规范化板块指数事实 |
| `dc_member` | 每日板块与成分股关系 | Bootstrap：prod DB；日常：`dc_member` | 统一 Raw schema，来源按阶段记录 | 规范化板块成员事实 |
| `dc_daily` | 每日板块行情 | `dc_daily` | 源站返回镜像 | 保留 `category` 的规范化行情事实 |

本专项包含：

1. `dc_index` / `dc_daily` 全历史从 Tushare bootstrap 到按 `trade_date` 分区的 Raw 文件。
2. `dc_member` 历史 bootstrap 从 prod DB 只读导出到同一 Raw 格式；日常再从 Tushare 获取最新交易日 Raw。
3. Raw 到 Silver 的类型、日期、代码、主键和交易日清洗。
4. 每个资产一个合并后的核心 blocking check，保持 Dagster check event 颗粒度可控。
5. Raw/Silver 的 job、sensor、cursor、run key、catalog 和测试设计。
6. bootstrap 前后的 Tushare 请求审计、prod 对照和事件验收。

本专项不包含：

- 直接改写现有 `raw_index_daily` / `silver_index_daily` 资产。
- 把板块关系强行并入 `silver_index_daily`。
- 在每日 sensor 热路径扫描 Dagster event history。
- 为跨数据集关系新增常驻 summary asset 或数据库表。
- 将 prod/source 的历史差异静默带入 Raw。

## 2. 已冻结的关键口径

### 2.1 日期和分区

- 三个资产均采用 `trade_date=YYYY-MM-DD` 的物理目录和 Dagster partition。
- 复用现有 `cn_a_index_trade_days` dynamic partition set。它是指数/板块资产族的交易日分区，不新建一套同义 partition set。
- `dc_index`、`dc_member` 的有效历史起点为 `2024-12-20`。
- `dc_daily` 的有效历史起点为 `2024-01-02`，这是 2024-01-01 之后 SSE 首个开市日。
- 日常 expected date 只取 SSE `is_open=1` 日期。Tushare 在周末可能返回 `dc_index` 行，但周末不进入本资产族的日常 partition domain；这属于明确的业务范围限制，不是 Raw 内部静默过滤。
- 传给 Tushare 的日期使用接口要求的 `YYYYMMDD`，Raw 文件中的 `trade_date` 保留源字段字符串，Silver 文件标准化为 `DATE`。

### 2.2 Raw 与 Silver 的边界

Raw 的定义是：在本专项明确的交易日 partition domain 内，保留 Tushare 请求返回的业务字段和源语义，不做当前板块池裁剪，不把 `category`、`idx_type` 或旧代码映射隐藏掉。

Silver 的定义是：从同日 Raw 生成可供下游查询的规范事实：

- trim 字符串、统一代码大写、日期转 `DATE`。
- 只保留 expected SSE open date。
- 按正式业务主键去重；同主键不同业务值不静默覆盖，必须 fail closed。
- 校验板块类型、分类、代码后缀和数值字段域。
- `dc_daily` 的 `category` 必须保留，并且是业务主键的一部分，不能压缩成 `(ts_code, trade_date)`。

Raw 不增加 `source_method`、bootstrap 路径、旧湖路径等业务列；来源、请求参数、页数、行数、对账结果只写 definition/materialization metadata。

### 2.3 来源策略

- `dc_index` / `dc_daily` 的 Bootstrap 和日常更新正式来源统一是 Tushare。
- `dc_member` 的历史 Bootstrap 正式来源改为 prod DB 只读导出；日常更新正式来源仍为 Tushare。两阶段使用完全相同的 Raw schema、分区目录和主键，不形成两套物理格式。
- prod DB 不是静默复制：Bootstrap 前必须完成日期覆盖、字段、主键、代码格式、行数和与 Tushare 样本的只读对照；来源差异写入 Bootstrap 审计报告和 materialization metadata，不增加业务字段。
- `dc_member` 历史 Bootstrap 不使用 Tushare 全市场分页，而是从 prod DB 只读导出；日常更新不再使用全市场 `limit/offset`，改为按交易日和板块代码请求。全市场接口只允许作为代码发现/审计辅助，不得作为成员事实输入。
- 这样既避免把 prod 已知的 2,124 条 `dc_daily` 分类错误复制进新 Raw，也避免 `dc_member` 全市场分页的重复和漏数问题；历史成员事实的来源差异通过 metadata 和 Bootstrap 审计报告显式保留。

## 3. 审计结论与数据风险

### 3.1 prod DB 总体规模

只读审计时间为 2026-07-14，prod 最大数据日期为 2026-07-13：

| 表 | 行数 | 日期数 | 日期范围 |
| --- | ---: | ---: | --- |
| `raw_tushare.dc_daily` | 600,198 | 610 | 2024-01-02 至 2026-07-13 |
| `raw_tushare.dc_index` | 244,750 | 380 | 2024-12-20 至 2026-07-13 |
| `raw_tushare.dc_member` | 25,326,662 | 376 | 2024-12-20 至 2026-07-13 |

Tushare SSE open calendar 对应：

- `dc_daily`：610 个 expected open dates。
- `dc_index` / `dc_member`：从 2024-12-20 起 376 个 expected open dates。

### 3.2 已确认的 prod/source 差异

1. `dc_daily` 在 2025-05-30 之前/期间发现固定的历史错误：
   - 12 个板块代码：`BK0425.DC`、`BK0429.DC`、`BK0447.DC`、`BK0470.DC`、
     `BK0477.DC`、`BK0480.DC`、`BK0485.DC`、`BK0729.DC`、`BK0730.DC`、
     `BK0733.DC`、`BK1017.DC`、`BK1029.DC`。
   - 177 个日期，共 2,124 行 prod-only 数据。
   - prod 将这些行标成 `概念板块`，Tushare 对应事实为 `行业板块`；source-only 为 0。
   - 这 2,124 行不得直接复制到最终 Raw，必须以 Tushare 对应结果替换或在 bootstrap 阶段明确记录为拒绝并修正。

2. `dc_index` 存在周末源数据差异：
   - 2026-03-28 的 Tushare 样本为 1,010 行，prod 为 960 行，prod 少 50 行。
   - 由于日常 partition domain 是 SSE open dates，周末不进入本专项的生产分区；但如果 bootstrap 导出周末数据，必须先排除在 domain 外，不能把差异混入开市日事实。

3. 三个数据集不是任意历史日期都能做集合相等：
   - `dc_member` 与 `dc_index` 的板块日期关系在样本中成立，但 `dc_index` 某些板块没有成员行，空成员集合可能是合法事实。
   - `dc_daily` 与 `dc_index` 在早期历史存在 132,035 个 daily-only board/date 和 6,845 个 index-only board/date；这不是可以直接用“缺失即失败”解释的单表契约。
   - 12 个代码的 2,124 条 category/type 不一致是明确数据错误，必须在 bootstrap 修复；其余跨表差异作为离线审计报告，不进入每日 sensor 热路径。

## 4. Tushare 源站契约

### 4.1 `dc_index`

- 必填业务参数：`idx_type`。
- 本专项每天固定请求三个类型：`行业板块`、`概念板块`、`地域板块`。
- 日期参数：`trade_date`。
- 分页参数：`limit`、`offset`；接口文档单次上限 5,000。
- 显式字段固定为：
  `ts_code,trade_date,name,leading,leading_code,pct_change,leading_pct,total_mv,turnover_rate,up_num,down_num,idx_type,level`。
- 三个类型请求的结果合并为一个交易日 Raw partition；单个类型为空不直接失败，因为 2024-12-20 只有概念类型有数据；三个类型合计为空才触发空结果保护。

### 4.2 `dc_member`

- 参数：`trade_date` 为主；`ts_code`、`con_code` 可用于校验或备用请求。
- 显式字段固定为：`trade_date,ts_code,con_code,name`。
- M1 真实 `TushareResource.call` 测试否决了“按交易日全市场请求 + 原生分页”作为正式来源：2026-07-13 返回 19 页、92,191 行，其中 374 行是跨页重复；对 20 个板块与按 `ts_code` 请求交叉核验时，`BK0552.DC` 全市场分页少 96 行。
- Bootstrap 不调用 `dc_member` Tushare 历史全量接口；日常按“交易日 + `ts_code`”请求是目前已验证的完整性方向，但 2026-07-13 观察到 1,023 个板块，意味着约 1,023 次/交易日；逗号拼接多个 `ts_code` 实测返回 0 行，不能用代码批量请求降低量级。因此日常代码循环仍必须先完成独立的请求量/配额/耗时评估，不能因为 Bootstrap 改用 prod 就跳过日常性能门禁。
- `tushareMCP` 包装层没有暴露 `limit/offset` 参数，不能把 MCP 一次返回约 8,000 行当作分页行为证明；本结论以工程 `TushareResource.call` 的原生分页实测为准。
- 分页结束条件只能由页响应和 `offset` 进展决定，不能只依赖“返回行数小于 limit”，并要检查页间主键重复。

### 4.3 `dc_daily`

- 主请求：`trade_date`；不把 `idx_type` 作为三个独立生产请求，因为接口按日期可以返回全部分类。
- 显式字段固定为：
  `ts_code,trade_date,close,open,high,low,change,pct_change,vol,amount,swing,turnover_rate,category`。
- 分页上限 2,000；按日期循环并持续分页。
- `category` 是源字段、规范字段和主键字段，允许值为 `行业板块`、`概念板块`、`地域板块`。
- SSE open date 上全量返回 0 行直接 fail closed；周末不在 expected domain，不能用周末空结果作为业务失败依据。

## 5. 资产拓扑设计

### 5.1 资产命名与文件布局

建议正式 asset key：

| 层 | `dc_index` | `dc_member` | `dc_daily` |
| --- | --- | --- | --- |
| Raw | `raw_tushare_dc_index` | `raw_tushare_dc_member` | `raw_tushare_dc_daily` |
| Silver | `silver_dc_index` | `silver_dc_member` | `silver_dc_daily` |

建议物理布局：

```text
raw/board/dc_index/trade_date=YYYY-MM-DD/part-000.parquet
raw/board/dc_member/trade_date=YYYY-MM-DD/part-000.parquet
raw/board/dc_daily/trade_date=YYYY-MM-DD/part-000.parquet
silver/board/dc_index/trade_date=YYYY-MM-DD/part-000.parquet
silver/board/dc_member/trade_date=YYYY-MM-DD/part-000.parquet
silver/board/dc_daily/trade_date=YYYY-MM-DD/part-000.parquet
```

所有文件以临时路径写入并原子 rename；失败不覆盖已有正式 partition。

`raw_tushare_dc_member` 的 asset key 和物理路径保持不变；这里的 `tushare` 表示数据集/API 契约族，不表示每个历史分区都必须由 Tushare 直接生成。每个分区必须通过 materialization metadata 标明 `bootstrap_source=prod_db_readonly_export` 或 `daily_source=tushare_api_by_ts_code`。

### 5.2 依赖关系

- 每个 Silver 资产只依赖同日对应 Raw 资产。
- `silver_dc_member` 不把 `silver_dc_index` 作为硬依赖；成员为空可能是源事实，不应因为跨表缺行阻断。
- `silver_dc_daily` 不要求与 `silver_dc_index` 做集合相等；两套接口在历史覆盖和分类语义上已实测不完全相同。
- 三者的板块关系、一致性和异常统计由离线 audit 工具完成，不进入 sensor hot path。

### 5.3 Job、sensor 与 cursor

建议每个 API/层级独立 job 和 sensor，避免一个 API 失败拖住其他 API，也避免多资产单 run 造成 check partition 归属歧义：

```text
raw_tushare_dc_index_update_job + raw_tushare_dc_index_update_job_sensor
raw_tushare_dc_member_update_job + raw_tushare_dc_member_update_job_sensor
raw_tushare_dc_daily_update_job + raw_tushare_dc_daily_update_job_sensor
silver_dc_index_update_job + silver_dc_index_update_job_sensor
silver_dc_member_update_job + silver_dc_member_update_job_sensor
silver_dc_daily_update_job + silver_dc_daily_update_job_sensor
```

每次 sensor：

- 只检查最近 10 个 expected dates。
- 只选择最早 first-not-ready 日期，最多返回 1 个 run request。
- 不读 Dagster event history；Raw/Silver readiness 通过一次 DuckDB batch 文件检查构建。
- 同一 asset 的正式 run 只带一个 `partition_key`，避免一个 check result 归属多个分区。
- run request 必须走 `build_run_request`；run key 必须走 `build_asset_update_run_key`；cursor 必须走 `build_sensor_cursor`。
- 传给 cursor 的只是一条 frontier、阻断组件、页数/行数/耗时摘要，不塞逐行明细。

Bootstrap 是独立人工维护工具，不接 sensor、schedule 或 AutomationCondition；bootstrap 完成后才执行有界的 event 验收/补录。

## 6. Check 设计

用户已确定：每个资产只保留一个核心 blocking check，将必要规则合并为一个 partitioned `AssetCheckResult`。这与新增数据集通用模板“一个 check 验证一个属性”的默认建议不同，是本专项为降低 Dagster DB 增量压力作出的明确例外；必须用 `failed_rules` 结构化 metadata 保持可诊断性。

六个正式 check：

```text
raw_tushare_dc_index_core_check
raw_tushare_dc_member_core_check
raw_tushare_dc_daily_core_check
silver_dc_index_core_check
silver_dc_member_core_check
silver_dc_daily_core_check
```

每个 check 必须：

1. 显式绑定 `partitions_def=cn_a_index_trade_days`。
2. 只检查当前 partition 的文件，不查历史 event。
3. 通过 set-based DuckDB SQL 检查：文件/行数、分区日期、业务主键非空唯一、数据集专属身份字段。
4. 失败时返回：`failed_rules`、每条规则的 `reason_code`、检查行数、失败数量、少量样本和文件路径。
5. 正式实现使用 `build_check_metadata(...)`，不裸写 metadata key。

规则映射：

| 资产 | 共同规则 | 数据集专属规则 |
| --- | --- | --- |
| `dc_index` | 文件存在、行数>0、trade_date 等于 partition、`(ts_code,trade_date)` 非空唯一 | `.DC` 代码、`idx_type` 三值、指标数值域 |
| `dc_member` | 文件存在、行数>0、trade_date 等于 partition、`(trade_date,ts_code,con_code)` 非空唯一 | 板块/成分代码后缀、成分代码格式 |
| `dc_daily` | 文件存在、行数>0、trade_date 等于 partition、`(ts_code,trade_date,category)` 非空唯一 | `category` 三值、`.DC` 代码、OHLC/成交量字段域 |
| Silver 三者 | 同 Raw 规则 | 日期为 `DATE`、不含非交易日、清洗后主键保持唯一 |

分页完整性、源行数/写入行数对账、空结果保护、请求量和耗时不拆成额外 Dagster check；它们属于 asset 写入前置门禁和 materialization metadata。这样既不丢失诊断，也不把每个执行事实扩成多条历史 check event。

## 7. Bootstrap 方案

### 7.1 顺序

1. 从 SSE expected open dates 生成待处理 partition 清单；不抓取周末分区。
2. `dc_index` / `dc_daily` 通过 Tushare fetcher 按交易日抓取到 staging；字段白名单固定，禁止隐式默认字段。
3. `dc_member` 从 prod DB 只读导出到 staging；按交易日流式读取 `raw_tushare.dc_member` 的四个正式字段，不使用写资源，不把 2,500 万行一次性装入 Python。
4. 对三类 staging 做字段、日期、主键、空结果、源行数/写入行数和 partition 范围检查；`dc_member` Bootstrap 额外检查 prod 覆盖日期和 Tushare 样本对照。
5. 通过后按交易日原子 promote 到 Raw，metadata 写明每个分区的来源和对账摘要。
6. 从 Raw 生成 Silver，逐分区写入；Silver 不区分 Bootstrap 和日常来源。
7. 只读验收文件、跨资产关系和下游查询所需字段。
8. 最后补全成功分区 materialization；只为最近 20 个交易日写 check event。事件补录失败不得回滚业务 parquet。

### 7.2 Bootstrap 安全原则

- 不在旧 Raw 文件上就地修补；`dc_index` / `dc_daily` 从 Tushare staging 生成，`dc_member` Bootstrap 从 prod 只读 staging 生成，日常从 Tushare staging 生成。
- 不把 prod 的错误分类复制到 Raw。
- 任何空结果、分页不完整、主键重复、日期越界、源/写入行数不一致都 fail closed；`dc_member` 单个板块返回空行只记录为空板块，全部候选代码均为空才触发空结果保护。
- `dc_member` prod Bootstrap 未完成 source audit 和 Tushare 样本 reconciliation 时，不能标记为正式 ready。

### 7.3 `dc_member` Bootstrap 具体流程

```text
SSE open dates
  -> ProdPostgresResource(read-only)
  -> 按 trade_date 流式导出临时 staging
  -> schema/date/key/code/row-count 校验
  -> Tushare 代码级样本对照
  -> 原子 promote raw/board/dc_member/trade_date=...
```

- 只使用现有 `ProdPostgresResource`，连接必须是 read-only transaction；为支持 server-side cursor，autocommit 必须关闭，并在结束时 rollback 只读事务；禁止使用 `ProdPostgresWriteResource`。
- SQL 只投影 `trade_date,ts_code,con_code,name`，按 `trade_date` 分批；不使用 `SELECT *`，不把 prod 表直接注册成 Dagster asset。
- 每个日期必须记录 `source_row_count`、`written_row_count`、`duplicate_key_count`、`invalid_code_count`、`elapsed_ms` 和 `source_method=prod_db_readonly_export`。
- prod 缺 expected 日期、主键重复、日期越界、代码格式非法或源/写入行数不一致时，整日 fail closed，不生成正式 Raw 文件。
- 选择起始日、2025-05-30、最近交易日和随机日期，从 prod 的板块代码集合中确定性抽取每日至多 20 个代码，用 Tushare MCP `dc_member(trade_date, ts_code)` 显式请求 `trade_date,ts_code,con_code,name` 做有限样本对照；本次共 69 个请求，69 个行数和四字段集合一致，差异仍只进入审计报告，不把不可靠的 Tushare 全市场分页当作全集基准。报告：`/private/tmp/dc_board_m1b_prod_bootstrap_reconciliation_20260714.json`。

### 7.4 `dc_member` 日常 Tushare 流程

- 当前交易日的候选板块代码集合取 `dc_index` 当日三类代码与最近一个已完成 Raw `dc_member` 分区代码的并集，避免仅依赖 `dc_index` 的 1,022 个代码而漏掉 member-only 代码。
- 每个 `ts_code` 单独请求 `dc_member(trade_date, ts_code)`，页大小不超过 5,000；逗号拼接多个代码已实测返回空结果，禁止批量拼接。
- 单个代码返回空行是允许的源事实；所有候选代码均为空才触发空结果保护。每行必须回验请求日期和请求板块代码。
- 成功条件是所有代码请求完成、请求行数总和等于 staging 行数、业务主键唯一、没有失败代码；metadata 写 `source_method=tushare_api_by_ts_code`、`request_count`、`empty_code_count`、`source_row_count` 和 `written_row_count`。
- 该请求链路只在 asset run 中执行，不在 sensor 热路径执行；sensor 只做最近 10 日文件 readiness。

## 8. 性能门禁

### 8.1 日常请求预算

按当前规模估算：

| 数据集 | 每个交易日请求模型 | 预估请求量 |
| --- | --- | ---: |
| `dc_index` | 3 个 `idx_type`，每个按页 | 通常 3 页级请求，超限按页增加 |
| `dc_daily` | 按日期分页 | 当前约 1 页，严格按 2,000 上限分页 |
| `dc_member` Bootstrap | prod DB 只读、按交易日流式导出 | 不产生 Tushare 历史请求；必须通过 prod 覆盖、主键和行数审计 |
| `dc_member` 日常 | 每个候选 `ts_code` 单独请求，单代码分页 | 当前约 1,023 次/日；固定最小间隔 `0.13s`、最多 1,200 次、最多 300s，超限整日 fail-closed |

不接受的情况：

- 未设置低于 Tushare 真实频率上限的请求节奏；当前接口已实测拒绝超过 `500 requests/minute` 的连续请求。
- 没有 bounded retry/backoff、失败代码清单和整日 fail-closed 规则就进入正式 Raw。
- `dc_member` 日常代码循环超过 M1C 固化的请求/耗时预算，或未完成失败代码与空结果对账。
- sensor 每个日期逐个调用 Dagster readiness 或 event history。
- 每个 check 读取全历史文件或跨日期 Python 行循环。
- 一个 partition run 读取/写入整个历史范围。

### 8.2 时间、事务和内存

- 每个 Dagster run 只处理一个 `trade_date`；每个文件通过 staging + 原子 rename 提交。
- Tushare 分页和 prod cursor 在内存中只保留当前 partition 的有限行集合；Bootstrap 使用日期批次和 DuckDB set-based SQL，禁止一次性 `fetchall` 全部 2,500 万成员行。
- 每次写入记录 `page_count`、`source_row_count`、`written_row_count`、`duplicate_key_count`、`elapsed_ms`、`request_count`。
- source 请求和文件写入的单分区耗时超过预算时，run fail closed，不进入重试风暴；cursor 只显示摘要，详细报告写临时审计文件。
- sensor 每 tick 最多 1 个 run request，readiness 只读取最近 10 个日期的目标文件。

## 9. 分阶段推进

### P0：方案与源契约冻结（已完成）

- 完成字段、起点、主键、路径、分区、来源和 check 口径。
- 已用实际 `TushareResource.call` 完成 `dc_member` 一日分页测试；结果见第 12 节。
- `limit/offset` 的接口行为已确认，但全市场分页不满足完整性门禁；因此不进入后续 Raw 实现，先做成员抓取策略评估。

### P1：dc_member 来源与性能门禁（M1B、M1C 均已通过）

- **M1B：prod Bootstrap 只读验证（已通过）。** 已审计 prod 的日期覆盖、字段投影、主键唯一性、代码格式和按日期流式读取耗时；并按起始日、`2025-05-30`、最新日和中间样本日，从 prod 选取有限板块代码，用 Tushare MCP 的 `trade_date + ts_code` 请求做四字段对照，69/69 个样本请求行数和行集合一致。本轮不写正式湖、不写 staging、不写 Dagster，因此不虚报 written rows，使用聚合行数与抽样流式行数对账验证读取路径。
- **M1C：日常 Tushare 代码循环验证（整改后通过）。** 原始无界循环已在真实接口上触发 `500次/分钟` 限流，随后新增独立的 `defs/tushare_request_policy.py`，不改变既有 `TushareResource.call()` 默认行为，提供 `0.13s` 最小间隔、最多 3 次重试、`1/2/4s` 指数退避（单次最多 `8s`）、每分区最多 `1,200` 次请求和 `300s` 总耗时预算。整改后的只读 profiling 覆盖 4 个日期、每日期 80 个确定性板块代码，分页共 323 个请求，其中 3 次重试均恢复；成功/空结果/失败/未尝试代码分别为 `286/37/0/0`，多页代码 `0`，日期/代码范围、列契约、空主键、重复业务主键错误均为 `0`。请求耗时 p50 `46.112ms`、p95 `136.134ms`、最大 `1,382.451ms`；最近交易日 `2026-07-13` 有 `1,022` 个候选代码，硬下限约 `122.64s`，必须按分钟级任务预算规划，不能当作秒级同步。
- 策略结果是整日 fail-closed：单代码空结果是合法源事实；任何不可重试错误、重试耗尽、分页未完成、未尝试代码、请求数或总耗时超限，均不得写入该交易日 Raw 分区，并必须输出失败代码清单和预算原因。
- M1B 与整改后的 M1C 均通过正确性、配额和性能门禁，可以进入 schema、路径 helper、partition model、catalog entry、中文名映射和后续 Raw 设计；正式 writer 仍必须复用该策略并保留单日真实请求/耗时回归。

### P2：Contract / Catalog / Path 基础

- 新增三类 schema、字段常量、路径 helper、partition model、catalog entry、中文名映射和来源 metadata contract。
- `dc_index` / `dc_daily` 的 Tushare source contract 与 `dc_member` 的 prod-bootstrap/Tushare-daily 双来源 contract 必须分别表达；不能把 `dc_member` 的历史分区标记为 Tushare 直接抓取。

### P3：Raw bootstrap 与 writer

- `dc_index` / `dc_daily` 使用 Tushare staging；`dc_member` 使用 `ProdPostgresResource` 只读、按交易日流式 staging。
- 三者共用字段、日期、主键、空结果和原子 promote 规则；`dc_member` 额外记录 prod source audit 和有限 Tushare 样本 reconciliation。
- 该阶段不在 sensor 热路径访问 prod DB；Bootstrap 是独立人工维护入口。

### P4：Raw 日常接入（已完成）

- 已新增三个 Raw asset、三个 job、三个 sensor 和 batch readiness helper，实际文件见 M4 实施状态。
- `dc_index` / `dc_daily` 按 Tushare 日期请求；`dc_member` 按 M1C 通过的候选代码逐个请求。
- 单日、分页、空结果、失败不覆盖和最近 10 日 readiness 已用本地临时数据覆盖；正式单日同步和全量 Bootstrap 留到 M7。

M4 的进入 M5 条件已满足：sensor 每 tick 最多提交一个 first-not-ready 分区，不读 Dagster event history，默认状态仍为 `STOPPED`，M3 writer/static gate 未回退。

### P5：Silver（已完成）

- `defs/assets/dc_board_silver.py` 提供三个 `trade_date` 分区 Silver asset 和 writer。输入只取同日 Raw 与 SSE 交易日文件；日期转 `DATE`、代码 trim/uppercase、业务字段保留、非法行 fail-closed、同业务主键完全重复去重、同主键不同业务值拒绝。
- Silver writer 使用 DuckDB set-based SQL，输出先写唯一临时 Parquet，回读 schema/行数通过后才 `os.replace`；校验失败不覆盖已有目标文件。`dc_daily.category` 保留并继续参与 `(ts_code, trade_date, category)` 主键。
- `defs/checks/dc_board_silver_checks.py` 提供三个显式绑定 `cn_a_index_trade_days` 的单分区 blocking core check。check 只扫描当前 Silver 文件，检查文件/行数、schema、分区日期、业务主键非空唯一、数据集身份字段和数值域，并通过 `failed_rules`/`reason_code`/有限样本表达失败原因。
- Silver 资产只依赖对应同日 Raw，不把 `dc_index`、`dc_member`、`dc_daily` 的历史非等集关系变成日常硬 gate；本阶段不新增 Silver job/sensor，不接入 Dagster event history，不启用任何 sensor。
- M3/M4/M5 scoped suite 共 `123 passed`；定义加载可见三个 Silver asset 和三个 Silver check。验证没有运行 `dg launch`，没有启动 daemon/webserver，没有写正式湖或 Dagster DB。
- 临时性能样本 `/private/tmp/dc_board_m5_performance_20260714.json` 使用每类 3,000 行：`dc_index=24.094ms`、`dc_member=20.839ms`、`dc_daily=21.587ms`；三类 source/output 均为 3,000 行，重复删除为 0。该样本只证明单分区集合 SQL 和原子 Parquet 写入在临时环境内没有异常，不代表正式全量 Bootstrap 耗时。

进入 M6 的条件已满足：同日 Raw ready 后 Silver 能生成正确分区；失败不覆盖；跨数据集历史非等集不误阻断；三类 Silver check 均保持单分区可归因。

### P6：check/event/下游验收

- 运行一个交易日的正式 checks，确认每个 check event 有正确 partition。
- 对照 prod DB、Tushare 样本、Raw、Silver 和业务查询。
- 再决定是否需要历史 event 补录；默认不做无界补录。

### P7：启用日常自动化

- 重载 definitions 后先保持 sensor `STOPPED`，完成人工 smoke。
- 仅在单日和小批量验收通过后由运营启用 sensor。

## 10. 验收标准

### 数据正确性

- `dc_index` / `dc_daily` 的 Raw 在有效交易日内与 Tushare 显式字段契约一致；`dc_member` 的历史 Raw 与 prod 只读导出对账一致，日常 Raw 与 Tushare 显式字段契约一致。
- `dc_daily` 的 `category` 未被删除或降为非主键字段。
- 2,124 条已知错误不出现在最终 Raw/Silver。
- Silver 不含非交易日，不含空主键，不含重复业务主键。
- 成员、指数、行情的跨表差异有审计报告和明确解释，不用不合理的集合相等阻断生产。

### Dagster 正确性

- 六个 check 都是 partitioned check，单 run 单 partition。
- 运行后可按 `asset_check_executions.partition` 读取当前分区状态。
- sensor 不依赖 event history，不产生多分区聚合 check event。
- job 只负责 selection，sensor 使用统一 request/cursor/run-key helper。

### 性能

- `dc_member` 日常请求量按 M1C 固化的代码请求预算控制；不得回到已实测不完整的全市场分页。
- 每个 sensor tick 最多 1 个 run request，最近 10 日有界。
- check 查询只扫描当前 partition 文件，不能全历史深扫。
- 记录请求数、分页数、行数、耗时，超过预算 fail closed。

## 11. 需要保留的事实记录

本方案不把历史 prod/source 差异直接改写成“从未发生过”。以下事实必须进入 bootstrap 审计报告：

- prod 表规模和日期覆盖。
- `dc_daily` 的 2,124 条固定分类错误及修复结果。
- `dc_index` 周末 source/prod 差异及交易日 domain 决策。
- `dc_index` / `dc_member` / `dc_daily` 的历史非等集关系。
- `dc_member` 全市场分页测试的实际页数、行数、重复和漏数事实；prod Bootstrap 的日期/行数/耗时审计；日常 Tushare 代码循环的请求数和耗时门禁。

## 12. M1 实测结论（2026-07-14）

本阶段只做了 Tushare 只读请求，没有写数据湖、Dagster event、materialization 或数据库。

### 12.1 已通过

- `dc_index`：2026-07-13 三类请求分别返回 496/495/31 行，合计 1,022 行；日期、`idx_type`、主键均通过；2024-12-19 概念板块为空，2024-12-20 返回 458 行。
- `dc_daily`：2026-07-13 返回 1,022 行，`category` 三类齐全，日期和 `(ts_code, trade_date, category)` 主键通过；2024-12-19 与 2024-12-20 均可返回数据，因此不把 2024-12-19 作为该数据集起点依据。
- 默认字段、显式字段和业务关键字段均已用直接 SDK/工程封装核验，`dc_daily.category` 存在。

### 12.2 `dc_member` 阻断事实

- 2026-07-13 全市场分页：19 页、92,191 行、按 `(trade_date, ts_code, con_code)` 去重后 91,817 行；374 个重复行全部是跨页重复的完全相同行。
- 20 个板块的按代码交叉核验中，19 个集合一致；`BK0552.DC` 全市场分页去重只有 1,033 行，按代码请求返回 1,129 行，少 96 行。
- `trade_date + ts_code=BK1752.DC,BK1751.DC` 的逗号合并请求返回 0 行，不能用多代码拼接规避请求量。
- 按代码请求已通过日常正确性和性能门禁：按观察到的 1,023 个板块计算，单个交易日约 1,023 次成员请求，受固定 1,200 次/300s 预算保护；历史 Bootstrap 不再按这一路径请求 Tushare，而是走 prod DB 只读导出。因此该数字只用于日常预算，不再乘以 376 个历史日期作为 Bootstrap 请求量。

### 12.3 M1A 结论：Tushare 全市场分页不作为成员事实源

`dc_member` 全市场分页同时存在跨页重复和按代码交叉核验缺失，不能通过简单去重证明完整；因此不用于 Bootstrap，也不用于日常成员事实。

### 12.4 新来源口径与后续门禁

- `dc_member` 历史 Bootstrap 改为 prod DB 只读导出，保留原 `raw_tushare_dc_member` asset key、按交易日物理布局、四字段 schema 和业务主键；每个分区 metadata 必须标记 `bootstrap_source=prod_db_readonly_export`。
- `dc_member` 日常更新仍从 Tushare 获取，使用按交易日 + `ts_code` 的单代码请求；每个分区 metadata 必须标记 `daily_source=tushare_api_by_ts_code`。
- M1B 必须证明 prod 能稳定导出 376 个 expected date；M1C 必须证明日常代码循环的请求量、配额、p50/p95 耗时和空代码语义可接受。两者均通过后才能进入 P2。
- 不因为 Bootstrap 不再请求 Tushare，就取消日常 Tushare 的性能门禁；不允许把当前 1,023 次/日观察值直接写成无限预算。

### 12.5 M1B 只读验证结果（2026-07-14）

报告：`/private/tmp/dc_board_m1b_prod_bootstrap_validation_20260714.json`。

- 表：`raw_tushare.dc_member`；实际字段为 `trade_date DATE`、`ts_code VARCHAR`、`con_code VARCHAR`、`name VARCHAR`，另有 `api_name`、`fetched_at`、`raw_payload` 审计字段；Bootstrap 只投影前四个字段。
- 数据规模：`25,326,662` 行，`2024-12-20` 至 `2026-07-13`，`376` 个 expected SSE open dates，缺失日期 `0`，范围外日期 `0`。
- 全历史聚合质量：重复主键 `0`、空主键 `0`、非法板块/成分代码 `0`、空名称 `0`。
- 流式抽样：起始日 `48,736` 行/10 chunks/`1315.032 ms`；`2025-05-30` `47,058` 行/10 chunks/`1890.098 ms`；最新日 `91,715` 行/19 chunks/`3323.125 ms`；中间样本日 `56,003` 行/12 chunks/`2142.295 ms`。四个样本的 streamed row count 与聚合 row count 全部一致。
- 全历史聚合耗时约 `110,930.151 ms`。该耗时只用于审计基线，不代表正式 Bootstrap 应执行一条全历史 SQL；正式实现必须按日期分批、流式读取、逐日 staging 和原子 promote。
- Tushare 有限对照：四个日期分别从 prod 确定性抽取板块代码，每日至多 20 个代码；使用 Tushare MCP `dc_member` 显式请求 `trade_date,ts_code,con_code,name`，共 69 个 `trade_date + ts_code` 请求。prod 与 Tushare 的行数和排序后的四字段行集合 `69/69` 一致，差异 `0`。该结果证明 prod Bootstrap 样本与源站当前按代码读取口径一致，不证明全市场分页完整性，也不替代 M1C 的日常请求预算验证。详细报告：`/private/tmp/dc_board_m1b_prod_bootstrap_reconciliation_20260714.json`。
- M1B 结论：**通过**。剩余风险是正式 staging 写入吞吐、磁盘空间和逐日 promote 失败恢复，这些留到后续实现阶段的临时 lake 验证，不在本轮执行。

### 12.6 M1C 日常代码请求 profiling 与策略整改结果（2026-07-14）

报告：`/private/tmp/dc_board_m1c_validation_20260714.json`；详细报告：`/private/tmp/dc_board_m1c_member_request_profile_throttled_20260714.json`。

- 候选集合按 `dc_index` 当日三类代码并集计算；当前没有已完成的 Raw `dc_member` 分区，因此本轮没有额外并入历史 member-only 代码。四个日期候选数为：`2024-12-20=458`、`2025-02-19=462`、`2025-05-30=552`、`2026-07-13=1,022`。
- 原始无界连续请求约 `10.2 req/s` 时真实收到 Tushare `dc_member` “频率超限（500次/分钟）”错误；空代码本身是合法源事实，但限流失败不能当作空代码。
- 整改后的 `defs/tushare_request_policy.py` 已提供并测试：最小间隔 `0.13s`、最多 3 次重试、`1/2/4s` 指数退避、单次退避上限 `8s`、单分区最多 `1,200` 请求、单分区最多 `300s`；分页通过 offset 逐页请求，所有页共享同一预算。
- 安全重测共 323 个分页请求；成功/空结果/失败/未尝试代码为 `286/37/0/0`，其中 3 次重试全部恢复，多页代码 `0`，日期/代码/空主键/重复业务主键错误均为 `0`。p50 `46.112ms`、p95 `136.134ms`、最大 `1,382.451ms`，总墙钟时间 `59,507.589ms`。最近日 `1,022` 个候选的硬下限仍为 `122.64s`。
- 空结果探针 `BK9999.DC` 正常返回 0 行；合成超时后第二次真实请求恢复，返回 444 行；两者均通过策略层且没有任何正式写入。
- M1C 结论：**整改后通过**。正式 Raw writer 必须使用该策略，任何失败代码、预算超限或分页未完成都整日 fail-closed；详细报告：`/private/tmp/dc_board_m1c_member_request_profile_throttled_20260714.json`，汇总报告：`/private/tmp/dc_board_m1c_validation_20260714.json`。

详细报告：`/private/tmp/dc_board_m1_tushare_validation_report_20260714.json`。

这些是离线审计和运维诊断事实，不写入业务 parquet 字段，也不进入 sensor cursor 的逐行明细。
