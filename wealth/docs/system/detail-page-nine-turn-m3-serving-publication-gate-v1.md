# 股票日线九转 M3 serving 发布门禁 v1

> 状态：M3-A/M3-B 已完成。Gold 日线修复、全历史验收和生产 serving 发布均已完成；生产表已按冻结计划验收到 3,066 个交易日、11,638,636 行，逐日行数差异为 0。修正后的十个短进程峰值 RSS 最高约 249MiB，未复现内存爆炸。两个 sensor 仍为 `STOPPED`，分钟未执行，M3-C Web 生产验收未开始。

> 总方案：[股票与主要指数详情页九转接入总方案 v1](./detail-page-nine-turn-integration-implementation-design-v1.md)

> LLD：[股票与主要指数详情页九转接入低层设计 v1](./detail-page-nine-turn-integration-low-level-design-v1.md)

## 1. 目标和退出边界

M3-A 纠正“文件齐全即可发布”的错误前提；M3-B 把发布改成可阻断、可审查、可中断、可续跑的正式链路。

本门禁通过本身不授权以下动作；2026-08-13 的 Gold 修复和日线 serving 分批发布均在用户另行批准后执行：

1. 修改正式 Gold 文件。
2. 向生产 `core_serving.equity_qfq_nineturn_daily` 写入数据。
3. 运行 materialize、backfill、runless event 或历史 publisher。
4. 启用任一股票九转 sensor。

## 2. M3-A 事实基线

| 项目 | 2026-08-13 只读结果 |
|---|---:|
| Alembic head | `20260813_000135` |
| 生产目标表 | 已存在，0 行 |
| Gold 九转分区 | 3,066 |
| 覆盖 | 2014-01-02 ～ 2026-08-12 |
| Gold 九转键数 | 11,638,636 |
| QFQ 行情键数 | 11,638,636 |
| 缺失/多余键 | 0 / 0 |
| `close_qfq` 漂移 | 45,442 行、18 只股票、3,065 个交易日 |
| 漂移股票公式重算 | 45,483 行比较，计数/信号差异 0 |
| Gold 修复后全历史对账 | 11,638,636 行；键、价格、计数、信号差异均为 0 |
| serving 最终检查点 | 3,066 / 3,066 个交易日；剩余 0 |
| serving 最终生产对账 | 11,638,636 行；日期缺失/额外/逐日行数不符均为 0 |

结论：页面 marker 算法结果没有发现差异，但九转 Gold 保存的价格已经不是当前 QFQ 事实。发布表包含 `close_qfq`，因此不能忽略这部分漂移；先 scoped rebuild，再发布。

## 3. 不可变发布门禁

1. Gold check 同时验证文件、分区、键、值域、源键覆盖和源收盘价一致性。
2. serving loader 再次运行同一门禁，不能靠跳过 Dagster check 绕过。
3. 正式 Lake 只允许 `raw/silver/gold`；候选、恢复副本和 checkpoint 只能进入 `/Volumes/datasource/data_lake_staging`。
4. 历史发布先 `plan`，计划绑定 Gold/QFQ 文件路径、size、mtime、行数和 fingerprint。
5. Gold scoped rebuild 与 serving 发布都要求 `sample` 只允许 1～3 个计划内分区；单个逻辑 `batch` 最多 20 个分区。Gold 修复一次已审批运行最多 200 个 batch；serving 因真实内存事件收紧为单进程最多 10 个 batch，即最多 200 个交易日，必须退出进程释放内存后再续跑。
6. 每个交易日独立事务；read-back 通过后才原子记录 checkpoint。
7. 续跑前先对计划冻结的全部 Gold/QFQ 文件做相对路径、size、mtime 元数据核对，再使用 PostgreSQL server cursor 流式回验 checkpoint 已完成日期的精确业务内容 hash；任一不一致立即停止。仅本次待发布分区重新执行完整 Gold/QFQ 内容门禁，禁止每次恢复都深扫全历史。
8. serving check 为 blocking，比较行数、键和业务内容 hash。
9. 日常 serving job 独立于 Gold job；下游 sensor 默认 `STOPPED`。
10. 不使用 Tushare、Mock、客户端重算或空表作为 fallback。
11. serving 历史发布专用 DuckDB 固定 `memory_limit=128MB`、`threads=1`、`preserve_insertion_order=false`；不得沿用通用 16GB 上限。
12. 每个 20 日 batch 复用一组 DuckDB、PostgreSQL 写连接和只读连接；每个交易日仍显式 commit、read-back、结束只读事务和写 checkpoint。
13. `plan` 的完整 3,066 分区明细只写报告文件；CLI 只打印固定大小摘要。发布进度每个逻辑 batch 最多打印一条，不逐日打印；最终结果不得携带完整 selected/published/resumed 日期数组。

## 4. 代码落点

| 能力 | 文件/定义 |
|---|---|
| Gold 源值门禁 | `qfq_nineturn_integrity.py` / `source_value_consistency` |
| scoped rebuild plan/sample/batch/resume | `qfq_nineturn_history.py` |
| 历史 plan/sample/batch/resume | `stock_daily_qfq_nineturn_serving_history.py` |
| 显式 CLI apply 门禁 | `stock_daily_qfq_nineturn_serving_history_cli.py` |
| serving blocking check | `prod_core_stock_daily_qfq_nineturn_partition_check` |
| 日常 serving job | `prod_core_stock_daily_qfq_nineturn_sync_job` |
| 默认停止 sensor | `prod_core_stock_daily_qfq_nineturn_sync_job_sensor` |

## 5. 配置审计

本轮不新增环境变量。正式根继续使用既有常量：

| 配置 | 值/来源 | 消费者 | 生效方式 |
|---|---|---|---|
| Lake root | `/Volumes/datasource/data_lake` / `DEFAULT_LAKE_ROOT` | plan、Gold loader、scoped rebuild | CLI/运行时 |
| Staging root | `/Volumes/datasource/data_lake_staging` / `DEFAULT_LAKE_STAGING_ROOT` | rebuild 候选、备份、checkpoint | CLI/运行时；正式根不可改 |
| Prod write env | `PROD_POSTGRES_WRITE_*` | serving asset、history publisher、serving check | 运行时 |
| serving DuckDB 内存 | `128MB` / 发布器代码常量 | serving plan、resume、publish | 每次连接建立后强制设置 |
| serving DuckDB 线程 | `1` / 发布器代码常量 | serving plan、resume、publish | 每次连接建立后强制设置 |
| serving 单进程批次数 | 最多 `10` | history publisher | CLI 参数校验；每批最多 20 日 |

CLI 虽保留 fixture 参数用于隔离测试，但正式 Lake 模式会强制固定 staging 根，不能用参数改到正式 Lake 内部。

## 6. 性能与事务预算

1. 历史规模为 3,066 个分区、11,638,636 行，约 13,472 个 1,000 行插入页。
2. 单日最多约 5,539 行；事务边界固定为一个交易日。
3. Gold scoped plan 只扫描目标资产族；本轮日线修复不再顺带扫描四个分钟资产。
4. 每个逻辑 batch 最多 20 个交易日；Gold 修复单次最多 200 个 batch，serving 单进程最多 10 个 batch。两者都逐日 checkpoint，失败不撤销已经回验通过的早期日期。
5. Gold 每个交易日使用独立候选、完整 blocking check 语义、同文件系统 `os.replace()` 和保留于 staging 的恢复副本；执行前按所选分区计算磁盘预算。
6. serving 每个交易日使用独立 PostgreSQL 事务；checkpoint 每成功一个交易日原子写一次。
7. 计划阶段每个分区只执行 SQL 完整性聚合并取得 `checked_row_count`，不再把整分区记录 `fetchall()` 到 Python；每 20 日关闭并重建 DuckDB 连接，释放 allocator 高水位。
8. 恢复阶段不再重新生成覆盖 3,066 日、6,132 个文件的深度计划；只做 6,132 个文件的固定元数据核对、已完成 Prod 行的 server-cursor 流式 hash，以及最多 200 个待发布日的深度校验和写入。
9. 修正前证据：128MB/单线程全历史计划峰值 RSS 约 316MiB；913 个已完成日的流式恢复回验峰值约 156MiB；随后 200 日发布进程峰值约 340MiB，立即再启恢复进程时峰值约 412MiB。根因是同一进程串行执行全历史深度重计划、已完成 Prod 回验和发布，叠加 DuckDB allocator 高水位；PostgreSQL 单日约 2,000～5,539 行写入不是主要放大点。
10. 修正后正式只读验收：3,066 日、6,132 文件、11,638,636 行的全历史 plan 用时 17.60 秒，峰值 RSS 248,348,672 bytes（约 237MiB），指纹与原计划一致；1,113 个 checkpoint 日期、2,770,508 行 Prod 精确 hash 回验全部通过，用时 187.39 秒，峰值 RSS 163,987,456 bytes（约 156MiB）。两项分进程执行，均未写 Lake 或 Prod。
11. CLI 曾打印 3,066 个完整计划对象、全部日期数组和逐日进度，产生 325KB 以上单次输出并放大 Codex 渲染内存；本轮正式 plan 摘要仅 526 bytes，恢复验收摘要 148 bytes，发布过程改为逐 batch 进度。该问题与数据写入正确性分开处理。
12. 修正后从 1,113 日恢复到 3,066 日，共使用 10 个独立短进程（九次 200 日、最后一次 153 日）；各进程最大 RSS 为 209～249MiB，最高 260,833,280 bytes，未触发 512MiB 观察阈值或 1GiB 中止阈值。最后进程最大 RSS 为 241,074,176 bytes，检查点剩余为 0。
13. 恢复回验耗时随已完成分区增长，最后进程总耗时约 932 秒，其中写入阶段约 215 秒。它是 server-cursor 精确内容 hash 的线性耗时问题，不是常驻内存增长；后续若优化恢复性能，必须保留“源身份 + 已完成生产内容”双重 fail-closed 语义。
14. 同期只读观察到长期运行的 Dagster Definitions gRPC 进程 RSS 约 6.6～7.4GiB；调用 Definitions/sensor 只读查询后为约 7.4GiB，随后 30 秒采样保持不变。该进程不是历史 publisher，不能把其内存归因于 PostgreSQL 日线写入；应另立 Dagster Definitions 常驻内存审计，本轮不混改、不停止该进程。

## 7. M3-B 验收矩阵

1. close 相同通过，close 漂移阻断，failure sample 可定位代码和数值。
2. Gold key 缺失、额外 key、重复 key、值域错误继续阻断。
3. 正式 Lake 内 staging 路径被拒绝；fixture Lake 与 staging 也不能相同；checkpoint 只能位于已审核 staging 根下。
4. 计划文件被改、源文件 size/mtime 变化、fingerprint 错配均在写 Prod 前停止。
5. Gold 与 serving 的 batch 上限 20；Gold 单次 batch 数上限 200，serving 单进程 batch 数上限 10，sample 上限 3；计划外日期拒绝。
6. Gold 提升或 serving 每日事务 read-back 漂移失败时，checkpoint 不记录失败日期；Gold 当前分区恢复原文件。
7. 第二次运行对全部冻结源做元数据身份核对，以流式游标验证已完成日期的目标 hash，并只对待发布日期重跑源内容门禁；发布函数不得再次调用全历史 `plan`。
8. serving check 为 blocking，catalog 登记一致。
9. job 只选择 serving asset/check；sensor 同分区触发且默认 STOPPED。
10. 既有日线/分钟九转公式、页面 DTO、共享 primitive 和 API 回归不漂移。

2026-08-13 本轮内存与输出修正后的定向代码验收为 21 项通过；九转相关完整回归为 96 项通过、另有 14 个子测试通过，Ruff 与 `git diff --check` 通过。测试明确证明 plan 不再调用行装载器、publish 不再重建深度计划、CLI 摘要不含完整分区数组、进度仅按 batch 发出。正式只读 plan、checkpoint 回验和全历史生产逐日行数对账均已通过。`dg list defs` 已发现 serving asset、blocking check、独立 job 和 sensor；正式 instance 再次确认两个九转 sensor 均为 `STOPPED`。M3-B 可以收口，但未完成生产 API、浏览器和自然日常链路验收，不能把股票九转整体标记为 production-ready。

## 8. 后续执行顺序

1. 已生成并审核 18 只股票 scoped rebuild 计划。
2. 已完成 3 个 Gold 样本、3,065 个修复分区及全历史 source-value/公式对账。
3. 已生成 serving history 计划并完成首、中、尾 3 天样本发布。
4. 已在代码修正和只读内存门禁通过后，以单进程最多 200 日的短进程从 1,113 日恢复到 3,066 日；最终 checkpoint、冻结计划和生产表逐日行数一致，剩余 0。两个 sensor 继续保持 STOPPED。
5. 进入 M3-C，进行生产日线 API、页面、权限、局部状态、性能与视觉验收。
6. 最后做一次自然日常链路验收；仍需单独审批才可启用 sensor。

## 9. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-08-13 | 登记正式数据漂移事实，冻结 Gold 修复与 serving 历史发布门禁、代码落点、性能预算和后续执行顺序 | Codex |
| v1.1 | 2026-08-13 | 登记 Gold 修复完成、serving 893 日检查点、内存事件和 256MB/单线程/10批次短进程门禁 | Codex |
| v1.2 | 2026-08-13 | 同步 serving 1,113 日检查点；修复计划取全量行、恢复全历史深扫和超大 CLI 输出三处放大点，内存上限收紧到 128MB；正式只读验收通过，生产恢复仍待用户确认 | Codex |
| v1.3 | 2026-08-13 | 完成余下 1,953 个交易日的十进程有界发布；最终 3,066 日、11,638,636 行逐日对账通过，峰值 RSS 约 249MiB；M3-B 收口，M3-C 与自然日常链路仍待验收 | Codex |
