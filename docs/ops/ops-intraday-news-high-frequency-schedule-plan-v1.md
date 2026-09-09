# Ops 新闻日内高频自动任务方案 v1

状态：已实现并结案（2026-09-01 用户确认）；实际自动任务配置属于运营日常，不再作为本文开放事项。

创建日期：2026-05-14；现行口径核对：2026-09-10。

适用范围：`news` 新闻快讯、`major_news` 新闻通讯的自动采集，不包含新闻关联计算。

本文保留新闻专项的配置、日期传导与回归边界，已完成的开发步骤从 Git 历史追溯。通用规则见[自动任务日期策略](/Users/congming/github/goldenshare/docs/ops/ops-schedule-calendar-policy-plan-v1.md)，字段见 [API capability](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md#automation-capability-schema)。本文不证明线上配置已启用或持续运行。

## 1. 现行配置

| 项目 | 新闻专项口径 |
| --- | --- |
| 维护对象 | `target_type=dataset_action`，`target_key=news.maintain` 或 `major_news.maintain` |
| 调度方式 | `schedule_type=cron`，重复方式为“每 N 分钟” |
| 间隔 | 默认 3 分钟；低于 3 分钟拒绝保存 |
| cron | 分钟步长表达式 `*/N * * * *`；3 分钟示例为 `*/3 * * * *` |
| 日期策略 | `calendar_policy=trigger_day_point` |
| 时间意图 | `params_json.time_input.mode=point`，不携带固定日期或范围 |
| 时区 | 使用 schedule 的时区；北京时间配置为 `Asia/Shanghai` |

能力由 DatasetDefinition 动作声明，经 capability 提供给自动任务页，并由后端校验。本文限定两个新闻数据集，不构成全仓白名单：其他已声明能力的数据集可以复用 `trigger_day_point`；未声明能力的对象不能使用。

## 2. 日期与读写链路

1. Scheduler 将**计划触发时间 `scheduled_at`**传给 TaskRun；TaskRun 按该时间与 schedule 时区计算自然日，生成 `time_input={mode: point, trade_date: D}`。不能改用 worker 实际开始日期，延迟跨日执行时仍取原计划日。
2. `DatasetActionResolver` 将意图归一化为执行计划；新闻 unit planner 按日期和 `src` 来源扇出。
3. Request builder 将锚点日期 `D` 转成源参数 `start_date=D 00:00:00`、`end_date=D 23:59:59`，并传入 `src`。当前 Definition 的分页大小为 `news=1500`、`major_news=400`。
4. 正式 ingestion 链路按 `row_key_hash` 幂等 upsert 到对应 `raw_tushare` 表，通过 `core_serving_light` 视图交付；不是源接口直接写库，也不是 Ops 生成源接口参数。

证据入口：

- [新闻 Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/news.py)：动作能力、来源扇出、分页及写入声明。
- [Schedule 校验](/Users/congming/github/goldenshare/src/ops/services/operations_schedule_service.py)：`_validate_intraday_interval_cron` 与日期策略校验。
- [TaskRun 日期生成](/Users/congming/github/goldenshare/src/ops/services/task_run_service.py)：`TRIGGER_DAY_POINT_POLICY` 分支与 `_natural_day_for_schedule`。
- [Unit planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py) 与 [request builders](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)：新闻 unit 与 `_news_params` / `_major_news_params`。

## 3. 能力边界与风险

- 本方案重复请求计划日的全日窗口，不是“最近 N 分钟”滚动窗口，不引入 cursor/checkpoint 或自动历史补录。
- 全日重复读取配合幂等写入可避免重复落行，**不保证新闻绝不遗漏**。例如源端跨日迟到、过去日期的数据后续才出现，不能仅靠下一日的 point 任务覆盖。
- 3 分钟下限不是账号配额保障；实际请求量还取决于来源数、分页数和其他任务，运营配置须考虑共同额度。
- 前端只保存维护与调度意图，不自行生成源接口 `start_date/end_date`；固定日期与触发日策略不能混用。
- 不从本专项结案推导其他自动任务专项或生产迁移已验收，也不重新打开已转为运营日常的新闻配置事项。

## 4. 回归重点与结案记录

后续修改相关代码时应核验：

| 范围 | 需要保持的行为 | 现有证据入口 |
| --- | --- | --- |
| 自动任务配置 | 新闻默认 3 分钟；小于 3 分钟、固定日期混用及未声明能力的组合被拒绝 | [Schedule API 测试](/Users/congming/github/goldenshare/tests/web/test_ops_schedule_api.py)、[自动化 capability 测试](/Users/congming/github/goldenshare/tests/test_ops_automation_capability.py) |
| 日期传导 | 按计划日与 schedule 时区生成 point，不因延迟执行改日 | [Runtime 测试](/Users/congming/github/goldenshare/tests/web/test_ops_runtime.py)中的 `test_scheduler_trigger_day_point_policy_uses_due_schedule_day_for_news_task_run` |
| 请求与写入 | 来源扇出、全日窗口、现行分页和幂等键保持一致 | 第 2 节 Definition、planner 与 builder |
| 页面 | 按 capability 展示重复方式与固定日期输入，不按新闻名称维护全局白名单 | [自动任务页测试](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-auto-tab.test.tsx) |

历史实施记录：后端策略、前端入口及文档收口已完成；2026-09-01 用户确认结案，实际配置和运行状态转为运营日常。本专项没有遗留待决策或待验收事项。上表是后续代码变更的回归定位，不代表本次文档精简重新运行过业务测试或生产任务。
