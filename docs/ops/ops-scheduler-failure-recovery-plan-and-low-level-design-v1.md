# Prod周线执行计划触发来源修复方案与LLD

日期：2026-10-24。状态：本地修复与测试完成，提交已获授权，未发布。管理员要求立即处理，并明确不能影响其他数据集，只纠正周线执行计划。

## 1. 目标、依据与范围

Prod股票分钟线规则15/schedule25启用，22、23日探测日志与更新任务均0条。21日17:15探测成功，任务16642随后成功；21日22:04:25起scheduler处理schedule14股票复权周线时报“周线触发来源无效”，next_run_at停在21日22:04，24日23:09仍反复重启。事故证据见`/private/tmp/prod_stk_mins_trigger_audit_20261024.md`。

Ops持久化、查询、前端筛选、新闻冻结及readiness查重使用scheduled；foundation周线冻结及自动恢复使用schedule。错误发生在周线进入执行计划的交接，不是要把全系统单词替换。保留两工程现有合同，在Ops周线入口明确转换；不是让周线同时接受两个值。

CodeGraph explore覆盖command/dispatcher/resolver，impact覆盖周线冻结及34个关联符号；核对API、前端、新闻消费者。根因已读取Prod部署代码确认。仅修改周线请求适配、command冻结/preflight和dispatcher构造请求。DatasetDefinition、DatasetExecutionPlan、源参数、分页、业务事务/恢复均不变；不新增配置、API、迁移或worker。

## 2. 硬约束与实现

| 约束 | 代码位置 | 验收 |
|---|---|---|
| Ops来源scheduled与周线内部schedule各保持现行合同 | `src/ops/services/dataset_action_request_adapter.py`唯一转换，只在对象等于现有周线合同DATASET_KEY且来源scheduled时返回schedule | 真实周线Definition正例；非周线scheduled保持；manual/retry/probe/非法来源均不兜底 |
| 创建、预检查与执行必须一致 | TaskRunCommandService冻结/preflight；TaskRunDispatcher构造请求共用转换 | 实际scheduler创建TaskRun、真实resolver/冻结、worker请求和恢复链验证，不mock触发来源校验 |
| 不影响其他数据集和公共调度 | 不修改OperationsScheduleService、OperationsScheduler、CLI循环、规则配置、通用重试/异常处理、来源标签/筛选 | 原文件diff为0；普通数据集和新闻任务原路径回归；其他数据集请求source保持原值 |
| 不修改原周线意图及业务安全检查 | Foundation源码、冻结合同/预算/幂等/事务不改 | 自动scheduled_week、非法来源拒绝、原冻结执行token不变、原自动续跑/手动恢复测试 |
| 不借修复实施历史补数 | 不创建22/23任务、不调用Prod scheduler tick/探测evaluator、不改业务数据或规则 | 生产仅有界只读核验；历史补齐单独记录未执行 |

## 3. LLD与读写边界

转换函数接收dataset_key与trigger_source。直接比较现有周线合同DATASET_KEY与scheduled；仅两者同时命中时返回schedule。其他情况原样返回，不为其他数据集新增Definition查询或校验。三处真实交接调用同一函数。TaskRun仍保存scheduled，执行计划和冻结合同仍保存schedule。当前消费其他source的代码不变，不新增foundation对ops依赖。

本步没有新增持久化，没有源请求、行情扫描、业务写入或长任务实现变更。原已提交unit和不可变交接记录仍是恢复事实源。自动续跑传原execution_context，resolver继续还原原意图/token，不能生成新合同绕过未完成批次。非法源仍按原合同拒绝；本轮不加入吞异常、失败当成功、推进失败日期等通用处理。开发中曾准备的公共调度异常隔离已按管理员收窄要求撤下，不属于交付。

## 4. 性能、失败、继续与验收预算

转换O(1)，仅比较两个字符串，无Definition查询、数据库或网络开销。测试仅隔离SQLite和字面小样本；真实模型/Definition与真实resolver，不调用外部源。总目标≤3分钟；缺依赖不安装，超过预算查慢项。生产只读经过psql-remote脚本，ops.schedule14及必要Ops规则/任务≤30行、statement_timeout≤30秒；不调用全市场生产resolver或全局行情/因子查询。失败时保留测试/日志证据，未发布则线上行为未变。

发布后继续和最终验收仅各一次有界schedule14/新任务查询、≤100行服务日志，观察至少两个30秒循环。不得以隔离SQLite测试宣称生产调度已恢复；周末不强制触发源探测。22/23数据不会因恢复自动补齐。

## 5. 步骤与验收

1. 同步本方案和原周线方案/LLD、自动任务文档；重新审核缩小后的影响面。
2. 增加真实自动来源scheduled回归，先证明修复前因本次来源错误失败； fixture必须使用Prod真实规则字段和当前schema。
3. 实施三处周线交接转换；测试正常自动周计划、preflight、worker冻结恢复一致；非法来源仍拒绝；其他数据集输入保持；原周线/runtime/schedule回归及架构、diff、文档检查。
4. 准备受限发布的准确文件和测试报告。正式流程要求明确推送/发布授权、已提交SHA，禁止直接覆盖远端未提交代码；无明确授权时将具体发布包交管理员确认，不执行发布。默认部署脚本包含安装/迁移/seed，不因本轮修复自动获准；不得擅自另造部署方式。
5. 获准发布后核实远端SHA和工作区，按批准范围部署；只读检查服务不再因来源错误退出、schedule14推进，记录新任务状态与其他实际阻塞。未完成源下载和缺失数据不能标成完成。

## 6. 计划对账与执行记录

待补本次测试、真实核验及发布状态。必须分别记录本地代码完成、生产部署、调度恢复和历史数据补齐。

### 2026-10-24 本地执行与计划对账

已仅实施3个代码文件，公共调度异常隔离撤下。最终398项相关测试通过（64.90秒），其中新增15项覆盖实际自动创建/worker请求/preflight/真实resolver、非法来源拒绝、原错误重现及自动重试保留原合同；其余93个数据集六种来源558个输入组合保持原值。公共调度、CLI、foundation实现的本次diff为0。Ruff、py_compile、文档检查和diff检查通过；CodeGraph sync/status最新。

真实核验只读规则14的1行配置：cron为`4 22 * * *`，latest_completed_calendar_week、point无固定日期；已纠正测试最初按名称猜为每周cron的错误假设。真实模型和Definition没有mock；仅以小型SQLite数据模拟已闭合bootstrap及一周恒定因子，不把测试当作Prod下载/发布验收。全部证据及3文件补丁见[本地验收报告](/Users/congming/github/goldenshare/reports/prod_weekly_trigger_fix_20261024/README.md)。

计划2/3本地完成；4/5未发布。当前工作区包含其他任务修改，README索引也有已有修改，提交需只取本次路径及索引新增一行。Prod先前核验HEAD efa55fff与本地HEAD d77a06cb不同，之间含其他提交，不能直接将全分支推进视为本次发布。正式流程要求明确推送/发布授权及提交SHA，且默认脚本会安装依赖、迁移、seed、重启多服务；本轮未执行这些操作，也未创建历史补数任务。需确认精确发布方式及范围后才可验收生产恢复。

### 提交授权

管理员明确“提交吧，我会来部署”。本轮只在dev-interface提交本次周线修复、测试、方案/LLD及验收记录；不推送、不部署、不重启或触发任务。docs/README.md只提交本次索引新增一行，其他工作区修改保留。生产恢复与22/23行情补齐仍未验收。
