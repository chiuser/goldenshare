# 新闻通讯数据集开发说明（已评审）

## 0. 架构基线与禁止项

本数据集必须按当前新架构接入：

1. 数据集事实源落在 `src/foundation/datasets/**` 的 `DatasetDefinition`。
2. 维护动作统一为 `action=maintain`，由 `DatasetActionRequest -> DatasetExecutionPlan -> IngestionExecutor` 执行。
3. 任务观测只走 TaskRun 主链。
4. 不使用旧三类同步命令、旧同步服务包、`__ALL__`、checkpoint/acquire 语义。
5. Ops、freshness、TaskRun 等状态写入失败不得影响业务数据表写入和事务提交。

参考模板：[数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)。

## 1. 源站事实

- 源站接口：Tushare `major_news`
- 本地源站文档：[0195_新闻通讯.md](/Users/congming/github/goldenshare/docs/sources/tushare/大模型语料专题数据/0195_新闻通讯.md)
- `docs_index.csv` 记录：`doc_id=195`，`api_name=major_news`
- 接口说明：获取长篇通讯信息，覆盖主要新闻资讯源。
- 权限说明：需要单独开权限。
- 单次限制：单次最大 400 行；按 `limit=400`、`offset` 循环读取。
- 字段注意：默认不输出 `content` 和 `url`，必须通过 `source_fields` 显式请求 `title,content,pub_time,src,url`。

### 1.1 输入参数

| 参数名 | 类型 | 必填 | 源站含义 | 运营侧是否填写 | 接入设计 |
| --- | --- | --- | --- | --- | --- |
| `src` | string | 否 | 新闻来源 | 可选多选 | 未选择时显式扇出全部真实来源 |
| `start_date` | string | 否 | 开始时间 | 不直接填写 datetime | 运营选择自然日点/范围，planner 生成 datetime |
| `end_date` | string | 否 | 结束时间 | 不直接填写 datetime | 由 unit 的时间窗口生成 |
| `limit` | integer | 否 | 单页返回条数 | 否 | 系统固定传 `400` |
| `offset` | integer | 否 | 分页偏移量 | 否 | 系统自动递增，直到源站返回不足一页 |

建议默认扇出的真实来源：

| 值 | 中文说明 |
| --- | --- |
| `新华网` | 新华网 |
| `凤凰财经` | 凤凰财经 |
| `同花顺` | 同花顺 |
| `新浪财经` | 新浪财经 |
| `华尔街见闻` | 华尔街见闻 |
| `中证网` | 中证网 |
| `财新网` | 财新网 |
| `第一财经` | 第一财经 |
| `财联社` | 财联社 |

### 1.2 输出字段

| 字段名 | 类型 | 含义 | 是否落 raw | 清洗规则 |
| --- | --- | --- | --- | --- |
| `title` | string | 标题 | 是 | 去掉首尾空白，可空 |
| `content` | string | 内容 | 是 | 去掉首尾空白，保留正文原文，可空 |
| `pub_time` | string | 发布时间 | 是 | 解析为 `pub_time` |
| `src` | string | 来源 | 是 | 去掉首尾空白 |
| `url` | string | 原文链接 | 是 | 去掉首尾空白，空值按 `NULL` 保存 |

说明：

1. `title` 和 `content` 允许其中一个为空，但两者不能同时为空。
2. `url` 是源站返回的行事实。已经确认不同 `url` 可能区分不同新闻记录，因此必须参与 `row_key_hash`。

## 2. 基本信息

- 数据集 key：`major_news`
- 中文显示名：`新闻通讯`
- 所属定义文件：建议新增 `src/foundation/datasets/definitions/news.py`
- 所属域：`news`
- 所属域中文名：`新闻资讯`
- 数据源：`tushare`
- 源站 API 名称：`major_news`
- 是否对外服务：是，raw 表写入后通过 `core_serving_light` 普通 view 直出
- 是否多源融合：否
- 是否纳入日期完整性审计：否

## 3. DatasetDefinition 事实设计

### 3.1 `identity`

```python
"identity": {
    "dataset_key": "major_news",
    "display_name": "新闻通讯",
    "description": "维护 Tushare 新闻通讯长文本数据。",
    "aliases": (),
}
```

说明：本数据集只有一个 Tushare 来源，不参与多源融合排序，因此不配置 `logical_key` / `logical_priority`。

### 3.2 `domain`

```python
"domain": {
    "domain_key": "news",
    "domain_display_name": "新闻资讯",
    "cadence": "intraday",
}
```

说明：新闻通讯按发布时间连续更新，但不保证每个来源每天都有数据。

### 3.3 `source`

```python
"source": {
    "source_key_default": "tushare",
    "source_keys": ("tushare",),
    "adapter_key": "tushare",
    "api_name": "major_news",
    "source_fields": ("title", "content", "pub_time", "src", "url"),
    "source_doc_id": "tushare.major_news",
    "request_builder_key": "_major_news_params",
    "base_params": {},
}
```

请求构造要求：

1. 必须通过 `source_fields` 向 Tushare payload 顶层 `fields` 传 `title,content,pub_time,src,url`，否则 `content` 和 `url` 不会返回。
2. `src` 不填时必须扇出真实来源枚举，不允许传 `__ALL__` 或模糊空值。
3. 时间由自然日点/范围转成源站 `start_date`、`end_date`。

### 3.4 `date_model`

```python
"date_model": {
    "date_axis": "natural_day",
    "bucket_rule": "not_applicable",
    "window_mode": "point_or_range",
    "input_shape": "trade_date_or_start_end",
    "observed_field": "pub_time",
    "audit_applicable": False,
    "not_applicable_reason": "新闻通讯按来源与发布时间采集，不保证每个自然日或每个来源都有数据。",
}
```

说明：

1. freshness 使用 `pub_time` 观测最近新闻发布时间。
2. 不启用日期完整性审计，避免把没有通讯稿的自然日误判为数据缺失。

### 3.5 `input_model`

| 字段 | 类型 | 是否必填 | 默认值 | 枚举值 | 是否多选 | 中文名 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `trade_date` | date | 否 | 无 | 无 | 否 | 处理日期 | 单日维护入口 |
| `start_date` | date | 否 | 无 | 无 | 否 | 开始日期 | 区间维护入口 |
| `end_date` | date | 否 | 无 | 无 | 否 | 结束日期 | 区间维护入口 |
| `src` | list | 否 | 无 | 见 1.1 | 是 | 新闻来源 | 不填表示按全部真实来源扇出 |

## 4. 表结构设计

### 4.1 raw 表

- 表名：`raw_tushare.major_news`
- ORM：`src/foundation/models/raw/raw_major_news.py`
- DAO：`raw_major_news`
- `target_table`：`core_serving_light.major_news`
- `delivery_mode`：`raw_with_serving_light_view`
- `layer_plan`：`raw->serving_light_view`
- `write_path`：`raw_only_upsert`

建议字段：

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | bigserial | PK | 内部行 ID |
| `src` | varchar(64) | not null | 新闻来源 |
| `pub_time` | timestamptz | not null | 发布时间 |
| `title` | text | nullable | 标题，源站可能为空 |
| `content` | text | nullable | 正文，源站定义为可空 |
| `url` | text | nullable | 原文链接，源站定义为可空 |
| `row_key_hash` | varchar(64) | unique not null | `api_name + src + pub_time + title + content + url` 的稳定哈希 |
| `fetched_at` | timestamptz | not null default now() | 抓取时间 |
| `raw_payload` | text | nullable | 原始行 JSON |

索引建议：

```sql
create unique index uq_raw_tushare_major_news_row_key_hash on raw_tushare.major_news(row_key_hash);
create index ix_raw_tushare_major_news_src_time on raw_tushare.major_news(src, pub_time desc);
create index ix_raw_tushare_major_news_time on raw_tushare.major_news(pub_time desc);
```

说明：

1. `title` 和 `content` 是新闻主体字段，允许单个为空，但不允许同时为空。
2. `url` 必须进入 `row_key_hash`。不能再使用旧口径 `src + pub_time + title + content`，否则同批次中不同链接的记录会被压成同一个 `row_key_hash`。
3. 不给 `title` / `content` 建普通索引。它们是长文本且可空，本轮只完成源站数据沉淀和 serving light 直出。

### 4.2 serving light view

V1 不复制一份新闻数据到 `core` 或 `core_serving` 物理表，直接建立普通 view：

- view：`core_serving_light.major_news`
- 来源：`raw_tushare.major_news`
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
            "新华网",
            "凤凰财经",
            "同花顺",
            "新浪财经",
            "华尔街见闻",
            "中证网",
            "财新网",
            "第一财经",
            "财联社",
        ),
    },
    "pagination_policy": "offset_limit",
    "page_limit": 400,
    "chunk_size": None,
    "max_units_per_execution": None,
    "unit_builder_key": "build_major_news_units",
}
```

说明：

1. `enum_fanout_defaults` 是“运营不选择新闻来源时”的默认真实来源清单。
2. 不填来源不代表传空值给 Tushare，也不代表传 `__ALL__`；planner 必须把来源拆成一组真实 `src` 值后逐个请求。

### 5.2 unit 拆分

新闻通讯接口单次最多 400 行，支持 `limit/offset` 循环读取。V1 按“来源 + 自然日”生成 unit：

1. `point` 模式：每个来源生成 1 个自然日 unit。
2. `range` 模式：按自然日逐日拆分，再按来源扇出。
3. 每个 unit 使用当天 `00:00:00 ~ 23:59:59` 的时间窗口。
4. source client 在该 unit 内按 `limit=400`、`offset=0/400/800...` 循环读取。
5. 当某页返回行数小于 400 时，该 unit 读取结束。

请求示例：

```json
{
  "dataset_key": "major_news",
  "action": "maintain",
  "time_input": {
    "mode": "point",
    "trade_date": "2026-04-24"
  },
  "filters": {
    "src": ["新华网", "财联社"]
  }
}
```

其中一个 Tushare 请求参数：

```json
{
  "src": "新华网",
  "start_date": "2026-04-24 00:00:00",
  "end_date": "2026-04-24 23:59:59",
  "fields": "title,content,pub_time,src,url",
  "limit": 400,
  "offset": 0
}
```

### 5.3 用户日期到 Tushare 参数转换

运营侧只选择自然日，不直接填写 Tushare 的 datetime 参数。系统内部按以下规则转换：

1. 用户选择单日时，`time_input.mode=point`，`trade_date` 表示要维护的自然日。
2. 用户选择区间时，`time_input.mode=range`，`start_date` 和 `end_date` 表示闭区间自然日。
3. planner 先把日期拆成逐日 unit，再按来源扇出。
4. 每个 unit 的自然日转换为 Tushare 请求参数：`start_date = 当天 00:00:00`，`end_date = 当天 23:59:59`。
5. 这里不使用交易日历；周末、节假日也按自然日处理，因为新闻通讯不是交易日数据。
6. freshness 观测使用源站返回的 `pub_time`，而不是用户输入日期。

单日示例：

```json
{
  "time_input": {
    "mode": "point",
    "trade_date": "2026-04-24"
  },
  "filters": {
    "src": ["新华网"]
  }
}
```

生成 1 个 unit，并请求：

```json
{
  "src": "新华网",
  "start_date": "2026-04-24 00:00:00",
  "end_date": "2026-04-24 23:59:59",
  "fields": "title,content,pub_time,src,url",
  "limit": 400,
  "offset": 0
}
```

区间示例：

```json
{
  "time_input": {
    "mode": "range",
    "start_date": "2026-04-20",
    "end_date": "2026-04-22"
  },
  "filters": {}
}
```

用户没有选择来源时，系统使用 `enum_fanout_defaults.src` 中的全部真实来源。这个例子会生成：

```text
3 个自然日 * 9 个来源 = 27 个 unit
```

其中“财联社 + 2026-04-21”这个 unit 的请求参数为：

```json
{
  "src": "财联社",
  "start_date": "2026-04-21 00:00:00",
  "end_date": "2026-04-21 23:59:59",
  "fields": "title,content,pub_time,src,url",
  "limit": 400,
  "offset": 0
}
```

分页继续在同一个 unit 内递增 `offset`：

```text
offset=0 -> offset=400 -> offset=800 -> ... -> 本页返回不足 400 行时结束
```

## 6. 清洗与质量

### 6.1 normalization

```python
"normalization": {
    "date_fields": (),
    "decimal_fields": (),
    "required_fields": ("src", "pub_time", "row_key_hash"),
    "row_transform_name": "_major_news_row_transform",
}
```

转换规则：

1. `pub_time` 由 `_major_news_row_transform` 按 Asia/Shanghai 语义解析后落 timestamptz；不放入通用 `date_fields`，因为通用 date parser 只适合日期，不适合保留时分秒。
2. `src`、`title`、`content`、`url` 去除首尾空白；空字符串按 `NULL` 保存。
3. `content` 可空，但如果字段不存在，应记录结构化问题，因为请求必须显式包含 `content`。
4. `title` 和 `content` 至少一个非空；两者同时为空时拒绝。
5. `row_key_hash = sha256(api_name|src|pub_time|title_or_empty|content_or_empty|url_or_empty)`。

### 6.2 quality

```python
"quality": {
    "reject_policy": "record_rejections",
    "required_fields": ("src", "pub_time", "row_key_hash"),
}
```

拒绝原因必须结构化：

| reason_key | 场景 |
| --- | --- |
| `normalize.required_field_missing:src` | 来源为空 |
| `normalize.required_field_missing:pub_time` | 发布时间为空 |
| `normalize.invalid_date:pub_time` | 发布时间无法解析 |
| `normalize.empty_not_allowed:title_content` | 标题和正文同时为空 |
| `normalize.required_field_missing:content` | 请求未返回 `content` 字段 |

## 7. 事务与写入量评估

```python
"transaction": {
    "commit_policy": "unit",
    "idempotent_write_required": True,
    "write_volume_assessment": "单 unit 为一个来源的一个自然日，按 limit=400/offset 分页取完该日全部通讯；单事务写入量按该 unit 全部返回行数计算。",
}
```

说明：

1. 每个 unit 独立提交。
2. 重复维护依靠 `row_key_hash` 幂等 upsert。
3. 状态写入失败不得回滚已提交的 raw 数据。

## 8. Ops 运营设计

### 8.1 手动任务

页面展示：

- 分组：`新闻资讯`
- 维护对象：`新闻通讯`
- 时间控件：自然日单日 / 自然日区间
- 筛选项：`新闻来源` 多选；默认不选等价于全选真实来源

用户不需要理解源站 `start_date/end_date` datetime 参数，也不需要理解 `fields` 参数。

### 8.2 任务详情

TaskRun 节点文案建议：

- 节点名称：`采集新闻通讯`
- unit 进度文案：`来源：新华网，日期：2026-04-24`
- 主指标：`已提交新闻条数`

不得展示 `fields`、`phase`、内部 request builder 名称等技术信息。

### 8.3 数据状态

- 最近同步：取 `max(pub_time)` 与成功时间派生后的 freshness 展示事实。
- 日期完整性：不展示完整性审计入口。

## 9. 测试与门禁

必须补充：

1. DatasetDefinition registry 测试覆盖 `major_news`。
2. source client 测试：必须验证 `fields="title,content,pub_time,src,url"` 来自 DatasetDefinition，并传给 connector。
3. unit planner 测试：默认来源全扇出，用户选择来源时只扇出所选来源。
4. row transform 测试：解析 `pub_time`、允许 `title/content` 单个为空、拒绝二者同时为空、生成 `row_key_hash`。
5. row transform 测试：`url` 不同必须生成不同 `row_key_hash`；不得保留“url 变化 hash 不变”的旧测试。
6. writer 测试：重复行 upsert 不重复插入。
7. Ops manual action API 测试：时间控件与来源枚举来自 DatasetDefinition。
8. 架构测试：不得出现 `__ALL__`、旧 sync 路由、旧 TaskRun 事实源。

### 9.1 上线与远程重建门禁

`major_news` 已经按旧 `row_key_hash` 口径写入过数据。完成开发并通过本地测试后，远程必须执行清表重建，不允许新旧 hash 口径混用：

1. 先发布新代码和迁移，确认 Alembic head 正确。
2. 执行数据库升级到 `20260501_000089` 或之后的 head；该迁移会重建 `raw_tushare.major_news` 表、索引和 `core_serving_light.major_news` view。
3. 不需要手动提前删除旧表；如果已经手动删除，迁移仍应能正常创建目标表和 view。
4. 重新同步指定日期或区间的 `major_news`。
5. 验证不再出现 `write.duplicate_conflict_key_in_batch:row_key_hash`。
6. 抽查同 `src/pub_time/title/content` 但不同 `url` 的记录，必须生成不同 `row_key_hash`。

这个重建步骤是 P0 门禁，不是可选清理项。旧表和旧 view 保留会导致现实数据与新唯一键口径不一致。

### 9.2 当前代码偏差清单

以下偏差来自当前代码核验，不是文档推测。进入实现前必须逐项收口，不能只修其中一个点：

| 范围 | 当前代码事实 | 目标口径 | 处理要求 |
| --- | --- | --- | --- |
| DatasetDefinition normalization | `major_news` 当前 `required_fields` 仍包含 `title` | `pub_time` 由 row transform 解析 timestamptz；`title` 可空，必填口径只保留 `src/pub_time/row_key_hash` | 更新 Definition，并同步 registry 测试 |
| DatasetDefinition quality | `quality.required_fields` 仍包含 `title` | `title` 和 `content` 至少一个非空，由 row transform 承担组合校验 | 不得把 `title` 写成单字段必填 |
| row transform | 当前缺 `content` 字段会拒绝；缺 `title` 也会拒绝 | 缺 `content` 字段仍记录结构化原因；但只有 `title` 与 `content` 同时为空才拒绝 | 去掉 `missing_title` 口径，改为 `missing_news_text` |
| row hash | 当前 hash 只包含 `src/pub_time/title/content` | hash 必须包含 `api_name/src/pub_time/title/content/url` | 修改实现与测试，删除“url 变化 hash 不变”的旧测试 |
| raw ORM | `RawMajorNews.title` 当前是 `nullable=False` | `title` 可空 | ORM 与 Alembic 必须一致 |
| serving light ORM | `MajorNewsLight.title` 当前是 `nullable=False` | view 输出允许 `title` 为空 | ORM 与 view 定义必须一致 |
| 初始 Alembic | `20260430_000086_add_major_news_dataset.py` 未建 `url`，且 `title TEXT NOT NULL` | 表结构从一开始就应包含 `url`，且 `title` 可空 | 若重写未上线迁移，初始迁移也要改到目标结构；不能只靠后续补丁掩盖 |
| 后续 Alembic | `20260501_000088_add_major_news_url.py` 只补 `url` 列和 view | 还需要处理 `title` 可空、旧 hash 口径数据、view 字段一致性 | 本地/远程必须按 9.1 清表重建；迁移脚本不能让旧 hash 数据继续混用 |
| reason codebook | 旧自定义 `missing_src/invalid_pub_time/missing_content_field/missing_news_text` 不是当前通用 reason codebook 口径 | 页面“查看原因”必须能显示中文原因和建议动作 | 使用已登记的通用 `normalize.*` reason_key，不新增任意命名的私有码 |
| request fields | `fields` 不在 `_major_news_params` 返回值里，而是由 `DatasetSourceClient -> connector.call(..., fields=definition.source.source_fields)` 传给 Tushare | 这是正确架构路径，但必须有测试覆盖，避免误以为 request builder 负责 `fields` | 测试应验证 connector payload 的 fields，而不是只看 request params |

### 9.3 实现改动面审计

本数据集的实现不是单文件修改。后续编码必须按以下范围逐项核验，尤其是表结构和写入路径：

| 类型 | 文件 | 检查/修改重点 |
| --- | --- | --- |
| DatasetDefinition | `src/foundation/datasets/definitions/news.py` | `major_news` 的 source fields、normalization、quality、planning、transaction 与本文一致 |
| Planner | `src/foundation/ingestion/unit_planner.py` | `build_major_news_units` 必须按自然日 + 真实来源扇出，不允许空来源或哨兵值 |
| Request builder | `src/foundation/ingestion/request_builders.py` | 只生成 `src/start_date/end_date`；不得把 `fields` 当业务参数拼进去 |
| Source client | `src/foundation/ingestion/source_client.py` | 确认 `definition.source.source_fields` 传给 connector；如源站不回 `src` 时才考虑按定义增加受控注入，不得随意拼字段 |
| Row transform | `src/foundation/ingestion/row_transforms.py` | 清洗 `title/content/url`，按组合规则拒绝，生成新 hash |
| Codebook | `src/foundation/ingestion/codebook.py` | 确认本数据集只使用已登记的通用结构化拒绝原因 |
| Raw model | `src/foundation/models/raw/raw_major_news.py` | `url`、`title nullable`、唯一键、索引与迁移一致 |
| Serving model | `src/foundation/models/core_serving_light/major_news.py` | view 模型字段和 nullable 口径与 raw/view 一致 |
| DAO | `src/foundation/dao/major_news_dao.py` | upsert 字段必须包含 `url`，冲突键只认新 `row_key_hash` |
| DAO factory | `src/foundation/dao/factory.py` | DAO 注册仍指向 `raw_major_news`，不得绕过 DatasetDefinition 写表 |
| Alembic | `alembic/versions/20260430_000086_add_major_news_dataset.py`、`alembic/versions/20260501_000088_add_major_news_url.py` | 表、view、title nullable、url、新旧 hash 数据清理策略必须一致 |
| Normalizer tests | `tests/test_dataset_normalizer.py` | 增加标题空/正文空/二者皆空/url 影响 hash；删除旧 hash 稳定测试 |
| Definition tests | `tests/test_dataset_definition_registry.py` | 覆盖 fields、nullable 口径、required_fields、enum defaults |
| Planner tests | `tests/test_dataset_action_resolver.py` | 覆盖默认来源全扇出与用户选择来源 |
| DAO tests | `tests/test_major_news_dao.py` | 覆盖 url 写入、upsert、不同 url 不冲突 |
| 架构门禁 | `tests/architecture/test_dataset_codebook_guardrails.py` | 确保新增 reason_code 不会绕过 codebook |

### 9.4 表结构升级口径

`major_news` 的表结构升级不能按“补一个字段”理解，因为唯一键事实也一起变了：

1. `url` 新增后必须进入 `row_key_hash`，这会导致同一条历史记录的新旧 hash 不一致。
2. `title` 从必填改为可空，ORM、迁移、view model、数据库实际表必须同时一致。
3. 已写入旧口径数据的环境必须清表重建，不能保留旧表继续 upsert。
4. 远程数据库操作只能在用户明确允许后执行；执行前必须再次核对当前 Alembic head、表结构、view 定义和待重建范围。
5. 重建后必须用真实同步小窗口验证：无批内冲突、`url` 可落库、空标题但有正文可落库、标题正文都空被拒绝且原因可展示。

验证命令：

```bash
python3 scripts/check_docs_integrity.py
pytest -q tests/test_dataset_definition_registry.py
pytest -q tests/foundation/ingestion
```

## 10. 当前评审口径

| 编号 | 决策点 | 口径 |
| --- | --- | --- |
| D1 | `news` domain | 已新增，中文名为“新闻资讯” |
| D2 | `major_news` 是否通过 serving light 直出 | 是，raw 写入后建立 `core_serving_light.major_news` 普通 view |
| D3 | 新闻来源默认行为 | 不填等价于全选真实来源，由 `enum_fanout_defaults` 显式扇出 |
| D4 | 分页策略 | 使用 `offset_limit`，`page_limit=400` |
| D5 | 是否加入日期完整性审计 | 否，只做 freshness 观测 |
| D6 | 用户日期如何转源站参数 | 运营输入自然日点/范围；系统逐日拆 unit，并转为 Tushare `start_date/end_date` datetime 窗口 |
