# DC 板块暂未形成行情的处理 LLD v1

> 状态：2026-10-13。原条件覆盖模型已实施（§8.1）；10 月 8、9 日数据恢复后的物理审计及 10 月 9 日 member 正式恢复见 §10.5。自动恢复次数、冷却与分类设计已按管理员指令写入 §10；§10.8 历史审计发现的身份载体冲突已按管理员确认在 §10.9 解决，§10.10 保留开发前复审，§10.11 保留开发、逐项对账与测试记录；代码已提交为 `8ecea622`，管理员重启 DG 后已上线，2026-10-11 19:13 正常运行只读检查通过。真实自动恢复链路待自然失败时验证，最小核验方式见 §10.12；10 月 12 日正常首次自动运行核验通过，未发生自然失败或自动恢复，结果见 §10.13。§8.1、§8.2 保留各自日期的历史记录，不代表当前发布阻断或新增机制验收。
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

新模型统一为 `DcBoardSourceFreezeConfig`，放在 `defs/run_contracts/configs.py`；替代 `DcBoardIndexSourceSnapshotConfig`，全部构造方和消费者同时迁移，不留旧模型兼容入口。index、daily、member 都绑定该类型。源证明阶段的集中构造函数为 `build_raw_dc_board_update_job_run_config(asset_name, partition_key, proof)`；后续自动恢复执行config的外层模型与新增identity入参以§10.9为准。asset_name 仅接受当前三个 Raw asset，返回对应 op config，不增加 job、CLI 参数或调度开关。bootstrap 用同一 proof 构造/校验函数调用 writer，不自行填写 observed_at。

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

### 8.2 提交后的限定恢复预检（2026-10-09 23:25）

实现已提交为 `6c58a145`，44个本任务文件；共享静态门禁测试仅提交DC相关hunk，其他资金流改动保留未暂存，未推送。随后按管理员“看看能否从10月8日开始恢复”的要求执行只读预检，不启动正式任务。

实际调用当前共享 `observe_dc_board_source`/`confirm_dc_board_source`，Prod 使用只读事务并限制SQL15秒/锁等待2秒，Tushare请求使用既有完整源分页门禁，历史使用正式Lake与独立512MiB/2线程/no-spill连接。两次源观察间隔超过300秒，全部源/Prod指纹及历史digest保持一致：

| 目标日 | Prod与源目录/行情 | Prod成员行数 | 源请求 | 当前分类/证明 |
| --- | --- | --- | --- | --- |
| 2026-10-08 | 1032 / 1031 | 94294，覆盖1032个板块 | 每轮4请求/4页/0重试 | BK1754等待1；666文件完整至2026-09-30；成熟缺失0、不可验证0；index冻结证明通过 |
| 2026-10-09 | 1032 / 1032 | 94563，覆盖1032个板块 | 每轮4请求/4页/0重试 | 无差集；当前日21:15及Prod双快照门禁通过 |

Tushare MCP另以完整显式daily字段核对BK1754：10月8日为空，10月9日已有真实行情（close=999.91、vol=139579、amount=566209341）。它可以在8日保留等待事实，在9日按首个真实样本进入Gold；不能回填8日行情。预检的coverage子结果仍标 `source_confirmation=not_evaluated`，两次源确认由外层冻结证明完成，两种证据不得混同。

当前物理审计确认两日各缺DC三类Raw、三类Silver、Gold共7个Lake分区，以及local/prod technical serving共2个分区；不是零行文件，也没有数据库未核验项。全catalog审计另发现资金流和跨市场缺口，本次恢复范围不包含它们。DC日期集合已注册这两日，无匹配更新run key；审计时无活动run。正式staging根可用且与Lake同设备，磁盘空间足够。

剩余发布门禁是加载范围：正式code location最后加载时间为2026-10-08 22:06:44，查询到的index配置仍是旧5字段模型，cursor仍报 `prod_completion_not_closed`。当前工作区还存在其他任务未提交的orchestrator改动；刷新整个location会一并加载，不能擅自将DC部署授权扩展到它们。需先由管理员/相应任务明确发布范围，再批准正式加载和限定两日恢复。所有DC链sensor目前RUNNING，加载后可能自行提交任务，因此reload属于正式执行阶段，不能当作只读操作。

建议按日期先恢复8日，再9日；各日期按Raw → Silver → Gold → local CH → Prod CH执行并读回既有核心check metadata及物理计数。三类Raw需在真正执行时重新取得各自有效证明；本次预检不是可跨事实变化重放的通行证。不修改Prod core、不补零、不重置cursor、不删除run key、不注册重复日期、不全历史重写。完整脱敏摘要见[限定恢复预检报告](../../reports/dc_board_quote_recovery_preflight_20261009.json)。本轮没有reload、sensor evaluation、job、materialize、事件补录、Lake/DB写入。

## 9. 推进边界（设计修订阶段历史）

本节保留当时的设计阶段边界；当前已上线，后续安排以 §10.12 为准。

原条件覆盖模型的开发与限定恢复已推进；§8.1、§8.2 是历史阶段证据，2026-10-11 恢复后的物理事实见 §10.5。当前下一步仅是审查新增自动恢复设计及补齐 §10.6 的开发前门禁；管理员本次只授权修订文档，没有授权开发、部署或正式执行新机制。原质量和写入安全门禁继续有效，不能把真实人工恢复结果当作新增自动恢复的验收。

不改变业务子系统依赖矩阵；实现仅在 DG orchestrator 域内。主要风险是历史证据不完整导致误判、源端短暂缺失被过早放行、多个门禁迁移不一致，以及观察记录容量/保留期限。本文分别以存在性证据不可验证时失败关闭、稳定重复快照、共用判定与消费者测试、显式截断及现有保留策略处理；没有依据时继续等待，不把猜测写成行情事实。

## 10. 自动恢复修订（2026-10-11，已上线，真实恢复待自然失败验证）

本节先按管理员“按建议修订原 LLD、先不要开发”的指令确定实施口径，随后获准开发；开发前审计历史保留在 §10.8/§10.10，开发阶段实施与验证见 §10.11，已上线后的正常运行检查和后续最小核验见 §10.12。只补齐 DC 日更的请求重试和失败分区恢复，不开启全局 run retries，不新增失败 sensor、状态表、事件台账或运营开关，不扩大历史质量扫描。§8.1 的已通过测试不能作为本节验收结果。

### 10.1 当前问题与修复范围

开发前 `resources.TushareResource.call` 对零列 DataFrame 抛出 `TushareResponseError`，这是正确的空数据保护；`tushare_request_policy.classify_tushare_error` 未识别该类型，落入 `non_retryable`。本机 SDK 的 `DataApi.query` 将 HTTP 400/401/403/429/5xx 等不成功响应转换成零列 DataFrame，丢失 HTTP 状态，因此不能把无字段响应描述为“已确认的网络临时错误”。现有 `test_tushare_resource_response.py` 已覆盖这些 HTTP 状态，但未证明请求策略对该异常会恢复。

开发前 DC Raw sensor 取得证明后总是提交 `job_subject:trade_date`；Dagster 对已使用 key 去重，包括失败任务。重新观察、重置 cursor 或再次返回相同请求都不会释放 key。该行为符合 [Dagster sensor 去重规则](https://dagster.io/docs/guides/automate/sensors#preventing-duplicate-runs)。

实施范围为三个 DC Raw 日更 job（index/member/daily）的统一恢复规则，以及 DC Silver 日更的活动任务和失败状态识别。Silver 不因本节自动重跑校验失败。Gold、serving、资金流及其他数据集不迁移；不得修改通用 `build_asset_update_run_key` 来改变所有调用方行为。共用错误分类器的所有调用方须回归，尤其完整分页、按代码分页、source probe 和既有周线异常分类消费者；不改变它们各自的自动调度次数。

### 10.2 两层次数与冷却时间

| 层级 | 确认值 | 如何计数 |
| --- | --- | --- |
| 单次请求重试 | 最多重试 3 次，即首次请求加 3 次重试，共最多 4 次调用 | 沿用既有策略；退避 1、2、4 秒，退避上限仍为 8 秒；每次调用、分页和重试计入本次 writer 请求预算 |
| 分区自动执行 | 同一 Raw job、同一交易日最多 3 次，包含首次执行，即最多 2 次自动恢复 | 首次为第 1 次，恢复为第 2、3 次；跨自然日、重启、reload 和 cursor 丢失均不重置 |
| 第 2 次执行冷却 | 首次失败结束后至少 600 秒（10 分钟） | 用失败 run 的持久化结束时间计算，不能用 sensor 发现失败的时间代替 |
| 第 3 次执行冷却 | 第 2 次失败结束后至少 1,800 秒（30 分钟） | 同上；缺结束时间或运行记录不完整则停止自动恢复 |

600 秒是现有 sensor 最小评价间隔，不是执行承诺；冷却满足后仍须等待实际 tick、源证明及排队。自动额度耗尽后不在次日重新获得额度。人工执行不消耗自动编号，但其活动、取消、失败和成功事实必须参与当前状态裁决；不得用人工执行重置既有自动额度。

每次 writer 保持既有 1,200 请求、600 秒预算，源复核、成员分页和请求重试继续从同一预算扣除。三个自动执行的 writer 请求上限为 3,600；sensor 的完整源观察另计，每次仍最多 16 请求。现有时间预算是阶段检查，不等于能够强制中断一个正在执行的 SDK 调用；验收必须记录实际总耗时和超限拒绝行为，不能宣称精确的 600 秒硬中止。

本节不持久化已成功板块的中间请求结果；分区恢复重新执行完整 writer。跨运行只补失败板块需要另行设计源一致性与 checkpoint，不能把不同时间的内存结果拼成正式文件。

### 10.3 失败原因与自动恢复资格

以下为拟实现的统一 reason code；当前旧事件不具有这些字段。请求重试资格和分区恢复资格必须分开保存，不能从异常类名字或一段 message 推导全部决策。

| reason code | 判定依据 | 单次请求重试 | 分区自动恢复 |
| --- | --- | --- | --- |
| `source_transient` | 已识别的连接中断、超时等临时源错误 | 有限重试 | 请求重试耗尽后可进入冷却 |
| `source_rate_limit` | 明确的限流证据 | 有限退避重试 | 请求重试耗尽后可进入冷却 |
| `source_response_unclassified` | SDK 未声明响应字段，HTTP 原因已丢失 | 有限重试 | 重试仍失败后允许有限恢复；不宣称已确认临时故障 |
| `source_permission_or_parameter` | 明确权限、积分、认证、参数或接口不支持证据 | 否 | 否，人工处理 |
| `source_or_data_contract` | 返回身份/日期/字段/主键错误、确定性行校验失败 | 否 | 否，人工处理 |
| `source_confirmation_pending` | 尚不满足已有源稳定证明 | 不新增分区运行 | 下一 tick 继续观察，不消耗执行次数 |
| `source_changed_after_freeze` | writer 复核发现源或历史证据漂移 | 不沿旧证明重放 | 否；阻断并人工复核，本轮不引入自动漂移修复 |
| `request_or_resource_budget_exhausted` | 请求、时间、分页、内存或既有资源门禁耗尽 | 否 | 否，不以新 run 获得新预算来绕过容量限制 |
| `blocking_check_failed` | 已物化文件的核心 blocking check 失败 | 不适用 | 否，不自动覆盖文件 |
| `manual_canceled` | 任一当前相关任务明确取消 | 否 | 否，尊重停止意图 |
| `unknown_or_infrastructure` | 无结构化证据、进程异常退出、依赖/挂载错误等 | 否 | 否，本轮不自动恢复未知或基础设施失败 |

有字段且零行的响应保留合法空返回语义；是否允许整日空数据仍由各数据集 writer 合同判定。不得把无字段异常改为零行成功，也不得将所有 schema 错误、`ValueError` 或未知异常纳入可恢复范围。SDK 丢失的 HTTP 401/403 可能与其他状态一并进入 `source_response_unclassified`，这是保留 SDK 的已知限制；最多有限重复，不保证这些状态立即停止。明确可见的权限错误仍立即停止。HTTP 传输重写不在本轮范围，不通过全局 monkeypatch 截获请求。

writer 必须在请求结果仍保有全部失败信息时计算恢复资格：只有全部失败均属于前三类、没有未尝试代码、没有总预算耗尽、没有结构校验失败，才可标记分区可恢复。不得只看最多 20 条展示样本；混合失败只要有一项不可恢复，整日即不可恢复。三类 Raw writer 和 source probe 的错误传播须保留类型化原因，不解析当前拼接字典的异常字符串。

使用 Dagster 既有 STEP_FAILURE 事件的结构化 failure metadata 保存：`failure_policy_version`、`reason_code`、`request_retryable`、`partition_retryable`、`failed_count`、`unattempted_count`、`request_count`、`retry_count`、`budget_exceeded`、`budget_reason` 和有界代码样本。恢复策略版本、自动尝试编号和来源失败 run id保存于§10.9的typed run_config；不写项目自定义run tags。失败资格只由STEP_FAILURE确定，config不承载retryable开关；事件id不进入run key。metadata 不能记录 token、原始 HTTP body 或无界源错误文字。状态记录不能替代文件事实，也不能回滚已经提升的业务文件；metadata 缺失时自动恢复停止，不能猜测放行。

### 10.4 sensor 决策、身份与观测

使用现有 sensor，依次执行以下流程：

1. 保持已有有界日期窗口和 readiness 判定。分区已就绪则停止；检查失败、坏文件或成功 run 与文件事实矛盾时返回人工复核，不以新编号覆盖。
2. 先查同一 job 的活动任务，再查目标日期的最近运行记录。活动查询覆盖人工、sensor 和 reexecution 任务，不仅匹配原固定 key；QUEUED、NOT_STARTED、STARTING、STARTED、CANCELING 等非终态均等待。未知状态停止自动判断。此检查在昂贵源观察之前执行。
3. 从持久化 run 记录读取最后状态、结束时间、失败资格、已消费自动 key 和人工停止意图。人工失败或未知失败不能被更早的可恢复失败遮盖。记录达到查询上限、事件不完整、编号重复或身份冲突时停止。
4. 无原始执行时使用现有首次 key；有可恢复失败时检查剩余次数与冷却。未满足则返回明确 skip。查询与源观察未创建 run，不消耗尝试次数。
5. 满足后重新走既有源观察与稳定确认，生成新证明；证明不完整则等待。源观察后、返回 RunRequest 前再次核对活动任务和尝试身份，避免观察期间已有人工任务启动。正式维护不得与自动运行并行；本节不承诺跨任意人工提交入口的原子互斥锁。
6. 首次 key 仍为 `job_subject:trade_date`。第 2、3 次调用既有 `build_repair_attempt_run_key(subject=job_subject, repair_scope_id=trade_date, attempt=2或3)`，不传按自然日变化的 scope，不用 UUID、时间或源指纹制造无限 key。恢复记录保留来源失败 run id，但不虚构 Dagster parent/root reexecution 关系；这是 sensor 新提交的恢复运行。
7. 同一待消费请求再次评价时复用相同编号与 key。已有 NOT_STARTED 或队列任务则等待 Dagster 原提交链，不另领编号。cursor 可丢失而不重置额度；持久化 run 存在才算消耗对应执行次数。
8. 成功后由物理 readiness 和已有核心 check 闭环，Silver 沿现有 sensor 继续推进。Silver 有失败记录时显示失败原因并停止，不另开自动恢复额度。

source 观察的旧 checkpoint 只按现有兼容性规则用于稳定时间举证；新恢复 run 必须取得当前完整证明，并由 writer 前后重新核验。不得直接复制旧失败 run_config 跳过观察。

cursor/skip 展示至少包含目标日期、`active_run` / `retry_cooldown` / `retry_exhausted` / `non_retryable_failure` / `legacy_failure_requires_review` 等决策、最后 run id、已执行次数、剩余次数、下一次最早允许时间及阻断原因。这些是现有观测载体的扩展，不新增行情事实或通知服务。

### 10.5 历史失败记录与上线迁移

不删除、改写旧 run，不清空 run key，不补造失败 metadata，不批量重跑历史。

| 历史情况 | 处理方式 |
| --- | --- |
| 旧首次 key 已存在，当前文件与检查已就绪 | 保留旧记录，停止；历史失败不触发恢复 |
| 旧首次 run 失败，文件缺失，缺本节结构化失败证据 | 记为 `legacy_failure_requires_review`，不能从旧异常文字或新一次源成功推断旧失败可恢复 |
| 旧 run 尚非终态 | 等待，不生成第 2 次 key |
| 旧取消、成功但文件缺失、编号/运行归属无法核清 | 停止并展示对应矛盾，人工处理 |
| 新策略运行失败且有完整失败证据 | 按本节分类、累计次数和冷却处理 |

旧首次固定 key 计为第 1 次自动执行；已带本策略身份的恢复运行计入第 2、3 次。历史人工 reexecution 不冒充自动编号，不重置自动次数；缺少身份信息且无法区分时停止自动恢复。管理员可按精确日期授权人工恢复，取得新证明并走原正式 job；这项授权不等于重新开放该分区的自动额度。

2026-10-09 原 member 失败 run `5cf410ae-7a9e-4218-9dde-673c9cc5a0f1` 属于旧记录，保留。2026-10-11 已人工恢复 Raw（`e95b31f2-1c4f-46da-92b2-f7ce133ca8c0`），Silver 随后由正常 sensor 完成（`88d24519-5d13-437d-806e-a1a7206d333c`）。两层各 94,563 行、1,032 板块，核心检查通过，BK1615 各 17 行；该日期已就绪，部署新策略时不得因旧失败再次执行。恢复后的按日物理审计在排除四个开发中资金流资产后，10 月 8、9 日均为 145/145 有实际数据；这不是全部数据集质量验收，也不是本节自动恢复已实现的证据。

上线前只核对当前有界窗口内相关失败、活动任务和已使用 key，不扫描全部历史。旧记录的只读清单与人工决策保留为发布证据，不新增运行状态事实表。Dagster run/event 的保留期限须能覆盖仍可能恢复的日期；记录被清理或关键身份不可验证时停止，不能把“查不到记录”当成新的首次执行。2026-10-11 当前配置与记录保留已核实（§10.8），额度可靠性限于记录未被外部清理的边界，不承诺永久保留或检测所有整段删除。

### 10.6 配置与实施点审计

下表保留开发前的配置审计与拟实施位置；当前落地结果见 §10.11，上线状态与后续验收见 §10.12。不使用 env、数据库或页面常量分散维护。

| 配置 | 默认值与位置 | 消费者、依赖与生效 | 运维可见与门禁 |
| --- | --- | --- | --- |
| 请求重试与 writer 预算 | 既有 `DC_MEMBER_MAX_RETRIES=3`、退避 1/2/4 秒、1,200 请求／600 秒；既有 DC contract 与共享请求策略 | writer/source probe，受总请求和时间预算约束；不新增设置 | failure metadata 和既有请求统计；重试/分页/预算边界测试 |
| `DC_BOARD_AUTO_MAX_ATTEMPTS`（拟新增） | 3，集中 `run_contracts/dc_board.py` | 三个 Raw sensor；依赖持久化 run 身份，不按日重置；definitions reload 后生效 | cursor 计数与 exhausted；初次/两次恢复/第四次禁止 |
| `DC_BOARD_AUTO_RETRY_COOLDOWN_SECONDS`（拟新增） | `(600, 1800)`，同一 contract | Raw sensor；依赖上一失败结束时间；reload 后生效 | next eligible time；599/600、1799/1800 秒边界 |
| `DC_BOARD_RECOVERY_POLICY_VERSION`（拟新增） | `dc_board_recovery_v1`，同一 contract | Raw asset failure metadata、sensor、typed run_config身份；不替代原行情覆盖 policy version | 版本不匹配/缺字段停止；旧记录迁移反例 |
| `DC_BOARD_RECOVERY_RUN_RECORD_LIMIT`（拟新增） | 20 条目标 job/date 记录；读取最多 21 条以判断溢出 | Raw/Silver 状态判断；命中第 21 条则停止，不无界补查；活动查询仅需取得一个匹配任务 | cursor `run_record_limit`；截断、历史人工运行密集样本 |

新增配置仅存于版本化源码；尝试身份存于typed run_config，不写自定义run tags；失败事实存于 STEP_FAILURE，cursor 保存观测投影。任何测试常量须从正式 contract 读取。改变次数、冷却或分类属于策略变更，必须同步本 LLD，不能由运营页面暗中调整。

拟改动：共享请求策略的类型化异常识别；DC Raw writer/asset 的结构化失败传播；三个 Raw sensor 的有界运行历史选择与恢复请求；Silver sensor 的活动/失败阻断；run contract、metadata/config builder 和相关测试；请求builder不新增自定义tags支持。必要公共异常类型放在 orchestrator 内独立小模块，避免让请求策略反向依赖装配资源；不引入 foundation/ops/biz/app 依赖。

开发前还必须同步 [run key 治理方案](./dagster-run-key-governance-optimization-plan.md) 和 [run key 治理 LLD](./dagster-run-key-governance-low-level-design.md) 的 DC 恢复消费者口径，按编码规范完成全部构造方/消费方与静态门禁审计。2026-10-11 已按后续授权同步两份治理文档，保留核验和开工结论见 §10.8；随后管理员已确认typed config载体，消费者口径与最终开工结论见§10.9/§10.10，§10.8只保留当时审计结论。需核验 Dagster 记录保留、运行查询限制及新旧策略上线的无活动任务窗口；不在文档阶段改变配置或正式状态。

### 10.7 开发阶段验收清单与推进顺序（历史）

以下保留当时的开发测试要求，已完成结果见 §10.11；不作为重新构造环境或重复测试的安排，当前后续核验仅按 §10.12。开发阶段要求覆盖以下相互独立的行为：

1. 单次无字段响应后成功、连续四次失败；有字段的合法空返回不被误判；显式权限错误不重试；已识别超时/限流有限重试。用安装 SDK 的 HTTP 替身证明 401/429/5xx 信息丢失边界，不能声称能够区分它们。
2. 一个或多个临时失败可恢复；混合确定性失败禁止恢复；超过 20 条失败样本仍用完整结果计算资格；预算耗尽、未尝试代码、错误日期/身份和源漂移禁止分区恢复。
3. 首次 key、两个稳定恢复 key；第四次禁止；跨日、重启、cursor 丢失和重复 tick 不重置、不重复领号；未消费请求不提前扣额度。
4. 所有非终态及人工活动任务等待；源观察前后活动核对；600/1,800 秒边界；结束时间缺失、记录溢出、事件缺失或版本不匹配停止。
5. 人工取消和未知失败停止；成功 run 与物理事实矛盾停止；旧失败无 metadata 不自动恢复；本文已恢复的 10 月 9 日不会因旧失败重跑。
6. writer 未通过校验不提升、既有文件不被失败覆盖；恢复成功后核心 check 与 Silver 推进闭环；观测状态缺失不能回滚已提交文件。

当时的推进顺序为治理/消费者对账、开发测试、静态校验，再安排限定正式验收。开发和上线现已完成；管理员最新决定为 §10.12 的自然失败最小只读核验，原“主动安排代表性日期验收”的方向不再执行。历史人工恢复不证明新自动链路，开发测试也不证明真实源必然恢复。

### 10.8 开发前补齐与审计（历史结论；2026-10-11，保留配置核验于 16:27）

本节保留typed config方向确认前的审计记录，载体阻断已在§10.9/§10.10解除；保留核验事实仍适用。本次按管理员要求只同步 run key 治理文档、核实记录保留并审计开工条件。没有开发、测试故障注入、加载定义、运行 job、修改 sensor/cursor、改配置或删除记录。完整有界结果归档为 [开发前审计证据](../../reports/dc_recovery_development_readiness_20261011.json)。时间是本次保留配置核验时点，不代表未来服务状态。

**治理同步已完成。** [run key 治理方案 §13](./dagster-run-key-governance-optimization-plan.md#13-dc-日更有限恢复增量2026-10-11已上线) 与 [治理 LLD §17](./dagster-run-key-governance-low-level-design.md#17-dc-raw-有限恢复身份2026-10-11已上线) 已同步三个 Raw subject、首次固定 key、恢复编号 2/3、无自然日 scope、三次总额度、人工运行边界及旧记录处理。通用 builder 不改签名，不改变其他数据集 key，原 M1-M9 完成状态不包含新增 DC 恢复。

**保留范围已做只读核实。** 正式目标为 `/Users/congming/.goldenshare/dagster_home`，现有项目环境 Dagster 为 1.13.18，`dagster.yaml` 使用 PostgreSQL storage，未配置 `retention` 或 `run_retries`。默认值和清理代码以安装版本为准；[官方 instance 配置文档](https://dagster.io/docs/deployment/oss/dagster-yaml)用于核对配置语义，不能用最新线上版本替代本机代码。

| 记录类别 | 当前核验结果 | 对恢复设计的意义 |
| --- | --- | --- |
| run、原生 run_key/partition tags、创建/结束时间 | 当前配置没有自动过期期限；六个 DC Raw/Silver job 均仍有 2026-08-31 样本 | 当前持久化范围覆盖本次恢复窗口；不是全历史完整性或永久保留保证 |
| member 原失败事件 | 旧失败 run及 STEP_FAILURE/RunFailure事件可读；limit=100，hasMore=false | 原始失败事实未因 tick清理丢失；旧事件仍缺新策略结构化失败资格，不能自动追认 |
| 10 月 9 日六个 DC job | 每 job读取最多21条，实际为1/2/1/1/1/1；member为原失败加人工成功恢复，未触及截断上限 | 当前有界查询能同时读到相关身份与时间，无需全历史遍历 |
| sensor tick | 本机默认只清理超过7天的 SKIPPED；其他sensor tick状态默认-1；schedule tick默认均-1 | tick与cursor不作为自动次数事实，SKIPPED清理不应重置额度 |
| 既有手工事件清理工具 | 股票分钟线、非分钟资产两类sample-delete均需显式确认，资产白名单不含DC；DELETE只针对check/materialization相关事件，未删runs/run tags/STEP_FAILURE | 当前源码工具不清理本方案所需DC恢复身份与失败证据；本次只读代码，未执行工具 |
| 已检查本机入口 | `Library/LaunchAgents`、`.goldenshare`下plist/sh/py/toml/yaml未发现匹配Dagster retention/delete的脚本 | 仅为已检查路径结果，不声称排除所有外部DBA、crontab或手工操作 |

保留约束为：只要 DC 日期仍能进入自动恢复窗口，就必须保留其首次/恢复 run、身份信息、终态时间及用于资格裁决的 STEP_FAILURE。不能把tick、stdout/compute logs清理等同于这些记录清理。当前无需新增TTL或状态表；未来清理、迁移或保留配置变更须先检查该依赖，不能把记录删空后让sensor重新当作第1次。

运行记录完全被外部删除且没有独立记录时，现有run历史本身不能证明“以前运行过”；文档不宣称系统能可靠检测所有整段删除。部分身份、事件缺失及截断要失败关闭；完全删除风险通过现行无自动清理事实与上述运维保留边界约束，重新部署前复核。若未来确需自动清理DC运行历史，先重新设计并获确认，不用本次方案兜底。

**开工审计结论：仍有一项设计冲突，暂不满足开始开发条件。**

| 开发门禁 | 结果 | 依据或剩余工作 |
| --- | --- | --- |
| 目标、范围、次数、冷却、分类、预算、历史处理 | 已明确 | §10.1–§10.7；不扩大数据集或全历史扫描 |
| run key治理同步与通用builder适配 | 已补齐 | 两份治理文档增量；CodeGraph确认沿用已有两个builder，不修改其他消费者输出 |
| 运行记录保留范围和真实有界样本 | 已核实 | 本节及归档证据；部署前复核属于上线门禁，不要求现在改正式配置 |
| 配置集中位置、读取上限、验收场景 | 已明确 | §10.6；新增常量尚未编码；限流、冷却、身份/事件缺失、旧记录、取消与截断均有测试要求 |
| 恢复身份持久化载体与静态门禁一致 | **当时阻断，已在§10.9解除** | 当时版本§10.3/§10.6的自定义run tags与现行禁令冲突；后续已确认typed config，不放开通用门禁 |
| 隔离实现/测试、definitions验证与正式上线验收 | 尚未执行 | 这是确认设计后的开发/发布阶段任务，不拿历史354/23测试或人工恢复结果替代 |

剩余冲突的代码证据为 `run_contracts/requests.py:build_run_request`（不接项目tags），治理LLD §1.2（禁止sensor写run tags），`test_run_contract_static_gates.py`（检查run_tags/tags写入）。开发影响面已经覆盖：三类Raw asset/config builder/source proof/writer、Raw sensor、Silver阻断、bootstrap与人工config构造、failure事件读写、共用错误分类器、run key与请求builder以及static gates；不改Prod/Wealth/业务分层依赖。

建议采用治理LLD §17.1的显式typed run_config替代自定义tags：保存`policy_version`、`automatic_attempt`、`source_failure_run_id`，原生Dagster key只与builder预期身份比对，不反解析执行参数；失败资格仍来自STEP_FAILURE。这会调整DC配置契约，尚待管理员确认。确认后须一次性修改本LLD §10.3/§10.6和治理文档的载体表述，补齐三asset、builder/validator、sensor、bootstrap/人工入口的消费者迁移与负向测试映射，清零自定义tags方案，不保留双轨；之后再做开工审计。此次未修改Python或现行契约，也不将该建议写成已批准。

### 10.9 已确认的 typed run_config 与全消费者口径（2026-10-11）

管理员已明确同意：typed run_config 保存恢复身份，STEP_FAILURE metadata 保存失败事实。本节取代 §10.8 历史审计的载体阻断结论；自定义 run tags 方案退出，不放宽禁止 sensor 写项目 tags 的门禁。以下模型和字段为已确认契约；当前 Python 实现与测试对账见 §10.11，正式执行尚未验收。

#### 10.9.1 配置模型与校验责任

集中于 `run_contracts/configs.py`，源证明与执行意图分开：

| 模型/字段 | 类型与默认值 | 来源、责任与拒绝条件 |
| --- | --- | --- |
| `DcBoardSourceFreezeConfig` | 保持现有 source proof 模型 | 只保存实际源/Prod/历史证明；原 `policy_version` 仍是行情覆盖版本，不放恢复编号或失败资格 |
| `DcBoardRecoveryIdentityConfig.policy_version` | 必填字符串，固定 `dc_board_recovery_v1` | 集中 recovery contract；不匹配拒绝，不默认补版本 |
| `automatic_attempt` | 必填整数，只允许 1、2、3；拒绝 bool/string/coercion | sensor 从持久化运行记录计算，不从 key解析，不供运营自由选次数 |
| `source_failure_run_id` | `str | None`；首次必须为空，2/3必须为非空真实run id | 指向同job、同partition、最近终态失败；来源失败资格、结束时间、冷却与次数须在实例记录中核验；不是event storage id |
| `DcBoardRawRunConfig.source_proof` | 必填 `DcBoardSourceFreezeConfig` | 三类Raw asset的执行config外层；日期/asset/覆盖policy一致性沿用原validator |
| `DcBoardRawRunConfig.recovery_identity` | `DcBoardRecoveryIdentityConfig | None = None` | 自动首次/恢复必须显式设置；人工正式执行无自动身份；None不是旧配置兼容入口，不授予自动恢复资格 |

对应 `ops.<asset_name>.config` 的唯一新形状为 `{source_proof: {...}, recovery_identity: {...或null}}`。不把恢复字段混入proof，不接受旧flat proof作为asset执行config，不同时支持tags和config两种身份。运行历史读取允许识别旧flat config为legacy记录，但不能将其转换成新自动执行授权。

统一 builder `build_raw_dc_board_update_job_run_config` 保留 asset/partition/proof 入参，新增可选 typed `recovery_identity=None`，序列化外层模型；三类asset签名同时迁移为`DcBoardRawRunConfig`。新增纯配置validator负责字段组合，原proof validator继续只校验源证明；关联run与运行来源核验使用单独有界运行记录reader，不能在纯config validator隐式连接instance。

自动身份还须与当前运行的原生sensor_name、job、partition及builder生成的预期run_key一致；第1次比对原fixed key，第2/3次比对repair key。这只是验证已有原生tags，不写新的tags，也不从key解析执行参数。人工reexecution的parent/root关系不能被当作自动编号；人工入口重建当前证明，并显式置恢复身份为空。手工复制旧自动config而伪称自动运行须拒绝，不改变已有run或补造来源关系。

sensor在生成请求前使用最多21条同job/partition记录核验额度、来源失败与时间；asset对带自动身份的运行在访问源/写文件之前再核验运行归属和来源身份。查询失败、截断、缺失败事件、来源不匹配、编号跳跃/重复、版本错误全部停止；不会因为config声明retryable而放行，config不包含可供调用方设置的retryable开关。运行历史查询成本有界，不全历史遍历；部署维护与自动运行仍不能并行，不声称能原子锁住任意人工入口。

#### 10.9.2 STEP_FAILURE 的唯一失败事实口径

由Raw asset边界把writer/probe的类型化失败转成Dagster `Failure`，在既有STEP_FAILURE保存§10.3的全部结构化字段；writer与probe不直接调用instance写事件。字段名固定为 `failure_policy_version`、`reason_code`、`request_retryable`、`partition_retryable`、`failed_count`、`unattempted_count`、`request_count`、`retry_count`、`budget_exceeded`、`budget_reason`、`failure_samples`。版本固定`dc_board_recovery_v1`，代码样本最多20条，裁决必须根据完整失败集合而非样本。失败计数/预算等使用可验证的实际统计；未知值保持不可恢复，不能伪造零值或true。

若底层异常没有完整类型化证据，保留原异常链并记录不可恢复reason，禁止从拼接dict/message恢复事实。sensor读取`step_failure_data.user_failure_data.metadata`，校验版本、类型、完整性与来源step；有多个失败step时只要存在无法核清或不可恢复失败，整run不自动恢复。核心check失败及已有文件异常不得被更早的writer可恢复失败遮盖。执行失败metadata不进入source proof、config、业务Parquet或额外台账；状态写入失败不能回滚已提交文件。

共用`TushareResponseError`及其判定须由orchestrator内纯异常契约承载，避免request policy反向import装配resources；全量迁移resource、共享分类器、周线异常消费者及相关测试，不保留旧分类双轨。已知HTTP信息丢失仍按§10.3有限处理，不把响应未分类升级为已知HTTP状态，不修改源参数/fields/pagination契约。

#### 10.9.3 构造方、消费方与验证映射

以下为已确认入口与同批迁移范围，实施结果见 §10.11；“保持”表示已核对语义后继续保留，不是遗留兼容层。

| 当前文件/入口 | 新口径与影响 | 必须覆盖的测试/验证 |
| --- | --- | --- |
| `run_contracts/configs.py`：模型、builder、validator | 新外层与typed身份；统一序列化；source proof原validator保持；禁止flat asset config | `test_run_contract_configs.py`：三asset、manual None、1/2/3组合、4/bool/string/空来源/错误版本/旧flat反例 |
| `sensors/dc_board_sensor.py`：`_source_freeze_result`及三个sensor | 从持久化run config计算累计编号、读取failure metadata、冷却，取得新proof后builder传入身份；不写项目tags | `test_dc_board_sensors.py`：初次/恢复/耗尽、时间边界、重复tick、cursor丢失、人工活动/取消、source观察前后核验、历史缺字段与21条溢出 |
| `assets/dc_board_raw.py`：三个Raw asset | 新外层config；自动身份/来源有界核验；只把source_proof传writer；asset边界形成STEP_FAILURE | `test_dc_board_raw_definitions.py`、新增隔离run/failure集成：自动归属/来源不符拒绝、手工无自动身份、失败事件完整且有界 |
| `assets/dc_board.py`：三个writer、member请求结果转换 | 仍收typed proof，不消费或决定automatic_attempt；保留全量失败类型/统计，供asset裁决；继续前后复核/原子提升 | `test_dc_board_raw_io.py`、`test_dc_board_performance.py`、集成：重试恢复、混合失败/样本截断、预算/未尝试/源漂移不提升 |
| `asset_guards/dc_board_source_freeze.py`：confirm/revalidate/offline confirmation | 只构造/校验纯proof；不从cursor/配置补自动身份；重验不被恢复意图绕过 | `test_dc_board_source_freeze.py`：proof字段不含恢复信息；300秒及漂移门禁保持 |
| `asset_guards/dc_board_source_probe.py`与共享`tushare_request_policy.py`、`resources.py` | 类型化失败与共同分类器；完整分页/按代码分页的请求重试受同预算 | `test_tushare_request_policy.py`、`test_tushare_resource_response.py`、`test_dc_board_source_probe.py`及共用probe消费者：合法空/零列/权限/限流、完整聚合失败资格 |
| `bootstrap/dc_board_bootstrap_apply.py:_raw_write`、`dc_board_bootstrap.py:export_dc_member_partition_from_prod_db`及CLI | 直接调用writer仍只传proof；不经过Raw job、不创建自动run config或消耗次数；保持逐日期checkpoint/流式导出和原CLI参数 | `test_dc_board_bootstrap.py`、`test_dc_board_bootstrap_apply.py`：证明复核保持、无自动身份、源预算计入、续跑不暗中领号 |
| DG Launchpad/既有GraphQL正式人工提交 | 使用统一builder生成新外层config与当前proof；recovery_identity=None；不恢复旧flat执行形状，不增加CLI或运营开关 | 配置schema隔离验证；人工运行参与活动/最新状态但不消耗或重置自动编号；旧run重放须重建config，不能照抄 |
| `sensors/dc_board_silver_sensor.py`、Silver asset/check/readiness | 不增加config或自动编号；有界活动/失败识别；物理就绪优先、校验失败阻断 | `test_dc_board_silver_sensors.py`与Silver/readiness回归：Raw恢复后正常推进、历史失败不复活、活动任务等待 |
| Raw/Silver checks、runless事件、catalog、物理日期audit、Gold/serving | 不消费恢复意图或failure资格；名称/schema/输出范围保持；config shape只影响Raw执行 | definition/catalog/static gates及既有相关回归；不要求正式补事件或重算全历史 |
| `run_contracts/requests.py`、`run_keys.py`及static gates | builder仍不写项目tags；通用key签名/输出不变；DC运行记录reader只读取原生tags/显式config | `test_run_contract_run_keys.py`、`test_run_contract_static_gates.py`：正向builder路径，负向自定义tags、手写/反解析key、旧flat执行口径；读取白名单仅按用途调整 |
| `stock_weekly_source.py`及异常测试支持 | 同批切到纯公共异常类型，周线原reason semantics和自动次数不变；不得为DC新增周线自动恢复 | 周线源异常分类的现有隔离测试及fake worker支持：schema异常归属保持，无新的HTTP外泄/重试次数 |

已按设计新增`defs/asset_guards/dc_board_run_recovery.py`及隔离`test_dc_board_run_recovery.py`，承载有界reader、纯选择与运行身份校验；纯共享异常契约集中`defs/tushare_errors.py`。恢复记录reader位于orchestrator内部的asset guard/纯选择模块，作为sensor与asset共同消费者；不会依赖Prod Ops/TaskRun或业务API。全消费者核对采用CodeGraph explore和当前源码搜索，已覆盖动态asset签名、序列化builder、bootstrap直接writer和测试构造；未发现业务/前端消费DC恢复config，不增加跨子系统依赖。

### 10.10 本次复审结论与阶段边界（2026-10-11）

以下保留开发前的历史复审；管理员后续已授权开发，最新结果见 §10.11。

**结论：文档与设计层面已满足开始开发的条件；尚未开始开发，尚未证明新机制可上线。** 管理员确认的typed config方向已同步本LLD及两份run key治理文档，§10.8的自定义tags阻断已解除，不保留tags/config双轨。设计约束、配置位置/默认、持久化载体、消费者迁移、性能预算、旧记录及正反验收场景均有明确映射，无待拍板设计项。

记录保留继续采用§10.8本次只读证据（16:27核验），本轮没有重复全历史检查或改变retention配置。当前无自动DC运行记录清理、关键失败事件可读的边界支持开发；部署前重验目标instance、关键记录及无活动任务窗口仍是上线门禁。

开发启动仍需要管理员后续明确指令。开发时在当前`dev-interface`工作区按上述范围推进，保留无关脏文件；不自行提交、建分支、安装或正式运行。先落配置/异常/记录读取契约与隔离测试，再迁移三个Raw sensor/asset和其他消费者，最后逐条对账、definitions与静态门禁验证。所有新增配置、旧flat执行口径和自定义tags方案须在同批清零。

本轮只做文档修改和静态代码消费者审计；文档完整性、相对链接与diff检查不证明Python实现或DG生产执行正确。原报告保留“当时阻断”的历史结论，本次另归档 [typed config确认后复审证据](../../reports/dc_recovery_development_readiness_typed_config_20261011.json)，不改写历史报告。正式失败—冷却—恢复验收和有限日期写入另获授权，不执行全历史重验/重写。

### 10.11 开发完成与逐项对账（2026-10-11，开发阶段历史记录）

**本节记录开发完成时点：开发与测试已完成，当时尚未上线。** 当前上线结论见 §10.12。 本轮在当前 `dev-interface` 工作区实现 §10.9 的唯一配置形状，没有提交、安装、reload、正式 sensor evaluation、job/backfill、分区或事件补录，也没有重写正式 Lake。此前的就绪审计报告保留不变，本次另存 [实现对账证据](../../reports/dc_recovery_implementation_reconciliation_20261011.json)。

| 已确认硬口径 | 当前实现 | 验证与反例 |
| --- | --- | --- |
| 三类 Raw job 共用 typed 外层；自动身份 1/2/3，人工 None，旧 flat 仅作历史 | `configs.py` 的两种新模型与统一 builder；`dc_board_raw.py` 三个签名 | 三 asset 的配置正例；缺 proof、旧 flat、错误版本、bool/string/越界编号、错误来源均拒绝；真实 Raw asset 临时执行 |
| 源证明仍独立，bootstrap 不领自动编号 | 三个 writer 仅收到 `source_proof`；原 proof/确认与 bootstrap 直接调用保持 | 原源稳定、漂移、bootstrap apply/续跑回归；proof 无恢复字段 |
| key 只作幂等比较，无项目 tags、专用 key builder 或反解析 | 两个现有通用 builder；新 reader 内直接生成预期 key 比对，不输出专用 key 函数；`requests.py`/`run_keys.py` 未改 | 重复 tick 同 key、来源字段独立、key/归属伪造拒绝；run key 单测及受保护静态门禁 |
| 单请求最多初次加三次重试，退避 1/2/4 秒，不另开预算 | 共用 classifier 识别纯 `TushareResponseError`；继续走同一个 bounded runner/session | 无字段四次调用及退避精确计数；合法有字段空结果；权限/参数、契约与本机文件错误不重试；共享消费者回归 |
| 失败原因分类与资格来自全部失败，不来自展示样本 | `dc_board_failures.py` 聚合完整 result；request policy 区分权限/参数、契约、未分类响应及已知临时错误；freeze 漂移保留明确 reason | 第 21 个失败为确定性错误时整日拒绝；预算/未尝试拒绝；样本最多 20，不包含原始消息；member 源观察与请求统计相加 |
| 失败事实只写 STEP_FAILURE；未知统计不能伪造零值 | Raw 边界 `Failure(..., allow_retries=False)`，保留 cause；probe/writer 不写 instance；无完整事实的字段为 null 且不可恢复 | 真实临时 Dagster run 写入/读回全部 11 个字段；逐字段缺失/类型错误、其他失败 step、事件截断均拒绝 |
| 日期窗口 10；运行记录正常上限 20，读第 21 条立即停止 | `dc_board_run_recovery.py`：同 job 活动查询 limit 2，目标日期 limit 21，不分页；每次失败事件同样 limit 21 | fake-client 核验过滤条件与调用次数；21 条运行/事件、has_more、查询失败停止；不扫描全历史 |
| 所有非终态（包括人工和其它日期）阻断昂贵源观察 | 同 job 的 QUEUED/NOT_STARTED/MANAGED/STARTING/STARTED/CANCELING 查询；物理 readiness 优先 | 全部非终态参数化反例；源观察前零调用、观察中人工任务启动后不提交；已就绪文件不复活旧失败 |
| 总共三次，冷却从失败结束时间计算，不因 cursor/跨日重置 | 纯选择从持久化身份累计；第二次 600 秒、第三次 1800 秒；原 key 只计历史首次 | 599/600、1799/1800 边界；重复 tick/cursor 丢失/跨日、缺结束时间、重复/跳跃编号；真实临时 instance 三次失败链与额度耗尽 |
| 来源为同 job/partition 最近失败，执行前再核验 | bounded reader 被 sensor 与 Raw 边界共用；核对原生 sensor/job/partition/key、remote origin 和 parent/root；source 观察后重查 | key/sensor/job/partition/origin/parent/来源编号伪造；中间人工失败和 legacy 来源链拒绝；三 asset 访问源前拒绝复制的自动 config |
| 历史缺证据、人工失败/取消、成功与缺文件矛盾需人工处理 | `legacy_requires_review`、manual/canceled、success/file missing、身份异常等明确 skip；旧事实不修改 | 历史缺 metadata、未知/确定性失败、最新人工终态不能被旧可恢复失败掩盖；没有删除/补造历史资格 |
| Silver 不增恢复次数；失败等待人工，Raw 就绪后自然推进 | 原 Silver key/配置保留，只加同 job 活动与目标日期历史保护 | Silver 自身失败/取消/活动/成功缺文件均阻断；就绪文件优先；原 Raw frontier/readiness 回归 |
| 没有新状态台账、资产、check、sensor 或全局 retry 开关 | 只在现有运行的 config/STEP_FAILURE 保存事实；未改 catalog/schema/paths/instance 配置 | 完整 `Definitions.validate_loadable`；受保护 catalog/static gates；正式状态操作未执行 |
| 公共异常与全部消费者同批迁移，边界不反向依赖 resource 装配 | resource、policy、周线和测试改读 `tushare_errors.py`；受保护测试导入白名单只加三个精确文件 | 周线原 reason/重试语义保持；共享 ETF/指数/分钟/资金流/BSE 请求策略回归；新增模块不依赖 Prod Ops/Web |

验证总计 **1088 项不同测试通过**：DC 与共享请求策略 917（完整组 916 加补充 transport 类型边界 1）、周线源 32、受保护静态门禁 113、受保护 BSE 消费者 26；另在最后 key 比对整理后重跑 125 项关键测试，均通过，不重复计入总数。35 个子测试另记，不冒充新增测试。资金流部分仅为共享分类器的隔离消费者回归，没有审计或恢复开发中的资金流数据集。

全项目 fatal Ruff（E9/F63/F7/F82）通过，新增模块及本轮新测试 Ruff 通过。三个已存在文件的完整 Ruff 仍有 13 项旧问题（configs 的 11 项、Silver sensor/test 各 1 项）；与 HEAD 基线比较没有新增 lint 问题，未为本轮改动扩大到其它合同的异常类型或时区改造。文档完整性与 diff 检查结果见实现报告。

CodeGraph 使用 explore、impact，并完成 sync/status；核验范围包括配置构造/消费、Raw/Silver sensor/asset、writer/probe、bootstrap、共享 classifier、周线以及测试启动器。图谱没有完整给出所有间接分类器消费者，已用当前导入与调用代码补核，不以图谱缺边推断无影响。不改变子系统依赖矩阵、Lake 路径、业务字段、CLI、通用 key/request builder、Gold/serving 语义。

开发完成时的后续安排（现已提交并上线，当前方向以 §10.12 为准）：复核目标 instance、记录保留和无活动任务窗口；人工 Launchpad/reexecution 使用新外层与当前 proof、身份为 None，不能复制旧 flat/自动身份。旧失败不补造恢复资格。没有通过本轮隔离测试证明真实源会恢复，也不声称跨人工入口原子互斥或永久保留全部历史。


### 10.12 已上线与正常运行验收（2026-10-11）

**已上线，正常运行检查通过；真实自动恢复链路待自然失败时验证。** 管理员重启 DG 后，19:13 的只读核验确认代码已加载并正常运行。依据为提交 `8ecea622` 和 [上线验收记录](../../reports/dc_recovery_online_acceptance_20261011.json)。这不是“全部正式恢复场景已验收”的结论。

| 核验项 | 当次事实 | 验收状态 |
| --- | --- | --- |
| 在线代码与配置 | `orchestrator` 为 LOADED；三个 Raw job 的 `ops.<asset>.config` 均使用必填 `source_proof`、可选 `recovery_identity`，身份包含约定三个字段 | 通过 |
| 六个 DC sensor | 当前来源为 `orchestrator`，均 RUNNING；重启后自然 tick 均为 `SKIPPED / all_ready`，无错误和任务请求 | 通过 |
| daemon 与活动运行 | 七个 daemon 健康、心跳无错误；全 DG 无活动运行 | 通过 |
| 当前数据 | 18:28—18:31 的独立只读物理核验为十个交易日 60/60 DC Raw/Silver 分区通过；19:13 六个 sensor 再确认就绪至 10 月 9 日，没有待恢复缺口 | 通过；19:13 未重复全量物理扫描 |
| 真实失败后的自动恢复 | 尚无新机制下的自然失败样本，未观察正式失败—冷却—第二次运行链路 | 待自然事件验证 |

管理员已确认不再为此构造隔离环境、模拟故障或执行额外验收任务。此前的开发测试证据保留，不安排重复测试；不删除、移动或损坏正式文件，不改 token/权限，不伪造失败事件，不补造旧 metadata，不重置 cursor/key，不手工重跑已就绪日期。当前无缺口，保持正常调度；本记录不创建轮询脚本或监控自动任务。

**最小核验只看首次自然失败后是否按规则产生第二次自动运行。** 后续出现自然失败时，按一个 Raw job、一个交易日读取既有事实，不主动触发 sensor evaluation 或恢复 run：

1. **确认失败有资格。** 首次 run 的持久化 `recovery_identity` 为版本 `dc_board_recovery_v1`、`automatic_attempt=1`、来源为空，归属与原生 sensor/job/partition/key 一致。读取该 run 全部有界 `STEP_FAILURE`，按当前 reader 核对完整 11 个字段、类型及统计；全部失败均可恢复，且没有未尝试对象、预算耗尽或其它不可恢复失败。旧失败缺新 metadata、人工失败/取消等不作为自动恢复样本，也不从错误文字猜资格。
2. **确认冷却。** 记首次失败持久化结束时间为 T0；第二次请求及 run 创建时间不得早于 T0+600 秒，执行开始时间同时记录。冷却满足后还需实际 tick、源确认和排队，不要求十分钟一到立即运行。未运行时先只读查看活动任务、源证明等待、窗口及具体阻断原因，不直接认定机制失败，更不手工提交来补验收。
3. **确认引用关系。** 第二次由同一 sensor 自动产生，job/partition 与首次一致；`automatic_attempt=2`，`source_failure_run_id` 精确指向首次失败 run；原生 key 与现有 builder 的第 2 次输出一致，没有重复运行。
4. **确认结果。** 若第二次成功，限定该日期只读核对 Raw 物理数据、既有核心 checks 和 Silver 后续状态；Raw/Silver 就绪后自然 tick 应回到 `all_ready`，不再提交恢复。若第二次仍失败，如实记录“第二次链路已观察、恢复未成功”；不为了验收制造第三次失败，第三次与耗尽路径仅在自然发生时另记，继续遵守 30 分钟冷却及三次总上限。

最小证据保存 job、日期、首次/第二次 run ID、身份字段、失败 metadata、T0、第二次请求/创建/开始时间及相差秒数、结果和限定日期物理核验。仅观察请求尚未建立 run 时，不宣称运行链路通过；仅确认第二次建立但未成功时，不宣称数据恢复成功。没有自然失败时长期保留“待自然事件验证”，不以等待结束冒充通过，也不影响“已上线、正常运行检查通过”的现有结论。

本次仅更新文档和归档既有验收证据，没有新增环境、代码、配置、依赖、Dagster 操作或正式数据写入；不改变原恢复条件、次数、冷却或人工入口合同。


### 10.13 10 月 12 日正常首次运行核验（2026-10-13 09:05，只读）

**正常首次自动运行通过；真实自动恢复链路仍待自然失败验证。** 本节归档已完成的只读查询，不执行额外任务。完整运行身份、run ID、请求统计和既有核心 check 结果已追加到 [验收记录](../../reports/dc_recovery_online_acceptance_20261011.json) 的 `normal_first_run_followups`；10 月 11 日的上线证据保持不变。

| 10 月 12 日数据集 | Raw / Silver 运行 | Raw 请求内重试次数 | Raw / Silver 核心 checks |
| --- | --- | --- | --- |
| DC index | 各一次，均 SUCCESS | 0 | 均通过 |
| DC member | 各一次，均 SUCCESS | 0 | 均通过 |
| DC daily | 各一次，均 SUCCESS | 0 | 均通过 |

三个 Raw run 均由对应 sensor 自动提交；typed 外层含 `source_proof`，恢复身份为 `policy_version=dc_board_recovery_v1`、`automatic_attempt=1`、`source_failure_run_id=null`。job、partition、sensor、原生 key 与第 1 次身份一致，parent/root 为空，原生 remote origin 为对应 `orchestrator` job。三类 Raw 请求内重试均为零；六个 Raw/Silver run 均未观察到 STEP_FAILURE。

同一 job/date 的有界查询各只返回一条记录，没有截断，也没有第 2、3 次恢复 run。因此 10 月 12 日没有自然运行失败，分区自动恢复没有触发；没有首次失败结束时间或第二次运行可用于核验冷却及身份引用。这两项明确记为“尚未观察，待自然失败验证”，不能算通过；本次只确认新机制正常首次执行路径。

后续继续按 §10.12 的最小方式，在自然失败出现时只读检查失败事实、至少 10 分钟冷却和第二次自动身份引用；不为了验收构造环境、故障或运行。以上均为 10 月 12 日任务在本次审计时点的事实，不代表以后日期不会失败。本次文档补录不改代码、配置或恢复策略，不触发 sensor evaluation/job，不修改正式数据及状态。
