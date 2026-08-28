# 旧 Lake Console、Kopia 与旧湖迁移适配器清退低层设计 v1

状态：代码逐项复核完成 / LLD 已补逐文件删除矩阵与 CLI 等价门禁 / Raw 恢复工具重构已拍板 / 尚未实施

审计基线：`dev-interface`，`c232889858d6fe93a3224bf65d3cdb682e4382f0`（用户无关工作区改动不纳入本专项）

分支口径：用户已确认 `main` 无需在本专项实施前强制追平；实施基线只认当前 `dev-interface` 的记录
HEAD、CodeGraph 状态和精确文件白名单。

审计日期：2026-08-28

上位方案：[`legacy-lake-console-and-kopia-retirement-plan-v1.md`](/Users/congming/github/goldenshare/docs/architecture/legacy-lake-console-and-kopia-retirement-plan-v1.md)

> 本文是本专项的代码实施依据。上位方案负责说明为什么清退、清退边界和阶段顺序；本文负责说明每个混合文件、运行契约、CLI、测试和文档具体如何修改。若实施时当前代码已经偏离本文审计基线，必须先重新做 CodeGraph 和文本引用审计，不能机械套用本文行号。

---

## 0. 结论先行

本专项可以安全实施，但不能把含有 `migration`、`bootstrap`、`snapshot`、`backup` 的文件按名字批量删除。

本次代码审计得到四个关键结论：

1. `lake_console/backend/**`、`lake_console/frontend/**`、旧 Console 专属入口和 `tests/lake_console/**` 是封闭的旧产品边界，可以同轮原子删除。
2. `stk_mins_migration.py` 和 `stk_mins_migration_cli.py` 是混合文件：旧湖/历史备份迁移能力要删除，但 Silver、QFQ、派生指标和 MACD/KDJ 历史治理能力仍在当前测试和正式湖链路中使用，必须先迁出再删原文件。
3. Raw `stk_mins` 的非 active 单日五频 prod-DB 恢复工具不属于旧湖/Kopia；用户已拍板保留业务能力
   并重构实现。它必须迁到正式 staging，改成逐文件 fingerprint/checkpoint/验证/幂等续跑，不能原样保留。
4. `ops.dataset_status_snapshot`、正式 Dagster、ClickHouse、DuckDB/Parquet、当前 Raw → Silver → Gold 派生、当前 runless event 治理均不在删除范围内。
5. 原拟历史化的 86 份纯旧 Console 文档从当前工作树删除；必要执行结果压缩进现行总账/设计，全文只
   通过 Git 历史追溯，不建立 archive 或 tombstone。

本 LLD 已无未决业务口径。实施仍需用户明确授权；本文自身不授权代码/旧文档删除、数据写入、
Dagster event 写入、数据库访问或物理目录清理。

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
7. `stk_mins_raw_replace_from_prod` 的 plan/apply/CLI、测试、历史执行和 active definitions 边界。
8. 四个 `src/foundation/clients/local_lake` Reader 到 Biz API、app router、Wealth 页面和测试的消费者。

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

### 4.2.6 21 个当前命令的行为等价迁移协议

“命令名相同”不足以证明 CLI 没被改坏。M2 必须拆成 M2A 等价迁移和 M2B 安全加固，且先后不可
颠倒。

M2A 开始前新增冻结 fixture：

```text
lake_console/orchestrator/tests/fixtures/stk_mins_history_cli_contract_v1.json
lake_console/orchestrator/tests/test_stk_mins_history_cli_contract_equivalence.py
```

fixture 对第 4.2.2–4.2.5 节每个命令逐项保存：

| 合同维度 | 必须冻结的值 |
|---|---|
| identity | 原命令名、目标新 CLI、命令职责 |
| parser | option 名、positional 顺序、type、default、required、choices、`store_true/store_false` action |
| normalization | `Path`、日期字符串、freq/year/partition tuple、空 tuple/`None` 的现行值 |
| dispatch | 目标 function 的 module/name、位置参数/关键字参数映射 |
| output | 当前 `print(...)` dictionary 的 key 集合、嵌套关键 key、返回值/exit code |
| side effect | `READ_ONLY`、`LAKE_WRITE`、`DAGSTER_WRITE` 三类；确认/`dry-run`/checkpoint 门禁发生时点 |
| failure | 缺必填参数、非法 choice、未确认、空 selector 时的异常类型和在目标 function 前失败的要求 |

M2A 测试方式：

1. 在旧 dispatcher 仍存在时，用同一 argv 分别调用旧入口和目标新入口。
2. patch 全部目标函数、Dagster instance、DuckDB/Lake writer 为记录调用的 fake；测试不得读写真实 Lake、
   数据库或 Dagster instance。
3. 对比 parser 后的规范化参数、被调 function、调用次数、args/kwargs、stdout dictionary 和异常时点。
4. 21 个命令每个至少一条正例；有 `--dry-run`、checkpoint、confirm 或多 selector 的命令补对应边界例。
5. 7 个旧命令只验证目标四个新 CLI 均拒绝，不生成兼容提示或 alias。
6. 双跑全绿后删除旧 dispatcher；测试改为“新 CLI 对冻结 fixture”，不能为了继续双跑保留旧 module。

M2A 明确禁止：

1. 改命令名、option 名、默认 freq/year/date、输出 key 或异常类型。
2. 把原本 read-only 的命令变成写入，或把写入门禁后移。
3. 顺手收紧 Silver selector 或 MACD/KDJ 单分区；这两项只允许在 M2B 出现。
4. 用“新 CLI 单元测试通过”替代 old/new 同输入对账。

M2B 只允许两项批准差异，并在 fixture 上标记 `approved_delta`：

| 命令组 | 批准差异 | 必须新增的负例 |
|---|---|---|
| Silver register/report/generate | 删除含糊 `--all`；register/report 禁止 `--all-from-raw-files` | 旧 selector 在扫描文件或访问 Dagster 前失败；显式 keys/正确文件 selector 仍 dispatch 一次 |
| MACD/KDJ baseline event | `start_date/end_date` 必填且相等，planner 只能返回一个 partition | 跨日、零 partition、多 partition、`--dry-run` 跨日均不得调用 event report |

除这两项外，任何差异都是回归，不得解释为“拆文件后的自然变化”。

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
| Raw `stk_mins` 1/5/15/30/60m | 5 | ingestion 含 OLD；bootstrap 为 OLD | ingestion 保留 `TUSHARE_API`、`PROD_DB_READONLY`；`bootstrap_sources=(PROD_DB_READONLY,)` | 用户已拍板保留 prod-DB 单日五频恢复能力，但必须先完成正式 staging/checkpoint 重构 |
| Silver `stk_mins` 1/5/15/30/60m | 5 | OLD | `DERIVED_FROM_ASSETS` | 当前由五频 Raw 和参考数据生成 |
| native Gold QFQ 1/5/15/30/60m | 5 | OLD + DERIVED | 只保留 `DERIVED_FROM_ASSETS` | 当前由 Silver 和复权因子生成 |
| `silver_index_daily` | 1 | OLD | `DERIVED_FROM_ASSETS` | 当前读取同日 Raw index daily |

Raw `stk_mins` 工具的代码事实：

```text
stk_mins_raw_replace_from_prod_cli.py plan
  -> ops.task_run 全市场 success（只读）
  -> DG stock_basic 推导当日股票全集
  -> prod raw_tushare.stk_mins 五频事实聚合（只读）
  -> 五个正式 Raw 文件 SHA-256
  -> /private/tmp plan report + fingerprint

stk_mins_raw_replace_from_prod_cli.py apply --apply --plan-report
  -> 重做 plan 并比对 fingerprint
  -> 五频导出 staging + schema/key/date/code/time/row 验证
  -> 五个旧 target 移入 quarantine
  -> 五个 staging 逐一 os.replace 到 target
  -> 异常时恢复已移动旧 target
```

该模块没有 asset/job/sensor/check decorator，没有被 definitions 装配；正向调用方只有专属 CLI，测试和
历史设计不构成运行入口。2026-07-27 曾实际使用，Raw apply 约 109,973ms，之后由普通 Raw job
`reuse_existing` 重新记录 materialization/check。新 BSE recovery 只处理冻结的 BSE scope，不能等价替代
任意交易日全市场五频 prod-DB 恢复。

日常 Raw job 同样不是替代物：当前 run contract 的 `source=prod_db` 只允许 `reuse_existing`，不会覆盖
已存在目标；`merge_repair` 只允许 `source=tushare`，语义是缺失代码合并，不提供 prod-DB 五频整体
替换。因此该 CLI 的业务空档真实存在；用户已拍板继续保留该能力并重构实现。

但当前 `_staging_root(...)` 解析到正式 Raw 树内 `raw/tushare/stk_mins/_staging/**`，
`_quarantine_root(...)` 解析到正式根 `_quarantine/**`，成功后 manifest 和五个 backup 文件长期保留。
这与根规则“候选只能在 `/Volumes/datasource/data_lake_staging`、正式根只允许 raw/silver/gold、不得以
文件备份/快照承担恢复”冲突。

此外，当前五次 `os.replace()` 仅各自保证单文件原子，五个频率之间没有文件系统事务。正常 Python
异常可以进入回滚分支，但进程被强杀、宿主机掉电或文件系统异常可能绕过回滚，使正式 Raw 留下部分
频率已替换、部分频率未替换的状态。保留分支必须用逐文件 old/new fingerprint、promote checkpoint、
重入时状态判定和幂等续跑替代“移动旧文件后整体回滚”的假原子语义。

最终实现矩阵：

| 能力 | 代码处理 | Catalog 五个 Raw entry | 验收 |
|---|---|---|---|
| 单日全市场五频 prod-DB 恢复 | 报告/candidate/checkpoint 全迁到 `DEFAULT_LAKE_STAGING_ROOT` 下专属 plan root；按 candidate → audit → checkpointed promote 重写；每个频率冻结 old/new fingerprint，并记录 `pending/promoted/verified` 状态；删除正式根 quarantine/backup 和整体回滚设计，不留兼容路径 | ingestion 保留 `TUSHARE_API`、`PROD_DB_READONLY`；`bootstrap_sources=(PROD_DB_READONLY,)` | plan 零正式写入；candidate/audit 不写正式根；中断后按 fingerprint 判定已提升项并幂等续跑；五频全部 `verified` 才成功；失败不靠备份恢复；正式根不产生 `_staging/_quarantine` |

#### 6.4.1 恢复 run 目录与 checkpoint 合同

新增 `stk_mins_raw_recovery_run_root(...)` 路径 helper，固定布局为：

```text
/Volumes/datasource/data_lake_staging/
  recovery/stk_mins_raw_replace_from_prod/
    trade_date=YYYY-MM-DD/
      recovery_run_id=<uuid>/
        plan.json
        checkpoint.json
        final-report.json
        candidates/freq=1/part-000.parquet
        candidates/freq=5/part-000.parquet
        candidates/freq=15/part-000.parquet
        candidates/freq=30/part-000.parquet
        candidates/freq=60/part-000.parquet
        audits/freq=1.json
        ...
```

`lake_root` 必须规范化后严格等于 `DEFAULT_LAKE_ROOT`，`staging_root` 必须严格等于
`DEFAULT_LAKE_STAGING_ROOT`；两者和五个目标父目录必须在同一文件系统，任一 `st_dev` 不一致立即停止。
CLI 保留 `plan/apply` 两阶段和原有业务参数，但新增 `--staging-root` / `--recovery-run-id`；`--output`、
`--plan-report` 若提供，必须解析到本次 recovery run root 内。旧的 `/private/tmp` 默认输出属于批准的
安全差异，改为上述 run root，不保留双路径兼容。

`checkpoint.json` 至少包含：

```text
schema_version
recovery_kind
trade_date
recovery_run_id
plan_fingerprint
expected_code_count / expected_code_hash
source_task_run_id
phase = planned | candidates_verified | promoting | completed | failed
frequencies[1|5|15|30|60]:
  target_path
  approved_old_sha256 / approved_old_size_bytes
  candidate_path / candidate_sha256 / candidate_size_bytes / candidate_row_count
  state = pending | promoted | verified
  promoted_at / verified_at / failure_code
```

`plan.json`、`checkpoint.json` 和 `final-report.json` 均通过同目录临时 JSON、flush/fsync、`os.replace()`
更新，禁止直接覆盖半写文件。candidate 写完后复用当前 schema/key/date/freq/code/time/row 全套校验，
并冻结 candidate fingerprint；所有 candidate 验证通过前不得改正式 Raw。

#### 6.4.2 首次 apply 与中断重入状态机

首次进入 promote 前重新读取 source facts、stock code set 和五个 target fingerprint，要求全部与
`plan.json` 一致，然后将 checkpoint phase 原子更新为 `promoting`。每个频率依次执行：

1. target hash 必须等于 `approved_old_sha256`，candidate hash 必须等于 `candidate_sha256`。
2. 对单文件执行 `os.replace(candidate, target)`。
3. 把该频率 checkpoint 原子更新为 `promoted`，随后立即重新读取 target；只有
   hash/size/schema/key/date/freq/code/time/row 全部等于 candidate audit，才更新为 `verified`。即使进程在
   `os.replace` 和 `promoted` checkpoint 之间退出，重入也能通过 target=candidate hash 识别已提升状态。
4. 五个频率全部 `verified` 后才写 `phase=completed` 和 `final-report.json`；在此之前 CLI 必须返回非成功。

同一 `recovery_run_id` 再次执行 `apply` 视为幂等重入，不重新创建计划：

| 当前 target/candidate 状态 | 重入动作 |
|---|---|
| target=approved old，candidate=approved candidate，state=pending | 继续 promote |
| target=approved candidate，state=promoted/verified | 重新做完整 target audit；通过后记 `verified` |
| target 既不等于 approved old 也不等于 candidate | `target_drift`，停止，不覆盖 |
| candidate fingerprint 变化或丢失且该频率尚未提升 | `candidate_drift`，停止，必须新建 plan/run |
| checkpoint/plan fingerprint、trade_date、run_id 不一致 | `checkpoint_identity_mismatch`，停止 |

中断重入时不能照搬现有“重新生成包含五个 target hash 的 plan 再比较”逻辑，因为部分 target 已合法
变成 candidate hash；必须按上表逐频率判定。工具不再提供 backup rollback：失败后的唯一动作是修复
外部阻断并用同一 run 幂等续跑，或在任何频率尚未 promote 时废弃该 run 并重新 plan。已发生部分
promote 后禁止创建第二个 run 覆盖现场。

#### 6.4.3 并发和可见性门禁

该工具继续保持 non-active、人工离线恢复定位。并发保护只解决一个具体问题：恢复五频文件期间，不能
让第二个入口同时写同一交易日。它不新增 lock/pid 文件，也不引入常驻协调服务；上一版 run-root 排它锁
只能挡第二个 recovery CLI、挡不住 Dagster/repair writer，并与“禁止自造锁文件”规则冲突，现已删除。

最终门禁分两层：

1. **代码内门禁**：同一 `trade_date` 存在未完成 checkpoint 时，禁止创建新的 `recovery_run_id`；只能用
   原 run id 按第 6.4.2 节续跑。这个判断复用恢复状态，不另建锁文件。
2. **执行前运营门禁**：人工 apply 前进入明确维护窗口，暂停或禁止可能写同日期的 stk_mins 日常、
   repair、history 和手动入口，并只读确认没有同日期 running/queued run。该确认不要求恢复 CLI 连接
   Dagster instance；正式执行时由独立 preflight/运营检查完成，结束五频验证后再恢复入口。

由于五个文件不存在组级原子提交，LLD明确接受“中断后靠 checkpoint 续跑”，不宣称五频原子；全部
`verified` 前不得运行 `reuse_existing` 记录 materialization/check，也不得把结果标为恢复成功。测试必须
覆盖第 6.4.2 节每个状态组合、同日期第二个 run 拒绝、同 run 两次 apply、进程在第 1–5 个频率后中断、
target 漂移、candidate 漂移、checkpoint 半写保护和跨文件系统拒绝。

#### 6.4.4 M4 性能预算与拒绝门禁

这里的性能门禁只约束 `stk_mins_raw_replace_from_prod` 的单日五频恢复，不涉及 Ops Dataset Status
Snapshot、freshness 页面或普通 API 查询。M4 的旧适配器删除本身没有大数据性能问题；需要预算的是
M4 前半段“从 prod DB 导出五频候选并审计”的离线数据处理。

| 项 | 冻结预算与实现要求 |
|---|---|
| 目标范围 | 一次只允许 1 个 `trade_date`、5 个频率、5 个正式 target 和 5 个 candidate；禁止扩成日期区间或全历史 |
| 读取模型 | plan：1 次本地 stock code set scan、最多 20 条 TaskRun 候选、1 次五频聚合身份查询、5 个 target SHA-256；apply：5 次按日期/频率有界的 prod 全量导出 |
| 样本基线 | 2026-07-27：5,533 个预期代码、27,665 个代码频率组合、1,776,093 行、五个 Raw 文件约 42.5 MiB；历史 apply 为 109.973 秒 |
| 计算与写入 | DuckDB/数据库流式或集合式导出；禁止 Python 明细行循环；写 5 个 candidate、5 份 audit 和小型 JSON plan/checkpoint/report；不写业务数据库和 Dagster event |
| 内存与临时空间 | 复用统一 DuckDB 配置；candidate 全部位于 `DEFAULT_LAKE_STAGING_ROOT`；开始生成前可用空间必须不少于 plan 估算 candidate 总字节数的 2 倍 |
| 时间上限 | 五个 candidate 生成加完整 audit 预算 5 分钟；约为历史 109.973 秒样本的 2.7 倍余量 |
| 拒绝条件 | 日期数不等于 1、频率/文件数不等于 5、查询失去日期/频率边界、候选行数或字节数超过 plan 上界、空间不足、跨文件系统，或生成加 audit 超过 5 分钟，均在正式 promote 前以 `performance_budget_exceeded` 停止 |

这个门禁不是拿速度代替正确性，也不是为了优化页面；它只防止实现退化成逐股票查询、Python 明细循环
或无界全表扫描。候选即使已经生成，只要超预算也保留在 staging 供审计，不触碰正式 Raw。

M4 必须先完成并验收恢复工具重构，再写入五个 catalog entry 的最终值；不得先把当前不合规实现描述为
正式可用，也不得在清退中删除该恢复能力。

### 6.5 当前 asset metadata 与说明文字

#### `assets/stk_mins.py`

当前 `_raw_stk_mins_extra_metadata` 的：

```python
"bootstrap_source": "backup_clean_next"
```

仍把已经清退的 backup 当作当前可用来源。先删除该过时字段。第 6.4 节恢复工具新链验收通过后，
才可新增与真实入口一致的稳定字段，例如：

```python
"historical_repair_source": "prod_db_raw_tushare"
```

五个 Raw asset description 中“历史基线来自 clean_next”改为：

1. 既有正式分区继续作为已提升的历史事实保留。
2. 当前日常来源按代码事实描述为正式生产库只读/Tushare；受控历史修复按第 6.4 节重构后的真实
   合同描述，不能把尚未合规的旧实现写成当前能力。
3. 当前 asset definition 不再携带旧 backup/old lake 的正向来源说明；历史 provenance 只留在现行迁移
   总账和既有 event 中。

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

先执行第 4.2.6 节 21 个命令的 old/new 双跑和冻结 fixture 对账，再执行每个新 CLI 的模块级测试。
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
11. fixture 中 side-effect 分类与目标 function 一致；read-only 命令不得触发 writer/event fake。
12. 旧 CLI 删除后，新 CLI 对冻结 fixture 继续全绿；测试不得 import tombstone module。

### 7.4 Static gate 修改

`test_run_contract_static_gates.py` 精准修改：

1. 删除 `BACKEND_DIR` 常量。
2. active source roots 从 `(DEFS_DIR, BACKEND_DIR / "app")` 收敛为 `DEFS_DIR`。
3. MACD/KDJ rebuild 命令和 `--confirm-rebuild` 的源码检查改读新 MACD/KDJ CLI。
4. canonical unsafe command 的负向检查改读 canonical CLI。
5. 删除对旧 backend 两个 derived service 文件的 removed-path 断言；目录本身已被 Git 删除，不再把不存在的旧产品文件当 current gate。
6. 保留对当前 defs 中 legacy derived symbol 的负向扫描。
7. 增加旧运行契约正向使用清零 gate，但允许现行迁移总账、既有 event 说明和禁止性测试中出现字符串。

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

其中第 1–3 项不是“保险性保留”，而是已核到页面的当前调用链：

| 当前 Reader | Biz/API 消费者 | HTTP 合同 | Wealth 页面/功能 | 正式数据路径 |
|---|---|---|---|---|
| `stock_mins_reader.py` | `StockMinuteQueryService`、`stock_detail_minutes.py` | `/api/v1/wealth/market/stock-detail/minutes`、`minute-indicators` | `/wealth/market/stock/{tsCode}` 的 1/5/15/30/60/90/120 分钟 K 线和技术指标 | `gold/quote/stk_mins_qfq`、`gold/indicator/stk_mins_qfq_macd_kdj` |
| `stock_nine_turn_reader.py` | `StockMinuteNineTurnQueryService`、`stock_detail_minute_nine_turn.py` | `/api/v1/wealth/market/stock-detail/minute-nine-turn` | 股票详情分钟九转叠加层/技术摘要 | `gold/quote/stk_mins_qfq`、`gold/indicator/stk_mins_qfq_nineturn` |
| `major_index_mins_reader.py` | `IndexDetailMinutesQueryService`、`index_detail_minutes.py` | `/api/v1/wealth/market/index-detail/minutes`、`minute-indicators` | `/wealth/market/index/{tsCode}` 的分钟 K 线和技术指标 | `gold/quote/major_index_mins`、`gold/indicator/major_index_mins_technical` |
| `index_nine_turn_reader.py` | `IndexMinuteNineTurnQueryService`、`index_detail_minute_nine_turn.py` | `/api/v1/wealth/market/index-detail/minute-nine-turn` | 指数详情分钟九转叠加层/技术摘要 | `gold/quote/major_index_mins`、`gold/indicator/major_index_mins_nineturn` |

路由装配位于 `src/app/api/v1/router.py::_include_local_minute_router(...)`，必须同时满足：

```text
APP_ENV in {dev, local}
WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED=true
GOLDENSHARE_LAKE_ROOT 可读
```

指数分钟 capability 和两类九转 capability 还要求根路径精确等于 `/Volumes/datasource/data_lake`。
普通股票分钟的 `resolve_local_minute_capability` / `StockMinsLakeReader` 当前只要求配置根可读并保证
派生路径不越界，没有同等的正式根精确检查；这是后续配置治理风险，不是本专项删除目标，也不授权
读取/修改 ignored 配置。前端股票页在
`supportsMinute=true` 且切换分钟周期时并行请求 bars/indicators；指数页的 `useIndexMinuteSeries` 还显式
要求 `import.meta.env.DEV`；九转 API client 在 period 不是 `day` 时改走 `minute-nine-turn`。

因此旧 Console 删除回归必须至少覆盖：

1. `src/foundation/config/local_minute_capability.py` 和 `Settings` 两个配置字段保留。
2. 上述四个 Reader、四组 Biz API/query service 和 app router 条件挂载保留。
3. `wealth/src/pages/stock-detail/StockDetailPage.tsx`、`IndexDetailPage.tsx` 及三个 API client 的请求合同不变。
4. `tests/test_*mins_reader.py`、四个 Web API 测试和 Wealth 两个详情页/分钟 controller 测试通过。
5. 根 `pyproject.toml` 的 `local-lake` DuckDB optional dependency 保留。

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

### 9.4 文档逐文件处理矩阵

处理码：

| 处理码 | 含义 |
|---|---|
| `DELETE_AFTER_MIGRATION` | 先迁移有效内容/引用，再删除文件 |
| `MODIFY_CURRENT` | 当前权威文档，改成清退后事实，不能加“整篇历史”标记 |
| `MODIFY_MIXED` | 同一文件含当前生产事实和旧 Console 事实，只修旧段落、链接和时态 |
| `DELETE_LEGACY_DOC` | 纯旧产品文档；必要结果先压缩进现行总账/设计，现行引用清零后从当前工作树删除；全文只经 Git 历史追溯，不建 archive/tombstone |
| `KEEP_CURRENT_VERIFY` | 已指向正式模板或当前代码，仅作为防误删验收，不改业务内容 |

上一版矩阵的遗漏原因已经确认：只做了“待删旧文档入链”扫描，没有再用待删运行符号和旧路径反扫
全部 tracked 文本文件。因此，不链接86份旧文档、却直接描述 `BootstrapDatasetSpec`、
`old_lake_bootstrap`、旧 backend 或 Raw recovery 旧路径的现行文档没有进入候选集。

矩阵现在由三份机器可复跑的候选清单交叉生成：

1. 86 份待删文档、三个待删模板、旧 frontend/backend 路径的反向引用清单。
2. `OLD_LAKE_BOOTSTRAP|old_lake_root|BootstrapDatasetSpec|BootstrapSourceMethod|old_lake_executor`、
   Kopia、旧物理湖路径、`lake_console/backend|frontend`、`stk_mins_raw_replace_from_prod`、旧
   `_staging/_quarantine` 口径的全仓 tracked 文本命中清单。
3. 本表路径存在性、唯一性和处理码计数清单。

`lake_console/backend/**`、`lake_console/frontend/**`、`lake_console/config.local.example.toml` 等位于263个
旧产品直接删除边界内的 AGENTS、skills、说明和配置，由精确 Git 删除白名单整体覆盖，不在本表重复列。
除此之外，每个命中文件都必须有一行处理码；仅包含“禁止 Kopia/旧湖”的当前文档也登记为
`KEEP_CURRENT_VERIFY`，不再静默排除。

本矩阵共 143 份文件：3 份迁移后删除、31 份现行文档修改、10 份混合文档局部修改、86 份纯旧文档
删除、13 份现行文档只验证。86 份删除目标全部逐文件列名；任何新增发现必须先补矩阵，禁止扩大目录级
删除范围。实施 M0、M5 和 M7 均要求三份候选清单的未归类命中、重复路径和不存在路径为 0。

#### 9.4.1 当前规则、索引、模板和正式 Dagster 文档

| 文件 | 处理码 | 精确修改 |
|---|---|---|
| `AGENTS.md` | `MODIFY_CURRENT` | M6 原子删除后把“旧 backend 现存冻结证据”改为“代码已清退、禁止恢复”；保留正式 Lake 路径和 Kopia 禁令 |
| `lake_console/AGENTS.md` | `MODIFY_CURRENT` | 删除旧 frontend/backend/CLI/配置开发规则；只保留 orchestrator/docs/reports/ClickHouse bin 边界 |
| `lake_console/orchestrator/AGENTS.md` | `MODIFY_CURRENT` | 删除旧湖作为允许 bootstrap source；保留旧根拒绝和正式 staging 规则 |
| `lake_console/orchestrator/CODING_STANDARDS.md` | `MODIFY_CURRENT` | 删除 old-lake 正向 metadata 示例；改成禁止恢复已删模块和来源无关 provenance |
| `scripts/AGENTS.md` | `MODIFY_CURRENT` | 删除 `local-lake-console.sh` 启动规则，保留其他脚本边界 |
| `.agents/skills/frontend-qa/SKILL.md` | `MODIFY_CURRENT` | 删除 `lake_console/frontend` scope/build/QA；保留根 frontend 与 Wealth QA |
| `.agents/skills/lake-dataset-onboarding/SKILL.md` | `MODIFY_CURRENT` | 只指向正式 Dagster onboarding 模板，不再路由到旧 templates |
| `docs/README.md` | `MODIFY_CURRENT` | 从现行索引删除两份旧模板和旧 Console 入口；新增/保留正式 Dagster onboarding 入口 |
| `lake_console/README.md` | `MODIFY_CURRENT` | 重写为 orchestrator/docs/reports/保留 bin 索引；删除旧端口、Vite/FastAPI、旧 root 和 Kopia 操作 |
| `docs/architecture/codegraph-architecture-snapshot.md` | `MODIFY_CURRENT` | 删除旧 Console 节点和 old-lake adapter 边；加入四个当前 stk_mins CLI 与 Wealth formal-Lake Reader 保护边界 |
| `docs/architecture/goldenshare-repository-onboarding-overview-v1.html` | `MODIFY_CURRENT` | S0 删除旧 Console 作为当前产品；明确 `lake_console` 现行内容和 `src/foundation/clients/local_lake` 当前用途 |
| `lake_console/docs/templates/dagster-dataset-onboarding-template.html` | `MODIFY_CURRENT` | 吸收旧模板有效源端/性能/原子写/smoke 检查；删除 old-lake bootstrap 正向章节 |
| `lake_console/docs/design/dagster-data-pipeline-performance-governance.md` | `MODIFY_CURRENT` | 补 prod DB 只读白名单、显式投影、绑定、流式读取、预算和行数对账；由正式模板引用 |
| `lake_console/docs/architecture/dagster-data-system-architecture.html` | `MODIFY_CURRENT` | 删除 `KopiaResource` 和旧湖迁移执行面；保留历史注记、正式 staging/candidate/promote |
| `lake_console/docs/design/dagster-run-contract-governance.html` | `MODIFY_CURRENT` | 删除 `OLD_LAKE_BOOTSTRAP` 当前 enum/producer 合同；历史 event metadata 说明改为只读历史字符串 |
| `lake_console/docs/design/dagster-new-lake-asset-catalog-design.md` | `MODIFY_CURRENT` | 逐项改 17 个 catalog 来源；Raw stk_mins 五项固定为 prod-DB 恢复来源，并声明工具已按第 6.4 节完成合规重构后才可用 |
| `lake_console/docs/design/dagster-bootstrap-legacy-links.md` | `MODIFY_CURRENT` | 收敛为唯一历史迁移结果总账；标记 executable adapter 已删除、物理旧湖待独立审计、不可执行；吸收 clean_next 重建/修复/代码集合审计的最小数字和结论，不复制旧命令 |
| `lake_console/docs/design/dagster-index-mins-data-onboarding-plan.md` | `MODIFY_CURRENT` | 删除旧 `lake-dataset-development-template.md` 依据，只保留正式 Dagster onboarding/性能/源文档 |
| `lake_console/docs/design/dagster-major-index-mins-data-onboarding-plan.md` | `MODIFY_CURRENT` | 同上 |
| `docs/datasets/major-index-mins-dataset-development.md` | `MODIFY_CURRENT` | 当前正式 Dagster 数据集说明；只移除旧模板引用，保留正式模板和数据集事实 |
| `lake_console/docs/design/dagster-stk-nineturn-dataset-onboarding-plan.md` | `KEEP_CURRENT_VERIFY` | 已走正式模板；确认不引入旧模板/旧 root |
| `lake_console/docs/design/dagster-stk-nineturn-dataset-onboarding-low-level-design.md` | `KEEP_CURRENT_VERIFY` | 同上 |
| `lake_console/docs/design/dagster-index-daily-000680-history-supplement-low-level-design.md` | `KEEP_CURRENT_VERIFY` | 当前正式历史补录；确认 source/staging 不依赖旧湖 |
| `docs/governance/engineering-risk-register.md` | `MODIFY_MIXED` | 保留当时 py_compile/pytest 命令为历史证据；对应风险状态改为旧实现已随产品清退，不再列当前入口 |
| `docs/governance/docs-information-architecture-v1.md` | `MODIFY_CURRENT` | 把“旧 Local Lake 文档保留追溯”改为“已从当前工作树删除，必要摘要见单一总账，全文走 Git 历史” |
| `docs/governance/prod-postgresql-raw-direct-serving-phase-one-lld-v1.md` | `MODIFY_MIXED` | 保留生产 PostgreSQL 当前设计；把旧 backend mapping 标为历史审计参照，去掉当前消费者含义 |
| `lake_console/docs/design/dagster-index-daily-raw-by-date-prod-db-migration-plan.md` | `MODIFY_MIXED` | 保留 Dagster 当前方案；旧 backend service 只保留为当时字段口径证据，不可链接为实现依赖 |
| `lake_console/docs/design/dagster-index-daily-raw-by-date-prod-db-migration-low-level-design.md` | `MODIFY_MIXED` | 同上；删除/转文本旧 backend 代码链接 |
| `lake_console/docs/design/dagster-derived-minute-bars-90-120-contract-rebuild-low-level-design.md` | `MODIFY_MIXED` | 把待删除旧算法 producer 更新为已清退事实；保留正式 Dagster 算法和验收记录 |
| `docs/datasets/index-wave4-trend-reversal-backtest-plan-v1.md` | `MODIFY_CURRENT` | 删除旧 index-mins/indicator/MACD 文档引用，改指正式 major-index 分钟接入、canonical bars 和现行 MACD/KDJ Dagster 设计 |
| `lake_console/docs/design/dagster-stk-mins-asset-design.html` | `MODIFY_CURRENT` | 删除 clean_next 代码集合审计原文链接；保留已写入本文的停牌/身份映射/非 strict equality 正式语义，并改引历史迁移总账 |
| `lake_console/docs/design/dagster-stk-mins-qfq-macd-kdj-indicators-plan.md` | `MODIFY_CURRENT` | 删除两个旧指标文档引用；当前递推、性能和验收只以本文及 canonical bars LLD 为准 |
| `lake_console/docs/design/dagster-etf-market-data-prod-db-onboarding-plan-v1.md` | `MODIFY_CURRENT` | 删除旧 etf-basic Console 导出方案引用和历史依据段；保留当前 source docs、正式 Dagster 方案与代码证据 |
| `lake_console/docs/design/dagster-phase-2-design.html` | `MODIFY_CURRENT` | 删除旧 suspend-d Console 导出方案引用；保留 Tushare source docs、实测记录和当前 Dagster 契约 |
| `lake_console/docs/design/dagster-phase-2-low-level-design.html` | `MODIFY_MIXED` | 保留第二期已发生的迁移结果；删除“generic old-lake spec/executor 长期保留并复用”的当前设计，明确 executable adapter 已退役、历史 metadata 只读保留 |
| `lake_console/docs/design/dagster-stock-limit-assets-design.md` | `MODIFY_CURRENT` | 尚未开发的现行方案不得再计划从物理旧湖 bootstrap；保留旧湖审计为历史证据，实施前重新审计 prod DB/Tushare 的完整历史来源并重做初始化预算 |
| `lake_console/docs/design/dagster-adj-factor-asset-design.md` | `MODIFY_MIXED` | 保留 M5/M6 已发生的旧湖迁移、行数和 event 记录；删除当前代码依据中的 generic bootstrap 可用性和可执行 spec 表述，明确后续不再复用旧适配器 |
| `lake_console/docs/design/dagster-namechange-asset-design.md` | `KEEP_CURRENT_VERIFY` | 旧湖只作为已明确的历史只读审计证据，正式来源是 Tushare；确认不新增旧湖执行入口即可，不改历史数字 |
| `lake_console/docs/design/dagster-stk-mins-prod-task-run-readiness-low-level-design.md` | `MODIFY_MIXED` | 保留 2026-07-27 事故、109.973秒、1,776,093行和历史 quarantine 执行证据；当前恢复实现改指第6.4节正式 staging/checkpoint/无backup合同，不继续把旧路径写成现行方案 |
| `wealth/docs/pages/stock-detail/stock-detail-minutes-api-implementation-design-v1.md` | `MODIFY_CURRENT` | 保留“不依赖旧 backend”的边界；M6 后把“是本地管理台”改为“已清退的旧管理台”，避免把已删产品写成当前存在 |
| `wealth/docs/pages/stock-detail/stock-detail-minutes-api-benchmark-requirement-v1.md` | `MODIFY_CURRENT` | 保留性能合同和不导入旧 router 的负向门禁；M6 后更新旧 backend 时态 |
| `wealth/docs/pages/stock-detail/stock-detail-minutes-api-low-level-design-v1.md` | `MODIFY_CURRENT` | 保留 Foundation Reader/Biz API/Wealth 页面当前链；M6 后把旧 backend 行改为已清退且禁止恢复 |
| `wealth/docs/pages/stock-detail/stock-detail-minutes-api-m2-coding-gate-v1.md` | `MODIFY_CURRENT` | 保留既有验收结论；M6 后把“没有作为生产 API”更新为“已清退且生产链未曾依赖” |
| `docs/architecture/etf-basic-rebuild-and-downstream-data-audit-cleanup-plan-v1.md` | `KEEP_CURRENT_VERIFY` | 仅包含“不引入 Kopia/不使用旧 Lake 备份”的当前禁止项，必须保留，不参与本专项修改 |
| `lake_console/docs/design/dagster-cn-a-minute-gold-canonical-bars-rebuild-low-level-design.md` | `KEEP_CURRENT_VERIFY` | 仅包含无 Kopia、正式 staging/checkpoint 的当前安全合同，确认不受清退影响 |
| `lake_console/docs/design/dagster-gold-wealth-market-turnover-dataset-design.md` | `KEEP_CURRENT_VERIFY` | 仅包含无 Kopia/无正式根 staging 的当前门禁，保留不改 |
| `lake_console/docs/design/dagster-gold-wealth-market-turnover-dataset-low-level-design.md` | `KEEP_CURRENT_VERIFY` | 同上；历史执行数字和当前 staging 合同均不依赖旧 Console |
| `lake_console/docs/design/dagster-stock-qfq-nineturn-dataset-plan.md` | `KEEP_CURRENT_VERIFY` | 仅记录执行未使用 Kopia/旧湖，保留为现行负向证据 |
| `wealth/docs/pages/market-overview/sector-overview-low-level-design-v2.md` | `KEEP_CURRENT_VERIFY` | 只声明不新增 Kopia/旧湖路径，保留当前禁止项 |
| `wealth/docs/pages/market-overview/sector-overview-m2-coding-gate-v2.md` | `KEEP_CURRENT_VERIFY` | 只记录 Heat 链无 Kopia的验收事实，不受本专项删除影响 |
| `wealth/docs/system/detail-page-nine-turn-integration-implementation-design-v1.md` | `KEEP_CURRENT_VERIFY` | 只记录分钟九转执行未使用 migration/Kopia，保留历史执行证据 |
| `wealth/docs/system/detail-page-nine-turn-integration-low-level-design-v1.md` | `KEEP_CURRENT_VERIFY` | 只包含禁止旧 Lake/Kopia及正式 staging/checkpoint合同，保留不改 |
| `docs/templates/lake-dataset-development-template.md` | `DELETE_AFTER_MIGRATION` | 有效检查迁入正式模板后删除，不留 tombstone |
| `docs/templates/lake-prod-raw-db-export-template.md` | `DELETE_AFTER_MIGRATION` | 有效只读/流式约束迁入性能治理后删除，不留 tombstone |
| `lake_console/docs/templates/dagster-bootstrap-migration-template.html` | `DELETE_AFTER_MIGRATION` | 旧湖→新湖执行模板直接删除；历史总账承接追溯 |

#### 9.4.2 `docs/architecture/local-lake-*` 旧产品文档

以下 25 份均只描述待删除的旧 Console/Kopia 产品或其页面、API、CLI、模型和性能方案，没有当前
运行契约。逐文件核验后，不再采用“退出索引但保留全文”；必要引用先清零，然后按精确 pathspec 删除。

| 文件 | 处理码 | 精确修改 |
|---|---|---|
| `local-lake-cli-planner-engine-refactor-plan-v1.md` | `DELETE_LEGACY_DOC` | 删除；只设计旧 CLI/Planner/Engine，现行 CLI 合同已由第 4.2 节和正式 Dagster CLI 承接 |
| `local-lake-command-examples-page-plan-v1.md` | `DELETE_LEGACY_DOC` | 删除；页面和全部命令入口随旧 frontend/backend 清退 |
| `local-lake-console-architecture-plan-v1.md` | `DELETE_LEGACY_DOC` | 删除；旧产品架构由本专项边界和 Git 历史替代，不再作为必读 |
| `local-lake-console-data-model-map-v1.html` | `DELETE_LEGACY_DOC` | 删除；只展示待删 backend 模型，不承载正式 Dagster schema |
| `local-lake-console-dataset-model-v1.md` | `DELETE_LEGACY_DOC` | 删除；旧 Catalog/Planner 模型已退役，现行事实在 DatasetDefinition/Dagster catalog |
| `local-lake-console-management-roadmap-v1.md` | `DELETE_LEGACY_DOC` | 删除；路线对象整体退役，无未完成事项需迁移 |
| `local-lake-console-model-api-blocker-audit-v1.md` | `DELETE_LEGACY_DOC` | 删除；阻断项只针对待删 API/模型，清退后失去对象 |
| `local-lake-console-page-evolution-boundary-card-v1.md` | `DELETE_LEGACY_DOC` | 删除；只约束待删旧页面 |
| `local-lake-console-recovery-write-safety-page-design-v1.md` | `DELETE_LEGACY_DOC` | 删除；只描述待删 Kopia/recovery UI，正式写湖安全由性能治理和本 LLD 承接 |
| `local-lake-dataset-access-mode-checklist-v1.md` | `DELETE_LEGACY_DOC` | 删除；有效接入检查已迁正式 Dagster onboarding 模板 |
| `local-lake-dataset-inventory-overview-v1.html` | `DELETE_LEGACY_DOC` | 删除；库存来自旧 Console catalog，不能继续作为当前数据集清单 |
| `local-lake-dataset-sync-expansion-plan-v1.md` | `DELETE_LEGACY_DOC` | 删除；只规划旧产品扩展，未完成项不迁入正式主链 |
| `local-lake-duckdb-compute-benchmark-m05-2026-05-16.md` | `DELETE_LEGACY_DOC` | 删除；旧路径/旧实现点时 benchmark 不能约束当前 Dagster，现行性能证据在正式 LLD |
| `local-lake-kopia-prewrite-snapshot-aggregation-plan-v1.md` | `DELETE_LEGACY_DOC` | 删除；Kopia 方案与当前禁令直接冲突，不保留在当前工作树 |
| `local-lake-large-compute-foundation-design-v1.html` | `DELETE_LEGACY_DOC` | 删除；旧 compute shell/publish 设计随 backend 清退，通用 DuckDB 约束已迁正式治理 |
| `local-lake-prod-db-daily-sync-design-v1.html` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console 日更链，当前 prod-DB 读取由正式 Dagster 资源和 LLD 约束 |
| `local-lake-prod-db-event-date-sync-plan-v1.md` | `DELETE_LEGACY_DOC` | 删除；旧事件日期同步链不进入正式 Dagster |
| `local-lake-prod-db-sync-api-contract-v1.html` | `DELETE_LEGACY_DOC` | 删除；API 随旧 backend 清退，无当前消费者 |
| `local-lake-prod-db-sync-center-page-design-v1.html` | `DELETE_LEGACY_DOC` | 删除；页面随旧 frontend 清退，无当前消费者 |
| `local-lake-recovery-api-minimal-design-v1.md` | `DELETE_LEGACY_DOC` | 删除；旧 recovery API 随 backend/Kopia 清退 |
| `local-lake-stk-mins-sync-center-pipeline-plan-v1.md` | `DELETE_LEGACY_DOC` | 删除；旧 Sync Center 流水线不等于正式 stk_mins Dagster 链 |
| `local-lake-storage-cost-api-minimal-design-v1.md` | `DELETE_LEGACY_DOC` | 删除；旧 storage/cost API 无当前消费者 |
| `local-lake-storage-cost-page-boundary-card-v1.md` | `DELETE_LEGACY_DOC` | 删除；旧 storage/cost 页面无当前消费者 |
| `local-lake-sync-center-master-review-v1.md` | `DELETE_LEGACY_DOC` | 删除；审计对象整体清退，必要边界已并入本专项 |
| `local-lake-write-recovery-management-plan-v1.md` | `DELETE_LEGACY_DOC` | 删除；Kopia/旧恢复模型禁止继续作为当前参考；已发生风险摘要保留在 engineering risk register |

#### 9.4.3 旧 Console 数据集/导出/修复文档

以下 61 份均不再作为当前数据集或正式 Dagster 的事实源。五份旧接入说明、42 份旧 Console 导出方案
直接删除；14 份 `stk_mins` clean/indicator 文档中，仅把新湖 bootstrap provenance 必需的执行数字和
“停牌/身份映射不能做 strict equality”结论压缩进现行总账/设计，随后删除原文。

| 文件 | 处理码 | 额外精确修改 |
|---|---|---|
| `docs/datasets/daily-lake-dataset-development.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console daily 接入，当前生产与 Dagster 各有正式数据集文档 |
| `docs/datasets/index-basic-lake-dataset-development.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console index_basic 接入，无当前消费者 |
| `docs/datasets/moneyflow-lake-dataset-development.md` | `DELETE_LEGACY_DOC` | 删除；已明确是历史 Tushare 直连版，现行 moneyflow 事实在正式数据集定义/文档 |
| `docs/datasets/index-mins-dual-source-lake-plan-v1.md` | `DELETE_LEGACY_DOC` | 删除；旧双模式不属于当前 major/index Dagster 主链，研究文档改引正式接入 LLD |
| `docs/datasets/stk-mins-parquet-lake-plan-v1.md` | `DELETE_LEGACY_DOC` | 删除；旧 raw/clean_next/manifest 结构已退役；必要 baseline provenance 迁入 Dagster bootstrap 总账 |
| `docs/datasets/stk-mins-clean-2022-bj-freq30-repair-plan-v1.md` | `DELETE_LEGACY_DOC` | 摘录 115 日、161 代码、81,408→122,112 行、修复后 issue_count=0 到迁移总账后删除 |
| `docs/datasets/stk-mins-clean-20241030-multifreq-repair-plan-v1.md` | `DELETE_LEGACY_DOC` | 摘录四频受影响/重建行数和修复后 issue_count=0 到迁移总账后删除 |
| `docs/datasets/stk-mins-clean-cleaning-master-record-v1.md` | `DELETE_LEGACY_DOC` | 摘录历史 3,735 个严重低行数分区恢复及 clean baseline 规模到迁移总账后删除 |
| `docs/datasets/stk-mins-clean-next-rebuild-action-plan-v1.md` | `DELETE_LEGACY_DOC` | 摘录最终 schema、分区/行数和全量复审结论到迁移总账后删除；不迁旧命令/备份步骤 |
| `docs/datasets/stk-mins-clean-next-vs-silver-stock-daily-code-audit-v1.md` | `DELETE_LEGACY_DOC` | 把 strict equality 不成立、停牌与身份映射归因摘要并入现行 stk_mins 设计/迁移总账后删除 |
| `docs/datasets/stk-mins-clean-audit-gates-v1.html` | `DELETE_LEGACY_DOC` | 删除；旧 clean_next 门禁已由正式 Raw/Silver checks 和当前 LLD 替代 |
| `docs/datasets/stk-mins-indicator-development-guide-v1.md` | `DELETE_LEGACY_DOC` | 删除；现行指标合同、性能和安全门禁已完整写入 Dagster MACD/KDJ LLD |
| `docs/datasets/stk-mins-indicator-system-plan-v1.md` | `DELETE_LEGACY_DOC` | 删除；旧 indicator 路径/任务模型已退役，现行 Dagster 设计自足 |
| `docs/datasets/stk-mins-indicator-compute-stability-review-v1.html` | `DELETE_LEGACY_DOC` | 删除；旧实现 benchmark 不作当前门禁，现行 benchmark 已在 Dagster MACD/KDJ LLD 固化 |
| `docs/datasets/stk-mins-macd-v2-recompute-and-incremental-plan.md` | `DELETE_LEGACY_DOC` | 删除；当前递推 state、非 recursive 实现和 benchmark 已在 Dagster MACD/KDJ LLD 自足 |
| `docs/datasets/stk-mins-raw-to-clean-next-sync-pipeline-plan-v1.html` | `DELETE_LEGACY_DOC` | 删除；旧 raw→clean_next 产品链已退役 |
| `docs/datasets/stk-mins-raw-to-clean-next-sync-pipeline-technical-design-v1.html` | `DELETE_LEGACY_DOC` | 删除；旧技术实现随 backend 清退，不能当作 Raw→Silver 方案 |
| `docs/datasets/stk-mins-clean-next-qfq-candidate-publish-plan-v1.html` | `DELETE_LEGACY_DOC` | 删除；旧 candidate 发布模型不是当前正式 staging/promote 实现 |
| `docs/datasets/stk-mins-security-universe-filter-plan-v1.md` | `DELETE_LEGACY_DOC` | 删除；旧生命周期过滤实现已由正式 stock daily/suspend/identity-map 合同替代 |
| `docs/datasets/ths-daily-valuation-fields-rebuild-plan-v1.md` | `MODIFY_MIXED` | 保留生产 schema/DatasetDefinition 重建事实；仅把旧 Lake export 文件/测试链接改为历史文本并声明代码已清退 |
| `docs/datasets/stk-nineturn-prod-raw-db-lake-export-plan.md` | `MODIFY_MIXED` | 旧导出实现历史化；保留对当前 Dagster prod readonly 来源的事实说明但改指当前实现 |
| `docs/datasets/adj-factor-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；旧 Console 导出方案，当前 adj_factor 以正式 Dagster asset/source contract 为准 |
| `docs/datasets/bse-mapping-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；旧 Console 导出方案，当前身份映射以正式 asset/seed 设计为准 |
| `docs/datasets/cyq-perf-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/daily-basic-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/daily-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console daily 导出，现行生产/Dagster 文档独立存在 |
| `docs/datasets/dc-daily-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/dc-hot-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/dc-index-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/dc-member-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/etf-basic-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；未实施的旧产品方案；当前 ETF Dagster 方案删除其历史引用 |
| `docs/datasets/etf-index-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；未实施的旧产品方案，无需迁移 |
| `docs/datasets/fund-adj-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/fund-daily-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/hk-basic-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/index-daily-basic-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/index-daily-prod-core-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；旧 Console 导出方案，当前 Dagster prod-core source 由正式 LLD 承接 |
| `docs/datasets/index-monthly-prod-core-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；旧 Console 导出方案，当前 Dagster prod-core source 由正式 LLD 承接 |
| `docs/datasets/index-weekly-prod-core-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；旧 Console 导出方案，当前 Dagster prod-core source 由正式 LLD 承接 |
| `docs/datasets/kpl-concept-cons-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/kpl-list-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/limit-cpt-list-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/limit-list-d-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/limit-list-ths-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/limit-step-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/margin-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/moneyflow-family-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；旧 Console 6+1 导出方案，现行 moneyflow 定义/文档承接 |
| `docs/datasets/namechange-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；旧 manifest/current 导出实现退役，当前身份映射链承接 |
| `docs/datasets/st-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；旧 manifest/current 导出实现退役 |
| `docs/datasets/stk-factor-pro-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/stk-limit-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/stk-period-bar-adj-month-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/stk-period-bar-adj-week-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/stk-period-bar-month-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/stk-period-bar-week-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/stock-company-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/stock-st-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/suspend-d-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；旧 Console 导出方案；current phase-2 设计改引 source docs 和正式契约 |
| `docs/datasets/ths-daily-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；旧 Console 导出方案，不影响保留的 valuation fields 生产重建文档 |
| `docs/datasets/ths-hot-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |
| `docs/datasets/ths-index-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；未实施的旧产品方案，无需迁移 |
| `docs/datasets/ths-member-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；未实施的旧产品方案，无需迁移 |
| `docs/datasets/top-list-prod-raw-db-lake-export-plan.md` | `DELETE_LEGACY_DOC` | 删除；只描述旧 Console prod-raw-db 导出路径 |

矩阵执行完成后再跑全仓删除目标链接扫描；发现未列文件时必须先判断 `MODIFY_CURRENT`、
`MODIFY_MIXED` 或 `DELETE_LEGACY_DOC` 并补入本表，禁止临时批量替换。

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
orchestrator/defs/bootstrap/stk_mins_raw_replace_from_prod.py
orchestrator/defs/bootstrap/stk_mins_raw_replace_from_prod_cli.py
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
test_stk_mins_raw_replace_from_prod.py
tests/fixtures/stk_mins_history_cli_contract_v1.json
test_stk_mins_history_cli_contract_equivalence.py
test_run_contract_static_gates.py
catalog 相关测试文件
```

### 10.4 删除代码和测试

删除边界以第 6、7、8 章清单为准。实施时应由 Git 精确 pathspec 删除，禁止使用模糊 glob 触及整个 `lake_console/` 或整个 `bootstrap/`。

### 10.5 保留不改代码

```text
ops.dataset_status_snapshot 全链
stk_mins 当前 Raw/Silver/Gold asset keys 和 partitions
stk_mins BSE history recovery
canonical history CLI
candidate/audit/promote/checkpoint 实现
正式 ClickHouse resources/assets
lake_console/reports/**
本机 ignored 配置和目录
物理旧湖
```

`stk_mins_raw_replace_from_prod` 的模块/CLI 已进入 10.2，专属测试进入 10.3；它们必须按第 6.4 节重构，
不是“保留不改”，也不得在旧适配器清退时删除。

---

## 11. 实施分片与顺序

### M0：基线冻结

1. 记录 branch、HEAD、工作区状态和精确变更白名单。
2. `codegraph sync` 后确认索引 current。
3. 重新运行旧 source、old root、mixed CLI 和 backend import 的引用清单。
4. 重跑第 9.4 节三路文档候选清单，确认未归类命中、矩阵重复/不存在路径、待删文档现行入链均为 0。
5. 发现本文以外的当前消费者或文档命中时停止，不进入删除。

### M1：先迁当前 `stk_mins` helper

1. 新增 check-event helper。
2. 把四个当前 event 模块改用新 helper。
3. 把 Raw partition discovery/alignment 迁到 Silver history。
4. 更新对应测试并跑定向回归。
5. 此阶段不删旧 migration 文件，保证每一步可验证。

### M2A：当前 CLI 行为等价迁移

1. 新增 shared CLI contract、冻结 fixture 和 old/new 等价测试。
2. 分别新增 Silver、QFQ、QFQ derived、MACD/KDJ CLI。
3. 按第 4.2.6 节原样迁移 21 个当前命令；不混入参数加固。
4. 对 21 个命令逐个双跑 parser/dispatch/output/failure 合同；7 个旧命令只做不存在负例。
5. 双跑全绿后改为新 CLI 对冻结 fixture，更新全部现行 import/static gate。
6. 证明无当前消费者后删除 `stk_mins_migration_cli.py`，不留 alias。

### M2B：当前 CLI 安全加固

1. 只修改 Silver selector 歧义。
2. 只增加 MACD/KDJ baseline 单分区门禁。
3. 新增批准差异正反例；M2A fixture 其余字段必须不变。

### M3：删除旧 migration 主体

1. 证明 `stk_mins_migration.py` 只剩旧符号且所有当前 import 已清零。
2. 删除该文件及纯旧测试。
3. 运行当前 Silver/QFQ/derived/MACD/KDJ 全套定向测试。

### M4：重构 Raw 恢复工具并删除 generic old-lake adapter

1. 先按第 6.4 节重构 `stk_mins_raw_replace_from_prod`：candidate/report/checkpoint 迁正式 staging，删除
   正式根 `_staging/_quarantine` 和 backup，增加逐文件 fingerprint 状态机、重入判定和幂等续跑测试。
2. 恢复工具新链验收通过后，删除 source method、dataset spec、executor、specs 和 adj factor old event 模块。
3. 清理 bootstrap package exports。
4. 删除旧 SQL templates 和精准测试断言。
5. 修改 enum、17 个 catalog entry 和当前 metadata 说明；Raw 五项固定为
   `bootstrap_sources=(PROD_DB_READONLY,)`。
6. 不新增 lock/pid 文件；同日期未完成 checkpoint 只允许原 run id 续跑，正式 apply 走人工维护窗口。
7. 按第 6.4.4 节验证单日五频读取、文件、空间和 5 分钟预算，超预算必须停在 promote 前。
8. 运行恢复工具、catalog、run contract、asset/check contract 测试。

### M5：合并模板、收敛证据摘要并删除旧文档

1. 先把有效检查项写入正式模板和性能治理文档。
2. 把 14 份旧 `stk_mins` 文档中仍需追溯的 bootstrap/修复数字和数据语义压缩进现行迁移总账或正式
   stk_mins 设计；不复制旧命令、路径和执行步骤。
3. 更新 current/mixed 文档、README、onboarding、research 和 Dagster 设计中的全部引用。
4. 删除三个旧模板。
5. 按第 9.4.2–9.4.3 节精确删除 86 份纯旧 Console 文档，不创建 archive/tombstone。
6. 运行全仓文件名/路径反向引用扫描和文档完整性检查。

M5 不提前把仍存在的旧 Console 代码写成“已删除”；当前规则和 README 的最终事实在 M6 原子同步。

### M6：原子删除旧 Console/Kopia并同步当前规则

1. 精确删除旧 frontend/backend/tests/entrypoints/example config。
2. 同轮更新 AGENTS、CODING_STANDARDS、skills、README、当前架构图为清退后事实，并移除所有正向入口。
3. 保留 reports、正式 bin、orchestrator 和 ignored 环境。
4. 反查 Wealth `local_lake` 四 Reader/API/page 链和 optional dependency 未变。
5. 运行仓库引用清零 gate。

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

现行迁移总账、既有 event 迁移记录和禁止性 guard 可保留字符串；验证脚本必须区分运行代码与这些
受控历史证据。

### 12.2 Python 验证

1. 对全部新增/修改 Python 文件运行 formatter/linter。
2. 对 orchestrator package 运行 `compileall`。
3. 运行所有第 7 章定向测试。
4. 运行 catalog、metadata、asset column schema、DuckDB SQL contract 测试。
5. 运行 `test_run_contract_static_gates.py`。
6. 运行 orchestrator 全量 pytest。
7. 根 Python 定向运行 `test_stock_mins_reader.py`、`test_major_index_mins_reader.py`、
   `test_stock_nine_turn_reader.py`、`test_index_nine_turn_reader.py`、四个分钟 Web API tests。
8. Wealth 定向运行 `StockDetailPage.test.tsx`、`IndexDetailPage.test.tsx`、
   `useIndexMinuteSeries.test.tsx` 和九转 API/controller 相关测试，证明当前详情页请求合同未损坏。

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
4. 86 份旧文档在当前工作树中不存在，现行链接为 0；必要摘要可从现行迁移总账读取，完整原文可从
   Git 历史追溯。

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
- [ ] 21 个命令 old/new 等价对账和新 CLI 冻结 fixture 对账全部通过。
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
- [ ] Raw `stk_mins` 五个 entry 固定保留 `PROD_DB_READONLY` 恢复来源，不声明尚未完成重构的不合规入口。
- [ ] Raw 恢复工具已完成重构：`bootstrap_sources=(PROD_DB_READONLY,)`，candidate/audit/checkpoint 已迁
      正式 staging，逐文件状态可幂等续跑，正式根无 `_staging/_quarantine`。
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
- [ ] 第 9.4 节逐文件矩阵全部完成；current/mixed 文档未被误删，86 份 `DELETE_LEGACY_DOC` 文件在
      当前工作树清零，现行引用为 0，必要结果摘要已迁入现行总账/设计。
- [ ] Wealth `local_lake` 四 Reader、分钟 API、页面调用和 optional dependency 未被误删。
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

第 6.4 节 `stk_mins_raw_replace_from_prod` 已拍板为“保留能力、重构实现”：正式 staging、逐文件
fingerprint/checkpoint/verified 状态、幂等续跑和无 backup 恢复是实施硬门禁。86 份纯旧 Console 文档
已拍板从当前工作树删除，必要摘要迁入现行总账，全文只走 Git 历史。开始实施前不再需要业务口径
拍板，但仍需要用户单独授权进入 M0–M7 代码和文档删除执行。物理旧湖和 ignored 环境属于后续独立
专项，不在本 LLD 的实施、验收或回退范围内。
