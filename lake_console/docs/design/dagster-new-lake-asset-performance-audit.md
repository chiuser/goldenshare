# Dagster 新湖 Asset 性能审计

审计日期：2026-06-04

## 审计目标

本轮审计只回答一个问题：当前新湖 Dagster asset、check、关键 helper 中，是否还存在违反性能门禁的实现，尤其是：

- 大体量数据读取、清洗、计算、合并、写 parquet 时，把明细行拉回 Python 循环处理。
- 本应使用 DuckDB SQL / `COPY` 的 lake 内计算或写入，被 Python list/dict/`executemany` 承担。
- check 或历史 helper 用小循环反复扫描大量 partition / 文件，导致正式运行或补 event 时耗时失控。

本轮只做静态代码审计，不运行 `dg`，不触发 Dagster job/sensor/backfill/materialization/check，不读取正式 Dagster instance，不写正式数据湖。

## 依据与范围

已读规则：

- 仓库根 `AGENTS.md`
- `lake_console/AGENTS.md`
- `lake_console/orchestrator/AGENTS.md`
- `lake_console/orchestrator/CODING_STANDARDS.md`

关键性能门禁摘要：

- 正式 lake Parquet 计算、过滤、join、聚合、去重、repair、merge、写入必须优先用 DuckDB SQL / `COPY`。
- Python 只能做参数校验、路径发现、批次规划、少量样本与汇总；如果 Python 处理数据，必须证明规模很小且有边界。
- 大范围历史审计或 event 补录不得按 partition/check 做碎循环；必须用集合、聚合计数和样本。
- 数据集同步性能是硬门禁；新增或修改同步方案必须明确请求量、分页次数、行数、文件数、事务边界和预估耗时。

审计范围：

- `lake_console/orchestrator/src/orchestrator/defs/assets/**`
- `lake_console/orchestrator/src/orchestrator/defs/checks/**`
- `lake_console/orchestrator/src/orchestrator/defs/prod_db/**`
- `lake_console/orchestrator/src/orchestrator/defs/tushare_api_io.py`
- `lake_console/orchestrator/src/orchestrator/defs/stk_mins_qfq.py`
- `lake_console/orchestrator/src/orchestrator/defs/stk_mins_qfq_factor_repair.py`
- `lake_console/orchestrator/src/orchestrator/defs/bootstrap/**` 中与历史生成、event 补录相关的 helper

CodeGraph 结果：索引正常，`fetch_prod_stk_mins_rows_for_stock_codes` 只有 `raw_stk_mins` prod DB 路径调用；`_write_raw_stk_mins_rows` 由 Tushare raw 和 prod DB raw 两条路径复用；`build_latest_announcement_namechange_timeline` 的正式资产调用点是 `silver_namechange`。

## 严重度定义

| 等级 | 含义 | 处理原则 |
|---|---|---|
| P0 | 默认生产链路中存在大体量 Python 明细处理或写入，已经违反性能门禁 | 必须优先修正，修正前不应继续扩大日常依赖 |
| P1 | 正式 asset/check 中存在明显性能风险，当前可能可跑，但缺少批量化或规模门禁 | 应在正式放大使用前修正或补强边界 |
| P2 | 当前规模较小或属于人工/历史工具，但实现形态容易被误用 | 需要文档、测试或静态门禁约束，防止复制到大数据链路 |

## 发现的问题

### P0：`raw_stk_mins` prod DB 默认路径曾把全市场分钟明细搬进 Python

代码位置：

- `lake_console/orchestrator/src/orchestrator/defs/prod_db/stk_mins.py:41`
- `lake_console/orchestrator/src/orchestrator/defs/prod_db/stk_mins.py:61`
- `lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py:574`
- `lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py:597`
- `lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py:764`
- `lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py:782`

审计时现状：

- prod DB 查询已经从“逐股票查询”改成“单频度一次批量 SQL”。
- 但是 `fetch_prod_stk_mins_rows_for_stock_codes(...)` 仍然 `fetchall()`，把单日全市场、单频度的所有分钟明细行拉回 Python。
- `_fetch_raw_stk_mins_rows_from_prod_db(...)` 对每行做 Python dict 归一化。
- `_write_raw_stk_mins_rows(...)` 再把 Python list 转成 `values`，通过 DuckDB `executemany` 插入临时表后写 parquet。

判断：

这是默认日常 `stock_mins_raw_update_from_prod_job` 的主路径。虽然查询次数不再按股票放大，但明细数据仍在 Python 内存和 `executemany` 中流转。对 1m 全市场单日数据，这不符合“正式 lake Parquet 写入必须用 DuckDB SQL / COPY，Python 不做大明细处理”的门禁。

影响：

- 单日同步耗时会被 Python 行对象构造、内存分配、`executemany` 放大。
- 1m 频度最容易出现慢、卡、内存膨胀。
- 这也是 2026-06-01/02 补数时暴露出的核心性能问题之一。

优化空间预估：

当前实现虽然已经把 prod DB 查询次数降到“每个频度 1 次”，但单日全市场分钟线仍然会在 Python 中形成多份明细行对象：

1. `psycopg2` `fetchall()` 返回 prod DB 明细行。
2. `_fetch_raw_stk_mins_rows_from_prod_db(...)` 逐行归一化，生成第二份 Python dict。
3. `_write_raw_stk_mins_rows(...)` 再构造 `values` 嵌套 list。
4. DuckDB `executemany` 再逐行插入临时表，最后 `COPY` 写 parquet。

按当前 A 股约 5,500 只上市股票估算，一个正常交易日大致是：

| 频度 | 每股 bar 数粗估 | 单日行数粗估 |
|---|---:|---:|
| 1m | 240 | 约 132 万 |
| 5m | 48-49 | 约 26-27 万 |
| 15m | 16-17 | 约 9 万 |
| 30m | 8-9 | 约 5 万 |
| 60m | 5 | 约 2.8 万 |

也就是说，默认日常全五频度约 170-180 万行，其中 1m 占绝大部分。当前路径会对这些行做 Python dict 构造、字段归一、list 再包装和 `executemany` 插入，实际等价于把 170-180 万行在 Python 层搬运数轮。

修正后目标不是减少 prod DB 需要扫描的数据量，而是消灭 Python 明细搬运：

- prod DB 查询仍按频度批量执行，预计仍是每日 5 次左右。
- 字段 cast、`exchange` 推导、`vwap` 计算、排序、写 parquet 下推到 SQL / DuckDB。
- Python 不再持有全量 rows，只负责传参数、接 row count、记录 metadata。

预期改善：

| 指标 | 当前实现 | 修正后目标 | 预期改善 |
|---|---|---|---|
| prod DB 查询次数 | 每日约 5 次 | 每日约 5 次 | 不变 |
| Python 明细行对象 | 约 170-180 万行，多份拷贝 | 接近 0 | 大幅下降 |
| DuckDB 写入方式 | `executemany` 行插入后 `COPY` | SQL 结果直接 `COPY` | 写入阶段预计 3-10 倍改善 |
| 单日全链路耗时 | 受 Python 搬运和 `executemany` 放大 | 主要受 prod DB 查询和 parquet 写入影响 | 若当前瓶颈在 Python，整体预计 2-5 倍；若瓶颈在 prod DB 查询，预计 1.5-3 倍 |
| 内存峰值 | 可能达到数百 MB 到 1GB+，1m 最明显 | 由 DuckDB/SQL 流程控制 | 明显下降 |

以上是代码路径和行数量级推导，不是实测结果。PA1 落地前后必须补真实性能验收：

- 同一交易日、同一股票池、同一 prod DB source。
- 分别测 `1m` 单频度和五频度全量。
- 输出查询耗时、写 parquet 耗时、总耗时、row count、目标文件大小、Python 进程内存峰值。
- benchmark 输出写到临时目录，不写正式 lake；正式切换前必须确认新旧行数和 schema 完全一致。

当前修正状态：

- 已按 PA1 代码口径修正为 DuckDB `postgres` extension 直连 prod DB。
- `raw_stk_mins` prod DB 默认路径现在通过 `postgres_query(...)` 读取字段白名单。
- 字段 cast、`exchange` 后缀映射、`vwap=amount/vol`、排序和 `COPY ... TO parquet` 均在 DuckDB SQL 中完成。
- Python 不再 `fetchall()` 全量分钟明细，不再用 `executemany` 写默认 prod DB raw parquet。
- 资产名、job 名、sensor、raw schema、raw path、raw checks、目标文件复用/坏文件失败口径均保持不变。

仍需补充：

- 还没有做正式 1m / 五频度 benchmark。
- 由于本轮不写正式 lake，真实性能结论必须等下一次日常更新或单独批准的临时 benchmark 后回填。

已采用的修正方案：

- 保留现有 asset/job/sensor/path/check 名称与业务口径。
- 将 prod DB 到 raw parquet 的数据通路改成 DuckDB 主导：
  - 用 DuckDB `postgres_query(...)` 把 prod DB 查询结果直接交给 DuckDB。
  - `exchange`、`vwap`、字段 cast、排序都放进 SQL。
  - Python 只传 `freq/date/window/stock_pool` 参数和接收 row count、file path、异常样本。
- 单元测试必须禁止 prod DB 主路径出现“全量结果 list + `executemany` 写 raw parquet”的回退。

### P1：`gold_stk_mins_qfq_*` check 每个分区会用 Python 构造数千个股票年份文件路径

代码位置：

- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py:270`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py:278`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py:286`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py:868`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py:876`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py:893`

现状：

- M8B 已经把 8 个 qfq checks 合并成每频度一个 `multi_asset_check`，避免同一频度重复深扫。
- 但 `_gold_qfq_expected_paths(...)` 会从当日 silver 读取全部 `ts_code`，`fetchall()` 到 Python，再为每只股票构造 `freq/ts_code/year` 路径。
- 后续用 Python `path.exists()` 拆出 missing/existing，再把大量 existing paths 拼进 DuckDB `read_parquet([...])`。

判断：

这不是 Python 明细行计算，但它是正式 check 中的“文件级大循环”。单日单频度通常几千只股票，五频度就是几万次路径判断。日常可能还能接受，但历史补 event 或频繁 check 时会放大。

影响：

- check 可能成为 qfq 日常 job 的瓶颈。
- 路径存在性和 schema 检查在 Python 文件系统循环中做，难以利用 DuckDB 聚合能力。
- 如果未来股票数量或年份文件数量继续增加，耗时不可控。

建议修正：

- 优先做一次只读性能测量：单个最新交易日五频度 qfq checks 各耗时。
- 若耗时不可接受，改为按 `freq/year` 聚合审计：
  - expected code set 仍可从 silver 得到，但文件存在与 row count 尽量通过 DuckDB filename/glob/union 聚合。
  - Python 只保留缺失路径样本，不逐文件做完整逻辑。
- 静态门禁增加“qfq check 不得退回 8 个独立深扫 check”的约束。

### P1：`silver_namechange` 使用 Python 构建完整名称时间线

代码位置：

- `lake_console/orchestrator/src/orchestrator/defs/assets/namechange.py:71`
- `lake_console/orchestrator/src/orchestrator/defs/assets/namechange.py:79`
- `lake_console/orchestrator/src/orchestrator/defs/assets/namechange.py:93`
- `lake_console/orchestrator/src/orchestrator/defs/assets/namechange.py:112`
- `lake_console/orchestrator/src/orchestrator/defs/assets/namechange.py:217`
- `lake_console/orchestrator/src/orchestrator/defs/assets/namechange.py:223`
- `lake_console/orchestrator/src/orchestrator/defs/namechange_timeline.py:141`
- `lake_console/orchestrator/src/orchestrator/defs/namechange_timeline.py:150`
- `lake_console/orchestrator/src/orchestrator/defs/namechange_timeline.py:259`
- `lake_console/orchestrator/src/orchestrator/defs/namechange_timeline.py:276`
- `lake_console/orchestrator/src/orchestrator/defs/namechange_timeline.py:527`

现状：

- `silver_namechange` 把 raw namechange 全量 `fetchall()` 成 Python dict。
- 在 Python 中过滤当前上市股票、按代码和日期分组、选择公告、归并区间、找 overlap/multi-open/gap。
- 最终再用 `executemany` 写 DuckDB 临时表并导出 parquet。

判断：

namechange 规模远小于分钟线，不是 P0。但它是正式 silver asset 中的复杂业务计算，当前没有明确的行数上限、耗时估算和门禁。按规则，复杂计算默认应尽量 DuckDB 化；若保留 Python，需要证明这是“小而有界”的快照。

影响：

- 目前可运行，但后续如果源端历史扩大、逻辑继续叠加，容易变成无法维护的 Python 规则堆。
- check 中 `analyze_namechange_silver_rows(...)` 也复用 Python 时间线扫描，进一步扩大这种模式。

建议修正：

- 短期：在文档和测试中登记当前可接受上限，例如 raw rows、filtered rows、distinct code 数、最大耗时；超限时 fail fast。
- 中期：把能用 SQL 表达的部分移到 DuckDB：
  - 当前上市过滤。
  - 同 `ts_code/start_date` 最新公告选择。
  - overlap/multi-open/gap 聚合检查。
- Python 只保留少量人工冲突仲裁和样本格式化。

### P2：`silver_stock_identity_map` 是 Python full snapshot 构建，当前小规模但缺少上限门禁

代码位置：

- `lake_console/orchestrator/src/orchestrator/defs/assets/stock_identity_map.py:73`
- `lake_console/orchestrator/src/orchestrator/defs/assets/stock_identity_map.py:90`
- `lake_console/orchestrator/src/orchestrator/defs/assets/stock_identity_map.py:122`
- `lake_console/orchestrator/src/orchestrator/defs/assets/stock_identity_map.py:155`
- `lake_console/orchestrator/src/orchestrator/defs/assets/stock_identity_map.py:174`
- `lake_console/orchestrator/src/orchestrator/defs/assets/stock_identity_map.py:301`
- `lake_console/orchestrator/src/orchestrator/defs/assets/stock_identity_map.py:322`

现状：

- 读取 `silver_stock_basic` 和 `silver_namechange` 的小快照到 Python。
- 用 Python 构建 self mapping + seed mapping，再 `executemany` 写 parquet。

判断：

这是当前上市股票和少量 seed 映射，规模约几千行，实际风险低。但它仍是正式 asset，且模式是 Python 快照构建。必须明确它是“小表契约”，不能被复制到分钟线或日线大表。

建议修正：

- 加 row-count guard：当前上市股票数、seed 行数、最终输出行数超过明确阈值时失败并提示重新设计。
- 文档中明确：该模式只允许用于几千行级别的基础映射表。
- 如未来身份映射扩展为大历史映射，应改为 DuckDB SQL 构建。

### P2：Tushare 通用 raw 写入 helper 使用 Python rows + DuckDB `executemany`

代码位置：

- `lake_console/orchestrator/src/orchestrator/defs/tushare_api_io.py:464`
- `lake_console/orchestrator/src/orchestrator/defs/tushare_api_io.py:485`
- `lake_console/orchestrator/src/orchestrator/defs/tushare_api_io.py:487`
- `lake_console/orchestrator/src/orchestrator/defs/tushare_api_io.py:502`
- `lake_console/orchestrator/src/orchestrator/defs/tushare_api_io.py:523`
- `lake_console/orchestrator/src/orchestrator/defs/tushare_api_io.py:525`

现状：

- Tushare Resource 返回 Python rows。
- helper 用 Python list 清洗后 `executemany` 写 DuckDB 临时表，再导出 parquet。

判断：

这是源 API 边界，不是 lake 内大表 transform。对 `stock_daily`、`adj_factor`、`index_daily` 这类单日 API 分区通常可以接受。但它必须有边界：不能被复用成 prod DB 大规模抽取、全市场分钟线主路径、历史大批量文件转换。

建议修正：

- 保留作为 Tushare 小批量/API 分页落盘 helper。
- 增加文档和测试门禁：该 helper 只允许处理 API 返回 rows，不允许 prod DB 或 lake 内 parquet 大转换调用。
- 对可能超大接口增加 `max_rows_per_partition` 或明确分页/请求量统计。

### P2：`raw_stk_mins` Tushare 默认备用入口仍是逐股票请求，必须继续限定为人工/repair

代码位置：

- `lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py:495`
- `lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py:518`
- `lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py:521`
- `lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py:542`

现状：

- Tushare `stk_mins` 按 `stock_code` 循环请求，内部再分页。
- 当前默认日常 sensor 已改走 prod DB job，Tushare 主要用于人工备用和 `merge_repair`。

判断：

这条路径如果被误用于全市场日常，会重新变成几千股票乘五频度的请求模型，耗时和配额都不可接受。

建议修正：

- 保持 Tushare 作为人工 repair / 小范围备用，不作为默认日常全市场入口。
- 在 Tushare source + reuse/full-market 场景上增加明确 guard：未指定小范围 repair 时，不允许全市场大规模运行，或必须要求显式确认。
- 文档和 Launchpad 示例必须继续强调默认日常是 prod DB。

### P2：`raw_stk_mins` Tushare `merge_repair` 仍用 Python rows + `executemany`，需要规模上限

代码位置：

- `lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py:802`
- `lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py:819`
- `lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py:820`

现状：

- repair 从 Tushare 拿指定股票、指定窗口 rows。
- 用 Python list 插入 DuckDB 临时表，再 SQL merge 到既有 raw 文件。

判断：

repair 设计本来是小范围人工修复，这个实现可以接受。但它没有硬性限制 stock code 数量、窗口长度和返回 row 数。如果被用成大范围补数，会退化成大数据 Python 写入。

建议修正：

- 给 `merge_repair` 增加最大股票数、最大窗口长度、最大返回 row count。
- 超限时提示走正式批量补数或 prod DB 链路。

### P2：部分历史 bootstrap / event helper 有逐分区执行模式，不能作为未来大批量模板复制

涉及范围：

- `lake_console/orchestrator/src/orchestrator/defs/bootstrap/**`

现状：

- adj factor、stk_mins raw/silver/gold 历史迁移和 event 补录 helper 中，部分旧 helper 仍有按 partition 执行审计/补录的模式。
- qfq gold event 方案已改为 `freq/year` 批量“审一年、写一年”，这是正确方向。

判断：

这些 helper 多数是一次性迁移工具，不是 active asset。但它们在仓库中存在，容易被后续复制成新数据集迁移模板。

建议修正：

- 在 bootstrap 文档中明确：大于 100 partition 或 partition * check 大于 1000 时，禁止逐 partition readiness/check 深扫。
- 新增静态或单元门禁：大批量 event helper 必须提供 plan / batch / sample / final audit，不允许只有单 partition 循环。

## 已审计且当前未发现性能违规的主要资产族

以下资产或资产族当前主要使用 DuckDB SQL / `COPY` 做 lake 内计算与写 parquet；Python 多用于路径、schema、row count、样本格式化，暂未列为性能问题：

| 资产族 | 当前判断 |
|---|---|
| `raw_tushare_trade_calendar` / `silver_trade_calendar` | 小表日历，fetchall 用于 partition/list 级别，规模有限 |
| `raw_tushare_stock_basic` / `silver_stock_basic` | 小表基础资料，主要用 DuckDB 写入和检查 |
| `raw_tushare_suspend_d` / `silver_stock_suspend_daily` | 日频分区，主要用 SQL 标准化和检查 |
| `raw_tushare_stock_daily` / `silver_stock_daily` | 日频分区，去重、冲突检查、silver select 主要在 DuckDB 中完成 |
| `raw_tushare_index_basic` / `silver_index_basic` | 指数基础小表，当前规模有限 |
| `raw_tushare_index_daily_by_code` / `silver_index_daily` | raw-by-code 与 silver 聚合主要走 DuckDB/parquet；历史 sensor 曾有重 IO 问题已改造 |
| `raw_tushare_adj_factor` / `silver_adj_factor` | raw API 落盘用通用 Tushare helper；silver 过滤使用 DuckDB SQL |
| `silver_stk_mins_*` | raw -> silver 标准化、停牌删除、1m 修正、粗频度重算等主体逻辑在 DuckDB SQL 中完成 |
| `gold_stk_mins_qfq_*` asset 写入 | qfq 计算和按股票年份写回已沉淀到 DuckDB helper；M9E 已把 repair 从逐股票碎循环改为 `freq/year` 批量 |
| `gold_market_breadth_daily` / `gold_stock_return_distribution` | 基于日线的聚合计算主要用 DuckDB SQL |
| `gold_market_major_indices_daily` | seed 只有 10 个主要指数，Python seed 处理规模小且有明确业务上限 |
| ClickHouse serving asset/check | 当前主要是 serving 同步/对账，不属于 lake parquet 明细计算；未发现 Python 处理海量 parquet 明细 |

注意：这里的“未发现性能违规”不是永久豁免。只要未来把这些资产扩展到大范围历史回放、全市场分钟级处理或跨多年扫描，仍然必须重新做请求量、文件量、行数和耗时评估。

## 建议的修正里程碑

### PA1：修复 `raw_stk_mins` prod DB 到 raw parquet 的 Python 明细通路

优先级：P0

目标：

- prod DB 默认日常 raw 路径不再 `fetchall()` 全量分钟行。
- 不再用 Python list/dict + DuckDB `executemany` 写全市场分钟线 raw parquet。
- 字段归一、`exchange`、`vwap`、排序、schema cast 全部下推到 SQL / DuckDB。

验收：

- 单频度单日 prod DB 主路径查询次数仍约为 1。
- Python 不持有全量分钟 rows。
- 1m 全市场单日写入耗时做真实只读/最小写入验证并记录。
- 记录修改前后对比：`1m` 单频度和五频度全量至少各一组，包含耗时、row count、文件大小、内存峰值。

### PA2：优化或测量 `gold_stk_mins_qfq_*` checks 的文件级循环

优先级：P1

目标：

- 明确最新交易日五频度 qfq checks 的真实耗时。
- 若耗时不可接受，改为 DuckDB 聚合文件审计，Python 只保留缺失样本。

### PA3：给 `silver_namechange` 和 `silver_stock_identity_map` 增加小表边界

优先级：P1/P2

目标：

- 登记当前 row count、code count、耗时基线。
- 增加超限 fail fast。
- 明确这两个资产允许 Python 的原因是“小表、业务规则复杂、有边界”，不是一般模式。

### PA4：为 Tushare API raw helper 和 `merge_repair` 增加规模门禁

优先级：P2

目标：

- 防止通用 helper 被误用到 prod DB 或 lake 大表转换。
- 防止 `merge_repair` 被当成大范围补数工具。

### PA5：收紧历史 helper 模板规则

优先级：P2

目标：

- 文档和测试要求所有大批量历史迁移/event 补录必须有 plan、sample、batch、final audit。
- 禁止复制旧的逐 partition 小循环作为新迁移模板。

## 本轮未执行的动作

- 未运行 `dg`。
- 未触发任何 Dagster job/sensor/backfill/materialization/check。
- 未读取正式 `DAGSTER_HOME`。
- 未读写 `/Volumes/datasource/data_lake`。
- 未做真实耗时 benchmark。

真实耗时验证需要单独审批命令和范围，尤其是 prod DB、正式 lake、Dagster event log 相关操作。
