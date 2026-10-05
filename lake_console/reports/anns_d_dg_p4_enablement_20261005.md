# 公告调度启用与 DG 停机交付（2026-10-05）

用户明确要求启用本专项所需能力，停止DG进程，后续自行启动。依据原方案每日08:00、Asia/Shanghai、最近七个已结束自然日更新合同，本轮只启用raw_anns_d_update_schedule，关联raw_anns_d_update_job。

[结构化读回证据](anns_d_dg_p4_enablement_20261005.json)。

正式实例为/Users/congming/.goldenshare/dagster_home。检查dagster schedule start --help及当前Dagster启动状态实现后，为确保不初始化数据库，执行/private/tmp/anns-d-enable-schedule-20261005.py，使用现有PostgresScheduleStorage(should_autocreate_tables=False)存储API，按现有orchestrator / __repository__身份写入RUNNING和启动时间。未执行DDL、任务或Lake/Prod写入；独立只读连接确认状态持久化。其余105条instigator状态逐条保持不变；代码default_status仍STOPPED，由实例内显式RUNNING状态覆盖。

操作前后本机DG webserver、daemon、code location均未运行，无需发送停止信号。本轮不启动服务，留待用户手工启动同一实例；应同时启动daemon，才会执行调度。停机期间不执行更新；长时间停机超过七日时需显式补齐窗口之外缺口。

另有独立stock_monthly_history_cli正在执行其它任务历史写湖，不是DG服务进程，本轮未中断。没有安装依赖或变更源码、配置与依赖矩阵。

本轮完成用户指定的启用与服务停机交付。正式日job真实运行/取消恢复验收仍未执行，不能将调度启用当成该项验收通过，P4完整验收尚未全部退出。历史文件、事件、衔接和CLI取消续跑证据沿用既有报告。
