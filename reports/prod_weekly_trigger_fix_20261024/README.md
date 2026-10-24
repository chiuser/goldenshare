# Prod周线触发来源修复验收

2026-10-24。本地修复与验证完成，管理员已授权提交；未推送或发布，生产部署由管理员负责。生产调度恢复尚未验收，22/23历史分钟数据未补跑。

## 修复范围

按管理员追加要求只纠正周线进入执行计划的来源，其他数据集保持原行为。

三个代码文件：`src/ops/services/dataset_action_request_adapter.py`、`src/ops/services/task_run_service.py`、`src/ops/runtime/task_run_dispatcher.py`。只有现有周线合同DATASET_KEY且Ops来源为scheduled，才转换为foundation的schedule。创建冻结、preflight及worker构造请求共用这一函数；TaskRun仍保存scheduled，冻结合同和原自动恢复意图仍是schedule/scheduled_week。

没有修改公共调度器、异常处理、CLI循环、规则配置、DatasetDefinition、foundation实现、业务事务、分页、对象集合、前端或其他来源消费者。曾准备的公共调度异常隔离已按管理员要求撤回，不在补丁中。

## 证据

- Prod规则14只读核验：cron=`4 22 * * *`，策略latest_completed_calendar_week，时间point且无固定日期；与回归测试一致。
- 原缺陷重现：测试保持真实scheduler/command/resolver/周线校验，只把交接还原为之前的原值透传，确实报“周线触发来源无效”。修复后同一真实隔离链通过。
- 15项新增测试：自动创建/实际resolver/worker请求/preflight、原错误重现、非法来源拒绝、自动任务重试保持执行token和原意图、其他93个数据集六种来源的558个输入组合保持原值。worker验证到构造请求和真实执行计划，不声称进行了网络下载或正式业务发布。
- 最终相关回归398项全部通过，64.90秒；其中新15项，原383项。覆盖原周线P1/P2/basis/bootstrap、Ops runtime、schedule/probe API和子系统依赖。3条框架弃用警告，不是本次错误。没有安装或升级依赖。
- Ruff通过、py_compile通过、docs完整性检查通过、git diff --check通过。
- CodeGraph explore/impact覆盖command、dispatcher、resolver及周线关联符号；最终sync/status为up to date，4349文件。API/前端标签及新闻任务按当前代码核对，不改契约；没有新增跨层依赖。
- 公共调度器、CLI循环和foundation目录的本次git diff为0。

## 读写和执行边界

真实数据库只读ops.schedule的id=14，显式字段，10秒超时，1行输出；使用规定的psql-remote脚本。测试仅隔离SQLite小样本、未调用外部源。没有Prod/DG数据写入、任务触发、服务重启、安装、迁移或seed。

原方案/LLD已同步，新步骤详见`docs/ops/ops-scheduler-failure-recovery-plan-and-low-level-design-v1.md`。`code-only.patch`仅含3个代码文件，`code-sha256.json`冻结文件摘要；其他文件为验收证据。

## 发布前剩余事项

仓库正式发版流程要求明确推送/发布授权及已提交SHA，禁止直接覆盖远端未提交源码。当前本地HEAD d77a06cb33956af5657b96f19fae61822feffc8c 与本次先前核验Prod HEAD efa55fff33b77cbc020a00be77ba75945a6c4736不同，之间存在其他提交；两处修改的原代码在这两个HEAD间没有差异，但不能因此把全部分支提交视为本次发布范围。

默认部署脚本还包含依赖安装、迁移、seed和多服务重启，不能未经额外授权顺带执行。应先确认只包含本修复的发布方式、提交范围和实际服务范围，检查在途任务，按批准范围发布。发布后只读核验scheduler稳定、旧周线到期点推进和新任务；可能仍遇到真实上游或历史批次问题，未核验前不宣称线上已经恢复。恢复不会自动补齐22/23行情。
