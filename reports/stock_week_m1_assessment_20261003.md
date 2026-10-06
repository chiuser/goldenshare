# 股票周线 M0／M1 开发验收记录

2026-10-07纠偏说明：本报告保留历史结论；搬运/审计中间数据文件已按管理员要求清理，不再是正式检查或调度依赖。现行口径为 bootstrap 完整对账一次即结束、日常只检查当前新增周期。详见[清理记录](stock_period_reports_cleanup_20261003.md#2026-10-07运行依赖纠偏及清理)。

日期：2026-10-03。结论：M0 开发前核验已收口，M1 纯合同和规划器已实现。账户配额按管理员确认视为足够，不再作为开发门禁。实际采集、正式文件提升和更新机制尚未交付，分别继续按后续里程碑执行。

依据：[方案](../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md)、[LLD](../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md)、DG 数据集新增模板及专项性能治理规则。

## 1. M0 收口证据

[M0 报告](stock_week_m0_assessment_20261003.md)记录三源接口、日期／分页对账、Prod 规模与代表性 Decimal Parquet 写出读回。两套 Prod 周线合计 5,787,046 行；最后的只读 API 标签核验（历史中间文件已清理）中，两表非预期源接口标签均为零。

账户配额无需再调查。超时、重试、批次、内存和请求总量上限仍保留，用于防止失控执行。M0 代表样本不替代 M2 的实际 adapter、取消／续跑和内存压力验收，也不证明全部退市股票可补齐。

## 2. 改动范围

| 文件（相对仓库根） | 作用 |
|---|---|
| `lake_console/orchestrator/src/orchestrator/defs/run_contracts/stock_weekly.py` | 三源字段／类型、主键、必填策略及冻结预算、范围、库存、unit、manifest |
| `lake_console/orchestrator/src/orchestrator/defs/stock_weekly_planner.py` | 周窗口、代码年度批次、范围拒绝、证据与计划 hash、跳过原因统计 |
| `lake_console/orchestrator/src/orchestrator/defs/run_contracts/asset_column_schemas.py` | 从单一来源合同派生三套 Raw schema |
| `lake_console/orchestrator/src/orchestrator/defs/partitions.py` | 新增独立周分区定义对象；不注册实际分区键 |
| `lake_console/orchestrator/src/orchestrator/defs/paths.py` | 三源 Raw 周路径；沿用正式 Lake 根，保留源日期 |
| `lake_console/orchestrator/tests/test_stock_weekly_contract.py` | 合同、字段、空值、证据和预算正反例 |
| `lake_console/orchestrator/tests/test_stock_weekly_planner.py` | 跨年、排除周、分类、限量及冻结计划正反例 |
| `lake_console/orchestrator/tests/stock_suspend_confirmed_test_runner.py` | 同步精确源码清单，不放宽隔离策略 |

同时更新原方案、LLD、文档索引与 M0 状态，新增本报告及 M1 dry-run 结果（历史中间文件已清理）。已有 API／CLI 签名和默认行为未变，没有增加环境、数据库或运营页面配置项。预算只存在于冻结的 `WeeklyBudget`，进入 manifest 和 plan hash。

## 3. 硬口径对账

| 硬口径 | 实现与验证 |
|---|---|
| Raw 对齐源业务字段，排除 Prod 采集信息 | 三源固定 13／21／11 列；schema 顺序和类型测试；没有 `api_name/fetched_at/raw_payload` |
| 主源保留退市、NULL、历史源日期 | Prod 年度库存按源日期分批；不做价格非空或在市过滤；NULL 必填策略和早于 2010 的年度测试 |
| 自然周归属与源日期分开 | 周分区为 ISO 周五；请求覆盖周一至周日；跨年唯一归属、休市周五与排除当前周测试 |
| 备用源不能冒充复权来源 | 独立 `weekly` 合同不含复权字段；源 enum、字段和主键测试 |
| 尽力补齐，无法补齐仍记录 | 可补／已查空要求源证据引用及 SHA256；未核验、失败、身份未决分类计数保留，不生成下载 unit |
| 不把对象与全日历无界展开 | 只规划给定候选；每 unit、代码、候选键、批次及阶段上限校验，超限拒绝而非截断 |
| 计划可核验、参数变化不能复用旧计划 | 冻结 scope／budget／unit；稳定 plan hash 包含证据 hash、分类和预算；确定性及变更反例测试 |
| 规划阶段没有业务写入 | 纯函数，不连接源、DB、Lake 或 instance；实际样本只读 dry-run |

`max_candidate_keys=250000` 为本轮新增的计划器内存边界，作用于 scope 验证与规划器。默认值及消费者已写回 LLD；预算调整会改变计划 hash。manifest 只保留外部键证据引用，不携带完整明细。

active assets、catalog entries、partition models 和 Dagster 执行 config 在 M4 与实际实现同步注册，避免提前暴露不能运行的数据集。M1 不包括采集 adapter、writer、job、sensor、动态分区注册或事件补录。

## 4. 验证结果

- 定向及相邻回归：**75 passed**，覆盖两套 M1 测试、ETF 路径／catalog、metadata、stock basic schema 和退役边界；28 条既有 Pydantic 警告。
- OS 隔离的 `test_asset_governance_contracts.py`：**12 tests／456 subtests 通过**，使用现有隔离启动器。
- Ruff 定向检查及新增四文件格式化完成；文档完整性检查及 `git diff --check` 均通过。

直接 pytest 首次因隔离 fixture 未初始化而失败，改用既有启动器。启动器先拒绝新增纯合同，随后暴露一项既有清单遗漏：ETF checks／writer 已直接导入 `etf_adj_factor_terminal_exceptions.py`。核验实际 imports 后，只将这两个源码文件补入精确清单；没有改 ETF 逻辑、开放其 YAML、网络、正式 Lake 或 instance 权限，随后治理回归通过。没有跳过失败门禁。

真实样本 dry-run（历史中间文件已清理）只消费已有 M0 CSV／JSON：两主源各 298 个代码、15,346 行，各形成一个 2025 年代码批次；退市 `000005.SZ` 的 656 个已证实候选键全部匹配源证据，形成 15 个年度 unit，含重试最多 45 次请求，首窗口始于 2009-12-28，单 unit 最多 53 周。此样本不能推断全部退市股票均可补。

dry-run 没有网络访问或 DB／Lake／instance 写入，仅生成报告。临时 CSV 引用不构成正式可执行输入；M2 必须重新捕获并持久化可核验输入。

## 5. 影响面及下一步

使用 CodeGraph explore／impact 检查 schema、资源和分区入口；分区 impact 返回范围有限，因此补做当前 imports、catalog active 定义和隔离清单直接引用审计。新合同尚未接入活跃消费者，不涉及 Prod DatasetDefinition／TaskRun／Quote API，未改变业务子系统依赖矩阵。M4／M9 仍须核验实际注册及 sensor/helper 消费者，不能以本轮静态结果替代。

下一阶段 M2 实现只读 Prod 流式导出、Tushare 有界采集／supervisor、持久化 checkpoint、超时取消和幂等续跑，完成实际 adapter 及压力验收。正式 bootstrap、提升、事件补录和自动更新启用按后续阶段执行。

本轮没有正式业务数据写入、安装套件、提交或推送；工作区其他任务文件保持原状。
