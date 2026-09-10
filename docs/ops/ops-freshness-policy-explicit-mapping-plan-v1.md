# Ops Freshness 现行契约

更新时间：2026-09-11。本文承接显式 Policy、单一事实源与旧分层观测退场的有效内容；描述当前代码及已知差距，不代表重新完成生产验收。

## 1. 职责与事实来源

Freshness 回答“数据是否追到应完成日期，或是否有维护成功记录”，不证明全历史、全部对象或分钟数据完整。

- `DatasetDefinition` 定义身份、表、日期模型、源端发布策略及 `observability.freshness_policy`。Policy 集中维护在 [freshness_policies.py](/Users/congming/github/goldenshare/src/foundation/datasets/freshness_policies.py)，builder 注入定义；缺少映射直接报错，不由 Ops 或前端猜测。
- Ops 将定义投影为 `DatasetFreshnessProjection`，结合真实目标表观测与 TaskRun/节点成功、失败记录计算状态。依赖方向是 **Ops → Foundation**，不是反向。
- `ops.dataset_status_snapshot` 是现行观测与状态投影，不是业务数据事实源，也不是 Kopia 备份，必须保留。它还为日期完整性规则列表提供已观测数据范围，不能理解成“只服务一个页面、可随意清空”。
- Policy 不落入 snapshot 表；查询按运行进程已加载的 Definition 解释观测结果。Registry 有进程内缓存，修改源码不等于下一次请求自动热更新。

全量数据集清单回到代码及 [registry 测试](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)，不在本文复制容易过时的逐项映射。日期输入、执行单元与完整性审计的区别见[日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)。

## 2. 五类 Policy

| Policy | 判断依据 | 展示重点 |
| --- | --- | --- |
| `continuous_open_day` | 最新观测业务日与应完成交易日比较；后者可能受源端发布时间影响 | 最新业务日期、应完成业务日期、滞后天数 |
| `continuous_natural_day` | 最新观测自然日与北京时间参考日比较 | 最新自然日、应完成自然日、滞后天数 |
| `period_bucket` | 按日期模型选取应完成的周、月或月窗口锚点，再比较观测日期 | 最新周期、应完成周期 |
| `event_run_trace` | 有成功记录为 `fresh`，无成功记录为 `unconfirmed`；不要求事件每天发生 | 最近维护成功时间、最新事件日期或时间 |
| `snapshot_run_trace` | 有成功记录为 `fresh`，无成功记录为 `unconfirmed`；不比较连续日期 | 最近刷新成功时间；不展示业务日期或滞后天数 |

事件型、快照型均不生成 `expected_business_date` 或 `lag_days`；没有成功记录时，不要求先证明表中有数据才返回 `unconfirmed`。它们的正常待确认状态不是 `unknown`。

已有修正：`dividend`、`stk_holdernumber` 仍支持公告日期范围维护，但 `bucket_rule=not_applicable`、`audit_applicable=False`，不再参加连续日期完整性审计；`block_trade` 使用事件型 freshness。不能据此推断所有事件类数据都采用同一输入模型，或反过来用 Policy 控制完整性审计。

### 日期、阈值与异常状态

计算实现见 [OpsFreshnessQueryService](/Users/congming/github/goldenshare/src/ops/queries/freshness_query_service.py) 的 `_build_item`、`_freshness_status_for_policy` 和 `_expected_business_date_target_for_projection`。

1. 参考时刻统一为 `Asia/Shanghai`。连续型/周期型的 `lag_days = max(应完成日期 - 最新观测日期, 0)`，单位是**自然日**，不是缺失交易日数或缺失周期桶数。
2. 差值为 0 返回 `fresh`；正差值不超过对应上限返回 `lagging`，超过则为 `stale`。当前每日规则上限为 2 天，周规则为 14 天，月规则为 31 天，未列出的 bucket rule 默认 7 天；这些是现行代码值，不是新增性能门禁。
3. 应完成日期不能统一简化为最新开市日：`next_calendar_day_0830` 要等对应交易日的次自然日 08:30；`next_open_day_0930` 在下一开市日 09:30 到期前保持 `unconfirmed`。源端发布目标无法解析也返回 `unconfirmed`。具体解析见 [DatasetReleaseTargetService](/Users/congming/github/goldenshare/src/ops/services/dataset_release_target_service.py)，不在本专题复制各数据集探测配置。
4. 股票自然周五/月末与指数最后交易日等周期锚点不能混用；月键/月窗口按当月首日目标判断。观测值也需按同类锚点筛选，不能任取共表中的其他频率日期。
5. 连续型/周期型缺少定义、无法得到日期差等情况可能为 `unknown`；无成功记录且无法算日期差，但有观测日期/时间时为 `unconfirmed`。不要把 `unknown` 一概解释成任务失败。

### 新鲜度与最近失败分开

`freshness_status` 不被较新的失败自动覆盖。事件型数据可以同时为 `fresh` 并带有较新的失败摘要；“新鲜度正常”不等于“最近一次任务成功”。已有成功之后的失败才继续显示，早于或等于成功时间的失败会被隐藏。

[今日关注列表](/Users/congming/github/goldenshare/src/ops/queries/overview_query_service.py)纳入带失败消息的数据集，以及 `lagging/stale/unconfirmed` 数据集，失败项优先。它不同于 `summarize()` 返回的五条滞后/未确认摘要，不能相互替代。

## 3. 查询与刷新链路

```text
目标业务表 + TaskRun/节点/issue
  → build_live_items：读取观测值与维护记录
  → DatasetStatusSnapshotService：写入状态投影
  → freshness 查询：读取投影 + 当前已加载定义 + 北京时间/交易日历
  → 重算应完成日期、状态与展示标签，附加调度和活动任务信息
  → freshness API、数据集卡片、总览/今日运行
```

入口见 [freshness 查询](/Users/congming/github/goldenshare/src/ops/queries/freshness_query_service.py)、[状态刷新服务](/Users/congming/github/goldenshare/src/ops/services/operations_dataset_status_snapshot_service.py)。完整字段由 [Ops API 参考](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md)维护，不在本文复制 schema。

- 快照中混合 `snapshot_date` 不会单独触发实时扫描；查询用缓存观测值重算，不直接相信已保存的状态。部分数据集缺行时按定义补无观测项，已不存在的定义会被跳过。
- 正常刷新入口包括 `ops-rebuild-dataset-status`、任务完成后的资源刷新；本地 `freshness_latest_open` 探测也会刷新并实时观测指定数据集。它属于后台探测，不是页面展示请求。
- 查询重算日期不等于重新读取业务数据；成功/失败和观测值仍依赖投影更新。`DatasetStatusSnapshotService.read_snapshot()` 是直接读缓存结果，不能当成页面按当前日期重算的等价入口。

<a id="query-safety-gap"></a>

### 页面查询安全要求与现存差距

**设计要求保留：页面请求不应同步扫描业务表；业务观测应由后台刷新承载。** 不得因文档精简而放宽这条要求。

当前实现尚未完全满足：`_build_from_snapshot()` 在没有任何快照行或捕获 `SQLAlchemyError` 时返回 `None`，`build_freshness()` 随后调用 `build_live_items()`，可能扫描多个业务表。现有“有快照时不 live scan”测试不证明空表/异常分支也满足要求。记录此差距不代表批准该回退，也不在本次文档治理中改造它。

## 4. 消费者边界

- 外部数据集卡片消费统一 freshness，但逻辑卡片可聚合多个成员：健康度取较差状态，日期等字段聚合，活动任务可令卡片主状态为 `running`。不能要求卡片 `status` 与单个数据集 `freshness_status` 字面恒等。[实现](/Users/congming/github/goldenshare/src/ops/queries/dataset_card_query_service.py)
- 页面使用服务端的 `latest_observed_date`、`expected_observed_date` 及对应 label、`last_success_label`，不把事件日期统一叫业务日。无值时不凭页面常量伪造事实。
- Biz 卡片有独立观测契约，见 [Biz 投影专题](/Users/congming/github/goldenshare/docs/ops/ops-biz-dataset-auto-projection-plan-v1.md)；本文五类外部数据集 Policy 不自动套用到 Biz。
- `freshness_latest_open` 仅适用于 `continuous_open_day`，比较本地观测日与最新开市日是否相等；它不等于通用的“fresh 即源端就绪”。远端条件与绑定限制由[自动任务能力契约](/Users/congming/github/goldenshare/docs/ops/ops-automation-capability-contract-plan-v1.md)维护，不再声称探测只有一种条件。
- 日期完整性审计使用 `date_model.audit_applicable`、bucket rule 等定义事实，不由 freshness Policy 决定；规则列表读取 snapshot 中的数据范围，也不代表已经验过该范围内每一日/每一对象。[规则查询](/Users/congming/github/goldenshare/src/ops/queries/date_completeness_query_service.py)

<a id="retired-observation"></a>

## 5. 已退场内容与不可回退边界

2026-05-15/16 的迁移分别为：

- [20260515_000107](/Users/congming/github/goldenshare/alembic/versions/20260515_000107_retire_ops_layer_snapshot.py)：删除 `dataset_layer_snapshot_current/history` 两张旧观测表，以及状态投影的四个分层状态列；不是删除 `dataset_status_snapshot` 本身。
- [20260516_000108](/Users/congming/github/goldenshare/alembic/versions/20260516_000108_drop_dataset_status_snapshot_cadence.py)：删除状态投影的 `cadence`。原 `DatasetDomain.cadence`、API 更新频率字段及对应页面展示不再作为现行口径。

保留以下边界：不恢复旧分层观测 API、模型、页面或基于旧分层行数的探测；不建立第二套健康度事实源。`raw/std/serving/light` 等交付层次仍有各自职责，退出的是独立分层健康状态，不是数据层或 `layer_plan`。

状态写入必须与业务数据事务隔离，不得阻塞或回滚已提交的业务数据；本专题及历史迁移不授权清空业务表、清空状态表或重新执行旧施工命令。源接口参数与维护执行链路不因 freshness 调整而改变。

历史记录确认 M1–M5 实施完成，但原 M6“快照重建与回归”没有在本轮获得独立生产证据；既不自动结案，也不认定目前仍未执行。需要运行态结案时另行只读核实，不能因保留历史记录而自动触发重建或迁移。

<a id="cadence-retirement"></a>

### cadence 退场：已完成，不另设实施清单

2026-05-16 原清单记录已完成：先明确 Policy，再冻结新增依赖、去页面展示、删除 freshness 兜底、删除 snapshot/API 字段，最后移除定义字段。该 M1–M5 是 cadence 专项，不与上文旧分层观测的 M1–M6 混算；本轮没有重新核验生产迁移或状态重建。

退场原因是“每日/低频/快照”标签不能准确表达输入、审计、发布和成功维护语义。现行判断使用 date_model、显式 freshness_policy、真实观测及 TaskRun；不能简写成 freshness 只看 date_model，也不新增另一套节奏镜像字段或兼容层。

历史传播链为 DatasetDomain → Ops projection → freshness/card/snapshot → API 类型与数据源页。现行实现不再使用 cadence/cadence_display_name 字段或兜底；但历史迁移、说明和防回流负向测试允许保留该词。审计应看实际依赖，不能要求全文关键词零命中。

关闭状态继续由[风险登记簿 RISK-2026-05-05-005](/Users/congming/github/goldenshare/docs/governance/engineering-risk-register.md)记录。回归复用下节定义、freshness、snapshot、卡片和总览测试；若改变前端，追加数据源页测试与类型检查，若改变边界则追加依赖矩阵测试。此次合并不执行迁移、重建或业务数据清理。

## 6. 回归入口与维护方式

修改实现时按影响面选用既有测试，不把文档整理升级为生产执行：

- `tests/test_dataset_definition_registry.py`：定义与集中映射覆盖一致。
- `tests/test_ops_freshness_snapshot_query_service.py`：北京时间跨日、发布目标、已有快照重算不扫描业务表、观测映射。
- `tests/web/test_ops_freshness_api.py`：事件/快照未确认、失败展示及周期日期；`tests/test_ops_dataset_release_target_service.py`：源端发布时间。
- `tests/test_dataset_status_snapshot_service.py`：投影刷新；`tests/web/test_ops_dataset_cards_api.py`、`test_ops_overview_api.py`：卡片、总览消费者。
- 涉及审计或探测时追加 `tests/web/test_ops_date_completeness_api.py`、`test_ops_schedule_api.py`；涉及前端时依其目录规则做类型、交互及构建验证。

纯文档变更只做文档完整性、引用、差异及代码口径对账。本轮合并去向和历史追溯见[治理记录](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md#ops-freshness-consolidation-20260909)，不保留重复计划或跳转空壳。
