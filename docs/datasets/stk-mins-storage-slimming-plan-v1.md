# 股票历史分钟行情存储瘦身方案 v1

- 版本：v1
- 状态：待评审
- 更新时间：2026-04-27
- 数据集：`stk_mins`
- 物理表：`raw_tushare.stk_mins`
- 服务入口：`core_serving.equity_minute_bar`
- 方案范围：`stk_mins` 存储瘦身，以及由删字段直接引发的读写、观测与展示适配

---

## 1. 目标

`stk_mins` 是当前仓库中数据量最大的单数据集之一。按 5500 只股票、1 年、`1/5/15/30/60` 分钟全频率估算，旧表结构会造成明显磁盘压力。

本方案目标是：

1. 保留 `stk_mins` 的完整分钟行情能力。
2. 删除重复字段和无必要索引，降低每年存储占用。
3. 保持上层仍可按 `trade_date` 查询和展示。
4. 在新架构下同步处理删字段后必然受影响的观测、freshness 与展示口径。
5. 不回退到旧 `sync_daily/backfill/sync_history` 架构，不引入兼容旧路径。

本方案不是旧架构兼容方案，也不是借机重做任务模型、审计模型或前端交互。凡是与 `stk_mins` 删字段无直接关系的改动，仍然禁止混入本轮。

---

## 2. 当前代码影响面审计

本节基于当前代码逐项扫描，不以历史文档或旧实现经验作为依据。

### 2.1 必改点

| 位置 | 当前行为 | 本方案要求 |
|---|---|---|
| `alembic/versions/20260424_000072_add_stk_mins_table_and_view.py` | 创建旧 `stk_mins` 表，含 `trade_date/session_tag/api_name/fetched_at/raw_payload`，按 `trade_date` 分区，额外建两个 BTree 索引 | 新增迁移 drop/recreate 空表，改为按 `trade_time` 分区，只保留主键 |
| `src/foundation/models/raw/raw_stk_mins.py` | ORM 含旧字段与旧索引，`freq` 为字符串 | 改为瘦身字段，`freq` 为整数，删除旧索引 |
| `src/foundation/ingestion/row_transforms.py` | `_stk_mins_row_transform` 派生 `trade_date/session_tag`，保留字符串 `freq` | 不再派生 `trade_date/session_tag`，入库前把 `freq` 转为 `1/5/15/30/60` |
| `src/foundation/datasets/definitions/market_equity.py` | `stk_mins` 的写入字段仍包含 `trade_date/session_tag`，观测字段仍可能指向日级字段 | 更新写入字段、质量字段、日期观测字段；`DatasetDefinition` 继续作为唯一事实源 |
| `src/ops/dataset_observation_registry.py` 及读取 DatasetDefinition 的状态链路 | 可能按旧 `trade_date` 观测分钟线 | 适配 `trade_time` 观测；如 freshness 需要日级判断，只能使用 `max(trade_time)::date`，不得恢复 raw 表 `trade_date` |
| Ops 页面/API 的字段展示 | 可能把 `stk_mins` 当普通日频展示“最新日期” | 对 `stk_mins` 这类 timestamp 观测字段展示为“最新时间/时间范围”；只做字段语义适配，不重做页面交互 |
| `core_serving.equity_minute_bar` View | 直接读取 raw 表中的 `trade_date/session_tag/fetched_at` | 从 `trade_time` 派生 `trade_date`，不暴露已删除字段 |
| `docs/datasets/stk-mins-dataset-development.md` | 仍描述旧字段、旧索引、旧分区 | 后续实现时同步更新为瘦身表结构 |

### 2.2 不应改动的点

| 位置 | 原因 |
|---|---|
| `src/foundation/ingestion/request_builders.py` | Tushare 接口请求仍要求字符串 `freq=1min/5min/...`，请求口径不应跟存储口径混淆 |
| `src/foundation/ingestion/source_client.py` | 仍需要把请求参数中的字符串 `freq` 注入返回行，供 transform 转换为整数 |
| `src/foundation/ingestion/unit_planner.py` | 计划层面仍按用户输入的字符串频率生成请求 unit，进度展示也继续显示 `1min/5min/...` 更符合用户理解 |
| `TaskRun` 主链 | 本次不改任务模型、进度模型、执行模型，只消费新的数据集事实字段 |
| 审计模型 | 分钟线完整性审计仍不在本轮实现 |
| `src/biz/**` 对上查询接口 | 本轮不新增分钟线 Biz 查询能力；只通过 View 保留未来读入口 |

---

## 3. 新表结构

### 3.1 物理表

```sql
CREATE TABLE raw_tushare.stk_mins (
    ts_code varchar(16) NOT NULL,
    freq smallint NOT NULL,
    trade_time timestamp without time zone NOT NULL,
    open real,
    close real,
    high real,
    low real,
    vol integer,
    amount real,
    CONSTRAINT pk_raw_tushare_stk_mins PRIMARY KEY (ts_code, freq, trade_time)
) PARTITION BY RANGE (trade_time);
```

字段说明：

| 字段 | 类型 | 含义 |
|---|---|---|
| `ts_code` | `varchar(16)` | 股票代码 |
| `freq` | `smallint` | 分钟周期，取值 `1/5/15/30/60` |
| `trade_time` | `timestamp` | Tushare 返回的分钟 bar 时间 |
| `open` | `real` | 开盘价 |
| `close` | `real` | 收盘价 |
| `high` | `real` | 最高价 |
| `low` | `real` | 最低价 |
| `vol` | `integer` | 成交量，按接口文档返回整数处理 |
| `amount` | `real` | 成交额 |

### 3.2 删除字段

| 字段 | 删除原因 |
|---|---|
| `trade_date` | 可由 `trade_time::date` 派生，不在 raw 表冗余保存 |
| `session_tag` | 可由 `trade_time` 判断上午/下午，不是源接口字段 |
| `api_name` | 表名已经表达来源和接口，不需要逐行重复保存 |
| `fetched_at` | 本数据集行数巨大，逐行抓取时间成本高；任务观测交给 TaskRun |
| `raw_payload` | 本数据集不保存逐行 raw payload，避免磁盘放大 |

### 3.3 索引策略

仅保留主键：

```sql
PRIMARY KEY (ts_code, freq, trade_time)
```

不再创建：

```sql
idx_raw_tushare_stk_mins_trade_date_freq
idx_raw_tushare_stk_mins_ts_code_freq_trade_time
```

理由：

1. 主要查询是“某股票 + 某频率 + 时间范围”，主键可覆盖。
2. 额外 BTree 索引在 4 亿级行数下会显著放大磁盘。
3. 如果后续发现跨股票按日期扫描确实慢，再单独评审是否增加 `BRIN(trade_time)`，不在本轮预设。

---

## 4. 分区策略

### 4.1 分区字段

从：

```sql
PARTITION BY RANGE (trade_date)
```

改为：

```sql
PARTITION BY RANGE (trade_time)
```

### 4.2 分区范围

继续使用月分区：

```text
raw_tushare.stk_mins_YYYY_MM
```

示例：

```sql
CREATE TABLE raw_tushare.stk_mins_2026_04
PARTITION OF raw_tushare.stk_mins
FOR VALUES FROM ('2026-04-01 00:00:00') TO ('2026-05-01 00:00:00');
```

### 4.3 HDD / SSD 分层

继续沿用已建立的 tablespace 策略：

| 分区 | tablespace |
|---|---|
| `2025` 及以前月分区 | `gs_stk_mins_hdd` |
| `2026` 及以后月分区 | `pg_default` |
| default 分区 | `pg_default` |

注意：

1. 本次结构重建必须同步重建分区 tablespace 规则。
2. 因当前表内无有效数据，允许 drop/recreate；若执行前发现已有数据，必须停止，重新评估迁移方式。

---

## 5. 读写路径

### 5.1 写入路径

写入目标保持：

```text
raw_tushare.stk_mins
```

`DatasetDefinition.storage` 保持：

```text
raw_dao_name = raw_stk_mins
core_dao_name = raw_stk_mins
target_table = raw_tushare.stk_mins
write_path = raw_only_upsert
```

请求与存储口径分离：

| 阶段 | `freq` 口径 |
|---|---|
| 用户输入 | `1min/5min/15min/30min/60min` |
| Tushare 请求 | `1min/5min/15min/30min/60min` |
| TaskRun 进度展示 | `1min/5min/15min/30min/60min` |
| raw 表存储 | `1/5/15/30/60` |

### 5.2 服务层 View

上层不直接依赖 raw 表冗余字段，而通过服务层 view 获取便利字段：

```sql
CREATE OR REPLACE VIEW core_serving.equity_minute_bar AS
SELECT
    ts_code,
    freq,
    trade_time,
    trade_time::date AS trade_date,
    open,
    close,
    high,
    low,
    vol,
    amount,
    'tushare'::varchar(32) AS source
FROM raw_tushare.stk_mins;
```

说明：

1. `trade_date` 只在 view 中派生，便于上层展示和轻量查询。
2. raw 表不保存 `trade_date`。
3. view 不复制数据，不创建物化视图。

### 5.3 上层按日期查询的性能规则

对用户/API 可以继续暴露 `trade_date` 概念，但查询实现不得在大表 WHERE 条件中使用：

```sql
trade_time::date = :trade_date
```

必须转换为半开时间范围：

```sql
trade_time >= :trade_date::date
AND trade_time < (:trade_date::date + interval '1 day')
```

区间查询同理：

```sql
trade_time >= :start_date::date
AND trade_time < (:end_date::date + interval '1 day')
```

硬规则：

1. `trade_time::date` 可以出现在 SELECT 列表中。
2. `trade_time::date` 不允许作为大表过滤条件。
3. 后续 Biz 查询或 Ops 查询若支持分钟线，必须用 `trade_time` 半开区间过滤。

---

## 6. 观测与展示适配

### 6.1 状态观测字段

`stk_mins` 不再保存 `trade_date` 后，状态观测不能继续读取 raw 表日级字段。新的观测口径是：

```text
observed field = raw_tushare.stk_mins.trade_time
```

要求：

1. `DatasetDefinition` 中 `stk_mins` 的观测字段必须与新表结构一致。
2. freshness 如果需要按交易日判断，使用 `max(trade_time)::date`，不能把 `trade_date` 加回 raw 表。
3. 状态快照、数据状态页、任务详情如展示范围，应支持 timestamp 字段。
4. 这属于新架构下的事实字段适配，不是旧架构兼容。

### 6.2 页面展示口径

分钟线不是普通日频数据。展示时应遵循：

```text
普通日频：最新日期 / 日期范围
分钟线：最新时间 / 时间范围
```

本轮允许做的页面/API 适配只限于“正确展示 timestamp 观测字段”。不允许借机重做审查中心、任务中心或审计交互。

### 6.3 审计口径

分钟级完整性审计仍不纳入本轮。

原因：

1. 分钟线完整性不能只按交易日判断。
2. 需要同时考虑交易时段、频率、停牌、新股、退市等规则。
3. 审计能力应在后续审查中心需求中单独评审。

本轮只需要保证 `audit_applicable=false` 的事实不被破坏。

### 6.4 架构保护边界

允许修改：

```text
表结构
分区与 tablespace 规则
Raw ORM 字段与索引
row transform 写入字段
core_serving.equity_minute_bar View
DatasetDefinition 中与 stk_mins 表结构直接相关的字段
读取 DatasetDefinition 的状态观测和展示适配
```

禁止修改：

```text
TaskRun 模型
任务进度模型
审计模型
Biz API 契约
CLI 任务语义
其他数据集日期模型
旧架构兼容路径
```

---

## 7. 容量估算

按：

```text
5500 只股票
244 个交易日
1/5/15/30/60 全频率
```

年行数：

```text
5500 * 244 * (240 + 48 + 16 + 8 + 4) = 约 4.24 亿行
```

瘦身后估算：

| 频率 | 年行数 | 稳定占用估算 |
|---|---:|---:|
| `1min` | 约 3.22 亿 | 42-57 GB |
| `5min` | 约 6444 万 | 8-11 GB |
| `15min` | 约 2147 万 | 3-4 GB |
| `30min` | 约 1074 万 | 1.5-2 GB |
| `60min` | 约 537 万 | 0.8-1.2 GB |
| 合计 | 约 4.24 亿 | 55-75 GB |

规划建议：

```text
稳定占用：55-75 GB / 年
磁盘预留：80-100 GB / 年
```

注意：同步过程仍会产生 WAL、页膨胀和失败重试空间消耗，不能按稳定占用卡死容量。

---

## 8. 实施 Milestone

### M0：执行前确认

目标：

1. 确认远程 `raw_tushare.stk_mins` 无有效数据。
2. 确认 HDD tablespace `gs_stk_mins_hdd` 可用。
3. 确认当前无运行中的 `stk_mins` TaskRun。

若任一条件不满足，停止实施。

### M1：Schema 重建

目标：

1. 新增 Alembic 迁移。
2. drop/recreate `raw_tushare.stk_mins`。
3. 按 `trade_time` 重建月分区。
4. 保留冷热 tablespace 分层。
5. 重建 `core_serving.equity_minute_bar` view。

验证：

1. `\d+ raw_tushare.stk_mins`
2. 分区字段为 `trade_time`。
3. 主键为 `(ts_code, freq, trade_time)`。
4. 无额外 BTree 索引。

### M2：ORM 与 DatasetDefinition

目标：

1. 更新 `RawStkMins` ORM。
2. 更新 `stk_mins` DatasetDefinition：
   - storage
   - source fields
   - normalization fields
   - required fields
   - quality fields
   - observed field
   - audit applicability 保持 false
3. 确认 `DatasetDefinition` 仍是唯一事实源，不允许其他调用方自行拼装旧字段。

验证：

1. DatasetDefinition registry 测试。
2. ORM model 导入测试。

### M3：归一化写入

目标：

1. 更新 `_stk_mins_row_transform`。
2. `freq` 字符串转整数。
3. 不再写 `trade_date/session_tag/api_name/fetched_at/raw_payload`。
4. `vol` 转整数，价格与 amount 转 float。

验证：

1. 单行 transform 测试。
2. 非交易时段仍应拒绝。
3. 非法 freq 仍应拒绝。

### M4：观测与展示适配

目标：

1. `core_serving.equity_minute_bar` 可正常读取并派生 `trade_date`。
2. 状态观测读取 `trade_time`。
3. freshness 如需日级判断，使用 `max(trade_time)::date`。
4. 页面/API 展示分钟线时使用“最新时间/时间范围”。
5. 按日期查询必须转换为 `trade_time` 半开区间。

验证：

1. raw 表查询返回瘦身字段。
2. View 查询返回 `trade_date` 派生列。
3. 数据状态查询不再访问 raw 表 `trade_date`。
4. `EXPLAIN` 确认日期过滤条件使用 `trade_time` 范围，而不是 `trade_time::date`。

### M5：小窗口远程验证

目标：

1. 单股票、单交易日、单频率同步。
2. 查询 raw 表。
3. 查询 view。
4. 查询数据状态。
5. 打开 Ops 页面确认分钟线展示口径正确。

建议命令：

```bash
GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-minute-history \
  --ts-code 000001.SZ \
  --freq 60min \
  --trade-date 2026-04-24
```

验证 SQL：

```sql
SELECT ts_code, freq, trade_time, open, close, high, low, vol, amount
FROM raw_tushare.stk_mins
ORDER BY trade_time
LIMIT 5;

SELECT ts_code, freq, trade_time, trade_date
FROM core_serving.equity_minute_bar
ORDER BY trade_time
LIMIT 5;
```

---

## 9. 风险与防护

| 风险 | 防护 |
|---|---|
| 执行前表里已有数据 | M0 必须查行数，非空则停 |
| 查询层继续用 `trade_time::date` 过滤大表 | 写入方案和后续 Biz/Ops 查询方案明确半开时间范围规则 |
| freshness / snapshot / 页面仍依赖 raw 表 `trade_date` | 纳入本轮直接关联适配；只改消费字段，不改任务/审计架构 |
| `freq` 请求口径和存储口径混淆 | 请求层保留字符串，transform 层统一转整数 |
| tablespace 分层丢失 | Alembic 迁移必须同步指定历史分区 tablespace |
| 后续误加 raw_payload/fetched_at | DatasetDefinition 与开发文档明确禁止逐行 raw payload 和 per-row fetched_at |

---

## 10. 本轮不做

1. 不实现 90 分钟线派生表。
2. 不新增分钟级完整性审计。
3. 不重做 TaskRun 模型、任务进度模型、审计模型或 Biz API 契约。
4. 不扩展 `DatasetDefinition.observed_table`。
5. 不新增额外索引。
6. 不回退到旧 `sync_minute_history` 规格作为用户主语；CLI 名称若仍存在，仅作为命令入口，不作为架构事实源。
