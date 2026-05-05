# 股票历史基础列表（`bak_basic`）数据集开发说明（待评审）

## 0. 架构基线与目标

本数据集按当前主链设计：

1. 数据集事实收敛到 `DatasetDefinition`。
2. 维护动作统一为 `bak_basic.maintain`。
3. 执行主链统一走 `DatasetActionRequest -> DatasetExecutionPlan -> IngestionExecutor -> TaskRun`。
4. Raw 层必须对 Tushare 原始字段名做精准复刻；对语义明确、格式稳定的日期字符串字段，允许直接落 `date`，不额外保留第二份字符串镜像。
5. 状态写入失败不得影响业务数据事务。

参考模板：[数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)

---

## 1. 源站事实

- 源站接口：Tushare `bak_basic`
- 本地源站文档：[0262_股票历史列表（历史每天股票列表）.md](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/基础数据/0262_股票历史列表（历史每天股票列表）.md)
- `docs_index.csv` 记录：`doc_id=262`，`api_name=bak_basic`
- 接口说明：获取备用基础列表，数据从 2016 年开始。
- 单次限制：单次最大 `7000` 条。
- 分页方式：`limit` + `offset`
- 源站已知输入：`trade_date`、`ts_code`

### 1.1 输入参数

| 参数名 | 类型 | 必填 | 源站含义 | 类别 | 运营侧是否填写 | 接入设计 |
| --- | --- | --- | --- | --- | --- | --- |
| `trade_date` | string | 否 | 交易日期 | 时间 | 是 | 单日维护直接映射；区间维护按交易日扇出后逐日映射 |
| `ts_code` | string | 否 | 股票代码 | 代码 | 是 | 作为可选过滤条件，不参与对象池扇出 |
| `limit` | integer | 否 | 单页行数 | 分页 | 否 | 系统固定传 `7000` |
| `offset` | integer | 否 | 分页偏移量 | 分页 | 否 | 系统自动递增 |

### 1.2 输出字段

| 字段名 | 源类型 | 是否落 raw | 备注 |
| --- | --- | --- | --- |
| `trade_date` | string | 是 | 源站为 `YYYYMMDD` 字符串，raw 层直接落 `date` |
| `ts_code` | string | 是 | 主身份字段 |
| `name` | string | 是 |  |
| `industry` | string | 是 |  |
| `area` | string | 是 |  |
| `pe` | float | 是 |  |
| `float_share` | float | 是 |  |
| `total_share` | float | 是 |  |
| `total_assets` | float | 是 |  |
| `liquid_assets` | float | 是 |  |
| `fixed_assets` | float | 是 |  |
| `reserved` | float | 是 |  |
| `reserved_pershare` | float | 是 |  |
| `eps` | float | 是 |  |
| `bvps` | float | 是 |  |
| `pb` | float | 是 |  |
| `list_date` | string | 是 | 源站为 `YYYYMMDD` 字符串，raw 层直接落 `date` |
| `undp` | float | 是 |  |
| `per_undp` | float | 是 |  |
| `rev_yoy` | float | 是 |  |
| `profit_yoy` | float | 是 |  |
| `gpr` | float | 是 |  |
| `npr` | float | 是 |  |
| `holder_num` | int | 是 |  |

### 1.3 源端行为判断

1. 本接口没有 `start_date/end_date`，所以区间维护不能一次请求整段时间，只能按交易日扇出。
2. 本接口单日全市场可能接近或达到单页上限，分页必须始终开启。
3. `ts_code` 只是过滤条件，不是必须项；但 V1 不开放“无日期 + 全历史”模式，避免形成从 2016 年起的超长全历史任务。
4. 源站文档没有明确说明 `ts_code` 单独传入时是否返回该股票全历史全集；编码前应做一次真实调试确认。

---

## 2. 基本信息

- 数据集 key：`bak_basic`
- 中文显示名：`股票历史基础列表`
- 所属定义文件：建议新增到 `src/foundation/datasets/definitions/market_equity.py`
- 所属域：`market_equity`
- 所属域中文名：`股票行情`
- 数据源：`tushare`
- 源站 API 名称：`bak_basic`
- 是否对外服务：是
- 是否多源融合：否
- 是否纳入自动任务：是，建议后续接入按交易日维护工作流
- 是否纳入日期完整性审计：是
- Ops 展示分组 key：`reference_data`
- Ops 展示分组名称：`A股基础数据`
- Ops 展示分组顺序：`1`

---

## 3. DatasetDefinition 设计

### 3.1 `identity`

```python
"identity": {
    "dataset_key": "bak_basic",
    "display_name": "股票历史基础列表",
    "description": "维护 Tushare 股票历史基础列表数据。",
    "aliases": (),
}
```

### 3.2 `domain`

```python
"domain": {
    "domain_key": "equity_market",
    "domain_display_name": "股票行情",
    "cadence": "daily",
}
```

### 3.3 `source`

```python
"source": {
    "source_key_default": "tushare",
    "source_keys": ("tushare",),
    "adapter_key": "tushare",
    "api_name": "bak_basic",
    "source_fields": (
        "trade_date",
        "ts_code",
        "name",
        "industry",
        "area",
        "pe",
        "float_share",
        "total_share",
        "total_assets",
        "liquid_assets",
        "fixed_assets",
        "reserved",
        "reserved_pershare",
        "eps",
        "bvps",
        "pb",
        "list_date",
        "undp",
        "per_undp",
        "rev_yoy",
        "profit_yoy",
        "gpr",
        "npr",
        "holder_num",
    ),
    "source_doc_id": "tushare.bak_basic",
    "request_builder_key": "_bak_basic_params",
    "base_params": {},
}
```

### 3.4 `date_model`

```python
"date_model": {
    "date_axis": "trade_open_day",
    "bucket_rule": "every_open_day",
    "window_mode": "point_or_range",
    "input_shape": "trade_date_or_start_end",
    "observed_field": "trade_date",
    "audit_applicable": True,
    "not_applicable_reason": None,
}
```

说明：

1. 本数据集的业务时间轴就是 `trade_date`。
2. 区间维护必须按开市交易日逐日生成 unit。
3. 不开放 `none` 模式，避免无边界地回扫 2016 年以来全历史。

### 3.5 `input_model`

| 字段 | 类型 | 是否必填 | 默认值 | 是否多选 | 中文名 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `trade_date` | date | 否 | 无 | 否 | 处理日期 | 单日维护 |
| `start_date` | date | 否 | 无 | 否 | 开始日期 | 区间维护开始日期 |
| `end_date` | date | 否 | 无 | 否 | 结束日期 | 区间维护结束日期 |
| `ts_code` | string | 否 | 无 | 否 | 股票代码 | 可选过滤条件 |

### 3.6 `storage`

```python
"storage": {
    "raw_dao_name": "raw_bak_basic",
    "core_dao_name": "raw_bak_basic",
    "target_table": "core_serving_light.bak_basic",
    "delivery_mode": "raw_with_serving_light_view",
    "layer_plan": "raw->serving_light_view",
    "std_table": None,
    "serving_table": "core_serving_light.bak_basic",
    "raw_table": "raw_tushare.bak_basic",
    "conflict_columns": ("trade_date", "ts_code"),
    "write_path": "raw_only_upsert",
}
```

说明：

1. Raw 表严格保留源站字段名；`trade_date`、`list_date` 虽然源站是 `YYYYMMDD` 字符串，但 raw 层直接落 `date`。
2. `core_serving_light.bak_basic` 只做轻量查询投影，不再复制一份物理数据。
3. 因 raw 层已经直接使用 `date`，view 层不再额外做日期 cast。

### 3.7 `planning`

```python
"planning": {
    "universe_policy": "none",
    "enum_fanout_fields": (),
    "enum_fanout_defaults": {},
    "pagination_policy": "offset_limit",
    "page_limit": 7000,
    "chunk_size": None,
    "max_units_per_execution": None,
    "unit_builder_key": "generic",
}
```

写入量评估：

1. 单个 unit = 一个交易日。
2. 单个事务写入量 = 某个交易日全市场返回的全部行数，受单日市场股票数约束。
3. 分页只负责把单日结果拉完整，不承担事务切分职责。

### 3.8 `normalization`

```python
"normalization": {
    "date_fields": ("trade_date", "list_date"),
    "decimal_fields": (
        "pe",
        "float_share",
        "total_share",
        "total_assets",
        "liquid_assets",
        "fixed_assets",
        "reserved",
        "reserved_pershare",
        "eps",
        "bvps",
        "pb",
        "undp",
        "per_undp",
        "rev_yoy",
        "profit_yoy",
        "gpr",
        "npr",
    ),
    "required_fields": ("trade_date", "ts_code"),
    "row_transform_name": "_bak_basic_row_transform",
}
```

说明：`row_transform` 只做字符串裁剪、`ts_code` 规范化和空值整理；`trade_date/list_date` 由标准日期解析链直接落成 `date`。

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
    "progress_label": "bak_basic",
    "observed_field": "trade_date",
    "audit_applicable": True,
},
"quality": {
    "reject_policy": "record_rejections",
    "required_fields": ("trade_date", "ts_code"),
},
"transaction": {
    "commit_policy": "unit",
    "idempotent_write_required": True,
    "write_volume_assessment": "单个事务只覆盖一个交易日；分页只负责拉完该交易日全部分页结果，不改变事务边界。",
}
```

---

## 4. 表结构、索引与 DAO 设计

### 4.1 Raw 表：`raw_tushare.bak_basic`

- ORM：建议新增 `src/foundation/models/raw/raw_bak_basic.py`
- DAO：建议在 `DAOFactory` 新增 `raw_bak_basic`
- 主键：`(trade_date, ts_code)`
- 审计字段：`api_name`、`fetched_at`、`raw_payload`

建议字段：

| 字段 | PostgreSQL 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `trade_date` | date | 否 | 源站 `YYYYMMDD` 日期直接落 `date` |
| `ts_code` | varchar(16) | 否 | 股票代码 |
| `name` | varchar(64) | 是 |  |
| `industry` | varchar(64) | 是 |  |
| `area` | varchar(64) | 是 |  |
| `pe` | double precision | 是 |  |
| `float_share` | double precision | 是 |  |
| `total_share` | double precision | 是 |  |
| `total_assets` | double precision | 是 |  |
| `liquid_assets` | double precision | 是 |  |
| `fixed_assets` | double precision | 是 |  |
| `reserved` | double precision | 是 |  |
| `reserved_pershare` | double precision | 是 |  |
| `eps` | double precision | 是 |  |
| `bvps` | double precision | 是 |  |
| `pb` | double precision | 是 |  |
| `list_date` | date | 是 | 上市日期直接落 `date` |
| `undp` | double precision | 是 |  |
| `per_undp` | double precision | 是 |  |
| `rev_yoy` | double precision | 是 |  |
| `profit_yoy` | double precision | 是 |  |
| `gpr` | double precision | 是 |  |
| `npr` | double precision | 是 |  |
| `holder_num` | integer | 是 |  |

索引建议：

```sql
create unique index uq_raw_tushare_bak_basic_trade_date_ts_code
on raw_tushare.bak_basic(trade_date, ts_code);

create index idx_raw_tushare_bak_basic_ts_code_trade_date
on raw_tushare.bak_basic(ts_code, trade_date);
```

### 4.2 Target View：`core_serving_light.bak_basic`

- ORM：建议新增 `src/foundation/models/core_serving_light/bak_basic.py`
- 作用：给 Ops / Biz 提供稳定查询出口，同时让 `trade_date` 可被 freshness / audit 正常消费。

建议口径：

1. 保持原始字段名不变。
2. `trade_date` 和 `list_date` 在 raw 层已经直接使用 `date`，view 层继续沿用同名字段。
3. 其他字段继续保持 raw 口径。

---

## 5. 执行链路设计

### 5.1 请求构造

- `request_builder_key`：`_bak_basic_params`
- 位置：`src/foundation/ingestion/request_builders.py`
- 行为：
  - `point`：传 `trade_date=YYYYMMDD`
  - `range`：planner 按交易日逐日扇出，每个 unit 仍然只传一个 `trade_date`
  - 如果用户填写 `ts_code`，则附带 `ts_code`

### 5.2 Unit 规划

- `unit_builder_key`：`generic`
- unit 维度：交易日
- `unit_id`：`bak_basic:<trade_date>:<ordinal>`
- `progress_context`：`trade_date`、可选 `ts_code`

### 5.3 Source Client 与分页

- adapter：`tushare`
- `pagination_policy`：`offset_limit`
- `page_limit`：`7000`
- 结束条件：返回行数 `< 7000`

### 5.4 Writer

- `write_path`：`raw_only_upsert`
- 冲突列：`(trade_date, ts_code)`
- 幂等：同一交易日重跑只 upsert，不重复插入

---

## 6. Ops 派生

### 6.1 手动任务

- 能见度：应在 `manual-actions` 中展示
- 名称：`股票历史基础列表`
- 时间控件：交易日单日 / 交易日区间
- 筛选项：`ts_code`
- 展示分组：`reference_data / A股基础数据`

### 6.2 自动任务

- 建议允许自动任务
- 推荐后续接入按交易日的日常维护工作流
- 展示分组：`reference_data / A股基础数据`
- 本文档不定义 workflow 细节

### 6.3 数据状态与日期完整性审计

- `observed_field`：`trade_date`
- 日期审计：适用
- freshness：按 `trade_open_day / every_open_day` 口径计算

---

## 7. 测试与验收清单

必须覆盖：

1. `DatasetDefinition` 注册测试
2. `request_builder`：单日 + 区间 + `ts_code` 过滤
3. `unit_planner`：区间按交易日逐日扇出
4. `normalizer`：`trade_date/list_date` 走标准日期解析链并落成 `date`
5. `writer`：按 `(trade_date, ts_code)` 幂等 upsert
6. `manual-actions` / `catalog` 契约
7. freshness / 日期审计链能正确读取 `core_serving_light.bak_basic.trade_date`

---

## 8. 当前未决点

1. 源站文档没有明确说明“仅传 `ts_code` 是否返回该股票全历史全集”；编码前必须实测。
2. 如果后续业务明确需要“单股票全历史一次性补拉”，再单独评审是否增加 `none` 模式；V1 不纳入本主链。
