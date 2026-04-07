# 运维系统一期 Low Level Design

> 历史文档（归档）：本文件保留一期落地细节记录。当前目录与运行入口请以 [current-architecture-baseline.md](/Users/congming/github/goldenshare/docs/architecture/current-architecture-baseline.md) 为准。

## 1. 文档目标

本文档是 [ops-system-phase1.md](/Users/congming/github/goldenshare/docs/ops/ops-system-phase1.md) 的低层设计文档。

它回答的是“如何具体落地运维系统一期”，而不是“为什么要做运维系统”。

本文档重点覆盖：

- 一期的具体实现边界
- 控制面数据模型
- 运行时模型
- Web API 设计
- 页面结构与查询模型
- 权限设计
- 推荐实施顺序

实现时应同时遵守：

- [design-principles.md](/Users/congming/github/goldenshare/docs/architecture/design-principles.md)
- [ops-system-phase1.md](/Users/congming/github/goldenshare/docs/ops/ops-system-phase1.md)
- [web-platform-phase1-lld.md](/Users/congming/github/goldenshare/docs/platform/web-platform-phase1-lld.md)

## 1.1 后续新增数据集准则

后续新增数据集时，运维能力必须与数据能力同步设计和交付。

明确规则：

- 只要一个数据接口天然带有起止日期语义，就必须同时具备：
  - 单日执行能力
  - 历史回补能力
- 不允许先只上“单日同步”或只上“历史回补”，再等后续页面需要时临时补另一半
- 新增数据集时，必须同步纳入运维系统：
  - 可被监控
  - 可查看健康度/数据状态
  - 可手动执行
  - 如有周期性更新需求，应可纳入自动运行
- 新增数据集的参数与任务交互设计，必须遵循统一模板：
  - [数据集开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)
  - 时间参数优先进入“第二步时间选择”，第三步仅用于“其他输入条件”
- 如果现有数据基座还不支持某种页面需要的同步方式，应先补数据基座能力，再由运维系统调用，不允许页面绕过基座自行实现

这条规则的目标是：

- 避免新增数据集成为“只能写表、不能运维”的孤岛
- 避免后续为了补运营能力再次返工底座接口
- 让运维系统与数据基座从第一天就按统一模式演进

## 2. 一期范围再确认

### 2.1 一期要落地的内容

- 运维系统基础数据模型
- 调度器最小实现
- worker 最小实现
- 统一 execution 链路
- 运维系统首页总览
- 调度配置页
- 执行中心页
- 执行详情页
- 数据新鲜度页
- 资源目录页
- 管理员权限约束

### 2.2 一期不落地的内容

- 告警通知
- 复杂角色系统
- 多节点分布式调度
- 可视化流程编排器
- 执行审批
- 跨环境编排控制
- 普通用户的运维只读视图

## 3. 权限设计

### 3.1 结论

运维系统一期所有能力都收敛到管理员角色。

包括：

- 运维系统页面访问
- 运维系统 API 访问
- 调度配置修改
- 手动执行
- 重试
- 取消
- 维护动作
- 配置查看与变更历史查看

### 3.2 对当前用户模型的判断

当前 [app_user.py](/Users/congming/github/goldenshare/src/platform/models/app/app_user.py) 的设计，在运维系统一期是合理的。

当前字段：

- `is_active`
- `is_admin`

这一设计在当前阶段合理的原因是：

1. 一期权限边界非常清晰，只分普通用户与管理员
2. 运维系统当前没有“部分管理权限”需求
3. 过早引入 `role / permission` 会让平台复杂化，但无法产生真实收益
4. 当前鉴权链路已经支持 `require_admin`

因此，一期建议保持现状，不修改用户表结构来引入 RBAC。

### 3.3 对未来的保留

当前模型合理，但它不是最终角色模型。

后续如出现以下需求，再进入角色系统设计：

- 运维只读角色
- 调度管理角色
- 审计角色
- 业务管理员但非运维管理员
- 多类后台操作权限分离

到那时建议演进为：

- `app.role`
- `app.user_role`
- 可选 `app.permission`

同时保留 `is_admin` 作为平台级超管 bootstrap 字段。

### 3.4 一期权限规则

一期建议明确：

- `/ops` 页面组全部要求管理员
- `/api/v1/ops/*` 全部要求管理员
- 导航中普通用户不展示运维入口
- 即使用户手工访问 URL，也返回 403 或跳转无权限页

## 4. 领域模型设计

### 4.1 代码内元数据模型

这一层不直接入库，而是系统注册表。

#### `JobSpec`

建议字段：

- `key`
- `display_name`
- `category`
- `description`
- `strategy_type`
- `executor_kind`
- `supported_params`
- `default_params`
- `target_tables`
- `supports_schedule`
- `supports_manual_run`
- `supports_retry`
- `estimated_unit_kind`

`strategy_type` 建议枚举：

- `full_refresh`
- `incremental_by_date`
- `backfill_by_trade_date`
- `backfill_by_security`
- `backfill_low_frequency`
- `maintenance_action`

`executor_kind` 建议枚举：

- `sync_service`
- `history_backfill_service`
- `maintenance`

#### `WorkflowSpec`

建议字段：

- `key`
- `display_name`
- `description`
- `steps`
- `parallel_policy`
- `default_schedule_policy`
- `supports_manual_run`

每个 `step` 建议包含：

- `step_key`
- `job_key`
- `depends_on`
- `default_params`

### 4.2 `ops` 表设计

#### `ops.job_schedule`

作用：

- 存储调度实例
- 将 `JobSpec` 或 `WorkflowSpec` 变成真实运行配置

建议字段：

- `id` bigint PK
- `spec_type` varchar(32)
- `spec_key` varchar(128)
- `display_name` varchar(128)
- `status` varchar(16)
- `schedule_type` varchar(32)
- `cron_expr` varchar(64) null
- `timezone` varchar(64)
- `calendar_policy` varchar(32) null
- `params_json` jsonb
- `retry_policy_json` jsonb
- `concurrency_policy_json` jsonb
- `next_run_at` timestamptz null
- `last_triggered_at` timestamptz null
- `created_by_user_id` bigint
- `updated_by_user_id` bigint
- `created_at` timestamptz
- `updated_at` timestamptz

建议索引：

- `(status, next_run_at)`
- `(spec_type, spec_key)`

说明：

- `schedule_type` 用于表达结构化调度方式，如 `cron`、`trading_day_close`、`monthly_window`
- `calendar_policy` 预留给交易日规则
- phase 1 当前实现先落 `once` 与 `cron`
- `trading_day_close`、`monthly_window` 等交易日感知规则在现有控制面上继续迭代

#### `ops.job_execution`

作用：

- 表达一次真实执行请求
- 是手动执行、定时执行、重试的统一容器

建议字段：

- `id` bigint PK
- `schedule_id` bigint null
- `spec_type` varchar(32)
- `spec_key` varchar(128)
- `trigger_source` varchar(16)
- `status` varchar(20)
- `priority` integer default 0
- `requested_by_user_id` bigint null
- `requested_at` timestamptz
- `queued_at` timestamptz null
- `started_at` timestamptz null
- `ended_at` timestamptz null
- `params_json` jsonb
- `summary_message` text null
- `rows_fetched` bigint default 0
- `rows_written` bigint default 0
- `cancel_requested_at` timestamptz null
- `canceled_at` timestamptz null
- `error_code` varchar(64) null
- `error_message` text null
- `created_at` timestamptz
- `updated_at` timestamptz

建议索引：

- `(status, requested_at desc)`
- `(schedule_id, requested_at desc)`
- `(spec_type, spec_key, requested_at desc)`

`trigger_source` 建议枚举：

- `scheduled`
- `manual`
- `retry`
- `replay`
- `system`

`status` 建议枚举：

- `queued`
- `running`
- `success`
- `failed`
- `canceled`
- `partial_success`

#### `ops.job_execution_step`

作用：

- 表达执行内的步骤或单位进度

建议字段：

- `id` bigint PK
- `execution_id` bigint
- `step_key` varchar(128)
- `display_name` varchar(128)
- `sequence_no` integer
- `unit_kind` varchar(32) null
- `unit_value` varchar(128) null
- `status` varchar(20)
- `started_at` timestamptz null
- `ended_at` timestamptz null
- `rows_fetched` bigint default 0
- `rows_written` bigint default 0
- `message` text null
- `created_at` timestamptz
- `updated_at` timestamptz

建议索引：

- `(execution_id, sequence_no)`
- `(execution_id, status)`

`unit_kind` 典型值：

- `trade_date`
- `ts_code`
- `index_code`
- `resource`

#### `ops.job_execution_event`

作用：

- 记录结构化事件流与时间线

建议字段：

- `id` bigint PK
- `execution_id` bigint
- `step_id` bigint null
- `event_type` varchar(32)
- `level` varchar(16)
- `message` text null
- `payload_json` jsonb
- `occurred_at` timestamptz

建议索引：

- `(execution_id, occurred_at)`
- `(step_id, occurred_at)`

`event_type` 建议值：

- `created`
- `queued`
- `started`
- `step_started`
- `step_progress`
- `step_succeeded`
- `step_failed`
- `cancel_requested`
- `canceled`
- `succeeded`
- `failed`

#### `ops.config_revision`

作用：

- 记录调度配置与关键控制面配置变更

建议字段：

- `id` bigint PK
- `object_type` varchar(32)
- `object_id` varchar(128)
- `action` varchar(32)
- `before_json` jsonb null
- `after_json` jsonb null
- `changed_by_user_id` bigint
- `changed_at` timestamptz

建议索引：

- `(object_type, object_id, changed_at desc)`

### 4.3 现有 `ops` 表扩展建议

#### `ops.sync_run_log`

建议增加：

- `execution_id` bigint null

用途：

- 将底层资源同步记录挂到高层 execution
- 让执行详情页可向下钻取到底层同步摘要

#### `ops.sync_job_state`

本期无需重构。

建议继续用于：

- 资源级最近成功日期
- 数据新鲜度计算输入

## 5. `dm` 读模型设计

### 5.1 `dm.ops_daily_overview`

用途：

- 支撑 `/ops` 总览页

建议字段：

- `summary_date`
- `planned_executions`
- `running_executions`
- `success_executions`
- `failed_executions`
- `canceled_executions`
- `lagging_datasets`
- `last_updated_at`

也可以拆成物化视图加多个明细查询，而不一定强行一张大宽表。

### 5.2 `dm.ops_dataset_freshness`

用途：

- 支撑数据新鲜度页面

建议字段：

- `dataset_key`
- `display_name`
- `target_table`
- `latest_business_date`
- `latest_success_at`
- `expected_business_date`
- `lag_days`
- `freshness_status`
- `recent_failure_message`
- `last_checked_at`

`freshness_status` 建议：

- `fresh`
- `lagging`
- `stale`
- `unknown`

phase 1 当前实现说明：

- 先不强依赖 `dm.ops_dataset_freshness`
- 先由 Web 查询层基于 `ops.sync_job_state`
- 辅以 `ops.sync_run_log` 最近失败信息
- 再结合 `core.trade_calendar` 推导日频/周频/月频的预期业务日期

### 5.3 `dm.ops_execution_overview`

用途：

- 支撑执行列表页

建议字段：

- `execution_id`
- `display_name`
- `spec_type`
- `spec_key`
- `trigger_source`
- `status`
- `requested_by_username`
- `requested_at`
- `started_at`
- `ended_at`
- `duration_seconds`
- `rows_fetched`
- `rows_written`
- `summary_message`

## 6. 运行时设计

### 6.1 运行时组件

建议新增：

- `scheduler`
- `worker`
- `dispatcher`

#### `scheduler`

职责：

- 扫描 `job_schedule`
- 判断哪些实例到期
- 创建 `job_execution`
- 计算下一次执行时间

#### `worker`

职责：

- 抢占 `queued` execution
- 执行具体 job 或 workflow
- 写 execution/step/event 状态

#### `dispatcher`

职责：

- 根据 `spec_type/spec_key` 选择对应 executor

### 6.2 抢占与幂等

worker 抢占建议采用数据库锁语义，例如：

- `FOR UPDATE SKIP LOCKED`

目标：

- 避免多个 worker 重复消费
- 未来能平滑扩展到多个 worker 进程

### 6.3 执行流程

标准流程建议：

1. 创建 `job_execution`，状态为 `queued`
2. worker 领取后写 `started_at`，状态改为 `running`
3. 按执行器写入 `job_execution_step`
4. 执行过程持续写 `job_execution_event`
5. 底层同步继续写 `sync_run_log` 和 `sync_job_state`
6. 汇总 `rows_fetched/rows_written`
7. 执行成功或失败后更新 `job_execution`

### 6.4 与现有服务的衔接

执行器建议拆三类：

- `SyncServiceExecutor`
- `BackfillExecutor`
- `MaintenanceExecutor`

对应：

- `build_sync_service(...).run_full/run_incremental(...)`
- `HistoryBackfillService.*`
- `rebuild_dm` 等维护动作

一期建议优先走进程内调用，不以 shell 调 CLI 为主路径。

## 7. 页面与路由设计

### 7.1 页面路由

- `/ops`
- `/ops/schedules`
- `/ops/executions`
- `/ops/executions/{execution_id}`
- `/ops/freshness`
- `/ops/catalog`

一期中这些页面全部要求管理员权限。

phase 1 当前实现说明：

- `/ops` 页面组先以静态控制台壳子方式落地
- 真正的权限边界当前落在 `/api/v1/ops/*`
- 因此未登录用户能拿到页面壳子，但无法读取或操作任何运维数据
- 如果后续需要服务端级页面门禁，再引入更适合的 cookie/session 方案

### 7.2 总览页 `/ops`

页面模块建议：

- 顶部 KPI 区
- 今日执行概览
- 失败与异常卡片
- 关键数据新鲜度摘要
- 快捷操作区

### 7.3 调度配置页 `/ops/schedules`

页面模块建议：

- 状态摘要条
- 调度列表
- 调度详情抽屉/侧栏
- 新建调度
- 编辑调度
- 下一次 / 未来几次运行预览
- 启停控制
- 配置变更历史
- 页面级草稿恢复
- 最近选中的 schedule 上下文恢复

### 7.4 执行中心页 `/ops/executions`

页面模块建议：

- 筛选条
- 执行列表
- 手动执行侧栏
- 快捷重试与取消
- 复制为新执行
- 危险操作确认
- 操作结果统一摘要
- 筛选条件本地持久化
- 最近查看 execution 快捷区

### 7.5 执行详情页 `/ops/executions/{execution_id}`

页面模块建议：

- 状态摘要条
- 基本信息
- 参数快照
- 时间线
- 步骤列表
- 事件流
- 日志面板
- 结果摘要
- 复制为新执行
- 危险操作确认与统一结果反馈
- 自动刷新、日志筛选与检查面板
- 返回列表时保留 execution 列表上下文

### 7.6 数据新鲜度页 `/ops/freshness`

页面模块建议：

- 域分组筛选
- 新鲜度矩阵表
- 滞后项高亮
- 跳转相关 execution

### 7.7 资源目录页 `/ops/catalog`

页面模块建议：

- 资源列表
- spec 详情面板
- 支持参数说明
- 当前调度绑定情况
- 启用中的调度数
- 当前数据状态

## 8. Web API 设计

一期建议新增 `src/ops/api/`。

所有接口都要求 `require_admin`。

### 8.1 总览

- `GET /api/v1/ops/overview`

返回：

- KPI
- 今日执行摘要
- 失败摘要
- 新鲜度摘要

### 8.2 调度配置

- `GET /api/v1/ops/schedules`
- `POST /api/v1/ops/schedules`
- `POST /api/v1/ops/schedules/preview`
- `GET /api/v1/ops/schedules/{id}`
- `PATCH /api/v1/ops/schedules/{id}`
- `POST /api/v1/ops/schedules/{id}/pause`
- `POST /api/v1/ops/schedules/{id}/resume`
- `GET /api/v1/ops/schedules/{id}/revisions`

### 8.3 执行中心

- `GET /api/v1/ops/executions`
- `POST /api/v1/ops/executions`
- `GET /api/v1/ops/executions/{id}`
- `POST /api/v1/ops/executions/{id}/retry`
- `POST /api/v1/ops/executions/{id}/cancel`

### 8.4 详情视图

- `GET /api/v1/ops/executions/{id}/steps`
- `GET /api/v1/ops/executions/{id}/events`
- `GET /api/v1/ops/executions/{id}/logs`

### 8.5 新鲜度与目录

- `GET /api/v1/ops/freshness`
- `GET /api/v1/ops/catalog`
- `GET /api/v1/ops/job-specs/{key}`

### 8.6 Runtime 命令

- `goldenshare ops-scheduler-tick --limit N`
- `goldenshare ops-worker-run --limit N`
- `POST /api/v1/ops/runtime/scheduler-tick`
- `POST /api/v1/ops/runtime/worker-run`

用途：

- 用统一入口驱动 scheduler / worker 的最小运行闭环
- 便于单机部署、systemd 托管和人工 smoke test
- 保持和 `job_execution` 统一模型对齐

## 9. Schema 设计建议

建议新增：

```text
src/ops/schemas/
  __init__.py
  overview.py
  schedule.py
  execution.py
  freshness.py
  catalog.py
```

### 9.1 `schedule.py`

建议定义：

- `ScheduleListItem`
- `ScheduleDetail`
- `CreateScheduleRequest`
- `UpdateScheduleRequest`
- `ScheduleRevisionItem`

### 9.2 `execution.py`

建议定义：

- `ExecutionListItem`
- `ExecutionDetail`
- `CreateExecutionRequest`
- `ExecutionStepItem`
- `ExecutionEventItem`

### 9.3 `freshness.py`

建议定义：

- `DatasetFreshnessItem`
- `FreshnessGroup`

### 9.4 `catalog.py`

建议定义：

- `JobSpecListItem`
- `JobSpecDetail`
- `WorkflowSpecDetail`

## 10. 服务与查询层设计

### 10.1 `src/operations/`

建议新增：

```text
src/operations/
  specs/
  services/
  runtime/
  executors/
```

### 10.2 `src/ops/services/`

建议新增：

- `overview_service.py`
- `schedule_service.py`
- `execution_service.py`

职责：

- 协调 web 请求与 operations 服务
- 处理权限后的业务流程

### 10.3 `src/ops/queries/`

建议新增：

- `overview_query_service.py`
- `execution_query_service.py`
- `freshness_query_service.py`
- `catalog_query_service.py`

职责：

- 面向页面拼装读模型

## 11. 推荐实施顺序

### 第一步：规则与元数据

- 建立 `JobSpec / WorkflowSpec`
- 建立 spec registry
- 先覆盖现有最关键同步与回补能力

### 第二步：数据库基础模型

- 新增 `job_schedule`
- 新增 `job_execution`
- 新增 `job_execution_step`
- 新增 `job_execution_event`
- 新增 `config_revision`
- 扩展 `sync_run_log`

### 第三步：执行闭环

- 实现 dispatcher
- 实现 worker
- 实现 scheduler
- 接通现有 sync/backfill service

### 第四步：先做观测页

- 总览
- 执行中心
- 执行详情

这三页最能验证控制面模型是否合理。

### 第五步：调度配置

- 调度列表
- 调度编辑
- 配置变更历史

### 第六步：新鲜度与目录

- 新鲜度页
- 资源目录页

## 12. 验收标准

一期完成时，应至少满足：

1. 只有管理员可以访问运维系统页面和 API
2. 可以配置、启停一个调度实例
3. scheduler 能创建 execution
4. worker 能消费 execution 并驱动现有同步服务
5. 手动执行与定时执行共享同一 execution 模型
6. 可以查看执行详情、步骤、事件、日志
7. 可以查看关键数据集新鲜度
8. 可以查看每日汇总
9. 页面不依赖文本日志解析作为主状态来源

## 13. 结论

从角色设计视角看，当前 `app_user.is_admin` 模型对运维系统一期是合理的。

从系统设计视角看，运维系统一期的关键不是先做 UI，而是：

- 先把控制面对象建立起来
- 再把执行链路收敛起来
- 最后再以页面方式呈现和操作这些对象

这也是本 LLD 的核心出发点。
