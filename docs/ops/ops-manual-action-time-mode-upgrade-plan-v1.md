# Ops 手动维护时间模式升级方案 v1

更新时间：2026-05-03  
状态：已实施（2026-05-03）  
适用范围：`src/foundation/ingestion/*`、`src/ops/queries/manual_action_query_service.py`、`src/ops/schemas/manual_action.py`、`src/ops/services/manual_action_service.py`、`frontend/src/pages/ops-v21-task-manual-tab.tsx`

---

## 1. 一句话结论

本次将两个问题合并处理：

1. 从架构上，补齐手动维护时间模式模型，允许同一个维护对象正式表达 `none + point + range`。
2. 从数据集落地上，把 `trade_cal` 的“无显式日期”从隐藏行为改成正式契约：不再偷偷走最近 30 天，而是明确表示“不传日期，分页拉全集”。

这两个问题不适合拆开做。因为如果只修 `trade_cal`，前端手动任务模型仍然无法准确表达；如果只升级手动任务模型，又会继续保留 `trade_cal` 当前“定义一套、运行一套”的架构偏差。

---

## 2. 当前已确认事实

### 2.1 `trade_cal` 当前定义与运行不一致

`trade_cal` 当前 `DatasetDefinition` 明确声明：

1. `date_model.window_mode = point_or_range`
2. `input_shape = trade_date_or_start_end`
3. `supported_time_modes = ("point", "range")`

但运行时实际存在第三条隐藏路径：

1. `time_input.mode=none` 会被 resolver 转成 `snapshot_refresh`
2. validator 没有拒绝这个未声明的 `none`
3. request builder 又把它偷偷改写成“最近 30 个自然日”

结果就是：

1. `DatasetDefinition` 没说支持 `none`
2. 但主链实际上允许 `none`
3. 而且 `none` 的真实语义还不是“全集”，而是“最近 30 天”

这不符合当前“`DatasetDefinition` 是单一事实源”的架构要求。

### 2.2 手动任务时间表单模型表达力不足

当前 `ManualActionTimeFormResponse` 结构是：

1. `control`
2. `default_mode`
3. `allowed_modes`
4. `selection_rule`
5. `point_label`
6. `range_label`

这套结构只能较好表达：

1. 只有 `none`
2. 只有 `point`
3. 只有 `range`
4. `point + range`

但不能优雅表达：

1. `none + point`
2. `none + range`
3. `none + point + range`

前端当前还有一个直接后果：

只要 `allowed_modes` 包含 `none`，页面就会把日期输入整体隐藏掉。  
这意味着后端即便返回 `["none", "point", "range"]`，前端也无法正确展示成三种可选模式。

### 2.3 `reference_data_refresh` 当前确实依赖了这个隐藏行为

`reference_data_refresh` 工作流没有时间参数，当前会以 `mode=none` 运行 `trade_cal` 这一步。  
也就是说，当前基础主数据刷新里的交易日历步骤，实际上跑的是“最近 30 天窗口”，不是“完整交易日历刷新”。

---

## 3. 本次目标

本次方案只做两件事：

1. 把“时间模式”从当前的弱表达模型，升级为可显式表达 mixed modes 的正式模型。
2. 用这套模型把 `trade_cal` 收口为正式支持 `none + point + range` 的数据集。

本次明确不做：

1. 不改自动任务主链
2. 不改 `ops/catalog` 主结构
3. 不改 TaskRun 详情页
4. 不改其他数据集的时间语义
5. 不重构执行器事务模型

---

## 4. 目标口径

### 4.1 `none` 的正式含义

以后 `time_input.mode=none` 只表示一件事：

不显式提供日期锚点，由数据集定义的 no-time 语义执行维护。

注意：

1. `none` 不是“最近几天”的代名词
2. `none` 不是“系统自己猜一个日期”的代名词
3. `none` 如果被支持，必须是数据集正式声明的能力
4. `none` 的真实请求参数必须可审计，不能藏在兜底逻辑里

### 4.2 `snapshot_refresh` 的边界

以后 `snapshot_refresh` 只允许在 action 正式声明支持 `none` 时进入。

也就是说：

1. `supported_time_modes` 不包含 `none` 的 action
2. 一旦收到 `mode=none`
3. validator 必须直接拒绝

不能再保留“先放进来，再看 request builder 怎么兜底”的路径。

### 4.3 `trade_cal` 的正式 no-time 语义

`trade_cal` 一旦正式支持 `none`，其 no-time 语义定义为：

1. 不传 `trade_date`
2. 不传 `start_date`
3. 不传 `end_date`
4. 保留 `exchange`
5. 按当前分页策略拉完整返回结果

这才是 `trade_cal` 的正式“全集刷新”。

---

## 5. 新的手动时间模式模型

## 5.1 为什么不能继续沿用旧 `time_form`

旧模型的问题不是字段少一点，而是结构本身有歧义：

1. `control` 是整个 action 级别的
2. `selection_rule` 也是整个 action 级别的
3. 但 `mode` 实际上是分支级别的

当同一个 action 同时支持多种 mode 时：

1. `none` 对应“无控件”
2. `point` 对应“单点日期”
3. `range` 对应“日期区间”

这三个分支的表单形态并不相同，所以不能再用一个 action 级别的 `control` 硬包住。

## 5.2 目标结构

把当前 `ManualActionTimeFormResponse` 改成“按 mode 明细化”的结构。

建议新结构：

```json
{
  "time_form": {
    "default_mode": "point",
    "modes": [
      {
        "mode": "none",
        "label": "全量刷新",
        "description": "不填写日期，按该维护对象的默认全量策略执行",
        "control": "none",
        "selection_rule": "none"
      },
      {
        "mode": "point",
        "label": "只处理一天",
        "description": "指定单个日期",
        "control": "calendar_date",
        "selection_rule": "calendar_day",
        "date_field": "trade_date"
      },
      {
        "mode": "range",
        "label": "处理一个时间区间",
        "description": "指定开始和结束日期",
        "control": "calendar_date_range",
        "selection_rule": "calendar_day",
        "date_field": "trade_date"
      }
    ]
  }
}
```

## 5.3 字段定义

### `time_form.default_mode`

表示页面初始默认选中的时间模式。

### `time_form.modes`

表示当前 action 实际支持的时间模式列表。

每个 mode item 必须完整表达：

1. `mode`
2. `label`
3. `description`
4. `control`
5. `selection_rule`
6. `date_field`（如适用）

### `control` 枚举

建议明确收口为以下枚举：

1. `none`
2. `trade_date`
3. `trade_date_range`
4. `calendar_date`
5. `calendar_date_range`
6. `month`
7. `month_range`
8. `month_window_range`

说明：

1. `trade_date*` 用于交易日语义
2. `calendar_date*` 用于自然日语义
3. `month*` 用于月份键或自然月窗口
4. `none` 表示该 mode 下不显示时间控件

### `selection_rule` 枚举

沿用当前已有口径，不新增第二套规则表：

1. `none`
2. `trading_day_only`
3. `week_last_trading_day`
4. `month_last_trading_day`
5. `calendar_day`
6. `week_friday`
7. `month_end`
8. `month_key`
9. `month_window`

---

## 6. 派生规则

## 6.1 dataset action

dataset action 的时间模式必须从两部分联合派生：

1. `DatasetDefinition.capabilities.supported_time_modes`
2. `DatasetDefinition.date_model`

派生原则：

1. `supported_time_modes` 决定“支持哪些 mode”
2. `date_model` 决定“每个 mode 的控件和日期规则”

### `trade_date_or_start_end`

1. `point` -> `trade_date` 或 `calendar_date`
2. `range` -> `trade_date_range` 或 `calendar_date_range`
3. 是否是交易日还是自然日，由 `date_axis` 决定

### `ann_date_or_start_end`

1. `point` -> `calendar_date`
2. `range` -> `calendar_date_range`
3. `date_field=ann_date`

### `month_or_range`

1. `point` -> `month`
2. `range` -> `month_range`

### `start_end_month_window`

1. `range` -> `month_window_range`

### `none`

1. `none` -> `control=none`

## 6.2 workflow manual route

workflow 的时间模式继续只从 `workflow.parameters` 派生，不继承步骤里某个 dataset 的能力。

这条规则必须保留。

原因：

1. workflow 是独立运维对象
2. 它暴露什么时间参数，应由 workflow 自己定义
3. 不能因为其中一个步骤支持 `point/range`，就把整个 workflow 自动升级成 `point/range`

因此：

1. `reference_data_refresh` 仍然是 `mode=none`
2. 它的手动执行页仍然不展示日期控件
3. 但其内部 `trade_cal` 步骤的 no-time 语义，会从“最近 30 天”改成“正式全量日历刷新”

---

## 7. `trade_cal` 收口方案

## 7.1 DatasetDefinition

把 `trade_cal.maintain.supported_time_modes` 从：

```text
("point", "range")
```

改为：

```text
("none", "point", "range")
```

这是正式契约修正，不是兼容补丁。

## 7.2 validator

调整规则：

1. `snapshot_refresh` 且 action 不支持 `none` -> 直接 reject
2. 删除当前 `pass` 放水逻辑

这样以后：

1. `mode=none` 是否允许，完全由 `supported_time_modes` 决定
2. resolver / validator / request builder 三层口径一致

## 7.3 request builder

`trade_cal` 请求构造改为：

1. `point`：`start_date=end_date=trade_date`
2. `range`：透传 `start_date/end_date`
3. `none`：不传日期字段，只传 `exchange`

必须删除当前“最近 30 个自然日”的隐藏兜底。

## 7.4 `reference_data_refresh` 影响

改完后，`reference_data_refresh` 的 `trade_cal` step 会变成：

1. 仍然 `mode=none`
2. 仍然无显式时间参数
3. 但真实语义从“最近 30 天”变成“完整交易日历刷新”

这会带来两个可预期变化：

1. 执行时长会比现在更长
2. 单次 unit 写入量会比现在更大

但执行模型本身不变：

1. 仍然是 `snapshot_refresh`
2. 仍然只生成 1 个 plan unit
3. 仍然在 unit 级提交事务

本方案不顺手改执行器事务模型，只修正语义与契约。

---

## 8. API 与前端改动范围

## 8.1 `GET /api/v1/ops/manual-actions`

需要改返回结构：

1. 删除旧 `time_form.control`
2. 删除旧 `time_form.allowed_modes`
3. 删除旧 `time_form.selection_rule`
4. 删除旧 `time_form.point_label`
5. 删除旧 `time_form.range_label`
6. 新增 `time_form.modes`

`POST /api/v1/ops/manual-actions/{action_key}/task-runs` 请求体不需要改。

原因：

1. 当前 `time_input.mode` 已经足够表达 `none/point/range`
2. 问题不在写接口，而在读接口的表单契约不够强

## 8.2 前端手动任务页

前端渲染逻辑改为：

1. 根据 `time_form.modes` 生成模式切换项
2. 当前选中哪个 mode，就渲染该 mode 对应的控件
3. `none` 只隐藏自己这一个 mode 下的时间控件
4. 不再因为 action 支持 `none`，就把整个 action 的日期输入全部隐藏

## 8.3 自动任务页

本次不处理自动任务页。

原因：

1. 自动任务页当前消费的是 `catalog` 和调度策略模型
2. 本次问题集中在手动任务 `time_form`
3. `trade_cal` 的实际 no-time 使用场景是 dataset action 手动任务和 `reference_data_refresh` workflow，不需要先动自动任务页

---

## 9. 代码复核后的影响面清单

本节基于当前代码逐项复核，不靠命名或历史印象。

## 9.1 必改后端文件

1. `src/foundation/datasets/definitions/reference_master.py`
作用：把 `trade_cal.maintain.supported_time_modes` 正式收口为 `none + point + range`。

2. `src/foundation/ingestion/validator.py`
作用：删除 `snapshot_refresh` 对未声明 `none` 的放水逻辑，恢复严格契约校验。

3. `src/foundation/ingestion/request_builders.py`
作用：删除 `trade_cal` 最近 30 天兜底，改成正式 no-time 请求。

4. `src/ops/schemas/manual_action.py`
作用：升级 `ManualActionTimeFormResponse` 契约，承接 `modes[]`。

5. `src/ops/queries/manual_action_query_service.py`
作用：从 `DatasetDefinition` / workflow 参数派生新的 `time_form.modes[]` 结构。

6. `src/ops/services/manual_action_service.py`
作用：提交时不再依赖旧 `allowed_modes/control`，而是按当前选中的 mode 明细解析。

## 9.2 必改前端文件

1. `frontend/src/shared/api/types.ts`
作用：同步 `/api/v1/ops/manual-actions` 的新响应类型。

2. `frontend/src/pages/ops-v21-task-manual-tab.tsx`
作用：这是当前 `time_form` 的主消费者，也是改动最大的位置。

重点会触及：

1. mode 切换项渲染
2. 日期控件选择逻辑
3. `none/point/range` 的请求体拼装
4. 默认模式、回填草稿、复制参数的恢复逻辑

## 9.3 必改测试与 smoke fixture

1. `tests/web/test_ops_manual_actions_api.py`
2. `frontend/src/pages/ops-v21-task-manual-tab.test.tsx`
3. `frontend/src/pages/ops-v21-task-center-page.test.tsx`
4. `frontend/e2e/support/smoke-fixtures.ts`

原因：

1. 这些测试和 fixture 当前都直接写死了旧 `time_form` 结构
2. 如果不一起改，测试会直接失真，甚至掩盖真实回归

## 9.4 本轮明确不受影响的链路

本轮复核后，以下链路不应进入修改范围：

1. `TaskRun` 表结构和任务详情 API
2. 自动任务页主链
3. `/api/v1/ops/catalog`
4. 数据源页、今日运行、freshness、数据集卡片、审计页
5. 数据库 migration

也就是说，本轮是“手动任务契约 + `trade_cal` 契约收口”，不是全站时间模型重构。

---

## 10. 专门风险评估

## 10.1 总体判断

总体风险级别：中等，可控。

不是因为改动目录很多，而是因为：

1. `/api/v1/ops/manual-actions` 是前后端共同依赖的契约
2. 手动任务页当前把“模式判断、控件选择、请求拼装”揉在了一起
3. `trade_cal` 语义修正会改变 `reference_data_refresh` 的真实执行行为

## 10.2 后端契约风险

风险级别：中。

风险点：

1. `ManualActionTimeFormResponse` 结构变化后，query / schema / service 三层必须同时改
2. workflow route 目前也依赖 `time_form.control` 解析月份与日期输入，不能只改 dataset action 路径
3. validator 一旦收紧 `snapshot_refresh`，必须确保所有真实使用 `mode=none` 的 action 都已正式声明 `none`

控制方式：

1. 先做 `/api/v1/ops/manual-actions` 消费者审计
2. 再改 schema 和 query 派生
3. 最后收紧 validator，并补 resolver/validator 测试

## 10.3 前端页面风险

风险级别：中。

风险点：

1. 当前页面把 `allowed_modes`、`control`、`selection_rule` 当作全局字段消费
2. 一旦切到 `modes[]`，默认模式、回填、复制参数、浏览器返回草稿恢复都要一起验证
3. 如果只改表单渲染，不改请求拼装，就会出现“看起来能选，提交不对”的功能性 bug

控制方式：

1. 前端先把“当前选中 mode”的视图模型收成单一事实源
2. 所有控件判断都从“当前 mode 定义”出发
3. 不在页面继续混用 action 级旧字段和 mode 级新字段

## 10.4 `trade_cal` 运行语义风险

风险级别：中。

风险点：

1. `reference_data_refresh` 的 `trade_cal` step 会从“最近 30 天”切到“完整交易日历刷新”
2. 当前执行器是单 unit 拉全页、聚合后统一写入并 commit
3. 因此这里增长的是“这个 step 的总请求量和单 unit 体量”，不是单纯改个 UI 文案

控制方式：

1. 把这次变更只限定在 `trade_cal`
2. 明确不顺手改执行器事务模型
3. 在 workflow 验收里单独验证 `reference_data_refresh`

## 10.5 最容易遗漏的点

这轮复核后，最容易漏掉的不是主代码，而是这些边角消费者：

1. `frontend/src/shared/api/types.ts`
2. `frontend/e2e/support/smoke-fixtures.ts`
3. `frontend/src/pages/ops-v21-task-center-page.test.tsx`
4. `tests/web/test_ops_manual_actions_api.py`

如果这些地方没一起更新，就很容易出现：

1. 页面本地能跑，测试全红
2. fixture 还是旧结构，导致 smoke 对真实接口形态失真
3. 契约变了，但测试没挡住错误回归

## 10.6 风险结论

本轮最大的风险，不是架构方向错，而是“改一半”：

1. 只改 `trade_cal`，不改 `time_form`
2. 只改 API，不改前端消费
3. 只改页面渲染，不改提交解析
4. 只改主代码，不改 fixture 和测试

所以实施时必须按单一主线一次收完整条链，不能做半套。

---

## 11. 里程碑

## M1：方案评审

交付：

1. 本文定稿
2. 明确 `trade_cal` 默认手动模式
3. 明确 `reference_data_refresh` 文案是否需要同步调整

## M2：后端契约收口

交付：

1. `trade_cal` 正式支持 `none`
2. validator 严格校验 `snapshot_refresh`
3. `trade_cal` 删除 30 天兜底逻辑
4. mixed modes 新 schema 落到 manual actions API

## M3：前端手动任务 mixed modes 支持

交付：

1. 手动任务页按 `modes[]` 渲染
2. `trade_cal.maintain` 可在“全量 / 单日 / 区间”之间切换
3. 其他现有 action 页面行为不回退

## M4：workflow 连带验收

交付：

1. `reference_data_refresh` 运行口径改为正式全量日历刷新
2. 任务结果和详情页文案不误导
3. docs / API reference 同步

---

## 12. 已拍板口径

## D1：`trade_cal.maintain` 手动任务默认模式

已确认：默认 `none`。

口径解释：

1. 打开手动任务页后，`trade_cal.maintain` 默认落在“全量刷新”
2. 用户仍可显式切换到单日或区间
3. 这与 `trade_cal` 的正式 no-time 语义保持一致

## D2：`reference_data_refresh` 文案

已确认：显式补一句“交易日历按完整日历刷新”。

落地要求：

1. workflow 文档说明必须补上
2. 如页面有对应帮助文案，也应同步保持一致
3. 不允许继续让“最近 30 天默认窗口”残留在描述里

---

## 13. 验证要求

后端至少执行：

```bash
pytest -q tests/web/test_ops_manual_actions_api.py
pytest -q tests/test_dataset_action_resolver.py
pytest -q tests/test_dataset_definition_registry.py
```

前端至少执行：

```bash
cd frontend && npm run typecheck
cd frontend && npm run test -- ops-v21-task-manual-tab.test.tsx
cd frontend && npm run build
```

文档改动必须执行：

```bash
python3 scripts/check_docs_integrity.py
```

---

## 14. 边界与后续

本次方案完成后，得到的是：

1. `mode=none` 正式化
2. mixed modes 手动任务模型补齐
3. `trade_cal` 与 `reference_data_refresh` 口径一致

本次完成后仍不在范围内的后续题：

1. 自动任务页是否也要升级成 mixed modes 模型
2. 其他数据集是否存在类似 `none` 隐藏语义
3. no-time 数据集的默认策略是否需要统一登记到数据集开发模板中
