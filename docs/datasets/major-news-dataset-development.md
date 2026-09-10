# 新闻通讯（`major_news`）维护说明

状态：当前代码说明；2026-09-10 文档治理核对。既有源端样本单列为历史证据，本轮未重新实测源端、写入数据库或确认生产部署。

## 1. 范围与事实源

- 单源 Tushare `major_news`，doc_id=195；[本地源文档](/Users/congming/github/goldenshare/docs/sources/tushare/大模型语料/0195_新闻通讯.md)。
- [DatasetDefinition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/news.py) 定义输入、字段、存储和观测；底层域为 `news / 新闻资讯`。
- 通用约束引用[数据集开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)与[日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)，不在本文复制完整 Definition 或重新定义公共流程。

## 2. 输入与执行单元

- 运营输入自然日 point/range，按每个自然日×每个选定来源生成 unit；周末、节假日也展开，不查交易日历。
- 每个 unit 的源请求是 `src + start_date=当天 00:00:00 + end_date=当天 23:59:59`。**没有继续拆成多个日内窗口。**
- `src` 可多选，不选时展开 Definition 的全部九个真实来源；不是给源站传空来源或哨兵值。
- 默认来源：`新华网/凤凰财经/同花顺/新浪财经/华尔街见闻/中证网/财新网/第一财经/财联社`。
- 例如两天、选择两个来源，生成 4 个 unit；分页发生在各 unit 内，不影响这个数量。

`unit_builder_key=build_major_news_units`，`universe_policy=no_pool`。[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)只构造业务请求参数；[SourceClient](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)负责把 Definition 的字段列表传给 connector，并在 unit 内注入 `limit=400`、递增 `offset`，遇到空页或短页结束。分页参数不开放给运营。

当前为 `buffer_all + commit_policy=unit`：先读完单个 unit 的所有分页，再归一化、写入并提交。单页 400 行不是整个 unit 的行数或内存上限，尤其完整区间不能按单页规模估计；本轮不把该实现宣称为已通过所有长任务恢复门禁。

## 3. 字段与身份

| 字段名 | 类型 | 含义 | 是否落 raw | 清洗规则 |
| --- | --- | --- | --- | --- |
| `title` | string | 标题 | 是 | 去掉首尾空白，可空 |
| `content` | string | 内容 | 是 | 去掉首尾空白，保留正文原文，可空 |
| `pub_time` | string | 发布时间 | 是 | 解析为 `pub_time` |
| `src` | string | 来源 | 是 | 去掉首尾空白 |
| `url` | string | 原文链接 | 是 | 去掉首尾空白，空值按 `NULL` 保存 |

1. `title/content/pub_time/src/url` 五个字段显式请求；`content/url` 在本地源文档中不是默认返回字段。
2. `src/pub_time` 必须有值；时间按 Asia/Shanghai 语义解析。标题与正文至少一项非空，`url` 可空；但响应连 `content` 字段都不存在时仍拒绝。
3. 哈希输入按顺序为 `major_news, src, pub_time.isoformat(), title, content, url`。空文本用空串，按 `\x1f` 分隔后 SHA-256。不同 URL 会影响身份，不恢复旧 hash。
4. 正规拒绝原因包含 `normalize.required_field_missing:src/pub_time/content`（按具体字段分别生成）、`normalize.invalid_date:pub_time`、`normalize.empty_not_allowed:title_content`，不另造旧私有码。

转换实现见 [row_transforms](/Users/congming/github/goldenshare/src/foundation/ingestion/row_transforms.py)；日期解析及 required fields 还会经过 [通用 normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)。

## 4. 存储与消费者

- Raw 物理表：`raw_tushare.major_news`；[Raw ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_major_news.py)保留 `id` 自增主键、唯一 `row_key_hash` 及审计字段，upsert 冲突列为 `row_key_hash`。
- 读取出口及 Definition `target_table`：`core_serving_light.major_news` 普通视图；[读取模型](/Users/congming/github/goldenshare/src/foundation/models/core_serving_light/major_news.py)描述其列。
- 写路径仍是 `raw_only_upsert`，`raw_with_serving_light_view`；target 指向读取出口不代表 writer 向 view 写入，也不生成第二份物理文本表。
- 当前市场新闻列表、阅读查询使用该出口，见 [major_news_query](/Users/congming/github/goldenshare/src/biz/queries/wealth/market/news/major_news_query.py) 和 [major_news_reader_query](/Users/congming/github/goldenshare/src/biz/queries/wealth/market/news/major_news_reader_query.py)；维护接受的行不保证一定符合页面筛选条件。

## 5. Ops、freshness 与日期审计

- 维护动作 `major_news.maintain`；输入由 Definition 投影，TaskRun 展示执行结果与问题，不用源接口参数替代运营时间意图。
- `observed_field=pub_time`；`bucket_rule=not_applicable / event_run_trace`，支持自然日输入但不要求每日有记录，日期完整性审计不启用。
- Definition 支持定时能力；不能据此认定某个自动任务已经启用。工作流证据见 [action_catalog](/Users/congming/github/goldenshare/src/ops/action_catalog.py)。

## 6. 验证入口与证据边界

- [Definition 回归](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[执行计划回归](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)、[归一化回归](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py)、[源字段传递回归](/Users/congming/github/goldenshare/tests/test_dataset_source_client.py)覆盖本数据集的相应合同；它们不是生产同步验收。
- [DAO 回归](/Users/congming/github/goldenshare/tests/test_major_news_dao.py)核对 upsert 身份与自增 ID 边界。
- 真实运行若另行授权，需要记录 fetched、normalized、written、rejected、拒绝样本和目标身份数；没有证据不能把源端样本或代码存在升级为“生产已验收”。

## 7. 历史 hash 与表结构迁移

2026 年 5 月旧实现曾将不同 URL 的通讯压成同一 hash，且把 title 设为必填。后续修正将 URL 纳入身份、允许标题或正文单项为空；当前 Definition、transform、Raw/Light ORM 与测试已采用第 3 节合同，不再作为待编码问题。

[revision 20260501_000089](/Users/congming/github/goldenshare/alembic/versions/20260501_000089_rebuild_major_news_storage.py)保留当时重建存储的历史实现。原文“远程清表重建是 P0 门禁”只属于那次旧身份迁移，**不是当前日常维护或本轮文档整理的执行要求**。本轮未核验任一环境的 migration head，也不授权重跑迁移、手动删表、清空历史数据或重写已发布迁移。

若另一个环境确实仍在旧合同，须先只读核对 head、表/view、hash 与消费者，再单独设计并获准实施；不能仅因读到旧章节就执行清表。
