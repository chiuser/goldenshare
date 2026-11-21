# 财势乾坤本地 DG 每日数据审计 LLD v1

状态为设计待评审。业务依据为[每日数据审计方案](dagster-daily-data-audit-wealth-data-center-plan-v1.md)和[逐资产规则](dagster-daily-data-audit-rules-review-v1.md)。本文中的新增文件、字段与接口是实现约定。现有代码用链接标出。

## 1. 目标与交付顺序

让财势乾坤和下游程序读取本机 DG 的同一份结论。每天按资产分别判断是否按要求更新、是否有证据证明齐备。先用正常交易日跑通「产出和 Check → DG 每日总结 → 本地页面和下游查询」，再接入已列明的生产 Check、东方财富板块分类核查、通用指数分钟线独立审计。

| 交付阶段 | 代码落点 | 阶段完成条件 |
|---|---|---|
| 每日总结与读取 | DG 证据读取、规则和汇总 job。本地 Web 路由、数据中心卡片和列表。 | 现有当日检查可复用，两列状态和日期切换正确，下游按同一版本取结论。 |
| 生产 Check | 第 5 节列明的现有生产者、检查和 readiness。 | 同日同版、晚到和真实缺口判定通过，已有生产门禁继续有效，代表性样本的增量有据可验。 |
| 东方财富板块分类 | 第 6 节的分类比较、标准集与源端复核，并接入已设计的页面动线。 | 名单相同可留档，真实增减可确认，源端证实漏采时拒绝确认，补齐后可继续。 |
| 通用指数分钟独立审计 | 第 7 节的本地独立 job 和操作接口。 | 单日预览、执行、复用、取消和换版验收通过后，按确认过的范围开放。自动提交需单独确认。 |

资产盘点从本机 DG 目录取值。当前基线共 187 个资产键，129 项优先复用、34 项在生产补证据、12 项走独立审计或待开放、12 项一期齐备不适用。实际实现与测试以目录键和两份方案的逐项映射为准。运行边界是本机正式 Lake `/Volumes/datasource/data_lake/{raw,silver,gold}`、本机 DG 事件和本机交付。Prod 发布目标与环境健康保留范围说明。国际指数日线两层分别列为一期不适用。审计记录写在 DG，业务文件及发布仍由原入口负责。

## 2. 编码入口和读写边界

| 位置 | 现有入口与拟新增实现 |
|---|---|
| DG 注册 | [definitions.py](../../orchestrator/src/orchestrator/definitions.py) 自动加载 `defs`。新增 `defs/daily_data_audit/`，`registry.py` 挂接资产规则，`evidence.py` 读取有界记录和核对身份，`summary.py` 生成状态及发布模型，`jobs.py` 注册汇总和阶段内的任务。板块与独立核验分别放在该目录下的 `dc_index_review.py`、`index_minute_audit.py`。公共业务入口使用下述 job 与结果模型。 |
| DG 调度 | 汇总 schedule 固定使用 `Asia/Shanghai`。生产补 Check 使用各生产链现有选择及依赖就绪机制。独立审计由正式队列启动单独 run，轮询和网页版接口不直接执行检查函数。正式实例当前为 `QueuedRunCoordinator`、`max_concurrent_runs=1`，本文复用该队列，验收时再次核对。 |
| 本地 Web | 在 `src/app/runtime/data_audit.py` 组装本地审计服务与路由，由 [web/app.py](../../../src/app/web/app.py) 条件挂载。沿用 [DataCenterError 处理](../../../src/app/runtime/announcement_archive_lifespan.py)、[数据中心 modules](../../../src/biz/api/wealth/data_center/home.py) 和 [Web 鉴权](../../../src/app/auth/dependencies.py)。`src/biz/api/wealth/data_center/data_audit.py` 管请求与响应，`src/biz/services/wealth/data_center/data_audit.py` 管读取和操作。Web 与 DG 通过现有本地 GraphQL 连接，DG 业务模块仍在自己的运行环境。 |
| 财势乾坤 | [DataCenterPage.tsx](../../../wealth/src/pages/data-center/DataCenterPage.tsx) 接受 modules 返回的卡片。[WealthRouter.tsx](../../../wealth/src/app/routes/WealthRouter.tsx) 注册 `/wealth/data-center/data-audit`，沿用现有 [请求封装](../../../wealth/src/features/data-center/api/dataCenterApi.ts)。新增 `wealth/src/pages/data-center/DataAuditPage.tsx` 及板块核查弹窗，按已评审的 Figma 动线复用现有数据中心组件和样式。 |
| 下游程序 | 本机 DG 内由 `evidence.py` 提供 `get_completeness(scope)`。本机进程外可读同一个资产详情接口，并提供自己实际读取的范围和版本来比对返回值。依赖方仅在范围及全部版本相符、状态为已确认齐备时继承其范围。 |

仿照现有 `announcements_enabled(settings)` 的部署判定，显式 `APP_ENV=dev/local` 与默认关闭的 `WEALTH_LOCAL_DATA_AUDIT_ENABLED` 同时成立才开放。由同一判定控制 modules、Web 的 SPA 直达地址与 API 挂载。DG GraphQL 连接使用已确认的本机回环地址和固定 `/graphql`，禁止从请求接收地址、任意查询、job 名或文件路径。Prod 不挂路由，直达页面返回 404，即使环境误传功能开关也不开放。已启用而 DG 连不上时入口仍可见。读接口使用 `get_current_user`，启动、取消、源端复核及人工确认使用现有 `require_admin`。DG 内重查目标、版本和范围。前端的可操作标志只决定显示与交互。

## 3. 资产规则、证据与状态

### 3.1 资产和日期

`registry.py` 遍历 [list_lake_asset_catalog_entries](../../orchestrator/src/orchestrator/defs/catalog/lake_assets.py#L4166)，从目录取 `asset_key/dataset_id/dataset_name/layer/partition_model/blocking_check_names`，频度从已注册的频度和资产合同取。以资产键关联 `due_rule`、`delivery_resolver`、`evidence_resolver` 和 `audit_mode`。相同合同的一组频度共用规则实现。优先调用该资产已有的业务日期、交付和版本证据解析。按[方案表 §4.1–4.4](dagster-daily-data-audit-wealth-data-center-plan-v1.md#4-csv-复核及按当天数据量分流)分流，使用[逐资产 §3、§5](dagster-daily-data-audit-rules-review-v1.md#3-原方案-73-项逐资产待评审规则)落实具体资产键、附加检查、所用日期和有效范围。目录的阻断检查名单不能代替齐备规则，ETF 非阻断覆盖检查须显式读取。目录差集测试要求一键一行、只有一种归属、无遗留规则指向未登记键。未知规则或缺证据的资产仍显示，并保留待确认原因。

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

- `daily_data_audit_summary_job` 输入 `business_date`，受影响行重算时另传 `changed_asset_keys`，运行开始记录 `observed_at`。由本地 DG schedule 在上海时间每日 00:00 对上一自然日提交一轮，日期取调度计划时点减一天。每个资产再按合同确定该日是否适用。停机时保留未生成。由获准的操作按单日补读已有记录，`generated_at` 是实际写记录时间。该次无法重建当时状态的项标未核实。
- `evidence.py` 将 `(资产键, 分区或无分区, 规定检查名, 所选日/截至日)` 构造为请求集合。DG 使用现有 SQL event storage，参考 [股票周月批量证据](../../orchestrator/src/orchestrator/defs/asset_guards/stock_period_silver_readiness.py#L46) 和 [完成 Check 查询](../../orchestrator/src/orchestrator/defs/asset_guards/stock_period_check_evidence.py#L25)。按实需选择有索引约束的分区组和无分区快照组。只纳入观察时点已存在的证据。先找到适用交付范围内的候选物化，再取已结束 Check 并核关联。快照/同物理分区的日交付必须匹配已有交付记录中的实际日期。依赖范围另由规则解析。每批出错只影响涉及行。只有证据足以确认没有交付才判未更新，事件读取失败时留无法确认。页面读接口不遍历各资产事件。
- 结果使用现有 Dagster run/event 承载。各 job 在最终步骤用 `add_output_metadata` 保存 `MetadataValue.json`，步骤输出 `Nothing`。汇总标签 `data_audit_summary` 含 `schema_version=1`、`business_date`、`observed_at`、`generated_at`、`rows[]`，带出每行的证据及观察时间。独立核验、标准集、源端复核分别用 `data_audit_result`、`dc_index_standard`、`dc_index_recheck`，包含范围、版本及该任务结果。查询按固定 job、`audit/business_date` 标签和必要范围标签筛 run，再按 run ID 读取命名元数据。仅 SUCCESS 且完整解码、与标签和输入版本吻合的记录可消费。独立核验任务失败、取消或中断只显示运行结果，没有成功输出时无可复用结论。标签表示定位范围，原生运行和事件 ID 用于定位与顺序。发布契约为原生记录，验收须证实可通过此路径读回及保留。若实际清理策略或元数据承载不能保存所需记录，先报告具体缺失与影响，另行评审存储。
- 迟到交付、Check 完成、版本更换和补审结果由本机 DG 的汇总刷新传感器读取有界的相关记录变动。该传感器只提交总结更新。先等该日已有总结，按变更影响的资产及依赖关系重算相应行，其余行沿用各自原观察时间，并追加同日新总结。旧总结保留。相同观察时点的结果按已完成 run 顺序选最近者，始终展示 `generated_at`。旧版记录按其观察时点展示。新输入未核验时不可读取旧记录为新版绿灯。
- 使用现有本机 Dagster GraphQL 形态。读使用 `runsOrError(filter: RunsFilter, limit: ...)`，过滤字段 `pipelineName/tags/statuses`，再用 `logsForRun(runId, afterCursor, limit)` 的 `EventConnection` 取指定 `ExecutionStepOutputEvent` 下的 `JsonMetadataEntry`。使用 `launchRun`、`terminateRun` 处理允许的明确操作，均以当前安装 schema 为准。只针对指定日、固定 job 和选中 run 做有界读取。专用 job 保证只输出固定数量的步骤及结果。schema 不匹配或分页未读到完整结果时显示不可读，不搜索其他日期。队列与调度语义见 [Dagster schedules](https://docs.dagster.io/guides/automate/schedules) 和 [Dagster sensors](https://docs.dagster.io/guides/automate/sensors)，本机连接依据[本地运行手册](../architecture/dagster-local-operations-cheatsheet.md)。

## 4. 本地 API 和页面

路径统一在 `/api/v1/wealth/data-center/data-audit` 下。请求固定业务日期、已有目录中的资产键或明确选择的审计 run ID。源端和独立任务的参数由 DG 从请求范围解析。

| 方法与路径 | 请求、结果与错误 |
|---|---|
| `GET /days/{date}` | 返回 `state`（`ready`、`not_generated`、`unavailable`）、`business_date`、`observed_at`、`generated_at`、`summary`（四项数量）、`rows`（主行及可显示子项的状态和简要原因）、`can_operate`。仅请求所选日最近有效总结。有已经读到的同日结果且连接中断时保留其时间并标不可用。 |
| `GET /days/{date}/assets/{asset_key}` | 读取同一个总结或所选日指定 `summary_run_id` 的该资产详情。返回第 3.2 节结果及来源链接。明确提供所用输入版本，客户端可以验证本次读取和既有结论是否一致。 |
| `GET /days/{date}/assets/{asset_key}/board-standard` | 仅分类资产。返回适用参照版本及代码、当日有效代码与增减、当日标准集（若已生成）、逐项 Tushare 结果、`review_version` 和可确认状态。 |
| `POST /days/{date}/assets/{asset_key}/board-recheck` | 输入 `review_version`。失败项重试时加 `retry_run_id`。提交对当前差异的源端复核，返回 `run_id/status`。服务端从版本记录推导代码差集。 |
| `POST /days/{date}/assets/{asset_key}/board-confirm` | 输入 `review_version`。按该版人工确认差异并保存标准。当日有效源名单证实本地缺码或参照变更时拒绝。返回 `run_id/status`。 |
| `GET /days/{date}/assets/{asset_key}/audit-preview` | 只对已开放独立规则的键返回 `scope`、`version`、预计文件/键列/行数/字节、可否提交及当前原因，频度由资产键确定。Web 读取 DG 已保存的身份、行数或页脚估算。读取量未知时返回 `null`，不给执行许可。 |
| `POST /days/{date}/assets/{asset_key}/audit-runs` | 输入预览的 `scope/version`。同范围重试带原 `retry_run_id`。在途或已有有效同身份任务返回原 run，允许执行时返回新 `run_id/status`。 |
| `GET /runs/{run_id}`、`POST /runs/{run_id}/cancel` | 仅识别本模块已定义的 job 及其所属范围。GET 返回任务状态、选中范围、开始/结束时间、结果或失败原因。仅独立审计的允许状态可取消，概念复核按约定等终态或超时。 |

`POST` 成功受理返回 202，已有有效结果或重复请求返回已有身份。版本变更、规则未开通、预算不明、该日依赖缺失或标准集不可保存用 409 与具体 `code/message`，非法范围/日期用 422，未知资产/任务或被禁用的模块用 404，操作权限不足走已有 403。DG 连接失败返回不可用状态（查询）或明确 503（提交）。错误和 UI 内容不透传内部连接信息。日期与列表读取沿用已有数据中心请求层。运行状态分别映射为排队（未启动或已排队）、运行中（启动中、已开始或取消中）、完成（成功）、失败、取消。源端复核还展示每个请求项的结果。

页面保留 `selectedDate`、`updateFilter`、`completenessFilter`、`page`。日期选择重新读取所选日，切换时舍弃晚回的旧请求。明细在该日结果内按两列筛选，组合后显示匹配数。点击任一齐备数字时保留日期、设对应齐备筛选、重置更新筛选为「全部」、页码为 1、定位明细标题。汇总一直显示当日主行数。东方财富概念板块行使用完整名称，与其它行左对齐，继承对应分类资产的层与频度。附属行只在相符筛选且其父资产已进入结果时展示，详情仍可见所属各类别。明细的状态原因和详情的范围、例外、样例均读接口，空字段显示「未记录」。详情链接使用固定本地 DG 地址。缺本日记录显示「未生成」，本地 DG 不可用时可继续注明已读到的同日总结时间。

## 5. 生产 Check 的实现清单

覆盖结果保存为现有 Check 的有结构元数据。每个结果带 `scope/version`、实际运行的规则、覆盖计数及身份引用。上游未就绪、参照未确认或身份无法对应时，登记新增规则待确认。原 Check 继续判定其原有门禁。依赖就绪后使用对应生产调度提交只选中 Check 的当日工作，不重跑已经完成的生产。用于补查的 run 必须确认当前正式版本仍与请求一致，否则使用该日新版本重新判定。已批准阻断的对账在现有门禁内失败，其他 Check 沿用原级别和失败行为。

先用生产调度已有的依赖检查。如果目标尚未产出，依赖成功后走原生产 job，检查随该次产出执行。如果目标已产出、相应覆盖字段为待确认，则由该资产生产传感器在既有业务日期窗口比较当天目标版本、最新依赖证据和已有覆盖结论。依赖可用时提交当天、该资产的检查选择，沿用 [gold_stock_daily_qfq_check_refresh_job](../../orchestrator/src/orchestrator/defs/jobs/stock_daily_qfq_update.py#L17) 的仅选 Check 模式，运行参数显式给分区和目标版本。资金流依赖的接线使用 [moneyflow_update_selection.py](../../orchestrator/src/orchestrator/defs/sensors/moneyflow_update_selection.py)，分类及参照依赖使用 [dc_board_silver_sensor.py](../../orchestrator/src/orchestrator/defs/sensors/dc_board_silver_sensor.py) 的生产就绪检查与分类 Check 完成记录。相同目标、输入、规则已有完成覆盖结果或已排队就跳过。指标和年文件的检查只接受已有生产统计或原有单日读取。页面不会提交补查。

### 5.1 复用现有 Check 或交付

`evidence_resolver` 按[方案 §4.1 全部 129 项](dagster-daily-data-audit-wealth-data-center-plan-v1.md#41-优先用现有-check-或发布证据129-个)和[逐资产 §5.1](dagster-daily-data-audit-rules-review-v1.md#51-原-105-项复用候选)读取检查字段。各组证据的适用范围如下。

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

### 5.2 生产时补证据的 34 项

| 资产键或频度组 | 改动点、应有集合、结果 |
|---|---|
| `gold_stock_daily_qfq` | [gold_stock_daily_qfq_contract_check](../../orchestrator/src/orchestrator/defs/checks/stock_daily_qfq_checks.py#L59)，同日 Gold 和该次使用的股票日线 Silver 的 `ts_code` 双向差集。保留已有复权因子门禁。确认缺/多则本 Check 阻断受影响后续生产，只有新增证据欠缺则待确认。最多两个当日文件的键列，目标列沿用原读取。 |
| `ch_dc_daily_technical` | [ch_dc_daily_technical_core_check](../../orchestrator/src/orchestrator/defs/checks/dc_daily_technical_serving_checks.py#L141) 对当前查询已读回的同日 Gold 和本机 ClickHouse 的 `(ts_code, trade_date, category)` 双向差集。数量相同且一缺一多仍失败，沿用原阻断。缺新增证据只记待确认。零新增查询。 |
| `silver_index_weekly`、`silver_index_monthly` | 在 [index_period_writer.py](../../orchestrator/src/orchestrator/defs/io/index_period_writer.py#L461) 调用 [index_period_checks.py](../../orchestrator/src/orchestrator/defs/checks/index_period_checks.py#L93) 的现有当期校验路径。日更和当日补跑以配置业务日期 (D) 为准。正式提升前从已生成的当期增量用 `list_date <= D` 的固定名单核代码集合、逐代码唯一与逐行 `trade_date = D`。未上市不算应有。用同一 Check 及物化消费覆盖与实际截至日，保留原阻断。当前代码已有 `active`、`as_of`、日线就绪与当期行数证据，仍须补逐代码截至日证据，不能以 sensor 就绪代替。周线 Raw 期末，月线 Raw 次月首个交易日核上月期末。固定 11 名单允许北证 50 Raw 空，复用现有同版检查，不推广到已上市的 Silver。 |
| `silver_index_basic` | [index_basic_checks.py](../../orchestrator/src/orchestrator/defs/checks/index_basic_checks.py) 复用发布前的同次源与候选对账和目前的生命周期 Check，核候选实际保留指数、终止日期和适用交易日。更新 job/sensor 由现有指数基础信息方案管理，本任务消费结果。 |
| `silver_stock_basic`、`silver_namechange`、`silver_stock_identity_map`、`silver_stock_lifecycle` | 分别在 [stock_basic_checks.py](../../orchestrator/src/orchestrator/defs/checks/stock_basic_checks.py)、[namechange_checks.py](../../orchestrator/src/orchestrator/defs/checks/namechange_checks.py)、[stock_identity_map_checks.py](../../orchestrator/src/orchestrator/defs/checks/stock_identity_map_checks.py)、[stock_lifecycle_checks.py](../../orchestrator/src/orchestrator/defs/checks/stock_lifecycle_checks.py)。期望分别是当前上市人民币股 `ts_code`，同次曾用名有效事件与合法开区间，源代码自映射与获准历史映射的有效边界，生命周期 `ts_code/上市日/退市日/状态`。用生产已算的投影和 Check 现有键/关键字段做双向差异，附该版输入。一个有效快照复用一次结果。上游范围待确认时只证明同版转换。 |
| `raw_tushare_moneyflow`、`raw_tushare_moneyflow_dc` | 复用 [moneyflow_daily.py](../../orchestrator/src/orchestrator/defs/checks/moneyflow_daily.py#L38) 的当日键列。普通个股取有效生命周期中的沪深京上市 A 股，含上市首日及全天停牌。东方财富个股以已核验当日股票日线取上市且有成交的沪深京 A 股，全天停牌和 B 股不计入应有名单。只核约定范围的缺码。日线晚到只执行该日覆盖 Check。 |
| `raw_tushare_moneyflow_cnt_ths`、`raw_tushare_moneyflow_ind_ths`、`raw_tushare_moneyflow_ind_dc` | 概念在 [moneyflow_daily.py](../../orchestrator/src/orchestrator/defs/checks/moneyflow_daily.py) 取已确认的 386 项基础名单，变动按代码列出并待人工确认后更新名录。另 4 个长期未发布的候选仍是待核事项。行业在 [moneyflow_ind_ths.py](../../orchestrator/src/orchestrator/defs/checks/moneyflow_ind_ths.py) 对 90 个已批准 `881` 行业名单逐码核对，后续采用确认生效的版本。东方财富板块资金流向按当日生效标准集分行业、概念、地域核板块代码，名称差异仅展示。缺当日概念标准时该项待确认，标准集生效后只检查当天。 |
| `raw_tushare_stk_nineturn` | [raw_tushare_stk_nineturn_content_integrity_check](../../orchestrator/src/orchestrator/defs/checks/stk_nineturn_checks.py#L198)，同日已核验股票日线代码减去 `freq=daily` 的九转代码。全天停牌无日线不算缺，盘中停牌但有日线应有记录，空信号也算交付。优先取现行检查已读的列，发布证据绑定日线和九转。 |
| `raw_stk_mins_{1,5,15,30,60}m` | [stk_mins_checks.py](../../orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py#L3070) 的现有同频 Raw Check，复用生产者同日有效名单、最终全日停牌事实与当次统计。应有集合和实有统计都剔除全天停牌代码，截止 15:00 计数，临时停牌按完整根数，零成交行计入。比较代码集合和汇总根数（每个应有股票分别 241、49、17、9、5 根）。保留原始交付和原写前覆盖。盘后采用当批交付结果独立记录，不能冲抵常规缺根。 |
| `silver_stk_mins_{1,5,15,30,60}m` | [stk_mins_checks.py](../../orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py#L2786) 当日引用覆盖读取中，先等同频 Raw、需要时同日 1m Raw、日线和应有停牌及映射证据。按正式 Silver 的标准化、去重、全天停牌与盘后剔除、允许的历史冻结及粗频合成核代码与总行数。粗频只有该股同频当日记录过滤后全空，且 1m 整日有效时做整日合成。Silver 全天停牌和盘后为零根。参考 [现行分钟转换](../../orchestrator/src/orchestrator/defs/assets/stk_mins.py#L1684)。 |
| `gold_stk_mins_qfq_macd_kdj_state_{1,5,15,30,60,90,120}m` | 接 [现有状态 Check](../../orchestrator/src/orchestrator/defs/checks/stk_mins_qfq_macd_kdj_checks.py#L417)。以实际前序有效状态应承接股票 ∪ 当天有指标股票为代码集，核每只一行、总数匹配。全天停牌沿用前序状态。首次初始化或历史修复取该次获准范围。复用生产已有前序与当日统计。 |
| `raw_tushare_dc_index`、`silver_dc_index` | 接 [Raw 分类 Check](../../orchestrator/src/orchestrator/defs/checks/dc_board_checks.py#L269) 和 [Silver 分类 Check](../../orchestrator/src/orchestrator/defs/checks/dc_board_silver_checks.py#L262)。行业、地域、概念分别按第 6 节核对。Silver 另核按同版 Raw 正式转换后的代码关系。 |

股票分钟前复权 Gold、分钟前复权九转及 MACD/KDJ 指标七频是第 5.1 节的复用路径。取得实际同频输出所用的上游 Check 后，结合本层原有计算检查，用已读的日内代码和根数确认覆盖。一个前复权 K 线对应一行指标。频度依赖按 [前复权输入合同](../../orchestrator/src/orchestrator/defs/run_contracts/cn_a_derived_minute_bars.py) 和生产实际来源，不能将输出 15m、120m 误当读相同频度的 Silver。指标缺少代码统计时在其现有读取中补齐。比如 10 只状态已存在，一只全天停牌，其他九只各 5 根 60m，指标 45 行，递推状态 10 行。已有原 Check 的质控仍依各自合同。

## 6. 东方财富板块分类与人工核查

### 6.1 当日对账与标准集

初始记录使用 2026-11-19 已确认的本地分类名单，行业 496、地域 31、概念 554。以该日有效名单作为内容，记录两层正式产出版本及确认依据，从下一交易日开始对照。行业、地域各用生效的人工确认名单，核同类别有效代码差集。确属正常变动时经确认形成新版本。分类占位与 Silver 拒绝规则以 [Raw 分类合同](../../orchestrator/src/orchestrator/defs/run_contracts/dc_board.py#L234) 和 [Silver 生产转换](../../orchestrator/src/orchestrator/defs/assets/dc_board_silver.py#L143) 为准。

概念按所选交易日的上一交易日查找确认版本。不存在时记「参照标准集缺失」，当前日齐备待确认，不能从更早的版本跳日生成。存在时，对比当日有效代码与参照。无增减时保存当日副本，有增减时记录代码、名称及存在性，待人工确认。分类父状态按第 3.3 节折叠。Raw、Silver 各核证据，同一交易日共同的概念标准集仅保存一个有效版本，记录两层正式交付关系，Silver 仍须证明同版转换。缺上一日时从缺失日恢复。已保存记录保留版本及生成时点。

在 `dc_index_review.py` 解析 `review_version` 为业务日、所选分类资产、当日正式产出的发布身份、原参照版本与差集。它只定位具体核查对象。候选名单只来自同版 Check 的代码投影，已有 Check 不具备保存字段时随生产检查写入相应版本的代码清单。使用 `daily_data_audit_board_confirm_job` 保存标准集。生产调度在同版分类检查确认完全匹配时提交保存副本，出现增减时由运营提交确认。同一函数校验当前目标和参照，并输出第 3.4 节标准集元数据。Silver 使用标准集时还核其自身和实际 Raw 的关联。公开读取以当前同版有效记录为准，上一日的原版本仍可追溯。

### 6.2 Tushare 复核与保存

1. 「核查 Tushare」提交 `daily_data_audit_board_recheck_job`。固定业务日、差异版本，服务端重算新增与减少的代码差集。请求仅限该集合。`dc_index(trade_date=YYYYMMDD, ts_code=code)` 复查分类，必要字段为业务日、板块代码、名称和类别。`dc_member(trade_date=YYYYMMDD, ts_code=code)` 独立核同日成分，结果按板块列出。参考当前 [分类参数](../../../src/foundation/ingestion/request_builders.py#L696)、[成分参数](../../../src/foundation/ingestion/request_builders.py#L962) 和 [DG 板块合同](../../orchestrator/src/orchestrator/defs/run_contracts/dc_board.py)。在 DG 的 [TushareDownloader](../../orchestrator/src/orchestrator/tushare_download/download_api.py) 挂接这两个已有接口的 `BY_OBJECT_POINT` 只读请求规则，沿用当前页大小、合法空响应和返回键校验。参照[指数单对象单日下载](../../orchestrator/src/orchestrator/tushare_download/contracts/index_weekly.py#L46)的调用形态。复核只读取会话响应，无 Prod 对账及文件提升步骤。
2. 点击后显示加载圈、核查范围及「正在核查 Tushare」。以任务终态或本次复核超时解除锁定。期间禁重复请求、查看参照、确认、取消、关闭、Esc 和遮罩关闭。页面只查询结果状态。超时后可重试失败项。提交时拒绝在途重复，防止重新打开时重复打源。
3. 按代码分别保存分类与成分的成功、未返回、失败结果及核查时间。保留原本地差异。合法成分空不等于板块消失。分类有效返回且本地当前版本缺少，记「源端有，本地缺少」和确认缺口。源端成功未返回记「源端本次未返回」，留待人工判断。只重试上次失败的代码和接口，保留同版已成功的结果。
4. 生成标准集前，前端与 DG 都检查：版本及参照仍适用、当前无源端证实的本地缺码。供独立操作的确认、自动保存、副本重试都使用相同的检查。通过则保存完整有效分类代码列表、所用目标与上一期版本、确认人和时间。首次和固定名单变更走已批准的人工确认流程。复核失败不抹掉已证实的缺口。用现有同步入口补齐后，应以新产出形成新的核查状态和版本关系。
5. 对同一业务日、同一版本重复提交时复用在途或已完成的同次操作。确认、复核与生产 Check 使用同一个正式队列。若并发提交生成两个 run，在排到执行时按操作、版本及重试来源查询更早的有效 run。存在同轮已执行的 run 就结束并引用结果，不能再次请求源或保存副本。保存前再验证当天和参照版本。资产更新与确认顺序变化时，旧候选不能写入为当前标准集。

交互顺序为「列表 → 东方财富概念板块 → 名单核查 → 查看参照或核查 Tushare → 确认并生成标准集」。发现确实漏采时，详情保留源证据和缺码，等待原同步流程补齐后重新核查。

## 7. 通用指数分钟线独立审计

执行入口为 `daily_data_audit_index_minute_job`，参数固定为一个资产键、一个业务日、该频度、范围和稳定版本。仅批准的 Raw 五频及 Silver 七频可以开放。先复用等价证明。不足再由运营选择单项预览。提交、开跑、完成前按目标及依赖版本各核一次。需要继承上游齐备结论且未取得时，不提交或不开始文件查询，详情说明等待上游或缺口。已存上游缺口可说明对 Silver 的影响，不能凭它声称已经执行 Silver 键对账。

| 目标 | 数据访问和键判定 |
|---|---|
| `raw_index_mins_{1,5,15,30,60}m` | 取此次 Prod 导入当时实际使用的 `ops.index_series_active(resource='index_mins')` 有效名单的留存版本。独立 job 读本地证据，不能到 Prod 重查激活池。已有同版代码覆盖可复用。只访问 [Raw 路径合同](../../orchestrator/src/orchestrator/defs/paths.py#L1078) 的一个日期一个频度文件，投影 `(ts_code, freq, trade_time)`。上海上午从 09:30（含）至 11:30，下午从 13:00 加一个频度至 15:00，按 (120/F + 1 + 120/F) 生成预期点。每频每代码应有 241、49、17、9、5 个键，核缺、多、重复。历史 15、30、60m 只有绑定到获准源全空证据的日期/频度才能用相应历史例外。 |
| `silver_index_mins_{1,5,15,30,60}m` | 应有对象继承本次实际同频 Raw 的批准范围。在需要补核时只读同日目标及实际来源，以正式标准化后业务键做双向差异及重复检测。已获准的历史源全空替代使用同日实际绑定的 5m Raw 和正式转换。只有键对账可证明时显示「仅与上游一致」。 |
| `silver_index_mins_90m`、`silver_index_mins_120m` | 分别使用同版 30m、60m Silver 的应有范围。复用[合成窗口合同](dagster-derived-minute-bars-90-120-contract-rebuild-low-level-design.md#22-90m-窗口)检查输入窗口和竞价锚点。按每指数输出 90m 的 11:00、14:00、15:00，120m 的 11:30、15:00 核键。最多读取对应上游及目标两个文件。 |

预览返回预算内可用的已记录文件身份、行数或页脚估算、字节和键列。正式运行前重新按当前作用域检查。队列运行必须满足批准的资源及时间窗口，已有日更重任务在占用或将无法在剩余窗口完成时跳过。中间阶段可以从固定批次边界停止。在取消、失败或版本变化时无可消费结论。手动重试仅复核同一范围和版本，沿用原资格，次数由该资产批准的预算约束。窗口外、版本不明或次数未批准不重试。结果保存实际读量、版本和差异。重新开始最多重读该次单日文件范围。替换目标或所用输入应以新身份再做预览和核验。

自动提交仍待评审。审核通过后才在已有本机 daemon 注册启用独立审计传感器，默认停止。传感器按已批准资产、日期、窗口有界读记录并调用与人工操作相同的资格判断。候选未就绪可在后来评估再次考虑。用稳定的 `scope/version` 检查在途和成功结果，`run_key` 只作该传感器防重复，日期与版本明确放 run config。避免人工与自动同时进入读取，在单 run 队列的 job 起点再次查询同身份已有结论，若已有则直接引用。窗口结束仍未有结果就保留待确认。

## 8. 性能预算与执行验收

| 步骤 | 可从合同和代码核算的工作量 | 开放前需验证 |
|---|---|---|
| DG 一次总结 | 设 `A` 为当前目录资产数，`P` 为所选业务日解析出、去重后的目标与必要参照范围数，`C` 为这些范围需要的 Check 键数。生产记录读取按范围分组批量执行，每组两类查询，分别取发布和已完成 Check。股票周月已有两次集合查询的例子。优先把匹配范围作为值表关联，禁止用资产集合与分区集合的笛卡尔乘积。输出至多 `A` 主行，另有固定、已列明的详情组件。一次完成结果只需查一个指定业务日的成功汇总 run 和该 run 的有界日志。无可用记录时不跨日查询。 | 在现有 SQL 存储对代表性的日分区、周期实际日及快照观察时点验证计划、查询次数和返回事件字节，区分 SQL 扫描量与结果条数。对无分区和复用分区先查可定位 `D` 的交付身份或已有发布记录，再按候选身份匹配 Check。没有可靠索引范围或绑定的项返回待确认，禁止降级为读明细或翻全历史。记录首跑、进程中断后的单日重读、只更新受影响行的读取和 Web 最终读回。单次记录的实际压缩前字节和 DG 存储保留条件需跟样本验收。 |
| 日更增量 | 周、月 Silver 各核最多 11 个应有指数，直接使用现有增量关系，新增文件或源请求为零。股票日线前复权 Gold 最多处理两个 `D` 文件的键，`S+G` 键记录。ClickHouse 使用已读的 `C_gold+C_ch` 条键，不追加 ClickHouse 请求。资金流、九转、板块分类取当日已有键列及适用参照。股票分钟 Raw/Silver 用原生产日内计数和代码，需计算时在已知当日文件投影中完成。状态用当次生产的前序和当日统计，快照 Check 复用当次转换工作集。 | 逐组记录新增文件数、投影、键记录数、峰值内存、正常 Check 时间、上游晚到后选中日期补查、发布后读回。分钟线参考逐资产规则的 2026-11-19 单列聚合样本约 9 毫秒。该值只测过 `ts_code` 分组，不能作为完整 Check 耗时。未证实开销可控的补项暂不进入日更，按方案复核执行方式。 |
| 通用指数分钟独立任务 | Raw 至多一个文件，Silver 至多当日目标加实际输入两个文件。键为三个字段。`N` 为当次有效指数数，Raw 每频预计键数 `N × 每指数预期时点数`，Silver 派生预期键数由同版输入窗口决定。样本 `N=530` 的 Raw 1m 是 `530 × 241 = 127730` 个预期键。若中断后批准重试，每次至多重读同样一个或两个文件，最终核版本及读回结果只查有界身份、记录和必要文件属性。 | 检查文件字节及行组、实际扫描键数、差集峰值内存、用时、终止时点、单日期重试和结果读回。确认生产队列仍串行，评审实际可用窗口、单轮名额、重试次数及余量后才配自动运行。 |
| 东方财富概念分类 Tushare 复核 | 设 `K` 为本轮差异代码数，在每个代码两个接口各一页时基础请求数为 `2K`。有分页时为 `sum(index_pages + member_pages)`，重试另计每页实际附加次数。复用 [现行东方财富请求策略](../../orchestrator/src/orchestrator/defs/asset_guards/dc_board_source_probe.py#L149) 的间隔、最多 3 次页内重试、1,200 次请求和 600 秒每轮硬上限作为外层限制，并按本次差集提前完成。页大小沿用[现行合同](../../orchestrator/src/orchestrator/defs/run_contracts/dc_board.py#L69)。只重试上一轮失败的代码与接口。某项分页未完整时重读这一项，其他已成功项沿用结果。 | 复用 DG [带限时 HTTP transport](../../orchestrator/src/orchestrator/tushare_download/http_transport.py#L202) 和[现有请求时限](../../orchestrator/src/orchestrator/tushare_download/configuration.py#L48)，每次调用的上限是 45 秒。排队及运行共用提交时生成的截止时点。达到请求数上限，或剩余时间不足当前一次调用的上限时，经下载会话已有的取消检查阻止下一页或重试。正常提前完成即解锁。验证无响应时 Web 可解锁、DG 到期无新请求、已完成项可按同版读回。记录分页、失败重试、返回的证据大小与实际用时。 |

汇总与独立读取复用现有治理的[事件、身份和读取边界](dagster-data-pipeline-performance-governance.md)。产品、生产 Check、独立审计分阶段获得本机正式执行授权。先用隔离实例和真实 schema 契约验证，再有界读回已有正式产出和 Check。可用已有验收样本包括[主要指数周月交付](dagster-daily-data-audit-rules-review-v1.md#主要指数周线和月线的检查结果复用)、[ETF 复权因子缺码和交付证据](dagster-daily-data-audit-rules-review-v1.md#复用与单日补核)及[股票分钟线保留和过滤的实例](dagster-daily-data-audit-rules-review-v1.md#31-股票原始分钟线与-silver10-项)。这些记录证明各自的历史业务口径，小范围实现验收还需证明新读取路径和目标版本绑定。

## 9. 编码测试和方案对账

以下是实施时应执行的测试及本次文档一致性审计。正反例来自方案或当前生产合同。使用独立字面数据作为业务预期。运行时验证应区分替身、隔离的真实 DG schema、正式实例有界只读及批准的正式执行。

| 方案约束 | LLD 和测试位置 | 需要通过的正反例 |
|---|---|---|
| 方案 §1–2 本地入口、日期和两列状态 | §2、§4。沿用 `DataCenterPage.test.tsx`，新增 `DataAuditPage.test.tsx`、`tests/web/test_wealth_data_audit_api.py` | 本地显式开启才有卡和读写接口。Prod 强传开关、伪造 localhost、直达路径也拿不到。登录只读、管理员操作、只读绕过按钮 POST 返回 403。DG 断开提示并标旧结果的原时间。当天未生成不借上一日。四个数字分别筛该日、更新条件回全部、明细定位回第一页，组合后按实际匹配数展示且汇总数字不变。 |
| 方案 §3.1、§5 更新 | §3.1/3.3/3.4。DG `tests/test_daily_data_audit_summary.py` | 正常交付、晚到交付、合法空公告、固定快照和非发布日。对同一「当日应更但确无交付」在 23:59:59 与次日 00:00 比较。休市或合同延期无超期，缺日历规则是无法确认。仅绿灯没交付、只登记分区、周期实际截至日落后均不可为已更新。 |
| 方案 §3.2–3.3、规则 §1.1 证据复用 | §3.2–3.4、§5。DG `tests/test_daily_data_audit_evidence.py` | 同资产、分区、频度、范围、上游、规则及目标均匹配才复用。Check 对旧物化、覆盖只跑了合同、证据读取失败、新版本没有 Check、较新失败且较旧绿灯、仅同版一致，分别验状态及原因。等待或已知上游缺口时测下游行情读取为零。换版只重算受影响的行，保留原总结时点和到达时刻，历史无法重建就写未核实。 |
| 方案 §4.1、§4.4 目录分流 | §3.1、§5.1。目录覆盖测试和 `tests/test_daily_data_audit_summary.py` | 对现有目录全部键核归类与原规则表的对应关系。国际指数日线两层各计一次不适用，六个 Prod 目标和 Lake 健康不参与本地核验，三项仅核更新。ETF 日线非阻断有缺码时允许已更新且齐备缺口。基金复权因子清算事实仅适用其对象及日期，未证实的事实不能认定为例外。 |
| 方案 §4.2、规则 §3.1、§3.3、§3.4、§5.2 生产 Check | §5.2。各现有 Check 测试及 `test_index_period_writer.py`、`test_index_period_sensors.py` | 同日 Gold/ClickHouse 同量一缺一多须阻断，缺证据只待确认。周月 Silver 只核目标交易日，原始允许空规则不延伸到 Silver，错日期、重复和未上市正反例。全天停牌 Raw 占位不能抵常规缺根，Silver 为零，盘后独立。临停完整根数。上游晚到只查当天。MACD/KDJ 验同码总数、指标 45 行和递推 10 行，缺前序、同数错代码或上游待确认时不能判绿。 |
| 规则 §3.5–3.7 资金流向、快照和日线神奇九转 | §5。扩展相应 Check 的现有测试 | 同花顺概念增减待人工、行业目录范围按 881 生效名单。东财板块资金流向代码相同改名通过、少板块报具体缺码、概念标准晚到后单日补 Check。普通资金流纳入全天停牌，东方财富个股只核有成交的上市 A 股。股票基础信息 20 条和 21 条分别判齐备、待确认。五个 Silver 快照按实际输入，变换漏写和版本错配可检出。日线神奇九转信号空合法，全天停牌无记录合法，盘中停牌有日线但缺九转报缺码。 |
| 方案 §2、§4.2、规则 §3.4 东方财富 | §6。扩展 `test_dc_board_checks.py`，新增 `tests/test_daily_data_audit_dc_index.py` 与核查弹窗测试 | 行业、地域及概念分开比较，父行优先级与统计正确。概念同名单留副本，源端正常变更可确认，上交易日缺标准时报参照缺失。Tushare 只请求差异限定，正常空、失败及超时分开，锁定含 Esc 与遮罩。源端证明本地漏采时前后端拒绝生成。补齐后核新版本才允许确认。Raw/Silver 成分均仅复用现有对应 Check。 |
| 方案 §4.3、§5 与规则 §1、§3.2 独立任务 | §7–8。DG `tests/test_daily_data_audit_index_minute.py` 与本地接口、页面测试 | 同版 Raw 时间键、Silver 输入窗口和输出键正常。代码齐全但缺 14:00、行数相同而时点错位、重复键或池换版被发现。只认已批准的历史全空例外。预览超预算无执行、排队后换版、生产冲突、取消与同身份重试。自动提交未批准时关闭，获准启用后验证无新事件但窗口打开也能提交、上游不到不读、浏览器关闭不影响执行、同一身份至多一次有效核验。 |
| 方案 §5–6 原生记录与恢复 | §3.4、§8。DG 汇总及读取集成测试 | 成功 run 可按日读回完整元数据，取消或失败留下运行记录而无可复用结论。部分证据失败只影响该范围。汇总发布失败不回滚业务数据。停机漏总结继续显示未生成，有界补记显示真实生成时间。测试原结果、迟到结果、同版消费和重试的读取预算。 |

**本次文档审计结论。** 对照两份方案，以上各阶段采用相同资产范围、业务日期、状态、阻断规则和开放条件。34 项按 1+1+2+5+5+1+10+7+2 对账。既有 Check 足够的路径直接读结果，独立核验仅覆盖 12 项通用指数分钟线。Tushare 人工复核只用于东方财富概念分类。新增内容为实现方案要求所需的接口、结果记录、调用顺序与验收用例。

使用 CodeGraph 核对了数据中心入口与请求链、DG 资产目录、检查和下游 readiness。将逐资产表的键与只读代码目录逐项比较，两侧均为 187 个唯一键，差集为空。当前安装的 Dagster 1.13.26 在隔离实例读回了成功 run 的 JSON 步骤输出元数据。汇总定位、结果读取、提交和取消的 GraphQL 文档通过同版 schema 校验。这里验证的是记录承载方式和接口形态。正式存储保留、同版生产证据读回、耗时与读取预算以及独立审计自动启用继续按本节分阶段验收。
