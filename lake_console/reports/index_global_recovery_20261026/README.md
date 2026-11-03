# 国际指数10月4日修复结果

<a id="report-attachment-cleanup-20261103"></a>

> 2026-11-03附件清理：相关恢复请求/响应、轮询、旧脚本和测试输出等过程附件已删除；下文旧附件清单、数量、命令和裸路径保留为当时记录，不表示文件仍存在，也不要求重跑任务。保留说明及最终结果，具体范围见[清理LLD20.17](../../docs/design/dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#2017-其余恢复过程附件的清理2026-11-03)。


目标日期为**2026-10-04**。已按当时批准的方案与LLD完成写入修正、隔离验证、单日原job重执行和sensor恢复，没有扩成全历史补数。

| 项目 | 结果 |
| --- | --- |
| 代码修正 | Raw/Silver候选移到正式staging；失败留存；目标锁、冻结输入、逐文件checkpoint及原子提升/继续 |
| 完整隔离回归 | 131项通过；随后Silver耗时统计定向14项通过 |
| 静态检查 | 改动文件ruff、工程致命错误基线、CodeGraph sync/status通过 |
| 正式job | `raw_index_global_update_job`，run `0465cb4b-0af1-4d6e-81d5-ed4c75c5d6f3`，SUCCESS，5.092秒 |
| 原检查 | 通过，target绑定本次物化；旧失败记录保留 |
| 源结果 | 1请求、0重试、0行；没有新增行情 |
| 正式文件 | Raw 278B、Silver 285B，五字段身份及SHA均未变，替换0 |
| Silver | 同日0行文件和schema仍正确，按方案跳过，不重复执行 |
| 维护恢复 | 五个原RUNNING的writer sensor均恢复；未reset cursor或启用股票sensor |
| 范围外 | 无全局数据审计、Bootstrap、Prod、安装、提交或推送 |

截至2026-10-26 17:17:42北京时间，23—25日最终Americas及Silver成功；26日Asia第二阶段已成功，但该run发生于维护前16:20，不属于新代码非空真实验收。26日18:30、27日00:45/05:30等后续阶段未全部到时，不能报告全天齐备。未创建未来监控任务。

此次新代码真实执行覆盖空源reuse；非空、NULL、候选变化和中断继续使用真实临时文件隔离验证，没有额外真实样本或性能试验。

关键证据：

- [原审计（附件已清理）](README.md#report-attachment-cleanup-20261103)
- [暂停门禁（附件已清理）](README.md#report-attachment-cleanup-20261103)
- [业务函数未变对账（附件已清理）](README.md#report-attachment-cleanup-20261103)
- [开发验证汇总（附件已清理）](README.md#report-attachment-cleanup-20261103)及[完整隔离日志（附件已清理）](README.md#report-attachment-cleanup-20261103)
- [代码加载（附件已清理）](README.md#report-attachment-cleanup-20261103)
- [启动依据（附件已清理）](README.md#report-attachment-cleanup-20261103)、[唯一提交记录（附件已清理）](README.md#report-attachment-cleanup-20261103)、[原生run事件（附件已清理）](README.md#report-attachment-cleanup-20261103)
- [单日验收](raw-run-verified.json)
- [sensor恢复响应（附件已清理）](README.md#report-attachment-cleanup-20261103)及[定向最终状态](final-state-readback.json)
- [清理记录（附件已清理）](README.md#report-attachment-cleanup-20261103)

4个本轮独占pytest basetemp目录已清理；4份临时GraphQL请求经摘要核对后归档到`requests/`并移除临时副本。子任务未发现其测试前缀残留；共享目录及其它任务文件未删。正式数据、本次staging中的operation/冻结输入及失败历史保留。
