# 本地 DG 停牌历史确认事实 S0 审计清单 v1

更新时间：2026-09-06

状态：**S0 已完成；仅只读审计与文档。S1–S5 未实施，TODO-SUSPEND-001 未关闭。**

依据：用户已认可[技术方案](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-technical-plan-v1.md)及[LLD](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-suspend-confirmed-facts-low-level-design-v1.md)，本轮明确要求“先完成 S0”。

代码基线：`dev-interface@b324ec48ce8fd67fdf216fedc6a69103fab4ae3a`。时间均为北京时间（UTC+08:00），除非另有标注。

## 1. 结论与完成清单

**来源与方案一致，4,022 个确认键在现有 Silver 中的效果全部正确，没有发现新增范围冲突。真实逻辑指纹已计算并回填 LLD。**

| S0 要求 | 实际结果 | 状态 |
| --- | --- | --- |
| 刷新 CSV、两个覆盖键与保留规则的身份 | CSV 为 31 区间、29 代码；两个覆盖键未变；14 条时段修正保留 | 通过 |
| 固定正式日历与展开方法 | 使用正式 SSE 开市日；相关窗口 2,929 个开市日；无重复日历日期 | 通过 |
| 从来源展开，不从已有 Silver 反推 | 4,022 行/键、29 代码、1,857 日期；4,020 补缺、2 覆盖 | 通过 |
| 实算批准逻辑指纹 | DuckDB 计算与第二次独立展开后的 Node SHA-256 结果一致，见 §3 | 通过 |
| 冻结两个停牌目录的精确输入集合 | Raw、Silver 各 3,083 文件；路径、大小、内容指纹及文件身份均已记录 | 通过 |
| 核验现有确认效果及冲突 | 每个确认键在 Silver 中恰好一条全日停牌；缺失/重复/冲突为 0 | 通过 |
| 检查非开市日及分区错放 | 两层文件日期均为开市日；文件内部日期错放为 0 | 通过 |
| 验证审计输入未漂移 | 审计前后文件集合及全部输入身份一致 | 通过 |
| 核清部署边界 | 正式 code location 直接使用当前工作区；两个停牌 sensor 均 RUNNING | 已明确，S1 前须安排维护 |
| 隔离集成验证设计 | LLD §6、§9、§13 已规定混合分区/check 阻断及事件关联测试；本轮不实现或执行 | 设计已固定 |

本结论只证明**现有修正规则的输入身份及现有效果**。未重新逐份查公告证明每条事实的独立业务真实性；也未执行尚未实现的新 helper，不能替代 S1 隔离测试或 S2 全范围四列双向 `EXCEPT ALL`。

## 2. 来源身份

实际物理审计时间：**2026-09-06 17:12:25–17:12:28**。

| 输入 | 大小（字节） | SHA-256 |
| --- | ---: | --- |
| [全日停牌 CSV](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/corrections/suspend_full_day_ranges.csv) | 1,407 | `3969f5c9ccd177bb4ea389136798b6e28925b2a54b1a583e3a47bca2af8a9e63` |
| [原范围/覆盖规则](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/corrections/suspend_full_day.py) | 3,812 | `349a5c9d98ef9c038f6245a61ce5c3178ee25eee0a03e61f9283afbb9b948bc4` |
| [保留的时段修正](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/corrections/suspend_timing.py) | 2,307 | `c4d2fb1c7fda5a120e7d9b7f55a11d8b3220616105122883ffbb2886a817ee5b` |
| [正式交易日历](/Volumes/datasource/data_lake/silver/calendar/trade_calendar/full/part-000.parquet) | 89,590 | `0055670758c0365f95f82f629144fe3e24143f6dbf012c728cb0020510107f5a` |

CSV 最近一次提交为 `77ff8e1de72d3cb2eaf7e212edc0f402f3a05763`，时间 `2026-05-21T06:06:58+08:00`；Git blob 为 `90a8c4ade887606d1eaf786f25bc3e042cf8ecb6`。文件系统修改时间只作为输入身份之一，不当作业务事实更新日期。

当前源码中的两个覆盖键：

| 代码 | 日期 | 原规则名称 | 本轮处置 |
| --- | --- | --- | --- |
| `688766.SH` | 2025-11-26 | 普冉股份 | 保留现有效果，固定事实中为 `replace_confirmed` |
| `688005.SH` | 2026-01-16 | 容百科技 | 保留现有效果，固定事实中为 `replace_confirmed` |

日历实际列为 `exchange / trade_date / is_open / pretrade_date`；共 13,162 行，覆盖 1990-12-19 至 2026-12-31，均为 SSE，其中开市日 8,797 个。展开相关窗口为 2014-01-02 至 2026-01-16，共 2,929 个开市日；其中 1,857 个日期命中 CSV 区间。

相关开市日期集合 SHA-256：`89883315e8d91b654d261d859028683fc198152845f5e77f0aac521277d7019a`。

日历集合编码为头行 `stock_suspend_confirmed_calendar|v1\n`，后接日期升序的 `SSE<TAB>YYYY-MM-DD<LF>`；完整有序日期保存在 §7 展开身份报告中。该指纹与整个日历 Parquet 的物理指纹用途不同，不互相替代。

## 3. 实算固定事实身份

按 LLD §3.3 原定编码，实算批准逻辑 SHA-256 为：

```text
c88a7406ecda31c7dfe92b20b1d9cc719ffd2d049ece93113676ef4e60db4307
```

| 项目 | 结果 |
| --- | ---: |
| 规范编码字节数 | 152,875 |
| 行数 / 不同键数 | 4,022 / 4,022 |
| 不同代码 / 不同日期 | 29 / 1,857 |
| `add_missing` / `replace_confirmed` | 4,020 / 2 |
| 最早 / 最晚事实日期 | 2014-01-02 / 2026-01-16 |
| 非法区间、重复区间、重复展开键、非法值 | 均为 0 |

计算过程：直接将 CSV 与正式日历作为关系连接，五列固定排序编码；DuckDB 一次聚合后计算 SHA-256。另一次独立展开生成相同编码字符串，由 Node 对 UTF-8 bytes 计算 SHA-256，结果一致。没有逐行用脚本改写业务事实，也没有从最终 Silver 复制事实作为来源。

这是**待持久化内容的真实逻辑指纹**，不是 LLD 两行编码样例的指纹，也不是尚未生成的 Parquet 物理指纹。本轮只回填文档；`STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256` 对应代码模块尚未实现。

## 4. Raw / Silver 文件范围与现有效果

本轮只枚举以下两个明确目录，不扫描旧湖或其他数据集：

- [Raw suspend_d](/Volumes/datasource/data_lake/raw/tushare/suspend_d)
- [Silver stock_suspend_daily](/Volumes/datasource/data_lake/silver/quote/stock_suspend_daily)

| 项目 | Raw | Silver |
| --- | ---: | ---: |
| 日期分区 / 文件数 | 3,083 / 3,083 | 3,083 / 3,083 |
| 最早 / 最新文件日期 | 2014-01-02 / 2026-09-04 | 2014-01-02 / 2026-09-04 |
| 文件总字节 | 4,571,863 | 4,531,752 |
| 最大单文件字节 | 7,733 | 7,714 |
| 总行数 | 386,240 | 390,259 |
| 文件内日期与分区不一致 | 0 | 0 |

两层日期集合完全配对，均为 `trade_date=YYYY-MM-DD/part-000.parquet`；缺配对、非预期路径、非开市日分区均为 0。拒绝符号链接输入。3,083 个日期中，受确认事实影响 1,857 个，其余 1,226 个；S2 比较范围仍包括两类，不能仅做受影响日期抽样。

| 集合 | 路径集合 SHA-256 | 内容集合 SHA-256 |
| --- | --- | --- |
| Raw | `be6ceed7ab437ef90a484bdd8f5f9fb3b136c67d742cb843cc79239895849cda` | `95767d0ec2a787d2860cb2846acb01163fe4b65331ece2b16f881660fb54f981` |
| Silver | `85816aa1a50bedf503ffbe76ccbfbabcfcb64f24987c9dbd46e0edff6d3a7dcc` | `74b7806d27edf6dd6548870af70cd1c86fb9184332846783efeddd07abe35ac2` |

集合均按绝对路径升序。路径编码为 `absolute_path<LF>`；内容编码为 `absolute_path<TAB>bytes<TAB>physical_sha256<LF>`。逐文件清单另存 device、inode、mtime_ns；审计前后重新枚举并读取内容指纹，全部一致。

**逐键结果：** 4,022 个确认键在 Silver 中每键恰好一行，均为 `suspend_type='S' AND suspend_timing IS NULL`；缺失、重复、错误时段或并存其他记录的确认键均为 0。Raw 中 4,020 个键缺失，只有两个既有覆盖键命中，共 3 行；没有新增未批准的补缺冲突。

两个覆盖键的实际 Raw 内容如下，保留该证据用于 S1/S2 反例与等价测试：

| 代码 | 日期 | suspend_type | suspend_timing |
| --- | --- | --- | --- |
| `688766.SH` | 2025-11-26 | `R` | NULL |
| `688766.SH` | 2025-11-26 | `S` | `09:30-09:30` |
| `688005.SH` | 2026-01-16 | `S` | `09:30-09:30` |

Silver 在这两个键各只有一条 `S + NULL`。总行数差 `390259 - 386240 = 4019 = 4022 - 3` 与规则效果一致；这只是旁证，**不代替新旧实现的全行对账**。

只读存在性检查还确认：新固定事实正式文件、`data_lake_staging/stock_suspend_confirmed` 和 `data_lake_staging/stock_suspend_daily` 均不存在。本轮没有创建它们。

## 5. 方法、批次与性能实测

主审计使用 DuckDB CLI `v1.5.2 (Variegata) 8a5851971f`；每次为内存连接，关闭扩展自动安装/加载，显式允许精确输入文件并锁定配置。SQL 负责连接、规范编码和统计；Node 只负责文件清单、身份指纹、调度有界批次和汇总。

| 项目 | 实测 / 配置 |
| --- | --- |
| 主审计总时间 | 3,024 ms，包含前后内容哈希与查询进程启动 |
| 主审计 DuckDB 调用 | 15 次：展开身份 1、分区开市日核验 1、年度批次 13 |
| 上述查询调用累计耗时 | 1,697 ms；不是额外加在总时间之外 |
| 日期批次上限 | 实际最多 245 日期/批；未超过 LLD 的 366 |
| 内存 / 线程配置 | 每个连接 512 MB / 2 threads；未测进程峰值 RSS，不把设置值当实际峰值 |
| spill | `max_temp_directory_size=0B`，禁止 spill；未创建正式或 staging 临时文件 |
| 额外核验 | 独立编码/hash 复核 1 次；不计入上述 15 次主审计统计 |
| 源请求 / Parquet 写入 / 事件写入 | 0 / 0 / 0 |

按年度使用显式文件列表，`hive_partitioning=false`；每批一次加载固定事实，进行集合式核验，不逐日启动 Dagster。除 Parquet 解码外，还完整读取输入字节做审计前后哈希；该 IO 已包含在总时间内。

| 年份 | 日期文件数（每层） | 确认键 | 查询调用耗时（ms） |
| --- | ---: | ---: | ---: |
| 2014 | 245 | 451 | 148 |
| 2015 | 244 | 302 | 169 |
| 2016 | 244 | 514 | 142 |
| 2017 | 244 | 797 | 139 |
| 2018 | 243 | 318 | 126 |
| 2019 | 244 | 272 | 104 |
| 2020 | 243 | 715 | 102 |
| 2021 | 243 | 404 | 107 |
| 2022 | 242 | 171 | 113 |
| 2023 | 242 | 41 | 105 |
| 2024 | 242 | 14 | 104 |
| 2025 | 243 | 22 | 105 |
| 2026 | 164 | 1 | 79 |

以上是 S0 只读审计实测，不代表新 writer、checks、sensor 或 S2 新旧实现对账性能。S1/S2 仍须分别记录其测试、内存及耗时证据。

## 6. 正式运行边界

用当前进程启动参数、工作目录、editable 安装元数据、生成的 workspace 配置及**只读 GraphQL query**交叉核验；没有调用 mutation、执行 sensor tick 或重载 definitions。

| 项目 | 实际结果 |
| --- | --- |
| 本地服务入口 | `uv … dg dev`，`127.0.0.1:3000` |
| code location / repository | `orchestrator / __repository__`，17:14:05 为 `LOADED` |
| 加载模块 / 工作目录 | `orchestrator.definitions` / `/Users/congming/github/goldenshare/lake_console/orchestrator/src` |
| Python | `/Users/congming/github/goldenshare/lake_console/orchestrator/.venv/bin/python3` |
| 安装形态 | editable；`.pth` 与 `direct_url.json` 指向当前工作区 |
| 实际 DAGSTER_HOME | `/Users/congming/.goldenshare/dagster_home`，已核对 webserver、daemon、code server 进程 |
| instance 存储身份 | PostgreSQL `localhost:5432` / `goldenshare_dagster`；不保存密码或完整连接串 |
| artifact / compute log 目录 | `/Users/congming/.goldenshare/dagster_artifacts` / `/Users/congming/.goldenshare/dagster_logs` |
| coordinator / launcher | `QueuedRunCoordinator` / `DefaultRunLauncher` |
| 活动 run | 17:14:05 查询 `QUEUED/NOT_STARTED/STARTING/STARTED/CANCELING`，结果 0 |
| Raw sensor | 17:15:10，`raw_suspend_d_update_job_sensor = RUNNING` |
| Silver sensor | 17:15:10，`silver_suspend_d_update_job_sensor = RUNNING` |

instance 配置文件 SHA-256 为 `27860ab1b63b33a07c4425177237d374ed55b9e3fab29491fd6dfae344d02049`。GraphQL 的 `instance.id` 是通用字面值 `Instance`，不能当唯一部署身份；后续 plan 必须使用规范化 home 与非敏感存储标识。

查询的最近 3 次 Raw job、最近 3 次 Silver job 均成功，仅作为近期运行旁证，不代表全历史健康证明：

| 最近一次 | run id | 运行时间（北京时间） |
| --- | --- | --- |
| Raw | `dcc15b60-716a-45de-a681-1fe66759395a` | 2026-09-04 17:39:25–17:39:29 |
| Silver | `3591e35c-dc66-4715-9c20-ec9ea03ec943` | 2026-09-04 17:49:22–17:49:26 |

**S1 开工边界已从待核实变为确认存在：改当前源码可能影响新 run 导入，不是“不重载就没影响”。** 两个 sensor 正在运行，某次查询活动 run 为 0 也不等于已进入维护窗口。S1 开发前须得到明确的本地维护安排和开发授权；不自动暂停/恢复任何触发器，不自行新建分支/worktree，不借 S0 跨阶段实施。

## 7. 证据位置与使用限制

本轮临时审计材料只在 `/private/tmp/stock-suspend-s0-20260906.erDtEj`。下列链接指向**成功审计批次**，不是发布 plan、业务事实源或候选数据：

- [逐文件输入清单](/private/tmp/stock-suspend-s0-20260906.erDtEj/attempt-qsqT9G/input-manifest.json)：6,166 个 Raw/Silver 文件及 CSV、规则、日历身份；SHA-256 为 `11dc3fc0125b00be4183e766b1e39f10d155708fe537cde1bc3f0ea3e2b535e4`。
- [展开身份与有序日期集合](/private/tmp/stock-suspend-s0-20260906.erDtEj/attempt-qsqT9G/expanded-facts-identity.json)：SHA-256 为 `0fe26b1eb0075980f65972e45e34c392a1a7373c6637e965216c28d2951a825a`。
- [主审计汇总与逐批结果](/private/tmp/stock-suspend-s0-20260906.erDtEj/attempt-qsqT9G/summary.json)、[SQL 指纹与输入上界](/private/tmp/stock-suspend-s0-20260906.erDtEj/attempt-qsqT9G/query-fingerprints.json)。
- [运行/部署只读结果](/private/tmp/stock-suspend-s0-20260906.erDtEj/runtime-evidence.json)、[sensor 状态及非敏感 instance 字段](/private/tmp/stock-suspend-s0-20260906.erDtEj/runtime-sensors.json)。
- [物理审计脚本](/private/tmp/stock-suspend-s0-20260906.erDtEj/audit.mjs)、[运行状态审计脚本](/private/tmp/stock-suspend-s0-20260906.erDtEj/runtime-audit.mjs)。

这些临时文件本轮保留，未清理；若未来丢失、源文件变化或新增日期需要纳入，必须重新只读刷新并审定范围，不能用本文计数或旧摘要直接批准发布。不会把临时证据目录转成日常读取依赖。S2 需由届时实现的工具生成正式候选和不可原地改写的 plan，并再次核对身份。

## 8. 交付边界与下一步

本轮修改仅为本清单、技术方案/LLD、主索引及原 TODO 三份文档的状态同步；保留工作区原有文档改动。未改业务代码、CSV、14 条时段修正、正式数据或 staging，未写 Dagster 状态、重载/停启服务、删除、提交或推送。

使用 CodeGraph `codegraph_explore` 核查 CSV/覆盖规则、正式路径和生成链入口，再以当前源码、文件及运行状态交叉确认；不是凭图的零引用判定可删。子系统边界及依赖矩阵无变化。

交付验证：`scripts/check_docs_integrity.py` 通过；技术方案、LLD、本清单共 41 个本地链接及显式锚点有效；三份文档代码围栏、全篇空白及已跟踪差异检查通过；逐文件清单和展开报告的 SHA-256 再次核验一致。工作区差异仅为上述七份文档（含此前未提交的文档工作），没有业务代码差异。未运行业务回归测试，不声称新实现已验收。

下一步仍为 **S1**：先明确当前工作区的本地维护安排，再按 LLD 实现固定合同/路径/纯合并和隔离 Dagster 验证。本清单没有产生新的业务范围选择，也不自动授予 S1、staging 写入、正式发布、事件登记或最终删除权限。
