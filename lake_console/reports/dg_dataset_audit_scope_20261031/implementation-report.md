# DG日期审计五项自动纳入：实施和验收报告

日期：2026-10-31。依据管理员已review的原方案和LLD，严格按文档提交→开发→隔离测试及清理→实现对账→说明同步顺序完成。本轮没有执行正式数据审计或补数。

## 提交与改动范围

- 文档先行提交：`b684397fb`，未推送。
- 实现仅修改本机skill的原`audit_datasets.py`，新增同目录`test_audit_datasets.py`；没有第二套正式入口。
- 同步skill说明、原方案、原LLD和本机操作手册第2节；手册其余部分及其中的命令块保持。
- 本目录`implementation/*.py.txt`只是源码追溯材料，不是运行入口或新增测试发现路径。本次收尾提交纳入这些源码归档、方案说明及验收记录；此前的验收JSON保留提交前快照，不回写其历史状态。
- 操作手册原文件在本轮开始前已是未跟踪文件，因此不将其既有其他章节一并加入Git；本轮仅第2节的修改保存为[差异归档](implementation/operations-manual-section2.patch.txt)，本机手册保留更新后的内容。
- DG资产、catalog事实、job/sensor/check、Prod业务代码、正式数据和依赖均未修改。

## 结果

- 当前源码目录180项：原159项加周/月Raw与Silver四项、公告Raw一项，合计164项纳入，16项排除。日历两项只在排除清单，Silver日历仅作周/月日期依据；没有执行这164项正式数据审计。
- 年度文件和本机/Prod ClickHouse只计请求日期；不可读、可读零行、合法空公告、物理缺失、更新落后、等待及最终未核实分别报告。
- 同周/月文件一次聚合，多日期同年一次计数；23/26/27的新增文件计划含必要Silver日历共10份上界。这里只核对代码计划和隔离查询次数，没有stat正式文件或进行性能试跑。
- 最终95项隔离验收通过（2.49秒，4条现有Dagster/Pydantic弃用警告），不代表正式盘性能或真实数据库连接已验收。
- Ruff检查通过，保留原Python调用和0644权限；仅忽略与既有文件可执行位有关的EXE001，数据/SQL/状态断言没有弱化。

## P1—P10实现对账

| 硬口径 | 原入口实现 | 隔离证据例子 |
| --- | --- | --- |
| P1 分类 | [_build_audit_plan](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/audit_datasets.py:526) | [test_current_catalog_classification_and_file_plan](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/test_audit_datasets.py:244) |
| P2 周月及空/缺失 | [_period_result](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/audit_datasets.py:792) | [test_period_missing_empty_exact_contract](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/test_audit_datasets.py:354) |
| P3 公告 | [_announcement_summary](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/audit_datasets.py:861) | [test_announcement_contract_and_allowed_empty](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/test_audit_datasets.py:581) |
| P4 日期依据 | [_load_calendar_windows](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/audit_datasets.py:653) | [test_no_raw_calendar_read_or_fallback](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/test_audit_datasets.py:1034) |
| P5 源窗口与改变 | [_period_result](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/audit_datasets.py:792) | [test_source_window_not_a_silver_timeout](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/test_audit_datasets.py:511) |
| P6 排除 | [_build_audit_plan](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/audit_datasets.py:526) | [test_unknown_or_conflicting_catalog_does_not_disappear](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/test_audit_datasets.py:287) |
| P7 既有行为与计数 | [_clickhouse_partition_summary](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/audit_datasets.py:432) | [test_clickhouse_count_contract_and_whitelist](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/test_audit_datasets.py:735) |
| P8 同文件去重 | [_audit_dates](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/audit_datasets.py:1025) | [test_multidate_period_reads_once_and_no_final_reread](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/test_audit_datasets.py:523) |
| P9 隔离及中断 | [_audit_dates](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/audit_datasets.py:1025) | [test_interrupt_preserves_finished_report_and_closes_connection](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/test_audit_datasets.py:912) |
| P10 报告与计数 | [_normalize_report](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/audit_datasets.py:912) | [test_normalizer_rejects_duplicate_or_overlapping_assets](/Users/congming/.codex/skills/audit-dg-datasets-by-date/scripts/test_audit_datasets.py:1126) |

表中只列各项代表用例；完整95项参数化记录见[测试XML](implementation/isolated-tests.xml)。另外覆盖：四项周月参数化、2020年2月28/29合法月坐标、周末/跨年、未来日期、已有数据不强制等待、坏文件后继续正常项、只读PostgreSQL及ClickHouse资源设置、年度不读额外年份、输出冲突与失败清理。关键预期采用独立字面日期和计数，未用被测函数生成expected。

## 原行为、旧错误和影响面

- [旧错误复现](implementation/regression-evidence.json)：旧ClickHouse函数仍执行附加统计；旧汇总把不可读和零行算作物理缺失。新实现纠正，正式数据读取为0。
- [源代码对账](implementation/source-reconciliation.json)：既有后端选择、表解析、ClickHouse连接参数AST保持；Serving编排与原只读事务流仅改变错误输出以去除凭据。最终路径修正之后，与三项旧错误相关的函数AST未改变，因此复用已取得的回归证据，不重复运行。
- CodeGraph使用`codegraph_explore`核对`period_for`及其现行调用关系；未修改该函数及8个调用方。仓库外skill不在索引内，通过当前源码和直接调用方搜索补核，没有发现业务API、前端、job或sensor依赖本工具。
- 初轮有5个反例因测试夹具使用`vars()`复制slots数据类而未进入目标路径，按真实catalog的slots合同修正，断言未改。独立对账补齐重复资产计数拒绝，以及绝对路径/目录越界反例，均为原P1/P9要求；目录总数沿用唯一asset key口径，重复登记仍显式报分类问题。
- 测试对正式路径、网络、实例和非只读SQL访问设拦截，并在用例结束确认没有被吞掉的禁止访问；小文件使用生产者schema，Serving仅替代远程边界，不冒充真实连接通过。

## 清理及边界

[验收与清理记录](implementation/acceptance-and-cleanup.json)：最后一轮清理118个测试夹具/临时报告、126,454字节，重复草稿删除；前一轮相同范围清理另有记录。未遗留测试数据树；仅保留必要源码、约束、测试结果和对账材料，不删除共享依赖或历史正式报告。

正式Lake/数据库读写0、网络请求0、job/sensor/check/事件/动态分区操作0、安装0。使用已有orchestrator `.venv`。本轮只完成工具实现验收，不对任何正式日期给出完整性结论。

后续收到明确日期审计任务时，按现有必要性规则决定范围、复用适用证据；不因本轮开发自动执行164项审计、全历史读取或补数。
