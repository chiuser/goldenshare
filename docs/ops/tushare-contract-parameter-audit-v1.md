# Tushare Contract 输入参数审计 v1（先审计，不下锚点结论）

- 日期：2026-04-21
- 范围：`src/foundation/services/sync_v2/registry.py` 中当前已落地的 38 个 V2 contract（Tushare）
- 对照源：`docs/sources/tushare/docs_index.csv` 与对应接口文档 `## 输入参数` 段
- 目标：先把“代码 contract 与源接口参数”事实对齐清楚，为后续 `anchor_type` 讨论提供稳定基线

---

## 1. 审计方法（事实口径）

1. 提取每个 contract 的：
   - `dataset_key`
   - `api_name`
   - `input_schema.fields`
   - `run_profiles_supported`
   - `planning_spec`（`date_anchor_policy/universe_policy/enum_fanout_fields`）
2. 通过 `api_name` 映射到 `docs/sources/tushare/docs_index.csv` 的 `local_path`。
3. 解析对应 markdown 中 `## 输入参数` 表格，抽取：
   - 参数名（`name`）
   - 是否必选（`必选` 列）
4. 对比规则：
   - `exact`：contract 参数集 = doc 参数集
   - `contract_superset`：contract 参数集严格包含 doc 参数集
   - `doc_superset`：doc 参数集严格包含 contract 参数集
   - `both_diff`：双方都存在独有参数

---

## 2. 总体统计

| 指标 | 数值 |
| --- | ---: |
| V2 contract 数据集数 | 38 |
| 文档命中数 | 38 |
| 文档未命中 | 0 |
| exact | 11 |
| contract_superset | 13 |
| doc_superset | 10 |
| both_diff | 4 |

---

## 3. 参数分类统计（先给事实，不下结论）

## 3.1 时间维度参数形态（contract vs doc）

### Contract 侧

| 分类 | 数量 | 数据集 |
| --- | ---: | --- |
| `trade_date + start_date/end_date` | 32 | `adj_factor, block_trade, broker_recommend, cyq_perf, daily, daily_basic, dc_index, dc_member, fund_adj, fund_daily, index_daily, index_daily_basic, kpl_concept_cons, kpl_list, limit_cpt_list, limit_list_d, limit_list_ths, limit_step, margin, moneyflow, moneyflow_cnt_ths, moneyflow_dc, moneyflow_ind_dc, moneyflow_ind_ths, moneyflow_mkt_dc, moneyflow_ths, stk_limit, stk_nineturn, stock_st, suspend_d, top_list, trade_cal` |
| `trade_date` only | 6 | `etf_basic, etf_index, hk_basic, index_basic, ths_index, us_basic` |
| `month` only | 0 | - |
| 无时间参数 | 0 | - |

### Doc 侧

| 分类 | 数量 | 数据集 |
| --- | ---: | --- |
| `trade_date + start_date/end_date` | 28 | `adj_factor, block_trade, cyq_perf, daily, daily_basic, dc_index, dc_member, fund_adj, fund_daily, index_daily, index_daily_basic, kpl_list, limit_cpt_list, limit_list_d, limit_list_ths, limit_step, margin, moneyflow, moneyflow_cnt_ths, moneyflow_dc, moneyflow_ind_dc, moneyflow_ind_ths, moneyflow_mkt_dc, moneyflow_ths, stk_limit, stk_nineturn, stock_st, suspend_d` |
| `trade_date` only | 2 | `kpl_concept_cons, top_list` |
| `start_date/end_date` only | 1 | `trade_cal` |
| `month` only | 1 | `broker_recommend` |
| 无时间参数 | 6 | `etf_basic, etf_index, hk_basic, index_basic, ths_index, us_basic` |

## 3.2 `trade_date` / `start_end` / `month` 支持统计

| 维度 | Contract | Doc |
| --- | ---: | ---: |
| 含 `trade_date` | 38 | 30 |
| 同时含 `start_date` + `end_date` | 32 | 29 |
| 含 `month` | 1 | 1 |

## 3.3 `ts_code` 支持统计

| 维度 | Contract | Doc |
| --- | ---: | ---: |
| 含 `ts_code` | 33 | 34 |

`contract` 不含 `ts_code` 的数据集：`broker_recommend, hk_basic, margin, moneyflow_mkt_dc, trade_cal`  
`doc` 不含 `ts_code` 的数据集：`broker_recommend, margin, moneyflow_mkt_dc, trade_cal`

## 3.4 其他参数族（从请求维度扩展分类）

| 参数族 | 事实统计（contract/doc） | 备注 |
| --- | --- | --- |
| 分页参数 `limit/offset` | `0 / 9` | doc 侧出现于：`fund_adj, moneyflow*, us_basic` |
| 市场参数 `exchange/exchange_id/market` | `12 / 7`（分项：`exchange 10/4`, `exchange_id 1/1`, `market 1/2`） | 市场筛选口径不完全一致 |
| 枚举扇开字段 | 4 个 contract 使用 | `kpl_list(tag), limit_list_d(limit_type,exchange), margin(exchange_id), moneyflow_ind_dc(content_type)` |
| 文档明确必选参数 | 6 个数据集出现 | 见 3.5 |

## 3.5 文档“必选参数”与 contract `required=true` 对照

文档出现必选参数（`Y`）的数据集：

1. `broker_recommend`: `month`
2. `cyq_perf`: `ts_code`
3. `daily_basic`: `ts_code`
4. `dc_index`: `idx_type`
5. `index_daily`: `ts_code`
6. `top_list`: `trade_date`

当前 contract 的 `input_schema.fields.required` 未与上述 6 项逐一对齐（均未直接标 `required=true`，更多依赖 run_profile/planner 约束与业务逻辑）。

---

## 4. 差异清单（重点）

## 4.1 `both_diff`（4 个，优先核查）

1. `hk_basic`
   - contract_only: `trade_date`
   - doc_only: `ts_code`
2. `index_basic`
   - contract_only: `trade_date`
   - doc_only: `category, market, name, publisher`
3. `trade_cal`
   - contract_only: `trade_date`
   - doc_only: `is_open`
4. `us_basic`
   - contract_only: `trade_date`
   - doc_only: `limit, offset`

## 4.2 `contract_superset`（13 个）

主要体现为 contract 比 doc 多出兼容参数或扩展参数：

- `exchange`：`adj_factor, cyq_perf, daily, fund_daily, index_daily, index_daily_basic`
- `trade_date`（doc 无时间入参的接口）：`etf_basic, etf_index, ths_index`
- `start_date/end_date`：`kpl_concept_cons, top_list`
- 其他：`dc_member(idx_type)`, `broker_recommend(trade_date,start_date,end_date)`

## 4.3 `doc_superset`（10 个）

主要体现为 doc 有但 contract 未纳入：

- `limit/offset`：`fund_adj, moneyflow, moneyflow_cnt_ths, moneyflow_dc, moneyflow_ind_dc, moneyflow_ind_ths, moneyflow_mkt_dc, moneyflow_ths, us_basic`
- 其他：`dc_index(name)`, `stk_nineturn(freq)`

---

## 5. 全量明细矩阵（38 个）

| dataset_key | api_name | 对齐判定 | contract时间参数 | doc时间参数 | contract含ts_code | doc含ts_code | contract_only | doc_only |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `adj_factor` | `adj_factor` | contract_superset | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | exchange | - |
| `block_trade` | `block_trade` | exact | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | - | - |
| `broker_recommend` | `broker_recommend` | contract_superset | `trade_date,start_date,end_date,month` | `month` | N | N | end_date, start_date, trade_date | - |
| `cyq_perf` | `cyq_perf` | contract_superset | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | exchange | - |
| `daily` | `daily` | contract_superset | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | exchange | - |
| `daily_basic` | `daily_basic` | exact | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | - | - |
| `dc_index` | `dc_index` | doc_superset | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | - | name |
| `dc_member` | `dc_member` | contract_superset | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | idx_type | - |
| `etf_basic` | `etf_basic` | contract_superset | `trade_date` | `-` | Y | Y | trade_date | - |
| `etf_index` | `etf_index` | contract_superset | `trade_date` | `-` | Y | Y | trade_date | - |
| `fund_adj` | `fund_adj` | doc_superset | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | - | limit, offset |
| `fund_daily` | `fund_daily` | contract_superset | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | exchange | - |
| `hk_basic` | `hk_basic` | both_diff | `trade_date` | `-` | N | Y | trade_date | ts_code |
| `index_basic` | `index_basic` | both_diff | `trade_date` | `-` | Y | Y | trade_date | category, market, name, publisher |
| `index_daily` | `index_daily` | contract_superset | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | exchange | - |
| `index_daily_basic` | `index_dailybasic` | contract_superset | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | exchange | - |
| `kpl_concept_cons` | `kpl_concept_cons` | contract_superset | `trade_date,start_date,end_date` | `trade_date` | Y | Y | end_date, start_date | - |
| `kpl_list` | `kpl_list` | exact | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | - | - |
| `limit_cpt_list` | `limit_cpt_list` | exact | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | - | - |
| `limit_list_d` | `limit_list_d` | exact | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | - | - |
| `limit_list_ths` | `limit_list_ths` | exact | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | - | - |
| `limit_step` | `limit_step` | exact | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | - | - |
| `margin` | `margin` | exact | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | N | N | - | - |
| `moneyflow` | `moneyflow` | doc_superset | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | - | limit, offset |
| `moneyflow_cnt_ths` | `moneyflow_cnt_ths` | doc_superset | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | - | limit, offset |
| `moneyflow_dc` | `moneyflow_dc` | doc_superset | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | - | limit, offset |
| `moneyflow_ind_dc` | `moneyflow_ind_dc` | doc_superset | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | - | limit, offset |
| `moneyflow_ind_ths` | `moneyflow_ind_ths` | doc_superset | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | - | limit, offset |
| `moneyflow_mkt_dc` | `moneyflow_mkt_dc` | doc_superset | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | N | N | - | limit, offset |
| `moneyflow_ths` | `moneyflow_ths` | doc_superset | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | - | limit, offset |
| `stk_limit` | `stk_limit` | exact | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | - | - |
| `stk_nineturn` | `stk_nineturn` | doc_superset | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | - | freq |
| `stock_st` | `stock_st` | exact | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | - | - |
| `suspend_d` | `suspend_d` | exact | `trade_date,start_date,end_date` | `trade_date,start_date,end_date` | Y | Y | - | - |
| `ths_index` | `ths_index` | contract_superset | `trade_date` | `-` | Y | Y | trade_date | - |
| `top_list` | `top_list` | contract_superset | `trade_date,start_date,end_date` | `trade_date` | Y | Y | end_date, start_date | - |
| `trade_cal` | `trade_cal` | both_diff | `trade_date,start_date,end_date` | `start_date,end_date` | N | N | trade_date | is_open |
| `us_basic` | `us_basic` | both_diff | `trade_date` | `-` | Y | Y | trade_date | limit, offset |

---

## 6. 本文输出边界

1. 本文只做“参数事实审计”，不在本文内直接下 `anchor_type` 结论。
2. 下一步讨论建议基于本审计中的三类高差异区域：
   - `both_diff` 的 4 个数据集
   - doc 含分页参数但 contract 未纳入的 9 个数据集
   - 文档“必选参数”与 contract required 未直接对齐的 6 个数据集

