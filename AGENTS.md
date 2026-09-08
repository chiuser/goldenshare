# AGENTS.md — 仓库根规则（重构收尾基线）

## 适用范围
本文件适用于仓库根目录及所有子目录。若子目录存在更近的 `AGENTS.md`，以更近规则为准。

---

## 当前主体分层与辅助目录

以下区分业务分层、入口工具和占位目录，不是完整文件清单：

```text
src/
  foundation/
  ops/
  biz/
  app/
  cli.py         # CLI 入口
  cli_parts/     # CLI 实现拆分，由 cli.py 调用
  scripts/       # Python 工具入口，不是业务子系统
  shared/        # 仅包说明骨架，无共享能力主实现
  platform/      # legacy 说明目录（冻结）
  operations/    # legacy 说明目录（冻结）
qtf/             # 财势量化平台正式产品域
```

- `foundation` / `ops` / `biz` 是三个业务子系统
- `app` 是组合根（composition root），不是业务子系统
- `cli.py` / `cli_parts` 与 `src/scripts` 是入口及工具目录，不新增业务分层；`src/scripts` 与仓库根 `scripts/` 是不同目录
- `src/shared` 当前只有包说明骨架，不能据此认定已有可复用的共享实现
- `qtf` 是仓库根目录的独立产品域，只允许依赖自身与 `src.foundation`
- `platform` / `operations` 已进入 legacy 冻结态，不承接新主实现
- 数据集事实源收敛到 `src/foundation/datasets/**` 的 `DatasetDefinition`
- 数据维护执行计划收敛到 `src/foundation/ingestion/**` 的 `DatasetExecutionPlan`
- 任务运行与详情观测收敛到 `src/ops/**` 的 TaskRun 主链

---

## 动手前必读

1. `docs/architecture/subsystem-boundary-plan.md`（目录职责、依赖矩阵、现存差距与 legacy 边界的统一入口）
2. `src/AGENTS.md` 与目标目录下更近的 `AGENTS.md`

涉及 `lake_console/orchestrator` 的 Dagster 数据管道、数据集、sensor、readiness、asset check、bootstrap、runless event、DuckDB/Parquet 性能方案时，还必须阅读 `lake_console/docs/design/dagster-data-pipeline-performance-governance.md`。

---

## 角色定义（术语澄清）

1. 用户：指财势乾坤行情系统的软件使用方，可查看行情与信息，不参与系统配置与开发。
2. 运营：指财势乾坤行情系统后台工作人员，可进行配置中心文件配置、开发与维护；同时也是运营数据后台、数据湖等支撑工具的使用者。
3. 涉及“是否对外暴露参数/开关/功能”时，默认“对外”指面向用户；面向运营的能力应通过运营侧流程与配置能力承载。
---

## 协作决策原则

1. 不要假设用户清楚自己想要什么；动机或目标不清晰时，必须停下来讨论。
2. 目标清晰但路径不是最短时，必须直接指出，并建议更好的办法。
3. 遇到问题必须追根因，不打补丁；每个决策都必须能回答“为什么”。
4. 输出只说重点，砍掉一切不改变决策的信息。

---

## CodeGraph 使用规范

1. 做架构分析、重构、依赖边界调整、共享 contract 修改、dispatcher/worker/service 修改前，必须先用 CodeGraph 做上下文与影响面分析。
2. CodeGraph 分析至少要覆盖：相关入口文件、关键调用链、调用方/被调用方、跨子系统依赖、测试与前端/API 消费者。
3. 若 CodeGraph 结果显示契约消费者、依赖方向或运行链路不清晰，必须继续核验当前代码；禁止只凭文件名、方法名、历史印象或文档结论动手。
4. 对重构和 contract 变更，必须在交付说明中记录已使用的 CodeGraph 工具、分析到的影响面、仍需人工确认的边界。
5. CodeGraph 索引根为仓库根目录 `/Users/congming/github/goldenshare`；多子项目分析按目录切片，不在子目录重复初始化独立索引，除非用户明确要求。
6. 开发前默认优先用 CodeGraph：
   - 理解模块、调用链、架构入口：用 `codegraph_explore`
   - 查找符号位置：用 `codegraph_search`
   - 查调用方/被调用方：用 `codegraph_callers` / `codegraph_callees`
   - 查重构影响面：用 `codegraph_impact`
   - 查目录结构：用 `codegraph_files`
   - 查索引状态：用 `codegraph_status`
7. 开发后若切分支、pull、rebase、批量改文件或怀疑索引滞后，先执行 `codegraph sync` 与 `codegraph status`；只有 `.codegraph/` 丢失、索引异常、仓库结构大变或 CodeGraph 升级后行为不确定时，才重新执行 `codegraph init -i`。
8. 如果 CodeGraph 提示 stale lock，先执行 `codegraph unlock`，再执行 `codegraph sync`；不得删除 `.codegraph/` 或重建索引来绕过锁问题，除非已确认索引损坏。
9. CLI 可作为 MCP 备用能力，常用命令包括：`codegraph files --filter <dir> --max-depth <n>`、`codegraph query <symbol>`、`codegraph impact <symbol>`。
10. `docs/architecture/codegraph-architecture-snapshot.md` 只在仓库模块边界、关键调用链、关键 contract/adapter 或主要入口文件发生实质变化时更新；普通功能改动不要求同步更新快照。

---

## 本机服务与网络命令规则

1. 访问网络、数据库、本机服务或远程服务器前，先确认任务授权和当前工具的权限模式；已知沙箱不支持该访问时，不得先在沙箱内试探。
2. 执行方式以当前工具约束为准：需要且支持提权时，使用其规定的申请方式并说明原因；已是本机完整权限时直接执行获准命令，不传不支持的提权参数；工具禁止提权且无法执行时，说明限制，不绕过。
3. 纯本地文件读取、代码搜索、静态检查和无需网络的测试使用当前可用的本地执行环境。工具权限不替代部署、安装、数据库或 Lake 写入等业务授权。
4. 若已有批准过的命令前缀，应优先复用该命令前缀，不要绕到 Python、curl 或临时脚本里重新实现。
5. DNS、connection refused、permission denied、registry/index access 等错误不能单独证明沙箱受限。先做有针对性的只读核验，区分地址、服务状态、认证与权限问题；确认是执行环境限制后再按第 2 条处理，不反复盲试，也不擅自安装、改配置或重启服务。

---

## 管理员持续授权

1. `/private/tmp`：允许创建、修改和执行临时审计脚本及报告，无需逐次向管理员确认。
2. DG 只读审计：允许直接读取 Dagster instance、只读数据库、workspace/code location 和 lake 文件，无需逐次向管理员确认。
3. 上述授权不包含 job、sensor、materialize、backfill、runless event、动态分区或任何数据库/lake 写入；这些仍须按阶段获得管理员明确批准。
4. 工具层如因沙箱或本机权限要求弹出授权提示，仍按工具规则申请；不得把该提示误解为需要再次请求业务审批。

---

## 本机套件安装限制

1. 未经管理员明确允许，禁止在本机安装或升级套件、依赖、解释器、数据库及工具；包括包管理器操作、自动依赖同步、工具隐式下载及扩展自动安装。
2. 开发、测试、修复或“继续推进”的授权不包含安装授权。优先使用现有环境；缺少依赖时先说明具体套件、用途、安装位置和影响，获得明确允许后再安装，不能自行绕过。
3. 清理测试环境时，区分本任务新增套件与环境既有共享依赖；不得将原有 Python／Dagster 等依赖误判为本任务安装项而卸载。

---

## Codex Hook 禁用规则

1. 本仓库禁止新增、恢复或启用 repo-scoped Codex hooks，包括 `.codex/hooks.json`、`.codex/hooks/**` 以及任何 `PreToolUse`、`UserPromptSubmit`、`Stop` hook。
2. 不得用 hook 做开发门禁、提示词注入、命令阻断或交付检查；需要约束时只能写入 `AGENTS.md`、skills 或普通文档，并由用户明确确认。
3. 若当前会话因历史缓存仍引用 hook 脚本，只允许保留本地 ignored no-op 兼容文件；不得提交或恢复 hook 注册。

---

## DG Lake 路径与 Kopia 禁用规则

1. DG / Dagster orchestrator 的唯一正式 Lake 根目录是 `/Volumes/datasource/data_lake`；正式数据只能位于该根下的 `raw/`、`silver/`、`gold/` 三层。
2. DG 的 run-scoped 候选文件和执行 staging 只能位于 `/Volumes/datasource/data_lake_staging`，不得写入正式 Lake 根，也不得把 staging 当成正式数据事实源。
3. `/Volumes/datasource/goldenshare-tushare-lake` 是已退役的旧 Lake 根路径，严禁将它用作 DG 的正式根、读取事实源、写入目标、bootstrap 输入或 staging 路径；目录是否仍在不改变这一边界。
4. 旧 `lake_console/config.local.toml` 及其 `lake_root` 即使仍有本机遗留，也不能用于判断 DG orchestrator 的 Lake 根；DG 路径必须以 `lake_console/orchestrator/src/orchestrator/defs/paths.py` 和当前正式目录为准。
5. 禁止运行任何 Kopia 命令；新开发、迁移、历史补录、bootstrap、修复和写湖任务均不得新增或调用 Kopia snapshot、prewrite backup、restore、recovery 命令或服务。
6. 旧 `lake_console/backend`、`lake_console/frontend`、Kopia 实现及 `OLD_LAKE_BOOTSTRAP` / `old_lake_root` 迁移适配器已清退；不得恢复、import、复用、下沉或重新启用。历史实现只从 Git 追溯，不能作为新主链依据；本机 ignored 遗留环境不代表源码仍受维护。
7. 写湖安全必须使用候选文件完整校验、同文件系统 `os.replace()` 原子提升、逐文件 checkpoint、幂等续跑和物理对账，不得以“安全恢复”为由自行引入文件备份或快照。
8. 清退按能力和实际依赖划界，不按 `snapshot` 关键字划界。`ops.dataset_status_snapshot` 是现行状态投影，与 Kopia 备份无关，必须保留；不得把 Kopia 禁令扩展为删除其他现行 snapshot 数据模型或查询能力。
9. 若方案、LLD、代码或命令中出现与本节冲突的 Lake 路径或 Kopia 设计，必须先停止并修正文档/方案，禁止继续开发或执行。

---

## 按计划开发执行链

当用户要求“按计划开发”“按文档推进”“严格按方案执行”时，计划不只是背景材料，必须转成可核验的执行约束：

1. 先抽取计划硬口径：把计划中的“只取、必须、禁止、不做、默认、边界、口径、验收”逐条列成开发约束清单。
2. 每条硬口径必须映射到代码点：必须追到真实实现、SQL、DAO、request builder、planner、API、前端消费者或配置来源；禁止被方法名、变量名或历史印象误导。
3. 每条硬口径必须有测试：正向测试证明应支持的路径，负向测试证明禁止项不会发生；“只允许/不得/默认只取”必须有反例样本。
4. 涉及对象池、数据范围、请求量、分页、事务边界、入库范围、状态口径时，必须做真实只读验收或最小真实验证，并记录数量、样本或请求参数证据。
5. 开发完成后必须做计划对账：逐条说明计划硬口径落在哪些代码、哪些测试、哪些验证里；未落地项必须显式说明原因和风险，不能默认算完成。
6. 复用通用能力前必须审计真实语义：凡复用 DAO、planner、builder、service、selector、配置项，都必须阅读实现和消费者，确认它与本次计划口径一致。
7. 若发现计划口径与当前实现、真实数据或源接口行为冲突，必须停下来说明冲突点，等待确认；禁止靠临时补丁绕过。

---

## Prod 数据集长任务可恢复性与可观测性门禁

以下规则只适用于以 Prod 数据集为目标的同步、历史回补、大范围 PLAN / APPLY、批量计算及相关任务；这里的 Prod 数据集包括写入或更新 Prod DB 中 raw、core、core_serving 等正式数据集的任务。数据湖、Dagster、DuckDB／Parquet 和 `lake_console/orchestrator` 数据集任务不适用本节，继续遵守其自身目录规则和专项性能治理文档。Prod 数据集任务预计或实测超过 60 秒，或规模会随日期、对象、分页、分区增长且无法静态约束时，即视为长任务。

1. 开发前必须在技术方案或 LLD 明确：执行 unit、批次与内存上限、业务持久化边界、幂等键、续跑依据、进度字段、取消检查点、事务边界和最小真实验收。缺少任何一项必须停下，不能编码后再补。
2. 禁止把完整范围长期放在进程内存中并在任务末尾首次写盘。常驻内存必须与单批次相关；每个已完成独立 unit 必须形成可读回的持久化事实。
3. APPLY 取消或进程退出后必须保留已提交 unit，并能从持久化状态安全续跑；重复执行必须幂等。长 PLAN 可分批保存不可执行草稿证据，但只有完整校验并原子冻结后才能进入 APPLY。
4. 页面必须显示阶段、当前对象或窗口、完成量、总量、百分比和最后更新时间；运行中不得连续 30 秒没有可见更新。心跳只证明存活，不能作为业务进度。ETA 不可靠时必须明确显示“暂无法估算”，不得伪造倒计时。
5. 每个 unit 或分页前后必须检查取消。不可分割步骤若可能超过 30 秒，必须拆分或采用可安全中断的调用；取消后不得领取新 unit。
6. TaskRun 与当前活动 `task_run_node` 在成功、失败、取消时必须进入一致终态。状态观察写入失败不得回滚已经提交的业务数据。
7. 默认禁止使用覆盖全历史的长数据库事务。确需使用时，必须提前说明锁、空间、失败恢复与影响范围并取得批准。
8. 自动化测试至少覆盖中途取消、进程退出、续跑、幂等重放、进度单调、状态写失败不回滚业务数据和 TaskRun/节点终态一致；全量生产执行前必须完成一次代表性的真实运行—取消—续跑—读回验收。
9. 新增或修改 Prod 数据集时，必须先复制并完整填写 `docs/templates/dataset-development-template.md`；修改 `DatasetDefinition` 或 `DatasetExecutionPlan` 合同时，必须同步校准该模板，禁止代码与模板再次漂移。

---

## 硬约束

1. 不得回流主实现到 `src/platform` 或 `src/operations`。
2. 不得引入 `foundation -> ops|biz|app|platform|operations` 反向依赖。
3. 不做 big-bang 重构；每轮只做一个清晰目标。
4. 删除兼容层前必须先做引用审计，再做最小回归。
5. 禁止“无依据猜测式编码”（No source, no code）。
6. 不接受“补丁叠补丁”修复；当现有实现已进入烂代码堆积状态，必须主动提出重构或重写方案。
7. 内部重构必须按现行架构设计，不得新增旧实现兼容层、双轨逻辑或临时兜底；不得以兼容为由恢复或保留已批准清退的旧实现。
8. 不允许自己发挥，添加自己认为的功能或需求。尤其是管理员没提出来的时候。
9. 未获明确批准，不得改变正在使用的 API、CLI 和入口行为；保持现行行为不变，不等于保留旧实现或新增兼容层。
10. Ops/TaskRun/freshness/snapshot/schedule 等状态写入不得影响业务数据表的读写与事务提交；状态写入失败只能影响观测状态，不允许阻塞、回滚或污染 `raw_*`、`core_*`、`core_serving*` 等业务数据。
11. 写给人看的文档，不要写晦涩难懂，给机器看的文档。
12. 审计必须看代码，不要靠猜；不得用文档、印象、命名或历史经验替代对当前实现的逐项核验。
13. 契约变更须先获明确批准；修改前做全量实现方与消费者审计，实施时同步迁移全部消费者并清零旧口径，不保留双轨；不允许页面、查询层或其他调用方自行拼装事实字段。
14. 新增 Alembic 迁移前必须先检查当前迁移 head，`down_revision` 只能接真实 head，不得按文件名、日期或印象猜。
15. 任何技术方案的变更，如果之前有对应的方案设计文档，必须同步落回原方案设计文档，禁止让现实代码、执行口径与既有设计文档脱节。
16. Ops/TaskRun 只保存用户或调度意图，`DatasetActionResolver` 才负责按 `DatasetDefinition.date_model` 归一化为执行计划，源接口参数只能在 ingestion request builder 中生成。
17. 开发、迁移、测试脚本中禁止擅自删除、清空或重建任何业务数据表、配置表、对象池表；确需清理必须有用户明确指令、备份方案和逐表清单。
18. 任何新增数据集或修改 `DatasetDefinition.date_model/input_shape/observed_field` 前，必须把“时间输入语义、执行/unit 语义、freshness/audit 语义”三层拆开逐项确认；严禁把“支持按日期输入”误写成“要求每天都有数据”。
19. 任何修改 `DatasetDefinition` 事实源的变更，必须先做全量消费者审计，至少覆盖：manual actions、catalog、workflow、resolver/unit planner、request builder、freshness、dataset cards、snapshot rebuild、date completeness audit、自动任务日期策略、前端时间控件、相关测试与文档。
20. 若 `date_model.bucket_rule=not_applicable`，必须额外说明：它只是“不按连续业务日期做 freshness/audit 判断”，还是连时间输入都不支持；禁止默认把 `not_applicable` 简化理解成“无日期输入”。
21. 新增数据集前必须做源接口真实行为验证，至少覆盖：不传业务参数、只传对象过滤、传时间点、传时间区间、分页拉取。源接口有可选日期参数，不等于该数据集应按日期驱动；若不传日期可拉全集且日期过滤会漏历史数据，主模型必须是 no-time snapshot。
22. 可选源接口参数不得自动暴露为运营输入字段。只有当该参数对应明确用户意图、不会造成数据缺失、并已通过真实请求和样本行数证明时，才允许进入 `DatasetDefinition.input_model`。
23. 新数据集完成前必须用真实样本或最小真实同步证明“源端行数、归一化行数、写入行数、拒绝原因、目标表行数”一致；任何 reject 都必须解释到 reason code 和样本，禁止把大批 reject 当作正常现象跳过。
24. 数据集同步的效率和性能问题是重要考虑点，是数据集接入方案的硬门禁；新增或修改数据集方案必须明确测算请求量、分页次数、事务边界、预估耗时、配额/限流影响，并给出不可接受量级的拒绝策略。
25. Tushare 资料理解、请求参数修改、真实行为与字段核验统一遵守本文件“本地 Tushare 能力”；子目录只补充本域要求，不重复定义通用流程。
26. 回答涉及代码细节、具体功能点、当前实现行为、调用链路、数据读写链路或 API 契约的问题前，必须先查看当前代码并逐项确认；不得凭命名、印象、历史经验或文档推测后直接回答。
27. 任何开发任务开始前，必须先明确输出开发目标、依据文档、改动范围和影响面；若无法确认上述内容，必须先停下汇报，不得直接进入编码。
28. 任何新增或修改配置项前，必须先完成配置项审计并落档，至少列清：配置名、默认值、来源与持久化位置（env/Settings/数据库/配置文件）、作用范围、所有消费者、配置之间的依赖关系、生效方式、运维可见性与测试门禁。配置项不得散落在页面常量、代码常量、脚本和文档口径中各自为政；未完成配置审计的实现不得进入开发。
29. 禁止 Codex 私自创建临时分支、临时 worktree 或在非当前开发分支上提交代码。默认且只能在当前 `dev-interface` 工作区推进；若工作区存在阻塞、冲突或脏文件导致无法继续，必须停下说明情况并等待用户处理或明确授权，不能自行绕开。
30. 不得引入 `foundation|ops|biz|platform|operations -> qtf` 反向依赖；`qtf` 只允许依赖自身与 `src.foundation`，由 `src.app` 负责组合装配。

---

## 本地 Tushare 能力

本节是全仓 Tushare 通用核验流程；子目录仅补充其特有的来源与执行边界。

1. 资料理解与选型：可结合 `docs/sources/tushare/**` 和 `tushare-data` skill 理解接口家族、数据域、研究场景及任务拆解。skill 路径为 `/Users/congming/.codex/skills/tushare-data/SKILL.md`；它不能替代代码、源文档与实测。
2. 实现与契约：涉及 request builder、`DatasetDefinition`、ingestion plan、字段契约、文档补丁或参数口径调整时，先读当前代码，再查阅并引用对应本地接口文档，逐项确认必填、可选、分页参数与字段含义，再做实测；禁止凭经验改请求参数。
3. 真实行为：输入输出、`limit/offset` 分页、日期过滤、权限积分、全量/增量可行性、不传时间拉全集、返回结构、样本行数和空结果原因，必须优先用可用的 `tushareMcp` 核验。工具不可用时应报告缺少的证据，不得以 skill、线上文档或经验替代实测结论。
4. 字段核验：对支持 `fields` 的接口，至少覆盖不传 `fields` 的默认返回、按文档字段显式请求、补充业务关键字段请求三类结果。影响身份、主键、Redis key、幂等、分组、频率、市场、时间或过滤语义的字段，例如 `freq/category/type/market/hot_type/is_new/time/trade_time`，必须显式放入 `fields` 请求并记录样本；缺少第三类验证，禁止回答“接口没有该字段”。
5. 差异处理：本地文档、线上文档与实测不一致时，显式记录差异，以“当前代码 + 实测行为”校准实现与本地文档；禁止带着未核清的口径继续编码。纯资料梳理可以先不实测，但一旦形成真实参数或实现契约结论，就必须完成上述核验。

---

## 目录职责速记

- `src/foundation/**`：数据基座与底层契约
- `src/ops/**`：运维治理、TaskRun 运行时编排与观测
- `src/biz/**`：对上业务 API/查询/服务
- `src/app/**`：入口装配、聚合路由、认证壳、运行壳
- `qtf/**`：量化研究、计算、验证与发布产品域；只依赖自身与 `src.foundation`
- `src/platform/**`：legacy 目录（兼容与清理）
- `src/operations/**`：legacy 目录（兼容与清理）

---

## 交付要求

每次任务结束至少说明：

1. 目标与依据
2. 改动文件
3. 是否影响边界/依赖矩阵
4. 验证结果
5. 下一步工作
6. 风险与后续建议

---

## 提交与推送

- 用户明确要求时可推送到 `origin/dev-interface`。
