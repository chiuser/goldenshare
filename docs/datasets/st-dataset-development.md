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
| `pub_date` | string | 否 | 发布日期 | 时间 | 是 | 选为 V1 主时间轴 |
| `imp_date` | string | 否 | 实施日期 | 过滤日期 | 是 | 保留为辅助过滤条件 |
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

1. 源接口没有 `start_date/end_date`，如果要做区间维护，只能按选定的主时间轴逐日 fan-out。
2. `pub_date` 更接近“事件产生 / 公告发生”的主时间轴，适合做增量维护。
3. `imp_date` 更适合作为辅助过滤条件，而不是第二套并行时间模型；否则会把一个数据集拆成两套时间主语。
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
- 是否纳入自动任务：是，建议按 `pub_date` 做日常增量
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
    "date_axis": "natural_day",
    "bucket_rule": "not_applicable",
    "window_mode": "point_or_range",
    "input_shape": "ann_date_or_start_end",
    "observed_field": "pub_date",
    "audit_applicable": False,
    "not_applicable_reason": "ST 风险警示事件不是每日必有数据的公告类事件，不按日完整性判断。",
}
```

说明：

1. V1 选 `pub_date` 作为主时间轴。
2. `imp_date` 保留为 filter，不另建第二套时间意图。
3. point 模式沿用 `ann_date_or_start_end` 这条既有链路进入 manual-actions / validator，再在 request builder 中映射到源接口参数 `pub_date`。
4. 手动任务日期控件仍按自然日选择；`not_applicable` 只表示 freshness / 完整性不按连续自然日做红绿灯判断。

### 3.5 `input_model`

| 字段 | 类型 | 是否必填 | 默认值 | 是否多选 | 中文名 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `trade_date` | date | 否 | 无 | 否 | 发布日期 | DatasetDefinition 统一时间槽位；manual-actions point 模式会映射为 `ann_date`，最终由 request builder 生成为 `pub_date` |
| `start_date` | date | 否 | 无 | 否 | 开始日期 | 区间维护开始日期，对应 `pub_date` |
| `end_date` | date | 否 | 无 | 否 | 结束日期 | 区间维护结束日期，对应 `pub_date` |
| `ts_code` | string | 否 | 无 | 否 | 股票代码 | 可选过滤 |
| `imp_date` | date | 否 | 无 | 否 | 实施日期 | 辅助过滤 |

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
    "unit_builder_key": "build_st_units",
}
```

说明：

1. `point`：1 个 `pub_date` 对应 1 个 unit。
2. `range`：按自然日逐日展开 `pub_date`。
3. 如果用户填写 `imp_date`，只是附加到每个 unit 请求上的过滤条件，不改变 unit 维度。

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
            "supported_time_modes": ("point", "range"),
        },
    ),
}
```

### 3.10 `observability` / `quality` / `transaction`

```python
"observability": {
    "progress_label": "st",
    "observed_field": "pub_date",
    "audit_applicable": False,
},
"quality": {
    "reject_policy": "record_rejections",
    "required_fields": ("ts_code", "pub_date", "st_tpye", "row_key_hash"),
},
"transaction": {
    "commit_policy": "unit",
    "idempotent_write_required": True,
    "write_volume_assessment": "单个事务只覆盖一个发布日的全部分页结果；区间维护按自然日拆 unit。",
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
- `point`：`pub_date=YYYYMMDD`
- `range`：unit builder 逐日展开，每个 unit 仍然只传一个 `pub_date`
- 若填写 `ts_code` / `imp_date`，一并透传

### 5.2 Unit 规划

- `unit_builder_key`：`build_st_units`
- unit 维度：`pub_date`
- `progress_context`：`pub_date`、可选 `ts_code`、可选 `imp_date`

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
2. 手动任务时间控件显示“发布日期 / 开始日期 / 结束日期”。
3. `imp_date` 作为筛选项，不作为第二主时间轴。
4. 数据源页、手动任务页、自动任务页统一展示到 `reference_data / A股基础数据`。
5. 数据状态只展示最近成功任务迹象，不按业务日新鲜度判断。

---

## 7. 测试与验收清单

1. `DatasetDefinition` 注册
2. `request_builder`：`trade_date -> pub_date`
3. `unit_planner`：区间按自然日展开 `pub_date`
4. `row_transform`：`row_key_hash` 生成且保留 `st_tpye`
5. `manual-actions`：展示文案不与 `stock_st` 混淆

---

## 8. 当前未决点

1. 是否允许后续追加“仅按 `imp_date` 驱动的独立动作”，本文档暂不纳入；V1 只认 `pub_date` 为主时间轴。
