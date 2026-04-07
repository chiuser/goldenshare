# 股票价格还原因子（`equity_price_restore_factor`）数据集设计说明

## 1. 背景与目标

为股票日线行情新增一套基于“价格还原法”的复权因子数据集，用于替代当前行情接口中直接依赖 `adj_factor` 的前/后复权计算。

本次目标：

- 新增独立因子表，不与 `core.equity_adj_factor` 混存。
- 基于 `daily + dividend + trade_calendar` 计算累积因子 `cum_factor`。
- 行情接口（日线）切换为读取价格还原因子进行即时复权计算。
- 运维侧新增可监控、可手动执行、可自动调度的任务能力。
- 数据状态页新增展示项：`价格还原因子`。

明确不做：

- 不持久化前复权价/后复权价。
- 不用 `pro_bar(qfq)` 作为验收对账口径（算法口径不同，预期不一致）。

## 2. 数据来源

- 原始日线：`daily`（不复权）
- 分红送转：`dividend`
- 交易日历：`trade_cal`

说明：

- 该数据集不直采上游“现成复权因子”，而是由基座内部计算生成。
- 现有 `core.equity_adj_factor` 继续保留并按原逻辑同步，供其他历史依赖使用。

## 3. 因子定义与计算规则

## 3.1 单次因子（除权事件）

```
single_factor(ex_date) = (P_prev - cash_div_tax) / (1 + stk_div) / P_prev
```

- `P_prev`：`ex_date` 前一个交易日（`< ex_date`）的原始收盘价
- `cash_div_tax`：税后每股现金分红
- `stk_div`：每股送转（送股+转股）

## 3.2 累积因子方向

- 后复权方向（旧 -> 新）
- 上市首个交易日：`cum_factor = 1.0`
- 自首日向后逐日累乘，精度保留 8 位小数

## 3.3 复权价即时计算（行情接口）

前复权（锚点=最新交易日）：

```
price_qfq(t) = price_raw(t) * cum_factor(t) / cum_factor(latest)
```

后复权（锚点=首日）：

```
price_hfq(t) = price_raw(t) * cum_factor(t)
```

## 4. 数据过滤与边界规则

- 分红记录仅保留：`div_proc = '实施'`
- 排除：`ex_date is null` 或 `ex_date > today`
- `ex_date` 非交易日时，必须用交易日历取 `< ex_date` 最近交易日作为 `P_prev`
- 同一 `ts_code + ex_date` 多条分红记录时，先聚合后计算单次因子
- `cash_div_tax`、`stk_div` 空值按 0 处理，并记录质量告警

## 5. 表设计（独立新表）

表名：`core.equity_price_restore_factor`

- 主键：`(ts_code, trade_date)`
- 字段：
  - `ts_code`
  - `trade_date`
  - `cum_factor`（`NUMERIC(20,8)`）
  - `single_factor`（`NUMERIC(20,8)`, 可空；仅事件日有值）
  - `event_applied`（`BOOLEAN`, 默认 `false`）
  - `event_ex_date`（`DATE`, 可空）
  - `created_at`
  - `updated_at`
- 索引建议：
  - `idx_equity_price_restore_factor_trade_date`
  - `idx_equity_price_restore_factor_updated_at`

说明：

- 与 `core.equity_adj_factor` 分离，避免两套语义和两套更新机制混用在同一表。
- `core.equity_adj_factor` 保留原用途，不参与新行情复权计算。

## 6. 同步与更新策略

## 6.1 全量重建（一次性）

输入：`start_date`, `end_date`（可选，不传则全历史）

流程：

1. 按股票遍历交易日序列（来自 `core.equity_daily_bar`）。
2. 构建该股票分红事件映射（按 `ex_date`）。
3. 线性扫描交易日生成 `cum_factor`、`single_factor`。
4. 批量 upsert 到 `core.equity_price_restore_factor`。

## 6.2 日常增量

输入：`trade_date`（单日）

流程：

1. 对当日有日线数据的股票，先复制前一交易日 `cum_factor`。
2. 若该股票当日命中除权事件，计算 `single_factor`。
3. 将该事件影响应用到 `trade_date >= ex_date` 的因子（可按股票局部批量更新）。
4. 写入进度日志与影响行数。

## 6.3 幂等与一致性

- 同一交易日重复执行，结果应幂等（最终 `cum_factor` 一致）。
- 事件重复应用必须避免（可依赖 `event_applied/event_ex_date` 或幂等重算覆盖策略）。

## 7. 运维接入（Ops）

任务建议：

- `maintenance.rebuild_equity_price_restore_factor`
- `sync_daily.equity_price_restore_factor`
- `sync_history.equity_price_restore_factor`（按区间重建或回补）

手动任务交互（遵循统一规范）：

1. 第一步：选择要维护的数据 -> `价格还原因子`
2. 第二步：时间选择（单日 / 区间）
3. 第三步：其他输入条件（当前无则不展示）

数据状态页：

- 分类：股票
- 名称：`价格还原因子`
- 日期口径：`trade_date` 范围 + 最近同步时间

## 8. 行情接口改造点

接口：`GET /api/v1/quote/detail/kline`（股票 + 日线）

- `adjustment=forward`：使用 `cum_factor(t)/cum_factor(latest)` 缩放
- `adjustment=backward`：使用 `cum_factor(t)` 缩放
- `adjustment=none`：保持原始价

注意：

- `latest` 必须是该股票全局最新因子交易日，不受请求区间限制。
- 周/月线策略本期不改，后续单独设计。

## 9. 测试方案

单元测试：

- 单次因子公式计算（含空值、边界值）
- 非交易日 `ex_date` 回溯前一交易日逻辑
- 多分红记录同日聚合逻辑
- `qfq/hfq` 即时计算公式与精度

集成测试：

- 全量重建后可查询到完整 `cum_factor` 序列
- 单日增量（无事件/有事件）两条链路正确
- 行情接口切换后可正确返回复权价格

回归测试：

- 不影响现有 `core.equity_adj_factor` 同步任务与依赖查询
- 旧接口字段不变（仅数值口径切换）

## 10. 发布与迁移建议

1. 建表 + DAO + 同步任务先落地，不切行情读取。
2. 全量重建因子数据。
3. 灰度切换行情接口读取新因子表。
4. 观察一个交易日周期后全量切换。
5. 保留 `core.equity_adj_factor` 原任务，不做强耦合改造。

## 11. 风险与应对

- 风险：分红事件修订可能导致历史区间因子变化
  - 应对：提供按区间重建任务，支持重算覆盖
- 风险：除权事件密集时批量更新成本上升
  - 应对：按股票分片执行 + 批处理提交
- 风险：两套因子被误用
  - 应对：接口层明确只读 `equity_price_restore_factor`，并在文档/任务名中显式区分
