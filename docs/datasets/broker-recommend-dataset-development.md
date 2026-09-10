# 券商月度金股推荐（`broker_recommend`）维护说明

状态：当前代码说明；2026-09-10 文档治理核对。2026-08-01 已确认单月和月份区间由 DatasetActionResolver 生成计划；本轮没有重新核验源端、生产数据或部署状态。

## 1. 依据与范围

- Tushare `broker_recommend`，doc_id=267；[本地源说明](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/特色数据/0267_券商每月荐股.md)。
- [market_equity Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py)：底层域为 `equity_market / 股票行情`，不是基础主数据；Ops 展示分组为 `broker_recommendation / 券商推荐`。
- 通用规则见 [开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)和 [日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)。

## 2. 月份输入与执行

| 维度 | 当前合同 |
| --- | --- |
| 动作 | `broker_recommend.maintain`；支持手动、定时、重试 |
| 时间输入 | `month_or_range`：point 使用月份；range 使用开始/结束月份 |
| 日期模型 | `month_key / every_natural_month`；观测字段 `month`，日期完整性审计适用 |
| 规划 | Resolver 归一化月份，planner 每自然月一个 unit，不查询交易日历 |
| 源请求 | builder 逐 unit 生成 `month=YYYYMM`，不是 Ops/TaskRun 自行拼月份序列 |
| 分页 | SourceClient 注入 `limit=1000/offset`，空页或短页结束；无对象池和业务过滤 |
| 提交 | `buffer_all + commit_policy=unit`；读完该月全部分页后写入、提交，不是每页一个事务 |

例如运营选 `2026-06..2026-08`，生成 `month=202606/202607/202608` 三个 unit。月份存为六位字符串，不转业务 Date；输出中的 `trade_date` 是行字段，不是“按日维护”入口。

## 3. 字段合同与来源证据缺口

当前代码显式请求以下 14 字段，按 Raw 和 Serving 模型保存：

| 字段名 | 当前类型说明 | 业务含义 | 是否全量落库 |
| --- | --- | --- | --- |
| `month` | `str` | 月度 | 是 |
| `currency` | `str` | 币种 | 是 |
| `name` | `str` | 股票名称 | 是 |
| `ts_code` | `str` | 股票代码 | 是 |
| `trade_date` | `str` | 收盘日期 | 是 |
| `close` | `float` | 收盘价 | 是 |
| `pct_change` | `float` | 月涨跌幅 | 是 |
| `target_price` | `float` | 目标价 | 是 |
| `industry` | `str` | 所属行业 | 是 |
| `broker` | `str` | 券商 | 是 |
| `broker_mkt` | `str` | 市场标识 | 是 |
| `author` | `str` | 分析师 | 是 |
| `recom_type` | `str` | 评级类型 | 是 |
| `reason` | `str` | 推荐理由 | 是 |

**来源覆盖与实现合同须分开看**：本地 doc_id=267 只列 `month/broker/ts_code/name` 四个输出字段；另外十个字段存在于当前 Definition 和 ORM，但不能冒称全部来自该本地文档或已获本轮实测。本轮保留实现字段，不删列、不改 fields；如需修改其语义或请求合同，须先补源端验证。

Raw/Serving ORM 还存在 `offset` 列；它不在当前 `source_fields`，不能将请求分页偏移当成源业务事实，或保证每行均回填了该值。

必填 `month/ts_code/broker`；`name` 等可空。`trade_date` 按日期解析，`close/pct_change/target_price` 按数值解析；其他合法性以实际 normalizer 拒绝记录为准，不笼统承诺所有字符串都有额外清洗。

## 4. 存储与查询

- Raw：`raw_tushare.broker_recommend`，[Raw ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_broker_recommend.py)。
- Serving：`core_serving.broker_recommend`，[Serving ORM](/Users/congming/github/goldenshare/src/foundation/models/core/broker_recommend.py)；同时是 Definition 的 `target_table`。
- **两张都是物理表，当前仍为 `raw_core_upsert`**；writer 对同一 normalized batch 按模型字段分别写入。不套用研究报告或新闻的 Raw-only/view 合同。
- 两层主键均为 `(month, ts_code, broker)`；Raw 保留 `api_name/fetched_at/raw_payload`，Serving 有 `created_at/updated_at`。
- 索引与真实类型以 ORM 和实际 catalog 为准，不执行旧文档“新增 raw/core 表”的过时指令。

## 5. 运营与观测

- 页面使用月份选择，不让运营填写 `limit/offset`。分组通过 [Ops 目录](/Users/congming/github/goldenshare/src/ops/catalog/dataset_catalog_views.py)投影，不为 UI 分组改底层域。
- freshness 使用 `period_bucket`，按月份事实观测与审计；不是仅显示 `last_sync_date`，也不要求每个交易日都有荐股。
- 源文档称一般月初 1–3 日更新。“月初同步一次”是原运营建议，不证明已有对应 cron 或源端已经更新；本轮不创建、启停自动任务。
- 原接入未要求新增专属业务 API 或研报联动主题视图，本轮同样不新增这些能力。

## 6. 验证与后续边界

[Resolver 月份回归](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)覆盖单月、月份范围和不访问交易日历；[Definition 回归](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[字段清单回归](/Users/congming/github/goldenshare/tests/test_fields_constants.py)及 [Ops 目录回归](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)作为合同核验入口。

现行实现存在不等于原空白验收清单全部通过；本轮未补生产写入、行数、取消/续跑或性能验收。扩大月份范围前按开发模板核对单月返回量、事务和恢复边界。源端 14 字段完整性需新实测时再独立执行，不在文档治理中猜测。
