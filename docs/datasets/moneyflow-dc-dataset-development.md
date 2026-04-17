# Tushare 个股资金流向（DC）（`moneyflow_dc`）数据集开发说明

## 0. 当前架构基线（必须遵守）

本数据集结论：

- 该数据集是否对外服务：是
- 当前是否多源：否（仅 `tushare`）
- 是否已具备 std 映射与融合策略：否
- 本次 target_table 选择：`core_serving.equity_moneyflow_dc`
- 路径选择：`raw_tushare -> core_serving`（单源直出）

---

## 1. 标准交付流程（本数据集）

1. 固定上游接口 `moneyflow_dc`（doc_id=349）。
2. 明确历史区间推进与容量上限处理。
3. 设计 `raw_tushare.moneyflow_dc` 与 `core_serving.equity_moneyflow_dc`。
4. 打通 Ops 与健康度观测。
5. 完成测试与回归。

---

## 2. 基本信息

- 数据集名称：个股资金流向（DC）
- 资源 key：`moneyflow_dc`
- 所属域：股票
- 数据源：`tushare`
- 官方文档链接：<https://tushare.pro/document/2?doc_id=349>
- API 名称：`moneyflow_dc`
- 文档抓取日期：`2026-04-17`

---

## 3. 接口分析

### 3.1 输入参数（上游原生）

| 参数名 | 类型 | 必填 | 说明 | 类别 | 是否暴露给用户 | 前端控件 | 执行层映射 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ts_code` | str | 否 | 股票代码 | 代码 | 是（可选） | 代码输入 | 直传 |
| `trade_date` | str | 否 | 交易日期 | 时间 | 是 | 单日选择器 | 直传 |
| `start_date` | str | 否 | 开始日期 | 时间 | 是 | 区间选择器 | 直传 |
| `end_date` | str | 否 | 结束日期 | 时间 | 是 | 区间选择器 | 直传 |

### 3.2 输出字段（上游原生）

| 字段名 | 类型 | 含义 | 是否落库 |
| --- | --- | --- | --- |
| `trade_date` | str | 交易日期 | 是 |
| `ts_code` | str | 股票代码 | 是 |
| `name` | str | 股票名称 | 是 |
| `pct_change` | float | 涨跌幅（%） | 是 |
| `close` | float | 最新收盘价 | 是 |
| `net_amount` | float | 净流入（万元） | 是 |
| `net_amount_rate` | float | 净流入占比（%） | 是 |
| `buy_elg_amount` | float | 今日超大单净流入额（万元） | 是 |
| `buy_elg_amount_rate` | float | 今日超大单净流入占比（%） | 是 |
| `buy_lg_amount` | float | 今日大单净流入额（万元） | 是 |
| `buy_lg_amount_rate` | float | 今日大单净流入占比（%） | 是 |
| `buy_md_amount` | float | 今日中单净流入额（万元） | 是 |
| `buy_md_amount_rate` | float | 今日中单净流入占比（%） | 是 |
| `buy_sm_amount` | float | 今日小单净流入额（万元） | 是 |
| `buy_sm_amount_rate` | float | 今日小单净流入占比（%） | 是 |

### 3.3 同步策略结论

- 是否支持单次时间点：是
- 是否支持区间回补：是
- 时间粒度：日
- 时间推进策略：交易日历逐日推进
- 是否需要分页循环：是（接口支持 `limit` / `offset`）
- 是否有级联依赖：否

推荐最省力拉取方式：

- 日常：按 `trade_date` 单日请求。
- 历史：按交易日历逐日请求。
- 分页：当单次返回触达上限时，使用 `limit`+`offset` 翻页补齐当日数据。
- `ts_code` 仅用于定向修复，不作为默认全量路径。

---

## 4. 参数与交互设计（Ops）

### 4.1 手动任务交互

1. 第一步：股票 -> 个股资金流向（DC）
2. 第二步：时间参数（单日/区间）
3. 第三步：其他输入条件（可选 `ts_code`）

### 4.2 自动任务交互

- 资源：`sync_daily.moneyflow_dc`
- 默认不暴露 `ts_code`，仅注入 `trade_date`

---

## 5. 落库与发布设计

### 5.1 路径选择

- 路径类型：`raw -> core_serving`
- 选择理由：单源且业务查询直接消费
- 是否为临时方案：是
- 后续收敛：接入第二源后升级到 `std + resolution`

### 5.2 表设计

#### A. `raw_tushare.moneyflow_dc`

- 主键：`(trade_date, ts_code)`
- 审计字段：`api_name`, `fetched_at`, `raw_payload`
- 索引：
  - `idx_raw_tushare_moneyflow_dc_trade_date(trade_date)`
  - `idx_raw_tushare_moneyflow_dc_ts_code_trade_date(ts_code, trade_date)`

#### B. `core_serving.equity_moneyflow_dc`

- 主键：`(trade_date, ts_code)`
- 索引：
  - `idx_equity_moneyflow_dc_trade_date(trade_date)`
  - `idx_equity_moneyflow_dc_ts_code_trade_date(ts_code, trade_date)`

---

## 6. 同步实现设计

- Sync Service：`SyncMoneyflowDcService`
- `target_table`：`core_serving.equity_moneyflow_dc`
- 参数构建：
  - `sync_daily.moneyflow_dc`：`trade_date`（可选 `ts_code`）
  - `sync_history.moneyflow_dc`：`trade_date` 或 `start_date+end_date`（可选 `ts_code`）
- 幂等：按主键 upsert
- 进度日志示例：
  - `moneyflow_dc: 25/83 trade_date=2026-04-16 fetched=4987 written=4987`

---

## 7. 数据状态与健康度观测

- 数据状态分组：资金流向
- 健康度口径：`trade_date` 日期范围
- 展示名：个股资金流向（DC）

---

## 8. 测试与验收

- 单测：参数映射、交易日历推进、upsert 幂等
- 集成：`sync_daily.moneyflow_dc`、`sync_history.moneyflow_dc`
- 回归：不影响既有 `moneyflow`（旧资金流）链路

---

## 9. 发布与回滚

- 迁移：新增 `raw_tushare.moneyflow_dc`、`core_serving.equity_moneyflow_dc`
- 发布后验证：跑一个交易日并核对行数
- 回滚：回滚代码，保留数据表

---

## 10. 已拍板结论（本数据集）

1. 若单次返回达到上限 6000，默认启用 `limit` + `offset` 分页补数。
2. 自动任务不附带单股 `ts_code`，仅手动页可选。
3. 纳入独立工作流：每日资金流向同步，不并入其它工作流。
