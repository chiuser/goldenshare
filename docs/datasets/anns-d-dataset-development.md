# 上市公司全量公告数据集接入方案（已按评审口径实现）

## 0. 方案边界

本方案记录 Tushare `anns_d` 数据集接入口径、实现边界与验收要求。

依据：

- 仓库根规则：[AGENTS.md](/Users/congming/github/goldenshare/AGENTS.md)
- 数据集模板：[dataset-development-template.md](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)
- 源站文档：[0176_上市公司全量公告.md](/Users/congming/github/goldenshare/docs/sources/tushare/大模型语料/0176_上市公司全量公告.md)
- 参考实现：`src/foundation/datasets/definitions/news.py` 中 `major_news` / `news` 的 raw + serving light 模式

禁止项：

1. 不做旧同步命令、旧任务标识或兼容路由。
2. 不把源端可选参数自动暴露给运营。
3. 不用 `__ALL__` 之类占位值。
4. 未完成真实请求验证前，不允许标记开发完成。

## 1. 基本信息

| 项 | 设计 |
| --- | --- |
| 数据集 key | `anns_d` |
| 中文显示名 | 上市公司公告 |
| 所属定义文件 | `src/foundation/datasets/definitions/news.py` |
| 底层领域 | `news` / 新闻资讯 |
| Ops 展示分组 | `news` / 新闻资讯 |
| Ops 展示顺序建议 | `40`，排在 `news` 后 |
| 数据源 | `tushare` |
| 源站 API | `anns_d` |
| 源站 doc_id | `176` |
| 是否对外服务 | 是，raw 表沉淀后通过 `core_serving_light` view 直出 |
| 是否多源融合 | 否 |
| 是否纳入自动任务 | 是，V1 挂入“每日收盘后维护”工作流 |
| 是否纳入日期完整性审计 | 否 |

说明：`DatasetDefinition.domain` 只是底层领域事实。页面分组统一走 `src/ops/catalog/dataset_catalog_views.py`，不能为了 UI 分组改 domain。

## 2. 源站接口事实

### 2.1 输入参数

| 参数名 | 类型 | 必填 | 源站说明 | 类别 | 是否给运营填写 | V1 设计 |
| --- | --- | --- | --- | --- | --- | --- |
| `ts_code` | str | 否 | 股票代码 | 对象过滤 | 是 | 可选过滤字段，不作为默认 fan-out |
| `ann_date` | str | 否 | 公告日期，`YYYYMMDD` | 时间点 | 否 | V1 不采用，避免同一数据集同时存在两套时间请求口径 |
| `start_date` | str | 否 | 公告开始日期 | 时间区间 | 是 | 源站请求统一使用；单日时等于所选日期 |
| `end_date` | str | 否 | 公告结束日期 | 时间区间 | 是 | 源站请求统一使用；单日时等于所选日期 |
| `limit` | int | 否 | 分页大小 | 分页 | 否 | 系统生成 |
| `offset` | int | 否 | 分页偏移 | 分页 | 否 | 系统生成 |

源站文档写明“单次最大 2000 条，可以根据日期循环获取全量”。V1 统一只向 Tushare 传 `start_date/end_date`：

1. 单日维护：`start_date=所选日期`，`end_date=所选日期`。
2. 区间维护：`start_date=区间开始日期`，`end_date=区间结束日期`。
3. 不使用源站 `ann_date` 入参。
4. `limit/offset` 只属于系统分页参数，不进入 `input_model`，也不让运营填写。

### 2.2 输出字段端到端对账

| 源站输出字段 | 源文档列出 | `source_fields` | raw ORM | serving light | 是否必填 | 清洗规则 |
| --- | --- | --- | --- | --- | --- | --- |
| `ann_date` | 是 | 是 | 是 | 是 | 是 | `YYYYMMDD` 转 `date`，伪空值拒绝 |
| `ts_code` | 是 | 是 | 是 | 是 | 是 | 去首尾空白，保持源站代码 |
| `name` | 是 | 是 | 是 | 是 | 否 | 文本清理，空值落 `NULL` |
| `title` | 是 | 是 | 是 | 是 | 是 | 文本清理，空值拒绝 |
| `url` | 是 | 是 | 是 | 是 | 是 | 文本清理，空值拒绝，参与行身份 |
| `rec_time` | 是 | 是 | 是 | 是 | 是 | 源站格式如 `2026-05-14 08:30:01`；按北京时间解析为 `timestamptz`，空值拒绝 |

注意：源文档样例只展示了 4 列，但输出参数表包含 `url` 和 `rec_time`。`source_fields` 必须显式请求全部 6 个字段，不能只按样例列建表。

### 2.3 源接口真实行为验证表（首次真实同步验收时补齐）

| 请求形态 | 实际请求参数 | 源端返回行数 | 是否分页 | 关键样本字段 | 结论 |
| --- | --- | --- | --- | --- | --- |
| 不传业务参数 | `{limit: 5, offset: 0}` | 5 | 是 | `ann_date/url/rec_time` | 返回字段完整，只能说明默认页可取，不作为主链全集策略 |
| 只传对象过滤 | `ts_code=603051.SH, limit=5, offset=0` | 5 | 是 | `ts_code` | 可按对象过滤 |
| 只传时间点 | `start_date=20260512, end_date=20260512, limit=5, offset=0` | 5 | 是 | `ann_date=20260512` | 单日日期窗口有效 |
| 传时间区间 | `start_date=20260512, end_date=20260512, limit=5, offset=0` | 5 | 是 | `ann_date=20260512` | 区间参数有效；单日窗口与 point 口径一致 |
| 分页第二页 | `start_date=20260513, end_date=20260514, limit=2, offset=2` | 2 | 是 | `url` | offset 生效 |
| 源站 `ann_date` 参数 | 未纳入主链验证 | 不适用 | 不适用 | 不适用 | V1 主链不采用 |

当前实现按 `start_date/end_date` 作为唯一源站时间请求口径。不传业务参数只用于源端探测，不作为主链全集拉取策略；首次真实同步验收时仍需记录 fetched、normalized、written、rejected 与目标表行数。

## 3. 三层语义拆分

| 语义层 | 本数据集答案 | 核验依据 |
| --- | --- | --- |
| 时间输入语义 | 运营提交公告自然日单日或自然日区间；源站请求统一落到 `start_date/end_date`；`ts_code` 只是可选过滤。 | 源文档提供 `start_date/end_date`，并说明可根据日期获取全量。真实请求待 M0 补证。 |
| 执行 / unit 语义 | point 生成 1 个自然日 unit，请求 `start_date=end_date=该日`；range 不逐日扇开，而是生成 1 个区间 unit，请求 `start_date=区间开始`、`end_date=区间结束`，分页拉完整个区间后按 unit 提交。 | 本轮评审确认：区间作为整体请求源站，不按日拆分。 |
| freshness / audit 语义 | 用 `ann_date` 作为最近观测日期；不做日期完整性审计。 | 公告是事件型数据，不应把没有公告的自然日判为缺失。 |

`bucket_rule=not_applicable` 在本数据集里的含义是：退出连续日期完整性判断，但仍支持自然日 point/range 输入。

## 4. DatasetDefinition 设计

### 4.1 identity

```python
"identity": {
    "dataset_key": "anns_d",
    "display_name": "上市公司公告",
    "description": "维护 Tushare 上市公司全量公告数据，保留公告标题、股票代码、原文 PDF URL 与发布时间。",
    "aliases": (),
}
```

### 4.2 domain

```python
"domain": {
    "domain_key": "news",
    "domain_display_name": "新闻资讯",
}
```

`freshness_policy`：`event_run_trace`，在 `src/foundation/datasets/freshness_policies.py` 集中登记，不写入 `domain`。

### 4.3 source

```python
"source": {
    "source_key_default": "tushare",
    "source_keys": ("tushare",),
    "adapter_key": "tushare",
    "api_name": "anns_d",
    "source_fields": ("ann_date", "ts_code", "name", "title", "url", "rec_time"),
    "source_doc_id": "tushare.anns_d",
    "request_builder_key": "_anns_d_params",
    "base_params": {},
}
```

### 4.4 date_model

```python
"date_model": {
    "date_axis": "natural_day",
    "bucket_rule": "not_applicable",
    "window_mode": "point_or_range",
    "input_shape": "trade_date_or_start_end",
    "observed_field": "ann_date",
    "audit_applicable": False,
    "not_applicable_reason": "上市公司公告是事件型数据，不保证每个自然日都有公告。",
}
```

### 4.5 input_model

| 字段 | 类型 | 必填 | 默认值 | 多选 | 中文名 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `trade_date` | date | 否 | 无 | 否 | 处理日期 | 平台 point 意图字段；源站请求映射为 `start_date=end_date=trade_date` |
| `start_date` | date | 否 | 无 | 否 | 开始日期 | 区间维护入口；源站请求直接映射为 `start_date` |
| `end_date` | date | 否 | 无 | 否 | 结束日期 | 区间维护入口；源站请求直接映射为 `end_date` |
| `ts_code` | string | 否 | 无 | 否 | 股票代码 | 可选过滤，不默认扇出股票池 |

`limit/offset` 不属于 `input_model`。它们是系统分页参数，由 executor/request 分页链路生成，不能让运营填写。

## 5. 存储设计

### 5.1 raw 表

- 表名：`raw_tushare.anns_d`
- ORM 建议：`src/foundation/models/raw/raw_anns_d.py`
- DAO 建议：`raw_anns_d`
- 写入路径：`raw_only_upsert`
- delivery mode：`raw_with_serving_light_view`
- 幂等键：`row_key_hash`

建议字段：

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | bigserial | PK | 内部行 ID |
| `ann_date` | date | not null | 公告日期 |
| `ts_code` | varchar(32) | not null | 股票代码，保持源站返回 |
| `name` | varchar(128) | nullable | 股票名称 |
| `title` | text | not null | 公告标题 |
| `url` | text | not null | 原文 PDF URL |
| `rec_time` | timestamptz | not null | 发布时间；源站字符串格式如 `2026-05-14 08:30:01`，normalizer 按 Asia/Shanghai 解析 |
| `row_key_hash` | varchar(64) | unique not null | 稳定行身份 |
| `api_name` | varchar(32) | not null default `'anns_d'` | 源接口 |
| `fetched_at` | timestamptz | not null default now() | 抓取时间 |
| `raw_payload` | text | nullable | 原始行 JSON |

建议索引：

```sql
create unique index uq_raw_tushare_anns_d_row_key_hash
on raw_tushare.anns_d(row_key_hash);

create index idx_raw_tushare_anns_d_date
on raw_tushare.anns_d(ann_date desc);

create index idx_raw_tushare_anns_d_code_date
on raw_tushare.anns_d(ts_code, ann_date desc);
```

`row_key_hash` 建议使用：

```text
anns_d + ann_date + ts_code + title + url + rec_time
```

原因：源站没有公告 ID，`url` 是区分公告原文的关键事实，必须参与行身份。

### 5.2 serving light view

- view：`core_serving_light.anns_d`
- 来源：`raw_tushare.anns_d`
- 字段：`row_key_hash, ann_date, ts_code, name, title, url, rec_time, source, fetched_at`
- 不新增 core 或 serving 物理表，只创建 view，避免文本类数据重复存储。

## 6. 执行链路设计

| 环节 | 设计 |
| --- | --- |
| unit builder | 使用现有 `generic` unit planner；point 生成 1 个自然日 unit；range 在 `bucket_rule=not_applicable` 下生成 1 个区间 unit，不逐日展开 |
| request builder | `_anns_d_params` 仅被 `anns_d` 的 `DatasetDefinition.source.request_builder_key` 引用；point 输出 `start_date=end_date=YYYYMMDD`；range 输出 `start_date/end_date`；可选附加 `ts_code`；不输出 `ann_date` |
| pagination | `offset_limit`，`page_limit=2000` |
| normalizer | 新增 `_anns_d_row_transform`，清理文本、解析 `ann_date/rec_time`、生成 `row_key_hash` |
| writer | raw DAO upsert，冲突列 `row_key_hash` |
| transaction | `commit_policy=unit`，单个 unit 的所有分页拉完、归一化、写入后提交 |

事务评估：point 的单个事务写入量等于一个公告自然日的全部公告行数；range 的单个事务写入量等于整个区间返回行数。首次真实同步验收必须用近期高公告日和典型区间样本复核写入量，不能只按接口单页 2000 条推断。

## 7. Ops 与页面

| 消费方 | 方案 |
| --- | --- |
| 数据源卡片 | 展示在“新闻资讯”分组，名称“上市公司公告” |
| 手动任务 | 支持单日、区间；可选股票代码过滤 |
| 自动任务 | 支持配置，并在 V1 挂入“每日收盘后维护”工作流 |
| 工作流 | 每日收盘后维护按当天日期触发，request builder 映射为 `start_date=end_date=当天` |
| 任务详情 | 处理范围显示公告日期或日期区间；不展示旧执行路径 |
| 日期完整性审计 | 不接入 |
| freshness | 最近同步展示来自 `ann_date` 与 TaskRun 健康，不按连续日判滞后 |

## 8. 测试与验收

已补充自动化覆盖：

1. `tests/test_dataset_definition_registry.py`：Definition 事实投影。
2. `tests/test_dataset_action_resolver.py`：证明 `unit_builder_key=generic` 时，point 生成 1 个自然日 unit，range 生成 1 个区间 unit。
3. request builder 测试：确认只生成 `start_date/end_date/ts_code/limit/offset`，不生成 `ann_date` 或源站不需要的 `trade_date`。
4. source client 测试：确认 connector payload 的 `fields` 包含全部 6 个源字段。
5. normalizer 测试：日期解析、`rec_time` 必填、缺 `rec_time/url/title` 拒绝、`row_key_hash` 稳定。
6. DAO 测试：upsert 不更新自增 ID。
7. Ops catalog 测试：缺展示目录配置应失败。
8. workflow 测试：每日收盘后维护触发时，`anns_d` 使用当天 `start_date=end_date`。

真实同步验收必须记录：

| 指标 | 要求 |
| --- | --- |
| source fetched | 与 Tushare 同参数返回一致 |
| normalized | 等于 fetched 减结构化 reject |
| written | 与目标表新增/更新结果可解释 |
| rejected | 必须列出 reason code 和样本 |
| target count | 与 `row_key_hash` 去重后可解释 |

## 9. 已拍板项

| 编号 | 问题 | 当前结论 |
| --- | --- | --- |
| D1 | V1 是否挂入现有 workflow | 已确认：挂入“每日收盘后维护”工作流，日期映射为 `start_date=end_date`。 |
| D2 | 是否允许 `ts_code` 作为运营过滤 | 已确认：允许，且是可选项、非必选。 |
| D3 | “按日期查”和“不传日期查”的结果是否一致 | 已确认：你已完成测试，结果一致。V1 固定使用 `start_date/end_date`，不再把 no-param snapshot 作为待拍板风险。 |
| D4 | 是否对 `rec_time` 做必填 | 已确认：`rec_time` 必填，必须落库。 |
