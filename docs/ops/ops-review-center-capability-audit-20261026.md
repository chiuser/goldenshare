# 数据运营后台审查中心功能审计（2026-10-26）

## 1. 审计范围与结论

- 文档类型：`audit`，记录本次核对时的实现，不替代现行 API、数据集和维护流程契约。
- 核对日期：2026-10-26，Asia/Shanghai。
- 代码范围：`dev-interface` 当前工作区，核对时 HEAD 为 `30607c79a`；工作区已有其他任务的未提交变更，本轮未修改功能代码。
- 证据：当前前端、路由、API、查询、服务、数据集定义、持久化模型、调度入口和现有测试。
- 验证边界：未访问生产数据库，未触发真实审计、调度、维护、补数或部署；本地测试使用隔离数据库或 API 替身。因此本文证明代码具有哪些能力，不证明生产已部署同一版本、服务正在运行或历史数据完整。

目前审查中心有三个页面入口：指数、板块、数据集审计。它已经能管理指数激活池、查询两家板块及股票所属板块、按日期检查数据存在性，并对六个数据集检查每天应有的股票或指数是否缺行。数据集审计还支持独立审计记录、缺口明细和自动计划。

必须区分两个限制：普通日期审计不能发现同一天仅缺少部分对象；审计 worker 对符合条件的指数日线缺口会创建补齐维护任务，不能把整个审查中心或完整审计链路理解为只读。

相关现行说明：[审查中心使用与查询说明](/Users/congming/github/goldenshare/docs/ops/ops-review-center-design-v1.md)、[日期完整性与日期对象矩阵审计说明](/Users/congming/github/goldenshare/docs/ops/dataset-date-completeness-audit-design-v2.md)、[指数日线完整性审计、补漏与激活池说明](/Users/congming/github/goldenshare/docs/ops/ops-index-daily-completeness-reconciliation-plan-v2.md)、[Ops API 全量说明](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md)。本文中的数字和限制均以本次代码核对为准。

## 2. 页面、权限与操作范围

| 菜单 | 浏览器路径 | 页面已有能力 | 写入范围 |
| --- | --- | --- | --- |
| 指数 | `/app/ops/v21/review/index` | 激活池列表、数量摘要、数据层状态、源站供数状态、候选搜索、加入及移出 | `ops.index_series_active` 对应池记录 |
| 板块 | `/app/ops/v21/review/board` | 同花顺、东方财富、股票所属板块三个 Tab，筛选、分页和详情 | 查询业务表，不提供修改板块或成员的操作 |
| 数据集审计 | `/app/ops/v21/review/dataset-audit` | 审计规则、手动创建、审计记录及明细、自动审计计划 | 独立审计及计划表；指数日线后处理还可创建标准维护 TaskRun |

前端页面位于管理员布局；非管理员会被引导至用户首页。后端两个审查路由模块的全部接口均要求 `require_admin`，包含读取接口，不只是写入接口。页面菜单不是唯一权限检查。

证据：[菜单](/Users/congming/github/goldenshare/frontend/src/app/shell.tsx)、[路由及管理员检查](/Users/congming/github/goldenshare/frontend/src/app/router.tsx)、[指数及板块 API](/Users/congming/github/goldenshare/src/ops/api/review_center.py)、[日期审计 API](/Users/congming/github/goldenshare/src/ops/api/date_completeness.py)。当前菜单和路由没有独立的“审查中心→新闻智能”页面，相关方案不能计入本次已实现页面能力。

## 3. 指数：激活池管理

### 3.1 查询与展示

页面固定管理 `resource=index_daily`。池的业务键为 `resource + ts_code`；它决定哪些指数允许进入相应 Serving 写入和指数对象审计范围，与 Raw 请求池不是同一对象。

| 能力 | 当前行为 |
| --- | --- |
| 检索 | 按指数代码或名称搜索；关键词经搜索按钮或回车提交 |
| 数据状态筛选 | 全部、完整、待处理、未同步、缺日线、缺周线、缺月线 |
| 源站供数筛选 | 全部、正常、等待源站、待审查 |
| 分页 | 默认每页 50；页面将每页数量限制在 10–200，API 上限 500；按指数代码升序 |
| 数量摘要 | 激活数、已有日线数、已有周线数、已有月线数；有待处理对象时显示待处理数 |
| 行信息 | 指数代码、名称、市场、发布方、缺少的数据层、供数状态、建议处理动作及参考日期、最近 Raw 日期、日／周／月最新日期、移出操作 |
| 条件保存 | 已应用关键词、状态、页码和每页数量保存在 URL；改变筛选会回到第一页 |
| 反馈 | 列表加载、无匹配结果、读取失败；加入和移出成功或失败通知 |

数量摘要统计整个选定资源的激活池，不随关键词和列表状态筛选变化。“完整”只表示日、周、月三张表各有至少一条该指数记录，不检查是否最新，也不检查中间日期是否连续。

数据状态按“全部没有→缺日→缺周→缺月→完整”的优先级给出单个 `data_status`；`missing_layers` 同时保留所有缺少的数据层。不能将“缺周线”筛选理解为能够同时列出所有还缺日线的对象；“待处理”才覆盖所有非完整对象。

查询数据来自 `ops.index_series_active`、`core_serving.index_basic`、`core_serving.index_daily_serving`、`core_serving.index_weekly_serving`、`core_serving.index_monthly_serving`。列表不是任务成功状态或 freshness 的替代品。

### 3.2 供数状态与加入条件

供数判断读取本地 Raw、Serving、交易日历和补齐 TaskRun，不在打开页面时实时请求 Tushare。

| 状态／条件 | 代码如何判断 | 应如何理解 |
| --- | --- | --- |
| 参考日期 | 默认交易所日历中，严格早于上海本地今天的最近开市日 | 当前实现即使在今天收盘后，也不会把今天作为此参考日 |
| 正常 `ready` | 参考日 Serving 已覆盖且 Raw 最近日期满足要求；或缺口分类发现目标日 Raw 已存在 | “正常”可同时存在 Serving 投影缺口，不能代替日期完整性结论 |
| 等待源站 `source_delayed` | 目标日 Raw 不存在，但最近 Raw 日期仍在目标日及之前最近三个开市日范围内，且自动补齐阶段未全部结束 | 从本地落库情况推导出的近期延迟，不是实时源接口诊断 |
| 待审查 `serviceability_review_required` | 参考日不可确定、Raw 长期缺失或近期延迟的自动阶段已全部结束等 | 页面提供人工移出入口，不会因显示此状态自动移出 |
| 允许加入 | 该指数已在指数基本信息中，且最近三个已结束开市日的 Raw 日线均存在 | 日历不足或任一天缺失均拒绝加入；不是只看最近日期 |

候选来自指数基本信息中尚未进入选定池的指数，支持代码／名称搜索，默认最多 20 条、API 最多 50 条。页面展示候选加入资格与原因，不能选中不符合条件的候选；提交时后端再次检查，避免只依赖页面判断。

### 3.3 加入与移出的效果

- 加入：规范化代码并写入一条池记录和相应观察时间；不存在的指数返回 404，已加入返回 409，供数条件不足返回 422。
- 移出：确认后只删除该资源下对应池记录；记录不存在返回 404。不删除已有 Raw 或 Serving 历史。
- 池变动会影响后续按池读取的 Serving 写入和对象完整性审计；它不自动补齐历史行情，也不保证与已经运行中的维护任务原子协调。
- 页面没有批量加入／移出、备注编辑、历史池版本回看或直接补数按钮。
- API 的 `resource` 是文本参数，服务只做去空白和默认值处理，没有资源白名单；页面固定 `index_daily`，不能据 API 可传其他资源就宣称页面支持其他指数池管理或同样的加入资格检查。

证据：[指数页面](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-review-index-page.tsx)、[查询服务](/Users/congming/github/goldenshare/src/ops/queries/review_center_query_service.py)、[池修改服务](/Users/congming/github/goldenshare/src/ops/services/review_center_service.py)、[供数判断](/Users/congming/github/goldenshare/src/ops/services/index_daily_source_serviceability_service.py)、[Serving 写入中的池过滤](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)。

## 4. 板块：两家板块与股票归属查询

### 4.1 三个 Tab

| Tab | 筛选 | 展示及查询口径 |
| --- | --- | --- |
| 同花顺 THS | 板块类型、代码／名称关键词、最少成分股数 | 基本信息来自 `core_serving.ths_index`；成员来自 `core_serving.ths_member` 中 `out_date IS NULL` 的当前成员；人数按不同成员代码计数 |
| 东方财富 DC | 交易日期、板块类型、代码／名称关键词、最少成分股数 | `core_serving.dc_index` 与 `core_serving.dc_member` 使用同一选定日期；不填日期时使用 DC 指数表的最大交易日期；类型选项来自该日指数记录 |
| 股票所属板块 | 股票关键词、THS／DC／全部来源、DC 交易日期、最少所属板块数 | 汇总当前 THS 成员与选定日期 DC 成员，展示股票代码、名称、板块数及所属板块 |

板块列表按成分股数降序、板块代码升序；股票列表按板块数降序、股票代码升序。默认每页 30，页面支持 10–100，三个列表 API 上限均为每页 200。

股票搜索支持代码／简称代码／拼音前缀及名称匹配；输入 200ms 后请求最多 20 条候选，选择“代码｜名称”会转换为代码检索。候选查询要求 `security_type=EQUITY`，没有同时限定上市状态、币种或交易所，不应额外解释为“当前正常上市 A 股名单”。

股票所属板块的数量按 `provider + board_code` 去重；同名 THS 和 DC 板块分别计数，不做跨来源同义合并。列表从已有成员关系出发，并不是完整证券名单，因此最少板块数设为 0，也不等于能查出所有没有任何板块关系的股票。

### 4.2 成员和所属板块详情

- 板块行先显示最多 5 个成员名称；超过 5 个时可打开成分股抽屉，显示代码及中文名称，每页 20 个，由前端分页。
- 股票行先显示最多 8 个所属板块；超过 8 个时可打开详情，全部来源模式按东方财富和同花顺分别展示。
- 列表接口默认 `include_members=true`，页面未关闭；同一请求已返回本页板块的全部成员。抽屉翻页不会再向服务器按成员分页。
- 板块 Tab、各自筛选、页码和每页数量保存在 URL；关键词先输入后提交，其余筛选改变时重置页码；切换 Tab 保留其他 Tab 的筛选。
- 页面有读取失败、加载和无匹配结果反馈，不提供成员增删、板块映射修改、补数、导出或两来源差异对账操作。

### 4.3 结果不能证明什么

1. THS 始终按当前 `out_date IS NULL` 查询；股票 Tab 的历史日期只影响 DC，不能把“全部来源 + 历史日期”当作两家同日历史快照。
2. DC 默认日期取指数表最新日；如果当天成员未齐，会如实显示低人数或空成员，不自动回退到成员齐全的日期。
3. 成分股数由本地成员表计算，不与源站预期数比较，不判断突然下降是否异常，也不证明成员已经完整。
4. 人数统计使用不同成员代码；成员展示数组另行读取，不能将标签数量直接当作独立完整性校验。
5. 列表虽然分页，返回的本页全部成员及股票全部所属板块没有独立数量上限；前端预览和抽屉分页并未限制数据库查询及响应中的成员规模。

证据：[板块页面](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-review-board-page.tsx)、[四个板块查询方法](/Users/congming/github/goldenshare/src/ops/queries/review_center_query_service.py)、[响应字段](/Users/congming/github/goldenshare/src/ops/schemas/review_center.py)。

## 5. 数据集审计：规则与检测能力

### 5.1 数据集规则列表

本次直接加载当前 `DatasetDefinition` 注册表，得到 **94 个数据集，52 个声明支持日期审计，42 个不支持；支持项中 6 个配置日期对象矩阵，其余 46 个为日期存在性检查**。这是代码配置数量，不是物理数据完整数量，也不证明 52 个目标表均在生产存在。

页面按“支持／不支持”和目录分组筛选，展示名称、目录、日期规则、审计粒度、已观测数据时间范围、目标表；不支持项展示原因并不提供创建按钮。规则 API 还返回日期轴、输入形状、观测字段、窗口适用规则、对象类型等，页面没有把所有 API 字段都展开成列。

数据时间范围来自 `ops.dataset_status_snapshot`：优先业务日期，其次已观测时间，最后最近同步日期；无投影时显示“—”。这不是每次打开页面重新扫描业务表，也不能由时间范围两端存在推断中间没有缺失。

规则事实源是 [数据集注册表](/Users/congming/github/goldenshare/src/foundation/datasets/registry.py) 及其定义。数据集清单继续由代码和规则 API 提供，不在本文建立第二套需逐次同步的全量名单。

### 5.2 普通日期审计

执行器根据定义生成应检查的日期，再从定义指定的目标表和观测字段读取范围内实际存在的不同日期；共享目标表时使用定义中的 `row_identity_filters` 限定记录。不能从页面任意输入表名、字段、SQL 或另一套日期规则。

| 已支持规则 | 实际检查内容 | 当前实例 |
| --- | --- | --- |
| 每个开市日 | 默认交易所日历中的各开市日是否有记录 | `dc_member`、`dc_daily` 等；六个矩阵数据集还会检查对象 |
| 每周／每月最后开市日 | 输入范围内各周／月最后开市日期是否存在 | `index_weekly`、`index_monthly` |
| 每个自然日 | 范围内每一天是否存在 | `trade_cal`、`cctv_news` |
| 自然周周五／自然月末 | 对应日期记录是否存在；整周／整月没有开市日时按规则排除并记录原因 | `stk_period_bar_week`、`stk_period_bar_adj_week`、`stk_period_bar_month`、`stk_period_bar_adj_month` |
| 自然月键 | 各 `YYYYMM` 月键是否存在 | `broker_recommend` |
| 自然月窗口有数据 | 将输入日期范围内实际数据归到月份，检查涉及月份是否至少有记录 | `index_weight`；不是检查所有指数权重或整月所有日期 |

相邻的缺失项按“应检查日期列表中的相邻位置”合成缺口区间，每段最多保存 20 个日期样例，不按自然日间隔简单拼接。规则排除项记录候选日期、所属窗口、原因代码和说明。

“通过”只表示应检查日期没有缺失。同一天少一半证券、板块或成员，字段全为 NULL、数值错误、重复记录、Raw 与 Serving 不一致、源站数据没有全部落库，都不属于普通日期检查的判断范围。

实际日期多于应检查日期数量时，页面会显示非预期日期数量提示，但不改变通过结论；当前提示只是 `max(实际数量 - 应有数量, 0)`，不是对“额外日期集合”的精确比较，不能据没有提示断言不存在额外日期。

### 5.3 日期 × 对象矩阵

| 数据集 | 当前目标表 | 每天应有对象来源 |
| --- | --- | --- |
| `adj_factor` | `core.equity_adj_factor` | 当前证券服务表中的上市股票，并按上市／退市日期限制当天范围 |
| `daily` | `core_serving.equity_daily_bar` | 同上 |
| `daily_basic` | `core_serving.equity_daily_basic` | 同上 |
| `stk_factor_pro` | `core_serving.equity_factor_pro` | 同上 |
| `stk_limit` | `raw_tushare.stk_limit` | 同上 |
| `index_daily` | `core_serving.index_daily_serving` | 当前 `ops.index_series_active` 中 `resource=index_daily` 的指数 |

股票来源为 `core_serving.security_serving`，过滤 `list_status=L`，再使用 `list_date <= 审计日期`、`delist_date >= 审计日期`；允许生命周期边界为空。**它是当前上市股票集合加生命周期过滤，不是重建每一天的历史全市场名单**，当前已退市对象可能不在历史检查范围；未配置停牌等逐日豁免。

指数对象也使用执行时的当前激活池，没有历史池版本和每个指数的入池生效区间。将今天的池用于旧日期审计，可能要求检查当时尚未纳入池的指数。

当前只支持股票和指数两种对象来源、单字段对象键。逐个日期读取应有对象与目标表该日不同对象键的匹配结果，记录应有单元、已覆盖单元、缺失单元、受影响日期、去重后的受影响对象数。这里的“实际单元”是应有对象中已匹配的数量，不是目标表原始总行数；多余对象和重复行不会使其增加。

每个缺失日期保存摘要及最多 20 个对象样例，明细含对象代码／名称、业务键、生命周期、目标表、`missing_subject_bucket` 原因和说明。全次审计最多落 5,000 条对象明细；超过后设置 `detail_truncated`，完整汇总继续计算。预算耗尽后的日期摘要可能没有样例，不代表该日没有缺失。

### 5.4 范围、性能和判断前提

- 矩阵单次最多 400 个应检查日期；手动创建先校验，执行时再次校验。自动创建路径没有同样的创建前范围预检，过大范围会在执行阶段失败。
- 矩阵逐日期计算及提交进度、摘要和样例，不一次构建全历史日期与对象的组合；单日仍会取出该日所有应有对象的匹配结果，且进程会累计去重后的受影响对象代码。
- PostgreSQL 矩阵查询设置事务内 60 秒语句超时；这不是整次任务 60 秒上限，也不适用于所有普通日期查询。
- 依赖开市日历的检查直接使用本地默认交易所日历，没有先完整核对所需区间日历的覆盖情况。日历缺少开市日可能缩小应检查集合，不能把审计通过反推为日历完整。
- 空日期集合或空对象池可能得到零缺失并通过；需要结合应检查数量判断，不能只看绿色结论。
- 创建时保存表名、日期字段及规则、固定过滤等信息；矩阵执行还会重新读取当前 Definition 的对象规则，对象池本身也不冻结。因此“规则快照”不能解释为可复原全部历史输入和对象范围。

证据：[规则列表查询](/Users/congming/github/goldenshare/src/ops/queries/date_completeness_query_service.py)、[创建及范围校验](/Users/congming/github/goldenshare/src/ops/services/date_completeness_run_service.py)、[日期规划、实际日期读取、矩阵和执行器](/Users/congming/github/goldenshare/src/ops/services/date_completeness_audit_service.py)、[数据集定义模型](/Users/congming/github/goldenshare/src/foundation/datasets/models.py)。

## 6. 审计记录、进度与详情

| 能力 | 页面和后端的实际行为 |
| --- | --- |
| 手动创建 | 从支持项打开抽屉，只提交数据集、开始和结束日期；成功后进入审计记录 Tab。当前初始日期固定为 `2026-04-20` 至 `2026-04-24`，不是自动选最近日期 |
| 独立记录 | 保存数据集、范围、规则信息、发起人／自动计划、运行状态、结果、计数、阶段、时间及技术诊断，不用 TaskRun 冒充审计记录 |
| 运行状态 | `queued`、`running`、`succeeded`、`failed`；结果另分 `passed`、`failed`、`error`，未完成为 NULL |
| 正确解读 | `succeeded + failed` 表示审计执行完成但发现缺失；`failed + error` 才表示执行异常 |
| 列表 | 展示范围、状态、结论、应有／实际／缺失／排除数、发起方式、详情按钮；矩阵另显示受影响日期与对象 |
| 自动刷新 | 最近记录中有排队或运行项时，每 3 秒刷新列表；当前列表只请求最近 50 条 |
| 进度 | 阶段、已处理／总日期数、当前日期、最后心跳和说明；矩阵每个日期开始和完成时持久化；不是每条 SQL 执行中持续心跳 |
| 停滞提示 | 运行中且已有心跳超过 5 分钟时显示警告；没有自动恢复、取消或清理运行态动作 |
| 普通详情 | 缺失日期数、缺口区间、排除数、日期样例、排除窗口与原因、规则信息、进度、完整技术信息 |
| 矩阵详情 | 缺失单元／日期／对象、每日期缺失摘要、对象样例明细、截断提示及规则信息 |

页面现有限制：

1. 后端支持按数据集、运行状态、结果筛选及分页，但页面没有这些筛选和翻页控件；“最近不通过”和“等待或运行中”均只统计已取回的最近 50 条。
2. 缺口、排除、对象摘要和对象明细接口默认每次 200 条，API 允许最多 500 条并按 offset 翻页；页面未传翻页参数，也无明细翻页控件。即使没有触及 5,000 条落库上限，页面也可能只显示持久化结果的前 200 条。
3. 详情抽屉选中时保存列表行对象，没有独立轮询单条 run；列表刷新后抽屉里的汇总、状态和进度不会自动换成最新对象。抽屉明细查询同样未配置定时刷新。
4. 规则读取错误有明确提示，但审计记录及各明细查询没有同等错误提示，不能仅凭页面空表认定没有记录或没有缺口；自动计划列表也有这一问题。
5. 没有审计 run 的取消、重试、断点续跑、结果删除、导出或一键修复入口。worker 默认只取 queued；进程退出留下 running 后不会自动领取恢复。内部重新执行 running 的矩阵记录会清理旧结果重算，不能称为从已完成日期继续。
6. 队列领取未实现并发 worker 的原子抢占；存在常驻服务入口不等于已验证可并发部署多个 worker。页面也没有可信 ETA 承诺。

持久化表为 `ops.dataset_date_completeness_run`、`ops.dataset_date_completeness_gap`、`ops.dataset_date_completeness_exclusion`、`ops.dataset_subject_completeness_gap`、`ops.dataset_subject_completeness_gap_detail`。

证据：[审计页面](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-dataset-audit-page.tsx)、[记录及明细查询](/Users/congming/github/goldenshare/src/ops/queries/date_completeness_run_query_service.py)、[审计模型](/Users/congming/github/goldenshare/src/ops/models/ops/dataset_date_completeness_run.py)、[worker 执行与状态写入](/Users/congming/github/goldenshare/src/ops/services/date_completeness_audit_service.py)。

## 7. 自动审计及指数后处理

### 7.1 自动计划

页面支持创建、编辑、暂停、恢复和删除自动审计计划，展示窗口、cron、时区、状态、最近结果及结束时间、下次运行时间。编辑不能更换数据集；创建只允许支持审计的数据集。

| 配置 | 已有语义 |
| --- | --- |
| 固定范围 | 每次检查同一个起止区间，不会随日期自动移动 |
| 最近 N 个自然日 | 截至计划时区的今天，包含今天 |
| 最近 N 个开市日 | 从本地日历取不晚于今天的最近 N 个开市日；不足 N 个但至少有一天时仍使用现有日期 |
| 最近 N 个自然月 | 从对应起始月首日至本月末，可能包含尚未到来的日期 |
| 周期及时区 | 校验 cron 和时区并计算下一次触发时间；页面默认每天 22:00、Asia/Shanghai |
| 日历 | 页面固定默认 A 股日历；后端只接受 `default_cn_market`／`cn_a_share`，不开放任意交易所日历 |
| 默认创建窗口 | 最近 10 个开市日；固定范围日期默认同手动审计的 2026 年 4 月日期 |

计划保存在独立的 `ops.dataset_date_completeness_schedule`，不是任务中心的 `ops.schedule`。暂停仅阻止未来调度，恢复会重新计算下次时间，删除只删除计划；这些动作不会取消已经生成的审计记录。页面删除直接调用接口，没有额外确认弹窗。

`OperationsScheduler.run_once` 会检查到期审计计划并创建独立 queued 记录，实际检查由 `DateCompletenessAuditWorker` 执行。CLI 还提供 `ops-date-completeness-scheduler-tick`、`ops-date-completeness-worker-run`、`ops-date-completeness-worker-serve`；仓库有对应常驻服务文件。这些是代码入口盘点，本轮未执行，也没有据此确认生产进程状态。

**指数日线是自动计划的特殊情况：** 到期时只有解析出的范围恰好为计划时区的今天一天、且今天开市，才生成审计。历史固定区间、多日滚动区间会被跳过并推进下次时间；页面仍允许保存这些配置，默认的“最近 10 个开市日”也没有针对指数禁用。因此“计划已保存”不代表该指数计划一定会产生记录。其余数据集没有这项指数专用过滤。

后端有 schedule 筛选、分页、单条读取和显式 tick 接口；页面只取前 50 条，未提供对应筛选、翻页和手动 tick 操作，也未配置计划列表定时刷新。

### 7.2 审计 worker 可以创建指数补齐任务

这是已实现的后处理，不是本轮建议的新功能：

1. worker 完成一次审计后调用 `IndexDailyCompletenessRepairService`。
2. 仅处理 `index_daily`、日期对象矩阵、单日、执行成功但结果不通过的记录；执行当天须为开市日，目标日须为今天或上一个开市日。
3. 按当前激活池重新识别缺口。Raw 已有目标日、Serving 缺行的对象允许补齐；近期 Raw 延迟的对象也可按规则创建维护任务；长期不可服务对象不会因此自动移出池。
4. 排除已有 queued／running／canceling 补齐维护任务覆盖的代码，每批最多 100 个代码，每轮最多创建 20 个标准 TaskRun，最多覆盖 2,000 个代码。
5. 新 TaskRun 使用 `dataset_action / index_daily / maintain`、单日和明确代码过滤，并保存来源审计 ID 等信息。后续标准维护 worker 可能实际写入业务数据，不能把创建审计理解为只会新增审计表记录。
6. 手动审计和已配置自动计划进入一般补齐判断，不统一受下面三个系统阶段的次数限制；系统再审计才按阶段避免重复消耗。已有未结束维护任务的去重仍然适用。

系统另外实现上一个开市日的再审计：当前日须开市，上海时间 09:00–12:00、13:30–16:30 两个窗口内，已有同日不通过审计、没有未结束审计或补齐任务、且仍有近期源延迟对象可重试时，生成新的独立审计记录。当日首次、上一开市日上午、下午共三个自动补齐阶段；不是无限重试，也没有覆盖任意历史日期的自动补数能力。

审计执行器本身读取业务表，只写审计结果；后处理创建维护任务失败会记录日志，不撤销已提交的审计结果。该区别解释了为什么“执行器只读”成立，而“整条审计链路绝不补数”不成立。

证据：[自动计划页面](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-dataset-audit-schedules-panel.tsx)、[自动计划服务](/Users/congming/github/goldenshare/src/ops/services/date_completeness_schedule_service.py)、[计划查询](/Users/congming/github/goldenshare/src/ops/queries/date_completeness_schedule_query_service.py)、[调度组合入口](/Users/congming/github/goldenshare/src/ops/runtime/scheduler.py)、[CLI 实现](/Users/congming/github/goldenshare/src/cli_parts/ops_handlers.py)、[常驻服务文件](/Users/congming/github/goldenshare/scripts/goldenshare-date-completeness-worker.service)、[补齐任务创建](/Users/congming/github/goldenshare/src/ops/services/index_daily_completeness_repair_service.py)、[系统再审计](/Users/congming/github/goldenshare/src/ops/services/index_daily_completeness_reconciliation_service.py)、[阶段及数量常量](/Users/congming/github/goldenshare/src/ops/services/index_daily_reconciliation_policy.py)。

## 8. API 能力清单

以下路径均在 `/api/v1` 下，均要求管理员。路径有能力不等于页面已提供全部参数和控件。

| 方法 | 路径 | 用途及页面覆盖 |
| --- | --- | --- |
| GET | `/ops/review/index/active` | 池列表、筛选和分页；页面固定 index_daily |
| GET | `/ops/review/index/active/summary` | 资源级池数量摘要 |
| GET | `/ops/review/index/active/candidates` | 未入池候选及加入资格 |
| POST | `/ops/review/index/active` | 单个指数入池 |
| DELETE | `/ops/review/index/active/{ts_code}` | 单个指数移出 |
| GET | `/ops/review/board/ths` | THS 板块及可选成员数组 |
| GET | `/ops/review/board/dc` | 指定／最新日期 DC 板块及可选成员数组 |
| GET | `/ops/review/board/equity-membership` | 股票所属板块 |
| GET | `/ops/review/board/equity-suggest` | 股票搜索候选 |
| GET | `/ops/review/date-completeness/rules` | 数据集规则、适用性和已观测范围 |
| POST | `/ops/review/date-completeness/runs` | 创建独立审计记录 |
| GET | `/ops/review/date-completeness/runs` | 列表、筛选及分页；页面只用最近 50 条 |
| GET | `/ops/review/date-completeness/runs/{run_id}` | 单条完整信息；页面详情当前沿用列表行 |
| GET | `/ops/review/date-completeness/runs/{run_id}/gaps` | 缺失日期区间，可分页 |
| GET | `/ops/review/date-completeness/runs/{run_id}/exclusions` | 排除日期及原因，可分页 |
| GET | `/ops/review/date-completeness/runs/{run_id}/subject-gaps` | 每日期对象缺失摘要，可分页 |
| GET | `/ops/review/date-completeness/runs/{run_id}/subject-gap-details` | 已保存的对象缺失明细，可分页 |
| GET | `/ops/review/date-completeness/schedules` | 计划列表、筛选及分页；页面只用前 50 条 |
| POST | `/ops/review/date-completeness/schedules` | 创建计划 |
| POST | `/ops/review/date-completeness/schedules/tick` | 检查到期计划并入队；页面无此操作 |
| GET | `/ops/review/date-completeness/schedules/{schedule_id}` | 单条计划及最近结果 |
| PATCH | `/ops/review/date-completeness/schedules/{schedule_id}` | 修改计划，不更换数据集 |
| POST | `/ops/review/date-completeness/schedules/{schedule_id}/pause` | 暂停未来调度 |
| POST | `/ops/review/date-completeness/schedules/{schedule_id}/resume` | 恢复未来调度 |
| DELETE | `/ops/review/date-completeness/schedules/{schedule_id}` | 删除计划 |

## 9. 对旧数据缺失问题的实际覆盖

| 需要判断的问题 | 当前能力 |
| --- | --- |
| 某数据集某个应有日期完全没记录 | 支持日期审计的数据集可以检查，受定义及本地日历约束 |
| 某天缺少部分股票／指数行 | 仅第 5.3 节六个矩阵数据集能按现有对象集合检查 |
| 某天某个 DC 板块只剩少数成员 | 板块页能看到人数，但 `dc_member` 仅做日期检查，不能自动认定该板块漏成员 |
| Raw 和 Serving 是否少转了一部分记录 | 没有通用自动对账；指数日线有专用缺口分类和补齐后处理 |
| 某天行数突然下降、与相邻日差异过大 | 没有通用人数／行数突降检测或历史趋势告警 |
| 本地是否与源接口完整一致 | 普通审计不会请求源接口比较，也没有通用源端总量核对 |
| 板块热度的拒绝是否合理 | 这里不审查 `HISTORY_INSUFFICIENT`／`MEMBER_COUNT_LOW` 的计算原因，不替代计算任务拒绝明细审计 |
| 已退市股票或历史指数池的逐日完整性 | 当前对象来源不能完整重建历史范围 |
| 分钟级缺口、事件数据合法空日 | 不套用普通连续日期审计；按各数据集不适用原因展示，不能把“不支持”解释为缺数据 |

因此，此前讨论的“按日期和板块核对成员数、Raw 与 Serving 比较、定位突降后再核验源端”，并不是审查中心现已实现的一整套功能；不能仅凭本页日期审计通过就跳过这些核验。

## 10. 本次发现与证据限制

以下记录现状和影响，不代表本轮批准修改功能。

| 级别 | 发现 | 影响与后续处理方向 |
| --- | --- | --- |
| G0 | 创建审计抽屉写“本审计只读取……不影响同步任务”；自动审计说明写“只写入日期完整性审计表”，但 worker 存在指数补齐 TaskRun 后处理 | 对符合条件的 index_daily 单日审计，运营可能误以为绝不会产生维护。后续若调整说明，应同步解释执行器和后处理的区别；现行日期审计文档已明确这一边界 |
| G1 | 指数自动计划可保存通用多日窗口，调度时却跳过非当天单日范围 | 配置成功与生成审计记录不等价；需要后续核对是否约束输入或明确展示原因 |
| G1 | 最近记录、缺失明细和计划列表的页面取数上限未配套翻页；详情不随列表自动刷新 | 页面可能看不到完整已保存结果，运行详情可能停留在打开时 |
| G1 | 部分查询错误会显示为空表，未独立提示 | 页面“没有缺口”不能替代接口成功及汇总核验 |
| G1 | 普通日期审计、当前对象池与日历依赖的检查范围有限 | 不能据“通过”宣称历史全市场、板块成员或源端完整性已证明 |
| G1 | 无 run 取消／可靠退出续跑／并发原子领取 | 不能将进度提交、内部重执行方法或服务文件当作这些能力已经验收 |

本轮未改写相关现行方案，也没有将这些限制自动升级为开发任务；本文件集中保留代码证据和后续决策所需信息。

## 11. 验证记录

### 11.1 已完成验证

| 验证 | 本次结果 | 能证明的范围 |
| --- | --- | --- |
| 注册表静态加载 | 94／52／42，6 个矩阵数据集；核对实际目标表、日期规则及对象来源 | 当前代码声明；不读取生产明细 |
| 后端本地测试 | 70 项通过：第一组 62，指数再审计 8 | 日期规划、规则分组、权限、入池条件、查询、范围门禁、隔离执行及缺口落库、计划和指数后处理等既有测试路径 |
| 前端本地测试 | 三个页面测试文件，共 9 项通过 | 使用 API 替身验证已写断言的展示、请求参数、创建审计／计划、对象明细、进度及候选资格；不是生产浏览器端到端验收 |
| 文档检查 | 结果见本节末尾 | 文档结构和引用；不证明运行逻辑或生产数据正确 |

后端测试文件：[模型](/Users/congming/github/goldenshare/tests/test_date_completeness_models.py)、[日期规划](/Users/congming/github/goldenshare/tests/test_date_completeness_audit_service.py)、[审查 API](/Users/congming/github/goldenshare/tests/web/test_ops_review_center_api.py)、[日期审计 API 及隔离执行](/Users/congming/github/goldenshare/tests/web/test_ops_date_completeness_api.py)、[指数供数](/Users/congming/github/goldenshare/tests/web/test_ops_index_daily_source_serviceability.py)、[补齐任务](/Users/congming/github/goldenshare/tests/web/test_ops_index_daily_completeness_repair.py)、[再审计](/Users/congming/github/goldenshare/tests/web/test_ops_index_daily_reconciliation.py)。Web 共用夹具使用内存 SQLite、替换数据库依赖并隔离真实计算生命周期。

前端测试文件：[指数](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-review-index-page.test.tsx)、[板块](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-review-board-page.test.tsx)、[数据集审计](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-dataset-audit-page.test.tsx)。板块测试仅 1 项，不能将通过数量解释为所有筛选、日期组合、异常及抽屉交互均已覆盖。

复核命令（均已执行；没有启动真实 worker）：

```bash
.venv/bin/python -m pytest -q tests/test_date_completeness_models.py tests/test_date_completeness_audit_service.py tests/web/test_ops_review_center_api.py tests/web/test_ops_date_completeness_api.py tests/web/test_ops_index_daily_source_serviceability.py tests/web/test_ops_index_daily_completeness_repair.py --tb=short
.venv/bin/python -m pytest -q tests/web/test_ops_index_daily_reconciliation.py --tb=short
npm --prefix frontend run test -- src/pages/ops-v21-review-index-page.test.tsx src/pages/ops-v21-review-board-page.test.tsx src/pages/ops-v21-dataset-audit-page.test.tsx
```

### 11.2 代码定位与未验证事项

使用 CodeGraph 的 `codegraph_search`、`codegraph_explore`、`codegraph_callers`、`codegraph_status` 定位审查查询及调用关系；调用分析覆盖 `list_active_indexes` 的 API 入口和 `enqueue_due_audits` 的调度、测试调用。类名级 callers 对部分服务返回空结果，未将其解释为没有消费者，而是继续读取当前 API 装配、worker、CLI 和调度组合代码确认链路。

核对链路为：管理员菜单／路由 → 页面请求 → API 权限及 schema → 查询／修改服务 → Definition／业务表及审计模型；另核对 scheduler → 审计记录 → worker → 指数补齐 TaskRun，以及指数池 → Serving 写入的消费者。

没有完成生产版本、迁移状态、目标表索引及查询计划、真实年度范围性能、线上服务状态、并发运行、运行—中断—恢复或真实浏览器操作验收。文档与本地隔离测试不替代这些证据。本轮产物只包含本文和主索引的一条入口。

文档检查结果：`scripts/check_docs_integrity.py` 通过（失效绝对链接、`.DS_Store` 噪声、Tushare 索引一致性）；`git diff --check` 通过。另与编辑前的 README 副本比较，本轮只增加本文入口，保留该文件原有修改。以上检查不证明生产功能或数据已验收。
