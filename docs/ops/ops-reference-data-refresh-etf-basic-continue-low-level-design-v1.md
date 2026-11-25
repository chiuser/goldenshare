# 基础主数据刷新：ETF 基础信息失败后继续 LLD v1

日期：2026-11-25。状态：本地实现及完成后审计通过，相关验证 41 项通过；管理员已授权提交本任务代码、测试和文档，未部署或运行生产任务。开发前证据保留在 §9，本轮实现和逐项验证见 §10。

对应[方案](/Users/congming/github/goldenshare/docs/ops/ops-reference-data-refresh-etf-basic-continue-plan-v1.md)。本 LLD 只设计 `reference_data_refresh` 的一个步骤策略，不修改 ETF 基础信息的数据合同。

## 1. 目标与硬口径

| 编号 | 管理员确认的约束 | 实现位置 | 验证 |
| --- | --- | --- | --- |
| R1 | 只让基础主数据刷新中的 ETF 基础信息失败后继续 | `action_catalog.py` 中该步骤的 `failure_policy_override` | T1、T2 |
| R2 | 其余 9 步、顺序、默认失败规则和其他工作流保持 | 同一注册表；不修改 dispatcher/worker | T1、T3 |
| R3 | ETF 基础信息仍执行和校验，错误快照不入库，原表保留 | 原 Definition、normalizer、writer、snapshot validator | T2、T4、T5 |
| R4 | 失败节点与技术诊断保留，任务不能冒充全部成功 | 原 dispatcher 记录 issue、worker 写终态 | T2、T6 |
| R5 | 无日期入口、手动/自动/重新提交语义保持 | 原 manual action、scheduler、TaskRun 服务 | T1、T2、T7 |
| R6 | 独立维护 ETF 基础信息行为保持 | 原 dataset action 分支 | T5 |
| R7 | 本轮仅按白名单本地开发、测试、同步文档，并按管理员后续明确授权提交；不推送、不部署、不补数 | §8 文件清单和本轮操作边界 | 差异审计；生产操作为 0 |

数量依据：当前 `reference_data_refresh.steps` 有 10 个元素，其中 ETF 基础信息 1 个，其余为 10 − 1 = 9 个；完整清单见方案 §3，不从修改后的实现动态生成预期。

## 2. 当前实现及影响面

已使用 CodeGraph 的 `codegraph_status`、`codegraph_search`、`codegraph_node`、`codegraph_callers`、`codegraph_callees` 查定义和调用关系，并以当前源码核对。CodeGraph 的 `commit`、`build_plan` 等同名匹配出现了无关候选，不把它们当作本任务调用关系；下面列出的链路均按实际 import 和调用点确认。

| 环节 | 当前代码 | 本次影响 |
| --- | --- | --- |
| 定义 | `src/ops/action_catalog.py::WorkflowStepDefinition`、`_dataset_workflow_step`、`WORKFLOW_DEFINITION_REGISTRY` | 只调整目标步骤字段；类型 frozen，使用 `replace` |
| 手动入口 | `src/ops/queries/manual_action_query_service.py::_build_workflow_route`、`src/ops/services/manual_action_service.py::_resolve_workflow_time` | 继续仅无日期模式；不新增参数 |
| 调度/重提 | `src/ops/services/operations_schedule_service.py`、`src/ops/services/task_run_service.py::retry_task_run` | 保留创建工作流意图的原行为，不在持久化参数中增加策略 |
| 编排 | `src/ops/runtime/task_run_dispatcher.py::_dispatch_workflow` | 运行时取工作流定义；普通错误使用步骤覆盖或工作流默认策略决定是否停止 |
| 数据维护 | 同 dispatcher 的 `_step_task_run`、`_build_dataset_action_request`、`_run_dataset_action_plan`，再到 `DatasetActionResolver`、`DatasetMaintainService` | 参数、计划、业务读写和提交方式不改 |
| ETF 写入 | `src/foundation/ingestion/writer.py::_write_etf_basic_snapshot_replace`、`etf_basic_snapshot.py::validate_etf_basic_snapshot` | 源列表校验在业务替换前；原错误及事务不改 |
| 后 3 步 | `reference_master.py`、`index_series.py` 中相应定义，`request_builders.py::_etf_index_params/_index_basic_params/_hk_basic_params` | 均为直接源接口、无对象池规划，不依赖本次 ETF 主数据刷新成功 |
| 最终状态 | `src/ops/runtime/worker.py::_finalize_task_run`、TaskRun/节点/issue 三表 | 正常错误场景保留部分成功和原始错误 |
| 目录/API/前端 | `src/ops/queries/catalog_query_service.py`、`src/ops/schemas/catalog.py`、`frontend/src/pages/ops-v21-task-manual-tab.tsx`、`frontend/src/pages/ops-task-detail-page.tsx` | 目录步骤数、名称、动作、日期和响应字段不变；失败策略不是现有目录响应字段，不新增前端控制 |
| freshness/自动覆盖 | `src/ops/queries/freshness_query_service.py` 按工作流步骤识别数据集的消费者 | ETF 步骤仍在，不改变覆盖名单，不把失败当作成功发布 |

本变更位于 Ops 的编排定义，不新增跨子系统依赖。ETF 主数据的行情、分钟线、申赎清单等消费者不迁移；它们继续使用上次成功发布的主数据，源端未修复期间新增身份可能暂未入库，这是当前失败的已有影响。

## 3. 最小实现

开发文件限于 `src/ops/action_catalog.py`：在现有 dataclasses import 加入 `replace`，只将下列步骤表达式替换为目标形式：

```python
replace(
    _dataset_workflow_step("etf_basic", "etf_basic"),
    failure_policy_override="continue_on_error",
),
```

目标位置保留一条说明原因及方案路径的简短注释。其余步骤仍使用原表达式，工作流默认策略仍为 `fail_fast`。不扩展 helper 签名，不复制 DatasetDefinition 派生字段，不写按异常 ETF 代码判断的分支。

复用前已核对的真实语义：

1. helper 只从 DatasetDefinition 派生动作、中文名及数据集编码，其他值沿用步骤默认值；`replace` 仅变更失败策略。
2. dispatcher 普通异常分支先回滚未提交事务、记录 issue、结束失败节点，再根据 `failure_policy_override or workflow.failure_policy_default` 判断是否 `break`。
3. 这次 `etf_basic_snapshot_invalid` 不属于 `normalize.source_validation_failed` 的强制结束分支，可走现有继续规则；不修改专门异常分支。
4. 默认策略是步骤级策略，覆盖该步骤的普通执行错误，不只针对 `562430.SZ`。不新增按错误码区分策略的能力。
5. 字段 `max_retry_per_unit=2` 是原步骤声明；不据此承诺该工作流已实现失败后自动重试两次，本次不增加重试。

## 4. 请求、业务数据与观测

输入仍为 `time_input={"mode":"none"}, filters={}`，工作流仍按固定的 10 步串行运行。所有参数继续按父请求、步骤默认参数、步骤覆盖参数的现有顺序合成。

ETF 基础信息仍请求完整快照，主键 `ts_code`、14 个业务字段、分页、归一化及 Raw/Serving 原子替换保持原设计。源记录 `562430.SZ + SH + P + 空设立日/上市日` 应继续产生 `etf_basic_snapshot_invalid`，不能过滤后当作完整快照。校验前后的旧表保护沿用现有 writer。

不为 `raw_tushare.etf_basic`、`core_serving.etf_basic` 新增写入路径；ETF 基础信息校验通过后仍按原规则刷新这两张表。其他数据集同样仅执行原有任务写入。没有新增配置、SQL、数据库迁移、状态写入规则或大事务。TaskRun/节点/issue 的观测不参与业务数据回滚策略。

在“只有 ETF 基础信息失败，且未取消”的样本下，预期：

| 对象 | 预期 |
| --- | --- |
| ETF 工作流节点 | `failed`；关联 issue，保留原始错误码及 `ts_code/exchange/expected_exchange` |
| 其余工作流节点 | 9 个 `success`，节点顺序与方案字面清单一致 |
| TaskRun | `partial_success`、`status_reason_code=workflow_step_failed`、原错误仍可定位 |
| 步骤汇总 | 最终 `unit_total=10`、`unit_done=9`、`unit_failed=1`；最终进度 `(9+1)/10×100=100%`，不是 10 个步骤全部成功 |
| ETF 业务表 | 这次错误快照不替换已发布数据 |

不能把节点显示的 0 行读取推断为源端未请求。当前错误路径未完整保留该次源获取量，本次不补造计数。最终摘要文字可能被后续成功步骤的摘要覆盖，失败事实须用任务状态、issue 和 ETF 节点判断；不为本次需求改摘要生成逻辑。

## 5. 中断、重新提交和生效

- 保留每个数据集已有业务提交边界。发生后续失败或取消时，前面已提交的数据不自动回滚。
- 保留现有取消检查与 worker 终态逻辑。普通 workflow 的取消异常、任务终态和节点终态存在已知局限，本次不承诺每个节点都转为 canceled，也不把取消请求当成可以继续做业务的授权。
- T8 须覆盖目标步骤期间收到取消请求后，不再产生后续源请求或写入；若现有行为使该约束无法成立，先停止开发并同步方案，不能擅改 dispatcher/worker。
- 进程退出后不增加自动接续；重提为新 TaskRun，并从第一步执行。测试和预算须包括重复执行已完成步骤，不使用 `resume_from_step_key` 宣称已有步骤续跑。
- 运行中的工作流已取得的定义不会中途替换。本轮不停止或重启任何任务或服务。
- 后续获准发布时须核对 Web/worker/scheduler 加载的实际代码版本；部署动作另由管理员安排。生产 `21026` 的历史记录保留，新结果写到新任务。

## 6. 性能与读写预算

本次不新增源请求类型、数据扫描、缓存、进程、队列或业务事务。仅目标错误场景比原来多执行后 3 步；正常全部成功场景仍执行原有 10 步。单次 ETF 失败的耗时、其余步骤分页数、重跑和最终业务对账耗时均无固定保证，不能由“继续”推断快速结束。

开发验证使用隔离 SQLite 和字面源样本；真实源请求与生产业务写入为 0。基线测试使用现有 `.venv`，设置 `PYTHONPATH=packages/technical_indicators/src`、`PYTHONDONTWRITEBYTECODE=1`、`GOLDENSHARE_ENV_FILE=/dev/null`、`-p no:cacheprovider`，所有临时资源放 `/private/tmp`，不安装或升级依赖。

正式运行的验收成本另按目标版本、新 TaskRun、最多 10 个工作流节点和关联 issue 进行有界元数据读取；数据检查先计数及必要样本，不能因此取得全局数据明细读取授权。不得为本地开发验收重新全量获取 ETF 源列表。

## 7. 开发测试与验收清单

以下为开发验收清单；本轮已新增、调整或复用对应测试，实际结果见 §10。§9 保留的开发前基线不单独作为目标策略已经实现的证据。

| 编号 | 测试位置及场景 | 必要断言及独立依据 |
| --- | --- | --- |
| T1 | `tests/test_ops_action_catalog.py` 中目标工作流断言；`tests/web/test_ops_catalog_api.py` 中目录断言 | 使用方案 §3 的独立字面顺序清单；仅 `etf_basic` 为 `continue_on_error`，其余 9 步为原默认值，工作流默认仍 `fail_fast`。目录没有减少步骤、增参或增加策略字段；其他工作流字段与开发前一致。 |
| T2 | `tests/web/test_ops_runtime.py` 增加目标工作流回归，覆盖 manual/scheduled/retry | 使用真实 dispatcher、worker 和隔离 TaskRun 表；替代源下载及业务执行，在 ETF 步骤抛出与真实 issue 同合同的 `IngestionWriteError`；断言后 3 步按序执行，9 成功/1 失败、部分成功、结构化错误不变。该关键回归须先在当前代码失败，改动后通过。 |
| T3 | 同文件，对其他 9 个步骤分别注入普通失败 | 只运行到失败步骤；后续不开始。包含 ETF 基础信息之后的步骤，防止误将整个工作流变为继续。不能用修改后的循环结果生成 expected。 |
| T4 | `tests/test_etf_basic_snapshot_writer.py` 增加实际异常样本 | 样本来自本会话 2026-11-25 有界源响应，完整字段按 Definition 合同构造；明确 `.SZ+SH+P+空日期` 拒绝。`.SH+SH+P+空日期` 和现有合法 L/D/.OF 样本继续按原合同处理，证明没有新日期或状态限制。 |
| T5 | ETF writer/独立维护回归 | 坏快照失败后旧 Raw/Serving 字面数据不变；独立 dataset action 仍失败。复用原 writer 的中途错误、对账失败回滚和正常重放测试，不改业务持久化逻辑。 |
| T6 | 目标工作流最小接入验证 | ETF 步骤连接真实 resolver/normalizer/writer，使用原 14 字段合同和真实异常字段的小样本；仅源下载及其他数据集业务边界使用替身。验证 writer 拒绝、原表保留、真实 dispatcher 继续、worker 写部分成功、节点/issue 可读。不能只用 mock 写入异常声称这一接入已验收。 |
| T7 | 复用手动入口、自动无日期默认值和正常工作流测试；补充源端修复样本 | 请求仍为无日期；全部 10 步成功则整任务成功；独立动作和其他工作流目录不变。源码 AST 差异须限定为 `replace` import 与目标步骤这一处表达式。 |
| T8 | 复用队列取消回归，增加 ETF 步骤取消场景 | 保留已提交数据，不开始后续源请求或写入；分别读回 TaskRun 和活动节点，记录既有取消局限，不使用伪造一致终态的替身。不能据此宣称生产取消已验收。 |

T2 是编排隔离测试，T4/T5 是业务校验和事务测试，T6 才覆盖这次错误穿过真实写入边界后由工作流继续的最小链路。它们均不是生产全市场完整性检查，也不要求所有 10 个源接口真实联网。

## 8. 实施文件及文档同步

| 文件 | 开发阶段允许修改内容 |
| --- | --- |
| `src/ops/action_catalog.py` | `replace` import、目标 ETF 步骤及简短注释 |
| `tests/test_ops_action_catalog.py` | 目标策略及其他步骤/工作流不变断言 |
| `tests/web/test_ops_runtime.py` | 目标失败继续、正常成功、其他步骤停止、最小接入和取消回归 |
| `tests/web/test_ops_catalog_api.py` | 目标步骤清单和 API 合同不变断言 |
| `tests/test_etf_basic_snapshot_writer.py` | 真实异常和正常待上市样本回归；复用原事务测试 |
| 本方案、LLD、工作流目录、`docs/README.md` | 记录开发/验证状态；未部署不能标为生产生效 |

最小接入测试若需复用 fixture，仅在现有测试文件内完成本任务隔离资源，不把测试需求变成产品代码或通用框架。现有脏工作区里的其他修改不得纳入本任务。

## 9. 开发前审计及证据（保留当时状态）

2026-11-25 开发前审计：范围、实现位置、真实失败分支、后续依赖及合同边界已核对，**可以进入后续本地开发；当时仍为待开发，未部署**。该阶段仅有文档编辑和本地只读/隔离验证，未执行源请求或 Prod 查询；方案 §2 的生产及源端证据复用本会话同日既有有界核查。

### 9.1 已运行的既有基线

使用 §6 的既有环境，临时根为 `/private/tmp/goldenshare-etf-basic-continue-design-20261125`：

```text
tests/test_ops_action_catalog.py::test_workflow_time_contracts_match_step_requirements
tests/web/test_daily_basic_limit_status_runtime.py::test_other_workflow_errors_keep_the_existing_partial_success_policy
tests/web/test_ops_runtime.py::test_scheduler_defaults_reference_data_refresh_workflow_to_snapshot_mode
tests/web/test_ops_manual_actions_api.py::test_ops_manual_action_task_run_supports_reference_data_refresh_workflow
tests/test_etf_basic_snapshot_writer.py
```

结果：`21 passed, 1 warning`。警告为既有 TestClient 依赖弃用提示，没有因此安装、升级依赖或过滤失败。

这些测试证明现有工作流顺序、通用失败策略、无日期入口、ETF 快照校验和原事务回归可以在当前环境通过。它们尚未证明目标 ETF 步骤已经配置为继续，也未覆盖 T6 的目标接入和 T8 的目标取消场景；这些是开发阶段验收条件，不提前标为已完成。

### 9.2 文档和开发约束审计

- 方案 R1–R7 均映射到明确代码位置或操作边界，测试 T1–T8 同时包含成功和失败反例；当前没有需要改变源合同、公共接口或工作流其余步骤的阻塞项。
- 原 ETF 方案/LLD 的完整快照、原表保护、身份选择规则保持，故不修改原数据集合同；本次工作流策略在原工作流目录明确登记为“已确认、尚未开发”。
- `python3 scripts/check_docs_integrity.py` 的绝对链接、目录噪音、Tushare 索引三组通过；改动文件的空白和新增链接另做核对。文档检查不证明运行行为。
- 本轮修改白名单为本方案、LLD、`docs/ops/ops-workflow-catalog-v1.md`、`docs/README.md`。索引中其他已有修改保留；产品代码和测试未修改，未提交 Git。
- 剩余验收边界：开发阶段完成 T1–T8；生产版本加载、实际任务执行及主数据更新情况只能在日后获准部署/执行后核验。现有取消节点终态、摘要文字和完整快照成本的限制均如实保留，不扩为本次重构。

## 10. 本轮实现、测试和完成后审计

2026-11-25，管理员在开发前审计通过后授权严格按方案开发；本节覆盖这次本地开发，取代文首原“待开发”状态。未提交或部署。

### 10.1 代码与范围

`src/ops/action_catalog.py` 按 §3 原样使用 `dataclasses.replace`，仅覆盖 `reference_data_refresh` 的 `etf_basic` 步骤。对整个文件执行 AST 对照，去除新增的 `replace` import 并还原这一处调用后，与本轮开发前完全一致。其他工作流、9 个其他步骤和所有参数均未变；没有修改 dispatcher、worker、DatasetDefinition、归一化、请求或 writer。

测试修改限于 §8 的 4 个测试文件；文档同步限于方案、LLD、工作流目录及索引。本任务写入均限于白名单。开发前文件指纹对照发现，期间白名单外另有并行文档变更；没有覆盖、纳入或提交这些变更，也不将其作为本次验收对象。

### 10.2 测试证据

使用 §6 的既有环境及 `/private/tmp/goldenshare-etf-basic-continue-20261125` 临时目录，无网络和生产资源。

- 修改业务代码前：目录目标策略、manual/scheduled/retry 错误继续、真实 writer 错误继续，共 5 个关键用例失败；失败点均为缺少覆盖策略或未到达后 3 步，能够抓住本次实际阻断。
- 修改后：同一批关键回归通过；本轮全部相关回归合计 `41 passed, 1 warning`。没有跳过失败或放宽业务断言。
- 测试初稿误把 `message` 放进结构化错误预期；核对 `ingestion_error_presentation.py::structured_error_payload` 后纠正：结构化 payload 固定六个字段，正文单独断言 `TaskRunIssue.technical_message`。未修改错误生产者或现行 API 合同。
- 警告仍为既有 TestClient 依赖弃用提示，没有安装或升级套件。

| 本轮执行范围 | 不重复用例数 |
| --- | ---: |
| `tests/test_ops_action_catalog.py::test_workflow_time_contracts_match_step_requirements` | 1 |
| `tests/web/test_ops_catalog_api.py::test_ops_catalog_returns_dataset_actions_for_admin` | 1 |
| `tests/web/test_ops_runtime.py` 中本次 16 个参数化场景及既有无日期调度、队列取消用例 | 18 |
| `tests/web/test_ops_manual_actions_api.py::test_ops_manual_action_task_run_supports_reference_data_refresh_workflow` | 1 |
| `tests/web/test_daily_basic_limit_status_runtime.py::test_other_workflow_errors_keep_the_existing_partial_success_policy` | 2 |
| `tests/test_etf_basic_snapshot_writer.py` 全文件，含新增异常/正常待上市样本 | 18 |

41 = 1 + 1 + 18 + 1 + 2 + 18。未运行整个仓库测试集；本轮范围不包含其他工作区改动的验收。

### 10.3 T1–T8 对账

| 验收项 | 本轮实现和实际结果 |
| --- | --- |
| T1：只覆盖一个步骤，其他定义/目录保持 | 字面 10 步及策略断言通过；API 步骤字段集合保持；完整业务文件 AST 对照通过。 |
| T2：目标错误继续，三类发起来源 | `test_reference_data_workflow_continues_after_etf_write_error` 三种 trigger_source 通过；真实 resolver、dispatcher、worker 和 Ops 表，业务执行使用替身；9 成功、1 失败、100% 进度及原错误六字段/正文均读回。该测试证明分发行为，不替代手动/调度/重提全入口生产验收。 |
| T3：其他步骤仍失败即停止 | `test_reference_data_workflow_other_errors_still_stop` 对其余 9 步分别注入错误，均在对应步骤停止，后继无节点。 |
| T4：真实坏样本与正常待上市样本 | `test_etf_basic_pending_source_sample_keeps_identity_validation` 两种后缀，通过真实 normalizer/writer；异常 `.SZ+SH` 拒绝，正常 `.SH+SH+P+空日期` 成功。原 L/D/.OF 回归继续通过。 |
| T5：原表保护、独立维护 | 新增 writer 用例逐字段读回旧 Raw/Serving；原事务中途错误、对账失败回滚、幂等重放通过；`test_etf_basic_standalone_still_fails_with_real_snapshot_error` 通过，独立任务真实终态仍为 failed。 |
| T6：最小接入 | `test_reference_data_workflow_real_etf_writer_boundary` 两种源样本均通过；ETF 使用真实 resolver、normalizer、writer、dispatcher、worker，仅源获取和其他数据集业务执行替代；错误后到达后 3 步，旧表保留，真实结构化错误可读；正常样本全部成功并真实写入隔离表。 |
| T7：无日期、正常成功、其他入口不变 | 既有手动提交和自动无日期任务生成通过；目标正常样本最终 10/10 成功；AST/目录验证和其他 workflow 原失败策略回归通过。重提仍为新任务、从头执行，本次未增加步骤续跑。 |
| T8：取消 | `test_reference_data_workflow_cancel_during_etf_stops_source_and_writes` 使用真实取消命令、真实取消读取和真实 worker；仅 ETF 源请求替身发出取消异常，前 6 步业务边界替代。后续真实源/写入接口未调用，旧 ETF 表保持；队列取消原回归也通过。实际节点局限见下文。 |

取消场景真实读回：TaskRun 为 `canceled`，前 6 个节点成功，ETF 基础信息节点失败；dispatcher 随后创建 ETF 跟踪指数节点，在该数据集进入执行前检查到取消并停止，节点也为失败。没有指数基础信息/港股基础信息节点，且没有 ETF 以后的源请求或业务写入。保留并记录这种任务与节点终态显示不一致的既有局限，不宣称已修复，也不据此改动通用执行逻辑。

### 10.4 完成后审计结论和未执行项

本地代码、T1–T8、R1–R7 及最小接入证据与本方案一致，未发现本次引入的阻塞问题。文档完整性、空白、新增链接和差异白名单检查完成；CodeGraph 用于目标定义、调用与影响面核验，具体边界见 §2；修改后已执行 `codegraph sync` 和 `codegraph status`，索引为最新。

本轮没有改源端记录、过滤异常行、降低校验、增加数据库/配置字段、恢复旧池或引入新依赖。没有真实源请求、Prod 查询、生产任务、Git 提交或部署。生产版本加载及正式更新情况仍需管理员安排部署/执行后核验；现有取消节点显示、摘要文字和完整快照成本限制保持 §4–§6 口径。

### 10.5 提交范围

开发完成并汇报后，管理员明确授权提交。提交范围仅为 §8 所列的 1 个业务代码文件、4 个测试文件、方案、LLD、工作流目录以及索引中的 ETF 两条记录，共 9 个文件。`docs/README.md` 中其他任务的索引修改不暂存、不带入；其他脏文件保留。提交前重新运行文档完整性与暂存区空白检查，代码和测试复用本轮最终 41 项通过的证据，不推送或部署。
