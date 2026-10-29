# 2026-10-28股票分钟链执行证据独立对账

结论：本轮五个原job的执行、repair承接、检查绑定、九转seed和sensor恢复证据与原方案/LLD §17一致，未发现阻断收尾的问题。28日新增补齐的25项分钟链产物在最后一次物理计数中全部有数据；整个当日审计仍有两项指数九转缺失，不能表述为DG全部数据集已齐备。

## 1. 审查范围与证据边界

本次只读当前代码、原LLD和本轮已生成的小型JSON证据，不连接正式服务或数据库、不读取正式Lake正文、不运行job、check或计算，不重复完整性审计。正式写入由原job完成，独立对账者只新增本报告。

本代理曾实现临时计数入口，因此不将自己的入口测试称为独立实现复审。该入口已由root另作源码复核，证据为[audit-count-only-root-review.json](audit-count-only-root-review.json)。本报告的独立结论针对正式run及既有结果之间的对应关系。

依据为[原方案和LLD §17](../../docs/design/dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#17-2026-10-28股票分钟链补齐方案和执行lld2026-10-29)、[具体范围批准](history-approval.json)、batch9/10/11的native-run与run-verified文件，以及最终计数和sensor恢复记录。

## 2. 原job顺序、日期和检查

| 阶段 | 原run id | 28日物化 | 通过检查 |
| --- | --- | ---: | ---: |
| QFQ日更 | `94384f7b-0b77-4317-998c-32da2a5e88dd` | 7 | 28 |
| 因子repair | `816a0d01-a56f-4f06-bdb3-1a7e0c05a793` | 0 | 7 |
| MACD/KDJ日更及state | `13e1b027-22c4-4268-950d-aaac9b5be9d2` | 14 | 28 |
| MACD/KDJ repair | `44caf58c-a1d9-4e37-b525-b82cda3179b3` | 0 | 14 |
| 四频九转 | `a9f7bedc-5041-48ab-8171-20c388bff5ea` | 4 | 4 |
| 合计 | 五个原job均SUCCESS | 25 | 81 |

原生启动请求使用`orchestrator/__repository__`中的对应原job；分区日更仅传28日partition和本轮标识，原因子job仅传`trade_date=2026-10-28`。各步骤均在前序成功并完成验收之后提交，未见跨阶段并行或提前启动九转。两个repair的完成check不计作额外数据集或物化。

日更原检查的准确asset/name集合、passing/blocking及目标storage id与本run真实28日物化对应。QFQ部分原生check partition为空，验收依已绑定的真实28日物化证明日期，未将空值说成已经修复。两个repair分别以本批7条和14条完成事件核验原guard；九转四项check另显式核对target_run_id及目标storage id。

对应证据：[QFQ日更](batch9/daily-run-verified.json)、[因子repair](batch9/factor-run-verified.json)、[MACD日更](batch10/daily-run-verified.json)、[MACD repair](batch10/repair-run-verified.json)、[九转最终验收](batch11/final-verified.json)。

## 3. repair名单、批次和保留范围

原因子job实际生成16股，范围为2014-01-02至2026-10-28、3,115个交易日。名单按换行连接后计算的SHA256与产物一致：

`c4a301285eb06a998bb596c4113580fb329a0f1b38f1d9fffa3119efa9824a91`

批次为`qfq_factor_repair:2026-10-28:3afb0b0b08f6`。factor产物、原decision、保存配置、MACD实际提交配置、repair完成记录及九转前置中的名单/hash/批次一致。MACD配置来自原builder，未把预估名单人工传给原因子job；完成gate的事件ID准确对应本run十四项记录，full gate为ready。

因子repair完成510份原生及208份派生QFQ年度目标；MACD repair完成723份指标年度及21,805份共享state目标。原publication验收核目标范围、promoted回执、候选已提升及正式文件身份；最后writer的合法更新不再以daily旧身份误判。

当前QFQ/指标writer按股票年度目标合并日期，MACD共享state保留未被replacement codes替换的既有股票。其他股票保留的结论依据原writer合并代码、执行范围及原候选/receipt/stat验收；本次没有新增对所有其他股票或其他历史日期的明细比对，也不将文件字节数说成设备实际读取量。

## 4. 九转seed及最终产物

[seed和候选范围证据](batch11/candidate-scope.json)来自实际factor名单及原有界候选函数。先核候选与全部实际年份/路径，再进行必要seed比较；去重历史468份、17,922,588B，包含其中2025/2026文件，小于批准1GiB。四频各16个seed结果，共64项全部匹配，差异0。

九转最终四项产物均promoted，合94,690行、241,902B，与实际来源计数及最终记录一致。验收记录中的正常来源、候选历史、factor历史和seed身份均保持，27日与29日相邻目标保持原状态；本次未回写27日seed或重跑其他日期九转。

## 5. sensor恢复

[恢复证据](sensor-restoration.json)记录：九转最终验收时五个分钟sensor仍STOPPED；2026-10-29 10:40:16完成五阶段验收之后，只对原五个准确selector执行startSensor。五个响应及随后只读状态均为RUNNING，`cursor_mutations=0`，无cursor写入请求。这里证明本轮未主动修改cursor，不代表sensor恢复运行后cursor不会按正常业务推进。

## 6. 唯一一次物理计数结果

最终证据为[final-physical-audit.json](final-physical-audit.json)，由原`dg_dataset_audit_count_only_20261028_20261029T024035847498Z.json`逐字节归档；报告观察时间为北京时间2026-10-29 10:40:35，业务日期为2026-10-28。未由本审查者重跑。

| 目录总数 | 实际审计 | 明确排除 | 有数据 | 真实缺失 | 未核实 | 零行文件 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 180 | 159 | 21 | 157 | 2 | 0 | 0 |

180＝138项直接分区＋14项年度族＋7项Serving＋21项非交易日驱动资产；159＝157有数据＋2缺失，分类完整。14项年度族均为2026文件、28日count，无额外代码/时间汇总字段。全部25项分钟链产物均`present`且行数大于0，与上述25项准确物化集合一致。

仍缺两项：

- `gold_major_index_daily_nineturn`：28日正式Parquet不存在。
- `prod_core_index_daily_nineturn`：`core_serving.index_nineturn_daily`的28日计数为0。

这两项属于本轮分钟链以外的指数链，未在本次自动补数。本计数只说明目标日物理存在性；81项原检查说明本轮对应job的原验收通过。二者都不等于全部DG数据、全部历史或所有字段的质量已经重新审计通过。
