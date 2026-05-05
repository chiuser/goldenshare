# 基础数据自然日维护工作流方案 v1

状态：已完成（M4.1 已落地 workflow 本体与对接）  
最后更新：2026-05-05  
适用范围：`src/ops/action_catalog.py`、`docs/ops/ops-workflow-catalog-v1.md`

---

## 0. 上位依据

本方案只负责定义一个具体 workflow，不重复展开 workflow 时间语义的总架构分析。

上位依据：

- [Workflow 时间形状与时间制度分析 v1](/Users/congming/github/goldenshare/docs/architecture/workflow-time-shape-vs-time-regime-analysis-v1.md)

本方案默认接受以下前提：

1. `point / range / none` 只是时间形状
2. natural_day workflow 不能继续吃“最近开市日”的默认补值
3. workflow 只表达公共时间意图，具体数据集字段映射仍由 `DatasetActionResolver` 主链处理

推进时机：

1. M2 负责把 workflow 时间制度切口收出来
2. M4.1 已基于这条切口落地真实 workflow
3. 前置条件 `namechange`、`st` 已在 M4 完成接入并可独立执行

---

## 1. 基本信息

- Workflow Key：`reference_data_natural_day_maintenance`
- Workflow 显示名：`基础数据自然日维护`
- 负责人：待实现时补充
- 关联需求/任务：为 A 股基础数据中按自然日维护的数据集提供独立工作流
- 本轮目标数据集：
  - `namechange`
  - `st`

命名说明：

1. 不使用“每日更新”作为正式显示名，因为“每日”容易和“交易日每日”混淆。
2. 不使用“公告/事件型”作为工作流命名依据，因为决定 workflow 归属的关键不是内容名称，而是时间制度。
3. 显示名明确写成“自然日”，目的是把它与 `daily_market_close_maintenance` 的交易日口径彻底区分开。

---

## 2. 设计目标与边界

### 2.1 目标

建立一个最小可用的自然日基础数据维护 workflow，用来承接当前这类需求：

1. 数据集属于 `reference_data / 基础主数据`
2. 维护时间轴是 `natural_day`
3. 日常运行方式是 `point` 增量维护，必要时支持 `range` 补跑
4. 不应被“最近交易日”默认值污染

### 2.2 非目标

本方案不做以下事情：

1. 不调整 `reference_data_refresh` 的定位。
2. 不把 `bak_basic` 并入本工作流。
3. 不新增泛化的“所有自然日数据集统一工作流体系”。
4. 不改手动任务整体交互。
5. 不新增新的 `calendar_policy` 体系。
6. 不修改业务数据表、DatasetDefinition 主结构或 ingestion 主链。
7. 不顺手接入新闻、公告、审计等其他不在本轮目标内的数据集。

### 2.3 为什么需要新 workflow

当前现有 workflow 分成三类：

1. `reference_data_refresh`
   - 无参数
   - 适合 `none/snapshot` 型基础主数据
2. `daily_market_close_maintenance`
   - 交易日驱动
   - 适合 `trade_open_day` 型数据集
3. `index_*`
   - 指数专项区间维护

当前缺的不是“公告工作流”，而是：

```text
natural_day + point/range
```

这一类数据的日常维护 workflow。

`namechange` 与 `st` 当前不适合塞进现有 workflow，不是因为它们叫“公告/事件”，而是因为它们的时间制度是自然日，不是交易日，也不是无时间快照。

---

## 3. 当前代码审计结论

### 3.1 现有 workflow 的时间默认行为

当前 workflow 若满足以下条件：

1. `workflow.parameters` 包含 `trade_date`
2. `workflow_profile == "point_incremental"`
3. 自动任务触发时未显式提供日期

系统会先生成：

```json
{"mode": "point"}
```

随后在 workflow step 落到 dataset action 前，被运行时补成“最近交易日”。

涉及代码：

1. `src/ops/services/task_run_service.py`
   - `_default_workflow_time_input()`
2. `src/ops/runtime/task_run_dispatcher.py`
   - `_prepare_dataset_action_request()`
   - `_run_dataset_action_plan()`

这套逻辑对 `daily_market_close_maintenance` 是对的，但对自然日 workflow 是错的。

本方案不是去重写 `point / range / none`，而是为这个具体 workflow 落一个最小的“自然日默认时间制度”切口。

### 3.2 `namechange` 与 `st` 的时间归一化能力

当前主链已经具备这两个数据集所需的时间归一化能力：

1. workflow 层仍可统一使用公共时间槽位：
   - `trade_date`
   - `start_date`
   - `end_date`
2. `DatasetActionResolver + DatasetRequestValidator` 会按各自 `date_model.input_shape` 再归一化：
   - `namechange`：`trade_date -> ann_date`
   - `st`：继续使用 `trade_date/start_date/end_date` 这组槽位表达 `pub_date`

因此，本 workflow 不需要额外发明：

1. `ann_date` workflow 参数
2. `pub_date` workflow 参数
3. 新的 workflow 时间模型

这符合当前主链约束：

- workflow 只表达用户时间意图
- 具体数据集如何映射到源接口参数，仍由 `DatasetActionResolver` 和 request builder 决定

---

## 4. Workflow 定义

### 4.1 顶层定义

建议新增：

```python
WorkflowDefinition(
    key="reference_data_natural_day_maintenance",
    display_name="基础数据自然日维护",
    description="按自然日维护 A 股基础数据中的日常事件类与历史资料类数据。",
    parameters=(NATURAL_DAY_PARAM, START_DATE_PARAM, END_DATE_PARAM),
    workflow_profile="point_incremental",
    default_schedule_policy="natural_day_daily",
    schedule_enabled=True,
    manual_enabled=True,
)
```

说明：

1. `workflow_profile` 继续使用 `point_incremental`
   - 手动单日维护与自动日常维护都还是“单点增量”
2. `default_schedule_policy` 新增最小值 `natural_day_daily`
   - 只解决“自动任务默认日期如何生成”的问题
   - 不扩展成新的通用日期策略系统

### 4.2 工作流参数

建议新增一个 workflow 专用参数常量：

```python
NATURAL_DAY_PARAM = ActionParameter(
    key="trade_date",
    display_name="处理日期",
    param_type="date",
    description="只处理一个自然日。",
)
```

说明：

1. `key` 仍然使用 `trade_date`
   - 保持当前 workflow 公共时间槽位与前后端类型不变
2. 但文案不能继续写“交易日”
   - 否则用户在自然日 workflow 中会被误导

`START_DATE_PARAM` 与 `END_DATE_PARAM` 可继续复用现有定义。

---

## 5. 步骤编排清单

| 序号 | step_key | 显示名 | action_key | depends_on | default_params |
|---:|---|---|---|---|---|
| 1 | `namechange` | 股票曾用名 | `namechange.maintain` | 无 | `{}` |
| 2 | `st` | ST 风险警示事件 | `st.maintain` | 无 | `{}` |

补充说明：

1. 当前 runtime 仍按顺序执行 workflow step。
2. 这两个步骤之间没有业务依赖，不需要引入额外参数覆盖。
3. 顺序固定即可，本轮不做并行化设计。

为什么先 `namechange` 后 `st`：

1. 两者都属于 A 股基础数据自然日维护
2. 先放历史名称，再放风险警示，符合“基础资料 -> 状态事件”的阅读顺序
3. 该顺序不影响执行正确性，只保证目录稳定与详情页阅读稳定

---

## 6. 时间语义与调度规则

### 6.1 手动执行

手动执行只支持当前已有两种模式：

1. `point`
   - 用户明确填写一个自然日
2. `range`
   - 用户明确填写开始日期和结束日期

不支持：

1. `none`
2. 自动兜底“最近交易日”
3. 自动兜底“今天”

原因：

1. 手动任务必须由用户明确表达时间意图
2. 不能让 workflow 查询层或页面自己猜日期

### 6.2 自动调度

自动任务使用最小新增策略：

```text
default_schedule_policy = natural_day_daily
```

语义：

1. 若 workflow 自动任务没有显式固定 `trade_date`
2. scheduler 到点触发时
3. 后端使用 `scheduled_at + timezone` 计算本地自然日
4. 直接生成：

```json
{
  "mode": "point",
  "trade_date": "YYYY-MM-DD"
}
```

这样 workflow step 拿到的就是明确日期，不会再掉进“最近交易日补值”逻辑。

这正是上位文档里说的：

```text
先保留 point 这种时间形状，
只把 workflow 默认时间制度从交易日补值中拆出来。
```

### 6.3 区间补跑

当用户手动用 workflow 做历史补跑时：

```json
{
  "mode": "range",
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD"
}
```

这组参数原样下传到 step，再由各数据集自己的 `DatasetActionResolver` 归一化。

### 6.4 为什么不直接复用交易日默认逻辑

因为它会把 natural_day workflow 的“单日但未显式给日期”错误解释成：

```text
最近开市交易日
```

这会造成两个问题：

1. 周末/节假日自然日任务无法表达真实业务日期
2. workflow 名义上是自然日维护，实际上却偷偷回落到交易日制度

这类定义与执行不一致的问题，本轮必须避免。

---

## 7. 代码变更范围

本方案实现时只允许改以下范围：

### 7.1 必改

1. `src/ops/action_catalog.py`
   - 新增 workflow 定义
   - 新增 `NATURAL_DAY_PARAM`
2. `src/ops/services/task_run_service.py`
   - 为 workflow 自动任务新增 `natural_day_daily` 的默认 `time_input` 生成逻辑
3. `docs/ops/ops-workflow-catalog-v1.md`
   - 新增 workflow 条目
4. `docs/ops/ops-api-reference-v1.md`
   - 若 catalog / schedule 输出说明有变化，补齐文档

### 7.2 原则上不改

1. `src/foundation/ingestion/**`
2. `src/foundation/datasets/**`
3. 前端页面组件结构
4. 其他 existing workflow

例外：

只有在实现时发现当前前后端 workflow 时间表单无法显示该新 workflow 参数文案时，才允许做最小文案修正，但不得扩大为新一轮交互改造。

---

## 8. 测试计划

### 8.1 单元/目录测试

1. `tests/test_ops_action_catalog.py`
   - 新 workflow 注册成功
   - 参数、步骤、默认调度策略符合预期
2. `tests/web/test_ops_catalog_api.py`
   - `/api/v1/ops/catalog` 正确返回新 workflow

### 8.2 调度与运行时测试

1. `tests/web/test_ops_schedule_api.py`
   - 自动任务创建后，workflow 的默认时间策略为自然日本地日期
2. `tests/web/test_ops_runtime.py`
   - workflow 单日触发时，不再回落到最近交易日
   - `namechange` step 能正确走到 `ann_date`
   - `st` step 能正确保留自然日 point/range 语义

### 8.3 回归测试

必须确保：

1. `daily_market_close_maintenance` 仍保持最近交易日默认逻辑
2. `reference_data_refresh` 不受影响
3. 手动任务现有 dataset action 路径不受影响

---

## 9. 发布与回滚

### 9.1 发布前检查

1. 新 workflow 目录出现在 `/api/v1/ops/catalog`
2. 手动触发单日模式时，`TaskRun.time_input.trade_date` 为用户指定自然日
3. 自动触发时，`TaskRun.time_input.trade_date` 为调度本地自然日，不是最近交易日
4. `namechange` 与 `st` 两个 step 都能成功创建计划并执行

### 9.2 回滚方式

若本 workflow 上线后发现问题：

1. 先停用该 workflow 对应自动任务
2. 回滚 workflow 定义与 `natural_day_daily` 时间解析代码
3. 不需要回滚业务数据表结构，因为本方案不改表

---

## 10. 文档同步清单

- [ ] 更新 `docs/ops/ops-workflow-catalog-v1.md`
- [x] 更新 `docs/README.md` 索引
- [ ] 如 catalog / schedule 契约说明有变化，更新 `docs/ops/ops-api-reference-v1.md`
- [ ] 提交信息明确标注 workflow 变更范围

---

## 11. 本轮结论

当前最小且合理的方案是：

1. 新增一个独立 workflow：
   - `reference_data_natural_day_maintenance`
2. 首批只纳入两个数据集：
   - `namechange`
   - `st`
3. 通过最小新增的 `natural_day_daily` 默认时间策略，解决自动任务把自然日误补成最近交易日的问题

本方案不处理：

1. `bak_basic`
2. 其他 natural_day 数据集
3. 新的 workflow 并行模型
4. 新的 UI 大改

先把这条 workflow 做对，再讨论是否扩充承载对象。
