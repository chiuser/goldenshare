# Dagster 股票分钟线 QFQ 计算测试与生产 Check 治理低层设计

更新时间：2026-07-15

状态：代码收敛完成；QFQ/MACD-KDJ 范围内本地验证通过。全仓共享治理测试目前受无关的 `dc_board` 未提交 catalog 变更阻塞，详见第 15 节；不得启用或初始化已撤销的 as-of basis 方案。

## 1. 结论

QFQ 的计算公式正确性由受保护的测试金样本证明；生产 check 不重复计算 QFQ OHLC。check 只验证真实运行时可能偏离预期的输入、文件和状态事实。

这不是降低质量要求，而是把不同问题交给正确的机制：测试发现代码算法错误，check 发现本次生产的输入或文件错误，repair 状态检查防止历史文件已改而旧状态仍被误用。

## 2. 职责边界

| 机制 | 只负责 | 明确不负责 |
| --- | --- | --- |
| QFQ 公式金样本测试 | 日常公式、repair 公式、OHLC、五个 native 频度、90m/120m 派生、因子变动、空值和边界日期的预期输出 | 读取正式 Lake、判断当天上游是否齐备、写 Dagster event |
| production asset check | 上游当天缺代码/缺因子/重复行/空值/字段漂移；目标文件存在、schema、分区、唯一键、原子写入结果；repair 状态是否与实际改写范围一致 | 对完整分钟线重复执行 QFQ OHLC 公式；从已有 QFQ 结果反推分母；证明历史源端当年的业务判断正确 |
| lake readiness / sensor | QFQ 日常 sensor 在最近 5 个交易日内、factor repair 与 MACD/KDJ sensor 在最近 10 个交易日内，复刻仍然 active 的 production blocking checks，选择首个未 ready 日期 | 扫描历史 Dagster event 解释红色公式 check；运行全历史公式审计；把 check failed 改判为 ready |
| factor repair 状态账本 | 记录 repair 上游 batch、代码集合 hash、范围、七频度 completion；供下游 repair gate 判断是否需要或已经完成 | 为每个历史 QFQ 分区补普通 materialization/check event；替代 QFQ 文件契约检查 |

## 3. 公式测试契约

### 3.1 测试内容

QFQ 计算 helper 的测试必须覆盖：

1. 日常写入：`as_of_trade_date = target_trade_date`，OHLC 预期值与 silver 输入一致的边界。
2. factor repair：指定 repair 日期作为显式分母，历史每个交易日仍使用自己的同日因子作为分子。
3. 因子未变化时不产生 repair replacement；因子变化时只影响已选代码和日期范围。
4. 五个 native 频度的字段、行数、`trade_time` 对齐和 OHLC 输出；90m/120m 只从 native QFQ 派生。
5. 缺因子、零/非有限因子、重复键、空关键字段、日期错位和生命周期边界必须 fail closed。
6. repair 后的 MACD/KDJ scoped repair 输入范围与 QFQ repair metadata 一致。

### 3.2 金样本保护规则

1. 测试中的 expected OHLC 必须是人工确认的字面量；禁止调用被测 QFQ helper 生成 expected 值。
2. 公式、repair 或派生逻辑变更时，必须同时提交设计口径、fixture 输入、expected 输出和变更原因；只改断言让测试通过属于禁止行为。
3. 不得删除、跳过、缩小金样本来换取通过；静态门禁应保护核心 QFQ formula fixture 和测试文件仍被执行。
4. 测试只使用临时 DuckDB / 临时 Parquet fixture，不读取正式 Lake、Dagster instance 或生产数据库。

### 3.3 现有代码的后续收敛点

后续代码专项应把公式验证从 `defs/checks/stk_mins_checks.py` 和 `asset_guards/stk_mins_lake_readiness.py` 移至受保护测试。现有 `tests/test_stk_mins_qfq_m8b_checks.py`、`tests/test_stk_mins_qfq_m8c_history.py`、`tests/test_stk_mins_qfq_m9c_factor_repair.py` 的有效 formula fixture 应整理为稳定测试契约；不得丢弃已有反例。

## 4. QFQ production check 集合

native QFQ 正式 blocking checks 只保留以下生产事实：

| 类别 | 目标事实 | 失败含义 |
| --- | --- | --- |
| contract | 目标年份文件存在、schema、freq、路径和目标日期一致 | 分区选错、写半截、字段漂移或文件损坏 |
| key integrity | `ts_code + trade_time` 无空值、无重复，交易日与分区一致 | 输入或写入产生身份错误 |
| value domain | 价格、成交量、成交额等业务字段满足既有非公式 domain 约束 | 空值、非法数值或源端异常进入结果 |
| source coverage | 当天 silver 代码集合、同日 adj factor、目标 QFQ 代码集合和行覆盖关系完整 | 上游缺代码、缺因子、漏写或多写 |

`gold_stk_mins_qfq_formula_matches_silver_adj_factor` 不再作为正式 Dagster check，也不进入 catalog、job selection、readiness spec 或 sensor 判断。MACD/KDJ 的 `formula_sample` 同理退回测试金样本，production check 只保留文件/状态/来源覆盖事实。

## 5. Repair 状态与历史文件

1. factor repair 改写 QFQ 历史文件后，不补全历史普通 QFQ materialization/check event，避免大规模 Dagster DB 写入。
2. repair plan/status/completion 继续作为小规模状态账本，metadata 必须包含上游 batch 身份、代码数/hash、范围和频度；下游 scoped repair 只消费这一事实。
3. 日常 QFQ readiness 只判断最近 5 个交易日的正式 production checks；factor repair 与 MACD/KDJ 使用既有的最近 10 个交易日窗口。它们均不读取 repair event 来覆盖一个失败 check。
4. 旧历史没有当时的 formula 生产依据时，不伪造绿色公式状态。历史文件未来被 repair 重写时，repair 状态自然记录其改写范围；这不等同于历史普通 QFQ event 回填。

## 6. 已撤销的 as-of basis 路线与代码影响

当前仓库中已提交但尚未获准启用的 as-of basis 实现，与本设计冲突。后续代码专项必须完整删除，而不是保留 dormant fallback：

1. `defs/stk_mins_qfq_as_of_basis.py`、`bootstrap/stk_mins_qfq_as_of_basis.py`、`bootstrap/stk_mins_qfq_as_of_basis_cli.py`、相关 paths/schema 和测试。
2. `defs/stk_mins_qfq.py` 中 `*_from_as_of_basis` SQL builder，以及 daily/repair/history 写入中的 basis upsert。
3. `defs/checks/stk_mins_checks.py` 中 native QFQ formula check 注册、catalog blocking check 清单和相应 check metadata。
4. `asset_guards/stk_mins_lake_readiness.py` 中年度 basis 文件读取、QFQ 公式重算和 basis validation；batch readiness 改为只复刻第 4 节的生产 check。
5. 三个 QFQ / MACD-KDJ sensor 中对 basis-ready 的假设，以及文档中将它描述为当前事实的文字。

旧 `effective_gold_qfq_readiness_for_trade_date(...)` repair-event 覆盖逻辑不恢复。目标是单一事实：production checks 失败就是未 ready；公式逻辑由测试保障，不在 readiness 中出现第二套例外。

## 7. 性能口径

1. 不执行全历史 QFQ 公式 bootstrap，不创建 `gold/quote/stk_mins_qfq_as_of_basis/**`，不增加 Lake 侧车文件。
2. QFQ 日常 sensor 热路径最多读取最近 5 个交易日；factor repair 与 MACD/KDJ 相关热路径最多读取最近 10 个交易日对应的 QFQ/silver/adj factor 文件集合。它们只运行 production contract/key/value/coverage 聚合，不做 OHLC 重算。
3. check/readiness 不得将分钟行扩成 OHLC 四倍中间行，不得扫描全历史，不得使用 Dagster event history 解释公式差异。
4. 因子 repair 的 `freq/year` 批量计算性能方案保留；它是实际写入逻辑，不是 check 的重复验证。

## 8. 实施顺序与验收

1. 先按本文同步治理、性能和 QFQ 设计文档。
2. 单独审计并设计代码删除/收敛专项；不得在该专项之外顺手修改 QFQ 计算公式或 repair 范围。
3. 本地 fixture 测试必须证明公式金样本完整，production checks 不再执行 QFQ OHLC 重算，batch readiness 不再 import as-of basis。
4. `git diff --check`、相关 unit/static-gate 测试和文档完整性检查通过后，才可讨论 definitions reload 或正式实例只读验证。
5. 不运行 bootstrap plan/apply，不写 Lake、不写 Dagster instance、不启停 sensor；这些均不属于本治理文档实施阶段。

## 9. 代码审计冻结基线

本节是后续代码专项唯一的实现基线。以下结论来自 2026-07-15 对当前 `dev-interface` 源码、调用方、测试和 CodeGraph 影响面的逐项审计；不是根据名称或历史文档推断。

### 9.1 本次代码专项的硬约束

1. 不改变 QFQ 日常写入、factor repair 写入、90m/120m 派生写入和 MACD/KDJ 计算的业务公式、分区、路径、run key、job selection、sensor 触发顺序或动态分区。
2. 不写 Lake、Dagster instance、prod DB；不做 bootstrap、backfill、runless event、历史状态清理或 sensor 启停。
3. 不保留 as-of basis 的兼容入口、fallback、空实现或 dormant 文件。代码删除后，活跃源和测试均不得再引用该概念。
4. 不让 check/readiness 通过重算 OHLC、MACD、KDJ 或把旧 repair event 解释为“公式正确”来改变 ready 结论。
5. 仍然保持 fail-closed：缺上游文件、缺因子、重复/空 key、schema 或分区错误、源窗口不完整、目标文件不完整、repair completion 元数据失配，都必须阻断。
6. `batch_gold_stk_mins_qfq_lake_readiness(...)` 的公共输入、返回类型和 batch 调用方式保持不变；sensor 不直接改逻辑，只通过该稳定入口获得收敛后的事实结论。

### 9.2 已确认的当前运行事实

| 事实 | 当前实现证据 | 本专项结论 |
| --- | --- | --- |
| 日常 native QFQ 写入的分子和分母都读取目标交易日的 `silver_adj_factor` | `defs/assets/stk_mins.py::write_gold_stk_mins_qfq_asset_partition` 将 `as_of_adj_factor_file_path` 赋值为 `trade_adj_factor_file_path` | 删除 basis sidecar 不改变日常 QFQ 输出。 |
| factor repair 仍使用既有显式 repair 触发日分母 | `defs/stk_mins_qfq_factor_repair.py` 的既有 repair select 生成路径 | 本专项不触碰 repair 计算或写入范围；只移除其 sidecar 写入。 |
| 90m/120m 的正式派生写入由 `build_gold_stk_mins_qfq_derived_select_sql(...)` 完成 | `defs/stk_mins_qfq.py` | 该完整 OHLC builder 只能留给 asset 写入和本地算法金样本，不能继续被 production check/readiness 用作预期结果。 |
| native / derived active check 各为 5 条，其中一条是 formula check；MACD/KDJ 指标每频度为 3 条，其中一条是 formula sample | `defs/checks/stk_mins_checks.py`、`defs/checks/stk_mins_qfq_macd_kdj_checks.py` | 目标分别收敛为 native 4、derived 4、指标 2；不新增任何 check。 |
| QFQ 日常 sensor 的 readiness 窗口是 5 个交易日；QFQ factor repair 与 MACD/KDJ 日常 sensor 使用通用 10 个交易日窗口 | `defs/sensors/stock_mins_qfq_daily_sensor.py::STOCK_MINS_QFQ_DAILY_READINESS_WINDOW_LIMIT = 5`；`defs/run_contracts/stk_mins.py::STK_MINS_CONTINUITY_WINDOW_LIMIT = 10` | 本文此前泛称“最近 10 天”不精确，以下统一按“日常 QFQ 5；repair/M12 10”执行。 |
| 三个 QFQ/M12 sensor 源码没有直接 import as-of basis | `stock_mins_qfq_daily_sensor.py`、`stock_mins_qfq_factor_repair_sensor.py`、`gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor.py` | sensor 业务决策、run key、cursor 和窗口不改；只验证其调用的 readiness 返回事实已更新。 |
| `checks_for_assets(...)` 驱动 QFQ/M12 job 的 check selection | QFQ / M12 job 定义 | 删除 active check definition 后，job selection 自动收敛；不修改 job 文件。 |

### 9.3 读前门禁

代码开始前必须执行一次只读 preflight，并把结果写入本专项实施报告：

1. `gold/quote/stk_mins_qfq_as_of_basis/**` 必须不存在或为空。若发现任何文件，停止；本专项没有删除 Lake 文件的授权。
2. `rg` 必须列出所有 `as_of_basis`、`formula_matches`、`formula_sample` 消费者；实际结果必须仅属于第 10、11、12 节列出的文件。出现新增消费者即停止并补 LLD。
3. 现有 QFQ/M12 资产、job、sensor 和 dynamic partition 名称与本节一致。若 definitions 已有漂移，先审计并修正文档，不直接按本 LLD 改代码。

## 10. 精确生产代码改动表

本表中的“删除”是完整删除，不留兼容包装；“收敛”是保留已有正确计算或运行入口，只剥离生产公式复算和 sidecar 依赖。

### 10.1 完整删除的 as-of basis 文件与契约

| 文件 | 当前符号 / 位置 | 当前职责 | 精确改动 | 必须验证 |
| --- | --- | --- | --- | --- |
| `orchestrator/defs/stk_mins_qfq_as_of_basis.py` | `build_qfq_as_of_basis_rows_sql`、`write_gold_stk_mins_qfq_as_of_basis`、`qfq_as_of_basis_*`、`_basis_write_lock` | 生成、写入、校验年度 sidecar | 删除整个模块。 | 源码、import graph、静态门禁均不再出现模块或符号。 |
| `orchestrator/defs/bootstrap/stk_mins_qfq_as_of_basis.py` | `plan_*`、`apply_*`、`audit_*`、`build_qfq_as_of_basis_history_reconstruction_sql` | 全历史重建、审计和自推导公式核对 | 删除整个模块；不得替换为新的 bootstrap。 | `defs/bootstrap` 无 as-of basis plan/apply/audit。 |
| `orchestrator/defs/bootstrap/stk_mins_qfq_as_of_basis_cli.py` | `main`、`plan` / `apply` CLI | 上述 bootstrap 的命令入口 | 删除整个模块。 | 无 CLI、无 `/private/tmp/stk_mins_qfq_as_of_basis_*` 新报告入口。 |
| `orchestrator/defs/paths.py` | `gold_stk_mins_qfq_as_of_basis_path`（当前约 171-179 行） | sidecar 路径 | 删除该 path helper。 | 所有 path consumer 清零；其他 QFQ path 不变。 |
| `orchestrator/defs/run_contracts/asset_column_schemas.py` | `GOLD_STK_MINS_QFQ_AS_OF_BASIS_SCHEMA`（当前约 253-259 行） | sidecar Parquet schema | 删除该 schema。 | `asset_column_schemas` 仍只保留活跃资产 schema。 |
| `orchestrator/tests/test_stk_mins_qfq_as_of_basis.py` | 全文件 | sidecar / bootstrap 的测试 | 删除整个测试文件。 | 以新的金样本测试覆盖算法行为，不能因删除测试而降低公式覆盖。 |

### 10.2 保留计算、移除 sidecar 写入的生产路径

| 文件 | 当前符号 / 位置 | 保留内容 | 精确改动 | 明确禁止 |
| --- | --- | --- | --- | --- |
| `orchestrator/defs/stk_mins_qfq.py` | `build_daily_qfq_select_sql`（约 142 行）、`_build_daily_qfq_select_sql` | 日常和 repair 共用的 QFQ SQL 算法 | 保留不改公式。删除 `build_daily_qfq_select_sql_from_as_of_basis`（约 156 行）和 `build_daily_qfq_coverage_sql_from_as_of_basis`（约 255 行）。 | 不改 `silver_price * trade_adj_factor / as_of_adj_factor` 的计算表达式。 |
| `orchestrator/defs/assets/stk_mins.py` | `write_gold_stk_mins_qfq_asset_partition`（约 1980 行） | 同日 factor 覆盖校验、QFQ select、年度文件原子写入 | 删除 `write_gold_stk_mins_qfq_as_of_basis(...)` 调用和 `GoldStkMinsQfqPartitionWriteResult` 的 `as_of_basis_years` / `as_of_basis_changed_year_count` 字段。 | 不改输入文件、覆盖 gate、replace trade date、QFQ 文件布局或 materialization 数量。 |
| 同上 | `_gold_stk_mins_qfq_extra_metadata`（约 2872 行） | QFQ 资产说明 metadata | 删除 `as_of_basis_contract`、`as_of_basis_path_template` 和“sidecar 持久化分母”文案；改为准确说明：日常写入按目标交易日 factor 计算。 | 不新增 metadata 路径或历史依据。 |
| `orchestrator/defs/stk_mins_qfq_factor_repair.py` | 当前 sidecar import 与 repair 完成后的 sidecar write（约 188-203 行） | 因子变化检测、代码/日期 scoped repair、QFQ 文件写入、completion metadata | 删除 sidecar import 和写入。 | 不改 repair 代码集合、频度、批次、分母日期、completion check 数量或 run key。 |
| `orchestrator/defs/bootstrap/stk_mins_qfq_history.py` | `StkMinsQfqHistoryReport.basis_write_results`（约 74 行）及约 200 行 sidecar write | 既有历史 QFQ 文件生成计划和写入 | 移除 sidecar 类型、结果字段、import 和写入段。`planned_event_count` 继续从 active check tuple 动态计算。 | 不在本专项运行 history bootstrap；不人为补 event。 |

### 10.3 native QFQ 正式检查：从五条收敛为四条

文件：`orchestrator/defs/checks/stk_mins_checks.py`。

| 当前符号 / 区域 | 精确改动 | 目标结果 |
| --- | --- | --- |
| `GOLD_STK_MINS_QFQ_NATIVE_CHECK_NAMES`（约 185-189 行） | 删除 `GOLD_STK_MINS_QFQ_FORMULA_MATCHES_SILVER_ADJ_FACTOR_CHECK`。 | 只保留 `contract`、`key_integrity`、`value_domain`、`source_coverage`。 |
| `GOLD_STK_MINS_QFQ_FORMULA_TOLERANCE`、`_gold_qfq_formula_counts_sql`（约 658 行）、`_gold_qfq_formula_sample_sql`（约 724 行） | 删除。 | production check 不比较 expected / actual OHLC。 |
| `GoldStkMinsQfqCheckCounts`（约 204 行） | 删除所有 `formula_*`、`*_as_of_basis`、`*_as_of_source_factor` 计数；只保留文件、schema、key、value domain 和同日 factor 覆盖所需计数。 | metadata 不出现 formula / basis 证据。 |
| `_gold_qfq_check_results`（约 792-1109 行） | 删除 formula result、formula samples、basis validation metadata。 | 返回恰好四个 blocking result。 |
| `_gold_stk_mins_qfq_check_results`（约 1402-1642 行） | 删除年度 basis path、basis 文件输入、source factor 追溯、`build_daily_qfq_select_sql_from_as_of_basis(...)` 和 basis coverage。改为以同一份目标日 `silver_adj_factor` 调用既有 `build_daily_qfq_coverage_sql(...)`，只求输入/输出覆盖数量。 | `source_coverage` 仍能发现银层缺代码、当天 factor 缺失、目标 QFQ 漏写/多写；不计算 OHLC。 |
| `_build_gold_qfq_native_multi_check`（约 3506 行） | 不改 factory 机制；由四项 tuple 自动生成 definition。 | 不改 asset key、check severity 或 partition。 |

说明：QFQ SQL builder 仍接受 numerator / denominator 两组 path，因为 repair 写入仍有显式分母语义。native 日常 production check 只把同一个目标日 factor 文件传入两组参数；它记录的是“当日 factor 覆盖是否齐”，不是“历史 as-of 分母是否正确”。

### 10.4 derived QFQ 正式检查：保留窗口身份，删除 OHLC 预期计算

文件：`orchestrator/defs/stk_mins_qfq.py`、`orchestrator/defs/checks/stk_mins_checks.py`。

| 当前符号 / 区域 | 精确改动 | 目标结果 |
| --- | --- | --- |
| `build_gold_stk_mins_qfq_derived_select_sql`（约 331 行） | 保留，仍只给 90m/120m asset 写入和本地公式金样本使用。 | 正式写入算法不变。 |
| `build_gold_stk_mins_qfq_derived_diagnostics_sql`（约 431 行） | 保留，继续统计 source row、expected/generated window、incomplete window、exchange mismatch。 | check/readiness 仍能发现 source 窗口不完整或交易所混杂。 |
| 新增 `build_gold_stk_mins_qfq_derived_coverage_sql(...)` | 复用 diagnostics 的 source/window map 和完成谓词，但只投影 `ts_code`、`trade_date`、`trade_time`、`freq`、`exchange` 等身份字段；禁止投影或聚合 OHLC、vol、amount。 | 给检查精确核对“应该出现哪些目标窗口”和“实际目标 key 是否覆盖”，而不重新算价格。 |
| `GOLD_STK_MINS_QFQ_DERIVED_CHECK_NAMES` | 删除 `GOLD_STK_MINS_QFQ_DERIVED_FORMULA_MATCHES_SOURCE_CHECK`。 | derived active check 同样为 contract/key/value/derived source coverage 四条。 |
| `GoldStkMinsQfqDerivedCheckCounts`、`_gold_qfq_derived_check_results`、`_gold_stk_mins_qfq_derived_check_results`（约 1113、1646 行） | 删除 `formula_*` 计数、samples 和 `_gold_qfq_formula_*` 调用；用新 coverage SQL 推导 expected output key / 文件路径，并将实际 target key 与 source-window identity 对比。 | 可识别漏窗口、多窗口、错误分区、重复/空 key、损坏文件、源窗口不全；不比较价格。 |
| `_build_gold_qfq_derived_multi_check`（约 3535 行） | factory 不改，随 tuple 生成四项 definition。 | asset identity、severity、partition 不变。 |

这是本专项最敏感的收敛点。当前 derived check/readiness 都调用完整 `build_gold_stk_mins_qfq_derived_select_sql(...)`，即便最后只显示 coverage，也已经构造了期望 OHLC。实施时必须改为 coverage-only helper；仅删除 check 名而仍调用完整 select 是不合格实现。

### 10.5 readiness：保留 batch 性能模型，删除公式 / basis 判断

文件：`orchestrator/defs/asset_guards/stk_mins_lake_readiness.py`。

| 当前符号 / 区域 | 精确改动 | 验收重点 |
| --- | --- | --- |
| 顶层 imports（当前含 formula constants、basis path、`*_from_as_of_basis`、basis validation） | 删除上述 import。 | 模块文本不再出现 `as_of_basis` 或 production QFQ formula check 常量。 |
| `_GoldQfqReadinessPlan` 及构造处（当前约 209、1218 行） | 删除 `as_of_basis_path` 字段及构造。 | 每个计划只描述 source/gold 文件，不新增替代 state。 |
| `_gold_qfq_native_batch_formula_counts`（约 1498 行） | 整段删除。 | batch readiness 不重算 native OHLC。 |
| `_gold_qfq_native_batch_counts`（约 1763 行）和 `_gold_qfq_native_counts_for_trade_date`（约 2000 行） | 删除 basis 搜索、年度 source factor 校验、formula counts；仅保留与 native 四个 active check 等价的批量文件/contract/key/value/same-day factor coverage。 | 热路径没有 basis 文件读取、没有 OHLC SQL。 |
| native failed-check 映射（约 2195 行） | 删除 formula failure 分支，保留四条真实阻断原因。 | materialized 但任一 active check 失败仍未 ready。 |
| `_gold_qfq_derived_batch_formula_counts`（约 2470 行） | 整段删除。 | batch readiness 不重算 derived OHLC。 |
| `_gold_qfq_derived_batch_counts`（约 2658 行）及单日 derived helper（约 2873 行） | 用第 10.4 节 coverage-only helper 取代完整 derived select；保留 diagnostics 和 contract/key/value 聚合。 | 不完整窗口、exchange mismatch、输出缺失仍 fail-closed。 |
| derived failed-check 映射（约 2995 行） | 删除 formula 分支，仅映射四条 active check。 | ready 语义与 catalog / check definition 一致。 |
| `_gold_qfq_status_for_trade_date`、`batch_gold_stk_mins_qfq_lake_readiness`（约 3035、3328 行） | 对外签名、`StkMinsDateReadiness` 结构和批量调用策略不改。 | 不逐日调用 single-date helper；不增加 Dagster event 查询。 |

### 10.6 catalog 与 readiness 契约

| 文件 | 当前位置 | 精确改动 | 不变项 |
| --- | --- | --- | --- |
| `orchestrator/defs/sensors/readiness.py` | `GOLD_STK_MINS_QFQ_NATIVE_CHECKS`、`GOLD_STK_MINS_QFQ_DERIVED_CHECKS`（约 92-104 行） | 删除两个 formula check 名。 | `GOLD_STK_MINS_QFQ_READINESS_SPECS` 的公共使用方式不变。 |
| `orchestrator/defs/catalog/lake_assets.py` | QFQ native / derived / MACD-KDJ check tuple（约 375-394 行） | 删除两个 QFQ formula check 和一个 MACD/KDJ formula sample check。 | asset 名、路径、schema、分区、source system、数据集身份均不改。 |
| `orchestrator/defs/checks/stk_mins_qfq_macd_kdj_checks.py` | `GOLD_STK_MINS_QFQ_MACD_KDJ_CHECK_NAMES`（约 49-53 行）、`_indicator_formula_result`（约 383 行）、`_build_indicator_check`（约 660 行） | 删除 `formula_sample` 常量、tolerance、formula result 和 factory branch；指标 active check 每频度仅保留 `contract`、`source_coverage`。state 两条 check 不动。 | MACD/KDJ 指标/状态写入算法、state 续算、七频度、job selection 不变。 |
| `orchestrator/defs/bootstrap/stk_mins_qfq_macd_kdj_baseline_events.py` | `_audit_indicator_asset_partition`（当前约 386-416 行） | 删除显式 `formula_sample` audit tuple，只审计 active 的 contract / source coverage 两条。 | 不运行 baseline event；现有 runless event 和历史记录不改。 |

### 10.7 已审计为“不得修改”的文件

| 文件 / 范围 | 为什么不改 |
| --- | --- |
| `defs/jobs/stock_mins_qfq_daily_update.py` 与 M12 job 定义 | 都用 `checks_for_assets(...)`；active check tuple 收敛后 selection 自然收敛，手改 job 会扩大风险。 |
| `defs/sensors/stock_mins_qfq_daily_sensor.py` | 日常窗口 5、run window、run key、cursor 和 RunRequest 逻辑均不属于本问题；它只消费稳定 readiness API。 |
| `defs/sensors/stock_mins_qfq_factor_repair_sensor.py` | repair decision、10 日窗口、run key 和 sensor state 不改；只验证其 readiness 结果不再含 formula check 名。 |
| `defs/sensors/gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor.py` 及 repair sensor | 不直接消费 basis；不改触发逻辑或 repair pairing。 |
| QFQ/M12 catalog 以外的资产、Dagster run/event 历史、dynamic partitions、Lake 历史 Parquet | 本专项没有写入或清理授权；旧公式 check event 仅保留为历史记录，不再参与 active readiness。 |

## 11. 测试设计与文件级改动矩阵

### 11.1 新增、受保护的公式金样本

新增两个测试模块，均只使用 `TemporaryDirectory`、临时 Parquet 和本地 DuckDB；不得读取正式 Lake、Dagster instance 或生产数据库。

| 新文件 | 金样本范围 | 必须使用的断言 | 保护规则 |
| --- | --- | --- | --- |
| `orchestrator/tests/test_stk_mins_qfq_formula_golden_contracts.py` | five native daily QFQ、factor repair、90m/120m derived、缺失/零/非有限 factor、重复/空 key、日期错位、源窗口不全与 exchange mismatch | 固定 fixture 输入，人工确认的字面量 OHLC/volume/amount/identity 输出；repair 同时断言选中代码和未选中代码；负例必须 fail-closed。 | expected 值不得调用 `build_daily_qfq_select_sql`、`build_gold_stk_mins_qfq_derived_select_sql`、writer 或被测 helper 生成。 |
| `orchestrator/tests/test_stk_mins_qfq_macd_kdj_formula_golden_contracts.py` | 固定 QFQ close 序列、已有 state、跨日续算、scoped repair 范围 | 人工确认的字面量 DIF、DEA、MACD、K、D、J 和新 state；确认 repair 只覆盖 metadata 指定的范围。 | expected 值不得调用 MACD/KDJ 计算 helper 反推。 |

金样本是算法回归线，不是方便改写的快照。任何公式、窗口、state 定义变更，都必须同时提交：业务理由、fixture 输入、人工复核 expected 值、影响范围和本 LLD 的同步说明。只修改 expected 让测试通过是阻断性违规。

### 11.2 现有测试的精确改动

| 测试文件 | 当前覆盖 / 当前问题 | 精确改动 |
| --- | --- | --- |
| `tests/test_stk_mins_qfq_as_of_basis.py` | sidecar 写入、history bootstrap、basis 公式核对 | 删除全文件；等价算法案例迁移至新的 QFQ golden 文件。 |
| `tests/test_stk_mins_qfq_m8b_checks.py` | 写入 sidecar fixture、lazy formula samples、formula mismatch | 删除 basis fixture 和 formula 测试；断言 native 仅四条，分别覆盖缺文件、schema、重复/空 key、非法值、同日 factor/输出 coverage。 |
| `tests/test_stk_mins_lake_readiness.py` | basis fixture；`test_gold_qfq_batch_readiness_detects_formula_failure` | 删除 basis fixture；将 formula failure 用例替换为真实事实失败：缺 target factor、缺 target QFQ key、derived 源窗口不完整或输出 key 缺失。保留 batch 不得逐日调用 helper 的断言。 |
| `tests/test_stk_mins_qfq_m8c_history.py` | `basis_write_results` | 移除 sidecar report 断言；断言 history report 只包含 QFQ 年度写入结果，event 数由四项 active check 动态得出。 |
| `tests/test_stk_mins_qfq_m9c_factor_repair.py` | repair 计算、batch、completion | 删除 sidecar 预期；保留 repair output / metadata / batch 测试，并把一个具有 literal expected QFQ 值的场景提升到 golden suite。 |
| `tests/test_stk_mins_qfq_sql_helpers.py` | daily formula helper | 删除 `*_from_as_of_basis` import/case；保留并增强 daily literal formula / 非价格字段不变 / input fail-closed 测试。 |
| `tests/test_stk_mins_qfq_m11_derived_assets.py` | 90m/120m output | 保留写入算法测试；添加 coverage-only helper 只返回身份列的断言，以及 incomplete/exchange mismatch 能阻断、不生成正常窗口身份的反例。 |
| `tests/test_stk_mins_qfq_macd_kdj_check_contracts.py` | formula sample Dagster metadata | 删除 formula check metadata 用例；断言指标 check 只有 contract/source coverage，state check 仍为两条。 |
| `tests/test_stk_mins_qfq_m12_macd_kdj.py` | 已有 expected formula 例子 | 保留资产写入行为；将当前 `test_macd_kdj_writes_indicator_and_state_with_expected_formulas` 的固定序列补足为新 golden test 的字面量断言来源。 |
| `tests/test_stk_mins_qfq_m12_sensor_contracts.py` 与 QFQ sensor contract tests | fake `failed_check_names` 含 formula 名 | 改用仍 active 的 `source_coverage` 或 `contract` 名，继续证明“已有 materialization 但 blocking check 失败”会 skip。不得修改 run key/window/选择顺序断言。 |
| `tests/test_asset_check_incremental_governance.py` | 三组活跃 check 期望清单仍含 formula | 改为 native 4、derived 4、指标 2、state 2 的精确集合。 |
| `tests/test_stk_mins_qfq_m8c_history.py`、`tests/test_stk_mins_qfq_m8d_events.py`、`tests/test_stk_mins_qfq_m11f_derived_history.py` | 事件数以每资产分区 `1 + 5 = 6` 写死 | native / derived 改为每资产分区 `1 + 4 = 5`；同步更新相应 history / dry-run 断言，但不生成或删除任何 event。 |
| MACD/KDJ history / baseline event 测试 | 每频度分区事件数由 `2 materialization + 3 indicator checks + 2 state checks = 7` 推导 | 改为 `2 + 2 + 2 = 6`；仅测试计划计数和 audit check 集合，不运行 apply。 |
| `tests/test_stk_mins_continuity_performance.py`、`tests/test_batch_readiness_hotpath_performance.py` | basis path / current batch query 期望 | 删除 basis fixture；新增“batch readiness 不含 formula SQL、不读 basis、derived readiness 不调用完整 derived select”的性能/静态断言。 |
| `tests/test_run_contract_static_gates.py` | 当前约 2497-2550 行错误要求 basis 文件和函数存在 | 改写为删除门禁：文件不存在、活跃源不含 basis/from-as-of/formula check，且 golden tests 存在并被验证命令显式覆盖。保留对旧 `effective_gold_qfq_readiness_for_trade_date(...)` workaround 的禁止。 |

### 11.3 必须新增的静态门禁

1. `defs/` 的活跃生产源中不得出现 `stk_mins_qfq_as_of_basis`、`as_of_basis`、`build_daily_qfq_select_sql_from_as_of_basis`、`build_daily_qfq_coverage_sql_from_as_of_basis`。
2. `GOLD_STK_MINS_QFQ_*CHECK_NAMES`、catalog 和 readiness spec 中不得出现两个 QFQ formula check；MACD/KDJ active indicator tuple 中不得出现 `formula_sample`。
3. `stk_mins_lake_readiness.py` 不得出现 `formula_*` count/sample/helper，也不得引用 `build_gold_stk_mins_qfq_derived_select_sql(...)`。它只能调用 coverage-only / diagnostics helper。
4. QFQ/M12 active check factory 生成的定义数量精确为：native `5 freqs x 4 = 20`、derived `2 freqs x 4 = 8`、M12 indicator `7 freqs x 2 = 14`、M12 state `7 freqs x 2 = 14`。此处是 definition 数，不是补历史 event 的计划。
5. golden 测试源不得把被测 helper、writer 或完整 select SQL 的结果作为 expected 值来源；fixture expected 必须显式保存字面量。
6. QFQ 日常 sensor 窗口仍为 5，factor repair 与 M12 仍为 10；禁止为了本专项改为全历史或扩大窗口。

## 12. 性能预算与验收方法

### 12.1 目标性能模型

| 热路径 | 改造前的额外负担 | 改造后的允许工作 | 明确禁止 |
| --- | --- | --- | --- |
| native QFQ check | 读取 basis、追溯历史 factor、重算 OHLC 并比对 | 同日 silver + factor + target QFQ 的文件契约、key/value、覆盖聚合 | 历史 annual basis、OHLC expected join、全历史扫描。 |
| native QFQ batch readiness | 近窗口 batch 中含 formula/basis 分支 | 同一批次内按年/频度聚合活跃四项事实，保持一次批量查询模型 | 对每个日期调用 single-date helper；逐 code Python 循环。 |
| derived QFQ check/readiness | 以完整 derived select 生成 expected OHLC | diagnostics + coverage-only identity query，比较窗口身份/目标覆盖 | `open/high/low/close` 预期重算、价格比较。 |
| MACD/KDJ production check | 每频度再计算 DIF/DEA/MACD/K/D/J 样本 | contract + source coverage 两条轻量事实检查 | 在生产 check 中执行指标公式或读取历史 state 做公式抽样。 |

### 12.2 测量门禁

实施完成后，必须在临时 fixture 上比较改造前后的非公式事实结果，并记录以下值；不需要访问正式 Lake：

1. 5 个交易日的 QFQ daily readiness batch 与 10 个交易日的 repair/M12 batch，分别记录 DuckDB 执行次数、读取文件数、扫描行数（若可取得）和 elapsed。
2. 断言 source-window / source-coverage、contract、key、value 的 passed / failed 结论与旧实现中对应的非公式规则一致。
3. 新 readiness 不得包含 formula/basis SQL 文本；derived coverage helper 的 projection 不得出现 `open`、`high`、`low`、`close`、`vol`、`amount`。
4. 没有新增 Parquet、Dagster event、dynamic partition 或外部请求。任何出现这些写入的实现均视为越界。

没有设定“允许变慢”的空间：本专项的目标是删除重复计算，因此同样 fixture 的 check/readiness 总工作量必须下降或至少不增加。若测量发现增加，停止并重新设计 coverage query，不得用缓存、旁路状态或扩大 cursor 规避问题。

## 13. 实施顺序、验证命令与停止条件

### 13.1 代码实施顺序

1. 完成第 9.3 节只读 preflight；若 sidecar 有实际文件或消费者超出本 LLD，停止。
2. 先新增 QFQ 与 MACD/KDJ 金样本，再确认它们独立证明当前算法的正例/反例；此时不改 production check。
3. 删除第 10.1 节 sidecar 模块、path/schema 和直接写入调用；同步清理 history report 字段。
4. 收敛 native QFQ check/readiness 至四项事实检查。
5. 新增 derived coverage-only helper，并收敛 derived QFQ check/readiness；先通过 source-window identity 反例，再删除完整 expected OHLC 调用。
6. 删除 MACD/KDJ formula sample production check；保留两个 indicator 与两个 state 事实 check。
7. 同步 catalog/readiness tuples、测试、静态门禁和本 LLD，执行本地验证。
8. 仅当全部本地验证通过，才可单独讨论 `dg check defs`；definitions 验证、正式 instance 只读、sensor 操作和任何写入均是后续独立审批。

### 13.2 必跑本地验证

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
uv run python -m unittest \
  tests.test_stk_mins_qfq_formula_golden_contracts \
  tests.test_stk_mins_qfq_macd_kdj_formula_golden_contracts \
  tests.test_stk_mins_qfq_m8b_checks \
  tests.test_stk_mins_lake_readiness \
  tests.test_stk_mins_qfq_m8c_history \
  tests.test_stk_mins_qfq_m8d_events \
  tests.test_stk_mins_qfq_m9c_factor_repair \
  tests.test_stk_mins_qfq_sql_helpers \
  tests.test_stk_mins_qfq_m11_derived_assets \
  tests.test_stk_mins_qfq_m11f_derived_history \
  tests.test_stk_mins_qfq_macd_kdj_check_contracts \
  tests.test_stk_mins_qfq_m12_macd_kdj \
  tests.test_stk_mins_qfq_m9a_sensor_contracts \
  tests.test_stk_mins_qfq_m9c_sensor_contracts \
  tests.test_stk_mins_qfq_m12_sensor_contracts \
  tests.test_stk_mins_continuity_performance \
  tests.test_batch_readiness_hotpath_performance \
  tests.test_run_contract_static_gates
git diff --check
python3 scripts/check_docs_integrity.py
```

`tests.test_asset_check_incremental_governance` 是全仓共享 catalog 门禁，必须单独执行并记录结果；它不应被为本专项而改写或跳过。若它因无关资产的未提交 catalog 变更失败，必须隔离记录，待对应资产专项补全治理映射后再恢复全仓绿色。

如某个现有 sensor contract test 位于不同命名文件，实施时可补入同一命令，但不得因为命名差异跳过 QFQ daily / factor repair 的契约回归。

### 13.3 阻断条件

以下任一情况出现，必须停在代码审计/本地测试阶段，不得以临时 fallback 推进：

1. sidecar 路径存在真实 Lake 文件，或任何正式代码/状态消费者未列入本 LLD。
2. 无法用固定 fixture 和字面量 expected 值覆盖已有 daily、repair、derived、indicator/state 核心算法。
3. 删除 formula check 后，无法用 contract/key/value/coverage 解释当前生产失败；这说明缺少的是真实事实 check，不是恢复公式 check。
4. derived source-window identity 无法在不投影价格字段的前提下确定；必须先重构 source-window 事实 helper。
5. batch readiness 退化成逐日期、逐代码、全历史或包含 QFQ OHLC 计算。
6. 需要改 job selection、run key、sensor cursor、repair 范围、历史 Parquet 或 Dagster event 才能使测试通过。

## 14. 本专项完成定义

只有同时满足以下条件，才可宣告本治理代码专项完成：

1. as-of basis 的源码、CLI、path、schema、tests 和全部活跃消费者已清零；没有 Lake/bootstrap 写入动作。
2. QFQ active production checks 为 native 4 + derived 4；MACD/KDJ indicator active checks 为每频度 2，state 每频度仍为 2。
3. production check/readiness 不再计算或对比 QFQ OHLC、MACD、KDJ；derived readiness 不构造完整 expected OHLC。
4. QFQ daily/repair/M12 sensor 的名称、窗口、run key、选择顺序和公开 readiness API 都保持原语义；窗口事实明确为 daily 5、repair/M12 10。
5. 两组受保护金样本通过，且本专项范围内的运行事实、批量性能、catalog、readiness、static-gate 测试通过。全仓共享治理测试若受无关未提交专项阻塞，必须在第 15 节逐项记录，不能伪称全仓绿色。
6. 本文与实际代码、check 集合和验证命令同步；没有把未来正式实例验证误记为已完成。

## 15. 2026-07-15 实施结果

### 15.1 只读 preflight 与边界

1. 已只读确认以下两个可能的 sidecar 目录均不存在：
   - `/Volumes/datasource/data_lake/gold/quote/stk_mins_qfq_as_of_basis`
   - `/Volumes/datasource/data_lake/gold/stk_mins_qfq_as_of_basis`
2. 未发现计划外的 sidecar 消费者。删除范围包括 sidecar 模块、history/bootstrap CLI、path helper、schema、生产写入调用和专属测试；没有保留兼容入口。
3. 本次未执行 Lake、Dagster instance、prod DB、dynamic partition 写入；未运行 job、sensor、materialize、backfill、bootstrap 或 runless event。
4. 工作区中的 `dc_board` 文件全部保持隔离，未修改、未暂存、未借本专项修复其问题。

### 15.2 已落地的代码事实

1. QFQ native active checks 为 `5 x 4 = 20`，derived 为 `2 x 4 = 8`；MACD/KDJ indicator 为 `7 x 2 = 14`，state 仍为 `7 x 2 = 14`。
2. daily、factor repair、derived asset 的实际计算 SQL、Parquet 布局、分区、run key、job selection 和 sensor 选择顺序未改变。daily 仍按 5 个交易日窗口，factor repair 与 M12 仍按 10 个交易日窗口。
3. production check/readiness 已不再读取 sidecar、不再重算 QFQ OHLC 或 MACD/KDJ，也不再调用完整 derived QFQ select。derived 覆盖查询只投影 `ts_code`、`trade_date`、`trade_time`、`freq`、`exchange` 等窗口身份字段。
4. 新增两组受保护的本地金样本。expected 值均为人工确认的字面量；fixture 不读取正式 Lake 或 Dagster instance，也不通过被测 helper/writer/完整 SQL 反推 expected。
5. baseline/history 辅助工具已从 formula audit 收敛到 active check 的身份与覆盖审计；没有生成、删除或修改任何历史 event。

### 15.3 本地验证结果

以下 QFQ/MACD-KDJ 精确范围验证于 2026-07-15 通过：

```text
python3 -m py_compile <QFQ/MACD-KDJ 10 个生产模块和 2 个 golden 测试模块>
uv run python -m unittest <第 13.2 节所列 18 个 QFQ/MACD-KDJ 测试模块>
Ran 237 tests in 11.141s
OK
git diff --check
python3 scripts/check_docs_integrity.py
```

静态扫描确认生产源没有 `as_of_basis`、retired formula check 或 formula sample helper 残留；命中仅存在于静态门禁自身的禁止词断言。`expected_identity_sql` 已在 derived check/readiness/bootstrap 内明确命名，避免把不含价格字段的身份覆盖 SQL 误解为完整 expected select。

`tests.test_asset_check_incremental_governance` 已单独执行但当前未绿：它检测到 `dc_board` 未提交 catalog 中的 7 个 blocking-check asset 没有治理映射，分别为 `raw_tushare_dc_daily`、`raw_tushare_dc_index`、`raw_tushare_dc_member`、`silver_dc_member`、`silver_dc_daily`、`silver_dc_index`、`gold_stock_daily_qfq`。该集合不含本专项的 QFQ/MACD-KDJ asset；本专项仅更新自身 check 清单，未修改 `dc_board` 或共享治理映射。此项应由 `dc_board` 专项处理后再恢复全仓绿色。

未运行 `dg check defs`。此外，一次仓库级 `compileall` 仅因同一批未提交 `dc_board` 文件存在两个既有 f-string 语法错误而失败；QFQ/MACD-KDJ 精确范围 `py_compile` 已通过。
