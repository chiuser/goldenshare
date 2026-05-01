# 股票历史分钟行情 Parquet Lake 方案 v1

- 版本：v1
- 状态：待评审
- 更新时间：2026-04-29
- 数据集：`stk_mins`
- 数据源：Tushare
- 源文档：`docs/sources/tushare/股票数据/行情数据/0370_股票历史分钟行情.md`
- 目标介质：本地移动 SSD
- 目标格式：Parquet + DuckDB 读取

---

## 1. 目标与边界

本方案只讨论 `stk_mins` 在本地移动 SSD 上的 Parquet Lake 存储、读取和派生数据组织方式。

目标：

1. 不依赖远程 Postgres，不参与生产 Ops 后台。
2. 移动 SSD 上只保存 Tushare 行情数据资产和我方派生行情数据。
3. 数据可被 DuckDB 直接高速读取。
4. 支持 5000 只以上股票、10 年历史分钟线、`1/5/15/30/60` 分钟频度。
5. 支持后续从 `30min` 派生 `90min`，从 `60min` 派生 `120min`。
6. 支持“单日全市场计算”和“单股/多股长周期回测”两类主要使用方式。
7. 写入中断时尽量只影响当前临时文件或当前分区，不影响已完成数据。

不做：

1. 不把移动盘作为 Postgres 数据目录。
2. 不把 `stk_mins` Parquet Lake 接入生产 Ops TaskRun 主链。
3. 不在本方案中实现运营后台、用户体系、自动任务或数据状态表。
4. 不把 90/120 分钟线写入 `raw_tushare`，因为它们不是 Tushare 原始接口数据。
5. 不要求第一版覆盖所有 Tushare 数据集，本方案只服务 `stk_mins`。

---

## 2. 上游接口事实

来自 Tushare 文档 `doc_id=370`：

| 项 | 内容 |
|---|---|
| API | `stk_mins` |
| 描述 | 获取 A 股分钟数据 |
| 支持频度 | `1min/5min/15min/30min/60min` |
| 单次上限 | `8000` 行 |
| 分页参数 | `limit` / `offset` |
| 必选参数 | `ts_code`、`freq` |
| 时间参数 | `start_date`、`end_date`，格式为 datetime |
| 历史能力 | 可提供超过 10 年历史分钟数据 |

输入参数：

| 字段 | 类型 | 必选 | 本方案口径 |
|---|---|---:|---|
| `ts_code` | `str` | 是 | 单个股票代码；全市场同步时由股票池扇出 |
| `freq` | `str` | 是 | 单个频度；多频度同步时按频度扇出 |
| `start_date` | `datetime` | 否 | 程序生成，不给用户手工输入具体时间 |
| `end_date` | `datetime` | 否 | 程序生成，不给用户手工输入具体时间 |
| `limit` | `int` | 否 | 固定 `8000` |
| `offset` | `int` | 否 | 从 `0` 开始递增，直到返回行数 `< 8000` |

输出字段：

| 字段 | 类型 | 本方案类型 |
|---|---|---|
| `ts_code` | `str` | string |
| `trade_time` | `str` | timestamp |
| `open` | `float` | float32 或 float64，第一版建议 float64，稳定后可评估 float32 |
| `close` | `float` | float32 或 float64，第一版建议 float64，稳定后可评估 float32 |
| `high` | `float` | float32 或 float64，第一版建议 float64，稳定后可评估 float32 |
| `low` | `float` | float32 或 float64，第一版建议 float64，稳定后可评估 float32 |
| `vol` | `int` | int64，避免大成交量溢出 |
| `amount` | `float` | float64 |

说明：

1. `vol` 不能使用 int32。现有 Postgres 路径已遇到过 `integer out of range`，Parquet Lake 也必须直接使用 int64。
2. 价格是否压缩为 float32 可以后置评估。第一版优先保证数值稳定、实现简单和 DuckDB 读取可靠。

---

## 3. 主要使用场景

### 3.1 单日全市场计算

示例：

> 统计昨天第一个 30 分钟线（9:30~10:00）内涨幅排名前 100 的股票。

访问特点：

1. 日期范围很窄，通常是一个交易日。
2. 股票范围很广，通常是全市场。
3. 频度明确，例如 `30min`。

最适合读取按日期组织的数据：

```text
raw_tushare/stk_mins_by_date/freq=30/trade_date=2026-04-24/
```

### 3.2 单股长周期回测

示例：

> 一只股票在过去 2 年内的 15 分钟线技术回测。

访问特点：

1. 股票范围很窄，通常是一只或少数几只股票。
2. 时间范围很长，可能是几个月到几年。
3. 如果只读按日期分区，会扫描很多日分区。

更适合读取按月和股票桶重排的数据：

```text
research/stk_mins_by_symbol_month/freq=15/trade_month=2026-04/bucket=07/
```

### 3.3 派生周期生成

示例：

> 依据 30 分钟线生成 90 分钟线，依据 60 分钟线生成 120 分钟线。

访问特点：

1. 输入是已有 `30min` 或 `60min` 数据。
2. 输出不是 Tushare 原始数据，而是我方派生数据。
3. 生成结果后仍应像其他分钟线一样被 DuckDB 高速读取。

输出应写入 `derived/` 和 `research/`，不写入 `raw_tushare/`。

### 3.4 多股相似性分析

示例：

> 对比几只股票在过去两个月内的 15 分钟线近似性。

访问特点：

1. 股票范围较小。
2. 时间范围中等。
3. 适合读取 `research/stk_mins_by_symbol_month`，过滤少数股票。

---

## 4. 总体存储设计

本方案采用两层 Parquet 布局：

```text
1. by_date 层：同步友好，适合单日全市场计算和补数。
2. by_symbol_month 层：研究友好，适合单股长周期回测和多股相似性分析。
```

目录建议：

```text
<LAKE_ROOT>/
  README.md
  manifest/
    lake.json
    datasets.json
    sync_runs.jsonl
    derived_runs.jsonl
    schema_versions.json

  raw_tushare/
    stk_mins_by_date/
      freq=1/
      freq=5/
      freq=15/
      freq=30/
      freq=60/

  derived/
    stk_mins_by_date/
      freq=90/
      freq=120/

  research/
    stk_mins_by_symbol_month/
      freq=1/
      freq=5/
      freq=15/
      freq=30/
      freq=60/
      freq=90/
      freq=120/

  _tmp/
```

说明：

1. `raw_tushare/` 只保存 Tushare 原始接口口径数据。
2. `derived/` 保存我方计算出来的分钟线，例如 `90/120`。
3. `research/` 保存为研究查询优化过的重排数据，既可以来自 `raw_tushare`，也可以来自 `derived`。
4. `_tmp/` 只用于写入临时目录。写入成功后通过 rename/replace 切换为正式分区。
5. 成功任务应清理本次 `_tmp/{run_id}` 的空目录；失败或中断任务保留 `_tmp/{run_id}` 供排查。
6. 历史 `_tmp/{run_id}` 只能通过 `lake-console clean-tmp --dry-run` 审计后，再用 `--older-than-hours` 显式清理。

---

## 5. by_date 层设计

### 5.1 作用

`by_date` 是采集层和补数层。

它服务：

1. 从 Tushare 同步数据。
2. 重跑某个交易日。
3. 单日全市场扫描。
4. 派生 `90/120` 分钟线的日级输入。

### 5.2 Tushare 原始分钟线目录

```text
raw_tushare/stk_mins_by_date/
  freq=1/
    trade_date=2026-04-24/
      part-000.parquet
      part-001.parquet
  freq=5/
    trade_date=2026-04-24/
      part-000.parquet
  freq=15/
  freq=30/
  freq=60/
```

分区字段：

| 分区字段 | 含义 |
|---|---|
| `freq` | 分钟周期，取值 `1/5/15/30/60` |
| `trade_date` | `trade_time` 所属交易日，格式 `YYYY-MM-DD` |

文件内容字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `ts_code` | string | 股票代码 |
| `freq` | int16 | 分钟周期，保留在文件字段中，方便 DuckDB 读取单文件时仍有完整语义 |
| `trade_time` | timestamp | 分钟 bar 时间 |
| `open` | double | 开盘价 |
| `high` | double | 最高价 |
| `low` | double | 最低价 |
| `close` | double | 收盘价 |
| `vol` | int64 | 成交量 |
| `amount` | double | 成交金额 |

排序建议：

```text
ts_code ASC, trade_time ASC
```

文件大小建议：

```text
128MB ~ 512MB / part
```

第一版如果实现复杂，可以先按同步批次生成 part 文件，但必须避免大量 KB 级小文件。

### 5.3 派生分钟线 by_date 目录

```text
derived/stk_mins_by_date/
  freq=90/
    trade_date=2026-04-24/
      part-000.parquet
  freq=120/
    trade_date=2026-04-24/
      part-000.parquet
```

字段与 `raw_tushare/stk_mins_by_date` 保持一致：

```text
ts_code, freq, trade_time, open, high, low, close, vol, amount
```

差异：

1. `freq` 取值为 `90/120`。
2. 数据来源是我方聚合计算，不是 Tushare 原始接口。
3. `derived_runs.jsonl` 记录生成来源、输入频度、输入分区、生成时间。

---

## 6. by_symbol_month 层设计

### 6.1 作用

`by_symbol_month` 是研究查询层。

它服务：

1. 单股长周期回测。
2. 少数股票多月对比。
3. 多股相似性分析。
4. 避免每次长周期查询都扫描几百个日分区。

### 6.2 为什么不用每只股票一个目录

不建议：

```text
ts_code=000001.SZ/trade_month=2026-04/
```

原因：

1. 5000 多只股票 x 120 个月 x 多个频度，会产生大量小目录。
2. 移动 SSD 上文件系统管理成本升高。
3. 后续派生频度增加后，小文件问题会继续放大。

### 6.3 推荐桶分区

目录：

```text
research/stk_mins_by_symbol_month/
  freq=15/
    trade_month=2026-04/
      bucket=00/
        part-000.parquet
      bucket=01/
        part-000.parquet
      ...
      bucket=31/
        part-000.parquet
```

分区字段：

| 分区字段 | 含义 |
|---|---|
| `freq` | 分钟周期，取值 `1/5/15/30/60/90/120` |
| `trade_month` | `trade_time` 所属月份，格式 `YYYY-MM` |
| `bucket` | 股票代码哈希桶，建议第一版使用 `0~31` 共 32 桶 |

桶规则：

```text
bucket = stable_hash(ts_code) % 32
```

要求：

1. 必须使用稳定哈希，不能使用 Python 默认 `hash()`，因为它跨进程不稳定。
2. 建议使用 `crc32(ts_code) % 32` 或 `md5(ts_code) % 32`。
3. 桶数量第一版固定为 32，后续如果改为 64，需要新建 layout version，不原地混用。

文件字段：

与 by_date 层一致：

```text
ts_code, freq, trade_time, open, high, low, close, vol, amount
```

排序建议：

```text
ts_code ASC, trade_time ASC
```

---

## 7. 写入策略

### 7.0 本地股票池前置

`stk_mins` 上游接口要求 `ts_code` 必填。全市场同步时，`lake_console` 不能读取远程 `goldenshare-db`，因此必须先在移动 SSD Lake 中维护一份本地 Tushare 股票池。

前置命令：

```bash
lake-console sync-stock-basic \
  --lake-root /Volumes/TushareData/goldenshare-tushare-lake
```

输出文件：

```text
manifest/security_universe/tushare_stock_basic.parquet
```

写入策略：

1. `stock_basic` 数据量较小，每次全量拉取。
2. 写入 `_tmp` 临时文件。
3. 校验 `ts_code` 非空、Parquet 可读、schema 正确。
4. 成功后全量替换正式文件。
5. 记录 `manifest/sync_runs.jsonl`。

建议字段：

| 字段 | 含义 |
|---|---|
| `ts_code` | 股票代码，`stk_mins` 全市场同步必需 |
| `symbol` | 股票代码数字部分 |
| `name` | 股票名称 |
| `area` | 地域 |
| `industry` | 行业 |
| `market` | 市场 |
| `list_status` | 上市状态 |
| `list_date` | 上市日期 |
| `delist_date` | 退市日期 |
| `is_hs` | 是否沪深港通 |

全市场 `stk_mins` 读取规则：

1. 读取 `manifest/security_universe/tushare_stock_basic.parquet` 的 `ts_code` 列。
2. 默认包含 `L/P/D` 状态，避免历史回补漏掉退市或暂停上市证券。
3. 若该文件不存在，`sync-stk-mins` 必须停止，并提示先运行 `sync-stock-basic`。
4. 第一版不读取远程数据库，不从生产 `stock_basic` 表补股票池。

### 7.1 从 Tushare 同步到 by_date

同步维度：

```text
ts_code x freq x request window
```

全市场同步时：

1. 从本地股票池 `manifest/security_universe/tushare_stock_basic.parquet` 获取全部 `ts_code`。
2. 按自然月或 `stk_mins_request_window_days` 把用户输入区间切成请求窗口，默认约一个自然月。
3. 对每个请求窗口、每个 `freq`、每个 `ts_code` 请求 Tushare。
4. `limit=8000`，`offset` 递增分页。
5. 将返回行按 `trade_time` 拆回对应 `trade_date` 分区。
6. 写入 `_tmp` 下的临时分区。
7. 请求窗口内所有 `ts_code + freq` 完成后，校验并替换该窗口覆盖的正式分区。

请求窗口示例：

```text
用户选择：2026-04-01 ~ 2026-04-30

请求：
stk_mins(ts_code=600000.SH, freq=30min, start_date=2026-04-01 09:00:00, end_date=2026-04-30 19:00:00, limit=8000, offset=0...)

落盘：
raw_tushare/stk_mins_by_date/freq=30/trade_date=2026-04-01/
raw_tushare/stk_mins_by_date/freq=30/trade_date=2026-04-02/
...
```

说明：

1. 下载维度是“单股票 + 单频率 + 宽日期窗口”，用于减少请求次数。
2. 存储维度仍然是 `freq + trade_date`，用于保留按交易日补数、校验和查询的便利性。
3. `limit=8000`，`offset` 递增分页。

请求窗口：

```text
start_date = 窗口开始日 09:00:00
end_date   = 窗口结束日 19:00:00
```

说明：

1. 用户只选择交易日期范围，不选择具体时间。
2. 程序内部用大窗口覆盖交易时段。
3. 写入前可过滤明显不在交易日当天的异常行。
4. 每完成一个 `ts_code + freq + request window`，追加 checkpoint 到 `manifest/sync_checkpoints/stk_mins_range/run_id=*/checkpoint.jsonl`。

### 7.2 分区覆盖

第一版建议使用分区覆盖，而不是追加：

```text
replace_partition(freq, trade_date)
```

原因：

1. 单个交易日重跑时语义清晰。
2. 不需要在 Parquet 文件内部做复杂去重。
3. 写坏时可以保留旧分区，只有新分区校验成功才替换。

替换流程：

```text
1. 写 _tmp/run_id/raw_tushare/stk_mins_by_date/freq=30/trade_date=2026-04-24/
2. 校验文件可读、行数 > 0、schema 匹配。
3. 将旧正式分区移动到 _tmp/backup/run_id/。
4. 将新分区 rename 到正式路径。
5. 更新 manifest。
6. 清理 backup。
```

如果第 4 步前失败，正式分区不变。

### 7.3 by_symbol_month 重排

`by_symbol_month` 不直接从 Tushare 写入，而是从 by_date 层生成：

```text
raw_tushare/stk_mins_by_date -> research/stk_mins_by_symbol_month
derived/stk_mins_by_date     -> research/stk_mins_by_symbol_month
```

生成触发：

1. 某个 `freq + trade_date` 同步完成后，标记其所属 `trade_month` 需要重排。
2. 重排任务按 `freq + trade_month` 读取当月所有日分区。
3. 按 `bucket` 写入 32 个桶分区。
4. 写入成功后替换该 `freq + trade_month` 的 research 分区。

第一版可以先提供手动命令：

```bash
lake-console rebuild-stk-mins-research --freq 15 --trade-month 2026-04
```

后续再做自动触发。

---

## 8. 90/120 分钟线派生策略

### 8.1 数据定位

90/120 分钟线是我方派生数据：

```text
90min  = 30min 聚合
120min = 60min 聚合
```

存储位置：

```text
derived/stk_mins_by_date/freq=90/
derived/stk_mins_by_date/freq=120/
research/stk_mins_by_symbol_month/freq=90/
research/stk_mins_by_symbol_month/freq=120/
```

不允许写入：

```text
raw_tushare/stk_mins_by_date/
```

### 8.2 输出字段

字段与原始分钟线一致：

| 字段 | 聚合规则 |
|---|---|
| `ts_code` | 原值 |
| `freq` | `90` 或 `120` |
| `trade_time` | 聚合窗口结束时间，必须固定口径 |
| `open` | 窗口第一根 bar 的 open |
| `high` | 窗口内 max(high) |
| `low` | 窗口内 min(low) |
| `close` | 窗口最后一根 bar 的 close |
| `vol` | 窗口内 sum(vol) |
| `amount` | 窗口内 sum(amount) |

### 8.3 窗口口径

第一版必须先固定交易时段窗口。

| 派生频度 | 输入 | 窗口 |
|---|---|---|
| `90` | `30` | 跳过 `09:30` 集合竞价 bar，从 `10:00` 开始按日内有效 30 分钟 bar 顺序聚合 |
| `120` | `60` | 每 2 根连续 60 分钟 bar 聚合 |

必须明确：

1. `90min` 的 `09:30` bar 不参与聚合，因为它代表集合竞价开盘/收盘情况。
2. `90min` 第一根由 `10:00、10:30、11:00` 三根 30 分钟 bar 聚合。
3. `90min` 第二根由 `11:30、13:30、14:00` 三根 30 分钟 bar 聚合，允许跨午休，因为这是按有效交易 bar 顺序聚合，不按自然时间连续性聚合。
4. `90min` 第三根由 `14:30、15:00` 两根 30 分钟 bar 聚合；虽然实际只有 60 分钟，仍作为 `freq=90` 的尾部 K 线使用。
5. `120min` 第一版按 60 分钟 bar 每 2 根聚合；不足 2 根的尾部 bar 暂不生成，后续如需尾部保留需单独评审。
6. 缺失输入 bar 时，该派生 bar 应拒绝生成，还是生成并标记缺失，需要单独评审。第一版对 `90min` 只保留日内自然尾部不足 3 根的情况，不额外补缺失窗口。

### 8.4 访问体验

派生结果与原始分钟线一样是 Parquet：

```sql
select *
from read_parquet('/Volumes/SSD/goldenshare-tushare-lake/derived/stk_mins_by_date/freq=90/**/*.parquet')
where trade_time >= timestamp '2026-04-01'
  and trade_time < timestamp '2026-05-01';
```

单股回测优先读 research 层：

```sql
select *
from read_parquet('/Volumes/SSD/goldenshare-tushare-lake/research/stk_mins_by_symbol_month/freq=90/**/*.parquet')
where ts_code = '000001.SZ'
  and trade_time >= timestamp '2024-01-01'
order by trade_time;
```

---

## 9. 读取方式示例

### 9.1 昨天第一个 30 分钟涨幅排名前 100

```sql
with bars as (
  select
    ts_code,
    trade_time,
    open,
    close,
    (close - open) / nullif(open, 0) as pct_chg
  from read_parquet('/Volumes/SSD/goldenshare-tushare-lake/raw_tushare/stk_mins_by_date/freq=30/trade_date=2026-04-24/*.parquet')
  where trade_time = timestamp '2026-04-24 10:00:00'
)
select *
from bars
order by pct_chg desc
limit 100;
```

### 9.2 单股两年 15 分钟回测

```sql
select *
from read_parquet('/Volumes/SSD/goldenshare-tushare-lake/research/stk_mins_by_symbol_month/freq=15/**/*.parquet')
where ts_code = '000001.SZ'
  and trade_time >= timestamp '2024-01-01'
  and trade_time < timestamp '2026-01-01'
order by trade_time;
```

### 9.3 最近两个月几只股票相似性分析

```sql
select *
from read_parquet('/Volumes/SSD/goldenshare-tushare-lake/research/stk_mins_by_symbol_month/freq=15/trade_month=2026-03/**/*.parquet')
where ts_code in ('000001.SZ', '600000.SH', '300750.SZ')
union all
select *
from read_parquet('/Volumes/SSD/goldenshare-tushare-lake/research/stk_mins_by_symbol_month/freq=15/trade_month=2026-04/**/*.parquet')
where ts_code in ('000001.SZ', '600000.SH', '300750.SZ');
```

后续 Lake Console 可以帮用户自动计算股票对应 bucket，减少不必要文件扫描。

---

## 10. Manifest 设计

### 10.1 `manifest/lake.json`

记录 lake 根信息：

```json
{
  "lake_name": "goldenshare-tushare-lake",
  "layout_version": 1,
  "created_at": "2026-04-29T00:00:00+08:00",
  "owner": "local"
}
```

### 10.2 `manifest/datasets.json`

记录数据集级定义：

```json
{
  "stk_mins": {
    "source": "tushare",
    "api_name": "stk_mins",
    "raw_layout": "raw_tushare/stk_mins_by_date",
    "research_layout": "research/stk_mins_by_symbol_month",
    "supported_freq": [1, 5, 15, 30, 60],
    "derived_freq": [90, 120],
    "bucket_count": 32,
    "schema_version": 1
  }
}
```

### 10.3 `manifest/sync_runs.jsonl`

每次 Tushare 同步写一行：

```json
{"run_id":"20260429T100000Z-daily","dataset":"stk_mins","freq":30,"trade_date":"2026-04-24","rows":1200000,"status":"success","started_at":"...","ended_at":"..."}
```

### 10.4 `manifest/derived_runs.jsonl`

每次派生写一行：

```json
{"run_id":"20260429T110000Z-derive90","dataset":"stk_mins","freq":90,"trade_date":"2026-04-24","source_freq":30,"rows":400000,"missing_input_bars":0,"status":"success"}
```

说明：

1. Manifest 是辅助事实，不是唯一事实。
2. 页面展示应优先扫描磁盘文件事实；manifest 用于补充运行记录和加速展示。
3. 如果 manifest 与文件事实冲突，以文件事实为准，并提示 manifest 需要重建。

---

## 11. Lake Console 能力边界

建议独立目录：

```text
lake_console/
  AGENTS.md
  README.md
  backend/
  frontend/
```

本方案下，Lake Console 第一阶段至少支持：

1. 配置并检查 `GOLDENSHARE_LAKE_ROOT`。
2. 展示移动 SSD 总空间、剩余空间。
3. 同步一个 `stk_mins` 小窗口到 by_date。
4. 扫描 by_date / research / derived 文件事实。
5. 展示 dataset、freq、trade_date、trade_month、bucket、文件数、总大小。
6. 使用 DuckDB 做 sample 查询。
7. 显示 `_tmp` 残留、空文件、schema 不一致等风险。

第一阶段不做：

1. 不接生产 Ops API。
2. 不读写远程数据库。
3. 不接生产 TaskRun。
4. 不做自动调度。
5. 不做所有数据集泛化。

---

## 12. 第一阶段实施里程碑

### M1：目录与工程隔离

目标：

1. 新增 `lake_console/` 独立工程目录。
2. 写 `lake_console/AGENTS.md`，明确不依赖生产 Ops、不进入生产部署。
3. 后端和前端都放在 `lake_console` 下。

验收：

1. 生产 `src/app` 和 `frontend` 不 import `lake_console`。
2. 部署脚本不启动 lake console。

### M2：Lake Root 与只读扫描

目标：

1. 后端读取 `GOLDENSHARE_LAKE_ROOT`。
2. 检查路径存在、可读写、磁盘剩余空间。
3. 扫描 `raw_tushare/stk_mins_by_date` 文件事实。

验收：

1. 空移动 SSD 也能显示“Lake 未初始化”。
2. 初始化后能显示 manifest 与目录结构。

### M3：`stk_mins` 最小写入闭环

目标：

1. 先支持从 Tushare 拉取 `stock_basic`，同时生成正式 `raw_tushare` 维表和本地股票池文件。
2. 再支持一个股票、一个频度、一个交易日同步。
3. 写入 by_date Parquet。
4. 使用 `_tmp -> 校验 -> 替换正式分区`。
5. 写 `sync_runs.jsonl`。

正式数据集路径：

```text
raw_tushare/stock_basic/current/part-000.parquet
```

本地股票池路径：

```text
manifest/security_universe/tushare_stock_basic.parquet
```

验收命令示例：

```bash
lake-console sync-stock-basic \
  --lake-root /Volumes/SSD/goldenshare-tushare-lake
```

验收命令示例：

```bash
lake-console sync-stk-mins \
  --ts-code 600000.SH \
  --freq 30 \
  --trade-date 2026-04-24 \
  --lake-root /Volumes/SSD/goldenshare-tushare-lake
```

验收：

1. `raw_tushare/stock_basic/current/part-000.parquet` 生成。
2. `manifest/security_universe/tushare_stock_basic.parquet` 生成。
3. `stk_mins` by_date Parquet 文件生成。
4. DuckDB 可读取。
5. 只读扫描能看到正式 `stock_basic` 数据集和 `stk_mins` 分区。

### M4：只读页面展示

目标：

1. 独立前端页面显示 Lake 总览。
2. 显示 `stk_mins` 数据集卡片。
3. 显示 `freq/trade_date` 分区树。
4. 显示文件数量、总大小、最早/最新分区、schema 摘要。
5. 显示风险项：空文件、tmp 残留、schema 不一致。

验收：

1. 页面只基于文件事实和 manifest，不依赖 Ops 状态表。
2. 页面可在本地独立访问。
3. 生产前端不出现 Lake Console 入口。

### M5：全市场写入与进度

目标：

1. 从本地股票池读取全市场 `ts_code`。
2. 支持多频度。
3. 控制 part 文件大小，避免小文件爆炸。
4. 显示当前股票、当前频度、当前分区、累计行数。
5. 中断后不破坏正式分区。

验收：

1. 单日单频全市场可同步。
2. 中断后只留下 `_tmp`，正式数据不被污染。
3. 重新执行可以覆盖该分区。

### M6：派生与 research 重排

目标：

1. 从 `30min` 生成 `90min`。
2. 从 `60min` 生成 `120min`。
3. 写入 `derived/stk_mins_by_date`。
4. 从 by_date 重排生成 `research/stk_mins_by_symbol_month`。
5. 支持 32 个 stable hash bucket。

验收：

1. `90/120` 与原始分钟线字段一致。
2. DuckDB 可直接读取派生数据。
3. 前端展示 `raw_tushare`、`derived`、`research` 三层语义和推荐用途。
4. 分区列表按 layer 分组展示，用户能区分原始落盘、派生周期和研究重排。
3. 单股长周期回测优先读 research 层。

---

## 13. 风险与待评审点

### 13.1 待评审点

| 问题 | 建议默认值 |
|---|---|
| 价格字段用 float32 还是 float64 | 第一版 float64，稳定后再压缩 |
| research bucket 数量 | 第一版 32 |
| by_date part 文件大小 | 128MB~512MB |
| 90/120 缺失输入 bar 怎么处理 | 第一版不生成缺失窗口，并记录缺失计数 |
| by_symbol_month 是否自动重排 | 第一版先手动，后续再自动 |

### 13.2 主要风险

1. 全市场分钟数据量极大，同步时间长，必须支持进度展示和中断安全。
2. 移动 SSD 写入期间不能拔盘；但 Parquet 分区写入风险只限制在当前临时分区。
3. 小文件过多会显著拖慢 DuckDB 查询和文件系统扫描。
4. 如果后续改变 bucket 数量，需要 layout version 迁移，不允许原地混写。
5. Tushare 权限、限速、异常返回需要在同步层明确重试和失败记录。

---

## 14. 与现有 Postgres `stk_mins` 方案的关系

现有文档：

1. `docs/datasets/stk-mins-dataset-development.md`
2. `docs/datasets/stk-mins-storage-slimming-plan-v1.md`
3. `docs/ops/stk-mins-tablespace-layout-v1.md`

它们服务的是 Postgres 路径：

```text
Tushare -> Goldenshare ingestion -> raw_tushare.stk_mins / core_serving view
```

本方案服务的是本地 Lake 路径：

```text
Tushare -> lake_console -> Parquet on mobile SSD -> DuckDB
```

二者不是同一条执行链路。后续如果确认 Parquet Lake 成为 `stk_mins` 的主方向，应单独评审是否下线 Postgres `stk_mins` 大表路径，而不是在本方案里直接混改。
