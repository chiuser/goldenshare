# 修数遗留临时文件清理（2026-10-30）

状态：已完成。3个临时副本已删除，五个测试目录树内83个空目录已清理，既有归档逐份校验未变。

## 依据、范围与保留项

管理员要求检查之前修数产生的现已废弃文件，有则清理。本次对应[22日恢复报告的收尾记录](../datasets_recovery_20261022_20261024/README.md#51-sensor待办及临时文件收尾完成2026-10-27)及[104911a4队列处理记录](queue_release_104911a4_20261028/result.json)，仅处理它们遗留的重复临时工具与空测试目录。既有业务方案、代码、正式数据及恢复规则不变。

现行writer.lock、publication/receipt/checkpoint、周期交付manifest和冻结输入仍有作用；运行日志和原审计/测试证据保留。20个旧DuckDB工作文件已按原清单删除，当前共享目录没有工作文件，不重复处理。29日审计JSON是原基线，继续保留。

## 本次清单与操作细节（LLD）

删除三个 `/private/tmp` 临时副本，共6,431字节；对应本报告 `queue_release_104911a4_20261028/` 中的同名`.py.txt`或`.graphql`归档。执行前已逐字节核对一致，并确认现行orchestrator源码无引用：

- `dg_queue_104911a4_readonly_20261028.py`
- `dg_run_104911a4_readonly_20261028.py`
- `dg_close_lost_104911a4_20261028.graphql`

清理下列五个 `/private/tmp` 测试目录树，已核实只剩83个空目录，普通文件与符号链接均为0：

- `dg_index_daily_raw_sample_dvhazron`
- `dg_index_daily_staging_sample_yduwf8wg`
- `dg_minute_staging_sample_6n7v28mx`
- `dg_qfq_staging_real_sample_sq68mnk8`
- `etf-mins-recovery-20261024`

先复核上述三个临时副本及归档的大小和SHA-256；全部通过才逐个unlink。目录仅在递归元信息确认无普通文件、符号链接后，由最深层起逐个rmdir；不用递归强删。任一对象与清单不符即停止，保留未处理对象，不扩大删除范围；既有归档不改写，必要时从原归档追溯，不自动重建临时执行入口。

本次只有文件元信息及三个小工具内容读取，读写预算各64KiB、额外空间64KiB，含核对和最终记录；不访问正式服务、不读行情、不执行GraphQL文件内容、不调用job/sensor、不删除正式Lake/staging或其他任务文件。结果JSON记录精确路径、归档路径、摘要、删除结果及空目录数量，最后核所有目标不存在、原归档仍一致。

## 执行结果

[逐项结果](temporary_cleanup_20261030.json)：删除3份重复工具副本，共6,431字节，清理5个测试目录树内83个空目录；所有目标均已核不存在，三个既有归档的SHA-256保持一致。未执行任何正式查询、任务或状态写入，未改动其他文件。
