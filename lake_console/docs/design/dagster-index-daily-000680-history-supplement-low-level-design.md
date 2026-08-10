# 科创综指 `000680.SH` 指数日线历史补录 LLD

> 状态：M0、M1、M2、M3、M4、M5、M6 已完成；Raw/Silver 历史补录、11 指数日级 seed 发布、1599 个 Gold 分区重建和 Prod -> source staging -> Raw -> Silver -> Gold 全链路只读对账均已通过。M8 已完成物理链路最小收口；M7 Dagster instance/event 写入仍未执行，也未被本状态授权。
> 审计日期：2026-08-09。
> 适用范围：DG 正式湖 `raw_index_daily`、`silver_index_daily`、`gold_market_major_indices_daily`，以及日级主要指数 seed。
> 不在本轮范围：Tushare 重新请求、Prod 数据写入、分钟线对象池、Wealth 首页 10 指数配置、正式 Dagster instance 写入。

### 当前实施状态（2026-08-09）

M0、M1、M2、M3、M4、M5、M6 已完成，物理湖写入和全链路只读对账均已验收：

1. M5 冻结计划位于 `/Volumes/datasource/data_lake_staging/index_daily_000680_history_supplement/run_id=m5-20260809/manifest/plan.json`。
2. M5 冻结 `plan_hash=9682418678919443c9f49a006f8581c3524e09be680b58c29bad0e6401526249`，`should_stop=false`。
3. source 为 1223 行、1223 个 distinct dates、零缺日、零重复、零关键字段空值、零非法 OHLC；边界 `2025-01-16.close = 2025-01-17.pre_close = 1090.4478`。
4. 目标文件为 Raw 1223、Silver 1223、Gold 1599；物理文件均存在。Raw/Silver 目标历史行各 1223，Gold `000680.SH` 目标行 1599。
5. 正式 instance 的目标 1223 个日期分区零缺失，`000680.SH` 已注册，当前注册指数代码 820 个。
6. 日级 seed 已从 10 个增至 11 个；保留 `899050.BJ`，追加 `000680.SH` 为 rank 11，`effective_start_date=2020-01-02`，seed SHA256 为 `963eeb727f5c1029b8933395a68e3c28084c4e655105cb2b6c15b9300f752bcd`。
7. M2 已把 1223 行 source 写入 run-scoped staging；Parquet SHA256 为 `647af89ef8f5f98d7a02a3ee9a6e5864efa88ce853056e542f467308f328117f`，独立 DuckDB 审计与 source blocking gates 全绿。
8. M3 已且只处理 `2020-01-02`、`2022-07-13`、`2025-01-16` 的 Raw/Silver；6 个正式文件均通过候选校验、原子提升和幂等重跑。
9. M5 在任何 Gold 候选生成和正式 writer 调用前强制核验冻结 seed 的路径、SHA256、行数和解析合同，任一漂移均 fail closed。
10. M5 先验证 `2020-01-02`、`2022-07-13`、`2025-01-16` 三个 Gold 样本日，再按最多 100 个交易日一批重建全部 1599 个 Gold 日期；三个样本日和 16 个全量批次全部通过。
11. M4 开始前已修正累计 checkpoint 与断点续跑语义；执行代码文件 SHA256 为 `6b8a64a543227aad29a94e53c043e13a9f94884f63ecaa2a54cfe93d3700a664`，checkpoint schema 继续使用 v1，没有新增兼容格式。
12. M4 已按最多 100 个交易日一批完成 13 个 Raw 批次和 13 个 Silver 批次；两层累计 checkpoint 均为 1223/1223。
13. source、Raw、Silver 的 1223 行目标数据逐行一致；Raw/Silver 各 978623 行、零重复键、零错误分区、每个目标日期恰好 1 行 `000680.SH`。
14. M5 的 Gold 累计 checkpoint 为 1599/1599；全量合同核验得到 expected/actual 均为 15726 行、零缺失、零意外行、零重复键、零重复 rank、零错误分区。
15. M5 的 16 个幂等批次新增 promotion 均为 0；本阶段未写 Dagster event/check history、未注册 dynamic partition、未修改分钟线对象池或 Wealth 首页配置。
16. M6 使用冻结的 M2 source plan/hash、source Parquet SHA256 和 M5 plan/hash 执行全链路只读审计；审计报告 `passed=true`，`audit_hash=3cca24c69028e00644828b33da11228f147af97cd7be9cf19381a4279a6741e4`。
17. M6 重新导出当前 Prod 1223 行并与 source staging 逐键比较：`source_only=0`、`prod_only=0`；source、Raw、Silver 均为 1223 行/1223 日期，跨层 fingerprint 完全一致。
18. M6 核验 Gold 为 1599 行/1599 日期，所有日期均满足发布后的 active seed coverage/rank 合同；正式湖、Dagster DB、dynamic partition 和 event 写入计数均为 0。
19. M8 只完成物理链路文档、测试和验收证据收口；由于 M7 未执行，Dagster instance/event 观测链路仍保留为独立待审批阶段，不能把 M8 解释为整项任务全部关闭。

## 1. 目标与冻结口径

本方案把 Prod DB 已补齐的科创综指日线历史数据安全补录到 DG，并将科创综指纳入**日级**主要指数池。

冻结口径如下：

1. 数据源固定为 Prod `core_serving.index_daily_serving`，代码固定为 `000680.SH`。
2. 历史补录区间固定为 `2020-01-02` 至 `2025-01-16`，共 1223 个上交所开市日、1223 行。
3. DG 在该区间的日期分区和 Parquet 文件已经存在；本次不是新增 1223 个日期分区，而是向每个既有 Raw 文件补 1 行，再重建同日 Silver。
4. DG 的 `000680.SH` Silver 从 `2025-01-17` 起已经存在，不得重复补写或删除。
5. 日级主要指数 seed 从 10 个增至 11 个：保留 `899050.BJ` 北证50，新增 `000680.SH` 科创综指。
6. 分钟线池继续使用自己的 source scope / Silver 有效池，不读取日级 seed；本方案不得改变分钟线排除北证50的既有合同。
7. Wealth 市场总览的 10 张主要指数卡由 `src/biz/services/wealth/config/definitions/major_indices.cn_a.v1.json` 独立配置。本次 DG seed 变更不会自动把页面改成 11 张卡，也不得修改该配置。
8. 物理数据写入、dynamic partition 注册、runless event 回放是不同审批阶段；本 LLD 本身不授权任何写入。
9. 管理员已拍板：`000680.SH` 的日级 seed `effective_start_date` 固定为 `2020-01-02`。
10. 管理员已拍板：`000680.SH` 追加为 `rank=11`，原 rank 1..10 的代码和顺序保持不变。
11. 本任务不创建文件备份；写入安全依赖候选文件完整校验、`os.replace()` 原子提升、逐文件 checkpoint 和幂等续跑。

## 2. 当前事实审计

### 2.1 Prod DB 审计

只读审计表：

- `raw_tushare.index_daily`
- `core_serving.index_daily_serving`
- `core_serving.trade_calendar`

过滤条件：`ts_code = '000680.SH'`，日期 `2020-01-02..2025-01-16`。

| 审计项 | Raw | Serving | 结论 |
|---|---:|---:|---|
| 行数 | 1223 | 1223 | 与 SSE 开市日完全一致 |
| distinct trade dates | 1223 | 1223 | 一日一行 |
| 最早日期 | 2020-01-02 | 2020-01-02 | 起点已确认 |
| 最晚日期 | 2025-01-16 | 2025-01-16 | 与现有 DG 尾部连续 |
| 缺失 SSE 开市日 | 0 | 0 | 无日期缺口 |
| 非开市日数据 | 0 | 0 | 无越界日期 |
| 重复主键 | 0 | 0 | 无重复 `(ts_code, trade_date)` |
| OHLC、昨收、涨跌、涨跌幅、量额空值 | - | 0 | Serving 可直接作为正式输入 |
| Raw/Serving 核心字段不一致 | 0 | 0 | 两层数据完全对账 |

Prod Serving 当前全量事实：

- `000680.SH` 共 1599 行；
- 日期范围 `2020-01-02..2026-08-07`；
- 对照 SSE 开市日共 1599 日，缺失 0 日。

边界连续性样本：

| trade_date | close | pre_close |
|---|---:|---:|
| 2025-01-16 | 1090.4478 | 1103.0262 |
| 2025-01-17 | 1103.2994 | 1090.4478 |
| 2025-01-20 | 1107.3130 | 1103.2994 |

`2025-01-17.pre_close = 2025-01-16.close`，补录段与 DG 现有尾部在价格口径上连续。

### 2.2 M0 执行前 DG 正式湖审计基线

正式湖根：`/Volumes/datasource/data_lake`。

目标区间 `2020-01-02..2025-01-16` 的 1223 个 SSE 开市日：

| 层 | 缺失 `part-000.parquet` | `000680.SH` 行数 | 结论 |
|---|---:|---:|---|
| Raw `raw/index_daily/trade_date=...` | 0 | 0 | 文件存在，但缺目标代码 |
| Silver `silver/index_daily/trade_date=...` | 0 | 0 | 文件存在，但缺目标代码 |
| Gold `gold/market/major_indices_daily/trade_date=...` | 0 | 0 | 文件存在，旧 seed 未选择目标代码 |

DG 现有 `000680.SH`：

| 层 | 行数 | 最早日期 | 最晚日期 |
|---|---:|---|---|
| Raw | 376 | 2025-01-17 | 2026-08-07 |
| Silver | 376 | 2025-01-17 | 2026-08-07 |
| Gold | 0 | - | - |

`silver_index_basic` 已存在该指数身份：名称“科创综指”、市场 `SSE`、基日 `2019-12-31`、发布日期 `2025-01-20`、终止日为空。发布日期不是历史回算数据的起点；本方案的 seed `effective_start_date=2020-01-02` 由 Prod/Lake 可用日线事实和 SSE 开市日完整性决定。

典型分区：

| 日期 | Raw 总行/目标行 | Silver 总行/目标行 | Gold 总行/目标行 |
|---|---:|---:|---:|
| 2020-01-02 | 795 / 0 | 795 / 0 | 8 / 0 |
| 2025-01-16 | 815 / 0 | 815 / 0 | 10 / 0 |
| 2025-01-17 | 817 / 1 | 817 / 1 | 10 / 0 |
| 2026-08-07 | 820 / 1 | 820 / 1 | 10 / 0 |

### 2.3 当前代码合同

| 事实 | 当前代码 | 对本方案的约束 |
|---|---|---|
| 日期分区 | `cn_a_index_trade_days` | 目标日期物理文件已存在；正式 instance 是否注册仍须执行前只读核验 |
| 指数代码注册 | `cn_a_index_ts_codes` | Gold check 要求 seed 代码已注册；必须执行前核验 `000680.SH` |
| Raw 正式入口 | `write_raw_index_daily_partition_from_prod_db()` | 按当日注册代码全集取数并要求 exact coverage，只支持 replace |
| Silver 正式 helper | `materialize_silver_index_daily_partition_from_raw_by_date()` | 可在 Raw 补录后复用，逐日原子替换 Silver |
| Gold 选择逻辑 | `active_major_indices_seed_rows()` + Silver join | seed 变更后须重建所有生效日期的 Gold |
| Gold checks | contract/value/seed coverage/rank/index-basic/registered-code | `000680.SH` 必须同时存在于 Silver、index_basic、dynamic code registry |
| 物理替换 | 临时文件 + `os.replace()` | Bootstrap 也必须沿用同等级原子替换语义 |

## 3. 为什么不能直接跑普通历史 backfill

普通 `raw_index_daily` 不是单代码补录器：

1. 它读取 `cn_a_index_ts_codes` 当前注册代码全集；
2. 对单个历史日期要求 Prod 返回集合与当前全集完全一致；
3. 历史日期中很多指数尚未发布，当前全集在历史日期天然无法 exact coverage；
4. 写入模式是整文件 replace，不是按代码 merge；
5. 用它处理本次补录，可能在校验阶段失败，或在错误放宽校验后覆盖既有历史行。

因此本轮必须使用专用、一次性的 Direct Lake Bootstrap。该工具只允许替换 `000680.SH` 这一行，禁止改变同文件中的任何其他代码。

## 4. 目标拓扑

```text
Prod core_serving.index_daily_serving
  WHERE ts_code='000680.SH'
    AND trade_date BETWEEN 20200102 AND 20250116
              |
              v
run-scoped source staging + immutable manifest
              |
              v
existing Raw by-date file
  (remove target code if present + append one staged row)
              |
              v
formal Silver helper rebuilds same 1223 dates
              |
              v
daily major-index seed: 10 -> 11
  preserve 899050.BJ + append 000680.SH
              |
              v
Gold rebuild: 2020-01-02..latest available date
              |
              v
physical reconciliation
              |
              v
dynamic partition reconciliation + runless events
  (separate approval)
```

## 5. 代码落点

### 5.1 新增一次性 Bootstrap 模块

| 文件 | 职责 |
|---|---|
| `defs/bootstrap/index_daily_000680_history_supplement_plan.py` | 只读生成 source/Raw/Silver/Gold/partition/event 计划与 plan hash |
| `defs/bootstrap/index_daily_000680_history_supplement_plan_cli.py` | dry-run CLI；只输出计划和审计结果 |
| `defs/bootstrap/index_daily_000680_history_supplement_apply.py` | 执行 source staging、Raw merge、Silver rebuild、Gold rebuild |
| `defs/bootstrap/index_daily_000680_history_supplement_apply_cli.py` | 显式 `--apply --expected-plan-hash` 写入入口 |
| `defs/bootstrap/index_daily_000680_history_supplement_audit.py` | 只读审计冻结 source staging、Raw/Silver/Gold 目标行、重复键、跨层 fingerprint、source SHA256 与两份冻结 plan hash |
| `defs/bootstrap/index_daily_000680_history_supplement_audit_cli.py` | 只读物理审计 CLI；必须显式传入 source plan/hash/source SHA256，只向显式报告路径写 JSON |
| `defs/bootstrap/index_daily_000680_history_supplement_events.py` | 物理验收后规划/回放 runless materialization；check event 数固定为 0，禁止伪造绿色 check |
| `defs/bootstrap/index_daily_000680_history_supplement_events_cli.py` | 独立 event dry-run/apply 入口 |

命名必须表达真实任务；不得使用 `temp`、`phase`、`fix` 或隐含兼容语义的文件名。

### 5.2 M5 已实施的正式合同

| 文件 | 修改 |
|---|---|
| `seeds/market/major_indices.py` | `EXPECTED_MAJOR_INDICES_COUNT = 11` |
| `seeds/market/major_indices.cn_a.csv` | 追加 rank 11：`000680.SH`，`effective_start_date=2020-01-02` |
| `defs/assets/market_major_indices.py` | 抽取可被正式 asset 与 bootstrap 共用的单分区 Gold writer；不得复制 Gold SQL |
| `tests/test_market_major_indices_seed_contracts.py` | 固定 11 个日级指数、科创综指生效边界和原 10 个顺序不变 |
| Gold readiness/check/sensor 测试 | 覆盖 11 指数有效池与 `000680.SH` 注册门禁 |

`000680.SH` 追加到 rank 11，原因是本轮只增加成员，不重排现有 10 个指数。若未来需要调整业务展示顺序，应单独变更 seed rank 并重新评审 Gold 全历史重建影响。

## 6. Source staging 合同

### 6.1 查询边界

一次 source 提取只允许访问：

```sql
SELECT
  ts_code,
  to_char(trade_date, 'YYYYMMDD') AS trade_date,
  open,
  high,
  low,
  close,
  pre_close,
  change_amount AS change,
  pct_chg,
  vol,
  amount
FROM core_serving.index_daily_serving
WHERE ts_code = '000680.SH'
  AND trade_date BETWEEN DATE '2020-01-02' AND DATE '2025-01-16'
ORDER BY trade_date;
```

实现必须复用当前 `INDEX_DAILY_RAW_COLUMNS` 和 Prod DB attach/resource 合同，不得新建另一套字段常量或直连配置。

### 6.2 staging 与 manifest

run-scoped staging 不能写入正式 Raw/Silver/Gold 路径。建议根目录：

```text
/Volumes/datasource/data_lake_staging/index_daily_000680_history_supplement/run_id={run_id}/
  source/part-000.parquet
  candidate/raw/...
  candidate/silver/...
  candidate/gold/...
  manifest/plan.json
  manifest/source-audit.json
  manifest/raw-audit.json
  manifest/silver-audit.json
  manifest/gold-audit.json
  manifest/events-plan.json
  manifest/checkpoints.json
```

`plan.json` 至少包含：

- run id；
- 固定代码和日期区间；
- expected 1223 dates；
- source row count / distinct dates / key hash；
- 目标 Raw、Silver、Gold 文件列表；
- seed 文件 hash；
- Prod 查询合同 hash；
- 是否涉及 dynamic partition/event 写入；
- 计划创建时的代码 commit；
- 可重复计算的 `plan_hash`。

### 6.3 Source blocking gates

写正式湖前必须全部满足：

1. source 行数 = 1223；
2. distinct trade dates = 1223；
3. source 日期集合 = `trade_calendar` 中目标区间 SSE 开市日集合；
4. 每个日期恰好一行；
5. `ts_code` 全部等于 `000680.SH`；
6. 关键字段无空值；
7. `high >= greatest(open, close, low)`、`low <= least(open, close, high)`；
8. `2025-01-17.pre_close = staged 2025-01-16.close`；
9. plan hash 与 apply 参数完全一致。

任一 gate 失败时，apply 必须在正式湖写入前停止。

## 7. Raw 补录算法

### 7.1 单分区规则

对于每个目标日期：

1. 既有 Raw 文件必须存在；不存在时 fail closed，禁止创建仅含 `000680.SH` 的残缺分区。
2. 读取既有文件，记录行数、字段、主键统计、非目标行 fingerprint。
3. 从 staging 读取该日唯一目标行。
4. 生成候选文件：`existing WHERE ts_code <> '000680.SH' UNION ALL target_row`。
5. 候选文件必须按 `ts_code` 排序，字段顺序/类型严格等于 `RAW_INDEX_DAILY_SCHEMA`。
6. 候选通过验收后，用临时文件 + `os.replace()` 原子替换正式文件。

候选 SQL 语义：

```sql
SELECT *
FROM read_parquet(existing_raw_path)
WHERE ts_code <> '000680.SH'
UNION ALL
SELECT *
FROM read_parquet(source_staging_path)
WHERE ts_code = '000680.SH'
  AND trade_date = target_trade_date
ORDER BY ts_code;
```

### 7.2 非目标数据保护

每个分区必须证明：

- 替换后 `000680.SH` 恰好 1 行；
- 首次补录时 `after_row_count = before_row_count + 1`；
- 幂等重跑时 `after_row_count = before_row_count`；
- 所有非目标代码的 key/value fingerprint 在替换前后完全一致；
- schema、日期和 key uniqueness checks 全绿。

禁止仅比较总行数。总行数一致不能证明其他代码未被篡改。

### 7.3 候选校验、原子提升与失败恢复

本任务不创建文件备份。每个正式文件只能通过“生成候选文件 -> 完整校验 -> 原子提升”进入正式湖：

1. 候选文件写入 `/Volumes/datasource/data_lake_staging/index_daily_000680_history_supplement/run_id={run_id}/candidate/{layer}/...`，不得写入 DG 正式根 `/Volumes/datasource/data_lake`，也不得直接修改正式 Parquet；
2. 提升前必须校验候选文件的 schema、分区日期、主键唯一性、目标行、总行数和非目标 fingerprint；
3. manifest 必须在提升前记录正式路径、候选路径、候选 hash、目标行 hash、非目标 fingerprint 和计划状态；
4. 任一候选校验失败时 fail closed，该文件不得提升；
5. 校验全部通过后，使用同一文件系统上的临时文件和 `os.replace()` 原子替换正式路径；
6. 每次替换后立即验证正式文件 hash 等于候选 hash，再把该文件 checkpoint 标记为 completed；
7. 一个批次全部完成并通过批次审计前，不得删除 source staging、manifest 和 checkpoint。

失败恢复采用向前修复，不恢复旧文件副本：

1. 进程在 `os.replace()` 前终止时，正式路径仍是旧文件；重跑重新生成并校验候选文件；
2. 进程在 `os.replace()` 后终止时，正式路径已是完整新文件；重跑通过目标行 hash、非目标 fingerprint 和 candidate hash 判定该文件已完成；
3. 批次只完成一部分时，从首个未完成 checkpoint 继续；已完成文件必须通过幂等校验，不得重复改变非目标数据；
4. Raw、Silver、Gold 都必须能从冻结 source、正式 helper 和 seed 确定性重建，不允许依赖人工编辑 Parquet；
5. 若正式文件与候选 hash 不一致，立即停止后续提升，保留 staging/manifest，重新生成该分区并完成物理审计后再继续；
6. runless events 只在全部物理文件验收通过后规划，因此文件阶段失败不需要撤销已写事件。

## 8. Silver 重建

Raw 补录成功后，按同一 1223 日期集合调用正式 Silver 归一化 writer：

```python
write_silver_index_daily_partition_from_raw_file(
    connection,
    raw_path=raw_candidate_or_formal_path,
    target_path=silver_candidate_path,
    partition_key=target_date,
)
```

正式 asset 也通过同一 writer 执行。Silver 不新增旁路 SQL，继续复用正式 normalization、冲突重复检测、字段合同和原子替换能力；bootstrap 批次复用同一个 DuckDB connection。

每个 Silver 分区验收：

- `000680.SH` 恰好 1 行；
- `output_row_count = raw_row_count`；
- `(ts_code, trade_date)` 唯一；
- `trade_date` 等于分区日期；
- Raw/Silver 目标行核心字段完全一致；
- 所有正式 Silver blocking checks 通过。

## 9. 日级 seed 与 Gold 重建

### 9.1 Seed 变更

已发布 seed 追加行：

```csv
11,000680.SH,,2020-01-02,
```

必须同时满足：

- 原 rank 1..10 的代码和顺序不变；
- `899050.BJ` 仍在日级 seed；
- `000680.SH` 只在 `2020-01-02` 起 active；
- seed 总数 = 11；
- `index_basic` 能识别 `000680.SH`；当前正式 Silver 已核验存在该代码；
- 正式 Dagster instance 的 `cn_a_index_ts_codes` 包含 `000680.SH`。

### 9.2 为什么 Gold 要重建到最新日期

历史 Raw/Silver 只缺 `2020-01-02..2025-01-16`，但 Gold 从未选择 `000680.SH`。DG Silver 在 `2025-01-17..2026-08-07` 已经有目标行。因此 seed 生效后，Gold 重建范围必须是：

```text
2020-01-02 .. 当前最新、Silver 已 ready 的 SSE 开市日
```

本次审计时为 `2020-01-02..2026-08-07`，共 1599 个交易日。执行时不得写死 `2026-08-07`，应从 formal Silver ready + SSE calendar 交集重新计算并冻结到 plan。

### 9.3 Gold writer

应从 `gold_market_major_indices_daily` 资产中抽取正式单分区 writer，正式 asset 与 bootstrap 共用以下语义：

- 创建 seed 临时表；
- 按 effective date 选择 active seed；
- 检查 Silver 缺失 seed codes；
- 使用 `_major_indices_daily_select_sql()`；
- 原子替换目标 Gold 文件；
- 返回 active seed count、codes、row count、schema。

Bootstrap 禁止复制 Gold SQL，以免正式资产和补录工具产生双重事实源。

### 9.4 后续 `idx_factor_pro` 消费合同

指数技术因子接入尚未实施，但它已经被设计为日级主要指数 seed 的消费者。因此本补录发布后：

- `idx_factor_pro` 的日级对象池、coverage keys 和历史 bootstrap 代码集合必须读取 11 指数 seed；
- 必须同时包含 `899050.BJ` 北证50和 `000680.SH` 科创综指；
- `000680.SH` 的技术因子有效起点必须由源端 `idx_factor_pro` 真实可用日期单独核验，不能直接把本方案的日线起点 `2020-01-02` 当成技术因子起点；
- 分钟技术指标继续读取分钟 Silver 有效池，不得因日级 seed 增至 11 而纳入北证50。

本轮不开发 `idx_factor_pro`，只消除其方案文档中“日级固定 10 个、排除 000680”的旧门禁。

## 10. Dynamic partitions 与事件回放

### 10.1 分区注册

物理文件存在不代表正式 Dagster instance 已注册分区。执行前必须在：

```text
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home
```

只读核验：

1. 1223 个历史日期是否全部存在于 `cn_a_index_trade_days`；
2. `000680.SH` 是否存在于 `cn_a_index_ts_codes`。

只允许补注册实际缺失项。禁止重新创建 partition definition，禁止因为文件存在就跳过 instance 核验。

正式 Dagster instance 查询和注册命令必须在执行前单独列出 exact command，经管理员再次批准后才能运行。

### 10.2 Runless events

事件回放与文件写入分开：

1. 全部 Raw/Silver/Gold 文件完成；
2. 全量物理审计通过；
3. event planner 读取现有 materialization/check 状态；
4. dry-run 输出缺失事件数量、日期样本和 plan hash；
5. 管理员单独批准 exact command；
6. apply 只补缺失或需要校正的事件。

Materialization events 可以覆盖全部被重写分区。Check events 只能在对应物理 check 已实际执行且通过后回放，禁止凭文件存在伪造绿色 check。

事件数量必须由 planner 根据 formal instance 当前状态计算，不能把理论上限直接作为执行数量。理论触及的物理分区为：

- Raw：1223；
- Silver：1223；
- Gold：执行时计算的全历史日期，审计时为 1599。

## 11. 性能与批次设计

Source 只有 1223 行，数据库读取不是瓶颈；主要成本是 4045 个分区文件的候选生成、原子提升和验收：

```text
1223 Raw + 1223 Silver + 1599 Gold = 4045 file promotions
```

执行要求：

1. source 采用一次 bounded query 或等价按年批次，不按 1223 个日期逐次查询 Prod；
2. 文件处理按年份或最多 100 个日期为一批；
3. 每批复用 DuckDB connection，不为每个文件启动新进程；
4. 每批结束写 checkpoint manifest，支持从首个未完成批次恢复；
5. 重跑已完成批次必须幂等；
6. 不通过 Dagster 启动 4045 个历史 runs；
7. runless event 读取 formal instance 时必须批量查询/规划，不做逐分区全历史扫描循环。
8. 每个文件完成候选校验后独立原子提升并立即写 checkpoint；禁止攒到全任务结束后一次性替换。

## 12. 实施里程碑

| Milestone | 工作 | 退出条件 |
|---|---|---|
| M0 合同冻结 | **已完成**：复跑 Prod/Lake/instance 只读审计；冻结日期、行数、seed、文件数和 plan hash | 1223 source dates、1223 Raw/Silver target、1599 Gold target、plan hash 已确认；正式写入为 0 |
| M1 工具开发 | **已完成**：开发 plan/apply/audit/events 四条链路、显式 CLI 和测试 | planner dry-run 不写 formal Lake/instance；专项与既有回归全绿 |
| M2 Source staging | **已完成**：从 Prod 提取 1223 行并生成 manifest | source blocking gates 全绿；正式湖与 Dagster instance 写入为 0 |
| M3 Raw/Silver 样本补录 | **已完成**：只处理 `2020-01-02`、`2022-07-13`、`2025-01-16` | Raw/Silver 候选校验、原子提升、跨层对账和幂等验证通过；Gold/seed/event/partition 写入为 0 |
| M4 Raw/Silver 全量 | **已完成**：分 13 批补齐 1223 个 Raw，并分 13 批重建 1223 个 Silver | 累计 checkpoint、全量哈希、跨层对账和 26 批幂等重跑全部通过；Gold/seed/instance 写入为 0 |
| M5 Seed/Gold | **已完成**：发布 11 指数 seed；先对 M3 三个样本日验证 Gold，再分 16 批重建 1599 个有效 Gold 日期 | 三日样本、1599/1599 累计 checkpoint、active seed coverage/rank 合同和 16 批幂等重跑全部通过；instance/event 写入为 0 |
| M6 全量对账 | **已完成**：重新核验当前 Prod，并对冻结 source staging -> Raw -> Silver -> Gold 执行全链路只读审计 | Prod/source 逐键差集均为 0；source/Raw/Silver 1223 行 fingerprint 相等；Gold 1599 日期 coverage/rank 全绿；正式写入为 0 |
| M7 instance/event | 注册缺失 dynamic keys，补 runless events | 单独审批；event planner 与执行报告一致 |
| M8 收口 | **物理链路最小收口已完成**：更新代码合同、测试、LLD 和 M6 验收证据；M7 观测链路仍单列 | 物理链路无未解释差异；不得用 M8 状态代替 M7 审批与执行 |

M3、M4、M5、M7 都是独立写入审批点；M6 是只读全量跨层对账，已完成但不自动授权 M7 instance/event 写入。

### 12.1 M3 执行冻结

M3 只验证 Raw/Silver 物理补录链路，固定范围如下：

| 维度 | 冻结值 |
|---|---:|
| 指数对象 | 1：`000680.SH` |
| 样本日期 | 3：`2020-01-02`、`2022-07-13`、`2025-01-16` |
| source 行数 | 1223；按目标日期裁剪为每日 1 行 |
| 正式分区替换 | 6：Raw 3 + Silver 3 |
| 候选文件 | 6：Raw 3 + Silver 3 |
| Gold/seed/event/partition 写入 | 0 |
| 原子边界 | 每个候选文件校验通过后独立 `os.replace()` |
| 单次失败重试成本 | 最多重建并重新校验当前 1 个分区文件 |

M3 性能与拒绝门禁：

1. 每个样本日只扫描该日一个 Raw 正式文件、一个 Silver 正式文件和对应候选文件，不扫描 1223 个正式历史分区；
2. source staging 仅 1223 行、约 86 KiB，所有变换使用 DuckDB set operation，不产生可观测 spill；
3. 任一命令选择超过 1 个冻结样本日、正式文件缺失、schema/key/date/目标行校验失败、非目标 fingerprint 变化或候选 hash 漂移时立即停止；
4. Raw 三日全部通过后才允许进入 Silver；Silver 三日全部通过后执行同范围幂等重跑；
5. `run_gold_batch` 在 seed `current_count != target_count` 时的阻断是正式门禁，M3 不得绕过、放宽或用临时 seed 规避；
6. M3 不执行 Dagster 命令，不读取或写入 event/check history，不注册 dynamic partition。

### 12.2 M3 实际验收证据

M3 使用冻结的 `plan_hash=6ccc360fc1432a127c2ad62cbcfb36f88549d52ce33522bd9e1a6ce22ff2a177` 和 source SHA256 `647af89ef8f5f98d7a02a3ee9a6e5864efa88ce853056e542f467308f328117f` 执行。正式结果如下：

| 层 | 日期 | 首次写入前/后总行数 | 幂等重跑前/后总行数 | 目标行 | 重复键 | 非目标 fingerprint | candidate/formal hash |
|---|---|---:|---:|---:|---:|---|---|
| Raw | 2020-01-02 | 795 / 796 | 796 / 796 | 1 | 0 | 不变 | 相等 |
| Raw | 2022-07-13 | 787 / 788 | 788 / 788 | 1 | 0 | 不变 | 相等 |
| Raw | 2025-01-16 | 815 / 816 | 816 / 816 | 1 | 0 | 不变 | 相等 |
| Silver | 2020-01-02 | 795 / 796 | 796 / 796 | 1 | 0 | 不变 | 相等 |
| Silver | 2022-07-13 | 787 / 788 | 788 / 788 | 1 | 0 | 不变 | 相等 |
| Silver | 2025-01-16 | 815 / 816 | 816 / 816 | 1 | 0 | 不变 | 相等 |

终审结果：

1. source、Raw、Silver 三个样本均为 3 行；source -> Raw 匹配 3、差异 0，Raw -> Silver 匹配 3、差异 0；
2. 6 个 candidate 文件与对应正式文件 SHA256 逐一相等，正式路径不存在遗留 `.incoming` 文件；
3. seed SHA256 仍为 `9c4cfd9efedc30584602839319a56ebec20ec4dde0273006a6022ddd887673e1`，与冻结计划一致；
4. 三个样本日 Gold `000680.SH` 行数均为 0；candidate 目录只有 Raw 3 文件和 Silver 3 文件，没有 Gold candidate；
5. 分日期首次审计和幂等审计保存在同一 run 的 `manifest/*-audit-*.json` 与 `manifest/*-idempotency-audit-*.json` 中；
6. 专项 apply/audit 测试共 10 项通过，atomic replace 失败、候选校验失败等故障路径由测试覆盖，未通过破坏正式文件模拟故障。

### 12.3 M4 checkpoint 修正与实际验收证据

M4 开始前先修正了 M3 暴露的覆盖式 checkpoint 问题：

1. `raw-checkpoints.json`、`silver-checkpoints.json` 改为按冻结计划日期顺序保存累计完成集合，不再只保留最近一次 CLI 调用；
2. 每个分区原子提升成功后，立即把新的累计 checkpoint 写入 `.incoming`，再用 `os.replace()` 原子替换正式 checkpoint；checkpoint 替换失败时保留上一版；
3. 恢复执行时校验 checkpoint 的 schema、plan hash、日期集合、路径和审计合同；只对本批将跳过的已完成日期执行 candidate/formal 文件哈希深验，避免 13 个批次重复扫描所有历史文件；
4. M4 全部完成后不限定日期，对两层 1223 条 checkpoint 审计执行一次全量 candidate/formal SHA256 深验；
5. 新增累计续跑、Silver 跨批累计、已完成日期跳过、历史哈希漂移阻断、checkpoint 原子替换失败保护和按批哈希范围测试；专项测试共 24 项通过，Ruff 通过。

M4 继续使用冻结 `plan_hash=6ccc360fc1432a127c2ad62cbcfb36f88549d52ce33522bd9e1a6ce22ff2a177` 和 source SHA256 `647af89ef8f5f98d7a02a3ee9a6e5864efa88ce853056e542f467308f328117f`。checkpoint 修正不改变 source、目标日期、目标路径、字段映射或分区写入算法；本轮执行代码文件 SHA256 为 `6b8a64a543227aad29a94e53c043e13a9f94884f63ecaa2a54cfe93d3700a664`。

正式执行结果：

| 层 | 批次数 | 日期数 | 首次 M4 新 promotion | 最终累计 checkpoint | 幂等重跑批次 | 幂等新增 promotion |
|---|---:|---:|---:|---:|---:|---:|
| Raw | 13 | 1223 | 1222 | 1223 | 13 | 0 |
| Silver | 13 | 1223 | 1222 | 1223 | 13 | 0 |

`2025-01-16` 已存在于 M3 最后一版 checkpoint，因此 M4 首轮每层新增 1222 次 promotion，最终累计 1223 次；其余两个 M3 样本日因旧 checkpoint 未保留累计状态而按幂等算法重新生成并提升，没有增加目标行或改变非目标数据。

全量物理审计：

| 审计项 | Raw | Silver |
|---|---:|---:|
| 正式文件数 | 1223 | 1223 |
| 正式层总行数 | 978623 | 978623 |
| `000680.SH` 行数 | 1223 | 1223 |
| distinct target dates | 1223 | 1223 |
| 重复键 | 0 | 0 |
| 错误日期分区 | 0 | 0 |
| candidate/formal 全量哈希 | 1223/1223 相等 | 1223/1223 相等 |
| 残留 `.incoming` | 0 | 0 |

跨层与禁止项结果：

1. source -> Raw 规范化 1223 行逐行一致，Raw -> Silver 规范化 1223 行逐行一致；
2. Raw 13 批和 Silver 13 批全部幂等重跑，所有报告 `promoted_count=0`；
3. Gold `000680.SH` 目标行仍为 0；没有 `gold-checkpoints.json`，没有 Gold candidate 目录；
4. 日级 seed SHA256 仍为 `9c4cfd9efedc30584602839319a56ebec20ec4dde0273006a6022ddd887673e1`，与冻结计划一致；
5. 没有执行 Dagster 命令，没有写 event/check history，没有注册 dynamic partition；
6. 运行证据保存在同一 run 的 `manifest/m4-raw-batch-*.json`、`manifest/m4-silver-batch-*.json`、`manifest/m4-idempotent-*-batch-*.json` 和 `manifest/m4-raw-silver-audit.json`。

关键 manifest SHA256：

| 文件 | SHA256 |
|---|---|
| `raw-checkpoints.json` | `eab2bd1535781d052eca7036266143004ce48b456a2b47b7b69fc2a62f9150fc` |
| `silver-checkpoints.json` | `2c7d2309e9458f72a464a979e52ac2ebb20daea1e4d290e6e569377d6431d728` |
| `m4-raw-silver-audit.json` | `c5ed55827e41c7978b5e7554b782921c132b7580f5920f639b87895b18e2f669` |

M4 完成后，管理员已单独批准 M5 的 11 指数 seed 发布、三日 Gold 样本和 1599 个 Gold 分区重建；M6 只读对账随后已完成，M7 仍须按独立写入边界审批。

### 12.4 M5 Seed/Gold 实际验收证据

M5 使用独立冻结计划执行，未复用 M2 的 10 指数 seed 计划：

| 维度 | 冻结值 / 结果 |
|---|---|
| plan | `/Volumes/datasource/data_lake_staging/index_daily_000680_history_supplement/run_id=m5-20260809/manifest/plan.json` |
| plan hash | `9682418678919443c9f49a006f8581c3524e09be680b58c29bad0e6401526249` |
| 日级 seed | 11 行；SHA256 `963eeb727f5c1029b8933395a68e3c28084c4e655105cb2b6c15b9300f752bcd` |
| Gold 目标日期 | 1599：`2020-01-02..2026-08-07` |
| 样本日期 | `2020-01-02`、`2022-07-13`、`2025-01-16` |
| 全量批次 | 16；每批最多 100 个交易日，最后一批 99 个 |
| Gold checkpoint | `/Volumes/datasource/data_lake_staging/index_daily_000680_history_supplement/run_id=m5-20260809/manifest/gold-checkpoints.json` |
| checkpoint SHA256 | `73ac747e372482c0a53908f3912230d2b4d85762db575c06506a34c430a13fb6` |

执行与幂等结果：

1. 三个样本日首次执行各 promotion 1 次，紧随其后的幂等重跑各为 0；样本累计 promotion 为 3。
2. 16 个首次全量批次共选择 1599 个日期，新增 promotion 1596；与三个已完成样本合计得到 1599/1599。
3. 16 个全量幂等批次再次选择 1599 个日期，新增 promotion 合计为 0，所有批次 `passed=true`。
4. Gold checkpoint 深验读取 1599 条审计记录，全部通过；candidate 与 formal 文件均存在且 SHA256 逐一相等，最早/最晚日期为 `2020-01-02` / `2026-08-07`。
5. set-based DuckDB 合同核验将每个日期的 active seed 集合与正式 Gold 的 `(trade_date, rank, ts_code)` 逐行对比：expected rows 15726、actual rows 15726、missing 0、unexpected 0、duplicate key groups 0、duplicate rank groups 0、invalid partition rows 0、null rank rows 0。
6. `000680.SH` 在 Gold 中共 1599 行、1599 个 distinct dates，日期范围 `2020-01-02..2026-08-07`。
7. M5 没有修改分钟线 seed、分钟线 source scope、Wealth 首页 10 指数配置；没有执行 Dagster event/check 写入或 dynamic partition 注册。

M5 完成只证明日级 seed 与 Gold 物理合同已收敛；完整的 Prod -> source staging -> Raw -> Silver -> Gold 只读对账证据见下一节。M5 与 M6 均不授权 M7 instance/event 写入。

### 12.5 M6 全链路只读对账与 M8 最小收口证据

M6 使用两份冻结计划和冻结 source 文件执行，未重新生成或替换任何正式数据：

| 维度 | 冻结值 / 结果 |
|---|---|
| M2 source plan | `/Volumes/datasource/data_lake_staging/index_daily_000680_history_supplement/run_id=m2-20260809/manifest/plan.json` |
| M2 source plan hash | `6ccc360fc1432a127c2ad62cbcfb36f88549d52ce33522bd9e1a6ce22ff2a177` |
| source Parquet SHA256 | `647af89ef8f5f98d7a02a3ee9a6e5864efa88ce853056e542f467308f328117f` |
| M5 plan hash | `9682418678919443c9f49a006f8581c3524e09be680b58c29bad0e6401526249` |
| M6 report | `/private/tmp/index_daily_000680_history_supplement_m6_20260809.json` |
| M6 report SHA256 | `71e7397bae5ac1c4defcec877f28c0b893e11a0b45cd58f7d56ffdb88f7dee2b` |
| M6 audit hash | `3cca24c69028e00644828b33da11228f147af97cd7be9cf19381a4279a6741e4` |

只读验收结果：

1. 当前 Prod `000680.SH` 在 `2020-01-02..2025-01-16` 仍为 1223 行、1223 日期，重复键、越界代码和关键字段空值均为 0。
2. 当前 Prod 全量导出与冻结 source staging 逐键比较：`source_only=0`、`prod_only=0`。
3. source、Raw、Silver 均为 1223 行、1223 日期，fingerprint 均为 `a2daf046e03890adb4e7e9f576cf59afaa231e665c589fe408d475fb8e34bd11`。
4. Gold 为 1599 行、1599 日期，fingerprint 为 `b3b3f050f5246066bf43b275bea9fbd4f0510c96995e9f45536f6b6db9e21fdc`；active seed coverage/rank 对账全部通过。
5. 审计共扫描 5245 个文件引用；formal Lake、Dagster DB、dynamic partition、materialization/check event 写入计数均为 0。
6. M8 已据此完成物理链路最小收口；`/private/tmp` 报告是本机临时验收证据，不是正式湖数据，也不替代后续 M7 的独立执行报告。

## 13. 测试门禁

### 13.1 新增测试

已新增：

- `tests/test_index_daily_000680_history_supplement_plan.py`
- `tests/test_index_daily_000680_history_supplement_apply.py`
- `tests/test_index_daily_000680_history_supplement_audit.py`
- `tests/test_index_daily_000680_history_supplement_events.py`

必须覆盖：

1. source 1223 行/日期完整；
2. source 缺日、重复键、空关键字段、越界代码时 fail closed；
3. 既有 Raw 文件缺失时拒绝创建残缺分区；
4. 首次补录总行数 +1；
5. 幂等重跑总行数不变；
6. 非目标代码 fingerprint 前后相等；
7. atomic replace 失败时正式文件不变；
8. 候选文件未通过完整合同校验时拒绝提升，正式文件 hash 与候选 hash 不一致时停止批次；
9. Silver 使用正式 helper，行数/schema/key 与 Raw 一致；
10. seed 恰好 11，保留 899050，新增 000680，原 10 个顺序不变；
11. `000680.SH` 在 2020-01-02 前 inactive、当日起 active；
12. Gold 在每个日期恰好等于 active seed 集合并按 rank 排序；
13. 缺 `cn_a_index_ts_codes` 注册时 Gold fail closed；
14. event apply 在物理审计未通过、plan hash 不匹配或未显式 `--apply` 时拒绝执行；
15. 代码中不存在 Tushare 请求、Prod 写入或分钟 seed 修改。

### 13.2 既有回归

至少运行：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
uv run python -m pytest -q \
  tests/test_market_major_indices_seed_contracts.py \
  tests/test_market_major_indices_checks.py \
  tests/test_market_major_indices_lake_readiness.py \
  tests/test_market_major_indices_input_readiness.py \
  tests/test_market_major_indices_daily_sensor.py \
  tests/test_index_daily_raw_by_date_asset.py \
  tests/test_index_daily_checks.py \
  tests/test_index_daily_raw_file_readiness.py \
  tests/test_silver_index_daily_sensor.py
uv run ruff check src tests
```

再执行仓库规定的 orchestrator 全量静态/定义加载门禁。

M1 当前验证结果：

- 专项测试：18 passed；
- 既有指数日线/主要指数回归：76 passed，7 subtests passed；
- `python -m py_compile`：M1 八个模块与四组测试通过；
- planner dry-run：`should_stop=false`，全部正式写入计数为 0。

M5 当前验证结果：

- 指数日线、主要指数 seed/readiness/check/sensor 与补录 plan/apply/audit 相关回归：101 passed，9 subtests passed；
- M5 目标代码 Ruff 门禁通过；
- `uv run ruff check src tests` 全仓检查仍有 907 项既有跨任务问题，首批包括 `test_suspend_d_sensor.py`、`test_tushare_request_policy.py` 和 wealth turnover 测试；这些文件不属于 M5，未在本轮越界修改；
- 活跃 LLD 与数据集接入模板中的旧测试环境与旧命令口径已清零，统一从 orchestrator 目录通过项目 `uv` 环境执行；
- Gold checkpoint 深验、set-based active seed 合同核验和 16 批幂等重跑结果见第 12.4 节。

## 14. 最终验收矩阵

| 层 | 必须满足 |
|---|---|
| Prod | `000680.SH` 在 `2020-01-02..latest` 对 SSE 开市日零缺口、零重复 |
| Raw | 目标 1223 日各 1 行；非目标 fingerprint 不变；现有尾部 376 行不变 |
| Silver | `2020-01-02..latest` 共 1599 个目标日期且每日 1 行；与 Raw 核心字段一致 |
| Seed | 11 行；保留北证50；科创综指从 2020-01-02 生效；原 10 个 rank 不变 |
| Gold | 每日代码集合等于 active seed；科创综指从 2020-01-02 起存在；rank 唯一有序 |
| Partitions | 所有物理日期已注册；`000680.SH` 已注册到 `cn_a_index_ts_codes` |
| Events | 只回放 planner 确认缺失/需校正的 materialization/check events |
| Wealth | 首页仍由独立 10 指数配置控制，无页面卡片数量变化 |
| Future idx factor | 发布后读取 11 指数日级 seed；技术因子自身起点仍须源端实测 |

## 15. 禁止项

1. 禁止直接启动普通 `raw_index_daily` 全历史 backfill。
2. 禁止删除、清空或重建任何正式数据表、湖目录或 dynamic partition set。
3. 禁止为了本次补录放宽 Raw exact coverage、Gold seed coverage 或 key checks。
4. 禁止用 Python 行循环处理数据内容；数据变换使用 DuckDB set operations。
5. 禁止覆盖非目标代码；必须有 fingerprint 证明。
6. 禁止把日级 seed 与分钟线对象池合并。
7. 禁止移除 `899050.BJ` 或把 Wealth 首页配置改成 11 个。
8. 禁止在物理审计完成前写 runless events。
9. 禁止跳过候选文件完整校验直接替换正式湖文件。
10. 禁止把本 LLD 中的示例命令视为已获执行授权。

## 16. 计划对账

| 用户目标 | LLD 落点 |
|---|---|
| 审计 Prod 已补数据 | 第 2.1 节：1223 日、零缺口、零重复、字段完整、边界连续 |
| 判断是否需要新增 partition | 第 2.2、10.1 节：物理文件已存在；只核验 formal registry，不新增定义 |
| 补 DG 历史数据 | 第 6-8 节：Prod staging -> Raw 单代码 merge -> Silver 正式 helper |
| 科创综指纳入日级主要指数 | 第 9 节：seed 10 -> 11，保留北证50，科创综指 2020-01-02 生效 |
| 不影响首页 10 卡 | 第 1、14、15 节：Wealth 配置独立且不在本轮范围 |
| 安全可恢复 | 第 7.2、7.3、12、13 节：非目标 fingerprint、候选校验、原子提升、逐文件 checkpoint 和幂等续跑 |
| 后续技术因子不漂移 | 第 9.4 节：日级技术因子跟随 11 指数 seed，分钟技术指标仍保持独立对象池 |

## 17. 关联文档

- [指数日线 Raw by-date / Prod DB 迁移 LLD](./dagster-index-daily-raw-by-date-prod-db-migration-low-level-design.md)
- [指数技术数据资产接入方案](./dagster-index-technical-datasets-onboarding-plan-v1.html)
- [指数技术数据资产接入 LLD](./dagster-index-technical-datasets-onboarding-low-level-design-v1.html)
- [Dagster Bootstrap 历史迁移开发模板](../templates/dagster-bootstrap-migration-template.html)
- [Dagster 数据管道性能治理](./dagster-data-pipeline-performance-governance.md)
