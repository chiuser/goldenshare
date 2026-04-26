# Tushare 概念板块资金流向（THS）（`moneyflow_cnt_ths`）数据集开发说明

## 0. 当前架构基线（必须遵守）

本数据集结论：

- 该数据集是否对外服务：是
- 当前是否多源：否（仅 `tushare`）
- 是否已具备 std 映射与融合策略：否
- 本次 target_table 选择：`core_serving.concept_moneyflow_ths`
- 路径选择：`raw_tushare -> core_serving`（单源直出）

---

## 1. 标准交付流程（本数据集）

1. 固定上游接口 `moneyflow_cnt_ths`（doc_id=371）。
2. 明确板块级时间同步与可选代码过滤逻辑。
3. 设计 `raw_tushare.moneyflow_cnt_ths` 与 `core_serving.concept_moneyflow_ths`。
4. 打通 Ops 任务与健康度观测。
5. 完成测试与回归。

---

## 2. 基本信息

- 数据集名称：概念板块资金流向（THS）
- 资源 key：`moneyflow_cnt_ths`
- 所属域：板块与热榜
- 数据源：`tushare`
- 官方文档链接：<https://tushare.pro/document/2?doc_id=371>
- API 名称：`moneyflow_cnt_ths`
- 文档抓取日期：`2026-04-17`

---

## 3. 接口分析

### 3.1 输入参数（上游原生）

| 参数名 | 类型 | 必填 | 说明 | 类别 | 是否暴露给用户 | 前端控件 | 执行层映射 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ts_code` | str | 否 | 板块代码 | 代码 | 是（可选） | 代码输入 | 直传 |
| `trade_date` | str | 否 | 交易日期 | 时间 | 是 | 单日选择器 | 直传 |
| `start_date` | str | 否 | 开始日期 | 时间 | 是 | 区间选择器 | 直传 |
| `end_date` | str | 否 | 结束日期 | 时间 | 是 | 区间选择器 | 直传 |

### 3.2 输出字段（上游原生）

| 字段名 | 类型 | 含义 | 是否落库 |
| --- | --- | --- | --- |
| `trade_date` | str | 交易日期 | 是 |
| `ts_code` | str | 板块代码 | 是 |
| `name` | str | 板块名称 | 是 |
| `lead_stock` | str | 领涨股票名称 | 是 |
| `close_price` | float | 最新价 | 是 |
| `pct_change` | float | 涨跌幅（%） | 是 |
| `industry_index` | float | 板块指数 | 是 |
| `company_num` | int | 公司数量 | 是 |
| `pct_change_stock` | float | 领涨股涨跌幅 | 是 |
| `net_buy_amount` | float | 净买入（万元） | 是 |
| `net_sell_amount` | float | 净卖出（万元） | 是 |
| `net_amount` | float | 净额（万元） | 是 |

### 3.3 同步策略结论

- 是否支持单次时间点：是
- 是否支持区间回补：是
- 时间粒度：日
- 时间推进策略：交易日历逐日推进
- 是否需要分页循环：否（接口无分页参数）
- 是否有级联依赖：否

推荐最省力拉取方式：

- 默认按交易日逐日全量请求（不传 `ts_code`）。
- `ts_code` 用于单板块修复。

---

## 4. 参数与交互设计（Ops）

### 4.1 手动任务交互

1. 第一步：板块与热榜 -> 概念板块资金流向（THS）
2. 第二步：时间参数（单日/区间）
3. 第三步：其他输入条件（可选 `ts_code`）

### 4.2 自动任务交互

- 资源：`moneyflow_cnt_ths.maintain`
- 默认仅 `trade_date`

---

## 5. 落库与发布设计

### 5.1 路径选择

- 路径类型：`raw -> core_serving`
- 选择理由：单源直出，便于业务侧直接消费板块资金流
- 是否为临时方案：是

### 5.2 表设计

#### A. `raw_tushare.moneyflow_cnt_ths`

- 主键：`(trade_date, ts_code)`
- 审计字段：`api_name`, `fetched_at`, `raw_payload`
- 索引：
  - `idx_raw_tushare_moneyflow_cnt_ths_trade_date(trade_date)`
  - `idx_raw_tushare_moneyflow_cnt_ths_ts_code_trade_date(ts_code, trade_date)`

#### B. `core_serving.concept_moneyflow_ths`

- 主键：`(trade_date, ts_code)`
- 索引：
  - `idx_concept_moneyflow_ths_trade_date(trade_date)`
  - `idx_concept_moneyflow_ths_ts_code_trade_date(ts_code, trade_date)`

---

## 6. 维护实现设计

- IngestionExecutor / SourceClient：`moneyflow_cnt_ths` 数据集维护链路
- `target_table`：`core_serving.concept_moneyflow_ths`
- 参数构建：
  - `moneyflow_cnt_ths.maintain`：`trade_date` 或 `start_date+end_date`（可选 `ts_code`）
- 幂等：主键 upsert
- 进度日志示例：
  - `moneyflow_cnt_ths: 31/83 trade_date=2026-04-16 fetched=412 written=412`

---

## 7. 数据状态与健康度观测

- 分组：资金流向
- 观测列：`trade_date`
- 展示名：概念板块资金流向（THS）

---

## 8. 测试与验收

- 单测：参数映射、交易日历推进、upsert 幂等
- 集成：`moneyflow_cnt_ths.maintain`（单日/区间）
- 回归：不影响 `dc_index/dc_member/ths_*` 现有链路

---

## 9. 发布与回滚

- 迁移：新增 `raw_tushare.moneyflow_cnt_ths`、`core_serving.concept_moneyflow_ths`
- 回滚：代码回滚 + 停止任务；表数据保留

---

## 10. 已拍板结论（本数据集）

1. 纳入独立工作流：每日资金流向同步。
2. 不并入其它工作流。
3. 数据状态分组归属：资金流向。
