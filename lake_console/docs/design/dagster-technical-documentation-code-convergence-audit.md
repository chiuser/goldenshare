# Dagster 技术文档与代码现状待收敛审计

更新时间：2026-07-15

状态：**C-01 至 C-11 已于 2026-07-15 完成文档收敛。** 本文保留初始审计快照与问题证据；不能替代各 successor 文档中的现行实施口径。

## 1. 审计范围与边界

本次审计的目的，是找出 Dagster 技术开发文档中仍会把人带到错误代码入口、错误调度链路或错误 check 口径的表述。它不是重写历史，也不要求把历史证据从文档中抹掉。

初始 P0 审计快照固定为当时仓库 `HEAD`：`90b48ab2`。C-08 在 `aebbca63` 合入 `dc_daily_technical` catalog 后重新核验，因此不再沿用本节的资产总数作为现行总数。

纳入范围：

1. `lake_console/docs/architecture/` 下 2 份 Dagster 文档。
2. `lake_console/docs/design/` 下 72 份 Dagster 技术设计、LLD、治理、迁移和审计文档。
3. `lake_console/docs/templates/` 下 3 份 Dagster 模板文档。
4. 共 77 份文档；代码对照范围是稳定 `HEAD` 中 `lake_console/orchestrator/src/orchestrator/defs/**`。

明确排除：当前工作区未提交的 `dc_daily_technical` repair 专项代码与两份设计文档。它们不改变本次已合入的 catalog/schema 基线，也不混入本次文档收敛结论。

本次没有运行 Dagster job、sensor、materialize、backfill 或 `dg check defs`；没有读取或写入正式 Dagster instance、Lake 或生产数据库。

## 2. 代码事实基线

初始 P0 审计时稳定 `HEAD` 的静态定义盘点结果（历史快照，不是当前总数）：

| 定义类别 | 数量 |
| --- | ---: |
| asset | 53 |
| asset check | 98 |
| job | 42 |
| sensor（含 `@run_status_sensor`） | 44 |

审计时先用 CodeGraph 覆盖了指数日线、QFQ/MACD-KDJ repair 与 run-status sensor 的真实调用链；随后以源码作逐项核验。特别注意：仅扫描 `@dg.sensor` 会漏掉 `@dg.run_status_sensor`，因此不能用简单文本或不完整 AST 结果判断某个 sensor 已删除。

当前几个容易被旧文档混淆的正式事实是：

| 主题 | 当前代码事实 |
| --- | --- |
| 指数日线 raw | `raw_index_daily[trade_date]` 位于 `assets/index_daily.py`，从 prod `core_serving.index_daily_serving` 读取并写入 by-date Parquet。 |
| 指数日线触发 | `raw_index_daily_update_job_sensor` 触发 `raw_index_daily_update_job`；`silver_index_daily_sensor` 读取同日 `raw_index_daily` by-date readiness。旧 `index_daily_sensor.py` 不存在。 |
| QFQ/MACD-KDJ production check | QFQ native 4 条、derived 4 条；MACD/KDJ indicator 每频度 2 条。公式正确性由受保护金样本测试承担，production check 不再执行公式重算。 |
| 市场宽度 / ClickHouse 触发 | 已使用 `market_breadth_continuity_sensor`、`stock_return_distribution_continuity_sensor`、`clickhouse_market_breadth_continuity_sensor`、`prod_clickhouse_market_breadth_continuity_sensor`；旧 automation sensor 文件已退出。 |
| 九转分区 | Raw/Silver 使用 `cn_a_stk_nineturn_trade_days`，历史起点由 `STK_NINETURN_HISTORY_START_DATE = "2023-01-03"` 集中定义。 |

## 3. 判定规则

文档中的旧名称不自动等于错误。按下列规则处理：

1. **现行规范、现行拓扑、现行注册表、当前代码事实**：必须与当前源码一致；错误入口属于 P0。
2. **已完成迁移的执行记录**：允许保留旧名称、数量、路径和 run id，但标题或开头必须清楚说明“历史记录”，并给出当前权威文档链接；缺失标记属于 P1。
3. **未来方案/待开发 LLD**：允许与当前代码不同，但必须显式写“待开发”，不能把目标方案称为当前实现。
4. **模板**：只约束方法和质量门禁，不要求示例资产名一定存在于当前 definitions。

因此，本清单不建议全仓替换 `raw_tushare_index_daily_by_code` 等字符串。它在指数迁移 LLD 的 P0/P3/P7 历史证据中仍有价值；真正要消除的是“它仍为当前 active source”的误导。

## 4. 待收敛事项

### C-01 [P0，已收敛 2026-07-15] 资产与 Job 拓扑仍把旧指数链路和旧 automation 当作当前入口

涉及文档：

- `lake_console/docs/architecture/dagster-asset-job-topology.html`

文档问题：

1. 当前说明、资产表、job 表和收口状态仍写 `index_daily_sensor`、`index_daily_update_job`、`raw_tushare_index_daily_by_code`、raw-by-code 文件门禁与 per-code run key。
2. 同一份“当前”拓扑仍列出 `market_breadth_automation_sensor`、`stock_return_distribution_automation_sensor`、`clickhouse_share_fact_market_breadth_automation_sensor`、`prod_clickhouse_share_fact_market_breadth_automation_sensor`。
3. 文档同时又列出新 raw/silver 日线名称，造成一份页面内存在两套互斥的“当前入口”。

源码依据：

- `defs/assets/index_daily.py` 只注册 `raw_index_daily` 和 `silver_index_daily`。
- `defs/jobs/index_daily_update.py` 只定义 `raw_index_daily_update_job`。
- `defs/sensors/raw_index_daily_update_job_sensor.py` 是 prod-core-db -> raw by-date 的正式 raw sensor。
- `defs/sensors/clickhouse_market_breadth_continuity_sensor.py` 定义本机和 prod 两个 ClickHouse continuity sensor；市场宽度和收益分布也使用对应 continuity sensor。

收敛动作：把拓扑中的“当前指数日线”和“当前派生/serving 触发”整段改为正式现行链路；旧 by-code 与旧 automation 只在一个明确的“已退出历史入口”小节保留，并链接到指数迁移 LLD/P7-P9 与非分钟线连续性治理方案。

实际收敛结果：已更新 `dagster-asset-job-topology.html` 的 current asset/job/sensor 表、指数流程和门禁说明。现行锚点是 `defs/assets/index_daily.py`、`defs/jobs/index_daily_update.py`、`defs/sensors/raw_index_daily_update_job_sensor.py`，以及四个 continuity sensor；旧 by-code/automation 名称只保留在明确的历史退出说明中。已做静态名称与链路复核。

### C-02 [P0，已收敛 2026-07-15] Silver/Raw readiness 注册表仍把 by-code 文件事实作为指数日线当前门禁

涉及文档：

- `lake_console/docs/design/dagster-silver-raw-readiness-registry.html`

文档问题：第 5.5 节仍绘制 `raw_tushare_index_daily_by_code -> silver_index_daily`，并把 `audit_index_daily_raw_gaps`、`check_index_daily_raw_files_for_trade_date` 描述为当前正式门禁。

源码依据：

- `defs/sensors/index_daily_raw_file_readiness.py` 的正式常量是 `raw_index_daily_file_contract_check`、`raw_index_daily_code_coverage_check`。
- `defs/sensors/silver_index_daily_sensor.py` 只调用 `raw_index_daily_lake_readiness_for_trade_dates(...)`，并明确以 `raw_index_daily` by-date 为阻断组件。

收敛动作：替换指数日线的 flow、readiness 名称、阻断说明和验证文件；保留“文件事实优先、避免 Dagster event 深扫”的性能原则，不回退为旧 by-code 描述。

实际收敛结果：已更新 `dagster-silver-raw-readiness-registry.html` 第 5.5 节为 prod core serving -> `raw_index_daily[trade_date]` -> 同日 `silver_index_daily[trade_date]`。raw gate 固定为文件契约和 code coverage 两条；silver coverage 明确对齐同日 raw 文件 code set。锚点是 `defs/sensors/index_daily_raw_file_readiness.py` 与 `defs/sensors/silver_index_daily_sensor.py`。

### C-03 [P0，已收敛 2026-07-15] Run contract 治理文档仍定义已删除的指数 run config 和 automation sensor

涉及文档：

- `lake_console/docs/design/dagster-run-contract-governance.html`

文档问题：M2/M3/M4 完成结论仍以 `index_daily_sensor`、`raw_tushare_index_daily_by_code`、`IndexDailyRawByCodeConfig` 为“当前”契约，也仍列出已退出的 market breadth / ClickHouse automation sensor。

源码依据：

- `defs/run_contracts/configs.py::build_raw_index_daily_update_job_run_config(...)` 目标 op 为 `raw_index_daily`。
- `defs/sensors/index_daily_sensor.py` 和三份旧 automation sensor 文件均不存在。

收敛动作：指数章节改为 date-level raw job 的 `trade_date/write_mode` 契约；automation 章节改为 continuity sensor，不再描述已删除文件。历史 run tags/config 的治理结论可以保留，但须标注为 by-code 退出前的历史背景。

实际收敛结果：已更新 `dagster-run-contract-governance.html` 为 partition-key trade date 加 `write_mode` 的现行边界，明确 `build_raw_index_daily_update_job_run_config(...)` 与 `raw_index_daily` op 层级。原 M2/M3 raw-by-code 内容已加历史执行记录标识；ClickHouse/market breadth 章节改为 continuity sensor。锚点是 `defs/run_contracts/configs.py` 与现行 sensor 文件。

### C-04 [P0，已收敛 2026-07-15] 历史 event retention 文档的“当前 active by-code”前提已失效

涉及文档：

- `lake_console/docs/design/dagster-event-history-retention-governance-plan.md`

文档问题：第 3.3 节明确称 `raw_tushare_index_daily_by_code` “仍是 active definition”，并据此把它排除在清理范围之外；后续删除顺序也仍写“先完成 by-date 迁移”。

源码与执行依据：指数迁移方案已记录 P7 active source/catalog 清理、P8 隔离和 P9B/P9C 状态治理完成；稳定代码中也不再存在 by-code asset/job/sensor。

收敛动作：将这一节改为“历史审计前提，已于 P7-P9 失效”，记录 P9B-1/P9C-1 已处理的精确范围，以及仍保留的 P8 quarantine 最终删除、P9C-2 mixed runs 决策。不得把已完成清理重新列为未来计划。

实际收敛结果：已更新 `dagster-event-history-retention-governance-plan.md`，明确 P7 active source/catalog 退出、P8 quarantine 与最终物理删除、P9B-1/P9C-1/P9C-2 精确治理均已完成。P9C-2 在删除前已导出 4 个 run、528 条 event、8 条 run tag 和 8 条 asset tag 的精确备份；post-audit 确认候选归零，且仅删除其 8 条旧 `silver_index_daily` event。旧 by-code 事件规模保留为历史证据，不再作为当前 active-definition 前提。

### C-05 [P0，已收敛 2026-07-15] 非分钟线连续性方案/LLD 仍把已删除的指数 sensor 当作 P5 现行实现

涉及文档：

- `lake_console/docs/design/dagster-non-stk-mins-continuity-governance-plan.md`
- `lake_console/docs/design/dagster-non-stk-mins-continuity-governance-low-level-design.md`

文档问题：两份文档都标记 P0F-P7 已完成，却仍把 `index_daily_sensor.py`、`test_index_daily_sensor.py`、`index_daily_late_arrival_repair.py` 写入当前代码事实、文件清单和验证命令。

源码依据：上述源文件与测试均已不存在；现行指数 raw sensor 是 `raw_index_daily_update_job_sensor.py`。P5 的“注册缺口、bounded window、禁止 event-history 深扫”治理原则仍有效，但实现入口已被指数 by-date/prod-db 迁移替换。

收敛动作：P5 一节不要重写整套连续性原则；仅替换实现锚点、测试清单和静态门禁，链接到指数迁移 LLD 作为当前实施权威。

实际收敛结果：已更新两份非分钟线连续性文档的 P5 实现锚点、测试锚点和性能说明，现行入口为 `raw_index_daily_update_job_sensor.py`、`silver_index_daily_sensor.py` 与 by-date lake readiness。10 日期 bounded window、注册缺口 fail-closed、禁止 event-history 深扫仍保留；迁移前 raw-by-code profiling 已明确标为历史容量证据。

### C-06 [P1，已收敛 2026-07-15] Run key LLD 仍引用已删除的 late-arrival repair helper 与测试

涉及文档：

- `lake_console/docs/design/dagster-run-key-governance-low-level-design.md`

文档问题：该文档声明 M1-M9 已完成，但第 3 节与验证命令仍引用 `defs/sensors/index_daily_late_arrival_repair.py` 和 `tests/test_index_daily_late_arrival_repair.py`。

源码依据：两者已随 by-code index daily 链路退出而删除；现行 raw sensor 使用统一 `build_asset_update_run_key(...)` 的 date-level 请求。

收敛动作：把这部分标记为历史实现证据，新增现行 `raw_index_daily:<trade_date>` run-key 的代码锚点；删除不存在的测试命令。

实际收敛结果：已更新 `dagster-run-key-governance-low-level-design.md`。`index_daily_late_arrival_repair.py` 与对应测试仅作为 raw-by-code 退出前的历史证据；现行 raw 链路固定为 `build_asset_update_run_key(subject="raw_index_daily", unit_id=trade_date)` 加 `build_raw_index_daily_update_job_run_config(...)`。验证入口已改为现存的 `tests/test_raw_index_daily_update_job_sensor.py`。

### C-07 [P0，已收敛 2026-07-15] Asset check 治理文档仍把已退役公式 check 当作当前清单

涉及文档：

- `lake_console/docs/design/dagster-asset-check-incremental-governance-plan.md`
- `lake_console/docs/design/dagster-asset-check-incremental-governance-low-level-design.md`
- `lake_console/docs/design/dagster-stk-mins-qfq-macd-kdj-indicators-plan.md`

文档问题：上述文档仍出现“QFQ native/derived 5 条”“MACD/KDJ indicator 3 条”“`formula_sample` 当前仍存在、后续再退役”的表述。

源码依据：

- `defs/checks/stk_mins_checks.py`：QFQ native/derived 均为 `contract + key_integrity + value_domain + source_coverage` 四条。
- `defs/checks/stk_mins_qfq_macd_kdj_checks.py`：indicator 仅为 `contract + source_coverage` 两条；state 两条不变。
- `defs/sensors/readiness.py` 已使用相同的 active check tuple。

收敛动作：以 `dagster-stk-mins-qfq-validation-governance-low-level-design.md` 为唯一当前 QFQ/MACD-KDJ check 治理权威；三份旧文档删除“当前仍存在/待退役”措辞，改为“已于 2026-07-15 收敛完成”，并保留公式职责已迁往金样本测试的原因。

实际收敛结果：已更新三份治理文档为 QFQ native 4 条、derived 4 条、MACD/KDJ indicator 每频度 2 条、state 两条不变。生产 check/readiness 只验证输入、文件、覆盖和 repair 状态；公式正确性由不可从被测实现反推 expected 的受保护金样本测试承担。旧 rule 名称和事件量仅保留为历史 metadata/统计说明。

### C-08 [P1，已收敛 2026-07-15] Schema contract 文档的 raw 指数历史片段和资产总数需要重新冻结

涉及文档：

- `lake_console/docs/design/dagster-asset-schema-contract-design.md`

文档问题：文档开头已经把 `raw_index_daily` 列入当前覆盖范围，但 SC-5“已落地”段又称 `raw_tushare_index_daily_by_code` 是当前 raw schema 对象；完成定义仍固化旧的 57/58 资产数字。这会让读者无法判断哪段是当前事实。

源码依据：稳定 `HEAD` 的 index catalog 只有 `raw_index_daily`，并不存在 `raw_tushare_index_daily_by_code` catalog entry。当前工作区另有未提交 `dc_daily_technical` catalog/schema 改动，故全仓最终数量不能在本轮重新拍板。

收敛动作：

1. 将 SC-5 改成明确的历史 slice 记录，注明其对象已由 `raw_index_daily` 替代。
2. 把“当前 active catalog entry 数/表结构资产数”改为待 `dc_daily_technical` 合入后由 `test_asset_governance_contracts` 和 catalog 实例重新生成的数值，禁止继续手写旧总数。

实际收敛结果：`dc_daily_technical` 的 catalog 基线已由 `aebbca63` 合入；`dagster-asset-schema-contract-design.md` 已移除手写的 57/58 总数，改为以 `list_lake_asset_catalog_entries()` 和 `test_asset_governance_contracts` 生成的事实为准。SC-5 的 by-code 内容已标记为历史执行记录，并补入当前 `raw_index_daily` by-date 对象。未提交 repair 专项不参与本次总数判断。

### C-09 [P1，已收敛 2026-07-15] ClickHouse serving/prod sync 文档仍以已退出 automation sensor 作为未来开关

涉及文档：

- `lake_console/docs/design/dagster-clickhouse-serving-design.md`
- `lake_console/docs/design/dagster-clickhouse-prod-sync-design.md`

文档问题：两份设计仍称 `*_automation_sensor` 已定义、默认 STOPPED、等待运营决定是否长期启用；这些文件已经被 P6 删除。

源码依据：当前定义只保留 market breadth / return distribution / local ClickHouse / prod ClickHouse 的 four continuity sensors，目标选择是 bounded first-not-ready，不是 declarative automation。

收敛动作：更新触发章节与“待运营决策”：运营可决定的是 continuity sensor 的 instance 启停与观察窗口，不是已经不存在的 automation sensor。保留 ClickHouse asset、replace 语义和 tunnel 前置条件不变。

实际收敛结果：两份 ClickHouse 文档均改为四个 continuity sensor 的当前链路：市场宽度、收益分布、本机 ClickHouse 与 prod ClickHouse。现行文本描述 bounded first-not-ready 选择和实例启停观察；旧 automation 名称仅保留在明确标识的历史 slice 中。ClickHouse asset、replace 语义和 tunnel 前置条件未改动。

### C-10 [P1，已收敛 2026-07-15] Phase 1/2/3 文档没有统一的“已被后续方案替代”入口

涉及文档：

- `lake_console/docs/design/dagster-phase-1-design.html`
- `lake_console/docs/design/dagster-phase-1-low-level-design.html`
- `lake_console/docs/design/dagster-phase-2-design.html`
- `lake_console/docs/design/dagster-phase-2-low-level-design.html`
- `lake_console/docs/design/dagster-phase-3-index-daily-refactor-design.html`
- `lake_console/docs/design/dagster-phase-3-index-daily-refactor-low-level-design.html`
- `lake_console/docs/design/dagster-phase-3-major-indices-design.html`
- `lake_console/docs/design/dagster-phase-3-major-indices-low-level-design.html`

文档问题：这些文档大量使用“当前代码已实现”，特别是 Phase 3 仍完整描述 raw-by-code/per-code sensor。它们是有价值的阶段记录，但页面开头没有足够醒目的 superseded 标识，容易被当作今日开发依据。

收敛动作：不重写历史设计；所有八份文件统一增加历史状态横幅和 successor links。Phase 3 index daily 指向当前 index raw-by-date/prod-db migration plan/LLD；Phase 1/2 指向当前 topology、readiness registry、non-stk continuity 和相应数据集 LLD。

实际收敛结果：八份 Phase 1/2/3 文档均已在开头增加“文档状态与现行依据”段。它们保留阶段事实，但不再可被当作今日开发入口；Phase 3 明确指向 index raw-by-date/prod-core-db migration plan/LLD，Phase 1/2 指向 topology、readiness registry、non-stk continuity 和对应数据集 LLD。

### C-11 [P2，已收敛 2026-07-15] 旧性能/架构审计应补“观测时点”与后续结果链接

涉及文档：

- `lake_console/docs/design/dagster-asset-ui-status-performance-diagnosis.md`
- `lake_console/docs/design/dagster-new-lake-asset-performance-audit.md`
- `lake_console/docs/design/dagster-new-lake-orchestration-architecture-audit-20260604.md`

文档问题：它们保留了旧 raw-by-code 的事件规模和“待退出 active definitions”结论。作为历史审计数据本身没有错误，但缺少醒目的“采样日期/后续已完成 P7-P9”提示，容易把历史容量数据误读为当前状态。

收敛动作：只加审计时点、事实失效范围与 successor link；不修改当时的原始数字、样本或诊断结论。

实际收敛结果：三份历史性能/架构审计均已增加历史审计快照、适用时点和 successor 链接；原始数字、样本和诊断结论未改。旧 raw-by-code、公式 check 和 active-definition 结论均明确为当时观察，不再描述当前运行态。

## 5. 已核对且暂不需要修改的文档

下列文档虽包含历史术语，但其状态标记或上下文已足以避免误读，且与当前实现的关键口径一致：

1. `dagster-index-daily-raw-by-date-prod-db-migration-plan.md` 与对应 LLD：开头已记录 P7-P9 完成；旧 by-code 仅作为 P0/P3/P7 历史输入和执行证据。
2. `dagster-stk-mins-qfq-as-of-basis-low-level-design.md`：明确标为“已撤销，禁止启用”。
3. `dagster-stk-mins-qfq-validation-governance-low-level-design.md`：当前 QFQ/MACD-KDJ check 与金样本职责边界已和代码一致。
4. `dagster-stk-nineturn-dataset-onboarding-plan.md` 与对应 LLD：专属分区、迁移和 sensor 代码锚点一致。
5. `dagster-gold-wealth-market-turnover-dataset-design.md` 与对应 LLD：gold -> prod core 同 job 下游 asset 的口径、命名和写入边界一致。
6. `dagster-daily-raw-silver-human-readable-governance-low-level-design.html`：指数日线已使用新 raw by-date 入口。
7. 三份模板文档：只作为方法模板，不以示例名称断言当前 definitions 必然存在。

## 6. 收敛状态与验收

本轮已按以下三批边界完成收敛：

1. **第一批，P0 当前入口纠偏（已完成）**：C-01 至 C-05、C-07 已更新 topology、readiness registry、run contract、event retention、non-stk continuity 与 QFQ check 表述。静态复核确认“当前”入口均能在 `defs/**` 定位，退役 formula/by-code/automation 只保留为明确历史背景。
2. **第二批，P1 历史与引用收口（已完成）**：C-06、C-08、C-09、C-10。已为历史阶段补横幅/链接，更新失效的文件路径、测试命令及 ClickHouse trigger 说明。
3. **第三批，P2 审计可读性（已完成）**：C-11。已补审计时点和后续结果链接，未重写历史数据。

全量验收方法：

1. 重新跑稳定 `HEAD` 文档引用扫描；所有“当前/已完成”段落中的 asset/job/sensor/check 名称必须存在于对应源码或明确标为历史。
2. 对 C-01、C-02、C-03、C-05、C-07、C-09 的正文执行人工链路复核：入口、job、readiness/check、下游必须来自同一当前实现。
3. `git diff --check`。
4. 不以 `rg` 零命中作为验收：迁移文档、撤销记录和历史审计仍可保留旧名称；验收的是其状态标签和 successor link。
5. C-08 的当前数量不再由文档手写；以 catalog 实例与 `test_asset_governance_contracts` 的生成结果为准。当前未提交的 `dc_daily_technical` repair 专项仍保持排除，后续若变更 catalog/schema，须在其自己的专项中重新验证。

## 7. 文档治理规则（后续新增）

为避免下一次“代码已迁移，但旧方案仍像现行规范”，后续每份 Dagster 技术文档必须在开头明确一种状态：

| 状态 | 含义 | 要求 |
| --- | --- | --- |
| `现行实现` | 可直接作为开发/运维依据 | 必须同步当前代码；每次契约迁移都更新。 |
| `待开发方案` | 已拍板但尚未实现 | 不得称“当前代码已实现”；实现后更新状态或链接到完成 LLD。 |
| `已完成执行记录` | 保存操作证据 | 保留当时事实；开头写明执行日期、现行 successor。 |
| `已撤销/已替代` | 不能再作为实现依据 | 开头醒目标记撤销原因与当前权威文档。 |
| `模板` | 新数据集开发约束 | 只使用示例名称，不声称示例就是当前 active definition。 |

这条规则应在后续文档收敛完成后同步进数据集 onboarding 模板，而不是在本轮对代码做任何行为改动。
