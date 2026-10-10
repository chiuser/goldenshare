# Prod 股票复权周线刷新代码级 LLD v1

起草：2026-10-09；更新：2026-10-10。状态：P0/D0核验完成，P1合同/ORM/DAO及迁移源码已实现；未正式迁移、部署、同步或切换。本文件按 [Prod 数据集开发模板](../templates/dataset-development-template.md) 的0—10节复制结构并填写；模板提示文字不作为项目内容重复保留。

业务范围和阶段以 [方案](stock-weekly-adj-refresh-plan-v1.md) 为准。DG实现仅引用本文交接合同，其余见 [DG LLD新增阶段](../../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#adjusted-weekly-prod-refresh-lld)。实现状态以§12为准：支持合同已存在，当前注册Definition未绑定，表及索引尚未在正式库创建；其余执行与DG交付仍待开发。

## 0. 架构基线与禁止项

### 0.1 当前必须遵守的主线

stk_period_bar_adj_week.maintain → Ops TaskRun → DatasetActionRequest → DatasetActionResolver → DatasetExecutionPlan → IngestionExecutor → Raw/Serving。Ops传维护意图；Foundation决定已结束周、股票范围与源参数；request builder只格式化参数。Foundation不导入Ops/Biz/App；DG只读Prod。

### 0.2 禁止项

不清空、不删除历史键，不改freq=month，不改未复权、备用源和Wealth API/UI。不增worker/lane/systemd，不使用旧同步入口，不把业务交接依赖放进reports。不得以TaskRun SUCCESS、fetched_at或内存计数代替业务完成事实。除本需求拟评审的专用交接表外，不设计通用checkpoint平台或第二套任务状态机。

### 0.3 开发前置硬检查

#### 0.3.0 源接口真实行为验证表

字段清单为0.3.3的21列。本轮通过tushareMcp核验；原SDK证据来自 [M0报告§2](../../reports/stock_week_m0_assessment_20261003.md)。历史报告用于设计依据，不是日常任务读取输入。

| 请求形态 | 参数与结果 | 证据边界/后续门禁 |
| --- | --- | --- |
| 无对象/日期 | 原M0使用freq=week、limit=2，返回受限页；freq必填 | 不能据此断言全市场全历史单请求完整；本轮不扩大无时间运营能力 |
| 只传对象，默认fields | 本轮freq=week、ts_code=000001.SZ，无日期；1781行，19910405—20261009，21列 | 对象全历史可取；生产按明确已有历史范围限制，不能下载后静默丢掉范围外行 |
| 时间点及显式文档fields | 本轮000001.SZ、trade_date=20260925；1行，返回end_date=20261009 | trade_date是行情周期；输出end_date不是请求截止日期 |
| 区间及关键fields | 本轮000001.SZ、20100101—20261009；851行，21列，freq均week，end_date均20261009 | 证明单股票历史区间可取；不推断其他股票完整性 |
| 全市场时间点 | 原M0 20260918复权主源5557行，后页空；前轮本会话20261009样本5559行 | 上线前复核本次已结束周期望代码，不能把旧行数写死 |
| 复权因子 | 本轮000001.SZ、20260610—20260925，76行；相邻样本证明20260612和20260924变化 | P0查日历确认20260925不开市；20260924至20261009的6个开市日日线代码均有因子，详见§11 |
| 默认/显式/业务关键列 | 本轮默认对象、显式点、显式区间均含ts_code/trade_date/end_date/freq/qfq/hfq/vol/amount等21列 | 三类核验已做；未知字段/NULL/精度风险仍由本次unit校验 |
| 分页、后页、短页、集合和值 | 原M0三接口6页合计52行、键/值一致，主源6000后页空；MCP工具不暴露limit/offset | P0已用当前HTTP connector验证13行基准=10+3分页键/值；另验证10+0终止；正常空页保留21列响应字段，详见§11 |

原始MCP响应本轮只保存在会话/临时审计材料中，不作为交付运行依赖。并行调用耗时约5.4—10.9秒含服务端排队，不作为串行生产请求承诺。

#### 0.3.1 三层语义拆分表

| 层 | 本次答案 | 核验与设计边界 |
| --- | --- | --- |
| 时间输入 | 沿用point周五或range日期范围；ts_code单值可选 | 现有Definition/API不新增源端可选参数；自动只传“更新已结束周”的调度意图 |
| 执行unit | 首次全市场range按周；指定代码range保留一个区间；自动point生成新周及变化代码历史区间 | §4.4.1、§6.2；range不是清空；历史unit与输入周日期不同须显式保存 |
| freshness/audit | natural_day/week_friday、iso_week有交易才要求周桶；observed_field=trade_date | 历史刷新不改周桶日期，不把end_date当行情日期；没有交易的周不要求非空 |

#### 0.3.2 DatasetDefinition消费者审计表

P0已核对Definition、resolver、planner、builder、executor、writer、DAO、TaskRun、展示/自动化及DG来源消费者。下表最后一列保留实施阶段回归要求；静态完整消费者清单与发现的问题见§11，未做真实浏览器验收。

| 消费者 | 当前入口 | 需要处理 | 验收阶段 |
| --- | --- | --- | --- |
| manual actions/catalog | src/ops/queries/manual_action_query_service.py、src/ops/services/manual_action_service.py、src/ops/catalog/dataset_catalog_views.py | 身份、point/range、单值ts_code保持；新增内部策略不暴露为表单源参数 | P0静态已核；P1合同/API回归 |
| workflow | src/ops/action_catalog.py及维护工作流消费者 | 扫描该action引用；range语义改为高效区间时同步计划预览 | P0引用已核；P1测试 |
| resolver/planner | ingestion/resolver.py、unit_planner.py、execution_plan.py、plan_helpers.py | 具名unit builder、冻结意图及恢复上下文；不复用公告专用freeze函数 | 已读主链；P1 |
| request builder/source | ingestion/request_builders.py、source_client.py | 显式历史区间、统一21列、取消/硬截止、分页计数 | P0当前connector实测通过；P2新监督链 |
| writer/DAO | ingestion/writer.py、dao/base_dao.py、stk_period_bar_adj_dao.py | 新具名write path；按三列主键更新；业务交接同事务 | 已读主链；P1/P2 |
| freshness/cards/snapshot | datasets/freshness_policies.py、ops/queries/freshness_query_service.py、dataset_card_query_service.py、services/operations_dataset_status_snapshot_service.py | trade_date、表映射及频度过滤不变；交付进度不是业务freshness | P0静态已核；P1回归 |
| 日期完整性 | ops/services/date_completeness_audit_service.py、dataset_observation_registry.py | 保留freq=week和无交易周规则；不把修正次数当日期覆盖 | P0静态已核；P1回归 |
| 自动时间策略/排程/probe | ops/services/dataset_schedule_time_policy_resolver.py、schedule_service.py、schedule_planner.py及运行时排程链 | 新“最后已结束自然周”意图策略；19:30排程仅本数据集；现有month分支保持 | P0策略/排程运行链静态已核；P2真实运行 |
| TaskRun/详情 | ops/runtime/task_run_dispatcher.py、ingestion/progress.py、models/ops/task_run及node | 当前计划预览截断20units，不作续跑依据；独立进度/终态写入 | 已读执行及模型；P2浏览器 |
| 前端时间控件 | Manual Action合同消费者、自动任务时间策略类型及任务详情组件 | 不写dataset_key日期转换；按API合同派生 | P0组件/类型已定位核验；P1/P2浏览器 |
| DG | assets/stock_weekly.py、jobs/stock_weekly.py、raw_stock_weekly_update_job_sensor.py、bootstrap/prod_db/io/checks | 复权来源及覆盖合同迁移，其他来源保持 | 已读主链；D1/D2 |

不修改date_model/input_shape/observed_field；增加planning/storage策略仍需上述消费者和shared model默认值回归。P0静态消费者已列到§11；P1/P2合同/API/浏览器回归仍待实施，不以静态审计代替运行验收。

<a id="source-field-contract"></a>

#### 0.3.3 源字段端到端对账表

共同证据：本地doc_id=365、本轮三类MCP响应；当前Definition请求21列；Raw/Serving ORM已核验；DG weekly_column_specs已核验。P0已只读核验两张实表的字段、类型、主键及索引，21列映射与下表一致；change在Serving名为change_amount。新交接表尚不存在，迁移实施另验。

| 源字段 | 源/实测/fields | Prod Raw → Serving | DG类型/列 | 必填与转换 |
| --- | --- | --- | --- | --- |
| ts_code | 均有 | VARCHAR(16) → 同名 | VARCHAR/同名 | 三列主键；保留原代码，不去T |
| trade_date | 均有 | DATE → 同名 | VARCHAR/同名 | 三列主键；DG格式YYYYMMDD |
| end_date | 均有 | DATE可空 → 同名 | VARCHAR/同名 | 保留源计算日期；刷新记录需有可解释基准 |
| freq | 均有 | VARCHAR(8) → 同名 | VARCHAR/同名 | 三列主键；仅week |
| open | 均有 | NUMERIC(18,4) → 同名 | DECIMAL(18,4) | 沿源未复权值 |
| high | 均有 | NUMERIC(18,4) → 同名 | DECIMAL(18,4) | 同上 |
| low | 均有 | NUMERIC(18,4) → 同名 | DECIMAL(18,4) | 同上 |
| close | 均有 | NUMERIC(18,4) → 同名 | DECIMAL(18,4) | 同上 |
| pre_close | 均有 | NUMERIC(18,4) → 同名 | DECIMAL(18,4) | 源文档为除权前收，不解释成普通bfq前收 |
| open_qfq | 均有 | NUMERIC(18,4) → 同名 | DECIMAL(18,4) | 源前复权，不自行重算 |
| high_qfq | 均有 | NUMERIC(18,4) → 同名 | DECIMAL(18,4) | 同上 |
| low_qfq | 均有 | NUMERIC(18,4) → 同名 | DECIMAL(18,4) | 同上 |
| close_qfq | 均有 | NUMERIC(18,4) → 同名 | DECIMAL(18,4) | 同上 |
| open_hfq | 均有 | NUMERIC(18,4) → 同名 | DECIMAL(18,4) | 源后复权一并更新 |
| high_hfq | 均有 | NUMERIC(18,4) → 同名 | DECIMAL(18,4) | 同上 |
| low_hfq | 均有 | NUMERIC(18,4) → 同名 | DECIMAL(18,4) | 同上 |
| close_hfq | 均有 | NUMERIC(18,4) → 同名 | DECIMAL(18,4) | 同上 |
| vol | 均有 | NUMERIC(20,4) → 同名 | DECIMAL(20,4) | 保留手，不复权、不换单位 |
| amount | 均有 | NUMERIC(20,4) → 同名 | DECIMAL(20,4) | 保留千元，不复权、不换单位 |
| change | 均有 | NUMERIC(18,4) → change_amount | DECIMAL(18,4)/change | DG从Raw读源名 |
| pct_chg | 均有 | NUMERIC(10,4) → 同名 | DECIMAL(10,4) | 源百分数语义不改 |

系统列api_name/fetched_at/raw_payload、Serving created_at/updated_at和交接版本均不进入DG行情。NULL不凭空填0；源精度超出当前合同须报错，不静默损失精度。

#### 0.3.4 硬需求追溯账本

所有代码/测试为拟修改或拟新增，状态均“待实现”，不是通过清单。

| ID | 硬需求/代码落点 | 正向测试 | 反向测试 | 真实验收/阶段 |
| --- | --- | --- | --- | --- |
| W01 | 仅week；Definition、writer、交接白名单 | 周线更新 | month/未复权键不变、跨频拒绝 | 两表分freq摘要，P1/P3 |
| W02 | 不清空；upsert及旧键差集 | 同键新价格覆盖 | 空/缺键不删除；请求失败非无源 | 源/写入/保留键，P2/P3 |
| W03 | 按日因子并集；weekly_adj_scope | 周中除权、跨周欠账 | 同周两次变化不漏；新股缺前值不误报 | 已知20260612/20260924样本，P0/P2 |
| W04 | 新周及单股历史unit；planner/builder | 1+K请求 | 禁止股票×周；未结束周拒绝 | 实际参数/页序列，P0/P2 |
| W05 | 21字段全链；source/normalizer/DAO | 默认/显式/关键字段一致 | freq缺失/冲突键/超精度阻断 | 源/标准化/Raw/Serving，P2 |
| W06 | 业务完成/交付独立于Ops；§5.4 | commit后可恢复和被DG读取 | 进度/终态写失败不回滚行情 | 注入观测失败，P2/J1 |
| W07 | 长任务有界与取消；executor | unit提交后递增、恢复幂等 | 半页/退出不判完成；取消不领新unit | 运行—取消—恢复—读回，P2 |
| W08 | 因子基准已刷新；validator | end_date覆盖因子且价格样本吻合 | 时间戳新但价格旧/混基准仍pending | 独立close样本校验，P0/P2 |
| W09 | 同一冻结意图先续跑；plan/receipt | 跳过已提交unit | 改范围/预算/fields不能伪装恢复 | 部分失败到成功，P2 |
| W10 | 19:30与完整周；schedule/time policy | 19:30提交已结束周 | 19:29不请求、长假空周不造数据 | 自动真实首批，J1 |
| W11 | bootstrap完整一次，日常只本次范围 | 一次键和值对账 | 无reports/旧hash仍可运行 | 删除临时材料后隔离运行，D2/J1 |
| W12 | DG唯一Prod来源、顺序交付 | 新周+历史修正到DG | Tushare被拒调用仍成功；旧批不覆盖新批 | D2/J1 |

#### 0.3.5 Prod数据集长任务识别与执行合同

| 合同项 | 本次设计 |
| --- | --- |
| 长任务判定 | 首次约876周；自动刷新随变化股票增长，按长任务治理 |
| unit | 全市场一周，或单股票一个历史区间；unit是事务/恢复/进度边界 |
| 硬上限 | page=6000、最多3页/12,000行；单unit业务payload≤8MiB，进程目标RSS≤256MiB |
| 写入批次 | SQL绑定按BaseDAO能力拆批；完整unit一次短事务，Raw/Serving合计≤24,000行 |
| 持久化 | 每unit行情及业务完成记录同事务；未提交unit无对上事实 |
| 幂等/续跑 | frozen batch_id+unit_id；行情(ts_code,trade_date,freq)；用已提交业务记录恢复 |
| 进度 | stage、current code/week/window、unit_done/total、rows_committed、percent、updated_at；每≤5秒更新活动信息，≤30秒可见 |
| 取消 | 页/unit前后、源监督进程每≤2秒；源硬截止20秒、SQL20秒/lock2秒；先不领新unit，再保留已提交unit |
| 终态 | TaskRun及活动node成功/失败/取消一致；独立观测事务失效不回滚业务，恢复后补观测 |
| 并发 | 单数据集业务发布者；沿现有worker/队列；PG advisory session锁覆盖本批，不是全历史数据库事务 |
| 最小真实验收 | 2个周unit及至少2个已知除权股票区间，实际取消、退出恢复、幂等重放、浏览器进度及读回 |
| 默认禁止 | 全历史长事务、末尾首次写盘、worker新增、凭心跳递增完成量 |

## 1. 标准交付流程

按方案P0→P1→P2→P3及DG对应阶段推进。P0完成当前connector分页、完整消费者审计、容量与专用持久化设计评审；P1完成合同/迁移/配置；P2完成执行及小样本门禁；获准后P3全量。未执行的迁移、浏览器、同步保持待验证。源事实维护在0.3.0，字段在0.3.3，测试/证据关联0.3.4，不新增报告事实源。

## 2. 基本信息

现有dataset_key=stk_period_bar_adj_week，中文名“股票周线行情（复权）”，equity_market/股票行情，Tushare接口stk_week_month_adj，doc_id=365。[本地源文档](<../sources/tushare/股票数据/行情数据/0365_股票周_月线行情(复权--每日更新).md>)；因子doc_id=28，[本地因子文档](../sources/tushare/股票数据/行情数据/0028_复权因子.md)。

修改存量数据集，不新增另一套周线身份。历史起点读取Prod已有week最早日期；截止为resolver计算的已结束周。审计日期2026-10-09；旧证据的库存量不能替代执行前库存。

## 3. 源站接口分析

### 3.1 输入参数

| 源参数 | 使用方式 | 运营输入 |
| --- | --- | --- |
| freq | 固定week，不能由调用方改为month | 不暴露 |
| trade_date | point周unit，格式YYYYMMDD | 沿用point意图；resolver归一化 |
| ts_code | 单股票历史unit/现有单值过滤 | 沿用可选单值，内部变化名单不加表单 |
| start_date/end_date | 定向历史区间，不与trade_date同时发送 | 沿用range意图；内部修正范围由planner生成 |
| limit/offset | 统一分页策略 | 不暴露 |
| fields | 21列来自Definition，非request builder拼装 | 不暴露 |

### 3.2 输出字段

转换唯一清单见0.3.3。日期在PG保持DATE、DG导出YYYYMMDD；数字通过Decimal字符串无损转换至合同精度。Serving只把change映射change_amount。返回end_date是基准证据，不是partition；也不能仅因end_date新就认定价格已正确刷新。

### 3.3 源端行为

源单页最多6000。每页统一fields，短页终止，满页必须继续；最多3页/12,000行，不累积全任务。完全相同重复键可计数去重，同键异值阻断。源未就绪、限流、网络、权限、参数错误分别分类，不把失败当无数据。生产沿用已有Tushare客户端/token来源，不调查配额、不新增SDK依赖。

## 4. DatasetDefinition事实设计

以下是切换后的目标Definition。P1已支持对应模型和校验，当前注册定义仍保留旧绑定；P2执行器完成后才整体切换，状态明细见§12。

### 4.1 identity

dataset_key/display_name/aliases沿现有定义；description补充“因子变化后刷新对应股票已有历史”；logical_key/logical_priority沿当前构建默认值，不新建逻辑身份。

### 4.2 domain

equity_market/股票行情不变；freshness引用当前FRESHNESS_POLICY_BY_DATASET，不在domain加节奏或DG交付状态。

### 4.3 source

source_keys=(tushare)，adapter=tushare，api=stk_week_month_adj，fields=0.3.3全部21列，doc_id=tushare.stk_week_month_adj。保留现有request_builder_key，base_params固定freq=week或builder唯一生成，不能两处不同值。release_policy沿现有合法枚举；晚发布由本批完整性门禁表达，不造新字符串。

### 4.4 date_model

natural_day/week_friday/point_or_range/trade_date_or_start_end，observed_field=trade_date，audit_applicable=True，bucket_window_rule=iso_week，bucket_applicability_rule=requires_open_trade_day_in_bucket；not_applicable_reason=None。字段不变。

### 4.4.1 时间意图归一化设计

Ops保留point/range时间意图，自动策略只生成“更新最后已结束周”。上海时间周五19:30前候选是上周五，此后及周末是本周五，周一至周四是最近周五；这只是意图边界，源完整性仍须另验。resolver归一化周界、历史截止和因子扫描窗；planner生成显式unit时间。历史unit用自己的start/end，不能继续使用新周anchor。builder只格式化YYYYMMDD。

首次all-market range逐周规划。指定ts_code range为单股票区间。自动point先恢复未闭合批次，再选择最早未完成已结束周；不跳过欠账。手动历史point/range形成修订批次，不推进自动周frontier。

区分意图使用现有DatasetActionRequest.trigger_source及time_input/filters；不加供运营选择的模式参数。具名freeze函数将scheduled_week、historical_refresh或manual_revision及原trigger_source冻结到plan/execution_context；重试恢复冻结意图，不能因为重试由人工点击就变成manual_revision。P1已将ValidatedDatasetActionRequest.trigger_source显式投影到DatasetExecutionPlan，并让恢复消费者保留execution_context中的原意图，不能在builder中猜触发来源。scheduled_week才能推进自动周/factor frontier；人工范围修订只交付其明确范围。

### 4.5 input_model

现有trade_date/start_date/end_date及可选单值ts_code保持。required_groups/mutually_exclusive_groups/dependencies沿已验证合同，不加运营选择“自动/全量/因子”等源参数。bootstrap使用明确已有历史range；重试使用原维护意图及冻结执行token，不允许调用方任意修改内部unit。

### 4.6 storage

raw_dao=raw_stk_period_bar_adj、core_dao=stk_period_bar_adj；raw_table=raw_tushare.stk_period_bar_adj；target/serving=core_serving.stk_period_bar_adj；single_source_serving/raw→serving；std_table=None。两个冲突键均(ts_code,trade_date,freq)，row_identity_filters={freq:week}。

拟新增具名write_path=raw_core_upsert_with_delivery及delivery_dao_name/delivery_table，默认None，不改变其他write path。该路径只允许具名weekly_adj_policy、unit提交、单并发及本freq；linter明确禁止用于month或其他dataset。observation/stage/replacement_scope保持不启用，不借用fund_daily观测表、公告checkpoint或staged_stream语义。

### 4.7 planning

universe_policy=no_pool；不以在市池裁掉历史。unit_builder_key拟改stock_weekly_adj_refresh；offset_limit/page_limit=6000；fetch_concurrency=1；buffer_all仅缓冲单unit，max_source_rows_per_unit=12,000。

拟新增planning.weekly_adj_policy，类型WeeklyAdjExecutionPolicy，存于Foundation具名合同文件；其他Definition默认None。策略冻结源/日期/字段/存储/预算；executor通过注册策略消费，禁止在通用主链按dataset_key散落分支。当前announcement_scope.freeze_execution只支持公告，不能强塞周线execution_context。

P1修改模型/builder/linter/Plan投影时同步校准原数据集模板，注明当前支持的新增字段；本轮不把未实现枚举写成模板现行能力。

### 4.8 normalization

沿用date_fields=(trade_date,end_date)、全部17数值字段Decimal、required=(trade_date,ts_code,freq)、_stk_period_bar_adj_row_transform。Raw可选NULL保留；新捕获qfq核心字段/基准缺失列为未完成刷新原因。不得重命名Raw、去T或自动合并股票身份。

### 4.9 capabilities

maintain的manual/schedule/retry保持True，supported_time_modes=(point,range)。拟声明schedule_time_policy=latest_completed_calendar_week，输出point/trade_date；该名字需要同时扩展合法策略类型、Ops解析/运行时及API/前端策略消费者，未实现前不能写入生产排程。

### 4.10 observability、quality、transaction

progress_label中文可读，observed_field仍trade_date。quality新增本次范围、freq、重复键、源完整性及基准校验，任何reject导致本unit不发布；不要保留通用“记录reject后仍发布部分unit”的默认行为。bootstrap历史可选NULL或异常值按源原样保留并记录，不能反向清洗旧历史；当前新增源不完整应阻断。

commit_policy=unit，idempotent_write_required=True；write_volume_assessment写入6.7的行数、短事务和拒绝策略。Ops进度/Issue/freshness不进入业务事务，补观测不能修改交接数据。

### 4.11 completeness

周桶完整性沿现有Definition及交易日历。新周期代码集合用已验证Prod日线同周实际代码并集，超过集合预算或上游未完整时不执行；源有额外有效代码时不得随意删除，先核验身份和源范围。不能用上市股票池作为全部历史覆盖依据。

历史完整性分为：源返回已更新键、Prod原有保留键、源新增键、未处理失败键。明确每组计数/样本，不将source_empty_preserved计为历史刷新完成。retired/T代码仅原样保留；不增加特殊去T规则。

## 5. 表结构、DAO与迁移设计

### 5.1 表设计

Raw/Serving复用现有ORM：models/raw/raw_stk_period_bar_adj.py、models/core_serving/stk_period_bar_adj.py；键及精度见0.3.3。Raw保留api_name/fetched_at/raw_payload；Serving系统时间沿当前契约。没有STD/Silver/Serving Light新增。

P0实查：Raw只有(ts_code,trade_date,freq)主键；Serving另有trade_date和(freq,trade_date)索引。单代码历史走Raw主键，850行执行约0.630ms；Raw全市场单周走并行全表扫描，5559行约246.669ms、约97,870个读缓冲页。P1拟仅给Raw增加部分索引(trade_date,ts_code) WHERE freq='week'，避免首次约876个unit反复全表扫描；不重复给Serving建索引，不重建/分区行情表。建索引方式、锁和额外空间列入迁移实施审查，索引后收益待真实EXPLAIN验证。

### 5.2 工程硬约束

不改行情字段/类型；新业务交接表只append，不ALTER/DELETE旧行情。P1先执行当前环境alembic heads，再生成revision/down_revision；本设计不预填迁移ID。ORM必须进入table_model_registry；迁移、PG约束及SQLite隔离测试替身一致。

### 5.3 DAO

沿用Raw/Serving DAO和BaseDAO bulk_upsert；在调用前完成unit冲突/范围校验。拟新增StockWeeklyAdjDeliveryDAO及DAOFactory属性。DAO只做SQL/幂等读写，不决定周界、因子名单、调度或重试。

<a id="delivery-contract"></a>

### 5.4 唯一业务交接合同：stock_weekly_adj_delivery/v1

**必要性评审。** 单unit数据在Prod与DG两个进程中交付；Raw会被后续更新覆盖，TaskRun摘要截断且观测允许失败。仅metadata/cursor/fetched_at不能同时证明完成范围、恢复和稳定版本。因此提出一个专用Foundation表，不新增DG状态实体。P0技术评审保留这一专用设计，容量样本及取舍见§11；不推广为通用框架。技术评审完成不等于正式建表/迁移执行授权。

拟新增core.stock_weekly_adj_delivery，一行代表不可变的业务交接记录：

| 字段 | 类型/约束 | 含义 |
| --- | --- | --- |
| revision | BIGINT identity PK | 同一发布者串行提交的读取顺序；允许rollback形成空号，不以连续号证明完整 |
| contract_version | SMALLINT，固定1 | 未知版本DG拒绝 |
| batch_id / unit_id | UUID / VARCHAR(128)，UNIQUE(batch_id,record_kind,unit_id) | 恢复和重复发布幂等键；不是TaskRun主键 |
| record_kind | VARCHAR(24)枚举plan/unit/batch_closed/bootstrap_closed | 冻结计划、实际unit、闭合交付批次；append事件，不维护queued/running等TaskRun状态 |
| intent / unit_kind | JSONB / VARCHAR(24) | 原始point/range及触发意图；point_week/stock_history等具名unit |
| cutoff_week / start_date / end_date / ts_code | DATE/DATE/DATE/VARCHAR(16)可按kind为空 | 源周期截止/历史窗口/原始股票代码 |
| factor_scan_start / factor_scan_end / factor_target | DATE/DATE/NUMERIC(20,8)可空 | 扫描覆盖窗与股票因子目标；不能靠全局 MAX(date)证明覆盖 |
| outcome | VARCHAR(32) | published/source_empty_preserved/partial_source_preserved/no_trading_week；网络/权限失败不能写成preserved成功 |
| payload | JSONB | plan的有界unit清单，或日常unit的21列标准化行情；bootstrap unit只摘要，不存全历史副本 |
| rows_received / rows_unique / rows_written / rows_preserved | BIGINT，非负 | 明確区分源、去重、写入、保留；rows_written是每层业务键数，不把Raw+Serving相加 |
| basis_date / payload_digest / scope_digest | DATE可空 / VARCHAR(64) / VARCHAR(64) | 本unit基准及本次传输完整性；不是永久历史hash门禁 |
| reason_summary | JSONB，≤20样本 | 保留/未刷新原因及计数；不含token/SQL凭证 |
| published_at | TIMESTAMPTZ | 业务提交记录时间，不用它代替revision水位 |

plan仅保存共享的字段/预算/意图一次，unit清单保存unit_id、kind、code、point或range边界及factor_target；不把完整Definition、重复policy、源行或全部request_params逐unit塞入plan。P0按此合同构造1000个stock_history unit的容量示例为224643字节，小于1MiB；这是拟定序列化形状的估算，不是已实现planner测试，P1还须对真实冻结对象校验上限并测试超量拒绝。

固定dataset/freq由表合同及CHECK约束表达；不让调用方透传表名/freq。索引：(record_kind,revision)、(batch_id,record_kind,unit_id)；payload限制8MiB/每unit12,000行情行，plan≤1MiB/1,000unit。日常整批payload总量上限256MiB，与DG一致；闭合头记录总行数/总字节、最大输入周anchor、零行原因和unit集合摘要，最多1000个unit ID且头控制投影≤4KiB，不传整份清单给sensor。

规划根据历史窗口周数、当前对象规模及标准化字段长度上界预估总量；超过unit/字节预算先拒绝，不开始源请求。当前批写入时累加实际payload字节，再次超限不提交当前unit/不闭合。需另获批准分范围处理或调整经过实测的局部预算，不设计自动分组状态机。未闭合的已提交unit仍可读回、恢复，不能在新意图下跳过。factor frontier只有整个原扫描范围完成后才推进，不用某一手动子任务冒充全周完成。

**提交与恢复算法。**

1. 现有TaskRun受理意图；Foundation将范围、字段/预算版本、期望unit和因子窗冻结为plan业务记录；冻结失败时尚未写行情。
2. 单数据集PG advisory session锁保证一批只有一个发布者，覆盖本批源捕获及多个短事务；锁键只属week adjusted，不锁月线。所有入口必须接入该发布者，不允许旧writer绕开。取消/进程退出自动释放连接锁。
3. 每unit先查同batch/unit已提交记录；有则核验scope后恢复，不重复请求。不用TaskRun unit_done跳过。
4. 拉取、校验、归一化后，一个短事务upsert Raw、Serving并append unit业务记录；提交失败三个均不可见。业务交接是交付数据本身，不是Ops观测。
5. 提交后独立写进度/node/Issue；写失败只记录观测问题，不能回滚、停止领取本批其余已获准业务unit或误报单位未提交。源/业务错误才决定本批停止。
6. 所有冻结unit有对应终结业务结果、范围和值读回通过后append batch_closed。失败/取消/未就绪不产生closure，续跑原batch；partial_source_preserved需记录缺键集合并确认返回部分的价格基准有效，不能把当前全市场缺码列为正常闭合。
7. 首次历史刷新完整对账及捕获期因子补刷完成后append bootstrap_closed，记录当前库存边界及bootstrap revision B0；本次初始unit只有完成摘要，不要求永久源缓存。

**payload精度及版本。** 日常payload保存提交后的标准化21列，日期YYYYMMDD，decimal以字符串保存，NULL保留，固定键排序；摘要基于canonical row encoding。交接payload与Raw/Serving在同事务验证一致；不直接把未经归一化的原始JSON当正式数值。闭合头列出有界unit ID集合/数量及摘要，DG只能读取属于该闭合批的unit；不得用当前Raw替换旧批payload。

**读取合同。** DG用唯一远程包装脚本的只读事务，头查询只投影revision/batch_id/cutoff/合同版本/数量/摘要；payload仅在运行job内按unit流式读。既有原bootstrap白名单只含行情表，必须新增交接表显式白名单，不能SELECT *或任意schema扩权。DG不写交接表，不存回执到Prod；交接记录不进入行情Parquet。

**保留与退出。** 交接payload是可重放业务增量，不是搬运证明；日常只读未交付批次。本轮851行样本将数值转字符串后，JSON约333,816字节，约392字节/行。外推新周5559行加20股票各851行约8.86MB/周；P0另测850行标准化JSONB表达式平均476.56字节，外推约10.76MB/周、559.5MB/年，尚未计新表索引、控制记录及实际TOAST压缩，不使用源矩阵146字节/行低估对象payload。不设计自动DELETE、归档服务、永久全历史复核或reports依赖；清理需确认DG水位、保留窗及另获明确清理授权。停机超过可读取范围时走受控bootstrap，不假装cursor可以重建丢失payload。

## 6. Ingestion实现设计

### 6.1 请求构造

_stk_period_bar_adj_week_params按unit自身归一化时间格式化：point只trade_date；stock_history只ts_code/start_date/end_date；freq固定week；fields始终来自Definition。builder不读数据库、不选日期、不拼变化代码。不能因为原request是point而把history unit再次发成point。

### 6.2 Unit规划

拟新增ingestion/stock_weekly_adj_scope.py，提供freeze_weekly_adj_execution、resolve_weekly_adj_units、load_changed_codes、validate_weekly_adj_source_basis。注册unit builder，不直接复用_stk_factor_pro私有函数或公告freeze函数。freeze_weekly_adj_execution只生成纯计划/冻结上下文；manual preflight、预览和resolver.build_plan禁止DML。TaskRun受理后，执行器取得发布锁才持久化业务plan。

自动扫描范围：(上次闭合factor_scan_end，本次已结束周最后开市日]，每个d与前一开市日比较，取并集；先校验每日期覆盖及相邻值。范围最长一个待处理周，遇长停机按最早周恢复；raw最早日期按变化代码一次GROUP BY，不逐代码SQL。新股无前日行分类为首次出现；有历史却缺相邻因子列pending。

unit_id=hash(contract_version,batch_id,unit_kind,ts_code,规范时间窗,scope_digest)，同冻结批恢复稳定。progress_context保存中文阶段、当前代码/周、窗口、unit序号；不可全量放进cursor或TaskRun摘要。

首次按周约876unit，上限1000；自动1+K，上限1000及整批payload256MiB。超限在计划冻结前明确报预算错误，显示完整待处理范围，等待获准调整范围或局部预算；不自行拆自动批次、不推进factor frontier。首次期间若因子变更，先补单股全历史后生成bootstrap_closed。

### 6.3 Source Client与分页

评估复用source_client分页迭代，增加受具名策略控制的调用监督/取消/预算；不能把公告的专用policy对象当周线policy。源请求在可终止子进程，硬截止20秒，正常页前后检查取消，≤2秒查询独立取消；本地隔离替身证明超时/终止及不泄漏token。

一个unit最多3页/12,000行，源响应和normalizer结果都计入256MiB RSS目标；首次全部876周不常驻内存。满页继续拉，超量整unit不提交。每页持同fields/筛选；若同一股票历史出现不能解释的多个basis factor，停止重取该unit而非接受混合基准。connector实测见0.3.0及§11。具名周线响应策略在监督进程内保留并校验envelope：code=0、data对象、完整且不重复的21字段、每行长度一致，才允许rows空。data缺失、字段缺失/重复或结构错误必须报weekly_adj.source_payload_invalid，不能写成source_empty_preserved；全市场完整性另验，正常空页也不自动等于可闭合空批。当前通用call/call_bounded尚未满足此约束，P1迁移具名响应策略及全部调用方，公告既有策略保持。

### 6.4 Normalizer

沿用现有Decimal/date/row transform；补scope和batch-key冲突验证。同键同值去重计数，同键不同值报weekly_adj.source_key_conflict；空、越界、缺主键、NaN/Infinity、精度溢出不静默截断或填0。不强制修订历史原始异常；旧键保留的原因独立记账。

### 6.5 Writer

拟新增ingestion/stock_weekly_adj_delivery.py，具名路径内完成范围验证、分层upsert、payload标准化和交接append；通用writer注册分派，保留其他路径行为。核心接口publish_unit(session,definition,unit,batch)->CommittedUnitDelivery；publish_closed_batch只在冻结unit闭合后调用。Raw/Serving upsert后，在同一短事务中按本unit实际输入键读回Raw显式21列，校准Serving映射并生成canonical payload，之后append交接；禁止用未经数据库精度校准的源float生成交付事实。读回不扫描未选历史。

cancel-before-commit回滚该unit，commit-after-cancel仍按实际完成记录恢复，不能宣称没提交；每个unit之后检查取消，不领新unit。独立Observer调用不能把已提交unit再次记为失败；当前_process_fetched_unit/report_progress交互需正反回归，不仅补异常catch。

### 6.6 结构化错误与codebook

拟新增weekly_adj.scope_mismatch、source_key_conflict、source_payload_invalid、source_not_ready、basis_not_updated、factor_coverage_missing、row_budget_exceeded、delivery_contract_mismatch、writer_busy、source_empty_preserved、partial_source_preserved。每码在codebook登记中文含义、阶段、可重试性、样本和动作。超时/网络/认证/限流沿现有分类；“未刷新”不是网络失败的别名。

基准验收至少选择旧历史周close，用该周最后交易日因子和源basis_date因子独立核对至源价格精度；周中除权的OHLC不能用整根周K同一个因子替代日内复权聚合。没有独立基准时保持basis待验，不靠输出证明输出。

### 6.7 配置审计与性能预算

| 配置 | 默认/来源及持久化 | 消费者/生效/可见性/测试 |
| --- | --- | --- |
| weekly_adj_policy | Definition planning中的具名策略；冻结到本批plan | resolver/planner/executor/linter；代码部署后新意图生效，恢复要求合同一致；计划详情及合同测试 |
| page_limit / max_source_rows / max_pages | 6000/12000/3，Definition及具名policy | source/executor；页序列可见；满页/超量反例 |
| source_timeout / cancel_poll / progress_interval | 20秒/2秒/5秒，policy | 监督进程/observer；日志显示阶段和超时；取消与30秒可见测试 |
| observation_timeout_seconds | 2秒，policy，冻结到execution_context | TaskRunDispatcher经execution_scope显式提取；独立取消/观测连接使用，不进入业务事务；None/公告/未知合同测试 |
| db_statement_timeout / lock_timeout | 20秒/2秒，policy，SET LOCAL | writer事务；超时分码；lock/rollback/重跑测试 |
| max_units / max_payload_bytes / max_plan_bytes / max_batch_payload_bytes | 1000/8MiB/1MiB/256MiB，policy及PG CHECK/批闭合校验 | planner/DAO/导出；超量不执行；容量反例，与DG总量一致 |
| fetch_concurrency / memory_target | 1/256MiB，policy和Definition | 单unit缓冲；压力样本RSS，超过预算停手重设 |
| 19:30、Asia/Shanghai | ops.schedule的cron_expr=30 19 * * *及timezone | 现有scheduler生成意图；运营排程页可见；不在migration seed，启用另批 |
| delivery source/table/contract | Definition storage及Foundation交接合同v1 | writer/DG只读白名单；部署同时迁移；跨表/freq/未知版本拒绝 |
| 日期起点/截止 | 运行读取Prod库存/权威日历，冻结plan | planner；不新增env硬编码2010；首周/跨年/长假测试 |
| 索引DDL lock_timeout / statement_timeout | 15秒/15分钟，仅迁移186的独立autocommit连接 | concurrent索引创建前后查valid/ready/live和准确定义；无env/Settings/页面配置，迁移结束RESET；正式执行及EXPLAIN另验 |

现有全局Settings、Tushare token、PG连接来源不改。不新增.env配置或页面常量。DG资源和预算在DG LLD维护，避免两侧常量不同。

首次源约876首请求、最多每unit3页；实际短页通常1次。初次周捕获按基线2.9百万行，Raw+Serving约5.8百万行分unit提交。每unit读回只本范围；完整对账仅首次一次。20变化股票约17,020历史行加5,559新周行，约21首请求；实际完整范围和页数P0复核。交易日因子扫描≤前日+本周5日，不扫描全历史factor；日期覆盖缺失时不扩大查询。

## 7. Ops、TaskRun与页面派生

### 7.1 手动任务

继续使用现有dataset maintain入口、point/range、可选单值ts_code。新scope/执行token由后端生成和冻结，不让运营输入SQL、freq或checkpoint位置。重试原意图必须显示原时间/股票范围及已有完成量。

### 7.2 自动任务

复用P0查到的ops.schedule id=14（stk_period_bar_adj_week.maintain），当前active、每周五22:04；不新建重复排程。切换时单独获准暂缓此排程，校准为30 19 * * *、Asia/Shanghai和新时间策略后再启用，既有受理/并发去重/worker路径复用。新增时间策略只生成“最后已结束周”意图，resolver才决定source参数；当已有未闭合批时先恢复，同周闭合后不重复下载。源未完整当晚任务失败/待重试，下一日19:30恢复；不附加高频cron或后台等待。

P0已核验同dataset排程；id=13未复权周线排程保持原样，切换前重新检查是否新增写者。因子、日历、日线的正式写者保持，不顺手把它们塞进周线workflow。Prod依赖已完整业务数据，Ops观测仅辅助诊断；不能因快照状态写失败阻断已有事实读取。

### 7.3 TaskRun观测

阶段：规划、等待上游/源、下载新周、刷新股票历史、提交unit、闭合交付。unit_total冻结，unit_done只在持久化后增长，rows_committed按单层业务键数；另显示retained/unrefreshed计数，不算reject或刷新成功。

单次活动更新≤5秒、页面≤30秒可见；没有可靠串行样本时ETA“暂无法估算”。TaskRun与node终态同独立事务更新；状态写失败进入观测待核对，已有业务receipt仍是续跑依据。既有任务详情组件能否完整呈现需P2真实浏览器验收，不能仅保证后端有字段。

### 7.4 数据状态、卡片与freshness

表映射/Raw-backed/Serving、trade_date观测不变；历史价格修正不伪造新行情日期。DG交付水位只在对应任务详情呈现，不混入Prod周线freshness。现有snapshot重建只做必要回归，不每次刷新全量重建。

### 7.5 日期完整性审计

期望为有交易的自然周周五，实际按freq=week的trade_date。历史保留键不能被当作“本次源刷新成功”，但仍属于Raw实际存在数据。不新增每日周线完整性要求；无交易周允许no_trading_week闭合且无行情行。

## 8. 测试与门禁

### 8.1 必补测试

新增tests/test_stock_weekly_adj_refresh_plan.py、test_stock_weekly_adj_delivery.py、test_stock_weekly_adj_refresh_execution.py、web排程/手动任务/详情相关测试。W01—W12逐条关联独立expected值。

必含：月线/未复权不变、scope改动拒绝、SQL无删除、周中/两次除权/新股/停牌/长假、因子缺一天、满页终空页、重复键异值、请求失败非无源、旧值覆盖、partial保留、前后两层一致、源basis新但qfq仍旧、单发布者、进程退出、提交边界取消、计划恢复、业务commit后Observer抛错、closure前后退出、幂等、TaskRun/node一致、30秒进度可见及浏览器。

DG合同测试使用同一v1字面fixture，对日期/Decimal/NULL/摘要/unknown version做双侧金样本；不能由生产编码器反向生成expected。

### 8.2 必跑命令

实施阶段使用已有仓库环境，先确认测试路径及无正式资源访问，不自动安装。基础命令：

~~~bash
pytest -q tests/architecture/test_subsystem_dependency_matrix.py
pytest -q tests/test_dataset_definition_registry.py tests/test_dataset_action_resolver.py tests/test_dataset_unit_planner.py
pytest -q tests/architecture/test_dataset_runtime_registry_guardrails.py
pytest -q tests/architecture/test_dataset_codebook_guardrails.py
GOLDENSHARE_ENV_FILE=.env.web.local goldenshare ingestion-lint-definitions
python3 scripts/check_docs_integrity.py
git diff --check
~~~

专项测试名为拟新增，实施后再执行；Ops schema/策略/页面变更还需API与真实浏览器回归。只改文档的本轮不跑同步或definitions正式检查。

### 8.3 验收勾选

- [x] P0：当前connector多页和基准、逐日factor覆盖、Prod库存/索引及静态全消费者、专用交接必要性/容量技术评审（2026-10-10，§11）。
- [x] P1：Definition模型/Plan/builder/linter/模板、ORM/迁移源码/DAO、默认None消费者、三列键及freq回归；当前Definition绑定留P2，正式DDL待执行。
- [ ] P2：完整小样本行数链、取消/退出/续跑/幂等、观测失败、浏览器进度及source basis。
- [ ] P3：源刷新一次全量键/值对账，保留未刷新/失败分清，无删除。
- [ ] D2/D3/J1：DG实际接收、正确覆盖、正式事件/check、一次bootstrap对账及19:30端到端验收。

### 8.4 阶段完成记录

| 阶段 | 本轮结果 | 未完成/下步 |
| --- | --- | --- |
| 设计编制 | 业务决定、方案及LLD已完成并提交5e903556 | 原设计提交，不代表新机制已实施 |
| P0/D0 | 当前connector、Prod只读、静态消费者、交接技术评审及隔离DG事件/IO样本通过 | P1需落实§11列出的契约、恢复与索引；正式迁移/端到端写入未验 |
| P1 | 支持合同、持久化对象和迁移源码已实现，具体证据见§12 | 正式DDL、同事务行情金样本及执行路径绑定待P2；有一项既有月线测试失配 |
| P2—J1 | 未开始 | 因子/欠账执行、部署、写入、DG交付及自动切换未执行 |

## 9. 发布与回滚

1. 先完成P0与结构评审；P1迁移只新增专用交接对象和经EXPLAIN证明需要的索引，不清空/重建行情表。down_revision取实际head。
2. 小样本在获准环境完成后部署Prod，再加载DG新定义但保持新路径未启用；旧复权源自动分支在切换阶段停用，未复权和月线继续。
3. 获准执行Prod首次刷新、一次对账、DG bootstrap文件阶段、事件阶段；B0只有DG全部文件和事件就绪后才设为交付水位。两阶段不能顺手合并写入。
4. 正式计划和完整命令在执行前冻结，写明环境/范围/批量/取消/恢复；本LLD不捏造当前CLI已支持新策略或预填真实验收结果。
5. 验收SQL限定freq=week、选中代码/日期，核对源/标准化/Raw/Serving/交接payload键和值；月线及未复权分freq摘要作不变证据，不做全表深扫。
6. 回退停止新触发，保留已提交unit、交接和DG checkpoint，修代码后同意图恢复。不得删业务表/旧数据回滚；不得重新启用DG直拉复权作为双轨兜底。迁移降级不自动DROP有业务数据的交接表。

## 10. 本次交付快照

当前正式任务仍为旧的Prod维护及DG直拉新周；P1支持合同已实现，历史因子刷新、业务交接执行及DG统一来源尚未实现。下一步P2完成发布执行链和绑定，真实小样本、全量运行和启用按各阶段另获明确授权。

2026-10-10设计阶段历史记录：五份文档同步、完整性及20个设计链接/锚点检查通过；当时未运行代码测试或迁移。P1开发后的当前结果见§12，不用历史文档检查替代运行验收。


<a id="p0-d0-review"></a>

## 11. P0/D0只读核验及技术评审（2026-10-10）

### 11.1 范围与结论

本阶段按P0/D0完成静态消费者审计、真实源读取、Prod只读SQL以及临时DG实验。未改业务代码，未迁移、部署或写Prod；未启动正式DG任务、登记事件、改变sensor/排程或提升Lake文件。源请求共9次，生产SQL均READ ONLY、显式列与限定范围、statement_timeout≤30秒；隔离实例和候选全部位于/private/tmp，不接正式实例。

技术评审结论：保留一个专用业务交接表；首次不复制全历史payload，日常只保存本批变更值，DG不新增状态表或summary asset。只读样本支持当前行数、文件数和payload预算；P1需要补齐下列当前实现缺口。P0通过不代表新表实存、正式取消恢复或联合19:30已验收。

### 11.2 实测事实

| 项目 | 2026-10-10证据与结论 |
| --- | --- |
| Prod实际库存 | Raw freq=week为2,896,821行、858个trade_date，2010-01-01至2026-10-09；不是DG的2,902,386行。Raw缺2026-10-02，000001.SZ源历史有该周，首次刷新按实际源补齐；本轮未补写。 |
| schema/索引/head | 两行情表21列及映射一致；Raw只有主键，Serving已有日期索引；core.stock_weekly_adj_delivery不存在。DB与本地迁移单head均20261008_000184，P1生成迁移前再次核查。 |
| 当前connector分页 | 使用DatasetSourceClient→TushareSourceConnector→TushareHttpClient，无writer。000001.SZ、20260701—20260925：6000行上限基准13行，limit=10得到10+3，键/值精确相等；20260701—20260904得到10+0并终止。终空页HTTP200/code=0/data存在、21字段齐全/items=[]。 |
| 源字段/范围 | 显式21字段；000001.SZ、20100101—20261009为851行，所有end_date=20261009，单请求约0.306秒。20261009全市场5559行、约0.477秒，与该周实际日线代码并集相等、无少码/多码。延迟只为单次读取，不是写入或全量SLA。 |
| 归一化最小样本 | 取捕获的20260605一行，received=normalized=1、rejected=0；日期转date、数值转Decimal、change映射change_amount正常。未执行新writer，完整源—归一化—两层—交接链留P2。 |
| 日历及factor | 20260925休市，源factor至24日合理。24/28/29/30及1008/1009六个开市日日线股票因子缺失均0。1008变化6只、1009变化8只，去重并集14只；1009有1只无前值，不计因子变化。 |
| 独立价格基准 | 000001.SZ、20260605 bfq close=10.98，旧因子134.5794、当前142.0699，round(10.98×134.5794/142.0699,2)=10.40，与新源qfq一致；hfq=1477.68亦一致。Prod旧Raw/Serving的qfq仍10.98、end_date=20260521，证明该样本需刷新，不推论所有历史行都错。 |
| 交接容量 | 851行源值转字符串的JSON约333,816字节；850行数据库标准化21列JSONB表达式平均476.56字节。20股各851行+新周5559行约22,579行，外推10.76MB/周、559.5MB/年。表达式字节不等于新表含索引/TOAST的实际空间，P2需实存样本；不做全量payload副本。 |
| 既有排程 | id=14已active，每周五22:04，目标stk_period_bar_adj_week.maintain，时区Shanghai；日后复用并改为每日19:30，不另建。id=13未复权排程不动；本轮均未修改。 |
| DG隔离事件 | 安装版本Dagster 1.13.18；临时ephemeral实例，2历史分区+1anchor：成功run产生3物化、9检查，历史yield后可读目标storage_id，三项检查准确绑定。故意历史失败的run失败、无anchor，已发历史物化保留。仅验证正常run机制，未写正式事件。 |
| DG隔离IO | 正式文件只读：859文件、2,902,386行、158,233,993字节；临时候选改单股一个字段用于IO压力，涉及851文件、2,888,911行、157,493,398字节，约5.961秒、峰值RSS647.8MiB。每年最多272,685行/53文件。无正式replace、事件或远程传输，不能当联合交付耗时。 |

DG与Prod库存差5565行，正是DG已存在的2026-10-02周文件；重新bootstrap保留DG独有键并分类对账，不为行数相同删除旧键。此次没有全历史逐值审计，完整一次对账留P3/D3。

### 11.3 静态消费者与P1必须落实的接口

以下记录P0时的实现缺口；P1已落实的支持代码及仍留P2的接线见§12，不把本表的旧现状当作当前实现。

本轮CodeGraph使用explore核对resolver/执行链和来源链、search定位OpsSchedule；前轮impact覆盖request builder。动态注册、SQL及以下消费者均直接读当前源码。影响为Foundation ingestion、Ops意图/调度/观测及独立DG供数域；不新增子系统反向依赖，未接入Wealth消费者。图关系没有代替代码和真实数据审计。

| 消费者 | 当前代码及实施约束 |
| --- | --- |
| manual/catalog/workflow | ops/api/manual_actions.py、queries/manual_action_query_service.py、services/manual_action_service.py、action_catalog.py、catalog/dataset_catalog_views.py；preflight调用resolver时禁止持久化plan。原point/range/单值代码表单不加源参数。 |
| resolver/plan/source/write | foundation/ingestion/resolver.py、execution_plan.py、unit_planner.py、request_builders.py、source_client.py、executor.py、writer.py及DAO；新具名builder/write path必须注册并被linter识别，未知策略不得落通用fallback。 |
| 冻结/恢复 | ops/services/task_run_service.py::_freeze_announcement_payload当前拒绝其他数据集resume；必须增加周线具名受理/恢复策略，不挪用公告合同。retry保留原冻结意图，不能因人工点重试改变scheduled_week为manual_revision。 |
| 取消/观测timeout | ops/runtime/task_run_dispatcher.py当前把任何execution_context按公告storage.insert_lock_timeout_seconds取值；TaskRunIngestionContext随后拼成PG timeout。P1须按具名执行合同显式提取周线取消/观测预算，测试None/错误合同及公告回归；不能靠catch补丁或复制公告嵌套字段骗过调用方。 |
| 响应结构 | clients/tushare_client.py通用call会把data=None转[]；bounded_tushare_call.py亦如此。P1严格周线策略在监督边界校验原响应后才出rows。源码调用链为bounded helper→HTTP client→connector→source_client；测试含test_bounded_tushare_call.py、test_anns_d_stream.py、test_anns_d_exact_records.py及新周线正反例，迁移全部消费者而不改变公告现行语义。 |
| freshness/cards/snapshot/audit | queries/freshness_query_service.py、dataset_card_query_service.py、services/operations_dataset_status_snapshot_service.py、date_completeness_audit_service.py、dataset_observation_registry.py；继续按trade_date/freq=week判断覆盖，交接revision不进入行情freshness。 |
| 新排程策略合同 | foundation模型、ops/services/dataset_schedule_time_policy_resolver.py、schedule_automation_capability_resolver.py、operations_schedule_service.py、schedule_planner.py、schemas/catalog.py；同步新增latest_completed_calendar_week类型/校验/执行，既有month分支回归。 |
| 前端消费者 | frontend/src/shared/api/types.ts及pages/ops-v21-task-auto-tab.tsx同步排程类型与展示；ops-v21-task-manual-tab.tsx沿合同派生周日期控件；ops-task-detail-page.tsx和ops-task-detail-eta.ts需P2验证实际进度和ETA，不用页面常量自行换日期。 |
| DG真实入口/测试 | asset/check/job、mixed weekly sensor、run config、Prod白名单及bootstrap均见DG A2。D1覆盖test_stock_weekly_contract/prod_source/candidates/history/events/definitions、test_raw_stock_weekly_update_job_sensor与static gates；现有update/source/monthly/period_checks作为不受影响回归，不把P0实验当这些实现已通过。 |

P1验收必须新增：preflight零DML、执行受理后持久化；正常空响应与data缺失反例；无缺列/重复列/短行混入；周线恢复合同及原公告不变；独立观测timeout合法且状态失败不阻断业务；同事务Raw读回payload精度金样本。源监督硬截止、取消及业务提交恢复仍在P2真实样本中验，不由本轮快速connector请求替代。

### 11.4 实验边界与后续

DG每年独立连接并关闭后再处理下一年，峰值RSS从同连接累计年度中间结果的898.7MiB降至647.8MiB；DuckDB512MiB是引擎内存预算，不是整个Python进程上限。DG LLD将进程RSS设计上限明确为1GiB，正式运行仍需监测。所有临时候选已清理，正式源文件大小和mtime未变。

首次IO实验参数顺序错误使COPY误指向正式路径，沙箱阻止写入；已核对无误写文件，改为固定/private/tmp目标且只绑定读取路径后重跑通过。没有扩大权限或执行正式提升。临时SQL/JSON/脚本只是本轮证据，不进入reports、代码或日常运行依赖；关键结果已落在本节。

P0完成时的下一阶段为P1；该切片当前结果见§12。建表、建索引、加载正式代码、全量下载/bootstrap、B0迁移及19:30切换继续按阶段授权。

<a id="p1-implementation"></a>

## 12. P1实现与计划对账（2026-10-10）

P1已完成支持合同和持久化对象的代码切片。`market_equity.py`当前注册的复权周线仍为原write path、`weekly_adj_policy=None`，正式排程不变。P2完成因子/欠账规划、有界抓取及发布器后，再一次性绑定新Definition，避免现有任务调用尚未实现的writer；这不是运行开关或旧新双轨。P1未执行正式建表/索引、部署、行情写入、DG事件或sensor切换。

### 12.1 硬口径、实现和验证

| 硬口径 | 当前代码 | 测试/阶段边界 |
| --- | --- | --- |
| 仅复权week、固定21列、三列键；其他数据集默认None | datasets/models.py、stock_weekly_adj_contracts.py、definitions/_builder.py、ingestion/linter.py；PlanWriting投影delivery字段 | 新P1测试的绑定、month/并发/孤立字段反例、builder转换；注册库回归及ingestion-lint通过；live绑定待P2 |
| 不去T、不填NULL、不经float改写源值 | canonical_source_rows保存date/Decimal字符串，按键排序、同值去重、异值报错 | 精度、NULL、T600018.SH、溢出/非有限/float/异值反例；同事务Raw/Serving读回金样本待P2 |
| preflight零业务DML；恢复原意图 | execution_scope → stock_weekly_adj_scope；resolver先冻结再规划；TaskRun受理仅保存execution_context | session execute/add/commit均无调用；变更范围/预算/intent/token拒绝；显式resume同dataset已停止任务；计划业务记录仅P2执行器获得发布锁后追加 |
| 冻结源/规划/存储/归一化/质量/事务和预算 | policy_snapshot含具名policy，planning不重复放policy；contract_digest、scope_hash、intent_digest绑定UUID及原触发意图 | JSON往返与稳定unit_id、单字段篡改反例；Plan.trigger_source保留当前调用来源，execution_context.trigger_source保留原来源 |
| 全市场range逐周，单股range一次区间请求 | stock_weekly_adj_refresh具名unit builder复用已实测参数builder；unit_id含版本/batch/scope/kind/实际参数 | 原point不能误传history；1000unit上限及合同字节超量在请求前拒绝；自动因子名单、欠账优先和紧凑业务plan留P2 |
| 不挪用公告合同 | execution_scope按具名策略分派；公告快照只含公告字段，排除新增周线默认字段 | 公告冻结/恢复、stream/exact records/API回归；两合同观测timeout分别显式提取，普通None不启用独立timeout |
| 交接只追加、幂等冲突不覆盖、DAO不commit | StockWeeklyAdjDelivery ORM、独立DAO、DAOFactory；唯一(batch,kind,unit)，PG防UPDATE/DELETE trigger | SQLite隔离追加/同值重放/异值拒绝/rollback/读回；PG迁移离线SQL验证。正式PG约束执行及Raw+Serving+receipt原子事务留P2 |
| 首次不存全历史副本，日常保存本批值 | plan/unit/closure类别、源行payload和bootstrap摘要合同；DAO限制行数/字节、闭合清单1000/控制头4KiB/整批256MiB | 日常精度/行数/摘要一致性与超量反例；bootstrap摘要、源保留键分类和实际批累计由P2 publisher补齐 |
| sensor只读闭合头；job才流式取unit | DAO.next_closed_header投影payload.header，按revision LIMIT 1；iter_units限1000、yield_per=1 | 顺序、小投影及非法范围测试；读闭合批一致性、只读白名单和DG消费者留D1 |
| 正常空页必须结构完整 | bounded_tushare_call监督进程内通过response_contract=stock_weekly_adj/v1校验原envelope；HTTP client只允许对应API/freq/fields | loopback真实子进程：完整空页通过，缺data/缺列/重复列/短行拒绝；month/其他API零请求拒绝；公告传输保持原合同。周线source_client/executor接线留P2 |
| 19:30只生成周意图，不证明源已发布 | Foundation候选周helper；Ops策略resolver/planner/service、catalog API类型；前端仅类型/中文摘要 | Fri19:29/19:30、周末、UTC/naive反例；固定日期和未声明month拒绝；前端单测及浏览器回归。新周期完整性/正式排程切换留P2/J1 |
| 仅新增专用表和必要Raw部分索引 | 迁移185新增表/trigger，186独立concurrent索引；Raw ORM同步；不增加Serving索引 | 开发前单head184，源码链184→185→186；离线SQL无清空/删除/重建行情。失效或同名异定义索引停止，不自动DROP；正式DDL、空间和EXPLAIN留后续 |

新增源码集中在Foundation合同、scope、DAO和ORM，现有resolver、planner、dispatcher、TaskRun受理及排程类型同步消费；不改变子系统依赖矩阵，Foundation没有Ops/Biz/App反向依赖。CodeGraph explore/query/impact覆盖Definition/Plan、resolver/planner、TaskRun、排程、call_bounded→connector→source_client→公告stream及测试；动态注册与前端/API消费者另外读代码核验。同步索引后再查状态；图不能证明实际数据库提交。

### 12.2 验证及限制

后端相关回归457项通过、23项跳过；1项失败是既有`test_planner_compresses_trade_dates_to_month_end`仍调用已删除的`_compress_to_month_end`，开发前HEAD也无该方法，本轮未恢复旧实现。跳过项需要隔离PostgreSQL配置，不能算通过。最后补强持久化预算和合同校验后，P1/注册库/架构专项101项通过；此前有界传输/P1/公告相关回归95项通过、23项跳过；最终有界HTTP子进程14项通过，cards/freshness/日期审计及能力消费者53项通过。这些测试组有重叠，不相加作唯一测试数。

前端151项单测通过；typecheck、check:rules、build通过；自动任务页3项既有Playwright冒烟/视觉用例通过，全部API mock。构建保留既有大chunk提示；未改bundle设计。Definition lint通过；新增合同/迁移/DAO文件ruff检查通过。文档完整性、本轮11个新增链接/锚点及git diff --check通过；CodeGraph sync/status确认索引最新。这些检查不作为正式业务验收。

SQLite和离线PG DDL只证明代码形状，尚不能证明正式trigger、并发锁、实际索引收益、TOAST空间或三表提交。P1默认支持不会自动创建正式对象或开始刷新；当前调度和DG仍沿既有逻辑运行。

### 12.3 下一步P2

实现自动欠账及逐日因子变化规划、单发布锁、紧凑plan持久化、原批续跑、源完整性/复权基准、监督抓取接线、Raw/Serving/交接同事务publisher、批闭合及独立观测；最后绑定注册Definition，清零该数据集旧写入口。先隔离取消/退出/恢复/幂等测试，再列出可审查的正式迁移和最小运行清单，按阶段授权执行。DG D1读取合同以§5.4为唯一来源；全量刷新/bootstrap和19:30启用仍不属于本轮执行范围。
