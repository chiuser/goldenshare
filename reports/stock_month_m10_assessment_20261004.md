# 月线 M10.B：来源、库存、性能及纯规划验收

2026-10-04，Asia/Shanghai。依据月线专项LLD及已确认的2020年2月仅28日口径。本阶段完成只读来源证据、纯合同和bootstrap规划；不代表月线已接入正式DG。

## 结论与库存

| 项目 | 未复权 | 复权 |
|---|---:|---:|
| Prod月线原始行数 | 711255 | 710444 |
| 明确排除20200229版本 | 3682 | 3682 |
| 预计准入行数 | 707573 | 706762 |
| 自然月份数 | 201 | 201 |
| 300代码年度unit数 | 225 | 225 |
| 最大unit规划行数 | 3900 | 3900 |

范围2010-01至2026-09，两表完整范围之外行数为0。两源各202个源日期，唯一非月末是20200228；排除29日后201个文件/源，共402个。准入合计1414335行，不把排除7364行记为异常reject。Raw保留28日原日期与两源原复权版本，不拼29日字段。历史NULL end_date继续保留；库存原始NULL数3960/3149，不拿它们要求bootstrap重拉源。

只读库存为同一REPEATABLE READ READ ONLY事务，逐年度记录有序代码、日期计数和NULL数量，30秒语句超时、32MB work_mem；仅使用psql-remote.sh，两个已获准Raw表业务字段及元数据。前置表规模/索引核验后执行目的明确的库存聚合，没有读取Ops/Serving或采集字段。

## 源端真实分页与性能

两主源合计20次SDK只读请求、零重试，复用已有监督执行器及资源调用，单请求20秒边界。2020单对象每源13行，分页5/5/3/0与完整响应的键及全部13/21字段一致；9月全市场各5571行，offset=6000空尾页，三个13行小页与完整响应前39行逐字段一致且无跨页重复。全部显式字段齐全、样本数值小数位最多2，类型容量仍按Prod Numeric四位定义。审计总37.598秒含20个1秒间隔；此数不等于自动更新耗时。

Prod两表主键均(ts_code,trade_date,freq)，300代码年度样本走Index Scan。2020代表unit实际3854/3860行（CSV428893/667221字节），显式13/21列，数据库EXPLAIN ANALYZE执行14.405/11.468毫秒；该缓存样本不是全量吞吐或网络时延估计。

临时DuckDB以VARCHAR读CSV、明确CAST为VARCHAR/DECIMAL后，保留28日、单列排除29日293/295行，再写月分区Parquet。3561/3565行读回、24个临时文件，双向EXCEPT ALL差集、重复键及schema差异全部0，reject=0；捕获=准入+排除守恒。转换/写出/读回耗时0.245/0.074秒；进程累计RSS峰值162.953MiB。配置512MiB buffer/2线程/2GiB spill；结束留存spill=0，没有过程峰值或强制spill压力证明。

样本压缩41.683/71.190字节/准入行，按当前行数线性估算正式Raw约80MB，非全市场文件大小承诺。全量bootstrap预计450个串行只读unit、最多900个unit业务SQL；不调用Tushare逐股复制历史。若每unit触及45秒期限，超时部分硬上界20250秒（5.625小时），触及边界必须中断/分批重设，不能据此给用户伪造ETA。真实全量时间、spill峰值、提升成本仍须小样本及全量阶段记录。未来正常新增月两源预计2次请求，分页/技术重试总上限24；超过行数或页上限停止。

## 代码与计划对账

- run_contracts/stock_monthly.py：两主源、13/21字段类型、月份与源日期分离、2020版本选择、typed预算、有界point请求、不可变库存及计划类型；没有资源、文件或网络操作。
- stock_monthly_planner.py：库存闭合、年度全覆盖、范围/证据hash校验、300代码切分、最后一年截止2026-10-01、确定性plan/unit身份及数量守恒。库存为空需显式记录；不因缺期伪造月份，不以29日补28日。
- 两组测试66项：日期/闰年/周末、异常日期/备用源拒绝、schema/字段、预算负例、mutable输入冻结、重复/未闭合库存、证据变更、unit代码集合不重不漏、范围外与超预算不截断。
- 相邻周线回归合计136项通过。完整113项受保护静态门禁通过；原清单又新增4个公告源码，仅补其精确只读路径，未改公告实现或放宽断言。改动文件默认Ruff、全src/tests致命错误基线、整个code location隔离加载通过。

CodeGraph explore覆盖原weekly合同/库存/规划、日期及14个normalize_week_key调用方，进一步按当前代码确认原周线执行栈不可直接承接month。新增纯模块不修改原weekly合同或消费者；root索引已sync/status。无src依赖矩阵变化，无新正式资产、partition、job或sensor；候选只在/private/tmp，无正式Lake/Prod写入。没有安装依赖、Git提交或推送。

## 证据与下一步

- stock_month_m10_prod_metadata_20261004.jsonl、prod_inventory及prod_bounds：类型/索引、完整库存与范围边界。
- stock_month_m10_pagination_20261004.json：20调用、参数、全字段fingerprint、分页闭合。
- stock_month_m10_performance_20261004.json及两份explain：代表unit与临时读回。
- stock_month_m10_bootstrap_plan_20261004.json、inventory_summary：450units及schema/策略/库存hash。标记为规划证据，不能作为正式apply授权。
- stock_month_m10_defs_validation_20261004.json：临时instance的dg加载验收。

下一切片M10.C为capture、候选和逐文件提升的隔离开发。当前尚无月线writer、CLI、资产/check/job/sensor或正式文件；要进入正式bootstrap须先刷新库存、核对plan hash、完成代表性的取消/续跑读回并分阶段批准。M9周线正式验收仍待源站生成10月2日数据，调度保持停止。
