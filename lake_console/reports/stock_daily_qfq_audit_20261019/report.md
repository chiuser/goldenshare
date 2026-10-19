# 股票日线前复权遗漏回刷：已有审计结论

保存日期：2026-10-19。本文保存本会话此前已完成的审计，不是一次新审计。
本次整理没有重新读取正式行情、查询正式数据库、请求 Tushare 或运行 DG 任务。

## 1. 可以直接使用的结论

五只样本的未复权行情和复权因子，在已核验日期与 Tushare 一致；错误发生在历史前复权价格没有随因子变化回刷。
四个相关日更任务虽然成功，但没有正式 code location/repository 来源。
现有 run-status sensor 在 Dagster 的来源筛选处没有匹配到这些运行，未进入项目自己的判断函数。
以后只比较新一天与前一天的因子，无法重新发现已经错过的变化，因此旧价格保留至审计截止日。

这说明两处需要修正：补跑不能依赖某种运行来源才能接上历史回刷；遗漏必须能在以后被发现。
不能仅修改公式，也不能只扩大自动处理股票上限。

## 2. 五只样本的数值证据

检查范围：2026-01-01—2026-10-16；每股 188 条日线。下表旧行数只指这个范围。
“应有昨收”是对应前一交易日收盘价按审计截止日因子计算的数值，不是源站额外返回的字段。

| 股票 | 因子变化日 | 前一交易日 | 保存的收盘价 | 应有收盘价 | 范围内旧口径行数 |
| --- | --- | --- | ---: | ---: | ---: |
| 600020.SH 中原高速 | 2026-07-13 | 2026-07-10 | 3.76 | 3.6400066703 | 124 |
| 603167.SH 渤海轮渡 | 2026-07-10 | 2026-07-09 | 8.95 | 8.4498544735 | 123 |
| 000623.SZ 吉林敖东 | 2026-07-08 | 2026-07-07 | 18.06 | 17.7699689805 | 121 |
| 600919.SH 江苏银行 | 2026-07-10 | 2026-07-09 | 11.37 | 11.1402424881 | 123 |
| 000750.SZ 国海证券 | 2026-07-10 | 2026-07-09 | 3.77 | 3.7400057982 | 123 |

源接口交叉核验共 25 条 daily、25 条 adj_factor；Raw/Silver 与源端核验通过。
核验的 daily 数值字段比较数为每层 175 个，因子为每层 25 个。
不能将这些小样本扩大解释为所有 Raw/Silver 历史都已核验。

## 3. 正常运行与遗漏运行的区别

| 交易日 | 日更 run_id | 正式来源匹配 | 已查到对应历史回刷 |
| --- | --- | --- | --- |
| 2026-07-07 | 65334ef4-183f-4e87-9c58-6d117a84ef2c | 是，orchestrator / __repository__ | 是，b6b9274b-5184-4bb9-bb36-13cedf731113 |
| 2026-07-08 | 05ad10e4-5d57-412b-a708-67ffb1e905e5 | 否，external_pipeline_origin 为空 | 否 |
| 2026-07-09 | 422d61ca-ad6c-4c42-8fb0-162f457099da | 否，external_pipeline_origin 为空 | 否 |
| 2026-07-10 | 4749e345-2a28-489f-9861-3e2ab0991409 | 否，external_pipeline_origin 为空 | 否 |
| 2026-07-13 | 9f2cab89-bf09-4d2d-a2e9-5a045093ef7e | 否，external_pipeline_origin 为空 | 否 |

四日因子变化股票计数分别为 58、58、102、33，都低于当前自动上限 500。
它们的普通结构检查通过，不能据此证明历史回刷完成。
历史具体启动命令没有证据，不推断操作者或精确启动方式。
旧跳过 tick 已受保留策略影响，不能把查不到 tick 当成额外的执行证明。

代码依据：

- `defs/sensors/gold_stock_daily_qfq_factor_repair_job_sensor.py`：只监听指定日更成功运行。
- `defs/stock_daily_qfq.py`：相邻因子比较、以触发日期为截止日回刷历史、末尾汇总结果。
- `defs/ops/gold_stock_daily_qfq_factor_repair.py`：整个调用返回后才写完成检查。
- Dagster `run_status_sensor_definition.py`：先匹配运行的 location/repository/job，再调用用户判断函数。
- `tests/test_stock_daily_qfq_factor_repair_sensor_contracts.py`：直接测试内部判断，未覆盖框架来源筛选这一步。

上述 `defs/` 与 `tests/` 路径均相对 `lake_console/orchestrator/src/orchestrator/` 与 `lake_console/orchestrator/`。
当前相关源码的 SHA-256 保存在 [证据索引](evidence-index.json)，供以后判断哪些代码结论需要更新。

## 4. 证据文件与复用边界

[证据索引](evidence-index.json)列出 17 个原始结果文件的来源、字节数和 SHA-256，合计 496,747 字节。
这些文件由已有临时结果原样复制，未重新生成：

- [五股汇总](evidence/summary.json)、[五股逐日样本](evidence/sample_rows.json)。
- [Tushare 核验结果](evidence/tushare_live.json)、[运行来源](evidence/origin_comparison.json)。
- `sample_daily_events.json`、`sample_checks_counts.json`、`sample_materializations.json`：样本日更事件与普通检查。
- `sample_repair_runs.json`、`repair_checks_july.json`、`repair_ticks_july.json`：已有回刷和监听记录。
- `screening_audit.json`、`screening_qfq_verification.csv`：最初窄幅筛选的范围和核验结果。

初筛发现的 234 只股票只代表今年以来检查中发现并处理的范围，不是全历史错误总数。
72 只是那次筛选最终候选数，与应修股票总数无关。
本报告没有原正式 Lake 文件的完整内容 hash，不能仅凭这里的副本证明当前 Lake 仍与当时完全相同。
后续完整审计首次读取实际文件时补记身份即可；不因此重新进行本节五股原因排查。

结论没有自动过期时间。代码、输入、目标文件或检查口径实际变化时，只更新受影响部分；
证据丢失或损坏应报出具体缺项，不能默默重跑整次审计。
本报告只供人审阅、开发回归及规划引用，不接入日常 sensor，也不是新增正式资产或运行状态来源。

## 5. 与另一个已完成专项的关系

[25股历史因子专项](../../docs/design/dagster-stock-adj-factor-history-repair-plan-v1.md)已于 2026-10-18完成文件修复和 DG 观察记录登记。
该专项记录 25 股、31 资产、15,788 个目标文件，其中 11,425 个替换、4,363 个无需修改、失败 0。
这是原专项完成记录，本次只引用文档，没有再次查询或验收这些正式文件。
本次不恢复已经清退的专用工具，不改原计划/hash，不重跑该专项。
后续历史覆盖检查应复用其能够证明的对象和范围；范围外仍属未覆盖，不把 25 股完成推广为全市场完成。
