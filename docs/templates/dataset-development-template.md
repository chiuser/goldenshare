# 数据集开发说明模板（DatasetDefinition 主线）

> 使用说明：
> - 写数据集开发文档之前，必须先阅读仓库根目录 `AGENTS.md`，确认当前硬约束和禁止项。
> - 每新增一个数据集，先复制本模板生成独立文档，放在 `docs/datasets/` 目录。
> - 文档命名建议：`<dataset-key>-dataset-development.md`。
> - 未完成本文档，不得进入编码、发版或远程同步。
> - 本模板以当前新架构为准：数据集事实源是 `DatasetDefinition`，执行主链是 `DatasetActionRequest -> DatasetExecutionPlan -> IngestionExecutor`，任务观测主链是 Ops TaskRun。
> - 只有目标为 Prod 数据集的任务，预计或实测超过 60 秒，或执行规模会随日期、对象、分页、分区持续增长且无法静态约束时，才必须同时完成 0.3.5；数据湖、Dagster、DuckDB／Parquet 数据集任务不适用 0.3.5，遵守其自身专项规则。
> - 如果本数据集还要接入 Dagster sensor，必须同时使用 `lake_console/docs/templates/dagster-dataset-onboarding-template.html` 的 sensor cursor 规范；本模板不允许为 Dagster sensor 另起一套 cursor 字段。

---

## 0. 架构基线与禁止项

### 0.1 当前必须遵守的主线

1. 数据集身份、领域、来源、输入、日期模型、落库、规划、清洗、能力、观测、质量、事务与完整性，全部收敛到 `src/foundation/datasets/**` 的 `DatasetDefinition`。
2. 维护动作统一为 `action=maintain`，动作 key 由 `DatasetDefinition.action_key("maintain")` 派生，格式为 `<dataset_key>.maintain`。
3. 执行计划由 `DatasetActionResolver` 根据 `DatasetDefinition` 生成，执行器只消费 `DatasetExecutionPlan` 和 plan units。
4. Ops 手动任务、自动任务、任务详情、数据状态、数据源卡片均消费由 `DatasetDefinition` 派生的事实，不在前端或 Ops 查询层重新拼装数据集事实。
5. 任务运行与问题诊断只走 TaskRun 主链：`ops.task_run`、`ops.task_run_node`、`ops.task_run_issue`。
6. 必须遵守三层分离：Ops / TaskRun 只保存用户或调度意图，`DatasetActionResolver` 负责归一化为执行计划，request builder 只负责源接口字段映射和格式化。

### 0.2 禁止项

1. 不得新增或恢复旧三类同步命令作为用户可见或 API 主执行模型。
2. 不得新增旧同步服务包或旧 `operations/platform` 主实现。
3. 不得在 foundation 中依赖 ops、biz、app、platform、operations。
4. 不得使用 `__ALL__` / `__all__` 这类业务占位值污染请求参数、落库行或 source key。需要全量枚举时，必须在 `enum_fanout_defaults` 中显式列出真实枚举值。
5. 不得私自新增 checkpoint / acquire / 定点跳过或第二套任务状态机。Prod 数据集长任务确需持久化续跑能力时，必须先完成 0.3.5，优先复用现有 TaskRun、节点和业务幂等边界；新增专用 checkpoint 表必须逐需求评审，不能成为所有数据集的默认结构。
6. 不得把状态写入失败设计成回滚业务数据；Ops/TaskRun/freshness/snapshot/schedule 等状态写入只能影响观测状态。
7. 不得写“临时方案”。如果事实或能力还没准备好，应标为“不支持 / 暂不接入”，不要把临时路径做进主链。
8. 不得在 Ops、前端、自动任务服务中提前展开日期模型，例如把自然月窗口提前转成源接口 `start_date/end_date`。这类展开必须由 resolver 根据 `DatasetDefinition.date_model` 完成。
9. 不得仅凭源接口参数名推断时间模型。源接口有 `start_date/end_date/ann_date/trade_date`，只说明源端支持这些过滤条件，不代表本数据集必须按日期维护。
10. 不得把源接口可选参数自动暴露为运营输入。只有当它对应明确用户意图、不会导致数据缺失、并经过真实请求证明时，才允许进入 `input_model`。
11. 不得在没有真实样本行数证明的情况下宣布数据集完成。源端拉取、normalizer、writer、目标表行数、reject 原因必须能对上。
12. 若同步引入 Dagster sensor，不得自定义报告型 cursor。cursor 只能做本 tick 调度路标：说明触发或跳过原因、阻断组件、目标日期和下一步动作；完整诊断放到 Dagster asset/check metadata 或审计报告。
13. 不得为 direct-serving 数据集伪造空 raw 表、影子 DAO 或双写兼容层；必须把“无 raw 层”作为 storage、writer、projection 与页面共同支持的正式契约。
14. 不得仅在后端拒绝某个 filter 与时间模式的非法组合；若 filter 会约束 point/range/none、单值或已有桶条件，必须经通用 API contract 驱动前端控件，同时保持后端为最终裁决。
15. 不得只在创建自动排程时校验源站 release/probe 限制；runtime 入队前还必须校验 target、日期和 filters，防止历史配置或直接写库绕过。

### 0.3 开发前置硬检查

下面四张验证 / 审计表、0.3.4 硬需求追溯账本，以及目标为 Prod 数据集且满足长任务条件时的 0.3.5 执行合同未填写完成前，不得进入编码。

#### 0.3.0 源接口真实行为验证表

这张表是硬门禁，用来防止把“源端有可选过滤参数”误建模成“平台按该参数驱动维护”。

| 请求形态 | 实际请求参数 | 源端返回行数 | 是否分页 | 关键样本字段 | 结论 |
| --- | --- | --- | --- | --- | --- |
| 不传业务参数 |  |  | 是 / 否 |  | 是否能拉全集 |
| 只传对象过滤 |  |  | 是 / 否 |  | 是否能拉该对象全集 |
| 只传时间点 |  |  | 是 / 否 |  | 是否会漏历史/空日期数据 |
| 传时间区间 |  |  | 是 / 否 |  | 是否完整、是否需要切窗 |
| 默认字段 |  |  | 不适用 |  | 默认是否缺少需要落库的字段 |
| 显式请求全部文档字段 / 业务关键字段 |  |  | 不适用 |  | `fields` 是否返回所有目标字段和身份字段 |
| 分页第二页及后续短页 |  |  | 是 / 否 |  | `limit/offset` 是否真实生效、结束条件是否正确 |
| 单页基准与分页合并对账 |  |  | 是 / 否 |  | 在不截断的同一业务范围内，唯一键集合是否完全相等 |

强约束：

1. 必须用真实请求、源站测试页下载、或源站原始 CSV 样本填写，不能只抄接口文档。
2. 如果“不传业务参数 + 分页”能返回全集，而时间点/区间会漏数据，主执行模型必须是 `mode=none` / `snapshot_refresh`。
3. 如果只传对象过滤能返回该对象全历史，`ts_code` 等对象字段只能作为 filter，不能因此引入日期 fan-out。
4. 如果时间点/区间只是源端过滤能力，不是完整维护能力，不得把它放进 `supported_time_modes`。
5. 如果源端返回重复行，必须说明幂等键如何去重；去重可以接受，但 reject 计数和原因必须在验收中说清楚。
6. 分页实测必须通过项目实际 connector；若 MCP / SDK 包装器未暴露 `limit/offset`，该包装器只能证明源端其他行为，不能替代第二页和页合并验证。
7. 对可能达到源端单次上限的接口，不能以无日期或宽区间请求当全量基准；基准请求必须确认不截断。

#### 0.3.1 三层语义拆分表

这张表是本模板新增的硬门禁，用来防止把“支持按日期输入”误写成“要求每天都有数据”。

| 语义层 | 必须回答的问题 | 本数据集答案 | 是否已从代码/源文档核验 |
| --- | --- | --- | --- |
| 时间输入语义 | 用户或调度到底在提交什么意图？是单日、区间、月份、自然月窗口，还是无时间？字段名虽然叫 `trade_date`，真实业务含义是什么？ |  | 是 / 否 |
| 执行 / unit 语义 | resolver 会如何展开执行计划？是保留单个区间 unit、逐日 fan-out、按月份 fan-out、按证券池 fan-out，还是按枚举组合 fan-out？单个事务边界在哪里？ |  | 是 / 否 |
| freshness / audit 语义 | 平台是否要求连续日期桶？如果要求，是按交易日、自然日、周五、月末还是月份键？如果不要求，为什么不要求？ |  | 是 / 否 |

强约束：

1. 这三层答案必须分别填写，禁止用一句模糊描述混过去。
2. 如果第三行答案是“不要求连续日期桶”，必须明确写出是否仍支持自然日/交易日输入。
3. 若 `bucket_rule=not_applicable`，必须额外说明：这是“仅退出 freshness/audit”，还是“连时间输入也不支持”。
4. `date_axis/window_mode/input_shape/supported_time_modes` 必须能从 0.3.0 的源接口真实行为验证表推导出来，不能从字段名、历史习惯或个人判断推导。

#### 0.3.2 DatasetDefinition 消费者审计表

修改 `DatasetDefinition` 事实源前，必须按下面清单逐项审计真实代码消费方。任何一项未确认，都不能动手改定义。

| 消费方 | 读取了哪些 Definition 事实 | 本次是否受影响 | 需要怎么改 | 已核验代码位置 |
| --- | --- | --- | --- | --- |
| manual actions | `date_model`、`input_model`、`capabilities` |  |  |  |
| catalog | `date_model.selection_rule()`、展示分组、参数 |  |  |  |
| workflow | step 时间模式、默认参数、日期制度 |  |  |  |
| resolver / unit planner | `date_model`、`planning`、`input_shape` |  |  |  |
| request builder | 源接口字段映射、日期格式化 |  |  |  |
| freshness | `observed_field`、`date_axis`、`bucket_rule`、集中 freshness policy 映射 |  |  |  |
| dataset cards | 卡片状态、最近同步、raw 表与目标表静态事实 |  |  |  |
| snapshot rebuild | `dataset_status_snapshot` freshness 缓存 |  |  |  |
| date completeness audit | `audit_applicable`、`bucket_rule`、`not_applicable_reason` |  |  |  |
| 自动任务 / calendar policy | `date_selection_rule`、默认时间模式 |  |  |  |
| source release / Probe | release policy、目标业务日、固定样本、排程绑定、runtime 入队和同日去重 |  |  |  |
| 前端时间控件 | point/range/none/month 控件与选择规则 |  |  |  |
| Ops 展示目录 | `dataset_catalog_views.py` 的分组、顺序、可见性 |  |  |  |
| 数据源页 / 分层展示 | raw 表、target/serving 表、layer plan、delivery mode 的 null / fallback 语义 |  |  |  |
| shared storage / writer | `raw_*` 字段可空性、write path DAO 依赖、Definition linter、既有 write path 回归 |  |  |  |
| 测试与文档 | 现有单测、方案文档、开发文档 |  |  |  |

停手条件：

1. 有任何一行“已核验代码位置”填不出来，先去看代码，不要猜。
2. 如果 manual actions、freshness、dataset cards 三行还没核验完，禁止修改 `date_model`。
3. 如果文档口径和当前代码实现不一致，先记录差异，再决定改文档还是改代码；禁止两边继续脱节。
4. 如果改动会让某个 workflow 的 step 时间模式不匹配，必须同步调整 workflow；不得把 no-time 数据集塞进 point/range workflow。
5. 如果改动会让数据源卡片或 freshness 从“按业务日判断”变成“按运行健康判断”，必须同步更新 snapshot / dataset cards 测试。
6. 如果新增 direct-serving 或改变 storage/write path，必须列出所有 raw/core 既有 write path，并验证本次 Optional 字段、DAO 分派和序列化不会使旧路径静默失效。
7. 如果自动维护依赖源端晚发布，必须同时审计 schedule API、binding service 和 probe runtime；只列 Probe service 文件不算完成。

#### 0.3.3 源字段端到端对账表

这张表是硬门禁，用来防止出现“源接口已经有字段，但代码没请求、表没建、Lake 没导出”的问题。

| 源站输出字段 | 源文档是否列出 | 真实样本是否返回 | `source_fields` | raw ORM | raw 迁移 / 真实表 | serving/core ORM | serving/core 迁移 / 真实表 | Lake 白名单（如适用） | 是否必填 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
|  | 是 / 否 | 是 / 否 | 是 / 否 | 是 / 否 | 是 / 否 | 是 / 否 | 是 / 否 | 是 / 否 / 不适用 | 是 / 否 |  |

强约束：

1. 源站输出字段必须逐列对账，不能只对默认显示字段。源文档里“默认显示=N”的字段，如果业务需要保留，也必须进入 `source_fields`、ORM、迁移和导出白名单。
2. `DatasetDefinition.source_fields` 是 `DatasetSourceClient -> connector.call(..., fields=definition.source.source_fields)` 的字段白名单，不是 request builder 返回值的一部分。测试不能只看 `request_params`，还要覆盖 connector payload 的 `fields`。
3. raw 层字段名默认保留源站输出字段名；不要因为觉得名字难看就改名。确需改名时，必须在文档写清楚映射，并说明不会破坏 Lake raw 或源站审计。
4. Goldenshare 自增字段如 `api_name/fetched_at/raw_payload/source/created_at/updated_at` 不是源站输出字段；可以用于生产表内部治理，但不得混入 `source_fields` 或 Lake raw 字段白名单。
5. 如果源字段参与业务身份，例如 `category/type/freq/market/hot_type/is_new`，必须用真实样本验证它是否应进入主键、`conflict_columns`、`raw_conflict_columns` 或 `row_identity_filters`。不得默认使用 `(ts_code, trade_date)`。
6. 如果发现源站文档更新导致字段缺失，例如新增估值字段、分类字段，优先补齐字段链路；若需要重建表，必须先取得明确确认，再新增 Alembic 迁移。
7. 对支持 `fields` 的 Tushare 接口，字段验证必须拆成三步：不传 `fields` 看默认返回、按源文档字段显式请求、按业务关键字段补充请求。不得因为一次手写 `fields` 没带某字段，或默认返回没出现某字段，就判断源接口不支持该字段。
8. `freq/category/type/market/hot_type/is_new/time/trade_time` 等会影响身份、主键、Redis key、幂等、分组、频率、市场或时间语义的字段，即使源文档未列出或默认返回未出现，也必须显式放入 `fields` 做真实请求验证；验证结果必须写入“真实样本是否返回”和备注。
9. direct-serving 可在 raw ORM、raw 迁移 / 真实表列明确填写“不适用（有意无 raw 层）”；不得留空，也不得为通过表格校验新建 raw 镜像。

#### 0.3.4 硬需求追溯账本

这是整个交付的控制面：把用户已定口径、LLD 中的“必须 / 仅 / 固定 / 禁止 / 不得”逐条编号；一条需求不能仅以“相关测试已通过”结案。设计、编码、每个里程碑和交付前都必须更新此表。

| ID | 硬需求与依据 | 影响层 / 消费者 | 后端权威约束 | 前端表现与直接消费者 | 实现文件 | 正向测试 | 反向测试 | 真实验证 / 浏览器路径 | 计划阶段 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `REQ-001` |  |  |  |  |  |  |  |  |  | 未开始 / 已实现待验 / 已验证 / 不适用 |

填写与阻断规则：

1. 每条独立业务结果占一行；不得把“唯一 condition、固定窗口、禁止筛选、runtime 防绕过、页面隐藏控件”合并成一句。一个条件在 API、binding、runtime 与页面有消费者时，这些消费者都必须写入同一行或拆成可独立验收的多行。
2. `前端表现与直接消费者` 不能用“前端已适配”代替真实文件和行为。任何会改变控件可见性、可编辑性、默认值、可选项或提交 payload 的约束，都必须列出具体页面 / shared helper，并由真实用户路径验证；helper 单测不能替代浏览器交互验证。
3. 每条“允许”至少有正向测试，每条“仅 / 禁止 / 固定 / 不得”至少有反向测试。后端拒绝不等于前端已完成；前端隐藏不等于后端已防绕过。
4. `不适用` 必须写明为什么该消费者确实不存在，并给出已审计代码位置；不能用空白或“暂不处理”结案。
5. 只有本阶段全部关联行均为“已验证”，才可标记该阶段完成。缺少前端、浏览器、真实 connector 或最小真实同步证据时，只能报告对应子项完成，禁止宣布整体完成。
6. 提交前必须按追溯账本复核 `git diff`：每个“实现文件”要么出现在本次 / 已引用的前序提交中，要么明确说明已存在且给出验证证据；任何未覆盖行都是 blocker。

#### 0.3.5 Prod 数据集长任务识别与执行合同

本节只适用于目标为 Prod 数据集的同步、回补、PLAN / APPLY 或批量计算；数据湖、Dagster、DuckDB／Parquet 数据集任务不填写本节。Prod 数据集任务满足任一条件即按长任务设计：预计或实测运行超过 60 秒；执行规模随日期、对象、分页或分区增长且无法静态约束；单次 PLAN / APPLY 需要处理大量历史范围；取消或进程退出后重新开始会造成明显时间、配额或资源浪费。

| 合同项 | 本数据集答案 | 代码 / 测试 / 真实证据 |
| --- | --- | --- |
| 是否为长任务及判断依据 |  |  |
| 最小独立执行 unit 与总 unit 估算 |  |  |
| 单 unit 页数、行数和耗时上界 |  |  |
| 批次大小、内存模式和内存上限 |  |  |
| 业务数据持久化边界 |  |  |
| 幂等键与重复执行结果 |  |  |
| 续跑依据：已提交 unit、业务读回或专用 checkpoint |  |  |
| 进度字段、更新频率与页面展示 |  |  |
| 取消检查点与最大取消延迟 |  |  |
| TaskRun 与活动节点终态同步 |  |  |
| 既有执行入口及串行／并发影响 |  |  |
| 事务边界与一致性口径 |  |  |
| 最小真实运行、取消、续跑和读回验收 |  |  |

长任务硬规则：

1. 禁止把完整历史范围长期累积在一个内存 `list`、`dict`、DataFrame 或等价容器中，并在任务末尾才首次写入。常驻内存必须与单批次大小相关，不能与全量范围线性增长。
2. APPLY 必须在每个已定义的独立业务 unit 完成后形成可读回的持久化边界。进程退出或用户取消后，已提交 unit 保留，未提交 unit 不得伪装完成。
3. 长 PLAN 若必须汇总全范围才能冻结，只能分批保存“不可执行的草稿证据”，全部完成并校验后再原子冻结最终 PLAN；未冻结或部分 PLAN 不得进入 APPLY。
4. 续跑必须从持久化事实、已提交 unit 或经专项批准的 checkpoint 恢复；不得依赖进程内缓存。重复执行同一 unit 必须幂等，不产生重复业务数据。
5. 页面必须显示阶段、当前对象或窗口、已完成量、总量、百分比和最后更新时间。运行中不得连续 30 秒没有可见更新；心跳只能证明任务仍活着，不能冒充业务完成进度。
6. ETA 仅在存在可靠样本时显示；无法可靠估算时明确显示“暂无法估算”，不得伪造倒计时。若复用当前 Ops ETA，必须按已提交 unit 进度计算，并遵守 10 秒浏览器采样口径。
7. 每个 unit 或分页开始前、完整结束后检查取消。任何不可分割步骤若可能超过 30 秒，必须继续拆分，或使用能安全中断的源调用；取消后不得领取新 unit。
8. TaskRun 与当前活动 `task_run_node` 必须在成功、失败、取消时共同进入一致终态；观察状态写入仍不得回滚已提交业务数据。
9. 默认禁止用一个覆盖全历史的长数据库事务换取一致性。应使用版本、日期、范围 hash 或冻结状态表达一致快照；确需长事务必须单独说明锁、空间、失败恢复和影响范围并取得批准。
10. 自动化测试至少覆盖：中途取消、进程退出、续跑、幂等重放、进度单调、状态写失败不回滚业务数据和 TaskRun/节点终态一致。
11. 全量生产执行前必须完成一次有代表性的最小真实运行，并实际验证取消、续跑、读回和进度展示；只跑单元测试不能关闭该门禁。
12. 长任务可以使用已经批准的既有执行入口；不得仅因任务耗时较长就默认新增 worker lane、Worker、systemd unit 或队列。确需新增基础设施时必须另立范围评审。

---

## 1. 标准交付流程

1. 固定源站事实：官方文档、输入参数、输出字段、分页、限速、更新时间。
2. 填完“0.3.0 源接口真实行为验证表”、“0.3.1 三层语义拆分表”、“0.3.2 DatasetDefinition 消费者审计表”、“0.3.3 源字段端到端对账表”和“0.3.4 硬需求追溯账本”；仅目标为 Prod 数据集时判断是否触发 0.3.5 长任务门禁。
3. 新增源站文档，或在真实验证改变已知源端事实时更新 `docs/sources/**`；Tushare 文档新增/修改必须同步 `docs/sources/tushare/docs_index.csv`。已有且未变化的源文档要在方案中引用并记录已核验，不重复新建。
4. 完成本文档，明确 `DatasetDefinition` 完整事实合同和执行/落库/观测方案；Prod 数据集长任务同时明确内存、持久化、续跑、进度和取消。
5. 新增 SQLAlchemy ORM 模型、DAO、Alembic 迁移；确认 ORM 能被 `table_model_registry()` 自动发现。
6. 在正确的 `src/foundation/datasets/definitions/<domain>.py` 中新增 `DATASET_ROWS` 定义。
7. 补齐 ingestion 能力：request builder、unit builder、row transform、writer 路径、分页、reject reason、codebook。
8. 确认 Ops 派生能力：manual actions、catalog、workflow、freshness、dataset cards、TaskRun 详情；新增数据集必须配置 `src/ops/catalog/dataset_catalog_views.py`。
9. 补测试：definition、resolver、unit planner、normalizer、writer、Ops API、架构门禁；有用户可见交互时补浏览器路径测试。
10. 在每个里程碑前后按 0.3.4 对照实际代码、测试与 `git diff`，未验证行不得跨阶段结案。
11. 本地执行门禁并记录命令。
12. 发版前在开发库跑最小真实同步或真实样本 dry-run，确认业务数据、TaskRun 详情、数据状态和数据源卡片一致。
13. 验收必须记录：源端 fetched 行数、normalized 行数、written 行数、rejected 行数、reject reason code、目标表实际行数。任何一项对不上，不能标完成。

---

## 2. 基本信息

- 数据集 key：
- 中文显示名：
- 所属定义文件：`src/foundation/datasets/definitions/<domain>.py`
- 所属域：`reference_master` / `market_equity` / `market_fund` / `index_series` / `board_hotspot` / `moneyflow` / `low_frequency` / 其他（新增域需先评审）
  - 说明：这里是 `DatasetDefinition.domain` 的底层领域事实，不等于前端或 Ops 的用户可见展示分组。
- 数据源：`tushare` / `biying` / 其他
- 源站 API 名称：
- 源站文档链接：
- 本地源站文档路径：
- 文档抓取日期：
- 是否对外服务：是 / 否
- 是否多源融合：是 / 否
- 是否纳入自动任务：是 / 否
- 是否纳入日期完整性审计：是 / 否
- Ops 展示分组 key：
- Ops 展示分组名称：
- Ops 展示分组顺序：
- Ops 展示目录配置文件：`src/ops/catalog/dataset_catalog_views.py`

说明：
- `DatasetDefinition.domain` 是底层领域事实，不能为了页面分组而改 domain。
- 运营后台用户可见分组必须来自 Ops 展示目录配置；新增数据集没有配置展示目录时，应让测试失败，而不是静默落入“其他”。

---

## 3. 源站接口分析

### 3.1 输入参数

| 参数名 | 类型 | 必填 | 说明 | 类别（时间/枚举/代码/分页/其他） | 是否给运营用户填写 | 对应 `DatasetInputField` | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |

### 3.2 输出字段

| 字段名 | 类型 | 含义 | 是否落 raw | 是否进入 serving/core | 清洗规则 |
| --- | --- | --- | --- | --- | --- |

硬规则：

1. 本表必须与 0.3.3 的端到端字段对账表一致。
2. 源站稳定日期字符串（例如 `YYYYMMDD`）可以在 raw 层直接落 `date`，但字段名仍保持源站字段名。
3. 源站可能返回伪空值时要在清洗规则写明，例如 `""`、`nan`、`nat`、`null`、`none`、`0` 是否应视为空。已知伪空值不得造成大批量 `normalize.invalid_date` 拒绝。
4. 如果某字段是源站输出但本轮不落库，必须写清楚“不落库原因”；不能因为遗漏而留空。

### 3.3 源端行为

- 是否分页：
- 分页参数与结束条件：
- 是否限速或有积分限制：
- 是否需要按代码池、日期、月份、枚举拆分请求：
- 是否有上游脏值或缺字段风险：
- 是否有级联依赖（例如先同步指数/板块主表，再同步成分）：

硬规则：

1. “是否需要按日期拆分请求”必须来自真实请求结论，不能来自参数名。
2. 若源接口不传日期可以分页拉全集，优先按 no-time snapshot 设计；只有证明全量不可用或业务明确要求增量，才允许设计 point/range。
3. 若日期过滤会漏掉 `ann_date` 为空、历史区间、退市记录、老数据等，禁止把日期过滤作为主维护路径。
4. 若源端单次返回可能重复，必须在本文档写清唯一幂等键和重复行处理口径。

---

## 4. DatasetDefinition 事实设计

### 4.1 `identity`

```python
"identity": {
    "dataset_key": "",
    "display_name": "",
    "description": "",
    "aliases": (),
    "logical_key": None,
    "logical_priority": 100,
}
```

- `dataset_key`：
- `display_name`：
- `description`：
- `aliases`：
- `logical_key` / `logical_priority`（多源或同逻辑数据集时必填）：

### 4.2 `domain`

```python
"domain": {
    "domain_key": "",
    "domain_display_name": "",
}
```

- `domain_key`：
- `domain_display_name`：
- 注意：`domain` 只表达底层领域事实，不再包含更新节奏或 freshness 判断字段。
- 注意：freshness policy 不写入 `DATASET_ROWS.domain`。新增数据集必须在 `src/foundation/datasets/freshness_policies.py` 的 `FRESHNESS_POLICY_BY_DATASET` 中显式登记，否则 registry 测试应失败。

### 4.3 `source`

```python
"source": {
    "source_key_default": "",
    "source_keys": ("",),
    "adapter_key": "",
    "api_name": "",
    "source_fields": (),
    "source_doc_id": "",
    "request_builder_key": "generic",
    "base_params": {},
    "release_policy": "same_day",
}
```

- `source_key_default` 必须属于 `source_keys`。
- `source_fields` 必须与源站文档和实际请求字段一致。
- 自定义请求参数构造器必须注册在 `src/foundation/ingestion/request_builders.py`。
- `release_policy` 当前只允许 `same_day` / `next_calendar_day_0830` / `next_open_day_0930`，并必须与 probe、排程目标日和 runtime 入队校验一致；新增发布策略前先扩展单一事实源和消费者测试，不能在数据集内自定义字符串。
- 不得从 `dataset_key` 前缀反推 source；source 事实只能来自这里。
- `source_fields` 会被 `DatasetSourceClient` 传给连接器作为源端 `fields`；不要把字段白名单写进 request builder。
- 有些 Tushare 接口默认不返回全部字段，必须用 `source_fields` 显式请求需要的字段。新增或修改字段时，测试要覆盖 connector 收到的 `fields`。
- 不得把“本次请求的 `fields` 没带某字段”解释成“源接口没有该字段”。如果字段影响数据身份或业务语义，必须先显式请求验证，再决定是否进入 `source_fields`、主键或 Redis key。

### 4.4 `date_model`

```python
"date_model": {
    "date_axis": "",
    "bucket_rule": "",
    "window_mode": "",
    "input_shape": "",
    "observed_field": None,
    "audit_applicable": False,
    "not_applicable_reason": None,
    "bucket_window_rule": None,
    "bucket_applicability_rule": "always",
}
```

- `date_axis`：`trade_open_day` / `natural_day` / `month_key` / `month_window` / `none`
- `bucket_rule`：`every_open_day` / `week_last_open_day` / `month_last_open_day` / `every_natural_day` / `week_friday` / `month_last_calendar_day` / `calendar_quarter_end` / `every_natural_month` / `month_window_has_data` / `not_applicable`
- `window_mode`：`point` / `range` / `point_or_range` / `none`
- `input_shape`：按现有代码枚举选择，例如 `trade_date_or_start_end`、`month_or_range`、`start_end_month_window`、`ann_date_or_start_end`、`none`
- `observed_field`：用于 freshness 和日期审计观测的目标表字段；没有业务日期时填 `None`
- `audit_applicable`：
- `not_applicable_reason`：
- `bucket_window_rule`：候选锚点对应的业务窗口；默认 `None`，仅在候选桶需要按窗口判断是否可产出时填写，例如 `iso_week` / `natural_month`
- `bucket_applicability_rule`：候选桶是否应纳入 expected bucket；默认 `always`，股票周/月线长假排除使用 `requires_open_trade_day_in_bucket`

说明：
- 周线/月线不能按名称猜口径，必须以源接口文档为准。
- 如果源接口要求每周/每月最后一个交易日，使用 `week_last_open_day` / `month_last_open_day`。
- 如果源接口要求自然周周五或自然月最后一天，使用 `week_friday` / `month_last_calendar_day`；即使字段名叫 `trade_date`，也不能误建模成交易日。
- 如果自然锚点对应的业务窗口没有开市日就不应产出数据，必须显式填写 `bucket_window_rule` 与 `bucket_applicability_rule`，不得在审计 SQL 或前端用节假日白名单兜底。
- 快照/主数据通常使用 `date_axis="none"`、`bucket_rule="not_applicable"`，并给出 `not_applicable_reason`。
- 事件型数据如果“支持自然日输入，但不要求每天都有数据”，也应使用 `bucket_rule="not_applicable"`，同时在 0.3 三层语义拆分表中明确写出：输入仍是自然日，只有 freshness / audit 退出连续日期桶判断。
- 前端日期控件、审计能力、freshness 口径都从 `date_model` 派生，不允许另建第二套日期规则。

### 4.4.1 时间意图归一化设计

必须明确本数据集的时间输入在三层中的形态：

| 层级 | 本数据集应保存或生成什么 | 示例 |
| --- | --- | --- |
| Ops / TaskRun / Schedule | 用户或调度意图 | `trade_date`、`start_date/end_date`、`month`、`start_month/end_month` |
| `DatasetActionResolver` | 标准化执行计划时间范围和 units | 自然月窗口展开为月初/月末，公告日区间扇开为自然日 units |
| request builder | 源接口参数字段和值 | `date` 格式化为 `YYYYMMDD`，字段名映射为源端要求 |

填写项：

- Ops/TaskRun 保存的 `time_input` 形态：
- resolver 需要做的归一化：
- request builder 需要做的源接口格式化：
- 是否存在 `calendar_policy`：是 / 否；如有，只能生成调度意图，不能绕过 resolver 生成源接口参数。

常见口径：

- `month_or_range`：上层传 `month` 或 `start_month/end_month`，resolver 归一化月份键和日期范围。
- `start_end_month_window`：上层传 `start_month/end_month` 表达自然月窗口，resolver 展开为 `start_date/end_date`，request builder 再格式化为源接口日期。
- `ann_date_or_start_end`：上层传公告日或日期区间，resolver/planner 决定公告日锚点，request builder 映射为源端 `ann_date`。
- `trade_date_or_start_end`：上层传交易日或日期区间，resolver/planner 根据 `date_axis/bucket_rule` 生成执行锚点。

反例：

- 因为源接口最终需要 `start_date/end_date`，就在手动任务或自动任务服务中提前展开自然月窗口。
- 因为源接口字段叫 `trade_date`，就把自然周五或自然月末误当成交易日。
- 因为源接口提供 `start_date/end_date`，就把历史主数据误建模成日期驱动，导致不带公告日的历史记录被漏掉。
- 在前端根据 `dataset_key` 手写日期转换逻辑。

### 4.5 `input_model`

```python
"input_model": {
    "time_fields": (),
    "filters": (),
    "required_groups": (),
    "mutually_exclusive_groups": (),
    "dependencies": (),
}
```

| 字段 | 类型 | 是否必填 | 默认值 | 枚举值 | 选项中文名 | 是否多选 | 是否允许全选 | 中文名 | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

约束：
- 表中“类型 / 枚举值 / 是否多选”分别对应 `DatasetInputField.field_type`、`enum_values`、`multi_value`；其他列分别落到同名字段，不得只写展示文案而遗漏结构化合同。
- 时间字段必须与 `date_model.input_shape` 一致。
- 给用户看的 `display_name` 必须是中文业务名，不得暴露内部字段含义。
- 枚举项的中文标签写入 `option_labels`；只有多值枚举且已声明非空枚举集合时才允许 `select_all_enabled=True`。
- `scoped_repair_policy` 只用于已定义的受限修复语义，必须使用当前 linter 支持值，并同时由 API 条件合同、前端控件和后端 validator 执行。
- 枚举多选如果要默认展开，必须同步配置 `planning.enum_fanout_defaults`。
- 如果某 filter 会限制可选时间模式、是否多值或“只能补录已存在日期桶”等执行边界，必须在字段级声明通用约束；Manual Action API 必须返回可消费的条件规则，前端随筛选值切换控件，planner / validator 同时做权威拒绝。禁止只按 `dataset_key` 写 UI 分支。

### 4.6 `storage`

```python
"storage": {
    "raw_dao_name": "",
    "core_dao_name": "",
    "target_table": "",
    "delivery_mode": "",
    "layer_plan": "",
    "std_table": None,
    "serving_table": None,
    "raw_table": "",
    "observation_dao_name": None,
    "observation_table": None,
    "stage_dao_name": None,
    "stage_table": None,
    "raw_conflict_columns": None,
    "conflict_columns": None,
    "write_path": "raw_core_upsert",
    "serving_conflict_resolution_policy": "none",
    "row_identity_filters": {},
    "replacement_scope_fields": (),
}
```

- `raw_table`：
- `target_table`：
- `delivery_mode`：
- `layer_plan`：例如 `raw-only`、`raw->core`、`raw->serving`、`raw->std->serving`
- `raw_dao_name`：
- `core_dao_name`：
- `observation_dao_name` / `observation_table`：需要从独立观测表发布 current serving 时填写，否则显式为 `None`。
- `stage_dao_name` / `stage_table`：只有当前 write path 明确支持 staged stream 时填写，否则显式为 `None`。
- `raw_conflict_columns`：
- `conflict_columns`：
- `write_path`：
- `serving_conflict_resolution_policy`：
- `row_identity_filters`：
- `replacement_scope_fields`：完整范围替换时必须非空并全部属于必填字段；其他路径保持空元组。

约束：
- raw 与 serving/core 的冲突列可以不同，必须分别说明。不要为了省事把 serving 口径硬套到 raw。
- 共表数据集如果依赖 `freq/type/source_variant` 等固定身份字段，必须填写 `row_identity_filters`，避免不同逻辑数据互相覆盖。
- 只要修改主键、唯一键或冲突列，就必须用真实样本验证同一日期同一代码下是否存在多行变体。
- 若选择 direct-serving，`raw_dao_name` 与 `raw_table` 必须显式为 `None`，`target_table=serving_table`，且 write path 只解析 core/serving DAO；Definition builder / linter、writer、freshness projection、snapshot、card schema 与前端展示都必须支持该 null 语义。
- direct-serving 页面不能显示伪造 raw 表或“—”掩盖事实：在通用来源卡片中应回退展示 target/serving 表，并明确这是服务表；raw-backed 数据集展示不得回归。
- 任何新 write path 都必须声明：所需 DAO、禁止访问的 DAO、空 batch 语义、冲突键、事务边界，以及对所有既有 write path 的回归范围。

以下只是常见 `write_path` 示例，不是完整枚举；可用值以当前 writer、Definition linter 和已注册 definitions 为准：
- `raw_only_upsert`
- `raw_core_upsert`
- `raw_core_snapshot_insert_by_trade_date`
- `raw_std_publish_stock_basic`
- `raw_std_publish_moneyflow`
- `raw_std_publish_moneyflow_biying`
- `raw_index_period_serving_upsert`

如果需要新增 `write_path`，必须说明为什么现有路径不能承载，并补 writer 测试。

### 4.7 `planning`

```python
"planning": {
    "universe_policy": "no_pool",
    "universe": None,
    "enum_fanout_fields": (),
    "enum_fanout_defaults": {},
    "request_variant_fields": (),
    "request_variant_defaults": {},
    "pagination_policy": "none",
    "page_limit": None,
    "max_source_rows_per_unit": None,
    "chunk_size": None,
    "max_units_per_execution": None,
    "unit_builder_key": "generic",
    "fetch_concurrency": 1,
    "page_processing_mode": "buffer_all",
}
```

- `universe_policy`：`no_pool` 表示明确不按对象池展开；`pool` 表示按 `planning.universe` 声明的对象池展开；`none` 只表示未定义，不得用于新数据集。
- `universe`：使用对象池时填写 `request_field`、允许的 `override_fields` 与正式 `sources`；每个 source 必须明确 `type` 和 `resource`。不使用对象池时显式为 `None`。
- `enum_fanout_fields`：哪些枚举字段参与 unit 扇出。
- `enum_fanout_defaults`：用户未填写枚举时默认展开的真实枚举值集合。
- `request_variant_fields` / `request_variant_defaults`：只描述源请求变体，不得冒充用户输入或对象池。
- `pagination_policy`：`none` / `offset_limit` / 其他现有策略。
- `page_limit`：
- `max_source_rows_per_unit`：单 unit 源端行数硬上限；超限必须失败，不能静默截断。
- `chunk_size`：
- `max_units_per_execution`：
- `unit_builder_key`：如需自定义，必须在 `src/foundation/ingestion/unit_planner.py` 有清晰实现和测试。
- `fetch_concurrency`：当前允许范围以 linter 为准；必须评估配额、连接数、worker 占用和稳定排序。
- `page_processing_mode`：当前只允许 `buffer_all` / `staged_stream`。长分页任务优先评估 `staged_stream`；选用时必须同时满足对应 write path、stage 表、单并发与 `commit_policy=unit` 的 linter 合同。

写入量评估：
- 必须估算单个 unit 的最大写入行数：
- 必须估算单个数据库事务的最大写入行数：
- 若单个 unit 可能形成超大事务，必须先调整 unit 拆分规则，不能靠分页掩盖事务风险。
- `transaction.write_volume_assessment` 必须写入以上实测基准、分页大小、单事务范围和超量时的停止 / 复核策略；不能留空或只写“数据量可控”。

### 4.8 `normalization`

```python
"normalization": {
    "date_fields": (),
    "decimal_fields": (),
    "required_fields": (),
    "row_transform_name": None,
}
```

- `date_fields`：
- `decimal_fields`：
- `required_fields`：
- `row_transform_name`：

约束：
- 行转换函数必须注册在 `src/foundation/ingestion/row_transforms.py`，不能放在 request builder 里。
- `required_fields` 缺失应进入 reject 统计，不得静默写入不完整业务行。
- 新增 row transform 必须补 normalizer 测试。
- 对已知上游伪空值必须做受控清洗，例如日期字段里的 `nan/nat/null/none/0`。如果该值语义上是空，应转为 `None`；如果它是业务非法值，才进入 reject。
- reject 必须有 reason code 和样本。大量 reject 不能只写“源端脏数据”，必须解释到字段和值。

### 4.9 `capabilities`

```python
"capabilities": {
    "actions": (
        {
            "action": "maintain",
            "manual_enabled": True,
            "schedule_enabled": True,
            "retry_enabled": True,
            "supported_time_modes": (),
            "schedule_time_policy": None,
        },
    ),
}
```

- 是否允许手动维护：
- 是否允许自动调度：
- 是否允许重试：
- `supported_time_modes`：`point` / `range` / `none`
- `schedule_time_policy`：自动任务如何从排程生成时间意图；不适用时显式为 `None`，不得由 Ops 自行展开源接口日期参数。
- 使用 `schedule_time_policy` 时必须逐项写清 `policy`、允许的 `schedule_types`、`cron_repeat_modes`、`explicit_time_input`、`generated_time_mode`、`generated_time_field` 和 `policy_parameters`；生成的时间模式必须属于本 action 的 `supported_time_modes`。

### 4.10 `observability`、`quality`、`transaction`

```python
"observability": {
    "progress_label": "",
    "observed_field": None,
    "audit_applicable": False,
},
"quality": {
    "reject_policy": "record_rejections",
    "required_fields": (),
    "unit_date_field": None,
    "duplicate_key_policy": "allow",
    "required_distinct_values": {},
    "batch_unique_key_fields": (),
    "source_multiplicity_policy": "reject",
    "empty_result_policy": "allow",
    "pre_write_validator_key": None,
},
"transaction": {
    "commit_policy": "unit",
    "idempotent_write_required": False,
    "write_volume_assessment": "",
}
```

- `observability.progress_label`：
- `observability.observed_field` 必须与 `date_model.observed_field` 保持一致。
- `observability.freshness_policy` 由 definition builder 从 `src/foundation/datasets/freshness_policies.py` 注入，开发文档必须说明本数据集归属哪一种 policy，但不要在 `DATASET_ROWS` 中重复保存。
- `quality.required_fields` 必须覆盖不能缺失的业务主键和日期字段。
- `quality.unit_date_field`、重复键、必备枚举、批内唯一键、源端多重记录、空结果和写前校验策略必须按当前数据集真实风险填写，不能依赖 writer 临场猜测。
- `transaction.commit_policy` 当前支持 `unit` 和受专用 write path 约束的 `raw_then_serving`；具体组合必须通过 Definition linter，不得自行创造提交策略。
- `transaction.write_volume_assessment` 必须写人话，说明单事务写入量如何被控制。

### 4.11 `completeness`

```python
"completeness": {
    "scope": "",
    "subject_kind": None,
    "subject_key_fields": (),
    "actual_key_fields": (),
    "universe_strategy": None,
    "universe_source_table": None,
    "universe_key_field": None,
    "universe_name_field": None,
    "lifecycle_start_field": None,
    "lifecycle_end_field": None,
    "status_field": None,
    "active_status_values": (),
}
```

- `scope`：说明是日期桶、对象池、组内成员还是不适用；不得从表名猜测。
- 需要对象完整性时，必须明确期望对象来源、实际键、生命周期和状态字段；不得用页面当前出现的对象反推完整对象池。
- 不适用时也要给出明确 scope 与理由，不能省略整个合同。

---

## 5. 表结构、DAO 与迁移设计

### 5.1 表设计

#### A. `raw_<source>.<table>`

- ORM 模型路径：
- 主键：
- 字段清单：
- 审计字段：
- 索引：
- 是否分区：

#### B. `*_std.<table>`（如启用）

- ORM 模型路径：
- 标准字段映射：
- 清洗规则：
- 主键与索引：

#### C. `core` / `core_serving` / `core_serving_light`（如启用）

- ORM 模型路径：
- 对外字段口径：
- 主键：
- upsert 冲突列：
- 索引：
- 是否分区：

### 5.2 工程硬约束

1. 数值类型默认使用 `DOUBLE PRECISION`；若使用 `NUMERIC`，必须逐字段说明理由。
2. 对于源站中语义明确、格式稳定的日期字符串（例如 `YYYYMMDD`），raw 层允许直接落 PostgreSQL `date`；字段名保持不变，不额外保留第二份字符串镜像。
3. 有 `trade_date` 且数据量较大的表，必须评估分区；默认年分区，超大表可月分区。
4. 有 `ts_code + trade_date` 语义时，默认主键为 `(ts_code, trade_date)`，并评估 `trade_date` 方向索引。
5. 新 ORM 模型必须能被 `src.foundation.models.table_model_registry.table_model_registry()` 发现；freshness 观测依赖该 registry。
6. 新表必须有 Alembic 迁移，迁移和 ORM 模型字段必须一致。
7. 新增 Alembic 迁移前必须先执行 `alembic heads`，`down_revision` 只能接真实 head。
8. 重建、清空或删除业务表必须有明确确认；迁移文件中要把 destructive rebuild 的确认来源写清楚。
9. 字段扩表不是只改 ORM；必须同步 `DatasetDefinition.source_fields`、raw/core ORM、Alembic 迁移、测试、Lake prod-raw-db 白名单（如适用）和相关文档。
10. 如果源站输出字段全量落 raw，raw 表业务字段必须与源站输出字段逐列对齐；系统字段单独说明。

### 5.3 DAO

- Raw DAO：
- Core/Serving DAO：
- 是否需要新增 DAOFactory 属性：
- `bulk_upsert` / `insert` / 特殊写入策略：
- 幂等策略：

---

## 6. Ingestion 实现设计

### 6.1 请求构造

- `request_builder_key`：
- 函数位置：`src/foundation/ingestion/request_builders.py`
- 输入来自 `DatasetActionRequest.time_input` / `filters` / `base_params`：
- 是否需要源端字段名转换：
- 是否需要默认参数：
- 是否只做源接口格式化，不承担业务日期语义判断：
- 如果需要日期、月份或窗口转换，请说明为何不应放在 resolver：

### 6.2 Unit 规划

- `unit_builder_key`：
- unit 维度：日期 / 月份 / 股票 / 指数 / 板块 / 枚举 / 组合
- unit_id 组成：
- `progress_context` 字段：
- 单 unit 最大数据量评估：
- 单次执行最大 unit 数评估：
- 本任务是否以 Prod 数据集为目标；如是，是否触发 0.3.5 长任务门禁，unit 是否同时构成进度、取消、持久化和续跑边界：

### 6.3 Source Client 与分页

- adapter：`tushare` / `biying` / 其他
- `pagination_policy`：
- `page_processing_mode`：`buffer_all` / `staged_stream`
- 单页参数：
- 结束条件：
- 限速策略：
- 源端错误映射：

分页硬约束：

1. 每一页都必须带同一份 `DatasetDefinition.source.source_fields`；不能只在第一页或 probe 中显式请求字段。
2. 必须记录 `offset/limit` 序列、每页行数、终止 short page、页合并行数和唯一业务键数。
3. 对达到或可能达到源端上限的范围，分页合并的唯一键集合必须与一个已证明不截断的同范围基准请求完全相等；任意漏键、额外键或内容冲突都阻断写入/上线。
4. 在 DAO `bulk_upsert` 前检测同批冲突键：完全相同可按明确定义去重；内容不一致必须以结构化错误使 unit 失败，不能依赖 DAO 的最后一行覆盖。
5. `buffer_all` 必须证明单 unit 全部分页合并后的内存和事务规模有硬上限；Prod 数据集任务触发 0.3.5 且无法证明时不得使用。
6. `staged_stream` 必须逐页写入隔离的 stage 范围，完整 unit 校验通过后再发布；中途取消或失败不得让部分 stage 数据成为对上事实。

### 6.4 Normalizer

- 字段类型转换：
- 日期转换：
- decimal/float 转换：
- required 字段拒绝策略：
- row transform：
- reject reason code：

### 6.5 Writer

- `write_path`：
- raw 写入：
- serving/core 写入：
- 是否先删后写：
- 幂等写入策略：
- 冲突列：
- 事务边界：每个 unit 一个业务数据事务
- 已提交 unit 的读回与续跑判定：
- 取消后保留 / 清理边界：

如果 Prod 数据集任务的 source client 先累积完整分页结果再写入，必须明确内存上限和单事务行数；超过 0.3.5 长任务阈值时不得把全范围数据留在内存并等到末尾首次写入。分页是否成为持久化边界取决于经评审的 `staged_stream` / write path 合同，不能自行把一个业务 unit 拆成可见的部分业务结果。数据湖任务不适用本段 0.3.5 门禁。

### 6.6 结构化错误与 codebook

- 新增 `error_code`：
- 中文语义：
- 建议动作：
- 是否需要加入 `src/foundation/ingestion/codebook.py`：
- 前端是否能通过 codebook 展示，不硬编码语义：

---

## 7. Ops、TaskRun 与页面派生

### 7.1 手动任务

- `GET /api/v1/ops/manual-actions` 是否能看到该数据集：
- 分组、顺序和可见性是否来自 `src/ops/catalog/dataset_catalog_views.py` / catalog resolver（而非 `DatasetDefinition.domain`）：
- 名称是否来自 `DatasetDefinition.display_name`：
- 时间控件是否由 `date_model` 正确派生：
- filter 控件是否由 `input_model.filters` 正确派生：
- 如 filter 会改变时间模式、单值范围或补录条件：API 条件规则、前端即时限制、后端绕过校验是否三者一致：
- 提交的 `time_input` 是否仍是用户意图，而不是源接口参数：
- 提交接口：`POST /api/v1/ops/manual-actions/<dataset_key>.maintain/task-runs`

### 7.2 自动任务

- 是否允许 `schedule_enabled=True`：
- 自动任务是否只选择数据集动作，不暴露底层执行路径：
- 如果有 `calendar_policy`，它生成的是哪种调度意图：
- 是否确认自动任务没有提前展开日期模型或生成源接口参数：
- 如源端是晚发布 / 不确定发布：是否有独立 source readiness probe；目标日期如何由交易日历求出：
- 即使与已有数据集发布时间相同，若 API、fields、样本或完整性条件不同，是否保持独立 probe service / condition，而只复用通用 TaskRun、日期目标和日志能力：
- probe schedule 的固定 target、window、interval、max triggers、filters 和 trigger mode：
- schedule API / binding service 是否拒绝非法配置，probe runtime 入队前是否再次强制 action、目标日期和 filters：
- 同一 schedule / 目标日期的 probe TaskRun 去重条件；failed 任务的重试口径：
- 生产排程是迁移 seed、配置文件还是 Ops 持久化记录；创建 / 启用所需的明确授权：
- 若 probe / schedule 有固定 target、condition、窗口、频率、触发上限或禁止 filters：是否已在 0.3.4 分别映射 schedule API、binding、runtime、自动任务表单、浏览器用户路径和反向绕过测试：
- 是否需要放入 workflow：如需要，使用 `docs/templates/workflow-development-template.md` 另写方案。
- 如另接入 Dagster sensor：是否已按 `lake_console/docs/templates/dagster-dataset-onboarding-template.html` 设计 cursor 的 `reason_code`、`blocked_component`、短中文 `summary`、`next_action`、长度预算和禁止字段：

### 7.3 TaskRun 观测

参考：[Ops TaskRun 执行观测模型重设计方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-task-run-observability-redesign-plan-v1.md)

必须填写：

- 当前对象类型：股票 / 指数 / 板块 / 日期 / 月份 / 枚举 / 其他
- 当前对象标识字段：
- 当前窗口字段：
- `progress_context` 示例：
- 失败时 `TaskRunIssue.object_json` 示例：
- 是否有 `rows_rejected`：
- 是否有 `rejected_reason_counts` / `rejected_reason_samples`：
- 进度总量来自哪里，何时冻结：
- 已完成量是否只在业务持久化边界后递增：
- 进度更新频率与最大静默时长：
- 取消检查点与最大取消延迟：
- TaskRun 与活动节点如何同步终态：
- ETA 是否可可靠计算；不可计算时的页面文案：

展示原则：
- 页面主指标只展示最终已提交结果，不把中间尝试写入量当成已入库结果。
- 后端输出结构化 token，Ops 层负责转换为用户可读展示。
- 不得在前端按 dataset_key 写专用文案分支。
- 进度只能在业务持久化边界完成后增加，且必须单调；心跳和当前阶段不能冒充已完成量。
- 若复用现有 ETA 页面能力，ETA 由浏览器按 10 秒样本窗口从已提交 unit 进度推算；样本不足或速度不稳定时显示“暂无法估算”。

### 7.4 数据状态、数据源卡片与 freshness

- `target_table` 是否能在 `table_model_registry()` 找到 ORM 模型：
- `date_model.observed_field` 是否存在于目标 ORM 模型：
- 无日期数据集是否明确展示最近同步迹象而非新鲜/滞后：
- 数据源卡片是否显示正确 source：
- direct-serving 时 `raw_table=None` 是否贯穿 projection、snapshot、schema 和页面；来源页是否明确显示 target/serving 表而不显示伪造 raw 表或“—”：
- `ops-rebuild-dataset-status` 后是否能生成正确快照：

### 7.5 日期完整性审计

- `audit_applicable`：
- 审计日期桶：
- 期望桶生成规则：
- 实际桶读取字段：
- 不适用原因：

---

## 8. 测试与门禁

### 8.1 必补测试

- DatasetDefinition registry：
  - 新 dataset key 在正确 domain 文件中
  - `tests/architecture/test_dataset_runtime_registry_guardrails.py` 的 domain key 矩阵已更新
- Resolver / planner：
  - point / range / none / month 视数据集能力覆盖
  - unit_count、unit_id、request_params、progress_context 正确
  - Prod 数据集长任务总量可冻结，超预算拒绝，不允许边执行边无限扩展计划
- Request builder：
  - 时间参数映射
  - filter / enum 参数映射
  - 不产生非法 ALL sentinel
  - connector payload 中的 `fields` 等于 `DatasetDefinition.source_fields`
  - 对分页接口，真实 connector 或等价测试替身覆盖第二页、short page 和页合并唯一键对账
- Normalizer：
  - date / decimal / required fields
  - row transform 可注册并可执行
  - reject reason 统计
- Writer：
  - 幂等 upsert
  - conflict_columns
  - 单 unit 事务边界
  - 同批冲突键的相同 / 不同内容处理
  - direct-serving 时不解析 raw DAO；raw/core 既有路径完整回归
  - Prod 数据集长任务中途取消或进程退出后，已提交 unit 可读回、未提交 unit 不可见；续跑和幂等重放无重复
- Ops API：
  - manual-actions
  - catalog
  - task-runs
  - freshness / dataset-cards
  - 如有 source probe：schedule API、binding、runtime action / filters 防篡改、目标日期去重
- Runtime / TaskRun（Prod 数据集长任务适用）：
  - 进度只在持久化边界后单调递增，连续运行不超过 30 秒无可见更新
  - queued / running 取消、进程退出后续跑、TaskRun 与节点终态一致
  - 状态观察写失败不回滚业务数据，业务失败不生成成功状态
- Frontend（如显示或交互变化）：
  - 页面能看到动作
  - 表单控件正确
  - 任务详情和数据状态展示正确
  - filter 条件改变时间模式时即时更新且后端拒绝绕过请求
  - direct-serving 卡片显示 target/serving 表，raw-backed 卡片无回归
  - 自动任务 / probe 有固定或禁止配置时：选择该动作后只出现允许的 condition；固定值已回填并不可编辑；不允许的日期、filters、trigger mode 与 calendar policy 不出现；提交前 payload 与后端固定契约一致
  - 上述用户可见限制必须由 Playwright（或等价真实浏览器）从“新建 / 编辑 -> 选择动作”完整验证

### 8.2 必跑命令

```bash
pytest -q tests/architecture/test_subsystem_dependency_matrix.py
pytest -q tests/test_dataset_definition_registry.py tests/test_dataset_action_resolver.py tests/test_dataset_unit_planner.py
pytest -q tests/architecture/test_dataset_runtime_registry_guardrails.py tests/architecture/test_dataset_maintenance_refactor_guardrails.py tests/architecture/test_arch_no_all_sentinel.py
GOLDENSHARE_ENV_FILE=.env.web.local goldenshare ingestion-lint-definitions
python3 scripts/check_docs_integrity.py
git diff --check
```

按改动范围追加：

```bash
pytest -q tests/test_dataset_normalizer.py
pytest -q tests/test_dataset_writer_<dataset>.py
pytest -q tests/web/test_ops_manual_actions_api.py tests/web/test_ops_catalog_api.py tests/web/test_ops_freshness_api.py tests/web/test_ops_schedule_api.py tests/web/test_ops_probe_api.py
cd frontend && npm run typecheck && npm run test && npm run build
# 如有页面交互改动：运行覆盖该用户路径的 Playwright spec，并在 0.3.4 记录 spec 与结果
```

### 8.3 验收勾选

- [ ] 0.3.4 硬需求追溯账本已填写；本阶段所有关联行均为“已验证”，不存在空白或未解释的“不适用”
- [ ] 每次里程碑 / 提交前已将追溯账本与实际 `git diff`、前序提交和测试文件对账；不存在未覆盖消费者
- [ ] 源站文档与 docs index 已更新
- [ ] 0.3.3 源字段端到端对账表已填完，源文档、真实样本、`source_fields`、ORM、迁移、真实表、Lake 白名单口径一致
- [ ] DatasetDefinition 完整事实合同已填写，与当前模型和 linter 一致
- [ ] 新数据集没有旧执行术语或旧路由
- [ ] 没有新增 `__ALL__` / `__all__` 业务占位值
- [ ] 没有私自新增 checkpoint / acquire / 第二套任务状态机；如为 Prod 数据集长任务，0.3.5 已批准且续跑来源明确
- [ ] ORM、DAO、迁移一致
- [ ] Alembic `down_revision` 已按真实 `alembic heads` 确认
- [ ] `target_table` 能被 table model registry 发现
- [ ] 日期模型能驱动手动任务、freshness 和审计
- [ ] Ops 展示目录配置 `src/ops/catalog/dataset_catalog_views.py` 已确认，数据源页 / 手动任务 / 自动任务的展示分组一致
- [ ] Ops/TaskRun 保存的是用户或调度意图，没有提前展开为源接口参数
- [ ] `DatasetActionResolver` 测试覆盖该数据集的时间输入归一化
- [ ] 测试覆盖 `TaskRun.time_input_json -> DatasetActionResolver.build_plan() -> PlanUnit.request_params`
- [ ] 单事务写入量已真实评估并写入 `transaction.write_volume_assessment`
- [ ] 已判断目标是否为 Prod 数据集；仅在是时判断是否属于长任务，并在适用时验证批量内存上限、分批持久化、取消、进程退出、续跑、幂等、进度单调和节点终态
- [ ] 分页已用项目实际 connector（或同等请求层）验证第二页、short page 和分页合并唯一键集合；未用无日期/宽区间截断结果充当基准
- [ ] request builder、unit planner、normalizer、writer 均有测试
- [ ] 同批冲突键不会被 DAO 静默最后一行覆盖；冲突的结构化错误和样本可追溯
- [ ] reject reason code 和 rejected reason samples 可解释，任何 reject 都有字段和值样本
- [ ] TaskRun 详情展示可读，无重复错误信息
- [ ] Prod 数据集长任务页面显示阶段、当前对象、完成量、总量、百分比和最后更新时间；30 秒内有可见更新，ETA 不可靠时明确不展示估算
- [ ] 数据源卡片和数据状态页展示正确；direct-serving 的无 raw 层与 target/serving fallback 已验证，raw-backed 页面无回归
- [ ] 若 filter 有条件时间 / 范围约束：Manual Action API、前端控件与 resolver / planner 拒绝逻辑一致
- [ ] 若使用 source readiness probe：schedule API、binding service、runtime 防篡改和按目标日期去重都已覆盖；生产 schedule 的创建权限和持久化来源已确认
- [ ] 若自动任务 / probe 有用户可见固定或禁止配置：已从新建 / 编辑页面完整走通浏览器测试，验证唯一选项、固定值、隐藏 / 禁用控件和提交 payload
- [ ] 如接入 Dagster sensor，cursor 已遵守 Dagster 数据集接入模板：不写报告型 batch/readiness 明细，能一眼看出触发或 skip 原因
- [ ] 门禁命令已通过并记录输出

### 8.4 阶段完成记录

每个项目里程碑单独填写，不能以一个后端测试集代表整个阶段。

| 阶段 | 本阶段追溯 ID | 已验证代码 / 提交 | 已验证测试与真实证据 | 未完成项 / 风险 | 结论 |
| --- | --- | --- | --- | --- | --- |
| M0 / 设计验证 |  |  |  |  | 未开始 / 部分完成 / 已完成 |

完成判定：只要本阶段任一追溯行未验证，结论必须是“部分完成”，并列出缺口与下一步；禁止写“阶段完成，后续再补前端 / 测试 / 实测”。

---

## 9. 发布与回滚

- Alembic 迁移：
- 发布顺序：
- 如需生产排程 / probe rule：创建入口、持久化位置、启用顺序和授权人；不得在 Alembic 中隐式 seed：
- 是否需要重建数据状态：`goldenshare ops-rebuild-dataset-status`
- 最小真实同步命令：
- Prod 数据集长任务最小运行 / 取消 / 续跑 / 读回命令与证据：
- 验收查询 SQL：
- 回滚方式：
- 风险点与处理：

---

## 10. 本次交付快照

- 当前已支持：
- 当前不支持：
- 已知风险：
- 后续计划：
