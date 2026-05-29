# AGENTS.md — Dagster Orchestrator 目录规则

## 适用范围

本文件适用于 `lake_console/orchestrator/` 及其所有子目录。

本目录是正式 Dagster 项目，不是学习项目、临时项目或实验目录。

上级规则仍然生效：仓库根 `AGENTS.md` 与 `lake_console/AGENTS.md` 的约束必须继续遵守；若本文件与上级规则冲突，以更严格、更靠近本目录的规则为准。

编码、重构、命名、文件组织变更前，必须遵守本目录长期编码规范：`lake_console/orchestrator/CODING_STANDARDS.md`。该文档是硬门禁，后续新增编码规范优先追加到该文档。

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

### 正式 Dagster 环境执行门禁

当前本地 Dagster 环境按正式生产环境对待，不是测试环境，也不是可以随意试跑的沙盒。

规则：

1. 禁止 Codex 未经用户明确批准自行运行任何 Dagster 执行动作，包括但不限于 `dg`、`dagster`、`uv run dg`、job、sensor、backfill、materialize、asset check、automation evaluation、临时 Python evaluator 或任何会读取/触碰正式 Dagster instance 的脚本。
2. 禁止把正式 Dagster instance、正式数据湖、正式 PostgreSQL、正式 Tushare token 或正在运行的任务当作 test case 使用。
3. 允许在不触发 Dagster 执行、不读取正式运行状态、不写正式环境的前提下做静态分析，例如阅读代码、阅读文档、搜索文件和整理方案。
4. 如确实需要执行任何 Dagster 相关命令，必须先列出完整命令、工作目录、目标 `DAGSTER_HOME`、读写范围、可能影响、回滚方式和为什么必须执行，等待用户明确同意后才能运行。
5. 即使只是“验证一下 evaluator / check / definitions”，只要会访问正式 instance、正式湖、正式数据库或可能干扰正在运行的任务，也必须按生产操作审批，禁止自行执行。
6. 用户未明确批准时，任务收口只能说明“未运行验证，原因是正式 Dagster 环境执行门禁”，不能用自行试跑来替代审计。

### 设计确认先于代码修改门禁

任何 Dagster 相关代码改动必须先完成设计确认。禁止一边想一边改、先改了再解释、先写代码再补方案。

规则：

1. 涉及 asset、resource、check、job、sensor、partition、backfill、automation、metadata、路径、字段契约、数据质量口径或生产触发逻辑的任何改动，必须先输出设计方案、影响范围、涉及文件、数据读写影响、验收方式和风险点。
2. 用户明确确认设计方案前，禁止修改正式 Python 代码、配置文件、Dagster definitions、数据湖文件、数据库表或运行入口。
3. 用户指出现有实现有问题时，默认先做代码审计和方案讨论；不得直接把口头理解落成代码。
4. 如果需要先做验证来支撑设计，必须把验证方案单独列出并等待用户批准；验证不得触碰正式 Dagster 生产环境，除非用户明确批准并接受影响范围。
5. 文档修改也要区分“记录已确认口径”和“提出待确认方案”；未经确认的方案不得写成已实现或已拍板事实。
6. 紧急修复也不能绕过设计确认；至少必须先说明要恢复什么、为什么恢复、会改哪些文件、是否会影响正在运行任务，并等待用户批准。

### 正式方案优先门禁

Dagster orchestrator 是正式项目，不接受“先跑通再说”的默认开发方式。任何进入正式代码、正式文档、正式 Definitions、正式数据湖路径或正式数据库对象的设计，必须按长期方案对待。

规则：

1. 默认输出正式方案，不得用“先跑通”“临时先这样”“以后再补”掩盖设计评估不足。
2. 正式方案必须在设计阶段考虑长期契约、字段 schema、definition metadata、materialization metadata、asset checks、UI 可观测性、自动化边界、迁移成本、退场成本和文档同步。
3. 如果确实需要验证系统能力，必须明确标记为“验证动作”或“验证代码”，不得伪装成正式链路，不得接入 active Definitions，不得写入正式数据湖或正式数据库，除非用户明确批准。
4. 验证代码或验证配置必须有明确删除条件、负责人为当前任务、清理步骤和验收方式；禁止让验证代码沉淀成历史包袱。
5. 对 Dagster、ClickHouse、Tushare、schema metadata、automation、checks、partitions 等平台能力不确定时，必须先查官方文档、看当前代码、必要时做经批准的最小验证；禁止不懂装懂或凭印象编码。
6. 新增正式资产时，稳定字段契约应优先写入 asset definition metadata；materialization metadata 只记录本次运行实际结果，例如 path、row_count、observed columns、样本和统计。不得只依赖 materialization metadata 承载正式资产契约。
7. 若发现早期实现是为了验证或过渡而遗留的临时口径，必须主动提出清理或重构方案，不能继续在临时方案上叠补丁。

### 文档目录归档门禁

`lake_console` 下的 Dagster 相关文档必须按文档职责归档，禁止继续散落在 `lake_console` 根目录或随手新建目录。

当前固定目录：

```text
lake_console/docs/design        # 设计方案、阶段方案、LLD、迁移方案、重构方案
lake_console/docs/architecture  # 架构说明、系统关系、资产/Job 拓扑、长期结构说明
lake_console/docs/templates     # 开发模板、资产说明卡模板、迁移检查清单、方案模板
```

规则：

1. 新增或迁移设计相关文档，必须放到 `lake_console/docs/design/`。
2. 新增或迁移架构说明相关文档，必须放到 `lake_console/docs/architecture/`。
3. 新增或迁移开发模板相关文档，必须放到 `lake_console/docs/templates/`。
4. 如果某个文档同时具备多种属性，按主要用途归档；必要时在其它文档中用链接引用，不复制多份。
5. 修改旧文档路径时，必须同步修正文档之间的链接和引用，避免出现死链或旧路径口径。
6. 新增文档前必须先判断是否应更新已有设计文档，禁止为同一主题不断新增平行文档导致口径分裂。

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

### 上游基础资产只读依赖门禁

业务 gold job 依赖上游基础资产时，必须先校验上游是否已经满足生产条件，再只读消费；禁止把共享基础资产随手加入业务 job 的 selection 里一起写。

规则：

1. `stock_basic`、`trade_calendar`、`suspend_d` 这类会被其它资产消费的上游事实资产，必须有明确且唯一的正式更新入口。
2. 下游业务 job 只能通过 readiness / blocking checks 确认基础资产已 materialized、checks 已通过、freshness 满足当日生产条件。
3. 下游业务 job 不得为了“省一步”把 `raw_tushare_stock_basic`、`silver_stock_basic`、`raw_tushare_trade_calendar`、`silver_trade_calendar` 等共享基础资产放入自己的 selection。
4. 如果某个下游业务确实需要从 raw 到 silver 到 gold 的组合入口，必须在方案文档中单独说明该 job 的写入范围、只读依赖范围、重复执行影响和并发保护；不能默认扩大 selection。
5. `stock_basic` 虽然是 full snapshot、不是 `trade_date` 分区资产，但新股上市会影响当日日线标准化和完整性检查，因此应按“日更全量快照基础资产”设计 freshness，不应简单归为低频资产。
6. `suspend_d` 是 `stock_daily` 生产前必须准备好的上游资产；`stock_daily` 生产 job 只读依赖 `silver_stock_suspend_daily`，不得把 `raw_tushare_suspend_d` / `silver_stock_suspend_daily` 放进自己的 selection 中顺手更新。
7. 每个涉及共享基础资产的方案文档必须列清：负责写入的 job、只读消费的 jobs、readiness 条件、blocking checks、更新频率、失败时下游行为。

### Readiness 与 Sensor 触发门禁

任何 sensor、schedule、declarative automation 或手动触发链路在判断下游是否可以生产时，禁止只看“文件存在”或“asset 曾经 materialized”。

规则：

1. ready 必须至少包含目标上游 asset 已 materialized，且该 asset 对应的 blocking checks 全部通过。
2. full snapshot 资产还必须额外判断 freshness，例如 `stock_basic` 是否满足当日生产需要；不能因为历史上 materialized 过就永久视为 ready。
3. partitioned 上游资产必须按同一个 `partition_key` 判断 materialization 和 checks，例如 `silver_stock_suspend_daily[trade_date]`。
4. WARN checks 只作为观测信号，不阻断生产；但 WARN metadata 必须可见，不能被静默吞掉。
5. sensor 只能提交满足门禁的 `RunRequest`；门禁不满足时返回清晰 `SkipReason` 或不请求下游，不得在下游 job 内部补上游。
6. `cn_a_trade_day_sensor` 的长期职责应收敛为注册已完成交易日 partition；各资产族可以有自己的 sensor，例如 `suspend_d_sensor`、`stock_basic_sensor`、`stock_daily_sensor`，分别围绕本资产族判断缺失、freshness、checks 和上游 ready。
7. 新增资产族 sensor 前，方案文档必须列清：输入状态、ready 条件、run key、cursor 内容、最大单 tick 请求数、失败重跑策略、是否允许注册 partition，以及与其它 sensor 的边界。
8. 分区范围、日期边界、资产族归属这类质量门禁，优先实现为正式 blocking asset check；禁止在业务 asset 写入函数里混入定制化的写前 guard，除非方案文档明确批准这种异常设计。

### Declarative Automation 验证门禁

涉及下游自动触发时，不能只看 Dagster API 名字就假设它能覆盖全部质量门禁。

当前 Dagster 1.13.6 已验证的口径：

1. `AutomationCondition.all_deps_blocking_checks_passed()` 可以判断直接上游 asset 的 blocking checks 是否通过。
2. 该条件只覆盖直接 asset deps，不会自动穿透检查间接上游或共享基础资产；不要把“直接 deps checks 通过”误当成“整条上游链路 ready”。
3. 如果某个下游业务资产的真实直接输入就是一个标准事实资产，例如 `gold_market_breadth_daily` 只消费 `silver_stock_daily`，则可以只围绕这个直接输入和它的 blocking checks 设计 declarative automation；`suspend_d`、`stock_basic`、`trade_calendar` 的门禁应在生产 `silver_stock_daily` 的链路里解决。
4. 如果某个下游确实需要多个非直接前置条件，必须设计显式 readiness gate、readiness asset，或经过确认的 asset sensor 后备方案；禁止为了省事把非直接前置条件假装成直接 deps。
5. `AutomationCondition.on_missing()` 带有 cursor / initial evaluation 语义，不能在一次性小样本验证中简单等同于“当前资产缺失”；做 API 验证时必须明确使用场景并记录结果。
6. 启用新的 declarative automation 前，必须先用临时 Definitions 验证条件行为，再只读检查正式 Dagster instance 中 materialization 和 check 状态可被可靠读取。

### 历史批量审计与事件补录门禁

历史 bootstrap、历史 backfill、runless event 补录、批量 readiness 复核这类动作，不能照搬日常 sensor 的逐分区 readiness 写法。

规则：

1. 开始任何历史批量操作前，必须先估算操作量，至少列出：partition 数、asset 数、blocking check 数、预计 event log 查询次数、预计写入文件数、预计补录 event 数。
2. 若分区数超过 100，或 `partition_count * blocking_check_count` 超过 1000，禁止在 dry-run 中逐分区调用 `asset_readiness_status(...)` 做全量深扫。
3. 大批量历史审计必须优先使用批量口径：materialized partition 集合、registered partition 集合、文件分区集合、每个 check 的 succeeded/failed 计数、集合差异和少量样本 readiness。
4. `asset_readiness_status(...)` 适用于日常 sensor、单日 repair、小样本验证和最终抽样，不适合作为上千分区历史 dry-run 的主循环。
5. 正式执行方案必须区分“日常门禁”和“历史批量审计”：日常门禁判断某个分区能不能跑；历史批量审计判断整体集合是否一致、是否全绿、是否存在差异样本。
6. 对 runless event 补录，必须先用批量只读审计确认上游 event 事实和文件事实，再按 dry-run、小样本、全量执行；不得在全量命令里重复做高成本逐分区 event history 深扫。
7. 如果执行中发现 dry-run 明显慢于预期，必须停下重新评估查询模型，优先改成聚合审计或分批审计；禁止硬等或继续扩大到写入阶段。
8. 任何新增历史批量 helper，都必须在设计文档中写清楚采用的是聚合审计还是逐分区审计；若选择逐分区审计，必须解释规模为什么可接受。

### Full Snapshot 并发保护门禁

`stock_basic` 这类 full snapshot asset 写的是单个全量文件。并发运行时，即使 `.tmp + os.replace` 能避免半截文件，也可能出现重复打接口、后完成 run 覆盖先完成 run、metadata 观测混乱等问题。

规则：

1. 设计主线是减少重复写入：共享 full snapshot asset 只能由自己的正式更新 job 负责写入。
2. 并发保护是保险丝，不是放任多个业务 job 都写同一个 asset 的理由。
3. 对 full snapshot asset 或其更新 job，如存在并发触发风险，方案文档必须分析是否需要 Dagster concurrency 限制。
4. 可选保护包括 run queue limits、concurrency pools、run executor limits、run tag concurrency limits 等 Dagster 官方并发机制；使用前必须查当前 Dagster 官方文档和本地版本行为，不得凭记忆配置。
5. 如果启用 Dagster concurrency，必须同步说明配置位置、作用范围、排队表现、UI 可见性、失败/取消后的恢复方式，以及是否依赖 PostgreSQL instance storage。
6. 禁止用自造锁文件、临时 pid 文件或散落脚本锁替代 Dagster 正式并发机制；若确需外部锁，必须先单独设计并获确认。

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
6. 日频资产不得默认共用全局交易日分区。正式生产资产必须按资产族选择 partition definition，例如股票行情使用 `cn_a_stock_trade_days`，指数行情使用 `cn_a_index_trade_days`。
7. `cn_a_trade_days` 只作为全量 SSE open day 备份和对照分区集合保留；新增生产 asset、sensor、history backfill 不得依赖它作为正式业务分区。
8. 扩展某个资产族历史范围时，必须同时说明该资产族分区起点、注册来源、是否影响其它资产族 sensors，以及是否需要保留或更新全量备份分区。
9. 如果历史范围拆分影响既有资产族，必须先完成生产资产、sensors、automation、jobs 的分区切换，再扩展全量备份分区；不得先扩大共享分区后再补迁生产链路。
10. 任何 dynamic partition 范围扩展都必须先做消费者审计，至少覆盖：assets、asset checks、jobs、sensors、automation condition sensors、history/backfill 入口和 readiness helper；审计未清零前不得运行注册或生产任务。
11. 调整分区事实源时，必须先关闭相关 sensors / automation，再完成代码切换、`dg check defs`、preview 验证和小范围只读审计，最后才允许注册更大范围分区。

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
