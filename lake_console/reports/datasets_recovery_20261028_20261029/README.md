# 2026-10-28股票分钟链补齐与DG完整性审计

28日股票分钟链已完成：五个原job依次成功，25个当日数据集、两次必要repair及81项原检查均通过。原五个sensor已恢复RUNNING，未清cursor。10:40的唯一一次全目录物理计数为157/159项有数据；管理员随后批准先补齐主要指数日线九转Gold及Prod两项，现已补齐并各核实11行。按原计数加这两项收尾证据，28日159项按日数据集均有数据，没有重跑全目录审计。23/26/27日THS历史缺口仍单独保留，不包含在28日结论中。

方案与逐步操作依据为[原分钟链方案/LLD §17](../../docs/design/dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#17-2026-10-28股票分钟链补齐方案和执行lld2026-10-29)。前序因子修正已于`876cc6a8`提交；本轮未修改业务代码，未重跑已完成的Raw/Silver，未执行额外性能测试或修改运行限制。

## 1. 批准范围与执行顺序

管理员已批准本轮28日具体年度/历史范围，见[批准原文](history-approval.json)。正常各必要job一次，批准预算估读428GiB、写123GiB、额外空间128GiB，包含原检查、临时读写及收尾。预算和文件stat不是实测设备I/O；本轮没有为了测量I/O增加测试。失败停止、不自动重跑，本次五个业务job均成功，无业务重跑。

只通过原job及现成repair配置函数执行：QFQ日更 → 因子repair → MACD/KDJ日更及state → MACD/KDJ repair → 九转。完成全链后才恢复原五个sensor，最后执行一次物理计数。九转sensor原代码不等待MACD repair，本轮通过逐job等待和暂缓恢复开关保证先后顺序。

## 2. 五步正式结果

| 步骤 | 原job / run | 结果 | 原检查 | 验收证据 |
| --- | --- | --- | ---: | --- |
| 七频前复权日更 | `stock_mins_qfq_daily_update_job` / `94384f7b` | SUCCESS，7物化 | 28 | [QFQ验收](batch9/daily-run-verified.json) |
| 七频因子repair | `stock_mins_qfq_factor_repair_job` / `816a0d01` | SUCCESS，原guard ready | 7 | [因子repair验收](batch9/factor-run-verified.json) |
| 七频MACD/KDJ及state | `gold_stk_mins_qfq_macd_kdj_daily_update_job` / `13e1b027` | SUCCESS，14物化 | 28 | [指标日更验收](batch10/daily-run-verified.json) |
| 七频MACD/KDJ repair | `gold_stk_mins_qfq_macd_kdj_repair_job` / `44caf58c` | SUCCESS，完整gate ready | 14 | [指标repair验收](batch10/repair-run-verified.json) |
| 四频九转 | `gold_stk_mins_qfq_nineturn_update_job` / `a9f7bedc` | SUCCESS，4物化 | 4 | [九转验收](batch11/final-verified.json) |

合计25个当日资产：前复权7项、MACD/KDJ指标7项、state7项、九转4项；repair的21条完成检查不作为新增数据集。各阶段核对本次真实run、28日物化、检查通过且绑定正确；repair另核实际范围、批次、名单hash及原guard。逐频复用原publication回执和正式目标stat，不追加价格正文或数据摘要遍历。[汇总及25项物理计数](execution-summary.json)。

因子repair实际名单由原job自动生成：16股，2014-01-02至2026-10-28、3,115个交易日、七频；批次`qfq_factor_repair:2026-10-28:3afb0b0b08f6`。指标repair使用原decision/config函数承接同批名单及28日daily readiness，没有手工干预名单。MACD repair完成723份指标年度文件及21,805份共享state的原写入与验收；共享state合并保留其他股票，不把这次操作说成全市场指标重算，也没有额外全量明细比对。

九转先核实际16股四频共64组27日末根计数，全部匹配，差异0；实际候选及seed所需2014—2026文件按路径去重468份、17,922,588B，包含2025/2026，处于批准1GiB范围内。没有重写27日seed或重跑27日。28日四频九转合94,690行、241,902B。[候选范围](batch11/candidate-scope.json)、[seed核对](batch11/prior-seed-verified.json)。

## 3. 最后一次28日物理计数

观测时间：2026-10-29 **10:40:35（上海时间）**。运行时catalog分类完整，每项均被审计或明确排除。只计数，不把DG物化或绿色检查当成物理有数据的依据。

| 业务日期 | catalog总数 | 实际审计 | 明确排除 | 有当日数据 | Parquet缺失 | Serving缺失 | 未核实 | 零行文件 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-10-28 | 180 | 159 | 21 | 157 | 1 | 1 | 0 | 0 |

21项排除是非按交易日审计的快照及健康资产，不代表废弃或无用。14个年度文件族仅查询2026文件中28日行数；直接分区和两端CH、Prod PG复用原skill的只读计数。未读取额外代码、时间或价格明细，未重复运行全目录审计。

10:40时剩余两项（现已按第7节补齐）：

| 数据集 | 28日物理事实 | 后续顺序 |
| --- | --- | --- |
| `gold_major_index_daily_nineturn` | Gold当日分区文件不存在 | 先确认该链前置与原job，再补Gold并通过其原检查 |
| `prod_core_index_daily_nineturn` | Prod `core_serving.index_nineturn_daily`当日0行 | Gold通过后，再用原同步job写Prod并核对原检查 |

原审计中股票分钟链25项缺失已全部消除；原先其余六项中，本次只有以上两项仍缺。这里只报告当前物理事实，没有另查其sensor或启动原因，也未继续修复本轮范围之外的指数链。157项有数据不代表对157项都做了质量或源端完整覆盖验收。

完整证据：[最终物理计数JSON](final-physical-audit.json)。此审计是本轮唯一一次全catalog计数，未将数据库不可用或读取失败算作缺失；本次此类未核实为0。

## 4. Sensor与临时文件收尾

在九转完成验收之后，10:40通过原生接口恢复且只恢复以下五个原开关，状态均RUNNING：

- `stock_mins_qfq_daily_sensor`
- `stock_mins_qfq_factor_repair_sensor`
- `gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor`
- `gold_stk_mins_qfq_macd_kdj_repair_job_sensor`
- `gold_stk_mins_qfq_nineturn_update_job_sensor`

未清cursor、未改并发、调度参数或其他开关，没有重启daemon。恢复请求及只读确认见[sensor记录](sensor-restoration.json)。恢复后原sensor可继续正常调度，不以本轮之外的指数缺口继续关闭股票分钟链。

DuckDB共享工作目录在MACD前为空，五步结束后再次只做目录/stat检查仍为空，无需删除共享工作文件：[前置](batch10/duckdb-workfiles-before.json)、[结束](duckdb-workfiles-after.json)。本轮临时编排、验收和隔离夹具按§17.8逐字节归档后精确清理；正式Lake结果和staging中的publication、receipt及恢复记录保留。[清理记录](cleanup-manifest.json)。

## 5. 证据与验收边界

准备阶段按现有原23日readback适配，业务验收函数保留；计数入口14项隔离测试及root源码复核通过，薄触发器普通及Python优化模式各32例通过。相关测试只证明临时编排和计数入口，不冒充原job正式验收。实际补数结论来自上表五个真实run和81条原检查，物理存在结论来自最后一次计数。

准备时纠正了观察入口额外要求旧check原生partition非空/因子每条check日期metadata齐全的错误假设，在业务启动前恢复原验收口径。现有部分旧check原生partition仍为空；本轮按真实物化的日期、run和storage id核准，有实际日期信息时不得冲突，没有补造检查事件，也不宣称已修复该存量事件字段问题。

08:58完整年度metadata结果从原exec session追回并归档，没有重复扫描年度目录；后续只据真实publication差额更新预算。[年度基线](annual-baseline-current.json)、[追回的原证据](recovered-metadata-stat.json)、[必要历史来源stat](history-stat-consumer.json)、[运行预检](runtime-preflight.json)。

最后的独立复核只查看当前代码和已有执行证据，不请求正式服务、不重跑job、不再读行情明细：[独立复核](execution-independent-review.md)。本轮方案、LLD及执行材料按管理员本次指令提交；其他工作区改动不纳入，不推送。

## 6. 后续授权：先补齐28日指数九转两项

管理员已批准先补齐第3节两项，并要求继续推进。具体方案和逐步LLD已先落[原文档§18](../../docs/design/dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#18-2026-10-28剩余两项主要指数日线九转补齐方案和执行lld)。只复用原Gold→Prod两个job，先后各通过一个原check；不改业务代码、开关或运行限制，不补THS，不重复全目录审计。

必要来源是最近20份小日线共52,537B及27日九转seed；正常读写预算8/1MiB、额外空间8MiB，中断状态核验及未完成部分另预留同额而不授权自动重跑。先核当前sensor避免自动/手工双提交，已有同日活动/成功则跟踪或验收复用。后续精确run、物理计数和收尾记录保存在`index-daily-nineturn/`；以下完成结果待实际执行后追加，10:40原计数JSON保持原样。

## 7. 指数日线九转两项补齐完成（2026-10-29 12:23）

| 阶段 | 实际原run | 结果 | 28日行数 | 原检查 |
| --- | --- | --- | ---: | --- |
| Gold日线九转 | `d4c794f5-4939-482e-a93c-4ba70d3eadd7` | SUCCESS，4.845秒 | 11 | 1项通过，准确绑定本次物化 |
| Prod发布 | `22dbd172-3a3c-4c51-bb1f-075eb31256bf` | SUCCESS，5.369秒 | 11 | 1项通过，同日业务内容hash一致 |

两条sensor实际均RUNNING。Gold最近两次评估因29日分区未注册而提前跳过，28日自身分区、上游Gold及27日seed原检查均通过。提交前再次确认这个阻断、28日目标仍缺且无活动任务后，只手工触发28日Gold一次；Prod完全由原sensor接续，未手工重复提交。按原batch/run_key和sensor名精确核Prod来源为本次Gold，未按最新同日run猜测。

最终只核这两项：Gold文件11行、Prod同日11行，原检查全部通过；21份必要来源、27/29日Gold目标stat及Prod邻日计数不变。两sensor状态保持RUNNING，没有修改开关、cursor、资源、并发或业务代码。依据原10:40物理计数157项加本次恢复2项，28日按日审计范围为159/159项有数据、剩余缺失0；这是已有计数与本次两项收尾的合并结论，未重复全目录审计，也不代表所有字段质量都重新审计。

23/26/27日THS Raw/Silver历史六分区仍缺，本次没有补这些日期。原10:40审计JSON以及分钟链完成记录保持原样，后续补齐事实分别保存：[执行前核验](index-daily-nineturn/preflight.json)、[Gold验收](index-daily-nineturn/gold-verified.json)、[自动Prod记录](index-daily-nineturn/prod-observation.json)、[Prod验收](index-daily-nineturn/prod-verified.json)、[两项最终收尾](index-daily-nineturn/final.json)。

本步只读观察入口、GraphQL和变量文件归档后精确删除本轮临时目录；正式Gold及staging保持。Prod变量只是预备材料，从未手工执行。[清理记录](index-daily-nineturn/cleanup.json)。原方案和LLD执行结果见§18.6；本步与分钟链材料一并提交，不推送。

两项执行证据已完成[独立对账](index-daily-nineturn/independent-review.md)，未发现阻断；对账仅使用当前代码及已有材料，没有新增正式读取。
