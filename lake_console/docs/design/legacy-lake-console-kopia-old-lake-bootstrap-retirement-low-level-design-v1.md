# 旧 Lake Console、Kopia 与旧湖迁移适配器清退低层设计 v1

状态：2026-09-05 M1 已提交 `3007cc0e` / M2A 已提交 `0cc84004` / M2B 已提交 `e8e2abf9` / M3 已提交 `1b0deb63` / M4 已提交 `68f97744` / M5 已提交 `3ed4c6ca` / M6 已提交 `63be03af` / M7 技术验收通过，用户已要求按 11 文件白名单提交（见 §11 续轮收口） / 文档处置矩阵 165 份，专项控制文档另列 3 份 / 其余具体数据删除待确认

审计基线：`dev-interface`，`c232889858d6fe93a3224bf65d3cdb682e4382f0`（用户无关工作区改动不纳入本专项）

M0 复核基线：`dev-interface`，`66a21e854659f26826e8bc6ad2836d49eaf622fe`（核心清退代码边界与原审计基线一致；文档矩阵按当前 HEAD 复扫）

分支口径：用户已确认 `main` 无需在本专项实施前强制追平；实施基线只认当前 `dev-interface` 的记录
HEAD、CodeGraph 状态和精确文件白名单。

初审日期：2026-08-28；本次复审：2026-09-05，`dev-interface@10521877`（代码边界仍为 263 个旧产品文件）

物理用途审计补充：2026-09-05，`dev-interface@75af8445`；本次点时结果见 §16.4–16.8，不覆盖上文历史基线。

后续执行补充：2026-09-05 08:21–08:24 +08:00，核验时 HEAD 为 `dev-interface@ca625748`；
单项 backup 删除见 §16.9，报告用途复核见 §16.10。其他任务提交造成的 HEAD 推进不纳入本专项改动。

上位方案：[`legacy-lake-console-and-kopia-retirement-plan-v1.md`](/Users/congming/github/goldenshare/docs/architecture/legacy-lake-console-and-kopia-retirement-plan-v1.md)

**最新数据清退口径**：用户已确认只依据代码直接使用判断用途，取消完整性、日期范围、内容替代和历史
价值审计。执行规则见 §16.1，当前批量清单见 §16.14；此前物理审计中的待核内容差异、人工取证/副本
确认等不再作为前置项。M4 写湖安全与代码回归要求不变；数据审计本身不授权删除。当前 M7 回归、
正式 Definitions 与差异复核已通过，用户已要求按 11 文件白名单提交；阶段实施记录见 §11，不自动进入 M8。

> 本文是本专项的代码实施依据。上位方案负责说明为什么清退、清退边界和阶段顺序；本文负责说明每个混合文件、运行契约、CLI、测试和文档具体如何修改。若实施时当前代码已经偏离本文审计基线，必须先重新做 CodeGraph 和文本引用审计，不能机械套用本文行号。

---

## 0. 结论先行

本专项必须按阶段验收实施，不能把含有 `migration`、`bootstrap`、`snapshot`、`backup` 的文件按名字批量删除。
2026-08-28 M0 是历史基线，不代表后续新增文档和物理数据已经审计完。2026-09-05 新增 M8 数据范围见 §16。

本次代码审计得到五个关键结论：

1. `lake_console/backend/**`、`lake_console/frontend/**`、旧 Console 专属入口和 `tests/lake_console/**` 是封闭的旧产品边界，可以同轮原子删除。
2. 审计基线中 `stk_mins_migration.py` 和 `stk_mins_migration_cli.py` 是混合文件：旧湖/历史备份迁移能力要删除，但 Silver、QFQ、派生指标和 MACD/KDJ 历史治理能力必须保留。现已完成 M1 helper 迁出、M2A 四 CLI 拆分、M2B 门禁及 M3 旧 migration 主体删除；当前历史治理能力保留。各阶段分别验收，generic old-lake adapter 和恢复工具仍归 M4。
3. Raw `stk_mins` 的非 active 单日五频 prod-DB 恢复工具不属于旧湖/Kopia；用户已拍板保留业务能力
   并重构实现。它必须迁到正式 staging，改成逐文件 fingerprint/checkpoint/验证/幂等续跑，不能原样保留。
4. `ops.dataset_status_snapshot`、正式 Dagster、ClickHouse、DuckDB/Parquet、当前 Raw → Silver → Gold 派生、当前 runless event 治理均不在删除范围内。
5. 原拟历史化的 86 份纯旧 Console 文档从当前工作树删除；必要执行结果压缩进现行总账/设计，全文只
   通过 Git 历史追溯，不建立 archive 或 tombstone。

业务范围已明确，物理对象的用途审计尚未全部完成。当前轮次只审计和修改文档；本文自身不执行或授权
代码/旧文档删除、数据写入、Dagster event 写入或物理目录清理。M8 纳入专项，但必须独立按精确清单验收。

---

## 1. 目标、依据与硬边界

### 1.1 开发目标

实现后必须同时满足：

1. 仓库中不再提供 Kopia repository、snapshot、restore、prewrite backup 或 recovery 的正向能力。
2. 旧 `lake_console/frontend + backend` 及其专属入口、测试和示例配置的 Git 跟踪文件原子清零；不得为使本机目录消失而删除 ignored 依赖环境。
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
lake_console/orchestrator/**
lake_console/bin/lake-clickhouse-start
lake_console/bin/lake-prod-clickhouse-tunnel
src/foundation/clients/local_lake/**
src/foundation/config/local_minute_capability.py
ops.dataset_status_snapshot 及全部生产者/消费者
```

上述正式根及当前数据主链保留，不能整根清理。§16 单独列出的废弃恢复遗留文件和旧湖数据按用途审计，
不因位于某个根目录而一律保留或删除。`lake_console/reports` 有当前审计输出消费者，目录保留，具体旧
报告逐项判断。本机 ignored 依赖环境/配置仍另轮处理。旧湖仅允许为清退做只读用途审计，不能用作 DG 输入。

### 1.4 代码阶段与数据阶段的副作用边界

M0–M7 代码清退实施本身不得：

1. 执行 Kopia 命令。
2. 把物理旧湖用作数据管道输入、改写或顺手删除；只读清退用途审计允许，具体删除移到 M8。
3. 写正式 Lake、staging、数据库或 Dagster instance。
4. materialize asset、启动 backfill、注册动态分区或补报 runless event。
5. 删除 ignored 本机依赖环境、构建产物或 `lake_console/config.local.toml`；ignored 业务数据仍按 §16 判断，不能与依赖环境混为一类。

M8 只处理 §16 已证明无用的精确数据清单，不扩大到业务表、Dagster instance 或 ignored 依赖环境/配置。
所有阶段的代码、旧文档、物理数据删除均须用户事先确认具体清单；方案同意、审计授权或文档提交授权
不等于删除授权。清单新增或范围变化必须重新确认，不能因为表中已标为“可删”就自行执行。

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

本节旧行号对应删除前的审计基线，不表示原文件仍存在。M2A 已完成当前命令拆分及原文件删除，
实际新入口与验证见 §11 M2A；最终 selector/日期加固已按 §11 M2B 单独实施。

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
| `register-silver-partitions` | `--partition-keys`、`--all-from-silver-files`、日期范围 | `--all`、`--all-from-raw-files` | 自动发现只能来自 Silver，不能用 Raw 文件推断 Silver 分区 |
| `report-silver-events` | `--partition-keys`、`--all-from-silver-files`、日期范围 | `--all`、`--all-from-raw-files` | event 必须以已存在且审计通过的 Silver 文件为准 |
| `audit-silver-final` | `--start-date`、`--end-date` | 所有“all”别名 | 审计函数自身按日期范围规划 |

参数错误必须在进入文件扫描或 Dagster instance 访问前失败：不支持的 option、缺少必填参数沿用 argparse 的 `SystemExit(2)`；解析成功后的选择语义错误沿用 `ValueError`。错误文本必须只列该命令真正支持的选择器。

显式 keys 的排序、重复值、空串/空 tuple 和对合法文件 selector 的优先级保持 M2A 不变。
原 register 函数只注册传入的 keys，不审计文件存在性；M2B 不给显式 keys 新加物理审计。真正补事件仍经过原 report planner 的 Silver 文件审计，不能将“动态分区已注册”当作文件/检查已就绪。
`report-silver-events` 不传 selector 时仍传 `None`，其现有 planner 按日期范围发现 **Silver** 文件；不新增必填限制。
删除 `--all` 注册后还须在 dispatch 前拒绝该完整 token，避免 argparse 将它当成剩余文件 selector 的缩写。其它 option 的缩写行为不扩大修改。

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
3. 显式 `partition_keys` 若存在，规范化后只能包含请求的当天；不能利用其优先于日期范围的现有语义扩大范围。planner 返回后再次检查 `plan.selected_partition_keys` 恰好为该当天的一项。
4. `--dry-run` 也必须经过同样门禁，不能把 dry-run 当绕过方式。
5. CLI 的日期/显式 keys 校验位于实例获取前；公开 Python report 入口重复同一纯校验，防止绕过 CLI。最终 plan 检查位于 report 函数内部、planner 返回之后，文件审计、readiness 和 `_report_asset_partition_events` 之前。不能等 report 返回再检查，因为那时事件可能已经写入。
6. baseline event planner 只执行一次，不增加 CLI 预规划或新配置；原文件审计内部还会调用 history planner，因此底层 history planner 合计仍为两次，不将“一次 baseline 规划”误写成整条链只有一次扫描。共享只读 planner 和 final audit 继续支持多日。

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
| output | 当前 `print(...)` 的类型、dictionary key/嵌套 key 或 dataclass repr、返回值/exit code |
| side effect | `READ_ONLY`、`LAKE_WRITE`、`DAGSTER_WRITE` 三类；确认/`dry-run`/checkpoint 门禁发生时点 |
| failure | 缺必填参数、非法 choice、未确认、空 selector 时的异常类型和在目标 function 前失败的要求 |

M2A 测试方式：

1. 在旧 dispatcher 仍存在时，用同一 argv 分别调用旧入口和目标新入口。
2. patch 全部目标函数、Dagster instance、DuckDB/Lake writer 为记录调用的 fake；测试不得读写真实 Lake、
   数据库或 Dagster instance。
3. 对比 parser 后的规范化参数、被调 function、调用次数、args/kwargs、原始 stdout/打印对象类型和异常时点。
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
| MACD/KDJ baseline event | `start_date/end_date` 必填且相等，planner 只能返回请求当天一个 partition | 跨日、空/越界显式 keys 在实例访问前失败；零、多、错日期 plan 在文件审计和事件写入前失败；dry-run 同样执行门禁 |

除这两项外，任何差异都是回归，不得解释为“拆文件后的自然变化”。

### 4.3 Handler 输出契约

新 CLI 必须保留当前每个命令的打印类型和内容。20 个命令打印 dictionary，保留其 key；
`audit-silver-final` 实际直接 `print(StkMinsSilverFinalAuditReport)`，必须保留 dataclass repr，
不能按本节旧的概括改成 dictionary。不得在拆文件时统一成另一个输出 schema。

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
    partitions_by_freq: Mapping[int, tuple[str, ...]],
) -> None: ...
```

保持 fail-closed：任一频率多/少日期都失败，不自动取交集掩盖缺文件。

M1 开工复核：旧函数实际返回 `None`，日期 tuple 由调用方取得。上面的签名已按当前代码纠正，
不新增返回行为；比较基准、异常类型和异常文字均原样保留。

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

本章保留实施前证据及批准的目标合同；2026-09-05 M4 已完成代码实现与隔离回归，实际文件、测试和未执行边界见 §11。下面的旧模块、旧字段值和旧恢复流程不是当前可用入口；正式环境恢复未执行。

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

| 资产组 | 数量 | 实施前旧值 | 目标值（M4 已实现） | 代码事实 |
|---|---:|---|---|---|
| `silver_adj_factor` | 1 | `OLD_LAKE_BOOTSTRAP` | `DERIVED_FROM_ASSETS` | 当前 asset 依赖 Raw adj factor 和 lifecycle |
| Raw `stk_mins` 1/5/15/30/60m | 5 | ingestion 含 OLD；bootstrap 为 OLD | ingestion 保留 `TUSHARE_API`、`PROD_DB_READONLY`；`bootstrap_sources=(PROD_DB_READONLY,)` | 用户已拍板保留 prod-DB 单日五频恢复能力，但必须先完成正式 staging/checkpoint 重构 |
| Silver `stk_mins` 1/5/15/30/60m | 5 | OLD | `DERIVED_FROM_ASSETS` | 当前由五频 Raw 和参考数据生成 |
| native Gold QFQ 1/5/15/30/60m | 5 | OLD + DERIVED | 只保留 `DERIVED_FROM_ASSETS` | 当前由 Silver 和复权因子生成 |
| `silver_index_daily` | 1 | OLD | `DERIVED_FROM_ASSETS` | 当前读取同日 Raw index daily |

Raw `stk_mins` 工具的实施前代码事实（基线 `d2d177bb`，下列旧命令链只作历史说明）：

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

但旧实现 `_staging_root(...)` 解析到正式 Raw 树内 `raw/tushare/stk_mins/_staging/**`，
`_quarantine_root(...)` 解析到正式根 `_quarantine/**`，成功后 manifest 和五个 backup 文件长期保留。
这与根规则“候选只能在 `/Volumes/datasource/data_lake_staging`、正式根只允许 raw/silver/gold、不得以
文件备份/快照承担恢复”冲突。

此外，旧实现五次 `os.replace()` 仅各自保证单文件原子，五个频率之间没有文件系统事务。正常 Python
异常可以进入回滚分支，但进程被强杀、宿主机掉电或文件系统异常可能绕过回滚，使正式 Raw 留下部分
频率已替换、部分频率未替换的状态。保留分支必须用逐文件 old/new fingerprint、promote checkpoint、
重入时状态判定和幂等续跑替代“移动旧文件后整体回滚”的假原子语义。

最终实现矩阵：

| 能力 | 代码处理 | Catalog 五个 Raw entry | 验收 |
|---|---|---|---|
| 单日全市场五频 prod-DB 恢复 | 报告/candidate/checkpoint 全迁到 `DEFAULT_LAKE_STAGING_ROOT` 下专属 plan root；按 candidate → audit → checkpointed promote 重写；每个频率冻结 old/new fingerprint，并记录 `pending/promoted/verified` 状态；删除生成正式根 quarantine/backup 的代码和整体回滚分支，不留兼容路径 | ingestion 保留 `TUSHARE_API`、`PROD_DB_READONLY`；`bootstrap_sources=(PROD_DB_READONLY,)` | plan 零正式写入；candidate/audit 不写正式根；中断后按 fingerprint 判定已提升项并幂等续跑；五频全部 `verified` 才成功；失败不靠备份恢复；新流程不产生正式根 `_staging/_quarantine`，既有数据另按 M8 清单判断 |

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
phase = planned | candidates_verified | promoting | completed | failed | aborted_before_promote
failure_code / operator_action_required
frequencies[1|5|15|30|60]:
  target_path
  approved_old_sha256 / approved_old_size_bytes
  candidate_path / candidate_sha256 / candidate_size_bytes / candidate_row_count
  state = pending | promoted | verified
  promoted_at / verified_at / failure_code
```

`plan.json`、`checkpoint.json` 和 `final-report.json` 均通过同目录临时 JSON、flush/fsync、`os.replace()`
更新，并持久化父目录变更，禁止直接覆盖半写文件。candidate 写完后复用当前 schema/key/date/freq/code/time/row
全套校验，完成文件持久化并冻结 candidate fingerprint；所有 candidate 验证通过前不得改正式 Raw。
promote 也须持久化源/目标父目录的 rename 结果；平台无法满足持久化要求时不能承诺掉电恢复安全。

#### 6.4.2 首次 apply 与中断重入状态机

**问题归属**：2026-09-05 复审指出的“候选丢失要求新 run，但部分提升后又禁止新 run”，是本 LLD
当时尚未实施的设计矛盾，不是已上线 checkpoint 状态机的 bug。实施前代码在同 run 目录存在时直接拒绝，
且只用 Python 异常回滚，强杀/掉电不能可靠恢复；修复现实现缺陷与补全新设计均在已批准的 M4 内。

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
| target=approved candidate，state=pending/promoted/verified，候选可能已被 replace 消耗 | 以物理 target 为准，重新做完整 target audit；通过后记 `verified`，不得再导出/覆盖。覆盖 replace 成功但 checkpoint 尚未落盘的窗口 |
| target 既不等于 approved old 也不等于 candidate | `target_drift`，停止，不覆盖 |
| target=approved old，但 state=promoted/verified（且 old≠candidate） | `checkpoint_target_mismatch`，停止，不能根据旧 checkpoint 跳过验证或重新覆盖 |
| candidate 尚未冻结，phase=planned，且五个 target 都仍等于 approved old | 同 run 重建未完成候选并重新完整审计；所有候选冻结前不提升任何正式文件 |
| 已冻结 candidate 变化/丢失，该频率 target=approved old，且没有任何频率提升 | `candidate_drift`，停止；只有五个 target 逐一核实仍为 approved old、无任何提升证据，人工确认废弃后才记 `aborted_before_promote` 并允许重新 plan |
| 已有部分频率提升，另一频率 target=approved old 且 candidate 变化/丢失 | `candidate_drift` + `operator_action_required=true`，保留现场和原 run，禁止自动换 run/改冻结指纹；按下文人工异常处置 |
| checkpoint/plan fingerprint、trade_date、run_id 不一致 | `checkpoint_identity_mismatch`，停止 |

身份校验先行；`aborted_before_promote` 的旧 run 再次 apply 必须拒绝，只能新建计划，不能重新提升旧候选。
其余状态再按物理 target 判断；old=candidate 时按“目标已满足候选”完整审计，不强行区分是否发生
replace。判断“未提升”必须同时核对全部物理 target 和 checkpoint，不能只看 pending 标记。

若 plan 因某个目标原本不存在而被标记 `should_stop`，仍禁止 apply；人工废弃时允许按 plan 的原始
“不存在”事实核对该目标仍不存在。该例外只使拒绝执行的计划可以明确终结，不允许忽略计划后新出现、
消失或变化的目标，也不允许给有效计划放宽五频完整性要求。

中断重入时不能照搬现有“重新生成包含五个 target hash 的 plan 再比较”逻辑，因为部分 target 已合法
变成 candidate hash；必须按上表逐频率判定。普通进程中断、候选仍完整时走同 run 幂等续跑。候选已丢失
是另一类故障，不能承诺自动恢复：人工可在同 run 的临时候选位置重新导出，只有结果与原冻结 SHA-256、
字节数及完整 audit 全部相同，才能原子放回该未提升候选位置继续原 run；不得覆盖已提升 target 或修改
原批准的 candidate fingerprint。无法复现时保持失败及维护窗口，提交带当前五频物理事实的现场修复方案，
不由该工具自动另建 run 覆盖混合现场。这是明确的安全停止点，不再同时要求“必须新 run”和“禁止新 run”。

不新增常驻恢复服务、候选版本管理或自动换计划功能；工具只支持正常续跑、提升前人工废弃和异常现场
保全。`aborted_before_promote` 是经零正式变更验证的终态，不能用 `failed` 冒充可丢弃状态。测试还必须
覆盖候选重建结果不同则拒绝、已有提升不可废弃、已完成 run 重入只审计，以及以上每一表格行。

#### 6.4.3 并发和可见性门禁

该工具继续保持 non-active、人工离线恢复定位。并发保护只解决一个具体问题：恢复五频文件期间，不能
让第二个入口同时写同一交易日。它不新增 lock/pid 文件，也不引入常驻协调服务；上一版 run-root 排它锁
只能挡第二个 recovery CLI、挡不住 Dagster/repair writer，并与“禁止自造锁文件”规则冲突，现已删除。

最终门禁分两层：

1. **代码内门禁**：同一 `trade_date` 存在未完成 checkpoint 时，禁止创建新的 `recovery_run_id`；只能用
   原 run id 按第 6.4.2 节续跑或人工处置；只有 `completed/aborted_before_promote` 是不阻挡新计划的
   终态。这个判断复用恢复状态，不另建锁文件，也不宣称它能防住两个进程同时启动；人工维护窗口仍必要。
2. **执行前运营门禁**：人工 apply 前进入明确维护窗口，暂停或禁止可能写同日期的 stk_mins 日常、
   repair、history 和手动入口，并只读确认没有同日期 running/queued run。该确认不要求恢复 CLI 连接
   Dagster instance；正式执行时由独立 preflight/运营检查完成，结束五频验证后再恢复入口。

由于五个文件不存在组级原子提交，LLD明确接受“中断后靠 checkpoint 续跑”，不宣称五频原子；全部
`verified` 前不得运行 `reuse_existing` 记录 materialization/check，也不得把结果标为恢复成功。测试必须
覆盖第 6.4.2 节每个状态组合、同日期第二个 run 拒绝、同 run 两次 apply、进程在第 1–5 个频率后中断、
target 漂移、candidate 漂移、checkpoint 半写保护和跨文件系统拒绝。

#### 6.4.4 M4 低频人工恢复的性能约束

这里的性能门禁只约束 `stk_mins_raw_replace_from_prod` 的单日五频恢复，不涉及 Ops Dataset Status
Snapshot、freshness 页面或普通 API 查询。M4 的旧适配器删除本身没有大数据性能问题；需要预算的是
M4 前半段“从 prod DB 导出五频候选并审计”的离线数据处理。

| 项 | 实现要求 |
|---|---|
| 目标范围 | 一次只允许 1 个 `trade_date`、5 个频率、5 个正式 target 和 5 个 candidate；禁止扩成日期区间或全历史 |
| 读取模型 | plan：本地 stock code set scan、最多 20 条 TaskRun 候选、五频聚合身份查询、5 个 target SHA-256；首次 apply 还会复核这些事实，再做 5 次按日期/频率有界的 prod 导出，顺序执行、不按股票 N+1；正常重入复用已冻结候选、不重复导出已提升频率 |
| 样本基线 | 2026-07-27：5,533 个预期代码、27,665 个代码频率组合、1,776,093 行、五个 Raw 文件约 42.5 MiB；历史 apply 为 109.973 秒 |
| 计算与写入 | DuckDB/数据库流式或集合式导出；禁止 Python 明细行循环；写 5 个 candidate、5 份 audit 和小型 JSON plan/checkpoint/report；不写业务数据库和 Dagster event |
| 内存与临时空间 | 复用统一 DuckDB 内存/线程/temp 配置；candidate 全部位于 `DEFAULT_LAKE_STAGING_ROOT`；不新增本工具独立资源配置。开始前及每频前后记录磁盘可用空间；旧 target 大小只能作参考，不作为候选上界或空间充足证明 |
| 时间参考 | 历史 109.973 秒只用于比较。候选生成+audit 超过 5 分钟，在下一阶段进度输出中提示 `slow_operation_warning`；继续安全执行，不因耗时拒绝、不废弃候选；不设总时长硬 SLA 或新增超时配置 |
| 可观测性 | 输出当前阶段/频率、开始与结束时间、已完成频率数、可得的行数/字节数；单次阻塞导出开始前说明正在等待数据库，不能伪报百分比/ETA；操作人员决定继续等待或取消 |
| 硬停止条件 | 非单日五频、查询无日期/频率边界、校验不符或范围漂移、目标漂移、跨文件系统、资源/磁盘错误仍停止；分别报告 `scope_invalid`、`candidate_invalid`、`target_drift`、`cross_filesystem`、`resource_exhausted` 等具体原因，不混成性能超时 |

落实点：plan/report 记录 `source_row_count_by_freq`、`target_size_bytes_by_freq`、
`staging_free_bytes_before`；实际执行 report/checkpoint 记录 `candidate_size_bytes_by_freq`、阶段耗时和
最后检查到的 `staging_free_bytes`。已有 source facts/target fingerprints 已在 M4 映射到上述报告字段；
实施前 dataclass 不具备全部字段。不要求 plan 提供 `estimated_candidate_bytes` 上界，也取消
“估算值 × 2”硬拒绝。候选生成可能发生空间不足：捕获后停止、保留有效 checkpoint、不开始 promote；
资源错误后不能清空现场。全部候选已落盘、fsync 并通过 audit 后，promote 仅同文件系统 rename，不再
生成大型数据；checkpoint 写入失败按 §6.4.2 恢复，不能判成功。此方案不承诺避免耗尽磁盘，人工预检
必须确认有余量，空间紧张时不启动，不能拿历史约 42.5 MiB 当容量保证。

取消检查放在每个导出/audit/promote 前后；阻塞数据库读取不承诺即时响应或自动 5 分钟超时。若人工必须
终止进程，按中断恢复规则处理，先查清残留数据库会话已结束再恢复写入口。这不新增后台计时/取消服务。
测试用可控时钟证明“超过 5 分钟仍可成功”，用模拟空间错误证明“promote 前零正式改动”，并覆盖
promote 后 checkpoint 写失败、退出重入和源行数不符的失败分支。真实只读导出测量或人工恢复另按执行
阶段授权，不为验证速度反复跑生产全量任务。

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

其中 `test_stk_mins_migration.py` 不能先删：必须先把 Raw partition discovery、五频 alignment 和 success count 的现行覆盖迁到对应当前模块测试。M1 已完成这些独立覆盖；M3 又将两条仍有效的零价格样本转到当前 Raw check，随后才删除旧测试，见 §11 M3。

### 7.2 当前测试的 import 迁移

| 测试文件 | 当前依赖 | 目标依赖/修改 |
|---|---|---|
| `test_stk_mins_silver_m6_history.py` | Silver functions，无完整 CLI 覆盖 | 新增五个 Silver CLI 命令测试和选择器负例 |
| `test_stk_mins_qfq_m8c_history.py` | `stk_mins_migration_cli` | 改 import `stk_mins_qfq_history_cli` |
| `test_stk_mins_qfq_m8d_events.py` | `stk_mins_migration_cli` | 改 import `stk_mins_qfq_history_cli` |
| `test_stk_mins_qfq_m11f_derived_history.py` | `stk_mins_migration_cli` | 改 import `stk_mins_qfq_derived_history_cli` |
| `test_stk_mins_qfq_m12_macd_kdj.py` | `stk_mins_migration_cli` | M2A 已改 import `stk_mins_qfq_macd_kdj_history_cli`；M2B 的 CLI 单分区测试落在 contract 测试，真实 report 门禁落在独立 `test_stk_mins_macd_kdj_baseline_single_partition.py` |

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
5. generate/register Silver 未选择 partition/source 时 fail-closed；report Silver 保持 `None` 交由现有 planner 按范围发现 Silver 文件，不从 Raw 发现。
6. `--all` 在 Silver CLI 不再可接受。
7. register/report Silver 不接受 `--all-from-raw-files`。
8. rebuild 未确认时不调用写函数。
9. baseline 日期/显式 keys 不合法时不获取实例；实际 plan 为零、多或错日期分区时不进入文件审计和事件 writer。
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
6. `dagster-bootstrap-legacy-links.md` 保留为历史总账，但必须明确 executable adapter 已清退、物理旧湖按 M8 逐项审计清退、不可作为操作手册。

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

M0 又把旧路径扫描从 `stk_mins_raw_replace_from_prod` 的旧 `_staging/_quarantine` 口径扩展到正式
Lake 的历史 `_quarantine` 执行证据，补出两份只记录正式 Dagster 历史执行的现行文档。它们不属于
旧 Console/Kopia，也不提供旧湖执行入口，统一登记为 `KEEP_CURRENT_VERIFY`；原矩阵遗漏是扫描口径
过窄，不是删除范围扩大。

矩阵由以下候选清单交叉生成：

1. 86 份待删文档、三个待删模板、旧 frontend/backend 路径的反向引用清单。
2. `OLD_LAKE_BOOTSTRAP|old_lake_root|BootstrapDatasetSpec|BootstrapSourceMethod|old_lake_executor`、
   Kopia、旧物理湖路径、`lake_console/backend|frontend`、`stk_mins_raw_replace_from_prod`、旧
   `_staging/_quarantine` 口径的全仓 tracked 文本命中清单。
3. 本表路径存在性、唯一性和处理码计数清单。
4. 实际物理文件的绝对路径、相对路径和文件名反向引用清单；关键词扫描未命中，不代表没有物理证据依赖。

`lake_console/backend/**`、`lake_console/frontend/**`、`lake_console/config.local.example.toml` 等位于263个
旧产品直接删除边界内的 AGENTS、skills、说明和配置，由精确 Git 删除白名单整体覆盖，不在本表重复列。
除此之外，每个命中文件都必须有一行处理码；仅包含“禁止 Kopia/旧湖”的当前文档也登记为
`KEEP_CURRENT_VERIFY`，不再静默排除。

2026-09-05 当前 HEAD 复扫再补 9 份：两个 Asset Check 治理文档含旧 migration 的历史实现说明，两个
现行趋势通道文档仍引用待删模板，另五份是当前负向禁令/正式链文档，只验证保留。此前“145 份、未归类
为 0”只对应 2026-08-28 M0 基线，不能作为仓库继续开发后的永久完整性保证；旧发现方式不足和后续
仓库变化都会产生新候选，必须在每次执行前重新扫描，而不是保证未来不会新增遗漏。

本次从 reports 的具体 CSV 反查，再补两份已经标明被替代的正式指数设计文档。它们不含旧 Console
关键词，也不是旧产品删除对象；登记为只验证保留。不能把其历史 CSV 初始化口径当当前代码事实。

M5 开工复扫补充（2026-09-05，基线 `5f834b02`）：全仓旧标识/路径反查新增 9 份，见表尾。
其中 6 份仅有合法 staging、负向禁令或只读验收证据，保留；3 份修正文档中的历史/当前 staging 边界。
另有 3 份原 `KEEP_CURRENT_VERIFY` 文档仍引用待删 bootstrap 模板，改为仅切换依据链接的 `MODIFY_CURRENT`，不改业务正文。
此前遗漏是扫描候选没有完整并入矩阵，不能用“都已审过”代替本轮集合对账；本轮不扩大 89 份删除白名单。

本矩阵共 165 份文件：3 份迁移后删除、37 份现行文档修改、14 份混合文档局部修改、86 份纯旧文档
删除、25 份只验证保留。86 份删除目标全部逐文件列名；任何新增发现必须先补矩阵，禁止扩大目录级
删除范围。实施 M0、M5 和 M7 均要求未归类命中、重复路径和意外不存在路径为 0；M5 删除完成后，
只允许明确批准的 89 个路径不存在，不能把正常删除算扫描失败，也不能借此忽略其他死链。物理用途待审不能算闭环。

M7 补清统计边界：本专项方案、本文 LLD、M0 审计清单是三个持续更新的控制文档，不是待清退的
产品文档，单独登记为 `MODIFY_CURRENT` 校验白名单，不重复计入下表 165 份处置对象。复扫集合为
“165 个处置对象 + 3 个控制文档”；不能把这三个命中静默过滤后宣称全文零遗漏。三个精确路径为：

1. `docs/architecture/legacy-lake-console-and-kopia-retirement-plan-v1.md`
2. `lake_console/docs/design/legacy-lake-console-kopia-old-lake-bootstrap-retirement-low-level-design-v1.md`
3. `lake_console/docs/design/legacy-lake-console-kopia-retirement-m0-audit-checklist-v1.md`

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
| `lake_console/docs/design/dagster-bootstrap-legacy-links.md` | `MODIFY_CURRENT` | 收敛为唯一历史迁移结果总账；标记 executable adapter 已删除、物理旧湖按 M8 逐项审计清退、不可执行；吸收 clean_next 重建/修复/代码集合审计的最小数字和结论，不复制旧命令 |
| `lake_console/docs/design/dagster-index-mins-data-onboarding-plan.md` | `MODIFY_CURRENT` | 删除旧 `lake-dataset-development-template.md` 依据，只保留正式 Dagster onboarding/性能/源文档 |
| `lake_console/docs/design/dagster-major-index-mins-data-onboarding-plan.md` | `MODIFY_CURRENT` | 同上 |
| `docs/datasets/major-index-mins-dataset-development.md` | `MODIFY_CURRENT` | 当前正式 Dagster 数据集说明；只移除旧模板引用，保留正式模板和数据集事实 |
| `lake_console/docs/design/dagster-stk-nineturn-dataset-onboarding-plan.md` | `MODIFY_CURRENT` | M5 仅把旧 bootstrap 模板依据切到正式模板 §14；prod-only 初始化与日常 Tushare 正文保留，不历史化 |
| `lake_console/docs/design/dagster-stk-nineturn-dataset-onboarding-low-level-design.md` | `MODIFY_CURRENT` | M5 仅切换同一旧模板依据，其余正文不动 |
| `lake_console/docs/design/dagster-index-daily-000680-history-supplement-low-level-design.md` | `MODIFY_CURRENT` | M5 仅切换旧模板链接到正式模板 §14；保留当前正式历史补录 source/staging 与验收 |
| `docs/governance/engineering-risk-register.md` | `MODIFY_MIXED` | 保留当时 py_compile/pytest 命令为历史证据；对应风险状态改为旧实现已随产品清退，不再列当前入口 |
| `docs/governance/docs-information-architecture-v1.md` | `MODIFY_CURRENT` | 把“旧 Local Lake 文档保留追溯”改为“已从当前工作树删除，必要摘要见单一总账，全文走 Git 历史” |
| `docs/governance/prod-postgresql-raw-direct-serving-phase-one-lld-v1.md` | `MODIFY_MIXED` | 保留生产 PostgreSQL 当前设计；把旧 backend mapping 标为历史审计参照，去掉当前消费者含义 |
| `lake_console/docs/design/dagster-index-daily-raw-by-date-prod-db-migration-plan.md` | `MODIFY_MIXED` | 保留 Dagster 当前方案；旧 backend service 只保留为当时字段口径证据，不可链接为实现依赖 |
| `lake_console/docs/design/dagster-index-daily-raw-by-date-prod-db-migration-low-level-design.md` | `MODIFY_MIXED` | 同上；删除/转文本旧 backend 代码链接 |
| `lake_console/docs/design/dagster-phase-3-index-daily-refactor-design.html` | `KEEP_CURRENT_VERIFY` | 已标为被替代的正式指数历史设计，不是旧 Console 文档；CSV 初始化段只作历史证据，不能用其 948 代码重建当前 820 代码集合。报告处置按 §16.6，不连带删本文或分区集合 |
| `lake_console/docs/design/dagster-phase-3-index-daily-refactor-low-level-design.html` | `KEEP_CURRENT_VERIFY` | 同上；全文已审，raw-by-code/旧 Tushare sensor 不是当前运行链。当前代码读取正式 instance 的 cn_a_index_ts_codes，不运行本文历史初始化步骤 |
| `lake_console/docs/design/dagster-derived-minute-bars-90-120-contract-rebuild-low-level-design.md` | `MODIFY_MIXED` | 把待删除旧算法 producer 更新为已清退事实；保留正式 Dagster 算法和验收记录 |
| `docs/datasets/index-wave4-trend-reversal-backtest-plan-v1.md` | `MODIFY_CURRENT` | 删除旧 index-mins/indicator/MACD 文档引用，改指正式 major-index 分钟接入、canonical bars 和现行 MACD/KDJ Dagster 设计 |
| `lake_console/docs/design/dagster-stk-mins-asset-design.html` | `MODIFY_CURRENT` | 删除 clean_next 代码集合审计原文链接；保留已写入本文的停牌/身份映射/非 strict equality 正式语义，并改引历史迁移总账 |
| `lake_console/docs/design/dagster-stk-mins-qfq-macd-kdj-indicators-plan.md` | `MODIFY_CURRENT` | 删除两个旧指标文档引用；当前递推、性能和验收只以本文及 canonical bars LLD 为准 |
| `lake_console/docs/design/dagster-stk-mins-qfq-macd-kdj-reconciliation-recovery-r5-low-level-design.md` | `KEEP_CURRENT_VERIFY` | 仅记录正式 Dagster MACD/KDJ recovery 已发生的 quarantine 历史证据；保留不改，不把正式 Lake 历史 quarantine 误判为旧 Console/Kopia |
| `lake_console/docs/design/dagster-etf-market-data-prod-db-onboarding-plan-v1.md` | `MODIFY_CURRENT` | 删除旧 etf-basic Console 导出方案引用和历史依据段；保留当前 source docs、正式 Dagster 方案与代码证据 |
| `lake_console/docs/design/dagster-phase-2-design.html` | `MODIFY_CURRENT` | 删除旧 suspend-d Console 导出方案引用；保留 Tushare source docs、实测记录和当前 Dagster 契约 |
| `lake_console/docs/design/dagster-phase-2-low-level-design.html` | `MODIFY_MIXED` | 保留第二期已发生的迁移结果；删除“generic old-lake spec/executor 长期保留并复用”的当前设计，明确 executable adapter 已退役、历史 metadata 只读保留 |
| `lake_console/docs/design/dagster-stock-limit-assets-design.md` | `MODIFY_CURRENT` | 尚未开发的现行方案不得再计划从物理旧湖 bootstrap；保留旧湖审计为历史证据，实施前重新审计 prod DB/Tushare 的完整历史来源并重做初始化预算 |
| `lake_console/docs/design/dagster-adj-factor-asset-design.md` | `MODIFY_MIXED` | 保留 M5/M6 已发生的旧湖迁移、行数和 event 记录；删除当前代码依据中的 generic bootstrap 可用性和可执行 spec 表述，明确后续不再复用旧适配器 |
| `lake_console/docs/design/dagster-namechange-asset-design.md` | `KEEP_CURRENT_VERIFY` | 旧湖只作为已明确的历史只读审计证据，正式来源是 Tushare；确认不新增旧湖执行入口即可，不改历史数字 |
| `lake_console/docs/design/dagster-stk-mins-prod-task-run-readiness-low-level-design.md` | `MODIFY_MIXED` | 保留 2026-07-27 事故、109.973秒、1,776,093行；当前 Raw 恢复实现改指第6.4节，不误改 Silver 工具合同。M8 删除 D04/D05 时，将物理路径注明为历史位置及实际清退状态，已有摘要保留；不再将搬迁完整 manifest 或重新审计人工取证价值列为数据删除前置项（§16.14） |
| `wealth/docs/pages/stock-detail/stock-detail-minutes-api-implementation-design-v1.md` | `MODIFY_CURRENT` | 保留“不依赖旧 backend”的边界；M6 后把“是本地管理台”改为“已清退的旧管理台”，避免把已删产品写成当前存在 |
| `wealth/docs/pages/stock-detail/stock-detail-minutes-api-benchmark-requirement-v1.md` | `MODIFY_CURRENT` | 保留性能合同和不导入旧 router 的负向门禁；M6 后更新旧 backend 时态 |
| `wealth/docs/pages/stock-detail/stock-detail-minutes-api-low-level-design-v1.md` | `MODIFY_CURRENT` | 保留 Foundation Reader/Biz API/Wealth 页面当前链；M6 后把旧 backend 行改为已清退且禁止恢复 |
| `wealth/docs/pages/stock-detail/stock-detail-minutes-api-m2-coding-gate-v1.md` | `MODIFY_CURRENT` | 保留既有验收结论；M6 后把“没有作为生产 API”更新为“已清退且生产链未曾依赖” |
| `docs/architecture/etf-basic-rebuild-and-downstream-data-audit-cleanup-plan-v1.md` | `KEEP_CURRENT_VERIFY` | 仅包含“不引入 Kopia/不使用旧 Lake 备份”的当前禁止项，必须保留，不参与本专项修改 |
| `lake_console/docs/design/dagster-cn-a-minute-gold-canonical-bars-rebuild-low-level-design.md` | `KEEP_CURRENT_VERIFY` | 仅包含无 Kopia、正式 staging/checkpoint 的当前安全合同，确认不受清退影响 |
| `lake_console/docs/design/dagster-gold-wealth-market-turnover-dataset-design.md` | `KEEP_CURRENT_VERIFY` | 仅包含无 Kopia/无正式根 staging 的当前门禁，保留不改 |
| `lake_console/docs/design/dagster-gold-wealth-market-turnover-dataset-low-level-design.md` | `KEEP_CURRENT_VERIFY` | 同上；历史执行数字和当前 staging 合同均不依赖旧 Console |
| `lake_console/docs/design/dagster-stock-qfq-nineturn-dataset-plan.md` | `KEEP_CURRENT_VERIFY` | 仅记录执行未使用 Kopia/旧湖，保留为现行负向证据 |
| `lake_console/docs/design/dagster-stock-qfq-nineturn-dataset-low-level-design.md` | `KEEP_CURRENT_VERIFY` | 仅记录正式 Dagster 九转治理已发生的 quarantine/manifest 历史证据；保留不改，不纳入旧产品清退 |
| `wealth/docs/pages/market-overview/sector-overview-low-level-design-v2.md` | `KEEP_CURRENT_VERIFY` | 只声明不新增 Kopia/旧湖路径，保留当前禁止项 |
| `wealth/docs/pages/market-overview/sector-overview-m2-coding-gate-v2.md` | `KEEP_CURRENT_VERIFY` | 只记录 Heat 链无 Kopia的验收事实，不受本专项删除影响 |
| `wealth/docs/system/detail-page-nine-turn-integration-implementation-design-v1.md` | `KEEP_CURRENT_VERIFY` | 只记录分钟九转执行未使用 migration/Kopia，保留历史执行证据 |
| `wealth/docs/system/detail-page-nine-turn-integration-low-level-design-v1.md` | `KEEP_CURRENT_VERIFY` | 只包含禁止旧 Lake/Kopia及正式 staging/checkpoint合同，保留不改 |
| `lake_console/docs/design/dagster-asset-check-incremental-governance-low-level-design.md` | `MODIFY_MIXED` | P6A 的 `stk_mins_migration` Raw runless/bootstrap audit 说明改为当时执行事实；M3 后注明旧 producer 已清退，当前 Raw blocking checks/readiness 及现行 Silver/QFQ 事件能力不变 |
| `lake_console/docs/design/dagster-asset-check-incremental-governance-plan.md` | `MODIFY_MIXED` | 同上；只处理旧 migration 实现状态，不删除已经收敛的当前 check 名称、语义和验收记录 |
| `lake_console/docs/design/dagster-dc-board-data-onboarding-low-level-design.md` | `KEEP_CURRENT_VERIFY` | Kopia 命中为禁止项；保留当前板块数据接入、正式 staging 和校验合同 |
| `lake_console/docs/design/dagster-etf-daily-data-onboarding-low-level-design-v1.md` | `KEEP_CURRENT_VERIFY` | 旧 backend/旧湖/Kopia 均为禁止来源；保留当前 ETF 日线 Raw/Silver 与运行验收 |
| `lake_console/docs/design/dagster-etf-daily-data-onboarding-plan-v1.md` | `KEEP_CURRENT_VERIFY` | 保留已运行的 ETF 日线方案和结案事实；旧湖/Kopia 命中不构成删除理由 |
| `lake_console/docs/design/dagster-etf-market-data-prod-db-onboarding-low-level-design-v1.md` | `KEEP_CURRENT_VERIFY` | 保留当前 ETF 正式 prod DB 只读接入；无旧 Console 正向实现依赖，禁止项不删 |
| `lake_console/docs/design/dagster-stock-daily-trend-channel-dataset-onboarding-low-level-design-v1.md` | `MODIFY_CURRENT` | §15 依据中的旧 `lake-dataset-development-template.md` 改引正式 Dagster onboarding 模板；保留现行趋势通道生产、repair、Wealth API 和全部验收记录 |
| `lake_console/docs/design/dagster-stock-daily-trend-channel-dataset-onboarding-plan-v1.md` | `MODIFY_CURRENT` | 文末依据中的旧 Lake 模板链接改引正式 Dagster onboarding 模板；其余当前方案不动；与对应 LLD 同步 |
| `wealth/docs/pages/wealth-exploration/turnover-insight-implementation-design-v1.md` | `KEEP_CURRENT_VERIFY` | 旧湖路径属于显式禁止读取项；保留 Gold turnover → Foundation Reader → Wealth 洞察页面当前链 |
| `lake_console/docs/design/dagster-etf-daily-data-onboarding-p0-audit-2026-09-02.md` | `KEEP_CURRENT_VERIFY` | M5 新发现：正式 staging 和隔离只读审计证据，不删、不改生产准入结论 |
| `lake_console/docs/design/dagster-etf-daily-data-onboarding-p2-real-sample-2026-09-02.md` | `KEEP_CURRENT_VERIFY` | 隔离样本 staging 与未写正式 Lake 的记录，保留 |
| `lake_console/docs/design/dagster-index-global-data-onboarding-low-level-design.md` | `KEEP_CURRENT_VERIFY` | 当前 Silver staging helper 与写入结果设计，保留 |
| `lake_console/docs/design/dagster-index-technical-datasets-onboarding-low-level-design-v1.html` | `MODIFY_CURRENT` | 仅补齐 §5.6 Silver staging 示例的独立根路径；不改字段、公式、源范围或样本门禁 |
| `lake_console/docs/design/dagster-major-index-mins-data-onboarding-low-level-design.md` | `KEEP_CURRENT_VERIFY` | 已获准保留的 source staging 和临时构建证据；不删、不触发源请求 |
| `lake_console/docs/design/dagster-phase-3-major-indices-design.html` | `MODIFY_MIXED` | 在旧 by-code 路径块标注历史位置；当前 Raw by-date 口径指向现行迁移 LLD，不把旧 staging 当操作示例 |
| `lake_console/docs/design/dagster-stk-mins-prod-db-raw-extraction-hardening-plan.html` | `MODIFY_MIXED` | 旧 .prod_db_staging 分页临时路径标为历史方案，不冒充现行 DuckDB COPY 或 M4 Raw 恢复路径 |
| `lake_console/docs/design/dagster-stock-daily-trend-channel-m0-readonly-performance-validation-2026-09-01.md` | `KEEP_CURRENT_VERIFY` | 当前趋势通道只读性能证据与容量估算，保留 |
| `wealth/docs/system/detail-page-nine-turn-m3-serving-publication-gate-v1.md` | `KEEP_CURRENT_VERIFY` | 当前九转 serving 发布与 staging/容量门禁，保留；M5 不处理其恢复副本 |
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
```

`stk_mins_raw_replace_from_prod` 的模块/CLI 已进入 10.2，专属测试进入 10.3；它们必须按第 6.4 节重构，
不是“保留不改”，也不得在旧适配器清退时删除。
本节是 M0–M7 代码保留清单，不是所有 reports/旧湖数据永久保留决定；具体数据按 §16，ignored 环境另轮处理。

---

## 11. 实施分片与顺序

### M0：基线冻结

1. 记录 branch、HEAD、工作区状态和精确变更白名单。
2. `codegraph sync` 后确认索引 current。
3. 重新运行旧 source、old root、mixed CLI 和 backend import 的引用清单。
4. 重跑第 9.4 节三路文档候选清单，确认未归类命中、矩阵重复/不存在路径、待删文档现行入链均为 0。
5. 发现本文以外的当前消费者或文档命中时停止，不进入删除。
6. 下一项工作先完成 §16 物理数据用途只读审计及分类清单，供用户 review，再进入代码清退实施；不等到 M8 才首次核用途。待审对象如实登记，任何删除清单均须用户另行确认。

### M1：先迁当前 `stk_mins` helper

1. 新增 check-event helper。
2. 把四个当前 event 模块改用新 helper。
3. 把 Raw partition discovery/alignment 迁到 Silver history。
4. 更新对应测试并跑定向回归。
5. 此阶段不删旧 migration 文件，保证每一步可验证。

#### M1 本轮执行约束（2026-09-05）

基线 `dev-interface@650c549d`。用户要求继续推进后进入本阶段；仅迁出当前能力，旧迁移模块及旧 CLI
保持原文件不动，直到 M2/M3 分阶段退出，不新增旧名 wrapper、alias 或新模块对旧迁移的依赖。

| 硬口径 | 代码落点 | 验证 |
|---|---|---|
| 四个事件模块不再导入旧 migration 的计数函数 | `stk_mins_history_check_events.py` 与 §5.2.3 四个消费者 | 真实消费者接线、只计 SUCCEEDED、空历史和读取异常、每 check 恰好一次 limit=50000 查询 |
| Raw 发现及五频校验归 Silver history | `stk_mins_silver_history.py` 的 discover/all_raw/alignment | 空目录、排序、只认 part-000 普通文件、不同频率缺日/多日必须失败；Raw/Silver 调用方均覆盖 |
| 不改变写入、参数、选择范围与成功口径 | 原 CLI/migration 原样；四个事件模块只改 import 和调用名 | 固定期望值、现有定向测试、静态无旧 import；derived/MACD quick 模式仍跳过历史计数 |
| 不运行正式环境、不删除物理数据或旧产品文件 | 本轮仅代码和测试重构、原三份文档同步 | 临时目录/fake instance 隔离；最终 diff 核对无删除、无 paths/catalog/SQL/asset/check 定义改动 |

性能与验证范围：

| 项目 | 本轮预算及边界 |
|---|---|
| 对象/日期/分区 | discovery 固定五频；隔离样本最多三日、十五个主路径，另设错误路径；不扫描正式湖 |
| 请求/分页/行数 | 计数 helper 每 check 一次 history 查询、limit=50000，原样保留；fake 样本覆盖零条、混合状态和 50000 条；Tushare/生产 DB 请求为 0 |
| 扫描与写入 | 只迁路径发现与计数，不增 Parquet scan/join/write/spill；测试数据及 DuckDB temp 只能在隔离临时目录 |
| 提交/替换/重试 | 不改正式 writer、事务、replace 或 checkpoint；helper 读取异常原样上抛，不新增重试或吞异常 |
| 耗时/空间/配额 | 不新增运行查询次数；测试规模固定，记录实际用时；无生产配额、正式数据磁盘增量或全量执行 |
| 拒绝项 | 新增生产访问、增加 history 查询次数、降低五频一致性或引入旧模块依赖，任一出现即停止验收 |

CodeGraph `explore/impact` 已覆盖迁出函数、Silver history、四个事件消费者和 CLI/测试；全仓程序引用
补扫确认离线 strict audit 的同名 discover 是独立定义，不属于本轮迁移，不顺手合并。参考
[Dagster asset checks 官方说明](https://docs.dagster.io/guides/test/asset-checks)，本轮不改 check 定义或注册。
#### M1 实施与验证结果

M1 代码迁移于前轮完成，本轮按用户要求提交为 `3007cc0e`，未推送或部署。以下是 M1 当时的验证记录；
本轮 M2A 的后续迁移和唯一文件删除另记于下节，不回写成 M1 的验证成果。

| 文件（以下 Python 路径相对 orchestrator） | 结果 |
|---|---|
| `src/orchestrator/defs/bootstrap/stk_mins_history_check_events.py` | 新增公开计数 helper，保留原查询次数、上限、状态过滤和异常传播 |
| `src/orchestrator/defs/bootstrap/stk_mins_silver_history.py` | 承接 discover/all_raw/alignment，Raw 与 Silver 日期对齐保持原语义 |
| `src/orchestrator/defs/bootstrap/stk_mins_silver_bootstrap_events.py` | final audit 改用新计数 helper |
| `src/orchestrator/defs/bootstrap/stk_mins_qfq_bootstrap_events.py` | plan/final audit 所用计数改接新模块 |
| `src/orchestrator/defs/bootstrap/stk_mins_qfq_derived_bootstrap_events.py` | full 计数改接新模块，quick/report 跳过计数行为不变 |
| `src/orchestrator/defs/bootstrap/stk_mins_qfq_macd_kdj_baseline_events.py` | indicator/state 计数改接新模块，可选跳过行为不变 |
| `tests/test_stk_mins_history_helpers.py` | 新增 Raw/Silver 路径、排序、空集、五频差异、选择和依赖防回退测试 |
| `tests/test_stk_mins_history_check_events.py` | 新增只读计数、50000 上限、异常、四个真实消费者和 full/quick 接线测试 |
| `tests/test_stk_mins_qfq_m11f_derived_history.py` | 两处 mock target 随公开 helper 改名；原“不得扫描历史”负向断言不减弱 |

验证结果：

1. 开工前 static gates：108 passed；改后定向组合：**155 passed、450 subtests passed、5.80 秒**。
   包括两份新测试（33 项）、static gates、asset governance、Silver helper 不注册组件检查，以及
   MACD/KDJ 内存配置与原 CLI 默认对象范围检查。16 条 warning 来自既有 Dagster/Pydantic 依赖提示。
2. 改动 Python 文件默认 Ruff、全 orchestrator `E9,F63,F7,F82` 均通过。
3. 结构等价核验：4 个迁出函数在名称/说明归一化后 AST 相等；5 个保留模块去除已审计 import、迁入函数
   并归一化调用名后 AST 相等。旧 migration 与旧 CLI 对开工基线逐字未变，当前五个消费者旧 import 为 0。
4. 现有部分集成测试会使用正式盘 DuckDB temp，因此本轮没有全跑 Silver/QFQ/derived/MACD 写湖集成测试；
   不把上述 155 项冒充完整链路或生产验收。正式 `dg check defs`、job/sensor、生产数据读取/写入均未执行。
   更新 mock target 的两条原 derived 写湖集成用例本轮未执行，已由新隔离 full/quick 接线测试覆盖迁移契约。
5. 没有改变 asset/check/partition/job/sensor 定义、路径/schema/catalog/SQL、业务 writer、前端/API、
   Ops Snapshot 或 ignored 配置；子系统边界与依赖矩阵不变，只解除 bootstrap 内当前模块对旧迁移的 import。
6. 文档完整性检查、`git diff --check` 通过；CodeGraph 已 sync 且 current。没有删除文件，既有 156 份
   文档矩阵与 263 个旧产品文件清单未变；其它任务的工作区改动保留，未纳入本轮。

M1 的后继阶段为 M2A：先冻结 21 个当前 CLI 命令合同，再迁移四个 CLI 并做双跑等价验证；现已执行，见下节。
旧模块中原实现保持冻结，不是新增兼容实现，也不代表已经符合 M3 的整文件删除前提。

### M2A：当前 CLI 行为等价迁移

1. 新增 shared CLI contract、冻结 fixture 和 old/new 等价测试。
2. 分别新增 Silver、QFQ、QFQ derived、MACD/KDJ CLI。
3. 按第 4.2.6 节原样迁移 21 个当前命令；不混入参数加固。
4. 对 21 个命令逐个双跑 parser/dispatch/output/failure 合同；7 个旧命令只做不存在负例。
5. 双跑全绿后改为新 CLI 对冻结 fixture，更新全部现行 import/static gate。
6. 证明无当前消费者后删除 `stk_mins_migration_cli.py`，不留 alias。

#### M2A 本轮执行约束（2026-09-05）

M1 已提交 `3007cc0e`，用户指定本轮进入 M2A。只新增 shared contract、四个 CLI、冻结 fixture 和
隔离合同测试，迁移四份现行测试与相应 static gate，修正直接引用旧 CLI 的现行 canonical 文档及原专项记录。
根规则要求主要入口实质变化时同步架构快照，因此一并更新 `docs/architecture/codegraph-architecture-snapshot.md`
中的分钟 CLI 入口；该文件原已在 §9.4 的 `MODIFY_CURRENT` 矩阵，不新增清退范围，不提前删除旧 Console 节点。
本轮唯一待删除代码文件为 `orchestrator/defs/bootstrap/stk_mins_migration_cli.py`，仅在双跑全部通过、
现行程序消费者迁移后执行；不删除 `stk_mins_migration.py`、旧 Console、旧文档或物理数据。

| 硬口径 | 代码/测试落点 |
|---|---|
| 先冻结旧入口，再创建新入口；期望值不由新实现生成 | fixture 记录旧文件 SHA/提交、21 项 parser/目标函数/副作用分类及实际隔离调用结果；先对旧入口验证 |
| 每命令原行为相等 | 同 argv 双跑，逐项比较 Namespace、有类型的 args/kwargs、调用顺序、stdout、返回值、异常及其发生前的调用 |
| 不提前实施 M2B | Silver 当前 selector/优先级/空值行为及 MACD baseline 当前日期默认保持；§4.2.2/4.2.5/4.4 中收紧和 selector 拆分属于最终 M2B 目标 |
| 不删仍在用的命令 | Silver 5、QFQ 5、derived 5、MACD/KDJ 6，共 21；7 个旧命令在四个新入口都拒绝 |
| 不执行正式能力 | Lake 路径发现、Dagster instance、DuckDB resource 和所有业务调用替换为严格 fake；异常调用即失败，不读取真实数据 |
| 删除后仍能回归 | 新 CLI 对冻结 fixture；最终测试不 import、恢复或内嵌旧 dispatcher；旧文件仍可通过 Git 历史取回但不作运行兜底 |

性能/副作用预算：21 个命令，每个覆盖默认和显式参数，并补 dry-run/selector/confirm/checkpoint/choice/
空值与异常案例；单例最多三个模拟日期、固定返回对象，每次只记录参数与输出。正式分区、Parquet 扫描、
源请求、数据库查询、事件写入、正式文件写入均为 0；不改变实际 writer 的批次、事务、原子替换或运行预算。
对不支持 option、缺必填或未确认等负例检查调用边界；测试规模固定，完成时记录案例数和实际耗时。
CodeGraph explore/impact 与程序引用补扫确认消费者为四份测试及 static gate，无业务 API/前端调用方。

#### M2A 实施结果（2026-09-05）

本轮先提交 M1，再基于 `dev-interface@3007cc0e` 冻结旧 CLI；创建新 CLI 前已生成固定 fixture。
旧源文件 SHA-256 为 `2e93cf484c9fc03ae89c52862f61eb8ad2382d7ac3ed5df0bea66f655770240e`。
21 个命令共 **246 组输入**完成旧/新双跑，parser、参数类型/值、目标函数、获取资源顺序、stdout、
返回值和异常一致；21 段 handler 归一化公开 helper 调用名后 AST 相等。只有程序入口/根 help 描述及
M1 已验证的 Raw discovery helper 归属变化，不引入业务逻辑差异。

以下路径相对 `lake_console/orchestrator`，文档行另标仓库根路径：

| 文件 | 已实施内容 |
|---|---|
| `src/orchestrator/defs/bootstrap/stk_mins_history_cli_contract.py` | 4 个 shared helper；CSV 保留输入顺序/重复项，partition 排序但不去重，空串与逗号空集原义不变；可注入 instance |
| `src/orchestrator/defs/bootstrap/stk_mins_silver_history_cli.py` | 5 个命令，54 组对照；原 selector 优先级、generate/register 无 selector 失败、report 无 selector 可传 None 均保留 |
| `src/orchestrator/defs/bootstrap/stk_mins_qfq_history_cli.py` | 5 个命令，57 组对照；历史生成和事件 plan/report/final 原样分派 |
| `src/orchestrator/defs/bootstrap/stk_mins_qfq_derived_history_cli.py` | 5 个命令，60 组对照；full/quick 的计数开关、输出和默认值不变 |
| `src/orchestrator/defs/bootstrap/stk_mins_qfq_macd_kdj_history_cli.py` | 6 个命令，75 组对照；rebuild 必须 checkpoint + confirm，默认整数频率 tuple 与空对象范围不变；baseline 日期尚未收紧 |
| `tests/fixtures/stk_mins_history_cli_contract_v1.json` | 独立于新实现的 21 命令字面量基线、246 案例及三类副作用标签；不把 fake 回放声称为生产读写验收 |
| `tests/test_stk_mins_history_cli_contract_equivalence.py` | 固定基线回归、四组命令归属、7 旧命令 × 4 新入口拒绝、shared 空值/注入、旧入口缺失及无旧直接依赖门禁；不导入/恢复旧 CLI |
| `tests/test_stk_mins_qfq_m8c_history.py` | 当前 plan/generate 改接 QFQ CLI；旧 canonical one-shot 负例改验证当前 canonical CLI，未删除负例 |
| `tests/test_stk_mins_qfq_m8d_events.py` | 当前 QFQ plan/report/audit 改接 QFQ CLI，注册分区 mock target 随公开 helper 改名 |
| `tests/test_stk_mins_qfq_m11f_derived_history.py` | 当前 derived 五命令及 quick audit 改接 derived CLI，原断言保留 |
| `tests/test_stk_mins_qfq_m12_macd_kdj.py` | 默认全市场 rebuild 入口和 mock 改接 MACD/KDJ CLI，不收紧对象范围 |
| `tests/test_run_contract_static_gates.py` | rebuild/confirm 检查读取 MACD/KDJ CLI；one-shot 禁令检查读取 canonical CLI；其它旧 backend/迁移静态门禁不动 |
| `src/orchestrator/defs/bootstrap/stk_mins_migration_cli.py` | 双跑及消费者切换通过后唯一删除；无兼容 alias，可从 M1 提交的 Git 历史恢复 |
| 仓库根 `lake_console/docs/design/dagster-cn-a-minute-gold-canonical-bars-rebuild-low-level-design.md` | 更正已删除 one-shot 的现行入口说明，不改 canonical 六阶段设计 |
| 仓库根 `docs/architecture/codegraph-architecture-snapshot.md` 与三份原专项文档 | 回填新入口、阶段进度、验证及保留边界；156 文档矩阵和 263 旧产品文件范围不变 |

已核清的易错点：

1. `audit-silver-final` 不是 dictionary 输出，已冻结真实 dataclass 类型及 repr，纠正 §4.3 文档概括。
2. 部分 event 命令原来先取业务 instance，又单独读取已注册分区；M2A 保留原调用次数/顺序，没有顺手优化。
3. `--partition-keys ''` 与 `' , '`、重复日期/频率/年份、`--all` 与文件 selector 的优先级都分别测试。
4. baseline 日期默认及 Silver 含糊 selector 仍待 M2B；这不是遗漏，也不能把 M2A 通过当作安全加固已完成。
5. 当前四组 history/event 业务函数、路径、schema、SQL、writer、事务、checkpoint、Dagster 组件、API/前端、
   ClickHouse、Ops Snapshot 均未改。旧迁移主体、旧 Console、停牌 CSV、ignored 环境、物理数据均保留。

验证与边界：删除旧入口前双跑脚本为 `/private/tmp/lake-retirement-m2a-20260905.5cPIXY/verify_dual.py`；
其中旧源码 hash 校验、246 对输入和 21 段 AST 全通过。该脚本仅用于删除前取证，删除后不作为回归依赖，
永久回归使用上述固定 fixture。补跑的现有 5 个 CLI 集成测试通过，覆盖 QFQ plan/generate/event/final、
derived 五命令/full/quick 和 canonical 拒绝旧命令；隔离运行器
`/private/tmp/lake-retirement-m2a-20260905.5cPIXY/run_isolated_cli_tests.py` 只把 DuckDB spill 重定向临时目录，
使用临时 Lake/ephemeral instance 并禁止正式 instance 与网络。M1 的“未全跑集成”历史限制未被掩盖。
最终收尾结果：

1. 删除后定向组合 **217 passed、696 subtests passed，5.37 秒**；包括 M2A 固定合同/负例 62 项，
   M1 helper/消费者、static gates、asset governance、Silver 非 active 检查、MACD 内存和默认对象范围检查。
   696 个子断言中 246 个来自 CLI 固定案例，450 个来自既有治理测试。16 条 warning 为已有依赖提示。
2. 删除后重新运行上述 5 个原 CLI 集成测试：**5 passed、42 deselected，2.19 秒**；52 条 warning 为
   Dagster 现有 API/资源提示。没有把 deselected 的其它 42 项算成通过，没有全跑长历史集成或生产验收。
3. 四个新模块分别执行 `uv run --no-sync python -m orchestrator.defs.bootstrap.<新模块名> --help`，
   均 exit 0，命令集合分别为 5/5/5/6；没有实际执行其业务子命令。
4. 11 个新增/修改 Python 文件默认 Ruff、全 orchestrator `E9,F63,F7,F82` 通过；固定 fixture 格式化后仍可解析。
5. `scripts/check_docs_integrity.py`、156 文档矩阵检查、`git diff --check` 全通过；矩阵无遗漏路径/重复，
   263 个旧产品 tracked 文件及路径摘要未变。CodeGraph sync/status 为 current。
6. 工作区范围共 18 个文件：5 份文档、5 个新运行模块、5 份既有测试、1 份新合同测试、1 份固定 fixture、
   1 个旧 CLI 删除；用户随后要求提交，本次仅按这 18 个文件归档，不包含 M2B 或其它阶段改动。

复跑位置为 `lake_console/orchestrator`。永久合同检查为
`uv run --no-sync python -m pytest -q tests/test_stk_mins_history_cli_contract_equivalence.py`。
隔离集成检查通过上述临时运行器传入三份 `m8c_history/m8d_events/m11f_derived_history` 测试文件，并使用
`-k 'test_cli or test_unsafe_canonical_rebuild_command_is_removed'`；不要直接全跑原集成文件而遗漏 DuckDB temp 隔离。

使用 CodeGraph `explore/impact/callers` 追踪旧 CLI helper、MACD rebuild、四份测试和底层 history/event；
全仓 tracked 程序引用补扫未发现 API、前端、调度、配置或脚本消费者。新 CLI 仅是人工离线入口，
不注册 active 组件，不改变子系统边界/依赖矩阵。正式环境及完整长历史链路没有执行，也未部署或推送。
M2A 修改已按用户要求归档为 `0cc84004`，未推送；该次提交未包含 M2B，也未进入 M3 或 M8。后续 M2B 独立实施记录见下。

### M2B：当前 CLI 安全加固

1. 只修改 Silver selector 歧义。
2. 只增加 MACD/KDJ baseline 单分区门禁。
3. 新增批准差异正反例；M2A fixture 其余字段必须不变。

#### 2026-09-05 执行约束与代码映射（开工前核验）

| 硬口径 | 实现点 | 验证 |
|---|---|---|
| 三条 Silver 写入口仅去掉批准的旧选择器 | Silver CLI 显式 parser；分离 Raw/Silver 两个私有 selector；精确拒绝 `--all` token | 旧 option、与合法 keys 混用、dry-run 和系统 argv 都在任何 capability 前失败；合法 selector 仅调用一次正确文件发现器 |
| baseline 请求和最终选择都是同一天 | MACD CLI 必填参数及实例访问前纯校验；baseline report 入口复用校验；一次 planner 后再次检查 | 缺日期、跨日、空/越界 keys、零/多/错日期 plan；正例、dry-run、skip-ready、审计失败和原有事件载荷 |
| 其余行为不变 | M2A 原 fixture 内容保持，新增 `approved_delta` 明确规则，不从新实现重录原预期 | 21 命令、246 原案例逐条对账；新增合法单日与拒绝案例；原有隔离回归 |
| 不扩至 M3 或数据操作 | 仅两份 CLI、一份 baseline report、对应测试及原设计文档 | diff 清单；无删除、无部署、无正式实例/Lake/数据库访问 |

性能边界：本轮不新增 SQL、文件扫描、事件类型、事务或配置。新门禁本身只解析日期和显式 keys（时间 O(keys)，内存与输入相关）；无效日期/keys 的文件查询、事件和提交均为 0。合法 baseline 仍只调用一次 event planner；其内部调用 history planner，后续原文件审计再调用一次 history planner，底层合计仍为两次。日期数固定 1，频率数不超过现有 `STK_MINS_QFQ_FREQS`，事件上界为该频率数乘现行 `EVENT_COUNT_PER_FREQ_PARTITION`，资产分区数为频率数 × 2。底层按年文件读取量、DuckDB 内存/spill 与原审计相同，本轮不声称单日门禁使物理扫描自动缩为日文件，也不新增超时阈值。使用隔离 mock 和临时样本计数核验，不进行正式全量性能验收。

CodeGraph 已在修改前覆盖两个选择入口、baseline CLI → report → planner → 文件审计/事件写入；文本复核确认 report 的现行运行调用方只有 MACD CLI，planner 另有只读 final audit 和测试消费者，均保持其多日能力。没有前端/API/sensor 消费者或跨子系统契约变更。

#### M2B 执行结果（2026-09-05）

| 文件（相对 orchestrator） | 已完成的修改 |
|---|---|
| `src/orchestrator/defs/bootstrap/stk_mins_silver_history_cli.py` | 三命令显式注册各自 selector；删除含糊 option；dispatch 前精确拒绝 `--all` token，包括实际 `sys.argv` 调用；分离 `_selected_raw_partition_keys` / `_selected_silver_partition_keys`；日期范围、排序/重复值/空值、合法 keys 优先级、skip/overwrite/dry-run 和输出不变 |
| `src/orchestrator/defs/bootstrap/stk_mins_qfq_macd_kdj_history_cli.py` | 仅 baseline 子命令显式必填起止日期；在任何 capability 获取前调用纯范围校验；其它五命令和四函数 shared contract 不变 |
| `src/orchestrator/defs/bootstrap/stk_mins_qfq_macd_kdj_baseline_events.py` | 新增纯校验；report 的 Python 起止日期参数改为必填，入口复核日期/keys；原 baseline event planner 执行一次后检验实际 keys 恰好为请求当天；不修改文件审计、check、event payload、skip-ready 或只读 planner/final audit |
| `tests/fixtures/stk_mins_history_cli_contract_v1.json` | 仅增加顶层 `approved_delta`，明确四命令的删参、必填和错误文本；原 M2A 全部内容保留 |
| `tests/test_stk_mins_history_cli_contract_equivalence.py` | 从旧 fixture 按批准规则转换预期，不重录新实现输出；哈希防止原基线漂移；增加 54 项 CLI 边界/合法单日对账，包含 target 异常传播、空值、重复 keys、优先级与其它 option 缩写 |
| `tests/test_stk_mins_macd_kdj_baseline_single_partition.py` | 新增 44 项真实 report 编排与事件构造测试；隔离 I/O；直接 Python 入口、零/多/错日期 plan、失败前无事件、单日七频、dry-run、skip-ready、审计失败、真实只读多日 planner 和原文件审计的第二次 history 规划 |

未修改当前 Silver/QFQ/derived/MACD 计算函数、生产数据、旧 migration 主体、旧 Console、配置和目录。原三份专项文档、MACD/KDJ 原设计与 CodeGraph 快照同步回填；边界/依赖矩阵不变。

验证结果：

1. 定向回归 **315 passed、696 subtests passed**（其中 246 为原 CLI 案例，其余 450 为既有合同子案例）；覆盖 contract、单分区、history helpers、check events、run-contract/static、asset governance，以及 Silver helper 和 MACD rebuild 两项原行为。
2. 原 QFQ/derived CLI 隔离集成测试 **5 passed、42 deselected**，复用 `/private/tmp/lake-retirement-m2a-20260905.5cPIXY/run_isolated_cli_tests.py`；临时 Lake、ephemeral instance、临时 DuckDB spill，不使用正式环境。
3. 新增测试确认请求非法时 planner/文件/事件均 0 次；异常实际 plan 只规划 1 次、文件/事件均 0 次。正常单日 7 频当前是 14 个资产分区、42 条事件（每频 2 materialization + 4 checks），不使用旧历史报告中的 56 条作为当前常量。
4. 五份 Python 文件 Ruff 检查通过；文档完整性与 `git diff --check` 通过。156 份文档矩阵无缺失/重复，263 个旧 Console 文件路径指纹保持 `d0f3778dab3fabb0992d92322dce3b3209d318e80f98b40c2a16d225f33f02bf`。CodeGraph sync/status 为 up to date。本轮未运行正式 baseline 补事件或生产性能验收，也未新增性能阈值。
5. 额外用真实 report → baseline planner → 文件审计验证底层 history planner 共两次（原逻辑），没有新增预扫描；不使用 mock 层的一次调用数推断全链扫描次数。

外部语义核验：Python 官方说明 argparse 默认允许无歧义前缀，因此需要精确拒绝已移除的 `--all`，同时保持其它缩写行为（[Python 3.13 argparse](https://docs.python.org/3.13/library/argparse.html#allow-abbrev)）。Dagster 的 `report_runless_asset_event` 会直接记录非 run 事件，安全检查必须位于调用之前（[Dagster Instance API](https://docs.dagster.io/api/dagster/internals#dagster.DagsterInstance.report_runless_asset_event)）；当前事件构造与本地安装版本已用隔离测试核验。

可复现的定向回归（从 `lake_console/orchestrator` 执行）：

```bash
uv run --no-sync python -m pytest -q --disable-warnings \
  tests/test_stk_mins_history_cli_contract_equivalence.py \
  tests/test_stk_mins_macd_kdj_baseline_single_partition.py \
  tests/test_stk_mins_history_helpers.py \
  tests/test_stk_mins_history_check_events.py \
  tests/test_run_contract_static_gates.py \
  tests/test_asset_governance_contracts.py \
  tests/test_stk_mins_silver_m6_history.py::StkMinsSilverM6HistoryTests::test_m6_helpers_do_not_define_active_dagster_components \
  tests/test_stk_mins_qfq_m12_macd_kdj.py::StkMinsQfqM12MacdKdjTests::test_history_rebuild_uses_bounded_duckdb_memory \
  tests/test_stk_mins_qfq_m12_macd_kdj.py::StkMinsQfqM12MacdKdjTests::test_rebuild_cli_uses_full_market_scope_when_stock_codes_are_omitted
```

M2B 已按用户要求提交为 `e8e2abf9`，未推送。用户随后单独授权进入 M3；引用清零与精确删除审计另记于下节，不回写成 M2B 成果。

### M3：删除旧 migration 主体

1. 证明 `stk_mins_migration.py` 的现行消费者已清零：其中仍保留 M1 已迁出的四个 helper 旧副本，不应误写成文件里只剩旧语义；这些旧副本也没有现行调用方，随整文件退出。
2. 删除该文件及纯旧测试。
3. 运行当前 Silver/QFQ/derived/MACD/KDJ 全套定向测试。

#### M3 开工核验与执行约束（2026-09-05，基线 `e8e2abf9`）

用户已明确要求进入 M3；只退出旧 minute migration 主体，不提前处理 M4 的 specs/executor/catalog/恢复工具，也不删除旧 Console、历史文档、物理数据或 ignored 环境。

逐行复核完整 1,328 行旧模块（32 个顶层函数、10 个 dataclass）和 425 行旧测试（10 项）。CodeGraph `explore/impact/callers` 覆盖 plan、Raw event report、Raw audit；全仓 tracked Python AST import 核验仅命中旧测试一个导入点。bootstrap package exports 未导出该模块；当前四 CLI、正式 assets/checks/jobs/sensors、API/前端和构建配置均无正向引用。名字相似的当前 Raw checks、分区定义和 identity-map asset 不随旧 producer 删除。

| 硬口径 | 精确文件/落点 | 验收 |
|---|---|---|
| 删除旧 minute migration 主体且不留兼容入口 | 删除 `orchestrator/src/orchestrator/defs/bootstrap/stk_mins_migration.py` | 当前模块引用为 0；旧模块和已删 CLI 均不可发现/import；新增静态防回退 |
| 旧测试先分辨用途再退出 | 删除 `orchestrator/tests/test_stk_mins_migration.py`；两条零价格样本先迁入新 `test_stk_mins_raw_value_domain_contract.py` | 对现行 `_raw_value_domain_check` 验证零 low 和全零报价通过，负价格/空值拒绝；不保留旧 audit 实现 |
| 已迁出的 helper 和 CLI 保持 | M1 的 discovery/alignment/check count、M2 四 CLI 和 fixture 均不改实现 | M1 helper/计数、21 命令/246 原案例及 M2B 批准差异、五组现行历史治理全套隔离回归 |
| 正式 Raw/identity-map 链不受误删 | 当前 `stk_mins_checks.py`、`assets/stock_identity_map.py`、readiness/partition/catalog 均保留 | 现行 Raw 合同和 identity-map asset/sensor 测试；asset governance/static gates |
| 不误扩大 M3 | `specs/stk_mins.py`、`specs/stock_identity_map.py`、source method、executor、Raw 恢复工具仍归 M4 | 最终删除文件必须恰好上述 2 份；保留运行文件与本轮基线逐字一致 |

旧测试逐项处置：

| 原测试行/名称 | 结论 |
|---|---|
| 115 `test_plan_is_read_only_and_reports_expected_counts` | 旧 backup/identity 迁移计划，随旧入口删除；当前分区发现/五频对齐已有 M1 独立测试 |
| 143 `test_migrates_raw_history_and_skips_existing_targets` | 旧 backup → Raw 写入，删除；不是现行 prod Raw 恢复工具的测试 |
| 169 `test_migration_requires_source_file` | 旧 backup 缺源行为，删除，不恢复已退役源 |
| 180 `test_registers_only_missing_stock_mins_partitions` | 旧迁移注册 helper，删除；正式 partition 定义与日常注册链保留 |
| 197 `test_reports_runless_raw_events_and_readiness` | 旧迁移 Raw 事件 producer，删除；不删除正式 Raw checks/readiness |
| 238 `test_raw_event_dry_run_does_not_write_events` | 旧 producer dry-run，删除；现行 Silver/QFQ/derived/MACD 事件 dry-run 独立测试保留 |
| 275 `test_failed_raw_audit_blocks_event_reporting` | 旧 producer 审计门禁，删除；当前 Raw 文件门禁与 value-domain 测试保留 |
| 320 `test_raw_price_sanity_allows_legacy_zero_low` | 样本仍代表现行 Raw 规则，迁到当前 check 测试后删除旧测试 |
| 356 `test_raw_price_sanity_allows_legacy_zero_quote_rows` | 全零报价样本仍有效，迁到当前 check 测试；不因源迁移退役而收紧零价格规则 |
| 392 `test_reports_identity_map_events_and_readiness` | 旧 manifest 导入及补事件，删除；现行 lifecycle + seed 生成 identity-map 的代码和测试保留 |

性能与安全预算：

| 项目 | M3 边界 |
|---|---|
| 正式对象/日期/分区、请求/分页、源行/写入行/文件/事件 | 全部 0；只删源码，禁止以验收为由执行旧迁移或触碰正式数据 |
| 新增样本 | 4 个固定案例；每例 1 个代码、1 天、1 频、1 行 Parquet；只写 pytest 临时目录 |
| DuckDB / spill | 现行 SQL 不变；新样本使用显式临时 DuckDB 目录，旧集成测试用既有隔离 runner 将连接 temp 改到测试目录 |
| replace / 事务 / 重试 | 正式实现均不修改；测试只验证现行行为，不新建状态实体或重试逻辑 |
| 耗时/配额 | 删除前完整五组历史治理回归 70 passed / 17.48 秒；生产网络请求与配额为 0；记录删除后同组结果，不增加性能门禁 |
| 拒绝条件 | 出现现行导入、遗失有效规则覆盖、冻结 CLI 差异、正式环境访问或第三个删除文件即停止 |

按文档治理核验，P6A 两份现行 check 治理文档仍把旧 producer 写成可用路径（G1）；本轮将对应句子标为历史事实并注明 M3 退出，不改正式三类 Raw check 口径，不另建方案。完整 Definitions 加载如需验证，只允许无正式实例/网络的隔离模式；不执行 `dg` job/sensor/materialization 或修改历史事件。

#### M3 实施与验收（2026-09-05）

1. 已精确删除上述两份文件，未创建 wrapper、alias 或替代旧迁移入口；从 `e8e2abf9` Git 历史可恢复源码，不需恢复任何物理备份。未删除其它 specs/executor/SQL/template/catalog 或旧 Console 文件。
2. 原旧文件 10 个测试已逐项处置：8 个纯旧迁移测试退出；2 个仍有效的零价格样本在删除前已改测当前 `_raw_value_domain_check` 并通过，额外负价格/空值样本也通过。M1 helper、check count 和 21 CLI 合同没有重录或降级。
3. `test_stk_mins_history_cli_contract_equivalence.py` 增加旧模块/CLI 不存在且不可发现，以及全 orchestrator 运行源码无旧 import 的静态门禁。删除前门禁按预期报旧模块存在（1 failed、2 passed），删除后全绿。
4. 删除前五组完整历史治理回归 **70 passed / 17.48 秒**；删除后同五组加当前 Raw 合同、identity-map asset/sensor 为 **112 passed / 17.85 秒**。另跑合同/静态/新样本组合 **318 passed、696 subtests passed / 6.69 秒**；两组合计 430 项测试，696 个子案例，不包含重复计算删除前基线。
5. 修改/新增测试默认 Ruff 与全 orchestrator `E9,F63,F7,F82`、文档完整性、矩阵与 `git diff --check` 均通过；156 份矩阵无缺失/重复、处理分类数不变，263 个旧产品路径及其 SHA-256 不变。根索引已执行 `codegraph sync/status`，状态 up to date。
6. 查阅了本地 `uv run --no-sync dg check defs --help`：该命令需要实例。没有运行正式 `dg check defs`、job、sensor 或生产读写；本轮通过隔离测试验证 assets/checks/CLI 消费者，不能称为正式部署或整份 code location 的运行验收。测试 DuckDB spill 和 Lake 均为临时目录，instance 使用 fake/ephemeral，网络与正式 `DagsterInstance.get()` 被隔离 runner 拦截。
7. 同步原方案、本 LLD、M0 清单、CodeGraph 快照和 P6A 两份 check 治理文档；不更新新闻关联等其它任务文档。用户随后要求提交：本次在 `dev-interface` 按 M3 的 10 文件白名单归档（6 份文档、2 份删除、1 份修改测试、1 份新增测试），不推送、不自动进入 M4。
8. 删除后以项目 Python 3.13.5 重新解析全仓 2,615 份已跟踪 Python 文件，对旧模块的 import 为 0；与 `e8e2abf9` 对比，运行代码差异仅旧 migration 模块删除，全部删除项恰好两份。CLI fixture 字节完全一致，SHA-256 为 `937a2e9aa42c93c0b7534d2f680a1249d9f96ee2d4f10ce33067543f2ad9f3bc`。首次误用系统 Python 3.11 扫描时不支持仓库已有 f-string 语法，已改用项目环境复核，未修改该无关代码。

复现命令（从 `lake_console/orchestrator` 执行）：

```bash
uv run --no-sync python -m pytest -q --disable-warnings \
  tests/test_stk_mins_history_cli_contract_equivalence.py \
  tests/test_stk_mins_macd_kdj_baseline_single_partition.py \
  tests/test_stk_mins_history_helpers.py \
  tests/test_stk_mins_history_check_events.py \
  tests/test_run_contract_static_gates.py \
  tests/test_asset_governance_contracts.py \
  tests/test_stk_mins_raw_value_domain_contract.py
uv run --no-sync python /private/tmp/lake-retirement-m2a-20260905.5cPIXY/run_isolated_cli_tests.py \
  -q --disable-warnings \
  tests/test_stk_mins_silver_m6_history.py \
  tests/test_stk_mins_qfq_m8c_history.py \
  tests/test_stk_mins_qfq_m8d_events.py \
  tests/test_stk_mins_qfq_m11f_derived_history.py \
  tests/test_stk_mins_qfq_m12_macd_kdj.py \
  tests/test_stk_mins_raw_m4_contracts.py \
  tests/test_stock_identity_map_active_asset.py
```

后续只进入 M4 的单独审计/实施：先处理仍在用的 Raw 恢复工具，再解除 generic old-lake adapter；不把 M3 零引用结论推广到它们。

### M4：重构 Raw 恢复工具并删除 generic old-lake adapter

#### M4 开工对账（2026-09-05，基线 `1b0deb63`）

用户已授权进入 M4。开工核验曾因 Raw/Silver 字段继承规则暂停；历史追溯与用户最新拍板已撤回该阻塞判断：保持现有字段及日常链路不变，`vwap` 差异不处理。本小节保留开工时证据；规则/文档纠正随后提交为 `d2d177bb`，其后的代码实施结果见下文。M4 不包含正式恢复、写湖、补事件、部署或 M5/M6/M8。

| 核验项 | 当前代码证据 | 结论 |
|---|---|---|
| 恢复工具入口与范围 | 完整阅读 `bootstrap/stk_mins_raw_replace_from_prod.py`（989 行）、CLI（76 行）与专属测试（365 行）；CodeGraph `explore/impact/callers` 加全仓引用核验 | 正向运行调用方只有专属 CLI；日常 prod Raw `reuse_existing` 不替代覆盖恢复。仍需按 §6.4 保留业务能力并重构 |
| Raw/Silver 既有字段差异 | `run_contracts/asset_column_schemas.py` 的 `RAW_STK_MINS_SCHEMA` 含 `vwap DOUBLE`；`SILVER_STK_MINS_SCHEMA` 不含它 | 这是既有字段契约差异，不能仅凭差集认定为实现 bug 或待修复技术债 |
| 当前写入与契约一致 | `assets/stk_mins.py::_prod_db_raw_stk_mins_output_sql` 输出 `vwap`；`_create_silver_stk_mins_base_tables` 没有投影它；`_write_distinct_silver_stk_mins_rows` 按 Silver 字段常量写文件 | 当前 Silver 实现确实不输出 `vwap`；未读取正式物理分区，不宣称完成数据盘点 |
| 现行契约有明确测试 | `_silver_stk_mins_extra_metadata` 的 `vwap_policy` 写明排除；`test_stk_mins_contracts.py:191` 和 `test_stk_mins_silver_m5b_contracts.py:536` 明确断言不存在 | 保留这些断言与现行字段；不补列、不删除断言，不作为 M4 待办 |
| 擅改字段的影响 | CodeGraph `impact write_silver_stk_mins_partition` 命中五频日常 Silver assets、Silver history/CLI、Silver replace/CLI | 字段变更会触及保留链路，M4 不做此类变更；这只是已核实的直接影响面，不代替将来真正变更契约时的全消费者审计 |

**原 G0 阻塞判断已撤回，不再要求补 `vwap` 或单独治理。** 历史追溯确认：2026-05-31 的分钟线 Silver 清洗与标准化设计（`c864e139`）已明确 Raw 保留、Silver 排除 `vwap`，见 [`dagster-stk-mins-asset-design.html` §8.7/8.9](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stk-mins-asset-design.html)；随后 `068e5ef2` 落地字段契约与排除断言，`01d25486` 落地资产及检查。字段继承规则于 2026-06-08 的 `9c9812ab`（分钟线 sensor 时窗调整提交）加入，未同步修改上述契约。未取得该规则产生时的原始对话，不推断它原本针对哪个具体漏字段问题。此前只按通用规则认定既有设计为字段缺口，是本次审计判断错误，不是已经证实的运行故障。

**2026-09-05 用户拍板并已落档：** 删除 `orchestrator/AGENTS.md` 整段 Raw/Silver 字段继承门禁，以及根 `AGENTS.md` 第 36 条同义要求，不再强制 Silver 覆盖 Raw 全部字段。Raw → Silver 允许按数据清洗和具体业务契约形成不同字段集合；本次 `vwap` 差异不处理、不列待修复事项、不另设字段治理任务。M4 保持 Raw/Silver 字段、现有字段测试及日常处理链路不变，仅按 §6.4/6.5 修改恢复流程和来源声明，再清退旧适配器。移除一刀切规则不授权随意增删现有字段；既有契约变更审计要求不变。此项已确认，不需要重复拍板，也不代表 M4 已实施或验收。

验证：原恢复工具 10 项测试经既有隔离 runner 全通过（1.07 秒，44 warnings），使用临时 Lake、临时 DuckDB spill、替身源，拦截网络与正式 `DagsterInstance.get()`；未新增或删除任何代码文件，未访问正式数据/实例。性能预算仍见 §6.4.4，未进行生产导出测量，不将历史样本当当前性能保证。

以下为批准的阶段步骤，不因完成开工对账而算作已实施：

本轮实现落点：`paths.py::stk_mins_raw_recovery_run_root` 固定日期/UUID 路径；恢复模块负责计划冻结、逐频候选审计、checkpoint、人工废弃与续跑；专属 CLI 只做参数验证和调用。现有生产只读 source adapter 与 Raw 字段投影不改。正反回归落在 `test_stk_mins_raw_replace_from_prod.py`，覆盖 §6.4.2 全表、目录限制、资源错误、JSON 半写及 CLI。

运营参数对账：`--staging-root` 默认取 `DEFAULT_LAKE_STAGING_ROOT`，只接受该正式根；`--recovery-run-id` 在 plan 可省略并生成 UUID，apply 从已审阅 plan 继承，显式提供时必须一致。两者冻结到 plan/checkpoint，不新增 env/Settings/数据库配置；只作用于本次离线恢复，CLI 报告可见。`--output` 只允许 run 内非保留文件名的报告副本，默认仍为 `plan.json` / `final-report.json`；`--plan-report` 必须属于同一 run，不能借此覆盖 checkpoint、audit 或 candidate。提升前人工废弃通过 `apply --apply --abort-before-promote` 明确表达，必须验证五频仍为原目标且没有任何提升证据；这只是 §6.4.2 已批准动作的 CLI 落点，不增加自动废弃/自动换 run 能力。

1. 先按第 6.4 节重构 `stk_mins_raw_replace_from_prod`：candidate/report/checkpoint 迁正式 staging，删除
   生成正式根 `_staging/_quarantine` 和 backup 的代码，增加逐文件 fingerprint 状态机、重入判定和幂等续跑测试；本阶段不清既有物理目录。
2. 恢复工具新链验收通过后，删除 source method、dataset spec、executor、specs 和 adj factor old event 模块。
3. 清理 bootstrap package exports。
4. 删除旧 SQL templates 和精准测试断言。
5. 修改 enum、17 个 catalog entry 和当前 metadata 说明；Raw 五项固定为
   `bootstrap_sources=(PROD_DB_READONLY,)`。
6. 不新增 lock/pid 文件；同日期未完成 checkpoint 只允许原 run id 续跑，正式 apply 走人工维护窗口。
7. 按第 6.4.4 节验证单日五频、资源错误和阶段记录；5 分钟为提示，不拒绝正确候选。验证 §6.4.2 的 checkpoint 落盘间隙和部分提升后候选丢失分支，不能遗漏人工停止点。
8. 运行恢复工具、catalog、run contract、asset/check contract 测试。

#### M4 实施结果（2026-09-05，基线 `d2d177bb`，随本次提交归档）

先提交两份 AGENTS 与三份口径文档，提交为 `d2d177bb`，未推送；随后按上述步骤先完成恢复工具隔离回归，再退出旧适配器。本次不修改数据集字段，不更改日常处理，不做正式恢复或物理删除。

实际修改逐文件对账（代码路径相对 `lake_console/orchestrator/`）：

| 文件 | 本次实际处理 | 保留与验证边界 |
|---|---|---|
| `src/orchestrator/defs/bootstrap/stk_mins_raw_replace_from_prod.py` | schema version 2；冻结计划、candidate audit、带校验和的原子 checkpoint；五频分步替换、同 run 续跑、提升前人工废弃、失败保全；移除备份和回滚分支 | 原 `ProdStkMinsRawReplaceSource` 的 SQL、投影与调用语义结构相同；候选仍遵守当前 Raw 字段、顺序和类型，不增加 Silver 字段 |
| `src/orchestrator/defs/bootstrap/stk_mins_raw_replace_from_prod_cli.py` | `plan/apply` 保留；新增已批准的 staging/run 参数；输出只能在同 run；`--abort-before-promote` 显式废弃；失败非成功退出 | 不接入页面、API、job、sensor，不保留旧 `/private/tmp` 报告或旧 schema 兼容 |
| `src/orchestrator/defs/paths.py` | 新增 `stk_mins_raw_recovery_run_root`，限定 ISO 单日和 UUID | 原有所有正式路径函数不改；恢复运行时另核 Lake/staging/五频父目录同文件系统及路径无逃逸 |
| `src/orchestrator/defs/bootstrap/__init__.py` | 删除旧 spec/executor 导出，只留包说明 | 不重导出所有 history 函数，不加兼容 alias |
| `src/orchestrator/defs/catalog/lake_assets.py` | 删除旧 enum 成员，修改 §6.4 的 17 项来源声明 | 159 个资产均保留；逐 entry 对比只允许 `ingestion_sources/bootstrap_sources` 差异，asset key/columns/path/partition 等不变 |
| `src/orchestrator/defs/run_contracts/metadata.py` | 只删除 `SourceSystem.OLD_LAKE_BOOTSTRAP` | 不迁移或删除历史 Dagster event |
| `src/orchestrator/defs/duckdb_sql.py` | 删除 §7 的七个 `*_BOOTSTRAP_SELECT_TEMPLATE` | 删除这些赋值后，余下源码 AST 与基线一致，当前 SQL 不改 |
| `src/orchestrator/defs/assets/stk_mins.py` | 改 `_raw_stk_mins_extra_metadata` 来源说明、五个 Raw asset description | 除该 metadata helper 和 description 外，全部顶层 AST 相同；五个 Raw 函数体、日常 SQL、Silver writer 均未改 |
| `src/orchestrator/defs/checks/stk_mins_checks.py` | 只改一条旧 backup 说明 | 去除该文字差异后 AST 相同；规则和数值判定不改 |
| `src/orchestrator/defs/run_contracts/asset_column_schemas.py` | 只改 Raw `vol/amount` 两条旧来源说明 | 所有字段名、顺序、类型 AST 相同；Raw 有 `vwap`、Silver 无 `vwap` 的断言保留 |
| `tests/test_stk_mins_raw_replace_from_prod.py` | 保留业务事实测试，改写旧备份回滚断言，增加状态机/CLI/失败注入 | 最终 38 项测试，22 个参数化子例；不是删除恢复能力的测试 |
| `tests/test_stk_mins_contracts.py` | 删除两项旧 bootstrap SQL 测试及专属 fixture/import | 保留当前字段、Raw/Silver/check/path 测试 |
| `tests/test_adj_factor_contracts.py` | 删除两项旧 bootstrap SQL 测试及专属 fixture/helper/import | 当前 lifecycle/Silver SQL、字段与路径测试保留 |
| `tests/test_old_lake_adapter_retirement.py` | 新增旧入口不可用、AST 无旧 import/enum、catalog 精确值和保留模块存在检查 | 只接受 ignored 缓存形成的无源码 namespace，不允许任何旧 spec 可导入；不删除本机 ignored 缓存 |

实际删除严格等于 §6.1 的 13 个运行文件，以及 `test_stk_mins_bootstrap_spec.py`、`test_adj_factor_bootstrap_spec.py`、`test_adj_factor_raw_bootstrap_events.py`、`test_adj_factor_silver_bootstrap_events.py` 四份专属测试。没有删除第 18 个文件；这些 Git 文件可由 `d2d177bb` 历史取回，但不提供运行兜底。`adj_factor_silver_history.py`、当前 Silver/QFQ/derived/MACD-KDJ/history events、canonical/指数 Gold 工具及 21 命令 fixture 保留。

实际安全与行为对账：

| 约束 | 已实现与验证 |
|---|---|
| plan 不改正式数据 | 只在 staging 写 plan/checkpoint；冻结 source TaskRun、股票池、五频聚合和五个旧目标指纹；禁止用旧根和跨文件系统路径 |
| 所有候选先完成验证 | 顺序生成五频 candidate，核 schema/顺序/类型/主键/空键/日期/频率/股票集合/时间范围/行数；全部冻结后再次核源和旧目标，才进入 promote |
| 替换后进度未写下 | 1/5/15/30/60m 分别注入 replace 后中断，以及 checkpoint 写入失败；目标等于候选时重新完整审计，不重复导出或覆盖 |
| 部分完成、剩余候选异常 | 候选丢失/改变时保留现场，禁止新 run、禁止废弃已提升 run；只有恢复完全相同的冻结字节和 audit 后才允许原 run 续跑 |
| 提升前废弃/完成后重入 | 五频原始状态且无提升证据才可显式废弃；包括被拒绝计划中原本缺失且仍缺失的目标，后来出现文件则拒绝废弃。已废弃 run 不能 apply。完成后重入只审计，不查生产源、不重新导出或替换目标 |
| 资源和慢任务 | 模拟 ENOSPC、DuckDB OOM 均保留 checkpoint，候选阶段失败零正式改动；模拟 301 秒仍可成功并给出 slow warning。不宣称已测量当前生产导出速度 |
| 人工维护窗口 | 无 lock/pid/后台服务；同日未完成 run 阻止新计划，但不伪装成跨进程互斥。正式使用仍须人工暂停同日 writer、确认残留会话结束 |

最终验证记录：

1. 既有隔离 runner `/private/tmp/lake-retirement-m2a-20260905.5cPIXY/run_isolated_cli_tests.py` 拦截网络与正式 `DagsterInstance.get()`，使用临时 Lake、staging、DuckDB spill 和替身生产源。
2. 最终联合运行 A/B 两组：A 组覆盖恢复工具、旧适配器退场、stk_mins/adj-factor/metadata/asset governance/static gates、21 命令 fixture；B 组覆盖当前 Silver/QFQ/event/derived/MACD-KDJ/adj-factor/identity-map/Silver contract。合计 439 项测试、750 个子例全部通过（33.61 秒，1577 条既有依赖等 warning）；已包含最后补充的“缺失目标的停止计划安全废弃”反例。没有正式数据库或湖写入。
3. `/private/tmp/lake-retirement-m4-20260905.aUDbb3/audit_boundaries.py` 对照 `d2d177bb` 验证精确 17 文件删除、七项 SQL 赋值外 AST 相同、字段/当前处理/source adapter 不变、159 资产仅 17 项来源变化、现行四 CLI/共享 contract/fixture、Local Lake Reader、Ops/Biz/前端/Wealth/旧 Console/正式 bin 不变。该脚本是临时只读审计证据，不是新运行依赖。
4. 10 个新实现相关/干净修改文件完整 Ruff 通过；全体修改 Python 文件逐诊断对比基线，新增问题 0。`assets/stk_mins.py` 既有 8 项、checks 1 项、duckdb_sql 1 项、metadata 2 项共 12 项历史 lint 问题未扩大；不为清退顺手改变原日期逻辑。整个 orchestrator `src/tests` 的 `E9,F63,F7,F82` 检查通过。
5. 全仓程序引用扫描排除防回退测试后，旧模块路径、`OLD_LAKE_BOOTSTRAP`、`old_lake_root`、七个旧 SQL 常量、旧 spec/source type 均无匹配。旧 Console 263 路径及其清单 SHA-256 未变；文档矩阵仍为 156 份、无遗漏或重复。文档完整性和 `git diff --check` 另作交付检查，不代替代码安全证明。
6. CodeGraph `explore/impact/callers` 覆盖恢复入口、旧 spec/executor/event、当前资产/测试和 API/前端消费者；对 `cn_a_minute_gold_history._DatasetSpec.source_path` 与旧后台通用 callback 的同名误命中逐条看代码排除，未删除这些保留能力。根索引 `codegraph sync/status` 已完成，无需新建索引；架构快照同步 M4，跨子系统依赖方向和 dependency matrix 不变。

验收边界：这是代码实现与隔离回归结果，不是生产恢复验收。未进行真实 prod 导出、正式文件替换、正式 Dagster 装配执行/事件写入、断电测试或历史数据删除；不承诺五文件组级原子，也不承诺自动处理不可重建候选。用户已要求提交，本次按 35 文件白名单归档，不推送；真实恢复另行确认日期、容量和维护窗口。本轮到 M4 为止，不自动进入 M5–M8。并行任务的 `wealth/docs/pages/wealth-exploration/sector-analysis-implementation-design-v1.md` 与 `wealth/docs/pages/wealth-exploration/sector-analysis-low-level-design-v1.md` 不属于本专项，未触碰、未纳入提交范围；上述 Wealth 保护结论针对运行代码。

### M5：合并模板、收敛证据摘要并删除旧文档

1. 先把有效检查项写入正式模板和性能治理文档。
2. 把 14 份旧 `stk_mins` 文档中仍需追溯的 bootstrap/修复数字和数据语义压缩进现行迁移总账或正式
   stk_mins 设计；不复制旧命令、路径和执行步骤。
3. 更新 current/mixed 文档、README、onboarding、research 和 Dagster 设计中的全部引用。
4. 删除三个旧模板。
5. 按第 9.4.2–9.4.3 节精确删除 86 份纯旧 Console 文档，不创建 archive/tombstone。
6. 运行全仓文件名/路径反向引用扫描和文档完整性检查。

M5 不提前把仍存在的旧 Console 代码写成“已删除”；当前规则和 README 的最终事实在 M6 原子同步。

#### M5 实施对账（2026-09-05，随本次提交归档）

基线 `dev-interface@5f834b02`，该基线已经包含 M4 提交 `68f97744`。本轮目标、依据和范围就是上文 M5 六步；
遵循文档治理 skill 的 current/mixed/legacy 分类，以当前代码和逐文件矩阵决定处置，不按 snapshot/backup 等关键词删除业务能力。
本轮修改 46 份文档/规则/skill、删除精确 89 份文档，不修改运行代码、测试或数据。历史 §M0–M4 的数字保留其原基线含义。

| 硬口径 | 落点与实际处理 | 核验结果 |
|---|---|---|
| 先保留有效检查，再删旧模板 | 正式 onboarding 模板新增 7A `source-contract-budget`、改写 §14 `history-recovery`；性能治理新增 §6.4 `prod-readonly-export` | 源参数/fan-out/三类字段、类型与精度、请求/连接/内存/文件成本、候选/提升/续跑、只读/白名单/流式、真实对账六组要求均可从正式入口找到 |
| 不照搬失去上下文的旧规则 | 逐字段说明 Raw/Silver 合法差异；日期按层和语义决定；小文件/低频耗时按实测预算；只读范围按当前 source contract | 不补回 vwap，不恢复 Raw⊆Silver；保留 Raw 恢复读取有界 `ops.task_run`，不套旧模板 raw-only 权限；服务端游标与 DuckDB COPY 均可在有界预算下使用 |
| 保留必要历史结果，不保留旧手册 | 单一历史总账 §2 保留正式初始化分区/行数/事件；§3 保留事故、clean_next 重建、BSE 30m、多频污染修复与代码集合差异；§4 指向现行指标方案 | 数字来自原文点时结果，不是本轮物理扫描；未映射的 6,257 个日-代码未冒充已解决；旧命令不复制，旧 11 列不成为当前 Silver 门禁 |
| 先解除引用依赖 | docs 索引/S0、onboarding skill、规则、两份趋势通道及指数/九转/分钟设计切换到正式模板和总账 | 89 文件名在全仓 tracked 文本中的剩余命中只在本专项三份清单/历史记录，无现行正向链接或代码读取引用 |
| 混合文档局部处理 | Phase 2、adj_factor、Raw readiness 等保留历史事实及正式运行设计，旧 spec/executor 不再可执行；Raw 恢复指向 M4，不改 Silver 恢复合同 | 保留 2026-07-27 的 109.973 秒、1,776,093 行等证据；旧物理位置只标历史，不称已删除；正式库写入/源验证未执行 |
| 不误删未开发方案中的有效设计 | 涨跌停方案撤回旧湖 bootstrap、固定 prod gap 日期和旧湖推算的预算；保留 §6–9 字段/业务键、§11 日常来源、§12.4–12.7 审计/事件绑定/幂等/计数门禁 | 新全历史来源和预算列为该数据集开工前的未验证项，不虚构可行性，不要求在本专项实现替代接入 |
| 删除范围不扩大 | 从固定基线矩阵提取 86 份 `DELETE_LEGACY_DOC` 与 3 份 `DELETE_AFTER_MIGRATION`，逐文件确认无基线后变更/符号链接后删除 | 实际删除恰好 89，无目录递归删、无 archive/tombstone；原文可从 Git 基线或后续提交父版本恢复 |
| 当前文档防误删 | §9.4 补 9 份：6 保留、3 局部改；原 3 保留项纠正为仅改模板链接 | 矩阵 165 唯一路径，处理码 37 current / 14 mixed / 25 keep / 86 legacy delete / 3 migrate-delete；25 份 keep 字节一致，3 份链接变更外正文一致；意外缺失和未归类均 0 |
| 业务与环境边界不变 | 263 个旧产品文件、orchestrator src/tests、Foundation Local Lake Reader、frontend/Wealth 源码、reports、正式 bin 保护核验 | 这些保护目标相对基线无差异；本轮没有 CLI、ClickHouse、Ops Snapshot 变更，未访问/删除物理湖或 ignored 环境；跨子系统依赖方向不变 |

M6 延后项不是 M5 漏项：

1. `AGENTS.md`、`scripts/AGENTS.md`、frontend QA skill、架构 CodeGraph 快照及四份 Wealth 分钟 API 文档，待旧产品原子删除后再改成“已清退”的最终时态，本轮不改。
2. `lake_console/AGENTS.md`、README、S0 和风险登记，本轮只解除旧文档引用/标明冻结边界；旧产品仍存在的事实、旧入口操作章节和历史测试命令不提前整段删除。M6 负责同步清零正向旧入口。
3. 物理数据归 M8，经具体清单确认再删；ignored 环境另轮精确处理。停牌 CSV 和现行隐性依赖 TODO 保留。

验证记录与限制：

- 临时只读核验 `/private/tmp/lake-retirement-m5-20260905.q040Vb/verify_m5.py`：固定基线 89 删除清单、165 矩阵计数/唯一性/预期缺失、25 保留文件内容、3 仅链接变更、263 旧产品内容和保护运行目录检查通过；全仓旧标识/路径候选全部归类。临时脚本不是产品依赖；后续复核以本节口径和 §9.4 固定清单重跑，不依赖临时目录永久存在。
- 已修改 Markdown/HTML 的本地目标链接核验：新增死链 0；10 份 HTML 的受检结构（section/table/row/cell/pre）无新增不平衡、id 无重复；正式模板两个新锚点和性能治理新锚点均可定位。未做浏览器视觉验收。
- `python3 scripts/check_docs_integrity.py` 与 `git diff --check` 通过。完整性脚本仅证明路径/索引等检查，不替代本节内容、删除集合及保护目标对账。
- CodeGraph `status/explore/impact` 配合当前代码核验恢复 CLI → Raw 恢复 → `ProdPostgresResource`/受控 prod adapter → catalog/测试；确认有界 Ops 状态读取不可按旧模板禁止。收尾执行根 `codegraph sync/status`，索引正常；无新运行边界，不需更改 dependency matrix。
- 未重跑业务回归、正式 `dg check defs`、真实恢复或 Tushare/prod 请求，因为本轮没有代码/契约实现；不把 M4 的隔离测试结果冒充 M5 生产验收。并行板块分析代码/测试修改不属于本专项，未触碰、不纳入上述保护结论。

用户已要求提交 M5；本次在 `dev-interface` 按精确 135 文件白名单归档（46 修改、89 删除），不推送。提交前 HEAD 为 `58d316c0`；并行板块分析代码、测试及两份 Wealth 文档已在该提交独立归档，不纳入本专项差异。本轮到 M5 为止，单独获准进入 M6 后才删除旧 Console 产品代码。

### M6：原子删除旧 Console/Kopia并同步当前规则

1. 精确删除旧 frontend/backend/tests/entrypoints/example config。
2. 同轮更新 AGENTS、CODING_STANDARDS、skills、README、当前架构图为清退后事实，并移除所有正向入口。
3. 保留 reports、正式 bin、orchestrator 和 ignored 环境。
4. 反查 Wealth `local_lake` 全部当前 Reader/API/page 链和 optional dependency 未变；原四 Reader 清单不是上限，还包括当前 turnover insight、trend channel 等新增消费者。
5. 运行仓库引用清零 gate。


#### M6 实施结果（2026-09-05，基线 `dev-interface@3ed4c6ca`，已提交 `63be03af`）

本次授权是“继续推进 M6”。以下是当前工作树实施证据，不覆盖旧阶段点时记录，不代表已经部署或正式服务停机。

**范围和前置审计**

- CodeGraph status/explore/impact/callers 核验 Kopia → 旧 API/CLI/UI/测试，以及六类 Lake Reader → Biz/API。
  KopiaPrewriteBackupService 的二层影响 20 个符号都在旧边界内；当前 Reader 的空 callers 结果另用
  impact 和真实 import/构造点补核，不能把索引空结果当无消费者。
- 删除前扫描 2,410 份保留 tracked Python 的 AST（含直接、from 和字面量动态导入），
  并补扫全仓 tracked TS/配置/脚本/构建入口；旧 backend 正向导入与外部当前调用均为 0。
- 固定清单恰好 263 文件：backend 181、frontend 65、根专属 tests 14，另有旧 CLI、联合启动脚本、
  示例配置各 1。逐文件核对基线内容、真实路径和非符号链接后，同轮删除；没有递归删除目录。
  262 个文本文件使用补丁删除，1 个旧 UI PNG 用精确单文件删除；未运行任何旧入口。
  “同轮原子”指前后端及外围作为一个交付集合，不声称文件系统提供 263 文件事务。
- 2,140 个受保护 tracked 文件内容指纹与基线一致：正式运行源码、21 命令 fixture、整个 src、
  主 frontend、Wealth 源码、reports、两项 ClickHouse bin 和根 pyproject。
  Lake Reader 保护为全目录 12 文件 / 6 类，包含 turnover insight 与 daily trend channel，不局限于原四类。
- 旧 Console 环境范围内 11,692 个 ignored 文件的路径、size、mtime、inode 集合与删除前一致；
  只核软件环境元数据，不扫描旧湖数据内容。旧 config.local.toml 仍保留；其残留 Kopia 配置没有当前消费者，
  不算生效配置，也不据此删除本机配置。
- 本轮预算：正式 Lake/DB/Tushare 查询、业务文件写入、Dagster event、物理数据删除均为 0；
  只读代码约 2,400 份，回归使用临时文件/替身。构建和 compileall 输出在本轮临时目录，
  没有清空旧 Console 环境或原构建输出。

**实现修改逐文件对账**

| 文件/精确范围 | M6 实际处理 |
|---|---|
| §8 的 263 文件 | 同轮精确删除；无空壳 package、alias、wrapper 或新旧双入口 |
| `orchestrator/tests/test_run_contract_static_gates.py` | 删除仅用于旧后台的两个目录常量；derived 全源扫描只遍历 DEFS_DIR；删除两个旧 writer 文件不存在断言。现行 CLI 检查和负向 derived 标识门禁保留 |
| 根 `tests/architecture/test_lake_console_retirement_guardrails.py`（新增） | 13 项检查：旧产品源码/入口为空、全仓 AST 无旧导入、当前运行/版本化配置无 Kopia/旧入口引用、当前 Reader/Ops snapshot/ClickHouse/停牌 CSV 仍在；反例覆盖直接/from/动态 import，并允许当前模块和历史文本。源码枚举包含新增非 ignored 文件，过滤已删 index 项，不要求 ignored 目录消失 |
| 根 `AGENTS.md` | 仅把旧 Kopia“现存冻结”改为已清退，保留禁令与正式路径 |
| `lake_console/AGENTS.md` | 去除旧 API/UI/CLI/配置开发流程；收敛正式工程规则。保留 Prod 只读白名单、stock_mins readiness 窄例外、独立资源、性能/安全/人工批准门禁与停牌 CSV TODO，不把 readiness 的窄投影误施加到 Raw 恢复 |
| `orchestrator/AGENTS.md` | 改当前定位，撤回旧湖允许输入、旧模型/clean_next 实现口径；按现行 resources.py 区分本机 clickhouse 与 prod_clickhouse，未更改资源或权限 |
| `scripts/AGENTS.md` | 删除旧联合启动规则；保留两个正式 ClickHouse 工具的操作边界 |
| `.agents/skills/frontend-qa/SKILL.md` | 退出旧 UI 路由/build；保留 frontend 与 Wealth 各自验证和设计边界 |
| `.agents/skills/lake-dataset-onboarding/SKILL.md` | 退出旧 Console/Sync Center 技能入口，只指向正式 Dagster |
| `lake_console/README.md` | 重写现行索引，移除全部旧启动、配置和 Kopia 操作；明确 CLI/Reader/ClickHouse/数据保留 |
| `docs/README.md` | 更新 M6 状态及 165 份矩阵索引，不再标成“尚未实施” |
| `docs/architecture/codegraph-architecture-snapshot.md` | 当前节点移除旧 UI/后台，补正式 Lake → 六类 Reader → Biz/API → Wealth 链和本轮影响面 |
| `docs/architecture/goldenshare-repository-onboarding-overview-v1.html` | 仓库地图、维护入口、旧根说明和验证表全部切为清退后事实，不再提供旧启动/测试命令 |
| `lake_console/docs/architecture/dagster-data-system-architecture.html` | 更新 M6 状态；保留 ClickHouse、Dagster 与 Wealth 链 |
| `dagster-bootstrap-legacy-links.md` | 总账标明旧产品已退场；历史数字不改 |
| `dagster-new-lake-asset-catalog-design.md` | 旧系统行明确历史/已退场；正式 catalog 继续保留 |
| `dagster-derived-minute-bars-90-120-contract-rebuild-low-level-design.md` | 旧 backend 部分改为已完成清退记录，不再要求改造已删 UI；当前计算合同不改 |
| `dagster-index-daily-raw-by-date-prod-db-migration-plan.md` | 旧 prod_core_db 行明确为开发前历史依据 |
| `dagster-index-daily-raw-by-date-prod-db-migration-low-level-design.md` | 旧文件退出“可复用模式”；当前实现仍指向正式 prod_db/index_daily.py |
| `dagster-stk-nineturn-dataset-onboarding-low-level-design.md` | 明确旧 exporter/manifest 交接是一次性历史，不恢复旧 CLI；当前日常链和校验保持 |
| `docs/datasets/ths-daily-valuation-fields-rebuild-plan-v1.md` | 只将旧 export 文件/测试改为 Git 历史证据，去掉死链接；生产字段和验收不改 |
| `docs/governance/prod-postgresql-raw-direct-serving-phase-one-lld-v1.md` | 旧 Console mapping 退出当前消费者和当前依据；生产迁移正文与其余消费者保留 |
| `docs/governance/engineering-risk-register.md` | 保留事故数字和修复证据，旧执行命令改历史说明；不把新 Raw 恢复当旧事故工具 |
| Wealth 股票分钟 API 的 benchmark / implementation / LLD / M2 gate 四文件 | 只改旧后台时态和禁止恢复说明；API、Reader、页面与性能合同不变 |
| 上位专项方案、本 LLD、M0 清单 | 同步当前 M6 结果；不改写 M0–M5 的历史检查记录 |

上述 Dagster 简写文件均位于 `lake_console/docs/design/`；
Wealth 四文件全名仍见 §9.4。CODING_STANDARDS 的旧来源示例已在 M4 修改，本轮复核通过，
负向 old_lake/backend 禁令保留，不为“每个阶段都改一次”制造无意义差异。
§9.4 矩阵未新增对象，仍是 165 唯一路径；M6 只完成此前明确延后项。

**验证证据**

| 验证 | 结果 |
|---|---|
| 删除前当前 Reader/API/Ops snapshot/边界回归 | 140 passed，16.18 秒 |
| 删除前编排静态门禁 + 21 CLI 冻结行为 | 226 passed / 246 subtests，5.92 秒 |
| 新清退检查的删除前反例 | 正确失败，恰好列出 263 个仍在的旧产品文件 |
| 删除后同组后端回归 + 清退护栏 | 首次 152 passed；随后补运行/配置禁止项，护栏最终 13 passed；原 140 项仍通过 |
| 删除后编排/CLI/Raw 恢复/ClickHouse/catalog 七组 | 304 passed / 268 subtests，12.13 秒；不访问正式 Dagster/网络，临时 DuckDB spill |
| Wealth 详情页、指数分钟控制器、九转三组 | 6 文件 / 60 passed |
| 运营后台手动任务、任务记录/中心、数据集详情/审计 | 5 文件 / 37 passed |
| frontend / Wealth | typecheck、build 通过；frontend check:rules 通过。保留 chunk >500 kB 提醒，不在清退中做拆包改造 |
| Python 静态 | 两份变更 Python 的 Ruff check 通过；新文件 formatter 通过。旧 static gate 在 HEAD 原有两处折行差异，本轮不夹带全文件格式化；无新增 lint 问题 |
| compileall / 两项 ClickHouse bin | 编排源码编译通过；bin 只做 bash -n，不执行启动或隧道 |
| 文档 / 差异 | 文档完整性、165 矩阵计数/唯一性、25 KEEP 字节一致、两份 HTML 结构/id、新增死链 0、git diff --check 通过 |
| 删除与保留对照 | 恰好 263 D，2,140 保护文件内容一致，11,692 ignored 文件元数据一致；无新增正向运行引用 |
| CodeGraph | 根 sync/status：2,949 files / 53,540 nodes / 129,954 edges，索引最新，未重建 |

可复跑的核心命令（均从对应工程根执行；正式资源仍禁止）：

```bash
# 仓库根
.venv/bin/python -m pytest -q tests/architecture/test_lake_console_retirement_guardrails.py
.venv/bin/python -m pytest -q tests/test_stock_mins_reader.py tests/test_major_index_mins_reader.py tests/test_stock_nine_turn_reader.py tests/test_index_nine_turn_reader.py tests/test_major_index_turnover_reader.py tests/test_stock_daily_trend_channel_reader.py tests/web/test_stock_detail_minutes_api.py tests/web/test_index_detail_minutes_api.py tests/web/test_wealth_stock_minute_nine_turn_api.py tests/web/test_wealth_index_minute_nine_turn_api.py tests/web/test_wealth_stock_trend_channel_api.py tests/test_dataset_status_snapshot_service.py tests/architecture/test_subsystem_dependency_matrix.py tests/architecture/test_platform_legacy_guardrails.py tests/architecture/test_operations_legacy_guardrails.py
npm --prefix wealth run test -- src/pages/stock-detail/StockDetailPage.test.tsx src/pages/index-detail/IndexDetailPage.test.tsx src/features/index-detail/controller/useIndexMinuteSeries.test.tsx src/features/nine-turn/controller/useNineTurnSeriesRegistry.test.tsx src/features/nine-turn/model/nineTurnAdapter.test.ts src/features/nine-turn/model/nineTurnChartAdapter.test.ts
npm --prefix frontend run test -- src/pages/ops-v21-task-manual-tab.test.tsx src/pages/ops-v21-dataset-audit-page.test.tsx src/pages/ops-v21-dataset-detail-page.test.tsx src/pages/ops-v21-task-records-tab.test.tsx src/pages/ops-v21-task-center-page.test.tsx
python3 scripts/check_docs_integrity.py
git diff --check
```

编排回归从 orchestrator 根使用既有临时隔离 runner，选择
test_run_contract_static_gates、test_stk_mins_history_cli_contract_equivalence、
test_stk_mins_raw_replace_from_prod、test_prod_clickhouse_market_breadth_batch_sync、
test_dc_daily_technical_clickhouse_bootstrap、test_dc_daily_technical_clickhouse_readiness、
test_etf_daily_catalog 七份测试。runner 禁止 DagsterInstance.get 和 socket.connect，
测试 DuckDB spill 改到 tmp_path；未运行正式 dg check/list defs。后续若临时 runner 不在，
先按相同隔离要求建立测试环境，不能直接把命令指向正式环境。

临时只读范围/文档校验脚本位于
`/private/tmp/lake-retirement-m6-20260905.yrlBQW/`；
这是本轮证据而非长期产品依赖。后续复核以 Git 基线、§8 固定删除范围和 §9.4 矩阵为准。

**阶段结论**

M6 实施及定向回归完成，已按 292 文件白名单提交 `63be03af`（263 删除、28 修改、1 新增），未推送。用户已授权进入 M7，全量验收与最终差异复核见下一节；
正式 definitions 检查仍须依 §12.3 单独授权。未停启任何正式服务、未进行线上 UI smoke，
不把构建与 mock 页面测试说成部署验收。M8 仍须确认具体数据清单；停牌 CSV、reports、
物理湖、ignored 环境与 Ops snapshot 均未删除。无新增待拍板设计项。

### M7：全量验证与差异复核

1. 执行第 12 章验证矩阵。
2. 逐项对照上位方案和本文 acceptance checklist。
3. 只 stage 本专项白名单；禁止 `git add .`。
4. 检查 staged name-status 和 staged diff，确认无物理数据、ignored 环境和用户无关改动。

#### M7 首轮验收记录（2026-09-05，基线 `dev-interface@63be03af`）

**首轮历史结论：当时尚未通过全部门禁。** 下表和失败记录保留原始证据，不代表当前还有相同待办；
用户此后批准两处测试修正和 Definitions 检查，当前结果以本节“续轮收口”小节为准。不进入 M8。

范围：第 12 章全量测试、现行 Reader/API/前端和 Ops snapshot 保护、各阶段实际差异、文档复扫。
测试均采用临时文件/替身资源；系统层禁止网络和 `/Volumes` 写入，禁止读取正式 Lake、staging、旧湖
及正式 Dagster home。测试 runner 在收集前禁止 `DagsterInstance.get()` 和真实 PostgreSQL 连接，
只把默认 DuckDB spill 改为测试临时目录，显式临时配置保持原样。不启停正式服务，不执行生产恢复。

| 门禁 | 本轮实际结果 | 判定与限制 |
|---|---|---|
| orchestrator 全量 pytest | 3,010 通过、3 失败，1,137 子例通过；279.24 秒 | 已完整执行，但首次未全绿；失败见下表 |
| 九转文件独立进程复跑 | `test_major_index_nineturn_m4b.py` 18 项通过；3.77 秒 | 重复覆盖首次中的 18 项，不能与 3,010 相加；正式 1 GiB 门禁未改 |
| 根架构 + 6 Reader + 分钟/九转/趋势 API + snapshot service | 242 通过、1 失败；21.93 秒 | 失败来自既有字符串扫描，非清退回归 |
| Ops snapshot 查询/CLI/worker/API 补充回归 | 40 项通过；5.47 秒 | snapshot 能力没有清退，状态失败隔离测试保留 |
| frontend | 40 个文件、149 项通过；typecheck、规则、build 通过 | 构建输出在临时目录，有既有大 chunk 提醒；不是线上 smoke |
| Wealth | 6 个文件、60 项通过；typecheck、build 通过 | 股票/指数详情、分钟和九转合同；mock 不等于正式页面验收 |
| 格式整理后的定向回归 | CLI/adj-factor/旧适配器/分钟合同 184 项、246 子例通过；根清退护栏 13 项通过 | 21 命令 fixture 未改；没有借格式化改参数或断言 |
| DuckDB resource 补充隔离验证 | 临时测试 2 项通过 | 验证默认工厂无参委托、连接透传及成功/异常清理；不替代失败的原测试 |
| 编译与静态检查 | 编排 `compileall`、全 `src/tests` 致命 Ruff、ClickHouse 两个 bin 语法通过 | 36 个专项存续 Python 完整 lint 对比；4 文件共 12 条既有诊断未扩大，不宣称全仓风格全绿 |
| 文档 | 165 矩阵对象存在性/唯一性/分类通过；76 保留文档 + 3 控制文档链接检查、12 HTML 结构/id、完整性检查通过 | 89 个批准删除路径不存在；25 KEEP 与 M5 前基线字节一致；未归类命中和已删文档入链为 0 |
| Git 与保留范围 | M6 263 删除与白名单一致；八个专项提交未修改根 `src/`、`frontend/`、`wealth/src/`、reports | 排除并行提交，不用跨整段历史 diff 误算其它任务；ignored 11,692 文件元数据未变 |
| 正式 definitions | 未执行 `dg check defs` / `dg list defs` | 等待独立命令授权，不能据静态 catalog 数量宣称正式 Definitions 验收完成 |

首轮失败逐项归因与当时提出的处理方案（此后已获批准并实施，结果见续轮收口）：

| 项目 | 当前代码事实 | 下一步与禁止做法 |
|---|---|---|
| 两项九转 daily serving history 测试超内存 | `major_index_nineturn_history._peak_rss_mib()` 读取整个进程的历史峰值 `ru_maxrss`；全量测试时为 1025.17/1025.78 MiB，超过既有 1024 门禁。独立文件全部通过，相关代码/测试不在专项改动中 | 后续全量测试按文件分新进程隔离该资源敏感组，其余测试仍全部覆盖。保留首次失败证据；不提高生产内存上限、不屏蔽 OOM 测试、不伪称修复生产代码 |
| `test_duckdb_resource_uses_configured_connection` | 原测试直接打开默认资源并断言 `/Volumes/datasource/.goldenshare_duckdb_tmp`；本轮 runner 为避免正式路径写入，将默认 spill 定位到临时目录，因此断言失败。原测试来自 `d946d440`，本专项未修改资源或此测试 | 建议仅重构该单元测试：mock 资源层连接工厂并断言无参委托/清理；保留既有临时目录真实连接设置测试及默认常量合同测试。两项临时验证已证明建议可行；不修改正式默认路径，不伪造查询结果或放行移动盘写入 |
| `test_active_code_does_not_reference_legacy_dataset_run_names` | 既有测试用子串 `execution_canceled` 扫描，命中 `sector_analysis_daily_task_executor._raise_if_execution_canceled`。该方法实际检查当前 TaskRun 取消意图并抛 `IngestionCanceledError`，由并行提交 `58d316c0` 引入；测试最近提交为 `853e3ca1` | 建议另行确认只调整扫描测试：保留旧执行合同/字段的真实禁止项，区分合法局部函数名并添加正反例。不删除取消函数，不改生产 TaskRun 逻辑，不以整文件白名单掩盖真正旧字段；本轮仅记录 |

**本轮实际文件修改**（除三个专项文档外，仅以下格式整理）：

| 路径（相对仓库根） | 修改 | 语义检查 |
|---|---|---|
| `lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_mins_qfq_macd_kdj_history_cli.py` | 参数声明折行 | AST 与 M6 提交相同 |
| `lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_mins_silver_history_cli.py` | 错误文字折行 | AST 与 M6 提交相同 |
| `lake_console/orchestrator/tests/test_stk_mins_history_cli_contract_equivalence.py` | decorator 折行 | AST 相同 |
| `lake_console/orchestrator/tests/test_adj_factor_contracts.py` | 移除多余空行 | AST 相同 |
| `lake_console/orchestrator/tests/test_old_lake_adapter_retirement.py` | 常量/断言/参数折行 | AST 相同 |
| `tests/architecture/test_lake_console_retirement_guardrails.py` | 标准库导入顺序与空行 | 导入集合与其余 AST 相同；13 项回归通过 |

这是按 §12.2 格式要求处理专项新引入的差异；未整文件格式化已有格式债务的其它 19 份 Python。
2,140 个 M6 保护文件中，2,138 个字节不变，只有上述两个 CLI 格式改变且 AST 不变；其余四份测试
不属于该保护指纹集合，已单独比对。六份修改文件完整 Ruff/formatter 通过。无新功能、字段、配置、
运行入口或跨子系统依赖，依赖矩阵不变。

CodeGraph `explore` 本轮核对 Definitions 装配入口、DuckDB 连接工厂和 resource 委托；结合既有
`callers/impact`、当前代码与 Git 差异复核 CLI、恢复、Reader、API 和前端消费者。没有以图中的
名称匹配替代实际代码；根索引 `sync/status` 已通过（2,949 files / 53,540 nodes / 129,954 edges），未创建独立子项目索引。

文档复扫另发现三个专项控制文档此前未进入同一链接集合，LLD 内有 3 处指向已删 backend 源码的
链接。已核对 `3ed4c6ca` 原文件，把链接改为“提交号 + 当时路径/行号”的历史证据，不把历史源码
恢复到工作树；§16.14 也注明旧代码依赖已退出 Git、物理删除仍未授权。完成修正后再得到上表的零死链结果。

证据根：`/private/tmp/lake-retirement-m7-20260905.yEELOh`。主要结果为 `orchestrator-full-first.xml`、
`nineturn-fresh-process.xml`、`root-acceptance.xml`、`ops-snapshot.xml`、`resource-delegation.xml`、
`format-regression.xml`、`root-format-regression.xml`；`readonly-tests.sb` 与 `run_isolated_tests.py`
记录隔离条件，`audit_docs.py`、`audit_python.py`、`verify_scope.py` 是本轮只读核验工具。
这些临时文件不是产品依赖或永久门禁；由本任务使用至 M7 review 完成，届时仅按精确路径清理，不
接入正式运行。本节数字与 Git 基线保留为持久摘要，不能假定临时文件永远可用。

**正式 Definitions 命令及边界**（首轮待授权；续轮已批准并执行）：

- 工作目录：`/Users/congming/github/goldenshare/lake_console/orchestrator`。
- 目标 `DAGSTER_HOME`：`/Users/congming/.goldenshare/dagster_home`，不是测试 instance。
- 完整命令：`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home uv run --no-sync dg check defs`；
  `DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home uv run --no-sync dg list defs --json`。
- 目的：验证正式代码位置能加载，并核对现行 asset/check/job/sensor，补足 §12.3。
- 范围：定义加载/配置读取；不触发任务、sensor、asset check 执行、分区注册、物化或补事件，不写湖或数据库业务数据，不启停常驻服务。加载可能建立短生命周期子进程并产生 CLI 缓存/日志；若要求超出批准范围的正式状态写入则停止。
- 风险与退出：先核本地命令帮助和当前配置；定义错误只记录失败，不借机运行修复任务。结束检查子进程即停止，不需要数据回滚；不得清库、改事件或重启正式服务来让检查通过。

收口顺序：用户确认测试修正范围及命令授权 → 修正/回归测试门禁 → 分进程覆盖完整编排测试集并跑
正式 Definitions → 复核九文件及任何另批测试的精确差异 → M7 单独验收。M8 仍需另外确认数据清单。

#### M7 续轮修正约束（2026-09-05，用户已同意）

用户已明确同意修正上述两处测试，并按已列明的范围执行 Definitions 检查。授权只用于本节，不包含
任务执行、物化、补事件、服务停启、业务数据写入、M8、提交或推送。上一节保留首次失败证据。

| 硬口径 | 修改/验证落点 | 禁止项与反例 |
|---|---|---|
| DuckDB 资源只委托统一工厂 | `tests/test_duckdb_connection.py` 用 context-manager mock 验证无参调用、原连接透传、正常/异常退出；真实临时连接和默认配置合同测试保留 | 工厂失败或消费者抛错必须原样传播；不调用正式默认 spill，不修改 `resources.py` / `duckdb_connection.py` |
| 旧模型扫描区分片段与完整名称 | `tests/architecture/test_dataset_maintenance_refactor_guardrails.py` 保留其它原有禁止片段；`execution_canceled` 按完整标识符/字符串边界匹配 | 合法 helper 名称及调用允许；同一 helper 内的旧字段、参数、事件字符串、属性访问仍拒绝；不设文件白名单，不改业务取消代码 |
| 测试与正式资源分开 | 沿用隔离 runner；九转资源敏感文件单独进程，其余全量集独立进程，覆盖集合必须不缺失、不重复 | 不提高 1 GiB 生产门禁，不跳过任何测试冒充全量通过 |
| Definitions 仅加载与清单核对 | 先读本地 help/JSON response schema，再执行已批准 check/list 命令；核资产/检查/任务/传感器身份 | 不启动正式 job/sensor/check，不注册分区，不用正式业务数据验收 |

性能与读写边界：两个测试文件只读本地代码/小型临时 SQL 结果，mock 不访问外部系统；业务日期、
分区、源端请求、正式行/文件写入、event 写入均为 0。全量测试沿用上一轮约 4–5 分钟预算，资源敏感
组串行隔离，不新增并发。Definitions 只枚举静态定义，不扫描 Lake 或 event 历史，不设新的运行配置。

#### M7 续轮收口（2026-09-05，技术验收通过，用户已要求提交）

本轮完成上述已批准修正，保留首次失败记录，不降低正式门禁。改动相对 M6 的总范围为 11 个文件：
首轮六份格式整理及三份专项文档，加本轮两份测试修正。只有测试断言/扫描方式改变，业务实现不变。

| 文件 | 实际修改 | 验证 |
|---|---|---|
| `lake_console/orchestrator/tests/test_duckdb_connection.py` | 原默认资源测试改为 mock 统一连接工厂，验证无参调用、连接原样透传、正常退出；新增消费者错误清理与工厂错误传播，保留三个原默认配置/临时真实连接/错误目录测试 | 6 项通过；不伪造 DuckDB 设置查询结果；`resources.py` 与 `duckdb_connection.py` 对 M6 字节不变 |
| `tests/architecture/test_dataset_maintenance_refactor_guardrails.py` | 抽取纯扫描 helper；23 个原禁止片段保持子串检查，`execution_canceled` 按完整名称边界检查，不禁止合法 helper 后缀；新增 5 个允许样本、12 个拒绝样本、6 个其它门禁保留样本 | 文件 64 项通过；24 个原禁止项集合/顺序完整保留，其余 41 个顶层函数 AST 不变；同一合法 helper 内出现旧字段/事件仍拒绝，没有文件白名单 |
| 三个专项控制文档 | 同步批准状态、首轮历史与续轮结果、11 文件边界及下一步 | 不删除首次失败证据，不新增数据清退授权 |

最终结果：

| 验收 | 数量/结果 | 证据和边界 |
|---|---|---|
| 编排全量主组 | 2,997 passed，1,137 subtests passed；304.71 秒 | `orchestrator-final-main.xml`；只分离九转文件，没有其它排除 |
| 编排九转独立组 | 18 passed；3.83 秒 | `orchestrator-final-nineturn.xml`；原 1 GiB 生产峰值保护代码不变 |
| 全量覆盖核对 | 3,015 个 node ID，遗漏 0、重叠 0、跳过/错误/失败 0 | 两组集合并集严格等于 `final-full-collection.collection.json`；XML 主组另计 1,137 子例，总测试数不能与 pytest 主项混算 |
| 根架构/6 Reader/API/Ops snapshot | 306 passed；27.17 秒 | `root-final.xml`，包括首轮误报门禁及新增 23 个反例/正例；不是只跑新测试 |
| 正式 Definitions | check/list 均退出 0；159 assets、364 checks、75 jobs、88 sensors、8 resources、1 schedule | 本地 help/response schema 与安装的 CLI 代码先核对；正式 `DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`，使用前述批准命令 |
| Definitions 身份对账 | 各类型无重复；159 asset key 与当前 catalog 全等；返回的定义清单无旧 Console/Kopia/old-lake adapter 引用 | `formal-definitions-inventory.json`；Raw/Silver/QFQ/derived/MACD-KDJ、当前 ClickHouse 和 Prod 资源均保留。不启动资产、检查、任务或传感器执行 |
| 静态与边界 | 编排 compileall/致命 Ruff、两份测试完整 Ruff 通过；38 个专项存续 Python 无新增 lint 诊断 | 原 4 文件共 12 条 lint 不扩大；本轮新纳入根测试也有既有格式债务，未整文件重排。总计 20 文件存在历史 formatter 差异，不声称全仓风格全绿 |
| 防误删 | M6 263 删除清单不变；2,140 保护文件中只有首轮两个 CLI 仅格式变化，AST 相同；11,692 ignored 文件元数据不变 | 本轮业务取消函数、DuckDB 设置、九转恢复及 21 命令 fixture 对 M6 字节相同；没有新增/删除 Git 文件或物理数据 |
| 文档 | 165 处置对象 + 3 控制文档、12 HTML、文档完整性与 diff 检查通过 | 首轮发现的三处旧源码链接已改为 Git 历史位置；不复活旧源码或兼容入口 |

前端验证沿用首轮 frontend 149 项、Wealth 60 项及两边 typecheck/build 结果；本续轮未改前端源码，
不重复构建，也不宣称做了线上 UI smoke。CodeGraph 本轮 `explore` 核对统一连接的现行调用面和
TaskRun 取消函数，图中同名 QTF `definitions` 误命中未用作 DG 证据；当前 DG 装配以实际代码及
正式命令结果为准。没有新增资产、字段、resource、分区、配置或跨子系统依赖。

额外证据工具仍仅在首轮临时根中：`verify_final_acceptance.py` 对账 node ID、JUnit、原禁止项、
其它测试函数 AST、受保护运行代码以及 11 文件白名单；`audit_python.py` 补入两份获批测试。
这些不是新的运行依赖。正式命令只完成定义加载/静态清单核验，没有执行 job/sensor、物化、分区
注册、runless event、生产恢复、Lake 写入、服务停启、部署或数据删除。

结论：M7 技术验收已收口，无剩余两处测试/Definitions 授权事项；用户已明确要求提交。本次按
11 文件白名单归档，提交前重新检查 staged diff，提交结果以 Git 记录为准；不推送、不进入 M8。
M8 仍须用户确认具体数据清单。

### M8：精确清退已证实无用的物理数据

1. 复核代码清退实施前已完成的 §16 对象清单；删除在 M0–M7 验收后独立进行，须先取得用户对具体删除清单的确认。§16.9 的单项 backup 是用户明确批准提前删除的唯一例外，不扩展到其余目标。
2. 按 §16.1/16.14 复核代码入口、配置与动态路径；不再核正式替代数据、完整性、日期、全量内容哈希或历史价值。
3. 只删除用户确认的精确数据集目录、恢复 run 目录或单文件；执行前核 realpath、范围、符号链接、跨挂载和占用。不清根、不跟随链接、不混入 ignored 环境。
4. 记录执行结果和能否恢复；历史文档中的物理位置改为当时位置/实际清退状态。核保留路径和代码未被触碰，不对正式数据新增内容扫描。
5. M8 清单与执行结果单独 review，不能用 M7 测试全绿代替数据用途判定。

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
5. M0–M7 的 `lake_console/reports/**`、物理数据和 ignored 环境没有变更；M8 数据差异独立按 §16 白名单对账。

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

代码回退只能回退 Git 变更，不触碰数据。M0–M7 不执行数据或 Dagster 写入；M8 物理删除不能依靠代码回退恢复。

不得以回退为由重新启用 Kopia、old-lake adapter 或兼容 CLI。若新 CLI 有缺陷，应修复新 CLI；只有整个专项提交回退时才由 Git 恢复原状态。

### 13.4 物理环境

M8 删除前必须在清单中明确恢复能力。非 Git 数据没有既有可用副本时，删除不可恢复；hash/manifest
摘要只是证据，不是备份。不得用“Git revert 可回退专项”隐去这种风险，不得新建 Kopia/文件备份补救。
出现未预计的数据差异立即停止剩余删除并保全清单，不能继续扩大清理。ignored 环境/配置仍另轮处理。

---

## 14. 完成验收清单

### 14.1 `stk_mins` 当前能力

- [x] 四个当前 CLI 可以独立 import（M2A；M2B 回归通过）。
- [x] 21 个保留命令全部迁移到正确 CLI（M2A）。
- [x] 21 个命令 old/new 等价对账通过；M2B 仅按 `approved_delta` 收紧四命令，其余冻结 fixture 对账通过。
- [x] 7 个旧 migration 命令在四个当前 CLI 均不存在（M2A）。
- [x] Silver 命令不再接受含糊 `--all`（M2B）。
- [x] Silver register/report 只从 Silver 文件或显式 keys 选择（M2B；显式注册本身不新增文件审计）。
- [x] MACD/KDJ rebuild 仍要求 checkpoint 和 confirm（M2B 回归）。
- [x] MACD/KDJ baseline event 只能选择单日单 partition（M2B）。
- [x] Raw/Silver/QFQ/derived/MACD-KDJ 当前定向 tests 通过（M3 隔离回归；不代表正式部署验收）。
- [x] `stk_mins_migration.py` 和 CLI 已删除，不留 wrapper/alias（M3）。

### 14.2 旧适配器

- [x] generic old-lake spec/executor/specs 全部删除（M4 工作区）。
- [x] `OLD_LAKE_BOOTSTRAP` 和 `old_lake_root` 无运行时正向使用（M4）。
- [x] 旧 DuckDB bootstrap templates 清零（M4）。
- [x] 旧 adj-factor event 补录模块和纯旧测试删除（M4）。
- [x] 历史事件不做存储改写（M4 未访问正式实例）。

### 14.3 Catalog 与 metadata

- [x] 17 个 catalog entry 按第 6.4 节逐个对账（M4）。
- [x] Raw `stk_mins` 五个 entry 固定保留 `PROD_DB_READONLY` 恢复来源（M4 代码与隔离回归）。
- [x] Raw 恢复工具已完成重构：`bootstrap_sources=(PROD_DB_READONLY,)`，candidate/audit/checkpoint 已迁
      正式 staging，逐文件状态可幂等续跑；新流程不再生成正式根 `_staging/_quarantine`，不以清空既有目录作为 M4 验收。
- [x] Silver/Gold/index/adj 的 derived source 与当前依赖一致（M4）。
- [x] 当前 asset metadata 不再宣称 backup clean_next 可用（M4）。
- [x] schema、asset key、partition 和既有正式 path contract 未变化（M4 结构对比与回归）。

### 14.4 旧 Console/Kopia

- [x] 263 个旧产品边界文件同轮删除（M6，精确清单与保护文件对照通过）。
- [x] 旧 backend/frontend 无当前 import、build、start 或 API 入口（M6）。
- [x] Kopia 无可执行代码和生效配置（M6；ignored 旧配置保留、无当前消费者）。
- [x] 正式 orchestrator、reports、ClickHouse bins 和根 frontend 保留（M6 内容对照）。

### 14.5 文档与边界

- [x] 有效模板检查项已先迁入正式模板/性能文档（M5）。
- [x] 三个旧模板删除，当前引用已更新（M5）。
- [x] AGENTS、skills、README 和架构文档与代码事实一致（M6）。
- [x] 第 9.4 节逐文件处理矩阵完成（M7 已复核 165 对象 + 3 控制文档）；current/mixed 文档未被误删，86 份 `DELETE_LEGACY_DOC` 文件在
      当前工作树清零，现行引用为 0，必要结果摘要已迁入现行总账/设计。
- [x] Wealth `local_lake` 全部当前 Reader、分钟/turnover insight/trend 等 API、页面调用和 optional dependency 未被误删（M6 内容与定向回归）。
- [x] 本次 M7 未改物理数据/reports，Ops Snapshot 与 ignored 依赖环境/配置保留；历史单项 backup 提前删除仅按 §16.9 的独立批准，不扩展到其它物理对象。
- [x] M7 全量回归与正式 Definitions 技术验收通过，工作区 diff 仅 11 个专项文件，无新增/删除文件；两处测试问题已按批准口径修正。
- [x] 用户已要求提交 M7；本次按 11 文件白名单归档，提交前重新核验 staged diff，提交结果以 Git 记录为准；不推送、不进入 M8。

### 14.6 M8 物理数据

- [ ] §16.14 按代码引用归类，有消费者证据、精确目录/文件、依赖前置项和恢复能力说明；不要求内容替代证明。
- [ ] 旧代码依赖先退出，用户确认具体清单，删除前机械安全检查通过；当前使用及引用范围未核清的对象未删。
- [ ] 实际删除与白名单一致，正式数据和共享目录未被误删；历史证据位置已更新。
- [ ] 未删除对象保留原因显式列出；不能把“未核清”当清退完成，也不为结案强制清空目录。

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
拍板，但仍需要用户单独授权进入 M0–M7 代码和文档删除执行。按 2026-09-05 更新，已证实无用的数据
纳入 M8；用途未知不删，实际删除独立清单验收。ignored 依赖环境和配置仍另轮处理。

---

## 16. 物理数据代码用途审计与清退清单（2026-09-05 更新）

### 16.1 判定规则与执行边界

本节替代旧版 §1.3/1.4、§13.4/14.5 的“物理数据本专项一律不处理”。范围限本专项涉及的旧 Console
数据、旧迁移输入、旧恢复遗留文件和报告，不扩成全盘数据治理，也不包含删除业务数据库/Dagster 历史。
用户已明确：代码没有直接使用的数据不再需要。直接使用包括真实读写、配置指定、路径拼接、glob，
以及代码读取 manifest/checkpoint 后继续读写的具体文件；不等于完整路径字符串命中。仅在禁止规则、
历史文字中提及不算使用。当前工具能接受任意文件参数，也不能据此把所有未指定文件永久判为在用。
取消日期/行数/schema/完整性、旧新内容差异、历史价值、副本承接及假设的人工用途审计；不恢复旧湖迁移。

| 处理状态 | 判断与动作 |
|---|---|
| `KEEP_IN_USE` | 有当前生产/查询/恢复/审计用途，保留；若未来解除依赖，重新审计 |
| `PENDING_AUDIT` | 仅用于代码/配置实际读写范围还没核清；不是因数据独有、年代早或副本未知而延长审计 |
| `DELETE_AFTER_DEPENDENCY` | 只有本专项待清退旧代码读写；先退出对应旧入口，再列入可删清单，不要求数据内容承接 |
| `DELETE_READY` | 已核无当前代码数据读写/续跑用途，可提请删除；不是已授权删除，仍须具体清单确认及原 M8 阶段/机械安全验收 |
| `DELETED` | 精确对象经用户确认并执行删除、完成删除后核验；不等于同目录其他对象或整个 M8 完成 |

每份实际执行清单只需记录：审计时间/HEAD、精确绝对路径及类型、代码引用与分类、待退出依赖、用户确认
范围、机械安全检查、执行结果和能否恢复。已有文件数/字节数可作范围参考，不额外读内容或遍历行数据。
执行前核 realpath、目录边界、符号链接、跨挂载、占用及新增消费者；异常则停该项。不允许
`/Volumes/datasource`、正式/旧 Lake 根、`_quarantine`、`reports` 等共享上层目录成为递归删除目标。

§16.2、16.4–16.7、16.9–16.10、16.12–16.13 是已发生的历史审计记录；其中基于内容差异、唯一历史、人工恢复
价值或证据迁移的保留结论与待办已被本节替代，不再执行。当前分类只看 §16.14；§16.9 已批准删除的事实
不变，§16.11 停牌规则 TODO 继续有效。此简化不降低 §6.4 新恢复工具的候选校验、fingerprint/checkpoint
和写入安全要求——清退无用旧数据与生成/替换正式数据是两件事。

**单对象明确批准例外（2026-09-05）**：用户确认
`/Volumes/datasource/backup/research/stk_mins_by_date_clean_next` 只是基础版本备份，无需再审内容，
并在确认精确路径后要求删除、继续推进。此对象不再要求内容替代证明或逐 Parquet 内容 SHA-256，
也不等待 M0–M7；仅做路径、无符号链接/跨挂载、范围元数据和占用检查后精确删除。记录执行前逐文件
路径/类型/大小/mtime/device/inode 清单及其摘要指纹，删除后确认目标消失、排除对象仍在。
旧湖内 `research/stk_mins_by_date_clean_next` 与正式 Raw 完全排除。旧迁移默认源将不可用，
旧 migration 主体按 M3 清退，`specs/stk_mins.py` 等适配器按 M4 清退，不重建源、不重启迁移。此批准不是其他数据、代码或文档的
删除授权；非 Git 备份直接删除不承诺可恢复。执行结果见 §16.9，其他对象仍遵守上文通用门禁。

### 16.2 首轮定点核验记录（历史取样，后续进展见 §16.4–16.10）

本轮使用 CodeGraph explore 核对 Raw recovery/CLI/rollback 和其他 quarantine 使用方，再核对实际代码、
tracked 文本引用、定点目录与 SHA-256。没有运行 Kopia、Dagster 或生产查询，没有启动恢复、改数据或删除文件。
没有完成整湖逐数据集对账，也没有实时排查所有在途任务，以下不能冒充 M8 最终执行白名单。

| 对象 | 当前证据 | 本次判断与后续动作 |
|---|---|---|
| 正式 Raw `raw/tushare/stk_mins/freq={1,5,15,30,60}/trade_date=2026-07-27/part-000.parquet` | 五份物理文件均存在，SHA-256 全等于成功 manifest 的 staged 指纹；`stk_mins_silver_replace_from_raw.py` 通过 `raw_stk_mins_path` 读这些正式输入，当前 Raw/Silver 链继续使用 | `KEEP_IN_USE`，不删，不因来源曾是恢复而当作废弃数据 |
| 下述 Raw recovery run 的五份 backup | 合计 31,282,051 字节（约 29.8 MiB）；SHA-256 全等于 `target_files_before`；manifest 为 `promoted`、五频全部已提升。代码 `_restore_backups` 只在该次 apply 异常内使用这些备份，没有历史 manifest 续跑入口 | `DELETE_AFTER_DEPENDENCY`，是已被正式文件替代的旧版本候选，不是当前输入；M4/M7 后核实无在途/人工恢复用途、同步历史证据后精确删除，不扩到其他 recovery run |
| 同 run 的 `manifest.json` | 4,572 字节，mtime 为 2026-07-28 01:17:00 +08:00；现行 `dagster-stk-mins-prod-task-run-readiness-low-level-design.md` 的执行记录仍引用它 | `DELETE_AFTER_DEPENDENCY`，先把 run/date/status/五频 old/new 指纹等必要摘要保留在该现行文档；标清原物理路径已清退后可删除，不留失效的当前证据入口 |
| `/Volumes/datasource/data_lake/raw/tushare/stk_mins/_staging` | 本轮直接子项为 0；当前旧 Raw 恢复实现仍会在此创建 run 目录 | `DELETE_AFTER_DEPENDENCY`，M4 解除生成依赖后，执行前再次核为空且无运行占用，才可删除这个空目录本身；不是清理父 Raw 树 |
| `/Volumes/datasource/data_lake/_quarantine` 其他子项 | 当前 `stk_mins_silver_replace_from_raw.py` 也生成/使用自身 quarantine；还有其他正式历史执行证据，不能套用 Raw run 的成功结论 | `PENDING_AUDIT`，共享根不能删；每个子 run 独立核验，仍需当前恢复使用的保留。Silver 工具不因本次 Raw 重构被顺手删改 |
| `/Volumes/datasource/goldenshare-tushare-lake` | 本轮只看顶层：`_recovery`、`_tmp`、`derived`、`manifest`、`raw_tushare`、`research` 及 `.DS_Store`；旧 Console/old-lake adapter 尚未删除，未做逐数据集内容/替代关系审计 | `PENDING_AUDIT`，纳入专项继续逐项核查，不是本次已有证据可整删；先解除退出代码依赖，独有且仍有用途的数据保留 |
| `/Volumes/datasource/backup/research/stk_mins_by_date_clean_next` | 仍是待删迁移器的历史输入；本轮未访问、未做物理内容与正式湖差异审计 | `PENDING_AUDIT`，先清迁移依赖，再核数据用途；不扩展到整个 backup 盘 |
| `/Volumes/datasource/data_lake_staging` | 正式当前 candidate/checkpoint 根；未逐 run 审计 | 根及有效运行数据保留；只可把逐 run 证明废弃的具体对象加入清单，不按文件年龄统一清理 |
| `lake_console/reports/**` | `orchestrator/audits/stk_mins_silver_strict_audit.py` 当前 CLI 默认输出到其中 `stk_mins_silver_audit_20260530`；本轮未逐报告审计 | 目录用途为当前审计输出，保留；单份历史报告 `PENDING_AUDIT`，不推断“当前输出目录=每份报告永久有用”或“旧日期=无用” |
| `lake_console/.venv`、frontend 的 `node_modules`、`dist`、`*.tsbuildinfo` 及 `lake_console/config.local.toml` | 依赖环境、构建输出或本机配置，不是本次更新中的业务数据清单 | 不纳入 M8，继续按原决定另轮精确处理；Git 产品删除不能递归带走它们 |

本次 Raw 遗留 run 的唯一根为：

```text
/Volumes/datasource/data_lake/_quarantine/stk_mins_raw_replace_from_prod/trade_date=2026-07-27/recovery_run_id=f573265f-1162-4535-9089-c486f7b7dac1
```

该根下本轮只发现 `manifest.json` 和以下五个相对文件，不能把更上层目录当目标；正式文件位于上表 Raw
路径，不在删除清单。M8 前还必须复核内容用途/无在途依赖和路径指纹，下面是定点审计证据，不是立即删除指令。

| 备份相对路径 | 字节数 | 备份 SHA-256 | 当前正式文件 SHA-256（与原 promoted 一致） |
|---|---:|---|---|
| `freq=1/trade_date=2026-07-27/part-000.parquet` | 21971002 | `bc04b0b8406b0509a1fb99edbef6d030018b20a6a01c6a1d5d56edff858e749f` | `777206dfa9b50d6834462c03df25da19059b30e2fd6a0641cb1b68286cccd20d` |
| `freq=5/trade_date=2026-07-27/part-000.parquet` | 5424024 | `8c7bf7920a74816c845bae4934cfc38526854a83b14788c0d6699f256bf07b4b` | `147b325eb208881250353b59b4983e924a3717da1a9032e761f25602ed2550f0` |
| `freq=15/trade_date=2026-07-27/part-000.parquet` | 1995793 | `14bb6947de0550d75c40ac412e8b75d5b58f4ded4ebb42e831550ba6c9fbaff6` | `106ac7a7537475bfa8d2d8162458ada88831588b2a0a62ef58c3774c7f51b414` |
| `freq=30/trade_date=2026-07-27/part-000.parquet` | 1138570 | `530fca944342e776181f897b6839c7e2fd5f72cfd44aaf9057f7dd76e175aae5` | `83372f10fc1d0a56bc03f45e2985bbc41c2660d33bcb89011a38db5366008b68` |
| `freq=60/trade_date=2026-07-27/part-000.parquet` | 752662 | `dfb10dff88822f8fa366da35151af4b5dcbede460b25d21e581353bf068fa445` | `deac6bb536d56bcb917d6c2c5ee56e947c8140d7605612e77365aa87b333f584` |

### 16.3 M8 完成条件

每个已纳入范围的对象都必须按当前代码读写用途形成结论；保留代码使用的保留，无代码用途的不再追加历史
价值或内容承接证明。删除只针对经用户确认的 `DELETE_READY` 清单，不能跳过 `DELETE_AFTER_DEPENDENCY`
的旧代码退出前置条件。清理不保证所有旧目录消失，也不建立周期性自动清理任务；不擅自修改保留消费者
来达到删除目的。完成记录须包含精确范围、确认依据、机械安全检查及执行结果，文档分类不能代替实际清退。

### 16.4 2026-09-05 首批物理用途审计：做到了哪一步

本批基线 `dev-interface@75af8445`，运行态取样时间为 07:55–07:58 +08:00。只读取代码、文件、
本机进程、Dagster GraphQL 查询及正式本机 `goldenshare_dagster` 的指数动态分区表；未执行 Kopia、
恢复 CLI、job、sensor evaluation、materialization、生产 DB 查询或任何数据删除。
Dagster 表查询先设置只读事务，查询后 rollback；没有改运行状态或分区集合。

方法与局限：

1. CodeGraph `status/explore/callers` 覆盖旧 bootstrap spec/executor、分钟恢复、当前 WMT 恢复输入；
   对图索引没有覆盖的动态路径、配置、CSV 文件名和历史引用，直接核对当前文件。
2. 逐目录枚举文件元数据，不跟随符号链接；每根预算为 45 秒或约 60 万目录项，在完成当前目录后检查预算。
   不扫描全湖 Parquet 行、不执行旧湖 bootstrap。大文件不因同名、同日期或目标存在就判为已完整替代。
3. 表中为普通文件数和逻辑字节数，含隐藏元数据；不是 Parquet 行数，也不等于可释放磁盘空间。
   五个根的 realpath 都等于记录的绝对路径；已访问范围没有符号链接或读取错误。
4. 原始逐文件路径/大小/mtime/device/inode 清单和查询结果在
   `/private/tmp/lake-retirement-audit-20260905.F0fmIk/`，属于可失效的临时审计产物；稳定结论保存在本节。
   `old_lake.csv/clean_next.csv/quarantine.csv/reports.csv` 为完整枚举，`staging.csv` 是部分枚举。
   它们没有全量内容 SHA-256，不能直接当删除执行清单。删除前必须重新生成并冻结精确白名单。

| 根/对象 | 普通文件数 | 逻辑字节数 | 本批完成程度 |
|---|---:|---:|---|
| `/Volumes/datasource/goldenshare-tushare-lake` | 297730 | 509788479887 | 元数据枚举完整，17.42 秒；逐数据集内容替代关系尚未完成 |
| `/Volumes/datasource/backup/research/stk_mins_by_date_clean_next` | 21047 | 67676449533 | 元数据完整，1.14 秒；21045 个 Parquet 的对应正式路径全部存在，但尚未做全量内容对账 |
| `/Volumes/datasource/data_lake/_quarantine` | 75265 | 14845426378 | 元数据完整，5.87 秒；只对两个五频恢复 run 完成 old/new SHA 核验 |
| `/Volumes/datasource/data_lake_staging` | 至少 40787 | 至少 4925835331 | 25.03 秒触达目录项预算，已访问 600436 项，尚有 4287 个待遍历目录；不声称全量统计 |
| `/Users/congming/github/goldenshare/lake_console/reports` | 4 | 200145 | 三个 tracked CSV 及 `.DS_Store`；三个 CSV 均完整解析并计算 SHA-256 |

运行态点时证据：

- `127.0.0.1:3000` 返回 Dagster 1.13.18；查询 `QUEUED/NOT_STARTED/MANAGED/STARTING/STARTED/CANCELING`
  的 run 总数为 0。这只证明取样时无这些在途 run，不证明之后没有新任务，也没有审完所有历史 backfill 意图。
- 进程参数扫描未命中旧 Console backend、两个分钟恢复 CLI、旧分钟迁移 CLI；不能替代对未命名脚本、
  未来人工恢复用途或其他机器的确认。
- 打开文件快照没有命中旧湖、clean_next、quarantine 或 staging；三个报告由 CodeGraph 索引进程
  PID 7942 打开，不是业务消费者。单次无占用不能证明永久无用。
- `.env.web.local` 的本地分钟能力已开启、Lake root 为 `/Volumes/datasource/data_lake`；旧
  `config.local.toml` 的 root 则为旧湖。二者是不同配置入口，不得删除前者的 Foundation Reader/API。

本批首轮取样时没有产生 `DELETE_READY` 执行白名单，也没有取得删除批准；这不是之后执行状态。
用户随后批准并删除的唯一 backup 见 §16.9；其他对象继续补齐内容/用途证据，不进入整湖删除。

### 16.5 旧湖与旧迁移输入分类清单

| 对象（旧湖内路径相对于 `/Volumes/datasource/goldenshare-tushare-lake`） | 文件数 / 字节数 | 状态、消费者和剩余证据 |
|---|---|---|
| `raw_tushare` 全部 54 个数据集及其隐藏元数据 | 80929 / 81763838602 | `PENDING_AUDIT`。旧 backend 动态目录消费者仍在；其中 daily、adj_factor、suspend_d、stock_basic、trade_cal 还有待删的旧 bootstrap spec。须逐数据集核正式源/范围/内容及唯一数据价值，不得把所有 54 个都写成“已迁完” |
| `manifest` | 149 / 558251170 | `PENDING_AUDIT`。含身份映射、日历、参考数据、gate、checkpoint 和运行账本；`specs/stock_identity_map.py` 仍指向旧身份映射文件。先解除旧迁移依赖，再核正式 seed/资产承接与历史证据摘要 |
| `research/stk_mins_by_date_clean_next` | 21077 / 95539889959 | `PENDING_AUDIT`。这不是下面 backup 目录的同一份输入；字节数明显不同，旧 compute 发布记录也存在。须按字段、复权语义、业务键和范围核对，不得当目录副本删 |
| `research/stk_mins_by_symbol_month` | 46817 / 89771554123 | `PENDING_AUDIT`。旧重排/指标链输出；尚未证明可从保留的正式数据完整重建 |
| `research/stk_mins_indicators_by_symbol_month` | 32 / 29402350 | `PENDING_AUDIT`。旧指标样本输出；需核算法、参数及历史证据引用，不按样本少就直接删 |
| `derived/stk_mins_by_date` | 8431 / 1771375884 | `PENDING_AUDIT`。旧 90/120 分钟派生数据；当前 canonical bars 不是凭路径就能证明与之等价 |
| `derived/stk_mins_indicators_by_date` | 102580 / 80148850273 | `PENDING_AUDIT`。旧指标分桶结果；先核其参数/用途和当前 Gold 承接关系 |
| `_recovery` 的 20 个旧修复目录 | 7470 / 88777972 | `PENDING_AUDIT`。存在 patch_rows 与 raw_partition_backup；尚未证明每份 patch 已进入被保留的最终事实，不能只按 2026-05 日期删除 |
| `_tmp` 全部 | 30242 / 160116510870 | `PENDING_AUDIT`。含未发布候选、旧备份、分块文件；年龄清理工具不是本专项的安全判据，不调用它 |
| `/Volumes/datasource/backup/research/stk_mins_by_date_clean_next` | 删除前 21047 / 67676449533；删除后目录不存在 | `DELETED`。用户确认基础版本备份无需再审，批准提前精确删除，见 §16.9；取消内容替代证明前置项。旧 migration 主体已在 M3 删除，`specs/stk_mins.py` 等适配器仍待 M4，默认源已不可用，不得重建 |

根级及各层 `.DS_Store` 只是元数据，不是业务数据；未据此新建删除任务，仍须纳入用户确认的精确清单。

54 个旧 Raw 数据集的首批盘点账如下。路径相对于旧湖根，数量为历史元数据盘点。
**按最新代码引用审计，以下 54 个目录统一为 `DELETE_AFTER_DEPENDENCY`（§16.14），不再逐个对账内容。**
旧 Console/适配器退出后，按这些精确目录提请删除；不能把本表当作已获删除批准。
目录内隐藏元数据计入文件数，`raw_tushare` 根自身的 `.DS_Store` 不在下面 54 行内。

| 相对路径 | 文件数 | 字节数 |
|---|---:|---:|
| `raw_tushare/adj_factor` | 4215 | 125267552 |
| `raw_tushare/bse_mapping` | 1 | 7325 |
| `raw_tushare/cyq_perf` | 2027 | 206000983 |
| `raw_tushare/daily` | 8641 | 772709905 |
| `raw_tushare/daily_basic` | 3971 | 1479472036 |
| `raw_tushare/dc_daily` | 570 | 30455001 |
| `raw_tushare/dc_hot` | 516 | 13778958 |
| `raw_tushare/dc_index` | 336 | 10087580 |
| `raw_tushare/dc_member` | 336 | 91984315 |
| `raw_tushare/etf_basic` | 1 | 119594 |
| `raw_tushare/etf_index` | 1 | 42505 |
| `raw_tushare/fund_adj` | 2515 | 19232158 |
| `raw_tushare/fund_daily` | 2515 | 119254586 |
| `raw_tushare/hk_basic` | 1 | 160874 |
| `raw_tushare/index_basic` | 1 | 516088 |
| `raw_tushare/index_daily` | 1540 | 118000496 |
| `raw_tushare/index_daily_basic` | 1540 | 11718095 |
| `raw_tushare/index_mins_by_date` | 1615 | 3093448632 |
| `raw_tushare/index_monthly` | 76 | 5729662 |
| `raw_tushare/index_weekly` | 326 | 24153717 |
| `raw_tushare/kpl_concept_cons` | 384 | 137188656 |
| `raw_tushare/kpl_list` | 328 | 11289540 |
| `raw_tushare/limit_cpt_list` | 605 | 3816846 |
| `raw_tushare/limit_list_d` | 1540 | 27510115 |
| `raw_tushare/limit_list_ths` | 613 | 15300798 |
| `raw_tushare/limit_step` | 605 | 1880783 |
| `raw_tushare/margin` | 327 | 1887568 |
| `raw_tushare/moneyflow` | 3971 | 1198170527 |
| `raw_tushare/moneyflow_cnt_ths` | 400 | 9317152 |
| `raw_tushare/moneyflow_dc` | 643 | 209456719 |
| `raw_tushare/moneyflow_ind_dc` | 643 | 26310824 |
| `raw_tushare/moneyflow_ind_ths` | 400 | 5095430 |
| `raw_tushare/moneyflow_mkt_dc` | 744 | 7421400 |
| `raw_tushare/moneyflow_ths` | 337 | 93217892 |
| `raw_tushare/namechange` | 1 | 230045 |
| `raw_tushare/st` | 1 | 374951 |
| `raw_tushare/stk_factor_pro` | 328 | 3221219515 |
| `raw_tushare/stk_limit` | 570 | 54734377 |
| `raw_tushare/stk_mins_by_date` | 21725 | 69744658004 |
| `raw_tushare/stk_nineturn` | 812 | 143651444 |
| `raw_tushare/stk_period_bar_adj_month` | 196 | 49701934 |
| `raw_tushare/stk_period_bar_adj_week` | 838 | 202200036 |
| `raw_tushare/stk_period_bar_month` | 196 | 29467981 |
| `raw_tushare/stk_period_bar_week` | 838 | 117834444 |
| `raw_tushare/stock_basic` | 2 | 363940 |
| `raw_tushare/stock_company` | 1 | 5721427 |
| `raw_tushare/stock_st` | 2368 | 11183497 |
| `raw_tushare/suspend_d` | 6381 | 20281446 |
| `raw_tushare/ths_daily` | 1540 | 235582642 |
| `raw_tushare/ths_hot` | 328 | 15122189 |
| `raw_tushare/ths_index` | 1 | 28737 |
| `raw_tushare/ths_member` | 1 | 1229598 |
| `raw_tushare/top_list` | 2515 | 40165407 |
| `raw_tushare/trade_cal` | 2 | 74480 |

旧迁移输入的路径覆盖已逐分区检查：

| 频率 | 源 Parquet / 日期数 | 日期范围 | 对应正式 Raw 存在 | 尚未证明 |
|---|---:|---|---:|---|
| 1 | 4209 | 2009-01-05 至 2026-05-07 | 4209 | 行/键/字段内容替代关系 |
| 5 | 4209 | 同上 | 4209 | 同上 |
| 15 | 4209 | 同上 | 4209 | 同上 |
| 30 | 4209 | 同上 | 4209 | 同上 |
| 60 | 4209 | 同上 | 4209 | 同上 |

对应路径通过已读的 `stk_mins_bootstrap_spec` 确定为
`/Volumes/datasource/data_lake/raw/tushare/stk_mins/freq={freq}/trade_date={date}/part-000.parquet`。
这项结果只排除了“根本没有对应正式分区”的情况，不是删除批准，也不允许再用旧迁移器读旧湖写正式湖。

旧 compute 六份 `run.json` 已逐份读取。以下只是磁盘记录状态，不冒充当时执行的内容验收：

| run_id | manifest 状态 | `_tmp/duckdb_compute/<run_id>` 文件数 / 字节数 | 本次处置 |
|---|---|---|---|
| `20260516T142430Z-stk-mins-qfq-4945b7` | abandoned | 32 / 1324953 | 暂保留，先核候选内容与旧发布/gate 依赖 |
| `20260517T024717Z-stk-mins-qfq-554d6c` | abandoned | 66 / 11827693 | 同上 |
| `20260517T035958Z-stk-mins-qfq-f659f3` | abandoned | 本次无普通文件命中 | manifest 仍有证据用途待核，不因为无候选就整目录删除 |
| `20260517T040204Z-stk-mins-qfq-ef77de` | abandoned | 1 / 1155359 | 暂保留，先核内容和引用 |
| `20260517T040338Z-stk-mins-qfq-f3a1a9` | abandoned | 4151 / 61181524575 | 暂保留；约 57 GiB 未发布候选不能只依据 abandoned 判断可删 |
| `20260517T044621Z-stk-mins-qfq-c906ef` | published | 21035 / 95298928595 | 暂保留；有正式发布/gate/downstream 阶段记录，需核替代内容与证据承接 |

代码证据为旧 `DuckDbComputeRunLifecycleService`：`abandoned` 表示退出旧 readiness 的 active 集合，
其设计明确保留 candidate/tmp/backup 追溯；它不证明候选和当前数据相同，也不代表本专项已确认可删。

### 16.6 reports 逐文件用途及指纹

以下路径统一位于 `/Users/congming/github/goldenshare/lake_console/reports`。目录继续服务当前
`orchestrator/audits/stk_mins_silver_strict_audit.py` 的 CLI 输出；此次三个既有 CSV 不是该工具的输出文件。
当前代码/脚本文件名反查未发现读取这三个 CSV 的运行入口；指数文件另有两份历史设计引用，已加入 §9.4。

| 文件 | 内容事实 | 处置与前置条件 |
|---|---|---|
| `index_daily_continuous_since_list_date_after_20000101.csv` | 188989 字节、948 行，as-of 为 2026-05-22，缺日计数均为 0。两份 Phase 3 HTML 的 CSV 初始化段属于已被替代的历史设计 | `DELETE_AFTER_DEPENDENCY`。当前 `assets/index_daily.py::_registered_index_ts_codes`、sensor/check 读的是正式 instance 的集合而不是 CSV。必要历史摘要已记在本节；M8 前复核没有新的文件消费者并确保历史引用不被当成可执行初始化入口，用户确认后才可删 CSV。两份历史设计本身不在新增删除范围 |
| `namechange_unresolved_candidates_active_only_v2_rules_20260530.csv` | 989 字节，14 行全是 SUMMARY；blocking/unresolved conflict 和 unresolved_candidate_rows 均为 0，人工已解决事件 3 条；不是待选事件明细或当前映射 seed | `DELETE_AFTER_DEPENDENCY`。保留本节零未决摘要；代码清退后再次核无读者并提交用户确认。不能根据它删除当前 namechange overrides/身份映射数据 |
| `stock_daily_missing_ranges.csv` | 1971 字节、35 行；后续 §16.10 核实：31 项与现行停牌修正规则相同、3 项未标停牌缺口已有正式数据、1 项 920188.BJ 的 S 标注与当前事实不符 | `DELETE_AFTER_DEPENDENCY`。报告不再作为未决修复输入；摘要与实际消费者已明确，M8 前复核无新引用、用户确认后再删。31 项现行 seed/修正规则和正式数据全部保留，不将报告退出当作全历史数据质量验收 |

正式本机 `goldenshare_dagster.public.dynamic_partitions` 只读结果：`cn_a_index_ts_codes` 当前 820 个，
全部包含在历史 CSV 的 948 个内；CSV 多 128 个，当前集合没有 CSV 外新增项。本轮没有审计这 128 个
目前不在集合的逐项原因，不能擅自添加或删除分区。当前排序代码加末尾换行的 SHA-256 为
`c93cc203a552f96d9087fbcab0cfa9edb254d819cf964be941c455b5ae526184`。
**禁止用旧 CSV 的 948 个代码重新初始化当前集合。** 数据集合保存在 Dagster，并不会因删 CSV 自动消失。

| CSV | 本次 SHA-256 |
|---|---|
| index_daily 连续性报告 | `be57b3cec0a41d2ddf060a774451317a79b357ec09dfddfc47886b555125010b` |
| namechange 零未决摘要 | `8eef7b295a93a4e8ba8366a9a5d3be18784b8a46ceb39c31ee957f61b236a4e3` |
| stock_daily 缺口报告 | `671b4266509bb25d3a9c369e1c7eecdde7ba63c84ffa15522378c91317fa045a` |

三个 CSV 均为 Git tracked，可从审计基线版本取回。Git 可恢复报告不等于可恢复未跟踪的湖数据，
更不构成未经确认直接删报告的理由。

### 16.7 正式湖恢复遗留与当前 staging 防误删清单

Raw run 仍为 §16.2 的六个文件，旧五频 SHA 分别匹配 manifest 的 before，正式五频分别匹配 staged，
不是旧文件与正式文件互相相同；保持
`DELETE_AFTER_DEPENDENCY`。本次增加同日 Silver run 的独立核验，不改变 Silver 工具保留决定：

```text
/Volumes/datasource/data_lake/_quarantine/stk_mins_silver_replace_from_raw/trade_date=2026-07-27/recovery_run_id=70c5f3d5-3857-4fa9-b840-3d632fba9e3f
```

该 run 是 `promoted`，频率 1/5/15/30/60 全完成。五份旧文件合计 21811817 字节，均匹配
`target_files_before`；当前五份正式 Silver 均匹配 staged SHA，不是待删文件。
manifest 为 16990 字节，仍被 readiness LLD §9.4 的执行记录引用，SHA-256 为
`28f1931c0219593c62d377e08d3a6e72a1a8967ec93a4b042decc8413c36917c`。
Raw manifest 为 4572 字节，本次 SHA-256 为 `8e892a12c252ab90bb34f7d50da8683e26e80c80d6d8602c1a8f3ecd6e0a7676`。
`stk_mins_silver_replace_from_raw.py` 的备份只用于同次异常回滚，没有读取历史 manifest 续跑入口。
因此该 run 的六个文件列 `DELETE_AFTER_DEPENDENCY`：先把必要摘要补回事故记录、确认无人工恢复用途，
M8 再独立提交精确清单；**不以清遗留文件为由删除或顺手重构 Silver 恢复工具**。

| Silver backup 相对路径 | 字节数 | backup SHA-256 | 当前正式 Silver SHA-256 |
|---|---:|---|---|
| `freq=1/trade_date=2026-07-27/part-000.parquet` | 14997533 | `18ee627219248ecb3914599d2de51e7a8ddc09cb89b20e3242a411250d547bca` | `ce2b1d9cb6afb754be85d81cc26d0586c985526a55708464dc2320a55de91bcb` |
| `freq=5/trade_date=2026-07-27/part-000.parquet` | 3892777 | `09d8eee34a92724b80d63e515539696cad18ee6db1b2491dd81442120beab171` | `3f5ab7f7ad9fccb035682a3109f22a11894d9e5f12ab1d519df7427197387026` |
| `freq=15/trade_date=2026-07-27/part-000.parquet` | 1464056 | `ba3686444b8241a326a3b034d2d044ad165dc3ad9cf184929ae72b73e00e7cc7` | `fe1e13697e38d885148cb17361931af845e05335809cd7843ef38b400b1f1fd9` |
| `freq=30/trade_date=2026-07-27/part-000.parquet` | 858723 | `5687c725ccafbc18ab70176136d201d5c09a176298f8a1ba86ba2f883ef3db32` | `18206ed63eb3e032af515025df960485338babc48ec25121237cf45892e5a7e9` |
| `freq=60/trade_date=2026-07-27/part-000.parquet` | 598728 | `ebe5c34313b3f8098d9a1ad0a52379038eb5fc2b8614c29607668e7e10904574` | `217d9c6c64cb632a9eb715606ffa12cda80427ec5c02084b99ebc012062e6e30` |

其他 quarantine 全部只是相邻目录，不因此变成 Kopia/旧 Console 数据；尚未证明内容替代，不扩成独立
指数/九转治理任务，以下统一暂保留。目录名中的 failed/remove 不是删除依据。

| `_quarantine` 下直接子项 | 普通文件数 / 字节数 | 已核事实与状态 |
|---|---|---|
| `index_daily_p8` | 0 / 0 | 只有目录层级或空项，没有普通文件；不递归清理共享父目录 |
| `index_daily_remove_58_codes_20260710T044737Z` | 6606 / 181948582 | staging/normalized 文件，无本次完整成功/替代核验；`PENDING_AUDIT` |
| `index_daily_remove_58_codes_20260710T050156Z` | 6606 / 181948582 | 同上；两个目录相同大小不能代替内容判重 |
| `index_daily_remove_58_codes_20260710T052642Z` | 13088 / 477021392 | backup manifest 有 13057 entries，不等于整目录文件数；剩余文件未按用途闭环；`PENDING_AUDIT` |
| `index_daily_remove_68_codes_20260723T201420+0800` | 6580 / 278515993 | backup manifest 有 6578 entries，另有 registry CSV；需核移除/保留证据，`PENDING_AUDIT` |
| `qfq_nineturn_p6b_failed_20260808_130229` | 3553 / 185941102 | manifest 记录 3552 个隔离输出；当前九转方案/LLD 仍引用本次事故，`PENDING_AUDIT`；不因失败文件就丢唯一事故证据 |
| `stk_mins_qfq_macd_kdj_r5_multi_20260714T130322Z` | 38820 / 13486935297 | manifest 与现行 R5 LLD 引用仍在；未重验 38819 个数据文件与当前目标，`PENDING_AUDIT` |

当前 staging 核查发现真实的后续使用关系，须保护：

1. `wealth_market_turnover_history.py::_load_recovery_inputs` 读取 BSE source bundle 与 actual changed
   Silver manifest；`_assert_recovery_inputs_unchanged` 在构建、提升、审计、prod publish 等步骤复核。
   `publish_wealth_market_turnover_history_to_prod` 还消费 actual changed WMT manifest。
   **链路是 BSE 恢复证据 → WMT 修复/审计 → Prod 发布，不是旧 Console 备份。**
2. `/Volumes/datasource/data_lake_staging/prod-republish-changed-wmt-manifest.json` 是 652228 字节，
   `stage=r5_actual_changed_wmt_manifest`、`complete=true`、1157 个 changed partitions。
   complete 只证明该 manifest 声明完整，不能独自证明所有后续发布/人工重试结束；保留其运行契约/证据用途。
3. `wealth_market_turnover_history` 下五份 actual-changed manifest 中，计划哈希前缀 `14557f0f`、
   `46f397e0`、`5f55277c` 仍为 `complete=false`，分别记录 80/738、340/658、420/1158 个
   已处理分区（最后一份为 60 changed + 360 no-op）；`8ca42653` 为 317 changed + 1 no-op，
   `84452203` 为 1 changed，均 complete=true。必须先核前后计划是否已合并接替，不能删 checkpoint。
4. `stk_mins_bse_recovery`、上述 WMT 文件及各自 checkpoint 先保护其恢复/审计用途；单个候选文件是否
   废弃仍逐 run `PENDING_AUDIT`。其他 ETF、趋势通道、九转、正式 raw/silver/gold staging 家族不因
   本次发现目录而加入旧产品删除目标；本次也未对未遍历部分声称“没有用途”。

### 16.8 剩余任务、验收与停止点

| 顺序 | 下一项工作 | 完成证据 | 不做什么 |
|---|---|---|---|
| 已完成 | 旧湖六个目录家族、54 个 Raw 和两个正式分钟恢复 run 按代码引用批量分类 | §16.14；旧湖同名 clean_next 属于旧 Console 依赖组，已删除 backup 的事实仍见 §16.9 | 不再核数据完整性、早期历史、旧证券差异或人工价值 |
| 2 | 用户 review 分类与具体候选；按批准阶段实施 M1–M7，解除旧适配器/Console 依赖 | 旧代码实际退出、现行 CLI/主链回归；M4 安全验收不变 | 审计同意不代替代码/数据删除批准 |
| 3 | M8 对获批目录/文件复核代码引用和机械安全，执行并记录结果 | 具体清单确认、精确路径、无越界/占用，保留范围未触碰 | 不重做 Parquet 对账或全量内容 SHA，不清共享根，不改业务库/DG |

原“剩余 49 个数据集内容核验、早期日线/停牌价值、两条身份映射、20 个旧恢复 run 内容承接、完整 staging
盘点、事故证据/人工恢复价值逐项确认”等任务取消。仍被当前恢复代码读取的 BSE/WMT 输入按代码依据保留，
不要求为了清退再证明这些文件是否成功发布。未纳入专项的其他正式治理隔离项不扩成新审计任务。
非 Git 数据删除不承诺可恢复；这是一项交付风险说明，不再启动副本搜寻或要求内容备份。

### 16.9 已执行：仅删除用户确认的基础版本备份

用户先说明“这个你不需要审计了，可以删了。它之前是一个基础的版本备份”，随后在精确路径确认后
要求“确认，删除后，你继续推进吧”。据此取消该 backup 的全量内容对账，不声称内容已经证明等价。
执行前先同步本节例外与上位方案，随后只做机械安全检查并删除；本节是实际结果，不是待执行计划。

| 项目 | 结果 |
|---|---|
| 唯一删除目标 | `/Volumes/datasource/backup/research/stk_mins_by_date_clean_next`，realpath 与字面路径一致 |
| 删除前范围 | 21047 个普通文件：21045 个 Parquet、2 个 `.DS_Store`；目录内 21050 个子目录，只有五个 freq 家族和元数据；67676449533 逻辑字节，约 63.03 GiB |
| 安全检查 | 08:21:04 +08:00，全路径及子树无符号链接、无跨 device 项、无特殊文件；元数据数量/字节与首批盘点一致；本机打开文件及旧分钟迁移进程扫描均无目标命中 |
| 精确清单 | 相对路径、类型、大小、mtime_ns、device、inode 的排序 JSON；SHA-256 为 `b423ed947a46d4320a84dcb24908a7e455ab65cd2ff221409c50c90b27e2b38d`。这是元数据清单指纹，不是 Parquet 内容哈希 |
| 执行及核验 | 精确目录递归删除命令退出码 0；08:21:45 +08:00 核验 `lexists=false`；核验时 HEAD `ca6257480f38c547158f86a3de2cc4abea4c8e4f` |
| 排除对象 | backup 的 `research` 父目录、旧湖 `research/stk_mins_by_date_clean_next`、正式 `data_lake/raw/tushare/stk_mins` 均存在且 device/inode 与删除前一致；未对这些数据执行写入/删除。不把目录身份检查说成全内容哈希审计 |
| 恢复能力 | 直接物理删除，未创建额外内容备份，也未调用 Kopia；这些文件不在 Git，不能通过 Git 恢复，不承诺存在其他可恢复副本；逻辑字节数不等于实际磁盘释放量 |
| 代码影响 | `specs/stk_mins.py` 中历史迁移默认源现已不存在，旧入口会找不到输入；这是已退役迁移能力的明确退出，不是现行日更输入丢失。当前 `_materialize_raw_stk_mins_partition` 仍读 Tushare/prod DB，未改代码、参数或正式数据 |

临时证据目录为 `/private/tmp/lake-retirement-delete-20260905.fZGKOr/`，其中 `metadata.json`、
`preflight.json`、`result.json` 保存执行信息，不包含已删除备份内容；稳定结论保存在本节。
其他物理数据、旧产品代码、旧文档和 ignored 环境均未删除，M1–M7 与整个 M8 不因本项完成而算完成。

### 16.10 继续推进：stock_daily 旧报告用途核验

08:24 +08:00 只读核对 `lake_console/reports/stock_daily_missing_ranges.csv`。预算为 2 个精确日期、
4 个代码、11 个输入文件合计 1463473 字节；DuckDB 内存上限 256 MB、2 线程、仅放行精确输入路径，
禁用其他外部访问及持久化 secrets，耗时 0.44 秒。没有扫描全历史分区，没有请求生产库/Tushare，
没有运行修复或写回。所有 11 个文件前后内容哈希一致。

| 报告项 | 当前证据 | 用途结论 |
|---|---|---|
| 001257.SZ、688813.SH、920055.BJ，2026-03-31 三条未标 S 的 single | 正式 Raw/Silver 日线各代码各有 1 行；Silver stock_basic 的上市日均为 2026-03-31，两层当日停牌表均无这三个代码 | 三条“缺行”描述已不反映当前 Lake，不需要据此补数据；不推断当时为什么缺行 |
| 其余标 S 的 31 条区间/单日 | 将 single 归一为同日起止后，代码+起止日与当前 `defs/corrections/suspend_full_day_ranges.csv` 31 项完全对应；双向 EXCEPT ALL 仅报告多 1 项，seed 无多余项 | 规则已经由现行 seed 承接，原报告不是唯一依据；保留 seed 和 `suspend_full_day.py`，不是删除停牌能力 |
| 报告多出的 920188.BJ，2026-03-30–31，标 S | 当前 stock_basic 上市日 2026-03-30；两天 Raw/Silver 各 1 行，收盘价分别 30.20 / 25.29，成交量均正；两层停牌表都无对应记录；现行 seed 不含该项 | 旧报告的 S 标注与当前行情事实不符，不得把它“补入”现行停牌 seed，也不能据此删除或屏蔽正式行情 |

消费者核对：`suspend_full_day.py` 的 `_PATCH_CSV_PATH` 是同目录 `suspend_full_day_ranges.csv`，
不是 reports 文件；`suspend_full_day_ranges()` → `suspend_full_day_ranges_values_sql()` →
`duckdb_sql.py::silver_stock_suspend_daily_select()` 按分区日期生成全日停牌规则。函数还独立处理
688766.SH / 688005.SH 两条 raw override，均保留。CodeGraph 两次 explore 未准确命中该报告动态
文件路径，已直接阅读上述代码、路径函数及停牌 CSV，未把无图命中当作无消费者。

原报告 SHA-256 仍为 `671b4266509bb25d3a9c369e1c7eecdde7ba63c84ffa15522378c91317fa045a`；
当前 seed 为 `3969f5c9ccd177bb4ea389136798b6e28925b2a54b1a583e3a47bca2af8a9e63`。
11 个输入路径、指纹和查询样本保存在上述临时目录 `report_audit.json`，稳定判断以本节为准。

结论：35 项报告内容的用途已分类闭合，转为 `DELETE_AFTER_DEPENDENCY`，与另两份 CSV 一样等待
删除前引用复核和用户具体确认。本轮不删报告、不改 seed；31 个历史停牌范围没有全量重验所有物理分区，
不能声称其历史数据质量已全部通过。报告清退只依赖“有效规则已有现行承接、其余缺行已不存在或旧标注
不适用”，不以本报告重写现行数据。下一批仍是旧湖逐数据集用途审计及恢复记录前置项梳理。

### 16.11 TODO-SUSPEND-001：消除停牌修正规则的运行时 CSV 隐性依赖

- [ ] **待后续治理，本轮仅登记，未实施。** 2026-09-05 用户明确要求：停牌修正规则后续不能再靠读取
  文件承载，要消除隐性依赖。§16.10 的“保留”仅指当前防误删，不代表认可这套长期实现。

**当前代码事实与风险**

`defs/corrections/suspend_full_day.py` 通过 `_PATCH_CSV_PATH = Path(__file__).with_name(...)`
定位同目录 `suspend_full_day_ranges.csv`，`suspend_full_day_ranges()` 用 `csv.DictReader` 读取，
并用 `@cache` 保存在进程内。`suspend_full_day_ranges_values_sql()` 将规则拼进 SQL，直接消费者有：

1. `defs/duckdb_sql.py::silver_stock_suspend_daily_select()`：生成正式 Silver 停牌数据。
2. `defs/assets/suspend_d.py::_full_day_patch_ctes()`：支撑冲突检查、修正数量及样本统计。

这意味着该 CSV 实际参与业务结果，不是可随手清理的报告。文件缺失会使首次加载失败；直接修改文件
又不一定被已有进程重新读取，存在进程间规则不一致的风险。此次通过 CodeGraph explore 和当前代码
核实上述直接读取链；后续实施前仍须补齐所有下游消费者、测试和运行影响，不能把本次登记当全量审计。

**后续目标与验收要求**

1. 先核清为什么需要这些人工修正、每项依据和现行有效性，再设计明确的事实源、管理入口和依赖契约；
   不只是把 CSV 换个格式、位置或隐藏读取函数。本次不预先决定建什么表或新增什么系统。
2. 停牌修正规则不再由运行代码隐式打开 CSV/旁路文件加载；规则来源、生效方式及影响范围必须可查，
   消费者显式依赖同一口径，不再依赖进程内缓存偶然决定采用哪版规则。
3. 迁移前逐项核对当前 31 条区间规则；同模块的两条 raw override 也需纳入影响面核验，不能遗漏或误删。
   核验仍有效的停牌规则必须保留业务效果；过期或错误规则的纠正须有证据和明确批准，不机械复制旧报告。
4. 验收至少证明：有效规则迁移前后结果一致、正常交易日不会被误标停牌、所有消费者使用相同规则、
   移除旧 CSV 后主链不再读取或依赖它。若结果需要纠正，单列差异与批准依据；不保留旧文件读取兜底。

**执行边界**：这是用户要求登记的后续治理项，不自动扩成清退 M0–M8 的新实施内容或前置门禁。
本轮不改 CSV、Python、SQL、正式停牌数据或其他业务数据。替代方案经确认、实现验收完成且具体删除
清单获批后，才能移除旧读取链及 CSV；在此之前继续保护现有依赖，不因“危险”立即删文件。

### 16.12 2026-09-05：五个旧 Raw 数据集与身份映射的用途初核

本轮是用户要求继续的只读审计，不执行迁移、修复或删除。开始基线为 `dev-interface@ca625748`；
审计期间其他任务提交到 `a5f995fa`，两次 HEAD 之间仅两个 asset governance 测试变化，本轮所读
生产代码未变，未触碰其他任务文件。CodeGraph 已执行 status、explore、callers，并在 HEAD 更新后
sync/status；图未精确表达的动态目录读取由当前 catalog/scanner/spec 实现补核，不以无图命中证明无依赖。

#### 16.12.1 当前消费者和承接来源

下面链接均指向本轮实际阅读的实现。旧代码尚未清退，不能把“正式主链不使用旧湖”写成“全仓没有旧读者”。

| 对象 | 仍在仓库的旧读取/入口 | 正式生产者及保留内容 |
|---|---|---|
| daily | 旧 market catalog 的 daily 节点、filesystem scanner、prod Raw 日线导出；旧 `stock_daily_bootstrap_spec` | [raw_tushare_stock_daily](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/assets/stock_daily.py:416) 从 Tushare 取分区，写正式 `raw/tushare/stock_daily`；Silver 读正式 Raw 及基础/停牌数据，不从旧湖日线承接日更 |
| adj_factor | 旧 market catalog/scanner；旧 `adj_factor_bootstrap_spec` | [raw_tushare_adj_factor](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/assets/adj_factor.py:243) 从 Tushare 写正式 `raw/tushare/adj_factor`；复权因子能力与正式数据保留 |
| suspend_d | 旧 market catalog/scanner；旧 `suspend_d_bootstrap_spec` | [raw_tushare_suspend_d](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/assets/suspend_d.py:348) 从 Tushare 写正式 Raw，允许空分区；正式 Silver 修正规则与 §16.11 CSV 读取链当前保留 |
| stock_basic | 旧 reference catalog/scanner、prod current 导出；旧 `stock_basic_bootstrap_spec` | [raw_tushare_stock_basic](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/assets/stock_basic.py:129) 直接拉取当前基础信息到正式 Raw full 文件；不是从旧 current 文件复制 |
| trade_cal | 旧 reference catalog/scanner、prod current 导出；旧 `trade_calendar_bootstrap_spec` | [raw_tushare_trade_calendar](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/assets/calendar.py:105) 从 Tushare 取 SSE 日历并写正式 Raw full；旧 `manifest/trading_calendar` 另被旧导出/分钟恢复读取，不能连带删 |
| security_identity | 旧 `stock_identity_map_bootstrap_spec` 明确把旧 manifest 映射到正式 Silver；旧分钟 migration 的 plan/migrate/audit 等仍调用它 | [silver_stock_identity_map](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/assets/stock_identity_map.py:365) 从正式 `silver_stock_lifecycle`、`silver_namechange` 与当前 mapping seed 构建，**不以旧 manifest 作为现行输入**；资产、seed、checks 和所有正式消费者继续保留 |

旧 scanner 当时的实际路径拼装是 `lake_root / node.path`，分别按日期目录或单文件读取；证据保存在
`3ed4c6ca:lake_console/backend/app/services/filesystem_scanner.py:282`（M6 已删源码）。因此仅搜索完整 Parquet 文件名不足以排除当时的旧消费者。
以上六个旧 spec 的源/目标与 SQL 已逐份核对。本轮只静态提取日期/类型投影做只读比较，没有 import、
运行旧 executor 或恢复旧 bootstrap 权限；旧 migration 主体已在 M3 退出，六个旧 spec/executor 与旧产品分别归 M4/M6，不影响当前 Tushare/正式湖链路。

#### 16.12.2 物理范围与逐项结论

本表旧路径相对于 `/Volumes/datasource/goldenshare-tushare-lake`，新路径相对于
`/Volumes/datasource/data_lake`。数量为 Parquet 数，不混入 `.DS_Store`；日期范围只是文件分区覆盖，
不是每个日期/证券均正确完整的证明。早期缺失只相对于表中正式 Lake，未审计 Prod/其他存储，不能称全局唯一。

| 对象及精确对应路径 | 当前物理与内容证据 | 本轮分类、删除前尚缺什么 |
|---|---|---|
| `raw_tushare/daily` → `raw/tushare/stock_daily` | 旧 8640 个分区，1990-12-19–2026-05-15；新 3083 个，2014-01-02–2026-09-04。共同 3004 个；旧独有 5636 个、253397444 字节，全部为 1990-12-19–2013-12-31。抽读旧早期首/中/末三分区分别 3/1114/2352 行，不是空目录 | `PENDING_AUDIT`。早期历史未在所比新湖承接，先保留并核是否仍有历史研究/业务用途及其他保留来源；重叠部分仅抽样等价，不整段判重复。正式代码 `STOCK_DAILY_MIN_TRADE_DATE=2014-01-01` 与范围差异相符，本轮不把早期缺失认定为新湖 bug，也不擅自补录 |
| `raw_tushare/adj_factor` → `raw/tushare/adj_factor` | 旧 4215 个分区，2009-01-05–2026-05-15；新 4294 个，至 2026-09-04。旧路径全部有对应新分区；5 个样本逐行等价 | `PENDING_AUDIT`。尚缺其余重叠分区的内容/键/字段核验，路径全覆盖不是全量替代证明；再解除旧 catalog/spec 依赖后才能评估候选 |
| `raw_tushare/suspend_d` → `raw/tushare/suspend_d` | 旧 6381 个分区，2000-01-04–2026-05-15；新 3083 个，2014-01-02–2026-09-04。共同 3004 个；旧独有 3377 个、10355813 字节，全部为 2000-01-04–2013-12-31。早期首/中/末样本分别 8/127/122 行 | `PENDING_AUDIT`。与早期日线一起核用途，不能因新停牌数据日更正常就删历史。当前停牌修正 CSV/SQL 不在旧数据删除目标中 |
| `raw_tushare/stock_basic/current/part-000.parquet` → `raw/tushare/stock_basic/full/part-000.parquet` | 全文件旧 5842 行、新 5895 行；旧代码集合多 `TS0018.SH` 一项。完整 17 字段双向差集为 5655/5708 行 | `PENDING_AUDIT`。不是完整重复快照；先解释缺失退市证券及状态/退市日期等变化，确认历史用途与保留来源，不能只按新文件较新判可删 |
| `raw_tushare/trade_cal/current/part-000.parquet` → `raw/tushare/trade_calendar/full/part-000.parquet` | 全文件双方各 13162 行；规范日期/类型后 4 字段双向 `EXCEPT ALL` 均 0，无旧文件字段被遗漏 | **仅旧这个 Parquet** 为 `DELETE_AFTER_DEPENDENCY`。现内容有正式副本，仍须 M4/M6 移除旧适配器/产品入口、执行前重核与用户具体确认。未包含旁边 `.DS_Store`、父目录或 `manifest/trading_calendar/tushare_trade_cal.parquet`；后者未做此次内容比较 |
| `manifest/security_identity/security_identity_map.parquet` → `silver/basic/stock_identity_map/part-000.parquet` | 全文件旧 6089 行、新 6146 行。旧独有 source code 为 `706055.SH`、`TS0018.SH`；共有映射的 latest code 无差异，但 valid_to/effective_delist_date 各 17 项不同 | `PENDING_AUDIT`。两条旧映射和有效期变化尚未解释闭合；当前 mapping seed 与正式资产保留，不能把旧映射无条件追加到新表，也不能以新表行数更多判旧表无用 |

快照差异的业务含义须进一步核实：

- `TS0018.SH` 在旧 stock_basic 中是“上港集箱(退)”，`list_status=D`，上市 2000-07-19、退市
  2006-10-20；旧 identity 为其自映射。不是仅凭名字推测的“垃圾代码”。
- `706055.SH` 旧 identity 映射到 `600680.SH`，有效期 1993-10-18–2019-05-24，旧记录标
  `confidence=inferred`、来自 namechange 重叠推断。尚未验证推断正确，**既不直接删，也不直接沿用**。
- stock_basic 共有代码比较中，名称 247、上市状态 14、退市日期 16 项变化，另有英文名等描述字段
  更新；变化不能全部当成丢数，也不能全部视为可忽略。
- identity 完整行差集为 6089/6146，包含共有记录 `created_at` 的 6087 项变化及来源/理由的
  5837 项变化；这不是“全部证券身份都不一致”。剥离观测/生成字段后，仍有上述旧代码与有效期差异待核。

#### 16.12.3 样本、指纹和审计限度

主对账于 08:46:27 +08:00 完成：42 个精确输入文件、3849480 字节、0.612 秒；DuckDB 内存
512 MB、2 线程、45 秒中断预算，禁用 Hive 自动字段补入、额外外部访问和持久化 secrets，只放行精确路径。
旧数据投影采用已读 SQL 中明确的日期/类型转换，保留全部旧字段，双向 `EXCEPT ALL` 不做浮点舍入；
对账前后 42 文件 SHA/大小/mtime 一致。另对上述两条旧证券记录及正式 lifecycle 做过小范围只读取样，
不据此宣称生命周期全表验收。没有连接 Prod/Tushare，没有运行资产检查、迁移或数据写入。

| 数据集 | 抽样共同日期（括号内为旧=新行数） | 内容对账 |
|---|---|---|
| daily | 2014-01-02 (2354)、2020-03-04 (3846)、2026-05-15 (5495)、2026-03-31 (5482)、2026-05-07 (5493) | 五个样本双向差集均 0；其余共同分区未全量验证 |
| adj_factor | 2009-01-05 (1603)、2017-09-01 (3499)、2026-05-15 (5523)、2026-03-31 (5499)、2026-05-07 (5519) | 同上 |
| suspend_d | 2014-01-02 (121)、2020-03-04 (15)、2026-05-15 (27)、2026-03-31 (23)、2026-05-07 (27) | 同上；空分区允许性不等于已验证整个日期范围 |

旧 trade_cal 精确候选文件为 68332 字节，SHA-256：
`1f85de555ae6be8ea239cf2576d000d1459bfd06833d1558a09da1f338f2bc19`；正式文件 85798 字节，SHA-256：
`fd4828e913af6a091557fe1407e2c795e6d2a5b31aedb5a54f7ccef949768ee9`。
二者字节不同但规范后全字段/行等价；这证明的是本次内容承接，不是物理文件相同。

临时证据 `/private/tmp/lake-retirement-audit2-20260905.Lcviqk/` 中的 `inventory.json` 保存六对象双方
逐文件元数据；`comparison.json` 保存 18 组对账、6 个早期样本、全部输入指纹/schema、逐字段差异和
投影源码 SHA。稳定结果保存在本节，临时文件不是数据备份，也不是必须保留到执行时的唯一删除依据。
后续实际删除必须重新生成精确证据；本轮只有 **5/54 Raw 的首轮分类 + 一个 identity 对象初核**，
其余 49 个 Raw、旧 manifest 日历/参考数据、research/derived 及本批未决差异均未结案。

### 16.13 2026-09-05：两次分钟恢复遗留的再次核验

08:52:52–53 +08:00 定点重验 §16.2 Raw 与 §16.7 Silver 两个 2026-07-27 run：总计 12 个遗留
文件、53115430 字节；连同 10 个正式文件共哈希读取 129366998 字节（包含 manifest 复读），没有写湖。
检查 realpath、无符号链接、同 device、文件集合与哈希期间大小/mtime 不变；两个家族各只发现这一份
run manifest。两个精确 run 的 `_staging/recovery_run_id=...` 均不存在，不据此删除共享 `_staging` 根。

| 独立核验项 | Raw `f573265f-1162-4535-9089-c486f7b7dac1` | Silver `70c5f3d5-3857-4fa9-b840-3d632fba9e3f` |
|---|---|---|
| 遗留内容 | 5 份替换前文件 31282051 字节 + manifest 4572 字节 | 5 份替换前文件 21811817 字节 + manifest 16990 字节 |
| 当前 manifest | `promoted`，五频完整，SHA 仍为 §16.7 所列值 | 同左，各用自己的 manifest，不套用 Raw 结果 |
| 旧文件核验 | 5/5 的字节数、SHA 等于自己的 `target_files_before` | 同左 |
| 正式文件核验 | 5/5 的字节数、SHA 等于自己的 staged 记录 | 同左 |
| 旧与正式是否相同 | **五频均不同**；旧文件是被替换的版本，不是当前正式数据副本 | 同左 |
| 代码恢复用途 | `apply_stk_mins_raw_replace_from_prod` 的 `_restore_backups` 仅处理本次调用已移走的文件；CLI 仅 plan/apply，无从历史 manifest 恢复/续跑入口 | Silver apply 同样仅在本次异常分支回滚；CLI 无历史恢复入口。工具保留，不因遗留文件退出而删改 |

CodeGraph callers 各命中自己的 CLI `main`，并已直接阅读两个 apply、两个 CLI、回滚函数和路径构造；
既没有把 CLI 无历史恢复参数当作“人工不可能恢复”，也没有调用旧恢复代码作验证。

对 [当时的事故/执行记录](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stk-mins-prod-task-run-readiness-low-level-design.md:280)
所列 run ID 逐一查询当前本机 Dagster，以下七条持久化记录仍为 `SUCCESS`：

| 阶段 | 实际 job / run ID |
|---|---|
| Raw 复用恢复结果 | `stock_mins_raw_update_from_prod_job` / `ae26c9f7-cb37-40be-9596-39eed38df343` |
| Silver 复用恢复结果 | `stock_mins_silver_update_job` / `33fc6520-9a55-4164-9d31-987c9bbbe9d6` |
| QFQ 日更 | `stock_mins_qfq_daily_update_job` / `f5569417-bd87-4dba-9d07-2f2ce0c69167` |
| QFQ 因子修复 | `stock_mins_qfq_factor_repair_job` / `96bb23db-04f2-4673-a6ce-6a2108a9c8d7` |
| MACD/KDJ 日更 | `gold_stk_mins_qfq_macd_kdj_daily_update_job` / `5202cc2a-6492-47ba-8443-6133c595a8be` |
| MACD/KDJ 修复 | `gold_stk_mins_qfq_macd_kdj_repair_job` / `ff441876-2ca2-4844-8789-5a0efeb25b7b` |
| WMT 日更 | `gold_wealth_market_turnover_update_job` / `a340e0b3-3833-4ce2-9c08-70badd6d2771` |

这证明历史流程有成功结束记录，**不等于本轮重跑全部 checks，也不证明当前全部下游内容无变化**。
点时 GraphQL（Dagster 1.13.18）在途六类状态合计 0；旧 Console/两类恢复/旧迁移进程未命中，
本机 `lsof` 对两个精确遗留根及旧湖根未命中，退出码 0。这些只是点时本机证据，不排除将来执行、
人工/异机用途，也不用于给整个旧湖放行。

两项均继续为 `DELETE_AFTER_DEPENDENCY`，本轮 `DELETE_READY` 仍为 0。必要前置项分清如下：

1. M3/M4/M6 按原顺序处理旧入口及 Raw 工具依赖；本次不提前删除数据、改 Raw 代码或扩大 Silver 重构。
2. M8 提请删除前，把各自 manifest 的必要执行/指纹摘要纳入事故记录，处理原记录对物理 manifest 的
   证据引用；本节已保存用途摘要，但未改原事故文档，不把其引用当作已解除。
3. 向用户明确：删除将丢失这 10 个替换前版本与 2 个原始 manifest，无法通过 Git 恢复；未核实其他
   可恢复副本，不能承诺可恢复。须确认不再需要人工回退/取证，再确认两个独立的逐文件清单。
4. 实际执行前再核指纹、正式目标、在途/占用和新消费者；任何变化都暂停该项，不按旧成功记录强删。

定点文件/运行快照保存在本轮临时目录 `recovery.json`；七条历史 run 查询结果摘要已完整记于上表。
旧湖自己的 `_recovery` 20 个目录、其他指数/九转/MACD 隔离项、本轮未审的 staging 均未获得新删除资格。
BSE/WMT 当前恢复证据链继续按 §16.7 保护；七条 7 月历史 run 成功不用于证明后续 BSE/WMT 恢复已结束。

### 16.14 当前执行清单：只按代码引用批量分类

**本节替代此前物理审计的分类及剩余待办。** 用户已确认不需要代码未使用的数据；本轮只审代码、配置和
路径构造，复用既有目录名清单，没有打开 Parquet/CSV 数据、读取恢复 manifest 内容、查询数据库/Dagster，
也没有重新比较日期、行数、哈希或检查数据完整性。代码清退及物理删除均未执行。

#### 16.14.1 代码证据和排除误报

2026-09-05 09:19 +08:00，基线 `dev-interface@0bae0fd0`。集中扫描 3227 个 tracked/非 ignored
untracked 程序及配置文件（Python、Shell、SQL、TS/JS、TOML/YAML/JSON 和 bin 入口），75 文件命中
旧路径/旧参数等候选词。按代码区分正向读写、旧入口、负向拒绝、测试及纯文字，不把命中数当消费者数。
另只读核 `.env.web.local` 的 Lake root 与旧 Console 本机 root，不输出凭据、不修改配置。

| 证据 | 确认的实际含义 |
|---|---|
| 旧 catalog 汇总入口：Git `3ed4c6ca:lake_console/backend/app/catalog/datasets/__init__.py:15`，以及当时九个数据域定义文件 | 静态提取 `storage_root`，旧湖盘点的 **54/54 Raw 目录全部有精确 catalog 声明**，没有未归类项；不是逐个读取数据得出的结论。旧产品代码已在 M6 退出 |
| 旧 scanner：Git `3ed4c6ca:lake_console/backend/app/services/filesystem_scanner.py:282`、当时的 `_physical_assets` | 当时拼接 `lake_root / node.path`；还扫描 raw_tushare/manifest/derived/research 和 _tmp/_recovery。旧代码引用曾覆盖这些家族，而非必须硬编码每个恢复目录名；M6 已退出 |
| 六个旧湖 spec + 旧分钟 migration/CLI（M3/M4 已退出 Git） | M0 核验时，旧 Raw daily/adj_factor/suspend_d/stock_basic/trade_cal 和旧 manifest identity 是这些适配器输入。分钟历史默认 source 为已删除的 backup，不是旧湖内同名 research；两者不混淆。代码退出不代表已取得剩余物理数据删除授权 |
| [正式根与路径](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/paths.py:41)、`LakeRootResource` | 正式路径为 data_lake/raw、silver、gold；旧路径片段的禁止列表不是旧数据读取者 |
| [股票分钟 Reader](/Users/congming/github/goldenshare/src/foundation/clients/local_lake/stock_mins_reader.py:91)、`resolve_local_minute_capability` | 依赖配置 root 下的正式 Gold 路径；本机 Web 配置为 `/Volumes/datasource/data_lake`，不消费旧 raw_tushare/research/derived。Reader/API 能力保留 |
| `MajorIndexTurnoverLakeReader`、BSE recovery、九转 no-price history、趋势通道 staging guard | 命中的旧湖根均用于拒绝输入，不是读取旧湖数据；不得因字面命中保留旧数据或删掉保护规则 |
| 正式 `index_daily_000680_history_supplement_apply.checkpoint_path` 中的 `manifest` | 位于正式 staging 的本次 run 下，不是旧湖 manifest；同名目录不能串到删除范围 |
| Raw/Silver 两个 replace apply、CLI 和 `_restore_backups` | 只读写本次 run 新建的备份用于同次异常回滚；已有 run ID 被拒绝，无读取历史 manifest 自动恢复/续跑入口。新 run 的路径模板不意味着历史 run 永久在用 |
| 三份旧报告文件名与两个恢复 UUID 反查 | 本次程序/配置扫描无命中；再结合上一行动态路径语义确认，不单凭零命中判可删。历史文档提及不算代码用途 |

CodeGraph `status/explore` 覆盖旧 scanner、正式 LakeRootResource、当前 WMT `_load_recovery_inputs`；
目录/字符串未被图表达的部分补读实现和静态 catalog。期间其他任务仅提交 ETF 文档/索引，生产代码未变，
已执行 sync/status；没有变更共享 contract、依赖矩阵、CLI 或运行配置。扫描不宣称覆盖仓库外个人脚本，
也不因此追加“所有潜在历史用途均须证明不存在”的门禁。

#### 16.14.2 只有旧代码使用：退出依赖后清退

本组均为 `DELETE_AFTER_DEPENDENCY`。没有找到保留主链对这些旧湖数据的读取入口；不能现在删，是因为
旧 Console 与通用迁移适配器尚在，并非数据完整性或历史价值未知。旧 migration 主体已在 M3 退出，M4/M6 按原 LLD 退出其余适配器/旧产品，
现行 CLI 拆分和回归完成后，再按 M8 申请删除。本轮引用分类覆盖 **106 个已盘点对象**，不以旧湖根整删。

以下路径相对于 `/Volumes/datasource/goldenshare-tushare-lake`；执行清单须展开为绝对路径，不使用通配符。
目录名复用此前元数据盘点，执行前只机械复核范围；新出现的对象须重新列入清单，不借父目录扩大授权。

| 家族 | 精确对象或清单位置 | 数量 |
|---|---|---:|
| Raw | §16.5 的 54 个 `raw_tushare/<dataset>` 精确目录，全部同一处理码 | 54 |
| research | `research/stk_mins_by_date_clean_next`、`research/stk_mins_by_symbol_month`、`research/stk_mins_indicators_by_symbol_month` | 3 |
| derived | `derived/stk_mins_by_date`、`derived/stk_mins_indicators_by_date` | 2 |
| manifest | `manifest/` 下：board_membership、board_universe、downstream_rebuild_requirements、duckdb_compute、etf_reference、etf_universe、index_universe、indicator_recalc_queue、indicator_state、lake.json、lake_jobs、security_identity、security_reference、security_universe、source_partition_events、stk_mins_quality、sync_checkpoints、sync_runs.jsonl、trading_calendar | 19 |
| 旧恢复 | 下列 `_recovery/` 20 个 run 目录；不再核 patch_rows 是否已合入其他数据 | 20 |
| 旧临时结果 | 下列 `_tmp/` 8 个子目录；不再比较候选或备份内容 | 8 |

旧恢复目录（每行完整相对路径）：

```text
_recovery/20260510T233701Z-stk-mins-raw-recovery
_recovery/20260510T233800Z-stk-mins-raw-recovery
_recovery/20260510T234031Z-stk-mins-raw-recovery
_recovery/20260510T234124Z-stk-mins-raw-recovery
_recovery/20260510T234221Z-stk-mins-raw-recovery
_recovery/20260510T234322Z-stk-mins-raw-recovery
_recovery/20260510T234520Z-stk-mins-raw-recovery
_recovery/20260510T234721Z-stk-mins-raw-recovery
_recovery/20260510T234926Z-stk-mins-raw-recovery
_recovery/20260510T235151Z-stk-mins-raw-recovery
_recovery/20260510T235410Z-stk-mins-raw-recovery
_recovery/20260510T235714Z-stk-mins-raw-recovery
_recovery/20260510T235942Z-stk-mins-raw-recovery
_recovery/20260511T000229Z-stk-mins-raw-recovery
_recovery/20260511T000648Z-stk-mins-raw-recovery
_recovery/20260511T000936Z-stk-mins-raw-recovery
_recovery/20260511T001244Z-stk-mins-raw-recovery
_recovery/20260511T001558Z-stk-mins-raw-recovery
_recovery/20260511T001935Z-stk-mins-raw-recovery
_recovery/20260511T002311Z-stk-mins-raw-recovery
```

旧临时目录：

```text
_tmp/20260503T163545Z-stk-mins-range
_tmp/20260507T130033Z-stk-mins-range
_tmp/20260509T202056Z-index-mins-prod-raw-db
_tmp/20260510T015622Z-compute-stk-mins-macd
_tmp/20260513T021617Z-repair-clean-next-2022-bj-freq30
_tmp/20260514T002433Z-research-stk-mins
_tmp/20260514T002501Z-research-stk-mins
_tmp/duckdb_compute
```

这 106 个对象没有当前保留消费者，不再逐项要求数据迁移；独有早期行情、旧证券信息、不同复权版本等
都不改变本次分类。散落的 `.DS_Store` 与共享父目录不追加到这份清单；获批子目录内部的普通附属文件
随该目录范围处理，不建立逐 Parquet 内容审计任务。

#### 16.14.3 无当前代码用途：五项可提请删除

以下 **5 个批准单位**列为 `DELETE_READY`，即无需再证明历史价值或内容替代；仍未取得具体删除批准，
也不跳过 M8 阶段。旧报告 3 个文件，恢复 run 2 个目录（原盘点每个 6 文件），不包含任何共享父目录。

| ID | 精确目标 | 说明 |
|---|---|---|
| D01 | `/Users/congming/github/goldenshare/lake_console/reports/index_daily_continuous_since_list_date_after_20000101.csv` | 旧报告，无代码读取；当前集合不是由此文件动态读取 |
| D02 | `/Users/congming/github/goldenshare/lake_console/reports/namechange_unresolved_candidates_active_only_v2_rules_20260530.csv` | 旧报告，无代码读取；不是当前身份映射 seed |
| D03 | `/Users/congming/github/goldenshare/lake_console/reports/stock_daily_missing_ranges.csv` | 旧报告，无代码读取；现行停牌 CSV 是不同文件，保留 |
| D04 | `/Volumes/datasource/data_lake/_quarantine/stk_mins_raw_replace_from_prod/trade_date=2026-07-27/recovery_run_id=f573265f-1162-4535-9089-c486f7b7dac1` | 已完成的旧 run，代码不把其旧版本作为当前输入；Raw 工具重构要求仍按 M4 保留 |
| D05 | `/Volumes/datasource/data_lake/_quarantine/stk_mins_silver_replace_from_raw/trade_date=2026-07-27/recovery_run_id=70c5f3d5-3857-4fa9-b840-3d632fba9e3f` | 同理；只删此旧 run，不删除或重构 Silver 工具，也不清整个 Silver quarantine 家族 |

D04/D05 的既有 run ID 存在性防覆盖检查不读取旧版本数据，不作为长期保留理由。实际删除前仍检查没有
正在使用这些精确目录的进程/任务；不能沿用前轮无占用快照直接执行。历史事故文档删除时改注“当时位置，
已清退”，不再要求先迁移完整 manifest 或再问是否有潜在人工取证价值。三个报告可从 Git 取回；两组
湖文件不在 Git，删除不承诺可恢复，不新建备份或调用 Kopia。

#### 16.14.4 必须保留和本轮边界

1. 正式 `data_lake/raw|silver|gold` 及当前 Foundation Reader/Wealth API 使用的数据保留；本次不审计
   正式数据是否完整，不改生产数据库、Ops Snapshot 或 Dagster 历史。
2. 当前停牌 `suspend_full_day_ranges.csv` 由 `suspend_full_day_ranges()` 实际读取；当前
   `stock_identity_mappings.cn_a.csv` 由 `load_stock_identity_mapping_seed()` 实际读取。两者均保留，
   不与旧湖 manifest 或 reports 混同；停牌 TODO 仍只是后续治理项。
3. reports 目录保留：[正式审计 CLI](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/audits/stk_mins_silver_strict_audit.py:463)
   默认在其子目录输出。该输出路径不等于 D01–D03，不能因为输出目录在用就保留所有历史报告。
4. BSE/WMT 的 source bundle、actual-changed manifest、checkpoint 和被这些输入指向的候选属于
   当前恢复/审计代码读取范围，按真实依赖保留；与 D04/D05 无关。不再全盘盘点 staging，也不因
   本次简化把其他指数/九转/MACD 正式治理隔离目录扩大为本轮删除目标。
5. ignored 环境、本机配置、共享上层目录不删；Git 旧代码/86+3 文档仍依照原处理矩阵，不因物理用途
   标准简化而跳过当前 CLI 迁出、模板内容迁移及回归要求。

临时可复核证据为 `/private/tmp/lake-retirement-code-refs-20260905.hindQZ/code_reference_audit.json`：
含程序输入指纹、命中位置、54 个 catalog 对应项与 106 个旧湖精确对象。只对源码生成指纹，没有对湖
数据计算内容哈希。稳定分类和完整目录名称已落本节及 §16.5；临时文件不是唯一执行依据。
