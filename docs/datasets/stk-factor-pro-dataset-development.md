# 股票技术面因子 stk_factor_pro 维护说明

更新时间：2026-10-16。原 Raw 直出与复权变化历史重刷方案已合并到本文；§2–6 描述当前实现，§7 新增“历史区间回补不依赖本地复权因子”的待实施修改方案。本轮只更新文档，未改代码、部署或执行回补，不能按 §7 认定现有后台已解除检查。

## 1. 范围与来源

`stk_factor_pro` 保存 Tushare 提供的股票日级技术面因子，包含不复权、前复权、后复权口径。字段及能力以 [DatasetDefinition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py) 为准，本文不另存字段数量快照。

源资料：doc_id=328，[股票技术面因子（专业版）](</Users/congming/github/goldenshare/docs/sources/tushare/股票数据/特色数据/0328_股票技术面因子(专业版).md>)。本地资料记载单次最多 10,000 行、5,000 积分每分钟 30 次、8,000 积分以上每分钟 500 次；这些是资料中的权限条件，不是本轮核实的当前账户额度。

通用日期和执行规则见[日期模型指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)与[执行计划说明](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)，不在本专题重复定义。

## 2. 维护输入与请求

`maintain` 必须显式选择单日或区间，可选单个 `ts_code`。源端支持的日期参数不等于运营输入会原样传给源端。

| 场景 | 请求与范围 | 是否追加复权变化历史重刷 |
| --- | --- | --- |
| 默认单日维护 | 一个 `trade_date=T` 当天全市场 unit | 是，仅为符合 §3 条件的股票追加 |
| 显式股票单日维护 | `ts_code + trade_date=T` | 否 |
| 区间维护 | 按交易日历展开，每日一个 `trade_date` 请求；有股票过滤则带上 `ts_code` | 否，不扩大所选范围 |
| 自动追加的历史 unit | 单股 `ts_code + start_date + end_date` | 这是规划结果，不是另一套运营入口 |

[`_stk_factor_pro_params`](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)负责上述两类源请求。历史追加是一只股票一个区间 unit，不再拆成“股票 × 每日”。

分页采用 `offset_limit`，当前每页 10,000 行，分页参数由 source client 追加，不暴露为运营输入。返回短页（包括空页）即停止，不要求再请求到一个空页。

## 3. 复权门禁与历史重刷

### 目标日存在性门禁（当前实现）

[planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)的 `_ensure_stk_factor_pro_adj_factor_ready` 对每个计划目标交易日查询 `core.equity_adj_factor`，只要存在至少一行就通过；完全没有数据则以 `upstream_data_not_ready` 失败，提示“先更新复权因子”。

这不是全市场完整性检查，也不保证显式选择的那只股票已有复权因子。区间中任一目标交易日缺少数据，整个计划构建失败；没有“早于可用起点只提示、不报错”的通用保证。历史区间解除这项检查的修改方案见 §7，尚未实施。

### 先规划，再执行

默认单日维护的计划在执行前一次构建：

1. 通过目标日 T 的存在性门禁，生成当天 unit。
2. 使用交易日历寻找 T 之前最近交易日 P，而不是直接以自然日减一天作为 P。
3. 按股票代码内连接 T/P 两日复权因子，取 `adj_factor IS DISTINCT FROM` 的股票。
4. 查询每只变化股票在 `raw_tushare.stk_factor_pro` 中已有的最早 `trade_date`。
5. 有历史起点的股票追加 `ts_code + min(raw.trade_date) + T` 区间 unit；其余不追加。
6. 计划形成后才进入执行。当前串行处理 units，先执行当天 unit，再执行追加历史 units。

因此“先生成当天 unit”不是“先写入当天数据，再查询历史起点”。变化判断和历史起点都在本次写入之前读取。

边界：

- 显式股票单日维护、区间维护不做这项全市场变化审计。
- 找不到 P、两日没有可比较的变化股票，或变化股票无 Raw 历史起点时，不追加历史 unit。
- 只比较 T/P 两日都存在的股票；缺 P 日记录的新股不会进入变化集合。如果 P 日有缺行，当前逻辑会跳过这些股票，不能据此认定它们的因子未变化。
- 历史起点不取上市日期、固定配置日期或额外状态表；没有历史起点不代表系统会自动补建全部历史。
- 重刷规划由 `stk_factor_pro` 自己完成；`adj_factor` 写入完成后不会由该机制主动通知或触发重刷。

## 4. Raw 写入与 Serving 读取

| 项目 | 当前实现 |
| --- | --- |
| Raw 表 | `raw_tushare.stk_factor_pro` |
| 业务主键 | `(ts_code, trade_date)` |
| 数值列 | 根据 Definition 字段生成，使用 `Float(53)` / DOUBLE PRECISION |
| Raw 普通索引 | `trade_date`、`(ts_code, trade_date)` |
| Raw 审计字段 | `api_name/fetched_at/raw_payload` |
| Serving 入口 | `core_serving.equity_factor_pro`，普通视图直接读取 Raw |
| Serving 系统字段 | 固定 `source='tushare'`，`created_at/updated_at` 投影自 `fetched_at` |
| 写入路径 | `raw_only_upsert`，不写第二份 Serving 物理表 |

模型见 [RawStkFactorPro](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_stk_factor_pro.py)与 [EquityFactorPro](/Users/congming/github/goldenshare/src/foundation/models/core/equity_factor_pro.py)。`STK_FACTOR_PRO_FIELDS` 从 Definition 取得，不是另一个字段事实源。Serving ORM 的索引 metadata 不代表普通视图自带物理索引。

Definition 仍保留 `target_table=core_serving.equity_factor_pro`、`core_dao_name=equity_factor_pro` 和 `delivery_mode=single_source_serving`；实际 `layer_plan=raw->serving_view`、`write_path=raw_only_upsert`。不能照搬其他 Raw 直出数据集的配置值，也不能仅凭 DAO 名或 target_table 推断写入目标；[writer 测试](/Users/congming/github/goldenshare/tests/test_dataset_writer_stk_factor_pro.py)明确禁止 Serving upsert。

正常历史重刷不先删，按业务主键覆盖已有行、插入新行。**不要清空 Raw 后再用默认单日维护恢复历史**：清空会同时移除自动重刷所需的历史起点。源端删除历史记录的同步处理不在该机制内；确需物理清理，须另行审计和批准，不复用旧方案中的清表指令。

## 5. 事务、重跑与现有限制

[executor](/Users/congming/github/goldenshare/src/foundation/ingestion/executor.py)当前按 unit 提交，`fetch_concurrency=1`。一个 unit 失败时，其尚未提交的写入回滚；前面已经成功提交的 units 保留。不能把“DAO 已写入”直接等同于“事务已提交”。

本数据集没有专用刷新状态表或按持久化完成记录跳过 units 的续跑设计。重新维护依赖重新规划及 upsert 覆盖，不等于从失败页恢复；已存在的任务观测信息也不等于数据刷新 checkpoint。

当前 `page_processing_mode=buffer_all`：[source client](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)先在内存汇集单个 unit 的全部分页，再归一化和写入。Definition 未设置 `max_source_rows_per_unit` 或 `max_units_per_execution`，每页 10,000 行不等于整个历史 unit 的内存/行数上限。

以上是既有实现限制，不是对现行长任务规则的豁免。原方案“不做 checkpoint/续跑”的约定只保留为历史范围，不作为未来扩展的禁令或免验收依据。后续若开展长任务改造或大范围执行，须按[根 AGENTS](/Users/congming/github/goldenshare/AGENTS.md)和[数据集模板 §0.3.5](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)单独明确边界；本次文档合并不启动该改造。

## 6. 工作流、迁移与验证

[每日收盘后维护工作流](/Users/congming/github/goldenshare/src/ops/action_catalog.py)中 `adj_factor` 排在 `stk_factor_pro` 之前；这证明步骤顺序，不证明复权数据已齐。数据集日期与观测依据仍是 Definition 中的 `trade_date` 及其日期模型。

[20260531_000115](/Users/congming/github/goldenshare/alembic/versions/20260531_000115_stk_factor_pro_raw_view.py)记录从 Serving 物理表转为 Raw 视图的迁移逻辑，不清空 Raw。迁移代码存在与生产已执行是两类证据；本轮没有重新检查生产 revision、视图实际列或历史覆盖。

现有验证入口：

- [resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)：两类请求、目标日缺复权因子失败、变化股票历史范围、无历史起点跳过、显式股票和区间不触发变化审计。
- [Definition 测试](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)：存储、日期和对象完整性元数据。
- [writer 测试](/Users/congming/github/goldenshare/tests/test_dataset_writer_stk_factor_pro.py)：只写 Raw，保留对外 Serving 目标信息。
- [字段常量测试](/Users/congming/github/goldenshare/tests/test_fields_constants.py)、[运行注册测试](/Users/congming/github/goldenshare/tests/test_dataset_runtime_registry.py)及 [Ops 工作流测试](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)：相应字段入口、运行注册和目录约束；按实际改动范围选用，不把文件存在当作全部验收已通过。

原三份文档全文可从 Git 提交 `08216be3` 追溯。本次保留当前机制与必要历史依据，不以离线测试推断真实源端响应、生产全量覆盖或长任务可靠性已验收。

## 7. 历史区间回补解除复权因子前置检查（2026-10-16，待实施）

### 7.1 问题与修改目标

本节接续已合并的复权门禁和历史重刷方案，记录本会话确定的最小修改方向；本次授权仅为同步文档，开发、部署及正式回补尚未执行。

Tushare `stk_factor_pro` 已提供 `close_qfq/close_hfq`、对应技术指标及 `adj_factor` 等源字段。当前 [request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)只生成代码、日期等请求参数，[normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)做类型归一化，[writer](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)按主键直接 upsert；没有用本地 `core.equity_adj_factor` 重新计算这些复权指标。字段依据仍为 §1 的源资料与 Definition，本节不更改源端契约。

本地复权因子的实际用途是 §3 的默认全市场单日维护：比较 T/P 两日，判断哪些股票需要重新从源端获取历史技术因子。区间维护原本不运行该变化审计，却同样被逐日存在性检查阻断。因此，本次只解除区间维护的这项无关依赖，不能据此删除单日维护的检查或历史重刷能力。

### 7.2 修改后的硬口径

| 正式维护输入 | 归一化执行模式 | 本地复权因子存在性检查 | 复权变化历史重刷 |
| --- | --- | --- | --- |
| 单日、无股票过滤 | `point_incremental` | 保留；缺失仍报 `upstream_data_not_ready` / “先更新复权因子” | 保留现有 T/P 比较和 Raw 历史起点规则 |
| 单日、指定股票 | `point_incremental` | 保留当前按目标日至少一行的口径，不新增指定股票完整性要求 | 仍不追加 |
| 区间、无股票过滤 | `range_rebuild` | 不执行，不要求先补本地复权因子 | 仍不追加，不扩大区间 |
| 区间、指定股票 | `range_rebuild` | 不执行，不要求先补本地复权因子 | 仍不追加，不扩大代码或区间 |

1. 分支依据必须是 [resolver](/Users/congming/github/goldenshare/src/foundation/ingestion/resolver.py)从正式时间输入生成的 `run_profile`，不能按日期是否早于 2009 年、是否手动触发或区间天数判断。起止相同的一天区间仍按 `range_rebuild` 处理，与单日输入区别明确。
2. 在 `_build_stk_factor_pro_units` 中仅对 `range_rebuild` 跳过 `_ensure_stk_factor_pro_adj_factor_ready`；其他现有路径保持原样。不得全局删除 helper、吞掉异常或新增 `skip/bypass` 参数、配置项和前端开关。
3. 区间仍按正式交易日历展开，每个开市日一个 unit，源请求仍为 `trade_date`，可带原有 `ts_code`。不改成单次宽区间拉全市场，不改变分页、字段、主键或事务口径。
4. 只调整 `stk_factor_pro` 的规划条件；不修改 `DatasetDefinition`、日期模型、API/CLI 输入、前端控件、自动工作流顺序、指数因子逻辑或已有 HDD 存储规则。

### 7.3 改动位置与影响范围

| 位置或消费者 | 后续实施要求 |
| --- | --- |
| [unit planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py) | 唯一业务逻辑改动点：按 `range_rebuild` 限定跳过范围；保留单日检查和历史追加逻辑 |
| [resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py) | 替换现有“区间缺复权因子必须失败”的旧断言，新增下表正向、反向用例，不保留新旧双轨 |
| [手动任务服务](/Users/congming/github/goldenshare/src/ops/services/manual_action_service.py)、[dispatcher](/Users/congming/github/goldenshare/src/ops/runtime/task_run_dispatcher.py) | 创建时预检与 worker 执行时均通过同一个 resolver/planner 生效，不在 Ops 层另设绕过逻辑 |
| [运营手动任务页](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-manual-tab.tsx) | 继续提交原有日期区间和股票过滤，不新增参数或独立下载入口 |
| 本文 §3、§6 | 实施并验证后再同步为新现状；在此之前保留当前检查的真实描述 |

本次已使用仓库根 CodeGraph 的 `codegraph_explore`、`codegraph_callers`、`codegraph_impact` 核查影响面。helper 的直接调用方为 `_build_stk_factor_pro_units`；静态 impact 对字符串注册的 planner 分派覆盖有限，已补读 resolver、手动任务预检、dispatcher、前端区间请求构建及相关测试。修改范围不改变子系统边界或依赖矩阵；真实入口和数据验收仍是后续待验证项。

### 7.4 后续验收要求（本轮未执行）

| 必须覆盖的用例 | 通过条件 |
| --- | --- |
| 全市场区间，复权因子全缺失或部分日期缺失 | 两种情况均可生成完整日期 units；断言不调用存在性检查，也不查询复权变化或 Raw 历史起点 |
| 指定股票区间、起止相同的一天区间 | 同样不依赖本地复权因子；代码过滤、日期和源请求参数精确保持原输入 |
| 全市场单日、指定股票单日，目标日复权因子缺失 | 两种输入仍失败，错误码与提示不变，不能被区间分支误放行 |
| 单日复权因子就绪及变化股票历史重刷 | 保留现有单日成功、T/P 变化追加、无 Raw 历史不追加、指定股票不追加的回归行为 |
| 区间不越界、原输入校验继续有效 | 非开市日不生成 unit，不增加区间外日期或其它股票；非法时间输入仍由原合同拒绝 |
| 最小真实验证，另行获准后执行 | 选择本地复权因子缺失的 1–2 个历史交易日和一个明确股票，走正式维护入口；记录实际源请求、源端/归一化/写入行数、reject 原因及 Raw/view 按键读回结果，核验在 HDD，不要求上游 `adj_factor` 写入 |

源码测试修改后先运行相关 resolver、Definition 和 writer 回归，再核验正式入口。真实样本中的重复执行按现有 upsert 语义核对，写入量不误当新增量；不能仅凭规划成功宣称历史已补齐。

### 7.5 交付和执行边界

本次仅同步这一项方案，没有新增配置、数据表或旁路脚本。后续实际实施需按仓库数据集开发模板补齐本次变更对应的研发与验收记录，测试通过并按正式流程部署后，后台才具备上述区间行为。

解除复权门禁不等于解决 §5 的全量分页内存、续跑和长任务观测限制，也不证明全部历史交易日历或源数据完整。大范围 Prod 历史回补仍须单独满足[数据集开发模板 §0.3.5](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)的长任务门禁；本方案不授权一次执行几十年全市场数据，不新增可靠执行改造范围。已完成的 HDD 迁移和用户延期的四组查询性能验收继续按[迁移记录](/Users/congming/github/goldenshare/docs/ops/factor-pro-full-hdd-migration-plan-v1.md)处理，不与本项修改混为同一次验收。
