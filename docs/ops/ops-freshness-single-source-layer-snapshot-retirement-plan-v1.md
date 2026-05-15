# Ops Freshness 单一事实源与分层观测退场计划 v1

状态：已完成

## 1. 本轮目标

把数据集健康度收敛为一套事实源：

1. 数据集状态只以 `DatasetDefinition.date_model + 真实业务表观测 + TaskRun 成功/失败信息` 计算。
2. `/api/v1/ops/freshness` 与 `/api/v1/ops/dataset-cards` 必须消费同一套 freshness 事实。
3. `raw/std/serving/light` 不再作为独立健康度观测层，不再驱动页面主状态。
4. 旧分层观测表、旧分层观测 API、dataset card 旧分层字段最终退场。

## 2. 硬边界

1. 不引入兼容方案、临时方案或第二套状态口径。
2. 不新增健康度表；`dataset_status_snapshot` 只能作为 freshness 缓存。
3. 不改业务数据写入链路，不触碰 `raw_*`、`core_*`、`core_serving*` 业务表数据。
4. 不做与 freshness / 旧分层观测退场无关的页面、视觉、数据集或调度改造。
5. 每个子任务开始前必须重读本文档；遇到代码事实不清楚，先审计代码，不猜。

## 3. Step 1：Freshness 成为数据源卡片主状态

目标：先切断数据源卡片和总览页面对旧分层观测状态的依赖。

改造范围：

1. `OpsFreshnessQueryService` 统一使用 `Asia/Shanghai` 业务日期作为 reference date。
2. `build_freshness()` 读取 `dataset_status_snapshot` 时，只能用缓存中的观测事实按当前北京时间业务日轻量重算展示状态；页面查询不得同步扫描真实业务表。
3. `DatasetCardQueryService` 的 `status/freshness_status/latest_business_date/last_sync_date/expected_business_date/lag_days` 只来自 freshness item，不再用旧分层观测或页面自行拼装。
4. 数据源页文案从“raw 状态”改为“数据集状态”，避免暗示旧原始层快照是独立事实。
5. Step 1 不新增兼容行为，Step 2 统一删除旧分层观测链路。
6. 真实业务表观测只能在 `ops-rebuild-dataset-status` 或任务完成后的资源刷新链路中执行，不能放进 `/ops/freshness`、`/ops/overview`、`/ops/dataset-cards` 页面请求路径。

验收：

1. `dc_hot/kpl_list/ths_hot` 在相同业务日期、相同最新业务日下状态一致。
2. UTC 与 Asia/Shanghai 跨日时不会产生 freshness 漂移。
3. `/api/v1/ops/freshness` 与 `/api/v1/ops/dataset-cards` 对同一数据集返回同一健康度口径。

## 4. Step 2：旧分层观测全面退场

目标：删除已经失去独立事实意义的分层观测链路。

改造范围：

1. 删除后端旧分层观测 API。
2. 删除后端旧分层观测 query/schema/model。
3. `DatasetStatusSnapshotService` 只写 freshness 缓存，不再写旧分层观测 current/history，也不再写四个分层状态列。
4. 数据集卡片契约删除来自旧分层观测的分层字段与更新时间字段。
5. 前端删除“全链路层级状态”“数据来源状态”“快照样本”和旧分层观测请求。
6. 探测规则删除依赖旧分层 rows 的行数阈值条件。
7. 新增 Alembic 迁移前必须先查真实 head；迁移删除两张旧分层观测表和 `dataset_status_snapshot` 四个分层状态列。

验收：

1. 当前代码和当前文档中不再把旧分层观测表、API 或字段作为现行口径。
2. 数据源页、数据状态总览、数据集详情页仍能正常展示 freshness、任务记录和调度覆盖。
3. `ops-rebuild-dataset-status` 只重建 freshness cache，不再产生旧分层观测行。

执行结果：

1. 旧分层观测 API、query、schema、model、router 注册、model registry 注册已删除。
2. `DatasetStatusSnapshotService` 只维护 freshness cache；迁移 `20260515_000107` 删除旧分层观测表和四个旧分层状态列。
3. 前端数据源页、数据状态总览页、数据集详情页不再请求旧分层观测 API，也不再展示旧分层字段。
4. 探测规则不再支持依赖旧分层行数的条件。
5. 修正页面请求卡顿问题：混合 `snapshot_date` 不再导致查询层放弃缓存并 live 扫描全量业务表。

## 5. 每轮开始前检查

1. 重读根 `AGENTS.md`、目标目录 `AGENTS.md` 和本文档。
2. 先 `rg` 审计引用，再改代码。
3. 删除契约前确认消费者清零。
4. 改完必须跑对应后端测试、前端类型/测试/构建，以及文档检查。
