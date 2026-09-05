# CodeGraph 架构快照

生成日期：2026-08-22
局部更新：2026-09-05，清退 M2A 当前分钟历史 CLI 拆分、M2B 入口安全门禁、M3 旧 migration 主体退出、M4 旧适配器退出/Raw 恢复重构及 M6 旧产品原子清退；未重审其它模块，下面索引规模仍是原生成日记录。
索引根：`/Users/congming/github/goldenshare`
索引结果：2,508 files，44,388 nodes，101,669 edges，DB 110.44 MB

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

### 正式 Dagster 数据湖：`lake_console/`

`lake_console/orchestrator` 是当前正式 Dagster 工程，不是生产 Ops 子系统或 Web app。
旧 frontend/backend、Kopia、专属测试及旧入口已在 2026-09-05 M6 同轮清退，不再列作当前架构节点。

1. `orchestrator/definitions.py:defs` 通过 load_from_defs_folder 加载 assets、checks、jobs、sensors、run contracts。
2. `orchestrator/defs/paths.py` 决定正式 Lake 三层与独立 staging 根，不使用旧 config.local.toml 或 Kopia。
3. reports 和两项 ClickHouse bin 工具保留；本机 ignored 环境不作为可用的旧产品入口。

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

### Lake → 当前业务 API 链（M6 保留）

```text
正式 Dagster Lake 文件
  -> src.foundation.clients.local_lake 的 6 类 Reader / 12 个文件
  -> Biz 查询服务与 API
  -> Wealth 股票／指数详情页面
```

保留 StockMins、MajorIndexMins、StockNineTurn、IndexNineTurn、MajorIndexTurnover、
StockDailyTrendChannel 六类 Reader；对应分钟行情、分钟九转、成交额洞察、日线趋势通道。
它们不经过旧 Console API。生产 Ops 的 dataset_status_snapshot 是独立观测链，也继续保留。

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

### 分钟历史 CLI（2026-09-05 M2A / M2B / M3）

以下是人工离线入口，不新增 job/sensor/asset，不由页面或 API 触发。模块都位于
`lake_console/orchestrator/src/orchestrator/defs/bootstrap/`：

| 当前入口 | 保留命令 | 调用的业务模块 |
|---|---:|---|
| `stk_mins_silver_history_cli.py` | 5 | `stk_mins_silver_history`、`stk_mins_silver_bootstrap_events` |
| `stk_mins_qfq_history_cli.py` | 5 | `stk_mins_qfq_history`、`stk_mins_qfq_bootstrap_events` |
| `stk_mins_qfq_derived_history_cli.py` | 5 | `stk_mins_qfq_derived_history`、`stk_mins_qfq_derived_bootstrap_events` |
| `stk_mins_qfq_macd_kdj_history_cli.py` | 6 | `stk_mins_qfq_macd_kdj_history`、`stk_mins_qfq_macd_kdj_baseline_events` |

共享 `stk_mins_history_cli_contract.py` 只负责参数注册、CSV/partition 解析和读取已注册 Silver 分区，
不扫描 Lake、不写数据或事件。CLI 不再直接依赖旧 migration；canonical QFQ 六阶段
入口仍是独立的 `stk_mins_qfq_canonical_history_cli.py`，不合并进上述 21 命令。
原混合 CLI 已在 246 组同输入双跑通过后删除，不提供兼容入口；旧 migration 主体在 M3 确认现行消费者清零后删除。
旧 Console 已在 M6 清退；以上正式 CLI 和当前业务模块全部保留。

M2B 已分离 Silver CLI 的 Raw 输入 / Silver 输入 selector，去掉批准的旧 option；baseline CLI 先校验单日范围，再调用原 report。report 入口复核同一范围，且在一次 planner 返回后、文件审计与 event writer 前检查实际分区是请求当天。文件计算、check/event payload、其它 CLI 和多日只读 planner 不变；未引入新服务或跨域依赖。

M3 删除旧 `stk_mins_migration.py` 及其旧测试；当前 helper、Raw checks/readiness、identity-map asset 与上述四 CLI 保留。两条仍有效的零价格测试样本迁到当前 Raw check。M4 单独核清依赖后删除 generic old-lake adapter、specs/executor 和两个旧 adj-factor event 模块；仍在用的 Raw 恢复工具保留并重构，不能套用旧 migration 的零引用结论。

### 单日五频 Raw 离线恢复（2026-09-05 M4）

```text
stk_mins_raw_replace_from_prod_cli.py plan/apply（人工维护窗口）
  -> stk_mins_raw_replace_from_prod（生产库只读 source + 当前股票池 + 旧目标指纹）
  -> 正式 staging：日期/UUID 的 plan、五频 candidates、audits、checkpoint
  -> 所有候选审计通过后逐文件 os.replace 到正式 Raw
  -> 目标完整复核 + checkpoint verified -> 五频完成报告
```

该入口仍不接入页面/API/job/sensor；不写业务数据库或 Dagster event，不做备份、整体回滚或自动换 run。
中断后按同 run 的目标/候选物理指纹续跑；部分提升后候选丢失是人工停止点。只有单文件原子性，没有
五文件事务；操作前须人工协调同日 writer，未引入常驻服务或锁文件。

M4 校准 17 个 catalog 来源声明，159 个资产仍保留；字段、正式 path/partition、当前日常计算和上述
21 CLI 命令契约不变。旧 enum/exports/七项 SQL 退出；历史 event 不改写。M4 实现与隔离回归记录随本次提交归档，
不是正式恢复或部署验收；旧 Console 随 M6 退出，物理数据仍须按精确清单单独确认。

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
10. `local_lake` Readers：位于 `src/foundation/clients/local_lake/**`，读取正式文件，不依赖旧 Console。
11. `orchestrator.definitions.defs`：位于 `lake_console/orchestrator/src/orchestrator/definitions.py`。Dagster defs-folder 装配入口。

## 风险点

1. `DatasetDefinition` 影响面大。CodeGraph impact 显示它影响 Ops action catalog、manual actions、dataset cards、freshness、task run query、schedule、probe、dispatcher workflow、架构护栏和多组测试。修改前必须做全量消费者审计。
2. `TaskRunDispatcher` 是执行观测主链。CodeGraph impact 显示它直接影响 `src/ops/runtime/worker.py` 与 `tests/web/test_ops_runtime.py`。修改 dispatcher 时必须同时确认 worker、TaskRunNode、TaskRunIssue、progress、serving light refresh 和异常状态。
3. `frontend` 手动任务页消费的是后端投影后的 `time_form` 和 filters。若后端自行变更字段或选择规则，前端控件会直接受影响。
4. `wealth` 和 `frontend` 是两个独立前端，不共享 Shell 与路由。不能把运营后台组件或视觉规范默认套到 Wealth。
5. 旧 Console/Kopia 已清退，禁止恢复或下沉到正式主链；新 Lake 路径和写入规则仍以根 AGENTS 与 paths.py 为准。
6. 正式 orchestrator、ClickHouse 和生产 Foundation/Biz 的文件消费者继续保留；不能用旧产品零引用结论删除这些在用模块。
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

### 正式数据湖

1. Dagster 入口：`lake_console/orchestrator/src/orchestrator/definitions.py`
2. Dagster defs：`lake_console/orchestrator/src/orchestrator/defs/**`
3. 人工维护：上述四项分钟历史 CLI 与独立 Raw 恢复 CLI
4. ClickHouse：`lake_console/bin/lake-clickhouse-start`、`lake_console/bin/lake-prod-clickhouse-tunnel`
5. 当前业务消费者：`src/foundation/clients/local_lake/**` 与 `src/biz/api/wealth/market/**`

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
10. 清退 M2A：`codegraph_explore/impact` 覆盖 CLI selector/注册分区 helper，`codegraph_callers`
    覆盖 MACD/KDJ rebuild 与其测试消费者；结合 tracked 程序引用补扫核清四份 CLI 测试、static gate，
    未发现 API/前端/调度消费者。此处记录入口重组，不宣称已完成后续迁移主体或旧产品清退。
11. 清退 M2B：`codegraph_explore/impact` 覆盖 Silver selector 和 baseline CLI → report → planner/审计/事件写入；现行 report 运行调用方仅 MACD CLI，共享 planner 的只读消费者保留多日能力。
12. 清退 M3：`codegraph_explore/impact/callers` 覆盖旧 plan、Raw event report 与 Raw audit；全仓 tracked Python AST 和文本引用补扫，正向导入仅旧测试。复核 package exports、当前 CLI、assets/checks/readiness、identity-map、API/前端和构建入口后，删除旧模块与旧测试；不删除现行 Raw check 或泛化到其它适配器。
13. 清退 M4：`codegraph_explore/impact/callers` 覆盖单日 Raw recovery/CLI、旧 spec/executor/events、资产/catalog/tests 与 API/前端消费者；核实指数 Gold 私有 `_DatasetSpec.source_path` 和旧后台通用 callback 是同名误命中，不属于旧适配器调用。结合真实 import、AST 和基线差异删除 13 个旧模块、4 份专属测试；根 `codegraph sync/status` 显示最新（3,182 files / 57,813 nodes / 141,807 edges，点时值），未新建索引。未改变跨子系统依赖方向，正式运行维护窗口需另确认。

14. 清退 M6：codegraph_explore/impact/callers 覆盖旧 Kopia → API/CLI/UI/测试及当前 6 类 Reader 的 Biz/API 消费者。用全仓 2,410 份保留 Python 的 AST 导入、动态导入和 tracked 配置/脚本/TS 引用补扫弥补索引空结果；旧产品删除清单固定为 263 文件。正式运行源码、21 CLI fixture、Foundation/Biz/Ops、现行前端、reports、两项 ClickHouse 工具共 2,140 文件逐内容对照不变。调用图只作静态证据，不代表正式环境已部署或停服。根 sync/status 完成：2,949 files / 53,540 nodes / 129,954 edges，索引最新（M6 点时值）。

## 仍需人工确认

1. 旧 Console 代码已清退；物理旧湖和 ignored 环境仍须按精确用途清单由管理员确认清理，不能凭当前快照自行删除。
2. `lake_console` 允许访问生产库只读导出的白名单边界，需要在具体改动前结合对应 Lake 文档和当前配置逐项确认。
3. `wealth` 与生产后端 API 的版本化策略是否要单独出 contract 文档；当前快照只记录代码事实，不新增策略。
4. `DatasetDefinition` 修改的测试门禁是否要沉淀为固定命令清单；当前已有架构护栏，但不同数据集仍需按计划口径补真实验证。
