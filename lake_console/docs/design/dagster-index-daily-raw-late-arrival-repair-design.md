# index_daily raw 晚到补缺调度方案

更新时间：2026-06-04

状态：已按确认口径落地开发。

## 1. 目标

`raw_tushare_index_daily_by_code` 每天按指数代码更新 Tushare `index_daily`。全市场约 900 多个指数，一轮更新时可能有少量指数源端尚未发布当天数据，导致对应 code 的 raw 当日数据缺失。

本方案目标是：在不重打全市场、不伪造空数据成功、不绕过 raw presence gate 的前提下，定时补跑仍然缺失的指数代码，直到目标交易日 raw presence 全齐，或者达到明确的请求预算和人工介入门槛。

## 2. 已核对依据

### 2.1 本地规则

已核对：

1. 根目录 `AGENTS.md`。
2. `lake_console/AGENTS.md`。
3. `lake_console/orchestrator/AGENTS.md`。
4. `lake_console/frontend/AGENTS.md`，本方案不涉及前端代码。
5. `lake_console/orchestrator/CODING_STANDARDS.md`。
6. `lake_console/docs/design/dagster-asset-schema-contract-design.md`。

本方案遵守的关键门禁：

1. 不运行正式 Dagster job、sensor、backfill、materialize 或 evaluator。
2. 不读写正式 Dagster instance。
3. 不读写正式 lake 数据。
4. 不新增数据库表、状态实体、summary asset 或 readiness asset。
5. 大体量文件事实审计继续使用 DuckDB set-based SQL。
6. sensor 只做编排，不写 parquet，不直接实现 Tushare 拉取逻辑。
7. 新增或修改 sensor 逻辑前，必须先列清 run key、cursor、最大单 tick 请求数、失败重跑策略和边界。

### 2.2 当前代码事实

当前实现要点：

1. `raw_tushare_index_daily_by_code` 是按 `cn_a_index_ts_codes` 分区的 raw asset。
2. `IndexDailyRawByCodeConfig.trade_date` 是 run config，不是 asset partition key。
3. `index_daily_update_job` 只选择 `raw_tushare_index_daily_by_code` 和它的 checks。
4. `index_daily_sensor` 当前每 600 秒评估一次。
5. `index_daily_sensor` 先用 `audit_index_daily_raw_gaps(...)` 查最近 60 个可运行交易日 raw-by-code 本地连续性。
6. 若连续性无缺口，再用 `check_index_daily_raw_files_for_trade_date(...)` 查最新目标交易日 raw presence。
7. raw 缺失 code 会触发 `index_daily_update_job[ts_code]`，run config 中 `trade_date=<target_trade_date>`。
8. 当前 run key 固定为 `index_daily:<trade_date>:<ts_code>`。
9. `fetch_tushare_index_daily_by_code_to_raw(...)` 对目标窗口 0 行直接抛 `RuntimeError`，不会把空结果物化成成功。
10. `check_index_daily_source_readiness(...)` 只用 `000001.SH` 对目标交易日做全局 probe，不能证明每个指数 code 都已 ready。

### 2.3 Dagster 官方机制依据

已调研的 Dagster 官方机制：

1. Sensors / `RunRequest` / `run_key`：`run_key` 用于 sensor 幂等，同一个 sensor 中相同 run key 只应创建一次 run。参考：<https://docs.dagster.io/api/dagster/schedules-sensors>
2. Op retries / `RetryPolicy`：适合短暂网络错误、API 抖动等技术重试。参考：<https://docs.dagster.io/guides/build/ops/op-retries>
3. Run retries：适合 run 级别失败重试，偏基础设施或全 run 重试，不适合作为本需求主机制。参考：<https://docs.dagster.io/deployment/execution/run-retries>
4. Run status sensors：适合失败通知或补充观测，不适合单独承载“等待源端晚到后再补缺”。参考：<https://docs.dagster.io/guides/automate/sensors/run-status-sensors>
5. Declarative Automation：适合基于 Dagster asset partition 状态自动触发，但当前 raw asset 的 partition 是 `ts_code`，目标 `trade_date` 在 run config 中，不能直接表达“某 code 在某 trade_date 缺 raw 行”。参考：<https://docs.dagster.io/guides/automate/declarative-automation>
6. Concurrency：对 rate-limited API 和共享资源应设置并发或请求预算。参考：<https://docs.dagster.io/guides/operate/managing-concurrency>

### 2.4 Tushare 源文档依据

本地文档 `docs/sources/tushare/指数专题/0095_指数日线行情.md` 记录：

1. 接口：`index_daily`。
2. 必填参数：`ts_code`。
3. 可选参数：`trade_date`、`start_date`、`end_date`、`limit`、`offset`。
4. 单次最多 8000 行。
5. 当前 raw asset 使用 `ts_code + start_date + end_date` 单日窗口。

## 3. 问题判断

当前问题不是“无法发现 miss”。`index_daily_sensor` 已经通过 DuckDB raw gap audit 和目标日 raw presence 找到缺失 code。

真正的问题是：某个 `(trade_date, ts_code)` 第一次发 run 后，如果源端仍未 ready，asset 会失败且 raw 文件中仍缺当天行。下一轮 sensor 仍会发现该 code 缺失，但再次发出的 run key 仍是：

```text
index_daily:<trade_date>:<ts_code>
```

Dagster sensor 的 run key 语义会把这个请求视为已经创建过，因此不能依赖同一个稳定 run key 实现“失败后继续补跑”。

## 4. 方案结论

本方案建议：**不要新增独立 repair sensor；优先扩展现有 `index_daily_sensor`，在同一个 sensor 中加入晚到补缺分支。**

理由：

1. 现有 `index_daily_sensor` 已经完成一次 DuckDB raw continuity / presence 审计，再新增 repair sensor 会重复扫描同一批 raw-by-code parquet。
2. 现有 `index_daily_sensor` 已经做一次 Tushare 全局 source readiness probe，独立 repair sensor 会引入第二次 probe。
3. 同一个 sensor 内可以共享 pending code、cursor offset、source readiness 和 raw scan metadata，状态边界更清晰。
4. 不新增 sensor definition tags，不扩展 Automation 页面分类，也不引入新的 sensor 运维开关。
5. 修复点集中在 run key 与 cursor 补缺状态，避免把“日常 raw 更新”和“晚到 raw 补缺”拆成两个互相竞争的调度器。

独立 repair sensor 作为备选方案保留，但第一期不采用。

## 5. 正确算法

### 5.1 输入事实

每次 tick 仍沿用当前事实输入：

1. 已注册 `cn_a_index_trade_days`。
2. 已注册 `cn_a_index_ts_codes`。
3. 最近 60 个可运行交易日。
4. DuckDB raw continuity audit 结果。
5. 目标交易日 raw presence 结果。
6. Tushare `index_daily` 全局 source readiness probe。
7. sensor cursor 中的晚到补缺状态。

raw 缺失事实只来自 DuckDB raw file/presence 审计，不从 Dagster failed run history 推断。

### 5.2 目标日期选择

保持当前目标日期选择：

1. 若最近 60 个可运行交易日存在 raw continuity gap，选择最早缺口日期。
2. 若 continuity 无缺口，则检查最新可运行交易日 target raw presence。
3. 若最新目标日 presence 缺失，选择最新可运行交易日。
4. 若全 ready，skip。

### 5.3 请求选择

在目标日期上得到 `pending_codes` 后，按以下优先级选择要发起的 code：

1. 优先发起尚未尝试过的 pending code，使用现有首轮 run key：

```text
index_daily:<trade_date>:<ts_code>
```

2. 对已经尝试过但仍 pending 的 code，只有达到 `next_retry_at` 后才允许进入补缺候选。
3. 补缺候选使用新的 retry run key：

```text
index_daily:<trade_date>:<ts_code>:repair:<evaluation_date>:<attempt>
```

其中：

1. `trade_date` 是被补的业务交易日。
2. `evaluation_date` 是 sensor 评估所在自然日，格式 `YYYYMMDD`。
3. `attempt` 是该自然日内对该 `(trade_date, ts_code)` 的补缺尝试序号。

这样可以同时满足：

1. 同一 attempt 在 daemon 重启或 cursor 未提交时仍可被 run key 去重。
2. 不同补缺 attempt 可以真实创建新 run。
3. 跨自然日可以重新进入受控补缺，不会被前一日 run key 永久挡住。

### 5.4 Cursor 状态

扩展现有 sensor cursor 的 `details`，只记录仍然 pending 的 code：

```json
{
  "repair_state": {
    "target_trade_date": "2026-06-02",
    "evaluation_date": "20260604",
    "codes": {
      "000001.SH": {
        "attempt": 2,
        "last_run_key": "index_daily:2026-06-02:000001.SH:repair:20260604:2",
        "last_launched_at": "2026-06-04T16:30:00+08:00",
        "next_retry_at": "2026-06-04T17:00:00+08:00"
      }
    }
  }
}
```

Cursor 维护规则：

1. 每轮根据最新 `pending_codes` 剪枝，已经 ready 的 code 从 cursor 删除。
2. 目标交易日变化时，删除旧目标日期的 repair state。
3. `evaluation_date` 变化时，日内 attempt 预算重置，但仍保留 code 是否曾经进入补缺的事实。
4. Cursor 中只记录 pending code，不记录所有 900 多个注册指数。
5. Cursor 状态只服务 sensor 编排，不作为业务数据事实源。

### 5.5 Backoff 策略

建议第一期使用固定且可解释的 backoff：

| 日内 attempt | 下次尝试间隔 |
|---:|---:|
| 1 | 15 分钟 |
| 2 | 30 分钟 |
| 3 | 30 分钟 |
| 4+ | 60 分钟 |

这样能覆盖源端晚到的常见场景，又不会在源端确实未发布时高频打接口。

### 5.6 截止与预算

建议默认预算：

| 项目 | 建议值 | 说明 |
|---|---:|---|
| 首轮 `MAX_RUN_REQUESTS_PER_TICK` | 500 | 沿用当前实现，900 多个 code 约 2 个 tick 发完首轮。 |
| 补缺 `MAX_REPAIR_RUN_REQUESTS_PER_TICK` | 50 | 补缺只处理少量晚到 code，不能按首轮 500 的规模重试。 |
| 每个 code 每自然日最大补缺 attempt | 8 | 足够覆盖 16:00 后到晚间的多轮源端晚到。 |
| 单 tick Tushare readiness probe | 1 | 只做全局 probe，不对每个 code probe。 |
| 单 tick repair Tushare 请求上限 | 50 | 每个 repair run 通常 1 次 Tushare `index_daily` 请求。 |
| Cursor 中 repair code 上限 | 500 | 超过说明不是少量晚到，而是源端或系统性问题，应降级。 |

超过预算后的行为：

1. 不继续发起补缺 run。
2. 返回清晰 skip reason。
3. Cursor metadata 暴露 pending 数、样本 code、已达预算原因。
4. 不触发 silver。
5. 需要人工判断是源端未发布、指数注册池口径问题、Tushare 权限/限流问题，还是本地写入失败。

## 6. 性能评估

### 6.1 当前基线成本

当前 `index_daily_sensor` 每个 tick 的主要成本：

| 成本项 | 当前行为 | 规模 |
|---|---|---:|
| Dynamic partitions 读取 | 读取交易日和指数 code 分区 | 约 60 个近期交易日，900 多个 code |
| raw continuity audit | DuckDB 读 raw-by-code parquet，计算 `raw_start` 后连续性 | 约 `900 * 60 = 54,000` expected pairs |
| target raw presence | DuckDB 检查目标日每个有效 code 是否有 raw 行 | 约 900 个 expected codes |
| Tushare source probe | `000001.SH` 单日 1 行 probe | 1 次请求 |
| 首轮 raw runs | 对 pending code 发 `RunRequest` | 每 tick 最多 500 |

这个成本已经存在。晚到补缺方案不应再增加一套相同扫描。

### 6.2 为什么不新增独立 repair sensor

如果新增独立 repair sensor，稳定态会出现：

1. `index_daily_sensor` 每 600 秒扫一次 raw gap / presence。
2. repair sensor 也需要每 600 秒扫一次 raw gap / presence 才能知道哪些 code 仍缺。
3. 两个 sensor 都可能做 source readiness probe。
4. 两套 cursor 要避免互相重复发 run。

这会把文件审计和源站 probe 成本接近翻倍，且没有增加新的事实来源。

因此性能优先方案是：把补缺分支放回现有 `index_daily_sensor`。

### 6.3 补缺增量成本

采用同一 sensor 后，新增成本只剩：

| 新增成本项 | 规模 | 说明 |
|---|---:|---|
| Cursor 解析与剪枝 | pending code 数 | 只处理缺失 code，不处理全量 code。 |
| due retry 过滤 | pending code 数 | Python 编排级小集合，禁止做大体量明细计算。 |
| repair run requests | 每 tick 最多 50 | 只对仍缺且到期的 code 发 run。 |
| Tushare repair 请求 | 每个 repair run 通常 1 次 | 单日窗口，`limit=8000`，正常不分页。 |

正常场景下，如果只有 2 到 10 个指数晚到，新增 Tushare 请求就是每轮 2 到 10 次，远低于首轮全市场更新。

### 6.4 最坏情况控制

最坏情况不是“几个指数晚到”，而是以下异常：

1. Tushare 源端整体延迟，但全局 probe code 恰好 ready。
2. 某类指数权限不足或源端长期不返回。
3. 本地写入失败导致 raw presence 一直缺。
4. 注册指数池口径错误，要求了源端不应有数据的 code。

控制方式：

1. repair 每 tick 独立上限 50，不跟随首轮 500。
2. 每 code 每自然日最多 8 次。
3. Cursor 中 pending repair code 超过 500 时，不进入高频补缺，返回系统性异常 skip。
4. 连续多轮 pending 样本不变时，优先暴露 metadata，不扩大请求量。
5. silver 仍由 raw presence gate 阻断，不因 repair 分支绕过质量门禁。

### 6.5 DuckDB 使用边界

本方案继续沿用当前 DuckDB helper：

1. `audit_index_daily_raw_gaps(...)`。
2. `check_index_daily_raw_files_for_trade_date(...)`。

禁止在 repair 逻辑里用 Python 枚举 `code * trade_date` 做历史缺口审计。

允许 Python 做：

1. 读取 DuckDB helper 返回的 `pending_codes`。
2. 基于 cursor 计算 attempt、due 时间和 run key。
3. 汇总样本和 metadata。

## 7. Dagster retry 的使用边界

### 7.1 不用 run retries 做主机制

run retries 是 run 失败后的通用重试。它不知道 raw presence，也不知道源端某个 code 是否晚到。

若用 run retries 承载本需求，会有问题：

1. 对所有失败原因一视同仁。
2. 不按 raw 是否已补齐来停止。
3. 难以按 code 控制请求预算。
4. 容易在源端未发布时重复打接口。

因此不作为主方案。

### 7.2 可以考虑小型 `RetryPolicy`

后续可以给 raw asset 增加小型 `RetryPolicy`，只用于技术抖动：

1. 网络短暂失败。
2. Tushare API 偶发错误。
3. 连接超时。

但它不能替代晚到补缺 sensor 分支。

第一期可以先不加 `RetryPolicy`，避免把源端 0 行晚到和技术异常混在一起。

### 7.3 run status sensor 只做观测

run status sensor 可以用于通知或失败样本记录，但不建议在失败事件里立刻发同一个 code 的新 run。

原因：源端晚到不是即时重试能解决的问题，必须交给定时 sensor 的 backoff 和预算控制。

## 8. 代码落点建议

第一期已落地改动：

```text
lake_console/orchestrator/src/orchestrator/defs/sensors/index_daily_sensor.py
lake_console/orchestrator/src/orchestrator/defs/sensors/index_daily_late_arrival_repair.py
lake_console/orchestrator/tests/test_index_daily_sensor.py
lake_console/orchestrator/tests/test_index_daily_late_arrival_repair.py
```

其中 `index_daily_late_arrival_repair.py` 是窄 helper，职责只限：

```text
1. 读取和剪枝 cursor 中的 repair state。
2. 计算 base / repair run key。
3. 计算 15/30/30/60 分钟 backoff。
4. 限制每 tick repair run 数量和每 code 日内 attempt 数。
```

该 helper 不读写 lake、不调用 Tushare、不扫描 parquet、不访问 Dagster instance。

不改：

1. `raw_tushare_index_daily_by_code` asset 计算逻辑。
2. `index_daily_update_job` selection。
3. `silver_index_daily_sensor` raw readiness 口径。
4. raw / silver / gold 物理路径。
5. asset/check definitions。
6. dynamic partitions。
7. 数据库表或配置项。

## 9. 测试计划

单元测试必须覆盖：

1. 首次 missing code 使用稳定 base run key。
2. 同一 `(trade_date, code)` 首次失败后仍 pending，达到 backoff 后使用 repair run key。
3. 未达到 `next_retry_at` 时不发 repair run。
4. repair run key 包含 `trade_date`、`ts_code`、`evaluation_date` 和 attempt。
5. raw ready 后 cursor 中对应 code 被剪枝。
6. 目标交易日变化后旧 repair state 被清理。
7. source readiness false 时不发首轮或 repair run。
8. repair 每 tick 不超过 `MAX_REPAIR_RUN_REQUESTS_PER_TICK`。
9. 每 code 每自然日超过最大 attempt 后 skip。
10. pending code 超过 cursor 上限时进入系统性异常 skip，不高频补缺。
11. `silver_index_daily_sensor` 不因 raw repair 方案改变行为。
12. 不新增 250 日或全历史 blocking audit 到 daily sensor 路径。

静态门禁：

1. 不新增数据库表、asset、job selection 扩张。
2. 不在 repair helper 中调用 Tushare 或 DuckDB。
3. 不在 repair helper 中写 parquet。
4. 不新增项目自定义 run tags，除非另行做 run tag 设计审计。

## 10. 验证门槛

开发后本地允许的验证：

```text
lake_console/orchestrator/.venv/bin/python -m unittest tests.test_index_daily_sensor
lake_console/orchestrator/.venv/bin/python -m unittest tests.test_index_daily_raw_file_readiness
lake_console/orchestrator/.venv/bin/python -m py_compile <changed python files>
ruff check <changed python files>
python3 scripts/check_docs_integrity.py
git diff --check
git status --short
```

禁止未经批准执行：

1. `dg` / `dagster` definitions check。
2. 正式 sensor tick。
3. 正式 job run。
4. 正式 backfill。
5. 读取正式 Dagster instance 的临时 evaluator。
6. 读写正式 lake 数据。

如后续确实需要正式环境只读验证，必须单独列出完整命令、`DAGSTER_HOME`、读写范围、影响和回滚方式，等待确认。

## 11. 已确认决策

2026-06-04 已确认：

1. 不新增独立 repair sensor，补缺逻辑放入现有 `index_daily_sensor`。
2. 补缺每 tick 上限为 50 个 code。
3. 每个 code 每自然日最大补缺 attempt 为 8 次。
4. Backoff 节奏为 15 分钟、30 分钟、30 分钟、之后 60 分钟。
5. 第一期不加 Dagster `RetryPolicy`，只做 sensor 业务补缺。
6. 若需要新增 helper，只允许做 cursor repair state 和 run key 计算；不得读写 lake、不得调用 Tushare、不得扫描 parquet。

## 12. 完成定义

方案落地后应满足：

1. 源端少量指数晚到时，raw 缺失 code 会在预算内自动补跑。
2. 已经失败过的 `(trade_date, ts_code)` 不会被稳定 base run key 永久挡住。
3. 补缺只请求仍缺 raw 的 code，不重打全市场。
4. raw presence 全齐后，`silver_index_daily_sensor` 可按原有门禁继续推进。
5. 源端或本地系统性异常时，不无限重试，不放大 Tushare 请求量。
6. 不新增业务数据状态表，不污染 raw/silver/gold 数据路径。
7. 性能成本相比当前 sensor 只增加小集合 cursor 计算和受限 repair run，不重复 raw parquet 扫描。

## 13. 落地记录

2026-06-04 已完成：

1. `index_daily_sensor` 保持唯一 raw index daily 调度入口，不新增独立 repair sensor。
2. 新增 `index_daily_late_arrival_repair.py`，只做 cursor/backoff/run key 纯计算。
3. 首次 pending code 继续使用稳定 base run key：

```text
index_daily:<trade_date>:<ts_code>
```

4. 已尝试且仍 pending 的 code 到达 backoff 后使用 repair run key：

```text
index_daily:<trade_date>:<ts_code>:repair:<evaluation_date>:<attempt>
```

5. Cursor `details.repair_state` 只记录仍 pending 的 code，raw ready 后由下一轮 DuckDB audit 结果自然剪枝。
6. Source readiness false 时不发 base 或 repair run，只保留已存在 repair state 的诊断信息。
7. 补缺每 tick 上限 50，每 code 每自然日最多 8 次，backoff 为 15/30/30/60 分钟。

已执行验证：

```text
lake_console/orchestrator/.venv/bin/python -m unittest \
  lake_console/orchestrator/tests/test_index_daily_late_arrival_repair.py \
  lake_console/orchestrator/tests/test_index_daily_sensor.py \
  lake_console/orchestrator/tests/test_index_daily_raw_file_readiness.py \
  lake_console/orchestrator/tests/test_index_daily_checks.py \
  lake_console/orchestrator/tests/test_silver_index_daily_sensor.py \
  lake_console/orchestrator/tests/test_silver_index_daily_readiness_selector.py \
  lake_console/orchestrator/tests/test_market_major_indices_daily_sensor.py \
  lake_console/orchestrator/tests/test_sensor_cursor_contracts.py

lake_console/orchestrator/.venv/bin/python -m py_compile \
  lake_console/orchestrator/src/orchestrator/defs/sensors/index_daily_sensor.py \
  lake_console/orchestrator/src/orchestrator/defs/sensors/index_daily_late_arrival_repair.py \
  lake_console/orchestrator/tests/test_index_daily_sensor.py \
  lake_console/orchestrator/tests/test_index_daily_late_arrival_repair.py

lake_console/orchestrator/.venv/bin/ruff check \
  lake_console/orchestrator/src/orchestrator/defs/sensors/index_daily_sensor.py \
  lake_console/orchestrator/src/orchestrator/defs/sensors/index_daily_late_arrival_repair.py \
  lake_console/orchestrator/tests/test_index_daily_sensor.py \
  lake_console/orchestrator/tests/test_index_daily_late_arrival_repair.py
```

未执行：

1. 未运行 `dg` / `dagster` definitions check。
2. 未运行正式 sensor tick。
3. 未运行正式 `index_daily_update_job`。
4. 未读取或写入正式 Dagster instance。
5. 未读写正式 lake 数据。
