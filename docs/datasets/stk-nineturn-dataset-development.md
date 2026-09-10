# Tushare 神奇九转指标（`stk_nineturn`）数据集开发说明

更新时间：2026-09-10。本文描述当前 Prod 数据集代码与迁移定义，不是新增接入计划，也不代表本轮完成了生产同步或源接口验收。

## 1. 范围与依据

本数据集通过 `DatasetDefinition -> DatasetActionResolver -> IngestionExecutor` 接入 Ops TaskRun，拉取 Tushare 日线九转指标，写入 Raw，再由 Serving 视图提供查询。

- 静态合同：[market_equity.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py) 中的 `stk_nineturn`。
- 通用职责与日期语义：[DatasetDefinition](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md)、[执行计划](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)、[日期消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)。本文只保留本数据集差异。
- 独立 Lake 链路继续查阅 [Dagster 接入方案](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stk-nineturn-dataset-onboarding-plan.md) 与 [LLD](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stk-nineturn-dataset-onboarding-low-level-design.md)。本文件的 Prod Serving 视图不是 Lake Silver；本次不修改 Lake 接入、历史 bootstrap 或日常链路。

## 2. 上游资料与请求字段

来源为 [doc 364 本地接口资料](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/特色数据/0364_神奇九转指标.md)，抓取于 2026-04-19。资料记载每天 21 点更新、数据从 `2023-01-01` 开始、单次最大返回 `10000` 行；这是上游资料口径，不是本地自动截断规则、到数承诺或本轮实测结果。

源接口列有可选 `ts_code/trade_date/start_date/end_date/freq` 及分页参数；运营输入只开放第 3 节的子集，不因源端可选就全部暴露。

当前 Definition 显式请求、Raw 模型及 Serving 视图承接以下 13 个源字段：

```text
ts_code, trade_date, freq, open, high, low, close, vol, amount,
up_count, down_count, nine_up_turn, nine_down_turn
```

`trade_date` 归一化为日期；价格、量额及九转计数按 Definition 的 `decimal_fields` 转换；必需字段为 `ts_code/trade_date`。字段含义见源资料，数据库类型见第 4 节模型；审计字段不加入源请求字段。

## 3. 维护输入与执行

动作是 `stk_nineturn.maintain`，供运营维护；不以旧 FULL/INCREMENTAL 名称区分入口。

| 输入 | 当前规划行为 |
| --- | --- |
| `mode=point` + `trade_date` | 以输入日期生成单日 unit |
| `mode=range` + `start_date/end_date` | 校验两端齐全且开始不晚于结束，按交易日历逐日生成 unit |
| 无时间 | 不支持；不能作为全量维护入口 |
| 可选单值 `ts_code` | 限定证券；未填写时不按证券池展开 |

[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py) 的 `_stk_nineturn_params` 为每个 unit 生成 `trade_date=YYYYMMDD`、固定 `freq=daily`，可选代码去除首尾空白并转大写。`freq` 不是运营输入；区间不会原样透传为源端 `start_date/end_date`。

- 日期模型为 `trade_open_day + every_open_day + point_or_range`。区间依赖本地交易日历；具体实现见 [validator](/Users/congming/github/goldenshare/src/foundation/ingestion/validator.py) 与 [unit planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)。
- 当前没有 `2023-01-01` 下限校验或自动截断。早于该日期的 point，以及交易日历返回的早期日期，仍可生成源请求；不能把源端数据起点当作已有代码限制。
- 交易日历返回空列表时，规划结果为零个 unit；这只说明规划行为，不承诺所有空结果都有专用提示或整条任务链必定成功。
- 每个 unit 使用 `offset_limit` 分页，`page_limit=10000`；提交策略为 `unit`。分页配置与单元提交不单独证明源端全量完整性或进程退出后可靠续跑，真实验收遵守上述执行计划专题。

## 4. Raw 写入与 Serving 视图

| 对象 | 当前代码与迁移定义 |
| --- | --- |
| `raw_tushare.stk_nineturn` | 物理表，也是 `storage.target_table`；主键 `(ts_code, trade_date)`，日期索引 `idx_raw_tushare_stk_nineturn_trade_date` |
| Raw 审计列 | `api_name/fetched_at/raw_payload`；不属于源端 13 字段 |
| 写入 | `raw_only_upsert`；`raw_dao_name/core_dao_name` 均指向 `raw_stk_nineturn`，不再独立写 Serving |
| `core_serving.equity_nineturn` | 普通视图，直接选择 Raw 的 13 个源字段；`created_at/updated_at` 均映射自 `fetched_at`，不暴露 `api_name/raw_payload` |

依据：[Raw 模型](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_stk_nineturn.py)、[writer](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)、[迁移 20260803_000124](/Users/congming/github/goldenshare/alembic/versions/20260803_000124_make_cyq_perf_nineturn_raw_views.py)。该迁移同时处理 `cyq_perf`，不是九转单表操作脚本，也不能据本文直接重跑。

[EquityNineTurn ORM](/Users/congming/github/goldenshare/src/foundation/models/core/equity_nineturn.py) 仍有主键和索引元数据声明；它们不证明迁移后的视图拥有独立物理主键或索引。上述迁移未安装专用 DML 拒写触发器，本文不将“同步只写 Raw”扩大为“数据库层已经强制只读”的保证。

## 5. Ops 与观测

- Definition 的底层域是 `equity_market`（股票行情）；Ops 展示分组是 `technical_indicators`（技术指标），来自 [展示目录](/Users/congming/github/goldenshare/src/ops/catalog/dataset_catalog_views.py)，两者不能混写。
- 动作声明允许手动、调度与重试；当前 [工作流定义](/Users/congming/github/goldenshare/src/ops/action_catalog.py) 未将其加入 `daily_market_close_maintenance`。允许调度不代表生产已有启用的排程。
- `observed_field=trade_date`、`audit_applicable=True`；[freshness 策略](/Users/congming/github/goldenshare/src/foundation/datasets/freshness_policies.py) 为 `continuous_open_day`。业务日期观测不以 `fetched_at` 替代，也不能仅凭某日有记录证明所有证券齐全。

## 6. 验证入口与证据边界

| 现行测试 | 能证明的范围 |
| --- | --- |
| [Definition registry](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py) | Raw-backed Serving 的表映射、写入配置与目标投影 |
| [Raw-only writer](/Users/congming/github/goldenshare/tests/test_dataset_writer_raw_serving_views.py) 的 `stk_nineturn` 样例 | 替身 DAO 下只写 Raw，返回正确目标与写入量 |
| [视图迁移](/Users/congming/github/goldenshare/tests/test_cyq_perf_nineturn_raw_view_migration.py) | 静态检查迁移前置校验、无 CASCADE、字段映射及禁止自动降级；不代表已在生产执行 |
| [源字段测试](/Users/congming/github/goldenshare/tests/test_fields_constants.py) | 从 Definition 读取的 13 个 `source_fields`，不是独立的 `STK_NINETURN_FIELDS` 常量 |
| [模型测试](/Users/congming/github/goldenshare/tests/test_extended_models.py) 的 `test_stk_nineturn_serving_model_matches_expected_keys` | ORM 主键/索引元数据，不证明真实数据库结构 |

2026-09-10 文档核验：使用替身交易日历调用真实 Resolver，范围 `2022-12-29` 至 `2023-01-03`、日历返回 `2022-12-30/2023-01-03` 时，生成两个日期的请求；point `2022-12-30` 也未截断，空日历生成零个 unit。相关迁移、九转 writer、源字段与模型的 4 项离线测试通过；未请求 Tushare、未连接生产库，不作为源端分页、数据起点或生产完整性验收。
