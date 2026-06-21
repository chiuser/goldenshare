# Dagster 非股票分钟线连续性治理 LLD

更新时间：2026-06-21

依据文档：

1. [Dagster 非股票分钟线连续性治理专项方案](dagster-non-stk-mins-continuity-governance-plan.md)
2. [Dagster Bounded Continuity Selector 基础能力 LLD](dagster-bounded-continuity-selector-foundation-low-level-design.md)
3. [Dagster Market Major Indices Sensor 热路径性能治理 LLD](dagster-market-major-indices-sensor-performance-governance-low-level-design.md)

状态：P0F-P3、P5 已完成，P4 及后续阶段待按顺序执行。

范围：非股票分钟线日频历史连续资产的停机补洞能力、生命周期事实源收敛、主要指数 sensor 性能治理、派生 automation 资产显式补洞入口。本文档只设计，不执行代码开发，不运行 `dg`，不读取正式 Dagster runtime，不触碰正式 lake。

## 1. 总体硬口径

1. 历史连续资产不得以 latest registered partition 作为正式目标。
2. 目标选择必须来自 expected calendar、registered gap guard、batch/bounded readiness、first missing / first not-ready。
3. 默认窗口固定为最近 60 个 expected trade dates。
4. 已 materialized 但 blocking checks failed 的日期必须阻断后续推进，不自动重跑。
5. sensor 热路径禁止逐日调用单日 Dagster readiness wrapper 扫 event/check history。
6. 能用 lake 文件事实判断的 readiness，优先 DuckDB batch；不能用 row count 冒充完整 blocking check 语义。
7. `silver_stock_lifecycle` 是历史股票生命周期判断的唯一长期 silver 事实源。
8. current snapshot 资产不做历史逐日补洞。
9. P6 后默认 `AutomationCondition.eager()` 不作为历史补洞入口；显式 bounded sensor 是唯一 active 补洞入口。
10. run key、run config、job/sensor/asset/check 名称除明确新增 `silver_stock_lifecycle` 外均不改变。

## 2. 推荐执行顺序

阶段编号表达治理主题，不等同于编码顺序。推荐推进顺序：

```text
P0F -> P1 -> P2A -> P2B -> P2C -> P3 -> P5 -> P4 -> P6 -> P7
```

原因：

1. P0F 是所有 first-not-ready sensor 的基础。
2. P1 先修 `cn_a_stock_current_trade_days` 注册，复权因子后续依赖它。
3. P2A/P2B 先收敛生命周期事实源，否则 P2C 复权因子 readiness 会继续误判历史退市股票。
4. P5 先加固指数日线上游 guard，再做 P4 主要指数 gold，更符合依赖顺序。
5. P6 涉及退出 declarative automation active 入口，必须在基础能力稳定后单独推进。

## 2.1 开发推进详细步骤

本节是后续进入开发时的执行清单。每个阶段开工前都必须重新读取根 `AGENTS.md`、`lake_console/orchestrator/AGENTS.md`、`lake_console/orchestrator/CODING_STANDARDS.md`、本 LLD 和对应专项 LLD；涉及代码改动时必须先用 CodeGraph 审计真实调用链与影响面，不允许只按文档、文件名或历史印象猜测。

### 2.1.1 通用开工与收口流程

每个阶段都按同一条链路推进：

1. Preflight：
   - 确认 `git status --short`，只识别当前阶段相关脏文件；无关 `reports/`、历史报告或其它用户改动不整理、不提交。
   - 抽取本阶段硬口径：必须、禁止、不做、保留、默认、验收、停机条件。
   - 用 CodeGraph 或定向代码审计确认真实入口、调用方、被调用方、测试覆盖点。
   - 若发现当前代码事实与本 LLD 冲突，立即停下汇报，不靠临时兼容绕过去。

2. 测试先行：
   - 先写或调整本阶段目标测试。
   - 正向测试覆盖应支持路径，负向测试覆盖禁止项，例如 latest registered 回流、逐日 Dagster readiness 深扫、row count 冒充完整 check、current-listed-only 生命周期误用。
   - 性能敏感阶段必须先做只读 profiling 或 DuckDB prototype，确认方案可行后再改生产代码。

3. 实现：
   - 只改本阶段列出的文件与契约。
   - 不改 run key、run config、job/sensor/asset/check 名称，除非本阶段明确写入。
   - 不运行 `dg`，不读取正式 Dagster runtime，不触碰正式 lake；若阶段明确需要正式只读审计，必须单独审批。

4. 验证：
   - 运行本阶段目标 pytest。
   - 跑对应静态门禁和 `git diff --check`。
   - 对性能阶段记录只读 profiling 数据：窗口大小、读取文件数、Dagster API 调用次数、DuckDB elapsed ms、是否触发停机条件。

5. 计划对账：
   - 逐条说明本阶段硬口径落在哪些代码、测试、静态门禁和文档里。
   - 未完成项必须明确原因、风险和后续阶段，不得默认算完成。
   - 阶段提交必须只 stage 本阶段相关文件。

### 2.1.2 P0F：通用 Bounded Continuity Selector 基础

目标：先落非分钟线 sensor 共用的 bounded selector 能力，不接入任何正式 sensor，不改变运行行为。

建议改动范围：

- 新增 `lake_console/orchestrator/src/orchestrator/defs/asset_guards/bounded_continuity.py`。
- 新增或扩展 `lake_console/orchestrator/tests/test_bounded_continuity.py`。
- 扩展 `lake_console/orchestrator/tests/test_run_contract_static_gates.py`，锁住 selector 使用边界。

执行步骤：

1. 定义只读内存模型：
   - `ContinuityExpectedDateWindow`
   - `ContinuityRegisteredGapStatus`
   - `ContinuityDateReadiness`
   - `ContinuityBatchReadiness`
   - `ContinuitySelection`
2. 定义通用 helper：
   - expected calendar window 裁剪。
   - registered gap 检测。
   - first missing / first not-ready / ready frontier 选择。
   - materialized-check-problem 阻断语义。
3. 测试覆盖：
   - registered 缺口优先于 readiness。
   - 早期 not-ready 阻断后续日期。
   - materialized 但 blocking checks failed 不自动重跑。
   - all ready 返回 ready frontier。
   - 20/60 窗口输入均只看窗口内数据，不扫全历史。
4. 静态门禁：
   - 后续正式 sensor 必须使用 bounded selector，不允许恢复 latest registered 目标选择。

验收：P0F 完成后只新增基础 helper 和测试，不出现任何 sensor 行为变化。

### 2.1.3 P1：Current Trade Day Partition Catch-Up

目标：修正 current trade day partition 注册能力，停机后能按 expected calendar 补最早缺口；current snapshot 资产不做历史重算。

建议改动范围：

- `lake_console/orchestrator/src/orchestrator/defs/sensors/stock_current_trade_day_sensor.py`
- current trade day sensor 相关测试，优先补齐在现有 sensor contract 测试中。
- `lake_console/orchestrator/tests/test_run_contract_static_gates.py`

执行步骤：

1. 读取 SSE calendar，按 bounded window 生成 expected dates。
2. 对 current trade day partition set 做 registered gap 检测。
3. 每 tick 只注册最早缺口或小批量缺口，具体批量必须保持文档拍板口径。
4. 删除 today-only 决策在正式路径中的主导地位。
5. 保留 current snapshot 资产语义：它们只消费 current trade day，不做历史连续资产补洞。

测试覆盖：

- 停机漏 `06-15/06-16` 时先注册 `06-15`。
- 今日窗口前不注册当天。
- 注册 cursor 暴露 first missing 和 ready frontier。
- 不读取逐日 Dagster event/check history。

验收：P1 完成后 current trade day 注册不再因为停机直接跳到最新日期。

### 2.1.4 P2A：新增 `silver_stock_lifecycle`

目标：从 `raw_stock_basic` 派生正式银层股票生命周期事实，供复权因子、股票日线、股票分钟线生命周期 check 和 runless dry-run 统一使用。

建议改动范围：

- 新增生命周期 path/schema/select helper，建议落在现有 stock basic / stock lifecycle 相邻模块。
- 新增 `silver_stock_lifecycle` asset/check/readiness/catalog contract。
- `lake_console/orchestrator/src/orchestrator/defs/jobs/stock_basic_update.py`
- 对应 catalog、asset governance、schema contract、job selection 测试。

字段契约必须固定：

- `ts_code`
- `list_date`
- `delist_date`
- `list_status`
- `exchange`
- `market`
- `is_cny_stock`
- 必要的审计字段，例如 source path、row count、snapshot date，具体字段以当前 schema 规范落地。

执行步骤：

1. 审计当前 `raw_stock_basic` schema 与 P2 已有生命周期 SQL。
2. 抽出 `silver_stock_lifecycle_select(...)`，保持历史退市股票不被 current-listed-only 过滤掉。
3. 新增 asset，加入 stock basic update job；不要改变 `silver_stock_basic` current-listed-only 语义。
4. 新增 blocking check：
   - 生命周期区间合法。
   - `ts_code/list_date` 唯一或符合当前数据事实。
   - CNY、exchange、market 派生字段可解释。
5. 新增 readiness spec，供后续 P2B/P2C 使用。

测试覆盖：

- `000638.SZ` 这种退市股票必须出现在 lifecycle 中。
- 当前上市股票 `delist_date is null`。
- 非 CNY 或不支持市场按现有规则过滤或标记。
- stock basic update job selection 包含 lifecycle。

验收：P2A 完成后，所有下游不得再以 `raw_stock_basic` 作为长期生命周期事实源的新增正式依赖。

### 2.1.5 P2B：迁移既有生命周期消费者

目标：把当前已经直接使用 `raw_stock_basic` 生命周期的正式消费者统一迁移到 `silver_stock_lifecycle`，一次性清零旧依赖。

建议改动范围：

- `lake_console/orchestrator/src/orchestrator/defs/assets/stock_daily.py`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stock_daily_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/asset_guards/stk_mins_lake_readiness.py`
- `lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_mins_name_timeline_check_events.py`
- 相关 tests 与静态门禁。

执行步骤：

1. 审计所有 `raw_stock_basic` 生命周期直接读取点，区分：
   - 合法源头：生成 `silver_stock_lifecycle`。
   - 非法下游：应迁移到 `silver_stock_lifecycle`。
2. 迁移 `silver_stock_daily`：
   - `silver_stock_daily_select(...)` 使用 lifecycle。
   - `silver_stock_daily_stock_lifecycle_covered` 使用 lifecycle。
   - 旧 current-listed-only blocking 口径不得回流。
3. 迁移股票分钟线 lifecycle/name timeline check：
   - `silver_stk_mins_name_timeline_covered` 保持 check 名称不变。
   - 内部事实源改为 `silver_stock_lifecycle`。
4. 迁移 lake readiness batch helper：
   - silver 分钟线 batch readiness 不再读 raw stock basic snapshot。
   - ready 语义仍必须覆盖生命周期，不得降级为 row count。
5. 迁移 runless check dry-run helper：
   - 候选生命周期判断使用 `silver_stock_lifecycle`。
6. 增加静态门禁：
   - 除 lifecycle asset 生产模块外，正式代码禁止直接用 `raw_stock_basic` 做股票生命周期覆盖判断。

测试覆盖：

- 退市生命周期内通过。
- 生命周期外失败。
- 缺 lifecycle 文件 fail closed。
- `silver_stock_basic` 保持 current-listed-only，不被塞入退市历史股票。
- runless dry-run 候选数量口径不变。

验收：P2B 完成后，生命周期事实源口径从 raw snapshot 迁移为 `silver_stock_lifecycle`，且旧直接依赖清零。

### 2.1.6 P2C：复权因子 Sensor 与 Check 语义修正

目标：在 P2A/P2B 后修复复权因子完整 blocking check 语义，并把 sensor 热路径改为 DuckDB batch readiness。

建议改动范围：

- `lake_console/orchestrator/src/orchestrator/defs/assets/adj_factor.py`
- `lake_console/orchestrator/src/orchestrator/defs/checks/adj_factor_checks.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/stock_adj_factor_sensor.py`
- 复权因子 batch readiness helper，建议独立于股票分钟线 helper，避免概念混用。
- 相关 contract tests 与静态门禁。

开发前必须先做只读 profiling：

- 使用临时 Parquet 或正式 lake 只读样本验证 20/60 天 batch SQL。
- 记录 raw/silver 文件数、DuckDB elapsed ms、失败样本耗时。
- 确认完整 check 语义可用 SQL 等价表达，不允许只用 row count。

执行步骤：

1. 用 `silver_stock_lifecycle` 替换复权因子 listed/CNY/lifecycle 判断。
2. 抽取或新增 adj factor batch readiness：
   - raw 文件存在与 schema。
   - silver 文件存在与 schema。
   - 日期、唯一键、正值、覆盖率、生命周期覆盖。
3. 改造 sensor：
   - expected calendar + registered gap + batch readiness + first not-ready。
   - materialized 但 check failed 阻断，不自动重跑后续日期。
4. 保持 run key、run config、job/sensor 名称不变。

测试覆盖：

- 早期 missing registered 阻断。
- 早期 raw/silver adj factor not-ready 阻断后续日期。
- 文件存在但 check failed 不自动重跑。
- 生命周期内退市股票通过，生命周期外失败。
- sensor 不出现逐日 Dagster readiness 深扫。

验收：P2C 完成后，复权因子 sensor 性能风险解除，生命周期语义不再卡在 current-listed-only 或 raw snapshot 直读。

### 2.1.7 P3：股票日线与停复牌历史连续资产 Gap Guard

目标：为股票日线、停复牌这类历史连续日线资产增加 expected registered gap guard，防止停机后跳过空洞日期。

建议改动范围：

- `lake_console/orchestrator/src/orchestrator/defs/sensors/stock_daily_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/suspend_d_sensor.py`
- 对应 sensor contract tests 与静态门禁。

执行步骤：

1. 审计当前 sensor 目标日期选择是否仍依赖 latest registered。
2. 引入 P0F bounded selector：
   - expected calendar window。
   - registered gap 优先。
   - selected date 上保留现有上游 gate。
3. 不在 P3 中引入 batch lake readiness，除非现有代码确实存在逐日 Dagster 深扫；若发现深扫，停下并重新评估。

测试覆盖：

- `06-15` partition 缺失时不提交 `06-16`。
- `06-15` registered 但 not-ready 时只处理 `06-15`。
- 已 materialized 但 check failed 阻断。
- run key/run config 不变。

验收：P3 完成后，股票日线与停复牌不会因停机漏注册而从后续日期继续推进。

### 2.1.8 P5：指数日线 Raw/Silver Gap Guard

目标：为指数日线 raw/silver 链路补 expected registered gap guard，保持既有 late-arrival repair 与 silver selector 语义。

建议改动范围：

- `lake_console/orchestrator/src/orchestrator/defs/sensors/index_daily_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/silver_index_daily_sensor.py`
- `lake_console/orchestrator/tests/test_index_daily_sensor.py`
- `lake_console/orchestrator/tests/test_silver_index_daily_sensor.py`
- `lake_console/orchestrator/tests/test_index_daily_late_arrival_repair.py`

执行步骤：

1. 审计 raw index daily 当前 late-arrival selector，确认 repair attempt/backoff/cursor 语义不能被破坏。
2. 在 raw 入口前增加 expected registered gap guard。
3. 在 silver selector 前增加 raw/silver expected gap guard。
4. 保留 existing late-arrival repair run key、attempt、cursor 语义。

测试覆盖：

- raw 缺 `06-15` 时不推进 `06-16`。
- silver 缺 raw/silver 早期日期时不推进后续日期。
- late-arrival repair attempt 语义不变。
- 不新增逐日 Dagster check 深扫。

验收：P5 完成后，指数日线链路具备停机补洞能力，且不破坏已有 late-arrival repair。

### 2.1.9 P4：主要指数 Gold Daily Batch Selector

目标：解决主要指数日线 sensor 的 batch selector 问题，避免逐日调用 `gold_market_major_indices_daily_ready_for_trade_date(...)`。

依据文档：

- `lake_console/docs/design/dagster-market-major-indices-sensor-performance-governance-plan.md`
- `lake_console/docs/design/dagster-market-major-indices-sensor-performance-governance-low-level-design.md`

开发前必须先做只读 SQL/prototype：

- 用 DuckDB 只读样本验证主要指数 gold daily readiness SQL。
- 覆盖文件存在、schema、index code 集合、trade_date、唯一键、价格成交量、行数覆盖等正式 blocking check 语义。
- 记录 20/60 天耗时和读取文件数。

建议改动范围：

- 新增或更新主要指数 lake readiness helper。
- `lake_console/orchestrator/src/orchestrator/defs/sensors/market_major_indices_daily_sensor.py`
- 对应 sensor/readiness/static tests。

执行步骤：

1. 实现 batch readiness helper，不持久化任何新实体。
2. sensor 使用 expected calendar + registered gap + batch readiness。
3. selected date upstream gate 保持现有语义。
4. 移除逐日 Dagster readiness wrapper 在热路径中的使用。

测试覆盖：

- first missing。
- first not-ready。
- materialized but checks failed。
- all ready。
- selected upstream not ready。
- 静态门禁禁止旧逐日 wrapper 回流。

验收：P4 完成后，主要指数日线 sensor 的性能问题有独立 batch selector 支撑，不再是非分钟线专项卡点。

### 2.1.10 P6：AutomationCondition 资产退出默认 Eager，改显式 Bounded Sensor

目标：对派生日线 / serving / ClickHouse 同步类资产退出默认 `AutomationCondition.eager()` 补洞假设，改为显式 bounded sensor。

涉及资产族：

- `gold_market_breadth_daily`
- `gold_stock_return_distribution`
- `ch_share_fact_market_breadth_daily`
- `prod_ch_share_fact_market_breadth_daily`

开发前必须先做只读 readiness provider 审计：

- 审计每个资产当前依赖、blocking checks、partition set、上游资产。
- 确认哪些 ready 状态可以用 lake DuckDB batch 判断，哪些只能用 bounded Dagster latest check 查询。
- 不运行自动化 evaluator，不写 cursor，不提交 run。

建议改动范围：

- 新增显式 bounded sensor，或按资产族拆多个 sensor，最终以 P6 开发计划拍板为准。
- 移除上述资产的 `automation_condition=dg.AutomationCondition.eager()`。
- 删除或退出对应 `AutomationConditionSensorDefinition` 正式入口。
- 增加 sensor contract tests 与静态门禁。

执行步骤：

1. 为每个资产族定义 expected calendar、registered set、upstream readiness、own readiness。
2. 用 P0F selector 选择 first missing / first not-ready。
3. selected date 上提交正式 job/run request，保持 run key 统一 builder 口径。
4. 确保 old eager automation 不再作为正式补洞入口。

测试覆盖：

- 早期 gap 阻断后续日期。
- 上游不 ready 阻断。
- 自身 materialized but checks failed 阻断。
- all ready skip。
- 静态门禁禁止这些资产继续挂 `AutomationCondition.eager()`。

验收：P6 完成后，非分钟线派生资产的补洞能力由显式 bounded sensor 控制，而不是依赖 Dagster 默认 eager 行为。

### 2.1.11 P7：最终回归、文档对账与专项收口

目标：确认 P0F-P6 代码、测试、静态门禁、性能结论和文档口径一致。

执行步骤：

1. 静态审计：
   - 正式 sensor 不再按 latest registered 推进历史连续资产。
   - 性能敏感 sensor 热路径不再逐日扫 Dagster event/check history。
   - 生命周期消费者不再直接读 `raw_stock_basic` 作为下游长期事实源。
   - current snapshot 资产没有被错误扩展成历史补洞资产。
2. 目标测试：
   - bounded selector。
   - current trade day。
   - stock daily / suspend。
   - adj factor。
   - index daily。
   - major indices。
   - AutomationCondition 替代 sensor。
3. 完整本地回归：
   - 只跑本地 pytest，不运行 `dg`。
4. 文档对账：
   - 更新本 LLD、总方案、foundation selector LLD、major indices LLD。
   - 删除“待确认/待落地”中已经完成的表述。
   - 保留历史背景时必须明确“治理前事实”。

验收：P7 完成后，非分钟线 continuity 专项可以进入最终提交和后续正式只读审计讨论。

### 2.1.12 阶段合并与提交建议

推荐推进节奏：

- P0F 单独推进：它是所有后续 sensor 的基础能力。
- P1 单独推进：范围小，但会影响 current trade day 注册入口。
- P2A、P2B、P2C 分开推进：生命周期 asset、消费者迁移、复权因子性能/语义修正风险不同，必须分阶段 review。
- P3 与 P5 可以连续排期，但建议分开提交：股票日线/停复牌与指数日线是两个资产族。
- P4 单独推进：已有独立专项 LLD，且必须先做只读 SQL 性能验证。
- P6 单独推进：退出 AutomationCondition 是运行入口级调整，必须独立 review。
- P7 单独推进：只做回归、静态审计和文档收口。

任何阶段如果出现以下情况，必须停止：

- 需要运行 `dg`、正式 job/sensor/backfill/materialization/asset check 才能判断。
- 需要读取或写入正式 Dagster runtime，但没有单独审批。
- 需要改变 run key、run config、job/sensor/asset/check 名称，而本阶段未明确允许。
- DuckDB batch 方案无法覆盖完整 blocking check 语义，只能用 row count 近似。
- 发现 current snapshot 资产被误当成历史连续资产。
- 发现 `silver_stock_lifecycle` 字段契约不足以支撑下游解释性和 check 语义。

## 3. P0F Bounded Continuity Selector 基础能力

详细设计见：[Dagster Bounded Continuity Selector 基础能力 LLD](dagster-bounded-continuity-selector-foundation-low-level-design.md)。

本阶段目标文件：

```text
lake_console/orchestrator/src/orchestrator/defs/asset_guards/bounded_continuity.py
lake_console/orchestrator/tests/test_bounded_continuity.py
lake_console/orchestrator/tests/test_run_contract_static_gates.py
```

本阶段验收：

1. `ContinuityExpectedDateWindow`、`ContinuityRegisteredGapStatus`、`ContinuityDateReadiness`、`ContinuityBatchReadiness`、`ContinuitySelection` 可用。
2. selector 是纯函数，不依赖 Dagster instance 或 DuckDB。
3. expected dates loader 只读 `silver_trade_calendar`。
4. cursor details 小型稳定。
5. 静态门禁禁止新接入 sensor 回流单日 readiness wrapper。

## 4. P1 Current Trade Day 注册补洞

### 4.1 当前代码

文件：

```text
lake_console/orchestrator/src/orchestrator/defs/sensors/stock_current_trade_day_sensor.py
```

当前函数：

```text
StockCurrentTradeDayRegistrationDecision
build_stock_current_trade_day_registration_decision(...)
_cursor_payload(...)
_skip_reason(...)
stock_current_trade_day_sensor(...)
```

当前问题：

`build_stock_current_trade_day_registration_decision(...)` 只判断 today 是否 open、是否到 06:00、today 是否已注册。停机错过历史交易日后不会补注册。

### 4.2 实现目标

1. 保留 sensor 名称、tags、default status、`minimum_interval_seconds=600`、resource 依赖。
2. 使用 P0F 的 expected date loader，`same_day_register_start=06:00`。
3. 只看最近 60 个 expected trade dates。
4. 每 tick 最多注册 2 个缺失 `cn_a_stock_current_trade_days`。
5. 历史已完成交易日不受当天 06:00 窗口阻挡。

### 4.3 代码改造

建议删除 today-only 决策结构，替换为通用注册结果：

```text
StockCurrentTradeDayRegistrationDecision
build_stock_current_trade_day_registration_decision(...)
```

改为：

```text
load_expected_trade_date_window(...)
build_registered_gap_status(...)
selected_keys = first 2 missing_registered_dates
```

cursor details 增加：

```text
expected_count
registered_count
first_missing_registered_date
selected_keys
same_day_register_start
window_limit
```

### 4.4 测试

更新：

```text
lake_console/orchestrator/tests/test_adj_factor_m4_contracts.py
```

覆盖：

1. expected 有 `2026-06-15/2026-06-16`，registered 缺二者，单 tick 注册两个或按上限先注册最早两个。
2. 当天 06:00 前不注册今天。
3. 历史缺口不受今天窗口影响。
4. cursor 不再写 today-only 旧字段作为正式契约。
5. 不读取 Dagster event/check history。

## 5. P2 股票生命周期 silver 化与复权因子 first-not-ready

P2 拆为 P2A / P2B / P2C，禁止合并成一个大改。

### 5.1 P2A 新增 `silver_stock_lifecycle`

#### 5.1.1 目标

新增正式 silver 事实资产：

```text
silver_stock_lifecycle
```

它表达历史股票生命周期事实，不是 current-listed snapshot。

#### 5.1.2 目标文件

新增或更新：

```text
lake_console/orchestrator/src/orchestrator/defs/paths.py
lake_console/orchestrator/src/orchestrator/defs/duckdb_sql.py
lake_console/orchestrator/src/orchestrator/defs/run_contracts/asset_column_schemas.py
lake_console/orchestrator/src/orchestrator/defs/assets/stock_lifecycle.py
lake_console/orchestrator/src/orchestrator/defs/checks/stock_lifecycle_checks.py
lake_console/orchestrator/src/orchestrator/defs/jobs/stock_basic_update.py
lake_console/orchestrator/src/orchestrator/defs/sensors/readiness.py
lake_console/orchestrator/src/orchestrator/defs/catalog/lake_assets.py
lake_console/orchestrator/tests/test_stock_lifecycle_contracts.py
lake_console/orchestrator/tests/test_run_contract_static_gates.py
```

说明：

1. `definitions.py` 使用 `load_from_defs_folder(...)`，新增 defs 文件会被加载；实现阶段仍必须用本地静态测试确认 definition 可发现。
2. 使用独立 `assets/stock_lifecycle.py`，避免继续扩大 `stock_basic.py` 的 current snapshot 语义。

#### 5.1.3 Path

新增：

```python
def silver_stock_lifecycle_path(root: Path) -> Path:
    ...
```

建议物理路径：

```text
silver/basic/stock_lifecycle.parquet
```

不得复用 `silver_stock_basic_path(...)`。

#### 5.1.4 字段契约

新增：

```python
SILVER_STOCK_LIFECYCLE_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "..."),
    ColumnContract("symbol", "VARCHAR", "..."),
    ColumnContract("name", "VARCHAR", "..."),
    ColumnContract("exchange", "VARCHAR", "..."),
    ColumnContract("market", "VARCHAR", "..."),
    ColumnContract("curr_type", "VARCHAR", "..."),
    ColumnContract("is_cny_stock", "BOOLEAN", "..."),
    ColumnContract("list_status", "VARCHAR", "..."),
    ColumnContract("list_date", "DATE", "..."),
    ColumnContract("delist_date", "DATE", "..."),
)
```

最低必须包含：

```text
ts_code
list_date
delist_date
list_status
exchange
market
is_cny_stock
```

字段规则：

1. `list_date` 必须非空。
2. `delist_date` 可空。
3. `is_cny_stock` 来自 `curr_type='CNY'` 的派生布尔值。
4. `list_status` 保留源状态，例如 `L/D/P/G`，不得只保留当前上市。
5. 保留 `exchange/market`，方便下游 check metadata 可解释。

#### 5.1.5 SQL

新增：

```python
def silver_stock_lifecycle_select(raw_stock_basic_path: Path) -> str:
    ...
```

规则：

1. 输入只读 `raw_tushare_stock_basic`。
2. 不过滤成 current-listed-only。
3. 保留 CNY 股票。
4. `list_date/delist_date` 标准化为 `DATE`。
5. 对明显非法 lifecycle 日期 fail closed，由 check 报错，不静默吞掉。

`historical_cny_stock_lifecycle_select(...)` 后续只允许作为 `silver_stock_lifecycle_select(...)` 的内部辅助或测试辅助，不再给下游长期直接消费。

#### 5.1.6 Asset

新增 `@dg.asset(name="silver_stock_lifecycle", deps=["raw_tushare_stock_basic"])`。

metadata：

```text
dataset_id="stock_lifecycle"
source_system=DERIVED
data_contract="historical_cny_stock_lifecycle"
column_schema=SILVER_STOCK_LIFECYCLE_SCHEMA
path_template=silver_stock_lifecycle_path(...)
```

materialization metadata：

```text
uri
row_count
observed_columns
source_row_count
cny_stock_count
list_status_distribution
```

#### 5.1.7 Job

更新 `jobs/stock_basic_update.py`：

1. `silver_stock_basic_update_job` 是否扩展 selection 到 `silver_stock_lifecycle`，需要在 P2A 实现计划中明确。
2. 推荐：保留 job 名称 `silver_stock_basic_update_job`，selection 包含 `silver_stock_basic | silver_stock_lifecycle | checks_for_assets(...)`，因为两个 silver fact 都从同一个 raw stock basic 快照派生，且都是基础股票事实。
3. 不新增单独 sensor；沿用现有 stock basic silver 更新节奏。

#### 5.1.8 Checks

新增 blocking checks：

```text
silver_stock_lifecycle_file_exists_check
silver_stock_lifecycle_required_columns_and_types_check
silver_stock_lifecycle_unique_ts_code_check
silver_stock_lifecycle_required_fields_non_null_check
silver_stock_lifecycle_dates_valid_check
silver_stock_lifecycle_cny_stock_universe_check
```

命名若与现有 check 风格冲突，以 `CODING_STANDARDS.md` 新增 check 命名规则为准；不得改名已有 check。

#### 5.1.9 Readiness

在 `sensors/readiness.py` 增加：

```python
silver_stock_lifecycle_ready(...)
silver_stock_lifecycle_ready_without_freshness(...)
```

或用现有 dataset readiness 构造方式注册 specs。

用途：

1. P2B/P2C selected-date gates。
2. 后续 lifecycle consumers check additional_deps。

#### 5.1.10 Catalog

更新 `LAKE_ASSET_CATALOG`：

1. 新增 `silver_stock_lifecycle` entry。
2. 登记 path template、column schema、blocking checks、write policy、event policy、performance contract。
3. 不把它登记成 trade_date partitioned asset。

### 5.2 P2B 迁移 lifecycle consumers

P2B 必须一次性清零既有长期消费者，不能只修复权因子。

#### 5.2.1 迁移清单

| 当前消费者 | 当前口径 | 目标口径 |
| --- | --- | --- |
| `assets/stock_daily.py::silver_stock_daily_select(...)` | 直接读 `raw_stock_basic` 生命周期。 | 读 `silver_stock_lifecycle`。 |
| `checks/stock_daily_checks.py` lifecycle checks | 多处直接 `historical_cny_stock_lifecycle_select(raw_stock_basic_path)`。 | 读 `silver_stock_lifecycle_path`，additional_deps 改为 `silver_stock_lifecycle`。 |
| `checks/stk_mins_checks.py::silver_stk_mins_name_timeline_covered` | 直接读 raw lifecycle。 | 读 `silver_stock_lifecycle`。 |
| `asset_guards/stk_mins_lake_readiness.py` | 直接读 raw lifecycle。 | 读 `silver_stock_lifecycle`。 |
| `bootstrap/stk_mins_name_timeline_check_events.py` | dry-run helper 直接读 raw lifecycle。 | 读 `silver_stock_lifecycle`。 |

#### 5.2.2 保留项

以下直接使用 `raw_stock_basic_path` 不属于本迁移清零目标：

1. `raw_tushare_stock_basic` 自身 checks。
2. `silver_stock_lifecycle` 的生产 SQL / checks。
3. 测试 fixture 或负向样本。
4. `silver_stock_basic` current-listed snapshot 生产逻辑。

#### 5.2.3 静态门禁

新增门禁：

1. 生产路径中禁止下游长期消费者直接调用 `historical_cny_stock_lifecycle_select(raw_stock_basic_path)`。
2. allowlist 只允许 `duckdb_sql.py`、`assets/stock_lifecycle.py`、`checks/stock_lifecycle_checks.py`、测试。
3. `silver_stock_basic` 不得被改成包含退市历史股票。

### 5.3 P2C 复权因子 first-not-ready

#### 5.3.1 当前代码

文件：

```text
sensors/stock_adj_factor_sensor.py
assets/adj_factor.py
checks/adj_factor_checks.py
```

实现事实：

1. `stock_adj_factor_sensor.py` 已移除 `_latest_registered_trade_date(...)` 正式口径，raw/silver 均使用 P0F bounded expected window、registered gap guard 和 first not-ready。
2. `silver_adj_factor` asset/check 已依赖 `silver_stock_lifecycle`，不再用 current-listed-only `silver_stock_basic` 判断历史股票全集。
3. 单日 Dagster readiness wrapper 已通过 profiling 证明不可进入窗口循环，P2C 正式 sensor 已改为 DuckDB batch lake readiness。
4. P2C 开发前只读 prototype 已验证迁移后完整语义：20 日约 10.119ms，60 日约 13.323ms；`000638.SZ` 在退市日 `2026-04-13` lifecycle 通过、current-listed 失败，退市后日期失败。

#### 5.3.2 Asset / check 语义修正

`assets/adj_factor.py`：

1. `silver_adj_factor` deps 从 `silver_stock_basic` 改为 `silver_stock_lifecycle`。
2. `silver_adj_factor_select(...)` 改为使用 `silver_stock_lifecycle_path(...)`。
3. `current_listed_stock_count` metadata 改名为历史生命周期语义字段，例如 `lifecycle_stock_count`。

`checks/adj_factor_checks.py`：

1. `silver_adj_factor_listed_stock_only` 使用 `silver_stock_lifecycle`。
2. `silver_adj_factor_coverage_complete` 使用 `silver_stock_lifecycle`。
3. 退市股票在 `trade_date <= delist_date` 时必须合法。
4. `trade_date > delist_date` 或无 lifecycle 记录必须失败。

#### 5.3.3 Sensor 改造

`stock_adj_factor_sensor.py`：

1. 删除 `_latest_registered_trade_date(...)` 正式口径。
2. 使用 P0F expected window + registered gap guard。
3. raw sensor：
   - batch 判断 raw adj factor materialized/checks。
   - 选择 first missing raw。
4. silver sensor：
   - batch 判断 silver adj factor materialized/checks。
   - selected date 上检查 raw ready、`stock_basic_ready_without_freshness`、`silver_stock_lifecycle` ready。
5. run key 不变：
   - `raw_adj_factor_update:{trade_date}`
   - `silver_adj_factor_update:{trade_date}`

#### 5.3.4 Readiness provider

已新增：

```text
asset_guards/adj_factor_lake_readiness.py
```

要求：

1. 60 日窗口一次性判断 raw/silver readiness。
2. 不调用 `raw_tushare_adj_factor_ready_for_trade_date(...)` 或 `adj_factor_ready_for_trade_date(...)`。
3. 完整覆盖正式 blocking check 语义。
4. 复用 `silver_stock_lifecycle` 做历史股票全集 / listed 判断。

#### 5.3.5 P2C 验收结果

已落地文件：

```text
asset_guards/adj_factor_lake_readiness.py
sensors/stock_adj_factor_sensor.py
sensors/stock_mins_qfq_daily_sensor.py
assets/adj_factor.py
checks/adj_factor_checks.py
bootstrap/adj_factor_silver_history.py
duckdb_sql.py
```

验收口径：

1. `raw_adj_factor_update_job_sensor` / `silver_adj_factor_update_job_sensor` 不再使用 latest registered target。
2. 60 日窗口内不调用 `raw_tushare_adj_factor_ready_for_trade_date(...)`、`adj_factor_ready_for_trade_date(...)` 或 `asset_readiness_status(...)`。
3. `silver_adj_factor_select(...)`、`silver_adj_factor_listed_stock_only`、`silver_adj_factor_coverage_complete`、`adj_factor_lake_readiness.py` 与 `adj_factor_silver_history.py` 均使用 `silver_stock_lifecycle`。
4. `silver_adj_factor` deps 已从 `silver_stock_basic` 迁到 `silver_stock_lifecycle`；metadata 字段使用 `lifecycle_stock_count` / `stock_lifecycle_file_path`。
5. `stk_mins_lake_readiness.py` 不再承载复权因子 batch helper，避免股票分钟线 helper 混入非分钟线复权因子语义。

## 6. P3 股票日线与停复牌 registered gap guard

状态：已完成。

### 6.1 目标文件

```text
sensors/stock_daily_sensor.py
sensors/suspend_d_sensor.py
tests/test_stock_daily_sensor.py
tests/test_suspend_d_sensor.py
tests/test_run_contract_static_gates.py
```

### 6.2 实现目标

1. 在现有 `_eligible_registered_trade_dates(...)` 后增加 expected registered gap guard。
2. 存在更早 expected date 未注册时 skip。
3. 不改变现有 registered 内 pending selection。
4. 不扩大 selected-date readiness。
5. 保留每 tick 最多 2 个 run。
6. 保留 stock daily raw missing-code repair 逻辑，不扩大到全历史。

### 6.2.1 已落地代码事实

1. `stock_daily_sensor.py` 与 `suspend_d_sensor.py` 均通过 `load_expected_trade_date_window(...)` 读取最近 60 个 expected stock trade dates。
2. 两个 sensor 均使用 `STOCK_TRADE_DAY_MIN_DATE` 和 `STOCK_TRADE_DAY_REGISTER_START`，保持与 `cn_a_stock_trade_days` 注册窗口一致，避免 17:00 前把当天误判为注册缺口。
3. 两个 sensor 均在读取 materialized partition set、selected-date readiness、Tushare source readiness 或 repair locator 之前检查 `build_registered_gap_status(...)`。
4. 注册缺口存在时，sensor 只返回 `SkipReason` 和小型 `continuity_status` cursor，不提交后续日期 run。
5. 注册连续时，原有 raw/silver pending selection、每 tick 最多 2 个 run、stock daily missing-code repair 和 run key/run config 均保持不变。

### 6.3 测试

覆盖：

1. expected 有 `2026-06-15/2026-06-16`，registered 缺 `2026-06-15`，raw/silver stock daily 不提交 `2026-06-16`。
2. suspend raw/silver 同样不提交后续日期。
3. registered 连续后，现有 pending selection 行为不变。
4. selected-date `stock_basic`、`suspend`、raw readiness 仍只对目标日期调用。
5. 静态门禁要求两个 sensor 保留 `load_expected_trade_date_window`、`build_registered_gap_status`、`build_continuity_cursor_details`、`STOCK_TRADE_DAY_REGISTER_START` 和 `DEFAULT_CONTINUITY_WINDOW_LIMIT`。

本地验证：

```bash
cd lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_stock_daily_sensor.py \
  tests/test_suspend_d_sensor.py \
  tests/test_run_contract_static_gates.py
```

结果：`57 passed`。

## 7. P5 指数日线 guard 加固

状态：已完成。

### 7.1 目标文件

```text
sensors/index_daily_sensor.py
sensors/silver_index_daily_sensor.py
tests/test_index_daily_sensor.py
tests/test_silver_index_daily_sensor.py
tests/test_run_contract_static_gates.py
```

### 7.2 实现目标

1. raw / silver 两个 sensor 增加 expected registered gap guard。
2. 保留 `audit_index_daily_raw_gaps(...)`。
3. 保留 `select_first_not_ready_silver_index_daily_partition(...)`。
4. 不把 `silver_index_daily_ready_for_trade_date(...)` 放入窗口循环。
5. 不改 raw-by-code repair、cursor offset、run key。

### 7.2.1 已落地代码事实

1. `index_daily_sensor.py` 与 `silver_index_daily_sensor.py` 均通过 `load_expected_trade_date_window(...)` 读取最近 60 个 expected index trade dates。
2. 两个 sensor 均使用 `INDEX_TRADE_DAY_MIN_DATE` 和 `SAME_DAY_PARTITION_REGISTER_START`，保持与 `index_trade_day_sensor` 注册口径一致。
3. 注册缺口存在时，raw sensor 在 `audit_index_daily_raw_gaps(...)`、target presence scan、Tushare source readiness 和 late-arrival repair 之前 skip。
4. 注册缺口存在时，silver sensor 在 `audit_index_daily_raw_gaps(...)`、`select_first_not_ready_silver_index_daily_partition(...)` 和 target raw presence scan 之前 skip。
5. 注册连续时，raw gap audit、latest raw target presence、late-arrival repair attempt/backoff/cursor offset、silver first-not-ready selector 和 run key/run config 均保持原语义。

### 7.3 测试

覆盖：

1. `cn_a_index_trade_days` 注册缺口存在时，raw/silver index daily skip。
2. 注册连续后，raw gap audit 行为不变。
3. silver first-not-ready 仍使用 bounded selector。
4. 静态门禁防止单日 wrapper 回流。
5. 静态门禁要求两个 sensor 保留 `load_expected_trade_date_window`、`build_registered_gap_status`、`build_continuity_cursor_details`、`SAME_DAY_PARTITION_REGISTER_START` 和 `DEFAULT_CONTINUITY_WINDOW_LIMIT`，并禁止 `_latest_registered_trade_date` / `_eligible_registered_trade_dates` 回流。

本地验证：

```bash
cd lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_index_daily_sensor.py \
  tests/test_silver_index_daily_sensor.py \
  tests/test_index_daily_late_arrival_repair.py \
  tests/test_run_contract_static_gates.py
```

结果：`55 passed`。

## 8. P4 主要指数日线 gold

详细设计见：[Dagster Market Major Indices Sensor 热路径性能治理 LLD](dagster-market-major-indices-sensor-performance-governance-low-level-design.md)。

本总 LLD 只固定接入边界：

1. P4 在 P5 后推进更稳。
2. P4 必须复用 P0F 的通用 selector 数据结构。
3. P4 不得调用旧 Dagster readiness wrapper。
4. P4 不得新增持久化状态实体。
5. P4 的 `checks_passed` 表示 lake-derived blocking check 等价语义，不表示历史 check event 已 passed。

## 9. P6 派生 / Serving 显式 Bounded Sensor

### 9.1 当前代码

当前仍存在：

```text
assets/market_breadth.py::MARKET_BREADTH_AUTOMATION_CONDITION
assets/stock_return_distribution.py::STOCK_RETURN_DISTRIBUTION_AUTOMATION_CONDITION
assets/clickhouse_serving.py::CLICKHOUSE_MARKET_BREADTH_AUTOMATION_CONDITION
assets/clickhouse_serving.py::PROD_CLICKHOUSE_MARKET_BREADTH_AUTOMATION_CONDITION
sensors/market_breadth_automation_sensor.py
sensors/stock_return_distribution_automation_sensor.py
sensors/clickhouse_share_fact_market_breadth_automation_sensor.py
sensors/prod_clickhouse_share_fact_market_breadth_automation_sensor.py
```

### 9.2 新增显式 sensor

建议新增：

```text
sensors/market_breadth_continuity_sensor.py
sensors/stock_return_distribution_continuity_sensor.py
sensors/clickhouse_market_breadth_continuity_sensor.py
```

也可以在 P6 设计评审时决定是否合并为一个文件；但 active sensor definition 必须职责清晰、tags 完整、cursor 小型。

### 9.3 资产目标

| 资产 | 上游门禁 | 目标 |
| --- | --- | --- |
| `gold_market_breadth_daily` | selected-date `silver_stock_daily` ready。 | first missing / first-not-ready gold breadth。 |
| `gold_stock_return_distribution` | selected-date `silver_stock_daily` ready。 | first missing / first-not-ready gold distribution。 |
| `ch_share_fact_market_breadth_daily` | selected-date 两个 gold 派生资产 ready。 | first missing / first-not-ready local ClickHouse serving。 |
| `prod_ch_share_fact_market_breadth_daily` | selected-date local ClickHouse serving ready。 | first missing / first-not-ready prod ClickHouse serving。 |

### 9.4 Automation 退出

P6 显式 sensor 成为正式入口时，必须同步：

1. 移除四个 asset 上的 `automation_condition=...`。
2. 删除或退出四个 `AutomationConditionSensorDefinition`。
3. 静态门禁禁止这些 asset 重新出现 `AutomationCondition.eager()`。
4. 静态门禁禁止旧 automation sensor definition 继续 active。

不允许保留 active automation condition 作为 latest propagation 辅助路径。

### 9.5 Readiness

P6 必须先做只读性能方案，再进入代码：

1. gold 派生资产可用 lake fact readiness 判断输出文件、schema、row count、partition date、计算语义。
2. ClickHouse serving readiness 如无法从 lake 文件判断，必须用 bounded metadata 或 ClickHouse 只读查询，并写清读取次数和上限。
3. 不允许全历史逐分区调用 `asset_readiness_status(...)`。

## 10. P7 最终收口

P7 只做：

1. 更新文档状态。
2. 静态门禁收口。
3. 本地单元回归。
4. 性能报告对账。
5. 代码事实与文档口径对账。

P7 不做新功能开发。

## 11. 静态门禁总表

| 禁止项 | 门禁范围 |
| --- | --- |
| latest-only target 回流 | P1/P2C/P3/P5/P4/P6 迁移后的 sensor。 |
| 60 日窗口逐日调用单日 Dagster readiness wrapper | 所有接入 bounded selector 的 sensor。 |
| `raw_stock_basic` 生命周期事实长期下游直接消费 | P2B 迁移完成后的生产代码。 |
| `silver_stock_basic` 被用作历史退市股票全集 | P2A 后除 current snapshot / freshness guard 外的生产路径。 |
| `AutomationCondition.eager()` 继续作为 P6 四个资产 active 补洞入口 | P6 完成后的 assets/sensors。 |
| 直接 `dg.RunRequest(...)` / 手写 run key | 所有正式 sensor。 |
| cursor 写完整大数组或逐文件明细 | 新增/迁移后的 continuity sensors。 |

## 12. 最小本地测试矩阵

每阶段执行各自小回归；最终 P7 汇总：

```bash
cd lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_bounded_continuity.py \
  tests/test_adj_factor_m4_contracts.py \
  tests/test_stock_lifecycle_contracts.py \
  tests/test_stock_daily_sensor.py \
  tests/test_suspend_d_sensor.py \
  tests/test_index_daily_sensor.py \
  tests/test_silver_index_daily_sensor.py \
  tests/test_market_major_indices_lake_readiness.py \
  tests/test_market_major_indices_daily_sensor.py \
  tests/test_run_contract_static_gates.py
```

说明：

1. 具体测试文件可在实现阶段按现有测试命名调整。
2. 不运行 `dg`。
3. 不读取正式 Dagster runtime。
4. 不触碰正式 lake。

## 13. 需要在实现计划中再次确认的点

以下不是方案口径分歧，而是每个阶段开工计划必须列清的实现细节：

1. P2A `silver_stock_lifecycle` 是否纳入现有 `silver_stock_basic_update_job` selection；本 LLD 推荐纳入，不新增独立 sensor。
2. P6 四个派生资产显式 sensor 是拆成三个文件还是四个文件；无论如何旧 automation active 入口必须退出。
3. P4 gold lake readiness SQL 是否复用现有 check helper 内部 SQL，还是抽成 shared SQL builder；不能复制出语义漂移的第二套逻辑。
4. P2C adj factor batch readiness helper 已落在 `asset_guards/adj_factor_lake_readiness.py`，测试沿用业务语义命名；后续不得回流到阶段编号命名或 stock-mins helper。
5. P2B 开工前必须逐项审计 `stock_daily_checks.py` 中 current-listed 语义和 historical lifecycle 语义的边界：仍服务 `silver_stock_basic` freshness / current pool 的检查可以保留 current-listed 口径；`silver_stock_daily` 历史生命周期过滤、覆盖和下游完整性判断必须迁到 `silver_stock_lifecycle`。禁止用全局替换方式把所有 `silver_stock_basic_path` / `raw_stock_basic_path` 调用一刀切改掉。
6. P2C 已在 P2A/P2B 完成后重新做只读 DuckDB batch profiling；迁移到 `silver_stock_lifecycle` 后 20 日约 10.119ms、60 日约 13.323ms，完整 blocking check 语义可行。
7. P4 开工前必须先做只读 DuckDB SQL / 性能原型验证：覆盖 60 日 `gold_market_major_indices_daily` lake readiness、selected-date `silver_index_daily` lake readiness、`silver_index_basic` lake readiness 和 seed/input gate。已有 47 秒 / 超时数据只证明旧 wrapper 不可用，不能替代新 lake-derived readiness 的性能验收。
8. P6 开工前必须先做只读 readiness provider 审计：gold 派生资产优先 lake 文件事实，local / prod ClickHouse serving 优先 bounded ClickHouse 只读查询或明确 bounded metadata 查询；不得运行正式 automation evaluator，不得全历史逐分区调用 `asset_readiness_status(...)`。

## 14. 已确认无需额外性能测试的阶段

以下阶段已有只读 profiling 或读取模型证据支撑，进入开发前不需要再跑正式性能测试，但仍需按阶段计划列清硬口径和测试：

1. P0F：基础 selector 是纯函数，性能门禁来自本地单元测试和静态门禁，不读取正式 Dagster runtime。
2. P1：正式 calendar 读取、`cn_a_stock_current_trade_days` dynamic partitions 读取和 60 日 gap diff 已完成只读 profiling，均为亚秒级 / 毫秒级。
3. P3：股票日线 / 停复牌只加 expected registered gap guard，不扩大 selected-date readiness；正式 dynamic partition 和 materialized partition set 读取已验证为毫秒级。
4. P5：指数日线 raw/silver 保留既有 raw gap audit 和 silver bounded selector，只补 expected registered gap guard；20/60 日只读 profiling 已覆盖。

这些点应在各阶段进入开发前计划中列清并等待 review。
