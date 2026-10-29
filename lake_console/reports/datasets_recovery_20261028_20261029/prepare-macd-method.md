# 28日MACD前置和原repair配置准备

本入口实现原方案/LLD§17.3—17.6已明确的本轮前置，不恢复23日旧preflight/control入口。只写本轮报告JSON；不触发job/sensor、不改cursor/pool/资源、不读Parquet正文、不计算价格或数据SHA、不初始化DG表。正式只读调用由根代理在对应前序通过后执行，本文件准备阶段没有连接正式资源。

## 原始依据

- 当前factor guard、readiness、原`build_gold_stk_mins_qfq_macd_kdj_repair_run_status_decision`及`_run_config_for_repair_decision`直接复用；不手工产生股票名单或配置字段。
- 当前`annual-baseline-current.json`真实生产字段为trade_date/observed_at/baseline_stage/day28_downstream_jobs_launched/qfq_two_year_bytes/qfq_2025_bytes/qfq_2026_bytes/macd_2026_bytes。基线实际来自08:58:31元数据stat；不是23日旧基线，不重复年度目录统计。
- 历史state的既有stat与原23日已核交易日期列表只用于文件预算和日期一致性；不使用旧41股名单。真实执行代码表、起止和batch/hash始终从本轮factor guard取得。

## preflight

1. 消费本轮batch9/daily-run-verified.json和factor-run-verified.json，要求28日、完整验收及SUCCESS，复核精确run的真实job、SUCCESS及partition或因子日期配置。基线观测时间必须早于本次QFQ daily start_time。
2. 查询现行factor guard，与刚接受的factor产物完整一致；核准确27日state的原readiness，不能退回更早state。
3. 只查本链5个job是否活动、5个sensor是否STOPPED、原共享pool是否空闲及原limit、分区是否已注册、Lake/staging同设备和空间。其他数据集运行不被拒绝；不要求daemon停止，不改任何开关。
4. Qd使用真实年度基线加28日已验收publication汇总的before→candidate净增量。daily与factor重叠的当前年目标，只对实际factor目标读取两份小receipt，确认daily candidate identity前四项等于factor before前四项；不重新读取39k年度文件或39k份daily receipt。
5. Qr与Ir仅按真实factor名单，用原discovery/路径函数枚举并stat2014—2026年度。原discovery若实际返回2013文件则在内容读取前拒绝；不glob全市场。B沿已存shared-state统计且要求只缺28日7份，U只stat27日7份，要求28日state尚不存在。
6. 沿原公式/预留核Qd≤18GiB、Qr≤1GiB、Ir≤2GiB及日更280/88GiB预算；这些是执行前预算核对，不施加给业务job的运行中限制。全部真实条件通过才以独占新建方式写batch10/preflight.json的safe_to_launch=true。

## prepare-repair

1. 消费本轮MACD daily完整验收，复核当前factor仍与preflight一致。使用原readiness，并要求14项最新物化ID与该daily验收完全一致。
2. 直接调用原decision函数；无历史改写时核原完整gate ready，不写空配置。若该upstream batch已存在有效completion则核完整gate，不重复提交。原decision拒绝时直接停止，不扩大股票范围或补字段。
3. 只有需要且未完成时才调用原`_run_config_for_repair_decision`；同一原输出分别写入decision.run_config和repair-run-config.json。decision同时写date/factor_gate/daily_run_id，满足根代理薄触发器的强绑定。
4. 只stat此前冻结的真实scoped QFQ输入，确认MACD daily没有改写其来源；只用daily-target-identities.json里实际因子股票的指标年度大小差额及7份28日state增量更新Ir/B，不重新扫描年度或shared state。
5. 沿原repair公式核36/20GiB预算。若需要提交才新建配置；最后新建repair-decision.json。已有证据不覆盖。任一步失败停止，可能已生成的配置小文件保留；薄触发器还必须有完整decision及对应真实daily/factor证据，不能单凭配置启动。

## 调用及产物

在orchestrator目录，沿正式DAGSTER_HOME和现有`.venv`：

```text
.venv/bin/python3 -B /private/tmp/dg_minute_chain_20261028_20261029/prepare_macd_20261028.py --mode preflight
.venv/bin/python3 -B /private/tmp/dg_minute_chain_20261028_20261029/prepare_macd_20261028.py --mode prepare-repair
```

第一条只能在QFQ daily和factor完整验收后调用；第二条只能在MACD daily完整验收后调用。默认读取本轮正式报告根内的annual-baseline-current.json；输出均在本轮报告根/batch10。脚本不创建正式报告目录，根代理应先准备目录。

## 隔离证据

`check_prepare_macd_20261028.py`以独立小JSON和stat标记文件验证，真实decision/config helper未替换；正式guard/readiness/存储由明确替身隔离。10项通过：真实schema的前置正例、原builder输出与手算增量、错物化绑定、factor批次变化、来源身份变化、原decision拒绝截断名单、已完成不再提交、无历史不造空repair、2025/26及重叠净增量、错误前序身份拒绝。语法和禁止业务/SQL调用静态门禁通过。

结果见prepare-macd-isolation.json：正式DB连接0、正式Lake访问0、Parquet正文0、job启动0，夹具目录无遗留。该结果只证明准备脚本的编排/身份/配置行为，不证明真实guard、数据或正式job已通过。实际前置/decision尚未调用。
