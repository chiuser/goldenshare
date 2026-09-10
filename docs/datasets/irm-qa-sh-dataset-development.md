# 上证E互动问答（`irm_qa_sh`）维护说明

状态：当前代码说明；2026-09-10 文档治理核对。既有源端样本单列为历史证据，本轮未重新实测源端、写入数据库或确认生产部署。

## 1. 范围与事实源

- 单源 Tushare `irm_qa_sh`，doc_id=366；[本地源文档](/Users/congming/github/goldenshare/docs/sources/tushare/大模型语料/0366_上证E互动.md)。
- [DatasetDefinition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/news.py) 定义输入、字段、存储和观测；底层域为 `news / 新闻资讯`。
- 通用约束引用[数据集开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)与[日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)，不在本文复制完整 Definition 或重新定义公共流程。

## 2. 输入与执行单元

- 运营输入自然日 point/range，可选 `ts_code` 过滤，不按股票池展开。
- point 一个 unit，源请求 `trade_date=YYYYMMDD`；range 一个完整区间 unit，发送 `start_date/end_date`，不逐日展开。
- 本地源文档将 `pub_date` 重复列成起止时间，又在示例使用输入表没有的 `ann_date`。当前 builder 不发送这两个参数；已确认不开放 `pub_date`，未来扩展须另行核验和批准。

`unit_builder_key=generic`，`universe_policy=no_pool`。[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)只构造业务请求参数；[SourceClient](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)负责把 Definition 的字段列表传给 connector，并在 unit 内注入 `limit=3000`、递增 `offset`，遇到空页或短页结束。分页参数不开放给运营。

当前为 `buffer_all + commit_policy=unit`：先读完单个 unit 的所有分页，再归一化、写入并提交。单页 3000 行不是整个 unit 的行数或内存上限，尤其完整区间不能按单页规模估计；本轮不把该实现宣称为已通过所有长任务恢复门禁。

## 3. 字段与身份

| 源站输出字段 | 源文档列出 | `source_fields` | raw ORM | serving light | 是否必填 | 清洗规则 |
| --- | --- | --- | --- | --- | --- | --- |
| `ts_code` | 是 | 是 | 是 | 是 | 是 | 去首尾空白，保持源站代码 |
| `name` | 是 | 是 | 是 | 是 | 否 | 文本清理，空值落 `NULL` |
| `trade_date` | 是 | 是 | 是 | 是 | 是 | `YYYYMMDD` 转 `date` |
| `q` | 是 | 是 | 是 | 是 | 是 | 问题文本，清理 NUL 和首尾空白 |
| `a` | 是 | 是 | 是 | 是 | 是 | 回复文本，清理 NUL 和首尾空白 |
| `pub_time` | 是 | 是 | 是 | 是 | 否 | 源站实测格式如 `2026-05-13 15:39:32`；非空时按北京时间解析为 `timestamptz`，空值落 `NULL` |

1. 显式请求六个源字段。`ts_code/trade_date/q/a` 必填；`name/pub_time`可空。
2. 日期转 `date`，代码大写，文本去 NUL 和首尾空白。`pub_time` 有值时按 Asia/Shanghai 解析，空值保留 NULL，不因此拒绝整行；非法非空时间仍会拒绝。
3. 哈希输入顺序为 `irm_qa_sh, ts_code, trade_date.isoformat(), pub_time.isoformat()或空串, q, a`，以 `\x1f` 分隔后 SHA-256。`name`不参与哈希。
4. 问题与答复共同构成事实身份；不能把回复时间可空误解为问题或回复也可以缺失。

转换实现见 [row_transforms](/Users/congming/github/goldenshare/src/foundation/ingestion/row_transforms.py)；日期解析及 required fields 还会经过 [通用 normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)。

## 4. 存储与消费者

- Raw 物理表：`raw_tushare.irm_qa_sh`；[Raw ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_irm_qa_sh.py)保留 `id` 自增主键、唯一 `row_key_hash` 及审计字段，upsert 冲突列为 `row_key_hash`。
- 读取出口及 Definition `target_table`：`core_serving_light.irm_qa_sh` 普通视图；[读取模型](/Users/congming/github/goldenshare/src/foundation/models/core_serving_light/irm_qa_sh.py)描述其列。
- 写路径仍是 `raw_only_upsert`，`raw_with_serving_light_view`；target 指向读取出口不代表 writer 向 view 写入，也不生成第二份物理文本表。

## 5. Ops、freshness 与日期审计

- 维护动作 `irm_qa_sh.maintain`；输入由 Definition 投影，TaskRun 展示执行结果与问题，不用源接口参数替代运营时间意图。
- `observed_field=pub_time`；`bucket_rule=not_applicable / event_run_trace`，支持自然日输入但不要求每日有记录，日期完整性审计不启用。
- 已纳入 `daily_market_close_maintenance`，工作流传当天日期，builder 按第 2 节生成源参数。工作流证据见 [action_catalog](/Users/congming/github/goldenshare/src/ops/action_catalog.py)。

## 6. 验证入口与证据边界

- [Definition 回归](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[执行计划回归](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)、[归一化回归](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py)、[源字段传递回归](/Users/congming/github/goldenshare/tests/test_dataset_source_client.py)覆盖本数据集的相应合同；它们不是生产同步验收。
- [DAO 回归](/Users/congming/github/goldenshare/tests/test_row_key_hash_dao.py)核对 upsert 身份与自增 ID 边界。
- 真实运行若另行授权，需要记录 fetched、normalized、written、rejected、拒绝样本和目标身份数；没有证据不能把源端样本或代码存在升级为“生产已验收”。

## 7. 历史源端验证记录

以下为原接入记录，使用 2026 年 5 月业务日期样本；原文未单列精确执行时间，本轮不补猜。记录不再标“待填写”，也不证明今天的源端状态或全量生产验收。

| 请求形态 | 实际请求参数 | 源端返回行数 | 是否分页 | 关键样本字段 | 结论 |
| --- | --- | --- | --- | --- | --- |
| 不传业务参数 | `{limit: 5, offset: 0}` | 5 | 是 | `trade_date/pub_time` | 返回字段完整，只能说明默认页可取，不作为主链全集策略 |
| 只传对象过滤 | `ts_code=600082.SH, limit=5, offset=0` | 5 | 是 | `ts_code` | 可按对象过滤 |
| 只传时间点 | `trade_date=20260512, limit=5, offset=0` | 5 | 是 | `trade_date=20260512` | 单日日期参数有效 |
| 传时间区间 | `start_date=20260512, end_date=20260512, limit=5, offset=0` | 5 | 是 | `trade_date=20260512` | 区间参数有效；单日窗口与 point 口径一致 |
| 分页第二页 | `start_date=20260513, end_date=20260514, limit=2, offset=2` | 2 | 是 | `q/a` | offset 生效 |
| 文档歧义参数 | `pub_date` | 不作为 V1 门禁 | 不作为 V1 门禁 | 无 | V1 不开放，未来需要时单独评审 |
