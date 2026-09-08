# DatasetDefinition 数据集定义与职责

更新时间：2026-09-08。状态：现行代码合同说明。本文承接原定义主案、枚举参考、Universe 与输入筛选清理方案的有效内容；旧迁移过程通过 Git 历史追溯，不作为当前操作指令。

## 1. 职责与入口

`DatasetDefinition` 定义“数据集是什么”，`DatasetExecutionPlan` 表达“一次维护如何执行”。二者不是并列的静态事实源。

- 定义、构建与查询：[models.py](/Users/congming/github/goldenshare/src/foundation/datasets/models.py)、[registry.py](/Users/congming/github/goldenshare/src/foundation/datasets/registry.py)、[definitions](/Users/congming/github/goldenshare/src/foundation/datasets/definitions)。
- 请求解析与执行：[执行计划专题](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)。
- 日期字段、锚点及消费者：[日期消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)。
- 分层、数据类型与开发门禁：[Foundation 研发基线](/Users/congming/github/goldenshare/docs/architecture/foundation-current-standards.md)、[数据集模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)。

完整字段看模型；完整数据集清单从 `list_dataset_definitions()` 读取。本文不维护手工数量快照，也不复制全量 Python 类定义。

## 2. 字段归属

| 部分 | 负责的事实与边界 |
| --- | --- |
| `identity` | dataset key、名称、别名、逻辑数据集身份与来源优先级；旧任务路由不是数据集身份 |
| `domain` | 底层数据域；不等于 Ops 展示分组、更新频率或 freshness 策略 |
| `source` | 默认/允许来源、adapter、API、显式源字段、源文档、request builder 与基础参数 |
| `date_model` | 时间输入、执行锚点、观测字段与日期审计语义 |
| `input_model` | 时间字段、业务筛选、必填组、互斥组与字段依赖 |
| `storage` | 目标、Raw/Std/Serving/observation/stage、DAO、冲突键、行归属与替换范围 |
| `planning` | 对象池、枚举扇出、请求变体、分页、unit builder、批量上限、拉取并发 |
| `normalization` | 日期/数值转换、必需字段与行转换器 |
| `capabilities` | 动作、手动/自动/重试能力、支持的时间模式及动作级调度日期策略 |
| `observability` | 进度标签、freshness 策略及现有观测投影字段；执行计划的观测日期/审计适用性取自 `date_model` |
| `quality` | 拒绝、空结果、重复键、必需值集合、写前校验等质量要求 |
| `transaction` | 提交策略、幂等要求、写入量评估 |
| `completeness` | 完整性范围、对象身份、预期对象来源与生命周期；不能仅用日期桶存在代替对象完整性 |

模型中的字符串默认值不自动成为允许的新业务语义。取值及组合要经过 definition 构建、linter、实现注册表与消费者核验。

## 3. 输入、枚举与来源

### 输入必须对应真实意图

源接口支持一个可选参数，不代表应该向运营开放。新增或修改输入，按根 AGENTS 与数据集模板完成源文档、真实行为和全量消费者核验。

- `time_fields` 表达时间输入；`filters` 表达有明确用途的业务过滤。分页参数不是运营常规输入。
- `enum_values` 是实际业务取值；`option_labels` 只解释已声明取值，不能新增值。
- 多选/全选须展开真实枚举集合。`__ALL__` 不得进入源请求、查询上下文或业务落库字段。
- `enum_fanout_fields/defaults` 表示不同组合生成不同 unit；`request_variant_fields/defaults` 表示同一 unit 内的请求变体，不能互换。
- `required_groups`、`mutually_exclusive_groups`、`dependencies` 由模型声明、validator 消费；页面不另造契约。

历史输入清理保留的教训：无效字段即使被 request builder 丢弃，也会污染动作目录、TaskRun 意图和计划参数/身份。原六个数据集的 `exchange` 清理已完成，不能继续按“待修复问题”推进；当前拒绝用例还覆盖后续新增的 `cyq_chips`。有效的其他数据集 `exchange` 不在删除范围，见 [resolver 回归](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py) 的 `rejects_removed_exchange_filter` 及合法 exchange 用例。

### 来源与 selector 不混用

`source_key_default/source_keys` 表示来源选择，`adapter_key` 选择客户端，`request_builder_key` 选择参数构造器，`unit_builder_key` 选择规划器，`row_transform_name` 选择归一化转换。这些是不同职责，不能用一个名称替代其他字段。

新增 selector 必须有实现、注册与测试。当前入口见 [request_builders.py](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)、[unit_planner.py](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)；不得把字符串写进 Definition 就当作能力已经实现。

<a id="universe-contract"></a>

## 4. 对象池定义与特殊边界

`planning.universe_policy` 的现行业务值为 `pool/no_pool`；`none` 是历史未定义占位，不作为新数据集的业务含义。模型仍有该默认值，不代表允许依赖默认值省略审计。

`planning.universe` 描述请求字段 `request_field`、显式选择字段 `override_fields`、有序来源 `sources(type/resource)`。这里的字段属于 Definition；Plan 已保存展开后的 units，并不包含 `plan.planning.universe`。

`override_fields` 不能被概括为“有输入就无条件绕过对象池”。代表性边界如下，真实行为必须连同 planner 与测试读取：

| 数据集/场景 | 必须保留的边界 |
| --- | --- |
| `index_weight` | 显式 `index_code` 不查默认池；默认先查 `index_weight` active 池，空时查未终止的 `index_basic`，全部为空报 `universe_empty` |
| `stk_mins` | 默认 active equity 池优先使用 Tushare 来源；显式 `ts_code` 不扫描默认池；频率与窗口仍由现行 builder 处理 |
| `biying_equity_daily/moneyflow` | 默认读本地 Biying stock_basic 的 `dm/mc`；显式 `ts_code` 转为 `dm`；保留日线复权类型扇出、资金流 100 天窗口 |
| `index_mins` | 默认用 `index_mins` active 池；显式代码仍须在该池内，不回退到 `index_basic` |
| `dc_member` | 默认来源为按日期读取的本地 `dc_index`；不得恢复规划阶段远程 fallback；显式板块/成分过滤仍遵守 builder |
| `ths_member` | 默认来源为本地 `ths_index` 快照；来源与空池失败语义不能隐藏在旧 selector 中 |
| `index_daily` | 请求池 `index_daily_raw` 与 Serving 的 `index_daily` active 池是两件事；Raw 保存本次返回，Serving 再筛选，不能因字段标记或通用规则改变范围 |

对象池契约收口不代表所有专用 builder 已可被一个通用算法替换。`no_pool` 也不能作为“整个链路绝不读取任何对象集合”的证明；对既有特殊路径须核验实际实现，不在本轮文档整理中重构它。

行为依据：[DatasetUnitPlanner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)、[registry 测试](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)。这些路径解释现行行为，不授权改变对象池数据。

## 5. 存储、质量与观测语义

### 存储与执行分别表达

`delivery_mode` 表达交付方式，`layer_plan` 表达经过的层，`write_path` 选择具体 writer。以 [Foundation 基线 §3](/Users/congming/github/goldenshare/docs/architecture/foundation-current-standards.md#3-foundation-分层与数据路径)为准，不要求所有数据集物理走完 Raw/Std/Serving，也不要求为 Serving 视图增加 writer。

例如 `raw_only_upsert` 只说明写 Raw；是否通过 Serving/Light 视图提供查询，须读 storage 与实际消费者。`serving_direct_upsert` 及 observation/scope/stage 等专用路径已有独立限制，不得漏列后反推“必须写 Raw”。

完整写入组合、质量规则与事务限制统一查 [linter.py](/Users/congming/github/goldenshare/src/foundation/ingestion/linter.py)、[writer.py](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)及数据集模板 §4–6。不要复制一份容易遗漏新策略的全量枚举表。

`row_identity_filters` 表达共表数据集的行归属；`replacement_scope_fields` 表达替换范围；`conflict_columns` 表达写入冲突身份，三者不能互相替代。质量拒绝必须解释原因和样本；声明 `record_rejections` 不是允许忽略大量拒绝。

### Freshness 策略单处维护

策略从 [freshness_policies.py](/Users/congming/github/goldenshare/src/foundation/datasets/freshness_policies.py)登记并构建到 Definition，不放回已退场的 `domain.cadence`，也不在 Ops、前端、报表复制映射。

| 策略 | 判断口径 |
| --- | --- |
| `continuous_open_day` | 连续开市日的业务日期 |
| `continuous_natural_day` | 连续自然日的业务日期 |
| `period_bucket` | 周、月、月份窗口等周期桶 |
| `event_run_trace` | 事件维护迹象及真实观测值，不要求每天有事件 |
| `snapshot_run_trace` | 快照维护迹象及真实观测值，不用同步日期伪造业务日期 |

事件/快照未确认维护状态的 `unconfirmed` 与技术事实缺失的 `unknown` 不混用。观测要求不改变“状态写失败不得回滚业务数据”的边界。

## 6. 派生消费者与变更范围

- Ops 的动作、catalog、cards、freshness、snapshot、完整性审计消费 Definition 投影；展示分组/排序归 [dataset_catalog_views.py](/Users/congming/github/goldenshare/src/ops/catalog/dataset_catalog_views.py)，不反写底层 domain。
- Ops 保存意图，Resolver 负责日期归一化与计划生成；API/前端只消费派生能力，不能另建事实映射。
- 主任务与详情使用 TaskRun；现行 API 见 [Ops 当前契约](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md)。原方案拟建的 URL 和投影类名不是现行 API 定义。
- 修改 Definition 必须覆盖所有实现方与消费者，并同步数据集模板；输入、日期、对象池、写入身份和配置的变更分别遵守根 AGENTS，不能以“内部整理”为由改现行 CLI/API 行为。

## 7. 维护与历史边界

定义/解析变更至少核对 registry、resolver、freshness 与相应架构护栏；按 [数据集模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)选择测试与获准的真实验收。文档整合本身只运行文档检查，不执行同步、重建或迁移。

旧单一事实源与对象池迁移已形成当前入口，原阶段计划不再是待办。旧运行历史的导出、清空、重建建议已撤销为当前操作指导；任何实际数据清理都需新的明确授权。历史方案全文可从 Git 追溯，本文件不宣称所有运行态目标已验收。
