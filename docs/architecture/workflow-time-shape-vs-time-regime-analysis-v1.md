# Workflow 时间形状与时间制度分析 v1

状态：已部分落地（M2 已完成）  
最后更新：2026-05-05  
适用范围：`src/ops/**` workflow 时间输入、`src/foundation/ingestion/**` 数据集维护计划主链

---

## 1. 目标

澄清当前 workflow 时间语义里的一个根问题：

```text
point / range / none
```

到底是什么，为什么当前会产生歧义，以及后续应从哪里切入做最小成本收口。

本分析文档是上位依据，不直接定义某一个具体 workflow 的步骤清单。

---

## 2. 结论先说

当前 workflow 时间语义混乱，不是因为 `point / range / none` 这三个词本身有问题，而是因为系统把两层不同的概念混在了一起：

1. **时间形状**
   - `point`
   - `range`
   - `none`
2. **时间制度**
   - 交易日
   - 自然日
   - no-time 默认语义

当前代码里的问题是：

```text
point 且未显式给日期
```

被框架默认解释成了：

```text
截至当前自然日的最近开市日
```

这说明当前 `point` 已经不只是“单点时间输入”，而是被掺进了“交易日默认制度”。

---

## 3. 两个概念必须拆开

### 3.1 时间形状（time shape）

时间形状只回答一个问题：

```text
调用方这次给的是单点、区间，还是不给时间。
```

定义如下：

| 形状 | 含义 |
| --- | --- |
| `point` | 一个单点时间锚 |
| `range` | 一个显式时间窗口 |
| `none` | 调用方不提供时间边界 |

它不应该隐含：

1. 交易日还是自然日
2. 今天、昨天、最近交易日
3. `ann_date`、`pub_date`、`trade_date` 的源接口字段差异

### 3.2 时间制度（time regime）

时间制度回答的是另一个问题：

```text
当系统需要理解、校验、补全或默认生成时间时，应按哪种日历和规则处理。
```

当前实际存在的制度至少有：

| 时间制度 | 示例 |
| --- | --- |
| 交易日制度 | 最近开市日、仅允许交易日、按交易日区间展开 |
| 自然日制度 | 今天、自然日区间、月末自然日 |
| no-time 制度 | 不给时间，按对象自身默认 no-time 语义执行 |

---

## 4. 当前代码链路审计

### 4.0 代码链全景表

当前 workflow 时间语义主链可以分成 8 段：

| 段位 | 代码位置 | 当前职责 | 当前问题 |
| --- | --- | --- | --- |
| 1. catalog 输出 | `src/ops/queries/catalog_query_service.py` | 把 workflow 参数暴露给目录接口 | 只暴露参数，不表达默认时间制度 |
| 2. 手动任务目录 | `src/ops/queries/manual_action_query_service.py` | 把 workflow 参数转成 `time_form` | 当前 workflow `trade_date` 文案默认是交易日 |
| 3. 手动任务提交 | `src/ops/services/manual_action_service.py` | 把页面输入转成 workflow `time_input` | 仍统一写入 `trade_date/start_date/end_date` 公共槽位 |
| 4. schedule / task run 创建 | `src/ops/services/task_run_service.py` | workflow 缺省时间输入生成 | 当前只区分 `point/range/none`，不区分默认时间制度 |
| 5. workflow step 分发 | `src/ops/runtime/task_run_dispatcher.py` | 父任务 `time_input` 透传给 step | 本层本来不该猜业务时间制度 |
| 6. dataset action 预处理 | `src/ops/runtime/task_run_dispatcher.py` | `point` 且缺日期时补默认日期 | 当前默认补“截至今天的最近开市日” |
| 7. resolver / validator | `src/foundation/ingestion/resolver.py`、`validator.py` | 公共时间槽位映射到数据集语义 | 这层设计基本正确，不应承接 workflow 默认制度 |
| 8. unit planner / request builder | `src/foundation/ingestion/unit_planner.py`、`request_builders.py` | 生成 unit 和源接口参数 | 这层只该消费已明确的时间意图 |

M2 的切入点必须优先落在第 4-6 段，不能把问题扩散到第 7-8 段。

### 4.1 workflow 只传一份公共时间输入

当前 workflow 的父任务只保存一份统一的 `time_input`，step 继承这份输入。

涉及代码：

1. `src/ops/services/task_run_service.py`
2. `src/ops/runtime/task_run_dispatcher.py`

这意味着：

1. workflow 层本身不直接理解每个数据集细节
2. workflow 只是把时间意图下发给 step

这层设计本身是合理的。

### 4.2 dataset action 主链负责具体语义落地

当前数据集维护主链已经具备“公共时间槽位 -> 数据集具体语义”的归一化能力。

例如：

1. `namechange`
   - workflow / task run 里仍可以用公共槽位 `trade_date`
   - validator/resolver 会再把它映射成 `ann_date`
2. `st`
   - 继续用 `trade_date/start_date/end_date` 这一组公共槽位表达 `pub_date`

涉及代码：

1. `src/foundation/ingestion/resolver.py`
2. `src/foundation/ingestion/validator.py`
3. `src/foundation/ingestion/request_builders.py`

这说明：

**workflow 层不需要直接懂源接口字段。**

### 4.3 当前歧义真正发生在 workflow 默认时间生成层

当前问题集中在两处：

1. workflow 未显式给时间时，`TaskRunCommandService` 会为某些 workflow 默认生成：

```json
{"mode": "point"}
```

2. workflow step 落到 dataset action 前，如果是 `point` 且没有具体日期，`TaskRunDispatcher` 会自动补：

```text
截至当前自然日的最近开市日
```

涉及代码：

1. `src/ops/services/task_run_service.py`
   - `_default_workflow_time_input()`
2. `src/ops/runtime/task_run_dispatcher.py`
   - `_prepare_dataset_action_request()`
   - `_resolve_default_trade_date()`

这一步才是把“时间形状”污染成“交易日制度”的地方。

### 4.4 手动任务目录已经部分表达了自然日 / 交易日差异

当前手动任务目录并不是完全不区分自然日与交易日。

对于 dataset action：

1. `ManualActionQueryService` 会根据 `DatasetDefinition.date_model` 区分：
   - `trade_date`
   - `calendar_date`
   - `trade_date_range`
   - `calendar_date_range`
2. `namechange` 这类 `ann_date_or_start_end` 数据集，point 模式甚至会直接标记 `date_field="ann_date"`

这说明：

1. dataset action 目录层已经在表达“时间制度”
2. 真正没有分开的，是 workflow 路径

换句话说：

当前问题不是整个系统从头到尾都不区分自然日与交易日，而是 **workflow 路由仍停留在“只看参数名 trade_date”的旧层级**。

### 4.5 workflow 手动任务路由当前固定按“交易日日期控件”表达

`ManualActionQueryService._time_form_from_params()` 当前只要看到 workflow 参数里有：

```text
trade_date
```

就会固定生成：

1. `control = trade_date`
2. `selection_rule = trading_day_only`
3. 描述文案 = “指定单个交易日”

这说明：

1. 当前 workflow 手动路由天然偏交易日
2. 如果新增 natural_day workflow，只在 `action_catalog.py` 加参数还不够
3. 还需要让 workflow 路由能表达“同样是 point，但它是自然日 point”

这是 M2 必须覆盖的链路，不然后端逻辑改对了，手动任务页文案和控件语义仍然是错的。

---

## 5. 当前“最近开市日”到底是什么

当前运行时默认补值逻辑，不区分中午、收盘后、夜间。

它的真实语义是：

```text
按 Asia/Shanghai 当前自然日 today，
从 TradeCalendar 中取 trade_date <= today 的最后一个开市日。
```

所以：

1. 如果今天和昨天都是交易日
2. 你今天中午触发
3. 返回今天
4. 你今天晚上触发
5. 还是返回今天

它不是“最近有数据的交易日”，也不是“收盘后最近交易日”。

更准确的人话应该是：

```text
截至当前自然日的最近开市日
```

---

## 6. 为什么这会影响新增 workflow

因为当前 workflow 时间处理框架是通用的。

只要一个新 workflow 满足：

1. 使用 `point`
2. 没有显式给具体日期
3. 没有专门覆盖默认时间制度

它就会自动吃到“最近开市日”的默认补值逻辑。

这对交易日 workflow 是合理的，例如：

1. `daily_market_close_maintenance`
2. `daily_moneyflow_maintenance`

但对 natural_day workflow 就是错的。

举例：

如果一个自然日 workflow 在周日触发，正确语义应是：

```text
处理本地自然日周日
```

而不是：

```text
处理上一个开市交易日周五
```

---

## 7. 正确的架构原则

后续收口必须遵守以下原则：

### 7.1 `point / range / none` 只表示输入形状

它们只表达：

1. 一个点
2. 一个范围
3. 不给时间

不允许再隐含：

1. 最近交易日
2. 今天
3. 公告日
4. 月末

### 7.2 workflow 层只负责自己的默认时间制度

workflow 可以定义：

1. 若调用方不给时间，我默认怎么取时间
2. 这个默认取值按交易日制度，还是自然日制度

但 workflow 不负责：

1. 源接口参数怎么拼
2. 某数据集的 `ann_date/pub_date/trade_date` 差异

### 7.3 数据集具体时间字段仍由 DatasetActionResolver 主链处理

也就是：

1. workflow 提供公共时间意图
2. `DatasetActionResolver + Validator + RequestBuilder` 再按 `DatasetDefinition` 落到具体语义

这条分层不应被打破。

---

## 8. 最小切入点

本问题不建议从“重写 point/range/none 全模型”切入，因为成本太高、影响链太长。

建议的最小切入点是：

### 8.1 先不改时间形状协议

保留现有：

1. `mode=point`
2. `mode=range`
3. `mode=none`
4. 公共时间槽位 `trade_date/start_date/end_date`

### 8.2 只在 workflow 默认时间生成层引入“时间制度”区分

最小目标只做两类默认制度：

1. 交易日默认制度
   - 维持现有交易日 workflow 行为
2. 自然日默认制度
   - 为新 natural_day workflow 提供本地自然日默认值

必要时再保留：

3. no-time 透传制度

这样可以做到：

1. 现有 dataset action 主链不动
2. 现有 point/range/none API 契约不大改
3. 先把 workflow 层的核心歧义收掉

---

## 9. M2 改动允许面与禁止面

### 9.1 M2 必须审计并允许改动

1. `src/ops/action_catalog.py`
   - 为 workflow 定义默认时间制度事实
2. `src/ops/queries/manual_action_query_service.py`
   - workflow 路由的时间控件、选择规则、文案
3. `src/ops/services/manual_action_service.py`
   - workflow 手动提交流程是否仍只按交易日语义组装 point/range
4. `src/ops/services/task_run_service.py`
   - workflow 默认 `time_input` 生成
5. `src/ops/runtime/task_run_dispatcher.py`
   - workflow step 落 dataset action 前的 point 默认补值逻辑

### 9.2 M2 原则上不应改动

1. `src/foundation/ingestion/resolver.py`
2. `src/foundation/ingestion/validator.py`
3. `src/foundation/ingestion/unit_planner.py`
4. `src/foundation/ingestion/request_builders.py`
5. `DatasetDefinition` 主模型结构

原因：

这些层当前承接的是“已明确时间意图 -> 数据集具体语义”的职责，不是 workflow 默认时间制度的根因点。

只有在代码审计发现某个 workflow 修复必须穿透到这些层时，才允许单独评审扩大范围。

---

## 10. 现有测试门禁审计

当前与 M2 直接相关的测试至少包括：

### 10.1 目录与 workflow 规格

1. `tests/test_ops_action_catalog.py`
   - 校验 workflow 参数与 `workflow_profile`

### 10.2 手动任务目录与提交

1. `tests/web/test_ops_manual_actions_api.py`
   - 当前已经断言：
     - `workflow:daily_market_close_maintenance` 的 point/range 控件
     - dataset action 自然日控件与 `ann_date` 行为

这意味着 M2 一旦引入 natural_day workflow，必须同步补：

1. 新 workflow 的 `time_form`
2. 自然日 point/range 的控件与文案

### 10.3 自动任务与 schedule

1. `tests/web/test_ops_schedule_api.py`
2. `tests/web/test_ops_runtime.py`

当前已经存在明确行为：

1. `daily_moneyflow_maintenance` 自动任务缺省时间输入会生成：
   - `{"mode": "point"}`
2. 交易日 workflow 的 schedule 路径已被接受为现行行为

这意味着 M2 必须保证：

1. 现有交易日 workflow 测试继续通过
2. 新增 natural_day workflow 行为用新测试单独覆盖

---

## 11. M2 必须达成的最小效果

不管具体代码怎么写，M2 至少必须满足以下结果：

1. workflow 继续使用 `point/range/none` 作为时间形状
2. workflow 可以额外表达自己的默认时间制度
3. 交易日 workflow 保持现有默认行为
4. natural_day workflow 的 point 默认值变成“调度本地自然日”
5. 手动任务页对 natural_day workflow 的 point/range 文案与控件必须改成自然日语义
6. dataset action 主链不因为本轮改动被重新定义

---

## 12. 影响面分层

### 9.1 本轮最小影响面

只触达：

1. `src/ops/action_catalog.py`
2. `src/ops/services/task_run_service.py`
3. `src/ops/runtime/task_run_dispatcher.py`
4. workflow 相关文档与测试

### 9.2 本轮不触达

不应直接扩大到：

1. `DatasetDefinition` 结构重写
2. `DatasetTimeInput` 协议重写
3. 手动任务全量交互改版
4. request builder 大改

---

## 13. 与当前三个任务组的关系

### 10.1 workflow 架构升级

本分析文档属于这一组。

目标：

1. 先把 workflow 时间形状和时间制度拆清楚
2. 找到最小切入点

### 10.2 五个新数据集接入

这组是需求开发，不应与本分析文档混写。

目标：

1. 数据集定义
2. 存储模型
3. 同步链路
4. 手动/自动能力

### 10.3 工作流对接

这组建立在前两组之后。

目标：

1. 哪些数据集接到现有 workflow
2. 哪些数据集接到新 workflow
3. workflow 默认时间制度如何选用

---

## 14. 本轮建议

当前最稳妥的推进顺序是：

1. 先完成 workflow 时间制度收口的架构与实现
2. 再完成 5 个新数据集的开发接入
3. 最后做 workflow 对接

原因：

1. 不先收口 workflow 默认时间制度，新 natural_day workflow 上线后仍会被交易日默认补值污染
2. 不先完成数据集接入，workflow 对接也没有真实目标对象可挂

---

## 15. 关联文档

1. [基础数据自然日维护工作流方案 v1（待评审）](/Users/congming/github/goldenshare/docs/ops/ops-workflow-reference-data-natural-day-maintenance-development-v1.md)
2. [运维工作流目录与实现清单](/Users/congming/github/goldenshare/docs/ops/ops-workflow-catalog-v1.md)
3. [手动维护动作模型收敛方案 v2](/Users/congming/github/goldenshare/docs/ops/ops-manual-action-model-alignment-plan-v2.md)

---

## 16. M2 落地结果

本轮 M2 已落地以下最小能力：

1. `WorkflowDefinition` 新增 workflow 时间制度事实：
   - `trade_open_day`
   - `natural_day`
   - `none`
2. workflow 手动任务目录现在能根据 workflow 时间制度输出：
   - `trade_date/trade_date_range`
   - 或 `calendar_date/calendar_date_range`
3. workflow 自动任务在 natural-day 场景下，到点创建 `TaskRun` 时会直接生成本地自然日 `trade_date`
4. 现有交易日 workflow 的默认行为保持不变

本轮没有落地：

1. 新 natural-day workflow 本体
2. `namechange` / `st` 的 workflow 对接
3. 五个新数据集的实际接入
