# 北交所新旧代码对照（`bse_mapping`）维护说明

状态：当前代码说明；2026-09-10 文档治理核对。本文不证明生产部署、最新数据或自动任务状态；原接入阶段结论不因此重新打开，也不升级为本轮生产验收。

## 1. 范围与依据

- Tushare `bse_mapping`，doc_id=375；[本地源说明](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/基础数据/0375_北交所新旧代码对照表.md)。
- 当前事实源为 [reference_master Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/reference_master.py)；底层域 `reference_data / 基础主数据`，Ops 展示分组 `reference_data / A股基础数据`。
- 通用规则引用 [开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)与 [日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)，不重复粘贴完整 Definition、建表 SQL 或施工清单。

## 2. 输入与执行

- 动作为 `bse_mapping.maintain`，`time_input.mode=none`；无日期控件，不按代码池或月份展开。
- 可选 `o_code/n_code`，request builder 只传实际填写的过滤；都不填时业务参数为 `{}`。
- generic planner 生成一个无日期 unit，内部继续分页。源文档“总量 300 以内”是抓取时的来源描述，不是永久容量门禁，也不能据此取消分页或断言任何规模都安全。

`universe_policy=no_pool`；分页由 [SourceClient](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)注入 `limit=1000/offset`，空页或短页结束。[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)只生成业务参数。当前 `buffer_all + commit_policy=unit`，分页不切事务，也不代表页级持久化或中断后从任意页续跑。

## 3. 字段与身份

| 字段名 | 源类型 | 是否落 raw | 备注 |
| --- | --- | --- | --- |
| `name` | string | 是 | 股票名称 |
| `o_code` | string | 是 | 原代码 |
| `n_code` | string | 是 | 新代码 |
| `list_date` | string | 是 | 上市日期；源站为 `YYYYMMDD` 字符串，raw 层直接落 `date` |

- 必填 `o_code/n_code`，两个代码去首尾空白并大写。`list_date` 直接转 `date`，可空；`name` 可空。
- 主键为旧码、新码二元组，不能把旧代码或新代码单独当作已获保证的唯一键。Raw 主键已承担唯一约束，不重复执行旧文档的建唯一索引示例。

具体解析和哈希见 [normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)及 [row_transforms](/Users/congming/github/goldenshare/src/foundation/ingestion/row_transforms.py)。

## 4. 存储与观测

- 写入 `raw_tushare.bse_mapping`，`raw_only_upsert`；幂等冲突列为 `(o_code, n_code)`。冲突列同时为 Raw 主键。
- [Raw ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_bse_mapping.py)定义真实类型、可空性、物理索引及审计字段 `api_name/fetched_at/raw_payload`，不执行旧文档中“建议新增”的 DDL。
- `target_table=core_serving_light.bse_mapping`；[Light 模型](/Users/congming/github/goldenshare/src/foundation/models/core_serving_light/bse_mapping.py)对应 Raw 普通读取视图，不复制第二份物理数据，也不是 writer 的 DML 目标。
- 日期模型 `none / not_applicable`，无运营时间输入、无业务日期 observed field；`snapshot_run_trace` 关注最近成功维护，不做连续日期完整性判断。
- 已纳入 `reference_data_refresh`，见 [action_catalog](/Users/congming/github/goldenshare/src/ops/action_catalog.py)；手动、定时、重试是能力，不等于实时 schedule 状态已核验。

## 5. 回归与运行边界

- [Definition 回归](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[Resolver 回归](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)、[Ops 目录与工作流回归](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)覆盖注册、输入及当前展开路径；日期/哈希相关样本见 [normalizer 回归](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py)。
- 本轮未新增源端调用或生产验收；不能从“已有实现”推出全部历史完整。扩大范围前，按开发模板核对真实请求量、单 unit 内存、提交量、取消和续跑证据，不把单页 1000 行当成整个任务上限。
