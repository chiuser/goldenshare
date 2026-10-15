# 股票技术面因子 stk_factor_pro 维护说明

更新时间：2026-10-16。§2–6 描述当前实现，§7 保留区间回补解除复权检查的方案与开工审计，§8 补齐有界批次的执行合同设计，待 review、未实施。方案和审计分别已提交为 `1a53b2616`、`7b3715d6`。本轮仅补合同文档，未改代码、部署、调用源接口或执行数据任务；设计完成不代表开发或生产执行已放行。

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

本节接续已合并的复权门禁和历史重刷方案，记录本会话确定的最小修改方向。用户先要求同步文档，随后要求提交方案、审计前置条件，并在满足时实施；方案已提交，实施因 §7.6 的前置缺口尚未开始。部署及正式回补不在本轮执行范围。

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
3. 区间仍按正式交易日历展开，每个开市日一个 unit，源请求仍为 `trade_date`，可带原有 `ts_code`。不改成单次宽区间拉全市场；`offset/limit` 分页语义和业务主键不变。为满足长任务门禁，拟增加 §8 的分页预算、逐页处理和逐日提交合同。
4. 复权条件改动仅针对 `stk_factor_pro`。补齐合同后，拟增加 Definition 的有界区间策略、执行器保障及由后端派生的批次限制/恢复能力，影响范围以 §8.8 为准；业务字段、日期模型、自动工作流顺序、指数逻辑和 HDD 存储规则不变。不再把整体改动称为只改一个条件。

### 7.3 改动位置与影响范围

| 位置或消费者 | 后续实施要求 |
| --- | --- |
| [unit planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py) | 复权条件改动点：按 `range_rebuild` 限定跳过范围；§8 另规定有界规划及执行保障 |
| [resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py) | 替换现有“区间缺复权因子必须失败”的旧断言，新增下表正向、反向用例，不保留新旧双轨 |
| [手动任务服务](/Users/congming/github/goldenshare/src/ops/services/manual_action_service.py)、[dispatcher](/Users/congming/github/goldenshare/src/ops/runtime/task_run_dispatcher.py) | 创建时预检与 worker 执行时均通过同一个 resolver/planner 生效，不在 Ops 层另设绕过逻辑 |
| [运营手动任务页](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-manual-tab.tsx) | 继续提交原有日期区间和股票过滤；§8 拟通过后端能力派生批次限制和既有恢复字段，不新增独立下载入口 |
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

本轮只同步方案及执行合同，没有实际新增配置、数据表或旁路脚本。后续实施需按数据集开发模板维护研发、测试与真实验收记录，测试通过并按正式流程部署后，后台才具备上述区间行为。

解除复权门禁本身不解决 §5 的执行限制。用户随后要求先补齐合同，§8 因此补充必要的执行保障设计；其新增实现范围仍待 review，不包含全站执行框架改造。本方案不授权一次提交几十年全市场数据。HDD 迁移及用户延期的四组性能验收继续按[迁移记录](/Users/congming/github/goldenshare/docs/ops/factor-pro-full-hdd-migration-plan-v1.md)处理。

### 7.6 提交后的开工前置审计：尚未满足，未编码

方案提交为 `1a53b2616`（`docs(datasets): plan factor history backfill gate change`）。用户要求的推进条件是先审计，满足后才实现；本次审计不把旧实现能够运行视为满足现行开发门禁。

| 审计项 | 当前证据与结果 |
| --- | --- |
| 改动范围与消费者 | 已确认。CodeGraph explore/callers 和当前代码显示，存在性检查由专用 `_build_stk_factor_pro_units` 调用；手动任务预检与 dispatcher 均复用 resolver。无需新增入口、配置或数据库结构；单日、区间的拟改边界见 §7.2 |
| 当前分支、改动冲突与测试环境 | 当前 `dev-interface`；拟改 planner 和 resolver 测试无本任务外未提交改动。现有 `.venv` 可直接运行测试，无需安装依赖 |
| 修改前回归基线 | `.venv/bin/python -m pytest -q tests/test_dataset_action_resolver.py -k stk_factor_pro`：9 passed，97 deselected。包含当前“区间缺复权因子失败”的旧行为，不代表新行为已通过 |
| 是否触发 Prod 长任务规则 | 触发。方案拟解除正式 `stk_factor_pro` 历史区间的规划限制，仍允许按日期扩大范围；Definition 的 `max_units_per_execution=None`、`max_source_rows_per_unit=None`，单页 10,000 行并非单 unit 总量上限，不能用“本轮不执行生产”代替开发前的合同设计 |
| 内存与规划持久化 | 尚未满足。`get_open_dates` 先返回完整日期列表，planner 汇集全部 units 后返回；source client 的 `fetch` 在 `rows_raw` 中汇集单 unit 的全部分页，`page_processing_mode` 默认 `buffer_all`。方案尚无具体批次/内存上限及长 PLAN 的分批持久化、冻结口径 |
| 恢复、进度与取消合同 | 尚未满足。§5 记录的按 unit 提交、主键 upsert 和重新规划，不等于完整的持久化续跑设计。方案未按模板逐项明确续跑依据、业务进度更新上限、取消检查点及延迟、TaskRun/节点一致终态和最小真实运行—取消—续跑—读回验收设计 |
| 数据集开发模板 | 尚未满足。§7 目前是行为差异方案与测试清单，尚未完成仓库根规则要求的完整模板及 §0.3.5 执行合同；不能把“后续补齐”作为开工通过依据 |

阻断依据为[仓库根规则](/Users/congming/github/goldenshare/AGENTS.md)“Prod 数据集长任务可恢复性与可观测性门禁”一节：第 1 条明确“缺少任何一项必须停下，不能编码后再补”，第 9 条要求新增或修改 Prod 数据集前完成数据集开发模板。这是开发前置要求，不能降为仅在生产回补前检查。

因此，本轮只完成方案提交、当前调用链审计及旧行为基线测试，没有修改 planner 或测试断言。§7.5 的“本次不新增可靠执行改造范围”不构成长任务规则豁免；当前方案不足以放行开发。

下一步须在原方案内明确可实际执行的范围、unit/分页/内存上限、持久化及恢复边界，并按模板补全相应合同和验证设计；若超出现有通用能力，需要先确认新增改动范围。不能擅自扩大为执行框架改造、创建新 worker，也不能直接删检查或补虚假复权因子行绕过门禁。当前未开展这些额外设计或实现。

以上保留为提交时的审计结论。后续用户已授权本轮补合同设计，新增内容见 §8；代码和真实验收缺口并未因补文档自动消失。

## 8. 有界历史区间执行合同（2026-10-16，设计待 review、未实现）

本节按[数据集开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)的 §0.3.4、§0.3.5 补齐本次变更的执行设计，不另建一份平行 LLD。数值是保守的拟定执行预算，不是生产吞吐实测结果，也不是已生效配置。完整模板的源端实测、字段及消费者对账仍按对应开发阶段核验；本节不宣称全部开工前置已通过。

### 8.1 执行范围与三个阶段

本合同仅覆盖 `stk_factor_pro` 的显式区间维护，支持全市场或原有单只 `ts_code` 过滤。较长历史由运营分成多个明确窗口，分别提交、验收；不自动拆成后台连续任务，不自动串接几十年历史，不增加 worker、队列、排程或独立下载入口。

1. **PLAN**：先校验范围预算，再按现有日期模型读交易日历，最多生成 31 个日期 unit。原子保存完整计划后才可 APPLY；没有半计划可执行入口。
2. **APPLY**：串行处理日期 unit，每页获取、归一化和分批写入；一个交易日一个业务事务。只在该日全部分页、写入和读回校验通过后提交。
3. **RECONCILE**：业务提交后独立更新 TaskRun/节点及完成凭据；恢复时核对凭据与真实 Raw 数据后决定跳过或重做日期 unit。观测更新不参与业务提交裁决。

保持 `trade_open_day/every_open_day`、`trade_date_or_start_end`、`observed_field=trade_date` 不变。时间输入、执行 unit 和 freshness/完整性仍是三个独立口径；成功请求一个空日期不等于该日期数据齐全。单日输入的复权门禁、T/P 变化审计及历史追加业务语义不变。

### 8.2 预算、来源与生效方式

拟在 Definition 增加可选的有界区间策略，由 planner 生成不可变的执行策略快照。通用模型默认关闭，仅本数据集区间启用；执行器消费计划快照，不在 Ops、页面或脚本复制参数。具体字段名随完整模型设计校准，但下列值和语义是本方案的设计基线。

| 策略项 | 拟定值 | 目的及所有执行消费者 |
| --- | ---: | --- |
| 单次日期范围 | 含首尾最多 31 个自然日 | validator 在读取完整日历前拒绝超限；catalog/API 派生上限，前端同步提示和校验 |
| 最大 unit 数 | 31 | planner、冻结计划、executor；禁止通过稀疏日历或直接请求绕过范围上限 |
| 并发 | 1 | executor 串行处理日期和分页，不改变通用 worker 数量 |
| 每页行数 / 每 unit 最大页数 | 1,000 / 16 | request builder/source client；offset 依次为 0、1000…15000 |
| 每 unit 最大源行数 | 16,000 | source client、normalizer；不能将单页上限误作全集上限 |
| 单页响应 / 单 unit 累计响应 | 4 MiB / 64 MiB | 源传输在收包及解码前检查；超限停止当前 unit，不截断后继续入库 |
| 单 unit Raw 校验范围 | 最多 20,000 个业务键 | writer/读回校验；包含已有行，超过即失败，不删旧行缩小范围 |
| SQL 写入批次 | 最多 100 行 | writer；261 个源字段及审计字段下避免过大绑定参数量，分批 flush，不逐批 commit |
| 业务工作集 / 执行进程 RSS | 增量最多 256 MiB / 总量最多 1 GiB | 控制器在分页及 SQL 批次边界检查；高于基线预算停止任务，不终止共享 worker |
| PLAN / 单 unit / 整次任务墙钟上限 | 5 秒 / 300 秒 / 3,600 秒 | 控制器；任何调用的实际 deadline 都取本动作与剩余预算较小值 |
| 单次源调用 / 自动重试 | 15 秒 / 0 次 | 源客户端与有界传输；不在 SDK、HTTP 层或分页循环隐式重试 |
| SQL statement / lock 上限 | 5 秒 / 2 秒 | 当前业务连接的局部设置；只影响本次执行，不修改数据库全局配置 |
| 独立观测 SQL 上限 | 1 秒 | 进度/取消/终态适配器，连接与事务独立于业务事务 |
| 请求速率 / 每次执行总请求数 | 最多 20 次/分钟 / 496 次 | 与已有账户级限流共同取更严限制；等待时检查取消并报告真实等待阶段 |
| 冻结计划 / 完成凭据 / 单次诊断大小 | 256 KiB / 64 KiB / 16 KiB | TaskRun 投影、节点 context、诊断序列化；不保存整页源数据或全量行情 JSON |

配置审计：这些预算拟只定义在 `src/foundation/datasets/**`，随代码版本加载并派生到 catalog；持久化位置为 TaskRun 中 resolver 生成的执行快照及其 hash。没有新增 env、Settings、数据库配置表、页面可编辑预算或脚本常量。新代码发布后仅新任务生效；已冻结任务恢复必须匹配原策略版本，不用新默认值悄悄覆盖。运维在任务详情能看到生效预算、已用预算和超限原因。模型、linter、registry、resolver、source client、executor、writer、Ops 投影及前端均须测试相同来源；任何消费者缺失不得放行实现提交。

请求量计算：N 个开市日、每日至多 16 页，上界 `16N≤496` 次；第 16 页若仍为满页，无法证明全集结束，当前日必须失败，不能把 16,000 行当作完整结果。20 次/分钟下耗尽预算的速率时间约 24.8 分钟，另有网络和 SQL 耗时，并受 1 小时总上限约束；这是预算推导，不是 ETA。限流账户条件不明或已有任务占用配额时，保持更严限流或失败，不提高并发和预算。

### 8.3 PLAN 与分页内存边界

**PLAN**：先以首尾日期检查 31 日上限，不先读取无限日历。按现有 exchange 来源枚举开市日，不新增 `exchange` 运营输入。每批最多 31 个 unit，计划是有界小对象，5 秒内完整校验并原子保存 `plan_id`、策略/Definition/字段 hash、规范化日期与过滤、日历日期列表及其 hash、每个 `unit_id`。TaskRun 仅保存 resolver 的投影，不自行生成源参数。

单位身份由版本、数据集、日期、规范化股票过滤及策略 hash 计算，同一冻结意图恢复得到相同 `unit_id`。范围、过滤、字段、策略版本或日历日期集合不匹配时拒绝恢复，要求发起新意图；不默默重新规划后继续旧任务。创建前预检与 worker 使用同一校验，worker 保存完整计划后才取第一页。PLAN 取消、超时或进程退出没有业务写入，部分草稿不可执行；因已严格限制为小计划，不引入长 PLAN 草稿表。

**分页**：复用 `offset_limit` 语义，以短页（含空页）证明结束。每页处理完即可释放响应、Raw JSON 和归一化对象；禁止再经当前 `fetch()` 把该日全部分页汇集到 `rows_raw`。跨页只保留最多 16,000 个键及行摘要，用于去重和完整性校验，内存随固定预算而非历史日期数增长。相同键且内容相同可去重并计数；同键内容冲突、错误日期/代码、超页数/行数/字节数必须报错，不覆盖掩盖异常。

已有 `bounded_tushare_call.py` 可作为有界传输的能力基础，但当前错误前缀依赖公告/周线合同，不能原样冒充通用股票因子实现。拟先将传输预算和错误域显式化，调用同一通用能力；不 import 周线/公告业务执行逻辑，不保留两套 HTTP 重试链。若完整审计发现不能无损复用，须先更新本设计，不能自行新增旁路客户端。

### 8.4 业务持久化、幂等与恢复

**业务事务**：一个 unit 为一个目标交易日，带可选单股过滤；它不包含默认单日维护追加的其它历史范围。每页最多 1,000 行、每批最多 100 行，同一业务事务内逐批写 Raw，最后一页及日级读回校验通过后一次 COMMIT。事务最多 300 秒，不跨日期或覆盖整段历史；源调用、限流等待期间也受该 deadline 约束。超时、取消、源异常或 reject 均回滚当前日，前面已提交日期保留。任何 reject 不能作为正常完成跳过，必须记录 reason code 和有界样本。

幂等键仍为 `(ts_code, trade_date)`，upsert 插入新行、更新已有行；不先删、不清表、不修改 Serving view。Tushare 返回的复权价格和技术指标直接作为业务值，不以本地 `adj_factor` 重算。源行数须能拆分为唯一有效行、相同重复行和拒绝行；写入量与新增量分别记录。

**读回与完成凭据**：当前日写入后、提交前，在该日及过滤范围内流式读回最多 20,000 个键，按同一规范化算法计算业务键/业务值摘要和行数；不把 `fetched_at` 等审计时间纳入摘要。校验本次源键均已写入且业务值一致，原有额外行保留并单独计数；再计算提交后的完整目标范围摘要。凭据保存 `unit_id`、冻结 hash、源唯一/重复/reject/写入/新增/已有行数、源摘要、目标范围摘要、提交时间及校验版本，不保存 16,000 行的完整内容。

摘要算法也须冻结版本：按 Definition 的业务字段顺序、`(ts_code, trade_date)` 排序，以长度前缀区分字段，空值独立标记、日期统一 ISO；数值按目标列类型归一化，Float(53) 用统一 binary64 表达，拒绝非有限值，零值统一规范化。源端预期值和库内读回必须复用同一纯函数，以增量 SHA-256 聚合；`api_name/fetched_at/raw_payload` 等审计字段不参与业务摘要。Raw 读回每批最多 1,000 行，不能用 ORM identity map 或全量 DataFrame 隐式积累整个窗口。

拟复用已有 `dataset_plan` 节点的 `context_json` 保存最多 31 份完成凭据，不新增专用 checkpoint 表或第二套任务状态机。凭据是校验索引，不是业务数据的替代事实。它在业务 COMMIT 后由独立观测事务保存；保存失败不得阻止、回滚或重试已经提交的业务数据，可以在本次进程内保留有界待投影队列，并在后续观测更新中补写。进程同时退出导致凭据丢失时，下次必须重做该日，不能假定完成。

**恢复算法**：运营通过已有 `resume_from_task_run_id` 表达恢复意图，拟为本数据集开放其后端能力派生；当前接口/页面尚不支持，不能直接使用。

1. 校验来源为同数据集、同模式、同范围/过滤/版本的已停止任务，复制原冻结意图，新 TaskRun 关联来源；旧任务和记录保留。不得扩大日期或更换股票后仍叫续跑。
2. 按冻结的日期顺序扫描各 unit。存在匹配凭据时，用 Raw 的对应日期/过滤范围重新计算行数和业务摘要；完全匹配才跳过。只读回一个有界日期，不做全表 hash。
3. 凭据缺失、目标内容发生变化或 commit 结果未知时，重新从该日第一页拉取并幂等 upsert。禁止仅凭 `unit_done`、节点 success、页码或 `fetched_at` 跳过；禁止从未知的 offset 接着拉，避免源端分页变化造成漏行。
4. 恢复先核验已完成 unit 后设置起始完成量，再处理剩余 unit；同一 TaskRun 内完成量只增不减。单日重做消耗本次请求预算，所有恢复都需运营显式发起，不无限自动重试。

源端没有提供跨日不可变快照版本，本合同冻结的是意图与策略，不承诺各日源数据来自同一源快照。恢复日期若重拉则以当次源端业务值为准，记录实际抓取时间；不得声称恢复保持了源端从未承诺的历史版本一致性。

**空源结果**：HTTP/结构/日期过滤校验通过的零行响应可记录为“请求完成、源端无记录”，不删已有数据、不推进该日业务 freshness 或判为数据齐全。保存空源证据和未改变的目标范围摘要；无持久化凭据时重拉。零行、拒绝全量行及接口错误三者必须分别展示。

### 8.5 并发、取消、进度与终态

**既有入口和并发**：继续使用通用 worker、TaskRun、同一个 resolver/executor。拟对本数据集写入使用 PostgreSQL 会话级 advisory lock，由专用业务连接持有并跨日 COMMIT 保持，异常退出自动释放；单日业务的源请求和复权规则不变，但必须尊重相同写入互斥规则，避免回补与自动历史重刷交错覆盖。连接丢失时禁止透明重连继续写，新任务只能在取得锁后开始。锁获取最多 2 秒，冲突返回清晰原因，不杀连接、不自动暂停服务。

互斥 key 由固定命名空间和数据集身份经稳定 hash 得到，不能使用进程随机化的 Python `hash()`；从取得锁到终态/退出始终使用同一专用连接，不能在连接池归还后误认为仍持锁。来源任务仍 running 且锁可取得时，恢复流程必须先核验冻结合同和修复旧终态；锁不可取得则不创建第二个写入者。

正式执行方案须记录可能冲突的单日任务、工作流和人工写入；需要暂停排程时，仍通过正式管理员入口并恢复原状态，不直接改 schedule。本合同不操作 #2/#24 或其它排程。外部 SQL 不遵守应用互斥时应停止后续 unit 并报告，不能承诺应用锁能阻止任意外部写入。

**取消**：在 PLAN 前后、每个 unit/分页/SQL 批次前后、读回批次前后、提交前后及限流等待中检查。等待每 1 秒检查一次；源传输须可中断，不能仅给请求线程一个不可终止的 Future。单次源调用硬上限 15 秒、SQL 5 秒，收到取消到停止领取新工作并回滚当前日的目标不超过 25 秒，真实验收不满足即阻断发版。已 COMMIT 的日不撤销，提交后收到取消不再领下一日。

源与数据库调用必须遵守端到端截止时间；服务器 `statement_timeout` 本身不能证明客户端断网时也能及时返回。实现阶段须审计既有驱动的可取消 IO、连接失效和事务收尾，不能用不可中断线程绕过截止时间。取消意图读取失败属于控制状态未知，停止领取新 unit 并对未提交日报错回滚；这与“观测写失败仅影响观测、不能回滚业务数据”必须分开处理和测试。

**进度**：复用 TaskRun 的 `unit_total/unit_done/progress_percent/current_object_json/updated_at`、节点和既有详情页。阶段为规划、取数、写入、读回、等待限流、结束；当前对象明确日期、可选股票、页号/offset、页行数、已处理行数及预算余量。收到页、写完批次、读回完成和提交日均更新业务进度，正常观测间隔不超过 5 秒；阶段内长调用显示真实阶段及已用时间，不伪增完成量。无可靠 ETA 时继续显示“暂无法估算”。

观测通过独立连接/事务写入，超时 1 秒，失败仅影响观测。连续 30 秒未更新时，页面显示“观测暂不可用”，不伪造心跳为业务进度；接口本身不可用时由前端显式展示读取错误。观测恢复后从凭据/Raw 校验重建进度，不据旧心跳宣布成功或另启重复执行。

**终态**：业务完成后，TaskRun 与当前 `dataset_plan` 节点在同一观测事务内分别按现有 success/failed/canceled 语义进入一致终态；不得只更新一方。观测事务失败时两者均不部分提交，已提交 Raw 保留，任务不得标记结案。后续正式恢复入口先取得同一数据集锁，确认旧执行者已经退出，再修复旧 TaskRun/节点的一致 failed/canceled 终态并建立新任务。只有 source 取消意图存在才使用 canceled，进程中断使用 failed 并记录原因；锁仍被占用则拒绝恢复，不凭更新时间擅自判死或强制并行。此终态修复属于拟实现能力，当前没有验收证据。

### 8.6 长任务合同对账（对应模板 §0.3.5）

| 合同项 | 本方案的具体答案 | 追溯项 |
| --- | --- | --- |
| 长任务判断 | 31 日、最多 496 次源请求，可能超过 60 秒；按长任务设计 | EXEC-01 |
| 最小 unit / 总量 | 一个交易日、可选股票过滤；最多 31 个 unit，PLAN 最多 5 秒 | EXEC-01、02 |
| 页数、行数、耗时 | 每页 1,000 行；16 页、16,000 源行、300 秒/unit，满上限不能确认结束则失败 | EXEC-03 |
| 批次及内存 | 每页释放；SQL 100 行；键摘要集有固定行数上限；增量 256 MiB、RSS 1 GiB | EXEC-03、04 |
| 业务持久化 | 同一日全部分页及读回通过后 COMMIT，日期之间独立 | EXEC-04 |
| 幂等与恢复 | `(ts_code,trade_date)`；凭据加 Raw 读回验证，否则从该日第一页重做 | EXEC-05 |
| 进度与 ETA | 5 秒正常更新、30 秒观测失联提示；完成量只按校验/提交的日推进，未知 ETA 如实显示 | EXEC-06 |
| 取消与延迟 | unit/页/SQL/读回前后及等待中检查；取消目标≤25秒，不再领新 unit | EXEC-07 |
| TaskRun/节点终态 | 同一独立观测事务写一致终态；中断后取得写入锁再修复，不回滚 Raw | EXEC-08 |
| 既有入口及并发 | 通用 worker、正式维护与恢复入口；同数据集写入互斥，不增基础设施 | EXEC-09 |
| 事务一致性 | 一日一事务、SQL 5秒/锁2秒，unit总deadline300秒，无全历史事务 | EXEC-04、07 |
| 最小真实验收 | 见 §8.9 的运行—取消—退出—续跑—读回及观测故障矩阵，尚未执行 | EXEC-10 |

### 8.7 硬需求追溯账本（对应模板 §0.3.4）

全部条目当前仅为设计完成、实现与验收待进行。实现阶段必须在本表补实际测试名称、结果与证据路径，不能预填“通过”。

| ID | 硬需求、实现位置及消费者 | 正向 / 反向验证设计 |
| --- | --- | --- |
| EXEC-01 | Definition 有界策略、validator、catalog、运营日期控件共同限定31日；源字段和日期模型不变 | 31日/单股/全市场可规划；32日及直接API超限拒绝；前后端上限来源一致 |
| EXEC-02 | resolver/planner 冻结≤31个 unit，TaskRun 保存完整投影后才执行 | 起止相同的区间稳定生成range计划；半计划、策略/hash/日期或过滤漂移禁止APPLY/恢复 |
| EXEC-03 | source client、有界传输、linter 执行分页/行数/字节/请求/速率预算 | 多页及短页正确结束；满第16页、超字节、隐藏重试、错误日期/代码均拒绝，当前日不提交 |
| EXEC-04 | executor、normalizer、writer 按页和100行批次写入，一个日期事务 | 单日分页成功后可读回；中途reject、SQL失败、超内存/耗时只回滚当前日，前日不变 |
| EXEC-05 | 节点完成凭据、Raw 摘要、TaskRunCommandService 恢复校验 | 有凭据且Raw相符可跳过；凭据丢失/Raw改变/commit未知重拉该日，重复主键不增行 |
| EXEC-06 | TaskRunIngestionContext、详情页和现有ETA派生 | 阶段及页/批次有真实进度；完成量不倒退，未知ETA/30秒观测失败不伪装正常 |
| EXEC-07 | 控制器、源调用、writer、读回和限流等待 | 每个边界可取消；取消≤25秒、不领取下一日；不能用仅进程存活证明响应取消 |
| EXEC-08 | dispatcher、TaskRun/节点终态与恢复入口 | 成功/失败/取消一致；业务COMMIT后观测失败不撤销Raw；进程退出后锁释放、旧终态修复后恢复 |
| EXEC-09 | 共用业务连接互斥、正式维护/恢复API、运营原任务页 | 同数据集冲突拒绝、其它数据集正常；API现有恢复字段只按后端派生能力开放，旧任务在运行时不能并行恢复 |
| EXEC-10 | 测试、目标库及正常认证入口 | 完整最小验收矩阵、源端/归一化/去重/拒绝/写入/读回对账；源错误不算空数据或成功 |
| EXEC-11 | 专用股票 planner、原单日工作流 | 区间缺复权因子可规划且不查T/P；全市场/指定股票单日仍保留原门禁，变化历史追加回归不变 |

### 8.8 实现影响面与阶段

1. **策略与合同**：拟修改 `src/foundation/datasets/models.py`、`definitions/market_equity.py`、ingestion 的执行计划/校验/linter，并同步数据集模板中新增合同口径。原有无策略数据集不得误启用这些预算；配置来源与冻结语义见 §8.2。
2. **规划与业务执行**：拟修改 `unit_planner.py`、`source_client.py`、`executor.py`、`writer.py` 及必要的通用有界传输/控制接口。所有执行策略仍由 Definition/plan 传递，foundation 不依赖 Ops，不按页面参数另立执行分支。
3. **Ops 与前端消费者**：拟修改 TaskRun 的命令/dispatcher/ingestion context、catalog/请求投影、手动任务页、详情页及共享 API 类型，使预算、既有恢复字段和观测语义一致。当前前端只对公告显示恢复输入、后端对本数据集拒绝恢复，必须一起迁移；不复用公告/周线的业务规则。仅保留原维护入口，TaskRun/节点仍是唯一任务状态机。
4. **存储**：业务表、视图、字段、主键、索引及 HDD 位置不变。完成凭据拟用既有节点 context，不新增数据库表或 migration；若实际审计证明容不下或语义不符，必须回到本方案评审，不能私建checkpoint表。共享 contract 若发生变化，先完成全部消费者清单与模板对账，再编码。

本轮使用 CodeGraph explore/search/impact 辅助检查，并补读当前执行器、source client、有界传输、TaskRun 命令/dispatcher/进度适配、节点模型与运营页面。`TaskRunIngestionContext` 的 impact 指向 dispatcher 及现有进度大小、节点同步、写失败容错测试，可作为后续回归入口；这不是全部新合同消费者已迁移的证明。当前仅修改本文，未实际改变边界或依赖矩阵。

上述为待 review 的最小保障范围，不是已获准实施清单。必须先补齐模板的源端与字段证据、准确配置/消费者审计，并明确每个阶段的准入后，才能开始实现；不能只改复权条件就宣布本合同生效。

### 8.9 自动化与最小真实验收设计（均未执行）

离线测试必须覆盖：§7.4 全部条件，31/32日边界，零页/短页/满16页，跨页相同及冲突主键，错误日期/代码，页大小/行数/字节/内存上限，隐藏重试，单 unit 和总 deadline，100行写批次及事务提交，源端空/错误/全拒绝的区别，以及所有 EXEC 条目的正向与反向路径。

另行获准后先在隔离验证库执行，不直接在正式历史表做故障注入。选一个源端确有记录的早期股票和两个相邻开市日、确认本地相应 `adj_factor` 为空，保持源请求有界。下列每一轮都记录代码版本、冻结hash、TaskRun/节点ID、实际参数、源/归一化/去重/reject/写入/新增/目标行数、提交范围和Raw/view读回证据：

| 轮次 | 操作与必须证明的结果 |
| --- | --- |
| A 正常 | 经正式维护API提交两日区间，正确落库及读回，复权因子表不写入；在任务页看实际阶段与完成量 |
| B 取消 | 第一天提交后在第二天源调用、写批次或读回阶段取消；≤25秒响应，第一天保留、第二天未提交，不领取新unit |
| C 进程退出 | 分别在COMMIT前、COMMIT后且凭据未落盘时退出本次隔离执行者；自动释放互斥，不终止共享生产服务，读回区分已提交与回滚 |
| D 恢复与幂等 | 经正常恢复入口同范围续跑；已验证日期可跳过，未知日期重拉；完成无重复键，修改过滤/版本及真实仍持写入锁的来源恢复均被拒绝；失联且锁已释放的旧running来源按§8.5先修复终态 |
| E 观测故障 | 业务COMMIT之后注入TaskRun/凭据写失败，Raw不回滚；恢复后能校验/重做并修复成对终态，进度不虚增 |
| F 源与预算故障 | 超页/字节/超时及同键冲突只失败当前日；零行单独报告，已有数据不删除，所有预算不自动上调 |

浏览器按 10 秒采样记录进度，验证正常更新不超过 30 秒、ETA未知显示及取消交互；不能只用API/单元测试替代页面验收。完整矩阵通过后，才可另行申请生产代表性两日验收，核验实际仍写 HDD。生产不得默认复用隔离故障注入步骤；所有正式写入须另有明确日期、股票、任务和窗口授权。

### 8.10 状态、发布及下一步

本轮完成的是执行合同设计补充，不是实现、部署、生产回补、测试通过或开发准入结论；本轮只运行文档静态检查。没有新增或修改生效配置、表结构、worker、排程、源请求或数据。

下一步先 review §8.2 的执行预算和 §8.8 的新增实现范围，再在同一维护说明内完成完整模板的开工核验和配置/消费者清单。若源端实测、内存采样或代码审计与设计冲突，先修正文档并确认，不临时提高预算、缩减验收或把未实现能力当作可用能力。

实现后按 EXEC 账本逐项验收，再按正常流程部署；没有生产写入授权不运行真实回补。应用回退只能停止新任务并保留已提交的 Raw 数据，不能通过删表、清表或自动回迁 HDD 撤销。正在运行的任务须先经正式取消并确认停止；旧代码不能读取新冻结合同或完成凭据时，必须先解决版本兼容策略，禁止回退后用旧入口继续该冻结任务。HDD 四组查询性能验收仍按用户延期决定，不纳入本轮合同设计验证。
