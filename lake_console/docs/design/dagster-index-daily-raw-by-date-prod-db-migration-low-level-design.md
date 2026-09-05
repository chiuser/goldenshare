# Index Daily Raw By-Date Prod DB Migration Low-Level Design

> M5 清退边界（2026-09-05）：本文出现的旧 backend service/mapping 是当时字段与实现对照，不是正式模块依赖；旧 Console 代码待 M6 删除。已完成迁移、quarantine、旧 staging 和临时报告路径仅用于追溯，不授权重跑或物理删除。当前正式数据、schema、serving、公式及验收记录保留。

状态：P-1 至 P9C-2 已完成；包括 P8 旧 by-code quarantine 最终物理删除，以及 P9C-2 四个 mixed run 的精确 Dagster 状态治理。`raw_index_daily_update_job_sensor` 与 `silver_index_daily_sensor` 已启用，`2026-06-23` 首个自动 raw+silver 日更已成功。

> **后续单代码历史补录（2026-08-08）：** Prod 已补齐 `000680.SH` 科创综指 `2020-01-02..2025-01-16` 的 1223 个开市日，但 DG 同期 Raw/Silver 文件是“文件存在、目标代码缺行”。该场景不能复用普通 `raw_index_daily` 历史 backfill，因为正式 Raw 会按当前注册代码全集做 exact coverage 并整文件 replace。专用补录、11 个日级主要指数 seed、Gold 全历史重建和 runless event 审批边界，以 [科创综指指数日线历史补录 LLD](./dagster-index-daily-000680-history-supplement-low-level-design.md) 为准。

最新代码落点：

- P1/P2：`c38e0eea feat: add index daily raw by-date asset`
- P4：`63ce2a75 feat: add index daily p4 runless events`
- P5/P6：`b61e052c feat: switch index daily to raw by-date baseline`
- P7：`8886072a feat: remove index daily by-code active source`

## 1. 目标

本 LLD 用于把指数日线 raw 层从当前 `raw_tushare_index_daily_by_code[ts_code]` 迁移为 `raw_index_daily[trade_date]`。

核心口径：

- 历史数据先在当前 Dagster 新湖内做物理布局转换：P0 profiling 扫描到的当时 by-code raw 文件转换为 by-date raw 文件；P0 全量输入样本范围是 `2000-01-04` 到 `2026-06-23`，但当时 `2026-06-23` 只有 10 个 code，不能作为绿色 ready baseline；ready baseline cutoff 候选是 `2026-06-22`。实现不得写死这些日期。
- raw 日更默认数据源切到 prod core DB 后，从当前 Lake `raw_index_daily` 最新已就绪交易日之后的第一个 expected trade date 开始，只读同步 `core_serving.index_daily_serving`；起点由文件事实和交易日历计算，不硬编码具体日期。
- raw 层按交易日分区，路径按 `trade_date` 组织。
- raw 层代码池与 silver 层一致，必须使用运行时 Lake 期望 code set；当前实现的 DG 管理集合是 `cn_a_index_ts_codes` dynamic partitions。
- prod `ops.index_series_active(resource='index_daily')` 必须覆盖运行时 Lake 期望 code set，但不能反向定义 Lake/DG 的同步集合。
- 日更目标交易日的 prod serving 数据没有完整覆盖运行时 Lake 期望 code set 时，不允许发起 Lake 更新；prod 多出来的 code 不阻断，DG 只读取并校验自己本次要的 code。
- raw 只做源镜像和最小归一化，不提前承担 silver 的 `change_amount` 等语义转换。
- 历史 by-date raw 文件正式从当前 DG raw-by-code 文件转换生成；这是同一 Dagster 新湖内的布局重排，不是读取旧 Lake Console 路径，也不是从 prod DB 重拉历史。P3 已完成该物理转换和 final audit，历史完整性以 P3 文件审计报告为准，不再要求为 6792 个历史分区补全 Dagster event。
- P4 只补最近 20 个交易日的 `raw_index_daily` materialization/check 状态，作为日更启动和最近窗口 UI 观测基线；不做全历史 runless event 补录。
- 性能是硬门禁：sensor 热路径不得逐 code 提交 run，不得逐日深扫 Dagster event/check history。

本 LLD 同时记录设计口径和阶段落地事实。P1/P2 已完成基础契约、prod-core-db adapter、`raw_index_daily` asset、两个聚合 checks、新 job、catalog 和测试；P3 已完成 by-code 到 by-date 的 lake 文件生成；P4 已完成最近 20 个交易日 runless event 补录；P5/P6 已完成 by-date raw/silver/sensor/major readiness 切换；P7 已完成旧 by-code active source/catalog 清理；P8 已完成 quarantine 与最终物理删除；P9B-1/P9C-1/P9C-2 已完成旧 Dagster 状态和全部旧 index daily run history 治理。2026-06-24 已启用 raw/silver sensors，并完成 `2026-06-23` 首个自动 raw+silver 日更。

2026-06-23 P3 执行结果：

1. Dagster 状态治理已完成：`index_daily_sensor`、`silver_index_daily_sensor` 为 `STOPPED`，旧 run `626d4822-0070-4434-9121-cca455e4d21b` 为 `CANCELED`，`market_major_indices_daily_sensor` 保持 `RUNNING`。
2. P3 by-date 文件生成已完成：`raw/index_daily/trade_date=<YYYY-MM-DD>/part-000.parquet` 共 6,792 个文件，范围 `2000-01-04` 到 `2026-06-22`，总行数 3,419,656，distinct pair 3,419,656。
3. P3 final audit 结果：source-target pair diff 为 0，source-target row diff 为 0，空 key 为 0，重复 key 为 0，未生成 `trade_date=2026-06-23` 目标目录。
4. P3 没有写 Dagster materialization/check event；P4 已负责最近 20 个交易日的小窗口状态补录。
5. P3 报告路径：`/private/tmp/index_daily_p3_state_governance_20260623_report.json`、`/private/tmp/index_daily_p3_sample_20260623_report.json`、`/private/tmp/index_daily_p3_full_20260623_report.json`、`/private/tmp/index_daily_p3_final_audit_20260623_report.json`。

2026-06-23 P4 执行结果：

1. P4 runless event 工具已在提交 `63ce2a75 feat: add index daily p4 runless events` 中落地，补录目标只允许 `raw_index_daily` 与两个聚合 check：`raw_index_daily_file_contract_check`、`raw_index_daily_code_coverage_check`。
2. P4 plan dry-run 通过：最近窗口为 `2026-05-25` 到 `2026-06-22` 共 20 个交易日，计划 event 上限 60，当前 DG code count/hash 为 `946 / 67b866dac8b5dc2a6450769a852f098e`，failed partition 为 0。
3. sample apply 已写 `2026-05-25`、`2026-06-08`、`2026-06-22` 三个分区，共 9 条 event；sample audit 全部 ready，且 P4 sample 阶段未写入 `raw_index_daily[2026-06-23]` materialization/check。
4. recent-window apply 已补剩余 17 个分区，共 51 条 event；final audit 显示最近 20 个分区全部 ready，P4 结束时未写入 `raw_index_daily[2026-06-23]` materialization/check。该日期随后由 prod-core-db 日更链路在 2026-06-24 重建并补绿。
5. P4 报告路径：`/private/tmp/index_daily_p4_plan_events_20260623.json`、`/private/tmp/index_daily_p4_sample_apply_20260623.json`、`/private/tmp/index_daily_p4_sample_audit_20260623.json`、`/private/tmp/index_daily_p4_recent_window_apply_20260623.json`、`/private/tmp/index_daily_p4_final_audit_20260623.json`。

2026-06-24 P8/P9 执行结果：

1. P8 已把旧 `raw/tushare/index_daily_by_code` 物理目录隔离到 `/Volumes/datasource/data_lake/_quarantine/index_daily_p8/index_daily_by_code_20260624_084707`；原路径已不存在，新 `raw/index_daily` 仍为 6,792 个 by-date parquet，范围 `2000-01-04` 到 `2026-06-22`。报告路径：`/private/tmp/index_daily_p8_dry_run_20260624_084649.json`、`/private/tmp/index_daily_p8_quarantine_apply_20260624_084707.json`、`/private/tmp/index_daily_p8_quarantine_audit_20260624_084731.json`。
2. P9B-1 已清理旧 `raw_tushare_index_daily_by_code` asset/check 状态和旧 `index_daily_sensor` instigator state；post-audit 显示旧 by-code asset event、check execution、asset tag、asset key 和旧 raw sensor instigator 均为 0。报告路径：`/private/tmp/index_daily_p9b_preflight_20260624_085909.json`、`/private/tmp/index_daily_p9b_backup_20260624_085909/manifest.json`、`/private/tmp/index_daily_p9b_apply_20260624_085909_retry1.json`、`/private/tmp/index_daily_p9b_post_audit_20260624_085909.json`。
3. P9C-1 已清理旧 index daily job run history 安全子集：删除 24,766 个 runs、1,600,791 条 event_logs、206,779 条 run_tags、6 条 asset_event_tags。post-audit 显示安全候选全部为 0，旧 job 只剩 4 个含 `silver_index_daily` event 的 protected mixed runs。报告路径：`/private/tmp/index_daily_p9c_preflight_20260624_090926.json`、`/private/tmp/index_daily_p9c_backup_20260624_090926/manifest.json`、`/private/tmp/index_daily_p9c_apply_20260624_090926.json`、`/private/tmp/index_daily_p9c_post_audit_20260624_090926.json`。
4. 2026-07-15 P8 最终删除与 P9C-2 已按单独批准执行：P8 永久删除 947 个 quarantine 文件；P9C-2 删除四个 mixed runs、528 条 event_logs、8 条 run_tags、8 条 asset_event_tags。精确备份与 post-audit 位于 `/private/tmp/index_daily_p8_p9c2_apply_20260715_171747/`；`silver_index_daily` event_logs 仅减少该四个 run 所属的 8 条历史 event。

2026-06-24 首个自动日更执行结果：

1. `raw_index_daily_update_job_sensor` 已在正式 Dagster instance 中启用，instigator `154416` 状态为 `RUNNING`。
2. sensor tick `77115` 在 `2026-06-24 09:31:14 +08:00` 选中 `2026-06-23`：最近窗口 ready baseline 到 `2026-06-22`，`first_not_ready_trade_date` 与 `selected_trade_date` 均为 `2026-06-23`。
3. 自动提交的 raw run `1de17504-b265-42ba-b79c-6187730cb073` 已 `SUCCESS`，job 为 `raw_index_daily_update_job`，partition 为 `2026-06-23`，run key 为 `raw_index_daily:2026-06-23`。
4. raw 文件已生成：`/Volumes/datasource/data_lake/raw/index_daily/trade_date=2026-06-23/part-000.parquet`。文件审计结果为 946 行、946 个 distinct code、946 个 distinct pair，文件内 `trade_date` 全为 `20260623`，空 key 0，重复 key 0，字段顺序符合 `RAW_INDEX_DAILY_SCHEMA`。
5. raw materialization event `6626251` 记录 `source_system=prod_core_db`、`source_table=core_serving.index_daily_serving`、`source_row_count=946`、`expected_code_count=946`、`missing_code_count=0`、`extra_code_count=0`、`duplicate_key_count=0`。
6. 两个 raw blocking checks 均通过并绑定到该 materialization：`raw_index_daily_file_contract_check` 与 `raw_index_daily_code_coverage_check`。
7. `silver_index_daily_sensor` 已跟进触发 `silver_index_daily[2026-06-23]`，run `cc5f0b7f-d8d9-4210-b19b-3a596c8507a8` 已 `SUCCESS`；silver 文件已生成，7 个 silver checks 均为 `SUCCEEDED`。

## 2. 设计修正

相对高层方案，本 LLD 做三个工程级修正：

1. 新正式 job/sensor 使用规范命名：
   - `raw_index_daily_update_job`
   - `raw_index_daily_update_job_sensor`
   - 旧 `index_daily_update_job` 随 `raw_tushare_index_daily_by_code` 删除，不保留别名兼容。

2. 新 raw asset 不再把 `trade_date` 作为 run config 重复传入：
   - `partition_key` 是唯一交易日执行参数。
   - run config 只保留 `source_mode`、`write_mode` 等非分区参数。
   - 避免出现 `partition_key != config.trade_date` 的双日期口径 bug。

3. 新 asset check 名称按长期编码规范使用 `_check` 后缀：
   - 例如 `raw_index_daily_file_contract_check`。
   - 旧 check 名称只作为历史 event 保留，不进入新 readiness。

## 3. 非目标

本专项不做以下事情：

- 不在新链路开发、历史文件转换、runless event 补录和 sensor 启用阶段清理 Dagster DB 里的旧 by-code run/materialization/check event；旧 index daily 状态/事件清理只能在 P9 作为独立治理动作执行。
- 不把 raw 层改成 silver 语义层。
- 不把 Tushare 作为默认正式路径。
- 不在本专项实现 Tushare fallback。
- 不把每个 index code 单独作为 run 单位。
- 不新增 summary asset、readiness asset、manifest、外部状态表。
- 不在 sensor 热路径读取正式 Dagster event history 做补洞判断。
- 不在未完成 runless event 补录前删除旧 by-code 文件。
- 不读取旧 Lake Console 路径生成正式 by-date raw 文件；历史转换只允许使用当前 Dagster 新湖内的 active by-code raw 资产。

## 4. 当前代码审计结论

### 4.1 raw asset 与路径

当前入口：

- `lake_console/orchestrator/src/orchestrator/defs/assets/index_daily.py`
  - `raw_tushare_index_daily_by_code`
  - `RAW_TUSHARE_INDEX_DAILY_BY_CODE_SCHEMA`
  - `IndexDailyRawByCodeConfig`
  - `fetch_tushare_index_daily_by_code_to_raw(...)`
- `lake_console/orchestrator/src/orchestrator/defs/paths.py`
  - `raw_index_daily_by_code_path(...)`
  - `raw_index_daily_by_code_staging_dir(...)`

当前 raw 路径：

```text
raw/tushare/index_daily_by_code/ts_code=<TS_CODE>/part-000.parquet
```

2026-06-23 P0 只读扫描当前 Dagster 新湖得到的 raw-by-code 文件事实：

| 项 | 观测值 |
| --- | ---: |
| 文件数 | 946 个 `part-000.parquet` |
| 行数 | 3,419,666 行 |
| distinct `(ts_code, trade_date)` | 3,419,666 个 |
| distinct `ts_code` | 946 个 |
| distinct `trade_date` | 6,793 个 |
| 日期范围 | `2000-01-04` 到 `2026-06-23` |
| 重复 key / 空 key | 0 / 0 |
| OHLC/pre_close 任一为空 | 369,425 行 |
| 最新输入日 | `2026-06-23`，只有 10 行、10 个 code |
| 最新 full DG coverage 日 | `2026-06-22`，946 个 code、无重复 key、无空 key |

问题：

- 物理组织是 by-code，无法高效服务 by-date sensor 与 silver 日分区。
- 每个 run 只处理一个 index code，历史或日常补洞 run 数过多。
- raw asset 名称、schema 名称、path helper 名称都绑定 Tushare 和 by-code。

### 4.2 silver 依赖

当前 `silver_index_daily`：

- 依赖 `raw_tushare_index_daily_by_code`。
- 使用 `AllPartitionMapping()` 从所有 code 分区读原始文件。
- `materialize_silver_index_daily_partitions_from_raw_by_code(...)` 会枚举所有已注册 code 的 raw by-code 文件，再按目标 trade date 聚合。

问题：

- silver 日分区为了一个日期要扫描全 code raw 文件。
- by-date raw 切换后必须改成只读目标日 raw 文件。

### 4.3 raw checks

当前 raw check 都挂在 `raw_tushare_index_daily_by_code` 上：

- `raw_index_daily_by_code_file_exists`
- `raw_index_daily_by_code_row_count_positive`
- `raw_index_daily_by_code_required_columns_and_types`
- `raw_index_daily_by_code_partition_code_matches`
- `raw_index_daily_by_code_unique_ts_code_trade_date`

问题：

- check 语义是 by-code，不适用于 by-date。
- `partition_code_matches` 需要替换为 `partition_date_matches`。
- raw by-date 还需要覆盖运行时 Lake 期望 code set。历史转换段看 by-code input pair，日更段看 prod serving 对本次 DG code set 的覆盖；不得再引入 `effective_index_codes_for_trade_date` 这类生命周期推断口径。

### 4.4 raw readiness 与 sensor

当前文件：

- `lake_console/orchestrator/src/orchestrator/defs/sensors/index_daily_raw_file_readiness.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/index_daily_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/index_daily_late_arrival_repair.py`

当前逻辑：

- `index_daily_sensor` 先做日期注册缺口检查。
- 再调用 `audit_index_daily_raw_gaps(...)` 检查最近窗口内 code/date pair。
- 再用 `select_index_daily_pending_code_runs(...)` 选出多个 code 级 run。
- 单 tick 最多 `MAX_RUN_REQUESTS_PER_TICK = 500` 个 `RunRequest`。
- run key 形如 `index_daily:{trade_date}:{index_code}` 或 repair attempt 变体。

问题：

- 这是 code 级调度模型，不是 date 级 raw asset。
- sensor cursor 有 `next_pending_offset`、`repair_state` 等 by-code 状态，迁移后必须删除。
- 当前 late-arrival repair helper 是 by-code 专用，不应带入新模型。

### 4.5 silver sensor 与 major indices readiness

当前 `silver_index_daily_sensor.py`：

- 依赖 `audit_index_daily_raw_gaps(...)`。
- 依赖 `check_index_daily_raw_files_for_trade_date(...)`。

当前 `asset_guards/market_major_indices_lake_readiness.py`：

- 使用 `raw_index_daily_by_code_path(...)` 拼所有 code raw 文件，再判断 silver readiness。

问题：

- by-date raw 切换后，这两个隐藏消费者必须同步迁移。
- major indices guard 不能继续从 by-code raw 推导 silver 覆盖。

### 4.6 run config 与 readiness registry

当前文件：

- `run_contracts/configs.py`
  - `build_index_daily_raw_op_config(...)`
  - op key `raw_tushare_index_daily_by_code`
- `defs/sensors/readiness.py`
  - `RAW_INDEX_DAILY_BY_CODE_READINESS_SPEC`
  - `raw_index_daily_by_code_ready_for_code(...)`

问题：

- op key、函数名、readiness spec 均绑定 by-code。
- 新模型必须改为 `raw_index_daily` + trade-date readiness。

### 4.7 catalog

当前 `catalog/lake_assets.py` raw index daily entry：

- asset key 是 `raw_tushare_index_daily_by_code`。
- path 是 by-code。
- source system 是 Tushare。
- contract 是 `source_mirror_by_code`。

问题：

- catalog 展示与新事实源冲突。
- 迁移后 entry 必须改成 prod core DB + by-date raw。

### 4.8 prod DB 现有模式

可复用模式：

- `defs/resources.py::ProdPostgresResource`
- `defs/prod_db/stk_mins.py`
- `lake_console/backend/app/services/prod_core_db.py`
- `lake_console/backend/app/sync/strategies/prod_db_trade_date.py`

已确认要求：

- 使用 DuckDB `ATTACH ... (TYPE POSTGRES, READ_ONLY)`。
- remote SQL 禁止 `select *`。
- 禁止读取 `source/created_at/updated_at`。
- SQL 必须有明确日期过滤。
- 不把生产连接串写入日志、cursor、metadata。
- 已有 backend prod-core-db 字段口径为 `change_amount AS change`，并已覆盖 `index_daily/index_weekly/index_monthly` 三张 `core_serving` 白名单表；Dagster LLD 必须对齐该口径，不得另起一套近义字段契约。
- 但 backend 当前 `build_prod_core_trade_date_query(...)` 只按 trade date/range 查询，不带 DG code set 过滤；它能作为字段白名单和安全口径参考，不能作为 orchestrator 日更运行时直接复用的实现文件。
- 按仓库边界，orchestrator 不得跨区引用 backend sync 文件；需要在 `lake_console/orchestrator/src/orchestrator/defs/prod_db/index_daily.py` 内实现自己的只读 query builder/source gate。

### 4.9 prod DB 只读审计事实

2026-06-23 P-1 执行前只读审计远程 prod DB：

| 项 | 观测值 |
| --- | ---: |
| 本机 Dagster `cn_a_index_ts_codes` dynamic partitions | 946 个 code |
| 本机 DG code set hash | `6f8f560f11cdce10e4cd5a096c64a4c9` |
| 当前 by-date raw 目标路径 | `/Volumes/datasource/data_lake/raw/index_daily` 不存在，`trade_date=*/part-000.parquet` 为 0 |
| `ops.index_series_active(resource='index_daily')` | P-1 执行前 1130 个 code；P-1 active pool 修复后 1216 个 code |
| `ops.index_series_active(resource='index_daily_raw')` | 3052 个 code |
| `ops.index_series_active(resource='index_mins')` | 530 个 code |
| `core_serving.index_daily_serving` distinct code | P-1 执行前 1130 个；P-1 serving 补齐后 1216 个 |
| `core_serving.index_daily_serving` 日期范围 | `2020-01-02` 到 `2026-06-22` |
| 最近 10 个交易日 serving 当日 code | 每日 1126 个 |
| DG code 与 P-1 执行前 prod serving 4 个缺口交集 | 0 个 |
| DG code 不在 prod serving 全历史中的数量 | 86 个 |
| prod serving 全历史 code 不在 DG 中的数量 | 270 个 |
| 上述 86 个在 `ops.index_series_active(resource='index_daily')` 中 | 0 个 |
| 上述 86 个在 `ops.index_series_active(resource='index_daily_raw')` 中 | 86 个 |
| 上述 86 个当前 prod raw 行数 | 2,837 行 |
| 上述 86 个 P-1 写入前 prod serving 行数 | 0 行 |
| 上述 86 个 `core_serving.index_basic.list_date` 范围 | `2023-03-13` 到 `2025-07-21`，仅作审计字段 |
| 已废弃的旧 `list_date` 口径估算 serving 行数 | 47,656 行 |
| 新湖 `silver/index_daily` 中上述 86 个 code 的全量可补 serving 行数 | 154,160 行 |
| 其中早于旧 `list_date` 口径的行数 | 106,720 行 |
| 上述 86 个 P-1 写入前 prod serving 缺口 | 154,160 行 |

P-1 执行前 prod serving 相对 `index_daily` active pool 的缺口：

| ts_code | serving 最后有数日期 | 缺口开始 | 缺口截止 | 缺失交易日数 |
| --- | --- | --- | --- | ---: |
| `480055.CNI` | `2026-05-13` | `2026-05-14` | `2026-06-22` | 27 |
| `480056.CNI` | `2026-05-13` | `2026-05-14` | `2026-06-22` | 27 |
| `480057.CNI` | `2026-05-13` | `2026-05-14` | `2026-06-22` | 27 |
| `931598.CSI` | `2026-05-08` | `2026-05-11` | `2026-06-22` | 30 |

结论：

- 当前 4 个 prod latest serving 缺口不在本机 DG `cn_a_index_ts_codes` 中；若本迁移沿用当前 DG 管理集合，这 4 个缺口本身不阻断 Lake 更新。
- 但 DG 当前有 86 个 code 不在 prod serving 全历史中；prod DB source 尚不能证明覆盖当前 DG 管理集合。
- `index_daily` raw by-date 更新的 code universe 不能凭设计假设为 prod `index_daily` active pool，也不能凭旧 by-code 文件推断；P0 必须记录迁移审计基线，并确认日更运行时 code set 来源。
- serving 当日不齐备时必须阻断 Lake 更新；阻断口径以运行时 Lake 期望 code set 为准。

### 4.10 开发前强制前置步骤：prod active pool 与 86 个 DG 代码历史补齐

本节是本 LLD 的硬门禁。P0 之前必须先完成本节，且最终验收必须全绿。否则禁止进入任何 Dagster/Lake 代码开发。

#### 4.10.1 前置目标

1. prod `ops.index_series_active(resource='index_daily')` 必须包含当前 DG 管理的全部指数日线代码。
2. DG/Lake 日更同步集合仍以运行时 Lake 期望 code set 为准；当前迁移审计基线是本机 Dagster `cn_a_index_ts_codes` 的 946 个 code。
3. prod active pool 只作为 prod source 与 serving 写入门禁，不作为 Lake code universe 的来源。
4. 新增进 prod `index_daily` active pool 的 DG 缺口代码，必须按新湖 `silver/index_daily` 中实际存在的历史 pair 补齐 prod `core_serving.index_daily_serving` 后，才能作为本迁移的 prod source。

#### 4.10.2 只读 dry-run

dry-run 必须生成 `/private/tmp/index_daily_prod_source_baseline_*.json` 或等价报告，报告不得进入 repo。

只读输入：

| 来源 | 读取内容 | 用途 |
| --- | --- | --- |
| 本机 Dagster DB | `public.dynamic_partitions where partitions_def_name='cn_a_index_ts_codes'` | 生成迁移审计基线 |
| prod `ops.index_series_active` | `resource, ts_code, first_seen_date, last_seen_date, last_checked_at` | 审计 `index_daily` 与 `index_daily_raw` resource 差异 |
| prod `core_serving.index_daily_serving` | `distinct ts_code`, bounded row counts | 审计 serving 是否覆盖 DG 集合 |
| prod `core_serving.index_basic` | `ts_code, list_date, exp_date` | 审计基础信息差异；禁止作为本次补数起始日期 |
| 新湖 `silver/index_daily` | `ts_code, trade_date, open, high, low, close, pre_close, change_amount, pct_chg, vol, amount` | 生成本次可补 prod serving 的正式 pair 与字段事实 |
| prod `core_serving.index_daily_serving` | `ts_code, trade_date` bounded counts | 审计 serving 缺口 |

集合对账要求：

1. `dg_codes = cn_a_index_ts_codes`，当前样本为 946 个。
2. `active_missing = dg_codes - prod_index_daily_active_pool`。
3. `serving_missing_codes = dg_codes - prod_index_daily_serving_distinct_codes`。
4. set diff 必须使用 SQL set operation，或将两侧输出统一 `LC_ALL=C sort` 后再比较；禁止直接把不同数据库的 `ORDER BY` 输出交给 `comm`。
5. 当前审计中 `active_missing` 与 `serving_missing_codes` 的核心交集是 86 个；若重新审计数量变化，必须先更新本 LLD，再继续。

补数 pair 选择：

1. `repair_codes = active_missing union serving_missing_codes`，当前审计样本为 86 个。
2. `source_pairs = 新湖 silver/index_daily where ts_code in repair_codes and trade_date <= approved_target_trade_date`。
3. `core_serving.index_basic.list_date/exp_date` 只进入审计报告，用于标记哪些 source pair 早于当前 prod 基础信息；不得过滤 source pair。
4. expected rows 等于 source_pairs 的唯一 `(ts_code, trade_date)` 数量，不再用交易日历和 list_date 生成理论日历。
5. 禁止把 prod raw 当前已有的 `2026-05-06` 到 `2026-06-22` 这 33 个交易日当作历史补齐范围；这只是当前缓存窗口。

P-1 执行前只读样本结论：

- 86 个 code 的 `list_date` 范围是 `2023-03-13` 到 `2025-07-21`，但该字段不再作为补数下限。
- 新湖 `silver/index_daily` 中这 86 个 code 到 `2026-06-22` 的全量可补 serving 行数为 154,160。
- 其中 106,720 行早于旧 `list_date` 口径；这些行应随新湖 silver 全量一起补 prod serving。
- P-1 写入前 prod serving 为 0 行，因此按新口径估算 serving 缺口为 154,160 行。
- prod raw 当前已有 2,837 行，但 P-1 不再要求补齐 prod raw；若未来需要治理 prod raw，必须另起专项方案。

#### 4.10.3 生产修复执行顺序

所有写 prod 的动作都必须单独审批。本 LLD 只记录必须执行的顺序，不授权直接执行。

1. 写入 prod active pool：
   - 向 `ops.index_series_active` 写入缺失 code 的 `resource='index_daily'` 行。
   - `first_seen_date/last_seen_date/last_checked_at` 是审计字段，不参与 Lake 期望集合定义。
   - 审计字段必须来自本次补齐计划的实际 source 覆盖范围和执行时间。
   - 不得把已有 `resource='index_daily_raw'` 行改名或复用为 `resource='index_daily'`。
2. 补齐 prod serving：
   - 本 P-1 的正式补数来源是新湖 `silver/index_daily`，不是 Tushare，也不是 prod raw 当前局部缓存。
   - 写入前必须对新湖 silver 生成 dry-run 报告：source pair 数、待写 pair 数、重复 key、字段空值、早于旧 list_date 的行数、样本行。
   - serving 写入必须保持当前 `index_daily` active gate 的业务含义：待补 code 已在 `ops.index_series_active(resource='index_daily')` 中。
   - 字段映射必须保持 serving 口径：新湖 silver 已提供 `change_amount`，不得再套 raw `change -> change_amount` 转换。
   - 写入目标是 `core_serving.index_daily_serving`，幂等键是 `(ts_code, trade_date)`。
   - 禁止携带 Lake 或 prod 系统字段作为业务事实写入，例如 `source`、`created_at`、`updated_at`。
   - 禁止按 `core_serving.index_basic.list_date` 截断新湖 silver 中已存在的历史日线。
   - 该动作是经审批的一次性 prod serving 修复，不进入 Dagster active source，不新增 Dagster/Lake 代码。
3. 执行后只读审计：
   - 对比新湖 silver source pair 与 prod serving 实际 pair。
   - 对比 DG code set 与 prod `index_daily` active pool。
   - 对比 DG code set 与 prod serving distinct code。

#### 4.10.4 最终验收

必须全部满足：

1. `dg_codes - prod_index_daily_active_pool = empty`。
2. `dg_codes - prod_index_daily_serving_distinct_codes = empty`。
3. 对本次待补 code，`new_lake_silver_index_daily_pairs - core_serving.index_daily_serving_pairs = empty`。
4. prod raw 不作为本次 P-1 最终验收项；若需要治理 prod raw，必须另起专项。
5. 目标交易日 `core_serving.index_daily_serving` 完整覆盖运行时 Lake 期望 code set。
6. 所有缺口、重复 key、字段映射和 row count 差异都有报告；若新湖 source pair 被证明有污染，必须停下单独审计数据来源。

停止条件：

1. prod active pool 仍缺任何 DG code。
2. 历史补齐后 prod serving 仍缺任何新湖 silver 中已存在的 code/date。
3. 补齐计划试图用 prod active pool 反向改写 Lake 期望 code set。
4. 补齐计划需要删除、清空或重建任何业务表。
5. row count、字段映射或重复键无法解释。

#### 4.10.5 2026-06-23 P-1 执行记录

执行范围：

- repair code：86 个，来自 `dg_codes - prod_index_daily_serving_distinct_codes`。
- source：新湖 `/Volumes/datasource/data_lake/silver/index_daily`。
- target：prod `core_serving.index_daily_serving`。
- 未写入：prod `raw_tushare.index_daily`、Lake 文件、Dagster event。

写前 dry-run：

| 项 | 结果 |
| --- | ---: |
| DG `cn_a_index_ts_codes` | 946 |
| DG code set hash | `6f8f560f11cdce10e4cd5a096c64a4c9` |
| prod `index_daily` active pool | 1216 |
| prod serving distinct code | 1130 |
| `dg_codes - prod_index_daily_active_pool` | 0 |
| `dg_codes - prod_index_daily_serving_distinct_codes` | 86 |
| payload rows | 154,160 |
| payload code count | 86 |
| payload distinct pair count | 154,160 |
| payload date range | `2004-12-31` 到 `2026-06-22` |
| duplicate key groups | 0 |
| rows before old `index_basic.list_date` | 106,720 |
| rows with any OHLC/pre_close NULL | 85,600 |
| rows with `change_amount` or `pct_chg` NULL | 42 |

prod schema 复核：

- `core_serving.index_daily_serving` 主键为 `(ts_code, trade_date)`。
- `open/high/low/close/pre_close/change_amount/pct_chg/vol/amount` 均允许 NULL。
- `source/created_at/updated_at` 由 prod 表默认值维护，payload 不携带这些系统字段。

执行结果：

- upserted rows：154,160。
- 写入方式：`insert ... on conflict (ts_code, trade_date) do update`，写前包含 row count、code count、distinct pair、duplicate key、active pool 覆盖检查。

写后验收：

| 项 | 结果 |
| --- | ---: |
| prod serving distinct code | 1216 |
| `dg_codes - prod_index_daily_active_pool` | 0 |
| `dg_codes - prod_index_daily_serving_distinct_codes` | 0 |
| repair code prod serving rows | 154,160 |
| payload/prod missing pair | 0 |
| payload/prod extra pair | 0 |
| payload/prod field diff rows | 0 |
| prod `core_serving.index_daily_serving` total rows | 1,827,704 |
| prod `core_serving.index_daily_serving` code count | 1216 |
| `2026-06-22` prod serving code count | 1212 |
| `2026-06-22` DG missing code count | 0 |
| `2026-06-22` prod extra vs DG code count | 266 |

主要报告文件位于 `/private/tmp`：

- `index_daily_p1_20260623_silver_repair_dry_run_summary.tsv`
- `index_daily_p1_20260623_silver_repair_payload.tsv`
- `index_daily_p1_apply_serving_from_silver_20260623.sql`
- `index_daily_p1_20260623_after_apply_field_diff_summary.tsv`
- `index_daily_p1_20260623_target_date_coverage_after_apply.tsv`

## 5. 新资产契约

### 5.1 asset

新增正式 raw asset：

```text
raw_index_daily
```

Partition：

```text
cn_a_index_trade_days
```

物理路径：

```text
raw/index_daily/trade_date=<YYYY-MM-DD>/part-000.parquet
```

staging 路径：

```text
raw/index_daily/_staging/run_id=<RUN_ID>/trade_date=<YYYY-MM-DD>/part-000.parquet
```

删除旧入口后，正式代码中不得再出现：

- `raw_tushare_index_daily_by_code`
- `raw_index_daily_by_code_path`
- `index_daily_by_code`
- `select_index_daily_pending_code_runs`
- `next_pending_offset`

### 5.2 schema

新增 schema 常量：

```python
RAW_INDEX_DAILY_SCHEMA
```

同步要求：

- `duckdb_sql.py` 中 `INDEX_DAILY_RAW_COLUMNS` 必须改为来自 `RAW_INDEX_DAILY_SCHEMA`；
- `assets/index_daily.py` 中 `INDEX_DAILY_RAW_COLUMN_TYPES` 必须改为来自 `RAW_INDEX_DAILY_SCHEMA`；
- `RAW_TUSHARE_INDEX_DAILY_BY_CODE_SCHEMA` 只能在迁移期旧 by-code 资产和 P3/P4 bootstrap 输入审计中出现；P7 后 active source 不得继续引用。

字段保持 raw 源镜像口径：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ts_code` | `VARCHAR` | 指数代码 |
| `trade_date` | `VARCHAR` | `YYYYMMDD` 或规范化后的 raw 字符串日期，raw 层不转 DATE |
| `close` | `DOUBLE` | 收盘 |
| `open` | `DOUBLE` | 开盘 |
| `high` | `DOUBLE` | 最高 |
| `low` | `DOUBLE` | 最低 |
| `pre_close` | `DOUBLE` | 昨收 |
| `change` | `DOUBLE` | 涨跌额，raw 层保留源字段名 |
| `pct_chg` | `DOUBLE` | 涨跌幅 |
| `vol` | `DOUBLE` | 成交量 |
| `amount` | `DOUBLE` | 成交额 |

约束：

- raw 层不得把 `change` 提前改名为 `change_amount`。
- raw 层不得把 `trade_date` 提前转成 `DATE`。
- silver 层继续负责 `change -> change_amount` 和日期类型转换。

### 5.3 source system

新增 source system：

```python
SourceSystem.PROD_CORE_DB = "prod_core_db"
```

catalog ingestion source 不新增近义枚举，优先复用现有：

```python
IngestionSource.PROD_DB_READONLY
```

catalog 不能继续使用 `_tushare_raw_entry(...)` 或 `_derived_entry(...)` 生成 `raw_index_daily` entry：

- `_tushare_raw_entry(...)` 会自动写 `SourceSystem.TUSHARE`、`DataContractSource.TUSHARE_RAW_CONTRACT`、`IngestionSource.TUSHARE_API`；
- `_derived_entry(...)` 会自动写 `SourceSystem.DERIVED`、`DataContractSource.DERIVED_CONTRACT`；
- 新实现必须新增专用 `_prod_core_raw_entry(...)`，或直接调用 `_entry(...)` 并逐项写完整字段。

本专项不引入 Tushare fallback source mode。

## 6. 指数代码集合与源端完整性门禁

禁止新增名为 `effective_index_codes_for_trade_date(...)` 且基于 `silver_index_basic list_date/exp_date` 的统一 helper。该设计会把“prod source 是否齐备”偷换成“Lake 本地生命周期推断”，与本迁移目标不一致。

新增 DG universe helper：

```python
dg_index_daily_registered_codes(
    connection,
    *,
    instance: dg.DagsterInstance,
) -> tuple[str, ...]
```

职责：

- 只读查询 `cn_a_index_ts_codes` dynamic partitions。
- 输出排序稳定、去重、去空。
- 不读取 `index_daily_raw` 请求池。
- 不读取 `silver_index_basic`。
- 每次日更运行前实时读取，不使用迁移时的静态文件替代 dynamic partitions。
- 返回值用于本次 run/check 的 expected code set；materialization/check metadata 必须记录 `expected_code_count` 与按排序 code 计算的 `expected_code_set_hash`，方便事后解释本次运行使用的 DG code 集合。hash 只做审计，不作为新的事实源。

若用户确认要切换到 prod `index_daily` active pool，必须单独设计 DG dynamic partitions、旧 raw/silver 文件、checks 和 runless events 的迁移，不得只替换 helper。

新增 source completeness helper：

```python
prod_index_daily_source_completeness_for_trade_date(
    connection,
    *,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
    expected_lake_codes: Sequence[str],
) -> SourceCompletenessStatus
```

职责：

- 检查 `core_serving.index_daily_serving[trade_date]` 是否完整覆盖本次运行的 Lake 期望 code set。
- 只对本次期望 code 检查 `(ts_code, trade_date)` 是否唯一。
- 返回 row count、expected code count、actual expected-code count、missing sample、prod extra code count/sample。
- 本次期望 code 缺失、重复 key、超时或查询异常时 fail closed；prod source 存在额外 code 不阻断，只记录为观测信息。若本地查询结果已经按期望 code 过滤后仍出现非期望 code，则视为 SQL/filter bug 并 fail closed。
- 输出排序稳定。

该门禁是日更路径的唯一 prod source 完整性门禁：

- raw by-date coverage check。
- silver index daily coverage check。
- raw/silver readiness。
- prod DB source readiness。

历史转换路径不使用 prod source completeness helper 判定每个历史日期是否应有当前 946 个 code；历史转换的覆盖依据是当前 DG raw-by-code 输入文件中真实存在的 `(ts_code, trade_date)` pair。

## 7. prod DB 日更读取设计

本节只服务日更 raw 写入，不服务历史 by-code 到 by-date 转换。

新增模块：

```text
lake_console/orchestrator/src/orchestrator/defs/prod_db/index_daily.py
```

核心常量：

```python
PROD_INDEX_DAILY_ATTACHED_DATABASE = "prod_core_pg"
PROD_INDEX_DAILY_ATTACH_OPTIONS = "TYPE POSTGRES, READ_ONLY"
PROD_INDEX_DAILY_SOURCE_TABLE = "core_serving.index_daily_serving"
PROD_INDEX_DAILY_SOURCE_COLUMNS = (...)
```

禁止项：

- 禁止 `select *`。
- 禁止读取 `source`、`created_at`、`updated_at`。
- 禁止没有 `trade_date` 过滤。
- 禁止没有 index code 集合约束。
- 禁止把连接串、密码、host 写入 metadata/cursor/log。

### 7.1 remote query

新增 builder：

```python
build_prod_index_daily_remote_query(
    *,
    trade_date: str,
    index_codes: Sequence[str],
) -> str
```

要求：

- `trade_date` 必须是 `YYYY-MM-DD` 或可严格规范化的日期。
- `trade_date` 必须来自日更 selector 选中的目标交易日；历史转换不得调用该 builder。
- `index_codes` 必须非空，数量不得超过当前注册池大小。
- SQL 只投影白名单字段。
- SQL 必须显式 `ORDER BY ts_code`，保证输出稳定。

字段映射在 P0 只读 profiling 后冻结。预期本地 raw 字段映射：

| 本地 raw 字段 | prod DB 字段 |
| --- | --- |
| `ts_code` | `ts_code` |
| `trade_date` | `trade_date` |
| `open` | `open` |
| `high` | `high` |
| `low` | `low` |
| `close` | `close` |
| `pre_close` | `pre_close` |
| `change` | `change_amount AS change` |
| `pct_chg` | `pct_chg` |
| `vol` | `vol` |
| `amount` | `amount` |

当前 prod DB 字段已核验为 `change_amount`，本地 select 必须显式 `change_amount AS change`，不得把 raw schema 改成 `change_amount`。

### 7.2 DuckDB attach

新增 helper：

```python
attach_prod_index_daily_readonly(
    connection,
    prod_postgres: ProdPostgresResource,
) -> None
```

要求：

- 只能通过 `ProdPostgresResource.duckdb_connection_string()` 获取连接串。
- attach options 必须包含 `READ_ONLY`。
- 单测必须断言 attach SQL 不泄漏密码。

### 7.3 source readiness probe

新增 helper：

```python
prod_index_daily_source_readiness_for_trade_date(
    connection,
    *,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
    expected_index_codes: Sequence[str],
) -> SourceReadinessStatus
```

语义：

- 只用于日更 sensor 选中目标日期后的一次有界 probe。
- 只做运行时 Lake 期望 code set 对账、`count(distinct ts_code)`、缺失代码样本、prod extra code 样本、source row count、重复 key 计数。
- 当日 serving code 集合必须完整覆盖运行时 Lake 期望 code set；prod 额外 code 不阻断。
- 不拉全量明细，除非 asset run 真正执行。
- 超时或异常时 fail closed，sensor skip，不提交 run。

性能预算：

- sensor source probe p95 必须小于 10 秒。
- 超过 10 秒时停止开发，改方案，不得把重查询塞进 sensor。

## 8. 日更 raw 写入设计

本节 writer 只负责日更从 prod-core-db 写入 `raw_index_daily[trade_date]`。历史 by-code 到 by-date 转换由第 16 节 bootstrap 模块负责。

新增 writer：

```python
write_raw_index_daily_by_date_from_prod_db(
    context,
    *,
    lake_root: Path,
    connection,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
    index_codes: Sequence[str],
    write_mode: Literal["replace"],
) -> dict[str, Any]
```

步骤：

1. 校验 `trade_date` 与 `context.partition_key` 一致。
2. 校验 `trade_date` 是日更 selector 选中的 expected trade date，不使用固定日期下界。
3. 校验 `index_codes` 非空且全部来自运行时 Lake 期望 code set。
4. attach prod DB readonly。
5. 执行 source completeness gate；若 prod serving 未完整覆盖运行时 Lake 期望 code set，则拒绝写 Lake。
6. 用 remote query 拉取目标日、目标代码池数据。
7. 写入 staging parquet。
8. 在 staging 上执行 raw checks 等价的 preflight：
   - schema。
   - row count > 0。
   - 所有行 `trade_date` 等于 partition date。
   - `(ts_code, trade_date)` 唯一。
   - 覆盖运行时 expected code set，且本地写出行不得包含非 expected code。
9. `os.replace` 原子替换正式 target。
10. 删除 staging。

禁止项：

- 不允许 append。
- 不允许 partial replace 某些 code。
- 不允许成功写出覆盖不全的 raw 文件。
- 不允许在 prod source 不齐备时生成 Lake 文件。
- 不允许 writer 内触发 Dagster event 或 runless event。

## 9. raw asset 与 job

### 9.1 asset definition

新增：

```python
@dg.asset(
    name="raw_index_daily",
    partitions_def=cn_a_index_trade_days,
    metadata={...},
    check_specs=[...],
)
def raw_index_daily(
    context,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    prod_postgres: ProdPostgresResource,
    config: IndexDailyRawConfig,
) -> dg.MaterializeResult:
    ...
```

definition metadata 必须写：

- `source_system=SourceSystem.PROD_CORE_DB`；
- `data_contract="source_mirror_by_date"`；
- `column_schema=RAW_INDEX_DAILY_SCHEMA`；
- `path_template=raw_index_daily_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)`；
- `source_api=None`，因为日更来源是 prod serving table，不是 Tushare API；
- `extra_metadata` 可以记录 `source_table="core_serving.index_daily_serving"`，但不得记录连接串、host、password。

config：

```python
class IndexDailyRawConfig(dg.Config):
    source_mode: Literal["prod_core_db"] = "prod_core_db"
    write_mode: Literal["replace"] = "replace"
```

约束：

- sensor 只使用 `source_mode="prod_core_db"`。
- 本专项不实现 `tushare_fallback`。
- 若未来要引入 fallback，必须单独出方案，不能在本 LLD 中预留半成品配置。

### 9.2 job

新增：

```python
raw_index_daily_update_job
```

selection：

```python
AssetSelection.assets(raw_index_daily) | AssetSelection.checks_for_assets(raw_index_daily)
```

旧：

```python
index_daily_update_job
```

最终删除，不保留别名。

## 10. raw checks

新增 raw by-date blocking check 只能是两个聚合 check：

- `raw_index_daily_file_contract_check`
- `raw_index_daily_code_coverage_check`

禁止把文件存在、行数、schema、分区日期、唯一键拆成多条 blocking check。拆得太碎会给 Dagster DB 产生大量细碎 check event，不增加新语义，只增加事件写入、UI 展示和 readiness 查询负担。

`raw_index_daily_file_contract_check` 聚合以下 raw 文件契约：

1. 目标 by-date 文件存在。
2. 文件行数大于 0。
3. 字段和类型符合 `RAW_INDEX_DAILY_SCHEMA`。
4. 文件内 `trade_date` 全部等于 partition trade date 的 `YYYYMMDD`。
5. `(ts_code, trade_date)` 唯一。

metadata 必须包含：

- `trade_date`
- `file_path`
- `row_count`
- `schema_ok`
- `partition_date_ok`
- `unique_key_ok`
- `failure_reason_counts`
- `failed_contract_items`
- `sample_rows`

`raw_index_daily_code_coverage_check` 是统一覆盖检查，但必须按 partition 所属阶段选择覆盖依据：

1. 历史转换段，覆盖依据是当前 DG raw-by-code 输入文件中真实存在的 `(ts_code, trade_date)` pair；目标 by-date 文件必须与输入 pair 集合一致。
2. 日更段，覆盖依据是第 6 节运行时 Lake 期望 code set 与 source completeness gate 的同一套 code set。

该 check 不读取 `silver_index_basic list_date/exp_date`，也不得把历史日期机械要求为当前 946 个 code。

code coverage metadata 必须包含：

- `trade_date`
- `coverage_basis`
- `expected_code_count`
- `expected_code_set_hash`
- `actual_code_count`
- `missing_code_count`
- `missing_code_samples`
- `extra_code_count`
- `extra_code_samples`
- `file_path`

不得写：

- prod DB 连接信息。
- 全量缺失代码列表。
- 超大 sample。

## 11. silver 改造

### 11.1 asset dependency

`silver_index_daily` 从：

```python
AssetDep(raw_tushare_index_daily_by_code, AllPartitionMapping())
```

改为：

```python
AssetDep(raw_index_daily)
```

默认 partition mapping 即按同一 `trade_date` 分区。

### 11.2 materialization helper

新增：

```python
materialize_silver_index_daily_partition_from_raw_by_date(
    *,
    lake_root: Path,
    trade_date: str,
    connection,
) -> SilverIndexDailyWriteResult
```

读取：

```text
raw/index_daily/trade_date=<trade_date>/part-000.parquet
```

转换：

- `trade_date` raw string -> silver `DATE`
- `change` -> `change_amount`
- 其它字段保持现有 silver schema。

禁止：

- 枚举所有 index code raw 文件。
- 读取旧 by-code path。
- 用 `AllPartitionMapping()`。

### 11.3 silver checks

`silver_index_daily_registered_code_coverage` 改为对齐同日 `raw_index_daily` 文件中的 code set；日更 raw 文件本身已由 prod source completeness gate 保证覆盖运行时 Lake 期望 code set。不得用 `silver_index_basic list_date/exp_date` 重新推导本日应有 code。

不得继续从“旧 by-code raw 文件是否存在”推导 expected code set。

## 12. readiness 改造

### 12.1 raw by-date readiness

新增 helper：

```python
raw_index_daily_lake_readiness_for_trade_dates(
    connection,
    *,
    lake_root: Path,
    trade_dates: Sequence[str],
    expected_index_codes: Sequence[str],
) -> BatchDateReadiness
```

该 helper 服务日常 sensor 热路径，默认只评估从当前 Lake 最新已就绪 `raw_index_daily` 之后开始的最近窗口。历史转换验收由第 16 节 bootstrap audit 承担，不进入日常 sensor。

覆盖 raw check 等价语义：

- file exists。
- row count。
- schema。
- partition date。
- unique key。
- 日更 code coverage，即运行时 Lake 期望 code set。

性能：

- sensor 默认最多 10 个 trade dates。
- 不读取 Dagster instance。
- 不读取 by-code raw；历史转换审计例外在第 16 节 bootstrap 模块中单独约束。
- DuckDB set-based SQL，禁止 Python 行循环逐 row 校验。

### 12.2 silver readiness

更新：

- `silver_index_daily_ready_for_trade_date(...)` 可继续作为 Dagster check readiness。
- sensor 热路径优先使用 lake readiness batch helper。
- major indices guard 使用 by-date silver/raw facts，不读 by-code path。

### 12.3 readiness registry

删除旧：

- `RAW_INDEX_DAILY_BY_CODE_CHECKS`
- `RAW_INDEX_DAILY_BY_CODE_ASSET_KEY`
- `RAW_INDEX_DAILY_BY_CODE_READINESS_SPEC`
- `raw_index_daily_by_code_ready_for_code(...)`

新增：

- `RAW_INDEX_DAILY_CHECKS`
- `RAW_INDEX_DAILY_ASSET_KEY`
- `RAW_INDEX_DAILY_READINESS_SPEC`
- `raw_index_daily_ready_for_trade_date(...)`

## 13. sensor 改造

### 13.1 raw sensor

新增：

```python
raw_index_daily_update_job_sensor
```

逻辑：

1. 读取 expected trade dates，候选日期从当前 Lake `raw_index_daily` 最新已就绪交易日之后开始；历史转换缺口不由 sensor 自动补。
2. 窗口使用 `STK_MINS_CONTINUITY_WINDOW_LIMIT` 同类默认，即当前 10 个交易日；若新增非分钟线常量，则统一命名为 `NON_STK_DAILY_CONTINUITY_WINDOW_LIMIT = 10`。
3. 检查 `cn_a_index_trade_days` registered gap。
4. 无 registered gap 后，调用 raw by-date lake readiness batch helper。
5. 选择 first not-ready date。
6. 如果 not-ready 且 `materialized=False`，做 prod DB source readiness probe。
7. source ready 必须表示 prod serving 当日 code 集合完整覆盖运行时 Lake 期望 code set；只有 source ready 后才提交一个 date-level `RunRequest`。
8. 如果 not-ready 且 `materialized=True, checks_passed=False`，skip，要求人工处理，不自动覆盖。

run key：

```python
build_asset_update_run_key(
    subject="raw_index_daily",
    unit_id=trade_date,
)
```

输出示例：

```text
raw_index_daily:2026-06-18
```

激活门禁：

- `raw_index_daily_update_job_sensor` 在 P3 文件审计、P4 最近 20 个交易日 event baseline、P5/P6 readiness/sensor 切换完成前必须保持 STOPPED，不得接管正式日更；
- sensor 启动时必须能从 P3 `raw_index_daily` 文件事实和 P4 最近窗口 runless event 事实得到最新已就绪 trade date；
- 如果 `raw/index_daily` 目标路径不存在、P3 final audit 未通过、最近 20 个交易日 event baseline 缺失，sensor 必须 fail closed 并返回明确 skip/block reason；
- sensor/readiness 不得要求 6792 个历史分区都有 Dagster materialization/check event；
- first daily target 只能是最新已就绪 trade date 之后的第一个 expected trade date；
- 生产代码不得使用 `2026-06-23`、`2026-06-22` 或任何固定日期作为日更起点。

cursor 必须删除旧字段：

- `selected_codes`
- `next_pending_offset`
- `repair_state`
- `missing_pair_count`

cursor 新字段：

- `selected_trade_date`
- `blocked_component`
- `raw_status`
- `source_status`
- `continuity_status`
- `performance_ms`
- `source_mode`

cursor 瘦身口径：

- cursor 是调度状态路标，不是 readiness 报告、文件审计报告或 asset check metadata 的替代品。
- `continuity_status` 只能写连续性摘要：expected window 起止、expected count、registered count、最早缺失分区、ready through、first not ready、selected date、blocked reason、扫描文件数和耗时；不得写批量 `status_samples`。
- `raw_status` 只能写目标日期判断所需的最小字段：ready/materialized/checks、reason、failed/missing check names、缺文件数量或首个样本、row/code/key/date 关键计数和少量失败样本；不得写完整 schema/type 明细、完整 summary 或全量路径列表。
- `source_status` 只写 prod source readiness 的最小证据：ready/reason、expected/returned/source row count、missing/extra/duplicate/null/date mismatch count、code set hash、少量 missing/extra code 样本和扫描错误。
- 禁止把 `raw_batch_status.to_cursor_details()`、完整 batch readiness、重复 readiness 结构或长 metadata payload 写入 `raw_index_daily_update_job_sensor` cursor。

### 13.2 silver sensor

更新 `silver_index_daily_sensor.py`：

- raw gate 改为 raw by-date readiness。
- 不再调用：
  - `audit_index_daily_raw_gaps(...)`
  - `check_index_daily_raw_files_for_trade_date(...)`
  - `raw_index_daily_by_code_path(...)`
- selected target 的 raw by-date ready 后再提交 silver run。

### 13.3 删除 by-code late-arrival selector

最终删除：

- `index_daily_late_arrival_repair.py`
- 相关测试和 cursor contract。

新模型下：

- 缺 raw 文件：raw sensor 提交 date-level run。
- raw 文件存在但 check 不绿：不自动重跑，人工处理。
- prod DB late arrival 若需要覆盖已存在 raw 文件，必须由人工启动 `raw_index_daily_update_job[trade_date]`，不由 sensor 自动覆盖。

## 14. major indices readiness 改造

更新：

```text
asset_guards/market_major_indices_lake_readiness.py
```

要求：

- 不再导入 `raw_index_daily_by_code_path`。
- 不再枚举 by-code raw 文件。
- silver readiness 覆盖使用运行时 Lake 期望 code set、同日 raw by-date code set，或 silver check 等价逻辑。
- major indices 只关心 silver 是否可消费，不反向依赖旧 raw 布局。

## 15. catalog 改造

更新 `catalog/lake_assets.py`：

raw index daily entry：

| 字段 | 新口径 |
| --- | --- |
| asset key | `raw_index_daily` |
| partition set | `cn_a_index_trade_days` |
| path | `raw/index_daily/trade_date=<date>/part-000.parquet` |
| source system | `SourceSystem.PROD_CORE_DB`，覆盖全量 `raw_index_daily`，包括历史转换段和日更段 |
| data contract source | `DataContractSource.PROD_SERVING_CONTRACT` |
| data contract | `source_mirror_by_date` |
| ingestion sources | `(IngestionSource.PROD_DB_READONLY,)` |
| default daily ingestion source | `IngestionSource.PROD_DB_READONLY` |
| bootstrap sources | `()`，历史 by-code 只作为物理转换输入，不写入该机器字段 |
| event policy | `EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL` |
| write policy | `WritePolicy.PARTITION_FILE_ATOMIC_REPLACE` |
| freshness | daily trade-date asset |
| checks | 第 10 节新 check names |

实现约束：

- `LakeAssetCatalogEntry.source_system` 是单值机器字段；本资产全量统一写 `PROD_CORE_DB`。
- `LakeAssetCatalogEntry.data_contract_source` 也必须是单值机器字段；本资产统一写 `PROD_SERVING_CONTRACT`，不得写 `TUSHARE_RAW_CONTRACT`。
- `ingestion_sources = (IngestionSource.PROD_DB_READONLY,)`。
- `default_daily_ingestion_source = IngestionSource.PROD_DB_READONLY`。
- `bootstrap_sources` 不用于表达历史 by-code 来源；如无其它正式业务 bootstrap source，可保持空 tuple。
- notes 和 materialization metadata 只能记录 `bootstrap_method=by_code_layout_conversion`、输入摘要、审计报告路径等迁移证据；不得把当前 DG `raw_tushare_index_daily_by_code`、Tushare 或 `DERIVED_FROM_ASSETS` 写成 `raw_index_daily` 的 source system。
- 不能通过 `_tushare_raw_entry(...)` 或 `_derived_entry(...)` 偷懒生成 entry；这两个 helper 会把机器字段写错。
- 旧 `raw_tushare_index_daily_by_code` entry 删除。

## 16. 历史 by-code 到 by-date 文件转换

新增 bootstrap 模块：

```text
defs/bootstrap/index_daily_raw_by_date_history.py
defs/bootstrap/index_daily_raw_by_date_history_cli.py
```

命令阶段：

1. `plan-files`
2. `write-sample-files`
3. `audit-sample-files`
4. `write-files`
5. `audit-files`

转换输入：

1. 正式输入只能是当前 Dagster 新湖内的 active `raw_tushare_index_daily_by_code[ts_code]` 文件。
2. 输入路径是 `raw/tushare/index_daily_by_code/ts_code=<TS_CODE>/part-000.parquet`，位于同一个 `DEFAULT_LAKE_ROOT=/Volumes/datasource/data_lake` 下。
3. 转换范围由 P0 profiling 扫描当前 DG raw-by-code 文件得到；当前全量输入样本是 `2000-01-04` 到 `2026-06-23`，ready baseline cutoff 候选是 `2026-06-22`，实现不得写死该范围。
4. code universe 是当前 DG `cn_a_index_ts_codes` 的 946 个 code；历史每个 trade date 的实际 code set 以 by-code 输入文件中存在的 `(ts_code, trade_date)` pair 为准。
5. prod DB 不参与历史转换；prod `ops.index_series_active(resource='index_daily')` 和 `core_serving.index_daily_serving` 只约束日更 source。
6. P0 样本中的 `2026-06-23` 是尾部半截日期，只有 10 个 code；除非另行审批，不得写绿色 ready baseline event。

禁止：

- 不允许读取旧 Lake Console 路径，例如 `/Volumes/datasource/goldenshare-tushare-lake/raw_tushare/index_daily/**`。
- 不允许从 prod DB 重拉历史来生成 by-date 文件。
- 不允许在新 bootstrap 中复用旧 by-code writer/check 作为正式写入逻辑；可以复用字段契约、path helper 和只读 SQL 片段。
- 不允许把 by-code input file list 全量写入 Dagster materialization metadata；只记录 input summary、`bootstrap_method=by_code_layout_conversion` 和报告路径。metadata 中的 source system 仍为 `PROD_CORE_DB`。

生命周期：

- P3/P4 期间，bootstrap 模块是唯一允许在 active source 中出现旧 by-code path/symbol 的范围；
- 该允许范围只服务历史转换和 runless event 补录，不得被 sensor、asset、check、catalog 或 readiness 引用；
- P7 必须删除 bootstrap 模块，或移动到不参与 active production static gate 的离线工具目录；
- P7 后 `src/orchestrator/defs/**` 旧 by-code symbol 扫描必须为 0。

生成 SQL：

- 用 DuckDB `read_parquet(..., hive_partitioning=false, union_by_name=true)` 批量读取当前 by-code parquet 文件。
- 按批次构造 input facts：`ts_code`、`trade_date`、行情字段。
- 每个目标日期的 expected code set 来自该日期在 input facts 中出现的 `ts_code` 集合。
- 按 `trade_date` 写 by-date parquet。
- 禁止 Python row loop。

批次建议：

- 按年份或月份切批。
- 单批输出文件数不超过 250。
- 单批内存峰值必须记录。

验收：

- by-date 总 row count 等于 by-code input 总 row count。
- by-date `(ts_code, trade_date)` pair 集合等于 by-code input pair 集合。
- `(ts_code, trade_date)` 唯一。
- 每个输出日期满足 raw by-date checks。
- 每个输出日期 code set 等于 by-code input 中该日期的 code set；不能要求历史日期都有当前 946 个 code。
- 异常日期输出 CSV 到 `/private/tmp`，不得进入 repo 或 lake。

## 17. runless event 补录

新增 bootstrap 模块：

```text
defs/bootstrap/index_daily_raw_by_date_runless_events.py
defs/bootstrap/index_daily_raw_by_date_runless_events_cli.py
```

命令阶段：

1. `plan-events`
2. `report-sample-events`
3. `audit-sample-events`
4. `report-recent-window-events`
5. `audit-recent-window-events`

补录对象：

- 最近 20 个交易日的 `raw_index_daily[trade_date]` materialization。
- 最近 20 个交易日的第 10 节 raw checks。

P4 不再补录全历史 6792 个分区的 runless event。P3 final audit 已经证明全历史文件事实完整；把 6792 个 materialization 和 13,584 个 check event 全写进 Dagster DB，只增加 event log 体积和 readiness 查询负担，不增加日更正确性。

事件量级估算：

| 类型 | 数量估算 |
| --- | ---: |
| materialization，最近 20 个交易日 | 20 |
| checks，最近 20 个交易日 × 2 | 40 |
| 总计 | 约 60 |

要求：

- 必须先 dry-run，生成最近 20 个交易日待写清单，并在报告里保留全历史 20,376 event 估算作为“不执行”的容量证据。
- sample 阶段最多 5 个 trade dates。
- recent-window 阶段只提交最近 20 个 trade dates 的缺失 event。
- 每个 check event 必须绑定本轮 materialization target。
- 不允许写 green check event，除非本地 raw by-date check 等价逻辑已经通过。
- 历史转换段最近窗口内的 `raw_index_daily_code_coverage_check` event metadata 必须写 `coverage_basis=by_code_source_pairs`。
- 禁止因为某个历史分区缺 materialization/check event，就自动扩展为全历史补录。
- 禁止补录旧 `raw_tushare_index_daily_by_code` 的新 event。

P4 不清理旧 Dagster event 的理由：

- Dagster event log 是历史审计账，不是当前 asset 事实源。
- 删除旧 event 风险高，必须有独立 dry-run、边界、备份和审批。
- 新 sensor/readiness/catalog 只读取 `raw_index_daily`，旧 by-code event 不参与新链路。
- 旧 asset definition 删除后，UI 中旧 event 只作为历史记录存在。
- 旧 index daily 状态/事件清理如确有需要，只能进入 P9，不能和 runless event 补录混在一起。

## 18. 旧 by-code 文件删除

删除旧 lake 文件必须单独审批，不与代码迁移混在一个开发阶段。

删除前置条件：

- by-date raw 文件全量 audit 通过。
- runless materialization/check event audit 通过。
- `silver_index_daily` 已切到 by-date raw。
- `raw_index_daily_update_job_sensor` 已切到 by-date raw。
- 正式代码 `src/**` 不再引用旧 by-code path。

删除范围：

```text
raw/tushare/index_daily_by_code/**
```

不得删除：

- Dagster DB 旧 event，P8 只处理 lake 物理文件。
- run history。
- 旧报告文件，除非用户明确要求。

### 18.1 旧 index daily Dagster 状态/事件清理

P9 是可选的独立治理阶段，不是新 by-date raw/silver 日更链路的启用条件。只有在 P7 active source 清零、P8 物理旧文件处理完成或明确延期、并且新 readiness/sensor/catalog 只读取 `raw_index_daily` 和 `silver_index_daily` 后，才允许评估 P9。

P9 候选清理对象只能通过精确名称和边界选出：

- 旧 `raw_tushare_index_daily_by_code` materialization event。
- 旧 raw-by-code check event。
- 旧 `index_daily_update_job` run 记录。
- 已删除旧 sensor 的 cursor/state。
- P8 已删除的 `raw/tushare/index_daily_by_code/**` 路径对应的旧观测记录。

P9 禁止删除：

- `cn_a_index_ts_codes` dynamic partitions。
- `cn_a_index_trade_days` dynamic partitions。
- 新 `raw_index_daily` materialization/check event。
- `silver_index_daily` 历史。
- prod DB 中任何 raw、core、serving、active pool 数据。
- 新 by-date lake 文件或历史转换报告。

P9 执行规则：

1. 必须先生成 dry-run 报告，列出候选对象类型、精确名称、storage id 或时间范围、预计数量、样本和保留对象。
2. 必须证明候选对象与新 readiness helper、sensor cursor、asset selection、catalog、run contract 无交集。
3. 必须有备份或回滚方案；没有安全回滚时，只允许归档/忽略旧记录。
4. 禁止宽泛清空 Dagster event history，禁止按 asset group、时间段或表级条件误删非 index daily 数据。
5. 用户单独审批后，可以使用“只读 preflight -> 文件备份 -> 单事务精确 SQL -> post-audit”的治理方式；SQL 必须固定精确 asset/check/job/run id 候选和删除数量断言，不得用宽泛时间段或表级条件强行清理。
6. 如果新链路必须依赖 P9 清理才能运行，说明 P1-P7 仍有旧依赖，必须回退到设计修正。

## 19. 性能门禁

### 19.1 sensor

| 场景 | 预算 |
| --- | ---: |
| raw sensor 稳定态 | < 5s |
| raw sensor 缺文件 + prod source probe | < 10s |
| silver sensor 稳定态 | < 5s |
| raw/silver readiness 窗口 | 10 trade dates |
| Dagster event history 读取 | 0 |
| 每 tick RunRequest 数 | 0 或 1 |

超过预算必须停下调方案，不允许把 timeout 作为解决方式。

### 19.2 raw asset run

| 场景 | 预算 |
| --- | ---: |
| prod DB 单日读取 | < 60s |
| 单日 raw write | < 10s |
| 单日 rows | 约运行时 Lake 期望 code count |

如果 prod DB 单日读取超过 60s：

- 先 profile SQL 和索引条件。
- 不允许退回每 code 多 run。
- 不允许在 sensor 热路径拉明细。

### 19.3 历史转换

| 场景 | 预算 |
| --- | ---: |
| 单批输出 partitions | <= 250 |
| 单批 DuckDB SQL | set-based |
| Python row loop | 0 |
| Dagster event 写入批次 | <= 250 partitions |

## 20. 静态门禁

更新 `tests/test_run_contract_static_gates.py`：

生产代码禁止：

- `raw_tushare_index_daily_by_code`
- `raw_index_daily_by_code_path`
- `index_daily_by_code`
- `select_index_daily_pending_code_runs`
- `next_pending_offset`
- `run_key` 中拼接 `index_code`
- `MAX_RUN_REQUESTS_PER_TICK = 500` 这类 code fan-out 模型
- sensor 里调用 `get_event_records` 判断 raw/silver readiness
- 生产代码中硬编码 `2026-06-22`、`2026-06-23` 作为迁移终点、日更起点或 cutover 日期

允许范围：

- 历史 bootstrap 模块在 P3/P4 可以且只能把当前 DG 新湖 by-code 文件作为正式只读输入，转换写入新 raw by-date；禁止旧 Lake Console 路径。P7 后 bootstrap 代码必须删除或移出 active source，避免旧 by-code path 继续留在生产代码扫描范围内。
- 测试 fixture 可以包含旧字符串作为负向样本。
- 设计文档可以描述旧口径，但必须明确是历史/待删除。
- 审计报告、测试 fixture 和设计文档可以包含 `2026-06-22`、`2026-06-23` 作为样本事实；production runtime 逻辑不得依赖这些日期。

新增门禁：

- `raw_index_daily_update_job_sensor` 每 tick 最多一个 `RunRequest`。
- raw index daily run key 必须经统一 builder。
- prod DB SQL builder 单测禁止 `select *` 和 forbidden columns。
- runless event CLI dry-run 路径不得调用 `report_runless_asset_event(...)`。
- `raw_index_daily_update_job_sensor` 在 by-date baseline 缺失时必须 skip/block，不得猜测 first target。
- raw index daily blocking check 名称只能是 `raw_index_daily_file_contract_check` 和 `raw_index_daily_code_coverage_check`；禁止重新引入 `file_exists/row_count/schema/partition_date/unique_key/registered_code_coverage/expected_code_coverage` 等细碎 raw check 名称。

## 21. 测试计划

### 21.1 prod DB SQL contract

新增：

```text
tests/test_index_daily_prod_db_contracts.py
```

覆盖：

- remote SQL 显式列。
- 必须包含 trade_date 过滤。
- 必须包含 code set 过滤。
- 禁止 forbidden columns。
- attach readonly。
- 不泄漏连接串。

### 21.2 raw by-date asset/checks

更新/新增：

```text
tests/test_index_daily_checks.py
tests/test_index_daily_raw_by_date_asset.py
```

覆盖：

- by-date path。
- schema。
- partition date。
- unique key。
- 运行时 Lake 期望 code coverage。
- raw file 契约收敛在 `raw_index_daily_file_contract_check`，coverage 收敛在 `raw_index_daily_code_coverage_check`。
- file contract metadata 能说明文件缺失、空文件、schema 错、日期错、重复键的具体子项和样本。
- prod DB source field mapping。
- `change` raw 字段保持不被提前改名。

### 21.3 silver

更新：

```text
tests/test_silver_index_daily_sensor.py
tests/test_silver_index_daily_asset.py
```

覆盖：

- silver 只读目标日 raw by-date。
- 不读 by-code raw。
- coverage 使用运行时 Lake 期望 code set 或同日 raw by-date code set。
- `change -> change_amount` 仍在 silver 层完成。

### 21.4 sensors

更新：

```text
tests/test_index_daily_sensor.py
tests/test_sensor_cursor_contracts.py
```

覆盖：

- raw sensor first-not-ready date。
- raw file missing 提交一个 date-level run。
- raw materialized but checks failed skip，不自动覆盖。
- prod source not ready skip。
- cursor 不再包含 selected_codes/next_pending_offset。
- run key 不含 index code。

### 21.5 major indices

更新：

```text
tests/test_market_major_indices_lake_readiness.py
```

覆盖：

- 不导入 by-code raw path。
- readiness 只使用 by-date raw/silver facts。
- 缺 silver 仍 fail closed。

### 21.6 bootstrap/runless

新增：

```text
tests/test_index_daily_raw_by_date_history_bootstrap.py
tests/test_index_daily_raw_by_date_runless_events.py
```

覆盖：

- dry-run 不写 event。
- sample/full audit。
- runless check event 绑定 materialization。
- 每个 partition 只补 `raw_index_daily_file_contract_check` 和 `raw_index_daily_code_coverage_check` 两个 raw check event。
- 超过 batch 上限 fail closed。
- 当前 DG by-code path 只允许在历史转换 bootstrap 的只读输入路径中出现；旧 Lake Console 路径禁止出现。

## 22. 开发阶段

### P-1：prod active pool 与 DG 缺口代码历史补齐

目标：

- 完成第 4.10 节的 prod source 基线修复。
- 确认 prod `ops.index_series_active(resource='index_daily')` 覆盖 DG 当前 946 个指数日线代码。
- 将当前 DG 缺口代码在新湖 `silver/index_daily` 中实际存在的历史 pair 补齐到 prod `core_serving.index_daily_serving`；不按 `core_serving.index_basic.list_date` 截断。
- 形成最终只读验收报告。

禁止：

- 不改 Dagster/Lake 代码。
- 不写 lake。
- 不写 Dagster event。
- 不把 prod active pool 作为 Lake code universe。
- 不把当前 33 个 prod raw 缓存交易日当作历史补齐范围。
- 不把 prod raw 作为本阶段必补目标。
- 不按 `index_basic.list_date` 截断新湖 silver 中已存在的指数日线。

输出：

- `/private/tmp/index_daily_prod_source_baseline_*.json`
- `/private/tmp/index_daily_prod_source_repair_audit_*.json`
- 如果该阶段任一验收项不通过，停止本迁移，不进入 P0。

### P0：只读 profiling 与契约基线

目标：

- 验证 prod DB `core_serving.index_daily_serving` 字段。
- 验证 `change` 字段映射。
- 验证本机 Dagster `cn_a_index_ts_codes`、prod `ops.index_series_active(resource='index_daily')`、prod `core_serving.index_daily_serving` 三个 code set 的覆盖关系。
- 记录本迁移 Lake code set 审计基线，并确认日更运行时读取 `cn_a_index_ts_codes` dynamic partitions。
- 验证 source completeness gate 对本次期望 code 缺失、重复 key、source 异常均 fail closed；prod 额外 code 不阻断。
- 测单日 prod source probe 和 full read 耗时。
- 只读扫描当前 DG raw-by-code 文件，估算历史转换 trade dates、row count、event count。

禁止：

- 不写代码。
- 不写 Dagster。
- 不写 lake。

输出：

- `/private/tmp/index_daily_p0_20260623_dg_code_summary.tsv`
- `/private/tmp/index_daily_p0_20260623_code_set_summary.tsv`
- `/private/tmp/index_daily_p0_20260623_prod_serving_schema.tsv`
- `/private/tmp/index_daily_p0_20260623_prod_serving_summary.tsv`
- `/private/tmp/index_daily_p0_20260623_prod_serving_latest_summary.tsv`
- `/private/tmp/index_daily_p0_20260623_by_code_summary.tsv`
- `/private/tmp/index_daily_p0_20260623_by_code_cutoff_candidate.tsv`
- `/private/tmp/index_daily_p0_20260623_by_code_ready_baseline_estimate.tsv`
- 若字段或性能与本 LLD 冲突，先改 LLD。

### P1：基础契约与 path/schema/prod SQL

状态：已完成，提交 `c38e0eea feat: add index daily raw by-date asset`。

目标：

- 新 schema/path helper。
- prod DB query builder。
- DG registered code helper。
- source completeness gate helper。
- 单元测试。

不接入 active sensor。

实际落点：

| 目标 | 当前实现 |
| --- | --- |
| schema | `defs/run_contracts/asset_column_schemas.py` 新增 `RAW_INDEX_DAILY_SCHEMA`；`defs/duckdb_sql.py` 中 `INDEX_DAILY_RAW_COLUMNS` 改由新 schema 派生。 |
| path | `defs/paths.py` 新增 `raw_index_daily_path(...)` 和 `raw_index_daily_staging_path(...)`。 |
| source system | `defs/run_contracts/metadata.py` 新增 `SourceSystem.PROD_CORE_DB`。 |
| prod query builder | `defs/prod_db/index_daily.py` 新增 prod-core-db index daily 只读 contract。remote SQL 显式投影业务字段，映射 `change_amount AS change`，按 `trade_date` 和 DG code set 过滤，禁止 `select *` 和 `source/created_at/updated_at`。 |
| source completeness gate | `defs/assets/index_daily.py::write_raw_index_daily_partition_from_prod_db(...)` 在写文件前校验 source row 非空、空 key、日期/code 越界、重复 key、缺 code 和 extra code；任何失败都不替换正式文件。 |
| code set hash | `defs/prod_db/index_daily.py::index_code_set_hash(...)` 记录本次运行时 DG code set 的稳定 hash；materialization metadata 写 `expected_code_count` 和 `expected_code_set_hash`。 |
| tests | `tests/test_index_daily_prod_db_contracts.py`、`tests/test_index_daily_raw_by_date_asset.py` 覆盖 SQL contract、字段映射、path、writer fail-closed 和 nullable OHLC。 |

实现边界：

- 未访问真实 prod DB。
- 未写正式 lake。
- 未运行 Dagster job/sensor/materialize/check/backfill。
- `source_mode` 暂未暴露为 run config；当前正式路径只有 prod-core-db，`IndexDailyRawConfig` 只保留 `write_mode="replace"`。

### P2：raw by-date asset/check/job

状态：已完成，提交 `c38e0eea feat: add index daily raw by-date asset`。

目标：

- 新 `raw_index_daily` asset。
- 新 checks。
- 新 `raw_index_daily_update_job`。
- config builder 更新。

旧 by-code asset 暂时保留，避免未补历史 event 前切断 silver。

实际落点：

| 目标 | 当前实现 |
| --- | --- |
| asset | `defs/assets/index_daily.py` 新增 `raw_index_daily[trade_date]`，partition 使用 `cn_a_index_trade_days`，definition metadata 写 `SourceSystem.PROD_CORE_DB`、`RAW_INDEX_DAILY_SCHEMA` 和 by-date path template。 |
| checks | `defs/checks/index_daily_checks.py` 新增 `raw_index_daily_file_contract_check` 与 `raw_index_daily_code_coverage_check`。旧 5 个 by-code checks 仍挂在旧 asset 上，P7 删除。 |
| job | `defs/jobs/index_daily_update.py` 新增 `raw_index_daily_update_job`，selection 为 `raw_index_daily` + `checks_for_assets(raw_index_daily)`。旧 `index_daily_update_job` 保留给迁移期现有 sensor。 |
| config | `defs/run_contracts/configs.py` 新增 `IndexDailyRawConfig` 和 `build_raw_index_daily_update_job_run_config(...)`；老 helper 语义不变。 |
| catalog | `defs/catalog/lake_assets.py` 新增 `raw_index_daily` entry，直接使用 `_entry(...)` 写 `PROD_CORE_DB` / `PROD_SERVING_CONTRACT` / `PROD_DB_READONLY` / `SUPPORTS_RUNLESS_EVENT_BACKFILL`。 |
| governance | `tests/test_asset_governance_contracts.py` active asset/catalog 数量从 55 调整为 56，并对账 new asset metadata、tags、column schema、blocking checks。 |
| static gates | `tests/test_run_contract_static_gates.py` 新增 P1/P2 门禁：prod SQL 不准 `select *`、新链路不导出 prod 系统列、不拆碎 by-date checks、不把 sensor 切到新 job、不硬编码 cutover 日期。 |

验证结果：

```text
cd /Users/congming/github/goldenshare/lake_console/orchestrator
uv run python -m unittest \
  tests.test_index_daily_prod_db_contracts \
  tests.test_index_daily_raw_by_date_asset \
  tests.test_index_daily_checks \
  tests.test_run_contract_configs \
  tests.test_asset_governance_contracts \
  tests.test_run_contract_static_gates
```

结果：82 个测试通过。

同时通过：

```text
git diff --check
uv run python -c "from orchestrator.defs.jobs.index_daily_update import raw_index_daily_update_job; print(raw_index_daily_update_job.name)"
```

未执行 `dg check defs`，因为正式 Dagster 环境执行门禁要求单独审批。

P2 当轮后仍未做：

- P2 当轮不包含 `raw_index_daily_update_job_sensor` 启用动作。
- 未切 `silver_index_daily` 依赖。
- 未切 major indices readiness。
- 未删除旧 by-code asset/check/job/sensor/readiness/catalog。
- 未生成历史 by-date raw 文件。
- 未补 runless materialization/check event。

以上是 P2 当轮边界；后续 P3-P9 与 2026-06-24 首个自动日更已经完成对应事项。

### P3：历史 by-code 到 by-date 文件转换

状态：已执行，P3 final audit 已通过，报告见 `/private/tmp/index_daily_p3_final_audit_20260623_report.json`。

目标：

- 从当前 Dagster 新湖 `raw_tushare_index_daily_by_code` dry-run/sample/full 写 by-date raw 历史文件。
- 转换范围来自 P0 profiling 的当前 DG raw-by-code 文件事实；当前全量输入样本为 `2000-01-04` 到 `2026-06-23`，ready baseline cutoff 候选为 `2026-06-22`。
- source/target `(ts_code, trade_date)` pair 必须一致。
- audit 文件完整性。
- 尾部半截日期不得写成绿色 ready baseline；P0 样本中 `2026-06-23` 只有 10 个 code，应由 prod-core-db 日更链路补齐，除非另有明确审批。

需要正式 lake 写入审批。

### P4：runless event 补录

状态：已执行，P4 final audit 已通过，报告见 `/private/tmp/index_daily_p4_final_audit_20260623.json`。

目标：

- dry-run/sample/recent-window 写最近 20 个交易日的 `raw_index_daily` materialization/check event。
- audit 最近窗口 event 与文件一致。
- 不补录 6792 个历史分区的全量 event；全历史正确性引用 P3 final audit。

需要正式 Dagster 写入审批。

### P5：silver 与 major indices 切换

状态：代码实现已完成；后续已启用 sensors，并在 `2026-06-24` 自动完成 `2026-06-23` raw+silver 日更。本阶段当轮未写 lake/prod DB/Dagster event，未启用 sensor。

已落地点：

- `silver_index_daily` 依赖已改为同分区 `raw_index_daily`，不再使用 `AllPartitionMapping()` 读取旧 by-code raw。
- 新增 same-date by-date silver writer：只读 `raw/index_daily/trade_date=<YYYY-MM-DD>/part-000.parquet`，输出既有 silver schema，并执行 `change -> change_amount` 转换。
- `silver_index_daily_registered_code_coverage` 已改为对齐同日 raw by-date 文件 code set，不再读取当前 dynamic partitions 或 by-code 文件推导历史覆盖。
- `asset_guards/market_major_indices_lake_readiness.py` 已改为读取同日 raw by-date + silver facts，不再导入 `raw_index_daily_by_code_path(...)`。

### P6：raw/silver sensors 切换

状态：代码实现已完成；新 sensor 在代码定义中仍默认 `STOPPED`，但正式 instance 已由人工启用。`2026-06-24` 自动触发 `raw_index_daily_update_job[2026-06-23]` 和 `silver_index_daily_update_job[2026-06-23]`，两者均成功。

- 已新增 `raw_index_daily_update_job_sensor`，目标 `raw_index_daily_update_job`，默认 STOPPED，每 tick 最多提交 1 个 date-level run，run key 为统一 builder 生成的 `raw_index_daily:<trade_date>`。
- 新 raw sensor 先做交易日注册缺口、最近 10 个 by-date raw readiness 和最新 ready baseline 检查；没有 ready baseline 时 fail closed，不从固定日期或当前日期猜起点。
- 新增 prod-core-db source readiness probe，只对选中的目标日期和运行时 DG code set 做一次只读检查；缺 DG code、重复 key、空 key、日期不匹配或异常时 skip，不提交 run。
- `silver_index_daily_sensor` 已改为先检查同日 `raw_index_daily` readiness，再选择 silver not-ready 分区；不再调用 `audit_index_daily_raw_gaps(...)` 或 by-code 文件 readiness。
- `sensors/readiness.py` 已新增 `RAW_INDEX_DAILY_ASSET_KEY/CHECKS/READINESS_SPEC` 和 `raw_index_daily_ready_for_trade_date(...)`。
- `sensors/index_daily_raw_file_readiness.py` 已新增 `raw_index_daily_lake_readiness_for_trade_dates(...)`，热路径最多 10 个交易日，复刻两个 raw by-date check 语义。
- P6 当轮旧 `index_daily_sensor`、旧 by-code asset/check/job/helper/readiness 仍保留到 P7，且不启用新 sensor；P7 已删除旧 active source/catalog，正式 instance 后续已启用新 raw/silver sensors。

### P7：旧 by-code active code 清零

目标：

- 删除旧 asset/job/check/readiness/catalog/sensor refs。
- 静态门禁强制生产代码无 by-code 旧符号。
- 文档状态更新。

落地结果：

- `defs/assets/index_daily.py`：删除 `raw_tushare_index_daily_by_code` asset，删除旧 silver by-code helper。
- `defs/checks/index_daily_checks.py`：删除旧 raw-by-code 5 个 asset checks，仅保留 `raw_index_daily_file_contract_check` 与 `raw_index_daily_code_coverage_check` 两个新 raw by-date 聚合 check。
- `defs/jobs/index_daily_update.py`：删除旧 `index_daily_update_job`，仅保留 `raw_index_daily_update_job`。
- `defs/run_contracts/configs.py`：删除旧 `IndexDailyRawByCodeConfig`、`build_index_daily_update_job_run_config(...)` 和旧 op key。
- `defs/paths.py`：删除旧 by-code path helper 与 staging helper。
- `defs/tushare_api_io.py`：删除旧 index daily by-code 专用 Tushare 写湖 helper。
- `defs/sensors/index_daily_sensor.py` 与 `defs/sensors/index_daily_late_arrival_repair.py`：删除旧 per-code raw sensor 与 late-arrival repair selector。
- `defs/sensors/index_daily_raw_file_readiness.py`：删除旧 by-code gap/readiness helper，仅保留 by-date hot-path readiness。
- `defs/sensors/readiness.py`：删除 `RAW_INDEX_DAILY_BY_CODE_*` readiness spec 与 `raw_index_daily_by_code_ready_for_code(...)`。
- `defs/catalog/lake_assets.py`：删除旧 `raw_tushare_index_daily_by_code` catalog entry，active catalog 中 index daily raw 只保留 prod-core-db `raw_index_daily`。
- `defs/bootstrap/index_daily_raw_by_date_runless_events*.py`：删除 P4 一次性 bootstrap helper/CLI，避免旧 by-code path/symbol 留在 active `src/orchestrator/defs/**`。
- tests：删除旧 by-code sensor/repair/runless 专用测试，改写 readiness/run config/governance/static gates；新增 P7 static gate 扫描 active defs，禁止旧 by-code production symbol 回流。

P7 不做：

- 不删除 `raw/tushare/index_daily_by_code/**` 物理文件；
- 不写 Dagster DB，不清理旧 event/run/sensor state；
- 不启用任何 sensor；
- 不修改 dynamic partitions；
- 不写 prod DB 或 lake 数据文件。

### P8：旧 by-code lake 文件删除

目标：

- 单独审批后删除旧 by-code raw files。
- 不删除 Dagster DB event。

### P9：旧 index daily Dagster 状态/事件清理

目标：

- P9A 先执行旧 index daily 状态/事件清理 dry-run。
- P9B-1 清理旧 by-code raw asset/check 状态和已删除旧 raw sensor state。
- P9C-1 清理旧 index daily job run history 中不含 `silver_index_daily` event 的安全子集。
- 只在 dry-run 证明不影响新 readiness、sensor、catalog、run contract 后 apply。
- 若无法安全精确删除，则保留旧记录作为历史审计账，不强行清理。
- P9C-2 是否处理 4 个含 `silver_index_daily` event 的 mixed runs，必须单独拍板。

## 23. 失败停止条件

任一条件触发，必须停止开发：

- prod DB 字段无法映射到 raw schema。
- prod DB 单日 source probe p95 超过 10s，且无索引/SQL 优化方案。
- prod DB 单日 full read 超过 60s。
- prod source completeness gate 发现目标日期 serving 未完整覆盖运行时 Lake 期望 code set。
- by-date 历史转换发现当前 DG by-code input 与目标行数、pair 集合、唯一键、schema 无法对齐。
- runless event 补录需要无界 Dagster event history 扫描。
- 需要清理 Dagster DB 旧 event 才能让新链路工作。
- 需要保留旧 by-code 兼容路径才能让新链路工作。
- P9 旧状态/事件清理 dry-run 无法证明候选对象与新 raw/silver/readiness/sensor 无交集。

## 24. 验收标准

最终验收必须同时满足：

- `raw_index_daily[trade_date]` 正式运行成功。
- `silver_index_daily[trade_date]` 只依赖 by-date raw。
- `raw_index_daily_update_job_sensor` 每 tick 最多提交一个 date-level run。
- raw by-date blocking check 只有 `raw_index_daily_file_contract_check` 和 `raw_index_daily_code_coverage_check` 两个聚合 check。
- 若执行 P9，清理报告证明未删除 dynamic partitions、新 raw by-date event、新 silver 历史、prod 数据和 by-date lake 文件；若不执行 P9，旧事件不参与新 readiness 和日更状态。
- 生产代码不再引用旧 by-code raw asset/path/helper。
- catalog 与代码一致。
- P0 profiling 确认范围内的 by-code 到 by-date 历史转换与 runless event 补录 audit 通过。
- 旧 by-code 文件删除后，新 sensor、silver、major indices 不受影响。
- 全量本地测试通过。
- 未运行任何未经批准的正式 Dagster/lake 写入。

## 25. 本轮重新审计结论与推进建议

### 25.1 已核实的代码影响面

CodeGraph 与源码审计确认，本专项真实改动面至少包括下表。表中的“P1/P2 前事实”保留当时的设计依据；“P5/P6 当前状态”记录最新落地情况和后续剩余工作。

| 改动面 | P1/P2 前事实 | P5/P6 当前状态 |
| --- | --- | --- |
| `paths.py` | 只有 `raw_index_daily_by_code_path(...)` 和 by-code staging helper。 | 已新增 `raw_index_daily_path(...)` 与 by-date staging helper；旧 helper 保留到 P7。 |
| `asset_column_schemas.py` / `duckdb_sql.py` | raw index daily schema 名称绑定 Tushare/by-code，`INDEX_DAILY_RAW_COLUMNS` 由旧 schema 生成。 | 已新增 `RAW_INDEX_DAILY_SCHEMA`，`INDEX_DAILY_RAW_COLUMNS` 已切到新 schema；旧 by-code schema 保留给迁移期旧 asset。 |
| `assets/index_daily.py` | raw asset 是 `raw_tushare_index_daily_by_code[ts_code]`；silver 通过 `AllPartitionMapping()` 扫所有 by-code 文件。 | 已新增 `raw_index_daily[trade_date]`；`silver_index_daily` 已改为依赖同日 `raw_index_daily` 并读取 by-date raw；旧 raw-by-code asset 保留到 P7。 |
| `checks/index_daily_checks.py` | raw checks 全部挂旧 asset，silver coverage 仍读 by-code raw。 | 已新增两个 by-date raw checks；`silver_index_daily_registered_code_coverage` 已改为对齐同日 raw by-date code set；旧 5 个 by-code checks 保留到 P7。 |
| `sensors/index_daily_sensor.py` | Tushare source probe + per-code run；cursor 带 selected_codes/next_pending_offset/repair_state。 | 旧 sensor 不再作为新链路入口，保留到 P7；已新增 `raw_index_daily_update_job_sensor`，prod source completeness gate + date-level single RunRequest，默认 STOPPED。 |
| `sensors/silver_index_daily_sensor.py` | 依赖 `audit_index_daily_raw_gaps(...)` 和 by-code 文件 presence。 | 已改为依赖 `raw_index_daily[trade_date]` readiness；不再扫描 by-code 文件集合。 |
| `asset_guards/market_major_indices_lake_readiness.py` | `silver_index_daily_lake_readiness_for_trade_date(...)` 仍读取 by-code raw。 | 已改为 by-date raw/silver facts，不再导入旧 path。 |
| `catalog/lake_assets.py` | raw entry 通过 `_tushare_raw_entry(...)` 写 Tushare source。 | 已新增 `raw_index_daily` prod-core-db catalog entry；旧 by-code catalog entry 保留到 P7。 |
| `run_contracts/configs.py` | op key 是 `raw_tushare_index_daily_by_code`，config 里重复传 `trade_date`。 | 已新增 `build_raw_index_daily_update_job_run_config(...)`，partition key 是新链路唯一日期参数；旧 helper 保留给旧 job/sensor。 |
| `sensors/readiness.py` | 存在 `RAW_INDEX_DAILY_BY_CODE_*` spec 和 `raw_index_daily_by_code_ready_for_code(...)`。 | 已新增 date-level `RAW_INDEX_DAILY_*` readiness spec；旧 by-code spec P7 删除。 |
| `tests/test_run_contract_static_gates.py` | 当时已有 sensor 侧旧 symbol 禁止项。 | 已新增 P1/P2、P4、P5/P6 静态门禁；P7 继续扩展到 active source 旧 by-code 符号清零。 |

### 25.2 已核实的 prod 与 lake 数据事实

2026-06-23 P-1 执行前只读复核：

- 本机 DG `cn_a_index_ts_codes` 为 946 个，code set hash 为 `6f8f560f11cdce10e4cd5a096c64a4c9`。
- 本机 by-code raw 文件为 946 个、3,419,656 行、946 个 code、6,792 个 trade date，范围 `2000-01-04` 到 `2026-06-22`。
- 目标 by-date raw 路径 `/Volumes/datasource/data_lake/raw/index_daily` 当前不存在。
- prod `ops.index_series_active(resource='index_daily')` 为 1130 个 code。
- prod `ops.index_series_active(resource='index_daily_raw')` 为 3052 个 code。
- prod `core_serving.index_daily_serving` distinct code 为 1130 个，当前最大 trade date 为 `2026-06-22`。
- `dg_codes - prod_index_daily_active_pool = 86`。
- `dg_codes - prod_index_daily_serving_distinct_codes = 86`。
- `dg_codes - prod_index_daily_raw_pool = 0`，说明 86 个缺口都在旧 raw 请求池中，但未进入 prod `index_daily` active pool 和 serving。
- `prod_serving_codes - dg_codes = 270`，prod 额外 code 不阻断 DG 日更。
- 最近 10 个 prod serving 交易日均为 1126 个 code；active pool 最新日缺 4 个：`480055.CNI`、`480056.CNI`、`480057.CNI`、`931598.CSI`，且这 4 个与 DG 946 交集为空。
- 已废弃的旧 `list_date` 口径曾估算 expected pair 为 47,656；后续源站核实确认部分指数日线早于 `index_basic.list_date` 是真实存在的源端口径，因此 `list_date` 不再作为补数下限。
- 新口径以新湖 `silver/index_daily` 中 86 个 code 实际存在的 pair 为准；P-1 写入前审计样本到 `2026-06-22` 为 154,160 行，其中 106,720 行早于旧 `list_date` 口径。当时 prod serving 为 0 行，因此 serving 缺口按新口径为 154,160 行。
- prod raw 当前已有 2,837 行，但 P-1 不再要求补齐 prod raw；若未来需要治理 prod raw，必须另起专项方案。

2026-06-23 P-1 执行后复核：

- prod `ops.index_series_active(resource='index_daily')` 为 1216 个 code。
- prod `core_serving.index_daily_serving` distinct code 为 1216 个，日期范围为 `2004-12-31` 到 `2026-06-22`。
- `dg_codes - prod_index_daily_active_pool = 0`。
- `dg_codes - prod_index_daily_serving_distinct_codes = 0`。
- 本次 86 个 repair code 在 prod serving 中有 154,160 个 pair；与新湖 silver payload 对账 missing pair 为 0、extra pair 为 0、字段级 diff 为 0。
- prod `core_serving.index_daily_serving` 总行数为 1,827,704。

2026-06-23 P0 正式只读 profiling 结果：

| 项 | P0 结果 |
| --- | --- |
| DG `cn_a_index_ts_codes` | 946 个，sorted hash `6f8f560f11cdce10e4cd5a096c64a4c9` |
| `dg_codes - prod_index_daily_active_pool` | 0 |
| `dg_codes - prod_index_daily_serving_distinct_codes` | 0 |
| prod latest trade date | `2026-06-22` |
| `dg_codes - prod_latest_trade_date_codes` | 0 |
| prod serving total rows / distinct pairs | 1,827,704 / 1,827,704 |
| prod serving duplicate key / null key | 0 / 0 |
| prod serving columns | 14 列；业务字段 `ts_code/trade_date/open/high/low/close/pre_close/change_amount/pct_chg/vol/amount`，系统字段 `source/created_at/updated_at` 不进入 lake raw 业务投影 |
| prod serving primary key | `(ts_code, trade_date)` |
| by-code raw files | 946 个 |
| by-code raw rows / distinct pairs | 3,419,666 / 3,419,666 |
| by-code raw duplicate key / null key | 0 / 0 |
| by-code raw trade dates | 6,793 个，`2000-01-04` 到 `2026-06-23` |
| by-code raw schema | `ts_code/trade_date` 为 `VARCHAR`，行情字段为 `DOUBLE` |
| by-code raw OHLC/pre_close 任一为空 | 369,425 行，不能作为 raw 阻断条件 |
| target by-date raw files | 0 |
| 全量当前输入 event 估算 | 6,793 materialization + 13,586 raw check = 20,379 event |
| ready baseline event 估算 | 6,792 materialization + 13,584 raw check = 20,376 event |
| P4 修正后事件基线 | 不做全历史 event baseline；只补最近 20 个交易日，约 20 materialization + 40 raw check = 60 event |

P0 发现当时 by-code raw 尾部 `2026-06-23` 只有 10 行、10 个 code；最新 full DG coverage 日期是 `2026-06-22`。后续 P3/P4 不能直接按 raw-by-code `max(trade_date)` 生成绿色 ready baseline，否则 raw sensor 会跳过 `2026-06-23` 的 prod-core-db 日更。P4 的 20,376 条全量 event 估算只作为容量风险证据，不作为执行目标。

这些事实是 P0 时点的冻结输入基线。P1/P2 可以按该基线做代码开发；P3/P4 在正式写 lake/event 前必须重新跑同类只读 profiling，并以当时结果决定 ready baseline cutoff。

### 25.3 新发现风险

1. catalog helper 写错字段风险：P1/P2 已通过直接 `_entry(...)` 为 `raw_index_daily` 写入 prod-core-db 口径，避开 `_tushare_raw_entry(...)`。P7 已删除旧 by-code entry；后续 static gate 继续防止旧 helper 回流到新链路。
2. backend 复用风险：backend prod-core-db 已有字段口径但没有 DG code set filter，且跨区直接引用不允许。orchestrator 需要自己的 prod adapter。
3. baseline 缺失风险：当前 by-date 目标路径不存在，sensor 不能在 M3/M4 前通过“最新 ready raw_index_daily”计算日更起点。
4. bootstrap 遗留风险：P3/P4 必须临时读 by-code 文件；P7 已删除 P4 bootstrap helper/CLI，active `src/orchestrator/defs/**` 中旧 by-code symbol 扫描必须保持为 0。
5. check 过碎风险：P1/P2 已把新 raw by-date blocking checks 收敛为 `raw_index_daily_file_contract_check` 和 `raw_index_daily_code_coverage_check`。P4/P6/P7 继续沿用这两个聚合 check；不得把文件存在、row count、schema、partition date、unique key、coverage 再拆成独立 blocking check。
6. 固定日期风险：当前审计样本中的 `2026-06-22/2026-06-23` 不能进入 production runtime 逻辑。
7. 旧数据清理风险：P8 只删旧 by-code lake 文件，P9 才处理旧 Dagster 状态/事件。P9 不能成为新链路启用门槛；如果新链路需要清旧 event 才能跑，说明还有旧依赖没清零。
8. 尾部半截日期风险：P0 样本里 raw-by-code `2026-06-23` 只有 10 个 code。历史转换可以审计这个事实，但不能把它写成 ready baseline；日更起点必须从 ready baseline cutoff 推导，而不是从 raw-by-code max date 推导。

### 25.4 建议推进步骤

1. 继续观察下一次 expected trade date 的自动 raw+silver 日更：prod source 未 ready 时应 skip，ready 后 raw run 成功，随后 silver run 成功。
2. 若下一交易日自动链路不触发或 check 不绿，先按 sensor cursor、run tags、raw/silver 文件事实和 blocking check metadata 做只读审计，不直接重跑或覆盖。
3. 如需释放 Dagster PostgreSQL 物理空间，再单独设计 vacuum/analyze 或存储回收观察方案；不要混入 index daily raw 日更链路。

### 25.5 遗留拍板项

1. P8 quarantine 最终删除与 P9C-2 mixed run 治理已于 2026-07-15 完成，不再是遗留拍板项。
2. P9 后是否需要额外 Dagster DB vacuum/analyze 或空间回收观察：P9C-1/P9C-2 已删除旧 event history，但数据库物理空间回收策略不在本轮范围内。
3. 是否把后续日更运行观察结果继续补充到本 LLD，还是转入常规运行手册；当前文档已记录首个自动日更成功事实。

## 26. 2026-06-23 check 收敛与 P9 清理代码级审计

本节只记录代码级审计和只读 dry-run 结果。P1/P2 代码落地事实见上文；本节不代表允许执行任何 Dagster DB 清理 apply。

### 26.1 当前 active 代码事实

P5/P6 后、P7 前源码逐项审计确认，当时状态是“新 by-date raw/silver/sensor/major 活跃路径已落地，旧 by-code 定义仍保留到 P7 删除”的并存状态：

| 文件 | 当前事实 | 对本方案的含义 |
| --- | --- | --- |
| `defs/assets/index_daily.py` | 已新增 `raw_index_daily[trade_date]`；`silver_index_daily` 已改为依赖同日 `raw_index_daily` 并读取 by-date raw；`raw_tushare_index_daily_by_code` 仍保留。 | 新 silver 路径已切到 by-date；P7 再删除旧 raw-by-code asset。 |
| `defs/checks/index_daily_checks.py` | 已新增 `raw_index_daily_file_contract_check` 与 `raw_index_daily_code_coverage_check`；`silver_index_daily_registered_code_coverage` 已改为对齐同日 raw by-date code set；旧 5 个 by-code checks 仍挂旧 asset。 | 新链路 check 已收敛；P7 删除旧 by-code checks。 |
| `defs/jobs/index_daily_update.py` | 已新增 `raw_index_daily_update_job`；旧 `index_daily_update_job` selection 仍是旧 `raw_tushare_index_daily_by_code` + checks。 | 新 raw sensor 指向 `raw_index_daily_update_job`；P7 最终删除旧 job，不保留别名。 |
| `defs/sensors/raw_index_daily_update_job_sensor.py` | P1/P2 后不存在。 | 已新增规范 raw date-level sensor，目标 `raw_index_daily_update_job`，默认 STOPPED，prod source completeness gate + 单日期 RunRequest。 |
| `defs/sensors/index_daily_sensor.py` | sensor 仍查 Tushare readiness，按缺失 code 生成 per-code RunRequest，cursor 记录 selected codes / offset / repair state。 | 旧 sensor 不作为新链路入口，保留到 P7 删除；P5/P6 不修改其旧语义。 |
| `defs/sensors/silver_index_daily_sensor.py` | sensor 先跑 by-code raw gap audit，再检查 by-code 文件是否包含目标交易日。 | 已改为只读取 `raw_index_daily[trade_date]` readiness，不扫描 by-code 文件集合。 |
| `defs/sensors/index_daily_raw_file_readiness.py` | readiness helper 仍基于 `raw_index_daily_by_code_path(...)` 扫 946 个 by-code 文件。 | 已新增基于单个 by-date raw 文件和 code coverage 的热路径 helper；旧 by-code helper P7 删除。 |
| `defs/sensors/readiness.py` | `RAW_INDEX_DAILY_BY_CODE_CHECKS` 仍列 5 个旧 check，`raw_index_daily_by_code_ready_for_code(...)` 仍存在。 | 已新增 date-level `RAW_INDEX_DAILY_*` readiness spec；P7 清零旧 by-code readiness。 |
| `defs/catalog/lake_assets.py` | 已新增 `raw_index_daily` prod-core-db catalog entry；旧 `_tushare_raw_entry(asset_key='raw_tushare_index_daily_by_code')` 和旧 5 个 blocking checks 仍保留。 | catalog 当前新旧并存；P7 删除旧 entry。 |
| `defs/run_contracts/configs.py` | 已新增 `build_raw_index_daily_update_job_run_config(...)`；旧 helper 仍指向 `raw_tushare_index_daily_by_code` 并重复传 `trade_date` 给旧 asset。 | 新链路日期语义已收敛；旧 helper P7 随旧 job 删除。 |
| `defs/asset_guards/market_major_indices_lake_readiness.py` | major indices readiness 仍读取 by-code raw paths，用 silver coverage 语义补判断。 | 已切到 by-date raw/silver facts，不再 import 旧 path。 |

### 26.2 check 收敛的落地状态与后续要求

P1/P2 已将新 raw by-date blocking checks 收敛为两条，不拆成细碎 check。`raw_index_daily_file_contract_check` 把旧 raw-by-code 的 4 类文件契约和新 by-date date/key 语义聚合到一条 blocking check：

1. 文件存在。
2. row count 大于 0。
3. schema 与 `RAW_INDEX_DAILY_SCHEMA` 一致。
4. 文件内 `trade_date` 等于 partition key 的 `YYYYMMDD`。
5. `(ts_code, trade_date)` 唯一。

该 check 的 metadata 至少包含 `file_path`、`row_count`、`schema_ok`、`partition_date_ok`、`unique_key_ok`、`failed_contract_items`、`failure_reason_counts` 和样本；这样排障信息不丢，但 Dagster DB 只写一条 check event。

`raw_index_daily_code_coverage_check` 只承载 code coverage：

1. 历史转换段在 P4 runless event 补录模块中使用 `coverage_basis=by_code_source_pairs`，证明 by-code 输入 `(ts_code, trade_date)` pair 到 by-date 目标无损。
2. 日更段 runtime check 使用 `coverage_basis=prod_serving_expected_lake_codes`，证明 prod serving 覆盖运行时 Lake 期望 code set。
3. metadata 记录 `expected_code_count`、`expected_code_set_hash`、`actual_code_count`、missing/extra count 和样本。

P1/P2 测试和静态门禁已覆盖前两项；P4/P7 继续补齐 runless event 和旧符号清零门禁：

1. active source 中 raw by-date blocking check 名称只能是这两个。
2. 禁止新增 `raw_index_daily_file_exists_check`、`raw_index_daily_row_count_positive_check`、`raw_index_daily_required_columns_and_types_check`、`raw_index_daily_partition_date_matches_check`、`raw_index_daily_unique_ts_code_trade_date_check`、`raw_index_daily_registered_code_coverage_check`、`raw_index_daily_expected_code_coverage_check`。
3. readiness 不能同时支持新旧 raw check。
4. runless event dry-run 对每个 partition 只计划 materialization + 2 个 raw check event。

### 26.3 早期 P9 dry-run 执行口径

以下为 2026-06-23 早期 dry-run 口径，保留用于解释为什么 P9 必须分阶段治理。2026-06-24 已在 P7/P8 后重跑 P9A，并完成 P9B-1/P9C-1，最终结果见 26.7。

本轮 dry-run 只读本机正式 Dagster Postgres：

```text
DAGSTER_HOME: /Users/congming/.goldenshare/dagster_home
postgres_url: postgresql://congming@localhost:5432/goldenshare_dagster
执行方式: psql SELECT only
写入动作: 0
Dagster API/job/sensor/backfill 调用: 0
```

当前 Dagster storage 总量：

| 表 | 行数 |
| --- | ---: |
| `event_logs` | 6,381,606 |
| `runs` | 71,150 |
| `run_tags` | 522,615 |
| `asset_check_executions` | 1,217,342 |
| `asset_event_tags` | 73,264 |
| `dynamic_partitions` | 30,560 |
| `instigators` | 44 |

### 26.4 早期 P9 dry-run 结果

当时新目标 `raw_index_daily` 还没有正式 Dagster DB 记录：

| 对象 | 行数 |
| --- | ---: |
| `event_logs.asset_key='["raw_index_daily"]'` | 0 |
| `asset_check_executions.asset_key='["raw_index_daily"]'` | 0 |
| `asset_event_tags.asset_key='["raw_index_daily"]'` | 0 |
| `asset_keys.asset_key='["raw_index_daily"]'` | 0 |

旧 by-code raw 候选：

| 候选对象 | 行数 / 数量 | 范围 |
| --- | ---: | --- |
| `raw_tushare_index_daily_by_code` asset events | 48,515 | event id `1439487` 到 `6622347`，`2026-05-25 10:19:38` 到 `2026-06-22 17:14:35` |
| 其中 materialization | 23,780 | 同上 |
| 其中 planned materialization | 24,734 | 同上 |
| 其中 freshness state change | 1 | `2026-05-25 10:19:38` |
| 旧 raw-by-code check executions | 123,684 | evaluation event id `1439537` 到 `6622391` |
| 旧 raw-by-code check succeeded | 118,909 | 5 个旧 check 各约 23,782 条 |
| 旧 raw-by-code check planned | 4,775 | 5 个旧 check 各约 954 到 956 条 |
| `asset_event_tags` old by-code | 23,782 | key 为 `dagster/data_version` |

旧 job / run 候选：

| job | runs | event_logs | run_tags | 当前判断 |
| --- | ---: | ---: | ---: | --- |
| `index_daily_update_job` | 24,741 | 1,634,475 | 206,649 | 旧 per-code raw 更新 job，P9 候选，但不建议默认和 asset/check 事件一起删除。 |
| `index_daily_history_backfill_job` | 9 | 200,409 | 28 | 早期历史 backfill，P9 二级候选。 |
| `index_daily_repair_by_codes_job` | 1 | 31,553 | 5 | 早期 repair job，P9 二级候选。 |
| `index_daily_active_pool_initialize_job` | 1 | 56 | 0 | 早期 active pool 资产历史，P9 二级候选。 |
| `index_daily_active_pool_update_job` | 5 | 332 | 4 | 早期 active pool 资产历史，P9 二级候选。 |
| `silver_index_daily_update_job` | 6,531 | 570,168 | 45,559 | 默认不作为 P9 删除候选；`silver_index_daily` 历史仍是正式资产历史。 |

其它旧 index daily asset 历史：

| asset | event rows | 当前判断 |
| --- | ---: | --- |
| `raw_tushare_index_daily` | 19,792 | 更早的旧 raw 资产历史，当前 active code 未引用；可列为二级候选，但必须单独确认是否还需要保留调试链路。 |
| `silver_index_daily_active_pool` | 14 | 早期 active pool 资产历史，当前 active code 未引用；可列为二级候选。 |
| `silver_index_daily` | 保留 | 正式 silver 资产历史，P9 不删。 |

instigator / cursor dry-run：

| id | 当前状态 | 识别结果 | 当前判断 |
| ---: | --- | --- | --- |
| `1827` | `RUNNING SENSOR` | `job_name: index_daily_sensor` | 旧 raw sensor state。P7 删除旧 sensor 后才可进入 P9 候选。 |
| `2173` | 历史 dry-run 样本为 `RUNNING SENSOR` | `job_name: silver_index_daily_sensor` | P5/P6 代码已切新语义；正式 instance cursor/state 是否重置仍需单独审批，不能直接按旧 sensor 删除。 |

必须排除：

| 对象 | 当前数量 | 原因 |
| --- | ---: | --- |
| `dynamic_partitions.cn_a_index_ts_codes` | 946 | 运行时 Lake 期望 code set，不能清理。 |
| `dynamic_partitions.cn_a_index_trade_days` | 6,411 | index daily trade-date partitions，不能清理。 |
| `raw_index_daily` | 0 | 新目标，未来 P9 永远排除。 |
| `silver_index_daily` | 已有正式历史 | 下游继续消费，不能作为旧数据清理。 |

### 26.5 早期 P9 dry-run 判定

当时判定：**禁止 apply**。

原因：

1. P5/P6 已让新 raw/silver/major 活跃路径不再消费旧 by-code baseline，但旧 `raw_tushare_index_daily_by_code`、旧 raw-by-code checks、旧 by-code path/helper、旧 by-code readiness 和旧 per-code sensor 仍保留到 P7；P9 不能在 P7 前 apply。
2. `index_daily_update_job` run history 关联 `event_logs` 超过 160 万行、`run_tags` 超过 20 万行，清理粒度必须单独拍板；不能把 run history 清理混入 asset/check 事件清理。
3. `silver_index_daily_sensor` 代码语义已切新链路，但正式 instance 的 cursor/state 是否重置必须单独审批；不能把 cursor 治理混入 P5/P6 代码开发。

P9 最小可执行前置条件：

1. P7 后 active source 旧 by-code symbol 静态扫描为 0。
2. 新 `raw_index_daily` 和 `silver_index_daily` readiness 只读取新 asset/check/file facts。
3. 新 raw/silver sensors 已确认不读取旧 instigator cursor。
4. P9 dry-run 重跑，新 `raw_index_daily` 候选仍为 0。
5. 用户明确拍板清理粒度：只清旧 raw asset/check 历史，还是同时治理旧 run history。

### 26.6 P7 后状态更新

P7 代码清理后，active `src/orchestrator/defs/**` 已不再注册旧 by-code source/catalog：

- 旧 `raw_tushare_index_daily_by_code` asset/check/job/sensor/readiness/catalog entry 已删除。
- 旧 by-code path helper、Tushare IO helper、raw gap/readiness helper、run config helper 已删除。
- P4 一次性 runless bootstrap helper/CLI 已从 active defs 删除。
- P7 static gate 扫描 active defs，禁止旧 by-code production symbol 回流。

这在当时只满足 P9 的“active source 清零”前置条件之一，因此仍要求重新 dry-run 并等待审批。2026-06-24 已在 P9A 重跑 dry-run，并按独立审批完成 P9B-1/P9C-1；最终执行结果见 26.7。

### 26.7 P9B-1/P9C-1 执行结果

2026-06-24 已按单独审批完成 P9B-1 和 P9C-1：

| 阶段 | 结果 | 报告 |
| --- | --- | --- |
| P9A dry-run | 重新冻结候选对象和排除证据 | `/private/tmp/index_daily_p9_dry_run_20260624_085207.json` |
| P9B-1 | 旧 `raw_tushare_index_daily_by_code` asset event、check execution、asset tag、asset key 和旧 raw sensor instigator 全部清为 0；新 raw/silver 和 dynamic partitions 未变 | `/private/tmp/index_daily_p9b_post_audit_20260624_085909.json` |
| P9C-1 | 删除安全子集 24,766 runs、1,600,791 event_logs、206,779 run_tags、6 asset_event_tags；安全候选归零 | `/private/tmp/index_daily_p9c_post_audit_20260624_090926.json` |

P9C-1 后剩余旧 index daily jobs 只包含 4 个 protected mixed runs：

| run_id | job | status | event_logs | silver events | 处理口径 |
| --- | --- | --- | ---: | ---: | --- |
| `2cd7c15e-d79a-4573-8d0e-d8f82c40b6b7` | `index_daily_update_job` | `SUCCESS` | 129 | 1 | 保留，P9C-2 单独拍板 |
| `7e72108b-3b1a-47d6-8be6-ea6ddb313d87` | `index_daily_update_job` | `SUCCESS` | 129 | 1 | 保留，P9C-2 单独拍板 |
| `94e237fa-c397-4c7b-a75c-8651a28b6286` | `index_daily_update_job` | `SUCCESS` | 129 | 1 | 保留，P9C-2 单独拍板 |
| `9d421a09-c65e-4968-9c7f-b2e04369d866` | `index_daily_history_backfill_job` | `SUCCESS` | 141 | 5 | 保留，P9C-2 单独拍板 |

post-audit 排除对象计数：

| 对象 | 行数 |
| --- | ---: |
| `raw_index_daily` event_logs | 21 |
| `raw_index_daily` check executions | 40 |
| `silver_index_daily` event_logs | 12,951 |
| `silver_index_daily` check executions | 45,309 |
| `cn_a_index_ts_codes` dynamic partitions | 946 |
| `cn_a_index_trade_days` dynamic partitions | 6,412 |

P9C-1 当时结论：旧 by-code asset/check/sensor state 和旧 run history 安全子集已清理；新 raw/silver 状态、dynamic partitions、prod DB 和 by-date lake 文件未进入删除候选。P9C-2 当时未纳入该轮范围，已于 2026-07-15 完成，见下节。

### 26.8 P8 最终物理删除与 P9C-2 执行结果

2026-07-15 按单独批准完成最后两项遗留治理：

1. P8 删除前只读 plan 固化 quarantine 目录 947 个文件、1,894 个目录、204,912 KiB、0 个 symlink，并保存 SHA-256 文件清单；随后永久删除 `/Volumes/datasource/data_lake/_quarantine/index_daily_p8/index_daily_by_code_20260624_084707`。旧 raw 原路径和 quarantine 路径均不存在；新 `raw/index_daily` 保持 6,778 个 `part-000.parquet`、191,596 KiB。
2. P9C-2 对四个固定 mixed run 先导出精确 CSV 备份：4 个 runs、528 条 event_logs、8 条 run_tags、8 条 asset_event_tags；`asset_check_executions`、`pending_steps`、`concurrency_slots` 均为 0。备份 manifest 与 SHA-256 位于 `/private/tmp/index_daily_p8_p9c2_apply_20260715_171747/postgres_backup/`。
3. 单事务删除后，四个候选 run/event/tag 均归零。`raw_index_daily` event_logs 仍为 61、raw/silver check executions 合计仍为 45,467、两个动态分区合计仍为 7,316；`silver_index_daily` event_logs 从 12,983 精确降为 12,975，差额是被批准删除的 8 条旧 mixed-run silver event。plan/apply/post-audit 目录分别为 `/private/tmp/index_daily_p8_p9c2_plan_20260715_171718/` 与 `/private/tmp/index_daily_p8_p9c2_apply_20260715_171747/`。
