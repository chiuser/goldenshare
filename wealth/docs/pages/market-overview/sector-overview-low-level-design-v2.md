# 市场总览｜板块速览低层设计 v2（LLD）

> 状态：按批准顺序实施中；Slice 1-5 已完成生产验收，Slice 6 后端 V2 与 Slice 7 前端三工作台已完成本地实现和回归。正式 PLAN TaskRun `8149`、首次 APPLY TaskRun `8152` 与幂等重放 TaskRun `8153` 均已通过；下一步是同窗口部署后的真实首页、同机房性能和像素验收。
> 日期：2026-08-13
> 需求基线：[sector-overview-benchmark-requirement-v2.md](./sector-overview-benchmark-requirement-v2.md)
> 实施方案：[sector-overview-implementation-design-v2.md](./sector-overview-implementation-design-v2.md)
> 编码门禁：[sector-overview-m2-coding-gate-v2.md](./sector-overview-m2-coding-gate-v2.md)

---

## 1. 结论与开工边界

### 1.1 本 LLD 冻结的实现结论

1. V2 仍使用现有 `GET /api/v1/wealth/market/sector-overview`，前后端在同一发布单元原子替换旧 DTO；不保留 V1/V2 双契约、别名字段或兼容 adapter。
2. 行业层级通过 `silver_dc_industry_hierarchy -> prod_core_wealth_sector_hierarchy -> core_serving.wealth_sector_hierarchy` 发布，Web 不读 Parquet。
3. 概念热度由 biz prod-native 物化服务只读生产 PostgreSQL 正式表，在质量 contract 通过后按交易日直接发布到 `core_serving.wealth_sector_heat_daily`；不生成 DG Gold 或第二份 Heat 事实，Web 请求不计算 Heat。
4. Heat 的行情、成员、资金、证券资格、停牌、涨停和前序 Heat 全部来自 prod；DG/Lake 只保留行业层级输入，不参与 Heat 计算、回放或 API 查询。
5. `biz` 承载 Heat 来源查询、有效池、公式、质量和事务发布；`ops` 只承载任务意图、计划快照、TaskRun/节点/问题/进度和失败观测。
6. `ops -> biz` 被依赖矩阵禁止；`ops` 通过窄执行端口调用，`app` 组合根负责把该端口绑定到 biz Heat 服务。业务事务与 TaskRun 状态事务必须分离。
7. 新 ORM 必须进入 `src/foundation/models/core_serving/**`，并在 `core_serving/__init__.py`、`all_models.py` 和模型注册测试中登记；不放入 legacy 或错误的 `models/core/**` 路径。
8. Heat 不使用 Dagster asset、dynamic partition、asset check、sensor、Gold 路径、runless event 或 DG history CLI；60 日回放是 prod-native TaskRun。
9. 本轮没有新的产品决策待确认。hierarchy、60+25 日 prod 来源、Heat/app 执行装配、事务与访问边界、60 日生产回放以及前后端 V2 本地实现已通过；剩余未通过项是同窗口部署后的真实首页、同机房性能、像素和观测验收。

### 1.2 当前事实快照

| 项目 | 当前结论 |
|---|---|
| Git 分支 | `dev-interface` |
| Alembic head（部署后复核） | 仓库与生产当前单 head 均为 `20260813_000135`；本需求 revision `20260813_000134` 已位于有效链上并完成生产结构/授权验收 |
| 当前 API | V1 `columns[] + heatMapItems[]` |
| 当前后端来源 | `core_serving.dc_daily/dc_index/board_moneyflow_dc` |
| 当前前端 | 4×2 排名列 + 5×4 涨跌热力格，仅 loading/ready/error |
| 行业层级 Lake | 现有单文件正式 Silver，契约要求 496 行、31/128/337 |
| Heat prod 来源 | `trade_calendar/dc_index/dc_daily/dc_member/board_moneyflow_dc/equity_daily_bar/equity_limit_list/security_serving/equity_suspend_d` 与前序 Heat |
| 当前来源审计 | 目标窗 `2026-05-20..2026-08-12`、warm-up `2026-04-10..2026-05-19` 已冻结并完成整窗复核；资金流对目标概念 100% 覆盖、有效池无真实缺行情；`dc_daily@2026-05-18/20/22/25` 的 88/448/1/2 个缺行在 Prod Raw/Core 一致，按逐概念 `INVALID` 处理 |
| 当前运行缺口 | 正式 PLAN `8149`、首次 APPLY `8152` 与幂等重放 `8153` 已通过；Heat 为 29,665 行/60 日，逐日 config/source/content hash 0 差异，重放 0 写入。当前缺口转为只读 prod 的后端 V2 与前端 V2 |

### 1.3 禁止项

1. 不在页面、adapter 或 API handler 里计算热度、层级、有效池或排序事实。
2. 不按名称模糊关联资金流，不按股票代码前缀判断 A/B 股，不用“有行情”反推上市或停牌。
3. 不把 DG/Lake 或本地文件当成 Heat 事实源；Heat 必须可由冻结的 prod 输入、配置版本/hash和来源 hash 独立重建。
4. 不增加 Redis、实时行情、分钟刷新、20 分钟变化或盘中加速度。
5. 不新增 Kopia、旧 Lake 路径或来源业务表写入。
6. 不在迁移中回填数据、删除来源表、`drop-before-create` 或调用 DG/Lake/Tushare。
7. 不在 ops dispatcher、worker 或 action catalog 中实现 Heat 公式或直接 import `src.biz`。
8. 不新增板块专用数据库账号、DSN、engine 或环境变量；Web/Heat 复用现有应用连接，DG hierarchy 复用现有 prod write resource，但各执行链只能访问本文规定的对象。
9. 不继续向已超过 400 行的 `MarketOverviewPage.tsx` 堆叠板块交互状态。

---

## 2. 当前代码审计

### 2.1 当前调用链

```text
MarketOverviewPage
  -> SectorOverviewPanel
  -> marketSectorOverviewApi
  -> GET /api/v1/wealth/market/sector-overview
  -> MarketSectorOverviewQueryService
  -> SectorOverviewStateQuery
  -> SectorOverviewQuery
  -> SectorOverviewStatusResolver / SectorOverviewExceptionBuilder
  -> DcDaily / DcIndex / BoardMoneyflowDc
```

### 2.2 后端差距

| 当前文件 | 当前问题 | V2 处理 |
|---|---|---|
| `src/biz/api/wealth/market/sector_overview.py` | 仅 `market/tradeDate/debug` | 增加严格 view/rank/selection 参数模型；handler 只校验和调用 service |
| `src/biz/schemas/wealth/market/sector_overview.py` | 只表达 8 列和热力格 | 原子替换为当前 view 的 workspace 契约 |
| `sector_overview_query.py` | 只查 3 表；无层级、成员、Heat | 拆成 state/hierarchy/metrics/heat/effective-pool/member queries |
| `sector_overview_query_service.py` | 固定 8 个 Top5，资金流混排行 | 由 view strategy 编排，后端完成候选、排序、选择和截断 |
| `sector_overview_state_query.py` | 仅追踪 3 个来源日期 | 按 view 定义 readiness，不拼接错日事实 |
| `sector_overview_status_resolver.py` | READY 依赖 8 列/20 格 | 改为 workspace 完整性、Heat/成员覆盖和来源日期状态 |
| `tests/web/test_wealth_market_sector_overview_api.py` | 只有 V1 happy/非法市场 | 覆盖真实路由、三个 view、选择、状态、互斥参数和旧字段清零 |

### 2.3 前端差距

| 当前文件 | 当前问题 | V2 处理 |
|---|---|---|
| `MarketOverviewPage.tsx` | 页面持有 sector 请求状态；文件已超过 1100 行 | 下沉到 `useSectorOverviewController`，页面只渲染 feature |
| `marketSectorOverviewApi.ts` | V1 request/response | 替换为 V2 判别式 workspace 类型 |
| `marketSectorOverviewAdapter.ts` | 丢弃 `leadingStock`；缺值 pct 被改成 0 | 删除事实重组，只做格式化；null 保持 null |
| `SectorOverviewPanel.tsx` | 旧矩阵/热力图；只有三态 | 拆分稳定骨架、tabs、toolbar、workspace、detail 和六态 overlay |
| `market-overview-sector-overview-real-api.test.tsx` | 只测 V1 ready/debug/timeout | 增加真实 API 三视图、交互、stale response、403 和旧结构清零 |
| 现有 CSS | 类名 `sector-v2-layout` 实际仍是 V1 | 删除旧网格规则，按 `1564 × 680` 新结构重建模块局部样式 |

### 2.4 CodeGraph 影响面

CodeGraph 已覆盖 API 入口、service 调用链、模型依赖、页面消费者和前后端测试入口。直接修改范围限于本模块及新增 serving/DG 文件；`index-detail`、`stock-detail`、turnover、money-flow 等模块没有契约依赖。共享边界变化只有：

1. `foundation` 新增两张 serving ORM。
2. `lake_console/orchestrator` 只新增 hierarchy serving 发布链，不新增 Heat 定义。
3. `biz` 继续只依赖 `foundation`。
4. `ops` 增加 Heat TaskRun 意图与抽象执行端口，但不依赖 biz。
5. `app` 增加执行装配适配器，但不增加业务规则。
6. 当前生产 `ops-worker-run/serve` 在 `src/cli.py -> src/cli_parts/ops_handlers.py` 直接构造 `OperationsWorker`；必须改为调用 app worker factory。Web runtime 端点已 decoupled，不进入本次 Heat 执行链。

---

## 3. 目标文件结构

```text
src/foundation/models/core_serving/
  wealth_sector_hierarchy.py
  wealth_sector_heat_daily.py
  __init__.py
src/foundation/models/all_models.py
alembic/versions/20260813_000134_add_wealth_sector_overview_serving.py

lake_console/orchestrator/src/orchestrator/defs/
  assets/wealth_sector_hierarchy_prod_core.py
  prod_db/wealth_sector_hierarchy.py

src/biz/
  api/wealth/market/sector_overview.py
  schemas/wealth/market/sector_overview.py
  queries/wealth/market/sector_overview/
    sector_overview_state_query.py
    sector_hierarchy_query.py
    sector_metrics_query.py
    sector_heat_query.py
    sector_heat_source_query.py
    effective_a_stock_pool_query.py
    sector_member_query.py
    sector_overview_query_service.py
  services/wealth/market/sector_overview/
    sector_heat_config_resolver.py
    sector_heat_contract.py
    sector_heat_materialization_service.py
    sector_heat_replay_planner.py
    sector_heat_models.py
    sector_selection_resolver.py
    sector_overview_status_resolver.py
    sector_overview_exception_builder.py

src/biz/services/wealth/config/
  definitions/sector_overview.cn_a.v1.json
  strategy_config_models.py
  strategy_config_registry.py

src/ops/
  action_catalog.py
  runtime/maintenance_executor.py
  runtime/task_run_dispatcher.py
  runtime/worker.py

src/app/
  services/wealth/market/sector_overview/sector_heat_task_executor.py
  services/wealth/market/sector_overview/sector_source_completion_evidence.py
  runtime/ops_worker_factory.py

src/cli.py
src/cli_parts/ops_handlers.py

tests/
  test_extended_models.py
  test_foundation_table_model_registry.py
  test_wealth_sector_serving_constraints.py
  test_wealth_sector_serving_migration.py
  test_wealth_sector_heat_contract.py
  test_wealth_sector_heat_materialization_service.py
  test_wealth_sector_heat_task_execution.py
  test_wealth_sector_database_access_boundaries.py
  test_cli_ops_runtime.py

wealth/src/features/market-overview/sectors/
  SectorOverviewPanel.tsx
  SectorOverviewTabs.tsx
  SectorRankingToolbar.tsx
  SectorDetailPanel.tsx
  useSectorOverviewController.ts
  model/sectorOverviewViewModel.ts
  api/marketSectorOverviewApi.ts
  industry/IndustryHierarchyWorkspace.tsx
  industry/IndustryLevelColumn.tsx
  industry/IndustryRankItem.tsx
  concept/ConceptHeatWorkspace.tsx
  concept/ConceptRankItem.tsx
  concept/HeatBadge.tsx
  region/RegionRankingWorkspace.tsx
  detail/SectorMetricGrid.tsx
  detail/SectorMemberStockList.tsx
```

文件名可因最近目录命名规则做等价收敛，但职责不得合并回 handler、页面或单个巨型 service。

---

## 4. 持久化 LLD

### 4.1 `WealthSectorHierarchy`

ORM：`src/foundation/models/core_serving/wealth_sector_hierarchy.py`。

| 字段 | SQLAlchemy | 约束 |
|---|---|---|
| `sector_code` | `String(16)` | PK |
| `sector_name` | `String(128)` | not null |
| `industry_level` | `SmallInteger` | not null, check 1..3 |
| `industry_level_name` | `String(32)` | not null |
| `parent_sector_code/name` | `String(16/128)` | 一级同时为空，二三级同时非空 |
| `root_sector_code/name` | `String(16/128)` | not null |
| `hierarchy_path` | `String(512)` | not null |
| `is_leaf` | `Boolean` | not null |
| `display_order` | `Integer` | not null, >=0 |
| `baseline_version` | `String(128)` | not null |
| `source_received_date` | `Date` | not null |
| `code_reference_trade_date` | `Date` | not null |
| `published_at` | `DateTime(timezone=True)` | not null |

索引：

1. `(industry_level, display_order, sector_code)`。
2. `(parent_sector_code, industry_level, display_order, sector_code)`。
3. `(root_sector_code, industry_level, display_order, sector_code)`。

表内不存 JSON children；父子路径由规范字段表达。应用读取后可按 `baseline_version` 构建不可变内存索引。

### 4.2 `WealthSectorHeatDaily`

ORM：`src/foundation/models/core_serving/wealth_sector_heat_daily.py`。

字段、精度、枚举和可空规则沿 implementation design 第 4.2 节；补充数据库约束：

1. PK `(trade_date, sector_code)`。
2. `heat_status IN ('VALID','INVALID')`。
3. `heat_level IN ('BOILING','HOT','ACTIVE','NONE')`。
4. `heat_trend/raw_heat_trend IN ('HEATING','STABLE','COOLING','UNKNOWN')`。
5. `VALID` 必须有五分量、`base_heat_score/rank`、`heat_score/rank`，且 `invalid_reason IS NULL`。
6. `INVALID` 必须有固定 `invalid_reason`，不可计算分数允许为空；不得用 0 代替缺失。
7. 分数范围、计数非负、`suspended_count <= member_count`、`quote_eligible_count = member_count - suspended_count`、`missing_quote_count = quote_eligible_count - valid_quote_count`。
8. `source_dates_json` 是只读证据，不作为查询排序字段。
9. `config_hash/source_hash` 固定为 64 位小写十六进制 SHA-256；`source_row_counts_json` 必须包含每个输入来源的有界读取行数。

索引：

1. `(trade_date, heat_score DESC, sector_code)`。
2. `(trade_date, heat_delta_1d DESC, sector_code)`。
3. `(sector_code, trade_date DESC)`。

### 4.3 模型登记

实现必须同时修改：

1. `src/foundation/models/core_serving/__init__.py`。
2. `src/foundation/models/all_models.py`。
3. `tests/test_extended_models.py`：表名、schema、PK、数值精度、check/index。
4. 如表卡注册依赖自动扫描，增加 table registry 测试，不能仅凭 import 成功判定完成。

### 4.4 Alembic

1. 本需求 revision 创建时本地与生产均为单 head `20260812_000133`，因此已正确接为 `20260813_000134`；部署后复核仓库与生产当前单 head 均为 `20260813_000135`。任何后续 revision 仍必须重新读取真实 head。
2. upgrade 顺序：create hierarchy -> constraints/indexes -> create heat -> constraints/indexes -> 给既有 `lake_raw_writer` 增加 hierarchy 单表 `SELECT/INSERT/DELETE`；不得创建 login、密码或新连接配置。
3. migration 不做 `DROP TABLE IF EXISTS`、数据回填、外部访问或来源表 DML。
4. downgrade 仅删除本次两张表，先 heat 后 hierarchy。
5. SQLite 单测若不支持某些 PostgreSQL check 表达式，测试数据库兼容只能在测试装配层解决，不能弱化生产约束。

### 4.5 现有连接复用与事务边界

本需求不新增数据库账号、DSN、engine 或板块专用环境变量。publisher、materializer、reader 是逻辑职责，不是三个数据库身份。

| 逻辑职责 | 复用的当前连接 | 代码访问范围 |
|---|---|---|
| migration | 现有 Alembic `DATABASE_URL` | 创建两表、约束和索引；只给既有 `lake_raw_writer` 增加 hierarchy 单表授权 |
| DG hierarchy publisher | `ProdPostgresWriteResource` / `PROD_POSTGRES_WRITE_*`，当前账号 `lake_raw_writer` | 仅对 `wealth_sector_hierarchy` 执行 `SELECT/DELETE/INSERT` |
| Heat materializer | `DATABASE_URL` / `SessionLocal` 新开的 business session | 只读冻结的 prod 来源表；仅对 `wealth_sector_heat_daily` 执行 `SELECT/DELETE/INSERT` |
| Wealth Web reader | `DATABASE_URL` / 现有 `get_db_session` | 只读取 V2 所需来源、hierarchy 与 Heat 表 |

1. migration 不创建 login 或 secret；只对既有 `lake_raw_writer` 执行 `GRANT SELECT, INSERT, DELETE ON core_serving.wealth_sector_hierarchy`，不新增 `UPDATE/CREATE/TRUNCATE`，也不改变该账号其它表的既有授权。
2. Web V2 handler 继续使用通用 `get_db_session`，不得新增 `WEALTH_SECTOR_READ_DATABASE_URL` 或板块专用 engine。
3. Heat executor 每个日期从现有 `SessionLocal` 工厂新开一个 `heat_session`；Ops worker 的 `ops_session` 与 `heat_session` 可以使用同一 DSN/账号，但不得共享 Session、connection 或 transaction。
4. Heat 业务提交完成后，Ops 状态写入失败不得回滚 Heat；Heat 回滚后，Ops 使用自己的事务记录失败。测试必须覆盖两个方向。
5. DG hierarchy 沿用现有 `ProdPostgresWriteResource` 的成功 commit、异常 rollback 语义，不新增 hierarchy resource 或 `WEALTH_SECTOR_HIERARCHY_POSTGRES_*`。
6. 应用现有数据库账号权限较宽，因此 Heat/Web 的“只读/只写”是 DAO、固定 SQL、显式字段和事务测试约束；全站数据库账号拆分不扩大进本需求。
7. 现有 URL/password 仍不得写入日志、TaskRun 或异常文本；这是通用 secret 规则，不是新增专用连接的理由。
8. PostgreSQL 集成测试验证两表约束、DG 既有账号对 hierarchy 的精确授权、事务回滚和 read-back；静态/单元测试验证 Heat/Web/DG 的 SQL 目标范围、Web 无 DML、运行时代码无 DDL/`TRUNCATE`。

---

## 5. DG hierarchy 与 prod-native Heat LLD

### 5.1 DG hierarchy 发布

`prod_core_wealth_sector_hierarchy` 是本需求唯一 DG asset：

1. 输入固定为 `/Volumes/datasource/data_lake/silver/board/dc_industry_hierarchy/full/part-000.parquet`；沿用现有单文件、无分区、手工 seed 身份。
2. 发布前调用层级文件 contract，验证 schema、唯一 `sector_code`、496 行、31/128/337、父子闭包和版本。
3. 复用现有 `ProdPostgresWriteResource` / `PROD_POSTGRES_WRITE_*` 和 `lake_raw_writer`；在单事务中 `DELETE + INSERT + read-back`，不使用 `TRUNCATE`。
4. read-back 验证 496、31/128/337、父子闭包、版本和 canonical hash，不一致回滚。
5. 显式人工运行或纳入部署步骤；不新增自动重建 sensor，也不与 Heat 任务建立依赖。

### 5.2 prod Heat 输入适配与范围

| 事实 | prod 表 | 范围 |
|---|---|---|
| 交易日 | `core_serving.trade_calendar` | `exchange='SSE' AND is_open=true`；解析 `t`、25 日 warm-up、5 日复算窗 |
| 板块目录/领涨 | `core_serving.dc_index[t-5..t]` | 逐日概念集合；目标日同时提供领涨事实 |
| 板块日线 | `core_serving.dc_daily[t-25..t]` | 已完成交易日窗口 |
| 板块成员 | `core_serving.dc_member[t-5..t]` | 仅概念代码 |
| 资金流 | `core_serving.board_moneyflow_dc[t-9..t]` | 复算前 5 日基础热度各自的 5 日窗口；概念、非空 `ts_code` |
| 股票资格 | `core_serving.security_serving` | 按每个计算日投影 |
| 停牌 | `core_serving.equity_suspend_d[t-5..t]` | `suspend_type='S'` |
| 股票日线 | `core_serving.equity_daily_bar[t-5..t]` | 仅相关成员 |
| 涨停 | `core_serving.equity_limit_list[t-5..t]` | `limit_type='U'`、相关成员 |
| 历史 Heat | `core_serving.wealth_sector_heat_daily` | 前序最多 2 个连续且 `scoreVersion/configHash` 相同的成功交易日；仅 delta/trend，跨版本/断点不比较 |

`SectorHeatSourceQuery` 使用 ORM/显式 SQL，一次返回 `SectorHeatSourceBundle`：交易日集合、逐来源行、逐来源日期、逐来源行数和 canonical source hash。禁止 `SELECT *`、自然日替代、逐概念 N+1、Parquet、DuckDB、DG resource 或 Tushare。

hash 规范固定：

1. `config_hash = SHA256(canonical_json(strict_strategy_payload))`，canonical JSON 使用 UTF-8、键排序、稳定十进制表示且不含 envelope 的更新时间/操作者。
2. `source_hash` 依次编码查询边界和每张表实际参与计算/资格判定的显式字段；按表名、交易日、表主键或文档冻结的稳定键排序，空值使用独立 token。
3. `created_at/updated_at/calculated_at`、数据库物理顺序、查询耗时和摄取批次等不改变业务结果的元数据不得进入 source hash；来源字段集合变化必须升级 `scoreVersion`。
4. `content_hash` 对候选 Heat semantic rows 按 `(trade_date, sector_code)` 排序后计算，排除 `calculated_at`；TaskRun 保存该 hash，表 read-back 现场复算，不新增第二份事实表。

完成性证据边界：

1. app `SectorSourceCompletionEvidenceProvider` 用独立 Ops read session 查询已有 TaskRun/日期完整性事实，输出中立 DTO：`dataset_key, trade_date, status, evidence_type, evidence_id, evidence_hash`。
2. biz `SectorHeatSourceBundle` 可接收该 DTO，但不得 import ops ORM；证据只参与来源就绪判定，不能提供或覆盖任何行情、成员、资金、停牌或涨停数值。
3. 非空来源仍按 prod 行、唯一键和覆盖校验；`equity_limit_list/equity_suspend_d` 等空集只有在对应日期存在成功完成证据时才解释为合法 0，否则整日进入 gap ledger。
4. 合法零行证据的 dataset/date/status/id/hash 进入 plan snapshot 和 `source_hash`；状态变化或证据缺失触发 `HEAT_PLAN_DRIFT/SOURCE_NOT_READY`，不得静默沿用旧证据。
5. provider 的 Ops read session、外层 TaskRun write session 和 Heat business session 三者职责分开；任一观测写失败不得影响已提交 Heat。

### 5.3 `EffectiveAStockPool` 单一语义

对每个 `calculation_date + sector_code`：

```text
sourceMembers = DISTINCT dc_member.con_code

eligibleMembers = sourceMembers
  INNER JOIN security_serving ON ts_code = con_code
  WHERE security_type = 'EQUITY'
    AND curr_type = 'CNY'
    AND list_status IN ('L', 'D')
    AND list_date <= calculation_date
    AND (delist_date IS NULL OR delist_date > calculation_date)

suspendedMembers = eligibleMembers
  INNER JOIN equity_suspend_d ON same ts_code/date AND suspend_type = 'S'

quoteEligibleMembers = eligibleMembers - suspendedMembers
validQuoteMembers = quoteEligibleMembers INNER JOIN equity_daily_bar ON same ts_code/date
missingQuoteMembers = quoteEligibleMembers - validQuoteMembers
```

1. Heat 物化与 Web 详情复用同一个 `EffectiveAStockPoolQuery`，不再保留 Lake/PostgreSQL 双 adapter。
2. 固定案例覆盖 B 股、未来上市、退市生效日、全日停牌、复牌、可报价但无日线和重复成员。
3. 六类计数必须由同一关系查询产出，禁止在 Python 用分散计数猜差值。

### 5.4 Heat 配置与纯 contract

1. 在策略配置中心注册 `moduleKey=sectorOverview, market=CN_A, definition_file=sector_overview.cn_a.v1.json`。
2. `SectorOverviewHeatStrategyPayload` 使用 `extra='forbid'`，完整表达五个主权重、价格/广度/资金流/持续性内部权重、窗口、TopN、winsor、等级/趋势/质量阈值和 `scoreVersion`；逐组校验权重和、阈值顺序、正整数窗口/TopN 与覆盖率。
3. `SectorHeatConfigResolver` 只通过 `StrategyConfigService` 读取配置，生成 canonical payload SHA-256；禁止业务模块直接打开 JSON。
4. `SectorHeatContract` 提供纯函数：winsor、平均秩 percentile、线性斜率、五分量、base/final score 与 rank、level、delta 和两日趋势确认。
5. 所有排序最终追加 `sector_code ASC`；配置非法严格失败，不使用代码默认值或旧版本回退。

### 5.5 单日计算、质量和事务发布

`SectorHeatMaterializationService.materialize_trade_date(session, trade_date, expected_plan_hash)`：

1. 用 prod 交易日历解析目标日、25 日 warm-up 和 5 日复算窗口。
2. `SectorHeatSourceQuery` 有界读取全部 prod 输入；结合 app 传入的中立完成性 DTO，验证来源日期、唯一键、概念代码覆盖及合法零行证据。来源整日缺失或零行且无完成证据时阻断该交易日；Prod Raw/Core 一致的局部概念缺行只使该概念因缺少主分量成为 `INVALID`，不得补 0、跨日填充、删除候选或阻断其它概念。
3. 构造逐日有效池与六类计数；复算前 5 日横截面 base rank，不读取未来输入。
4. 使用纯 contract 计算目标日五分量、persistence、final score/rank、level、delta 和 trend。
5. 为当日所有概念生成候选行；质量不足保留 `INVALID + reason`，不伪造 0 分、不补权。
6. 发布前运行内存/SQL contract：schema、状态不变量、来源日期、identity、公式抽样、rank/等级分布、no-lookahead 与有效池恒等式。
7. 在同一业务事务中 `DELETE WHERE trade_date=:date`、批量 `INSERT`、显式列 read-back；比较 semantic `content_hash`、行数、`scoreVersion/configHash/sourceHash/tradeDate`。
8. read-back 不一致或任一质量门禁失败则回滚；成功后提交该日 Heat。来源表全程只读。
9. 返回 `SectorHeatMaterializationResult`：日期、读写行数、有效/无效分布、来源证据、配置/hash、内容 hash、耗时和质量结果。
10. PLAN 的业务 session 以 PostgreSQL `REPEATABLE READ, READ ONLY` 启动；单日发布以 `REPEATABLE READ` 启动，保证来源 bundle、有效池聚合、公式与 source hash 使用同一数据库快照。
11. APPLY/续跑传入 `expected_plan_hash + expected_content_hash`；若重新计算无漂移且现存 semantic content 已等于计划，则返回 `skipped_existing=true` 且不执行 DML。

### 5.6 Ops 执行端口与 app 组合

`src/ops/runtime/maintenance_executor.py` 定义不含 biz 类型的通用端口：

```python
class MaintenanceExecutor(Protocol):
    def plan(self, request: MaintenanceExecutionRequest) -> MaintenanceExecutionPlan: ...
    def execute_unit(self, unit: MaintenanceExecutionUnit) -> MaintenanceExecutionResult: ...
```

dispatcher 语义固定：replay `PLAN` 调用 `plan()` 后只持久化 snapshot 并成功结束，不调用 `execute_unit()`；replay `APPLY` 读取并校验被引用 snapshot 后直接按冻结 units 调用 `execute_unit()`，不重新选择日期；单日 action 构造一个日期 unit。通用端口 DTO 只含 JSON 可序列化标量/映射，不引用 biz 或 ops ORM。

1. `ops.action_catalog` 登记 `maintenance.materialize_wealth_sector_heat_daily` 与 `maintenance.replay_wealth_sector_heat_history`，两者的 `executor_key` 均为 `wealth_sector_heat`。
2. `TaskRunDispatcher` 只按 executor key 调用端口、创建逐日 TaskRunNode、记录进度/结果/issue；不得 import `src.biz` 或读取 Heat 配置。
3. `src/app/.../sector_heat_task_executor.py` 实现该端口：plan 委托 biz replay planner，execute_unit 为每个日期打开独立 business session 并调用 materialization service。
4. `src/app/runtime/ops_worker_factory.py` 是生产 worker 唯一装配入口；向 `OperationsWorker` 注入 executor registry。`src/cli.py` 的 `ops-worker-run/serve` 必须使用该 factory，`src/cli_parts/ops_handlers.py` 接收 callable factory；不得直接构造未装配的 worker。执行器缺失时 Heat action 失败关闭。
5. Ops session 与 business session 不共享 transaction。Heat 已提交后，即使 TaskRun 节点/终态写入失败，也不得回滚 Heat；重试先按 plan/config/source/content hash 做 read-back，再幂等覆盖或确认完成。
6. `biz` 不读写 TaskRun；app 适配器只做参数映射、session 生命周期和结果映射，不实现公式/SQL。
7. replay PLAN snapshot 保存逐日 `source_dates/source_row_counts`、期望行数、config/source/plan/content hash，并增加通用 `snapshot_integrity_hash`；APPLY 必须同时校验成功 PLAN 身份、日期窗、提交的 plan hash 与 snapshot integrity。

ActionDefinition 参数：

| action | 参数 | 规则 |
|---|---|---|
| `maintenance.materialize_wealth_sector_heat_daily` | `trade_date: date` | 必填；`manual_enabled=true`，60 日和最新日验收前不启用 schedule |
| `maintenance.replay_wealth_sector_heat_history` | `execution_mode: enum(PLAN,APPLY)` | 必填；`schedule_enabled=false` |
| replay PLAN | `start_date/end_date: date` | 必填且连续打开日不少于 60；禁止 `plan_task_run_id/plan_hash`；只写 Ops plan snapshot/issue，不写 Heat |
| replay APPLY | `plan_task_run_id: integer`, `plan_hash: string` | 必填；禁止 start/end；引用同 action、成功 PLAN TaskRun 的 immutable snapshot |

1. ops 负责从所引用 PLAN TaskRun 读取并校验 snapshot；传给 executor 的是通用 plan units/expected hashes，不暴露 ops ORM。
2. app/biz 在每个日期执行前复算配置与来源 hash；与 plan 不一致时以 `HEAT_PLAN_DRIFT` 停止，不自动重规划或跳日。
3. PLAN、APPLY 和单日 action 都使用 TaskRun/TaskRunNode 正式状态链；不另建 Heat run 表。
4. 单日 schedule 仅在首发回放和最新日验收后通过现有 Ops Schedule 数据配置启用；不新增 sensor 或代码内隐藏 cron。

### 5.7 60 个有效交易日 plan/apply

1. replay PLAN 从 prod 交易日历选择候选日期，对每一日执行来源日期、数量、唯一键、合法零行、代码覆盖和配置可用性审计；只写 Ops `plan_snapshot_json` 与 issue，不写 Heat。
2. plan 先从 prod 交易日历选择连续至少 60 个 `exchange='SSE' AND is_open=true` 的目标交易日；只有全部必需 prod 来源在日期级通过的日期才是“有效交易日”。日期级失败包括整日缺失、枚举/唯一键非法或零行无完成证据；源站现状导致的单概念特征缺行归入该概念 `INVALID`，不把日期整体移出窗口。不完整日期进入 gap ledger，修复并复核前不得跳过或用窗外日期凑数。
3. plan 固定该连续目标窗、额外 25 个前置 warm-up 交易日、逐日来源证据、预计读写行数、配置版本/hash 和 canonical plan hash。
4. APPLY 必须携带成功 PLAN 的 `plan_task_run_id + plan_hash`，从旧到新逐日执行；每个日期独立 business transaction 和 TaskRunNode。
5. 首个失败日立即停止；续跑根据 plan hash 与 Heat read-back 从最后成功日继续。warm-up 不计入 60 日验收。
6. 当前审计事实写入 plan 说明：`dc_daily/dc_member` 按源站现状判定；`board_moneyflow_dc@2026-07-09` 已补齐但仍需整窗复核。
7. 不提供 DG history CLI，不生成 runless event；历史回放通过正式 Ops TaskRun 提交与观察。

### 5.8 DG Heat 清零静态门禁

仓库扫描必须断言本需求未新增或引用：`gold_wealth_sector_heat_daily`、Heat dynamic partition、Heat asset check、Heat sensor、Heat Gold/Parquet 路径、Heat runless event、Heat history CLI、DG Heat 配置文件或 DG Heat 计算 contract。DG 只允许 hierarchy 发布文件出现在本模块改动清单中。

---

## 6. 后端 LLD

### 6.1 请求模型与 handler

API handler 使用显式 enum/格式校验，禁止把互斥规则分散到 query：

1. 默认 `market=CN_A, view=INDUSTRY`。
2. 行业/地域默认 `CHANGE_PCT`，概念默认 `HEAT_SCORE`。
3. `selected*Code` 使用 `^BK[0-9]{4}(?:\.DC)?$`；进入查询前规范化为存储格式，响应保持统一格式。
4. 当前 view 之外的 rank/selection 参数立即返回 `400001`。
5. 显式 `tradeDate` 非交易日或无完整事实返回 `EMPTY`，不回退。
6. 403 仍由统一 `require_quote_access` 产生，不伪装为 HTTP 200。

### 6.2 查询职责与 SQL 边界

| 类 | SQL/职责 | 上限 |
|---|---|---:|
| `SectorOverviewStateQuery` | 视图所需来源的最近共同完成日 | 1 round trip 或受控的固定查询 |
| `SectorHierarchyQuery` | 当前层级版本全部节点；校验单版本 | 496 行 |
| `SectorMetricsQuery` | 候选代码集同日行情 + 资金流 | 行业 496 / 概念约百 / 地域 31 |
| `SectorHeatQuery` | 同日 Heat 排名；所选概念最近 20 发布日 | Top20 + 20 点 |
| `EffectiveAStockPoolQuery` | 单板块成员资格、停牌、行情和计数 | 单板最大成员数，按 code/date 有界 |
| `SectorMemberQuery` | 单板块有效成员 Top5 | 5 行 |
| `SectorSelectionResolver` | 纯内存路径修正 | 无 SQL |

全部 SQL：

1. 使用显式列名、确定排序和有界候选集合。
2. `board_moneyflow_dc` 只按 `trade_date + non-null ts_code` 关联。
3. 领涨股只取 `dc_index.leading/leading_code/leading_pct`，不从 member Top1 反推。
4. 成员 Top5 按 `pct_chg DESC NULLS LAST, stock_code ASC`。
5. `MAIN_NET_INFLOW` 空值末尾；所有主排序同分最终 `sector_code ASC`。
6. 不做逐板块成员 N+1；仅为最终详情节点查一次成员。

### 6.3 层级缓存

`SectorHierarchyQuery` 可维护进程内只读缓存：

```text
cache key   = baseline_version
cache value = nodesByCode + childrenByParent + roots
invalidate  = DB 查询发现 baseline_version 改变
fallback    = 不允许使用旧版本掩盖当前表空/闭包失败
```

不设置运维可调 TTL。缓存只是 496 行结构优化，不是事实来源。

### 6.4 选择算法

`SectorSelectionResolver` 输入候选树、排名结果和可选请求 code，输出完整 selection 与可选 `SO_SELECTION_INVALID`：

1. 先确定一级 Top5；请求节点 root 不在 Top5 时回到榜首。
2. 再确定所选一级直接二级 Top5；请求祖先不在榜内时回到榜首。
3. 再确定所选二级直接三级 Top5；请求三级不在榜内时回到榜首。
4. 请求一级/二级时向下补榜首；无子级时停在最深合法节点并返回后续空列。
5. `detailSectorCode` 始终等于最深合法选择，不由前端拼装。

概念/地域：请求 code 在当前确定候选中则保留，否则选择榜首并记录 debug；概念热度排序未就绪时不改用涨跌幅。

### 6.5 状态归并

| 条件 | panel status | 页面内容 |
|---|---|---|
| 当前 view 必需事实同日完整 | READY | 正常 workspace |
| Heat 未发布/个别 Heat 无效/成员覆盖不足 | PARTIAL | 可用事实保留，缺失显示 `--` |
| 最近共同完成日落后期望日 | DELAYED | 显示真实旧日，不冒充当日 |
| 显式日无候选/全部基础源合法空 | EMPTY | 稳定空态 |
| 层级闭包、SQL、配置契约失败 | ERROR | 当前模块错误态 |
| HTTP 403 | 前端 FORBIDDEN | 稳定无权限态 |

`pageStatus` 沿用首页现有聚合器；模块异常不得让其它首页模块丢失。

### 6.6 响应构建

1. response 只出现当前 view 对应的 `industry/concept/region`。
2. `MetricValue.value=null` 时 `displayText='--', direction='UNKNOWN'` 由后端 formatter 产出。
3. `leader` 三字段均缺失时返回 `null`；不产出半真半假的占位股票。
4. Heat `INVALID` 保留质量计数和原因；`heatScore/heatRank` 为 null。
5. `heatHistory` 日期升序、最多 20 点，断点/无效点保留日期与 null，不向前填充。
6. `asOf` 是响应组装时间，`calculatedAt` 是 Heat 物化时间，两者都不能写成实时行情时间。

---

## 7. 前端 LLD

### 7.1 状态控制器

`useSectorOverviewController` 持有：

```ts
type SectorTabState = {
  industry: { rankMetric: IndustryRankMetric; selectedCode?: string };
  concept: { rankMetric: ConceptRankMetric; selectedCode?: string };
  region: { rankMetric: RegionRankMetric; selectedCode?: string };
};

type SectorRequestState =
  | { kind: "initial-loading" }
  | { kind: "refreshing"; data: SectorOverviewPanelV2 }
  | { kind: "ready"; data: SectorOverviewPanelV2 }
  | { kind: "empty"; data?: SectorOverviewPanelV2 }
  | { kind: "partial" | "delayed"; data: SectorOverviewPanelV2 }
  | { kind: "forbidden" }
  | { kind: "error"; message: string };
```

请求纪律：

1. 首次、Tab、rank、selection、tradeDate 变化均走同一 controller。
2. 每次新请求 abort 上一个请求，并以递增 request id 二次防止 stale response 回写。
3. 超时保持现有 5 秒；timeout -> error，不切 mock。
4. 切 Tab 恢复该 Tab 自己的 rank/selection；服务端纠正后的 selection 回写对应 Tab。
5. retry 重发当前完整请求，不重置用户选择。

### 7.2 组件边界

1. `SectorOverviewPanel`：固定外框和状态 overlay，不持有事实排序。
2. `SectorOverviewTabs`：可访问的 tablist/tab，键盘左右切换。
3. `SectorRankingToolbar`：只发 rank enum。
4. 三个 workspace：只渲染各自 DTO，不接收其它 view 字段。
5. `SectorDetailPanel`：共享指标、领涨、成员结构；地域增加 breadth 分布，概念增加 Heat 历史。
6. badge 只映射后端 enum 到已冻结中文，不从 score/delta 二次推导。

### 7.3 布局约束

1. 外框 `1564 × 680`，高度不因状态或列表长度变化。
2. 行业左侧三列每列固定 5 行；概念/地域固定 7 行可视和内部 `overflow-y:auto`。
3. 排名项中板块名、主指标、领涨股各自有真实容器；名称和领涨股单行省略，tooltip 提供全文。
4. 工具栏、Tab、列表、详情使用 flex/grid 正常流；Heat 迷你趋势图内部坐标可绝对定位。
5. A 股红涨绿跌只由 `direction` enum 驱动；Heat 标签使用独立 token，不复用 success/error。
6. Loading/Empty/Error/Partial/Delayed/Forbidden 共用同一 grid 骨架，overlay 不导致布局跳动。

### 7.4 类型与 adapter

1. API 类型按 view 判别，禁止可选字段堆叠后由组件猜 view。
2. adapter 只做日期/金额/百分比显示格式，不排序、不补 0、不修 selection、不算标签。
3. 删除所有 `columns/heatMapItems`、旧 fixture、旧 `SectorRankMatrix/SectorHeatmap`。
4. `null` 永远映射 `--/UNKNOWN`；空数组保留 empty 语义。

---

## 8. 测试 LLD

### 8.1 Foundation / migration

1. 两个 ORM 的 schema、PK、index、numeric 和 check 约束。
2. migration upgrade/downgrade 仅影响两张目标表。
3. Alembic 单 head、metadata 与数据库表一致。

### 8.2 层级发布、Heat 业务 contract 与执行链

| 组 | 必测正例 | 必测反例 |
|---|---|---|
| DG hierarchy | Silver 496 行、层级计数、写后 hash 对账 | 非法层级、重复键、计数/hash 不一致时不得发布 |
| 配置中心 | V1 canonical config/hash，注册表可解析 | 权重不为 1、阈值逆序、未知版本、版本未升 |
| prod 来源查询 | 每个来源按冻结字段和窗口有界读取 | `SELECT *`、自然日凑数、逐板块 N+1、访问 DG/Lake/Tushare |
| 有效池 | CNY 上市 A 股、停牌扣分母 | B 股、未来上市、退市生效日、重复成员、两套 adapter 口径 |
| 行情覆盖 | 有效报价、合法零停牌 | 可报价无行情、必需来源缺失或错日仍计算 |
| Heat contract | golden 五分量/总分/rank/level | 缺分量补权、低覆盖仍有效、未来数据影响历史结果 |
| prod 发布 | 单日 delete+insert+read-back hash 同事务成功 | read-back 不同、数据库写入失败或 contract 失败时保留旧成功日 |
| Ops/app/CLI 装配 | TaskRun 计划 60 个有效交易日，生产 CLI 经 app factory 注入 executor 并调用 biz | ops import biz、CLI 直构未装配 worker、TaskRun session 与业务 session 共事务、失败跳日 |
| 访问边界 | DG/Heat/Web 只操作各自规定对象，Heat 与 Ops 使用独立 Session/事务 | DG 写 Heat、Heat 写来源/hierarchy、Web 产生 DML、运行时代码执行 DDL/`TRUNCATE` |
| 静态清零 | DG 仅存在 hierarchy 发布实现 | 出现 DG Heat asset/partition/check/sensor/Gold/history CLI |

### 8.3 后端真实 API

`tests/web/test_wealth_market_sector_overview_api.py` 至少拆分：

1. 三个 view 的 happy path，断言用户实际看到的字段。
2. 行业三级 Top5、父子范围、默认/保留/纠正/无子级。
3. 概念四种排序、Heat INVALID、历史 20 点和未就绪不回退。
4. 地域三种排序、精确 31 项、无 hierarchy/Heat。
5. 领涨字段严格来自 `dc_index`；成员 Top5 和覆盖计数。
6. 互斥参数、非法 market/date/code、403。
7. READY/PARTIAL/DELAYED/EMPTY/ERROR。
8. response/schema 明确不存在 V1 `columns/heatMapItems` 旧根语义。

### 8.4 前端真实 API 与组件

1. `loading -> ready`、refreshing 保留旧数据、timeout/error/retry、403。
2. 三 Tab 独立 rank/selection，三级联动、服务端 selection 纠正。
3. 快速切换时旧响应不能覆盖新响应。
4. 名称、主指标、领涨、Heat、成员和地域 breadth 的可见断言。
5. 长名称、null、负数、大金额和 `INVALID`。
6. 7 行可视区/内部滚动、稳定高度和键盘操作。
7. mock source 关闭时绝不 fallback 到 mock。

### 8.5 性能与像素

1. API 同机房 P95 `<250ms`、P99 `<500ms`、payload `<120KB`、SQL round trips `<=8`。
2. 单日 Heat P95 `<60s`；60 个有效交易日回放记录每日日志、均值/P95 和失败恢复。
3. 行业/概念/地域与所有状态保存 `1564 × 680` 截图；普通 UI 偏差 `<=2px`。
4. 首页 `1600 × 1200` 截图确认其它模块宽度/图表位置未变化；板块模块增高只改变后续文档流位置。

实现完成后的固定命令：

```bash
# Foundation / biz Heat / app-ops 装配 / 访问边界 / 后端真实路由 / 架构边界
pytest -q \
  tests/test_extended_models.py \
  tests/test_foundation_table_model_registry.py \
  tests/test_wealth_sector_serving_constraints.py \
  tests/test_wealth_sector_serving_migration.py \
  tests/test_wealth_sector_heat_contract.py \
  tests/test_wealth_sector_heat_materialization_service.py \
  tests/test_wealth_sector_heat_task_execution.py \
  tests/test_wealth_sector_database_access_boundaries.py \
  tests/test_cli_ops_runtime.py \
  tests/web/test_wealth_market_sector_overview_api.py \
  tests/architecture/test_subsystem_dependency_matrix.py

# Wealth 类型、真实 API 行为与构建
cd wealth
npm run test -- market-overview-sector-overview-real-api
npm run typecheck
npm run build

# DG 仅验证 hierarchy 发布（实现时创建对应测试）
cd ../lake_console/orchestrator
uv run python -m pytest -q tests/test_wealth_sector_hierarchy_prod_core.py
uv run ruff check src/orchestrator/defs tests/test_wealth_sector_hierarchy_prod_core.py

# 仓库文档与补丁完整性
cd ../..
.venv/bin/python scripts/check_docs_integrity.py
git diff --check
```

`uv run dg check defs` 只用于确认 hierarchy Definitions 可加载，按 DG 运维规则单独执行并记录结果；它不授权 job、materialize、backfill、runless event 或任何数据写入。仓库静态门禁还必须确认没有任何 Heat DG 定义被加载。

---

## 9. 性能与查询预算

### 9.1 API 最多 8 次数据库往返

| 次数 | 查询 |
|---:|---|
| 1 | trading day / source state |
| 2 | hierarchy（行业；缓存命中可省） |
| 3 | 当前 view 候选 metrics + leader |
| 4 | Heat ranking/association（概念） |
| 5 | 最终详情板块有效池 +聚合计数 |
| 6 | 最终详情成员 Top5 |
| 7 | Heat history（概念） |
| 8 | 预留 debug/source audit；非 debug 应尽量省略 |

不得用 N+1 消耗预算。行业 15 行、概念 20 行、地域 31 行均在 SQL 排序后有界返回。

### 9.2 prod-native Heat 读取与计算预算

1. 所有输入只读 prod 正式表，并按目标概念、交易日和 25/6/5 日等冻结窗口有界查询；不得扫描全历史。
2. 资金流读取 `t-9..t` 共 10 个有效交易日，涨停读取 `t-5..t` 共 6 个有效交易日；窗口由交易日历解析，不能用自然日替代。
3. 大型成员代码集合使用临时值关系、数组绑定或数据库等价批量方式，禁止每个概念一次 SQL。
4. 每日 TaskRun 节点记录逐来源行数与 canonical source hash，以及 SQL、计算、写入和 read-back 耗时；不记录文件数或 Gold 元数据。
5. 单日计算应复用已加载的来源 bundle，不允许 contract 内部重新访问数据库。
6. 生产只读验收表明 85 日有效池单次聚合超过 60 秒，而 10 日批次约 7.4-16.7 秒；正式物化必须按单交易日查询，历史 plan 审计批次不得超过 10 个交易日，并设置数据库 statement timeout，禁止整窗大查询。

---

## 10. 分阶段实现与提交边界

### Slice 0：文档冻结与生产只读证据

1. 复核层级 496/31/128/337。
2. 记录 member pair、重复率、最大单板成员。
3. 按 prod 有效池唯一口径对账证券资格、停牌、日线和成员固定样本。
4. 验证 `board_moneyflow_dc`、`equity_limit_list` 等全部必需来源的目标日期、唯一键、零行完成证据、代码覆盖率和有界查询计划。
5. 输出 60 个有效交易日、warm-up 日期与缺口台账；缺口日期不得计入 60 日。

未通过时停止，不进入 Heat 计算、回放或应用切换。

### Slice 1：实施日迁移基线

本需求迁移创建时重新查询 Alembic head，本地仓库与生产均为单 head `20260812_000133`，因此 revision 使用 `down_revision = 20260812_000133`。2026-08-13 部署后再次只读验收，仓库与生产当前单 head 已推进为 `20260813_000135`；`000134` 两张表迁移已位于有效链上，后续新增迁移必须接真实 head `000135`，不得继续引用本需求创建时的旧 head。

### Slice 2：Foundation + migration 与现有连接复用

只新增两表模型、注册、迁移和模型测试；迁移给既有 `lake_raw_writer` 增加 hierarchy 单表 `SELECT/INSERT/DELETE`。Web/Heat 复用现有应用连接，DG 复用现有 prod write resource；完成双 Session 事务隔离、组件 SQL 范围、DG 精确对象授权和 secret 不泄漏测试，不新增账号、DSN 或配置项。

实施记录（2026-08-13）：已新增两表 ORM、模型注册、revision `20260813_000134`、约束正反例和迁移范围测试。部署后生产只读验收确认当前 head 为 `20260813_000135`，hierarchy/Heat 分别为 15/31 列、4/18 个约束、各 4 个索引且迁移验收时均为 0 行；既有 `lake_raw_writer` 对 hierarchy 的 `SELECT/INSERT/DELETE` 为真，`UPDATE/TRUNCATE` 为假。hierarchy 随后在 Slice 3 正式发布，Heat 随后在 Slice 5 正式发布。

### Slice 3：DG hierarchy -> prod hierarchy

实现唯一 DG hierarchy asset、prod write contract、read-back 和测试；先本地/测试库，再单独生产发布验收。DG 不得出现 Heat 计算、存储或自动化。

实施记录（2026-08-13）：已新增 `prod_core_wealth_sector_hierarchy`、固定 Silver 文件读取/校验、hierarchy-only SQL contract、单事务全表替换和 canonical hash read-back；已登记 serving schema、catalog 和无分区模型。隔离测试覆盖 496/31/128/337、唯一键、父子/根/路径/叶节点闭包、版本、写入失败、read-back 篡改回滚，以及 DG Heat/job/sensor/check/bootstrap 清零。`dg check defs` 通过后，正式 Run `e875b632-dfb4-4898-a577-944ffa51de95` 已发布 496 行；生产 read-back 为 31/128/337、闭包全绿，source/prod hash 均为 `5094c9f1b0cfd51890351a8d6ecb6d2e0dc7ee4d1de816b5cb3ccf9946ce3525`。

### Slice 4：60 日 prod 来源缺口闭环

按缺口台账修复或补齐生产来源，重新核验来源表枚举、日期、数量、唯一键、零行完成证据和资金流代码覆盖率；冻结 60 个有效交易日及 warm-up 集合。

实施记录（2026-08-13）：目标窗冻结为 `2026-05-20..2026-08-12` 共 60 个连续 SSE 开放日，warm-up 为 `2026-04-10..2026-05-19` 共 25 日。九张 prod 来源完成只读对账：概念成员与资金流每日覆盖全部目标概念，资金流代码覆盖率为 100%，成员 pair 为 31,717-71,132、单板最大 3,850；所有可报价成分均有股票日线，真实缺行情为 0；涨停每日 29-152、停牌每日 1-57，无物理零行日，停牌 `(trade_date, ts_code, suspend_type)` 重复为 0。`BK0636.DC/B股` 每日无有效 A 股成分，按 `INVALID` 处理。`dc_daily` 四个日期的局部缺行与 Prod Raw 完全一致，按已批准源站现状口径归入逐概念 `INVALID`，没有可补写的 Goldenshare 落库缺口。Slice 4 据此闭环，不写来源表。

### Slice 5：prod-native Heat 与回放

实现 biz 来源查询、配置解析、有效池、纯计算 contract 和原子发布；实现 ops generic executor port 与 app 装配；通过正式 TaskRun 完成至少 60 个有效交易日的 plan/apply、read-back、重放一致性与性能验收。

实施记录（2026-08-13）：本地实现与专项回归已通过；生产正式 PLAN TaskRun `8149` 冻结 `2026-05-20..2026-08-12` 共 60 units、0 gaps、`apply_ready=true`。首次 APPLY TaskRun `8152` 从旧到新完成 60/60、0 失败，发布 29,665 行，其中 16,756 `VALID`、12,909 `INVALID`；60 个节点全部成功、issue 为 0，逐日行数、状态数、config/source/content hash 均与 PLAN 一致。单日平均 `9.806s`、P95 `11.253s`、最大 `11.421s`。幂等重放 TaskRun `8153` 再次完成 60/60、0 失败、`rows_saved=0`；Heat 行数、日期范围和 `calculated_at` 范围不变，最终全量 canonical content hash 复算仍为 60 日 0 差异。最新日 `2026-08-12` 为 503 行、477 `VALID`、26 `INVALID`，最近 20 日有效率 `94.50%`。

### Slice 6：后端 V2

先冻结 schema 与真实路由测试，再替换 query/service/status；只读 prod hierarchy/Heat/行情/成员事实，不得保留 V1 DTO 或运行时 Heat 计算。

实施记录（2026-08-13）：已将同一路由后端原子替换为 `view` 判别式 V2 DTO，严格拒绝未知、重复、跨视图与隐藏参数；新增 `SectorHierarchyQuery/SectorMetricsQuery/SectorHeatQuery/SectorMemberQuery/SectorSelectionResolver`，删除 V1 固定八列查询。行业按真实父子节点返回 5/2/3 等有界列并由服务端修正完整选择路径；概念支持四种排序、同日 Heat、20 日升序历史且无效点不填充；地域返回固定生产枚举 31 项且无层级/Heat 字段。详情复用有效 A 股池并只为最终节点查询一次成员 Top5，领涨只取 `dc_index`，`changePct` 固定取 `dc_daily`。10 个真实路由场景与 Heat/Ops/迁移/架构共 86 项相关回归通过。生产只读调用在 `2026-08-12` 三视图均为 `READY`：行业 5/2/3、概念 20+20、地域 31；不含只读事务设置的应用 SQL 往返为 7/8/6，payload 为 4.3/13.1/8.7KB，均通过 `<=8` 与 `<120KB`。本机跨网络单次耗时不能替代同机房 P95；该门禁待前后端同窗口部署后验收。后端契约已破坏性替换，Slice 7 完成前禁止单独部署。

### Slice 7：前端三工作台

先 controller 和稳定骨架，再行业、概念、地域、详情；最后删除旧结构并做真实 API/像素验收。

实施记录（2026-08-13）：已将前端 API 类型破坏性替换为 V2 判别式 workspace，删除旧 adapter 和 `MarketOverview` mock 中的 8 列/20 格 fixture；板块交互状态下沉至 `useSectorOverviewController`，三个 Tab 各自保存 rank/selection，使用 AbortController 与递增 request id 阻止 stale response，并消除服务端 selection 回写造成的重复请求。`SectorOverviewPanel` 已实现固定 680px 骨架、行业三级列、概念 Top20/Heat 历史、地域 31 项/涨跌分布、共享领涨股/成分 Top5、Loading/Ready/Partial/Delayed/Empty/Error/Forbidden、5 秒超时/重试和 Tab 左右/Home/End 键盘切换。真实 API 测试覆盖三视图、Heat/成员/地域可见结果、旧响应隔离、403、debug、超时与无 mock fallback；全量 Wealth 为 33 个文件、192 项通过，typecheck/build 通过。由于本地新 Wealth 端口没有可复用登录态，未完成真实页面截图；该项必须随前后端同窗口部署做最终验收。

### Slice 8：发布

迁移及既有账号 hierarchy 对象授权 -> 层级 -> 来源缺口闭环 -> 60 日 Heat -> 最新日 -> 后端 -> 前端同窗口切换 -> smoke/性能/截图。每个 Slice 独立提交，不混入其它模块。

---

## 11. 发布、回滚与观测

### 11.1 发布前硬门禁

1. 实施日 Alembic 单 head 已记录。
2. 全部生产来源真实只读对账通过，60 个有效交易日与 warm-up 集合已冻结；日期级缺口已清零，源站局部缺行已冻结为逐概念 `INVALID` 证据。
3. 层级 prod read-back 为 496/31/128/337 且 hash 一致。
4. Heat 至少 60 个有效交易日全部通过业务 contract、TaskRun 节点验收和 prod read-back；不以自然日、缺口日或 warm-up 凑数。
5. 最近交易日 Heat 来源日期一致、有效率/等级分布/日度跳变已人工审阅。
6. 现有连接复用、DG hierarchy 对象授权、组件访问边界和 Heat/Ops 双 Session 事务隔离测试通过，app 已注入 Heat executor，且依赖测试证明没有 `ops -> biz`。
7. 后端和前端真实 API、性能、六态和像素测试通过。

### 11.2 回滚

1. 应用回滚到切换前版本；新表保留诊断，不删除、不清空。
2. Heat 单日业务事务失败时整日回滚，保留此前成功交易日；不得用 TaskRun 状态事务回滚业务数据。
3. TaskRun 遇到来源、contract、数据库写入或 read-back 失败时停止后续日期，记录失败节点；修复后按相同 plan hash 从最后成功日续跑。
4. 不恢复旧 DTO 别名，不让 V2 前端连接 V1 后端或反向混用。

### 11.3 观测

1. DG hierarchy：运行标识、Silver/prod 行数、31/128/337 层级计数、source hash 与 prod read-back hash。
2. Ops TaskRun：plan hash、目标/有效/warm-up/缺口日期、逐日节点状态、来源行数/hash、失败 reason 和续跑位置。
3. API：`SO_*` 数量、view/status、响应耗时、SQL round trips、payload。
4. 数据：有效/无效 Heat 比例、invalid reason 分布、member/coverage 分布、等级分布和 score 日跳变。
5. 观测写入失败不得回滚、阻断或污染 Heat 及其它业务数据事务；仅影响本次观测状态。

---

## 12. 计划硬口径到代码与测试的映射

| 硬口径 | 代码落点 | 必须测试 |
|---|---|---|
| 盘后、非实时 | biz Heat materialization + API `tradeDate/asOf` | 无分钟字段、无盘中回退 |
| 行业三级各 Top5 | selection resolver + hierarchy query | 父子范围、5 行、无子级 |
| 概念 Top20/地域 31 | metrics/heat query | 精确上限/数量与稳定排序 |
| 领涨只来自 dc_index | metrics query | member Top1 不得覆盖 leader |
| 有效 A 股池 | prod query + 单一 golden contract | B 股/上市/退市/停牌/缺行情，不得访问 Lake |
| Heat EOD V1 | 策略配置中心 + pure contract | golden、缺分量、不补权、no-lookahead、未知配置严格失败 |
| Web 不算事实 | response DTO + presentation-only adapter | null 不补 0、badge 不推导 |
| 来源同日 | prod source query + quality contract | 错日必须阻断，不得以其它日期替代 |
| 原子发布 | 单日 prod DB transaction + read-back | 失败保留旧成功交易日 |
| biz/ops/app 边界 | ops executor port + app adapter + CLI factory consumer | ops 不得 import biz，CLI 不得直构未装配 worker，状态事务不得影响业务事务 |
| 现有连接复用与访问边界 | Web/Heat 使用 `DATABASE_URL`，DG 使用 `ProdPostgresWriteResource`；Heat/Ops 独立 Session/事务 | DG 写 Heat、Heat 写来源/hierarchy、Web DML、运行时 DDL/`TRUNCATE` 被测试阻止 |
| DG Heat 清零 | hierarchy-only Definitions + 静态扫描 | asset/partition/check/sensor/Gold/history CLI 不存在 |
| V1 清零 | schema/API/frontend 同提交 | 旧字段/旧组件/旧 fixture 不存在 |
| 60 日回放 | Ops TaskRun plan/apply | 旧到新、checkpoint、缺口/warm-up 不计数、失败停止 |
| Alembic 真 head | 实施步骤 | 单 head 与真实 down_revision |

---

## 13. 当前仍未完成但不需要产品拍板的事项

1. 前后端 V2 必须作为一个发布单元部署；不得以当前本地完成状态单独上线任一侧。
2. 最终上线证据：首页真实 API smoke、同机房 P50/P95/P99、三视图与六态同尺寸像素截图，以及 `SO_*`/Heat 覆盖率观测。
3. 真实页面确认 Tab/rank/selection、列表内部滚动、成员跳转和地域涨跌分布；不得用 jsdom 组件测试替代浏览器验收。

如果上述工程门禁发现真实数据与已冻结产品口径冲突（例如地域不再是 31 个、有效池定义无法用事实字段表达、Heat 大面积无效），必须回到产品评审；在出现这种证据前无需新增决策。

---

## 14. 版本记录

| 版本 | 日期 | 变更摘要 |
|---|---|---|
| v2.10 | 2026-08-13 | 记录 Slice 7 前端 V2 实施：判别式 API 类型、独立 controller、三工作台、地域涨跌分布、六态、键盘与 stale 防护完成，V1 DTO/adapter/fixture 清零；Wealth 192 项测试、typecheck/build 通过，真实页面像素/同机房性能待部署后验收 |
| v2.9 | 2026-08-13 | 记录 Slice 6 后端 V2 实施、86 项回归和生产只读三视图验收；应用 SQL 7/8/6、payload 均达标，同机房 P95 待原子发布；后端禁止单独部署 |
| v2.8 | 2026-08-13 | 记录正式 PLAN `8149`、首次 APPLY `8152` 与幂等重放 `8153` 的生产结果：60 日 29,665 行、逐日 hash 0 差异、重放 0 写入、物化 P95 约 11 秒；Slice 5 完成，下一步为后端 V2 |
| v2.7 | 2026-08-13 | 记录首次正式 PLAN TaskRun `8147` 的门禁未通过结果：生产资金流 85 日完整，根因是代码把 `content_type='概念'` 错写成 `概念板块`；修正来源过滤与测试 fixture，并新增错误枚举负例，待重新部署复跑 PLAN |
| v2.6 | 2026-08-13 | 记录 Slice 5 本地实现：严格 Heat 配置、prod 来源与有效池、两位最终分、REPEATABLE READ、单日发布/read-back、PLAN/APPLY 与 snapshot integrity、断点跳过、Ops/app/CLI 双事务装配及本地回归；生产回放仍待部署后分阶段验收 |
| v2.5 | 2026-08-13 | 记录 hierarchy 正式 Run 与 hash read-back、Slice 4 冻结 60+25 日并完成九张 prod 来源审计；日期级缺口清零，源站现状局部缺行改为逐概念 `INVALID`，并将历史审计限制为最多 10 日批次 |
| v2.4 | 2026-08-13 | 记录生产已升级至单 head `20260813_000135`，两表结构与 hierarchy 精确授权验收通过；Slice 3 hierarchy publisher 已实施并通过隔离测试，正式生产发布仍待部署后单独执行 |
| v2.3 | 2026-08-13 | 记录 Slice 1/2 已实施的 ORM、模型注册、revision `20260813_000134` 与本地约束/迁移测试；本提交 head 为 `000134`，生产仍为 `000133`，生产迁移与后续阶段未执行 |
| v2.2 | 2026-08-13 | 撤回三账号/三 DSN 设计；Web/Heat 复用现有应用连接，DG 复用现有 prod write resource；保留 Heat/Ops 双 Session 事务隔离和既有 `lake_raw_writer` hierarchy 单表授权 |
| v2.1 | 2026-08-13 | Heat 改为 biz prod-native 计算与直接发布；ops 仅承载执行意图/状态/观测，由 app 注入执行器；删除 DG Heat、Gold 双份事实和 Lake/prod 双 adapter；三账号/三 DSN 门禁已由 v2.2 撤回 |
| v2 | 2026-08-12 | 历史基线：曾按 DG Heat/Gold 与 Lake 优先设计，已被 v2.1 全面替代，不得用于实施 |
