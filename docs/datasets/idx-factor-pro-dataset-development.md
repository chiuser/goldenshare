# 指数技术因子（专业版）维护说明

更新时间：2026-10-09。状态：§1–6 为现行实现说明及历史记录，已合并原接入方案与 LLD；§7 为历史覆盖基准修订方案与 LLD。用户已确认初始基准、要求提交方案并按计划推进；本轮先执行M0，各切片独立验收。代码及生产变更未实施，迁移、启用排程与补写生产数据仍按M4单独授权。

依据：[DatasetDefinition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/index_series.py)、[日期消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)、[执行计划与可靠执行](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)、[数据集模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)。源资料为 [Tushare doc 358](</Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0358_指数技术因子(专业版).md>)；§7 单独记录本次有限源端查询，不代表当前账户配额或生产验收。

## 1. 范围与使用入口

`idx_factor_pro.maintain` 维护 Tushare 按交易日返回的全量指数技术因子，不按指数激活池筛选。正式路径为：

```text
手动日期意图 / 自动探测命中
  -> Ops TaskRun -> DatasetActionResolver -> 每个开市日一个 unit
  -> Tushare 分页 -> 归一化 -> raw_tushare.idx_factor_pro
  -> core_serving.index_factor_pro 普通视图
```

- 手动维护支持单日或日期区间；无 `ts_code` 等业务筛选输入。
- 自动任务仅支持“探测触发”和“定时 + 探测兜底”，规则见 §4；不能把手动的 point/range 能力直接当作自动任务配置能力。
- Ops 展示在“A股指数行情”（`index_market_data`，排序 45）；底层 domain 仍为 `index_fund`。
- 不加入既有 workflow、不预置自动任务、不新增补漏链路、不接入 Dagster/Lake；`schedule_enabled=True` 不代表生产已存在或启用了 schedule。
- 不新增 Serving 物理副本，不引入股票复权因子门禁或专用历史重刷规划。股票因子差异见[股票技术面因子维护说明](/Users/congming/github/goldenshare/docs/datasets/stk-factor-pro-dataset-development.md)，不能套用旧“依赖股票对象池”的描述。

## 2. 输入、执行与日期观测

| 层次 | 当前口径 |
| --- | --- |
| 手动输入 | point 用 `trade_date`；range 用 `start_date/end_date`；`filters={}` |
| 日期模型 | `trade_open_day + every_open_day`；`point_or_range`；观测字段为 `trade_date` |
| 规划 | `generic`、`no_pool`；point 一日一个 unit，range 按交易日历展开开市日 |
| 源端请求 | builder 只生成 `trade_date=YYYYMMDD`；不透传区间、代码或 Ops 自定义分页参数 |
| 分页 | `offset_limit`，每页 8,000 行；不足一页结束，满页继续 |
| 观测 | freshness 为 `continuous_open_day`；完整性为 `date_bucket`，不做激活池代码矩阵审计 |

运营选择日期区间是维护意图，不是直接调用源接口的 `start_date/end_date`。例如一个含 23 个开市日的区间生成 23 个单日 unit，不按“指数代码数 × 日期数”扇出。

实现入口：[resolver](/Users/congming/github/goldenshare/src/foundation/ingestion/resolver.py)、[unit planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)、[request builders](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py) 的 `_idx_factor_pro_params()`、[source client](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py) 的 `fetch()/iter_pages()/_fetch_page()`。不能根据旧伪代码新增不存在的方法或错误类型。

日期桶有数据、最近业务日期较新，都不证明源站全部指数已齐备。本数据集不读取 `index_daily/index_daily_raw` 激活池或 DG 动态分区来限定请求、写入与预期代码集合；历史覆盖比较只用于解释这一设计。

## 3. 字段、存储与事务

字段唯一入口为 Definition 中的 `IDX_FACTOR_PRO_SOURCE_FIELDS` / `IDX_FACTOR_PRO_VALUE_FIELDS`。本次核对为 89 个源字段（2 个身份字段、87 个数值字段）；字段名、顺序和指标含义分别查 Definition 与 doc 358，不在本文再复制整张字段表。

| 对象 | 当前定义 |
| --- | --- |
| Raw | `raw_tushare.idx_factor_pro`，主键 `(ts_code, trade_date)`；身份列为 `VARCHAR(16)/DATE`，87 个数值列为可空 `Float(53)` |
| Raw 附加字段 | `api_name`、`fetched_at`、`raw_payload`；不进入源字段请求 |
| 索引 | 主键索引之外只有 `idx_raw_tushare_idx_factor_pro_trade_date`；不重复创建同序主键索引 |
| Serving | `core_serving.index_factor_pro` 普通视图：显式投影全部源字段，另加固定 `source=tushare` 与来自 `fetched_at` 的 `created_at/updated_at`；不暴露 Raw 的 `api_name/raw_payload` |
| 写入 | `raw_only_upsert`，按 Raw 主键幂等写入；结果的 `target_table` 仍指向 Serving 视图 |

[Raw ORM](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_idx_factor_pro.py)和[视图 ORM](/Users/congming/github/goldenshare/src/foundation/models/core/index_factor_pro.py)从 Definition 派生数值列；[迁移 20260801_000120](/Users/congming/github/goldenshare/alembic/versions/20260801_000120_add_idx_factor_pro_dataset.py)保留当时的显式字段定义。字段变更须同步核验 Definition、ORM、迁移与视图，不以文档字段数代替逐列对账。

[normalizer](/Users/congming/github/goldenshare/src/foundation/ingestion/normalizer.py)转换交易日期与数值；缺少 `ts_code/trade_date` 会记录 reject，无独立行转换或激活池过滤。[writer](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)会取得 Raw 和 Serving DAO 元数据，但本写入分支只调用 Raw upsert；不能因 Serving 不参与写入就删除它的 DAO、ORM 或观测映射。

“维护流程不写视图”不等于“数据库强制拒绝所有视图 DML”。现有迁移与 writer 护栏测试不能证明后一项；本轮不新增数据库权限或拒写机制。

每个交易日的分页结果先汇集、归一化，再按 `commit_policy=unit` 写入提交。已提交日期与未提交日期分开；Ops 状态写失败不得回滚业务数据。内存随单日结果增长，并非仅一页大小；分页上限也不是每日总量上限。`max_units_per_execution=None` 不构成历史区间容量保证。幂等 upsert 不等于已证明进程退出后可靠续跑；长范围任务仍按[执行计划的事务与恢复约束](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)和模板 §0.3.5 单独验证，本轮不扩展代码改造。

## 4. 自动任务与源站探测

条件为 `remote_idx_factor_pro_ready`，展示为“源站已有指数技术因子”。它只判断源站是否**开始返回当天开市日数据**，不验证全量指数齐备。

### 配置与职责

- [ScheduleAutomationCapabilityResolver](/Users/congming/github/goldenshare/src/ops/services/schedule_automation_capability_resolver.py)统一声明、校验该动作的自动化能力：仅 `probe/schedule_probe_fallback`，禁止固定日期、日期区间、`calendar_policy` 和非空 filters；最小探测间隔 300 秒，每条规则每日触发上限固定为 1。
- [ScheduleProbeBindingService](/Users/congming/github/goldenshare/src/ops/services/schedule_probe_binding_service.py)将通过校验的自动任务意图持久化为 ProbeRule；不另维护一套该数据集专用配置校验。
- [自动任务页面](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-auto-tab.tsx)消费 action 返回的 `automation_capability`，不靠新增数据集页面分支决定条件和禁填字段。该动作不提供本地 `freshness_latest_open` 条件。
- 运营配置窗口和频率；不凭印象写死源站发布时间。纯 probe 与带兜底执行时间是两种触发方式，不是单日/区间两种维护输入。

### 运行链路

1. [ProbeRuntimeService](/Users/congming/github/goldenshare/src/ops/services/operations_probe_runtime_service.py)检查规则窗口、间隔及每日触发上限，再调用[专用探测服务](/Users/congming/github/goldenshare/src/ops/services/idx_factor_pro_remote_probe_service.py)。
2. 服务按 `Asia/Shanghai` 当前自然日查询交易日历；日历缺失或当天不开市，零次源请求并返回 miss，不回退为上一开市日。
3. 以当天日期和空 filters 构造 point 意图，经 resolver 生成唯一 unit；只在探测调用中追加 `fields=(ts_code,trade_date), limit=1, offset=0`。
4. 第一行的日期匹配当天且代码非空才命中；空结果、错日期、缺字段为 miss，源异常由 runtime 记录 error，不创建任务。
5. 命中后按去重规则创建标准单日 TaskRun，`trigger_source=probe`、`filters={}`；全部字段的正式分页、清洗与写入仍由 ingestion 执行。Probe payload 进入日志，不代替业务写入或 freshness/snapshot 刷新。

去重不是全系统“同日只能同步一次”：runtime 核验同 schedule、同目标日的有效 probe TaskRun，规则重建也不能绕过这一判断；[schedule 执行服务](/Users/congming/github/goldenshare/src/ops/services/operations_schedule_service.py)在兜底到期时检查同日有效 probe 任务，避免重复创建。不得把每条规则的上限理解为跨手动任务、跨 schedule 的全局互斥。

不采用五个固定指数逐只探测：该方案虽然做过历史可行性试验，但会要求绕过或扩展当前不允许 `ts_code` 的输入合同。探测参数不能写回 Definition、TaskRun 维护参数或隐藏运营字段。

## 5. 性能与验证入口

在无重试、单次扫描期间源端结果稳定且 offset 分页如约返回的前提下，单日 N 行的请求数为 `floor(N/8000)+1`；整页结尾还要请求空页确认结束。区间按各日求和，重试与独立 probe 请求另计。不能用单日样本推断所有历史日期的规模或耗时。

doc 358 的本地资料记载积分档位为 5000 积分 30 次/分钟、8000 积分以上 500 次/分钟；这不是本轮对当前账户权限、剩余配额或实际吞吐的核验。禁止把单日全量改成逐代码扇出，也不能把无日期单指数的一次返回当作完整历史。

| 核验点 | 现有入口 |
| --- | --- |
| Definition、日期 unit、非法 filters | [registry 测试](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py) |
| 89 字段透传、满页续拉、日期与数值转换、身份缺失 | [source client 测试](/Users/congming/github/goldenshare/tests/test_dataset_source_client.py)、[normalizer 测试](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py) |
| Raw-only、模型字段与迁移视图 | [writer 测试](/Users/congming/github/goldenshare/tests/test_dataset_writer_idx_factor_pro.py)、[模型合同测试](/Users/congming/github/goldenshare/tests/test_idx_factor_pro_model.py) |
| 自动能力、探测、绑定与兜底 | [capability 测试](/Users/congming/github/goldenshare/tests/test_ops_automation_capability.py)、[probe 测试](/Users/congming/github/goldenshare/tests/web/test_ops_probe_api.py)、[schedule API 测试](/Users/congming/github/goldenshare/tests/web/test_ops_schedule_api.py) |
| 展示与观测消费者 | [catalog 分组](/Users/congming/github/goldenshare/src/ops/catalog/dataset_catalog_views.py)、[Definition 投影](/Users/congming/github/goldenshare/src/ops/dataset_definition_projection.py)、[freshness 策略](/Users/congming/github/goldenshare/src/foundation/datasets/freshness_policies.py)、[观测注册](/Users/congming/github/goldenshare/src/ops/dataset_observation_registry.py)、[日期完整性服务](/Users/congming/github/goldenshare/src/ops/services/date_completeness_audit_service.py) |
| 不加入既有工作流 | [workflow 目录实现](/Users/congming/github/goldenshare/src/ops/action_catalog.py)、[action catalog 测试](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py) |

这些入口不表示本轮全量运行了 Web/API 或生产测试。后续若获准做真实验收，应核对源端读取、归一化、去重/reject、实际写入与目标日期数据；解释每类差异，核对 Raw/view 的身份、字段、行数及 Ops 观测。upsert 行数不能直接当新增行数，也不能无条件要求重跑写入量等于既有整日总量。

若分页失效、字段集合漂移，或需要隐藏参数/对象池才能实现新的就绪含义，应停下重新评审；不得在本文合并中更改现行合同。新迁移必须接届时真实 head，不能沿用历史 revision 的“当前 head”称谓。

## 6. 历史证据与验收边界

### 2026-08-01 接入与源端实测

以下为原两份文档保留的历史记录，不是 2026-09-10 重新查询结果：

- 接入前：候选业务表、字段、相关 TaskRun、状态快照查询均为 0，当时尚无本数据集代码。
- 同日完成 M1–M5 本地实现；M1 定向测试 210 项、M5 定向回归 399 项，以及当时的 lint、前端与文档检查通过。
- 当时 migration head 为 `20260801_000120`（父 revision `20260625_000119`）；记录时尚未执行生产迁移和真实单日同步。该状态只属于当时。

| 当时请求 | 历史结果 |
| --- | --- |
| 不传业务参数 / 只传日期区间 | 返回 `50101`，要求至少有 `ts_code` 或 `trade_date` |
| `trade_date=20260731`，两个身份字段 | 3,146 行、3,146 个代码 |
| 上述请求分别加 `limit=1, offset=0/1` | 分别返回 `000094.SH/000096.SH`，证明当时 offset 生效；MCP 公开 schema 虽未列分页参数，实际调用接受 |
| 仅 `ts_code=000001.SH` | 返回恰好 8,000 行，日期 `19930908..20260731`；单次结果不能证明完整历史 |
| 同代码加 `20260701..20260731` 区间 | 返回 23 行；显式请求全部 89 个字段时每行字段齐全 |

当时五个代码 `000001.SH/399001.SZ/399300.SZ/000016.SH/000905.SH` 分别加目标日及 `limit=1,offset=0` 都命中；只证明精确请求可行，不代表采用了固定代码探测，也不证明全部指数发布完成。

### 当时的覆盖比较与后续运行记录

| 2026-08-01 比较的集合 | 代码数 | 与 2026-07-31 因子集合重合 |
| --- | ---: | ---: |
| `index_daily` 服务激活池 | 1,216 | 1,212，缺 4 |
| `index_daily_raw` 请求池 | 3,052 | 2,049，缺 1,003 |
| 当日因子集合 | 3,146 | 其中 1,934 不在服务激活池 |
| DG `cn_a_index_ts_codes` 动态分区 | 820 | 820 |

服务激活池当日缺失代码为 `480055.CNI/480056.CNI/480057.CNI/931598.CSI`。这些结果解释为什么不把其他链路对象池作为本数据集过滤器；单日缺失不证明永久不可用，DG 比较不构成运行依赖。

后续[业绩快报专项 M3 生产记录](/Users/congming/github/goldenshare/docs/datasets/equity-express-low-level-design-v1.md#206-m3-生产验收记录)记载 `idx_factor_pro TaskRun#7924` 成功。因此不能继续以“生产同步从未执行”描述当前状态。但该旁证不包含本数据集源端—Raw—view 全量对账，不能替代其完整发布验收。

2026-09-10 文档合并时仅核对仓库代码、测试和历史记录，未查询当时生产 revision、数据、schedule 或源端接口；该轮不宣称生产验收已结案。旧文档全文可从 Git 提交 `a0df5e1a` 追溯。

<a id="source-coverage-revision-20261009"></a>

## 7. 历史覆盖基准修订方案与 LLD（2026-10-09，按计划推进M0，代码及生产未实施）

### 7.1 原方案定位、问题与修订范围

原接入方案就是本文的原路径；原 LLD 为 `docs/datasets/idx-factor-pro-low-level-design-v1.md`，已在提交 `8bc1fb44` 合并后删除，去向见[2026-09-10 整合记录](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md#idx-factor-docs-consolidation-20260910)。新增 probe 的提交为 `9a851ede`，其中原方案 §12、原 LLD §7.4 明确确认了“一条当天记录即命中”和“每日最多触发一次”。原文还明确不新增代码级完整性判断。这不是当前实现偏离原方案，而是原就绪定义不足以处理分批发布；本节提出修订该定义，不把原决策改写为历史错误实现。

当前实现与待修订行为对账：

| 环节 | 当前代码事实 | 本节目标 |
| --- | --- | --- |
| Probe | `IdxFactorProRemoteReadinessProbeService.evaluate()` 请求两个身份字段及 `limit=1`；一条有效记录即命中 | 完整扫描当天身份集合，覆盖基准并通过稳定性检查才命中 |
| 正式拉取 | `DatasetSourceClient._iter_request_pages()` 遇短页结束；未判断源端日内发布是否完成 | 保留分页，增加拉取结果的覆盖门禁，不能把短页当发布完成 |
| 写入 | `raw_only_upsert` 当前未调用覆盖校验；Definition 仅 `record_rejections` | 写入前核对覆盖、日期、去重与拒绝；不完整日期零次业务写入 |
| 限次 | `_should_probe()` 统计 `condition_matched=True` 日志，固定上限 1 | 区分探测、执行尝试、验证成功；不完整或失败不能封死后续尝试 |
| 去重与兜底 | Probe 与 schedule 将 `success/partial_success` 等状态视为有效任务 | 活动任务防并发；停止当日更新必须以业务覆盖验证证据为准 |
| 日期观测 | `date_bucket` 与最近业务日期不证明代码覆盖完整 | 保留原日期新鲜度语义，另报告覆盖校验结论，不能相互替代 |

只修订 Prod `idx_factor_pro` 这一条链。继续使用全市场按交易日请求、空 filters、既有 TaskRun 和一日一个 unit，不增加激活池、逐代码请求、Serving 物理副本或 DG/Lake 依赖。`remote_idx_factor_pro_ready` 的 key 保留，但其就绪语义、展示文案、限次与去重行为需要统一迁移；开发前须批准这些合同变更。手动和定时兜底也必须经过相同的正式写入门禁，不能成为绕过入口。

### 7.2 已有证据及“完整”的能力边界

2026-10-09 本次讨论期间，通过 `tushareMcp.idx_factor_pro` 分别请求 `trade_date=20260930/20261008`、`fields=[ts_code,trade_date]`：两日均为3,388行、3,388个不同代码，日期全部匹配，两个代码集合相同。用户已确认选用2026-10-08集合为初始历史覆盖基准，2026-09-30用于交叉比对。没有查询Prod数据、排程或当天发布进程；没有在这两次请求中验证完整89字段及分页参数。该选择批准的是**历史覆盖参照**，不是源端全量清单、生产对账或发布终态证明。

历史 §6 曾记录 2026-07-31 为 3,146 个代码，本次样本为 3,388 个，已经说明不能将总数当永久常量。

读取的本地源资料和这两次结果没有提供发布结束标志、权威当日代码清单或源端版本号。只依赖数量及连续两次稳定，无法严格区分“合法减少”和“源端长时间只发布了一部分”；也无法证明尚未见过的新代码都已经出现。本节默认定义为**已覆盖用户选定的历史观测集合，且当前源端身份集合稳定**。页面与报告应写“通过历史覆盖基准校验”，不能承诺“源端已确认全部发布”。若必须获得严格的当日全量保证，须先取得并验证源方发布凭证或权威当日覆盖清单；在取得前不伪造此保证。

### 7.3 动态基准：保存集合与版本，总数由集合推导

令 `B(D)` 为适用于目标日 D 的已确认预期代码集合，`C(D,t)` 为时刻 t 完整分页扫描所得的当日唯一代码集合：

```text
预期数量 = |B(D)|                 当前数量 = |C(D,t)|
缺失集合 = B(D) - C(D,t)          新增集合 = C(D,t) - B(D)
覆盖率   = |B(D) ∩ C(D,t)| / |B(D)|
```

覆盖率用于解释结果，**不允许以 95%、99% 等阈值放过缺失代码**。3,388 只作为当前样本数量，不放进页面常量、env、Settings 或永久 minimum count。代码集合按非空 `ts_code` 原值去重、排序后生成 SHA-256 指纹；不截掉后缀、不替换代码别名；指纹不含日期，比较时必须同时校验目标日、来源和基准版本。

| 当日情况 | 判断与处理 | 是否改变基准 |
| --- | --- | --- |
| 只有100多条，或缺任意预期代码 | 未齐备，继续探测；缺失明细可解释 | 否，不能向下学习 |
| 数量相同但有旧代码缺失、新代码出现 | 集合替换待核实，不能按数量放行 | 否，需代码变更证据 |
| 集合与基准相同且稳定 | 可以进入正式拉取与再次校验 | 保留原版本 |
| 包含基准全部代码，同时出现新增代码 | 稳定后允许拉取全部返回；新代码同样入库 | 完成正式校验与提交后，生成扩容版本 |
| 真实停编、改码或覆盖范围收缩 | 依据源方证据确认具体代码与生效日，形成新版本，再重新判断当天集合 | 经运营确认后减少或替换，不自动缩减 |
| 基准缺失、损坏或目标日在基准生效日之前 | 明确阻塞，不能退回一条即命中 | 先建立适用基准 |

例如由3,388增加到3,400：新增12个、缺失0个，集合稳定且正式拉取对账通过后自动扩容。由3,388变成3,380：即使连续多轮返回相同3,380个，也不能直接删掉预期的8个；有停编证据才按生效日建立缩容版本。由3,388变成另一个3,388：仍须解释缺失和新增代码，数量相等不代表齐备。

初始基准V1已选定为2026-10-08源端返回的3,388个不同代码，源端原始身份样本的代码集合已固化为[基准证据JSON](/Users/congming/github/goldenshare/docs/datasets/evidence/idx-factor-pro-coverage-baseline-20261008.json)。集合指纹为 `a97cb74f3fb09854158c99507f983eb4cadae524fde73248a69a925b10107295`；计算方式为排序去重后，以UTF-8紧凑JSON数组编码，再取SHA-256。初始适用日期从2026-10-08起；更早日期须另有适用基准。

用户选择已经确认，不再将V1描述为等待选型的候选，也不把人工确认当源端全量证明。生产导入前仍须复查身份、分页、Prod Raw/view及reject差异；若重新查询的集合与固化指纹不同，报告新增/缺失，不静默替换V1。禁止拿“Prod最新有数据日期”、单次成功TaskRun或两个相同的小集合自动初始化。源日期、采集日期、代码集合、指纹及本次用户确认依据都要保存；当前JSON仅保存身份集合证据，没有89个因子字段。

基准按版本追加，保存生效日期及父版本；不能覆盖历史版本。同一生效日有多个版本时按追加顺序取最新已确认版本；扩容版本从已验证目标日生效，缩容/改码版本从源方证据与运营确认的生效日生效。历史维护须取当日适用版本，不能用今天3,388个去否决过去真实3,146个的历史日。缺少历史版本时先补历史证据，不提供绕过校验的隐藏开关。

### 7.4 基准与业务验证证据的持久化设计

目前 `idx_factor_pro` 没有上述覆盖基准和逐日验证证据。不能复用 `ops.dataset_status_snapshot` 的日期/行数作为“已验证”事实，Foundation 也不能反向读取 Ops 日志或 TaskRun 作为业务门禁。拟由 Foundation 持有三类持久化记录，仅服务本数据集；这是新设计，物理 schema、表名、ORM/DAO、唯一键及 Alembic DDL 须在开发前完成审计并落回本节，不能现在声称已存在。

| 逻辑记录 | 必须保存的内容 | 持久化和职责 |
| --- | --- | --- |
| 覆盖基准版本 | dataset/source、版本、父版本、生效日、完整代码集合、集合指纹、数量、依据日期、变更类型、证据、确认人与确认时间 | Foundation 管理已确认集合；新增版本不可就地覆盖，不能从失败/未齐备结果生成 |
| 源端扫描证据 | 扫描ID、dataset/source/目标日、基准及规则版本、采集时间、完整分页是否结束、代码集合与指纹、页数/行数、缺失/新增、失败原因 | Foundation的有界扫描独立保存源观察；未齐备也可记录，但不得当已验证基准或业务发布证据；按扫描ID追加、可读回 |
| 已验证日期证据 | dataset/source/目标日、使用的基准版本、源端代码集合和指纹、源行数、唯一数、归一化数、重复与 reject、实际目标集合与数量、验证时间、验证规则版本 | 与当日业务发布一起形成可读回事实；幂等键为 dataset/source/目标日，重新验证保留版本追溯 |

正式 unit 在短事务中锁定/核验适用基准版本，完成业务 upsert、目标集合读回及验证证据提交；需要扩容时同一发布边界记录新版本，避免业务已发布但基准被另一任务错误缩小。并发版本冲突不得覆盖，重新读取后判断。基准与逐日证据是门禁所需的业务校验事实，**不是另一套 TaskRun 状态机或 Ops 成功状态**。

Probe、手动和兜底调用同一Foundation有界扫描能力；两次稳定确认读取Foundation源端扫描证据，`ProbeRunLog`只保存引用及运营摘要。这样正式门禁无需读取Ops日志或在TaskRun意图里夹带代码集合。扫描证据独立提交，不与后续业务发布混成一笔跨网络的长事务；保存扫描不修改Raw/view、基准或已验证日期。原方案“probe只写Ops日志”的范围也需要随之修订，不保留Ops与Foundation两份就绪算法。

日志与TaskRun状态写入独立；其写失败不回滚已提交Raw、验证证据或扩容版本。源端扫描证据保存失败时本轮不能提供确认依据，尚未执行业务写入；缺失证据只能重新扫描，不允许降级放行。这些记录是源观察事实，不是持久化的另一套任务生命周期。

### 7.5 Probe、正式拉取与失败后的执行流程

1. **判定目标日。** 保留当日开市日语义及当前日历校验；日历缺失或不开市时零次源请求。选择有效基准，缺失则报告阻塞。
2. **扫描身份集合。** 仍经 resolver/builder 生成 `trade_date`，源端只请求两个身份字段，但改为按 Definition 的8,000页大小完整分页。校验所有行的日期、代码及分页终止；出现跨日期、空身份、重复代码或预算超限，不积累稳定观察、不创建任务。不使用第一条或抽样指数代表全部覆盖。
3. **判定覆盖及稳定。** 默认至少两轮相邻有效扫描，间隔不小于现有300秒；同目标日、同来源、同基准版本、集合指纹相同且缺失0个才通过。最近扫描距当前时间不得超过两倍实际确认间隔；确认间隔取现有probe间隔，手动/无probe兜底取300秒。中间出现错误、未齐备、基准切换或窗口结束，要重新积累。不能把多轮部分集合求并集当一次完整结果。
4. **入队。** 没有同 dataset/source/目标日的活动任务，且当天尚无满足最新覆盖要求的业务验证证据时，创建标准单日TaskRun。TaskRun仍只保存日期等维护意图；不把源端扫描当已发布业务数据，不把基准集合塞入运营filters或绕过resolver。正式执行从Foundation证据锁定适用基准及确认扫描ID。
5. **正式再次取数。** 正式请求全部89个字段并完整分页。通过 Foundation 的同一覆盖规则，且正式集合与最近通过稳定检查的集合一致；probe到执行期间集合变化则重新等待。对所有行核对日期/身份、重复和 reject；允许文档规定的可空数值，不能要求所有技术指标非空。
6. **写入前门禁。** 自动、兜底、手动、retry均经过同一规则。先检查Foundation是否有仍有效的两次确认；没有时，本次只做一次有界身份扫描并保存证据，确认仍不足就以“源端覆盖确认中”及可重试reason结束该次TaskRun，不在worker里等待300秒，也不获取/写入完整因子。手动由运营在提示时间后retry；自动/兜底由已配置probe在下一间隔继续，无probe规则的兜底不擅自创建新排程。确认通过后才正式拉取及upsert；任何reject、分页不完整或覆盖失败都不触碰目标日期业务行。普通视图会直接暴露已提交Raw，不能先写100条再靠后置审计补救。
7. **读回与提交。** 同事务核对当日目标主键集合与正式源端集合一致，保存逐日验证证据；业务提交后才更新 TaskRun及观测。若已有目标代码不在本次源端集合，先报告差异并阻塞，不擅自删行；清理或更正必须另有逐项授权。
8. **后续复核。** 在原探测窗口内，即使已有当日验证证据，也继续按间隔做身份扫描。集合未变则不重复下载因子；新增代码或替换/缺失则按上述规则处理。因此当天后续扩批不会被一次成功永久遮住。源端仅改数值而身份不变的修订识别不在本节范围。
9. **窗口结束。** 仍有缺口或变更待确认时，保留缺口、最后扫描时间及证据，报告“窗口结束，覆盖未通过”，不写成功。现行probe仅检查当天，本节不暗中加入跨日补漏；后续由已授权的手动维护/retry处理，不把次日错当目标日。

稳定确认不采用工作进程内 `sleep` 等待：每次probe只执行一次有界扫描，下一轮由现有间隔驱动。进程重启从持久化源端扫描证据重新判断；不能依赖内存计数器。正式写入前还须核验所用基准和扫描未被后续失败/集合变化作废，变化则退出本次尝试，不持锁等待源端。

### 7.6 限次、去重、兜底与运营展示

旧D4的“每日最多触发一次”必须修订。继续把 `max_triggers_per_day=1` 当命中日志上限，会同时挡住失败重试和当天后续新增代码；不能只改probe请求而保留这一阻塞。修改计划保留字段名，以“同schedule、同目标日实际创建的自动TaskRun次数”为计数口径，仅本条件固定值由1改为3；统计同排程的probe及scheduled兜底任务，包括失败和取消，不统计miss或重复命中日志。API、持久化规则及页面统一显示“每日自动执行上限3次”，其他数据集保持现行口径。按目标日和候选集合防重复，窗口限制尝试；不得在页面仍表示每日一次、runtime却偷偷改语义。

| 情况 | 是否允许后续扫描/执行 |
| --- | --- |
| miss、未齐备、源异常或稳定确认不足 | 下一间隔继续扫描；不计为业务完成；如果已经创建TaskRun，该次仍计入正式尝试预算 |
| queued/running/canceling 的相同目标任务 | 可记录源端观察，不创建并发执行；跨schedule也须防重复 |
| 覆盖失败、执行失败或 partial_success | 已提交的其他日期保留；目标日无验证证据则仍可重试，不能仅凭状态封锁 |
| 业务已提交但 Ops 状态写失败 | 读取 Foundation 验证证据判断；相同集合不重复写，修复观测独立进行 |
| 已验证且集合未变 | 继续轻量复核，不创建同集合任务 |
| 已验证后出现稳定扩容集合 | 允许同日再次完整拉取及幂等upsert，追加覆盖版本与日期证据 |

每个自动任务、目标日拟限定最多3次正式执行尝试，probe扫描不占此额度；失败尝试也计入，规则重建不能清零。3次是待评审默认预算，不是源端事实。窗口、现有探测间隔及该预算共同约束重试；达到预算报告“需人工处理”，不得无限重跑。用户取消的任务不由自动流程重新拉起；需运营明确恢复。定时兜底只能启动同等确认流程，不能因到点直接绕过覆盖门禁；有活动任务或同集合验证证据时跳过。

运营展示统一使用后端事实：当前唯一代码数、基准数量/版本、缺失及新增数量、稳定确认次数、最后观察时间、下次检查时间、正式尝试次数和原因。例：“源端132个，预期3388个，尚缺3256个，继续等待”；新增示例为“源端3400个，预期3388个，新增12个，确认中”。基准数量从版本记录推导，页面不计算完整性。

修改 `automation_capability` 文案为“源端覆盖校验通过后更新”，probe日志给出结构化reason及计数，TaskRun详情报告正式门禁结果。现行freshness仍表示日期新鲜度；覆盖待确认时必须显式呈现，不能借 `MAX(trade_date)`、桶存在或旧 `success` 文案声称已全量完成。需要新增API/卡片字段时，须先审计合同并迁移全部消费者；禁止页面额外拼表。

### 7.7 策略值、配置来源与性能门禁

下表是拟实施配置/策略审计，全部为待评审口径。算法语义声明在 Foundation DatasetDefinition/相应策略模型，Ops从中投影；运行预算由统一自动化能力解析并落入Ops排程，不散落为脚本或页面常量。新增模型字段前要完成消费者审计；本轮不添加配置项或修改模板合同。

| 项目 | 拟默认值 | 来源与持久化 / 消费者 / 生效与可见性 |
| --- | --- | --- |
| 每日固定预期数 | 不设置 | 仅从有效基准代码集合推导；Foundation校验、Ops日志/详情同读一个版本 |
| 基准扩容/缩容策略 | 无缺失且稳定可扩容；缩容/替换需证据及运营确认 | Foundation策略及版本记录；生效日控制，不用env/Settings改覆盖事实 |
| 稳定确认轮数 | 2 | 拟Definition覆盖策略；Probe和正式门禁共用，Ops展示计数；重启不得跳过 |
| 扫描证据有效期 | 最近扫描不早于当前时间减两倍确认间隔 | 从实际间隔推导，手动/无probe取300秒；Foundation确认及正式门禁共用，过期重新确认，不另设env |
| 探测间隔/窗口 | 最小300秒；沿用运营配置窗口 | 现有capability/binding、OpsSchedule/ProbeRule；编辑后的规则按新版本重新确认，不写死源站发布时间 |
| 正式尝试预算 | 每自动任务、目标日3次 | 拟统一capability、Ops持久化意图及TaskRun尝试记录；日志/详情可见，不能因重建ProbeRule绕过 |
| 源端页大小 | 8,000 | 现有Definition planning；身份与正式拉取复用，不暴露为运营筛选参数 |
| 单日扫描预算 | 拟最多16,000行、3次源请求、60秒；单调用20秒 | 拟Foundation有界取数策略；8,000整页终止需要额外空页，3次容纳16,000行；超限阻塞，先重新评估预算 |
| 内存/响应预算 | 拟单unit响应累计16 MiB、工作内存128 MiB | 待实测校准并实现硬限制；身份扫描和89字段取数分别测量，不能仅靠行数宣称已限制内存 |

运行预算只能影响是否等待/阻塞，不能改变已确认代码范围。3,388行时单轮身份扫描通常1次请求，一次完整发布至少经历两次确认和一次正式取数，通常3次请求；16,000行且终端空页时每次扫描3次，同样三个阶段共9次请求。这是跨确认间隔的总量，不是在一个60秒尝试中等待两次确认。单次probe最多一次身份扫描；单次TaskRun缺少证据时最多做一次身份扫描，已有有效证据时才做一次正式扫描。窗口内持续probe的请求另计，为 `扫描轮数 × 每轮页数`，多个schedule及其他数据集共享配额，不能用平均每分钟请求数证明瞬时安全。正式门禁复用仍有效的Foundation两次确认，避免无意义重复扫描；每一次真实调用均纳入预算。

网络超时须可安全中断，不能把线程等待超时等同于底层调用取消。当前 `DatasetSourceClient` 的通用65秒限流等待不能直接证明上述有界扫描要求已满足；开发前核对现有有界source调用能力，采用分页前后取消检查，源异常退出本轮，由下一probe间隔重试。超预算或缺少可安全中断能力时停止开发，不擅自安装依赖或引入另一执行入口。

等待源发布不占用长驻执行TaskRun。一旦正式维护可能超过60秒、批量历史范围无法静态约束或这些预算无法兑现，必须先完整填写[模板 §0.3.5](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)：一日unit、批次和内存、业务提交与幂等键、持久化续跑依据、30秒内可见进度、取消检查点、事务及TaskRun/节点终态、最小真实运行—取消—续跑—读回验收。不能用本节预算建议替代该门禁，也不在本次修复中默认扩大历史任务执行规模。

### 7.8 代码落点、合同消费者与边界

本次先用 CodeGraph `codegraph_search/codegraph_impact` 定位专用probe及其runtime、关联probe测试；上一轮 `codegraph_explore` 查询覆盖source client，但存在宽泛匹配，故实际设计继续逐项核对当前源码、原方案和测试。影响图不是全量合同审计，尤其不能代替动态调用、snapshot和前端投影核验。

| 拟改动区域 | 真实入口和实施注意点 |
| --- | --- |
| DatasetDefinition与策略 | [index_series.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/index_series.py)、[models.py](/Users/congming/github/goldenshare/src/foundation/datasets/models.py)；复用现有 `quality.pre_write_validator_key` 等能力前审计语义，新增覆盖策略需同步模型、投影、模板和消费者 |
| 取数与门禁 | [source_client.py](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)、[pre_write_validators.py](/Users/congming/github/goldenshare/src/foundation/ingestion/pre_write_validators.py)、[writer.py](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)、[executor.py](/Users/congming/github/goldenshare/src/foundation/ingestion/executor.py)；当前raw-only分支没有覆盖validator调用，不能只填一个validator key就宣称接通；reject从记录改为整unit拒写需同步测试 |
| 覆盖事实存储 | Foundation的版本记录、源端扫描及逐日验证证据和查询；新DDL必须先查真实Alembic head，不恢复历史LLD中的过时head；不在迁移中seed或开启排程 |
| Probe与去重 | [专用probe](/Users/congming/github/goldenshare/src/ops/services/idx_factor_pro_remote_probe_service.py)、[runtime](/Users/congming/github/goldenshare/src/ops/services/operations_probe_runtime_service.py)；只本数据集改变限次/去重口径，其他条件回归保持 |
| 能力、绑定和兜底 | [capability resolver](/Users/congming/github/goldenshare/src/ops/services/schedule_automation_capability_resolver.py)、[binding](/Users/congming/github/goldenshare/src/ops/services/schedule_probe_binding_service.py)、[schedule service](/Users/congming/github/goldenshare/src/ops/services/operations_schedule_service.py)；旧每日1次、状态去重与兜底跳过均需迁移，不能只改一处 |
| 日期观测与消费者 | [freshness query](/Users/congming/github/goldenshare/src/ops/queries/freshness_query_service.py)、[snapshot service](/Users/congming/github/goldenshare/src/ops/services/operations_dataset_status_snapshot_service.py)、[date audit](/Users/congming/github/goldenshare/src/ops/services/date_completeness_audit_service.py)、[registry](/Users/congming/github/goldenshare/src/ops/dataset_observation_registry.py)；日期与覆盖两种结论分别报告，历史未验日期不能自动标绿 |
| 自动任务页面及API | [自动任务页面](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-auto-tab.tsx)、关联schedule/probe/TaskRun schema与测试；统一删除旧每日一次及一条即命中文案，不留双轨条件 |

开发前全量消费者清单至少覆盖manual actions、catalog、workflow、resolver/unit planner、request builder、freshness、dataset cards、snapshot rebuild、日期完整性审计、自动任务日期策略、前端时间控件及相关测试/文档；须记录读取的字段、所需迁移及正反例。没有完成时不把上表称为已经完成的全量审计。

依赖方向不变：Foundation只依赖自身，Ops消费Foundation的覆盖判定/证据，App负责装配。§7.10指定拟新增表与模块、限次迁移及实施切片；详细DDL、覆盖结果API字段与有界调用的专项化仍需在编码前完成合同审计，不允许通过隐藏开关、兼容分支或旁路脚本绕过。

### 7.9 验收矩阵与生产启用顺序

| 验收项 | 必须证明的正向与负向结果 |
| --- | --- |
| 分批发布 | `0 → 132 → 3,000 → 3,388 → 3,388`；前四轮不入队/不写业务，第五轮才有两次稳定确认；相同132连续多轮仍不放行 |
| 数量漂移 | 3,388到3,400无缺失可扩容；3,388到3,380无证据阻塞；相同数量替换代码也阻塞；版本与生效日可读回 |
| 历史日期 | 旧3,146集合使用当日适用版本；没有历史版本时阻塞；今天的扩容不回写旧日期基准 |
| 非法返回与分页 | 错日期、空身份、重复键、满页后的漏页、超行数/页数/字节/时间预算均拒绝；8,000及16,000整页尾需要空页确认；小样本不被错当全量 |
| Probe到正式请求变化 | Probe覆盖后正式只返回100条、出现新增/缺失、产生reject或缺少源字段时零业务写入，不保存已验证证据、不降低基准 |
| 手动与兜底 | 均不能绕过同等确认与写入门禁；无证据时单次扫描后可重试终态，不持有worker等300秒；过期证据不得使用；已有活动任务防并发；旧partial_success无证据不能阻止修复 |
| 发布及重放 | 源集合、归一化集合、Raw及view集合一致；同日重放无重复；目标已有额外代码时明确阻塞，不自行删行 |
| 失败与取消 | 日志匹配不等于完成；失败可在窗口和3次预算内重试；取消不自动拉起；超预算停止；TaskRun及活动节点终态一致 |
| 重启和状态写失败 | 稳定观察可重建；基准版本不回退；业务提交证据可读回，Ops失败不回滚、不造成重复发布；并发基准变更不能互相覆盖 |
| 后续扩批与观测 | 当日已验证后仍发现稳定新增并补齐；集合不变不重复下载；日期最新但覆盖未知不显示全量完成；页面计数和文案来自后端 |

测试扩展优先落在现有 `tests/web/test_ops_probe_api.py`、`tests/web/test_ops_schedule_api.py`、`tests/test_dataset_source_client.py`、`tests/test_dataset_writer_idx_factor_pro.py`、Definition/resolver/normalizer与观测测试；新增reason需同步[codebook](/Users/congming/github/goldenshare/src/foundation/ingestion/codebook.py)。新增覆盖基准、版本和发布边界测试必须验证行为与失败恢复，不能只照抄算法。其他数据集与子系统依赖护栏必须通过。

按阶段独立验收：

1. **设计收口与只读核验：** 批准覆盖语义及原D2-A/D4修订；读回代表性源端和Prod样本，区分源端缺口、分页、reject与目标差异；冻结初始候选、DDL、配置及消费者清单。
2. **实现与隔离验收：** 验证动态集合、写入门禁、限次/重试、兜底及状态隔离；模拟分批发布和基准变更；如触发长任务门禁，补真实运行—取消—续跑—读回。
3. **生产启用：** 单独批准迁移、初始基准确认与现有排程迁移；重新核验全部89字段、实际分页和账户预算。只读观察完整发布过程，至少记录两个代表性开市日每轮的时间、集合、缺失/新增、正式拉取/归一化/reject/目标行数及耗时；没有真实数量变动时，用隔离样本覆盖增减验收，不伪造Prod变更。
4. **既有缺口修复：** 另行列明日期及代码差异，按逐日unit经相同门禁补齐；已批准的新方案不能追认旧100多条为完整，也不能自动授权生产补写或删行。

本轮结果：只补充本文方案与初始基准证据JSON，读取当前代码、测试、Git历史及上述源端身份样本；未修改代码/配置/模板、未执行迁移或生产同步、未运行上述拟新增测试。初始基准选择已确认，其余修改计划仍需评审，生产缺口及源端日内节奏尚未独立验收。

### 7.10 基于已确认V1的具体修改计划

#### 7.10.1 本轮交付范围

目标：自动更新不因源端先返回少量记录而过早发布或终止后续更新。验收对象是“相对历史基准的覆盖”，不将新方案命名为源端全量认证。

用户已确认初始V1来源及历史参照语义，并要求提交本方案、继续按计划推进；本轮从M0开始，各切片独立验收。拟改Definition质量策略、覆盖事实存储、probe/runtime、schedule能力与去重、正式写入门禁及相关运营文案。时间输入仍是既有point/range，自动日期仍为当天开市日；不新增运营证券代码、覆盖率容忍阈值或绕过校验开关。现有历史维护早于2026-10-08时没有适用基准将阻塞，属于M0必须明确核对的行为影响，不能上线后才发现。

#### 7.10.2 Foundation持久化与共用校验

现有 `src/foundation/models/meta/source_registry.py`、`dataset_resolution_policy.py` 已使用 `foundation` schema，故拟将覆盖事实放在该schema，不放到Ops，不将其混入Raw源字段或Serving view。

| 拟新增表 | 键和必要索引 | 内容与提交边界 |
| --- | --- | --- |
| `foundation.dataset_source_coverage_baseline` | 主键dataset/source/version；适用日期查询索引dataset/source/effective_from/version | 完整代码JSON、count、SHA-256、样本日、父版本及确认依据；V1导入单独执行，扩容与当日业务发布一起提交 |
| `foundation.dataset_source_coverage_scan` | 扫描ID主键；dataset/source/目标日/采集时间索引 | 保存§7.4身份扫描证据及失败原因，不用TaskRun状态定义有效性；一个扫描一条，不覆盖失败或未齐备的历史观察 |
| `foundation.dataset_source_coverage_validation` | dataset/source/目标日/验证revision复合唯一；同日最新revision索引 | 保留历次业务发布对账、基准及扫描ID、集合指纹和数量，读回按最新已提交revision；与Raw同一unit提交，Ops失败不影响它 |

**初始证据JSON的保存与使用（按本修改计划推进，尚未实施生产导入）：**

1. 将已固化的 `docs/datasets/evidence/idx-factor-pro-coverage-baseline-20261008.json` 随本方案纳入Git长期保留，作为初始V1选择的追溯证据。用户已要求提交方案及证据；本轮只提交这两份文件，不将其理解为生产导入或排程变更授权。
2. 生产启用时，基准导入入口读取该文件，核验dataset/source、样本日、唯一代码数及集合指纹，然后幂等建立V1。相同版本和指纹再次导入不新增记录；已存在V1但指纹不同则拒绝，不覆盖。文件里的3,388是这一份证据的校验数，不是后续每日预期数。
3. 正常运行的probe和正式写入门禁读取数据库中适用于目标日的基准版本，不每次读取仓库JSON；数据库基准不可用时明确阻塞，不回退读取文件或现场生成基准。部署包如何取得初始文件须在导入入口验收中确认，不能依赖开发机绝对路径。
4. 后续扩容或经确认的缩容/改码在数据库追加基准版本，保存集合、指纹、生效日和依据；不改写初始JSON，也不每日向仓库生成新JSON。日常扫描及发布对账分别保存在扫描表和验证表。
5. 这是一份约60KB的初始集合证据。生产基准及各版本同样必须持久化；文件的长期保留不代替数据库记录，不包含因子数值、认证信息或生产运行状态。扫描表和验证表的保留期限另行评估，本条不默认承诺无限保存所有日常扫描，也不授权任何自动清理。

这三张表仅接入 `idx_factor_pro`，不展开为全仓通用治理项目；DDL需验证JSON/日期/唯一性与约束，不能只凭表名生成迁移。模型放Foundation meta目录，查询与发布校验由Foundation负责，按真实用途确定DAO，不把Ops调度规则下沉。新增Alembic前查询届时真实head，不在DDL迁移中拉源端或写V1、修改排程。

拟新增 `src/foundation/ingestion/idx_factor_pro_coverage.py`，承载完整身份扫描、基准选择、缺失/新增计算、稳定确认、正式批次校验和逐日证据。Probe与executor共用；执行参数仍由原builder生成。Definition声明validator及禁止reject/重复的质量口径，复用既有质量字段前核验normalizer、linter和所有消费者。需要新增预算策略字段时同步模型/序列化/模板，不能散落成常量。

当前 `DatasetWriter.write()` 的raw-only分支未调用pre-write validator，故必须显式接通声明的validator，并传入真实unit；无声明的其他数据集保持现行写入语义。`executor`负责取数前就绪检查、短业务事务及验证证据提交；取得有效确认后再获取完整89字段。Raw主键upsert、普通view和日期unit保持现有结构。

现有 `bounded_tushare_call.py` 使用可终止子进程，但错误码/文案包含 `anns_d`，不能未经审计直接套用本数据集。实施前专项化为可注入错误语义的底层有界调用，保留现有公告契约和回归，idx-factor错误统一进入codebook；不复制一套网络调用、不增加新worker/lane或安装依赖。

#### 7.10.3 Probe与自动任务迁移

| 现有文件 | 拟修改 |
| --- | --- |
| `idx_factor_pro_remote_probe_service.py` | 取消limit=1，调用Foundation有界身份扫描；0缺失且两次稳定才matched；错误/不足确认只输出可解释原因 |
| `operations_probe_runtime_service.py` | 本条件不再因命中日志达到1次就停止扫描；按同schedule目标日实际入队数核算3次预算；按业务验证指纹与活动TaskRun决定是否入队 |
| `schedule_automation_capability_resolver.py` | 本条件固定max_triggers_per_day改为3，文案改为历史覆盖校验；保留间隔下限300秒及已有输入限制 |
| `schedule_probe_binding_service.py` | 统一持久化新capability与rule version；拒绝旧每日1次口径继续作为本条件有效配置，不创建第二个条件key |
| `operations_schedule_service.py` | 兜底去重从仅看同日success/partial_success改为活动任务或同集合业务验证证据；预算与probe合并计数；兜底不能直接跳过正式门禁 |
| `schemas/schedule.py`、`schemas/probe.py`、`schemas/catalog.py`及query | 保留既有字段形状，核验默认值与固定值由capability返回；新增覆盖摘要先定义schema，完整迁移消费者，不由前端自行计算 |
| `frontend/src/pages/ops-v21-task-auto-tab.tsx`及共享API类型 | 消费后端固定3次和覆盖文案，展示缺失/新增/确认情况；旧通用默认1只适用于其他动作，不能覆盖本动作capability |

并发保护覆盖同dataset/source/目标日的所有排程，活动检查与入队须原子化；Ops短锁不能跨源端请求或阻塞业务提交。已验证相同集合不再取89字段；窗口内后来出现新增集合则重新确认、执行并扩容。失效的Ops状态不能当业务失败证据，同样不能让source扫描失败去修改已有业务验证记录。

生产排程迁移另有明确清单：只选择 `idx_factor_pro.maintain` 对应排程及绑定规则，记录迁移前后capability、触发上限、rule version、窗口、间隔及启停状态；将上限1改3，不改变原窗口/频率/启停、不创建新schedule、不清空旧日志。迁移V1和排程都属于生产写入，本次不执行。检测到孤立规则、非法参数或无法唯一对应schedule时报告并停止该条迁移。

#### 7.10.4 按切片推进与验收

| 切片 | 产出 | 独立验收与停止点 |
| --- | --- | --- |
| M0：设计与当前事实对账 | 固化V1证据；完成DDL、配置审计、API摘要合同及全部Definition消费者清单；只读核对Prod排程和代表日期缺口 | 证据代码数/排序/指纹正确；区分源端、分页、reject和目标缺口；没有全量消费者审计或有界调用方案则不编码 |
| M1：Foundation覆盖能力 | 三类记录、基准导入入口、集合规则及有界身份扫描；只在隔离库使用V1 | 3,388→100拒绝、稳定扩容接受、无证据缩容拒绝、历史适用版本和并发版本正确；不写正式数据 |
| M2：正式写入门禁 | Definition质量声明、validator、executor发布对账与状态隔离 | Probe之后源端变成100条时零Raw写入；同日重放幂等；全部89字段及可空数值口径正确；Ops写失败不回滚业务 |
| M3：自动任务闭环 | Probe、3次预算、去重/兜底、运营API与页面一次迁移 | 分批发布直到两次稳定才执行；失败后可再触发；成功后新增代码可补；取消尊重运营意图；其他probe条件回归通过 |
| M4：生产启用与缺口修复 | 按单独授权迁移DDL、导入固化V1、迁移既有排程，观察代表性开市日 | V1读回集合及指纹一致；源端—归一化—Raw/view—验证证据逐项对账；既有日期补写另列清单并单独授权 |

每个切片验收后才进入下一切片；M0不意味着批准M1–M4。历史基准只能识别已知覆盖缺口，不保证尚未观察到的新增指数都已出现；继续保留窗口内复核。源端仅改因子数值、日后出现窗口之外新增代码及跨日自动补漏仍不在本次修改范围。

本修改计划已核对CodeGraph search、impact、callers，以及当前probe、raw-only writer、基础模型schema、有界调用、capability/binding、schedule/probe schema和前端消费点。全量Definition消费者、生产事实、细化DDL和新API字段尚未核完，M0必须补齐；不能把上述文件表称为已经完成的开发验收。
