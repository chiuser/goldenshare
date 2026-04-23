# 数据集接口请求策略重审 v1（逐数据集）

> 状态：历史评审文档（归档）。  
> 说明：本文用于追溯当时的全量策略评审过程，含 V1 路径引用；当前以 V2 contract 与 `sync_v2` 策略实现为准。

- 审计日期：2026-04-22
- 审计范围：`SYNC_SERVICE_REGISTRY` 全量 56 个数据集（Tushare 54 + Biying 2）
- 对照依据：
  - `docs/sources/tushare/docs_index.csv` 与对应接口文档
  - `docs/datasets/biying-*.md`（Biying 两个数据集）
  - `src/foundation/services/sync/registry.py`
  - `src/foundation/services/sync_v2/*`（contract/planner/worker_client）
- 本文目标：逐数据集给出“效率优先”的推荐请求策略，作为后续代码评审与改造基线。

---

## 1. 先固定的口径（本轮沿用）

1. 大多数接口若支持 `limit/offset`，优先采用分页策略，避免截断。
2. `index_daily / index_weekly / index_monthly` 继续沿用你定制的“active 指数池”策略。
3. `trade_date` 语义固定为交易日；周/月类锚点固定为周/月最后交易日（仅周期栏族）。
4. 效率优先原则：默认先选“请求次数更少且覆盖完整”的策略；只有在存在截断风险时才增加 fanout 维度。

---

## 2. 请求策略模板（Strategy Code）

| Code | 模板名 | 核心语义 |
| --- | --- | --- |
| `S01` | 快照刷新 | 无时间锚点，默认全量单窗；仅显式筛选时带过滤参数。 |
| `S02` | 交易日点式 | `trade_date` 点式请求；默认全市场，`ts_code` 只用于定向补数。 |
| `S03` | 交易日 + 枚举扇出 | `trade_date` 点式 + 必需枚举维度（如 `exchange_id`、`limit_type`、`content_type`）。 |
| `S04` | 指数池定制 | 按 active 指数池 fanout，再走 `trade_date` 或 `start/end`。 |
| `S05` | 月键快照 | `month=YYYYMM`。 |
| `S06` | 低频事件 | 按事件日期字段（如 `ann_date`）或按 `ts_code` 回补。 |
| `S07` | 周/月末锚点 | 仅周末/月末交易日触发请求。 |
| `S08` | 自然月区间 + 指数扇出 | 当月自然日窗口（1日~月末）+ `index_code` fanout。 |
| `S09` | 板块池兜底策略 | 优先“日期单窗全量”；如存在截断风险再按板块代码 fanout。 |
| `S10` | 东财板块行情专用 | `trade_date + idx_type(概念/行业/地域)` 扇出，避免 `ts_code` 全扇出。 |
| `S11` | Biying 证券分窗 | 按 `dm` fanout + 日期窗口分片。 |
| `S12` | 日历区间单窗 | 自然日 `start/end` 单窗请求（必要时分页）。 |

---

## 3. 策略分布总览（56）

| Strategy | 数据集数 |
| --- | ---: |
| `S01` | 7 |
| `S02` | 25 |
| `S03` | 6 |
| `S04` | 3 |
| `S05` | 1 |
| `S06` | 2 |
| `S07` | 4 |
| `S08` | 1 |
| `S09` | 3 |
| `S10` | 1 |
| `S11` | 2 |
| `S12` | 1 |

---

## 4. 逐数据集请求策略（全量 56）

> 列说明：  
> `文档时间形态` 来自接口文档输入参数；  
> `文档分页` 仅表示文档是否显式写了 `limit/offset`。

| 数据集 | 源 | API | 文档时间形态 | 文档分页 | 推荐主策略 | 推荐 history/backfill 策略 |
| --- | --- | --- | --- | --- | --- | --- |
| `adj_factor` | `tushare` | `adj_factor` | `trade_date+range` | `limit+offset` | `S02` 交易日点式，全市场优先。 | `trade_date` 枚举回补，每交易日 1 unit。 |
| `biying_equity_daily` | `biying` | `equity_daily_bar` | `none` | `lt(无offset)` | `S11` 按 `dm` + `adj_type` + 日期窗口分片。 | 全历史走 `start/end` 分窗，增量走当日窗。 |
| `biying_moneyflow` | `biying` | `moneyflow` | `none` | `lt(无offset)` | `S11` 按 `dm` + 日期窗口分片。 | 全历史走 `start/end` 分窗，增量走当日窗。 |
| `block_trade` | `tushare` | `block_trade` | `trade_date+range` | `limit+offset` | `S02` 交易日点式，全市场优先。 | `trade_date` 枚举回补；`ts_code` 仅补数。 |
| `broker_recommend` | `tushare` | `broker_recommend` | `month_key` | `limit+offset` | `S05` 月键快照（`YYYYMM`）。 | 按 month 序列回补。 |
| `cyq_perf` | `tushare` | `cyq_perf` | `trade_date+range` | `limit+offset` | `S02` 交易日点式，全市场优先。 | `trade_date` 枚举回补。 |
| `daily` | `tushare` | `daily` | `trade_date+range` | `limit+offset` | `S02` 交易日点式，全市场优先。 | `trade_date` 枚举回补。 |
| `daily_basic` | `tushare` | `daily_basic` | `trade_date+range` | `limit+offset` | `S02` 交易日点式，全市场优先。 | `trade_date` 枚举回补。 |
| `dc_daily` | `tushare` | `dc_daily` | `trade_date+range` | `limit+offset` | `S10`：`trade_date × idx_type(3)`，不做 `ts_code` 全扇出。 | `trade_date` 枚举 × `idx_type`，每窗分页。 |
| `dc_hot` | `tushare` | `dc_hot` | `trade_date_only` | `limit+offset` | `S03`，但默认先单请求（不带枚举）；仅需细分时扇出。 | `trade_date` 枚举；枚举维度按需打开。 |
| `dc_index` | `tushare` | `dc_index` | `trade_date+range` | `limit+offset` | `S02` 交易日点式，全量优先。 | `trade_date` 枚举回补。 |
| `dc_member` | `tushare` | `dc_member` | `trade_date+range` | `limit+offset` | `S09`：优先日期单窗全量，截断风险时再按板块代码 fanout。 | 区间单窗优先；高水位时切换板块 fanout。 |
| `dividend` | `tushare` | `dividend` | `event_date` | `limit+offset` | `S06` 低频事件；优先 `ts_code` fanout。 | 全历史按 `ts_code` fanout；增量按 `ann_date` 水位。 |
| `etf_basic` | `tushare` | `etf_basic` | `none` | `limit+offset` | `S01` 快照刷新。 | snapshot_refresh；可按筛选参数局部刷新。 |
| `etf_index` | `tushare` | `etf_index` | `none` | `limit+offset` | `S01` 快照刷新。 | snapshot_refresh；可按筛选参数局部刷新。 |
| `fund_adj` | `tushare` | `fund_adj` | `trade_date+range` | `limit+offset` | `S02` 交易日点式；区间场景允许 `start/end`。 | `trade_date` 枚举回补（或区间单窗+分页）。 |
| `fund_daily` | `tushare` | `fund_daily` | `trade_date+range` | `limit+offset` | `S02` 交易日点式，全市场优先。 | `trade_date` 枚举回补。 |
| `hk_basic` | `tushare` | `hk_basic` | `none` | `limit+offset` | `S01` 快照刷新。 | snapshot_refresh。 |
| `index_basic` | `tushare` | `index_basic` | `none` | `limit+offset` | `S01` 快照刷新。 | snapshot_refresh。 |
| `index_daily` | `tushare` | `index_daily` | `trade_date+range` | `limit+offset` | `S04`（固定）：active 指数池 fanout。 | active 指数池 × 日期窗口。 |
| `index_daily_basic` | `tushare` | `index_dailybasic` | `trade_date+range` | `limit+offset` | `S02` 交易日点式。 | `trade_date` 枚举回补。 |
| `index_monthly` | `tushare` | `index_monthly` | `trade_date+range` | `limit+offset` | `S04`（固定）：active 指数池 fanout。 | active 指数池 × 月线窗口。 |
| `index_weekly` | `tushare` | `index_weekly` | `trade_date+range` | `limit+offset` | `S04`（固定）：active 指数池 fanout。 | active 指数池 × 周线窗口。 |
| `index_weight` | `tushare` | `index_weight` | `trade_date+range` | `limit+offset` | `S08`：自然月区间 + `index_code` fanout。 | 按月窗口枚举，再按指数代码 fanout。 |
| `kpl_concept_cons` | `tushare` | `kpl_concept_cons` | `trade_date_only` | `limit+offset` | `S02` 交易日点式。 | `trade_date` 枚举回补。 |
| `kpl_list` | `tushare` | `kpl_list` | `trade_date+range` | `limit+offset` | `S03`，默认先单请求，`tag` 仅在显式要求时扇出。 | `trade_date` 枚举，`tag` 按需扇出。 |
| `limit_cpt_list` | `tushare` | `limit_cpt_list` | `trade_date+range` | `limit+offset` | `S02` 交易日点式。 | `trade_date` 枚举回补。 |
| `limit_list_d` | `tushare` | `limit_list_d` | `trade_date+range` | `limit+offset` | `S03`：`trade_date × exchange × limit_type`。 | 交易日枚举 × 组合扇出。 |
| `limit_list_ths` | `tushare` | `limit_list_ths` | `trade_date+range` | `limit+offset` | `S02` 默认单请求；`limit_type/market` 仅按需带入。 | `trade_date` 枚举回补。 |
| `limit_step` | `tushare` | `limit_step` | `trade_date+range` | `limit+offset` | `S02` 交易日点式。 | `trade_date` 枚举回补。 |
| `margin` | `tushare` | `margin` | `trade_date+range` | `limit+offset` | `S03`：`trade_date × exchange_id`（SSE/SZSE/BSE）。 | 交易日枚举 × 交易所扇出。 |
| `moneyflow` | `tushare` | `moneyflow` | `trade_date+range` | `limit+offset` | `S02` 交易日点式，全市场优先。 | `trade_date` 枚举回补。 |
| `moneyflow_cnt_ths` | `tushare` | `moneyflow_cnt_ths` | `trade_date+range` | `limit+offset` | `S02` 交易日点式，全市场优先。 | `trade_date` 枚举回补。 |
| `moneyflow_dc` | `tushare` | `moneyflow_dc` | `trade_date+range` | `limit+offset` | `S02` 交易日点式，全市场优先。 | `trade_date` 枚举回补。 |
| `moneyflow_ind_dc` | `tushare` | `moneyflow_ind_dc` | `trade_date+range` | `limit+offset` | `S03`：`trade_date × content_type(行业/概念/地域)`。 | 交易日枚举 × `content_type` 扇出。 |
| `moneyflow_ind_ths` | `tushare` | `moneyflow_ind_ths` | `trade_date+range` | `limit+offset` | `S02` 交易日点式，全市场优先。 | `trade_date` 枚举回补。 |
| `moneyflow_mkt_dc` | `tushare` | `moneyflow_mkt_dc` | `trade_date+range` | `limit+offset` | `S02` 交易日点式。 | `trade_date` 枚举回补。 |
| `moneyflow_ths` | `tushare` | `moneyflow_ths` | `trade_date+range` | `limit+offset` | `S02` 交易日点式，全市场优先。 | `trade_date` 枚举回补。 |
| `stk_factor_pro` | `tushare` | `stk_factor_pro` | `trade_date+range` | `limit+offset` | `S02`：优先按交易日全市场拉取，不建议按 `ts_code` 全扇出。 | `trade_date` 枚举回补。 |
| `stk_holdernumber` | `tushare` | `stk_holdernumber` | `range_only` | `limit+offset` | `S06` 低频事件；按 `ts_code + start/end`。 | 优先 `ts_code` fanout + 区间回补。 |
| `stk_limit` | `tushare` | `stk_limit` | `trade_date+range` | `limit+offset` | `S02` 交易日点式，全市场优先。 | `trade_date` 枚举回补。 |
| `stk_nineturn` | `tushare` | `stk_nineturn` | `trade_date+range` | `limit+offset` | `S02` 交易日点式，`freq=daily` 固定。 | `trade_date` 枚举回补。 |
| `stk_period_bar_adj_month` | `tushare` | `stk_week_month_adj` | `trade_date+range` | `limit+offset` | `S07` 月末交易日锚点。 | 仅月末锚点日期回补。 |
| `stk_period_bar_adj_week` | `tushare` | `stk_week_month_adj` | `trade_date+range` | `limit+offset` | `S07` 周末交易日锚点。 | 仅周末锚点日期回补。 |
| `stk_period_bar_month` | `tushare` | `stk_weekly_monthly` | `trade_date+range` | `limit+offset` | `S07` 月末交易日锚点。 | 仅月末锚点日期回补。 |
| `stk_period_bar_week` | `tushare` | `stk_weekly_monthly` | `trade_date+range` | `limit+offset` | `S07` 周末交易日锚点。 | 仅周末锚点日期回补。 |
| `stock_basic` | `tushare` | `stock_basic` | `none` | `limit+offset` | `S01` 快照刷新（Tushare: `list_status=L,D,P,G`；Biying 独立快照）。 | snapshot_refresh。 |
| `stock_st` | `tushare` | `stock_st` | `trade_date+range` | `limit+offset` | `S02` 交易日点式。 | `trade_date` 枚举回补。 |
| `suspend_d` | `tushare` | `suspend_d` | `trade_date+range` | `limit+offset` | `S02` 交易日点式。 | `trade_date` 枚举回补。 |
| `ths_daily` | `tushare` | `ths_daily` | `trade_date+range` | `limit+offset` | `S09`：优先日期单窗全量（不先做板块全扇出）。 | 区间单窗优先；检测截断后再板块 fanout。 |
| `ths_hot` | `tushare` | `ths_hot` | `trade_date_only` | `limit+offset` | `S03`，默认单请求；按需再启用 `market/is_new` 枚举。 | `trade_date` 枚举，枚举维度按需开启。 |
| `ths_index` | `tushare` | `ths_index` | `none` | `limit+offset` | `S01` 快照刷新。 | snapshot_refresh。 |
| `ths_member` | `tushare` | `ths_member` | `none` | `limit+offset` | `S09`：优先单窗全量；截断风险时按板块 fanout。 | snapshot/区间回补优先单窗，必要时切 fanout。 |
| `top_list` | `tushare` | `top_list` | `trade_date_only` | `limit+offset` | `S02` 交易日点式。 | `trade_date` 枚举回补。 |
| `trade_cal` | `tushare` | `trade_cal` | `range_only` | `limit+offset` | `S12` 自然日区间单窗。 | `start/end` 单窗回补（必要时分页）。 |
| `us_basic` | `tushare` | `us_basic` | `none` | `limit+offset` | `S01` 快照刷新（建议 `classify` 分类拉取 + 分页）。 | snapshot_refresh。 |

---

## 5. 分页能力复核结果（2026-04-22）

按 2026-04-22 最新源文档复核，当前纳入评估的 `tushare` 数据集中，文档均已显式给出 `limit/offset`。  
因此本轮不再保留“文档未写分页能力”的待确认清单。

---

## 6. 关键结论（面向后续代码评审）

1. 当前最大效率风险点不在“是否有 contract”，而在“是否过早全量 fanout”（典型是板块族）。
2. 板块族建议统一改成“先单窗全量，再按截断风险兜底 fanout”。
3. 你定制的指数池逻辑应继续保持，不应回退到全市场无约束模式。
4. `stk_factor_pro` 建议默认走交易日全市场，不走 `ts_code` 全扇出。
5. 低频事件类（`dividend`、`stk_holdernumber`）不应套用日频增量心智，应独立事件水位策略。

---

## 7. 下一步建议

1. 先按本文件对照代码做“现实现状差异表”（仅审计，不改代码）。
2. 再按本文件逐数据集把分页能力明确落回 contract（含分页默认值与翻页终止条件）。
3. 最后按数据集批次改造请求策略，并做单数据集切换验证（切换前后对账）。
