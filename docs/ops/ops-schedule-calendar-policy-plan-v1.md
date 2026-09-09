# Ops 自动任务日期策略 v1

状态：当前实现说明；2026-09-09 按代码校准并合并历次已完成方案。
适用范围：`ops.schedule` 的自动任务日期意图；不替代手动维护、独立日期完整性审计或业务写入契约。

## 1. 职责与事实源

日期策略解决两件事：**什么时候触发、这次维护哪个业务日期或窗口**。它已经参与预览、下次运行时间和 TaskRun 创建，不再是只保存不执行的字段。

| 内容 | 唯一维护入口 |
| --- | --- |
| 策略含义、日期生成与边界 | 本文 |
| 目标允许的触发方式、探测与持久化约束 | [自动任务能力契约](/Users/congming/github/goldenshare/docs/ops/ops-automation-capability-contract-plan-v1.md) |
| 请求及 Catalog 字段 | [Ops API §3、§11、§12.1](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md#automation-capability-schema) |
| 数据集日期模型与动作声明 | `src/foundation/datasets/**` 的 `DatasetDefinition` |
| 自动日期能力解析 | `src/ops/services/dataset_schedule_time_policy_resolver.py` |

`schedule_type` 表达 cron/once，`timezone` 决定本地日期，`calendar_policy` 表达日期策略，`params_json` 保存目标意图。普通 schedule 或 fallback 没有日期策略时沿用 cron/once；**纯 probe 是例外**：其 cron/next-run 必须为空，不走定时预览，详见能力契约。

## 2. 能力如何确定

`DatasetScheduleTimePolicyResolver.resolve()` 先检查动作是否可排程：

1. 动作显式声明 `schedule_time_policy` 时，以该声明为先，包括策略、允许的 schedule types、重复方式、生成字段及策略参数。
2. 未显式声明时，才从 `date_model` 和动作支持的时间模式派生下表前四类策略。
3. 没有匹配规则则不提供日期策略，不能由页面按数据集名称补出一套规则。

Catalog 的 `automation_capability.calendar_policy_rules` 是前端消费入口。表单与保存校验使用同一后端能力；日期策略不能覆盖数据集自身的输入语义，也不能把“可按日期输入”改成“每天必须有数据”。

<a id="calendar-policies"></a>

## 3. 当前七种策略

下表的“触发日”均指**计划触发时间转为 schedule 时区后的自然日**，不是 worker 实际开始日期。

| calendar_policy | 定时触发计算 | TaskRun 时间意图 | 能力来源 |
| --- | --- | --- | --- |
| `monthly_last_day` | 自然月最后一天，cron 只取时分 | point，`trade_date=月末自然日` | 未显式声明时由 `bucket_rule=month_last_calendar_day` 派生 |
| `monthly_last_trading_day` | 当月最后开市日，cron 只取时分 | point，`trade_date=当月最后开市日` | 未显式声明时由 `bucket_rule=month_last_open_day` 派生 |
| `monthly_window_current_month` | 自然月最后一天，cron 只取时分 | range，`start_month=end_month=计划触发月份 YYYYMM` | 未显式声明时由 `month_window + month_window_has_data + start_end_month_window` 派生 |
| `trigger_day_single_range` | 普通 cron | range，`start_date=end_date=触发日` | 未显式声明时，由 natural_day、ann_date_or_start_end 且仅支持 range 的动作派生 |
| `trigger_day_point` | 普通 cron；重复方式受动作声明限制 | point；将触发日写入声明的 `trade_date` 或 `ann_date` | 动作显式声明 |
| `latest_completed_calendar_quarter` | 按声明支持 cron/once | point，`trade_date=严格早于触发日的最近自然季末` | 动作显式声明 |
| `since_last_success_day_range` | 普通 cron；重复方式受动作声明限制 | range，从初始起日/上次成功窗口之后到触发日前一天 | 动作显式声明；须配置初始起日 |

前三类派生规则仅支持 cron/月度重复；第四类派生规则支持 cron 的每日、每周、每月重复。显式声明的策略不可沿用这组默认限制，须读取其自己的 `schedule_types/cron_repeat_modes`。

### 3.1 trigger_day_point 不等于新闻专用或日内专用

当前声明示例：

| 动作 | 允许的 cron 重复方式 | 生成字段 |
| --- | --- | --- |
| `news.maintain` / `major_news.maintain` | 仅 intraday_interval | `trade_date` |
| `fund_share.maintain` | daily / weekly / monthly / intraday_interval | `trade_date` |
| `fund_div.maintain` | daily / weekly / monthly | `ann_date`，同时标明 `date_field=ann_date` |

只有采用日内重复时才要求 `*/N * * * *` 且 `N >= 3`。不能对所有 `trigger_day_point` 强制分钟间隔，也不能一律生成 `trade_date`。新闻的当天全日窗口仍由新闻 request builder 生成，见[新闻专项](/Users/congming/github/goldenshare/docs/ops/ops-intraday-news-high-frequency-schedule-plan-v1.md)。

### 3.2 季末与成功窗口游标

- 季末策略选的是严格早于触发日的季末：6 月 30 日触发仍取 3 月 31 日，7 月 1 日才取 6 月 30 日。它不是“最近已发布报告期”的源站就绪判断。`fund_portfolio.maintain` 当前允许 cron/once，cron 仅 weekly/monthly。
- 成功窗口策略要求 `params_json.schedule_policy_params.initial_start_date`。终点为计划触发日前一天；起点为初始起日与成功窗口终点加一天的较晚者。
- 成功窗口从**同一 schedule_id、resource_key、action** 的成功 TaskRun 中取有效 `end_date` 的最大值；失败、取消或别的自动任务不能推进它。
- 起点晚于终点时，服务按已覆盖窗口跳过并推进调度，不创建空区间任务。TaskRun 成功窗口是续接依据，不等于独立证明业务数据完整。

## 4. 日期传导与校验

当前链路：

`Definition → 日期能力 resolver → Catalog/表单 → Schedule 保存校验 → 定时计算 → TaskRun 时间意图 → DatasetActionResolver 执行计划 → request builder 源参数`

- `OperationsScheduleService` 负责创建/更新校验、恢复与下次运行时间。`schedule_planner.py` 处理普通 cron 和自然月末；最后交易日由 service 的交易日历查询分支处理，不能仅检查 planner 的枚举就判为未支持。
- 月末计算使用单一小时、分钟，不支持 cron 的 `L/LW/5L` 扩展；从 after 之后选下一次时间，按时区换算并以 UTC 保存。
- `TaskRunCommandService` 使用传入的 `scheduled_at` 生成日期。到期扫描正常传入原 `next_run_at`；不能用实际执行时间改写业务月份。
- 例如 4 月 30 日 19:00 的月窗口任务晚到 5 月 1 日执行，仍生成 `start_month=end_month=202604`。月份首尾展开由 `DatasetActionResolver` 完成，不由前端生成。
- 自动日期规则声明 `explicit_time_input=forbidden` 时，保存必须拒绝与固定日期/窗口混用；检查包括顶层与 `time_input` 中已声明的日期字段。允许只带 mode 占位及合法业务 filters。
- Catalog 的 `policy_parameters` 声明策略参数，保存值位于 `params_json.schedule_policy_params`；它与固定维护时间是两回事，只接受该规则声明的字段、类型及必填项，无策略或无声明时不可任意夹带。
- 创建/更新仍须核验目标、触发方式、日期策略及重复方式的组合。预览请求没有 `target_type/target_key`，只计算时间；**预览成功不代表目标可保存或业务数据已就绪**。

本章不变更手动任务、业务表或业务事务。Ops 调度/观测状态写入不得阻塞、回滚或污染业务数据提交。

## 5. 代码与回归入口

| 检查点 | 当前入口 |
| --- | --- |
| 定义优先级、策略与模式 | `dataset_schedule_time_policy_resolver.py`；`tests/test_ops_automation_capability.py` |
| 月末、闰年、时区、after 边界与普通 cron | `schedule_planner.py`；`tests/test_ops_schedule_planner.py` |
| 策略匹配、固定时间拒绝、参数与最小间隔 | `operations_schedule_service.py`；`tests/web/test_ops_schedule_api.py` |
| 计划日期、跨月晚跑、季末、成功窗口 | `task_run_service.py`；`tests/web/test_ops_runtime.py` 及 Schedule API 测试 |
| 能力驱动重复选项、保存与预览 | `frontend/src/pages/ops-v21-task-auto-tab.tsx` 及同名测试 |

上述 service 文件均位于 `src/ops/services/`。后续改动须保留正反例：不匹配目标、禁止的重复方式、固定日期混用、错误策略参数、非本任务成功窗口，以及纯 probe 不参与定时计算。本轮仅核验代码/测试定义并修改文档，不宣称重新执行了这些运行测试或生产任务。

## 6. 历史收口与未实现方向

原第一至第五期的实现步骤已收口为本文当前规则；不再把已支持的最后交易日、窗口或触发日策略列成待开发。原远程验证里程碑只是当时的记录，本次未重新核实生产配置。

旧方案提到的 `fixed_day_of_month`、`weekly_friday`、`weekly_last_trading_day` 不在当前策略枚举中；固定日号和周五触发本身可由普通 cron 表达，不据此新增策略。月份键生成、每周最后交易日、“次月维护上月窗口”仍需有明确需求时另行评审，不是本轮待办，也不得偷换当前月窗口含义。
