# Tushare 板块资金流向（DC）（`moneyflow_ind_dc`）数据集开发说明

## 0. 当前架构基线（必须遵守）

本数据集结论：

- 该数据集是否对外服务：是
- 当前是否多源：否（仅 `tushare`）
- 是否已具备 std 映射与融合策略：否
- 本次 target_table 选择：`core_serving.board_moneyflow_dc`
- 路径选择：`raw_tushare -> core_serving`（单源直出）

---

## 1. 标准交付流程（本数据集）

1. 固定上游接口 `moneyflow_ind_dc`（doc_id=344）。
2. 明确 `content_type` 扇开策略与唯一键设计。
3. 设计 `raw_tushare.moneyflow_ind_dc` 与 `core_serving.board_moneyflow_dc`。
4. 打通 Ops 配置与观测。
5. 完成测试与回归。

---

## 2. 基本信息

- 数据集名称：板块资金流向（DC）
- 资源 key：`moneyflow_ind_dc`
- 所属域：板块与热榜
- 数据源：`tushare`
- 官方文档链接：<https://tushare.pro/document/2?doc_id=344>
- API 名称：`moneyflow_ind_dc`
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
| `content_type` | str | 否 | 板块类型（`行业`、`概念`、`地域`） | 枚举 | 是 | 多选下拉（勾选） | 扇开请求 |
| `limit` | int | 否 | 单次返回数据长度 | 分页 | 否 | 不暴露 | 执行层自动注入 |
| `offset` | int | 否 | 请求数据开始位移 | 分页 | 否 | 不暴露 | 执行层自动注入 |

### 3.2 输出字段（上游原生）

| 字段名 | 类型 | 含义 | 是否落库 |
| --- | --- | --- | --- |
| `trade_date` | str | 交易日期 | 是 |
| `content_type` | str | 板块类型（行业/概念/地域） | 是 |
| `ts_code` | str | 板块代码 | 是 |
| `name` | str | 板块名称 | 是 |
| `pct_change` | float | 板块涨跌幅（%） | 是 |
| `close` | float | 板块最新指数 | 是 |
| `net_amount` | float | 今日主力净流入净额（元） | 是 |
| `net_amount_rate` | float | 今日主力净流入最大股占比（%） | 是 |
| `buy_elg_amount` | float | 今日超大单净流入净额（元） | 是 |
| `buy_elg_amount_rate` | float | 今日超大单净流入净占比（%） | 是 |
| `buy_lg_amount` | float | 今日大单净流入净额（元） | 是 |
| `buy_lg_amount_rate` | float | 今日大单净流入净占比（%） | 是 |
| `buy_md_amount` | float | 今日中单净流入净额（元） | 是 |
| `buy_md_amount_rate` | float | 今日中单净流入净占比（%） | 是 |
| `buy_sm_amount` | float | 今日小单净流入净额（元） | 是 |
| `buy_sm_amount_rate` | float | 今日小单净流入净占比（%） | 是 |
| `buy_sm_amount_stock` | str | 今日主力净流入最大股 | 是 |
| `rank` | int | 板块涨跌排名 | 是 |

### 3.3 同步策略结论

- 是否支持单次时间点：是
- 是否支持区间回补：是
- 时间粒度：日
- 时间推进策略：交易日历逐日
- 是否需要分页循环：是（接口支持 `limit` / `offset`）
- 是否有级联依赖：否

推荐最省力拉取方式：

- 默认按交易日 + `content_type` 扇开请求。
- 若 `content_type` 未指定，默认请求三类中文枚举（`行业/概念/地域`）。
- 单次结果达到上限时，执行层自动按 `limit` + `offset` 分页拉取并合并。

---

## 4. 参数与交互设计（Ops）

### 4.1 手动任务交互

1. 第一步：板块与热榜 -> 板块资金流向（DC）
2. 第二步：时间参数（单日/区间）
3. 第三步：其他输入条件（`content_type` 多选 + 可选 `ts_code`）

### 4.2 自动任务交互

- 资源：`moneyflow_ind_dc.maintain`
- 默认策略：`content_type` 全选扇开

---

## 5. 落库与发布设计

### 5.1 路径选择

- 路径类型：`raw -> core_serving`
- 选择理由：单源、字段结构稳定、直接对外服务
- 是否为临时方案：是

### 5.2 表设计

#### A. `raw_tushare.moneyflow_ind_dc`

- 主键：`(trade_date, content_type, name)`
- 额外字段：`content_type`（从请求参数回写，便于唯一性与审计）
- 审计字段：`api_name`, `fetched_at`, `raw_payload`
- 索引：
  - `idx_raw_tushare_moneyflow_ind_dc_trade_date(trade_date)`
  - `idx_raw_tushare_moneyflow_ind_dc_content_type_trade_date(content_type, trade_date)`

#### B. `core_serving.board_moneyflow_dc`

- 主键：`(trade_date, content_type, name)`
- 索引：
  - `idx_board_moneyflow_dc_trade_date(trade_date)`
  - `idx_board_moneyflow_dc_content_type_trade_date(content_type, trade_date)`

---

## 6. 维护实现设计

- IngestionExecutor / SourceClient：`moneyflow_ind_dc` 数据集维护链路
- `target_table`：`core_serving.board_moneyflow_dc`
- 参数构建：
  - `moneyflow_ind_dc.maintain`：`trade_date` 或 `start_date+end_date` + `content_type[]`（可选 `ts_code`）
- 扇开策略：`content_type` 多选逐个请求后合并写入
- 分页策略：每个 `trade_date + content_type` 组合内，自动用 `limit` + `offset` 分页直至取完
- 幂等：按主键 upsert
- 进度日志示例：
  - `moneyflow_ind_dc: 9/83 trade_date=2026-04-16 content_type=概念 page=1 fetched=132 written=132`

---

## 7. 数据状态与健康度观测

- 分组：资金流向
- 观测列：`trade_date`
- 展示名：板块资金流向（DC）

---

## 8. 测试与验收

- 单测：`content_type` 扇开、参数校验、upsert 幂等
- 集成：`moneyflow_ind_dc.maintain`（单日/区间）
- 回归：不影响 `moneyflow_ind_ths`、`dc_*` 板块链路

---

## 9. 发布与回滚

- 迁移：新增 `raw_tushare.moneyflow_ind_dc`、`core_serving.board_moneyflow_dc`
- 回滚：回滚代码与任务注册，保留历史数据

---

## 10. 已拍板结论（本数据集）

1. `content_type` 默认策略：全选扇开（行业+概念+地域）。
2. 运营页参数：暴露 `content_type` 多选。
3. 分页策略：启用 `limit` + `offset` 自动分页补齐。
4. 纳入独立工作流：每日资金流向同步，不并入其它工作流。
5. 数据状态分组归属：资金流向。
