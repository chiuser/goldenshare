# Tushare 每日筹码及胜率（`cyq_perf`）数据集开发方案（评审稿）

## 1. 目标与边界

- 目标：新增 `cyq_perf` 数据集，打通 Tushare 拉取、`raw_tushare` 落库、`core_serving` 对外服务、Ops 手动/自动任务与数据状态观测。
- 本期边界：
  - 仅接入 Tushare 单源。
  - 采用 `raw_tushare -> core_serving`（单源直出）路径。
  - 不引入 `std` 实体表物化（后续多源再升级）。

---

## 2. 上游接口信息

- 接口文档：<https://tushare.pro/document/2?doc_id=293>
- API：`cyq_perf`
- 描述：获取 A 股每日筹码平均成本与胜率，约 18:00~19:00 更新，数据从 2018 年开始。
- 频控约束：当前账户每天可请求约 20,000 次。
- 单次返回上限：5,000 行（支持分页）。

---

## 3. 真实测算与最优同步策略结论

本节基于你当前库和接口实测数据：

### 3.1 实测基线

1. `raw_tushare.stock_basic` 当前规模：
- `distinct ts_code = 5,829`
- `list_status='L' = 5,505`

2. 交易日（2018-01-01 ~ 2026-04-16）：
- `2,009` 个交易日

3. `cyq_perf` 接口实测：
- 按 `trade_date=20260415` 请求（不传 `ts_code`）返回 `5,494` 行（单日全市场可拉）。
- 分页实测：
  - `limit=5000, offset=0` 返回 `5,000` 行，`has_more=true`
  - `limit=5000, offset=5000` 返回 `494` 行，`has_more=false`
- 按单票 `ts_code=000001.SZ`（不传日期）返回 `2,009` 行（2018 全历史）。

4. 用现有日线数据估算“按交易日回补”的分页调用量：
- 2018 至今交易日：`2,006`（按日线实际数据）
- 每日平均股票数约：`4,567.74`
- 估算请求数：`2,827` 次（已考虑 `>5000` 需第二页）

### 3.2 两种方案对比

1. 按股票代码全历史拉取（code-loop）
- 每个 `ts_code` 一次请求可覆盖 2018 至今（单票行数 < 5,000）。
- 预计请求数约 `5,733`~`5,829` 次。

2. 按交易日拉取全市场（date-loop）
- 每个交易日请求 1~2 页。
- 预计请求数约 `2,827`~`4,018` 次（上界按每天都超 5,000 估算）。

### 3.3 最优策略（结论）

选择 **按交易日（trade_date）推进 + 分页**，原因：

1. 总请求量显著更低（约 2,827 vs 5,733+）。
2. 和日常增量天然一致（每天只需要按 `trade_date` 拉 1~2 次）。
3. 更符合 20,000 次/日配额约束，留出其他任务余量。

---

## 4. 接口参数与输出字段

### 4.1 输入参数（上游）

| 参数 | 说明 | 本期使用方式 |
| --- | --- | --- |
| `ts_code` | 股票代码 | 作为可选过滤参数（默认不传，全市场） |
| `trade_date` | 交易日期（YYYYMMDD） | 日常同步主参数；历史回补按交易日历逐日传入 |
| `start_date` | 开始日期 | 本期不直接传给上游，作为用户输入后内部拆成逐交易日 |
| `end_date` | 结束日期 | 同上 |
| `limit` | 分页长度 | 内部固定 `5000` |
| `offset` | 分页偏移 | 内部分页递增（0/5000/10000...） |

### 4.2 输出字段（全量落库）

- `ts_code`
- `trade_date`
- `his_low`
- `his_high`
- `cost_5pct`
- `cost_15pct`
- `cost_50pct`
- `cost_85pct`
- `cost_95pct`
- `weight_avg`
- `winner_rate`

---

## 5. 落库设计

### 5.1 Raw 层

- 表：`raw_tushare.cyq_perf`
- 主键：`(ts_code, trade_date)`
- 字段：上游输出全字段 + 审计字段
  - `api_name`
  - `fetched_at`
  - `raw_payload`
- 索引：
  - `idx_raw_tushare_cyq_perf_trade_date(trade_date)`
  - `idx_raw_tushare_cyq_perf_ts_code_trade_date(ts_code, trade_date)`

### 5.2 Serving 层

- 表：`core_serving.equity_cyq_perf`
- 主键：`(ts_code, trade_date)`
- 字段：与业务口径一致（与上游字段一一对应）
- 索引：
  - `idx_equity_cyq_perf_trade_date(trade_date)`
  - `idx_equity_cyq_perf_ts_code_trade_date(ts_code, trade_date)`

---

## 6. 同步实现设计

### 6.1 任务定义

- `sync_daily.cyq_perf`
  - 参数：`trade_date`（可选 `ts_code`）
- `sync_history.cyq_perf`
  - 参数：`start_date/end_date` 或 `trade_date`（可选 `ts_code`）

### 6.2 执行逻辑

1. 日常同步（INCREMENTAL）
- 传入单日 `trade_date`
- 内部分页：`limit=5000` + `offset` 循环，直到 `has_more=false` 或当页不足 `limit`

2. 历史同步（FULL）
- 用户输入起止日期
- 服务内部按交易日历筛开市日，逐日请求
- 每个交易日内部继续分页

3. 幂等与去重
- upsert 主键 `(ts_code, trade_date)`，重复拉取可覆盖更新

4. 进度上报（面向用户）
- `cyq_perf: 交易日=2026-04-15 分页=2/2 获取=5494 写入=5494`

---

## 7. Ops 交互与观测

### 7.1 手动任务交互

1. 第一步：选择维护对象「每日筹码及胜率」
2. 第二步：时间参数（单日 / 区间）
3. 第三步：其他输入条件（可选 `ts_code`）

分页参数不暴露给用户。

### 7.2 自动任务

- 纳入股票分组自动任务能力：
  - 日常自动：按 `trade_date` 执行
- 数据状态分组：股票
- 节奏：daily
- 业务日期列：`trade_date`

---

## 8. 测试与验收计划

### 8.1 单测

- 参数校验（`trade_date` / `start_date+end_date`）
- 交易日历扇出逻辑
- 分页循环（`limit/offset/has_more`）
- upsert 幂等

### 8.2 集成/回归

- 手动任务触发 + 落库
- 自动任务触发 + 数据状态更新时间
- 对现有股票类数据集无回归影响

### 8.3 验收标准

- 输出字段全量落库
- 历史回补按交易日推进且可分页拉完
- 单日增量稳定 1~2 次请求可完成
- 数据状态正确显示日期范围与同步状态

---

## 9. 风险与应对

1. 风险：个别日期股票数继续增长，单日超过 5,000。
- 应对：分页已内建，无需改交互。

2. 风险：接口偶发无数据/慢响应。
- 应对：分页页级重试 + 可读错误透传。

3. 风险：配额被其他任务占用。
- 应对：优先采用 date-loop 降低请求量，必要时限流。

---

## 10. 开发清单（通过评审后执行）

1. 新增模型与迁移：
- `raw_tushare.cyq_perf`
- `core_serving.equity_cyq_perf`

2. 新增同步服务：
- `SyncCyqPerfService`
- 接入 `sync registry`

3. 接入 Ops：
- job spec（daily/history）
- 数据状态 freshness 元数据
- 自动工作流（股票日收盘同步）接入

4. 测试补齐与文档索引更新。

