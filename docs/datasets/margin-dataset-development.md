# Tushare 融资融券交易汇总（`margin`）数据集开发说明

## 0. 当前架构基线（必须遵守）

本数据集结论：

- 该数据集是否对外服务：是
- 当前是否多源：否（仅 `tushare`）
- 是否已具备 std 映射与融合策略：否
- 本次 target_table 选择：`core_serving.equity_margin`
- 路径选择：`raw_tushare -> core_serving`（单源直出）

---

## 1. 标准交付流程（本数据集）

1. 固定上游接口 `margin`（doc_id=58）。
2. 明确输入输出与执行口径（按日期循环 + 交易所扇开）。
3. 设计 `raw_tushare.margin` 与 `core_serving.equity_margin`。
4. 打通 Ops（手动/自动）与健康度观测。
5. 完成测试与回归。

---

## 2. 基本信息

- 数据集名称：融资融券交易汇总
- 资源 key：`margin`
- 所属域：股票
- 数据源：`tushare`
- 官方文档链接：<https://tushare.pro/document/2?doc_id=58>
- API 名称：`margin`
- 文档抓取日期：`2026-04-16`

---

## 3. 接口分析

### 3.1 输入参数（上游原生）

| 参数名 | 类型 | 必填 | 说明 | 类别（时间/枚举/代码/分页） | 是否暴露给用户 | 前端控件 | 执行层映射 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `trade_date` | str | 否 | 交易日期（YYYYMMDD） | 时间 | 是 | 日期选择器（单日） | UI 日期 -> `trade_date` |
| `start_date` | str | 否 | 开始日期（YYYYMMDD） | 时间 | 是 | 日期区间 | UI 日期区间 -> `start_date` |
| `end_date` | str | 否 | 结束日期（YYYYMMDD） | 时间 | 是 | 日期区间 | UI 日期区间 -> `end_date` |
| `exchange_id` | str | 否 | 交易所代码（`SSE/SZSE/BSE`） | 枚举 | 是 | 多选下拉（勾选） | 执行层逐交易所扇开请求 |

### 3.2 输出字段（上游原生）

| 字段名 | 类型 | 含义 | 是否落库 |
| --- | --- | --- | --- |
| `trade_date` | str | 交易日期 | 是 |
| `exchange_id` | str | 交易所代码 | 是 |
| `rzye` | float | 融资余额（元） | 是 |
| `rzmre` | float | 融资买入额（元） | 是 |
| `rzche` | float | 融资偿还额（元） | 是 |
| `rqye` | float | 融券余额（元） | 是 |
| `rqmcl` | float | 融券卖出量（股/份/手） | 是 |
| `rzrqye` | float | 融资融券余额（元） | 是 |
| `rqyl` | float | 融券余量（股/份/手） | 是 |

### 3.3 同步策略结论（必须）

- 是否支持单次时间点：是
- 是否支持区间回补：是
- 时间粒度：日
- 时间推进策略：交易日历（日历日区间 -> 交易日序列）
- 是否需要分页循环：否
- 是否有级联依赖：否

关键口径（本次评审重点）：

- **区间同步按交易日逐日请求**（不是一把区间请求）。
- **交易所按扇开执行**：`SSE/SZSE/BSE` 分别请求，不使用逗号拼接。

---

## 4. 参数与交互设计（Ops）

### 4.1 手动任务交互

1. 第一步：选择要维护的数据  
数据分组：股票  
维护对象：融资融券交易汇总
2. 第二步：时间参数  
支持单日、区间
3. 第三步：其他输入条件  
交易所（多选）

交互规则：

- 未选交易所：默认扇开全部交易所（`SSE/SZSE/BSE`）。
- 已选交易所：仅扇开所选交易所。

### 4.2 自动任务交互

- 资源：`margin.maintain`
- 可配交易所多选；未配置时默认全交易所。
- 仍保留统一调度模式（单次/每日/每周/每月）。

---

## 5. 落库与发布设计

### 5.1 路径选择（必填）

- 路径类型：`raw -> core_serving`
- 选择理由：当前单源场景，先稳定落地；后续多源再引入 `std + resolution`
- 是否为临时方案：是
- 后续收敛计划：引入第二数据源后升级为 `raw_* -> *_std -> core_serving`

### 5.2 表设计

#### A. `raw_tushare.margin`

- 主键策略：`(trade_date, exchange_id)` 复合业务键
- 字段清单：
  - 业务字段：`trade_date`, `exchange_id`, `rzye`, `rzmre`, `rzche`, `rqye`, `rqmcl`, `rzrqye`, `rqyl`
  - 审计字段：`api_name`, `fetched_at`, `raw_payload`
- 索引：
  - `idx_raw_tushare_margin_trade_date(trade_date)`
  - `idx_raw_tushare_margin_exchange_trade_date(exchange_id, trade_date)`

#### B. `core_serving.equity_margin`

- 对外字段口径：与上游业务字段一致（不包含 raw 审计字段）
- upsert 主键：`(trade_date, exchange_id)`
- 索引：
  - `idx_equity_margin_trade_date(trade_date)`
  - `idx_equity_margin_exchange_trade_date(exchange_id, trade_date)`

---

## 6. 维护实现设计

- IngestionExecutor / SourceClient：`margin` 数据集维护链路
- `target_table`：`core_serving.equity_margin`
- 参数构建规则：
  - `margin.maintain`：`trade_date` 或 `start_date + end_date` + `exchange_id`（可选，多选）
- 执行策略：
  - 区间 -> 交易日序列
  - 每个交易日内 -> 交易所扇开
- 幂等写入策略：`trade_date + exchange_id` upsert
- 进度日志示例：
  - `margin: 18/102 trade_date=2026-04-15 exchange=SZSE fetched=1 written=1`
- 异常处理：
  - 参数非法：中文提示（区间为空、起止倒置等）
  - 上游失败：按现有客户端重试策略

---

## 7. 数据状态与健康度观测

- 数据状态分组：股票
- 健康度口径：
  - 日期范围：`trade_date` 最小值~最大值
  - 最近同步时间：取最近成功任务时间
- 异常展示：中文摘要 + 原始错误追踪
- 自动任务覆盖标识：纳入

---

## 8. 测试与验收

### 8.1 测试清单

- 单元测试：
  - 参数映射（单日/区间/交易所多选）
  - 交易所扇开逻辑（默认全量、指定子集）
  - 区间按交易日历推进
  - upsert 幂等
- 集成测试：
  - `margin.maintain`（单日/区间）
  - Ops 手动与自动任务参数链路
- 回归测试：
  - 不影响既有股票日频数据集任务

### 8.2 验收勾选

- [ ] 输出字段全量落库
- [ ] 交易所扇开逻辑生效
- [ ] 手动任务满足 1-2-3 步交互规范
- [ ] 自动任务可配置并可观察
- [ ] 数据状态可展示日期范围与最近同步时间

---

## 9. 发布与回滚

- 迁移：新增 `raw_tushare.margin` 与 `core_serving.equity_margin`
- 发布顺序：
  1. 执行数据库迁移
  2. 部署代码
  3. 触发一次 `margin.maintain` 验证
- 回滚：
  - 回滚代码版本
  - 回退任务注册（如已上线）
  - 保留数据表，避免回滚过程中丢历史

---

## 10. 本次交付快照

- 当前已支持（设计）：日期循环、交易所扇开、单源直出、Ops 手动/自动参数模型
- 当前不支持：多源融合（`std/resolution`）
- 后续计划：引入第二数据源后升级融合策略与发布链路
