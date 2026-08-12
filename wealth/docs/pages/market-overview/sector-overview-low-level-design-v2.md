# 市场总览｜板块速览低层设计 v2（LLD）

> 状态：编码前技术评审稿；本文件不授权业务代码、数据库迁移、DG 物化或生产写入。
> 日期：2026-08-12
> 需求基线：[sector-overview-benchmark-requirement-v2.md](./sector-overview-benchmark-requirement-v2.md)
> 实施方案：[sector-overview-implementation-design-v2.md](./sector-overview-implementation-design-v2.md)
> 编码门禁：[sector-overview-m2-coding-gate-v2.md](./sector-overview-m2-coding-gate-v2.md)

---

## 1. 结论与开工边界

### 1.1 本 LLD 冻结的实现结论

1. V2 仍使用现有 `GET /api/v1/wealth/market/sector-overview`，前后端在同一发布单元原子替换旧 DTO；不保留 V1/V2 双契约、别名字段或兼容 adapter。
2. 行业层级通过 `silver_dc_industry_hierarchy -> prod_core_wealth_sector_hierarchy -> core_serving.wealth_sector_hierarchy` 发布，Web 不读 Parquet。
3. 概念热度通过日期分区 Gold 资产离线计算，再按交易日发布到 `core_serving.wealth_sector_heat_daily`；Web 请求不计算 Heat。
4. Heat 离线链优先消费已经存在的正式 Lake 事实：`silver_dc_index/silver_dc_member/silver_dc_daily/silver_stock_lifecycle/silver_stock_suspend_daily/silver_stock_daily`。
5. 当前 DG 没有正式等价 Lake 资产的 `board_moneyflow_dc` 和 `equity_limit_list`，首版仅通过 `ProdPostgresResource.connect_readonly_transaction()` 做按日期有界读取。
6. DG 与 Web 使用同一套 `EffectiveAStockPool` 语义和同一组 golden cases，但分别由 Lake adapter 与 PostgreSQL query adapter 实现；禁止 `biz` 依赖 DG runtime，也禁止 DG import `biz`。
7. 新 ORM 必须进入 `src/foundation/models/core_serving/**`，并在 `core_serving/__init__.py`、`all_models.py` 和模型注册测试中登记；不放入 legacy 或错误的 `models/core/**` 路径。
8. Heat 使用独立动态分区集 `cn_a_wealth_sector_heat_trade_days`；它不复用股票或任一 DC 数据族的分区集。
9. 本轮没有新的产品决策待确认。剩余未通过项是生产数据证据、性能、回放、迁移和发布验收门禁。

### 1.2 当前事实快照

| 项目 | 当前结论 |
|---|---|
| Git 分支 | `dev-interface` |
| Alembic head（本次审计） | `20260811_000132`；实施迁移前必须重新读取，本文不得作为未来 `down_revision` |
| 当前 API | V1 `columns[] + heatMapItems[]` |
| 当前后端来源 | `core_serving.dc_daily/dc_index/board_moneyflow_dc` |
| 当前前端 | 4×2 排名列 + 5×4 涨跌热力格，仅 loading/ready/error |
| 行业层级 Lake | 现有单文件正式 Silver，契约要求 496 行、31/128/337 |
| 股票资格 Lake | 现有 `silver_stock_lifecycle`，来自 `stock_basic` 全状态 CNY 股票生命周期 |
| 股票停牌 Lake | 现有 `silver_stock_suspend_daily[trade_date]`，允许已证实的零行分区 |
| 股票行情 Lake | 现有 `silver_stock_daily[trade_date]`，按生命周期/CNY/北交所日期过滤 |
| 仍需 prod 只读 | `core_serving.board_moneyflow_dc`、`core_serving.equity_limit_list` |

### 1.3 禁止项

1. 不在页面、adapter 或 API handler 里计算热度、层级、有效池或排序事实。
2. 不按名称模糊关联资金流，不按股票代码前缀判断 A/B 股，不用“有行情”反推上市或停牌。
3. 不把 prod PostgreSQL serving 当成 Gold 的历史真相源；Heat 必须可由冻结输入和配置独立重建。
4. 不增加 Redis、实时行情、分钟刷新、20 分钟变化或盘中加速度。
5. 不新增 Kopia、旧 Lake 路径或来源业务表写入。
6. 不在迁移中回填数据、删除来源表、`drop-before-create` 或调用 Lake/Tushare。
7. 不继续向已超过 400 行的 `MarketOverviewPage.tsx` 堆叠板块交互状态。

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
2. `lake_console/orchestrator` 新增一条 Gold/serving 发布链。
3. `biz` 继续只依赖 `foundation`。
4. `app` 只保留现有路由聚合，不增加业务规则。

---

## 3. 目标文件结构

```text
src/foundation/models/core_serving/
  wealth_sector_hierarchy.py
  wealth_sector_heat_daily.py
  __init__.py
src/foundation/models/all_models.py
alembic/versions/<implementation-day-revision>_add_wealth_sector_overview_serving.py

lake_console/orchestrator/src/orchestrator/defs/
  assets/wealth_sector_overview.py
  assets/wealth_sector_overview_prod_core.py
  asset_guards/wealth_sector_overview_lake_readiness.py
  checks/wealth_sector_overview_checks.py
  config/wealth_sector_heat.cn_a.v1.json
  jobs/wealth_sector_overview.py
  sensors/wealth_sector_overview_sensor.py
  bootstrap/wealth_sector_heat_history.py
  bootstrap/wealth_sector_heat_history_cli.py
  prod_db/wealth_sector_overview.py
  wealth_sector_heat_contract.py
  partitions.py
  paths.py
  catalog/lake_assets.py
  run_contracts/asset_column_schemas.py

src/biz/
  api/wealth/market/sector_overview.py
  schemas/wealth/market/sector_overview.py
  queries/wealth/market/sector_overview/
    sector_overview_state_query.py
    sector_hierarchy_query.py
    sector_metrics_query.py
    sector_heat_query.py
    effective_a_stock_pool_query.py
    sector_member_query.py
    sector_overview_query_service.py
  services/wealth/market/sector_overview/
    sector_selection_resolver.py
    sector_overview_status_resolver.py
    sector_overview_exception_builder.py

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

1. 实施日先运行 `alembic heads`，只允许单 head；若不再是 `20260811_000132`，迁移接新的真实 head。
2. upgrade 顺序：create hierarchy -> constraints/indexes -> create heat -> constraints/indexes。
3. migration 不做 `DROP TABLE IF EXISTS`、数据回填、外部访问或来源表 DML。
4. downgrade 仅删除本次两张表，先 heat 后 hierarchy。
5. SQLite 单测若不支持某些 PostgreSQL check 表达式，测试数据库兼容只能在测试装配层解决，不能弱化生产约束。

---

## 5. DG 资产 LLD

### 5.1 分区与路径

新增：

```python
cn_a_wealth_sector_heat_trade_days = dg.DynamicPartitionsDefinition(
    name="cn_a_wealth_sector_heat_trade_days"
)
```

Gold 正式路径：

```text
/Volumes/datasource/data_lake/gold/wealth/sector_heat_daily/
  trade_date=YYYY-MM-DD/part-000.parquet
```

候选文件必须位于 `/Volumes/datasource/data_lake_staging`，校验后以同文件系统 `os.replace()` 提升。层级 serving 不产生第二份 Lake 文件，直接消费现有 Silver 快照。

资产依赖表达：

1. Gold 对目标日 `silver_dc_index/silver_dc_member/silver_dc_daily/silver_stock_daily/silver_stock_suspend_daily` 使用 `dg.AssetDep(..., partition_mapping=dg.IdentityPartitionMapping())`，即不同数据族分区集之间只映射相同日期 key。
2. Gold 对无分区的 `silver_stock_lifecycle` 使用普通 `AssetDep`。
3. 前置 25/5 日窗口无法由异构 dynamic partition set 的默认映射完整表达，必须由 readiness guard 显式解析和核验每个日期文件/check，并把实际依赖分区列表写入 materialization metadata；禁止依赖“目录里碰巧有文件”。
4. prod 资金流和涨停不是 DG asset，不伪造资产依赖；其目标/历史日完成证据由 readiness guard 和只读提取审计记录。
5. 新 Gold 与 prod serving 共用 `cn_a_wealth_sector_heat_trade_days`，serving 对 Gold 使用 Identity partition mapping。

### 5.2 输入适配与范围

| 事实 | Heat 计算输入 | 范围 | Web 详情输入 |
|---|---|---|---|
| 板块目录/领涨 | `silver_dc_index[t]` | 目标日概念集合 | `core_serving.dc_index` |
| 板块日线 | `silver_dc_daily[t-25..t]` | 已完成交易日窗口 | `core_serving.dc_daily` |
| 板块成员 | `silver_dc_member[t-5..t]` | 仅概念代码 | `core_serving.dc_member` |
| 股票资格 | `silver_stock_lifecycle` | 按每个计算日投影 | `core_serving.security_serving` |
| 停牌 | `silver_stock_suspend_daily[t-5..t]` | `suspend_type='S'` | `core_serving.equity_suspend_d` |
| 股票日线 | `silver_stock_daily[t-5..t]` | 仅相关成员 | `core_serving.equity_daily_bar` |
| 资金流 | prod `board_moneyflow_dc[t-4..t]` | 概念、非空代码 | 同表 |
| 涨停 | prod `equity_limit_list[t-5..t]` | `limit_type='U'`、相关成员 | 同表 |
| 历史 Heat | 既有 Gold 分区 | `t-2..t-1`，只算变化/确认 | serving 表 |

`silver_dc_index` 只需目标日概念身份和页面领涨事实，不读取无业务用途的 5 日窗口。`silver_dc_daily` 为活跃度基线至少提供 `t-20..t-1`，再为复算前 5 个 base rank 留足 warm-up，因此上界按 25 个已完成交易日规划，实际日期集合由交易日历产生。

### 5.3 `EffectiveAStockPool` 纯语义

对每个 `calculation_date + sector_code`：

```text
sourceMembers = DISTINCT dc_member.con_code

eligibleMembers = sourceMembers
  INNER JOIN lifecycle ON lifecycle.ts_code = con_code
  WHERE lifecycle.is_cny_stock = true
    AND lifecycle.list_status IN ('L', 'D')
    AND lifecycle.list_date <= calculation_date
    AND (lifecycle.delist_date IS NULL OR lifecycle.delist_date > calculation_date)

suspendedMembers = eligibleMembers
  INNER JOIN suspend ON same ts_code/date AND suspend_type = 'S'

quoteEligibleMembers = eligibleMembers - suspendedMembers
validQuoteMembers = quoteEligibleMembers INNER JOIN stock_daily ON same ts_code/date
missingQuoteMembers = quoteEligibleMembers - validQuoteMembers
```

语义说明：

1. Lake 的 `silver_stock_lifecycle` 来自 Tushare `stock_basic` 股票域（该接口行天然属于股票证券）并显式保留 `list_status`、CNY 和生命周期，因此承担离线侧 `EQUITY + CNY + L/D + 上市/退市日期` 资格事实；不再额外读 prod `security_serving`。
2. Web 侧仍用 `security_serving.security_type='EQUITY' AND curr_type='CNY'` 表达同一语义，因为 Web 不允许读 Lake。
3. 两个 adapter 共用固定输入输出案例：B 股、未来上市、退市生效日、全日停牌、复牌记录、可报价但无日线、重复成员。
4. `source_member_count/member_count/suspended_count/quote_eligible_count/valid_quote_count/missing_quote_count` 必须由同一个关系查询一次产出，不允许分散查询后在 Python 猜差值。

### 5.4 Heat 配置加载

`wealth_sector_heat_contract.py` 负责：

1. 加载并严格校验 `wealth_sector_heat.cn_a.v1.json`。
2. 生成 canonical JSON 和 SHA-256 config hash。
3. 验证总权重/子权重、阈值顺序、窗口、覆盖率和 `scoreVersion`。
4. 提供纯计算函数：winsor、平均秩 percentile、线性斜率、五分量、base score/rank、final score/rank、等级、变化和两日趋势确认。
5. 所有排序最终增加 `sector_code ASC`，避免数据库/并列值不稳定顺序。

禁止在 asset 文件里复制公式常量；配置值只允许这个 contract 消费。

### 5.5 Gold 写入步骤

`gold_wealth_sector_heat_daily[trade_date]` 单分区执行：

1. 用交易日历解析目标日、25 日 warm-up 和 5 日复算窗口；任何自然日替代都失败关闭。
2. 用 readiness guard 验证所需 Lake 文件、checks 和两个 prod 数据集完成证据。
3. 一次提取当日概念集合和有界历史源；prod SQL 必须显式列名、日期范围和代码范围。
4. 在 DuckDB 中去重成员并构造逐日有效池、覆盖计数和原始特征。
5. 对每个需要复算的历史日做横截面 winsor/percentile/base rank；不读取未来输入。
6. 计算目标日 persistence、final score/rank、level、delta 和 trend。
7. 为当日所有概念保留一行；质量失败写 `INVALID + reason`。
8. 将候选文件写入 staging，运行文件级 contract audit。
9. 同文件系统原子提升到 Gold 正式路径。
10. 返回 materialization metadata：输入日期、行数、hash、配置版本/hash、有效/无效分布、计数分布、耗时和 readiness 证据。

### 5.6 Asset checks

所有 Heat check 使用 `asset=gold_wealth_sector_heat_daily`、相同 `partitions_def` 且 `blocking=True`：

| check | 断言 |
|---|---|
| `gold_wealth_sector_heat_daily_contract_check` | schema、类型、PK、枚举、范围、行状态不变量 |
| `..._source_date_check` | 必需来源日期与分区日/窗口一致 |
| `..._identity_check` | 当日概念集合全覆盖，无无来源额外行 |
| `..._formula_check` | 固定抽样复算与 config hash 一致 |
| `..._distribution_check` | rank 唯一连续、等级与阈值一致、异常比例可解释 |
| `..._history_check` | delta/trend/persistence 无前视，历史断点不填充 |
| `..._effective_pool_check` | 六类计数恒等式及排除/停牌/缺行情样本可回溯 |

层级 serving 在发布函数内先调用现有层级文件 contract，再做 prod read-back；不修改 `silver_dc_industry_hierarchy` 的手工 seed、无分区和单文件身份，也不为它增加自动重建 sensor。

### 5.7 Prod serving 发布

`prod_core_wealth_sector_hierarchy`：

1. 无分区，显式人工运行或在部署流程中运行。
2. 单事务中将新快照写入临时 SQL 关系、核验后替换正式表；若采用 delete+insert，read-back 必须在同一事务内完成。
3. read-back 必须验证 496、31/128/337、父子闭包、版本和 canonical hash。

`prod_core_wealth_sector_heat_daily[trade_date]`：

1. 依赖同分区 Gold 和全部 blocking checks。
2. 使用 `ProdPostgresWriteResource.connect()`。
3. 单事务 `DELETE WHERE trade_date=%s` + `executemany INSERT` + 显式列 read-back。
4. read-back 比较完整 canonical rows hash、行数、`score_version` 和日期；失败回滚，保留上次成功分区。
5. `prod_db/wealth_sector_overview.py` 不 import ORM，不写 `created_at/updated_at` 隐式字段，不使用 `SELECT *`。

### 5.8 Job、sensor 与 60 日回放

1. Job：`wealth_sector_heat_daily_update_job`，选择 Gold、Gold checks 和 prod serving；单分区、in-process executor。
2. Sensor：`wealth_sector_heat_daily_update_job_sensor`，只提交最早一个 actionable 交易日；成功、失败、checks 问题和 prod 未同步分别给出稳定 reason code。
3. 新分区注册由该数据族专属注册逻辑从正式交易日历产生；不得复用任一上游 dynamic partition set 名称。
4. readiness 同时要求三个 DC Silver、股票日线/停牌 Silver、股票生命周期快照及两个 prod 数据集完成证据。
5. `limit_list_d` 合法零行必须有目标日成功 TaskRun/日期完整性证据；资金流不可用不解释为零流入。
6. 历史入口：`wealth_sector_heat_history_cli.py plan/apply`。`plan` 只读，冻结 60 个发布日 + 25 个 warm-up 日、输入文件/来源证据和预计请求量；`apply` 需显式确认计划 hash。
7. 回放从旧到新，每日独立 run/事务/checkpoint；失败停在首个失败日，可从最后成功日续跑。
8. 不发 runless success，不在失败后自动跳日，不把 warm-up 日计入 60 日验收。

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

### 8.2 DG 单元与集成

| 组 | 必测正例 | 必测反例 |
|---|---|---|
| 配置 | V1 canonical config/hash | 权重不为 1、阈值逆序、版本未升 |
| 有效池 | CNY 上市股票、停牌扣分母 | B 股、未来上市、退市生效日、重复成员 |
| 行情覆盖 | 有效报价、合法零停牌 | 可报价无行情、停牌源缺失 |
| Heat | golden 五分量/总分/rank/level | 缺分量不补权、低覆盖 INVALID |
| 历史 | delta、两日确认、连续 Top20 | t+1 改动影响 t、断点填充 |
| 文件 | staging -> atomic replace | contract 失败不得覆盖正式文件 |
| serving | delete+insert+read-back hash | read-back 不同回滚保留旧分区 |
| sensor | 最早缺口单日 RunRequest | upstream 未 ready、check fail、prod fail 不重发 |
| replay | 60 日旧到新和 checkpoint | warm-up 混入验收、失败跳日 |

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
2. 单日 Heat P95 `<60s`；60 日回放记录每日日志、均值/P95 和失败恢复。
3. 行业/概念/地域与所有状态保存 `1564 × 680` 截图；普通 UI 偏差 `<=2px`。
4. 首页 `1600 × 1200` 截图确认其它模块宽度/图表位置未变化；板块模块增高只改变后续文档流位置。

实现完成后的固定命令：

```bash
# Foundation / 后端真实路由
pytest -q tests/test_extended_models.py tests/web/test_wealth_market_sector_overview_api.py

# Wealth 类型、真实 API 行为与构建
cd wealth
npm run test -- market-overview-sector-overview-real-api
npm run typecheck
npm run build

# DG 专项（实现时创建对应 test_wealth_sector_overview*.py）
cd ../lake_console/orchestrator
uv run python -m pytest -q tests/test_wealth_sector_overview*.py
uv run ruff check src/orchestrator/defs tests/test_wealth_sector_overview*.py

# 仓库文档与补丁完整性
cd ../..
.venv/bin/python scripts/check_docs_integrity.py
git diff --check
```

`uv run dg check defs` 是正式 Definitions 加载门禁，按 DG 运维规则单独执行并记录结果；它不授权 job、sensor、materialize、backfill、runless event 或任何数据写入。

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

### 9.2 离线读取预算

1. Lake 输入只读目标概念、25/5 日窗口；不得扫描 Lake 全历史。
2. prod 资金流最多 5 个交易日、概念代码集合；涨停最多 6 个交易日、相关成员集合。
3. 大型成员代码集合使用临时值关系/数组绑定或数据库等价批量方式，禁止每个概念一次 SQL。
4. materialization metadata 记录每个来源行数、字节/文件数、SQL 耗时、计算耗时、写入耗时。

---

## 10. 分阶段实现与提交边界

### Slice 0：M0 数据证据（只读）

1. 复核层级 496/31/128/337。
2. 记录 member pair、重复率、最大单板成员。
3. 对账 Lake 生命周期/停牌/日线与 prod 有效池 adapter 的固定样本语义。
4. 验证 `board_moneyflow_dc` 和 `limit_list_d` 目标日期、唯一键、零行完成证据、代码覆盖率和有界查询计划。
5. 输出 60 日回放日期集合与 warm-up 日期集合。

未通过时停止，不进入迁移或物化。

### Slice 1：Foundation + migration

只新增两表模型、注册、迁移和模型测试；重新确认 Alembic head。不得同步生产。

### Slice 2：层级 serving

实现 prod write contract、资产、read-back 和测试；先本地/测试库，再单独生产发布验收。

### Slice 3：Heat Gold

实现分区/路径/catalog/schema/config/contract/guard/asset/checks 和固定样本测试；暂不写 prod。

### Slice 4：Heat serving + automation

实现 prod write、job、sensor、history plan/apply；完成至少 60 个交易日回放后才能进入应用切换。

### Slice 5：后端 V2

先冻结 schema 与真实路由测试，再替换 query/service/status；不得保留 V1 DTO。

### Slice 6：前端 V2

先 controller 和稳定骨架，再行业、概念、地域、详情；最后删除旧结构并做真实 API/像素验收。

### Slice 7：发布

迁移 -> 层级 -> 60 日 Heat -> 最新日 -> 后端/前端同窗口切换 -> smoke/性能/截图。每个 Slice 独立提交，不混入其它模块。

---

## 11. 发布、回滚与观测

### 11.1 发布前硬门禁

1. 实施日 Alembic 单 head 已记录。
2. M0 全部真实只读对账通过。
3. 层级 prod read-back 为 496/31/128/337 且 hash 一致。
4. Heat 连续至少 60 个发布交易日全部通过 blocking checks 和 prod read-back。
5. 最近交易日 Heat 来源日期一致、有效率/等级分布/日度跳变已人工审阅。
6. 后端和前端真实 API、性能、六态和像素测试通过。

### 11.2 回滚

1. 应用回滚到切换前版本；新表保留诊断，不删除、不清空。
2. Heat 单日发布失败由事务回滚，保留上一成功分区；Gold 失败候选不提升。
3. sensor 遇到失败/check 问题停止自动重发，转人工按分区修复。
4. 不恢复旧 DTO 别名，不让 V2 前端连接 V1 后端或反向混用。

### 11.3 观测

1. DG：run key、分区、readiness reason、source hashes、check 结果、Gold/prod row hash。
2. API：`SO_*` 数量、view/status、响应耗时、SQL round trips、payload。
3. 数据：有效/无效 Heat 比例、invalid reason 分布、member/coverage 分布、等级分布和 score 日跳变。
4. 观测写入失败不得回滚或污染来源业务表；仅影响本次观测状态。

---

## 12. 计划硬口径到代码与测试的映射

| 硬口径 | 代码落点 | 必须测试 |
|---|---|---|
| 盘后、非实时 | Heat asset + API `tradeDate/asOf` | 无分钟字段、无盘中回退 |
| 行业三级各 Top5 | selection resolver + hierarchy query | 父子范围、5 行、无子级 |
| 概念 Top20/地域 31 | metrics/heat query | 精确上限/数量与稳定排序 |
| 领涨只来自 dc_index | metrics query | member Top1 不得覆盖 leader |
| 有效 A 股池 | 两 adapter + golden contract | B 股/上市/退市/停牌/缺行情 |
| Heat EOD V1 | config + pure contract | golden、缺分量、不补权、no-lookahead |
| Web 不算事实 | response DTO + presentation-only adapter | null 不补 0、badge 不推导 |
| 来源同日 | readiness + source date check | 错日必须阻断/降级 |
| 原子发布 | staging replace + DB transaction | 失败保留旧成功数据 |
| V1 清零 | schema/API/frontend 同提交 | 旧字段/旧组件/旧 fixture 不存在 |
| 60 日回放 | history plan/apply | 旧到新、checkpoint、warm-up 不计数 |
| Alembic 真 head | 实施步骤 | 单 head 与真实 down_revision |

---

## 13. 当前仍未完成但不需要产品拍板的事项

1. 生产只读 M0：member 规模/重复、涨停零行完成证据、有效池分类和两个 prod 查询计划。
2. DG 设计评审：新分区注册、readiness reason codes、7 个 blocking checks 与 60 日 plan/apply。
3. 数据库评审：两表约束、索引、事务替换和实施日 Alembic head。
4. 前后端评审：V2 判别式 DTO、状态机、请求 stale 防护和原子切换窗口。
5. 上线证据：60 日回放、同机房性能、真实 API 和像素截图。

如果上述工程门禁发现真实数据与已冻结产品口径冲突（例如地域不再是 31 个、有效池定义无法用事实字段表达、Heat 大面积无效），必须回到产品评审；在出现这种证据前无需新增决策。

---

## 14. 版本记录

| 版本 | 日期 | 变更摘要 |
|---|---|---|
| v2 | 2026-08-12 | 基于当前代码、DG 正式资产、V2 产品/技术方案和 CodeGraph 影响面形成编码级 LLD；校准股票生命周期、停牌和日线优先使用 Lake |
