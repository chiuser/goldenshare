# Sync V2 数据集策略简化方案 v1（全量 47 个 V2 数据集）

- 版本：v1
- 日期：2026-04-22
- 状态：已执行（持续收口中）
- 范围：`sync_v2` 已接入的 47 个数据集（不含未迁移 9 个）

---

## 1. 设计决策（本次拍板）

本方案只按以下 5 条落地，不再引入额外抽象层：

1. 保留 `engine`（执行、重试、进度、写入）这一层。
2. 请求编排改为“每个数据集一个策略函数”，每个策略函数放单独文件。
3. 仅保留 3 个通用 helper：交易日展开、分页循环、参数格式化。
4. 不做通用 provider 抽象；板块池/指数池逻辑放到对应数据集策略文件内。
5. contract 降级为最小必需字段，不再叠复杂 type 体系。

---

## 2. 目标目录结构（请求编排层）

```text
src/foundation/services/sync_v2/
  engine.py                         # 保留：执行主链路
  worker_client.py                  # 保留：重试/限速/分页请求
  normalizer.py                     # 保留：归一化
  writer.py                         # 保留：写入
  observer.py                       # 保留：进度上报
  runtime_contract.py               # 新：最小 contract 定义
  strategy_helpers/                 # 新：仅 3 个 helper
    trade_date_expand.py
    pagination_loop.py
    param_format.py
  dataset_strategies/               # 新：每个数据集 1 文件
    __init__.py
    adj_factor.py
    block_trade.py
    ...
```

说明：

1. `dataset_strategies/` 只放“请求如何发”的逻辑，不放写库逻辑。  
2. `engine` 通过 `runtime_contract.strategy_fn` 调用具体数据集策略函数生成请求单元。  
3. 原有 `planner` 逻辑逐步下沉到各策略文件；不再作为统一复杂编排中心扩展功能。  

---

## 3. 最小 Contract 定义（已落地形态）

当前实现采用“双层契约”：

1. 编排/校验层继续保留 `DatasetSyncContract`（兼容既有 `validator/planner/lint`）。
2. 引擎执行层落地最小运行时契约 `DatasetRuntimeContract`（见 `runtime_contract.py`），核心字段包括：
   - `dataset_key`
   - `api_name`
   - `fields`
   - `source_key_default`
   - `run_profiles_supported`
   - `strategy_fn`

说明：

1. 当前没有一次性删除 `InputSchema/PlanningSpec/...`，这是刻意的平稳迁移策略，不是遗漏。
2. 请求编排已按“每数据集策略函数”迁移；旧契约对象保留用于门禁与兼容。

---

## 4. 通用 Helper（仅 3 个）

### 4.1 `trade_date_expand.py`

职责：

1. 接收 `trade_date` 或 `start_date/end_date`。
2. 按交易日历展开交易日列表。
3. 支持周末/月末交易日压缩（给周期栏/周期线使用）。

### 4.2 `pagination_loop.py`

职责：

1. 封装 `limit/offset` 分页循环。
2. 统一终止条件：返回条数 `< limit` 即停止。
3. 支持“不分页”模式直通。

### 4.3 `param_format.py`

职责：

1. 日期格式化（`YYYYMMDD` / `YYYYMM`）。
2. 参数透传（仅透传用户显式输入）。
3. 多值参数扇出辅助（单字段枚举扇出、双字段笛卡尔组合）。

---

## 5. 全量 47 个 V2 数据集：策略文件映射

> 规则：每个数据集 1 个策略文件，文件名与数据集同名。  
> 函数命名统一：`build_<dataset_key>_units(...)`。

| dataset_key | 策略文件 | 默认请求语义（目标） |
| --- | --- | --- |
| adj_factor | `dataset_strategies/adj_factor.py` | 交易日点式 + 分页 |
| block_trade | `dataset_strategies/block_trade.py` | 交易日点式 + 分页 |
| broker_recommend | `dataset_strategies/broker_recommend.py` | `month(YYYYMM)` 月键请求 + 分页 |
| cyq_perf | `dataset_strategies/cyq_perf.py` | 交易日点式 + 分页 |
| daily | `dataset_strategies/daily.py` | 交易日点式 + 分页 |
| daily_basic | `dataset_strategies/daily_basic.py` | 交易日点式 + 分页 |
| dc_daily | `dataset_strategies/dc_daily.py` | 时间核心（`trade_date` 或区间交易日枚举）+ 分页，不做板块代码扇出 |
| dc_hot | `dataset_strategies/dc_hot.py` | 交易日点式 + 分页；多值参数按需扇出 |
| dc_index | `dataset_strategies/dc_index.py` | 交易日点式 + 分页 |
| dc_member | `dataset_strategies/dc_member.py` | 时间核心（`trade_date` 或区间交易日枚举）+ 分页，不做板块代码扇出 |
| etf_basic | `dataset_strategies/etf_basic.py` | 快照 + 分页 |
| etf_index | `dataset_strategies/etf_index.py` | 快照 + 分页 |
| fund_adj | `dataset_strategies/fund_adj.py` | 交易日点式/区间 + 分页 |
| fund_daily | `dataset_strategies/fund_daily.py` | 交易日点式 + 分页 |
| hk_basic | `dataset_strategies/hk_basic.py` | 快照 + 分页 |
| index_basic | `dataset_strategies/index_basic.py` | 快照 + 分页 |
| index_daily | `dataset_strategies/index_daily.py` | active 指数池 fanout + 交易日点式/区间 + 分页 |
| index_daily_basic | `dataset_strategies/index_daily_basic.py` | 交易日点式 + 分页 |
| kpl_concept_cons | `dataset_strategies/kpl_concept_cons.py` | 交易日点式 + 分页 |
| kpl_list | `dataset_strategies/kpl_list.py` | 交易日点式 + 分页；`tag` 多值按需扇出 |
| limit_cpt_list | `dataset_strategies/limit_cpt_list.py` | 交易日点式 + 分页 |
| limit_list_d | `dataset_strategies/limit_list_d.py` | 交易日点式 + 分页；`exchange/limit_type` 组合扇出 |
| limit_list_ths | `dataset_strategies/limit_list_ths.py` | 交易日点式 + 分页 |
| limit_step | `dataset_strategies/limit_step.py` | 交易日点式 + 分页 |
| margin | `dataset_strategies/margin.py` | 交易日点式 + 分页；`exchange_id` 枚举扇出 |
| moneyflow | `dataset_strategies/moneyflow.py` | 交易日点式 + 分页 |
| moneyflow_cnt_ths | `dataset_strategies/moneyflow_cnt_ths.py` | 交易日点式 + 分页 |
| moneyflow_dc | `dataset_strategies/moneyflow_dc.py` | 交易日点式 + 分页 |
| moneyflow_ind_dc | `dataset_strategies/moneyflow_ind_dc.py` | 交易日点式 + 分页；`content_type` 枚举扇出 |
| moneyflow_ind_ths | `dataset_strategies/moneyflow_ind_ths.py` | 交易日点式 + 分页 |
| moneyflow_mkt_dc | `dataset_strategies/moneyflow_mkt_dc.py` | 交易日点式 + 分页 |
| moneyflow_ths | `dataset_strategies/moneyflow_ths.py` | 交易日点式 + 分页 |
| stk_limit | `dataset_strategies/stk_limit.py` | 交易日点式 + 分页 |
| stk_nineturn | `dataset_strategies/stk_nineturn.py` | 交易日点式 + 分页，固定 `freq=daily` |
| stk_period_bar_adj_month | `dataset_strategies/stk_period_bar_adj_month.py` | 月末交易日锚点 + 分页，固定月线参数 |
| stk_period_bar_adj_week | `dataset_strategies/stk_period_bar_adj_week.py` | 周末交易日锚点 + 分页，固定周线参数 |
| stk_period_bar_month | `dataset_strategies/stk_period_bar_month.py` | 月末交易日锚点 + 分页，固定月线参数 |
| stk_period_bar_week | `dataset_strategies/stk_period_bar_week.py` | 周末交易日锚点 + 分页，固定周线参数 |
| stock_st | `dataset_strategies/stock_st.py` | 交易日点式 + 分页 |
| suspend_d | `dataset_strategies/suspend_d.py` | 交易日点式 + 分页 |
| ths_daily | `dataset_strategies/ths_daily.py` | 时间核心（`trade_date` 或区间交易日枚举）+ 分页，不做板块代码扇出 |
| ths_hot | `dataset_strategies/ths_hot.py` | 交易日点式 + 分页；多值参数按需扇出 |
| ths_index | `dataset_strategies/ths_index.py` | 快照 + 分页 |
| ths_member | `dataset_strategies/ths_member.py` | 无时间参数，单窗分页，不做板块代码扇出 |
| top_list | `dataset_strategies/top_list.py` | 交易日点式 + 分页 |
| trade_cal | `dataset_strategies/trade_cal.py` | 自然日区间单窗 + 分页 |
| us_basic | `dataset_strategies/us_basic.py` | 快照 + 分页 |

---

## 6. 迁移执行顺序（只改编排，不改写入链路）

### 6.1 Batch-1（先改你刚拍板的 4 个）

1. `dc_member`
2. `ths_member`
3. `dc_daily`
4. `ths_daily`

目标：

1. 去掉默认板块代码扇出。
2. 落地“时间核心分页”与“单窗分页”语义。

### 6.2 Batch-2（低风险交易日点式组）

`daily, daily_basic, adj_factor, block_trade, cyq_perf, top_list, stock_st, suspend_d, stk_limit, stk_nineturn, limit_cpt_list, limit_step`

### 6.3 Batch-3（枚举扇出组）

`limit_list_d, margin, moneyflow_ind_dc, kpl_list, dc_hot, ths_hot`

### 6.4 Batch-4（快照组）

`index_basic, etf_basic, etf_index, hk_basic, us_basic, ths_index`

### 6.5 Batch-5（指数与周期组）

`index_daily, index_daily_basic, stk_period_bar_week, stk_period_bar_month, stk_period_bar_adj_week, stk_period_bar_adj_month, broker_recommend`

### 6.6 Batch-6（资金流其余组）

`moneyflow, moneyflow_ths, moneyflow_dc, moneyflow_cnt_ths, moneyflow_ind_ths, moneyflow_mkt_dc`

### 6.7 Batch-7（剩余）

`fund_daily, fund_adj, kpl_concept_cons, dc_index, trade_cal, limit_list_ths`

---

## 7. 门禁与回滚

## 7.1 门禁（分阶段迁移，避免“旧门禁假匹配”）

### 7.1.1 当前实现可用门禁（基线）

在“尚未改造到新方案”前，沿用当前门禁：

1. `tests/test_sync_v2_validator.py`
2. `tests/test_sync_v2_planner.py`
3. `tests/test_sync_v2_worker_client.py`
4. `tests/test_sync_v2_linter.py`
5. `tests/architecture/test_sync_v2_registry_guardrails.py`
6. 本 batch 涉及数据集的 CLI 冒烟 + 对账

说明：以上门禁与当前 `planning_spec + planner + linter` 体系匹配，作为重构起点。

### 7.1.2 新方案目标门禁（完成切换后的常态）

当请求编排切到“每数据集策略函数 + 最小 contract”后，门禁应切到：

1. `tests/test_sync_v2_validator.py`（保留，按最小 contract 重写用例）
2. `tests/test_sync_v2_strategy_engine.py`（新增，覆盖 engine 调 strategy_fn 的主链路）
3. `tests/test_sync_v2_strategy_helpers.py`（新增，覆盖交易日展开/分页循环/参数格式化）
4. `tests/test_sync_v2_dataset_strategies.py`（新增，覆盖每个数据集策略的请求单元生成）
5. `tests/architecture/test_sync_v2_registry_guardrails.py`（保留并升级为“策略文件分组与模板门禁”）
6. 本 batch 涉及数据集的 CLI 冒烟 + 对账

同时逐步下线：

1. `tests/test_sync_v2_planner.py`（在 planner 被策略函数替代后下线）
2. `tests/test_sync_v2_linter.py`（在 `planning_spec` 语义退出后重构/下线）

### 7.1.3 门禁切换节奏（必须与代码改造同步）

1. 阶段 A（结构迁移期）  
保留现有 5 个门禁，新增 `strategy_helpers` 与 `strategy_engine` 测试，不下线旧测试。
2. 阶段 B（双轨期）  
数据集逐批迁移到 `dataset_strategies/`，新增 `dataset_strategies` 覆盖；旧 `planner/linter` 测试允许部分保留但不得新增新语义依赖。
3. 阶段 C（收口期）  
当所有 V2 数据集完成策略函数迁移后，下线 `test_sync_v2_planner.py`，重构或下线 `test_sync_v2_linter.py`，以新门禁集合作为唯一基线。

### 7.2 回滚

1. （历史）按数据集粒度回滚曾依赖 `USE_SYNC_V2_DATASETS`；当前运行为 V2-only，回滚按提交粒度执行。  
2. 编码回滚只回退本 batch，不跨批次回退。  
3. 出现异常只暂停当前数据集，不影响其他已稳定数据集。  

---

## 8. 与旧方案关系

本方案替代“高抽象 planner/provider/type 扩展路线”，后续请求编排以“每数据集单独策略文件”为唯一主线。  
之前复杂抽象相关文档可保留历史记录，但不作为后续实施依据。
