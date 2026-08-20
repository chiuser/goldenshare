# Dagster 股票分钟线 QFQ Sensor 热路径性能修复方案

更新时间：2026-06-21

状态：已由 [Dagster Batch Readiness Hot Path 性能治理专项方案](dagster-batch-readiness-hotpath-governance-plan.md) 收口完成。S1、S2、S3 对应的窗口前轻量 skip、qfq gold true batch、同类窗口前重活收口、全 helper 性能回归和长期门禁均已落地；本文保留为问题背景与修复依据。

2026-07-15 治理补充：本文中“公式 check 必须进入 batch readiness”的旧要求已撤销。
QFQ 与 derived QFQ 的公式正确性改由受保护金样本测试保障；后续热路径只能校验生产输入、
文件、键、值域、来源覆盖和 repair 状态。现行职责边界见
[QFQ 计算测试与生产 Check 治理低层设计](dagster-stk-mins-qfq-validation-governance-low-level-design.md)。

## 1. 背景

打开 Dagster Runs 页面时出现报错。初步怀疑是任务过重导致 UI 请求超时。

本次只读诊断结论显示，问题不在 Runs 页面自身的 run list 查询，也不在 PostgreSQL run storage 明显慢查询，而是 Dagster user-code gRPC 进程被股票分钟线 qfq sensor 热路径中的 DuckDB 查询打满。

已观察到的只读证据：

| 证据 | 结果 |
|---|---|
| `dagster_webserver` 进程 | CPU 低、内存约百 MB 级，不是主要瓶颈 |
| `dagster._daemon` 进程 | CPU 低、内存低，不是主要瓶颈 |
| `dagster api grpc --lazy-load-user-code` 进程 | CPU 约 467%，RSS 约 16GB，采样时 physical footprint 约 35GB |
| `sample` 栈采样 | 热点在 DuckDB C extension |
| `lsof` 打开文件 | 正在读取 `gold/quote/stk_mins_qfq/freq=90/.../year=2026/*.parquet` |
| 代码入口 | `stock_mins_qfq_daily_sensor.py`、`stock_mins_qfq_factor_repair_sensor.py` |
| 重查询 helper | `batch_gold_stk_mins_qfq_lake_readiness(...)` |

Runs 页面为什么会被拖垮：

1. Dagster webserver 打开页面时，不只查询 run storage，也会访问 code location / workspace / definitions 信息。
2. 这些信息需要 user-code gRPC 进程响应。
3. 当前 user-code gRPC 进程正在执行重 DuckDB 查询，CPU 和内存被打满。
4. webserver 等不到 user-code 响应，最终表现为 Runs 页面报错或超时。

## 2. 当前根因

### 2.1 重活发生在窗口判断之前（治理前事实）

治理前两个 qfq sensor 都先计算长窗口 continuity readiness，再判断是否到运行窗口：

- `stock_mins_qfq_daily_sensor.py`
  - 目标运行窗口：19:50
  - 当前代码在窗口判断前会调用：
    - `batch_silver_stk_mins_lake_readiness(...)`
    - `batch_adj_factor_lake_readiness(...)`
    - `batch_gold_stk_mins_qfq_lake_readiness(...)`
- `stock_mins_qfq_factor_repair_sensor.py`
  - 目标运行窗口：20:05
  - 当前代码在窗口判断前会调用：
    - `batch_gold_stk_mins_qfq_lake_readiness(...)`
    - 之后才根据窗口决定是否提交 run

这在治理前导致一个非常不合理的行为：

```text
现在时间还没到 19:50 / 20:05
  -> sensor tick
  -> 先扫 60 天 qfq lake readiness
  -> 重 DuckDB 查询打满 user-code 进程
  -> 最后返回 SkipReason：窗口尚未到
```

这是第一优先级修复点。

### 2.2 60 天日常回看窗口本身也过重

本轮重新拍板：日常 sensor hot path 的连续性回看窗口默认改为最近 10 个 expected trade dates。

2026-06-26 追加口径：`stock_mins_qfq_daily_sensor` 不是普通窗口成本。只读 dry-run 显示，最近 5 个交易日完整链路约 `17.33s`，其中 gold qfq readiness 约 `14.2s`；若继续按 10 个交易日做完整语义扫描，已经有 60 秒 sensor tick 超时风险。因此 qfq daily sensor 正式收敛为最近 5 个 expected trade dates。其它日常 sensor 仍按默认 10 个交易日口径执行。

原因：

1. 日常 sensor 的职责是保证近期连续推进，不是承担长时间停机后的历史扫雷。
2. 如果任务每天或每周都在跑，最近 10 个交易日足以覆盖常见短暂停机、周末、节假日和少量补洞。
3. 如果系统停机超过 10 个交易日，应该进入显式 continuity audit / recovery 流程，而不是让每 10 分钟一次的 sensor tick 悄悄扫描更长历史。
4. 60 天只有在“停机接近三个月但仍希望自动恢复”的场景才有意义；这个场景本身应该由人工审计和专项补洞接管。
5. 60 天窗口会放大所有 readiness helper 的设计缺陷，特别是 qfq 90/120 这种 stock-year 文件组织的派生资产。

新的窗口边界：

| 场景 | 正式口径 |
|---|---|
| 日常 sensor hot path continuity 回看 | 默认最近 10 个 expected trade dates |
| `stock_mins_qfq_daily_sensor` continuity 回看 | 最近 5 个 expected trade dates |
| partition registered gap 检查 | 与对应 sensor 的 hot path 窗口一致 |
| first-not-ready / first-not-completed 选择 | 与对应 sensor 的 hot path 窗口一致 |
| 窗口外历史缺口 | 不由日常 sensor 自动处理，走 continuity audit / recovery |
| 长时间停机恢复 | 单独只读审计、明确补洞范围、再按专项执行 |
| 历史质量审计 | 独立 CLI / dry-run，不进入 sensor hot path |

因此，后续代码不应继续把旧的 60 天窗口常量作为日常 sensor 默认回看口径。建议改成表达业务语义的常量，例如：

```text
STK_MINS_DAILY_SENSOR_CONTINUITY_WINDOW_LIMIT = 10
```

### 2.3 `batch_gold_stk_mins_qfq_lake_readiness` 不是真正意义上的 batch（治理前事实）

治理前函数名叫 batch，但旧模型仍然是：

```text
for trade_date in N 个 expected dates:
  for native freq in 1/5/15/30/60:
    读 silver 当日文件
    计算 expected gold paths
    读 gold target files
    做 row count / schema / path / unique / price / coverage / formula

  for derived freq in 90/120:
    发现 source freq 的 stock-year qfq paths
    基于 source qfq paths 构造 derived select SQL
    计算 diagnostics
    计算 expected target paths
    读 target gold files
    做 row count / schema / path / unique / price / source window / formula
```

最重的是 derived 90/120：

1. 派生频度不是按 `trade_date` 物理分区，而是按 `freq/ts_code/year` 文件组织。
2. 每个目标日期都要从大量 stock-year qfq 文件里推导当天的 90m/120m expected rows。
3. 当前实现对窗口内每个日期重复构造和执行 derived diagnostics / formula 相关 SQL。
4. 即使每次只读 2026 年文件，股票数量 × 频度 × 年文件的展开量仍然很大。
5. DuckDB 会在 user-code 进程内执行这些查询，导致 CPU、内存和文件句柄压力集中到同一个 gRPC 进程。

因此问题不是“DuckDB 天生慢”，而是当前查询模型把本应批量聚合的 derived qfq 语义，拆成了 `日期 × 频度` 的重复大查询。

## 3. 优化目标

本专项只解决两个问题：

1. 窗口未到时，禁止进入重 readiness 扫描。
2. 日常 sensor hot path 默认回看窗口统一收敛为最近 10 个 expected trade dates。
3. gold qfq readiness 必须从 per-date 重复扫描，改成真正批量或分层计算。

不做：

1. 不改 run key。
2. 不改 run config。
3. 不新增 Dagster asset、sensor、job、check。
4. 不新增 status manifest、summary asset、readiness asset、数据库表或持久化状态实体。
5. 不降低 blocking check 语义。
6. 不用文件存在和 row count 冒充完整 ready。
7. 不把长时间停机恢复塞进日常 sensor tick。
8. 不运行 `dg`，不写正式 Dagster instance，不写正式 lake。

## 4. 两步优化方案

### Step 1：窗口判断前置，窗口未到直接轻量 Skip

#### 目标

窗口未到时，sensor 不得执行任何重 DuckDB lake readiness 查询。

#### 改造对象

第一批必须改：

| Sensor | 当前窗口 | 当前问题 | 目标行为 |
|---|---:|---|---|
| `stock_mins_qfq_daily_sensor` | 19:50 | 窗口前先跑 silver / adj factor / gold qfq batch readiness | 窗口前直接 Skip，不打开 DuckDB readiness |
| `stock_mins_qfq_factor_repair_sensor` | 20:05 | 窗口前先跑 gold qfq batch readiness | 窗口前直接 Skip，不打开 DuckDB readiness |

同步审计后建议纳入同一规则但可分批改：

| Sensor | 风险级别 | 原因 |
|---|---|---|
| `stock_mins_raw_sensor` | 中 | 窗口前会跑 raw batch readiness；raw 查询比 qfq 小，但仍不应发生 |
| `stock_mins_silver_sensor` | 中高 | 窗口前会跑 raw / silver batch readiness；当前实测 60 天 silver 可到 20s 级 |
| `stock_mins_silver_trade_day_sensor` | 中 | 注册窗口前会跑 raw batch readiness；注册窗口未到时不需要做重检查 |
| `stock_adj_factor_sensor` | 低 | 当前已先判断窗口，再跑 batch readiness，模式正确 |
| market breadth / return distribution / major indices continuity sensors | 待单独审计 | 这些 sensor 多数没有“运行窗口前 heavy skip”问题，但仍要检查 batch helper 是否满足预算 |

#### 实现口径

窗口型 sensor 的执行顺序固定为：

```text
1. evaluated_at = now()
2. window_started = evaluated_at.time() >= RUN_START
3. if not window_started:
     return lightweight SkipReason + lightweight cursor
4. load expected calendar / partitions
5. registered gap check
6. batch lake readiness
7. selected-date upstream gate
8. RunRequest or SkipReason
```

窗口前 cursor 只允许写轻量信息：

```json
{
  "run_window_started": false,
  "reason": "窗口尚未到",
  "job_name": "...",
  "batch_status": null,
  "continuity_status": null
}
```

窗口前禁止写：

1. `gold_batch_status`
2. `silver_batch_status`
3. `raw_batch_status`
4. 任何 10 天 readiness 结果
5. 任何 `elapsed_ms` 来自重 DuckDB helper 的字段

#### 验收

必须新增或更新测试：

1. qfq daily 窗口前：
   - mock `batch_gold_stk_mins_qfq_lake_readiness` 为抛错。
   - sensor 仍返回 SkipReason。
   - cursor 中 `gold_batch_status is None`。
2. qfq factor repair 窗口前：
   - mock `batch_gold_stk_mins_qfq_lake_readiness` 为抛错。
   - sensor 仍返回 SkipReason。
3. 静态门禁：
   - 窗口型 sensor 中，`batch_*lake_readiness` 不得在窗口未到分支之前被必经调用。
   - 若静态 AST 难以完整表达，至少用单测覆盖所有窗口型 sensor。

### Step 2：重写 gold qfq readiness 查询模型

#### 目标

把 `batch_gold_stk_mins_qfq_lake_readiness(...)` 从“窗口天数 × 7 频度 × 多次 derived SQL”改成真正批量计算，避免 user-code 进程被单次 sensor tick 打爆。

#### 现状问题

当前 helper 的主要问题：

1. 外层按 `trade_date` 循环。
2. native 1/5/15/30/60 每个日期各自计算 counts / formula。
3. derived 90/120 每个日期都重新发现 source paths、生成 expected select、跑 diagnostics、跑 formula。
4. 对同一个 `year=2026` 的 stock-year qfq 文件，在窗口内被重复读取或重复参与 query planning。
5. `full_semantics=True` 下，sensor hot path 会尝试重放非常接近 asset check 的完整公式语义。

#### 改造原则

1. 不降低 check 语义。
2. 不用 row count 冒充 ready。
3. 不新增状态实体。
4. 优先让 DuckDB 查询按窗口、频度、年份批量聚合。
5. 如果完整 lake 语义在合理优化后仍超预算，必须停下讨论是否引入“正式 check event bounded read + lake preflight”的混合模型，不能偷偷降级。

#### 目标查询模型

建议拆成三层。

第一层：路径与缺文件粗筛，纯 Python 路径规划。

```text
输入：最近 10 个 expected dates、registered silver partitions、qfq freqs
输出：
  expected file paths
  missing file paths
  existing file paths
```

这一层用于快速发现：

1. 上游 silver partition 未注册。
2. native qfq 目标文件缺失。
3. derived qfq 目标文件缺失。

缺文件时无需跑 formula SQL，直接返回：

```text
materialized=false
ready=false
failed_check=gold_stk_mins_qfq_file_exists_and_row_count_positive
```

第二层：native 1/5/15/30/60 窗口批量语义。

目标：

```text
按 freq 一次读取窗口内所有 existing native gold files
按 freq 一次读取窗口内所有 silver files
按 trade_date + freq group by 输出 check counts
```

应覆盖：

1. schema
2. freq/date path match
3. unique key
4. price sanity
5. row count matches silver
6. factor coverage
7. formula matches silver + adj factor（历史实现；后续从 production check/readiness 删除）

第三层：derived 90/120 窗口批量语义。

目标：

```text
按 target_freq=90/120 分别处理
source_freq = 30/60
source stock-year paths 只发现一次
expected_select_sql 一次覆盖整个 window partition_keys
diagnostics 一次按 trade_date 聚合
target existing files 一次读取并按 trade_date 聚合
formula_counts 一次按 trade_date 聚合
```

关键要求：

1. `source_paths` 不能在窗口内按日期重复发现。
2. `build_gold_stk_mins_qfq_derived_select_sql(...)` 不能每个日期单独构造。
3. derived source window / source coverage 必须按窗口一次聚合，并映射回每个交易日；
   不在 readiness 中生成 expected OHLC 或进行公式对账。
4. 输出仍然必须能映射回 `StkMinsDateReadiness`，保留每个 trade_date 的：
   - `ready`
   - `materialized`
   - `checks_passed`
   - `failed_check_names`
   - `missing_file_paths`
   - `checked_row_count`
   - `failed_row_count`

#### 性能预算

| 项 | 预算 |
|---|---:|
| qfq daily 窗口前 tick | < 200ms，且不打开 qfq parquet |
| qfq factor repair 窗口前 tick | < 200ms，且不打开 qfq parquet |
| gold qfq 10 天缺文件粗筛 | < 1s |
| gold qfq 10 天完整语义，稳定态 | 目标 < 5s |
| gold qfq 10 天完整语义，异常态 | 目标 < 8s |
| user-code gRPC 进程 RSS 增量 | 不得出现 10GB 级增长 |
| 单次 sensor tick | 不得把 user-code 进程 CPU 长时间打满 |

若完整语义无法进入预算：

1. 不允许把 `full_semantics=False` 作为正式路径。
2. 不允许降低输入、文件、键、值域、来源覆盖或 repair 状态的 production 语义；
   公式验证由受保护测试金样本承担，不进入热路径。
3. 不允许只看文件存在和 row count。
4. 必须先拿真实 profiling 数据回来，再讨论是否使用 Dagster 正式 check event 的 bounded batch read 作为 heavyweight check 的缓存事实。

## 5. 为什么 DuckDB 会这么重

这次重不是 DuckDB 本身的问题，而是查询建模问题。

DuckDB 擅长：

1. 一次读取一批 Parquet。
2. 用 SQL 批量 group by。
3. 在列式文件上做向量化计算。

治理前实现没有完全利用这些优点：

1. `batch_gold_stk_mins_qfq_lake_readiness` 外层仍按日期循环。
2. derived 90/120 的 source 是 stock-year 文件，不是 day partition 文件。
3. 每个日期重复构造 derived select / diagnostics / formula SQL。
4. 单次 sensor tick 可能触发大量文件参与 query planning。
5. 查询运行在 Dagster user-code gRPC 进程内；这个进程同时服务 UI code location 请求，所以一旦被打满，Runs 页面也会跟着坏。

简单说：

```text
正确方式：一次把 10 天日常窗口作为集合交给 DuckDB 聚合。
治理前方式：用 Python 按天驱动 DuckDB 重复做大查询。
```

## 6. 同类问题审计

本次审计发现，同类问题分两类；下表记录治理前风险和后续收口结果。

### 6.1 治理前已确认需要立即修复，当前已完成

| 位置 | 治理前问题 | 当前处理结果 |
|---|---|---|
| `stock_mins_qfq_daily_sensor` | 窗口前执行 gold qfq batch readiness；gold qfq helper 本身过重 | 已完成窗口前轻量 skip、silver -> adj factor -> gold qfq 分层短路、qfq gold true batch；2026-06-26 进一步将日常窗口收敛为最近 5 个 expected trade dates。 |
| `stock_mins_qfq_factor_repair_sensor` | 窗口前执行 gold qfq batch readiness；gold qfq helper 本身过重 | 已完成窗口前轻量 skip；gold qfq 未 ready 时不读 repair status；qfq gold true batch 已落地。 |

### 6.2 治理前有同类窗口前重活风险，当前已收口

| 位置 | 治理前模型 | 风险 | 当前处理结果 |
|---|---|---|---|
| `stock_mins_raw_sensor` | 窗口前可能执行 batch readiness | raw 文件量大，但 SQL 简单 | 已收敛为最近 10 个 expected trade dates；窗口前重活已由连续性性能优化专项收口。 |
| `stock_mins_silver_sensor` | 窗口前可能执行 raw + silver batch readiness | silver 实测可到 20s 级 | 已收敛为最近 10 个 expected trade dates；窗口前重活已由连续性性能优化专项收口。 |
| `stock_mins_silver_trade_day_sensor` | 注册窗口前可能执行 raw batch readiness | 不应在 19:45 前做重活 | 已收敛为最近 10 个 expected trade dates；注册窗口前重活已收口。 |

### 6.3 当前结构较合理，但仍需保留门禁

| 位置 | 现状 | 建议 |
|---|---|---|
| `stock_adj_factor_sensor` | 已先判断窗口，再执行 adj factor batch readiness | 保持，补静态/单测防回流 |
| `market_major_indices_daily_sensor` | 已有独立性能治理方案，batch selector 范围小 | 不纳入本 qfq 修复，保留现有专项 |
| `market_breadth_continuity_sensor` / `stock_return_distribution_continuity_sensor` | batch helper 存在，但数据规模远小于分钟线 qfq | 后续只读 profiling，确认是否需要窗口前轻量 skip |

## 7. 开发阶段建议

本节保留原开发拆分作为历史执行记录。对应阶段已由 batch readiness hot path 专项和股票分钟线连续性性能优化专项完成，不再表示待开发任务。

### S1：快速止血

范围：

1. `stock_mins_qfq_daily_sensor`
2. `stock_mins_qfq_factor_repair_sensor`

任务：

1. 窗口未到时直接返回 Skip。
2. 窗口未到时禁止调用任何 batch lake readiness。
3. 加单测证明 mock batch helper 抛错时窗口前仍能 Skip。
4. 加静态门禁或 targeted 单测防回流。

验收：

1. 18:00-19:50 之间打开 Runs 页面，不应触发 qfq parquet 扫描。
2. `lsof -p <user-code-pid>` 不应在窗口前出现 `gold/quote/stk_mins_qfq/freq=90` 读取。
3. user-code gRPC 进程 CPU/RSS 不应因窗口前 qfq sensor tick 暴涨。

### S2：修正 gold qfq batch readiness

范围：

1. `asset_guards/stk_mins_lake_readiness.py`
2. qfq daily / qfq factor repair sensor tests
3. performance tests

任务：

1. 把 native qfq readiness 改成窗口批量聚合。
2. 把 derived 90/120 readiness 改成按 target freq / year / window 聚合。
3. 避免每个 trade_date 重复发现 source paths 和重复构造 derived SQL。
4. 保留完整 blocking check 语义。
5. 记录 10 天真实性能数据；20/60 天只作为离线对比，不作为日常 hot path 验收口径。

验收：

1. 10 天窗口完整语义进入预算。
2. `sample` 不再显示 user-code 进程长时间卡在 DuckDB derived qfq 查询。
3. `batch_gold_stk_mins_qfq_lake_readiness.elapsed_ms` 稳定落入文档预算。
4. 测试覆盖：
   - missing native file
   - missing derived file
   - native formula mismatch
   - derived source window incomplete
   - derived formula mismatch
   - materialized check problem 不自动重跑
   - 06-15 未 ready 不提交 06-16

### S3：同类窗口前重活收口

范围：

1. `stock_mins_raw_sensor`
2. `stock_mins_silver_sensor`
3. `stock_mins_silver_trade_day_sensor`

任务：

1. 窗口/注册窗口未到时轻量 Skip。
2. 不再为了 cursor 展示而提前做 10 天 lake readiness。
3. cursor 允许少写 batch details；热路径性能优先于窗口前可观测性。

验收：

1. 窗口前 mock batch helper 抛错，sensor 仍 Skip。
2. 窗口后行为不变。
3. run key、run config、partition set 不变。

## 8. 性能验证计划

只读验证，不运行 `dg`，不写 Dagster instance，不写正式 lake。

### 8.1 进程侧验证

```bash
ps -p <user-code-pid>,<webserver-pid>,<daemon-pid> -o pid,ppid,%cpu,%mem,rss,vsz,etime,state,command
```

目标：

1. 窗口前 user-code 进程不再持续高 CPU。
2. RSS 不再出现 10GB 级增长。

### 8.2 文件打开验证

```bash
lsof -p <user-code-pid> | rg "/Volumes/datasource/data_lake/gold/quote/stk_mins_qfq|parquet"
```

目标：

1. 窗口前不打开 qfq gold parquet。
2. 窗口后若打开，必须在预算内关闭。

### 8.3 栈采样验证

```bash
sample <user-code-pid> 8 -file /private/tmp/dagster_user_code_server_qfq_hotpath_after_fix.sample.txt
```

目标：

1. 不再长时间停在 `_duckdb.cpython-313-darwin.so`。
2. 若仍停在 DuckDB，采样要能定位到新的 SQL 模型问题。

### 8.4 Helper 性能测试

本地测试必须记录：

1. 10 天完整语义耗时。
2. 20/60 天离线对比耗时，作为容量参考，不作为 sensor hot path 验收口径。
3. native 与 derived 分段耗时。
4. 文件数。
5. query count。
6. 是否发生 spill。
7. 峰值 RSS。

## 9. 停止条件

出现以下任一情况，停止实现并重新讨论：

1. 必须降低 qfq blocking check 语义才能进入预算。
2. 必须新增持久化状态实体才能进入预算。
3. 必须恢复逐日 Dagster event/check 深扫。
4. 必须改变 run key、run config、job/sensor 名称或 partition set。
5. 完整 derived 90/120 lake 语义优化后仍无法进入预算。
6. 需要读取或写入正式 Dagster instance 才能判断。
7. 需要运行 `dg`、提交 run、materialize、asset check 或 backfill。

## 10. 当前建议

当前已经按独立 batch readiness hot path 专项完成：

1. S1 已完成：qfq daily / qfq factor repair sensor 在运行窗口前轻量 skip，窗口前不执行重 DuckDB readiness。
2. S2 已完成：`batch_gold_stk_mins_qfq_lake_readiness(...)` 已从日期乘频度重扫改成窗口级 true batch，并保留 native + derived 完整 blocking check 语义。
3. S3 已完成：raw / silver / silver partition 同类窗口前重活已在股票分钟线连续性性能优化专项中收口，日常窗口统一为最近 10 个 expected trade dates。
4. 全 helper 性能回归已完成：`batch_raw_stk_mins_lake_readiness`、`batch_silver_stk_mins_lake_readiness`、qfq gold、adj factor、major indices、market breadth、ClickHouse readiness helper 均已跑过本地性能样本或 fake-client 调用次数测试。
5. 长期门禁已写入 `lake_console/orchestrator/CODING_STANDARDS.md`，后续不得恢复窗口前重扫、逐日 Dagster event history 深扫、row count 冒充 ready 或名不副实 batch。

因此，本文不再作为待开发计划使用；后续如出现新的 sensor hot path 性能问题，必须先对照 batch readiness hot path 专项和编码规范做读取模型审计。
