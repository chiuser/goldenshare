# 基础数据工作流与数据集三线推进索引 v1

状态：执行中（M1、M2、M3、M3.1、M4、M4.1、M5、M5.1 已完成，后续里程碑已细化）  
最后更新：2026-05-05  
目标：把当前三组并行但不能混写的任务拆开，并给出推荐推进顺序。

---

## 1. 当前三组任务

当前至少存在三组任务，它们职责不同，不能混成一个文档，也不应混成一次随意实现。

### A. Workflow 架构升级

范围：

1. workflow 时间语义
2. workflow 默认时间制度
3. workflow 自动任务默认日期生成

对应文档：

1. [Workflow 时间形状与时间制度分析 v1](/Users/congming/github/goldenshare/docs/architecture/workflow-time-shape-vs-time-regime-analysis-v1.md)
2. [基础数据自然日维护工作流方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-workflow-reference-data-natural-day-maintenance-development-v1.md)

说明：

1. 上位架构分析负责讲清“时间形状 vs 时间制度”与 M2 允许改动面
2. 具体 workflow 方案只定义 `reference_data_natural_day_maintenance` 这一个 workflow

### B. 五个新数据集开发接入

范围：

1. `bak_basic`
2. `bse_mapping`
3. `namechange`
4. `st`
5. `stock_company`

对应文档：

1. [股票历史基础列表](/Users/congming/github/goldenshare/docs/datasets/bak-basic-dataset-development.md)
2. [北交所新旧代码对照](/Users/congming/github/goldenshare/docs/datasets/bse-mapping-dataset-development.md)
3. [股票曾用名](/Users/congming/github/goldenshare/docs/datasets/namechange-dataset-development.md)
4. [ST 风险警示事件](/Users/congming/github/goldenshare/docs/datasets/st-dataset-development.md)
5. [上市公司基本信息](/Users/congming/github/goldenshare/docs/datasets/stock-company-dataset-development.md)

### C. 工作流对接

范围：

1. 哪些数据集并入现有 workflow
2. 哪些数据集接到新 workflow
3. catalog / schedule / runtime / 文档同步

当前已明确的归属判断：

1. `bse_mapping`
   - 进入 `reference_data_refresh`
2. `stock_company`
   - 进入 `reference_data_refresh`
3. `bak_basic`
   - 进入 `daily_market_close_maintenance`
4. `namechange`
   - 进入 `reference_data_refresh`
5. `st`
   - 进入 `reference_data_natural_day_maintenance`

---

## 2. 为什么不能乱序推进

### 2.1 不能先做自然日 workflow 对接，再补 workflow 架构

原因：

当前 workflow 若是 `point` 且没显式日期，会默认回落到“截至当前自然日的最近开市日”。

如果不先收口这一层：

1. `st`

即使接进了新 workflow，也会继续吃错的默认时间制度。

### 2.2 不能先做 workflow 对接，再做数据集接入

原因：

workflow step 的目标对象必须是真实存在、可执行、可测的数据集 action。

如果 5 个数据集本体还没接入，workflow 对接只是空壳。

### 2.3 不能把架构升级和需求接入混在一轮里瞎改

原因：

1. 风险定位会混乱
2. 回归验证会失焦
3. 一旦出问题，很难判断是 workflow 框架、数据集定义还是 workflow 绑定出了问题

---

## 3. 推荐推进顺序

### M1：完成 workflow 架构口径确认

产物：

1. `workflow-time-shape-vs-time-regime-analysis-v1.md`
2. `ops-workflow-reference-data-natural-day-maintenance-development-v1.md`

目标：

1. 明确 `point/range/none` 只是时间形状
2. 明确 workflow 默认时间制度要从交易日补值里拆出来
3. 锁定新 natural_day workflow 的最小实现方向
4. 明确 M2 允许改动面、禁止改动面与最小回归门禁

状态：已完成

### M2：实现 workflow 架构最小升级

范围：

1. `src/ops/action_catalog.py`
2. `src/ops/services/task_run_service.py`
3. `src/ops/runtime/task_run_dispatcher.py`
4. workflow 相关测试与文档

目标：

1. 新增 natural_day workflow 所需的默认时间制度切口
2. 不影响现有交易日 workflow

门禁：

1. `daily_market_close_maintenance` 行为不变
2. 自然日 workflow 不再回落到最近开市日

状态：已完成

### M3：接入两类快照基础数据

对象：

1. `bse_mapping`
2. `stock_company`

原因：

1. 它们都是 `none/snapshot`
2. 不依赖 workflow 时间制度改造
3. 适合先独立完成数据集主链，再立刻并入 `reference_data_refresh`

状态：已完成

### M3.1：对接 `reference_data_refresh`

对象：

1. `bse_mapping`
2. `stock_company`
3. `namechange`

原因：

1. 这些数据集的时间制度是 `none`
2. 它们不需要等待 natural_day workflow
3. 接入完成后立刻并入现有快照型 workflow，能形成完整闭环

门禁：

1. `reference_data_refresh` 步骤清单更新完成
2. 手动任务与自动任务都能创建该 workflow 的 TaskRun
3. workflow step 能真实执行 `st`
4. `ops-workflow-catalog-v1.md` 与相关 API 文档同步完成

状态：已完成

### M4：接入自然日基础数据

对象：

1. `st`

原因：

1. 它依赖前面的 natural_day workflow 架构切口
2. 先把数据集本体接入完成，才能做自然日 workflow 的真实步骤对接和验收

状态：已完成

### M4.1：新增并对接 `reference_data_natural_day_maintenance`

对象：

1. `st`

原因：

1. 该 workflow 的存在意义就是承接 `natural_day + point/range` 这批基础数据
2. 不应在数据集尚未可执行时先做空壳对接
3. 也不应把这批对接拖到所有数据集都完成之后再统一收口

门禁：

1. 新 workflow 定义、目录、文档与测试全部落地
2. `st` 可通过手动任务与自动任务进入该 workflow
3. 默认时间制度保持自然日，不回落到“截至今天的最近开市日”
4. workflow 详情、catalog 与 schedule 口径一致

状态：已完成

### M5：接入交易日基础数据

对象：

1. `bak_basic`

原因：

1. 它是 `trade_open_day`
2. 最终会并入 `daily_market_close_maintenance`
3. 与自然日 workflow 架构不耦合，但和交易日维护口径有关

状态：已完成

### M5.1：对接 `daily_market_close_maintenance`

对象：

1. `bak_basic`

原因：

1. 它是这批 5 个数据集中唯一明确归属交易日维护 workflow 的对象
2. 与 `st` 的自然日 workflow 没有耦合
3. 接入完成后应立即闭环，不应拖到最后和其他 workflow 一起混改

状态：已完成

门禁：

1. `daily_market_close_maintenance` 步骤清单更新完成
2. 手动任务与自动任务都能创建包含 `bak_basic` 的 TaskRun
3. 交易日默认时间制度保持原语义，不影响既有步骤
4. workflow step 真实执行与文档同步完成

---

## 4. 每个里程碑的完成门禁

### M2 门禁

1. workflow 默认时间制度切口已落地
2. 交易日 workflow 回归通过
3. natural_day workflow 单点默认日期不再走最近开市日

### M3-M5 数据集接入门禁

每个数据集接入都必须单独满足：

1. DatasetDefinition 完整
2. storage 设计完整
3. request builder / planner / normalization / writer 链路打通
4. 手动维护可用
5. 自动任务能力符合文档
6. 文档与代码口径一致

### M3.1 / M4.1 / M5.1 工作流收口门禁

每一批工作流收口都必须满足：

1. catalog 中 workflow 目录更新正确
2. 手动任务与自动任务都能正确创建 TaskRun
3. workflow step 真实执行通过
4. 文档同步完成
5. 只收本批数据集，不顺手混入其他未完成对象

---

## 5. 当前建议

当前不建议直接开始“把 5 个数据集都塞进 workflow”，也不建议把所有 workflow 对接拖到最后统一做。

正确顺序是：

1. 先做 M3：接入 `bse_mapping`、`stock_company`
2. 立刻做 M3.1：把这两个对象并入 `reference_data_refresh`
3. 再做 M4：接入 `namechange`、`st`，其中 `namechange` 按 no-time snapshot 归入 `reference_data_refresh`
4. 立刻做 M4.1：新增并对接 `reference_data_natural_day_maintenance`
5. 最后做 M5：接入 `bak_basic`
6. 立刻做 M5.1：把 `bak_basic` 并入 `daily_market_close_maintenance`

这样做的好处是：

1. 风险隔离清楚
2. 每轮验证目标单一
3. 出问题时容易定位
4. 不会出现“5 个数据集都接进去了，但 3 条 workflow 还没收口”的半完成状态

---

## 6. 关联文档

1. [运维工作流目录与实现清单](/Users/congming/github/goldenshare/docs/ops/ops-workflow-catalog-v1.md)
2. [基础数据自然日维护工作流方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-workflow-reference-data-natural-day-maintenance-development-v1.md)
3. [Workflow 时间形状与时间制度分析 v1](/Users/congming/github/goldenshare/docs/architecture/workflow-time-shape-vs-time-regime-analysis-v1.md)
