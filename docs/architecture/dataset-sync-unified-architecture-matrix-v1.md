# 数据同步统一架构与全量数据集矩阵 v2

## 1. 设计总纲（先统一思想）

数据同步最本质只有一件事：**下载数据 -> 落库数据**。  
其余所有复杂性，都应该通过“切面（Aspect）”在流程节点上编排，而不是把流程散落到各个数据集里各写一套。

也就是说：

1. 主流程只有一条（可观测、可回放、可恢复）。
2. 数据集差异只体现在切面配置和少量插件逻辑。
3. 同步安全依赖统一门禁，而不是靠人工经验。

---

## 2. 统一主流程（Pipeline）

```text
Intent(用户意图)
  -> 计划编排(执行单元计划)
  -> 下载执行(含流控/分页/重试)
  -> 数据处理(清洗/补齐/计算/去重)
  -> 落库提交(raw/core)
  -> 质量校验与状态快照
```

主流程固定，扩展靠切面，不允许绕主流程直接写“特殊入口”。

---

## 3. 切面模型（AOP）

## 3.1 Join Points（切入点）

1. `JP1_IntentParse`：解析用户意图（时间、筛选、范围、调度）。
2. `JP2_PlanBuild`：构建执行单元（trade_date/code/month/range）。
3. `JP3_RequestDispatch`：请求发出前（参数归一、签名、限流）。
4. `JP4_ResponseHandle`：下载返回后（字段规范化、空值处理）。
5. `JP5_PreWrite`：落库前（补数、计算、去重主键准备）。
6. `JP6_Write`：落库动作（raw/core 写入策略）。
7. `JP7_PostWrite`：写后（质量告警、进度汇总、快照更新）。

## 3.2 Aspect Catalog（统一切面目录）

| 切面ID | 名称 | 作用 |
| --- | --- | --- |
| `A01` | 参数映射切面 | UI 业务化参数 -> API 参数（含多选枚举拼接） |
| `A02` | 时间解析切面 | 单点/区间、日周月、交易日历映射 |
| `A03` | 执行单元规划切面 | 按交易日/代码/月份/区间切片生成 units |
| `A04` | 依赖预热切面 | 先主表后成分、先基础后派生 |
| `A05` | 流控重试切面 | 限流、指数退避、超时重试 |
| `A06` | 分页拉取切面 | limit/offset/page 直到拉完 |
| `A07` | 数据清洗切面 | 字段清洗、类型归一、默认值补齐 |
| `A08` | 补齐计算切面 | 用其他表补值或计算派生字段 |
| `A09` | 去重键切面 | 业务主键/代理键策略、重复处理 |
| `A10` | 幂等写入切面 | upsert 规则、冲突策略 |
| `A11` | 质量规则切面 | 质量告警与修复（如 dividend ex_date） |
| `A12` | 观测快照切面 | freshness 快照、任务状态、结果摘要 |

> 规则：新增数据集必须从 `A01~A12` 里选择；如不满足再新增切面，禁止在 Service 内无约束扩散。

---

## 4. 同步安全门禁（统一）

1. **计划安全**：执行计划必须可序列化、可复放（Plan Hash）。
2. **参数安全**：参数白名单 + 类型校验 + 时间闭区间校验。
3. **执行安全**：单元失败隔离，任务不中断；支持重试与续跑。
4. **数据安全**：每个数据集必须声明去重键 + 幂等写策略。
5. **质量安全**：写后自动跑质量规则，异常入日志与结果摘要。
6. **观测安全**：任务结束必须写快照，杜绝“库已更新但页面不变”。

---

## 5. 42个数据集全量梳理（按切面）

说明：

1. `当前入口`用于说明现状，不代表目标态保留多入口。
2. `核心切面`是该数据集必须启用的切面组合。
3. `特性插件`仅列必须保留的非通用逻辑。

| 数据集 | 当前入口 | 核心切面 | 特性插件（必须保留） |
| --- | --- | --- | --- |
| `stock_basic` | `sync_history.stock_basic` | `A01 A03 A07 A09 A10 A12` | 无 |
| `hk_basic` | `sync_history.hk_basic` | `A01 A03 A07 A09 A10 A12` | `list_status` 枚举过滤 |
| `us_basic` | `sync_history.us_basic` | `A01 A03 A06 A07 A09 A10 A12` | `classify` 枚举过滤 |
| `trade_cal` | `backfill_trade_cal.trade_cal / sync_history.trade_cal` | `A01 A02 A03 A05 A07 A10 A12` | 交易所维度口径 |
| `etf_basic` | `sync_history.etf_basic` | `A01 A03 A07 A09 A10 A12` | `list_status/exchange` 多选 |
| `etf_index` | `sync_history.etf_index` | `A01 A03 A07 A09 A10 A12` | 无 |
| `index_basic` | `sync_history.index_basic` | `A01 A03 A07 A09 A10 A12` | 无 |
| `ths_index` | `sync_history.ths_index` | `A01 A03 A07 A09 A10 A12` | `type/exchange` 参数 |
| `ths_member` | `sync_history.ths_member` | `A01 A03 A04 A05 A07 A09 A10 A12` | 先 `ths_index` 后成分 |
| `daily` | `backfill_equity_series.daily / sync_daily.daily / sync_history.daily` | `A01 A02 A03 A05 A07 A09 A10 A12` | 代码池纵向推进 |
| `adj_factor` | `backfill_equity_series.adj_factor / sync_daily.adj_factor / sync_history.adj_factor` | `A01 A02 A03 A05 A07 A09 A10 A12` | 代码池纵向推进 |
| `daily_basic` | `backfill_by_trade_date.daily_basic / sync_daily.daily_basic / sync_history.daily_basic` | `A01 A02 A03 A05 A07 A09 A10 A12` | 按交易日推进 |
| `moneyflow` | `backfill_by_trade_date.moneyflow / sync_daily.moneyflow / sync_history.moneyflow` | `A01 A02 A03 A05 A07 A09 A10 A12` | 按交易日推进 |
| `top_list` | `backfill_by_trade_date.top_list / sync_daily.top_list / sync_history.top_list` | `A01 A02 A03 A05 A07 A09 A10 A12` | 按交易日推进 |
| `block_trade` | `backfill_by_trade_date.block_trade / sync_daily.block_trade / sync_history.block_trade` | `A01 A02 A03 A05 A07 A09 A10 A12` | 重复行处理（代理键） |
| `limit_list_d` | `backfill_by_trade_date.limit_list_d / sync_daily.limit_list_d / sync_history.limit_list_d` | `A01 A02 A03 A05 A07 A09 A10 A12` | `exchange/limit_type` 多选组合 |
| `limit_list_ths` | `backfill_by_trade_date.limit_list_ths / sync_daily.limit_list_ths / sync_history.limit_list_ths` | `A01 A02 A03 A05 A07 A09 A10 A12` | `market/limit_type` 多选组合 |
| `limit_step` | `backfill_by_trade_date.limit_step / sync_daily.limit_step / sync_history.limit_step` | `A01 A02 A03 A05 A07 A09 A10 A12` | 无 |
| `limit_cpt_list` | `backfill_by_trade_date.limit_cpt_list / sync_daily.limit_cpt_list / sync_history.limit_cpt_list` | `A01 A02 A03 A05 A07 A09 A10 A12` | 无 |
| `fund_daily` | `backfill_fund_series.fund_daily / sync_daily.fund_daily / sync_history.fund_daily` | `A01 A02 A03 A05 A06 A07 A09 A10 A12` | 单日分页拉全量 |
| `fund_adj` | `backfill_fund_series.fund_adj / sync_daily.fund_adj / sync_history.fund_adj` | `A01 A02 A03 A05 A06 A07 A09 A10 A12` | 单日分页拉全量 |
| `index_daily` | `backfill_index_series.index_daily / sync_daily.index_daily / sync_history.index_daily` | `A01 A02 A03 A05 A06 A07 A09 A10 A12` | 指数代码池推进 |
| `index_weekly` | `backfill_index_series.index_weekly / sync_history.index_weekly` | `A01 A02 A03 A05 A06 A07 A09 A10 A12` | 周期边界映射 |
| `index_monthly` | `backfill_index_series.index_monthly / sync_history.index_monthly` | `A01 A02 A03 A05 A06 A07 A09 A10 A12` | 月周期边界映射 |
| `index_daily_basic` | `backfill_index_series.index_daily_basic / sync_history.index_daily_basic` | `A01 A02 A03 A05 A06 A07 A09 A10 A12` | 指数池过滤与分页 |
| `index_weight` | `backfill_index_series.index_weight / sync_history.index_weight` | `A01 A02 A03 A05 A07 A09 A10 A12` | `index_code` + 区间 |
| `stk_period_bar_week` | `backfill_equity_series.stk_period_bar_week / sync_history.stk_period_bar_week` | `A01 A02 A03 A05 A07 A09 A10 A12` | 周线边界规则 |
| `stk_period_bar_month` | `backfill_equity_series.stk_period_bar_month / sync_history.stk_period_bar_month` | `A01 A02 A03 A05 A07 A09 A10 A12` | 月线边界规则 |
| `stk_period_bar_adj_week` | `backfill_equity_series.stk_period_bar_adj_week / sync_history.stk_period_bar_adj_week` | `A01 A02 A03 A05 A07 A09 A10 A12` | 复权周线边界 |
| `stk_period_bar_adj_month` | `backfill_equity_series.stk_period_bar_adj_month / sync_history.stk_period_bar_adj_month` | `A01 A02 A03 A05 A07 A09 A10 A12` | 复权月线边界 |
| `dc_index` | `backfill_by_date_range.dc_index / sync_daily.dc_index / sync_history.dc_index` | `A01 A02 A03 A05 A07 A09 A10 A12` | `idx_type` 过滤 |
| `dc_member` | `backfill_by_trade_date.dc_member / sync_daily.dc_member / sync_history.dc_member` | `A01 A02 A03 A04 A05 A07 A09 A10 A12` | 先 `dc_index` 再拉成分 |
| `dc_daily` | `backfill_by_date_range.dc_daily / sync_daily.dc_daily / sync_history.dc_daily` | `A01 A02 A03 A05 A07 A09 A10 A12` | 按 `dc_index` 代码推进 |
| `ths_daily` | `backfill_by_date_range.ths_daily / sync_daily.ths_daily / sync_history.ths_daily` | `A01 A02 A03 A05 A07 A09 A10 A12` | 按 `ths_index` 代码推进 |
| `kpl_concept_cons` | `backfill_by_trade_date.kpl_concept_cons / sync_daily.kpl_concept_cons / sync_history.kpl_concept_cons` | `A01 A02 A03 A05 A07 A09 A10 A12` | `con_code/ts_code` 条件 |
| `ths_hot` | `backfill_by_trade_date.ths_hot / sync_daily.ths_hot / sync_history.ths_hot` | `A01 A02 A03 A05 A07 A09 A10 A12` | `market + is_new` |
| `dc_hot` | `backfill_by_trade_date.dc_hot / sync_daily.dc_hot / sync_history.dc_hot` | `A01 A02 A03 A05 A07 A08 A09 A10 A12` | 美股 `ts_code` 补齐 |
| `kpl_list` | `backfill_by_date_range.kpl_list / sync_daily.kpl_list / sync_history.kpl_list` | `A01 A02 A03 A05 A07 A09 A10 A12` | `tag` 默认与多选 |
| `dividend` | `backfill_low_frequency.dividend / sync_history.dividend` | `A01 A03 A05 A07 A08 A09 A10 A11 A12` | `ex_date` 自动修复规则 |
| `stk_holdernumber` | `backfill_low_frequency.stk_holdernumber / sync_history.stk_holdernumber` | `A01 A03 A05 A07 A09 A10 A12` | 低频代码池遍历 |
| `broker_recommend` | `backfill_by_month.broker_recommend / sync_daily.broker_recommend / sync_history.broker_recommend` | `A01 A02 A03 A05 A06 A07 A09 A10 A12` | 月份区间展开 |

---

## 6. 例子串联（你提的那类复杂数据集）

假设数据集能力：支持 `code + start/end + trade_date`，上游有重复，落库前要用其他表补值。

统一流程落地：

1. `JP1/JP2`：`A01+A02+A03` 生成“按代码 + 按交易日”的执行计划。
2. `JP3`：`A05` 加流控与重试；`A06` 如需分页。
3. `JP4`：`A07` 清洗字段。
4. `JP5`：`A08` 补值（查其他表）；`A09` 去重。
5. `JP6`：`A10` 幂等写 raw/core。
6. `JP7`：`A11` 质量规则；`A12` 写快照并可视化。

这正是“主流程稳定 + 切面编排差异”的目标形态。

---

## 7. 对现阶段代码的结论

1. 现有实现已经具备很多切面雏形，但分散在 `sync_history/sync_daily/backfill_*` 多入口里。
2. 下一步不该再增加新入口；应把入口语义收敛到统一主流程。
3. 收敛顺序建议：
   - 先统一 `A01/A02/A03/A12`（参数、时间、单元、观测）
   - 再统一 `A05/A06/A09/A10`（执行安全）
   - 最后收口 `A04/A08/A11`（依赖、补值、质量）

---

## 8. 研发约束（必须执行）

1. 新数据集接入必须提交“切面选择清单”（至少列出 A01~A12 中使用项）。
2. 若出现特性逻辑，必须声明是插件，不得直接侵入主流程核心。
3. 若需新增切面，先补文档与测试，再进代码。
4. 所有数据集最终只对外呈现同一套业务语义：  
   **维护数据 -> 选时间 -> 选其他条件 -> 执行 -> 看进度与结果**。
