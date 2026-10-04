# M6 五只退市股票备用周线 Raw 验收

2026-10-03 20:03（Asia/Shanghai）独立读回通过。按原方案、LLD §15/§29与接入模板7A完成五对象试点：源响应=捕获=正式Raw 3132行，734个周文件，业务值双向差集0、重复键0、错分区0、候选遗漏0。M6完成；不是全体退市或全市场覆盖完成。M5/M6修改仍在当前dev-interface工作区，未提交、未推送。

## 范围与结果

| 代码 | 原候选键 | 源/捕获/正式行 | 已恢复键 |
|---|---:|---:|---:|
| 000005.SZ | 656 | 656 | 656 |
| 000961.SZ | 732 | 732 | 732 |
| 002089.SZ | 674 | 674 | 674 |
| 300090.SZ | 473 | 473 | 473 |
| 600090.SH | 597 | 597 | 597 |
| 合计 | 3132 | 3132 | 3132 |

anchor范围2010-01-01至2026-09-25，2026-10-02排除；有候选的实际15年度、69 code/year units。Raw源日期20091231至20240510，11列、日期VARCHAR、数值DOUBLE、原单位；所有源字段NULL计数0，不清洗或自行复权。MCP本轮独立跨年请求确认20091231归属2010-01-01周；正式分区按同一周坐标核验。

目标唯一为`/Volumes/datasource/data_lake/raw/tushare/weekly/week_end={key}/part-000.parquet`；staging为`/Volumes/datasource/data_lake_staging/stock_weekly_raw/{plan_hash}`。同设备/空间/写权限预检通过，目标之前不存在。没有改主源Raw、Prod、Silver、API/前端、asset/catalog或Dagster instance/events/动态分区/sensor/schedule。

## 计划约束与实现

| 硬口径 | 真实代码点/验证 |
|---|---|
| 只取固定五对象已证实可补键 | M6年度candidate/expected CSV及v2 frozen scope；CLI load_weekly_inventory复用WeeklyHistoryScope与freeze_weekly_history_plan；AVAILABLE集合必须与expected完全相等 |
| 完整证据、不把失败视为空 | 候选及expected hash/列/大小/键/状态验证；包括EMPTY_CONFIRMED的全部源证据hash验证，失败/未查键不进unit |
| 保留源日期、列、值、单位 | WeeklySdkWorker、capture store原契约；源CSV→capture→formal全列EXCEPT ALL双向0；schema及全部字段NULL计数核验 |
| 年度捕获后只构建/提升一次 | 原candidate/promoter不改；独立年度阶段进程、全部receipt齐备后构建，签名/目标指纹/同盘replace/checkpoint门禁保留 |
| 取消/续跑/幂等重放 | v2首年度封存首unit后取消；最终69请求=69units，完整重放不增加请求；CLI缺token仅capture失败，dry-run不读token/不创建路径 |
| best effort及复权分开记录 | 未复权3132逐key已恢复；qfq/hfq各3132残余，6264记录引用2026-10-02原源空证据，明确未在M6刷新 |

正式Python改动仅扩充`lake_console/orchestrator/src/orchestrator/defs/bootstrap/stock_weekly_history_cli.py`和对应`tests/test_stock_weekly_history_cli.py`。源、schema、request builder、planner、candidate/promoter和预算值沿用既有实现；未新增配置项或依赖。备用离线inventory新格式不修改原Prod格式/现行参数行为。CodeGraph query/impact核验load_inventory、WeeklyHistoryScope、capture_weekly_history，直接阅读source、candidate/promoter及测试调用方补齐；当前CLI没有API/前端消费者，不影响子系统边界/依赖矩阵。

## 执行与性能

实际执行cwd：`/Users/congming/github/goldenshare/lake_console/orchestrator`。现有`.venv`，不安装依赖、不设置PYTHONPATH。TUSHARE_TOKEN仅继承现有环境，未写入命令、计划或报告。

执行命令分别为`.venv/bin/python -B /private/tmp/stock_week_m6_probe.py`、冻结脚本`stock_week_m6_freeze.py`、`.venv/bin/python -B /private/tmp/stock_week_m6_execute.py`和独立审计`stock_week_m6_reconcile.py`。临时执行协调器依次调用CLI的capture/build/promote；完整参数使用[年度冻结输入](stock_week_m6_frozen_scope_v2_20261003.json)中的inventory/plan、canonical capture/target roots，build附`--year`，promote附准确`--audit`，写入必须`--apply`。临时脚本不接入definitions；继续维护的正式入口是CLI。DAGSTER_HOME不读取、不初始化。

| 项目 | 冻结上界/实测 |
|---|---|
| 规模 | 5对象、15有候选年度、69units；request cap207，源行cap3293 |
| 实际请求 | v2捕获69次，来源快照5次，MCP边界1次；旧计划3次失败子进程启动保留，不算成功源响应 |
| 页/并发 | 每年度单代码单次有界请求，不用未验证分页；source_concurrency=1、默认1秒间隔/20秒截止/2次重试 |
| 内存/临时 | DuckDB512MiB buffer、2threads、2GiB spill；每阶段独立进程，外部12分钟期限 |
| 扫描与写入 | 单年度≤5 captures及同年度目标；原vectorized DuckDB业务合并/读回，734正式文件每个独立原子提交 |
| 输出/耗时 | 正式1372621字节；v2阶段累计153.213秒（不含预检/源刷新/最终独立对账和旧启动失败） |
| RSS | 自身退出peak255852544字节（244MiB）；采样进程树peak447283200字节（426.5625MiB） |
| spill | 1147次采样峰值0；目标采样间隔0.1秒，实际含ps/扫描开销；不能排除采样间隙短暂spill，未强制spill压力测试 |
| 恢复边界 | 已完成unit有receipt；候选/提升逐文件checkpoint，hash或业务差异拒绝；不增加预算/删除attempt/备份正式文件 |

临时测量启动器首次缺少__main__保护，spawn子进程重复执行协调器，被writer锁拒绝；消耗原unit三次尝试，未形成receipt或正式文件。修正启动器后，旧计划unit_attempt_budget_exceeded正确拒绝继续。原计划、attempt、[启动失败日志](stock_week_m6_logs_20261003/2010-startup-failed.log)及预算阻断日志保留；v2将真实源响应请求/时间/字段/CSV指纹/完整业务行冻结为每对象JSON，产生独立plan hash，预算仍沿用默认值。没有把v1失败称为v2成功续跑。

## 验证与证据

定向测试三组46、50、162项通过（含重复），最终补充EMPTY_CONFIRMED证据校验后CLI17项再通过；Ruff修改文件默认规则、全src/tests致命错误基线、文档integrity与diff检查通过，CodeGraph sync/status最新。仅使用隔离测试样本；真实源刷新和正式写入/只读审计独立执行。

- [最终独立对账](stock_week_m6_reconciliation_20261003.json)：源/捕获/正式数量、全业务值、key/分区/schema/NULL与每个正式文件hash。
- [执行及每阶段测量](stock_week_m6_execution_20261003.json)：年度capture/build/promote、取消/replay及RSS/spill/log hash。
- [未复权逐key](stock_week_m6_key_outcomes_20261003.csv)：3132行fallback_recovered。
- [前后复权残余](stock_week_m6_adjusted_residual_keys_20261003.csv)：6264行，核验日期保持2026-10-02；不是本轮重新证实当前无源。
- [MCP跨年实测](stock_week_m6_mcp_boundary_probe_20261003.json)、[五对象源证据](stock_week_m6_source_20261003/evidence.json)、[冻结范围v2](stock_week_m6_frozen_scope_v2_20261003.json)。

下一步M7：原211退市范围中剩余206对象有界查源、准入及补齐，251身份候选另核验；旧候选100505键只作调查基准，不能默认全能补。M8才单独补录事件，M9仍须完成更新机制。当前物理文件完成不代表DG事件/readiness或整个周月线项目交付完成。
