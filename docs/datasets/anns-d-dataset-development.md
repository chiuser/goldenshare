# 上市公司公告（`anns_d`）维护说明

状态：现行实现说明及 P0 目标合同；2026-10-02 更新。§2—§7 的必填、旧哈希和完整区间 unit 描述仍是现行行为，尚未改代码。新增同步原则见 §8，技术方案和 LLD 已落文，P1—P4 未执行。既有源端样本保留为历史证据；本轮实测与 Prod 只读结果见新方案。

## 1. 范围与事实源

- 单源 Tushare `anns_d`，doc_id=176；[本地源文档](/Users/congming/github/goldenshare/docs/sources/tushare/大模型语料/0176_上市公司全量公告.md)。
- [DatasetDefinition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/news.py) 定义输入、字段、存储和观测；底层域为 `news / 新闻资讯`。
- 通用约束引用[数据集开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)与[日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)，不在本文复制完整 Definition 或重新定义公共流程。

## 2. 输入与执行单元

- 运营输入公告自然日 point/range，可选 `ts_code` 过滤，不按股票池展开。
- point：一个 unit，源请求 `start_date=end_date=所选日期`。
- range：一个完整区间 unit，源请求 `start_date/end_date`，**不逐日展开**。
- 已确认只采用这一套源时间参数；不发送 `ann_date` 或平台 `trade_date`。无日期请求只曾用于探测，不是全集维护入口。

`unit_builder_key=generic`，`universe_policy=no_pool`。[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)只构造业务请求参数；[SourceClient](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)负责把 Definition 的字段列表传给 connector，并在 unit 内注入 `limit=2000`、递增 `offset`，遇到空页或短页结束。分页参数不开放给运营。

当前为 `buffer_all + commit_policy=unit`：先读完单个 unit 的所有分页，再归一化、写入并提交。单页 2000 行不是整个 unit 的行数或内存上限，尤其完整区间不能按单页规模估计；本轮不把该实现宣称为已通过所有长任务恢复门禁。

## 3. 字段与身份

| 源站输出字段 | 源文档列出 | `source_fields` | raw ORM | serving light | 是否必填 | 清洗规则 |
| --- | --- | --- | --- | --- | --- | --- |
| `ann_date` | 是 | 是 | 是 | 是 | 是 | `YYYYMMDD` 转 `date`，伪空值拒绝 |
| `ts_code` | 是 | 是 | 是 | 是 | 是 | 去首尾空白，保持源站代码 |
| `name` | 是 | 是 | 是 | 是 | 否 | 文本清理，空值落 `NULL` |
| `title` | 是 | 是 | 是 | 是 | 是 | 文本清理，空值拒绝 |
| `url` | 是 | 是 | 是 | 是 | 是 | 文本清理，空值拒绝，参与行身份 |
| `rec_time` | 是 | 是 | 是 | 是 | 是 | 源站格式如 `2026-05-14 08:30:01`；按北京时间解析为 `timestamptz`，空值拒绝 |

1. 六个源字段全量显式请求。`ann_date/ts_code/title/url/rec_time` 必填，`name` 可空；不能因源样例只展示四列而漏掉 URL 或收录时间。
2. `ann_date` 转日期，`rec_time` 按 Asia/Shanghai 解析为带时区时间；文本去 NUL、首尾空白，代码大写。源文档称 `rec_time` 为发布时间，当前错误提示称公告收录时间；两者均指同一源字段，不另造字段。
3. 哈希按 `anns_d, ann_date.isoformat(), ts_code, title, url, rec_time.isoformat()` 顺序、`\x1f` 分隔后 SHA-256；URL 和 rec_time 都参与身份。
4. 缺必填值和解析失败必须保留实际 reason code 与样本，不能把 reject 直接当成正常过滤。

转换实现见 [row_transforms](/Users/congming/github/goldenshare/src/foundation/ingestion/row_transforms.py)；日期解析及 required fields 还会经过 [通用 normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)。

## 4. 存储与消费者

- Raw 物理表：`raw_tushare.anns_d`；[Raw ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_anns_d.py)保留 `id` 自增主键、唯一 `row_key_hash` 及审计字段，upsert 冲突列为 `row_key_hash`。
- 读取出口及 Definition `target_table`：`core_serving_light.anns_d` 普通视图；[读取模型](/Users/congming/github/goldenshare/src/foundation/models/core_serving_light/anns_d.py)描述其列。
- 写路径仍是 `raw_only_upsert`，`raw_with_serving_light_view`；target 指向读取出口不代表 writer 向 view 写入，也不生成第二份物理文本表。

## 5. Ops、freshness 与日期审计

- 维护动作 `anns_d.maintain`；输入由 Definition 投影，TaskRun 展示执行结果与问题，不用源接口参数替代运营时间意图。
- `observed_field=ann_date`；`bucket_rule=not_applicable / event_run_trace`，支持自然日输入但不要求每日有记录，日期完整性审计不启用。
- 已纳入 `daily_market_close_maintenance`，工作流传当天日期，builder 按第 2 节生成源参数。工作流证据见 [action_catalog](/Users/congming/github/goldenshare/src/ops/action_catalog.py)。

## 6. 验证入口与证据边界

- [Definition 回归](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[执行计划回归](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)、[归一化回归](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py)、[源字段传递回归](/Users/congming/github/goldenshare/tests/test_dataset_source_client.py)覆盖本数据集的相应合同；它们不是生产同步验收。
- [DAO 回归](/Users/congming/github/goldenshare/tests/test_row_key_hash_dao.py)核对 upsert 身份与自增 ID 边界。
- 真实运行若另行授权，需要记录 fetched、normalized、written、rejected、拒绝样本和目标身份数；没有证据不能把源端样本或代码存在升级为“生产已验收”。

## 7. 历史源端验证记录

以下为原接入记录，使用 2026 年 5 月业务日期样本；原文未单列精确执行时间，本轮不补猜。记录不再标“待填写”，也不证明今天的源端状态或全量生产验收。

| 请求形态 | 实际请求参数 | 源端返回行数 | 是否分页 | 关键样本字段 | 结论 |
| --- | --- | --- | --- | --- | --- |
| 不传业务参数 | `{limit: 5, offset: 0}` | 5 | 是 | `ann_date/url/rec_time` | 返回字段完整，只能说明默认页可取，不作为主链全集策略 |
| 只传对象过滤 | `ts_code=603051.SH, limit=5, offset=0` | 5 | 是 | `ts_code` | 可按对象过滤 |
| 只传时间点 | `start_date=20260512, end_date=20260512, limit=5, offset=0` | 5 | 是 | `ann_date=20260512` | 单日日期窗口有效 |
| 传时间区间 | `start_date=20260512, end_date=20260512, limit=5, offset=0` | 5 | 是 | `ann_date=20260512` | 区间参数有效；单日窗口与 point 口径一致 |
| 分页第二页 | `start_date=20260513, end_date=20260514, limit=2, offset=2` | 2 | 是 | `url` | offset 生效 |
| 源站 `ann_date` 参数 | 未纳入主链验证 | 不适用 | 不适用 | 不适用 | V1 主链不采用 |


原评审还记录：管理员已测试按日期与不传日期的结果一致，确认继续使用 `start_date/end_date`，不重开 no-param snapshot 的拍板问题；该决策不外推为任意日期范围均完整。


## 8. 2026-10-02 同步完善 P0（目标合同，尚未实现）

主方案：[公告同步完善技术方案](/Users/congming/github/goldenshare/docs/datasets/anns-d-sync-technical-plan-v1.md)；实施约束：[LLD](/Users/congming/github/goldenshare/docs/datasets/anns-d-sync-low-level-design-v1.md)。本节按开发模板校准原开发文档，不把计划覆盖为当前代码。

### 0.3.0 本轮源核验与生产证据

源必选业务参数无；当前运营仍明确指定日期point/range，源请求使用start/end；默认五字段不含rec_time，必须显式六字段。真实默认/五字段/六字段、无参数、只代码、单点、区间、第二页与缺值样本见技术方案 §2。限量文档2,000/MCP描述6,000不一致，本轮不提高。Prod只读范围为任务14075一行及表列元数据，未扫描全量、未导出、未写入；结果见技术方案 §2，不能拿该任务success替代有效公告完整性验收。

### 0.3.1—0.3.3 身份、完整定义及字段落点

| 事实层 | 目标与现状差异 | 设计/验证位置 |
| --- | --- | --- |
| 身份/来源/输入 | anns_d/news/Tushare六字段、maintain、point/range可选ts_code不变 | 当前Definition；技术方案 §1—§3 |
| 时间输入 | natural_day、trade_date或start/end，不按股票池展开 | resolver/builder；LLD §4/A07/A14 |
| unit语义 | range由完整区间改自然日units | 具名规划合同；LLD §4 |
| freshness/audit | ann_date观测、not_applicable/event_run_trace，空日合法不变 | freshness/cards/audit消费者A07 |
| 存储/读取 | 同Raw/view名称；Raw保存源版本，view只读有效版本 | LLD §3；A06/A12 |
| 质量/事务/预算 | 缺值不拒；偏序覆盖；逐500行提交；单日完成凭证 | LLD §2—§6；A01—A11 |
| action/schedule | 既有maintain、收盘工作流日期意图不变；显式恢复意图属于Ops | LLD §6/A13 |

| 字段 | 源字段请求 | 当前落库 | P0目标转换、存储与读取 |
| --- | --- | --- | --- |
| ann_date | 显式 | date非空 | 必填、候选组字段；不虚构空日期 |
| ts_code | 显式 | varchar32非空 | 必填，保留源类型，不用当前股票池过滤 |
| name | 显式 | varchar128可空 | 可空、纳入内容指纹与覆盖比较；非空冲突保留 |
| title | 显式 | text非空 | 必填，必要清理，不模糊匹配 |
| url | 显式 | text非空 | 改可空；有值不改URL，下载可用性另判断 |
| rec_time | 显式 | timestamptz非空 | 改可空；有效时间规范化；非法原值保留载荷并告警 |
| id/row_key_hash | 非源字段 | 自增/旧唯一哈希 | id保持源证据身份；统一六字段新指纹 |
| group_key/is_current/covered_by_id | 非源字段 | 不存在 | 分组/有效投影/覆盖追溯；不伪装成源字段 |
| fetched_at/raw_payload | 非源字段/源证据 | 已有审计列 | 抓取时间不补rec_time；保留真实载荷，不存合成源行 |

所有新字段、真实表结构和测试仍待P1；没有写入验收证据。没有源字段明确弃用，也不添加源文档未证实字段。

### 0.3.4 硬要求追溯账本

A01—A14唯一追溯表见LLD §8，逐条关联代码点、正反例和验证阶段。本轮已完成业务决策表与现行代码核验，自动化测试、DDL及真实写入状态均为未执行。P1/P2交付必须回填对应证据，不能只附总测试数。

### 0.3.5 Prod长任务可恢复性与可观测性合同

| 必填项 | 本数据集设计 |
| --- | --- |
| 目标/长任务判定 | Prod公告维护及历史补录；14075实测约12小时，明确适用 |
| 执行unit | 一个公告自然日，计划冻结范围/过滤/合同摘要；空日可完成 |
| 批次/内存 | 源页2,000、写批500、响应64MiB、组128版本；decoded峰值实测，不缓存全范围 |
| 业务持久化边界 | 每批源证据及有效投影同事务提交；末批与unit完成凭证同事务 |
| 幂等键 | 六字段规范内容指纹；候选组日期代码标题；同指纹核验真实字段 |
| 续跑依据 | 同一冻结execution的业务完成凭证；未完成日从第一页重放，不用旧offset |
| 进度字段 | 当前日/页/阶段、返回/提交/新增/重复/覆盖/冲突、完成日总日百分比、最近更新时间 |
| 取消检查点 | 每页/写批/重试/等待前后；单调用25秒，30秒可见更新门禁 |
| 事务/并发 | 短业务事务、观察独立；公告执行try advisory lock串行，普通读不阻塞 |
| 观察失败 | 不回滚已提交业务；任务/节点一致终态和既有恢复路径核验 |
| 恢复与请求预算 | anns_d专用unit凭证及request预算账，理由/表设计见LLD §3/§5；非第二TaskRun |
| 入口影响 | 维护入口不换名，增加明确恢复意图须同步Ops/API/UI；不新增lane/Worker |
| 最小真实验收 | 缺时间/URL样本、第二页、运行取消续跑读回、状态写失败、RSS和30秒进度；见A01—A14 |

### 8.4 P0阶段完成记录与后续门禁

| 阶段 | 本阶段目标 | 状态及未执行项 |
| --- | --- | --- |
| P0 | 事实、合并规则、LLD、配置设计、长任务合同、迁移和测试计划 | 文档已落地；文档检查结果见本轮交付，不代表代码验收 |
| P1 | NULL、单一身份、覆盖存储及消费者 | 未开始；需真实head、迁移演练、消费者审计 |
| P2 | 日units、批提交、取消续跑、进度 | 未开始；需源调用合同/隐藏重试预算、页面验收 |
| P3/P4 | 最小真实验收/生产迁移补录 | 未执行；需具体范围、恢复方案和授权 |

### 9—10 发布、恢复与交付

发布和回滚约束见LLD §7，不复制执行命令伪装已运行。P4以前不得生产迁移、停止任务、清空/删除业务表；不收紧已写NULL列，不让旧/新身份双轨运行。P0当前只支持现行旧链路；目标保存/合并/续跑能力均未实现。PDF已完成M1保留，后续适配及验收以本前置阶段为依赖。
