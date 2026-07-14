# Dagster 股票分钟线 QFQ MACD/KDJ Reconciliation Recovery R5 LLD

状态：R5-P0 至 R5-P5B 已完成；四批 completion 状态已按 QFQ 触发日独立可见。后续只剩 P6A 只读运行链路验收与 P6B sensor 恢复审批。

更新时间：2026-07-14

## 1. 一句话结论

`2026-07-08`、`2026-07-09`、`2026-07-10`、`2026-07-13` 的 qfq factor repair 都改写了历史 QFQ，因此必须分别重算同批受影响代码的 MACD/KDJ。R5-P0 已消除 source scope 与全段 state 的代码级阻断；R5-P2 已补齐四个日期的 28 份 state 文件；R5-P3 已按四个精确上游批次完成历史 repair。四批合计 253 个互不重叠代码，均由成功 run、逐批 14 条 completion 历史事件和物理文件审计证实。

R5 的顺序是：先完成两项 fail-closed 代码硬化，再按交易日顺序补齐 `2026-07-08`、`2026-07-09`、`2026-07-10`、`2026-07-13` 的 MACD/KDJ daily state，最后按同一顺序对四个 qfq repair 批次分别做历史 reconciliation。R5 不补全历史 Dagster 分区事件，不改变日常 sensor 的触发机制。

## 2. 目标、边界与硬约束

### 2.1 目标

1. 让 scoped MACD/KDJ repair 只读取 qfq factor repair 当前给出的 affected code 范围，不再为少量受影响代码扫描全市场历史文件。
2. repair 开始写任何指标或 state 文件前，确认完整 target range 的 state 文件都存在；缺任意一份时立即失败且不写 completion check。
3. 用既有 `gold_stk_mins_qfq_macd_kdj_daily_update_job` 顺序补齐四个缺失日期的 14 个 daily asset/state 状态，再执行一次正式 scoped repair。
4. 保持 `gold_stk_mins_qfq_macd_kdj_repair_completed_check` 的轻量语义：成功后只写 14 个 reconciliation completion check，不为 3,044 个历史日期补 materialization、普通 check 或 runless event。

### 2.2 本轮不做

1. 不改 qfq、MACD 或 KDJ 公式，不改 Parquet schema、路径、分区模型、资产名、job 名、sensor 名、run key 或 `upstream_batch_id` 口径。
2. 不修改 `gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor` 的事件触发逻辑，也不为它新增历史 backlog polling 或自动重跑能力。
3. 不对历史 `TProtocolException: Invalid data` 猜测根因并写兜底重试。该异常只在历史 tick 中出现，当前相同 readiness 重放通过，尚无可复现的坏文件证据。
4. 不新增 asset、check、job、sensor、resource、数据库表、配置项或新的状态实体。
5. 不直接 SQL 修改 Dagster PostgreSQL，不写 prod 数据库，不做全历史 runless event 补录，不删除既有 run/event/check 历史。
6. 本文只定义后续写入前的代码、preflight、备份和执行门禁；本次文档落地不写 lake、不写 Dagster instance、不启停 sensor。

### 2.3 不变量

| 不变量 | R5 处理方式 |
|---|---|
| qfq repair scope | 仍以当前 `gold_stk_mins_qfq_factor_repair_status(...)` 的 `start/end/codes/hash/upstream_batch_id` 为唯一事实源；运行时重新读取，不把本文件中的任何固定代码数或日期硬编码进生产代码。 |
| 全七频度 completion | repair completion 固定覆盖 `1/5/15/30/60/90/120` 七个 indicator 与七个 state asset，共 14 个 check event。 |
| state merge | 继续只替换 affected code 的 state 行，保留同日 state 文件内未受影响代码；不得整文件用 scoped 结果覆盖。 |
| 日常连续性 | daily 仍必须要求上一 expected trade date 的 state ready；R5 只按该既有规则补洞，不放宽门禁。 |
| 并发 | repair 继续使用既有 `GOLD_STK_MINS_QFQ_WRITER_POOL`；正式执行窗口还必须单独防止 sensor 与人工恢复并发。 |

## 3. 已核验事实与根因

### 3.1 初始单批修复基线（历史记录）

只读 preflight 报告：`/private/tmp/stk_mins_qfq_macd_kdj_reconciliation_preflight_20260714T081142Z.json`。

| 项 | 当前事实 |
|---|---|
| qfq factor repair 目标日 | `2026-07-13` |
| repair expected range | `2014-01-02` 至 `2026-07-13`，共 3,044 个实际交易日 |
| affected scope | 33 个代码，hash 为 `596cb3d8ae8fe1475512c2b52663f9f90a980c9e40223712673a6bf2b933311b` |
| 上游批次 | `qfq_factor_repair:2026-07-13:6e5e6183709d` |
| 动态分区 | 3,044 个目标日均已注册，无注册缺口 |
| 当前 completion gate | 不通过。现存 completion 属于 7 月 7 日的 32-code 旧批次，不能覆盖当前 33-code/hash/upstream batch。 |
| 相关 active run | qfq daily、qfq factor repair、MACD/KDJ daily、MACD/KDJ repair 均为 0。 |

上表是 R5 初始针对 `2026-07-13` 的冻结基线，不是最终执行范围。后续只读审计发现 `2026-07-08/09/10` 也各有独立 qfq factor repair scope，故 P3 按四批分别执行。任何 repair 运行前仍必须重新读取 qfq repair status；若日期、范围、code count、hash 或 upstream batch 任一变化，停止并重新生成计划，不得复用本表作为 run config。

### 3.2 四个 state 缺口及因果链

只读原因审计：`/private/tmp/stk_mins_qfq_macd_kdj_missing_state_cause_audit_20260714T081646Z.json`；逻辑重放：`/private/tmp/stk_mins_qfq_macd_kdj_sensor_replay_audit_20260714T081902Z.json`。

| 日期 | QFQ daily / factor repair | MACD/KDJ 事实 | 正确处理 |
|---|---|---|---|
| `2026-07-08` | 两个上游均成功 | 14 个 indicator/state asset 都没有 materialization。qfq factor repair 成功后的 daily run-status sensor tick 在提交 RunRequest 前报 DuckDB `TProtocolException: Invalid data`。 | 由人工按既有 daily job 补跑。 |
| `2026-07-09` | 两个上游均成功 | 上一日 `2026-07-08` state 未 ready，因此 sensor 正确 skip。 | 等 7 月 8 日全绿后补跑。 |
| `2026-07-10` | 两个上游均成功 | 上一日 `2026-07-09` state 未 ready，因此 sensor 正确 skip。 | 等 7 月 9 日全绿后补跑。 |
| `2026-07-13` | 两个上游均成功 | 上一日 `2026-07-10` state 未 ready，因此 sensor 正确 skip。 | 等 7 月 10 日全绿后补跑。 |

结论：这是一个由 7 月 8 日单次 sensor user-code 异常引起的连续性空洞，不是 qfq 数据缺失，也不是后续 sensor 逻辑错误。R5 不修改 daily sensor；人工顺序补齐正是恢复既有连续性语义的最小动作。

### 3.3 当前性能与写入规模

| 对象 | 当前实现 | R5 目标 / 事实 |
|---|---:|---:|
| repair qfq 源文件 | 370,023 个，约 83.8 GiB，全市场按年份 glob | 初始 7 月 13 日单批为 2,260 个、约 494 MiB；最终四批合并范围另见 P3 执行结果 |
| indicator 年文件 | 2,260 个，约 1.18 GiB | repair 会重写该范围内已有或应创建的年文件 |
| state 文件 | 3,044 日期 × 7 频度 = 21,308 个；已有 21,280 个 | 缺 `2026-07-08/09/10/13` × 7 = 28 个；必须先由 daily job 生成 |
| 现有 state 体量 | 约 3.46 GiB、905,379,552 行 | scoped repair 仍会 merge/replace 全部 target state 文件，不能忽略写入风险 |
| Dagster reconciliation 状态 | 14 个 completion check | 继续只写 14 个，不扩成 3,044 日期的历史事件 |

`/Volumes/datasource` 当前可用约 2.3 TiB，因此后续约 4.64 GiB 的 affected-file quarantine 备份不受容量阻断；但备份仍是正式 lake 写入，必须单独审批。

## 4. 当前实现差距

### 4.1 source discovery 没有消费 repair code scope

`discover_gold_stk_mins_qfq_source_year_paths(...)` 目前只接收 `freq/trade_dates`，对每个目标年和上一年执行：

```text
freq=<freq>/ts_code=*/year=<year>/part-000.parquet
```

`gold_stk_mins_qfq_macd_kdj_repair_op(...)` 虽然随后把 `stock_codes` 传给 writer 过滤 replacement rows，但 DuckDB 已经需要规划并读取全市场 source file 集合。这与 affected-code scoped repair 的意图相矛盾，也是 83.8 GiB 扫描的直接根因。

CodeGraph 影响面审计确认该 helper 同时被 daily writer、五类 checks、历史 bootstrap/history 工具和 repair op 使用。R5 只能给 helper 增加可选 code scope，且默认必须保持当前全市场行为；只有 repair op 传入显式 code scope。

### 4.2 M10 的“全量 preflight”当前不覆盖整段 state target

repair op 现在会在写入前检查：expected calendar、目标日期注册、各频度 source path，以及 `start_trade_date` 前一 expected date 的 state。

但是 scoped repair 随后会按 `target_dates` 依次调用 `_write_state_partition_file(...)`。该函数在 scoped state 文件不存在时才抛 `FileNotFoundError`。因此像当前 7 月 8 日这样的 state 缺口，会在前面年份和频度的 indicator/state 已经写入后才暴露，留下跨文件的部分修复结果。

R5 必须把“所有 target state 文件存在”纳入写前 preflight。它不取代每个文件现有的临时文件校验和 `os.replace`，而是把已知的缺文件风险提前阻断。

### 4.3 当前 repair 不能接受部分频度

repair config schema 虽允许传 `freqs`，但 `_repair_completion_asset_keys()` 无条件写全七频度的 14 个 completion check。若某次仅运行部分频度，completion metadata 会声称全频度 repair 已完成，语义错误。

R5 必须要求 `freqs` 严格等于 `STK_MINS_QFQ_FREQS` 的标准全量顺序；缺少、重复、额外或重排的频度均 fail closed。自动 sensor 已经传全七频度，因此这一收紧不改变正常触发行为。

## 5. R5.1 代码实现：限定 repair source 范围

### 5.1 改动文件与职责

| 文件 | R5 改动 |
|---|---|
| `defs/stk_mins_qfq_macd_kdj.py` | 为 `discover_gold_stk_mins_qfq_source_year_paths(...)` 增加可选 `stock_codes: Sequence[str] | None = None`。 |
| `defs/ops/gold_stk_mins_qfq_macd_kdj_repair.py` | repair op 传入当前已核验的 `stock_codes`；增加全频度与所有 target state 的写前门禁。 |
| `tests/test_stk_mins_qfq_m12_macd_kdj.py` | 锁住 source helper 的全市场默认与显式 scope 行为。 |
| `tests/test_stk_mins_qfq_macd_kdj_repair_op_contracts.py` | 锁住 repair 的 source scope、全频度、缺 state fail-before-write 和 completion-event 语义。 |
| `tests/test_run_contract_static_gates.py` | 防止 repair 回到全市场 source discovery 或允许不完整频度。 |

不修改 daily asset、checks、bootstrap/history、job definition、sensor definition、catalog 或任何 lake schema/path。

### 5.2 helper 语义

```python
def discover_gold_stk_mins_qfq_source_year_paths(
    lake_root: Path,
    *,
    freq: int | str,
    trade_dates: Sequence[str],
    stock_codes: Sequence[str] | None = None,
) -> tuple[Path, ...]:
```

固定规则：

1. `stock_codes is None`：保留现有全市场 glob，现有 daily/check/history 调用方不传该参数，行为完全不变。
2. `stock_codes` 为显式非空列表：仍计算每个目标年及其上一年，但只按 `freq/ts_code=<code>/year=<year>/part-000.parquet` 的精确路径收集存在文件，排序并去重。
3. 某代码在上市前没有对应年文件是正常情况，不以“每代码每年都有文件”作为完整性条件；若所有 scoped source path 都不存在，repair op 继续 fail closed。
4. helper 不从 Dagster status 推导代码，不读取 qfq repair metadata，不改变 code 格式；repair op 已有 metadata/hash 一致性校验，仍是唯一 scope 入口。
5. 只有 `gold_stk_mins_qfq_macd_kdj_repair_op(...)` 传 `stock_codes=stock_codes`。daily writer、checks 与 history/bootstrap 继续使用默认全市场 source，禁止被 R5 收窄。

### 5.3 测试门禁

1. 默认调用仍发现同一年全部代码文件，证明 daily/check/history 没有行为回归。
2. 显式 2-code scope 只返回这两个代码在目标年与上一年的存在文件，不返回其它代码。
3. 上市前无文件的代码不导致 helper 失败；所有 scoped 文件缺失时由 repair op 失败。
4. repair op 的 mocked helper 必须断言收到完整且排序后的 `stock_codes`；不得再出现只传 `freq/trade_dates` 的调用。
5. 静态门禁反向检查 daily writer、checks、history/bootstrap 调用点没有传入 repair-only `stock_codes`。

## 6. R5.2 代码实现：repair 全量 state 预检与全频度约束

### 6.1 新增写前门禁

在 repair op 取得 `target_dates`、检查 expected registration、并建立各频度 scoped source/initial previous-state plan 后，在任何 `write_gold_stk_mins_qfq_macd_kdj_rows(...)` 调用前执行：

```text
for freq in STK_MINS_QFQ_FREQS:
  for trade_date in target_dates:
    require existing gold_stk_mins_qfq_macd_kdj_state_path(freq, trade_date)
```

要求：

1. helper 返回完整 missing count、按频度聚合 count、最多 10 个路径样本、首个缺失 `freq/trade_date/path`。
2. 只要缺一份 state，抛 `dg.Failure`，metadata 同时写目标日期数、频度数、缺失摘要与当前 qfq repair `upstream_batch_id/hash`。
3. 失败时 `write_gold_stk_mins_qfq_macd_kdj_rows(...)` 调用次数必须为 0，且 completion check event 必须为 0。
4. first expected date 可不需要“上一日 state”，但 scoped repair 自己仍必须有每个 target state 的完整文件，因为它的语义是合并 affected code 与既有全量 state，不是初始化全量 state。
5. 这项预检只检查 repair 需要 merge 的 state target 是否存在；不以文件存在冒充 readiness，也不替代 daily 资产的 blocking checks。

### 6.2 全七频度约束

op 在任何 source/state 预检前验证：

```text
freqs == STK_MINS_QFQ_FREQS
```

不允许空列表、部分频度、重复频度、额外频度或不同顺序。错误信息必须明确说明：repair completion check 固定覆盖七频度，部分频度会产生虚假的完成状态，所以被拒绝。

`freqs` 字段暂不删除，以避免改变现有 sensor/Launchpad config 形状；它由“可选子集”收紧为“必须传全量或使用默认值”。现有自动 sensor 已显式传入全七频度，行为不变。

### 6.3 剩余原子性风险与恢复边界

当前 writer 是“每个 Parquet 临时写入、校验后 `os.replace`”，不是覆盖 23,568 个 affected 文件的跨文件事务。R5 的 source/state 预检会消除当前已知的晚失败风险，但不能承诺 DuckDB、磁盘或某个既有 indicator 文件绝不会在后续写入中失败。

因此正式 R5 repair 前必须先创建 affected indicator/state 文件的同卷 quarantine 备份和 checksum manifest。备份是运维恢复措施，不进入 op，不自动执行恢复：

1. repair 失败后立即停止，先输出已替换文件清单与 pre/post checksum 差异。
2. 是否从 quarantine 恢复由管理员单独批准；不得在失败 run 内自动反向覆盖 lake 文件。
3. repair 成功并完成最终审计后，quarantine 保留期限和最终删除另行决定。

## 7. 测试、静态门禁与文档对账

### 7.1 必跑测试

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
uv run python -m unittest \
  tests.test_stk_mins_qfq_m12_macd_kdj \
  tests.test_stk_mins_qfq_macd_kdj_repair_op_contracts \
  tests.test_stk_mins_qfq_macd_kdj_repair_sensor_contracts \
  tests.test_stk_mins_qfq_m12_sensor_contracts \
  tests.test_run_contract_static_gates \
  tests.test_stk_mins_continuity_performance \
  tests.test_batch_readiness_hotpath_performance
git diff --check
```

不默认运行 `dg check defs`；如需验证正式 definitions 加载，另行申请审批。

执行结果（2026-07-14）：上述 131 项关联单测、静态门禁和性能门禁全部通过；R5 生产代码与测试的 `ruff check` 通过。测试只使用临时目录和 ephemeral Dagster instance，不读取或写入正式 lake / Dagster instance。

### 7.2 必须新增的负向用例

| 用例 | 必须证明 |
|---|---|
| 28 个 target state 中任意一个缺失 | repair fail before write，writer 和 completion event 均为 0。 |
| `freqs=[1, 5]`、重复、乱序 | fail before source discovery/write，错误说明 completion 语义。 |
| 初始 33-code fixture | repair source helper 只收到该测试 scope；未传 scope 的 daily/check/history 调用保持全市场。 |
| scope/hash 与 qfq repair metadata 不一致 | 保持现有 fail closed，不能因为 source scope 优化而放宽。 |
| 完整 state + 全七频度 | 保持 14 个 completion check、`covered_end_trade_date`、hash 与 upstream batch metadata。 |

### 7.3 文档同步

实现通过后必须同步：

1. 本 R5 LLD：把“待实施”改为实际代码、测试与执行结果。
2. `dagster-stk-mins-continuity-governance-low-level-design.html`：将 M10 的“全量 preflight”限定为已经实现的范围，并记录 R5 补齐 all-target-state gate 的结果。
3. `dagster-stk-mins-qfq-macd-kdj-indicators-plan.md`：补充 scoped source discovery、全频度约束、R5 reconciliation 执行结果与 completion 语义。
4. `dagster-namechange-source-drift-recovery-low-level-design.md`：只更新 R4 到 R5 的交接状态，不把 R5 repair 写成 namechange 恢复的一部分。

## 8. 后续执行分阶段计划

### R5-P0：代码与本地验证（已完成）

已完成范围：第 5、6、7 节列出的 Python、测试和文档；未写正式 lake、Dagster instance 或 prod。实现文件为 source helper、repair op、两个契约测试和静态门禁；正式 daily/check/history 调用保持默认全市场 scope。

停止条件：任一现有 daily/check/history 调用被收窄、正常 sensor config 不满足全频度约束、或测试发现 helper scope 与实际 qfq repair metadata 语义冲突。

### R5-P1：正式执行前只读 preflight（已完成，仍阻断正式执行）

重新输出 `/private/tmp/stk_mins_qfq_macd_kdj_r5_preflight_<timestamp>.json`，至少记录：

1. 当前 qfq repair 的 `trade_date/start/end/codes/count/hash/upstream_batch_id`；与本 LLD 基线不同即停止。
2. 相关四个 job 的 active run、四个相关 sensor 的状态、完整 target range 的 registration。
3. 四个 daily state gap 的当前文件/asset/check 状态。
4. scoped source file/byte/row 规模、indicator/state target 文件数、quarantine 所需字节数、磁盘可用空间。
5. 当前 completion gate 是否仍未覆盖本批次，及已有 completion 的 batch/hash 证据。

执行结果（2026-07-14 16:59:11+08:00）：报告为 [R5-P1 preflight](/private/tmp/stk_mins_qfq_macd_kdj_reconciliation_preflight_20260714T085911Z.json)。当时只审计了 7 月 13 日的 33-code scope、`2014-01-02` 至 `2026-07-13`、3,044 个 expected dates、hash `596cb3d8...933311b`、upstream batch `qfq_factor_repair:2026-07-13:6e5e6183709d`；相关四个 job 均无 active run，全部 target dates 已注册，四个相关 sensor 均为 `RUNNING`。该单批 preflight 在 P3 前已被四批 preflight 取代。

本次 preflight 按 R5-P0 的 scoped source helper 计量：7 个频度合计只读取 2,260 个 affected-code qfq 年文件、517,689,750 bytes、255,998,831 行；不再把全市场 source 扫描作为 repair 输入。正式 repair 前仍有两个阻断：四个日期 `2026-07-08/09/10/13` 在每个频度各缺一份 state，共 28 份；旧 completion 仍属于 2026-07-07 的 32-code batch，不能覆盖当前 batch。当前可备份的 affected indicator/state 文件为 23,540 份、4,978,522,950 bytes；P2 补齐 state 后必须重新 preflight，届时预期为 23,568 份。lake 可用空间为 2,566,700,339,200 bytes，不构成阻断。

### R5-P2：维护窗口与四个 daily state 补洞

建议在同一个维护窗口内先记录并暂停下列当前 `RUNNING` sensor，避免人工 job 与正常触发并发；暂停和恢复只能用 `DagsterInstance` API，按当前 selector 解析：

1. `stock_mins_qfq_daily_sensor`
2. `stock_mins_qfq_factor_repair_sensor`
3. `gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor`
4. `gold_stk_mins_qfq_macd_kdj_repair_job_sensor`

随后严格按以下顺序人工运行既有 job：

```text
gold_stk_mins_qfq_macd_kdj_daily_update_job[2026-07-08]
  -> 14 个 indicator/state materialization 与 blocking checks 全绿
gold_stk_mins_qfq_macd_kdj_daily_update_job[2026-07-09]
  -> 同上
gold_stk_mins_qfq_macd_kdj_daily_update_job[2026-07-10]
  -> 同上
gold_stk_mins_qfq_macd_kdj_daily_update_job[2026-07-13]
  -> 同上
```

每一步都重新确认同日 qfq daily、qfq factor repair、当前目标文件、上一 expected state 与 14 个 blocking checks。任一步失败、已 materialized 但 checks 失败、或发现新 active run，立即停止，不跳到后一天，不自动覆盖。

执行结果（2026-07-14）：四个 sensor 已在维护窗口开始前由 `DagsterInstance` API 暂停，并保持 `STOPPED`。既有 job 严格串行完成：

| 日期 | daily job run id | post-audit |
|---|---|---|
| `2026-07-08` | `6dec541a-dbef-4161-914e-b0f9bef3ddd3` | [报告](/private/tmp/stk_mins_qfq_macd_kdj_r5_p2_post_audit_2026-07-08_20260714T102735Z.json) 通过 |
| `2026-07-09` | `7ccb8146-55c6-46e4-8e32-8649d1872ff7` | [报告](/private/tmp/stk_mins_qfq_macd_kdj_r5_p2_post_audit_2026-07-09_20260714T114415Z.json) 通过 |
| `2026-07-10` | `145e45c3-d7e5-4234-9bde-ad17e2b8c1fb` | [报告](/private/tmp/stk_mins_qfq_macd_kdj_r5_p2_post_audit_2026-07-10_20260714T115623Z.json) 通过 |
| `2026-07-13` | `a1adce0c-fe1f-4cc8-bc54-79ced2eb8e80` | [报告](/private/tmp/stk_mins_qfq_macd_kdj_r5_p2_post_audit_2026-07-13_20260714T120710Z.json) 通过 |

每份 post-audit 都确认同日 14 个 indicator/state asset 已 materialize 且 blocking checks 通过、七份 state 文件存在、相关 job 无 active run。汇总 [R5-P2 preflight](/private/tmp/stk_mins_qfq_macd_kdj_reconciliation_preflight_20260714T120822Z.json) 随后确认：3,044 个目标交易日乘七个频度的 21,308 份 state 文件均存在，原有 28 个 state 缺口已归零；实时 repair scope 仍为 33 个代码、hash `596cb3d8...933311b`、upstream batch `qfq_factor_repair:2026-07-13:6e5e6183709d`，与 R5 基线一致；四个相关 job 均无 active run。P2 未写 prod 数据库、未修改 dynamic partitions，且未启动 repair job。

### R5-P3：quarantine 备份与四批 scoped repair（已完成）

在四个 daily gap 都绿后：

1. 重新运行 multi-batch preflight，确认四个 qfq factor repair status 均完整、四批 code scope 两两无重叠、所有 state target 已存在、相关 sensor 均为 `STOPPED`，且不存在 active repair run。
2. 用生产 QFQ 公式比较 helper 做只读 source gate。最近受影响日期的所有 253 个公式差异代码都必须落在其对应的、已成功 factor-repair scope 内；发现任一未覆盖代码即停止。
3. 将四批的 affected indicator/state 文件并集复制到同卷 quarantine，生成相对路径、字节数、SHA-256 manifest；备份完成后才启动 repair。
4. 每一批都实时读取自己的 `start_trade_date/stock_codes/hash/upstream_batch_id`，用全七频度 config 启动既有 `gold_stk_mins_qfq_macd_kdj_repair_job`；必须严格串行，单批 post-audit 通过才进入下一批。
5. 任一 batch 失败即停止，不自动恢复；是否按 manifest 回滚仍由管理员另行批准。

执行结果（2026-07-14）：

| qfq factor repair 日 | 代码数 | repair run id | 运行结果 |
|---|---:|---|---|
| `2026-07-08` | 60 | `d06290f4-3f0b-44d9-a9ce-307d4b8dd676` | 成功；14 条 completion 历史事件与 batch metadata 一致 |
| `2026-07-09` | 58 | `9ac6079c-3dc2-442b-9a7b-015faf40fc29` | 成功；14 条 completion 历史事件与 batch metadata 一致 |
| `2026-07-10` | 102 | `81595590-c0a0-406d-a845-543218f370c2` | 成功；14 条 completion 历史事件与 batch metadata 一致 |
| `2026-07-13` | 33 | `9d967323-524a-4241-9d01-628f2e74672c` | 成功；14 条 completion 历史事件与 batch metadata 一致 |

source gate 报告为 [source gate](/private/tmp/stk_mins_qfq_macd_kdj_repair_source_gate_20260714T125731Z.json)，确认 253 个 scoped 差异代码都被其精确 factor-repair 批次覆盖。quarantine 位于 `/Volumes/datasource/data_lake/_quarantine/stk_mins_qfq_macd_kdj_r5_multi_20260714T130322Z/`，manifest 包含 38,819 个文件、13,476,511,817 bytes。最终审计为 [final audit](/private/tmp/stk_mins_qfq_macd_kdj_multi_batch_repair_final_audit_20260714T142623Z.json)：四批 run config 均仍匹配实时 source metadata，当前目标文件均存在且非空，且无 active repair run。

### R5-P4：最终审计与恢复日常（审计完成；sensor 恢复待复核）

输出 `/private/tmp/stk_mins_qfq_macd_kdj_r5_final_audit_<timestamp>.json`，必须证明：

1. 四批的 run config 必须逐项匹配其 source metadata；每批历史 run 都必须存在恰好 14 条 passed/blocking completion event，且 event metadata 的 trade date、start/end、code count/hash、upstream batch 必须精确一致。
2. 不能把四批都要求为当前 latest completion ready：它们共享 `repair_start_trade_date=2014-01-02`，后写 batch 的最新 check 会覆盖先前 batch 的最新 check。前 3 批以历史 run events 为证据，最后一批以 latest completion 为证据。
3. quarantine manifest 的 38,819 个当前目标文件均必须存在且非空；不存在 active qfq/MACD-KDJ repair job；未修改 prod 数据库、动态分区或不相关 lake 文件。
4. 已完成最终审计，但四个 sensor 继续保持 `STOPPED`。恢复前必须先单独审计 completion latest-state 碰撞对未来 sensor gate 的实际影响，不能因为本轮物理数据已正确就默认恢复。

### R5-P5：completion latest-state 碰撞（P5A/P5B 已完成）

completion check 的 Dagster identity 是 `asset key + check name + partition`。四个 repair 批次都从 `2014-01-02` 开始，旧实现把该开始日期当作 check partition，因此同一 14 个 asset/check 的 latest 视图只会留下最后写入的 `2026-07-13` 批次。物理数据和四个历史 repair run 都正确，错误只在 completion 状态的身份设计。

P5 将正式身份改为 QFQ factor repair 的触发交易日：

```text
asset key + gold_stk_mins_qfq_macd_kdj_repair_completed_check
+ qfq_factor_repair_trade_date
```

`repair_start_trade_date` 与 `repair_end_trade_date` 仍是 repair 覆盖范围，继续写入并校验 metadata；它们不再用于查询 Dagster latest completion check。`gold_stk_mins_qfq_macd_kdj_repair_completion_status_for_upstream_batch(...)` 现在显式接收 `qfq_factor_repair_trade_date`。日常 MACD/KDJ gate 和 repair sensor 都把上游 QFQ status 的 `trade_date` 原样传入。

repair op 仍为 14 个既有 asset 写 14 条 blocking completion check，未新增 asset、check、job、sensor、动态分区或日常 event 数量；唯一变化是 event partition 从 `start_trade_date` 改为 `qfq_factor_repair_trade_date`。同一触发日出现新的 upstream batch 时，`source_upstream_batch_id`、代码 hash、范围或频度 metadata 不匹配，gate 必须 fail-closed 并要求重新 repair，不能把旧完成状态误认为新 batch 已完成。

#### P5A 代码与只读计划

新增非 active bootstrap 模块和 CLI：

```text
src/orchestrator/defs/bootstrap/stk_mins_qfq_macd_kdj_repair_completion_events.py
src/orchestrator/defs/bootstrap/stk_mins_qfq_macd_kdj_repair_completion_events_cli.py
```

它只允许本次冻结的四个 QFQ 触发日：`2026-07-08`、`2026-07-09`、`2026-07-10`、`2026-07-13`。先执行 `plan-events`，只读扫描每个日期的 QFQ status、QFQ producer run、旧 completion history 和目标 trigger-date partition；随后才可使用带 `--apply` 的 `report-events`。`--apply` 必须同时提供刚生成的 plan report，CLI 会核对 plan fingerprint，防止 preflight 与写入之间上游状态已经变化。

每一批只有在以下条件全部满足时才可计划 14 条 runless `AssetCheckEvaluation`：

1. 当前 QFQ repair status ready、实际 rewrote history，且 producer run 为 `SUCCESS`。
2. 旧 `2014-01-02` completion history 中，每个既有 MACD/KDJ indicator/state asset 都恰有一条 passed/blocking event；14 条 event 的触发日、覆盖范围、代码数/hash、upstream batch、全频度 metadata 全部与该 QFQ batch 一致，并来自同一个成功 repair run。
3. 新的 trigger-date partition 没有 completion event；若已存在，必须 metadata 完全一致才跳过，任何冲突都停止。

四批最多写入 `4 x 14 = 56` 条 runless check event。补录只复制已验证的正式 completion metadata，并额外记录 bootstrap 方法、源 completion storage id 和源 repair run id；不补 materialization、不附目标 materialization、不重跑 repair、不改原 event、不写 lake、prod 或动态分区，也不直接 SQL 修改 Dagster DB。写后会重新 plan，只有计划事件数归零且无 stop reason 才算收敛；中途部分写入可由同一 plan 安全续跑，未补全批次继续 fail-closed。

P5A 已完成代码、单元测试和正式 instance 的只读 preflight。2026-07-14 的 [plan report](/private/tmp/stk_mins_qfq_macd_kdj_repair_completion_events_plan-events_20260714_225551.json) 与 [dry-run report](/private/tmp/stk_mins_qfq_macd_kdj_repair_completion_events_report-events_20260714_225734.json) 一致：4 批、56 条 source completion event、0 条目标 trigger-date event、计划补 56 条、`should_stop=false`，冻结 fingerprint 为 `f1e3771014ed8570f908a24a7af471710678b4f67dd72db180136b91350e1f4e`。

P5B 已于 2026-07-14 执行。apply 使用同轮 [fresh plan report](/private/tmp/stk_mins_qfq_macd_kdj_repair_completion_events_plan-events_20260714_230729.json)，写入恰好 56 条 runless completion check event，报告为 [apply report](/private/tmp/stk_mins_qfq_macd_kdj_repair_completion_events_report-events_20260714_230913.json)。CLI 的 post-apply plan 为：`existing_target_event_count=56`、`planned_event_count=0`、`should_stop=false`。独立 [post-audit](/private/tmp/stk_mins_qfq_macd_kdj_p5b_completion_events_post_audit_20260714T151024Z.json) 进一步确认四个触发日各有 14 条 passed/blocking completion check，代码数为 `60/58/102/33`，覆盖范围均为 `2014-01-02` 至各自触发日，七频度齐全，且四个 upstream batch 均精确匹配。旧 `2014-01-02` source completion evidence 仍完整可读；四个相关 sensor 仍为 `STOPPED`，四个相关 job 无 active run。

## 9. 审批点与停止条件

### 9.1 后续需要管理员明确批准的动作

1. R5-P6A 的只读运行链路验收：确认四批 completion gate 均独立 ready，并审计当前交易日 qfq、factor repair、MACD/KDJ 的上游 readiness 与 sensor 选择日期。该步骤不启用 sensor、不发 run。
2. R5-P6B 的四个 sensor 恢复；仅在 P6A 全绿后单独批准。恢复后只观察自然触发，不人工补发历史 run。
3. quarantine 的保留期限与最终删除；当前不得自动删除。

### 9.2 必须停止的情况

1. R5-P1 发现 qfq repair scope、hash、upstream batch 或 expected range 已变化。
2. 任何四个 daily gap 仍缺完整 14 asset/check readiness，或 target state 文件未全部存在。
3. source scope 超出当前 qfq repair code list，或发现 helper 默认全市场行为被影响。
4. 存在 qfq/MACD-KDJ 相关 active run，或维护窗口中出现新的并发 run。
5. quarantine manifest 行数、字节数或 hash 与 preflight 不一致。
6. scoped repair 成功但任一历史 completion event 的 batch/hash/full freqs 不匹配，或 final audit 发现异常代码/文件。

## 10. 影响面审计结论

CodeGraph 已审计 `discover_gold_stk_mins_qfq_source_year_paths` 的 10 个直接调用方和 25 个受影响符号：daily asset writer、五类 checks、history plan/generator/audit/count、repair op 及对应 tests。R5 的共享 contract 修改只允许 repair op 使用新可选 scope，其他调用方保持 `stock_codes=None` 的全市场语义。

R5 不触及 `src/` 业务子系统边界，也不新增跨子系统依赖；改动范围限定在 `lake_console/orchestrator` 的既有 qfq MACD/KDJ helper、repair op、测试和设计文档。
