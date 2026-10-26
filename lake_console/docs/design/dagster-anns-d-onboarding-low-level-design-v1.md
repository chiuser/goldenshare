# 上市公司公告接入 DG 代码级 LLD v1

状态：2026-10-26 管理员已确认单job九日更新与取消整批时间期限；本轮只更新设计，以下改动尚未落地。现行代码仍须按本LLD开发、隔离验收后才能另行申请正式执行。

对应[技术方案](dagster-anns-d-onboarding-plan-v1.md)，约束编号R01—R10以方案第10节为准。遵守[编码规范](../../orchestrator/CODING_STANDARDS.md)、[性能治理](dagster-data-pipeline-performance-governance.md)、[schema contract](dagster-asset-schema-contract-design.md)及[接入模板7A](../templates/dagster-dataset-onboarding-template.html#source-contract-budget)。

本文以完整的新执行设计替换被取消的技术设计，不保留两套长期执行路径。既有事实和历史批准仅由第12节的报告索引追溯。

## 1. 开发边界与已有代码依据

### 1.1 固定目标

- 每天08:00 Asia/Shanghai生成一个job运行，自动日期严格为计划日D−7..D+1九日；例如2026-10-26为19..27。
- 无整批总时限；计划时刻只决定日期与去重身份，实际开始/结束时间仅记录进度和耗时。
- 同一job内按日期顺序尝试九日；单日数据错误不阻断其他日，公共资源错误停止。取消不等于失败后自动重试。
- 数据集、文件、schema、检查名称不改；不改变其他数据集的资源、全局并发或自动任务。
- 本轮不重做Prod初始化、不下载PDF、不新增页面、sensor、数据库、摘要资产或独立执行入口。
- 不以历史CLI/runless事件模式承担正式日更；不修改公共TushareResource的其他消费者。

### 1.2 修改位置

路径相对于 `lake_console/orchestrator/src/orchestrator/`。

| 文件/符号 | 实施职责 |
| --- | --- |
| `defs/schedules/anns_d.py::raw_anns_d_update_schedule` | 从九个日请求改为一个范围请求，显式配置和固定批次身份 |
| `defs/jobs/anns_d.py::raw_anns_d_update_job` | 保持asset+原两项checks选择；不放业务循环、取源、SQL或写文件 |
| `defs/assets/anns_d.py::raw_tushare_anns_d` | 范围上下文、逐日执行helper、各日metadata；末尾仅一个MaterializeResult |
| `defs/anns_d_window.py` | 冻结范围、单次执行循环、按日结果和恢复；去掉前日成功门禁及总期限 |
| `defs/anns_d_execution.py` | 复用 `update_announcement_day` 的完整capture/build/promote，保留提交与取消边界 |
| `defs/anns_d_checkpoint.py` | 保留请求计数/间隔/未决请求恢复；移除总期限，保存单次执行信息 |
| `defs/checks/anns_d_checks.py` | 核验helper显式接收day；两个检查节点逐日发出正确分区与物化目标的结果 |
| `defs/run_contracts/anns_d.py` | 移除已取消配置，集中执行版本和配置校验；请求控制保持 |
| `defs/anns_d_cli.py` | 参数和只写文件语义保持，复用同一范围执行helper；plan仍零写入 |
| `defs/bootstrap/anns_d_event_files.py`、`anns_d_history_plan.py`、`anns_d_history_execution.py`、`anns_d_history_cli.py` | 只改证据配置解析的耦合，不改变历史SQL、范围或执行方式 |
| `defs/catalog/lake_assets.py` | 从公告source_request_policy删除整批时间预算；历史event_policy保留`SUPPORTS_RUNLESS_EVENT_BACKFILL`，字段及路径合同保持 |
| `defs/anns_d_partitions.py`、`paths.py`、schema模块 | 核验并保留当前定义，没有必要则不改 |

当前代码的 `context.partition_key`、只返回一日MaterializeResult及基于单日上下文的checks不能直接用于范围运行。CodeGraph已覆盖上述入口、window/day执行helper、CLI、checks与测试；原始代码核验补充了catalog及bootstrap证据消费者。没有跨Prod/Ops/biz依赖变更。

## 2. 资产、字段与时间合同

### 2.1 稳定身份

| 对象 | 名称/定义 |
| --- | --- |
| asset | `raw_tushare_anns_d` |
| job | `raw_anns_d_update_job` |
| schedule | `raw_anns_d_update_schedule` |
| 文件合同check | `raw_tushare_anns_d_file_contract_check` |
| 交付check | `raw_tushare_anns_d_delivery_reconciliation_check` |
| partition model | catalog现有 `ann_date_partition_raw_anns_d` |
| partitions_def | 现有 `anns_d_natural_days`，2020-01-01起，Asia/Shanghai，end_offset=2 |

保留check名称以维护既有事件身份；资产及两个check继续绑定相同partitions_def，保持blocking=True。不得增加同义新check、伪造日期资产依赖或注册交易日动态分区。

时间输入、执行与完整性分开：自动输入按计划日冻结；一次运行九日、源逐日分页、文件逐日提交；完整性按本次观察及检查判断，合法零行不是缺失，当天/次日预取不是永久齐备。

### 2.2 六字段矩阵

| 源字段 | 源/Raw表示 | 可空与规则 |
| --- | --- | --- |
| ann_date | 源YYYYMMDD字符串 / VARCHAR | schema可空，但缺值或非法日期无法归属目标日时整个日候选失败 |
| ts_code | 字符串 / VARCHAR | 可空，不trim，不用股票池或正则过滤债券等公告 |
| name | 字符串 / VARCHAR | 可空，原值保留 |
| title | 字符串 / VARCHAR | 可空，原值保留 |
| url | 字符串 / VARCHAR | 可空，不以URL合并元数据 |
| rec_time | 源发布时间文本 / VARCHAR | 可空，不转时区，不作为公告日期 |

字段顺序固定为上表顺序。缺列、额外未知字段、非缺失数值/对象、错误日期或跨请求日数据均明确拒绝该日，不能删行/补列/转字符串后当作成功。仅SDK的NA/NaT/NaN还原为None；NULL、空串、空白不同。

合并仅使用六字段 `DISTINCT(existing UNION ALL incoming)`。不同URL、NULL与非NULL、不同rec_time等版本都保留；源本次未返回不构成删除理由。definition metadata继续注册稳定schema，运行metadata只写本日path、rows、observed_columns及交付证据。

源依据：doc_id=176，[本地源文档](../../../docs/sources/tushare/大模型语料/0176_上市公司全量公告.md)。沿用既有源字段、空页和缺值证据，本次不改request builder参数、不扩大源请求页大小。

## 3. 请求、日期和执行身份

<a id="automatic-announcement-window"></a>

### 3.1 自动范围

`announcement_refresh_dates(scheduled)`继续在Asia/Shanghai计算D−7..D+1。以字面九日数组作为测试expected，不调用待测helper生成expected。

新运行使用执行格式版本2；这是公告执行信息版本，不能提升六字段数据合同的 `ANNOUNCEMENT_VERSION=1`。执行版本为内部常量，不是运营输入或环境变量。

保留内部tags中的 `anns_d/window_id`、`anns_d/start_date`、`anns_d/end_date`、`anns_d/automatic`。现有 `anns_d/started_at` 名称不另改，但其含义严格为计划时刻；不读它计算是否允许执行。增加内部 `anns_d/execution_version=2`，并将版本、计划日、范围用于整个执行身份。

身份生成集中在 `anns_d_window.py`，例如：

~~~python
window_id = sha256(
    f"anns_d:update:2:{scheduled_local_date}:{first}:{last}".encode()
).hexdigest()[:32]
run_key = build_asset_update_run_key(
    subject="anns_d",
    unit_id=f"update:2:{scheduled_local_date}:{first}:{last}",
)
~~~

run_key只用于去重，不从它解析日期或配置；不得含event storage id。新身份与既有未完成执行不碰撞，同一tick重复求值则保持同一身份。未来实施时同步[run key方案](dagster-run-key-governance-optimization-plan.md)及[run key LLD](dagster-run-key-governance-low-level-design.md)，本轮不提前声称运行合同已实现。

### 3.2 单个RunRequest

schedule只返回一个请求，结构为：

~~~python
RunRequest(
    run_key=run_key,
    partition_key=None,
    run_config={
        "ops": {
            "raw_tushare_anns_d": {
                "config": {"interval_seconds": AnnouncementPolicy().interval_seconds}
            }
        }
    },
    tags={
        **frozen_announcement_tags,
        "dagster/asset_partition_range_start": first,
        "dagster/asset_partition_range_end": last,
    },
)
~~~

不同时设置 `dagster/partition`，也不在job默认tags中遗留单日标签；不保留逐目标日priority。schedule不取源、不读Lake、不开instance、不写执行checkpoint；缺少计划时刻或非法时区时明确失败，不用当前时间猜测替代。

范围请求不会走单日分区的自动config解析，因此必须显式传config。项目校验要核对：版本、window id、ISO端点、九日长度、与计划日一致、Dagster范围一致、D+2不允许。不能指望框架只根据tags完成这些业务校验。

### 3.3 手工和续跑

当前单日手工materialize仍支持；手工历史闭区间继续使用 `announcement_dates` 的已结束日期约束，不因自动D+1放宽。单日上下文也统一通过 `context.partition_keys` 获取一元素列表；禁止自动批次退回逐日子job。

无公告批次tags的手工运行生成新的内部版本2身份；携带批次tags的恢复必须完整一致，不接受缺版本的旧执行身份自动套用新设计。CLI的参数、plan/run含义、默认plan及不写DG事件边界保持；不发布新的任意SQL、表名或根路径入口。

同一执行恢复使用原window id、计划时间、范围及有效policy，不按恢复时钟重算。恢复须是Dagster支持的显式重新执行，不能用“重复schedule求值”代替，后者本来会被run_key去重。

## 4. 单job编排与文件阶段

### 4.1 范围asset

资产声明 `BackfillPolicy.single_run()`，使用 `context.partition_keys`。该声明不会自动把schedule九请求合成一请求，必须同时实施第3节。

资产仅负责接线，业务循环放入 `anns_d_window.py` 的范围执行helper。复用现有 `update_announcement_day`、source和io，不复制下载/合并算法。建议接口：

~~~python
execute_announcement_window(
    days, *, tags, policy, control, store_factory, call_factory
) -> dict[str, AnnouncementDayDelivery]
~~~

返回只包含每日本次交付的计数、路径、identity和checkpoint引用，不包含公告明细。内部for循环保证先旧后新，取消原“前一天必须成功”的跨日门禁；不再依赖队列顺序来决定是否允许读取。

~~~text
验证固定意图并取得本次执行锁
加载执行checkpoint及请求计数
for day in fixed_days:
    检查取消及公共资源
    若该日已提交，核对交付证据和物理指纹后复用
    否则执行原单日capture → build → validate → promote
    单日可恢复错误：记failed并继续下一个日期
    公共错误/取消：保存当前状态并退出，不再领取日期
全部可执行日期已尝试：
    若有失败：保存准确摘要，抛批次失败
    否则返回九份独立交付结果
~~~

数据错误不能仅用宽泛 `except Exception: continue` 吞掉。异常必须按第5节分类，未知错误停止。源码中已保留的源响应校验、候选完整性检查不因为改批次而弱化。

### 4.2 正式物化的时机

文件阶段全部成功后，asset逐日调用：

~~~python
context.add_asset_metadata(day_metadata, partition_key=day)
~~~

每一日metadata使用原 `build_materialization_metadata`：包含该日uri、written_rows、observed_columns、source_rows、existing_rows、new_unique_rows、capture_complete、末页证据、`goldenshare/announcement_checkpoint`及完整identity。不得在九日上复用最后一天的metadata。

完成后只 `return MaterializeResult()` 一次，框架为范围中的每个日分区生成一条物化。不得在循环中返回九次MaterializeResult，不额外手工发出九条相同物化，不把一份整批行数写到每个日期。

如果文件阶段有一天失败，循环仍尝试其他可执行日，末尾抛错；已提交文件保留，本次尚不生成九条范围物化，两个检查节点也不启动。进度和失败摘要须明确“文件已提交”和“检查已通过”不同。同一执行恢复完成缺日后，再生成正确的九条物化。

业务文件不可因事件失败而回滚。这个实现不承诺文件一提交就有正式物化；不能在文档或UI摘要里宣称部分日已经通过本次DG检查。

## 5. 执行checkpoint、错误与取消

### 5.1 持久化位置和内容

沿用执行staging，不新增永久业务状态：

~~~text
data_lake_staging/anns_d/windows/<window_id>/execution.json
data_lake_staging/anns_d/windows/<window_id>/budget.json
data_lake_staging/anns_d/run_id=<sha256(window_id:day)>/delivery.json
~~~

`execution.json`替换本次设计不再需要的admission职责；旧文件保持历史现场，不自动迁移或删除。身份包括execution_version、固定日期列表、计划时间、有效policy及字段合同；进度包括：

- phase、active_run_id、current_day、actual_started_at、updated_at；
- attempted_days、files_completed、failed_days及各日phase/reason；
- 每日checkpoint引用及交付指纹，当前来源页/offset和请求消耗；
- 文件完成量/总量；检查进度由各自节点日志和原生检查事件记录，不把心跳或文件提交量当成检查完成量。

时间只用于可见进度与耗时，不能据其拒绝新日期、分页或续跑。checkpoint通过现有原子JSON写入和fsync持久化；先验证身份再写，不能覆盖不匹配的执行意图。

`budget.json`保留 `window_id, identity, requests, day_requests, in_flight, next_request`，不生成或消费整批deadline。identity绑定同一固定范围、有效policy和执行版本，计数、间隔和未决请求只由当前执行持锁修改。

初始化和崩溃恢复必须固定：取得本次执行锁→校验不存在同身份的旧执行现场→原子写零计数budget→原子写execution→才允许领取源请求。仅budget存在且identity一致、requests=0、无day_requests、in_flight=False时，可完成被中断的初始化；budget已有消耗却无execution，或execution存在却缺失/损坏budget，均停止，不从零重建配额。正常恢复先严格读回两个文件的身份再领取请求；测试覆盖这两个原子写之间退出以及首个请求后退出。

两个check节点在同一run内可能并发，不能以max_concurrent_runs=1推断它们串行。检查节点不共同累加execution.json；各自发出带check_name、day、evaluated_count/total、phase和updated_at的结构化进度日志及原生检查事件，最终按本run的两个check结果汇总。无需新增共享检查计数文件，也避免read-modify-write丢更新。

### 5.2 失败分类

| 类别 | 示例及判断依据 | 后续 |
| --- | --- | --- |
| 单日源失败 | `announcement_source_timeout`、`announcement_source_call_failed`、`announcement_source_process_exit`在该页三次尝试后仍失败 | 保存该日failed，继续其他日期 |
| 单日响应/数据错误 | 缺列、类型/日期/分区不符、oversized/repeated page、capture不完整、当日请求上限 | 不提升该日候选；记录具体reason，继续其他日期 |
| 共享执行/资源错误 | 意图不符、卷/权限/空间失效、总请求预算用尽、writer_busy、目标/候选指纹冲突、执行证据损坏 | 停止本批，保留成功日，列出未尝试日期 |
| 未预期异常 | 未归入已测试reason集合的异常 | 停止，不默认当成单日源问题 |
| 主动取消/KeyboardInterrupt | control取消或进程信号 | 不再领取页/日，终止源子进程并保存可恢复状态 |

开发时在公告模块集中维护上述reason分类，不复制到job/schedule/页面。现有SDK错误已脱敏，不能从隐藏的异常文本推断认证失败，也不能为分类暴露token或完整SDK响应。

批次失败摘要列：固定日期、已尝试日期、文件已提交日期、失败日期及reason、未尝试日期、原执行身份、checkpoint位置和已用请求数。无无限重试、整批自动重跑或成功后再审全局。

### 5.3 续跑边界

- day checkpoint存在validated delivery：先验证完整来源页及候选/目标指纹，再继续promote或恢复promoted。
- 正式文件等于已保存交付指纹：补齐本次执行记录，复用交付，不再次取源或重写正式文件。
- capture完整但未build：核来源页SHA，复用完整capture构建候选。
- capture不完整：用新attempt重新拉该日全部页；旧attempt保留，不把不同观察时刻的offset拼接。
- 已完成的其他日只做恢复必要的指纹/证据核对，不再次下载；剩余请求仍计入同一budget。
- 目标文件已被其他批次更新：旧交付不能冒充当前文件，不强行提升旧候选；明确冲突，不擅自新建执行或重置计数。
- 事件阶段失败：文件不回滚；显式恢复本次执行时按稳定物理证据再次形成本次物化并运行checks，不承诺完全不新增观测事件。

取消检查保留在每页前后、每日前后及文件计算观察线程。源子进程仍按cancel_grace释放。没有整批总期限，不等于取消单次源请求超时或人工取消能力。

### 5.4 跨日与并发

计划26日的范围始终19..27，即使27日00:10开始也不变。27日的新计划有独立身份与20..28范围，不自动合并或重写旧执行。

本机当前全局max_concurrent_runs=1，本轮不改；同一job文件循环不会与另一个DG run并行。保留公告源执行锁及每日提升锁；锁冲突明确失败，不伪称已有等待重试能力。CLI/历史工具也必须遵守现有写入保护，人工恢复前核查无同范围并行写者。

## 6. 源读取、文件写入与配置

### 6.1 Tushare请求

继续 `announcement_request`：

~~~python
{
    "ann_date": day_as_YYYYMMDD,
    "limit": 2000,
    "offset": actual_rows_already_captured,
}
# TushareResource.call("anns_d", params, ANNOUNCEMENT_FIELDS)
~~~

不加ts_code/title过滤，不改为九天一次请求。短页结束，满页继续；零行也必须六字段schema完整。每页保存原始响应、规范化输入和Parquet及SHA，checkpoint完整后推进offset。

每页最多三次尝试，只有已知调用超时/调用失败/子进程退出会重试，重试不推进offset；每次尝试都消耗持久化请求数。开始捕获前及请求结束后保持默认五秒间隔，恢复未决请求也保留间隔，不增加源并发。

### 6.2 文件提交

正式路径保留：

~~~text
/Volumes/datasource/data_lake/raw/tushare/anns_d/ann_date=<day>/part-000.parquet
~~~

页、候选、DuckDB spill在本批staging。只读取本日现有文件及本日来源页，显式六列建立relation，用DuckDB合并、审计、COPY；完整候选检查通过后，在同文件系统 `os.replace`、fsync并保存delivery。

`build_day`、`promote_day`中的schema、来源/候选集合、计数、基线及来源页SHA校验保持，不在本轮顺带重写计算算法。失败候选不进正式Lake，已提交其他日期不回滚；不能自动删除stage、生成备份或调用Kopia。

### 6.3 配置审计表

| 名称 | 值及来源/持久化 | 消费者与本次处理 |
| --- | --- | --- |
| ANNOUNCEMENT_CRON/TIMEZONE | 08:00 / Asia/Shanghai，run_contracts代码常量 | schedule和日期归一化；不改钟点、不改实例启停 |
| ANNOUNCEMENT_REFRESH_DAYS | 7，代码常量 | 过去七天+D+D+1；不能改为9后多取两天 |
| execution_version | 2，公告执行代码常量，run tags/checkpoint | 区分新的执行意图；不是运营可调参数，不提升字段合同版本 |
| page_size | 2000，Policy及执行记录 | builder/分页/check，保持 |
| interval_seconds | 默认5，RawConfig或现有CLI，run config/checkpoint | 唯一既有运营可覆盖调用参数，要求有限且≥0 |
| max_attempts/call_timeout/cancel_grace | 3 / 30s / 5s，Policy及记录 | 单页尝试、调用进程及取消；保持，不与整批期限混淆 |
| max_day_requests/max_window_requests | 100 / 350，Policy及budget | 单日/整批源请求次数，含重试与续跑；保持，不宣称源站硬限 |
| max_window_seconds | 从新执行Policy、校验、序列化、调用方和catalog中移除 | 不写deadline，不检查运行年龄，不用极大值或inf伪装取消 |
| duckdb_memory/threads/spill_limit | 2GB / 2 / 20GB，Policy | 专用受控连接，spill进本批staging；不改其他资产默认 |
| min_free_reserve | 5GiB，Policy | 保留现有卷/空间检查，不视为整批总空间估算 |
| Prod历史控制 | fetch=10000、月200万行、月1800s、SQL60000ms | 保留，仅解除历史证据与日更Policy整体构造的耦合 |
| token/连接 | 既有resource/env，秘密不进入记录 | 不新增环境变量，不复制秘密；Prod无日更fallback |
| 根路径 | 正式paths及staging固定路径 | 不从旧config/env/旧Lake兜底 |

代码变更随code location重载生效；重载与正式触发另获执行批准。所有有效非敏感配置、固定范围和执行版本在run摘要可见；删除的参数不能继续作为新运行可传字段。

## 7. 原生按日物化和检查

### 7.1 必须采用的范围适配

本机Dagster1.13.26核验：范围运行不能读 `context.partition_key`；`AssetCheckResult`无partition参数，直接返回会把range检查写为partition=None。不能仅加single_run policy而保留旧单日函数。

采用第4节的逐日metadata、一次MaterializeResult方案。两个独立 `@asset_check` 的名称、分区及blocking定义保留；不把它们替换成只记整批结果的新check。

`evaluate_announcement_check`改成显式接收day和当前run身份的纯核验调用，不在其中从context猜单日日期；返回每日本次检查的passed、metadata和目标物化引用。check-only单日运行继续支持，不能要求每次检查一定重写asset。

### 7.2 每个检查节点的输出

每个检查节点：

1. 取并校验 `context.partition_keys`，对每个day执行原schema或交付规则。
2. 查该day的目标物化；选中asset共同执行时必须是当前run；只跑check时按既有规则取该day最新物化。
3. 原生发出 `AssetCheckEvaluation`，显式设置asset_key、check_name、partition=day、passed、severity=ERROR、blocking=True、metadata及 `target_materialization_data`。
4. 单日核验返回未通过且节点可继续时，仍对其余day产生结果；最后发出该check节点所需的一次 `dg.Output(None)`，让框架完成节点输出并按blocking失败决定run终态。取消、公共故障或未处理异常不属于这一继续承诺，必须按第5节停止并报告未核验日期。

`AssetCheckEvaluation`使用本机已验证的 `dagster._core.definitions.asset_checks.asset_check_evaluation` 类型，事件由正在执行的check step yield进入正常引擎；不调用instance.report_runless_asset_event，不直写event表。内部API的使用仅封装在本数据集checks模块，并由固定版本隔离事件测试保护，不能扩散成通用事件框架。

仅yield逐日Evaluation而不发节点Output会造成缺result输出失败；仅yield一个AssetCheckResult会丢分区归属。两者均需反向回归测试。两个检查节点互不依赖，不因其中一个day失败而主动跳过另一个check。

### 7.3 两项原有规则

文件check：普通正式文件、安全路径、六列顺序/类型、日期与目录一致、全字段重复组为零；合法空日及缺URL/rec_time等不误拦。

交付check：目标checkpoint属于本日、本次交付；完整capture/末页证据；来源页与目标SHA未变；计数/集合对账及保存的readback一致；核验期间最新物化及文件保持稳定。不会重新请求Tushare或Prod。

目标引用必须是 `AssetCheckEvaluationTargetMaterializationData(run_id=..., timestamp=..., storage_id=...)` 对应本日物化，不能用整批最后一天的引用。读取现有events要有asset+day过滤和limit；正常收尾只汇总本run 9/18条事件，不增加全历史readiness循环。

沿用现有有界查询时，文件check增加每日本次物化查询一次，交付check保留每日前后各一次：九日最多27次`limit=1`元数据查询，均核对asset/day及目标run；不是扫描事件历史。不得为了收尾再重复九日readiness深查。后续若复用同一批已查结果，仍须保留交付检查的物化稳定性验证，不能只为减少次数删规则。

### 7.4 已完成的框架核验及证据边界

本轮只在隔离内存环境核验Dagster1.13.26接口，未导入正式项目defs或连接正式instance、DB、Lake：

- 单次schedule evaluate_tick返回一个范围RunRequest，partition_key=None、范围19..27、显式config保留；解析结果无需backfill daemon。
- 阅读调度提交源码确认没有强制单日partition_key；单日tag不能与range tags并存。
- 固定九日的单run产生恰好9条物化及18项检查，各日metadata和target_run_id正确。
- 证明无Output的检查节点会失败，普通AssetCheckResult在range下分区为空。
- 一个日期的交付检查返回未通过时，仍生成两个check各九条结果，兄弟检查未跳过，run最终失败；仅证明可继续的规则失败，不包括异常退出。
- check-only单日通过既有单日tag/选择路径得到两项检查、零新物化，目标绑定原物化；不新增检查专属job。独立仅checks job不能直接假设`execute_in_process(partition_key=...)`会从check specs推导分区，隔离测试必须使用真实可解析的入口。
- 已独立读取隔离instance的检查执行历史：两个check各九条持久记录，`record.partition`与evaluation.partition均为19..27且无None，run_id和target storage_id逐日正确。失败样本同样保留十八条记录，其中一个FAILED，其余SUCCEEDED。该证明只涉及临时实例，不是正式PostgreSQL或业务验收。

这些只证明框架路径可行，不证明本次公告业务代码、真实daemon/RPC提交或正式补数已经通过。未来开发必须将此路径固化到项目测试，不能只引用会话中的临时验证结果。

## 8. 历史证据读取及切换

### 8.1 删除参数的实际影响

现有window/day checkpoint的identity保存 `asdict(policy)`；checks及history/event-files直接 `AnnouncementPolicy(**stored_policy)`。旧成功物化中包含被删除的配置，若只删新类字段，会使历史检查抛TypeError并变红。旧冻结历史计划也有同样问题。

必须在同次开发统一调整所有证据消费者：

- `checks/anns_d_checks.py`
- `bootstrap/anns_d_event_files.py`
- `bootstrap/anns_d_history_plan.py`
- `bootstrap/anns_d_history_execution.py`
- `bootstrap/anns_d_history_cli.py`
- 这些模块直接调用的校验、store和checkpoint构造路径

开发前以符号引用审计清零“把整份历史policy当成当前执行参数”的残留，不只修新job。

### 8.2 统一读法

历史policy是那次执行的原始记录，不是今天运行参数。证据读取保持一套流程：

1. 原identity字典完整读取，与原checkpoint严格匹配；原文件SHA、计划fingerprint、日期及路径不变。
2. 文件核验只显式提取真正需要的page_size、DuckDB配置及文件/交付字段，构造专用只读核验输入；不把整个policy作为kwargs实例化当前执行Policy。
3. bootstrap冻结计划同样只读取月捕获实际需要的fetch/行数/SQL/月份配置，仍验证原始计划fingerprint及范围，不重新封存旧计划。
4. 所需字段缺失、类型非法、日期/路径/identity/SHA错误仍拒绝；不能因不再使用旧执行时间字段就放宽文件合同。
5. 新执行配置严格只允许当前有效字段；移除参数不接受为运行输入。六字段合同及原checkpoint合同版本不提升、不批量改旧物化metadata。
6. 全部新旧证据走统一的按用途读取，不维护按旧设计执行的分支、旧executor或长期兼容入口。

实现落点固定在`anns_d_contract.py`的证据解析helper及既有消费者：`announcement_file_settings_from_evidence(identity)`显式读取`page_size、duckdb_memory、duckdb_threads、spill_limit、min_free_reserve`，验证类型与正值，返回只用于文件核验的结构；不能接受或启动源请求。历史计划的`announcement_history_settings_from_plan(plan)`显式读取`prod_fetch_rows、max_month_rows、month_deadline、sql_timeout_ms`及同一文件计算配置。调用方保留完整原identity做严格匹配，不把提取结果写回原记录。来源字段、日期、路径、SHA和fingerprint验证仍使用原有规则；已经完成的交付不会仅因原执行的总期限已过而失效。

历史计划若用于真正执行，仍必须校验并使用其冻结的月份、上界id、范围、源/目标路径及上述全部历史执行配置；缺字段、非法值、超原有界限均拒绝，不能以“仅为历史记录”为由跳过执行检查，或用当前默认值替代冻结值。移除的是日常整批总期限，原Prod月/SQL控制继续保护历史执行。

已结束的历史文件和观测保持可核验；旧未完成window不自动纳入新job续跑。新执行身份不得借旧完成标记跳过来源观察，也不得覆盖旧执行现场。

### 8.3 正式切换

本轮不实施。未来顺序为：隔离测试通过→列清批准的重载范围及旧活动任务→停止本公告旧入口领取新任务并让活动任务正常结束或按批准取消→重载→确认只有一个正式公告job/schedule定义→恢复原实例持久启停状态→另获准运行一次新九日job。

不同时保留两套自动schedule，不启停其他数据集，不提升全局并发，不擅自重启整机服务。旧失败run不改成成功，旧checkpoint/staging不自动删除。核验新run的执行版本、范围、1/9/18数量及物理结果后汇报。

08:00到实际创建任务之间的延迟原因仍是独立审计事项：现有记录只能排除该批run排队数小时，不能断定停机或休眠；更不能宣称单job改造已解决后台准点运行。

## 9. 测试、夹具和开发步骤

使用本工程已有.venv；无安装/升级、隐式uv同步。测试资源只用临时目录与隔离instance，禁止正式DAGSTER_HOME、正式Lake或token。夹具依据 `ANNOUNCEMENT_FIELDS`、现有source/Prod生产者及既有真实缺值样本；expected用独立字面日期/数据，不由待测函数生成。

| 测试组/拟落点 | 正向与反向验收 |
| --- | --- |
| `test_anns_d_window.py`、`test_anns_d_definitions.py` | 08:00 schedule只返回1请求，固定19..27；跨月/年、北京时间跨日；重复tick同key；tag冲突、D+2、错范围/版本拒绝 |
| 同上 | 计划08点实际15:35、运行超过一小时、隔日恢复均可继续；新执行无deadline检查；日期不随时钟漂移 |
| `test_anns_d_execution.py`及window测试 | 中间日失败后后续日期确实被调用；最终失败摘要准确；共享故障/未知异常立即停并标未尝试，不吞错 |
| `test_anns_d_source.py` | 满页/短页/空页schema、offset、三次尝试、单次30秒与取消进程；请求间隔与100/350计数不重置 |
| `test_anns_d_io.py`、execution测试 | 完全重复及NULL/空白/不同版本；budget/execution初始化中间退出、已消耗预算缺证据拒绝；候选失败、提交后崩溃、目标变化、已提交复用、不完整capture重拉 |
| definitions/checks隔离测试 | 单run9条物化、18项检查、各日metadata、partition及target绑定；同时读取隔离instance的`asset_check_executions`记录，两个check各九个非空且正确的partition；重复MR/空分区Result/无Output错误路径；单日规则返回未通过时其余结果仍完整，异常/取消不伪造已检查 |
| 同上 | 第4日失败但第5..9日实际尝试；成功文件保留、范围asset无假物化；同意图恢复只拉失败日后形成9/18结果 |
| checks-only隔离测试 | 单日检查不触源、不重写文件；历史成功证据仍可读；缺物化、错run/day/path/SHA/必要配置缺失不假绿 |
| bootstrap相关测试 | 原生产者生成的旧冻结计划/交付及新证据均按同一读法验证，fingerprint原样；删除参数不能作为新运行输入 |
| catalog/static gates | 资产/检查身份、schema、路径、end_offset保持；公告performance policy无总期限；无旧九请求、前日成功门禁、runless正式日更或共享resource行为变化 |

测试实施按项目现有实际文件继续组织，新增测试只覆盖本次必要边界，不为低风险文档变化另造测试框架。开发前确认各测试路径与授权边界。

推荐开发顺序：

1. 统一证据读取、移除总期限配置与全部消费者，先防止历史检查失效。
2. 实现范围身份、单请求schedule及window逐日执行，覆盖失败、取消及续跑。
3. asset与两个checks范围适配、catalog对账和run key文档同步。
4. 全部定向单元/隔离集成通过，再做计划逐条对账；本阶段不触正式资源。
5. 汇报变更与测试后，再按批准范围重载和正式运行；不用本轮文档批准替代执行批准。

## 10. 性能、读写与恢复预算

### 10.1 正常一批

自动模式N=9。对第i日设来源行数n_i、更新前正式Parquet大小F_i、完整来源页Parquet总大小S_i、候选大小C_i；源JSON总字节、checkpoint及spill另计。

- 基础页数 `p_i=floor(n_i/2000)+1`，空日一页，满页后继续取结束页。
- 实际请求数Q含失败尝试，单日≤100、整批≤350；未完成不得因达到上限当作完整日。
- 正常最多9次同文件系统替换；Parquet写入 `W=Σ(S_i+C_i)`。rename不再完整复制C_i，也不备份旧F_i。
- SDK调用响应、原始offset JSON及规范化输入JSON均写staging，大小不能从压缩Parquet反推；按实际字节累计。
- Python只持一页2000行及九份小型结果；DuckDB专用连接2GB/2线程/20GB spill，文件计算仍列式。
- 不承诺实际磁盘I/O等于文件大小；按SQL relation引用加完整SHA保守计，正常Parquet输入预算如下。

| 现有阶段 | 保守读取量 |
| --- | --- |
| build_day | 9F_i + 6S_i + 5C_i |
| promote_day | F_i + S_i + 3C_i |
| 文件check | 4C_i |
| 交付check | 7C_i + S_i |
| capture完成后的源页SHA | S_i |
| 一批合计 | R=Σ(10F_i + 9S_i + 19C_i) |

这是按每次SQL引用完整输入估计的逻辑读入量，不是OS实测I/O封顶；列裁剪/缓存可能减少，footer、JSON、绑定及spill另计。原因是merged为VIEW，count、audit、COPY和双向EXCEPT会再次引用输入，不能写“旧文件只读一次”。

本次保留原检查语义，不新增一遍完整源抓取或全局审计。实现时显式记录各阶段输入文件/字节、SQL/请求数和输出字节；正常9/18结果完成后只做本run收尾。

### 10.2 中断、恢复和空间

| 恢复位置 | 必要工作及开销 |
| --- | --- |
| 已完成其他日 | 仅必要文件指纹/身份核对；不再请求，不因一个日失败重做九日审计 |
| capture不完整 | 新attempt重拉该日；已消耗请求不退还，旧页/JSON保留，所以预算同时含旧attempt与新attempt |
| capture完整、未形成delivery | 复核来源页SHA后构建候选；仅该日新增候选写入C_i，无源下载 |
| delivery已validated、未promote | promote及两检查，保守约F_i+2S_i+14C_i读取，rename不增加完整候选写入 |
| 目标已是已交付SHA | 恢复分支及两检查，保守约2S_i+12C_i读取，不重写正式文件 |
| 事件/检查失败 | 只恢复已有文件证据及重新需要的事件/检查，不新抓来源；事件可有恢复重放记录，不能承诺数据库零新增 |

上述只对相应日生效；不能把每个恢复公式再对已完成九天各执行一遍。真实恢复位置与文件状态决定采用哪一项，不能默认自动重跑一次整批。

额外空间包括来源Parquet、三类JSON、待提升候选、checkpoint、失败attempt及DuckDB spill；正式数据增长为各日新C_i替换旧F_i后的差额。现有5GiB空闲保留是空间检查，不是总开销估算。正式执行前仅对目标日stat和已有执行记录估算这些量，不读取全历史；不能因文档有20GB spill配置就预先生成或扫描20GB文件。

### 10.3 测量与收尾

最近30天原方式已有10个成功九日批次，耗时约139—166秒；只说明当时规模，不能作为新job必须在固定时间内结束的门槛。取消的是整批期限，不取消观测及单次请求控制。

隔离验证记录实际文件数、行数、请求与SQL次数、峰值RSS、临时文件和恢复增量；不做额外正式性能压测。本次自动目标固定九日，日常收尾为本run的9条物化、18项检查及九日文件统计；不反复审全历史。未知来源规模不预填“全部通过”，请求/空间等非时间限制触发时准确报告失败。

## 11. 授权、部署与交付

本轮只允许文档细化和已完成的隔离框架能力核验；没有改生产代码、安装依赖、访问正式源、触发job、重载或改正式实例。后续开发按本LLD的硬约束—代码—测试逐条对账，不能只以测试总数作验收。

正式执行前说明命令、DAGSTER_HOME、目标九日、读写及恢复开销、当前执行记录和重载影响；历史全局读取/初始化批准不覆盖新任务。真实源验证仅补仍缺的有界证据，不用每个测试重读正式数据。

交付至少列清：改动模块、一个schedule请求、单run固定九日、无整批期限、文件/物化/check数量、每项失败和未完成日期、恢复依据、旧证据可读结果、实际读写与临时空间、未执行事项。代码开发、正式写入与08:00迟到根因分别说明，不混为已完成。

## 12. 历史报告与引用保留

本节只保留追溯链接，旧执行设计不再作为当前方案。对应[方案历史索引](dagster-anns-d-onboarding-plan-v1.md#11-历史证据索引)，以下JSON仍为当时独立证据，不能当作本轮新实现已通过。

<a id="15-p2-实现与验收对账2026-10-04"></a>

- [P0证据](../../reports/anns_d_dg_p0_20261004.json)
- [核心实现证据](../../reports/anns_d_dg_p1_20261004.json)
- [初始接线报告](../../reports/anns_d_dg_p2_20261004.md) / [证据](../../reports/anns_d_dg_p2_20261004.json)
- [历史入口证据](../../reports/anns_d_dg_p3_20261004.json) / [样本证据](../../reports/anns_d_dg_p3_sample_20261004.json) / [全量证据](../../reports/anns_d_dg_p3_full_20261004.json)
- [冻结计划](../../reports/anns_d_dg_p3_frozen_plan_20261004.json) / [历史正式审计](../../reports/anns_d_dg_p3_formal_audit_20261004.json)
- [历史事件接线证据](../../reports/anns_d_dg_p4_20261005.json) / [样本证据](../../reports/anns_d_dg_p4_sample_20261005.json) / [全量证据](../../reports/anns_d_dg_p4_full_20261005.json)
- [历史事件冻结计划](../../reports/anns_d_dg_p4_frozen_event_plan_20261005.json)
- [衔接补拉证据](../../reports/anns_d_dg_p4_bridge_20261005.json) / [启用及停机证据](../../reports/anns_d_dg_p4_enablement_20261005.json)

保留既有自动窗口和历史接线锚点，只为外部文档可追溯；锚点下均以本次正文或历史报告索引为准，不恢复被取消的执行设计。
