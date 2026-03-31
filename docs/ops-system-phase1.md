# 运维系统一期设计

## 1. 文档目标

本文档定义 `goldenshare` 运维系统一期的设计方案。

这里的“一期”不是指做一个临时 admin 页面，而是指在现有数据基座与 Web 平台之上，开始建立一个可以长期演进的运维系统 V0。

本文档聚焦：

- 运维系统的系统定位
- 一期的边界与目标
- 核心领域对象与总体架构
- 页面与 API 的信息架构
- 与当前同步体系的衔接方式
- 推荐的实施顺序

实现与后续迭代需同时遵守以下文档：

- [design-principles.md](/Users/congming/github/goldenshare/docs/design-principles.md)
- [web-platform-phase1.md](/Users/congming/github/goldenshare/docs/web-platform-phase1.md)
- [web-platform-phase1-lld.md](/Users/congming/github/goldenshare/docs/web-platform-phase1-lld.md)

## 2. 系统定位

### 2.1 不是“数据监控页迁移”

本期不应被理解为：

- 把外部仓库的 admin 页面搬过来
- 在 Web 中临时加几个监控接口
- 用页面直接拼接现有 CLI 和日志

本期应被理解为：

- 在 `goldenshare` 上建立运维系统的第一阶段
- 为未来的调度、执行、监控、审计、汇总、告警能力建立统一控制面

### 2.2 在整体系统中的位置

`goldenshare` 长期将由三层能力共同构成：

1. 数据基座
2. 运维系统
3. 产品化 Web

其中：

- 数据基座负责采集、清洗、落库、分层存储
- 运维系统负责调度、执行、控制、监控、汇总、审计
- 产品化 Web 负责后续业务页面、分析页面、用户功能

换句话说，本期做的是“运维系统的开始”，不是普通后台页。

## 3. 一期目标

运维系统一期要完成的是：

1. 建立统一的控制面模型
2. 建立统一的执行请求模型
3. 建立统一的执行监控与详情查看能力
4. 建立统一的数据新鲜度与每日汇总能力
5. 建立结构化调度配置能力
6. 让手动执行与定时执行进入同一条控制链路

一期完成后，应具备以下结果：

- 可以配置一个定时任务，而不是依赖本地 YAML 作为长期真相源
- 可以从页面发起一次手动执行，而不是直接在页面中拼命令
- 可以看到一次执行的结构化状态、参数、步骤、日志、结果
- 可以看到每日整体同步状态和关键数据集最新状态
- 可以为后续告警、审计、维护模式、多 worker 扩展留出稳定位置

## 4. 一期边界

### 4.1 一期纳入范围

- 运维系统首页总览
- 调度配置
- 执行中心
- 执行详情
- 数据新鲜度
- 资源目录
- 统一控制面模型
- 调度器与执行器最小闭环
- 结构化运行状态与事件

### 4.2 一期明确不做

- 不做告警通知中心
- 不做短信、邮件、IM 推送
- 不做完整 RBAC
- 不做多租户、多环境集群编排
- 不做可视化 DAG 设计器
- 不做多节点分布式调度编排
- 不做旧仓库后端兼容
- 不把页面建立在文本日志解析之上

### 4.3 一期权限边界

运维系统一期的权限应收敛到管理员角色。

这意味着：

- 运维系统页面默认仅管理员可见
- 运维系统 API 默认仅管理员可调用
- 调度配置、手动执行、重试、取消、维护类操作不向普通登录用户开放
- 不在一期引入复杂角色树来支撑尚未出现的需求

从当前用户模型看，现有 [app_user.py](/Users/congming/github/goldenshare/src/models/app/app_user.py) 中的：

- `is_active`
- `is_admin`

作为一期权限模型是合理的。

原因是：

- 当前 Web 平台尚无复杂业务角色
- 运维系统一期明确是管理员控制面
- `is_admin` 与当前权限边界完全一致

但这并不代表长期角色模型已经最终确定。

后续如果出现：

- 运维只读角色
- 调度管理员
- 审计查看角色
- 业务运营角色

再按真实需求引入 `role / user_role / permission` 等结构化模型，而不是提前过度设计。

## 5. 现有能力与复用原则

一期并不是从零开始。

当前仓库已具备以下可复用基础：

- [sync_run_log.py](/Users/congming/github/goldenshare/src/models/ops/sync_run_log.py)
- [sync_job_state.py](/Users/congming/github/goldenshare/src/models/ops/sync_job_state.py)
- [base_sync_service.py](/Users/congming/github/goldenshare/src/services/sync/base_sync_service.py)
- [history_backfill_service.py](/Users/congming/github/goldenshare/src/services/history_backfill_service.py)
- [cli.py](/Users/congming/github/goldenshare/src/cli.py)
- 已完成的一期 Web 平台基础能力

这些能力的定位应是：

- `sync` service 和 `backfill` service 是执行原语
- CLI 是当前已有的人工入口和维护入口
- `ops.sync_run_log` 和 `ops.sync_job_state` 是已有运维底座

但它们还不是完整的运维系统控制面。

因此，一期应采用以下复用原则：

- 复用现有同步 service，不重写同步逻辑
- 尽量复用现有 `ops` 表，而不是推倒重建
- 通过新增更高层控制面对象，把现有同步能力纳入统一控制链路
- 外部仓库只参考页面结构和交互，不参考其调度文件、日志解析、后端路由设计

## 6. 总体架构

运维系统一期建议按四个平面设计：

### 6.1 控制面

负责：

- 任务定义
- 工作流定义
- 调度配置
- 手动执行请求
- 重试与取消
- 配置变更历史

### 6.2 执行面

负责：

- 调度器扫描到期任务
- worker 消费执行请求
- 调用现有 `sync` / `backfill` service
- 产出结构化执行状态、步骤、事件和日志

### 6.3 观测面

负责：

- 执行状态
- 步骤状态
- 错误与结果摘要
- 数据集新鲜度
- 每日汇总

### 6.4 展示面

负责：

- 总览
- 调度配置
- 执行中心
- 执行详情
- 数据新鲜度
- 资源目录

## 7. 核心领域对象

一期应围绕领域对象设计，而不是围绕页面设计。

### 7.1 代码内定义对象

#### `JobSpec`

表示一个可执行能力定义。

典型示例：

- `sync_history.stock_basic`
- `sync_daily.daily_basic`
- `backfill_equity_series.daily`
- `backfill_index_series.index_weekly`
- `maintenance.rebuild_dm`

建议包含的信息：

- `key`
- `display_name`
- `category`
- `strategy_type`
- `supported_params`
- `default_params`
- `target_tables`
- `supports_manual_run`
- `supports_schedule`

#### `WorkflowSpec`

表示一组可编排执行的任务模板。

典型示例：

- 每日收盘后同步
- 历史基础数据回补
- 指数扩展数据补齐

建议包含的信息：

- `key`
- `display_name`
- `steps`
- `step_order`
- `parallel_policy`
- `default_trigger_policy`

### 7.2 `ops` 持久化对象

#### `ops.job_schedule`

表示一个调度实例。

作用：

- 将 `JobSpec` 或 `WorkflowSpec` 落成实际调度配置
- 记录启用状态、下次执行时间、重试策略、并发策略

phase 1 当前实现说明：

- 调度类型先支持 `once` 和 `cron`
- 先保证手动执行、定时执行、重试都进入统一 execution 链路
- 交易日感知的结构化调度规则后续在这个控制面上继续扩展

#### `ops.job_execution`

表示一次执行请求。

来源可以是：

- scheduled
- manual
- retry
- replay
- system

这是统一控制面的核心对象。

#### `ops.job_execution_step`

表示一次执行中的子步骤或子单元。

作用：

- 表达工作流内部步骤
- 表达按 trade_date / ts_code / index_code 纵向执行时的单位进度
- 为详情页提供结构化进度

#### `ops.job_execution_event`

表示结构化事件流。

用途：

- 记录 `created / queued / started / progress / succeeded / failed / canceled`
- 记录关键上下文，例如参数、错误摘要、运行阶段变化
- 为页面提供时间线与实时进度基础

#### `ops.config_revision`

表示配置变更记录。

用途：

- 审计谁改了什么
- 支持回看历史
- 支撑未来配置回滚

### 7.3 现有表的继续角色

#### `ops.sync_run_log`

继续保留，用作底层同步运行摘要。

建议在一期中增加可选关联能力：

- `execution_id`

这样单个底层同步记录可以挂到一次高层执行请求上。

#### `ops.sync_job_state`

继续保留，用作资源级最新成功状态快照。

它适合作为数据新鲜度计算的输入之一，但不替代 `job_execution`。

### 7.4 `dm` 读模型

一期建议新增至少两个读模型：

#### `dm.ops_daily_overview`

用于总览页。

建议汇总：

- 今日计划执行数
- 今日成功/失败/运行中
- 今日关键失败任务
- 每日结果摘要

#### `dm.ops_dataset_freshness`

用于数据新鲜度页。

建议包含：

- dataset_key
- target_table
- latest_business_date
- latest_success_at
- expected_business_date
- lag_days
- freshness_status
- recent_failure_message

## 8. 状态机设计

### 8.1 调度状态

`job_schedule.status` 建议至少包含：

- `active`
- `paused`
- `disabled`

### 8.2 执行状态

`job_execution.status` 建议至少包含：

- `queued`
- `running`
- `success`
- `failed`
- `canceled`
- `partial_success`

### 8.3 步骤状态

`job_execution_step.status` 建议至少包含：

- `pending`
- `running`
- `success`
- `failed`
- `skipped`
- `canceled`

## 9. 执行链路设计

### 9.1 统一原则

手动执行、定时执行、重试执行都必须汇入同一条执行链路。

标准流程建议如下：

1. 由 Web 或 scheduler 创建 `job_execution`
2. worker 领取待执行记录
3. worker 根据 `JobSpec / WorkflowSpec` 调用具体执行器
4. 执行过程写入 `job_execution_step` 与 `job_execution_event`
5. 底层资源同步继续写 `sync_run_log` 和 `sync_job_state`
6. 执行结束后更新 `job_execution` 总体状态
7. `dm` 读模型刷新总览与新鲜度

### 9.2 Web 的职责边界

Web 不负责长期持有任务执行。

Web 只负责：

- 创建执行请求
- 查询执行状态
- 请求取消
- 修改调度配置

真正执行长任务的应是独立 runtime 组件：

- scheduler
- worker

### 9.3 与现有同步体系的衔接

一期不建议让 worker 通过 shell 调 CLI 作为主路径。

推荐顺序：

1. 优先在进程内复用现有 service 层
2. CLI 继续作为人工维护入口和兜底入口
3. 如短期存在无法直接进程内复用的能力，再通过明确的 adapter 过渡

这条原则的目的是避免未来控制面长期依赖 shell 命令。

## 10. 页面与信息架构

一期建议将这一模块命名为：

- `数据控制台`
或
- `运维系统`

不建议继续沿用“一个 admin 页面 + tab”作为长期结构。

### 10.1 页面路由建议

- `/ops`
- `/ops/schedules`
- `/ops/executions`
- `/ops/executions/{execution_id}`
- `/ops/freshness`
- `/ops/catalog`

### 10.2 总览页 `/ops`

定位：

- 运维系统首页
- 每日同步结果与系统状态总览

建议内容：

- 顶部 KPI
  - 今日计划数
  - 运行中
  - 成功
  - 失败
  - 数据滞后数
- 今日执行看板
- 关键异常
- 快捷操作
- 关键数据新鲜度摘要

页面目标：

- 一眼看清今天整体是否正常
- 一眼识别当前最需要处理的问题

### 10.3 调度配置页 `/ops/schedules`

定位：

- 控制面配置页

建议内容：

- 状态摘要条
- 调度实例列表
- 启用/暂停开关
- 下次执行时间
- 未来几次运行预览
- 最近一次执行结果
- 调度编辑器
- 触发规则预览
- 配置变更历史入口

设计建议：

- 默认使用结构化调度规则
- 高级模式再允许 cron 表达式
- 不以本地 YAML 文件作为长期真相源
- 调度编辑页应保留页面级草稿和最近查看上下文，避免刷新或跳转后丢失操作现场

### 10.4 执行中心页 `/ops/executions`

定位：

- 统一执行监控中心

建议内容：

- 执行列表
- 按状态、来源、资源域、时间范围筛选
- 手动执行入口
- 重试入口
- 复制为新执行入口
- 取消入口
- 跳转执行详情
- 危险操作确认
- 操作结果统一摘要
- 筛选条件持久化
- 最近查看 execution 快捷入口

### 10.5 执行详情页 `/ops/executions/{execution_id}`

定位：

- 单次执行的排障与审计核心页

建议内容：

- 状态摘要条
- 基本信息
- 参数快照
- 时间线
- 子步骤/子任务进度
- 结构化事件流
- 原始日志
- 结果摘要
- 重试与复制执行参数
- 复制为新执行
- 自动刷新、日志筛选与 payload 检查面板
- 危险操作确认与统一结果反馈
- 返回列表时尽量保留执行中心的筛选上下文

不建议把日志长期放在弹窗中完成全部查看与排障。

### 10.6 数据新鲜度页 `/ops/freshness`

定位：

- 数据是否“同步到了应该同步到的日期”的统一判断入口

建议内容：

- 数据集分组视图
- 最新业务日期
- 最新成功时间
- 预期日期
- 滞后天数
- 最近失败摘要
- 跳转相关执行记录

### 10.7 资源目录页 `/ops/catalog`

定位：

- 系统能力目录
- 手动执行与调度配置的说明入口

建议内容：

- 资源 key
- 展示名
- 所属域
- 支持的执行策略
- 支持的参数
- 目标表
- 调度绑定数
- 启用中的调度数
- 当前数据状态

这一页虽然不是最早必须上线的用户入口，但从系统演进角度非常值得纳入一期设计。

## 11. 手动执行设计

手动执行不应设计成“选一个命令然后输入几个参数”。

建议设计成“按执行策略驱动的结构化表单”。

### 11.1 策略类型建议

一期建议至少支持：

- `full_refresh`
- `incremental_by_date`
- `backfill_by_trade_date`
- `backfill_by_security`
- `backfill_low_frequency`
- `maintenance_action`

### 11.2 参数驱动方式

手动执行表单应由 `JobSpec` 元数据驱动，而不是页面硬编码。

表单应根据策略动态展示：

- 日期参数
- 交易所参数
- 资源参数
- offset / limit
- 指定 `ts_code`
- 指定 `index_code`
- dry-run（后续可扩）

### 11.3 建议增强能力

建议预留：

- 执行预估
  - 预估将涉及多少 trade_date / 多少证券 / 多少指数
- 参数复用
  - 从历史执行复制参数
- 保存为调度
  - 将一次稳定的手动执行直接升格为调度实例

## 12. 调度配置设计

### 12.1 设计目标

调度配置页的目标不是编辑一个文件，而是管理“调度实例”。

### 12.2 调度表达方式

建议支持三层表达：

1. 结构化规则
2. 交易日语义规则
3. 高级 cron

优先推荐：

- 每个交易日某时刻
- 每周五某时刻
- 每月前 N 日
- 月末窗口

### 12.3 调度策略建议

每个调度实例建议支持：

- enabled / paused
- retry policy
- max concurrency
- dedupe policy
- catch-up policy
- next run preview

## 13. API 设计建议

一期 API 仍应遵循 BFF 原则，面向页面模型，不暴露底层表结构。

建议新增 `src/web/api/v1/ops/` 模块。

权限要求：

- 一期中所有 `/api/v1/ops/*` 端点默认要求 `require_admin`
- 不区分普通登录用户的只读访问
- 如果未来需要只读运维角色，应在真正出现需求后再扩展

### 13.1 总览

- `GET /api/v1/ops/overview`

### 13.2 调度配置

- `GET /api/v1/ops/schedules`
- `POST /api/v1/ops/schedules`
- `POST /api/v1/ops/schedules/preview`
- `PATCH /api/v1/ops/schedules/{id}`
- `POST /api/v1/ops/schedules/{id}/pause`
- `POST /api/v1/ops/schedules/{id}/resume`
- `GET /api/v1/ops/schedules/{id}/revisions`

### 13.3 执行中心

- `GET /api/v1/ops/executions`
- `POST /api/v1/ops/executions`
- `GET /api/v1/ops/executions/{id}`
- `POST /api/v1/ops/executions/{id}/retry`
- `POST /api/v1/ops/executions/{id}/cancel`

### 13.4 执行事件与日志

- `GET /api/v1/ops/executions/{id}/steps`
- `GET /api/v1/ops/executions/{id}/events`
- `GET /api/v1/ops/executions/{id}/logs`

### 13.5 Runtime 入口

为了让运维系统的一期控制面真正能驱动 execution，phase 1 允许保留最小 CLI runtime 入口：

- `goldenshare ops-scheduler-tick --limit N`
  - 扫描到期调度并创建 execution
- `goldenshare ops-worker-run --limit N`
  - 消费最多 N 条 queued execution

同时提供管理员 API 入口，供运维控制台直接调用：

- `POST /api/v1/ops/runtime/scheduler-tick`
- `POST /api/v1/ops/runtime/worker-run`

这两个命令的定位是：

- 便于本地与单机环境验证执行闭环
- 为后续 systemd / supervisor / cron 编排预留稳定入口
- 不改变“worker 主路径应直接调用 Python runtime，而不是通过 shell 再套一层 CLI”的总体原则

### 13.6 新鲜度与目录

- `GET /api/v1/ops/freshness`
- `GET /api/v1/ops/catalog`
- `GET /api/v1/ops/job-specs/{key}`

## 14. 推荐目录结构

一期建议在现有架构上新增一个独立的运维子系统目录，而不是把所有代码塞进 `src/web/`。

建议结构：

```text
src/operations/
  __init__.py

  specs/
    __init__.py
    job_spec.py
    workflow_spec.py
    registry.py

  services/
    __init__.py
    schedule_service.py
    execution_service.py
    overview_service.py
    freshness_service.py

  runtime/
    __init__.py
    scheduler.py
    worker.py
    dispatcher.py

  executors/
    __init__.py
    sync_executor.py
    backfill_executor.py
    workflow_executor.py

src/web/
  api/
    v1/
      ops/
        __init__.py
        overview.py
        schedules.py
        executions.py
        freshness.py
        catalog.py

  schemas/
    ops/
      __init__.py
      overview.py
      schedule.py
      execution.py
      freshness.py
      catalog.py

  services/
    ops/
      __init__.py
      overview_service.py
      execution_service.py
      schedule_service.py

  queries/
    ops/
      __init__.py
      overview_query_service.py
      execution_query_service.py
      freshness_query_service.py
```

## 15. 一期推荐实施顺序

建议按“先内核、后页面”的方式推进。

### 第一步：控制面基础模型

- 定义 `JobSpec / WorkflowSpec`
- 新增 `job_schedule / job_execution / job_execution_step / job_execution_event / config_revision`
- 明确状态机

### 第二步：执行最小闭环

- 实现 scheduler 最小扫描逻辑
- 实现 worker 最小消费逻辑
- 接通现有 `sync` / `backfill` service
- 写入结构化执行状态

### 第三步：总览与执行中心

- 先做总览
- 再做执行列表与执行详情
- 这两部分最能验证控制面模型是否合理

### 第四步：数据新鲜度

- 建立 `dm.ops_dataset_freshness`
- 做新鲜度页面

### 第五步：调度配置

- 做调度实例列表与编辑
- 做配置变更历史

### 第六步：资源目录与增强能力

- 做资源目录
- 做“保存为调度”“复制参数执行”等增强功能

## 16. 一期验收标准

如果一期完成，至少应满足：

1. 可以通过页面配置并启停一个调度实例
2. 调度器可以创建执行请求
3. 手动执行与定时执行进入同一条执行链路
4. 可以查看执行列表和执行详情
5. 可以查看关键数据集新鲜度
6. 可以在总览页看到每日同步结果摘要
7. 可以追溯配置变更历史
8. 页面状态主要来自结构化 `ops` 与 `dm` 数据，而不是文本日志解析

## 17. 后续迭代方向

一期之后，运维系统可以继续向这些方向扩展：

- 告警与通知中心
- 维护模式
- 失败自动重试策略
- 审批型执行
- 多 worker 扩展
- 分布式调度
- SLO / SLA 监控
- 运维日报
- 审计查询

## 18. 总结

运维系统一期的核心不是“做几个监控页面”，而是：

- 先定义统一控制面
- 再建立统一执行链路
- 最后以页面方式呈现控制与观测能力

这也是为什么本期应被视为“运维系统的一期”，而不是“数据监控页面的迁移”。
