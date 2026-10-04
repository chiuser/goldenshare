# DG 股票周线 M5 预检与阻断记录

截至2026-10-03，M4已提交`eb1a3aab`，未推送。M5已完成两主源实时Prod只读库存、正式目标只读预检、全量/试点捕获计划草案及空边界证据修正；**尚未完成M5正式bootstrap验收**。未捕获正式staging、未写正式Lake、未访问或写入正式Dagster instance。捕获传输路径与本机规则冲突，等待管理员确认后继续。

## 实时只读范围及结果

唯一网络入口为`bash scripts/psql-remote.sh -f /private/tmp/stock_week_m5_inventory_20261003.sql`；遵守AGENTS.local.md。两张白名单表为`raw_tushare.stk_period_bar`、`raw_tushare.stk_period_bar_adj`，只读`freq='week'`，库存过滤为`2009-01-01 <= trade_date < 2028-01-01`，包含首尾邻年；没有在市/退市筛选。一个repeatable-read/read-only事务，statement_timeout30秒、work_mem16MB，最后rollback；未执行数据库写SQL。

字段投影仅年度、ts_code、count、min/max trade_date、非周五计数、价格/成交量等业务NULL计数。没有SELECT *或采集信息导出。库存输出122473条code/year汇总，两组日期边界和一条快照记录；一次有界聚合覆盖各表，然后查询indexed日期边界，不在各个unit重复全表DISTINCT。NULL观察计数仅针对SQL列出的行情数值字段，不包含end_date，不能用其宣称所有源字段均非NULL。

| 来源 | 源行数 | 年份 | 起止日期 | 300代码units | 数值NULL／非周五行 |
|---|---:|---|---|---:|---:|
| 未复权 | 2895784 | 2010–2026 | 2010-01-01至2026-09-25 | 212 | 0／0 |
| 复权 | 2891262 | 2010–2026 | 2010-01-01至2026-09-25 | 212 | 0／0 |

2009与2027在获准窗口内均无行，来自完整聚合和日期边界证据，不能用未请求或接口报错替代。当前snapshot为`11369700:11369700:`，transaction timestamp为2026-10-03 15:15:42.700054+08。跨后续捕获unit不共享此快照；每unit需新snapshot/control count，最终delta audit应核实源变化。

报告入口：[库存CSV](stock_week_m5_prod_inventory_20261003.csv)、[年度预算CSV](stock_week_m5_year_budget_20261003.csv)、[日期边界](stock_week_m5_prod_bounds_20261003.csv)、[快照](stock_week_m5_prod_snapshot_20261003.csv)、[计划摘要](stock_week_m5_preflight_summary_20261003.json)。两源的`frozen_inventory`及`capture_plan` JSON位于同目录，包含hash和明确代码列表；它们是待执行计划，不能视为capture receipt。

## 正式目标与性能门禁

[Lake预检](stock_week_m5_lake_preflight_20261003.json)：两份目标`raw/tushare/stk_period_bar_week`、`stk_period_bar_adj_week`尚不存在、零目标文件。正式根与staging均存在、无symlink、设备号相同，自由空间约2.94TB。本轮沙箱内os.access返回不可写，尚未用实际获准写入环境验证权限，不能据此判定宿主目录不可写或尝试创建目录。

全量范围两源共5787046行、424units；各源预计857个实际周文件，保守19年×54=1026文件上界，低于phase3000上限。每unit300代码、≤30000行、≤45秒、SQL≤30秒、fetch≤10000；每unit最多3个source chunks，捕获与控制查询约424次事务、424次计数和424次有界读取，附带事务/快照/超时控制语句。DuckDB512MiB/2线程/spill2GiB，只在正式staging受控目录使用。单文件原子replace、逐文件checkpoint、dataset/week锁；无全历史长事务，无逐周Dagster backfill。

M0样本压缩外推约321MB仅为目标数据参考；实际source chunks、候选、目标及试点后重写字节应在执行中逐阶段测量。本轮不把离线CSV聚合或M4离线耗时作为真实导出ETA。424×45秒是unit超时总上界约5.3小时，不是预计耗时；试点不达标应在冻结新计划前拆分unit，不能在apply扩大预算。

[试点预算](stock_week_m5_pilot_budget_20261003.json)：各源选2025年有行的前300个排序代码，捕获2024–2026三个自然年，以覆盖2025所有ISO周边界；各3units、41932输入行、15450归属2025行、最多54周文件。仅拟输出2025、最多两源108文件；不得称全市场bootstrap已完成。试点库存CSV与计划JSON由同次真实全量汇总生成可复算子集。后续全量合并试点重复行必须值一致，并单列rewrite bytes。试点尚未执行。

## 已修正的独立边界问题

M3原实现只用非空capture unit的年度区间判断完整边界。2010首周跨入2009，真实2009库存为0且无unit，于是被拒绝为`year_boundary_inventory_missing`。不能制造有数据unit，也不能使用正式目标禁止的partial_scope。

`defs/bootstrap/stock_weekly_candidates.py`新增冻结库存证据读取：只识别`prod_weekly_inventory@1` JSON；受控路径/hash、16MiB文件上限、readonly/repeatable-read标记、日期窗口、ProdYearInventory/Scope及完整manifest复算全部通过后，再独立核对原始库存CSV的各年代码集合/控制行数。只有rows=0且codes为空的年可扩展边界区间；CSV hash同时加入audit evidence，后续变化阻断。旧格式、缺声明、JSON/源身份/快照/窗口/计划不一致、伪装空年、篡改均拒绝。未修改WeeklyPlanManifest/receipt schema、已有plan hash算法、Prod访问resource或全局连接工厂。

新增`tests/test_stock_weekly_inventory.py`。相关回归87 passed、static gates113 passed；新代码默认Ruff、全项目致命错误基线、docs integrity与diff检查通过。真实库存在临时目录再次核验，两主源2009/2027空窗口及完整manifest匹配，2010边界通过后按预期停在`capture_incomplete`，未伪造receipt或宣称已写湖。详见[边界核验](stock_week_m5_boundary_preflight_20261003.json)。初始正例测试误把返回audit路径当dict，改为读取真实audit后通过，没有修改实现来迁就测试。

CodeGraph开发前query plan_prod_source_units/impact iter_prod_weekly_batches，开发后sync、impact verified_empty_inventory_intervals/build_weekly_partition_candidates；补审当前source、planner、capture、candidate、promote和治理消费者。影响仅独立orchestrator的候选边界验证，未改变子系统依赖、Prod业务契约或前端/API行为。LLD §26已同步硬口径与配置/预算来源；16MiB为冻结证据格式读取上限，无env/数据库/运营覆盖入口。

## 待确认后继续

[AGENTS.local.md](/Users/congming/github/goldenshare/AGENTS.local.md)明确“远程DB只能通过脚本”，但LLD §6.2/M2捕获器要求readonly resource直连、同连接named cursor。已向管理员请求选择：建议继续保留psql-remote.sh唯一入口，实现同只读快照内的有界CSV流，再复用现有capture/receipt/candidate/promote；或明确给予本次两张表的只读Resource直连窄例外。未确认前不修改该捕获合同或正式执行。

确认后：同步原LLD和必要代码/正反测试 → 试点真实运行、取消/续跑、业务字段读回对账 → 两源分批全量 → 聚合源/目标计数、schema/key/hash和source delta audit。文件未通过不得进入M7事件补录；M6备用源、M7事件、M9自动更新仍不包含在本次M5范围。
