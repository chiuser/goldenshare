# 运维工作流目录与实现清单（Workflow Catalog v1）

> 更新时间：2026-09-11（承接基础数据三线关闭记录；非新增生产运行验收）
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
- 当前 workflow 按定义的步骤顺序串行执行，为已开始步骤创建 `node_type=workflow_step` 的 `ops.task_run_node`，更新节点状态，异常记录到 `ops.task_run_issue`。不再把旧 `step_started/step_succeeded/...` 列为现行事件契约。
- `parallel_policy`、`depends_on` 虽存在于定义与目录响应，当前 `_dispatch_workflow` 不据此并行或做依赖阻塞判断；不能仅凭字段存在推断能力已实现。

参考：`src/ops/runtime/task_run_dispatcher.py`

### 2.2 步骤参数合成规则

每个 workflow step 的执行参数按以下顺序合并：

1. `task_run.request_payload_json`（工作流任务参数）
2. `workflow_step.default_params`
3. `workflow_step.params_override`

后者覆盖前者（同名键覆盖）。

### 2.3 失败策略与实际限制

- 当前不生成“依赖失败后后继步骤 blocked”的结果。`fail_fast` 停止后，未执行步骤不能当作已生成的 blocked 节点；`continue_on_error` 也不能当成会自动跳过失败依赖的安全保障。
- 每步的有效失败策略：
  - `workflow_step.failure_policy_override`
  - 否则 `workflow.failure_policy_default`
  - 默认是 `fail_fast`
- 当步骤失败且策略是 `continue_on_error` 时，workflow 继续后续步骤；最终状态可能为 `partial_success`。
- 当步骤失败且策略是 `fail_fast` 时，停止后续步骤并汇总：
  - 已有成功步骤 -> `partial_success`
  - 无成功步骤 -> `failed`
- 本函数的步骤异常统一进入 `except Exception`，没有像 dataset action 分支那样单独将 `IngestionCanceledError` 转为 `canceled`。不能在此承诺取消异常必然产生 canceled workflow；完整取消链需结合 worker 单独验收，本轮不改代码。

### 2.4 最终状态判定

- 全部成功：`success`
- 成功和失败步骤都有：`partial_success`；即使允许继续，若没有任何成功步骤仍为 `failed`
- 失败并提前停止：`failed` 或 `partial_success`（取决于是否已有成功步骤）
- 上述为 dispatcher 返回值，不替代 worker 最终落库状态；不将未实现的依赖阻塞或未经验证的取消保障写成已交付能力。

---

## 3. 工作流明细

## 3.1 `reference_data_refresh`（基础主数据刷新）

- 描述：刷新股票、股票曾用名、ST 风险警示事件、北交所代码映射、上市公司、交易日历（按完整日历刷新）、ETF 与指数基础信息。
- 支持自动调度：是
- 支持手动执行：是
- 支持参数：无
- 适用场景：主数据初始化、主数据质量巡检后的补刷。

已确认：该工作流手动入口保持无日期表单，不继承 `trade_cal` 的单日/区间能力；交易日历按完整日历刷新，不隐含最近 30 天窗口。完整刷新仍需按实际请求量和写入体量评估运行成本。

步骤（顺序执行）：

| 序号 | step_key | 显示名 | action_key |
|---:|---|---|---|
| 1 | `stock_basic` | 股票主数据 | `stock_basic.maintain` |
| 2 | `namechange` | 股票曾用名 | `namechange.maintain` |
| 3 | `st` | ST 风险警示事件 | `st.maintain` |
| 4 | `bse_mapping` | 北交所新旧代码对照 | `bse_mapping.maintain` |
| 5 | `stock_company` | 上市公司基本信息 | `stock_company.maintain` |
| 6 | `trade_cal` | 交易日历 | `trade_cal.maintain` |
| 7 | `etf_basic` | ETF 基本信息 | `etf_basic.maintain` |
| 8 | `etf_index` | ETF 基准指数列表 | `etf_index.maintain` |
| 9 | `index_basic` | 指数基本信息 | `index_basic.maintain` |
| 10 | `hk_basic` | 港股列表 | `hk_basic.maintain` |

## 3.2 `daily_market_close_maintenance`（每日收盘后维护）

- 描述：覆盖日线、集合竞价、历史基础列表、日指标、资金流、热榜、基金日线与新闻资讯的每日维护工作流。
- 支持自动调度：是
- 支持手动执行：是
- 默认调度策略：`trading_day_close`
- 支持参数：`trade_date`、`start_date`、`end_date`
- 适用场景：盘后日常批处理。

步骤（顺序执行）：

| 序号 | step_key | 显示名 | action_key |
|---:|---|---|---|
| 1 | `daily` | 股票日线 | `daily.maintain` |
| 2 | `stk_auction_o` | 股票开盘集合竞价 | `stk_auction_o.maintain` |
| 3 | `stk_auction_c` | 股票收盘集合竞价 | `stk_auction_c.maintain` |
| 4 | `adj_factor` | 复权因子 | `adj_factor.maintain` |
| 5 | `daily_basic` | 每日指标 | `daily_basic.maintain` |
| 6 | `bak_basic` | 股票历史基础列表 | `bak_basic.maintain` |
| 7 | `cyq_perf` | 每日筹码及胜率 | `cyq_perf.maintain` |
| 8 | `stk_factor_pro` | 股票技术面因子(专业版) | `stk_factor_pro.maintain` |
| 9 | `stk_limit` | 每日涨跌停价格 | `stk_limit.maintain` |
| 10 | `stock_st` | ST股票列表 | `stock_st.maintain` |
| 11 | `limit_list` | 每日涨跌停名单 | `limit_list_d.maintain` |
| 12 | `suspend_d` | 每日停复牌信息 | `suspend_d.maintain` |
| 13 | `top_list` | 龙虎榜 | `top_list.maintain` |
| 14 | `block_trade` | 大宗交易 | `block_trade.maintain` |
| 15 | `fund_daily` | 基金日线行情 | `fund_daily.maintain` |
| 16 | `fund_adj` | 基金复权因子 | `fund_adj.maintain` |
| 17 | `ths_daily` | 同花顺板块日线行情 | `ths_daily.maintain` |
| 18 | `dc_index` | 东方财富板块列表 | `dc_index.maintain` |
| 19 | `dc_member` | 东方财富板块成分 | `dc_member.maintain` |
| 20 | `dc_daily` | 东方财富板块日线行情 | `dc_daily.maintain` |
| 21 | `ths_hot` | 同花顺热榜 | `ths_hot.maintain` |
| 22 | `dc_hot` | 东方财富热榜 | `dc_hot.maintain` |
| 23 | `limit_list_ths` | 同花顺涨停名单 | `limit_list_ths.maintain` |
| 24 | `limit_step` | 连板梯队 | `limit_step.maintain` |
| 25 | `limit_cpt_list` | 涨停概念列表 | `limit_cpt_list.maintain` |
| 26 | `kpl_concept_cons` | 开盘啦板块成分 | `kpl_concept_cons.maintain` |
| 27 | `anns_d` | 上市公司公告 | `anns_d.maintain` |
| 28 | `irm_qa_sh` | 上证E互动问答 | `irm_qa_sh.maintain` |
| 29 | `irm_qa_sz` | 深证互动易问答 | `irm_qa_sz.maintain` |

当前为 29 步；`margin` 不在该工作流中，不代表其数据集或独立维护能力退场。

## 3.3 `daily_moneyflow_maintenance`（每日资金流向维护）

- 描述：覆盖个股、概念、行业、板块和市场维度的资金流向每日维护工作流。
- 支持自动调度：是
- 支持手动执行：是
- 支持参数：`trade_date`、`start_date`、`end_date`
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
- 支持参数：`start_date`、`end_date`
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

<a id="reference-data-closeout"></a>

### 基础数据三线接入关闭记录

原 2026-05-06 三线索引将“workflow 时间架构、五个数据集接入、工作流绑定”分开实施，并记录 M1–M5 及 M3.1/M4.1/M5.1 完成。其价值是避免把框架、数据集、绑定三类问题混在一次改动中，不是当前待执行顺序。

| 数据集 | 当前归属 | 接入说明 |
| --- | --- | --- |
| bse_mapping | reference_data_refresh | [北交所映射](/Users/congming/github/goldenshare/docs/datasets/bse-mapping-dataset-development.md) |
| stock_company | reference_data_refresh | [上市公司信息](/Users/congming/github/goldenshare/docs/datasets/stock-company-dataset-development.md) |
| namechange | reference_data_refresh | [曾用名](/Users/congming/github/goldenshare/docs/datasets/namechange-dataset-development.md) |
| st | reference_data_refresh | [ST 事件快照](/Users/congming/github/goldenshare/docs/datasets/st-dataset-development.md) |
| bak_basic | daily_market_close_maintenance | [历史基础列表](/Users/congming/github/goldenshare/docs/datasets/bak-basic-dataset-development.md) |

历史 M1/M2 区分时间形状与默认时间制度；M3/M3.1 接入并绑定基础快照，M4 收口 st 为 no-time snapshot，M4.1 退出无现行步骤来源的 reference_data_natural_day_maintenance，M5/M5.1 接入并绑定 bak_basic。不能因为保留时间制度能力，重新创建已退出的自然日工作流。

原关闭门禁覆盖定义/存储/请求与写入链、手动/自动 TaskRun、步骤执行及 catalog/schedule/文档一致性。此次仅核验注册表映射与既有回归，不把旧索引的“已完成”升级为今天重新完成生产同步。日期规则见[日期指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md#workflow-time)，回归入口见本文 §5；独立旧推进清单已合并，不重复列接入待办。

## 4. 运维排查建议（面向值守）

1. 先看 step 粒度状态，不要只看 workflow 总状态。
2. `partial_success` 通常表示：
   - 失败策略是 `continue_on_error` 并且后续步骤继续执行，或
   - fail-fast 之前已有部分步骤成功。
3. 不要把“未执行”视为已完成依赖阻塞，也不要仅凭 catalog 的 `depends_on` 判断后续步骤受到保护；参照 §2 的实际边界。
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
   - `tests/web/test_ops_runtime.py`（当前 scheduler/worker/dispatcher 回归；已有工作流步骤与无 probe 执行测试，不等于已覆盖依赖阻塞）
   - `tests/web/test_ops_task_run_api.py`（任务查询、重提与工作流目标恢复）
   - `tests/web/test_ops_schedule_api.py`（可调度工作流行为）
5. 提交信息中明确写明“workflow 变更范围”，禁止隐式变更。

---

## 6. 接口归属与自动任务边界

catalog 字段、定义到接口的来源、绑定统计及未暴露字段统一见 [API 参考 §12.1](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md#121-目录与模式)，本清单不再复制字段表。手动路由、时间模式和回归重点见 [Ops 当前契约 §11](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md#manual-maintenance)。

### 自动任务 probe 边界

按 [Ops 自动任务能力契约收敛方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-automation-capability-contract-plan-v1.md) 的已确认口径：

1. workflow 自动任务只能普通 `schedule` 触发；不得使用 `probe` 或 `schedule_probe_fallback`，也不得派生 `ops.probe_rule`。
2. workflow 可以包含支持源端 probe 的 dataset action；它在 workflow 中始终按工作流传入的日期和参数直接执行，不使用该数据集单独自动任务的 probe。
3. `WorkflowDefinition.probe_trigger_enabled` 是未被运行链路消费的历史字段，已在该方案 P1 删除；不得重新引入 UI 或 API 能力。

因此，`index_extension_maintenance` 与 `index_kline_maintenance_pipeline` 中的 `index_daily` 步骤保留，但不会获得 `remote_index_daily_ready` 的 workflow probe。
