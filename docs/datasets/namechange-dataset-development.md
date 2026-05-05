# 股票曾用名（`namechange`）数据集开发说明（待评审）

## 0. 架构基线与目标

本数据集属于事件型历史资料：

1. Raw 表必须精准复刻源字段名；对语义明确、格式稳定的日期字符串字段允许直接落 `date`。
2. 维护动作统一为 `namechange.maintain`。
3. 本数据集不做“无边界全历史一次性事务”，但正常区间维护不额外切自然月窗口，直接按用户给定区间请求并分页。
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
| `start_date` | string | 否 | 公告开始日期 | 时间 | 不直接暴露源字段名 | 区间维护映射 |
| `end_date` | string | 否 | 公告结束日期 | 时间 | 不直接暴露源字段名 | 区间维护映射 |
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

1. 本接口原生支持 `start_date/end_date`，所以区间维护不应再按自然日逐日 fan-out 到 source；否则请求数过多且没有必要。
2. `namechange` 是低频事件数据，单只股票不会频繁改名，正常区间直接查整段再分页通常就足够，不需要人为切自然月窗口。
3. 源站文档没有给出单页最大返回条数，编码前必须实测。

---

## 2. 基本信息

- 数据集 key：`namechange`
- 中文显示名：`股票曾用名`
- 所属定义文件：建议新增到 `src/foundation/datasets/definitions/low_frequency.py`
- 所属域：`low_frequency`
- 所属域中文名：`低频数据`
- 数据源：`tushare`
- 源站 API：`namechange`
- 是否对外服务：是
- 是否多源融合：否
- 是否纳入自动任务：是，建议按公告日增量维护
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
    "domain_key": "low_frequency",
    "domain_display_name": "低频数据",
    "cadence": "low_frequency",
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
    "date_axis": "natural_day",
    "bucket_rule": "not_applicable",
    "window_mode": "point_or_range",
    "input_shape": "ann_date_or_start_end",
    "observed_field": None,
    "audit_applicable": False,
    "not_applicable_reason": "名称变更属于事件型公告数据，不要求每个自然日都有记录。",
}
```

说明：用户时间意图是“按公告日期查一个点或一个区间”，但 freshness / completeness 不按每日有无数据判定。

### 3.5 `input_model`

| 字段 | 类型 | 是否必填 | 默认值 | 是否多选 | 中文名 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `ann_date` | date | 否 | 无 | 否 | 公告日期 | 单日维护 |
| `start_date` | date | 否 | 无 | 否 | 开始日期 | 区间维护开始 |
| `end_date` | date | 否 | 无 | 否 | 结束日期 | 区间维护结束 |
| `ts_code` | string | 否 | 无 | 否 | 股票代码 | 可选过滤 |

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
    "page_limit": 3000,
    "chunk_size": None,
    "max_units_per_execution": None,
    "unit_builder_key": "generic",
}
```

说明：

1. `page_limit=3000` 只是文档阶段的保守建议值。
2. 因源站文档未给出单页上限，编码前必须用 WebClient / 数据工具实测，并以实测结果替换。
3. 不需要自定义 unit builder；单日维护 1 个 unit，区间维护也只保留 1 个区间 unit，内部靠分页拉完整段结果。

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
            "supported_time_modes": ("point", "range"),
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
    "write_volume_assessment": "namechange 为低频事件数据，正常区间维护直接按用户给定公告日期区间抓取并分页；单个事务覆盖该区间结果，预期写入量可控。",
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
- `point`：把 `ann_date` 映射为源站 `start_date=end_date`
- `range`：传窗口级别 `start_date/end_date`
- 如果填写 `ts_code`，一并透传

### 5.2 Unit 规划

- `unit_builder_key`：`generic`
- `point`：1 个 unit，请求参数映射为 `start_date=end_date=ann_date`
- `range`：1 个区间 unit，直接使用用户给定的 `start_date/end_date`
- `progress_context`：`ts_code`、`start_date`、`end_date`

### 5.3 分页

- `pagination_policy`：`offset_limit`
- `page_limit`：待实测确认
- 结束条件：返回 `< limit`

### 5.4 Writer

- `write_path`：`raw_only_upsert`
- 冲突列：`row_key_hash`

---

## 6. Ops 派生

1. 手动任务时间控件应显示“公告日期 / 开始日期 / 结束日期”。
2. `ts_code` 是可选过滤项。
3. 自动任务允许按公告日做日常增量，但本文档不定义具体 workflow。
4. 数据源页、手动任务页、自动任务页统一展示到 `reference_data / A股基础数据`。
5. 数据状态只展示最近一次成功任务迹象，不以“业务日新鲜度”做红绿灯。

---

## 7. 测试与验收清单

1. `DatasetDefinition` 注册
2. `request_builder`：`ann_date -> start_date=end_date`
3. `unit_planner`：区间不切窗，不按天扇出，保持 1 个区间 unit
4. `normalizer`：`row_key_hash` 生成与空值处理
5. `writer`：`row_key_hash` 幂等 upsert
6. `manual-actions`：显示公告日期语义和 `ts_code` 过滤项

---

## 8. 当前未决点

1. 源站文档未给出单页最大返回量，`page_limit` 必须在编码前实测确认。
2. 是否要额外支持“仅 `ts_code`、无时间窗口”的全历史模式，本文档暂不纳入；如要支持，需要单独评估源站真实返回语义和 UI 语义。
