# 股票分钟线盘后尾段：Raw 保留、Silver 过滤方案

**状态：代码与隔离验证完成，待单独批准 2026-09-29 数据恢复。**
**日期：2026-09-29**

## 1. 要解决什么

2026-09-29 的 Tushare `stk_mins` 实测表明，北交所股票 `920000.BJ` 在五种频度均会返回 `15:01–15:30` 的尾段。当前 Prod 标准化器把所有 `15:00` 之后的分钟统一作为“非交易时段”拒绝，导致 `ops.task_run.rows_rejected=13,920`。DG 的分钟 Raw sensor 对全市场任务要求零 rejected row，因此正确地没有启动 Lake 更新。

这个问题不是“把 rejected 视作成功”可以解决的。原始层不应丢弃来源真实返回的分钟行；但标准化 Silver、前复权和技术指标也不应把北交所盘后尾段混进常规盘中 K 线。

本方案的最终边界：

| 层 | 对任何代码的 `15:01–15:30` | 原因 |
| --- | --- | --- |
| Prod `raw_tushare.stk_mins` | 保留 | 忠实保存已批准来源的原始分钟事实。 |
| DG `raw_tushare_stk_mins_*` | 保留 | 只读导出 Prod Raw，不擅自过滤来源。 |
| DG `silver_stk_mins_*` | 过滤 | Silver 表示供 QFQ/技术指标使用的常规交易时段分钟事实。 |
| QFQ、MACD/KDJ、财富成交额等下游 | 不接收 | 它们只消费经过上述过滤的 Silver。 |

## 2. 已核实事实

1. Tushare MCP 对 `920000.BJ / 2026-09-29` 的实测：
   - `1min` 返回 `15:01` 至 `15:30`；
   - `5/15/30/60min` 都返回以 `15:30` 收束的盘后 bar；
   - `15:01` 或对应聚合 bar 有成交，后续不少 bar 为零成交延续价格。因此不能以“零成交”作为删除理由。同期 `600000.SH`、`000001.SZ` 样本当前仅返回至 `15:00`；这是当日源行为，不能作为以后永久删除沪深盘后记录的依据。
2. 北交所官方交易规则将 `15:00–15:30` 列为盘后相关交易/确认时段；这不是沪深普通连续竞价时段。生产资料参见[北京证券交易所交易规则](https://www.bse.cn/jygl_list/200028217.html)。
3. 当前 `src/foundation/ingestion/row_transforms.py::_stk_mins_row_transform` 固定只允许 `09:30–11:30`、`13:00–15:00`，且在代码后缀规范化前做此判断，直接造成 reject。
4. DG Prod Raw 导出没有 `<= 15:00` SQL 条件，Raw checks 也只审计 schema、日期、频度、键和值域。因此 Prod 只要保存，这一层天然能保留尾段。
5. DG Silver 当前从 `target_filtered` 直接形成最终行；粗频度的重算辅助会忽略 `15:30`，但原始 target 行仍可能写进 Silver。它不是统一、可证明的过滤边界。

## 3. 范围与非目标

### 本次做

- Prod `stk_mins` 标准化允许任何合法股票代码额外接收当日 `15:01:00–15:30:00`；保留既有字段和原始 OHLCVA 值。
- DG Raw 对该尾段的保留行为增加回归保护。
- DG Silver 在所有频度的共同输入入口过滤 `trade_time > 15:00:00`，并记录被过滤数量。
- 使用既有 Silver value-domain check 防止盘后行错误进入 Silver；不新增 check 名称、数量或事件。
- 完成隔离测试、静态门禁、文档对账。正式 Prod/Lake 恢复另行审批。

### 明确不做

- 不改变表 schema、Parquet schema、路径、分区、asset/job/sensor/check 名称、run key、调度时间或 TaskRun 零 rejected 门槛。
- 不新增 `session_tag`、例外表、seed、环境变量、动态分区、catalog 条目或 Dagster 状态实体。
- 不允许午间、`15:31` 及任何不在既有常规时段或新增 `15:01–15:30` 尾段内的时间借此放宽。
- 不回写或重写历史 prod/Lake 文件。此前已经被 Prod 拒绝的尾段需要从 Tushare 受控重拉，不能凭空恢复。
- 不修改 QFQ、MACD/KDJ、财富成交额的计算或 readiness；它们的输入边界由 Silver 统一保障。

## 4. 长期合同

### 4.1 Prod Raw 接收合同

定义唯一纯函数：给定已规范化的 `ts_code` 与 `trade_time`，判断是否属于可保存的来源分钟。

```text
所有股票：09:30:00–11:30:00 或 13:00:00–15:30:00
其它任何时间：reject，继续沿用 normalize.row_transform_failed
```

代码仍必须先规范化 `ts_code`，再决定时段，保证输出身份稳定；但时段判断不得依赖交易所后缀。频度不改变允许时间：五种频度按相同市场无关边界处理。

### 4.2 DG Raw 合同

DG Raw 是 Prod Raw 的列式镜像：同一 `freq + ts_code + trade_time` 的行必须原样可导出。Raw 不把盘后时间标记为 value-domain 失败，也不为它新增业务过滤。Raw 的键完整性、日期一致性、频度和值域规则保持不变。

### 4.3 DG Silver 合同

Silver 的标准时段上界固定为 `15:00:00`，不因交易所后缀放宽。过滤发生在 target 与 one-minute 两条输入支路建立后、身份映射/停牌/价格修正/粗频度重算之前：

```text
Raw input
  -> 去掉 trade_time > 15:00:00
  -> 原有身份、停牌、价格、冻结代码处理
  -> 1m 输出，或由 1m 重算/补齐粗频度
  -> Silver
```

这只删除盘后尾段，不改当前 `13:00` 与 `13:01` 的已有口径。`SilverStkMinsWriteResult` 追加小型计数 `post_close_filtered_row_count`；materialization metadata 仅记录计数，不记录代码或分钟全集。

既有 `silver_stk_mins_value_domain_check` 增加“Silver 内 `trade_time > 15:00:00` 必须为零”的规则。check 名称、blocking 级别、数量保持不变。

## 5. 实施结果和正式恢复顺序

2026-09-29 已完成：Raw 的市场无关 `15:30` 接收边界、Silver 的共同 `<=15:00` 输入过滤、冻结历史行的同一过滤、既有 value-domain check/readiness 的盘后行防线，以及对应的隔离测试。没有运行正式 job、sensor 或写入 Prod、Lake、Dagster 状态。

验证结果：根 normalizer 相关测试通过；分钟 Silver 的 M5B、freeze policy、readiness 隔离 suites 通过；静态门禁 `test_run_contract_static_gates.py` 为 113 passed。全仓治理 runner 目前因不属于本专项的 ETF 例外模块缺失而无法完整导入全部 check 模块，未作为本专项代码问题处理。

1. **Prod 发布前只读核验：** 重新取 Tushare `.BJ` 五频度样本，审计当前 Prod reject 明细与同日普通 `.SH/.SZ` 边界；确认没有其它来源/市场语义被扩展。
2. **受控 Prod 数据恢复：** 单独批准后，重新同步受影响交易日的 `.BJ` 五频度，要求 TaskRun 零 rejected。仅恢复来源确有记录的日期。
3. **DG 下游恢复：** 单独批准后，按 Raw -> Silver -> QFQ -> factor repair -> MACD/KDJ -> 财富成交额的已有依赖顺序重建受影响日期。每一步的既有 checks 必须全绿，失败即停止。
4. **最终审计：** Raw 含批准尾段、Silver 和所有下游不含 `>15:00`，且 2026-09-29 不再因为该原因被 TaskRun 门禁阻断。

## 6. 性能与安全

- 时段判断是每行常数时间，Prod 不增加查询、网络请求、表或索引。
- Silver 只增加一个已有 DuckDB relation 上的时间谓词和一个聚合计数；不新增文件扫描、event 查询或 sensor 热路径工作。
- Sensor 仍只读取 TaskRun 摘要和已批准的 `(freq, ts_code)` 覆盖。零 rejected 的门槛不降低。
- 每个正式写阶段仍遵循候选校验、同文件系统 `os.replace()` 和既有幂等规则；本方案不引入备份/Kopia。

## 7. 验收标准

- `.BJ/.SH/.SZ` 的 `15:01`、`15:30` 五频度样本均可进入 Prod Raw；所有代码的 `12:00`、`15:31` 仍被拒绝。
- DG Raw 从包含 `.BJ` 尾段的模拟 Prod 结果导出后，行、键和值不丢失。
- DG Silver 五频度从同一 Raw 输入生成后，所有 `trade_time > 15:00` 行为零，计数可见；其他常规时段行保持原行为。
- 原有 asset/check/job/sensor 名称、数量、分区、run key、cursor 和性能窗口不变。
- 目标测试、修改文件 Ruff、静态门禁和 `git diff --check` 通过；正式 Prod/Lake/Dagster 写入在后续单独审批前不得执行。

## 8. 风险与停止条件

- 若实测显示 Tushare 提供超过 `15:30` 的盘后分钟，或返回跨自然日分钟，停止并修订合同；不能把本次 `15:01–15:30` 边界自动扩大。
- 若 Silver 输入过滤会改变 `15:00` 前的既有结果、粗频度窗口、价格修正或冻结行保留，停止并定位 SQL 边界。
- 若任何消费者直接读取 Raw 并把尾段视为标准交易分钟，必须先列入影响面并单独确认，不能只靠 Silver 修复。

## 9. 权威实现位置

- Prod：`src/foundation/ingestion/row_transforms.py` 与 `src/foundation/datasets/definitions/market_equity.py`。
- DG：`lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py`、`checks/stk_mins_checks.py`。
- 代码级改动、SQL 落点、测试矩阵和历史恢复边界见配套 [LLD](stk-mins-bse-post-close-raw-retention-low-level-design.md)。
