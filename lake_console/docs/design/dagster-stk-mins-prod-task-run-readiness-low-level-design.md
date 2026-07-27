# Dagster 股票分钟线 Prod TaskRun 完成门禁 LLD

**状态：R2 raw 受控替换已完成；R3 在 silver 覆盖能力缺失处停止；R3A Silver 受控替换代码与本地验证完成，待正式只读 plan / 维护窗口审批**
**日期：2026-07-28**
**范围：`stock_mins_raw_update_from_prod_job` 的 prod 完成门禁与 2026-07-27 受控重建**

## 1. 要解决的问题

股票分钟线的 prod 同步和 DG Lake 同步是两套独立运行链路。此前 DG 只等待本地交易日和 `stock_basic` 就绪，便直接从 `raw_tushare.stk_mins` 导出；如果 prod 仍在逐股票、逐频度写入，DG 会读到一个中间版本。

这不是 Lake 文件格式问题，而是触发依据错误：**“prod 表里已经有一些数据”不能代表“prod 当天分钟线任务已结束”。**

本方案将 prod 运营后台的全市场任务终态作为第一道完成依据，再以 prod 原始分钟表对 DG 当天股票集合的五频度代码覆盖作为第二道完成依据。两者都满足才允许 DG 导出；TaskRun 的 `success` 不再被误当成单独的完整性证明。

DG 不新增完成表、视图、asset、check、job、sensor、动态分区或环境变量。第二道门直接读取已有 `raw_tushare.stk_mins` 的最小代码身份集合，不扫描 OHLC、成交量或完整分钟行。

## 2. 已核实事实

### 2.1 prod 的完成记录

prod 使用 `ops.task_run` 记录运营任务。相关字段包括：

- 身份：`id`、`task_type`、`resource_key`、`action`；
- 目标范围：`time_input_json`、`filters_json`、`plan_snapshot_json`；
- 终态：`status`、`status_reason_code`、`ended_at`；
- 完成度：`unit_total`、`unit_done`、`unit_failed`、`progress_percent`；
- 结果计数：`rows_fetched`、`rows_saved`、`rows_rejected`。

`stk_mins` 的 prod planner 按“目标股票代码 × 选择的分钟频度”生成 unit。因此完整日常任务会留下五频度、全市场范围的计划与完成计数。

### 2.2 当前 DG 缺口

1. `stock_mins_raw_sensor` 目前只检查本地交易日、raw 连续性与 `stock_basic` readiness；没有读取 prod 的任务完成状态。
2. sensor 当前最短评估间隔为 600 秒，日常窗口从 19:30 开始。
3. prod raw writer 仅统计 `empty_stock_code_count`，当前不会因缺股票代码而拒绝写入。
4. 正常 raw job 的 `write_mode` 为 `reuse_existing`。因此已写入的半成品不会因后续普通重试自动覆盖。
5. 2026-07-27 证明 TaskRun `success` 不可单独作为完整性证明：全市场 TaskRun `6544` 在 `20:51:33+08` 以 `29,355 / 29,355` unit、零 reject 成功结束；随后 `6578` 在 `23:34:34+08` 对 `688825.SH`、`920176.BJ` 做五频度补跑，新增恰好 642 个不重复分钟键。最终 prod 原始表才达到完整状态。

### 2.3 本次明确授权的边界

用户已明确授权本专项直接只读 `ops.task_run`。这是一条窄例外，不泛化到 `ops.schedule`、`ops.task_run_node`、`ops.task_run_issue`、状态快照、scheduler 或 worker。为实现第二道代码覆盖门，现有已批准的 `prod-raw-db` 白名单读取 `raw_tushare.stk_mins` 仅限 `freq`、`ts_code` 和 `trade_time` 身份字段；不得读取 OHLC、成交额或 payload 作为 readiness 依据。

实现时同步把这一例外写入 `lake_console/AGENTS.md` 的远程只读白名单：只允许 `ProdPostgresResource.connect_readonly_transaction()` 对 `ops.task_run` 做显式字段投影和精确条件查询；代码覆盖查询只允许读取 `raw_tushare.stk_mins` 的 `freq`、`ts_code`、`trade_time`。不得使用 `SELECT *`，不得写 prod，不得读取其它 `ops.*` 表。

## 3. 完成门禁口径

### 3.1 合格的 prod `stk_mins` TaskRun

对目标交易日 `D`，候选记录必须同时满足：

```text
task_type = 'dataset_action'
resource_key = 'stk_mins'
action = 'maintain'
status = 'success'
ended_at IS NOT NULL
time_input_json 的 trade_date = D
filters_json 指向五频度：1min, 5min, 15min, 30min, 60min
filters_json 未将 ts_code 缩小为人工子集
unit_total > 0
unit_done = unit_total
unit_failed = 0
progress_percent = 100
rows_fetched > 0
rows_saved > 0
rows_rejected = 0
```

候选按 `ended_at DESC, id DESC` 排序。若有多条满足条件的同日全市场任务，选择最新的一条；run ID 与终态摘要作为本次 DG 导出的第一道来源依据。后续代码子集补跑不替代该全市场候选，但它们写入 prod 原始表后的事实会由第 3.2 节重新核对。

`time_input_json`、`filters_json`、`plan_snapshot_json` 是身份判定输入，不直接写入 sensor cursor、run config 或 Lake metadata。只有经规范化后的频度集合、是否全市场、task run ID、结束时间、预期代码数/hash 与小型 fingerprint 可以留存。

### 3.2 prod 原始分钟代码覆盖

全市场 TaskRun 合格后，DG 从同日 `silver_stock_basic` 按既有 raw writer 的口径得到预期股票集合，并对 prod `raw_tushare.stk_mins` 做一个有界的五频度身份查询：

```text
时间范围：D 09:00:00 <= trade_time < D 19:00:00
频度：1 / 5 / 15 / 30 / 60
字段：freq、ts_code、trade_time
判定：每个频度都覆盖全部预期 ts_code；每个频度无重复 (ts_code, trade_time)
```

这不是对分钟值的重新计算，也不是全表状态扫描。查询只比较 DG 将要导出的代码集合和分钟键身份：缺任意预期代码、重复键、日期/频度不符、查询异常都视为 prod 尚未完整。prod 中不属于 DG 当前集合的额外代码不阻断，因为 DG 不会导出它们。

只有第 3.1 节与本节同时通过，才产生 `ProdStkMinsCompletionReference`。reference 记录全市场 TaskRun ID、结束时间、预期代码 count/hash、各频度覆盖计数与观察时间；不记录完整代码列表、TaskRun JSON 或分钟键列表。

### 3.3 不合格状态

以下任一情况都视为 prod 未完成，DG 必须 fail closed：

- 找不到目标日匹配 TaskRun；
- `queued`、`running`、`canceling`、`failed`、`canceled`、`partial_success` 或任何非 `success` 状态；
- 成功记录是单频度或代码子集任务；
- 计划/完成单元不闭合、进度不是 100%、存在失败单元、拒绝行或零行结果；
- 任务 JSON 结构无法解析，或无法确认日期、五频度和全市场身份；
- 只读 prod 查询超时或异常。

失败不是 raw job 失败：sensor 不提交 run、不写 Lake。cursor 只写目标日、`blocked_component=prod_ops_task_run`、reason code、候选状态/ID（若有）以及有限计数与下一步动作。

## 4. 运行行为

### 4.1 日常当天

```text
19:30 前
  -> 不读 ops.task_run，不提交 run。

19:30 至 24:00 前
  -> 每次 sensor tick 先读取目标日 ops.task_run。
  -> 无合格全市场任务：skip；15 分钟后继续判断。
  -> 有合格全市场任务：读取一次 prod raw 五频度代码覆盖。
  -> 覆盖不完整：skip；15 分钟后继续判断。
  -> 两道门都通过：提交一次 raw 五频度 job。

24:00 后
  -> 当天仍无合格 TaskRun 或代码覆盖不完整：停止当天自动提交；保持该日期为 not-ready，
     cursor 写 prod_task_run_cutoff_reached 或 prod_source_code_coverage_incomplete，
     等待人工发起受控历史修复。
```

sensor 的 `minimum_interval_seconds` 改为 `900`。这是最短间隔，不是精确 cron；daemon 忙时允许实际间隔大于 15 分钟。

历史缺口不借用当天的自动窗口：若一个过去交易日在 24:00 截止时仍无合格 prod TaskRun，日常 sensor 不得在后续日期静默自动补跑。它会继续阻断连续性，必须通过明确的历史 `replace_from_prod` 修复入口处理。

### 4.2 job 与 asset 的二次防线

sensor gate 不能成为唯一防线，因为 Launchpad 或手工 job 可以绕过 sensor。

1. sensor 提交 run 时，在五个 raw asset 的 config 中传递同一个最小 `prod_completion_reference`：`task_run_id`、`trade_date`、`ended_at`、频度集合 hash、全市场标记、预期代码 count/hash、覆盖观察时间与摘要 fingerprint。
2. 每个 raw asset 写入前，只读按 `id` 查询同一 `ops.task_run`，并只对自身频度重做第 3.2 节的代码覆盖复核；任一复核不合格即 fail，不写目标文件。
3. 运行 config 缺少 completion reference 时，`source=prod_db` 的 full-day raw 写入 fail closed。Tushare merge repair 不受这一配置约束。
4. 不新增运行时完成状态；`ops.task_run` 是 prod 事实，Dagster materialization/check 仍是 Lake 事实。

## 5. Lake 写入与半成品防护

### 5.1 后续日常写入

prod TaskRun 合格后，writer 仍用既有 staging -> 校验 -> `os.replace` 写入正式 Parquet。额外要求：

- `returned_stock_code_count` 必须等于由当日 `silver_stock_basic` 推导的请求代码数；
- 否则在 promote 前失败，删除临时文件，不写正式文件；
- 不把 `empty_stock_code_count > 0` 当作可接受的 materialization；
- 正常新分区仍使用 `reuse_existing`，但该模式只能复用已通过完整代码覆盖验证的既有文件。

这不会增加 check 数或 Dagster event 数；它是 raw writer 对“不能将部分 prod 结果固化成 Lake 文件”的写前事实保护。

### 5.2 已存在半成品的恢复

`reuse_existing` 不适合修复已写入的半成品。此次恢复**不**给现有 raw job 增加 `replace_from_prod` write mode：五个 raw asset 是五个独立 step，单靠 job config 不能提供跨频度的整体回滚边界。

因此新增一个**非 active 的离线 recovery CLI**：`stk_mins_raw_replace_from_prod`。它只接受一个明确的历史交易日，且不注册 asset、check、job、sensor 或 Dagster event。

1. `plan` 只读核验 `ops.task_run` 的全市场五频度成功证据、DG 当前股票集合、prod 五频度代码覆盖与现有五个 raw 文件指纹，输出 `/private/tmp` JSON 及 fingerprint；
2. `apply` 必须同时提供该新鲜 plan 和显式 `--apply`；先将五个频度完整导出到同卷 staging；
3. 每个 staging 文件必须通过 schema、交易日、频度、空键、重复分钟键、代码 count/hash、行数和 `09:30–15:00` 时间范围验证；
4. 五个 staging 全绿后，才把五个原文件整体移到同卷 quarantine 并生成 manifest，再逐个 `os.replace` promote；
5. 任一 backup/promote 异常必须恢复所有已移动的原文件；成功后的 quarantine 保留，物理删除另行审批；
6. 现有 `stock_mins_raw_update_from_prod_job` 在 recovery 成功后仍只使用普通 `reuse_existing` 路径，重新记录五个 raw materialization 并执行既有结构性 checks；它不承担文件替换责任。

该 CLI 是本次历史事故的受控恢复入口，日常 sensor 永不自动调用它。未来日常 TaskRun + prod 覆盖双门禁仍按第 4 节、5.1 节和下文“后续日常开发”单独实现，不能借这次恢复 CLI 混入 active definitions。

## 6. 代码级改动点

### 6.1 R1：2026-07-27 离线恢复工具

| 文件 | 改动 |
|---|---|
| `defs/bootstrap/stk_mins_raw_replace_from_prod.py` | 新增非 active 的单日五频度 plan/apply。只读使用 `ProdPostgresResource`、`ops.task_run` 与 `raw_tushare.stk_mins`；apply 使用 DuckDB set-based staging、同卷 quarantine、manifest 和整体回滚；不报告 Dagster event。 |
| `defs/bootstrap/stk_mins_raw_replace_from_prod_cli.py` | 新增 `plan` / `apply` CLI。`apply` 同时要求 `--apply` 与已审阅的 plan report；所有报告默认写 `/private/tmp`。 |
| `tests/test_stk_mins_raw_replace_from_prod.py` | 临时 Lake fixture 覆盖缺频度、hash/重复键、staging 失败、promote 回滚、stale/repeated apply 和 plan 零 Lake 写入。 |
| 本 LLD | 将历史修复从活跃 raw job 的 write mode 纠正为离线 recovery CLI，并记录它与 R2/R3 的责任边界。 |

R1 不修改 `assets/stk_mins.py`、`run_contracts/configs.py`、job、sensor、asset/check 名称或 Definitions。

### 6.2 后续日常完成门禁（本轮不实施）

| 文件 | 改动 |
|---|---|
| `defs/prod_db/stk_mins_task_run.py` | 新增只读 TaskRun SQL builder、投影行模型、JSON 解析与 `ProdStkMinsTaskRunStatus`。只访问 `ops.task_run`。 |
| `defs/prod_db/stk_mins.py` | 在既有 prod raw source contract 内新增有界代码覆盖 SQL/read model；只投影 `freq`、`ts_code`、`trade_time`，按给定日期和 DG 代码集合判定五频度覆盖与重复键。 |
| `defs/run_contracts/stk_mins.py` | 定义五频度集合、19:30 起始、24:00 截止、900 秒间隔，以及 completion reference 的规范化/hash。 |
| `defs/run_contracts/configs.py` | 扩展 raw config schema 与 builder，传最小 `prod_completion_reference`；不承载 2026-07-27 历史 replace。 |
| `defs/sensors/stock_mins_raw_sensor.py` | 在 `stock_basic` gate 后读取 TaskRun 完成状态；合格才构造 RunRequest；cursor 加入紧凑 prod status；15 分钟间隔与截止语义。 |
| `defs/assets/stk_mins.py` | prod full-day 写入前复核 completion reference；把空代码从 metadata 变成写入失败。历史五频度 replace 由 R1 离线 CLI 独占。 |
| `defs/resources.py` | 不新增 resource；复用 `ProdPostgresResource.connect_readonly_transaction()`。 |
| `lake_console/AGENTS.md` | 记录本专项唯一的 `ops.task_run` 只读白名单与字段/用途限制。 |
| 现有分钟线 LLD 与本文件 | 同步完成门禁、半成品恢复和运维边界；不改旧事件历史。 |

## 7. 性能预算

| 路径 | 单次读取/写入 | 上限与拒绝策略 |
|---|---|---|
| raw sensor，19:30 前 | 不读 prod；仅保留既有轻量窗口判断 | 0 条 prod SQL。 |
| raw sensor，未出现全市场成功任务 | 1 条 `ops.task_run` 有界查询，最多 20 条候选；既有 10 日 Lake batch readiness | 不读分钟源表，不读取 task node/issue/history。查询异常立即 skip。 |
| raw sensor，已出现全市场成功任务 | 上述 TaskRun 查询 + 1 条五频度代码覆盖查询 | 只扫描 DG 预期代码对应的 `freq/ts_code/trade_time` 身份字段；缺代码/重复键立即 skip。 |
| 同日等待 | 最多约 18 次（19:30 至 23:45） | 仅在已有全市场成功 TaskRun 后才重复代码覆盖查询；15 分钟最短间隔。 |
| raw job | 5 次按 TaskRun ID 的主键读取 + 5 次单频度代码覆盖复核 + 既有五频度导出 | TaskRun 不合格或代码覆盖不闭合即不 promote。 |
| R1 历史 recovery plan | 1 次本地 `silver_stock_basic` code scan、最多 20 条 `ops.task_run` 候选、1 次五频度聚合身份查询、5 个现有 raw 文件 SHA-256 | 只读；任一 TaskRun、coverage、时间范围、target 文件异常即 stop。 |
| R1 历史 recovery apply | 5 个 prod 全量导出、5 个 staging Parquet、5 个旧 raw quarantine、5 次 promote | 已冻结规模为 1,776,093 行、约 5 个单日文件；DuckDB `COPY` 写入，无 Python 行循环。任一 staging 或 promote 异常完整回滚已移动原文件。 |

正式开发前必须用 fake prod cursor 的测试和一次经批准的只读 `EXPLAIN`/限量查询验证：TaskRun 过滤可命中 `resource_key, requested_at` 索引；全市场成功后的代码覆盖查询仅处理五频度与 DG 预期代码集合，稳定 tick 总预算小于 5 秒。达不到即停止，先优化已有表索引或查询形状；不得退回“TaskRun 成功即完整”的错误口径。

## 8. 测试与静态门禁

### 8.1 单元测试

- 合格全市场五频度成功 TaskRun 可触发 run；
- running、failed、partial_success、缺结束时间、拒绝行、未完成单元、非 100% 进度、零行均 skip；
- 单频度、代码子集、日期不匹配、JSON 异常均 skip；
- 全市场成功但 prod 缺预期代码、重复分钟键或代码覆盖查询异常均 skip；后续代码子集补跑使覆盖闭合后才可触发；
- 19:30 前不查询 prod；19:30 后每 tick 查询一次；24:00 后不再提交 run；
- cursor 包含简短中文 summary / next_action / reason code，不包含完整 JSON、代码列表或 SQL；
- asset 的 reference 缺失/变化/失效均 fail closed；
- prod 返回少代码或 asset 二次覆盖复核失败时不 promote；
- R1 CLI 的 plan 零 Lake 写入、缺频度、hash 不符、重复键、staging 失败、五频度中途 promote 失败回滚、stale/repeated apply；
- 普通 `reuse_existing` 不承担历史五频度替换；recovery CLI 不注册 active Dagster definition，也不报告 runless event。

### 8.2 静态门禁

- 生产 source probe 只允许 `ops.task_run` 与 `raw_tushare.stk_mins` 的最小身份字段，禁止 `ops.task_run_node`、`ops.schedule`、`ops.*` 通配访问；
- 禁止 `SELECT *`、禁止以 OHLC/成交量/全量分钟行扫描判断 prod ready；
- 禁止 sensor 写 Lake、发起历史 replace 或绕过 completion reference；
- 禁止 active raw job/run config 取得历史 recovery replace 的兼容分支；
- 禁止 cursor 写 TaskRun JSON、完整 filters、完整 plan snapshot 或代码全集；
- 禁止 normal `reuse_existing` 把 `empty_stock_code_count > 0` 当成功。

## 9. 2026-07-27 已冻结的受控修复范围

### 9.1 只读审计结果

审计报告：`/private/tmp/stk_mins_20260727_lineage_audit.json`。

prod `raw_tushare.stk_mins` 当天五频度均已完整：每个频度均为 **5,533 个代码**、时间范围 `09:30` 至 `15:00`。本地 Lake 与下游是在 prod 尚未完成时生成的中间版本，当前内容事实如下：

| 层 | 频度 | 当前代码数 | 与 prod 差额 | 结论 |
|---|---:|---:|---:|---|
| raw | 1m / 5m / 15m / 30m / 60m | 3,966 / 3,978 / 3,965 / 3,978 / 3,983 | 1,567 / 1,555 / 1,568 / 1,555 / 1,550 | 五个文件均为半成品，必须整体 replace。 |
| silver | 1m / 5m / 15m / 30m / 60m | 3,959 / 3,971 / 3,958 / 3,971 / 3,976 | 不能以 prod 代码数直接判定；但全部从上述半成品 raw 生成，必须重建。 |
| gold QFQ | 1/5/15/30/60/90/120m | 与对应旧 silver/QFQ 输入一致 | 已继承半成品 | 必须在 silver 后依赖顺序重建。 |
| MACD/KDJ 与 state | 7 个频度各一套 | 指标逐日数据继承旧 QFQ；state 文件虽含 5,543 个历史状态代码，但没有用当天缺失行情推进 | 已继承半成品 | daily 与同日 repair 都必须重跑，不能只补 indicator 文件。 |
| 财富成交额 | 5 行、代码数 3,958 至 3,976 | 每频度仅约 1.464 至 1.473 万亿元 | 相比 prod 当日约 2.086 至 2.088 万亿元显著偏低 | Lake gold 与已同步 prod serving 均为旧值，必须最后重建并同步。 |

Dagster 在错误数据上仍记录了成功 materialization 与 passed checks：raw `19:32`、silver `20:02`、财富 `20:11`、QFQ `20:13-20:16`、QFQ factor repair `20:41`、MACD/KDJ daily `20:43-20:50`、MACD/KDJ repair `20:50`。这些状态只证明旧文件通过了当时的结构/覆盖规则，**不能证明它们完整**；重建后会由新 materialization 与既有 checks 取代当前事实。

本次受影响的直接数据资产共 33 个：5 raw、5 silver、7 QFQ、7 MACD/KDJ indicator、7 MACD/KDJ state、1 wealth gold、1 prod serving。代码审计未发现其它资产直接消费 `silver_stk_mins`；本次不扩展到无直接依赖的资产族。

### 9.2 修复顺序

```text
P0  冻结全市场 TaskRun `6544`（2026-07-27 20:51:33+08）与最终 prod raw 覆盖。
    该 TaskRun 是五频度、非代码子集、29,355/29,355 unit、零 reject 的第一道门；
    后续两代码 TaskRun `6578` 只作为 prod 最终数据补齐证据。五频度最终均为
    5,533 个代码、09:30 至 15:00，且两代码 642 个分钟键无重复。两道门任一不通过即停止。
P1  使用 R1 非 active recovery CLI 对五个既有 raw 文件建立 quarantine manifest；五个 staging
    同时通过代码覆盖、schema、时间、唯一键后才整体 promote。此步不写 Dagster event。
P2  运行 raw job 自带的既有 blocking checks；任何一个失败均不进入 silver。
P3  重建五个 silver_stk_mins 分区并验证既有四类 checks。
P4  运行 stock_mins_qfq_daily_update_job：先五个 native，再两个 derived QFQ；通过既有 checks。
P5  运行同日 stock_mins_qfq_factor_repair_job，完成对 QFQ 上游 batch 的 repair 状态确认。
P6  运行 gold_stk_mins_qfq_macd_kdj_daily_update_job，再运行同日
    gold_stk_mins_qfq_macd_kdj_repair_job；每一频度的 indicator 和 state 必须成对完成。
P7  在所有五频度 silver ready 后运行 gold_wealth_market_turnover_update_job；同一个 job 在
    gold integrity check 通过后同步 prod_core_wealth_market_turnover。
P8  只读最终审计：五频度 source/Lake code coverage、checks、Dagster materialization、
    wealth 五频度 `security_count` 与成交额，以及 prod serving read-back。
```

每一个 P 阶段都是独立生产写入审批；本 LLD 不授权任何 run、Lake 覆盖、runless event、prod 写入、sensor 启停或动态分区改动。

### 9.3 2026-07-28 执行记录与停止点

本次执行已获得单独维护窗口批准，且没有重复运行全量 R0 审计。执行事实如下：

1. 维护开始时，6 个相关 sensor 为 `RUNNING`，`stock_mins_qfq_daily_update_job_sensor`
   按当前 Definitions 的 `default_status=STOPPED` 且无 instance state；7 个相关 job 无 active run。
   维护期间只暂停前述 6 个，停止点触发后已全部恢复，QFQ daily sensor 保持原有停止状态。
2. recovery CLI 的首份 plan 暴露实现偏差：TaskRun `6544` 的 `unit_total=29,355` 是
   prod 全市场 planner 的执行单元数，不等于 DG 当前 5,533 代码乘五频度。LLD 第 3.1 节
   原口径正确，工具已改为只验证 unit 正数、完成闭合、五频度全市场身份和零 reject；DG
   当前集合是否齐备仍由第 3.2 节的独立 prod 覆盖门验证。
3. 修正后 plan 报告
   `/private/tmp/stk_mins_20260727_r2_plan_20260728_011430.json` 全绿：五频度均为
   5,533 代码、MD5 `e7fc1641425bd1bae5980d1e3639e02a`、零空键/重复键、时间范围
   `09:30` 至 `15:00`；TaskRun `6544` 为 `29,355/29,355`、零 reject。
4. raw apply 成功整体 promote 五个频度，耗时 `109,973ms`。旧文件 quarantine manifest 为
   `/Volumes/datasource/data_lake/_quarantine/stk_mins_raw_replace_from_prod/trade_date=2026-07-27/recovery_run_id=f573265f-1162-4535-9089-c486f7b7dac1/manifest.json`。
   随后 `stock_mins_raw_update_from_prod_job[2026-07-27]` 成功完成（run
   `ae26c9f7-cb37-40be-9596-39eed38df343`），仅以 `reuse_existing` 重新记录 raw 事实并运行既有 checks。
5. `stock_mins_silver_update_job[2026-07-27]`（run
   `d76288be-4d96-4bf7-a2d7-45f9a5be8500`）在五个 asset 写入前全部因
   `FileExistsError` 停止：当前 `write_silver_stk_mins_partition(...)` 明确禁止覆盖既有
   `silver/quote/stk_mins/**/part-000.parquet`。没有 silver 文件被改写，未运行 QFQ、factor
   repair、MACD/KDJ 或财富 turnover。

因此，继续 R3 前必须先在本 LLD 中补充并经批准一个与 raw recovery 同级的 **非 active
silver 五频度受控 replace**：五个 staging 全部校验后，整体 quarantine/promote，失败时恢复；
不能通过删除既有 silver 文件、修改日常 job 为强制覆盖或跳过备份来绕过现有防护。具体待确认
方案见第 9.4 节。

### 9.4 R3A：五频度 Silver 受控替换（代码与本地验证完成）

#### 9.4.1 已核对的代码和规模事实

1. `write_silver_stk_mins_partition(...)` 当前默认 `overwrite=False`；目标文件存在时会在写前
   抛出 `FileExistsError`。这正是 `d76288be-4d96-4bf7-a2d7-45f9a5be8500` 没有改动任何
   Silver 文件的原因。
2. 该 helper 虽有 `overwrite=True` 低层参数，且现有单元测试已覆盖它，但它只是对**一个**频度
   的临时文件 `os.replace`。它没有五频度共同 staging、quarantine manifest 或跨频度回滚，
   因而不能直接用于本次恢复，也不会暴露给日常 job、sensor 或 run config。
3. 当前写入逻辑已经承担了必须复用的业务语义：身份映射、全日停牌过滤、1m 价格校正、异常
   粗频 bar 的 1m 重算、成交量/成交额规范化、交易所后缀推导、冲突主键拒绝和 Parquet 类型
   强制转换。R3A 不重写或复制这些计算。
4. 四个现行 Silver blocking check 组分别验证：文件契约、主键、取值域、引用覆盖；最后一组
   还对齐 `silver_stock_daily`、`silver_stock_suspend_daily` 和 `silver_stock_lifecycle`。R3A
   的 staging 必须使用从这些现行 rule 抽取的同一组路径无关诊断，不能只看文件存在或行数。
5. 2026-07-27 当前五个 raw 文件合计约 **42.5 MiB / 1,776,093 行**；旧 Silver 合计约
   **20.5 MiB / 1,271,603 行**。旧 Silver 各频度均无空键和重复分钟键，但只有
   `3,958–3,976` 个代码，证明旧结构绿色并不能替代本次重建。五个旧+五个 staging 文件的
   峰值文件体量约为当前输入输出的两份，远小于当前卷约 **2.3 TiB** 可用空间。
6. 只读 DuckDB 统计的单文件检查耗时为：1m 约 327ms，5m 约 11ms，15m 约 8ms，30m
   约 4ms，60m 约 4ms。R3A 的重计算仅扫描本交易日的五个 raw 文件；粗频度各额外读取
   当日 1m raw。它不进入 sensor 热路径，也不扫描历史分区。

#### 9.4.2 责任边界和不可变约束

| 项 | R3A 约束 |
|---|---|
| 入口 | 已新增 non-active 离线 `stk_mins_silver_replace_from_raw` 模块和 CLI；不注册 asset、check、job、sensor、resource 或 automation。 |
| 输入 | 2026-07-27 的五个 repaired raw 文件，以及同日 `silver_stock_daily`、`silver_stock_suspend_daily` 和当前 `silver_stock_identity_map`、`silver_stock_lifecycle`。 |
| 输出 | 仅五个既有 `silver/quote/stk_mins/freq=<freq>/trade_date=2026-07-27/part-000.parquet`。不改变路径、schema、资产键、分区或计算口径。 |
| 写入纪律 | 先五个 staging，全部通过同语义校验后才整体 quarantine/promote；不直接调用现有 helper 的 `overwrite=True` 覆盖正式文件。 |
| Dagster 状态 | recovery CLI 不写 materialization/check/runless event；替换成功后由既有 Silver job 的显式 `reuse_existing` 状态复核路径重新记录 materialization 并运行既有 20 条 blocking checks。 |
| 禁止项 | 不删除旧文件、不写 prod、不补动态分区、不改 sensor/job selection/run key、不在 sensor 中调用恢复 CLI、不跳过四类 Silver check。 |

#### 9.4.3 需要实现的最小代码结构

1. `defs/assets/stk_mins.py` 已扩展现有 writer 的受限 `output_path_override` 参数：它只改变 recovery CLI 的输出目标路径，完全复用既有计算 SQL；日常 asset 调用不传该参数。
   日常 `write_silver_stk_mins_partition(...)` 仍固定写正式 Silver path，默认遇到既有文件仍失败；
   recovery CLI 仅把输出指向同卷 staging path。不能把 staging root 伪装成 Lake root，否则会
   错误读取 staging 下不存在的 raw/身份/停牌输入。
2. `defs/checks/stk_mins_checks.py` 已抽取路径参数化的 Silver rule diagnostics。现行 asset
   checks 继续调用它们，R3A 只在 staging 文件上调用同一语义；不新增或改名 Dagster check。
3. 已新增 `defs/bootstrap/stk_mins_silver_replace_from_raw.py` 与 CLI，固定 `plan` / `apply`：
   - `plan` 只读 fingerprint 五个 raw、五个旧 Silver 及四个参考输入，验证目标五文件完整存在，
     固化日期、频度、文件事实、计划 fingerprint 和 stop reasons；不重算整日 Silver，也不写 Lake。
   - `apply` 必须有新鲜绿 plan 和 `--apply`。先按 `1/5/15/30/60m` 写同卷 staging；每个
     staging 文件通过四类现行 Silver check 的全部 rule 后才进入下一频度。五个全部通过后才备份。
   - 将五个旧文件移动到
     `_quarantine/stk_mins_silver_replace_from_raw/trade_date=2026-07-27/recovery_run_id=<uuid>/`，
     写入含 input/target/staging SHA-256、字节数、计划 fingerprint，以及 staging 行数、字段和十条
     rule 诊断结果的 manifest；然后
     用同卷 `os.replace` 逐一 promote。任何 backup/promote/post-promote 断言失败都恢复已经
     移动或替换的全部旧文件，并停止。
4. 常规 `stock_mins_silver_update_job` 不能以默认配置直接重新执行：默认 `write_new` 仍会触发
   `FileExistsError`。因此已新增一个仅显式配置可用的 Silver
   `reuse_existing` mode：它只读取已存在的标准路径、收集 materialization metadata，绝不写
   Parquet；随后让该 job 原有 selection 执行已有 20 条 Silver checks。无 config 的日常行为
   仍为 `write_new`，遇到既有文件仍 fail closed。该 mode 不承担 replace，也不由 sensor 发起。

#### 9.4.4 执行和回滚步骤

1. 本地 fixture 测试和静态门禁已通过。正式执行前，先单独运行只读 R3A plan；它冻结五个 raw、
   四个参考输入和五个既有 Silver 目标的文件存在性、字节数与 SHA-256。随后另行只读核验分区日期、
   活跃 run 和现有 check 状态；任一证据异常即停止。
2. 维护窗口中仅暂停当前原本运行的六个相关 sensor，记录状态且不启动原本停止的 QFQ daily
   sensor；确认七个相关 job 无 active run。
3. 另行批准 `apply` 后运行 recovery CLI。五个 staging 和整体 promote 成功后，保留 quarantine，
   不物理删除。
4. 用显式 `reuse_existing` config 运行既有 `stock_mins_silver_update_job[2026-07-27]`。它只
   写 Dagster materialization/check 状态，不修改 Lake 文件；任一 20 条 check 失败则停止，
   从 quarantine 完整恢复五个 Silver 文件，并且不进入 QFQ。
5. 只读核验五个新 Silver 的行数、代码集合、频度/日期、键、四类 check 及 raw 输入 hash；
   全绿后才恢复原本运行的 sensor 并继续原 R3 的 QFQ、repair、MACD/KDJ、wealth 顺序。

#### 9.4.5 测试、性能门禁与停止条件

1. 新 CLI fixture 覆盖：plan 零写入、缺 raw/reference/target、stale fingerprint、staging 文件
   任一规则失败、五频度均绿、quarantine manifest、promote 中途异常全量恢复、重复 apply 拒绝。
2. 参数化 diagnostics 测试确保 staged 与正式路径对同一输入给出相同的文件契约、主键、取值域
   和引用覆盖结论；普通日常 writer 对已有文件仍抛 `FileExistsError`。
3. `reuse_existing` 测试必须锁住：显式模式零 Parquet 字节变化、正常 job selection 不变、无
   config 不改变当前 fail-closed 行为、20 条既有 checks 仍被选择；静态门禁禁止 recovery CLI
   被 sensor、asset definition 或 run config builder 引用。
4. 性能预算固定为单日五频度：最多读取 5 个 raw、5 个 staging/target 和 4 个 reference
   Parquet；粗频度额外复用同日 1m raw；最多输出 5 个 staging、移动 5 个 quarantine、promote
   5 个正式文件。禁止 Python 行循环、历史 glob、逐股票文件扫描或 Dagster event-history 深扫。
5. 任一 source/reference fingerprint 变化、任一 staging rule 失败、quarantine/manifest 不完整、
   promote 回滚失败、显式 reuse job 的任一 blocking check 失败，均停止在 Silver，不进入 QFQ。

已完成的本地验证包括：恢复 CLI 的 plan 零写入、staging 十条 rule 诊断、stale plan 拒绝、诊断
失败不触碰正式目标、五频度 quarantine/promote、promote 中途回滚、显式 `reuse_existing` 零
Parquet 字节变化、默认 `write_new` fail-closed、job selection 与 sensor 隔离静态门禁。R3A 尚未运行
正式 plan 或 apply，未触碰正式 Lake、Dagster instance、prod 或 sensor 状态。

## 10. 不做的事

- 不创建 prod 完成视图、完成表、manifest、asset、check 或状态文件；
- 不让 DG 读取其它 `ops.*` 表，或接入 prod scheduler/worker；
- 不导出、聚合或比较分钟 OHLC/成交额来判断 prod 是否 ready；仅允许第 3.2 节的有界分钟键身份覆盖查询；
- 不改 raw/silver/gold asset 名、job 名、sensor 名、partition、路径、schema 或正常 run key；
- 不自动覆盖历史半成品，不在 24:00 后静默自动补数；
- 不把 Dagster materialization 当成 prod 完成证明，也不把 prod TaskRun 当成 Lake ready。

## 11. 开发前阻断项

1. 已完成：`lake_raw_reader` 已获 `ops` schema USAGE 和 `ops.task_run` 的 18 个显式字段 SELECT；DML 权限为 false。
2. 已完成：实际 TaskRun JSON 已证明 `time_input_json`、`filters_json`、`plan_snapshot_json` 能区分全市场五频度任务与代码子集补跑。
3. 已完成但形成设计纠偏：TaskRun `success` 满足 unit、行数和 reject 口径，仍可能在后续出现代码子集补跑。因此生产门禁必须保留第 3.2 节代码覆盖，不能仅依赖 TaskRun status。
4. 已完成：R1 离线 recovery CLI 与临时 Lake fixture 测试。它仍须单独审批 R2 的 sensor 暂停、CLI apply 与后续 job；R1 本身未触碰正式 Lake、Dagster instance 或 prod 写入。
5. 仍待完成：未来日常 TaskRun + prod 代码覆盖双门禁、asset 二次复核和部署；它们与 R1 历史恢复分开开发、分开验收。
