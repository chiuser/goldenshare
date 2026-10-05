# 上市公司公告接入 DG 代码级 LLD v1

状态：历史文件与全量事件已完成；P4衔接补拉/日常验收/启用待阶段授权。日期：2026-10-05；最新状态见§23。

对应 [技术方案](dagster-anns-d-onboarding-plan-v1.md)，共同使用 R01–R12。采用 [接入模板](../templates/dagster-dataset-onboarding-template.html) 的身份、字段矩阵、§7A、预算、检查、写入与验收要求；未测性能必须在 P0 补齐。

## 1. 三层时间语义与范围

| 层次 | 合同 |
|---|---|
| 时间输入 | ISO 日期点或闭区间；起点 2020-01-01；按 Asia/Shanghai 判定已结束自然日；首期拒绝今天及未来日期 |
| 执行 unit | Tushare 按单日分页；bootstrap 按月读取、按日提交；分页单位不是分区 |
| freshness/audit | 检查预期日期是否有完整更新证据及有效文件；零行是合法值，不要求每日有公告；七日刷新不证明源端永不迟到 |

分区使用专属 `DailyPartitionsDefinition(start_date="2020-01-01", timezone="Asia/Shanghai")`。不依赖股票/指数交易日，不注册共享动态分区。源时间 ann_date 和 rec_time 独立；发布时间可能跨日，不能据其替代公告日期。

Bootstrap 固定 2020-01-01..2026-09-30。首次接线后按相同日更新实现补 2026-10-01..启用前一天；若范围为空则不创建工作。正式 schedule 启用前必须对账此区间，不能只跑七天。

## 2. 模块和接线点（实现状态见§13）

路径相对于 `lake_console/orchestrator/src/orchestrator/`；实施前再次核对当前分拆规则，保持一个职责一个模块，不写通用万能入口。

| 模块 | 职责 |
|---|---|
| `defs/anns_d_contract.py` | 六字段/schema、日期输入、全字段身份与源类型验证 |
| `defs/prod_db/anns_d.py` | 批准白名单、只读 SQL、月服务端游标、有限 preflight |
| `defs/anns_d_source.py` | 显式六字段 Tushare 分页、有界调用、限流/配额/取消 |
| `defs/anns_d_io.py` | 页 Parquet、DuckDB UNION DISTINCT、候选检查与原子提升 |
| `defs/bootstrap/anns_d_history.py` / `anns_d_history_cli.py` | plan/capture/build/audit/promote；独立事件补录入口不混入每日链 |
| `defs/anns_d_execution.py` | 日执行器、提交证据复核、取消与续跑 |
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

月起止和上界 id 绑定参数；只读属性在业务 SQL 前建立，优先 `ProdPostgresResource.connect_readonly_transaction()`。月内使用 repeatable read 只读快照，设置 cursor_tuple_fraction=1.0，不与全历史共享事务。读取结束 rollback/close。

已实现的六业务字段投影如下；真实 helper 另返回类型化分区日期和 keys_present 校验标记，不进入 Raw：

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
ORDER BY ann_date, id;
```

使用 JSON 值投影而非随意 `::text`，驱动得到原始字符串或 NULL；字符串以外类型、缺少声明字段、非法 JSON、源 ann_date 和类型化 ann_date 不一致必须显式识别。缺键与显式 NULL 的检查在服务器端逐批有界校验中进行，源 helper 可显式回传仅用于校验的 keys_present 布尔值（不进入 Raw），不靠 `->` 返回 NULL 判断键存在。禁止把异常数字转换成字符串后宣称源镜像。

EXPLAIN 检查月日期过滤索引、ann_date/id 排序及 JSON 解析成本。P0实测旧ORDER BY id LIMIT会扫描约838万无关记录，禁止沿用；改用日期前导稳定排序，测试必须断言该排序。81 月直接路径若重复全表扫描或排序代价不可接受，P0 停止并修订源读取计划，不能硬跑，也不擅改 Prod 索引。

月事务内以服务端游标 fetchmany=10,000；每批转换六字段列式批次并写 staging shard。Python 不累积月全集。中途退出未完成月份从头重新 capture（新 attempt 目录），不把新快照拼到旧 capture 中；已完成月候选和已提升文件可复用。capture cursor 是证据，不承诺跨事务恢复旧快照。

计划冻结每月边界、upper_id、范围计数/六字段统计、目标冲突、合同版本。月 capture 必须在同快照获得计数并读回对账；全历史不宣称统一时间快照。发现源 schema 或月份统计异常停止，不扩大白名单。执行期避免同范围 Prod 重置/重放，最终再做有界汇总核验。

### 4.2 Tushare

专用 builder 只生成 `anns_d(ann_date=YYYYMMDD, fields=<six>, limit=2000, offset=<cursor>)`。历史范围先展开日期，不能把大区间一次请求后认为完成；不传 ts_code/title，避免源全集被过滤。

SDK值规范：只将pandas表示的缺失值（已实测url为float NaN）还原为None，保留空字符串/空白；非缺失float、数值、对象仍阻断。该步骤是传输层缺失值还原，不是源字段填补；必须用SDK样本和NULL/空字符串反例测试。

字段实测见方案 §2.1；MCP 描述上限与源文档差异已记录。MCP 高 offset 能力有限，不作为生产分页上限。SDK 返回列必须明确包含六字段；合法零行页仍须有 schema。异常无字段响应、类型错误、非成功请求均失败，不能作为空日。

每页先检查取消/配额，调用后再检查取消；原始页完整写入与 checkpoint 原子记录后才推进 offset。短页结束，满页继续；终止证据保存末页 offset、长度和累计页数。推进量为实际行数。超过单日请求预算、重复页导致无进展或截止时间时失败，不提升截断结果。

调用必须有 30 秒硬截止和可取消控制：公告专用 adapter 使用可终止调用进程，每 ≤1 秒观察取消，取消最多 5 秒释放调用；子进程只调用现有资源，不输出 token。API 失败最多三次尝试，同一页重试不推进 cursor。实现前核验现有 SDK 与进程生命周期，隔离测试证明子进程不遗留；不擅改共享 TushareResource 行为。

请求结束至下次请求至少 5 秒，退避/服务端限流要求只能增加等待；重试也计入预算。日进程重启重新 capture 当日，避免 offset 动态变化时混合旧页；已提交其它日期不重做，已完整 capture 可按指纹继续 build/promote。

## 5. 配置审计

执行默认值已集中到 `defs/run_contracts/anns_d.py` 的 AnnouncementPolicy；Dagster schema、refresh_days 与 schedule 定义待 P2 接线。本表是设计合同，不证明配置已部署。运营覆盖仅从已声明 job/CLI 参数进入，不散落 env、页面和脚本。

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

设计轮完成两份文档和索引；随后P0已完成只读核验及临时基准，见§12；没有新增资产、resource、checks、schedule，未触发Prod/Lake写入。动态 definitions、完整月性能及最小真实写入尚未完成，不能声称可投入运行。

CodeGraph query/impact与当前实现核对覆盖入口、TushareResource、Prod只读源、通用分页、路径、catalog和现有下载器消费链。共享资源其它消费者不随本专项改行为；未来前端和下载器合同尚未迁移。当前技术风险为源offset分页可变、7天之外迟到、Prod JSON解析/排序成本、磁盘容量，以及跨月源变化；按本文实测与阻断处理，不引入双轨兜底。

## 12. P0 验收结论与 P1 入口

2026-10-04：[报告](../../reports/anns_d_dg_p0_20261004.md)、[结构化证据](../../reports/anns_d_dg_p0_20261004.json)。P0通过，P1未开始。源合同、范围、六字段镜像、读取计划、执行配置及初始空间/耗时预算已核验；正式写入门禁继续有效。

- 月读取修订为ORDER BY ann_date,id；峰值月有界10,000行EXPLAIN ANALYZE约0.222秒，服务端游标MOVE约0.236秒。MOVE不包含网络传输/客户端反序列化，不代替全月计时。
- 年度700条服务器内字段检查：缺键0、错误类型0、额外键0；单批10,000条临时Parquet读回集合差0。抽样不证明全表，因此P1每批仍验证源JSON键/类型。
- SDK空日0行但六字段齐全；尾页257行；已知两条记录url分别NaN/字符串，rec_time均None。SDK socket timeout=30秒已查现有代码，但可终止进程及取消5秒上限必须在P1测试，不写为已实现。
- DuckDB专用2GB/2线程/20GB spill配置可用于隔离连接，不改共享16GB默认；本机未安装pyarrow，P1优先使用现有DuckDB按批JSON/CSV列式读写，不安装依赖。
- 根环境所需秘密配置均存在（只核验布尔值）；正式instance并发1、路径同文件系统、剩余空间约2.67TiB。资源连通性已通过SSH和SDK核验，未实连ProdPostgresResource；P1须检验其只读属性/隔离级别，不能把SSH成功等同resource验收。
- P3执行规划15–60分钟、保守空间35GiB；样本不足以证明全月峰值RSS或全量时限，P3先样本校准。原计划81源月/2,465日不变，预算耗尽和类型异常仍fail closed。

## 13. P1 实现与计划对账（2026-10-04）

[验收报告](../../reports/anns_d_dg_p1_20261004.md)、[结构化证据](../../reports/anns_d_dg_p1_20261004.json)。P1 核心完成，P2 接线未开始。§12保留P0时点的历史结论，以本节作为最新状态。

| 硬口径 | 当前实现、测试与证据 |
|---|---|
| R01/R02 六字段与源值 | anns_d_contract / anns_d_io；固定六 VARCHAR，SDK 缺失值还原 NULL；类型、空白、空字符串、额外列反例测试。真实 SDK 空日六列、两条缺值样本通过 |
| R03 完全重复 | 显式六列 DISTINCT；NULL 与空字符串分别保留，URL/rec_time 不同版本保留；io 测试包含 155162.SH 样本及幂等重放 |
| R04/R06 自然日及异常 | 专用日期合同、raw_anns_d_path；空日生成六列文件，无股票池过滤；日期/schema/类型错误阻断并留 staging 证据 |
| R05 Prod 只读、每日直连源 | prod_db/anns_d 月服务端游标及 anns_d_source；测试 SQL/事务顺序、批次上限、闭合计数；真实资源 transaction_read_only=on、10,000 行读取，未写 Prod |
| R07 有界内存与分页 | fetchmany=10,000；源单页2,000，逐页持久化；月份在专用 DuckDB 内一次物化，按日构建，不重复扫描全部月页；2GB/2线程/20GB spill，预算与超时测试通过 |
| R08 取消与恢复 | checkpoint / io / execution / bootstrap；锁、指纹、基线比较、原子改名、逐文件恢复；进程退出、阻塞调用取消、页篡改、磁盘不足、writer 冲突测试通过 |
| R09 七日和衔接补拉 | 核心支持已结束自然日/闭区间及共享窗口预算；七日 planner、首次衔接范围和调度接线待 P2，正式补拉待 P4 |
| R10 业务提交独立 | emit 失败后文件仍保留，checkpoint 落盘失败可核验文件续跑；正式 Dagster 事件补报接线及验收待 P2/P4 |
| R11 阶段门禁 | 没有资产/job/schedule/正式 checks 注册，没有正式 Lake 或事件写入；仅 /private/tmp 隔离文件和只读请求 |
| R12 不新增正式状态事实 | 仅 run-scoped 文件 checkpoint 与窗口预算，不新增数据库、摘要 asset 或 freshness 投影；boundaries 测试核验核心不注册 Dagster 定义、不依赖 Prod Ops |

源 capture 完成才可构建候选。完整源页须有大小/SHA 指纹、行数和结束证据；提升前再次验证。Prod keys_present 同时检查六键齐全和没有额外键。错误行仅保存内部 id、分区日期、六字段及 reason code 到 run-scoped staging，不输出完整 raw_payload，不静默跳过。

P1 使用 codegraph query/impact 分析 ProdPostgresResource、TushareResource、DuckDB 连接及路径调用链，并 sync/status 核验索引；新增 raw_anns_d_path 消费者仅公告 Store 和路径测试。没有修改共享资源行为、业务子系统依赖矩阵或下载器消费者。P2 尚须核验 definitions/catalog/checks/schedule 消费者和实际运行 metadata。

自动化结果：公告及资源测试82项通过（公告新增67项、既有资源15项），受保护 DuckDB launcher 回归27项通过；4条既有 Dagster/Pydantic 弃用警告。两种真实进程退出路径均在隔离目录验证。只读验收不是完整月份吞吐测试，也不证明所有 Tushare 日期的全集覆盖。

执行配置由 AnnouncementPolicy 集中管理，持久窗口额度包含失败和重试，重启不退还未决请求；完整月/全量成本仍待正式阶段测量。

## 14. P2 接线执行约束

本轮沿用用户已批准的 P2 范围：资产 raw_tushare_anns_d，job raw_anns_d_update_job，schedule raw_anns_d_update_schedule；两个 blocking check 分别为 raw_tushare_anns_d_file_contract_check、raw_tushare_anns_d_delivery_reconciliation_check。catalog 登记专属 ann_date_partition_raw_anns_d，自然日从2020-01-01起，六 VARCHAR schema。不得增加股票池、交易日依赖、Silver/Gold 或永久状态表。

七日 schedule 只生成请求，不读写 Lake/instance；共享窗口身份、范围及起始时刻通过内部 run tags 传递，间隔通过资产 config 传递。按日期优先级排队，执行时 admission 核验更早日期已物理提交；乱序或并发领取失败关闭，不先请求源，不假定队列顺序等于执行顺序。窗口超时或前日未完成时明确失败，保留已完成日；运营可续跑同窗口或另建手工窗口。只在 run-scoped staging 保存 admission、预算与日 checkpoint。

仅运营日期范围和间隔开放为手工 CLI 参数；内部窗口/续跑身份不进入面向用户的页面。日补拉 CLI 默认 plan，run 必须显式选择，固定正式根目录，不能透传 SQL/表/根路径。历史文件与 runless 事件入口仍分阶段提供，不用日更新入口替代 bootstrap。

检查只读当日文件、当前 materialization 引用的 run-scoped 证据；不能借用其它分区或正在 materializing 的其它 run。缺证据、目标或源页指纹改变时红灯。正式 check 分区事件在隔离 instance 验证；默认 STOPPED、definitions/catalog/schema、七日跨月年、重复 tick、乱序/取消/预算、合法空日与缺值、观测失败后续跑均需正反测试。

性能沿用 P0/P1 预算：每 tick7日/7请求计划、350源请求/60分钟共享上限，checks仅单日文件和对应证据，不重拉源；schedule求值不得扫描任何数据文件。本轮全部执行测试位于临时目录及隔离instance，未获授权的正式 job、文件、事件、调度均不执行。

## 15. P2 实现与验收对账（2026-10-04）

[验收报告](../../reports/anns_d_dg_p2_20261004.md)、[结构化证据](../../reports/anns_d_dg_p2_20261004.json)。P1 已提交 aa08fbd0；本节是最新状态，§12/§13保留各阶段历史结论。

| 约束 | 实现与验收 |
|---|---|
| Raw-only、稳定schema/metadata | assets/anns_d.py、RAW_ANNS_D_SCHEMA、catalog/name_mapping与lake_assets；asset无上游交易日/股票池依赖；测试核验六VARCHAR、名称、路径、checks及分区模型 |
| 自然日分区事件 | anns_d_partitions.py；asset和两个check同一DailyPartitionsDefinition；隔离实际 materialize 的返回evaluation、持久化event和materialization均为2023-06-09；零行和缺值版本通过 |
| 七日08:00、默认停止、同tick去重 | schedules/anns_d.py；集中cron/timezone/refresh defaults；通用run key builder生成anns_d:<tick-date>:<target-date>，显式tags共享窗口；跨月年和重复tick测试通过；schedule只构造请求，不扫描文件或写预算 |
| 顺序、配额、截止与取消 | anns_d_window.py；执行锁+前日已提交核验，乱序不请求源；保持窗口已完成日；policy/range冻结、截止时间不能重启延长；取消终态、过期、危险窗口标签与非有限时间反例通过 |
| Checks不借证据、不重拉源 | checks/anns_d_checks.py；文件check独立检查物理合同，交付check读取同日当前materialization指向的checkpoint，核验run归属、源页/目标指纹、行数与结束证据；缺证据、错误身份、其它run、篡改和越界源页红灯 |
| 业务提交独立、续跑 | asset调用P1核心，物理交付先完成再返回MaterializeResult；同window/day使用稳定run目录，复用已经提交的证据。事件失败不删除文件；P1崩溃/观测失败回归继续通过 |
| 运营入口默认只读 | anns_d_cli.py；默认plan只输出日期/预算/窗口身份；不读秘密、不连接源、不建Store；run显式执行，固定Lake/staging；asset/check也拒绝共享resource覆盖正式Lake根，访问前阻断并有反例测试；interval有限且非负；plan零写入与危险输入测试通过 |

集中配置来源：AnnouncementRawConfig和CLI间隔默认引用AnnouncementPolicy；cron/timezone/refresh_days在run_contracts/anns_d.py定义。窗口内部tags为window_id/start_date/end_date/started_at，由schedule或CLI构造，不进入Raw；持久化仅windows/<id>/admission.json、budget.json及稳定日run目录的delivery.json，身份包含日期与policy。临时目录是执行证据，不作为freshness事实。

CLI例子（从orchestrator目录运行，当前仅plan可用于未批准阶段）：

```bash
.venv/bin/python -B -m orchestrator.defs.anns_d_cli plan --start-date 2026-10-01 --end-date 2026-10-03 --interval-seconds 5
```

默认省略plan效果相同。显式run会写正式Raw与staging，必须按阶段获得执行授权；需要TUSHARE_TOKEN。--window-id用于恢复同一窗口，日期和间隔不得改变。完成日可重复核验；过期窗口中的未完成日不能靠重启重置预算，须形成新的运营补拉意图。CLI不写Dagster事件，文件完成不代表正式事件已齐；历史CLI和runless补报入口继续在P3/P4完成，未发布伪命令。

124项自动化回归通过，包括P1核心、27项P2测试、既有资源/metadata/ETF catalog。隔离dg check defs通过，dg list defs确认asset/job/schedule/check被自动发现，无需改definitions.py装配。正式instance、Prod、Lake、事件、调度均未变更。源端真值沿用P0/P1只读证据，本轮没有新增真实源请求。

CodeGraph query/impact/sync/status与源码核验覆盖共享资源、definition metadata、路径、公告asset/check/window/job/schedule、catalog消费者和现有下载器。新增natural_date_partition不会进入仅支持trade_date的historical_materialization_reconciliation白名单；其余catalog条目及消费者语义未迁移。无子系统依赖矩阵变化，无下载器/前端改动。

风险：当前固定Dagster1.13.18的partitioned AssetCheckSpec有PreviewWarning，已通过真实隔离事件测试；升级时须重新验收。队列乱序不会越过前日，但会明确失败，运营须按窗口续跑；七天之外迟到仍需显式补拉。正式全月性能、运行—取消—续跑读回、事件补报和启用验收留待P3/P4。

## 16. P3 历史入口开发约束

沿用已批准的2020-01-01..2026-09-30范围，历史执行按完整自然月选择子范围，不改变公告字段或日更新入口。新增bootstrap/anns_d_history_plan.py、anns_d_history_execution.py、anns_d_history_audit.py和anns_d_history_cli.py；复用现有六字段source、Store、checkpoint，不引入长期状态实体。

plan仅用Prod只读日期/id/行数聚合和本地卷/目标指纹读取，报告写/private/tmp；不创建正式Lake/staging目录。计划冻结范围、每月上界id、逐日源行数、目标基线、policy、合同版本、成本及SHA身份。CLI只接受受控日期、计划身份、月份、阶段和报告路径，不透传SQL、表名或Lake根；capture/build/promote明确要求计划SHA。

数据阶段分开执行：capture按月快照及10,000条批次保存六字段；同快照行数必须等于计划。build逐日记录候选，取消后不丢已完成候选引用；audit用月级DuckDB集合差、物理schema/footer和路径日期校验，禁止只比较行数；promote只接纳同计划的绿色audit并复核指纹，逐日原子提交。已经提交日可续跑核验，目标冲突不覆盖、不备份、不删除。最终formal audit按月扫描正式文件，不对2,465日逐日打开大表查询。

预算沿用P0：81月、2,465自然日，约1,206万行；每月最多200万行、1800秒、SQL60秒、DuckDB2GB/2线程/20GB spill。计划空间门禁为至少35GiB且同文件系统，成本估算保留误差，不当作实测吞吐；执行按月记录实际耗时和行数。事件期望为2,465 materialization及4,930 check，但P3不写事件或启动调度。新增35GiB门禁为bootstrap固定预算，不增加env或运营可调参数；消费者仅历史plan/执行卷检查，随进程启动生效，并有磁盘不足反例。

隔离正反验收覆盖：默认plan不创建Lake/staging、计划篡改/越界/超预算、源数量变更、取消capture重启、候选逐日续跑、目标/页/候选变化、无绿色audit不能promote、中途提交后续跑幂等、月级集合差及最终formal audit。实际只读计划先落地，再列样本/全量的完整命令、卷路径、执行范围、取消与恢复方法；正式文件与事件批准分开记录。

## 17. P3 开发与计划对账（2026-10-04）

[验收和正式样本完整命令](../../reports/anns_d_dg_p3_20261004.md)、[结构化证据](../../reports/anns_d_dg_p3_20261004.json)。P3开发与只读计划完成，正式样本/全量尚未执行；本节是最新状态，§12–§15保留历史记录。

| 硬口径 | 代码与验证 |
|---|---|
| 默认plan、正式卷先验、固定范围/根 | history_cli/plan及prod_db.inventory；日期/count/id只读聚合，未创建Lake/staging；启动卷失败不打开Prod、越界/部分月/目标篡改反例 |
| 冻结逐日源量、上界id、基线、policy、SHA | history_plan；snapshot源计数不同阻断，报告不可覆盖；真实81月预检冻结12,064,049行/2,465日 |
| 单批1万、月200万/1800秒/SQL60秒 | P1源复用与HistoryControl；预算/超时正反测试；35GiB同卷门禁；每阶段实际耗时存checkpoint，完整月峰值资源待正式样本 |
| 六字段/完全重复/NULL | history_capture及Store；六VARCHAR、DISTINCT和源值不变；隔离测试重复3行变2行，NULL URL与有URL均保留，空日生成空文件 |
| 每日候选/提交可恢复 | build逐日checkpoint，promote独立child交付checkpoint；取消保留2日候选及2正式文件并恢复，重放指纹不变；child身份包含day/policy供P2check读取 |
| 审计不只比行数 | history_audit月级批量集合双向差、footer、文件名日期、前后指纹；同量错误内容及交换日期文件反例阻断 |
| 无绿色审计不可提升/不覆盖冲突 | history_execution冻结audit计划身份及文件SHA，提升前复核；无证明/目标冲突反例；原子提升复用P1 |
| 文件与事件隔离 | 边界测试覆盖全部历史模块，CLI无events；未访问正式instance或写Prod/事件/调度；正式样本与全量批准仍分开 |

156项回归及scoped Ruff/全目录致命检查通过；4条既有Pydantic及1条分区check预览警告。CodeGraph query/impact/sync/status核验入口、源、历史build及消费者，只有公告历史helper/CLI增加调用，不改变依赖矩阵、下载器或前端。正式全月吞吐、峰值RSS、运行—取消—续跑真实读回尚未验收，不能把隔离测试替代正式阶段。

## 18. P3 正式样本事实（2026-10-04）

[完整验收、性能及全量待批准命令](../../reports/anns_d_dg_p3_sample_20261004.md)、[结构化证据](../../reports/anns_d_dg_p3_sample_20261004.json)。用户批准此前列明的2023-06样本；本节是最新执行状态，§17为开发/预检时点。

六字段source/readback集合一致：147,952→147,952行，完全重复0、reject0、集合差0，30日期文件/1空日；URL缺值3、rec_time缺值66,669保留。capture22.571秒，恢复build1.367秒，候选audit0.904秒，恢复promote1.324秒，重放1.014秒，最终formal audit0.870秒；最大采样进程RSS414,433,280字节。每次测量日志和真实命令保留/private/tmp，时间是实测而非估算。

两次SIGINT分别证明build候选2日和promote正式文件2日持久化；相同计划续跑后既有SHA一致，重放后30个SHA一致、零新增；30日child checkpoint均promoted。正式月audit再验证全部文件，未重新请求源或报事件。既有缺值原始版本逐条读回一致。

本轮没有主代码、配置、API或依赖矩阵变更，没有Prod/instance事件/调度写入。只执行正式样本，剩余80月/2,435文件/11,916,097源行需按阶段批准；P3尚未全量完成。采样月吞吐不能证明最大月峰值，硬内存/时间/空间门禁继续适用；最终Dagster readiness在P4事件及日常验收完成后确认。

## 19. P3 全量事实与退出（2026-10-04）

[全量报告/实测性能](../../reports/anns_d_dg_p3_full_20261004.md)、[聚合证据](../../reports/anns_d_dg_p3_full_20261004.json)、[冻结计划](../../reports/anns_d_dg_p3_frozen_plan_20261004.json)、[正式审计](../../reports/anns_d_dg_p3_formal_audit_20261004.json)。用户明确授权全量五阶段命令，本节是最新状态，§17/§18保留开发/样本时点。

六字段业务数据source/readback均12,064,049行，81月/2,465日/83空日，重复0、拒绝0、双向集合差0。URL缺值15、rec_time缺值4,039,070均保留；全部目标集合/schema/日期分区/指纹通过formal audit，原六月30文件SHA不变。81个捕获checkpoint及2,465日交付checkpoint promoted，源1,249 shards/258,488,034字节，正式200,709,132字节。

五阶段合计2,049.396秒（约34.2分钟），最大观测RSS1,841,954,816字节，峰值月543,563行capture81.189秒，结束剩余空间约2.66TiB；预算/超时/空间拒绝未触发。RSS采样不证明绝对峰值，也不是DuckDB内部用量。本轮没有Python/配置/入口/依赖矩阵变更，没有Prod写入、Tushare/PDF请求、Dagster事件或启用动作。开发156项回归和样本取消/续跑/重放证明保持有效，此次以全部月正式集合读回完成文件验收。

P3退出条件全部达成。P4衔接补拉、独立runless事件、正式日更新恢复/事件失败补报及调度启用尚未执行，不能把物理完成记为Dagster readiness已通过。文件授权不扩大至事件或schedule；后续依照原阶段精确范围审批。

## 20. P4 开发约束（2026-10-05）

P4先开发独立事件plan/materializations/checks/audit入口，随后按明确命令分别批准正式事件样本、全量、衔接补拉、日任务恢复和调度启用。日asset/job和STOPPED定义不改合同，不下载PDF、不写Prod，不增加永久状态表或动态分区。源请求/间隔保持P2。

事件文件事实：历史复用P3冻结计划及formal audit，重新按月完整集合审计；日补拉最多7个delivery.json复用P2交付验证。固定正式Lake/staging及DAGSTER_HOME，只打开已有本机PostgreSQL stores，should_autocreate_tables=False，默认连接transaction_read_only=on，SQL10秒。禁止默认instance发现、初始化、DDL、任意表/SQL/根路径。实例身份冻结配置SHA、主机/端口/库/用户及artifact根（不保存秘密）。

成本：历史最多2,465文件/7,395事件，日补拉最多7文件/21事件；每自然月≤31日期，批量读最新物化、check partition info和对应storage IDs，整次最多30,000返回记录（含info+body），不逐日深扫event history。每月物理扫描只做一轮集合审计，源/目标文件SHA前后固定；存储查询SQL10秒，每月apply最多93事件、1800秒，超预算阻断。原P3完整formal audit18秒/RSS1.72GiB是文件校验测量依据，事件读写性能须真实只读计划/获批样本校准，不能预先声明全量通过。

计算只读边界：不使用Store构造及staging spill；复用只读schema/audit方法，DuckDB临时计算仅在/private/tmp，固定2GB/2线程/20GBspill和25GiB空闲门禁。

配置审计：以上25GiB/31日/30,000记录/1800秒/SQL10秒为公告事件模块固定安全预算，不新增env或Settings参数；消费者为state reader、planner、apply和instance opener，随进程启动生效；测试涵盖超预算、分页不推进和不初始化stores。入口仅运营阶段、计划SHA、已有manifest/审计引用、月份及/private/tmp报告；不增加用户页面输入。

plan冻结日文件、child checkpoint及source页/完整审计证据、当前事件storage IDs和instance身份。物化metadata复用P2 announcement_identity/checkpoint，补文件SHA和合同/schema；check显式partition、blocking ERROR、checked_row_count以及target_materialization_data指向正确storage ID/run/timestamp。日文件改变/证据缺失、旧红灯、错误关联或外部事件变化均阻断。相同文件身份重复报告跳过，不仅按行数或绿灯判断。

物化和checks分两阶段，月内先批量读当前状态，提交事件后批量读回。每事件前后取消检查，每事件checkpoint写失败不回滚已提交事件；重启靠实际事件身份继续，不能靠checkpoint猜已完成。完整月读回通过后形成月checkpoint，检查提交不覆盖业务文件。文件SHA在单事件前复核、源及交付证据在每月开始重验；事件变更用冻结ID/自身计划token比较并最终复核，禁止借其它分区check。只追加正确事实，不删除事件。

隔离正反测试必须覆盖正确日期/target绑定、空日/缺值、partial取消和进程退出、写后报错/读回/观测失败续跑、幂等、文件/源/identity/实例变化、外部事件竞争、旧failed check阻断、超预算与分页停滞、默认只读无初始化。正式只读计划可执行；完成样本完整命令/范围/数量后再审批执行，不把开发授权当成正式event或schedule写入授权。


## 21. P4 开发与只读预检（2026-10-05）

[实现对账、预检和正式样本完整命令](../../reports/anns_d_dg_p4_20261005.md)、[聚合证据](../../reports/anns_d_dg_p4_20261005.json)、[冻结事件计划](../../reports/anns_d_dg_p4_frozen_event_plan_20261005.json)。本节为最新状态，P4尚未全部退出。

独立anns_d_events_cli默认plan，物化/checks/audit分离；history引用既有P3报告重新完整集合审计，daily最多7个已promoted凭据。物理读取不创建Lake/staging，固定PG存储不初始化且plan/audit强制只读；冻结源/目标/交付/父捕获/实例/事件身份。每月批读事件并读回，正确日期与target_materialization_data绑定，逐事件checkpoint、SIGINT/SIGTERM取消、实际事件身份续跑；旧红灯和外部变化阻断，业务文件不参与事件事务。

正式只读预检重新核验81月/2,465文件/12,064,049行；现有公告事件0，待补2,465物化+4,930检查。166项自动化通过（P4新增25项），完整30日隔离物理文件到90事件读回通过；取消/退出/丢响应/观测失败恢复和幂等、反例均通过，scoped Ruff通过。CodeGraph query/impact/sync/status和源码核验覆盖交付/check/CLI消费者，不改变依赖矩阵或原入口。

尚未正式写事件、请求Tushare、补衔接区间、执行正式日任务恢复或启用schedule；2023-06样本30物化/60check的命令、取消续跑/重放及授权范围已具体落档，必须获样本执行批准。全量及后续步骤各自保留阶段审批，不以开发/只读验收替代正式readiness和写入性能证据。


## 22. P4 正式事件样本验收（2026-10-05）

[实测、读回及全量待批准命令](../../reports/anns_d_dg_p4_sample_20261005.md)、[结构化证据](../../reports/anns_d_dg_p4_sample_20261005.json)。用户授权2023-06的30物化/60check和取消续跑重放，本节为最新执行事实，§21保留开发时点。

样本30日/147,952行/1空日，正式30物化+60正确日期且绑定同日mat的绿色检查读回通过；SIGINT取消分别0.238/0.227秒，实际各保留3提交事件；续跑新增27物化/57checks。两阶段重放均新增0。最终audit和首/尾/缺值/空日readiness通过，全范围只读复核全部81月文件/交付/父捕获证据不变。无业务文件/Prod写入，无Tushare/PDF请求及启用；本轮无源码/配置/依赖变化。

剩余80月需新增2,435物化+4,870检查，共7,305事件。报告已列原计划三条完整全量命令、估算5–15分钟（非实测承诺）、取消续跑及精确写范围；尚未获全量执行批准，因此未执行。衔接补拉、正式日任务恢复及schedule各自待具体阶段批准，P4仍未全部退出。


## 23. P4 全量历史事件事实（2026-10-05）

[全量报告、实测及下一阶段具体流程](../../reports/anns_d_dg_p4_full_20261005.md)、[结构化证据](../../reports/anns_d_dg_p4_full_20261005.json)。用户明确授权样本报告三条全量命令，本节为最新事实，§21/§22保留开发/样本时点。

本輪新增2,435物化+4,870check，六月已完成样本跳过；总2,465物化/4,930check、81月/2,465日/12,064,049行，最终audit和新只读缺口plan通过，缺物化0/缺check0。全部文件/源页/日交付/父捕获证据与原冻结计划不变，81事件月checkpoint checks_verified；5个代表日期readiness通过。月批查询audit返回24,650记录，低于30,000门禁，不逐日深历史扫描。三阶段观测94.693/183.384/47.390秒，累计约5.4分钟，计量口径见报告，未测RSS。

无业务文件/Prod写入，无Tushare/PDF请求、日job执行或启用；无源码/配置/入口/依赖改动。历史文件+事件退出，P4整体尚未退出。下一阶段只读plan已明确2026-10-01..04四日、5秒间隔、稳定窗口及原请求/时间/内存预算；四日文件和至多12事件的具体命令、取消恢复、绿色交付门禁及拒绝策略已列明，尚未获该阶段执行授权。正式日任务与schedule继续分别审批，不扩大全量历史事件授权。
