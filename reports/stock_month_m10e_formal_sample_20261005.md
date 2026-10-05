# M10.E 正式月线小样本执行验收

日期：2026-10-05，Asia/Shanghai。管理员本轮明确“先提交10.E的修改，然后确认执行小样本清单”。文件入口/LLD/冻结证据已先提交e1f56646，未推送；随后按已批准6条命令逐条串行执行，没有扩展正式写入范围。

## 正式文件结果

| 月份 | 未复权行数 | 复权行数 | 实际正式日期 | 全字段差异 | 重复主键 |
|---|---:|---:|---|---:|---:|
| 2010-01 | 1534 | 1534 | 20100131 | 0 | 0 |
| 2020-02 | 3632 | 3625 | 20200228 | 0 | 0 |
| 2026-05 | 5510 | 5510 | 20260531 | 0 | 0 |

总计76个已持久化source units、28709源行、7364条明确排除的20200229记录、21345正式行、6个正式文件。每个成功unit的源COUNT/COPY在真实READ ONLY REPEATABLE READ事务中执行并ROLLBACK；76份control有独立snapshot与snapshot_at证据，无模拟运输或Tushare请求。源业务SQL共152次，超预算拒绝未触发。

正式Raw严格保留两源13/21个业务字段及精确Decimal/NULL。2020-02未复权end_date=NULL 31行、复权24行与采集数据一致，未擅自填充；没有将28日改为29日，也没有将周末月末20260531改为最后交易日。20200229全字段排除台账仍在staging，C提升前已与capture精确对账。

正式文件仅位于：

- `/Volumes/datasource/data_lake/raw/tushare/stk_period_bar_month/month={2010-01,2020-02,2026-05}/data.parquet`
- `/Volumes/datasource/data_lake/raw/tushare/stk_period_bar_adj_month/month={2010-01,2020-02,2026-05}/data.parquet`

捕获CSV/Parquet、运输控制、排除台账、候选及receipt/年度audit/promoted checkpoint位于各冻结plan对应的`/Volumes/datasource/data_lake_staging/stock_monthly_raw/<plan_hash>/<io_hash>/`，正式business Parquet不混入采集字段。同文件系统逐文件原子提升；未覆盖未知异值文件，未使用Kopia/备份或删除数据。

## 验证与性能

各次正式apply均完成本源/本年集合校验及交付证明绑定；每份文件审计11次SQL，共66次。执行后独立重读所有76个capture及receipt/control、六个正式文件、排除证明，重新做双向EXCEPT ALL全字段差集、schema、重复业务键、文件内日期及正式目录摆放核验，均通过。每份receipt的四个artifact hash与真实文件一致；独立读回约0.667秒。

六条命令各自日志创建到末次写入耗时合计约54.523秒，范围4.541–13.274秒，未计命令间人工/工具编排间隔。正式文件合计946544字节。没有实测正式执行进程RSS峰值或强制spill；不将隔离RSS当作正式测量。逐unit事实和文件hash见[详细JSON](stock_month_m10e_formal_sample_20261005.json)。

## 事件状态与后续范围

用禁自动建表的现有正式instance入口只读复核：cn_a_stock_months键仍0，两源样本materialization均0；本次未触发job/sensor、动态分区写入、runless event或调度启用。物理文件验收成功不等于Dagster ready。

已另存小样本之后的全量只读preflight，两源各201预期目标，其中3个已存在、198个待创建。旧“目标全空”preflight保留为历史证据，不用于下一次全量apply。全量执行前须按阶段确认新预检及精确范围，发生同值复用才保留已完成样本；异值仍拒绝。后续全历史文件对账通过后再进入独立事件补录阶段。M10.E当前是正式小样本通过、全量及事件未执行；M10.F调度启用及M9原正式验收继续单列。

本轮执行未改业务代码、字段/日期合同、weekly行为或src依赖矩阵。提交e1f56646之后新增的六份正式file audit、独立读回JSON/本报告、两个post-sample全量预检及文档状态更新尚未提交。
