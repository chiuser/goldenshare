# 月线 M10.E：文件执行准备与小样本审批清单

日期：2026-10-05，Asia/Shanghai。M10.D已提交733fbd61，未推送。M10.E当前只完成执行入口、正式只读预检与隔离验收，未正式写湖、注册分区、补录事件或启用sensor。

## 已核验结果

- Prod只读入口：仓库根`bash scripts/psql-remote.sh -f <已审计SQL> -- -qAt`。仅raw_tushare.stk_period_bar/stk_period_bar_adj、freq=month，投影ts_code/trade_date/end_date的年度/日期聚合；READ ONLY事务/ROLLBACK、30秒超时、32MiB work_mem。全量原始库存及3个样本月库存均保存JSONL；没有业务数据写入。
- 2010-01至2026-09：两源711255/710444源行，明确排除20200229各3682行，预计正式707573/706762行、450units、402files。原始起止和范围外0行也已只读核验。
- 固定Lake和staging根既存、已挂载且同卷；剩余约2.93TB。402目标均不存在；cn_a_stock_months键0，两月线资产物化记录0。instance仅用禁自动建表的现有入口查询已有状态，未初始化/修改instance。
- 210项不同月线回归已覆盖（首次208项，最后24项入口回归含2项新拒绝样本；不重复加总）；113项受保护静态、12项资产治理门禁通过。Ruff默认/致命基线、隔离完整definitions及docs integrity通过，CodeGraph已使用explore/impact并sync/status。
- 缓存真实Prod样本在/private/tmp验证两个年度集合：各12文件，3561/3565准入行，全字段双向差集0。年度文件审计各22 SQL；含完整捕获/候选/提升及末尾审计首次0.525/0.444秒，续跑无新增源调用。RSS累计峰值255.5/284.6MiB；此为300代码历史样本，不证明全市场性能、强制spill或新Prod事务正确性。

## 本次待批准的正式小样本

仅以下3个完整月、两源各1文件，共6文件；不做对象抽样，不向正式月分区写半市场数据。

| 月份 | 未复权准入行 | 复权准入行 | 原始源行合计 | 排除行合计 | units合计 |
|---|---:|---:|---:|---:|---:|
| 2010-01 | 1534 | 1534 | 3068 | 0 | 12 |
| 2020-02 | 3632 | 3625 | 14621 | 7364 | 26 |
| 2026-05 | 5510 | 5510 | 11020 | 0 | 38 |

总计28709源行、排除7364行、正式21345行、76个串行连接/152次业务SQL预检和COPY。实际SQL/事务证据以每unit持久化控制文件为准。单元45秒监督超时，30秒SQL超时，DuckDB512MiB/2线程/2GiB staging spill；预留至少2282749952字节，超预算停止。不能用纯本地样本的亚秒耗时预测76次远程连接；实际时长在小样本执行后记录，理论unit超时上界3420秒。

工作目录：`/Users/congming/github/goldenshare/lake_console/orchestrator`。
正式`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`；本文件阶段不打开instance，因而不产生Dagster任务或事件。
Prod投影严格是现行13/21业务字段，不包含采集信息；每unit READ ONLY REPEATABLE READ且ROLLBACK。2020-02两源只落trade_date=20200228，20200229完整保留在staging排除台账；2026-05保留20260531，不改为29日。普通月保留20100131。

正式目标根：`/Volumes/datasource/data_lake`，下述两个目录仅所列3个月的data.parquet：

- `raw/tushare/stk_period_bar_month/month=YYYY-MM/data.parquet`
- `raw/tushare/stk_period_bar_adj_month/month=YYYY-MM/data.parquet`

采集、候选、spill、排除台账、receipt、年度audit和promoted checkpoint位于`/Volumes/datasource/data_lake_staging/stock_monthly_raw/<本清单plan_hash>/<固定IO_hash>/`。精确plan/preflight/范围与外部SHA见[冻结清单](stock_month_m10e_frozen_scopes_20261005.json)。控制报告只写仓库reports。以下6条命令逐条串行执行，已核验dry-run，无任意SQL或覆盖参数：

```bash
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_monthly_history_cli apply --plan /Users/congming/github/goldenshare/reports/stock_month_m10e_2010-01_primary_unadjusted_20261005_plan.json --preflight /Users/congming/github/goldenshare/reports/stock_month_m10e_2010-01_primary_unadjusted_20261005_preflight.json --preflight-sha256 7f63fdcce075719576dc9c8319d537c56e618ebf4a39a719fe733057297da536 --output /Users/congming/github/goldenshare/reports/stock_month_m10e_2010-01_primary_unadjusted_20261005_files.json
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_monthly_history_cli apply --plan /Users/congming/github/goldenshare/reports/stock_month_m10e_2010-01_primary_adjusted_20261005_plan.json --preflight /Users/congming/github/goldenshare/reports/stock_month_m10e_2010-01_primary_adjusted_20261005_preflight.json --preflight-sha256 028f4b6d72735f583270af62247feb4256a9b0c40cafbeef76b5699de7cb563a --output /Users/congming/github/goldenshare/reports/stock_month_m10e_2010-01_primary_adjusted_20261005_files.json
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_monthly_history_cli apply --plan /Users/congming/github/goldenshare/reports/stock_month_m10e_2020-02_primary_unadjusted_20261005_plan.json --preflight /Users/congming/github/goldenshare/reports/stock_month_m10e_2020-02_primary_unadjusted_20261005_preflight.json --preflight-sha256 e6697d961bc5cddf121e07a46f204da7aaa8df3bbe291a9f18d3907c24dfdee0 --output /Users/congming/github/goldenshare/reports/stock_month_m10e_2020-02_primary_unadjusted_20261005_files.json
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_monthly_history_cli apply --plan /Users/congming/github/goldenshare/reports/stock_month_m10e_2020-02_primary_adjusted_20261005_plan.json --preflight /Users/congming/github/goldenshare/reports/stock_month_m10e_2020-02_primary_adjusted_20261005_preflight.json --preflight-sha256 740095791beac8c624ba95f091a22751245fe4dceeeef3022e651e6b909ef8bf --output /Users/congming/github/goldenshare/reports/stock_month_m10e_2020-02_primary_adjusted_20261005_files.json
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_monthly_history_cli apply --plan /Users/congming/github/goldenshare/reports/stock_month_m10e_2026-05_primary_unadjusted_20261005_plan.json --preflight /Users/congming/github/goldenshare/reports/stock_month_m10e_2026-05_primary_unadjusted_20261005_preflight.json --preflight-sha256 05706c8e677fbea96c59d810dfbffe5cfe0ab8f71238ece0d56da9972db13efc --output /Users/congming/github/goldenshare/reports/stock_month_m10e_2026-05_primary_unadjusted_20261005_files.json
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_monthly_history_cli apply --plan /Users/congming/github/goldenshare/reports/stock_month_m10e_2026-05_primary_adjusted_20261005_plan.json --preflight /Users/congming/github/goldenshare/reports/stock_month_m10e_2026-05_primary_adjusted_20261005_preflight.json --preflight-sha256 a418aef33545bbaaf398df78605c94a95ab130fd29f0e4810902aeee6cfb1025 --output /Users/congming/github/goldenshare/reports/stock_month_m10e_2026-05_primary_adjusted_20261005_files.json
```

恢复与拒绝：SIGINT/SIGTERM只停止领取新unit，保留完成receipt/已提交文件；同命令沿冻结计划与逐文件checkpoint续跑。业务文件提交后状态或报告失败不回滚文件；不删表/文件/事件，不做Kopia或备份。目标存在同值可复用；异值、漂移或异常证据一律停止，须另行确定修订范围。不同sample计划与后续full计划共用source-month目标锁。小样本成功后，全量preflight必须重新冻结并列明同值目标，不能沿样本前的“目标不存在”预检直接执行。

## 尚未执行与下一阶段

正式小样本需按orchestrator AGENTS的正式执行门禁批准；全量文件、事件小样本/批量补录随后各自冻结清单并审批，不包含在本次6文件执行中。文件年度聚合对账通过后才准备402次materialization和1206次blocking checks，绑定正式文件证明及精确目标事件ID；没有正式绿色事实时不补录绿色事件。M10.E未完成，M10.F实际源更新与启用另行推进，M9原正式验收仍保留。

本轮仅新增月线bootstrap运营CLI与薄编排模块，测试隔离器新增3个精确源码读取路径。没有改字段/日期合同、asset/check/job/sensor、周线执行、Prod接口、src依赖矩阵或正式路径。其他任务的工作区修改保留。M10.E代码尚未提交。
