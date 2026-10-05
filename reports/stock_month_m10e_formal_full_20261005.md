# M10.E 正式月线全量 bootstrap 验收

日期：2026-10-05，Asia/Shanghai。管理员本轮明确“提交。然后推进全量bootstrap”。先将小样本结果与post-sample预检提交a49609db，未推送；使用已提交e1f56646文件入口执行两源全量历史，未改业务代码或扩展到事件阶段。

## 结果与性能

| 主源 | 原始Prod行 | 排除20200229行 | 正式行 | 文件 | units | COUNT/COPY业务SQL | 新提交/同值复用 | 命令日志计时 |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| primary_unadjusted | 711255 | 3682 | 707573 | 201 | 225 | 450 | 198/3 | 195.964s |
| primary_adjusted | 710444 | 3682 | 706762 | 201 | 225 | 450 | 198/3 | 228.689s |

两源范围均2010-01至2026-09、201个月、17年度，共450units/402文件/1414335正式行。共396个新文件逐月原子提升、6个样本同值复用且字节hash未变化；7364条20200229全字段记录保留于staging排除台账。没有异值覆盖、静默去重、日期改写或预算拒绝。

只通过仓库psql-remote.sh读取raw_tushare.stk_period_bar/stk_period_bar_adj，freq=month，字段按现行13/21列白名单投影、不带采集信息。每unit≤300明确代码/3900计划上界/10000硬上限，真实COUNT/COPY同一READ ONLY REPEATABLE READ事务并ROLLBACK，30秒SQL超时/45秒unit监督超时，单连接串行。450份成功receipt、真实snapshot/control、capture、源运输证据均持久化；没有全历史长事务或Tushare请求。

工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`。完整两条apply命令与已核验的post-sample外部SHA见[执行清单](stock_month_m10e_full_commands_20261005.txt)。DAGSTER_HOME为`/Users/congming/.goldenshare/dagster_home`，文件入口不打开instance；后置instance审计仅读已有事实，禁自动建表。

正式路径为`/Volumes/datasource/data_lake/raw/tushare/{stk_period_bar_month,stk_period_bar_adj_month}/month=YYYY-MM/data.parquet`；所有capture/候选/台账/receipt/audit/checkpoint位于`/Volumes/datasource/data_lake_staging/stock_monthly_raw/<plan_hash>/<io_hash>/`。两个入口各按year处理、按unit持久化、按month同卷os.replace提交。退出或取消保留已完成事实，沿本次冻结计划/checkpoint续跑；不删除正式数据、不做Kopia或备份。

## 完整性与值核验

1. 两条apply自带34次年度集合文件审计，累计742次SQL，验证schema、业务主键、源月份和物理摆放、全字段canonical hash、排除台账及冻结交付证据；不是402次年度深扫描。
2. 执行后独立重读450个capture/receipt/control和402个正式文件。34个年度集合的全字段双向EXCEPT ALL差异均0，20200229台账与对应source capture双向差异也均0；源日期计数与冻结inventory、正式分区集合完全一致，无额外或缺失文件。schema/主键检查通过，duplicate key 0。
3. 正式2020-02只含20200228，其他月保持源自然月末，2026-05保持20260531。Decimal与NULL源值一致，正式end_date合法NULL为3960/3149行，共7109；不套新增源的截至门禁擅自填充历史NULL。
4. 两条命令日志计时合计424.653秒（约7.08分钟，不含命令间编排），正式Parquet合计61569878字节，单源年度集合audit约1.937/2.387秒；全量独立读回8.980秒。DuckDB沿既定512MiB/2线程/2GiB spill预算，没有实测正式进程RSS峰值或spill峰值，不借隔离值代替。本次事实为逐unit来源快照，不宣称一个全局Prod时间点事务。

完整路径/字节hash、450个事务快照、34个年度对账结果和各源汇总见[详细JSON](stock_month_m10e_formal_full_20261005.json)。未复权先行独立审计另见stock_month_m10e_unadjusted_full_readback_20261005.json；全量JSON为最终结果。

## 阶段边界

本轮只完成Prod月线批准历史投影的物理全量镜像，按管理员口径排除20200229，不宣称Tushare或日线期望的历史缺口已经全部消失。未新增Silver/Gold，未改weekly执行、src依赖矩阵、字段/日期合同或自动更新逻辑。

正式instance后置只读核对：cn_a_stock_months键0、两月线资产materialization均0。本轮未注册分区、补录runless事件、触发job或启用调度；文件通过不等于Dagster ready。下一阶段是独立事件计划dry-run、少量sample和批量report/final audit。M10.E文件阶段通过，事件阶段未完成；M9原验收和M10.F源实际更新/调度启用仍单列。

全量执行证据与本报告/文档状态更新尚未提交；当前已提交的是小样本结果a49609db。
