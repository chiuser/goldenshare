# Tushare 个股资金流向（THS）（`moneyflow_ths`）数据集开发说明

## 0. 当前架构基线（必须遵守）

本数据集结论：

- 该数据集是否对外服务：是
- 当前是否多源：否（仅 `tushare`）
- 是否已具备 std 映射与融合策略：否
- 当前代码 target_table：`raw_tushare.moneyflow_ths`
- 当前生产路径：`raw_tushare + core_serving` 两张物理表、`raw_core_upsert`
- raw 直出专项目标：`raw_tushare.moneyflow_ths` 唯一物理事实表，原 `core_serving.equity_moneyflow_ths` 名称保留为只读 view
- 当前阶段：`P1-B3-moneyflow_ths-M0/M1` 已通过；生产尚未应用 revision 159，仍是双物理表和既有双写部署

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

| 参数名 | 类型 | 必填 | 说明 | 类别 | 是否暴露给运营 | 前端控件 | 执行层映射 |
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

- 资源：`moneyflow_ths.maintain`
- 默认参数：仅 `trade_date`（由调度注入）
- 可选扩展：`ts_code`

---

## 5. 落库与发布设计

### 5.1 路径选择

- 当前路径：同一 normalized batch 同时 upsert `raw_tushare.moneyflow_ths` 与 `core_serving.equity_moneyflow_ths`
- M1 已实现路径：只 upsert Raw，原 Serving 名称由 revision 159 改为显式列投影的只读 view
- 选择理由：M0 已证明两层全部 13 个业务字段、主键和 21 个自然月数据完全一致，当前没有 Serving 专属业务转换
- 不在本次范围：引入 std、多源融合、修改 Tushare fields/分页/日期模型、修改 Ops 输入或自动任务时间

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
- 当前形态：生产物理表；M1 已实现只读 view migration，但尚未在隔离库或生产应用
- 目标形态：保留原 relation 名的普通只读 view；13 个业务字段同名投影，`fetched_at AS created_at/updated_at`
- 索引：
  - `idx_equity_moneyflow_ths_trade_date(trade_date)`
  - `idx_equity_moneyflow_ths_ts_code_trade_date(ts_code, trade_date)`
- 透明边界：业务字段、名称和查询结果保持；不承诺 OID、relkind、view 自身约束/index catalog 与历史 `created_at` 值透明

---

## 6. 维护实现设计

- IngestionExecutor / SourceClient：`moneyflow_ths` 数据集维护链路
- 当前代码 `target_table`：`raw_tushare.moneyflow_ths`；Serving 仍通过原名称读取
- 当前生产部署仍是旧双写版本，必须等 M2 通过和 M3a 独立授权后才能切换
- 参数构建：
  - `moneyflow_ths.maintain`：`trade_date` 或 `start_date+end_date` + 可选 `ts_code`
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
  - `moneyflow_ths.maintain`（单日/区间）
  - Ops 手动/自动任务链路
- 回归测试：
  - 不影响既有 `moneyflow` / `moneyflow_dc` 等数据集

### 8.2 验收勾选

- [x] 输出字段全量显式请求并落入当前 Raw/Serving
- [x] Ops 手动/自动任务、分页和日期推进合同已存在
- [x] 数据状态页可按 `trade_date` 展示
- [x] M0 已完成 21 月、2,077,033 行、13 字段生产只读等价审计
- [x] M1 raw-only Definition、ORM metadata、独立 migration 和自动化测试
- [ ] M2 隔离 PostgreSQL 验证
- [ ] M3a 生产切换与即时验收
- [ ] M3b 首个自然工作流验收

---

## 9. raw 直出后续发布与回滚

- M1：只修改本数据集 storage contract、Raw ORM 的既存索引 metadata、独立 migration 和测试。
- M2：在隔离 PostgreSQL 验证 150,000/150,001 行容量、全字段/身份差异、依赖、ACL/comment、三类 DML、回滚、writer 与查询计划。
- M3a：实时暂停 schedule #4、停止 generic worker、最终对账后使用维护迁移模式切换；回收连接池、执行最小 TaskRun 后恢复 schedule。
- 自动 downgrade 禁止；DDL 提交前失败由同一事务原子回滚，提交后的物理回退必须另行授权并从 Raw 重建。

---

## 10. 已拍板结论（本数据集）

1. 自动任务默认不暴露 `ts_code`，仅保留手动页定向补数。
2. 单次返回触顶（6000）时，优先走 `limit` + `offset` 自动分页补齐，不启用 `ts_code` 二级扇出。
3. 纳入独立工作流：每日资金流向同步，不并入其它工作流。
4. 数据状态分组归属：资金流向。

---

## 11. 2026-08-29 `P1-B3-moneyflow_ths-M0` 只读审计结论

1. 当前生产 Raw/Serving 各 2,077,033 行，日期范围 `2024-12-19..2026-08-28`，21 个自然月全部 13 个业务字段双向 `EXCEPT ALL` 为 0；身份空值和 Raw `api_name` 异常均为 0。
2. 两层主键都是 `(trade_date, ts_code)`，日期与 `(ts_code, trade_date)` 索引等价。Raw ORM 漏声明两个生产既存二级索引，M1 只补 metadata，不重建索引。
3. 自然月峰值 116,993 行，业务行最大 134 B；M1 固定 150,000 行/层/月安全上限，M2 必须验证 150,001 行在 Serving DDL 前失败。
4. 五类 Raw/Serving 代表查询结果一致、索引正确、无临时块，Raw 最大正向退化约 9.43%，不需要复制竞价开盘数据集的 vacuum。
5. Lake Console 已直接读 Raw；仓库内未发现 Biz、QTF、frontend、DG 或脚本直接读取 Serving。唯一自动入口为 schedule #4 `daily_moneyflow_maintenance`，未来 M3a 只暂停/恢复该 schedule。
6. 35,990 行旧 Serving 的 `created_at != updated_at`；仓库内无审计时间消费者。目标 view 按一期固定边界把 Raw `fetched_at` 同时投影为 `created_at/updated_at`，业务字段透明，但历史 `created_at` 不属于透明承诺。
7. M0 结论：**通过，可在独立授权后进入 M1**。M0 没有修改代码、数据库、schedule 或任务，也没有请求 Tushare。

---

## 12. 2026-08-29 `P1-B3-moneyflow_ths-M1` 实施结论

1. Definition 只修改 storage delivery contract：Raw/`target_table`/freshness 统一指向 `raw_tushare.moneyflow_ths`，写路径改为 `raw_only_upsert`；13 个 source fields、交易日逐 unit、可选 `ts_code`、6,000 行分页、手动/定时/重试能力均保持不变。
2. Raw ORM 只补生产已存在的 `trade_date` 与 `(ts_code, trade_date)` 两个索引 metadata；revision 159 不创建、删除或重建 Raw 表和索引。
3. 独立 migration `20260829_000159` 接真实 head `20260829_000158`，固定 Raw→Serving 锁序、16 MiB `work_mem`、15 秒锁等待、120 秒 statement timeout、150,000 行/层/月容量门禁、13 字段双向 `EXCEPT ALL`、`(trade_date, ts_code)` 唯一性、对象依赖/ACL/comment/索引/tablespace 门禁和三类 DML 拒绝；禁止 `CASCADE`、共享拒写函数重建和自动 downgrade。
4. 专项与共享回归覆盖 Definition/plan/filter、ORM 类型/空值/主键/索引、Raw-only writer、Raw freshness/date-completeness target、ServingPublish 旁路、migration 离线 SQL 与禁止项；M1 未连接数据库、未请求 Tushare、未部署、未创建 TaskRun、未修改 schedule #4。
5. M1 结论：**通过**。下一阶段仅为另行授权的 M2，在隔离 PostgreSQL 验证 150,000/150,001 行、原子回滚、权限与三类 DML、正式 writer 即时可见和查询计划；不得把本轮代码测试当成数据库验收或生产切换证据。
