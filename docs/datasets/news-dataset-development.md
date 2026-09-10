# 新闻快讯（`news`）维护说明

状态：当前代码说明；2026-09-10 文档治理核对。既有源端样本单列为历史证据，本轮未重新实测源端、写入数据库或确认生产部署。

## 1. 范围与事实源

- 单源 Tushare `news`，doc_id=143；[本地源文档](/Users/congming/github/goldenshare/docs/sources/tushare/大模型语料/0143_新闻快讯.md)。
- [DatasetDefinition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/news.py) 定义输入、字段、存储和观测；底层域为 `news / 新闻资讯`。
- 通用约束引用[数据集开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)与[日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)，不在本文复制完整 Definition 或重新定义公共流程。

## 2. 输入与执行单元

- 运营输入自然日 point/range，按每个自然日×每个选定来源生成 unit；周末、节假日也展开，不查交易日历。
- 每个 unit 的源请求是 `src + start_date=当天 00:00:00 + end_date=当天 23:59:59`。**没有继续拆成多个日内窗口。**
- `src` 可多选，不选时展开 Definition 的全部九个真实来源；不是给源站传空来源或哨兵值。
- 默认来源：`sina/wallstreetcn/10jqka/eastmoney/yuncaijing/fenghuang/jinrongjie/cls/yicai`。
- 例如两天、选择两个来源，生成 4 个 unit；分页发生在各 unit 内，不影响这个数量。

`unit_builder_key=build_news_units`，`universe_policy=no_pool`。[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)只构造业务请求参数；[SourceClient](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)负责把 Definition 的字段列表传给 connector，并在 unit 内注入 `limit=1500`、递增 `offset`，遇到空页或短页结束。分页参数不开放给运营。

当前为 `buffer_all + commit_policy=unit`：先读完单个 unit 的所有分页，再归一化、写入并提交。单页 1500 行不是整个 unit 的行数或内存上限，尤其完整区间不能按单页规模估计；本轮不把该实现宣称为已通过所有长任务恢复门禁。

## 3. 字段与身份

| 字段名 | 类型 | 含义 | 是否落 raw | 是否进入 serving/core | 清洗规则 |
| --- | --- | --- | --- | --- | --- |
| `datetime` | string | 新闻时间 | 是 | 是（`core_serving_light.news`） | 解析为 `news_time` |
| `content` | string | 内容 | 是 | 是 | 去掉首尾空白，保留正文原文，可空 |
| `title` | string | 标题 | 是 | 是 | 去掉首尾空白，可空 |
| `channels` | string | 分类 | 是 | 是 | 可空，保留源值 |
| `score` | string | 分值 | 是 | 是 | 可空，保留源值 |

1. 显式请求 `datetime/content/title/channels/score`。SourceClient 根据请求补入 `src`，随后 normalizer 解析和验证；不是由 normalizer 凭空推断来源。
2. `datetime` 映射为 `news_time`；无时区时间按 Asia/Shanghai 解析为带时区时间。
3. 文本去 NUL、首尾空白；标题与正文允许单项为空，不能同时为空。`channels/score` 可空。
4. 哈希输入按顺序为 `news, src, news_time.isoformat(), title, content, channels, score`。空文本使用空串，字段以 `\x1f` 分隔后 SHA-256；不是竖线拼接。
5. 来源/时间缺失、时间非法、标题正文皆空分别使用实际 `normalize.required_field_missing:*`、`normalize.invalid_date:news_time`、`normalize.empty_not_allowed:title_content` 拒绝原因。

转换实现见 [row_transforms](/Users/congming/github/goldenshare/src/foundation/ingestion/row_transforms.py)；日期解析及 required fields 还会经过 [通用 normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)。

## 4. 存储与消费者

- Raw 物理表：`raw_tushare.news`；[Raw ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_news.py)保留 `id` 自增主键、唯一 `row_key_hash` 及审计字段，upsert 冲突列为 `row_key_hash`。
- 读取出口及 Definition `target_table`：`core_serving_light.news` 普通视图；[读取模型](/Users/congming/github/goldenshare/src/foundation/models/core_serving_light/news.py)描述其列。
- 写路径仍是 `raw_only_upsert`，`raw_with_serving_light_view`；target 指向读取出口不代表 writer 向 view 写入，也不生成第二份物理文本表。

## 5. Ops、freshness 与日期审计

- 维护动作 `news.maintain`；输入由 Definition 投影，TaskRun 展示执行结果与问题，不用源接口参数替代运营时间意图。
- `observed_field=news_time`；`bucket_rule=not_applicable / event_run_trace`，支持自然日输入但不要求每日有记录，日期完整性审计不启用。
- Definition 支持定时能力；不能据此认定某个自动任务已经启用。工作流证据见 [action_catalog](/Users/congming/github/goldenshare/src/ops/action_catalog.py)。
- 真实 `progress_context` 使用 `start_date/end_date/trade_date/date_field/enum_field/enum_value` 等通用键。例如来源是 `enum_field=src, enum_value=sina`；旧文档的顶层 `src/window_start/window_end` JSON 不是当前结构。见 [progress context builder](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)。

## 6. 验证入口与证据边界

- [Definition 回归](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[执行计划回归](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)、[归一化回归](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py)、[源字段传递回归](/Users/congming/github/goldenshare/tests/test_dataset_source_client.py)覆盖本数据集的相应合同；它们不是生产同步验收。
- [DAO 回归](/Users/congming/github/goldenshare/tests/test_news_dao.py)核对 upsert 身份与自增 ID 边界。
- 真实运行若另行授权，需要记录 fetched、normalized、written、rejected、拒绝样本和目标身份数；没有证据不能把源端样本或代码存在升级为“生产已验收”。
