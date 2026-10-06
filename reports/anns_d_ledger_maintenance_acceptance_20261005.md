# 公告下载台账查询与维护验收（2026-10-05）

状态：本地 CLI 实现与隔离/正式只读验收通过；本阶段未提交。**按用户要求停在台账能力，尚未开始数据中心页面、API、Figma 或产品功能设计。**

## 目标、依据与实现

依据原[技术方案](../docs/datasets/anns-d-pdf-download-technical-plan-v1.md) §11 和[LLD](../docs/datasets/anns-d-pdf-download-low-level-design-v1.md) §16，以及当前 Ledger、Volume 和 Files 协议，新增 `python -m src.scripts.announcement_ledger` 六子命令：summary/runs/files/show/verify/repair。

查询可直接显示台账位置、文件状态与日期统计、历史来源/运行原因、日期/完整代码/标题/状态筛选、单文件六字段来源值。默认页 20、最多 100，SQL 参数化，按 key/rowid 翻页，无 OFFSET/fetchall。只读 SQLite mode=ro/query_only，允许观察 schema 1/2；不创建/升级台账、不探测写外盘。状态列表均标 physical_status=not_checked；verify 才读实际 file size/hash。

repair 必须指定单一 artifact_key，先只读核验存在及归档身份，再获取原 Volume 排他锁，在锁内重读目标并调用原 Files.allocate/recover。保留缺失/损坏/未知文件证据，恢复 prepared，或将缺失/失败整理为 pending；零 HTTP，不重写历史 run/task outcomes/source_records/cooldown/attempts。返回 redownload 日期参数后，由用户自行执行原日期下载命令；原命令会枚举这一完整自然日，同日其他未完成任务也会下载，有效文件跳过，不是单 URL 立即下载接口。缺 URL 记录仍计入来源概况，不强行制造下载任务。

新内部查询配置集中于 LedgerQueryPolicy：page_default=20、page_max=100、query_timeout_seconds=4、sql_progress_steps=1000，无 env/DB 持久化，每次 JSON 可见；完整审计见 LLD §16.2。现有 SQLite DELETE journal、5 秒 busy timeout 不变，整次只读观察事务共用 4 秒截止时间，在卷复检/打印/物理哈希前关闭。超预算或 Ctrl+C 中断查询，不自动扩大限制或建索引。

改动文件：新 announcement_ledger.py、maintenance.py、test_announcement_ledger.py；Ledger 新 read_only 分支、Volume 提取现有禁止归档路径规则、Files.fingerprint 添加 O_NONBLOCK/同设备门禁；更新两份原方案和本组验收报告。原下载 CLI 四参数、DG reader、HTTP/限速、schema 2、DatasetDefinition 与 Dagster/Prod/Lake 主链不变，无新增依赖或服务。

## 自动验证

最终联合 **178 项通过，13.19 秒**：已有下载专项 113、维护专项 49、架构护栏 16。既有本机 HTTP fixture 需工具提权绑定临时端口，全部在临时目录完成，不请求真实 PDF 服务或写正式台账。维护专项正/反例覆盖：

- schema 1/2 查询后 SQLite 字节/目录树不变；missing/empty/unsupported/schema/identity/symlink 失败不建账，不升级。
- 101+文件 keyset 分页、日期/完整代码/状态/run/title 参数化筛选、引号与百分号/下划线原文、来源 NULL/空串及缺 URL 统计；限制、日期/cursor/key 和 policy 反例。
- 真实长 SQLite SQL 的 deadline、整次快照预算及 callback 清理；独立子进程对 CLI 的实际 OS SIGINT 得到 130，台账字节不变。
- succeeded 被删除时列表仍为账面事实，verify 报 missing 不改账；repair 后原下载仅请求缺失一份。损坏文件保留并分配新路径，其他有效文件跳过。
- prepared part/final/证据缺失三窗口；哈希后取消保留 part，续操作恢复；rename 后台账写失败保留 final/prepared 并可零网络恢复。
- FIFO 非阻塞拒绝、symlink/hardlink/越界/跨设备拒绝；锁冲突/缺目标/错卷不修改台账；写入门禁处取消不升级旧版。
- failed/blocked/downloading 可重新整理 pending，attempts/历史记录/冷却不重置；临时 schema 1 已知档升级也保留历史。

CodeGraph explore/search 用于原 CLI→Volume/SourceVolume→Ledger→Files 与消费者影响面审计，泛化同名结果补读实际目录源码/SQL/测试；实现后 sync/status 为 up to date。依赖矩阵、业务子系统、数据集/页面/API 契约没有变化，不更新架构快照。后续需要人工讨论的边界只有数据中心产品细节和 Figma，本轮不跨越。

## 正式只读验收

通过实际 CLI main 共 **16 次**调用，分别验证 schema 1 默认归档与 schema 2 独立五文件验收归档。每个归档都查询概况、两次有界文件分页合并得到同日五 key、两条运行和单条来源；默认根校验一个既有文件，新根校验五个，共六份现场 size/hash 匹配。只读模式不需要 DG/DuckDB/PG/CH/网络在线。原始命令、JSON、计时与指纹见[机器报告](anns_d_ledger_maintenance_acceptance_20261005.json)。

| 归档根 | schema | 文件任务 | 来源映射 | 台账 bytes | 现场匹配文件 | 台账前后 SHA-256 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| /Volumes/datasource/announcements | 1 | 34188 | 34188 | 54812672 | 1 | 相同 |
| /Volumes/datasource/announcements/dg-source-acceptance-20261005 | 2 | 5 | 5 | 65536 | 5 | 相同 |

两份真实 SQLite SHA-256 前后均相同。每次完整 CLI 耗时 0.505—0.995 秒，包含实际外盘检查；不是单纯 SQL 计时，不外推全历史台账容量/性能。所有正式命令为只读，schema 1 默认台账仍为 schema 1；没有升级正式台账、repair、删除 PDF、网络请求、数据库/lake写入、DG动作或依赖安装。

## 使用与交付边界

在 `/Users/congming/github/goldenshare` 执行：

```bash
.venv/bin/python -m src.scripts.announcement_ledger summary
.venv/bin/python -m src.scripts.announcement_ledger files --state failed --limit 20
```

单文件 show/verify/repair 和翻页例子见 LLD §16.4。修复真实归档应由管理员明确选择具体 key 后自行运行；本轮只验证隔离修复。现场拔盘/重挂载、真实大文件及全量台账预算未验证。既有 DG 连续日常稳定性验收继续独立进行。

**台账能力已完成，当前停下。数据中心页面/API/Figma/产品功能相关工作需先讨论产品细节并完成 Figma，之后另行授权。**
