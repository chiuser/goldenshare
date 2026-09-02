# ETF 日线与复权因子 DG 接入 P0 真实验证报告

> 状态：P0 开发门禁已通过；21:00 后最新交易日可用性仍是 Sensor 启用前验收，不是开发阻断
> 验证时间：2026-09-02 11:39—11:50 CST
> 数据集：Tushare `fund_daily`、`fund_adj`
> 依据：ETF 日线接入技术方案、数据湖接入模板、Dagster 数据管道性能治理规范
> 边界：只读源端并写 `/private/tmp` 隔离样本；未运行 `dg`，未访问正式 Dagster instance，未读写正式 Lake

---

## 1. 先说结论

源合同、显式字段、分页和小样本性能都已经用真实项目代码验证，现有方向可行：

1. `fund_daily` Raw 固定保留 11 个源字段，正式单页 limit 为 `5000`。
2. `fund_adj` Raw 固定保留 4 个源字段，`discount_rate` 必须显式请求，正式单页 limit 为 `2000`。
3. 两个接口都按单个 `trade_date` 拉取。`fund_daily` 无业务参数会报错；`fund_adj` 无业务参数虽能返回数据，但不能证明某个交易日完整。
4. 三日样本没有主键重复、日期错位、字段漂移和无效复权因子。`discount_rate` 确实存在空值和极端值，不能做范围清洗。
5. 当前仓库已有 `execute_bounded_pages(...)` 和 `TushareRequestPolicy`，可以直接提供请求次数、重试、限速、时间和跨页重复门禁。新资产不需要修改旧 `_fetch_all_pages`，也不需要再造分页框架。
6. 正式实现应参考当前 idx factor writer 的 page-bounded DuckDB staging 结构：候选写到正式 staging，完成 read-back 和内容对账后再原子提升。
7. 盘中查询 `20260902` 时两个接口都是 0 行，只能证明盘中尚未发布。管理员已确认以 21:00 作为开发口径；实际 21:00 非空复验移到 Sensor 启用前完成。

本报告记录 P0 的点时证据；技术方案和 LLD 已在 2026-09-02 根据这些证据及当前代码完成收口。

---

## 2. 验证方法和样本边界

正式项目组件：

- `TushareResource.call(...)`
- `fetch_tushare_partition_to_raw(...)`
- `DuckDBResource`
- DuckDB 1.5.2、Tushare Python 1.4.29

代表日期：

| 位置 | 日期 |
| --- | --- |
| Bootstrap 首日 | `2025-01-02` |
| 2025 年末 | `2025-12-31` |
| 当前已完成最新样本 | `2026-09-01` |

验证体量严格有界：

| 项 | 实际数量 |
| --- | ---: |
| 正式 limit 三日真实请求 | 7 次 |
| 临时 Parquet | 6 个 |
| `fund_daily` 样本行 | 5,405 |
| `fund_adj` 样本行 | 5,501 |
| 临时 Parquet 总大小 | 326,003 bytes |
| 三日下载与写文件总耗时 | 4.05 秒 |

另外只对 `fund_daily@2026-09-01` 做了一次诊断分页复验，共 3 个请求。没有拉取 2025 年以来的全量数据。

---

## 3. 源接口真实行为

### 3.1 `fund_daily`

| 请求形状 | 结果 |
| --- | --- |
| 不传 `ts_code/trade_date` | 失败，错误码 `50101`，要求二者至少一个 |
| 只传对象 `159578.SZ` | 返回 542 个交易日，范围 `20240607..20260831` |
| 单日 `20260901` | 返回 2,105 行、2,105 个代码 |
| 对象 + 区间 | `510330.SH@20250825..20250901` 返回 6 行 |
| 盘中当天 `20260902 11:39` | 0 行 |

默认请求和显式请求都观察到以下 11 个字段：

```text
ts_code, trade_date, pre_close, open, high, low, close,
change, pct_chg, vol, amount
```

Raw 必须保留源字段 `change`。本报告不引入任何改名结论。

`20260901` 还出现了 `158008.OF`。这再次说明 Raw 不能先按 `.SH/.SZ` 过滤；是否属于场内 ETF，由 Silver 使用最新 ready ETF Basic 判断。

### 3.2 `fund_adj`

| 请求形状 | 结果 |
| --- | --- |
| 不传业务参数、`limit=100` | 返回最新日 100 行；只是一个受限页，不是完整分区 |
| 只传对象 `159578.SZ`、`limit=100` | 返回最近 100 行，必须继续分页才是对象历史 |
| 单日默认字段 | 只有 `ts_code,trade_date,adj_factor` |
| 单日显式关键字段 | 增加 `discount_rate`，样本值可正常返回 |
| 对象 + 区间 | `510330.SH@20250825..20250901` 返回 6 行 |
| 盘中当天 `20260902 11:39` | 0 行 |

正式字段固定为：

```text
ts_code, trade_date, adj_factor, discount_rate
```

`discount_rate` 不是默认字段。实现如果省略显式 `fields`，Raw 会静默缺列，因此字段列表必须是受测试保护的代码合同。

---

## 4. 分页结论

### 4.1 正式 limit 下的真实页数

| 接口 | 日期 | 页行数 | 总行数 |
| --- | --- | --- | ---: |
| `fund_daily` | `20250102` | `1452` | 1,452 |
| `fund_daily` | `20251231` | `1848` | 1,848 |
| `fund_daily` | `20260901` | `2105` | 2,105 |
| `fund_adj` | `20250102` | `1501` | 1,501 |
| `fund_adj` | `20251231` | `1862` | 1,862 |
| `fund_adj` | `20260901` | `2000 + 138` | 2,138 |

`fund_adj` 已真实走到第二页，证明不能只取第一页。

### 4.2 `fund_daily` 分页链复验

正式 limit 为 `5000`，三日样本都只有一页。为了验证连接器的 offset 合并行为，另用诊断 limit `1000` 重拉 `20260901`：

```text
offset=0     -> 1000
offset=1000  -> 1000
offset=2000  -> 105
```

合并结果共 2,105 行；与正式 limit 文件双向 `EXCEPT ALL`，差异均为 0。诊断 limit 不进入生产合同。

### 4.3 用于请求预算的真实页数

| 接口 | 正式 limit | 当前最大真实页数 | 冻结的物理请求预算 | 理由 |
| --- | ---: | ---: | ---: | --- |
| `fund_daily` | 5,000 | 1 | `max_retries=1, max_requests=2, max_elapsed=30s` | 支持一次重试或第二页 |
| `fund_adj` | 2,000 | 2 | `max_retries=1, max_requests=4, max_elapsed=30s` | 支持两页各一次重试 |

新资产直接复用 `execute_bounded_pages(...)`；达到请求或时间预算仍未取得短页时 fail-closed。`max_requests` 是物理网络尝试数，重试也占预算。

CodeGraph 显示旧 `_fetch_all_pages` 被多个股票和基础信息资产间接使用，因此本需求明确不修改它。也不新增“第 N 个巨大满页”的数据集 fake 测试；通用 paginator 的满页/预算语义由现有共享测试负责，新资产只证明 budget failure 不会提升候选。

---

## 5. 三日数据质量观察

### 5.1 `fund_daily`

三个日期合计 5,405 行：

- 主键空值：0；
- 重复 `ts_code + trade_date`：0；
- 返回日期错位：0；
- 数值空值和非有限值：0；
- 非正价格：0；
- 负成交量/成交额：0；
- OHLC 关系错误：0；
- `change - (close - pre_close)` 最大绝对误差：`1.48e-14`；
- `pct_chg - (close - pre_close) / pre_close * 100` 最大绝对误差：`0.005497` 个百分点。

建议在 LLD 中冻结：

```text
change 公式容差：1e-6 元
pct_chg 公式容差：0.01 个百分点
```

这两个检查用于准入判断，不修改源值。

### 5.2 `fund_adj`

三个日期合计 5,501 行：

- 主键空值：0；
- 重复 `ts_code + trade_date`：0；
- 返回日期错位：0；
- `adj_factor` 空值、非有限或不大于 0：0；
- `discount_rate` 空值：8；
- `discount_rate` 非有限值：0；
- `discount_rate` 最小值：`-72.4787`；
- `discount_rate` 最大值：`9940.7`。

极端值主要出现在部分货币基金等源端事实中。按已拍板口径，Raw 和 Silver 都保留；只允许为空和有限数值检查，不做正负号或绝对值范围限制。

### 5.3 两个 Raw 不能互相当覆盖基线

| 日期 | `fund_daily` 代码 | `fund_adj` 代码 | 日线独有 | 因子独有 |
| --- | ---: | ---: | ---: | ---: |
| `20250102` | 1,452 | 1,501 | 0 | 49 |
| `20251231` | 1,848 | 1,862 | 0 | 14 |
| `20260901` | 2,105 | 2,138 | 1 | 34 |

两个接口覆盖范围本来就不完全相同。Raw 各自保存源端事实，不能用“两个 Raw 代码集合必须相等”作为阻断规则。Silver 是否应有某个 ETF，只能用同一次执行冻结的最新 ready ETF Basic 做范围审计。

---

## 6. 性能与容量

### 6.1 单分区表现

| 接口/日期 | 行数 | 文件大小 | 总耗时 | API 耗时 | 页数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `fund_daily@20250102` | 1,452 | 69,400 B | 1,787 ms | 1,516 ms | 1 |
| `fund_daily@20251231` | 1,848 | 86,313 B | 523 ms | 188 ms | 1 |
| `fund_daily@20260901` | 2,105 | 95,801 B | 588 ms | 192 ms | 1 |
| `fund_adj@20250102` | 1,501 | 20,969 B | 256 ms | 80 ms | 1 |
| `fund_adj@20251231` | 1,862 | 25,432 B | 320 ms | 108 ms | 1 |
| `fund_adj@20260901` | 2,138 | 28,088 B | 461 ms | 228 ms | 2 |

首个请求包含依赖加载和冷启动，后续单分区保持在亚秒级。

### 6.2 内存、压缩和 DuckDB

- 首个冷启动 Python 分配峰值约 35.3 MB；稳定单分区额外分配峰值不超过 2.4 MB。
- 进程最大 RSS 从 125.6 MB 上升到 245.5 MB；该值包含 Python、Dagster、Pandas、Tushare 和 DuckDB 的一次性加载，不是单分区常驻行集。
- 六个 Parquet 共 326,003 B；同数据 CSV 共 601,732 B，CSV/Parquet 大小比为 1.846。
- DuckDB 一次扫描 6 个文件、10,906 行并完成聚合质量检查耗时 206 ms，临时目录写入 0 B，没有 spill。

按样本平均大小外推 404 个 Raw 日期约 42 MiB；Silver 不会大于对应 Raw。即使把四层文件、候选文件和增长余量一起计算，技术方案中“总体低于 0.5 GB”仍是保守估算。

### 6.3 建议冻结的批次口径

- Direct Lake Bootstrap 每批最多 20 个交易日；每个 `asset + trade_date` 完成即写 checkpoint。
- 源请求保持串行，不新增并发。复用 `TushareRequestPolicy` 当前 `0.13` 秒最小间隔；P0 连续请求未触发限流，耗尽有界重试后停止当前 batch 并按 checkpoint 续跑。
- 磁盘 preflight 使用计划新增字节的 `2.5` 倍作为最低安全余量，覆盖候选、正式文件和增长误差。
- 常驻内存只允许一个接口、一个交易日的分页结果；不跨日积累 DataFrame 或 Python 行列表。

20 日批次不是一个 20 日大事务。它只是 checkpoint 调度上限，每个文件仍独立校验、独立提升、独立恢复。

---

## 7. 当前代码与后续编码要求

### 当前可直接复用的部分

- `TushareResource` 强制显式 fields，能防止 `discount_rate` 静默遗漏。
- `execute_bounded_pages(...)` 已支持短页终止、请求/时间预算、重试、限速、跨页重复和 page consumer。
- idx factor Raw writer 已给出 page-bounded DataFrame -> DuckDB accumulator -> 外置 staging -> `os.replace()` 的当前实现参考。
- 单日数据量很小，不需要客户端缓存、并发或跨日内存结构。

### 必须在 LLD 明确的缺口

1. 新资产要定义自己的小预算 `TushareRequestPolicy`，不能使用共享默认的 1,200 请求上限。
2. 新 writer 必须写 `/Volumes/datasource/data_lake_staging/<operation_id>/...`，完成候选 read-back 后才提升正式 Lake。
3. 页内日期/key 在消费时阻断；跨页重复由共享 paginator 阻断；完整候选仍要统一做 schema、日期、主键和行数复核。
4. 21:00 是管理员接受的开发假设，不是本报告已验证的源端发布时间；启用前仍需同口径实测。

没有必要新增客户端、缓存层、状态表或专用分页框架，也没有必要修改旧 `_fetch_all_pages`。

---

## 8. Sensor 启用前剩余动作

在一个正常交易日的上海时间 21:00 后，对当天执行：

1. `fund_daily`：显式 11 字段、`limit=5000`、按短页结束；
2. `fund_adj`：显式 4 字段、`limit=2000`、按短页结束；
3. 验证两份结果都非空、日期完全等于当天、字段合同一致、主键无重复；
4. 记录首次成功时间、行数、页数和耗时。

通过后才允许启用四个新 Sensor。若 21:00 仍未发布，不能擅自改成更晚的 Sensor 时间；先记录真实可用时点，再交付 review。该动作不再阻断 LLD 和 P1—P5 开发。

## 9. 边界声明

- 未运行任何 `dg` 命令。
- 未访问或修改正式 Dagster instance、动态分区、materialization、check、runless event、job 或 sensor。
- 未读取或写入 `/Volumes/datasource/data_lake`。
- 未写入 `/Volumes/datasource/data_lake_staging`；所有样本均位于本机 `/private/tmp/etf-daily-p0.k9X5kr`。
- 未从 Prod DB 拉取数据。
- 未执行全历史同步。
