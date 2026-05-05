# 北交所新旧代码对照（`bse_mapping`）数据集开发说明（待评审）

## 0. 架构基线与目标

本数据集是小体量基础快照数据，按当前主链接入：

1. `DatasetDefinition` 定义事实。
2. 动作统一为 `bse_mapping.maintain`。
3. Raw 层精确复刻源字段名；对语义明确、格式稳定的日期字符串字段允许直接落 `date`。
4. 不单独复制 core 物理表，采用 `raw -> core_serving_light view`。

参考模板：[数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)

---

## 1. 源站事实

- 源站接口：Tushare `bse_mapping`
- 本地源站文档：[0375_北交所新旧代码对照表.md](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/基础数据/0375_北交所新旧代码对照表.md)
- `docs_index.csv` 记录：`doc_id=375`，`api_name=bse_mapping`
- 单次限制：最大 `1000` 条
- 源站总量说明：总数据量 `300` 条以内

### 1.1 输入参数

| 参数名 | 类型 | 必填 | 源站含义 | 类别 | 运营侧是否填写 | 接入设计 |
| --- | --- | --- | --- | --- | --- | --- |
| `o_code` | string | 否 | 旧代码 | 过滤 | 是 | 可选过滤 |
| `n_code` | string | 否 | 新代码 | 过滤 | 是 | 可选过滤 |
| `limit` | integer | 否 | 单页行数 | 分页 | 否 | 固定传 `1000` |
| `offset` | integer | 否 | 分页偏移量 | 分页 | 否 | 自动递增 |

### 1.2 输出字段

| 字段名 | 源类型 | 是否落 raw | 备注 |
| --- | --- | --- | --- |
| `name` | string | 是 | 股票名称 |
| `o_code` | string | 是 | 原代码 |
| `n_code` | string | 是 | 新代码 |
| `list_date` | string | 是 | 上市日期；源站为 `YYYYMMDD` 字符串，raw 层直接落 `date` |

### 1.3 源端行为判断

1. 虽然总量很小，仍然按 `offset_limit` 统一实现分页链。
2. 不需要按日期、代码池或月份扇出。
3. 单次全量快照安全，可作为 `none` 模式数据集。

---

## 2. 基本信息

- 数据集 key：`bse_mapping`
- 中文显示名：`北交所新旧代码对照`
- 所属定义文件：建议新增到 `src/foundation/datasets/definitions/reference_master.py`
- 所属域：`reference_data`
- 所属域中文名：`基础主数据`
- 数据源：`tushare`
- 源站 API：`bse_mapping`
- 是否对外服务：是
- 是否多源融合：否
- 是否纳入自动任务：是，已并入 `reference_data_refresh`
- 是否纳入日期完整性审计：否
- Ops 展示分组 key：`reference_data`
- Ops 展示分组名称：`A股基础数据`
- Ops 展示分组顺序：`1`

---

## 3. DatasetDefinition 设计

### 3.1 `identity`

```python
"identity": {
    "dataset_key": "bse_mapping",
    "display_name": "北交所新旧代码对照",
    "description": "维护 Tushare 北交所新旧代码对照数据。",
    "aliases": (),
}
```

### 3.2 `domain`

```python
"domain": {
    "domain_key": "reference_data",
    "domain_display_name": "基础主数据",
    "cadence": "snapshot",
}
```

### 3.3 `source`

```python
"source": {
    "source_key_default": "tushare",
    "source_keys": ("tushare",),
    "adapter_key": "tushare",
    "api_name": "bse_mapping",
    "source_fields": ("name", "o_code", "n_code", "list_date"),
    "source_doc_id": "tushare.bse_mapping",
    "request_builder_key": "_bse_mapping_params",
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
    "not_applicable_reason": "小体量快照主数据，不按业务日期判断新鲜度。",
}
```

### 3.5 `input_model`

| 字段 | 类型 | 是否必填 | 默认值 | 是否多选 | 中文名 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `o_code` | string | 否 | 无 | 否 | 旧代码 | 可选过滤 |
| `n_code` | string | 否 | 无 | 否 | 新代码 | 可选过滤 |

### 3.6 `storage`

```python
"storage": {
    "raw_dao_name": "raw_bse_mapping",
    "core_dao_name": "raw_bse_mapping",
    "target_table": "core_serving_light.bse_mapping",
    "delivery_mode": "raw_with_serving_light_view",
    "layer_plan": "raw->serving_light_view",
    "std_table": None,
    "serving_table": "core_serving_light.bse_mapping",
    "raw_table": "raw_tushare.bse_mapping",
    "conflict_columns": ("o_code", "n_code"),
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

### 3.8 `normalization`

```python
"normalization": {
    "date_fields": ("list_date",),
    "decimal_fields": (),
    "required_fields": ("o_code", "n_code"),
    "row_transform_name": "_bse_mapping_row_transform",
}
```

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
    "progress_label": "bse_mapping",
    "observed_field": None,
    "audit_applicable": False,
},
"quality": {
    "reject_policy": "record_rejections",
    "required_fields": ("o_code", "n_code"),
},
"transaction": {
    "commit_policy": "unit",
    "idempotent_write_required": True,
    "write_volume_assessment": "全量只有数百行，单事务为一个快照 unit，写入规模很小。",
}
```

---

## 4. 表结构、索引与 DAO 设计

### 4.1 Raw 表：`raw_tushare.bse_mapping`

- ORM：建议新增 `src/foundation/models/raw/raw_bse_mapping.py`
- DAO：建议新增 `raw_bse_mapping`
- 主键：`(o_code, n_code)`

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `o_code` | varchar(16) | 否 | 原代码 |
| `n_code` | varchar(16) | 否 | 新代码 |
| `name` | varchar(128) | 是 | 股票名称 |
| `list_date` | date | 是 | 源站 `YYYYMMDD` 日期直接落 `date` |

索引建议：

```sql
create unique index uq_raw_tushare_bse_mapping_o_code_n_code
on raw_tushare.bse_mapping(o_code, n_code);

create index idx_raw_tushare_bse_mapping_n_code
on raw_tushare.bse_mapping(n_code);
```

### 4.2 Target View：`core_serving_light.bse_mapping`

- ORM：建议新增 `src/foundation/models/core_serving_light/bse_mapping.py`
- 与 raw 保持同名字段，`list_date` 继续使用 `date`

---

## 5. 执行链路设计

### 5.1 请求构造

- `request_builder_key`：`_bse_mapping_params`
- 只透传 `o_code` / `n_code`

### 5.2 Unit 规划

- `unit_builder_key`：`generic`
- 只生成 1 个 snapshot unit

### 5.3 分页

- `limit=1000`
- `offset=0/1000/...`
- 结束条件：返回 `< 1000`

### 5.4 Writer

- `write_path`：`raw_only_upsert`
- 冲突列：`(o_code, n_code)`

---

## 6. Ops 派生

1. 手动任务使用 `none` 模式，不展示时间控件。
2. 筛选项只展示 `o_code`、`n_code`。
3. 数据源页、手动任务页、自动任务页统一展示到 `reference_data / A股基础数据`。
4. freshness 只展示最近一次任务成功迹象，不按业务日期判断新鲜/滞后。

---

## 7. 测试与验收清单

1. `DatasetDefinition` 注册
2. `request_builder` 透传 `o_code` / `n_code`
3. `manual-actions` / `catalog` 只暴露两个过滤项
4. `writer` 对 `(o_code, n_code)` 幂等 upsert
5. `ops-rebuild-dataset-status` 后数据状态能正确显示最近运行迹象
