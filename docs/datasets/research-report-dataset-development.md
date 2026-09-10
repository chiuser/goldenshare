# 券商研究报告（`research_report`）维护说明

状态：当前代码说明；2026-09-10 文档治理核对。既有源端样本单列为历史证据，本轮未重新实测源端、写入数据库或确认生产部署。

## 1. 范围与事实源

- 单源 Tushare `research_report`，doc_id=415；[本地源文档](/Users/congming/github/goldenshare/docs/sources/tushare/大模型语料/0415_券商研究报告.md)。
- [DatasetDefinition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py) 定义输入、字段、存储和观测；底层域为 `equity_market / 股票行情`，Ops 分组为 `broker_recommendation / 券商推荐`。
- 通用约束引用[数据集开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)与[日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)，不在本文复制完整 Definition 或重新定义公共流程。

## 2. 输入与执行单元

- 运营输入研报发布自然日 point/range；point 发送 `trade_date`，range 发送完整 `start_date/end_date`，不逐日展开。
- `report_type/ts_code/inst_csname/ind_name` 均为可选过滤；不使用股票池。
- 不选 `report_type` 时不向源站发送该参数，point/range 各一个 unit；选一个类型也是一个 unit；同时选“个股研报、行业研报”则分别生成两个 unit。
- 类型展开与日期窗口是两个维度，不能笼统写成“任何 point/range 都只生成一个 unit”。

`unit_builder_key=generic`，`universe_policy=no_pool`。[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)只构造业务请求参数；[SourceClient](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)负责把 Definition 的字段列表传给 connector，并在 unit 内注入 `limit=1000`、递增 `offset`，遇到空页或短页结束。分页参数不开放给运营。

当前为 `buffer_all + commit_policy=unit`：先读完单个 unit 的所有分页，再归一化、写入并提交。单页 1000 行不是整个 unit 的行数或内存上限，尤其完整区间不能按单页规模估计；本轮不把该实现宣称为已通过所有长任务恢复门禁。

## 3. 字段与身份

| 源站输出字段 | 源文档列出 | 2026-05-14 样本 | `source_fields` | raw ORM | serving light | 是否必填 | 清洗规则 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `trade_date` | 是 | 是 | 是 | 是 | 是 | 否 | `YYYYMMDD` 转 `date`，空值落 `NULL` |
| `abstr` | 是 | 是 | 是 | 是 | 是 | 否 | 文本清理，空值落 `NULL` |
| `title` | 是 | 是 | 是 | 是 | 是 | 否 | 文本清理，空值落 `NULL` |
| `report_type` | 是 | 是 | 是 | 是 | 是 | 否 | 文本清理，空值落 `NULL` |
| `author` | 是 | 是 | 是 | 是 | 是 | 否 | 文本清理，空值落 `NULL` |
| `name` | 是 | 是 | 是 | 是 | 是 | 否 | 个股研报股票名称，行业研报可为空 |
| `ts_code` | 是 | 是 | 是 | 是 | 是 | 否 | 股票代码，行业研报可为空；非空时去空白并大写 |
| `inst_csname` | 是 | 是 | 是 | 是 | 是 | 否 | 券商简称，文本清理，空值落 `NULL` |
| `ind_name` | 是 | 是 | 是 | 是 | 是 | 否 | 行业名称，空值落 `NULL` |
| `url` | 是 | 是 | 是 | 是 | 是 | 是 | 下载链接，文本清理，空值拒绝 |
| `report_code` | 是，默认不显示 | 是 | 是 | 是 | 是 | 否 | 研报唯一编码；非空时作为首选身份事实，空值时走兜底身份规则 |

1. 显式请求全部 11 字段，包括非默认的 `report_code`；当前没有 `file_name` 字段。2026-05-14 历史实测曾额外请求 `file_name`，返回仍为 `title`，这不是本轮新实测。
2. 源字段中只有 `url` 被要求非空；`trade_date/title/report_type/inst_csname/ts_code/name/ind_name/report_code` 等允许 NULL，行业研报不能因为没有股票代码被丢弃。**可空不等于任意非空值合法**，例如非法日期仍会被通用 normalizer 拒绝。
3. 有 `report_code` 时，哈希输入为 `research_report, report_code, 编码值`。
4. 无编码时，输入为 `research_report, fallback, trade_date, title, report_type, inst_csname, author, ts_code, ind_name, url`，空值用空串，日期转 ISO；两条路径均按 `\x1f` 分隔后 SHA-256。
5. 物理自增 `id` 不参与业务身份；`report_code` 可空并不意味着丢弃整行，也不能改成只按股票和日期去重。

转换实现见 [row_transforms](/Users/congming/github/goldenshare/src/foundation/ingestion/row_transforms.py)；日期解析及 required fields 还会经过 [通用 normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)。

## 4. 存储与消费者

- Raw 物理表：`raw_tushare.research_report`；[Raw ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_research_report.py)保留 `id` 自增主键、唯一 `row_key_hash` 及审计字段，upsert 冲突列为 `row_key_hash`。
- 读取出口及 Definition `target_table`：`core_serving_light.research_report` 普通视图；[读取模型](/Users/congming/github/goldenshare/src/foundation/models/core_serving_light/research_report.py)描述其列。
- 写路径仍是 `raw_only_upsert`，`raw_with_serving_light_view`；target 指向读取出口不代表 writer 向 view 写入，也不生成第二份物理文本表。

## 5. Ops、freshness 与日期审计

- 维护动作 `research_report.maintain`；输入由 Definition 投影，TaskRun 展示执行结果与问题，不用源接口参数替代运营时间意图。
- `observed_field=trade_date`；`bucket_rule=not_applicable / event_run_trace`，支持自然日输入但不要求每日有记录，日期完整性审计不启用。
- 已确认不加入每日收盘后维护；Definition 保留定时能力不等于已创建独立自动任务，新增自动任务仍另行评审。工作流证据见 [action_catalog](/Users/congming/github/goldenshare/src/ops/action_catalog.py)。

## 6. 验证入口与证据边界

- [Definition 回归](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[执行计划回归](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)、[归一化回归](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py)、[源字段传递回归](/Users/congming/github/goldenshare/tests/test_dataset_source_client.py)覆盖本数据集的相应合同；它们不是生产同步验收。
- [DAO 回归](/Users/congming/github/goldenshare/tests/test_row_key_hash_dao.py)核对 upsert 身份与自增 ID 边界。
- 真实运行若另行授权，需要记录 fetched、normalized、written、rejected、拒绝样本和目标身份数；没有证据不能把源端样本或代码存在升级为“生产已验收”。

## 7. 历史源端验证（2026-05-14）

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

当时凭据有访问权限；不能据此推断其他环境或今天仍有权限。

同日最小源端读取与归一化验证：

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

该记录证明当时 27 行读取与归一化，不包含生产写入、迁移或目标表行数验收。本次未新增这些证据。
