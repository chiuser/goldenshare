# 旧 Lake Console、Kopia 与旧湖迁移适配器清退专项方案 v2

状态：2026-09-05 M1 已提交 `3007cc0e` / M2A 已提交 `0cc84004` / M2B 已提交 `e8e2abf9` / M3 已提交 `1b0deb63` / M4 已提交 `68f97744` / M5 已提交 `3ed4c6ca` / M6 已提交 `63be03af` / M7 已提交 `3b94c48a` / M8 获批 111 项已精确删除，用户已要求按 10 文件白名单提交执行记录 / ignored 环境与清单外对象未处理

初审日期：2026-08-28；本次复审基线：2026-09-05，`dev-interface@10521877`

适用仓库：`/Users/congming/github/goldenshare`

> 本文替代本文件的 v1 结论。v1 错误地把 `OLD_LAKE_BOOTSTRAP` / `old_lake_root` 留在本次范围之外，也没有完成两份旧模板的内容价值审计。代码范围仍为 Kopia、旧 `lake_console/frontend + backend` 和旧湖/历史备份迁移适配器；现行 Dagster、ClickHouse、DuckDB/Parquet、Ops Dataset Status Snapshot 保留。按 2026-09-05 用户更新，物理数据不再一律延期：与本专项相关且审计证实不再使用的数据，纳入 M8 精确清退；仍在使用或证据不足的保留。reports 不整目录删除；ignored 依赖环境和本机配置仍另轮处理。

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

### 0.3 数据与保留边界（2026-09-05 更新）

1. 物理旧湖 `/Volumes/datasource/goldenshare-tushare-lake` 及本专项涉及的旧迁移/恢复遗留数据：按代码实际读写引用分类。保留主链使用的保留；只有待清退旧代码使用的，先退代码再删数据；没有代码使用的列可删。路径拼接、配置、glob、manifest/checkpoint 输入也算引用。取消数据完整性、日期范围、新湖承接和历史价值对账；不整根删除，不重新用旧湖驱动 DG。
2. 本机 ignored 依赖环境、构建产物和配置：本次不删除，Git 清退稳定后另轮逐路径处理；此处不是把所有 ignored 业务数据一律排除，数据仍按第 1、3 项用途审计。
3. `lake_console/reports/**`：不随旧 Console 整体删除。当前正式审计工具仍使用这个输出目录；没有代码读取的具体旧报告可列 M8 候选，历史文档提及不再构成保留数据的理由，删除时修正相应位置说明即可。
4. `ops.dataset_status_snapshot` 及其 ORM、service、CLI、任务完成副作用、freshness/date completeness 查询和页面消费者：全部保留。
5. `lake_console/orchestrator/**` 的正式 Dagster 主链、当前 ClickHouse、DuckDB、Parquet、正式 Lake 读写和无 Kopia 发布机制：全部保留。
6. 根目录现行运营后台 `frontend/**`、Wealth、QTF、`src/foundation/clients/local_lake/**`：全部保留。
7. 历史 Dagster event 中已经写入的旧湖/Kopia 字样：允许保留，不改写既有 event；86 份纯旧 Console
   文档不再留在当前工作树，必要结果摘要迁入现行总账后删除，全文只通过 Git 历史追溯。
8. 对旧湖路径和 Kopia 的禁止性规则、负向测试：保留并按新事实更新。
9. 现行 `suspend_full_day_ranges.csv` 及读取链当前保留只是防误删措施，不是长期设计认可。用户已要求
   记录后续治理 TODO：消除停牌修正规则的运行时文件隐性依赖。详见 LLD §16.11 `TODO-SUSPEND-001`；
   本轮仅登记，不改规则/数据，不自动扩充本专项实施范围，替代方案验收前不得先删该 CSV。

### 0.4 新增拍板结果

1. `stk_mins_raw_replace_from_prod` 的**业务能力保留并重构**：继续支持“prod DB 可信、正式 Raw
   单日五频错误”的离线恢复，但候选、审计、报告和 checkpoint 全部迁入正式 staging 根；删除正式
   根内 `_staging/_quarantine`、backup 的生成代码和假整体回滚设计，改为逐文件 fingerprint、checkpoint、验证和
   幂等续跑。
2. 原拟 `HISTORICALIZE` 的 86 份纯旧 Console 文档不再保留在当前工作树。对后续仍有价值的执行数量、
   修复结果和数据语义先压缩进现行 Dagster 总账/设计文档，清理全部现行引用后删除原文；Git 历史是
   全文追溯面，不创建新的 archive 目录或 tombstone 文件。
3. `main` 与 `dev-interface` 完全追平不再作为本专项开工门禁；实施以当前 `dev-interface` 的已记录 HEAD、
   CodeGraph 状态和精确工作区白名单为基线，不因分支进度差异扩大或缩小清退范围。
4. Raw `stk_mins` 恢复工具不新增自造排它锁。它继续是人工、非 active 的离线工具；并发安全收敛为
   “同日期只允许一个未完成 recovery run + 执行前进入明确维护窗口 + 确认没有同日期写任务”。

5. 物理数据以“代码使用则保留、仅旧代码使用则先退依赖、无代码使用则可删”为准；只有代码/配置读写范围未核清时才暂列待核。M8 与 M0–M7 分阶段验收。
6. Raw 恢复的 5 分钟改为耗时参考和人工排查提示，不再因超过这个时间自动拒绝；正确性和范围门禁不放宽。
7. 代码清退前集中审计代码入口与路径，按数据集目录/恢复 run 批量分类供 review；不再逐 Parquet 核行数、日期、内容或 SHA。代码退出后、实际删除前仅复核依赖和机械安全条件。
8. 任何代码、旧文档和物理数据删除，都必须先由用户确认具体删除清单；同意方案、允许审计或提交文档不等于授权删除。清单新增或范围变化必须重新确认，禁止自行删除。
9. 2026-09-05 用户确认 `/Volumes/datasource/backup/research/stk_mins_by_date_clean_next` 只是基础版本备份，
   不再做内容用途审计，并明确“确认，删除后，你继续推进吧”。仅此精确目录获准提前删除，不再等待 M0–M7
   或全量内容替代证明；执行前仍检查真实路径、符号链接、文件范围和占用。旧湖内另一处同名目录、正式湖、
   其他 backup 数据不在授权内。旧 migration 主体已在 M3 清退，其余适配器仍待 M4；不得恢复备份或入口。
   执行结果落入 LLD §16.9 和 M0 清单 §17；其他对象继续只读审计，删除仍需分别确认。
10. 用户随后明确“目前只要代码中没有直接引用的，都不需要了”，并确认按简化思路执行。该决定替代前轮
    因早期历史、旧证券差异、未知副本或人工取证价值而继续保留/对账的要求。数据删除仍须精确清单确认，
    不影响 M4 恢复工具本身的候选校验、写入安全及代码回归门禁。最新分类以 LLD §16.14 为准。

旧“不处理物理数据”口径来自用户此前“物理旧湖本次先不删”“其它物理旧湖、ignored 环境等清退后
再处理”的决定，曾落在本节、§1.4、§4.6、M8 和 §9；2026-09-05 的决定替代其中物理数据的延期口径，
没有把 ignored 依赖环境/本机配置自动变成数据删除对象。除 §0.4 第 9 项获单独批准的备份外，当前仍是审计和文档更新，不执行代码清退或其他数据删除。
具体物理对象的删除资格仍须由 LLD §16 的清单证明，不能把原则拍板写成所有对象已可删除。

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
| 86 份纯旧 Console 文档中的旧路径/source metadata | 摘要迁入现行总账后删除原文 | 防止旧设计继续被搜索和误用；全文仍可从 Git 历史追溯 |

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

1. 旧 Console 前后端及专属入口的 Git 跟踪文件和运行入口全部清零，不要求本机 ignored 目录消失。
2. 可执行代码和可生效配置中不再存在 Kopia 正向能力。
3. 可执行代码中不再存在旧湖/历史备份到正式湖的 bootstrap reader、参数、命令和 catalog 入口。
4. `OLD_LAKE_BOOTSTRAP`、`old_lake_root` 等正向运行契约清零；负向守卫和历史文字不要求字符串清零。
5. 混合迁移文件中的现行中性 helper 已迁到合适的当前模块，所有消费者改用新位置，不留兼容 wrapper 或 alias。
6. 两份旧模板的有效内容已吸收到正式文档，现行引用已切换，旧模板和旧 bootstrap migration 模板已删除。
7. 正式 Dagster、ClickHouse、正式 Lake Reader、Ops Snapshot 等保留主链通过回归。
8. M0–M7 不改物理数据、数据库或 Dagster instance；M8 只删除已完成用途审计的精确废弃数据，保留在用/未知对象，输出逐项结果；ignored 依赖环境和本机配置不动。

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
| files | 2,787 |
| nodes | 49,059 |
| edges | 124,757 |
| backend | node:sqlite / full WAL |

影响面查询至少覆盖：

1. `BootstrapDatasetSpec`。
2. `OLD_TUSHARE_LAKE_ROOT`。
3. `BootstrapSourceMethod`。
4. `IngestionSource`。
5. `plan_stk_mins_migration`。
6. `stock_identity_map_bootstrap_spec`。
7. `plan_stk_mins_raw_replace_from_prod` / `apply_stk_mins_raw_replace_from_prod` 及专属 CLI。
8. `StockMinsLakeReader`、`MajorIndexMinsLakeReader`、`StockNineTurnLakeReader`、
   `IndexNineTurnLakeReader` 到 Biz API/Wealth 页面的消费者。

CodeGraph 对 enum member 字符串和动态 CLI 分支覆盖有限，因此又用全仓文本搜索和逐文件阅读复核了入口、调用方、被调用方、测试、文档和 catalog。

### 2.3 审计边界

本轮是静态只读审计：没有运行 `dg`，没有加载或写入 Dagster instance，没有执行迁移、materialize、job、sensor、backfill、runless event、数据库写入或 Lake 写入。

### 2.4 文档遗漏复盘与防漏方法

上一版遗漏的不是代码依赖，而是文档候选发现方式不完整：当时主要从“86 份待删旧文档的入链引用”
向外查，因此能发现谁链接了旧文档；但没有再从“将被删除的代码符号、配置名、旧湖路径和恢复工具名”
反向扫描全部 tracked 文本文件。没有链接旧文档、却直接写着 `old_lake_bootstrap`、
`BootstrapDatasetSpec`、`lake_console/backend` 或旧恢复路径的现行文档因此漏入矩阵。

本轮改为三路独立发现、逐文件归类：

1. **删除目标反向引用**：逐个扫描 86 份待删文档、三个待删模板、旧 frontend/backend 路径的入链。
2. **运行符号与路径扫描**：扫描 `OLD_LAKE_BOOTSTRAP`、`old_lake_root`、`BootstrapDatasetSpec`、
   `old_lake_executor`、Kopia、旧物理湖路径、`lake_console/backend|frontend`、
   `stk_mins_raw_replace_from_prod` 及旧 staging/quarantine 口径。
3. **矩阵反向对账**：所有命中文件必须进入 LLD 第 9.4 节，或明确属于将整体删除的
   `lake_console/backend/**`、`lake_console/frontend/**`、专属入口/配置边界；不能仅凭“是负向禁令”
   就不登记。

矩阵经历 125 → 143 → M0 的 145 份；2026-09-05 按当前 HEAD 补齐 9 份至 154 份，随后从 reports
的具体文件反查补入两份正式指数历史设计，达到 156 份。M5 在 `5f834b02` 再补 9 份，当前为 165 份；
其中 6 份只验证保留、3 份纠正 staging 的历史/当前边界，均不增加删除目标。另将 3 份仍引用旧模板的保留项
改为仅切换链接；两个趋势通道文档的旧模板引用也已切换。实施 M0、M5 和 M7 都要重跑同一组扫描；只有
“未归类命中文件为 0、待删文档现行入链为 0、矩阵意外缺失/重复为 0”才允许继续（M5 已批准删除的 89 项除外）。这样不能承诺未来
新增文件永远不会出现，但可以保证当前 HEAD 上的新增命中不会被静默漏过。

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

### 3.6 Raw `stk_mins` 离线替换工具与 Catalog 最终重构口径

`stk_mins_raw_replace_from_prod` 不是旧湖迁移器，也不是 Kopia。它是 2026-07-27 分钟数据事故后增加的
**非 active、单交易日、五频整体替换**工具：当正式 Lake 已经存在某日 1/5/15/30/60 分钟 Raw 文件，
但这些文件被确认不完整或错误，而生产 PostgreSQL `raw_tushare.stk_mins` 仍保有可信完整副本时，
它从生产库重新导出五个候选文件并整体替换正式 Raw。

真实链路为：

```text
人工 CLI plan
  -> 只读核验 ops.task_run 的全市场成功任务
  -> 从正式 Lake 的 stock_basic 推导当日应有股票代码集合
  -> 聚合核验 prod raw_tushare.stk_mins 五频代码、行数、键和时间范围
  -> 冻结现有五个正式 Raw 文件 SHA-256
  -> 输出 /private/tmp plan + fingerprint

人工审阅后 CLI apply + --apply + plan report
  -> 重新生成同一 plan，拒绝 stale plan
  -> DuckDB 从 prod PostgreSQL 导出五个 staging Parquet
  -> 逐文件校验 schema、日期、频率、代码集合、行数、空键、重复键和 09:30-15:00
  -> 五个旧 Raw 先移入 quarantine
  -> 五个 staging 逐一 os.replace 到正式 Raw
  -> 中途失败则尝试把已移动的五个旧文件恢复
```

它不会注册 asset、job、sensor 或 check，不会被日常 Dagster 自动调用，也不会主动补 Dagster event。
正常 Raw job 只在替换成功后通过 `reuse_existing` 重新记录 materialization/check。仓库内正向调用方仅有
专属 CLI；其余引用是单元测试、静态门禁和 2026-07-27 的历史执行设计。新 BSE recovery 虽也使用
candidate/audit/promote/checkpoint，但只修复冻结的 BSE 代码/日期范围，不能替代“任意单日全市场五频
从 prod DB 整体恢复”。

当前日常 Raw job 也不能替代它：`source=prod_db` 只允许 `reuse_existing`，目标已存在时不会覆盖；
`merge_repair` 只允许 `source=tushare`，用于缺失代码合并，不是从 prod DB 重建并整体替换五频文件。
所以从能力角度看，这个 CLI 填补的是一个真实空档。用户已拍板保留该恢复能力，但现实现不得原样
进入清退后的正式代码基线。

当前实现有三个必须正视的问题：

1. staging 位于正式 Raw 树下的 `raw/tushare/stk_mins/_staging/**`，不在唯一允许的
   `/Volumes/datasource/data_lake_staging`。
2. 旧五频文件被移动到正式根下 `_quarantine/**` 并在成功后长期保留；这实质上是正式根内的
   运行时备份，与“正式根只允许 raw/silver/gold、不得用文件备份或快照做安全恢复”的现行规则冲突。
3. 五个 `os.replace()` 只保证单个文件替换原子，不能构成五文件事务。Python 捕获到异常时会尝试
   回滚，但进程被强杀、宿主机掉电或文件系统异常时回滚代码可能根本不会执行，正式 Raw 可能短暂或
   持久处于“部分频率已新、部分频率仍旧”的混合状态；因此不能把现实现描述为真正的五频原子替换。

最终处理已经确定：

| 能力 | 代码处理 | Catalog 处理 |
|---|---|---|
| 单日全市场五频 prod-DB 恢复 | **保留能力、重构实现**：报告/candidate/checkpoint 全迁 `DEFAULT_LAKE_STAGING_ROOT`；按 candidate → audit → checkpointed promote 重写；每个频率冻结 old/new fingerprint 并记录 `pending/promoted/verified`；删除生成正式根 quarantine/backup 的代码和整体回滚设计，物理遗留按 M8 审计 | Raw `stk_mins` ingestion 保留当前 `TUSHARE_API`、`PROD_DB_READONLY`；五个 entry 固定为 `bootstrap_sources=(PROD_DB_READONLY,)` |

除 Raw `stk_mins` 这一项外，其余 12 个受影响 catalog entry 的目标已经确定：

| 资产 | 数量 | 清退后来源口径 |
|---|---:|---|
| silver `adj_factor` | 1 | `bootstrap_sources=(DERIVED_FROM_ASSETS,)` |
| silver `stk_mins` | 5 | `bootstrap_sources=(DERIVED_FROM_ASSETS,)` |
| gold `stk_mins_qfq` | 5 | 只保留 `DERIVED_FROM_ASSETS` |
| silver `index_daily` | 1 | `bootstrap_sources=(DERIVED_FROM_ASSETS,)` |

总计 17 个 catalog entry 的目标值已经全部确定。禁止为了让 enum 消失而机械替换 catalog，也禁止在
恢复工具尚未完成 staging/checkpoint 重构和验收时提前把不合规实现描述成可用正式入口。

#### 3.6.1 并发保护为什么需要、做到什么程度

这个工具会替换同一交易日的五个正式 Raw 文件。唯一需要防的并发问题是：人工恢复尚未完成时，
另一个日常、repair、history 或第二个 recovery 又写同一日期，导致 checkpoint 看到的文件指纹和现场
不一致。它不需要常驻锁服务，也不需要为整个 Dagster 新增一套并发系统。

上一版 LLD 提出的 run-root 排它锁只能挡住第二个 recovery CLI，挡不住 Dagster 或其它 repair writer，
并且与仓库“禁止自造锁文件”的规则冲突，属于复杂但保护不完整的设计，本轮删除。最终采用：

1. 同一日期发现未完成 checkpoint 时，只允许用原 `recovery_run_id` 续跑，禁止创建第二个 run。
2. `apply` 前进入人工维护窗口，暂停或禁止可能写同日期的自动/手动入口，并确认没有 running/queued run。
3. 五频全部 `verified` 前不恢复相关入口、不补 materialization/check、不宣称恢复完成。

#### 3.6.2 M4 性能门禁是什么

M4 的性能门禁只约束上述单日五频 Raw 恢复，不涉及 Ops Dataset Status Snapshot，也不约束普通页面查询。
原因是该工具要从生产 PostgreSQL 读取约 180 万分钟行、生成并审计五个 Parquet 后才替换正式文件；如果
实现意外变成逐股票查询、Python 明细循环或无界全表扫描，可能长时间占用生产库、内存和 staging 磁盘。

按低频、人工监督场景采用简单约束：一个交易日、五个频率、五个候选文件；集合 SQL/流式导出，不并发
增加生产库压力。2026-07-27 的 1,776,093 行、约 42.5 MiB、109.973 秒仅是历史参考，不是性能 SLA。
超过 5 分钟提示人工检查，不自动失败、不废弃已校验候选，也不引入新的超时配置/后台计时服务。
范围失控、数据校验失败、目标漂移、空间不足或跨文件系统仍必须停止；按 LLD §6.4.4 记录阶段、实际
耗时、行数/字节数和磁盘空间。取消或中断按 checkpoint 处理，不能省略校验来追求速度。

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

### 3.12 `src/foundation/clients/local_lake/**` 是当前 Wealth 读取链，不是旧 Console

这里的 `local_lake` 表示“本机 Web 进程直接只读正式 Lake Parquet”，不是
`lake_console/backend` 管理的旧湖。当前代码链已经逐项确认：

```text
APP_ENV=dev|local
+ WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED=true
+ GOLDENSHARE_LAKE_ROOT=/Volumes/datasource/data_lake
  -> src/app/api/v1/router.py 按 capability 挂载分钟 routers
  -> src/biz/api/wealth/market/{stock,index}_detail_*minutes*.py
  -> Biz query service
  -> src/foundation/clients/local_lake/*_reader.py
  -> DuckDB 只读正式 Gold Parquet
  -> Wealth 股票详情页 / 指数详情页
```

当前实际数据集和页面为：

| Reader | 正式 Lake 数据集 | API | 页面消费者 |
|---|---|---|---|
| `stock_mins_reader.py` | `gold/quote/stk_mins_qfq`、`gold/indicator/stk_mins_qfq_macd_kdj` | `/api/v1/wealth/market/stock-detail/minutes`、`minute-indicators` | `/wealth/market/stock/{tsCode}` 分钟 K 线与指标 |
| `stock_nine_turn_reader.py` | `gold/quote/stk_mins_qfq`、`gold/indicator/stk_mins_qfq_nineturn` | `/api/v1/wealth/market/stock-detail/minute-nine-turn` | 股票详情分钟九转层 |
| `major_index_mins_reader.py` | `gold/quote/major_index_mins`、`gold/indicator/major_index_mins_technical` | `/api/v1/wealth/market/index-detail/minutes`、`minute-indicators` | `/wealth/market/index/{tsCode}` 分钟 K 线与指标 |
| `index_nine_turn_reader.py` | `gold/quote/major_index_mins`、`gold/indicator/major_index_mins_nineturn` | `/api/v1/wealth/market/index-detail/minute-nine-turn` | 指数详情分钟九转层 |

这些路由默认不在生产挂载：resolver 只允许 `APP_ENV=dev|local` 且显式开关开启。指数分钟 capability、
股票九转和指数九转还强制 Lake 根精确等于 `/Volumes/datasource/data_lake`；普通股票分钟
`StockMinsLakeReader` 当前只校验配置根可读和路径不越界，**没有**同等的正式根精确门禁。因此实施
回归必须使用正式根验证，同时不能在本轮顺带读取或修改 ignored 配置；该不一致作为后续配置治理风险
记录，不能反过来成为删除当前 Reader 的理由。因此本专项保护它们的原因不是“旧 Console
也有 DuckDB”，而是它们是当前 Wealth 本地分钟产品的真实消费者。删除旧 frontend/backend 时不得
顺手删除 `local-lake` optional dependency、capability resolver、Biz API/query service、Wealth API client
或页面周期能力。

### 3.13 86 份旧文档的价值复核与删除结论

逐文件阅读标题、状态、实现链接、结果段并做全仓入链引用扫描后，86 份文件的结论如下：

| 分组 | 数量 | 是否保留全文 | 处理依据 |
|---|---:|---|---|
| 旧 Console 架构、页面、API、CLI、模型、Kopia、旧 benchmark | 25 | 否 | 产品和实现整体删除；当前 Dagster/Wealth 不依赖这些合同，旧 benchmark 也不能约束当前代码 |
| 旧 Console 数据集接入说明 | 5 | 否 | 目标目录、Catalog、Planner、CLI 和模板全部退役；现行生产/Dagster 文档已独立存在 |
| 旧 Console prod-raw/core-db 导出方案 | 42 | 否 | 只描述待删导出服务、旧目录和旧页面；当前来源合同由 DatasetDefinition、source docs、正式 Dagster LLD 和代码承接 |
| `stk_mins` clean/repair/indicator 历史方案 | 14 | 原文否、最小结果摘要保留 | 旧命令/路径/备份方案会误导；但部分修复数字、baseline provenance、停牌/身份映射语义对理解正式新湖来源仍有价值 |

因此 86 份文件全部从当前工作树删除。14 份 `stk_mins` 文档只迁以下不可替代结果，不迁旧实现步骤：

1. `clean_next` 最终 schema、分区/行数和全量复审结论。
2. 历史 3,735 个严重低行数分区恢复摘要。
3. 2022 北交所 30m 专项和 2024-10-30 多频污染专项的影响范围、行数变化及修复后
   `issue_count=0`。
4. 分钟线与日线代码集合不能 strict equality，差异需按停牌和身份映射解释的结论。
5. 正式新湖 bootstrap 已经在现行 Dagster 设计中采用的 source/path/count/check 结果。

摘要统一落入 `lake_console/docs/design/dagster-bootstrap-legacy-links.md` 或已经自足承载同一事实的现行
`stk_mins` Dagster 设计。删除前必须清理 `docs/README.md`、onboarding、risk register、research 方案和
正式 Dagster 文档中的全部入链引用。Git 历史保留完整原文，因此不新建 `archive/`、不复制 86 份文件、
不留 tombstone；后续物理旧湖审计必须重新读取物理数据，不能把这些点时文档当作当前数据事实。

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
3. 86 份纯旧 Console 文档会在必要结果摘要迁移、现行引用清零后删除，不保留不可点击历史路径、
   archive 副本或 tombstone；完整原文按 Git 历史追溯。
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

`stk_mins_raw_replace_from_prod` 按第 3.6 节进入“保留能力、必须重构”的修改清单；现模块和 CLI 不得
原样视为保留完成。

### 4.6 F 类：物理数据纳入 M8，ignored 环境仍另轮处理

物理旧湖（逐项审计对象，不是整目录删除白名单）：

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

旧湖、旧迁移源和恢复遗留数据按 LLD §16.1/16.14 的代码引用标准分类，不再做内容替代审计。物理删除在 M0–M7 验收后
作为 M8 独立执行；仅旧代码消费的数据先解除依赖。唯一提前执行的已批准备份例外见 §0.4 第 9 项。
上列 ignored 依赖环境和配置仍不在 M8 删除范围，
后续单独精确处理。任何阶段都不能使用共享上层目录递归删除。

**当前批量结论（替代下面历史审计的待办/保留理由）**：54 个旧 Raw 目录及旧湖 manifest/research/
derived/_tmp/_recovery 仅由旧 Console/旧适配器使用，列 `DELETE_AFTER_DEPENDENCY`；不再逐个对账。
三份旧报告、两个已完成的 2026-07-27 Raw/Silver 遗留 run 列 `DELETE_READY` 供确认，不清其共享父目录。
正式数据、停牌 CSV、身份映射 seed、reports 输出目录及 BSE/WMT 当前恢复输入保留。具体代码证据、
精确路径与审批边界见 LLD §16.14、M0 §21；没有执行删除。

**以下仅保留此前已发生的审计记录，不再作为当前待办或删除门禁。** 早期历史、内容差异、人工取证
可能性不再要求逐项核清；不再以“只完成 5/54 内容初核”阻塞旧湖分组分类。

2026-09-05 首批物理审计已落入 LLD §16.4–16.8 与 M0 清单 §16：旧湖 297730 个文件、约 475 GiB。
首批记录中的 clean_next backup 经用户确认无需再审内容，已于 08:21 +08:00 精确删除：21047 个文件、
67676449533 逻辑字节（63.03 GiB），不承诺实际磁盘释放量或可恢复性；旧湖同名目录和正式分钟目录保留。
执行证据见 LLD §16.9、M0 清单 §17，不再列为待内容审计项。两个 2026-07-27 Raw/Silver 恢复 run 的
旧五频分别匹配 manifest 的 before、正式五频分别匹配 staged；旧与正式文件本身五频均不同。
仅列为处理依赖和证据后可提请删除的候选，正式文件与 Silver 恢复工具保留。

reports 已逐文件区分：指数 CSV 是 948 代码的历史候选集，当前 Dagster 集合为其中 820 个，运行链不读
CSV；namechange CSV 只是零未决摘要。stock_daily CSV 的 35 项已完成报告用途分类：31 项停牌区间
与当前正式修正规则相同，3 项未标停牌的缺口已有 Raw/Silver 数据，另 1 项 920188.BJ 的停牌标注与当前
两天实际行情不符。三份均列依赖处理后、待用户确认的报告删除候选；保留现行修正规则和 reports 输出目录，
不宣称全历史数据质量已验收，详见 LLD §16.10。当前 BSE → WMT → Prod 发布仍使用 staging 恢复
证据/manifest/checkpoint；部分计划记录尚未完整，不能清理。staging 盘点达到预算后停止，未遍历部分
明确待核。除已确认的单项 backup 外，没有其他删除；业务代码未改，详细证据与剩余工作以 LLD 为准。

后续逐数据集初核见 LLD §16.12–16.13、M0 清单 §20：已核 5/54 个旧 Raw 及身份映射，不是整湖结案。
旧日线有 5636 个 2014 年以前分区、旧停牌有 3377 个同期早期分区，在所比正式湖没有对应文件且样本
非空；旧股票基础信息独有退市代码 `TS0018.SH`，旧身份映射另有 `706055.SH`，用途/差异未核清前保留。
adj_factor 路径已全覆盖但只做 5 分区内容取样，仍待核；只有旧 trade_cal 的精确 Raw Parquet 与正式
文件整表 13162 行等价，列为解除旧消费者后、待具体确认的候选，不包含旧 manifest 日历和父目录。
两个分钟恢复 run 又核实 12 个遗留文件、10 个正式文件及 7 条成功的历史任务记录；事故文档证据承接、
人工恢复用途确认和执行前复核仍未完成，没有新 `DELETE_READY`。本轮没有任何删除、业务代码或数据写入。

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
3. `lake_console/docs/design/dagster-bootstrap-legacy-links.md`：保留为已结束迁移的历史总账，写明执行代码已清退、物理旧湖按 M8 逐项审计清退、不可再作为运行入口。
4. `lake_console/docs/architecture/dagster-data-system-architecture.html`：删除 `KopiaResource` 正向建议。
5. `lake_console/docs/design/dagster-new-lake-asset-catalog-design.md` 和 run-contract 治理文档：移除旧迁移 source 的现行契约表述。
6. `dagster-phase-2-design.html` 等历史设计：保留历史事实并加退役边界，不把历史方案重写成从未发生。

### 5.3 旧 Console 文档与历史证据

86 份纯旧 Console 文档按已拍板口径从当前工作树删除，不继续以“历史文档”名义整篇保留。仍有当前
生产事实的混合文档只修旧段落和时态；只包含禁止 Kopia/旧湖的现行负向门禁保留不改；必要执行数字和
数据语义先压缩进唯一现行迁移总账或当前 Dagster 设计。

每个命中文件都必须按 LLD 第 9.4 节归为 `DELETE_AFTER_MIGRATION`、`MODIFY_CURRENT`、
`MODIFY_MIXED`、`DELETE_LEGACY_DOC` 或 `KEEP_CURRENT_VERIFY`。位于旧 frontend/backend 整体删除边界
内的文档、AGENTS 和本地 skills 由 263 文件精确清单覆盖，不重复进入外部文档矩阵。禁止临场批量替换，
也禁止用“只是历史文字”跳过归类。

---

## 6. 实施顺序

### M0：删除前复核和精确白名单

1. 同步并确认 CodeGraph 状态。
2. 重跑旧 backend import、旧 API、Kopia、旧 migration symbol、old-lake 参数和模板引用扫描。
3. 对混合模块重新列出正向消费者。
4. 只读检查本机是否仍有旧 Console 进程；发现遗留进程只说明运行状态，不扩大代码保留范围。
5. 形成 tracked 文件删除白名单和修改白名单；不得使用目录上层模糊删除。
6. 重跑第 2.4 节三路文档扫描，确认未归类命中文件、矩阵重复/不存在路径和待删文档现行入链均为 0。
7. 先完成 LLD §16 的用途只读审计和分类清单，再进入代码清退实施；未核清对象显式列为待审，不以用户拍板代替事实核验。任何删除前另行提交具体清单请用户确认。

准入：依赖图与本文第 3、4 节一致；任何新增消费者都必须先补回方案。

### M1：先迁出混合模块中的现行能力

1. 迁移 `stk_mins_migration.py` 中的中性 helper。
2. 更新全部现行消费者和 helper 单元测试。
3. 验证正式 history/event/repair 路径不再依赖旧 migration helper。

本阶段验收：Silver history 与四个当前事件模块对旧 migration helper 的 import 为 0。旧混合 CLI
仍按原文件运行，入口迁移属于 M2；不能把“旧 migration 所有当前消费者为 0”的 M3 删除前提提前算作 M1 结果。

2026-09-05 实施记录：基线 `dev-interface@650c549d`，当前 helper 已迁出；新增一个计数模块、修改五个
保留模块和三份测试文件（其中两份为新增），不改旧 CLI/migration，不删除文件。155 项隔离/静态测试
及 450 个子断言通过，包含 33 项新增 helper/消费者测试；4 个迁出函数及 5 个保留模块的 AST 等价核验通过。
Ruff 与文档检查结果见 LLD M1 记录；未运行正式 Dagster、Lake、数据库、部署或完整写湖集成测试。
后续提交：按用户要求已提交为 `3007cc0e`，未推送。

### M2A：CLI 等价迁移

1. 区分原 28 个命令：冻结 21 个保留命令的 parser/handler 合同；7 个旧命令只做新入口拒绝测试，不迁移旧能力。
2. 为 21 个当前命令记录命令名、参数/default/required/choices、handler、目标函数、参数映射、输出 key、
   side-effect 类型和确认门禁。
3. 新增四个职责 CLI，把 21 个命令按 LLD 映射原样迁入；此阶段禁止改变 selector、默认值、输出或
   确认语义。
4. 用 fake dependency 对旧、新入口做同输入双跑，比较规范化 Namespace、目标调用和原始输出类型/内容；不执行
   Lake、Dagster 或数据库写入。
5. 21 个等价合同全绿后，删除原混合 dispatcher；7 个旧命令不迁移、不留 alias。

准入：21 个当前命令行为等价；7 个旧命令在新入口均不存在；旧 dispatcher 当前消费者为 0。

2026-09-05 实施记录：基于 `3007cc0e` 先冻结旧入口，再新增 shared contract 和四个职责 CLI。
21 个命令、246 组输入双跑全等，21 段 handler 结构等价；四份现行 CLI 测试与 static gate 已切换，
删除了唯一文件 `stk_mins_migration_cli.py`，不留 alias。永久回归改为“新入口对固定旧行为 fixture”，
旧文件只通过 Git 历史追溯。`audit-silver-final` 保留真实 dataclass 打印，未按旧文档的 dictionary 概括改错。

另有 5 个原 CLI 集成测试在临时 Lake、ephemeral instance、临时 DuckDB spill 下通过，正式环境未参与。
完整文件表、测试结果、限制及新入口见 LLD §11 M2A。同步 canonical 现行文档、架构快照与三份专项记录；
未改变边界/依赖矩阵、156 份文档矩阵和 263 个旧产品文件清单。用户要求提交 M2A，按 18 文件白名单归档为 `0cc84004`，未推送，当时 M2B 未开始；
旧 migration 主体、旧 Console、物理数据、ignored 环境均未动。

### M2B：CLI 安全门禁收紧

只在 M2A 等价基线通过后，单独实施并测试两项已批准的现行安全修正：

1. Silver generate 删除 `--all`、保留显式 keys 和 `--all-from-raw-files`；register/report 只允许 Silver 文件或显式 keys，不再接受 `--all` 或 `--all-from-raw-files`。禁止利用 argparse 缩写继续传入 `--all`；其它 option 缩写不变。
2. MACD/KDJ baseline event 的日期显式必填且相同，显式 keys 不能超出当天，planner 只能选出该天一个 partition；`--dry-run` 不能绕过。CLI 在实例访问前校验，公开 report 入口复用校验，并在其内部 baseline planner 返回后、文件审计/事件写入前检查最终 plan；不增加预规划。原文件审计还会调用 history planner，底层仍共两次，未增加扫描。

准入：等价迁移失败和安全加固失败可分别定位；不得把安全变更混入“迁移等价”验收。

2026-09-05 已完成本阶段代码和隔离验证，按用户要求提交 `e8e2abf9`，未推送。原 M2A fixture 的 21 命令、246 案例原文保留并加哈希断言，仅新增四个命令的 `approved_delta`。新增 98 项正反例；合并回归 315 passed、696 subtests passed，另有 5 项原 CLI 隔离集成测试通过。完整逐文件落点、命令、范围和限制见 LLD §11 M2B。该阶段没有删文件、改数据、接入正式 Dagster 或开始 M3。

### M3：删除旧 migration 主体

1. 删除只剩旧 raw/identity-map migration、event report、audit 和 metadata 的主体。
2. 删除纯旧测试，运行 Silver/QFQ/derived/MACD-KDJ 定向回归。

准入：`stk_mins_migration.py` 和原 CLI 不留 wrapper、re-export 或兼容 alias。

2026-09-05 已按用户“进入 M3”实施，用户随后要求提交；本次仅按 M3 的 10 文件白名单归档，不推送。重新逐行核验 1,328 行旧模块及 425 行旧测试；删除前全仓 Python 导入只有旧测试一处，当前 helper 已迁出。注意旧文件当时仍留有四个已迁 helper 的旧副本，但已无现行消费者，不是再次删除当前能力。

本轮精确删除 `stk_mins_migration.py`、`tests/test_stk_mins_migration.py` 两份文件。旧测试中的零 low、全零报价样本先转为现行 Raw value-domain check 测试，并补负价格/空值反例；其余 8 项只验证已退役的旧迁移 producer。新增模块不可发现和全 orchestrator 无旧 import 门禁，不留兼容代码。现行 Raw、identity-map、Silver/QFQ/derived/MACD-KDJ 运行文件全部保持基线原文。

删除前五组现行历史治理回归 70 passed；删除后合同/静态/新样本 318 passed、696 subtests passed，另有五组完整历史治理 + Raw 合同 + 当前 identity-map 链 112 passed，均为隔离测试。逐文件与旧测试处置、执行命令、限制见 LLD §11 M3。旧湖 generic specs/executor、`OLD_LAKE_BOOTSTRAP`、恢复工具及其 metadata 仍归 M4，不因模块删除顺带清理。

### M4：重构 Raw 恢复工具并删除 generic old-lake adapter

2026-09-05 用户已明确：删除 AGENTS 中一刀切的 Raw/Silver 字段继承门禁；Raw → Silver 的清洗与标准化可以形成不同字段集合，不能仅凭差集认定漏字段。当前 `vwap` 在 Raw 保留、在 Silver 排除，是专项设计、代码与测试一致的既有契约，本轮不处理，不列为待修复事项，也不另设字段治理任务。撤回此前因此暂停 M4 的判断；M4 保持现有字段及日常处理链路不变，仅按下列步骤重构恢复工具和清退旧适配器。规则与口径纠正已提交 `d2d177bb`；随后完成本阶段代码与隔离回归，实际对账见 LLD §11 M4 实施结果。正式恢复、部署及物理清理未执行。

1. 先把 `stk_mins_raw_replace_from_prod` 的 report/candidate/checkpoint 迁到正式 staging 根，完成逐文件
   fingerprint、`pending/promoted/verified` checkpoint、中断判定、幂等续跑和五频最终核验。
2. 删除该工具生成正式根 `_staging/_quarantine`、backup 的代码和整体回滚分支；不在 M4 清物理目录。既有数据按 M8 清单处理；恢复工具新测试全绿后才进入旧适配器删除。
3. 删除旧 bootstrap dataset specs、executor、旧 enum members、exports、CLI 分支和参数。
4. 删除七个旧 SQL templates。
5. 逐资产修正 17 个 catalog source/bootstrap 声明；Raw `stk_mins` 五项固定保留
   `bootstrap_sources=(PROD_DB_READONLY,)`。
6. 删除一次性旧 event 模块和专属测试。
7. 删除旧 producer 后，确认历史 event 无需数据迁移。
8. 保留并补强旧根拒绝测试。
9. 恢复工具不新增 lock/pid 文件；按第 3.6.1 节用未完成 checkpoint 唯一性和人工维护窗口防止同日期并发。
10. 按第 3.6.2 节落实单日五频、受控资源和耗时记录；5 分钟只提示，正确性或资源安全失败必须停在正式 promote 之前。续跑必须覆盖 replace 后 checkpoint 未落盘及部分完成后候选丢失两个场景。

M4 实施结果（2026-09-05）：

- 恢复能力保留；证据统一放到正式 staging 的日期/UUID 目录。五频候选全部审计后逐文件替换，失败保留现场，同 run 按物理指纹续跑；删除原备份/整体回滚流程，不提供旧路径或旧报告兼容。
- 精确删除 LLD §6.1 对应的 13 个旧运行模块和 4 份专属测试，移除 7 个旧 SQL 常量、两处旧 enum 成员和 package exports。当前 Raw/adj-factor/Silver/QFQ/history 能力未删除。
- 全部 159 个 catalog entry 保留；只有批准的 17 项来源声明改变。结构对比证明字段名、顺序、类型、日常计算与生产只读 source SQL 不变，现行 21 命令 fixture 回归通过。
- 最终联合隔离回归 439 项测试、750 个参数化子例通过；新实现相关 10 文件完整 Ruff 通过，全部修改 Python 文件相较 `d2d177bb` 无新增 Ruff 问题。4 个既有文件仍有 12 项历史 lint 问题，未借清退改动现行业务逻辑。文档与边界复核见 LLD。
- 用户已要求提交 M4；本次只按 35 文件白名单归档代码、测试及四份同步文档，不推送，不纳入并行任务的 Wealth 文档。未运行真实恢复、正式 Dagster/数据库/Lake 操作或 M5–M8；实际 apply 仍须单独确认日期和人工维护窗口。

### M5：模板迁移、证据摘要收敛与旧文档删除

1. 把两份旧模板的有效增量先写入正式 Dagster onboarding 模板或性能治理文档。
2. 更新现行 onboarding 和 S0 索引引用。
3. 把旧 `stk_mins clean_next` 重建、两次专项修复、代码集合差异和正式新湖 bootstrap 所需的最小结果
   摘要迁入 `dagster-bootstrap-legacy-links.md` 或已经承载同一事实的现行 Dagster 设计；不复制旧命令。
4. 更新所有 current/mixed 文档引用，确保不再依赖待删旧文档。
5. 按 LLD 逐文件矩阵删除 86 份纯旧 Console 文档；不建立 archive 目录或 tombstone。
6. 删除两份旧模板和 `dagster-bootstrap-migration-template.html`。

准入：新数据集接入不依赖待删除模板；86 份删除矩阵无遗漏；必要历史结果已在单一现行总账中有摘要；
现行文档和索引对 86 份文件的正向链接为 0；尚未删除的旧 Console 代码在此阶段仍按“待删”描述，
不能提前把规则写成“已删除”。

M5 实施结果（2026-09-05，实施基线 `dev-interface@5f834b02`，随本次提交归档）：

- 先迁移有效检查项：正式接入模板 7A/14 承接源契约、字段、预算、候选与续跑；性能治理 §6.4 承接 prod 只读、流式读取和对账。未照搬旧模板的统一 DATE、Raw 字段全部继承到 Silver、只准读取 raw_tushare 等不适用口径。
- 初始化与旧分钟修复的必要结果收敛到 `dagster-bootstrap-legacy-links.md`；明确点时数字、未解释差异与现行契约，旧命令不迁移。86 份旧方案和 3 份旧模板已精确删除，可从 Git 历史恢复。
- 修改 46 份文档/规则/skill（含本专项三份记录）；全矩阵 165 份，25 份保留项字节不变；3 份原保留项只有模板链接变化。涨跌停待开发方案撤回旧湖来源与预算，但保留字段、业务键、日常来源和事件补录安全设计；全历史新来源需该数据集开工前另审计，不冒充已验证。
- 89 项删除白名单、全仓引用/候选集合、链接、HTML 结构与文档完整性检查通过。263 个旧产品文件、正式 orchestrator 运行代码/测试、Foundation Lake Reader、前端、reports 与正式 bin 不变。未操作物理数据、ignored 环境、正式 DG/数据库或部署。
- 按文档治理 skill 区分现行、混合和纯旧内容；CodeGraph 配合当前实现核验 Raw 恢复 → 只读资源/源 adapter → catalog，不用关键词判定业务删除。依赖方向和矩阵无变化。并行板块分析代码/测试不属于本轮，未触碰；具体硬口径对账、验证边界及 M6 延后项见 LLD §11 M5。

### M6：原子删除旧 Console/Kopia并同步当前规则

1. 精确删除第 4.1 节旧产品对象，frontend、backend、tests、入口和示例配置同轮完成。
2. 同一原子阶段更新根/lake_console/orchestrator AGENTS、CODING_STANDARDS、skills、README、当前架构
   文档和 CodeGraph snapshot 为“代码已清退、禁止恢复”的真实事实。
3. 立即反查 `lake_console/orchestrator/**`、`lake_console/docs/**`、`lake_console/reports/**`、两个 ClickHouse
   bin、Wealth `local_lake` 读取链仍存在。

M6 实施结果（2026-09-05，基线 `dev-interface@3ed4c6ca`，已提交 `63be03af`）：

- 精确删除 263 个 Git 文件：backend 181、frontend 65、旧根测试 14、旧 CLI/联合启动/示例配置各 1。
  前后端和外围同轮处理，无 wrapper、alias 或空壳；源码可以通过 Git 恢复，本轮没有删除物理数据。
- 正式运行源码、21 CLI fixture、Foundation/Biz/Ops、主前端、Wealth 源码、reports、两项 ClickHouse 工具
  与根 optional dependency 共 2,140 个保护文件内容不变。六类 Reader 共 12 文件全部保留。
- 静态测试只去掉旧 backend 扫描；新增 13 项清退护栏防止源码、导入、Kopia 配置/入口回流，
  同时允许历史文字和 ignored 环境继续存在。11,692 个旧 Console ignored 文件元数据未变。
- 更新规则、skills、当前索引/架构和混合文档的旧段落；165 份文档矩阵保持不变，25 KEEP 文档字节一致。
  CODING_STANDARDS 已在 M4 校准，本轮仅复核，不重复改动。
- 当前后端 140 项回归和最终 13 项清退护栏通过；编排/CLI/Raw 恢复/ClickHouse/catalog
  304 项与 268 子例通过；Wealth 60 项、运营后台 37 项通过。两前端类型检查、构建及规则检查、
  Python 静态检查、编译、文档和删除/保留对账通过。
- 未使用 Kopia、未运行正式 DG/数据库/源请求、未停启服务、未删除旧湖或本机环境；
  UI 为现行页面 mock 回归，不宣称已完成部署 smoke。逐文件落点、原有警告与完整证据见 LLD §11 M6。
- M6 已按 292 文件白名单提交 `63be03af`，未推送。用户授权进入 M7，结果见下一节，不进入 M8。

### M7：全量回归验收

执行第 7 节的静态、单元、definitions、文档和差异门禁。任何保留主链失败都必须修复真实依赖，禁止恢复兼容 wrapper、空 module、旧 enum 或旧 CLI alias。

2026-09-05 首轮结果（基线 `dev-interface@63be03af`，以下为当时未通过的历史记录；当前收口结果见下文）：

- orchestrator 全量隔离测试：3,010 通过、3 失败，另有 1,137 个参数化子例通过。两项九转测试因整个测试进程累计内存超过 1 GiB 而失败；独立进程复跑该文件 18 项全部通过，未放宽正式内存门禁。另一项 DuckDB 测试断言正式 spill 目录，与本轮禁止写移动盘、强制临时目录的隔离方式冲突，仍待修正测试本身。
- 根架构及 Reader/API/snapshot 回归：242 通过、1 失败。失败是既有扫描把当前取消函数 `_raise_if_execution_canceled` 当成旧执行模型；代码及扫描均非本专项引入。另补 Ops snapshot 查询、CLI、worker、API 40 项全部通过。不得通过删除当前取消能力来消除误报。
- 根 frontend 全量 149 项、Wealth 定向 60 项及两边 typecheck/build 通过；不是线上页面 smoke。格式整理后，CLI/适配器/相关合同 184 项及 246 子例、根清退护栏 13 项再次通过。
- 删除/保留边界、21 命令冻结合同、165 份文档矩阵、12 份 HTML、文档完整性与编排致命静态检查通过；三个专项控制文档显式单列校验，补正 LLD 中 3 处已删源码链接为 Git 历史位置。M7 仅整理 5 份专项 Python 的格式及 1 份专项测试的导入顺序，逻辑/契约不变，未顺手修复两处既有测试。
- `dg check defs` / `dg list defs` 未执行，等待单独授权；完整命令、目录和影响边界见 LLD §11 M7。M7 不能标为全绿，也不能据此进入 M8。

原始失败、依据、当时待处理方案与证据位置详见 LLD §11 M7 和 M0 清单 §29；首轮结束时新增记录/格式整理尚未提交。

2026-09-05 用户同意修正后的当前结果：

1. 两处只改测试：DuckDB 连接委托/成功与异常清理/工厂失败 6 项通过，临时目录真实连接和默认配置合同保留；旧模型扫描 64 项通过，其中新增 23 个正反例，24 个原禁止项完整保留，仅取消事件名改为完整名称匹配。业务取消函数、正式 DuckDB 配置和九转内存门禁字节不变。
2. 全量编排测试按两组独立进程运行：2,997 + 18 = **3,015 项全部通过**，另有 1,137 子例通过。两组 node ID 并集等于全量收集集合，遗漏、重复、失败、错误、跳过均为 0。根架构/Reader/API/Ops snapshot 联合回归 **306 项全部通过**。
3. 已按批准命令、cwd 与正式 `DAGSTER_HOME` 完成 `dg check defs` / `dg list defs --json`，均退出 0；159 assets、364 checks、75 jobs、88 sensors、8 resources、1 schedule。资产身份与当前 catalog 全等，无重复或旧退役定义引用。没有触发业务任务、物化、分区注册或补事件。
4. 删除/保留范围、文档与代码差异复核通过。前端沿用首轮 149/60 项及构建结果，本续轮未改前端源码或重做线上 smoke。CodeGraph 覆盖已核，未引入新边界依赖。
5. M7 技术验收通过，已按 11 文件白名单提交 `3b94c48a`（3 文档、6 份首轮格式整理、2 份已批准测试修正），未推送。该提交未清理物理数据或进入 M8，不等同于生产部署；之后的 M8 独立批准和执行结果见下一节。

### M8：无用物理数据精确清退（纳入专项，独立验收）

1. 复核 LLD §16.14 代码引用清单；只核当前/旧代码入口、配置及动态路径，不再查内容、日期、完整性或副本承接。
2. 按精确数据集目录、恢复 run 目录或报告文件分类；目录自身可作为批准单位，但正式/旧湖根、共享父目录不作为递归删除目标。
3. M0–M7 验收后取得用户对具体清单的确认。执行前只做引用复核及 realpath、目录范围、符号链接、跨挂载和占用检查；不做全量内容哈希或业务查询。只删获批对象，新增目标重新确认。单项已删除 backup 例外仍见 §0.4 第 9 项。
4. 记录实际删除结果与恢复能力；历史引用更新为当时位置/已删除状态，不再为证明数据无用迁移大份证据。复核保留目录和代码未被触碰。

M8 不与代码提交混做，不修改业务数据库或 Dagster 历史，不清 ignored 依赖环境/本机配置，也不是全盘
数据清理。清单外对象不能自动进入删除执行。非 Git 物理删除不能用 Git revert 恢复，更不能以本阶段为由
启用 Kopia 或生成新的数据备份。

2026-09-05 M8 本批执行结果（基线 `dev-interface@3b94c48a`）：

- 用户 review §16.14 后明确确认 106 个旧湖对象、D01–D05，以及必须保留的范围。111 个对象全部删除，未增加目标。
- 合计 297,740 个普通文件、509,841,740,142 逻辑字节（约 510 GB），不是实测释放磁盘空间。108 个非 Git 对象删除约 56.5 秒；三份报告通过精确文件删除处理。
- 当前代码与动态路径已复核；111 项 canonical path、符号链接/跨挂载/类型检查通过。108 个非 Git 对象执行前无打开文件/相关进程命中；报告仅有 CodeGraph 只读索引句柄，未停止任何服务。
- 18 个保留锚点、64 个非目标同级对象、27,240 个 ignored 文件及 3,007 个程序/配置文件完成删除后对账；正式 2026-07-27 五频 Raw/Silver 共 10 文件仍在。正式数据内容未作扫描或重写。
- 旧湖根、六个共享家族目录及清单外 5 个 `.DS_Store` 保留；reports、quarantine、staging 共享目录与有效恢复数据未扩大清理。
- 三份报告可从 `3b94c48a` 取回；非 Git 湖文件不承诺可恢复。完整绝对路径、逐项结果、检查和限制见 LLD §16.15。用户已要求提交，执行记录按 10 文件白名单归档；不推送或处理 ignored 环境。
- 收口验证：根清退护栏 13 项、编排适配器退出/保留模块 17 项隔离回归通过；165 文档对象、3 控制文档、12 HTML 和 111 行绝对路径清单对账通过，文档完整性与差异检查通过。

---

## 7. 验收门禁

### 7.1 删除和保留路径

预期清零（以下目录只要求 Git 跟踪文件清零，不要求本机目录消失）：

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
LLD 第 9.4.2–9.4.3 节列出的 86 份纯旧 Console 文档
```

特别是 `lake_console/frontend/node_modules`、`dist` 等 ignored 内容不得为满足“清零”而删除；M8 的
数据白名单也不能覆盖这些依赖环境。物理数据验收另按 LLD §16，不能要求整个 `_quarantine` 不存在。

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

允许保留：历史 event metadata、现行迁移总账中的必要结果摘要、禁止规则和负向测试中的旧字符串。

### 7.3 CLI 行为等价与安全加固验收

1. 当前 28 个命令 inventory 与代码一致：7 个旧命令删除、21 个当前命令迁移。
2. 21 个当前命令逐个比较旧/新 parser 的参数名、类型、default、required、choices 和 action。
3. 使用 fake dependency 对比旧/新 handler 的目标函数、传参和值规范化、输出字典 key 和异常时点；
   禁止用真实 Lake/Dagster 写入做等价测试。
4. M2A 等价用例全部通过后，M2B 才运行 Silver selector 和 MACD/KDJ 单分区门禁正反例。
5. 任何当前命令出现名称、默认行为、输出或副作用差异，都必须解释为已批准的 M2B 安全修改；否则视为
   拆分回归，不得删除旧 CLI。

### 7.4 正式 Dagster 回归

实施时按实际变更文件选择并记录定向测试，至少覆盖：

1. definitions/asset governance 静态门禁。
2. catalog contracts。
3. run-contract metadata contracts。
4. stock identity map 正式资产、job、sensor、checks/readiness。
5. `stk_mins` silver history、qfq、technical、repair 和 event 模块。
6. ClickHouse definitions 和资源边界。

`dg` definitions 检查需要按仓库规则另行获得明确执行授权；不得把本方案评审视为自动授权。任何验收不得触发 materialize、job、sensor、backfill 或 runless event。

### 7.5 现行 DuckDB/Parquet、Ops 和前端保护

1. `src/foundation/clients/local_lake/**` 与分钟 API 回归通过。
2. 根 `pyproject.toml` 的 `local-lake` DuckDB optional dependency 仍在。
3. Ops Dataset Status Snapshot 的 service/query/CLI/worker/API 回归通过。
4. 根 `frontend/**` 构建/定向测试不受旧 frontend 删除影响。
5. ClickHouse 启动和 tunnel 脚本仍存在并通过语法检查。

### 7.6 模板验收

正式 Dagster onboarding 模板必须能独立回答：

1. 源端参数、字段、分页和 fan-out 如何验证。
2. 请求量、连接、内存、文件数、小文件、重试和配额如何估算。
3. schema/DuckDB 类型和精度如何确认。
4. 写入如何做临时文件校验、原子替换、checkpoint 和幂等恢复。
5. prod DB 读取如何保证只读、白名单、显式投影、参数绑定和流式拉取。
6. 真实 smoke 如何对账源端、归一化、写入、拒绝和目标行数。

如果任何一项只能从旧模板找到，M5 不得通过，旧模板不能先删。

### 7.7 文档与工作区门禁

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
| 把离线 Raw 恢复工具当旧湖迁移器直接删 | 丢失单日全市场五频事故恢复能力 | 已拍板保留能力；第 3.6 节重构项必须进入修改白名单 |
| 原样保留 Raw 恢复工具 | 正式根出现 `_staging/_quarantine` 和长期备份，违反当前路径规则 | 必须迁到正式 staging，改用逐文件 fingerprint/checkpoint/verified 和幂等续跑 |
| 仅搜索完整文件名就判无引用，或清空共享根 | 误删配置/glob/恢复代码仍读写的数据 | 审计真实路径构造；当前使用保留、仅旧代码使用先退依赖、无使用列可删；不以历史价值追加保留门禁；ignored 环境另轮处理 |

---

## 9. 回退姿态

1. M0–M7 Git 清退不包含数据库迁移、Dagster event rewrite、Lake 数据写入或物理目录删除；M8 单独执行和留证。
2. 合并前通过精确 diff 恢复误删；合并后整体 revert 清退提交。
3. 旧 Console frontend/backend 必须整体回退，不能只恢复一侧。
4. 不允许把 Kopia、旧 enum、旧 module wrapper、旧 CLI alias 或空壳 package 恢复为“临时兼容”。
5. 模板回退必须连同引用和正式模板内容一起评估，不能只恢复旧模板入口。
6. M8 必须逐项说明恢复能力：Git 跟踪的报告可从 Git 追溯；非 Git 数据若无既有可用副本则删除不可恢复，必须在清单中明示，不能承诺 Git 回退或假设有 Kopia 恢复。ignored 环境未来另轮处理。

---

## 10. 最终评审结论

### 10.1 可以直接删除

旧 Console 前后端及专属外围、纯旧 bootstrap spec/event/template/test，可以在删除前引用复核通过后直接删除。

### 10.2 必须拆依赖后再删

`stk_mins_migration.py`、`stk_mins_migration_cli.py`、`duckdb_sql.py`、catalog、bootstrap exports 和混合 tests 不能整文件先删；必须先迁出现行能力或删除旧分支的消费者，再清退旧实现。

### 10.3 两份旧模板是否还有用

两份文档都包含值得保留的检查项，但**都不再适合作为独立、现行模板继续使用**。正确处置是把有效内容并入正式 Dagster onboarding/性能治理文档，切换现行引用，然后删除旧模板。`lake-dataset-development-template.md` 不应因为过去常被用于新湖接入就原样保留；恰恰因为仍可能被打开，它的旧 Console 主体会持续误导新开发。

### 10.4 明确保留与物理数据分类

Ops Dataset Status Snapshot、正式 orchestrator、ClickHouse、正式 DuckDB/Parquet 和现行历史处理保留。
reports 不整删；旧湖和本专项遗留数据纳入 M8，以代码实际使用作为唯一用途依据，不再做内容替代证明。本机
ignored 依赖环境/配置仍在代码清退稳定后另轮精确处理。

### 10.5 下一步

M7 已提交 `3b94c48a`，未推送；用户随后确认 M8 的 111 个具体对象，已全部删除并完成范围对账，见 LLD §16.15。用户现已要求提交，本次仅按 10 文件白名单归档 7 份文档修改及 3 份旧报告删除，提交结果以 Git 记录为准，不推送或再次操作物理数据。当前字段、`vwap` 差异和日常链路保持不变。后续涨跌停全历史来源待该数据集开工前另审计；ignored 环境/本机配置仍另轮精确确认，不继续清空旧湖、reports、quarantine 或其它共享根。
