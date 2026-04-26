# 数据集日期模型收敛方案 v1（单一事实源）

- 版本：v1
- 状态：已落地（审计能力待单独评审）
- 更新时间：2026-04-24
- 目标范围：`sync_v2 contract`、`validator/planner`、`ops freshness`
- 非目标：本方案不实现日期完整性审计；审计能力作为独立需求，在 `date_model` 收敛完成后重新评审。

---

## 1. 目标与结论

这次收敛的核心结论：

1. 同步执行语义与审计完整性语义本质是同一套“数据集日期模型”。  
2. 该模型应归位为数据集 contract 的原生属性，作为单一事实源。  
3. `validator/planner`、`freshness` 都只读这一份模型，不再各自维护副本。  
4. 后续日期完整性审计能力必须以 `date_model` 为前置依赖，但不纳入本次收敛实施范围。  

---

## 2. 现状（代码事实）

M0 前日期语义曾分散在三处：

1. **执行层（sync_v2 contract）**  
   - 定义位置：`DatasetSyncContract.planning_spec`  
   - 字段：`date_anchor_policy/anchor_type/window_policy` + `run_profiles_supported`  
   - 文件：`/Users/congming/github/goldenshare/src/foundation/services/sync_v2/contracts.py`（历史路径，已删除）

2. **状态层（freshness）**  
   - 定义位置：旧 freshness metadata  
   - 字段：`cadence/observed_date_column`（以及展示字段）  
   - 文件：旧 ops 规格注册表（已退场）

3. **策略层（特例覆盖）**  
   - M0 前已知漂移点是 `ths_daily`、`dc_daily` 存在 `anchor_type/window_policy` override。  
   - M0 目标是先把这两个漂移点清零，使策略层不再覆盖 contract 日期语义。  

当前落地后的代码事实：

1. **单一事实源**  
   - 定义位置：`DatasetSyncContract.date_model`  
   - 字段：`date_axis/bucket_rule/window_mode/input_shape/observed_field/audit_applicable/not_applicable_reason`
   - 文件：`/Users/congming/github/goldenshare/src/foundation/services/sync_v2/contracts.py`（历史路径，已删除）
2. **分域注册**  
   - 所有 56 个 V2 数据集通过 `build_date_model(dataset_key)` 绑定日期模型。  
   - 文件：`/Users/congming/github/goldenshare/src/foundation/services/sync_v2/registry_parts/common/date_models.py`（历史路径，已删除）
3. **执行层消费**  
   - `validator/planner/strategy_helpers` 通过 `resolve_contract_anchor_type()` 与 `resolve_contract_window_policy()` 从 `date_model` 派生运行时锚点语义。
   - `PlanningSpec` 不再保存 `anchor_type/window_policy/date_anchor_policy`。
4. **状态层消费**  
   - `ops.specs.registry` 只保留展示元数据，`observed_date_column` 从 `contract.date_model.observed_field` 派生。

### 2.1 M0 前主要问题

1. 语义重复定义，新增/修改数据集时容易漏改。  
2. 执行层与状态层可能出现漂移。  
3. 策略层 override 打破“contract 即事实”的原则。  

---

## 3. 收敛后的单一结构化模型（当前）

## 3.1 当前模型定义

在 `DatasetSyncContract` 中已新增 `date_model` 字段，类型 `DatasetDateModel`：

```python
@dataclass(slots=True, frozen=True)
class DatasetDateModel:
    # 时间基轴
    date_axis: str
    # 日期桶规则
    bucket_rule: str
    # 请求窗口语义
    window_mode: str
    # 输入形态（对 validator/planner 直接可用）
    input_shape: str
    # 观测字段（freshness 使用；后续审计能力复用）
    observed_field: str | None
    # 是否可做日期完整性审计
    audit_applicable: bool
    # 不可审计原因（audit_applicable=False 必填）
    not_applicable_reason: str | None = None
```

## 3.2 枚举（第一版）

### `date_axis`

1. `trade_open_day`
2. `natural_day`
3. `month_key`
4. `month_window`
5. `none`

### `bucket_rule`

1. `every_open_day`
2. `week_last_open_day`
3. `month_last_open_day`
4. `every_natural_day`
5. `every_natural_month`
6. `month_window_has_data`
7. `not_applicable`

### `window_mode`

1. `point`
2. `range`
3. `point_or_range`
4. `none`

### `input_shape`

1. `trade_date_or_start_end`
2. `month_or_range`
3. `start_end_month_window`
4. `ann_date_or_start_end`
5. `none`

---

## 4. 现状模型与目标模型映射关系

## 4.1 执行层映射

1. `anchor_type/date_anchor_policy + window_policy` -> `date_axis + bucket_rule + window_mode + input_shape`
2. `run_profiles_supported` 继续保留（执行控制），不并入日期模型

## 4.2 freshness 映射

1. `observed_date_column` -> `date_model.observed_field`
2. `cadence` 保留在 ops 展示元数据（不是日期语义核心）

## 4.3 后续审计能力关系

1. 日期完整性审计不在本方案内实现。  
2. 后续审计能力重新评审时，应以 `date_model.date_axis + bucket_rule + observed_field + audit_applicable` 作为规则来源。  
3. 审计 API、任务模型、前端交互、查询协议单独设计，不在本方案中提前写死。  

---

## 5. M0 前旧定义快照

说明：以下表格是 M0 前的旧定义快照，用于说明为什么需要收敛；不再作为实现事实源。当前实现事实源以第 6 节 `date_model` 表和 `registry_parts/common/date_models.py` 为准。

旧快照曾包含：

1. `run_profiles_supported`
2. 解析后的 `anchor_type/window_policy`
3. freshness `cadence/observed`
4. 是否存在策略层 override

| dataset_key | 数据集 | run_profiles | 当前 anchor_type | 当前 window_policy | freshness cadence | freshness observed | 策略 override |
|---|---|---|---|---|---|---|---|
| `adj_factor` | 复权因子 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `biying_equity_daily` | BIYING 股票日线 | `point_incremental/range_rebuild` | `natural_date_range` | `point_or_range` | `daily` | `trade_date` | `no` |
| `biying_moneyflow` | BIYING 资金流向 | `point_incremental/range_rebuild` | `natural_date_range` | `point_or_range` | `daily` | `trade_date` | `no` |
| `block_trade` | 大宗交易 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `broker_recommend` | 券商每月荐股 | `point_incremental/range_rebuild/snapshot_refresh` | `month_key_yyyymm` | `point_or_range` | `monthly` | `None` | `no` |
| `cyq_perf` | 每日筹码及胜率 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `daily` | 股票日线 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `daily_basic` | 股票日指标 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `dc_daily` | 东方财富板块行情 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `dc_hot` | 东方财富热榜 | `point_incremental/range_rebuild` | `natural_date_range` | `point_or_range` | `daily` | `trade_date` | `no` |
| `dc_index` | 东方财富概念板块 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `dc_member` | 东方财富板块成分 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `dividend` | 分红送转 | `range_rebuild/snapshot_refresh` | `natural_date_range` | `range` | `event` | `None` | `no` |
| `etf_basic` | ETF 基本信息 | `point_incremental/snapshot_refresh` | `none` | `point` | `reference` | `None` | `no` |
| `etf_index` | ETF 基准指数列表 | `point_incremental/snapshot_refresh` | `none` | `point` | `reference` | `None` | `no` |
| `fund_adj` | 基金复权因子 | `point_incremental/range_rebuild/snapshot_refresh` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `fund_daily` | 基金日线 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `hk_basic` | 港股列表 | `point_incremental/snapshot_refresh` | `none` | `point` | `reference` | `None` | `no` |
| `index_basic` | 指数主数据 | `point_incremental/snapshot_refresh` | `none` | `point` | `reference` | `None` | `no` |
| `index_daily` | 指数日线 | `point_incremental/range_rebuild` | `natural_date_range` | `point_or_range` | `daily` | `trade_date` | `no` |
| `index_daily_basic` | 指数日指标 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `index_monthly` | 指数月线 | `point_incremental/range_rebuild` | `month_end_trade_date` | `point_or_range` | `monthly` | `trade_date` | `no` |
| `index_weekly` | 指数周线 | `point_incremental/range_rebuild` | `week_end_trade_date` | `point_or_range` | `weekly` | `trade_date` | `no` |
| `index_weight` | 指数成分权重 | `range_rebuild` | `month_range_natural` | `range` | `monthly` | `trade_date` | `no` |
| `kpl_concept_cons` | 开盘啦题材成分 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `kpl_list` | 开盘啦榜单 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `limit_cpt_list` | 最强板块统计 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `limit_list_d` | 涨跌停榜 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `limit_list_ths` | 同花顺涨跌停榜单 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `limit_step` | 涨停天梯 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `margin` | 融资融券交易汇总 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `moneyflow` | 资金流向（基础） | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `moneyflow_cnt_ths` | 概念板块资金流向（同花顺） | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `moneyflow_dc` | 个股资金流向（东方财富） | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `moneyflow_ind_dc` | 板块资金流向（东方财富） | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `moneyflow_ind_ths` | 行业资金流向（同花顺） | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `moneyflow_mkt_dc` | 市场资金流向（东方财富） | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `moneyflow_ths` | 个股资金流向（同花顺） | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `stk_factor_pro` | 股票技术面因子(专业版) | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `stk_holdernumber` | 股东户数 | `range_rebuild/snapshot_refresh` | `natural_date_range` | `range` | `event` | `None` | `no` |
| `stk_limit` | 每日涨跌停价格 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `stk_nineturn` | 神奇九转指标 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `stk_period_bar_adj_month` | 股票复权月线 | `point_incremental/range_rebuild` | `month_end_trade_date` | `point_or_range` | `monthly` | `trade_date` | `no` |
| `stk_period_bar_adj_week` | 股票复权周线 | `point_incremental/range_rebuild` | `week_end_trade_date` | `point_or_range` | `weekly` | `trade_date` | `no` |
| `stk_period_bar_month` | 股票月线 | `point_incremental/range_rebuild` | `month_end_trade_date` | `point_or_range` | `monthly` | `trade_date` | `no` |
| `stk_period_bar_week` | 股票周线 | `point_incremental/range_rebuild` | `week_end_trade_date` | `point_or_range` | `weekly` | `trade_date` | `no` |
| `stock_basic` | 股票主数据 | `snapshot_refresh` | `none` | `none` | `reference` | `None` | `no` |
| `stock_st` | ST股票列表 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `suspend_d` | 每日停复牌信息 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `ths_daily` | 同花顺板块行情 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `ths_hot` | 同花顺热榜 | `point_incremental/range_rebuild` | `natural_date_range` | `point_or_range` | `daily` | `trade_date` | `no` |
| `ths_index` | 同花顺概念和行业指数 | `point_incremental/snapshot_refresh` | `none` | `point` | `reference` | `None` | `no` |
| `ths_member` | 同花顺板块成分 | `point_incremental/range_rebuild/snapshot_refresh` | `natural_date_range` | `point_or_range` | `reference` | `None` | `no` |
| `top_list` | 龙虎榜 | `point_incremental/range_rebuild` | `trade_date` | `point_or_range` | `daily` | `trade_date` | `no` |
| `trade_cal` | 交易日历 | `point_incremental/range_rebuild/snapshot_refresh` | `natural_date_range` | `point_or_range` | `reference` | `trade_date` | `no` |
| `us_basic` | 美股列表 | `point_incremental/snapshot_refresh` | `none` | `point` | `reference` | `None` | `no` |

---

## 6. 逐数据集定义（当前落地模型）

说明：下表是本次收敛后的当前定义（56/56），作为后续新增数据集和日期完整性审计的唯一模型依据。

| dataset_key | 数据集 | date_axis | bucket_rule | window_mode | input_shape | observed_field | 可审计 | not_applicable_reason |
|---|---|---|---|---|---|---|---|---|
| `adj_factor` | 复权因子 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `biying_equity_daily` | BIYING 股票日线 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `biying_moneyflow` | BIYING 资金流向 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `block_trade` | 大宗交易 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `broker_recommend` | 券商每月荐股 | `month_key` | `every_natural_month` | `point_or_range` | `month_or_range` | `month` | `yes` | - |
| `cyq_perf` | 每日筹码及胜率 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `daily` | 股票日线 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `daily_basic` | 股票日指标 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `dc_daily` | 东方财富板块行情 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `dc_hot` | 东方财富热榜 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `dc_index` | 东方财富概念板块 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `dc_member` | 东方财富板块成分 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `dividend` | 分红送转 | `natural_day` | `every_natural_day` | `range` | `ann_date_or_start_end` | `ann_date` | `yes` | - |
| `etf_basic` | ETF 基本信息 | `none` | `not_applicable` | `point` | `none` | `-` | `no` | snapshot/master dataset |
| `etf_index` | ETF 基准指数列表 | `none` | `not_applicable` | `point` | `none` | `-` | `no` | snapshot/master dataset |
| `fund_adj` | 基金复权因子 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `fund_daily` | 基金日线 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `hk_basic` | 港股列表 | `none` | `not_applicable` | `point` | `none` | `-` | `no` | snapshot/master dataset |
| `index_basic` | 指数主数据 | `none` | `not_applicable` | `point` | `none` | `-` | `no` | snapshot/master dataset |
| `index_daily` | 指数日线 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `index_daily_basic` | 指数日指标 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `index_monthly` | 指数月线 | `trade_open_day` | `month_last_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `index_weekly` | 指数周线 | `trade_open_day` | `week_last_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `index_weight` | 指数成分权重 | `month_window` | `month_window_has_data` | `range` | `start_end_month_window` | `trade_date` | `yes` | - |
| `kpl_concept_cons` | 开盘啦题材成分 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `kpl_list` | 开盘啦榜单 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `limit_cpt_list` | 最强板块统计 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `limit_list_d` | 涨跌停榜 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `limit_list_ths` | 同花顺涨跌停榜单 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `limit_step` | 涨停天梯 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `margin` | 融资融券交易汇总 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `moneyflow` | 资金流向（基础） | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `moneyflow_cnt_ths` | 概念板块资金流向（同花顺） | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `moneyflow_dc` | 个股资金流向（东方财富） | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `moneyflow_ind_dc` | 板块资金流向（东方财富） | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `moneyflow_ind_ths` | 行业资金流向（同花顺） | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `moneyflow_mkt_dc` | 市场资金流向（东方财富） | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `moneyflow_ths` | 个股资金流向（同花顺） | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `stk_factor_pro` | 股票技术面因子(专业版) | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `stk_holdernumber` | 股东户数 | `natural_day` | `every_natural_day` | `range` | `ann_date_or_start_end` | `ann_date` | `yes` | - |
| `stk_limit` | 每日涨跌停价格 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `stk_nineturn` | 神奇九转指标 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `stk_period_bar_adj_month` | 股票复权月线 | `trade_open_day` | `month_last_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `stk_period_bar_adj_week` | 股票复权周线 | `trade_open_day` | `week_last_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `stk_period_bar_month` | 股票月线 | `trade_open_day` | `month_last_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `stk_period_bar_week` | 股票周线 | `trade_open_day` | `week_last_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `stock_basic` | 股票主数据 | `none` | `not_applicable` | `none` | `none` | `-` | `no` | snapshot/master dataset |
| `stock_st` | ST股票列表 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `suspend_d` | 每日停复牌信息 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `ths_daily` | 同花顺板块行情 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `ths_hot` | 同花顺热榜 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `ths_index` | 同花顺概念和行业指数 | `none` | `not_applicable` | `point` | `none` | `-` | `no` | snapshot/master dataset |
| `ths_member` | 同花顺板块成分 | `none` | `not_applicable` | `point_or_range` | `none` | `-` | `no` | snapshot/master dataset |
| `top_list` | 龙虎榜 | `trade_open_day` | `every_open_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `trade_cal` | 交易日历 | `natural_day` | `every_natural_day` | `point_or_range` | `trade_date_or_start_end` | `trade_date` | `yes` | - |
| `us_basic` | 美股列表 | `none` | `not_applicable` | `point` | `none` | `-` | `no` | snapshot/master dataset |

---

## 6.1 运行时派生规则

`date_model` 是唯一事实源，但现有 planner/strategy 内部仍需要较窄的运行时锚点值。当前通过 helper 派生：

1. `date_axis=trade_open_day + bucket_rule=every_open_day` -> `trade_date`
2. `date_axis=trade_open_day + bucket_rule=week_last_open_day` -> `week_end_trade_date`
3. `date_axis=trade_open_day + bucket_rule=month_last_open_day` -> `month_end_trade_date`
4. `date_axis=natural_day` -> `natural_date_range`
5. `date_axis=month_key` -> `month_key_yyyymm`
6. `date_axis=month_window` -> `month_range_natural`
7. `date_axis=none` -> `none`

`window_policy` 不再单独维护，运行时直接读取 `date_model.window_mode`。

## 6.2 特殊但合规的数据集说明

1. `index_daily` 的日期模型仍是 `trade_open_day/every_open_day`，因为数据本身按交易日观测；但源接口默认必须按活跃指数池 `ts_code` 扇开并传 `start_date/end_date` 窗口，避免 `日期 * 指数池` 的请求爆炸。该差异属于数据集请求策略，不改变日期模型。
2. `broker_recommend` 的观测字段为 `month`（`YYYYMM` 字符串）。freshness 查询会把 `YYYYMM` 归一化到该月第一天用于状态计算。
3. `dividend` 与 `stk_holdernumber` 按 `ann_date` 自然日模型处理；上层可传 `start_date/end_date`，策略层按自然日扇开为 `ann_date` 请求。
4. `ths_member` 没有日期输入参数，当前按快照/主数据处理，`audit_applicable=false`。

---

## 7. 收敛迁移步骤（逐步切换）

## 7.1 Milestone 总览

| Milestone | 目标 | 主要产物 | 验证重点 |
|---|---|---|---|
| M0 | 收掉已知漂移点 | `ths_daily/dc_daily` contract 与策略口径统一 | 已完成：不再存在策略层 `anchor_type/window_policy` override；range 不重复请求同一窗口 |
| M1 | 日期模型落到 contract | `DatasetDateModel` 定义 + 56 个数据集补齐 | 已完成：linter/guardrail 能发现缺字段、非法组合、重复定义 |
| M2 | 执行层读取统一模型 | `validator/planner/strategy_helpers` 主读 `date_model` | 已完成：sync-daily/sync-history/sync-snapshot 行为保持兼容 |
| M3 | 状态层读取统一模型 | freshness `observed_field` 从 `date_model` 派生 | 已完成：数据状态页不再维护重复观测字段 |
| M4 | 删除旧日期字段与 fallback | 移除旧 `anchor_type/window_policy/date_anchor_policy` 主路径与重复元数据 | 已完成：旧字段不再作为事实源，测试门禁覆盖新增数据集流程 |

说明：

1. M0 是本轮新增的前置收口项，只处理 `ths_daily/dc_daily` 两个已知漂移点。  
2. M1-M4 是日期模型单一事实源的主线，不夹带新的数据集迁移。  
3. 每个 Milestone 单独验证、单独可回滚。  
4. 日期完整性审计作为后续独立需求，不作为本方案 Milestone。  

## Phase A0：先消除 `ths_daily/dc_daily` 策略层 override

目标：把已知漂移点先收掉，作为 date model 收敛的第一个可验证小闭环。

M0 前问题：

1. `ths_daily/dc_daily` 的 contract 仍保留旧板块池语义：`anchor_type=natural_date_range` + `universe_policy=<board_pool>`。  
2. 两个策略文件通过 `anchor_type_override=trade_date` 临时覆盖 contract。  
3. `range_rebuild` 下当前参数构造仍可能按 `start_date/end_date` 请求，而策略锚点已被展开成交易日，存在重复窗口请求风险。  

收敛目标：

1. `ths_daily/dc_daily` 的 contract 日期语义统一为：
   - `date_axis=trade_open_day`
   - `bucket_rule=every_open_day`
   - `window_mode=point_or_range`
   - `input_shape=trade_date_or_start_end`
2. 旧字段同步对齐为：
   - `anchor_type=trade_date`
   - `window_policy=point_or_range`
   - `universe_policy=none`
3. 策略层移除 `anchor_type_override/window_policy_override`。  
4. `range_rebuild` 按交易日历展开，每个 unit 使用自己的 `trade_date` 请求；`ts_code` 仅作为用户显式定向补数参数。  
5. `dc_daily` 的 `idx_type` 只在用户显式传入时参与枚举扇出；未传时不补默认值，由源接口返回全量。  

边界：

1. 本阶段只处理 `ths_daily/dc_daily`。  
2. 不处理 `ths_member/dc_member`、`ths_hot/dc_hot` 或其他板块族数据集。  
3. 不引入审计功能，不改 freshness 展示。  
4. 不删除旧日期字段，只先消除运行期 override。  

门禁：

1. 补充 `ths_daily/dc_daily` 策略单测，覆盖 point 与 range。  
2. 断言 `range_rebuild` 生成的 unit 使用逐日 `trade_date`，不重复传同一个 `start_date/end_date` 窗口。  
3. 断言策略文件中不再出现 `anchor_type_override/window_policy_override`。  
4. 跑 `tests/test_board_sync_services.py`、`tests/test_sync_v2_validator.py`、`tests/architecture/test_sync_v2_registry_guardrails.py`。  

## Phase A：模型落地，不改行为（已完成）

1. 在 contract 新增 `date_model`（56 数据集补齐）。  
2. linter 增加强校验（必填、组合合法）。  
3. 运行路径保持兼容，先补齐定义。  
4. `ths_daily/dc_daily` 延续 Phase A0 已收敛后的统一口径，不再重新引入策略覆盖。

## Phase B：执行层切主读（已完成）

1. `validator/planner` 改为主读 `date_model`。  
2. `PlanningSpec` 不再保存旧 `anchor_type/window_policy/date_anchor_policy`。  
3. 检查所有数据集策略文件，确认不再出现日期语义 override。

## Phase C：状态层切主读（已完成）

1. `ops.specs.registry` 的 `observed_date_column` 改为从 `date_model.observed_field` 派生。  
2. 旧 freshness metadata 的展示维度字段已迁入 `DatasetDefinition.domain`。

## Phase D：删除旧定义（已完成）

1. 删除 contract 中旧日期字段。  
2. 删除所有 fallback 逻辑与重复元数据。
3. 保留面向后续审计能力的 `date_model` 读取能力，但不实现审计 API、任务与前端。

---

## 8. 门禁与回滚

## 8.1 门禁

1. `tests/test_sync_v2_validator.py`
2. `tests/test_sync_v2_planner.py`
3. `tests/test_sync_v2_linter.py`
4. `tests/architecture/test_sync_v2_registry_guardrails.py`
5. `tests/test_ops_action_catalog.py` 与 `tests/test_ops_freshness_snapshot_query_service.py`

## 8.2 回滚

每个 Phase 单独提交，单独可回滚。  
回滚原则：恢复上一个 Phase 的读取路径，不做跨阶段混回滚。

---

## 9. 已确认口径

1. `broker_recommend` 使用 `month_key/every_natural_month/month_or_range`，observed field 为 `month`。  
2. `ths_member` 当前按快照/主数据处理，`audit_applicable=false`。  
3. `trade_cal` 使用 `natural_day/every_natural_day/trade_date_or_start_end`，observed field 为 `trade_date`；后续若做日期完整性审计，再结合交易所维度细化查询协议。
