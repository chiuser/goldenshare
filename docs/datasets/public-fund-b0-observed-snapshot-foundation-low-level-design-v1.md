# 公募基金 B0：观察快照直出最小地基 LLD v1

状态：**实现完成，B0 定向单元/SQLite 事务集成验证通过；已由 B1 在生产完成迁移与两项首次完整快照验收。B0 自身不单独创建业务表、任务或排程。**
日期：2026-08-05
上游总览：[公募基金九数据集接入总览与分批推进计划 v1](public-fund-nine-dataset-onboarding-program-plan-v1.md)
首个消费者：B1 `fund_company`、`mkt_idx_bmk`；已确认的后续消费者：B2 `fund_basic`

## 1. 目标、非目标与结论

### 1.1 目标

为“来源一次给出完整无时间快照、需要保留当前源记录和接入后观察版本”的数据集，补一个**不带任何基金业务语义**的 foundation 写入协议。它必须做到：

1. 每次成功完整快照都把所有显式 `source_fields` 原样保留在 direct-serving 表中；不另建 raw 表。
2. 当前表只保存“本次完整源快照中出现的源记录”；观察表保留从接入日开始出现过的内容版本，绝不伪称为源端生效历史。
3. 身份推断完全由数据集归一化层提供；共享 writer 不认识 `credit_code`、`ts_code`、基金名称、市场或日期字段。
4. 同一执行 unit 的历史写入、当前快照替换和状态翻转在 executor 已有的**一次事务**中完成；任何失败回滚，不留下半个当前快照。

### 1.2 不做什么

本批明确不做下列事项，它们不具备“无业务语义、至少两个已确认消费者”的共享条件：

| 不纳入 B0 的内容 | 留在何处 | 原因 |
| --- | --- | --- |
| HDD tablespace、表/索引/分区 DDL | B1 各表迁移 | 是物理存储要求，不是运行时共享能力；不同数据集的分区和容量需求不同。 |
| `公募基金` Catalog 分组、排序、手动/定时/no-probe | B1 Ops 配置 | 已有 Catalog/API capability contract；新增项目只是显式条目，不应在 foundation 硬编码。 |
| `limit/offset` 取页、页大小、页流式写入 | B1 请求契约；B7 流式写入 | B1 可复用现有分页；B7 的“边取边写”会改变 executor 边界，不能偷渡进 B0。 |
| `credit_code`、空信用代码回退、`ts_code`、基准文本关系 | B1 归一化/模型 | 都是源业务事实，放入共享层会让后续数据集被基金规则绑死。 |
| 自然日展开、相对时间、活动 unit 租约 | B4/B5 | B1 的时间模型为 `none`，没有消费者证明这些能力应提前实现。 |
| 原始 payload、通用 JSON/EAV 表、跨表文本关联、用户侧查询 API | 不做 | 会牺牲显式列、直接服务语义或扩大本批范围。 |

### 1.3 审计结论

当前实现已有 `serving_direct_upsert`，但它只向一个 `core_dao_name` 做覆盖式 upsert，不能保存观察版本；`DatasetStorageDefinition` 也没有第二张观察表的声明。`BaseDAO.bulk_upsert` 会更新全部非冲突列，不能保证观察表的 `first_observed_at` 在冲突时保持不变。因此不能把 B1 直接塞进已有路径，也不能用两个基金专用 writer 绕开问题。

保留一个最小共享能力是合理的：B1 两个数据集和已确认的 B2 `fund_basic` 都需要“完整快照 + 当前源记录 + 内容观察历史”，而协议只依赖固定元数据列、显式字段列表和数据集提供的 `source_entity_key`。除此以外的原 B0 设想全部移出。

## 2. 已审计事实与边界

| 事实 | 当前代码证据 | B0 决策 |
| --- | --- | --- |
| Definition 是数据集事实源 | `src/foundation/datasets/models.py`、`definitions/_builder.py` | 新能力由 Definition 显式声明，不能靠 dataset key 分支。 |
| 计划会固化 source fields、分页、写入目标 | `src/foundation/ingestion/resolver.py` | 增加观察表声明到计划快照，避免 TaskRun 只看到一半写入契约。 |
| source client 在 `offset_limit` 时先累积所有页，短页结束 | `src/foundation/ingestion/source_client.py` | B0 不改变取页/内存行为；B1 数据量小，B7 另行解决流式写入。 |
| executor 在 writer 成功后才 `session.commit()`，异常时 `rollback()` | `src/foundation/ingestion/executor.py` | 当前/观察两表必须只在 writer 内发 SQL，不自行 commit。 |
| Catalog group 缺失会由 resolver 报错 | `src/ops/catalog/dataset_catalog_view_resolver.py` | B1 补显式 Catalog；B0 不改 Ops。 |
| schedule capability 对非连续 freshness 数据集自动返回 schedule-only | `src/ops/services/schedule_automation_capability_resolver.py` | B1 使用既有 capability；B0 不增加 probe 白名单或前端 condition。 |

依赖方向保持为：`foundation datasets / ingestion / dao -> foundation models`。B0 不导入 `ops`、`biz`、`app`；Ops 仅作为既有执行上下文和观测消费者。

## 3. 共享契约

### 3.1 新写入路径

新增唯一写入路径：`serving_observed_snapshot_refresh`。

它只适用于同时满足下列前提的 Definition：

1. `date_model.input_shape == "none"`、`window_mode == "none"`、`audit_applicable == false`。
2. 一个 action 只规划一个完整 snapshot unit；不可用于对象池 fan-out、日期区间或局部筛选。
3. `storage.raw_dao_name is None`、`raw_table is None`、`std_table is None`，交付为 direct-serving。
4. `storage.core_dao_name` 指向当前快照 DAO；新增 `storage.observation_dao_name` 和 `storage.observation_table` 指向观察历史 DAO/表。
5. 归一化后的每行均含非空 `source_entity_key`；全部 `source.source_fields` 均存在（值可以是 `null`）。
6. 当前表和观察表都使用固定复合键：`(source_entity_key, source_content_hash)`。

`DatasetStorageDefinition` 增加两个可选字段：

```python
observation_dao_name: str | None = None
observation_table: str | None = None
```

仅当 `write_path == "serving_observed_snapshot_refresh"` 时 builder 强制二者非空，并强制 `raw_dao_name/raw_table/std_table` 为空。`PlanWriting` 同步增加只读快照字段，记录观察 DAO 和观察表；已有路径采用 `None`，不改变既有构造调用。

### 3.2 固定元数据列与哈希

下列元数据列是共享协议，而非业务字段：

| 列 | 含义 |
| --- | --- |
| `source_entity_key` | 数据集归一化层提供的稳定实体键；writer 不推断它。 |
| `source_content_hash` | 对**按 Definition 顺序的全部 `source_fields`**做含空值、类型稳定的规范 JSON 序列化后计算 SHA-256。不得混入抓取时间、分页参数或内部元数据。 |
| `first_observed_at` | observation 表中，该实体键 + 内容散列首次被本系统观察到的 UTC 时间。 |
| `last_observed_at` | observation 表中，该实体键 + 内容散列最近一次被本系统成功观察到的 UTC 时间。 |

所有 current/observation 表都有 `source_entity_key`、`source_content_hash` 和数据集声明的全部 source fields。current 表以 `observed_at TIMESTAMPTZ NOT NULL` 代替首次/末次观察列：它表示这条记录由最近一次**成功且非空的完整源快照**观察到的时间，不表示机构存续、基金存续或指数发布状态。

哈希由一个纯 foundation helper 按固定序列化规则计算；哈希前必须验证每个显式 `source_field` 都在行中。字段缺失不是“可省略”，而是 `write.source_field_missing`，整 unit 失败；字段值为 `null` 会参与哈希，保证“空值”和“未请求字段”不会混淆。数据集若在归一化阶段需要“内容散列回退身份”，只能复用这个纯 helper，writer 仍会独立重算并以自身结果为准。

### 3.3 写入算法与事务

writer 对一个完整 normalized batch 的顺序如下：

1. 若 `batch.rows_rejected > 0`、无归一化行，或任一行缺少共享协议字段，抛出结构化错误；不接触业务表。
2. 计算内容散列。若同一 batch 出现完全相同的 `(source_entity_key, source_content_hash)`，以 `write.snapshot_duplicate_record` 失败，不能静默去重丢失源端行的多重性。
3. 观察 DAO 对每个键执行“插入新版本；冲突时仅更新 `last_observed_at`”，永不改写首次观察时间或历史源字段。
4. 当前 DAO 在同一 session 内只对该数据集的 current 表执行一次有界 replace：删除旧 current projection，再插入本次完整快照中的全部版本并写入 `observed_at`。删除的只是可再生 current projection；所有源字段和历史版本已由上一步保存在 observation 表。若后续失败，executor rollback 会恢复旧 current projection。
5. 返回的 `WriteResult.rows_written` 等于本次持久化的唯一源记录数，而不是两张表的物理 DML 行数。这样 TaskRun 的 `rows_saved` 能与 fetched/normalized 行数对账。
6. executor 在 writer 返回后统一 commit；任一步异常由 executor rollback，旧 `is_current` 状态和观察历史均保持不变。

当前表是最近一次完整源快照的精确投影；observation 表是版本事实表。同步只会删除可再生 current projection，绝不删除 observation 记录。这样既能直接查询当前源快照，也不会因源端撤回或短暂异常丢失已保存事实。

### 3.4 DAO 的最小职责

新增 `ObservedSnapshotDAO`（或等价的两个无业务语义 DAO）只封装上述两种 SQL：

- `record_observations(rows, observed_at)`：冲突更新仅限 `last_observed_at`/`updated_at`，并返回新版本数与已观察数。
- `replace_current_snapshot(rows, observed_at)`：在调用方事务内仅替换该 current 表的完整 projection；不得 commit，也不得触及 observation 表。

它不能接收 dataset key、不能根据字段名决定身份、不能读写 Ops 状态、不能跨多个数据集表。各数据集仍在 `DAOFactory` 中明确注册各自 model 的 DAO，防止反射式“任意表写入”。

## 4. 代码落点与消费者审计

| 层 | 计划文件 | B0 责任 | 现有消费者/回归范围 |
| --- | --- | --- | --- |
| Definition contract | `src/foundation/datasets/models.py`、`definitions/_builder.py` | 新增并校验观察表声明 | registry、resolver、catalog projection、snapshot rebuild、测试中的手工 Definition 构造。 |
| Plan snapshot | `src/foundation/ingestion/execution_plan.py`、`resolver.py` | 将观察表写入不可变执行计划 | TaskRun plan snapshot、`tests/test_dataset_action_resolver.py`。 |
| Writer dispatch | `src/foundation/ingestion/writer.py`、`src/foundation/ingestion/observed_snapshot.py`（新增纯哈希 helper） | 新路径、强制完整快照、哈希和两 DAO 调用 | `IngestionExecutor` 是唯一写入调用方；既有路径必须原样回归。 |
| DAO | `src/foundation/dao/observed_snapshot_dao.py`（新增） | 有选择地更新观察时间、当前快照状态 | 不改 `BaseDAO.bulk_upsert` 语义，避免影响所有既有 upsert。 |
| 模型/迁移 | **B0 不新增** | 无业务表、无 migration | B1 在自己的迁移创建具体表。 |
| Ops/API/前端 | **B0 不改** | 无 group、无 schedule、无 probe、无组件 | B1 从既有 Catalog capability contract 接入。 |

这不是“为共享而共享”：B0 只引入一个固定的数据库写入协议；所有业务主键、字段、表、显示和调度仍分别属于 B1/B2。

## 5. B0 测试与负向门禁

| 测试 | 正向证明 | 负向证明 |
| --- | --- | --- |
| Definition builder/registry | 合法观察快照 Definition 能构建，计划同时带 current/observation 目标 | 少 observation DAO/表、带 raw 表、非 `none` 时间模型或错误键即拒绝。 |
| Writer 单元测试 | 同一实体内容变化产生两个观察版本；重复同步不新增版本但移动 `last_observed_at`；current 精确等于最新完整快照 | 缺 `source_entity_key`、缺显式字段、空快照、partial reject、完全重复源记录均整 unit 失败。 |
| DAO 事务测试 | current + observation 在一次 commit 后同时可见 | 在 current replace 后注入异常，rollback 后旧 current projection 和历史行不变。 |
| Resolver 回归 | 既有 `serving_direct_upsert`、`raw_core_upsert` 和 no-time plan 仍使用原字段 | 既有 Definition 未配置 observation 字段时计划序列化和 writer 均不进入新路径。 |
| 静态边界 | foundation 不 import `ops`/`biz`/`app` | 不允许 DatasetWriter 按 `fund_company`、`mkt_idx_bmk` 等 key 分支。 |

实现记录（2026-08-05）：

- 已实现 `src/foundation/ingestion/observed_snapshot.py`、`src/foundation/dao/observed_snapshot_dao.py` 及 writer/Definition/plan/linter 接线；未新增业务模型、DAOFactory 条目或迁移。
- `tests/test_observed_snapshot_foundation.py` 覆盖内容哈希、Definition/plan 契约、完整快照 current/observation 行为、所有禁止的部分写入路径，以及 executor 回滚后的真实 SQLite 表状态。
- 已通过对应 pytest 定向集、Definition lint、架构依赖守卫、代码本守卫、文档完整性和 `git diff --check`。B1 真实同步前仍必须执行 B1 的 source/normalization/write/rejection/target 五段对账。

## 6. 配置、性能与运维口径

| 项目 | 决策 |
| --- | --- |
| 新环境变量/数据库配置 | 无。 |
| page limit/调度时间 | 不属于 B0；由各 DatasetDefinition 与既有 Ops Schedule 保存。 |
| 事务 | 复用 executor 的 unit 事务；DAO 不 commit。 |
| 内存 | B0 不改变 source client 的全页累积；只允许小型完整快照消费者。B7 的页流式写入另行设计。 |
| Ops 状态 | TaskRun 继续只写意图与观测；状态写失败不得回滚业务表，遵循现有隔离边界。 |
| HDD/WAL | B0 不触碰。具体表的 tablespace 在 B1 migration 强制验证；PostgreSQL 集群 WAL 仍在现有 SSD。 |

## 7. B0 退出条件

1. ✅ 共享 writer 的正反向测试全部通过，且没有 dataset-key 特例。
2. ✅ Definition/plan 的既有消费者审计完成；Catalog、manual、schedule、workflow、freshness、date-completeness、snapshot rebuild 和前端 API consumer 均确认无需 B0 改造。
3. ✅ 未提前创建模型、迁移、业务表、自动任务、probe 或远程写入。
4. ⏳ 业务评审仍须确认“当前源记录”是源快照成员语义，不是源端生效历史或业务实体唯一记录；该语义已按本 LLD 实现。

通过 B0 代码与测试门禁后，B1 才能创建两组实际表并接入 Ops；B1 不得把尚未实现的 B0 路径改写为两套基金专用 writer。
