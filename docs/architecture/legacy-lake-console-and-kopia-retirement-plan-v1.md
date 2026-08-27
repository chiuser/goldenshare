# 旧 Lake Console、Kopia 与旧湖迁移适配器清退专项方案 v2

状态：代码逐项审计与 LLD 已完成 / 清退口径已拍板 / 等待评审与实施授权

审计日期：2026-08-27

适用仓库：`/Users/congming/github/goldenshare`

> 本文替代本文件的 v1 结论。v1 错误地把 `OLD_LAKE_BOOTSTRAP` / `old_lake_root` 留在本次范围之外，也没有完成两份旧模板的内容价值审计。本文按最终口径重新划界：清退 Kopia、旧 `lake_console/frontend + backend`，以及只负责把旧湖或历史备份数据迁入正式湖的适配器；保留现行 Dagster、ClickHouse、DuckDB/Parquet、Ops Dataset Status Snapshot、物理旧湖、`lake_console/reports/**` 和本机 ignored 环境。

代码实施细节以 [`legacy-lake-console-kopia-old-lake-bootstrap-retirement-low-level-design-v1.md`](/Users/congming/github/goldenshare/lake_console/docs/design/legacy-lake-console-kopia-old-lake-bootstrap-retirement-low-level-design-v1.md) 为准。LLD 已把混合文件逐段拆分、CLI 命令归属、catalog 精确值、测试迁移和原子删除顺序落实到符号级；若本文概括与 LLD 的代码级结论冲突，以当前代码复核后的 LLD 为准并同步修正本文。

---

## 0. 已拍板结论

### 0.1 本次 Git 清退范围

本次只清退三类对象：

1. **Kopia 能力**：备份、写前 snapshot、repository/snapshot 查询、恢复命令提示、配置、API、UI 和测试。
2. **旧 Lake Console 产品**：`lake_console/backend/**` 与 `lake_console/frontend/**`，以及只服务它们的 CLI、启动脚本、配置样例和测试；前后端必须同轮原子删除。
3. **旧湖迁移适配器**：`OLD_LAKE_BOOTSTRAP`、`old_lake_root`、对应 bootstrap spec/executor、旧迁移命令、只服务旧湖迁移的 SQL、事件补录代码、catalog 声明和测试。

这里的“旧湖迁移适配器”既包括从 `/Volumes/datasource/goldenshare-tushare-lake` 读取旧 Console 湖数据，也包括沿用同一旧迁移抽象、从 `/Volumes/datasource/backup/research/stk_mins_by_date_clean_next` 向正式湖迁移的 `stk_mins` 一次性历史链。它们都不是当前数据集正常同步或正式湖内部派生能力。

### 0.2 两份模板的最终处置

| 文档 | 内容是否还有价值 | 是否还能作为现行模板 | 最终处置 |
|---|---|---|---|
| `docs/templates/lake-dataset-development-template.md` | **有部分价值**。源端输入输出、显式字段、分页/fan-out、DuckDB 类型、请求/连接/内存/写入/重试估算、小文件分析、临时文件校验与原子替换、真实 smoke 等检查仍有用 | **不能**。主体仍指导向已退役的旧 Console Catalog/Planner/Strategy/CLI/frontend，以及旧 `raw_tushare/manifest/derived/research` 目录和旧 sync 命令 | 先把正式 Dagster onboarding 模板缺失的有效检查合并进去，更新现行引用，然后删除旧模板；不留 tombstone 模板 |
| `docs/templates/lake-prod-raw-db-export-template.md` | **有少量通用价值**。只读事务、表/列白名单、显式投影、参数绑定、单连接流式读取、`fetchmany`、schema/行数对账等仍有用 | **不能**。它定义的是 prod raw DB → 旧 Lake Console 的导出链，目标代码、目录、CLI 和页面均将删除 | 把缺失的通用数据库读取约束并入正式 Dagster 模板或性能治理文档，更新引用，然后删除旧模板；不留 tombstone 模板 |

正式新湖数据集接入只保留一个 Lake 专项入口：

```text
lake_console/docs/templates/dagster-dataset-onboarding-template.html
```

`docs/templates/dataset-development-template.md` 仍作为生产 `DatasetDefinition` / Ops 数据集开发模板保留，它与正式 Dagster Lake onboarding 模板职责不同。

### 0.3 本次明确不处理

1. 物理旧湖 `/Volumes/datasource/goldenshare-tushare-lake`：本次不读取、不改写、不删除。代码清退完成后另立物理数据审计。
2. 本机 ignored 目录和配置：本次不删除。Git 清退稳定后逐路径精确处理。
3. `lake_console/reports/**`：保留，不随旧 Console 删除。
4. `ops.dataset_status_snapshot` 及其 ORM、service、CLI、任务完成副作用、freshness/date completeness 查询和页面消费者：全部保留。
5. `lake_console/orchestrator/**` 的正式 Dagster 主链、当前 ClickHouse、DuckDB、Parquet、正式 Lake 读写和无 Kopia 发布机制：全部保留。
6. 根目录现行运营后台 `frontend/**`、Wealth、QTF、`src/foundation/clients/local_lake/**`：全部保留。
7. 历史文档和历史 Dagster event 中用于说明过去事实的旧湖/Kopia 字样：允许保留，但不能继续构成可执行入口。
8. 对旧湖路径和 Kopia 的禁止性规则、负向测试：保留并按新事实更新。

### 0.4 待拍板项

**没有遗留的方案设计决策。**

下一步唯一需要用户授权的是：是否按本文开始实际删除与修改。物理旧湖和 ignored 环境不是本轮待拍板项，它们已经明确延期到代码清退之后的独立审计。

---

## 1. 清退语义和完成标准

### 1.1 禁止按关键词删除

不得因为名称包含 `snapshot`、`lake`、`backup`、`bootstrap`、`recovery`、`duckdb` 或 `parquet` 就删除。每个对象必须按真实生产者、消费者和数据方向判断。

| 语义 | 本次处理 | 原因 |
|---|---|---|
| Kopia snapshot / repository / restore / prewrite backup | 删除 | 本次明确清退对象 |
| `ops.dataset_status_snapshot` | 保留 | 当前 Ops 状态投影，有真实读写消费者 |
| 数据集的 no-time snapshot 输入语义 | 保留 | 数据模型语义，与 Kopia 无关 |
| 正式 Lake candidate/audit/promote/checkpoint/原子替换 | 保留 | 当前无 Kopia 写湖安全主链 |
| 旧湖/历史备份 → 正式湖 bootstrap | 删除 | 一次性迁移适配器，不是现行同步能力 |
| 正式湖内部 raw → silver → gold 派生 | 保留 | 当前生产数据链 |
| 正式 Tushare / prod DB readonly ingestion | 保留 | 当前源端接入能力 |
| 历史文档中的旧路径和旧 source metadata | 作为历史证据保留 | 不能篡改已发生事实 |

### 1.2 旧 Lake Console 的精确定义

```text
lake_console/backend/**
lake_console/frontend/**
lake_console/bin/lake-console
scripts/local-lake-console.sh
lake_console/config.local.example.toml
tests/lake_console/**
```

它不等于整个 `lake_console/`。以下对象必须保留：

```text
lake_console/orchestrator/**
lake_console/docs/**
lake_console/reports/**
lake_console/bin/lake-clickhouse-start
lake_console/bin/lake-prod-clickhouse-tunnel
```

### 1.3 旧湖迁移适配器的精确定义

本专项所说的适配器，是以 `OLD_LAKE_BOOTSTRAP` / `old_lake_root` 为核心，读取旧湖或历史备份并向正式 Lake 写入、补事件或做迁移验收的一整条执行链，包括：

1. source method / source system / ingestion source 枚举成员。
2. `BootstrapDatasetSpec`、旧湖 executor 及其 exports。
3. 各数据集 `*_bootstrap_spec`。
4. `stk_mins_migration.py` 中的旧 raw/identity-map 迁移、事件补录和最终审计。
5. `stk_mins_migration_cli.py` 中的旧迁移子命令和参数。
6. 只用于旧 bootstrap 的 DuckDB SQL template。
7. catalog 中对旧 bootstrap 源和 bootstrap spec 的正向声明。
8. 只为旧迁移存在的测试和旧 bootstrap 文档模板。

不在该定义内：正式 Lake 当前资产、正式历史回补、BSE 恢复、silver/qfq/技术指标事件补录，以及它们共用的中性校验工具。混合文件必须先拆出这些现行能力，才能删除旧迁移部分。

### 1.4 完成标准

只有同时满足以下条件，专项才可宣布完成：

1. 旧 Console 前后端及专属入口全部清零。
2. 可执行代码和可生效配置中不再存在 Kopia 正向能力。
3. 可执行代码中不再存在旧湖/历史备份到正式湖的 bootstrap reader、参数、命令和 catalog 入口。
4. `OLD_LAKE_BOOTSTRAP`、`old_lake_root` 等正向运行契约清零；负向守卫和历史文字不要求字符串清零。
5. 混合迁移文件中的现行中性 helper 已迁到合适的当前模块，所有消费者改用新位置，不留兼容 wrapper 或 alias。
6. 两份旧模板的有效内容已吸收到正式文档，现行引用已切换，旧模板和旧 bootstrap migration 模板已删除。
7. 正式 Dagster、ClickHouse、正式 Lake Reader、Ops Snapshot 等保留主链通过回归。
8. 未触碰物理旧湖、正式 Lake 数据、数据库业务表、Dagster instance、`lake_console/reports/**` 和本机 ignored 环境。

---

## 2. 审计依据与方法

### 2.1 必读规则和现行设计

本轮按当前代码和以下规则交叉审计，不以旧文档标题或历史印象作结论：

1. 根 `AGENTS.md`。
2. `lake_console/AGENTS.md`。
3. `lake_console/orchestrator/AGENTS.md`。
4. `lake_console/orchestrator/CODING_STANDARDS.md`。
5. `lake_console/docs/design/dagster-data-pipeline-performance-governance.md`。
6. `lake_console/docs/design/dagster-asset-schema-contract-design.md`。
7. `lake_console/docs/templates/dagster-dataset-onboarding-template.html`。
8. 本次被评估的两份旧模板全文。

### 2.2 CodeGraph 与文本复核

CodeGraph 审计时索引为 up to date：

| 指标 | 数值 |
|---|---:|
| files | 2,736 |
| nodes | 48,208 |
| edges | 111,611 |
| backend | node:sqlite / full WAL |

影响面查询至少覆盖：

1. `BootstrapDatasetSpec`。
2. `OLD_TUSHARE_LAKE_ROOT`。
3. `BootstrapSourceMethod`。
4. `IngestionSource`。
5. `plan_stk_mins_migration`。
6. `stock_identity_map_bootstrap_spec`。

CodeGraph 对 enum member 字符串和动态 CLI 分支覆盖有限，因此又用全仓文本搜索和逐文件阅读复核了入口、调用方、被调用方、测试、文档和 catalog。

### 2.3 审计边界

本轮是静态只读审计：没有运行 `dg`，没有加载或写入 Dagster instance，没有执行迁移、materialize、job、sensor、backfill、runless event、数据库写入或 Lake 写入。

---

## 3. 当前代码事实

### 3.1 旧 Console 与 Kopia 是闭合旧产品

旧 frontend 只消费旧 backend 的 `/api/lake/**` 和 `/api/recovery/**`；旧 backend 的 catalog、sync center、recovery、DuckDB compute 和 Kopia 服务没有挂入 `src/app` 或正式 orchestrator。

```text
旧 frontend
  -> 旧 /api/lake/**、/api/recovery/**
  -> 旧 backend catalog/sync/recovery
  -> 旧湖目录与 Kopia
```

未发现 `src/**`、根 `frontend/**`、`wealth/**`、`qtf/**` 或 `lake_console/orchestrator/src/**` 对旧 backend 的正向运行时 import。旧前后端及其专属外围可以原子删除，不需要把业务逻辑迁入正式 orchestrator。

### 3.2 旧迁移适配器不是一个文件，而是分布式契约

#### 枚举和公共契约

| 位置 | 旧契约 |
|---|---|
| `defs/bootstrap/source_method.py` | `BootstrapSourceMethod.OLD_LAKE_BOOTSTRAP` |
| `defs/run_contracts/metadata.py` | `SourceSystem.OLD_LAKE_BOOTSTRAP` |
| `defs/catalog/lake_assets.py` | `IngestionSource.OLD_LAKE_BOOTSTRAP` |

`SourceSystem.OLD_LAKE_BOOTSTRAP` 没有发现正向现行消费者；其存在主要是旧迁移 metadata 合法值。上述成员在旧 producer 清零后应删除，不能作为“历史事件兼容”继续留在可执行契约中。

#### 通用 spec 和 executor

`BootstrapDatasetSpec` 硬编码 `old_lake_path_pattern`，并且只接受旧湖 bootstrap source。它不是通用的当前历史回补抽象。`defs/bootstrap/old_lake_executor.py` 也专门读取旧路径并向正式层写入。两者连同 `defs/bootstrap/__init__.py` 的 exports 应在消费者清零后删除，不改名伪装成通用框架。

#### 数据集 spec

| 数据集 | 旧来源 | 处置 |
|---|---|---|
| `adj_factor` | `/Volumes/datasource/goldenshare-tushare-lake` | 删除 bootstrap spec；保留当前 Tushare/raw/silver 链 |
| `stock_basic` | 同上 | 删除 bootstrap spec；保留当前正式资产 |
| `stock_daily` | 同上 | 删除 bootstrap spec；保留当前正式资产 |
| `suspend_d` | 同上 | 删除 bootstrap spec；保留当前正式资产 |
| `trade_calendar` | 同上 | 删除 bootstrap spec；保留当前正式资产 |
| `stock_identity_map` | 旧 manifest | 删除旧 manifest bootstrap；保留当前 versioned seed + `stock_basic`/`namechange` 正式资产 |
| `stk_mins` | `/Volumes/datasource/backup/research/stk_mins_by_date_clean_next` | 删除一次性 backup → 正式湖迁移 spec；保留现行分钟历史处理和派生链 |

### 3.3 `stk_mins_migration.py` 不能整文件先删

该文件混合了两类代码。

应删除的旧迁移能力：

1. raw backup migration plan/execute。
2. 从旧湖 manifest 迁移 identity map。
3. raw/identity-map bootstrap runless event 补录。
4. 旧迁移 final audit。
5. `old_lake_bootstrap` source metadata。

仍被现行模块消费的中性 helper：

| helper | 当前消费者 |
|---|---|
| `discover_raw_stk_mins_partitions` | `stk_mins_silver_history.py` |
| `_validate_backup_partition_alignment` | `stk_mins_silver_history.py` |
| `_check_success_count` | silver/qfq/derived/technical bootstrap event 模块 |

安全顺序必须是：

1. 给中性 helper 重新命名并移入现行 history/event utility。
2. 修改全部现行消费者和测试。
3. 确认旧迁移函数无调用方。
4. 删除旧迁移模块剩余内容或整文件。

禁止为了降低改动量留下旧 module wrapper、re-export 或 deprecated alias。

### 3.4 `stk_mins_migration_cli.py` 也是混合入口

逐行审计确认要删除的旧子命令共 7 个：

1. `dry-run` 迁移 plan。
2. `migrate-raw`。
3. `migrate-identity-map`。
4. `register-partitions`。
5. `report-raw-events`。
6. `report-identity-map-events`。
7. `audit-final`。

同一 dispatcher 还包含 21 个当前命令。实施时按职责迁入 `stk_mins_silver_history_cli.py`、`stk_mins_qfq_history_cli.py`、`stk_mins_qfq_derived_history_cli.py`、`stk_mins_qfq_macd_kdj_history_cli.py` 四个入口，再删除原混合 dispatcher。`old-lake-root`、`backup-root`、旧选择器和旧命令不迁移；当前命令名与输出字段保留。完整命令映射和参数收紧见 LLD 第 4 章。

### 3.5 只删除旧 bootstrap SQL，不删除 SQL 公共模块

`duckdb_sql.py` 是混合 contract 文件。只删除以下旧模板及其专属测试：

```text
TRADE_CALENDAR_BOOTSTRAP_SELECT_TEMPLATE
STOCK_BASIC_BOOTSTRAP_SELECT_TEMPLATE
STOCK_DAILY_BOOTSTRAP_SELECT_TEMPLATE
STOCK_IDENTITY_MAP_BOOTSTRAP_SELECT_TEMPLATE
ADJ_FACTOR_BOOTSTRAP_SELECT_TEMPLATE
SUSPEND_D_BOOTSTRAP_SELECT_TEMPLATE
STK_MINS_BOOTSTRAP_SELECT_TEMPLATE
```

其他当前 DuckDB SQL contract 必须保留。

### 3.6 Catalog 必须按真实来源改，不可机械替换 enum

当前 `IngestionSource.OLD_LAKE_BOOTSTRAP` 出现在多个资产声明中。清退后的正确处理不是统一替换成另一个 source：

| 资产 | 清退后来源口径 |
|---|---|
| silver `adj_factor` | `bootstrap_sources=(DERIVED_FROM_ASSETS,)` |
| raw `stk_mins` | ingestion 保留 `TUSHARE_API` / `PROD_DB_READONLY`；`bootstrap_sources=(PROD_DB_READONLY,)`，用于当前正式生产库只读的单日五频恢复 |
| silver `stk_mins` | `bootstrap_sources=(DERIVED_FROM_ASSETS,)` |
| gold `stk_mins_qfq` | `bootstrap_sources=(DERIVED_FROM_ASSETS,)` |
| silver `index_daily` | `bootstrap_sources=(DERIVED_FROM_ASSETS,)` |

代码复核后共确认 17 个 catalog entry 需要修改。实施时必须逐个对照 asset definition、job/sensor 和真实读取路径，禁止为了让 enum 消失而机械改 catalog 文本。尤其不得清空 Raw `stk_mins` 的 bootstrap source，否则会与当前 `stk_mins_raw_replace_from_prod` 恢复能力冲突。

### 3.7 一次性事件补录模块的处置

`adj_factor_raw_bootstrap_events.py` 和 `adj_factor_silver_bootstrap_events.py` 目前只发现测试 import，没有正式 definitions、CLI 或当前生产调用方；它们属于旧湖迁移后的事件补录，应直接删除。

`stk_mins` 相关 event 模块不能按名字批量删除。仍用于当前 silver/qfq/technical 历史事件治理的模块必须保留，仅移除对旧迁移 module helper 的依赖。

### 3.8 历史 Dagster event 不需要数据迁移

旧 event 中的 `source_method=old_lake_bootstrap` 是普通历史 metadata 字符串。当前代码中没有发现依据该字符串驱动业务读取、readiness、恢复或调度的逻辑。

因此：

1. 删除 enum 和 producer，不修改、不删除历史 Dagster event。
2. 历史 UI 仍可显示原 metadata 字符串。
3. 不建立兼容 enum，不做 event rewrite，不触碰 Dagster storage。

### 3.9 旧路径正向读取和负向守卫必须区分

应清零：

1. `old_lake_root` 参数。
2. `old_lake_path_pattern`。
3. 旧根到正式湖的 reader/executor/spec/CLI。
4. 正向建议用户使用旧根的现行文档和模板。

应保留：

1. 根 `AGENTS.md` 对旧根的禁止规则。
2. `stock_daily_qfq_nineturn_no_price_history.py` 的 `FORBIDDEN_LEGACY_LAKE_ROOT`。
3. `stk_mins_bse_history_recovery.py` 对旧根的拒绝。
4. 证明旧路径不能再作为输入的负向测试。
5. 历史执行记录中的旧绝对路径。

所以验收不能使用“全仓旧路径字符串为 0”。正确门禁是“正向可执行 reader/参数/入口为 0，禁止性和历史性引用仍合法”。

### 3.10 两份旧模板与正式模板的覆盖关系

正式 Dagster onboarding 模板已经覆盖：资产分层、schema contract、partition、resource、asset/check/job/sensor、readiness、事件治理、测试与验收等主流程。旧 `lake-dataset-development-template.md` 仍独有或写得更具体的有效点主要是：

1. 源端显式字段与分页/fan-out 量级。
2. DuckDB 类型映射和精度风险。
3. 请求数、连接数、内存、写入、重试、配额估算。
4. 文件数与小文件风险。
5. 临时文件校验、同文件系统原子替换。
6. 最小真实 smoke 的输入行、归一化行、写入行和拒绝原因对账。

旧 raw DB export 模板的有效增量主要是：

1. read-only transaction。
2. table/column whitelist。
3. explicit projection，禁止 `SELECT *`。
4. 参数绑定。
5. 单个受限连接和流式 `fetchmany`，禁止大结果 `fetchall`。
6. schema、源端行数、导出行数和目标行数对账。

这些是检查项，不足以证明两份旧文档仍应作为独立模板存在。保留它们会继续把新开发导向已删除的产品结构，因此必须“吸收有效内容后删除”，而不是加一个历史 banner 后继续留在 templates 目录。

### 3.11 测试也必须按语义拆分

可以随纯旧实现直接删除：

```text
lake_console/orchestrator/tests/test_adj_factor_bootstrap_spec.py
lake_console/orchestrator/tests/test_adj_factor_raw_bootstrap_events.py
lake_console/orchestrator/tests/test_adj_factor_silver_bootstrap_events.py
```

必须先拆旧断言、迁出现行覆盖：

| 测试 | 处理 |
|---|---|
| `test_stk_mins_bootstrap_spec.py` | 删除旧 backup/identity-map bootstrap 断言；若无现行语义剩余再删文件 |
| `test_stk_mins_migration.py` | 先把中性 helper 覆盖迁到新 utility 测试，再删除旧 migration cases；无剩余后删文件 |
| `test_adj_factor_contracts.py` | 只删除旧 bootstrap select-template 断言，保留当前 adj-factor contract |
| `test_stk_mins_contracts.py` | 只删除旧 bootstrap select-template 断言，保留当前分钟 contract |
| `test_stk_nineturn_history.py` | 保留 `old_lake_bootstrap` 被拒绝的负向测试，不因字符串命中而删除 |

删除测试的依据必须是被测能力退役，不得为了让测试通过而删掉保护现行能力的断言。

---

## 4. 文件级处置分类

### 4.1 A 类：同轮直接删除

| 对象 | 说明 |
|---|---|
| `lake_console/backend/**` | 旧 FastAPI、CLI、catalog、sync、DuckDB compute、Parquet writer、Kopia 与专属测试 |
| `lake_console/frontend/**` | 只消费旧 backend，不能独立运行 |
| `lake_console/bin/lake-console` | 只进入旧 backend CLI |
| `scripts/local-lake-console.sh` | 只启动旧 backend/frontend |
| `lake_console/config.local.example.toml` | 只描述旧 Console/Kopia/旧 root 配置 |
| `tests/lake_console/**` | 只测试旧产品和旧入口 |
| `lake_console/docs/templates/dagster-bootstrap-migration-template.html` | 专门指导旧湖 → 新湖 bootstrap |
| `adj_factor_raw_bootstrap_events.py` | 旧迁移事件补录，无现行生产消费者 |
| `adj_factor_silver_bootstrap_events.py` | 同上 |
| 纯旧 bootstrap spec 文件及专属测试 | 无当前同步用途 |

### 4.2 B 类：先拆现行依赖，再删除旧实现

| 对象 | 先做什么 | 再删除什么 |
|---|---|---|
| `stk_mins_migration.py` | 迁出中性 partition/alignment/success-count helper，改完消费者和测试 | 旧 raw/identity migration、event report、audit 和旧 metadata |
| `stk_mins_migration_cli.py` | 迁出现行 silver/qfq/technical/repair 子命令到当前命名 CLI | 旧迁移 dispatcher、old-lake/backup 参数和命令别名 |
| `duckdb_sql.py` | 确认每个模板消费者并保留当前 SQL | 七个旧 bootstrap select templates |
| `defs/bootstrap/__init__.py` | 先更新所有 imports | 旧 spec/executor/source exports |
| `defs/catalog/lake_assets.py` | 按真实当前 source 重写受影响资产 | 旧 source 和 bootstrap spec 引用 |
| 混合 contract tests | 先保留当前 SQL/资产断言 | 仅删除旧 bootstrap 断言 |

### 4.3 C 类：修改现行契约后清零旧符号

1. 删除 `BootstrapSourceMethod.OLD_LAKE_BOOTSTRAP`。
2. 删除 `SourceSystem.OLD_LAKE_BOOTSTRAP`。
3. 删除 `IngestionSource.OLD_LAKE_BOOTSTRAP`。
4. 删除 `BootstrapDatasetSpec`、旧 executor 和各数据集旧 spec。
5. 删除 `old_lake_root` / `old_lake_path_pattern` 参数和配置。
6. 删除旧 bootstrap CLI/API/metadata producer。
7. 保留能证明旧 source/path 被拒绝的负向测试；测试里的字符串不要求清零。

### 4.4 D 类：模板和引用先迁后删

旧 `lake-dataset-development-template.md` 当前被以下类型文档引用：

1. `docs/README.md` 模板索引。
2. 旧 Local Lake 架构/命令/access-mode 文档。
3. 历史数据集开发记录。
4. 仍属正式 Dagster 范围的 index-mins / major-index-mins onboarding 方案。

其中以下两份是现行 Dagster 方案，必须直接切换到正式模板，不能按历史链接处理：

```text
lake_console/docs/design/dagster-index-mins-data-onboarding-plan.md
lake_console/docs/design/dagster-major-index-mins-data-onboarding-plan.md
```

处置规则：

1. 现行 Dagster 方案必须改指向正式 Dagster onboarding 模板。
2. `docs/README.md` 只保留正式模板入口。
3. 历史文档若需要证明当时依据，使用不可点击的历史路径文字或在文首说明模板已删除；不得恢复死链接。
4. 有效检查项合并完成并通过文档审计后，删除旧模板。

旧 `lake-prod-raw-db-export-template.md` 的现行引用同样切到正式模板/性能治理；历史引用按历史路径处理。旧 Lake 模板之间的互相引用必须一起清理，不能留下链式死链接。

### 4.5 E 类：明确保留

```text
lake_console/orchestrator/**
lake_console/docs/**（除明确删除的旧 bootstrap 模板）
lake_console/reports/**
lake_console/bin/lake-clickhouse-start
lake_console/bin/lake-prod-clickhouse-tunnel
src/foundation/clients/local_lake/**
src/foundation/config/local_minute_capability.py
根 pyproject.toml 的 local-lake DuckDB 可选依赖
ops.dataset_status_snapshot 全链
正式 Lake candidate/audit/promote/checkpoint/原子替换
正式 stock_identity_map 资产、job、sensor、checks/readiness
```

### 4.6 F 类：代码清退后另轮处理

物理旧湖：

```text
/Volumes/datasource/goldenshare-tushare-lake
```

ignored 候选：

```text
lake_console/.venv/
lake_console/frontend/node_modules/
lake_console/frontend/dist/
lake_console/frontend/*.tsbuildinfo
lake_console/config.local.toml
```

以上本轮全部不动。后续必须逐路径确认存在性、用途、恢复要求和删除边界，不能使用上层目录递归删除。

---

## 5. 文档治理口径

### 5.1 现行规则必须改成清退后事实

实施轮至少更新：

1. 根 `AGENTS.md`：从“现存 Kopia/旧 backend 是冻结证据”改为“已删除，禁止恢复”；移除把旧湖作为 bootstrap 输入的例外。
2. `lake_console/AGENTS.md` 和 `lake_console/README.md`：删除旧 Console 启动、页面、CLI 和配置入口，只描述正式 orchestrator、docs/reports 和保留工具。
3. `lake_console/orchestrator/AGENTS.md`：删除“旧 Lake 是受控迁移源”的正向许可，保留旧路径拒绝规则。
4. `lake_console/orchestrator/CODING_STANDARDS.md`：把旧 import 禁令更新为“不得恢复已删除模块”。
5. `.agents/skills/frontend-qa/SKILL.md`：删除旧 frontend 适用范围和命令。
6. `.agents/skills/lake-dataset-onboarding/SKILL.md`：现行入口只指向正式 Dagster 模板。
7. `scripts/AGENTS.md`：删除旧启动脚本规则。
8. `docs/README.md`：移除两份旧模板和旧 Console 的现行入口。

### 5.2 正式 Dagster 文档

1. `lake_console/docs/templates/dagster-dataset-onboarding-template.html`：吸收第 3.10 节有效检查项；删除旧 bootstrap 作为正常接入路径的章节和 checklist。
2. `lake_console/docs/design/dagster-data-pipeline-performance-governance.md`：如正式模板不适合承载通用 prod DB 流式读取约束，则把它们落在此处并由模板引用。
3. `lake_console/docs/design/dagster-bootstrap-legacy-links.md`：保留为已结束迁移的历史总账，写明执行代码已清退、物理旧湖延期审计、不可再作为运行入口。
4. `lake_console/docs/architecture/dagster-data-system-architecture.html`：删除 `KopiaResource` 正向建议。
5. `lake_console/docs/design/dagster-new-lake-asset-catalog-design.md` 和 run-contract 治理文档：移除旧迁移 source 的现行契约表述。
6. `dagster-phase-2-design.html` 等历史设计：保留历史事实并加退役边界，不把历史方案重写成从未发生。

### 5.3 历史旧 Console 文档

旧 Local Lake 架构、页面、API、Kopia、Sync Center、repair 和数据集开发记录逐份保留为历史证据，不批量删除。每份按以下规则审计：

1. 文首是否明确“历史/冻结/不可执行”。
2. 是否仍用现在时宣称旧功能可用。
3. 是否包含可点击的已删除代码链接。
4. 是否被 `docs/README.md` 或现行方案当作入口。
5. 是否混有仍有效的正式 Dagster/生产内容；混合文档只修边界，不误删现行部分。

历史文件可以记录 `OLD_LAKE_BOOTSTRAP`、旧绝对路径、Kopia 命令和执行结果，但必须是历史叙述，不能留下可复制的现行操作指导。

---

## 6. 实施顺序

### M0：删除前复核和精确白名单

1. 同步并确认 CodeGraph 状态。
2. 重跑旧 backend import、旧 API、Kopia、旧 migration symbol、old-lake 参数和模板引用扫描。
3. 对混合模块重新列出正向消费者。
4. 只读检查本机是否仍有旧 Console 进程；发现遗留进程只说明运行状态，不扩大代码保留范围。
5. 形成 tracked 文件删除白名单和修改白名单；不得使用目录上层模糊删除。

准入：依赖图与本文第 3、4 节一致；任何新增消费者都必须先补回方案。

### M1：先迁出混合模块中的现行能力

1. 迁移 `stk_mins_migration.py` 中的中性 helper。
2. 拆出现行 silver/qfq/technical/repair CLI。
3. 更新全部 imports、dispatcher 和测试。
4. 验证正式 history/event/repair 路径不再依赖名称含 `migration` 的旧模块。

准入：旧 migration module 只剩待删能力，现行消费者为 0。

### M2：模板内容归并与现行引用切换

1. 将两份旧模板的有效增量写入正式 Dagster onboarding 模板或性能治理文档。
2. 删除正式模板中旧湖 bootstrap 作为正常路径的内容。
3. 更新所有现行 onboarding 方案和 `docs/README.md` 引用。
4. 处理历史文档中的模板死链接和历史说明。
5. 删除两份旧模板和 `dagster-bootstrap-migration-template.html`。

准入：新数据集接入不需要打开任何待删除模板，且正式模板覆盖第 3.10 节检查项。

### M3：原子删除旧 Console 和 Kopia

精确删除第 4.1 节旧产品对象。前端、后端、专属脚本、配置样例和测试必须同轮完成。

删除后立即反查以下路径仍存在：

```text
lake_console/orchestrator/**
lake_console/docs/**
lake_console/reports/**
lake_console/bin/lake-clickhouse-start
lake_console/bin/lake-prod-clickhouse-tunnel
```

### M4：删除旧湖迁移适配器

1. 删除旧 bootstrap dataset specs 和 executor。
2. 删除旧 enum members、exports、CLI 分支和参数。
3. 删除七个旧 SQL templates。
4. 逐资产修正 catalog source/bootstrap 声明。
5. 删除一次性旧 event 模块和专属测试。
6. 删除旧 producer 后，确认历史 event 无需数据迁移。
7. 保留并补强旧根拒绝测试。

### M5：规则和历史文档收口

按第 5 节修改规则、README、skills、现行设计、历史总账和死链接。更新 CodeGraph 架构快照时只写清退后的真实边界。

### M6：回归验收

执行第 7 节的静态、单元、definitions、文档和差异门禁。任何保留主链失败都必须修复真实依赖，禁止恢复兼容 wrapper、空 module、旧 enum 或旧 CLI alias。

### M7：后续独立工作，不属于本轮

1. 物理旧湖逐目录数据审计，另行决定是否删除。
2. ignored 环境逐路径精确删除。
3. 两者都需要独立清单和回退口径，不与 Git 代码清退混合。

---

## 7. 验收门禁

### 7.1 删除和保留路径

预期清零：

```text
lake_console/backend
lake_console/frontend
lake_console/bin/lake-console
scripts/local-lake-console.sh
lake_console/config.local.example.toml
tests/lake_console
docs/templates/lake-dataset-development-template.md
docs/templates/lake-prod-raw-db-export-template.md
lake_console/docs/templates/dagster-bootstrap-migration-template.html
```

预期保留：

```text
lake_console/orchestrator
lake_console/docs
lake_console/reports
lake_console/bin/lake-clickhouse-start
lake_console/bin/lake-prod-clickhouse-tunnel
src/foundation/clients/local_lake
src/ops/models/ops/dataset_status_snapshot.py
src/ops/services/operations_dataset_status_snapshot_service.py
```

### 7.2 正向运行契约清零

1. 旧 backend/frontend/Kopia 正向入口为 0。
2. `OLD_LAKE_BOOTSTRAP` 三类 enum member 为 0。
3. `BootstrapDatasetSpec` 和 old-lake executor 正向消费者为 0，定义文件已删除。
4. `old_lake_root` / `old_lake_path_pattern` 可执行参数为 0。
5. 七个旧 SQL template 定义与消费者为 0。
6. catalog 不再声明旧 bootstrap source/spec。
7. 当前 history/event/repair 代码不 import 旧 migration module。

允许保留：历史文档、历史 event metadata、禁止规则和负向测试中的旧字符串。

### 7.3 正式 Dagster 回归

实施时按实际变更文件选择并记录定向测试，至少覆盖：

1. definitions/asset governance 静态门禁。
2. catalog contracts。
3. run-contract metadata contracts。
4. stock identity map 正式资产、job、sensor、checks/readiness。
5. `stk_mins` silver history、qfq、technical、repair 和 event 模块。
6. ClickHouse definitions 和资源边界。

`dg` definitions 检查需要按仓库规则另行获得明确执行授权；不得把本方案评审视为自动授权。任何验收不得触发 materialize、job、sensor、backfill 或 runless event。

### 7.4 现行 DuckDB/Parquet、Ops 和前端保护

1. `src/foundation/clients/local_lake/**` 与分钟 API 回归通过。
2. 根 `pyproject.toml` 的 `local-lake` DuckDB optional dependency 仍在。
3. Ops Dataset Status Snapshot 的 service/query/CLI/worker/API 回归通过。
4. 根 `frontend/**` 构建/定向测试不受旧 frontend 删除影响。
5. ClickHouse 启动和 tunnel 脚本仍存在并通过语法检查。

### 7.5 模板验收

正式 Dagster onboarding 模板必须能独立回答：

1. 源端参数、字段、分页和 fan-out 如何验证。
2. 请求量、连接、内存、文件数、小文件、重试和配额如何估算。
3. schema/DuckDB 类型和精度如何确认。
4. 写入如何做临时文件校验、原子替换、checkpoint 和幂等恢复。
5. prod DB 读取如何保证只读、白名单、显式投影、参数绑定和流式拉取。
6. 真实 smoke 如何对账源端、归一化、写入、拒绝和目标行数。

如果任何一项只能从旧模板找到，M2 不得通过，旧模板不能先删。

### 7.6 文档与工作区门禁

```bash
python3 scripts/check_docs_integrity.py
git diff --check
git status --short
git diff --name-status
```

实施时必须使用精确 staged 白名单，禁止 `git add .`。用户工作区中的无关改动不得纳入专项。

---

## 8. 风险与防误删措施

| 风险 | 后果 | 防线 |
|---|---|---|
| 把整个 `lake_console/` 当旧产品删除 | 正式 Dagster、ClickHouse、docs/reports 丢失 | 只按精确路径删除，反查保留清单 |
| 看到 `snapshot` 就删除 | 误删 Ops Snapshot 或数据模型语义 | 按真实调用链和语义分类 |
| 整删 `stk_mins_migration.py` | 当前 history/event 链 import 失败 | 先迁中性 helper，再删旧模块 |
| 整删 migration CLI | 当前 qfq/technical/repair 命令丢失 | 先迁当前子命令和 dispatcher |
| 机械替换 catalog enum | 资产来源事实被伪造 | 每个资产对照真实 reader/asset/job |
| 为历史 event 保留旧 enum | 旧迁移契约永久残留 | 历史 metadata 按字符串保留，不保留 producer/enum |
| 全仓旧路径字符串清零 | 误删禁止规则和历史证据 | 只要求正向 reader/参数清零 |
| 旧模板先删、有效检查未迁 | 新数据集接入失去性能/安全门禁 | 正式模板逐项覆盖后再删 |
| 旧模板只加历史 banner 仍留在 templates | 新开发继续误用 | 更新引用后从 templates 删除 |
| 删除旧 backend 时连 DuckDB/Parquet 依赖一起删 | 当前正式 Lake/分钟查询失效 | 保留现行 reader 和 optional dependency 回归 |
| 顺带删除物理旧湖、reports、ignored 环境 | 未审计数据或证据丢失 | 明确分轮，当前禁止触碰 |

---

## 9. 回退姿态

1. 本次 Git 清退不包含数据库迁移、Dagster event rewrite、Lake 数据写入或物理目录删除。
2. 合并前通过精确 diff 恢复误删；合并后整体 revert 清退提交。
3. 旧 Console frontend/backend 必须整体回退，不能只恢复一侧。
4. 不允许把 Kopia、旧 enum、旧 module wrapper、旧 CLI alias 或空壳 package 恢复为“临时兼容”。
5. 模板回退必须连同引用和正式模板内容一起评估，不能只恢复旧模板入口。
6. 物理旧湖和 ignored 环境未来各自拥有独立回退/恢复方案。

---

## 10. 最终评审结论

### 10.1 可以直接删除

旧 Console 前后端及专属外围、纯旧 bootstrap spec/event/template/test，可以在删除前引用复核通过后直接删除。

### 10.2 必须拆依赖后再删

`stk_mins_migration.py`、`stk_mins_migration_cli.py`、`duckdb_sql.py`、catalog、bootstrap exports 和混合 tests 不能整文件先删；必须先迁出现行能力或删除旧分支的消费者，再清退旧实现。

### 10.3 两份旧模板是否还有用

两份文档都包含值得保留的检查项，但**都不再适合作为独立、现行模板继续使用**。正确处置是把有效内容并入正式 Dagster onboarding/性能治理文档，切换现行引用，然后删除旧模板。`lake-dataset-development-template.md` 不应因为过去常被用于新湖接入就原样保留；恰恰因为仍可能被打开，它的旧 Console 主体会持续误导新开发。

### 10.4 明确保留并延期

Ops Dataset Status Snapshot、正式 orchestrator、ClickHouse、正式 DuckDB/Parquet、现行历史处理、`lake_console/reports/**` 均保留。物理旧湖和本机 ignored 环境等代码清退完成后再分别审计和精确处理。

### 10.5 下一步

方案和 LLD 已无待拍板技术项。评审通过并收到实施授权后，严格按 LLD 的 M0 → M7 推进；本轮文档修改不构成代码删除、`dg` 执行、数据写入或物理目录清理授权。
