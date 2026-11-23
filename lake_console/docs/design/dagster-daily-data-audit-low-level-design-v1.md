# 财势乾坤本地 DG 每日数据审计 LLD v1

第一阶段详细设计及 DG 样本读回已完成。第二阶段实现见 §12。业务依据为[每日数据审计方案](dagster-daily-data-audit-wealth-data-center-plan-v1.md)和[逐资产规则](dagster-daily-data-audit-rules-review-v1.md)。本文中的新增文件、字段与接口是实现约定。现有代码用链接标出。

## 1. 目标与交付顺序

让财势乾坤和下游程序读取本机 DG 的同一份结论。每天按资产分别判断是否按要求更新、是否有证据证明齐备。先用正常交易日跑通「产出和 Check → DG 每日总结 → 本地页面和下游查询」，再接入已列明的生产 Check、东方财富板块分类核查、通用指数分钟线独立审计。

| 交付阶段 | 代码落点 | 阶段完成条件 |
|---|---|---|
| 每日总结与读取 | DG 证据读取、规则和汇总 job。本地 Web 路由、数据中心卡片和列表。 | 现有当日检查可复用，两列状态和日期切换正确，下游按同一版本取结论。 |
| 生产 Check | 第 5 节列明的现有生产者、检查和 readiness。 | 同日同版、晚到和真实缺口判定通过，已有生产门禁继续有效，代表性样本的增量有据可验。 |
| 东方财富板块分类 | 第 6 节的分类比较、标准集与源端复核，并接入已设计的页面动线。 | 名单相同可留档，真实增减可确认，源端证实漏采时拒绝确认，补齐后可继续。 |
| 通用指数分钟独立审计 | 第 7 节的本地 DG 独立 job，结果进入每日总结。 | 先在 DG 验一个代表资产的单日范围、同版证据、读取开销和结果读回。自动提交需单独确认。 |

资产盘点从本机 DG 目录取值。当前基线共 187 个资产键，130 项优先复用、33 项在生产补证据、12 项走独立审计或待开放、12 项一期齐备不适用。实际实现与测试以目录键和两份方案的逐项映射为准。运行边界是本机正式 Lake `/Volumes/datasource/data_lake/{raw,silver,gold}`、本机 DG 事件和本机交付。Prod 发布目标与环境健康保留范围说明。国际指数日线两层分别列为一期不适用。审计记录写在 DG，业务文件及发布仍由原入口负责。

## 2. 编码入口和读写边界

| 位置 | 现有入口与拟新增实现 |
|---|---|
| DG 注册 | [definitions.py](../../orchestrator/src/orchestrator/definitions.py) 自动加载 `defs`。新增 `defs/daily_data_audit/`，`registry.py` 挂接资产规则，`evidence.py` 读取有界记录和核对身份，`summary.py` 生成状态及发布模型，`jobs.py` 注册汇总和阶段内的任务。板块与独立核验分别放在该目录下的 `dc_index_review.py`、`index_minute_audit.py`。公共业务入口使用下述 job 与结果模型。 |
| DG 调度 | 汇总 schedule 固定使用 `Asia/Shanghai`。生产补 Check 使用各生产链现有选择及依赖就绪机制。独立审计由正式队列启动单独 run，轮询和网页版接口不直接执行检查函数。正式实例当前为 `QueuedRunCoordinator`、`max_concurrent_runs=1`，本文复用该队列，验收时再次核对。 |
| 本地 Web | 在 `src/app/runtime/data_audit.py` 组装本地审计服务与路由，由 [web/app.py](../../../src/app/web/app.py) 条件挂载。沿用 [DataCenterError 处理](../../../src/app/runtime/announcement_archive_lifespan.py)、[数据中心 modules](../../../src/biz/api/wealth/data_center/home.py) 和 [Web 鉴权](../../../src/app/auth/dependencies.py)。`src/biz/api/wealth/data_center/data_audit.py` 管请求与响应，`src/biz/services/wealth/data_center/data_audit.py` 管读取和操作。Web 与 DG 通过现有本地 GraphQL 连接，DG 业务模块仍在自己的运行环境。 |
| 财势乾坤 | [DataCenterPage.tsx](../../../wealth/src/pages/data-center/DataCenterPage.tsx) 接受 modules 返回的卡片。[WealthRouter.tsx](../../../wealth/src/app/routes/WealthRouter.tsx) 注册 `/wealth/data-center/data-audit`，沿用现有 [请求封装](../../../wealth/src/features/data-center/api/dataCenterApi.ts)。新增 `wealth/src/pages/data-center/DataAuditPage.tsx` 及板块核查弹窗，按已评审的 Figma 动线复用现有数据中心组件和样式。 |
| 下游程序 | 本机 DG 内由 `evidence.py` 提供 `get_completeness(scope, version)`。本机进程外可读同一个资产详情接口，用自己实际使用的范围和版本比对返回值。依赖方仅在范围及全部版本相符、状态为已确认齐备时继承其范围。 |

仿照现有 `announcements_enabled(settings)` 的部署判定，显式 `APP_ENV=dev/local` 与默认关闭的 `WEALTH_LOCAL_DATA_AUDIT_ENABLED` 同时成立才开放。由同一判定控制 modules、Web 的 SPA 直达地址与 API 挂载。DG GraphQL 连接使用已确认的本机回环地址和固定 `/graphql`，禁止从请求接收地址、任意查询、job 名或文件路径。Prod 不挂路由，直达页面返回 404。已启用而 DG 连不上时入口仍可见。读接口使用 `get_current_user`，东方财富概念板块的源端复核及标准集确认使用现有 `require_admin`。DG 内重查对应日期和产出版本。

## 3. 资产规则、证据与状态

### 3.1 资产和日期

`registry.py` 遍历 [list_lake_asset_catalog_entries](../../orchestrator/src/orchestrator/defs/catalog/lake_assets.py#L4166)，从目录取 `asset_key/dataset_id/dataset_name/layer/partition_model/blocking_check_names`，频度从已注册的频度和资产合同取。应更日复用各资产定义和生产调度已有的日期判断，不新增更新频率表。主要指数周月线复用[现有调度的日期判定](../../orchestrator/src/orchestrator/defs/sensors/index_period_update_job_sensors.py#L63)和[产出记录的实际截至日](../../orchestrator/src/orchestrator/defs/assets/index_period.py#L214)。按[方案表 §4.1–4.4](dagster-daily-data-audit-wealth-data-center-plan-v1.md#4-csv-复核及按当天数据量分流)分流，使用[逐资产 §3、§5](dagster-daily-data-audit-rules-review-v1.md#3-原方案-73-项逐资产待评审规则)落实具体资产键、附加检查、所用日期和有效范围。目录的阻断检查名单不能代替齐备规则，ETF 非阻断覆盖检查须显式读取。目录差集测试要求一键一行、只有一种归属、无遗留规则指向未登记键。未知规则或缺证据的资产仍显示，并保留待确认原因。

| 日期形态 | 怎样解析所选日 `D` |
|---|---|
| 日更、分钟、当日指标或本机交付 | 按适用交易日与起点，使用已注册日期分区或同日增量发布/生效证据。频度独立。只读取当前分区或该业务日提交的记录。 |
| 自然日公告 | `D` 对应公告自然日。复用同批分页交付及明确合法空的证据。 |
| 周月和按年存放 | 先按源合同算应更新日、当期分区及应到实际日。多个日共用物理分区时，以该业务日发布记录的实际覆盖日至 `D` 核对日更。主要指数周月 Raw 与 Silver 的特例见第 5 节。 |
| 全量快照与固定事实 | 先判当天是否有必须刷新/生效要求。指数基础信息和股票基础信息按各自日更要求。其他快照用 `D` 适用的发布版本和保留证据。旧版仍适用时可显示它的原核验结果。 |
| 仅更新与一期范围外 | 股票曾用名 Raw、停复牌 Raw/Silver 查当日更新与现有 Check，齐备固定为不适用。其余见[一期不适用清单](dagster-daily-data-audit-rules-review-v1.md#53-一期齐备不适用原-9-个)。国际指数日线一期没有专门的到期规则，有已绑定的本地交付可显示证据，无法核实应更日期时更新显示「无法确认」。 |

交易日与上一交易日复用现有本地 SSE 日历发布证据。读取失败时应更规则未知。日期表达在 API 使用 `YYYY-MM-DD`，跨午夜及有效时点统一由上海时区计算，DG 物化分区格式由各资产合同转换。

### 3.2 结果契约与版本绑定

| 字段 | 含义与约束 |
|---|---|
| `scope` | `asset_key`、`business_date`、`partition_key`、`as_of_date`、`frequency`、`coverage_scope`。业务日和实际截至日分开。无频度、未确定分区或未知截至日用 `null`。 |
| `version` | `target_version`、`inputs[]`（输入资产或事实、适用范围、实际读取版本）、`rule_version`。取自该生产链已有的正式发布身份、文件身份、冻结名单标识或经批准的事实版本。事件存储 ID、run ID 用来按记录定位和证明引用，不能单独充当产物版本。 |
| `update` | `status`、`expected_date`、`published_at`、`deadline_at`、`reason`。时间返带时区的 ISO 8601，未记录用 `null`。 |
| `completeness` | `status`、`reason`、`checked_at`、`expected_count`、`actual_count`、`missing_count`、`extra_count`、`samples`、`exceptions`、`evidence[]`、`components[]`。计数无法证明时为 `null`，已知零用 `0`。`evidence` 给出证据类型、Check 名、对应 DG run/记录及其版本。分类子项与分钟 Raw 盘后分别作为组件，独立保存状态和原因。 |
| `reason` | `code`、`message`。根据实际证据至少区分 `upstream_pending`（等待上游核验）、`upstream_gap`（上游有缺口）、`upstream_parity_only`（已核对上游，上游齐备待确认）、`reference_missing`（参照标准集缺失）、`manual_review`（需要人工核查）、`version_mismatch`（版本无法关联）、`not_verified`（未核验）和 `not_in_scope`（不在适用范围）。详情复用原 Check 错误和合法例外证据。 |

例如某交易日东财个股资金流向 Raw 已交付，但覆盖 Check 仍缺同日股票日线证据。该行 `update.status=updated`、`completeness.status=pending`、`reason.code=upstream_pending`，覆盖计数为 `null`。原 Check 已核的范围可展示在 `evidence`。日线齐备后使用已发布的资金流向版本做覆盖，再写入真实计数和结论。

按下面的顺序核定证据。

1. 解析该日所需的资产、分区、实际截至日及规则范围。读取最近的适用发布，按资产合同核对正式交付或合法空。只在合同规定范围内比较目标身份，并保留实际发布时间。
2. 查该候选正式版本对应的已结束 Check 和发布前证据。检查名、分区和 Check 所绑定的真实物化一致后才取覆盖字段。使用已有 [同版 Check 匹配](../../orchestrator/src/orchestrator/defs/sensors/index_period_daily_readiness.py#L32) 和 [交付指纹示例](../../orchestrator/src/orchestrator/defs/asset_guards/moneyflow_delivery_readiness.py#L56)。不能先过滤成功结果再找最后一条。发现较新失败、已换版、原地修改无法证明身份或历史清理后只剩计数时，按当前实际可证范围判定。
3. 由生产者的元数据把 Check 绑定到该次实际输入和规则版本。缺字段先判待确认。已有等价的较小身份校验才核身份，避免用日报复算整个目录的文件指纹。旧日期的原文件已被替换时，只用保留的当时证据，不能拿当前文件冒充。
4. 依赖已确认齐备的执行先比较必需输入的身份。只有全部匹配且上游已齐备才做下游覆盖读取。上游无证据或有缺口时记录所缺的依赖，保留下游的更新状态。若已有同版转换 Check 可展示「仅与上游一致」。下游消费同样核对自己实际使用的版本，不能拿按日期返回的最近一条绿灯套到其他版本。

### 3.3 两列状态与汇总

| 字段值 | 决策顺序 |
|---|---|
| `update.status` | 不要求更新 `not_required` → 在要求更新的情况下有实际适用交付为已更新 `updated` → 应更条件、应到日或交付情况不能证实为无法确认 `unknown` → 已确认未交付且观察时点早于 `D+1 00:00` 为尚未到期 `not_due` → 已确认未交付且到达或超过界线为超期未更新 `overdue`。迟到交付后变为已更新，仍保存其实际时间。 |
| `completeness.status` | 先识别不适用 `not_applicable`。对适用范围，有同版对账证实缺键或不允许多键时为已确认缺口 `gap`，满足本资产全部规定证据时为已确认齐备 `complete`，其他为待确认 `pending`。单一任务成功、空文件、合同未确认、仅对上游、依赖缺口和普通检查失败均不可直接替代范围对账。 |
| 东方财富板块分类父行 | 行业、地域、概念中任一确认缺口 → 缺口。有待确认而无缺口 → 待确认。适用项全部齐备 → 齐备。全不适用 → 不适用。明细保留概念项，汇总每个分类资产键只计一次。 |

生成时对目录主行聚合四项，前三项之和是适用资产数。Raw 股票分钟线的常规通过仍用 `complete`，显示「已确认齐备（常规时段）」。盘后状态独立。对仅考核更新的资产，必须使用各自实际更新证据，齐备的「不适用」不改变更新列。

### 3.4 运行、存储、失效

- `daily_data_audit_summary_job` 输入 `business_date`，刷新受影响条目时另传 `changed_asset_keys`，运行开始记录 `observed_at`。由本地 DG schedule 在上海时间每日 00:00 对上一自然日提交一轮。首轮以实际观察时点看到的证据判定，若 00:07 已交付而汇总到 00:12 才开始，直接显示「已更新」和实际发布时间 00:07。每个资产按现有规则确定该日是否适用。停机时保留未生成。由获准的操作按单日补读已有记录，`generated_at` 是实际写记录时间。无法重建当时状态的项标未核实。
- `evidence.py` 将 `(资产键, 分区或无分区, 规定检查名, 所选日/截至日)` 构造为请求集合。DG 使用现有 SQL event storage，参考 [股票周月批量证据](../../orchestrator/src/orchestrator/defs/asset_guards/stock_period_silver_readiness.py#L46) 和 [完成 Check 查询](../../orchestrator/src/orchestrator/defs/asset_guards/stock_period_check_evidence.py#L25)。按实需选择有索引约束的分区组和无分区快照组。只纳入观察时点已存在的证据。先找到适用交付范围内的候选物化，再取已结束 Check 并核关联。快照/同物理分区的日交付必须匹配已有交付记录中的实际日期。依赖范围另由规则解析。每批出错只影响涉及行。只有证据足以确认没有交付才判未更新，事件读取失败时留无法确认。页面读接口不遍历各资产事件。
- 结果使用现有 Dagster run/event 承载。各 job 在最终步骤用 `add_output_metadata` 保存 `MetadataValue.json`，步骤输出 `Nothing`。汇总标签 `data_audit_summary` 含 `schema_version=1`、`business_date`、`observed_at`、`generated_at`、`rows[]`，带出每行的证据及观察时间。独立核验、标准集、源端复核分别用 `data_audit_result`、`dc_index_standard`、`dc_index_recheck`，包含范围、版本及该任务结果。查询按固定 job、`audit/business_date` 标签和必要范围标签筛 run，再按 run ID 读取命名元数据。仅 SUCCESS 且完整解码、与标签和输入版本吻合的记录可消费。独立核验任务失败、取消或中断只显示运行结果，没有成功输出时无可复用结论。标签表示定位范围，原生运行和事件 ID 用于定位与顺序。发布契约为原生记录，验收须证实可通过此路径读回及保留。若实际清理策略或元数据承载不能保存所需记录，先报告具体缺失与影响，另行评审存储。
- 迟到交付、Check 完成、版本更换和补审结果由本机 DG 的汇总刷新传感器读取有界的相关记录变动。该传感器只提交总结更新。先等该日已有总结，按变更影响的资产及依赖关系刷新相应条目，其余行沿用各自原观察时间，并追加同日新总结。东方财富标准集确认及其后续 Check 结果按[第 6.1 节](#标准集确认后的状态刷新)限定日期、资产和字段。旧总结保留。相同观察时点的结果按已完成 run 顺序选最近者，始终展示 `generated_at`。旧版记录按其观察时点展示。新输入未核验时不可读取旧记录为新版绿灯。
- 使用现有本机 Dagster GraphQL 形态。读使用 `runsOrError(filter: RunsFilter, limit: ...)`，过滤字段 `pipelineName/tags/statuses`，再用 `logsForRun(runId, afterCursor, limit)` 的 `EventConnection` 取指定 `ExecutionStepOutputEvent` 下的 `JsonMetadataEntry`。财势乾坤只为东方财富概念名单核查和标准集确认调用 `launchRun`。只针对指定日、固定 job 和选中 run 做有界读取。专用 job 保证只输出固定数量的步骤及结果。未读到完整结果时显示不可读。队列与调度语义见 [Dagster schedules](https://docs.dagster.io/guides/automate/schedules) 和 [Dagster sensors](https://docs.dagster.io/guides/automate/sensors)，本机连接依据[本地运行手册](../architecture/dagster-local-operations-cheatsheet.md)。

## 4. 本地 API 和页面

路径统一在 `/api/v1/wealth/data-center/data-audit` 下。页面读取汇总和详情。人工操作只用于东方财富概念板块名单的源端复核及 Raw 标准集确认。通用指数分钟独立任务由本机 DG 执行，页面读其结论。

| 方法与路径 | 请求、结果与错误 |
|---|---|
| `GET /days/{date}` | 返回 `state`（`ready`、`not_generated`、`unavailable`）、`business_date`、`observed_at`、`generated_at`、`summary`（四项数量）、`rows`（主行及可显示子项的状态和简要原因）、`can_operate`。仅请求所选日最近有效总结。有已经读到的同日结果且连接中断时保留其时间并标不可用。 |
| `GET /days/{date}/assets/{asset_key}` | 读取同一个总结或所选日指定 `summary_run_id` 的该资产详情。返回第 3.2 节结果及来源链接。明确提供所用输入版本，客户端可以验证本次读取和既有结论是否一致。 |
| `GET /days/{date}/assets/{asset_key}/board-standard` | 仅分类资产。返回适用参照版本及代码、当日有效代码与增减、当日标准集（若已生成）和逐项 Tushare 结果。Raw 返回用于复核和确认的 `review_version` 及可确认状态，Silver 展示结果。 |
| `POST /days/{date}/assets/{asset_key}/board-recheck` | 仅东方财富板块分类 Raw 的概念名单。输入 `review_version`，失败项重试时加 `retry_run_id`。提交对当前差异的源端复核，返回 `run_id/status`。服务端从版本记录推导代码差集。 |
| `POST /days/{date}/assets/{asset_key}/board-confirm` | 仅东方财富板块分类 Raw 的概念名单。输入 `review_version`，按该版人工确认差异并保存标准。存在已证实的本地缺码或参照变更时拒绝。返回 `run_id/status`。 |
| `GET /runs/{run_id}` | 只读取东方财富概念板块复核、标准集确认这两类任务，返回进度和结果。 |

`POST` 成功受理返回 202。版本变更、存在已证实缺码或标准集不可保存用 409 与具体 `code/message`，非法范围或日期用 422，未知资产或任务用 404，操作权限不足走已有 403。DG 连接失败时查询显示不可用，提交返回 503。日期与列表读取沿用已有数据中心请求层。源端复核展示每个请求项的结果。

页面保留 `selectedDate`、`updateFilter`、`completenessFilter`、`page`。日期选择重新读取所选日，切换时舍弃晚回的旧请求。明细在该日结果内按两列筛选，组合后显示匹配数。点击任一齐备数字时保留日期、设对应齐备筛选、重置更新筛选为「全部」、页码为 1、定位明细标题。汇总一直显示当日主行数。东方财富概念板块行使用完整名称，与其它行左对齐，继承对应分类资产的层与频度。附属行只在相符筛选且其父资产已进入结果时展示，详情仍可见所属各类别。明细的状态原因和详情的范围、例外、样例均读接口，空字段显示「未记录」。详情链接使用固定本地 DG 地址。缺本日记录显示「未生成」，本地 DG 不可用时可继续注明已读到的同日总结时间。

## 5. 生产 Check 的实现清单

已有生产 Check 的读取、判定和阻断规则维持现状。新增下游审计优先复用上游当天齐备、下游当天交付和任务成功的记录。已确认须比代码或行数的资产，只在当次生产已有统计或已读日内数据上比较。新增审计禁止重新打开行情或指标文件、重算、跨日扫描或为日报单独重跑重 Check。现有证据不足时显示「待确认」。

覆盖结果附在现有 Check 的元数据中，供数据审计汇总和页面读取。每个结果带 `scope/version`、实际运行的规则、覆盖计数及身份引用。上游未就绪、参照未确认或身份无法对应时，该项审计记待确认。原 Check 的通过条件及下游生产就绪条件照旧。新增覆盖发现差异时只记录审计结论，已明确批准的阻断只有本节列出的本机 ClickHouse 板块日线技术指标的真实键差异，以及主要指数周月 Silver 写入前的截至日和覆盖校验。依赖就绪后使用对应生产调度只补查该日、该版产出。

先用生产调度已有的依赖检查。如果目标尚未产出，依赖成功后走原生产 job，检查随该次产出执行。如果目标已产出、相应覆盖字段为待确认，则由该资产生产传感器在既有业务日期窗口比较当天目标版本、最新依赖证据和已有覆盖结论。依赖可用时提交当天、该资产的检查选择，使用仅选现有 Check 的方式，运行参数显式给分区和目标版本。资金流依赖的接线使用 [moneyflow_update_selection.py](../../orchestrator/src/orchestrator/defs/sensors/moneyflow_update_selection.py)，分类及参照依赖使用 [dc_board_silver_sensor.py](../../orchestrator/src/orchestrator/defs/sensors/dc_board_silver_sensor.py) 的生产就绪检查与分类 Check 完成记录。相同目标、输入、规则已有完成覆盖结果或已排队就跳过。指标和年度文件的新增审计只接受已有生产统计或同一次生产已经读取的单日数据。页面不会提交补查。

东方财富个股资金流向和股票日线神奇九转复用原生产传感器的最新适用交易日。日线晚到时，传感器在没有常规更新请求的轮次核对这一天的发布和 Check 记录，最多提交一个原 Check，按目标产出和日线版本去重。补查沿用同日键列预算，日报按原生 Check 指向的同版产出读取结果。

### 5.1 复用现有 Check 或交付

`evidence_resolver` 按[方案 §4.1 全部 130 项](dagster-daily-data-audit-wealth-data-center-plan-v1.md#41-优先用现有-check-或发布证据130-个)和[逐资产 §5.1](dagster-daily-data-audit-rules-review-v1.md#51-原-105-项复用候选)读取检查字段。各组证据的适用范围如下。

| 资产或组 | 可直接读的证据和条件 |
|---|---|
| 股票日线、股票复权因子 | Raw 日线按当次适用股票基础信息，Silver 日线用已核验的历史生命周期及同日停牌事实。股票复权因子复用 `silver_adj_factor_lifecycle_coverage_check` 的同日、Raw、Silver、股票生命周期和对账证据。所有当天上市的 A 股含全天停牌均应有股票复权因子，源端真实的已退市股票记录仍可保留。2026-10-28 以前缺同等覆盖证据时记待确认。 |
| ETF 日线行情 Raw/Silver、基金复权因子 Raw、ETF 复权因子 Silver | 取当次绑定的 `silver_etf_basic`，按当天已上市的沪深 ETF 代码和日期。分别读取 `silver_etf_daily_basic_coverage_check` 或 `silver_etf_adj_factor_basic_coverage_check`。Raw 以已执行覆盖规则的应有代码数减 Raw 命中数核缺码。Silver 还须同版 Raw 转换对账。ETF 日线覆盖告警仍为非阻断，业务更新另判。复用基金复权因子/ETF 复权因子检查时，同步采用现有已批准清算例外及其事实版本，缺事实读取证据时按待确认。实现参考 [现行检查](../../orchestrator/src/orchestrator/defs/checks/etf_daily_checks.py#L604)。ETF 日线与基金复权因子 Raw 仅核沪深上市 ETF 范围。在获准的单日补核中按同一名单仅读所选日的键列。 |
| ETF 基础信息及分钟行情 | 基础信息按输入输出快照版本对账。ETF Raw 五频绑定当次冻结 ETF 范围及已完成的代码、唯一键、时点差异检查，保留合同告警。ETF Silver 保留同版 Raw 双向对账，齐备结论仅继承已确认的范围。 |
| 上交所交易日历 | Raw 复用已发布区间自然日逐日且唯一（含休市日）的结果。Silver 对同版 Raw 双向核日期、开休市、上一交易日。 |
| 指数基础信息 Raw、Silver | 复用 `index_basic_update_job` 各层实际日更和该次正式 Check。Silver 候选在发布前完成现有同版转换对账，属于生产补证据组中的一个已具备实现方向的条目。按当日逐层判定，旧快照重跑 Check 不代表当日已更新。 |
| 股票基础信息 Raw、定期快照、主要指数量化结构 | 股票基础信息用当日成功 Check 和当日与上一交易日的同口径发布计数（`L/D/P/G` 全状态），净增减绝对值 ≤20 条通过，参照缺失或超过 20 条待确认。固定事实只复用有效快照，旧版缺证据时保留原因。主要指数量化结构取所选日完成 Check，允许无事件。 |
| 其他日、周月或分钟转换资产 | 依各资产绑定该日实际来源，已针对不同范围完成对账的 Check 不能互换。主要指数分钟线与通用指数分钟线不可交叉证明。七类资金流向 Silver 只基于各自同版 Raw 及正式映射。东方财富板块行情复用已有分类差集及合法缺报证据。已有逐键 Check 仍按原合同执行。 |
| 东方财富板块成分 Raw、Silver | 读取 `raw_tushare_dc_member_core_check`、`silver_dc_member_core_check` 各自当日且同版结果。通过时显示「已确认齐备」，详情写「现有生产 Check 通过」。检查失败按有效证据判断是否确实有缺口。没有同版结果为待确认。此资产不参加分类标准集、历史比例比较、额外成分对账和独立任务。 |


#### 股票日线前复权 Gold

日报用所选交易日 `D` 的 `silver_stock_daily` 正式产出关联的现有阻断 Check。按[目录的检查名单](../../orchestrator/src/orchestrator/defs/catalog/lake_assets.py#L634)全部通过后，通过[正式路径](../../orchestrator/src/orchestrator/defs/paths.py#L680)确认同日 `gold_stock_daily_qfq` 文件存在。再读该日 Gold 产出关联的已有 DG 任务终态。日线 Check 通过、同日 Gold 文件存在且该日任务成功，日报显示「已确认齐备」。任一证据欠缺则显示「待确认」并写明原因。更新列继续按现有发布记录判断。

在 `daily_data_audit/jobs.py` 随已有批量取证读取同日日线 Check。生成或刷新该行时最多确认一次 Gold 文件是否存在。`summary.py` 合并日线 Check、Gold 文件存在和该次任务成功三个证据。原生产 Check、写入、下游就绪判断和调度沿用原流程，生产增量读写为零。日报只查当天一个文件的存在，新增 Parquet 内容读取、源请求和文件写入均为零，重跑相同。沿用现有按版本读取接口，有证据才填写正式版本，文件存在结论无需新增版本记录。

日报已接入任务终态。正式 DG 的 2026-11-19 样本中，股票日线 Silver 的 6 条阻断 Check 均通过，Gold 文件存在，且发布所对应的 Gold 任务已成功。隔离验收覆盖文件存在但当次任务失败时齐备仍为「待确认」。


#### 股票分钟前复权 Gold

适用 `gold_stk_mins_qfq_{1,5,15,30,60,90,120}m`。先复用所选交易日 `D` 实际来源频度的股票分钟行情 Silver 齐备结论，频度用[现行输入合同](../../orchestrator/src/orchestrator/defs/run_contracts/cn_a_derived_minute_bars.py#L11)，例如 15 分钟用 5 分钟 Silver。再读取同日、同频 Gold 已有物化中本次写入文件数、当日替换行数和该次任务终态。实际交付和任务成功均确认后，日报判「已确认齐备」。证据欠缺保持「待确认」。

股票分钟前复权文件按频度、股票和年度存放，日报以[生产已经写完后留下的交付记录](../../orchestrator/src/orchestrator/defs/assets/stk_mins.py)确认新日期的输出。复用日报批量读取到的物化记录，日线和分钟前复权的同日任务终态至多合并查询这 8 项对应的运行。现有生产写入记录实际输入身份及交付批次，日报只读记录，新增年度文件内容读取为零。生产 Check 沿用各自原规则。

2026-11-19 已有 DG 任务日志显示，1、60、120 分钟 Gold 前复权各发布 5,573 个文件。前复权生产步骤分别耗时 221.46、55.10、49.46 秒，现有阻断 Check 步骤分别耗时 152.53、18.36、16.29 秒。原 Check 回读 Silver、复权因子及目标年度文件。日报只复用交付和运行结论。 [现有 Check 的读取](../../orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py#L1239)

### 5.2 生产时补证据的 33 项

| 资产键或频度组 | 改动点、应有集合、结果 |
|---|---|
| `ch_dc_daily_technical` | [ch_dc_daily_technical_core_check](../../orchestrator/src/orchestrator/defs/checks/dc_daily_technical_serving_checks.py#L141) 对已读回的同日 Gold 和本机 ClickHouse 的 `(ts_code, trade_date, category)` 双向差集。产出记录本次读取的 Gold 文件身份，Check 至多读一条本分区的最新发布记录，与当次读取的 Gold 文件身份相符时才用新增差集阻断。数量相同且一缺一多仍失败。缺新增证据只记待确认。新增 ClickHouse 查询和行情文件内容读取均为零。 |
| `silver_index_weekly`、`silver_index_monthly` | 第三阶段第一批，按 [§5.3](#53-第三阶段第一批主要指数周线月线-silver) 实现。在现有文件合同 Check 内，正式提升前从已生成的当期数据核对固定名单中截至目标交易日已上市的指数，每只恰好一行且实际 `trade_date` 等于目标交易日。原 Check 阻断保留。周线 Raw 期末交付，月线 Raw 次月首个交易日交付上月期末。两项 Raw 复用现有结果，北证 50 可合法空的规则仅适用于 Raw。 |
| `silver_index_basic` | [index_basic_checks.py](../../orchestrator/src/orchestrator/defs/checks/index_basic_checks.py) 复用发布前的同次源与候选对账和目前的生命周期 Check，核候选实际保留指数、终止日期和适用交易日。更新 job/sensor 由现有指数基础信息方案管理，本任务消费结果。 |
| `silver_stock_basic`、`silver_namechange`、`silver_stock_identity_map`、`silver_stock_lifecycle` | 分别在 [stock_basic_checks.py](../../orchestrator/src/orchestrator/defs/checks/stock_basic_checks.py)、[namechange_checks.py](../../orchestrator/src/orchestrator/defs/checks/namechange_checks.py)、[stock_identity_map_checks.py](../../orchestrator/src/orchestrator/defs/checks/stock_identity_map_checks.py)、[stock_lifecycle_checks.py](../../orchestrator/src/orchestrator/defs/checks/stock_lifecycle_checks.py)。期望分别是当前上市人民币股 `ts_code`，同次曾用名有效事件与合法开区间，源代码自映射与获准历史映射的有效边界，生命周期 `ts_code/上市日/退市日/状态`。用生产已算的投影和 Check 现有键/关键字段做双向差异，附该版输入。一个有效快照复用一次结果。上游范围待确认时只证明同版转换。 |
| `raw_tushare_moneyflow`、`raw_tushare_moneyflow_dc` | 复用 [moneyflow_daily.py](../../orchestrator/src/orchestrator/defs/checks/moneyflow_daily.py#L38) 的当日键列。普通个股取有效生命周期中的沪深京上市 A 股，含上市首日及全天停牌。东方财富个股以已核验当日股票日线取上市且有成交的沪深京 A 股，全天停牌和 B 股不计入应有名单。只核约定范围的缺码。日线晚到只执行该日覆盖 Check。 |
| `raw_tushare_moneyflow_cnt_ths`、`raw_tushare_moneyflow_ind_ths`、`raw_tushare_moneyflow_ind_dc` | 概念在 [moneyflow_daily.py](../../orchestrator/src/orchestrator/defs/checks/moneyflow_daily.py) 取已确认的 386 项基础名单，变动按代码列出并待人工确认后更新名录。另 4 个长期未发布的候选仍是待核事项。行业在 [moneyflow_ind_ths.py](../../orchestrator/src/orchestrator/defs/checks/moneyflow_ind_ths.py) 对 90 个已批准 `881` 行业名单逐码核对，后续采用确认生效的版本。东方财富板块资金流向按当日生效标准集分行业、概念、地域核板块代码，名称差异仅展示。缺当日概念标准时该项待确认，标准集生效后只检查当天。 |
| `raw_tushare_stk_nineturn` | [raw_tushare_stk_nineturn_content_integrity_check](../../orchestrator/src/orchestrator/defs/checks/stk_nineturn_checks.py#L198)，同日已核验股票日线代码减去 `freq=daily` 的九转代码。全天停牌无日线不算缺，盘中停牌但有日线应有记录，空信号也算交付。优先取现行检查已读的列，发布证据绑定日线和九转。 |
| `raw_stk_mins_{1,5,15,30,60}m` | [stk_mins_checks.py](../../orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py#L3070) 的现有同频 Raw Check，复用生产者同日有效名单、最终全日停牌事实与当次统计。应有集合和实有统计都剔除全天停牌代码，截止 15:00 计数，临时停牌按完整根数，零成交行计入。比较代码集合和汇总根数（每个应有股票分别 241、49、17、9、5 根）。保留原始交付和原写前覆盖。盘后采用当批交付结果独立记录，不能冲抵常规缺根。 |
| `silver_stk_mins_{1,5,15,30,60}m` | [stk_mins_checks.py](../../orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py#L2786) 当日引用覆盖读取中，先等同频 Raw、需要时同日 1m Raw、日线和应有停牌及映射证据。按正式 Silver 的标准化、去重、全天停牌与盘后剔除、允许的历史冻结及粗频合成核代码与总行数。粗频只有该股同频当日记录过滤后全空，且 1m 整日有效时做整日合成。Silver 全天停牌和盘后为零根。参考 [现行分钟转换](../../orchestrator/src/orchestrator/defs/assets/stk_mins.py#L1684)。 |
| `gold_stk_mins_qfq_macd_kdj_state_{1,5,15,30,60,90,120}m` | 接 [现有状态 Check](../../orchestrator/src/orchestrator/defs/checks/stk_mins_qfq_macd_kdj_checks.py#L417)。以实际前序有效状态应承接股票 ∪ 当天有指标股票为代码集，核每只一行、总数匹配。全天停牌沿用前序状态。首次初始化或历史修复取该次获准范围。复用生产已有前序与当日统计。 |
| `raw_tushare_dc_index`、`silver_dc_index` | 接 [Raw 分类 Check](../../orchestrator/src/orchestrator/defs/checks/dc_board_checks.py#L269) 和 [Silver 分类 Check](../../orchestrator/src/orchestrator/defs/checks/dc_board_silver_checks.py#L262)。行业、地域、概念分别按第 6 节核对。Silver 另核按同版 Raw 正式转换后的代码关系。 |

股票分钟前复权 Gold 按第 5.1 节复用当日上游齐备和交付。分钟前复权九转及 MACD/KDJ 指标七频沿用各自的复用规则，代码和根数来自已读的日内结果。一个前复权 K 线对应一行指标。频度依赖按 [前复权输入合同](../../orchestrator/src/orchestrator/defs/run_contracts/cn_a_derived_minute_bars.py) 和生产实际来源，不能将输出 15m、120m 误当读相同频度的 Silver。指标缺少代码统计时，只从现有读取已取得的结果中生成，证据仍缺时保留「待确认」。比如 10 只状态已存在，一只全天停牌，其他九只各 5 根 60m，指标 45 行，递推状态 10 行。已有原 Check 的质控仍依各自合同。

MACD/KDJ 使用前复权写入时已确认的年度文件身份和计算时已取得的当日输入文件身份核对版本。事件只保存身份列表的摘要。代码和行数从现有当日工作表及文件写入结果汇总，上一交易日状态沿用计算时已读的状态表。新增读取范围为零个年度文件，重跑和日报读回沿同一边界。

### 5.3 第三阶段第一批主要指数周线、月线 Silver

**已实现并通过隔离验收。** 本批只接 `silver_index_weekly`、`silver_index_monthly` 的文件合同 Check 和对应的两行日报。复用现有生产 job、原生 Check、每日汇总和同版结果查询。Raw 取数、指数基础信息日更、历史初始化以及现有调度设置沿用原规则。本批没有新增配置项、独立审计任务或页面接口。正式环境尚未运行新增检查。

#### 写入前核对

1. [写入入口](../../orchestrator/src/orchestrator/defs/io/index_period_writer.py#L491) 已算出当期第一个交易日 `first`、最后一个交易日 `last`、实际目标交易日 `as_of` 和应有代码 `active`。日更及按日补跑的 `D = config.trade_date`。现有期末正式覆盖和已结束周期修复的 `D = last`，即该批行情对应的最后一个交易日。周分区标的是本周最后一个交易日，月分区标的是年月，`D` 取该次要交付的业务交易日。例如 11 月 19 日的周线日更，分区为 `2026-11-20`，目标仍是 `2026-11-19`。次月覆盖上月月线时，发布时点在次月，业务日仍是上月最后一个交易日。
2. 应有代码直接使用 `active`。它由现有固定 11 个主要指数名单与本次读取的指数基础信息 Silver 得出，只取 `list_date <= D` 的指数，上市首日纳入。已上市的北证 50 也要有 Silver 行。日线合成、正式 Raw 覆盖和保留已验收期末 Silver 的来源选择照旧。Check 不调整这些来源，也不修改行情的 `trade_date`。
3. [候选写入](../../orchestrator/src/orchestrator/defs/io/index_period_writer.py#L231) 把 `first`、`D` 和 `active` 传给原文件合同 Check。原有 Schema、行数和增量 `index_period_silver_delta` 的分区检查继续执行。新增对账沿用内存中 `index_period_merged` 已有的 `period_start_date = first` 过滤，只核合并后实际会保留的当期 `ts_code` 和 `trade_date`，并复用该次统计作为当期行数。先做代码差集，再核每个应有代码恰好一行、每行 `trade_date = D`。日期差异记录实际日期，早一天和晚一天都报错。期望数是 `len(active)`，实际数是合并后的当期总行数。这样旧文件里仍保留的当期多余代码也会被算进差集。
4. 缺少、多出、重复和错日期的计数加入现有 `IndexPeriodFileCheck.failure_counts`，由原 `passed` 判定统一阻断。新旧检查都通过才调用 `promote_index_period_file` 提升正式文件。差异走现有 `IndexPeriodContractError` 和失败 Check 路径，记录目标日及差异，正式文件保持原版。上游未交付继续走原生产依赖，补齐后由原 job 按原分区和目标日重跑。检查通过但版本证据欠缺时，审计显示「待确认」，生产继续按原条件判断。历史初始化调用共享写入入口时不传本批目标日和名单，历史逻辑照旧。

例如 11 月 20 日应有 11 个指数，候选有 11 行，但其中某只的 `trade_date` 是 11 月 19 日。Check 要报出该代码、目标日 20 日和实际日期 19 日，并拦截候选。这是验收反例。已有 11 月 20 日发布记录作为样本，见 [§10](#10-第一阶段收尾)。

#### Check 与当次产出、实际输入的关联

在 [资产返回结果](../../orchestrator/src/orchestrator/defs/assets/index_period.py#L199) 中继续以一次 `MaterializeResult` 返回正式发布和它的文件合同 Check。周线用 `silver_index_weekly_file_contract_check`，月线用 `silver_index_monthly_file_contract_check`。改动落在周期写入、[Check 结果构造](../../orchestrator/src/orchestrator/defs/checks/index_period_checks.py#L186)和资产返回处。沿用 `build_materialization_metadata`、`build_check_metadata` 写已有事件。以下为本批拟记录的字段。

| 记录 | 内容和取值位置 |
|---|---|
| 正式文件版本 | `os.replace` 成功后，用现有 [file_version](../../orchestrator/src/orchestrator/defs/io/stock_period_raw.py#L225) 读正式文件身份，记到物化的 `goldenshare/period_file_version`。在 Check 内以相同的紧凑 JSON 字符串保存为 `version.target_version`，格式沿用 [`_target_version`](../../orchestrator/src/orchestrator/defs/daily_data_audit/summary.py#L80)。共享文件重新发布时生成新身份。DG 原生的物化事件编号和 run ID 用于查找 Check 与产出的关系。 |
| 适用范围和规则 | 物化和 Check 同时记录 `goldenshare/index_period_coverage`。两者共用一次生成的 `scope` 和 `version`。`scope` 沿用 §3.2，业务日和截至日为 `D`，分区取当前 `partition_key`，频度用日报现有的「周线」或「月线」，`coverage_scope = dataset`。`version.rule_version = index_period_silver_current_coverage_v1`，只标记本次齐备核对口径，Parquet 数据合同不变。 |
| 实际输入 | 同一 `version.inputs` 按下表记录，用 §3.2 的 `asset_key`、`scope`、`target_version` 三个字段。文件在实际读取前后各取一次同格式身份，保持一致才作为已关联输入。输入列表按资产键、分区排序，无分区按空串排序。取不到身份时留空并记录原因，不取后来的发布替代。 |
| 核对结果 | Check 的 `index_period_coverage` 另带 `passed`、`expected_count`、`actual_count`、`missing_count`、`extra_count`、`duplicate_count`、`wrong_date_count` 和 `samples`。缺多按代码计，重复计超过每代码一行的行数，错日期按行计。样本记录代码和具体差异，日期错误附实际日期，沿用现有当期 Check 的样本上限。写前失败的 Check 保存本次候选差异，`version.target_version` 为空。 |

| 本次实际读取的输入 | 记录范围 |
|---|---|
| 固定主要指数名单 `major_indices.cn_a.csv` | `asset_key` 记文件名，使用本次已解析的固定代码，排序后取紧凑 UTF-8 JSON 的 SHA-256。 |
| 上交所交易日历 Silver、指数基础信息 Silver | 日历记录读取的自然周或自然月起止日期，基础信息记录本次用其上市日期判断的目标业务日 `D`。两项分别记录读取的文件身份。 |
| 指数日线 Silver | 只有触发合成的指数才走这条来源。对 [合成函数](../../orchestrator/src/orchestrator/defs/io/index_period_writer.py#L388) 实际读取的每个交易日记录该日分区和文件身份，每日一条。不从最新日线发布倒推。 |
| 周线或月线 Raw | 有指数采用正式 Raw 时，记录实际读取的同频 Raw 文件身份、原分区和对应期末交易日。 |
| 同频已有 Silver | 用于当期接续判断或保留该期行时，记录替换前实际读取的文件身份和对应周期。 |

#### 日报复用和验收

- [日报目录](../../orchestrator/src/orchestrator/defs/daily_data_audit/registry.py#L117) 按交易日 `D` 找周或月分区。按正式物化记录的 `trade_date = D` 选截至该日的最新发布。即使 21 日凌晨才发布 20 日行情，仍归 20 日，并保留 21 日的实际发布时间。对这两项，已成功查询却没有目标日发布，按次日零点分「尚未到期」和「超期未更新」。无法查询时更新状态为「无法确认」，与齐备分开判。
- [`load_evidence`](../../orchestrator/src/orchestrator/defs/daily_data_audit/evidence.py#L182) 在已有的批量 Check 查询中，对这两项取同资产、分区、Check 名、物化事件编号且 Check 的执行 run 等于物化 run 的记录。只给这两项加同一生产 run 的限制。这能避免一次失败尝试或仅跑 Check 的记录被当成已发布版本的核验。其他资产的补查规则照旧。
- [`summary.py`](../../orchestrator/src/orchestrator/defs/daily_data_audit/summary.py#L629) 比对物化和 Check 的两个 `index_period_coverage`。`scope` 必须与所选日的资产、分区和实际截至日一致。物化 `period_file_version` 与两份 `version.target_version` 一致，两个实际输入列表一致且每个输入版本非空，两份规则版本均为本节版本。文件合同与逐代码截至日检查都通过后，才记为「已确认齐备」。计数、Check 时间及证据写入现有日报行，`version` 交给现有 `get_completeness` 按实际使用版本比对，前端照常读取。已有发布而缺同版覆盖字段为「待确认」，显示缺少该版本的齐备证据。写前失败的差异留在该次 DG 运行，本次没有正式产出，不能写到上一个正式版本上。重发同日新版后必须用新版的 Check 才能继承绿灯。历史产出继续按 §3.2 使用已留存证据，日报不扫行情文件或历史记录补证据。
- **开销。** 每项 Check 核一个目标周期，正常产出最多 11 个应有代码。复用当期增量和合并候选已有统计，新增 Parquet 内容读取、Tushare 请求和文件写入均为 0。对原生产已打开的文件各读两次身份，提升后读一次正式目标身份。按最多 7 个周内日期或 31 个月内日期，再加日历、基础信息、Raw、原 Silver 四个文件计算，每项上界分别是 `2 × (7 + 4) + 1 = 23`、`2 × (31 + 4) + 1 = 71` 次文件身份调用。未打开的文件按实际范围扣除。原 job 重跑只核同一目标周期，预算相同。日报继续使用原有两类有界批量读取，新增业务文件读取为 0。
- **编码后验收。** 扩展 [写入测试](../../orchestrator/tests/test_index_period_writer.py)、[原生 Check 测试](../../orchestrator/tests/test_index_period_checks.py) 和 [日报证据测试](../../orchestrator/tests/test_daily_data_audit_evidence.py)。两种频度各验证一个期中日更，覆盖未上市合法不计、北证 50 已上市时必须有、代码等量一缺一多、重复、截至日偏早或偏晚、原候选失败后同目标日重跑、期末 Raw 覆盖和原 Silver 保留。用隔离的正式 asset job 回读物化与 Check，验证同一次发布可读、同日换版的旧 Check 被拒绝、错误生产 run 不误配。验证输入身份缺失或历史发布缺新字段时，原生产通过条件不受影响，日报仍可显示已更新、齐备待确认。保留 §10 的正式只读样本作为日期、分区和事件关联的参照，新增行为先以隔离样本验收。

#### 首批验收记录

- 隔离 DG 中，周线、月线均通过原生生产任务、关联 Check、日报生成与同版结果查询。日期错误不提升候选，也不覆盖上一次发布的 Check 证据。新增版本缺输入证据时，日报显示已更新、齐备待确认。历史发布仅有旧文件合同 Check 时同样保持待确认。
- 对 2026-11-20 的正式 Lake 只读复核，按固定名单和上市日各应有 11 个指数，周线、月线当期均为 11 行，无缺码、多码、重复或日期差异。这次读取只验证样本本身。新增 Check 和日报读取仍以隔离运行结果为验收依据。
- 隔离样本取一周 5 个、一个月 23 个日线文件。周线 17 次文件身份调用、月线 53 次。文件身份调用、当期 SQL 投影、Python 键比较三个实测步骤合计约 1.4 毫秒和 2.1 毫秒。Python 键比较的增量峰值约 8.1 KiB 和 2.8 KiB，为 `tracemalloc` 观测值，不含 DuckDB 或全 job。另从期中日更的原生事件读回扩展字段，周线 7 条输入引用时，发布和 Check 新增 JSON 分别为 1,593 和 1,633 字节，月线 4 条输入引用时分别为 1,113 和 1,153 字节。字节数按新增字段的紧凑 UTF-8 JSON 计算，不含 DG 存储外层。此处均为隔离样本开销。
- 相关隔离回归 102 项通过。扩展回归中，指数周期传感器的 10 个失败项在开发前提交 `582b7f38a` 上全部复现。传感器测试用例和调度代码保持原样。
- 使用正式 DG 的 2026-11-20 已有事件只读复算 187 行日报。首批两项均为「已更新、齐备待确认」，原因是历史发布没有新增 Check 字段。指数基础信息 Silver 的既有同版 Check 可以直接复用。本机 ClickHouse 板块日线技术指标的样本发布仍只有源路径，原有对账方案继续按 §5.2。股票日线前复权 Gold 已改用 §5.1 的简化口径。第三阶段其他改动仍按 §5.2 的逐资产范围实施。

### 5.4 第三阶段其余批次的实现与验收

第 5.2 节 33 项中，30 项已有生产检查接线或可直接复用的现有证据。其中主要指数周线、月线 Silver 是第一批，指数基础信息 Silver 直接复用现有检查。东方财富板块分类 Raw、Silver 和东方财富板块资金流向 Raw 共三项依赖第 6 节的每日标准集，在第四阶段联验。在标准集生效前，这三项依各自已有证据显示，覆盖不足时保留「待确认」。

| 范围 | 代码和验收口径 | 读取边界 |
|---|---|---|
| 本机 ClickHouse 板块日线技术指标 | [现有核心 Check](../../orchestrator/src/orchestrator/defs/checks/dc_daily_technical_serving_checks.py) 比较当次读取的键。当前 Gold 文件与本次写入来源一致时，同量一缺一多会被拦截。更换 Gold 文件后旧交付记录只可使用原 Check 口径。 | 复用该日两个现有结果。新增一条有界的 DG 发布记录读取，ClickHouse 和 Parquet 内容查询次数照旧。 |
| 指数与股票相关 Silver 快照 | [快照对账](../../orchestrator/src/orchestrator/defs/checks/daily_audit_coverage.py) 使用生产已经算出的投影和本版输出；检查与目标发布关联。股票基础信息 Raw 比较上一交易日全状态数量，净增减 20 条可通过，21 条待确认。上游覆盖未确认时，Silver 只显示转换一致。 | 每次仅对一个输出快照的关键字段检查；日报追溯一份上一交易日的股票基础信息 Raw 记录。 |
| 普通个股、东方财富个股、同花顺行业及概念资金流向 Raw，股票日线神奇九转 Raw | [资金流向覆盖](../../orchestrator/src/orchestrator/defs/checks/moneyflow_daily.py) 和[日线九转内容检查](../../orchestrator/src/orchestrator/defs/checks/stk_nineturn_checks.py) 在原查询统计代码。同花顺使用 11 月 19 日已核对的 386 个概念和 90 个行业作为首份生效名单，概念变化待人工确认。日线晚到时仅补同日、同版本的现有 Check。 | 复用单日目标的键列。读取适用的小名单、生命周期投影或已核验日线键列。补查不触发重写或源请求。 |
| 股票分钟线 Raw、Silver 五频 | [生产与检查](../../orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py) 核常规时段应有股票代码和总根数。Raw 常规统计剔除全天停牌股票及盘后记录，盘后独立记录。Silver 绑定本次使用的 Raw、日线和参照文件，日报先确认上游。历史冻结范围仍按适用证据判断。 | Raw 复用 Prod 批内分组。Silver 复用 Check 已访问的目标及当日股票日线。新增证据不扫历史，不逐根核对。 |
| 股票日线前复权 Gold、股票分钟前复权 Gold、MACD/KDJ 指标和状态 | [日报](../../orchestrator/src/orchestrator/defs/daily_data_audit/summary.py) 和[现有生产统计](../../orchestrator/src/orchestrator/defs/stk_mins_qfq_macd_kdj.py) 复用当次运行、交付和工作表计数。分钟按实际输入频度绑定版本。递推状态纳入已有状态但当天无行情的股票。 | 前复权日线确认一个文件存在；分钟前复权、指标和状态不增加年度文件读取。首次、重试和读回均沿同日范围。 |

正式 DG 的 2026-11-19 已有记录可只读复算 187 行，股票日线前复权 Gold 为「已更新、已确认齐备」。历史周月线和分钟线记录缺本阶段新增证据，齐备仍待确认。另投影同日 60 分钟 Raw、Silver、股票日线和最终停牌四个文件，常规时段两层均为 5,573 只、27,865 根，股票代码缺口为零。投影样本约 0.235 秒，这是一次只读查询的耗时，生产 Check 增量耗时尚待正式运行测量。

隔离回归通过 684 项，包含两组受保护的股票分钟线测试。验证了同量换码、文件存在但任务失败、更新后旧版本证据失效、晚到只选原 Check、全天停牌与盘后不能冲抵缺根、以及停牌股票的前序递推状态保留。DG 定义、文档完整性和变更差异检查均通过。

前述隔离验收使用隔离 DG 和正式实例既有事实。日报刷新优化另行处理。

#### 2026-11-22 只读验收

截至北京时间 21:31，正式 DG 中没有第三阶段首批提交之后的新运行记录。核对所选业务日的既有发布和对应 Check，并在内存中核对日报状态。两个样本日均无正式日报。本次执行 DG 任务 0 次，正式 Lake、ClickHouse、DG 记录及调度配置无写入。

| 业务日 | 已有发布及 Check | 日报判定 |
| --- | --- | --- |
| 2026-11-19，主样本 | 第三阶段范围内 29 项有产出，关联的 70 条既有 Check 全部通过。指数基础信息 Silver 当日无发布记录。 | 29 项显示「已更新、齐备待确认」。指数基础信息 Silver 显示「超期未更新、齐备待确认」。 |
| 2026-11-20，对照样本 | 第三阶段范围内 30 项均有产出，关联的 73 条既有 Check 全部通过。 | 指数基础信息 Silver 直接复用当日同版 Check，显示「已更新、已确认齐备」。其余 29 项缺少第三阶段新增的同版证据，显示「已更新、齐备待确认」。 |

2026-11-20 实物抽验中，主要指数周线、月线 Silver 各覆盖 11 个应有指数，全部截至 11 月 20 日。股票 1 分钟、60 分钟 Raw 和 Silver 的常规时段均覆盖 5,572 只应有股票。1 分钟两层各 1,342,852 根（5,572 × 241），60 分钟两层各 27,860 根（5,572 × 5）。两种频度的代码和总根数均匹配，全天停牌及盘后记录不计入常规时段。该日东方财富板块日线技术指标 Gold 和本机 ClickHouse 各 1,081 行，业务键无缺失、多余或重复。

**正式运行验收待完成。** 下一次正常日更结束后，只读核对新版 Check 是否随生产任务产生、能否关联到当次产出和实际输入，以及可以从该次运行确认的新增耗时和内存开销。缺少记录的条目继续待验收。为验收补跑生产任务、Check 或日报任务均不在本次授权内。

**对第四阶段的影响。** 上述待验项不构成第四阶段开发和隔离验收的技术前置条件。第四阶段使用 2026-11-19 的东方财富板块分类基线、本组资产的当日同版结果以及已有日报入口，依第 6 节联验东方财富板块分类 Raw、Silver 和东方财富板块资金流向 Raw。缺少同版结果时，条目先显示「待确认」，待对应 Check 产出后按第 6.1 节刷新。第四阶段正式启用仍需完成该三项的联验并另行获得正式执行授权。

## 6. 东方财富板块分类与人工核查

### 6.1 当日对账与标准集

行业、地域各用生效的人工确认名单，核同类别有效代码差集。确属正常变动时经确认形成新版本。Silver 复用 Raw 确认的标准集，并核对自身与实际使用的 Raw 转换是否一致。分类占位与 Silver 拒绝规则以 [Raw 分类合同](../../orchestrator/src/orchestrator/defs/run_contracts/dc_board.py#L234) 和 [Silver 生产转换](../../orchestrator/src/orchestrator/defs/assets/dc_board_silver.py#L143) 为准。

概念按所选交易日的上一交易日查找确认版本。不存在时记「参照标准集缺失」，当前日齐备待确认，从缺失日恢复。存在时，对比当日 Raw 有效代码与参照。无增减时保存当日副本，有增减时记录代码、名称及存在性，待人工确认。分类父状态按第 3.3 节折叠。同一交易日只保存一份当前有效的概念标准集。已保存记录保留版本及生成时点。本阶段联验依赖当天标准集的东方财富板块资金流向。

在 `dc_index_review.py` 解析 `review_version` 为业务日、当日 Raw 正式产出的发布身份、原参照版本与差集。正常日更使用同版 Raw Check 已记录的分类名单，由现有分类 Check 保存其已读到的类别、代码和名称及所对应的产出版本。缺少这份同版结果时保留「待确认」。使用 `daily_data_audit_board_confirm_job` 保存标准集。现有东方财富板块分类 Raw 传感器在同版分类名单与参照完全匹配且尚无当天标准集时提交保存副本，出现增减时由运营提交确认。同一函数校验当前 Raw 目标和参照，并输出第 3.4 节标准集元数据。Silver 使用标准集时还核其自身和实际 Raw 的关联。读取以当前同版有效记录为准，上一日的原版本仍可追溯。当天日报保存 DG 生成的分类核查信息 `board_review`，Web 读取该信息及同版确认、源端核查结果，不在 Web 比较板块名单。

#### 首份标准集与启用前接续

1. 首份标准集使用已确认的 2026-11-19 东方财富板块分类 Raw 名单，包括行业 496 个、地域 31 个、概念 554 个。该日是唯一的起点，人工确认时无需上一交易日标准集。从 11 月 20 日起按交易日接续到启用日，每日沿用上一交易日参照。名单相同保存每日副本，有增减走原人工确认流程，遇缺失的交易日从该日恢复。
2. 仅在这段启用前接续中，旧 Raw Check 未保存名单时，`dc_index_review.py` 查该日 `raw_tushare_dc_index` 的正式发布及其关联的已通过 Check，再各读取当天的板块分类 Raw（`dc_index`）和板块行情 Raw（`dc_daily`）一个正式文件。只投影 `DC_INDEX_FIELDS`、`DC_DAILY_FIELDS`，先用生产 [源字段规范化函数](../../orchestrator/src/orchestrator/defs/asset_guards/dc_board_source_probe.py#L174) 统一日期等字段，再用 [现有源指纹函数](../../orchestrator/src/orchestrator/defs/run_contracts/dc_board.py#L282) 核对分类发布记录中的 `tushare_source_fingerprint`。一致时从已读入的分类记录排除合同规定的占位行，取类别、代码和名称作为候选名单。缺正式发布、关联 Check 或指纹不一致时保留「待确认」，不生成该日标准集。
3. 仍由现有设计中的 `daily_data_audit_board_confirm_job` 保存，记录该日分类 Raw 发布编号、核对的指纹和适用的参照版本。每次只处理一个交易日，已有有效标准集直接复用。中断后从最早未确认的交易日继续，重试最多重读该日这两个文件。最终验收按日读取 `dc_index_standard` 记录；业务文件写入、源请求和历史生产任务重跑均为零。2026-11-19 和 20 日实测两日各读取 1,081 行分类和 1,081 行行情，重建指纹均与各自分类发布一致。
4. 旧 Check 未记名单且名单有增减时，可对该日显式运行现有日报任务，传 `use_board_history=true`，按第 2 步把核过指纹的候选名单、增减和版本记入日报。财势乾坤沿用同一核查窗口和操作接口。DG 复核和保存时沿用该日历史名单校验，确认仍须匹配核查版本。复核结果到达后的状态刷新复用日报里的同版候选名单，仍只读 DG 记录。普通日更和自动日报使用默认值 `false`。

#### 东方财富板块资金流向 Raw 的 Check

1. `raw_tushare_moneyflow_ind_dc_file_contract_check` 在现有当日文件读取中取类别、代码，用当天已确认标准集分行业、地域、概念核代码覆盖，`行业`、`地域`、`概念` 分别对应分类名单中的 `行业板块`、`地域板块`、`概念板块`。名称变化不参与覆盖判断。Check 记录齐备结论、缺码、目标 Raw 发布及文件版本、标准集版本。标准集尚未就绪时齐备为「待确认」，原生产通过条件照旧。
2. 资金流向 Raw 已按原规则交付且原 Check 已通过、标准集随后就绪时，由 [现有资金流向 Raw 传感器](../../orchestrator/src/orchestrator/defs/sensors/moneyflow_ind_dc_sensor.py#L60) 在原日期窗口内识别缺少当日同版覆盖结果的日期，沿用 [只选原 Check 的提交方式](../../orchestrator/src/orchestrator/defs/sensors/stock_daily_audit_coverage.py#L57)，通过原更新 job 只执行该日的文件合同 Check。以业务日、Raw 正式发布的 run ID 和标准集版本去重。传感器复用原有交付与文件指纹核对，不增加文件内容读取。Check 只读当日一个 Raw 文件及当日标准集记录，数据重写和源请求为零。正常日更已有匹配结果时直接复用。
3. 日报在 `evidence.py` 读取原生 Check 的目标发布关联，允许复用上述只运行 Check 的结果。按业务日、当次 Raw 发布及文件版本、标准集版本匹配，结果尚未到达时保留「待确认」。获准重试时仍只执行该日原 Check。验收读回对应发布、标准集和 Check 记录。标准集确认任务和日报刷新传感器负责下面的状态刷新，资金流向 Raw 传感器负责提交原有 Check。这两条流程各自按既有开关运行。

#### 标准集确认后的状态刷新

1. `daily_data_audit_board_confirm_job` 成功保存 `dc_index_standard` 后，由现有 `daily_data_audit_summary_refresh_sensor` 读取该成功记录，按记录中的 `business_date` 提交现有 `daily_data_audit_summary_job`。日期取标准集对应的交易日，即使事后确认也是如此。首次刷新固定传入 `changed_asset_keys` 为 `raw_tushare_dc_index`、`silver_dc_index`、`raw_tushare_moneyflow_ind_dc`。刷新请求同时传入确认任务的 run ID 以定位该版标准集，汇总任务据此进入本节限定的齐备状态刷新路径，无需扩展通用下游依赖。如果所选日还没有日报，首份日报生成时一并读取现有标准集和 Check 结果。
2. 汇总任务读取现有同日的发布、Check 和标准集记录。板块分类 Raw 使用本次确认和同版 Raw Check，启用前接续时复用标准集确认记录中已保存的旧 Check 对应发布和指纹，按原规则归并行业、地域、概念状态。板块分类 Silver 复用本版标准集，并沿用可对应到实际 Raw 输入的转换结果。板块资金流向 Raw 使用与当天正式产出和本版标准集都对应的覆盖结果。缺少任何一项必要的同版核对结果时，该条目显示「待确认」，详情记录缺少的证据。
3. 原有 Check 按第 5 节的流程出结果后，同一个刷新传感器识别与该交易日和标准集版本匹配的记录，只刷新这三项中受该结果影响的齐备状态。如果当前产出的新版 Check 未通过，则按原生记录关联该产出，显示「待确认」并保留失败记录。若板块分类 Raw 的 Check 使标准集暂时无法复用，或使它恢复可复用，同时刷新依赖它的分类 Silver 和板块资金流向 Raw 的齐备状态。初次刷新按业务日和标准集确认 run ID 去重，后续按业务日、同版标准集、Check 运行 ID 和检查项去重。标准集版本使用保存该版的确认 run ID。Dagster 事件编号只用于读回、关联和判断先后。确认与刷新只处理审计记录，业务数据计算及 Check 执行由原流程负责。任务去重使用现有通用 builder，见 [Run Key 清单](dagster-run-key-governance-low-level-design.md#数据审计阶段四运行去重)。
4. `board_summary.py` 在现有当日日报上更新目标条目的齐备状态、原因和相关证据，按这些状态变动更新四项汇总计数。原有更新列及其观察时间继续来自上次日报。按第 3.4 节保存该日新版日报。首轮及后续刷新只读该日、该版本的 DG 记录，业务文件读写和源请求均为零。

### 6.2 Tushare 复核与保存

1. 「核查 Tushare」提交 `daily_data_audit_board_recheck_job`。固定业务日、差异版本，服务端重算新增与减少的代码差集。请求仅限该集合。`dc_index(trade_date=YYYYMMDD, ts_code=code)` 复查分类，必要字段为业务日、板块代码、名称和类别。`dc_member(trade_date=YYYYMMDD, ts_code=code)` 独立核同日成分，结果按板块列出。参考当前 [分类参数](../../../src/foundation/ingestion/request_builders.py#L696)、[成分参数](../../../src/foundation/ingestion/request_builders.py#L962) 和 [DG 板块合同](../../orchestrator/src/orchestrator/defs/run_contracts/dc_board.py)。在 DG 的 [TushareDownloader](../../orchestrator/src/orchestrator/tushare_download/download_api.py) 挂接这两个已有接口的 `BY_OBJECT_POINT` 只读请求规则，沿用当前页大小、合法空响应和返回键校验。参照[指数单对象单日下载](../../orchestrator/src/orchestrator/tushare_download/contracts/index_weekly.py#L46)的调用形态。复核只读取会话响应，无 Prod 对账及文件提升步骤。
2. 点击后显示加载圈、核查范围及「正在核查 Tushare」。以任务终态或本次复核超时解除锁定。期间禁重复请求、查看参照、确认、取消、关闭、Esc 和遮罩关闭。页面只查询结果状态，单次查询暂时失败时继续查询同一运行，仍以原截止时间为准。超时后可重试失败项。提交时拒绝在途重复，防止重新打开时重复打源。
3. 按代码分别保存分类与成分的成功、未返回、失败结果及核查时间。保留原本地差异。合法成分空不等于板块消失。分类有效返回且本地当前版本缺少，记「源端有，本地缺少」和确认缺口。源端成功未返回记「源端本次未返回」，留待人工判断。重新完整核查时使用本次有效结果；本次请求失败时保留同版上次有效证据。选择重试失败项时只请求上次失败的代码和接口，复用其余结果。
4. 保存前由 DG 核对 Raw 版本和参照，并检查该版是否存在源端证实的缺口。前端按同一结果控制确认按钮。通过后保存完整有效分类代码、所用 Raw 及上一期版本、确认人和时间。首次和固定名单变更走已批准的人工确认流程。同一核查窗口在行业或地域名单有增减时显示这些差异，Tushare 复核仍只请求概念板块差异。已证实漏采时，用现有同步入口补齐，再核对新产出。
5. 确认、复核与生产 Check 使用同一个正式队列。提交时复用同一业务日、同一版本的在途操作，开跑时核对当前 Raw 及参照版本。

源端复核完成并确认本地缺口时，现有日报刷新传感器读取 `dc_index_recheck` 和同日既有日报，只刷新对应版本的东方财富板块分类 Raw 齐备状态。此后同版复核解除该缺口时，同一条目恢复按现有参照判定。请求按业务日、核查版本和复核运行 ID 去重，沿用第 6.1 节只读 DG 记录、保留更新状态的刷新方式。

若原同步流程补齐并发布新的板块分类 Raw，刷新传感器按新发布关联的 Check 找到该业务日既有日报，即使当天尚无标准集，也刷新其分类核查信息。页面读新的本地差异，旧源端复核仅适用于旧版。按业务日、Raw 发布运行 ID 和 Check 运行 ID 去重，沿用原日报更新和证据读取。

交互顺序为「列表 → 东方财富概念板块 → 名单核查 → 查看参照或核查 Tushare → 确认并生成标准集」。发现确实漏采时，详情保留源证据和缺码，等待原同步流程补齐后重新核查。

### 6.3 第四阶段隔离验收

| 验收项 | 验收证据 |
|---|---|
| 每日标准集 | 隔离 DG 从历史 Raw 和已通过的同版 Check 生成首份标准集。无增减的下一交易日提交保存副本。历史名单有变时，指定日期的日报读回候选名单，确认必须传入当前核查版本。错指纹、缺上一交易日参照和旧版本均无法保存。 [历史接续及运行测试](../../orchestrator/tests/test_daily_data_audit_dc_index.py) |
| 东方财富概念板块 Tushare 复核 | 下载会话使用替身接口。验证只请求差异概念板块的分类与成分，失败项重试复用其余结果。截止后不发新请求。有源端缺口时拒绝确认。完整复核得到新的有效结果后按该结果判断。 [核查运行测试](../../orchestrator/tests/test_daily_data_audit_dc_index.py) |
| 当日报告三项状态 | 隔离 DG 读回原生发布、确认及 Check。确认后只刷新当天三项的齐备状态并更新计数。资金流向缺同版结果先待确认，Check 补到只刷新该项。同版新版 Check 失败保留失败证据并退回待确认。另验证源端缺口及历史 Raw 补齐后对应页面读回的新版本。 [日报联动测试](../../orchestrator/tests/test_daily_data_audit_evidence.py) |
| 财势乾坤本地页面 | 隔离 API 验证仅在本地开关打开时提供入口，管理员可确认和复核，Silver 只读。页面验收覆盖查看标准集、操作期间锁定、任务结束或到期后解锁、缺口停止确认。 [Web API 测试](../../../tests/web/test_wealth_data_audit_api.py) · [页面测试](../../../wealth/src/pages/data-center/DataAuditPage.test.tsx) |

隔离设置使用临时 DG 实例和临时数据文件。正式启用待完成授权后的单日联验，包括正式标准集保存及读回、实际 Check 证据和耗时，以及经授权的真实 Tushare 复核。隔离验收期间正式 DG 任务、正式数据文件写入和调度启用均为零。

2026-11-23 的隔离回归中，DG 相关测试及运行规范共 352 项通过。最后一次修正后，日报证据和状态联动的 22 项测试重新通过。Web API 16 项、Wealth 前端 1,656 项通过。DG 定义加载和文档完整性检查通过，独立复核未发现阶段四的剩余阻塞。全仓治理另有两项资产登记对账失败和一项指数基础信息测试导入失败，均已用本阶段修改前的提交复现。

## 7. 通用指数分钟线独立审计

执行入口为 `daily_data_audit_index_minute_job`，由本机 DG 的独立进程执行。参数固定为一个资产键、一个业务日、该频度、范围和稳定版本，范围限 Raw 五频及 Silver 七频。先复用已有的同版证据，确需补核时才读该日文件。需要继承上游齐备结论且未取得时，等待上游或记录其缺口，受影响的下游文件不读。财势乾坤页面只通过每日总结和详情查看结果。

| 目标 | 数据访问和键判定 |
|---|---|
| `raw_index_mins_{1,5,15,30,60}m` | 取此次 Prod 导入当时实际使用的 `ops.index_series_active(resource='index_mins')` 有效名单的留存版本。独立 job 读本地证据，不能到 Prod 重查激活池。已有同版代码覆盖可复用。只访问 [Raw 路径合同](../../orchestrator/src/orchestrator/defs/paths.py#L1078) 的一个日期一个频度文件，投影 `(ts_code, freq, trade_time)`。上海上午从 09:30（含）至 11:30，下午从 13:00 加一个频度至 15:00，按 (120/F + 1 + 120/F) 生成预期点。每频每代码应有 241、49、17、9、5 个键，核缺、多、重复。历史 15、30、60m 只有绑定到获准源全空证据的日期/频度才能用相应历史例外。 |
| `silver_index_mins_{1,5,15,30,60}m` | 应有对象继承本次实际同频 Raw 的批准范围。在需要补核时只读同日目标及实际来源，以正式标准化后业务键做双向差异及重复检测。已获准的历史源全空替代使用同日实际绑定的 5m Raw 和正式转换。只有键对账可证明时显示「仅与上游一致」。 |
| `silver_index_mins_90m`、`silver_index_mins_120m` | 分别使用同版 30m、60m Silver 的应有范围。复用[合成窗口合同](dagster-derived-minute-bars-90-120-contract-rebuild-low-level-design.md#22-90m-窗口)检查输入窗口和竞价锚点。按每指数输出 90m 的 11:00、14:00、15:00，120m 的 11:30、15:00 核键。最多读取对应上游及目标两个文件。 |

DG 运行前用已知文件数、读取列及已有行数估算开销，字节数仅供性能验证参考。复用已有队列，开跑前核对目标及必要输入版本。缺少同版范围证据时保留「待确认」。任务完成后保存实际读量、版本和差异。取消、失败及获准的同范围重试沿用 DG 运行管理，失败或取消的运行没有可消费的结论。

先在 DG 验一个代表资产的单日读取和结果读回。自动提交和运行窗口另行评审。获准后，由本机 daemon 评估专用审计传感器，从同版产出及必要上游就绪记录判断是否提交。日期与版本明确放 run config，`run_key` 只用于传感器去重。未取得核验结果时页面显示待确认。

## 8. 性能预算与执行验收

| 步骤 | 可从合同和代码核算的工作量 | 开放前需验证 |
|---|---|---|
| DG 一次总结 | 设 `A` 为当前目录资产数，`P` 为所选业务日解析出、去重后的目标与必要参照范围数，`C` 为这些范围需要的 Check 键数。生产记录读取按范围分组批量执行，每组两类查询，分别取发布和已完成 Check。股票周月已有两次集合查询的例子。优先把匹配范围作为值表关联，禁止用资产集合与分区集合的笛卡尔乘积。输出至多 `A` 主行，另有固定、已列明的详情组件。一次完成结果只需查一个指定业务日的成功汇总 run 和该 run 的有界日志。无可用记录时不跨日查询。 | 在现有 SQL 存储对代表性的日分区、周期实际日及快照观察时点验证计划、查询次数和返回事件字节，区分 SQL 扫描量与结果条数。对无分区和复用分区先查可定位 `D` 的交付身份或已有发布记录，再按候选身份匹配 Check。没有可靠索引范围或绑定的项返回待确认，禁止降级为读明细或翻全历史。记录首跑、进程中断后的单日重读、只更新受影响行的读取和 Web 最终读回。单次记录的实际压缩前字节和 DG 存储保留条件需跟样本验收。 |
| 日更增量 | 周、月 Silver 各核最多 11 个应有指数，直接使用现有增量关系，新增文件或源请求为零。ClickHouse 使用已读的 `C_gold+C_ch` 条键，不追加 ClickHouse 请求。资金流、九转、板块分类取当日已有键列及适用参照。股票分钟 Raw/Silver 用原生产日内计数和代码，需计算时在已知当日文件投影中完成。状态用当次生产的前序和当日统计，快照 Check 复用当次转换工作集。 | 逐组记录新增文件数、投影、键记录数、峰值内存、正常 Check 时间、上游晚到后选中日期补查、发布后读回。分钟线参考逐资产规则的 2026-11-19 单列聚合样本约 9 毫秒。该值只测过 `ts_code` 分组，不能作为完整 Check 耗时。未证实开销可控的补项暂不进入日更，按方案复核执行方式。 |
| 通用指数分钟独立任务 | Raw 至多一个文件，Silver 至多当日目标加实际输入两个文件。键为三个字段。`N` 为当次有效指数数，Raw 每频预计键数 `N × 每指数预期时点数`，Silver 派生预期键数由同版输入窗口决定。样本 `N=530` 的 Raw 1m 是 `530 × 241 = 127730` 个预期键。若中断后批准重试，每次至多重读同样一个或两个文件。 | 在 DG 验代表资产的文件数、实际扫描键数、峰值内存、耗时、单日重试和结果读回。用实测确定可用窗口，再评审自动运行。 |
| 东方财富概念分类 Tushare 复核 | 设 `K` 为本轮差异代码数，在每个代码两个接口各一页时基础请求数为 `2K`。有分页时为 `sum(index_pages + member_pages)`，重试另计每页实际附加次数。复用 [现行东方财富请求策略](../../orchestrator/src/orchestrator/defs/asset_guards/dc_board_source_probe.py#L149) 的间隔、最多 3 次页内重试、1,200 次请求和 600 秒每轮硬上限作为外层限制，并按本次差集提前完成。页大小沿用[现行合同](../../orchestrator/src/orchestrator/defs/run_contracts/dc_board.py#L69)。只重试上一轮失败的代码与接口。某项分页未完整时重读这一项，其他已成功项沿用结果。 | 复用 DG [带限时 HTTP transport](../../orchestrator/src/orchestrator/tushare_download/http_transport.py#L202) 和[现有请求时限](../../orchestrator/src/orchestrator/tushare_download/configuration.py#L48)，每次调用的上限是 45 秒。排队及运行共用提交时生成的截止时点。达到请求数上限，或剩余时间不足当前一次调用的上限时，经下载会话已有的取消检查阻止下一页或重试。正常提前完成即解锁。验证无响应时 Web 可解锁、DG 到期无新请求、已完成项可按同版读回。记录分页、失败重试、返回的证据大小与实际用时。 |

汇总与独立读取复用现有治理的[事件、身份和读取边界](dagster-data-pipeline-performance-governance.md)。产品、生产 Check、独立审计分阶段获得本机正式执行授权。先用隔离实例和真实 schema 契约验证，再有界读回已有正式产出和 Check。可用已有验收样本包括[主要指数周月交付](dagster-daily-data-audit-rules-review-v1.md#主要指数周线和月线的检查结果复用)、[ETF 复权因子缺码和交付证据](dagster-daily-data-audit-rules-review-v1.md#复用与单日补核)及[股票分钟线保留和过滤的实例](dagster-daily-data-audit-rules-review-v1.md#31-股票原始分钟线与-silver10-项)。这些记录证明各自的历史业务口径，小范围实现验收还需证明新读取路径和目标版本绑定。

## 9. 编码测试和方案对账

以下是实施时应执行的测试及本次文档一致性审计。正反例来自方案或当前生产合同。使用独立字面数据作为业务预期。运行时验证应区分替身、隔离的真实 DG schema、正式实例有界只读及批准的正式执行。

| 方案约束 | LLD 和测试位置 | 需要通过的正反例 |
|---|---|---|
| 方案 §1–2 本地入口、日期和两列状态 | §2、§4。沿用 `DataCenterPage.test.tsx`，新增 `DataAuditPage.test.tsx`、`tests/web/test_wealth_data_audit_api.py` | 本地显式开启才有卡和读写接口。Prod 强传开关、伪造 localhost、直达路径也拿不到。登录只读、管理员操作、只读绕过按钮 POST 返回 403。DG 断开提示并标旧结果的原时间。当天未生成不借上一日。四个数字分别筛该日、更新条件回全部、明细定位回第一页，组合后按实际匹配数展示且汇总数字不变。 |
| 方案 §3.1、§5 更新 | §3.1/3.3/3.4。DG `tests/test_daily_data_audit_summary.py` | 正常交付、合法空公告、固定快照和非发布日。到次日 00:00 确无应有交付时为超期。首轮运行前若已迟到交付，直接显示「已更新」和实际发布时间。休市或合同延期无超期，缺日历规则是无法确认。仅绿灯没交付、只登记分区、周期实际截至日落后均不可为已更新。 |
| 方案 §3.2–3.3、规则 §1.1 证据复用 | §3.2–3.4、§5。DG `tests/test_daily_data_audit_evidence.py` | 同资产、分区、频度、范围、上游、规则及目标均匹配才复用。Check 对旧物化、覆盖只跑了合同、证据读取失败、新版本没有 Check、较新失败且较旧绿灯、仅同版一致，分别验状态及原因。等待或已知上游缺口时测下游行情读取为零。换版只刷新受影响的条目，保留原总结时点和到达时刻，历史无法重建就写未核实。 |
| 方案 §4.1、§4.4 目录分流 | §3.1、§5.1。目录覆盖测试和 `tests/test_daily_data_audit_summary.py` | 对现有目录全部键核归类与原规则表的对应关系。国际指数日线两层各计一次不适用，六个 Prod 目标和 Lake 健康不参与本地核验，三项仅核更新。ETF 日线非阻断有缺码时允许已更新且齐备缺口。基金复权因子清算事实仅适用其对象及日期，未证实的事实不能认定为例外。 |
| 方案 §4.2、规则 §3.1、§3.3、§3.4、§5.2 生产 Check | §5.2。各现有 Check 测试及 `test_index_period_writer.py`、`test_index_period_sensors.py` | 本机 ClickHouse 板块日线技术指标同量一缺一多须阻断，缺证据只待确认。周月 Silver 只核目标交易日，原始允许空规则不延伸到 Silver，错日期、重复和未上市正反例。全天停牌 Raw 占位不能抵常规缺根，Silver 为零，盘后独立。临停完整根数。上游晚到只查当天。MACD/KDJ 验同码总数、指标 45 行和递推 10 行，缺前序、同数错代码或上游待确认时不能判绿。 |
| 规则 §3.5–3.7 资金流向、快照和日线神奇九转 | §5。扩展相应 Check 的现有测试 | 同花顺概念增减待人工、行业目录范围按 881 生效名单。普通资金流纳入全天停牌，东方财富个股只核有成交的上市 A 股。股票基础信息 20 条和 21 条分别判齐备、待确认。五个 Silver 快照按实际输入，变换漏写和版本错配可检出。日线神奇九转信号空合法，全天停牌无记录合法，盘中停牌有日线但缺九转报缺码。 |
| 方案 §2、§4.2、规则 §3.4 东方财富 | §6。扩展 `test_dc_board_checks.py`，新增 `tests/test_daily_data_audit_dc_index.py` 与核查弹窗测试 | 行业、地域及概念分开比较，父行优先级与统计正确。概念同名单留副本，源端正常变更可确认，上交易日缺标准时报参照缺失。Tushare 只请求差异限定，正常空、失败及超时分开，锁定含 Esc 与遮罩。源端证明本地漏采时前后端拒绝生成。补齐后核新版本才允许确认。Raw/Silver 成分均仅复用现有对应 Check。 |
| 方案 §6 东方财富首份标准集与启用前接续 | §6.1。DG `tests/test_daily_data_audit_dc_index.py` | 用 11 月 19 日、20 日的历史证据样本验证，旧 Check 无名单时能按生产规范化重建同版指纹。首日可经确认保存，下一交易日名单一致可接续。指纹不一致或普通接续日缺上个交易日参照时不保存。从未确认日续跑，不重跑历史生产任务。 |
| 方案 §4.2、规则 §3.5 东方财富板块资金流向 Raw | §6.1。扩展该资产现有 Check、传感器及日报证据测试 | 代码相同改名通过，少板块报具体缺码。标准集先到时原日更记录覆盖，晚到时仅由资金流向 Raw 传感器选择同日原 Check。匹配结果缺失先待确认，结果到达才刷新。重复观察、已存在同版结果、错日或旧版本不产生重复执行或误判。确认与日报刷新均不提交 Check，补查不下载、不发布数据。 |
| 方案 §5–6 标准集确认后的状态刷新 | §6.1。DG `tests/test_daily_data_audit_evidence.py` | 确认历史交易日标准集时只刷新该日三项齐备状态，更新列保留原值。已有同版 Check 直接复用，缺同版结果先待确认，匹配的原 Check 出结果后只刷新受影响条目。刷新只读取 DG 记录，业务文件内容读写、源请求和业务计算均为零。 |
| 方案 §4.3、§5 与规则 §1、§3.2 独立任务 | §7–8。DG `tests/test_daily_data_audit_index_minute.py` 与页面结果读取测试 | 同版 Raw 时间键、Silver 输入窗口和输出键正常。代码齐全但缺 14:00、行数相同而时点错位、重复键或池换版被发现。只认已批准的历史全空例外。通过 DG 验单日范围、换版和上游未就绪时的读取边界。页面从总结和详情展示结果。 |
| 方案 §5–6 原生记录与恢复 | §3.4、§8。DG 汇总及读取集成测试 | 成功 run 可按日读回完整元数据，取消或失败留下运行记录而无可复用结论。部分证据失败只影响该范围。汇总发布失败不回滚业务数据。停机漏总结继续显示未生成，有界补记显示真实生成时间。测试原结果、迟到结果、同版消费和重试的读取预算。 |

**本次文档审计结论。** 对照两份方案，以上各阶段采用相同资产范围、业务日期、状态、阻断规则和开放条件。生产补证据 33 项按 1+2+5+5+1+10+7+2 对账。既有 Check 足够的路径直接读结果，独立核验仅覆盖 12 项通用指数分钟线。Tushare 人工复核只用于东方财富概念分类。新增内容为实现方案要求所需的接口、结果记录、调用顺序与验收用例。

使用 CodeGraph 核对了数据中心入口与请求链、DG 资产目录、检查和下游 readiness。将逐资产表的键与只读代码目录逐项比较，两侧均为 187 个唯一键，差集为空。此前在 Dagster 1.13.26 隔离实例读回了成功 run 的 JSON 步骤输出元数据，汇总定位、结果读取和提交的 GraphQL 文档通过同版 schema 校验。这里验证的是记录承载方式和接口形态。正式存储保留、同版生产证据读回、耗时与读取预算以及独立审计自动启用继续按本节分阶段验收。

## 10. 第一阶段收尾

对照修改后的方案及逐资产规则，DG 目录和规则清单均为 187 个唯一资产键，差集为空。已通过本机 DG GraphQL 只读核对 2026-11-20 的三次现有运行及对应分区最新物化。三次运行均成功，六条 Check 均通过，分别指向各自资产、分区、运行和物化时间对应的记录。每个分区只取一条最新物化，运行日志只查这三个运行。以下是北京时间。

| 样本 | 分区 / 实际业务日期 | 发布时间 | 关联证据 |
|---|---|---|---|
| 指数日线 Silver | `2026-11-20` / `2026-11-20` | 11 月 21 日 01:05:09 | 4 条 Check 指向物化 `8295431`。覆盖 Check 记录 Raw 实有 820 个代码、Silver 820 行，缺失、多出均为 0。该覆盖以实际 Raw 为依据。 |
| 主要指数周线 Silver | `2026-11-20` / `2026-11-20` | 11 月 21 日 01:07:42 | 1 条文件合同 Check 指向物化 `8295659`，产出元数据记录截至 20 日、当期 11 行。 |
| 主要指数月线 Silver | `2026-11` / `2026-11-20` | 11 月 21 日 01:08:18 | 1 条文件合同 Check 指向物化 `8295681`，产出元数据记录截至 20 日、当期 11 行。 |

本次样本验证现有 DG 记录可提供日期、发布时点和目标 Check 关联。物化编号用于关联记录。周月线当期逐代码、逐行截至日的新增检查继续在第三阶段验收。第一阶段读回未执行生产或检查任务。

第二阶段实现 DG 每日总结、财势乾坤本地数据审计入口和日期/资产详情读取，以及下游按实际范围和版本复用结果。阶段内验证一日批量取证、原生汇总写入与读回、本地与 Prod 路由边界、两列状态和筛选。证据不足的资产依照现有状态口径展示。生产 Check、东方财富概念人工复核和通用指数分钟线独立任务分别在第三、四、五阶段处理。

## 11. 第二阶段编码与验收边界

视觉参考 [R1 每日总结与资产明细](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?node-id=2227-163)。这一阶段使用第 4 节的两个 GET 接口。返回第 3 节已有字段及列表显示所需的资产名、层和频度。详情使用列表的 `summary_run_id`，保证两处读取同一次结论。页面默认看上海时间上一自然日，日期切换后使用该日的真实响应。沿用数据中心现有的 5 秒读取超时和「请求超时，连接状态暂不可获取」文案。

| 财势乾坤交付清单 | 适用范围及验收 |
|---|---|
| §2.1、§2.6、§2.8、§2.12 | 本方案、逐资产规则、R1 和本 LLD 为实现依据。用真实本地读接口对账日期、四项数量、行状态、详情证据和同版范围。 |
| §2.2、§2.4、§2.10 | DG 汇总负责语义和计数。Web 按单日读原生结果。前端只筛选、分页和格式化显示。验收量为 187 个目录主行对应的单日汇总及一个详情。记录实际查询次数、响应字节和耗时。 |
| §2.3、§2.5 | 验证加载、已生成、未生成、DG 不可用状态及日期切换、双筛选和详情。 |
| §2.7 | 模块由明确的本地开关控制，默认关闭。只在隔离环境打开验证。回滚时关闭开关并将审计调度保持停止。 |
| §2.9、§2.11 | 本阶段只展示文本、数字和表格。无图表、策略中心接线或该清单的模块级例外。 |

DG 汇总以一天和目录生成的明确键范围批读已有记录，最多写入一个成功汇总结果。按日期精确绑定产出和 Check。运行中断后重新读取同一天的该范围。页面与程序读回只访问成功汇总记录。批量取证无法确认的项使用明确原因，禁止回退到逐资产文件扫描。第二阶段验证使用隔离实例和现成生产证据，正式调度启用另行执行。

## 12. 第二阶段验收记录

第二阶段已跑通每日总结、本地页面和同版结果查询，待 Review。逐资产复用仍有未覆盖的规则组。正式调度和页面开关保持关闭。

| 对照 | 验收结果 |
|---|---|
| §3 日更与变更刷新 | 隔离 Dagster 生成并读回 187 个目录主行。午夜计划选上海时间上一自然日。Refresh Sensor 验证已有总结后发现晚到产出，带上依赖项提交刷新，未受影响的行保留原观察时间。共用月分区用实际截至日选历史产出。 |
| §3.2 同版复用 | 调用 `get_completeness(instance, scope, version)` 时，资产、日期、范围、频度、实际输入版本、产出版本和规则版本一致才返回。验收比较了换版、换频度、输入变化、规则变化和新版没有 Check 的结果。 |
| §4 本地只读页面 | 由本地开关控制入口和两个 GET。验证日期筛选、更新与齐备双筛选、点击四项数字重置更新筛选并跳回第一页、指定总结版本的详情、所选日无总结，以及断线时保留同日已读结果。Prod 强开开关仍无入口和读路由，本机 Host 直达地址也返回 404。隔离 Chrome 在 1600 × 1000 的桌面窗口完成入口、筛选和详情验证。 |
| §8 单日取证及读回 | 只读试算 2026-11-20，读取 SSE 日历 61 行及 180 个 DG 产出范围的已有事件。取证和汇总实测 1.612 秒，得到 187 行。隔离真实 GraphQL 每次取总结或详情各发两条查询。187 行总结 HTTP 响应约 131 KB、80 毫秒，一项详情约 0.8 KB、15 毫秒。接口时间为隔离样本的一次测量。 |
| §9 回归验证 | DG 7 项、Web 7 项、前端及路由 20 项通过，Vite 构建通过。全站 TypeScript 检查在当前工作区报两处股票详情历史测试类型错误，涉及 `nineTurn`、`retryLayer`。 |

正式只读样本观察于 2026-11-22 06:27:51（上海时间）。2026-11-20 的 187 个主行里，已确认齐备 24 个、已确认缺口 2 个、待确认 148 个、不适用 13 个。两个缺口都是 ETF 日线行情，Raw、Silver 各发布了当天的数据，各缺已上市沪深 ETF 名单中的 2 只（应有 1,723 只）。主要指数周线、月线 Silver 的实际截至日为 11 月 20 日，更新列为已更新，已有的文件合同 Check 作为详情证据。

已实际复用的样本包括上交所日历、主要指数周线 Raw、股票周月行情、ETF 日线及复权因子的覆盖 Check、ETF 分钟线五频、东方财富板块成分 Raw、大盘资金流向和上市公司公告。现行东财板块成分 Silver 的 Check 在样本中通过，现有记录未带可用的目标文件版本，齐备状态仍待确认。

§5.1 的 129 个候选尚未逐项验完。股票日线、股票复权因子、主要指数分钟线及其衍生结果等，仍需逐组核对并接入现有证据。已接入但缺目标或输入版本的历史记录继续显示待确认。实际台账的结论仍逐项受证据范围限制。正式实例只执行了有界读取。总结事件的长期保留及正式调度启用后的实际运行留待本机启用验收。

## 13. 第二阶段逐资产复用复核

复用复核仍使用 2026-11-20 做验收。只在现有总结读取和判定中补接可验证证据。普通历史资产继续要求同资产、分区、版本、实际输入与业务规则吻合。产出及 Check 关联按 DG 当前存储约定查找，目标身份取生产已经发布的内容指纹、文件版本或经核对的正式交付版本。目标文件路径或运行编号单独出现时无法作版本依据。同版对账的结论按原业务范围表述。

本轮只读取 SSE 日历、中间结果及已有 DG 运行事件。扫描量由资产目录及其 Check 名约束，复核同一日不扩大分区或重新计算指标。定时计划、生产 Check、标准集及独立审计沿用既有阶段安排。验收逐项比对旧版总结、现有事件和新版总结，同版成功、目标换版、输入换版与旧证据缺字段均纳入回归。

2026-11-22 06:38（上海时间）复算 2026-11-20 正式 DG 的只读数据。187 个主行中，已确认齐备由 24 项增至 36 项，已确认缺口仍是 ETF 日线 Raw、Silver 两项，待确认由 148 项降至 136 项，不适用仍为 13 项。129 个复用候选已逐项对照，结果为 35 项齐备、2 项缺口、91 项缺证据、1 项当日无需交付。第 12 节是首轮样本，以下覆盖它的全部 148 项待确认。

旧版 Check 的分区字段有 101 条为空，但 DG 同时保存了它对应的真实物化。读取按资产键、Check 名、目标物化编号及其运行关联找回这些记录。已有明确分区的记录仍须匹配所选分区。旧版证据只用于它已经检查的业务范围。另按两项本机 ClickHouse 资产自己定义的交易日分区找回对应产出及 3 项 Check。两条更新状态变为「已更新」，两条齐备状态仍待确认。

这次同日只读复算耗时 0.872 秒。读取范围仍是一个交易日、187 个目录主行的已发生发布和检查，以及现用 SSE 日历窗口。阶段二接线使用已有的发布身份和 Check。以下逐组列出原 148 项，每条资产键只出现一次。

### 本次补接并判定齐备（12 项）

| 数据集和 DG 资产键 | 项数 | 所用证据或仍缺什么 |
|---|---:|---|
| 股票每日指标 Raw<br>`raw_tushare_daily_basic` | 1 | 复用最终文件 SHA-256 和日线代码集合指纹。覆盖 Check 同时核了必需状态值。 |
| 指数基础信息 Raw<br>`raw_tushare_index_basic` | 1 | 发布记录保留 3 页和 12,648 行，合同 Check 附同一物化和文件版本的分页对账。Silver 延续前次通过，并补入 Raw 版本关联。 |
| 历史确认全日停牌 Silver<br>`silver_stock_suspend_confirmed` | 1 | 产出及批准内容 Check 的逻辑指纹一致，保留批准原件与日历身份。 |
| 主要指数分钟行情 Raw（1、5、15、30、60 分钟）<br>`raw_major_index_mins_15m`、`raw_major_index_mins_1m`、`raw_major_index_mins_30m`、`raw_major_index_mins_5m`、`raw_major_index_mins_60m` | 5 | 正式发布的源版本包含当次规范化镜像的记录内容。同次 Check 绑定目标及固定名单的范围指纹，已核必备时点。 |
| 股票技术因子 Raw、Silver<br>`raw_tushare_stk_factor_pro`、`silver_stock_factor_pro` | 2 | 两层均读取实际文件 SHA-256、当天源批和有效范围摘要，生产源覆盖门禁已通过。Silver 另有同版 Raw 与键值对账。 |
| ETF 基础信息 Raw、Silver<br>`raw_tushare_etf_basic`、`silver_etf_basic` | 2 | Raw 用冻结快照指纹，Silver 用内容指纹及同一个 Raw 快照。复用原有检查。 |

### 复用候选的同版证据仍不足（91 项）

| 数据集和 DG 资产键 | 项数 | 所用证据或仍缺什么 |
|---|---:|---|
| 同花顺个股资金流向 Raw、Silver<br>`raw_tushare_moneyflow_ths`、`silver_moneyflow_ths` | 2 | 在 DG 未找到该日两层的对应产出。Raw 需要最终缺码列表与当批冻结名录版本，Silver 需要同版 Raw。 |
| 普通个股、东方财富个股、东方财富板块、同花顺概念、同花顺行业资金流向 Silver<br>`silver_moneyflow`、`silver_moneyflow_cnt_ths`、`silver_moneyflow_dc`、`silver_moneyflow_ind_dc`、`silver_moneyflow_ind_ths` | 5 | 已读到标准化 Check 和同版 Raw 文件指纹。本批只证实转换一致，各自 Raw 的业务范围尚待验证。 |
| 股票基础信息 Raw<br>`raw_tushare_stock_basic` | 1 | 当日全状态快照 5,924 行、现有两个 Check 通过。快照只有发布时间、路径和计数，当前记录无法绑定这版文件及上一交易日适用版本。 |
| 东方财富三级行业层级 Silver<br>`silver_dc_industry_hierarchy` | 1 | Check 通过且发布记录有基线和分类参照指纹。未保存输出内容身份，Check 也未带它实际读取的分类文件版本。 |
| 股票日线 Raw、Silver<br>`raw_tushare_stock_daily`、`silver_stock_daily` | 2 | 旧格式 Check 现已正确关联。已上市/生命周期与停牌覆盖结论缺当次输入指纹，输出也只有路径和行数。 |
| 股票复权因子 Raw、Silver<br>`raw_tushare_adj_factor`、`silver_adj_factor` | 2 | Silver 生命周期覆盖 Check 已关联。该次输入的生命周期、Raw 文件及 Silver 文件没有可用的版本绑定。 |
| 股票日线神奇九转 Silver<br>`silver_stock_nineturn_daily` | 1 | 有规范化 Check，未留下可核对的 Silver、Raw 及股票身份映射的文件版本。Raw 的日线代码覆盖按后续生产 Check 处理。 |
| 股票日线前复权趋势通道结果及状态 Gold<br>`gold_stock_daily_trend_channel`、`gold_stock_daily_trend_channel_state` | 2 | 输入覆盖 Check 已核当日输入及承接状态。两版目标文件、实际前序/生命周期/前复权日线版本没有一起保存。 |
| 股票日线前复权九转 Gold<br>`gold_stock_daily_qfq_nineturn` | 1 | 有当次源文件指纹和键对账。该日九转结果本身缺正式输出版本，前复权日线范围仍待确认。 |
| 板块日线技术指标 Gold<br>`gold_dc_daily_technical` | 1 | 有当日板块行情键对账，只有输入路径和文件数，缺实际输入与目标身份。 |
| 股票前复权分钟行情 Gold（1、5、15、30、60、90、120 分钟）<br>`gold_stk_mins_qfq_120m`、`gold_stk_mins_qfq_15m`、`gold_stk_mins_qfq_1m`、`gold_stk_mins_qfq_30m`、`gold_stk_mins_qfq_5m`、`gold_stk_mins_qfq_60m`、`gold_stk_mins_qfq_90m` | 7 | 已关联 7 个频度的覆盖 Check，有实际统计及按股票保存的文件路径，缺该日目标及 Silver/复权输入版本，Silver 常规覆盖仍待验证。 |
| 股票前复权分钟九转 Gold（30、60、90、120 分钟）<br>`gold_stk_mins_qfq_nineturn_120m`、`gold_stk_mins_qfq_nineturn_30m`、`gold_stk_mins_qfq_nineturn_60m`、`gold_stk_mins_qfq_nineturn_90m` | 4 | 有当次源文件指纹及原生频度键对账。目标未发布可审计的版本，前复权分钟先决证据尚缺。 |
| 股票前复权分钟 MACD/KDJ 指标 Gold（1、5、15、30、60、90、120 分钟）<br>`gold_stk_mins_qfq_macd_kdj_120m`、`gold_stk_mins_qfq_macd_kdj_15m`、`gold_stk_mins_qfq_macd_kdj_1m`、`gold_stk_mins_qfq_macd_kdj_30m`、`gold_stk_mins_qfq_macd_kdj_5m`、`gold_stk_mins_qfq_macd_kdj_60m`、`gold_stk_mins_qfq_macd_kdj_90m` | 7 | 有当日源/指标统计和覆盖 Check。未绑定按股票保存的年文件中当日切片与输入版本。其分钟行情的齐备证据仍待确认。 |
| 指数日线 Raw、Silver<br>`raw_index_daily`、`silver_index_daily` | 2 | Raw 出现 820 个登记代码并有预期名单指纹，未记录目标内容版本。Silver Check 比实有 Raw，缺目标和当次实际 Raw 文件版本。 |
| 通用指数分钟行情 Gold（1、5、15、30、60、90、120 分钟）<br>`gold_index_mins_120m`、`gold_index_mins_15m`、`gold_index_mins_1m`、`gold_index_mins_30m`、`gold_index_mins_5m`、`gold_index_mins_60m`、`gold_index_mins_90m` | 7 | 已有按频度的规范时点核验。缺该版目标和源文件身份，上游 Raw、Silver 是否漏整只指数仍待相应审计。 |
| 主要指数分钟行情 Silver、Gold（各 1、5、15、30、60、90、120 分钟）<br>`gold_major_index_mins_120m`、`gold_major_index_mins_15m`、`gold_major_index_mins_1m`、`gold_major_index_mins_30m`、`gold_major_index_mins_5m`、`gold_major_index_mins_60m`、`gold_major_index_mins_90m`、`silver_major_index_mins_120m`、`silver_major_index_mins_15m`、`silver_major_index_mins_1m`、`silver_major_index_mins_30m`、`silver_major_index_mins_5m`、`silver_major_index_mins_60m`、`silver_major_index_mins_90m` | 14 | 现有 Check 已按批准范围、原生频度和时点验键，Silver 的范围哈希是名单范围。两层都缺绑定到 Check 的实际目标版本。 |
| 主要指数量化结构 Gold<br>`gold_major_index_quantitative_structure` | 1 | 所选日一行，完成 Check 通过。计算结果未保存内容指纹或其他正式目标版本，无法交给下游按版复用。 |
| 主要指数日线九转 Gold、分钟九转 Gold（5、15、30、60、90、120 分钟）<br>`gold_major_index_daily_nineturn`、`gold_major_index_mins_nineturn_120m`、`gold_major_index_mins_nineturn_15m`、`gold_major_index_mins_nineturn_30m`、`gold_major_index_mins_nineturn_5m`、`gold_major_index_mins_nineturn_60m`、`gold_major_index_mins_nineturn_90m` | 7 | 源文件指纹与现行键对账可见，目标本身没有正式版本。源文件指纹不标识九转输出。 |
| 东方财富板块成分 Silver<br>`silver_dc_member` | 1 | 核心 Check 与当天产出原生关联并通过，文件路径及行数仍无法标识发布版本。 |
| 东方财富板块行情 Raw、Silver<br>`raw_tushare_dc_daily`、`silver_dc_daily` | 2 | Raw 核验通过，记录缺实际分类参照版本。Silver 的核心 Check 当时读不到同日分类文件，本次读回没有找到能替代的同版通过记录。 |
| 主要指数日线 Gold<br>`gold_market_major_indices_daily` | 1 | 同日固定主要指数名单和排序 Check 已关联，目标只有行数和分区，没有该次发布的目标身份。 |
| 市场宽度、股票涨跌幅分布、财富市场成交额 Gold<br>`gold_market_breadth_daily`、`gold_stock_return_distribution`、`gold_wealth_market_turnover` | 3 | 原 Check 已关联并核同日投影或汇总。缺实际输入与目标版本，上游股票日线或分钟线的覆盖结论也未绑定。 |
| 本机 ClickHouse 市场宽度<br>`ch_share_fact_market_breadth_daily` | 1 | 交易日分区、发布事件和对账 Check 已读到。没有该版 ClickHouse 结果及两张实际输入的版本。 |
| 指数技术因子 Raw、Silver<br>`raw_tushare_idx_factor_pro`、`silver_index_factor_pro` | 2 | 两层已有生效名单、键和 Raw 转换 Check。记录路径和 11 行覆盖，未提供实际目标版本及 Silver 读取的同版 Raw 文件。 |
| 主要指数分钟技术指标及状态 Gold（各 1、5、15、30、60、90、120 分钟）<br>`gold_major_index_mins_technical_120m`、`gold_major_index_mins_technical_15m`、`gold_major_index_mins_technical_1m`、`gold_major_index_mins_technical_30m`、`gold_major_index_mins_technical_5m`、`gold_major_index_mins_technical_60m`、`gold_major_index_mins_technical_90m`、`gold_major_index_mins_technical_state_120m`、`gold_major_index_mins_technical_state_15m`、`gold_major_index_mins_technical_state_1m`、`gold_major_index_mins_technical_state_30m`、`gold_major_index_mins_technical_state_5m`、`gold_major_index_mins_technical_state_60m`、`gold_major_index_mins_technical_state_90m` | 14 | 结果的同日源覆盖、状态每只一行和末端时点 Check 可见。结果及递推状态还缺实际版本和本次所用输入身份。 |

### 沿用后续阶段安排（45 项）

| 数据集和 DG 资产键 | 项数 | 所用证据或仍缺什么 |
|---|---:|---|
| 股票日线前复权 Gold<br>`gold_stock_daily_qfq` | 1 | 本样本原列第三阶段补 Check。当前口径已转入 §5.1，直接复用当日日线 Check、同日文件存在及当次 Gold 任务成功。 |
| 本机 ClickHouse 板块日线技术指标<br>`ch_dc_daily_technical` | 1 | 第三阶段。原 Check 通过，本日已有交付。还需按实际业务键双向对账。 |
| 主要指数周线、月线 Silver<br>`silver_index_monthly`、`silver_index_weekly` | 2 | 第三阶段。实际截至日已经到 11 月 20 日。现有 Check 未记录当日每个应有指数均已达到该截至日。 |
| 股票基础信息、股票曾用名、股票身份映射、股票生命周期 Silver<br>`silver_namechange`、`silver_stock_basic`、`silver_stock_identity_map`、`silver_stock_lifecycle` | 4 | 第三阶段。原快照 Check 继续保留。用各自正式转换规则补同版输入输出差异。 |
| 普通个股、东方财富个股、东方财富板块、同花顺概念、同花顺行业资金流向 Raw<br>`raw_tushare_moneyflow`、`raw_tushare_moneyflow_cnt_ths`、`raw_tushare_moneyflow_dc`、`raw_tushare_moneyflow_ind_dc`、`raw_tushare_moneyflow_ind_ths` | 5 | 第三阶段。各自已有交付字段和质量检查。所选日应有代码名单及相应覆盖仍需生产 Check。东方财富板块资金流向还需当日标准集。 |
| 股票日线神奇九转 Raw<br>`raw_tushare_stk_nineturn` | 1 | 第三阶段。现有检查不代替当日应有股票日线代码的覆盖证明。 |
| 股票分钟线 Raw、Silver（各 1、5、15、30、60 分钟）<br>`raw_stk_mins_15m`、`raw_stk_mins_1m`、`raw_stk_mins_30m`、`raw_stk_mins_5m`、`raw_stk_mins_60m`、`silver_stk_mins_15m`、`silver_stk_mins_1m`、`silver_stk_mins_30m`、`silver_stk_mins_5m`、`silver_stk_mins_60m` | 10 | 第三阶段。复用旧 Check 展示已有结果。常规时段按已批准的停牌规则校验应有代码和总根数。 |
| 股票前复权分钟 MACD/KDJ 递推状态 Gold（1、5、15、30、60、90、120 分钟）<br>`gold_stk_mins_qfq_macd_kdj_state_120m`、`gold_stk_mins_qfq_macd_kdj_state_15m`、`gold_stk_mins_qfq_macd_kdj_state_1m`、`gold_stk_mins_qfq_macd_kdj_state_30m`、`gold_stk_mins_qfq_macd_kdj_state_5m`、`gold_stk_mins_qfq_macd_kdj_state_60m`、`gold_stk_mins_qfq_macd_kdj_state_90m` | 7 | 第三阶段。需绑定同频输入及应承接的前序状态。 |
| 东方财富板块分类 Raw、Silver<br>`raw_tushare_dc_index`、`silver_dc_index` | 2 | 第三阶段的覆盖接线依赖第四阶段的正式标准集。 |
| 通用指数分钟线 Raw（1、5、15、30、60 分钟）和 Silver（另含 90、120 分钟）<br>`raw_index_mins_15m`、`raw_index_mins_1m`、`raw_index_mins_30m`、`raw_index_mins_5m`、`raw_index_mins_60m`、`silver_index_mins_120m`、`silver_index_mins_15m`、`silver_index_mins_1m`、`silver_index_mins_30m`、`silver_index_mins_5m`、`silver_index_mins_60m`、`silver_index_mins_90m` | 12 | 第五阶段。已有交付和文件合同，独立任务仍需核当批激活名单和分钟时点/合成范围。 |

复核验收覆盖 148 个唯一资产键。前后仍读取相同的已选发布记录，并新增识别此前未读到的两个本机 ClickHouse 发布。12 项同版证据可直接复用，5 类资金流向 Silver 已记录实际 Raw 版本和转换结论。DG 12 项、Web 7 项回归通过，文档完整性检查及代码格式检查通过。本轮保持定时计划关闭，正式 DG 仅进行了只读查询。

## 14. 91 项待确认的处理方案（待 Review）

把 2026-11-20 这 91 项分别查清楚，让后续的日报能说明数据已齐备、确实缺数据，或者当前还缺哪份证据。这里保留第二阶段的只读样本和处理清单，第三阶段实现及验收见第 5.4 节。正式调度保持关闭。

| 优先按什么处理 | 项数 | 可预期的结果 |
|---|---:|---|
| 复用第三阶段的上游覆盖 | 5 | 三项可随现有第三阶段工作收口，前提是对应 Raw 同日同版通过。其中同花顺概念增减仍按已定流程确认。东方财富个股还需要核实实际采用的股票日线版本。东方财富板块还需要第四阶段的当日标准集。 |
| 查已有发布凭证，必要时提议随原生产补版本记录 | 84 | 先确认记录是真缺，还是已经存在于本次发布的日志、元数据或正式提升凭证里。若以前没保存，未来产出可按评审后的方案记录。历史日期能否确认，取决于当时的产出和输入是否还能可靠对应。 |
| 交付样本复核 | 2 | 同花顺个股资金流向 Raw、Silver 的 11 月 20 日交付观察保留。另用 11 月 19 日验证这两项已有证据能证明什么，结果见 §14.4。 |

在这次样本中，91 项均保持「待确认」。东方财富板块行情 Silver 曾因读不到同日分类参照而未通过，这条 Check 还没有证实行情本身缺板块。第 13 节两个 ETF 日线缺口已证实，属于另外两项。未来可以给这 91 项逐项建立闭环，但旧版本如果已被覆盖且当时的凭证未保留，该历史日会继续保留「待确认」。

### 14.1 共同处理与验收方法

1. **优先用当时留下的凭证。** 从目标业务日、资产键、实际分区和目标发布记录出发，核对同一次运行的 Check、正式发布清单或提升凭证。按 §3.2 核范围、目标版本、Check 实际读取的输入版本及规则口径。现有文件路径、时间、行数、源指纹和分类范围指纹各自只能作其原本用途。年文件以实际发布批次及本次覆盖的日期和频度为准，只有候选或未完成提升的记录不可作为正式证据。
2. **缺记录时给未来产出补证据的提案。** 只针对逐项仍缺的字段，优先在既有生产写入、提升或 Check 已经取得文件身份和输入版本的位置留存这些值。适用时由审计汇总复用已有内容指纹或正式版本。若必须追加文件读取、重新核算、改动生产 Check 或补跑历史，先说明具体资产、日期、读取量及验收方法，另行评审。历史日期使用可确认的原版本，找到新版本只能据此形成一次新的核验结论。
3. **按同版依赖先查源再查下游。** 只有源结果、输入和目标绑定，才用既有转换、键和行数结果判定。第三、四、五阶段交付的新证据可用于其适用的版本。若源端结果仍待确认，页面保留更新状态，并显示当前能证明的范围。晚到或换版时，只重读该日受影响的已有结果。
4. **核实交付时先看正式单日路径和当批记录。** 对应日期适用且确实未交付时，按 §3.3 判更新状态。已有文件但找不到可靠版本时，记录实际可证的交付状态，齐备继续待确认。若有可核对的同版 Check 和规定的覆盖证据，再判齐备或缺口。
5. **验收以代表资产的真实同版记录为准。** 对照同日旧、新版本和当前状态，至少核对三种情况：已有凭证能够重用、版本换掉后旧结果无法套用、上游有缺口时下游仍可显示已更新和待确认。以单资产、单业务日的已有记录为读取单位，记录主要读量、耗时及重试范围。第二阶段既有批量读和两列状态保持原口径。

### 14.2 可复用第三阶段上游结论的 5 项

这五项在样本中已有 Silver 标准化 Check 和对应 Raw 文件指纹。按当前的资金流向读回规则，先确认新取得的是 Silver 当时所用的那版 Raw，再继承齐备。用于验收 2026-11-20 时，也要有该版 Raw 的结果。 [同版 Raw 的取证入口](../../orchestrator/src/orchestrator/defs/daily_data_audit/summary.py#L177)

| 数据集与资产键 | 后续阶段能解决什么 | 查找顺序或验收条件 |
|---|---|---|
| 普通个股资金流向 Silver<br>`silver_moneyflow` | 第三阶段给 Raw 核当日上市沪深京 A 股，涵盖全天停牌与上市首日。 | 对上该版 Raw 的指纹，汇总直接复用现有标准化 Check。 |
| 同花顺概念资金流向 Silver<br>`silver_moneyflow_cnt_ths` | 第三阶段给 Raw 核生效的概念基线。既有增减按已定流程确认。 | 确认该日生效的基线和同版 Raw 通过后，复用 Silver 标准化 Check。 |
| 同花顺行业资金流向 Silver<br>`silver_moneyflow_ind_ths` | 第三阶段给 Raw 核生效的 90 项 881 行业名单。 | 同版 Raw 覆盖通过后，复用 Silver 标准化 Check。 |
| 东方财富个股资金流向 Silver<br>`silver_moneyflow_dc` | 第三阶段给 Raw 核当天上市且有成交的沪深京 A 股。检查还依赖下表的「股票日线 Silver」同日同版证据。 | 顺序是股票日线 Silver、资金流向 Raw、资金流向 Silver。三者对上版本后才确认覆盖。 |
| 东方财富板块资金流向 Silver<br>`silver_moneyflow_ind_dc` | 第三阶段给 Raw 接分类覆盖，第四阶段生成当日生效的行业、地域、概念标准集。 | 标准集与 Raw 覆盖就绪后，对上 Silver 所用 Raw 版本再判。 |

### 14.3 须查发布凭证或补版本记录的 84 项

每行的动作先用于查已有证据。表中提到补记的内容是拟评审的最小范围。原有生产 Check 负责的业务校验继续复用。已有后续阶段供给上游证据时，也要把本行产出和对应输入绑定。

| 数据集与资产键 | 后续阶段能解决什么 | 查找顺序或验收条件 |
|---|---|---|
| 股票基础信息 Raw<br>`raw_tushare_stock_basic` | 第三阶段对股票基础信息 Silver 补转换对账。 | 找当日和上一交易日全状态快照的发布版本、行数和当日 Check。按已确认的全状态行数净增减绝对值 ≤20 条核对。以后留两份参照身份。 |
| 东方财富三级行业层级 Silver<br>`silver_dc_industry_hierarchy` | 既有第三阶段未包含本项的版本记录。 | 找正式层级快照版本、发布所用基线和指定的板块分类参照版本。已有基线和分类范围指纹可作线索，验三者与核心 Check 对应。 |
| 股票日线 Raw<br>`raw_tushare_stock_daily` | 第三阶段可补部分快照或下游依据。本项的同日行情与停牌输入版本仍须单独核实。 | 找当日报价版本、实际使用的上市股票名单与同日停牌证据。复用原 Check 对其适用范围的结论。 |
| 股票日线 Silver<br>`silver_stock_daily` | 第三阶段可补股票生命周期快照的对账。此项同时是东方财富个股资金流向 Raw、日线神奇九转 Raw 等第三阶段检查的先决条件。 | 优先查当日 Silver 及实际使用的生命周期、股票日线 Raw、全日停牌版本。关联原有应有代码对账后才能供下游复用。 |
| 股票复权因子 Raw<br>`raw_tushare_adj_factor` | 第三阶段的生命周期快照对账可提供上游依据。 | 找 Raw 目标文件、当日上市股票生命周期版本和 Silver 覆盖 Check 采用的实际 Raw。复用能证明 Raw 覆盖的证据，全天停牌仍在应有范围内。 |
| 股票复权因子 Silver<br>`silver_adj_factor` | 第三阶段的生命周期快照对账可提供上游依据。 | 找 Silver 目标、原 Check 实际读到的 Raw 及生命周期版本。按原规则验上市股票覆盖及 Raw 标准化。 |
| 股票日线神奇九转 Silver<br>`silver_stock_nineturn_daily` | 第三阶段给 Raw 补应有股票日线代码覆盖，并处理股票身份映射的同版对账。 | 对上 Silver 目标、当日实际 Raw 和身份映射版本。复用原标准化 Check，结合 Raw 的同版覆盖。 |
| 股票日线前复权趋势通道 Gold<br>`gold_stock_daily_trend_channel` | 前复权日线的简化口径只用于该行情文件的日报行。依赖的逐键覆盖仍须有各自的同版证据。 | 找 Gold 输出、当天前复权日线、生命周期和适用前序状态的版本。复用原输入覆盖 Check。 |
| 股票日线前复权趋势通道状态 Gold<br>`gold_stock_daily_trend_channel_state` | 前复权日线的简化口径只用于该行情文件的日报行。依赖的逐键覆盖仍须有各自的同版证据。 | 找状态输出、实际前序状态、生命周期和当日日线版本。绑定同次趋势通道输入覆盖 Check，复用它核到的承接范围。 |
| 股票日线前复权九转 Gold<br>`gold_stock_daily_qfq_nineturn` | 前复权日线的简化口径只用于该行情文件的日报行。依赖的逐键覆盖仍须有各自的同版证据。 | 已有源文件指纹可用。找当天九转输出版本，对上实际日线源和已有键对账。 |
| 东方财富板块日线技术指标 Gold<br>`gold_dc_daily_technical` | 第三阶段的技术指标对账针对本机 ClickHouse 交付。此项先依赖实际用到的板块日线 Silver 证据。 | 找 Gold 输出和 Check 所用同日板块日线 Silver 版本，复用原有业务键对账。 |
| 指数日线 Raw<br>`raw_index_daily` | 既有第三阶段未包含本项的版本记录。 | 保留发布已有的应有名单指纹和代码覆盖。找该次目标文件版本，确认指数日线与此批名单和覆盖 Check 对应。 |
| 指数日线 Silver<br>`silver_index_daily` | 既有第三阶段未包含本项的版本记录。 | 找目标文件版本和实际读取的同日 Raw 版本。原 Check 对实有 Raw 的转换结论供复用，原始覆盖由 Raw 证明。 |
| 主要指数量化结构 Gold<br>`gold_major_index_quantitative_structure` | 既有第三阶段未包含本项的版本记录。 | 找所选日一行计算结果的正式产出版本，与完成 Check 绑定。按已确认的当日计算成功口径判定，无事件仍可通过。 |
| 主要指数日线九转 Gold<br>`gold_major_index_daily_nineturn` | 既有第三阶段未包含本项的版本记录。 | 找九转目标版本，核对已存的源指纹是否对上实际用到的主要指数日线 Gold。复用原业务键对账。 |
| 东方财富板块成分 Silver<br>`silver_dc_member` | 既有第三阶段未包含本项的版本记录。 | 先找样本当日已通过核心 Check 对应的正式 Silver 文件版本。能核实则按既定口径通过。往后补记正式目标身份，沿用成分的现有 Check。 |
| 东方财富板块行情 Raw<br>`raw_tushare_dc_daily` | 第四阶段可提供相应日期的板块分类标准。先核它是否与原 Check 使用的分类版本相同。 | 找目标和用于核验的当日分类 Raw 版本，复用现有缺行情、合法等待等结论。 |
| 东方财富板块行情 Silver<br>`silver_dc_daily` | 第四阶段可提供相应日期的板块分类标准。先核它是否与原 Check 使用的分类版本相同。 | 先核样本日分类 Silver 是否已经实际交付及其版本。旧 Check 因读不到参照失败。用可绑定的行情 Silver、分类 Silver 及本次转换所用 Raw 的凭证和有效 Check 重判。 |
| 主要指数日线 Gold<br>`gold_market_major_indices_daily` | 既有第三阶段未包含本项的版本记录。 | 找正式目标发布身份，把它绑定到当日固定主要指数名单和排序 Check。保留该次输入日线版本，以便解释结果和供下游复用。 |
| 市场宽度 Gold<br>`gold_market_breadth_daily` | 通过股票日线链依赖已核验的同版股票日线 Silver。 | 找正式 Gold 输出与实际股票日线 Silver 文件版本，再复用原汇总对账。 |
| 股票涨跌幅分布 Gold<br>`gold_stock_return_distribution` | 通过股票日线链依赖已核验的同版股票日线 Silver。 | 找涨跌幅分布当日输出与实际股票日线 Silver 版本，复用原投影和汇总对账。 |
| 财富端市场成交额 Gold<br>`gold_wealth_market_turnover` | 第三阶段可提供五个实际使用的股票分钟行情 Silver 的覆盖依据。股票日线 Silver 仍按本表处理。 | 找同日五频输入、股票日线输入和成交额 Gold 正式发布版本。复用已有汇总对账，只有路径和统计时仍待确认。 |
| 本机 ClickHouse 市场宽度<br>`ch_share_fact_market_breadth_daily` | 第三阶段直接补的是另一项本机 ClickHouse 板块日线技术指标。此项等待市场宽度和股票涨跌幅分布两份 Gold 输入。 | 从本机交付凭证找当日写入批次和两份实际 Gold 源版本。已有对账无需重算，确认版本关联后才复用。 |
| 指数技术因子 Raw<br>`raw_tushare_idx_factor_pro` | 既有第三阶段未包含本项的版本记录。 | 找该日 Raw 正式输出身份和当时采用的有效范围，与原覆盖和键 Check 关联。 |
| 指数技术因子 Silver<br>`silver_index_factor_pro` | 既有第三阶段未包含本项的版本记录。 | 找 Silver 正式输出和实际 Raw 版本，复用原有效名单和转换 Check。 |
| 股票前复权 1 分钟行情 Gold<br>`gold_stk_mins_qfq_1m` | 第三阶段补实际采用的股票分钟行情 Silver 常规覆盖。 现行输入合同使用 1 分钟 Silver。 | 按 §5.1 复用上游当日齐备及 Gold 的同日成功任务和文件交付。 |
| 股票前复权 5 分钟行情 Gold<br>`gold_stk_mins_qfq_5m` | 第三阶段补实际采用的股票分钟行情 Silver 常规覆盖。 现行输入合同使用 1 分钟 Silver。 | 按 §5.1 复用上游当日齐备及 Gold 的同日成功任务和文件交付。 |
| 股票前复权 15 分钟行情 Gold<br>`gold_stk_mins_qfq_15m` | 第三阶段补实际采用的股票分钟行情 Silver 常规覆盖。 现行输入合同使用 5 分钟 Silver。 | 按 §5.1 复用上游当日齐备及 Gold 的同日成功任务和文件交付。 |
| 股票前复权 30 分钟行情 Gold<br>`gold_stk_mins_qfq_30m` | 第三阶段补实际采用的股票分钟行情 Silver 常规覆盖。 现行输入合同使用 5 分钟 Silver。 | 按 §5.1 复用上游当日齐备及 Gold 的同日成功任务和文件交付。 |
| 股票前复权 60 分钟行情 Gold<br>`gold_stk_mins_qfq_60m` | 第三阶段补实际采用的股票分钟行情 Silver 常规覆盖。 现行输入合同使用 30 分钟 Silver。 | 按 §5.1 复用上游当日齐备及 Gold 的同日成功任务和文件交付。 |
| 股票前复权 90 分钟行情 Gold<br>`gold_stk_mins_qfq_90m` | 第三阶段补实际采用的股票分钟行情 Silver 常规覆盖。 现行输入合同使用 30 分钟 Silver。 | 按 §5.1 复用上游当日齐备及 Gold 的同日成功任务和文件交付。 |
| 股票前复权 120 分钟行情 Gold<br>`gold_stk_mins_qfq_120m` | 第三阶段补实际采用的股票分钟行情 Silver 常规覆盖。 现行输入合同使用 60 分钟 Silver。 | 按 §5.1 复用上游当日齐备及 Gold 的同日成功任务和文件交付。 |
| 股票前复权 30 分钟九转 Gold<br>`gold_stk_mins_qfq_nineturn_30m` | 依赖同日 30 分钟前复权 Gold。第三阶段补实际采用的股票分钟行情 Silver 常规覆盖。 | 找 30 分钟九转目标发布凭证，与已有源指纹、同频前复权行情和原键对账绑定。 |
| 股票前复权 60 分钟九转 Gold<br>`gold_stk_mins_qfq_nineturn_60m` | 依赖同日 60 分钟前复权 Gold。第三阶段补实际采用的股票分钟行情 Silver 常规覆盖。 | 找 60 分钟九转目标发布凭证，与已有源指纹、同频前复权行情和原键对账绑定。 |
| 股票前复权 90 分钟九转 Gold<br>`gold_stk_mins_qfq_nineturn_90m` | 依赖同日 90 分钟前复权 Gold。第三阶段补实际采用的股票分钟行情 Silver 常规覆盖。 | 找 90 分钟九转目标发布凭证，与已有源指纹、同频前复权行情和原键对账绑定。 |
| 股票前复权 120 分钟九转 Gold<br>`gold_stk_mins_qfq_nineturn_120m` | 依赖同日 120 分钟前复权 Gold。第三阶段补实际采用的股票分钟行情 Silver 常规覆盖。 | 找 120 分钟九转目标发布凭证，与已有源指纹、同频前复权行情和原键对账绑定。 |
| 股票前复权 1 分钟 MACD/KDJ 指标 Gold<br>`gold_stk_mins_qfq_macd_kdj_1m` | 依赖同日 1 分钟前复权 Gold。第三阶段补实际采用的股票分钟行情 Silver 常规覆盖。 | 找 1 分钟指标年文件本次正式提升凭证及所用前复权版本。复用该日同频股票代码覆盖与总行数结果。 |
| 股票前复权 5 分钟 MACD/KDJ 指标 Gold<br>`gold_stk_mins_qfq_macd_kdj_5m` | 依赖同日 5 分钟前复权 Gold。第三阶段补实际采用的股票分钟行情 Silver 常规覆盖。 | 找 5 分钟指标年文件本次正式提升凭证及所用前复权版本。复用该日同频股票代码覆盖与总行数结果。 |
| 股票前复权 15 分钟 MACD/KDJ 指标 Gold<br>`gold_stk_mins_qfq_macd_kdj_15m` | 依赖同日 15 分钟前复权 Gold。第三阶段补实际采用的股票分钟行情 Silver 常规覆盖。 | 找 15 分钟指标年文件本次正式提升凭证及所用前复权版本。复用该日同频股票代码覆盖与总行数结果。 |
| 股票前复权 30 分钟 MACD/KDJ 指标 Gold<br>`gold_stk_mins_qfq_macd_kdj_30m` | 依赖同日 30 分钟前复权 Gold。第三阶段补实际采用的股票分钟行情 Silver 常规覆盖。 | 找 30 分钟指标年文件本次正式提升凭证及所用前复权版本。复用该日同频股票代码覆盖与总行数结果。 |
| 股票前复权 60 分钟 MACD/KDJ 指标 Gold<br>`gold_stk_mins_qfq_macd_kdj_60m` | 依赖同日 60 分钟前复权 Gold。第三阶段补实际采用的股票分钟行情 Silver 常规覆盖。 | 找 60 分钟指标年文件本次正式提升凭证及所用前复权版本。复用该日同频股票代码覆盖与总行数结果。 |
| 股票前复权 90 分钟 MACD/KDJ 指标 Gold<br>`gold_stk_mins_qfq_macd_kdj_90m` | 依赖同日 90 分钟前复权 Gold。第三阶段补实际采用的股票分钟行情 Silver 常规覆盖。 | 找 90 分钟指标年文件本次正式提升凭证及所用前复权版本。复用该日同频股票代码覆盖与总行数结果。 |
| 股票前复权 120 分钟 MACD/KDJ 指标 Gold<br>`gold_stk_mins_qfq_macd_kdj_120m` | 依赖同日 120 分钟前复权 Gold。第三阶段补实际采用的股票分钟行情 Silver 常规覆盖。 | 找 120 分钟指标年文件本次正式提升凭证及所用前复权版本。复用该日同频股票代码覆盖与总行数结果。 |
| 通用指数 1 分钟行情 Gold<br>`gold_index_mins_1m` | 第五阶段可提供实际采用的通用指数 1 分钟 Silver 的上游审计结论。 | 先找 1 分钟 Gold 目标和实际 1 分钟 Silver 版本。复用原 Gold 时点与覆盖 Check，等待实际输入齐备。 |
| 通用指数 5 分钟行情 Gold<br>`gold_index_mins_5m` | 第五阶段可提供实际采用的通用指数 1 分钟 Silver 的上游审计结论。 | 先找 5 分钟 Gold 目标和实际 1 分钟 Silver 版本。复用原 Gold 时点与覆盖 Check，等待实际输入齐备。 |
| 通用指数 15 分钟行情 Gold<br>`gold_index_mins_15m` | 第五阶段可提供实际采用的通用指数 5 分钟 Silver 的上游审计结论。 | 先找 15 分钟 Gold 目标和实际 5 分钟 Silver 版本。复用原 Gold 时点与覆盖 Check，等待实际输入齐备。 |
| 通用指数 30 分钟行情 Gold<br>`gold_index_mins_30m` | 第五阶段可提供实际采用的通用指数 5 分钟 Silver 的上游审计结论。 | 先找 30 分钟 Gold 目标和实际 5 分钟 Silver 版本。复用原 Gold 时点与覆盖 Check，等待实际输入齐备。 |
| 通用指数 60 分钟行情 Gold<br>`gold_index_mins_60m` | 第五阶段可提供实际采用的通用指数 30 分钟 Silver 的上游审计结论。 | 先找 60 分钟 Gold 目标和实际 30 分钟 Silver 版本。复用原 Gold 时点与覆盖 Check，等待实际输入齐备。 |
| 通用指数 90 分钟行情 Gold<br>`gold_index_mins_90m` | 第五阶段可提供实际采用的通用指数 30 分钟 Silver 的上游审计结论。 | 先找 90 分钟 Gold 目标和实际 30 分钟 Silver 版本。复用原 Gold 时点与覆盖 Check，等待实际输入齐备。 |
| 通用指数 120 分钟行情 Gold<br>`gold_index_mins_120m` | 第五阶段可提供实际采用的通用指数 60 分钟 Silver 的上游审计结论。 | 先找 120 分钟 Gold 目标和实际 60 分钟 Silver 版本。复用原 Gold 时点与覆盖 Check，等待实际输入齐备。 |
| 主要指数 1 分钟行情 Silver<br>`silver_major_index_mins_1m` | 优先复用已接入的主要指数 Raw 证据。按当次实际来源核原生或合成链。 | 找 1 分钟 Silver 目标版本，并对上其覆盖 Check 与实际输入。发布记录只有名单范围指纹时，继续找正式交付凭证。 |
| 主要指数 5 分钟行情 Silver<br>`silver_major_index_mins_5m` | 优先复用已接入的主要指数 Raw 证据。按当次实际来源核原生或合成链。 | 找 5 分钟 Silver 目标版本，并对上其覆盖 Check 与实际输入。发布记录只有名单范围指纹时，继续找正式交付凭证。 |
| 主要指数 15 分钟行情 Silver<br>`silver_major_index_mins_15m` | 优先复用已接入的主要指数 Raw 证据。按当次实际来源核原生或合成链。 | 找 15 分钟 Silver 目标版本，并对上其覆盖 Check 与实际输入。发布记录只有名单范围指纹时，继续找正式交付凭证。 |
| 主要指数 30 分钟行情 Silver<br>`silver_major_index_mins_30m` | 优先复用已接入的主要指数 Raw 证据。按当次实际来源核原生或合成链。 | 找 30 分钟 Silver 目标版本，并对上其覆盖 Check 与实际输入。发布记录只有名单范围指纹时，继续找正式交付凭证。 |
| 主要指数 60 分钟行情 Silver<br>`silver_major_index_mins_60m` | 优先复用已接入的主要指数 Raw 证据。按当次实际来源核原生或合成链。 | 找 60 分钟 Silver 目标版本，并对上其覆盖 Check 与实际输入。发布记录只有名单范围指纹时，继续找正式交付凭证。 |
| 主要指数 90 分钟行情 Silver<br>`silver_major_index_mins_90m` | 优先复用已接入的主要指数 Raw 证据。按当次实际来源核原生或合成链。 | 找 90 分钟 Silver 目标版本，并对上其覆盖 Check 与实际输入。发布记录只有名单范围指纹时，继续找正式交付凭证。 |
| 主要指数 120 分钟行情 Silver<br>`silver_major_index_mins_120m` | 优先复用已接入的主要指数 Raw 证据。按当次实际来源核原生或合成链。 | 找 120 分钟 Silver 目标版本，并对上其覆盖 Check 与实际输入。发布记录只有名单范围指纹时，继续找正式交付凭证。 |
| 主要指数 1 分钟行情 Gold<br>`gold_major_index_mins_1m` | 按现行输入合同用 1 分钟主要指数行情 Silver。 | 找 1 分钟 Gold 目标与实际 1 分钟 Silver 版本，复用现有按名单及固定时点验键的结果。 |
| 主要指数 5 分钟行情 Gold<br>`gold_major_index_mins_5m` | 按现行输入合同用 1 分钟主要指数行情 Silver。 | 找 5 分钟 Gold 目标与实际 1 分钟 Silver 版本，复用现有按名单及固定时点验键的结果。 |
| 主要指数 15 分钟行情 Gold<br>`gold_major_index_mins_15m` | 按现行输入合同用 5 分钟主要指数行情 Silver。 | 找 15 分钟 Gold 目标与实际 5 分钟 Silver 版本，复用现有按名单及固定时点验键的结果。 |
| 主要指数 30 分钟行情 Gold<br>`gold_major_index_mins_30m` | 按现行输入合同用 5 分钟主要指数行情 Silver。 | 找 30 分钟 Gold 目标与实际 5 分钟 Silver 版本，复用现有按名单及固定时点验键的结果。 |
| 主要指数 60 分钟行情 Gold<br>`gold_major_index_mins_60m` | 按现行输入合同用 30 分钟主要指数行情 Silver。 | 找 60 分钟 Gold 目标与实际 30 分钟 Silver 版本，复用现有按名单及固定时点验键的结果。 |
| 主要指数 90 分钟行情 Gold<br>`gold_major_index_mins_90m` | 按现行输入合同用 30 分钟主要指数行情 Silver。 | 找 90 分钟 Gold 目标与实际 30 分钟 Silver 版本，复用现有按名单及固定时点验键的结果。 |
| 主要指数 120 分钟行情 Gold<br>`gold_major_index_mins_120m` | 按现行输入合同用 60 分钟主要指数行情 Silver。 | 找 120 分钟 Gold 目标与实际 60 分钟 Silver 版本，复用现有按名单及固定时点验键的结果。 |
| 主要指数 5 分钟九转 Gold<br>`gold_major_index_mins_nineturn_5m` | 取同频 5 分钟主要指数行情 Gold 的可复用结论。 | 找 5 分钟九转目标发布版本。对上已有源指纹和同版行情后，复用原有源键覆盖。 |
| 主要指数 15 分钟九转 Gold<br>`gold_major_index_mins_nineturn_15m` | 取同频 15 分钟主要指数行情 Gold 的可复用结论。 | 找 15 分钟九转目标发布版本。对上已有源指纹和同版行情后，复用原有源键覆盖。 |
| 主要指数 30 分钟九转 Gold<br>`gold_major_index_mins_nineturn_30m` | 取同频 30 分钟主要指数行情 Gold 的可复用结论。 | 找 30 分钟九转目标发布版本。对上已有源指纹和同版行情后，复用原有源键覆盖。 |
| 主要指数 60 分钟九转 Gold<br>`gold_major_index_mins_nineturn_60m` | 取同频 60 分钟主要指数行情 Gold 的可复用结论。 | 找 60 分钟九转目标发布版本。对上已有源指纹和同版行情后，复用原有源键覆盖。 |
| 主要指数 90 分钟九转 Gold<br>`gold_major_index_mins_nineturn_90m` | 取同频 90 分钟主要指数行情 Gold 的可复用结论。 | 找 90 分钟九转目标发布版本。对上已有源指纹和同版行情后，复用原有源键覆盖。 |
| 主要指数 120 分钟九转 Gold<br>`gold_major_index_mins_nineturn_120m` | 取同频 120 分钟主要指数行情 Gold 的可复用结论。 | 找 120 分钟九转目标发布版本。对上已有源指纹和同版行情后，复用原有源键覆盖。 |
| 主要指数 1 分钟技术指标 Gold<br>`gold_major_index_mins_technical_1m` | 依赖实际用到的主要指数 1 分钟 Gold 行情。 | 找 1 分钟指标目标及同频实际输入的版本。绑定现有源键覆盖及预热 Check，按其日内范围判。 |
| 主要指数 5 分钟技术指标 Gold<br>`gold_major_index_mins_technical_5m` | 依赖实际用到的主要指数 5 分钟 Gold 行情。 | 找 5 分钟指标目标及同频实际输入的版本。绑定现有源键覆盖及预热 Check，按其日内范围判。 |
| 主要指数 15 分钟技术指标 Gold<br>`gold_major_index_mins_technical_15m` | 依赖实际用到的主要指数 15 分钟 Gold 行情。 | 找 15 分钟指标目标及同频实际输入的版本。绑定现有源键覆盖及预热 Check，按其日内范围判。 |
| 主要指数 30 分钟技术指标 Gold<br>`gold_major_index_mins_technical_30m` | 依赖实际用到的主要指数 30 分钟 Gold 行情。 | 找 30 分钟指标目标及同频实际输入的版本。绑定现有源键覆盖及预热 Check，按其日内范围判。 |
| 主要指数 60 分钟技术指标 Gold<br>`gold_major_index_mins_technical_60m` | 依赖实际用到的主要指数 60 分钟 Gold 行情。 | 找 60 分钟指标目标及同频实际输入的版本。绑定现有源键覆盖及预热 Check，按其日内范围判。 |
| 主要指数 90 分钟技术指标 Gold<br>`gold_major_index_mins_technical_90m` | 依赖实际用到的主要指数 90 分钟 Gold 行情。 | 找 90 分钟指标目标及同频实际输入的版本。绑定现有源键覆盖及预热 Check，按其日内范围判。 |
| 主要指数 120 分钟技术指标 Gold<br>`gold_major_index_mins_technical_120m` | 依赖实际用到的主要指数 120 分钟 Gold 行情。 | 找 120 分钟指标目标及同频实际输入的版本。绑定现有源键覆盖及预热 Check，按其日内范围判。 |
| 主要指数 1 分钟技术指标状态 Gold<br>`gold_major_index_mins_technical_state_1m` | 依赖实际用到的主要指数 1 分钟 Gold 行情及适用前序状态。 | 找 1 分钟状态目标和当日及适用前序输入的版本。复用原状态代码和最后时点 Check。 |
| 主要指数 5 分钟技术指标状态 Gold<br>`gold_major_index_mins_technical_state_5m` | 依赖实际用到的主要指数 5 分钟 Gold 行情及适用前序状态。 | 找 5 分钟状态目标和当日及适用前序输入的版本。复用原状态代码和最后时点 Check。 |
| 主要指数 15 分钟技术指标状态 Gold<br>`gold_major_index_mins_technical_state_15m` | 依赖实际用到的主要指数 15 分钟 Gold 行情及适用前序状态。 | 找 15 分钟状态目标和当日及适用前序输入的版本。复用原状态代码和最后时点 Check。 |
| 主要指数 30 分钟技术指标状态 Gold<br>`gold_major_index_mins_technical_state_30m` | 依赖实际用到的主要指数 30 分钟 Gold 行情及适用前序状态。 | 找 30 分钟状态目标和当日及适用前序输入的版本。复用原状态代码和最后时点 Check。 |
| 主要指数 60 分钟技术指标状态 Gold<br>`gold_major_index_mins_technical_state_60m` | 依赖实际用到的主要指数 60 分钟 Gold 行情及适用前序状态。 | 找 60 分钟状态目标和当日及适用前序输入的版本。复用原状态代码和最后时点 Check。 |
| 主要指数 90 分钟技术指标状态 Gold<br>`gold_major_index_mins_technical_state_90m` | 依赖实际用到的主要指数 90 分钟 Gold 行情及适用前序状态。 | 找 90 分钟状态目标和当日及适用前序输入的版本。复用原状态代码和最后时点 Check。 |
| 主要指数 120 分钟技术指标状态 Gold<br>`gold_major_index_mins_technical_state_120m` | 依赖实际用到的主要指数 120 分钟 Gold 行情及适用前序状态。 | 找 120 分钟状态目标和当日及适用前序输入的版本。复用原状态代码和最后时点 Check。 |

当前代码记载了股票前复权分钟行情、九转和 MACD/KDJ 生产时的逐文件提升凭证。股票分钟前复权 Gold 的日报按 §5.1 复用同日成功交付，逐文件凭证仍供原生产恢复使用。以下取证要求适用于依赖逐键证据的九转和 MACD/KDJ。优先查对应运行是否还保留这些记录，确认记录指向正式目标、发布完成、包含该日及频度并能对应 Check。凭证是否还在，以及是否足以绑定当次输入，留待获准后对所选日核实。 [前复权分钟发布凭证](../../orchestrator/src/orchestrator/defs/io/stk_mins_qfq_publication.py#L73) · [Gold 行情实际输入频度](../../orchestrator/src/orchestrator/defs/run_contracts/cn_a_derived_minute_bars.py#L11)

### 14.4 同花顺个股资金流向交付复核（2 项）

单独用 **2026-11-19** 验这两项的交付和同版证据。11 月 20 日仍是第 13 节全量盘点的业务日。运营已说明 11 月 20 日源端缺码较多，未达到提交更新任务的条件。 [现有同花顺个股资金流向流程](../../orchestrator/src/orchestrator/defs/sensors/moneyflow_ths_sensor.py)

11 月 22 日 17:20（上海时间）只读复核。11 月 19 日的 Raw、Silver 都在 11 月 21 日正式补交，分别是 10:26:34、10:27:12。两层各 5,218 行，对应正式文件的 SHA-256 与 DG 发布记录相符。两条 Check 均通过，分别绑定物化 `8296396` 和 `8296424`。Silver 记录的 Raw 输入指纹与本次核对的 Raw 一致。 [现有交付与文件指纹核验](../../orchestrator/src/orchestrator/defs/asset_guards/moneyflow_delivery_readiness.py#L56)

| 数据集与资产键 | 11 月 19 日复核结论 | 后续要补的证据 |
|---|---|---|
| 同花顺个股资金流向 Raw<br>`raw_tushare_moneyflow_ths` | 已更新。该次生产记录的最终缺码列表为空。正式发布和源端凭证均未保存可读回的当批沪深应有名单版本，齐备仍待确认。 | 先查能否找到此次实际使用的冻结名单凭证。以后可在现有发布过程中保存实际名单指纹及其依据，和最终缺码结果、正式文件版本一起复用。 |
| 同花顺个股资金流向 Silver<br>`silver_moneyflow_ths` | 已更新。标准化 Check 证明与同版 Raw 一致，齐备仍待确认。 | Raw 覆盖证据齐全后即可结合该版标准化 Check 判定。 |

五项上游复用继续按现有阶段排期。其余项先按上表找证据，包括同花顺个股资金流向 11 月 19 日的当批应有名单凭证。查实仍需补充生产记录的，再逐组评审具体字段与开销。历史日期能确认多少，以实际读回的证据为准。
