# 新闻联播数据集开发说明（已评审）

## 0. 架构基线与禁止项

本数据集必须按当前新架构接入：

1. 数据集事实源落在 `src/foundation/datasets/**` 的 `DatasetDefinition`。
2. 维护动作统一为 `action=maintain`，由 `DatasetActionRequest -> DatasetExecutionPlan -> IngestionExecutor` 执行。
3. 任务观测只走 TaskRun 主链。
4. 不使用旧三类同步命令、旧同步服务包、`__ALL__`、checkpoint/acquire 语义。
5. Ops、freshness、TaskRun 等状态写入失败不得影响业务数据表写入和事务提交。

参考模板：[数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)。

## 1. 源站事实

- 源站接口：Tushare `cctv_news`
- 本地源站文档：[0154_新闻联播.md](/Users/congming/github/goldenshare/docs/sources/tushare/大模型语料专题数据/0154_新闻联播.md)
- `docs_index.csv` 记录：`doc_id=154`，`api_name=cctv_news`
- 接口说明：获取新闻联播文字稿，数据开始于 2017 年。
- 权限说明：需要单独开权限。
- 单次限制：源站未明确单页上限，按本次接入口径使用 `limit=400`、`offset` 循环读取。

### 1.1 输入参数

| 参数名 | 类型 | 必填 | 源站含义 | 运营侧是否填写 | 接入设计 |
| --- | --- | --- | --- | --- | --- |
| `date` | string | 是 | 日期，格式 `YYYYMMDD` | 不直接填写源站参数 | 运营选择自然日点/范围，unit 按自然日生成 `date` |
| `limit` | integer | 否 | 单页返回条数 | 否 | 系统固定传 `400` |
| `offset` | integer | 否 | 分页偏移量 | 否 | 系统自动递增，直到源站返回不足一页 |

### 1.2 输出字段

| 字段名 | 类型 | 含义 | 是否落 raw | 清洗规则 |
| --- | --- | --- | --- | --- |
| `date` | string | 日期 | 是 | 保持源站字段名 `date`，便于与 Tushare 原始结果审计对齐 |
| `title` | string | 标题 | 是 | 去掉首尾空白 |
| `content` | string | 内容 | 是 | 去掉首尾空白，保留正文原文 |

## 2. 基本信息

- 数据集 key：`cctv_news`
- 中文显示名：`新闻联播文字稿`
- 所属定义文件：建议新增 `src/foundation/datasets/definitions/news.py`
- 所属域：`news`
- 所属域中文名：`新闻资讯`
- 数据源：`tushare`
- 源站 API 名称：`cctv_news`
- 是否对外服务：是，raw 表写入后通过 `core_serving_light` 普通 view 直出
- 是否多源融合：否
- 是否纳入自动任务：是，建议每日维护最近 1 个自然日
- 是否纳入日期完整性审计：是

## 3. DatasetDefinition 事实设计

### 3.1 `identity`

```python
"identity": {
    "dataset_key": "cctv_news",
    "display_name": "新闻联播文字稿",
    "description": "维护 Tushare 新闻联播文字稿数据。",
    "aliases": (),
}
```

说明：本数据集只有一个 Tushare 来源，不参与多源融合排序，因此不配置 `logical_key` / `logical_priority`。

### 3.2 `domain`

```python
"domain": {
    "domain_key": "news",
    "domain_display_name": "新闻资讯",
    "cadence": "daily",
}
```

### 3.3 `source`

```python
"source": {
    "source_key_default": "tushare",
    "source_keys": ("tushare",),
    "adapter_key": "tushare",
    "api_name": "cctv_news",
    "source_fields": ("date", "title", "content"),
    "source_doc_id": "tushare.cctv_news",
    "request_builder_key": "_cctv_news_params",
    "base_params": {},
}
```

### 3.4 `date_model`

```python
"date_model": {
    "date_axis": "natural_day",
    "bucket_rule": "every_natural_day",
    "window_mode": "point_or_range",
    "input_shape": "trade_date_or_start_end",
    "observed_field": "date",
    "audit_applicable": True,
    "not_applicable_reason": None,
}
```

说明：

1. 新闻联播是按自然日播出的文本稿，适合纳入日期完整性审计。
2. 运营侧仍使用“只处理一天 / 处理一个时间区间”的统一自然日控件。
3. `trade_date_or_start_end` 在当前代码中会被 natural_day 识别为日历日期控件；这里不表达交易日语义。

### 3.5 `input_model`

| 字段 | 类型 | 是否必填 | 默认值 | 枚举值 | 是否多选 | 中文名 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `trade_date` | date | 否 | 无 | 无 | 否 | 处理日期 | 单日维护入口，生成源站 `date` |
| `start_date` | date | 否 | 无 | 无 | 否 | 开始日期 | 区间维护入口 |
| `end_date` | date | 否 | 无 | 无 | 否 | 结束日期 | 区间维护入口 |

## 4. 表结构设计

### 4.1 raw 表

- 表名：`raw_tushare.cctv_news`
- ORM：`src/foundation/models/raw/raw_cctv_news.py`
- DAO：`raw_cctv_news`
- `target_table`：`core_serving_light.cctv_news`
- `delivery_mode`：`raw_with_serving_light_view`
- `layer_plan`：`raw->serving_light_view`
- `write_path`：`raw_only_upsert`

建议字段：

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | bigserial | PK | 内部行 ID |
| `date` | date | not null | 源站返回日期 |
| `title` | text | not null | 段落标题 |
| `content` | text | not null | 段落正文 |
| `row_key_hash` | varchar(64) | unique not null | `date + title + content` 的稳定哈希 |
| `fetched_at` | timestamptz | not null default now() | 抓取时间 |
| `raw_payload` | text | nullable | 原始行 JSON |

索引建议：

```sql
create unique index uq_raw_tushare_cctv_news_row_key_hash on raw_tushare.cctv_news(row_key_hash);
create index ix_raw_tushare_cctv_news_date on raw_tushare.cctv_news(date desc);
```

### 4.2 serving light view

V1 不复制一份新闻数据到 `core` 或 `core_serving` 物理表，直接建立普通 view：

- view：`core_serving_light.cctv_news`
- 来源：`raw_tushare.cctv_news`
- 作用：给查询侧一个稳定出口，避免业务页面直接依赖 raw 表名。
- 约束：普通 view 不复制数据，不做物化视图。

## 5. 执行计划设计

### 5.1 planning

```python
"planning": {
    "universe_policy": "none",
    "enum_fanout_fields": (),
    "enum_fanout_defaults": {},
    "pagination_policy": "offset_limit",
    "page_limit": 400,
    "chunk_size": None,
    "max_units_per_execution": None,
    "unit_builder_key": "generic",
}
```

### 5.2 unit 拆分

1. `point` 模式：1 个自然日生成 1 个 unit。
2. `range` 模式：按自然日逐日生成 unit。
3. 每个 unit 对应一个日期，source client 在这个日期内按 `limit=400`、`offset=0/400/800...` 循环读取。
4. 当某页返回行数小于 400 时，该日期读取结束。

请求示例：

```json
{
  "dataset_key": "cctv_news",
  "action": "maintain",
  "time_input": {
    "mode": "point",
    "trade_date": "2026-04-24"
  },
  "filters": {}
}
```

Tushare 请求参数：

```json
{
  "date": "20260424",
  "limit": 400,
  "offset": 0
}
```

## 6. 清洗与质量

### 6.1 normalization

```python
"normalization": {
    "date_fields": ("date",),
    "decimal_fields": (),
    "required_fields": ("date", "title", "content", "row_key_hash"),
    "row_transform_name": "_cctv_news_row_transform",
}
```

转换规则：

1. 源站 `date` 保持字段名不变，只把字符串规范化为日期类型。
2. 不新增 `segment_index`。源站文档只说明“分段处理”，没有返回稳定顺序字段；如果我们按返回顺序补序号，那只是本次请求的观察结果，不是可审计事实。
3. `title`、`content` 去除首尾空白。
4. `row_key_hash = sha256(date|title|content)`。

### 6.2 quality

```python
"quality": {
    "reject_policy": "record_rejections",
    "required_fields": ("date", "title", "content", "row_key_hash"),
}
```

拒绝原因必须结构化：

| reason_code | 场景 |
| --- | --- |
| `invalid_date` | 日期无法解析 |
| `missing_title` | 标题为空 |
| `missing_content` | 正文为空 |
| `missing_row_key_hash` | 行键生成失败 |

## 7. 事务与写入量评估

```python
"transaction": {
    "commit_policy": "unit",
    "idempotent_write_required": True,
    "write_volume_assessment": "单 unit 为一个自然日，按 limit=400/offset 分页取完该日全部段落；单事务写入量按该自然日全部返回行数计算。",
}
```

说明：

1. 每个自然日独立提交。
2. 重复维护依靠 `row_key_hash` 幂等 upsert。
3. 状态写入失败不得回滚已提交的 raw 数据。

## 8. Ops 运营设计

### 8.1 手动任务

页面展示：

- 分组：`新闻资讯`
- 维护对象：`新闻联播文字稿`
- 时间控件：自然日单日 / 自然日区间
- 筛选项：无

用户不需要理解源站 `date=YYYYMMDD` 参数。

### 8.2 自动任务

建议新增每日任务：

- 维护对象：`新闻联播文字稿`
- 时间范围：最近 1 个自然日
- 频率：每日运行

### 8.3 任务详情

TaskRun 节点文案建议：

- 节点名称：`采集新闻联播文字稿`
- unit 进度文案：`播出日期：2026-04-24`
- 主指标：`已提交文字稿段数`

### 8.4 数据状态与审计

- 最近同步：取 `max(date)` 与成功时间派生后的 freshness 展示事实。
- 日期完整性：按自然日检查 `date` 是否有数据。
- 若某天确实无数据，应支持后续在审计结果中标记业务例外，而不是改写 date_model。

## 9. 测试与门禁

必须补充：

1. DatasetDefinition registry 测试覆盖 `cctv_news`。
2. request builder 测试：单日 `date` 参数正确。
3. unit planner 测试：区间按自然日拆分。
4. row transform 测试：规范化 `date`、生成 `row_key_hash`。
5. writer 测试：重复行 upsert 不重复插入。
6. date completeness 测试：自然日审计可识别缺失日期。
7. Ops manual action API 测试：时间控件来自 DatasetDefinition。

验证命令：

```bash
python3 scripts/check_docs_integrity.py
pytest -q tests/test_dataset_definition_registry.py
pytest -q tests/foundation/ingestion
```

## 10. 待评审决策

| 编号 | 决策点 | 建议 |
| --- | --- | --- |
| D1 | 是否新增 `news` domain | 新增，中文名为“新闻资讯” |
| D2 | `cctv_news` 是否通过 serving light 直出 | 是，raw 写入后建立 `core_serving_light.cctv_news` 普通 view |
| D3 | 是否纳入日期完整性审计 | 是，按自然日审计 |
| D4 | 是否新增 `segment_index` | 否，源站没有提供稳定段落顺序字段，不把请求返回顺序固化成数据事实 |
| D5 | 分页策略 | 使用 `offset_limit`，`page_limit=400` |
