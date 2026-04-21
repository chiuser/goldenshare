# Tushare 全量数据集参数审计 v1（V2 + 非V2实现）

- 审计时间：2026-04-21
- 范围：`src/foundation/services/sync/registry.py` 全量 56 个资源（`tushare=54`，`biying=2`）
- 审计目标：不只看 V2 contract，同时覆盖非 V2 旧实现，核对“文档参数 / 任务入口参数 / 服务请求参数”的一致性与合理性。
- 数据源：
  - `docs/sources/tushare/docs_index.csv` + 对应接口文档 `输入参数`
  - `src/foundation/services/sync/**/*.py`（真实参数构造与上游请求）
  - `src/ops/specs/registry.py`（`sync_daily/sync_history/backfill` 对外参数）
  - `src/foundation/services/sync_v2/registry.py`（V2 contract 覆盖）

## 1. 总体结论

- 资源总数：`56`（Tushare `54` + Biying `2`）
- 已有 V2 contract：`38`；仍为非 V2：`18`
- 非 V2 资源：`biying_equity_daily, biying_moneyflow, dc_daily, dc_hot, dividend, index_monthly, index_weekly, index_weight, stk_factor_pro, stk_holdernumber, stk_period_bar_adj_month, stk_period_bar_adj_week, stk_period_bar_month, stk_period_bar_week, stock_basic, ths_daily, ths_hot, ths_member`
- 关键结论：
  1. 当前“源文档参数”与“运行入口参数”存在系统性投影差异（属于既有策略，不全是 bug）。
  2. 非 V2 资源的参数语义分散在服务代码里，缺少统一 contract，是后续 anchor_type 改造的主要风险源。
  3. 存在明确请求效率/完整性风险：`moneyflow`、`moneyflow_cnt_ths`、`us_basic` 文档支持分页，但请求层未显式分页。

## 2. 参数形态分类（全量）

### 2.1 源文档时间参数形态

| 形态 | 数量 |
| --- | ---: |
| `trade_date+range` | 39 |
| `trade_date_only` | 4 |
| `range_only` | 2 |
| `month_only` | 1 |
| `no_time` | 9 |

### 2.2 实现运行入口时间参数形态（代码）

| 形态 | 数量 |
| --- | ---: |
| `trade_date+range` | 30 |
| `trade_date_only` | 14 |
| `no_time` | 11 |
| `month+other` | 1 |

### 2.3 ts_code 支持情况

- 文档声明支持 `ts_code`：`50` / 56
- 运行入口支持 `ts_code`（代码可见）：`26` / 56

## 3. 关键差异与风险（全量审计结果）

### 3.1 文档支持 `ts_code`，但 `sync_history` 不暴露 `ts_code`（策略差异）

- 资源数：`18`
- 资源：`block_trade, daily_basic, etf_basic, etf_index, fund_adj, fund_daily, hk_basic, index_basic, kpl_list, limit_cpt_list, limit_list_d, limit_list_ths, limit_step, moneyflow, stock_basic, ths_daily, top_list, us_basic`
- 说明：这类多数是“产品策略收敛”（避免高维筛选），不是立即故障；但会影响按代码定向补数能力。

### 3.2 文档有区间能力，但 `sync_history` 未完整暴露区间（策略差异/能力缺口）

- 资源数：`3`
- 资源：`dc_member, stk_holdernumber, ths_daily`
- 说明：需要结合后续 anchor_type 统一策略决定是否补齐。

### 3.3 明确请求层风险：文档支持分页，但服务请求未显式分页

- 资源：`moneyflow, moneyflow_cnt_ths, us_basic`
- 风险：当单次返回量超过上游默认上限时，存在截断或历史漏数风险。
- 优先级建议：P0。

### 3.4 月度语义专项

- `broker_recommend`：源文档为 `month` 口径，当前 `sync_daily` 已改为 `month` 参数（不再要求 `trade_date`），语义正确。
- 仍建议在后续 anchor_type 改造中将其明确归类为 `month_key_yyyymm`，避免再被交易日语义污染。

## 4. 非 V2 资源（18个）专项审计表

| resource | api | 文档时间形态 | 运行入口时间形态 | sync_daily参数 | sync_history参数 | 请求参数（上游） | 文档输入参数 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `biying_equity_daily` | `equity_daily_bar` | `-` | `trade_date+range` | `trade_date` | `end_date, start_date` | `adj_type, dm, et, freq, lt, st` | `-` |
| `biying_moneyflow` | `moneyflow` | `trade_date+range` | `trade_date+range` | `trade_date` | `end_date, start_date` | `dm, et, st` | `end_date, limit, offset, start_date, trade_date, ts_code` |
| `dc_daily` | `dc_daily` | `trade_date+range` | `trade_date+range` | `idx_type, trade_date, ts_code` | `end_date, idx_type, start_date, ts_code` | `-` | `end_date, idx_type, start_date, trade_date, ts_code` |
| `dc_hot` | `dc_hot` | `trade_date_only` | `trade_date_only` | `hot_type, is_new, market, trade_date, ts_code` | `end_date, hot_type, is_new, market, start_date, trade_date, ts_code` | `hot_type, is_new, market` | `hot_type, is_new, market, trade_date, ts_code` |
| `dividend` | `dividend` | `no_time` | `trade_date_only` | `-` | `ts_code` | `ann_date, ts_code` | `ann_date, ex_date, imp_ann_date, record_date, ts_code` |
| `index_monthly` | `index_monthly` | `trade_date+range` | `no_time` | `-` | `end_date, start_date, ts_code` | `-` | `end_date, start_date, trade_date, ts_code` |
| `index_weekly` | `index_weekly` | `trade_date+range` | `trade_date_only` | `-` | `end_date, start_date, ts_code` | `limit, offset` | `end_date, start_date, trade_date, ts_code` |
| `index_weight` | `index_weight` | `trade_date+range` | `trade_date+range` | `-` | `end_date, index_code, start_date` | `end_date, index_code, start_date` | `end_date, index_code, start_date, trade_date` |
| `stk_factor_pro` | `stk_factor_pro` | `trade_date+range` | `trade_date+range` | `trade_date, ts_code` | `end_date, start_date, trade_date, ts_code` | `limit, offset, ts_code` | `end_date, start_date, trade_date, ts_code` |
| `stk_holdernumber` | `stk_holdernumber` | `range_only` | `trade_date_only` | `-` | `ts_code` | `ann_date, ts_code` | `ann_date, end_date, enddate, start_date, ts_code` |
| `stk_period_bar_adj_month` | `stk_week_month_adj` | `trade_date+range` | `no_time` | `trade_date` | `end_date, start_date, ts_code` | `-` | `end_date, freq, start_date, trade_date, ts_code` |
| `stk_period_bar_adj_week` | `stk_week_month_adj` | `trade_date+range` | `no_time` | `-` | `end_date, start_date, ts_code` | `-` | `end_date, freq, start_date, trade_date, ts_code` |
| `stk_period_bar_month` | `stk_weekly_monthly` | `trade_date+range` | `no_time` | `trade_date` | `end_date, start_date, ts_code` | `-` | `end_date, freq, start_date, trade_date, ts_code` |
| `stk_period_bar_week` | `stk_weekly_monthly` | `trade_date+range` | `no_time` | `-` | `end_date, start_date, ts_code` | `-` | `end_date, freq, start_date, trade_date, ts_code` |
| `stock_basic` | `stock_basic` | `no_time` | `no_time` | `-` | `source_key` | `list_status` | `exchange, is_hs, list_status, market, name, ts_code` |
| `ths_daily` | `ths_daily` | `trade_date+range` | `trade_date+range` | `trade_date, ts_code` | `-` | `-` | `end_date, start_date, trade_date, ts_code` |
| `ths_hot` | `ths_hot` | `trade_date_only` | `trade_date_only` | `is_new, market, trade_date, ts_code` | `end_date, is_new, market, start_date, trade_date, ts_code` | `is_new, market` | `is_new, market, trade_date, ts_code` |
| `ths_member` | `ths_member` | `no_time` | `no_time` | `-` | `con_code, ts_code` | `-` | `con_code, ts_code` |

> 重点关注：`dc_* / ths_* / stock_basic / stk_period_* / index_weekly,index_monthly,index_weight / stk_factor_pro` 仍属非 V2，建议作为下一轮 contract 化主目标。

## 5. 全量资源矩阵（56）

| resource | source | api | V2 | 文档时间形态 | 实现时间形态 | 文档含ts_code | 实现含ts_code | sync_daily参数 | sync_history参数 | 请求参数（上游） |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `adj_factor` | tushare | `adj_factor` | Y | trade_date+range | trade_date+range | Y | Y | `trade_date` | `end_date, start_date, ts_code` | `end_date, start_date, trade_date, ts_code` |
| `biying_equity_daily` | biying | `equity_daily_bar` | N | - | trade_date+range | N | N | `trade_date` | `end_date, start_date` | `adj_type, dm, et, freq, lt, st` |
| `biying_moneyflow` | biying | `moneyflow` | N | trade_date+range | trade_date+range | Y | N | `trade_date` | `end_date, start_date` | `dm, et, st` |
| `block_trade` | tushare | `block_trade` | Y | trade_date+range | trade_date_only | Y | N | `trade_date` | `end_date, start_date` | `trade_date` |
| `broker_recommend` | tushare | `broker_recommend` | Y | month_only | month+other | N | N | `month` | `-` | `limit, month, offset` |
| `cyq_perf` | tushare | `cyq_perf` | Y | trade_date+range | trade_date+range | Y | Y | `trade_date, ts_code` | `end_date, start_date, trade_date, ts_code` | `limit, offset, ts_code` |
| `daily` | tushare | `daily` | Y | trade_date+range | trade_date+range | Y | Y | `trade_date` | `end_date, start_date, ts_code` | `end_date, start_date, trade_date, ts_code` |
| `daily_basic` | tushare | `daily_basic` | Y | trade_date+range | trade_date_only | Y | N | `trade_date` | `end_date, start_date` | `trade_date` |
| `dc_daily` | tushare | `dc_daily` | N | trade_date+range | trade_date+range | Y | N | `idx_type, trade_date, ts_code` | `end_date, idx_type, start_date, ts_code` | `-` |
| `dc_hot` | tushare | `dc_hot` | N | trade_date_only | trade_date_only | Y | N | `hot_type, is_new, market, trade_date, ts_code` | `end_date, hot_type, is_new, market, start_date, trade_date, ts_code` | `hot_type, is_new, market` |
| `dc_index` | tushare | `dc_index` | Y | trade_date+range | trade_date+range | Y | Y | `idx_type, trade_date, ts_code` | `end_date, idx_type, start_date, ts_code` | `end_date, idx_type, start_date, trade_date, ts_code` |
| `dc_member` | tushare | `dc_member` | Y | trade_date+range | trade_date_only | Y | N | `con_code, trade_date, ts_code` | `con_code, trade_date, ts_code` | `-` |
| `dividend` | tushare | `dividend` | N | no_time | trade_date_only | Y | Y | `-` | `ts_code` | `ann_date, ts_code` |
| `etf_basic` | tushare | `etf_basic` | Y | no_time | trade_date_only | Y | N | `-` | `exchange, list_status` | `list_status` |
| `etf_index` | tushare | `etf_index` | Y | no_time | trade_date_only | Y | Y | `-` | `-` | `ts_code` |
| `fund_adj` | tushare | `fund_adj` | Y | trade_date+range | trade_date+range | Y | N | `trade_date` | `end_date, start_date` | `end_date, limit, offset, start_date, trade_date` |
| `fund_daily` | tushare | `fund_daily` | Y | trade_date+range | trade_date+range | Y | N | `trade_date` | `end_date, start_date` | `end_date, limit, offset, start_date, trade_date` |
| `hk_basic` | tushare | `hk_basic` | Y | no_time | no_time | Y | N | `-` | `list_status` | `list_status` |
| `index_basic` | tushare | `index_basic` | Y | no_time | no_time | Y | N | `-` | `-` | `-` |
| `index_daily` | tushare | `index_daily` | Y | trade_date+range | trade_date+range | Y | Y | `trade_date` | `end_date, start_date, ts_code` | `end_date, limit, offset, start_date, trade_date, ts_code` |
| `index_daily_basic` | tushare | `index_dailybasic` | Y | trade_date+range | trade_date+range | Y | Y | `-` | `end_date, start_date, ts_code` | `end_date, limit, offset, start_date, trade_date, ts_code` |
| `index_monthly` | tushare | `index_monthly` | N | trade_date+range | no_time | Y | N | `-` | `end_date, start_date, ts_code` | `-` |
| `index_weekly` | tushare | `index_weekly` | N | trade_date+range | trade_date_only | Y | Y | `-` | `end_date, start_date, ts_code` | `limit, offset` |
| `index_weight` | tushare | `index_weight` | N | trade_date+range | trade_date+range | N | N | `-` | `end_date, index_code, start_date` | `end_date, index_code, start_date` |
| `kpl_concept_cons` | tushare | `kpl_concept_cons` | Y | trade_date_only | trade_date_only | Y | Y | `con_code, trade_date, ts_code` | `con_code, trade_date, ts_code` | `con_code, trade_date, ts_code` |
| `kpl_list` | tushare | `kpl_list` | Y | trade_date+range | trade_date+range | Y | Y | `tag, trade_date` | `end_date, start_date, tag, trade_date` | `end_date, start_date, tag, trade_date, ts_code` |
| `limit_cpt_list` | tushare | `limit_cpt_list` | Y | trade_date+range | trade_date+range | Y | Y | `trade_date` | `end_date, start_date, trade_date` | `end_date, start_date, trade_date, ts_code` |
| `limit_list_d` | tushare | `limit_list_d` | Y | trade_date+range | trade_date+range | Y | Y | `exchange, limit_type, trade_date` | `end_date, exchange, limit_type, start_date, trade_date` | `end_date, exchange, limit_type, start_date, trade_date, ts_code` |
| `limit_list_ths` | tushare | `limit_list_ths` | Y | trade_date+range | trade_date_only | Y | N | `limit_type, market, trade_date` | `end_date, limit_type, market, start_date, trade_date` | `limit_type, market` |
| `limit_step` | tushare | `limit_step` | Y | trade_date+range | trade_date+range | Y | Y | `trade_date` | `end_date, start_date, trade_date` | `end_date, nums, start_date, trade_date, ts_code` |
| `margin` | tushare | `margin` | Y | trade_date+range | trade_date+range | N | N | `exchange_id, trade_date` | `end_date, exchange_id, start_date, trade_date` | `exchange_id, trade_date` |
| `moneyflow` | tushare | `moneyflow` | Y | trade_date+range | trade_date_only | Y | N | `trade_date` | `end_date, start_date` | `trade_date` |
| `moneyflow_cnt_ths` | tushare | `moneyflow_cnt_ths` | Y | trade_date+range | trade_date+range | Y | Y | `trade_date, ts_code` | `end_date, start_date, trade_date, ts_code` | `ts_code` |
| `moneyflow_dc` | tushare | `moneyflow_dc` | Y | trade_date+range | trade_date+range | Y | Y | `trade_date, ts_code` | `end_date, start_date, trade_date, ts_code` | `limit, offset, ts_code` |
| `moneyflow_ind_dc` | tushare | `moneyflow_ind_dc` | Y | trade_date+range | trade_date+range | Y | Y | `content_type, trade_date, ts_code` | `content_type, end_date, start_date, trade_date, ts_code` | `limit, offset, ts_code` |
| `moneyflow_ind_ths` | tushare | `moneyflow_ind_ths` | Y | trade_date+range | trade_date+range | Y | Y | `trade_date, ts_code` | `end_date, start_date, trade_date, ts_code` | `limit, offset, ts_code` |
| `moneyflow_mkt_dc` | tushare | `moneyflow_mkt_dc` | Y | trade_date+range | trade_date+range | N | N | `trade_date` | `end_date, start_date, trade_date` | `limit, offset` |
| `moneyflow_ths` | tushare | `moneyflow_ths` | Y | trade_date+range | trade_date+range | Y | Y | `trade_date, ts_code` | `end_date, start_date, trade_date, ts_code` | `limit, offset, ts_code` |
| `stk_factor_pro` | tushare | `stk_factor_pro` | N | trade_date+range | trade_date+range | Y | Y | `trade_date, ts_code` | `end_date, start_date, trade_date, ts_code` | `limit, offset, ts_code` |
| `stk_holdernumber` | tushare | `stk_holdernumber` | N | range_only | trade_date_only | Y | Y | `-` | `ts_code` | `ann_date, ts_code` |
| `stk_limit` | tushare | `stk_limit` | Y | trade_date+range | trade_date+range | Y | Y | `trade_date, ts_code` | `end_date, start_date, trade_date, ts_code` | `limit, offset, ts_code` |
| `stk_nineturn` | tushare | `stk_nineturn` | Y | trade_date+range | trade_date+range | Y | Y | `trade_date, ts_code` | `end_date, start_date, trade_date, ts_code` | `limit, offset, ts_code` |
| `stk_period_bar_adj_month` | tushare | `stk_week_month_adj` | N | trade_date+range | no_time | Y | N | `trade_date` | `end_date, start_date, ts_code` | `-` |
| `stk_period_bar_adj_week` | tushare | `stk_week_month_adj` | N | trade_date+range | no_time | Y | N | `-` | `end_date, start_date, ts_code` | `-` |
| `stk_period_bar_month` | tushare | `stk_weekly_monthly` | N | trade_date+range | no_time | Y | N | `trade_date` | `end_date, start_date, ts_code` | `-` |
| `stk_period_bar_week` | tushare | `stk_weekly_monthly` | N | trade_date+range | no_time | Y | N | `-` | `end_date, start_date, ts_code` | `-` |
| `stock_basic` | tushare | `stock_basic` | N | no_time | no_time | Y | N | `-` | `source_key` | `list_status` |
| `stock_st` | tushare | `stock_st` | Y | trade_date+range | trade_date+range | Y | Y | `trade_date, ts_code` | `end_date, start_date, trade_date, ts_code` | `limit, offset, ts_code` |
| `suspend_d` | tushare | `suspend_d` | Y | trade_date+range | trade_date+range | Y | Y | `suspend_type, trade_date, ts_code` | `end_date, start_date, suspend_type, trade_date, ts_code` | `limit, offset, suspend_type, ts_code` |
| `ths_daily` | tushare | `ths_daily` | N | trade_date+range | trade_date+range | Y | N | `trade_date, ts_code` | `-` | `-` |
| `ths_hot` | tushare | `ths_hot` | N | trade_date_only | trade_date_only | Y | N | `is_new, market, trade_date, ts_code` | `end_date, is_new, market, start_date, trade_date, ts_code` | `is_new, market` |
| `ths_index` | tushare | `ths_index` | Y | no_time | no_time | Y | Y | `-` | `exchange, ts_code, type` | `exchange, ts_code, type` |
| `ths_member` | tushare | `ths_member` | N | no_time | no_time | Y | N | `-` | `con_code, ts_code` | `-` |
| `top_list` | tushare | `top_list` | Y | trade_date_only | trade_date_only | Y | N | `trade_date` | `end_date, start_date` | `trade_date` |
| `trade_cal` | tushare | `trade_cal` | Y | range_only | trade_date+range | N | N | `-` | `end_date, exchange, start_date` | `end_date, exchange, start_date` |
| `us_basic` | tushare | `us_basic` | Y | no_time | no_time | Y | N | `-` | `classify` | `classify` |

## 6. 结论与后续建议

1. 本轮审计已经覆盖全量资源，不再局限 V2。
2. 下一步建议先做“参数语义收口”而非直接改代码：
   - 统一 anchor_type（`trade_date/week_end_trade_date/month_end_trade_date/month_range_natural/month_key_yyyymm/natural_date_range/none`）
   - 统一 sync_daily 仅适用于 trade_date 类资源，月度/快照类走对应语义入口
   - 对 P0 分页风险资源先补请求层分页保障（`moneyflow`、`moneyflow_cnt_ths`、`us_basic`）
3. 详细机器审计产物：
   - `/Users/congming/github/goldenshare/reports/tushare_full_sync_param_audit_2026-04-21.json`
   - `/Users/congming/github/goldenshare/reports/tushare_full_sync_param_audit_2026-04-21.csv`
   - `/Users/congming/github/goldenshare/reports/tushare_full_sync_param_audit_with_specs_2026-04-21.json`

## 7. 非 V2 旧实现代码审计（人工逐文件）

> 本节是“人工读代码”结论，目标是确认未迁移资源是否存在旧实现风险；不是脚本静态推断。

### 7.1 已确认的实现问题（需要进入改造清单）

1. 低频事件类参数能力丢失（`dividend` / `stk_holdernumber`）
- 代码位置：
  - `src/foundation/services/sync/sync_dividend_service.py`
  - `src/foundation/services/sync/sync_holdernumber_service.py`
- 现状：
  - 两者共用 `build_date_window_params`，仅透传 `ts_code` + `ann_date`。
  - 文档支持的 `start_date/end_date/enddate/record_date/ex_date/imp_ann_date` 未进入请求构造。
  - `sync_daily` 注入的 `trade_date` 在这两个实现中不会转成任何上游过滤条件。
- 风险：
  - 历史回补只能依赖“按代码全量拉”，无法按时间窗精确控制。
  - 任务语义和用户输入预期不一致，回补效率与可控性差。

2. 周月线族仍使用“日任务触发 + 接口自判”方式（`stk_period_bar_*`）
- 代码位置：
  - `src/foundation/services/sync/sync_stk_period_bar_week_service.py`
  - `src/foundation/services/sync/sync_stk_period_bar_month_service.py`
  - `src/foundation/services/sync/sync_stk_period_bar_adj_week_service.py`
  - `src/foundation/services/sync/sync_stk_period_bar_adj_month_service.py`
- 现状：
  - 参数构造函数允许传 `trade_date`，但没有周末/月末锚点约束，也没有“无效日期快速短路”策略。
  - 在 `sync_daily` 语义下会频繁触发非周末/月末请求。
- 风险：
  - 请求次数浪费、调度噪音高、可观测性上出现大量“无业务增量”的执行。

3. 板块族 fanout 逻辑分散在服务内部（`ths_daily` / `dc_daily` / `ths_member`）
- 代码位置：
  - `src/foundation/services/sync/sync_ths_daily_service.py`
  - `src/foundation/services/sync/sync_dc_daily_service.py`
  - `src/foundation/services/sync/sync_ths_member_service.py`
- 现状：
  - 通过先刷新索引表再逐板块扇出调用，逻辑可用，但 fanout 语义、过滤策略、重试节奏都散落在各服务。
  - 与 V2 planner 的统一 fanout 能力（策略可配置）尚未对齐。
- 风险：
  - 同类数据集重复实现，后续维护成本高；同一类参数变更需要多处同步改动。

4. `biying_moneyflow` 写路径跨层耦合（raw + std + serving 在一个服务里）
- 代码位置：
  - `src/foundation/services/sync/sync_biying_moneyflow_service.py`
- 现状：
  - 单个同步服务内同时写 `raw_biying.moneyflow`、`core_multi.moneyflow_std` 并触发 serving 发布。
- 风险：
  - 同步执行链路与层级职责耦合，难以纳入统一 contract/engine 的 write_path 策略。
  - 失败恢复与重跑边界不清晰（raw 成功但 std/serving 失败时的重试语义复杂）。

### 7.2 设计上可接受但需要后续 contract 化收口的实现

1. `stock_basic`
- 现状：以 `source_key` 为主控，Tushare 侧固定 `list_status=L,D,P,G`，Biying 侧直拉。
- 结论：这是当前业务策略，不是 bug；但参数语义与“通用 sync_daily/sync_history”模型不一致，应在 V2 contract 中显式建模为 snapshot + source policy。

2. `index_weekly` / `index_monthly`
- 现状：分页拉取后基于 active index 池过滤，并对缺失代码做 daily 派生补齐。
- 结论：功能上可运行；但“指数池约束 + 周月聚合 + 派生补齐”是复合策略，建议后续拆为 contract 能力项，避免埋在服务实现中。

3. `index_weight`
- 现状：强制要求 `index_code`（不提供 index_code 则拒绝执行）。
- 结论：语义可接受，但需要在任务编排层明确“这是按指数代码执行”的类型，不应混入通用 `sync_daily` 期待。

### 7.3 全量口径结论（面向后续方案）

1. 本次已覆盖全量 56 资源，并且对未迁移 18 资源完成逐文件审计。
2. 非 V2 旧实现的主要问题不在“单个 bug”，而在能力模型分散：
- 时间锚点语义分散（`trade_date/week_end_trade_date/month_end_trade_date/month_range_natural/month_key_yyyymm/natural_date_range/none`）。
- fanout 语义分散（指数池、板块池、按代码）。
- 写路径策略分散（raw-only、raw+serving、raw+std+serving）。
3. 后续方案应以“能力模型统一”为目标，不建议继续对旧服务做补丁式修补。

## 8. AnchorType 重划分建议（基于全量审计）

### 8.1 划分原则

1. 先按时间语义划分（交易日/自然日/月键/无时间），再按窗口模式划分（point/range/point_or_range/none）。  
2. 不再把所有“月度”都归为月末交易日；`index_weight` 与 `broker_recommend` 单独建类。  
3. anchor_type 是全局枚举，数据集必须显式归类。  

### 8.2 建议分类与典型数据集

| anchor_type | 说明 | 典型数据集 |
| --- | --- | --- |
| `trade_date` | 交易日单点/区间 | `daily, moneyflow, stk_limit, suspend_d` |
| `week_end_trade_date` | 每周最后交易日 | `index_weekly, stk_period_bar_week, stk_period_bar_adj_week` |
| `month_end_trade_date` | 每月最后交易日 | `index_monthly, stk_period_bar_month, stk_period_bar_adj_month` |
| `month_range_natural` | 自然月首日~末日区间 | `index_weight` |
| `month_key_yyyymm` | 月键 `YYYYMM` | `broker_recommend` |
| `natural_date_range` | 自然日区间（通常公告日期） | `dividend, stk_holdernumber` |
| `none` | 无时间锚点快照类 | `stock_basic, ths_member, etf_basic, index_basic` |

### 8.3 直接落地约束

1. `sync_daily` 仅用于 `anchor_type=trade_date` 且 `window_policy` 含 `point` 的资源。  
2. 周/月最后交易日类必须先做交易日历锚点约束，再落请求参数。  
3. `index_weight` 必须固定为自然月区间策略：建议输入当月第一天与最后一天自然日。  
