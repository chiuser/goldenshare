# CodeGraph 架构快照

生成日期：2026-08-11
索引根：`/Users/congming/github/goldenshare`
索引结果：2,258 files，38,946 nodes，89,060 edges，DB 97.10 MB

本文是基于 CodeGraph 根索引生成的当前事实快照，不是新的重构方案。后续做架构分析、重构、依赖边界调整、共享 contract 修改、dispatcher/worker/service 修改前，应先回到 CodeGraph 做上下文和影响面分析。

## 模块分层

### 生产后端：`src/`

当前后端主结构仍按根规则收敛为：

1. `src/foundation/**`：数据基座。事实源是 `src/foundation/datasets/**` 的 `DatasetDefinition`，执行计划是 `src/foundation/ingestion/**` 的 `DatasetExecutionPlan`。源请求、normalizer、writer、DAO、模型和 serving 发布都在这一层。
2. `src/ops/**`：运维治理与 TaskRun 主链。包括 Ops API/query/service、runtime dispatcher/worker/scheduler、TaskRun 观测、manual actions、freshness、schedule、probe、dataset cards。
3. `src/biz/**`：对上业务 API 与查询服务。当前包含 quote、market、realtime，以及 `src/biz/api/wealth/**` 的财势乾坤行情系统 API。
4. `src/app/**`：组合根。`src/app/api/v1/router.py` 聚合 auth、Ops、Biz、Wealth API；`src/app/web/app.py` 是 Web 应用装配入口。
5. `src/platform/**`、`src/operations/**`：legacy 冻结目录，不承接新主实现。

### 数据运营后台：`frontend/`

`frontend` 是独立 React/Vite 运营后台前端。当前主入口在 `frontend/src/main.tsx`，应用装配在 `frontend/src/app/**`，页面集中在 `frontend/src/pages/**`。Task Center、Dataset Audit、Realtime Config/Monitor 等页面消费 Ops API，尤其依赖 `/api/v1/ops/task-runs*`、`/api/v1/ops/manual-actions*`、dataset cards、freshness、schedule 等契约。

### 财势乾坤行情系统：`wealth/`

`wealth` 是独立行情系统前端，不共享运营后台 Shell。入口为 `wealth/src/main.tsx` 与 `wealth/src/app/App.tsx`，当前通过 `AuthProvider -> WealthRouter` 装配市场总览、股票详情和指数详情。共享 API adapter 是 `wealth/src/shared/api/wealthApiClient.ts` 的 `wealthFetch`，它负责鉴权请求和 401 刷新令牌。股票与指数日线分别通过 `StockChartWorkspace -> DetailChartWorkspace`、`IndexChartWorkspace -> DetailChartWorkspace` 组合；领域 adapter 保留各自文案和数据映射，共享引擎承载四面板、visible range、crosshair、tooltip 定位和 null-safe series。指数趋势通道以 `TrendChannelPanePrimitive` 附着在共享主图 series，不进入股票 adapter。

后端对应入口在 `src/biz/api/wealth/market/**`，统一挂到 `/api/v1/wealth/market/**`。

### 本地 Lake 管理台：`lake_console/`

`lake_console` 是本地独立工程，不是生产 Ops 子系统，也不是生产 Web app 的一部分。

1. `lake_console/backend/**`：本地 Lake 管理台后端。入口是 `lake_console/backend/app/main.py:create_app`，API 包括 `/api/lake/status`、datasets、partitions、recovery、sync center 等。
2. `lake_console/frontend/**`：本地 Lake 管理台前端。入口是 `lake_console/frontend/src/main.tsx`，共享 API adapter 是 `lake_console/frontend/src/services/lakeApi.ts`。
3. `lake_console/orchestrator/**`：新湖 Dagster 编排工程。入口是 `lake_console/orchestrator/src/orchestrator/definitions.py:defs`，通过 Dagster `load_from_defs_folder` 加载 `defs/**` 下的 assets、checks、jobs、sensors、run contracts。

## 关键调用链

### 生产 Web/API 装配链

```text
src.app.web.run
  -> src.app.web.app
  -> src.app.api.router
  -> src.app.api.v1.router
  -> src.ops.api.router
  -> src.biz.api.* / src.biz.api.wealth.*
```

`src/app/api/v1/router.py` 是当前 API 聚合点：它包含健康检查、auth/admin、Ops API、quote/market/realtime，以及 Wealth market 模块。

### TaskRun 数据维护主链

```text
frontend task center
  -> /api/v1/ops/manual-actions* 或 /api/v1/ops/task-runs*
  -> src.ops.services.task_run_service / manual_action_service
  -> src.ops.runtime.worker
  -> src.ops.runtime.task_run_dispatcher.TaskRunDispatcher
  -> DatasetActionResolver.build_plan
  -> DatasetMaintainService.maintain
  -> IngestionExecutor.run
  -> source_client.fetch
  -> normalizer.normalize
  -> writer.write
```

CodeGraph 确认 `TaskRunDispatcher._dispatch_dataset_action` 会从 TaskRun 构造 `DatasetActionRequest`，调用 `DatasetActionResolver(session).build_plan(action_request)`，创建 `TaskRunNode`，保存 `plan_snapshot_json`，再进入 `_run_dataset_action_plan`。

`_run_dataset_action_plan` 创建 `DatasetMaintainService`，把 `_plan` 与 `_action_request` 传入 `maintain`。因此 TaskRun 只承载用户或调度意图；计划归一化仍由 `DatasetActionResolver` 负责。

`IngestionExecutor.run` 按 unit 循环执行 `fetch -> normalize -> write -> session.commit()`，异常时 rollback，并通过 progress reporter 上报 unit、行数、reject reason 和 current object。

### DatasetDefinition 到运营前端的契约链

```text
src.foundation.datasets.definitions
  -> DatasetDefinition
  -> src.ops.queries.manual_action_query_service
  -> /api/v1/ops/manual-actions
  -> frontend/src/pages/ops-v21-task-manual-tab.tsx
```

`ManualActionQueryService` 读取 `list_dataset_definitions()`，把 `DatasetDefinition.date_model` 转成 `time_form`，把 `input_model.filters` 转成前端可用的 filters。运营前端手动任务页根据这些字段渲染时间控件和参数控件。

这意味着修改 `DatasetDefinition.date_model/input_model/capabilities` 时，必须同时审计 manual actions、catalog、workflow、resolver/unit planner、request builder、freshness、dataset cards、snapshot rebuild、date completeness audit、自动任务日期策略、前端时间控件、相关测试与文档。

### Wealth 行情系统 API 链

```text
wealth/src/shared/api/wealthApiClient.ts:wealthFetch
  -> wealth feature API
  -> /api/v1/wealth/market/**
  -> src.biz.api.wealth.market.*
  -> src.biz.queries.wealth.market.*
  -> src.foundation.models.core/core_serving/core_serving_light
```

指数详情前端链为：

```text
MarketOverviewPage / TopMarketBar
  -> buildIndexDetailPath
  -> WealthRouter
  -> IndexDetailPage
  -> useIndexDetailController
  -> index-detail page-init / kline
  -> 000001.SH 时并行读取既有 quote trend-channel
  -> IndexChartWorkspace / IndexInfoRail
```

`wealthFetch` 是 Wealth 前端真实 API 模块的共享 adapter。CodeGraph 显示它被 market overview 的 breadth、context、indices、leaderboards、limit-up、money-flow、news、sectors、style、summary、turnover，以及 index detail 的 page-init、kline、weights、SSE-only trend 客户端调用。

### Lake Console Sync Center 链

```text
lake_console/frontend/src/services/lakeApi.ts
  -> /api/lake/sync/**
  -> lake_console/backend/app/api/sync_center.py
  -> LakeJobStateStore / LakeJobLockService
  -> KopiaPrewriteBackupService
  -> SyncProfileRunner.run
  -> dataset-specific lake sync services
```

`start_run` 明确要求 `confirmed_backup_required` 与 `confirmed_no_sql`。常规 Sync Profile run 会读取 plan token、校验 blockers、获取 Lake 写入锁、创建 Kopia prewrite backup，然后执行 `SyncProfileRunner.run`，最后写 run/current/events 状态并释放锁。`stk_mins` 特殊 profile 走 pipeline state run 分支。

### Dagster 新湖编排链

```text
lake_console/orchestrator/src/orchestrator/definitions.py:defs
  -> load_from_defs_folder
  -> orchestrator/defs/assets
  -> orchestrator/defs/checks
  -> orchestrator/defs/jobs
  -> orchestrator/defs/sensors
  -> orchestrator/defs/run_contracts
```

`orchestrator/defs/**` 包含 stock_basic、stock_daily、stk_mins、adj_factor、index_daily、market_breadth、ClickHouse serving 等资产、检查、任务、传感器和 run contract。

## 关键 Contract 与 Adapter

1. `DatasetDefinition`：位于 `src/foundation/datasets/models.py`。核心字段包括 identity、domain、source、date_model、input_model、storage、planning、normalization、capabilities、observability、quality、transaction、completeness。
2. `DatasetExecutionPlan`：位于 `src/foundation/ingestion/execution_plan.py`。由 `DatasetActionResolver` 生成，承载 source、planning、writing、transaction、observability 和 units。
3. `DatasetActionResolver`：位于 `src/foundation/ingestion/resolver.py`。负责按 `DatasetDefinition.date_model.input_shape` 归一化时间输入，并生成 plan。
4. `DatasetUnitPlanner`：位于 `src/foundation/ingestion/unit_planner.py`。负责 anchor、universe、enum fanout、分页和 request builder 解析。
5. `request_builders`：位于 `src/foundation/ingestion/request_builders.py`。源接口参数只能在这里生成或通过这里的 builder 生成。
6. `DatasetSourceClient.iter_pages` / `StagedStreamPublisher`：位于 `src/foundation/ingestion/source_client.py` 与 `src/foundation/ingestion/staged_stream.py`。前者提供通用逐页读取，后者只为 Definition 显式 opt-in 的 staged DAO 持有专用连接、锁和事务；页级 stage commit 不改变 unit 级业务提交边界。
7. `TaskRunDispatcher`：位于 `src/ops/runtime/task_run_dispatcher.py`。负责 TaskRun 到执行链的运行时分派、节点、issue、plan snapshot 和 summary。
8. `ManualActionQueryService`：位于 `src/ops/queries/manual_action_query_service.py`。把 DatasetDefinition 与 workflow definition 投影为运营前端可提交的 manual actions。
9. `wealthFetch`：位于 `wealth/src/shared/api/wealthApiClient.ts`。Wealth 前端共享鉴权 API adapter。
10. `lakeApi.ts`：位于 `lake_console/frontend/src/services/lakeApi.ts`。Lake Console 前端共享 API adapter。
11. `SyncProfileRunner`：位于 `lake_console/backend/app/services/sync_profile_runner.py`。本地 Lake Sync Profile 执行 adapter。
12. `orchestrator.definitions.defs`：位于 `lake_console/orchestrator/src/orchestrator/definitions.py`。Dagster defs-folder 装配入口。

## 风险点

1. `DatasetDefinition` 影响面大。CodeGraph impact 显示它影响 Ops action catalog、manual actions、dataset cards、freshness、task run query、schedule、probe、dispatcher workflow、架构护栏和多组测试。修改前必须做全量消费者审计。
2. `TaskRunDispatcher` 是执行观测主链。CodeGraph impact 显示它直接影响 `src/ops/runtime/worker.py` 与 `tests/web/test_ops_runtime.py`。修改 dispatcher 时必须同时确认 worker、TaskRunNode、TaskRunIssue、progress、serving light refresh 和异常状态。
3. `frontend` 手动任务页消费的是后端投影后的 `time_form` 和 filters。若后端自行变更字段或选择规则，前端控件会直接受影响。
4. `wealth` 和 `frontend` 是两个独立前端，不共享 Shell 与路由。不能把运营后台组件或视觉规范默认套到 Wealth。
5. `lake_console` 是本地工程，允许访问本地 Lake、Kopia、DuckDB/Parquet、限定场景下的生产库只读导出；不得把它当作生产 Ops 主链。
6. `lake_console/orchestrator` 与 `lake_console/backend` 都涉及新湖/旧湖、文件事件、Dagster materialization 和 ClickHouse serving。修改时要先确认目标属于管理台、编排工程还是生产后端。
7. `.codegraph/` 是本地索引产物，已加入根 `.gitignore`，不得提交索引数据库。

## 后续开发入口文件

### 生产后端

1. Web 入口：`src/app/web/run.py`、`src/app/web/app.py`
2. API 聚合：`src/app/api/v1/router.py`
3. Ops 聚合：`src/ops/api/router.py`
4. TaskRun runtime：`src/ops/runtime/worker.py`、`src/ops/runtime/task_run_dispatcher.py`
5. TaskRun 服务与查询：`src/ops/services/task_run_service.py`、`src/ops/queries/task_run_query_service.py`
6. Manual actions：`src/ops/services/manual_action_service.py`、`src/ops/queries/manual_action_query_service.py`
7. Dataset facts：`src/foundation/datasets/models.py`、`src/foundation/datasets/registry.py`、`src/foundation/datasets/definitions/**`
8. Ingestion plan/execution：`src/foundation/ingestion/resolver.py`、`src/foundation/ingestion/unit_planner.py`、`src/foundation/ingestion/request_builders.py`、`src/foundation/ingestion/service.py`、`src/foundation/ingestion/executor.py`
9. Wealth backend API：`src/biz/api/wealth/market/**`

### 数据运营后台

1. App 装配：`frontend/src/main.tsx`、`frontend/src/app/router.tsx`
2. API client：`frontend/src/shared/api/client.ts`
3. Task Center：`frontend/src/pages/ops-v21-task-center-page.tsx`、`frontend/src/pages/ops-v21-task-manual-tab.tsx`、`frontend/src/pages/ops-v21-task-records-tab.tsx`、`frontend/src/pages/ops-task-detail-page.tsx`

### 财势乾坤行情系统

1. App 装配：`wealth/src/main.tsx`、`wealth/src/app/App.tsx`
2. API adapter：`wealth/src/shared/api/wealthApiClient.ts`
3. 市场总览：`wealth/src/features/market-overview/**`、`wealth/src/pages/market-overview/**`
4. 股票详情：`wealth/src/features/stock-detail/**`、`wealth/src/pages/stock-detail/**`
5. 详情共享图表：`wealth/src/shared/charts/detail-workspace/**`，当前消费者为 `StockChartWorkspace`

### 本地 Lake 管理台与新湖

1. Lake 后端入口：`lake_console/backend/app/main.py`
2. Sync Center API：`lake_console/backend/app/api/sync_center.py`
3. Sync Profile Runner：`lake_console/backend/app/services/sync_profile_runner.py`
4. Lake 前端入口：`lake_console/frontend/src/main.tsx`
5. Lake 前端 API：`lake_console/frontend/src/services/lakeApi.ts`
6. Dagster 入口：`lake_console/orchestrator/src/orchestrator/definitions.py`
7. Dagster defs：`lake_console/orchestrator/src/orchestrator/defs/**`

## 本次 CodeGraph 调用记录

1. `codegraph_status`：确认根索引状态、文件数、节点数、边数。
2. `codegraph_files`：查看 `src`、`frontend/src`、`wealth/src`、`lake_console`、`lake_console/orchestrator/src/orchestrator/defs` 的结构。
3. `codegraph_explore`：分析 API 装配、TaskRun/ingestion 主链、DatasetDefinition contract、运营前端 manual actions、Wealth API、Lake Console sync center。
4. `codegraph_node`：查看 `TaskRunDispatcher._dispatch_dataset_action`、`TaskRunDispatcher._run_dataset_action_plan`、`DatasetMaintainService._run`、`IngestionExecutor.run`、`wealthFetch`、`SyncProfileRunner.run`、`sync_center.start_run`、`orchestrator.definitions.defs`。
5. `codegraph_search`：校正 `wealthFetch`、`SyncProfileRunner`、`lakeApi` 等符号位置。
6. `codegraph_impact`：分析 `DatasetDefinition` 与 `TaskRunDispatcher` 的代表性影响面。
7. `codegraph query DetailChartWorkspace` / `codegraph query StockChartWorkspace`：确认 shared engine、stock adapter、测试与 `StockDetailPage` 消费者。
8. `codegraph impact DetailChartWorkspace`：确认本轮影响局限于 Wealth 图表入口；另用 import 搜索补足 CodeGraph 对 TSX 消费关系的识别不足。
9. `codegraph query/impact IndexDetailPage`、`codegraph query useIndexDetailController`、`codegraph impact buildIndexDetailPath/MajorIndexPanel/TrendChannelPanePrimitive`：确认 M3 新入口、导航消费者、真实请求控制器和趋势 primitive 的影响面；另用 import 搜索补足 CodeGraph 对 TSX import 的识别不足。

## 仍需人工确认

1. “旧湖 + 新湖”的边界名称是否需要在后续文档中进一步统一：当前快照按代码目录区分 `lake_console/backend`、`lake_console/frontend`、`lake_console/orchestrator`。
2. `lake_console` 允许访问生产库只读导出的白名单边界，需要在具体改动前结合对应 Lake 文档和当前配置逐项确认。
3. `wealth` 与生产后端 API 的版本化策略是否要单独出 contract 文档；当前快照只记录代码事实，不新增策略。
4. `DatasetDefinition` 修改的测试门禁是否要沉淀为固定命令清单；当前已有架构护栏，但不同数据集仍需按计划口径补真实验证。
