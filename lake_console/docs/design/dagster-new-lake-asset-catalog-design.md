# Dagster 新湖 Asset Catalog 设计方案

更新时间：2026-06-07

C1 review / 落地口径文档：`dagster-new-lake-asset-catalog-c1-review.html`。

## 1. 结论

新湖需要做 Asset Catalog，但目标不是升级旧湖控制台的 `lake_console/backend` catalog，也不是让旧湖和新湖长期共享同一套模型。

本方案建议在 `lake_console/orchestrator` 内新增只读的新湖资产注册表，用来收敛 Dagster assets、checks、sensors、bootstrap、repair、event backfill 共同依赖的资产事实。

C1 已按该口径落地为 `orchestrator.defs.catalog.lake_assets`：只做代码内 registry 和 static gates，不新增数据库、不新增 UI、不新增配置项、不改变现有 asset/job/sensor/check 语义。

## 2. 背景

当前存在三类系统口径：

| 名称 | 目录 | 定位 |
|---|---|---|
| 旧湖控制台 | `lake_console/backend`、`lake_console/frontend` | 本地旧湖文件扫描、旧 Lake catalog、Sync Center、Recovery 页面 |
| 新湖 Dagster | `lake_console/orchestrator` | 正式 Dagster assets/checks/jobs/sensors/resources，目标路径为 `data_lake/raw`、`data_lake/silver`、`data_lake/gold` |
| 数据基座 | `src/foundation/datasets`、`src/foundation/ingestion` | 生产主系统成熟的数据集事实源和执行计划模型 |

旧湖控制台会逐步退场，`lake_console/backend` 的 catalog 不应继续升级为长期事实源。新湖后续仍会持续接入来自 Tushare、prod DB 和旧湖未迁移数据的数据集，因此需要在新湖内部建立稳定资产事实模型。

## 3. 当前现状审计

### 3.1 新湖事实已经分散

当前新湖资产事实分别位于：

| 事实 | 当前位置 |
|---|---|
| 路径模板 | `orchestrator.defs.paths` |
| 字段契约 | `orchestrator.defs.run_contracts.asset_column_schemas` |
| dataset 中文名 | `orchestrator.defs.catalog.name_mapping` |
| definition metadata | `orchestrator.defs.run_contracts.metadata` |
| layer/domain tags | `orchestrator.defs.run_contracts.asset_tags` |
| 分钟线频度与 source contract | `orchestrator.defs.run_contracts.stk_mins` |
| source request / prod DB select | `orchestrator.defs.tushare_api_io`、`orchestrator.defs.prod_db.*` |
| check 名称和语义 | `orchestrator.defs.checks.*` |
| sensor readiness | `orchestrator.defs.sensors.*` |
| bootstrap / runless event | `orchestrator.defs.bootstrap.*` |

这些事实目前都有测试保护，但没有统一的资产注册卡。

### 3.2 测试已经在维护“隐形 catalog”

历史上 `test_asset_governance_contracts.py` 手写 `ASSET_CONTRACTS`，用于对账 asset layer、domain、dataset_id、dataset_name。

C1 已将这张隐形 catalog 迁移为正式只读 registry；治理测试现在只保留 active Dagster asset definitions 作为 live spec 读取入口，dataset/path/schema/check 事实从 `LAKE_ASSET_CATALOG` 反查。

### 3.3 qfq 已暴露多消费者风险

`gold_stk_mins_qfq_path(...)` 当前被 asset、check、repair、bootstrap、event backfill 和测试多方消费。90/120 派生、repair、历史直写补录、runless event 已经证明：复杂数据集如果没有集中事实源，路径、频度、check、event 口径容易漂移。

### 3.4 source 语义需要拆分

以 `raw_stk_mins_*` 为例：

- 字段契约是 Tushare raw mirror。
- 日常默认来源可以是 prod DB 的 `raw_tushare.stk_mins`。
- 备用来源是 Tushare API。
- 历史初始化可来自旧湖 bootstrap。

当前 metadata 中的 `source_system=SourceSystem.TUSHARE` 表达的是字段契约来源，不足以表达实际摄取来源。Catalog 应拆开：

- `data_contract_source`
- `ingestion_sources`
- `default_daily_ingestion_source`
- `bootstrap_sources`

## 4. 旧湖 catalog 不直接继承

旧湖 `LakeDatasetDefinition` 是 UI 和文件扫描导向模型，核心字段包括 `storage_root`、`primary_layout`、`available_layouts`、`nodes`、`scan_profile`、`command_examples`。

它服务的是旧湖路径：

```text
raw_tushare/
manifest/
derived/
research/
```

新湖正式路径是：

```text
data_lake/raw/
data_lake/silver/
data_lake/gold/
```

因此旧湖 catalog 只能借鉴“定义卡 + 节点 + 分区维度”的结构经验，不能作为新湖事实源，也不能把旧湖 layer、scan profile、command examples 引入新湖 asset contract。

## 5. 数据基座代码审计与借鉴口径

本轮审计读取了数据基座当前实现，而不是只看概念名称。审计范围包括：

| 模块 | 当前职责 | 对新湖的结论 |
|---|---|---|
| `src/foundation/datasets/models.py` | `DatasetDefinition` 及 identity/source/date/input/storage/planning/normalization/quality/transaction/completeness 等事实模型 | 可借鉴字段分层和事实源口径 |
| `src/foundation/datasets/definitions/_builder.py` | 把数据集 dict row 构造成强类型 definition，并做源、存储、规划、观测、完整性校验 | 可借鉴 builder 校验和 fail-fast 规则 |
| `src/foundation/datasets/registry.py` | 只读列举和按 key 获取数据集定义 | 可借鉴 registry 作为唯一事实入口 |
| `src/foundation/datasets/freshness_policies.py` | 将 freshness/audit 策略从 dataset row 中拆成稳定策略表 | 可借鉴 freshness 口径独立建模 |
| `src/foundation/ingestion/validator.py` | 校验 action、time input、filter、enum、互斥、依赖和未知参数 | 可借鉴严格校验思想；新湖 C1 先落 static gates |
| `src/foundation/ingestion/resolver.py` | 将用户/调度意图解析成 `DatasetExecutionPlan` | 可借鉴“意图先变计划”的模式 |
| `src/foundation/ingestion/unit_planner.py`、`plan_helpers.py` | 按日期锚点、对象池、枚举扇出、分页策略生成 planned units | 可借鉴性能门禁字段；不能照搬 per-stock 单元到新湖重型批量写入 |
| `src/foundation/ingestion/request_builders.py` | 源接口参数只在 request builder 中生成 | 可借鉴 source request 隔离原则 |
| `src/foundation/ingestion/source_client.py` | 连接源适配器、分页、重试、补充查询上下文字段 | 可借鉴 source 字段显式投影和分页口径；不直接复用运行时 |
| `src/foundation/ingestion/normalizer.py` | 字段类型转换、必填字段、reject reason 和样本 | 可借鉴结构化 reject 诊断 |
| `src/foundation/ingestion/writer.py` | DAO 写入、幂等/upsert、拒绝原因、事务内业务过滤 | 不复用 DAO 写入；只借鉴 write policy 和诊断字段 |
| `src/foundation/ingestion/executor.py` | fetch、normalize、write、commit、rollback、进度聚合 | 不引入执行器；只借鉴阶段化执行和每单元提交口径 |
| `src/foundation/ingestion/service.py` | CLI/ops dispatcher 的维护入口，状态写入旁路化 | 不接入新湖 Dagster；借鉴“观测状态失败不污染业务写入” |
| `src/foundation/ingestion/linter.py`、`codebook.py` | 对 definition/runtime registry 做静态 lint，并沉淀错误码 | 可借鉴为新湖 catalog static gates 和后续 planner 错误码 |

CodeGraph 也确认了 `DatasetMaintainService.maintain` 的主要调用方是 CLI 和 `src/ops` dispatcher。它属于生产主系统维护链路，不是新湖 Dagster 的可直接依赖库。

### 5.1 可借鉴的成熟经验

| 数据基座经验 | 具体代码依据 | 新湖 catalog 落地方式 |
|---|---|---|
| Definition 是事实源，不让页面、脚本、任务各自拼事实 | `DatasetDefinition`、`list_dataset_definitions()` | 新湖建立 `LakeAssetCatalogEntry` 只读 registry，active asset/check/sensor/bootstrap 都从同一事实对账 |
| identity/domain/source/date/storage/planning/quality/transaction 分层 | `models.py` 的 dataclass 组合 | 新湖 entry 拆成 identity、asset node、storage、partition、source、quality、automation、bootstrap、event policy |
| date_model 是独立事实，不从参数名或路径猜 | `DatasetDateModel` | 新湖显式登记 `partition_model`、partition key 语义、observed field，不从 parquet path 推断 |
| input_model 不是 source request | `DatasetInputModel` + `DatasetRequestValidator` + `request_builders.py` | Dagster run config、sensor cursor、source API 参数分离；源请求只允许由专门 builder/helper 生成 |
| source fields 是字段契约 | `DatasetSourceDefinition.source_fields` | 新湖继续把 `dagster/column_schema`、raw mirror 字段、prod DB 投影字段作为稳定契约 |
| builder/linter 做 fail-fast | `_builder.py`、`lint_all_dataset_definitions()` | 新湖 C1 增加 static gates：未登记 asset、缺 schema、缺 check、路径漂移直接测试失败 |
| planner 先规划 unit，再执行 | `DatasetActionResolver`、`DatasetUnitPlanner` | C1 不做生成器；C3 可用于 bootstrap/repair/history backfill 规划，但必须保留新湖批量性能门禁 |
| 性能参数进 definition，而不是散落在脚本 | `planning.page_limit`、`fetch_concurrency`、`max_units_per_execution`、`transaction.write_volume_assessment` | 新湖 entry 记录 source request 规模、批次维度、DuckDB 写入模式、禁止 per-stock 主循环等门禁 |
| 质量与完整性单独建模 | `DatasetQualityPolicy`、`DatasetCompletenessDefinition` | 新湖 entry 记录 blocking checks、check 适用范围、derived/native check 差异 |
| 观测状态旁路化 | `DatasetMaintainService._finish_success()` 捕获状态写入异常 | 新湖 runless event/backfill/report 继续与业务文件写入分阶段，event 失败不得污染 parquet 文件 |
| 错误/拒绝原因结构化 | `IngestionCodebookEntry`、`NormalizedBatch.rejected_reasons` | 后续补录/repair planner 输出 structured reason，不用只写自由文本 |

### 5.2 不能照搬的内容

| 不继承内容 | 原因 | 新湖处理方式 |
|---|---|---|
| `src.foundation` 运行时 import | `lake_console/orchestrator` 是独立 Dagster 工程；引入主系统运行链会扩大依赖边界 | 只复制建模经验，不 import foundation 代码 |
| SQLAlchemy DAO / raw/core/serving 写库 | 新湖正式产物是 Parquet/DuckDB/Dagster event，不是生产库表 | 新湖保留 LakeRoot/DuckDB/resource/path/check 体系 |
| `DatasetMaintainService`、Ops TaskRun、dispatcher | 新湖控制面是 Dagster job/sensor/schedule | 不让新湖 sensor/job 走 Ops TaskRun |
| `source_client` 运行时重试/限流 | 新湖 Tushare/prod DB/旧湖 bootstrap 已有独立受控路径，需要单独设计权限、只读和性能门禁 | 借鉴分页与字段投影，不直接复用客户端 |
| per-stock planned unit 默认模型 | 对生产数据库维护可控，但对 qfq/分钟线 Parquet 批量写入会退化成碎循环 | 新湖重型路径必须按 freq/year/date window 批量规划 |
| UI filter/input 控件模型 | 旧湖 backend/frontend 会逐步退场；新湖 C1 不做 UI | catalog 先服务代码门禁和审计 |
| 动态 feature flag 修改 definition | `_builder.py` 对 hot market enum 有运行期变体 | 新湖 catalog 第一阶段必须是稳定只读事实，不做运行期变形 |

### 5.3 针对新湖三类未来来源的借鉴方式

| 来源 | 数据基座可借鉴点 | 新湖 catalog 应记录 | 禁止项 |
|---|---|---|---|
| Tushare | `source_fields`、`source_doc_id`、`request_builder_key`、pagination policy | `data_contract_source=tushare_raw_contract`、`source_api`、`source_doc`、`source_fields/column_schema`、`ingestion_sources=(tushare_api,)` | 不把可选源参数自动暴露成 Dagster run config；新增/修改请求仍必须查本地 Tushare 文档并实测 |
| prod DB | 明确字段投影、源适配器隔离、write volume assessment | `ingestion_sources=(prod_db_readonly,)`、白名单表/字段投影、READ_ONLY attach、批量 SQL 维度 | 不保存 host/user/password/dbname，不把连接串写进 catalog、metadata、run tags |
| 旧湖未迁移数据 | 定义卡和执行计划分离 | `bootstrap_sources=(old_lake_bootstrap,)`、bootstrap spec、允许直写/无 run event 补齐策略 | 旧湖 path/layout/scan profile 不进入正式 asset path 和 dataset 名称 |

### 5.4 对 C1/C2/C3 的具体影响

C1 只读 registry 应先借鉴数据基座的 `Definition + Builder + Registry + Linter` 四件事：

1. `LakeAssetCatalogEntry` 是唯一资产事实卡。
2. builder/static gate 对账 active definitions、metadata、tags、column schema、path template、blocking checks。
3. registry 不做 IO，不访问 Dagster instance，不扫 lake，不生成 asset。
4. 文档、tests 和 assets 不再各自维护隐形事实表。

C2 新增数据集门禁应借鉴 validator 的 strict 模式：

1. 新增正式 asset 前必须先登记 catalog entry。
2. 新增 source request 前必须明确 `data_contract_source`、`ingestion_sources`、字段投影、分区语义和性能门禁。
3. 未登记的 asset/check/bootstrap/repair 引用一律 static gate 失败。

C3 选择性消费 catalog 时，才借鉴 resolver/planner：

1. bootstrap、repair、history backfill 可以从 catalog 生成批次计划。
2. 计划必须显式写明批次维度，例如 `freq/year`、`trade_date`、`asset/freq/partition`。
3. 对分钟线、qfq、技术指标等重型路径，catalog planner 只能生成批量任务，不允许退化成 per-stock Python 明细循环。

## 6. 新湖 Catalog 第一阶段模型

第一阶段已新增只读 registry：

```text
lake_console/orchestrator/src/orchestrator/defs/catalog/lake_assets.py
```

落地模型：

```python
@dataclass(frozen=True, slots=True)
class PartitionModelDefinition:
    model: PartitionModel
    family: PartitionModelFamily
    layer: AssetLayer
    asset_family: str
    dagster_partition_dimension: str | None
    physical_layout: PartitionPhysicalLayout
    notes: str = ""


@dataclass(frozen=True, slots=True)
class LakeAssetCatalogEntry:
    asset_key: str
    dataset_id: str
    dataset_name: str
    layer: AssetLayer
    data_domain: DataDomain
    group_name: str
    source_system: SourceSystem
    data_contract: str
    data_contract_source: DataContractSource
    column_schema: tuple[ColumnContract, ...] | None
    path_template: str | None
    partition_model: PartitionModel
    source_api: str | None
    source_doc: str | None
    ingestion_sources: tuple[IngestionSource, ...]
    default_daily_ingestion_source: IngestionSource | None
    bootstrap_sources: tuple[IngestionSource, ...]
    blocking_check_names: tuple[str, ...]
    write_policy: WritePolicy
    event_policy: EventPolicy
    performance_contract: LakeAssetPerformanceContract
    notes: str = ""
```

字段解释：

| 字段 | 含义 |
|---|---|
| `asset_key` | Dagster asset key，必须与 active definition 一致 |
| `dataset_id` | 稳定 dataset id，对应 definition metadata |
| `layer` / `data_domain` | 对应 `goldenshare/layer` 和 `goldenshare/data_domain` tags |
| `data_contract_source` | 字段契约来源，例如 `tushare_raw_contract`、`derived_contract`、`seed_contract`、`prod_serving_contract` |
| `ingestion_sources` | 实际可摄取来源，例如 `tushare_api`、`prod_db_readonly`、`old_lake_bootstrap`、`derived_from_assets`、`seed_file` |
| `partition_model` | 具体 leaf 分区模型，命名采用“分区维度 + layer + 资产名/资产簇”，例如 `trade_date_partition_raw_stock_mins`；上层关系由 `PartitionModelDefinition.family` 表达 |
| `blocking_check_names` | 该 asset 正式 blocking checks 名称 |
| `write_policy` | `single_file_replace`、`partition_file_replace`、`stock_year_atomic_replace`、`clickhouse_sync` 等 |
| `event_policy` | 是否支持 runless event backfill，或只允许 Dagster run materialization |

`PartitionModel` 不再使用单层泛化名承载所有含义。C1 采用两层关系：

```text
PartitionModelFamily  高层分类，例如 full_file、trade_date_partition
PartitionModel        leaf model，例如 trade_date_partition_raw_stock_mins
PartitionModelDefinition  解释 family、layer、asset_family、Dagster 分区维度和物理布局
```

qfq 保留特例：

```text
trade_date_partition_gold_stock_mins_qfq_stock_year_file
```

该名称表达：Dagster asset 的核心分区维度是 `trade_date`，层级是 `gold`，资产簇是 `stock_mins_qfq`，但物理文件按 `stock_year_file` 写入。

## 7. 目标能力

第一阶段只支持以下能力：

1. 从 registry 对账 asset definition metadata。
2. 从 registry 对账 `dagster/column_schema`。
3. 从 registry 对账 path template。
4. 从 registry 对账 layer/domain tags。
5. 从 registry 对账 blocking checks。
6. 从 registry 输出人工审计用 inventory。
7. 替代测试中的手写 `ASSET_CONTRACTS` 大表。

第一阶段不做：

1. 不自动生成 Dagster assets。
2. 不自动生成 checks。
3. 不自动生成 jobs/sensors。
4. 不接旧湖 backend UI。
5. 不新增数据库表。
6. 不新增配置项。
7. 不改变现有 materialization metadata。
8. 不改变现有 source request builder。

## 8. 分阶段实施

### C1：只读 registry + static gates

状态：已落地。C1 只提供 registry、查询 API 和 static gates，不生成 asset/check/job/sensor，不让业务运行逻辑消费 catalog。

目标：

1. 新增新湖 asset catalog entry 模型。
2. 为当前 active assets 建立 registry。
3. static gates 验证 registry 与 active definitions 一致。
4. 治理测试从 `ASSET_CONTRACTS` 手写表迁移到 registry。

验收：

1. 所有 active table-like assets 都在 registry 中。
2. registry 中不存在 inactive asset。
3. metadata 的 `dataset_id`、`dataset_name`、`data_contract`、`path_template` 与 registry 一致。
4. tag 的 layer/domain 与 registry 一致。
5. column schema 与 registry 一致。
6. blocking check names 与 registry 一致。

### C2：新增数据集必须先登记 catalog

目标：

1. 新增数据集时，先写 registry entry。
2. assets/checks/jobs/sensors/bootstrap 只能消费已登记 asset。
3. static gates 禁止出现未登记正式 asset。

验收：

1. 新增 asset 没有 registry entry 时测试失败。
2. 新增 check 指向未登记 asset 时测试失败。
3. 新增 bootstrap/event helper 引用未登记 asset 时测试失败。

### C3：选择性消费 catalog

目标：

1. bootstrap plan、runless event、repair scope、readiness helper 可从 registry 读取资产事实。
2. 保留现有 path/schema helper 作为底层函数，不用 catalog 替代所有计算代码。
3. 不做全量生成器，避免把 registry 变成过度抽象。

验收：

1. qfq derived history/event、old lake bootstrap、prod DB raw update 的计划输入可追溯到 registry。
2. 不再在多个 helper 中重复维护同一组 asset/check 名称。

## 9. 对未来三类来源的支持方式

### 9.1 Tushare 来源

Catalog 记录：

- `data_contract_source=tushare_raw_contract`
- `ingestion_sources=(tushare_api,)`
- `source_api`
- `source_doc`
- `column_schema`
- `partition_model`

仍然要求新增或修改 Tushare 请求参数时，按仓库规则查本地 Tushare 文档并用 Tushare MCP 实测。

### 9.2 Prod DB 来源

Catalog 记录：

- `data_contract_source=tushare_raw_contract` 或 `prod_serving_contract`
- `ingestion_sources=(prod_db_readonly,)`
- prod DB 白名单表或契约模块
- READ_ONLY / 显式字段投影 / 禁止系统字段

Catalog 不保存密码、连接串、host、user、dbname，也不承载运行配置。

### 9.3 旧湖未迁移数据

Catalog 记录：

- 正式目标 asset 的 contract。
- 允许的 bootstrap source：`old_lake_bootstrap`。
- 对应 bootstrap spec 名称。

旧湖路径只能出现在 bootstrap spec 和迁移审计，不进入正式 asset path，不进入 parquet 字段，不污染 asset 名称。

## 10. 风险与边界

| 风险 | 控制方式 |
|---|---|
| catalog 变成另一套旧湖 backend catalog | 只服务 `lake_console/orchestrator`，不接旧湖 UI |
| 过早抽象导致 asset 生成器复杂化 | 第一阶段只做 registry + static gates，不生成 definitions |
| source 语义混乱 | 强制拆分 `data_contract_source` 与 `ingestion_sources` |
| 文档和代码继续漂移 | static gates 以 registry 对账 active definitions |
| 引入生产主系统运行依赖 | 只借鉴数据基座模型经验，不 import `src.foundation` |

## 11. 建议下一步

C1 已实施。它不改变 Dagster 行为，只把已经存在的散落事实登记成一张正式 registry，并用 static gates 防止后续接入 prod DB、Tushare 和旧湖迁移数据时继续漂移。

下一步再决定是否进入 C2/C3。C2/C3 应等待下一个新增数据集或 M12 技术指标资产开始前推进。
