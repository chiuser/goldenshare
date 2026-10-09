# DC 板块暂未形成行情的处理 LLD v1

> 状态：2026-10-09 已按管理员开发授权完成代码实施、隔离回归和正式 Lake 历史存在性只读验证；实施对账见 §8.1。生产源双快照预检、正式写入与上线验收尚未执行，不能据此宣称 10 月 8 日数据已经恢复。
> 本文是 [板块接入方案](./dagster-dc-board-data-onboarding-plan.md) 和 [原 LLD](./dagster-dc-board-data-onboarding-low-level-design.md) 的实施补充；本文条件覆盖口径已进入当前工作区代码，原文档中的旧集合门禁仅保留为历史阶段记录。

## 1. 结论与范围

允许有真实身份、尚未形成行情的板块留在 `dc_index`，保留源端真实的 `dc_member`；`dc_daily` 只写源端返回的行情。缺行情信息保存为目标日期对应的 Dagster asset check metadata，由 Dagster instance 存储。无需新业务表、manifest 或状态资产。

本次确认的设计方向：保留条件放行；成熟板块缺行情仍整日阻断；复用现有核心 check metadata，不增加 WARN check 或预检事件台账；历史验证只承担行情存在性举证，不全面重验历史质量。

这项放行必须有边界：在可信历史范围内从未出现行情、且完整源端重复确认缺行情的板块，可以等待首次行情；过去已有行情、今天缺失的板块继续阻断。历史证据不完整时不能判成“合法等待”。不能仅凭名称、零值、无成员或一次空响应放行。

本轮设计涉及 DG 板块 Raw/Silver、源完成判定、writer、checks、readiness、sensor、bootstrap，以及 Gold/ClickHouse 消费链验收。不修改 Prod ingestion、`DatasetDefinition`、Wealth API、行情计算公式和物理字段。不得将 DG 的观察记录下沉成业务行情。

## 2. 审计证据及其边界

审计日期为 2026-10-09，目标业务日为 2026-10-08。以下事实来自当前代码、只读 Prod 查询、Tushare MCP 和正式 Lake 文件；临时证据保存在 `/private/tmp`，不是长期事实源。

| 项目 | 结果 | 能说明什么 |
| --- | --- | --- |
| Prod index / daily | 1,032 / 1,031 个板块；行业 496、概念 505/504、地域 31 | 唯一 index-only 是 `BK1754.DC`，名称“2026三季报首亏” |
| 完整 Tushare 三类型 index / daily | 496 + 505 + 31 / 1,031；差集同上 | 差异存在于源端，并非 DG 丢掉一条行情 |
| BK1754 成员 | 5 个真实成员 | 不能按“没有股票纳入”解释该案例 |
| 成员样本 | 688837.SH、920091.BJ、920701.BJ、920717.BJ、920925.BJ | 目录与成员已经有事实，日行情仍为空 |
| BK1754 index 数值 | leading 为 `-`，市值、换手等为 0，涨跌家数为空 | 仅作现象记录，不能作为合法性判据 |
| 源端历史日线查询 | 2024-01-02 至 2026-10-07，BK1754 返回 0 行 | 当前源端没有返回该范围的历史行情，不证明其永久没有行情 |
| Lake 历史身份扫描 | daily 666/666 文件、index 432/432 文件，BK1754 匹配 0 行 | 在已扫描文件中此前未见该代码；尚未做全部文件的完整质量验收 |
| DG sensor | index 原因为 `prod_completion_not_closed`；其余依次等上游 | 第一处阻断发生在 Prod 完成判定，后续缺文件是级联结果 |

此前日审计计数为 145 个审计对象，其中 136 存在、7 个 Lake 对象缺失、2 个 serving 对象缺失；该计数不是板块覆盖率。不能把 1,031 条真实行情写成 1,032 条来消除审计异常。

证据文件：

- `/private/tmp/dc_cause_audit_20261008.json`：原因汇总及原始证据路径。
- `/private/tmp/dc_full_source_audit_20261009.json`：完整源端集合差异及历史查询结果摘要。
- `/private/tmp/dc_quote_history_audit_20261009.json`：历史身份与列扫描性能；明确标记 `history_presence_only=true`。
- `/private/tmp/dg_dataset_audit_20261008_20261008T235159Z.json`：最初物理完整性审计。

上述证据支持本方案方向，但尚不足以直接执行生产放行：还需通过本设计的历史存在性证据验证和两次源快照稳定性验收。临时文件可能被系统清理；开发验收时应将脱敏摘要和验收结论落回本文，不依赖临时路径长期存在。

## 3. 开发前实现审计（历史基线）

下表记录开发前的阻断点，实施后的代码与测试见 §8.1。下列路径均相对于 `lake_console/orchestrator/src/orchestrator/`。

| 代码点 | 当前行为 | 必须调整的原因 |
| --- | --- | --- |
| `defs/asset_guards/dc_board_source_probe.py::load_prod_dc_board_completion_snapshot` | 要求 index 代码是 daily 子集，member 是 index 子集；失败不给完成快照 | 未形成行情的真实板块导致源校验尚未开始就被阻断 |
| 同文件 `load_tushare_dc_index_daily_source_snapshot` | 全字段、有界分页，重复检查 index ⊆ daily | 只放宽 Prod 门禁仍无法提交 run |
| `defs/assets/dc_board.py::_validate_dc_daily_covers_same_day_index` | promote 前再次检查同日 Raw index ⊆ daily | 只改源 probe 仍无法写入 daily |
| 同文件三类 writer | 重验 Prod 完成；index 重验冻结源指纹；member 按代码请求并确认差异 | 必须共用新判定，保留冻结与请求预算，禁止 writer 自行豁免 |
| `defs/asset_guards/dc_board_relations.py` | Raw/Silver relation 的 index-only 都是失败 | 核心 check 与 readiness 同时依赖它，不能只改 check 展示 |
| Raw/Silver quality / checks / lake readiness | 文件、schema、日期、身份、主键、数值及同日关系共同决定 ready | 合法等待不再计核心失败，结构异常与成熟板块缺失仍失败 |
| `defs/sensors/dc_board_sensor.py` | 最近 10 日 first-not-ready；当前日 21:15 后观察 Prod 稳定快照 | 保留窗口、稳定等待和每 tick 至多一个请求，不扫描事件历史 |
| `defs/run_contracts/configs.py` | 集中构造 Prod/source observed_at 与 fingerprint 配置 | 新覆盖证据必须集中声明，所有构造与消费方一起迁移 |
| `defs/bootstrap/dc_board_bootstrap_apply.py`、`dc_board_events.py` | 复用完成判定、writer 或 readiness | 正常日更之外也有消费者；不能留下旧豁免口径 |
| `defs/assets/dc_daily_technical.py` 与 quality | 基于真实 Silver daily；Gold 当日键与 Silver 键一致 | 没有行情就没有技术指标，现有公式无需加入目录补行 |
| `defs/assets/dc_daily_technical_serving.py` | Gold → local CH → Prod CH，按实际 Gold 行发布 | 不应向 `board_fact_technical_daily` 写空板块占位行 |

`dc_member` 单代码请求成功返回空集合，当前允许该代码没有成员；所有请求整体无数据仍失败。它与行情缺失是两个问题，本设计不改变 member 的差异确认和全局非空门禁。

现有“历史新高/历史新低”占位剔除是特定既有规则；BK1754 不符合其名称条件。不得扩展成“全部零值板块都剔除”。源端 daily-only 代码当前允许保留，本设计继续保留。

影响面分析使用了 CodeGraph explore/search/callers/impact；其调用图没有完整识别动态 definitions 和部分导入消费者，因此又逐项搜索并阅读 orchestrator 的实现、bootstrap、tests，以及 `src/biz`、`wealth/src` 的消费代码。不能把 CodeGraph 的“无调用方”当作没有消费者。Wealth sector-overview 当前读取 Prod 业务事实并保留 `has_daily`/可空行情语义，不读取 DG check metadata；上述业务/前端搜索范围未发现直接消费 `board_fact_technical_daily` 的代码。本轮不新增跨域依赖或前端功能。

## 4. 统一判定契约

### 4.1 集合与结果

令 I 为当天有效 index 代码，D 为当天真实 daily 代码，M 为 member 代码。现有结构、日期、唯一键、类别覆盖、分页完整性与 `M ⊆ I` 继续强制执行。D 中额外代码保留源事实，不删除。

对 G = I − D 中每个代码生成如下判定，不能靠人工白名单维护：

| 状态 | 判定依据 | 核心 ready | 观察结果 |
| --- | --- | --- | --- |
| `awaiting_first_observed_quote` | 可信历史范围内未见行情；当日完整源快照两次稳定确认无行情；身份有效 | 可通过 | 核心 check 通过，metadata 记录等待状态 |
| `missing_previously_observed_quote` | 目标日前可信 daily 中出现过该代码 | 不通过 | 缺行情及最后可见日期 |
| `quote_history_unverifiable` | 应有历史文件缺失、文件不可读、身份/日期证据不可信、预算超限或扫描证据不稳定 | 不通过 | 标记证据缺口，不能归为等待 |
| `source_snapshot_unstable` | 当日源重复结果不一致或请求失败/未完成分页 | 不通过 | 继续既有源端等待/失败流程 |

`awaiting_first_observed_quote` 表示“在已声明历史范围内尚未观察到行情”，不能简化成源端承诺的“合法永久无行情”。不推断公司财报披露进度，不要求 index 数值全部为零，也不要求成员为空。等待多久不自动变成成熟板块；首次真实行情出现后，后续日期缺失就适用成熟板块门禁。成熟板块缺行情时，目标日期整体不发布；第一版不做部分板块降级发布。

纯判定结果为 `BoardQuoteCoverageResult`：包含 target_date、policy_version、history_start/end、history_complete、index/daily 数量、差集分类、blocking reason、证据摘要与 digest。函数不写数据库、Lake 或 Dagster instance；身份及时间规范化集中在 `defs/run_contracts/dc_board.py`。

实现必须分清两个层次：共享纯分类函数依据当天 I/D 与历史证据给出分类；源完成裁决在该分类之上额外要求重复源确认。Lake core check/readiness 只读物理文件与历史证据，不请求 Tushare/Prod，也不读取 check event 或 cursor 来证明文件可用。因此物理观察应明确 `source_confirmation=not_evaluated`，不能把物理 ready 宣称为当次已做两次源确认。正式 writer 必须在提升前完成源裁决；既有历史文件需在限定修复的源预检中补验，不借 read-only readiness 触发网络请求。

### 4.2 历史依据与性能

daily 历史起点固定为现行 `2024-01-02`；index 起点为 `2024-12-20`。目标日期不参与“此前出现过”的判定。历史日期由正式 Silver 交易日历生成，只读正式 Raw daily 文件；Silver 复核同样使用此原始事实，避免 Raw/Silver 得出不同生命周期结论。历史 index 只提供 first_observed_index_date 诊断，不是放行必要条件：一个已在目录等待多天的板块仍可没有行情。

只有存在 G 时才查询历史，查询对象仅为当日缺行情代码。一个 invocation 共用一个 DuckDB connection，以批量、列裁剪和代码过滤读取 `ts_code`、`trade_date` 等身份/日期证据，汇总 first/last quote date。已经找到可信历史行情的代码即可判为成熟缺失，不必为了这一判断继续读完所有历史；只有要得出“此前未见行情”的代码，才需要覆盖已声明起点至目标日前的完整日期范围。不能把“最近十天没见到”当作“从未有行情”。

验证职责仅限于：交易日历生成的应有文件是否齐全；文件及必要列是否可读；用于举证的代码、日期类型和日期归属是否可信。日期归属采用必要日期列的批量汇总，不逐分区执行完整 core check。历史文件缺失或身份/日期证据异常时，不能用其证明“未见行情”；对已找到可信历史行情的代码仍直接阻断，不需要证明全部历史健康。

**不重验全部历史的 OHLC、成交量、数值、类别覆盖、全量重复键或其他质量规则。** 这些继续由原分区质量检查负责；本功能不把历史文件全部读成宽表，不新增全历史质量审计任务。目标日自己的 schema、主键、数值、类别和写入前校验保持原有要求。历史 index 仅提供可选的首次目录观察诊断，不为每次判定额外扫全量 index 历史。

禁止每代码、每日期单独连接或查 Dagster event history，禁止持久化历史缓存来替代文件事实。文件清单只服务当前 invocation；开始与结束核对实际举证范围内的文件大小、mtime 与应有日期集合，扫描期间变化则不接受证据。digest 包含举证范围、文件签名和分类；mtime 只负责变化检测，分类仍来自读取到的身份/日期证据。找到历史行情而提前结束时，应记录实际举证范围，不得标记成全范围扫描完成；“未见行情”必须标记其完整否定证据范围。

同一次批量 readiness 对多个目标日判定时，合并缺行情代码与举证范围，共用一次有界历史读取，再按各目标日截取结果；禁止在最近 10 日循环内重复扫描同一份历史。提前结束的成熟判定只需要记录一条可信 `observed_quote_date`，不要求为展示补扫；未覆盖全部声明范围时，first/last 日期只能表示实际举证范围内的结果，不能宣称是全历史最早/最后行情。

#### 4.2.1 容量依据与冻结参数

2026-10-09 补充只读容量测量覆盖 666 个真实历史文件、652,809 行、文件总大小 36,961,424 字节。必要 schema、代码和日期读取未发现缺文件、空身份、错日期或扫描中变化；不读取历史 OHLC、不做全量重复键或数值质量检查。1,200 个筛选键包含 1,031 个当前实际代码、BK1754 和 168 个合成只读筛选键；合成键只测容量，不代表真实板块。10 个目标日合并到同一调用，结果对数 10,310。

| 每批文件 | 筛选代码 / 目标日 | SQL 次数 | 整次耗时 | 单批最慢 | 进程峰值 RSS |
| --- | --- | --- | --- | --- | --- |
| 64 | 1 / 1 | 33 | 201.455 ms | 24.675 ms | 197,083,136 B |
| 64 | 1,200 / 1 | 33 | 170.971 ms | 38.659 ms | 232,980,480 B |
| 32 | 1,200 / 10 | 63 | 380.038 ms | 20.705 ms | 263,503,872 B |
| 64 | 1,200 / 10 | 33 | 274.358 ms | 26.960 ms | 266,158,080 B |
| 128 | 1,200 / 10 | 18 | 228.914 ms | 44.102 ms | 279,379,968 B |

保留证据：[容量审计 JSON](../../reports/dc_board_quote_coverage_capacity_audit_20261009.json)。该报告不读取 Dagster instance、不请求网络、不改正式数据。RSS 是解释器、导入和累计查询的进程峰值，不是查询独占内存；文件总大小不是实测读取字节。未驱逐文件系统缓存，不承诺冷盘耗时；该原型证明查询形态可行，不替代生产 helper 和 sensor 验收。

以下参数冻结在 `defs/run_contracts/dc_board.py`，只有一个定义来源；无 env、DB、运营输入或自动放大逻辑：

| 常量 | 默认值 / 口径 | 超限处理及理由 |
| --- | --- | --- |
| `DC_QUOTE_HISTORY_BATCH_FILES` | 64 | 每个 SQL 最多传 64 文件；相较 32 批次减少 SQL，相较 128 控制单批工作集 |
| `DC_QUOTE_HISTORY_MAX_CODES` | 1,200 | invocation 中全部目标日的缺行情代码并集超过即不可验证；与现有 member 候选预算对齐，不等于修改全部目录的业务合法范围 |
| `DC_QUOTE_HISTORY_MAX_TARGETS` | 10 | 超过时离线调用方按目标日批次拆分；sensor 不扩大既有窗口 |
| `DC_QUOTE_HISTORY_MEMORY_LIMIT` | 512 MiB | 专用 DuckDB connection；包含既有投影/汇总工作；内存不足不能启用 spill |
| `DC_QUOTE_HISTORY_THREADS` | 2 | 单次 invocation 固定，避免多个 sensor 同时放大并行度 |
| `DC_QUOTE_HISTORY_BATCH_SQL_DEADLINE_SECONDS` | 1 | SQL 到时调用 connection.interrupt；中断后本调用失败关闭，不复用被中断连接 |
| `DC_QUOTE_HISTORY_DEADLINE_SECONDS` | 5 | 从文件规划/签名开始计时，覆盖全部批次、归并和结束签名；每批检查剩余预算，计时器不在批次间重置 |
| `DC_QUOTE_HISTORY_MAX_PROJECTED_ROWS` | 2,000,000 | 每批先取 footer 行数并累计；下一批使累计超限则不扫描该批，约为当前样本3倍的资源拒绝阈值，不是完整性口径或行数保证 |
| `DC_QUOTE_HISTORY_MAX_FILE_BYTES` | 128 MiB | 实际举证文件的 Parquet 压缩字节累计；下一批超限不扫描该批，未完成的否定证明保持不可验证 |

总文件数不是任意固定的 2,000 个分区：它等于 `2024-01-02 <= d < max(target_date)` 范围内去重的 SSE 开市日数，且不超过该范围的自然日数。目标日不得晚于当前业务日；日历重复、范围外日期或文件集合不对应时失败。该公式给出本次有限范围，行数、字节、内存和5秒预算共同限制实际工作量；增长触发资源阈值时需性能复审，不能自动改起点、提高上限或维护历史缓存。

每批最多3条重查询：必要 footer/schema 汇总（先核对必要列及非空文件，再按下一批额度判断能否读取）、日期/空身份验证、缺行情代码×目标日存在性汇总；总重 SQL 上限为 `3 × ceil(history_file_count / 64)`。日历规划查询计1次；不能把全部目标日再次套在 SQL 批次外循环。输出状态最多 `1,200 × 10` 个小型结果；无差集时历史重 SQL 为0。最多读取必要身份、日期与 footer，不能把 file count/bytes 误说成实际 IO。

历史批次按日期降序执行，先尝试最近64文件。已找到可信历史行情的代码/目标日立即保留成熟缺失分类，全部目标已确定成熟则结束；未确定的代码继续向前举证。更早文件缺失/损坏或预算超限只会使剩余否定证明不可验证，不推翻已找到的成熟证据。声明范围没有历史交易日时用规范空证据，不要求不存在的历史文件。

历史专用 connection 通过现有 `DuckDBResource.connect()` 建立，本次连接设置上述集中常量后复用，不修改父调用已有 connection 的全局设置，不另造配置型resource。多个目标日共用这一历史连接；check/readiness现有目标文件连接的用途不变，禁止按日期创建历史连接。

5秒是本功能额外历史举证预算，1秒是单批 SQL 中断预算，均不是整个 sensor 或所有网络调用的超时。同步文件系统调用无法保证被 DuckDB interrupt 强中断：每个64文件批次前后检查剩余时间，挂载失效按现有 Lake 可用性门禁处理，不承诺底层 IO 故障时精确5秒返回。SQL timer 要绑定本次 connection，在 finally 取消并清理，不泄漏到下一个查询。

预算失败使用 `quote_history_unverifiable` 并附 `history_budget_exceeded`、`history_query_interrupted` 或 `history_io_unavailable` 子原因；当前候选不提交 run，writer 不提升文件。对已找到的可信成熟板块直接阻断，但不能将尚未查询的其他代码判为等待。不得因为局部扫描成功，把 `history_complete` 置为 true。

容量样本留出耗时/内存余量，不能承诺到资源上限仍必然通过。开发后以同一真实数据做只读 profiling，分别记录 helper、完整 sensor、SQL 次数与最慢子查询；其他原有结构校验耗时单列，不能归入本原型结果。超预算先优化批量查询，再按批准流程修订参数，不增加状态表。

### 4.3 完成时机与源冻结

不能简单删除 Prod 的 index ⊆ daily 判断后返回 ready。将当前完成函数拆成“结构有效的 Prod reference snapshot”和“综合完成裁决”：前者提供稳定完成时机证据，后者结合完整 Tushare I/D、历史分类后决定能否运行。调用方一次性迁移，不保留新旧双轨门禁。

当前日继续要求 21:15 后、两次间隔至少 300 秒的相同 Prod fingerprint。对于存在 G 的源快照，还必须有两次间隔至少 300 秒、完整内容 fingerprint 相同的 Tushare index/daily 观察；两种稳定观察可在同一轮收集，避免先被 Prod 集合差异挡住源观察。过去日期存在 G 时也要满足源重复确认；正常无差集日期不增加五分钟源等待；下游为取得独立证明新增的完整源预检请求按 §4.4.4 计入预算。每 tick 至多一个 run request，现有 600 秒 sensor 间隔不改变。请求预算不足时等待，不以小页探测代替完整源快照。

集中 run config 使用 §4.4 的统一模型；证明只由完整实际观察生成。writer 重新读取完整当前源事实并核对冻结内容，同时重新验证历史证据。证据变化或重新分类出现阻断项就 fail closed，候选文件不得提升；禁止仅相信 sensor 的布尔标记。运营不手填或拼装观察时间、指纹与 digest。

这里的 digest 保护判定证据，不把 Prod 变成内容裁判；Prod 与源的差异继续进入诊断，不删除或补齐源行。

### 4.4 入口冻结证明协议

#### 4.4.1 模型与构造方

新模型统一为 `DcBoardSourceFreezeConfig`，放在 `defs/run_contracts/configs.py`；替代 `DcBoardIndexSourceSnapshotConfig`，全部构造方和消费者同时迁移，不留旧模型兼容入口。index、daily、member 都绑定该类型。集中构造函数为 `build_raw_dc_board_update_job_run_config(asset_name, partition_key, proof)`；asset_name 仅接受当前三个 Raw asset，返回对应 op config，不增加 job、CLI 参数或调度开关。bootstrap 用同一 proof 构造/校验函数调用 writer，不自行填写 observed_at。

| 字段 | 类型及约束 | 实际生成方 |
| --- | --- | --- |
| `policy_version` | str，精确为 `dc_board_quote_coverage_v1` | contract 常量 |
| `trade_date` | ISO 日期；必须等于 partition_key | 集中 builder |
| `target_asset` | 当前三个 Raw asset 枚举；必须等于消费 asset/writer | builder 从调用入口赋值 |
| `prod_observed_at_first` / `prod_fingerprint_first` | 带时区 ISO str / lowercase SHA256，可空；成对出现 | Prod 第一完整结构快照 |
| `prod_observed_at_second` / `prod_fingerprint_second` | 同上，不可空；单次模式也以该字段表示实际最近快照 | Prod 实际最近快照 |
| `source_observed_at_first` / `source_fingerprint_first` | 同上，可空；成对出现 | 第一完整 Tushare index/daily 快照 |
| `source_observed_at_second` / `source_fingerprint_second` | 同上，不可空 | 实际最近完整 Tushare 快照 |
| `history_start` / `history_end` | 起点固定 `2024-01-02`；end 为目标日前最后开市日，可空以表示空历史范围 | 日历规划 |
| `history_file_count` | 非负 int，等于实际举证范围文件数 | 历史读取 helper |
| `history_evidence_digest` | lowercase SHA256；无差集/空历史仍生成规范空证据 digest | 纯证据归并函数 |
| `coverage_gap_count` | 非负 int；必须与 writer 重取的 I−D 数量一致 | source + coverage helper |

时间戳在完整观察成功结束时生成，统一 UTC；先于或等于调用校验时刻，不允许未来时间。两次字段在要求稳定确认时不可空，间隔至少300秒、对应 fingerprint 相等。是否要求两次由目标日期、asset 身份、I−D 和既有 source/reference 差异规则计算，不接受运营传入 bypass 或 confirmation_required 开关。指纹仍覆盖全部显式业务字段，不只哈希代码列表；拒绝错误版本、跨日期/asset 重放、假空字段和格式错误。

历史 digest 规范 payload 为 policy version、target_date、缺行情代码排序、每代码分类和已扫描日期范围、证据日期、历史文件签名（相对正式 Raw 路径、size、mtime_ns）及日历日期集合。用规范 JSON + SHA256，排除查询耗时、observed_at 和展示样本；无差集时不为了生成 digest 扫历史。稳定两次 source 观察期间若 history digest 变化，清空该 source 确认链并重新观察；同一次读取首尾签名变化立即不可验证。

#### 4.4.2 正常日更与下游入口

| 入口 | 取得证明 | 传递与强制重验 |
| --- | --- | --- |
| index sensor | 保留当前日21:15后Prod两次稳定；在同一观察链获取完整源和覆盖证据；有差集或既有差异确认条件时做source两次稳定 | builder 生成 index config；writer 重取Prod/source/历史，核对全部冻结字段后提升 |
| daily sensor | 先走既有 first-not-ready 与同日 index readiness；只对选中的1个日期完整 source 预检。有差集时在本 sensor 小型 cursor 内形成两次source观察；无差集单次即可 | builder 生成 daily config；writer 重验源、Prod和历史；daily 直接写该次已核验完整 source snapshot 的 daily_rows，不另外请求一份可能变化的 daily |
| member sensor | 同样先等同日 index，再取得自己选中日期的完整 source 和覆盖证明；不从 index 文件或其事件推断稳定确认 | builder 生成 member config；writer 先重验再按既有同日index候选采成员，保留全部有界请求/差异确认；成员请求结束、promote前再次重验 source/历史 |
| 直接调用三类 writer | 必须提供本模型，不能省略证明自动降级 | 校验 target_asset/日期/版本/时间，重取当前事实；缺证明在源采集/正式写入前拒绝 |
| Silver/check/readiness | 不接收该源证明，也不请求源/Prod | 只用实际 Raw/Silver 文件和同一历史分类；`source_confirmation=not_evaluated` |

下游不会重做 index 的当前日Prod五分钟等待：同日 index 文件是依赖条件，下游重新读取最新 Prod 结构快照并核对自己的冻结 fingerprint，Prod first 字段可空。当前日 index（包括 bootstrap 生产 index 的路径）必须提供两次Prod证明。Prod仍不裁决源内容；不同入口的 Prod fingerprint 不强求与先前 index 相等。

daily/member 有缺行情时独立等一次300秒源稳定，可能使其在 index 完成后再多等一个600秒 tick；两者并行观察，不串联两段额外等待。无差集时不新增该等待。两个 snapshot 不一致时更新本 sensor 的 first 摘要并继续等待，沿用失败/去重合同，不修改 run key 以绕过既有已提交 run。

cursor 只增加 schema version、所选日期、第一观测时间/两个指纹、history digest和小型计数；不保存源行、逐代码分类或文件清单。新的 cursor schema 在首次读取旧版本时丢弃不可验证的稳定证明并重新观察，不保留旧 config 裁决分支；不删除既有历史事件。不得读取 event history 来把证明搬给下游。

所有 writer 的当前完整 source fingerprint 和 history digest 必须与配置相同；有差集时确认文件签名不能只在运行开始验一次，必须在 promote 前重验。member 的末次复核若失败，丢弃候选并保留旧正式文件，不将成员部分结果视为完成。无差集时 history digest 是空证据，不增加历史查询。

#### 4.4.3 Bootstrap 和手工入口

既有 `dc_board_bootstrap_apply_cli.py raw` 参数、命令名及 `--confirm-lake-write` 不变。不新增“准备证明”CLI、旁路 manifest 或永久台账。`_raw_write` 调用共用 `observe_and_confirm_dc_board_source`：只读实际完整快照；正常历史无差集且不满足既有source/reference差异确认条件时单次；差集或既有差异确认条件至少两次间隔300秒；当前日 index 还需Prod双快照。取得证明后交给同一 builder/validator 和 writer。

bootstrap等待由入口层负责，writer 本身不 sleep。单日期确认阶段的总领取预算为600秒，含等待和观察；等待每5秒检查终止信号/剩余预算并输出当前日期与等待阶段。请求前检查剩余预算，确认变化或预算耗尽则该日期失败退出，不无限循环。网络调用仍遵守当前 resource 超时与有界请求策略，不把5秒等待轮询宣称为同步网络调用强中断能力。等待/失败不得提升候选文件，不清理已经完成的其他日期。

source稳定确认只保存在本次调用内存；bootstrap中途退出后，不从旧报告恢复“已经稳定”标记，重启重新取得证明。既有报告保持运行说明角色，不是证明事实源；逐日期完成后立即更新既有 batch report 的已完成 entries，而非等满20日期再首次持久化，确保新增长等待不会丢掉已完成日期的观测。续跑仍按正式文件的统一 readiness 判断已完成日期，不补造事件。

member历史 bootstrap仍为既有Prod只读流式导出，不改成Tushare成员采集。其外层取得相同 source覆盖证明，导出前/候选提升前复核；无需把证明解析塞进通用Prod导出资源。Silver bootstrap及已有 runless事件入口仅使用物理分类，不触发新源观察；事件写入仍需独立授权。

Dagster手工 Launchpad/直接 job 必须提交由同一个共用观察函数和 builder 实际生成的本模型；旧index config、空证明或人工猜测时间/哈希一律不支持。运营只提供日期和目标入口，不新增手填控制字段；需手工恢复时优先使用现有受控 bootstrap 路径。证明是可信执行链的输入记录，不是防恶意管理员伪造的签名认证；writer重读防的是事实变化，不能声称一个SHA256能证明人为时间戳真实性。

#### 4.4.4 请求量、阶段预算及迁移对账

完整 source观察通常为3次index + 1次daily，共4次请求；分页/重试次数以实际 session计。每次source观察派生既有策略、最多16次请求（包含重试），使用同一限速与不超过既有600秒耗时上限；不足以完整分页时失败，不接受部分数据。Prod仍为3条日期限定只读查询；不引入member全集probe。

正常无差集日期，三个sensor各最多进行一次完整source观察，三个writer各重取一次，member提升前再复核一次：典型额外/复核source读取共7次观察、28次API请求；相较当前链的请求增量应在实施验收单列，而不是声称没有新增请求。有差集的稳定首轮/次轮增加观察，完整稳定一轮典型10次观察、40次请求；source发生变化的后续tick分别受单次16请求预算约束，不承诺无限等待期间累计请求有固定总数。

member正式请求session需把两次writer source观察实际请求量扣入现有1,200请求/600秒的写入阶段预算；candidate首请求前按剩余预算检查，且预留末次source观察最多16请求的额度，不能把1,200全部留给成员后另外追加source调用。预留未使用的额度不计实际调用，但必须保证末次完整复核有预算；请求数不足时拒绝当前候选，不裁剪成员池。index/daily writer同样共用该写入阶段总预算；source重复确认的300秒等待发生在sensor tick之间或bootstrap确认阶段，不算伪造的writer工作进度。超预算报明确原因、保留旧文件。

迁移必须同时覆盖：三类 asset 签名；三个sensor的run_config构造（下游当前没有config）；config模型/builder/validator；三类writer；bootstrap `_raw_write` 与member导出外层；直接构造旧config的 tests；静态旧符号扫描。`build_raw_dc_index_update_job_run_config`、`validate_dc_board_index_source_snapshot_config` 和旧class退出本链，不保留旧模型 fallback。物理 schema、asset/job/check名称、CLI参数、Lake路径、Prod成员历史来源不改。

## 5. 写入与恢复

Raw index 写 I 的真实内容，Raw daily 写 D 的真实内容，Raw member 的候选继续来自 I 并执行既有有界单代码请求。保留候选文件 schema/键/日期/行数回读、同文件系统 `os.replace()` 原子提升、checkpoint 和幂等语义；不改 Lake 根，不加入备份或 Kopia。

2026-10-09 实施核验发现原 Raw/Silver writer 仍在目标分区旁创建 `.tmp`。同链 Gold 日更与限定 repair 也使用目标旁 `.tmp`；本次一并校准候选位置，计算公式和 serving 口径不变。本次按根 AGENTS 的现行硬约束纠正：正式候选只能放到现有 `DEFAULT_LAKE_STAGING_ROOT=/Volumes/datasource/data_lake_staging` 下的 DC/run-id/layer/dataset/date 目录，不能落在正式 Raw/Silver 根。提升前核对设备号，跨文件系统直接拒绝；member 的末次源复核在候选回读通过之后、`os.replace()` 之前执行。隔离测试仅使用系统临时目录中的独立 sibling staging；拒绝将任意其它目录或退役 Lake 根当成正式路径。不新增环境变量、运营配置或 CLI 参数。

同日 relation 将“全部 index-only 都失败”改为“只有合法等待分类可豁免”。Raw writer、Raw/Silver core checks 和 readiness 调用同一判定实现；不允许 readiness 为绿而 writer/check 仍执行旧关系。现有一个合并核心 blocking check 的名称、分区定义与其余规则保持。

首次真实行情到来：当日 daily 正常写入，Gold 自然生成该代码的首个样本，observation_count 从 1 开始，warmup 继续按现行指标规则，不从目录补历史行。local/prod CH 发布实际 Gold 行即可。

未来日期恢复只改变新日期的观察结果，旧日期记录保留为当时证据。源端后来补发历史行情时，当前 first-not-ready 与 run-key 去重不会自动发现所有历史修订；必须走已批准的限定日期重采和技术指标 repair。修复范围从受影响日期延伸到依赖后续窗口，继续现有 source_revision/fingerprint 协议。不能承诺自动回补，也不能只重算单日忽略后续指标。

本次 10 月 8 日在契约实施后重新做只读预检；只有全部门禁通过并获得生产执行授权，才可恢复既有日更链或进行限定修复。本 LLD 不授权修改 cursor、补事件、启停 sensor 或启动任何 run。

## 6. 缺行情信息保存在哪里

### 6.1 记录载体

复用现有 Raw/Silver daily 的合并核心 blocking check，不新增 `board_quote_coverage_check`，不新增 WARN check 或额外 check event。合法等待时核心检查 `passed=True`，metadata 记录 `awaiting_first_observed_quote`；成熟缺失、证据不可验证或其他核心规则失败时，核心检查 `passed=False`。检查通过表示满足允许发布的契约，并不表示所有目录代码都有行情。

沿用现有 check 名称、分区绑定、job 选择和 catalog 的 `blocking_check_names`。metadata schema 和 policy version 由同一个 contract 声明，复用 `build_check_metadata(extra_metadata=...)`；查看入口为既有 Dagster 分区核心 check 详情，无需增加 catalog 状态模型。

合法等待的代码数量不计入 `failed_row_count`，等待分类不进入 `failed_rules` 或 `failure_samples`；另用覆盖明细和覆盖样本展示。否则即使 `passed=True`，原有失败字段仍会让运营误读成质量异常。

第一版记录边界：成功落湖后执行核心 check，持久化当日覆盖状态及正常规模的逐代码分类；如果源预检在提交 run 前就阻断，asset check 尚未执行，阻断原因沿用现有 sensor 诊断。本功能不新增预检事件台账，不承诺每次被阻断的预检都有持久化逐板块明细。writer 在 check 前失败同样不能宣称已保存覆盖 check 记录。

当前 Dagster instance 的持久化为 PostgreSQL，asset check evaluation 进入 instance 的事件存储及 check execution 记录（实现表包括 `event_logs`、`asset_check_executions`）。这是 DG 自身运行存储，不是 Prod core 业务库。通过正常 `AssetCheckResult` 产生记录，禁止手写这些表。

官方 [asset checks 文档](https://dagster.io/docs/guides/test/asset-checks) 说明了 metadata 与 blocking 语义。本机审计版本为 Dagster 1.13.18；实施必须以本机 API 和隔离执行测试验证核心检查通过/失败的下游行为。

### 6.2 Metadata 与容量

沿用现有 `goldenshare/` 命名空间，至少记录：

| 字段 | 内容 |
| --- | --- |
| `partition_key`、`policy_version` | 业务日和分类版本 |
| `index_code_count`、`daily_code_count`、`missing_quote_count` | 目录、行情和缺行情代码数，不能混为物理行数 |
| `awaiting_count`、`previously_observed_missing_count`、`unverifiable_count` | 各类差集数量 |
| `missing_quote_details` | 按代码排序去重，正常规模完整保留每个代码、分类、举证范围和 observed quote date；first/last 日期按实际扫描范围注明；名称只作样本 |
| `quote_coverage_samples` | 最多 5 条覆盖样本：代码、名称、类别、状态和历史举证日期；与原有 failure_samples 分开 |
| `history_start/end`、`history_complete`、`history_file_count` | 实际验证范围及完整程度 |
| `source_confirmation`、`evidence_digest` | 物理 core check 标为 `not_evaluated`，不冒充执行源预检；记录本次历史判定 digest |
| `reason_code`、`metadata_truncated` | 机器原因和明确的容量限制标记 |

序列化 coverage metadata 上限为 64 KiB（不含既有质量检查的其它 metadata）。优先保存数量、范围、digest 与完整逐代码分类，名称只保留样本；若仍超限，则明细列表也截断并记录 `metadata_truncated=true`、实际保留数与总数，不能伪称历史明细完整。大规模异常应先解决源完整性，不引入外部明细文件作为新事实源。此限制只约束观察载体，不改变业务事实或把已提交数据回滚。

观察写入失败不能回滚已原子提升的 Lake 文件。运行状态可显示观测失败，由后续获准的 check-only 执行恢复观察；物理 readiness 仍从文件判断，不能读取 event 作为数据存在证明。事件保留期限取决于现有 instance 运维策略，本文不承诺永久留存，也不新增清理任务。

sensor cursor 仅保留当前候选日期、稳定观察所需时间/指纹、分类计数及短 reason；重置 cursor 不删除历史 check。不要把全部板块名单、全部历史文件或长期缺行情台账塞进 cursor。

## 7. 改动点与配置审计

已新增 `defs/asset_guards/dc_board_quote_coverage.py` 承载批量历史读证据与纯判定，`dc_board_source_freeze.py` 承载源确认与写入前复核；均不依赖 `src/ops`、`src/biz`、`src/app`。

| 实现面 | 实施范围与同步验收 |
| --- | --- |
| `run_contracts/dc_board.py`、`configs.py` | 结果模型、policy version、预算、metadata 契约和冻结配置集中声明；全部构造/消费方迁移 |
| `dc_board_source_probe.py` | Prod 结构观察与综合裁决分离；源重复确认不受旧 subset 门禁短路 |
| `assets/dc_board.py`、`dc_board_raw.py` | 三类 writer 重验统一证据；daily 仅写真实行；配置迁移 |
| `dc_board_relations.py`、Raw/Silver quality/readiness | 删除 blanket index-only 失败口径，使用统一分类；保留 member 关系和结构规则 |
| `dc_board_checks.py`、`dc_board_silver_checks.py` | 复用现有核心 blocking check；通过时也附带覆盖分类；metadata 有界 |
| sensors、jobs、catalog 注册及 definition tests | 验证两次观察、run 去重和现有核心 check 选择；不新增 check、调度开关或预检事件 |
| bootstrap apply / event readiness | 同步消费者；历史修复不得借 bootstrap 绕过证据 |
| Gold / serving / repair tests | 不改表和公式，验证实际行闭环、首样本和历史修复范围 |
| 日期物理审计 | 缺文件仍是缺文件；文件存在不代表目录100%有行情；输出中明确观察覆盖与物理完整性分开 |

原方案每资产“一个核心 blocking check”及不增加额外观察 check 的约束均保持。契约变更仅为 index-only 的条件分类和核心 check metadata，不增加额外检查注册。

| 配置/常量 | 当前默认 | 来源/持久化 | 作用范围与生效 |
| --- | --- | --- | --- |
| 当前日观察起点、稳定间隔、sensor 间隔 | 21:15、300 秒、600 秒；沿用现行 | 既有 contract/sensor definitions；稳定值进入 cursor/config | 全部相关 source sensor/writer；definitions reload 后生效 |
| 请求限速与总预算 | 0.13 秒最小间隔、1,200 请求、600 秒；沿用当前实现 | 既有请求策略 contract | 源 probe/member；不能用历史扫描侵占或放大请求预算 |
| history batch/resource/time guard | §4.2.1 已冻结：64文件、1,200代码、10目标日、512MiB/2线程、SQL1秒/整体5秒、2,000,000行/128MiB文件 | 集中 `run_contracts/dc_board.py`，不新增 env/DB/运营输入 | 所有覆盖判定消费者；超限不可验证，禁止自动提高阈值 |
| coverage policy version | `dc_board_quote_coverage_v1` | 同一 contract；随 metadata/config 持久化 | 禁止旧版本 digest 直接被新 writer 接受 |
| coverage metadata budget/sample limit | 64 KiB / 5 | 同一 contract及 metadata builder | 观察载体；截断可见，不影响已提交业务事实 |
| history digest/source observations | §4.4统一证明；无手工默认，只由实际观察生成 | 集中config builder、三个asset的run config、小型cursor/本次bootstrap内存 | 三类writer同样重验；拒绝旧模型和缺证明 |
| source observation / bootstrap confirmation guard | 16请求每完整观察；bootstrap确认领取预算600秒、等待检查5秒 | 集中 `run_contracts/dc_board.py`；派生现有session策略 | 三个source观察入口与bootstrap；包含重试，确认不完整不运行 |

以上配置审计已落实为集中 contract、typed config 与统一 builder，没有新增运营参数；默认、边界、超限及消费者迁移验证见 §8.1。

候选路径复用现有 `paths.DEFAULT_LAKE_STAGING_ROOT`，默认值、来源和正式作用范围保持不变；新增的 DC candidate helper 由 Raw、Silver、Gold 日更及限定 repair、Bootstrap 及既有 Silver repair stage 共同调用。路径即时生效、无持久化配置，staging 根不可用或设备号不一致时拒绝提升；测试覆盖正式根映射、临时隔离、非法根和跨设备拒绝。

## 8. 测试与真实验收

开发前回归（保留历史记录）：`test_dc_board_completeness.py`、`test_dc_board_source_probe.py`、`test_dc_board_raw_io.py`、`test_dc_board_silver.py` 共 **38 passed、5 warnings**。这些是前一轮审计执行的现行实现测试，非本轮文档修订重新执行的测试，不能证明本方案已实现。

以下为设计验收清单；已完成项与生产阶段保留项见 §8.1：

1. BK1754 式有效目录、有成员、无历史行情、两次稳定无行情：目录/成员保留，daily 不补行，核心通过且 metadata 完整记录等待分类，不产生新增 WARN check。
2. 等待多日后首次真实行情：核心 check metadata 的等待数量归零，Gold 首样本与 warmup 正确，CH 行数与 Gold 相同。
3. 曾有行情但目标日缺失：所有源裁决、writer、Raw/Silver check/readiness 一致阻断，失败不覆盖原文件。
4. 历史缺文件、不可读、必要列/身份/日期异常、扫描中变更、冻结后的资源预算超限：不可验证，不缩短范围放行；无关历史数值异常不触发新增全量质量重验。
5. 一次空响应、源重复变化、分页失败/重复键、请求预算不足：不冻结、不提交 run。
6. 无成员但有行情、有成员但无行情、全零但有行情：不得混淆成员、数值和覆盖语义。
7. daily-only 保留；member-outside-index 失败；既有已批准占位过滤保持。
8. Run config 全构造方迁移；旧 policy/digest 拒绝；当前日窗口和两次时间间隔边界；每 tick 最多一次请求。
9. 现有核心 check 名称、数量和日期绑定不变；合法等待的 passed=True 实际允许下游，成熟缺失的核心 ERROR 阻断目标日整体发布。
10. metadata 大规模截断可见、无静默丢明细；观察存储失败不回滚业务文件；check-only 重验不重写文件。
11. 历史补发后限定重采、Gold 后续区间 repair 与幂等读回，不能伪造此前不存在的行情。
12. bootstrap/readiness 与日更共用分类；物理日期审计不因等待 metadata 把存在文件改判缺文件；源预检阻断沿用 sensor 诊断，不新增事件台账。
13. 已找到历史行情即阻断，无需全部历史验证；未见行情必须有完整声明范围的否定证据；代码过滤、列裁剪和批量连接生效，不扫描历史数值宽表。
14. 64文件批次、代码/目标日并集上限、行数/文件字节预算、SQL及整体deadline、内存不足/禁止spill的正反边界；interrupt后connection清理，不发生跨批次timer泄漏。
15. 三个asset/config的日期/asset/版本/时间校验；有差集却缺第一快照、间隔不足300秒、源/历史digest变化必须拒绝；无差集不增加源稳定等待。
16. 下游独立证明与member末次复核；source请求从同一1,200预算扣除，不能偷偷额外重试；bootstrap确认超时/中断不影响已完成日期，旧报告不能冒充稳定证明。
17. source与Prod fingerprint按职责验证；仅index当前日要求Prod双快照；旧模型/builder和手工无证明入口静态清零。

隔离测试使用临时目录与 fake resources，不接正式 Lake/DG DB。开发后先定义加载与静态检查，再经授权做正式只读演练：记录 I/D/M 数量、分类、实际举证范围及否定证据完整性、请求/分页次数、源指纹两次时间、存在性查询峰值内存与耗时。以 1,032 个板块和当前 666 个历史 daily 文件为代表样本，按已补齐的 §4.2.1 资源阈值和 §4.4 请求模型验收轻量查询与 sensor 总耗时；未达标先优化批量读取，不加状态表，也不恢复全历史质量重验。

生产写入验收须另外获准：先限定 2026-10-08，核对 Raw/Silver directory/member/daily 实际计数、核心 check 及其覆盖 metadata、Gold/CH 对实际行情闭环，再决定后续日期与历史修复。不得为了验收重新写所有日期。

### 8.1 2026-10-09 实施对账

本次在 `dev-interface` 工作区实施；不创建分支，不修改 Prod ingestion、DatasetDefinition、业务/API 契约、物理字段、指标公式或 serving 行范围。CodeGraph 已用于入口、调用链、消费者及 Gold writer 影响面分析，并通过当前源码搜索补齐动态装配；开发后执行 sync/status。没有新增跨子系统依赖。

| 硬口径 | 当前代码落点 | 隔离验证 |
| --- | --- | --- |
| 真实目录和成员保留，daily 不补行；成熟缺失或证据不可验证则阻断 | `dc_board_quote_coverage.py`、`dc_board_relations.py`、Raw/Silver checks/readiness、Raw writer | `test_dc_board_quote_integration.py` 使用完整 fake source 和临时 Raw/Silver 验证 I=4、D=3、M=4、等待=1，核心失败数=0；追加此前行情后两层都阻断；既有占位/成员关系反例保留 |
| 必要存在性证据、批量复用、完整否定、正证据可提前结束；预算与扫描变更失败关闭 | `batch_board_quote_coverage`、集中 `run_contracts/dc_board.py` | `test_dc_board_quote_coverage.py` 覆盖单连接多日期、缺文件、坏 schema/身份/日期、行数/文件/代码/日期预算、deadline/interrupt、文件及日历漂移；异常退出清除未经末次签名核对的匹配 |
| 三类入口统一配置，源双快照不少于300秒；仅当前日 index 要求 Prod 双快照 | `DcBoardSourceFreezeConfig`、统一 builder/validator、`dc_board_source_freeze.py`、三类 asset/sensor/bootstrap | `test_dc_board_source_freeze.py`、sensors、config/static gates 覆盖299/300秒、窗口、漂移、错误版本/日期/asset、旧模型拒绝、无差集下游不等待；fake clock 验证离线确认与600秒超时 |
| 提升前复核，member 候选回读后末次复核；请求仍受既有总预算约束 | Raw 三 writer、bootstrap member streaming、`_promote_table(promotion_guard=...)` | raw_io、performance、integration 覆盖请求预算、定向确认、源漂移保留旧文件；1022个 member 代码假源测试包含前后源复核，仍低于1200次 |
| 复用现有核心 blocking check，不新增观察事件；覆盖信息不计质量失败 | 两层 daily core checks、`quote_coverage_metadata`、既有 runless events | completeness/checks/events/definitions/static gates 与 integration；通过结果含覆盖详情和样本，`source_confirmation=not_evaluated`；1200明细截断可见，样本长文本有界 |
| 候选仅放 staging，同文件系统原子提升 | `io/dc_board_candidate.py`；Raw/Silver、Gold 日更和限定 repair | candidate、各层 writer/repair 既有测试；正式根映射只 mock 路径检查，实际写入均为临时目录；非法根、跨设备提升拒绝 |
| bootstrap 完成一日即保存已有批次报告；重启重新观察，不复用旧证明 | `dc_board_bootstrap_apply.py`、共享源确认 | bootstrap_apply 新增批次20内第二日 KeyboardInterrupt：第一日文件/报告保留，重跑跳过第一日并完成第二日 |
| 首次真实行情按真实行计算，warmup 不补历史 | Gold 及 serving 保持现行实际行消费 | technical 新增 BK1754 首样本 `observation_count=1`、MA 未预热为空；既有 serving 与限定 repair 回归 |

隔离回归命令在 orchestrator 目录使用现有 `.venv/bin/python3 -B -m pytest -q tests/test_dc_board*.py tests/test_dc_daily_technical*.py tests/test_run_contract_configs.py tests/test_run_contract_static_gates.py --tb=short`，结果 **354 passed、121 warnings**。警告为既有 Dagster/Pydantic 弃用、preview/beta API 提示，不作为生产验收证明。最终 metadata 增加 `reason_code` 后补跑覆盖、集成和事件3组 tests，**23 passed、45 warnings**。

静态检查：致命错误规则 `E9,F63,F7,F82` 通过；本次新增及其余修改文件的默认 Ruff 检查通过。`run_contracts/configs.py` 的11条、`bootstrap/dc_board_events.py` 的2条默认 Ruff 提示与 HEAD 原有问题一致（DTZ007/TRY004），未借此变更其它合同的异常类型。文档链接检查与 `git diff --check` 通过；旧 DC index 冻结模型、builder、validator 与旧 Prod completion 函数在源码/测试中引用已清零。

正式 Lake 只读执行的是已实现的历史 helper，未连接正式 Dagster instance、Prod 或 Tushare，未写正式文件：

| 验证 | 范围/结果 | 实测 |
| --- | --- | --- |
| BK1754 目标2026-10-08 | 666文件，完整举证至2026-09-30；历史分类等待1、不可验证0；源确认未评估 | 34条SQL、482.566ms，最长212.828ms，峰值RSS232,144,896B |
| 容量边界 | 1200键×10日期合并，1连接；1031真实键、BK1754、168合成键；所有结果无不可验证 | 34条SQL、735.399ms，最长19.927ms，峰值RSS242,909,184B，符合当前阈值 |

容量场景把全部1200键当作假设差集来测分类，得到1031成熟缺失和169等待；这**不是**当天真实行情缺失数量。实际已知差集仍是 BK1754。数据摘要归档于 [实施验证报告](../../reports/dc_board_quote_coverage_implementation_validation_20261009.json)，不依赖 `/private/tmp` 长期保留。

尚需生产阶段验证：真实源两次快照的时间/指纹及实际请求量、正式 Dagster check 事件持久化和下游阻断、限定日期 Raw/Silver/Gold/local与Prod CH 计数闭环。当前未实际写正式 Lake/DB、修改 cursor、补事件、启动 run 或启停 sensor。历史补发只保留既有限定 repair 合同和回归，未执行全历史重验/重写；自动观察恢复和事件保留期限沿用现有机制。一个调用超过10个实际有差集目标日会按容量合同失败关闭，人工范围需限定在该上限内，不自动放大预算。

## 9. 推进边界

本轮开发授权已落实为代码及隔离测试，完整生产验收仍分阶段执行。下一步先做独立实施审计与限定 2026-10-08 的真实源双快照只读预检；只有门禁通过并获得明确生产授权，才能恢复正式链路或进行限定修复。不能把隔离测试、历史存在性只读结果当作完整源确认或正式恢复结果。

不改变业务子系统依赖矩阵；实现仅在 DG orchestrator 域内。主要风险是历史证据不完整导致误判、源端短暂缺失被过早放行、多个门禁迁移不一致，以及观察记录容量/保留期限。本文分别以存在性证据不可验证时失败关闭、稳定重复快照、共用判定与消费者测试、显式截断及现有保留策略处理；没有依据时继续等待，不把猜测写成行情事实。
