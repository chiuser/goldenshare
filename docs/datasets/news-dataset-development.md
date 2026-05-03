# 新闻快讯数据集开发说明（已开发）

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
- 源站文档链接：<https://tushare.pro/document/2?doc_id=143>
- 本地源站文档：[0143_新闻快讯.md](/Users/congming/github/goldenshare/docs/sources/tushare/大模型语料专题数据/0143_新闻快讯.md)
- `docs_index.csv` 记录：`doc_id=143`，`api_name=news`
- 文档抓取日期：`2026-05-02 23:42:59`
- 接口说明：获取主流新闻网站的快讯新闻数据。
- 权限说明：需要单独开权限。
- 单次限制：单次最大 1500 条；按 `limit=1500`、`offset` 循环读取。

### 1.1 输入参数

| 参数名 | 类型 | 必填 | 说明 | 类别（时间/枚举/代码/分页/其他） | 是否给运营用户填写 | 对应 `DatasetInputField` | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `start_date` | datetime | 是 | 开始时间，示例 `2018-11-20 09:00:00` | 时间 | 否 | `trade_date` 或 `start_date` | 由 resolver + planner 归一化后生成 |
| `end_date` | datetime | 是 | 结束时间 | 时间 | 否 | `trade_date` 或 `end_date` | 与 `start_date` 成对出现 |
| `src` | string | 是 | 新闻来源 | 枚举 | 是 | `src` | 不填写时按真实来源枚举全扇出 |
| `limit` | integer | 否 | 单页返回条数 | 分页 | 否 | 无 | 系统固定 `1500` |
| `offset` | integer | 否 | 分页偏移量 | 分页 | 否 | 无 | 系统分页循环自动递增 |

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

| 字段名 | 类型 | 含义 | 是否落 raw | 是否进入 serving/core | 清洗规则 |
| --- | --- | --- | --- | --- | --- |
| `datetime` | string | 新闻时间 | 是 | 是（`core_serving_light.news`） | 解析为 `news_time` |
| `content` | string | 内容 | 是 | 是 | 去掉首尾空白，保留正文原文，可空 |
| `title` | string | 标题 | 是 | 是 | 去掉首尾空白，可空 |
| `channels` | string | 分类 | 是 | 是 | 可空，保留源值 |
| `score` | string | 分值 | 是 | 是 | 可空，保留源值 |

源站输出不包含 `src`，但 `src` 是请求事实，必须在 normalizer 中补入落库行。
`title` 和 `content` 允许其中一个为空，但两者不能同时为空；两者同时为空时不是有效新闻记录，必须拒绝。

### 1.3 源端行为

- 是否分页：是。
- 分页参数与结束条件：`limit=1500` + `offset` 递增；当返回行数 `< 1500` 结束当前 unit。
- 是否限速或有积分限制：有接口权限限制，且按账号积分/频控约束执行。
- 是否需要拆分请求：需要按 `src` 枚举扇出，并按自然日 point/range 逐日拆分 unit。
- 是否有上游脏值或缺字段风险：有，`title/content` 可能出现空值；`datetime` 可能格式异常。
- 是否有级联依赖：无，不依赖其他数据集先行同步。

## 2. 基本信息

- 数据集 key：`news`
- 中文显示名：`新闻快讯`
- 所属定义文件：`src/foundation/datasets/definitions/news.py`
- 所属域：`news`
- 所属域中文名：`新闻资讯`
- 数据源：`tushare`
- 源站 API 名称：`news`
- 源站文档链接：<https://tushare.pro/document/2?doc_id=143>
- 本地源站文档路径：[0143_新闻快讯.md](/Users/congming/github/goldenshare/docs/sources/tushare/大模型语料专题数据/0143_新闻快讯.md)
- 文档抓取日期：`2026-05-02 23:42:59`
- 是否对外服务：是，raw 表写入后通过 `core_serving_light` 普通 view 直出
- 是否多源融合：否
- 是否纳入自动任务：是
- 是否纳入日期完整性审计：否

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
    "source_fields": ("datetime", "content", "title", "channels", "score"),
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

### 3.6 `capabilities`

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

### 3.7 `observability` / `quality` / `transaction`

```python
"observability": {
    "progress_label": "news",
    "observed_field": "news_time",
    "audit_applicable": False,
},
"quality": {
    "reject_policy": "record_rejections",
    "required_fields": ("src", "news_time", "row_key_hash"),
},
"transaction": {
    "commit_policy": "unit",
    "idempotent_write_required": True,
    "write_volume_assessment": "单 unit 为一个来源的一个自然日，按 limit=1500/offset 分页取完该日全部快讯；单事务写入量按该 unit 全部返回行数计算。",
}
```

说明：

1. `observability.observed_field` 必须与 `date_model.observed_field` 一致，统一使用 `news_time`。
2. `commit_policy` 固定 `unit`，且 Ops/TaskRun/freshness 状态写入失败不得影响业务数据提交。

## 4. 表结构设计

### 4.1 raw 表

- 表名：`raw_tushare.news`
- ORM：`src/foundation/models/raw/raw_news.py`
- DAO：`raw_news`
- `target_table`：`core_serving_light.news`
- `delivery_mode`：`raw_with_serving_light_view`
- `layer_plan`：`raw->serving_light_view`
- `write_path`：`raw_only_upsert`

字段：

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | bigserial | PK | 内部行 ID |
| `src` | varchar(32) | not null | 请求来源 |
| `news_time` | timestamptz | not null | 新闻时间 |
| `title` | text | nullable | 标题，源站可能为空 |
| `content` | text | nullable | 正文，源站可能为空 |
| `channels` | text | nullable | 分类 |
| `score` | text | nullable | 分值，源站可能为空 |
| `row_key_hash` | varchar(64) | unique not null | `api_name + src + news_time + title + content + channels + score` 的稳定哈希 |
| `fetched_at` | timestamptz | not null default now() | 抓取时间 |
| `raw_payload` | text | nullable | 原始行 JSON |

索引建议：

```sql
create unique index uq_raw_tushare_news_row_key_hash on raw_tushare.news(row_key_hash);
create index ix_raw_tushare_news_src_time on raw_tushare.news(src, news_time desc);
create index ix_raw_tushare_news_time on raw_tushare.news(news_time desc);
```

说明：

1. `title` 和 `content` 是新闻主体字段，允许单个为空，但不允许同时为空。
2. `channels`、`score` 是源站返回的行事实，在缺少源站稳定 ID 的情况下纳入 `row_key_hash`，用于降低同一时间同一来源下的误合并风险。
3. 不给 `title` / `content` 建普通索引。它们是长文本且可空，本轮只完成源站数据沉淀和 serving light 直出。

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
    "universe_policy": "no_pool",
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

说明：`universe_policy` 使用 `no_pool` 明确表达“不按对象池展开”，只按日期与枚举来源拆分 unit，不使用 `none` 这种未定义语义。

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
    "date_fields": (),
    "decimal_fields": (),
    "required_fields": ("src", "news_time", "row_key_hash"),
    "row_transform_name": "_news_row_transform",
}
```

转换规则：

1. `datetime` -> `news_time` 由 `_news_row_transform` 完成，按 Asia/Shanghai 语义解析后落 timestamptz。
2. `src` 从请求参数补入。
3. `title`、`content`、`channels`、`score` 去除首尾空白；空字符串按 `NULL` 保存。
4. `title` 和 `content` 至少一个非空；两者同时为空时拒绝。
5. `row_key_hash = sha256(api_name|src|news_time|title_or_empty|content_or_empty|channels_or_empty|score_or_empty)`。

### 6.2 quality

```python
"quality": {
    "reject_policy": "record_rejections",
    "required_fields": ("src", "news_time", "row_key_hash"),
}
```

拒绝原因必须结构化：

| reason_code | 场景 |
| --- | --- |
| `normalize.required_field_missing:src` | 请求来源缺失 |
| `normalize.invalid_date:news_time` | 新闻时间无法解析 |
| `normalize.empty_not_allowed:title_content` | 标题和正文同时为空 |
| `normalize.required_field_missing:row_key_hash` | 行键生成失败 |

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
提交入口：`POST /api/v1/ops/manual-actions/news.maintain/task-runs`。

### 8.2 任务详情

TaskRun 节点文案建议：

- 节点名称：`采集新闻快讯`
- unit 进度文案：`来源：新浪财经，日期：2026-04-24`
- 主指标：`已提交新闻条数`

不得展示 `src=sina`、`phase=started` 这类原始技术上下文。

TaskRun 结构化观测字段建议：

- 当前对象类型：`enum_source + natural_day`
- 当前对象标识字段：`src`
- 当前窗口字段：`date_window`（`start_date` / `end_date`）
- `progress_context` 示例：`{"src":"sina","trade_date":"2026-04-24","window_start":"2026-04-24 00:00:00","window_end":"2026-04-24 23:59:59"}`
- `TaskRunIssue.object_json` 示例：`{"src":"sina","trade_date":"2026-04-24","page_offset":1500}`

### 8.3 数据状态

- 最近同步：取 `max(news_time)` 与成功时间派生后的 freshness 展示事实。
- 日期完整性：不展示完整性审计入口。

## 9. 测试与门禁

已补充：

1. DatasetDefinition registry 测试覆盖 `news`。
2. request builder 测试：单日、区间、单来源、多来源、默认全来源。
3. unit planner 测试：按来源 + 自然日拆分，并使用 `offset_limit` 分页。
4. row transform 测试：补 `src`、解析 `news_time`、允许 `title/content` 单个为空、拒绝二者同时为空、生成 `row_key_hash`。
5. writer 测试：重复行 upsert 不重复插入。
6. Ops manual action API 测试：时间控件与来源枚举来自 DatasetDefinition。
7. 架构测试：不得出现 `__ALL__`、旧 sync 路由、旧 TaskRun 事实源。

验证命令：

```bash
python3 scripts/check_docs_integrity.py
pytest -q tests/test_dataset_definition_registry.py
pytest -q tests/foundation/ingestion
```

## 10. 当前评审口径（已拍板）

| 编号 | 决策点 | 口径 |
| --- | --- | --- |
| D1 | 是否新增 `news` domain | 已新增，中文名为“新闻资讯” |
| D2 | `news` 是否通过 serving light 直出 | 是，raw 写入后建立 `core_serving_light.news` 普通 view |
| D3 | 新闻来源默认行为 | 不填等价于全选真实来源，由 `enum_fanout_defaults` 显式扇出 |
| D4 | 分页策略 | 使用 `offset_limit`，`page_limit=1500` |
| D5 | 是否加入日期完整性审计 | 否，只做 freshness 观测 |
