# 股票周线行情（复权）开发说明

2026-11-16状态：阶段2已提交`45dc21c96`；阶段3历史回刷及人工维护编码、隔离验收和独立审计已完成，符合本阶段LLD要求。源21字段、Raw较新保护和Serving整行选择继续沿阶段2合同；新增用途已在本地代码开放，尚未部署到生产。未执行生产迁移、排程切换或行情写入；阶段4串联与阶段5生产验收仍待分阶段推进。详细证据及边界见原LLD13.28—13.29。管理员已定的0行按0、信任平台价格、20:00—次日00:00探针、不扩大人工范围、无全市场初始化/2010截断等口径不变；PostgreSQL16/18差异仍按决定忽略。

本文依照[数据集开发说明模板](../templates/dataset-development-template.md)复制章节结构并填写。本数据集与另一频率共享的源事实、字段、业务记录和处理规则只在[原LLD第13节](stock-weekly-adj-refresh-low-level-design-v1.md#prod-stock-period-dg-alignment-lld)维护；本说明按具体章节引用，不维护另一套口径。 已定要求统一对照[原方案7.10](stock-weekly-adj-refresh-plan-v1.md#stock-period-confirmed-decisions)，共同实施位置见原LLD13.27。

## 0. 架构基线与禁止项

### 0.1 当前必须遵守的主线

DatasetDefinition→DatasetActionResolver→DatasetExecutionPlan→request builder/source client/normalizer/publisher→Raw及Serving；Ops只保存意图和观察，app装配。当前定义及目标表已存在；拟改合同与现状分开，详见LLD13.1、13.14、13.25。

### 0.2 禁止项

不重算源前/后复权价格，不检测平台未改变复权因子的历史价格修订；不改未复权周/月、日线或DG；不按前缀猜身份、不请求已确认旧码、不改名Raw；不全表清空、不复制旧执行兜底、不增加worker/lane。按13.22最新决定，不扩展上游生产者、不新增上游完成表、不另向源重复捕获依赖。

### 0.3 开发前置硬检查

#### 0.3.0 源接口真实行为验证表

完整实际证据、参数和耗时见LLD13.22，本表说明适用范围。

| 请求形态 | 实际参数/证据 | 返回与结束 | 结论 |
| --- | --- | --- | --- |
| 不传业务参数 | 接口必需freq；仅freq意味着无对象全市场，当前不重做此种全局读取 | 本地doc365已列6000上限，不当作全集基线 | 本次修改既有接口，不由无对象截断回包决定模型；日更使用明确周期全市场 |
| 只传对象过滤 | ts_code=000001.SZ,freq=week及limit6000/offset0，不传日期 | 1786行，首个短页结束，19910405—20261113 | 单股完整源历史成立；不得展开为逐日或逐周期单股请求 |
| 只传时间点 | 既有doc365行为证据；本轮MCP另以000001.SZ/month/20261130取形成中月线 | 1行，trade_date=20261130,end_date=20261113；完整21列 | 周/月坐标不是每日更新日；本轮带代码样本不证明全市场覆盖 |
| 时间区间 | 000001.SZ,week,20261106—20261113 | 基线2条原键 | 按源trade_date过滤；不是计算快照区间 |
| 默认字段 | doc365原2026-10-16默认字段实测；本轮MCP默认月线请求再次得到21列 | 含freq/end_date及完整价格/量额 | 默认字段证据复用，正式下载仍显式21字段 |
| 显式全部及关键字段 | 本轮两频实际connector均显式21字段；MCP显式同列 | 21列齐全 | 逐列去向见0.3.3；不只按默认字段推断 |
| 第二页与末页 | week基线后limit1/offset0、1、2 | 1、1、0；页键及generic解码的21字段内容等于完整2行基线 | 项目connector真实分页已核；不冒充6000行生产跨页验收 |
| 全量覆盖 | 阶段5按批准当期/指定股票及明确周期维护范围验收 | 本轮未执行 | 不能用单股证据关闭全市场准入/覆盖 |

#### 0.3.1 三层语义拆分表

| 层 | 本数据集答案 | 依据 |
| --- | --- | --- |
| 时间输入 | 原point/range仍为自然周五/区间；current_period显式business_date=D；股票完整历史/准确撤回为none；内部自动历史保存D但源无日期 | LLD13.14、13.23 |
| 执行/unit | 本频当前/补齐为一个全市场周期；历史为一只股票本频完整历史；撤回为一只股票本频的指定键，组合维护按下载/撤回股票并集分组，逐unit短事务 | LLD13.14—13.15、13.24 |
| freshness/audit | natural_day/week_friday及iso_week保持；observed_field=trade_date。每日是否完成另看D业务交付，不把未来周期坐标当未来更新 | LLD13.3、13.18 |

#### 0.3.1a 一个数据集有不同处理用途时

阶段2的period/current_period及阶段3的股票历史、准确撤回和组合维护已分别按原LLD13.14—13.17落实；人工无日期范围由input_fields声明，内部自动历史不进入手动选项。具名policy冻结/恢复、两频首次名单和全部消费者的实际结果统一在原LLD13.28—13.29维护，不复制预算或测试证据。

#### 0.3.2 DatasetDefinition消费者审计表

位置均已读代码，改动及验收是计划状态。跨层完整链及动态入口见LLD13.18、13.25。

| 消费方 | 读取事实/本次动作 | 已核代码 |
| --- | --- | --- |
| manual actions | 由具名意图派生用途及time_form，保留原period含义 | ops/queries/manual_action_query_service.py；schemas/manual_action.py；services/manual_action_service.py |
| catalog | 原dataset key/中文名/domain不变，新增能力从Definition派生 | ops/queries/catalog_query_service.py；ops/action_catalog.py |
| workflow | 步骤重新构造请求时保留已给意图，不自动加入撤回 | ops/runtime/task_run_dispatcher.py:_dispatch_workflow/_build_dataset_action_request |
| resolver/planner | D→P只在Foundation；用途决定单元及冻结范围 | foundation/ingestion/resolver.py、unit_planner.py、execution_scope.py |
| request builder | 固定week，只格式化冻结P或代码；历史无日期 | foundation/ingestion/request_builders.py |
| freshness | week_friday仍为周期桶；D完成独立显示 | foundation/datasets/freshness_policies.py；ops/dataset_observation_registry.py |
| dataset cards | 保留Raw/Serving两层及freq过滤，不计业务记录表为行情行数 | ops/queries/dataset_card_query_service.py |
| snapshot rebuild | 沿现有观测重建，不写业务数据；观察失败不回滚行情 | ops/services/operations_dataset_status_snapshot_service.py |
| date completeness audit | 完整周期证据不能由单股修订创建 | ops/services/date_completeness_audit_service.py |
| 自动任务/calendar policy | 当前交易日D、20:00—次日00:00，本频唯一自动意图 | ops/services/dataset_schedule_time_policy_resolver.py；schedule_automation_capability_resolver.py |
| source release/Probe | 三列预检、正式再验、D去重、内部历史依赖 | schedule_probe_binding_service.py；operations_probe_runtime_service.py |
| 前端时间控件 | 用途驱动控件/提交体，不自行算自然周五 | frontend/src/pages/ops-v21-task-manual-tab.tsx |
| Ops展示目录 | equity_market组及原顺序70保留 | ops/catalog/dataset_catalog_views.py |
| 数据源页/分层展示 | raw→serving结构不变，无raw-null fallback新增 | frontend/src/pages/ops-v21-source-page.tsx；ops/queries/dataset_card_query_service.py |
| shared writer/全部发布者 | 新专用条件upsert及共同publisher，不修改BaseDAO全局语义 | foundation/ingestion/writer.py；serving/publish_service.py；两个stk_period_bar_adj Serving builder |
| 测试/文档 | 变更合同同步模板；旧周线活动定义断言按新行为迁移，历史事实读取不改 | LLD13.19、13.25；tests/test_stock_weekly_adj_p1_contracts.py |

#### 0.3.3 源字段端到端对账表

逐列权威映射为[LLD13.23](stock-weekly-adj-refresh-low-level-design-v1.md#1323-字段响应表单及错误合同的编码规定)的21行字段表：文档、Definition、真实21列、Raw/Serving ORM全部对账。Raw的change仍为change，只有Serving为change_amount；新源end_date非空，存量列仍可空且不得补值。所有字段已在现行行情表，迁移不新增源业务列；api_name/fetched_at/raw_payload/created_at/updated_at为本地辅助列。Lake白名单不适用：本次不读写DG/Lake、不增加导出接口。新增本地业务记录不是Tushare字段契约。

#### 0.3.4 硬需求追溯账本

设计、当前实现与验收分别记录。正反例及方法见LLD13.19，阶段2实际结果见13.28；管理员已明确忽略PG16/18差异，采用既有PG18结果完成阶段2验收，无需重复测试；阶段3—5仍是计划。

| ID | 必须达到的结果 | 权威位置/消费者 | 正向/反向及真实验证 | 阶段/状态 |
| --- | --- | --- | --- | --- |
| REQ-01 | 每开市日更新当前week，D与P分开 | resolver、builder、Probe、manual time_form | LLD13.19-1；周中/月中正确P，D当P及混传日期拒绝；检查出站和真实表单 | 2/开发及本阶段验收完成，数据库实测PG18 |
| REQ-02 | 源逐股齐备、新股/盘中停牌必需、全日停牌允许缺席 | input reader、预检、正式捕获 | 13.19-2；低于目标日期、缺码/同数换码/真实未来日期失败，跨日较新合法回包通过；0行口径见13.16/13.22，不新增证明 | 2/开发及本阶段验收完成，数据库实测PG18 |
| REQ-03 | 20:00开始、次日00:00停止；不继承17:00 | Definition能力、schedule/probe、自动表单/绑定/runtime | 20点命中、19:59及次日00点不查源；篡改窗口/filters拒绝；创建/编辑浏览器路径 | 2/已实现及API/浏览器验证 |
| REQ-04 | 完整21字段、真实分页、无截断 | source_client、两频新响应合同 | 两频1/1/0及generic字段内容实测已通过；缺列/重复页/满页未结束反例；正式Decimal精度测试在实现后 | 2/源合同、分页及真实传输验证 |
| REQ-05 | 同键较新保护，同期整行选择 | Raw DAO、共同publisher、人工Serving入口 | 13.19-3/4；按最大end_date选择整行；28日较新则选28日且审计认所属月，不能固定选月末；旧源保护及PG并发/唯一索引 | 2/开发及本阶段验收完成，数据库实测PG18 |
| REQ-06 | 每天真实因子变化触发本频完整历史，两频独立 | 因子比较、内部Probe、resolver | 13.19-5；首次规划同事务冻结两份分频计划，后续读原本频单元不重筛名单；人工/周末只执行明确范围，不要求配对或另查当天因子；源请求无日期 | 3/计划 |
| REQ-07 | 历史失败不挡次日当期，零变化有真实记录 | 原D意图、unit/闭合事实、任务受理 | 两种完成顺序及因子晚到均触发；失败历史、旧D不能冒充新D；0结果不请求历史 | 3/计划 |
| REQ-08 | 周期补齐及准确撤回/组合维护 | planner、DAO、手动输入/展示 | 13.19-6；单股合并不索要全市场证明、不扩其他股票；一股本频一个撤回单元，A提交后仅续B；组合包含仅撤回股票且不为其下载；精确重选，跨freq/源缺键自动删拒绝 | 3/计划 |
| REQ-10 | 逐unit提交、幂等恢复、进度及终态正确 | manifest/业务DAO、executor、worker/详情页 | 13.19-7；取消/退出/重放/观察失败；隔离正式组件运行—取消—续跑—读回 | 2部分已验证，4串联待验 |
| REQ-11 | 行情API/分页/指标继续读唯一周期Serving | quote_query_service主查询及older date、实际消费者 | 13.19-8；bar_count/limit/前后复权/指标、重复月及翻页回归 | 2读取/归属已验证，4串联待验 |
| REQ-12 | 旧写者/排程一次切换，保留原不可变历史 | 迁移、旧week消费者、schedule/probe | 13.19-9；旧路径引用清单、在途办结及范围外不变；自然日更另验收 | 5/计划 |
| REQ-03a | 自动条件只属于这两个数据集，内部历史不公开给任意动作 | capability resolver、manual/schedule API、binding/runtime、自动页选项 | 正确数据集可用；其他动作/手动伪造内部kind拒绝；真实创建/编辑选择项验证 | 当期已验证，历史留3 |
| REQ-03b | 自动当期禁止固定业务日期、股票过滤及源参数 | schedule validator、binding/runtime、自动页提交体 | 空filter/动态D可用；ts_code、固定trade_date、改freq请求拒绝；浏览器确认不可编辑且提交体不带 | 2/已实现及API/浏览器验证 |
| REQ-03c | 一条日更自动任务的两个从属Probe同步更新/暂停 | ScheduleProbeBindingService及ProbeRuntimeService | 两种用途分别触发；暂停不留活动附属规则，其他数据集仍一份；错误动作绑定拒绝 | 当期规则已验证，历史规则留3 |
| REQ-03d | 入队必须保留D/用途并按D去重 | TaskRunCommandService、dispatcher、ProbeRuntimeService | 同D不重复，同一周不同D独立；午夜不查源，入队失败不冒充业务已完成；读回冻结载荷 | 当期D/用途已验证，历史/4待验 |
| REQ-13 | 上游0行直接按当天0结果，不新增完成证明 | input reader、历史Probe、零结果日志 | 0停牌为空集合、0可比较因子保存0且不请求历史；反例为索要新完成表/额外源抓取/把0当未知；0后实际因子到达可触发 | 2主数据/停牌0已验证，因子0留3 |

#### 0.3.5 Prod数据集长任务执行合同

| 合同项 | 本数据集具体设计/引用 |
| --- | --- |
| 是否长任务 | 是。完整历史随股票/分页增长，整批不能假定60秒以内 |
| 最小unit及总量 | 当前/补齐=一个全市场周期；历史=一股本频；撤回=一股本频的指定键；组合按下载/撤回股票并集一股本频一个单元。自动有变化时本频K个历史单元，零变化只留Probe日志；最多1000单元设计限制见13.24 |
| 单unit源边界 | 6000/页、12000行、3页；每次20秒且重试0，最多60秒源调用推导；失败即停 |
| 内存 | 仅当前unit行情，8MiB载荷；按现有行数/载荷预算处理，不新增整进程树RSS硬限制，见13.24 |
| 业务提交 | Raw受控合并/删除、Serving精确重选及unit事实同一个累计20秒事务 |
| 幂等 | batch_id+record_kind+unit_id；同键事实摘要相同复用、异值报错 |
| 续跑 | 从原冻结manifest及已提交unit恢复；未提交捕获重抓，已提交不重抓；不依赖TaskRun计数 |
| 进度 | 用途/阶段/对象/原总量/已提交量/百分比/更新时间；5秒更新、ETA无依据显示不可估算 |
| 取消 | 源控制2秒检查、每页/单元前后；SQL最坏至当前剩余20秒期限结束后回滚，不承诺全链2秒 |
| 终态 | TaskRun与活动node同成功/失败/取消；观察连接独立、失败不回滚已提交 |
| 串行/并发 | 本频发布事务锁；网络在锁外；另一频独立；不让旧历史共享待办挡次日 |
| 真实验收 | 阶段2隔离验证已完成，见LLD13.28；阶段4串联及全量生产前代表性真实演练仍按后续阶段执行 |

## 1. 标准交付流程

阶段顺序按原方案7.5：设计→当期→历史/维护→串联验收→生产切换。共同设计和实际证据按原LLD单处维护；本文件只补本频差异和追溯状态。设计填写不代表编码/测试/生产验收完成。

## 2. 基本信息

| 项目 | 值 |
| --- | --- |
| dataset key/中文名 | stk_period_bar_adj_week / 股票周线行情（复权） |
| Definition/domain | src/foundation/datasets/definitions/market_equity.py；equity_market/股票行情 |
| source/API | tushare单源；stk_week_month_adj；正式源21字段 |
| 官方/本地文档 | [doc365](https://tushare.pro/document/2?doc_id=365)；docs/sources/tushare/股票数据/行情数据/0365_股票周_月线行情(复权--每日更新).md，docs_index.csv第365项，抓取时间2026-04-19，后有2026-10-16实测补充 |
| 对外/多源/自动/日期审计 | 行情API对外读取Serving；不多源融合；自动维护启用能力；周期日期审计适用 |
| Ops展示 | dataset_catalog_views.py：equity_market，原顺序70，不改domain以迎合展示 |
| 真实表 | raw_tushare.stk_period_bar_adj→core_serving.stk_period_bar_adj，严格freq=week |

## 3. 源站接口分析

### 3.1 输入参数

freq必需且由dataset固定；当前/补齐传trade_date=P；单股完整历史只传ts_code+freq；已有point/range在resolver展开周期。limit/offset及fields由source层注入，不暴露为运营随意输入。参数矩阵见0.3.0及LLD13.14/13.22。

### 3.2 输出字段

引用LLD13.23完整21行字段/类型/NULL/Raw与Serving列映射。本轮实测字段齐全，未增加源字段。标准化错误当前unit失败，不继续写其余“好行”冒充完整交付。

### 3.3 源端行为

历史end_date也可更新到当前，是计算截至日。原键为代码/源日期/频率；同一自然周期可有不同日期原键。完全相同原键同次异值失败，跨次同键相同截至日按本次合法完整行更新。实际重复月份及整行选择见LLD13.5；不猜平台内部原因。

## 4. DatasetDefinition事实设计

### 4.1 identity

保留stk_period_bar_adj_week、中文名及原maintain action key，不新增镜像数据集。

### 4.2 domain

equity_market/股票行情保持；Foundation不依赖Ops/Biz/App/DG。

### 4.3 source

保留tushare、stk_week_month_adj、完整21列、doc365、现有频率builder；新两频响应合同见LLD13.23。预检三列是独立用途，不缩减正式source_fields。

### 4.4 date_model

date_axis=natural_day，bucket_rule=week_friday，window_mode=point_or_range，input_shape=trade_date_or_start_end，observed_field=trade_date，audit_applicable=true，bucket_window_rule=iso_week，requires_open_trade_day_in_bucket。保留原周期事实；每日完成另由业务D表达。

### 4.4.1 时间意图归一化

新增business_date与维护用途的适用组合、原输入互斥、D→P和source请求形状引用LLD13.14/13.23。Ops/页面/CLI只表达意图；原period缺省有明确业务含义，不恢复旧week执行器。

### 4.5 input_model

保留现有单值ts_code过滤；business_date为具名意图输入。stock_codes数组和remove_keys三键数组在maintenance_intent，不偷改旧单值过滤。内部factor_history只供自动日更依赖触发，手动提交拒绝；恢复仅原TaskRun ID，不能附新范围。

### 4.6 storage

保留raw→serving，无std。Raw主键(ts_code,trade_date,freq)，Serving保留主键及原日期，新增本频周期唯一索引。新业务交付事实表及旧week表历史边界见LLD13.15。选择不同层合法行数差异，不硬造1:1对账；Raw2/Serving1可正确。

### 4.7 planning

共同stock_period_adj_policy；当前单周期全市场、历史一股本频完整捕获，最多1000单元及累计计划1MiB，冻结前拒绝超量，不截断名单；计划单元先持久化、最后原子冻结。详细数值来源、取消及超限见LLD13.24，不沿用旧共享待办。

### 4.8 normalization

21列按LLD13.23处理；三键非空，end_date新源必须有效；17数值Decimal保留NULL和精度，超数据库精度拒绝；Raw.change与Serving.change_amount分别映射。辅助字段不进入源合同。

### 4.9 capabilities

maintain保留；手动支持13.14允许用途，自动当期/因子历史分别去重和依赖；时间模式按用途校验，union不放宽默认period。当前动作不加入现有每日收盘工作流造成双重触发；本频一条日更自动任务同步三个用途的从属Probe，不要求运营另建排程。

### 4.10 observability、quality、transaction

观测仍按freq过滤原行情，D交付另展示；两频正式捕获fail_unit_on_any_rejection、幂等=true、unit短事务。结构化原因见LLD13.23，观察连接与业务事务分离。

### 4.11 completeness

当前逐股核对计算截至日期不早于目标D、不晚于实际执行日，跨日较新合法结果通过；闭合周期按每股最后应更新日作为最低日期。单股修订不创建完整周期。新股/盘中停牌必需、确认全日停牌可缺席。上游查询0行按当天0结果使用，不索要完成证明；目标行情自身仍做已定逐股预检。

## 5. 表结构、DAO与迁移设计

### 5.1 表设计

Raw及Serving现有业务列逐列复用0.3.3；本频条件upsert保护end_date，Serving按股票/周期选择整行并替换。无std、Redis及新行情缓存表。交付记录schema、索引/不可变约束及周期唯一表达式见LLD13.15；不新增上游完成记录表。Raw/Serving均复用现有模型，std不适用；只给本功能增加交付事实和周期唯一索引，不增加行情列。

### 5.2 工程硬约束

新增ORM必须进入自动发现/DAOFactory；Alembic创建前重查真实head，不按文档快照写down_revision。不清表重建，不改旧交付历史，不在生产执行DDL测试。PG16.13日期表达式证据保留，索引与双连接行为已在PG18隔离验收；管理员已确认忽略16/18差异，无需重复测试。

### 5.3 DAO

现有Raw GenericDAO不能直接保护新版本，拟用本功能专用条件写入；Serving DAO及人工publisher共同走LLD13.15，不改BaseDAO全局语义。业务交付DAO追加不可变事实及查原未完成单元；幂等异值报错。

## 6. Ingestion实现设计

### 6.1 请求构造

固定freq=week；当前/补齐仅P，完整历史仅有效ts_code；fields分页由source注入。精确撤回不请求源。

### 6.2 Unit规划

引用LLD13.14/13.15/13.25；自动有变化时本频K股即K源单元，原日期/名单/预算冻结；零变化保存既有Probe日志，本次检查结果0，不请求历史或造业务闭合批；窗口内定时检查继续。只合并本次股票/频率的合法源记录；不索要全市场周期证明，不因较早源日期强制先补齐其他股票，也不把该股结果标成全市场完整。

人工补数、明确股票修正及周末执行直接使用运营给定的范围；不重新筛选当天因子变化股票，不对两个人工任务重复核全市场名单。两频共用名单仅针对同一次自动因子变化回刷，详见原LLD13.6/13.14。

自动共用名单按LLD13.14由首个历史任务在已有worker中进入Foundation规划，保存两份分频草稿并同事务冻结；各冻结头及执行上下文保存history_plan_refs。另一频任务按原D/本频读取自己的冻结计划及plan_unit，不重查因子形成新名单；行情执行、取消和恢复仍分频独立。精确撤回及组合维护按LLD13.14的一股本频单元冻结指定键，下载/撤回股票取并集，仅撤回股票无源请求；单元数及恢复成本见13.24，不新增限制或协调设施。

### 6.3 Source Client与分页

真实limit/offset证据见0.3.0；6000页、短/空末页、重复键/重复页检测、完整21列与三列合同独立。内存始终当前unit；源传输、行/字节/页边界引用13.24。没有满页后“默认已完”的分支。

### 6.4 Normalizer

引用4.8；正式JSON以Decimal解码，generic审计不是精度验收。失败保留原因，不能默认补字段/补日期/补价格。

### 6.5 Writer

引用LLD13.15的固定顺序：捕获完整→短事务/本频锁→核原引用及幂等→Raw条件合并/准确撤回→按受影响股票周期读Raw→整行选择及Serving范围替换→分层读回→追加unit→提交；失败只回滚当前unit，恢复只读原未完成。

纯撤回跳过源捕获；组合只捕获下载名单中的股票。同股指定键的删除、各受影响周期Serving重选和unit事实一起提交，取消/退出保留已提交股票。LLD13.19-6要求以A两键/B一键验证A提交后只续B，并读回剩余最新候选或候选已空时的Serving结果；仅撤回股票不得发生源调用。

### 6.6 结构化错误与codebook

引用LLD13.23已列code及职责，实施时同次登记codebook。未齐是等待，源错误不是合法空数据；明确指出日期/股票/周期及失败步骤，不打印秘密或截断原范围后声称完整。

## 7. Ops、TaskRun与页面派生

### 7.1 手动任务

引用LLD13.14/13.23：明确用途及条件表单，后端权威校验、前端清除不适用字段，撤回完整键可见。实际创建/切换/提交及恢复浏览器路径为实现后必验。

### 7.2 自动任务

已定20:00起、目标业务日次日00:00停止，60秒间隔；预检齐后入队、正式捕获再核；计算截至日期达到目标D即可，跨日恢复允许较新合法日期并如实保存实际源日期/完成时间。本频当期与另一频独立；历史在同D两频当期完成后按现有因子数据比较，0行按0。午夜不提前探测新D。旧排程切换属于阶段5，不重新验证此业务口径。

### 7.3 TaskRun观测

阶段、对象、已提交/原总量、百分比、最后更新时间和不可可靠估算的ETA均明确。取消、异常、进程退出、观察失败及TaskRun/node终态引用0.3.5；进度不作为续跑唯一依据。

### 7.4 数据状态、数据源卡片与freshness

原freq/周月桶和两层数据映射不变，D交付从新业务事实派生；未来P不表示未来数据已到。状态写失败不改变行情事务。

### 7.5 日期完整性审计

Serving按计算截至日期最新的整行发布，保留源trade_date；审计通过原LLD13.18所列读取入口，按Definition的自然周/月归属比较周期，不能要求所选原日期必须等于固定周五/月末。合法28日月线应被识别，真正缺月仍须报告；其他数据集的现有审计行为保持。

只对有开市日的iso_week适用；不要求每天一根week。全市场周期完整依据与每日D更新分开，不能由单股行情存在抬高覆盖结论。

## 8. 测试与门禁

### 8.1 必补测试

逐条采用0.3.4及LLD13.19；新测试文件为拟建test_stock_period_adj_plan/readiness/publish/history/recovery。正向证明允许路径，反向覆盖每个仅/禁止；独立字面样本与真实生产schema，不调用待测helper生成expected。

### 8.2 必跑命令

本轮仅执行文档检查及真实只读源/DB核验；下列代码检查在对应实现阶段运行，不声称已执行。实施前确认路径存在，再用现有环境，不安装依赖。

- 通用回归：tests/test_dataset_definition_registry.py、test_dataset_action_resolver.py、test_dataset_unit_planner.py。
- 架构：tests/architecture/test_subsystem_dependency_matrix.py、tests/architecture/test_dataset_runtime_registry_guardrails.py、tests/architecture/test_dataset_codebook_guardrails.py。
- 发布/原周合同：tests/test_stk_period_serving_builders.py、test_stock_weekly_adj_p1_contracts.py及已建本功能测试；旧活动规则与新行为冲突须先依据LLD迁移，不能改expected掩盖错误。
- Ops/API/浏览器：实际涉及的manual/schedule/probe/TaskRun/Quote测试及manual/auto页测试；新建/编辑/切换用途真实浏览器路径。
- 文档：python3 scripts/check_docs_integrity.py；git diff --check；新增相对链接/锚点单独核验。

### 8.3 验收勾选

- [x] 管理员已定功能、源21字段及本轮有界分页/单股历史证据已记录。
- [x] 日期、unit、freshness分开；存储、事务、恢复、资源拒绝及验收方法有明确设计。
- [x] 管理员已定上游0行即当天0结果，不新增上游完成表或扩展三个生产者。
- [x] 原方案7.10及LLD13.26—13.27已逐项校准已定口径；单股合并不要求全市场周期证明，不默认全市场补到最早，也不新增2010年过滤规则。
- [x] LLD13.14—13.15已补齐共用名单的首次保存/后续读取、准确撤回的按股单元与恢复；13.19/13.24/13.25同步测试、预算及实现职责。
- [ ] 对应阶段代码、迁移、正反测试及真实表单/API/隔离数据库验收通过。
- [ ] 另获准的生产切换、最小真实演练及自然日更完成。

### 8.4 阶段完成记录

| 阶段 | 当前状态 |
| --- | --- |
| 设计编写 | 已按原方案7.10及LLD13.27校准已定口径，补齐最后两处执行说明，本轮文档复核完成；未编码 |
| 实现/隔离验收 | 未开始；测试/浏览器/实际新SQL性能均未执行 |
| 生产迁移/真实验收 | 未开始；不以本轮原周批证据替代 |

## 9. 发布与回滚

按原方案7.5阶段5及LLD13.25：先处理旧在途及唯一排程，确认并批准存量范围/恢复安排，再建业务事实表、按准确股票周期重发Serving并处理冲突，建立周期唯一索引，统一切换全部写者与排程。失败保留业务已提交单元、停止后续切换，不清表、不改TaskRun旧失败历史、不重启旧写者绕新约束。不扩展上游，不新增完成证明。当前不涉及数据库凭据、安装、DG写入或Kopia。

## 10. 本次交付快照

2026-11-15：完成本频设计填写、共同LLD引用、源/DB真实有界证据及管理员0行口径同步。修改仅文档；新代码、迁移、测试、生产执行均未发生。具体只读样本、数量、页尾、耗时及边界见LLD13.22。13.22原扩展上游建议已撤回；已按原方案7.10及LLD13.27逐项校准已定口径；已删除强制补全市场及额外历史起点审批。代码开发/测试/生产验收均未完成。

2026-11-16：补齐自动历史计划共同冻结和本频读取、精确撤回/组合维护按股提交及中断恢复，更新REQ-06/08和长任务合同；详细步骤只维护于原LLD13.14—13.15。下一步依原方案7.5阶段2—5推进，不把本轮文档检查算成实现验收；本轮未修改代码、数据库、排程或DG。

2026-11-16阶段2实施：共同合同、业务记录/恢复、当期预检/下载及发布、任务/Probe/表单、日期归属与读取链已落代码。实际验证及独立审计以原LLD13.28为准；按管理员忽略16/18差异且不重复测试的决定，阶段2开发、独立审计及本阶段验收完成，未推进阶段3或生产切换。此前各条“本轮未开发/未执行”为其当时文档复核记录，不能覆盖本次最新状态。
