# 公募基金 B2：基金列表（`fund_basic`）LLD v1

状态：**LLD、B2-M1 与 B2-M2 隔离验证已通过。尚未应用生产 migration，未创建任务或写入远程数据。**
日期：2026-08-06
上游总览：[公募基金九数据集接入总览与分批推进计划 v1](public-fund-nine-dataset-onboarding-program-plan-v1.md)
依赖：[B0 观察快照直出最小地基 LLD](public-fund-b0-observed-snapshot-foundation-low-level-design-v1.md)、[B1 基金管理人与业绩基准库 LLD](public-fund-b1-static-reference-low-level-design-v1.md)
源端发现审计：[公募基金列表接入发现审计](fund-basic-onboarding-discovery-audit.md)
源接口文档：[公募基金列表](../sources/tushare/公募基金/0019_公募基金列表.md)

## 0. 结论与实施边界

B2 只接入 Tushare `fund_basic`，采用 B0 已实现的“current 完整快照 + observation 观察版本”direct-serving 协议。B1 是否已配置 schedule 与 B2 无数据或代码依赖；B2 的进入门禁是 B1 生产迁移和首次完整同步五段对账已通过，该条件已经满足。

本批必须是**一个无时间、无运营筛选的完整快照 unit**。不得把 E、O 市场拆成两个 unit：现有 `ObservedSnapshotDAO.replace_current_snapshot()` 会删除整张 current 表，而 `IngestionExecutor` 按 unit 独立提交；两个市场 unit 会导致后执行市场覆盖先执行市场。

真实 connector 已证明：不传 `market`、显式请求全部 25 字段并用 `limit/offset` 分页，得到的 32,342 行与分别请求 `market=E`、`market=O` 的逐行多重集并集完全相等。因此 B2 固定使用一个 `request_params={}` unit，由同一 unit 连续翻页并在一个事务中替换 current。

本批不做以下事项：

- 不创建或启用生产 schedule；只声明普通 cron/once 能力，后续由运营明确频率后手工配置。
- 不接 probe，不加入 workflow，不自动 seed schedule。
- 不暴露 `ts_code`、`market`、`status` 或其他运营 filters，避免局部请求替换全量 current。
- 不创建 raw/core/EAV/JSON 镜像，不关联或解析 `benchmark` 到 `mkt_idx_bmk`。
- 不修改 B1 的分页、身份、表或同步语义。
- 不进行生产 migration、首次同步或远程数据写入；这些需要后续单独授权。

## 1. 已定口径与硬需求

1. 场内 E 与场外 O 的全部 Tushare 源记录都必须保存；“全量”不允许被 ETF 池、代码后缀、`status`、前端筛选或固定页数上限缩小。
2. 25 个输出字段必须全部显式放入 `source_fields`，每页都携带同一 fields，并全部进入 current 与 observation。
3. `benchmark` 保留为 Tushare 原始文本，不自动结构化、不与 `mkt_idx_bmk` 建外键或文本关联。
4. 逻辑实体身份是去首尾空格并转大写后的 `ts_code`；源字段 `ts_code` 原值不改写。
5. current 保存最近一次完整源快照；observation 从接入日起保存同一实体的内容变化版本。观察时间不是源端生效时间。
6. direct-serving 业务表和全部索引放 `gs_raw_cold_hdd`；PostgreSQL WAL 保持现有 SSD 配置。
7. Ops 归入既有“公募基金”分组；支持手动、普通 cron/once schedule 和重试；不支持 probe/workflow。
8. 任一 source field 缺失、任一 normalize reject、空快照、完全重复源行或缺少 E/O 任一市场，都必须在删除 current 前使整个 unit 失败。

## 2. 源接口真实行为验证

验证日期：2026-08-06。业务行数是当次基线，不是永久 SLA。

### 2.1 请求形态矩阵

| 请求形态 | 实际参数 / fields | 结果 | 结论 |
| --- | --- | --- | --- |
| 不传业务参数、未分页 | `{}`；未显式 fields 的既有验证 | 恰好 15,000 行，E/O 混合 | 单页命中上限，不能作为全量基准。 |
| 对象过滤 | `ts_code=510300.SH`；25 fields | 1 行，`market=E` | 只证明源端支持对象查询，不暴露为运营 filter。 |
| 时间点 / 时间区间 | 接口无时间参数 | 不适用 | 数据集是 no-time snapshot，不建立日期输入。 |
| 显式 E 分页 | `market=E, limit=2000, offset=0/2000`；25 fields | `2000 + 883 = 2,883`；2,883 个唯一 `ts_code` | E 分片完整翻至 short page。 |
| 显式 O 分页 | `market=O, limit=2000, offset=0..28000`；25 fields | `14×2000 + 1459 = 29,459`；29,459 个唯一 `ts_code` | O 分片完整翻至 short page。 |
| 不传 market 分页 | `limit=2000, offset=0..32000`；25 fields | `16×2000 + 342 = 32,342`；E=2,883、O=29,459 | 一个请求范围可以分页取得 E/O 全集。 |
| 无 market 与显式 E+O 对账 | 对 25 字段逐行规范序列计算多重集 | 行多重集、`ts_code` 集合完全相等；缺失/额外均为 0 | 单完整 unit 有真实基线。 |

分页由项目 `TushareHttpClient` 实测：第二页及后续 offset 生效，短页结束。当前 MCP 的 `fund_basic` schema 未暴露 `limit/offset`，因此 MCP 仅用于参数、字段和样本核验，不冒充项目 connector 的分页证据。

### 2.2 字段与数据特征

显式 source fields 固定为：

```text
ts_code, name, management, custodian, fund_type, found_date, due_date,
list_date, issue_date, delist_date, issue_amount, m_fee, c_fee,
duration_year, p_value, min_amount, exp_return, benchmark, status,
invest_type, type, trustee, purc_startdate, redm_startdate, market
```

当前 32,342 行样本中，25 个字段均存在于每一行；`ts_code` 和 `market` 无空值。`status` 分布为 L=26,910、D=4,884、空值=548，证明不能按状态过滤或把状态写成必填排他枚举。`exp_return`、`trustee` 当前全部为空，但仍是源端声明字段，必须请求并保存，不能因当前样本为空删除字段。

七个数值字段当前最大观测小数位为 4，最大绝对值不超过 4,579.4338；使用 `NUMERIC(30,10)` 可覆盖当前证据并避免费用、面值等商业值的二进制浮点漂移。五个日期字段和两个申赎日期字段保留源端 `YYYYMMDD` 文本，使用 `VARCHAR(8)`；这样 observation 内容表示与源字段一致，不把无效或未知日期强行解释成业务日期。

完整分页行的紧凑 JSON 约 19.82 MiB。当前一次完整抓取为 17 个源请求、32,342 行；允许在单 unit 内累积后写入一个业务事务，不引入分页分段提交，也不设置会截断源数据的页数或行数上限。后续发布验收必须重新记录当次行数、请求数、内存和事务耗时；若资源不足应让任务明确失败并复审 transaction / writer，不能截断后提交部分快照。

### 2.3 文档差异

本地源文档写明 `market` 默认 E；真实无 market 分页却返回完整 E/O，并与显式 E+O 多重集相等。实现以当前 connector 实测为准，同时用声明式批次完整性防护要求 `market` 至少出现 E、O。若源站恢复文档行为只返回 E，normalizer 必须整批失败，不能替换 current。

## 3. 三层语义拆分

| 语义层 | B2 口径 | 代码依据 |
| --- | --- | --- |
| 时间输入 | Ops/TaskRun/Schedule 只提交 `action=maintain`，不提交日期、市场、状态或代码。 | `date_axis=none`、`input_shape=none`、`supported_time_modes=("none",)`。 |
| 执行 / unit | resolver 生成一个 `none` unit，`request_params={}`；source client 在该 unit 内以 2,000 行分页至 short page；一个 unit 一个事务。 | B0 observed-snapshot Definition linter强制无 filters、无 fan-out；executor 按 unit commit。 |
| freshness / audit | 不存在业务日期桶，不要求每日有数据；只展示最近成功快照迹象，不做连续日期完整性审计。 | `bucket_rule=not_applicable`、`observed_field=None`、`audit_applicable=false`。 |

这里的 `not_applicable` 同时表示不支持时间输入，而不仅是退出 freshness/audit。

## 4. DatasetDefinition 与执行契约

### 4.1 Definition

| 段 | 固定值 |
| --- | --- |
| identity | `dataset_key=fund_basic`、中文名“基金列表” |
| domain | `public_fund / 公募基金` |
| source | `tushare / fund_basic`，25 个显式字段，`base_params={}`，复用 `_public_fund_snapshot_params` |
| date_model | `none / not_applicable / none / none`，无 observed field，无 audit |
| input_model | 无 time fields、无 filters |
| storage | `serving_observed_snapshot_refresh`；current + observation；无 raw/std |
| planning | `no_pool`、无 enum fan-out、`offset_limit`、`page_limit=2000`、并发 1、generic unit builder |
| normalization | 七个 decimal fields；required=`ts_code, market, source_entity_key`；`_fund_basic_observed_snapshot_row_transform` |
| capabilities | maintain 支持 manual/schedule/retry，仅 `time_mode=none` |
| observability / quality | 最近快照健康；required markets E/O；duplicate policy 由 B0 writer fail-closed |
| transaction | `commit_policy=unit`；一个完整快照事务 |

B1 的 `_OBSERVED_SNAPSHOT_PLANNING` 固定 `page_limit=64`，B2 不修改或复用该常量。`public_fund.py` 新增 B2 专属 planning 常量，避免改变 B1 的请求次数与既有测试。

### 4.2 身份与内容版本

`public_fund_contracts.py` 新增 `FUND_BASIC_SOURCE_FIELDS` 和纯函数 `fund_basic_identity(row)`：

- `source_entity_key = strip(ts_code).upper()`；
- `identity_basis = "ts_code"`；
- 空白 `ts_code` 仍产生空 entity key，随后由 required field 规则以 `normalize.empty_not_allowed:source_entity_key` 拒绝；
- 25 个 source fields 原值不被 identity helper 改写；
- `source_content_hash` 继续由 B0 writer根据全部 25 个 source fields 计算。

同一 `ts_code` 内容变化时，observation 新增 `(source_entity_key, source_content_hash)` 版本；current 只保留最新完整快照中出现的版本。当前源样本没有同一 `ts_code` 的多行变体；如果未来同一 entity 在同一快照出现不同内容，两条源事实均可表示。若完全相同行重复出现，B0 writer 以 `write.snapshot_duplicate_record` 拒绝整个快照。

### 4.3 声明式整批完整性防护

为避免在 writer、DAO 或 planner 中写 `fund_basic` 特例，`DatasetQualityPolicy` 新增可选字段：

```python
required_distinct_values: dict[str, tuple[str, ...]] = field(default_factory=dict)
```

`fund_basic` 配置：

```python
"required_distinct_values": {"market": ("E", "O")}
```

normalizer 在完成逐行归一化和重复键策略后、返回 `NormalizedBatch` 前校验整批字段值。缺少任一声明值时抛出：

```text
normalize.required_distinct_values_missing
```

错误 details 必须包含 `field`、`required_values`、`observed_values`、`missing_values` 和 `unit_id`。该错误加入 ingestion codebook。Definition linter 必须拒绝以下配置：字段不在 `source_fields`、字段名或要求值为空、要求值重复。该能力是 opt-in 的通用批次完整性约束；B0/B1 和其他未配置数据集行为不变。

## 5. 字段端到端与表结构

### 5.1 字段映射

direct-serving 有意不建 raw，以下 25 字段同时存在于 current 与 observation。

| 源字段 | 源类型 | ORM / DDL | nullable | 身份/语义 |
| --- | --- | --- | --- | --- |
| `ts_code` | str | `TEXT` | 否 | 源实体身份输入；源值保留 |
| `name` | str | `TEXT` | 是 | 基金名称 |
| `management` | str | `TEXT` | 是 | 管理人名称源事实 |
| `custodian` | str | `TEXT` | 是 | 托管人名称源事实 |
| `fund_type` | str | `TEXT` | 是 | 基金类型 |
| `found_date` | str | `VARCHAR(8)` | 是 | 成立日期原文 |
| `due_date` | str | `VARCHAR(8)` | 是 | 到期日期原文 |
| `list_date` | str | `VARCHAR(8)` | 是 | 上市日期原文 |
| `issue_date` | str | `VARCHAR(8)` | 是 | 发行日期原文 |
| `delist_date` | str | `VARCHAR(8)` | 是 | 退市日期原文 |
| `issue_amount` | float | `NUMERIC(30,10)` | 是 | 发行份额 |
| `m_fee` | float | `NUMERIC(30,10)` | 是 | 管理费 |
| `c_fee` | float | `NUMERIC(30,10)` | 是 | 托管费 |
| `duration_year` | float | `NUMERIC(30,10)` | 是 | 存续年限 |
| `p_value` | float | `NUMERIC(30,10)` | 是 | 面值 |
| `min_amount` | float | `NUMERIC(30,10)` | 是 | 最低申购金额 |
| `exp_return` | float | `NUMERIC(30,10)` | 是 | 预期收益；当前全空仍保留 |
| `benchmark` | str | `TEXT` | 是 | 原始业绩基准文本，不解析关联 |
| `status` | str | `TEXT` | 是 | 源端状态，允许空和未知值 |
| `invest_type` | str | `TEXT` | 是 | 投资类型 |
| `type` | str | `TEXT` | 是 | 基金类型补充字段 |
| `trustee` | str | `TEXT` | 是 | 受托人；当前全空仍保留 |
| `purc_startdate` | str | `VARCHAR(8)` | 是 | 日常申购起始日原文 |
| `redm_startdate` | str | `VARCHAR(8)` | 是 | 日常赎回起始日原文 |
| `market` | str | `TEXT` | 否 | 全市场完整性维度，必须含 E/O |

raw ORM、raw migration 和 Lake whitelist 均为“不适用：有意 direct-serving”，不得为了字段对账伪造 raw 表。

### 5.2 两张显式列模型

新增：

- `core_serving.fund_basic_current`
- `core_serving.fund_basic_observation`

两表主键都是 `(source_entity_key, source_content_hash)`，并保存全部 25 个 source fields、`identity_basis`、`created_at`、`updated_at`。

current 额外保存 `observed_at`；observation 保存 `first_observed_at`、`last_observed_at`。current 不增加 `is_current`，避免与“表成员即当前快照”形成第二事实源。

索引：

- current：`(source_entity_key)`；
- observation：`(source_entity_key, last_observed_at DESC)`；
- 主键唯一索引和上述二级索引全部显式迁移到 `gs_raw_cold_hdd`。

不分区。当前约 3.2 万行，current 每次完整替换，observation 只在源内容变化时增长；为该规模建立分区只会增加迁移与查询复杂度，不带来可证明收益。

### 5.3 ORM、DAO 与迁移

| 层 | 文件 / 约束 |
| --- | --- |
| ORM | `src/foundation/models/core_serving/fund_basic_current.py`、`fund_basic_observation.py`；注册到 `core_serving/__init__.py` 和 `all_models.py`。 |
| DAO | DAO factory 注册两项既有 `ObservedSnapshotDAO`；不新增业务 DAO 或数据集专用 writer。 |
| migration | 新 migration 的 `down_revision` 只接编码时重新查询到的真实 head；当前审计 head 为 `20260805_000125`。 |
| HDD | upgrade 首先检查 `gs_raw_cold_hdd`；不存在则在建表前失败。两表、PK 和二级索引均指定 HDD。 |
| downgrade | observation 保存源事实，禁止自动 downgrade 删除两表。 |

## 6. 消费者审计与 Ops/UI

| 消费方 | 影响与处理 | 已核验代码 |
| --- | --- | --- |
| manual actions | Definition 自动派生一个无时间、无 filters 的 `fund_basic.maintain`。 | `src/ops/services/manual_action_query_service.py`、现有 B1 API tests |
| Catalog | 在既有 `public_fund` 分组新增排序 30 的 `fund_basic`；不得静默归到其他组。 | `src/ops/catalog/dataset_catalog_views.py` |
| workflow | 不新增 workflow step；工作流无法选择该动作。 | `src/ops/action_catalog.py` 与 workflow registry tests |
| resolver / planner | no-time 请求生成一个 unit，`request_params={}`；不做 E/O fan-out。 | `src/foundation/ingestion/resolver.py`、`unit_planner.py` |
| request builder | 复用 `_public_fund_snapshot_params`，拒绝从 Ops 参数生成 market/status/ts_code。 | `src/foundation/ingestion/request_builders.py` |
| source client | 每页注入同一 25 fields 和 `limit/offset`，短页停止。 | `src/foundation/ingestion/source_client.py` |
| freshness | 注册 no-time snapshot policy，只显示成功快照迹象。 | `src/foundation/datasets/freshness_policies.py` |
| cards / snapshot | direct-serving 由 `target_table/serving_table` 回退展示，不伪造 raw。 | 既有 catalog/status/card projection 与 B0/B1 tests |
| date completeness | `audit_applicable=false`，不产生 expected date buckets。 | date completeness resolver/tests |
| schedule | capability 只返回普通 `schedule`，允许 cron/once；不自动创建持久化记录。 | `src/ops/services/schedule_automation_capability_resolver.py` |
| probe | action key 不在 remote probe registry，freshness policy 也不是 continuous-open-day，因此 probe 创建被拒绝。 | schedule capability resolver 与 schedule/probe API tests |
| frontend | 既有 API contract 渲染公募基金分组、无时间表单和 schedule-only 选项；不新增 action-key 白名单。 | `frontend/src/pages/ops-v21-task-manual-tab.tsx` 与自动任务 capability 消费链 |
| runtime guard | `public_fund` domain allowlist 加入 `fund_basic`；Definition 是唯一事实源。 | `tests/architecture/test_dataset_runtime_registry_guardrails.py` |

本批没有新的前端控件或交互语义，预计不修改生产 TSX/TS。验收以 API contract tests 和浏览器现有页面可见性检查为准；若实施中发现必须修改前端，应停止并先补前端治理前置审计。

## 7. 硬需求追溯账本

| ID | 硬需求 | 实现位置 | 正向测试 | 反向测试 / 真实证据 | 阶段状态 |
| --- | --- | --- | --- | --- | --- |
| B2-REQ-001 | 一个无时间、无 filters 的完整快照 unit | Definition、resolver/planner | plan unit_count=1、params={} | builder/linter拒绝 filters 与 enum fan-out | 代码与自动化已验证 |
| B2-REQ-002 | 25 fields 每页显式请求并全部落两表 | contracts、Definition、ORM、migration | connector替身验证每页 fields；模型列集合 | 缺任一 source field 时 writer 整批失败；真实25字段每行齐全 | 代码与自动化已验证 |
| B2-REQ-003 | E/O 全市场且不传 status | `base_params={}`、无 input filters | 无 market 分页集合等于显式 E+O | 请求参数出现 market/status 的 Definition/plan测试失败 | 真实证据、代码与自动化已验证 |
| B2-REQ-004 | `offset_limit=2000`，无业务最大页数，短页结束 | B2专属 planning、source client | offsets 0/2000/4000、末页2的替身分页；真实17页末页342 | 不允许复用 B1 page_limit=64 或固定5页 | 真实证据、代码与自动化已验证 |
| B2-REQ-005 | 缺 E/O 任一市场不得替换 current | quality contract、normalizer、codebook | E/O 同批通过 | 仅E或仅O抛结构化错误，writer未被调用 | 代码与自动化已验证 |
| B2-REQ-006 | 身份 `ts_code`，保留内容观察版本 | contracts、row transforms、B0 writer | 同 code 内容变化保留两版本 | 空 code reject；完全重复源行整批失败 | 代码与 SQLite 集成已验证 |
| B2-REQ-007 | `benchmark` 原文保存且不关联基准库 | source fields、两模型 | 长文本原样往返 fixture | 无外键、无解析字段、无 join writer | 代码与自动化已验证 |
| B2-REQ-008 | direct-serving，无 raw/std | Definition、B0 writer | current/observation写入 | linter拒绝 raw DAO/table | 代码与 SQLite 集成已验证 |
| B2-REQ-009 | 表、PK、索引全部 HDD；WAL不改 | migration | PostgreSQL隔离库查 tablespace | HDD不存在时建表前失败；downgrade拒绝删表 | 隔离库 fail-closed 与 6 个 relation placement 已验证；生产物理介质待 B2-M3 |
| B2-REQ-010 | 手动 + schedule + retry，无 probe/workflow/seed | Definition、Catalog、Ops resolver | manual与cron/once capability可见 | probe请求、workflow使用、自动seed均不存在/被拒绝 | API contract 自动化已验证 |
| B2-REQ-011 | 公募基金分组排序稳定 | Ops Catalog | group内出现 fund_basic | 不改前端分组白名单、Catalog缺项测试失败 | API contract 自动化已验证 |
| B2-REQ-012 | 空、reject、缺字段、重复源行全量失败 | normalizer、B0 writer | 完整快照成功 | 四类失败均 rollback，不改变旧current | B2 fixture 与 B0 回归已验证 |
| B2-REQ-013 | 单事务规模已评估且不得截断 | transaction assessment | 32,342行/17页/约19.82MiB实测 | 不设页数/行数 cap；资源不足须整批失败，不当作永久SLA | 隔离 PostgreSQL 单事务真实同步与全量对账已验证 |
| B2-REQ-014 | 不创建生产任务或写生产数据 | release流程 | 不适用 | git diff/migration/tests中无seed；本阶段无远程写 | 持续门禁 |

前端表现均由已有 catalog/manual-action/automation capability contract 派生；本批没有 B2 专用前端消费者，因此浏览器只需验证“公募基金 → 基金列表”可见、无时间/filters、自动任务仅普通 schedule。生产任务创建不属于代码验收。

## 8. 实现文件与测试计划

### 8.1 实际改动文件

- Definition / contracts：`src/foundation/datasets/definitions/public_fund.py`、`src/foundation/datasets/public_fund_contracts.py`、Definition注册与 runtime guard。
- 通用 opt-in 质量约束：`src/foundation/datasets/models.py`、`ingestion/linter.py`、`normalizer.py`、`codebook.py`；既有 Definition builder 可直接构造该字段，无需修改。
- 身份转换：`src/foundation/ingestion/row_transforms.py`。
- ORM / registry：两张 `fund_basic_*` 模型及 `core_serving/__init__.py`、`all_models.py`。
- DAO factory：注册 current / observation 的既有 `ObservedSnapshotDAO`。
- migration：一个新 Alembic revision，创建两张 HDD 表与索引。
- Ops：`src/ops/catalog/dataset_catalog_views.py` 新增排序 30 item。
- tests：新增 `tests/test_public_fund_b2_fund_basic_dataset.py`、B2 migration test，并更新 Definition、runtime registry、Ops API 精确集合测试。
- docs：本 LLD、发现审计、源文档、专项总览、`docs/README.md`。

不修改 source client、resolver、unit planner、writer、executor、schedule capability resolver 或前端生产代码；它们只通过现有契约被回归验证。

### 8.2 测试门禁

必须覆盖：

1. Definition：no-time、无 filters、一个 unit、params={}、25 fields、page_limit=2000、observed snapshot storage。
2. 项目 connector替身：17页等价形态、每页 fields一致、offset序列、短页结束、合并唯一键与显式 E/O fixture 一致。
3. identity/normalizer：trim+uppercase entity key但源值不改；数值转换；E/O通过；缺E或缺O结构化失败；空 `ts_code/market` reject。
4. writer：重复同步、内容变化、空快照、partial reject、缺字段、完全重复源行、事务 rollback；复用 B0 既有覆盖并增加 fund_basic fixture。
5. ORM/DAO/registry：两表显式列、nullable、PK、DAO factory 和 table registry。
6. migration：真实 head、HDD fail-closed、两表/PK/二级索引 placement、无自动 destructive downgrade、无 schedule seed。
7. Ops/API：Catalog顺序、无时间手动动作、schedule-only capability、probe拒绝、workflow无条目、direct-serving卡片投影。
8. 架构与回归：Definition registry、runtime guard、subsystem dependency、B0/B1 observed snapshot测试、Definition lint、docs integrity、`git diff --check`。

本批若没有前端源码改动，不把 frontend build 作为代码修改门禁；仍需通过后端 API contract 测试和一次浏览器只读验收。

## 9. 里程碑、发布与回滚

| 阶段 | 内容 | 完成门禁 |
| --- | --- | --- |
| B2-M0 | LLD、源端与影响面冻结 | 本文、真实分页/字段/规模证据、CodeGraph消费者审计通过 |
| B2-M1 | Definition、quality、identity、ORM/DAO、migration、Ops实现 | **已完成**：定向单元、SQLite集成、迁移静态测试及共享链路回归通过；未触发远程写 |
| B2-M2 | 隔离 PostgreSQL migration与最小真实同步 | **已完成**：单次真实完整同步五段对账、`gs_raw_cold_hdd` placement；重复同步/内容变化由 B2-M1 集成测试验证 |
| B2-M3 | 生产发布验收 | 单独授权生产 migration和首次完整同步；不自动创建 schedule |

生产发布顺序必须是：部署代码 → 获得生产迁移授权 → 应用 migration → Manual Action首次完整同步 → fetched/normalized/written/rejected/current/observation 对账 → 运营另行决定是否创建 cron/once schedule。

迁移不提供自动 downgrade 删除源事实。若首次同步失败，保留空表或上一版 current，修复后重试；禁止 truncate/drop/rebuild。若完整性校验缺 E/O，必须停止并重新验证源行为，不能关闭校验绕过。

### 9.1 B2-M2 隔离 PostgreSQL 验收证据（2026-08-06）

本轮使用全新临时 PostgreSQL 18.4 实例和独立数据库 `goldenshare_b2_m2`，未连接远程或生产数据库。先把 B1 已使用的临时 tablespace 改名，使 `gs_raw_cold_hdd` 不存在，再尝试应用 `20260806_000126`：migration 按预期抛出 `B2 公募基金列表快照表要求 PostgreSQL tablespace`，Alembic 保持 `20260805_000125`，两张 B2 表均未创建。恢复 tablespace 名称后升级成功，Alembic head 为 `20260806_000126`。

物理关系的 PostgreSQL catalog 验收结果：`fund_basic_current`、`fund_basic_observation` 两张表，两个主键索引和两个二级索引，共 6 个 relation 的 `reltablespace` 均解析为 `gs_raw_cold_hdd`。隔离实例中该 tablespace 位于临时验证目录；本机没有机械盘挂载，因此这一步证明 DDL 与 catalog placement，不冒充生产服务器物理机械盘证据。生产阶段仍须复核 `pg_tablespace_location` 指向生产 HDD；隔离实例的 WAL 仍位于独立 `data_directory/pg_wal`，未迁入该 tablespace。

随后通过 `DatasetActionResolver -> DatasetSourceClient -> DatasetNormalizer -> DatasetWriter` 执行一个真实完整 snapshot unit。源端与目标对账如下；这些数量是当次样本，不是永久 SLA：

| 对账段 | 当次结果 |
| --- | --- |
| 计划 | `snapshot_refresh`；`unit_count=1`；`trade_date=None`；`request_params={}`；`page_limit=2000` |
| 源端 fetched | 32,342 行；17 次请求；offset `0..32000`；页长 `16×2000 + 342`；retry 0 |
| source fields | 每页显式请求同一 25 字段；每行 25 个源字段均存在；无 `market/status/ts_code` 业务请求参数 |
| normalized | 接受 32,342，reject 0，reason `{}`；key+hash 32,342 |
| writer / commit | 32,342 行在一个 unit 事务内提交；writer 的完整快照协议在 current/observation 任一写入量不等于 32,342 时会拒绝提交 |
| target | current 32,342；observation 32,342；distinct entity 32,342；E=2,883、O=29,459 |
| 集合对账 | source/current、source/observation、current/observation 的 `(source_entity_key, source_content_hash)` 双向差集全部为 0 |
| 存储量 | current 含索引 20,307,968 B；observation 含索引 20,930,560 B |
| Ops 边界 | 隔离库 `fund_basic` TaskRun 为 0，schedule 总数为 0；未创建 probe/workflow/schedule |

首次写入已经成功提交后，验收输出脚本曾因把 SQLAlchemy `Result` 直接转换为 `dict` 报类型错误；该错误发生在业务提交之后，未触发第二次写入。随后用修正后的只读源端分页与目标 SQL 重新构造 32,342 个 key+hash，并完成上述三方集合对账。用户本轮只授权一次真实写入，因此未执行第二次真实同步；重复同源快照和内容变化的观察版本语义继续由 B2-M1 的 SQLite 集成测试覆盖。

## 10. LLD 审计结论

- 源端、分页、字段、身份、数据规模与单事务边界均有当前真实证据。
- “E/O 两个 unit”已判定为会造成 current 覆盖的数据丢失方案，并改为一个无 market 的完整分页 unit。
- 文档“market 默认 E”与当前真实行为的差异已被显式记录，并用整批 E/O 声明式门禁 fail-closed。
- 共享改动仅新增 opt-in 的批次完整性质量约束；不改变 B0/B1 未配置数据集的执行、写入或事务语义。
- Definition、存储、HDD、Ops、前端派生、测试、发布和禁止项均已映射真实代码消费者。
- 没有尚待业务拍板的项目；schedule频率可继续后置，不影响实现。

结论：**B2-M0、B2-M1 和 B2-M2 隔离验证门禁均已通过；生产机械盘物理 placement、生产 migration、首次生产同步和任务配置仍未授权。**
