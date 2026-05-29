# Dagster Adj Factor 资产设计

状态：设计口径已确认；M1 契约基础已实现；M2 bootstrap spec 已实现；M3 assets/checks 已实现；M4 job/sensors 已实现；历史 bootstrap 迁移尚未执行。

本文只定义 `adj_factor`（复权因子）这个数据资产在新 Dagster lake 中的正式口径。分钟线前复权、受影响股票回刷、指标重算等下游设计不放在本文中。

## 1. 目标

把复权因子作为股票行情域的日频基础事实资产接入新 Dagster lake：

- `raw_tushare_adj_factor`：Tushare `adj_factor` 源站镜像。历史数据先从旧湖 bootstrap 到新湖 raw；日常按交易日从 Tushare 更新。
- `silver_adj_factor`：从 raw 生成的标准层复权因子，只保留当前上市股票，并确保每个应覆盖交易日都有因子值。

核心原则：

1. raw 层保存 Tushare 源字段契约，不把旧湖物理类型当成新湖 raw 契约。
2. silver 层负责过滤退市股票、标准化日期类型和做完整性门禁。
3. 分区模型按交易日，与 `raw_tushare_suspend_d` / `silver_stock_suspend_daily` 一致。
4. bootstrap 只是历史迁移来源，不进入 asset 命名；正式 asset 仍以长期来源和业务语义命名。
5. 不设计复权因子历史版本资产；新湖维护一套最新口径复权因子事实。

## 2. 依据

### 2.1 当前代码依据

- `lake_console/orchestrator/AGENTS.md`：新 Dagster lake 只允许 `data_lake/raw|silver|gold` 三层路径；新增数据集前必须形成设计记录。
- `lake_console/orchestrator/src/orchestrator/defs/partitions.py`：股票日频资产当前使用 `cn_a_stock_trade_days` 动态分区；`adj_factor` 需要新增独立的 `cn_a_stock_current_trade_days`，用于早盘可用的数据集。
- `lake_console/orchestrator/src/orchestrator/defs/paths.py`：股票行情 raw/silver 路径已收敛为 `raw/tushare/.../trade_date=...` 与 `silver/quote/.../trade_date=...`。
- `lake_console/orchestrator/src/orchestrator/defs/assets/suspend_d.py`：停复牌资产是本设计的分区和日更形态参考。
- `lake_console/orchestrator/src/orchestrator/defs/bootstrap/**`：已有旧湖 bootstrap 能力，支持按 `trade_date` 从旧路径复制到新湖 raw。
- `lake_console/orchestrator/src/orchestrator/defs/tushare_api_io.py`：已有 Tushare 分页拉取并写 raw parquet 的通用 helper。
- `lake_console/orchestrator/src/orchestrator/defs/run_contracts/**`：asset tags、definition metadata、column schema、materialization metadata 已有治理入口，新资产必须使用这些入口。

### 2.2 Tushare 文档依据

本地文档：`docs/sources/tushare/股票数据/行情数据/0028_复权因子.md`

确认口径：

- 接口名：`adj_factor`
- 更新时间：盘前 9:15~9:20 完成当日复权因子入库
- 支持取法：
  - 单只股票全部历史复权因子：`ts_code`
  - 单日全部股票复权因子：`trade_date`
  - 日期区间：`start_date/end_date`
  - 分页：`limit/offset`
- 输出字段：
  - `ts_code`
  - `trade_date`
  - `adj_factor`

本地文档：`docs/sources/tushare/股票数据/行情数据/0146_A股复权行情.md`

确认口径：

- 前复权公式是 `当日价格 * 当日复权因子 / 最新复权因子`。
- Tushare 说明行情软件通常以最近交易日作为前复权基准。
- 该公式是下游分钟线 qfq 设计依据，不改变本文对 `adj_factor` 自身的资产定义。

### 2.3 Tushare MCP 轻量实测

已用 `tushareMcp.adj_factor` 做轻量核验：

- `trade_date=20260526` 且显式请求 `ts_code/trade_date/adj_factor`，返回单日多股票复权因子。
- `ts_code=000001.SZ, start_date=20260525, end_date=20260526`，返回指定股票指定区间两行。
- `ts_code=000001.SZ` 不传日期，返回该股票历史序列；样本中可观察到因子在若干日期发生阶跃变化。

说明：

- 分页按现有 `fetch_tushare_partition_to_raw(...)` 通用 helper 复用。Tushare 文档确认 `adj_factor` 支持 `limit/offset`，实现时不为 `adj_factor` 单独发明分页逻辑。
- 本次没有执行 Dagster job、sensor、backfill 或 materialization。

### 2.4 旧湖审计依据

此前只读审计旧湖 `/Volumes/datasource/goldenshare-tushare-lake/raw_tushare/adj_factor` 得到的关键结论：

- 旧湖 `adj_factor` 覆盖完整交易日分区，没有整日交易日分区缺失。
- 若按 `list_status='L'` 当前上市股票口径统计，上市日之后交易日复权因子缺失为 0。
- 若把退市股票生命周期也纳入，仍存在部分退市股票缺口；这些缺口不进入本次 silver 口径。

这些是历史审计记录，不冒充当前实时状态。开发前仍需做一次只读复核，确认旧湖路径、字段和分区范围没有变化。

## 3. 资产边界

| 项 | raw | silver |
| --- | --- | --- |
| Asset key | `raw_tushare_adj_factor` | `silver_adj_factor` |
| 中文名 | 复权因子 | 复权因子 |
| 所属层级 tag | `raw` | `silver` |
| 数据域 tag | `quote_data` | `quote_data` |
| 分区 | `cn_a_stock_current_trade_days` | `cn_a_stock_current_trade_days` |
| 分区键 | `YYYY-MM-DD` 交易日 | `YYYY-MM-DD` 交易日 |
| 来源 | bootstrap 时来自旧湖；日常来自 Tushare `adj_factor` | `raw_tushare_adj_factor` + `silver_stock_basic` |
| 写入策略 | replace partition | replace partition |
| 路径 | `data_lake/raw/tushare/adj_factor/trade_date={partition_key}/part-000.parquet` | `data_lake/silver/quote/adj_factor/trade_date={partition_key}/part-000.parquet` |

命名说明：

- 不使用 `raw_legacy_adj_factor`。原因是旧湖只是 bootstrap 来源；资产长期来源和字段契约仍是 Tushare `adj_factor`。
- 不使用 `silver_adj_factor_basis_snapshot`。同一天同一股票的因子值不应拆成两个业务资产；前复权使用哪个最新交易日作为基准，是下游 qfq run 的选择，不是 `adj_factor` 本身的第二套事实。
- `cn_a_stock_current_trade_days` 承载历史分区和日常分区：历史初始化从旧湖 `adj_factor` 最早日期开始，对齐旧湖 `adj_factor` 全量范围内的股票开市日；日常运行每天 6:00 后追加注册当天股票开市日。

## 4. 字段契约

### 4.1 Raw 字段契约

`raw_tushare_adj_factor` 保持 Tushare 源站镜像口径：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ts_code` | `VARCHAR` | 股票代码 |
| `trade_date` | `VARCHAR` | Tushare 原始交易日，`YYYYMMDD` 字符串 |
| `adj_factor` | `DOUBLE` | 复权因子 |

注意：

- 旧湖或旧 prod-raw-db 导出方案里可能把 `trade_date` 写成 Parquet `DATE`。迁入新 Dagster raw 时必须归一成 `YYYYMMDD` 字符串，保持当前新湖 raw 层“源站镜像”的统一口径。
- raw 不过滤退市股票，不按当前上市股票池裁剪。raw 只做字段、类型、分区和基础质量校验。

### 4.2 Silver 字段契约

`silver_adj_factor` 是标准层可计算事实：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ts_code` | `VARCHAR` | 股票代码 |
| `trade_date` | `DATE` | 交易日 |
| `adj_factor` | `DOUBLE` | 复权因子 |

silver 过滤规则：

1. 只保留 `silver_stock_basic` 中存在的当前上市股票。当前 `silver_stock_basic` 已按 `list_status='L'` 过滤。
2. 只保留 `trade_date >= list_date` 的记录。
3. `adj_factor` 必须为正数。
4. 同一 `ts_code + trade_date` 必须唯一。

silver 完整性规则：

- 对目标分区 `trade_date=D`，expected universe 是：

```text
silver_stock_basic 中 list_status='L' 且 list_date <= D 的股票
```

- `silver_adj_factor[D]` 必须覆盖 expected universe 中每只股票一行。
- 退市股票不进入 expected universe，不再为后续分钟线加工承担完整性要求。

## 5. 数据流

```text
旧湖 raw_tushare/adj_factor
  -> bootstrap raw_tushare_adj_factor[trade_date]

Tushare adj_factor(trade_date=YYYYMMDD)
  -> 日常更新 raw_tushare_adj_factor[trade_date]

raw_tushare_adj_factor[trade_date]
silver_stock_basic
  -> silver_adj_factor[trade_date]
```

## 6. Bootstrap 设计

历史数据迁移使用现有 bootstrap 能力，不新增一套迁移框架。

已新增 `adj_factor_bootstrap_spec(...)`：

| 项 | 口径 |
| --- | --- |
| `dataset_key` | `raw_tushare_adj_factor` |
| `layer` | `raw` |
| `partition_type` | `trade_date` |
| 旧湖路径 | `/Volumes/datasource/goldenshare-tushare-lake/raw_tushare/adj_factor/trade_date={partition_key}/part-000.parquet` |
| 新湖目标路径 | `raw_adj_factor_path(lake_root, "{partition_key}")` |
| `empty_policy` | `require_positive` |
| `business_key` | `("ts_code", "trade_date")` |

bootstrap select 口径：

```sql
SELECT
  CAST(ts_code AS VARCHAR) AS ts_code,
  CASE
    WHEN trade_date IS NULL OR trim(CAST(trade_date AS VARCHAR)) = '' THEN NULL
    WHEN regexp_matches(trim(CAST(trade_date AS VARCHAR)), '^\\d{8}$')
      THEN trim(CAST(trade_date AS VARCHAR))
    ELSE strftime(CAST(trade_date AS DATE), '%Y%m%d')
  END AS trade_date,
  CAST(adj_factor AS DOUBLE) AS adj_factor
FROM read_parquet({old_path}, hive_partitioning=false, union_by_name=true)
```

门禁：

- 必须使用 `hive_partitioning=false` 核验文件内部字段，避免把目录分区列误当成 parquet 内部字段。
- bootstrap 只写新湖 raw，不直接写 silver。
- 历史 bootstrap 范围必须对齐旧湖 `adj_factor` 最早日期到旧湖当前全量范围内的股票开市日；这些历史交易日需要先注册到 `cn_a_stock_current_trade_days`，不写非交易日分区。

## 7. 日常更新设计

日常更新按交易日分区执行，但不与 `suspend_d` 共用 `cn_a_stock_trade_days`。`adj_factor` 使用独立的 `cn_a_stock_current_trade_days`：

```text
api_name = "adj_factor"
api_params = {"trade_date": partition_key.replace("-", "")}
fields = ("ts_code", "trade_date", "adj_factor")
allow_empty = false
write_mode = replace partition
```

运行边界：

- 只处理已注册的 `cn_a_stock_current_trade_days` 分区。
- 不提供按 `ts_code` 局部覆盖作为主入口。按股票历史补洞或修复属于 repair/backfill 专项，不能污染日常更新入口。
- 如果 Tushare 当日返回 0 行，raw asset 应失败或 skip，不覆盖已有正式分区。
- 分区注册必须在每天早上 6:00 后执行；如果当天是股票开市日，则把当天日期注册到 `cn_a_stock_current_trade_days`。
- `stock_adj_factor_sensor` 触发必须晚于 Tushare 文档说明的 9:15~9:20 入库窗口，正式口径为最早 9:30 后处理当天分区。

## 8. Checks 设计

### 8.1 Raw blocking checks

| Check | blocking | 说明 |
| --- | --- | --- |
| raw file exists | 是 | 分区文件必须存在 |
| required columns | 是 | 字段必须等于 `ts_code/trade_date/adj_factor` |
| partition date matches | 是 | 文件内 `trade_date` 必须等于分区日期的 `YYYYMMDD` |
| unique key | 是 | `ts_code + trade_date` 唯一 |
| positive factor | 是 | `adj_factor > 0` |
| row count positive | 是 | 交易日分区不能为空 |

### 8.2 Silver blocking checks

| Check | blocking | 说明 |
| --- | --- | --- |
| silver file exists | 是 | 分区文件必须存在 |
| schema | 是 | 字段和类型符合 silver 契约 |
| partition date matches | 是 | `trade_date` 必须等于分区日期 |
| unique key | 是 | `ts_code + trade_date` 唯一 |
| positive factor | 是 | `adj_factor > 0` |
| listed stock only | 是 | `ts_code` 必须来自 `silver_stock_basic` 当前上市股票 |
| coverage complete | 是 | 覆盖 `silver_stock_basic` 中 `list_date <= partition_date` 的全部当前上市股票 |

## 9. Job / Sensor / Readiness 口径

日常入口已按下列口径接入 active definitions；正式运行、分区注册和历史 bootstrap 仍需后续单独审批。

更新入口：

- `stock_adj_factor_update_job`
  - selection：`raw_tushare_adj_factor`、`silver_adj_factor` 及两者 blocking checks。
  - 不扩大到 `stock_basic` 更新；`silver_stock_basic` 是只读前置依赖。
  - 不提供 run config，不写自定义 run tags。

分区注册 sensor：

- `stock_current_trade_day_sensor`
  - 只注册 `cn_a_stock_current_trade_days`，不触发数据更新任务。
  - 只处理当天日期：上海时间 06:00 后，如果当天是 `silver_trade_calendar` 中 SSE 开市日且尚未注册，则注册当天分区。
  - 不做历史补齐；历史分区注册和旧湖 bootstrap 留到后续迁移验收。

更新触发 sensor：

- `stock_adj_factor_sensor`
  - 只处理最新一个已注册且不晚于当前上海日期的 `cn_a_stock_current_trade_days` 分区。
  - 09:30 前不触发；09:30 后才允许提交 `stock_adj_factor_update_job[trade_date]`。
  - 先确认 `silver_stock_basic` 已 materialized 且 blocking checks 通过；按本轮确认口径，不要求 `stock_basic` materialization date >= 目标交易日。
  - 若目标 `adj_factor` 分区已 ready，则 skip；若已 materialized 但 blocking checks 未全绿，则保守 skip，避免失败循环。
  - 不写自定义 run tags。
  - cursor 使用 M7 标准结构。

命名已确认：

- job 使用 `stock_adj_factor_update_job`。
- sensor 使用 `stock_adj_factor_sensor`。

分区注册与触发口径已确认：

- 新增独立 dynamic partitions：`cn_a_stock_current_trade_days`。
- 新增专用分区注册 sensor：`stock_current_trade_day_sensor`。
- `stock_current_trade_day_sensor` 的职责只注册当天的 `cn_a_stock_current_trade_days`，不触发数据更新任务，不补历史分区。
- 历史初始化时，`cn_a_stock_current_trade_days` 从旧湖 `adj_factor` 最早日期开始，承载旧湖 `adj_factor` 全量范围内的股票开市日。
- 每天早上 6:00 后读取交易日历；如果当天是股票开市日，则把当天日期注册到 `cn_a_stock_current_trade_days`。
- `raw_tushare_adj_factor` 和 `silver_adj_factor` 使用 `cn_a_stock_current_trade_days`，不使用共享的 `cn_a_stock_trade_days`。
- `cn_a_stock_trade_days` 仍按现有股票日频资产族口径服务 `suspend_d`、`stock_daily` 等盘后数据集，不被 `adj_factor` 早盘注册逻辑污染。
- `stock_adj_factor_sensor` 不早于 9:30 触发，并选择 `max(partition_key) where partition_key <= 上海当前日期` 的 `cn_a_stock_current_trade_days` 分区。
- 如果今天是 `2026-05-29` 且是股票开市日：
  - `2026-05-29 06:00` 后，专用分区注册 sensor 注册 `2026-05-29` 到 `cn_a_stock_current_trade_days`。
  - `2026-05-29 09:30` 后，`stock_adj_factor_sensor` 可以处理 `2026-05-29`。
  - 同一时间，`cn_a_stock_trade_days` 不会因此提前出现 `2026-05-29`，所以不会带动 `suspend_d_sensor`、`stock_daily_sensor` 提前处理当天。

Readiness：

- 下游 qfq 或分钟线资产只应依赖 `silver_adj_factor[trade_date]` 的 materialization + blocking checks passed。
- 如果需要判断“今天哪些股票因子变化”，应从相邻两个 `silver_adj_factor` 分区计算，不写入 `adj_factor` asset 的定义中。

## 10. 不做事项

本轮不做：

- 不新增 `silver_adj_factor_basis_snapshot`。
- 不设计 qfq 分钟线资产。
- 不设计因子历史版本体系。
- 不保留退市股票 silver 完整性。
- 不新增数据库表。
- 不运行 Dagster job、sensor、backfill、materialization 或 automation evaluation。
- 不复制旧湖大文件。

## 11. 风险与待确认点

1. 旧湖 raw 的 `trade_date` 类型可能是 `DATE` 或字符串，bootstrap 必须在 select 中显式归一到 `YYYYMMDD` 字符串。
2. 旧湖历史分区范围应在开发前只读复核，不把此前审计结果当成当前事实。
3. `silver_stock_basic` 当前只保留 `list_status='L'`，这与“过滤掉退市股票”的口径一致；本资产不为退市股票设计 silver 完整性和下游加工口径。
4. 分页必须复用现有 Tushare 通用拉取 helper，不新增 `adj_factor` 专用分页实现。
5. `cn_a_stock_current_trade_days` 必须在早上 6:00 后注册当天股票开市日；`stock_adj_factor_sensor` 必须晚于 Tushare 当日因子入库窗口，正式不早于 9:30。

## 12. 后续开发切片建议

### A1：契约与路径

- 增加 `adj_factor` 中文名映射。
- 增加 `cn_a_stock_current_trade_days` 动态分区定义。
- 增加 raw/silver column schema。
- 增加 raw/silver path 函数。
- 增加 DuckDB SQL 常量和 select helper。
- 不接入 active Definitions。
- 状态：已完成。

### A2：Bootstrap raw

- 增加 `adj_factor_bootstrap_spec(...)`。
- 增加 bootstrap 纯函数/静态测试。
- 用临时 parquet 测试 `DATE` / `YYYYMMDD` 两种旧湖输入都能生成新湖 raw 契约。
- 状态：已完成；正式旧湖数据迁移未执行。

### A3：Assets 与 checks

- 增加 `raw_tushare_adj_factor`、`silver_adj_factor`。
- 增加 raw/silver blocking checks。
- 只做静态编译、单元测试和临时 DuckDB 文件测试。
- 状态：已完成；未新增 job/sensor，未执行正式 Dagster materialization。

### A4：Job 与 sensor

- 增加 `stock_current_trade_day_sensor`，只注册 `cn_a_stock_current_trade_days`。
- `stock_current_trade_day_sensor` 每天 6:00 后把当天股票开市日注册到 `cn_a_stock_current_trade_days`，不补历史分区。
- 增加 `stock_adj_factor_update_job`。
- 增加 `stock_adj_factor_sensor`。
- 接入 readiness helper。
- 不运行正式 Dagster，先做代码与静态门禁验证。
- 状态：已完成；未注册正式分区，未运行正式 Dagster job/sensor/materialization。

### A5：历史 bootstrap 与日常更新验收

- 先列命令、路径、读写范围和回滚方式，获得明确批准后再执行。
- 历史 bootstrap 范围从旧湖 `adj_factor` 最早日期开始，按旧湖 `adj_factor` 全量范围迁移；执行前仍需只读复核旧湖当前实际范围，并列出完整命令、读写路径和回滚方式。
- 先小范围验收，再执行旧湖 `adj_factor` 全量范围迁移。
- 日常 Tushare 更新先用单日分区验收，再启用 sensor。
