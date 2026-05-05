# 股票分钟线指标系统设计方案 v1

- 版本：v1
- 状态：待评审
- 更新时间：2026-05-05
- 适用范围：`lake_console` 本地 Parquet Lake
- 首个指标：`MACD(12,26,9)`
- 后续指标：`MA`、`BOLL`、其他基于分钟线的本地派生指标
- 相关文档：
  - [股票历史分钟行情 Parquet Lake 方案 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-parquet-lake-plan-v1.md)
  - [Local Lake Console 架构方案 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-architecture-plan-v1.md)
  - [Local Lake Console 数据集模型 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-dataset-model-v1.md)

---

## 1. 设计目标

本方案要把 `stk_mins` 从“只有分钟 K 线文件”推进到“可长期计算、增量更新、可回放、可审查的分钟指标资产”。

落地后要得到这些能力：

1. 用本地 Parquet 文件直接计算 `1/5/15/30/60/90/120` 分钟 MACD。
2. 支持单股长周期回测，例如读取一只股票过去两年的 15 分钟 MACD。
3. 支持单日全市场筛选，例如找出某天 30 分钟 MACD 金叉的股票。
4. 支持全量重算，也支持基于 `ema_state` 的增量更新。
5. 支持源分钟线被重写后，识别指标结果已经过期，进入重算队列。
6. 指标结果仍然以 Parquet Lake 的方式管理，DuckDB 可以直接读取。
7. 所有长任务必须有进度输出，不能出现“执行了但不知道跑到哪里”的体验。

本方案不做：

1. 不接生产 Ops TaskRun。
2. 不访问远程 `goldenshare-db`。
3. 不引入生产前端或生产后端依赖。
4. 不重新做复权。当前 `stk_mins` Parquet 已按前复权口径保存，指标计算直接使用 `close`。
5. 不把指标写回 `raw_tushare`。指标是本地派生结果，只能进入 `derived` 和 `research`。

---

## 2. 当前代码事实

当前 `lake_console` 已具备：

| 能力 | 当前实现 |
|---|---|
| 原始分钟线落盘 | `raw_tushare/stk_mins_by_date/freq=*/trade_date=*/*.parquet` |
| 90/120 分钟线派生 | `derived/stk_mins_by_date/freq=90|120/trade_date=*/*.parquet` |
| 研究层重排 | `research/stk_mins_by_symbol_month/freq=*/trade_month=*/bucket=*/*.parquet` |
| 临时写入 | `_tmp/{run_id} -> 校验 -> replace` |
| 执行记录 | `manifest/sync_runs.jsonl` |
| 关键服务 | `StkMinsDerivedService`、`StkMinsResearchService` |
| CLI | `sync-stk-mins`、`sync-stk-mins-range`、`derive-stk-mins`、`rebuild-stk-mins-research` |

这意味着指标系统应该复用现有 Lake 物理分层，而不是另起一套 `data/minute_kline` 目录。

---

## 3. 输入文件契约

### 3.1 原始频度输入

`1/5/15/30/60` 分钟指标读取：

```text
raw_tushare/stk_mins_by_date/
  freq=30/
    trade_date=2026-04-24/
      part-000.parquet
```

必须字段：

| 字段 | 用途 |
|---|---|
| `ts_code` | 分组计算单位 |
| `freq` | 周期 |
| `trade_time` | 指标时间轴，跨日递推不能重置 |
| `close` | MACD 输入价格，当前视为前复权价格 |

可保留但 MACD 不直接使用：

```text
open, high, low, vol, amount, exchange, vwap
```

### 3.2 派生频度输入

`90/120` 分钟指标读取：

```text
derived/stk_mins_by_date/
  freq=90/
    trade_date=2026-04-24/
      part-000.parquet
```

说明：

1. `90` 来自 `30` 分钟线。
2. `120` 来自 `60` 分钟线。
3. 指标系统不关心它们来自源站还是本地派生，只要求 `trade_time` 顺序稳定、`close` 可用。

### 3.3 前复权口径

当前分钟线 Parquet 的 `open/high/low/close` 默认就是前复权结果。

这样做带来的收益：

1. 指标计算时不需要读 `adj_factor`，少一次大规模 JOIN。
2. MACD、MA、BOLL 的输入价格连续性更好，更适合量化研究。
3. 增量计算更稳定，不会因为每日复权因子变动而让全部历史状态频繁失效。

约束：

1. 不能在指标系统里再次乘复权因子。
2. 如果未来发现某批分钟线不是前复权，必须先修复源分钟线分区，再重算指标。

---

## 4. 输出层设计

### 4.1 指标 by_date 层

按日期组织的指标层用于单日全市场扫描。

目录：

```text
derived/stk_mins_indicators_by_date/
  indicator=macd/
    params_key=12_26_9/
      freq=30/
        trade_date=2026-04-24/
          part-000.parquet
```

这样做能得到：

1. 查某个交易日全市场 MACD 时，只扫一个 `trade_date` 分区。
2. 指标重算某天时，只替换对应日期分区。
3. `indicator` 和 `params_key` 进入路径后，未来可以并存不同指标和不同参数版本。

### 4.2 指标 research 层

按股票月份重排的指标层用于长周期回测。

目录：

```text
research/stk_mins_indicators_by_symbol_month/
  indicator=macd/
    params_key=12_26_9/
      freq=30/
        trade_month=2026-04/
          bucket=07/
            part-000.parquet
```

这样做能得到：

1. 查一只股票两年 MACD 时，只读相关月份和该股票所在 bucket。
2. 不需要扫描几百个 `trade_date` 分区。
3. 指标层和分钟 K 线层保持同样的查询习惯，前端和研究脚本容易理解。

### 4.3 指标状态层

MACD 是递推指标，增量更新必须保存 EMA 状态。

目录：

```text
manifest/indicator_state/
  stk_mins_macd/
    params_key=12_26_9/
      state.parquet
```

这样做能得到：

1. 每天新增分钟线后，不用扫十年历史。
2. 单只股票、单个频度可以从上次状态继续递推。
3. 状态文件很小，`5500` 只股票 x `7` 个频度约 `38500` 行，全量覆盖成本可接受。

### 4.4 指标运行记录与重算队列

运行记录：

```text
manifest/indicator_runs.jsonl
```

重算队列：

```text
manifest/indicator_recalc_queue/
  stk_mins_macd.parquet
```

这样做能得到：

1. 每次全量、增量、重算都有可追踪记录。
2. 源数据被重写后，不会静默留下过期指标。
3. 后续页面可以展示“哪些指标分区需要重算”，而不是靠人猜。

---

## 5. MACD 结果 schema

### 5.1 by_date / research 输出字段

| 字段 | 类型 | 必填 | 含义 |
|---|---|---:|---|
| `ts_code` | string | 是 | 股票代码 |
| `freq` | int16 | 是 | 分钟周期，取值 `1/5/15/30/60/90/120` |
| `trade_time` | timestamp | 是 | 指标对应的分钟 bar 时间 |
| `dif` | float32 | 是 | 快慢 EMA 差值 |
| `dea` | float32 | 是 | DIF 的 EMA 平滑值 |
| `macd_bar` | float32 | 是 | `2 * (dif - dea)` |
| `params_key` | string | 是 | 参数版本，例如 `12_26_9` |
| `indicator_version` | int16 | 是 | 指标算法版本，第一版为 `1` |

说明：

1. 输出结果用 `float32`，是为了控制指标层长期存储体积。
2. 递推状态用 `double`，是为了降低长期增量计算的累计误差。
3. 不写 `open/high/low/close`，避免指标层复制 K 线事实；需要价格时应 JOIN 或同时读取分钟线层。
4. 不新增 `trade_date` 字段，分钟线主时间口径仍然是 `trade_time`，日期通过路径分区表达。

### 5.2 `ema_state` 字段

| 字段 | 类型 | 必填 | 含义 |
|---|---|---:|---|
| `indicator_key` | string | 是 | 固定 `macd` |
| `params_key` | string | 是 | 固定 `12_26_9`，后续可扩展 |
| `source_dataset_key` | string | 是 | 固定 `stk_mins` |
| `freq` | int16 | 是 | 分钟周期 |
| `ts_code` | string | 是 | 股票代码 |
| `last_trade_time` | timestamp | 是 | 已计算到的最后一根 bar |
| `ema_fast` | double | 是 | `EMA12` 状态 |
| `ema_slow` | double | 是 | `EMA26` 状态 |
| `dea` | double | 是 | `DEA` 状态 |
| `source_layer` | string | 是 | `raw_tushare` 或 `derived` |
| `source_watermark` | timestamp | 是 | 状态对应的源数据时间水位 |
| `state_version` | int16 | 是 | 状态 schema 版本 |
| `updated_at` | timestamp | 是 | 状态更新时间 |

### 5.3 重算队列字段

| 字段 | 类型 | 必填 | 含义 |
|---|---|---:|---|
| `queue_id` | string | 是 | 稳定唯一 ID |
| `indicator_key` | string | 是 | `macd` |
| `params_key` | string | 是 | `12_26_9` |
| `freq` | int16 或 null | 否 | null 表示所有频度 |
| `ts_code` | string 或 null | 否 | null 表示全市场 |
| `invalid_from_time` | timestamp | 是 | 从哪个时间点开始需要重算 |
| `reason` | string | 是 | `source_partition_replaced` / `indicator_params_changed` / `schema_migration` / `manual_request` |
| `status` | string | 是 | `pending` / `running` / `done` / `failed` |
| `created_at` | timestamp | 是 | 入队时间 |
| `finished_at` | timestamp 或 null | 否 | 完成时间 |
| `error_message` | string 或 null | 否 | 失败原因 |

---

## 6. MACD 公式口径

默认参数：

```text
fast=12
slow=26
signal=9
params_key=12_26_9
```

递推公式：

```text
EMA_fast(t) = EMA_fast(t-1) * (fast-1)/(fast+1) + close(t) * 2/(fast+1)
EMA_slow(t) = EMA_slow(t-1) * (slow-1)/(slow+1) + close(t) * 2/(slow+1)
DIF(t)      = EMA_fast(t) - EMA_slow(t)
DEA(t)      = DEA(t-1) * (signal-1)/(signal+1) + DIF(t) * 2/(signal+1)
MACD(t)     = 2 * (DIF(t) - DEA(t))
```

首根 K 线：

```text
EMA_fast(t0) = close(t0)
EMA_slow(t0) = close(t0)
DIF(t0)      = 0
DEA(t0)      = 0
MACD(t0)     = 0
```

跨日规则：

1. MACD 不在每日开盘重置。
2. 同一股票、同一频度按 `trade_time ASC` 连续递推。
3. 不同频度完全独立计算，不能从 `1min` MACD 推导 `5min` MACD。

---

## 7. 全量计算流程

全量计算用于首次建立指标库、参数变更、源数据大范围修复。

### 7.1 单股单频度全量

流程：

```text
读取 source research 或 by_date
-> 按 ts_code + trade_time 排序
-> pandas/numpy 计算 MACD
-> 按 trade_date 切分结果
-> 写入 _tmp 指标 by_date 分区
-> 校验行数和 schema
-> replace 正式分区
-> 更新 ema_state
-> 记录 indicator_runs
```

这样做能得到：

1. 小范围验证简单。
2. 单只股票历史修复时不用触碰全市场。
3. 增量状态和结果文件在同一轮中保持一致。

### 7.2 全市场全量

全市场全量不能直接按日期扫十年，否则每只股票的 EMA 状态不好连续维护。

推荐执行单位：

```text
freq x bucket
```

流程：

```text
读取 research/stk_mins_by_symbol_month/freq=*/trade_month=*/bucket=*
-> 在 bucket 内按 ts_code 分组
-> 每个 ts_code 按 trade_time 排序计算全量 MACD
-> 结果先写入 _tmp/{run_id}/indicator_stage/.../trade_date=*/bucket=*
-> 每个 trade_date 汇总所有 bucket
-> 写入正式 derived/stk_mins_indicators_by_date 分区
-> 重建 research/stk_mins_indicators_by_symbol_month
-> 最后更新 ema_state
```

这样做能得到：

1. 单只股票跨多年连续递推，不断链。
2. 最终仍然保留按日期分区，方便全市场横截面查询。
3. 计算阶段可以分 bucket 并行，但正式分区替换仍然受控。

### 7.3 状态更新时机

`ema_state` 必须最后更新。

顺序：

```text
1. 指标结果写入 _tmp
2. 指标结果校验
3. 指标 by_date 正式替换
4. 指标 research 重排或标记待重排
5. state.parquet 写入 _tmp
6. state.parquet 校验
7. state.parquet 正式替换
8. indicator_runs 记录完成
```

这样做能避免：

1. 结果没写完但 state 已前进。
2. 下次增量跳过未落盘数据。
3. 出现“页面显示完成、文件实际缺失”的错觉。

---

## 8. 增量计算流程

增量计算用于每天新增分钟线之后。

### 8.1 增量入口

输入：

```text
indicator_key=macd
params_key=12_26_9
freqs=1,5,15,30,60,90,120
start_date=YYYY-MM-DD
end_date=YYYY-MM-DD
scope=all_market 或 ts_code
```

读取：

1. `ema_state` 找到每只股票、每个频度的 `last_trade_time`。
2. `raw_tushare/stk_mins_by_date` 或 `derived/stk_mins_by_date` 读取新增 bar。
3. 只处理 `trade_time > last_trade_time` 的行。

输出：

1. 替换受影响的指标 by_date 分区。
2. 更新对应股票和频度的 `ema_state`。
3. 标记对应月份的 indicator research 分区待重建，或直接触发重建。

### 8.2 没有 state 的处理

没有 state 时不能瞎跑增量。

规则：

| 场景 | 处理 |
|---|---|
| 新上市股票，源数据从首根开始 | 从首根 K 线建立 state |
| 老股票缺 state，但已有多年历史 | 进入 bootstrap，全量计算该股票该频度 |
| 用户要求强制增量但 state 缺失 | 返回 `needs_bootstrap`，不假装成功 |

这样做能得到：

1. 新股能自然纳入。
2. 历史股票不会因为状态缺失而算错。
3. 增量任务失败原因可读，不会沉默丢指标。

### 8.3 源数据重写后的处理

如果某个源分区被替换：

```text
raw_tushare/stk_mins_by_date/freq=30/trade_date=2026-04-24
```

则对应指标可能过期：

```text
derived/stk_mins_indicators_by_date/indicator=macd/params_key=12_26_9/freq=30/trade_date>=2026-04-24
```

处理方式：

1. 记录 `indicator_recalc_queue`。
2. 从被替换分区的最早 `trade_time` 开始重算。
3. 如果只影响少量股票，可以按 `ts_code` 精确重算。
4. 如果无法判断影响股票范围，则按该频度全市场重算受影响日期之后的指标。

这样做能得到：

1. 源数据修复后指标不会悄悄过期。
2. 重算范围有依据，不用全库重来。
3. 页面后续可以展示“指标待重算”的风险。

---

## 9. research 重排流程

指标 by_date 是计算结果的主输出，research 是查询优化布局。

重排流程：

```text
读取 derived/stk_mins_indicators_by_date/indicator=macd/params_key=12_26_9/freq=*/trade_date=YYYY-MM-*
-> 按 ts_code 稳定 hash 到 bucket
-> 写入 _tmp/research/stk_mins_indicators_by_symbol_month/...
-> 校验行数
-> replace 正式 trade_month/bucket
```

触发方式：

1. 全量计算完成后，按月份重建。
2. 增量计算完成后，重建受影响月份。
3. 源数据修复后，重建受影响月份。

这样做能得到：

1. 指标计算和研究查询解耦。
2. 写入失败只影响某个月指标 research，不污染 by_date 主结果。
3. 后续做单股两年 MACD、BOLL、MA 时查询路径一致。

---

## 10. CLI 设计

第一版不要一次塞太多命令。建议先用一个主命令承接指标计算：

```bash
lake-console compute-stk-mins-indicator \
  --indicator macd \
  --mode full \
  --all-market \
  --freqs 30,60,90,120 \
  --start-date 2024-01-01 \
  --end-date 2026-04-30
```

增量：

```bash
lake-console compute-stk-mins-indicator \
  --indicator macd \
  --mode incremental \
  --all-market \
  --freqs 30,60,90,120 \
  --start-date 2026-05-01 \
  --end-date 2026-05-05
```

单股票验证：

```bash
lake-console compute-stk-mins-indicator \
  --indicator macd \
  --mode full \
  --ts-code 600000.SH \
  --freq 30 \
  --start-date 2025-01-01 \
  --end-date 2026-04-30
```

只重建 research：

```bash
lake-console rebuild-stk-mins-indicator-research \
  --indicator macd \
  --freq 30 \
  --trade-month 2026-04
```

进度输出必须包含：

| 字段 | 用途 |
|---|---|
| 百分比 | 知道整体进度 |
| `indicator` | 当前指标 |
| `freq` | 当前周期 |
| `bucket` 或 `ts_code` | 当前处理对象 |
| `trade_month` 或 `trade_date` | 当前范围 |
| `source_rows` | 已读取源行数 |
| `written_rows` | 已写入指标行数 |
| `state_updates` | 已更新状态数 |

---

## 11. 模块设计

建议目录：

```text
lake_console/backend/app/services/indicators/
  __init__.py
  models.py
  macd_spec.py
  macd_calculator.py
  indicator_source_reader.py
  indicator_by_date_writer.py
  indicator_state_store.py
  indicator_research_service.py
  indicator_recalc_queue.py
  indicator_progress.py
```

模块职责：

| 模块 | 职责 |
|---|---|
| `models.py` | 指标参数、运行摘要、state、queue 的结构 |
| `macd_spec.py` | `MACD(12,26,9)` 的参数、字段、版本 |
| `macd_calculator.py` | 全量和增量 MACD 计算，不做文件 IO |
| `indicator_source_reader.py` | 从 raw/derived/research 读取分钟线 |
| `indicator_by_date_writer.py` | 写指标 by_date 分区 |
| `indicator_state_store.py` | 读写 `ema_state` |
| `indicator_research_service.py` | 重建指标 research 层 |
| `indicator_recalc_queue.py` | 管理重算队列 |
| `indicator_progress.py` | CLI 进度输出 |

这样拆分能得到：

1. 计算逻辑可单测，不被文件系统拖住。
2. 文件写入逻辑复用 Lake 的 `_tmp -> 校验 -> replace`。
3. 后续 `MA/BOLL` 可以复用 reader/writer/progress，只新增各自 calculator/spec。

---

## 12. 后续指标扩展

### 12.1 MA

MA 是滚动窗口指标，不需要递推 state，但需要窗口预热。

输出示例：

```text
ma5, ma10, ma20, ma60
```

需要的能力：

1. 对每只股票按 `trade_time` 排序。
2. 增量时读取新增区间之前的 `max(window)-1` 根作为预热。
3. 输出和 MACD 共用指标 by_date / research 布局。

### 12.2 BOLL

BOLL 是滚动均值和标准差指标。

输出示例：

```text
boll_mid, boll_upper, boll_lower
```

需要的能力：

1. 读取窗口预热数据。
2. 增量时不能只读新增行，必须带足窗口历史。
3. 不需要 `ema_state`，但需要记录计算参数和预热范围。

### 12.3 指标 spec 统一字段

每个指标必须定义：

| 字段 | 含义 |
|---|---|
| `indicator_key` | 例如 `macd`、`ma`、`boll` |
| `params_key` | 参数版本，例如 `12_26_9` |
| `source_dataset_key` | 当前为 `stk_mins` |
| `source_freqs` | 支持的周期 |
| `input_columns` | 需要的源字段 |
| `output_columns` | 输出字段 |
| `stateful` | 是否需要 state |
| `warmup_bars` | 增量计算所需预热长度 |
| `indicator_version` | 算法版本 |

---

## 13. 校验与测试

第一批必须有这些测试：

| 测试 | 证明什么 |
|---|---|
| MACD 公式 fixture | pandas/numpy 计算与预期一致 |
| 跨日递推测试 | 第二天不重置 EMA |
| 不同 freq 独立测试 | `30` 与 `60` 状态互不污染 |
| 增量等价测试 | 全量结果与“先算到 T，再增量算 T+1”一致 |
| state 写入顺序测试 | 结果失败时 state 不前进 |
| by_date 写入测试 | `_tmp -> 校验 -> replace` 生效 |
| research 重排测试 | 同一股票可从 bucket 中查到连续月份 |
| 源分区替换入队测试 | raw/derived 分区替换后生成重算队列 |

手工验证：

```bash
lake-console compute-stk-mins-indicator --indicator macd --mode full --ts-code 600000.SH --freq 30 --start-date 2026-04-01 --end-date 2026-04-30
lake-console compute-stk-mins-indicator --indicator macd --mode incremental --ts-code 600000.SH --freq 30 --start-date 2026-05-01 --end-date 2026-05-05
lake-console rebuild-stk-mins-indicator-research --indicator macd --freq 30 --trade-month 2026-04
```

DuckDB 验证：

```sql
SELECT ts_code, trade_time, dif, dea, macd_bar
FROM read_parquet('<LAKE_ROOT>/derived/stk_mins_indicators_by_date/indicator=macd/params_key=12_26_9/freq=30/trade_date=2026-04-24/*.parquet')
WHERE ts_code = '600000.SH'
ORDER BY trade_time;
```

---

## 14. 性能与文件数量

### 14.1 by_date 指标层

单日全市场文件建议：

```text
128MB ~ 512MB / part
```

如果单日单频度结果很小，允许一个 `part-000.parquet`。

### 14.2 research 指标层

复用 `stk_mins` research 的 bucket 规则：

```text
bucket = stable_hash(ts_code) % 32
```

如果未来指标层明显膨胀，可以单独评估 `64` bucket，但不能和旧 bucket 数混用。

### 14.3 小文件控制

增量不能无限追加小文件。

规则：

1. by_date 分区采用替换，不采用追加。
2. research 月分区采用整月重建。
3. state 采用单文件全量替换。
4. queue 可以采用单文件覆盖或按状态 compact。

这样做能得到：

1. 文件数量可控。
2. DuckDB 查询规划更快。
3. 移动硬盘随机 IO 压力更低。

---

## 15. 里程碑

### M1：MACD 计算内核

目标：

1. 新增 `macd_calculator`。
2. 支持全量计算单个 `ts_code + freq` 的 MACD。
3. 支持从已有 state 增量递推。
4. 单测证明增量结果等价于全量结果。

不做：

1. 不写全市场 CLI。
2. 不做 research 重排。

### M2：指标 by_date 写入

目标：

1. 新增指标 by_date writer。
2. 支持单股票、单频度、一个小日期区间写入。
3. 使用 `_tmp -> 校验 -> replace`。
4. 结果写入后 DuckDB 可读。

### M3：EMA state

目标：

1. 新增 `indicator_state_store`。
2. state 只在结果分区成功替换后前进。
3. 支持缺 state 的 bootstrap 判断。
4. 支持 state 文件全量覆盖写。

### M4：全市场 full / incremental CLI

目标：

1. 新增 `compute-stk-mins-indicator`。
2. 支持 `--indicator macd`。
3. 支持 `--mode full|incremental`。
4. 支持 `--all-market` 和 `--ts-code`。
5. 有单行进度输出，显示当前 `freq/bucket/ts_code/date/written/state_updates`。

### M5：指标 research 重排

目标：

1. 新增 `rebuild-stk-mins-indicator-research`。
2. 从指标 by_date 重排到 indicator research。
3. 支持按 `freq + trade_month` 重建。
4. DuckDB 验证单股长周期查询。

### M6：源数据修复与重算队列

目标：

1. 新增 `indicator_recalc_queue`。
2. 源 raw/derived 分区替换后可生成待重算记录。
3. CLI 能列出和执行待重算任务。
4. 不自动调度，先保障手动可控。

### M7：MA / BOLL 扩展评审

目标：

1. 基于 MACD 已稳定的 reader/writer/research/state 模型，评审 MA/BOLL。
2. MA/BOLL 采用滚动窗口预热，不使用 EMA state。
3. 不在 MACD 第一批里夹带实现。

---

## 16. 关键风险

| 风险 | 影响 | 控制方式 |
|---|---|---|
| state 先更新、结果后失败 | 增量跳过未写数据 | state 永远最后写 |
| 源数据被重写但指标未重算 | 研究结果过期 | 写 recalc queue |
| by_date 与 research 不一致 | 查询结果不一致 | by_date 为主结果，research 只做重排 |
| 小文件膨胀 | DuckDB 查询变慢 | 分区替换，不追加；research 整月重建 |
| 计算口径漂移 | 不同指标/参数混用 | `indicator_key + params_key + indicator_version` 入路径和字段 |
| 误用未复权数据 | 指标不连续 | 输入契约明确当前分钟线已经前复权 |

---

## 17. 评审结论待确认

本方案建议先确认以下点，再进入代码：

1. MACD 输出字段是否采用 `float32`，state 采用 `double`。
2. 指标路径是否采用统一目录 `stk_mins_indicators_by_date`，通过 `indicator=macd` 区分。
3. 第一批 CLI 是否采用通用 `compute-stk-mins-indicator --indicator macd`，而不是单独 `compute-stk-mins-macd`。
4. 全市场 full 是否先要求 source research 已存在，再计算指标，避免直接扫描大量 by_date。
5. 源分区替换后，M6 之前是否先用文档/命令提示人工重算，M6 再补正式 queue。
