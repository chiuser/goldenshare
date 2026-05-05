# 指数基础信息 index_basic 源站对齐修复方案 v1

- 状态：实施中
- 数据集 key：`index_basic`
- 源站文档：`docs/sources/tushare/指数专题/0094_指数基本信息.md`
- 当前实现：`src/foundation/datasets/definitions/index_series.py`
- 目标：让 `index_basic` 的 DatasetDefinition、请求计划、表模型、DAO 与源站事实一致，避免指数池缺数或参数不可用。

---

## 1. 背景

`index_basic` 是指数类数据集的基础池。后续 `index_daily`、`index_weekly`、`index_monthly`、`index_weight` 等能力会依赖它提供指数代码范围。

当前实现已经能维护基础字段，但与 Tushare 源文档相比存在几个关键偏差：参数声明不完整、市场枚举没有建模、默认全量如果误设市场会被错误缩窄、日期模型和表结构语义不够干净。

这类问题不能靠前端或 Ops 页面补救，应在 DatasetDefinition 和 ingestion 主链一次性收口。

---

## 2. 源站事实

源文档定义：

| 类别 | 字段 / 参数 |
| --- | --- |
| API | `index_basic` |
| 输入参数 | `ts_code`、`symbol`、`name`、`market`、`publisher`、`category`、`limit`、`offset` |
| 输出字段 | `ts_code`、`name`、`fullname`、`market`、`publisher`、`index_type`、`category`、`base_date`、`base_point`、`list_date`、`weight_rule`、`desc`、`exp_date` |
| 市场枚举 | `MSCI`、`CSI`、`SSE`、`SZSE`、`CICC`、`SW`、`OTH` |
| 分页参数 | `limit` / `offset` |
| 日期参数 | 无 |

已确认口径：`market` 什么都不传时，接口返回全量；如果显式传 `market=SSE`，才只返回上交所指数。因此默认维护不需要按 market 扇出，必须保留“无业务参数 + limit/offset 分页取全量”的主路径。

---

## 3. 当前实现差异

| 编号 | 差异点 | 当前实现 | 风险 |
| --- | --- | --- | --- |
| D1 | `symbol` 参数缺失 | DatasetDefinition 未声明，request builder 未处理 | 无法按指数代码简码查询；严格模式下传入会被拒绝 |
| D2 | `market/name/publisher/category` 未声明 | request builder 支持部分参数，但 DatasetDefinition 只声明 `ts_code` | 前端/API 无法合法传入这些参数，形成“代码里支持、契约里不支持”的断裂 |
| D3 | `market` 参数口径容易误用 | 不传 `market` 时走全量；显式传 `SSE` 时只取上交所 | 如果代码或配置错误地把默认 market 填成 `SSE`，指数池会不完整 |
| D4 | 市场枚举未建模 | DatasetDefinition 未声明 `market` 可选枚举 | 用户无法合法按市场筛选，测试也不能约束可选值 |
| D5 | 日期模型不够干净 | `date_model.input_shape=none`，但 `input_model.time_fields` 仍有 `trade_date`，action 支持 `point` | 用户语义上容易误解为需要日期；快照类主数据不应暴露日期锚点 |
| D6 | raw 层日期字段被转成 Date | 源文档类型为 str，raw/core 均使用 Date | raw 层不完全保留源站原始形态；异常日期格式可能导致整行拒绝 |
| D7 | active 指数池 fallback 未排除终止指数 | DAO `get_active_indexes()` 直接返回全部行 | 当 `ops.index_series_active` 为空并触发 fallback 时，指数 serving 门禁可能包含已终止指数，增加空结果和噪音 |

---

## 4. 目标口径

### 4.1 DatasetDefinition

`index_basic` 应定义为无时间维度快照类数据集：

| 字段 | 目标 |
| --- | --- |
| `date_model.date_axis` | `none` |
| `date_model.bucket_rule` | `not_applicable` |
| `date_model.window_mode` | `none` |
| `date_model.input_shape` | `none` |
| `capabilities.maintain.supported_time_modes` | `("none",)` |
| `input_model.time_fields` | 空 |
| `planning.pagination_policy` | `offset_limit` |
| `planning.page_limit` | 保持当前 `6000`，除非实测证明源站上限更低 |

### 4.2 输入参数

DatasetDefinition 必须显式声明源站可用业务过滤参数：

| 参数 | 类型 | 多值 | 是否暴露给手动维护 | 处理方式 |
| --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | 是 | 原样大写 |
| `symbol` | list | 是 | 是 | 多值逗号拼接传给源站 |
| `name` | string | 否 | 是 | 原样 trim |
| `market` | enum | 否 | 是 | 不填表示全量；填写时按单一市场筛选 |
| `publisher` | string | 否 | 是 | 原样 trim |
| `category` | string | 否 | 是 | 原样 trim |

`limit`、`offset` 继续作为分页内部参数，由 source client 统一追加，不进入用户可填写过滤项。

### 4.3 市场参数与分页全量

目标默认行为：

1. 用户不填任何业务参数时，生成 1 个无业务过滤 unit。
2. 该 unit 通过 `offset_limit` 分页取全量：`offset=0, limit=6000` 开始，直到返回行数 `< limit`。
3. 用户显式选择 `market` 时，只按该 market 过滤。
4. 本轮不做默认 market 扇出；全量语义由“不传 market”表达。
5. 禁止把 `market=SSE` 写成默认值，否则会把全量错误缩窄为上交所指数。

### 4.4 表模型

建议重建 `raw_tushare.index_basic` 与 `core_serving.index_basic`。

原因：

1. 当前还没正式上线，可以停机清理，不需要兼容旧结构。
2. raw 层应尽量保留源站字段形态，避免源站日期异常导致 raw 行丢失。
3. serving 层可以继续保留规范化日期，服务查询更方便。

建议字段：

| 字段 | raw_tushare.index_basic | core_serving.index_basic |
| --- | --- | --- |
| `ts_code` | string，主键 | string，主键 |
| `name` | string | string |
| `fullname` | string | string |
| `market` | string，索引 | string，索引 |
| `publisher` | string，索引 | string，索引 |
| `index_type` | string | string |
| `category` | string，索引 | string，索引 |
| `base_date` | string | date |
| `base_point` | decimal | decimal |
| `list_date` | string | date |
| `weight_rule` | string | string |
| `desc` | text | text |
| `exp_date` | string | date |
| `api_name` | string | 不需要 |
| `fetched_at` | timestamp | 不需要 |
| `raw_payload` | text/json | 不需要 |

如果实现时判断 raw 层继续 Date 更符合当前仓库统一写法，也必须在方案实施前明确说明，并补“异常日期不导致整批失败”的测试。

### 4.5 DAO active 语义

`IndexBasicDAO.get_active_indexes()` 应只返回当前有效指数：

1. `exp_date is null` 视为有效。
2. `exp_date >= today` 视为有效。
3. `exp_date < today` 视为已终止，不进入默认指数池。

如果某些源站把 `exp_date` 填成特殊字符串或异常值，应在 raw -> serving 归一化阶段处理，不应让 DAO 自己理解源站脏值。

---

## 5. 实施步骤

### M1：补 DatasetDefinition 契约

1. 移除 `index_basic` 的 `trade_date` time field。
2. 把 action 支持模式改为 `none`。
3. 补齐 `symbol/name/market/publisher/category` filters。
4. 给 `market` 配置源站枚举值，但不加入默认 fanout。
5. 保持 `enum_fanout_fields=()` 与 `enum_fanout_defaults={}`，除非后续明确需要按市场拆 unit。

验收：

1. registry 测试能证明参数、日期模型、market 枚举完整。
2. 手动任务页显示为无日期维度。

### M2：补请求构造

1. `_index_basic_params` 支持 `symbol`。
2. `market` 只来自用户显式选择；默认不传。
3. `category/name/publisher/ts_code` 来自合法 filters。
4. `limit/offset` 仍只由 source client 追加。

验收：

1. 默认请求计划生成 1 个无业务过滤 unit，`request_params={}`。
2. source client 对该 unit 自动追加 `offset/limit` 分页。
3. 指定 `market="CSI"` 时请求参数包含 `market=CSI`。
4. 指定 `symbol=["000300","000001"]` 时请求参数正确。

### M3：重建表模型与迁移

1. 新增 Alembic 迁移，drop/recreate `raw_tushare.index_basic`。
2. 新增 Alembic 迁移，drop/recreate `core_serving.index_basic`。
3. raw 层日期字段按 string 存储。
4. serving 层日期字段按 date 存储。

验收：

1. ORM 字段与迁移一致。
2. `goldenshare init-db` 或迁移测试通过。
3. 空库可建表。

### M4：补 raw/core 分层写入规则

实现前已确认：当前 writer 的 `raw_core_upsert` 原本会把同一份 `rows_normalized` 同时写 raw/core。如果只在 DatasetDefinition 里声明 raw=str、serving=date，会形成“定义看似正确、写入仍共用值”的假收口。

本轮采用的规则：

1. `index_basic` normalizer 不再把 `base_date/list_date/exp_date` 提前转成 date，保留源站字符串。
2. writer 在写入具体 DAO 前按目标表模型列类型做转换。
3. 写 raw DAO 时，raw 表日期列是 string，因此保留源站字符串。
4. 写 core DAO 时，core 表日期列是 date，因此转换为 date。
5. 该能力是 `raw_core_upsert` 的目标表类型适配，不新增 `index_basic` 专用兼容路径。

验收：

1. normalizer 测试证明 `index_basic` 的 raw 日期字段仍为源站字符串。
2. writer 测试证明同一行写 raw/core 时，raw 保留字符串、core 转 date。
3. 如果日期字段非法，错误发生在目标表类型转换和写入阶段，不允许通过伪造 Definition 字段隐藏问题。

### M5：DAO active 语义收口

1. `get_active_indexes()` 改为只返回未终止指数。
2. 补单元测试覆盖 `exp_date is null`、未来日期、过去日期。
3. 审计 `index_daily/index_weekly/index_monthly/index_weight` 依赖该方法的影响。

### M6：回归与验收

最小测试：

1. `pytest -q tests/test_dataset_definition_registry.py`
2. `pytest -q tests/test_dataset_action_resolver.py`
3. `pytest -q tests/test_dataset_normalizer.py`
4. `pytest -q tests/test_extended_daos.py tests/test_extended_models.py`
5. `pytest -q tests/architecture/test_dataset_runtime_registry_guardrails.py`

业务验收：

1. 小窗口执行 `index_basic` 维护，只选 `CSI` 验证请求、分页、落库。
2. 默认维护验证为 1 个无业务过滤 unit，并通过分页取完所有返回行。
3. 维护后检查 `core_serving.index_basic` 覆盖多个实际有数据的市场，避免误传 `SSE` 导致缺数。
4. 再执行一个依赖指数池的小范围 `index_daily`，确认代码池可用。

---

## 6. 需要你确认的决策点

| 编号 | 决策点 | 建议 |
| --- | --- | --- |
| D1 | 是否重建 `raw_tushare.index_basic` 和 `core_serving.index_basic` | 建议重建，避免旧字段语义继续污染 |
| D2 | raw 层日期字段是否按源站 str 保留 | 建议 raw=str，serving=date |
| D3 | 默认是否按 market 扇出 | 不扇出；默认不传 market，依靠无参分页取全量 |
| D4 | `symbol` 是否作为多值筛选暴露 | 建议暴露，源文档明确支持多值 |
| D5 | `get_active_indexes()` 是否排除已终止指数 | 建议排除，以免后续行情维护请求废弃指数 |

---

## 7. 非目标

1. 本轮不改 Lake Console 的 Parquet Lake 实现。
2. 本轮不改指数行情类数据集的业务口径，只修复它们依赖的指数基础池。
3. 本轮不新增兼容逻辑，不保留旧表结构兼容路径。
4. 本轮不连接远程数据库；远程清表或重建必须等方案确认后单独执行。

---

## 8. 完成定义

只有同时满足以下条件，才认为本需求完成：

1. DatasetDefinition 与源站输入/输出事实一致。
2. 默认维护不会传入 `market=SSE`，而是无业务参数分页取全量。
3. 表结构、ORM、迁移、DAO、normalizer、writer 行为一致。
4. `get_active_indexes()` 语义真实表达“当前有效指数”。
5. 手动任务、自动任务、数据源卡片仍能正确展示和发起维护。
6. 所有最小测试与小窗口业务验收通过。
