# Dagster 新湖 Asset 性能审计

审计日期：2026-06-04

复审日期：2026-06-05

> **历史审计快照（2026-07-15 校正）：** 本文的性能样本、P0/P1/P2 优先级和
> raw-by-code 结论只描述 2026-06 的代码与数据规模。后续指数日线已迁移到 raw by-date /
> prod core DB 链路；QFQ/MACD-KDJ 公式 production check 已退出，公式正确性转由受保护金样本
> 测试承担。当前性能规则以 <a href="dagster-data-pipeline-performance-governance.md">数据管道性能治理规范</a>
> 和对应数据集 LLD 为准；本文不改写原始测量数字。

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

## 2026-06-05 复审结论

本次复审重点重新查看了正式 `defs/**` 中的 DuckDB 写入、Python 明细处理、qfq check、namechange、identity map、Tushare helper、repair 和历史 event helper。结论：

1. 当前已登记的 P0 均已修复，未发现新的 P0。
2. 非 P0 风险仍存在，主要是“可运行但缺少规模边界或批量化优化”的 P1/P2。
3. 非 P0 不阻断当前生产链路，但应按下方优先级收口，避免后续放大时再次演变成 P0。

### 建议修复优先级

| 顺序 | 项目 | 等级 | 为什么排在这里 | 建议动作 |
|---:|---|---|---|---|
| 1 | `gold_stk_mins_qfq_*` checks 无条件 sample 查询与重复深扫 | P1 | 属于日常 gold qfq 生产链路；2026-06-05 只读实测显示，真正主耗时不是文件 exists 循环，而是全绿场景仍无条件执行 sample 查询和重复 DuckDB 深扫。 | P1A 已落地：sample 懒加载，只有失败时取样本；同日复测五频度从约 `31.9s` 降到约 `19.4s`。若仍慢，再做 P1B：聚合扫描复用。 |
| 2 | `silver_namechange` 小表 Python 时间线边界 | P2 | 2026-06-05 只读实测显示当前 raw 仅 `20311` 行，时间线构建约 `0.13s`，asset 侧 Python 总耗时约 `0.16s`；不构成实际 P1 性能瓶颈。 | 不做中期 DuckDB 重写；只补小表边界治理：row count/code count/耗时基线和超限 fail-fast。 |
| 3 | Tushare `stk_mins` 全市场备用入口与 `merge_repair` 规模门禁 | P2 | 默认日常已经走 prod DB，但人工入口一旦误用成全市场 run，会重新进入逐股票请求和 Python rows 写入模型。 | 给 Tushare source 和 `merge_repair` 增加股票数、窗口长度、返回行数上限；超限提示走 prod DB 批量补数。 |
| 4 | `silver_stock_identity_map` 小表构建边界 | P2 | 当前只有几千行，风险低；但它是正式 asset，仍需明确“小表 Python 规则构建”的合法边界。 | 增加输入/输出 row count 上限和测试，文档说明该模式不得复制到大表。 |
| 5 | 历史 bootstrap / event helper 模板约束 | P2 | 当前多数是一次性工具；真正风险是未来复制旧的逐 partition helper 到新数据集。 | 增加迁移模板规则：大于 100 partitions 或 partition*checks 大于 1000 时必须使用 plan/sample/batch/final audit。 |
| 6 | `raw_stk_mins` prod DB P0 修复后的真实 benchmark 回填 | 验证项 | P0 代码已修；还缺真实日常耗时对比，属于证据回填，不是当前代码阻塞。 | 等下一次日常 run 或单独批准 benchmark 后补 1m 与五频度耗时、row count、文件大小、内存峰值。 |

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

### P1：`gold_stk_mins_qfq_*` checks 无条件 sample 查询与重复深扫

代码位置：

- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py:270`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py:278`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py:286`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py:446`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py:582`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py:868`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py:876`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py:893`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py:911`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py:939`

现状：

- M8B 已经把 8 个 qfq checks 合并成每频度一个 `multi_asset_check`，避免同一频度重复深扫。
- 但 `_gold_qfq_expected_paths(...)` 会从当日 silver 读取全部 `ts_code`，`fetchall()` 到 Python，再为每只股票构造 `freq/ts_code/year` 路径。
- 后续用 Python `path.exists()` 拆出 missing/existing，再把大量 existing paths 拼进 DuckDB `read_parquet([...])`。
- 当前 `_gold_stk_mins_qfq_check_results(...)` 在全绿场景也无条件执行 3 类 failure sample 查询：path mismatch、duplicate、price。
- 当前公式 check 在 `formula_failed_count=0` 时也无条件执行 formula sample 查询。

2026-06-05 只读实测：

- 测量对象：正式湖 `2026-06-04`，五个 `gold_stk_mins_qfq_*` 频度。
- 测量方式：不运行 Dagster，不读取正式 instance，不写 lake；只用 DuckDB 读取正式 lake 文件并按当前 check helper 分段计时。
- 输出文件：
  - `/private/tmp/stk_mins_qfq_check_perf_20260605_073843.csv`
  - `/private/tmp/stk_mins_qfq_check_perf_20260605_073843.json`

| freq | 总耗时 | 路径构造 + exists | 占比 | sample 查询 | 占比 | gold counts | formula counts |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 60 | 3.60s | 0.07s | 1.9% | 1.83s | 50.7% | 0.60s | 0.82s |
| 30 | 3.83s | 0.09s | 2.4% | 2.00s | 52.1% | 0.78s | 0.64s |
| 15 | 4.38s | 0.19s | 4.4% | 2.20s | 50.2% | 0.94s | 0.71s |
| 5 | 5.57s | 0.44s | 7.9% | 2.51s | 45.1% | 1.48s | 0.77s |
| 1 | 14.54s | 0.42s | 2.9% | 5.44s | 37.4% | 6.88s | 1.44s |

五频度合计：

- 当前总耗时约 `31.92s`。
- 路径构造 + `exists` 合计约 `1.21s`，只占 `3.8%`。
- sample 查询合计约 `13.97s`，占 `43.8%`。
- `gold_counts_sql` 合计约 `10.69s`。
- `formula_counts_sql` 合计约 `4.38s`。

P1A 落地后同日只读复测：

- 测量对象仍为正式湖 `2026-06-04`，不运行 Dagster，不读取正式 instance，不写 lake。
- 复测方式：直接调用当前 `_gold_stk_mins_qfq_check_results(...)` helper，确认全绿场景 failure samples 不再被查询。

| freq | P1A 后耗时 | failed checks | failure sample rows |
|---:|---:|---:|---:|
| 60 | 2.14s | 0 | 0 |
| 30 | 2.04s | 0 | 0 |
| 15 | 2.30s | 0 | 0 |
| 5 | 2.66s | 0 | 0 |
| 1 | 10.21s | 0 | 0 |

五频度合计：

- P1A 后总耗时约 `19.36s`。
- 相比 P1A 前 `31.92s`，下降约 `39.4%`。
- 全绿场景 `failure_sample_rows=0`，证明样本查询已按失败懒加载。

判断修正：

- 原先把“文件级 exists 循环”列为主瓶颈是不准确的。它确实存在，但实测占比只有 `3.8%`，不是优先优化对象。
- 当前真正高性价比问题是：check 已经通过时仍执行 failure sample 查询。sample 只服务失败诊断，全绿场景不应付出这部分 IO。
- 第二层问题是 `gold_counts_sql`、`formula_counts_sql` 和 coverage 查询之间存在重复读取与重复 join 空间，但这一步改动更大，应排在 sample 懒加载之后。

影响：

- check 可能成为 qfq 日常 job 的瓶颈。
- 当前全绿场景也会浪费约 `14s` 做失败样本查询，五频度正常 run 被无意义 IO 放大。
- 1m 的 `gold_counts_sql` 单项已经达到约 `6.88s`，后续若日常 run 仍慢，需要继续做聚合扫描复用。

建议修正：

- P1A：sample 懒加载，成本低、收益确定，已落地为当前代码口径。
  - `path_mismatch_row_count > 0` 时才执行 path mismatch sample 查询。
  - `duplicate_key_count > 0` 时才执行 duplicate sample 查询。
  - `invalid_price_row_count > 0` 时才执行 price sample 查询。
  - `formula_missing_gold_row_count + formula_unexpected_gold_row_count + formula_mismatch_row_count > 0` 时才执行 formula sample 查询。
  - 正常全绿场景已从约 `31.9s` 降到约 `19.4s`，节省约 `39.4%`。
  - check 质量口径不变；失败时仍保留 failure samples。
- P1B：聚合扫描复用，成本中等，等 P1A 后按新耗时决定是否推进。
  - 尽量复用 `gold_rows` / `target_rows` 中间结果，减少 `gold_counts`、formula 和 coverage 的重复读。
  - 若需要，可以把当日 expected qfq rows 和 gold target rows 放入 DuckDB 临时表，多个 check count 复用同一轮扫描结果。
  - 目标是把五频度全绿 check 继续压到 `10-15s` 量级。
- 暂不优先做文件 exists 循环优化。
  - 实测五频度只占 `1.21s`。
  - 单独优化它预计收益小于 `5%`，性价比低。
- 静态门禁增加“qfq check 不得退回 8 个独立深扫 check”的约束。

### P2：`silver_namechange` 使用 Python 构建完整名称时间线，但当前规模很小

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

namechange 规模远小于分钟线，不是 P0。2026-06-05 已按用户建议做只读耗时核验，结论是当前不需要进入中期 DuckDB 重写；它应从 P1 性能改造项降为 P2 小表边界治理项。

2026-06-05 只读实测：

- 测量对象：正式湖 `raw_tushare_namechange`、`silver_stock_basic`、`silver_namechange` 文件。
- 测量方式：不运行 Dagster，不读取正式 instance，不写 lake；只调用当前读取/时间线 helper 做内存计时。

| 指标 | 数值 |
|---|---:|
| raw namechange rows | `20311` |
| current listed stock count | `5524` |
| filtered current-listed rows | `17668` |
| filtered delisted rows | `2643` |
| silver namechange rows | `12325` |
| raw file size | `429712` bytes |
| silver file size | `202163` bytes |
| 读取 raw rows | `0.025s` |
| 读取 stock basic names | `0.003s` |
| 当前上市过滤 | `0.002s` |
| 构建 namechange timeline | `0.126s` |
| asset 侧 Python 总耗时，不含正式写文件 | `0.158s` |
| 读取 silver rows | `0.016s` |
| 分析 silver rows 一次 | `0.022s` |
| 当前两个 checks 重复分析估算 | `0.080s` |

实测结论：

- 当前 Python 时间线构建耗时低于 `0.2s`，不是实际生产瓶颈。
- 两个 `silver_namechange` checks 即使重复读取与分析，估算也低于 `0.1s`。
- 直接做中期 DuckDB 重写的性价比很低，且会增加规则迁移风险。
- 真正需要补的是小表边界：证明它长期只允许作为几万行级别基础快照，而不能被复制到分钟线、日线或其它大表链路。

影响：

- 当前可运行且性能足够。
- 风险不是当前耗时，而是未来源端历史或业务规则扩大后，没有 row count/code count/耗时上限来阻止 Python 小表模式被放大。

建议修正：

- 不做中期 DuckDB 重写。
- 短期只补边界门禁：
  - 在 asset 或 timeline helper 入口登记 raw rows、filtered rows、current listed code count 的可接受上限。
  - 超过上限时 fail fast，提示重新设计为 DuckDB SQL 方案。
  - 文档明确：该 Python 模式只允许用于小表、规则复杂、可解释的基础快照。
- 如果未来 raw namechange 行数扩大到当前数量级的数倍，或耗时超过明确阈值，再重新评估 DuckDB 化。

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

### PA2：优化 `gold_stk_mins_qfq_*` checks 的 sample 查询与重复扫描

优先级：P1

目标：

- 已完成最新交易日五频度只读测量，确认主瓶颈不是文件 exists 循环。
- 第一阶段 P1A：只在 check 失败时执行 failure sample 查询，已落地。
- 第二阶段 P1B：如果 P1A 后仍慢，再复用 DuckDB 中间结果，减少 `gold_counts` / formula / coverage 重复深扫。

P1A 落地步骤：

1. 保留当前每频度一个 `multi_asset_check` 的 Dagster definition 结构。
2. 先执行现有 count SQL，得到 path mismatch、duplicate、price、formula 四类失败计数。
3. 只有对应失败计数大于 0 时，才执行对应 sample SQL。
4. 所有 `AssetCheckResult` 的 check name、blocking、metadata key、通过/失败口径保持不变。
5. 单元测试证明：
   - 全绿场景不执行 sample SQL。
   - path mismatch / duplicate / price / formula 任一失败时，只执行对应 sample SQL。
   - check result 仍包含原有 failure sample metadata。

预期收益：

- 基于 2026-06-05 只读测量，P1A 前五频度全绿 check 约 `31.9s`。
- sample 查询约 `14.0s`，占 `43.8%`。
- P1A 后同日复测约 `19.4s`，节省约 `39.4%`。
- 这一步不降低质量口径，只移除通过场景的无意义诊断 IO。

P1B 候选步骤：

1. 对 P1A 后的新耗时再做一次只读测量。
2. 如果五频度全绿仍明显超过可接受范围，再把 `gold_rows`、`target_rows`、expected qfq rows 复用为 DuckDB 临时表或统一 CTE。
3. 优先合并 `gold_counts_sql` 和 formula/coverage 中重复读取 gold/silver/adj factor 的部分。
4. P1B 改动更大，必须单独列计划和测试，不能和 P1A 混在一个补丁里。

### PA3：给 `silver_namechange` 和 `silver_stock_identity_map` 增加小表边界

优先级：P2

目标：

- `silver_namechange` 已登记当前 row count、code count、耗时基线；后续只需补代码级超限 fail-fast。
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
