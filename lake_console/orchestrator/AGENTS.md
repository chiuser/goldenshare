# AGENTS.md — Dagster Orchestrator 目录规则

## 适用范围

本文件适用于 `lake_console/orchestrator/` 及其所有子目录。

本目录是正式 Dagster 项目，不是学习项目、临时项目或实验目录。

上级规则仍然生效：仓库根 `AGENTS.md` 与 `lake_console/AGENTS.md` 的约束必须继续遵守；若本文件与上级规则冲突，以更严格、更靠近本目录的规则为准。

编码、重构、命名、文件组织变更前，必须遵守本目录长期编码规范：`lake_console/orchestrator/CODING_STANDARDS.md`。该文档是硬门禁，后续新增编码规范优先追加到该文档。

任何 Dagster 相关设计方案或正式代码开发开始前，必须先阅读并遵守 `lake_console/orchestrator/CODING_STANDARDS.md` 和 `lake_console/docs/design/dagster-asset-schema-contract-design.md`；禁止在未核对编码规范与 asset schema contract 口径的情况下输出方案或进入编码。

涉及数据集、sensor、run-status sensor、readiness、asset check、bootstrap、runless event、DuckDB/Parquet 计算或任何性能敏感的数据管道改动时，还必须先阅读并遵守 `lake_console/docs/design/dagster-data-pipeline-performance-governance.md`。

---

## 项目定位

`orchestrator` 是 Goldenshare 当前正式的 Dagster 数据湖编排工程。

当前边界：

1. 用 Dagster 管理本地数据湖资产、依赖、分区、检查、调度、回填、日志与运行状态。
2. 旧 Console frontend/backend、Kopia、旧专属入口和测试已在清退 M6 同轮删除；保留本工程、reports 与 ClickHouse 工具。
3. 资产事实以当前 catalog、paths、schema、run contract 和消费者为准；旧实现仅从 Git 追溯，不恢复导入或兼容入口。

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

### Python 环境与静态测试命令

`lake_console/orchestrator` 是独立的 `uv` 项目。测试和静态检查必须从本目录运行，并使用本项目 `.venv` 中的解释器与工具；不得依赖仓库根环境、全局 Conda 工具或手工 `PYTHONPATH`。

固定命令：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
uv sync --group dev
uv run python -m pytest -q tests/<target_test_file.py>
uv run ruff check --select E9,F63,F7,F82 src tests
uv run ruff check <本次修改的 Python 文件>
```

规则：

1. 禁止使用裸 `pytest`、裸 `python` 或 `PYTHONPATH=src pytest ...` 运行本项目测试；统一使用 `uv run python -m pytest ...`，确保 pytest 与被测代码绑定同一个解释器。
2. `orchestrator` 由 `uv` 以 editable package 安装，正常环境不需要设置 `PYTHONPATH`。出现 `ModuleNotFoundError` 时，禁止先追加 `PYTHONPATH` 掩盖环境问题。
3. import 失败时，先在本目录执行 `uv run python -c "import sys, orchestrator, dagster, pytest; print(sys.executable); print(orchestrator.__file__)"`，确认解释器和项目安装状态；失败时修复 `uv` 环境，不得切换到全局 Conda 继续运行。
4. 全仓 Ruff 先执行已可通过的致命错误基线 `E9,F63,F7,F82`；本次修改的 Python 文件还必须执行默认规则检查。不得把仓库既存风格债务伪装成本轮回归，也不得因此跳过本次改动文件的完整检查。
5. `pytest` 与 `ruff` 必须登记在本项目 `pyproject.toml` 的 `dev` dependency group 并进入 `uv.lock`，不得依赖本机额外安装。
6. 上述 pytest/ruff 命令只允许静态或隔离测试；任何会访问正式 Dagster instance、正式 Lake、数据库或网络的测试，仍受“正式 Dagster 环境执行门禁”约束。

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

### 开发执行自检门禁

任何按计划推进的 Dagster 开发任务，在编码前必须先把计划转成可执行自检清单，禁止靠“我记得”“应该差不多”推进。

规则：

1. 编码前必须列出本轮硬口径：`必须`、`禁止`、`不做`、`默认`、`边界`、`验收`。如果无法列清，必须先停下补方案，不能直接改代码。
2. 每条硬口径必须映射到具体落点：asset、check、job、sensor、resource、helper、SQL、metadata builder、cursor、CLI、测试或文档；不能只停留在设计描述。
3. 每条硬口径必须有正反测试或静态门禁。凡是“禁止新增”“只允许”“默认不做”“不得自动触发”这类规则，都必须有反例测试或静态扫描防回退。
4. 不得默认新增状态实体、summary asset、readiness asset、repair summary、数据库表或配置项来承载运行说明。除非用户明确拍板，优先用 run、asset check metadata、materialization metadata、cursor 或文档审计记录表达状态。
5. 开发前发现现有设计文档、当前代码、正式数据事实或用户最新口径不一致时，必须先说明冲突并等待确认；禁止用代码补丁绕过口径冲突。
6. 提交前必须做计划对账：说明硬口径分别落到哪些代码、哪些测试、哪些验证；未落地项必须显式说明原因，不能默认算完成。

### Dagster Definition 命名门禁

新增或改名正式 asset、check、job、sensor 前，必须按 `lake_console/orchestrator/CODING_STANDARDS.md` 中的 “Dagster Definition 命名规则” 先列清最终名称并完成对账。

规则：

1. job 名称固定为 `layer + asset name + mode + job`，例如 `raw_stock_daily_update_job`。
2. sensor 名称固定 follow job，即 `job name + sensor`。
3. 新增 check 名称固定为 `asset name + function + check`。
4. 已存在 check 禁止仅为了符合新命名规则而改名；确需改名必须先单独评估历史 check event、readiness、sensor、job selection、UI 状态和补跑成本，并等待用户确认。
5. 不得新增一个同语义新名 check 来替代旧 check。

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
6. 禁止解析 `run_key` 生成 `run_config`；`run_key` 只用于幂等去重。执行参数只能来自显式 `run_config`、`partition_key`、上游 metadata/status，或正式定义的 `upstream_batch_id`。
7. `cn_a_trade_day_sensor` 的长期职责应收敛为注册已完成交易日 partition；各资产族可以有自己的 sensor，例如 `suspend_d_sensor`、`stock_basic_sensor`、`stock_daily_sensor`，分别围绕本资产族判断缺失、freshness、checks 和上游 ready。
8. 新增资产族 sensor 前，方案文档必须列清：输入状态、ready 条件、run key、cursor 内容、最大单 tick 请求数、失败重跑策略、是否允许注册 partition，以及与其它 sensor 的边界。
9. 分区范围、日期边界、资产族归属这类质量门禁，优先实现为正式 blocking asset check；禁止在业务 asset 写入函数里混入定制化的写前 guard，除非方案文档明确批准这种异常设计。

### Sensor Hot Path 性能分析门禁

日常 sensor、run-status sensor、continuity selector、readiness gate 这类热路径的性能分析，必须先优化读取模型，再讨论新增状态实体。禁止只复现当前慢实现的逐日期、逐 asset、逐 check 深扫结果，就直接下结论新增 summary asset、status manifest、数据库表或配置项。

规则：

1. 性能审计必须先列清读取次数模型，至少包括：窗口日期数、asset 数、blocking check 数、Dagster event/check history 查询次数、每次查询 limit、反序列化记录数、DuckDB 扫描文件数和预计行数。
2. 测量必须区分三类结果：当前实现耗时、batch 后的 Dagster metadata 读取耗时、DuckDB/lake 文件事实读取耗时。不能只测当前实现，也不能只测单日样本后推断整段窗口。
3. 遇到 `日期 * asset * check` 级别循环时，必须先设计 batch 方案：按 asset 一次读取 materialization 集合，按 check key 一次读取 check records，再在内存里映射窗口日期；禁止默认继续逐日期调用 `asset_readiness_status(...)` 或 `dataset_readiness_status(...)`。
4. 判断 20 天、60 天或其它窗口大小前，必须先用 batch 读取模型测量；如果 batch 后 20 和 60 成本接近，窗口大小不能被误判为根因。
5. 对可以从 lake 文件事实判断的 readiness，例如文件存在、row count、schema、freq/date、唯一键和基础质量统计，必须优先评估 DuckDB 批量读取 Parquet 的方案；Dagster event log 只承载调度事件和 check 记录，不应默认作为大窗口数据事实扫描源。
6. DuckDB/lake readiness 不得偷换完整 blocking check 语义。正式实现必须复用或抽取现有 check SQL/契约语义；只能把“文件存在 + row count”作为性能基准或粗筛，不能冒充完整 ready。
7. 新增 status manifest、readiness asset、summary asset、数据库表或其它状态实体前，必须证明：现有 Dagster metadata batch 查询和 DuckDB/lake 文件事实查询都不能满足正确性或性能要求；同时列清新增实体的一致性风险、写失败语义、回补方式、路径/schema 契约和退出成本。
8. profiling 输出必须包含真实数字，不得只写“很慢”或“应该更快”。至少记录：窗口范围、读取次数、记录数、文件数、耗时、最慢查询样本，以及是否触发超时或预算上限。
9. 若 profiling 过程中发现测量脚本本身采用了低效逐日期深扫，必须停下重写测量方法；禁止把错误测量结果当成方案依据继续推进。
10. 任何 sensor hot path 优化完成后，必须增加静态门禁或单元测试防回流，确保正式路径不会重新出现未批准的逐日期 event history 深扫。

### Sensor Definition Tags 分类门禁

Sensor definition tags 是 Automation 页面筛选和运维分类的一部分，不是 run tags，也不是 cursor 或 run config。

规则：

1. 新增或修改正式 sensor 前，方案文档必须列清该 sensor 的 `goldenshare/sensor_domain`、`goldenshare/sensor_target_layer`、`goldenshare/sensor_role`。
2. sensor 分类必须优先对齐 asset data domain；非资产生产类通知 sensor 使用正式 `platform_observability` domain，不得强行归入业务资产域。
3. 落地 sensor definition tags 后，所有 active sensor definition 都必须通过统一 helper 构造分类 tags；禁止 sensor 文件手写散落 tag dict。
4. 新增 sensor 时必须同步更新 `dagster-run-contract-governance.html`、`dagster-asset-job-topology.html` 中的 sensor 分类口径和静态门禁测试，禁止只新增 Python sensor definition 导致 Automation 页面分类退化。
5. sensor definition tags 不得包含日期、分区、代码、行数、成功/失败状态、cursor offset、缺失数量等动态信息。
6. 禁止用 `run_tags` 做 sensor 分类；`AutomationConditionSensorDefinition` 同时有 `tags` 和 `run_tags` 参数，分类只能写 definition `tags`。

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

### 直写补录模式门禁

直写补录模式，全称 `Direct Lake Bootstrap + Runless Event Backfill`，指历史大批量数据不通过 Dagster backfill 逐分区执行 asset，而是先用受控 helper / CLI 直接生成或迁移 lake parquet 文件，再用 runless materialization / asset check events 把文件事实补录为 Dagster event 事实。

该模式是 `stk_mins` silver / gold 历史初始化已经采用的正式模式。后续类似历史大批量 silver/gold 初始化、基于获准正式来源的物理布局重建，可以复用这个名字和流程。

规则：

1. 直写补录模式只适用于历史大批量初始化、迁移或重建；日常增量必须走正式 asset job / sensor，不能用直写补录绕过 Dagster 日常链路。
2. 直写补录不是 Dagster backfill。方案文档和执行说明必须明确区分：文件生成阶段、runless event 补录阶段、最终聚合审计阶段。
3. 文件生成阶段必须先 dry-run，再样本，再分批全量；每批写入前必须确认输入完整、目标冲突、预计文件数、预计行数和回滚方式。
4. event 补录阶段必须先 dry-run，再样本，再分批全量；补绿 event 前必须确认对应文件事实和 blocking check 事实全部通过。
5. 大批量补录必须使用聚合审计、集合差异、年度 / 频度 / 批次维度处理；禁止按日期、按 partition、按 check 做碎循环深扫。
6. 文件写入必须遵守 Parquet 计算与写入门禁：大体量计算和写 parquet 使用 DuckDB SQL / `COPY ... TO parquet` 或等价列式能力，禁止 Python 明细循环写大文件。
7. runless event log 是追加事实；正式补录前必须说明误写后的处理方式。默认不做数据库级删除回滚，只能追加更正事件或单独设计清理方案。
8. 直写补录完成后，必须用聚合 event count、文件集合差异、少量样本 readiness 做最终验收；不得用全量逐分区 readiness 深扫作为主验收方式。

### Parquet 计算与写入门禁

涉及分钟线、日线、历史 bootstrap、日常增量、silver/gold 派生、qfq、repair、runless event 前置审计等正式 lake Parquet 数据处理时，禁止用 Python 手搓明细计算或逐行写 Parquet。

规则：

1. 正式 lake parquet 的计算、过滤、join、聚合、去重、修复合并和写入必须优先使用 DuckDB SQL、`COPY ... TO parquet` 或等价的向量化/列式引擎能力；历史批量和日常增量都适用。
2. 禁止把分钟线、日线或分区明细拉回 Python 后，用 `for` 循环、list/dict 拼装、逐行计算、逐行 merge 或逐行写文件来生成正式 lake parquet。
3. Python 只允许做编排、参数校验、路径发现、批次规划、少量样本收集和结果汇总；不得承载正式数据集的大体量业务计算逻辑。
4. 若确需在 Python 中处理数据，必须证明数据规模很小且不会随历史分区、股票数量、分钟行数或日常新增量增长；方案文档必须写清行数上界和为什么 DuckDB 不适用。
5. 写正式 Parquet 时，必须使用临时文件加原子替换，例如 `.tmp + os.replace`；禁止直接覆盖目标文件导致半写入状态。
6. 历史批量写入必须先说明物理文件冲突维度，例如 `freq/ts_code/year`，并设计串行或等价互斥保护；禁止多个任务同时写同一个目标 Parquet 文件。
7. 正式 `src/orchestrator/defs/**` 中的 DuckDB 连接必须通过 `DuckDBResource` 或 `connect_configured_duckdb(...)` 统一入口创建；禁止 asset、check、bootstrap、qfq、repair、sensor readiness helper 自行 `duckdb.connect()`，测试文件除外。
8. 代码评审时，一旦发现新增 helper 在正式路径上用 Python 手工计算大体量数据、写 Parquet，或绕过统一 DuckDB 连接入口，必须停止开发，改回 DuckDB/SQL/统一连接方案后才能继续。

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

对 partitioned asset 增加 asset checks 时，必须同时绑定资产对象并显式声明与资产一致的 `partitions_def`。

规则：

1. 正式写法：`@dg.asset_check(asset=silver_stock_daily, partitions_def=cn_a_stock_trade_days, blocking=True)`。
2. 禁止只写 `asset=silver_stock_daily` 后假设 check 会自动继承分区。当前 Dagster 版本的本地 asset + checks job 回归测试证明，这种写法会让 `AssetCheckEvaluation.partition` 与 `asset_check_executions.partition` 为空。
3. 显式 `partitions_def` 当前可能触发 preview warning，但 check event 的正确分区归属优先于该 warning；不得为了消除 warning 退回空 partition event。
4. check 的 `partitions_def` 必须与目标 asset 的 partition definition 相同，并由单元测试同时断言 definition 属性、`AssetCheckEvaluation.partition` 与 `asset_check_executions.partition`。
5. 验证 partitioned checks 时，必须显式传入 `partition_key`；否则不能说明具体交易日分区已经验收。
6. 读取 `ASSET_CHECK_EVALUATION` 事件时，`event.event_specific_data` 本身就是 `AssetCheckEvaluation`；check 分区应读取 `event.event_specific_data.partition`，不得误用顶层 `DagsterEvent.partition`，也不要再访问不存在的 `.asset_check_evaluation` 属性。

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
3. `tushare-data` skill 只能做理解与选型辅助，不能替代当前代码、`docs/sources/tushare/**`、正式 Lake 上游与获准来源实际样本和 `tushareMcp` 实测。
4. 设计或实现 `raw_tushare_*` asset、Tushare resource、字段契约、asset checks、分区口径、数据完整性判断前，必须先说明依据来自哪里：当前代码、本地 Tushare 文档、正式 Lake 上游与获准来源样本、`tushare-data` skill、`tushareMcp` 实测。
5. 若本地文档、正式 Lake 上游与获准来源样本和 `tushareMcp` 实测不一致，必须显式记录差异，并以“当前代码 + 获准来源实际数据 + 实测行为”校准实现；禁止带着未核清口径继续编码。

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

4. 旧数据湖不得作为正式读取事实源、迁移输入或 staging；旧迁移适配器已在 M4 删除。
5. 数据集来源必须是当前已批准的 Tushare、Prod 只读来源、正式 Lake 上游或版本化 seed。旧湖用途审计与物理清理单列精确清单，不能据此恢复业务读取。
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
5. 对时间字段类型做任何修改前，必须核验源接口文档、正式 Lake 上游与获准来源实际样本和当前代码消费者；禁止只凭字段名猜测类型。
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
2. 当前批准的来源、字段合同与范围；禁止使用旧湖路径作为迁移输入。
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

## Asset Catalog Registry 门禁

C1 已将新湖 Dagster asset 事实收敛到 `orchestrator.defs.catalog.lake_assets`。后续新增或修改正式 active asset，必须按 registry-first 口径落代码。

规则：

1. 新增正式 active asset 前，必须先在设计记录中填写 `LakeAssetCatalogEntry` 事实卡：asset key、dataset id/name、layer/domain、group、source、data contract、字段契约、path template、partition model、ingestion/bootstrap sources、blocking checks、write/event/performance policy。
2. 代码落地时，必须同步更新 `LAKE_ASSET_CATALOG`；新增 partition model 时必须同步更新 `PARTITION_MODEL_DEFINITIONS`。
3. catalog entry 必须与 active asset definition metadata、tags、path template、`dagster/column_schema`、partition model 和 blocking check specs 一致；不得让 asset/check/job/sensor/bootstrap 各自维护一份资产事实。
4. `lake_assets.py` 是只读 registry 和 static gates 事实源，不是 Dagster resource、asset 生成器或运行时 planner。C3 以前，业务 asset/check/job/sensor 不得为了省事改成依赖 catalog 生成逻辑。
5. `lake_assets.py` 禁止 import `src.foundation`、`lake_console.backend`、Dagster instance、DuckDB、数据库、网络客户端或 lake 扫描逻辑；只能引用 orchestrator 内稳定的 schema、path、name mapping 和 run contract 常量。
6. 不得恢复测试侧手写 `ASSET_CONTRACTS`、`ASSET_PATH_TEMPLATES`、`ASSET_COLUMN_SCHEMAS` 这类隐形 catalog；治理测试必须从 `LAKE_ASSET_CATALOG` 反查事实。
7. 新增 asset/check/job/sensor/bootstrap/event helper 后，必须运行或说明未运行对应 catalog governance/static gates；如果 static gate 失败，优先修 registry 或定义事实，不得放宽门禁绕过。

---

## Resource 迁移门禁

新增或迁移任何 Dagster resource 前，必须先完成配置和边界审计，至少列清：

1. resource 名称。
2. 管理的外部能力：Lake Root、DuckDB、Tushare、PostgreSQL、ClickHouse 等（Kopia 禁止）。
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
6. 当前 `resources.py` 分别装配 `clickhouse` 与 `prod_clickhouse`，本机与生产配置、权限和消费者必须分开审计。保留已有批准链路，不能因清退旧 Console 删除生产 ClickHouse 能力。

---

## 已确认架构口径

1. Dagster asset 以当前 catalog 的独立物理资产粒度定义；旧 LakeNodeDefinition / LakeDatasetDefinition 已退出，不作为新定义来源。
2. `manifest` 是历史物理目录，不是资产层级。
3. 旧运行账本不再是当前事实源；正式运行状态与文件事实按 Dagster、当前 CLI checkpoint 和物理审计各自职责处理，不能恢复旧账本。
4. Silver 与 QFQ Gold 保持独立资产语义；旧 research/clean_next 路径不再是实现口径，不得恢复或原地混写。
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
