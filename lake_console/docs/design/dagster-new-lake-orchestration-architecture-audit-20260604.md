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
- CodeGraph 索引与调用关系
- 当前真实代码

关键约束：

- Dagster job 应只表达 asset selection / op 入口，不承接业务 SQL、路径拼接或文件写入。
- sensor 只提交满足门禁的 RunRequest，不在 sensor 中做重计算。
- 大体量 parquet 计算、过滤、join、merge、写入必须使用 DuckDB / SQL / COPY。
- 物理文件存在共享写入维度时，必须设计串行或等价互斥保护。
- 禁止把 prod DB 密码等敏感信息写入日志、metadata、run config 或可能进入错误栈的文本。

## 已确认 P0

### P0-1：Gold qfq 物理文件共享写入缺少正式互斥保护

#### 现状

当前 `gold_stk_mins_qfq_*` 的 Dagster 逻辑分区是交易日：

- `cn_a_stock_mins_silver_trade_days`
- `gold_stk_mins_qfq_1m/5m/15m/30m/60m[trade_date]`

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

静态扫描结果：

- qfq daily job 与 qfq repair job 都只使用 `in_process_executor`
- 当前 definitions 中没有发现 Dagster concurrency pool、run queue、tag concurrency 或其它正式互斥配置
- 文档中已有“后续 job/backfill 必须串行，或用 Dagster concurrency 限制保护同一 gold qfq 文件族”的描述，但当前代码没有落地该保护

#### 为什么是 P0

`in_process_executor` 只能保证同一个 run 内部串行，不能保证两个 run 之间互斥。

如果出现以下任一情况：

- 人工同时启动两个不同日期的 `stock_mins_qfq_daily_update_job`
- daily qfq run 与 factor repair run 时间重叠
- backfill 或 UI 手动 run 造成同一年同股票同频度文件被两个 run 同时写

两个 run 可能同时读取同一个 stock-year 旧文件，各自生成临时文件并 `os.replace`。后完成的 run 会覆盖先完成 run 对同一目标文件写入的内容，导致先完成 run 的交易日行丢失或回退。

这不是 UI 噪音，也不是 metadata 小问题，而是可能造成正式 gold qfq parquet 文件内容不一致。

#### 修复方向

需要单独设计并落地正式互斥机制，不能靠人工记忆。

候选方向：

1. 使用 Dagster 官方 concurrency 机制保护 qfq 文件族写入。
   - 至少让 `stock_mins_qfq_daily_update_job` 与 `stock_mins_qfq_factor_repair_job` 共享同一个 qfq writer concurrency key。
   - 需要确认当前 Dagster 版本对 job/op/asset concurrency 的具体配置方式。
2. 对 qfq 写回 helper 增加运行期互斥保护。
   - 不建议优先自造锁文件；若确实需要外部锁，必须单独设计锁语义、恢复方式和失败处理。
3. 静态门禁必须补上：
   - qfq 写入 job/op/helper 必须声明或使用统一互斥口径。
   - 禁止新增其它入口绕开该互斥口径写 `gold/quote/stk_mins_qfq`。

在 P0 修复前，不建议同时启用 daily qfq sensor 和 factor repair sensor，也不建议并行 backfill qfq 日期。

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

2. 完整 Postgres conninfo 只在执行侧 `ATTACH '<conninfo>' AS prod_raw_pg (TYPE POSTGRES)` 使用，不再进入 `postgres_query(...)` SQL。
3. `ATTACH` 失败时抛出脱敏错误，不把原始 DuckDB exception chain 带入 Dagster 错误栈。
4. 测试已锁定：
   - source SQL 不得包含 `host=`、`user=`、`password=`、`dbname=`、`connect_timeout=`。
   - fake password 不得出现在 source SQL 或 attach 失败错误消息中。
   - prod DB 路径仍保持每个频度一次批量 SQL，不回退到逐股票查询。

该修复不改变 raw schema、路径、checks、job/sensor 边界，也不改变 `freq + trade_date window + 股票池` 的批量抽取性能模型。

## 已确认的非 P0 观察项

### O1：qfq repair 改写历史数据，但事件事实集中挂在目标 trade_date

当前 repair job 会根据某个目标 `trade_date` 的复权因子变化，回刷受影响股票的历史 qfq stock-year 文件。repair 结果通过五个 gold qfq assets 上的 repair check event 记录，partition 是目标 `trade_date`。

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

## 当前阶段结论

截至本阶段，已确认 2 个 P0，其中 P0-2 已在本轮修复：

1. Gold qfq stock-year 共享物理文件没有正式互斥保护，存在并发覆盖导致数据不一致的风险。
2. prod DB DuckDB 批量抽取 SQL 内嵌 Postgres password，存在失败日志泄露敏感信息的风险；当前已改为 DuckDB attach alias source SQL，并增加脱敏测试。

P0-1 仍需优先修正；它会影响 gold qfq 正式文件正确性。P0-2 已完成代码和测试收口，后续只需按正常失败分区重跑恢复业务数据。

## 待继续审计

后续还需要继续补充：

- 全部 sensor 的触发边界与 readiness 口径是否存在遗漏。
- 所有 job selection 是否存在把共享基础资产顺手写入下游 job 的情况。
- runless event helper 是否存在历史批量逐分区深扫回退。
- ClickHouse serving sync 的 delete/insert 与 automation 并发边界。
- 全部 full snapshot asset 的并发保护是否需要从“文档建议”升级为正式门禁。
- 现有 static gates 是否覆盖本轮发现的两个 P0。
