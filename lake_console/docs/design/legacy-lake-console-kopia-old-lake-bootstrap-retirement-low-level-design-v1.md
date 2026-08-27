# 旧 Lake Console、Kopia 与旧湖迁移适配器清退低层设计 v1

状态：代码逐项审计完成 / LLD 待评审 / 尚未实施

审计基线：`dev-interface`，`e712c1eda872`

审计日期：2026-08-27

上位方案：[`legacy-lake-console-and-kopia-retirement-plan-v1.md`](/Users/congming/github/goldenshare/docs/architecture/legacy-lake-console-and-kopia-retirement-plan-v1.md)

> 本文是本专项的代码实施依据。上位方案负责说明为什么清退、清退边界和阶段顺序；本文负责说明每个混合文件、运行契约、CLI、测试和文档具体如何修改。若实施时当前代码已经偏离本文审计基线，必须先重新做 CodeGraph 和文本引用审计，不能机械套用本文行号。

---

## 0. 结论先行

本专项可以安全实施，但不能把含有 `migration`、`bootstrap`、`snapshot`、`backup` 的文件按名字批量删除。

本次代码审计得到四个关键结论：

1. `lake_console/backend/**`、`lake_console/frontend/**`、旧 Console 专属入口和 `tests/lake_console/**` 是封闭的旧产品边界，可以同轮原子删除。
2. `stk_mins_migration.py` 和 `stk_mins_migration_cli.py` 是混合文件：旧湖/历史备份迁移能力要删除，但 Silver、QFQ、派生指标和 MACD/KDJ 历史治理能力仍在当前测试和正式湖链路中使用，必须先迁出再删原文件。
3. Raw `stk_mins` 不能把历史恢复来源清空。当前代码已经存在正式生产库只读的单日五频恢复能力，因此 catalog 应删除 `OLD_LAKE_BOOTSTRAP`，同时保留 `PROD_DB_READONLY` 作为 bootstrap/recovery 来源。
4. `ops.dataset_status_snapshot`、正式 Dagster、ClickHouse、DuckDB/Parquet、当前 Raw → Silver → Gold 派生、当前 runless event 治理均不在删除范围内。

本 LLD 没有遗留技术拍板项。实施仍需用户明确授权；本文自身不授权代码删除、数据写入、Dagster event 写入、数据库访问或物理目录清理。

---

## 1. 目标、依据与硬边界

### 1.1 开发目标

实现后必须同时满足：

1. 仓库中不再提供 Kopia repository、snapshot、restore、prewrite backup 或 recovery 的正向能力。
2. 旧 `lake_console/frontend + backend` 及其专属入口、测试和示例配置原子清零。
3. `OLD_LAKE_BOOTSTRAP`、`old_lake_root`、旧湖/历史备份读取 executor、spec、CLI 和事件补录入口清零。
4. 当前正式 Lake 的数据集、分区、历史生成、检查、事件治理、ClickHouse 和 Ops 能力保持可导入、可测试。
5. 不保留旧命令 alias、兼容 wrapper、tombstone module 或“先留着以后可能用”的运行代码。

### 1.2 依据文档

实施前必须以以下文档共同约束：

1. 根 `AGENTS.md`。
2. `lake_console/AGENTS.md`。
3. `lake_console/orchestrator/AGENTS.md`。
4. `lake_console/orchestrator/CODING_STANDARDS.md`。
5. `lake_console/docs/design/dagster-data-pipeline-performance-governance.md`。
6. 本文上位清退专项方案。

### 1.3 明确保留

以下对象不因本专项改名、迁移或删除：

```text
/Volumes/datasource/data_lake
/Volumes/datasource/data_lake_staging
/Volumes/datasource/goldenshare-tushare-lake
lake_console/orchestrator/**
lake_console/reports/**
lake_console/bin/lake-clickhouse-start
lake_console/bin/lake-prod-clickhouse-tunnel
src/foundation/clients/local_lake/**
src/foundation/config/local_minute_capability.py
ops.dataset_status_snapshot 及全部生产者/消费者
```

其中物理旧湖和本机 ignored 旧环境只是延期审计，不代表它们重新成为可用数据源。

### 1.4 本轮禁止副作用

代码清退实施本身不得：

1. 执行 Kopia 命令。
2. 读取、修改或删除物理旧湖。
3. 写正式 Lake、staging、数据库或 Dagster instance。
4. materialize asset、启动 backfill、注册动态分区或补报 runless event。
5. 删除 ignored 本机目录或 `lake_console/config.local.toml`。

---

## 2. 审计方法与影响面

### 2.1 审计方式

本次审计不是按关键字推断，而是逐层核对：

```text
CLI/parser
  -> handler
  -> service/history/event function
  -> filesystem / Dagster / DuckDB side effect
  -> catalog / metadata contract
  -> tests / static gates / docs consumer
```

已使用仓库根 CodeGraph 索引核对：

1. `BootstrapDatasetSpec` 的调用方和被调用方。
2. `plan_stk_mins_migration` 的消费者。
3. `discover_raw_stk_mins_partitions` 的当前消费者。
4. `BootstrapSourceMethod`、`IngestionSource` 和 `SourceSystem` 的影响面。
5. `_check_success_count` 的跨模块调用方。
6. 旧 backend `create_app` 的消费者边界。

CodeGraph 审计结果：旧 generic bootstrap/spec/executor 只连到旧迁移代码和旧测试；`_check_success_count`、Raw 分区发现、Silver/QFQ/指标 CLI 则仍被当前模块和测试使用，必须迁移。

### 2.2 代码边界数量

Git 跟踪文件按审计基线统计：

| 边界 | 文件数 | 处置 |
|---|---:|---|
| `lake_console/backend/**` | 181 | 原子删除 |
| `lake_console/frontend/**` | 65 | 原子删除 |
| `tests/lake_console/**` | 14 | 与前后端同轮删除 |
| 旧 Console 专属入口/示例配置 | 3 | 与前后端同轮删除 |
| 合计直接删除的旧产品文件 | 263 | 一个实施阶段完成 |

专属入口/示例配置为：

```text
lake_console/bin/lake-console
scripts/local-lake-console.sh
lake_console/config.local.example.toml
```

### 2.3 不可按目录整删的边界

`lake_console/orchestrator/src/orchestrator/defs/bootstrap/**` 不能整目录删除。该目录同时包含：

1. 要删除的旧湖 generic spec/executor。
2. 要删除的旧 Raw/identity-map 一次性迁移。
3. 当前仍使用的 Silver history、QFQ history、派生指标 history、MACD/KDJ history、canonical history、BSE recovery 和当前 event 审计。

实施必须按下文的符号级处置矩阵执行。

---

## 3. 目标代码结构

### 3.1 Bootstrap 包目标结构

清退后保留的相关结构为：

```text
orchestrator/defs/bootstrap/
  __init__.py
  stk_mins_history_check_events.py
  stk_mins_history_cli_contract.py
  stk_mins_silver_history.py
  stk_mins_silver_history_cli.py
  stk_mins_silver_bootstrap_events.py
  stk_mins_qfq_history.py
  stk_mins_qfq_history_cli.py
  stk_mins_qfq_bootstrap_events.py
  stk_mins_qfq_derived_history.py
  stk_mins_qfq_derived_history_cli.py
  stk_mins_qfq_derived_bootstrap_events.py
  stk_mins_qfq_macd_kdj_history.py
  stk_mins_qfq_macd_kdj_history_cli.py
  stk_mins_qfq_macd_kdj_baseline_events.py
  ...其余当前 history/recovery 模块
```

删除后不再存在：

```text
source_method.py
dataset_spec.py
old_lake_executor.py
specs/**
stk_mins_migration.py
stk_mins_migration_cli.py
adj_factor_raw_bootstrap_events.py
adj_factor_silver_bootstrap_events.py
```

### 3.2 设计原则

1. 每个 CLI 只承载一个当前数据层或当前派生产品的历史治理命令。
2. 新 CLI 保留现有命令名和输出字段，避免改变运维脚本的可观测语义。
3. 旧迁移命令不迁移、不别名、不打印退役提示，直接从可执行面消失。
4. 共享模块只放真正跨四个 CLI 的解析或事件计数能力，不建新的“大而全 migration utils”。
5. 文件移动不改变 asset key、partition definition、文件路径模板、检查名和 event metadata key。

---

## 4. `stk_mins_migration_cli.py` 逐段审计与修改设计

审计对象：`lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_mins_migration_cli.py`，审计基线共 1,038 行。

### 4.1 Import 区域逐段处置

| 当前行 | 当前内容 | 判定 | 修改 |
|---:|---|---|---|
| 1–7 | future、`argparse`、`Path`、Dagster | 混合依赖 | 分配到四个新 CLI；各文件只保留自身需要的 import |
| 8–9 | `BACKUP_STK_MINS_ROOT`、`OLD_TUSHARE_LAKE_ROOT` | 旧迁移专属 | 删除，不迁移 |
| 10–21 | `stk_mins_migration` imports | 混合 | 旧迁移函数删除；`all_raw_partition_keys` 改从 Silver history 模块导入 |
| 22–31 | QFQ 与 QFQ derived event imports | 当前 | 分别迁入 QFQ 和 QFQ derived CLI |
| 32–40 | QFQ derived/history imports | 当前 | 分别迁入对应 CLI |
| 41–50 | MACD/KDJ event/history imports | 当前 | 迁入 MACD/KDJ CLI |
| 51–61 | Silver event/history imports | 当前 | 迁入 Silver CLI |
| 62 | Silver 动态分区定义 | 当前共享 | 由新 shared CLI contract 读取 |
| 63–64 | 正式 Lake root、DuckDB resource | 当前 | 各新 CLI 按需导入 |

### 4.2 Parser 命令逐行分类

#### 4.2.1 删除的旧命令

| 当前 parser 行 | 命令 | 当前调用链 | 删除原因 |
|---:|---|---|---|
| 71 | `dry-run` | `_print_plan` → `plan_stk_mins_migration` → backup/old lake | 只规划一次性旧迁移 |
| 72–76 | `migrate-raw` | backup clean_next → Raw Lake | 历史备份迁移适配器已退役 |
| 78–80 | `migrate-identity-map` | old lake manifest → Silver identity map | 旧湖输入适配器已退役 |
| 82–84 | `register-partitions` | 扫描旧迁移 Raw 结果 → 动态分区 | 属于旧 Raw bootstrap 收尾；当前日常链另有正式分区管理 |
| 86–90 | `report-raw-events` | 旧迁移 Raw 文件 → runless event | 只为旧迁移补历史事件 |
| 92–95 | `report-identity-map-events` | 旧 identity map → runless event | 只为旧迁移补历史事件 |
| 97–98 | `audit-final` | backup/old lake 与正式湖最终对账 | 源端退役后无有效比较对象 |

对应 handler 行 248–336 整段删除，不迁到任何新 CLI。

#### 4.2.2 保留并迁入 Silver CLI 的命令

目标文件：`stk_mins_silver_history_cli.py`

| 当前 parser/handler 行 | 命令 | 目标行为 |
|---:|---|---|
| 100–103 / 337–357 | `plan-silver` | 只读规划 Raw → Silver 历史生成；保留输出字段 |
| 105–109 / 358–374 | `generate-silver` | 生成正式 Silver 文件；保留 skip/overwrite 语义 |
| 111–114 / 375–393 | `register-silver-partitions` | 注册已有 Silver 文件对应的动态分区；保留 `--dry-run` |
| 116–120 / 394–417 | `report-silver-events` | 审计已有 Silver 文件并补正式历史事件；保留跳过已物化选项 |
| 122–124 / 418–425 | `audit-silver-final` | 对选择日期范围做最终只读审计 |

新 parser description 使用 `stk_mins silver history governance`，不再出现 migration、backup 或 old lake。

Silver 参数必须收紧：

| 命令 | 保留选择器 | 删除选择器 | 原因 |
|---|---|---|---|
| `plan-silver` | `--partition-keys`、`--start-date`、`--end-date` | 无 | planner 本身可按范围发现 Raw 输入 |
| `generate-silver` | `--partition-keys`、`--all-from-raw-files`、日期范围 | `--all` | 明确全集来自 Raw 文件，消除 `--all` 隐式语义 |
| `register-silver-partitions` | `--partition-keys`、`--all-from-silver-files`、日期范围 | `--all`、`--all-from-raw-files` | 只能注册已经存在的 Silver 文件 |
| `report-silver-events` | `--partition-keys`、`--all-from-silver-files`、日期范围 | `--all`、`--all-from-raw-files` | event 必须以已存在且审计通过的 Silver 文件为准 |
| `audit-silver-final` | `--start-date`、`--end-date` | 所有“all”别名 | 审计函数自身按日期范围规划 |

参数错误必须在进入文件扫描或 Dagster instance 写入前抛出 `ValueError`。错误文本必须只列该命令真正支持的选择器。

#### 4.2.3 保留并迁入 QFQ CLI 的命令

目标文件：`stk_mins_qfq_history_cli.py`

| 当前 parser/handler 行 | 命令 | 保留行为 |
|---:|---|---|
| 126–128 / 426–453 | `plan-gold-qfq-history` | 规划 native QFQ 历史 |
| 130–132 / 454–475 | `generate-gold-qfq-history` | 生成 native QFQ 历史 |
| 134–136 / 476–504 | `plan-gold-qfq-events` | 规划当前 QFQ baseline events |
| 138–142 / 505–532 | `report-gold-qfq-events` | 报告审计通过的 QFQ events |
| 144–146 / 533–558 | `audit-gold-qfq-final` | QFQ 最终审计 |

所有命令保留：

```text
--lake-root
--start-date
--end-date
--partition-keys
--freqs
--years
```

只有 report 命令保留 `--dry-run` 和 `--skip-existing-ready`。生成、计划和审计命令不新增确认开关；本次不改变现行写入语义。

#### 4.2.4 保留并迁入 QFQ derived CLI 的命令

目标文件：`stk_mins_qfq_derived_history_cli.py`

| 当前 parser/handler 行 | 命令 | 保留行为 |
|---:|---|---|
| 148–150 / 559–592 | `plan-gold-qfq-derived-history` | 规划 90m/120m 等派生 QFQ 历史 |
| 152–156 / 593–614 | `generate-gold-qfq-derived-history` | 生成派生 QFQ 历史 |
| 158–162 / 615–646 | `plan-gold-qfq-derived-events` | 规划派生资产事件 |
| 164–173 / 647–674 | `report-gold-qfq-derived-events` | 报告派生资产事件 |
| 175–184 / 675–705 | `audit-gold-qfq-derived-final` | 支持 `full/quick` 的最终审计 |

`audit-gold-qfq-derived-final --mode quick` 继续跳过 check success history 计数；`full` 保持现行行为。本专项不改变检查数量和 readiness 判定。

#### 4.2.5 保留并迁入 MACD/KDJ CLI 的命令

目标文件：`stk_mins_qfq_macd_kdj_history_cli.py`

| 当前 parser/handler 行 | 命令 | 保留/修改 |
|---:|---|---|
| 186–190 / 706–735 | `plan-gold-stk-mins-qfq-macd-kdj-history` | 原样迁移 |
| 192–196 / 736–757 | `generate-gold-stk-mins-qfq-macd-kdj-history` | 原样迁移 |
| 198–211 / 758–781 | `rebuild-gold-stk-mins-qfq-macd-kdj-history` | 保留 checkpoint、stock codes 和显式确认门禁 |
| 213–217 / 782–809 | `audit-gold-stk-mins-qfq-macd-kdj-files` | 原样迁移 |
| 219–234 / 810–837 | `report-gold-stk-mins-qfq-macd-kdj-baseline-events` | 迁移并修复单分区安全门禁 |
| 236–245 / 838–867 | `audit-gold-stk-mins-qfq-macd-kdj-final` | 保留 `full/quick` |

Rebuild 命令保持以下硬约束：

1. `--checkpoint` 必填。
2. 未传 `--confirm-rebuild` 时在调用 rebuild function 前失败。
3. 未传 `--freqs` 时仍默认 `(5, 15, 30, 60)`。
4. `--stock-codes` 为空时仍传空 tuple，表示按原计划选择全部。
5. 不修改 checkpoint fingerprint、resume 或 batch 语义。

Baseline event 命令在现代码中默认可选整段历史，但现行指标设计要求一次只补一个 partition。迁移时必须补齐已经在当前设计文档中要求、代码尚未落实的门禁：

1. `--start-date` 和 `--end-date` 改为该子命令显式必填。
2. 两者必须相等。
3. planner 返回后再次断言 `len(report.plan.selected_partition_keys) == 1`。
4. `--dry-run` 也必须经过同样门禁，不能把 dry-run 当绕过方式。
5. 失败发生在 `report_stk_mins_qfq_macd_kdj_baseline_events` 报告事件之前。

这项修改是现行 MACD/KDJ 方案的安全门禁补齐，不是为了清退而新增业务能力。

### 4.3 Handler 输出契约

新 CLI 必须保留当前每个命令打印的 dictionary key。不得在拆文件时把可观测输出改成自由文本或统一成另一个 schema。

重点保留：

1. plan 命令的 selected count、source/target file count、missing input 和 samples。
2. generate 命令的 written/skipped file 或 asset partition count。
3. event 命令的 dry-run、audit count、failed count、reported/skipped count 和 event count。
4. audit 命令的 mode、materialized count、check success count 和 readiness samples。
5. rebuild 命令的 fingerprint、checkpoint path、resumed/executed batch count。

### 4.4 Helper 区域逐行处置

| 当前行 | Helper | 判定 | 目标 |
|---:|---|---|---|
| 870–889 | `_print_plan` | 旧迁移专属 | 删除 |
| 892–895 | `_add_common_paths` | old lake + backup | 删除 |
| 897–899 | `_add_lake_and_backup` | backup 专属 | 删除 |
| 902–904 | `_add_lake_and_old_lake` | old lake 专属 | 删除 |
| 907–915 | `_add_partition_selection` | 旧 raw migration 选择器 | 删除，不复用到当前 CLI |
| 918–920 | `_add_silver_history_range` | 当前 | 作为 Silver CLI 私有 helper |
| 923–928 | `_add_gold_qfq_history_selection` | 当前、四 CLI 共用 | 迁入 shared CLI contract 并改成显式命名 |
| 931–941 | `_add_silver_partition_selection` | 当前但参数含歧义 | 在 Silver CLI 内按命令分别注册参数，不整体复制 |
| 944–957 | `_selected_partition_keys` | backup/raw 双重语义 | 删除 |
| 960–969 | `_optional_partition_keys` | 当前通用 | 迁入 shared CLI contract，签名改为接收字符串值 |
| 972–975 | `_optional_csv_values` | 当前通用 | 迁入 shared CLI contract |
| 978–985 | `_registered_stock_mins_silver_partition_keys` | 当前通用 | 迁入 shared CLI contract，支持注入 instance 便于测试 |
| 988–1034 | `_selected_silver_partition_keys` | 当前但 `--all`/Raw/Silver 三义混合 | 拆成 Silver CLI 的两个明确 selector；不保留通用布尔组合 |
| 1037–1038 | module main guard | 当前入口 | 四个新 CLI 各自保留 |

### 4.5 新 shared CLI contract

目标文件：`stk_mins_history_cli_contract.py`

只允许包含：

```python
def add_history_selection_arguments(
    parser: argparse.ArgumentParser,
    *,
    default_start_date: str,
) -> None: ...

def parse_optional_partition_keys(value: str | None) -> tuple[str, ...] | None: ...

def parse_optional_csv_values(value: str | None) -> tuple[str, ...] | None: ...

def registered_stk_mins_silver_partition_keys(
    instance: dg.DagsterInstance | None = None,
) -> tuple[str, ...]: ...
```

约束：

1. parser helper 只添加日期、partition、freq、year，不添加任何旧湖或 backup 路径。
2. CSV 解析保持 strip、丢弃空值和稳定顺序语义。
3. partition keys 继续排序，避免 plan fingerprint 或测试输出因输入顺序漂移。
4. instance 传入时不得再次调用 `DagsterInstance.get()`；便于单元测试不连接本机正式 instance。
5. 不在该模块读取 Lake 文件或产生 Dagster event。

---

## 5. `stk_mins_migration.py` 逐段审计与修改设计

审计对象：`lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_mins_migration.py`，审计基线共 1,328 行。

### 5.1 旧迁移主体：删除

| 当前行 | 内容 | 处置 |
|---:|---|---|
| 1–86 | 旧迁移所需 imports 和基础定义 | 随消费者拆分后删除无用部分 |
| 87–186 | old migration dataclass、常量、样本 partition | 删除 |
| 189–232 | `plan_stk_mins_migration` | 删除 |
| 235–247 | backup partition discovery | 删除 |
| 265–298 | Raw 历史 backup migration | 删除 |
| 301–316 | identity-map old lake migration | 删除 |
| 319–333 | 旧 Raw partition registration | 删除 |
| 336–452 | Raw/identity-map event report | 删除 |
| 455–647 | 旧 Raw/identity-map audit | 删除 |
| 649–695 | backup/target final audit | 删除 |
| 698–703 | backup partition selector | 删除 |
| 722–760 | disk/backup/old path helpers | 删除 |
| 763–1284 | 旧迁移专属 check/audit 构造 | 删除 |
| 1298–1328 | 旧 check key/metadata constructors | 删除 |

这些代码不能改名为 generic history 工具，因为它们的 source contract、path contract 和 audit contract 都建立在退役的 backup/old lake 上。

### 5.2 当前能力：迁出

#### 5.2.1 Raw 分区发现

当前行 250–262 的 `discover_raw_stk_mins_partitions` 仍被 Silver history 用于发现五频 Raw 文件的日期交集。

迁入：`stk_mins_silver_history.py`

同时把当前行 704–707 的 `all_raw_partition_keys` 迁入并改名为：

```python
def all_raw_stk_mins_partition_keys(lake_root: Path) -> tuple[str, ...]: ...
```

改名原因是离开 migration module 后，`all_raw_partition_keys` 过于宽泛；新名称明确只扫描 `stk_mins` Raw 五频文件。

#### 5.2.2 五频 partition 对齐校验

当前行 710–721 的 `_validate_backup_partition_alignment` 实际逻辑是验证五个频率的 partition key 集合一致。它的语义是当前 Silver history 需要的输入完整性，不应继续叫 backup。

迁入并改名：

```python
def _validate_stk_mins_partition_alignment(
    partition_keys_by_freq: Mapping[int, tuple[str, ...]],
) -> tuple[str, ...]: ...
```

保持 fail-closed：任一频率多/少日期都失败，不自动取交集掩盖缺文件。

#### 5.2.3 Asset check success 计数

当前行 1287–1295 的 `_check_success_count` 被四个当前 event/final-audit 模块调用，不属于旧迁移。

迁入：`stk_mins_history_check_events.py`

公开名称：

```python
def count_succeeded_asset_check_executions(
    instance: dg.DagsterInstance,
    check_key: dg.AssetCheckKey,
) -> int: ...
```

本专项只移动，不重写语义：继续查询最多 50,000 条 execution history，并统计 `SUCCEEDED`。性能或分页策略另立专项，不能混入清退。

必须更新的四个消费者：

```text
stk_mins_silver_bootstrap_events.py
stk_mins_qfq_bootstrap_events.py
stk_mins_qfq_derived_bootstrap_events.py
stk_mins_qfq_macd_kdj_baseline_events.py
```

完成上述三类迁移并改完消费者后，整文件删除 `stk_mins_migration.py`，不保留 import compatibility layer。

---

## 6. Generic 旧湖 bootstrap 适配器清退

### 6.1 直接删除的运行模块

```text
orchestrator/defs/bootstrap/source_method.py
orchestrator/defs/bootstrap/dataset_spec.py
orchestrator/defs/bootstrap/old_lake_executor.py
orchestrator/defs/bootstrap/specs/__init__.py
orchestrator/defs/bootstrap/specs/adj_factor.py
orchestrator/defs/bootstrap/specs/stk_mins.py
orchestrator/defs/bootstrap/specs/stock_basic.py
orchestrator/defs/bootstrap/specs/stock_daily.py
orchestrator/defs/bootstrap/specs/stock_identity_map.py
orchestrator/defs/bootstrap/specs/suspend_d.py
orchestrator/defs/bootstrap/specs/trade_calendar.py
orchestrator/defs/bootstrap/adj_factor_raw_bootstrap_events.py
orchestrator/defs/bootstrap/adj_factor_silver_bootstrap_events.py
```

代码审计结论：

1. `BootstrapDatasetSpec` 强制包含 `old_lake_path_pattern`，不是当前通用 DatasetDefinition 或 history contract。
2. `old_lake_executor.py` 的输入读取直接由旧 path pattern 驱动，不能转成正式 Lake 内部派生 executor。
3. `specs/**` 的 source method 均建立在旧湖或历史 backup 上。
4. 两个 `adj_factor_*_bootstrap_events.py` 没有正式 definitions/CLI 消费者，只有旧测试 import。

### 6.2 `bootstrap/__init__.py`

保留 package 文件，但移除全部旧 spec/executor exports，内容收敛为包说明。

禁止从 `__init__.py` 重新导出四个新 CLI 或所有 history 函数。调用方应直接 import 具体子模块，避免再次形成大入口。

### 6.3 Enum 清理

#### `run_contracts/metadata.py`

只删除：

```python
SourceSystem.OLD_LAKE_BOOTSTRAP
```

保留 `SourceSystem` 及其现行成员。历史 Dagster event 中已经写入的字符串 metadata 不做存储迁移；删除 Python enum 不会改写历史事件。

#### `catalog/lake_assets.py`

只删除：

```python
IngestionSource.OLD_LAKE_BOOTSTRAP
```

`bootstrap_sources` 字段本身保留，因为正式生产库只读、Tushare 和当前 asset 派生仍是有效历史构建来源。

### 6.4 Catalog 逐资产修改

共修改 17 个 catalog entry：

| 资产组 | 数量 | 当前旧值 | 目标值 | 代码事实 |
|---|---:|---|---|---|
| `silver_adj_factor` | 1 | `OLD_LAKE_BOOTSTRAP` | `DERIVED_FROM_ASSETS` | 当前 asset 依赖 Raw adj factor 和 lifecycle |
| Raw `stk_mins` 1/5/15/30/60m | 5 | ingestion 含 OLD；bootstrap 为 OLD | ingestion 保留 `TUSHARE_API`、`PROD_DB_READONLY`；bootstrap 改为 `PROD_DB_READONLY` | 当前已有 `stk_mins_raw_replace_from_prod` 的单日五频正式恢复链 |
| Silver `stk_mins` 1/5/15/30/60m | 5 | OLD | `DERIVED_FROM_ASSETS` | 当前由五频 Raw 和参考数据生成 |
| native Gold QFQ 1/5/15/30/60m | 5 | OLD + DERIVED | 只保留 `DERIVED_FROM_ASSETS` | 当前由 Silver 和复权因子生成 |
| `silver_index_daily` | 1 | OLD | `DERIVED_FROM_ASSETS` | 当前读取同日 Raw index daily |

Raw `stk_mins` 的最终契约必须明确区分：

```text
日常主来源：PROD_DB_READONLY
可用同步/修复来源：PROD_DB_READONLY、TUSHARE_API
历史受控恢复来源：PROD_DB_READONLY
退役来源：OLD_LAKE_BOOTSTRAP、backup_clean_next
```

不得把 bootstrap sources 清空，否则 catalog 会与当前 `stk_mins_raw_replace_from_prod` 代码事实矛盾。

### 6.5 当前 asset metadata 与说明文字

#### `assets/stk_mins.py`

当前 `_raw_stk_mins_extra_metadata` 的：

```python
"bootstrap_source": "backup_clean_next"
```

仍把已经清退的 backup 当作当前可用来源。修改为当前稳定事实字段，例如：

```python
"historical_repair_source": "prod_db_raw_tushare"
```

五个 Raw asset description 中“历史基线来自 clean_next”改为：

1. 既有正式分区继续作为已提升的历史事实保留。
2. 当前日常/受控历史修复来自正式生产库只读链，Tushare 仅按当前策略参与同步或修复。
3. 当前 asset definition 不再携带旧 backup/old lake 的正向来源说明；历史 provenance 只留在历史文档和既有 event 中。

不修改 Raw 文件 schema、partition key、path、asset key、日常 source selection 或写入实现。

#### `checks/stk_mins_checks.py`

只修改仍写着“保留 backup clean_next 事实”的说明文字，改成来源无关的正式分区保留语义。检查 SQL、check key、passed 判定和 metadata 不变。

#### `run_contracts/asset_column_schemas.py`

Raw `stk_mins` 字段说明中“沿用 backup clean_next”的文字改成稳定的字段类型/业务语义。列名、顺序、DuckDB type 和 nullable contract 不变。

### 6.6 DuckDB SQL template 清理

`defs/duckdb_sql.py` 是当前共享文件，不能整删。只删除以下旧 spec 专属常量：

```text
TRADE_CALENDAR_BOOTSTRAP_SELECT_TEMPLATE
STOCK_BASIC_BOOTSTRAP_SELECT_TEMPLATE
STOCK_DAILY_BOOTSTRAP_SELECT_TEMPLATE
STK_MINS_BOOTSTRAP_SELECT_TEMPLATE
STOCK_IDENTITY_MAP_BOOTSTRAP_SELECT_TEMPLATE
ADJ_FACTOR_BOOTSTRAP_SELECT_TEMPLATE
SUSPEND_D_BOOTSTRAP_SELECT_TEMPLATE
```

同时精准修改：

1. `test_adj_factor_contracts.py`：只删旧 `ADJ_FACTOR_BOOTSTRAP_SELECT_TEMPLATE` import 和对应断言，保留当前 adj factor contract tests。
2. `test_stk_mins_contracts.py`：只删旧 `STK_MINS_BOOTSTRAP_SELECT_TEMPLATE`、`STOCK_IDENTITY_MAP_BOOTSTRAP_SELECT_TEMPLATE` import 和对应断言，保留当前分钟 schema/SQL contract tests。

---

## 7. 当前测试迁移设计

### 7.1 整文件删除的旧测试

```text
test_stk_mins_bootstrap_spec.py
test_stk_mins_migration.py
test_adj_factor_bootstrap_spec.py
test_adj_factor_raw_bootstrap_events.py
test_adj_factor_silver_bootstrap_events.py
```

其中 `test_stk_mins_migration.py` 不能先删：必须先把 Raw partition discovery、五频 alignment 和 success count 的现行覆盖迁到对应当前模块测试。

### 7.2 当前测试的 import 迁移

| 测试文件 | 当前依赖 | 目标依赖/修改 |
|---|---|---|
| `test_stk_mins_silver_m6_history.py` | Silver functions，无完整 CLI 覆盖 | 新增五个 Silver CLI 命令测试和选择器负例 |
| `test_stk_mins_qfq_m8c_history.py` | `stk_mins_migration_cli` | 改 import `stk_mins_qfq_history_cli` |
| `test_stk_mins_qfq_m8d_events.py` | `stk_mins_migration_cli` | 改 import `stk_mins_qfq_history_cli` |
| `test_stk_mins_qfq_m11f_derived_history.py` | `stk_mins_migration_cli` | 改 import `stk_mins_qfq_derived_history_cli` |
| `test_stk_mins_qfq_m12_macd_kdj.py` | `stk_mins_migration_cli` | 改 import `stk_mins_qfq_macd_kdj_history_cli`，新增单分区门禁测试 |

`test_stk_mins_qfq_m8c_history.py` 中用于证明 canonical unsafe command 不应存在的负例，不能继续调用将删除的 migration CLI。它应直接针对当前 canonical CLI：

```python
stk_mins_qfq_canonical_history_cli.main(
    ["rebuild-gold-qfq-canonical-history"]
)
```

目标仍是证明 unsafe command 不存在，不是保留旧 migration dispatcher。

### 7.3 CLI 最小测试矩阵

每个新 CLI 至少覆盖：

1. module 可独立 import。
2. 每个保留命令能正确 dispatch 到目标 function。
3. 参数解析后 Path、tuple、日期、freq、year 与当前 handler 传参一致。
4. 输出 dictionary 保留现有 key。
5. 未选择 partition/source 时 fail-closed。
6. `--all` 在 Silver CLI 不再可接受。
7. register/report Silver 不接受 `--all-from-raw-files`。
8. rebuild 未确认时不调用写函数。
9. baseline event 日期不相等或选出多 partition 时不调用 event report。
10. `--dry-run` 不绕过参数和单分区校验。

### 7.4 Static gate 修改

`test_run_contract_static_gates.py` 精准修改：

1. 删除 `BACKEND_DIR` 常量。
2. active source roots 从 `(DEFS_DIR, BACKEND_DIR / "app")` 收敛为 `DEFS_DIR`。
3. MACD/KDJ rebuild 命令和 `--confirm-rebuild` 的源码检查改读新 MACD/KDJ CLI。
4. canonical unsafe command 的负向检查改读 canonical CLI。
5. 删除对旧 backend 两个 derived service 文件的 removed-path 断言；目录本身已被 Git 删除，不再把不存在的旧产品文件当 current gate。
6. 保留对当前 defs 中 legacy derived symbol 的负向扫描。
7. 增加旧运行契约正向使用清零 gate，但允许历史文档和禁止性测试中出现字符串。

建议 gate 只扫描 Python/配置的正向代码边界，不能要求仓库全文 `OLD_LAKE_BOOTSTRAP` 字符串为零，否则会误伤历史证据和本清退文档。

---

## 8. 旧 Console 与 Kopia 原子删除设计

### 8.1 原子删除边界

同一提交阶段删除：

```text
lake_console/backend/**
lake_console/frontend/**
tests/lake_console/**
lake_console/bin/lake-console
scripts/local-lake-console.sh
lake_console/config.local.example.toml
```

不能先删 frontend 再让 backend 暂时存活，也不能保留 backend API 供“以后可能用”。用户已明确前后端同轮清退。

### 8.2 Backend 依赖审计

旧 backend 181 个文件中，主要内部边界为：

| 子目录 | 文件数/职责概况 | 外部耦合结论 |
|---|---|---|
| `app/services/**` | 65，catalog/sync/recovery/storage/derived 等旧服务 | 只被旧 backend API/CLI/tests 消费 |
| `app/sync/**` | 23，旧 planner/engine/source/strategy | 旧 Console 同步链专属 |
| `app/catalog/**` | 17，旧数据集 catalog/model | 不是当前 `DatasetDefinition` 或 Dagster catalog |
| `app/cli/**` | 14，旧 Console CLI | 只由旧 `lake-console` 入口调用 |
| `app/api/**` | 10，旧 HTTP API | 只由旧 frontend/backend tests 消费 |
| `app/schemas/**` | 3，旧 API schema | 无当前业务消费者 |
| `main.py/settings.py/__init__.py` | 应用入口与旧配置 | CodeGraph `create_app` 只连接旧测试 |

未发现 `src/**`、`qtf/**`、`wealth/**`、根 `frontend/**` 或正式 orchestrator import 旧 backend Python package。

Backend 中的 ClickHouse、DuckDB、Parquet 字样不能成为保留理由：它们属于旧 Console 的管理 API/服务实现，不是正式 Dagster definitions。当前正式 ClickHouse/DuckDB/Parquet 实现位于 orchestrator 等保留边界。

### 8.3 Frontend 依赖审计

旧 frontend 65 个文件由自己的 Vite/React 配置、`src/**`、静态资源和局部 skill 组成，API client 指向旧 backend。未发现根 `frontend/**` import 它的组件或配置。

因此删除旧 frontend 不影响当前行情/运营前端。实施后 `.agents/skills/frontend-qa/SKILL.md` 必须移除旧 `lake_console/frontend` 的构建和 QA 入口，避免工具继续指导启动不存在的应用。

### 8.4 Kopia 删除边界

Kopia 正向实现全部位于将删除的旧 backend 及其旧文档/配置入口。实施后：

1. 可执行 Python、shell、frontend 和示例配置不再提供 Kopia endpoint、command、repository setting 或 restore flow。
2. 根和架构规则继续保留“禁止恢复 Kopia”的负向约束。
3. `tests/architecture/test_wealth_sector_heat_guardrails.py` 等负向 Kopia guard 保留。
4. 历史设计文档可记载曾使用 Kopia，但必须标为历史/退役，不能给出现行执行步骤。

### 8.5 明确保留的同名/近名能力

以下内容虽含 lake、backup、recovery 或 local_lake 语义，但不属于旧 Console：

1. `src/foundation/clients/local_lake/**`：有当前业务消费者。
2. `src/foundation/config/local_minute_capability.py`：当前分钟能力配置。
3. 根 `pyproject.toml` 中 `local-lake` DuckDB optional dependency：当前 Python 能力边界。
4. `gold_stock_daily_qfq_history_reset_cli.py` 中“old target files”：指本次受控 reset 前的正式目标文件，不是旧 Console 湖。
5. BSE recovery、candidate/audit/promote/checkpoint：当前正式 Lake 恢复机制。

---

## 9. 文档模板和规则修改设计

### 9.1 旧模板删除前的内容迁移

删除：

```text
docs/templates/lake-dataset-development-template.md
docs/templates/lake-prod-raw-db-export-template.md
lake_console/docs/templates/dagster-bootstrap-migration-template.html
```

不是直接丢弃全部内容。先迁移仍有效的检查项。

#### 合并到正式 Dagster onboarding 模板

目标：`lake_console/docs/templates/dagster-dataset-onboarding-template.html`

补充：

1. 源端默认字段、显式字段、业务关键字段三类输出核对。
2. 输入参数、分页、日期过滤和 fan-out 模式。
3. 请求数、SQL 数、连接数、分页数、预计时间和配额估算。
4. fetch batch、write batch、内存峰值和 retry 粒度。
5. Parquet/DuckDB 字段类型和 schema 对账。
6. 文件数与小文件风险。
7. 临时文件完整性校验、同文件系统原子替换。
8. 源端行数、归一化行数、写入行数、reject reason 和目标行数真实 smoke 对账。
9. 当前 history/rebuild 只允许正式 Tushare、生产库只读、正式 Lake upstream 或版本化 seed；禁止旧湖和 Kopia。

#### 合并到性能治理文档

目标：`lake_console/docs/design/dagster-data-pipeline-performance-governance.md`

补充：

1. 生产库只读单连接和 read-only transaction。
2. server-side cursor / `fetchmany` 边界。
3. 表和列白名单、显式 projection、参数绑定、禁止 `SELECT *`。
4. query 数、连接数、fetch batch、内存和总耗时预算。
5. source schema、read count、normalized count、write count 对账。

### 9.2 规则文件修改

| 文件 | 修改 |
|---|---|
| 根 `AGENTS.md` | 把“旧 backend Kopia 是冻结实现证据”改为“代码已删除，禁止恢复”；保留路径和 Kopia 负向规则 |
| `lake_console/AGENTS.md` | 重写为 orchestrator/docs/reports/保留 bin 的当前边界，删除旧 frontend/backend 开发规则 |
| `lake_console/orchestrator/AGENTS.md` | 删除“旧湖迁移”作为 direct bootstrap 允许来源；保留正式湖内部历史生成、rebuild 和 runless event 规则；删除旧湖文件必须作为源证据的要求 |
| `CODING_STANDARDS.md` | 把 `old_lake` 正向 metadata 示例换成当前稳定 provenance 示例 |
| `.agents/skills/frontend-qa/SKILL.md` | 删除旧 frontend scope 和 build command |
| `.agents/skills/lake-dataset-onboarding/SKILL.md` | 只指向正式 Dagster onboarding 模板 |
| `scripts/AGENTS.md` | 删除 `local-lake-console.sh` 启动规则 |

### 9.3 当前架构文档修改

1. `lake_console/README.md` 重写为当前 workspace 索引，只介绍 orchestrator、docs、reports 和保留 bin。
2. `docs/architecture/codegraph-architecture-snapshot.md` 更新旧 Console 节点删除和 bootstrap 调用链拆分。
3. `dagster-data-system-architecture.html` 删除正向 `KopiaResource`，把 Raw `stk_mins` 历史来源改成“已提升正式事实 + 生产库只读恢复”。
4. `dagster-run-contract-governance.html` 删除 old-lake source enum 的当前契约说明。
5. `dagster-new-lake-asset-catalog-design.md` 删除旧湖作为未来 bootstrap source 的设计。
6. `dagster-bootstrap-legacy-links.md` 保留为历史总账，但必须明确 executable adapter 已清退、物理旧湖延期审计、不可作为操作手册。

历史 phase/验收文档中的旧来源事实不篡改；缺少状态标记时加“历史/已退役”页首说明。

---

## 10. 文件级处置清单

### 10.1 新增

```text
orchestrator/defs/bootstrap/stk_mins_history_check_events.py
orchestrator/defs/bootstrap/stk_mins_history_cli_contract.py
orchestrator/defs/bootstrap/stk_mins_silver_history_cli.py
orchestrator/defs/bootstrap/stk_mins_qfq_history_cli.py
orchestrator/defs/bootstrap/stk_mins_qfq_derived_history_cli.py
orchestrator/defs/bootstrap/stk_mins_qfq_macd_kdj_history_cli.py
```

### 10.2 修改代码

```text
orchestrator/defs/bootstrap/__init__.py
orchestrator/defs/bootstrap/stk_mins_silver_history.py
orchestrator/defs/bootstrap/stk_mins_silver_bootstrap_events.py
orchestrator/defs/bootstrap/stk_mins_qfq_bootstrap_events.py
orchestrator/defs/bootstrap/stk_mins_qfq_derived_bootstrap_events.py
orchestrator/defs/bootstrap/stk_mins_qfq_macd_kdj_baseline_events.py
orchestrator/defs/catalog/lake_assets.py
orchestrator/defs/run_contracts/metadata.py
orchestrator/defs/run_contracts/asset_column_schemas.py
orchestrator/defs/assets/stk_mins.py
orchestrator/defs/checks/stk_mins_checks.py
orchestrator/defs/duckdb_sql.py
```

### 10.3 修改测试

```text
test_adj_factor_contracts.py
test_stk_mins_contracts.py
test_stk_mins_silver_m6_history.py
test_stk_mins_qfq_m8c_history.py
test_stk_mins_qfq_m8d_events.py
test_stk_mins_qfq_m11f_derived_history.py
test_stk_mins_qfq_m12_macd_kdj.py
test_run_contract_static_gates.py
catalog 相关测试文件
```

### 10.4 删除代码和测试

删除边界以第 6、7、8 章清单为准。实施时应由 Git 精确 pathspec 删除，禁止使用模糊 glob 触及整个 `lake_console/` 或整个 `bootstrap/`。

### 10.5 保留不改代码

```text
ops.dataset_status_snapshot 全链
stk_mins 当前 Raw/Silver/Gold asset keys 和 partitions
stk_mins_raw_replace_from_prod
stk_mins BSE history recovery
canonical history CLI
candidate/audit/promote/checkpoint 实现
正式 ClickHouse resources/assets
lake_console/reports/**
本机 ignored 配置和目录
物理旧湖
```

---

## 11. 实施分片与顺序

### M0：基线冻结

1. 记录 branch、HEAD、工作区状态和精确变更白名单。
2. `codegraph sync` 后确认索引 current。
3. 重新运行旧 source、old root、mixed CLI 和 backend import 的引用清单。
4. 发现本文以外的当前消费者时停止，不进入删除。

### M1：先迁当前 `stk_mins` helper

1. 新增 check-event helper。
2. 把四个当前 event 模块改用新 helper。
3. 把 Raw partition discovery/alignment 迁到 Silver history。
4. 更新对应测试并跑定向回归。
5. 此阶段不删旧 migration 文件，保证每一步可验证。

### M2：拆当前 CLI

1. 新增 shared CLI contract。
2. 分别新增 Silver、QFQ、QFQ derived、MACD/KDJ CLI。
3. 迁移现行命令和输出契约。
4. 收紧 Silver selector 和 MACD/KDJ baseline 单分区门禁。
5. 更新所有测试和 static gates。
6. 证明无当前消费者后删除 `stk_mins_migration_cli.py`。

### M3：删除旧 migration 主体

1. 证明 `stk_mins_migration.py` 只剩旧符号且所有当前 import 已清零。
2. 删除该文件及纯旧测试。
3. 运行当前 Silver/QFQ/derived/MACD/KDJ 全套定向测试。

### M4：删除 generic old-lake adapter

1. 删除 source method、dataset spec、executor、specs 和 adj factor old event 模块。
2. 清理 bootstrap package exports。
3. 删除旧 SQL templates 和精准测试断言。
4. 修改 enum、catalog 和当前 metadata 说明。
5. 运行 catalog、run contract、asset/check contract 测试。

### M5：合并模板并更新规则

1. 先把有效检查项写入正式模板和性能治理文档。
2. 更新当前引用。
3. 删除三个旧模板。
4. 更新 AGENTS、skills、README、架构图和历史状态标记。
5. 运行文档完整性检查。

### M6：原子删除旧 Console/Kopia

1. 精确删除旧 frontend/backend/tests/entrypoints/example config。
2. 同轮移除所有当前文档/skill/脚本正向入口。
3. 保留 reports、正式 bin、orchestrator 和 ignored 环境。
4. 运行仓库引用清零 gate。

### M7：全量验证与差异复核

1. 执行第 12 章验证矩阵。
2. 逐项对照上位方案和本文 acceptance checklist。
3. 只 stage 本专项白名单；禁止 `git add .`。
4. 检查 staged name-status 和 staged diff，确认无物理数据、ignored 环境和用户无关改动。

---

## 12. 验证矩阵

### 12.1 静态引用清零

可执行代码和生效配置中以下正向符号必须为零：

```text
OLD_LAKE_BOOTSTRAP
old_lake_root
OLD_TUSHARE_LAKE_ROOT
BACKUP_STK_MINS_ROOT
BootstrapDatasetSpec
BootstrapSourceMethod
execute_old_lake_bootstrap
plan_stk_mins_migration
migrate_stk_mins_raw_history
migrate_stock_identity_map_snapshot
report_stk_mins_raw_bootstrap_events
report_stock_identity_map_bootstrap_events
backup_clean_next 作为当前 source metadata
```

历史文档、迁移记录和禁止性 guard 可保留字符串；验证脚本必须区分运行代码与历史文本。

### 12.2 Python 验证

1. 对全部新增/修改 Python 文件运行 formatter/linter。
2. 对 orchestrator package 运行 `compileall`。
3. 运行所有第 7 章定向测试。
4. 运行 catalog、metadata、asset column schema、DuckDB SQL contract 测试。
5. 运行 `test_run_contract_static_gates.py`。
6. 运行 orchestrator 全量 pytest。

### 12.3 Definitions 验证

`dg check defs` 和 `dg list defs` 可验证删除后 definitions 可加载、asset/check/job/sensor 数量无意外变化，但依据仓库规则必须单独获得命令执行授权。本专项代码授权不能自动扩展成 `dg` 授权。

Definitions 验收关注：

1. 当前 asset key 数量不因旧 Console 删除变化。
2. 当前 `stk_mins` Raw/Silver/QFQ/derived/MACD-KDJ assets 和 checks 仍可加载。
3. 不出现旧 bootstrap asset/source definition。
4. 不产生 materialization、partition registration 或 runless event。

### 12.4 文档验证

1. `python3 scripts/check_docs_integrity.py`。
2. 当前索引不再把三个旧模板列为现行入口。
3. 当前规则和 skills 不再提供旧 Console/Kopia/old-lake bootstrap 操作步骤。
4. 历史文档链接仍可追溯，状态明确。

### 12.5 Git 边界验证

1. `git diff --check` 通过。
2. `git diff --name-status` 只包含批准白名单。
3. 删除数量与第 2、6、8 章清单对账。
4. `lake_console/orchestrator/**` 当前代码没有被目录级误删。
5. `lake_console/reports/**`、物理旧湖和 ignored 环境没有变更。

---

## 13. 失败处理与回退

### 13.1 在提交前失败

每个 M 阶段在进入下一阶段前必须通过对应定向测试。失败时只修复该阶段的代码映射，不恢复旧 alias 绕过测试。

### 13.2 发现新消费者

如果实施时发现本文未列出的当前消费者：

1. 停止删除目标符号或文件。
2. 沿调用链确认它是当前能力还是旧能力。
3. 当前能力迁到本 LLD 的对应目标模块；旧能力加入删除清单。
4. 更新本文和上位方案后再继续。

### 13.3 已提交后的代码回退

代码回退只能回退 Git 变更，不触碰数据。由于本专项不执行数据或 Dagster 写入，不需要数据回滚。

不得以回退为由重新启用 Kopia、old-lake adapter 或兼容 CLI。若新 CLI 有缺陷，应修复新 CLI；只有整个专项提交回退时才由 Git 恢复原状态。

### 13.4 物理环境

物理旧湖和 ignored 环境本轮没有变更，因此不属于本 LLD 的回退对象。它们在代码稳定后另立精确审计和删除方案。

---

## 14. 完成验收清单

### 14.1 `stk_mins` 当前能力

- [ ] 四个当前 CLI 可以独立 import。
- [ ] 21 个保留命令全部迁移到正确 CLI。
- [ ] 7 个旧 migration 命令全部消失。
- [ ] Silver 命令不再存在含糊 `--all`。
- [ ] Silver register/report 只从 Silver 文件或显式 keys 选择。
- [ ] MACD/KDJ rebuild 仍要求 checkpoint 和 confirm。
- [ ] MACD/KDJ baseline event 只能选择单日单 partition。
- [ ] Raw/Silver/QFQ/derived/MACD-KDJ 当前 tests 通过。
- [ ] `stk_mins_migration.py` 和 CLI 不留 wrapper/alias。

### 14.2 旧适配器

- [ ] generic old-lake spec/executor/specs 全部删除。
- [ ] `OLD_LAKE_BOOTSTRAP` 和 `old_lake_root` 无运行时正向使用。
- [ ] 旧 DuckDB bootstrap templates 清零。
- [ ] 旧 adj-factor event 补录模块和纯旧测试删除。
- [ ] 历史事件不做存储改写。

### 14.3 Catalog 与 metadata

- [ ] 17 个 catalog entry 按第 6.4 节逐个对账。
- [ ] Raw `stk_mins` bootstrap source 是 `PROD_DB_READONLY`，不是空集合。
- [ ] Silver/Gold/index/adj 的 derived source 与当前依赖一致。
- [ ] 当前 asset metadata 不再宣称 backup clean_next 可用。
- [ ] schema、asset key、partition 和 path contract 未变化。

### 14.4 旧 Console/Kopia

- [ ] 263 个旧产品边界文件原子删除。
- [ ] 旧 backend/frontend 无当前 import、build、start 或 API 入口。
- [ ] Kopia 无可执行代码和生效配置。
- [ ] 正式 orchestrator、reports、ClickHouse bins 和根 frontend 保留。

### 14.5 文档与边界

- [ ] 有效模板检查项已先迁入正式模板/性能文档。
- [ ] 三个旧模板删除，当前引用已更新。
- [ ] AGENTS、skills、README 和架构文档与代码事实一致。
- [ ] 物理旧湖、reports、ignored 环境和 Ops Snapshot 未触碰。
- [ ] 全量验证通过，staged diff 只含专项白名单。

---

## 15. 最终实施口径

本专项不是“删除所有 snapshot/bootstrap/migration”，而是删除两个明确产品/数据方向：

```text
旧 Lake Console + Kopia
旧湖/历史备份 -> 正式 Lake 的一次性适配器
```

当前正式链继续存在：

```text
Prod DB readonly / Tushare
  -> Raw stk_mins
  -> Silver stk_mins
  -> Gold QFQ / derived / MACD-KDJ
  -> checks / history events / final audit
```

`stk_mins_migration_cli.py` 的正确修改不是整删命令，也不是整文件保留，而是：删除 7 个旧迁移命令，把 21 个当前命令迁入 4 个职责明确的 CLI，迁出 3 类当前 helper，然后删除原来的混合 dispatcher 和 migration module。这个拆分是实施安全性的核心门禁。
