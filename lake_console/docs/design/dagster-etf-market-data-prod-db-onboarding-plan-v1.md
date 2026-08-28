# ETF 市场数据 DG 接入技术方案 v1

状态：重新基线阻塞；当前不可开发、Bootstrap、补事件或启用 Sensor
创建日期：2026-08-27
最近更新：2026-08-29
适用范围：`lake_console/orchestrator` 正式 Dagster 数据湖

## 1. 重新基线结论

旧方案把 ETF Basic、旧分钟激活池和 ETF 历史分钟线设计成三类相互依赖资产。旧激活池已经退场，因此原来的池 Raw/Silver 资产、只读白名单、快照 hash、路径、Job、Sensor 和建设顺序全部失效。

P8 不把 DG 上游白名单擅自改成 Basic Serving，也不设计新的 Lake 选择池。ETF Basic 是否独立入湖、分钟 Raw/Silver 的代码范围、历史覆盖解释和日常 ready contract 必须整体重新拍板；在此之前本文只保存已确认的生产表、湖路径、性能和安全事实。

## 2. 当前确认事实

截至 2026-08-27 的代码审计：正式 DG Catalog/Lake 尚无 ETF Basic、ETF 历史分钟 Raw/Silver、专属 Job、Sensor、Bootstrap 或 Check。

生产可用事实表：

| 事实 | Prod 表 | 业务字段 |
| --- | --- | --- |
| ETF Basic 源快照 | `raw_tushare.etf_basic` | `ts_code, csname, extname, cname, index_code, index_name, setup_date, list_date, list_status, exchange, mgr_name, custod_name, mgt_fee, etf_type` |
| ETF 历史分钟 | `raw_tushare.etf_minute_bar` | `ts_code, freq, trade_time, open, close, high, low, vol, amount, vwap, exchange` |

分钟主键为 `(ts_code, freq, trade_time)`，支持 `1min/5min/15min/30min/60min`。

旧 `ops.etf_series_active(resource='etf_mins')` 的 1,395 个代码只是一份历史测量集合；P8 已删除其代码基础设施并准备生产待执行 drop migration。该表不能成为未来 DG 白名单、Lake 资产或完整性事实源。

历史 TaskRun `9597` 的已完成部分曾提交 28,434,209 行、5,729 个 unit，六个月线性外推约 4,850 万行。该样本只用于说明分钟数据是大体量，不能证明最终覆盖或作为 Bootstrap 行数门禁。

## 3. 永久硬边界

1. 正式 Lake 根目录只能是 `/Volumes/datasource/data_lake`。
2. staging 只能是 `/Volumes/datasource/data_lake_staging`。
3. 禁止读取或写入 `/Volumes/datasource/goldenshare-tushare-lake` 作为 DG 事实源。
4. 禁止 Kopia。
5. DG 不重复请求 Tushare；数据只能通过批准的 Prod 只读合同进入 Lake。
6. Prod SQL 必须显式列、只读事务、有界查询，禁止 `SELECT *`。
7. 历史大批量写湖使用 Direct Lake Bootstrap，不制造海量 Dagster runs。
8. 候选文件先在 staging 完整校验，再以同文件系统 `os.replace()` 原子提升。
9. 文件写入、物理对账和 Runless Event 补录是三个独立授权步骤。
10. Silver 是 Raw 审计通过后的准入层，不偷偷补值、合成频率、重算 `vwap` 或丢字段。

## 4. 可保留的分钟资产候选形状

如果重新基线后批准 ETF 分钟入湖，五频物理分区仍是合理候选：

```text
/Volumes/datasource/data_lake/raw/tushare/etf_mins/
  freq=<1min|5min|15min|30min|60min>/
  trade_date=YYYY-MM-DD/part-000.parquet

/Volumes/datasource/data_lake/silver/quote/etf_mins/
  freq=<1min|5min|15min|30min|60min>/
  trade_date=YYYY-MM-DD/part-000.parquet
```

这只是已验证的存储形状候选，不代表资产名、分区名、范围、ready 或 checks 已批准。Raw 应保留 11 个业务字段和源端精度；`trade_date` 可从 `trade_time` 推导为物理分区键。Silver 是否保留完全相同列、哪些检查 blocking，仍需首次生产覆盖审计后拍板。

## 5. 性能与查询证据

未来设计仍应采用 set-based 读取：

1. 日常按频率和目标日做聚合 ready probe，明细最多五条单频查询。
2. Bootstrap 按一批交易日、一个频率流式读取，再由 DuckDB 按日拆文件。
3. 不按 ETF 数量扇出 Prod SQL，不把全历史明细装进 Python。
4. dry-run 必须输出 SQL 数、扫描行数、预计文件数、磁盘和临时空间峰值。
5. 任何查询、锁、空间或时间预算超限都 fail-closed。

旧方案曾以正常日约 447,795 行、六个月约 600 个 Raw 文件作为量级估算。这些是历史估算，不是当前范围确定后的正式预算；新 LLD 必须基于最终白名单与当前 Prod 只读 profiling 重算。

## 6. 必须重新拍板的问题

1. ETF Basic 是否作为独立 Raw/Silver 主数据资产入湖；读取 raw 还是 serving，保留哪些状态。
2. ETF 分钟的代码范围事实源是什么；当前 Basic、任务意图、实际物理集合三者如何分工。
3. 如何复现某次生产分钟任务的范围，而不依赖已删除的静态激活池。
4. 日常 ready 是否继续采用“ETF 专属 TaskRun 完成 + 物理覆盖”双门禁；TaskRun 身份和允许字段是什么。
5. 历史 Bootstrap 的可解释起止范围和缺口分类。
6. Silver 的 blocking/WARN 规则、停牌/零成交/源端空结果语义。
7. 最终资产名、动态分区、Job、Sensor、Check、事件补录范围和性能预算。

旧方案 D1/D3/D4 以及依赖池路径的 D10 已失效；其他历史决定也必须在新范围合同下重新确认，不能因曾经“已确认”就直接开工。

## 7. 当前禁止事项

1. 不增加对旧表的 Prod 白名单。
2. 不新增 Lake active-pool 资产、快照目录或 hash contract。
3. 不把 Basic Serving 自动当成分钟全历史覆盖集合。
4. 不运行 Dagster、Bootstrap、Prod 查询、正式 Lake 写入或 Runless Event。
5. 不修改 orchestrator 代码、Catalog、Job、Sensor、Check 或路径 helper。
6. 不触碰正在运行或已完成的 Prod ETF 分钟任务。

## 8. 重新进入开发的顺序

```text
范围和主数据合同拍板
-> 当前代码与 Prod 只读重新审计
-> 新 LLD（SQL/字段/路径/资产/check/性能/测试）
-> 小样本 dry-run
-> 独立 Bootstrap 授权
-> 文件全量对账
-> 独立事件补录授权
-> Sensor 默认 STOPPED 上线并自然观察
```

任何一步发现范围无法复现、查询预算不可接受或缺口语义不清，都必须停止并回到方案层，而不是恢复旧池或增加兼容路径。
