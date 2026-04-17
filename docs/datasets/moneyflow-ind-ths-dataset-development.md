# Tushare 行业资金流向（THS）（`moneyflow_ind_ths`）数据集开发说明

## 0. 当前架构基线（必须遵守）

本数据集结论：

- 该数据集是否对外服务：是
- 当前是否多源：否（仅 `tushare`）
- 是否已具备 std 映射与融合策略：否
- 本次 target_table 选择：`core_serving.industry_moneyflow_ths`
- 路径选择：`raw_tushare -> core_serving`（单源直出）

---

## 1. 标准交付流程（本数据集）

1. 固定上游接口 `moneyflow_ind_ths`（doc_id=343）。
2. 设计交易日推进与全量日切抓取策略。
3. 设计 `raw_tushare.moneyflow_ind_ths` 与 `core_serving.industry_moneyflow_ths`。
4. 打通 Ops 手动/自动任务和健康度展示。
5. 完成测试与回归。

---

## 2. 基本信息

- 数据集名称：行业资金流向（THS）
- 资源 key：`moneyflow_ind_ths`
- 所属域：板块与热榜
- 数据源：`tushare`
- 官方文档链接：<https://tushare.pro/document/2?doc_id=343>
- API 名称：`moneyflow_ind_ths`
- 文档抓取日期：`2026-04-17`

---

## 3. 接口分析

### 3.1 输入参数（上游原生）

| 参数名 | 类型 | 必填 | 说明 | 类别 | 是否暴露给用户 | 前端控件 | 执行层映射 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ts_code` | str | 否 | 板块代码 | 代码 | 是（可选） | 代码输入 | 直传 |
| `trade_date` | str | 否 | 交易日期（YYYYMMDD） | 时间 | 是 | 单日选择器 | 直传 |
| `start_date` | str | 否 | 开始日期 | 时间 | 是 | 区间选择器 | 直传 |
| `end_date` | str | 否 | 结束日期 | 时间 | 是 | 区间选择器 | 直传 |
| `limit` | int | 否 | 单次返回数据长度 | 分页 | 否 | 不暴露 | 执行层自动注入 |
| `offset` | int | 否 | 请求数据开始位移 | 分页 | 否 | 不暴露 | 执行层自动注入 |

### 3.2 输出字段（上游原生）

| 字段名 | 类型 | 含义 | 是否落库 |
| --- | --- | --- | --- |
| `trade_date` | str | 交易日期 | 是 |
| `ts_code` | str | 板块代码 | 是 |
| `industry` | str | 行业名称 | 是 |
| `lead_stock` | str | 领涨股票名称 | 是 |
| `close` | float | 最新价 | 是 |
| `pct_change` | float | 涨跌幅（%） | 是 |
| `company_num` | int | 公司数量 | 是 |
| `pct_change_stock` | float | 领涨股涨跌幅 | 是 |
| `close_price` | float | 领涨股最新价 | 是 |
| `net_buy_amount` | float | 净买入（万元） | 是 |
| `net_sell_amount` | float | 净卖出（万元） | 是 |
| `net_amount` | float | 净额（万元） | 是 |

### 3.3 同步策略结论

- 是否支持单次时间点：是
- 是否支持区间回补：是
- 时间粒度：日
- 时间推进策略：交易日历逐日
- 是否需要分页循环：是（接口支持 `limit` / `offset`）
- 是否有级联依赖：否

推荐最省力拉取方式：

- 按交易日逐日全量抓取。
- 区间同步由执行层拆成交易日序列。
- 单次结果达到上限时，执行层自动按 `limit` + `offset` 分页拉取并合并。

---

## 4. 参数与交互设计（Ops）

### 4.1 手动任务交互

1. 第一步：板块与热榜 -> 行业资金流向（THS）
2. 第二步：时间参数（单日/区间）
3. 第三步：其他输入条件（可选 `ts_code`）

### 4.2 自动任务交互

- 资源：`sync_daily.moneyflow_ind_ths`
- 仅注入 `trade_date`

---

## 5. 落库与发布设计

### 5.1 路径选择

- 路径类型：`raw -> core_serving`
- 选择理由：单源且字段明确稳定
- 是否为临时方案：是

### 5.2 表设计

#### A. `raw_tushare.moneyflow_ind_ths`

- 主键：`(trade_date, ts_code)`
- 审计字段：`api_name`, `fetched_at`, `raw_payload`
- 索引：
  - `idx_raw_tushare_moneyflow_ind_ths_trade_date(trade_date)`
  - `idx_raw_tushare_moneyflow_ind_ths_ts_code_trade_date(ts_code, trade_date)`

#### B. `core_serving.industry_moneyflow_ths`

- 主键：`(trade_date, ts_code)`
- 索引：
  - `idx_industry_moneyflow_ths_trade_date(trade_date)`
  - `idx_industry_moneyflow_ths_ts_code_trade_date(ts_code, trade_date)`

---

## 6. 同步实现设计

- Sync Service：`SyncMoneyflowIndThsService`
- `target_table`：`core_serving.industry_moneyflow_ths`
- 参数构建：
  - `sync_daily.moneyflow_ind_ths`：`trade_date`（可选 `ts_code`）
  - `sync_history.moneyflow_ind_ths`：`trade_date` 或 `start_date+end_date`（可选 `ts_code`）
- 分页策略：每个 `trade_date`（及可选 `ts_code`）组合内，自动用 `limit` + `offset` 分页直至取完
- 幂等：按主键 upsert
- 进度日志示例：
  - `moneyflow_ind_ths: 18/83 trade_date=2026-04-16 page=1 fetched=156 written=156`

---

## 7. 数据状态与健康度观测

- 分组：资金流向
- 观测列：`trade_date`
- 展示名：行业资金流向（THS）

---

## 8. 测试与验收

- 单测：参数校验、区间推进、upsert 幂等
- 集成：`sync_daily.moneyflow_ind_ths`、`sync_history.moneyflow_ind_ths`
- 回归：不影响板块成分/板块行情链路

---

## 9. 发布与回滚

- 迁移：新增 `raw_tushare.moneyflow_ind_ths`、`core_serving.industry_moneyflow_ths`
- 回滚：回滚代码、停任务，保留历史数据

---

## 10. 已拍板结论（本数据集）

1. 纳入独立工作流：每日资金流向同步。
2. 不并入其它工作流。
3. 数据状态分组归属：资金流向。
