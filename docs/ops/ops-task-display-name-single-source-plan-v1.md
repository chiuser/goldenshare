# Ops 任务显示名单一事实源收口方案 v1

> 状态：待评审  
> 适用范围：任务记录、任务详情、今日任务、自动任务、手动任务入口中涉及 `spec_key/spec_display_name/display_name/resource_display_name` 的展示链路。  
> 本文档先冻结命名规则与审计清单；评审通过前不直接推进代码改造。

## 1. 背景

`sync_minute_history.stk_mins` 在任务详情页显示为：

```text
任务 / 未配置显示名称（stk_mins）
```

直接原因是前端 `formatSpecDisplayLabel(spec_key, spec_display_name)` 在遇到 `prefix.resource` 形式的 `spec_key` 时，优先按前端静态映射拼接：

```text
specPrefixLabelMap[prefix] / resourceLabelMap[resource]
```

而不是优先使用后端返回的 `spec_display_name`。

但当前后端 `JobSpec.display_name` 也并非全部可靠。实查发现：

```text
sync_minute_history.stk_mins => 分钟行情同步 / 股票历史分钟行情
sync_daily.daily => 日常同步 / daily
backfill_by_date_range.kpl_list => 按日期区间回补 / kpl_list
daily_market_close_sync => 每日收盘后同步
```

因此不能简单改成“前端无条件后端优先”。正确收口顺序应是：

1. 先把后端 `JobSpec/WorkflowSpec` 展示名质量补齐。
2. 再把前端改成后端展示名优先。
3. 前端静态映射只作为旧数据/异常数据兼容兜底。
4. 用测试门禁阻止 `未配置显示名称`、裸 `resource_key` 再进入正常页面。

## 2. 目标

1. 后端成为任务显示名的单一事实源。
2. 前端不再在正常路径复制任务命名规则。
3. 所有用户可见任务名称必须是中文业务名称，不暴露 `daily/kpl_list/stk_mins` 这类内部 key。
4. 新增数据集时，显示名缺失必须被测试或门禁拦住，而不是等页面暴雷。

## 3. 非目标

1. 本轮不改变任务执行路径、调度语义、`spec_key` 稳定性。
2. 本轮不改 `JobExecution.spec_key` 历史数据。
3. 本轮不重命名数据库字段或 API 字段。
4. 本轮不要求删除前端 `resourceLabelMap`，只把它降级为兼容兜底。

## 4. 单一事实源规则

### 4.1 后端命名规则

所有 `JobSpec.display_name` 必须遵守：

```text
<执行类型中文名> / <资源中文名>
```

示例：

```text
日常同步 / 股票日线
历史同步 / 股票日线
按交易日回补 / 东方财富热榜
分钟行情同步 / 股票历史分钟行情
```

资源中文名来源优先级：

1. `DatasetFreshnessSpec.display_name`
2. 若无 freshness spec，则显式维护人工名称
3. 禁止直接使用 `resource_key` 作为用户展示名

### 4.2 前端显示规则

前端展示任务名时必须遵守：

```text
1. 优先使用后端返回的 spec_display_name/display_name
2. 后端缺失时，使用前端兼容映射推导
3. 推导失败时，显示原始 spec_key
4. 正常用户界面不得出现“未配置显示名称”
```

建议目标实现：

```ts
export function formatSpecDisplayLabel(
  specKey: string | null | undefined,
  specDisplayName: string | null | undefined,
): string {
  const displayName = normalizeKey(specDisplayName);
  if (displayName) {
    return displayName;
  }

  // 后端缺失时才进入前端兼容推导。
}
```

## 5. 改造阶段

### P0：冻结命名清单

1. 评审本文第 7 节命名审计表。
2. 对“待人工命名”的维护任务给出最终中文名。
3. 确认是否接受统一格式 `<执行类型中文名> / <资源中文名>`。

### P1：后端命名收口

1. 修改 `src/ops/specs/registry.py` 的批量生成逻辑，让 `display_name` 使用 `DatasetFreshnessSpec.display_name`。
2. 单独处理无 freshness spec 的 maintenance 任务。
3. 更新后端测试：
   - 所有 `JobSpec.display_name` 非空。
   - 对 `prefix.resource`，若 resource 有 `DatasetFreshnessSpec`，展示名不得包含裸 `resource_key`。
   - `sync_minute_history.stk_mins` 必须返回 `分钟行情同步 / 股票历史分钟行情`。

### P2：前端后端优先

1. 修改 `frontend/src/shared/ops-display.ts`：
   - `formatSpecDisplayLabel` 先返回 `specDisplayName`。
   - 只有 `specDisplayName` 缺失才使用前端映射。
   - 未知 key 兜底显示 `spec_key`，不显示“未配置显示名称”。
2. 更新前端测试：
   - 后端有显示名时必须优先使用后端值。
   - 后端缺失时继续兼容旧 key。
   - 未知 key 不出现“未配置显示名称”。

### P3：文档与模板门禁

1. 更新 `docs/templates/dataset-development-template.md`：
   - 新增数据集必须填写任务显示名影响面。
   - 若会进入 Ops 任务页，必须验证 `spec_display_name`、manual action `display_name/resource_display_name`。
2. 更新前端/ops 相关文档：
   - 前端不维护正常路径任务命名单一事实源。
   - 前端静态映射仅为兼容兜底。

## 6. 需要评审拍板

| 编号 | 决策项 | 建议值 |
| --- | --- | --- |
| D1 | 任务显示名统一格式 | `<执行类型中文名> / <资源中文名>` |
| D2 | `backfill_fund_series.*` 前缀 | `基金按交易日回补` |
| D3 | `maintenance.rebuild_dm` 展示名 | `维护动作 / 数据集市刷新` |
| D4 | `maintenance.rebuild_index_kline_serving` 展示名 | `维护动作 / 指数K线服务层重建` |
| D5 | 前端未知 key 兜底 | 显示原始 `spec_key`，不显示“未配置显示名称” |

## 7. 名称审计表

说明：

1. 仅列出当前不合理或建议调整的 `JobSpec.display_name`。
2. 未列出的 WorkflowSpec 当前显示名可接受。
3. `sync_minute_history.stk_mins` 已是目标口径，不再列入待改清单。

| spec_key | 当前显示名 | 建议显示名 |
| --- | --- | --- |
| `backfill_by_date_range.dc_daily` | `按日期区间回补 / dc_daily` | `按日期区间回补 / 东方财富板块行情` |
| `backfill_by_date_range.dc_index` | `按日期区间回补 / dc_index` | `按日期区间回补 / 东方财富概念板块` |
| `backfill_by_date_range.kpl_list` | `按日期区间回补 / kpl_list` | `按日期区间回补 / 开盘啦榜单` |
| `backfill_by_date_range.ths_daily` | `按日期区间回补 / ths_daily` | `按日期区间回补 / 同花顺板块行情` |
| `backfill_by_month.broker_recommend` | `按月份回补 / broker_recommend` | `按月份回补 / 券商每月荐股` |
| `backfill_by_trade_date.block_trade` | `按交易日回补 / block_trade` | `按交易日回补 / 大宗交易` |
| `backfill_by_trade_date.daily_basic` | `按交易日回补 / daily_basic` | `按交易日回补 / 股票日指标` |
| `backfill_by_trade_date.dc_hot` | `按交易日回补 / dc_hot` | `按交易日回补 / 东方财富热榜` |
| `backfill_by_trade_date.dc_member` | `按交易日回补 / dc_member` | `按交易日回补 / 东方财富板块成分` |
| `backfill_by_trade_date.kpl_concept_cons` | `按交易日回补 / kpl_concept_cons` | `按交易日回补 / 开盘啦题材成分` |
| `backfill_by_trade_date.limit_cpt_list` | `按交易日回补 / limit_cpt_list` | `按交易日回补 / 最强板块统计` |
| `backfill_by_trade_date.limit_list_d` | `按交易日回补 / limit_list_d` | `按交易日回补 / 涨跌停榜` |
| `backfill_by_trade_date.limit_list_ths` | `按交易日回补 / limit_list_ths` | `按交易日回补 / 同花顺涨跌停榜单` |
| `backfill_by_trade_date.limit_step` | `按交易日回补 / limit_step` | `按交易日回补 / 涨停天梯` |
| `backfill_by_trade_date.margin` | `按交易日回补 / margin` | `按交易日回补 / 融资融券交易汇总` |
| `backfill_by_trade_date.moneyflow` | `按交易日回补 / moneyflow` | `按交易日回补 / 资金流向（基础）` |
| `backfill_by_trade_date.moneyflow_cnt_ths` | `按交易日回补 / moneyflow_cnt_ths` | `按交易日回补 / 概念板块资金流向（同花顺）` |
| `backfill_by_trade_date.moneyflow_dc` | `按交易日回补 / moneyflow_dc` | `按交易日回补 / 个股资金流向（东方财富）` |
| `backfill_by_trade_date.moneyflow_ind_dc` | `按交易日回补 / moneyflow_ind_dc` | `按交易日回补 / 板块资金流向（东方财富）` |
| `backfill_by_trade_date.moneyflow_ind_ths` | `按交易日回补 / moneyflow_ind_ths` | `按交易日回补 / 行业资金流向（同花顺）` |
| `backfill_by_trade_date.moneyflow_mkt_dc` | `按交易日回补 / moneyflow_mkt_dc` | `按交易日回补 / 市场资金流向（东方财富）` |
| `backfill_by_trade_date.moneyflow_ths` | `按交易日回补 / moneyflow_ths` | `按交易日回补 / 个股资金流向（同花顺）` |
| `backfill_by_trade_date.stk_factor_pro` | `按交易日回补 / stk_factor_pro` | `按交易日回补 / 股票技术面因子(专业版)` |
| `backfill_by_trade_date.stk_nineturn` | `按交易日回补 / stk_nineturn` | `按交易日回补 / 神奇九转指标` |
| `backfill_by_trade_date.suspend_d` | `按交易日回补 / suspend_d` | `按交易日回补 / 每日停复牌信息` |
| `backfill_by_trade_date.ths_hot` | `按交易日回补 / ths_hot` | `按交易日回补 / 同花顺热榜` |
| `backfill_by_trade_date.top_list` | `按交易日回补 / top_list` | `按交易日回补 / 龙虎榜` |
| `backfill_equity_series.adj_factor` | `股票纵向回补 / adj_factor` | `股票纵向回补 / 复权因子` |
| `backfill_equity_series.daily` | `股票纵向回补 / daily` | `股票纵向回补 / 股票日线` |
| `backfill_equity_series.stk_period_bar_adj_month` | `股票纵向回补 / stk_period_bar_adj_month` | `股票纵向回补 / 股票复权月线` |
| `backfill_equity_series.stk_period_bar_adj_week` | `股票纵向回补 / stk_period_bar_adj_week` | `股票纵向回补 / 股票复权周线` |
| `backfill_equity_series.stk_period_bar_month` | `股票纵向回补 / stk_period_bar_month` | `股票纵向回补 / 股票月线` |
| `backfill_equity_series.stk_period_bar_week` | `股票纵向回补 / stk_period_bar_week` | `股票纵向回补 / 股票周线` |
| `backfill_fund_series.fund_adj` | `按交易日回补 / fund_adj` | `基金按交易日回补 / 基金复权因子` |
| `backfill_fund_series.fund_daily` | `按交易日回补 / fund_daily` | `基金按交易日回补 / 基金日线` |
| `backfill_index_series.index_daily` | `指数纵向回补 / index_daily` | `指数纵向回补 / 指数日线` |
| `backfill_index_series.index_daily_basic` | `指数纵向回补 / index_daily_basic` | `指数纵向回补 / 指数日指标` |
| `backfill_index_series.index_monthly` | `指数纵向回补 / index_monthly` | `指数纵向回补 / 指数月线` |
| `backfill_index_series.index_weekly` | `指数纵向回补 / index_weekly` | `指数纵向回补 / 指数周线` |
| `backfill_index_series.index_weight` | `指数纵向回补 / index_weight` | `指数纵向回补 / 指数成分权重` |
| `backfill_low_frequency.dividend` | `低频事件回补 / dividend` | `低频事件回补 / 分红送转` |
| `backfill_low_frequency.stk_holdernumber` | `低频事件回补 / stk_holdernumber` | `低频事件回补 / 股东户数` |
| `backfill_trade_cal.trade_cal` | `交易日历回补 / trade_cal` | `交易日历回补 / 交易日历` |
| `maintenance.rebuild_dm` | `维护动作 / rebuild_dm` | `维护动作 / 数据集市刷新` |
| `maintenance.rebuild_index_kline_serving` | `维护动作 / rebuild_index_kline_serving` | `维护动作 / 指数K线服务层重建` |
| `sync_daily.adj_factor` | `日常同步 / adj_factor` | `日常同步 / 复权因子` |
| `sync_daily.biying_equity_daily` | `日常同步 / biying_equity_daily` | `日常同步 / BIYING 股票日线` |
| `sync_daily.biying_moneyflow` | `日常同步 / biying_moneyflow` | `日常同步 / BIYING 资金流向` |
| `sync_daily.block_trade` | `日常同步 / block_trade` | `日常同步 / 大宗交易` |
| `sync_daily.broker_recommend` | `日常同步 / broker_recommend` | `日常同步 / 券商每月荐股` |
| `sync_daily.cyq_perf` | `日常同步 / cyq_perf` | `日常同步 / 每日筹码及胜率` |
| `sync_daily.daily` | `日常同步 / daily` | `日常同步 / 股票日线` |
| `sync_daily.daily_basic` | `日常同步 / daily_basic` | `日常同步 / 股票日指标` |
| `sync_daily.dc_daily` | `日常同步 / dc_daily` | `日常同步 / 东方财富板块行情` |
| `sync_daily.dc_hot` | `日常同步 / dc_hot` | `日常同步 / 东方财富热榜` |
| `sync_daily.dc_index` | `日常同步 / dc_index` | `日常同步 / 东方财富概念板块` |
| `sync_daily.dc_member` | `日常同步 / dc_member` | `日常同步 / 东方财富板块成分` |
| `sync_daily.fund_adj` | `日常同步 / fund_adj` | `日常同步 / 基金复权因子` |
| `sync_daily.fund_daily` | `日常同步 / fund_daily` | `日常同步 / 基金日线` |
| `sync_daily.index_daily` | `日常同步 / index_daily` | `日常同步 / 指数日线` |
| `sync_daily.kpl_concept_cons` | `日常同步 / kpl_concept_cons` | `日常同步 / 开盘啦题材成分` |
| `sync_daily.kpl_list` | `日常同步 / kpl_list` | `日常同步 / 开盘啦榜单` |
| `sync_daily.limit_cpt_list` | `日常同步 / limit_cpt_list` | `日常同步 / 最强板块统计` |
| `sync_daily.limit_list_d` | `日常同步 / limit_list_d` | `日常同步 / 涨跌停榜` |
| `sync_daily.limit_list_ths` | `日常同步 / limit_list_ths` | `日常同步 / 同花顺涨跌停榜单` |
| `sync_daily.limit_step` | `日常同步 / limit_step` | `日常同步 / 涨停天梯` |
| `sync_daily.margin` | `日常同步 / margin` | `日常同步 / 融资融券交易汇总` |
| `sync_daily.moneyflow` | `日常同步 / moneyflow` | `日常同步 / 资金流向（基础）` |
| `sync_daily.moneyflow_cnt_ths` | `日常同步 / moneyflow_cnt_ths` | `日常同步 / 概念板块资金流向（同花顺）` |
| `sync_daily.moneyflow_dc` | `日常同步 / moneyflow_dc` | `日常同步 / 个股资金流向（东方财富）` |
| `sync_daily.moneyflow_ind_dc` | `日常同步 / moneyflow_ind_dc` | `日常同步 / 板块资金流向（东方财富）` |
| `sync_daily.moneyflow_ind_ths` | `日常同步 / moneyflow_ind_ths` | `日常同步 / 行业资金流向（同花顺）` |
| `sync_daily.moneyflow_mkt_dc` | `日常同步 / moneyflow_mkt_dc` | `日常同步 / 市场资金流向（东方财富）` |
| `sync_daily.moneyflow_ths` | `日常同步 / moneyflow_ths` | `日常同步 / 个股资金流向（同花顺）` |
| `sync_daily.stk_factor_pro` | `日常同步 / stk_factor_pro` | `日常同步 / 股票技术面因子(专业版)` |
| `sync_daily.stk_limit` | `日常同步 / stk_limit` | `日常同步 / 每日涨跌停价格` |
| `sync_daily.stk_nineturn` | `日常同步 / stk_nineturn` | `日常同步 / 神奇九转指标` |
| `sync_daily.stk_period_bar_adj_month` | `日常同步 / stk_period_bar_adj_month` | `日常同步 / 股票复权月线` |
| `sync_daily.stk_period_bar_month` | `日常同步 / stk_period_bar_month` | `日常同步 / 股票月线` |
| `sync_daily.stock_st` | `日常同步 / stock_st` | `日常同步 / ST股票列表` |
| `sync_daily.suspend_d` | `日常同步 / suspend_d` | `日常同步 / 每日停复牌信息` |
| `sync_daily.ths_daily` | `日常同步 / ths_daily` | `日常同步 / 同花顺板块行情` |
| `sync_daily.ths_hot` | `日常同步 / ths_hot` | `日常同步 / 同花顺热榜` |
| `sync_daily.top_list` | `日常同步 / top_list` | `日常同步 / 龙虎榜` |
| `sync_history.adj_factor` | `历史同步 / adj_factor` | `历史同步 / 复权因子` |
| `sync_history.biying_equity_daily` | `历史同步 / biying_equity_daily` | `历史同步 / BIYING 股票日线` |
| `sync_history.biying_moneyflow` | `历史同步 / biying_moneyflow` | `历史同步 / BIYING 资金流向` |
| `sync_history.block_trade` | `历史同步 / block_trade` | `历史同步 / 大宗交易` |
| `sync_history.broker_recommend` | `历史同步 / broker_recommend` | `历史同步 / 券商每月荐股` |
| `sync_history.cyq_perf` | `历史同步 / cyq_perf` | `历史同步 / 每日筹码及胜率` |
| `sync_history.daily` | `历史同步 / daily` | `历史同步 / 股票日线` |
| `sync_history.daily_basic` | `历史同步 / daily_basic` | `历史同步 / 股票日指标` |
| `sync_history.dc_daily` | `历史同步 / dc_daily` | `历史同步 / 东方财富板块行情` |
| `sync_history.dc_hot` | `历史同步 / dc_hot` | `历史同步 / 东方财富热榜` |
| `sync_history.dc_index` | `历史同步 / dc_index` | `历史同步 / 东方财富概念板块` |
| `sync_history.dc_member` | `历史同步 / dc_member` | `历史同步 / 东方财富板块成分` |
| `sync_history.dividend` | `历史同步 / dividend` | `历史同步 / 分红送转` |
| `sync_history.etf_basic` | `历史同步 / etf_basic` | `历史同步 / ETF 基本信息` |
| `sync_history.etf_index` | `历史同步 / etf_index` | `历史同步 / ETF 基准指数列表` |
| `sync_history.fund_adj` | `历史同步 / fund_adj` | `历史同步 / 基金复权因子` |
| `sync_history.fund_daily` | `历史同步 / fund_daily` | `历史同步 / 基金日线` |
| `sync_history.hk_basic` | `历史同步 / hk_basic` | `历史同步 / 港股列表` |
| `sync_history.index_basic` | `历史同步 / index_basic` | `历史同步 / 指数主数据` |
| `sync_history.index_daily` | `历史同步 / index_daily` | `历史同步 / 指数日线` |
| `sync_history.index_daily_basic` | `历史同步 / index_daily_basic` | `历史同步 / 指数日指标` |
| `sync_history.index_monthly` | `历史同步 / index_monthly` | `历史同步 / 指数月线` |
| `sync_history.index_weekly` | `历史同步 / index_weekly` | `历史同步 / 指数周线` |
| `sync_history.index_weight` | `历史同步 / index_weight` | `历史同步 / 指数成分权重` |
| `sync_history.kpl_concept_cons` | `历史同步 / kpl_concept_cons` | `历史同步 / 开盘啦题材成分` |
| `sync_history.kpl_list` | `历史同步 / kpl_list` | `历史同步 / 开盘啦榜单` |
| `sync_history.limit_cpt_list` | `历史同步 / limit_cpt_list` | `历史同步 / 最强板块统计` |
| `sync_history.limit_list_d` | `历史同步 / limit_list_d` | `历史同步 / 涨跌停榜` |
| `sync_history.limit_list_ths` | `历史同步 / limit_list_ths` | `历史同步 / 同花顺涨跌停榜单` |
| `sync_history.limit_step` | `历史同步 / limit_step` | `历史同步 / 涨停天梯` |
| `sync_history.margin` | `历史同步 / margin` | `历史同步 / 融资融券交易汇总` |
| `sync_history.moneyflow` | `历史同步 / moneyflow` | `历史同步 / 资金流向（基础）` |
| `sync_history.moneyflow_cnt_ths` | `历史同步 / moneyflow_cnt_ths` | `历史同步 / 概念板块资金流向（同花顺）` |
| `sync_history.moneyflow_dc` | `历史同步 / moneyflow_dc` | `历史同步 / 个股资金流向（东方财富）` |
| `sync_history.moneyflow_ind_dc` | `历史同步 / moneyflow_ind_dc` | `历史同步 / 板块资金流向（东方财富）` |
| `sync_history.moneyflow_ind_ths` | `历史同步 / moneyflow_ind_ths` | `历史同步 / 行业资金流向（同花顺）` |
| `sync_history.moneyflow_mkt_dc` | `历史同步 / moneyflow_mkt_dc` | `历史同步 / 市场资金流向（东方财富）` |
| `sync_history.moneyflow_ths` | `历史同步 / moneyflow_ths` | `历史同步 / 个股资金流向（同花顺）` |
| `sync_history.stk_factor_pro` | `历史同步 / stk_factor_pro` | `历史同步 / 股票技术面因子(专业版)` |
| `sync_history.stk_holdernumber` | `历史同步 / stk_holdernumber` | `历史同步 / 股东户数` |
| `sync_history.stk_limit` | `历史同步 / stk_limit` | `历史同步 / 每日涨跌停价格` |
| `sync_history.stk_nineturn` | `历史同步 / stk_nineturn` | `历史同步 / 神奇九转指标` |
| `sync_history.stk_period_bar_adj_month` | `历史同步 / stk_period_bar_adj_month` | `历史同步 / 股票复权月线` |
| `sync_history.stk_period_bar_adj_week` | `历史同步 / stk_period_bar_adj_week` | `历史同步 / 股票复权周线` |
| `sync_history.stk_period_bar_month` | `历史同步 / stk_period_bar_month` | `历史同步 / 股票月线` |
| `sync_history.stk_period_bar_week` | `历史同步 / stk_period_bar_week` | `历史同步 / 股票周线` |
| `sync_history.stock_basic` | `历史同步 / stock_basic` | `历史同步 / 股票主数据` |
| `sync_history.stock_st` | `历史同步 / stock_st` | `历史同步 / ST股票列表` |
| `sync_history.suspend_d` | `历史同步 / suspend_d` | `历史同步 / 每日停复牌信息` |
| `sync_history.ths_daily` | `历史同步 / ths_daily` | `历史同步 / 同花顺板块行情` |
| `sync_history.ths_hot` | `历史同步 / ths_hot` | `历史同步 / 同花顺热榜` |
| `sync_history.ths_index` | `历史同步 / ths_index` | `历史同步 / 同花顺概念和行业指数` |
| `sync_history.ths_member` | `历史同步 / ths_member` | `历史同步 / 同花顺板块成分` |
| `sync_history.top_list` | `历史同步 / top_list` | `历史同步 / 龙虎榜` |
| `sync_history.trade_cal` | `历史同步 / trade_cal` | `历史同步 / 交易日历` |
| `sync_history.us_basic` | `历史同步 / us_basic` | `历史同步 / 美股列表` |
