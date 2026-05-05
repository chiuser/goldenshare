# 股票曾用名（`namechange`）数据集开发说明（M4 已完成）

## 0. 架构基线与目标

本数据集属于事件型历史资料：

1. Raw 表必须精准复刻源字段名；对语义明确、格式稳定的日期字符串字段允许直接落 `date`。
2. 维护动作统一为 `namechange.maintain`。
3. 本数据集不是按日期扇出的数据集。正确维护方式是默认不传时间参数，按源接口分页拉取全集。
4. 不额外复制 serving 物理表，采用 `raw -> core_serving_light view`。

参考模板：[数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)

---

## 1. 源站事实

- 源站接口：Tushare `namechange`
- 本地源站文档：[0100_股票曾用名.md](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/基础数据/0100_股票曾用名.md)
- `docs_index.csv` 记录：`doc_id=100`，`api_name=namechange`
- 接口说明：历史名称变更记录
- 源站支持输入：`ts_code`、`start_date`、`end_date`
- 源站支持分页：`limit`、`offset`

### 1.1 输入参数

| 参数名 | 类型 | 必填 | 源站含义 | 类别 | 运营侧是否填写 | 接入设计 |
| --- | --- | --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | 股票代码 | 代码 | 是 | 可选过滤 |
| `start_date` | string | 否 | 公告开始日期 | 源接口过滤 | 否 | V1 不作为运营时间模型；默认不传 |
| `end_date` | string | 否 | 公告结束日期 | 源接口过滤 | 否 | V1 不作为运营时间模型；默认不传 |
| `limit` | integer | 否 | 单页行数 | 分页 | 否 | 系统固定传，具体上限待实测 |
| `offset` | integer | 否 | 分页偏移量 | 分页 | 否 | 自动递增 |

### 1.2 输出字段

| 字段名 | 源类型 | 是否落 raw | 备注 |
| --- | --- | --- | --- |
| `ts_code` | string | 是 | 股票代码 |
| `name` | string | 是 | 证券名称 |
| `start_date` | string | 是 | 开始日期；源站为 `YYYYMMDD` 字符串，raw 层直接落 `date` |
| `end_date` | string | 是 | 结束日期，可能为空；raw 层直接落 `date` |
| `ann_date` | string | 是 | 公告日期；源站为 `YYYYMMDD` 字符串，raw 层直接落 `date` |
| `change_reason` | string | 是 | 变更原因 |

### 1.3 源端行为判断

1. 本接口支持不传任何业务过滤条件；此时源站返回历史名称变更全集，需要通过 `limit/offset` 分页拉完。
2. 源站返回的老历史记录可能没有 `ann_date`。如果用公告日期 `start_date/end_date` 过滤，会漏掉这类历史区间事实。
3. `namechange` 的核心事实是股票名称历史区间，不是“每天一个桶”的日频事实；不应按自然日、公告日或日期区间做 fan-out。
4. 源站可能返回重复业务行，写入侧通过 `row_key_hash` 保证幂等。重复源行会被识别为批内重复，不代表有效业务行丢失。
5. 源站文档没有给出单页最大返回条数，当前实现先按保守值 `page_limit=1000` 分页拉取。

---

## 2. 基本信息

- 数据集 key：`namechange`
- 中文显示名：`股票曾用名`
- 所属定义文件：建议新增到 `src/foundation/datasets/definitions/reference_master.py`
- 所属域：`reference_data`
- 所属域中文名：`基础主数据`
- 数据源：`tushare`
- 源站 API：`namechange`
- 是否对外服务：是
- 是否多源融合：否
- 是否纳入自动任务：是，按默认全集分页刷新；不按公告日增量维护
- 是否纳入日期完整性审计：否
- Ops 展示分组 key：`reference_data`
- Ops 展示分组名称：`A股基础数据`
- Ops 展示分组顺序：`1`

---

## 3. DatasetDefinition 设计

### 3.1 `identity`

```python
"identity": {
    "dataset_key": "namechange",
    "display_name": "股票曾用名",
    "description": "维护 Tushare 股票曾用名历史记录。",
    "aliases": (),
}
```

### 3.2 `domain`

```python
"domain": {
    "domain_key": "reference_data",
    "domain_display_name": "基础主数据",
    "cadence": "daily",
}
```

### 3.3 `source`

```python
"source": {
    "source_key_default": "tushare",
    "source_keys": ("tushare",),
    "adapter_key": "tushare",
    "api_name": "namechange",
    "source_fields": ("ts_code", "name", "start_date", "end_date", "ann_date", "change_reason"),
    "source_doc_id": "tushare.namechange",
    "request_builder_key": "_namechange_params",
    "base_params": {},
}
```

### 3.4 `date_model`

```python
"date_model": {
    "date_axis": "none",
    "bucket_rule": "not_applicable",
    "window_mode": "none",
    "input_shape": "none",
    "observed_field": None,
    "audit_applicable": False,
    "not_applicable_reason": "股票曾用名是历史区间事实，维护时按源接口默认全集分页刷新，不按公告日或自然日扇出。",
}
```

说明：`namechange` 的事实主轴是名称生效区间。源接口虽然提供公告日期过滤参数，但 V1 运营维护主链不使用它们作为时间模型，避免漏掉 `ann_date` 为空的历史记录。

### 3.5 `input_model`

| 字段 | 类型 | 是否必填 | 默认值 | 是否多选 | 中文名 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | 无 | 否 | 股票代码 | 可选过滤 |

说明：本数据集没有运营时间输入项。手动任务默认展示“按默认策略处理”，即不传日期参数并分页拉取。

### 3.6 `storage`

```python
"storage": {
    "raw_dao_name": "raw_namechange",
    "core_dao_name": "raw_namechange",
    "target_table": "core_serving_light.namechange",
    "delivery_mode": "raw_with_serving_light_view",
    "layer_plan": "raw->serving_light_view",
    "std_table": None,
    "serving_table": "core_serving_light.namechange",
    "raw_table": "raw_tushare.namechange",
    "conflict_columns": ("row_key_hash",),
    "write_path": "raw_only_upsert",
}
```

说明：`end_date` 可能为空，不适合做唯一键的一部分；使用 `row_key_hash` 做 null-safe 幂等键。

### 3.7 `planning`

```python
"planning": {
    "universe_policy": "none",
    "enum_fanout_fields": (),
    "enum_fanout_defaults": {},
    "pagination_policy": "offset_limit",
    "page_limit": 1000,
    "chunk_size": None,
    "max_units_per_execution": None,
    "unit_builder_key": "generic",
}
```

说明：

1. 当前实现先按保守值 `page_limit=1000` 分页拉取。
2. 源站文档仍未给出单页上限，后续若有实测结论，可再单独上调。
3. 不需要自定义 unit builder；每次维护只生成 1 个 snapshot unit，内部靠分页拉完整结果。

### 3.8 `normalization`

```python
"normalization": {
    "date_fields": ("start_date", "end_date", "ann_date"),
    "decimal_fields": (),
    "required_fields": ("ts_code", "name", "start_date", "row_key_hash"),
    "row_transform_name": "_namechange_row_transform",
}
```

`row_transform` 负责：

1. 生成 `row_key_hash`
2. 统一 `ts_code` 大写
3. 清理空白字符串
4. 日期字段交由标准日期解析链直接落成 `date`

### 3.9 `capabilities`

```python
"capabilities": {
    "actions": (
        {
            "action": "maintain",
            "manual_enabled": True,
            "schedule_enabled": True,
            "retry_enabled": True,
            "supported_time_modes": ("none",),
        },
    ),
}
```

### 3.10 `observability` / `quality` / `transaction`

```python
"observability": {
    "progress_label": "namechange",
    "observed_field": None,
    "audit_applicable": False,
},
"quality": {
    "reject_policy": "record_rejections",
    "required_fields": ("ts_code", "name", "start_date", "row_key_hash"),
},
"transaction": {
    "commit_policy": "unit",
    "idempotent_write_required": True,
    "write_volume_assessment": "股票曾用名按源接口默认全集分页拉取；一个执行计划只生成一个 snapshot unit，分页拉完整后按 unit 提交。",
}
```

---

## 4. 表结构、索引与 DAO 设计

### 4.1 Raw 表：`raw_tushare.namechange`

- ORM：建议新增 `src/foundation/models/raw/raw_namechange.py`
- DAO：建议新增 `raw_namechange`
- 主键：`id bigserial`
- 幂等键：`row_key_hash`

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `id` | bigserial | 否 | 内部主键 |
| `row_key_hash` | varchar(64) | 否 | 唯一幂等键 |
| `ts_code` | varchar(16) | 否 | 股票代码 |
| `name` | varchar(128) | 否 | 证券名称 |
| `start_date` | date | 否 | 开始日期直接落 `date` |
| `end_date` | date | 是 | 结束日期直接落 `date` |
| `ann_date` | date | 是 | 公告日期直接落 `date` |
| `change_reason` | text | 是 | 变更原因 |

索引建议：

```sql
create unique index uq_raw_tushare_namechange_row_key_hash
on raw_tushare.namechange(row_key_hash);

create index idx_raw_tushare_namechange_ts_code
on raw_tushare.namechange(ts_code);

create index idx_raw_tushare_namechange_ann_date
on raw_tushare.namechange(ann_date);
```

### 4.2 Target View：`core_serving_light.namechange`

- ORM：建议新增 `src/foundation/models/core_serving_light/namechange.py`
- 与 raw 保持相同字段名
- 与 raw 保持相同字段名；`start_date`、`end_date`、`ann_date` 继续使用 `date`

---

## 5. 执行链路设计

### 5.1 请求构造

- `request_builder_key`：`_namechange_params`
- `snapshot_refresh`：不传 `start_date/end_date`
- 默认请求参数：`{}`
- 如果填写 `ts_code`，仅透传 `ts_code`
- 不支持 `point/range`，不能把公告日期当作执行 fan-out 维度

### 5.2 Unit 规划

- `unit_builder_key`：`generic`
- `none`：1 个 snapshot unit
- `request_params`：默认 `{}`，填写股票代码时为 `{"ts_code": "000001.SZ"}`
- `progress_context`：最多展示 `ts_code`

### 5.3 分页

- `pagination_policy`：`offset_limit`
- `page_limit`：待实测确认
- 结束条件：返回 `< limit`

### 5.4 Writer

- `write_path`：`raw_only_upsert`
- 冲突列：`row_key_hash`

---

## 6. Ops 派生

1. 手动任务时间控件只显示“按默认策略处理”，不展示公告日期或区间选择。
2. `ts_code` 是可选过滤项。
3. 自动任务允许按默认全集分页刷新。
4. 数据源页、手动任务页、自动任务页统一展示到 `reference_data / A股基础数据`。
5. 数据状态只展示最近一次成功任务迹象，不以“业务日新鲜度”做红绿灯。
6. `reference_data_refresh` 工作流包含 `namechange`；`reference_data_natural_day_maintenance` 不再包含 `namechange`。

---

## 7. 测试与验收清单

1. `DatasetDefinition` 注册
2. `request_builder`：`none` 模式不传日期参数，只保留可选 `ts_code`
3. `unit_planner`：不切窗，不按天扇出，保持 1 个 snapshot unit
4. `normalizer`：`row_key_hash` 生成与空值处理
5. `writer`：`row_key_hash` 幂等 upsert
6. `manual-actions`：只展示默认策略和 `ts_code` 过滤项
7. `workflow`：基础主数据刷新包含 `namechange`；自然日维护工作流不包含 `namechange`

---

## 8. 当前未决点

1. 源站文档未给出单页最大返回量，当前保守使用 `page_limit=1000`；后续如要上调，必须实测。
2. 源站重复行目前仍会按批内重复写入拒绝计数展示，后续如要改成“去重提示”而不是“拒绝”，需要单独评估 writer 口径，不能只对页面改文案。
