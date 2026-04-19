# Tushare 个股资金流向（THS）（`moneyflow_ths`）数据集开发说明

## 0. 当前架构基线（必须遵守）

本数据集结论：

- 该数据集是否对外服务：是
- 当前是否多源：否（仅 `tushare`）
- 是否已具备 std 映射与融合策略：否
- 本次 target_table 选择：`core_serving.equity_moneyflow_ths`
- 路径选择：`raw_tushare -> core_serving`（单源直出）

---

## 1. 标准交付流程（本数据集）

1. 固定上游接口 `moneyflow_ths`（doc_id=348）。
2. 明确输入输出参数与历史回补推进口径。
3. 设计 `raw_tushare.moneyflow_ths` 与 `core_serving.equity_moneyflow_ths`。
4. 打通 Ops 手动/自动任务、数据状态观测。
5. 完成单测、集成测试与回归。

---

## 2. 基本信息

- 数据集名称：个股资金流向（THS）
- 资源 key：`moneyflow_ths`
- 所属域：股票
- 数据源：`tushare`
- 官方文档链接：<https://tushare.pro/document/2?doc_id=348>
- API 名称：`moneyflow_ths`
- 文档抓取日期：`2026-04-17`

---

## 3. 接口分析

### 3.1 输入参数（上游原生）

| 参数名 | 类型 | 必填 | 说明 | 类别 | 是否暴露给用户 | 前端控件 | 执行层映射 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ts_code` | str | 否 | 股票代码 | 代码 | 是（可选） | 代码输入 | 直传 |
| `trade_date` | str | 否 | 交易日期（YYYYMMDD） | 时间 | 是 | 单日日期选择器 | 直传 |
| `start_date` | str | 否 | 开始日期（YYYYMMDD） | 时间 | 是 | 区间选择器 | 直传 |
| `end_date` | str | 否 | 结束日期（YYYYMMDD） | 时间 | 是 | 区间选择器 | 直传 |
| `limit` | int | 否 | 单次返回数据长度 | 分页 | 否 | 不暴露 | 执行层自动注入 |
| `offset` | int | 否 | 请求数据开始位移 | 分页 | 否 | 不暴露 | 执行层自动注入 |

### 3.2 输出字段（上游原生）

| 字段名 | 类型 | 含义 | 是否落库 |
| --- | --- | --- | --- |
| `trade_date` | str | 交易日期 | 是 |
| `ts_code` | str | 股票代码 | 是 |
| `name` | str | 股票名称 | 是 |
| `pct_change` | float | 涨跌幅 | 是 |
| `latest` | float | 最新价 | 是 |
| `net_amount` | float | 净流入（万元） | 是 |
| `net_d5_amount` | float | 5日主力净额（万元） | 是 |
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
- 历史：按区间映射交易日历逐日请求。
- 分页：当单次返回触达上限时，使用 `limit` + `offset` 翻页补齐当日数据。
- 保留 `ts_code` 作为定向补数入口（默认不填，走全市场）。

---

## 4. 参数与交互设计（Ops）

### 4.1 手动任务交互

1. 第一步：选择要维护的数据  
数据分组：股票  
维护对象：个股资金流向（THS）
2. 第二步：时间参数  
支持单日、区间
3. 第三步：其他输入条件  
`ts_code`（可选）

### 4.2 自动任务交互

- 资源：`sync_daily.moneyflow_ths`
- 默认参数：仅 `trade_date`（由调度注入）
- 可选扩展：`ts_code`

---

## 5. 落库与发布设计

### 5.1 路径选择

- 路径类型：`raw -> core_serving`
- 选择理由：当前单源，且业务侧需要直接查询该数据
- 是否为临时方案：是
- 后续收敛计划：接入多源后升级 `raw_* -> *_std -> core_serving`

### 5.2 表设计

#### A. `raw_tushare.moneyflow_ths`

- 主键：`(trade_date, ts_code)`
- 审计字段：`api_name`, `fetched_at`, `raw_payload`
- 索引：
  - `idx_raw_tushare_moneyflow_ths_trade_date(trade_date)`
  - `idx_raw_tushare_moneyflow_ths_ts_code_trade_date(ts_code, trade_date)`

#### B. `core_serving.equity_moneyflow_ths`

- 主键：`(trade_date, ts_code)`
- 对外口径：与上游业务字段一致（不含审计字段）
- 索引：
  - `idx_equity_moneyflow_ths_trade_date(trade_date)`
  - `idx_equity_moneyflow_ths_ts_code_trade_date(ts_code, trade_date)`

---

## 6. 同步实现设计

- Sync Service：`SyncMoneyflowThsService`
- `target_table`：`core_serving.equity_moneyflow_ths`
- 参数构建：
  - `sync_daily.moneyflow_ths`：`trade_date` + 可选 `ts_code`
  - `sync_history.moneyflow_ths`：`trade_date` 或 `start_date+end_date` + 可选 `ts_code`
- 幂等：按主键 upsert
- 异常策略：上游异常按现有重试；参数异常中文提示
- 进度日志示例：
  - `moneyflow_ths: 12/82 trade_date=2026-04-16 fetched=5210 written=5210`

---

## 7. 数据状态与健康度观测

- 数据状态分组：资金流向
- 健康度口径：日期范围（`trade_date`）
- 展示名称：个股资金流向（THS）
- 异常文案：中文摘要 + 原始错误可追溯

---

## 8. 测试与验收

### 8.1 测试清单

- 单元测试：
  - 参数映射（单日/区间/可选 `ts_code`）
  - 交易日历推进
  - upsert 幂等
- 集成测试：
  - `sync_daily.moneyflow_ths`
  - `sync_history.moneyflow_ths`
  - Ops 手动/自动任务链路
- 回归测试：
  - 不影响既有 `moneyflow` / `moneyflow_dc` 等数据集

### 8.2 验收勾选

- [ ] 输出字段全量落库
- [ ] Ops 交互满足 1-2-3 步规范
- [ ] 数据状态页可展示日期范围与最新状态

---

## 9. 发布与回滚

- 迁移：新增 `raw_tushare.moneyflow_ths` 与 `core_serving.equity_moneyflow_ths`
- 发布顺序：
  1. 数据库迁移
  2. 部署代码
  3. 触发一次 `sync_daily.moneyflow_ths` 验证
- 回滚：回滚代码与任务注册，保留表数据

---

## 10. 已拍板结论（本数据集）

1. 自动任务默认不暴露 `ts_code`，仅保留手动页定向补数。
2. 单次返回触顶（6000）时，优先走 `limit` + `offset` 自动分页补齐，不启用 `ts_code` 二级扇出。
3. 纳入独立工作流：每日资金流向同步，不并入其它工作流。
4. 数据状态分组归属：资金流向。
