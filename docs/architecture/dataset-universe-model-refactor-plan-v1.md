# index_weight 对象池最小收口方案 v1

- 状态：已完成（2026-05-03，代码已落地）
- 本轮范围：只处理 `index_weight`
- 不在本轮处理：`index_daily`、`dc_member`、`ths_member`、`stk_mins`、`biying_*` 等其他对象池链路
- 关联代码：
  - [index_weight DatasetDefinition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/index_series.py)
  - [DatasetUnitPlanner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)

---

## 1. 改造前问题（已收口）

`index_weight` 改造前 Definition 写的是：

```python
"planning": {
    "universe_policy": "none",
    "unit_builder_key": "build_index_weight_units",
}
```

但真实执行行为不是“无对象池”。

当前 `build_index_weight_units` 的行为是：

1. 如果用户传了 `index_code`，就按用户传入的指数代码执行。
2. 如果用户没传 `index_code`，就隐式查一批指数代码：
   - 先查 `ops.index_series_active(resource='index_weight')`
   - 如果为空，再查 `core_serving.index_basic` 中未终止指数
3. 然后按每个指数代码生成一个 unit。

这会造成两个问题：

1. 看 Definition 会误以为 `index_weight` 不使用对象池。
2. 真实对象池来源和优先级藏在 custom builder 里，后续审计和维护都容易漏。

当前代码已收口为：

```python
"planning": {
    "universe_policy": "pool",
    "universe": {
        "request_field": "index_code",
        "override_fields": ("index_code",),
        "sources": (
            {"type": "ops_index_series_active", "resource": "index_weight"},
            {"type": "core_index_basic_active"},
        ),
    },
    "unit_builder_key": "build_index_weight_units",
}
```

---

## 2. 本轮目标

本轮只做 `index_weight` 的最小收口：

1. `none` 不再表达“无对象池”，它只能表示未定义或历史未迁移。
2. `index_weight` 明确使用 `universe_policy = "pool"`。
3. `index_weight` 的对象池规则只声明当前必须的 3 类信息：
   - 请求字段是什么
   - 用户填了什么字段时不查对象池
   - 默认对象池从哪里来，按什么顺序查

本轮不设计通用大模型，不新增未来暂时用不到的字段。

---

## 3. 最小模型

### 3.1 `universe_policy`

本轮只需要两个有效业务值：

| 值 | 含义 |
| --- | --- |
| `no_pool` | 明确不按对象池展开 |
| `pool` | 明确按对象池展开 |

`none` 只表示未定义或历史未迁移，不作为业务语义使用。

### 3.2 `planning.universe`

`index_weight` 只需要以下字段：

```python
"universe": {
    "request_field": "index_code",
    "override_fields": ("index_code",),
    "sources": (
        {"type": "ops_index_series_active", "resource": "index_weight"},
        {"type": "core_index_basic_active"},
    ),
}
```

字段含义：

| 字段 | 含义 |
| --- | --- |
| `request_field` | 对象池查出来的值，最终写入哪个源接口请求参数。`index_weight` 是 `index_code`。 |
| `override_fields` | 用户填了这些字段时，就直接按用户输入执行，不再查默认对象池。 |
| `sources` | 用户没填时，按顺序查哪些对象池来源。 |

本轮明确不新增：

| 不新增字段 | 原因 |
| --- | --- |
| `entity_type` | 当前 `index_weight` 不需要用它驱动执行。 |
| `source_filter_fields` | 当前 `index_weight` 没有对象池筛选字段。 |
| `anchor_scope` | 当前 `index_weight` 的指数池不依赖日期。 |
| `empty_behavior` | 当前查不到对象池就报错，不需要配置化。 |

---

## 4. `index_weight` 目标定义

目标 Definition 形态：

```python
"planning": {
    "universe_policy": "pool",
    "universe": {
        "request_field": "index_code",
        "override_fields": ("index_code",),
        "sources": (
            {"type": "ops_index_series_active", "resource": "index_weight"},
            {"type": "core_index_basic_active"},
        ),
    },
    "enum_fanout_fields": (),
    "enum_fanout_defaults": {},
    "pagination_policy": "offset_limit",
    "page_limit": 6000,
    "unit_builder_key": "build_index_weight_units",
}
```

说明：

1. `request_field=index_code` 是因为 Tushare `index_weight` 接口参数名就是 `index_code`。
2. `override_fields=("index_code",)` 表示用户手动选择指数代码时，只跑用户选择的指数。
3. `sources` 保留当前真实行为：先查专用 active 池，再查 `index_basic` 未终止指数。
4. `unit_builder_key` 本轮可以暂时保留，因为 `index_weight` 还有自然月窗口逻辑；但它不能再自己隐藏对象池来源。

---

## 5. Planner 目标行为

本轮 planner 只需要支持 `index_weight` 的最小行为：

1. 如果 `universe_policy = "pool"`，读取 `planning.universe`。
2. 如果请求参数里存在 `override_fields`，直接用用户传入值生成 unit。
3. 如果用户没传，按 `sources` 顺序查对象池。
4. 查到对象池后，把每个值写入 `request_field`，生成 unit。
5. 所有来源都查不到时，返回明确的 `universe_empty` 规划错误。

对应到 `index_weight`：

```text
用户传 index_code
-> 只生成这些 index_code 的 units

用户没传 index_code
-> 查 ops.index_series_active(resource='index_weight')
-> 如果为空，查 core_serving.index_basic 未终止指数
-> 每个 code 生成一个 index_code unit
```

---

## 6. 实施步骤

### M1：补最小结构

1. 在 `DatasetPlanningDefinition` 增加可选 `universe` 字段。
2. 暂只支持 `request_field / override_fields / sources`。
3. 不引入其他通用字段。

### M2：修改 `index_weight` Definition

1. `universe_policy` 从 `none` 改为 `pool`。
2. 增加 `planning.universe`。
3. 保持日期模型、request builder、分页策略不变。

### M3：调整 `index_weight` unit 规划

1. `build_index_weight_units` 不再自己决定对象池来源。
2. 对象池来源从 `definition.planning.universe` 读取。
3. 继续保留自然月窗口相关行为，不改日期模型。

### M4：补测试

至少覆盖：

1. 用户传 `index_code` 时，不查默认对象池。
2. 用户不传 `index_code` 时，先用 `ops_index_series_active`。
3. active 池为空时，fallback 到 `core_index_basic_active`。
4. 两个来源都为空时，返回 `universe_empty`。
5. 生成的 source request params 仍是 `index_code + start_date + end_date`。

---

## 7. 明确不做

本轮不做：

1. 不迁移所有 `universe_policy="none"` 的数据集。
2. 不处理 `index_daily`、`dc_member`、`ths_member`。
3. 不设计通用对象池大模型。
4. 不新增暂时没有消费者的字段。
5. 不改变 `index_weight` 的自然月窗口模型。

`index_daily` 这类现有对象池链路后续单独处理，不能混在本轮 `index_weight` 修复里。
