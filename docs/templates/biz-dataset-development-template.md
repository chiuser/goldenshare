# Biz 数据集开发说明模板（内部计算数据主线）

> 使用说明：
> - 编写前必须先阅读仓库根目录 `AGENTS.md`、`docs/AGENTS.md`、目标代码目录逐级 `AGENTS.md`。
> - 本模板只适用于本系统计算、聚合、物化或发布形成的内部业务数据集。
> - 外部源站拉取的数据集必须使用 [DatasetDefinition 数据集开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)，不能用本模板绕过 ingestion 主线。
> - Dagster/Lake 生产的数据集还必须同时遵守 orchestrator 的数据集模板和目录规则；Biz 定义只负责 Ops 展示，不替代 Dagster asset 定义。
> - 每个 Biz 数据集复制本模板生成独立开发文档，放入 `docs/datasets/`。
> - 未完成事实定义、生产链路、观测语义、任务边界、性能和测试门禁，不得进入编码。

---

## 0. 先判断是否属于 Biz 数据集

| 判断项 | 本数据集答案 | 证据 |
| --- | --- | --- |
| 数据是否由本系统计算、聚合、物化、裁剪或关联生成 |  |  |
| 是否不是外部源站原始维护对象 |  |  |
| 最终物理表/视图是否服务业务 API 或业务页面 |  |  |
| 生产入口是 Ops maintenance action、Dagster asset 还是其他正式入口 |  |  |
| 是否应展示在 Ops“Biz数据集”页面 |  |  |

不适用情况：

1. 数据直接来自 Tushare/Biying 等外部源站：使用普通数据集模板和 `DatasetDefinition`。
2. 表是 staging、临时、缓存、中间交换或内部控制表：默认不展示为 Biz 卡片。
3. 只有研究脚本或报告文件，没有正式生产表和稳定生产入口：不得登记为 Prod Biz 数据集。

## 1. 基本信息

- Biz dataset key：
- 中文显示名：
- 简短说明：
- 物理表/物化视图：
- 对外消费者/API/页面：
- 页面分组 key：
- 页面分组名称：
- 分组顺序：
- 卡片顺序：
- 数据负责人：
- 方案文档：
- LLD：
- 当前状态：待评审 / 待开发 / 已实现待验收 / 已验收

硬规则：

1. `dataset_key` 和物理表必须全局唯一。
2. 中文名称必须表达业务内容，不能暴露内部执行器、任务类型或技术缩写。
3. 分组只用于 Ops 展示，不反向改变业务模型、表结构或生产入口。
4. 一张卡片默认对应一张可独立解释的业务表；控制表必须写明为何不展示。

## 2. 数据模型与存储

### 2.1 表定义

| 项目 | 设计与证据 |
| --- | --- |
| schema.table |  |
| 对象类型（表/普通 view/物化 view） |  |
| ORM/SQL 定义位置 |  |
| 主键或唯一身份 |  |
| 业务日期字段 |  |
| 构建/发布时间字段 |  |
| 关键查询索引 |  |
| 数据保留/覆盖规则 |  |
| 是否有发布批次控制表 |  |

### 2.2 业务身份和幂等

- 一条数据代表什么：
- 唯一身份：
- 重复计算如何处理：覆盖 / 分区替换 / 版本发布 / 其他
- 源数据修订后如何重新生成：
- 失败重跑是否幂等：

### 2.3 表与控制对象边界

| 对象 | 是否展示卡片 | 原因 |
| --- | --- | --- |
| 正式业务表 | 是 / 否 |  |
| 发布批次表 | 默认否 |  |
| staging/candidate 表 | 否 |  |
| 临时表 | 否 |  |

禁止为了凑卡片数量把发布批次、锁、游标、checkpoint、日志或临时表包装成业务数据集。

## 3. 生产链路

### 3.1 生产入口

- `producer_type`：`maintenance_action` / `dagster_asset` / `materialized_view` / 其他（需评审）
- `producer_key`：
- 真实代码入口：
- 上游数据：
- 下游消费者：

```text
上游正式数据
  -> 计算/聚合
  -> 校验
  -> 业务事务提交或原子发布
  -> Biz 业务表
  -> API/页面
```

### 3.2 事务与失败

| 项目 | 本数据集口径 |
| --- | --- |
| 最小可提交单元 |  |
| 是否分区/分日提交 |  |
| 失败后已提交数据是否保留 |  |
| 重跑依据 |  |
| 取消检查点 |  |
| TaskRun/观测失败是否影响业务事务 | 必须为“否” |

硬规则：

1. Ops/TaskRun/schedule 等状态写入不得回滚已提交的 Biz 业务数据。
2. 不新增第二套执行入口；必须引用当前正式 producer。
3. 预计或实测超过 60 秒的 Prod 任务必须补充根 `AGENTS.md` 中的长任务合同。
4. Dagster 资产不得为了出现 Ops 卡片而包装成假的 maintenance action。

### 3.3 性能评估

| 项目 | 估算/实测 |
| --- | --- |
| 单次输入规模 |  |
| 预计输出行数 |  |
| 峰值内存 |  |
| 数据库写入量 |  |
| 预计耗时 |  |
| 对在线查询的锁/IO 影响 |  |
| 可接受边界 |  |

数据集同步和计算效率是开发硬门禁。不能等上线后才发现全量扫描、超大事务或轮询查询不可接受。

## 4. BizDatasetDefinition

目标定义位置：

```text
src/ops/catalog/biz_dataset_definitions.py
```

填写：

```python
BizDatasetDefinition(
    dataset_key="",
    display_name="",
    description="",
    table_name="schema.table",
    group_key="",
    group_label="",
    group_order=0,
    item_order=0,
    observation_query_key="",
    freshness_policy_key="",
    business_date_column=None,
    observed_at_column=None,
    ready_after_local_time=None,
    producer_type="",
    producer_key="",
)
```

### 4.1 字段对账

| 定义字段 | 本数据集值 | 代码/数据库证据 |
| --- | --- | --- |
| `dataset_key` |  |  |
| `display_name` |  |  |
| `table_name` |  |  |
| `group_key/group_label` |  |  |
| `group_order/item_order` |  |  |
| `observation_query_key` |  |  |
| `freshness_policy_key` |  |  |
| `business_date_column` |  |  |
| `observed_at_column` |  |  |
| `ready_after_local_time` |  |  |
| `producer_type/producer_key` |  |  |

### 4.2 禁止重复定义

Biz definition 不得复制以下事实：

- `manual_enabled`
- `schedule_enabled`
- 手动参数
- 自动任务时间策略
- 执行器名称和执行配置

如果 producer 是 maintenance action，上述事实必须直接读取 `MaintenanceActionDefinition`。

## 5. 观测与新鲜度

### 5.1 三层语义

| 层级 | 必须回答的问题 | 本数据集答案 |
| --- | --- | --- |
| 业务表事实 | 表里实际最新到哪一天/哪个版本 |  |
| 构建事实 | 最近一次正式发布或构建何时成功 |  |
| Ops 判断 | 什么条件下显示正常、滞后、失败或未确认 |  |

这三者不能混为一谈：TaskRun 成功不自动证明目标日期已经写入；业务表有旧数据也不证明最近一次构建成功。

### 5.2 观测查询

- query key：
- 查询的表/发布批次：
- 业务日期列：
- 构建时间列：
- 必须过滤的正式状态：
- 查询是否命中索引：
- 是否需要关联发布批次：
- 空表语义：
- 查询失败语义：

禁止：

1. 页面每 5 秒刷新时对大表执行 `count(*)`。
2. 对无索引日期列反复做 `MAX/MIN` 或排序。
3. 根据表名猜业务日期。
4. 通过前端拼装“最近成功日期”。

### 5.3 新鲜度策略

- policy key：
- 是否要求每个交易日都有数据：
- 期望业务日如何计算：
- 最早判迟时间：
- 非交易日如何处理：
- 静态/事件型数据为什么不会被错误判迟：

若现有策略不适用，先说明新的业务语义和复用范围，经评审后才能新增。禁止为每张表发明一个只用一次的模糊策略。

## 6. 手动任务支持

### 6.1 是否支持

- 是否需要运营手动维护：是 / 否
- 如果否，原因：只读 Dagster 资产 / 自动生产 / 无安全手动入口 / 其他
- 如果是，maintenance action key：

### 6.2 `MaintenanceActionDefinition`

| 字段 | 本数据集设计 |
| --- | --- |
| `key` |  |
| `display_name` |  |
| `description` |  |
| `executor_key` |  |
| `target_tables` | 必须包含本 Biz 表 |
| `parameters` |  |
| `manual_time_regime` |  |
| `manual_enabled` |  |
| `retry_enabled` |  |

手动任务主链：

```text
MaintenanceActionDefinition(manual_enabled=True)
  -> ManualActionQueryService
  -> POST /api/v1/ops/manual-actions/{action_key}/task-runs
  -> TaskRun(target_type=maintenance_action)
  -> TaskRunDispatcher
  -> app composition root 中注册的 executor
```

门禁：

1. Ops action catalog 只描述动作；业务实现放在正确子系统，由 `src/app` 组合装配，禁止 `src/ops -> src/biz` 反向依赖。
2. 参数必须表达运营意图，不暴露内部 SQL、表名或执行器分支。
3. Biz 卡片绑定该 action 后，`primary_action_type` 必须是 `maintenance_action`。

## 7. 自动任务支持

### 7.1 是否支持

- 是否需要自动任务：是 / 否
- `schedule_enabled`：
- 允许的 schedule 类型：
- 日期/时间策略：
- 是否需要 readiness/probe：
- 并发与去重规则：

自动任务主链：

```text
MaintenanceActionDefinition(schedule_enabled=True)
  -> ScheduleAutomationCapabilityResolver
  -> Ops catalog
  -> ops.schedule(target_type=maintenance_action, target_key=<action_key>)
  -> scheduler 创建 TaskRun
  -> dispatcher 执行同一个 maintenance action
```

硬规则：

1. `schedule_enabled=False` 时不得仅靠前端开放自动任务。
2. 有特殊重复频率、固定时间或 readiness 时，必须在服务端能力契约中定义并测试，不能只写页面常量。
3. 自动任务和手动任务必须进入同一个正式生产入口，不能各走一套业务实现。
4. 卡片自动任务摘要直接查询 action 的 schedule，不在 Biz definition 保存副本。

## 8. 卡片投影与页面

### 8.1 预期卡片

| 字段 | 预期 |
| --- | --- |
| 卡片名称 |  |
| 表名 |  |
| 分组与顺序 |  |
| 状态 |  |
| 最新业务日期/构建时间 |  |
| 手动入口 | 有 / 无 |
| 自动任务摘要 | 有 / 无 |
| 只读说明 |  |

### 8.2 投影规则

1. 注册合法 `BizDatasetDefinition` 后，`source_key=biz_tableset` 自动返回卡片。
2. 前端只消费服务端字段，不维护数据集名单、分组、状态或动作映射。
3. action 字段为空时显示只读，不出现“去操作”。
4. action 类型和 key 均来自后端；前端不得固定按 `dataset_action` 跳转。
5. 一张 Biz 表查询失败不能导致整个 Biz 页面永久 loading；错误必须能定位到具体卡片或明确返回整体失败原因。

## 9. 硬需求追溯账本

| ID | 硬需求 | 代码点 | 正向测试 | 反向测试 | 真实验收 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| `BIZ-001` | Definition 注册后自动出现卡片 |  |  |  |  | 未开始 |
| `BIZ-002` | 物理表、中文名、分组由单一事实源返回 |  |  |  |  | 未开始 |
| `BIZ-003` | 新鲜度使用正确业务语义 |  |  |  |  | 未开始 |
| `BIZ-004` | 手动任务只复用正式 maintenance action |  |  |  |  | 未开始 |
| `BIZ-005` | 自动任务只读取服务端能力契约 |  |  |  |  | 未开始 |
| `BIZ-006` | 观测失败不影响业务生产和事务 |  |  |  |  | 未开始 |
| `BIZ-007` | 页面轮询不触发大表昂贵扫描 |  |  |  |  | 未开始 |

## 10. 测试门禁

### 10.1 定义与架构

- key/table 唯一。
- 定义字段完整，未知 query/policy 拒绝。
- action 绑定存在且目标表一致。
- control/staging 表不能误注册。
- `src/ops` 不依赖 `src/biz` 或 orchestrator。

### 10.2 查询与 API

- API 返回卡片且字段来自 Definition。
- 业务日期、发布状态、构建时间和空表语义正确。
- 无昂贵 `count(*)` 或无索引全表轮询。
- 单卡观测异常处理符合约定。

### 10.3 手动与自动任务

- `manual_enabled=True` 的 action 出现在手动任务并能创建 TaskRun。
- `manual_enabled=False` 或无 action 的卡片没有操作入口。
- `schedule_enabled=True` 才能配置自动任务。
- 自动任务参数、时间策略、去重和执行器注册有正反测试。
- TaskRun 状态写失败不得回滚业务数据。

### 10.4 前端

- 卡片名称、表名、状态、分组和顺序正确。
- `maintenance_action` 链接正确。
- 只读卡片不显示操作按钮。
- 自动任务徽标来自 API，不由页面猜测。

## 11. 最小真实验收

| 验收项 | 结果与证据 |
| --- | --- |
| Prod 物理对象存在 |  |
| 最新业务日期与 SQL 只读结果一致 |  |
| 最近构建时间与正式 producer 一致 |  |
| 卡片状态与定义策略一致 |  |
| 手动任务入口可用或明确只读 |  |
| 自动任务状态与 `ops.schedule` 一致 |  |
| 业务 API/页面读取不受影响 |  |
| 轮询查询性能可接受 |  |

生产验收只允许只读查询和页面核对；任何重建、清表、补数据或任务执行都必须另行获得明确指令。

## 12. 交付清单

- [ ] Biz 数据集开发文档已完成并评审。
- [ ] `BizDatasetDefinition` 已登记。
- [ ] 生产入口和 target table 已对账。
- [ ] 观测 query 与 freshness policy 已对账。
- [ ] 手动任务能力已验证或明确不适用。
- [ ] 自动任务能力已验证或明确不适用。
- [ ] 后端、前端、架构测试通过。
- [ ] 文档完整性检查通过。
- [ ] 生产只读验收完成。
- [ ] 文档状态已更新为真实状态。
