# 上市公司公告接入 DG 代码级 LLD v1

状态：2026-10-27 第三项原生中断分类及两项隔离验收待办已按第17节完成，最终613项及40项子用例通过，结果见17.7。前两项历史585项通过保留在16.6。正式重载、真实源/正式PostgreSQL事件验收、任务及补数均未执行，不将隔离完成等同于正式上线验收。

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
| `defs/assets/anns_d.py::raw_tushare_anns_d` | 范围上下文、逐日执行helper、各日metadata；末尾仅一个MaterializeResult；保留既有backfill policy |
| `defs/anns_d_window.py` | 冻结范围、单次执行循环、按日结果和恢复；去掉前日成功门禁及总期限 |
| `defs/anns_d_execution.py` | 复用 `update_announcement_day` 的完整capture/build/promote，保留提交与取消边界 |
| `defs/anns_d_checkpoint.py` | 保留请求计数/间隔/未决请求恢复；移除总期限，保存单次执行信息 |
| `defs/checks/anns_d_checks.py` | 核验helper显式接收day；两个检查节点逐日发出正确分区与物化目标的结果 |
| `defs/checks/anns_d_check_targets.py` | 只承接检查目标、实际执行步骤和根run分类、同日物化及未重跑兄弟检查的有界引用核验；不复制文件/交付规则 |
| `defs/run_contracts/anns_d.py` | 移除已取消配置，集中执行版本和配置校验；请求控制保持 |
| `defs/anns_d_cli.py` | 参数和只写文件语义保持，复用同一范围执行helper；plan仍零写入 |
| `defs/bootstrap/anns_d_event_files.py`、`anns_d_history_plan.py`、`anns_d_history_execution.py`、`anns_d_history_cli.py` | 只改证据配置解析的耦合，不改变历史SQL、范围或执行方式 |
| `defs/catalog/lake_assets.py` | 从公告source_request_policy删除整批时间预算；历史event_policy保留`SUPPORTS_RUNLESS_EVENT_BACKFILL`，字段及路径合同保持 |
| `defs/anns_d_partitions.py`、`paths.py`、schema模块 | 核验并保留当前定义，没有必要则不改 |

开发前基线的 `context.partition_key`、只返回一日MaterializeResult及基于单日上下文的checks不能直接用于范围运行。CodeGraph已覆盖上述入口、window/day执行helper、CLI、checks与测试；原始代码核验补充了catalog及bootstrap证据消费者。没有跨Prod/Ops/biz依赖变更；本轮实现对账见第14节。

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

自动身份生成集中在 `anns_d_window.py`，固定为：

~~~python
window_id = sha256(
    f"anns_d:update:2:{scheduled_local_date}:{first}:{last}".encode()
).hexdigest()[:32]
run_key = build_asset_update_run_key(
    subject="anns_d",
    unit_id=f"update:2:{scheduled_local_date}:{first}:{last}",
)
~~~

run_key只用于去重，不从它解析日期或配置；不得含event storage id。新身份与既有未完成执行不碰撞，同一tick重复求值则保持同一身份。[run key方案](dagster-run-key-governance-optimization-plan.md)第14节及[run key LLD](dagster-run-key-governance-low-level-design.md)第18节同步本次实现；正式调度执行仍须另行验收。

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

不新增或改变asset的backfill policy，保留手工UI原有默认逐分区回填；本次不开放另一个无自动意图tags的DG多日range入口。Dagster CLI的partition-range还有独立policy要求，本次不新增该入口。CLI原有历史闭区间plan/run继续调用同一业务helper，但只写文件、不产生DG事件，仍适用其原有范围/请求控制。

身份与恢复固定如下：

| 入口 | 全新执行 | 已有执行/重新执行 |
| --- | --- | --- |
| 自动schedule | 按第3.1节计划日和固定范围生成一次身份与tags | 使用原tags；逐项匹配execution/budget；不接受缺版本旧tags自动套用新设计 |
| 手工UI单日 | `root = context.run.root_run_id or context.run.run_id`，window_id取`sha256(f"anns_d:manual:2:{root}:{first}:{last}".encode()).hexdigest()[:32]`；首次才记录当前时刻 | 根据相同原生root字段及范围找到execution，先读取原计划时间/policy，再验证输入；不能依赖可能不存在的`dagster/root_run_id`标签，也不能因为新run_id而新建意图 |
| CLI历史闭区间 | 未传window-id则保持生成新UUID；显式新window-id首次才记录当前时刻 | 收到已存在的`--window-id`时，先只读execution取得原计划时间/范围/policy，核对输入日期和间隔完全一致后构造恢复tags；不每次取now |

无公告tags的手工asset内生成的tags不会自动回写到Dagster run，故稳定root及持久execution是恢复依据。两个独立手工新run即使同日同范围也必须有不同身份并重新观察来源，不能把一次新的请求误作已完成执行的重放。

plan模式可以只读已存在的执行信息，但不能创建目录、锁、budget或checkpoint；新意图尚未冻结的计划时间在plan中仅为预览，run时首次持久化才生效。发现旧admission、无版本预算或旧delivery的未完成执行，不覆盖、不重置，按第8节另行明确补拉。

同一执行恢复保持原window id、计划时间、范围及有效policy。采用Dagster显式重新执行：文件/物化阶段未完成时包含asset；仅checks失败时允许from-failure只执行相应检查节点，具体计数和绑定见第7节。重复schedule求值仍按run_key去重，不能代替恢复。

包含asset的恢复也必须先按第16.2节核根日期、根配置及所有显式身份字段；不能只在checks入口核root。原初始化前失败和合法零预算恢复保留，旧P2现场拒绝自动换成v2身份。

## 4. 单job编排与文件阶段

### 4.1 范围asset

资产保留当前backfill policy，使用 `context.partition_keys`。本机已验证schedule直接提交None加范围tags即可执行单run九日，不需要声明`BackfillPolicy.single_run()`；只改policy也不会把九个schedule请求合成一个。这样保持既有手工UI回填行为，本轮仅实施第3节的自动范围请求。

资产仅负责接线，业务循环放入 `anns_d_window.py` 的范围执行helper。复用现有 `update_announcement_day`、source和io，不复制下载/合并算法。执行接口固定为：

~~~python
execute_announcement_window(
    days, *, tags, policy, control, store_factory, call_factory
) -> dict[str, AnnouncementDayDelivery]
~~~

`AnnouncementDayDelivery`在同模块定义为不可变小记录，字段为`day: str`、`checkpoint_path: Path`、`identity: Mapping[str, Any]`、`delivery: Mapping[str, Any]`；delivery仅含已有交付计数、页/文件路径、指纹及末页证明，不装入公告明细。返回字典按已验证日期完整覆盖本批；有失败则不返回不完整成功字典。内部for循环保证先旧后新，取消原“前一天必须成功”的跨日门禁；不再依赖队列顺序决定是否允许读取。

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

取得本次执行锁后先区分新建与恢复：两文件均不存在且不存在旧执行现场时，才按“原子写零计数budget→原子写execution→允许领取请求”新建；两文件均已存在时，正常恢复严格核对两份身份、固定时间/范围/policy及计数，不以文件已存在为错误。仅budget存在且identity一致、requests=0、无day_requests、in_flight=False时，可完成被中断的初始化；budget已有消耗却无execution，或execution存在却缺失/损坏budget，均停止，不从零重建配额。测试覆盖两个原子写之间退出以及首个请求后退出。

每个day的最新phase/reason是汇总来源，不用只能追加的failed列表：失败日恢复为promoted后移除其旧reason，重新派生attempted_days、files_completed、failed_days和未尝试日期。一次attempt的错误历史可保留，不能让旧failed标记使已成功的本批继续报失败；测试必须验证“首轮中间日失败、同意图恢复成功后整批成功”。

若日记录已经持久化为promoted，随后进度日志等步骤失败，不得覆盖已提交事实或删除checkpoint/fingerprint。窗口原来已有promoted记录时，异常处理始终优先保留其原checkpoint和fingerprint，不能采纳与其冲突的日证据。仅原窗口尚无提交记录且确已进入day helper，才按第15.4节严格核验日checkpoint和目标SHA后补记。保留phase=promoted，另存failure_phase（failed或cancelled）和reason；已提交量不减少，失败日同时反映失败阶段。正常恢复清除两层旧错误，原子替换后、promoted持久化前退出仍按既有validated交付与正式指纹恢复。

两个check节点在同一run内可能并发，不能以max_concurrent_runs=1推断它们串行。检查节点不共同累加execution.json；各自发出带check_name、day、evaluated_count/total、phase和updated_at的结构化进度日志及原生检查事件，最终按本run的两个check结果汇总。无需新增共享检查计数文件，也避免read-modify-write丢更新。

### 5.2 失败分类

| 类别 | 示例及判断依据 | 后续 |
| --- | --- | --- |
| 单日源失败 | `announcement_source_timeout`、`announcement_source_call_failed`、`announcement_source_process_exit`在该页三次尝试后仍失败 | 保存该日failed，继续其他日期 |
| 单日响应/数据错误 | 缺列、类型/日期/分区不符、oversized/repeated page、capture不完整、当日请求上限 | 不提升该日候选；记录具体reason，继续其他日期 |
| 共享执行/资源错误 | 意图不符、卷/权限/空间失效、需要新请求但总次数已用尽、writer_busy、目标/候选指纹冲突、执行证据损坏 | 停止本批，保留成功日，列出未尝试日期 |
| 未预期异常 | 未归入已测试reason集合的异常 | 停止，不默认当成单日源问题 |
| 主动取消/KeyboardInterrupt | control取消或进程信号 | 不再领取页/日，终止源子进程并保存可恢复状态 |

执行层reason分类集中在公告window模块，检查规则白名单集中在checks模块；两者只管理各自语义，目标引用模块不复制文件规则，不扩成通用异常框架，也不复制到job/schedule/页面。现有SDK错误已脱敏，不能从隐藏的异常文本推断认证失败，也不能为分类暴露token或完整SDK响应。

批次失败摘要列：固定日期、已尝试日期、文件已提交日期、失败日期及reason、未尝试日期、原执行身份、checkpoint位置和已用请求数。无无限重试、整批自动重跑或成功后再审全局。

### 5.3 续跑边界

- day checkpoint存在validated delivery：先验证完整来源页及候选/目标指纹，再继续promote或恢复promoted。
- 正式文件等于已保存交付指纹：补齐本次执行记录，复用交付，不再次取源或重写正式文件。
- capture完整但未build：核来源页SHA，复用完整capture构建候选。
- capture不完整：用新attempt重新拉该日全部页；旧attempt保留，不把不同观察时刻的offset拼接。
- 已完成的其他日只做恢复必要的指纹/证据核对，不再次下载；剩余请求仍计入同一budget。
- 目标文件已被其他批次更新：旧交付不能冒充当前文件，不强行提升旧候选；明确冲突，不擅自新建执行或重置计数。
- 物化尚未完整生成：显式重新执行包含asset，按稳定文件证据复用，重新形成完整九条物化和两项checks；保留此前部分观测，不承诺数据库零新增。
- 九条物化已完整、仅check节点失败：允许只重跑实际失败节点，不新抓来源、不重做物化。物化目标、可复用的兄弟检查和0/9或0/18计数按第7节处理，不能强制该恢复run新产物化。
- 单日100次或整批350次已耗尽：原执行不再领取相应请求，不能通过原window续跑、删budget或清failed记录获得新额度；仅另一个明确获准的新补拉意图可有新预算，旧现场原样保留，不自动换身份重跑。若已有完整capture/validated delivery，只做build/promote、事件或检查恢复而不发新请求，则仍可继续，不把次数已满作为拒绝这类恢复的理由。

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

不能沿用现行helper对全部Exception统一返回`announcement_evidence_unavailable`的catch-all。缺文件/物化、schema/日期/交付规则不符等可解释的单日核验不通过，返回带具体reason的未通过结果；卷/权限/安全路径失效、写者/指纹冲突、取消以及未预期异常向框架抛出，停止当前节点，不吞成普通False。保留脱敏，不暴露SDK秘密；两个分支均有反例测试。

### 7.2 每个检查节点的输出

每个检查节点：

1. 取并校验 `context.partition_keys`，对每个day执行原schema或交付规则。
2. 查该day的目标物化。是否在本run重做asset，必须同时看asset_selection/可执行asset及`step_keys_to_execute`；后者非空且不含asset真实step key时，不因job定义含asset就误判为本次写入。实际执行asset时要求当前run；仅重新执行check时按第7.5节核对原冻结执行的本日已有物化；独立手工检查则取该day最新物化。
3. 原生发出 `AssetCheckEvaluation`，显式设置asset_key、check_name、partition=day、passed、severity=ERROR、blocking=True、metadata及 `target_materialization_data`。
4. 单日核验返回未通过且节点可继续时，仍对其余day产生结果；最后发出该check节点所需的一次 `dg.Output(None)`，让框架完成节点输出并按blocking失败决定run终态。取消、公共故障或未处理异常不属于这一继续承诺，停止当前检查节点后续日期并报告未核验范围；不能声称一个节点异常会自动取消已经并发运行的兄弟节点，整run取消仍由Dagster执行。

检查wrapper创建的AnnouncementControl必须绑定当前run的CANCELING/CANCELED状态，沿用asset的同一判断；不能使用永远返回False的默认取消回调。此control同时传入文件核验，使现有DuckDB观察线程可中断计算。Dagster执行中断异常继续向外传播。隔离测试通过真实wrapper及当前run状态替身证明取消前/首日后不再进入后续日期，并确认核验收到同一control；不以直接让audit_file抛取消异常替代回调接线验收。取消状态查询为运行控制开销，按现有观察周期执行；第15.5节按场景计算的元数据上界不含Dagster内部日志及取消状态查询，不新增配置项。

`AssetCheckEvaluation`使用本机已验证的 `dagster._core.definitions.asset_checks.asset_check_evaluation` 类型，事件由正在执行的check step yield进入正常引擎；不调用instance.report_runless_asset_event，不直写event表。内部API的使用仅封装在本数据集checks模块，并由固定版本隔离事件测试保护，不能扩散成通用事件框架。

仅yield逐日Evaluation而不发节点Output会造成缺result输出失败；仅yield一个AssetCheckResult会丢分区归属。两者均需反向回归测试。两个检查节点互不依赖，不因其中一个day失败而主动跳过另一个check。

### 7.3 两项原有规则

文件check：普通正式文件、安全路径、六列顺序/类型、日期与目录一致、全字段重复组为零；合法空日及缺URL/rec_time等不误拦。独立手工只检查时，合法文件即使没有物化记录也可通过文件规则，此时目标引用为空；交付check仍须因缺少物化而未通过。实际执行asset的同run检查及冻结执行的恢复，继续遵守当前run或原冻结物化的目标要求。

交付check：目标checkpoint属于本日、本次交付；完整capture/末页证据；来源页与目标SHA未变；计数/集合对账及保存的readback一致；核验期间最新物化及文件保持稳定。不会重新请求Tushare或Prod。

“本次交付”还须对照原物化保存的指纹，而非只对照当前checkpoint；冻结v2恢复再核原execution的每日提交证明，具体接口及历史物化两种字段见第16.3节。原纯文件CLI及独立schema-only边界保持。

目标引用必须是 `AssetCheckEvaluationTargetMaterializationData(run_id=..., timestamp=..., storage_id=...)` 对应本日物化，不能用整批最后一天的引用。读取现有events要有asset+day过滤和limit；正常全流程收尾汇总本run 9/18条事件，仅检查恢复按第7.5节计数，不增加全历史readiness循环。

沿用现有有界查询时，文件check增加每日本次物化查询一次，交付check保留每日前后各一次：九日最多27次`limit=1`元数据查询，均核对asset/day及目标run；不是扫描事件历史。不得为了收尾再重复九日readiness深查。后续若复用同一批已查结果，仍须保留交付检查的物化稳定性验证，不能只为减少次数删规则。

### 7.4 已完成的框架核验及证据边界

本轮只在隔离内存环境核验Dagster1.13.26接口，未导入正式项目defs或连接正式instance、DB、Lake：

- 单次schedule evaluate_tick返回一个范围RunRequest，partition_key=None、范围19..27、显式config保留；解析结果无需backfill daemon。补充验证asset.backfill_policy=None时，同一路径仍生成正确9/18事件及持久分区记录，故本次保留既有policy即可。
- 阅读调度提交源码确认没有强制单日partition_key；单日tag不能与range tags并存。
- 固定九日的单run产生恰好9条物化及18项检查，各日metadata和target_run_id正确。
- 证明无Output的检查节点会失败，普通AssetCheckResult在range下分区为空。
- 一个日期的交付检查返回未通过时，仍生成两个check各九条结果，兄弟检查未跳过，run最终失败；仅证明可继续的规则失败，不包括异常退出。
- check-only单日通过既有单日tag/选择路径得到两项检查、零新物化，目标绑定原物化；不新增检查专属job。独立仅checks job不能直接假设`execute_in_process(partition_key=...)`会从check specs推导分区，隔离测试必须使用真实可解析的入口。
- 已独立读取隔离instance的检查执行历史：两个check各九条持久记录，`record.partition`与evaluation.partition均为19..27且无None，run_id和target storage_id逐日正确。失败样本同样保留十八条记录，其中一个FAILED，其余SUCCEEDED。该证明只涉及临时实例，不是正式PostgreSQL或业务验收。

这些只证明框架路径可行，不证明本次公告业务代码、真实daemon/RPC提交或正式补数已经通过。未来开发必须将此路径固化到项目测试，不能只引用会话中的临时验证结果。

### 7.5 仅检查恢复及结果计数

恢复根据实际执行步骤处理，不强制每个新run都重做全部九日：

| 本次实际执行 | 新增物化/检查 | 目标与验收 |
| --- | --- | --- |
| 文件阶段失败或物化尚不完整，重新执行包含asset及两checks | 完整成功时9/18 | 文件证据复用，物化属于本恢复run；此前部分事件只保留历史，不混入本次计数 |
| asset已成功，仅重新执行一个失败check节点 | 0/9 | 本节点九日结果绑定原冻结执行的父/祖先run对应日物化，不要求目标run_id等于当前check run |
| asset已成功，重新执行两个checks节点 | 0/18 | 同上，无源请求、无文件重写、无新物化 |
| 独立单日手工只检查 | 0/所选check数 | 维持既有检查入口，只检查本日最新物化；不能据此声称整个九日执行已完成 |

先区分原执行入口，不能仅因存在parent/root_run_id就强制读取文件执行checkpoint：原根run有可验证版本2文件执行意图，或根据根自身的选择、实际steps及必要的原执行计划确实执行过公告asset时，才进入冻结window恢复。不能用当前check subset反推根run。无自动tags时，从原生root_run_id定位手工文件执行的execution；该文件应存在而缺失时明确失败，不能降为独立检查或用新的now重新冻结。每个检查节点至多有界读一次根run和必要时一份根执行计划快照，不扫描祖先或全历史；详细判断见第15.3节。

原根run本来就是独立手工check-only、从未选择执行asset且无文件执行意图时，其重新执行仍按本日最新物化检查，不要求按这个check run的root生成execution.json，也不承担九日窗口兄弟检查恢复；这条路径与普通独立单日检查一致，须有独立检查失败后再次重新执行的回归。

文件执行的检查恢复前核对固定window、各日最新物化的完整identity及交付文件指纹；原物化若已被另一批更新，不取另一批新物化来冒充原window，而是明确引用冲突。

原execution的每日phase、checkpoint和fingerprint必须保留至逐日检查，不得读取后只取identity；与原物化、当前CP的比较按第16.3节，不为此增加数据扫描。

若只执行一项check，还要验证未重跑的另一项原结果可复用：按check_key及`PartitionKeyFilter(key=day)`读最新一条执行记录，要求SUCCEEDED、正确day，且target storage_id/run_id对应本日选定物化。不能过滤SUCCESS后向更旧记录找绿灯；缺失、失败或目标不符时，在节点恢复前置核验中明确拒绝，提示显式选择需要的检查步骤，不自动扩大执行范围。

复用交付检查还必须确认来源页及正式文件仍匹配原delivery SHA；若本次选中的交付检查会执行同一指纹核验，则复用其验证，不另外重复读取。仅重跑文件检查时，来源页及文件SHA的必要核对用于证明未重跑的交付检查仍有效，不重做其集合SQL、不抓来源。独立手工单日检查不承担九日窗口的兄弟检查恢复，不增加上述整窗前置条件。

交付元数据校验按真实生产者统一：旧P2及当前日更均要求完整分页/短末页，Prod bootstrap按整月共享页规则，不根据execution_version或缺字段猜类型。普通交付与复用检查调用同一个纯元数据函数；每日实际检查按原交付SHA核对当前文件。完整规则及既有测试夹具修正依据见第15.2/15.3节，不加集合SQL或源请求。

恢复收尾区分“本次所选步骤成功”与“整个冻结九日两项检查均有效”。正常9/18、只检查0/9或0/18按本次实际步骤对账；确认窗口整体通过时，还要核对未重跑检查与同日物化目标及指纹一致。全部查询限本次九日，按第15.5节的实际场景计数：正常27次，单检查恢复最多29次，双检查恢复最多31次；另含所选结果收尾的保守最坏值为49次。相比原47，增加的最多两次仅是必要的根执行计划快照，不是新增全局扫描或运行限制。

## 8. 历史证据读取及切换

### 8.1 删除参数的实际影响

开发前window/day checkpoint的identity保存 `asdict(policy)`；checks及history/event-files直接 `AnnouncementPolicy(**stored_policy)`。旧成功物化中包含被删除的配置，若只删新类字段，会使历史检查抛TypeError并变红。旧冻结历史计划也有同样问题；本轮按下述职责拆分证据读取。

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

第16.3节的原物化指纹核验同时识别真实原生及runless生产者的已有字段，不重写历史metadata；首次生成runless物化和纯文件核验不要求预先已有物化。第16.2节的旧P2现场检查只负责拒绝自动迁移，不重新启用旧执行路径。

### 8.3 正式切换

本轮不实施。未来顺序为：隔离测试通过→列清批准的重载范围及旧活动任务→停止本公告旧入口领取新任务并让活动任务正常结束或按批准取消→重载→确认只有一个正式公告job/schedule定义→恢复原实例持久启停状态→另获准运行一次新九日job。

不同时保留两套自动schedule，不启停其他数据集，不提升全局并发，不擅自重启整机服务。旧失败run不改成成功，旧checkpoint/staging不自动删除。核验新run的执行版本、范围、1/9/18数量及物理结果后汇报。

08:00到实际创建任务之间的延迟原因仍是独立审计事项：现有记录只能排除该批run排队数小时，不能断定停机或休眠；更不能宣称单job改造已解决后台准点运行。

## 9. 测试、夹具和开发步骤

使用本工程已有.venv；无安装/升级、隐式uv同步。测试资源只用临时目录与隔离instance，禁止正式DAGSTER_HOME、正式Lake或token。夹具依据 `ANNOUNCEMENT_FIELDS`、现有source/Prod生产者及既有真实缺值样本；expected用独立字面日期/数据，不由待测函数生成。

| 测试组/落点 | 正向与反向验收 |
| --- | --- |
| `test_anns_d_window.py`、`test_anns_d_definitions.py` | 08:00 schedule只返回1请求，固定19..27；跨月/年、北京时间跨日；重复tick同key；tag冲突、D+2、错范围/版本拒绝 |
| 同上 | 计划08点实际15:35、运行超过一小时、隔日恢复均可继续；新执行无deadline检查；日期不随时钟漂移 |
| window/CLI及definitions测试 | 同一CLI window隔日续跑读取冻结时间，plan零写入；手工root_run_id恢复与独立新run区分；输入日期/间隔不符拒绝；不改变UI backfill policy、不新增无自动意图tags的DG多日range |
| `test_anns_d_execution.py`及window测试 | 中间日失败后后续日期确实被调用；最终失败摘要准确；共享故障/未知异常立即停并标未尝试，不吞错 |
| `test_anns_d_source.py` | 满页/短页/空页schema、offset、三次尝试、单次30秒与取消进程；100/350耗尽不得领取新请求、不自动换window；额度已满但完整capture/交付可无源恢复 |
| `test_anns_d_io.py`、execution测试 | 完全重复及NULL/空白/不同版本；budget/execution初始化中间退出、已消耗预算缺证据拒绝；候选失败、提交后崩溃、目标变化、已提交复用、不完整capture重拉 |
| definitions/checks隔离测试 | 单run9条物化、18项检查、各日metadata、partition及target绑定；同时读取隔离instance的`asset_check_executions`记录，两个check各九个非空且正确的partition；重复MR/空分区Result/无Output错误路径；单日规则返回未通过时其余结果仍完整，异常/取消不伪造已检查 |
| 同上 | 第4日失败但第5..9日实际尝试；成功文件保留、范围asset无假物化；同意图恢复只拉失败日并清除旧failed/reason，最终形成9/18结果 |
| checks-only/reexecution隔离测试 | 单日检查不触源、不重写文件；from-failure的asset_selection仍含asset但steps只含失败check时，绑定同window的既有物化，0/9或0/18准确；未重跑兄弟结果/指纹不可复用则拒绝；独立check-only自身的重新执行不误要文件执行checkpoint，不假绿 |
| 检查异常测试 | 可解释规则False继续其他日；资源故障、取消、未知异常不被catch-all改成普通False，停止该节点；不承诺自动取消并发兄弟节点 |
| bootstrap相关测试 | 原生产者生成的旧冻结计划/交付及新证据均按同一读法验证，fingerprint原样；删除参数不能作为新运行输入 |
| catalog/static gates | 资产/检查身份、schema、路径、end_offset保持；公告performance policy无总期限；无旧九请求、前日成功门禁、runless正式日更或共享resource行为变化 |

测试实施按项目现有实际文件继续组织，新增测试只覆盖本次必要边界，不为低风险文档变化另造测试框架。开发前确认各测试路径与授权边界。

开发顺序固定为：

1. 统一证据读取、移除总期限配置与全部消费者，先防止历史检查失效。
2. 实现稳定范围身份、单请求schedule及window逐日执行，覆盖单日失败继续、取消及手工/CLI续跑，移除前日成功门禁。
3. asset与两个checks范围和仅检查恢复适配、catalog对账和run key文档同步，保留现有手工UI backfill policy。
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

本次保留原检查语义，不新增一遍完整源抓取或全局审计。实现时显式记录各阶段输入文件/字节、SQL/请求数和输出字节；正常9/18结果完成后只做本run收尾，仅检查恢复按第7.5节实际步骤及引用收尾。

### 10.2 中断、恢复和空间

| 恢复位置 | 必要工作及开销 |
| --- | --- |
| 已完成其他日 | 文件恢复阶段仅必要指纹/身份核对，不再请求或重建候选；如果本次重新执行asset形成九条物化，后续正式18项检查仍按本次目标执行一次，并计入下列已交付分支预算 |
| capture不完整 | 新attempt重拉该日；已消耗请求不退还，旧页/JSON保留，所以预算同时含旧attempt与新attempt |
| capture完整、未形成delivery | 复核来源页SHA后构建候选；仅该日新增候选写入C_i，无源下载 |
| delivery已validated、未promote | promote及两检查，保守约F_i+2S_i+14C_i读取，rename不增加完整候选写入 |
| 目标已是已交付SHA | 恢复分支及两检查，保守约2S_i+12C_i读取，不重写正式文件 |
| 物化不完整 | 重新执行asset，复用各日交付，形成9/18；有物化重放记录，不新抓已提交来源，不能承诺数据库零新增 |
| 仅检查节点失败 | 不新产物化；只重做所选节点每日本次check，文件check约4C_i、交付check约7C_i+S_i；复用未重跑兄弟检查时，指纹稳定性最多另需C_i+S_i，已由本次交付核验完成的部分不重复读 |

上述按每个日期的真实恢复位置选择一种，不把build、promote等互斥分支叠加。重新执行asset后按实际九日正式检查计一次；只检查恢复则按所选节点计，不再追加整批审计。不能因为其中一日失败而重拉九天或默认自动重跑整批。

额外空间包括来源Parquet、三类JSON、待提升候选、checkpoint、失败attempt及DuckDB spill；正式数据增长为各日新C_i替换旧F_i后的差额。现有5GiB空闲保留是空间检查，不是总开销估算。正式执行前仅对目标日stat和已有执行记录估算这些量，不读取全历史；不能因文档有20GB spill配置就预先生成或扫描20GB文件。

### 10.3 测量与收尾

最近30天原方式已有10个成功九日批次，耗时约139—166秒；只说明当时规模，不能作为新job必须在固定时间内结束的门槛。取消的是整批期限，不取消观测及单次请求控制。

本轮隔离阶段计数、读写口径、绝对峰值RSS及失败恢复增量按第17.5节实际测量并在第17节记录；这是实现阶段验收报告，不为正式run另增性能配置或周期字段，也不取消本节记录要求。

隔离验证记录实际文件数、行数、请求与SQL次数、峰值RSS、临时文件和恢复增量；不做额外正式性能压测。本次自动目标固定九日，日常收尾为本run的9条物化、18项检查及九日文件统计；不反复审全历史。未知来源规模不预填“全部通过”，请求/空间等非时间限制触发时准确报告失败。

## 11. 授权、部署与交付

管理员本轮已授权按本LLD开发和隔离测试；按硬约束—代码—测试逐条对账，不能只以测试总数作验收。本轮不安装依赖，不访问正式源，不触发正式job、重载或修改正式实例；设计阶段框架核验不替代本轮业务实现验收。

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

## 13. 提交后完整一致性审计

2026-10-26审阅基线为`afecb8330`，修订后按R01—R10、当前代码消费者及本机框架边界再次核对。已闭合的事项：

| 审计项 | 固定结论及落点 |
| --- | --- |
| 两文档开发顺序 | 先统一历史证据读取并移除期限，再改范围执行，最后检查适配与catalog/run key对账；方案第9节与本文件第9节一致 |
| 自动与手工入口 | 自动只提交1个范围run；保留asset原backfill policy，不扩大UI/CLI范围入口；第3/4节 |
| 恢复身份 | 自动用固定tags，手工UI用原生root_run_id，CLI已有window先读冻结信息；plan零写入；第3.3节 |
| 状态与预算 | 新建/正常恢复分开，初始化中间退出不重置请求；成功清除旧失败；额度已满仅禁止新请求；第5节 |
| 检查规则与异常 | 规则未通过可以继续，公共异常/取消不被catch-all吞掉，停止当前节点；第7.1/7.2节 |
| 物化目标与计数 | 根据实际steps判断asset是否执行；正常9/18，检查恢复0/9或0/18并绑定原目标及有效兄弟结果；第7.5节 |
| 证据和读写成本 | 原identity/fingerprint保持；恢复成本按真实分支及所选检查计算，不重抓已提交来源，不另加全局审计；第8/10节 |

本次审计范围内没有待讨论的执行设计选择或前后冲突。后续开发与正式验收是明确列出的工作，不属于待补的方案决策；本结论不把计划或框架样本提升为业务代码/正式数据已通过。

## 14. 本轮实现与测试对账（2026-10-26）

2026-10-27复核：本节保留历史测试结果；未覆盖六项边界，故不再支持R01—R10全面符合性结论。缺口及获准修正统一见第15节。

按第9节顺序完成证据读取、范围执行、原生事件和检查恢复；未增加新job/sensor、配置项、业务状态表或正式入口。使用CodeGraph explore及sync/status核对入口和调用关系，并逐项阅读原代码补核同名符号、动态调用、catalog和bootstrap消费者；影响限定于公告链，无Prod/Ops/biz跨层变更。架构快照只补本链局部记录。

| 约束 | 代码落点（相对defs） | 测试与独立证据 |
| --- | --- | --- |
| R01 六字段及合并规则 | `anns_d_contract.py`证据配置拆分；`anns_d_source.py`/`anns_d_io.py`源值、分页、DISTINCT算法未改 | contract/source/io及definitions测试保留NULL、空白、版本和错类型反例；临时文件由原生产者输出，字面行数和六字段独立断言 |
| R02 一次九日 | `schedules/anns_d.py`单请求；`anns_d_window.py`冻结范围/hash；`assets/anns_d.py`使用partition_keys | definitions/window测试固定19..27、跨月/年、同tick字面key、单请求及范围tags；backfill_policy仍为None |
| R03 无整批期限 | `run_contracts/anns_d.py`移除max_window_seconds；window/checkpoint无年龄拒绝 | source/window/recovery测试超过一小时、晚启动及隔日恢复；新Policy拒绝已删除参数，旧证据字段保持原样 |
| R04 单日失败独立 | `anns_d_window.py`本域reason集合、逐日结果和汇总失败 | 中间日错误后后续日确实取源；共享/未知故障停止；同意图恢复只抓失败日并清旧失败 |
| R05 保留请求控制 | `anns_d_checkpoint.py`严格冻结预算；source原请求/分页/重试不改 | source/window_recovery验证100/350、间隔、重试、初始化中断及耗尽后无源恢复；缺/坏预算不重置 |
| R06 交付与续跑 | `anns_d_execution.py`、window保存两层promoted事实与失败信息；原IO原子提交不改 | execution/window_recovery测试rename后硬退出、promoted/file_promoted后异常或取消、指纹冲突、无源恢复和清除两层错误 |
| R07 原生按日结果及恢复 | asset逐日metadata+一次MR；`checks/anns_d_checks.py`显式Evaluation+一次Output；`anns_d_check_targets.py`核实际steps/root/同日目标 | definitions/range_checks用临时instance实读9/18持久分区和target；check_recovery用原生KnownExecutionState产生0/9、0/18；失败规则仍逐日记录，取消/框架中断向外传播 |
| R08 保留历史证据 | contract中独立FileSettings/HistorySettings；四个bootstrap消费者只取所需配置，不重写identity | evidence_settings/history_execution/events及check_recovery验证旧生产者结构、真实临时交付、原identity/SHA不变及缺字段拒绝；reused_delivery验证空/短/满页、来源引用缺失拒绝、手工根定位与外来物化拒绝 |
| R09 有界读取 | 每日文件及当前执行证据；目标查询含day及limit=1，兄弟检查只取最新一条 | source请求计数、target查询参数、缺execution时不读物化、最新兄弟失败不找旧绿；严格复用只读元数据和原SHA，不加集合SQL或源请求 |
| R10 只改公告链 | job选择、自然日分区、schema、路径和共享builder保持；catalog仅公告描述更新 | definitions/catalog合同及通用run_contract static gates/run_keys通过；正式资源未执行，其他dirty改动不纳入本提交 |

独立手工文件检查无物化时仍可通过文件规则，交付检查明确失败；冻结执行的检查恢复必须保留同一物化目标。取消回调在真实wrapper测试，状态服务使用替身；未通过改变预期或吞异常获得通过。文件证据使用实际临时source/capture/build/promote链，包含0、1、2000（满页后空结束页）、2001行，既证明缺证据拒绝，也证明合法分页不被误拦。

最终命令在orchestrator现有.venv执行，pytest使用专用系统临时目录，关闭测试缓存；临时目录在测试后清理：

~~~sh
.venv/bin/python -B -m pytest -q --tb=short -p no:cacheprovider --basetemp=<系统临时目录>/pytest tests/test_anns_d*.py tests/test_run_contract_static_gates.py tests/test_run_contract_run_keys.py
~~~

结果：**440 passed，40 subtests passed，27.09秒**。5条警告来自现有Pydantic弃用及Dagster分区检查preview提示；未安装或升级依赖。全工程`E9,F63,F7,F82`基线、本次修改Python文件默认Ruff及差异空白检查通过。

测试过程记录：首次整组发现旧history_execution测试尚未显式传day，按真实同日合同迁移调用；后来专用basetemp放在/private/tmp，使既有“非/private/tmp路径应拒绝”的反例变成合法路径，未修改其断言，改用系统临时目录后最终整组通过。另曾运行通用asset_governance_contracts组，其新增停牌专用测试因fixture模块导入失败，整组未通过；没有改动、跳过或将其计入最终440项通过结论。该组其余已运行结果也未重复累加。

证据边界：原生事件和文件链是临时资源的隔离集成验证；源响应、Prod数据库及部分run/record查找使用已有合同夹具或替身。没有当前Tushare/Prod/Lake真实读写或正式PostgreSQL事件验收；源请求/IO算法未改，故不追加真实源或大范围审计。本轮性能只验证既有次数/范围和小型隔离执行，不冒称正式耗时或实际磁盘IO测量。后续严格按第8.3节先批准重载及旧活动任务处理，再运行一次明确九日job核对结果，不用本轮开发通过替代正式批准。

## 15. 六项审计缺口修正（2026-10-27）

### 15.1 目标、依据、范围和开发顺序

管理员已批准修复F1—F6。依据为`7fa219584`当前实现及七个最小隔离反例；开工基线公告文件相对该提交未变。CodeGraph explore覆盖window、普通/复用检查、根run判断及直接消费者，源码补核动态调用、旧P2生产者和Prod bootstrap。官方API通过Context7查阅，并以本机固定Dagster1.13.26的原生run/plan对象核验实际字段，不能把旧迁移文档中的API当当前行为。

顺序：先统一F1证据合同，再完成F2/F3检查恢复和F4/F5/F6窗口安全；统一回归后做独立代码复核及逐项对账。每条反例先在未修复代码证明会失败，修复后通过；合法变化有正向测试，不用宽松fixture或过滤失败掩盖问题。

| 实现位置（相对orchestrator） | 本步职责 |
| --- | --- |
| `src/orchestrator/defs/anns_d_execution.py` | 新增统一纯元数据函数，普通verify也必须调用；不改变capture/build/promote算法 |
| `src/orchestrator/defs/checks/anns_d_checks.py` | 按日核验原交付SHA、物化稳定性；调用统一元数据函数，删除重复分页规则和整窗提前SHA循环 |
| `src/orchestrator/defs/checks/anns_d_check_targets.py` | 根自身steps/选择/执行计划判断；保持同日最新兄弟结果要求 |
| `src/orchestrator/defs/anns_d_window.py` | 原指纹优先、计数不倒退、每日及完成后取消；只读恢复也核计数 |
| `src/orchestrator/defs/assets/anns_d.py` | helper返回后、逐日metadata前及最终MR前检查同一取消control |
| 三个新`test_anns_d_*_regressions.py` | delivery_evidence、check_safety、window_safety三组实际缺陷正反回归 |
| 既有execution/exit_support、check_recovery及evidence_settings夹具 | 按原生产者补齐原先漏写的identity/分页字段，不改独立预期 |

只读本次执行的metadata、日文件及其来源页，不新增配置、表、job、sensor、resource、并发锁或入口；不改取源请求、六字段、日合并、路径、分区和其他数据集。测试只用自建临时资源，无正式DAGSTER_HOME/token/网络，无安装、部署、正式任务或补数。

### 15.2 F1：按真实生产者统一证据规则

新增 `announcement_capture_pages(checkpoint, *, page_size)` 于`anns_d_execution.py`，返回已验证的来源页tuple。函数只检查现有identity/delivery元数据，不开数据库、不算SHA、不取源、不写证据。普通`verify_announcement_delivery`、checks的路径核验/复用入口均调用它；不得从execution反向import checks。现有checks内重复的分页规则移除，不保留两套宽严规则。

生产者识别依据是互斥identity：旧P2和当前日更均为`window_id/day/policy`；Prod bootstrap为`plan_fingerprint/day/policy`。原生产者见`anns_d_window.py::announcement_day_checkpoint`、`bootstrap/anns_d_history_execution.py::announcement_history_day_checkpoint`；旧日更在`725f5a501`也已保存完整页字段。identity须为合法Mapping，日期/政策/对应身份字段完整；未知或同时含两类身份拒绝，不能按缺execution_version或缺末页字段降为bootstrap。

- 两类都要求delivery为Mapping、capture_complete严格为True、source_pages明确为list，页有非空path、严格非负整数rows、合法size/SHA256指纹。损坏/缺失元数据明确失败，安全路径和实际SHA变化仍抛冲突，不改成普通绿灯。
- 日更新旧统一要求非空来源页（0行也有一个空结束页）；page_count/source_rows/last_offset/last_page_rows为非负int且不是bool；页数等于列表长度；offset严格为页序号×2000；非末页2000行，末页0..1999行；last_offset及source_rows等于原分页公式。满页后必须有结束页。
- bootstrap继续使用整月共享页：没有日更offset/短末页要求，sum(page.rows)对照source_plan.expected_rows；expected_rows及本日source_rows同样必须是严格非负int，禁止bool。全月expected_rows=0时空页列表合法。source_rows是本日数量，不能错与整月页之和强制相等；既有月audit和来源/目标SHA规则保持，不重跑月审核或读Prod。
- 普通交付缺字段作为明确规则未通过；仅复用未重跑交付时缺证据须明确拒绝复用，不能伪造该兄弟检查仍有效。错误脱敏，取消及资源异常不吞成规则False。

已核实部分旧测试只调用write/build/promote，手工漏了真实capture生成的字段：`test_anns_d_evidence_settings.py`及`test_anns_d_check_recovery.py`缺page_count、last_offset、页rows/offset；`test_anns_d_execution.py`和`anns_d_exit_support.py`的`{day}`只是内部简化identity。按已核实旧生产者补齐这些夹具并标明依据，不为其保留未知模式放行；真实历史月生产者测试继续通过。

检查目标替身须保留本机原生EventLogRecord实际使用的storage_id、event_log_entry.run_id及timestamp；`test_anns_d_history_execution.py`原bootstrap消费样本只填了storage_id，须按原生记录结构补全，不能为简化替身放宽生产目标稳定性判断。

### 15.3 F2/F3：本日实际核验及原执行意图

F2删除wrapper在循环前对九日做完SHA的逻辑，改为每个day实际evaluator中处理。内部参数`reuse_delivery`只表达当前已确认的未重跑交付检查复用，不是运营配置。独立文件check仍可以在无物化时通过合法schema，不能误加交付要求。

仅文件检查恢复：本日加载checkpoint并调用统一元数据函数；以本次已有目标before SHA对照原delivery指纹，核来源页SHA一次，运行原文件audit一次，再核本日最新物化storage_id/run_id与所选目标一致，并用原有after SHA再次对照before/原delivery。现有`_verify_reused_delivery_references`若保留，须在实际按日路径使用并返回可复用的store/checkpoint/before，不能留下只供旧测试使用的平行核验入口。前置核验后换入合法新文件、或仅物化ID变动，均不能绿。不新增集合SQL、目标额外第三次SHA或源请求；普通/仅交付检查继续复用原交付核验。

F3当前run可以用当前job实际定义判断；判断根run不得使用当前check subset代替根的事实。先采用已验证版本2执行tags，否则用根自身实际step_keys_to_execute、resolved_op_selection及显式asset_selection；明确矛盾或仍不明确时，每节点至多读取一次根execution_plan_snapshot_id对应的原生执行计划快照。该快照的asset_selection/asset_check_keys须按原实际step范围得出，不能把计划中未执行的asset算作执行过；有原公告asset则进入文件恢复，只有原公告checks则为独立检查。缺快照、未知实体或证据仍不明确时明确拒绝，不降级；不扫描祖先或历史。

原生全job运行的asset_selection可能为空集合，但当前真实steps仍含asset；当前run须以实际steps及其job定义判断，不能先被该空集合排除。相反，只有checks的steps仍不能被当作写入；两种形态都有原生回归。

重新执行以根意图为准，child tags不能另定义执行：根有已冻结版本2意图时，采用根tags并拒绝child显式提供的窗口、版本、起止、计划时间或automatic与根不一致；根是无tags的手工文件执行时，按根身份及持久execution恢复，并核对child显式提供的意图字段，不能注入另一个合法窗口；根是独立检查时，也不能由child额外tags把它变成另一批文件执行。同一冻结意图的正常恢复必须通过。新增A根/B子窗口及手工根注入窗口的反例；只用已取得的根/快照/同一execution，不增加祖先或全局查询。

原根run三项选择字段全None是合法全job形态，须用其实际冻结计划正向证明，不能一律误拦；原生check-only计划也须正确识别。文件根应有execution而缺失时仍拒绝，不能以新的now另建；兄弟检查继续按同日最新一条、成功、同target判断，不向更旧绿灯回退。

### 15.4 F4/F5/F6：提交事实、请求计数和取消

F4在每日开始保留完整previous记录。若原window已promoted，异常路径始终保留原checkpoint/fingerprint，仅另记failure_phase/reason；发现CP指纹冲突后也不得导入其新值。只有原window无提交事实、确已进入day helper且预期日CP持久存在时，才重读并核完整identity/contract_version、promoted、统一capture证据、合法指纹及实际目标SHA一致后补记。补记失败不复制其指纹或路径到原事实，不改日CP、不取源、不执行集合SQL；额外读取仅异常当前日一次目标SHA。原rename后尚未保存promoted的恢复仍走既有validated/物理指纹路径。

F5新execution显式初始化requests=0/day_requests={}。已有执行先严格读取两份文件，验证execution计数字段类型、总/逐日求和及day键合法，再要求budget总数和每个day计数均不低于execution；预算合法领先必须允许。全部通过才更新active_run/phase、recover_interrupted或领取请求。只读restore入口及每次覆盖执行摘要前也做同样比较；失败前两份文件保持字节不变。原版本2初始化在两次原子写之间退出的现场，仅当execution.phase=planned、各日均planned、两计数字段同时缺失且预算0/空逐日数/in_flight=False，才在内存按0解释；其余缺字段、部分字段或已有消耗都拒绝，不自动重建配额。

F6每日领取前、file_promoted后及最终完成日志后检查同一control。领取前取消不改该planned日为已尝试；保留已提交日并把窗口记为cancelled。asset在helper返回后、每次metadata前及最终MR前检查，已可见取消不继续物化。若helper已正常返回后取消才在asset被观察到，execution.files_completed保留真实文件阶段事实，run按取消终止，不为此另开窗口文件写入口；仍不新增物化。恢复只核已提交证据、不重取来源，成功时清旧取消/失败信息。

### 15.5 正常、中断及收尾预算

纯元数据函数最多遍历本执行已有页（每日请求仍≤100，整批≤350），无额外源/Prod查询、SQL、SHA或写湖。F4只在无原window提交事实的异常补记分支增加当前目标一次SHA≤C_i；已有原指纹分支不新增读，错误证据不反复重读。F5/F6只读写本窗口小型JSON，正常Parquet写入/空间不变，不恢复已提交文件备份。

| 查询场景，九日 | 目标/兄弟/根/必要快照 | 另留所选结果收尾 | 保守合计 |
| --- | --- | --- | --- |
| 正常全流程 | 27 | 18 | 45 |
| 仅文件检查恢复 | 18目标/稳定+9兄弟+1根+1快照≤29 | 9，兄弟已核不重复 | 38 |
| 仅交付检查恢复 | 同上≤29 | 9 | 38 |
| 两检查恢复 | 27目标/稳定+2根+2快照≤31 | 18 | 49 |

根选择本来明确时不读快照；上表为必要最坏场景，不要求为了达到预算增加查询。原47的推导未含新增两份必要根计划快照，现明确最坏49；这只是成本测算，不新增运行限制。运行取消和框架日志查询另属既有控制开销。

仅文件恢复的目标读取由原前置SHA加file检查的5C_i+S_i降为4C_i+S_i：before/after两次目标SHA及原文件SQL核验保留，来源页SHA一次；仅交付、全流程及其它恢复按第10节原分支预算，不增加全局收尾。F4异常补记的C_i只加一次到该日异常分支，不与所有正常分支混加。

隔离验收使用0/1/2000/2001行以及最多九日的原生产者临时样本；既有历史回归仅使用本地月fixture，不读取正式历史。专用测试目录预算≤256MiB、正常一轮约一分钟，失败只重验受影响组，最后统一回归一次并清理本轮临时目录；这不是对正式job新增超时或空间限制。无性能压测、依赖安装和额外全局审计。

### 15.6 验收及失败处理

新增三组回归分别覆盖F1、F2/F3、F4/F5/F6。每项都保存旧代码会失败的证据，并有相应正向：完整新旧日更、空/满页/末页；真实bootstrap整月/空月；同目标稳定SHA；原生根选择None及原计划；预算领先/零初始化；提交后日志失败恢复和取消后无源恢复。

反例须使用真实临时生产者及独立字面预期，明确损坏输入；F2保留真实wrapper/evaluator和实际文件替换，不用返回False的mock代替被验收层。F3使用原生Run/冻结Plan和实际from-failure；状态/记录查询如用替身须写明边界。错误证据被拒绝不能写window新事实；未知/缺证据、权限、SHA冲突、取消按原异常类别停止，不放宽规则或自动重试。

步骤验收：先确认七个原反例在未修复实现失败，再完成各自必要回归；统一运行公告全组和既有run_contract static gates/run_keys、Ruff及文档完整性。之后由不改该模块的审阅者复核生产者/消费者和六项代码—测试对账，再更新结果；任何失败先查实际合同，不改预期迎合实现，不触正式资源。未执行的正式验收明确保留到第8.3节。

### 15.7 实现、反例与隔离验收结果

后续复核更正：下述测试及次数保留，但发现asset恢复入口未核root、检查未绑定原execution/物化指纹。其修正由第16节承接，本节历史独立复核“未发现剩余阻断”不再是当前整体结论。

本轮只修改第15.1节的五个生产代码文件，新增三组回归并修正五处既有测试/替身；schema、source、IO、run contract、路径、job/schedule和共享resource源码未改。两份原文档及README公告索引同步；未提交、部署或操作正式资源。

| 修正 | 最终实现 | 关键回归（test_anns_d前缀） |
| --- | --- | --- |
| F1 | execution的`announcement_capture_pages`统一日更/月证据；verify及checks均接入；旧重复页validator移除 | delivery_evidence_regressions：正常入口缺来源/末页、各计数及页类型错误；0/1/2000/2001行、新旧日更原字节、未知/混合身份、真实月2行/单日1行/空日及空月 |
| F2 | `_verify_reused_delivery_references`在实际当日使用并返回store/checkpoint/before；after与原SHA、最新物化均核对 | check_safety_regressions：预验后/返回helper后换合法文件、只换物化ID；正常路径实测两次目标SHA、一次源SHA、一次原audit及一次末尾物化查询 |
| F3 | 当前run按其实际steps/定义；根按自身事实和必要冻结plan；根与execution决定六项身份字段，child不能改窗口 | check_safety_regressions：原生None/空集合选择、三字段皆None的真实plan、独立检查plan、未知/缺plan拒绝；真实from-failure不重做asset且绑定父目标；三种根被子窗口覆盖及12个身份字段冲突反例，同意图正向 |
| F4 | window优先复制并保留原提交证明；原记录未知才严格补记，异常当前目标最多额外SHA一次 | window_safety_regressions：连续冲突仍保留原A/日CP字节；坏identity/缺页/坏SHA/变目标均拒绝补记；有效补记及后续无源恢复 |
| F5 | initialize、只读restore及save前同一计数校验；总数/逐日不退，预算合法领先允许 | window_safety_regressions：两种倒退及execution非法计数拒绝前两文件字节不变；领先in_flight额度不退；零初始化中断及已消耗缺字段边界 |
| F6 | 领取前、每日提交后、最终日志后及asset物化前检查同一control；未领取日保持planned | window_safety_regressions：首日/末日/最终日志等4个取消阶段及asset3个边界；已提交指纹保留、未开始日未尝试、恢复无源；helper正常返回后的取消保持文件事实 |

先在旧行为取得真实失败：F1两例，F2/F3四例，F4/F5/F6十例，独立复核补出的根/子意图覆盖三例，合计19例；未把收集错误或简化fixture缺字段计作缺陷回归证据。新增共92例（delivery40、check29、window23）。修正后原七个反例均有对应期望拒绝/取消/事实不变的回归，合法变化也通过。

最终在现有orchestrator .venv、专用系统临时目录执行一次统一回归：

~~~sh
.venv/bin/python -B -m pytest -q --tb=short -p no:cacheprovider --basetemp=<本轮专用系统临时目录>/pytest tests/test_anns_d*.py tests/test_run_contract_static_gates.py tests/test_run_contract_run_keys.py
~~~

**532 passed，40 subtests passed，35.26秒。** 这是同一最终命令的去重结果，不累加各阶段重叠组。5条警告为现有Pydantic弃用和Dagster分区检查preview。全工程致命错误Ruff基线、全部本轮Python文件默认Ruff、差异空白及文档完整性检查通过。生成数据、staging及DuckDB工作文件随本轮专用目录清理；不清理正式或其他任务文件。

独立代码复核由未编辑相应模块的审阅者完成：旧P2/当前/Prod生产合同、统一函数及夹具真实性、F4/F5/F6错误顺序和计数、F2按日稳定性、F3根及子意图均未发现剩余阻断。CodeGraph explore及sync/status覆盖入口、消费关系和最终索引；同名符号及动态调用已补读源码。仍无跨子系统依赖或对外合同变化，不另造架构/恢复框架。

测试中唯一的既有消费者夹具问题是bootstrap记录替身缺真实EventLogRecord.run_id字段，按15.2补全后通过，没有给生产代码加getattr兜底。当前run空asset_selection的原生形态由真实运行证据确认后修正，并保留只执行checks的反向；没有改断言迎合错误行为。

本轮证据限代码和隔离集成：文件生产/替换/audit及原生plan/from-failure为实际临时执行，源响应、部分run/record查询和取消状态为已说明替身。没有读取正式历史或当前源、没有正式PostgreSQL事件验收，未据小样本宣称正式吞吐。正式重载和任务仍按8.3另行批准；本节不替代该批准，也不声称08:00后台延迟已经解决。

## 16. 两处恢复遗漏的修正（2026-10-27）

本节记录上一轮仅修前两项的范围及结果，当时未处理事项由第17节承接；不能继续用本节的历史待办表述推断当前完成状态。

### 16.1 目标、依据和范围

管理员仅批准先修继续审计的前两项：asset恢复改换原窗口，以及检查未核对原窗口/物化保存的指纹。原反例使用真实临时asset、文件生产和evaluator，run/源查找为替身；原物化含真实asset完整metadata，不能把问题归因于简化夹具。沿用第3.3、7、15.3节的原意图和本次交付要求，先完成本节后编码。

CodeGraph explore定位asset→window/day helper、check targets→evaluator→delivery verify及CLI/bootstrap消费者；最终逐项补读当前源码，旧P2以`725f5a501`的真实生产者核验。框架依据通过Context7查[官方执行API](https://dagster.io/docs/api/dagster/execution)，root/partition/config以本机固定1.13.26字段及原生执行验证。没有跨工程、跨业务子系统依赖或公共API契约变更。

只改`defs/assets/anns_d.py`、`defs/checks/anns_d_check_targets.py`、`defs/checks/anns_d_checks.py`，新增内部`defs/anns_d_run_intent.py`承接已有根执行判断，并修改对应隔离测试；window、budget、source、IO及bootstrap算法复用不改。原判断位于checks内，asset不能反向导入checks；window负责文件执行，故将已有Dagster根选择/原计划判断迁出共用，不复制两套逻辑，不增加执行入口或通用框架。禁止新增job、sensor、resource、配置、表、入口、源字段或文件扫描。第三项原生中断分类、10.3逐阶段IO/SQL与峰值RSS记录、第9节九日第4日失败后完整恢复组合验收仍待办，不在本轮编码范围，也不能宣称全部LLD验收完成。

### 16.2 包含asset的恢复入口

在asset内增加私有`_announcement_asset_window_tags(context, days, policy, staging)`；在`control.progress`、store、call及execute helper前调用，不能从asset反向import checks。返回核验后的原tags，后续窗口初始化、预算与文件逻辑仍由现有helper负责。

1. 独立新run沿用现有单日手工或完整tags入口，全部显式意图字段仍应核验；不能丢掉缺window_id时的部分冲突tag。手工自动标记由既有producer省略，不能创建新的`automatic=false`执行格式。
2. 子run最多按原生`root_run_id`读一次原root；缺root明确拒绝。原日期来自根自身`dagster/partition`，或完整成对的分区range标签；二者冲突、缺半边或与当前days不符均拒绝，不能用child日期计算新manual hash。
3. 原interval只读根`run_config.ops.raw_tushare_anns_d.config.interval_seconds`，未配置按原`AnnouncementRawConfig`默认5；经现有Config/Policy校验，与当前policy相等。其余policy仍由现有窗口初始化对照已保存identity，不能只比window_id。配置来源、持久化及消费者未变，不读取resource或秘密配置。
4. 根有完整v2公告tags：用`announcement_window_identity(days, root_tags, root_policy)`核原日期、时间、版本、automatic及窗口；子显式提供的六字段逐项对照原意图，始终使用根tags。已冻结时由原initialize验证原execution/budget；尚未初始化允许按原tags创建，不能因无execution误拦，也不能让restore的无证据fallback生成新now。
5. 根无window tag的手工单日：先核根日期及同一root的旧现场，再调用原`announcement_manual_window_tags(root_id, first,last,staging,policy)`。有execution或合法零预算沿用原时间及计数；两文件均无且没有遗留证据才首次记录时间。已消耗budget缺execution、execution缺budget和旧证据拒绝仍由原helper执行。对根及子所有显式身份字段核对，禁止部分tags被丢弃。
6. 旧P2手工根window_id为原root id，日目录为`sha256(f"{window_id}:{day}")[:32]`（旧window70—77）。只对这一root和原日期的旧window `admission.json/budget.json/execution.json`及对应日`delivery.json`做安全路径存在性核验，发现即拒绝自动迁移；不读取全staging、不恢复旧执行器、不清理或归零现场。

7. 根无完整固定窗口意图时，还必须证明原根选择过公告asset。只选checks的根不能在子run加入asset。本机1.13.26的`_reexecute_job`在不传step_selection且parent.asset_selection为空时会按传入full job创建全steps；已用实际check-only父执行及同名full job隔离验证，子run确实启动asset，所以不能依据API说明中的子集表述省略本检查。

将targets既有`_root_file_intent/_root_snapshot_file_intent`迁至`anns_d_run_intent.py`，保留同一语义：内部`announcement_root_file_intent(root, *, instance, asset_step_key)`先用根自身选择/实际steps，冲突或不明确时至多读取原根一份冻结计划；未知、缺计划或非本资产仍拒绝。targets用现有实际step适配器调用；asset用自身真实step名调用，不能用当前full job代替原根选择。已核合法v2固定意图的根保持原规则；原根确含asset但初始化前失败仍允许。此迁移不重写root分类、不增加其他数据集消费者。

冲突在任何写入前抛出明确错误，原预算、窗口、CP和目标文件字节不变，不建B窗口、不取源。合法恢复继续受原350/100计数和零初始化规则约束；新独立root仍可形成新观察。失败不自动重试或另换身份。

### 16.3 检查使用原物化和原每日提交指纹

真实合同：当前及旧P2原生asset由delivery写出`goldenshare/fingerprint`；`bootstrap/anns_d_events.py`的既有runless物化写`goldenshare/announcement_file`，既可对应日补拉也可对应月初始化，不能仅按identity类型挑key。在targets内集中提取原物化指纹：至少一种存在，size为非负int且非bool，SHA为合法64位十六进制；两key同时存在必须各自合法且相等。缺失/错型不从当前CP反填；双字段冲突明确拒绝。

- `_frozen_check_window`保留本次已经读到的execution.daily记录，返回identity和`execution['days']`。`AnnouncementCheckTargets`增加内部`window_deliveries`，无冻结窗口时为None；`prepare`验证每日本来已经promoted、checkpoint为原window/day推导路径、fingerprint合法且与所选物化指纹一致。缺/坏/冲突停止，不回填execution，不额外查祖先、历史物化或文件。
- wrapper逐日把原日指纹经内部`expected_fingerprint`参数传给evaluator。`_delivery_evidence`在统一页合同之后比较当前CP.delivery.fingerprint、原物化指纹及已传的原日指纹；普通交付和复用未重跑交付均使用它。current CP变成完整B仍不能绕过原A证明。
- 真实执行asset后的同run文件check使用已有目标before SHA对照该日物化指纹，不新增CP/来源读取。冻结仅文件恢复继续完整复用交付核验。独立schema-only（包括无物化）仍只做原文件规则，不能强加交付门槛。普通旧P2交付和合法history/runless物化可按原证据检查，不因无v2 execution拒绝；只有明确的v2冻结恢复要求原窗口日证明。
- 原`verify_announcement_delivery`纯文件helper及首次历史runless事件准备不要求事先存在Dagster物化。全部实际文件核验沿用已有before/after目标SHA、来源SHA及audit；不增加第三次目标SHA、不加SQL或取源。原最新目标storage_id/run_id稳定和最新兄弟检查要求保持，不向更旧绿灯回退。

缺失/非法物化证据使普通交付明确未通过，冻结恢复或复用明确停止；两指纹、CP路径或原日提交冲突向外抛出，不吞成绿灯，不修改业务或证据文件。记录查询替身必须保留真实run_id/timestamp/storage_id。既有简化Mat补入真实producer指纹，并独立以文件stat/SHA核对；负例必须保留有效原Mat，不能因缺字段提前失败而虚称抓住本次错误。

### 16.4 成本、恢复和测试边界

| 场景 | 本步新增工作 | 源请求、DuckDB SQL、数据文件读写增量 |
| --- | --- | --- |
| 独立首次asset | 验证已有tags，手工保留现有恢复调用 | 0 |
| 包含asset重执行 | 至多1次root查询＋必要时1份原执行计划；本root旧P2的固定少量路径存在性核验；原restore的JSON读取保持 | 0 |
| 普通两checks及历史交付 | 已读Mat的最多两份指纹与当前CP比较 | 0 |
| 冻结仅检查恢复 | 在已读execution内保留每日提交记录并比较，最多九日 | 0 |
| 冲突/中断后继续及收尾 | 冲突不写、不自动重试；合法继续沿用原分支；收尾不另做文件审计 | 0 |

现有正常检查查询上界45、两检查恢复49及单检查恢复38不变（15.5）；仅包含asset的重执行在对应原预算上最多增加1次root及1次必要原计划查询，取消观察查询仍单列。metadata比较复杂度为目标日期数（自动9日）、来源页数沿用原350次上界；不新增长期内存、临时空间、quota、超时或运行限制。JSON校验不声称替代已批准原文件核验；本轮无正式业务读写。

隔离使用现有.venv、临时Lake/staging和临时Dagster instance，源响应/run查询替身明示；正向原生恢复使用实际固定框架和临时事件库。0/1/2000/2001行及至多九日复用已有测试范围，专用临时资源≤256MiB、单次统一回归预计一分钟内（非强制超时）。先定向红/绿，失败只重验受影响组，最终统一公告组和run_contract两组一次，加Ruff、文档及空白检查；删除本轮临时生成数据，保留小型报告，不清理正式或其他任务文件。

### 16.5 代码—验收清单

| 硬口径 | 代码位置 | 正向/反向验收 |
| --- | --- | --- |
| asset原root意图在写前固定 | asset私有tags入口 | 完整B、缺window的部分六字段、日期、policy、缺root全部拒绝；根预算/文件不变、无B写入/源请求 |
| 正常恢复不误拦 | 原window helpers调用 | manual/automatic同root、原初始化前失败、合法零budget中断及已消耗原预算续跑；独立新root重新观察 |
| check-only根不能升级为asset执行 | 共用原根选择/原计划判断 | 原生check-only父＋同名full job重新执行在写前拒绝；原生文件父正常恢复、空选择/未知字段用原计划核验；缺证据拒绝 |
| 旧现场不能变新意图 | asset固定旧root路径核验 | 旧admission或旧日CP拒绝且不改字节；无旧现场的正常manual可运行 |
| 原物化独立指纹生效 | targets提取、checks evidence | 真实asset产生A Mat，换完整B delivery仍拒绝；两字段合法各自通过、缺失/坏/两字段冲突拒绝；合法旧P2/history/runless不误拦 |
| 原窗口每日提交不能丢 | targets及wrapper expected_fingerprint | 原execution A与Mat/CP B冲突拒绝；缺日/未promoted/坏checkpoint或指纹拒绝；仅文件及两checks恢复合法通过 |
| 不增加数据读取、不扩大门槛 | evaluator及原纯文件verify | 仅文件恢复仍2次目标SHA/1次源SHA/1次audit；独立无Mat schema通过、无Mat交付未通过；真实含asset from-failure及原两类恢复接线 |

完成后记录旧实现真实失败证据、最终同一命令结果、实际临时清理、独立复核和仍待事项。未执行正式源/数据库/instance读写，不能以隔离通过宣称正式验收、全部LLD符合或08:00延迟已解决。

### 16.6 实现、旧行为反例与最终结果

本步先完成16.1—16.5，再修改代码；原生框架可将check-only根用于full job的边界，在实测确认后先补16.2第7项及相应预算，才继续补入共享判断。两位未编辑相应模块的审阅者完成原合同、最终代码、正常变化和测试真实性复核，本步两项范围内未发现剩余阻断。

| 硬口径 | 最终实现和证据 |
| --- | --- |
| 资产恢复沿用原任务 | asset的`_announcement_asset_window_tags`在control/store/helper前核根日期、原interval、六项完整或部分tags；A根/B子、部分tags、改日/改配置/缺根均拒绝且源/原文件/预算不变 |
| 根只选检查不能加入asset | 新`anns_d_run_intent.py::announcement_root_file_intent`承接原targets判断，资产及checks共用；真实公告check-only父、同名full job、真实`_reexecute_job`且父子均默认5秒，具体因`announcement_root_asset_not_selected`拒绝，零源请求、Lake/staging文件不变 |
| 合法文件恢复保留 | manual/automatic、原初始化前失败、零预算中断、已消耗预算、原固定tags及独立新root正向；真实文件父from-failure必要原计划读取恰1次，原请求3次失败后仅再请求第4次成功，保持同window并生成子run的1条物化/2项成功检查 |
| 原指纹独立核验 | targets提取原生`fingerprint`或runless`announcement_file`，双键必须合法相等；checks核CP/Mat/expected，A Mat配完整B交付仍拒绝；缺失、非法、冲突及历史格式正反例通过 |
| 原每日提交记录保留 | targets保留并核原execution的日phase/checkpoint/fingerprint，wrapper经`expected_fingerprint`传至当日evaluator；原日证明与物化、CP不一致拒绝，不读文件回填原证明 |
| 原读取及消费者边界保持 | F2仍目标SHA两次、来源SHA一次、audit一次；同run文件检查复用before指纹；独立无Mat schema、旧日更、history/runless及纯文件CLI回归通过，没有新增源/Prod或DuckDB数据查询 |

新增`test_anns_d_asset_reexecution.py`33项和`test_anns_d_materialization_binding_regressions.py`20项，共53项；原六项修正的92项仍保留。新缺陷先取得6项真实红灯：资产窗口/部分tag两项、实际A物化/B完整交付两个入口及原窗口指纹冲突三项、真实check-only根升级一项。红灯均为应拒绝却继续执行/通过，不是缺字段、收集或配置先行失败。

既有5份夹具按真实生产者补齐原物化指纹及窗口日证明：reused_delivery、check_recovery、history_execution、definitions、check_safety；真实文件指纹用独立stat/SHA核对，不调用待测提取函数生成expected。原生九日事件恢复测试仍替换文件evaluator，只证明事件接线；本步没有借此宣称已补齐九日第4日失败业务组合验收。

最终同一命令（orchestrator现有.venv，独立系统临时目录）执行：

~~~sh
.venv/bin/python -B -m pytest -q --tb=short -p no:cacheprovider --basetemp=<本步专用系统临时目录>/pytest tests/test_anns_d*.py tests/test_run_contract_static_gates.py tests/test_run_contract_run_keys.py
~~~

结果：**585 passed，40 subtests passed，38.47秒**。这是一次去重最终结果，不累加定向155/79/21等重叠测试。5条警告仍为现有Pydantic弃用及分区检查preview。全src/tests致命错误Ruff基线、本次及此前六项修正涉及的全部Python默认Ruff、文档完整性和差异空白检查通过。CodeGraph完成explore、最终sync/status，索引有效；新共用函数及两入口已人工补核，没有跨业务子系统、其他数据集或前端/API消费者变化。

临时清理：最终统一回归目录`anns-d-two-fixes-final-20261027.ACyDeL`内4,125个文件、7,779,599字节已删除，确认目录不再存在；两定向组也清掉Parquet/DuckDB/checkpoint及临时instance，仅留小日志。正常source/IO算法未改，未读当前正式源/历史业务数据、未安装依赖、未重载DG、未跑正式job/check、未提交。静态/隔离通过不替代正式PostgreSQL或源站验收，第三项中断分类及16.1两项验收缺口继续待办。

小型证据：`/private/tmp/anns-d-two-fixes-20261027.4WIZPh/pytest-final.log`、`/private/tmp/anns-asset-reexecution-VzzzzA/`及系统临时目录`anns-mat-binding-aamfppr9`下的red/green日志；只有日志保留，不保留测试数据，正式文件和其他任务目录未清理。

## 17. 中断分类及隔离验收收尾（2026-10-27）

### 17.1 目标、当前依据与范围

管理员已授权完成第三项中断分类、10.1/10.3阶段读写/SQL及RSS记录、第9节九日第4日失败后完整业务恢复组合。先完成本节并复核，再编码；不是以增加测试数量替代原要求。保留第15—16节全部指纹、原意图、预算不退及取消边界修正。

CodeGraph explore覆盖`AnnouncementControl`、day/window、asset/check、历史消费者及测试。当前源码证据：day104和window475/652只识别主动取消/KeyboardInterrupt；window初始running保存及最终摘要还在原逐日捕获之外。本机固定Dagster1.13.26 `errors.py:32`直接将原生中断定义为BaseException，`raise_execution_interrupts`将信号转换为此异常；Context7官方API仅作框架依据，真实行为以本机原生测试核实。源调用父进程已有finally回收子进程，Store.connection已有finally关闭连接/观察线程，checks不会把该BaseException吞成规则False，不重写这些算法。

生产修改位置限定`defs/anns_d_checkpoint.py`、`anns_d_execution.py`、`anns_d_window.py`、`bootstrap/anns_d_history.py`和`anns_d_history_execution.py`。新增取消回归、`tests/test_anns_d_nine_day_recovery.py`及只在测试导入的测量支持/用例；不增加生产metrics功能、配置、job、sensor、resource、表、公共入口、字段或source请求。无跨子系统、Prod、前端/API消费者变化。

### 17.2 三类取消统一，保留原异常及提交事实

在已有`anns_d_checkpoint.py`集中内部取消异常tuple，仅含`AnnouncementCancelled`、`KeyboardInterrupt`和固定Dagster的`DagsterExecutionInterruptedError`。day和window的catch/isinstance及两个历史公告消费者引用同一tuple；不将所有BaseException当取消，不包成普通AnnouncementError，也不吞异常。单日白名单继续后续日期、未知普通错误停止的规则保持。

`update_announcement_day`用统一tuple调用原`_record_day_failure(cancelled=True)`后原样raise。已有promoted日CP保留原phase/delivery，另存failure_phase；未提交日记cancelled，不删来源页、候选或budget。历史两个取消catch只换同一tuple，已有月捕获/交付/SQL与范围不变，测试用本地fixture和替身，不读Prod。

窗口外层保留identity、store、原execution.lock及`_initialize_execution`。仅将身份/计数已核通过后的原活动体提为私有`_execute_announcement_window_locked(state, state_path, budget, *, control, first_store, policy, store_factory, call_factory)`，原日期/身份由state取得；初始化两文件原子恢复规则不改，尚未取得合法state不伪造取消摘要。

- 外层在原lock内捕获统一取消tuple，保存window.phase=cancelled、按原日记录重新汇总、输出既有摘要，然后原样raise；覆盖初始running保存/日志、每日前后、已提交后及最终保存/摘要。原异常对象不能变，不能以日志成功声称数据已成功。
- 原`_record_window_failure`取消分支只准备当日事实并返回停止；window取消的save及摘要统一由外层执行一次，避免内存phase已改却误认落盘完成。普通失败仍按原分支save/停止/继续。原末尾单独取消catch并入外层，不保留重复收尾。
- 原无提交事实时的F4持久CP/目标核验仍保留；该核验期间原生中断也须进入取消收尾，不能被只catch Exception/KeyboardInterrupt漏掉。已提交记录始终优先，不采纳冲突指纹。
- 未领取日保持planned；中断不能领取下一页或下一日，原请求不退，已完成文件不回滚。恢复仍用原身份/预算，成功后清旧失败/取消信息。初始化前与资源不可用边界沿原规则，不新增自动重跑。
- 再次信号或写盘本身故障可能阻止最后摘要持久化；不能承诺SIGKILL也能写状态。原子文件与预算仍为后续恢复依据，不为此新增备份、删除或新的恢复执行器。

正常0额外请求/SQL/SHA/正式文件写入；取消沿原day CP保存，window统一必要小JSON一次，不重复取消save。原F4异常补记已有一次当前目标SHA预算保持，不扩成九日重审。

### 17.3 中断与正常变化的验收

先在未修实现取得首日源内、已提交后及启动/最终收尾的原生中断反例；修正后同一异常原样抛出、window/day按实际阶段取消、后续未领取、已提交FP/CP及额度保持。覆盖原KeyboardInterrupt/control取消、SystemExit/GeneratorExit/RuntimeError及原单日白名单，证明不误归取消或误阻后续日期。

使用临时实际job核原生中断传播；至少一项专用测试子进程内由SIGINT经本机`raise_execution_interrupts`转换，绝不信号父测试、正式服务或其他进程。真实spawn sleeping_worker验证原finally回收，结束后无本测试新增active_children。内部证据核验中断、初始running保存/日志、最后files_completed保存/日志也须覆盖；仅测旧取消回调不能代替原生类型。历史两消费者定向native反例使用原月合同fixture，无真实DB。测试子进程限本测试持有PID，timeout只防测试挂起，不新增生产运行限制。

### 17.4 九日失败、继续与同root恢复的完整业务验收

固定字面日期2023-06-01..09、计划日2023-06-08 08:00 Asia/Shanghai，使用原schedule tags、range及显式interval=0。绑定实际`raw_anns_d_update_job`、原asset和两checks，仅测试中换in_process executor；仅替换源响应与正式卷可用性。真实capture/build/promote、guard/root/config、evaluator、原生事件、持久引用均不得mock。

源每次返回合法空六字段页；首轮仅06-04返回缺rec_time的五列schema，让真实归一化报错且不触调用失败重试。首轮字面源请求顺序九日各一次，window attempted=9、completed=其余8日、failed=[04]、unattempted=[]；execution/budget总数9、各日1、in_flight=False。04无目标，其余8个空Parquet合法；原run FAILED、0 Mat/0 CheckEvaluation，两个checks没有STEP_START。独立记录8个目标的ino/mtime_ns/size/SHA及来源页集合。

以真实KnownExecutionState及原run config/tags构建同root的from-failure plan/run并实际execute，不手拼待修股票/日期或替代文件helper。只将04源响应改合法，新增源请求只能04一次；原identity不变、总请求9→10、仅04日1→2，其余八日计数不变，不退款或归零。透传观察原os.replace，不改变其执行，证明恢复期正式目标仅替换04一次；其余8日ino/mtime/hash及来源页集合不变。小CP正常重存不要求字节不变。

子run SUCCESS，failed/reason清除，恰9条Mat及18项实际CheckEvaluation、每日期两项passed。按9日取得临时instance物化，核partition/run_id、CP和原指纹与独立文件SHA；18项target storage_id/run_id/timestamp各自匹配本日Mat，持久check history各9条、日期非空且SUCCEEDED。仅查询本2个run/9日，不扫事件历史或其他数据集。

### 17.5 只在测试测量，逐阶段记录并区分口径

本步落实10.1“实现时记录”和10.3“隔离验证”的原要求，不删减它们；原文没有要求为正式run新增持久性能字段，因此无需修改Store、全局DuckDB连接或历史读取器生产逻辑。新增测试支持`tests/anns_d_measurement_support.py`，测试入口`test_anns_d_acceptance_measurements.py`及必要本地测量用例。参数显式传临时目录和报告路径，不新增环境配置或pytest公开CLI参数。

测量运行于全新现有.venv worker，清除DAGSTER_HOME/TUSHARE_TOKEN并显式临时资源。执行一次普通分页/合并样本（最多2,001源行、已有1行）及17.4九日失败恢复用例；包括真实file/delivery checks和仅检查恢复的必要分支。worker内每用例测量一次，最终统一回归可能再次验证同用例，这是隔离内存测量及回归的分开证据，不能累计为更多业务覆盖。无正式源、无性能压测、无重复全局数据审计。

| 观测对象 | 实现及验收口径 |
| --- | --- |
| 阶段 | 测试上下文标capture/build/promote/file_check/delivery_check及run/attempt；嵌套audit归外层，不重复汇总；准备和独立验收读数单列，不混入算法消耗 |
| SQL/API | 透传包装`duckdb.connect`返回的真实连接；execute原样执行、返回原结果，setup和业务计数分开。settings验证1条、Store两条SET单列（普通Store每连接3条setup）；read_parquet/read_json和relation.create_view分列API，不当作物理scan次数。不执行EXPLAIN、额外SELECT或改变SQL |
| 已有SHA读取 | 观察原fingerprint的rb read，累计真实len(chunk)，fsync只打开不读计0；不自行再算一遍SHA。独立测试断言读取另列，不能隐藏在算法数字中 |
| DuckDB输入 | 对实际已知relation/参数中的输入路径只stat，记录唯一文件数/size及逻辑引用模型；native物理磁盘读取标未测，不将size、绑定次数或SQL数冒充实际读取字节/扫描次数 |
| 输出及提升 | 对原COPY/JSON完成路径stat，分列Parquet输出、JSON现场和os.replace提升；rename是移动已写文件，不再算一份完整新写。不得为了测量额外读取输出内容 |
| 临时资源 | 只遍历本轮临时根的元数据，区分逻辑size/分配空间、阶段边界和恢复新增。短暂spill若仅边界/定时采样，只能报采样最大值，不能冒称精确峰值 |
| 内存 | worker结束记录resource.getrusage(RUSAGE_SELF).ru_maxrss的绝对峰值，macOS为bytes、其他平台按系统单位转换；是整个隔离worker峰值，不是某阶段峰值，禁止取前后差值冒充阶段新增内存。不新增依赖 |
| 恢复增量 | 按初次/续跑/仅checks分别记请求、SQL/API、SHA读、Parquet输出、替换及保留文件；请求和替换数与17.4独立字面预期交叉核验，不能只信观察器自己的汇总 |

观察器的返回值、异常和真实执行不变；有独立小金样本核分类/计数，不能只证明包装器和自身expected相同。全部报告JSON来自本轮临时执行，带测量边界、样本数量及源替身说明；原page/行数/JSON字段合同仍按实际producer造样本。报告不得使用物理IO未测的数字填零冒充测得。

### 17.6 成本、失败规则与交付门禁

生产正常路径0新增数据请求、DuckDB SQL、SHA或写湖；取消至多原day CP及统一窗口小JSON，正常源/行/文件/预算上界不改。测试只涉及1个普通日期及固定9日（可独立目录），无对象池扩张；九日失败恢复合计10次本地源调用，普通样本准备1次、分页2次，仅checks 0次，合计约13次测量替身调用。信号/回收回归最多2个受控子进程，所有资源位于本步专用系统temp，预计文件与日志≤256MiB；预计小型测量及最终公告回归累计数分钟，不设正式job新的时间、RSS或磁盘硬阈值。

开发顺序：本节完成→取消原反例先红→取消修正定向绿→九日实际业务组合→透明观察器独立计数验证及新worker测量→独立源码/结果复核→统一公告组及原run_contract门禁一次→Ruff/文档/空白→清理并填结果。失败停止当步，查真实合同，只重验受影响组；不改输入迎合错误、不skip失败、不自动正式执行或重新扫描数据。

最终逐条记录本步实际修改、原生取消与普通错误的正反证据、九日9/0/0→10/9/18、阶段测量表、峰值RSS/临时空间/恢复增量、去重统一测试结果及清理。未执行的正式源/PostgreSQL事件、重载、正式job/check及08:00延迟根因仍明确未验收，不能因本步隔离待办完成而标为已上线。本节仅覆盖开发和隔离验收，提交须另行指令；不安装、不修改正式后台状态或数据。

### 17.7 实现与隔离验收结果

本步先完成17.1—17.6，再修改五个生产文件。`anns_d_checkpoint.py::ANNOUNCEMENT_CANCELLATION_ERRORS`集中三类取消；day、window及两个历史消费者全部接入；window已验证state后的活动体提为`_execute_announcement_window_locked`，取消事实只由锁内外层持久化一次。source、IO、checks算法和其他数据集未改。源码检索无旧同义tuple遗漏，正常无新增数据请求/SQL/SHA/写湖。两位未编辑相应模块的审阅者完成取消源码、九日业务测试及观察器独立复核，本步三项范围内无剩余阻断。

**取消分类与正常变化。** 8条旧行为真实反例先红：首日源、day提交后、window提交后、startup保存/日志、final保存/日志及新提交证据核验期间的原生中断；当时原异常虽抛出却留下错误phase，未把夹具/收集失败计为红灯。修正后18项专项通过，原有execution/window_recovery/window_safety另51项定向通过，不与最终组累加。覆盖三类取消、SystemExit/GeneratorExit/RuntimeError反向、原单日schema错误继续、合法同scope恢复、预算不退、已提交FP/ino/mtime保持，以及真实月合同fixture的两个历史消费者。

专用子进程用实际临时Dagster job分别验证首日原生中断及提交后SIGINT（仅发本测试PID），经本机SDK转换/传播，run均为CANCELED、ErrorSource.INTERRUPT，0 Mat/0 Check；提交后1个真实文件保留。另实际spawn sleeping_worker经原finally回收，未留下新增active_children。一次专项只控制信号probe和sleeping_worker两个子进程，未信号父测试或正式服务。窗口七个边界核实cancelled保存恰一次；day CP沿原规则保存，初始化两文件协议未变。

**九日业务组合。** `test_anns_d_nine_day_recovery.py`使用实际job/asset/guard/evaluator/文件及事件库，源传输和正式卷可用性为明示替身。首轮06-01..09依次各1请求，06-04五列schema在真实归一化失败，05..09仍继续，8个目标、0 Mat/0 Check。真实同root from-failure只再取04，原execution/budget总9→10，只有04日1→2；恢复期正式Parquet只替换04一次，其他8日ino/mtime/size/SHA及来源页集合不变。最终9 Mat/18项通过检查，storage_id/run_id/timestamp逐日绑定，持久check history两项各9日SUCCEEDED。第一次独立定向1项通过，最终统一组及全新worker再次核实，没有用mock evaluator代替这条业务验收。

**测量的独立依据。** 新增测量支持、worker用例及入口，生产不导入它们。8项金样本验证字面5字节SHA（fsync打开不计读）、真实连接1 settings+2 SET、业务SQL/API/COPY、原异常透传、RSS平台单位、业务控制与独立核验分类及已知run/window归属。初次测量发现阶段间JSON被误列verification，后按真实执行补为execution_control；late补齐check的window_id不增加查询。最终报告来自统一回归中的新worker，24个实际check阶段均有原run/window，不引用补字段前草稿作最终证据。

下面是最终worker的分轮汇总；SQL是显式execute提交数，括号内为setup/业务，read_parquet/read_json/create_view的API计数在JSON另列；不是引擎物理扫描数。SHA字节仅原函数实际返回的应用层read；JSON/Parquet为已完成输出文件大小，rename不另算完整数据写入。独立验收的8次audit及断言读取单列，未漏算或混入算法成本。

| 本地样本/轮次 | 源替身请求 | SQL（setup/业务） | SHA读取字节 | Parquet COPY数/输出字节 | 正式Parquet替换 | JSON输出字节 |
| --- | --- | --- | --- | --- | --- | --- |
| 准备已有1行 | 1 | 44（18/26） | 8,640 | 2 / 1,728 | 1 | 18,422 |
| 普通2,001行分页→合并2,002行 | 2 | 51（21/30） | 29,434 | 3 / 5,866 | 1 | 566,648 |
| 九日首轮，第4日schema失败 | 9 | 208（72/136） | 6,144 | 16 / 3,072 | 8 | 172,824 |
| 同root恢复，仅第4日补写并完成两checks | 1 | 188（90/98） | 14,208 | 2 / 384 | 1 | 146,893 |
| 仅两项checks恢复，仍引用原物化 | 0 | 18（9/9） | 15,974 | 0 / 0 | 0 | 0 |
| 独立验收，不计作算法阶段 | 0 | 48（24/24） | 0；另独立二进制断言读4,800 | 0 / 0 | 0 | 0 |

测量替身请求合计13，九日两轮合计10；正常/恢复JSON开销包含execution_control，未从汇总中排除。算法显式SQL合计509，另独立验收48；业务及setup各自对账。请求/COPY/替换数与业务测试字面预期一致，不只相信观察器自己的结果。

应用层JSON文本读回按UTF-8另列：prepare 7,424 B、normal 9,877 B、initial 42,742 B、resume 80,188 B、checks_only 6,259 B；独立验收55,911 B。它们没有并入SHA或DuckDB输入模型；普通execution_control阶段本身读回3,455 B，不是表中relation输入模型为0就代表没有控制文件读取。

普通2,001行更新的逐阶段输入和输出如下；输入文件为已知relation唯一文件的压缩/JSON大小模型（build含readback候选），同一文件可能被多条SQL引用，不能当成实际物理读取总量。其他轮次逐日/阶段详情完整保存在小JSON中。

| 阶段 | 输入文件数/大小模型字节 | SQL（setup/业务） | SHA实读字节 | Parquet输出字节 | JSON输出字节 |
| --- | --- | --- | --- | --- | --- |
| capture | 2 / 271,026 | 8（6/2） | 3,339 | 3,339 | 549,084 |
| build | 4 / 6,730 | 19（3/16） | 3,391 | 2,527 | 0 |
| promote | 1 / 2,527 | 6（3/3） | 6,730 | 0（移动已有候选） | 7,199 |
| file_check | 1 / 2,527 | 6（3/3） | 5,054 | 0 | 0 |
| delivery_check | 1 / 2,527 | 12（6/6） | 10,920 | 0 | 0 |
| execution_control | 0 / 0（JSON读另列） | 0 | 0 | 0 | 10,365 |

全新worker绝对峰值RSS为**269,385,728 B（256.9MiB）**，包含Python导入、pytest、Dagster、观察器和本地DuckDB用例，不是某阶段新增内存或正式源子进程的峰值。其自有目录阶段边界观察最大82文件、逻辑大小**593,118 B**、分配空间**806,912 B**；它是边界采样最大值，不保证捕获短暂spill。SDK IPC/网络及DuckDB物理磁盘IO/引擎scan数明确未测（JSON为null），未填0冒称测得，也未据此外推正式吞吐。

最终统一命令沿17.6，现有.venv和独立系统temp：**613 passed，40 subtests passed，43.63秒**。相对上一轮新增28个主测试；worker内部2个业务节点均passed，不再叠加成615。5条现有Pydantic/分区检查preview警告保持。全src/tests致命错误Ruff、本链全部27个修改Python文件默认Ruff、文档完整性和差异空白检查通过；CodeGraph explore及最终sync/status完成且索引有效，提取的活动体及测试动态接线已人工补核。没有新增业务依赖方向、公共配置或其他数据集影响。

最终测试目录`anns-d-acceptance-final-20261027.KRkLLV`的**4,387个文件、8,168,448 B**已删除，确认目录不再存在；测量worker先自行清掉measurement-data，定向组也删除Parquet/DuckDB/checkpoint及临时instance。只保留有用小日志/报告：`/private/tmp/anns-d-acceptance-closeout-20261027.wToffs/`内最终pytest、完整测量JSON、阶段摘要、signal-report及cleanup记录；取消原红/绿小日志仍在`/private/tmp/anns-cancellation-7kjV0M/`。未清理正式或其他任务文件。

本步第三项及两项隔离验收待办已闭合。上述隔离验收完成时尚未提交；后续提交以Git记录为准，不代表部署或补数。未安装、未重载DG、未跑正式job/check、未取当前真实源或读写正式业务数据；正式源/PostgreSQL事件验收和08:00后台迟到根因仍属于未执行的正式边界，不能宣称已上线或源站完整性已验证。
