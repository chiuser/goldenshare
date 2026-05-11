# 市场总览｜money-flow 真实数据验证用例 v1

> 目标：在进入 API 实现前，用真实库数据验证“查询组合、状态判定、性能基线”是否可落地。
> 范围：验证 money-flow 模块默认路径与显式 `tradeDate` 观测路径；不涉及前端接入。
> 执行脚本：
> [money-flow-real-data-validation-sql-v1.sql](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/money-flow-real-data-validation-sql-v1.sql)

---

## 1. 数据源与字段

1. 主表：`core_serving.market_moneyflow_dc`
2. 日历：`core_serving.trade_calendar`（`exchange='SSE'`）
3. 核心字段：
   - `net_amount`、`net_amount_rate`
   - `buy_elg_amount`、`buy_elg_amount_rate`
   - `buy_lg_amount`、`buy_lg_amount_rate`
   - `buy_md_amount`、`buy_md_amount_rate`
   - `buy_sm_amount`、`buy_sm_amount_rate`

---

## 2. 真实验证 Case 设计

### Case-A（默认路径）

1. 输入：无（未传 `tradeDate`，系统自动推导 `expectedTradeDate`）。
2. 期望交易日规则（按当前实现口径）：
   - 使用上海时区当前时间；
   - `latestOpen = 当日及以前最近开市日`；
   - 若 `当前小时 >= 20`，`expectedTradeDate = latestOpen`；
   - 若 `当前小时 < 20` 且当日开市，`expectedTradeDate = 前一开市日`；
   - 若 `当前小时 < 20` 且当日不开市，`expectedTradeDate = latestOpen`。
3. 验证点：
   - `today` 与 `prev` 双卡是否都有值；
   - 历史窗口是否达到 `22/62`；
   - 状态是否符合预期（当前样本为 `READY`）。

### Case-B（显式 tradeDate 观测路径）

1. 输入：`tradeDate=YYYY-MM-DD`。
2. 语义：该参数是模块观测交易日，用于回看、验证和调试；不是用户侧资金流规则配置项。
3. 验证点：
   - `expectedTradeDate` 等于传入的 `tradeDate`；
   - `today`、`prev`、分单结构与历史窗口均围绕该观测交易日计算；
   - 历史点仍按 `tradeDate` 升序输出；
   - 状态判定继续使用 `observedTradeDate` 与目标观测交易日比较。

---

## 3. 状态判定校准口径（本轮验证版）

1. `observedTradeDate is null` -> `EMPTY`
2. `expectedTradeDate > observedTradeDate` -> `DELAYED`
3. `today_missing && prev_missing && history_1m=0 && history_3m=0` -> `EMPTY`
4. `today_missing || prev_missing || history_1m<22 || history_3m<62` -> `PARTIAL`
5. 其他 -> `READY`

> 说明：显式 `tradeDate` 是所有已落地市场模块统一保留的可选观测日参数，本模块必须保持一致。

---

## 4. 性能基线验证

### Query-P1：双卡查询

1. 目标：`today/prev` 两行读取
2. 指标：`EXPLAIN ANALYZE` 执行耗时

### Query-P2：1个月历史（22点）

1. 目标：按交易日窗口取 `22` 点
2. 指标：`EXPLAIN ANALYZE` 执行耗时

### Query-P3：3个月历史（62点）

1. 目标：按交易日窗口取 `62` 点
2. 指标：`EXPLAIN ANALYZE` 执行耗时

---

## 5. 通过标准（本轮）

1. 默认路径状态判定符合预期。
2. 显式 `tradeDate` 路径状态判定符合预期。
3. 查询组合能稳定产出双卡 + 分单 + 历史数据。
4. Query-P1/P2/P3 耗时显著低于模块预算 `P95 < 260ms`（单次执行量级校准）。
5. 若出现口径冲突或异常，先回写三件套，不进入 API 开发。

---

## 6. 执行命令

```bash
bash scripts/psql-remote.sh -f /Users/congming/github/goldenshare/wealth/docs/pages/market-overview/money-flow-real-data-validation-sql-v1.sql
```

---

## 7. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-12 | 首版：定义 money-flow 真实数据验证 case 与性能基线 | Codex |
| v1.1 | 2026-05-12 | 收敛为默认路径验证，移除前端不存在的显式日期输入分支 | Codex |
| v1.2 | 2026-05-12 | 统一市场模块请求口径：补回显式 `tradeDate` 观测路径验证 | Codex |
