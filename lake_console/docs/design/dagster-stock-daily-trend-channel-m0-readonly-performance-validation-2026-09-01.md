# 股票日线趋势通道 M0 只读规模与性能验证报告

状态：M0 已通过；自动 repair 上限、历史分段和本地 API limit 已冻结；尚未开发、部署、写入正式 Lake 或启用 Sensor

日期：2026-09-01

对应方案：

- [股票日线趋势通道 Lake 数据集接入技术方案 v1](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-daily-trend-channel-dataset-onboarding-plan-v1.md)
- [股票日线趋势通道 Lake 数据集接入 LLD v1](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-daily-trend-channel-dataset-onboarding-low-level-design-v1.md)

---

## 1. 结论

M0 全部门禁通过，可以进入 M1 编码。冻结值如下：

| 合同 | 冻结值 |
| --- | ---: |
| 历史/repair 单 segment 交易日数 | `250` |
| 趋势自动 repair 股票数上限 | `500` |
| 本地 API 默认 `limit` | `300` |
| 本地 API 最大 `limit` | `2000` |
| 日常 qfq/lifecycle pool 硬上限 | `10000` |

自动 repair 上限采用：

```text
min(qfq 自动上限 500, 趋势实测安全上限 500) = 500
```

超过 500 只股票必须 fail closed，进入人工 dry-run 和单独批准流程；不得截断为前 500 只，也不得通过配置放大上限。

本轮只读取 `/Volumes/datasource/data_lake`。所有样本、候选文件和 benchmark 输出均位于：

```text
/private/tmp/goldenshare-stock-trend-channel-m0-20260901
```

没有写 `/Volumes/datasource/data_lake`、`/Volumes/datasource/data_lake_staging`、Dagster event storage 或业务数据库，也没有执行 job、sensor、materialization、bootstrap 或 repair。

---

## 2. 环境和口径

| 项 | 实测值 |
| --- | --- |
| 正式 Lake 根 | `/Volumes/datasource/data_lake` |
| qfq 数据集 | `gold/quote/stock_daily_qfq` |
| lifecycle | `silver/basic/stock_lifecycle/full/part-000.parquet` |
| stock basic | `silver/basic/stock_basic/full/part-000.parquet` |
| trade calendar | `silver/calendar/trade_calendar/full/part-000.parquet` |
| DuckDB | `1.5.2` |
| Python | `3.11.9` |
| DuckDB threads | `4` |
| DuckDB memory limit | `16GB`，沿用现有资源合同 |

历史股票范围按 lifecycle 半开区间校验：

```text
list_date <= trade_date < delist_date
```

`delist_date IS NULL` 表示右侧无界。没有使用 current stock basic 裁剪历史股票。

---

## 3. 正式 qfq 规模与质量

### 3.1 规模

| 指标 | 实测值 |
| --- | ---: |
| 历史范围 | `2014-01-02` ～ `2026-08-31` |
| 交易日/分区/文件数 | `3079` |
| 总行数 | `11,710,697` |
| 历史股票代码数 | `5565` |
| 单日最少行数 | `1275` |
| 单日平均行数 | `3803.41` |
| 单日中位数 | `3605` |
| 单日 P95 | `5453` |
| 单日最大行数 | `5547`，发生于 `2026-08-28` |
| qfq 总文件大小 | `824,719,268 bytes` |
| 平均文件大小 | `267,852.96 bytes` |
| 最小/最大文件大小 | `95,484 / 382,832 bytes` |
| schema 变体数 | `1` |

单日最大 qfq 行数 `5547`，低于 LLD 的 `10000` 行 fail-closed 门禁。

### 3.2 数据质量

以下异常计数全部为 `0`：

- 空股票代码、空交易日期；
- OHLC 空值、非有限值、非正数；
- OHLC 高低范围不一致；
- `(trade_date, ts_code)` 重复；
- qfq 股票缺失 lifecycle；
- qfq 行超出对应股票的 lifecycle 半开区间。

### 3.3 lifecycle 覆盖

| 指标 | 实测值 |
| --- | ---: |
| lifecycle 行数/代码数 | `5890` |
| 当前上市 | `5551` |
| 已退市 | `339` |
| 非 CNY | `0` |
| lifecycle 重复代码 | `0` |
| qfq 缺失 lifecycle 代码/行 | `0 / 0` |
| qfq 越 lifecycle 代码/行 | `0 / 0` |
| qfq 中存在历史行情的已退市代码 | `14` |
| 上述已退市代码历史行数 | `33,189` |

因此“全历史 + lifecycle 保留退市历史”的范围能够由当前正式数据完整支撑。

---

## 4. 公式与日常路径

### 4.1 公式一致性

使用 800 行确定性合成样本，按 250 个交易日拆成 4 个 segment，对照当前指数趋势通道计算器与 DuckDB 集合公式：

| 指标 | 实测值 |
| --- | ---: |
| raw 最大绝对误差 | `7.815970093361102e-14` |
| 4 位小数序列化不一致 | `0` |
| state 不一致 | `0` |
| segment 边界不一致 | `0` |

结论：`SEGMENT_TRADE_DAY_LIMIT = 250` 不改变公式和 state 语义。开发时仍须把这些边界样本固化为 golden tests；M0 临时脚本不能代替仓库测试。

### 4.2 全市场单日

目标日为 `2026-08-31`，使用上一交易日合成 state，执行 10 次隔离进程 benchmark：

| 指标 | 实测值 |
| --- | ---: |
| qfq/result 行 | `5545` |
| state 行 | `5551` |
| carry state 行 | `6` |
| 两个候选文件总大小 | `300,209 bytes` |
| elapsed 中位数 | `29.94 ms` |
| elapsed P95 | `34.63 ms` |
| elapsed 最大值 | `37.89 ms` |
| 峰值 RSS | `72,105,984 bytes`，约 `68.8 MiB` |
| temp spill | `0` |

单日路径明显低于 `120 s / 2 GiB / 1 GiB spill` 三项硬门禁。

---

## 5. Repair 矩阵

### 5.1 计算与文件编排实测

股票样本按历史行数确定性选取，覆盖 `1 / 20 / 100 / 500` 只股票及 `1 年 / 5 年 / 全历史`。下表中的候选字节是“受影响股票结果”的文件编排诊断值；正式 repair 会把未受影响行合并后写成完整分区，完整分区容量另见第 6 节。

| 股票 | 跨度 | 交易日 | 源行 | 计算 ms | 计算峰值 RSS MiB | 候选文件 | 编排候选 MB | 文件写入 ms | promotion ms | spill |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1 年 | 242 | 242 | 59.48 | 76.1 | 484 | 0.97 | 111.68 | 55.17 | 0 |
| 1 | 5 年 | 1210 | 1210 | 194.30 | 127.1 | 2420 | 4.86 | 739.21 | 282.48 | 0 |
| 1 | 全历史 | 3079 | 3079 | 354.68 | 221.8 | 6158 | 12.36 | 1592.93 | 736.16 | 0 |
| 20 | 1 年 | 242 | 4840 | 48.10 | 105.6 | 484 | 1.74 | 232.82 | 55.58 | 0 |
| 20 | 5 年 | 1210 | 24,200 | 156.98 | 191.7 | 2420 | 8.70 | 847.76 | 287.17 | 0 |
| 20 | 全历史 | 3079 | 61,580 | 365.50 | 337.8 | 6158 | 22.10 | 1995.02 | 766.75 | 0 |
| 100 | 1 年 | 242 | 24,200 | 106.45 | 167.6 | 484 | 3.64 | 224.87 | 56.20 | 0 |
| 100 | 5 年 | 1210 | 121,000 | 422.11 | 332.6 | 2420 | 18.56 | 1124.96 | 287.93 | 0 |
| 100 | 全历史 | 3079 | 307,900 | 726.92 | 613.6 | 6158 | 47.30 | 2564.45 | 746.67 | 0 |
| 500 | 1 年 | 242 | 120,946 | 345.41 | 289.1 | 484 | 11.61 | 320.29 | 54.81 | 0 |
| 500 | 5 年 | 1210 | 604,714 | 756.10 | 853.0 | 2420 | 60.57 | 1415.69 | 303.52 | 0 |
| 500 | 全历史 | 3079 | 1,536,897 | 1767.42 | 1645.4 | 6158 | 155.86 | 3948.92 | 896.08 | 0 |

最坏的 500 股票全历史计算峰值为约 `1.61 GiB`，低于 `2 GiB`；12 组均无 temp spill。最坏 6,158 文件的原子提升低于 `0.9 s`，文件提升不是自动 repair 的主瓶颈。

500 股票全历史计算距离 2 GiB 门禁仍有约 400 MiB 余量，因此实现必须继续遵守 250 日 segment、单 repair 串行、投影最小列和 `>500` fail closed，不能并行放大同一进程的 repair scope。

---

## 6. 250 日全市场分段、单文件归并与磁盘

对最近 250 个正式 qfq 分区执行全市场计算、`PARTITION_BY` 临时 chunks、逐日归并唯一 `part-000.parquet`、全量行数审计和临时目录内 `os.replace`：

| 指标 | 实测值 |
| --- | ---: |
| 日期范围 | `2025-08-20` ～ `2026-08-31` |
| qfq 输入文件 | `250` |
| result 行 | `1,367,602` |
| state 行 | `1,370,173` |
| carry state 行 | `2571` |
| staging chunks | `1142` |
| 最终候选文件 | `500` |
| 最终候选大小 | `101,813,757 bytes`，约 `97.1 MiB` |
| 计算 | `791.81 ms` |
| chunks 写入 | `1668.30 ms` |
| 单文件归并 | `1974.35 ms` |
| 全量行数审计 | `13.97 ms` |
| promotion | `49.83 ms` |
| 总耗时 | `4591.47 ms` |
| 峰值 RSS | `1,633,828,864 bytes`，约 `1.52 GiB` |
| temp spill | `0` |

这项验证证明：DuckDB 多 chunk 不能直接提升，但“分块写入 -> 每日归并单文件 -> 审计 -> 提升”的 LLD 路径在 250 日全市场规模下通过资源门禁。

由于正式趋势目标尚不存在，M0 不能读取真实历史趋势文件测量完整 repair 候选容量。使用最近 250 日全市场候选按全部 3079 日线性外推，得到保守的全历史候选估算：

```text
estimated_candidate_bytes = 1,253,938,232 bytes，约 1.17 GiB
duckdb_temp_budget         = 1,073,741,824 bytes，1 GiB
required_staging_free      = 2 * candidate + temp = 3,581,618,288 bytes，约 3.34 GiB
```

当前 formal Lake 与 staging 所在卷可用：

```text
2,514,958,323,712 bytes，约 2.29 TiB
```

可用空间约为门禁需求的 `702` 倍。该结论只证明当前容量充足；正式 bootstrap/repair 仍必须在每次执行前按当时文件和磁盘重新生成 plan，不能复用本报告数值跳过预检。

---

## 7. 本地 API 读取

使用 3079 个单股票、单日、单文件临时候选模拟最终分区布局。每次请求先扫描分区名，再只把最近 `limit` 个精确文件交给 DuckDB；每个 limit 执行 10 次隔离进程。

| limit | 选择文件 | 请求中位数 | 请求 P95/最大值 | 查询中位数 | 查询 P95 | 峰值 RSS |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 300 | 300 | `41.17 ms` | `60.04 ms` | `14.82 ms` | `33.09 ms` | `70,320,128 bytes` |
| 2000 | 2000 | `136.91 ms` | `191.70 ms` | `94.12 ms` | `146.05 ms` | `161,644,544 bytes` |

结果顺序、单一股票、公式版本和行数全部校验通过。因此保留 `limit` 默认 300、最大 2000；reader 必须继续先选择有界分区路径，禁止把全历史文件交给 DuckDB 后再过滤。

---

## 8. M0 之后的开发门禁

1. M1 才开始修改业务代码；本报告不代表任何实现已完成。
2. `TREND_AUTO_REPAIR_CODE_LIMIT` 固定为 `500`，不是配置项；501 及以上必须有负向测试。
3. `SEGMENT_TRADE_DAY_LIMIT` 固定为 `250`；不得为了省事改成全历史单段。
4. 正式 repair 候选必须包含完整分区；第 5 节的受影响股票候选不得被误用为 delta 正式文件。
5. 每日期的 chunks 必须归并成唯一 `part-000.parquet`，多 chunk 目录不得直接提升。
6. 自动 repair 不得并行处理多个 scope 来突破单进程资源门禁。
7. 本地 API 保持 300/2000 和有界文件发现，不增加全历史扫描 fallback。
8. 不新增“整代文件 + 原子指针”或 manifest 状态实体；未完成 repair 继续由 completion check 隔离。
9. 正式 bootstrap、repair、runless event、Sensor 启用、部署和验收均需要后续单独审批。

M0 的临时候选只用于性能和合同验证，不是正式数据事实源，也不能作为后续 Dagster readiness 或物理完整性证据。
