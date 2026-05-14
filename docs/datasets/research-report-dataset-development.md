# 券商研究报告数据集接入方案（已实施）

## 0. 方案边界

本方案记录 Tushare `research_report` 数据集接入的设计与当前实现口径。

依据：

- 仓库根规则：[AGENTS.md](/Users/congming/github/goldenshare/AGENTS.md)
- 数据集模板：[dataset-development-template.md](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)
- 源站文档：[0415_券商研究报告.md](/Users/congming/github/goldenshare/docs/sources/tushare/大模型语料专题数据/0415_券商研究报告.md)
- 参考实现：`src/foundation/datasets/definitions/market_equity.py` 中 `broker_recommend` 的券商推荐领域归属，以及 `src/foundation/datasets/definitions/news.py` 中文本类 raw + serving light 模式

禁止项：

1. 不做旧同步命令、旧 job_name 或兼容路由。
2. 不把 `limit/offset` 暴露为运营输入字段。
3. 不使用 `__ALL__` 之类占位值。
4. 不把样例里的 `file_name` 当作当前源站输出字段建表；真实返回和输出参数表均为 `title`。
5. 未完成最小真实同步和目标表行数对账前，不标记生产验收完成。

当前实现范围：

1. 已新增 `DatasetDefinition`、请求构造、归一化、raw ORM、serving light ORM、DAO 注册、Ops 展示目录项、Alembic 迁移与针对性测试。
2. V1 不新增工作流步骤，不接入日期完整性审计，不创建物理 serving 表。
3. 生产验收仍需在迁移应用后执行最小真实同步，并记录源端行数、归一化行数、写入行数、拒绝原因与目标表行数。

## 1. 基本信息

| 项 | 设计 |
| --- | --- |
| 数据集 key | `research_report` |
| 中文显示名 | 券商研究报告 |
| 所属定义文件 | `src/foundation/datasets/definitions/market_equity.py` |
| 底层领域 | `equity_market` / 股票行情，与 `broker_recommend` 保持一致 |
| Ops 展示分组 | `broker_recommendation` / 券商推荐 |
| Ops 展示顺序 | 排在 `broker_recommend` 后 |
| 数据源 | `tushare` |
| 源站 API | `research_report` |
| 源站 doc_id | `415` |
| 历史范围 | 源文档说明从 `20170101` 开始 |
| 更新频率 | 源文档说明增量每天两次更新 |
| 单次返回上限 | 1000 |
| 是否对外服务 | 是，raw 表沉淀后通过 `core_serving_light` view 直出 |
| 是否多源融合 | 否 |
| 是否纳入每日收盘后维护工作流 | 否 |
| 是否纳入日期完整性审计 | 否 |

说明：`DatasetDefinition.domain` 是底层领域事实，不等于 Ops 页面展示分组。本数据集按评审结论与“券商月度金股推荐”放到同一个底层 domain；运营入口展示在“券商推荐”分组。

## 2. 源站接口事实

### 2.1 输入参数

| 参数名 | 类型 | 必填 | 源站说明 | 类别 | 是否给运营填写 | V1 设计 |
| --- | --- | --- | --- | --- | --- | --- |
| `trade_date` | str | 否 | 研报日期，`YYYYMMDD` | 时间点 | 是 | 单日维护使用 |
| `start_date` | str | 否 | 研报开始日期 | 时间区间 | 是 | 区间维护使用 |
| `end_date` | str | 否 | 研报结束日期 | 时间区间 | 是 | 区间维护使用 |
| `report_type` | str | 否 | 研报类别：个股研报 / 行业研报 | 枚举过滤 | 是 | 可选过滤；用户多选时按真实枚举扇出，未选择时不传该参数 |
| `ts_code` | str | 否 | 股票代码 | 对象过滤 | 是 | 可选过滤，不默认扇出 |
| `inst_csname` | str | 否 | 券商名称 | 文本过滤 | 是 | 可选过滤，不默认扇出 |
| `ind_name` | str | 否 | 行业名称 | 文本过滤 | 是 | 可选过滤，不默认扇出 |
| `limit` | int | 否 | 单次返回数据长度 | 分页 | 否 | 系统生成 |
| `offset` | int | 否 | 请求数据开始位移量 | 分页 | 否 | 系统生成 |

V1 日期请求口径按你的建议设计：

1. 单点日期：平台 point 输入映射为源站 `trade_date=YYYYMMDD`。
2. 时间范围：平台 range 输入直接映射为源站 `start_date=YYYYMMDD`、`end_date=YYYYMMDD`。
3. 区间不逐日拆分，单个 range unit 内按 `limit/offset` 分页拉完后提交。

### 2.2 输出字段端到端对账

| 源站输出字段 | 源文档列出 | 真实样本返回 | `source_fields` | raw ORM | serving light | 是否必填 | 清洗规则 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `trade_date` | 是 | 是 | 是 | 是 | 是 | 是 | `YYYYMMDD` 转 `date` |
| `abstr` | 是 | 是 | 是 | 是 | 是 | 否 | 文本清理，空值落 `NULL` |
| `title` | 是 | 是 | 是 | 是 | 是 | 是 | 文本清理，空值拒绝 |
| `report_type` | 是 | 是 | 是 | 是 | 是 | 是 | 文本清理，建议限制为真实返回值 |
| `author` | 是 | 是 | 是 | 是 | 是 | 否 | 文本清理，空值落 `NULL` |
| `name` | 是 | 是 | 是 | 是 | 是 | 否 | 个股研报股票名称，行业研报可为空 |
| `ts_code` | 是 | 是 | 是 | 是 | 是 | 否 | 股票代码，行业研报可为空；非空时去空白并大写 |
| `inst_csname` | 是 | 是 | 是 | 是 | 是 | 是 | 券商简称，文本清理 |
| `ind_name` | 是 | 是 | 是 | 是 | 是 | 否 | 行业名称，空值落 `NULL` |
| `url` | 是 | 是 | 是 | 是 | 是 | 是 | 下载链接，文本清理，空值拒绝 |
| `report_code` | 是，默认不显示 | 是 | 是 | 是 | 是 | 否 | 研报唯一编码；非空时作为首选身份事实，空值时走兜底身份规则 |

字段差异结论：

1. 源文档输出参数表没有 `file_name`，样例代码和样例表出现了 `file_name`。
2. 真实请求中，即使额外请求 `file_name`，源端返回字段仍是 `title`，没有返回 `file_name`。
3. V1 只按输出参数表和真实返回落库：`title` 是报告文件名/标题事实字段，不新增 `file_name`。

`source_fields` 建议：

```python
(
    "trade_date",
    "abstr",
    "title",
    "report_type",
    "author",
    "name",
    "ts_code",
    "inst_csname",
    "ind_name",
    "url",
    "report_code",
)
```

### 2.3 源接口真实行为验证表

验证时间：2026-05-14。

| 请求形态 | 实际请求参数 | 源端返回行数 | 是否分页 | 关键样本字段 | 结论 |
| --- | --- | --- | --- | --- | --- |
| 不传业务参数 | `{limit: 3, offset: 0}` | 3 | 是 | `trade_date=20260513`, `report_code=AP202605121822229289` | 默认可返回最新页，但不作为全集维护策略 |
| 只传对象过滤 | `{ts_code: 603659.SH, limit: 3, offset: 0}` | 3 | 是 | `ts_code=603659.SH`, `report_type=个股研报` | 可按股票代码过滤 |
| 只传时间点 | `{trade_date: 20260121, limit: 3, offset: 0}` | 3 | 是 | `trade_date=20260121`, `report_code=AP202601211818173194` | 单日日期参数有效 |
| 传时间区间 | `{start_date: 20260121, end_date: 20260121, limit: 3, offset: 0}` | 3 | 是 | 与同日 point 返回同类字段 | 区间参数有效；单日窗口与 point 口径一致 |
| 枚举过滤 | `{trade_date: 20260121, report_type: 个股研报, limit: 3, offset: 0}` | 3 | 是 | `report_type=个股研报` | `report_type` 可作为可选过滤 |
| 分页第二页 | `{trade_date: 20260121, limit: 2, offset: 2}` | 2 | 是 | 第二页样本 `report_code=AP202601211818173194` | offset 生效 |
| 额外请求 `file_name` | `fields` 追加 `file_name` | 3 | 是 | 返回字段仍无 `file_name` | 不建 `file_name` 字段 |

注意：源接口需要单独开权限；当前本地 token 已能请求成功。后续环境如果没有权限，应在部署验收前单独确认。

## 3. 三层语义拆分

| 语义层 | 本数据集答案 | 是否已核验 |
| --- | --- | --- |
| 时间输入语义 | 运营提交研报发布自然日单日或自然日区间。单日用 `trade_date`，区间用 `start_date/end_date`。 | 已用源文档和真实请求核验 |
| 执行 / unit 语义 | point 生成 1 个自然日 unit；range 生成 1 个区间 unit，不逐日展开；单个 unit 内按 `limit/offset` 分页拉完后提交。 | 已按你的口径确认，编码前需核验 generic unit planner 行为 |
| freshness / audit 语义 | 最近观测字段为 `trade_date`；不做日期完整性审计，因为研究报告不是每天一定有每只股票/每个行业数据。 | 已按源接口语义确认 |

`bucket_rule=not_applicable` 在本数据集里的含义是：退出连续日期完整性审计，但仍支持自然日 point/range 输入。

## 4. DatasetDefinition 设计

### 4.1 identity

```python
"identity": {
    "dataset_key": "research_report",
    "display_name": "券商研究报告",
    "description": "维护 Tushare 券商研究报告数据，保留研报摘要、标题、机构、作者、股票/行业、下载链接与唯一编码。",
    "aliases": (),
}
```

### 4.2 domain

按评审结论，与 `broker_recommend` 保持同一底层 domain：

```python
"domain": {
    "domain_key": "equity_market",
    "domain_display_name": "股票行情",
    "cadence": "daily",
}
```

原因：本数据集与“券商月度金股推荐”同属券商研究类运营对象。注意：底层 domain 只表达系统领域归属；Ops 用户可见分组仍固定到“券商推荐”。

### 4.3 source

```python
"source": {
    "source_key_default": "tushare",
    "source_keys": ("tushare",),
    "adapter_key": "tushare",
    "api_name": "research_report",
    "source_fields": (
        "trade_date",
        "abstr",
        "title",
        "report_type",
        "author",
        "name",
        "ts_code",
        "inst_csname",
        "ind_name",
        "url",
        "report_code",
    ),
    "source_doc_id": "tushare.research_report",
    "request_builder_key": "_research_report_params",
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
    "observed_field": "trade_date",
    "audit_applicable": False,
    "not_applicable_reason": "券商研究报告按研报发布日采集，但不保证每个自然日都有数据，也不要求按连续日期桶做完整性审计。",
}
```

### 4.5 input_model

| 字段 | 类型 | 必填 | 默认值 | 多选 | 中文名 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `trade_date` | date | 否 | 无 | 否 | 处理日期 | 单日维护入口，映射源站 `trade_date` |
| `start_date` | date | 否 | 无 | 否 | 开始日期 | 区间维护入口，映射源站 `start_date` |
| `end_date` | date | 否 | 无 | 否 | 结束日期 | 区间维护入口，映射源站 `end_date` |
| `report_type` | list | 否 | 无 | 是 | 研报类别 | 可选过滤；枚举 `个股研报`、`行业研报`；未选择时不传该参数 |
| `ts_code` | string | 否 | 无 | 否 | 股票代码 | 可选过滤 |
| `inst_csname` | string | 否 | 无 | 否 | 券商名称 | 可选过滤 |
| `ind_name` | string | 否 | 无 | 否 | 行业名称 | 可选过滤 |

`limit/offset` 不进入 `input_model`，只由分页链路生成。

## 5. 存储设计

### 5.1 raw 表

- 表名：`raw_tushare.research_report`
- ORM：`src/foundation/models/raw/raw_research_report.py`
- DAO：使用 `RowKeyHashDAO`，表保留 surrogate 自增 `id`，幂等冲突键为 `row_key_hash`；该模式与 `anns_d` / `irm_qa_*` 等 raw + serving light 数据集保持一致。
- 写入路径：`raw_only_upsert`
- delivery mode：`raw_with_serving_light_view`
- 幂等键：`row_key_hash`

建议字段：

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | bigserial | primary key | 物理自增主键，不参与业务身份 |
| `row_key_hash` | varchar(64) | unique not null | 稳定行身份；优先由 `report_code` 生成，缺失时由兜底字段生成 |
| `report_code` | varchar(64) | nullable | 研报唯一编码，源站输出；非空时建议建 partial unique index |
| `trade_date` | date | not null | 研报发布时间 |
| `abstr` | text | nullable | 研报摘要 |
| `title` | text | not null | 研报标题/文件名 |
| `report_type` | varchar(32) | not null | 研报类别 |
| `author` | text | nullable | 作者 |
| `name` | varchar(128) | nullable | 股票名称，行业研报可为空 |
| `ts_code` | varchar(32) | nullable | 股票代码，行业研报可为空 |
| `inst_csname` | varchar(128) | not null | 机构简称 |
| `ind_name` | varchar(128) | nullable | 行业名称 |
| `url` | text | not null | 下载链接 |
| `api_name` | varchar(32) | not null default `'research_report'` | 源接口 |
| `fetched_at` | timestamptz | not null default now() | 抓取时间 |
| `raw_payload` | text | nullable | 原始行 JSON |

建议索引：

```sql
create index idx_raw_tushare_research_report_trade_date
on raw_tushare.research_report(trade_date);

create unique index uq_raw_tushare_research_report_report_code
on raw_tushare.research_report(report_code)
where report_code is not null;

create index idx_raw_tushare_research_report_ts_code_date
on raw_tushare.research_report(ts_code, trade_date);

create index idx_raw_tushare_research_report_inst_date
on raw_tushare.research_report(inst_csname, trade_date);

create index idx_raw_tushare_research_report_type_date
on raw_tushare.research_report(report_type, trade_date);
```

防 null 设计：

1. `trade_date`、`title`、`report_type`、`inst_csname`、`url` 必填。
2. `ts_code` 和 `name` 必须允许为空，因为行业研报样本中这两个字段为空。
3. `ind_name` 必须允许为空，不能作为主键组成部分。
4. `ts_code` 允许为空，`ts_code + trade_date` 索引只用于常见按股票过滤查询；业务身份不依赖 `ts_code`。
5. `report_code` 允许为空；非空时作为首选身份事实，空值时使用兜底身份规则。

身份键规则：

```text
report_code 非空：
row_key_hash = sha256("research_report" + "report_code" + report_code)

report_code 为空：
row_key_hash = sha256("research_report" + "fallback" + trade_date + title + report_type + inst_csname + author + ts_code + ind_name + url)
```

这样做的目的：

1. 源站给 `report_code` 时，身份事实等价于使用 `report_code`。
2. 源站偶发缺 `report_code` 时，不会因为主键为空直接丢弃整行。
3. 兜底身份仍基于源站真实字段，不引入业务占位值。

### 5.2 serving light view

- view：`core_serving_light.research_report`
- 来源：`raw_tushare.research_report`
- 字段：`row_key_hash, report_code, trade_date, abstr, title, report_type, author, name, ts_code, inst_csname, ind_name, url, source, fetched_at`
- 不新增 core 物理表。

原因：摘要和标题是文本型内容，raw 已经是精准复刻；serving light view 足以供查询和页面展示，避免重复存储大文本。

## 6. 执行链路设计

| 环节 | 设计 |
| --- | --- |
| unit builder | 使用现有 `generic` unit planner；point 生成 1 个自然日 unit；range 在 `bucket_rule=not_applicable` 下生成 1 个区间 unit，不逐日展开 |
| request builder | 新增 `_research_report_params`；point 输出 `trade_date=YYYYMMDD`；range 输出 `start_date/end_date`；可选附加 `report_type/ts_code/inst_csname/ind_name` |
| pagination | `offset_limit`，`page_limit=1000` |
| normalizer | 新增 `_research_report_row_transform`，清理文本、解析 `trade_date`、规范非空 `ts_code`、拒绝缺关键字段行 |
| writer | raw upsert，冲突列/主键 `row_key_hash` |
| transaction | `commit_policy=unit`，单个 unit 的所有分页拉完、归一化、写入后提交 |

事务评估：point 的单个事务写入量等于一个自然日全部研报；range 的单个事务写入量等于输入区间全部研报。编码前应使用高峰日期和典型区间复核写入量，不按“单页 1000”误判事务规模。

## 7. Ops 与页面

| 消费方 | 方案 |
| --- | --- |
| 数据源卡片 | 展示在“券商推荐”分组，名称“券商研究报告” |
| 手动任务 | 支持单日、区间；可选研报类别、股票代码、券商名称、行业名称过滤 |
| 自动任务 | 不纳入每日收盘后维护工作流；如后续需要独立自动任务，单独评审 |
| 工作流 | V1 不挂入“每日收盘后维护” |
| 任务详情 | 处理范围显示研报日期或区间；不展示内部执行路径 |
| 日期完整性审计 | 不接入 |
| freshness | 最近同步展示来自 `trade_date` 与 TaskRun 健康，不按连续日判缺失 |

## 8. DatasetDefinition 消费者审计清单

| 消费方 | 本次影响 | 需要怎么改 | 编码前核验位置 |
| --- | --- | --- | --- |
| manual actions | 新增 point/range 数据集 | 时间控件支持单日/区间，可选过滤字段显示 | `src/ops` 派生 action、前端手动任务页面 |
| catalog | 新增展示目录项 | 必须配置 Ops 展示分组，否则测试失败 | `src/ops/catalog/dataset_catalog_views.py` |
| workflow | 不纳入每日收盘后维护 | 不新增 workflow step | `src/ops/action_catalog.py` |
| resolver / unit planner | 新增 generic point/range unit | 确认 range 不逐日展开 | `src/foundation/ingestion/unit_planner.py` |
| request builder | 新增参数映射 | 新增 `_research_report_params` | `src/foundation/ingestion/request_builders.py` |
| freshness | 新增 observed field | 使用 `trade_date`，audit 不适用 | freshness / snapshot 服务 |
| dataset cards | 新增卡片 | 最近同步来自 `trade_date` 与运行健康 | dataset status projection |
| snapshot rebuild | 新增 dataset projection | raw + light 两层状态 | snapshot rebuild 服务 |
| date completeness audit | 不接入 | `audit_applicable=False` | date completeness audit |
| 自动任务 / calendar policy | 不纳入每日收盘后维护 | 本轮不新增固定 workflow step | schedule/action catalog |
| 前端时间控件 | 新增 point/range + filters | 不允许页面自行拼请求字段 | manual task UI |
| 测试与文档 | 新增覆盖 | definition、resolver、source client、normalizer、DAO、workflow、catalog | `tests/**` |

## 9. 测试与验收要求

编码时至少补充：

1. `tests/test_dataset_definition_registry.py`：Definition 事实投影。
2. `tests/test_dataset_action_resolver.py`：point 生成 `trade_date`，range 生成 `start_date/end_date`，range 不逐日展开。
3. source client 测试：connector payload 的 `fields` 包含全部 11 个源字段，不包含 `file_name`。
4. request builder 测试：确认可选过滤字段只在用户传入时出现。
5. normalizer 测试：`trade_date` 解析、`ts_code` 可空、`report_code/title/url` 缺失拒绝。
6. DAO/writer 测试：以 `row_key_hash` 幂等 upsert，覆盖 `report_code` 非空和为空兜底两种身份规则。
7. Ops catalog 测试：缺展示目录配置失败。
8. workflow 测试：确认每日收盘后维护不包含 `research_report`。

当前已落地的自动化覆盖：

1. `tests/test_dataset_definition_registry.py`：Definition 事实投影、过滤字段、raw/light 存储口径。
2. `tests/test_dataset_action_resolver.py`：point/range 请求参数、`report_type` 多选扇出、range 不逐日展开。
3. `tests/test_dataset_source_client.py`：分页参数与 11 个源字段传递。
4. `tests/test_dataset_normalizer.py`：`report_code` 身份、缺编码兜底身份、缺关键字段拒绝。
5. `tests/test_fields_constants.py`：源字段全量对账。
6. `tests/architecture/test_dataset_runtime_registry_guardrails.py`：定义域矩阵守卫。
7. `tests/test_ops_action_catalog.py`：Ops 展示分组与未挂入 workflow 的范围守卫。

本轮最小真实源端验证：

| 项 | 结果 |
| --- | --- |
| 验证时间 | 2026-05-14 |
| 请求 | `trade_date=20260121`, `report_type=个股研报` |
| unit 数 | 1 |
| 源端返回 | 27 行 |
| 归一化成功 | 27 行 |
| 拒绝 | 0 行 |
| 返回字段 | 覆盖 `trade_date/abstr/title/report_type/author/name/ts_code/inst_csname/ind_name/url/report_code` |
| 样本 `report_code` | `AP202601211818182045` |

真实同步验收必须记录：

| 指标 | 要求 |
| --- | --- |
| source fetched | 与 Tushare 同参数返回一致 |
| normalized | 等于 fetched 减结构化 reject |
| written | 与目标表新增/更新结果可解释 |
| rejected | 必须列出 reason code 和样本 |
| target count | 与 `row_key_hash` 去重后可解释；`report_code` 非空样本需能追溯到同一身份 |

## 10. 已拍板项

| 编号 | 问题 | 当前结论 |
| --- | --- | --- |
| D1 | 底层 `domain` 放哪里 | 已确认：与券商月度金股推荐放到同一 domain，即 `equity_market / 股票行情` |
| D2 | Ops 展示分组放哪里 | 已确认：`broker_recommendation / 券商推荐` |
| D3 | 是否纳入“每日收盘后维护”工作流 | 已确认：不纳入 |
| D4 | 是否开放可选过滤 | 已确认：开放 `report_type/ts_code/inst_csname/ind_name`，全部为可选过滤 |
| D5 | 是否使用 `report_code` 作为主键 | 已确认：优先使用 `report_code` 生成身份键；`report_code` 为空时使用稳定字段兜底生成 `row_key_hash` |
| D6 | 是否创建物理 serving 表 | 已确认：不创建，只建 `core_serving_light` view，避免大文本重复存储 |
