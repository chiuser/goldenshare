# 股票历史基础列表（`bak_basic`）维护说明

状态：当前代码说明；2026-09-10 文档治理核对。本文不证明生产部署、最新数据或自动任务状态；原接入阶段结论不因此重新打开，也不升级为本轮生产验收。

## 1. 范围与依据

- Tushare `bak_basic`，doc_id=262；[本地源说明](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/基础数据/0262_股票历史列表（历史每天股票列表）.md)。
- 当前事实源为 [reference_master Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/reference_master.py)；底层域 `reference_data / 基础主数据`，Ops 展示分组 `reference_data / A股基础数据`。
- 通用规则引用 [开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)与 [日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)，不重复粘贴完整 Definition、建表 SQL 或施工清单。

## 2. 输入与执行

- 动作为 `bak_basic.maintain`，只支持显式 point/range，不提供无日期全历史入口。
- point 一个 unit，range 按交易日历开市日逐日生成 unit；每个源请求只传 `trade_date=YYYYMMDD` 和可选 `ts_code`，不发送源接口没有的 `start_date/end_date`。
- `ts_code` 是普通过滤，不展开股票池。当前 unit ID 由日期和序号生成，普通代码过滤保存在 request params/progress context，不自动拼入 unit ID。应连同完整计划理解身份，不能单独依赖字符串示例。
- 源文档称数据从 2016 年开始，这不是代码自动裁剪的证明。仅传代码是否能取得全历史仍未补充实测；该路径不在现行主链，不能继续写成当前编码阻塞。若未来增加无日期入口，再单独验证与评审。

`universe_policy=no_pool`；分页由 [SourceClient](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)注入 `limit=7000/offset`，空页或短页结束。[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)只生成业务参数。当前 `buffer_all + commit_policy=unit`，分页不切事务，也不代表页级持久化或中断后从任意页续跑。

## 3. 字段与身份

| 字段名 | 源类型 | 是否落 raw | 备注 |
| --- | --- | --- | --- |
| `trade_date` | string | 是 | 源站为 `YYYYMMDD` 字符串，raw 层直接落 `date` |
| `ts_code` | string | 是 | 主身份字段 |
| `name` | string | 是 |  |
| `industry` | string | 是 |  |
| `area` | string | 是 |  |
| `pe` | float | 是 |  |
| `float_share` | float | 是 |  |
| `total_share` | float | 是 |  |
| `total_assets` | float | 是 |  |
| `liquid_assets` | float | 是 |  |
| `fixed_assets` | float | 是 |  |
| `reserved` | float | 是 |  |
| `reserved_pershare` | float | 是 |  |
| `eps` | float | 是 |  |
| `bvps` | float | 是 |  |
| `pb` | float | 是 |  |
| `list_date` | string | 是 | 源站为 `YYYYMMDD` 字符串，raw 层直接落 `date` |
| `undp` | float | 是 |  |
| `per_undp` | float | 是 |  |
| `rev_yoy` | float | 是 |  |
| `profit_yoy` | float | 是 |  |
| `gpr` | float | 是 |  |
| `npr` | float | 是 |  |
| `holder_num` | int | 是 |  |

- `trade_date/list_date` 在 Raw 直接落 `date`，不保留重复字符串镜像；读视图不再额外 cast。
- 必填 `trade_date/ts_code`；非法必填日期拒绝，`list_date=00000000` 等日期伪空值归一化为 NULL。
- 数值走 Definition 的 decimal 解析清单，物理列类型见 Raw ORM；`name/industry/area` 清理首尾空白，代码规范为大写。

具体解析和哈希见 [normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)及 [row_transforms](/Users/congming/github/goldenshare/src/foundation/ingestion/row_transforms.py)。

## 4. 存储与观测

- 写入 `raw_tushare.bak_basic`，`raw_only_upsert`；幂等冲突列为 `(trade_date, ts_code)`。冲突列同时为 Raw 主键。
- [Raw ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_bak_basic.py)定义真实类型、可空性、物理索引及审计字段 `api_name/fetched_at/raw_payload`，不执行旧文档中“建议新增”的 DDL。
- `target_table=core_serving_light.bak_basic`；[Light 模型](/Users/congming/github/goldenshare/src/foundation/models/core_serving_light/bak_basic.py)对应 Raw 普通读取视图，不复制第二份物理数据，也不是 writer 的 DML 目标。
- `trade_open_day / every_open_day`，观测 `trade_date`；freshness 为 `continuous_open_day`，启用日期完整性审计。
- 已纳入 `daily_market_close_maintenance`，见 [action_catalog](/Users/congming/github/goldenshare/src/ops/action_catalog.py)；手动、定时、重试是能力，不等于实时 schedule 状态已核验。
- 原 `unit_id` 示例误把普通 `ts_code` filter 拼入 ID，已撤下；实际序列由 [build_plan_units/build_unit_id](/Users/congming/github/goldenshare/src/foundation/ingestion/plan_helpers.py)生成，进度另含 `date_field/trade_date` 和可选代码。

## 5. 回归与运行边界

- [Definition 回归](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[Resolver 回归](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)、[Ops 目录与工作流回归](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)覆盖注册、输入及当前展开路径；日期/哈希相关样本见 [normalizer 回归](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py)。
- 本轮未新增源端调用或生产验收；不能从“已有实现”推出全部历史完整。扩大范围前，按开发模板核对真实请求量、单 unit 内存、提交量、取消和续跑证据，不把单页 7000 行当成整个任务上限。
