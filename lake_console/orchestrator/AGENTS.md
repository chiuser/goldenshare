# AGENTS.md — Dagster Orchestrator 目录规则

## 适用范围

本文件适用于 `lake_console/orchestrator/` 及其所有子目录。

本目录是正式 Dagster 项目，不是学习项目、临时项目或实验目录。

上级规则仍然生效：仓库根 `AGENTS.md` 与 `lake_console/AGENTS.md` 的约束必须继续遵守；若本文件与上级规则冲突，以更严格、更靠近本目录的规则为准。

---

## 项目定位

`orchestrator` 是 Goldenshare 本地数据湖未来的 Dagster 编排项目。

长期目标：

1. 用 Dagster 管理本地数据湖资产、依赖、分区、检查、调度、回填、日志与运行状态。
2. 若 Dagster 能胜任当前数据湖控制台的大部分工作，`lake_console` 产品形态将逐步废弃、退场，最终移除。
3. 现有 `lake_console` 的数据结构、catalog、同步策略、数据生成服务、路径口径、质量检查经验，是迁移到 Dagster 的重要参考资产；不得凭空重写未知口径。

---

## Dagster 学习与设计门禁

任何 Dagster 相关设计、实现、命令操作前，必须先查依据，不允许靠猜。

最低门禁：

1. 涉及 `assets`：先查 Dagster 官方 assets 文档。
2. 涉及 `resources`：先查 Dagster 官方 external resources 文档。
3. 涉及 `partitions` / `backfills`：先查 Dagster 官方 partitions and backfills 文档。
4. 涉及 `asset checks` / data contracts：先查 Dagster 官方 checks 或 data contracts 文档。
5. 涉及 `dg`、`dagster`、`dagster-webserver`、`dagster-daemon` 命令：先看官方文档或本地 `--help`。
6. 查完后必须先讨论设计与影响范围，再改文件或执行命令。

当前基础参考：

```text
https://docs.dagster.io/guides/build/assets
https://docs.dagster.io/guides/build/external-resources
https://docs.dagster.io/guides/build/partitions-and-backfills
https://docs.dagster.io/guides/test/asset-checks
```

禁止：

1. 不查文档就创建 asset/resource/check/schedule/backfill 设计。
2. 不讨论就新增目录、脚本、配置、依赖、数据库表或数据文件。
3. 自由发挥迁移多个数据集。
4. 用旧 `lake_console` 运行账本机制包装成新的 Dagster 资产。

### Job / Asset 职责边界门禁

Dagster job 只做流程入口和 asset selection，不承接具体数据生产逻辑。

依据：

1. Dagster 官方 asset jobs 文档中，asset job 是从一组 assets selection 定义出来的执行入口。
2. Dagster 官方 software-defined assets 口径中，asset definition 才描述资产如何由上游和计算逻辑生成。

规则：

1. `defs/jobs/**` 文件只能定义 job 名称、asset selection、checks selection、description 等入口信息。
2. `defs/jobs/**` 禁止直接调用 Tushare、DuckDB SQL、parquet 写入、路径拼接、字段转换、停牌修正、业务过滤或质量判断。
3. 具体拉取源数据、写 raw、生成 silver/gold 的代码必须放在 `defs/assets/**` 对应资产函数中。
4. 多个 asset 复用的通用能力应放在 resource 或 helper 中，例如 `TushareResource` 和 Tushare parquet 写入 helper；不能复制到多个 job 文件里。
5. 质量判断必须放在 `defs/checks/**`，或者作为 asset materialization 前必须失败的资产内部校验；禁止把质量判断写进 job。
6. job 可以组合多个资产形成执行入口，但不能为了控制执行顺序伪造数据血缘；真实依赖必须通过 asset `deps` 或 check `additional_deps` 表达。
7. 下游业务 job 不得在自己的 asset 代码里重复实现上游数据集拉取；需要完整链路时，应新增或调整组合 asset job 的 selection。

推荐心智模型：

```text
Job      = 这次要跑哪些资产
Asset    = 这个资产怎么生成
Resource = 怎么连接外部系统
Helper   = 多个资产复用的小工具
Check    = 这个资产生成后是否合格
```

### Asset Checks 运行门禁

当前 Dagster 版本的 `dagster.materialize()` 可用于轻量 asset 冒烟验证，但不接受 `asset_checks=` 参数，不能代表完整的 asset + checks 运行模型。

规则：

1. 所有 asset checks 必须注册进正式 `Definitions`，并能被 `load_from_defs_folder` 自动发现。
2. 验收 assets + checks 时，必须通过 Dagster asset job / asset selection / implicit global asset job 执行。
3. 当前版本验证 asset job 时，优先使用 `Definitions.resolve_implicit_global_asset_job_def()`；不要继续沿用已有重命名 warning 的旧入口作为新示例。
4. 后续 schedule、sensor、backfill、自动化运行必须基于正式 `Definitions` 解析 assets 与 checks。
5. 若验收目标是 Dagster UI 可观测，必须通过 UI materialize，或显式使用 UI 当前正式 `DAGSTER_HOME` 对应 instance 执行 job；临时 `dagster.materialize()` 不保证运行记录出现在当前 UI。
6. 禁止只在临时测试脚本里 import checks，却不让 Dagster code location 正式加载。
7. 禁止用只跑 asset 的 `dagster.materialize()` 结果替代 asset checks 验收。

### Partitioned Asset Checks API 门禁

对 partitioned asset 增加 asset checks 时，优先让 check 绑定资产对象，不要给 check 手写 `partitions_def`。

规则：

1. 推荐写法：`@dg.asset_check(asset=silver_stock_daily, blocking=True)`。
2. 避免写法：`@dg.asset_check(asset="silver_stock_daily", partitions_def=cn_a_trade_days, ...)`。
3. 原因：当前 Dagster 版本在 `asset_check` 上显式指定 `partitions_def` 会触发 preview warning；绑定 partitioned asset 对象时，check 会继承 asset 的分区语义。
4. 验证 partitioned checks 时，必须显式传入 `partition_key`；否则不能说明具体交易日分区已经验收。
5. 读取 `ASSET_CHECK_EVALUATION` 事件时，`event.event_specific_data` 本身就是 `AssetCheckEvaluation`；不要再访问不存在的 `.asset_check_evaluation` 属性。

### 提交前检查门禁

提交前必须看 `git status --short`，不能只看 `git diff --stat`。

原因：

1. `git diff --stat` 不显示未跟踪的新文件。
2. Dagster slice 经常新增 asset/check/job 文件；若只看 diff stat，容易漏掉 untracked 文件。
3. 提交前必须确认新增文件、修改文件、生成物是否都符合本轮范围。

### Dynamic Partitions 持久化门禁

注册 dynamic partitions 时，必须使用正式 Dagster instance。

规则：

1. 本地验证 dynamic partition 注册时，必须显式使用正式 `DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home` 对应的 `DagsterInstance`。
2. 若使用 `job.execute_in_process()` 验证注册逻辑，必须传入 `instance=DagsterInstance.get()`。
3. 验证注册结果时，必须从同一个正式 instance 调用 `get_dynamic_partitions(...)` 读取。
4. 禁止用默认 `execute_in_process()` 的临时 instance 验证 dynamic partition 注册结果。
5. 禁止看到 job `success=True` 就认定 partition keys 已持久注册。

---

## Tushare 数据源依据门禁

本目录会逐步承接 Tushare 相关 raw / silver / gold 资产。涉及 Tushare 数据源时，必须区分“资料理解”和“真实接口核验”。

使用分工：

1. 想获取 Tushare 数据源中数据集的相关信息时，可以使用 `tushare-data` skill 辅助理解，例如接口家族、数据域背景、常见字段、可能相关接口、研究路径和自然语言需求到接口能力的映射。skill 路径：`/Users/congming/.codex/skills/tushare-data/SKILL.md`。
2. 想实测请求接口、验证真实输入输出返回值、确认字段是否真实返回、样本行数、分页行为、日期过滤、权限积分或空结果原因时，必须使用 `tushareMcp` 做真实请求核验。
3. `tushare-data` skill 只能做理解与选型辅助，不能替代当前代码、`docs/sources/tushare/**`、旧数据湖实际 parquet 和 `tushareMcp` 实测。
4. 设计或实现 `raw_tushare_*` asset、Tushare resource、字段契约、asset checks、分区口径、数据完整性判断前，必须先说明依据来自哪里：当前代码、本地 Tushare 文档、旧湖 parquet、`tushare-data` skill、`tushareMcp` 实测。
5. 若本地文档、旧湖 parquet 和 `tushareMcp` 实测不一致，必须显式记录差异，并以“当前代码 + 旧湖实际数据 + 实测行为”校准第一期实现；禁止带着未核清口径继续编码。

禁止：

1. 只凭接口名、字段名、历史印象或 `tushare-data` skill 直接写 Dagster asset/check/resource。
2. 在没有 `tushareMcp` 实测的情况下，断言某个 Tushare 接口真实支持或不支持某种参数、字段、分页、日期过滤或全量/增量模式。
3. 把一次未显式请求关键字段的返回结果，当成“接口没有该字段”的证据。

---

## 新数据湖路径硬约束

Dagster 新数据湖只使用以下三层路径：

```text
data_lake/raw
data_lake/silver
data_lake/gold
```

规则：

1. 资产分类只认 `raw` / `silver` / `gold`。
2. 旧数据湖路径不再作为任何新 Dagster asset 的正式 path。
3. 新 Dagster asset path 禁止出现旧路径概念，包括但不限于：

```text
raw_tushare
manifest
derived
research
lake_jobs
duckdb_compute/runs
duckdb_compute/_tmp
```

4. 旧数据湖不是废弃数据，而是迁移来源。
5. 迁移一个数据集时，可以读取、审计、复制、对比旧路径数据，但最终新资产必须落到 `data_lake/raw|silver|gold`。
6. 不得在未获明确指令前创建移动盘目录、复制大数据文件或重写历史数据。

### DuckDB 读取 raw parquet 门禁

读取 `trade_date=...` 这类 Hive 分区目录下的 raw parquet 时，DuckDB 默认可能从目录名推断同名分区列。

规则：

1. 若目的是核验文件内部 raw 字段契约、字段类型或源站镜像口径，必须使用 `hive_partitioning=false`。
2. 若目的是按数据湖分区批量读取数据，必须明确说明使用的是目录分区列还是文件内部字段。
3. 禁止把 DuckDB 自动推断出来的目录分区列，误当成 parquet 文件内部真实字段。

### Silver 层时间字段标准化门禁

`raw` 层保持源站镜像口径，`silver` 层负责形成 Goldenshare 内部稳定可计算的数据事实。因此 `silver` 层必须对时间语义字段做类型标准化，但不能断章取义、机械转换。

规则：

1. `silver` 层中具备明确“日期”语义的字段必须标准化为 `DATE`，例如 `trade_date`、`list_date`、`delist_date`、`cal_date`、`pretrade_date`、`ann_date`、`start_date`、`end_date`。
2. `raw` 层中的同名字段仍按源站契约保留，例如 Tushare `daily.trade_date` 在 raw 中保持 `YYYYMMDD` 字符串。
3. 具备具体时刻语义的字段不得硬转 `DATE`，应按真实语义标准化为 `TIMESTAMP` 或保留为字符串，例如 `trade_time`、`update_time`、`created_at`、`datetime`。
4. 周期、月份、报告期、财报期等字段不得按字段名直接转 `DATE`，必须先定义语义再确定类型，例如 `period`、`report_period`、`end_date` 在不同接口中可能分别表示月份、报告期或自然日期。
5. 对时间字段类型做任何修改前，必须核验源接口文档、旧湖实际 parquet 和当前代码消费者；禁止只凭字段名猜测类型。
6. 相关 asset checks 必须围绕标准化后的类型设计，例如 `silver_stock_daily.trade_date` 应按 `DATE` 与 partition key 比较，而不是按 raw 字符串比较。

---

## 数据资产迁移门禁

迁移策略是：

```text
理清一个数据集 -> 设计一个数据集 -> 迁移一个数据集
```

禁止批量迁移。

每个数据集迁移前，必须先形成设计记录，至少回答：

1. 数据集名称、业务含义、来源系统。
2. 旧数据湖来源路径，仅作为迁移输入。
3. 新 Dagster asset key。
4. 新物理路径，必须位于 `data_lake/raw`、`data_lake/silver` 或 `data_lake/gold`。
5. 所属层级：`raw` / `silver` / `gold`。
6. 分区模型：无分区、`trade_date`、`event_date`、`freq + trade_date`、`freq + trade_month + bucket` 等。
7. 上游资产和下游消费。
8. 所需 resources。
9. asset checks / data contract。
10. backfill 策略和失败重试口径。
11. 迁移验证方式：行数、schema、主键、分区、样本、质量检查。
12. 是否需要同步到本地 ClickHouse serving。
13. 是否涉及发布包或 `goldenshare_lake_meta`。

没有完成上述设计，不允许写 Dagster asset 代码。

---

## Resource 迁移门禁

新增或迁移任何 Dagster resource 前，必须先完成配置和边界审计，至少列清：

1. resource 名称。
2. 管理的外部能力：Lake Root、DuckDB、Tushare、PostgreSQL、ClickHouse、Kopia 等。
3. 配置来源与持久化位置。
4. 是否包含敏感信息。
5. 是否允许 `dg dev` 启动时失败。
6. 是否只在 asset 执行时检查。
7. 消费它的 assets/checks/schedules。
8. 测试替身或 mock 方案。
9. 失败时如何暴露给 Dagster run/check/log。
10. 是否会写入业务数据、metadata 或外部系统。

默认原则：

1. `LakeRootResource` 不应阻断 `dg dev` 启动；应在 lake asset 执行前检查可用性。
2. `TushareResource` 缺 token 时不应让整个 code location 崩掉；只让依赖它的 asset 失败。
3. `TushareResource` token 必须通过 `dg.EnvVar("TUSHARE_TOKEN")` 注入；本机变量由 `~/.bash_profile` 提供。禁止硬编码 token，禁止写入 `dagster.yaml`、`.env`、`~/.goldenshare/*.sh`、设计文档、Parquet metadata、Dagster materialization metadata 或日志。
4. `DuckDBResource` 必须约束临时目录和输出路径，不允许把大计算 spill 写到未知系统目录。
5. `PostgreSQL` 分清 Dagster 内部库 `goldenshare_dagster` 和业务 metadata 库 `goldenshare_lake_meta`。
6. `ClickHouseResource` 只服务本地 serving 表，不代表生产查询链路。

---

## 已确认架构口径

1. Dagster asset 以 `LakeNodeDefinition` 粒度迁移，不以 `LakeDatasetDefinition` 粒度粗暴迁移。
2. `manifest` 是历史物理目录，不是资产层级。
3. `lake_jobs/*`、`duckdb_compute/runs/*`、`duckdb_compute/_tmp/*` 属于历史运行账本，应逐步退场给 Dagster。
4. `research/stk_mins_by_date_clean_next` 在 qfq 前是 silver；qfq 后结果必须拆成独立 gold asset，不能原地替换造成语义混乱。
5. `goldenshare_lake_meta` 不急于建表；真需要业务账本时再设计。

---

## 交付要求

每次在本目录完成任务后，必须说明：

1. 目标与依据，包含查阅的 Dagster 官方文档或本地 help。
2. 改动文件。
3. 是否影响 `data_lake/raw|silver|gold` 路径口径。
4. 是否新增或修改 Dagster asset/resource/check/partition/schedule/backfill。
5. 验证结果。
6. 风险与下一步。
