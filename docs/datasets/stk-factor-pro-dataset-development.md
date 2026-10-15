# 股票技术面因子 stk_factor_pro 维护说明

更新时间：2026-10-16。§2–6 描述当前仓库代码，§7 的最小修改已实现并通过本地回归，§8 保留已撤回扩大设计的历史记录。本次只让股票因子历史区间跳过复权存在性检查，单日逻辑不变。尚未部署、执行真实同步或生产回补，不能据此认定生产行为已改变。

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

[planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)仅在非 `range_rebuild` 模式调用 `_ensure_stk_factor_pro_adj_factor_ready`。单日模式仍查询目标日的 `core.equity_adj_factor`，只要存在至少一行就通过；完全没有数据则以 `upstream_data_not_ready` 失败，提示“先更新复权因子”。

单日检查不是全市场完整性检查，也不保证显式选择的那只股票已有复权因子。历史区间无论是否指定股票、是否只有一天，均跳过这项存在性检查；不按日期早晚区分。区间原本就不追加复权变化历史重刷，本次保持该行为。该最小修改已在仓库实现并通过本地测试，见 §7；尚未部署。

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

- [resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)：两类请求、单日缺复权因子失败、区间不调用复权存在性检查、变化股票历史范围、无历史起点跳过、显式股票和区间不触发变化审计。
- [Definition 测试](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)：存储、日期和对象完整性元数据。
- [writer 测试](/Users/congming/github/goldenshare/tests/test_dataset_writer_stk_factor_pro.py)：只写 Raw，保留对外 Serving 目标信息。
- [字段常量测试](/Users/congming/github/goldenshare/tests/test_fields_constants.py)、[运行注册测试](/Users/congming/github/goldenshare/tests/test_dataset_runtime_registry.py)及 [Ops 工作流测试](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)：相应字段入口、运行注册和目录约束；按实际改动范围选用，不把文件存在当作全部验收已通过。

原三份文档全文可从 Git 提交 `08216be3` 追溯。本次保留当前机制与必要历史依据，不以离线测试推断真实源端响应、生产全量覆盖或长任务可靠性已验收。

## 7. 历史区间同步解除复权因子检查（2026-10-16，已实现、本地回归通过、未部署）

### 7.1 目标与原因

Prod 已有股票技术面因子的单日和区间同步能力。本次只解决一个阻断：历史区间同步在规划每个交易日时，仍要求本地 `core.equity_adj_factor` 当日存在数据，缺失则报“先更新复权因子”。不重建同步能力，不把既有执行链改造成新的回补系统。

修改前，[专用 planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)的 `_build_stk_factor_pro_units` 对每个日期无条件调用 `_ensure_stk_factor_pro_adj_factor_ready`；本次仅在该调用外增加 `request.run_profile != "range_rebuild"` 条件。同文件的 `_build_stk_factor_pro_adj_factor_refresh_units` 已限定只在无股票过滤的 `point_incremental` 下比较 T/P 复权因子并追加历史 unit，区间模式直接返回。因此，历史区间的存在性检查与其实际执行路径不匹配。

现有 [request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)生成日期、代码等请求参数，[normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)做类型归一化，[writer](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)直接 upsert 源端业务值。本次不改源字段或复权计算；字段和源资料继续以 §1 为准。

### 7.2 必须保持的行为

| 正式维护输入 | resolver 生成的模式 | 修改后的本地复权因子检查 | 复权变化历史重刷 |
| --- | --- | --- | --- |
| 单日、无股票过滤 | `point_incremental` | 保留；缺失仍报 `upstream_data_not_ready` / “先更新复权因子” | 保留现有 T/P 比较及 Raw 历史起点规则 |
| 单日、指定股票 | `point_incremental` | 保留现有按目标日至少一行的检查，不新增指定股票完整性要求 | 仍不追加 |
| 区间、无股票过滤 | `range_rebuild` | 跳过，不查询本地复权因子是否存在 | 仍不追加，不扩大区间 |
| 区间、指定股票 | `range_rebuild` | 跳过，不查询本地复权因子是否存在 | 仍不追加，不扩大股票或区间 |

硬约束：

1. 只按正式 `run_profile == "range_rebuild"` 跳过检查；其它路径仍执行原检查。不能按日期早晚、是否人工触发、股票代码或区间天数判断。
2. 起止相同的一天区间仍是 `range_rebuild`，跳过检查；同一天以单日模式提交则是 `point_incremental`，保留检查。
3. 保留 `_ensure_stk_factor_pro_adj_factor_ready` 及原错误码、提示，不全局删除、不吞异常，不新增 `skip/bypass` 参数、开关或配置。
4. 保留现有交易日历展开、每日一个 unit、原 `trade_date` 及可选 `ts_code` 请求、分页、按 unit 提交和 upsert 逻辑。不修改 Definition、日期模型或执行计划结构。
5. 复用现有运营入口与通用 worker。不修改 API/CLI 请求合同、前端、排程、工作流顺序、指数因子逻辑、表结构或 HDD 存储位置。
6. 本次不新增 31 日限制、分页预算、逐页流式处理、专用续跑、数据集互斥锁、进度改造或故障注入项目。这些不属于解除复权检查的实现范围。

### 7.3 实际改动文件与消费者

本次只修改以下三个文件，保留原有文档纠偏：

| 文件 | 具体改动 |
| --- | --- |
| [unit_planner.py](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py) | 已在 `_build_stk_factor_pro_units` 的现有存在性检查调用外增加模式条件：只有 `range_rebuild` 跳过；日期 unit 构建和历史追加 helper 保持原逻辑 |
| [test_dataset_action_resolver.py](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py) | 已替换旧的区间缺因子失败断言，补齐区间跳过、单日保留及输入边界回归，详见 §7.5、§7.7 |
| 本文 | 已更新 §3 的仓库现状、测试结果及状态；明确未部署，不把本地结果当作生产事实 |

以下是已核验、未修改的消费者和通用能力：

- [resolver](/Users/congming/github/goldenshare/src/foundation/ingestion/resolver.py)：现有 point/range 输入分别生成 `point_incremental/range_rebuild`，包括起止相同的区间。
- [手动任务服务](/Users/congming/github/goldenshare/src/ops/services/manual_action_service.py)和 [dispatcher](/Users/congming/github/goldenshare/src/ops/runtime/task_run_dispatcher.py)：提交前预检与 worker 规划均调用同一 resolver，条件只在专用 planner 实现，不在两处分别绕过。
- [运营手动任务页](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-manual-tab.tsx)：继续提交原有 `time_input.mode`、起止日期及股票过滤，没有新控件或入口。
- Definition、request builder、source client、executor、normalizer、writer：沿用现有合同与行为，不借本次修改顺手扩展执行能力。

本轮已用仓库根 CodeGraph 的 `codegraph_explore`、`codegraph_callers`、`codegraph_impact` 核验专用 planner、检查 helper、resolver 和 request builder，并补读相关测试、手动任务预检、dispatcher 和前端时间输入构建。检查 helper 的直接调用方只有 `_build_stk_factor_pro_units`；静态 impact 对注册分派覆盖有限，不能用其结果代替上述入口代码核验。本方案不改变子系统边界或依赖矩阵。

### 7.4 实施步骤（本次按已确认计划执行）

1. **基线**：确认当前为 `dev-interface`，planner 和测试文件无冲突改动；修改前定向测试 9 项通过。
2. **先补测试**：更新区间旧断言及参数化正反例，原业务代码下 12 个区间用例失败、10 项通过，失败均指向原复权检查。
3. **修改条件**：只给原检查调用增加 `run_profile != "range_rebuild"` 条件，不改 helper、日期 unit 构建和历史追加逻辑。
4. **回归与对账**：定向测试 22 项通过，约定的完整回归 188 项通过，Definition lint 通过；行为对账见 §7.7。
5. **交付停止**：更新当前仓库行为与结果，保留未部署、未真实验收状态；不自动提交或推进生产操作。

### 7.5 验证范围与通过条件（本地回归通过，真实同步未执行）

| 用例 | 必须证明的结果 |
| --- | --- |
| 全市场区间，本地复权因子全部缺失或仅部分日期缺失 | 都能生成原有日期 units；对检查 helper 或对应查询设置调用即失败的断言，证明不是依靠测试数据碰巧通过 |
| 指定股票区间 | 同样跳过检查；unit 日期和 `ts_code` 精确保留，不加入其它股票 |
| 一天区间与相同日期的单日输入 | 前者跳过；后者缺因子仍失败。不能把区间天数作为判断条件 |
| 全市场单日、指定股票单日缺复权因子 | 两者均保持原错误码和提示，不被误放行 |
| 单日复权因子就绪及变化股票重刷 | 原有单日成功、T/P 变化追加、无 Raw 起点不追加、指定股票不追加等用例继续通过 |
| 区间不追加、不越界及既有输入校验 | 不查 T/P 变化和 Raw 历史起点；只生成原日历返回的开市日 units；不增加区间外日期或代码，非法输入仍由原校验拒绝 |
| 原请求与写入路径 | 保持 `trade_date`、可选 `ts_code`、原分页与 `raw_only_upsert`；无需修改源请求或 Serving 写入方式 |

原 `test_stk_factor_pro_range_fails_when_any_trade_date_lacks_adj_factor` 已替换为 `test_stk_factor_pro_range_does_not_require_adj_factor`，覆盖全缺失/部分缺失及全市场/指定股票，并 spy 检查 helper 确认未调用。`test_stk_factor_pro_range_does_not_run_adj_factor_audit` 已加强为复权或 Raw 历史查询一旦调用即失败，覆盖早期/近期、多日/一天区间及股票过滤，精确核对日历日期、请求、分页和写入路径。单日缺因子测试参数化覆盖早期/近期及股票过滤；原单日成功、变化历史追加和 request builder 测试保留。测试均使用 mock/stub，不能替代真实数据验收。

后续另行获准真实验证时，选择一个明确股票和本地复权因子缺失的 1–2 个历史开市日，通过原有正式维护入口提交区间，记录计划日期、实际源请求、源端/归一化/写入行数、reject 及 Raw/view 按键读回结果；不写复权因子表。数据仍应落入已有 HDD 表空间。该验证只验收本次解除检查，不扩大到全历史回补、执行框架故障演练或已延期的 K 线性能测试。

### 7.6 交付与执行边界

用户已明确批准按最小计划实施。本次完成 planner 条件、回归测试和本文更新，没有修改运行配置或范围外文件。实现阶段未自动提交；随后用户明确要求提交本次三个文件。未推送、部署、运行真实同步或生产写入，不能当作生产功能已经生效；提交记录以 Git 为准。

§5 的内存、重跑和任务观测限制继续如实保留；本次解除检查不声称修复它们，也不把更早的日期可通过规划说成历史数据完整。仓库根规则和数据集开发模板保持有效，本专题文档不豁免规则；后续开工核验如发现某条规则与本次最小范围存在具体冲突，应单列条款、代码证据及所需决策说明，不能自行扩成整套执行能力改造。

本次交付范围仅为 §7.2 的行为差异、§7.3 的三个文件及约定的本地验证。此前要求确认扩大实现范围、31 日手动分批的事项已撤回，不作为本次改动的一部分。提交按用户后续指令办理；发布和真实数据验收仍需另行授权。

### 7.7 本地验证记录与计划对账（2026-10-16）

| 检查 | 命令与结果 |
| --- | --- |
| 修改前基线 | `.venv/bin/python -m pytest -q tests/test_dataset_action_resolver.py -k stk_factor_pro`：9 passed、97 deselected |
| 新回归验证旧问题 | 同一定向命令，业务代码修改前：12 failed、10 passed、97 deselected；4 个缺因子区间被原门禁阻断，8 个日期/过滤场景触发禁止查询断言 |
| 修改后定向回归 | 同一定向命令：22 passed、97 deselected |
| 约定的完整回归 | `.venv/bin/python -m pytest -q tests/test_dataset_action_resolver.py tests/test_dataset_definition_registry.py tests/test_dataset_writer_stk_factor_pro.py tests/architecture/test_subsystem_dependency_matrix.py tests/architecture/test_dataset_runtime_registry_guardrails.py`：188 passed |
| Definition 静态检查 | `.venv/bin/goldenshare ingestion-lint-definitions`：passed |
| 文档与差异检查 | `python3 scripts/check_docs_integrity.py`：三项检查通过；`git diff --check -- src/foundation/ingestion/unit_planner.py tests/test_dataset_action_resolver.py docs/datasets/stk-factor-pro-dataset-development.md`：通过 |
| 范围核验 | 与实施前保存的跟踪文件 SHA-256 对比，三个指定文件之外的文件内容无变化；实现完成核验时暂存区为空 |

硬口径对账：仅按模式跳过、一天区间和不同年代由参数化区间测试覆盖；单日缺因子仍失败及原错误由单日参数化测试覆盖；T/P 变化、Raw 起点和单股不追加由原有测试覆盖；日期、过滤、请求、分页与 Raw 写入由区间精确断言及原 writer/request builder 回归覆盖。没有增加源参数、配置、入口或执行合同，没有改变架构边界。

未执行项：真实 Tushare 请求、正式入口同步及 Raw/view 生产读回、部署、生产回补、排程调整、四组 K 线查询性能验收。本次本地测试不证明生产数据已补齐或生产已切换新行为。

## 8. 纠偏与历史方案记录（已撤回内容，不作为实施依据）

- `1a53b2616` 提交原最小方案；`7b3715d6` 提交后续前置审计，当时执行过股票因子相关 resolver 基线：9 passed、97 deselected。这是历史测试记录，不是本轮或新行为的验收结果。
- `e6160905` 将既有执行限制扩展成 31 日上限、逐页预算、专用续跑、互斥及 Ops/前端改造的待评审合同。用户随后明确需求只是让历史同步跳过复权检查，因此这一扩大设计及其作为解除检查前置的结论均撤回。全文留在该 Git 提交，不继续作为当前待实现清单。
- 本轮以 §7 收敛后的最小方案为实施依据。没有声称旧审计发现的限制已修复，没有修改根规则，也不在本次方案中另设执行预算。
- 已完成的 HDD 迁移和延期的四组 300/2000 查询验收继续按[迁移记录](/Users/congming/github/goldenshare/docs/ops/factor-pro-full-hdd-migration-plan-v1.md)处理，与本次解除检查分开。
