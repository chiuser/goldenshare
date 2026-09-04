# 旧 Lake Console、Kopia 与旧湖迁移适配器清退 M0 只读审计清单 v1

状态：2026-08-28 M0 历史基线；2026-09-05 补充复核见 §15；未执行任何代码清退或数据删除

审计日期：2026-08-28

上位依据：

1. `docs/architecture/legacy-lake-console-and-kopia-retirement-plan-v1.md`
2. `lake_console/docs/design/legacy-lake-console-kopia-old-lake-bootstrap-retirement-low-level-design-v1.md`
3. 根 `AGENTS.md`、`lake_console/AGENTS.md`、`lake_console/orchestrator/AGENTS.md`

> 本清单只记录当前代码和文档事实，不替代上位方案或 LLD，不授权 M1–M7，也不授权删除代码、
> 文档、物理数据或本机环境。M0 发现的两个漏项已经回填 LLD，并重新得到未归类命中为 0；进入
> 后续实施轮次仍须用户单独授权。

> §1–14 保留 2026-08-28 的审计记录，不是当前永久事实。用户在 2026-09-05 将无用物理数据纳入专项，
> 原“物理旧湖另轮处理”和 5 分钟硬门禁已被上位方案及 LLD 新口径替代；当前矩阵为 154 份，不能再用
> 历史 145 份或当时未归类为 0 证明当前覆盖完整。最新边界与复核结果见 §15。

---

## 1. 本轮边界

### 1.1 允许动作

- [x] 读取 Git、CodeGraph、代码、测试、规则和文档。
- [x] 做静态引用、调用关系、路径存在性和 Git 跟踪边界审计。
- [x] 新增本清单，记录审计结论。

### 1.2 未执行动作

- [x] 未修改 Python、TypeScript、Shell、配置、迁移或测试代码。
- [x] 未删除任何旧 Console、Kopia、旧湖适配器或文档文件。
- [x] 未运行 Kopia。
- [x] 未连接数据库、Tushare、本机服务或远程服务。
- [x] 未读取、写入或删除 `/Volumes/datasource/goldenshare-tushare-lake`。
- [x] 未写正式 Lake、正式 staging、Dagster instance、动态分区或 runless event。
- [x] 未执行 `dg check defs`、materialize、backfill、job 或 sensor。
- [x] 未读取 ignored 配置内容；只核对精确路径是否存在、是否由 `.gitignore` 排除。
- [x] M0 只读审计阶段未提交或推送；本次闭环只提交 LLD 与本清单，不提交代码。

---

## 2. 审计基线

| 项 | M0 当前事实 | 判定 |
|---|---|---|
| 当前分支 | `dev-interface` | 符合当前仓库规则 |
| 当前 HEAD | `66a21e854659f26826e8bc6ad2836d49eaf622fe` | 本清单唯一代码事实基线 |
| `origin/dev-interface` | `060e2661b95283afc46b1277c6e318b396f9104c` | 当前分支 ahead 3；用户已确认 main/origin 追平不是本专项门禁 |
| LLD 原审计 HEAD | `c232889858d6fe93a3224bf65d3cdb682e4382f0` | 已与当前 HEAD 做差异复核 |
| CodeGraph | 2,815 files / 49,687 nodes / 126,215 edges | `Index is up to date` |

从 LLD 原审计 HEAD 到当前 HEAD，没有修改以下核心清退代码边界：

```text
lake_console/backend/**
lake_console/frontend/**
tests/lake_console/**
lake_console/orchestrator/src/orchestrator/defs/bootstrap/**
lake_console/orchestrator/src/orchestrator/defs/catalog/lake_assets.py
lake_console/orchestrator/src/orchestrator/defs/run_contracts/metadata.py
```

这段时间发生的代码变化主要属于 ETF、stk auction、Wealth sector analysis 和 Ops TaskRun；本次已按
当前 HEAD 重新读取 Ops Snapshot 保护链，不能沿用旧审计印象。

### 2.1 用户无关脏文件排除清单

M0 和本次闭环提交都不得修改、暂存或提交：

```text
docs/architecture/etf-basic-rebuild-and-downstream-data-audit-cleanup-low-level-design-v1.md
docs/architecture/etf-basic-rebuild-and-downstream-data-audit-cleanup-plan-v1.md
docs/datasets/stk-auction-o-dataset-development.md
docs/governance/prod-postgresql-raw-direct-serving-phase-one-lld-v1.md
docs/governance/prod-postgresql-storage-space-optimization-program-v2.md
wealth/docs/pages/wealth-exploration/sector-analysis-product-interaction-baseline-v1.md
```

---

## 3. M0 总结论

### 3.1 可以确认的事实

- [x] 旧 `lake_console/frontend + backend` 仍是封闭旧产品边界；当前正式代码没有导入它们。
- [x] Kopia 正向运行能力只在待删旧产品边界中；边界外只发现禁止 Kopia 的负向门禁。
- [x] `OLD_LAKE_BOOTSTRAP` / `old_lake_root` 确实是旧湖或历史备份迁入正式湖的一次性适配器，
  可以清退，但必须先迁走混合文件中的当前 helper 和 CLI。
- [x] `stk_mins_migration.py`、`stk_mins_migration_cli.py` 不能直接删除。
- [x] 28 个 `stk_mins_migration_cli` 子命令中，7 个是旧迁移命令，21 个是当前历史治理命令。
- [x] `stk_mins_raw_replace_from_prod` 不是旧湖/Kopia 适配器；能力必须保留并在 M4 重构。
- [x] Ops Dataset Status Snapshot、四个 Foundation Local Lake Reader、Wealth 分钟 API/页面、
  ClickHouse、BSE recovery、正式 Dagster 和 `lake_console/reports/**` 均不在删除范围。
- [x] 未发现需要扩大代码删除范围的新消费者。

### 3.2 已闭环的文档门禁

- [x] LLD 第 9.4 节文档矩阵已新增 2 个 `KEEP_CURRENT_VERIFY` 条目。
- [x] 矩阵已从 143 份变为 145 份，`KEEP_CURRENT_VERIFY` 已从 13 份变为 15 份。
- [x] 已重新运行相同的三路扫描，未归类命中、重复路径、不存在路径均为 0。

因此，M0 的只读审计和文档矩阵修正已经闭环；这只代表 M1 的事实基线已具备，不代表自动授权
开始改代码。M1 仍须用户单独明确授权。

---

## 4. 旧 Console 原子删除边界

### 4.1 精确 Git 跟踪范围

| 边界 | 跟踪文件数 | M0 判定 |
|---|---:|---|
| `lake_console/backend/**` | 181 | M6 原子删除 |
| `lake_console/frontend/**` | 65 | 与 backend 同轮原子删除 |
| `tests/lake_console/**` | 14 | 只测试旧 backend/frontend，随旧产品删除 |
| 专属入口和示例配置 | 3 | 与旧产品同轮删除 |
| 合计 | 263 | 禁止扩大为整个 `lake_console/**` |

三个专属文件：

```text
lake_console/bin/lake-console
scripts/local-lake-console.sh
lake_console/config.local.example.toml
```

按字典序排序后的 263 路径清单 SHA-256：

```text
d0f3778dab3fabb0992d92322dce3b3209d318e80f98b40c2a16d225f33f02bf
```

若实施时文件数、路径集合或该 hash 变化，旧白名单立即失效，必须重做 M0，不得沿用数量强删。

### 4.2 外部引用核对

- [x] `src/**`、`qtf/**`、根 `frontend/**`、`wealth/**`、正式 orchestrator 中没有导入旧
  `lake_console.backend` 或 `lake_console.frontend`。
- [x] 旧 backend/frontend 也没有反向导入 `src`、`orchestrator`、`qtf` 或 `wealth` 当前实现。
- [x] `tests/lake_console/**` 的业务 import 全部指向旧 backend；没有当前正式模块的测试职责。
- [x] 边界外唯一正向启动器是待删的 `scripts/local-lake-console.sh`。
- [x] `lake_console/orchestrator/tests/test_run_contract_static_gates.py` 中的
  `lake_console.backend` 是禁止 catalog 导入旧 backend 的负向断言，不能随关键字批量删除。
- [x] Wealth 四份股票分钟 API 文档中的旧 backend 引用是“不依赖旧 backend”的边界说明，按 LLD
  修改时态，不删除当前 Wealth 设计。

### 4.3 原子删除条件

旧 frontend、backend、14 个测试、三个入口/示例配置必须在 M6 同轮删除。不得只删后端留下页面，
也不得只删页面留下可执行 API/CLI。M6 之前只允许迁移依赖和修正文档，不允许分批造成半退役状态。

---

## 5. Kopia 审计

### 5.1 正向能力

Kopia repository、snapshot、restore、prewrite backup、recovery 的正向代码和配置均位于：

```text
lake_console/backend/**
lake_console/frontend/**
lake_console/config.local.example.toml
tests/lake_console/**
```

这些内容由 263 文件原子删除边界覆盖，不应抽出复用到 orchestrator。

### 5.2 边界外命中

可执行代码和生效配置中未发现边界外 Kopia 正向调用。以下命中必须保留为负向门禁：

```text
lake_console/orchestrator/tests/test_index_daily_000680_history_supplement_plan.py
lake_console/orchestrator/tests/test_run_contract_static_gates.py
tests/architecture/test_wealth_sector_heat_guardrails.py
```

规则和现行设计中的“禁止 Kopia”也必须保留。后续引用清零 gate 必须区分“正向能力”和“禁止性
断言”，不能要求字符串在全仓绝对为 0。

---

## 6. 旧湖迁移适配器处置清单

### 6.1 依赖迁出后整文件删除

```text
lake_console/orchestrator/src/orchestrator/defs/bootstrap/source_method.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/dataset_spec.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/old_lake_executor.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/specs/__init__.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/specs/adj_factor.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/specs/stk_mins.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/specs/stock_basic.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/specs/stock_daily.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/specs/stock_identity_map.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/specs/suspend_d.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/specs/trade_calendar.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/adj_factor_raw_bootstrap_events.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/adj_factor_silver_bootstrap_events.py
```

代码事实：

- `BootstrapDatasetSpec` 强制包含 `old_lake_path_pattern`，不是当前 DatasetDefinition/history 通用契约。
- `old_lake_executor.py` 直接读旧 path pattern 并写正式 Raw，不应保留为正式派生 executor。
- `specs/**` 的输入全部是物理旧湖或 `backup/research/stk_mins_by_date_clean_next`。
- 两个 adj factor event 模块没有 definitions 或 CLI 入口，只有专属旧测试。

### 6.2 整文件删除的纯旧测试

```text
lake_console/orchestrator/tests/test_adj_factor_bootstrap_spec.py
lake_console/orchestrator/tests/test_adj_factor_raw_bootstrap_events.py
lake_console/orchestrator/tests/test_adj_factor_silver_bootstrap_events.py
lake_console/orchestrator/tests/test_stk_mins_bootstrap_spec.py
lake_console/orchestrator/tests/test_stk_mins_migration.py
```

其中 `test_stk_mins_migration.py` 只能在当前 helper 测试迁出后删除。

### 6.3 只能局部修改的当前共享文件

| 文件 | 允许修改 | 禁止误删 |
|---|---|---|
| `bootstrap/__init__.py` | 移除旧 spec/executor export | package 本身保留 |
| `defs/duckdb_sql.py` | 只删 7 个旧 bootstrap SQL template | 其余当前 DuckDB SQL 全保留 |
| `defs/catalog/lake_assets.py` | 删除 `IngestionSource.OLD_LAKE_BOOTSTRAP` 并逐资产改来源 | catalog 和 `bootstrap_sources` 字段保留 |
| `defs/run_contracts/metadata.py` | 只删 `SourceSystem.OLD_LAKE_BOOTSTRAP` | 其余 metadata 合同和历史字符串保留 |
| `tests/test_adj_factor_contracts.py` | 只删旧 template import/断言 | 当前 adj factor contract tests 保留 |
| `tests/test_stk_mins_contracts.py` | 只删两个旧 template import/断言 | 当前分钟 schema/SQL tests 保留 |

7 个旧 SQL template：

```text
TRADE_CALENDAR_BOOTSTRAP_SELECT_TEMPLATE
STOCK_BASIC_BOOTSTRAP_SELECT_TEMPLATE
STOCK_DAILY_BOOTSTRAP_SELECT_TEMPLATE
STK_MINS_BOOTSTRAP_SELECT_TEMPLATE
STOCK_IDENTITY_MAP_BOOTSTRAP_SELECT_TEMPLATE
ADJ_FACTOR_BOOTSTRAP_SELECT_TEMPLATE
SUSPEND_D_BOOTSTRAP_SELECT_TEMPLATE
```

### 6.4 Catalog 17 个展开项

| 资产组 | 数量 | 清退后来源 |
|---|---:|---|
| `silver_adj_factor` | 1 | `DERIVED_FROM_ASSETS` |
| Raw `stk_mins` 1/5/15/30/60m | 5 | ingestion 保留 Tushare/prod DB；bootstrap 只留 `PROD_DB_READONLY` |
| Silver `stk_mins` 1/5/15/30/60m | 5 | `DERIVED_FROM_ASSETS` |
| native Gold QFQ 1/5/15/30/60m | 5 | 只留 `DERIVED_FROM_ASSETS` |
| `silver_index_daily` | 1 | `DERIVED_FROM_ASSETS` |

五个 Raw catalog 项只有在 `stk_mins_raw_replace_from_prod` 的 M4 重构验收后才能写成
`PROD_DB_READONLY` 当前 bootstrap 来源，不能先改文案掩盖旧实现仍不合规的事实。

---

## 7. `stk_mins_migration.py` 混合依赖清单

### 7.1 必须先迁出的三个当前能力

| 当前符号 | 当前消费者 | M1 目标 |
|---|---|---|
| `discover_raw_stk_mins_partitions` | `stk_mins_silver_history.py` | 迁入 Silver history 当前模块 |
| `_validate_backup_partition_alignment` | `stk_mins_silver_history.py` | 改成来源无关的五频 partition alignment helper |
| `_check_success_count` | Silver、QFQ、QFQ derived、MACD/KDJ 四个 event 模块 | 迁入当前 history check-event helper |

四个 `_check_success_count` 当前消费者：

```text
stk_mins_silver_bootstrap_events.py
stk_mins_qfq_bootstrap_events.py
stk_mins_qfq_derived_bootstrap_events.py
stk_mins_qfq_macd_kdj_baseline_events.py
```

这些文件名虽含 `bootstrap`，实际负责当前正式湖历史事件和最终审计，不能按名称删除。

### 7.2 迁出后删除

`stk_mins_migration.py` 的其余 plan、backup discovery、旧 Raw 写入、identity map 写入、动态分区注册、
旧 Raw/identity event 补录和最终旧源对账均只服务一次性迁移。所有当前 import 清零后，原文件整删，
不留 wrapper、alias 或 tombstone module。

---

## 8. `stk_mins_migration_cli.py` 命令清单

### 8.1 当前 parser 事实

静态 AST 复核得到 28 个子命令。

删除的 7 个旧迁移命令：

```text
dry-run
migrate-raw
migrate-identity-map
register-partitions
report-raw-events
report-identity-map-events
audit-final
```

保留并迁移的 21 个当前命令：

| 目标 CLI | 命令数 | 命令 |
|---|---:|---|
| Silver history CLI | 5 | `plan-silver`、`generate-silver`、`register-silver-partitions`、`report-silver-events`、`audit-silver-final` |
| QFQ history CLI | 5 | `plan-gold-qfq-history`、`generate-gold-qfq-history`、`plan-gold-qfq-events`、`report-gold-qfq-events`、`audit-gold-qfq-final` |
| QFQ derived CLI | 5 | `plan-gold-qfq-derived-history`、`generate-gold-qfq-derived-history`、`plan-gold-qfq-derived-events`、`report-gold-qfq-derived-events`、`audit-gold-qfq-derived-final` |
| MACD/KDJ history CLI | 6 | plan、generate、rebuild、file audit、baseline events、final audit |

### 8.2 当前 CLI 测试消费者

```text
lake_console/orchestrator/tests/test_stk_mins_qfq_m8c_history.py
lake_console/orchestrator/tests/test_stk_mins_qfq_m8d_events.py
lake_console/orchestrator/tests/test_stk_mins_qfq_m11f_derived_history.py
lake_console/orchestrator/tests/test_stk_mins_qfq_m12_macd_kdj.py
lake_console/orchestrator/tests/test_run_contract_static_gates.py
```

这些测试必须改指拆分后的新 CLI，不能随旧 dispatcher 删除。

`test_stk_mins_qfq_m8c_history.py` 还保护一个已经删除的危险命令
`rebuild-gold-qfq-canonical-history`。后续应改为直接验证当前 canonical CLI 继续拒绝它，不能丢掉这条
负向门禁。

### 8.3 行为等价门禁

- [ ] M2A 先冻结 21 个命令的 parser、默认值、规范化参数、dispatch、stdout key、失败时点和副作用分类。
- [ ] 旧/新入口用 fake writer、fake Dagster instance、临时 Lake 双跑；不得碰真实运行态。
- [ ] 7 个旧迁移命令和已删除 canonical one-shot 在新 CLI 中均不存在。
- [ ] M2A 等价通过后才能删除旧 dispatcher。
- [ ] M2B 才允许执行已拍板的 Silver selector 收紧和 MACD/KDJ 单分区门禁；其余差异一律视为回归。

---

## 9. `stk_mins_raw_replace_from_prod` 保留与重构边界

### 9.1 当前真实链路

```text
专属 non-active CLI plan
  -> 只读读取 ops.task_run、正式股票代码集、prod raw_tushare.stk_mins 五频事实
  -> 读取五个正式 Raw target fingerprint
  -> 生成 reviewed plan

专属 non-active CLI apply
  -> 重做 plan 并校验 fingerprint
  -> 生成五个 candidate 并逐频校验
  -> 五个正式 target 依次替换
```

正向调用方只有专属 CLI；模块没有 asset/job/sensor/check decorator，也没有被 active definitions 装配。
它填补“任意单日全市场五频 prod DB 整体恢复”的真实空档，BSE recovery 和日常 Raw job都不能等价替代。

### 9.2 当前不合规点

- `_staging_root(...)` 位于正式 Raw 树内。
- `_quarantine_root(...)` 位于正式 Lake 根。
- 成功后 manifest 和五份旧 target backup 长期保留在正式根。
- 五次 `os.replace()` 只有单文件原子性；进程强杀或掉电可能绕过 Python rollback，不能宣称五频原子。

### 9.3 M4 目标

- candidate、audit、plan、checkpoint、final report 全迁到 `DEFAULT_LAKE_STAGING_ROOT`。
- 每频冻结 old/candidate fingerprint，状态为 `pending/promoted/verified`。
- 中断后只允许同一 run id 按 target fingerprint 幂等续跑。
- 不新增 lock service、pid 文件或自造排它锁。
- 人工维护窗口保证没有同日期其他 writer；五频全部 verified 前不得宣称恢复成功。
- 单日、五频、五文件、5 分钟预算只约束该离线恢复工具，不涉及 Ops Snapshot 或页面查询。

该模块和测试在 M4 是“修改”，不是删除。

---

## 10. 必须保留的当前能力

### 10.1 Ops Dataset Status Snapshot

当前写链和读链同时存在：

```text
src/ops/models/ops/dataset_status_snapshot.py
src/ops/services/operations_dataset_status_snapshot_service.py
src/ops/services/task_run_completion_service.py
src/ops/services/operations_probe_runtime_service.py
src/cli.py + src/cli_parts/ops_handlers.py
src/ops/queries/freshness_query_service.py
src/ops/queries/date_completeness_query_service.py
src/ops/queries/dataset_card_query_service.py
```

当前测试中至少 9 个文件直接使用 `DatasetStatusSnapshot` 或 `DatasetStatusSnapshotService`。它是
freshness/数据卡片/日期完整性的数据范围缓存，不是本专项所谓的 Kopia snapshot，禁止删除表、ORM、
service、CLI 或查询消费者。

### 10.2 Foundation Local Lake 与 Wealth 分钟链

| Reader | 当前消费者 |
|---|---|
| `StockMinsLakeReader` | 股票详情分钟 Query Service |
| `MajorIndexMinsLakeReader` | 指数详情分钟 Query Service |
| `StockNineTurnLakeReader` | 股票分钟九转 Query Service/API |
| `IndexNineTurnLakeReader` | 指数分钟九转 Query Service/API |

保护测试：四个 Reader 测试、股票/指数分钟 API 测试、股票/指数分钟九转 API 测试，以及 Wealth
`StockDetailPage`、`IndexDetailPage`、`useIndexMinuteSeries` 等页面测试。

这些 Reader 读取正式 `/Volumes/datasource/data_lake` 的 Gold 文件，不依赖旧 Console backend。

### 10.3 ClickHouse、BSE recovery 和 reports

- 正式 orchestrator 有 26 个 ClickHouse 源文件和 14 个相关测试文件。
- `lake_console/bin/lake-clickhouse-start`、`lake_console/bin/lake-prod-clickhouse-tunnel` 必须保留。
- BSE history/recursive/QFQ recovery 是当前正式 staging/candidate/promote 链，必须保留。
- `lake_console/reports/**` 当前有 3 个跟踪 CSV，均不在本专项删除范围。
- `index_daily_continuous_since_list_date_after_20000101.csv` 被两份当前 Phase 3 Dagster 文档明确引用。
- 另外两份 CSV 未发现当前运行消费者或 tracked 反向引用；这只说明“本次不证明其仍被运行使用”，
  不授权在本专项顺带删除。若要清理，应另立 reports 专项。

### 10.4 必须保留的旧湖路径负向门禁

以下当前代码出现旧物理湖路径，是为了拒绝错误根目录，不能按路径关键字删除：

```text
lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_mins_bse_history_recovery.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/stock_daily_qfq_nineturn_no_price_history.py
```

前者在 `_validate_roots(...)` 中拒绝把旧湖当 recovery lake root；后者在 `_validate_roots(...)` 中拒绝
旧湖及其子目录。后续运行代码清零扫描必须把“正向读取旧湖”和“显式拒绝旧湖”分开。

---

## 11. 本机 ignored 环境与物理旧湖

仅核对存在性和 ignore 规则，未读取内容：

| 路径 | 当前状态 | 本专项处置 |
|---|---|---|
| `lake_console/config.local.toml` | 存在、ignored | 不删、不读，后续精确处理 |
| `lake_console/.venv/` | 存在、ignored | 不删，后续精确处理 |
| `lake_console/frontend/node_modules/` | 存在、ignored | 不删，后续精确处理 |
| `lake_console/frontend/dist/` | 存在、ignored | 不删，后续精确处理 |
| `/Volumes/datasource/goldenshare-tushare-lake` | M0 未访问 | 代码清退后另立物理数据审计 |

删除 tracked `lake_console/frontend/**` 不等于授权删除 ignored `node_modules/dist`；Git 代码和本机环境
必须分轮处理。

---

## 12. 文档矩阵复核

### 12.1 修正后 145 行矩阵完整性

| 处理码 | 数量 | 路径存在 | 重复 |
|---|---:|---:|---:|
| `DELETE_AFTER_MIGRATION` | 3 | 0 缺失 | 0 |
| `MODIFY_CURRENT` | 31 | 0 缺失 | 0 |
| `MODIFY_MIXED` | 10 | 0 缺失 | 0 |
| `DELETE_LEGACY_DOC` | 86 | 0 缺失 | 0 |
| `KEEP_CURRENT_VERIFY` | 15 | 0 缺失 | 0 |
| 合计 | 145 | 0 缺失 | 0 |

86 份待删文档的 basename/path 反向引用扫描得到 9 个当前引用源；9 个全部已进入矩阵，未归类为 0：

```text
docs/README.md
docs/architecture/goldenshare-repository-onboarding-overview-v1.html
docs/datasets/index-wave4-trend-reversal-backtest-plan-v1.md
docs/governance/engineering-risk-register.md
lake_console/AGENTS.md
lake_console/docs/design/dagster-etf-market-data-prod-db-onboarding-plan-v1.md
lake_console/docs/design/dagster-phase-2-design.html
lake_console/docs/design/dagster-stk-mins-asset-design.html
lake_console/docs/design/dagster-stk-mins-qfq-macd-kdj-indicators-plan.md
```

### 12.2 M0 发现并已回填的两个漏项

扩大旧路径扫描到正式 Lake `_quarantine` 历史证据后，发现两份未登记文档：

| 文件 | 命中事实 | 正确处理 |
|---|---|---|
| `lake_console/docs/design/dagster-stk-mins-qfq-macd-kdj-reconciliation-recovery-r5-low-level-design.md` | 记录 2026-07-14 已发生的 MACD/KDJ quarantine 路径和执行结果 | `KEEP_CURRENT_VERIFY`；保留历史证据，不改写、不删除 |
| `lake_console/docs/design/dagster-stock-qfq-nineturn-dataset-low-level-design.md` | 记录 2026-08-08 已发生的九转 quarantine 路径和 manifest | `KEEP_CURRENT_VERIFY`；保留历史证据，不改写、不删除 |

它们不是旧 Console 文档，也不提供 Kopia/旧湖执行入口。漏项原因是原扫描只覆盖了
`stk_mins_raw_replace_from_prod` 的旧 `_staging/_quarantine` 口径，没有把其他当前 Dagster 文档中的
正式 Lake 历史 quarantine 证据纳入候选。M0 使用更宽的路径扫描后才暴露该问题。

修正后实测矩阵：

```text
TOTAL=145
DELETE_AFTER_MIGRATION=3
MODIFY_CURRENT=31
MODIFY_MIXED=10
DELETE_LEGACY_DOC=86
KEEP_CURRENT_VERIFY=15
MISSING=0
DUPLICATE=0
UNMAPPED=0
```

本清单、上位方案和 LLD 自身是扫描控制文档，必然包含全部关键字；机器扫描必须显式排除这三个控制
文件，否则会产生递归假阳性。旧 `lake_console/backend/**`、`lake_console/frontend/**` 和
`tests/lake_console/**` 已由第 4 节 263 项直接删除白名单独立覆盖，宽文档扫描先校验该白名单数量与
hash，再排除这些路径；除此之外不得静默排除命中。

---

## 13. 下一阶段允许范围与停止条件

### 13.1 M1 前置条件

- [x] 只更新 LLD 文档矩阵，加入第 12.2 节两个 `KEEP_CURRENT_VERIFY`。
- [x] 重跑矩阵计数、路径存在性、待删文档反向引用和宽关键字扫描。
- [x] 确认当前用户无关脏文件均不在 M1 白名单。
- [ ] 用户单独明确授权 M1。

### 13.2 M1 最大代码白名单

M1 只能迁移当前 helper，不删除旧文件、不拆 CLI、不改 catalog、不改恢复工具：

```text
新增：
lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_mins_history_check_events.py

修改：
lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_mins_silver_history.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_mins_silver_bootstrap_events.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_mins_qfq_bootstrap_events.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_mins_qfq_derived_bootstrap_events.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_mins_qfq_macd_kdj_baseline_events.py

对应当前测试按需修改：
lake_console/orchestrator/tests/test_stk_mins_silver_m6_history.py
lake_console/orchestrator/tests/test_stk_mins_qfq_m8d_events.py
lake_console/orchestrator/tests/test_stk_mins_qfq_m11f_derived_history.py
lake_console/orchestrator/tests/test_stk_mins_qfq_m12_macd_kdj.py
```

`stk_mins_migration.py` 和 `test_stk_mins_migration.py` 在 M1 仍保留，用于逐步证明迁移前后语义一致。

### 13.3 任一命中立即停止

- [ ] 263 旧产品路径集或 hash 变化。
- [ ] 当前代码新增旧 backend/frontend 正向 import。
- [ ] Kopia 在旧边界外出现正向运行调用。
- [ ] 旧湖 spec/executor 出现新的当前消费者。
- [ ] 21 个当前 CLI 命令出现未记录的 parser/dispatch/output 差异。
- [ ] `stk_mins_raw_replace_from_prod` 被 active definitions 装配，或其调用方不再只有专属 CLI。
- [ ] Ops Snapshot、Foundation Reader、ClickHouse、BSE recovery 或 reports 被纳入删除 diff。
- [ ] 任何物理 Lake、ignored 环境、数据库或 Dagster 运行态发生变化。
- [ ] 文档矩阵出现未归类、重复或不存在路径。
- [ ] staged diff 出现本专项白名单外文件。

---

## 14. M0 验收结论

- [x] 代码影响面已经按当前 HEAD 重新核对，不依赖旧文档印象。
- [x] 旧 Console/Kopia 直接边界已冻结为 263 个精确 Git 路径。
- [x] 旧湖适配器的纯旧、混合、当前保护对象已分开。
- [x] `stk_mins` 7 个旧命令和 21 个当前命令已逐项分类。
- [x] Ops Snapshot、Wealth Local Lake、ClickHouse、BSE recovery、reports 和负向旧湖门禁已列入防误删清单。
- [x] 86 份待删文档的当前反向引用已全部归类。
- [x] M0 主动发现 2 个文档矩阵漏项，并给出唯一明确处理码。
- [x] 2 个漏项已回填 LLD；145 行矩阵路径存在、处理码唯一，宽扫描未归类为 0。
- [x] 本轮没有代码、运行态、物理数据或 ignored 环境变更。

2026-08-28 当时判定：**M0 只读审计与文档矩阵修正已闭环；代码清退范围没有新增拍板项；145 份文档均有唯一
处理码，未归类、重复和不存在路径均为 0。M1 仍未获得用户单独授权，本次提交不开始任何代码修改或删除。**

---

## 15. 2026-09-05 补充复核（替代旧口径，不改写历史审计）

### 15.1 范围与依据

依据用户最新决定，无用物理数据纳入专项：确认无用才删、在用不删、用途未知先保留；ignored 依赖环境
和本机配置仍另轮处理。本轮仅做只读审计及专项文档更新，不执行 M1–M8，不运行 Kopia、Dagster、
生产查询或恢复工具。代码基线为 `dev-interface@10521877`，开始时工作区干净。

采用文档治理的权威分层：§1–14 是 2026-08-28 点时证据；当前执行口径以已更新的专项方案及 LLD 为准，
不把文档修订当代码已实现。CodeGraph explore 覆盖 Raw recovery/CLI/rollback 及其他 quarantine 使用方，
直接代码核验补足 apply 的异常/目录重入行为、报告输出消费者及物理路径构造。

### 15.2 四项复审结论与处置

| 复审项 | 核验结论 | 已落位置 |
|---|---|---|
| 物理边界 | 旧版一律延期已被用户更新。M4 删除旧路径/备份的生成代码，M8 才按用途清退精确物理文件；不能要求整个 frontend/quarantine 目录消失 | 方案 §0.3、M8、§7/9；LLD §1、M4/M8、§16 |
| Raw 续跑矛盾 | “丢候选必须新 run、部分提升后禁止新 run”是未实施 LLD 的设计缺口。现代码则确有同 run 目录拒绝和强制中断不能可靠回滚的问题；M4 统一覆盖 | LLD §6.4.2：补 pending+target=candidate、提升前废弃、提升后丢候选的人工停止点及负例测试 |
| 文档漏项 | 当前 HEAD 比历史矩阵多 9 份命中，含两个仍引用旧模板的现行趋势通道文档；不能靠“上次已审完”跳过它们 | LLD §9.4，矩阵 154 份；新增项为 2 MODIFY_CURRENT、2 MODIFY_MIXED、5 KEEP_CURRENT_VERIFY，无新增旧文档删除目标 |
| 低频性能 | 取消超过 5 分钟自动拒绝和未定义 candidate 字节估算 ×2 硬门禁；保留单日五频、受控读取/资源、完整校验、阶段记录和人工监督。阻塞查询不承诺即时取消 | 方案 §3.6.2；LLD §6.4.4 的实施点及正反例测试 |

### 15.3 物理定点证据

- [x] 精确读取 2026-07-27 Raw recovery 的 `f573265f-1162-4535-9089-c486f7b7dac1` manifest，状态
  `promoted`，频率 `1/5/15/30/60` 全部已提升。
- [x] 五份当前正式 Raw 的 SHA-256 全等于 manifest 的 staged 指纹；五份 backup 的 SHA-256 全等于
  old target 指纹，backup 合计 31,282,051 字节。正式文件仍是当前 Raw/Silver 链输入，保留。
- [x] manifest 仍被当前事故执行文档引用；五份旧备份和 manifest 只列为依赖/证据处理后可删的候选，
  没有提前标成 `DELETE_READY`。
- [x] 旧 Raw `_staging` 目前为空，但现代码仍可创建其子项，须 M4 解除依赖后再复核空目录。
- [x] 当前 Silver replace 代码也使用 `_quarantine`；其数据不因 Raw run 已成功而一律可删。
- [x] 物理旧湖仅看顶层目录，未做内容对账；reports 有当前正式审计输出消费者，未逐报告核用途。
- [ ] 整湖、历史 backup 输入、其他 quarantine/staging run、reports 的逐对象用途审计。
- [ ] 实际删除前的在途任务/人工恢复用途、指纹、保留证据和恢复能力复核。

精确路径、五频 SHA-256 和分类见 LLD §16。未知对象仍是待审计，不意味着已确认无用。

### 15.4 验证结果与剩余风险

| 检查 | 结果 |
|---|---|
| 旧产品精确路径白名单 | 263 个，排序路径 SHA-256 仍为 `d0f3778dab3fabb0992d92322dce3b3209d318e80f98b40c2a16d225f33f02bf` |
| 文档矩阵 | 154 份：33 MODIFY_CURRENT、12 MODIFY_MIXED、20 KEEP_CURRENT_VERIFY、86 DELETE_LEGACY_DOC、3 DELETE_AFTER_MIGRATION |
| 矩阵路径存在/唯一性 | 不存在 0、重复 0 |
| 旧符号/路径 tracked 文档宽扫描 | 未归类命中 0；仅限登记扫描规则与当前 HEAD，不保证未来文件无新增命中 |
| 89 份待删文档的反向路径/文件名引用 | 矩阵外未归类文档 0；这些引用在 M5 尚须真实切换，不是已经清零 |
| 仓库文档完整性检查 | 通过；该检查不证明恢复代码正确或物理数据可删 |
| `git diff --check` | 通过 |
| 运行测试/真实数据任务 | 未执行；本轮没有代码实现，不声称 M4 回归或生产恢复已通过 |

上述复审当时仅修改专项方案、LLD、本清单及 `docs/README.md`，不改变实际模块边界/依赖矩阵，未提交、未删除。
后续仍需按批准阶段实施代码与测试，M8 对待审对象继续核实，不能用本次文档检查代替开工时引用审计或
最终数据删除资格判定。

### 15.5 提交前补记：审计时机与删除确认

用户随后确认：不能自行删除，必须先由用户确认。方案和 LLD 已同步明确所有代码、旧文档和物理数据
删除均受具体清单确认约束；新增目标或范围变化须重新确认，方案/审计/文档提交授权不代替删除授权。
下一项工作是代码清退实施前的物理数据用途只读审计与逐项分类清单，交用户 review；代码实施后、实际
删除前再次核用途和指纹，不等到 M8 才开始首次审计。本次用户仅要求提交专项文档并列出下一步，不开始
代码修改、物理数据审计任务或任何删除。
