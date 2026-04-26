# Tushare 大盘资金流向（DC）（`moneyflow_mkt_dc`）数据集开发说明

## 0. 当前架构基线（必须遵守）

本数据集结论：

- 该数据集是否对外服务：是
- 当前是否多源：否（仅 `tushare`）
- 是否已具备 std 映射与融合策略：否
- 本次 target_table 选择：`core_serving.market_moneyflow_dc`
- 路径选择：`raw_tushare -> core_serving`（单源直出）

---

## 1. 标准交付流程（本数据集）

1. 固定上游接口 `moneyflow_mkt_dc`（doc_id=345）。
2. 明确“单日行集”主键与幂等口径。
3. 设计 `raw_tushare.moneyflow_mkt_dc` 与 `core_serving.market_moneyflow_dc`。
4. 打通 Ops 与观测。
5. 完成测试与回归。

---

## 2. 基本信息

- 数据集名称：大盘资金流向（DC）
- 资源 key：`moneyflow_mkt_dc`
- 所属域：股票
- 数据源：`tushare`
- 官方文档链接：<https://tushare.pro/document/2?doc_id=345>
- API 名称：`moneyflow_mkt_dc`
- 文档抓取日期：`2026-04-17`

---

## 3. 接口分析

### 3.1 输入参数（上游原生）

| 参数名 | 类型 | 必填 | 说明 | 类别 | 是否暴露给用户 | 前端控件 | 执行层映射 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `trade_date` | str | 否 | 交易日期（YYYYMMDD） | 时间 | 是 | 单日选择器 | 直传 |
| `start_date` | str | 否 | 开始日期 | 时间 | 是 | 区间选择器 | 直传 |
| `end_date` | str | 否 | 结束日期 | 时间 | 是 | 区间选择器 | 直传 |
| `limit` | int | 否 | 单次返回数据长度 | 分页 | 否 | 不暴露 | 执行层自动注入 |
| `offset` | int | 否 | 请求数据开始位移 | 分页 | 否 | 不暴露 | 执行层自动注入 |

### 3.2 输出字段（上游原生）

| 字段名 | 类型 | 含义 | 是否落库 |
| --- | --- | --- | --- |
| `trade_date` | str | 交易日期 | 是 |
| `close_sh` | float | 上证最新价 | 是 |
| `pct_change_sh` | float | 上证涨跌幅（%） | 是 |
| `close_sz` | float | 深证最新价 | 是 |
| `pct_change_sz` | float | 深证涨跌幅（%） | 是 |
| `net_amount` | float | 今日主力净流入净额（元） | 是 |
| `net_amount_rate` | float | 今日主力净流入净额占比（%） | 是 |
| `buy_elg_amount` | float | 今日超大单净流入净额（元） | 是 |
| `buy_elg_amount_rate` | float | 今日超大单净流入净占比（%） | 是 |
| `buy_lg_amount` | float | 今日大单净流入净额（元） | 是 |
| `buy_lg_amount_rate` | float | 今日大单净流入净占比（%） | 是 |
| `buy_md_amount` | float | 今日中单净流入净额（元） | 是 |
| `buy_md_amount_rate` | float | 今日中单净流入净占比（%） | 是 |
| `buy_sm_amount` | float | 今日小单净流入净额（元） | 是 |
| `buy_sm_amount_rate` | float | 今日小单净流入净占比（%） | 是 |

### 3.3 同步策略结论

- 是否支持单次时间点：是
- 是否支持区间回补：是
- 时间粒度：日
- 时间推进策略：交易日历逐日
- 是否需要分页循环：是（接口支持 `limit` / `offset`）
- 是否有级联依赖：否

推荐最省力拉取方式：

- 按交易日历逐日请求。
- 单次结果达到上限时，执行层自动按 `limit` + `offset` 分页拉取并合并。

---

## 4. 参数与交互设计（Ops）

### 4.1 手动任务交互

1. 第一步：股票 -> 大盘资金流向（DC）
2. 第二步：时间参数（单日/区间）
3. 第三步：无

### 4.2 自动任务交互

- 资源：`moneyflow_mkt_dc.maintain`
- 仅注入 `trade_date`

---

## 5. 落库与发布设计

### 5.1 路径选择

- 路径类型：`raw -> core_serving`
- 选择理由：单源直出、数据体量小、业务查询频繁
- 是否为临时方案：是

### 5.2 表设计

#### A. `raw_tushare.moneyflow_mkt_dc`

- 主键：`trade_date`
- 审计字段：`api_name`, `fetched_at`, `raw_payload`
- 索引：`idx_raw_tushare_moneyflow_mkt_dc_trade_date(trade_date)`

#### B. `core_serving.market_moneyflow_dc`

- 主键：`trade_date`
- 索引：`idx_market_moneyflow_dc_trade_date(trade_date)`

---

## 6. 维护实现设计

- IngestionExecutor / SourceClient：`moneyflow_mkt_dc` 数据集维护链路
- `target_table`：`core_serving.market_moneyflow_dc`
- 参数构建：
  - `moneyflow_mkt_dc.maintain`：`trade_date` 或 `start_date+end_date`
- 分页策略：每个 `trade_date` 组合内，自动用 `limit` + `offset` 分页直至取完
- 幂等：按 `trade_date` upsert
- 进度日志示例：
  - `moneyflow_mkt_dc: 21/83 trade_date=2026-04-16 page=1 fetched=1 written=1`

---

## 7. 数据状态与健康度观测

- 分组：资金流向
- 观测列：`trade_date`
- 展示名：大盘资金流向（DC）

---

## 8. 测试与验收

- 单测：参数映射、区间推进、单键 upsert
- 集成：`moneyflow_mkt_dc.maintain`（单日/区间）
- 回归：不影响其他资金流数据集

---

## 9. 发布与回滚

- 迁移：新增 `raw_tushare.moneyflow_mkt_dc`、`core_serving.market_moneyflow_dc`
- 回滚：回滚代码并停用任务

---

## 10. 已拍板结论（本数据集）

1. 主键按 `trade_date` 单键处理（默认一天一条）。
2. 数据状态分组归属：资金流向。
3. 分页策略：启用 `limit` + `offset` 自动分页补齐。
4. 纳入独立工作流：每日资金流向同步，不并入其它工作流。
