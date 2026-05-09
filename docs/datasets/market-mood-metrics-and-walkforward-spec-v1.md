# A股市场温度/情绪与 Walk-forward 指标口径说明 v1

状态：当前有效（代码实现口径）。

实现对应：

1. [market_mood_calculator.py](/Users/congming/github/goldenshare/src/biz/services/market_mood_calculator.py)
2. [market_mood_walkforward_validation_service.py](/Users/congming/github/goldenshare/src/biz/services/market_mood_walkforward_validation_service.py)

---

## 1. 适用范围

本说明覆盖 4 组输出：

1. 市场温度（`temperature`）
2. 市场情绪（`emotion`）
3. 诊断与分层信息（`diagnostics`）
4. Walk-forward 验证层（训练/验证/测试、概率、策略建议、评估指标）

默认关键参数：

1. `sample_threshold=5`
2. `tick=0.01`
3. `board_lookback_days=120`
4. `theme_min_members=10`

---

## 2. 基础样本池与预处理口径

### 2.1 交易日与窗口

1. 交易日来自 `core.trade_calendar`，`exchange='SSE'` 且 `is_open=true`。
2. 目标日必须是交易日；否则直接报错。
3. 高位崩塌率要求至少有 21 个历史交易日，否则报错。

### 2.2 股票样本筛选（eligible universe）

基于 `core_serving.equity_daily_bar` 联合 `security_serving`、`core.equity_stk_limit`、`core.equity_stock_st`、`core.equity_suspend_d`：

1. 仅保留 `security_type='EQUITY'` 且 `exchange in ('SSE','SZSE')`。
2. 上市满 20 个交易日：
   当前交易日 `t` 的门槛日是 `t-19` 交易日，要求 `list_date <= 门槛日`。
3. 剔除 ST：`equity_stock_st.type='ST'` 当日命中即剔除。
4. 剔除停牌：`equity_suspend_d` 当日命中即剔除。
5. 必须有 `close` 和非零 `pre_close`。
6. 必须能计算非零涨跌停幅：`limit_pct > 0`。

### 2.3 基础派生字段

对每只 eligible 股票在日 `t`：

1. 日收益率：`r = close / pre_close - 1`
2. 涨跌停幅：`limit_pct = up_limit / base_pre_close - 1`
3. `base_pre_close` 优先取 `stk_limit.pre_close`，为空或 0 时回退到 `daily.pre_close`
4. `close_up`: `close >= up_limit - tick`
5. `close_down`: `close <= down_limit + tick`
6. `touch_up`: `high >= up_limit - tick`
7. 一字板 `oneword_up`: `open/high/low/close` 均在 `up_limit ± tick`
8. 可交易涨停 `tradable_up`: `close_up && !oneword_up`
9. 可交易触板 `tradable_touch_up`: `touch_up && low < up_limit - tick`
10. 炸板 `blast`: `tradable_touch_up && !close_up`
11. 桶分层：
    `10cm` 当 `0.095 <= limit_pct <= 0.105`
12. 桶分层：
    `20cm` 当 `0.195 <= limit_pct <= 0.205`

---

## 3. 市场温度（temperature）指标口径

### 3.1 指标定义

1. `universe_size`: 当日 eligible 股票数量。
2. `red_rate`: `red_count / universe_size`，其中 `red_count = count(r > 0)`。
3. `median_return`: eligible 股票 `r` 的中位数。
4. `strong3_rate`: `count(r >= 0.03) / universe_size`。
5. `weak3_rate`: `count(r <= -0.03) / universe_size`。
6. `market_amount`: eligible 股票 `amount` 求和。
7. `market_amount_ratio_20`:
   `market_amount_today / median(market_amount of previous 20 trade days)`。
8. `small_vs_large`:
   `index_return(中证1000) - index_return(沪深300)`。
9. `top3_mainlines`: 概念主线评分前三名列表（见 3.2）。
10. `mainline_concentration`: 前三主线成分股并集成交额 / 全市场成交额。
11. `limit_down_rate`: `count(close_down) / universe_size`。
12. `high_collapse_rate`: 高位池崩塌占比（见 3.3）。

### 3.2 主线识别（top3_mainlines）

主题来自：

1. `core.dc_index` 中 `idx_type='概念板块'`
2. `core.dc_member` 映射主题成分股

计算窗口：`trade_date` 的前 20 交易日 + 当天。

对每个主题在当天：

1. `member_count`: 当天匹配到 eligible 的成分股数量。
2. `theme_return`: 成分股 `r` 的中位数。
3. `theme_red_rate`: 成分股红盘占比。
4. `theme_amount`: 成分股成交额求和。
5. `theme_amount_ratio`:
   `theme_amount_today / median(theme_amount of previous window days)`。

准入条件：

1. `member_count >= theme_min_members`（默认 10）
2. 历史金额样本长度大于 1，且满足样本阈值校验
3. `theme_return/theme_red_rate/theme_amount_ratio` 都非空

评分：

1. 先对全部候选主题做百分位排名，范围 0~100，平局取平均位次。
2. `theme_score = 0.4*rank(theme_return) + 0.3*rank(theme_red_rate) + 0.3*rank(theme_amount_ratio)`。
3. 按 `theme_score` 降序取前 3。

### 3.3 高位崩塌率（high_collapse_rate）

1. 先计算每只股票 20 日复权收益：
   `ret20 = (close_t-1 * adj_factor_t-1) / (close_t-21 * adj_factor_t-21) - 1`。
2. 按 `ret20` 降序，取前 10% 为高位池（向上取整，至少 1 只）。
3. 当日在高位池中统计：
   `collapse = count(r <= -0.7 * limit_pct)`。
4. `high_collapse_rate = collapse / valid_high_pool_count`。

输出中的两个辅助量：

1. `high_pool_size`: 可计算 `ret20` 的股票数。
2. `high_pool_effective_size`: 高位池中当天可有效判断崩塌的股票数（分母）。

---

## 4. 市场情绪（emotion）指标口径

### 4.1 主指标

1. `universe_size`: 与 temperature 相同。
2. `tradable_up_count`: `count(tradable_up)`。
3. `tradable_up_rate`: `tradable_up_count / universe_size`。
4. `seal_success_rate`: `tradable_up_count / tradable_touch_up_count`。
5. `blast_rate`: `blast_count / tradable_touch_up_count`。
6. `board2plus_count`: 连板数 `>=2` 的股票数（见 4.2）。
7. `board2plus_rate`: `board2plus_count / universe_size`。
8. `max_board`: 当日最高连板数。
9. `advance_rate`:
   前一日 `close_up` 股票中，当日继续 `close_up` 的占比。
10. `open_premium`:
    前一日 `tradable_up` 样本上，当日 `(open/prev_close -1)` 的中位数。
11. `close_premium`:
    前一日 `tradable_up` 样本上，当日 `(close/prev_close -1)` 的中位数。
12. `big_loss_rate`:
    `tradable_touch_up` 样本中，`r <= -0.3 * limit_pct` 的占比。
13. `high_board_break_kill_rate`:
    前一日连板 `>=2` 样本中，当日“非涨停且收跌”的占比。

### 4.2 连板序列计算

在 `board_lookback_days` 窗口内逐日滚动：

1. 当日 `close_up`：`streak_t = streak_t-1 + 1`
2. 当日非 `close_up`：`streak_t = 0`

由此得到 `board2plus_count` 和 `max_board`。

### 4.3 10cm / 20cm 分层与 `msi10`、`msi20`

分别在 10cm 和 20cm 样本池上计算：

1. `tradable_up_rate`
2. `seal_success_rate`
3. `advance_rate`
4. `close_premium`

子分数：

1. `msi_bucket = 0.30*(tradable_up_rate*100) + 0.25*(seal_success_rate*100) + 0.20*(advance_rate*100) + 0.25*(close_premium*100)`。

结构标签 `structure_tag`：

1. 两个都空：`None`
2. 仅一侧非空：`样本不足`
3. `msi10 - msi20 >= 10`：`10cm主导`
4. `msi20 - msi10 >= 10`：`20cm主导`
5. 差值绝对值 `<10` 且两侧都 `>=30`：`双线共振`
6. 其余按大小关系：
   `msi20 > msi10` 为 `接力弱，弹性强`，反之 `接力强，弹性一般`，相等为 `双线均衡`

---

## 5. Diagnostics（诊断与分层信息）口径

输出字段：

1. `prev_trade_date`: 前一交易日。
2. `ret20_base_date`: 20 日收益回看基准日（`t-21` 交易日）。
3. `sample_threshold`: 样本阈值（默认 5）。
4. `theme_day_coverage`: 在“前20日+当天”窗口内，概念主题数据非空的交易日数量。
5. `high_pool_size`: 可计算 20 日复权收益的股票数量。
6. `high_pool_effective_size`: 当天高位崩塌分母有效样本数。
7. `index_returns`: 10 个基准指数当日收益。
8. `bucket_stats`: 10cm/20cm 分桶统计，包含：
   `sample_size/tradable_up_rate/seal_success_rate/advance_rate/close_premium/msi`。

---

## 6. Walk-forward 验证层口径

### 6.1 可用日期集合（common trade dates）

按交易日历筛选开市日，并要求以下数据在该日都存在：

1. `core_serving.equity_daily_bar`
2. `core.equity_stk_limit`
3. `core_serving.equity_adj_factor`
4. `core_serving.equity_daily_basic`
5. `core_serving.index_daily_serving`
6. `core.dc_index`（`idx_type='概念板块'`）
7. `core.dc_member`

### 6.2 三个评分（MTI / MSI / RSK）

归一化函数：

1. 正向：`n_pos(x, lo, hi)=clip((x-lo)/(hi-lo),0,1)`
2. 反向：`n_neg=1-n_pos`
3. 空值：按 `0.5` 处理

`MTI`（0~100）：

1. `100 * (0.18*red_rate + 0.16*median_return + 0.10*strong3_rate + 0.10*(1-weak3_rate) + 0.12*market_amount_ratio_20 + 0.08*small_vs_large + 0.10*mainline_concentration + 0.08*(1-limit_down_rate) + 0.08*(1-high_collapse_rate))`
2. 上式中的每项均先做区间归一化：
   `red_rate[0.35,0.85]`
3. 上式中的每项均先做区间归一化：
   `median_return[-0.03,0.03]`
4. 上式中的每项均先做区间归一化：
   `strong3_rate[0,0.25]`
5. 上式中的每项均先做区间归一化：
   `weak3_rate[0,0.15]`（反向）
6. 上式中的每项均先做区间归一化：
   `market_amount_ratio_20[0.80,1.40]`
7. 上式中的每项均先做区间归一化：
   `small_vs_large[-0.03,0.03]`
8. 上式中的每项均先做区间归一化：
   `mainline_concentration[0,0.20]`
9. 上式中的每项均先做区间归一化：
   `limit_down_rate[0,0.03]`（反向）
10. 上式中的每项均先做区间归一化：
    `high_collapse_rate[0,0.12]`（反向）

`MSI`（0~100）：

1. `100 * (0.18*tradable_up_rate + 0.16*seal_success_rate + 0.12*(1-blast_rate) + 0.10*board2plus_rate + 0.10*max_board + 0.12*advance_rate + 0.10*close_premium + 0.07*(1-big_loss_rate) + 0.05*(1-high_board_break_kill_rate))`
2. 归一化区间依次为：
   `tradable_up_rate[0,0.06]`、`seal_success_rate[0.40,1.00]`、`blast_rate[0,0.60]`（反向）、`board2plus_rate[0,0.03]`、`max_board[0,8]`、`advance_rate[0,0.50]`、`close_premium[-0.03,0.05]`、`big_loss_rate[0,0.40]`（反向）、`high_board_break_kill_rate[0,0.60]`（反向）

`RSK`（0~100）：

1. `100 * (0.40*high_collapse_rate + 0.35*blast_rate + 0.25*limit_down_rate)`
2. 归一化区间：
   `high_collapse_rate[0,0.20]`、`blast_rate[0,0.60]`、`limit_down_rate[0,0.04]`

### 6.3 标签定义（next-day labels）

对样本日 `t`，标签来自 `t+1`：

1. `y_temp_cont = 1{ MTI_{t+1} >= MTI_t - delta_temp }`
2. `y_emo_cont = 1{ MSI_{t+1} >= MSI_t - delta_emotion }`
3. `y_env_continue = 1{ y_temp_cont==1 and y_emo_cont==1 }`
4. `y_mainline_expand = 1{ mainline_concentration_{t+1} >= mainline_concentration_t - 0.005 }`（任一侧空值则标签空）
5. `y_risk_event`：
   在 `t+1` 处，对过去最多 252 天历史分别求 `high_collapse_rate/blast_rate/limit_down_rate` 的 80% 分位数（每项样本至少 20），若 `t+1` 任一指标超各自阈值则为 1，否则 0
6. 回归观测量：
   `y_red_next = red_rate_{t+1}`，`y_tradable_up_next = tradable_up_rate_{t+1}`

### 6.4 概率模型（分桶分层回退）

特征状态键：

1. `mti_bucket`：`<40 low`，`[40,65) mid`，`>=65 high`
2. `msi_bucket`：`<35 low`，`[35,70) mid`，`>=70 high`
3. `rsk_bucket`：`<45 low`，`[45,65) mid`，`>=65 high`
4. `d_mti` 与 `d_msi`：增减符号（1/0/-1）

4 级回退键：

1. `(mti_bucket, msi_bucket, rsk_bucket, d_mti, d_msi)`
2. `(mti_bucket, msi_bucket, rsk_bucket)`
3. `(mti_bucket, msi_bucket)`
4. `(mti_bucket,)`

预测概率：

1. 每级要求最小样本：
   `L1=min_state_samples`、`L2=max(15,min_state_samples/2)`、`L3=max(10,min_state_samples/3)`、`L4=5`
2. 命中后使用平滑：
   `p = (positives + global_rate*5) / (total + 5)`
3. 若全部级别都不达标，回退到 `global_rate`

### 6.5 Walk-forward 切分

第 `k` 折（从 0 开始）：

1. `train_end = train_days + k*roll_days`
2. `valid = [train_end, train_end + valid_days)`
3. `test = [valid_end, valid_end + test_days)`
4. 当 `test_end > sample_size` 停止

### 6.6 策略建议输出

概率：

1. `p_env_continue`
2. `p_mainline_expand`
3. `p_risk_event`

仓位建议：

1. `base_exposure = clip(0.15 + 0.45*p_env + 0.20*p_main - 0.50*p_risk, 0, 0.80)`
2. 按 playbook 上限截断：
   `A0=0.20`、`A1=0.50`、`A2=0.70`、`A3=0.35`、`A4=0.30`

playbook 规则（按顺序命中）：

1. 若 `p_risk>=0.60` 或 `RSK>=70`：
   `MTI>=55 -> A4`，否则 `A0`
2. 若 `MTI>=65 且 35<=MSI<75 且 p_env>=0.55 且 p_risk<0.35`：
   `A2`
3. 若 `MTI>=60 且 MSI<45`：
   `A1`
4. 若 `MTI<50 且 MSI>=60 且 p_risk<0.40`：
   `A3`
5. 若 `MTI>=75 且 MSI>=75 且 RSK>=60`：
   `A4`
6. 否则：
   `MTI>=50 -> A1`，否则 `A0`

追涨开关：

1. `allow_chase = (55<=MSI<=75) && (RSK<60) && (p_risk<0.35)`

说明：

1. 当前规则引擎中 `p_main` 未直接参与分支判断，仅参与仓位线性组合。

### 6.7 评估指标

每折输出：

1. `env_brier`、`main_brier`、`risk_brier`
2. `mti_red_rank_ic`（Spearman: `MTI` vs `next_red_rate`）
3. `msi_tradable_up_rank_ic`（Spearman: `MSI` vs `next_tradable_up_rate`）

全局聚合：

1. 上述 5 项在全体测试点的聚合版本
2. `avg_recommended_exposure`
3. `playbook_distribution`（A0~A4 次数分布）

---

## 7. 空值与“样本不足”规则

统一规则：

1. 比率类若分母 `< sample_threshold` 或分母 `<=0`，返回 `None`。
2. 中位数类若样本 `< sample_threshold`，返回 `None`。
3. `safe_ratio` 若 `count < min_count`、分母空或 0，返回 `None`。
4. Walk-forward 评分层对空值默认归一化为 `0.5`，用于保持连续计算。

---

## 8. 当前已知边界

1. `trade_calendar` 目前按 `exchange='SSE'` 驱动交易日窗口。
2. 股票样本仅含沪深 A 股（`SSE/SZSE`），不含北交所与港美股。
3. `high_collapse_rate` 的高位池来自“前一日相对 20 日前”的复权收益排序，不是更长周期高位定义。
4. Walk-forward 中 `valid` 片段当前仅用于时序切分，不参与显式调参搜索。
