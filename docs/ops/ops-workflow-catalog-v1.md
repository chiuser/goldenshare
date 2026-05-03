# 运维工作流目录与实现清单（Workflow Catalog v1）

> 更新时间：2026-04-23  
> 代码基线：`src/ops/action_catalog.py`、`src/ops/runtime/task_run_dispatcher.py`、`src/ops/queries/catalog_query_service.py`  
> 目标：把当前所有复合型任务（workflow）做成可审计实现清单，避免“记忆驱动运维”。

## 1. 当前工作流总览（共 6 个）

| 工作流 Key | 名称 | 支持自动调度 | 支持手动执行 | 默认调度策略 |
|---|---|---:|---:|---|
| `board_reference_refresh` | 板块主数据刷新 | 是 | 是 | 无 |
| `daily_market_close_maintenance` | 每日收盘后维护 | 是 | 是 | `trading_day_close` |
| `daily_moneyflow_maintenance` | 每日资金流向维护 | 是 | 是 | 无 |
| `index_extension_maintenance` | 指数扩展数据维护 | 否 | 是 | 无 |
| `index_kline_maintenance_pipeline` | 指数K线全链路维护 | 否 | 是 | 无 |
| `reference_data_refresh` | 基础主数据刷新 | 是 | 是 | 无 |

来源：`WORKFLOW_DEFINITION_REGISTRY`（`list_workflow_definitions()` 按 key 排序输出）。

---

## 2. 工作流运行机制（代码级）

### 2.1 入口与分发

- worker 在 dispatcher 中根据 `TaskRun.task_type` 分支：
  - `dataset_action` -> 数据集维护动作
  - `workflow` -> 工作流
  - `maintenance_action` -> 系统维护动作
- workflow 模式下，每个步骤会落 `ops.task_run_node`，问题进入 `ops.task_run_issue`：
  - `step_started`
  - `step_succeeded`
  - `step_failed`
  - `step_canceled`
  - `step_blocked`

参考：`src/ops/runtime/task_run_dispatcher.py`

### 2.2 步骤参数合成规则

每个 workflow step 的执行参数按以下顺序合并：

1. `execution.params_json`（工作流执行参数）
2. `workflow_step.default_params`
3. `workflow_step.params_override`

后者覆盖前者（同名键覆盖）。

### 2.3 失败策略与阻塞语义

- 有依赖步骤失败时，后继步骤会标记为 `blocked`，并记录 `skip_reason_code=dependency_failed`。
- 每步的有效失败策略：
  - `workflow_step.failure_policy_override`
  - 否则 `workflow.failure_policy_default`
  - 默认是 `fail_fast`
- 当步骤失败且策略是 `continue_on_error` 时，workflow 继续后续步骤；最终状态可能为 `partial_success`。
- 当步骤失败且策略是 `fail_fast` 时，workflow 立即返回：
  - 已有成功步骤 -> `partial_success`
  - 无成功步骤 -> `failed`
- 取消请求在当前单元抛出 `ExecutionCanceledError` 后返回 `canceled`。

### 2.4 最终状态判定

- 全部成功：`success`
- 有失败但允许继续并跑完：`partial_success`
- 失败并提前停止：`failed` 或 `partial_success`（取决于是否已有成功步骤）
- 取消：`canceled`

---

## 3. 工作流明细

## 3.1 `reference_data_refresh`（基础主数据刷新）

- 描述：刷新股票、交易日历（按完整日历刷新）、ETF 与指数基础信息。
- 支持自动调度：是
- 支持手动执行：是
- 支持参数：无
- 适用场景：主数据初始化、主数据质量巡检后的补刷。

步骤（顺序执行）：

| 序号 | step_key | 显示名 | action_key |
|---:|---|---|---|
| 1 | `stock_basic` | 股票主数据 | `stock_basic.maintain` |
| 2 | `trade_cal` | 交易日历 | `trade_cal.maintain` |
| 3 | `etf_basic` | ETF 基本信息 | `etf_basic.maintain` |
| 4 | `etf_index` | ETF 基准指数列表 | `etf_index.maintain` |
| 5 | `index_basic` | 指数基本信息 | `index_basic.maintain` |
| 6 | `hk_basic` | 港股列表 | `hk_basic.maintain` |

## 3.2 `daily_market_close_maintenance`（每日收盘后维护）

- 描述：覆盖日线、日指标、榜单与基金/指数日线的每日维护工作流。
- 支持自动调度：是
- 支持手动执行：是
- 默认调度策略：`trading_day_close`
- 支持参数：无（各步骤按自身 action 规则消费参数）
- 适用场景：盘后日常批处理。

步骤（顺序执行）：

| 序号 | step_key | 显示名 | action_key |
|---:|---|---|---|
| 1 | `daily` | 股票日线 | `daily.maintain` |
| 2 | `adj_factor` | 复权因子 | `adj_factor.maintain` |
| 3 | `daily_basic` | 股票日指标 | `daily_basic.maintain` |
| 4 | `cyq_perf` | 每日筹码及胜率 | `cyq_perf.maintain` |
| 5 | `stk_factor_pro` | 股票技术面因子(专业版) | `stk_factor_pro.maintain` |
| 6 | `margin` | 融资融券交易汇总 | `margin.maintain` |
| 7 | `stk_limit` | 每日涨跌停价格 | `stk_limit.maintain` |
| 8 | `stock_st` | ST股票列表 | `stock_st.maintain` |
| 9 | `limit_list` | 涨跌停榜 | `limit_list_d.maintain` |
| 10 | `suspend_d` | 每日停复牌信息 | `suspend_d.maintain` |
| 11 | `top_list` | 龙虎榜 | `top_list.maintain` |
| 12 | `block_trade` | 大宗交易 | `block_trade.maintain` |
| 13 | `fund_daily` | 基金日线 | `fund_daily.maintain` |
| 14 | `fund_adj` | 基金复权因子 | `fund_adj.maintain` |
| 15 | `index_daily` | 指数日线 | `index_daily.maintain` |
| 16 | `ths_daily` | 同花顺板块行情 | `ths_daily.maintain` |
| 17 | `dc_index` | 东方财富概念板块 | `dc_index.maintain` |
| 18 | `dc_member` | 东方财富板块成分 | `dc_member.maintain` |
| 19 | `dc_daily` | 东方财富板块行情 | `dc_daily.maintain` |
| 20 | `ths_hot` | 同花顺热榜 | `ths_hot.maintain` |
| 21 | `dc_hot` | 东方财富热榜 | `dc_hot.maintain` |
| 22 | `kpl_list` | 开盘啦榜单 | `kpl_list.maintain` |
| 23 | `limit_list_ths` | 同花顺涨跌停榜单 | `limit_list_ths.maintain` |
| 24 | `limit_step` | 涨停天梯 | `limit_step.maintain` |
| 25 | `limit_cpt_list` | 最强板块统计 | `limit_cpt_list.maintain` |
| 26 | `kpl_concept_cons` | 开盘啦题材成分 | `kpl_concept_cons.maintain` |

## 3.3 `daily_moneyflow_maintenance`（每日资金流向维护）

- 描述：覆盖个股、概念、行业、板块和市场维度的资金流向每日维护工作流。
- 支持自动调度：是
- 支持手动执行：是
- 支持参数：无
- 适用场景：盘后资金流向批处理。

步骤（顺序执行）：

| 序号 | step_key | 显示名 | action_key |
|---:|---|---|---|
| 1 | `moneyflow` | 资金流向（基础） | `moneyflow.maintain` |
| 2 | `moneyflow_ths` | 个股资金流向（同花顺） | `moneyflow_ths.maintain` |
| 3 | `moneyflow_dc` | 个股资金流向（东方财富） | `moneyflow_dc.maintain` |
| 4 | `moneyflow_cnt_ths` | 概念板块资金流向（同花顺） | `moneyflow_cnt_ths.maintain` |
| 5 | `moneyflow_ind_ths` | 行业资金流向（同花顺） | `moneyflow_ind_ths.maintain` |
| 6 | `moneyflow_ind_dc` | 板块资金流向（东方财富） | `moneyflow_ind_dc.maintain` |
| 7 | `moneyflow_mkt_dc` | 市场资金流向（东方财富） | `moneyflow_mkt_dc.maintain` |

## 3.4 `board_reference_refresh`（板块主数据刷新）

- 描述：刷新同花顺板块主数据与同花顺板块成分。
- 支持自动调度：是
- 支持手动执行：是
- 支持参数：无
- 适用场景：板块体系补全、板块成分定期刷新。

步骤（顺序执行）：

| 序号 | step_key | 显示名 | action_key |
|---:|---|---|---|
| 1 | `ths_index` | 同花顺概念和行业指数 | `ths_index.maintain` |
| 2 | `ths_member` | 同花顺板块成分 | `ths_member.maintain` |

## 3.5 `index_extension_maintenance`（指数扩展数据维护）

- 描述：批量维护指数日线、周线、月线、日指标和成分权重。
- 支持自动调度：否
- 支持手动执行：是
- 支持参数：无
- 适用场景：历史修复、指数扩展数据一次性维护。

步骤（顺序执行）：

| 序号 | step_key | 显示名 | action_key |
|---:|---|---|---|
| 1 | `index_daily` | 指数日线 | `index_daily.maintain` |
| 2 | `index_weekly` | 指数周线 | `index_weekly.maintain` |
| 3 | `index_monthly` | 指数月线 | `index_monthly.maintain` |
| 4 | `index_daily_basic` | 指数日指标 | `index_daily_basic.maintain` |
| 5 | `index_weight` | 指数权重 | `index_weight.maintain` |

## 3.6 `index_kline_maintenance_pipeline`（指数K线全链路维护）

- 描述：按日线→周线→月线→服务表补齐顺序执行。
- 支持自动调度：否
- 支持手动执行：是
- 支持参数：`start_date`、`end_date`
- 适用场景：指定区间重建指数 K 线链路。

步骤（顺序执行）：

| 序号 | step_key | 显示名 | action_key |
|---:|---|---|---|
| 1 | `index_daily` | 维护指数日线 | `index_daily.maintain` |
| 2 | `index_weekly` | 维护指数周线 | `index_weekly.maintain` |
| 3 | `index_monthly` | 维护指数月线 | `index_monthly.maintain` |
| 4 | `rebuild_index_serving` | 补齐指数服务表 | `maintenance.rebuild_index_kline_serving` |

---

## 4. 运维排查建议（面向值守）

1. 先看 step 粒度状态，不要只看 execution 总状态。
2. `partial_success` 通常表示：
   - 失败策略是 `continue_on_error` 并且后续步骤继续执行，或
   - fail-fast 之前已有部分步骤成功。
3. 出现 `blocked` 时，优先回看它的 `depends_on` 上游步骤失败原因。
4. 带维护动作的 workflow（如 `index_kline_maintenance_pipeline`）失败时，区分“采集失败”与“重建失败”。
5. 盘后工作流建议结合 `ops.task_run_node` 与 `ops.task_run_issue` 看步骤进度和问题诊断，不只看 rows 计数。

---

## 5. 变更治理规则（必须遵守）

新增或修改 workflow 时，必须同步完成以下事项：

1. 更新 `src/ops/action_catalog.py` 的 `WORKFLOW_DEFINITION_REGISTRY`。
2. 更新本文档（至少更新总览表 + 明细步骤）。
3. 若文档入口发生变化，同步更新 `docs/README.md`。
4. 增加/更新测试（至少）：
   - `tests/test_ops_action_catalog.py`（动作目录与步骤约束）
   - `tests/web/test_ops_catalog_api.py`（目录接口输出）
   - `tests/web/test_ops_runtime.py`（dispatch 语义，含 continue_on_error/依赖阻塞）
   - `tests/web/test_ops_schedule_api.py`（可调度工作流行为）
5. 提交信息中明确写明“workflow 变更范围”，禁止隐式变更。

---

## 6. `/api/v1/ops/catalog` 工作流字段映射（代码 -> 接口）

### 6.1 接口位置

- 路由：`GET /api/v1/ops/catalog`
- API 文件：`src/ops/api/catalog.py`
- 查询装配：`src/ops/queries/catalog_query_service.py`
- 返回模型：`src/ops/schemas/catalog.py`

### 6.2 workflow 顶层字段映射

`OpsCatalogResponse.workflows[]`（`WorkflowCatalogItem`）来源如下：

| 接口字段 | 代码来源 | 说明 |
|---|---|---|
| `key` | `workflow.key` | 工作流标识 |
| `display_name` | `workflow.display_name` | 工作流显示名称 |
| `description` | `workflow.description` | 工作流描述 |
| `parallel_policy` | `workflow.parallel_policy` | 并行策略 |
| `default_schedule_policy` | `workflow.default_schedule_policy` | 默认调度策略 |
| `schedule_enabled` | `workflow.schedule_enabled` | 是否支持自动调度 |
| `manual_enabled` | `workflow.manual_enabled` | 是否支持手动执行 |
| `schedule_binding_count` | `OpsSchedule` 分组统计（`target_type=workflow, target_key=workflow.key`） | 绑定调度总数 |
| `active_schedule_count` | 同上（状态 `active` 计数） | 激活调度数 |
| `parameters[]` | `workflow.parameters` | 工作流级参数定义 |
| `steps[]` | `workflow.steps` | 步骤清单 |

### 6.3 workflow step 字段映射

`workflows[].steps[]`（`WorkflowStepCatalogItem`）来源如下：

| 接口字段 | 代码来源 | 说明 |
|---|---|---|
| `step_key` | `step.step_key` | 步骤 key |
| `action_key` | `step.action_key` | 绑定动作 key |
| `dataset_key` | `step.dataset_key` | 数据集步骤对应的数据集 key |
| `display_name` | `step.display_name` | 步骤显示名 |
| `depends_on` | `list(step.depends_on)` | 依赖步骤 |
| `default_params` | `step.default_params` | 步骤默认参数 |

### 6.4 当前未暴露到 catalog API 的 workflow 字段

下列字段存在于 `WorkflowDefinition` 或 `WorkflowStepDefinition`，但当前 `GET /api/v1/ops/catalog` 不返回：

- `WorkflowDefinition.workflow_profile`
- `WorkflowDefinition.failure_policy_default`
- `WorkflowDefinition.probe_trigger_enabled`
- `WorkflowDefinition.resume_supported`
- `WorkflowStepDefinition.failure_policy_override`
- `WorkflowStepDefinition.params_override`
- `WorkflowStepDefinition.max_retry_per_unit`

这部分若后续需要前端可见，需同步修改：

1. `src/ops/schemas/catalog.py`
2. `src/ops/queries/catalog_query_service.py`
3. `tests/web/test_ops_catalog_api.py`
