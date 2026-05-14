# 深证互动易问答数据集接入方案（已按评审口径实现）

## 0. 方案边界

本方案记录 Tushare `irm_qa_sz` 数据集接入口径、实现边界与验收要求。

依据：

- 仓库根规则：[AGENTS.md](/Users/congming/github/goldenshare/AGENTS.md)
- 数据集模板：[dataset-development-template.md](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)
- 源站文档：[0367_深证互动易.md](/Users/congming/github/goldenshare/docs/sources/tushare/大模型语料专题数据/0367_深证互动易.md)
- 参考实现：`src/foundation/datasets/definitions/news.py` 中新闻文本类数据集

重要源文档问题：

1. 输入参数表里 `pub_date` 出现两次，分别描述“发布开始日期”和“发布结束日期”，但参数名相同。
2. 示例代码里的 `ann_date` 是源文档错误，输入参数表没有该参数；V1 忽略这处错误，不进入方案。
3. 样例 Markdown 中问答文本包含 `|`，导致表格看起来错列。实现必须以接口返回 DataFrame 字段为准，不能按样例渲染列位猜字段。
4. V1 不开放 `pub_date` 过滤；未来如需支持，必须单独评审，不在本轮夹带。

## 1. 基本信息

| 项 | 设计 |
| --- | --- |
| 数据集 key | `irm_qa_sz` |
| 中文显示名 | 深证互动易问答 |
| 所属定义文件 | `src/foundation/datasets/definitions/news.py` |
| 底层领域 | `news` / 新闻资讯 |
| Ops 展示分组 | `news` / 新闻资讯 |
| Ops 展示顺序建议 | `60`，排在 `irm_qa_sh` 后 |
| 数据源 | `tushare` |
| 源站 API | `irm_qa_sz` |
| 源站 doc_id | `367` |
| 历史范围 | 源文档说明从 2010 年 10 月开始 |
| 是否对外服务 | 是，raw 表沉淀后通过 `core_serving_light` view 直出 |
| 是否多源融合 | 否 |
| 是否纳入自动任务 | 是，V1 挂入“每日收盘后维护”工作流 |
| 是否纳入日期完整性审计 | 否 |

## 2. 源站接口事实

### 2.1 输入参数

| 参数名 | 类型 | 必填 | 源站说明 | 类别 | 是否给运营填写 | V1 设计 |
| --- | --- | --- | --- | --- | --- | --- |
| `ts_code` | str | 否 | 股票代码 | 对象过滤 | 是 | 可选过滤字段，不作为默认股票池 fan-out |
| `trade_date` | str | 否 | 交易日期，`YYYYMMDD` | 时间点 | 是 | 单日维护使用 |
| `start_date` | str | 否 | 开始日期 | 时间区间 | 是 | 区间维护使用，直接传给源站 |
| `end_date` | str | 否 | 结束日期 | 时间区间 | 是 | 区间维护使用，直接传给源站 |
| `pub_date` | str | 否 | 文档同时写成发布开始日期和发布结束日期 | 时间过滤 | 否 | V1 不开放 |
| `limit` | int | 否 | 分页大小 | 分页 | 否 | 系统生成 |
| `offset` | int | 否 | 分页偏移 | 分页 | 否 | 系统生成 |

源站文档写明“单次请求最大返回 3000 行，可根据股票代码、日期等参数循环提取全部数据”。V1 时间请求口径：

1. 单日维护：生成 1 个自然日 unit，向源站传 `trade_date=YYYYMMDD`。
2. 区间维护：生成 1 个区间 unit，向源站传 `start_date=YYYYMMDD`、`end_date=YYYYMMDD`，不逐日展开。
3. 单个 unit 内按 `limit/offset` 分页拉完后再提交。

### 2.2 输出字段端到端对账

| 源站输出字段 | 源文档列出 | `source_fields` | raw ORM | serving light | 是否必填 | 清洗规则 |
| --- | --- | --- | --- | --- | --- | --- |
| `ts_code` | 是 | 是 | 是 | 是 | 是 | 去首尾空白，保持源站代码 |
| `name` | 是 | 是 | 是 | 是 | 否 | 文本清理，空值落 `NULL` |
| `trade_date` | 是 | 是 | 是 | 是 | 是 | `YYYYMMDD` 转 `date` |
| `q` | 是 | 是 | 是 | 是 | 是 | 问题文本，清理 NUL 和首尾空白 |
| `a` | 是 | 是 | 是 | 是 | 是 | 回复文本，清理 NUL 和首尾空白 |
| `pub_time` | 是 | 是 | 是 | 是 | 否 | 源站实测格式如 `2026-05-13 15:39:32`；非空时按北京时间解析为 `timestamptz`，空值落 `NULL` |
| `industry` | 是 | 是 | 是 | 是 | 否 | 文本清理，空值落 `NULL` |

`source_fields` 必须显式请求全部输出字段，不能只依赖默认返回。

### 2.3 源接口真实行为验证表（首次真实同步验收时补齐）

| 请求形态 | 实际请求参数 | 源端返回行数 | 是否分页 | 关键样本字段 | 结论 |
| --- | --- | --- | --- | --- | --- |
| 不传业务参数 | `{limit: 5, offset: 0}` | 5 | 是 | `trade_date/pub_time/industry` | 返回字段完整，只能说明默认页可取，不作为主链全集策略 |
| 只传对象过滤 | `ts_code=300707.SZ, limit=5, offset=0` | 5 | 是 | `ts_code` | 可按对象过滤 |
| 只传时间点 | `trade_date=20260512, limit=5, offset=0` | 5 | 是 | `trade_date=20260512` | 单日日期参数有效；`20260513` 当时返回 0，属于源站该业务日期暂无数据，不是参数错误 |
| 传时间区间 | `start_date=20260512, end_date=20260512, limit=5, offset=0` | 5 | 是 | `trade_date=20260512` | 区间参数有效；单日窗口与 point 口径一致 |
| 分页第二页 | `start_date=20260512, end_date=20260513, limit=2, offset=2` | 2 | 是 | `q/a` | offset 生效 |
| 文档歧义参数 | `pub_date` | 不作为 V1 门禁 | 不作为 V1 门禁 | 无 | V1 不开放，未来需要时单独评审 |

## 3. 三层语义拆分

| 语义层 | 本数据集答案 | 核验依据 |
| --- | --- | --- |
| 时间输入语义 | 运营提交自然日单日或自然日区间；`ts_code` 只是可选过滤。 | 源文档提供 `trade_date/start_date/end_date`，真实行为待 M0 补证。 |
| 执行 / unit 语义 | point 生成 1 个自然日 unit，使用 `trade_date` 传递单一时间点参数；range 生成 1 个区间 unit，使用 `start_date/end_date` 传递时间范围，分页拉完后按 unit 提交。 | 本轮评审确认：range 不逐日展开，直接按区间请求源站。 |
| freshness / audit 语义 | 用 `pub_time` 作为最近观测时间；不做日期完整性审计。 | 互动易问答是事件型文本，不保证每个自然日都有问答。 |

`bucket_rule=not_applicable` 在本数据集里的含义是：退出连续日期完整性判断，但仍支持自然日 point/range 输入。

## 4. DatasetDefinition 设计

### 4.1 identity

```python
"identity": {
    "dataset_key": "irm_qa_sz",
    "display_name": "深证互动易问答",
    "description": "维护 Tushare 深交所互动易问答文本数据。",
    "aliases": (),
}
```

### 4.2 domain

```python
"domain": {
    "domain_key": "news",
    "domain_display_name": "新闻资讯",
    "cadence": "daily",
}
```

### 4.3 source

```python
"source": {
    "source_key_default": "tushare",
    "source_keys": ("tushare",),
    "adapter_key": "tushare",
    "api_name": "irm_qa_sz",
    "source_fields": ("ts_code", "name", "trade_date", "q", "a", "pub_time", "industry"),
    "source_doc_id": "tushare.irm_qa_sz",
    "request_builder_key": "_trade_date_or_start_end_params",
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
    "observed_field": "pub_time",
    "audit_applicable": False,
    "not_applicable_reason": "深证互动易问答是事件型文本数据，不保证每个自然日都有问答。",
}
```

### 4.5 input_model

| 字段 | 类型 | 必填 | 默认值 | 多选 | 中文名 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `trade_date` | date | 否 | 无 | 否 | 处理日期 | 单日维护入口 |
| `start_date` | date | 否 | 无 | 否 | 开始日期 | 区间维护入口 |
| `end_date` | date | 否 | 无 | 否 | 结束日期 | 区间维护入口 |
| `ts_code` | string | 否 | 无 | 否 | 股票代码 | 可选过滤，不默认扇出股票池 |

## 5. 存储设计

### 5.1 raw 表

- 表名：`raw_tushare.irm_qa_sz`
- ORM 建议：`src/foundation/models/raw/raw_irm_qa_sz.py`
- DAO 建议：`raw_irm_qa_sz`
- 写入路径：`raw_only_upsert`
- 幂等键：`row_key_hash`

建议字段：

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `id` | bigserial | PK | 内部行 ID |
| `ts_code` | varchar(32) | not null | 股票代码，保持源站返回 |
| `name` | varchar(128) | nullable | 公司名称 |
| `trade_date` | date | not null | 源站日期 |
| `q` | text | not null | 投资者问题 |
| `a` | text | not null | 公司回复 |
| `pub_time` | timestamptz | nullable | 回复时间；源站实测格式如 `2026-05-13 15:39:32`，非空时按 Asia/Shanghai 解析 |
| `industry` | varchar(128) | nullable | 涉及行业 |
| `row_key_hash` | varchar(64) | unique not null | 稳定行身份 |
| `api_name` | varchar(32) | not null default `'irm_qa_sz'` | 源接口 |
| `fetched_at` | timestamptz | not null default now() | 抓取时间 |
| `raw_payload` | text | nullable | 原始行 JSON |

建议索引：

```sql
create unique index uq_raw_tushare_irm_qa_sz_row_key_hash
on raw_tushare.irm_qa_sz(row_key_hash);

create index idx_raw_tushare_irm_qa_sz_code_time
on raw_tushare.irm_qa_sz(ts_code, pub_time desc);

create index idx_raw_tushare_irm_qa_sz_trade_date
on raw_tushare.irm_qa_sz(trade_date desc);
```

`row_key_hash` 建议使用：

```text
irm_qa_sz + ts_code + trade_date + pub_time + q + a
```

原因：源站没有问答 ID，问题和回复文本是事实主体；`industry` 是分类展示字段，不参与行身份，避免分类口径变化导致同一问答生成新 hash。

### 5.2 serving light view

- view：`core_serving_light.irm_qa_sz`
- 来源：`raw_tushare.irm_qa_sz`
- 字段：`row_key_hash, ts_code, name, trade_date, q, a, pub_time, industry, source, fetched_at`
- 不新增 core 物理表。

## 6. 执行链路设计

| 环节 | 设计 |
| --- | --- |
| unit builder | 使用现有 `generic` unit planner；point 生成 1 个自然日 unit；range 在 `bucket_rule=not_applicable` 下生成 1 个区间 unit，不逐日展开 |
| request builder | 复用共享参数映射 `_trade_date_or_start_end_params`；point 输出 `trade_date=YYYYMMDD`；range 输出 `start_date/end_date`；可选附加 `ts_code` |
| pagination | `offset_limit`，`page_limit=3000` |
| normalizer | 新增 `_irm_qa_sz_row_transform`，清理文本、解析 `trade_date/pub_time`、生成 `row_key_hash` |
| writer | raw DAO upsert，冲突列 `row_key_hash` |
| transaction | `commit_policy=unit`，单个 unit 的所有分页拉完、归一化、写入后提交 |

事务评估：point 的单个事务写入量等于深证互动易某个自然日的全部问答行数；range 的单个事务写入量等于整个区间返回行数。首次真实同步验收必须用高峰日期样本和典型区间样本复核写入量。

## 7. Ops 与页面

| 消费方 | 方案 |
| --- | --- |
| 数据源卡片 | 展示在“新闻资讯”分组，名称“深证互动易问答” |
| 手动任务 | 支持单日、区间；可选股票代码过滤 |
| 自动任务 | 支持配置，并在 V1 挂入“每日收盘后维护”工作流 |
| 工作流 | 每日收盘后维护按当天日期触发，request builder 映射为 `trade_date=当天` |
| 任务详情 | 处理范围显示处理日期或日期区间 |
| 日期完整性审计 | 不接入 |
| freshness | 最近同步展示来自 `pub_time` 与 TaskRun 健康，不按连续日判滞后 |

## 8. 测试与验收

已补充自动化覆盖：

1. Definition 事实投影测试。
2. resolver 测试：证明 `unit_builder_key=generic` 时，point 生成 1 个自然日 unit；range 生成 1 个区间 unit，不逐日展开。
3. request builder 测试：point 确认生成 `trade_date/ts_code/limit/offset`；range 确认生成 `start_date/end_date/ts_code/limit/offset`；不传 `pub_date`。
4. source client 测试：确认 connector payload 的 `fields` 包含全部 7 个源字段。
5. normalizer 测试：`pub_time` 非空时按完整时间解析、空值落 `NULL`，文本 NUL 清理，缺 `q/a` 结构化拒绝。
6. DAO upsert 测试。
7. Ops catalog 测试。

真实同步验收必须记录 fetched、normalized、written、rejected、reject reason code、target count。任何 reject 必须给样本。

## 9. 已拍板项

| 编号 | 问题 | 当前结论 |
| --- | --- | --- |
| D1 | V1 是否挂入现有 workflow | 已确认：挂入“每日收盘后维护”工作流。 |
| D2 | 是否开放 `pub_date` 过滤 | 已确认：V1 不开放。 |
| D3 | 是否按股票池 fan-out | 已确认：不按股票池 fan-out。 |
| D4 | `industry` 是否参与 row hash | 已确认：不参与。 |
| D5 | `pub_time` 返回格式 | 已确认：实测返回完整时间字符串，例如 `2026-05-13 15:39:32`；非空时按完整时间解析，空值不拒绝。 |
