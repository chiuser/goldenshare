# DG周/月Silver自动维护开工审计（2026-10-17）

目标：补齐已确认的handoff内存测试消费者，并一次核对第2项Raw通知→Silver自动维护的当前入口、测试、治理同步和权限边界。本轮不开发代码、不执行管道，不重新审计行情。基线b9ba7163；第1项恢复修复及87项隔离证据沿d865e640和共享LLD §11.11复用，未重跑或升级为第2项验收。

## 结论

已批准的test_stock_period_handoff_memory.py白名单遗漏已修正。当前静态引用检出44份文件，全部逐项分类，未分类差集为0；具体路径、导入、事件回调位置及本轮源码指纹见[consumer_inventory.json](consumer_inventory.json)。这表示本轮检出集合有明确处理结论，不声称静态搜索能证明所有未来动态行为。

**以下为当时审计结论，随后管理员已要求清退该逐文件登记机制，现行方案见共享LLD §11.8；本报告及JSON保留为修改前证据。** 当时继续开发仍有一项待确认：受保护测试的固定源码读取名单尚未覆盖两个计划新增的Silver sensor文件。原方案没有包括这项权限同步，故本轮只记录精确建议，未改启动器或测试权限，尚不能报告1—3全部推进条件齐备。

## 已核实的影响面

| 类别 | 处理 |
| --- | --- |
| Raw真实生产链 | run_period/replay_events、daily/history/handoff、Raw CLI、周线补报op全部同步完成引用及通知；原schema、SQL、下载、预算和水位不变 |
| 直接回调测试 | 原history/recovery/handoff/combined、Silver共用夹具及此次补列的handoff_memory；迁移内部回调/替身，不削弱原断言 |
| 真实入口回归 | 现有test_stock_period_integration的小型CLI/events/handoff/job场景、test_stock_monthly_definitions、两个Raw sensor测试和周线补报job；不默认修改代码或重跑完整bootstrap |
| Silver消费者与治理 | 既有五份Silver测试、原两资产/job/check、两份HTML治理、静态定义名单及精确标签/STOPPED断言按原设计同步；第1项metadata适配器不能作为第2项真实通知集成证据 |
| 保留边界 | Raw周/月策略及其19:30窗口/水位不改；source/storage/candidate/RSS路径未变时不默认全套回归；四个退役CLI保持拒绝；未发现跨foundation/ops/biz/app或业务API/前端消费者 |

CodeGraph callers/impact用于report_file_events、handoff_bootstrap、run_period；其动态回调结果不完整，已用当前源码导入、别名、events关键字回调、共享夹具及实际CLI/job调用补核。检出包含一个历史审计驱动，明确归为历史材料，不运行或迁移；生产者本身和原显式合同/门禁另按清单中的根文件核对。

## 防漏措施及实际证据

此前措施只有文字要求，没有先用真实代码生成消费者集合再核对白名单，这是连续遗漏的直接原因。本轮改为先检出、再分类、再求差集；迁移、仅回归、保留和历史材料分别记录，不能以手写白名单作为消费者发现来源。

- 初次分类表漏填原计划已有的test_stock_period_update.py时，差集检查实际拒绝；补齐为入口回归后通过，保留该准备阶段失败事实。
- 独立反例：从完整分类集合中故意移除test_stock_period_handoff_memory.py，差集恰好检出该文件；恢复分类后未分类数0。
- 后续变更只复核源码差集及对应直接测试，不增加数据扫描、Tushare请求或运行时检查，不新增长期CLI、配置、状态表或hook。

以下仅重现已列明引用的集合核对，不会导入生产模块或扩大任何权限；源码实际变化后，新增结果必须先按用途人工分类，不能自动加入允许清单：

```python
import json
import subprocess
from pathlib import Path

report = json.loads(Path(
    "reports/dg_stock_period_silver_auto_preflight_20261017/consumer_inventory.json"
).read_text())
actual = {
    Path(p).as_posix().removeprefix("./")
    for p in subprocess.check_output(report["scan_command"], text=True).splitlines()
}
reviewed = {item["path"] for item in report["entries"]}
planned = set(report["planned_new_reference_files"])
unclassified = actual - reviewed - planned
assert not unclassified, sorted(unclassified)
```

## 当时待确认的精确改动（已被随后清退决定取代）

tests/stock_suspend_confirmed_test_runner.py的CONSUMER_SOURCE_FILES是固定、逐文件的源码读取允许名单。tests/test_protected_test_runner_inventory.py独立枚举当前defs文件并验证覆盖，不允许靠跳过、删除断言或自动过滤隐藏缺项。

纯AST/集合核对结果：当前690份defs文件全部在已有名单内；模拟增加下面两个计划路径后，差集恰为这两项；只追加这两项时差集为空。

```text
defs/sensors/silver_stock_weekly_update_job_sensor.py
defs/sensors/silver_stock_monthly_update_job_sensor.py
```

建议在新文件实际开发时，只向上述固定名单追加这两个源码路径；保留test_protected_test_runner_inventory.py的完整覆盖、未知/缺失文件、符号链接及权限先于runtime核对。该库存测试仅作直接回归，不默认改断言。禁止目录通配、发现即放行、扩大其他scope或正式Lake/instance/网络/子进程写权限。此项尚未批准、未实施，须确认后落回原LLD白名单。

## 验证边界

本轮执行了源代码静态定位、AST读取、44项分类差集和上述正反集合核对；文档检查结果随本轮交付报告。没有导入/初始化正式Dagster instance，没有运行正式或隔离job/sensor/启动器，没有读取行情Parquet、请求Tushare、写Lake/staging或推进Prod/R3。未改变生产/测试代码，不将本轮静态通过冒充开发或隔离验收通过。其他任务改动保留；本轮文档及审计结果未提交。

## 后续清退结果（2026-10-17，管理员要求）

原“待确认追加两个源码路径”的建议撤回并已清退对应机制。删除consumer手写源码名单和库存覆盖检查；治理测试只读固定src/orchestrator目录，无需新增文件登记或整份源码hash。仅修改测试启动器、该边界测试及原方案/LLD；周/月业务、其他数据集和正式资源未修改。consumer之外四种scope的完整策略及源码范围与修改前逐字相同。

- 8项定向测试通过；真实macOS sandbox验证策略生成后新增源码可读，目录外读取、外指链接、源码/外部写入和自建测试端点连接均拒绝。所有输入均为临时资源。
- 既有catalog治理12项及513个subtests通过，原业务断言保持。两批consumer报告均不再列举/hash全部源码，记录实际只读源码根。
- 两修改Python的Ruff、文档完整性与git diff --check通过；未重跑数据完整性、bootstrap、停牌全链或R3，未提交。
- CodeGraph explore/search/callers/impact核对影响面，修改后sync显示已同步；实际调用仅在测试policy生成与报告中，没有业务API/前端或子系统依赖变化。

本轮证据目录：/private/tmp/dg-source-registration-retirement-5vbx91nc/，其中catalog.log为实际隔离回归日志，catalog-summary.json汇总两批结果，policy-comparison.json记录其余四种策略对照。前文及consumer_inventory.json保留为清退前快照，不能作为修改后源码指纹。
