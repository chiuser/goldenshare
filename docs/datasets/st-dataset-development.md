# ST 风险警示事件（`st`）数据集开发说明（M4 已完成）

## 0. 架构基线与目标

本数据集必须与仓内已有的 `stock_st` 明确区分：

1. `stock_st` 对应的是 `doc_id=397` 的“每日 ST 股票列表”。
2. 本文对应的是 `doc_id=423` 的 `st` 接口，表示 ST 风险警示事件历史。
3. Raw 层必须保留源站字段名，尤其保留源字段拼写 `st_tpye`，不得私自修正；`pub_date`、`imp_date` 这类稳定日期字符串允许直接落 `date`。
4. 不做“先兼容再收口”；V1 从一开始就按独立数据集设计。

参考模板：[数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)

---

## 1. 源站事实

- 源站接口：Tushare `st`
- 本地源站文档：[0423_ST风险警示板股票.md](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/基础数据/0423_ST风险警示板股票.md)
- `docs_index.csv` 记录：`doc_id=423`，`api_name=st`
- 单次限制：最大 `1000` 条
- 输入维度：`ts_code`、`pub_date`、`imp_date`
- 输出维度：事件公告日期、实施日期、类型、原因、详细说明

### 1.1 输入参数

| 参数名 | 类型 | 必填 | 源站含义 | 类别 | 运营侧是否填写 | 接入设计 |
| --- | --- | --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | 股票代码 | 过滤 | 是 | 可选过滤 |
| `pub_date` | string | 否 | 发布日期 | 源端日期字段 | 否 | 不作为维护主轴；默认不传 |
| `imp_date` | string | 否 | 实施日期 | 源端日期字段 | 否 | 不作为运营输入；默认不传 |
| `limit` | integer | 否 | 单页行数 | 分页 | 否 | 固定传 `1000` |
| `offset` | integer | 否 | 分页偏移量 | 分页 | 否 | 自动递增 |

### 1.2 输出字段

| 字段名 | 源类型 | 是否落 raw | 备注 |
| --- | --- | --- | --- |
| `ts_code` | string | 是 | 股票代码 |
| `name` | string | 是 | 股票名称 |
| `pub_date` | string | 是 | 发布日期；源站为 `YYYYMMDD` 字符串，raw 层直接落 `date` |
| `imp_date` | string | 是 | 实施日期；源站为 `YYYYMMDD` 字符串，raw 层直接落 `date` |
| `st_tpye` | string | 是 | 源站原始拼写，不能改名 |
| `st_reason` | string | 是 | 变更原因 |
| `st_explain` | string | 是 | 详细原因说明 |

### 1.3 源端行为判断

1. 源接口支持不传 `pub_date` / `imp_date`，按 `limit/offset` 分页返回全集。
2. `pub_date` / `imp_date` 是源端结果字段，不作为本仓维护主轴。
3. V1 只保留 `ts_code` 作为对象过滤；不暴露日期过滤，避免把事件全集错误拆成按日期 fan-out。
4. 分页必须开启。

---

## 2. 基本信息

- 数据集 key：`st`
- 中文显示名：`ST 风险警示事件`
- 所属定义文件：建议新增到 `src/foundation/datasets/definitions/reference_master.py`
- 所属域：`reference_data`
- 所属域中文名：`基础主数据`
- 数据源：`tushare`
- 源站 API：`st`
- 是否对外服务：是
- 是否多源融合：否
- 是否纳入自动任务：是，纳入 `reference_data_refresh`，按默认全集分页刷新
- 是否纳入日期完整性审计：否
- Ops 展示分组 key：`reference_data`
- Ops 展示分组名称：`A股基础数据`
- Ops 展示分组顺序：`1`

---

## 3. DatasetDefinition 设计

### 3.1 `identity`

```python
"identity": {
    "dataset_key": "st",
    "display_name": "ST 风险警示事件",
    "description": "维护 Tushare ST 风险警示事件历史数据。",
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
    "api_name": "st",
    "source_fields": ("ts_code", "name", "pub_date", "imp_date", "st_tpye", "st_reason", "st_explain"),
    "source_doc_id": "tushare.st",
    "request_builder_key": "_st_params",
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
    "not_applicable_reason": "ST 风险警示事件按源接口默认全集分页刷新，不按发布日期或实施日期扇出。",
}
```

说明：

1. `st` 不按业务日期维护；`pub_date` / `imp_date` 只作为源数据字段保存。
2. 手动任务默认不填写时间条件。
3. `not_applicable` 表示 freshness / 完整性不按连续日期做红绿灯判断。

### 3.5 `input_model`

| 字段 | 类型 | 是否必填 | 默认值 | 是否多选 | 中文名 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | 无 | 否 | 股票代码 | 可选过滤 |

### 3.6 `storage`

```python
"storage": {
    "raw_dao_name": "raw_st",
    "core_dao_name": "raw_st",
    "target_table": "core_serving_light.st",
    "delivery_mode": "raw_with_serving_light_view",
    "layer_plan": "raw->serving_light_view",
    "std_table": None,
    "serving_table": "core_serving_light.st",
    "raw_table": "raw_tushare.st",
    "conflict_columns": ("row_key_hash",),
    "write_path": "raw_only_upsert",
}
```

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

1. 默认生成 1 个 snapshot unit。
2. unit 内通过 `limit/offset` 分页拉完整源端结果。
3. 不按 `pub_date` 或 `imp_date` 拆 unit。

### 3.8 `normalization`

```python
"normalization": {
    "date_fields": ("pub_date", "imp_date"),
    "decimal_fields": (),
    "required_fields": ("ts_code", "pub_date", "st_tpye", "row_key_hash"),
    "row_transform_name": "_st_row_transform",
}
```

说明：`row_transform` 负责生成 `row_key_hash`，同时保留源字段 `st_tpye` 的原始命名。

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
    "progress_label": "st",
    "observed_field": None,
    "audit_applicable": False,
},
"quality": {
    "reject_policy": "record_rejections",
    "required_fields": ("ts_code", "pub_date", "st_tpye", "row_key_hash"),
},
"transaction": {
    "commit_policy": "unit",
    "idempotent_write_required": True,
    "write_volume_assessment": "ST 风险警示事件按源接口默认全集分页拉取；一个执行计划只生成一个 snapshot unit，分页拉完整后按 unit 提交。",
}
```

---

## 4. 表结构、索引与 DAO 设计

### 4.1 Raw 表：`raw_tushare.st`

- ORM：建议新增 `src/foundation/models/raw/raw_st.py`
- DAO：建议新增 `raw_st`
- 主键：`id bigserial`
- 幂等键：`row_key_hash`

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `id` | bigserial | 否 | 内部主键 |
| `row_key_hash` | varchar(64) | 否 | 唯一幂等键 |
| `ts_code` | varchar(16) | 否 | 股票代码 |
| `name` | varchar(128) | 是 | 股票名称 |
| `pub_date` | date | 否 | 发布日期直接落 `date` |
| `imp_date` | date | 是 | 实施日期直接落 `date` |
| `st_tpye` | varchar(64) | 否 | 源站原始拼写 |
| `st_reason` | text | 是 | 事件原因 |
| `st_explain` | text | 是 | 事件详细说明 |

索引建议：

```sql
create unique index uq_raw_tushare_st_row_key_hash
on raw_tushare.st(row_key_hash);

create index idx_raw_tushare_st_ts_code
on raw_tushare.st(ts_code);

create index idx_raw_tushare_st_pub_date
on raw_tushare.st(pub_date);

create index idx_raw_tushare_st_imp_date
on raw_tushare.st(imp_date);
```

### 4.2 Target View：`core_serving_light.st`

- ORM：建议新增 `src/foundation/models/core_serving_light/st.py`
- 与 raw 保持同字段名，`pub_date`、`imp_date` 继续使用 `date`，不修正 `st_tpye`

---

## 5. 执行链路设计

### 5.1 请求构造

- `request_builder_key`：`_st_params`
- 默认：不传 `pub_date` / `imp_date`
- 可选：若填写 `ts_code`，透传为大写股票代码

### 5.2 Unit 规划

- `unit_builder_key`：`generic`
- unit 维度：snapshot
- `progress_context`：可选 `ts_code`

### 5.3 分页

- `limit=1000`
- `offset=0/1000/...`
- 结束条件：返回 `< 1000`

### 5.4 Writer

- `write_path`：`raw_only_upsert`
- 冲突列：`row_key_hash`

---

## 6. Ops 派生

1. 页面展示名必须是“ST 风险警示事件”，不能简写成 `st`。
2. 手动任务时间控件显示“不填写时间条件”。
3. `pub_date` / `imp_date` 不作为运营输入项。
4. 数据源页、手动任务页、自动任务页统一展示到 `reference_data / A股基础数据`。
5. 数据状态只展示最近成功任务迹象，不按业务日新鲜度判断。

---

## 7. 测试与验收清单

1. `DatasetDefinition` 注册
2. `request_builder`：默认不传日期参数，可选 `ts_code`
3. `unit_planner`：默认 1 个 snapshot unit
4. `row_transform`：`row_key_hash` 生成且保留 `st_tpye`
5. `manual-actions`：展示文案不与 `stock_st` 混淆

---

## 8. 当前未决点

1. 是否允许后续追加“仅按 `imp_date` 驱动的独立动作”，本文档暂不纳入；V1 不按日期驱动。
