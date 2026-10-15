# Prod复权周线现行交付与8月月线独立待办 v1

更新：2026-10-16。本文维护Prod现行合同和未完成待办；DG新方案已改为Tushare直接源bootstrap，不再把Prod刷新或搬运作为DG前置。执行安排后置于DG周/月Raw与Silver均完成并验收之后；本轮不部署、不执行Prod维护。

## 1. 当前事实与边界

2026-10-13周线15565/15604及B0=1785交付已完成，DG接收859周文件/3,028,907行；这是历史事实，不重开首次搬运任务。Prod周线Raw/Serving及不可变闭合批机制继续按现行实现运行。

[DG总方案](../../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md)改为单股无时间参数历史下载、每日当前周期覆盖和因子变更单股历史刷新，尚未开发或切换。切换完成前DG仍是旧入口，之后不再消费Prod闭合批写这两个目标；不因DG退出消费而删除Prod交接表、数据集或入口。

## 2. Prod保留的运行合同

1. DatasetDefinition→DatasetActionResolver→DatasetExecutionPlan→ingestion builder/executor为现行执行链；Ops只保存意图与观测，不拼源参数。
2. 已结束周规划、新周全市场及因子变化股票历史区间请求沿现行Prod策略；不能把DG无时间全历史请求或当前周期新设计自动当成已修改Prod。
3. 每unit完整捕获、归一化、校验，一个短事务提交Raw、Serving及交接unit；观测失败不回滚业务。原批未完成沿冻结计划恢复，不用新意图绕过欠账。
4. core.stock_weekly_adj_delivery保存不可变plan/unit/closure；当前DG按revision消费，待新链正式切换后退出该消费，不保留双写。合法空批不造行情或物化。
5. 北交所因子/复权对象请求只能使用确认的新代码，历史日期不改，不回退旧码；新码策略仍须迁移实际消费者并验收，不能声称当前通用builder已自动完成。全市场回包保留原代码，不把旧行改名后upsert。
6. 21业务字段及源精度/NULL保留，不用本地计算价覆盖源价；end_date是源计算截至日期，不是该历史K线内部的最后交易日。

现有单位、事务、并发、恢复、诊断和交接合同见[Prod LLD](stock-weekly-adj-refresh-low-level-design-v1.md)。不把旧局部256MiB/1,000unit等预算搬到DG直接源任务，也不擅自更改Prod预算。

## 3. 8月月线独立待办

2026-10-15证据：Prod复权8月5,551行、trade_date均20260831，大量end_date仍20260828；平安银行旧close=11.65，MCP当时为11.72。完整月份旧价格问题已确认，不能因为DG重新下载就宣称Prod也已修复。

仅两个Prod月线数据集、freq=month、trade_date=2026-08-31：raw_tushare.stk_period_bar→core_serving.stk_period_bar，raw_tushare.stk_period_bar_adj→core_serving.stk_period_bar_adj。沿现行链短事务upsert本次源返回键，保留未返回旧键并解释；不清表、不删week或覆盖其他月份，不借用周线交接表建立月线旁路。

正式执行前只确认该月分页完整、显式13/21字段、有效新码与精确范围；记录本次源值并读回Raw/Serving。取消/进程退出保留已提交unit，状态和业务提交分开。异值/目标漂移、旧码兜底、分页截断和错误scope拒绝；其他月份若需维护另列已确认范围，不重扫全历史来证明8月写入。

本待办未执行。DG旧8月及其他月份由其直接源bootstrap处理，不再承接本节源批到DG的搬运/逐月候选步骤。两个任务独立关闭，正式数据库写入、部署与执行卡另行确认。

## 4. 验收与后续

Prod最小验收：请求参数/新码正确，源完整页、Raw/Serving业务键与完整行一致，范围外不变，已提交可恢复，TaskRun和节点终态一致，观测失败不回滚业务。新共享合同或配置变更先审计所有消费者与模板，不恢复旧worker lane或增加通用状态机。

DG和Prod各自保留真实执行证据，不互相冒充完成；先完成DG周/月Raw与Silver，再单独确认本Prod待办及其他后置任务，不默认沿用旧修复流程。详细历史从Git及日期报告追溯，不作日常运行依赖。
