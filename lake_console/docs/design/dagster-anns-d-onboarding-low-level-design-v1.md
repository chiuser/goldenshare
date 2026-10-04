# 上市公司公告接入 DG 代码级 LLD v1

状态：设计完成，待开发。日期：2026-10-04。业务决策已获用户确认；本文的拟新增文件、配置、命令及验收项均未实现，不是可直接执行的生产 runbook。

对应 [技术方案](dagster-anns-d-onboarding-plan-v1.md)，共同使用 R01–R12。采用 [接入模板](../templates/dagster-dataset-onboarding-template.html) 的身份、字段矩阵、§7A、预算、检查、写入与验收要求；未测性能必须在 P0 补齐。

## 1. 三层时间语义与范围

| 层次 | 合同 |
|---|---|
| 时间输入 | ISO 日期点或闭区间；起点 2020-01-01；按 Asia/Shanghai 判定已结束自然日；首期拒绝今天及未来日期 |
| 执行 unit | Tushare 按单日分页；bootstrap 按月读取、按日提交；分页单位不是分区 |
| freshness/audit | 检查预期日期是否有完整更新证据及有效文件；零行是合法值，不要求每日有公告；七日刷新不证明源端永不迟到 |

分区使用专属 `DailyPartitionsDefinition(start_date="2020-01-01", timezone="Asia/Shanghai")`。不依赖股票/指数交易日，不注册共享动态分区。源时间 ann_date 和 rec_time 独立；发布时间可能跨日，不能据其替代公告日期。

Bootstrap 固定 2020-01-01..2026-09-30。首次接线后按相同日更新实现补 2026-10-01..启用前一天；若范围为空则不创建工作。正式 schedule 启用前必须对账此区间，不能只跑七天。

## 2. 拟新增模块和接线点

路径相对于 `lake_console/orchestrator/src/orchestrator/`；实施前再次核对当前分拆规则，保持一个职责一个模块，不写通用万能入口。

| 模块 | 职责 |
|---|---|
| `defs/anns_d_contract.py` | 六字段/schema、日期输入、全字段身份与源类型验证 |
| `defs/prod_db/anns_d.py` | 批准白名单、只读 SQL、月服务端游标、有限 preflight |
| `defs/anns_d_source.py` | 显式六字段 Tushare 分页、有界调用、限流/配额/取消 |
| `defs/anns_d_io.py` | 页 Parquet、DuckDB UNION DISTINCT、候选检查与原子提升 |
| `defs/bootstrap/anns_d_history.py` / `anns_d_history_cli.py` | plan/capture/build/audit/promote；独立事件补录入口不混入每日链 |
| `defs/anns_d_checkpoint.py` | 原子 run-scoped checkpoint、指纹恢复、并发锁；不新增永久状态表 |
| `defs/assets/anns_d.py` | 薄 asset，调用日执行器并返回交付 metadata |
| `defs/checks/anns_d_checks.py` | 分区一致的文件合同和交付对账 checks |
| `defs/jobs/anns_d.py`、`defs/schedules/anns_d.py` | 日 job、08:00 七日请求计划和共享窗口预算 |
| `defs/run_contracts/anns_d.py` | 唯一公告执行 policy/run config，集中默认值及校验 |
| 现有 `paths.py`、`catalog/lake_assets.py`、schema 合同与 `definitions.py` | 增加本 asset/path/schema/definitions，不改变其它资产行为 |

测试在 orchestrator/tests 下，按 contract/source/bootstrap/io/checks/schedule 分组。后续名称须与现有工程规则核对，禁止据拟定文件名推断已接线。

不 import Prod DatasetDefinition/DAO/TaskRun；Prod 表通过 resource 和受控 SQL 读取。现有只读资源可复用，交易日校验、非空代码、通用全量 DataFrame helper 不可复用。

## 3. 逐字段合同（模板 §7A）

| 源字段 | Tushare 输入值 | Prod bootstrap 来源 | Raw 物理类型/可空 | 转换、消费者 |
|---|---|---|---|---|
| ann_date | YYYYMMDD 字符串 | 原始 JSON 的 ann_date | VARCHAR / yes | 原值；解析仅用于检查目录一致，不写回；日期查询 |
| ts_code | 字符串或 NULL | 原始 JSON 的 ts_code | VARCHAR / yes | 不 trim/不股票池过滤；代码查询 |
| name | 字符串或 NULL | 原始 JSON 的 name | VARCHAR / yes | 原值；未来名称查询 |
| title | 字符串或 NULL | 原始 JSON 的 title | VARCHAR / yes | 原值；未来文件命名由下载层负责 |
| url | 字符串或 NULL | 原始 JSON 的 url | VARCHAR / yes | 原值；未来下载层校验与跳过 |
| rec_time | 无时区文本或 NULL | 原始 JSON 的 rec_time | VARCHAR / yes | 不转 TIMESTAMP；查询展示，不能用于分区 |

固定顺序即上表顺序。日期 schema 可空不等于允许把无法归属请求日期的记录无声归档；此类异常阻断整个候选并保存证据，不丢弃行。其余缺值均保留，不强制代码匹配股票正则；例如 155162.SH 债券公告仍属于源全集。

不写 id、row_key_hash、group_key、api_name、fetched_at、raw_payload、source、created_at、updated_at、下载状态或文件 SHA。内部执行数据可以另带 cursor/checksum，但最终 COPY 必须仅投影六字段。

### 3.1 完全重复语义

相等指六字段逐个值相等，NULL 等于 NULL，NULL 不等于空字符串；保留空白、大小写及字符原值。DuckDB DISTINCT 的 NULL 语义符合重复消除需求；不得先归一化再 DISTINCT。

构建使用显式六列：`SELECT DISTINCT <six columns> FROM (existing UNION ALL new_pages)`；不依赖 hash 作为唯一判定，不按 URL 或三元组去重。两条相同代码/标题而 URL 不同（包括 NULL）必须同时存在。这是用户最终简化规则，早先“有 URL 覆盖无 URL”的方案不适用。

元数据保留六字段版本；下载器可以让多条元数据关联同一 PDF，这是后续合同，不在 Raw 中合并行。

## 4. 来源合同与 SQL

### 4.1 Prod 只读白名单

唯一业务表 `raw_tushare.anns_d`。允许在服务器内部读取 raw_payload 并提取六个批准业务值；完整 raw_payload 禁止输出。id 和类型化 ann_date 只作为排序、范围、恢复及月计划过滤，id 可以进入内部 staging cursor，不进入 Raw。禁止其它业务列、Ops 表、任意表名/SQL 透传和 Prod 写入。

月起止和上界 id 绑定参数；只读属性在业务 SQL 前建立，优先 `ProdPostgresResource.connect_readonly_transaction()`。月内使用 repeatable read 只读快照，不与全历史共享事务。读取结束 rollback/close。

拟定受控投影（语法需 P0 实际 EXPLAIN/类型核验，不是当前已实现 helper）：

```sql
SELECT id,
       raw_payload::jsonb -> 'ann_date' AS ann_date,
       raw_payload::jsonb -> 'ts_code' AS ts_code,
       raw_payload::jsonb -> 'name' AS name,
       raw_payload::jsonb -> 'title' AS title,
       raw_payload::jsonb -> 'url' AS url,
       raw_payload::jsonb -> 'rec_time' AS rec_time
FROM raw_tushare.anns_d
WHERE ann_date >= %(month_start)s AND ann_date < %(month_end)s
  AND id <= %(upper_id)s
ORDER BY id;
```

使用 JSON 值投影而非随意 `::text`，驱动得到原始字符串或 NULL；字符串以外类型、缺少声明字段、非法 JSON、源 ann_date 和类型化 ann_date 不一致必须显式识别。缺键与显式 NULL 的检查在服务器端 bounded 校验中进行，不靠 `->` 返回 NULL 判断键存在。禁止把异常数字转换成字符串后宣称源镜像。

EXPLAIN 检查月日期过滤索引、id 排序及 JSON 解析成本。81 月直接路径若重复全表扫描或排序代价不可接受，P0 停止并修订源读取计划，不能硬跑，也不擅改 Prod 索引。

月事务内以服务端游标 fetchmany=10,000；每批转换六字段列式批次并写 staging shard。Python 不累积月全集。中途退出未完成月份从头重新 capture（新 attempt 目录），不把新快照拼到旧 capture 中；已完成月候选和已提升文件可复用。capture cursor 是证据，不承诺跨事务恢复旧快照。

计划冻结每月边界、upper_id、范围计数/六字段统计、目标冲突、合同版本。月 capture 必须在同快照获得计数并读回对账；全历史不宣称统一时间快照。发现源 schema 或月份统计异常停止，不扩大白名单。执行期避免同范围 Prod 重置/重放，最终再做有界汇总核验。

### 4.2 Tushare

专用 builder 只生成 `anns_d(ann_date=YYYYMMDD, fields=<six>, limit=2000, offset=<cursor>)`。历史范围先展开日期，不能把大区间一次请求后认为完成；不传 ts_code/title，避免源全集被过滤。

字段实测见方案 §2.1；MCP 描述上限与源文档差异已记录。MCP 高 offset 能力有限，不作为生产分页上限。SDK 返回列必须明确包含六字段；合法零行页仍须有 schema。异常无字段响应、类型错误、非成功请求均失败，不能作为空日。

每页先检查取消/配额，调用后再检查取消；原始页完整写入与 checkpoint 原子记录后才推进 offset。短页结束，满页继续；终止证据保存末页 offset、长度和累计页数。推进量为实际行数。超过单日请求预算、重复页导致无进展或截止时间时失败，不提升截断结果。

调用必须有 30 秒硬截止和可取消控制：公告专用 adapter 使用可终止调用进程，每 ≤1 秒观察取消，取消最多 5 秒释放调用；子进程只调用现有资源，不输出 token。API 失败最多三次尝试，同一页重试不推进 cursor。实现前核验现有 SDK 与进程生命周期，隔离测试证明子进程不遗留；不擅改共享 TushareResource 行为。

请求结束至下次请求至少 5 秒，退避/服务端限流要求只能增加等待；重试也计入预算。日进程重启重新 capture 当日，避免 offset 动态变化时混合旧页；已提交其它日期不重做，已完整 capture 可按指纹继续 build/promote。

## 5. 配置审计

新增默认值集中到拟定 `defs/run_contracts/anns_d.py` 的 policy 与 Dagster schema；本表是设计合同，不证明配置已部署。运营覆盖仅从已声明 job/CLI 参数进入，不散落 env、页面和脚本。

| 配置/常量 | 默认 | 来源/持久化 | 消费者、依赖与生效 |
|---|---|---|---|
| start_date/end_date | 手工必填；bootstrap 固定范围 | CLI/job config，run checkpoint | planner，闭区间校验；每 run 冻结 |
| refresh_days | 7 | policy，schedule 使用冻结值 | schedule 请求计划；范围 D-7..D-1 |
| schedule_time/timezone | 08:00 / Asia/Shanghai | schedule 定义，STOPPED；不加第二套 env | 请求计划与自然日判断；重载生效 |
| page_size | 2000 | 合同常量，不提供任意增大入口 | builder；末页/满页测试 |
| prod_fetch_rows | 10000 | policy，run 记录 | capture；只影响 fetch 缓冲 |
| interval_seconds | 5 | job/CLI config、run 记录 | API limiter；必须有限且≥0，debug 可调 |
| max_attempts/call_timeout/cancel_grace | 3 / 30s / 5s | policy | adapter；请求预算含重试 |
| max_day_requests/max_window_requests | 100 / 350 | policy，window 运行意图及共享预算 checkpoint | 日执行器/调度；窗口日期 run 不各自重置350 |
| max_window_seconds | 3600 | policy，窗口起止记录 | scheduler/admission；超时停止新日期领取 |
| max_month_rows/month_deadline/sql_timeout | 200万 / 1800s / 60s | policy | Prod capture；不把 SQL timeout 当整月时限 |
| duckdb_memory/threads/spill_limit | 2GB / 2 / 20GB | 专用连接设置，run 记录 | writer/check；不得修改其它资产全局默认16GB等 |
| min_free_reserve | 5GiB | policy | volume/space gate，额外加输出预测与spill预算 |
| root/staging | 正式路径固定，见方案 | 现行 paths 与专用 path helper | 所有读写；禁止旧路径/env fallback |
| TUSHARE_TOKEN、ProdPostgresResource 既有连接 env | 复用既有来源，不新增默认秘密 | 现有环境资源，不复制到 checkpoint | API/只读 source；run 日志脱敏 |

仅暴露日期和请求间隔；其它预算调整须更新合同与实测，不自动变成前端输入项。所有生效配置以非敏感值出现在计划/运行摘要，schedule 停启状态在 Dagster 可见。

七个日期 run 共享窗口配额必须跨进程同步：run-scoped window checkpoint 保存领用请求数、截止时间与请求未决标志，文件锁保护原子领用；超时/退出的未决请求按已消耗计，避免少计。它只约束这一次窗口意图，不计算数据 readiness，不是持久公告状态表。手工补拉以新窗口 id 执行；bootstrap 不消耗 Tushare 配额。

P0 需核验配置与当前 project concurrency、DuckDBResource、schedule 装配及所有消费者；若以上 defaults 不能在预算内完成，先落回两份文档，不在代码静默降级。

## 6. 文件状态机与事务边界

`PLANNED → CAPTURING → CAPTURED → BUILT → VALIDATED → PROMOTED → EVENTS_REPORTED`，任一步可 CANCELLED/FAILED。状态只描述执行，不是独立业务事实。

1. 创建 run-scoped staging 前检查卷真实挂载、UUID/路径、写权限、空闲空间、root/staging 同文件系统及目标冲突；正式执行前授权。磁盘缺失不得创建假 /Volumes 目录。
2. 逐页写独立 Parquet 临时文件，fsync、原子改名，再写包含页范围/行数/指纹的 checkpoint；中断后仅接纳校验成功的页。无有效末页证据不能 build。
3. Bootstrap 月页用 DuckDB 显式投影六列、DISTINCT、按 ann_date 写每日候选；83 个历史空日的文件需单独生成正确 schema。日更新读取该日已有文件和新页合并，不用 Python 逐行大表写入。
4. build/audit 的 DuckDB 配置限制内存和 spill 到 run-scoped staging，长查询采用独立有界执行和取消中断，≤30 秒更新可见阶段。执行预算包括写前、写后和 checks，不只测 API。
5. VALIDATED 保存来源页计数/尾页、输入与重复计数、目标行数、schema、文件 SHA 和已有文件基线；源页原始字符串不改变，未知额外源字段阻断契约漂移。
6. 同日文件锁保护基线核验与 promote；已有文件发生变化停止重建。锁只是协调，不是公告状态。目标必须是普通安全文件，不通过符号链接写盘。
7. 同文件系统 `os.replace(candidate, final)`、fsync 父目录后记录 PROMOTED。逐日事务，不声称月份/全范围整体原子性。窗口内已成功日不回滚。
8. 若 rename 成功而 checkpoint 或 event 失败，恢复读取文件 SHA 与已冻结候选证据；相符补记/补报，不重新请求源或覆盖文件；不符停止人工审计。
9. 如果 cancelled/failed，已提交文件保留，未提升 candidate 和异常页保留。禁止自动清 staging、备份或 Kopia。

新增 checkpoint 的理由：event 无法证明页已落盘和 rename 前后位置；Parquet 无法保存执行 cursor/共享请求配额；隔离测试不能替代中断持久化；已有其它数据集 checkpoint 语义不能直接复用。故仅使用 run-scoped 执行证据，不建永久 manifest/readiness 表或 summary asset。

## 7. Checks、交付数量与观测

### 7.1 文件合同 check

文件存在及路径合法；hive_partitioning=false 时物理列顺序/类型符合六 VARCHAR；零行允许；所有非空日期等于目录日期，空/错日期是分区合同错误；六字段重复组为零；缺 URL/rec_time/code/title 不因非空键规则拒绝。

这是文件自身检查，不重做源请求或重算其它业务资产。asset/check 都绑定同一个日 partitions_def，测试同时断言定义属性、AssetCheckEvaluation.partition 和隔离 instance 的持久事件分区。

### 7.2 交付对账 check

本轮原始页数/尾页已完成，页行数合计一致；`目标集合 = DISTINCT(已有集合 UNION 源集合)`。bootstrap 目标等于源六字段去重集合。记录：source_rows、existing_rows、duplicate_rows、new_unique_rows、written_rows、readback_rows、missing_url、missing_rec_time、rejected_rows。非完全重复过滤数必须为零。

用 DuckDB 对当日已有/源/candidate 做集合差与聚合，证明已有记录未丢、新唯一记录未漏；不要只比 count。checks 不再依赖远程 Prod/Tushare，可使用 run-scoped交付证据及 materialization metadata 引用指纹。证据丢失时不能猜绿色，失败并提示重新形成可验证证据；此情况不自动删除正式文件。

合法零行页的失败/成功 schema 必须区分；空日交付需要完整末页证据，不能靠零行 Parquet 自证源查询成功。

### 7.3 观测与事件独立

结构化进度字段：run/window id、phase、month/date、offset、page_count、rows_captured、days_completed、days_total、requests_used/budget、last_business_progress_at、updated_at、cancelled/reason。源总数未知时不显示行百分比；日期完成百分比可展示，ETA 暂无法估算。

业务 commit 与 Dagster 状态分开。事件失败可能使 run 不成功，但已提交文件有效；恢复按物理事实补报。bootstrap runless 事件包含文件 SHA、schema版本、源计数及 green check；先 plan 数量/已存在事件，再批准样本和全量补报。同文件 SHA/事件身份重放不重复灌事件。

## 8. 调度与手工执行合同

一个日 asset/job，定时 schedule 生成七个有 partition_key 的 RunRequest，run_key=`anns_d:<scheduled_local_date>:<target_date>`。目标日期按先旧后新提交；队列执行顺序不能仅靠发出顺序保证，必要时按窗口 admission 队列串行领取。日及 bootstrap 锁保证同分区唯一 writer；工作窗口源调用并发默认1。

schedule 默认 STOPPED，启用需批准；cron 为每日08:00，明确 Asia/Shanghai。不同日 tick 的七日窗口允许重新更新相同目标日期；同 tick 不重复提交。window 截止后未完成日期在失败摘要可见，手工补拉，不把任务标成功。

拟历史 CLI 子命令 plan/capture/build/audit/promote/report-events，各阶段接受已验证计划身份；默认只读 plan，不把单一 `--apply` 混合文件与事件。拟日补拉入口接受闭区间、间隔，拆日期，支持失败日期重试与物理续跑，不接受 SQL、table 或任意根路径。

本文件没有发布可执行命令，P1/P2 形成真实 help 后再补 runbook，禁止按拟命令直接操作正式环境。

## 9. P0 性能测量和成本对账

在实现业务写入前填入以下证据；设计文档完成不能替代本门禁。

| 必须补测 | 方法、上限与退出要求 |
|---|---|
| 当前 Prod 范围/月份 | 有界日期聚合最多81月/2465日，缺日期/非法源字段服务器内统计；不导出完整payload |
| 查询执行计划 | 首/中/末月 EXPLAIN，不默认 EXPLAIN ANALYZE 全月；记录索引、扫描、排序、SQL时间与连接数 |
| 类型保真 | 每年最多100条六字段样本及已知缺URL/rec_time样本，确认JSON键/字符串/NULL；抽查不等于全表证明 |
| 单批内存/Parquet压缩 | 限定最多10,000条业务字段，只在 /private/tmp 写隔离候选；RSS、源字节、Parquet大小、耗时、schema/集合一致 |
| 源空页/SDK截止 | 真实空日和2000满页/尾页；有界真实adapter调用，SDK schema及取消测试；不写正式Lake |
| 历史文件/时间/空间 | 用各年分布与代表性批次外推，列最坏余量与误差；按正式+candidate+shards+spill+5GiB reserve测空间 |
| 七日稳态与峰值 | 峰值按历史35页/日预算；最大约245页加重试计数，测单日writer/check耗时，外推7日是否≤60min/350请求 |

预计正式文件2,465，源读取81个主要连接；实际 fetch/SQL次数必须测量，不把12,064,049/10,000向上取整当真实fetch总数。日期写 partition 与读取 unit 不同；小文件成本按日期/代码查询和维护频率评估，不套固定MB阈值。

超预算、未知类型、目标冲突、磁盘不足时 fail closed，保留证据；禁止缩小股票池、减少fields、截止未完成分页或把未读数据算完成。P0 若不能闭合成本先修订本方案，不进入P1。

## 10. 约束—代码—测试—真实验收矩阵

| 约束 | 拟实现点 | 正向/负向测试 | 最小真实验收 |
|---|---|---|---|
| R01/R02 | contract、六列COPY、Prod projection | 六字符串/NULL保真；系统字段、类型漂移、trim反例 | 六字段源/Prod样本与文件schema |
| R03 | DISTINCT、集合审计 | 完全重复丢弃；URL NULL/非NULL、空白、rec_time不同、同标题保留 | 155162.SH两条版本均在目标 |
| R04/R06 | natural-day planner/check | 周末/空日成功；股票池过滤禁止；缺URL/rec_time合法；错日期阻断 | 合法空日+债券样本 |
| R05 | readonly source、Tushare builder | SQL白名单/绑定/只读先行；禁止Ops/任意SQL/Prod fallback | 源连接/SQL/只读事务证据 |
| R07 | source/capture/shards | 多批不累积；满页续取/短页停；异常无schema失败 | 峰值日分页、fetch内存/请求数量 |
| R08 | checkpoint/io/lock | 各边界崩溃、取消、基线竞争、磁盘失效；禁止半写正式文件 | 批准样本运行—取消—续跑—读回 |
| R09 | schedule/window/bridge | D-7..D-1、跨月/年、7日去重tick；bootstrap衔接及长停机缺口 | 衔接范围和七日请求计划 |
| R10 | event reporting | rename后event失败不回滚；补报幂等、终态一致 | 已提交文件SHA不变+事件补报 |
| R11/R12 | scope/plan/entrypoints | 默认STOPPED、plan零写入、无Silver/Gold/永久状态表 | definitions及正式只读审计 |
| 配置/预算 | policy/window/admission | 区间反转/非有限间隔、请求共享耗尽、timeout、子进程退出、进度单调 | 配额/最长无更新间隔/ETA证据 |

测试必须有真正反例，不仅复述实现。失败与取消后日 run 的活动步骤进入一致终态；物理文件已提交不能因观测状态失败删除或回滚。

## 11. 验收顺序、授权及遗留风险

P0只读核验与 /private/tmp 基准 → P1隔离开发验收 → P2 definitions/partition/check事件测试 → P3获批样本与全量文件 → P4获批事件补录、衔接补拉、日任务验收及调度启用。正式样本、全量文件、事件、调度分别留下批准与对账证据。

本轮只完成两份设计文档和索引；没有新增资产、resource、checks、schedule，未触发Prod/Lake写入。动态 definitions、性能测量和最小真实写入尚未完成，不能声称可投入运行。

CodeGraph query/impact与当前实现核对覆盖入口、TushareResource、Prod只读源、通用分页、路径、catalog和现有下载器消费链。共享资源其它消费者不随本专项改行为；未来前端和下载器合同尚未迁移。当前技术风险为源offset分页可变、7天之外迟到、Prod JSON解析/排序成本、磁盘容量，以及跨月源变化；按本文实测与阻断处理，不引入双轨兜底。
