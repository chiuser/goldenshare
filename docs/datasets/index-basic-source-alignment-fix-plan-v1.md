# 指数基础信息 index_basic 维护说明

更新时间：2026-09-10。本文按当前代码整理原源站对齐修复方案，保留历史迁移与未核实事项，不再作为清表、重建或重跑指令。代码已具备下述能力；本轮没有重新验收生产数据或请求 Tushare。

## 1. 范围与依据

`index_basic` 维护指数基础信息，不是指数行情请求池的统一替代品。定义见 [index_series.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/index_series.py)，接口资料为 doc_id=94：[指数基本信息](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0094_指数基本信息.md)。

日期与执行的通用规则分别见[日期模型指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)和[执行计划说明](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)，本文只保留本数据集的差异。

## 2. 当前输入与请求行为

| 项目 | 当前实现 |
| --- | --- |
| 日期语义 | 无日期输入的主数据快照；`date_axis/window_mode/input_shape=none`，`bucket_rule=not_applicable`，不做连续业务日期完整性审计 |
| 维护动作 | `maintain`，时间模式只支持 `none`；无 `trade_date` 输入项 |
| 业务过滤 | `ts_code/symbol/name/market/publisher/category` 均可选 |
| `symbol` | 支持多值，由 builder 去除首尾空白后逗号拼接 |
| `ts_code` | 去除首尾空白并转大写；名称、发布方、类别去除首尾空白 |
| `market` | 可选单值枚举 `MSCI/CSI/SSE/SZSE/CICC/SW/OTH`，默认不传；不按市场默认扇出 |
| 默认计划 | 无业务过滤时生成一个 unit，业务 `request_params={}` |
| 分页 | `offset_limit`，当前配置 `page_limit=6000`；分页参数由 source client 追加，不是运营过滤项 |

请求实现见 [`_index_basic_params`](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)。请求显式包含 Definition 的 13 个源字段，包括 `exp_date`；完整字段清单以 Definition 和源资料为准，不在本文重复维护。

### market 来源口径冲突

原方案记录的既定口径是“不传 market 获取全量”，当前 Definition 的参数描述也沿用这一说法；本地源资料却写“默认 SSE”。本轮确认的是**代码默认不传 market**，不是源端当前必然返回所有市场。

本次不改变默认值、市场扇出或请求参数，也不改写来源资料。后续如需确认全集覆盖，须重新用 Tushare 实测对比不传 market 与显式市场过滤的分页结果，记录市场分布、唯一代码和差集。仅证明请求参数为空，或返回多个市场，都不足以单独证明全集完整。

## 3. 存储与日期转换

当前 `write_path=raw_core_upsert`，Raw 与 Serving 两层写入；两者主键均为 `ts_code`。

| 项目 | Raw | Serving |
| --- | --- | --- |
| 表 | `raw_tushare.index_basic` | `core_serving.index_basic` |
| `base_date/list_date/exp_date` | `varchar(16)` | `date` |
| `base_point` | `numeric(20,4)` | `numeric(20,4)` |
| 来源/审计字段 | `api_name/fetched_at/raw_payload` | `created_at/updated_at` |
| 市场、发布方、类别普通索引 | 当前 Raw 模型未定义 | 当前 Serving 模型分别定义 |

模型见 [RawIndexBasic](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_index_basic.py) 与 [IndexBasic](/Users/congming/github/goldenshare/src/foundation/models/core/index_basic.py)。

normalizer 的 `date_fields=()`，保留上述源日期字符串；[writer](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py) 在写入前按目标模型列类型分别转换 Raw、Serving 的行。这是通用目标类型适配，不是专用兼容分支。

注意：两层转换均发生在 upsert 前。非法日期可能在 Serving 类型转换阶段抛错；不能把“Raw 列是字符串”理解成“异常行一定已经独立写入 Raw”，也不能将 Raw 当作原始响应无损归档。

## 4. 有效指数与下游依赖

[`IndexBasicDAO.get_active_indexes(as_of)`](/Users/congming/github/goldenshare/src/foundation/dao/index_basic_dao.py) 使用 `exp_date IS NULL OR exp_date >= effective_date`，默认 effective_date 为当天，并按代码排序。

当前 ingestion 调用位于 [`_resolve_index_weight_universe_values`](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)：先取显式代码，再按 Definition 配置尝试对象池来源；走到基础信息回退来源时调用该 DAO。因此需要覆盖的是 **index_weight 的回退路径**，不是通过运行 index_daily 来间接证明。

`index_daily` 的 Raw 请求池和 Serving 入库池另有机制，见[指数行情统一说明](/Users/congming/github/goldenshare/docs/datasets/index-series-active-sync-mechanism.md)。不要把基础信息中的“有效指数”与运营激活池混为一谈。

## 5. 历史修复与验证边界

原方案中的过滤参数缺失、日期模型混用、Raw 日期类型与终止指数过滤等问题，已在当前实现中体现修正，不再列为待开发项。历史结构调整见 [20260501_000090](/Users/congming/github/goldenshare/alembic/versions/20260501_000090_rebuild_index_basic_storage.py)。

该迁移包含重建两层表的历史逻辑；原“尚未上线”“可以停机清理”和待确认重建清单不再作为当前事实或执行授权。旧全文可从 Git 提交 `b8811098` 追溯。

现有离线验证入口：

- [Definition 测试](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)：过滤、日期与维护合同。
- [resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)：默认单 unit、显式参数与 index_weight 回退。
- [normalizer 测试](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py)及 [writer 日期转换测试](/Users/congming/github/goldenshare/tests/test_dataset_writer_stock_basic.py)：Raw 字符串与 Serving 日期分层。
- [DAO 测试](/Users/congming/github/goldenshare/tests/test_extended_daos.py)：有效日期过滤 SQL。

这些测试不证明源端全集覆盖或生产历史数据完整。本次仅校正文档；如另行批准真实验收，应分别记录来源分页/市场覆盖、指定范围两层落库对账及 index_weight 规划结果，不必为证明依赖而启动行情同步。
