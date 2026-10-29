# 2026-10-28股票分钟链：原job、范围和预算核对

依据：当前HEAD `876cc6a8ed1c0fb944d8a01be69dd17e0dff2507`、23日batch9/10/11执行卡、23日history-scope-preparation、28日因子修正后的repair-scope-readonly.json。本次只读代码/已有报告、做目录元数据与stat；没有读取年度/历史价格正文，没有触发job/sensor，没有性能测试或代码修改。

## 可直接用于具体历史读取审批的范围

| 顺序 | 原job | 日期/读取与合并范围 | 正常读/写/额外空间GiB |
| --- | --- | --- | --- |
| 1 | stock_mins_qfq_daily_update_job | 仅补28日七频QFQ；读取28日Silver/因子，合并实际股票2026年度QFQ，保留其他日期；此步不读2025 QFQ | 34 / 9 / 12 |
| 2 | stock_mins_qfq_factor_repair_job | 原job自动生成实际名单，目前小因子预检16股；2014-01-02至2026-10-28、3115日、七频。来源为四个唯一频率1/5/30/60的全市场Silver日文件和历史因子；合并实际股票各年QFQ | 52 / 3 / 4 |
| 3 | gold_stk_mins_qfq_macd_kdj_daily_update_job | 28日七频指标/state；现行discovery会读2025/2026七频QFQ、准确27日state；合并2026指标年度文件，生成28日state | 280 / 88 / 96 |
| 4 | gold_stk_mins_qfq_macd_kdj_repair_job | 消费第二步真实名单/hash/batch，2014-01-02至28日七频指标；合并3115日×7共享state并保留其他股票，不能按16股比例缩小shared state读取 | 36 / 20 / 24 |
| 5 | gold_stk_mins_qfq_nineturn_update_job | 28日30/60/90/120四频；2025/2026 QFQ和27日seed。必要时一次实际变化股票seed核验；更早历史只限原有界候选查询的实际代码、2014—2026、候选文件合计≤1GiB，先stat再读 | 26 / 3 / 3 |

合计沿用原保守上界：正常各一次读428GiB、写123GiB、顺序额外空间128GiB。包含原检查、一次候选摘要、原DuckDB工作文件预留和最后receipt/stat；不是实测设备I/O，也不是新的内存/时间/并发/磁盘运行限制。失败停止后续，不自动重跑；追加一次同阶段预算只是续跑费用参考，必须先明确原root/receipt/实际剩余范围。

全市场年度基线复用23日metadata，不伪称是本次最新stat：两年QFQ约16.370GiB、2026指标约17.266GiB；原预留Qd18GiB、MACD候选20GiB保留。正式前沿26/27既有receipt及28日前序receipt更新，不为细化预算重复读取年度内容或做全目录正文审计。16股相关年度现有规模显著低于旧41股，H/B仅增加约47MiB/5MiB，旧52/36GiB的两个repair读取预留不需要增加。

## 实际stat

- 16股七频2014—2026已有QFQ：723份、148,790,838B；对应旧MACD：723份、378,182,606B。缺少的上市前/无行情年度路径不能自动判为缺失；是否生成新文件交原job实际来源决定。16股名单不是手工执行参数。
- 因子repair四频Silver历史：12,460份、47,423,932,430B，全存在；历史Silver因子3115份、113,410,783B，全存在。
- 共享state目标21,805份；现存21,798份、3,844,228,112B。仅28日七份缺失，必须先由MACD daily生成，再启动scoped repair。
- 原MACD discover会探测2013；16股×7频的112个2013路径均不存在。本次不申请2013内容读取；出现新的2013实际文件时先停在内容读取之前报告。
- 27日七份state共1,755,431B、四份九转seed共234,465B；都存在。26/27不重跑。
- 28日QFQ七目标映射的Silver字节D=56,815,263B：2×Silver1+2×Silver5+2×Silver30+Silver60，不能把四份去重大小相加当D。

详见同目录consumer-small-stat.json、history-stat-consumer.json、consumer-budget.json。

## 原入口和配置

工作目录 `/Users/congming/github/goldenshare/lake_console/orchestrator`；环境沿正式 `DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home` 和项目现有`.venv`。已只读检查`.venv/bin/dg launch --help`：本机接受`--module-name`、`--job`、`--partition`、`--config FILE`。未执行以下命令。

三个分区job分别用：

```bash
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job stock_mins_qfq_daily_update_job --partition 2026-10-28
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job gold_stk_mins_qfq_macd_kdj_daily_update_job --partition 2026-10-28
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job gold_stk_mins_qfq_nineturn_update_job --partition 2026-10-28
```

两个repair是op-only非分区job，不能传`--partition`。因子repair配置只含日期，不含股票名单：

```json
{"ops":{"stock_mins_qfq_factor_repair_op":{"config":{"trade_date":"2026-10-28"}}}}
```

再以相同module运行`stock_mins_qfq_factor_repair_job --config <本轮因子配置文件>`。股票名单、hash、起止、batch、改写统计及7条完成check全部由原job产生。

MACD repair配置必须在因子完成和MACD daily原28检查通过后生成：读取原`gold_stk_mins_qfq_factor_repair_status`，连同同日daily readiness交给原`build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision`，然后原`_run_config_for_repair_decision`。原字段为qfq_factor_repair_trade_date/start_trade_date/freqs/stock_codes/reason/repair_required_codes_hash/upstream_batch_id；结束日期由op从真实因子status推导，不能添加end参数或预算16股名单。`rewrote_history=false`时不造空repair，按原decision和完整gate记录不需要。

需要repair且尚无该batch有效completion时，再运行`gold_stk_mins_qfq_macd_kdj_repair_job --config <原builder输出文件>`。

## sensor实际顺序与本次手工编排

1. stock_mins_qfq_daily_sensor：19:30后检查Silver/因子并选第一个缺口。
2. stock_mins_qfq_factor_repair_sensor：19:40后要求当日七频QFQ ready再触发。
3. gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor：监控前两个job SUCCESS，并核同日factor ready和准确前序state。
4. gold_stk_mins_qfq_macd_kdj_repair_job_sensor：监控MACD daily SUCCESS，消费实际factor历史改写及完整名单/hash/batch，按原自动上限判断。
5. gold_stk_mins_qfq_nineturn_update_job_sensor：检查四频QFQ、factor repair和前序九转；代码本身没有要求MACD历史repair完成。因此五阶段全串行是本轮执行顺序，不能声称现有sensor天然保证九转一定最后。

本轮精确28日补齐期间继续保持五sensor停止，逐个原job通过后再启动下一步，避免后台抢先/重复提交。结束后按原维护记录恢复对应开关，不重置cursor、不调整资源或增加限制。根代理已只读确认27日五阶段成功，不重跑。

## 原检查、恢复和唯一收尾

- QFQ daily：7物化/28原checks；因子repair：7原completion，无7物化；要求现成factor status完整ready。
- MACD daily：14物化/28原checks；其历史repair：14原completion，无14新物化。要求upstream batch completion及最终daily repair gate均ready。
- 九转：4物化/4原checks；必要seed核验和有界候选范围必须在正式job前完成，不提前调用会打开未知旧年份的完整planner。
- 只核本次精确run、真实物化/check绑定、原operation/receipt与正式stat。不重跑普通checks，不追加年度全文比对/公式重算/SHA。daily与repair重叠文件最终identity以后写入的合法repair receipt为准。
- QFQ daily、factor repair、MACD daily和分钟九转已有root publication参数；重执行必须沿原root和原输入，逐文件receipt可复用，但前序关系准备仍可能必要重读，不能承诺零重读。
- MACD历史repair op当前调用writer没有传publication_id，实际operation随机生成。出现失败时必须保留记录、从原日志定位目录并核未完成范围；不能承诺新run自动复用旧receipt，不能盲目重跑全历史。此为现行已知恢复边界，本次正常补数不新增开发。

## 当前代码定位

defs/stk_mins_qfq_factor_repair.py:87/329：日期登记、当前因子/前日因子/Basic/生命周期身份冻结，按year/source一次加载及七目标重算。
defs/stk_mins_qfq_macd_kdj.py:169/920/1060：前一年source discovery、年度指标合并及共享state合并。
defs/ops/gold_stk_mins_qfq_macd_kdj_repair.py:174/377/550：要求所有目标state存在、验证真实上游scope、现行随机publication调用。
defs/sensors/gold_stk_mins_qfq_macd_kdj_repair_job_sensor.py:55/130：原decision和run-config生产者。
defs/qfq_nineturn.py:337/468/1224：查询前身份冻结、两年正常来源、有界候选键查询；不由手工名单替换。
defs/io/stk_mins_qfq_publication.py：原候选完整校验、一次摘要、原子提升及逐文件记录。
