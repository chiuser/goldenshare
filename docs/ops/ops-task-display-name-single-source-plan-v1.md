# Ops 任务显示名单一事实源收口方案 v1

> 状态：任务记录/任务详情闭环已落地；自动任务页待专项方案。
> 当前版本：已按用户评审意见调整为“维护对象优先”的 UI 口径，并完成 execution list/detail、任务记录、任务详情的第一轮实现。
> 适用范围：任务记录、任务详情、今日任务、自动任务、手动任务入口中涉及任务名称、处理范围、发起方式、状态与操作的展示链路。
> 当前落地边界：本轮只落地任务记录与任务详情；今日任务/概览类页面暂不迁移；自动任务页单独立题。

## 1. 背景

`sync_minute_history.stk_mins` 曾在任务详情页显示为：

```text
任务 / 未配置显示名称（stk_mins）
```

直接原因是前端 `formatSpecDisplayLabel(spec_key, spec_display_name)` 在遇到 `prefix.resource` 形式的 `spec_key` 时，优先按前端静态映射拼接：

```text
specPrefixLabelMap[prefix] / resourceLabelMap[resource]
```

而不是优先使用后端返回的用户语言。

继续审计后发现，更深层的问题不是某一个 `stk_mins` 映射缺失，而是当前 UI 把后端执行链路暴露给了用户：

```text
日常同步 / daily
历史同步 / daily
按交易日回补 / daily_basic
股票纵向回补 / stk_period_bar_week
指数纵向回补 / index_daily
```

这些词来自后端 spec 分类、任务路由或执行策略。用户真正关心的是：

1. 维护什么数据？
2. 处理哪个时间点或时间范围？
3. 谁/什么方式发起？
4. 当前状态是什么？
5. 可以做什么操作？

因此，本方案不再把目标设为“把执行类型翻译成中文”，而是把 UI 主路径收敛为“维护对象 + 处理范围 + 发起方式/状态/操作”。

## 2. 总体原则

### 2.1 用户主路径不暴露底层执行链路

以下内容不进入普通 UI 主路径：

```text
sync_daily
sync_history
backfill_by_trade_date
backfill_by_date_range
backfill_equity_series
backfill_index_series
run_profile
spec_key
```

这些信息只允许作为后端解析、日志、API 排查字段存在，不作为任务名称、列表主列或详情标题。

### 2.2 任务显示的核心对象是“维护对象”

维护对象统一来自数据集/动作的中文资源名：

```text
股票日线
复权因子
东方财富热榜
股票历史分钟行情
指数成分权重
开盘啦榜单
```

### 2.3 “维护”二字只用于动作入口

手动任务入口、自动任务创建入口中，动作名使用：

```text
维护 + 资源中文名
```

示例：

```text
维护股票日线
维护东方财富热榜
维护股票历史分钟行情
```

任务记录列表和任务详情页标题不加“维护”二字，只显示资源名。

## 3. 页面级目标口径

### 3.1 任务记录列表

任务记录列表展示用户关心的信息：

| 列 | 口径 |
| --- | --- |
| 任务名称 | 资源中文名，如 `股票日线` |
| 处理范围 | 单点、区间、月份或无时间维度 |
| 发起方式 | 手动、自动、重新提交、系统 |
| 提交时间 | 用户提交或系统入队时间 |
| 当前状态 | 等待开始、执行中、成功、失败、已取消 |
| 操作 | 查看详情、重新提交、停止等 |

不展示：

```text
执行路径
spec_key
sync/backfill/纵向回补
```

### 3.2 任务详情页

标题：

```text
股票日线
```

不是：

```text
维护股票日线
日常同步 / 股票日线
backfill_equity_series.daily
```

标题下方的信息卡片：

1. 保留现有“发起方式”卡片。
2. 在“发起方式”卡片右侧新增“处理范围”卡片。
3. 如果该任务没有时间维度，不展示“处理范围”卡片。

处理范围展示口径：

| 场景 | 示例 |
| --- | --- |
| 单日/单点 | `2026-04-24` |
| 日期区间 | `2026-04-20 ~ 2026-04-24` |
| 月份 | `2026-04` |
| 月份区间 | `2026-01 ~ 2026-04` |
| 无时间维度 | 不展示处理范围卡片 |

不新增技术信息折叠区。底层执行信息不在普通任务详情页暴露。

### 3.3 手动任务入口

手动任务选择列表继续使用动作语言：

```text
维护股票日线
维护东方财富热榜
维护股票历史分钟行情
```

这是“我要做什么”的入口语言，和任务执行后的标题不同。

### 3.4 自动任务页

自动任务与手动任务的本质区别只是触发方式不同，不应该让用户理解底层 spec。

目标方向：

1. 自动任务创建/编辑也选择“维护动作”，而不是选择底层 `JobSpec`。
2. 自动任务列表与任务记录列表保持对象语言一致。
3. 自动任务列表主列建议包含：
   - 任务名称：资源中文名或动作名
   - 处理范围/时间规则：如“每个交易日”“每月最后一个交易日”“固定月份”
   - 发起方式/触发方式：自动
   - 下次运行时间
   - 当前状态
   - 操作

不展示：

```text
spec_key
底层执行路径
sync_daily/backfill_xxx
```

自动任务页需要单独重新设计列表和创建/编辑交互，不能只做显示名替换。

## 4. 后端契约建议

为了让前端不再猜，后端需要向任务相关接口提供用户语言字段。

### 4.1 Execution List / Detail 建议字段

建议在现有 execution list/detail 响应中补充：

| 字段 | 含义 |
| --- | --- |
| `resource_key` | 数据集/维护对象 key |
| `resource_display_name` | 资源中文名，如 `股票日线` |
| `action_display_name` | 动作名，如 `维护股票日线` |
| `time_scope` | 结构化处理范围 |
| `time_scope_label` | 可直接展示的处理范围文案 |

`time_scope` 建议结构：

```json
{
  "kind": "point | range | month | month_range | none",
  "start": "2026-04-20",
  "end": "2026-04-24",
  "label": "2026-04-20 ~ 2026-04-24"
}
```

### 4.2 JobSpec / spec_display_name 的定位

`spec_display_name` 不再作为 UI 主标题的唯一来源。

建议定位：

1. 兼容旧接口和旧页面。
2. 后端内部 catalog 可读名称。
3. 调试、日志或管理工具辅助字段。

UI 主路径优先使用：

```text
resource_display_name
action_display_name
time_scope_label
```

而不是从 `spec_key/spec_display_name` 推导。

## 5. 前端显示规则

前端任务展示优先级：

```text
1. resource_display_name
2. action_display_name 去掉“维护”前缀后得到的资源名
3. spec_display_name（兼容兜底）
4. spec_key（最后兜底）
```

前端不得在正常路径展示：

```text
未配置显示名称
任务 / 未配置显示名称（xxx）
```

`resourceLabelMap` 可保留，但只能作为旧数据或后端字段缺失时的兼容兜底，不能覆盖后端用户语言字段。

## 6. 名称审计与建议口径

### 6.1 当前不合理模式

当前大量 `JobSpec.display_name` 属于后端链路语言：

| 当前模式 | 问题 | UI 主路径建议 |
| --- | --- | --- |
| `日常同步 / daily` | 暴露执行策略和内部 key | `股票日线` |
| `历史同步 / daily` | 用户不关心历史/日常区别 | `股票日线` |
| `按交易日回补 / dc_hot` | 用户不理解回补和 key | `东方财富热榜` |
| `股票纵向回补 / stk_period_bar_week` | 暴露后端批处理方式 | `股票周线` |
| `指数纵向回补 / index_daily` | 暴露后端批处理方式 | `指数日线` |
| `分钟行情同步 / stk_mins` | 暴露 key | `股票历史分钟行情` |

### 6.2 维护对象标准名称

后续任务记录、任务详情标题统一使用以下资源中文名。

| resource_key | 标准任务名称 |
| --- | --- |
| `stock_basic` | 股票主数据 |
| `daily` | 股票日线 |
| `adj_factor` | 复权因子 |
| `daily_basic` | 股票日指标 |
| `stk_mins` | 股票历史分钟行情 |
| `stk_limit` | 每日涨跌停价格 |
| `limit_list_d` | 涨跌停榜 |
| `limit_list_ths` | 同花顺涨跌停榜单 |
| `limit_step` | 涨停天梯 |
| `limit_cpt_list` | 最强板块统计 |
| `top_list` | 龙虎榜 |
| `block_trade` | 大宗交易 |
| `cyq_perf` | 每日筹码及胜率 |
| `stk_factor_pro` | 股票技术面因子(专业版) |
| `stock_st` | ST股票列表 |
| `stk_nineturn` | 神奇九转指标 |
| `suspend_d` | 每日停复牌信息 |
| `stk_holdernumber` | 股东户数 |
| `dividend` | 分红送转 |
| `stk_period_bar_week` | 股票周线 |
| `stk_period_bar_month` | 股票月线 |
| `stk_period_bar_adj_week` | 股票复权周线 |
| `stk_period_bar_adj_month` | 股票复权月线 |
| `moneyflow` | 资金流向（基础） |
| `moneyflow_ths` | 个股资金流向（同花顺） |
| `moneyflow_dc` | 个股资金流向（东方财富） |
| `moneyflow_cnt_ths` | 概念板块资金流向（同花顺） |
| `moneyflow_ind_ths` | 行业资金流向（同花顺） |
| `moneyflow_ind_dc` | 板块资金流向（东方财富） |
| `moneyflow_mkt_dc` | 市场资金流向（东方财富） |
| `fund_daily` | 基金日线 |
| `fund_adj` | 基金复权因子 |
| `index_basic` | 指数主数据 |
| `index_daily` | 指数日线 |
| `index_weekly` | 指数周线 |
| `index_monthly` | 指数月线 |
| `index_daily_basic` | 指数日指标 |
| `index_weight` | 指数成分权重 |
| `ths_index` | 同花顺概念和行业指数 |
| `ths_member` | 同花顺板块成分 |
| `ths_daily` | 同花顺板块行情 |
| `ths_hot` | 同花顺热榜 |
| `dc_index` | 东方财富概念板块 |
| `dc_member` | 东方财富板块成分 |
| `dc_daily` | 东方财富板块行情 |
| `dc_hot` | 东方财富热榜 |
| `kpl_list` | 开盘啦榜单 |
| `kpl_concept_cons` | 开盘啦题材成分 |
| `broker_recommend` | 券商每月荐股 |
| `trade_cal` | 交易日历 |
| `hk_basic` | 港股列表 |
| `us_basic` | 美股列表 |
| `etf_basic` | ETF 基本信息 |
| `etf_index` | ETF 基准指数列表 |
| `biying_equity_daily` | BIYING 股票日线 |
| `biying_moneyflow` | BIYING 资金流向 |

### 6.3 维护动作标准名称

手动任务入口和自动任务创建入口使用：

```text
维护 + 标准任务名称
```

示例：

| resource_key | 维护动作名称 |
| --- | --- |
| `daily` | 维护股票日线 |
| `dc_hot` | 维护东方财富热榜 |
| `stk_mins` | 维护股票历史分钟行情 |
| `index_weight` | 维护指数成分权重 |

## 7. 需要评审拍板

| 编号 | 决策项 | 建议值 |
| --- | --- | --- |
| D1 | 任务记录/详情主标题 | 只显示资源中文名，不加“维护” |
| D2 | 手动任务入口动作名 | `维护 + 资源中文名` |
| D3 | 任务记录列表新增列 | 新增“处理范围”，保留发起方式、提交时间、状态、操作 |
| D4 | 任务详情信息卡片 | 在发起方式卡片右侧新增“处理范围”卡片，无时间维度则隐藏 |
| D5 | 技术信息折叠区 | 不新增 |
| D6 | 自动任务页 | 重新设计为选择维护动作，不选择底层 spec |
| D7 | 底层执行路径 | 不进入普通 UI 主路径 |

## 8. 后续改造阶段

### P0：评审冻结本文口径（已完成）

1. 确认第 3 节页面口径。
2. 确认第 6 节标准任务名称。
3. 确认第 7 节 D1-D7。

### P1：后端补充用户语言字段（execution list/detail 已完成）

1. execution list/detail 补 `resource_display_name`。
2. execution list/detail 补 `time_scope/time_scope_label`。
3. manual-actions 已有 `resource_display_name` 基线；auto schedule 等待 P3 专项。
4. 已增加后端测试，覆盖 execution 的 `resource_display_name` 与 `time_scope_label`。

### P2：任务记录与任务详情改造（已完成）

1. 任务记录列表新增“处理范围”列。
2. 任务记录任务名改为资源中文名。
3. 任务详情标题改为资源中文名。
4. 任务详情新增“处理范围”卡片。
5. 普通 UI 不展示执行路径。

### P3：自动任务页专项重新设计（待专项方案）

自动任务页不纳入 P1/P2 的任务记录与任务详情收口范围。

原因：

1. 自动任务页当前同时承载列表、创建、编辑、详情、调度预览、探测触发、同步参数等多条链路。
2. 页面仍直接选择底层 `JobSpec` / `WorkflowSpec`，不是简单替换显示名即可解决。
3. 如果在 P1/P2 顺手改 `formatSpecDisplayLabel` 或执行对象展示，会让多个底层 spec 显示成同一个资源名，反而增加误选风险。

P3 需要单独出交互方案，再进入开发。

1. 自动任务创建/编辑从选择 spec 改为选择维护动作。
2. 自动任务列表与任务记录列表保持对象语言一致。
3. 自动任务仍可在后端内部解析到真实 spec，但前端不感知。

### P4：前端兜底降级与门禁（进行中）

目标：让 `formatSpecDisplayLabel` 逐步退出普通 UI 主路径，避免内部执行链路继续泄漏给用户。

TODO：

1. 新增任务展示专用入口，例如 `formatExecutionResourceLabel`。（已完成）
   - 优先使用 `resource_display_name`。
   - 其次使用 `action_display_name` 去掉“维护”前缀后的资源名。
   - 再兜底 `spec_display_name`。
   - 最后才兜底 `spec_key`。
2. P2 只在任务记录和任务详情中接入 `formatExecutionResourceLabel`。（已完成）
   - 不全局修改 `formatSpecDisplayLabel`。
   - 不顺手影响今日任务、概览、自动任务页。
3. 今日任务、概览类页面后续单独评估是否迁移。（待办）
   - 迁移前先确认这些页面是否仍需要显示执行路径信息。
   - 若不需要，再改用 `formatExecutionResourceLabel`。
4. 自动任务页必须等 P3 专项方案冻结后迁移。（待办）
   - 在自动任务页改造前，不能直接把所有 spec 选项都显示成资源名。
   - 避免 `sync_daily.daily`、`sync_history.daily`、`backfill_equity_series.daily` 同时显示为“股票日线”导致误选。
5. `formatSpecDisplayLabel` 最终定位为兼容/调试辅助函数。
   - 可保留给旧数据、技术排查或内部管理视图。
   - 不再作为普通用户页面标题、列表主列、表单主选项的默认 formatter。
6. 前端静态映射仅用于旧数据兼容。
7. 测试禁止普通页面出现“未配置显示名称”。
8. 新增数据集模板补充 Ops 任务显示验收项。
