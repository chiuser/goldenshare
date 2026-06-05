# Dagster 新湖编排架构审计记录

> 日期：2026-06-04  
> 状态：阶段性审计记录，P0 已先行登记；后续仍需继续补充其它资产族的非 P0 风险。

## 审计范围

本轮审计对象是 `lake_console/orchestrator/src/orchestrator/defs/**` 中的新湖 Dagster definitions：

- assets
- partitions
- sensors
- jobs
- checks
- readiness helper
- runless event / bootstrap helper
- 与正式 asset/job/sensor 直接相关的 parquet 计算、写入和外部资源连接 helper

本轮只做静态审计：

- 未运行 `dg`
- 未运行 Dagster job / sensor / backfill / materialization / asset check
- 未读取正式 Dagster instance
- 未写正式数据湖
- 未访问 prod DB 或 Tushare

## 依据

已读取并按以下口径审计：

- 仓库根 `AGENTS.md`
- `lake_console/AGENTS.md`
- `lake_console/orchestrator/AGENTS.md`
- `dagster-expert` skill 中 Dagster assets、asset jobs、sensors、run status sensors、asset selection、definition metadata 等参考说明
- DuckDB 官方 PostgreSQL extension、configuration、performance tuning 文档
- Dagster 官方 concurrency 文档
- CodeGraph 索引与调用关系
- 当前真实代码

说明：本轮尝试按 `duckdb-docs` skill 使用本地 DuckDB docs FTS 索引，但当前环境缺少可用 `fts` 本地扩展，且在线索引刷新失败；因此 DuckDB 依据改用官方文档页面只读核验，不以历史印象替代。

关键约束：

- Dagster job 应只表达 asset selection / op 入口，不承接业务 SQL、路径拼接或文件写入。
- sensor 只提交满足门禁的 RunRequest，不在 sensor 中做重计算。
- 大体量 parquet 计算、过滤、join、merge、写入必须使用 DuckDB / SQL / COPY。
- 物理文件存在共享写入维度时，必须设计串行或等价互斥保护。
- 禁止把 prod DB 密码等敏感信息写入日志、metadata、run config 或可能进入错误栈的文本。

## 已确认 P0

### P0-1：Gold qfq 物理文件共享写入缺少正式互斥保护（已修复）

#### 现状

当前 `gold_stk_mins_qfq_*` 的 Dagster 逻辑分区是交易日：

- `cn_a_stock_mins_silver_trade_days`
- `gold_stk_mins_qfq_1m/5m/15m/30m/60m/90m/120m[trade_date]`

但真实物理文件按股票年份组织：

```text
data_lake/gold/quote/stk_mins_qfq/freq={freq}/ts_code={ts_code}/year={year}/part-000.parquet
```

也就是说，同一个 `freq + ts_code + year` 文件会承载同一年多个交易日的数据。

当前至少两条正式路径会写同一类 stock-year 文件：

- `stock_mins_qfq_daily_update_job`
  - 触发 `gold_stk_mins_qfq_*[trade_date]`
  - 资产内部调用 qfq 写回 helper，只替换当前 `trade_date`
- `stock_mins_qfq_factor_repair_job`
  - 非分区维护型 op job
  - 按 `trade_date` 检测因子变化后，批量回刷受影响股票的历史 qfq

写回核心会读取已有 stock-year 文件，删除 `replace_trade_dates` 对应行，再 union replacement rows，最后 `os.replace` 原子替换目标文件。

#### 证据

代码点：

- `lake_console/orchestrator/src/orchestrator/defs/paths.py`
  - `gold_stk_mins_qfq_path(root, freq, ts_code, year)`
- `lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py`
  - `gold_stk_mins_qfq_*` 使用 `cn_a_stock_mins_silver_trade_days`
  - `write_gold_stk_mins_qfq_asset_partition(...)`
- `lake_console/orchestrator/src/orchestrator/defs/stk_mins_qfq.py`
  - `write_gold_stk_mins_qfq_rows_to_year_files(...)`
  - `_write_gold_qfq_group_to_year_file(...)`
- `lake_console/orchestrator/src/orchestrator/defs/stk_mins_qfq_factor_repair.py`
  - `execute_gold_stk_mins_qfq_factor_repair(...)`
- `lake_console/orchestrator/src/orchestrator/defs/jobs/stock_mins_qfq_daily_update.py`
- `lake_console/orchestrator/src/orchestrator/defs/jobs/stock_mins_qfq_factor_repair.py`

静态扫描结果与当前修复状态：

- qfq daily job 与 qfq repair job 都只使用 `in_process_executor`
- 已采用 Dagster 官方 concurrency pools 作为正式互斥机制。
- 七个 `gold_stk_mins_qfq_*` assets 和 `stock_mins_qfq_factor_repair_op` 已统一声明 `pool="gold_stk_mins_qfq_writer"`。
- 当前代码已补静态门禁，禁止 qfq 写入口绕开统一 pool 常量。
- 正式 instance 已执行 pool limit 与 `dagster.yaml` 配置：`gold_stk_mins_qfq_writer` limit 为 `1`，pool granularity 为 `run`。

#### 为什么是 P0

`in_process_executor` 只能保证同一个 run 内部串行，不能保证两个 run 之间互斥。

如果出现以下任一情况：

- 人工同时启动两个不同日期的 `stock_mins_qfq_daily_update_job`
- daily qfq run 与 factor repair run 时间重叠
- backfill 或 UI 手动 run 造成同一年同股票同频度文件被两个 run 同时写

两个 run 可能同时读取同一个 stock-year 旧文件，各自生成临时文件并 `os.replace`。后完成的 run 会覆盖先完成 run 对同一目标文件写入的内容，导致先完成 run 的交易日行丢失或回退。

这不是 UI 噪音，也不是 metadata 小问题，而是可能造成正式 gold qfq parquet 文件内容不一致。

#### 已选修复方向

已选择 Dagster 官方 concurrency pools，不自造锁文件，不依赖人工记忆。

当前代码口径：

1. 统一 pool 常量：`GOLD_STK_MINS_QFQ_WRITER_POOL = "gold_stk_mins_qfq_writer"`。
2. 七个 gold qfq assets 使用该 pool。
3. `stock_mins_qfq_factor_repair_op` 使用同一 pool。
4. static gates 锁定该 pool 必须集中定义并被所有 qfq 写入口引用。

正式 instance 已执行口径：

```yaml
concurrency:
  pools:
    granularity: run
run_monitoring:
  enabled: true
  free_slots_after_run_end_seconds: 300
```

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
export DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home
.venv/bin/dagster instance concurrency set gold_stk_mins_qfq_writer 1
.venv/bin/dagster instance concurrency get gold_stk_mins_qfq_writer
```

该配置写入正式 `DAGSTER_HOME` 后持久生效；重启 Dagster web/daemon 后运行进程会读取新的 run 级别 pool granularity。后续不建议并行 backfill qfq 日期。

---

### P0-2：prod DB DuckDB 直连 SQL 内嵌 Postgres 密码，存在日志泄露风险（已修复）

#### 现状

`stock_mins_raw_update_from_prod_job` 的 prod DB 默认入口已从逐股票查询改为 DuckDB `postgres_query(...)` 批量抽取。

修复前连接方式：

1. `ProdPostgresResource.duckdb_connection_string()` 从环境变量拼出完整 Postgres conninfo。
2. conninfo 包含 `password=...`。
3. `build_prod_stk_mins_duckdb_source_sql(...)` 把完整 conninfo 拼进 DuckDB SQL：

```text
postgres_query('<完整 conninfo>', '<remote query>')
```

4. asset 执行时将这段 SQL 拼进：

```text
CREATE TEMP TABLE prod_stk_mins_source AS SELECT * FROM (<source_sql>) AS source_rows
```

#### 证据

代码点：

- `lake_console/orchestrator/src/orchestrator/defs/resources.py`
  - `ProdPostgresResource.duckdb_connection_string()`
- `lake_console/orchestrator/src/orchestrator/defs/prod_db/stk_mins.py`
  - `build_prod_stk_mins_duckdb_source_sql(...)`
- `lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py`
  - `write_raw_stk_mins_partition_from_prod_db(...)`
  - `_write_raw_stk_mins_rows_from_prod_db_source(...)`

#### 为什么是 P0

正常执行成功时，SQL 不一定暴露；但只要 DuckDB 报错、扩展报错、远程查询报错、类型转换报错或异常栈携带 query text，完整 SQL 有机会进入：

- Dagster run log
- Dagster UI error page
- Python exception message
- 本地调试输出

因为 SQL 里包含 prod DB password，这属于敏感信息泄露风险。

该问题与数据正确性无关，但属于安全 P0。

#### 已落地修复

已重新设计 DuckDB 连接方式，目标是：密码不得出现在可被日志打印的 source SQL 字面量里。

当前代码口径：

1. `build_prod_stk_mins_duckdb_source_sql(...)` 只生成基于固定 attach alias 的 source SQL：

```text
postgres_query('prod_raw_pg', '<remote query>')
```

2. 完整 Postgres conninfo 只在执行侧 `ATTACH '<conninfo>' AS prod_raw_pg (TYPE POSTGRES, READ_ONLY)` 使用，不再进入 `postgres_query(...)` SQL。
3. `ATTACH` 失败时抛出脱敏错误，不把原始 DuckDB exception chain 带入 Dagster 错误栈。
4. 测试已锁定：
   - source SQL 不得包含 `host=`、`user=`、`password=`、`dbname=`、`connect_timeout=`。
   - fake password 不得出现在 source SQL 或 attach 失败错误消息中。
   - prod DB 路径仍保持每个频度一次批量 SQL，不回退到逐股票查询。

该修复不改变 raw schema、路径、checks、job/sensor 边界，也不改变 `freq + trade_date window + 股票池` 的批量抽取性能模型。

## 已确认的非 P0 观察项

### O1：qfq repair 改写历史数据，但事件事实集中挂在目标 trade_date

当前 repair job 会根据某个目标 `trade_date` 的复权因子变化，回刷受影响股票的历史 qfq stock-year 文件。M11 后 repair 结果通过七个 gold qfq assets 上的 repair check event 记录，partition 是目标 `trade_date`。

这个口径是此前讨论中明确选择的方案：不新增 `gold_stk_mins_qfq_factor_repair_summary`，不为每个被改写的历史日期补 materialization event。

它不是本轮 P0，因为这是已拍板的观测模型；但长期看会带来一个认知边界：

- 物理历史文件会被 repair 更新。
- Dagster 上历史日期 partition 的 materialization/check event 不会逐个刷新。
- 要判断某次 repair 做了什么，需要看目标日期的 repair check metadata，而不是看所有历史 partition 的最近 materialization 时间。

文档需要持续把这个边界写清楚，避免误把历史 partition event 当作“该行从未被后续 repair 改写”。

### O2：run status 飞书 sensors 未限定 monitored jobs，但默认 STOPPED

当前 `feishu_run_started_sensor`、`feishu_run_succeeded_sensor`、`feishu_run_failed_sensor` 没有设置 `monitored_jobs`，按 Dagster run status sensor 语义会面向 code location 内 run 状态。

由于三个 sensor 均默认 STOPPED，暂不构成 P0。

如果未来启用，需要单独确认通知范围，否则容易重新放大噪音。

### O3：部分 full snapshot 或小表资产使用 Python 收集少量 rows 后写入 DuckDB

例如股票身份映射、namechange、stock_basic 等 full snapshot 资产里存在 `fetchall`、`executemany`、`Counter` 等 Python 逻辑。

目前这些对象规模相对有限，尚未判断为 P0；但后续性能审计应按数据规模分级：

- 小型配置/映射表可以接受 Python 轻量处理，但必须有规模上界。
- 日线、分钟线、历史批量、repair、全市场大表必须继续走 DuckDB/SQL/COPY。

### O4：qfq daily / factor repair sensor readiness 在稳定态逐 check 深扫 event history

当前 `stock_mins_qfq_daily_sensor` 和 `stock_mins_qfq_factor_repair_sensor` 都调用通用 `asset_readiness_status(...)`。

该通用 helper 会对每个 blocking check 单独执行 `get_asset_check_execution_history(limit=5000)`，再从 history 中寻找绑定 latest materialization `storage_id` 的结果。qfq daily sensor 稳定态会评估 silver 五频度、adj factor 两资产和 qfq gold 七频度，约 108 次 check history 扫描；factor repair sensor 会评估 qfq gold 七频度，约 56 次 check history 扫描。

这已经被观测为 60 秒 sensor tick 超时风险。它不直接写业务数据，也不是 qfq 文件生产失败，所以不列为数据一致性 P0；但它会让 sensor tick 报 `DEADLINE_EXCEEDED`，影响自动触发观测和后续触发节奏。

已选修复方向：

1. 不改通用 `asset_readiness_status(...)` 的单分区语义。
2. 只为 qfq daily / repair sensor 新增专用 run-event 批量 readiness helper。
3. 先取目标日期各 asset 的 latest materialization，再按 `run_id` 分组，每个 run 只读一次 run event log。
4. 用 `asset_key + check_name + target_materialization_data.storage_id` 精确匹配 latest materialization 的 blocking check result。
5. missing materialization、failed check、missing latest check result、非 terminal check result 都 fail closed。
6. 两个 sensor 增加同一目标日期已提交 run 后的 cursor 快路径，避免稳定态重复深查。
7. 不新增独立 repair sensor、summary asset、readiness asset、数据库表或配置项，不改 job selection、run key、tags、asset/check definitions。

性能门槛：

| 路径 | 当前成本 | 目标成本 | 拒绝阈值 |
| --- | --- | --- | --- |
| qfq daily 首次决策 tick | 约 14 次 materialization 查询 + 108 次 check history 扫描 | 约 14 次 materialization 查询 + 不超过 4 次 run event log 读取 + 0 次 check history 扫描 | 经审批的正式只读 dry-run 超过 10 秒拒绝上线 |
| factor repair 首次决策 tick | 约 7 次 materialization 查询 + 56 次 check history 扫描 | 约 7 次 materialization 查询 + 不超过 1 次 qfq run event log 读取 + 0 次 check history 扫描 | 经审批的正式只读 dry-run 超过 5 秒拒绝上线 |
| 同一目标日期已提交 run 后的稳定 tick | 仍可能重复 readiness 深查 | cursor 快路径直接 skip | 本地单测超过 2 秒拒绝上线 |

代码落地前必须先在 `dagster-stk-mins-asset-design.html` 和 `dagster-stk-mins-qfq-90-120-assets-plan.md` 中保持同一口径；开发阶段不得运行正式 Dagster job/sensor/backfill/materialization/check。

## 当前阶段结论

截至当前阶段，已确认 4 个 P0，均已完成代码和测试收口：

1. Gold qfq stock-year 共享物理文件缺少正式互斥保护；当前已加 Dagster pool 标记和门禁，正式 instance 已配置 pool limit 与 run granularity。
2. prod DB DuckDB 批量抽取 SQL 内嵌 Postgres password，存在失败日志泄露敏感信息的风险；当前已改为 DuckDB attach alias source SQL，并增加脱敏测试。
3. 正式 DuckDB 连接没有统一 temp/spill/thread/memory 治理，且 qfq 写入 helper 绕过 `DuckDBResource` 直接开连接；当前已收敛到统一 `connect_configured_duckdb(...)` 入口。
4. prod DB DuckDB attach 未声明 `READ_ONLY`，没有在 DuckDB extension 层强制只读；当前已修正为统一 attach options：`TYPE POSTGRES, READ_ONLY`。

P0-2 失败分区按正常重跑恢复业务数据即可。

---

### P0-3：正式 DuckDB 连接缺少统一 temp/spill/thread/memory 治理

#### 现状

当前 `DuckDBResource.connect()` 只是创建内存库连接：

```python
connection = duckdb.connect(database=":memory:")
```

没有设置：

- `temp_directory`
- `max_temp_directory_size`
- `memory_limit`
- `threads`

同时，部分重型正式路径没有使用 `DuckDBResource`，而是直接调用 `duckdb.connect(...)`。最典型的是 gold qfq 写回 helper：

```python
with duckdb.connect(database=":memory:") as connection:
```

该 helper 是 daily qfq asset 和 factor repair 的共同写回核心，属于正式 gold 文件生产路径。

#### 证据

代码点：

- `lake_console/orchestrator/src/orchestrator/defs/resources.py`
  - `DuckDBResource.connect()`
- `lake_console/orchestrator/src/orchestrator/defs/stk_mins_qfq.py`
  - `write_gold_stk_mins_qfq_rows_to_year_files(...)`
  - `_write_gold_qfq_group_to_year_file(...)`
- `lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_mins_qfq_bootstrap_events.py`
  - event 补录年度审计通过 `DuckDBResource` 连接运行大批量 gold/silver/factor 对账

静态扫描结果：

- `lake_console/orchestrator/src/orchestrator/defs/**` 下仍存在大量 `duckdb.connect()` 直接调用。
- 测试文件中的直接连接不构成生产问题；正式 `assets/checks/bootstrap` 路径中的直接连接需要分级治理。
- qfq 写回是已确认重型正式路径，不能作为“小表例外”处理。

DuckDB 官方文档依据：

- DuckDB 支持通过 `SET` / `PRAGMA` 配置运行参数。
- `temp_directory`、`max_temp_directory_size`、`memory_limit`、`threads` 都是可配置项。
- DuckDB 对超过内存的工作负载会使用临时目录；线程数过高也可能拖慢大查询。

#### 为什么是 P0

分钟线、qfq、历史 event 审计和 repair 都是大体量 DuckDB 查询场景。如果不显式设置 temp/spill 目录和上限，风险包括：

- 大查询 spill 到默认 `.tmp` 或不可控系统目录，污染仓库或占满系统盘。
- 多个 Dagster run 同时执行时，每个 DuckDB 连接独立使用默认线程和内存，无法统一限流。
- 即使以后修正 `DuckDBResource`，绕过 resource 的 qfq 写回 helper 仍继续失控。

这违反 `orchestrator/AGENTS.md` 中 Parquet 计算与历史批量审计的性能门禁，也会直接影响正式任务稳定性。

#### 已落地修复方案

P0-3 的正式原则是：**正式 `defs/**` 生产路径不再直接调用 `duckdb.connect()`**。

更准确地说：

- 允许：统一 DuckDB 连接 helper 内部调用一次 `duckdb.connect(...)`，因为最终必须创建连接。
- 禁止：asset / check / bootstrap / qfq / repair / sensor readiness helper 各自直接 `duckdb.connect()`。
- 允许例外：测试文件可以直接创建临时 DuckDB 连接；`src/orchestrator/audits/**` 是离线审计工具，暂不纳入本 P0 强制范围，但后续也建议逐步复用统一 helper。

第一版不新增运营配置项，不把配置散落到 env / YAML / run config。连接参数作为 orchestrator 内部固定契约，由统一 helper 集中定义；未来如需对外可调，必须另做配置项审计。

已落地默认值：

| 参数 | 值 | 说明 |
|---|---:|---|
| `temp_directory` | `/Volumes/datasource/.goldenshare_duckdb_tmp` | DuckDB spill / 临时文件统一落到数据盘，避免污染仓库、系统盘或不可控临时目录。 |
| `max_temp_directory_size` | `512GB` | 临时目录上限，避免异常查询无限制占用磁盘。 |
| `memory_limit` | `16GB` | 单 DuckDB 连接内存上限。 |
| `threads` | `4` | 控制单连接并行度，避免多个 Dagster run 同时执行时把 CPU、内存和 IO 打满。 |
| `preserve_insertion_order` | `false` | 放弃保序成本；正式输出排序必须由 SQL `ORDER BY` 显式表达。 |

落地方式：

1. 新增统一连接契约。
   - 建议在 `defs/resources.py` 或独立 `defs/duckdb_connection.py` 中定义 `DuckDBConnectionSettings` 和 `connect_configured_duckdb(...)`。
   - `connect_configured_duckdb(...)` 是正式代码中唯一允许调用 `duckdb.connect(...)` 的位置。
   - helper 创建 `temp_directory`，再创建 `:memory:` 连接。
   - helper 必须设置或校验上述五个参数；可通过 `duckdb.connect(config={...})` 或连接后 `SET` 实现，但最终必须用 `duckdb_settings()` 只读核验当前连接参数。
   - 如果临时目录不可创建、配置未生效或参数非法，直接抛清晰错误，不进入数据读写。

2. `DuckDBResource.connect()` 收敛到统一 helper。
   - 所有 Dagster asset / check / op / bootstrap helper 默认通过 `DuckDBResource` 取得连接。
   - 保留现有 resource 名称 `duckdb`，不改 Definitions 资源键，不影响 job/sensor selection。

3. 清理正式重型路径。
   - 第一批必须清理：
     - `defs/stk_mins_qfq.py`：daily qfq、factor repair plan、stock-year 写回 helper。
     - `defs/assets/stk_mins.py`：raw/silver/gold 分钟线正式写入路径。
     - `defs/bootstrap/stk_mins_qfq_bootstrap_events.py`：gold qfq runless event 年度审计。
     - `defs/bootstrap/stk_mins_silver_bootstrap_events.py`：silver 历史 event 审计。
     - `defs/bootstrap/adj_factor_*_bootstrap_events.py`：adj factor 历史 event 审计。
   - 第二批清理其它正式 assets/checks 中的直接连接；即使当前是小表，也不应继续扩散裸连接习惯。

4. 静态门禁。
   - `src/orchestrator/defs/**` 禁止出现 `duckdb.connect(`，唯一白名单是统一连接 helper 文件。
   - `tests/**` 允许。
   - `src/orchestrator/audits/**` 暂不作为 P0 强制对象；若后续 audit CLI 写正式 lake 或正式 event，必须改走统一 helper。

5. 文档与编码规范同步。
   - `orchestrator/AGENTS.md` / `CODING_STANDARDS.md` 应补充：正式 DuckDB 连接只能走统一 helper / `DuckDBResource`，不得在生产路径裸连。
   - 设计文档必须记录上述五个默认值和“未来如需配置化必须先做配置审计”的边界。

#### 落地范围与验收

| 阶段 | 内容 | 验收 |
|---|---|---|
| P0-3A | 新增统一连接 helper，`DuckDBResource.connect()` 改用 helper。 | 单元测试验证 `temp_directory/max_temp_directory_size/memory_limit/threads/preserve_insertion_order` 生效；临时目录不可用时失败。 |
| P0-3B | 改造 qfq daily / repair / stock-year 写回路径，禁止 qfq helper 自己开连接。 | qfq M7/M8/M9 相关测试通过；`defs/stk_mins_qfq.py` 不再出现 `duckdb.connect(`。 |
| P0-3C | 改造分钟线 raw/silver/gold、history event、adj factor event 等重型正式路径。 | stk_mins、adj_factor、bootstrap event 测试通过；重型路径不再裸连。 |
| P0-3D | 清理剩余正式 assets/checks 中的裸连接，或在极少数小表场景写明临时白名单和上界。 | `rg "duckdb\\.connect" src/orchestrator/defs` 只命中统一 helper。 |
| P0-3E | 增加 static gate 并更新文档/编码规范。 | static gates 阻止新增正式裸连接；文档与代码口径一致。 |

当前代码已经完成上述阶段：`DuckDBResource.connect()` 统一调用 `connect_configured_duckdb(...)`；`src/orchestrator/defs/**` 里除 `duckdb_connection.py` 外不再出现 `duckdb.connect(`。

#### 性能与稳定性预估

该修复目标不是让每个单独 SQL 都更快，而是让正式运行可控：

- 单个大查询可能因 `threads=4` 比默认全核略慢，但多个 Dagster run 并行时整体更稳定。
- spill 目录固定到数据盘，避免系统盘或仓库目录被大查询临时文件打爆。
- `memory_limit=16GB` 降低单连接 OOM 和系统内存挤压风险。
- `max_temp_directory_size=512GB` 给历史 qfq / 分钟线 / event 审计足够空间，同时保留硬上限。
- `preserve_insertion_order=false` 减少不必要的保序开销；所有正式输出排序必须由 SQL 显式 `ORDER BY` 保证。

#### 不做事项

- 不改变 lake path、asset key、partition、checks、job selection、sensor 触发逻辑。
- 不把 DuckDB 参数暴露为 run config。
- 不新增数据库表、summary asset 或 readiness asset。
- 不运行正式 Dagster job/sensor/backfill，不写正式 lake；本 P0 先改连接治理和测试。

---

### P0-4：prod DB DuckDB attach 未强制 READ_ONLY（已修复）

#### 现状

P0-2 已经修复了 `postgres_query(...)` 内嵌完整 conninfo 和 password 的问题；当前 source SQL 只引用 attach alias。

历史问题是执行 attach 的 SQL 曾经是：

```text
ATTACH '<conninfo>' AS prod_raw_pg (TYPE POSTGRES)
```

没有声明 `READ_ONLY`。当前已改为：

```text
ATTACH '<conninfo>' AS prod_raw_pg (TYPE POSTGRES, READ_ONLY)
```

#### 证据

代码点：

- `lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py`
  - `_attach_prod_postgres_database(...)`

旧代码：

```python
attach_sql = (
    "ATTACH "
    + duckdb_string(postgres_connection_string)
    + f" AS {PROD_STK_MINS_DUCKDB_ATTACHED_DATABASE} (TYPE POSTGRES)"
)
```

DuckDB 官方 PostgreSQL extension 文档依据：

- PostgreSQL extension 允许 DuckDB 直接读写 PostgreSQL。
- 文档提供 `ATTACH ... (TYPE postgres, READ_ONLY)` 口径，用于阻止写入操作。
- `postgres_query(attached_database, query)` 的第一个参数应是已 attach 数据库别名。

#### 为什么是 P0

当前 remote query builder 只生成 `SELECT`，且正式 prod 用户也应是只读用户；但代码层没有在 DuckDB extension 层强制只读。

这意味着未来只要出现以下任一情况：

- helper 改成直接查询 attach schema 而不是 `postgres_query(...)`
- remote SQL builder 被错误扩展
- prod DB 用户权限配置被放宽

DuckDB 连接本身没有第二道防线。

`lake_console` 对 prod DB 的长期口径是只读审计/抽取，不允许写生产库。缺少 `READ_ONLY` 是安全边界缺失，不应留给外部账号权限兜底。

#### 修复方向

已按以下口径修复，性能影响视为 0：

1. attach SQL 已改成：

```text
ATTACH '<conninfo>' AS prod_raw_pg (TYPE POSTGRES, READ_ONLY)
```

2. 测试已补齐：
   - attach SQL 必须包含 `READ_ONLY`。
   - attach 失败错误仍脱敏。
   - source SQL 仍不得包含 conninfo/password。
3. 文档保留 P0-2/P0-4 的区别：
   - P0-2 是“不泄露密码”。
   - P0-4 是“DuckDB extension 层强制 prod DB 只读”。

## 待继续审计

后续还需要继续补充：

- 除 qfq daily / factor repair 之外，其它 sensor 的触发边界与 readiness 口径是否存在遗漏。
- 所有 job selection 是否存在把共享基础资产顺手写入下游 job 的情况。
- runless event helper 是否存在历史批量逐分区深扫回退。
- ClickHouse serving sync 的 delete/insert 与 automation 并发边界。
- 全部 full snapshot asset 的并发保护是否需要从“文档建议”升级为正式门禁。
- 现有 static gates 是否覆盖本轮发现的两个 P0。
