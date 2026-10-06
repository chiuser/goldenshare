# M5 周线 Prod bootstrap 执行验收

2026-10-07纠偏说明：本报告保留历史结论；搬运/审计中间数据文件已按管理员要求清理，不再是正式检查或调度依赖。现行口径为 bootstrap 完整对账一次即结束、日常只检查当前新增周期。详见[清理记录](stock_period_reports_cleanup_20261003.md#2026-10-07运行依赖纠偏及清理)。

当前状态：M5 两主源物理 bootstrap 和最终库存 delta 审计完成；Dagster 事件与更新机制尚未执行。

依据为管理员确认的脚本唯一数据库入口、周线 LLD §27 和接入模板 7A。先更新原 LLD 与总体方案，再替换 named cursor 传输；没有改 Prod/Tushare 字段合同、路径口径或子系统依赖。

## 改动与硬口径对账

| 要求 | 实现与证据 |
|---|---|
| 唯一 DB 入口 | `prod_db/stock_weekly.py` 只启动现有 psql-remote.sh，固定 .env.web.local；未改脚本或通用 Resource |
| 快照与全量业务列 | 单 unit repeatable-read/read-only、COUNT 与 COPY 同事务、ROLLBACK；13/21 显式字段、numeric 文本、NULL 标记 |
| 预算与性能 | WeeklyBudget/冻结 plan：300 代码、30000 行、CSV64MiB、control16KiB、45秒、单连接、DuckDB512MiB/2线程/2GiB staging spill；超限拒绝，不自动放宽 |
| columnar 捕获 | CSV 显式 VARCHAR 解析、计数匹配、DuckDB relation→10000行 chunks；复用精度/键/范围/COPY/读回校验，Prod 不经 DataFrame |
| 取消、续跑与证据 | 进程组终止/回收；SQL/CSV/control/chunks hash；完整 unit receipt 唯一完成事实，失败 attempt 保留，已完成不重取 |
| 边界 | 冻结空年 JSON 绑定真实库存 CSV，2009/2027 空窗口严格校验；不能把缺 receipt 当空源 |
| 候选和正式提升 | M3 年度集合合并/业务值差集、完整签名和目标指纹、同设备逐文件 replace/checkpoint/readback |
| 显式阶段入口 | 新 history CLI 默认只读 dry-run；执行要求显式冻结 plan+apply，year/audit/roots 不匹配拒绝，无 instance 操作 |

CodeGraph query/impact 覆盖捕获协调器、Prod adapter 和调用方，代码搜索补齐测试、candidate、CLI 消费者；sync/status 已核验。受保护治理启动器因空年证据 helper 引入纯 planner，仅增加该单文件读取白名单，没有放宽网络/正式 Lake/凭证权限。

## 验证

- 定向周线及静态门禁 241 项通过；最终受影响的 Prod/history/CLI 29 项通过，补充了预算拒绝与取消前不启动进程的反例。默认 Ruff、全 src/tests 致命错误基线、docs integrity、diff check 通过。
- 既有 OS 隔离启动器：治理 12 项、增量 checks 治理 6 项通过。初次嵌套 sandbox-exec 被环境拒绝；主机启动严格 OS 策略后定位并补齐纯 planner 白名单，再全部通过。
- 真实只读 COPY：两源各300代码、15450行，source/CSV/readback 一致，业务列双向 EXCEPT ALL=0；见 传输审计（历史中间文件已清理）。
- 实际 staging 试点：两源各3units/41932行；取消后复用已封存 unit，重复执行源调用0；2025候选各15450行/52文件、值差集0。临时目标跨设备提升被正确拒绝，不放宽同设备要求；见 试点审计（历史中间文件已清理）。

## 执行与恢复

工作目录 `/Users/congming/github/goldenshare/lake_console/orchestrator`；实际命令 `.venv/bin/python -B /private/tmp/stock_week_m5_copy_full.py`。固定计划为未复权 `21eb70c1b4ac42d4f5a303b8a59087a16ba1beee1b4091b2619016944d4cf85c`、复权 `bf673c3b60473a8430ea2bfb5a2ada07f69130975a2116f1808d99f438e8f6ec`。每源212units，全量分别2895784/2891262行，2010–2026年，预期各857个正式周文件。

capture/candidate 只写 `/Volumes/datasource/data_lake_staging`，正式目标为 `/Volumes/datasource/data_lake/raw/tushare/stk_period_bar_week` 和 `stk_period_bar_adj_week`。Prod 始终只读；不使用 DAGSTER_HOME，不写 Dagster instance、events、动态分区、sensor/schedule。失败保留 capture/assembly/逐文件 checkpoint；同一计划重新执行只续跑，不能删除目标或改预算来强行恢复。

逐 unit/年度持久化实际进度、耗时、行数和文件数，见 全量执行证据（历史中间文件已清理）。完成后补独立正式聚合/schema/重复键/文件集/文件指纹审计，以及通过原脚本重新读取 Prod 库存的差异审计。不同 unit 快照不等于同一瞬间全库备份；最终业务值一致性以已捕获快照为准，库存 delta 不替代之后同键数值修订的再捕获。

本轮修改未提交、未推送。下一阶段 M6 备用源、M7 事件补录、M9 更新机制尚未执行。

## 最终结果

| 来源 | 源/捕获/正式行数 | 正式文件 | 年度业务值差集 | 重复键 | code/year库存差异 |
|---|---:|---:|---:|---:|---:|
| 未复权 | 2895784 | 857 | 0 | 0 | 0 |
| 复权 | 2891262 | 857 | 0 | 0 | 0 |

所有正式文件指纹与已审计候选一致；Prod终态重新读取库存/源日期边界的差异0，见最终对账（历史中间文件已清理）。end_date NULL分别21495/16976行，其他业务列NULL为0；Raw原样保留。reject、同值去重、排除行0，没有把不完整数据按成功处理。

capture分别395.100/435.355秒；年度build/audit分别27.050/34.588秒，promote/readback分别14.302/18.521秒，最大unit导出4.312/4.325秒。正式字节分别89441602/157624274，合计约235.62MiB；全量CSV约780.14MiB。详细物理/耗时/NULL统计见测量（历史中间文件已清理）。

组合进程peak RSS=1781.453MiB，约1.74GiB。DuckDB512MiB是buffer预算，不能作为进程硬上限；下一阶段标准运行按既有CLI独立阶段/年度进程，并补过程RSS/peak spill测量。当前结束留存spill=0，峰值没有采样，未声称spill压力验收通过。此剩余性能测量不影响源→捕获→候选→正式业务值对账；不能据此宣称所有性能风险已消除。

M5完成后停在阶段边界：没有执行备用源补齐、事件补录、自动更新或Silver；修改尚未提交/推送。下一步按方案为M6，不把它附带在本次执行中。
