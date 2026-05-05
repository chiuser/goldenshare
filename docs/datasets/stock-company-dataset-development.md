# 上市公司基本信息（`stock_company`）数据集开发说明（待评审）

## 0. 架构基线与目标

本数据集是典型的按交易所分批抓取的主数据快照：

1. Raw 层精确复刻源字段名；对语义明确、格式稳定的日期字符串字段允许直接落 `date`。
2. 维护动作统一为 `stock_company.maintain`。
3. 当用户未指定 `ts_code` / `exchange` 时，必须按交易所拆成多个 unit，而不是赌单请求一定装得下。
4. 不重复落一份 serving 物理表，采用 `raw -> core_serving_light view`。

参考模板：[数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)

---

## 1. 源站事实

- 源站接口：Tushare `stock_company`
- 本地源站文档：[0112_上市公司基本信息.md](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/基础数据/0112_上市公司基本信息.md)
- `docs_index.csv` 记录：`doc_id=112`，`api_name=stock_company`
- 单次限制：最大 `4500` 条
- 源站建议：可按交易所分批提取
- 交易所枚举：`SSE` / `SZSE` / `BSE`

### 1.1 输入参数

| 参数名 | 类型 | 必填 | 源站含义 | 类别 | 运营侧是否填写 | 接入设计 |
| --- | --- | --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | 股票代码 | 代码 | 是 | 精确拉单个公司 |
| `exchange` | string | 否 | 交易所 | 枚举 | 是 | 不填时按 `SSE/SZSE/BSE` 默认扇出 |
| `limit` | integer | 否 | 单页行数 | 分页 | 否 | 固定传 `4500` |
| `offset` | integer | 否 | 分页偏移量 | 分页 | 否 | 自动递增 |

### 1.2 输出字段

| 字段名 | 源类型 | 是否落 raw | 备注 |
| --- | --- | --- | --- |
| `ts_code` | string | 是 | 股票代码 |
| `com_name` | string | 是 | 公司全称 |
| `com_id` | string | 是 | 统一社会信用代码 |
| `exchange` | string | 是 | 交易所代码 |
| `chairman` | string | 是 | 法人代表 |
| `manager` | string | 是 | 总经理 |
| `secretary` | string | 是 | 董秘 |
| `reg_capital` | float | 是 | 注册资本 |
| `setup_date` | string | 是 | 注册日期；源站为 `YYYYMMDD` 字符串，raw 层直接落 `date` |
| `province` | string | 是 |  |
| `city` | string | 是 |  |
| `introduction` | string | 是 | 长文本，建议 `text` |
| `website` | string | 是 |  |
| `email` | string | 是 |  |
| `office` | string | 是 | 长文本 |
| `employees` | int | 是 | 员工人数 |
| `main_business` | string | 是 | 长文本 |
| `business_scope` | string | 是 | 长文本 |
| `ann_date` | string | 是 | 公告日期；源站为 `YYYYMMDD` 字符串，raw 层直接落 `date` |

### 1.3 源端行为判断

1. 源文档明确说“可以根据交易所分批提取”，这意味着无条件全量请求不应直接做成单个 unit。
2. 当用户明确传 `ts_code` 时，应当直接拉单个公司，不需要再按交易所扇出。
3. 当用户未传 `ts_code` 但传了一个或多个 `exchange` 时，按 `exchange` 扇出。
4. 当用户两个都没传时，按 `SSE/SZSE/BSE` 默认扇出。

---

## 2. 基本信息

- 数据集 key：`stock_company`
- 中文显示名：`上市公司基本信息`
- 所属定义文件：建议新增到 `src/foundation/datasets/definitions/reference_master.py`
- 所属域：`reference_data`
- 所属域中文名：`基础主数据`
- 数据源：`tushare`
- 源站 API：`stock_company`
- 是否对外服务：是
- 是否多源融合：否
- 是否纳入自动任务：是，已纳入 `reference_data_refresh`
- 是否纳入日期完整性审计：否
- Ops 展示分组 key：`reference_data`
- Ops 展示分组名称：`A股基础数据`
- Ops 展示分组顺序：`1`

---

## 3. DatasetDefinition 设计

### 3.1 `identity`

```python
"identity": {
    "dataset_key": "stock_company",
    "display_name": "上市公司基本信息",
    "description": "维护 Tushare 上市公司基本信息数据。",
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
    "api_name": "stock_company",
    "source_fields": (
        "ts_code",
        "com_name",
        "com_id",
        "exchange",
        "chairman",
        "manager",
        "secretary",
        "reg_capital",
        "setup_date",
        "province",
        "city",
        "introduction",
        "website",
        "email",
        "office",
        "employees",
        "main_business",
        "business_scope",
        "ann_date",
    ),
    "source_doc_id": "tushare.stock_company",
    "request_builder_key": "_stock_company_params",
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
    "not_applicable_reason": "主数据快照，不按业务日期判断新鲜度。",
}
```

### 3.5 `input_model`

| 字段 | 类型 | 是否必填 | 默认值 | 枚举值 | 是否多选 | 中文名 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ts_code` | string | 否 | 无 | 无 | 否 | 股票代码 | 精确抓单个公司 |
| `exchange` | list | 否 | 无 | `SSE/SZSE/BSE` | 是 | 交易所 | 不填时按三交易所默认扇出 |

### 3.6 `storage`

```python
"storage": {
    "raw_dao_name": "raw_stock_company",
    "core_dao_name": "raw_stock_company",
    "target_table": "core_serving_light.stock_company",
    "delivery_mode": "raw_with_serving_light_view",
    "layer_plan": "raw->serving_light_view",
    "std_table": None,
    "serving_table": "core_serving_light.stock_company",
    "raw_table": "raw_tushare.stock_company",
    "conflict_columns": ("ts_code",),
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
    "page_limit": 4500,
    "chunk_size": None,
    "max_units_per_execution": None,
    "unit_builder_key": "build_stock_company_units",
}
```

说明：使用自定义 unit builder，而不是直接依赖 `enum_fanout_defaults`，原因是“`ts_code` 已给定时不应再按交易所扇出”。

### 3.8 `normalization`

```python
"normalization": {
    "date_fields": ("setup_date", "ann_date"),
    "decimal_fields": ("reg_capital",),
    "required_fields": ("ts_code", "exchange"),
    "row_transform_name": "_stock_company_row_transform",
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
    "progress_label": "stock_company",
    "observed_field": None,
    "audit_applicable": False,
},
"quality": {
    "reject_policy": "record_rejections",
    "required_fields": ("ts_code", "exchange"),
},
"transaction": {
    "commit_policy": "unit",
    "idempotent_write_required": True,
    "write_volume_assessment": "单个事务只覆盖一个交易所快照或一个明确 ts_code 请求，避免把三交易所全集压成一个 unit。",
}
```

---

## 4. 表结构、索引与 DAO 设计

### 4.1 Raw 表：`raw_tushare.stock_company`

- ORM：建议新增 `src/foundation/models/raw/raw_stock_company.py`
- DAO：建议新增 `raw_stock_company`
- 主键：`ts_code`

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `ts_code` | varchar(16) | 否 | 股票代码 |
| `com_name` | varchar(256) | 是 | 公司全称 |
| `com_id` | varchar(32) | 是 | 统一社会信用代码 |
| `exchange` | varchar(8) | 否 | 交易所代码 |
| `chairman` | varchar(128) | 是 |  |
| `manager` | varchar(128) | 是 |  |
| `secretary` | varchar(128) | 是 |  |
| `reg_capital` | double precision | 是 |  |
| `setup_date` | date | 是 | 注册日期直接落 `date` |
| `province` | varchar(64) | 是 |  |
| `city` | varchar(64) | 是 |  |
| `introduction` | text | 是 |  |
| `website` | varchar(256) | 是 |  |
| `email` | varchar(256) | 是 |  |
| `office` | text | 是 |  |
| `employees` | integer | 是 |  |
| `main_business` | text | 是 |  |
| `business_scope` | text | 是 |  |
| `ann_date` | date | 是 | 公告日期直接落 `date` |

索引建议：

```sql
create unique index uq_raw_tushare_stock_company_ts_code
on raw_tushare.stock_company(ts_code);

create index idx_raw_tushare_stock_company_exchange
on raw_tushare.stock_company(exchange);

create index idx_raw_tushare_stock_company_com_id
on raw_tushare.stock_company(com_id);
```

说明：`com_id` 不建议做唯一索引，因为源文档没有给出“全量必填且绝对唯一”的事实保证。

### 4.2 Target View：`core_serving_light.stock_company`

- ORM：建议新增 `src/foundation/models/core_serving_light/stock_company.py`
- 与 raw 保持相同字段名；`setup_date`、`ann_date` 继续使用 `date`

---

## 5. 执行链路设计

### 5.1 请求构造

- `request_builder_key`：`_stock_company_params`
- 透传 `ts_code`
- 透传单个 `exchange`

### 5.2 Unit 规划

- `unit_builder_key`：`build_stock_company_units`
- 规则：
  - 如果给了 `ts_code`：1 个 unit，不按交易所扇出
  - 如果没给 `ts_code` 但给了 `exchange`：按选中的交易所逐个 unit
  - 如果都没给：默认扇出 `SSE`、`SZSE`、`BSE`

### 5.3 分页

- `limit=4500`
- `offset=0/4500/...`
- 结束条件：返回 `< 4500`

### 5.4 Writer

- `write_path`：`raw_only_upsert`
- 冲突列：`ts_code`

---

## 6. Ops 派生

1. 手动任务不显示时间控件。
2. `exchange` 应表现为可多选枚举。
3. 如果用户未选择交易所，后端默认按三交易所扇出，而不是让前端写死。
4. 数据源页、手动任务页、自动任务页统一展示到 `reference_data / A股基础数据`。
5. freshness 只展示最近成功任务迹象。

---

## 7. 测试与验收清单

1. `DatasetDefinition` 注册
2. `request_builder` 透传 `ts_code/exchange`
3. `unit_planner`：
   - `ts_code` 模式只生成 1 个 unit
   - 无 `ts_code` 且无 `exchange` 时默认生成 `SSE/SZSE/BSE`
4. `writer`：按 `ts_code` 幂等 upsert
5. `manual-actions` / `catalog` 正确展示 `exchange` 多选过滤项
