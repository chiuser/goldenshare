# Dagster `dc_index` / `dc_member` / `dc_daily` 数据集接入技术方案

> 状态：M3 Raw 写入能力、M4 Raw Dagster definition、M5 Silver writer/asset/check、M6 Silver Dagster 接入、M7A 只读 Bootstrap dry-run、M7E 临时 lake 样本联调、M7F-M7I 正式 Raw/Silver Bootstrap 与对账、M8 Dagster 事件补录与验收均已完成。M9-R 已完成专属分区、同日 Lake 关系和 writer 基础闭环的代码落地；其中“有限小页 source probe 可提交 Raw run”的日常触发口径已被 M10 取代。M10“稳定 prod 基线 + 完整 Tushare 对照”与 M10.1“`dc_member` 成功但不完整响应的单轮定向重试”均已完成代码与本地验证。2026-07-26 已完成 2026-07-24 的正式历史恢复；2026-07-27 已完成历史 member check 状态纠偏，并启用当前 code location 的 raw index sensor。该传感器已按稳定 prod 基线门禁自然完成 `2026-07-27` 的 Raw index/daily/member 更新；没有写 prod。2026-08-12 已补齐 `2026-05-20/21` 的 `dc_member` Tushare 确认缺口，并根据 36 个 2026 年日期的当前源端实测，将错误的 daily/index 集合相等约束修正为 `dc_index code set ⊆ dc_daily code set`。2026-08-19 已完成 M10.2“源事实权威纠偏”的代码与本地验证：Tushare 成为日常 Raw 唯一内容权威，prod 只保留完成时机和差异诊断职责；尚未执行 `dg check defs`、正式只读演练、sensor 启停或实际生产 run。
>
> 依据：新增数据集接入模板、`lake_console/orchestrator/CODING_STANDARDS.md`、
> `dagster-data-pipeline-performance-governance.md`、现有 `index_daily` / `stk_nineturn`
> 实现，以及 2026-07-14 对 prod DB 和 Tushare 的只读审计。

> **当前阅读口径**：M3-M8 的实施状态保留当时的代码事实，用于追溯历史和验收证据；其中出现的
> 共享 `cn_a_index_trade_days` 只代表旧实现，不是当前板块链路的目标口径。分区、Lake core check
> 和同日关系以 M9-R 为准；M10/M10.1 是已经退出的历史裁决口径，当前代码以 M10.2 为准。
> 小页 probe 和 prod 精确 identity 相等门禁仅保留为历史实现事实，不能被解释为当前生产契约。

## M3 实施状态

M3 已完成 Raw-only 写入能力：

- `defs/tushare_request_policy.py` 提供共享有界分页、重试、限流、请求/时间预算、跨页主键重复和首请求前代码数预算保护。
- `defs/assets/dc_board.py` 提供 `dc_index` 三类型合并、`dc_daily` 日期分页、`dc_member` 单代码分页和 DuckDB staging/回读 schema/行数校验/原子替换；无 Dagster decorator。
- `defs/bootstrap/dc_board_bootstrap.py` 提供 Prod `dc_member` named cursor + `fetchmany` 只读流式导出；不使用写资源、不执行 `fetchall`。
- `ProdPostgresResource.connect_readonly_transaction()` 提供只读、非 autocommit、退出 rollback 的独立 Bootstrap 连接语义，既有 `connect()` 保持不变。
- 测试覆盖策略边界、三类 Raw writer、失败不覆盖、字段/日期/主键校验、Prod chunk 边界和 rollback-only 约束。

性能样本：`/private/tmp/dc_board_m3_performance_20260714.json`。1,022 个 fake `dc_member` 代码请求为 1,022 次、1,022 页、0 retry，source/written 均为 1,022，DuckDB + Parquet staging 耗时约 394 ms；真实 Tushare 间隔仍由 M1C 固化的 `0.13s` 和 1,200/300s 预算控制。

M3 明确不新增 active Dagster asset/check/job/sensor，不执行正式 bootstrap，不写正式湖或 Dagster DB。

### 2026-07-19 运行修复：拒绝部分 `dc_daily` 响应

7 月 17 日的 `raw_tushare_dc_daily` 文件只有 277 个代码，而同日 `dc_index` 基准集合为
1,022 个代码；这不是允许落湖的板块关系差异。对当前源站做的只读复核中，`dc_daily` 与
三个 `dc_index` 类型均返回 1,022 个代码，两个集合差异为 0，因此该 277 行响应应视为
源端的临时不完整响应。

- `dc_daily` writer 在原子替换前，额外对齐同日 `raw_dc_index` 的去重 `ts_code` 集合；
  缺同日 index 文件、index 集合为空或 daily 缺少 index 代码都会 fail closed，既不替换目标 Parquet，也不产生成功 materialization；
  daily 出现源端真实存在的额外代码是合法事实，不触发该门禁。
- 这不是新增 Dagster check：现有合并 core check 仍是最终湖文件防线；写入前闭环负责避免
  将已知不完整的源端响应先写入再报红，不增加 check event 数量。
- `dc_member` 候选规划的交易日历字段统一使用 Silver 实际 schema 的 `trade_date`；不再读取
  已不存在的 `cal_date`。

本修复不改变 Tushare 请求参数、分页策略、资产/检查/job/sensor 名称、分区或数据湖路径。

### 2026-08-12 源端复审、`dc_member` 补齐与关系契约纠正

- 对 36 个可疑日期使用全部显式字段复核当前 Tushare：`dc_index` 与 DG 逐行一致，`dc_daily` 与 DG 逐行一致。
- 36 个日期中有 32 个日期存在合法的 daily-only 身份，共 13,305 个 board/date/category 身份；所有 36 个日期的 index-only 数量均为 0。因此源事实只证明 `dc_index code set ⊆ dc_daily code set`，不证明集合相等。
- `dc_member` 继续使用 `dc_member code set ⊆ dc_index code set`。源端或湖内 member 缺少某个 index 代码时，不能只凭跨表关系断言数据缺失；但本次已由 Tushare 按代码实测确认的缺口必须补齐。
- 正式补齐仅请求已确认缺失范围：`2026-05-20` 请求 478 个板块代码并新增 27,807 行，Raw/Silver 由 16,428 行增至 44,235 行；`2026-05-21` 请求 1 个板块代码并新增 63 行，Raw/Silver 由 80,618 行增至 80,681 行。合计 479 次请求、0 次重试、27,870 行；两日均达到 1,013 个 index/member 代码，源端修复范围、Raw、Silver 完全对账，无 Prod 写入。
- writer、Prod reference closure、Raw/Silver core check 与 readiness 使用同一关系：`dc_member ⊆ dc_index ⊆ dc_daily`。daily 额外代码允许；daily 缺任一 index 代码、member 出现 index 外代码仍 fail closed。旧 `daily_equals_index` mode 不保留兼容入口。
- 新契约下重新只读核验上述 32 个日期的 Raw/Silver，64 个分区层级全部 `ready=True`；随后只追加 64 条绑定既有 materialization 的通过 check evaluation，未请求 Tushare、未改 Lake 文件、未写 Prod、未补发 materialization。
- 最终全量物理复核覆盖 `2026-01-05..2026-08-11` 共 146 个分区：Raw/Silver 的 index/member/daily 六组均为 `146 ready / 0 not ready`，且六组日期集合一致。

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
- 不再复用现有 `cn_a_index_trade_days` 作为板块数据集的正式分区注册事实。为避免不同数据集起点和生命周期互相污染，改为三个专属 dynamic partition set：`cn_a_dc_index_trade_days`、`cn_a_dc_member_trade_days`、`cn_a_dc_daily_trade_days`。`silver_dc_index` / `silver_dc_member` / `silver_dc_daily` 分别复用对应 Raw 分区集；`gold_dc_daily_technical` 及其 repair 链路复用 `cn_a_dc_daily_trade_days`。
- 专属分区注册只由 SSE open calendar 驱动，不以 Tushare 固定更新时间为注册条件，也不设置“每天某时刻才注册”的硬门槛。dynamic partition 只表达“该交易日已经进入本数据集的日期域”，不表达源数据已经 ready。
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
- `silver_dc_daily` 不要求与 `silver_dc_index` 做集合相等；同日 `silver_dc_index` 的代码必须全部出现在 `silver_dc_daily`，daily-only 代码允许保留。
- `dc_member ⊆ dc_index ⊆ dc_daily` 的同日关系由 core check/readiness 的有界 SQL 校验；更宽的历史差异和异常统计仍由离线 audit 工具完成，不扫描历史 event。

### 5.3 Job、sensor 与 cursor（历史基线）

建议每个 API/层级独立 job 和 sensor，避免一个 API 失败拖住其他 API，也避免多资产单 run 造成 check partition 归属歧义：

```text
raw_tushare_dc_index_update_job + raw_tushare_dc_index_update_job_sensor
raw_tushare_dc_member_update_job + raw_tushare_dc_member_update_job_sensor
raw_tushare_dc_daily_update_job + raw_tushare_dc_daily_update_job_sensor
silver_dc_index_update_job + silver_dc_index_update_job_sensor
silver_dc_member_update_job + silver_dc_member_update_job_sensor
silver_dc_daily_update_job + silver_dc_daily_update_job_sensor
```

以下是 M4-M6 旧版 sensor 的历史基线，不能作为 M9-R 的正式触发规则：

- 只检查最近 10 个 expected dates。
- 只选择最早 first-not-ready 日期，最多返回 1 个 run request。
- 不读 Dagster event history；Raw/Silver readiness 通过一次 DuckDB batch 文件检查构建。
- 同一 asset 的正式 run 只带一个 `partition_key`，避免一个 check result 归属多个分区。
- run request 必须走 `build_run_request`；run key 必须走 `build_asset_update_run_key`；cursor 必须走 `build_sensor_cursor`。
- 传给 cursor 的只是一条 frontier、阻断组件、页数/行数/耗时摘要，不塞逐行明细。

Bootstrap 是独立人工维护工具，不接 sensor、schedule 或 AutomationCondition；bootstrap 完成后才执行有界的 event 验收/补录。

M9-R 会保留 job、sensor、cursor 和单分区 check 的低基数原则，但替换分区来源、注册入口、source
probe 和成功判定；旧版文件 readiness 不能单独触发正式更新。

### 5.4 M9-R：专属分区、有限探测与完整性门禁修复专项（历史实现基线）

本节替代 5.3 中旧的“共享 `cn_a_index_trade_days` + 文件 readiness 即可触发”口径。它已经定义并落地专属分区、Lake core check 和同日关系闭环；但其中“有限小页 source probe”无法证明当天 Tushare 已发布完整目录，已由 5.5 M10 替代。M10 不改变数据字段、物理布局、run key 命名规则和单分区 check 颗粒度。

#### 5.4.1 专属分区注册 sensor

新增三个仅负责注册交易日分区的 sensor，名称在代码实现阶段固定为：

```text
dc_index_trade_day_partition_sensor
dc_member_trade_day_partition_sensor
dc_daily_trade_day_partition_sensor
```

规则：

1. 每个 sensor 只读取 `silver_trade_calendar`，按自己的 history start date 生成 SSE `is_open=true` 且不晚于当前本地日期的 expected dates。
2. 每个 sensor 只向自己的 dynamic partition set 注册缺失日期；注册操作幂等，已注册日期不重复添加。
3. 分区注册 sensor 不访问 Tushare、Prod DB、Parquet 业务文件或 Dagster event history。
4. 注册周期是有限轮询间隔，不是源站更新时间。即使源站当天尚未更新，也先注册日期；M9-R 当时随后会等待 Raw sensor 的 source probe，M10 则按 5.5 的 prod 基线与完整 Tushare 对照判断是否提交 run。
5. 注册缺口只能由专属注册 sensor 修复；Raw/Silver sensor 发现自己的分区缺口时只返回 `partition_not_registered`，不得借用其它资产族的 partition set，也不得在同一个 tick 里偷偷注册。
6. Gold technical asset、Gold daily sensor 和 Gold repair sensor 必须跟随 `cn_a_dc_daily_trade_days`，不能继续消费旧的共享注册集。

#### 5.4.2 Raw 触发模式（历史规则，已由 M10 替换）

M9-R 的 Raw sensor 曾使用“分区已注册 + 有限源探测 + first-not-ready”模式；该模式保留在此解释已落地
代码的来源，不能作为 M10 后的日常触发规则：

```text
专属分区注册
  -> 最近 10 个 expected dates
  -> 注册缺口门禁
  -> 当前 Raw lake readiness
  -> 有限 source probe
  -> first-not-ready target
  -> 一个单分区 RunRequest
```

触发规则：

1. 先选本数据集最近 10 个 expected dates 中最早的 missing/not-ready 日期；后续日期不得越过更早缺口。
2. 文件存在但 core check 失败时返回 skip，不自动覆盖；文件缺失或未生成时才进入 source probe。
3. source probe 只判断“现在是否值得提交完整 run”，不把 probe 结果当作成功事实，也不代替完整 run 的分页、行数和集合校验。
4. probe 失败只返回 `source_probe_not_ready` / `source_probe_error` 等 ASCII reason code，并等待下一轮；不得写 lake、不得写 Dagster event、不得把失败记成 ready。
5. probe 通过后只提交一个目标日期的 RunRequest；Raw asset run 内才执行完整请求和 bounded writer。
6. `dc_member` sensor 先要求同日 `raw_tushare_dc_index` 已通过完整 readiness，再抽样探测 3-5 个确定性板块代码；sensor 不计算全量 candidate、不执行 1,000+ 次 Tushare 请求。

有限探测预算固定为实现阶段的 contract，不开放为运营参数：

| 数据集 | 探测请求 | 探测成功条件 | 单 tick 上限 |
|---|---:|---|---:|
| `dc_index` | 3 次，每个 `idx_type` 一次，单页小 limit | 三个请求均无协议/网络错误，返回列和日期合法；若允许源端合法空类型，必须由完整 run 记录该空类型并完成全日闭环；三类全空直接失败 | 最多 3 次探测请求、单次 probe 8 秒 |
| `dc_daily` | 1 次，小页请求 | 非空、日期合法、出现正式 category 集合；完整 run 再验证全部板块代码集合 | 最多 1 次探测请求、单次 probe 8 秒 |
| `dc_member` | 3-5 次，每个确定性板块代码一次 | 请求无错误、返回代码与请求代码一致；空响应不能单独证明完整，最终以全量代码请求闭环为准 | 最多 5 次探测请求、单次 probe 8 秒 |

探测策略不得有无限重试；探测总预算超限就 skip，避免 Dagster user-code RPC 接近 60 秒 deadline。完整生产 run 使用 1,200 请求 / 600 秒分区预算。

#### 5.4.3 “更新成功”的正式定义

一个交易日只有同时满足以下三层事实，才称为更新成功：

```text
source request closure
  AND lake file/core quality
  AND same-day board-family completeness
```

**A. 源请求闭环（由 writer 在 promote 前完成）**

- `dc_index`：三个 `idx_type` 请求全部有终态；每个终态必须是成功非空或明确的合法空结果；无失败请求、无未尝试请求、分页完整、源行数与写入行数一致。
- `dc_daily`：日期分页全部结束；无失败页、无未尝试页、`category` 完整、源行数与写入行数一致。
- `dc_member`：`requested_code_count = success_code_count + valid_empty_code_count`，`failed_code_count = 0`，`unattempted_code_count = 0`，跨代码主键唯一，源行数与写入行数一致。合法空响应必须被计数，不能和“没有请求到”混为一谈。
- 任一 source closure 失败，writer 不 promote、不产生成功 materialization；原有目标文件保持不变。

**B. 湖文件与核心 check**

- 文件存在、schema 正确、分区日期一致、业务主键非空且唯一、身份字段和数值域合法。
- `dc_index` 类型覆盖和 `dc_daily` category 覆盖符合正式 contract。
- check 仍然每个资产一个合并 blocking check，不拆成分页/行数/请求耗时等多个 event；`failed_rules`、`reason_code` 和有限样本负责诊断。

**C. 板块族闭环**

- `dc_daily` 的同日板块代码集合必须覆盖 `dc_index` 基准集合；Tushare `dc_daily` 返回的额外板块是合法源事实，不得因为不在 `dc_index` 中而拒绝。
- `dc_member` 的请求候选代码必须来自同日 `dc_index` 代码集合；每个请求终态都必须可解释。若源端允许某板块合法无成员，必须由 source closure 明确记录，不能仅凭 member 文件缺行推断成功。
- 关系校验采用有界同日 SQL，不扫描历史 event，不把历史 Bootstrap 的非等集差异带入日常 sensor。

完整成功条件由“writer source closure + core check + 关系闭环”共同组成；不是 source probe 通过、文件存在或 row count 大于 0 的任一单项条件。

#### 5.4.4 Sensor / cursor 状态模型（历史规则）

M9-R 的历史 ASCII reason code：

```text
partition_not_registered
source_probe_not_ready
source_probe_error
source_request_incomplete
source_request_budget_exceeded
lake_file_missing
materialized_check_failed
cross_dataset_code_set_mismatch
all_ready
```

cursor 只保存目标日期、first-not-ready、ready frontier、probe 请求数/耗时/结果摘要和失败规则数量；不保存完整板块代码列表、逐页结果、原始响应或 source payload。sensor 不依赖 Dagster event history，不解析 run key，不在 cursor 中保存可恢复业务状态。

#### 5.4.5 修复专项推进顺序

1. **R0 代码/文档审计**：确认所有 `cn_a_index_trade_days` 消费者、Raw/Silver/Gold technical job/check/sensor 和测试影响面。
2. **R1 Contract**：新增三个专属 partition set、日期起点映射、probe result 和 source closure 结果模型、ASCII reason code；不新增数据库表或 manifest。
3. **R2 分区注册**：实现三个 calendar-only partition registration sensor，补齐单独注册测试。
4. **R3 Writer source closure**：扩展 Raw writer 的完整请求终态、分页、行数和合法空响应审计；失败不 promote。
5. **R4 Core check / relation audit**：把代码集合闭环、类型/category 完整性和 source closure 失败映射到合并核心 check；保持每资产一个 check。
6. **R5 Raw/Silver/Gold sensor**：替换旧共享 partition set，接入 bounded source probe、first-not-ready 和 Raw frontier gate。
7. **R6 临时 lake 回归**：使用起始日、中间日、最新日、已知异常日验证缺失、部分返回、空响应、集合不一致和失败不覆盖。
8. **R7 性能门禁**：记录每种 probe 请求数、DuckDB 扫描文件数、tick elapsed、RPC 安全余量；超限停止，不调大 timeout。
9. **R8 正式切换**：definitions 静态验证、专属分区只读核对、停用旧 sensor、逐个启用新注册/Raw/Silver sensor，连续观察 3 个实际交易日后再允许 Gold technical 自动链路。

事件边界：M8 已写入的历史 event 作为审计事实保留，不删除、不自动改写、不用于 source readiness；新定义切换后的事件使用专属 partition set。若需要把旧事件迁移到新分区集，必须另开事件对账/补录专项，不能在 M9-R 中隐式完成。

R0-R8 未完成前，不得继续按旧 `cn_a_index_trade_days` 口径启用 Raw/Silver sensor；正式 Dagster 执行和 sensor 切换另行审批。

### 5.5 M10：日常源端完成确认门禁（代码完成，待正式审计/启用）

#### 5.5.1 目标、边界与事实源

M10 解决的是“源端已有少量记录，但当天目录或行情尚未完整发布”这一时序问题。2026-07-22 的自动
`raw_tushare_dc_index` run 在 15:06 以 231 行成功，而同日后续复核的 Tushare 和 prod 基线均为
1,022 个板块代码；因此“非空的小页 probe”不能再作为提交 Raw run 的依据。

审计证据固定为 `/private/tmp/tushare_dc_20260722_source_audit_20260723_215311.json`（Tushare 当前完整
code set）与 `/private/tmp/prod_dc_daily_publish_timing_20260724.tsv`（prod 在 2026-07-10 至 2026-07-23
的首写入、最终更新时间和同日集合闭环）。prod 时间戳只证明 prod 的可用与稳定窗口，不被表述为 Tushare
的直接发布时间证明。

- Tushare 仍是 `raw_tushare_dc_index`、`raw_tushare_dc_daily`、`raw_tushare_dc_member` 的唯一业务数据来源；M10 不把 prod 数据写入 Lake，也不改变历史 Bootstrap 来源。
- prod `core_serving.dc_index`、`core_serving.dc_daily`、`core_serving.dc_member` 只作为当天已发布数据的**只读完整性基线**。它不是新的 Raw source，也不参与 Silver/Gold 的数据计算。
- 不新增 asset、job、check、dynamic partition、runless event、manifest 或状态表。M10 只替换 Raw 日常触发和 Raw promote 前的完整性判定。
- 现有 Raw/Silver/Gold 的分区、路径、schema、run key、单分区合并 check 和 Lake readiness 语义保持不变。

#### 5.5.2 冻结时间与 prod 基线

对当天目标分区，基线不是在 21:15 直接冻结，而是以下两次读取均通过后，在第二次读取完成时冻结：

```text
t1 = 21:15（上海时间）之后的第一个 raw_dc_index sensor tick
  -> 读取 prod 当天 reference snapshot，得到 fingerprint F1

t2 >= t1 + 5 分钟的下一次 tick
  -> 再次读取同一 reference snapshot，得到 fingerprint F2

F1 == F2 且两次 reference 都内部闭合
  -> 在 t2 冻结 F2，才允许提交 raw_tushare_dc_index run
```

现有 Raw sensor 的最小间隔是 600 秒，因此不为 M10 缩短轮询；若第一轮恰在 21:15，实际最早冻结约为
21:25。`21:15` 是近期 prod 审计中最晚最终更新时间约 21:12 后的首个观察下限，不是“到点必然完整”的
断言。若两次 fingerprint 不同，或 prod 读取失败、集合不闭合，则只保留最新候选并等待下一 tick；绝不提交
run。

冻结 snapshot 的身份只包含排序后的业务身份、计数和 SHA-256：

| 数据集 | 基线身份 | 必须满足的内部闭环 |
| --- | --- | --- |
| `dc_index` | `(idx_type, ts_code)` | 三类均存在；无空/重复 key |
| `dc_daily` | `(category, ts_code)` | 无空/重复 key；code set 覆盖 `dc_index`，允许 daily-only code |
| `dc_member` | `ts_code` 的 distinct set、总行数 | distinct `ts_code` 是当天 `dc_index` code set 的子集；无空 key |

sensor 热路径只读取约千级 index/daily identity 和 member 聚合，不拉取约九万级 member pair。完整
`(ts_code, con_code)` 对照留在 member writer 的单日 run 内执行。

#### 5.5.3 Tushare 完整性对照与执行顺序

`raw_tushare_dc_index_update_job_sensor` 是唯一做“完整源端可用性”判断的 Raw sensor：它在 prod snapshot
冻结后，完整读取 Tushare 三个 `dc_index` 类型和完整 `dc_daily` 分页，并要求每类 identity、计数和
hash 与冻结基线严格相等。它不再发出 `limit=1` probe。

```text
注册交易日
  -> raw_dc_index：时间门槛 + prod 双快照冻结 + Tushare index/daily 全量对照
  -> raw_dc_index promote：重新确认冻结 fingerprint 未变化，再原子写入
  -> raw_dc_daily：同日 raw_dc_index 已 ready；完整 Tushare daily 对齐 raw index 与 prod daily
  -> raw_dc_member：同日 raw_dc_index 已 ready；仅请求当天 raw index 的代码，完整成员集合对齐 prod
  -> 三个 Silver
  -> gold_dc_daily_technical
```

`dc_daily` 和 `dc_member` 不再以“几条小页返回正常”作为独立 source ready 条件。它们只能在同日 Raw
index 已 ready 后提交；实际 writer 仍在 promote 前做自己的完整闭环。这样既不把 1,000+ member 请求放到
sensor 热路径，也不允许手工 Launchpad 绕过完整性检查。

#### 5.5.4 Writer promote 前的不可绕过门禁

- `dc_index` run config 只传递 `trade_date`、冻结时刻和 64 位 reference fingerprint，不传完整代码清单。writer 重新只读 prod，并要求 fingerprint 仍等于传入值；随后完整 Tushare index/daily identity 必须等于该基线。任一不等，staging 丢弃，不 promote。
- `dc_daily` 的完整 Tushare `(category, ts_code)` 身份必须等于 fresh prod `dc_daily` 基线，同时其 code set 必须覆盖同日 `raw_dc_index`；同日 Raw index 身份仍必须等于 fresh prod `dc_index` 基线。任一条件不满足，不 promote。
- `dc_member` 候选只能等于同日 `raw_dc_index` 的 `ts_code` 集合，删除“与前一日 member 代码并集”的连续性 fallback。writer 用 DuckDB set-based SQL 将 Tushare `(ts_code, con_code)` 与 prod 当天同一 identity 做双向差集；缺失、额外、重复、空 key、日期不符或请求失败都不 promote。
- 所有比对均显式字段投影，禁止 `SELECT *`。prod 连接必须是既有 `ProdPostgresResource.connect_readonly_transaction()`；不得使用写资源。
- 已有目标文件只沿用既有“materialized 但 blocking check failed 时不自动覆盖”规则；M10 不引入自动重写历史文件。

#### 5.5.5 Cursor、性能与失败语义

cursor 是调度路标，不是基线报告。跨 tick 的 `runtime_state` 只保存 `trade_date`、第一次 snapshot
fingerprint 和 `observed_at`；人可见部分只保存目标日期、阻断组件、当前/基线数量、简短中文摘要和下一步动作。
禁止写全量 code、hash 明细、Tushare 行、prod 行、分页结果或 member pair。

新增 reason code：

```text
before_prod_reference_window
prod_reference_pending_confirmation
prod_reference_not_closed
prod_reference_changed
tushare_reference_mismatch
prod_reference_unavailable
```

典型摘要必须可直接读懂，例如“尚未到板块源端观察窗口，21:15 后再检查”或“Tushare 概念板块返回 100 个，
prod 基线为 495 个，未提交 run”。`blocked_component` 固定为 `prod_core_reference`、`tushare_source`、
`raw_tushare_dc_index` 或现有分区/Lake 组件，不使用宽泛的 `source_probe`。

稳定日 index sensor 先用两轮、每轮 3 个只读 prod 查询冻结基线；仅在第二轮一致后，才执行一次完整
Tushare 对照（3 个 `dc_index` 类型 + 1 个 `dc_daily` 请求）。因此两轮合计最多 6 次 prod 查询和 4 次
Tushare 请求。实际 index writer 会再做一次完整 Tushare 对照，以防 sensor 到 run 执行之间的源端变化。
member 的约千次请求仍只发生在实际 member job，不进入 sensor。任何 prod/Tushare 调用超时、请求预算越界或
对照不一致都 fail closed，下一 tick 再尝试；不得调大 Dagster RPC timeout。

#### 5.5.6 M10.1：`dc_member` 成功但不完整响应的恢复边界（代码、本地验证与历史恢复已完成）

M10 已能阻止“当天目录尚未完整”时过早提交 Raw index run，但 2026-07-24 的运行事实说明，`dc_member`
还存在另一类源端短暂异常：**请求没有报网络错误，却少返回了部分成员关系**。两次 writer run 分别在约
`235.6s` 和 `212.3s` 内完成请求并在 promote 前被 prod pair 对照拒绝，差异分别为 `9` 与 `315` 条
missing pair；两次之间的一次只读全量 Tushare/prod 对照为 `0` 差异。这不是超时、请求数超限或 429 限流，
而是“成功响应不等于完整事实”。现有 fail-closed 门禁正确地阻止了半截 Parquet，但缺少一次有界的恢复机会。

**现行请求限速必须保持不变：**

| 约束 | 当前值 | 含义 |
| --- | ---: | --- |
| 请求起点最小间隔 | `0.13s` | 理论上约 `461` 次/分钟，低于已验证的 `500` 次/分钟源端限制 |
| 单分区总请求数 | `1,200` | 首轮、分页、网络异常重试和 M10.1 定向重试共用同一计数 |
| 单分区总耗时 | `600s` | M10.1 不重新获得第二个 600 秒预算 |
| 网络异常重试 | 最多 `3` 次 | 只处理限流、超时、连接中断等异常；`1/2/4s` 退避，单次上限 `8s` |
| sensor 最小间隔 | `600s` | 不因 member 恢复逻辑缩短轮询或增加热路径请求 |

网络异常重试不能解决本问题：Tushare 对这类不完整返回给出了正常响应，因此现有 request policy 不会重试。
M10.1 只在实际 `raw_tushare_dc_member` job 内增加下面的**一轮定向重试**，不在 sensor 中执行九万级
member pair 对照，也不新增 asset、check、job、分区、event、环境变量或业务字段。

```text
同日 raw_dc_index ready
  -> 首轮：按当天 1,022 级板块代码请求 Tushare（现有分页、限速与预算）
  -> DuckDB：与 prod 当天 (ts_code, con_code) 做双向差集
  -> 无差异：沿用现有 promote
  -> 仅 missing pair：按缺失 pair 聚合出受影响的 ts_code，排序后只重试这些板块一次
  -> 用重试结果替换这些板块的首轮临时行，再做全量双向差集
  -> 差异归零：沿用现有 staging + 原子 promote
  -> 仍有差异 / 任何其它契约错误 / 预算不足：fail closed，不写目标文件
```

恢复只适用于“所有已有字段、日期、请求代码、分页终态和主键校验通过，且最终差异仅为 source 缺少 prod
pair”的情形。出现 extra pair、跨代码响应、重复 key、空 key、日期错误、列漂移、请求失败或未尝试代码时，
不尝试通过重抓掩盖问题，直接按现有语义停止。重试时必须先从 DuckDB 临时表删除受影响板块的首轮行，再插入
该板块的完整重试结果，不能把两轮结果拼接在一起制造重复或保留半截成员关系。

M10.1 不提高 `1,200` 次或 `600s` 上限。首轮后可用的请求数和时间才是定向重试的真实预算；若受影响板块
数量、分页数或网络退避使第二轮无法在剩余额度内完成，整日失败而不是扩大限额。正常成功路径增加 `0` 个
请求；异常路径只增加“缺失成员涉及的板块数及其分页数”，最多一轮。开发前必须用 2026-07-24 运行样本和
fake source 测试记录缺失板块分布、请求数、剩余预算和耗时，不得假设 `315` 条 missing pair 等于 `315` 个
板块请求。

写入前后的可读性边界如下：

- 成功 materialization 只记录聚合诊断：首轮 missing pair 数、定向重试板块数/请求数、恢复 pair 数、最终
  missing/extra 数及总耗时；不记录完整代码或 pair 清单。
- 失败 run 日志和异常文本最多附 `20` 个缺失板块/pair 样本，说明是“源端成功但成员不完整”；cursor 不写 pair
  清单或完整 request report。
- 不新增 production check。现有合并 core check、Lake readiness 和同日关系语义不变；writer 成功仍要求
  source closure、原子 promote 和后续 core check 全部通过。

**自动再次提交不属于 M10.1。** 现有 dependent sensor 的 run key 是按 job 和 trade date 固定生成的；同日失败
run 不能被当作无限次自动重放的理由。本轮只修复单次 job 内可验证的短暂不完整响应，保留现有 run key 和
sensor 触发行为。若单轮定向重试仍失败，后续是否设计“仅 `member_source_incomplete`、固定次数、固定间隔”的
sensor retry，必须另立 M10.3 方案并单独评估 Dagster run-key、cursor state 和源端压力，不能顺手改变。

上述自动再次提交议题顺延为 M10.3；M10.2 优先解决下面的源事实权威冲突。

#### 5.5.7 M10.2：Tushare 源事实权威纠偏（代码与本地验证完成）

##### 5.5.7.1 问题与证据

M10 的原始意图是用 prod 已完成的当天快照阻止 DG 过早写入半截 Tushare 数据，但当前实现把“完成时机证据”
扩大成了“逐条内容裁决”：Tushare 与 prod 的 index、daily identity 或 member pair 只要存在双向差异，writer
就拒绝 promote。该实现与本方案 5.5.1 已冻结的事实冲突：日常 `raw_tushare_dc_*` 的业务事实来自 Tushare，
prod 不是权威内容源，也不保证与稍后时点的 Tushare 快照完全相同。

2026-08-18 的两次正式失败提供了直接证据：

| run | 阶段 | Tushare 少于 prod | Tushare 多于 prod | 结果 |
| --- | --- | ---: | ---: | --- |
| `d649d644-48b9-48c2-a7b5-120ef1229bf1` | initial pair diff | 36 | 18 | promote 前失败，未生成目标文件 |
| `0b86e5de-dd2a-487f-9b97-ac75ad1d65bd` | initial pair diff | 5 | 18 | promote 前失败，未生成目标文件 |

第二次请求已消除 31 个 missing pair，但 18 个 extra pair 完全不变；剩余 5 个 missing pair 集中在
`BK1516.DC`。两次结果说明 prod 与 Tushare 可能只是采集时点或版本不同。当前代码既不能判定哪边更新，也不能
让已稳定的 Tushare 事实胜出，只能永久 fail closed。安全拒写本身正确，但“prod 精确相等才算完整”的权威
口径不正确。

##### 5.5.7.2 权威与职责重新冻结

1. 日常 Raw 行事实唯一以受控时点取得且通过结构、分页、日期、主键、关系和稳定性门禁的 Tushare 响应为准。
2. prod 仍保留两个用途：证明当天 prod 采集链路已进入稳定完成窗口；在 Tushare 与 prod 不同时指出需要二次
   稳定确认的异常范围。prod 不再逐条裁决 Tushare 行是否合法。
3. prod 与 Tushare 内容不一致时，不直接选择 prod，也不立即接受第一份 Tushare 响应；系统必须用第二份
   Tushare 结果证明源端自身稳定。稳定后采用 Tushare，未稳定则拒写。
4. 严禁把 prod 行补入、替换或删除 Tushare 行；历史 `dc_member` Bootstrap 的 prod 只读来源保持原历史事实，
   M10.2 只修改日常生产口径，不重写历史文件和事件。
5. 不新增 asset、job、sensor、check、partition、状态表、manifest 或 runless event。现有核心 check/readiness
   已验证文件 schema、键、日期和 `member ⊆ index ⊆ daily` 关系，不增加 prod 对账 check。

##### 5.5.7.3 日常触发和写入方案

`raw_tushare_dc_index_update_job_sensor` 继续在 21:15 后观察两份间隔满足要求且 fingerprint 稳定的 prod
快照，但该 fingerprint 只表示“prod 完成状态未继续变化”。随后完整请求 Tushare index/daily：

- 若 Tushare 结构闭合且 identity 与 prod 相同，现有独立副本已互相印证，可直接提交 index run。
- 若 Tushare 结构闭合但与 prod 不同，cursor 只保存由完整规范化 Tushare index/daily 业务行计算的 source
  fingerprint、观察时刻和有限差异计数；
  下一 tick 再完整请求一次。第二份 Tushare fingerprint 与第一份相同才允许提交，变化则以新 fingerprint
  重新开始观察。
- 两次 Tushare 观察都必须满足三类 index、三类 daily、分页终态、日期、空/重复 key 和
  `index code set ⊆ daily code set`。不能用“fingerprint 相同”掩盖结构错误。

index run config 后续应同时携带最小 prod 完成 fingerprint 和 Tushare source fingerprint。index writer 在
promote 前重新确认 prod 完成状态没有继续变化，并重新请求 Tushare；写入内容的 fingerprint 必须等于 sensor
冻结的 Tushare source fingerprint。prod 内容与 Tushare 内容是否逐条相等不再是 promote 条件。

daily writer 继续完整分页请求 Tushare，保留三类 category、字段、日期、主键和同日 raw index 覆盖门禁；
prod identity 差异只写聚合诊断，不得否决一份结构闭合且覆盖同日 raw index 的稳定 Tushare daily 结果。

member writer 的首轮请求、分页和 DuckDB 临时表保持不变。首轮与 prod 有差异时，按 missing 与 extra pair 的
`ts_code` 并集生成唯一、排序后的异常板块范围，只对这些板块再请求一次：

```text
首轮 Tushare member 全量请求
  -> 结构、分页、日期、请求代码、空/重复 key 全部通过
  -> 与 prod 只读 pair 做诊断性双向差集
  -> 无差异：直接 promote
  -> 有差异：只重新请求差异涉及的板块
  -> 同一板块第二份完整规范化 Tushare raw row set == 第一份：认定源端稳定，采用 Tushare
  -> 第二份发生变化、请求失败或预算不足：fail closed，不 promote
```

第二轮必须替换 DuckDB 中对应板块的首轮行，再执行结构和同日关系校验。最终允许保留非零 prod 差异，但必须
记录 prod missing/extra 计数、稳定确认板块数、第二轮请求数和最终 Tushare source fingerprint；不得记录完整
pair 或代码全集。2026-08-18 第二次失败涉及 15 个唯一异常板块，不能把 23 个 pair 差异误算为 23 次请求；
正式开发前仍要用只读 profiling 核定各板块实际分页数和剩余预算。

##### 5.5.7.4 性能和失败边界

| 路径 | 当前工作量 | M10.2 最大增量 | 硬边界 |
| --- | ---: | ---: | --- |
| index sensor，prod/Tushare 一致 | 现有两轮 prod 观察 + 4 个 Tushare 逻辑请求 | 0 | 单 tick 仍小于 10 秒 |
| index sensor，内容不一致 | 同上 | 下一 tick 增加 4 个 Tushare 逻辑请求 | 不在一个 tick 连续做两轮，不请求 member |
| index/daily writer | 现有完整 Tushare 请求 | 只增加 fingerprint/诊断计算 | 不增加全量第二遍请求 |
| member writer，无差异 | 约 1,022 个板块请求 | 0 | 共享 `1,200` 次、`600s` 预算 |
| member writer，有差异 | 约 1,022 个板块请求 | 只重试差异涉及的板块及其分页 | 不重置 runner，不做全市场第二遍 |

任一 Tushare 结构错误、分页未终止、failed/unattempted code、两份 source fingerprint 不同、member 差异板块
第二份结果变化、剩余请求数/时间不足或 writer 与 sensor source fingerprint 不同，都必须在正式路径提升前
失败。prod 不可用或完成状态仍变化时仍不提交当前日 run，因为它承担的是开始生产的时机门禁，而不是内容真相。

##### 5.5.7.5 P0 只读门禁与实际结果

进入代码修改前必须先完成一次只读 profiling，至少输出：最近实际日期的 prod/Tushare index、daily identity
差异；2026-08-18 的 15 个异常板块两轮 Tushare 完整 raw row fingerprint、pair count、分页数、请求数和
耗时；现有 sensor/run
config/cursor 的唯一消费者清单。若 Tushare 同一历史日期在有界间隔内仍持续变化，或差异板块重试使 member
超过 `1,200` 次/`600s`，停止并重新设计，不能靠放宽预算或取消完整性门禁继续。

P0 已于 2026-08-19 完成，报告为
`/private/tmp/dc_board_m102_p0_profile_20260819_011903.json`：15 个受影响板块连续两份完整 Tushare
member 快照间隔 300 秒，全部稳定，无变化板块；两轮共 30 次请求，实际请求耗时约 4.309 秒（不含固定等待）。
最近 5 个实际日期 `2026-08-12/13/14/17/18` 的 index/daily 对照均完成，每日 4 个 Tushare 逻辑请求，
与 prod 的聚合差异为 0。P0 `should_stop=false`，没有写 Lake、Dagster DB 或 prod。

自动重放失败 run 不属于 M10.2。若源事实权威纠偏后仍要让 sensor 自动再次提交 member，作为 M10.3 独立
评估 attempt run key、最大次数、间隔、cursor runtime state 和源端压力。

#### 5.5.8 实现、验证与切换顺序

1. 先完成 prod schema/identity 一致性只读审计：确认三张 prod 表的列、主键、同日集合关系，以及 member
   `(ts_code, con_code)` 与 Tushare 写入 schema 可直接对照；若字段或语义不一致，停止并修订本设计。
2. 修改现有 source probe、Raw sensor、Raw writer、member candidate planner 和对应 run-config helper；不新增
   平行 job/sensor 或兼容 fallback。
3. 本地 fake prod/Tushare 测试覆盖：21:15 前不请求源站、第一次快照不触发、第二次稳定快照触发、prod 变化、
   231/1022 部分源响应、writer 执行期 reference 变化、daily/member identity mismatch、member 前一日独有代码
   不再请求、所有失败不 promote。
4. 性能测试锁定完整 probe 的调用次数、prod 行数、DuckDB 差集耗时和 600 秒 sensor 间隔；稳定日 sensor
   目标小于 10 秒，任何路径不得出现按日期循环、Dagster event-history 扫描或全量 member 热路径请求。
5. M10 既有代码与本地 fake prod/Tushare 回归、静态门禁和性能测试已通过；其中 M10 定向回归 `99` 条，资产治理与 cursor contract 回归 `18` 条，Bootstrap/M7 样本调用也已通过。M10.1 已新增共享 request session、missing-only replace retry、聚合 materialization diagnostics 和静态门禁；本地定向 suite 共 `120` 条通过，覆盖首轮无差异零额外请求、仅缺失 pair 的定向重试成功、多个板块排序重试、重试后仍缺失、extra/重复/日期/请求错误不重试、跨轮总请求数/总耗时不足时不 promote，以及 sensor 热路径零新增 member 请求。正式环境只读 source-finalization 审计、`dg check defs` 和 sensor 启用仍须单独批准。M10/M10.1 均不包含 Lake 回补、prod 写入或历史 event 补录。
6. M10.2 已一次性切换 source probe、index sensor、三个 Raw writer、run config、M7 sample 与历史 bootstrap
   调用方；旧 reference class/helper/config alias 在 active production source 中为零。定向 unittest 共 `128` 条通过，
   bootstrap pytest 共 `3` 条通过，覆盖 prod 差异仅诊断、两份 Tushare source 稳定确认、writer source hash
   复核、member 双向差异板块定向确认、共享请求预算和失败不 promote。M10.2 没有触发 run，没有写 Lake、
   Dagster DB、prod 或 dynamic partitions。`dg check defs`、正式只读演练和生产启用仍须单独批准。

#### 5.5.9 2026-07-24 正式历史恢复记录

2026-07-26 按 M10/M10.1 进行了受控恢复，报告如下：

- `dg check defs` 成功加载当前 definitions；prod reference 为 `1,022` 条 index、`1,022` 条 daily、`91,900` 条 member pair，fingerprint 为 `d4443e37...d52c35d`；完整 Tushare index/daily 对照为零差异。
- 已存在且正确的 Raw index/Raw daily、Silver index/Silver daily 和 Gold technical 没有重跑。仅运行 `raw_tushare_dc_member_update_job[2026-07-24]`（run `f1071ca3-2868-4265-81c4-3b992c2aa010`）和 `silver_dc_member_update_job[2026-07-24]`（run `3e4acedd-13ab-4ac8-a993-1fd1ede4b066`）。
- M10.1 首轮发现 `38` 个 missing pair，聚合为一个板块 `BK0477.DC`；定向轮增加 `1` 次请求后恢复全部 `38` 个 pair。最终 Raw member 为 `91,900` 行，prod 双向差集均为 `0`，总请求 `1,023`、耗时约 `170.7s`。
- 7 个资产文件、materialization 与 blocking check 均为 ready；Raw/Silver/Gold 的同日 code-set 关系均为零差异。最终报告：`/private/tmp/dc_20260724_m10_recovery_final_audit_20260726_195812.json`。
- 恢复期间暂停的当前 code location 6 个 dependent sensor 已恢复为 `RUNNING`；当日 `raw_tushare_dc_index_update_job_sensor` 按恢复前状态保持 `STOPPED`。该历史状态已在 2026-07-27 的日常启用记录中更新。

#### 5.5.10 2026-07-27 状态纠偏与当前日 Raw 启动记录

2026-07-23 的 `raw_tushare_dc_member` 曾在 member check 执行时与当时的 raw index 文件不一致，留下了
`same_day_board_relation_integrity` 失败事件。随后同日 raw index 被重新 materialize，当前 Lake 文件已经一致，但旧
check 状态不会自行重算。经现有 `raw_tushare_dc_member_core_check` 的同一套 DuckDB 语义复核，member 文件
`91,728` 行、同日关系差异为 `0`，因此只补录了一条绑定既有 member materialization `6815686` 的 runless
passed check event；没有重拉 Tushare、没有重写 Lake，旧失败事件保留为历史证据。计划与执行报告分别为：
`/private/tmp/dc_member_status_recovery_plan_20260727_211617.json`、
`/private/tmp/dc_member_status_recovery_apply_20260727_211622.json`。

随后，使用当前存活 code server 启动 `raw_tushare_dc_index_update_job_sensor`。第一次 prod 快照在
21:17 记录 `1,022` 条 index、`1,022` 条 daily、`91,581` 条 member pair；第二次快照在 21:27 得到相同
fingerprint `58ff4253...564d8d4`，并通过完整 Tushare index/daily 对照，才自然提交 index run。实际结果：

- `raw_tushare_dc_index_update_job[2026-07-27]`：`57cb42f2-cabf-42e1-9969-36fca4aa1311`，成功。
- `raw_tushare_dc_daily_update_job[2026-07-27]`：`880af581-9e0c-4655-a6df-19c0067201f8`，成功。
- `raw_tushare_dc_member_update_job[2026-07-27]`：`1956c1ed-0c2c-4ea9-b823-fe100a6b7297`，成功；写入
  `91,581` 条 member pair，`1,022` 次请求、零缺失/额外 pair、零定向重试，核心 check 通过。

本次仅写入一条历史 check 状态事件，并把 index sensor 从 `STOPPED` 置为 `RUNNING`；没有手工提交日常 run，
daily/member 均由既有依赖 sensor 在同日 raw index ready 后自然触发。sensor 启动报告：
`/private/tmp/dc_member_status_recovery_start_index_sensor_20260727_211747.json`。

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

1. 显式绑定对应数据集的专属 partition set：`dc_index` 使用
   `cn_a_dc_index_trade_days`，`dc_member` 使用 `cn_a_dc_member_trade_days`，`dc_daily` 使用
   `cn_a_dc_daily_trade_days`；Silver/Gold 使用各自对齐的对应集合。
2. 只检查当前 partition 的文件，不查历史 event。
3. 通过 set-based DuckDB SQL 检查：文件/行数、分区日期、业务主键非空唯一、数据集专属身份字段。
4. 失败时返回：`failed_rules`、每条规则的 `reason_code`、检查行数、失败数量、少量样本和文件路径。
5. 正式实现使用 `build_check_metadata(...)`，不裸写 metadata key。

规则映射：

| 资产 | 共同规则 | 数据集专属规则 |
| --- | --- | --- |
| `dc_index` | 文件存在、行数>0、trade_date 等于 partition、`(ts_code,trade_date)` 非空唯一；三个请求都有终态、无失败/未尝试请求 | `.DC` 代码、`idx_type` 合法、指标数值域；三类全空失败，合法空类型必须有 source closure 证据 |
| `dc_member` | 文件存在、行数>0、trade_date 等于 partition、`(trade_date,ts_code,con_code)` 非空唯一；请求代码全部有终态、无失败/未尝试代码 | 板块/成分代码后缀、成分代码格式；合法空响应必须与请求终态区分，不能用缺行冒充成功 |
| `dc_daily` | 文件存在、行数>0、trade_date 等于 partition、`(ts_code,trade_date,category)` 非空唯一；日期分页闭环、源/写入行数一致 | `category` 三值、`.DC` 代码、OHLC/成交量字段域；同日 code set 覆盖 `dc_index`，允许 daily-only code |
| Silver 三者 | 同 Raw 规则 | 日期为 `DATE`、不含非交易日、清洗后主键保持唯一 |

分页完整性、源行数/写入行数对账、空结果保护、请求量和耗时不拆成额外 Dagster check；它们属于 asset 写入前置门禁和 materialization metadata。只有 source closure 通过的结果才允许 promote 和产生成功 materialization，核心 check 再对湖文件及同日板块族关系做最终自审计。这样既不丢失诊断，也不把每个执行事实扩成多条历史 check event。

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
| `dc_member` 日常 | 每个候选 `ts_code` 单独请求，单代码分页 | 当前约 1,023 次/日；固定最小间隔 `0.13s`、最多 1,200 次、最多 600s，超限整日 fail-closed |

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
- 专属分区注册 sensor 只读取交易日历并幂等补注册，不以固定时刻判断源站是否完成。
- M10 落地后，`raw_dc_index` 在 21:15 后先用两轮、每轮 3 个只读 prod 查询冻结当天基线；仅在第二轮
  一致后才执行一次完整 Tushare 对照（3 个 `dc_index` 类型 + 1 个 `dc_daily` 请求）。现有 600 秒间隔下
  两轮之间至少相隔 5 分钟。其余 Raw sensor 不再使用小页 Tushare probe。
- sensor 的 prod reference、完整 source 对照、日常 readiness 和 cursor 必须在 Dagster RPC 安全预算内；
  目标是稳定态 `<10s`，硬上限不得接近 `60s`，不能通过调大 timeout 规避。
- 完整 member source closure 只发生在 asset run 内；`dc_member` 的 1,022 级代码请求和约九万级 identity
  对照不能回流到 sensor 热路径。

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

### P4：Raw 日常接入（历史实现，待 M9-R 替换）

- 已新增三个 Raw asset、三个 job、三个 sensor 和 batch readiness helper，实际文件见 M4 实施状态；当时
  使用共享 `cn_a_index_trade_days`，后续由 M9-R 迁移到三个专属分区集。
- `dc_index` / `dc_daily` 按 Tushare 日期请求；`dc_member` 按 M1C 通过的候选代码逐个请求。
- 单日、分页、空结果、失败不覆盖和最近 10 日 readiness 已用本地临时数据覆盖；正式单日同步和全量 Bootstrap 留到 M7。

M4 的进入 M5 条件已满足：sensor 每 tick 最多提交一个 first-not-ready 分区，不读 Dagster event history，默认状态仍为 `STOPPED`，M3 writer/static gate 未回退。

### P5：Silver（历史实现，待 M9-R 替换分区口径）

- `defs/assets/dc_board_silver.py` 提供三个 `trade_date` 分区 Silver asset 和 writer。输入只取同日 Raw 与 SSE 交易日文件；日期转 `DATE`、代码 trim/uppercase、业务字段保留、非法行 fail-closed、同业务主键完全重复去重、同主键不同业务值拒绝。
- Silver writer 使用 DuckDB set-based SQL，输出先写唯一临时 Parquet，回读 schema/行数通过后才 `os.replace`；校验失败不覆盖已有目标文件。`dc_daily.category` 保留并继续参与 `(ts_code, trade_date, category)` 主键。
- `defs/checks/dc_board_silver_checks.py` 提供三个显式绑定 `cn_a_index_trade_days` 的单分区 blocking core check；这是历史实现快照。M9-R
  必须改为分别绑定 `cn_a_dc_index_trade_days`、`cn_a_dc_member_trade_days`、`cn_a_dc_daily_trade_days`，并补齐 source closure
  与同日关系门禁。check 只扫描当前 Silver 文件，检查文件/行数、schema、分区日期、业务主键非空唯一、数据集身份字段和数值域，并通过 `failed_rules`/`reason_code`/有限样本表达失败原因。
- Silver 资产只依赖对应同日 Raw，不把 `dc_index`、`dc_member`、`dc_daily` 的历史非等集关系变成日常硬 gate；本阶段不新增 Silver job/sensor，不接入 Dagster event history，不启用任何 sensor。
- M3/M4/M5 scoped suite 共 `123 passed`；定义加载可见三个 Silver asset 和三个 Silver check。验证没有运行 `dg launch`，没有启动 daemon/webserver，没有写正式湖或 Dagster DB。
- 临时性能样本 `/private/tmp/dc_board_m5_performance_20260714.json` 使用每类 3,000 行：`dc_index=24.094ms`、`dc_member=20.839ms`、`dc_daily=21.587ms`；三类 source/output 均为 3,000 行，重复删除为 0。该样本只证明单分区集合 SQL 和原子 Parquet 写入在临时环境内没有异常，不代表正式全量 Bootstrap 耗时。

进入 M6 的条件已满足：同日 Raw ready 后 Silver 能生成正确分区；失败不覆盖；跨数据集历史非等集不误阻断；三类 Silver check 均保持单分区可归因。

### P6：Silver Dagster 接入（历史实现，待 M9-R 替换分区与成功门禁）

- `defs/asset_guards/dc_board_silver_quality.py` 集中保存 Silver core check 与 batch readiness 共用的 schema、主键、身份和数值域规则。
- `defs/asset_guards/dc_board_silver_lake_readiness.py` 提供三个 Silver batch helper；历史实现按共享分区集读取最近 10 个 expected dates，每个 sensor tick 使用一个 DuckDB connection，不读取 Dagster event history、Tushare 或 Prod DB。M9-R 迁移后还必须加入 Raw source closure 和同日关系门禁。
- `defs/jobs/dc_board_silver.py` 提供三个只选择对应 Silver asset/check 的单分区 job；`defs/sensors/dc_board_silver_sensor.py` 提供三个默认 `STOPPED` sensor。
- Raw first-not-ready 早于或等于 Silver target 时阻断；Raw frontier 晚于 Silver target 时允许处理更早的 Silver 缺口；Silver 文件已存在但 blocking check 失败时不自动覆盖。
- M3-M6 scoped suite `137 passed`；定义加载可见 66 个 asset、162 个 asset checks，以及三组新增 Silver job/sensor。
- 临时 benchmark `/private/tmp/dc_board_m6_readiness_benchmark_20260715.json`：10 日 × 3 数据集共扫描 30 个文件，每个数据集 10/10 ready，单数据集耗时约 4.972ms-5.578ms。
- 本阶段未运行 `dg launch`，未启动 daemon/webserver，未启用 sensor，未写正式 lake、Dagster DB 或 event。

进入 M7 的条件已满足：Raw ready 可触发 Silver；Raw 未 ready 阻断 Silver；materialized check problem 不自动覆盖；sensor 热路径保持最近 10 日、单连接、无 event history 扫描。

### P7：全量 Bootstrap

- M7A/M7E 已完成：只读 Bootstrap planner/CLI 和临时三日期 Raw → Silver 联调通过；正式湖的 Raw/Silver 文件已在 M7F-M7I 生成并完成对账。
- `dc_index` / `dc_daily` 从历史起点请求 Tushare；`dc_member` 从 Prod DB 只读导出历史分区。
- 按日期分批生成 Raw staging，完成来源、schema、日期、主键、行数和性能门禁后原子 promote。
- Raw 全量通过后生成 Silver staging；文件审计通过后再规划 materialization/check 事件验收。
- 本阶段不自动启用 sensor；正式 Bootstrap、正式 lake promote 和事件补录必须分开审批。

### P8：事件验收与日常自动化（M8 已完成，M9-R 修复已落地）

- M8 已通过独立 CLI 完成事件补录：全量 materialization，最近 20 个交易日各补一个核心 check event。
- 事件补录只写 Dagster event，不重新运行 asset、不请求 Tushare/Prod、不修改 Raw/Silver Parquet。
- 原计划由运营启用 Raw/Silver sensor 已暂停；M9-R 代码修复已完成，但六个 Raw/Silver update sensor 和三个 calendar-only partition sensor 仍保持 `STOPPED`，待单独只读切换审计后再启用。

### M7A/M7E 实际验收记录（2026-07-15）

- 新增只读入口：`orchestrator.defs.bootstrap.dc_board_bootstrap_plan` 和
  `orchestrator.defs.bootstrap.dc_board_bootstrap_cli`。CLI 只暴露 `dry-run`，没有
  `apply`、Dagster event 或 lake promote 路径。
- 稳定审计边界使用显式 `--end-date 2026-07-14`。交易日历包含未来日期，且
  `2026-07-15` 在审计时尚未完成源数据，因此不把当日空结果误判为历史缺失。
- 最终报告：`/private/tmp/dc_board_m7_bootstrap_dry_run_20260715_v7.json`，
  `should_stop=false`，有效结束日 `2026-07-14`，预计 Raw/Silver 文件共 `2730` 个：
  `dc_index=377`、`dc_member=377`、`dc_daily=611`。
- 源行数：`dc_index=241,948`、`dc_member=25,418,099`、`dc_daily=596,200`。
  源审计耗时：`dc_index=232,424.293ms`、`dc_member=86,700.496ms`、
  `dc_daily=75,199.453ms`，总耗时 `394,717.231ms`。`dc_member` dry-run 使用
  Prod 只读 named cursor + `fetchmany` 的数据库侧 set-based 汇总，不重复把全量成员行
  传回本机；正式 writer 仍使用逐日流式导出。
- Tushare 请求统计：`dc_index=1,131` 次、`dc_daily=612` 次；Prod member 使用单次
  日期范围只读聚合查询和有界 cursor 读取。所有源日期均通过重复主键、身份字段、日期、空结果校验。
- 目标审计：Raw/Silver 2730 个目标均为 missing，invalid conflict 为 0，existing bytes 为 0；
  没有写入或覆盖正式数据湖。
- 一次全量审计中出现的 Tushare 空列响应已对 `dc_index/2024-12-30` 和
  `dc_daily/2026-05-20` 做单日重测，均通过；最终 v7 全量重跑无失败。该事实保留为源端
  瞬时异常记录，不修改 fail-closed 规则。
- 临时样本测试：`tests/test_dc_board_m7_sample.py` 覆盖起始/中间/最新三个日期，完成
  Tushare Raw、Prod-style member streaming Raw、Silver writer、schema/非空/无 staging
  残留验收；包含 M7A/M3/M5 相关测试共 `25 passed`。
- M7F/M7G 实际执行记录：正式 Raw 已生成 `1365` 个文件（`dc_index=377`、`dc_member=377`、`dc_daily=611`）。Raw 对账首次发现 `dc_index[2026-06-23]` 少 `496` 行后停止；经批准后使用已验证的临时 `1,021` 行 staging 定点原子重发布，旧文件备份为 `/private/tmp/dc_board_m7_dc_index_2026-06-23_before_republish_20260715T053028Z.parquet`，操作报告为 `/private/tmp/dc_board_m7_dc_index_republish_20260715T053028Z.json`。
- 重发布后 Raw 对账 `/private/tmp/dc_board_m7_raw_audit_20260715.json` 通过：三类 Raw 的 `ready_count` 分别为 `377/377`、`377/377`、`611/611`，行数与 v7 基线完全一致，missing/invalid/staging residue 均为 `0`。
- M7H/M7I 已完成：正式生成 `1365` 个 Silver 文件并通过 `/private/tmp/dc_board_m7_silver_audit_20260715.json`；最终汇总 `/private/tmp/dc_board_m7_final_reconciliation_20260715.json` 为 `should_stop=false`。Raw/Silver 合计 `2730` 个文件，无 staging 残留。

#### M8：Dagster 事件补录与验收（已完成）

- 新增 `orchestrator.defs.bootstrap.dc_board_events` 和
  `orchestrator.defs.bootstrap.dc_board_events_cli`。CLI 分为只读 `dry-run` 和显式
  `--confirm-event-write` 的 `apply`，不运行 Dagster job/sensor，不触碰 lake 文件。
- M8 dry-run `/private/tmp/dc_board_m8_events_dry_run_20260715.json` 通过：6 个资产全量
  readiness 绿色，动态分区缺口为 `0`，计划 materialization `2730`、最近 20 日核心
  check `120`，计划事件总数 `2850`。
- 正式 apply `/private/tmp/dc_board_m8_events_apply_20260715.json` 完成：写入
  `2730` 条 materialization event 和 `120` 条 check event，无跳过、无失败。
- 事件验收 `/private/tmp/dc_board_m8_events_post_verify_20260715.json` 通过：每个资产的
  materialization 分区数为 `377/377/611/611`，每个核心 check 正好有最近 20 个
  `asset_check_executions.partition`，所有 check 都绑定非空 target materialization storage id，
  readiness 全部通过，动态分区仍为 `6427`。
- post dry-run `/private/tmp/dc_board_m8_events_post_dry_run_20260715.json` 计划新增事件数为
  `0`，证明补录入口幂等。`raw_tushare_dc_member` 的 catalog event policy 同步修正为支持
  runless backfill，与 Prod DB 直写 Bootstrap 和 M8 事件口径一致。

## M9-R：板块分区与完整性门禁修复（历史实施记录）

旧版 sensor 不能直接启用，因为它使用共享 `cn_a_index_trade_days`，并把“文件存在且基础字段可读”当作足够的 ready 条件。以下保留 M9-R 代码和本地验证时的历史事实，不描述当前 Dagster instance 的 sensor 状态，也不改变历史 M8 event。

核心任务：按 5.4 的 R0-R8 顺序完成专属分区注册、有限源探测、writer source closure、合并核心 check 和同日板块族关系审计。M10 已取代其中的日常 source trigger 语义：小页 probe 不能再作为完整性依据。

完成条件：

1. 三类 Raw/Silver/Gold technical 使用各自正确的 partition set。
2. 分区注册只由交易日历驱动，源站更新时间只影响 Raw probe，不影响 partition registration。
3. 任何分页失败、未尝试对象、请求预算超限、源/写入行数不一致、代码集合不一致都不能产生成功 materialization。
4. 最近 10 日窗口中，Raw/Silver readiness 与核心 check 对“文件缺失”和“已生成但不完整”做出不同处理。
5. 连续 3 个实际交易日的 sensor tick 无 RPC 超时、无错误跨日期推进、无不完整文件覆盖。

R0-R8 已完成本地代码、静态门禁和临时 lake 验证；在正式切换前仍需只读确认 definitions、专属动态分区和当前 active run/cursor 状态。不得按旧 `cn_a_index_trade_days` 口径启用 Raw/Silver sensor；正式 sensor 切换另行审批。

### M9-R 已落地的实现边界

- 新增 `cn_a_dc_index_trade_days`、`cn_a_dc_member_trade_days`、`cn_a_dc_daily_trade_days`；Raw、对应 Silver、Gold daily technical 分别使用自己的日期域，历史 `cn_a_index_trade_days` 不再参与当前 `dc_board` 正式链路。
- 新增三个 calendar-only partition sensor。它们只读取 SSE open calendar 并幂等注册专属动态分区，不读取 Tushare、Prod DB、湖文件或 Dagster event history，也不以固定源站时间作为注册门禁。
- Raw update sensor 先做最近 10 个 expected trade dates 的 DuckDB readiness；M10 落地后，`raw_dc_index`
  仅在 prod 双快照冻结并完成完整 Tushare 对照后才提交一个 partition run，`dc_daily` / `dc_member` 等待同日
  `raw_dc_index` ready。文件存在但 core check 失败时只 skip，不自动覆盖。
- `dc_index`、`dc_daily`、`dc_member` 的完整 source closure 仍只在 writer run 内执行：分页、请求终态、失败/未尝试、字段、日期、主键、类别覆盖、源/写入行数和原子 promote 全部通过后才产生可消费的湖文件。
- Raw/Silver core check 与 readiness 继续使用单个 partition、单个合并 blocking check，并增加同日关系审计：`dc_daily` code set 覆盖 `dc_index`、`dc_member` 不得出现 index 外代码，且 member 请求集合有明确成功或合法空终态。关系失败不会进入 ready frontier。
- `dc_daily` / `dc_member` 的 Raw sensor 先确定自身首个未就绪目标，再比较 `raw_dc_index` 上游 frontier；上游首个未就绪日期早于或等于自身目标时阻断，晚于自身目标时允许补更早目标。不能因为上游窗口存在一个更晚缺口，就阻断自身更早日期。
- 小页 source probe 是 M9-R 当时的“现在是否值得尝试”筛选策略，不是成功证明；文件存在、row count > 0 或 probe 通过都不能单独判定更新成功。M10 已将当前日提交条件替换为稳定 prod 基线加完整 Tushare 对照，writer closure + 湖文件 core check + 同日关系闭环仍是最终成功条件。
- Dagster 可能先记录 materialization 再记录 blocking check 失败；因此本专项的“成功更新”定义为 readiness `ready=True` 和下游 frontier 可推进，而不是单独看 materialization event。

### M9-R 本地验证记录

- 新增分区注册、source probe、同日关系和 Raw category coverage 的正/负向测试；Raw/Silver/Gold 定义、sensor、静态门禁回归通过。本轮板块相关回归共 `155 passed`，仅保留 Dagster preview/deprecation warnings。
- 针对上游 frontier 修复，额外完成 Raw sensor 定向回归 `92 passed`：覆盖 `dc_daily` / `dc_member` 上游较晚缺口放行、上游同日缺口阻断、上游较晚 check failure 不阻断、单 tick 单 DuckDB connection 和无 event history 读取。
- 本轮不运行 `dg`，不读取正式 Dagster runtime，不启用 sensor，不写正式湖或 Dagster event。正式切换前仍需做只读 definitions/partition/cursor 审计和至少三个实际交易日观察。

## M10：稳定 prod 基线与完整 Tushare 对照（代码完成，待正式审计/启用）

M10 的唯一目标是拒绝“源端已经返回少量行、但当天目录或行情尚未完整”的中间状态。当前日先在 21:15
之后的两个 600 秒 sensor tick 读取 prod reference；两次内部闭合且 fingerprint 一致，第二次才冻结。冻结后
只做一次完整 Tushare 对照，随后将 reference fingerprint 传入既有 index job，writer 在 promote 前再复核。
`dc_daily`、`dc_member` 不再独立做小页探测，只在同日 raw index ready 后由 writer 完成完整闭环；member 候选仅来自当天 index 目录。完整口径、性能预算、测试和切换顺序以 5.5 为准。

## 10. 验收标准

### 数据正确性

- `dc_index` / `dc_daily` 的 Raw 在有效交易日内与 Tushare 显式字段契约一致；`dc_member` 的历史 Raw 与 prod 只读导出对账一致，日常 Raw 与 Tushare 显式字段契约一致。
- `dc_daily` 的 `category` 未被删除或降为非主键字段。
- 2,124 条已知错误不出现在最终 Raw/Silver。
- Silver 不含非交易日，不含空主键，不含重复业务主键。
- 日常交易日的 `dc_daily` 板块代码集合覆盖同日 `dc_index`，daily-only 板块完整保留；`dc_member` 的每个候选板块请求均有明确终态，合法空响应和失败/未尝试请求不能混淆。
- 历史 Bootstrap 的非等集差异仍保留在离线审计中，不被错误地回放成日常自动链路的成功事实。

### Dagster 正确性

- 六个 check 都是 partitioned check，单 run 单 partition。
- 运行后可按 `asset_check_executions.partition` 读取当前分区状态。
- sensor 不依赖 event history，不产生多分区聚合 check event。
- 更新成功必须同时满足 source request closure、湖文件/core check 和同日板块族关系闭环；source probe、文件存在或 row count>0 都不能单独判定成功。
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

### 12.7 2026-07-24 日常请求预算校准

M1C 的 300 秒是 2026-07-14 profiling 的历史基线，不再是当前生效值。2026-07-24 的正式 `raw_tushare_dc_member_update_job[2026-07-23]` 在无重试的情况下于 `300.070s` 只完成 `802 / 1,022` 个板块请求，触发 `max_elapsed_seconds_exceeded`，未写入或覆盖任何 Lake 文件。管理员据此确认将 DC member 的单分区总耗时预算调整为 **600 秒**。

本次只调整 `DC_BOARD_MAX_ELAPSED_MS`；`0.13s` 最小间隔、最多 `1,200` 次请求、最多 3 次重试、分页共享预算、source/prod identity 对照和 staging 原子 promote 均不变。600 秒仍是有界预算：任一代码失败、未尝试、超出 600 秒或对照不一致时，整日继续 fail-closed，不产生成功 materialization。

详细报告：`/private/tmp/dc_board_m1_tushare_validation_report_20260714.json`。

这些是离线审计和运维诊断事实，不写入业务 parquet 字段，也不进入 sensor cursor 的逐行明细。

### 5.5.8 M10.3：已知源端占位行治理（代码完成）

2026-08-27 的只读审计发现，`BK1675.DC`（名称“历史新高”）出现过一条源端占位记录：没有领先股票和领先股票代码，涨跌幅、领先股票涨跌幅、总市值、换手率均为 0，涨跌家数为空。该行同时出现在 prod `core_serving.dc_index` 与 Tushare 返回中；2026-08-12 Tushare 没有该行，2026-08-28 又返回了带真实领先股票和统计值的正常行。

不能按名称单独过滤，因为名称为“历史新高”或“历史新低”的正常板块记录也可能带真实统计信息。只有以下条件全部成立时，才认定为源端占位行：

- `name` 为“历史新高”或“历史新低”；
- `leading` 为空或为 `-`，`leading_code` 为空；
- `pct_change`、`leading_pct`、`total_mv`、`turnover_rate` 均为空或为 0；
- `up_num`、`down_num` 均为空。

代码职责固定为：Tushare source probe 在结构校验后过滤该行；Raw `dc_index` core check 和 Silver `dc_index` core check 将该行视为身份不合法；Silver writer 再次过滤它；`dc_daily` 同日覆盖关系和 `dc_member` 诊断只按过滤后的有效板块集合判断。prod 仍只承担完成时机和诊断职责，不向 Raw 写入或替换任何 prod 行。实现只复用既有请求结果和 DuckDB 查询，不增加 asset、check、job、sensor、动态分区或额外 source 请求。

当前本地 `raw/silver dc_index`、`raw/silver dc_daily` 的 `2026-08-27` 文件均不存在，因此该日期不执行物理删除或凭空重建；不改 prod、不改其它日期、不写 Dagster event。后续重新生成该日期时，Raw/Silver 会自动排除该占位行；若目标文件已存在，则必须走既有 staging 校验和原子替换。

实施结果：上述规则已落到当前 DC source probe、Raw/Silver 质量门禁、Silver 写入和同日关系校验；正常的“历史新高/历史新低”记录仍保留。针对 `2026-08-27` 的只读复核报告为 `/private/tmp/dc_board_20260827_placeholder_correction_audit.json`，四个目标文件均不存在，实际修正动作是 no-op，没有修改 Lake、prod 或 Dagster。DC 专项测试共 `99 passed`，占位行新增覆盖包含 source 过滤、Silver 过滤、Raw check 拒绝和关系校验。

### 5.5.9 M10.3-P：prod 历史错误行清理（已完成）

代码治理已经完成；prod 中的历史错误事实已按独立修正单元完成清理。该动作不是日常同步，也不改变 Tushare、Raw、Silver、Dagster 或 prod 表结构。

#### 当前只读基线

报告：`/private/tmp/dc_board_prod_cleanup_preflight_20260829.json`。

| 表 | 精确范围 | 当前结果 | 处理口径 |
| --- | --- | ---: | --- |
| `core_serving.dc_index` | `trade_date=2026-08-27 AND ts_code='BK1675.DC'` | 1 条 | 删除精确占位行 |
| `core_serving.dc_daily` | `trade_date=2026-08-27 AND ts_code='BK1675.DC'` | 0 条 | 不操作 |
| `core_serving.dc_member` | `trade_date=2026-08-27 AND ts_code='BK1675.DC'` | 1 条 | 删除孤立成员关系 |

目标 `dc_index` 行的类型为“概念板块”、名称为“历史新高”，并完全满足 `source_placeholder_row` 规则。目标 member 行是 `BK1675.DC - 688835.SH`。由于 `dc_index` 删除后该 member 会失去父板块，不能只删 index，必须把这两条错误/孤立事实作为一个修正单元处理。

#### 执行步骤

1. **只读复核**：执行前重新按完整占位条件核对 `dc_index` 恰为 1 条、`dc_member` 恰为 1 条、`dc_daily` 恰为 0 条；任一数量或字段变化即停止。
2. **精确备份**：将上述两张表命中的完整字段导出到 `/private/tmp`，生成行数、字段清单和 SHA-256 manifest。禁止全表导出、禁止把密码或连接串写入报告。
3. **单事务修正**：在同一事务中锁定并再次核对目标行，先删除同日同板块的 member，再删除满足完整占位条件的 `dc_index` 行；使用 `RETURNING` 核验删除数必须是 `1 + 1`。不执行 `dc_daily` 删除，不按日期范围、不按名称模糊删除。
4. **事务内回查**：确认目标 `dc_index`、`dc_member` 均为 0，`dc_daily` 仍为 0，并确认 2026-08-27 的 prod 三表内部闭环没有产生新的孤立关系；任何异常立即回滚。
5. **提交后只读审计**：输出 post-audit 报告，确认目标记录消失、非目标记录未改变、prod 完成快照不再包含 BK1675，且本地 Lake/Dagster 事实没有被触碰。

#### 边界与回滚

- 该修正只允许写 `core_serving.dc_index` 和 `core_serving.dc_member` 的上述精确行；不改 `index_basic`、`dc_daily`、Tushare、Lake、Dagster event/check/run 或动态分区。
- 预检查、精确备份、事务内数量核对任一不通过，禁止执行删除。
- 事务提交前可直接回滚；提交后如需恢复，使用精确备份另立恢复操作，不现场拼接插入语句。
- 修正完成后，2026-08-27 仍不会凭空生成 DG 文件；DG 该日期四个目标文件当前不存在，后续若重建，现有占位过滤规则继续生效。

#### M10.3-P 实施结果（2026-08-29）

- 按 `AGENTS.local.md` 规定，使用 `bash scripts/psql-remote.sh` 连接远程业务库；未使用无权限的 `lake_raw_writer` 账号，也未绕过受控入口。
- 执行前重新复核仍为 `dc_index=1`、`dc_member=1`、`dc_daily=0`；精确备份位于 `/private/tmp/dc_board_prod_cleanup_backup_20260829/manifest.json`。
- 单事务删除严格为：`core_serving.dc_member` 1 条、`core_serving.dc_index` 1 条，`core_serving.dc_daily` 0 条。事务内删除数和闭环校验均通过。
- 提交后目标记录均为 0；同日剩余 `dc_index=1030`、`dc_member=93176`、`dc_daily=1030`，成员孤儿数为 0，占位行数为 0。
- 提交后审计报告为 `/private/tmp/dc_board_prod_cleanup_post_audit_20260829.json`。本次没有修改 Lake、Dagster、Tushare 或动态分区。
