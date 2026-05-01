# 新闻快讯数据集开发说明（待评审）

## 0. 架构基线与禁止项

本数据集必须按当前新架构接入：

1. 数据集事实源落在 `src/foundation/datasets/**` 的 `DatasetDefinition`。
2. 维护动作统一为 `action=maintain`，由 `DatasetActionRequest -> DatasetExecutionPlan -> IngestionExecutor` 执行。
3. 任务观测只走 TaskRun 主链，不恢复旧 executions API、旧 job state 或 sync log 作为页面事实源。
4. 不使用旧三类同步命令、旧同步服务包、`__ALL__`、checkpoint/acquire 语义。
5. Ops、freshness、TaskRun 等状态写入失败不得影响业务数据表写入和事务提交。

参考模板：[数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)。

## 1. 源站事实

- 源站接口：Tushare `news`
- 本地源站文档：[0143_新闻快讯.md](/Users/congming/github/goldenshare/docs/sources/tushare/大模型语料专题数据/0143_新闻快讯.md)
- `docs_index.csv` 记录：`doc_id=143`，`api_name=news`
- 接口说明：获取主流新闻网站的快讯新闻数据。
- 权限说明：需要单独开权限。
- 单次限制：单次最大 1500 条；按 `limit=1500`、`offset` 循环读取。

### 1.1 输入参数

| 参数名 | 类型 | 必填 | 源站含义 | 运营侧是否填写 | 接入设计 |
| --- | --- | --- | --- | --- | --- |
| `start_date` | datetime | 是 | 开始时间，示例 `2018-11-20 09:00:00` | 不直接填写 datetime | 运营选择自然日点/范围，planner 拆成日内时间窗口 |
| `end_date` | datetime | 是 | 结束时间 | 不直接填写 datetime | 由 unit 的时间窗口生成 |
| `src` | string | 是 | 新闻来源 | 可选多选 | 未选择时显式扇出全部真实来源 |
| `limit` | integer | 否 | 单页返回条数 | 否 | 系统固定传 `1500` |
| `offset` | integer | 否 | 分页偏移量 | 否 | 系统自动递增，直到源站返回不足一页 |

`src` 真实枚举值：

| 值 | 中文说明 |
| --- | --- |
| `sina` | 新浪财经 |
| `wallstreetcn` | 华尔街见闻 |
| `10jqka` | 同花顺 |
| `eastmoney` | 东方财富 |
| `yuncaijing` | 云财经 |
| `fenghuang` | 凤凰新闻 |
| `jinrongjie` | 金融界 |
| `cls` | 财联社 |
| `yicai` | 第一财经 |

### 1.2 输出字段

| 字段名 | 类型 | 含义 | 是否落 raw | 清洗规则 |
| --- | --- | --- | --- | --- |
| `datetime` | string | 新闻时间 | 是 | 解析为 `news_time` |
| `content` | string | 内容 | 是 | 去掉首尾空白，保留正文原文 |
| `title` | string | 标题 | 是 | 去掉首尾空白 |
| `channels` | string | 分类 | 是 | 可空，保留源值 |

源站输出不包含 `src`，但 `src` 是请求事实，必须在 normalizer 中补入落库行。

## 2. 基本信息

- 数据集 key：`news`
- 中文显示名：`新闻快讯`
- 所属定义文件：建议新增 `src/foundation/datasets/definitions/news.py`
- 所属域：`news`
- 所属域中文名：`新闻资讯`
- 数据源：`tushare`
- 源站 API 名称：`news`
- 是否对外服务：是，raw 表写入后通过 `core_serving_light` 普通 view 直出
- 是否多源融合：否
- 是否纳入自动任务：是，建议每日按最近 1 个自然日补采
- 是否纳入日期完整性审计：否

> 待评审点：是否接受新增 `news` 数据域。按你的口径，这三个接口归属“新闻资讯”，不按语料域处理。

## 3. DatasetDefinition 事实设计

### 3.1 `identity`

```python
"identity": {
    "dataset_key": "news",
    "display_name": "新闻快讯",
    "description": "维护 Tushare 新闻快讯数据。",
    "aliases": ("news_flash",),
}
```

说明：

1. `dataset_key` 与 Tushare API 名称保持一致，降低实现映射成本。
2. `display_name` 负责表达用户语义，页面不展示 `news` 这种技术名。
3. 本数据集只有一个 Tushare 来源，不参与多源融合排序，因此不配置 `logical_key` / `logical_priority`。

### 3.2 `domain`

```python
"domain": {
    "domain_key": "news",
    "domain_display_name": "新闻资讯",
    "cadence": "intraday",
}
```

说明：新闻快讯是日内持续更新数据，cadence 使用 `intraday`。

### 3.3 `source`

```python
"source": {
    "source_key_default": "tushare",
    "source_keys": ("tushare",),
    "adapter_key": "tushare",
    "api_name": "news",
    "source_fields": ("datetime", "content", "title", "channels"),
    "source_doc_id": "tushare.news",
    "request_builder_key": "_news_params",
    "base_params": {},
}
```

请求构造要求：

1. `point` 模式把用户选择日期拆为当天多个日内时间窗口。
2. `range` 模式按自然日逐日拆分，再按日内时间窗口拆分。
3. 每个请求必须携带真实 `src`，不得使用 `__ALL__` 或空值代替全选。

### 3.4 `date_model`

```python
"date_model": {
    "date_axis": "natural_day",
    "bucket_rule": "not_applicable",
    "window_mode": "point_or_range",
    "input_shape": "trade_date_or_start_end",
    "observed_field": "news_time",
    "audit_applicable": False,
    "not_applicable_reason": "新闻快讯按来源和发布时间采集，不保证每个来源每天都有新闻。",
}
```

说明：

1. 运营侧看到的是“只处理一天 / 处理一个时间区间”，不暴露源站 datetime 参数。
2. freshness 使用 `news_time` 观测最近新闻时间。
3. 日期完整性审计不启用，因为不同来源在不同自然日的新闻量不稳定。

### 3.5 `input_model`

| 字段 | 类型 | 是否必填 | 默认值 | 枚举值 | 是否多选 | 中文名 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `trade_date` | date | 否 | 无 | 无 | 否 | 处理日期 | 单日维护入口 |
| `start_date` | date | 否 | 无 | 无 | 否 | 开始日期 | 区间维护入口 |
| `end_date` | date | 否 | 无 | 无 | 否 | 结束日期 | 区间维护入口 |
| `src` | list | 否 | 无 | 见 1.1 | 是 | 新闻来源 | 不填表示按全部真实来源扇出 |

`src` 不填时必须由 `planning.enum_fanout_defaults` 展开为真实来源列表。

## 4. 表结构设计

### 4.1 raw 表

- 表名：`raw_tushare.news`
- ORM：`src/foundation/models/raw/raw_news.py`
- DAO：`raw_news`
- `target_table`：`core_serving_light.news`
- `delivery_mode`：`raw_with_serving_light_view`
- `layer_plan`：`raw->serving_light_view`
- `write_path`：`raw_only_upsert`

建议字段：

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | bigserial | PK | 内部行 ID |
| `src` | varchar(32) | not null | 请求来源 |
| `news_time` | timestamptz | not null | 新闻时间 |
| `title` | text | not null | 标题 |
| `content` | text | not null | 正文 |
| `channels` | text | nullable | 分类 |
| `row_key_hash` | varchar(64) | unique not null | `src + news_time + title + content` 的稳定哈希 |
| `fetched_at` | timestamptz | not null default now() | 抓取时间 |
| `raw_payload` | text | nullable | 原始行 JSON |

索引建议：

```sql
create unique index uq_raw_tushare_news_row_key_hash on raw_tushare.news(row_key_hash);
create index ix_raw_tushare_news_src_time on raw_tushare.news(src, news_time desc);
create index ix_raw_tushare_news_time on raw_tushare.news(news_time desc);
```

### 4.2 serving light view

V1 不复制一份新闻数据到 `core` 或 `core_serving` 物理表，直接建立普通 view：

- view：`core_serving_light.news`
- 来源：`raw_tushare.news`
- 作用：给查询侧一个稳定出口，避免业务页面直接依赖 raw 表名。
- 约束：普通 view 不复制数据，不做物化视图。

## 5. 执行计划设计

### 5.1 planning

```python
"planning": {
    "universe_policy": "none",
    "enum_fanout_fields": ("src",),
    "enum_fanout_defaults": {
        "src": (
            "sina",
            "wallstreetcn",
            "10jqka",
            "eastmoney",
            "yuncaijing",
            "fenghuang",
            "jinrongjie",
            "cls",
            "yicai",
        ),
    },
    "pagination_policy": "offset_limit",
    "page_limit": 1500,
    "chunk_size": None,
    "max_units_per_execution": None,
    "unit_builder_key": "build_news_units",
}
```

### 5.2 unit 拆分

新闻快讯接口单次最多 1500 条，支持 `limit/offset` 循环读取。V1 按“来源 + 自然日”生成 unit：

1. `point` 模式：每个来源生成 1 个自然日 unit。
2. `range` 模式：按自然日逐日拆分，再按来源扇出。
3. 每个 unit 使用当天 `00:00:00 ~ 23:59:59` 的时间窗口。
4. source client 在该 unit 内按 `limit=1500`、`offset=0/1500/3000...` 循环读取。
5. 当某页返回行数小于 1500 时，该 unit 读取结束。

### 5.3 请求示例

单日维护 `2026-04-24`，用户未选择来源时，planner 生成多个 unit，例如：

```json
{
  "dataset_key": "news",
  "action": "maintain",
  "time_input": {
    "mode": "point",
    "trade_date": "2026-04-24"
  },
  "filters": {}
}
```

其中一个 unit 的 Tushare 请求参数：

```json
{
  "src": "sina",
  "start_date": "2026-04-24 00:00:00",
  "end_date": "2026-04-24 23:59:59",
  "limit": 1500,
  "offset": 0
}
```

## 6. 清洗与质量

### 6.1 normalization

```python
"normalization": {
    "date_fields": ("news_time",),
    "decimal_fields": (),
    "required_fields": ("src", "news_time", "title", "content", "row_key_hash"),
    "row_transform_name": "_news_row_transform",
}
```

转换规则：

1. `datetime` -> `news_time`，按 Asia/Shanghai 语义解析后落 timestamptz。
2. `src` 从请求参数补入。
3. `title`、`content` 去除首尾空白。
4. `row_key_hash = sha256(src|news_time|title|content)`。

### 6.2 quality

```python
"quality": {
    "reject_policy": "record_rejections",
    "required_fields": ("src", "news_time", "title", "content", "row_key_hash"),
}
```

拒绝原因必须结构化：

| reason_code | 场景 |
| --- | --- |
| `missing_src` | 请求来源缺失 |
| `invalid_news_time` | 新闻时间无法解析 |
| `missing_title` | 标题为空 |
| `missing_content` | 正文为空 |
| `missing_row_key_hash` | 行键生成失败 |

## 7. 事务与写入量评估

```python
"transaction": {
    "commit_policy": "unit",
    "idempotent_write_required": True,
    "write_volume_assessment": "单 unit 为一个来源的一个自然日，按 limit=1500/offset 分页取完该日全部快讯；单事务写入量按该 unit 全部返回行数计算。",
}
```

说明：

1. 每个 unit 独立提交。
2. 同一新闻重复采集依靠 `row_key_hash` 幂等 upsert。
3. 状态写入失败不得回滚已提交的 raw 数据。

## 8. Ops 运营设计

### 8.1 手动任务

页面展示：

- 分组：`新闻资讯`
- 维护对象：`新闻快讯`
- 时间控件：自然日单日 / 自然日区间
- 筛选项：`新闻来源` 多选；默认不选等价于全选真实来源

用户不需要理解源站 `start_date/end_date` datetime 参数。

### 8.2 自动任务

建议新增每日任务：

- 维护对象：`新闻快讯`
- 时间范围：最近 1 个自然日
- 来源：全部真实来源
- 频率：每日运行，可后续按实际需要增加日内补采

### 8.3 任务详情

TaskRun 节点文案建议：

- 节点名称：`采集新闻快讯`
- unit 进度文案：`来源：新浪财经，日期：2026-04-24`
- 主指标：`已提交新闻条数`

不得展示 `src=sina`、`phase=started` 这类原始技术上下文。

### 8.4 数据状态

- 最近同步：取 `max(news_time)` 与成功时间派生后的 freshness 展示事实。
- 日期完整性：不展示完整性审计入口。
- 数据量统计：可展示 raw 表总行数、最近 7 日新增行数。

## 9. 测试与门禁

必须补充：

1. DatasetDefinition registry 测试覆盖 `news`。
2. request builder 测试：单日、区间、单来源、多来源、默认全来源。
3. unit planner 测试：按来源 + 自然日拆分，并使用 `offset_limit` 分页。
4. row transform 测试：补 `src`、解析 `news_time`、生成 `row_key_hash`。
5. writer 测试：重复行 upsert 不重复插入。
6. Ops manual action API 测试：时间控件与来源枚举来自 DatasetDefinition。
7. 架构测试：不得出现 `__ALL__`、旧 sync 路由、旧 TaskRun 事实源。

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
| D2 | `news` 是否通过 serving light 直出 | 是，raw 写入后建立 `core_serving_light.news` 普通 view |
| D3 | 新闻来源默认行为 | 不填等价于全选真实来源，由 `enum_fanout_defaults` 显式扇出 |
| D4 | 分页策略 | 使用 `offset_limit`，`page_limit=1500` |
| D5 | 是否加入日期完整性审计 | 否，只做 freshness 观测 |
