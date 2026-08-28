# Tushare 每日停复牌信息（`suspend_d`）数据集开发说明

- 当前状态（2026-08-28）：raw 直出 M1 代码与自动化测试已完成；生产仍需经过隔离 PostgreSQL M2 和独立授权的生产 M3，不能把本文目标结构误读为已经切换。

## 1. 目标与边界

- 目标：维护 `suspend_d` 数据集，并在不改变下游读取合同的前提下，以 `raw_tushare.suspend_d` 作为唯一物理事实表、`core_serving.equity_suspend_d` 作为只读兼容 view。
- 本期边界：
  - 先做 `tushare` 单源，不做多源融合。
  - 已纳入 `daily_market_close_maintenance` 工作流；手动任务和自动工作流共用同一 Definition/planner/request 契约。
  - `suspend_d.maintain` 必须显式传时间参数（`trade_date` 或 `start_date+end_date`），禁止无时间全量。

## 2. 上游接口

- 文档：<https://tushare.pro/document/2?doc_id=214>
- API：`suspend_d`
- 描述：按日期获取股票每日停复牌信息（不定期更新）。
- 文档抓取日期：`2026-04-16`

## 3. 参数与字段

### 3.1 输入参数（上游原生）

| 参数名 | 类型 | 必填 | 说明 | 类别 | 是否暴露给用户 | 前端控件 | 执行层映射 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ts_code` | str | 否 | 股票代码（如 `000001.SZ`） | 代码 | 是（可选） | 文本输入 | 原样传递 |
| `trade_date` | str | 否 | 交易日期（YYYYMMDD） | 时间 | 是 | 日期选择器（单日） | UI 日期 -> YYYYMMDD |
| `suspend_type` | str | 否 | 停复牌类型（`S` 停牌 / `R` 复牌） | 枚举 | 是（可选） | 多选下拉 | 未选时不传；选择一个或多个值时由 planner 按合法单值扇出，源端永远只接收 `S` 或 `R` 字符串 |

### 3.2 输出字段（上游原生，全量落库）

| 字段名 | 类型 | 含义 | 是否落库 |
| --- | --- | --- | --- |
| `ts_code` | str | 股票代码 | 是 |
| `trade_date` | str/date | 交易日期 | 是 |
| `suspend_timing` | str | 停牌时段 | 是 |
| `suspend_type` | str | 停复牌类型（S 停牌 / R 复牌） | 是 |

### 3.3 同步策略结论

- 是否支持单次时间点：是（`trade_date`）
- 是否支持区间回补：是（`start_date+end_date`，执行层按日扇出）
- 时间粒度：日
- 时间推进策略：交易日历（按开市日期推进）
- 是否需要分页循环：是；按现有通用 `offset/limit` 分页，`page_limit=5000`，短页结束，不设置任意最大页数
- 是否有级联依赖：否

2026-08-28 使用 `tushareMcp` 对 `trade_date=20260827`、显式四个 source fields 做了最小真实验证：不传 `suspend_type` 返回 4 行，`S` 返回 3 行，`R` 返回 1 行，且 `S/R` 多重集并集与无过滤结果一致；把列表错误转换为 `"['S', 'R']"` 时源端返回 `50101`。因此多选是运营意图，不能直接作为源参数；必须先在 planner 中拆成单值 unit。

## 4. 参数与交互设计（Ops）

### 4.1 手动任务

1. 第一步：选择要维护的数据（股票 -> 每日停复牌信息）。
2. 第二步：时间参数
  - 单日：选择一个日期（映射 `trade_date`）
  - 区间：开始日期 + 结束日期（执行层按交易日历逐日映射为 `trade_date` 请求）
3. 第三步：其他输入条件
  - `股票代码`（可选）
  - `停复牌类型`（可选多选；不选表示全部，选择 `S/R` 时分别形成合法源请求）

### 4.2 自动任务

- 保持统一模型：单次 / 每日 / 每周 / 每月 + 时间选择器。
- 业务化配置，不向用户暴露底层字段名。

## 5. 落库设计

### 5.1 路径选择

- 路径类型：`raw_tushare.suspend_d -> core_serving.equity_suspend_d view`（raw 直出）
- 唯一物理事实表：`raw_tushare.suspend_d`；ingestion 只执行 `raw_only_upsert`。
- 对下游合同：保留 `core_serving.equity_suspend_d` 名称和显式列投影，view 禁止三类 DML；查询由 PostgreSQL 下推到 raw 的等价索引。
- 存储边界：raw heap 与索引继续位于 SSD `pg_default`，本项不迁 HDD；切换只释放原 serving 物理表。

### 5.2 表设计

#### A. `raw_tushare.suspend_d`

- 审计字段：`api_name`, `fetched_at`, `raw_payload`
- 业务字段：`ts_code`, `trade_date`, `suspend_timing`, `suspend_type`
- 字段长度：
  - `suspend_timing`：`varchar(128)`，源端可能返回多个日内停牌时段，例如 `09:30-10:31,10:31-13:02,13:42-14:57`，禁止截断。
  - `suspend_type`：`varchar(16)`，当前枚举为 `S` / `R`。
- 索引：
  - `uq_raw_tushare_suspend_d_row_key_hash(row_key_hash)`
  - `idx_raw_tushare_suspend_d_trade_date(trade_date)`
  - `idx_raw_tushare_suspend_d_ts_code_trade_date(ts_code, trade_date)`

#### B. `core_serving.equity_suspend_d`

- 对象类型：只读普通 view，不再保存第二份物理数据。
- 对外字段显式固定为：`id`, `row_key_hash`, `ts_code`, `trade_date`, `suspend_timing`, `suspend_type`, `created_at`, `updated_at`。
- `created_at/updated_at` 均映射 raw `fetched_at`；已登记消费者不读取这两个审计字段，不承诺保留旧 serving 历史 `created_at` 的差异。
- 字段长度与 raw 保持一致，`suspend_timing` 为 `varchar(128)`，不得截断日内多时段信息。
- view 本身没有物理索引；原有查询依赖 raw 的唯一索引、`trade_date` 索引和 `(ts_code, trade_date)` 索引完成下推。
- 独立 `INSTEAD OF INSERT OR UPDATE OR DELETE` trigger 统一以 SQLSTATE `55000` 拒绝写入。

### 5.3 幂等与切换门禁

- 写入冲突键固定为 `row_key_hash`；raw 物理主键继续为自增 `id`，不修改共享 upsert。
- migration 按自然月对比 `id, row_key_hash, ts_code, trade_date, suspend_timing, suspend_type` 的双向 `EXCEPT ALL`，并验证每月 `id/row_key_hash` 均无重复。
- 月容量上限固定为 20,000 行；任一层超限、任一字段差异、身份重复、对象/索引/权限/依赖漂移都必须在 serving DDL 前失败。
- migration 不执行 `CASCADE`、不修改 raw 数据或索引、不提供自动 downgrade。

## 6. 维护实现设计

- IngestionExecutor / SourceClient：`suspend_d` 数据集维护链路
- `target_table`：`raw_tushare.suspend_d`
- 参数构建规则：
  - `suspend_d.maintain`：`trade_date` 或 `start_date+end_date`
  - 区间模式：按 SSE 开市日逐日调用上游（每次传 `trade_date`）
  - `suspend_type`：未填写时不传；单选生成 1 个单值 unit；多选按去重后的 `S/R` 分别生成 unit；request builder 遇到未展开列表必须 fail-closed，禁止字符串化后请求源端
- 写入规则：
  - 只 upsert `raw_tushare.suspend_d`
  - `core_serving.equity_suspend_d` 由 view 同事务即时可见，不再发生 serving DAO 写入
- 进度事件（用户可读）：
  - `suspend_d: 3/15 date=2026-04-10 fetched=xx written=xx`
  - 明确展示当前日期推进进度与读写统计。

## 7. 数据状态与健康度观测

- 数据状态页分组：`股票`
- 健康度口径：
  - 展示日期范围：`trade_date` 最小~最大
  - 同时展示最近同步日期（来自任务成功时间）
- 异常展示：中文摘要 + 原始错误可展开

## 8. 测试与验收（计划）

- 单元测试：
  - 参数映射（单日/区间/可选枚举）
  - 无类型单 unit、单选单 unit、多选按日期和类型笛卡尔展开、非法枚举拒绝、request builder 拒绝未展开列表
  - 区间 SSE 开市日推进
  - raw-only writer 只调用 `raw_suspend_d` DAO，冲突键为 `row_key_hash`
  - ORM 字段、主键和三组 raw/serving 现存索引合同
  - migration 顺序、20,001 行超限、全字段/双身份差异、未知依赖、三类拒写、事务回滚和离线 PostgreSQL SQL
- 集成测试：
  - `suspend_d.maintain`（单日/区间）
  - Ops 手动任务参数链路
- 回归测试：
  - 不影响现有股票日频数据集（`moneyflow/limit_list_d/stk_limit/stk_nineturn`）

## 9. 风险与讨论点（请你 review）

1. 主键与幂等策略：采用 `row_key_hash`（已拍板）。
2. 数据状态分组：归到“股票”（已拍板）。
3. 自动任务：默认开放创建（已拍板）。
