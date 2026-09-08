# Foundation 当前强约束（统一基线）

更新时间：2026-09-08（校准文档口径，不变更现行代码、字段或存储）

## 1. 文档定位

本文件是 Foundation 研发规则的**统一基线**，用于替代分散在多份文档中的重复约束。

下文数据集接入、落库和 TaskRun 要求适用于 `DatasetDefinition / Ingestion / Ops TaskRun` 主线的 Prod 数据集。本地 DG 数据湖使用其[接入模板](/Users/congming/github/goldenshare/lake_console/docs/templates/dagster-dataset-onboarding-template.html)和目录规则，不套用本文件的数据库分层、ORM 或 TaskRun 要求。

当以下文档出现描述冲突时，以本文件为准：

1. `dataset-publish-governance-spec-v1.md`
2. `foundation-onboarding-and-legacy-checklist-v1.md`

---

## 2. 强约束总览（必须遵守）

1. 子系统边界以 [subsystem-boundary-plan.md](/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md) 为准。
2. 依赖方向以 [dependency-matrix.md](/Users/congming/github/goldenshare/docs/architecture/dependency-matrix.md) 为准。
3. Ops 状态语义以 [ops-contract-current.md](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md) 为准。
4. 数据集事实以 `src/foundation/datasets/**` 的 `DatasetDefinition` 为准。
5. 数据维护执行计划以 `src/foundation/ingestion/**` 的 `DatasetExecutionPlan` 为准。

---

## 3. Foundation 分层与数据路径

### 3.1 默认分层

1. `core_serving`：对上业务契约层（当前主读口径）。
2. `raw_<source>`：需要保留源站原始事实、审计或重放时使用；不是所有数据集的强制前置层。
3. `core_serving_light`：高频查询性能层（可选，不替代 `core_serving`）。
4. 经正式设计批准的 direct-serving 数据集可以从源端直接写入 `core_serving`；不得为了形式完整伪造空 raw 表、影子 DAO 或双写兼容层。

### 3.2 交付、数据路径与写入方式分开说明

当前存储合同以 [DatasetStorageDefinition](/Users/congming/github/goldenshare/src/foundation/datasets/models.py) 为准，不能用旧模式分类代替实际字段：

| 字段 | 说明 |
| --- | --- |
| `storage.delivery_mode` | 数据集的交付方式，与实际查询消费者对账。 |
| `storage.layer_plan` | 数据经过哪些层，以及 Serving 是物理表还是视图。 |
| `storage.write_path` | 执行器采用的写入策略，不等于对外查询方式。 |

例如 [stk_factor_pro 定义](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_equity.py) 使用 `delivery_mode=single_source_serving`、`layer_plan=raw->serving_view`、`write_path=raw_only_upsert`：只写 Raw，通过 Serving 视图提供查询。因此，“只写 Raw”不能推导为“不对外服务”，也不能为视图额外建立写入链路。

具体取值按当前 definition、builder/linter 和 writer 核验；设计填写[数据集模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)第 4、5 节。`single_source_direct`、`multi_source_pipeline`、`legacy_core_direct` 等旧模式名不再作为本文的配置分类；既有 `core.*` 保留范围仍遵守下一节，不因措辞更新扩展。

### 3.3 新增能力约束

1. 新增“对外服务”数据集，默认落 `core_serving.*`。
2. 不允许新增 `core.*` 直写主路径（除已明确保留项）。
3. 仅当存在高频性能瓶颈时才引入 `core_serving_light.*`。

---

## 4. 同步链路约束

1. 同步主流程必须可观测、可重放、可恢复。
2. 时间输入能力必须由 `DatasetDefinition.date_model` 与源接口真实行为决定；允许 point、range、month、no-time snapshot 等不同模型，不要求所有数据集同时支持单时间点和时间区间。
3. 分页接口必须内部自动循环，不把分页细节暴露为运营常规参数。
4. 同步任务通过 Ops TaskRun 观测执行，freshness 按数据集已登记的策略判断；交付与写入事实来自 `DatasetDefinition.storage`，不要求另建 `pipeline_mode` 字段。
5. 旧执行路由不再作为当前用户任务、API 或长期领域模型。
6. Prod 长任务识别及执行合同统一遵守[根 AGENTS](/Users/congming/github/goldenshare/AGENTS.md#prod-数据集长任务可恢复性与可观测性门禁)与[数据集模板 0.3.5](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)：预计或实测超过 60 秒，或规模会随日期、对象、分页、分区增长且无法静态约束时，必须按长任务设计；不能省略“无法静态约束”的限定。DG/Lake 不适用这套 Prod 合同。

---

## 5. 数据集交付门禁（DoD）

适用范围内的数据集交付时必须同时满足以下条件。开工前完成事实核验、设计与验收计划，实现和获准执行后再补实际证据，不能要求先执行正式写入来填开工材料：

1. 有按 [数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md) 完整填写的独立数据集开发文档（`docs/datasets/*`）。
2. DatasetDefinition 中的身份、中文名、来源、日期模型、输入能力与表映射明确。
3. 落库路径与目标表明确（raw/serving/light）。
4. 幂等写入与去重策略明确。
5. Ops 交互与状态观测已接入。
6. DatasetExecutionPlan 能覆盖对应维护动作。
7. 测试清单完整（单元/集成/回归）。
8. 长任务已完成内存、持久化、续跑、进度、取消、终态一致以及既有执行入口／并发影响的设计与真实最小验收；不得仅因任务耗时较长就默认新增 Worker 或 lane，非长任务已记录不适用依据。

模板入口：

1. [dataset-development-template.md](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)
2. [workflow-development-template.md](/Users/congming/github/goldenshare/docs/templates/workflow-development-template.md)

---

## 6. 数值类型与表结构约束

1. 按字段语义、取值范围和精度选型：计数使用适当整数类型，精确十进制使用 `NUMERIC`，允许近似计算时可使用 `DOUBLE PRECISION`；不统一默认浮点。说明要求见[数据集模板 §5.2](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md#52-工程硬约束)，同类字段可合并说明。
2. 已有字段继续遵守现行 Schema 和消费契约，不因文档校准批量修改类型、Normalizer 或历史数据；确需变更时另行审计影响并获得确认。
3. 存在 `trade_date` 的大表默认按时间分区（年或月，需说明理由）。
4. 主键、唯一键和冲突键必须从源端真实身份与业务语义推导；`(ts_code, trade_date)` 只能作为候选，不能作为默认答案。`freq/category/type/market/hot_type/is_new` 等身份字段必须通过真实样本决定是否入键。
5. 只有存在日期驱动读写路径时才要求对应日期索引；索引字段和顺序必须由真实查询、同步范围与表规模决定。

---

## 7. 按改动类型选择验收

| 改动类型 | 验证范围 |
| --- | --- |
| 仅文档 | 在仓库根使用现有环境运行 `.venv/bin/python3 -B scripts/check_docs_integrity.py`、`git diff --check`；另核验新增引用和锚点。不要求访问 Web、数据库或执行数据任务。 |
| Foundation 代码、存储或合同 | 按影响面选择单元/隔离集成测试；边界与执行主链护栏见[依赖矩阵 §3](/Users/congming/github/goldenshare/docs/architecture/dependency-matrix.md#3-护栏测试清单现行)。数据集验收按模板分阶段执行，静态通过不能代替真实数据验收。 |
| 获准部署或运行验证 | 先明确环境、权限和范围，再按任务需要检查 Web 健康及 Ops 可见性；不因文档列出接口而自动获得服务访问或部署授权。 |

现行 Web 健康接口为 `GET /api/health`、`GET /api/v1/health`，内部会执行数据库查询。Ops 的 `/api/v1/ops/dataset-cards`、`/api/v1/ops/freshness` 需要管理员身份和数据库访问。这些接口仍有效，但不是文档静态检查，也不能单独证明数据集正确。

验证使用现有环境；缺依赖时报告，不自动安装。交付时分别记录文档检查、隔离测试和获准正式验证的实际结果。

---

## 8. 文档协作规则

1. 本文件维护“当前强约束”；专题文档维护“领域细节”。
2. 任何变更先改文档，再改代码。
3. 若专题文档与本文件不一致，先修正文档再继续开发。
