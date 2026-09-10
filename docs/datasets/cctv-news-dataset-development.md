# 新闻联播文字稿（`cctv_news`）维护说明

状态：当前代码说明；2026-09-10 文档治理核对。既有源端样本单列为历史证据，本轮未重新实测源端、写入数据库或确认生产部署。

## 1. 范围与事实源

- 单源 Tushare `cctv_news`，doc_id=154；[本地源文档](/Users/congming/github/goldenshare/docs/sources/tushare/大模型语料/0154_新闻联播.md)。
- [DatasetDefinition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/news.py) 定义输入、字段、存储和观测；底层域为 `news / 新闻资讯`。
- 通用约束引用[数据集开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)与[日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)，不在本文复制完整 Definition 或重新定义公共流程。

## 2. 输入与执行单元

- 运营输入自然日 point/range；point 一个 unit，range 按闭区间自然日逐日生成 unit，无其他过滤条件。
- 源请求只发送 `date=YYYYMMDD`，平台 point 字段 `trade_date` 在这里不表示开市日。
- 当前使用专用 `build_cctv_news_units`，不是旧文档中的 `generic`。通用自然日 range 分支不会自动逐日展开，不能按旧示例替换。
- `page_limit=400` 是本仓配置；本地源文档未声明这个数是源端最大页容量。

`unit_builder_key=build_cctv_news_units`，`universe_policy=no_pool`。[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)只构造业务请求参数；[SourceClient](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)负责把 Definition 的字段列表传给 connector，并在 unit 内注入 `limit=400`、递增 `offset`，遇到空页或短页结束。分页参数不开放给运营。

当前为 `buffer_all + commit_policy=unit`：先读完单个 unit 的所有分页，再归一化、写入并提交。单页 400 行不是整个 unit 的行数或内存上限，尤其完整区间不能按单页规模估计；本轮不把该实现宣称为已通过所有长任务恢复门禁。

## 3. 字段与身份

| 字段名 | 类型 | 含义 | 是否落 raw | 清洗规则 |
| --- | --- | --- | --- | --- |
| `date` | string | 日期 | 是 | 保持源站字段名 `date`，便于与 Tushare 原始结果审计对齐 |
| `title` | string | 标题 | 是 | 去掉首尾空白 |
| `content` | string | 内容 | 是 | 去掉首尾空白，保留正文原文 |

1. `date` 保留源字段名并转为日期；`title/content` 去首尾空白，日期、标题、正文均为必填。
2. 哈希按 `date.isoformat(), title, content` 顺序、`\x1f` 分隔后 SHA-256。不含额外 API 前缀。
3. 不新增 `segment_index`：源文档只说明分段，没有稳定顺序字段；请求返回次序不能成为持久化事实。
4. 日期非法、必填项缺失按通用 normalizer/codebook 输出结构化拒绝；旧文档的 `invalid_date/missing_title` 等裸值不是当前完整 reason key。

转换实现见 [row_transforms](/Users/congming/github/goldenshare/src/foundation/ingestion/row_transforms.py)；日期解析及 required fields 还会经过 [通用 normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)。

## 4. 存储与消费者

- Raw 物理表：`raw_tushare.cctv_news`；[Raw ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_cctv_news.py)保留 `id` 自增主键、唯一 `row_key_hash` 及审计字段，upsert 冲突列为 `row_key_hash`。
- 读取出口及 Definition `target_table`：`core_serving_light.cctv_news` 普通视图；[读取模型](/Users/congming/github/goldenshare/src/foundation/models/core_serving_light/cctv_news.py)描述其列。
- 写路径仍是 `raw_only_upsert`，`raw_with_serving_light_view`；target 指向读取出口不代表 writer 向 view 写入，也不生成第二份物理文本表。

## 5. Ops、freshness 与日期审计

- 维护动作 `cctv_news.maintain`；输入由 Definition 投影，TaskRun 展示执行结果与问题，不用源接口参数替代运营时间意图。
- `observed_field=date`；`every_natural_day / continuous_natural_day`，按自然日对 `date` 做完整性审计。
- 已具备定时动作能力；此前“每日维护最近一天”是运营配置建议，不表示已创建或启用 schedule。工作流证据见 [action_catalog](/Users/congming/github/goldenshare/src/ops/action_catalog.py)。

## 6. 验证入口与证据边界

- [Definition 回归](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[执行计划回归](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)、[归一化回归](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py)覆盖本数据集的相应合同；它们不是生产同步验收。
- [DAO 回归](/Users/congming/github/goldenshare/tests/test_cctv_news_dao.py)核对 upsert 身份与自增 ID 边界。
- 真实运行若另行授权，需要记录 fetched、normalized、written、rejected、拒绝样本和目标身份数；没有证据不能把源端样本或代码存在升级为“生产已验收”。
