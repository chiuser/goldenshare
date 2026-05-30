# AGENTS.md — 仓库根规则（重构收尾基线）

## 适用范围
本文件适用于仓库根目录及所有子目录。若子目录存在更近的 `AGENTS.md`，以更近规则为准。

---

## 当前结构（已收敛）

```text
src/
  foundation/
  ops/
  biz/
  app/
  platform/      # legacy/compat（冻结）
  operations/    # legacy/compat（冻结）
```

- `foundation` / `ops` / `biz` 是三个业务子系统
- `app` 是组合根（composition root），不是业务子系统
- `platform` / `operations` 已进入 legacy 冻结态，不承接新主实现
- 数据集事实源收敛到 `src/foundation/datasets/**` 的 `DatasetDefinition`
- 数据维护执行计划收敛到 `src/foundation/ingestion/**` 的 `DatasetExecutionPlan`
- 任务运行与详情观测收敛到 `src/ops/**` 的 TaskRun 主链

---

## 动手前必读

1. `docs/architecture/subsystem-boundary-plan.md`
2. `docs/architecture/dependency-matrix.md`
3. `docs/architecture/platform-split-plan.md`
4. `docs/architecture/ops-consolidation-plan.md`
5. `src/AGENTS.md` 与目标目录下更近的 `AGENTS.md`
---

## 角色定义（术语澄清）

1. 用户：指财势乾坤行情系统的软件使用方，可查看行情与信息，不参与系统配置与开发。
2. 运营：指财势乾坤行情系统后台工作人员，可进行配置中心文件配置、开发与维护；同时也是运营数据后台、数据湖等支撑工具的使用者。
3. 涉及“是否对外暴露参数/开关/功能”时，默认“对外”指面向用户；面向运营的能力应通过运营侧流程与配置能力承载。
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

## 硬约束

1. 不得回流主实现到 `src/platform` 或 `src/operations`。
2. 不得引入 `foundation -> ops|biz|app|platform|operations` 反向依赖。
3. 不做 big-bang 重构；每轮只做一个清晰目标。
4. 删除兼容层前必须先做引用审计，再做最小回归。
5. 禁止“无依据猜测式编码”（No source, no code）。
6. 不接受“补丁叠补丁”修复；当现有实现已进入烂代码堆积状态，必须主动提出重构或重写方案。
7. 忘掉老架构，忘掉历史包袱，必须在新架构下设计合理方案。任何改动不允许出现兼容方案，临时方案。不接受临时修复。管理员脾气非常大。必须按指令行事。
8. 不允许自己发挥，添加自己认为的功能或需求。尤其是管理员没提出来的时候。
9. 重构要彻底，不要留任何兼容性代码在仓库中。
10. Ops/TaskRun/freshness/snapshot/schedule 等状态写入不得影响业务数据表的读写与事务提交；状态写入失败只能影响观测状态，不允许阻塞、回滚或污染 `raw_*`、`core_*`、`core_serving*` 等业务数据。
11. 写给人看的文档，不要写晦涩难懂，给机器看的文档。
12. 审计必须看代码，不要靠猜；不得用文档、印象、命名或历史经验替代对当前实现的逐项核验。
13. 改契约时，必须做全量消费者审计，旧口径必须清零；不允许页面、查询层或其他调用方自行拼装事实字段。
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
25. 任何新增或修改 Tushare 请求参数生成逻辑前，必须查阅并引用对应 `docs/sources/tushare/**` 接口文档，逐项确认必填参数、可选参数、分页参数与字段含义；禁止凭经验改请求参数。
26. 回答涉及代码细节、具体功能点、当前实现行为、调用链路、数据读写链路或 API 契约的问题前，必须先查看当前代码并逐项确认；不得凭命名、印象、历史经验或文档推测后直接回答。
27. 任何开发任务开始前，必须先明确输出开发目标、依据文档、改动范围和影响面；若无法确认上述内容，必须先停下汇报，不得直接进入编码。
28. 当前环境若可见 `tushareMcp`，凡涉及 Tushare 接口的输入参数、输出字段、分页语义、日期过滤、权限积分、全量/增量可行性、样本返回行数等真实行为，必须优先用 `tushareMcp` 做实测核验；禁止只看线上文档或凭经验下结论。
29. 当前环境若可见 `tushare-data` skill，可用它理解接口家族、数据域背景、常见研究场景、自然语言需求到接口能力的映射；但它只能做理解与选型辅助，不能替代当前代码、`docs/sources/tushare/**` 和 `tushareMcp` 的事实核验。
30. 若 `docs/sources/tushare/**`、线上文档与 `tushareMcp` 实测结果不一致，必须显式记录差异，并以“当前代码 + 实测行为”校准实现与本地文档；禁止带着未核清的口径继续编码。
31. Tushare 字段验证必须区分“默认返回字段”“显式请求字段”和“业务关键字段”。不得因为一次请求的 `fields` 没带某字段，或文档默认字段没列某字段，就下结论说源接口不返回该字段。凡字段会影响身份、主键、Redis key、幂等、分组、频率、市场、时间或过滤语义，例如 `freq/category/type/market/hot_type/is_new/time/trade_time`，必须显式放入 `fields` 做真实请求验证，并记录返回样本。
32. 任何新增或修改配置项前，必须先完成配置项审计并落档，至少列清：配置名、默认值、来源与持久化位置（env/Settings/数据库/配置文件）、作用范围、所有消费者、配置之间的依赖关系、生效方式、运维可见性与测试门禁。配置项不得散落在页面常量、代码常量、脚本和文档口径中各自为政；未完成配置审计的实现不得进入开发。
33. 禁止 Codex 私自创建临时分支、临时 worktree 或在非当前开发分支上提交代码。默认且只能在当前 `dev-interface` 工作区推进；若工作区存在阻塞、冲突或脏文件导致无法继续，必须停下说明情况并等待用户处理或明确授权，不能自行绕开。
---

## 本地 Tushare 能力

- `tushareMcp`：用于验证 Tushare 接口真实行为，重点覆盖输入参数、输出字段、`limit/offset` 分页、时间过滤、权限积分、是否支持不传时间拉全集、样本返回结构与行数。
- `tushare-data` skill：用于帮助理解 Tushare 接口文档、接口家族关系、数据集背景、研究任务拆解，以及把自然语言需求映射到可能相关的数据接口。
- 获取 Tushare 数据源中某个数据集的相关信息时，可以使用 `tushare-data` skill 辅助理解，例如接口家族、数据域背景、常见字段、可能相关接口和研究路径。skill 路径：`/Users/congming/.codex/skills/tushare-data/SKILL.md`。
- 需要实测请求接口、验证真实输入输出、确认返回字段、样本行数、分页行为、权限积分、日期过滤或空结果原因时，必须使用 `tushareMcp` 做真实请求核验；不得用 `tushare-data` skill、线上文档或经验替代实测。
- 严格实现口径：涉及 request builder、`DatasetDefinition`、ingestion plan、字段契约、文档补丁或参数口径调整时，先看当前代码，再看 `docs/sources/tushare/**`，再用 `tushareMcp` 实测，`tushare-data` skill 只做辅助理解。
- 文档与研究口径：做接口梳理、目录盘点、任务拆解、研究路径建议时，可先结合 `docs/sources/tushare/**` 和 `tushare-data` skill；一旦要落到真实参数或实现契约，必须回到 `tushareMcp` 做验证。
- 字段核验口径：对支持 `fields` 的接口，至少核验三类请求结果：不传 `fields` 的默认返回、按文档字段显式请求、按业务关键字段补充请求。缺少第三步时，禁止回答“接口没有该字段”。

---

## 目录职责速记

- `src/foundation/**`：数据基座与底层契约
- `src/ops/**`：运维治理、TaskRun 运行时编排与观测
- `src/biz/**`：对上业务 API/查询/服务
- `src/app/**`：入口装配、聚合路由、认证壳、运行壳
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
