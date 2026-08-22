# 公募基金 B1：基金管理人与业绩基准库 LLD v1

状态：**实现完成；B0 观察快照 contract 已作为既有共享地基复用。隔离验证与生产迁移、首次完整同步、五段对账均通过；尚未创建 schedule。**
日期：2026-08-05
上游：[公募基金九数据集接入总览与分批推进计划 v1](public-fund-nine-dataset-onboarding-program-plan-v1.md)
依赖：[B0 观察快照直出最小地基 LLD](public-fund-b0-observed-snapshot-foundation-low-level-design-v1.md)
发现审计：[基金管理人](fund-company-onboarding-discovery-audit.md)、[基金业绩基准库](fund-performance-benchmark-onboarding-discovery-audit.md)

## 1. 范围与冻结决策

本批仅接入两个小型、无时间轴的 Tushare 参考快照：

| 数据集 | Dataset key | 接口 | 交付语义 |
| --- | --- | --- | --- |
| 基金管理人 | `fund_company` | `fund_company` | 全量基金管理人源记录、当前源快照 + 接入后观察版本。 |
| 基金业绩基准库 | `mkt_idx_bmk` | `mkt_idx_bmk` | 全量基准指数参考记录、当前源快照 + 接入后观察版本。 |

已冻结：显式请求/保存所有 source fields；完整保存 Tushare 当前返回的所有源记录；Ops 新分组“公募基金”；只支持手动、普通定时和重试；无 probe；所有业务表/索引落 HDD；PostgreSQL WAL 保持 SSD。

不做：基金与基准文本自动关联、用户侧 Wealth API、工作流步骤、source filter 的运营输入、raw 表、历史回补、日期完整性审计、自然日调度策略或 B7 流式分页。

### 1.1 B1 硬需求追溯账本

| ID | 硬需求 | 实现落点 | 正向 / 反向验证 |
| --- | --- | --- | --- |
| B1-01 | 全部 source fields 显式请求并逐页落库 | `public_fund.py`、`DatasetSourceClient`、四个 ORM | 分页 fields/offset、字段链路测试；缺字段由 B0 writer 拒绝。 |
| B1-02 | 无日期、无 filters 的完整快照 | Definition date/input model、generic planner | `none` 计划和手动任务；point/range/未知 filter 拒绝。 |
| B1-03 | 分页无最大页数，短页才停止 | `offset_limit` + `page_limit=64` | 204/141 行 fixture 覆盖多页与短页。 |
| B1-04 | direct-serving 且 current 不可被部分结果替换 | B0 observed-snapshot writer、四表 DAO | 空结果、reject、重复记录与 rollback 回归。 |
| B1-05 | 基金公司同信用代码的不同源内容不得丢失 | `public_fund_contracts.py`、row transform、联合主键 | 同码双变体与内容更新观察历史测试。 |
| B1-06 | 所有表及索引固定 HDD，WAL 不迁移 | `20260805_000125` migration | tablespace 缺失 fail-closed、DDL 与 catalog 验证。 |
| B1-07 | Ops 仅手动/cron/once/retry，无 probe/workflow/seed | Definition、Ops catalog、既有 capability resolver | manual/schedule 正向，probe 触发方式拒绝。 |

## 2. 源端契约与实测证据

### 2.1 `fund_company`

本地源文档：`docs/sources/tushare/公募基金/0118_公募基金公司.md`（doc 118）。Tushare MCP 无参默认返回 204 行/17 字段，不含 `short_enname`；显式请求下列全部 18 字段后仍返回 204 行且字段无缺失：

```text
name, shortname, short_enname, province, city, address, phone, office,
website, chairman, manager, reg_capital, setup_date, end_date, employees,
main_business, org_code, credit_code
```

MCP schema 未展示 `limit/offset`，但不能据此断言“不可分页”。2026-08-05 通过项目的 `TushareHttpClient` 实测，显式 18 字段、`page_limit=64` 时各页为 `[64, 64, 64, 12]`；204 条分页并集与无参数基线按完整行内容多重集完全一致（无遗漏、无额外行、无完全重复行）。所以正式 Definition 必须使用 `offset_limit`，短页是唯一结束条件。

身份实测：204 行中 155 行 `credit_code` 非空；非空信用代码去重后 154 个。`91440400MA4UH0BF7C` 同时对应“中科沃土基金管理有限公司”和“众盈基金管理有限公司”，`org_code/setup_date` 相同；这是一个业务实体的两个当前源记录变体，绝不能因 current 表一实体一行而吞掉其中之一。49 行信用代码为空，均有 `name + setup_date`，当前样本中该组合无重复。

### 2.2 `mkt_idx_bmk`

本地源文档：`docs/sources/tushare/公募基金/0462_公募基金业绩基准库.md`（doc 462）。无参数和显式请求都返回 141 行、完整 8 字段；`ts_code` 无空值且不重复：

```text
ts_code, symbol, name, fullname, bmk_level, bmk_type, bmk_src, idx_type
```

`ts_code=000001.SH` 实测只返回一条匹配行；`BMK_TYPE=宽基` 返回 31 条且均为宽基。它们是源端筛选能力，不是本批 Ops 输入，因为局部请求会破坏“当前全库快照”语义。

同样，MCP schema 没有列分页字段，但项目 HTTP client 的 `page_limit=64` 实测页长为 `[64, 64, 13]`，141 条分页并集与无参数基线完整行多重集一致。正式定义采用同一分页协议。

该接口没有基金代码、公告日、生效日或历史版本字段。它是独立指数参考库，**不得**把 `fund_basic.benchmark` 的自由文本解析、推断或覆盖到本表；基金-基准映射不是本批可证明的源端事实。

## 3. Definition、时间和请求设计

两项 Definition 都位于新增 `src/foundation/datasets/definitions/public_fund.py`，由 `definitions/__init__.py` 明确注册；不塞入 ETF 的 Definition 文件，不用 source 菜单分类决定产品域。

| 项目 | `fund_company` | `mkt_idx_bmk` |
| --- | --- | --- |
| domain | `public_fund` / `公募基金` | `public_fund` / `公募基金` |
| time model | `date_axis=none`、`input_shape=none`、`bucket_rule=not_applicable`、`audit_applicable=false` | 同左 |
| action | `maintain`；manual/schedule/retry 均 true；只支持 `time_mode=none` | 同左 |
| run profile / unit | `snapshot_refresh`，一个全量 unit | 同左 |
| filters | 空；不暴露字段 | 空；不暴露 `ts_code`/`BMK_TYPE` |
| source | `tushare` / `fund_company` / doc `tushare.fund_company` | `tushare` / `mkt_idx_bmk` / doc `tushare.mkt_idx_bmk` |
| request fields | 固定为上节 18 字段 | 固定为上节 8 字段 |
| pagination | `offset_limit`，`page_limit=64`，`no_pool`，concurrency=1 | 同左 |
| freshness / completeness | `snapshot_run_trace`；不做连续日期或对象矩阵审计 | 同左 |

每页请求仅由通用 source client 生成：`fields=<全部字段>`、`limit=64`、`offset=0,64,...`。禁止配置最大页数；当页长 `<64` 成功结束，若前页恰好 64 则必须继续请求下一页（包括可能的空终止页）。B1 体量至多四页，现有 source client 全页累积后归一化/写入不会造成内存风险；不得借此声称 B7 无需页流式写入。

无 filters 不是 UI 缺失：它防止任何一次单公司/单基准请求把不在局部结果中的当前记录误标为非当前。以后若需要局部源查询，必须另立不改变全量 current snapshot 的读取/补录设计，不能给本维护 action 偷加参数。

## 4. 身份、当前记录与观察历史

### 4.1 共同语义

采用 B0 的 `serving_observed_snapshot_refresh`：

- `current` 表只含最近成功完整源快照中的**源记录内容版本**；它不等价于基金公司/指数的法律或业务状态。
- `observation` 表保存接入日起每一个 `(source_entity_key, source_content_hash)`；没有源端历史日期，不能说它是源端生效版本。
- 每个源字段均同时存在于 current 与 observation 表；`source_content_hash` 对全部显式 source fields（含 null）计算。
- 完全相同的源记录重复出现无法用源端稳定 ID 表达次数，因此整 snapshot fail-closed；不同内容但同一实体键是合法的多版本/多变体，必须全部保存。

### 4.2 `fund_company` 身份

归一化仅添加内部元数据，不裁剪任一源字段：

| 条件 | `source_entity_key` | `identity_basis` | 处理 |
| --- | --- | --- | --- |
| `credit_code` 非空 | `credit:<规范化信用代码>` | `credit_code` | 业务确认的实体身份；同码不同内容同时保留。 |
| 信用代码为空且 `name + setup_date` 可用 | `name_setup:<sha256(规范化名称 + 分隔符 + setup_date)>` | `name_setup` | 保守身份；不跨名称/成立日自动合并。 |
| 两者都不可用 | `content:<source_content_hash>` | `content_hash_fallback` | 归一化以 B0 的纯内容哈希 helper 和本接口的 18-field tuple 先生成键；writer 会独立重算同一哈希。仍完整保存这条源记录，但不把它与任何其他机构自动合并。 |

当前实测落在前两种：155 条信用代码记录、49 条 `name_setup` 回退记录。上述两条同信用代码但名称不同的记录将有同一 `source_entity_key`、不同 `source_content_hash`，因此在本次 `current` 中各占一行；这既保留全量源事实，也允许按信用代码查看同一实体的观察变体。

### 4.3 `mkt_idx_bmk` 身份

`source_entity_key = ts_code`，`identity_basis = ts_code`。`ts_code` 缺失或空白是不可恢复的 source-contract 错误，整 snapshot 失败，不写部分数据。当前 141 行均满足。

## 5. 存储、ORM、DAO 与迁移

### 5.1 物理对象

本批直接服务，不建 `raw_tushare.*`、`core.*` 或 JSON/EAV 表。B1 创建四张 explicit-column 表：

| 表 | 主键 | 作用 |
| --- | --- | --- |
| `core_serving.fund_company_current` | `(source_entity_key, source_content_hash)` | 最近一次完整源快照。 |
| `core_serving.fund_company_observation` | `(source_entity_key, source_content_hash)` | 接入后观察历史。 |
| `core_serving.mkt_idx_bmk_current` | `(source_entity_key, source_content_hash)` | 最近一次完整基准库快照。 |
| `core_serving.mkt_idx_bmk_observation` | `(source_entity_key, source_content_hash)` | 接入后观察历史。 |

所有表都有 B0 固定元数据；current 表只用其成员资格表达“当前”，**不新增 `is_current`**。所有业务表、主键索引和额外索引必须显式使用 `TABLESPACE gs_raw_cold_hdd`。B1 无时间分区：当前量为 204/141，按日期分区只会增加运维对象而无剪枝收益。共享 `pg_wal` 不移动，继续由 PostgreSQL 默认 SSD 承担 WAL。

迁移必须先读取真实 Alembic head，再以该 head 为 `down_revision`；不得沿用本文日期或旧 migration 文件名猜测。迁移先校验 `pg_tablespace` 存在 `gs_raw_cold_hdd`，缺失即失败，**不得**回退到默认 SSD。降级不得删除已保存的源事实，应显式拒绝自动 downgrade。

### 5.2 字段映射

`fund_company` 的 source 字段全部显式列：

| Source field | Current / observation 列类型 | 可空 |
| --- | --- | --- |
| `name`, `shortname`, `short_enname`, `province`, `city`, `address`, `phone`, `office`, `website`, `chairman`, `manager`, `main_business`, `org_code`, `credit_code` | `TEXT` | 是 |
| `reg_capital`, `employees` | `NUMERIC(30, 10)` | 是 |
| `setup_date`, `end_date` | `VARCHAR(8)`，保留源端 `YYYYMMDD` 文本 | 是 |

`mkt_idx_bmk` 的 `ts_code`、`symbol`、`name`、`fullname`、`bmk_level`、`bmk_type`、`bmk_src`、`idx_type` 均为 `TEXT`、可空；唯一不可空的是 B0 元数据 `source_entity_key/source_content_hash`，而 `ts_code` 空值会在归一化门禁前失败。

每张表另有：`source_entity_key TEXT NOT NULL`、`source_content_hash VARCHAR(64) NOT NULL`、`identity_basis VARCHAR(32) NOT NULL`、`created_at/updated_at`；current 表加 `observed_at TIMESTAMPTZ NOT NULL`，observation 表加 `first_observed_at TIMESTAMPTZ NOT NULL`、`last_observed_at TIMESTAMPTZ NOT NULL`。额外索引：current `(source_entity_key)`，observation `(source_entity_key, last_observed_at DESC)`；均在 HDD tablespace。

### 5.3 代码落点

| 责任 | 文件 |
| --- | --- |
| B0 shared contract/writer/DAO | B0 LLD 第 4 节列出的 foundation 文件。 |
| B1 Definitions | `src/foundation/datasets/definitions/public_fund.py`、`src/foundation/datasets/definitions/__init__.py` |
| B1 identity/source-field constants | `src/foundation/datasets/public_fund_contracts.py`（新增）；一份 field tuple 同时供 Definition 与 content-fallback transform 使用。 |
| B1 identity transforms | `src/foundation/ingestion/row_transforms.py`；只添加两项 named transform，调用 B0 的纯内容哈希 helper。 |
| ORM | `src/foundation/models/core_serving/fund_company_current.py`、`fund_company_observation.py`、`mkt_idx_bmk_current.py`、`mkt_idx_bmk_observation.py`，以及 `core_serving/__init__.py`、`all_models.py`。 |
| DAO registration | `src/foundation/dao/factory.py`；每张表显式实例化 B0 的 DAO。 |
| schema | 一个新的 `alembic/versions/*_add_public_fund_b1_snapshot_tables.py`。 |
| Ops Catalog | `src/ops/catalog/dataset_catalog_views.py`。 |
| 前端 | 无生产 JSX/TS 改动；现有 API contract 已传递 group、parameters 与 automation capability。 |

`src/app/model_registry.py` 不需要改变：它已只加载 `src.foundation.models.all_models` 作为 foundation model registry。不得在 app API 或前端加入表名、字段白名单或 dataset key 特例。

## 6. Ops、API 与前端

### 6.1 Catalog 与手动任务

在 `OPS_DATASET_DEFAULT_VIEW` 新增：

- `DatasetCatalogGroup("public_fund", "公募基金", 8)`，紧接现有 `ETF基金`；现有 group order 8–13 顺延一位，保持唯一且用户可预期的目录顺序。
- `DatasetCatalogItem("fund_company", "public_fund", 10)`。
- `DatasetCatalogItem("mkt_idx_bmk", "public_fund", 20)`。

Catalog resolver 已对所有 registry dataset 强制要求显式项目，缺失会失败；这正是本批不需要前端白名单的原因。手动任务 API 会从 Definition 生成两个无时间、无 filters 的 action；UI 只显示动作选择与提交，不显示日期、`ts_code`、`BMK_TYPE` 或分页参数。

### 6.2 自动任务与 probe

两 action 的 `snapshot_run_trace` freshness 会走现有 `ScheduleAutomationCapabilityResolver._schedule_only_capability()`：

```json
{
  "default_trigger_mode": "schedule",
  "trigger_options": [{"mode": "schedule", "allowed_schedule_types": ["cron", "once"]}],
  "probe_conditions": []
}
```

因此不改 `schedule_automation_capability_resolver.py`、不加 remote probe service、不建 `ProbeRule`、不放入 workflow。B1 只提供可配置的普通 schedule；不在 migration 或部署时自动创建一个 schedule。运营在 B1 最小真实同步与对账通过后，按既有页面配置 cron/once 时间，系统默认不可编辑的 capability 保证其不能切到 probe。

日期完整性页面会把本批归为“不支持审计”，这是 `audit_applicable=false` 的正确语义，不表示不能手动或定时刷新。

## 7. 对账、验收与测试

### 7.1 最小真实同步对账

已在本地隔离 PostgreSQL 验证库执行：先迁移到 B1 前一版本，验证缺失 `gs_raw_cold_hdd` 时迁移失败且四张 B1 表均未创建；再创建该临时 tablespace 后应用 B1 migration。随后每个 dataset 各执行一个完整 snapshot unit 的真实同步。第一轮结果为：

| 指标 | `fund_company` | `mkt_idx_bmk` |
| --- | ---:| ---:|
| 源端/分页并集行数 | 204 | 141 |
| 归一化接受行数 | 204 | 141 |
| writer `rows_written` | 204 | 141 |
| 拒绝行与 reason code | 0 | 0 |
| current 唯一源记录数 | 204 | 141 |
| observation 唯一版本数（首次） | 204 | 141 |
| distinct entity key | 203 | 141 |

第二次同源快照的隔离验证结果：两项均仍为相同的 source/normalized/written 行数；observation 总数分别仍为 204/141；全部 observation 行的 `first_observed_at < last_observed_at`；全部 current 行的 `observed_at` 已晚于相同键 observation 的 `first_observed_at`。定向 fixture 另证明内容变化后旧 observation 仍在、current 只保留新内容。

物理 placement 验证结果：4 张表、4 个主键索引和 4 个二级索引（共 12 个 relation）均位于 `gs_raw_cold_hdd`；集群 WAL 未改动，仍由默认 SSD 路径承担。整个验证库位于本机临时 PostgreSQL 实例，不是远程或生产数据库。

这些是当前 2026-08-05 样本证据，不是永久行数 SLA；正式验收按当次源端分页基线对账，不能把 204/141 写死成成功条件。

### 7.2 自动化测试清单

| 层 | 必测项 |
| --- | --- |
| Source contract | 默认字段与 explicit fields 的差异；分页 offsets、短页结束、完整分页并集等于无参基线；`mkt_idx_bmk` 的两种源筛选只作为实测，不进入 Definition 输入。 |
| Definition/resolver | `none` 时间、一个 unit、`offset_limit=64`、全部 `source_fields`、无 filters、`snapshot_run_trace`。 |
| Normalization/identity | 155/49 两类基金公司身份、同信用代码双变体、无身份字段的 content fallback；基准空 `ts_code` 整 unit fail。 |
| B0 writer/DAO | 全字段 hash、当前/观察双表、重复同步、版本变化、空快照、partial reject、完全重复源行和 rollback。 |
| Migration | 四表、约束、HDD 表/索引 placement；tablespace 缺失 fail-closed；ORM metadata 与 DDL 一致。 |
| Ops backend | Catalog group/order/items、manual action 无日期/filters、schedule-only capability、probe 创建请求被拒绝。 |
| Frontend contract | 不修改生产 JSX/TS，也不新增 dataset-key 前端白名单；后端 API 回归验证 catalog、无时间 action 与 schedule-only capability。浏览器已启动本仓库 `frontend/` 并到达登录页（无前端 console warning/error）；因本轮无登录授权，不提交凭据或创建任务。 |

实现验证已运行 B1/registry 69 项、B0/source-client/action-resolver/架构 167 项、Ops API 120 项、Definition lint、文档完整性和 `git diff --check`。本批没有前端源码改动，因此不把前端 typecheck/test/build 作为 B1 代码门禁。最小真实同步已在隔离验证库完成五段对账；生产迁移与首次真实同步的验收事实见下一节。B1 仍未启用 schedule。

### 7.1.1 生产首次完整同步与五段对账（2026-08-05）

生产发布已将数据库推进到 migration `20260805_000125`。运营管理员以既有 Manual Action → TaskRun 主链创建两个无时间、无 filters 的完整快照任务；未走旧 CLI 直连同步，未使用 probe、workflow 或 schedule。

| 数据集 | TaskRun | 分页证据 | 源端 fetched | 归一化接受 | 写入 | reject / reason | current / observation 实际行数 |
| --- | ---:| --- | ---:| ---:| ---:| --- | --- |
| `fund_company` | `#7401` | `page_limit=64`、short page 终止；`64 + 64 + 64 + 12` | 204 | 204 | 204 | 0 / `{}` | 204 / 204 |
| `mkt_idx_bmk` | `#7402` | `page_limit=64`、short page 终止；`64 + 64 + 13` | 141 | 141 | 141 | 0 / `{}` | 141 / 141 |

两项 TaskRun 均为 `success`，`unit_total=unit_done=1`、`unit_failed=0`，且 plan snapshot 显示 `snapshot_refresh`、一个 `none` unit、`request_params={}`。两对 current/observation 的 `(source_entity_key, source_content_hash)` 集合双向差集均为 0。`fund_company` 有 204 条源记录、203 个实体键，证明同一信用代码的不同 source-content 变体没有被合并或丢弃。四张实际写入表仍全部位于 `gs_raw_cold_hdd`。

这只是当次生产源端基线，不将 204/141 固化为未来同步的成功阈值；后续完整快照仍以当次 fetched、accepted、written、reject 与两表行数五段对账为准。

## 8. 风险与拒绝策略

| 风险 | 拒绝/控制策略 |
| --- | --- |
| MCP schema 漏列分页导致漏页 | Definition 固定 `offset_limit=64`；项目 HTTP 实测已有分页基线；无最大页数，短页才结束。 |
| 显式字段未来被源端遗漏 | hash 前严格检查全字段存在，整 unit 失败，不部分更新。 |
| 信用代码同码多行被 current 表吞掉 | primary key 含内容 hash；同实体不同源内容并存为当前源记录变体。 |
| 空信用代码误把不同公司合并 | 仅 `name+setup_date` 回退；再缺失则 content fallback，不做跨记录推断。 |
| 局部 source filter 使 current 失真 | Definition/API/UI 全部不暴露过滤器。 |
| 空/部分结果覆盖当前状态 | B0 对空 snapshot、任何 normalization reject、完全重复源记录均 fail-closed；事务 rollback。 |
| HDD tablespace 不存在而悄悄落 SSD | migration 强校验并失败；不采用 fallback。 |
| 手动/定时误变 probe | 后端 capability 返回 schedule-only，前端只渲染 contract，创建时后端再次校验。 |

## 9. B1 开工与完成门禁

开工前必须满足：B0 已实现并通过测试；当前 Alembic head 已确认；HDD tablespace 只读验证通过；本 LLD 及两份源文档的分页事实无冲突。

完成结果：四表迁移的 fail-closed/HDD placement 已在隔离验证库及生产验证；两条 Definition、ORM/DAO、Catalog/API contract 均通过测试；隔离两次真实小快照与生产首次完整同步五段对账均已闭环；没有自动创建 schedule/probe/workflow，也没有新增 user-facing API 或跨表文本关联。下一步只有在运营明确给出频率与 cron/once 意图后，才手工创建普通 schedule。
