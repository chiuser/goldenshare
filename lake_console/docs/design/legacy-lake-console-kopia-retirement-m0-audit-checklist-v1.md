# 旧 Lake Console、Kopia 与旧湖迁移适配器清退 M0 只读审计清单 v1

状态：2026-08-28 M0 历史基线；2026-09-05 旧湖批量分类见 §21，M1 已提交见 §22，M2A 已提交 `0cc84004` 见 §23，M2B 已提交 `e8e2abf9` 见 §24；M3 已提交 `1b0deb63` 见 §25，M4 已实现并通过隔离回归，随本次提交归档见 §26，其余具体删除待确认

审计日期：2026-08-28

上位依据：

1. `docs/architecture/legacy-lake-console-and-kopia-retirement-plan-v1.md`
2. `lake_console/docs/design/legacy-lake-console-kopia-old-lake-bootstrap-retirement-low-level-design-v1.md`
3. 根 `AGENTS.md`、`lake_console/AGENTS.md`、`lake_console/orchestrator/AGENTS.md`

> 本清单只记录当前代码和文档事实，不替代上位方案或 LLD，不授权 M1–M7，也不授权删除代码、
> 文档、物理数据或本机环境。M0 发现的两个漏项已经回填 LLD，并重新得到未归类命中为 0；进入
> 后续实施轮次仍须用户单独授权。

> §1–14 保留 2026-08-28 的审计记录，不是当前永久事实。用户在 2026-09-05 将无用物理数据纳入专项，
> 原“物理旧湖另轮处理”和 5 分钟硬门禁已被上位方案及 LLD 新口径替代；当前矩阵为 156 份，不能再用
> 历史 145/154 份或当时未归类为 0 证明当前覆盖完整。物理数据的最新边界与结果见 §21 和 LLD §16.14。
> §15–20 的内容对账结果保留为历史事实，其未勾选的数据差异/人工价值待办已取消，不再作为当前门禁。
> §17 已批准删除的事实、§19 现行停牌 TODO 不变。

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

以下完成状态按 2026-09-05 M2A 回填，不属于原 M0 只读审计的实施成果。

- [x] M2A 先冻结 21 个命令的 parser、默认值、规范化参数、dispatch、打印类型/内容、失败时点和副作用分类。
- [x] 旧/新入口用 fake 资源/业务函数双跑 246 组输入，不碰真实运行态。
- [x] 7 个旧迁移命令在四个新 CLI 中均拒绝；当前 canonical CLI 继续拒绝已删除 one-shot。
- [x] M2A 等价与消费者切换通过后，唯一删除旧 dispatcher。
- [x] M2B 已单独执行已拍板的 Silver selector 收紧和 MACD/KDJ 单分区门禁，见 §24；其余差异一律视为回归。

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

## 16. 2026-09-05 物理用途首批只读审计（历史取样，后续见 §17–18）

用户要求继续推进后，按 §15.5 先做物理数据用途审计。本节是新增的执行记录，不把前次文档提交追认为
数据审计授权。基线 `dev-interface@75af8445`；只改专项文档及其索引，保留工作区其他任务的改动。
详细证据与分类位于清退 LLD §16.4–16.8；没有形成可执行删除白名单，没有开始 M1–M8 代码/删除实施。

### 16.1 已完成

- [x] CodeGraph status/explore/callers 与直接代码核对：旧迁移源、Raw/Silver 恢复、当前 WMT 证据消费者。
- [x] 旧湖完整元数据清单：297730 个普通文件、509788479887 字节；分清 54 个 Raw 数据集、manifest、
  research、derived、旧 `_recovery` 与 `_tmp`；不把目录盘点当内容已迁完。
- [x] clean_next backup 完整清单：21047 个文件、67676449533 字节；五频各 4209 个 Parquet，
  2009-01-05 至 2026-05-07，对应正式 Raw 路径 21045/21045 存在。只证明路径覆盖。
- [x] quarantine 完整元数据清单：75265 个文件、14845426378 字节；识别相邻指数、九转、MACD/KDJ
  正式治理遗留，未归为旧 Console/Kopia 删除对象。
- [x] 独立重验 2026-07-27 Raw 与 Silver 两个恢复 run：各五份旧文件/正式新文件的 SHA-256 均匹配
  manifest；旧文件分别 31282051 / 21811817 字节。正式文件保留，遗留六文件各列依赖处理后候选。
- [x] 三个报告逐份完整读取和 SHA-256：指数 948 行，namechange 14 行零未决摘要，stock_daily 35 行。
  不删除 reports 目录，不删除当前 overrides/seed，也不把旧缺口都当已解决。
- [x] 本机 Dagster GraphQL 点时在途 run 数为 0；只读查询正式本机 DG DB 中 `cn_a_index_ts_codes`
  为 820 个，全部在旧 CSV 内，旧 CSV 另多 128 个。当前代码读持久化集合，不读报告。
- [x] 打开文件取样：湖目录无命中，三个 CSV 由 CodeGraph 索引进程持有，不是业务读者；不能据此
  断言所有潜在人工/异机用途都不存在。
- [x] 本地 Web 配置为正式 Lake root；旧 Console 配置为旧 root。未改 ignored 配置/环境。
- [x] 两份 Phase 3 指数 HTML 全文审计：已标为被替代的正式指数设计，历史 CSV 初始化不是当前入口；
  补入 LLD 文档矩阵 `KEEP_CURRENT_VERIFY`。现在 156 份，旧文档删除目标仍为 86+3 份。

### 16.2 未完成，不得据此删除

- [x] backup clean_next 后经用户确认无需再审内容，取消其内容替代证明任务并精确删除，见 §17；旧湖内另一处同名数据仍待审。
- [ ] 旧湖 54 个 Raw 数据集逐项当前用途、正式承接、唯一数据价值及内容差异；研究/派生/manifest 同样待核。
- [ ] staging 全量盘点。本次遍历 600436 个目录项后按预算停止，记录到 40787 个普通文件、4925835331
  字节，仍有 4287 个待遍历目录；这两个数量是下界。
- [ ] 当前 BSE/WMT 恢复记录跨计划承接、发布和续跑用途；三份 WMT changed manifest 仍为 complete=false。
  单个完成 manifest 或当前无 run 都不足以删除这些记录。
- [x] stock_daily 报告 35 项用途核验已补齐，见 §18；报告未删除，不能将分类闭合当全历史质量验收。
- [ ] 两个分钟恢复 run 的事故记录摘要迁移、人工恢复用途确认及删除恢复能力。
- [ ] 用户确认逐文件删除清单、执行前指纹/路径/消费者/运行状态复核。当前 `DELETE_READY` 为 0。

### 16.3 新发现为什么之前没被纳入

两个指数历史设计没有旧 Console/Kopia 关键词，也不依赖原 86 份旧文档；它们通过一份实际 CSV
形成历史证据依赖。之前的关键词和待删文档入链扫描不能覆盖这类关系。本次增加“物理文件绝对路径、
相对路径、文件名反查”入口，并区分历史引用与当前消费者。它降低漏审风险，但不构成未来零遗漏保证；
不认识或证据不足的对象继续 `PENDING_AUDIT`，不能默认删除。

### 16.4 下一步与边界

首批审计原先安排 backup clean_next 的内容对账，后已被 §17 用户明确决定取消；当前继续逐数据集补旧湖用途清单，
并收敛报告/恢复记录前置项。下一轮仍先给可核验的分类和证据，不自动进入代码删除。需要删除时，
必须由用户确认具体清单；未经确认不删代码、文档或物理文件，不改 Dagster/业务库状态。

本次验证：文档完整性检查、`git diff --check` 通过；156 份矩阵处理码计数与正文一致，按表内目录前缀
展开后不存在/重复路径均为 0。263 个旧产品路径白名单及排序 SHA-256 未变。未运行代码回归，未提交
或推送。本次仅修改专项方案、LLD、M0 清单和 README 中本专项索引；其他任务新增的代码/文档改动均未触碰。
文档检查不证明任何未实施代码或未完成数据对账已经通过。

## 17. 2026-09-05 已批准的单项 backup 删除

- [x] 用户确认精确目标 `/Volumes/datasource/backup/research/stk_mins_by_date_clean_next`，声明这是
  基础版本备份、无需内容审计，并要求“确认，删除后，你继续推进吧”。不再重复要求内容对账或 M0–M7 完成。
- [x] 执行前同步专项方案 §0.4/LLD §16.1 的单项例外，不改变其他对象删除门禁。
- [x] 08:21:04 +08:00 机械检查通过：realpath 一致、无符号链接/跨挂载/特殊文件、无文件占用和旧迁移
  进程命中；21047 文件、67676449533 字节，数量与前次盘点一致。元数据清单指纹见 LLD §16.9。
- [x] 精确删除该目录，命令退出码 0；08:21:45 核验目标不存在，backup 父目录、旧湖同名目录、正式
  Raw 分钟目录均存在且 device/inode 未变。核验时 `dev-interface@ca625748`。
- [x] 记录不可通过 Git 恢复，未创建内容备份、未用 Kopia，不承诺额外副本或实际磁盘释放量。
- [x] 旧迁移默认源已不可用，代码仍待 M3 清退；现行 Tushare/prod DB 分钟链未改，正式数据未删。

本项完成不代表 M8 完成；其他旧湖/恢复数据、报告、代码、文档和 ignored 环境均未获本次删除授权。
执行细节及临时清单位置见 LLD §16.9。

## 18. 2026-09-05 删除后继续推进的报告用途审计

- [x] 只读核 2 日期、4 代码、11 输入文件（1463473 字节），0.44 秒；文件前后哈希一致，无生产查询或写入。
- [x] 三个未标停牌的 2026-03-31 缺行项在正式 Raw/Silver 中各有一行，上市日均为当天。
- [x] 报告 32 项 S 与现行 31 项停牌 seed 双向对账：31 项一一对应，只有报告多出
  `920188.BJ / 2026-03-30–31`；该代码两天正式 Raw/Silver 有行情，Raw/Silver 停牌表无记录。
  不把旧报告的 S 标注加进当前规则。
- [x] 阅读真实规则加载和 SQL 消费链，确认当前读取的是 `defs/corrections/suspend_full_day_ranges.csv`，
  不读取报告；该 seed、Python 规则及 SQL 全部保留，不是旧 Console 删除对象。
- [x] stock_daily 报告转 `DELETE_AFTER_DEPENDENCY`，必要摘要落入 LLD §16.10；三份报告均未删除。
- [ ] 旧湖 54 个 Raw 数据集和 research/derived/manifest 逐项用途审计继续；两个分钟恢复 run 的
  历史摘要/人工恢复前置项继续。其他删除清单须单独由用户确认，暂不进入 M1–M7。

本轮仅改三份专项文档并删除已批准的一个 backup。未改业务代码、依赖矩阵、正式湖、生产库或 ignored
配置，没有提交或推送；工作区中其他任务的改动未触碰。验收不覆盖未实施 CLI/代码重构或全历史质量。

本轮文档完整性检查与 `git diff --check` 通过。旧产品 tracked 白名单仍为 263 个文件，排序路径
SHA-256 仍为 `d0f3778dab3fabb0992d92322dce3b3209d318e80f98b40c2a16d225f33f02bf`；
本轮未删除代码或文档。业务代码未改，未运行代码重构回归。

## 19. 后续 TODO：停牌修正规则隐性文件依赖

- [x] 按用户要求将 `TODO-SUSPEND-001` 登记到清退 LLD §16.11，并同步专项方案 §0.3。
- [ ] 后续治理：停牌修正规则不再由运行代码隐式读取 CSV，明确规则事实源、管理/生效方式和消费者依赖；
  先核有效性，再做结果对账与回归，验收后清除旧读取链，不保留文件读取兜底。
- [x] 明确边界：“当前保留”仅为防误删，不代表长期认可；本轮只记 TODO，不改 CSV/业务代码/数据，
  不把此项自行并入 M0–M8 实施或新增前置门禁。下一步按后续治理安排评审方案，不自动启动重构。

本次登记仅修改三份专项文档，不改变子系统边界、依赖矩阵或现行运行行为；未提交、未推送。

## 20. 2026-09-05 继续旧湖逐数据集与恢复遗留只读核验

用户要求继续审计；本轮不含删除、代码清退、迁移或修复授权。依据及详细逐项矩阵见 LLD §16.12–16.13，
专项方案 §4.6 已同步。使用数据湖/Dagster 技能约束为有预算的只读文件和运行查询，文档治理要求将新差异
回填原方案/LLD，不另建一套冲突的删除口径。

### 20.1 已核实

- [x] CodeGraph status/explore/callers + 当前代码：六个旧 spec、旧 catalog/scanner、两个恢复 apply/CLI/
  回滚函数，以及正式五类 Raw 和 identity 的生产者。动态路径依赖补读实现，不以搜索零命中判无用。
- [x] 六对象双方逐文件元数据；5 个 Raw 是 54 项中的首批，identity 属于 manifest，不能记为 6/54。
- [x] 18 组主内容对账与 6 个早期样本，42 文件/3849480 字节，0.612 秒、512 MB/2 线程、精确路径
  白名单；输入前后 SHA/大小/mtime 一致。另核两条旧证券记录，不请求 Prod/Tushare、不写湖。
- [x] 旧日线比所比正式湖多 5636 个早期分区，旧停牌多 3377 个；抽样非空，保留待用途确认。
- [x] adj_factor 旧 4215 分区路径全覆盖，5 个样本等价；其余内容未全量核，不写成已迁完。
- [x] stock_basic 全表旧 5842/新 5895 行，旧独有 `TS0018.SH`；identity 旧 6089/新 6146 行，旧独有
  `706055.SH`、`TS0018.SH`，另有有效期变化。区分观测字段变化和业务差异，均 `PENDING_AUDIT`。
- [x] trade_cal 精确 Raw Parquet 双方 13162 行、四字段双向差集 0，转 `DELETE_AFTER_DEPENDENCY`；
  不包含 `.DS_Store`、目录或 `manifest/trading_calendar`，当前旧 catalog/spec 仍须先解除。
- [x] 两个 2026-07-27 恢复 run 的 12 个遗留文件共 53115430 字节；旧 10 文件均匹配 before，正式
  10 文件均匹配 staged，旧与正式文件并不相同；两个精确 run staging 目录均已不存在。
- [x] 当前 DG 中七条历史下游任务记录均 SUCCESS；08:52 点时在途任务 0、相关进程/打开文件未命中。
  不冒充重新跑过全部 checks，不把点时无占用或历史成功外推为无人使用旧文件。
- [x] 修正方案/LLD 原“old/new 指纹一致”的易误读表述：各自匹配 manifest，不是旧文件等于正式文件。

### 20.2 未闭合与下一步

- [ ] 本批早期日线/停牌、退市证券与旧身份映射的实际历史用途、其他保留来源及差异成因；只读核清，
  不自动迁回正式湖。若涉及保留/舍弃未承接历史的取舍，单列证据交用户确认。
- [ ] 其余 49 个旧 Raw 数据集逐项初核；本批重叠日期未做全量内容核验，不能把首轮分类当删除验收。
- [ ] 旧 manifest 的日历/基础数据，以及 research/derived 和旧 `_recovery` 20 个目录逐 run/文件用途。
- [ ] 两个分钟恢复 run 的原事故记录证据承接、人工恢复用途和不可通过 Git 恢复的说明；保留正式文件、
  Silver 工具及 BSE/WMT 当前恢复证据链。此次未新增删除范围，也不进入 M1–M7。
- [ ] 用户确认精确删除清单，并在执行前重新核验依赖、指纹及运行状态；`DELETE_READY` 仍为 0。

基线由 `ca625748` 推进到其他任务提交的 `a5f995fa`，中间只有两个治理测试变更；本轮生产代码未变，
已同步 CodeGraph。仅改专项方案、LLD、本清单三个文档，未改变依赖矩阵或现行行为，未提交、未推送；
不触碰其他任务的文档/代码。收尾验证：文档完整性检查与 `git diff --check` 通过；156 份矩阵为
33 MODIFY_CURRENT、12 MODIFY_MIXED、22 KEEP_CURRENT_VERIFY、86 DELETE_LEGACY_DOC、3 DELETE_AFTER_MIGRATION，
路径不存在/重复均 0。旧产品 tracked 白名单仍为 263 份，排序路径 SHA 仍为
`d0f3778dab3fabb0992d92322dce3b3209d318e80f98b40c2a16d225f33f02bf`。本轮未扩大代码/文档候选集合，
未重跑全仓宽词扫描或代码回归，不声称未实施重构已通过；上述检查不代替数据删除资格。

## 21. 2026-09-05 按代码直接引用批量分类（当前口径）

用户确认“代码没有直接引用的数据不再需要”，并同意简化执行。目标是区分当前主链、待清退旧入口和
无代码用途对象，不再证明数据完整、旧新等价或没有历史价值。依据已同步专项方案 §0.3/0.4/M8 和
LLD §16.1/16.8/16.14；不改变 M4 写湖安全、CLI 回归、具体删除确认及 ignored 环境排除边界。

### 21.1 已完成

- [x] 基线 `dev-interface@0bae0fd0`；集中扫描 3227 个程序/配置文件，75 个文件命中候选词。结合
  CodeGraph status/explore 与实际路径代码，区分正向读写、拒绝旧路径、旧入口、测试及说明文字。
- [x] 54/54 旧 Raw 目录均有旧 catalog 精确 `storage_root`；旧 scanner 的动态读取覆盖六个旧湖家族。
  当前保留代码没有找到读取这些旧湖数据的入口，本机 Web 配置及 Reader 指向正式 Gold。
- [x] 106 个既有对象统一 `DELETE_AFTER_DEPENDENCY`：Raw 54、manifest 19、research 3、derived 2、
  旧 `_recovery` 20、旧 `_tmp` 8。名称复用此前元数据，不重新扫描文件内容；完整分组见 LLD §16.14.2。
- [x] 三份旧 CSV 报告及两个已完成分钟恢复 run 改列 `DELETE_READY`（D01–D05），精确路径见 LLD
  §16.14.3；“ready”只表示无代码用途可提请删除，不是已获批准。新 run 的路径模板不等于历史 run 数据在用。
- [x] 明确保留：当前正式数据/Reader/API、停牌 CSV、identity seed、reports 输出目录、BSE/WMT 当前
  恢复输入；旧路径拒绝规则不删除。其他正式治理隔离家族不自动扩大到本轮删除范围。
- [x] 取消剩余 49 个数据集的内容对账，以及早期日线/停牌、旧证券、身份映射差异、恢复 patch 内容
  承接、潜在人工价值与全盘 staging 盘点任务；不以这些问题延长数据清退审计。
- [x] 没有读取湖数据内容、重算湖文件 SHA、查询生产/Dagster、启动恢复或删除文件；只修改三份专项文档。

### 21.2 剩余执行项

- [ ] 用户 review 分组/具体删除清单；按批准阶段实施 M1–M7，先解除旧适配器与旧 Console 依赖。
- [ ] M8 执行前复核实际代码引用、精确路径/目录范围、符号链接、跨挂载、占用；只删明确批准的对象，
  不追加内容审计、不清共享根。两个非 Git 恢复目录删除不承诺可恢复，三个 tracked 报告可从 Git 取回。
- [ ] 记录实际执行结果，更新被删除物理位置的历史说明；本轮不提交、不推送、不进入任何删除执行。

本轮程序证据保存在 `/private/tmp/lake-retirement-code-refs-20260905.hindQZ/code_reference_audit.json`；
稳定结论已入 LLD，不依赖临时文件才能理解。实际子系统边界、依赖矩阵和运行行为未变，其他任务的
趋势通道文档与代码均未触碰。代码/CLI 重构尚未实施，因此未运行其回归或声称生产验收通过。

验证：文档完整性检查及 `git diff --check` 通过；原 156 份文档处理矩阵仍为 156 个唯一有效路径，
263 个旧产品 tracked 文件清单及其路径摘要未变。以上验证只覆盖文档和静态范围，不代表代码重构验收。

## 22. 2026-09-05 M1 执行回填（不是 M0 只读审计）

用户在代码引用分类落档后要求“继续推进”，本轮按 LLD §11 M1 迁出当前 helper；未扩大到 CLI 切换、
代码/文档删除、物理数据删除、部署或提交。基线为 `dev-interface@650c549d`。

- [x] `stk_mins_history_check_events.py` 承接成功检查计数，四个当前事件模块已切新 import。
- [x] Silver history 承接 Raw discovery/all_raw/alignment；五频一致性、排序、空范围和日期选择行为未变。
- [x] 旧 CLI 和旧 migration 原文件不变，没有新增 wrapper/alias；独立 strict audit 同名函数未改。
- [x] 33 项新增测试 + 当前静态/隔离回归共 155 passed，另有 450 subtests passed，耗时 5.80 秒。
- [x] 4 个迁出函数和 5 个保留模块 AST 等价核验通过，Ruff 默认规则及全项目致命错误检查通过。
- [x] 目标及硬口径、具体文件、性能/副作用边界、验证限度已回填原方案和 LLD M1；未修改依赖矩阵。
- [x] 用户要求提交 M1 并进入 M2A；M1 提交 `3007cc0e`，未推送。M2A 另做独立 CLI 验收，见 §23。
- [ ] 写湖集成与正式环境验证按后续阶段执行：本轮不访问正式 Lake/Dagster/DB；原写湖集成测试因默认
  DuckDB temp 指向正式盘未全跑，两处 mock target 改名对应的旧集成用例也未执行，新隔离测试覆盖其计数开关契约。

本轮代码文件共 9 个（6 个正式 Python、3 个测试，其中新增 3 个文件），具体名称见 LLD M1 文件表；
三份原专项文档同步更新。临时 AST 比对脚本为
`/private/tmp/lake-retirement-m1-20260905.YlHLoU/verify_ast_equivalence.py`，稳定结论已入文档。
没有删除数据或 Git 文件，没有修改 Ops Snapshot、停牌 CSV、身份 seed、ignored 环境、生产模块或其它任务文件。

## 23. 2026-09-05 M2A 执行回填

用户要求“提交修改，下一步是 M2A：冻结 21 个当前 CLI 命令的行为，再逐项等价迁移”。已先提交 M1，
再基于 `3007cc0e` 实施 M2A；没有把 M2B 参数收紧或 M3/M4/M6/M8 删除混进来。

- [x] 先保存旧入口固定 fixture，再创建 shared contract 与 Silver/QFQ/derived/MACD-KDJ 四个新 CLI。
- [x] 21 命令、246 组旧/新同输入双跑全部一致；21 段 handler 归一化 helper 接口后 AST 相等。
- [x] 冻结默认值、重复值、None/空 tuple、selector 优先级、dry-run/confirm/checkpoint、full/quick、
  stdout/打印对象类型及异常发生前的调用顺序。`audit-silver-final` 保留实际 dataclass 输出。
- [x] 四份现行测试、static gate 已改接正确新入口；canonical one-shot 拒绝检查保留，没有删除负例。
- [x] 全仓 tracked 程序消费者已清零后，唯一删除 `stk_mins_migration_cli.py`，无 alias；可从 Git 历史恢复。
- [x] 永久测试只对冻结 fixture 回归，不导入或恢复旧 dispatcher；另检查四 CLI 的命令归属、
  7 × 4 旧命令拒绝、shared 注入/空值、旧入口缺失与无旧直接依赖。
- [x] 5 个现有 CLI 集成测试通过，全部使用临时 Lake、ephemeral instance 和重定向临时目录的 DuckDB spill；
  不连接正式 Dagster/数据库/网络，不访问正式 Lake。具体命令与最终回归统计见 LLD §11 M2A。
- [x] 原专项方案、LLD、清单、canonical 文档与架构快照同步；后两份原已属于 156 份处理矩阵。
- [x] 用户要求提交 M2A；本次按 18 文件白名单归档，未推送；正式部署/长历史运行不在验收内。
- [x] 后续 M2B 仅实施 Silver selector 收紧和 MACD/KDJ baseline 单分区门禁，见 §24；其余冻结行为保持。

## 24. 2026-09-05 M2B 执行回填

本节是用户明确要求继续 M2B 后的实施记录，不回写为原 M0 只读审计成果。

- [x] generate Silver 删除 `--all`；register/report 删除 `--all` 和 `--all-from-raw-files`；分开 Raw/Silver selector，拒绝 `--all` 被 argparse 重新解释为缩写。
- [x] 保留显式 keys 的排序/重复值/空值/优先级、其它 option 缩写、日期边界与输出；report 无 selector 仍由原 planner 从 Silver 文件选择。
- [x] baseline 日期显式必填且相同，显式 keys 不得越出当天；CLI 在实例访问前校验，Python report 入口复核；一次 planner 后、文件审计/事件写入前检查恰好一个请求日分区。
- [x] dry-run 不能绕过；skip-ready、check/event 构造和只读多日 planner 保留。
- [x] 原 fixture 21 命令/246 案例内容完整保留，增加哈希断言和四命令 `approved_delta`；新增 54 项 CLI 与 44 项 report 门禁/现行规划链测试。
- [x] 定向回归 315 passed、696 subtests passed；原 CLI 临时环境集成 5 passed；Ruff、文档完整性、矩阵、diff 检查通过。执行命令和逐文件映射见 LLD §11 M2B。
- [x] 本轮无文件删除、无配置变更、无正式 Lake/数据库/Dagster 访问或写入；依赖边界、156 份文档矩阵、263 个旧 Console 文件清单未扩大。
- [x] M2B 已按用户要求提交 `e8e2abf9`，未推送；该阶段没有删除 migration 主体、旧 Console 或物理数据。随后用户单独授权 M3，见 §25。

旧 migration 主体、263 个旧产品文件、旧文档、物理数据、停牌 CSV、ignored 环境、Ops Snapshot
均未改动；子系统边界/依赖矩阵不变。删除前双跑脚本仅作临时证据，旧文件删除后不再作为回归入口。

## 25. 2026-09-05 M3 执行回填

本节是用户明确要求进入 M3 后的实施记录，基线 `e8e2abf9`；不回写为原 M0 只读审计成果。

- [x] 逐行复核旧模块 1,328 行和旧测试 425 行；CodeGraph `explore/impact/callers` 加全仓 tracked Python AST、文本引用核验，正向导入仅剩旧测试。
- [x] 精确删除 `orchestrator/src/orchestrator/defs/bootstrap/stk_mins_migration.py` 和 `orchestrator/tests/test_stk_mins_migration.py` 两份文件；Git 历史可恢复，无 wrapper/alias。
- [x] 旧测试 10 项逐项处置见 LLD §11 M3：8 项纯旧迁移测试退出；2 条零价格样本先改测当前 Raw check，再删除旧测试；补充负价格/空值反例，共 4 项通过。
- [x] 已迁出的 helper、四份当前 CLI、21 命令冻结 fixture 和全部保留运行代码未改；新增旧模块/CLI 不可发现与运行源码无旧 import 的防回退测试。
- [x] 删除前五组现行历史治理测试 70 passed；删除后两组无重叠回归合计 **430 passed、696 subtests passed**。覆盖完整 Silver/QFQ/derived/MACD-KDJ 历史治理、当前 Raw 合同和 identity-map asset/sensor；命令与边界见 LLD §11 M3。
- [x] 修改/新增测试 Ruff 与全 orchestrator 致命静态规则通过；同步原方案、LLD、本清单、架构快照和两份 P6A check 治理文档，旧 producer 仅作为历史事实。
- [x] 收口核验通过：2,615 份已跟踪 Python 的旧模块 import 为 0；删除恰好两份，保留运行文件和 CLI fixture 与 `e8e2abf9` 字节一致；文档完整性、156 份矩阵、263 个旧产品路径指纹与 diff 检查通过，CodeGraph 已 sync/status。
- [x] specs、source method、executor、Raw 恢复工具仍归 M4；旧 Console、历史文档、物理数据、ignored 环境、停牌 CSV、Ops Snapshot 不在本轮删除范围。
- [x] 测试使用临时 Lake、临时 DuckDB spill 和 fake/ephemeral instance；未运行正式 `dg check defs` 或任何正式任务、补事件、生产读写、部署。不能将隔离测试称为完整 code location 运行验收。
- [x] 用户要求提交 M3；本次在 `dev-interface` 按 10 文件白名单归档，不推送、不自动进入 M4。工作区两份新闻关联文档的并行修改不属于本轮，未触碰。

## 26. 2026-09-05 M4 开工与实施对账（隔离回归通过，随本次提交归档）

- [x] 用户单独授权进入 M4；基线 `dev-interface@1b0deb63`。
- [x] 完整复核 Raw 恢复模块/CLI/专属测试，CodeGraph 与引用扫描确认只有人工 CLI 正向调用；原 10 项隔离回归通过，无正式环境访问。
- [x] 核实既有字段差异：Raw schema/SQL 有 `vwap`，Silver schema/SQL 无此列，专项设计、metadata 与测试明确排除；这是既有设计，不按字段差集直接判定遗漏。历史及代码证据见 LLD §11 M4。
- [x] 用户确认删除一刀切的字段继承规则：已移除 orchestrator AGENTS 整段门禁及根 AGENTS 第 36 条同义要求。`vwap` 差异本轮不处理、不列待修复事项、不另开治理任务；撤回此前因此暂停 M4 的判断，不再待拍板。
- [x] M4 保持 Raw/Silver 字段及日常链路不变；规则删除不等于允许随意增删字段，既有契约变更审计要求保留。
- [x] 规则与口径纠正先按两份 AGENTS、专项方案、LLD、本清单的五文件白名单提交 `d2d177bb`，未推送；未纳入其它任务文件。
- [x] 此后按 LLD §6.4 先实现恢复工具正式 staging、五频候选审计、原子 checkpoint、物理指纹续跑和人工废弃，通过隔离回归后再退出旧适配器。
- [x] 删除精确 13 个旧运行模块、4 份旧测试、7 个 SQL 常量、两处旧 enum 成员与 package exports；当前 Raw 恢复、adj-factor history、Silver/QFQ/derived/MACD-KDJ 和 CLI 保留。
- [x] 全部 159 个 catalog entry 保留，只有 17 项来源声明变化；字段名/类型/顺序、日常业务代码、生产 source SQL、现行 21 命令 fixture 及保护目录不变，见 LLD §11 的逐文件对账。
- [x] 最终联合隔离回归 439 项测试、750 个参数化子例通过（33.61 秒）；覆盖五频逐一替换后中断、候选异常、目标漂移、错误字段/日期/频率/股票池、资源不足与慢任务提示，以及缺失目标的停止计划安全废弃。10 个相关干净文件完整 Ruff 通过，全体修改文件无新增问题；4 个文件保留 12 项历史 lint 问题，不掺入额外业务修改。
- [x] CodeGraph 上下文与影响分析、真实 import/AST 核验及根索引 sync/status 完成；两个同名误命中经代码核实不构成依赖。架构快照同步，跨域依赖矩阵不变。
- [x] 156 份文档矩阵和 263 个旧产品文件路径/指纹不变；没有提前删除旧 Console、物理湖、ignored 环境、报告、停牌 CSV 或 Ops Snapshot。
- [x] 用户要求提交本轮 M4；按 35 文件白名单归档，不推送，不自动进入 M5–M8。两份并行 Wealth 文档改动不属于本专项，未触碰、未纳入提交。
- [ ] 真实恢复的日期、维护窗口与容量检查在需要执行时单独确认；本轮没有生产读取、正式 Lake 写入、正式 Dagster/事件/部署或真实性能验收，不把隔离测试写成正式恢复成功。
