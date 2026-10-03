# 周线／月线审计报告清理记录

日期：2026-10-03，Asia/Shanghai。按管理员要求，仅清理此前审计生成的冗余或已被后续结果替代的 reports 文件。

共删除 8 个文件、9,301,791 字节。这些文件删除前均未被 Git 跟踪，因此本次以本记录保留清理范围；不是正式行情数据删除。

| 已删除文件 | 依据与保留证据 |
|---|---|
| `stock_month_backfill_task_status_20261002.csv` | 32 行及全部字段已包含于 `stock_month_backfill_submitted_tasks_20261002.csv`，逐项比较无差异。 |
| `stock_month_listed_backfill_tasks_20261002.csv` | 32 行及全部字段已包含于上述合并提交记录，逐项比较无差异。 |
| `stock_week_300114_backfill_status_20261002.csv` | 118 行及全部字段已包含于 `stock_week_300114_submitted_tasks_20261002.csv`，逐项比较无差异。 |
| `stock_week_300114_backfill_tasks_20261002.csv` | 118 行及全部字段已包含于上述合并提交记录，逐项比较无差异。 |
| `stock_week_full_reaudit_gap_ranges_20261002.csv` | 23,146 组记录可由 `stock_week_full_reaudit_gap_keys_20261002.csv` 按 layer、ts_code 无损聚合重建；日期集合、数量、首尾日期、名称和上市状态均核对一致。 |
| `stock_week_month_prod_gap_detail_20261002.csv` | 早期 2026 年缺口候选已被补齐后的月线验收和周线全历史复核替代；保留原整体评估及最终物理验收。 |
| `stock_week_month_prod_gap_manual_tasks_20261002.csv` | 早期手动补齐建议已过时；保留实际提交记录与最终验收，最新决定不再在 Prod 回补剩余历史周线。 |
| `stock_week_prod_reaudit_20261002_2033.csv` | 152 行预期、匹配、缺失数量与最终 `stock_week_full_reaudit_coverage_20261002.csv` 对应键全部一致。 |

同步更新 `stock_month_backfill_submission_20261002.md`、`stock_week_backfill_assessment_submission_20261002.md`、`stock_period_full_audit_2010_2026_20261002.md`、`stock_week_completed_full_reaudit_20261002.md` 的证据引用。历史时点结论保留，不改写为当前状态。

最终验收、源响应、独有历史事实、DG 方案所需历史剩余清单均保留。本次不改代码、配置、数据库、Lake、Dagster instance 或方案／LLD。

验证：删除前核验内容与替代关系；删除时校验 8 个文件 SHA-256，确认未在审查期间变化；删除后检索确认文档及代码无残留引用。文档完整性及 Git 空白检查通过。原本未跟踪的其它证据继续保留在工作区，本次不把整批审计文件扩大纳入提交。
