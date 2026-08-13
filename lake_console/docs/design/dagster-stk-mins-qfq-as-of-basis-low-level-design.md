# Dagster 股票分钟线 QFQ As-Of 因子审计依据撤销记录

> 2026-08-13 补充：本文仍是已撤销方案，不参与当前分钟线修复。当前 Gold 非 1m
> 竞价锚点、QFQ source 和历史重建只按
> [A 股分钟线 Gold 标准 K 线合同与历史重建 LLD](./dagster-cn-a-minute-gold-canonical-bars-rebuild-low-level-design.md)
> 执行；不得借本撤销记录恢复 as-of basis 侧车或 production 公式复算。

更新时间：2026-07-15

状态：**已撤销，禁止启用。** 本文保留为一次被否决方案的事实记录，不是当前设计、实现或运行依据。现行口径见 [QFQ 计算测试与生产 Check 治理低层设计](dagster-stk-mins-qfq-validation-governance-low-level-design.md)。

> 撤销原因：本方案把 QFQ 公式二次计算放进 production check/readiness，并试图从既有 QFQ 结果反推全历史 as-of 因子。前者会把 check 变成昂贵的第二计算系统；后者最多证明历史文件内部自洽，不能证明当年因子来源正确。2026-07-15 的独占只读 plan 在 328.89 秒后耗尽 16 GiB DuckDB 预算，未生成报告、未写入 Lake。任何 as-of basis 路径、bootstrap、sidecar、check/readiness 依赖均不得据本文启用。

## 撤销决定

1. QFQ 计算公式正确性由受保护的金样本测试负责，不由 Dagster production check 重新计算 OHLC 负责。
2. production check 只验证上游输入、目标文件契约、分区完整性和 repair 状态新鲜度。
3. 既有历史缺少写入当时的 as-of 事实时，保持“未具备公式审计依据”，不得从自身结果反推后写成已验证事实。
4. 本文第 2 节及以下内容仅用于解释被撤销方案的来由和代码清理范围；其中的“必须”“正式”“当前”措辞均不再生效。

## 1. [撤销方案] 一句话结论

`gold_stk_mins_qfq` 的历史文件可以在一次 factor repair 后使用较新的 as-of 复权因子。因此，不能再用“目标交易日的复权因子”直接重算历史 QFQ 并把差异判成错误。

本设计为每个 `ts_code + trade_date` 固化实际使用的 **as-of 因子数值**，作为 QFQ 文件族的年度审计侧车。正式 formula check 和 batch readiness 都直接读取这个依据，按真实 QFQ 公式校验。现有“普通 check 先红，再由 readiness 根据 repair event 改判为绿”的逻辑彻底删除。

## 2. [撤销方案] 已核实事实与根因

以下结论来自当前代码与 2026-07-15 的只读审计，不是推测。

1. 日常 QFQ 写入 `write_gold_stk_mins_qfq_asset_partition(...)` 使用同日 `silver_adj_factor[trade_date]` 作为 as-of 因子；这是正确的日常口径。
2. `execute_gold_stk_mins_qfq_factor_repair(...)` 在发现因子变化后，用 repair 触发日的 `silver_adj_factor` 重写受影响代码从历史起点到触发日的 QFQ 文件；这也是正确的 repair 口径。
3. 现有 `gold_stk_mins_qfq_formula_matches_silver_adj_factor` 及 batch readiness 却始终把目标日因子同时当作 trade 因子和 as-of 因子。历史文件被 repair 后，数据正确但此 check 会错误变红。
4. `effective_gold_qfq_readiness_for_trade_date(...)` 随后查询 repair event metadata，确认红色代码被某次 repair 覆盖后，将 readiness 改判为绿。它让调度继续运行，但 Dagster UI 上的原 check 仍为红色，且调度真相依赖两套相互矛盾的机制。
5. 只读公式审计覆盖 `2026-06-30` 至 `2026-07-10` 共 9 个日期、五个 native 频度。按错误的同日 as-of 口径有 `867,975` 条公式差异；按每个代码实际 repair as-of 因子重算则 `1,022,056` 条可比行全部通过，未发现真实 QFQ 公式错误。
6. 当前 QFQ Lake 共有 `370,023` 个 Parquet、约 `79 GiB`；`silver_stk_mins[1m]` 已注册并有文件的日期为 `2014-01-02` 至 `2026-07-14`，共 `3,045` 个交易日。不能把这类审计依据做成逐日 Dagster event 或逐股票小文件。

## 3. [撤销方案] 目标、边界与硬约束

### 3.1 目标

1. 固化每个代码在每个交易日实际使用的 as-of 因子数值，供人和程序独立复核。
2. 让既有 `gold_stk_mins_qfq_formula_matches_silver_adj_factor` 直接表达真实 QFQ 公式，而不是同日因子公式。
3. 让 `batch_gold_stk_mins_qfq_lake_readiness(...)` 复刻同一公式语义，不读取 repair event 来修正 check 结论。
4. 删除 `effective_gold_qfq_readiness_for_trade_date(...)`、`gold_qfq_formula_mismatch_codes(...)` 及三处 sensor 的 repair-aware 绕行。
5. 不增加日常 Dagster event 数量；不为历史 3,045 个日期补 materialization 或普通 check event。

### 3.2 不做

1. 不改变 QFQ 计算公式、现有 QFQ Parquet 列、路径、asset 名、check 名、job 名、sensor 名、run key、分区模型或动态分区。
2. 不把 as-of basis 设计成新的 active Dagster asset、job、sensor、check、resource、数据库表或 cursor 状态。
3. 不修改 MACD/KDJ 公式、repair 范围、completion check 身份或事件数量。
4. 不在本轮写 Lake、Dagster instance、prod DB，或启停 sensor/job。历史 basis 初始化另行审批。
5. 不保留旧 readiness fallback，也不让 sensor 根据 repair metadata 覆盖一个仍然失败的正式 formula check。

## 4. [撤销方案] As-Of Basis 数据契约

### 4.1 物理布局

```text
gold/quote/stk_mins_qfq_as_of_basis/
  year=<YYYY>/
    part-000.parquet
```

年度文件而不是逐日、逐代码文件，原因是：

1. 一次日常更新只会触及目标年份的一个小文件。
2. 一次历史 factor repair 最多触及 `2014` 至当前年的年度文件，不会把 Lake 扩张为数十万 basis 小文件。
3. 日常 5 日 readiness 只需要读取涉及年份的 1 至 2 个 basis 文件，而不是扫描 370,023 个 QFQ 文件或 Dagster event history。

这个文件是 `gold_stk_mins_qfq` 的**内部审计侧车**，不是独立面向下游消费的数据集。因此不新增 `LakeAssetCatalogEntry`、不新增 Dagster asset identity；五个 native QFQ asset 的 definition metadata 只追加已命名空间化的 basis path template 和 basis contract 标识。

### 4.2 固定 schema

| 字段 | 类型 | 含义 |
|---|---|---|
| `ts_code` | `VARCHAR` | 标准股票代码 |
| `trade_date` | `DATE` | 被 QFQ 的交易日 |
| `as_of_adj_factor` | `DOUBLE` | 该代码该日 QFQ 实际使用的分母因子；这是公式校验的权威依据 |
| `as_of_trade_date` | `DATE NULL` | 因子来源日期。日常和 repair 必填；历史重建若无法从旧运行事实唯一证明日期则为 `NULL`，不得猜填 |
| `basis_origin` | `VARCHAR` | 仅允许 `daily_qfq`、`factor_repair`、`history_reconstruction` |

唯一键为 `(ts_code, trade_date)`。`as_of_adj_factor` 不允许为 null、零、非有限数；`trade_date` 必须属于目录年份；`basis_origin` 必须在上述枚举内。

`as_of_trade_date` 是可审计的来源信息，不是公式的主键。复权因子值可能在多个交易日相同，历史文件也可能缺失原始 bootstrap 的唯一运行日期。对这种无法证明唯一日期的历史行，保存可由现有 QFQ 文件反推并全量验证的因子数值，标为 `history_reconstruction`，而不是伪造一个日期。

### 4.3 真实 QFQ 公式

对 gold QFQ 的 OHLC，正式语义统一为：

```text
gold_price
  = silver_price
  * trade_date_adj_factor
  / as_of_basis.as_of_adj_factor
```

其中 `trade_date_adj_factor` 仍来自同日 `silver_adj_factor`；分母来自 basis。对于 `basis_origin in ('daily_qfq', 'factor_repair')`，check 还必须验证：basis 的 `as_of_adj_factor` 等于 `silver_adj_factor[as_of_trade_date]` 中同一代码的因子。对 `history_reconstruction`，check 只使用已验证的数值 basis，不虚构来源日期。

## 5. [撤销方案] 代码级实现

### 5.1 基础 helper 与路径

在 `defs/stk_mins_qfq.py` 增加下列稳定能力：

1. `GOLD_STK_MINS_QFQ_AS_OF_BASIS_COLUMNS` 和基于 `GOLD_STK_MINS_QFQ_AS_OF_BASIS_SCHEMA` 的列类型契约。
2. `gold_stk_mins_qfq_as_of_basis_path(lake_root, year)`，在 `defs/paths.py` 固定上述年度路径。
3. 生成 daily、repair、history 三类 basis replacement rows 的 DuckDB SQL。大数据路径只用 SQL；Python 只负责年份分组、路径、校验和汇总。
4. `write_gold_stk_mins_qfq_as_of_basis(...)`：按年份读取既有 basis，删除本次 replacement 的 `(ts_code, trade_date)`，`UNION ALL` replacement 后按唯一键校验、写临时文件、schema/行数校验、同卷 `os.replace`。
5. basis 根目录使用一个只保护 basis 写入的排他锁文件。这样日常 QFQ asset 与维护型 factor repair 即使被人工并发启动，也不能对同一年度 basis 发生丢失更新。锁等待或校验失败时 fail closed，不写 green state。

已有 `gold_stk_mins_qfq` 结果文件仍使用原来的按 `freq/ts_code/year` 原子替换函数；basis 不是把这 370,023 个文件重新布局。

### 5.2 日常 QFQ 写入

`write_gold_stk_mins_qfq_asset_partition(...)` 在 native 频度完成既有 QFQ 文件写入并通过原 coverage guard 后，构造同日 basis replacement：

```text
ts_code = 该 native silver/QFQ 输入中的代码
trade_date = partition_key
as_of_adj_factor = 同日 silver_adj_factor 的 adj_factor
as_of_trade_date = partition_key
basis_origin = daily_qfq
```

五个 native asset 允许各自请求同一份 basis upsert，以保证手工只跑任一 native asset 时仍有完整依据。upsert 必须语义幂等：若年度文件中该日期、代码、因子、来源已经完全一致，只返回 `unchanged`，不再物理替换文件。90m/120m 是从 native QFQ 派生，不写 basis。

materialization metadata 只追加紧凑汇总：basis 年份、replacement code count、written/unchanged 和 `as_of_trade_date`；不写完整代码列表。

### 5.3 Factor repair

`execute_gold_stk_mins_qfq_factor_repair(...)` 保持现有 QFQ 和派生频度改写顺序。只有全部既有 QFQ/derived 写入成功后，才一次性为 `repair_required_codes × selected_partition_keys` 更新 basis：

```text
as_of_adj_factor = silver_adj_factor[repair_trade_date]
as_of_trade_date = repair_trade_date
basis_origin = factor_repair
```

这一步在既有 repair op 的同一次运行内完成，不新增 asset/check/event。若 basis 更新失败，repair op 失败；QFQ 文件即使已改写也会因为 basis 与文件不一致而让正式 formula check/readiness fail closed，不能误判为完成。

### 5.4 新历史生成与现存历史初始化

1. `generate_stk_mins_qfq_history(...)` 对未来全新历史生成，在所有既有 QFQ batch 成功后，按当次 plan 的真实 `as_of_trade_date = selected_partition_keys[-1]` 生成 basis。新生成历史也使用既有 `history_reconstruction` 来源名，但必须填写实际 `as_of_trade_date`；只有本设计之前、无法唯一反推来源日期的旧文件才允许该字段为空。
2. 新增非 active bootstrap 模块与 CLI：
   - `bootstrap/stk_mins_qfq_as_of_basis.py`
   - `bootstrap/stk_mins_qfq_as_of_basis_cli.py`
3. CLI 默认 `plan`，只读扫描 1m silver、1m QFQ 与同日 adj factor，以 `silver_close * trade_factor / gold_close` 反推每个 `(ts_code, trade_date)` 的实际分母；对每个代码日先验证分钟级推导值在正式公式容差内一致，再生成年度 replacement plan。
4. 只有显式 `--apply` 才能写 basis。写入仍是年度 `.tmp -> validate -> os.replace`，写后必须用同一真实 QFQ 公式审计全部 basis 行。任何空 basis、重复键、未覆盖 QFQ 代码日、推导离散超容差、公式差异或已有目标冲突都停止。
5. 历史重建不写 Dagster materialization/check event，也不改 QFQ Parquet。它只产生 `/private/tmp/stk_mins_qfq_as_of_basis_*` 计划与审计报告。

### 5.5 正式 check 与 readiness

保留原 check 名：`gold_stk_mins_qfq_formula_matches_silver_adj_factor`。其检查内容改为真实 QFQ 公式，且把下列 basis 故障收敛到这一条现有 blocking check：

1. 年度 basis 文件缺失或 schema 不符。
2. gold `(ts_code, trade_date)` 没有恰好一条 basis。
3. basis 有空 key、重复 key、非法因子、年份错位或非法来源。
4. 对有来源日期的 basis，日期或因子与 `silver_adj_factor` 不一致。
5. 用 basis 分母重算后，gold 缺行、多行或 OHLC 公式不一致。

这样不新增细碎 check，也不把“basis 存在”弱化为文件存在检查。`gold_stk_mins_qfq_source_coverage_check` 的因子 coverage 同步按 basis 校验，不再假设 as-of 因子等于 trade-date 因子。

`batch_gold_stk_mins_qfq_lake_readiness(...)` 提取或复用相同的 SQL 契约。它按窗口涉及年份一次读取 basis 年度文件，不得逐日调用单日 helper，不得读取 Dagster event/check history，也不得只因文件存在就返回 ready。

### 5.6 删除 readiness 绕行

删除 `defs/asset_guards/stk_mins_qfq_effective_readiness.py` 及其所有引用：

1. `stock_mins_qfq_daily_sensor.py`
2. `stock_mins_qfq_factor_repair_sensor.py`
3. `gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor.py`
4. 对应 unit/performance/static-gate 测试

三个 sensor 仍保持当前窗口、run key、run config、选择第一个未完成日期、短路顺序和每 tick 最多一个请求的行为；唯一变化是它们直接消费真实 `batch_gold_stk_mins_qfq_lake_readiness(...)` 结果。不存在“check failed 但 effective ready”的状态。

## 6. [撤销方案] 性能与写入预算

| 入口 | 读取模型 | 写入模型 | 预算与拒绝策略 |
|---|---|---|---|
| Native QFQ daily | 当前 silver、当日 adj factor、当前年 basis | 最多一个年度 basis 文件；重复语义完全一致时零替换 | 不扫描历史；basis 校验或锁失败立即失败 |
| Factor repair | 已有 repair 的 `freq/year` QFQ 批次；受影响代码的历史日期；最多 `2014` 至当前年 basis | 最多一个年度 basis 文件/受影响年份，无 Dagster event 增量 | 任一既有 QFQ/derived 写入失败或 basis 覆盖不完整即失败 |
| Check / 5 日 sensor 热路径 | 目标 QFQ 文件、同日 silver/adj、窗口涉及的 1 至 2 个年度 basis | 零 | 不读 repair event；不回调逐日 full helper；语义不完整即 not ready |
| 历史 basis bootstrap | 1m silver、1m QFQ、同日 adj factor，按年 DuckDB set-based join | 最多 13 个年度 basis 文件；零 Dagster event | 先 plan/sample，再显式 apply；发现任何推导或公式异常立即停止 |

当前 `2014-01-02` 至 `2026-07-14` 覆盖 13 个自然年度。bootstrap 的准确行数、每年行数、输出字节和耗时必须由 `plan` 实测写入报告，不能在代码里硬编码估算。目标是把 audit 数据控制为 13 个年度文件，而非数十万小文件或数万个 Dagster event。

## 7. [撤销方案] 测试与静态门禁

### 7.1 单元与 DuckDB fixture

1. path/schema：年度路径、字段顺序、唯一键、来源枚举和目录年份一致性。
2. daily upsert：写入同日 as-of 因子；重复 native 写入语义幂等；90m/120m 不写 basis。
3. repair upsert：只改 selected codes 与 expected date range；未受影响代码和日期不变；repair date/factor 必须准确写入。
4. historical reconstruction：稳定推导正确因子；零价格/无可比行/推导离散/重复键均 fail closed；dry-run 零写入。
5. direct QFQ check：历史 gold 使用未来 repair 因子时，basis 正确则通过；缺 basis、错 basis、错来源日期、错因子、重复 basis、公式真错均失败。
6. batch readiness：与 direct check 对同一 fixture 一致；仍是真 batch，不调用单日 helper 或 Dagster instance。
7. sensor：正常 request/skip 行为不变；不再 import 或调用 effective readiness；正式 QFQ check 失败就不能请求 run。

### 7.2 静态门禁

1. 生产代码不得再引用 `effective_gold_qfq_readiness_for_trade_date`、`gold_qfq_formula_mismatch_codes` 或 `stk_mins_qfq_effective_readiness`。
2. native QFQ formula check/readiness 不得再把 `silver_adj_factor[partition_key]` 同时作为 trade 和 as-of 分母输入。
3. 新 basis bootstrap 默认路径不得写 Lake；只有显式 `--apply` 可以写。
4. 不得新增 QFQ formula/basis 的 Dagster check、asset、job、sensor 或 runless event。
5. 不得在 cursor 或 materialization metadata 写完整代码、文件或日期清单。

### 7.3 本轮实现结果

1. 已新增年度 sidecar 路径、固定 schema、基于 DuckDB 的 replacement/upsert 与单写入锁；daily、factor repair 和未来历史生成都会在既有 QFQ 文件写入成功后更新它。
2. native QFQ direct check 与 batch readiness 已改为读取 sidecar，并验证有来源日期的 basis 因子确实来自对应的 `silver_adj_factor` 文件；缺 basis、错 basis、重复键或真实公式差异都会保持 blocking failed。
3. 旧 `stk_mins_qfq_effective_readiness.py` 已删除，三处 sensor 不再根据 repair event 覆盖 failed formula check。
4. 已新增非 active bootstrap module/CLI：`plan` 只读，`apply --plan-report ... --apply` 才能写 Lake；apply 前重算 fingerprint，apply 后重跑真实公式审计。它不创建 Dagster asset、check、job、sensor 或 event。
5. 本轮未运行 bootstrap plan/apply，未写正式 Lake、Dagster instance 或 prod DB。正式初始化仍按第 8 节的审批顺序执行。

建议验证命令：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
uv run python -m unittest \
  tests.test_stk_mins_qfq_as_of_basis \
  tests.test_stk_mins_qfq_m8c_history \
  tests.test_stk_mins_qfq_m9c_factor_repair \
  tests.test_stk_mins_lake_readiness \
  tests.test_stk_mins_qfq_m9a_sensor_contracts \
  tests.test_stk_mins_qfq_m9c_sensor_contracts \
  tests.test_stk_mins_continuity_performance \
  tests.test_run_contract_static_gates
git diff --check
```

不默认运行 `dg check defs`、job、sensor、materialize、backfill 或 bootstrap apply。

## 8. [撤销方案] 上线顺序与审批边界

代码合入不等于 basis 已启用。为了不出现“代码已要求 basis、但 Lake 里尚无 basis”而阻塞运行，正式启用顺序固定如下：

1. 完成代码与本地测试；不写 Lake 或 Dagster instance。
2. 单独执行 basis bootstrap 的只读 `plan`，输出每年行数、字节、推导离散、QFQ 覆盖和正式公式差异报告。
3. 管理员审批后，暂停 QFQ daily、QFQ factor repair 与依赖其 readiness 的下游 sensor；确认无 active run。
4. 备份现有 basis 目标（首次为空也要记录），执行 `--apply`，按年原子写入并完成 final audit。
5. 仅在 final audit 全绿后，让包含本设计代码的 definitions 生效；随后由管理员单独批准对最近窗口运行既有 formula check/job 验证。
6. 不补历史普通 QFQ event。旧的红色 check event 仅是历史的错误评估证据；新的正确 check 会在正常运行或获批的 check refresh 时写入。禁止用 runless 绿事件覆盖历史。
7. basis 缺失、plan/apply 不一致、任一年有公式差异、任何 active run、或 check/readiness 语义与本设计不一致时，停止，不删除旧 basis，不启用新代码路径。

## 9. [撤销方案] 与既有方案的关系

1. 本文已同步 `dagster-stk-mins-qfq-macd-kdj-indicators-plan.md`：当前 daily sensor 使用“直接 QFQ readiness”，不保留双口径。
2. 本文不推翻 R5 的 repair 事实：repair 确实按代码集合和触发日改写历史 QFQ，MACD/KDJ repair 仍按既有 completion check 处理。本文只让 QFQ 自身的 check/readiness 使用同一事实。
3. 本文不恢复被撤销的普通 QFQ reconciliation event 方案；basis 是 Lake 文件事实，不是 Dagster 历史事件账本。
