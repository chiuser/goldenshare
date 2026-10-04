# M7 执行前冻结与范围

依据原方案、LLD §15/§31和M6物理验收继续M7。当前dev-interface，既有无关脏文件保留，未提交/推送。正式执行进行中，本报告不作为完成证明。

## 冻结结果

- 退市剩余206对象、100505候选键，206次成功完整weekly历史调查，100505源行，候选全部source_available。
- 身份251对象/63460键先读正式identity map和两主源Raw。245对象/38893键处于confirmed整周有效区间，另24567键未通过该门禁（包含2对象897 inferred键、249对象23670有效区间之前或边界）。不改映射或Raw代码。
- 对上述245对象按原始代码查询weekly，245次成功、源响应49193行；36044候选键可补，2849候选键成功历史请求未返回行。该2849不是整对象无数据。
- 原M6五对象/3132行/734文件指纹预检一致，M7只合并备用Raw并保留原业务值。
- 两支共139398个调查候选键，136549 AVAILABLE、2849成功缺行；24567 identity pending不进入apply。实际16年度、3232units，默认重试下request cap9696、单位完整返回行cap144964。源调查窗口以外、unit请求范围以外记录不计为本轮应写入行。

## 硬口径与落点

| 口径 | 代码/证据/正反门禁 |
|---|---|
| 只取冻结对象和源可补键 | 原WeeklyHistoryScope/freeze_weekly_history_plan；CLI candidate/expected集合相等及文件hash；失败/未查不进unit |
| 周坐标与真实源日期分开 | 现有source request Monday–Sunday；Raw VARCHAR保源日期；candidate真实日期投影ISO Friday，边界测试保留 |
| 不改正式映射/只确认有效区间 | 本轮只读identity map和原始源日期，confirmed且整周在区间；inferred/无map/区间外/边界不当已覆盖 |
| 不把空/失败/未决混为一类 | 451对象逐请求参数、时间、字段/rows/rawCSV/JSON/hash证据；成功缺行按key保存，与failed/contract blocked/pending分开 |
| Raw只保weekly真实11列 | 原WeeklySdkWorker/capture schema/finite/precision/key/range校验，源日期和单位不改，不制造freq/qfq/hfq |
| 年度只完整构建/提升一次 | 同年度manifest capture按20个新receipt进程批次，单位封存后安全取消；全部成功才build，签名/完整值差集/指纹/replace/checkpoint门禁保留 |
| 不扩大副作用 | 目标raw/tushare/weekly，staging canonical；主源/identity只读，Prod/Silver/instance/events/sensor/schedule均不写 |

正式源码和配置本轮不新增/修改；复用原CLI、planner、source、capture、candidate/promoter。临时报告/执行脚本不接definitions，默认预算沿用WeeklyBudget并随plan冻结。CodeGraph query/impact核验capture_weekly_history、load_weekly_inventory、plan_weekly_source_units、build_stock_identity_map_rows；直接代码/consumer阅读补齐范围与恢复语义，没有API/前端或src子系统消费者变更。

## 预算与执行

源调查实际451次（206退市+245身份），按范围分别最多618/735尝试、每对象≤874周/显式11列/22秒外部截止。字段/身份/范围/同周唯一性/required NULL/非有限值/负vol或amount校验；当前所有对象成功，没有将zero-column认作空源。

capture并发1、20秒截止/至少1秒间隔/2次重试；每进程最多新增20receipts，原manifest续跑校验以前receipt，不重拉已完成单元。16年度每年一次向量化候选与提升；最多319units/年度，冻结源行cap144964、857文件上界，保留M6业务投影。DuckDB512MiB仅buffer预算、2线程、2GiB spill。每工作阶段12分钟外部截止，取消/失败保留数据和attempt；不清空checkpoint或扩大预算。年度resume的已完成receipt重验开销及实际elapsed、process RSS/tree RSS/spill独立记录；0.1秒目标采样含系统调用开销，为峰值下界，不能声称压力通过。源调查CSV/JSON和年度candidate证据远低于当前约2.94TB可用空间。

cwd为`/Users/congming/github/goldenshare/lake_console/orchestrator`，现有`.venv`。正式控制命令`.venv/bin/python -B /private/tmp/stock_week_m7_execute.py`，只使用[冻结年度输入](stock_week_m7_frozen_scope_20261003.json)，capture批次调用现有capture_weekly_history，build/promote调用CLI明确的year/audit与apply。staging `/Volumes/datasource/data_lake_staging/stock_weekly_raw/{plan_hash}`；目标 `/Volumes/datasource/data_lake/raw/tushare/weekly`；不读取/初始化DAGSTER_HOME。中断重新执行同一命令按已封存receipt/年度audit/checkpoint恢复，先对账后继续。

## 验证与待验收

47项相关隔离回归通过（CLI、历史coordinator、planner/source），文档integrity/diff检查通过；没有把正式资源作为测试样例。源真实调查和身份只读核验独立于测试。正式源→capture→target全部业务列、文件集/指纹、分区/schema/NULL/key、旧M6数据保持和逐key分类数量守恒仍须最终独立对账，本报告不代替这些结果。复权来源可补性另记录，weekly恢复不代表qfq/hfq恢复。

证据：[身份只读审计](stock_week_m7_identity_audit_20261003.json)、[源键分类](stock_week_m7_source_key_classification_20261003.csv)、[同盘/原目标预检](stock_week_m7_preflight_20261003.json)、[退市来源证据](stock_week_m7_source_20261003/evidence.json)、[已确认身份来源证据](stock_week_m7_identity_source_20261003/evidence.json)。M8事件补录及M9更新机制尚未执行。
