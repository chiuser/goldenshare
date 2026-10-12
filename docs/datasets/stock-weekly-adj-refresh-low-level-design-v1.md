# Prod 股票复权周线刷新代码级 LLD v1

起草：2026-10-09；更新：2026-10-12。状态：P0/D0完成，P1已提交7d32163d，P2已提交018168fc，日期纠偏及PG/Ops验收已提交12f5ddde。内存优化已提交cc7c528e，依据现有验证及管理员决定收口，不再追加专门复测或优化：业务执行的单进程峰值达到原256MiB目标，同时进程树总量另列，见§13.7。管理员已部署cc7c528e；正式迁移到186及表/trigger/索引只读核验通过，正式双周15368及两只单股历史15375/15378的21字段对账通过；15378采样观察到父/源进程均低于256MiB，取消续跑、同批零请求重放及页面验收留到全量执行前合并完成，不阻断DG D1/D2开发，见§13.9—13.12；未执行全量刷新或DG切换。本文件按 [Prod 数据集开发模板](../templates/dataset-development-template.md) 的0—10节复制结构并填写；模板提示文字不作为项目内容重复保留。

业务范围和阶段以 [方案](stock-weekly-adj-refresh-plan-v1.md) 为准。DG实现仅引用本文交接合同，其余见 [DG LLD新增阶段](../../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#adjusted-weekly-prod-refresh-lld)。当前实现以§13为准：源码注册Definition已绑定新规划/发布路径，管理员部署后正式表及索引已创建并只读核验；首个两历史周正式任务已对账通过；其他正式验收、首次全量收尾和DG接收链待完成。§12保留P1提交时的历史状态。

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
| 执行unit | 首次全市场range按周；收尾再次提交全范围range冻结独立补刷批，含新完整周/变化代码历史，允许0-unit；指定代码range保留一个区间；自动point生成新周及变化代码历史区间 | §4.4.1、§6.2、§13.15；range不是清空；两批不合并原计划 |
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

下表为设计时的追溯清单；P1/P2当前落点及已验证/未验证边界分别见§12、§13，不能把设计测试名当作通过证据。

| ID | 硬需求/代码落点 | 正向测试 | 反向测试 | 真实验收/阶段 |
| --- | --- | --- | --- | --- |
| W01 | 仅week；Definition、writer、交接白名单 | 周线更新 | month/未复权键不变、跨频拒绝 | 两表分freq摘要，P1/P3 |
| W02 | 不清空；upsert及旧键差集 | 同键新价格覆盖 | 空/缺键不删除；请求失败非无源 | 源/写入/保留键，P2/P3 |
| W03 | 按日因子并集；weekly_adj_scope | 周中除权、跨周欠账 | 同周两次变化不漏；新股缺前值不误报 | 已知20260612/20260924样本，P0/P2 |
| W04 | 新周及单股历史unit；planner/builder | 1+K请求 | 禁止股票×周；未结束周拒绝 | 实际参数/页序列，P0/P2 |
| W05 | 21字段全链；source/normalizer/DAO | 默认/显式/关键字段一致 | freq缺失/冲突键/超精度阻断 | 源/标准化/Raw/Serving，P2 |
| W06 | 业务完成/交付独立于Ops；§5.4 | commit后可恢复和被DG读取 | 进度/终态写失败不回滚行情 | 注入观测失败，P2/J1 |
| W07 | 长任务有界与取消；executor | unit提交后递增、恢复幂等 | 半页/退出不判完成；取消不领新unit | 运行—取消—恢复—读回，P2 |
| W08 | 因子值与价格一致；validator | 旧日期但目标因子相同、价格正确也通过 | 新日期但价格旧、目标因子不同/混基准仍pending | 独立close样本校验，P0/P2；修正见§13.6 |
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

P2源码已绑定具名write_path=raw_core_upsert_with_delivery及delivery_dao_name/delivery_table，默认None，不改变其他write path。该路径只允许具名weekly_adj_policy、unit提交、单并发及本freq；linter明确禁止用于month或其他dataset。observation/stage/replacement_scope保持不启用，不借用fund_daily观测表、公告checkpoint或staged_stream语义。

### 4.7 planning

universe_policy=no_pool；不以在市池裁掉历史。P2源码unit_builder_key=stock_weekly_adj_refresh；offset_limit/page_limit=6000；fetch_concurrency=1；buffer_all仅缓冲单unit，max_source_rows_per_unit=12,000。

已新增并绑定planning.weekly_adj_policy，类型WeeklyAdjExecutionPolicy，存于Foundation具名合同文件；其他Definition默认None。策略冻结源/日期/字段/存储/预算；executor通过注册策略消费，禁止在通用主链按dataset_key散落分支。当前announcement_scope.freeze_execution只支持公告，不能强塞周线execution_context。

P1修改模型/builder/linter/Plan投影时同步校准原数据集模板，注明当前支持的新增字段；本轮不把未实现枚举写成模板现行能力。

### 4.8 normalization

沿用date_fields=(trade_date,end_date)、全部17数值字段Decimal、required=(trade_date,ts_code,freq)、_stk_period_bar_adj_row_transform。Raw历史可选NULL保留；本周新增及非bootstrap修正的qfq核心字段/基准缺失列为未完成刷新原因。不得重命名Raw、去T或自动合并股票身份。

### 4.9 capabilities

maintain的manual/schedule/retry保持True，supported_time_modes=(point,range)。源码已声明schedule_time_policy=latest_completed_calendar_week，输出point/trade_date；合法策略类型、Ops解析/运行时及API/前端消费者已同步。正式排程尚未更改，不能因源码已支持而默认启用。

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
| intent / unit_kind | JSONB / VARCHAR(24) | mode、原trigger_source、bootstrap布尔值和intent_digest；point_week/stock_history等具名unit |
| cutoff_week / start_date / end_date / ts_code | DATE/DATE/DATE/VARCHAR(16)可按kind为空 | 源周期截止/历史窗口/原始股票代码 |
| factor_scan_start / factor_scan_end / factor_target | DATE/DATE/NUMERIC(20,8)可空 | 扫描覆盖窗与股票因子目标；不能靠全局 MAX(date)证明覆盖 |
| outcome | VARCHAR(32) | published/source_empty_preserved/partial_source_preserved/no_trading_week；网络/权限失败不能写成preserved成功 |
| payload | JSONB | plan的有界unit清单，或日常unit的21列标准化行情；bootstrap unit只摘要，不存全历史副本 |
| rows_received / rows_unique / rows_written / rows_preserved | BIGINT，非负 | 明確区分源、去重、写入、保留；rows_written是每层业务键数，不把Raw+Serving相加 |
| basis_date / payload_digest / scope_digest | DATE可空 / VARCHAR(64) / VARCHAR(64) | 本unit基准及本次传输完整性；不是永久历史hash门禁 |
| reason_summary | JSONB，有界 | 原因/计数/≤20展示样本、单元预算内的完整preserved_keys及基准样本；不含token/SQL凭证 |
| published_at | TIMESTAMPTZ | 业务提交记录时间，不用它代替revision水位 |

plan只保存共享合同/预算/原意图一次；unit清单保存稳定ID、进度上下文及已由request builder生成的少量实际参数（freq、日期、可选单代码）。不逐unit重复Definition、policy、fields或源行；恢复使用冻结参数，不能以当前请求重新推断历史unit。P0按此合同构造1000个stock_history unit的容量示例为224643字节，小于1MiB；这是拟定序列化形状的估算，不是已实现planner测试，P1还须对真实冻结对象校验上限并测试超量拒绝。

固定dataset/freq由表合同及CHECK约束表达；不让调用方透传表名/freq。索引：(record_kind,revision)、(batch_id,record_kind,unit_id)；payload限制8MiB/每unit12,000行情行，plan≤1MiB/1,000unit。日常整批payload总量上限256MiB，与DG一致；闭合头记录总行数/总字节、本批实际输入的最大周max_input_week（空行批为null）、零行原因和unit集合摘要，最多1000个unit ID且头控制投影≤4KiB，不传整份清单给sensor。

规划根据历史窗口周数、当前对象规模及标准化字段长度上界预估总量；超过unit/字节预算先拒绝，不开始源请求。当前批写入时累加实际payload字节，再次超限不提交当前unit/不闭合。需另获批准分范围处理或调整经过实测的局部预算，不设计自动分组状态机。未闭合的已提交unit仍可读回、恢复，不能在新意图下跳过。factor frontier只有整个原扫描范围完成后才推进，不用某一手动子任务冒充全周完成。

**提交与恢复算法。**

1. 现有TaskRun受理意图；Foundation将范围、字段/预算版本、期望unit和因子窗冻结为plan业务记录；冻结失败时尚未写行情。
2. 单数据集PG advisory session锁保证一批只有一个发布者，覆盖本批源捕获及多个短事务；锁键只属week adjusted，不锁月线。所有入口必须接入该发布者，不允许旧writer绕开。取消/进程退出自动释放连接锁。
3. 每unit先查同batch/unit已提交记录；有则核验scope后恢复，不重复请求。不用TaskRun unit_done跳过。
4. 拉取、校验、归一化后，一个短事务upsert Raw、Serving并append unit业务记录；提交失败三个均不可见。业务交接是交付数据本身，不是Ops观测。
5. 提交后独立写进度/node/Issue；写失败只记录观测问题，不能回滚、停止领取本批其余已获准业务unit或误报单位未提交。源/业务错误才决定本批停止。
6. 所有冻结unit有对应终结业务结果、范围和值读回通过后append batch_closed。失败/取消/未就绪不产生closure，续跑原batch；partial_source_preserved需记录缺键集合并确认返回部分的价格基准有效，不能把当前全市场缺码列为正常闭合。
7. 首次历史批对账结果以audit:{source_unit_id}的bootstrap unit摘要逐条持久化，闭合头bootstrap_reconciled=true；不计入源unit_ids/行情数量。运营再次提交覆盖原范围的maintain，冻结独立补刷plan，关联原闭合批。第二批对账及基准核验通过后append bootstrap_closed，记录实际库存边界、父闭合身份和B0；0-unit批也持久化plan/closure/B0。B0前中断的第二批仍算未完成计划，不允许新意图跳过。详细算法见§13.15；原源unit只有摘要及保留键摘要，不存永久历史副本。

**payload精度及版本。** 日常payload保存提交后的标准化21列，日期YYYYMMDD，decimal以字符串保存，NULL保留，固定键排序；摘要基于canonical row encoding。交接payload与Raw/Serving在同事务验证一致；不直接把未经归一化的原始JSON当正式数值。闭合头列出有界unit ID集合/数量及摘要，DG只能读取属于该闭合批的unit；不得用当前Raw替换旧批payload。

**读取合同。** DG用唯一远程包装脚本的只读事务，头查询只投影revision/batch_id/cutoff/合同版本/数量/摘要；payload仅在运行job内按unit流式读。既有原bootstrap白名单只含行情表，必须新增交接表显式白名单，不能SELECT *或任意schema扩权。DG不写交接表，不存回执到Prod；交接记录不进入行情Parquet。

**保留与退出。** 交接payload是可重放业务增量，不是搬运证明；日常只读未交付批次。本轮851行样本将数值转字符串后，JSON约333,816字节，约392字节/行。外推新周5559行加20股票各851行约8.86MB/周；P0另测850行标准化JSONB表达式平均476.56字节，外推约10.76MB/周、559.5MB/年，尚未计新表索引、控制记录及实际TOAST压缩，不使用源矩阵146字节/行低估对象payload。不设计自动DELETE、归档服务、永久全历史复核或reports依赖；清理需确认DG水位、保留窗及另获明确清理授权。停机超过可读取范围时走受控bootstrap，不假装cursor可以重建丢失payload。

## 6. Ingestion实现设计

### 6.1 请求构造

_stk_period_bar_adj_week_params按unit自身归一化时间格式化：point只trade_date；stock_history只ts_code/start_date/end_date；freq固定week；fields始终来自Definition。builder不读数据库、不选日期、不拼变化代码。不能因为原request是point而把history unit再次发成point。

### 6.2 Unit规划

已实现：stock_weekly_adj_scope.py负责纯冻结/稳定ID；stock_weekly_adj_planning.py负责只读resolve_weekly_adj_units和load_changed_codes；stock_weekly_adj_delivery.py负责validate_weekly_adj_source_basis与发布。注册unit builder，不直接复用_stk_factor_pro私有函数或公告freeze函数。freeze_weekly_adj_execution只生成纯计划/冻结上下文；manual preflight、预览和resolver.build_plan禁止DML。TaskRun受理后，执行器取得发布锁才持久化业务plan。

自动扫描范围：(上次闭合factor_scan_end，本次已结束周最后开市日]，每个d与前一开市日比较，取并集；先校验每日期覆盖及相邻值。范围最长一个待处理周，遇长停机按最早周恢复；raw最早日期按变化代码一次GROUP BY，不逐代码SQL。新股无前日行分类为首次出现；有历史却缺相邻因子列pending。

unit_id=hash(contract_version,batch_id,unit_kind,ts_code,规范时间窗,scope_digest)，同冻结批恢复稳定。progress_context保存中文阶段、当前代码/周、窗口、unit序号；不可全量放进cursor或TaskRun摘要。

首次按周约876unit，上限1000；自动1+K，上限1000及整批payload256MiB。超限在计划冻结前明确报预算错误，显示完整待处理范围，等待获准调整范围或局部预算；不自行拆自动批次、不推进factor frontier。首次期间的因子补刷另冻结独立批，原批单元不增加；详情见§13.15。

### 6.3 Source Client与分页

评估复用source_client分页迭代，增加受具名策略控制的调用监督/取消/预算；不能把公告的专用policy对象当周线policy。源请求在可终止子进程，硬截止20秒，正常页前后检查取消，≤2秒查询独立取消；本地隔离替身证明超时/终止及不泄漏token。

一个unit最多3页/12,000行，源响应和normalizer结果都计入256MiB RSS目标；首次全部876周不常驻内存。满页继续拉，超量整unit不提交。每页持同fields/筛选；若同一股票历史出现不能解释的多个basis factor，停止重取该unit而非接受混合基准。connector实测见0.3.0及§11。具名周线响应策略在监督进程内保留并校验envelope：code=0、data对象、完整且不重复的21字段、每行长度一致，才允许rows空。data缺失、字段缺失/重复或结构错误必须报weekly_adj.source_payload_invalid，不能写成source_empty_preserved；全市场完整性另验，正常空页也不自动等于可闭合空批。P1已实现监督进程内具名响应策略，P2 source_client已接线；周线JSON数值以Decimal解析并校验数据库精度，公告既有策略保持。

### 6.4 Normalizer

沿用现有Decimal/date/row transform；补scope和batch-key冲突验证。同键同值去重计数，同键不同值报weekly_adj.source_key_conflict；空、越界、缺主键、NaN/Infinity、精度溢出不静默截断或填0。不强制修订历史原始异常；旧键保留的原因独立记账。

### 6.5 Writer

已新增ingestion/stock_weekly_adj_delivery.py，具名路径内完成范围验证、分层upsert、payload标准化和交接append；通用writer注册分派，保留其他路径行为。核心接口publish_unit(writer,definition,unit,batch,context,check)->unit receipt；publish_closed_batch只在冻结unit闭合后调用。Raw/Serving upsert后，在同一短事务中按本unit实际输入键读回Raw显式21列，校准Serving映射并生成canonical payload，之后append交接；禁止用未经数据库精度校准的源float生成交付事实。读回不扫描未选历史。

cancel-before-commit回滚该unit，commit-after-cancel仍按实际完成记录恢复，不能宣称没提交；每个unit之后检查取消，不领新unit。独立Observer调用不能把已提交unit再次记为失败；当前_process_fetched_unit/report_progress交互需正反回归，不仅补异常catch。

### 6.6 结构化错误与codebook

拟新增weekly_adj.scope_mismatch、source_key_conflict、source_payload_invalid、source_not_ready、basis_not_updated、factor_coverage_missing、row_budget_exceeded、delivery_contract_mismatch、writer_busy、source_empty_preserved、partial_source_preserved、business_deadline_exceeded。每码在codebook登记中文含义、阶段、可重试性、样本和动作。超时/网络/认证/限流沿现有分类；“未刷新”不是网络失败的别名。

基准验收使用股票当周实际最后交易日，而不是周五标签作为实际成交日。旧历史周close用该交易日因子和源basis_date因子独立核对至源价格精度；周中除权的OHLC不能用整根周K同一个因子替代日内复权聚合。不得因basis_date早于行情周或刷新截止日直接拒绝。因子变化单股必须将源基准因子与冻结factor_target比较，不以日期相等作为比较前提；日期较早的其他股票，比较本批截止范围内实际最后交易日的因子，bootstrap中的退市股不要求存在当前市场日期的日线/因子。已知价格或目标因子不符仍拒绝；缺少独立依据时，bootstrap源值保留并记录未验证，日常必要核验保持factor_coverage_missing，不误称价格错误。

实现先选既有最多20个常规股票样本，并额外选本unit日期较早的全部股票与因子变化单股。每只选一条旧周close，单股历史不逐周重新读Daily。Daily只读这些代码：当周最后成交日，以及需要目标因子时截至本批范围的最后成交日；利用现有代码/日期主键ORDER BY DESC LIMIT 1。每128只组成一次SQL、Factor所需主键也按有界批次读取，避免每股票独立网络往返；没有新配置项。候选、返回和内存均受原12000行unit预算约束，数据库仍使用原20秒单元总截止和取消检查，不提高预算。只核验本次范围，不增加全历史永久对账、stock_basic依赖或退市白名单。

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

当前测试为tests/test_stock_weekly_adj_p1_contracts.py、tests/test_stock_weekly_adj_p2.py、tests/test_bounded_tushare_call.py及Ops/前端合同回归；实际代码点与结果见§13。W01—W12逐条关联独立expected值；DG专项仍待D1/D2。

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

专项路径与已跑结果见§13；Ops schema/策略/页面需合同与浏览器回归。静态lint、mock浏览器和隔离数据库测试不替代正式业务验收。

### 8.3 验收勾选

- [x] P0：当前connector多页和基准、逐日factor覆盖、Prod库存/索引及静态全消费者、专用交接必要性/容量技术评审（2026-10-10，§11）。
- [x] P1：支持合同/Plan/builder/linter/模板、ORM/迁移源码/DAO、默认None消费者、三列键及freq回归；已提交7d32163d，正式DDL待执行。
- [x] P2开发与隔离验证：因子/欠账规划、有界抓取、单元原子发布、续跑、观测及源码Definition绑定；不代表下一项真实验收已通过。
- [ ] P2：完整小样本行数链、取消/退出/续跑/幂等、观测失败、浏览器进度及source basis。
- [ ] P3：源刷新一次全量键/值对账，保留未刷新/失败分清，无删除。
- [ ] D2/D3/J1：DG实际接收、正确覆盖、正式事件/check、一次bootstrap对账及19:30端到端验收。

### 8.4 阶段完成记录

| 阶段 | 本轮结果 | 未完成/下步 |
| --- | --- | --- |
| 设计编制 | 业务决定、方案及LLD已完成并提交5e903556 | 原设计提交，不代表新机制已实施 |
| P0/D0 | 当前connector、Prod只读、静态消费者、交接技术评审及隔离DG事件/IO样本通过 | P1需落实§11列出的契约、恢复与索引；正式迁移/端到端写入未验 |
| P1 | 支持合同、持久化对象和迁移源码已实现，具体证据见§12 | 正式DDL、同事务行情金样本及执行路径绑定待P2；有一项既有月线测试失配 |
| P2 | 代码及隔离验证已完成，见§13 | 正式PG锁/迁移/源到三表真实小样本验收待执行 |
| P3/D1—J1 | 未开始 | 全量及捕获期因子补刷/B0收尾、DG接收/覆盖/事件及自动切换未执行 |

## 9. 发布与回滚

1. 先完成P0与结构评审；P1迁移只新增专用交接对象和经EXPLAIN证明需要的索引，不清空/重建行情表。down_revision取实际head。
2. 小样本在获准环境完成后部署Prod，再加载DG新定义但保持新路径未启用；旧复权源自动分支在切换阶段停用，未复权和月线继续。
3. 获准执行Prod首次刷新、一次对账、DG bootstrap文件阶段、事件阶段；Prod在一次全量对账及捕获期因子补刷完成后形成B0；DG只有全部文件和事件就绪后，才将该B0初始化为消费水位。两阶段不能顺手合并写入。
4. 正式计划和完整命令在执行前冻结，写明环境/范围/批量/取消/恢复；本LLD不捏造当前CLI已支持新策略或预填真实验收结果。
5. 验收SQL限定freq=week、选中代码/日期，核对源/标准化/Raw/Serving/交接payload键和值；月线及未复权分freq摘要作不变证据，不做全表深扫。
6. 回退停止新触发，保留已提交unit、交接和DG checkpoint，修代码后同意图恢复。不得删业务表/旧数据回滚；不得重新启用DG直拉复权作为双轨兜底。迁移降级不自动DROP有业务数据的交接表。

## 10. 本次交付快照

工作区源码已实现Prod因子刷新及业务交接执行，并绑定新Definition；正式环境未迁移/部署，DG仍沿既有供数链。P2真实小样本待验，P3全量/捕获期因子补刷/B0收尾、D1/D2接收与J1启用分阶段推进，不能用本轮隔离通过代替正式完成。

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

以下记录P1提交7d32163d时的状态，不代表P2之后的当前源码。P1已完成支持合同和持久化对象的代码切片。`market_equity.py`当时注册的复权周线仍为原write path、`weekly_adj_policy=None`，正式排程不变。P2完成因子/欠账规划、有界抓取及发布器后，再一次性绑定新Definition，避免现有任务调用尚未实现的writer；这不是运行开关或旧新双轨。P1未执行正式建表/索引、部署、行情写入、DG事件或sensor切换。

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

### 12.3 P1交付时的下一步（当前结果见§13）

实现自动欠账及逐日因子变化规划、单发布锁、紧凑plan持久化、原批续跑、源完整性/复权基准、监督抓取接线、Raw/Serving/交接同事务publisher、批闭合及独立观测；最后绑定注册Definition，清零该数据集旧写入口。先隔离取消/退出/恢复/幂等测试，再列出可审查的正式迁移和最小运行清单，按阶段授权执行。DG D1读取合同以§5.4为唯一来源；全量刷新/bootstrap和19:30启用仍不属于本轮执行范围。


<a id="p2-implementation"></a>

## 13. P2开发、隔离验证及真实验收待办（2026-10-10）

### 13.1 当前状态与调用链

P1已提交7d32163d，P2已提交018168fc。P2源码已完成因子/欠账规划、有界源抓取、单元原子发布、批闭合、取消续跑及任务详情展示。注册Definition一次性绑定新策略；仅复权week，月线及未复权入口保持原行为。没有执行正式迁移185/186、加载正式代码、写Prod、DG任务/事件或排程变更。

当前链路：DatasetActionResolver纯冻结＋业务只读规划 → DatasetUnitPlanner消费冻结business_plan → IngestionExecutor具名策略分派 → stock_weekly_adj_execution单发布锁/源捕获 → DatasetWriter具名路径 → Raw与Serving upsert＋输入键21列读回＋unit receipt同事务提交 → 全部unit完成后batch_closed。Ops只消费ProgressSnapshot，经TaskRunQueryService的typed weekly_adj_progress投影，由现有任务详情页渲染；页面不自行推导数据事实。

这次没有新增全局配置、worker、lane或通用状态平台。CodeGraph explore、impact用于executor/resolver/planner/writer、共享进度合同、TaskRun查询/API及前端消费者；动态注册、SQL和事务边界另读实际源码确认，收尾执行sync/status。依赖矩阵不变，Foundation没有Ops/Biz/App反向依赖。图和mock测试不能证明正式PG连接、锁或真实任务终态。

### 13.2 硬口径到代码与测试

| 口径 | 实现落点 | 已有验证与边界 |
| --- | --- | --- |
| W01/W04：仅week，1新周＋K单股全历史 | market_equity、unit_planner、stock_weekly_adj_planning及原request builder；各unit使用自身日期参数 | P1合同及P2规划/越界反例；month键原样保留；无股票×周展开 |
| W03：按日因子并集，停牌不漏，新股不误判 | load_changed_codes扫描前日＋本周全部Factor代码；同周变回旧值也计变化 | 两次变化、新上市、停牌有Factor无Daily、缺一天Factor测试；只对缺相邻Factor的疑似首次代码查询旧Daily，不查全市场日线历史；变化代码Raw起点一次GROUP BY |
| W02/W05/W08：源21列、Decimal、范围及基准 | bounded_tushare_call周线专用Decimal解析；capture_unit全列/精度/冲突；publish_unit范围和独立close因子样本 | 同值/异值重复、越界、超精度、缺字段、HTTP失败、基准新但价格旧反例；NULL历史按源保留，本周qfq核心NULL拒绝；独立样本不足则不提交 |
| W06/W07：单元事务及状态独立 | stock_weekly_adj_execution、writer、stock_weekly_adj_delivery、DAO；业务事务累计20秒，锁等待2秒 | SQLite物理Raw/Serving/receipt读回；Serving故障全部rollback；提交前取消rollback，提交后取消保留；观察写失败继续业务；真实隔离PG锁/事务deadline已通过，正式环境待验，见§13.5 |
| W09：先恢复原批，再最早周欠账 | resolver恢复原requested_scope/run_profile；只读查oldest_unclosed_plan；执行器锁后append plan；稳定unit_id及receipt | SQL监听确认preflight零DML；手动range被自动恢复仍保留原意图；进程退出后跳过已提交单元/零重复请求；第一条可见进度恢复已提交计数，未从0倒退 |
| W07：页/行/内存有界及取消 | source_client独立周线分页，监督子进程20秒硬截止/取消查询2秒/活动5秒；单unit6000×最多3页、最多12000行 | 真HTTP loopback子进程结构/取消/硬截止/精度测试；整批256MiB/计划1MiB超预算源请求前拒绝；业务单元累计deadline过期回滚已flush但未commit的Raw；实际发布累计字节再验。RSS256MiB仍需真实大单元运行实测 |
| W10：完整周及长假 | latest_completed_calendar_week策略；每日意图由resolver选择最早欠账；无交易周不请求源、不造行 | 19:29/19:30、未来周、无交易周零源请求与合法零行闭合；正式cron/id=14尚未修改 |
| W11：一次bootstrap、日常只本批 | metadata/intent.bootstrap独立布尔值，首次全范围unit仅summary；bootstrap后手动历史修正也保存本批rows | 不以historical_refresh模式推断“可以丢payload”；源缺键完整保留台账但不称已刷新；本次输入键Raw/Serving读回，没有永久历史扫描/reports输入 |
| 可读进度和ETA | runtime.weekly_adj → TaskRunWeeklyAdjProgress → OpsWeeklyAdjProgress | backend typed投影与前端单测；Playwright mock轮询下载→历史刷新、1/2进度、范围/保留量、更新时间及“暂无法估算”，≤30秒、无横向溢出/console错误/失败请求 |

新周门禁读取权威Calendar、Tushare Daily实际代码并集及逐日Factor覆盖/相邻值；当前完整周或自动欠账point的require_complete_source在计划中冻结，旧历史bootstrap不额外要求每周Daily全集，只保留无交易周/返回范围/实际输入值和旧键差集检查。没有依赖Ops SUCCESS/freshness快照。它不声称已向Tushare重新证明全市场日线完整；新周源代码集合与日线期望集合不一致时拒绝提交，不能静默裁掉额外代码。冻结后上游代码集合变化同样停止，保留原批供审计，不擅自修改不可变计划或跳过欠账。

历史源为空/只返回部分时，旧Raw键不删，receipt记录完整有界preserved_keys及≤20展示样本。该unit可以形成“已处理但未刷新旧键”的业务结果，不把rows_preserved计入rows_written；新周全市场缺码则不能闭合。日常payload是本次实际提交值，供DG顺序重放，并非对旧bootstrap证明的长期校验。

### 13.3 真实Prod只读规划样本

2026-10-10使用唯一远程包装脚本、READ ONLY事务及20秒statement_timeout核验2026-10-09周。未调用writer、未导出全历史或请求新源数据；临时SQL在/private/tmp，不作为运行输入。

相邻因子扫描日为2026-09-30、2026-10-08、2026-10-09，共14只代码发生变化，均有Raw周线库存；5559只日线代码构成本周集合。规划为1＋14＝15个unit，已有历史合计7476行、单股最多858行，加本周期望行约13035行。此数是规划规模，不是本轮源下载或入库结果。另只读核验最早2010-01-01周：2009-12-28至12-31均有Daily（每日1576—1604只）；000001.SZ四天因子均35.90600000，可作为该周末历史close独立抽样的上游基础，不以此代替新源价格校验。

| 变化代码 | Raw历史起点 | 已有周线行数 |
| --- | --- | ---: |
| 000422.SZ | 2010-01-01 | 852 |
| 000680.SZ | 2010-01-01 | 858 |
| 000739.SZ | 2010-01-01 | 842 |
| 001207.SZ | 2021-06-25 | 270 |
| 002023.SZ | 2010-01-01 | 858 |
| 003027.SZ | 2020-12-18 | 297 |
| 300919.SZ | 2020-12-25 | 296 |
| 601390.SH | 2010-01-01 | 840 |
| 603006.SH | 2014-07-04 | 618 |
| 603303.SH | 2017-03-31 | 487 |
| 603307.SH | 2023-02-17 | 187 |
| 603337.SH | 2017-01-20 | 497 |
| 605337.SH | 2021-02-12 | 289 |
| 688676.SH | 2021-03-12 | 285 |

### 13.4 P2提交时的验证结果与正式验收安排

P2/P1专项、注册库/架构/规划消费者、Ops API、传输监督和前端检查分别执行，组间有重叠，不累计为唯一测试数。最终P1/P2＋注册库及三项架构专项136项通过，其中P1/P2专项65项；这些组有重叠。真实HTTP子进程15项通过；Ops/API/公告回归48项通过、10项需要隔离PG而跳过；前端152项单测、typecheck、check:rules、build通过，Playwright周线详情1项通过（API mock）。Definition lint、Prod改动源码及新专项ruff、文档完整性、新增P2相对引用/锚点和git diff --check通过；CodeGraph sync/status为最新。既有构建大chunk提示保留。广泛unit planner回归仍有P1记录的既有月末压缩测试失配，未恢复已删除的旧私有函数。

P2提交时尚未配置隔离PG验收连接；当时SQLite测试明确替换发布锁，仅证明隔离物理事务、故障和续跑逻辑，正式发布器拒绝SQLite，不引入生产fallback。之后完成的隔离真实PG验收见§13.5；正式Prod验收和P3全量仍未执行。

剩余步骤按顺序：

1. 获准环境中先确认迁移head及旧写者清单，暂停现有id=14复权周线排程；执行185/186并验证表/trigger/索引valid-ready及EXPLAIN。id=13、月线和DG当前任务不变。这些执行尚未获本轮授权。
2. 加载新代码后，冻结代表性范围：两历史周＋两只本周变化股票；以真实源完成源行数→标准化→Raw/Serving→receipt读回，检查月线/未复权不变。验证PG单发布锁、事务截止、主动取消/进程退出/同意图续跑、Observer故障以及TaskRun/当前node一致终态；大单元测RSS及30秒内真实页面进度。实际代码/周、命令和恢复身份在执行前核定，不能用mock数据作正式证据。
3. P2真实验收通过后继续D1/D2开发及P3执行工具收尾。P3必须补齐首次捕获范围一次完整对账、捕获期间新增因子变化的单股补刷与bootstrap_closed生成入口；当前executor只写batch_closed，不自动封B0。完整历史下载完成不是B0完成，不提前开放自动更新。
4. 获准执行P3全量及D3文件/事件后初始化DG消费B0；最后J1联调新周＋历史修正，复权源入口清零、每日19:30排程和DG接收分阶段启用。

### 13.5 P2真实隔离PG与源样本验收（2026-10-10）

P2开发已提交018168fc。本轮先使用本机既有PostgreSQL18，在/private/tmp创建仅Unix socket/当前用户可访问的测试集群，复用ANNS_P1_TEST_DATABASE_URL的测试专属连接门禁；不安装依赖、不迁移/部署正式Prod、不改DG或排程。只对新测试库运行185/186迁移、PG锁/timeout、原子提交、取消/真正进程退出后续跑及Ops终态测试，再用真实源及有限Prod只读上游样本在隔离库核验源→标准化→Raw/Serving/receipt。

真实PG反例复现了worker._finalize_task_run只对公告保留业务进度并同步节点终态的问题：周线失败/取消会清掉已提交计数，节点仍显示running。按W06/W07修正现有收尾链，只对dataset_action/复权week/maintain且contract_kind=stock_weekly_adj/v1生效；成功使用最终结果，失败/取消保留业务进度，并同步当前节点。公告行为不变；月线、其他合同、没有周线合同的反例仍走原行为。没有新增状态机、接口或配置。

CodeGraph explore、impact覆盖OperationsWorker._finalize_task_run、_run_started_task_run、run_next/run_task_run；实际源码核验TaskRunIngestionContext、活动节点及现有API消费者。Foundation没有新增Ops依赖，边界矩阵不变。

本轮联合回归151项全部通过，含周线12项真实PG测试、P1/P2、公告真实PG、Ops API、任务协调及三项架构测试。真实PG覆盖185/186迁移与有效部分索引、append-only trigger、两个发布者竞争、实际os._exit进程退出后的锁释放和续跑、提交后取消、重复执行零请求、观察失败不回滚、Raw/Serving原子回滚、statement/lock timeout及终态一致。既有3条依赖弃用警告保留，没有安装或升级依赖。

真实输入取自Prod的READ ONLY事务，经规定远程包装脚本导出：3只股票，Raw/Serving各1712行，Calendar50行、Daily96行、Factor99行；均为显式字段、有限日期和行数上限，statement_timeout=20秒。只向新建测试库载入，不作为正式bootstrap数据或日常运行依赖。

| 真实源请求 | 返回/标准化/每张行情表写入 | 本次结果 |
| --- | ---: | --- |
| 000001.SZ，2026-06-05，week point | 1/1/1 | 提交后取消，TaskRun和node均canceled且保留1行；原批续跑仅闭合，重放也不再次请求源 |
| 000001.SZ，2026-06-12，week point | 1/1/1 | 成功；源与两张表、receipt逐字段一致 |
| 000422.SZ，2010-01-01—2026-10-09 | 853/853/853 | 成功；原库存852行，本次源多1行；没有保留缺键 |
| 000680.SZ，2010-01-01—2026-10-09 | 859/859/859 | 成功；原库存858行，本次源多1行；没有保留缺键 |

四次实际connector调用均limit=6000、offset=0，看到短页即结束；固定week及Definition21列，通过监督子进程Decimal传输。1714个本次输入键在Raw/Serving/receipt的全部21字段相等，包含未复权、qfq/hfq、成交量和成交额；没有reject或preserved键。单次源延迟1.211—2.481秒，执行及读回合计8.755秒，独立PG进度最大间隔2.533秒。没有用这组单股样本冒充当前全市场代码集合验收，也没有用API mock冒充正式任务页面验收。

资源实测：父进程峰值231.38MiB，源子进程峰值183.77MiB。二者是各自累计峰值，不能相加当作同一时刻值，也不能据父进程低于256MiB声称整个进程树通过RSS门禁。全市场大单元和进程树同时占用，以及正式页面30秒内可见进度，仍需验收；不提高既定预算。测试结束已停止临时PG集群，临时输入/审计日志仅在/private/tmp，不新增reports运行依赖。

**2026-10-10首次全市场验收被日期门禁阻断（历史记录；已由§13.6纠正）。** 请求2026-06-05全市场返回5514行，其中1行688287.SH的trade_date=20260605、end_date=20260521、close=close_qfq=0.35。其余5496行基准为20261009，17行有其他历史基准但未早于行情周。当前validate_source_scope对任何end_date早于trade_date的行都报weekly_adj.basis_not_updated，故整周未提交，未产生unit或batch_closed。MCP独立复核该股票5月22日、29日、6月5日、12日均保留同一旧基准；stock_basic显式list_status/delist_date显示“退市观典”、D、退市日期20260610。不能将这个源行为误称为网络故障，也不能未经确认过滤该代码或修改价格。

当时LLD §4.10与无条件日期门禁的冲突尚待确认，未修改校验。2026-10-11补查实际交易和因子后，不再将该样本称为价格异常；管理员批准按新判断修改，当前执行口径及结果见§13.6。其余正常样本及PG行为验收结果有效。

当时下一步：确认后修订原方案/LLD并重新验证全市场历史单元；后续实际完成情况以§13.6为准，正式小样本及页面验收仍未执行。正式迁移185/186、暂停旧id=14排程及代码加载仍须按授权阶段执行；D1/D2开发、P3全量、DG文件/事件与19:30启用均未执行。

<a id="weekly-basis-correction"></a>

### 13.6 日期校验纠偏（2026-10-11，代码与隔离验收完成，性能门禁未通过）

管理员确认按新判断修改。上交所公告和stock_basic均确认688287.SH于2026-06-10摘牌，最后交易日为6月8日。6月5日周线由6月1—5日五天形成，6月12日周线仅由6月8日一天形成；周五是周期标签。重新请求Tushare Daily、adj_factor及显式21列周线后，两周未复权OHLC/vol/amount按源周线精度与日线汇总一致；5月21日至最后交易日因子始终1.5915，前复权OHLC也吻合。计算日期较早不能证明复权价格未更新。

硬口径：去掉validate_source_scope的basis<week、publish_unit的basis<市场最后开市日，以及validate_weekly_adj_source_basis的basis<floor日期门禁，统一按本节及§6.6的因子值/价格核验；保留频率/范围/字段/重复键/预算/当前代码集合、原子发布、取消续跑和读回。异常验证写入现有basis_audit，保留源end_date及全部21列。测试必须覆盖退市当周标签、旧日期但因子相同通过、旧日期但因子变化拒绝、新日期却旧价格拒绝、缺因子分阶段处理、样本之外的日期较早股票不能绕过核验、SQL批次数受候选批次约束。真实验收重跑两历史周全市场及单股退市样本，不改正式数据或排程；本轮暂不进行部署、P3全量或DG切换。

落地代码为stock_weekly_adj_delivery的范围校验、发布校验及独立因子校验。源基准对应因子必须与实际目标因子相同；单股刷新还核对实际目标与冻结factor_target，即使源end_date更晚也不能跳过。周内最后交易日由Daily按代码/日期索引取得，不要求退市后继续有日线或因子。20个常规样本之外，所有日期较早的代码都加入核验；每128代码一组，只读必要日期和因子键。缺少依据的bootstrap继续保留源值，并在现有receipt记录未验证数量和样本原因，不伪造basis_date。日常必验代码缺依据仍报factor_coverage_missing，实质价格/目标因子不符仍报basis_not_updated；只调整后者的中文说明，没有新增reason code、配置或运营输入。

最终联合回归329项通过，其中本轮日期纠偏13项、真实PG13项；还覆盖P1/P2、Definition/运行注册库、resolver、Ops任务API、公告真实PG、任务协调及三项架构检查。新增正反例包括退市当周源标签保留、旧日期因子相同通过、因子变化/价格错误拒绝、冻结目标漂移拒绝、缺依据时bootstrap真实写入并记录未验证而日常阻断、257代码只发6条SQL。3条既有依赖弃用警告保留。Definition lint、改动Python的ruff、文档完整性及CodeGraph sync/status通过。未改变依赖矩阵、DatasetDefinition/DatasetExecutionPlan字段、源请求/21字段合同、Wealth API/UI；原模板无需新增字段。CodeGraph explore/impact覆盖三个校验点及publish_unit→writer→executor链，动态分派和SQL另读当前实现。

真实验收使用任务专属临时PG和新测试库，执行185/186；源端为真实监督connector，不以mock替代。有限Prod只读输入沿用§13.5，加688287.SH实际Daily和因子：

| 真实源请求 | 返回/标准化/每张行情表写入 | 验收 |
| --- | ---: | --- |
| 全市场2026-06-05 | 5514/5514/5514 | 688287.SH正常保留；提交后主动取消 |
| 全市场2026-06-12 | 5519/5519/5519 | 同一冻结批次续跑，只请求第二周；再次重放零源请求 |
| 688287.SH，2026-06-12 | 1/1/1 | 退市当周按周五标签发布，保留2026-05-21源end_date |
| 000422.SZ，2010-01-01—2026-10-09 | 853/853/853 | 正常历史刷新、源21字段读回一致 |
| 000680.SZ，同区间 | 859/859/859 | 同上 |

两全市场周合计11033输入行；五个receipt合计12746输入行，其中存在跨请求重叠，不能称为12746个最终唯一键。Raw、Serving和receipt对本次输入逐行21字段一致，含未复权/qfq/hfq、成交量和成交额；reject及preserved均0。每个全市场周独立价格实际验证000001.SZ和688287.SH两只；其余19个常规样本缺依据，是隔离库仅载入有限上游样本所致，receipt如实记录，不能据此认定Prod缺因子或宣称5514/5519只价格全部独立验证。两周只有688287.SH属于日期较早的必验代码，均已验证。全市场范围是历史源请求，不替代当前周全市场集合及正式页面验收。

五次实际源请求均limit=6000、offset=0，短页结束，单请求0.684—1.029秒。执行及全部读回21.187秒，独立PG业务进度最大间隔3.366秒。取消后保留5514行、1/2单元；续跑累计11033行、2/2单元；重放无重复下载。TaskRun与当前node终态一致，观察故障/进程退出/锁竞争等由同轮真实PG测试覆盖。本轮未迁移或写正式Prod，没有DG文件、事件或sensor操作。临时脚本、源证据和结果只在/private/tmp，不增加reports运行依赖；临时PG测试后停止。

**日期纠偏验收时性能门禁未通过（历史记录；后续优化见§13.7），不能据此进入全量执行。** 联合运行父进程峰值356.14MiB、源子进程峰值148.84MiB；另用新进程只执行首个5514行单元，在额外验收读回之前父进程峰值已达348.31MiB，子进程149.56MiB。父进程单独已超过256MiB目标，因此不能以测试读取历史结果为理由忽略，也无需相加两个累计峰值才能判断超预算。隔离发布成功只证明功能正确，不证明RSS门禁通过。保留原预算，不调整全局配置；内存分配根因尚待剖析。

下一步先单独处理单元执行的内存占用，审计源传输、标准化、写入/读回及receipt构造各阶段，减少同一单元的重复驻留；按同规模实际源单元复验父子进程同时占用及20秒单元截止。通过后再安排正式迁移、代表性运行—取消—续跑—读回和页面验收，之后推进D1/D2及P3。此处不批准正式执行，也不将日期纠偏完成写成P2整体完成。

<a id="weekly-memory-optimization"></a>

### 13.7 单元内存根因与优化（2026-10-11，代码与隔离验证完成，正式验收待完成）

日期纠偏已提交12f5ddde，未推送。管理员授权继续定位内存并优先按256MiB原目标优化；只有无法解决或复杂度很高才讨论提高预算。本轮不增加配置、不改源参数/字段/分页、单元持久化及续跑合同，也不写正式Prod/DG。

同一5514行真实源单元在隔离PG分阶段采样：导入后171.5MiB，测试上游载入后204.0MiB；标准化前249.3MiB、之后263.1MiB；Raw写入后300.6MiB、Serving写入后316.0MiB；两层整周读回后323.3MiB，交接DAO写入峰值341.9MiB。每条行情SQL1000行、21000参数，SQL约408KiB。执行持有原始Decimal页、整周canonical字符串、标准化Decimal及两层coerce/过滤副本；之后又同时加载两层整周读回并重复canonical化。内存随单元增大，不是读了全部历史；峰值已在额外验收读回前发生。

独立importtime证明仅导入有界HTTP模块就经clients包导出加载tushare_client的全局tushare SDK，连带pandas/numpy；静态调用链确认HTTP路径不使用SDK。该导入在spawn子进程重复发生，实测父子及resource tracker同时RSS峰值367.8MiB。采样与单阶段精确峰值分别记录，不能把各进程不同时刻的累计峰值相加。临时测量工具仅在/private/tmp，不进入运行链。

优化边界与代码映射：

1. tushare_client只在构造TushareSdkClient时加载SDK，仍在构造时设置原token，pro_bar参数、限流和返回行为不变；HTTP和有界HTTP不加载SDK。审计包导出、connector factory、错误映射及SDK调用方；补无SDK导入和实际SDK委托的正反例。
2. capture_unit在完成源精度/重复键/载荷校验后，释放原始页与原始列表，再进入原normalizer。保持20秒源调用、三页/12000行及全部拒绝规则；跨页重复、冲突、取消和空页回归。
3. publish_unit对既有normalized rows每256行调用原writer两层upsert，再按incoming canonical每256键依次读回两层并逐字段比较。写入全部完成后才开始读回；避免重复键跨块改变校验结果。所有小块仍在原20秒单元事务内，取消/失败回滚整个单元，单元最终仍只有一条receipt及一次commit。每块前后检查取消，不改变日常批次交接值或bootstrap摘要。读回通过后直接使用已经逐块验证的incoming构造receipt，去掉整周多份读回和重复canonical。

256行为内部临时工作集边界，不是新增运营配置；既有SYNC_BATCH_SIZE（Settings/env，默认1000）的DAO上限仍有效，小于256时继续进一步拆SQL。page/单元/内存/payload及事务预算不提高，不改通用BaseDAO或其他数据集写路径。正反例须证明大单元SQL/读回工作集有界、后一块失败/取消回滚前块、读回缺键/值变化阻断、跨块重复一致处理；PG故障、重放、Ops、公告和普通writer消费者继续回归。

验收先复跑5514行真实源单元并同时采样父子进程，再检查两历史周和两股历史的21字段读回、取消/续跑/重放。补12000行单元容量样本，明确合成与真实来源，不能用合成代表全市场完整性。若仍超预算，继续根据阶段分配证据优化；不先提高目标。正式迁移、页面验收及全量执行仍单列。

第一轮5514行父进程239.8MiB、同时进程树254.2MiB；12000行合成单元仍达317.7MiB。进一步阶段采样定位到交接DAO：进入时257.4MiB，整份deepcopy及重复canonical后285.2MiB，JSON持久化/读回后319.0MiB。继续消除整份临时JSON/UTF-8双副本：用相同sort_keys/分隔符/Unicode规则逐片计字节和SHA256，冻结摘要必须与原canonical_json字节完全一致。DAO不修改输入，只做浅层字段准备；日常源行分块校验并验证块间严格排序，不再重建整份canonical载荷。输入、返回值和数据库之间仍须隔离可变JSON，幂等冲突及载荷预算不放松。先测这些调整，只有证据表明仍不达标才进一步改读取方式。

第二轮12000行仍达291.5MiB，交接写入后把完整JSON载荷重新取回Python会再解码整份行数据。正式PG利用既有JSONB在数据库中做完整payload等值校验，查询只返回其余字段；逐字段校验仍覆盖全部元数据，不只比摘要。等值成立后返回独立字典副本，使用原已验证不可变字符串，避免重新解码并分配所有数值字符串；返回ORM及可变JSON隔离语义保持。SQLite仅用于隔离测试，沿其JSON类型作Python等值核验，不作为正式执行后备。须用真实PG验证不同payload/元数据冲突、不加载载荷列、返回JSON修改不影响输入或数据库。若仍超预算，再依据SQL阶段峰值缩小内部块；不调整SYNC_BATCH_SIZE全局值。

第三轮12000行峰值258.1MiB，仍不能算通过。最终内部工作块收紧至128行，在stock_weekly_adj_contracts的SOURCE_ROW_BLOCK_SIZE统一定义，由发布器和交接DAO共用，替代本节前述256行试验值；该值仅限制SQL/读回/校验的临时对象规模，不是运营配置或新policy字段。单元仍可包含12000行及三源页，完整21字段读回和单事务不变。

128行复测257.6MiB，剩余峰值来自PG驱动再次生成完整JSON文本。PG payload用既有canonical_json只编码一次，作为有类型的Text绑定并CAST为JSONB，插入和数据库等值核验复用同一文本；不修改引擎全局JSON serializer，也不自行拼SQL或丢字段。摘要/字节计量继续按相同规范流式处理，SQL参数始终绑定，payload落库仍为JSONB对象。


最终结果（本节取代§13.6的超预算当前状态，不改写历史实测）：

| 验证范围 | 业务执行父进程峰值 | 源子进程累计峰值 | 结果 |
| --- | ---: | ---: | --- |
| 12000行容量单元，6000＋6000＋0三页 | 244.78MiB | 未调用源进程 | 原256MiB单进程目标通过；源数据为已捕获样本扩展，不能冒充12000只真实股票 |
| 两历史周全市场、退市单股及两股历史，连续取消/续跑/重放 | 251.89MiB | 100.06MiB | 原单进程目标通过；五次真实源请求，21字段读回一致 |

原§0.3/W07预算为进程RSS目标，policy.memory_target_bytes仍为256MiB，没有提高预算、压低12000行上限或改变单元事务。另行采样整棵Python执行进程树（含source worker和resource tracker）同时总RSS峰值344.14MiB，不能把单进程达标说成整棵树总量低于256MiB；正式环境必须同时记录各进程与总量。此结果证明原文所列单进程目标，不证明进程树合计低于256MiB，没有提高任何预算。

内存测量覆盖业务执行及原批重放，结束点在额外独立验收读取全部receipt/行情之前；后者使真实源验证脚本累计峰值264.89MiB、容量脚本278.94MiB，已如实列出，不能混作业务执行峰值或遗漏进程总量。只在临时脚本中诊断显式GC，连续执行驻留几乎不下降，因此没有往生产代码加入gc.collect或平台malloc释放钩子。源码优化解决重复活对象和重复JSON解码/编码；长期进程与正式入口的实际RSS仍须部署后代表性验收，不能将隔离脚本结论推广为所有环境保证。

真实源最终五次请求行数仍为5514、5519、1、853、859，receipt输入合计12746（跨请求重叠，唯一键口径见§13.6）；Raw/Serving/receipt的21字段一致，reject/preserved均0。首次提交5514行后取消，同一意图续跑只下载5519行第二周，累计11033行；再重放无源调用，退市单股和两股历史成功，TaskRun/node终态一致。真实验证及独立读回合计22.791秒，业务进度最大间隔3.795秒；容量验证合计23.093秒（含独立读回），单元事务及源分页阶段最长可见进度间隔9.366秒，原20秒单元deadline正常执行。测量异步采样，不在每条SQL前调用ps；早期密集探针曾使容量验收触及20秒deadline并完整回滚，不能据该测量开销判生产执行超时。

最终439项定向回归通过、3条既有依赖弃用警告。新增内存专项16项及真实PG共16项覆盖：HTTP不加载SDK/pandas/numpy、SDK token/限流/参数/返回委托不变、标准化前原始Decimal页释放、128行写入/读回工作集、跨块同键一致处理、后块失败/取消/读回异常回滚整单元；流式UTF-8字节数和SHA256与既有冻结字节逐项相等（含Unicode及有限浮点表示），非有限值仍拒绝；DAO块间重复/乱序/非规范值拒绝；真实PG JSONB等值检查、不加载完整payload列、不同payload/元数据幂等冲突拒绝、返回JSON与输入/数据库独立。相邻回归涵盖通用normalizer、BaseDAO、source connector/factory、HTTP监督、公告、Ops/API、注册库/resolver和架构护栏。

变更只在tushare_client的SDK加载、周线capture/publisher/contract/DAO，以及writer的具名周线路径字节计量；通用BaseDAO、其他writer路径、模型/迁移、Definition/Plan字段、源请求参数与21列、配置及API/UI不变。SOURCE_ROW_BLOCK_SIZE为固定内部工作集边界，不增运营配置；原SYNC_BATCH_SIZE仍由已有Settings/env统一供DAO消费。CodeGraph explore/impact覆盖capture→source、publisher→writer→BaseDAO、周线DAO及SDK类；digest同名结果用实际imports核验，仅变更周线合同中的digest，公告和其他同名函数不受影响。PG的payload仍为原JSONB对象，冻结摘要及字节合同未变，模板没有新增字段。临时脚本、输入、日志和性能证据只在/private/tmp，未增reports依赖、未安装依赖，未写正式Prod/DG。

下一步为正式环境代表性验收：核定迁移head和现有写者，获准后暂停id=14旧复权周线排程、迁移185/186并加载代码，检查正式入口的各进程RSS、累计事务期限、运行—取消—续跑—读回及页面进度。之后才继续D1/D2、P3全量及DG切换；本轮不擅自进入这些阶段。内存优化随本次提交收口；已提交日期纠偏为12f5ddde，未推送。


<a id="weekly-prod-formal-preflight"></a>

### 13.8 Prod 部署核验及人工操作清单（2026-10-11，正式运行验收待执行）

管理员告知已部署最新修改并授权继续推进。SSH只读确认远程提交为cc7c528ea1bb46a840d3870407df428bfcc57ec7；Web、Ops worker和scheduler均active，启动时间分别为17:10:29、17:10:26、17:10:26（上海时间）。生产数据库只经规定的psql-remote.sh读取，所有事务READ ONLY、statement_timeout=20秒、显式字段及限定代码/日期/行数。本轮没有迁移、部署、提交/取消任务、暂停排程、写Prod或启动DG。

核验结果：

- Alembic版本20261010_000186；core.stock_weekly_adj_delivery存在，尚无记录，没有未完成交接批次。append-only trigger启用。
- Raw的week日期部分索引定义与186一致，valid/ready/live均true；2026-06-05的EXPLAIN使用该索引的Bitmap Index Scan，已不是P0时的全表扫描。
- id=14复权周线仍active，cron=4 22 * * 5，下次2026-10-16 22:04；id=13未复权仍active，cron=3 22 * * 5。验收操作第一步仅暂停id=14，不改cron，不提前启用19:30。部署已发生，但部署前暂停这个步骤没有完成，不能写成切换已完成。
- 当前没有queued/running/canceling任务。最新旧机制复权周线TaskRun15186在10月9日成功，5559行；它早于部署，不是新执行器验收证据。
- Raw与Serving的2026-06-05、06-12、10-09行数分别均为5514、5519、5559；周线库存起点2010-01-01。这只是写入前库存，不是本轮源对账。
- SSE本周10月5—7日休市，8/9日开市；9月30日、10月8日、9日的Tushare日线分别5561、5557、5559行，逐键均有当日因子。000422.SZ于10月9日因子15.83480000→15.90530000，000680.SZ为5.76400000→5.82820000，适合验证单股历史刷新。
- 两股2010-01-01至2026-10-09的Raw周线分别852、858行。相同代码/范围的月线在Raw/Serving各404行，close_qfq合计3001.6400、vol合计1991576497.6300、amount合计1977366928.9300；这只是限定样本的写入前对照，不证明全部月线字段一致。正式写入前再冻结全部21字段和未选择键，执行后按本次范围对账，不建立固定历史reports依赖。
- SSH进程采样worker RSS212268KiB（207.29MiB），当时无源子进程。它是既有进程的运行前基线，不能当作周线执行峰值；正式运行仍须记录父进程、source worker及同时进程树总量，并核对原256MiB单进程目标。

执行入口与具体范围已核定如下，全部为运营后台“股票周线行情（复权）”（stk_period_bar_adj_week）的手动维护，串行进行，先完成A的验收再提交B/C：

| 任务 | 日期输入 | 股票代码 | 用途及边界 |
| --- | --- | --- | --- |
| A | 区间2026-06-05至2026-06-12 | 留空，全市场 | 两个完整周，预计库存11033行；实际接收/写入数以源及receipt为准。第一单元提交后尝试主动取消，确认保存该单元，再同意图恢复。不是首次全量bootstrap。 |
| B | 区间2010-01-01至2026-10-09 | 000422.SZ | 一只本周因子变化股票的历史刷新，1个stock_history单元；原库存852行，源可能返回此前没有的历史，不按旧数量拒绝新增。 |
| C | 区间2010-01-01至2026-10-09 | 000680.SZ | 同上，原库存858行。 |

A看到“已完成1/2”且仍运行时，在原任务详情点击“停止处理”。等待任务及活动node实际canceled，确认已提交数据仍在；随后点击原任务详情“重新提交”。当前代码的retry接口保留原request_payload.execution_context、日期和过滤，因此保持原批次身份并恢复剩余单元。不能用“复制参数”另建意图冒充续跑。若人工点击来不及且A已经成功，如实记录取消尚未验证，不清空receipt、不伪造停止或改变原批；另行安排自然未完成的代表性范围。成功任务的页面不显示重新提交，幂等重放须通过现有API携原scope和resume_from_task_run_id发起，不将复制参数的新批次算成原批重放。

执行时原每页6000、最多3页/12000行、单元payload8MiB及20秒事务截止不变；SQL/读回临时块128行，不把分块当独立提交。收到任何质量/预算/范围错误即停止并审计，不提高预算或跳过检查。对本次源→标准化→Raw/Serving→receipt的21字段完整读回，包含成交量、成交额及未复权/qfq/hfq；未返回旧键保留。检查TaskRun和node终态、真实业务进度及页面最长更新间隔≤30秒，页面的既有轮询为3秒。隔离的进程退出/故障注入测试证据继续保留，本轮不擅自终止共享Prod worker或注入正式观察故障。

当前执行障碍是浏览器控制连接连续两次超时，无法使用已登录运营会话；已经请求管理员代操作以上清单。数据库、SSH及既有服务访问正常。待取得实际TaskRun ID后可继续只读监测及对账。真实任务运行、运行时内存峰值、主动取消/同意图续跑、幂等重放及真实页面进度均未验收；不以本次部署/DDL预检代替P2完成。无需启动DG，D1/D2、P3全量、DGbootstrap和19:30启用继续分阶段推进。


<a id="weekly-prod-run15368"></a>

### 13.9 正式双周任务15368对账（2026-10-11，通过；P2其余验收待完成）

管理员按§13.8提交任务A，并提供TaskRun15368供审计。实际请求为range、2026-06-05至2026-06-12、filters={}，执行批次077d12a5-3215-475d-8100-f742372b6749。任务于上海时间18:22:49.408受理、18:22:52.454开始、18:23:24.487成功，运行约32.033秒；2/2单元完成，rows_fetched=rows_saved=11033，rejected=0、failed=0。活动node23719也success，结果计数一致，没有issue或取消时间。32秒是整个两单元和批闭合耗时，不是一个单元事务耗时；没有触发20秒单元截止错误。

正式业务事实与只读验收：

| 项 | 结果 |
| --- | --- |
| 原批记录 | revision1=plan、2/3=unit、4=batch_closed；bootstrap=false，未伪造首次全量闭合 |
| 第一周 | received=unique=written=5514，preserved=0，revision2发布于18:22:56.935 |
| 第二周 | received=unique=written=5519，preserved=0，revision3发布于18:23:13.570 |
| 源复权依据抽验 | 每个周unit的basis_audit.checked=21、unverified_codes=0；日期较早代码1只，已验证1只；不是5514/5519只价格独立复算全验 |
| 物理对账 | 原批payload的11033个唯一输入键，在Raw/Serving均存在；全部21字段分别0差异，含freq/日期、未复权、qfq/hfq、vol/amount/change/pct_chg；用数值/date类型直接比较，保持null语义 |
| 摘要和规范值 | 分unit只读导出既有payload至/private/tmp，本地使用既有canonical_source_rows/digest复验规范化、唯一数和payload摘要；两条均通过，闭合units_digest一致 |
| payload总量 | 第一条2328381字节、第二条2330660字节，共4659041字节，与闭合头和TaskRun进度一致 |
| 限定月线对照 | 两股原404行及close_qfq/vol/amount合计与§13.8相同；仅为限定样本辅助对照，不扩称全历史/全字段未变 |
| 排程 | 管理员已暂停id=14，cron保持原值；id=13保持active，不提前启用19:30 |

仅通过psql-remote.sh执行READ ONLY事务，statement_timeout=20秒，按TaskRun ID/原批UUID、两个业务日期和两只对照股票限定。数据库输出只保留汇总；两条unit payload合计约4.7MB，在/private/tmp流式逐条复验，不增加reports依赖、历史固定hash门禁或日常重复对账。这里比较的是本次正式写入批次，没有重新验证此前bootstrap全历史。SSH只读查询worker进程状态和18:22:45—18:23:30日志，未启动/重启/终止服务。

内存证据：原worker PID331417持续存活，/proc状态VmHWM=261016KiB（254.898MiB）、VmRSS=239872KiB（234.25MiB）。VmHWM是该进程自启动以来的生命周期高水位，涵盖本次任务但不能称为任务专属峰值；因为这个上界仍低于256MiB，可确认本次父进程满足原单进程目标。service cgroup MemoryPeak=370999296字节（353.813MiB），包含服务组进程及cgroup其他记账，不能当父进程RSS，也不能冒充精确的同时进程树RSS采样。执行后仅剩resource tracker，已退出source worker没有可读的VmHWM；收到ID时任务已经完成，因此源子进程和完整时序未采集，不声称完整正式性能验收结束，也不提高预算。

本次无cancel_requested_at，两个unit及批闭合均已提交。不得删除receipt/清空数据或把success改canceled来补取消证明。主动取消/原意图恢复、同批零请求重放、运行中页面≤30秒真实更新仍待验证；源子进程及同时进程树采样待下次在启动前挂好只读监测。页面3秒轮询源码和最终typed progress存在不能代替浏览器现场验收。P2暂不标记整体完成。

下一步先串行提交§13.8的B：2010-01-01至2026-10-09，ts_code=000422.SZ，股票周线行情（复权）；审计通过后再提交C的000680.SZ。两单股用于历史因子刷新对账；均为一个单元，不能用它们替代“已提交第一单元后取消”的双单元验收。暂不提交全量bootstrap/自动更新，不恢复id=14或切换DG。当前没有新源码、配置或依赖边界变更；本轮文档记录尚未提交。

为B提前启动一次300秒的只读内存采样：每0.1秒读取既有worker及其子进程的/proc Name/VmRSS/VmHWM，结果仅输出到本地/private/tmp/weekly-p2-formal-memory-next.jsonl，采样进程不在worker子树中，期限到达自动退出；不修改服务、配置或数据。开始采样不代表B已提交或验收通过，后续按实际TaskRun时间窗口归属样本。


<a id="weekly-prod-run15375"></a>

### 13.10 正式单股历史任务15375对账（2026-10-11，功能通过，性能归因待验证）

管理员提交B并提供TaskRun15375。实际请求：股票周线行情（复权）、range、2010-01-01至2026-10-09、ts_code=000422.SZ；批次570b9383-2776-46ea-b0bf-8a1fe64cb61b。上海时间19:09:28.910受理、19:09:30.354开始、19:09:36.773成功，约6.419秒。1/1单元、received=saved=853、reject=0、failed=0；node23726同为success，没有issue或取消。receipt revision5=plan、6=unit、7=batch_closed，bootstrap=false；unit于19:09:34.371提交，preserved=0、basis_date=2026-10-09，basis_audit.checked=1、unverified_codes=0。

按原批payload的853个唯一输入键对照正式Raw和Serving，所有键存在，全部21源字段各0差异；两层该股历史现在均853行，2010-01-01至2026-10-09，相较§13.8的852行库存净增1行。没有事前完整键快照，不能仅凭数量宣称已确定新增日期。原批unit及闭合头只读导出到/private/tmp，规范值、两个payload摘要、闭合units_digest与359445字节总量均核验通过。限定月线样本仍404行，close_qfq/vol/amount合计同§13.8，不扩称全部月线字段未变。

历史复权刷新效果：以下旧值来自此前隔离验收前由Prod只读捕获的000422.SZ样本，不是DG数据；新值来自15375执行后的正式Raw，且本批21字段对账已覆盖Serving。

| 周标签 | 旧end_date | 新end_date | 旧close_qfq | 新close_qfq | 未复权close |
| --- | --- | --- | ---: | ---: | ---: |
| 2010-01-01 | 2025-09-10 | 2026-10-09 | 13.7000 | 13.3900 | 21.3500，两次一致 |
| 2020-01-03 | 2025-09-10 | 2026-10-09 | 2.7900 | 2.7200 | 2.9300，两次一致 |
| 2026-09-25 | 2026-09-30 | 2026-10-09 | 11.7900 | 11.7400 | 11.7900，两次一致 |

三样本的close_hfq、vol、amount也分别与旧样本一致。以上证明该股旧日期qfq已刷新到当前源返回的基准，不能据此宣称全Prod或DG全历史已更新。

性能仍需单独验证：worker仍为PID331417，查询时VmHWM=284160KiB（277.5MiB）、VmRSS=243380KiB（237.676MiB），service MemoryPeak=374263808字节。277.5MiB是生命周期高水位，已超过256MiB，不能沿用§13.9的254.898MiB称正式长期worker始终达标。两次观测之间实际还执行了15369—15374共6个新闻/维护/dividend/stk_holdernumber任务；目前没有本任务专属时序，因此不能把该峰值归因15375或判定周线导致超预算。此前300秒只读采样已正常退出，窗口未覆盖19:09的B，不能当作B的性能证据。完整正式性能门禁仍待确认，不提高预算、不重启共享worker来清空高水位。

为C（000680.SZ、同日期区间）取得可归属的内存证据，先请管理员准备表单并暂不提交，确认准备好后开始采样再通知提交。采样以实际TaskRun时间窗口和worker/source进程身份归属RSS，不用旧VmHWM冒充新任务峰值。若时序证明周线执行或自身连续运行超过目标，继续定位原256MiB预算内的原因，先修方案再实施；不因功能通过忽略性能。B是一单元正常完成，不替代取消续跑/幂等重放/真实页面验收，P2整体待完成；本轮只读审计及原方案/LLD记录，未提交源码/文档，未执行C或启动DG。


<a id="weekly-prod-run15378"></a>

### 13.11 正式单股历史任务15378及内存时序审计（2026-10-11）

管理员先准备C表单，待采样已确认正常后提交000680.SZ，并提供TaskRun15378。请求为range、2010-01-01至2026-10-09；批次50ea35d4-a18e-41e9-84b3-32e0487cfb3a。上海时间19:43:09.484受理、19:43:10.236开始、19:43:15.650成功，约5.414秒。1/1单元、received=saved=859、reject=0、failed=0；node23729同为success，没有issue或取消。业务revision8=plan、9=unit、10=batch_closed，bootstrap=false，basis_date=2026-10-09；basis_audit.checked=1、unverified_codes=0。任务时间窗口没有其他TaskRun重叠。

数据对账：本批859个唯一输入键在Raw/Serving均存在，全部21字段各0差异，包含未复权/qfq/hfq及vol/amount；两层该股库存现为859行，2010-01-01至2026-10-09。相较§13.8的858行净增1行，未保存同一时点完整旧键清单，不推测新增日期。既有unit及闭合头只读导出约358KB至/private/tmp，规范值、两个payload摘要、闭合units_digest及357505字节总量全部一致。限定月线样本仍404行及原close_qfq/vol/amount合计；id=14保持paused，id=13保持active。

历史qfq刷新样本（旧值来自此前隔离验收前捕获的Prod只读样本，新值来自本次正式Raw，Serving在本批全字段对账中一致）：

| 周标签 | 旧end_date | 新end_date | 旧close_qfq | 新close_qfq | 未复权close |
| --- | --- | --- | ---: | ---: | ---: |
| 2010-01-01 | 2025-09-10 | 2026-10-09 | 7.7000 | 7.5300 | 12.6600，两次一致 |
| 2020-01-03 | 2025-09-10 | 2026-10-09 | 3.5200 | 3.4400 | 3.6800，两次一致 |
| 2026-09-25 | 2026-09-30 | 2026-10-09 | 9.0400 | 8.9400 | 9.0400，两次一致 |

三样本close_hfq、vol和amount分别与旧值一致；两只样本股票的历史qfq刷新效果均已在正式库验证，不代表全市场历史刷新或DGbootstrap完成。

内存采样在上海时间19:42:28.573启动，worker仍为PID331417，既有resource tracker为349825；每0.1秒读取worker子树/proc Name、VmRSS、VmHWM。实际TaskRun开始至结束窗口内有53个样本，最大间隔0.101836秒；采样覆盖任务前、完整执行和结束后。新源进程PID369675在任务窗口中出现，持续约2.416秒，其VmHWM一并采集，未把已有tracker误作源进程。

| 指标 | 本次任务窗口结果 | 含义 |
| --- | ---: | --- |
| 父进程RSS采样峰值 | 240.613MiB | 本次运行观测低于原256MiB单进程目标 |
| 源进程RSS/已观察VmHWM峰值 | 136.957MiB | 新源进程，两者均低于256MiB |
| 同时进程树RSS采样峰值 | 390.445MiB | 同一时点求和，含父进程、source worker和resource tracker，不能称进程树合计低于256MiB |
| 父进程既有VmHWM | 前后均278.051MiB | 提交前已经存在，本次没有增加；不能用它冒充本任务峰值 |

以上是0.1秒时序观测，不能排除采样间极短瞬态；旧生命周期高水位较高，无法从VmHWM单独求出本次低于它的精确绝对峰值。本轮证据支持该单股样本的运行观测，不证明所有正式全市场/12000行单元或混合任务长期进程均已验收。原memory_target_bytes仍为256MiB，不提高预算、不重启worker清空高水位。§13.10仍如实保留B没有专属采样而无法归因的历史结论。

任务结束后校验采样PID369518、启动时间和命令，只停止本轮采样进程，已确认其退出、正式worker331417保持运行。采样只读，不属于业务worker/scheduler；未启动DG、改服务或写业务数据。SQL仅经psql-remote.sh、READ ONLY、显式字段及原批/代码/日期限定，statement_timeout≤20秒；临时payload/采样/汇总均位于/private/tmp，不引入reports依赖。本轮原方案/LLD更新，文档记录尚未提交。

A/B/C正常运行及数据验收全部通过。本节完成时曾将完整全市场性能采样列为待办；之后管理员决定内存工作收口，现行安排以§13.12为准。正式主动取消/原意图恢复、同批零请求重放及真实页面进度尚未验收；P3全量、DG D1/D2和19:30切换没有提前执行。


<a id="weekly-memory-closeout"></a>

### 13.12 内存工作收口及后续安排（2026-10-11）

管理员认为内存验证轮次已经足够，决定在现有证据基础上收口。内存优化cc7c528e已部署；12000行容量隔离验证、连续执行验证、正式双周15368及两只单股15375/15378的数据对账，以及15378的任务时序采样，足够支持后续开发。不再追加专门的全市场内存复测，不继续优化，也不提高原256MiB单进程目标。此前各次观测的范围、生命周期高水位和进程树合计如实保留，不改写成所有场景均已验证。

P2开发、正常小样本及内存工作收口；正式取消续跑、同批零请求重放及页面进度仍未完成。下一步可推进DG D1/D2接收链开发；上述正式验收在P3全量执行前用一次代表性运行协调完成，不再重复正常单股任务。全量执行仍需阶段授权；id=14保持暂停，DG供数及19:30自动切换尚未执行。

本轮只更新Prod与DG原方案/LLD的状态及验收安排，不修改代码、配置或数据，不新增验收机制。


<a id="weekly-delivery-anchor-correction"></a>

### 13.13 DG接收前的日期合同校正（2026-10-11，管理员已确认）

修正前，publish_closed_batch把任务cutoff_week填入max_input_week；任务截止周可能晚于实际返回数据，不能用于DG选择真实分区。管理员确认：max_input_week改为本批已提交输入的最大trade_date；没有输入行时为null。日常从已有unit payload.rows汇总；bootstrap unit仅摘要，发布时保存该unit实际最大输入周，再由闭合阶段汇总。cutoff_week仍表示任务范围，两者不混用。21行情列、意图/请求参数、事务、预算、原批记录均不变；不改写已闭合批。DG捕获时核验闭合头与实际输入范围一致，错误摘要不能创建虚假分区。

源码已修正；`test_stock_weekly_adj_p2.py`新增四项隔离验收，覆盖任务到10月9日但实际只到6月5日、实际返回10月9日、空批不造日期及首次bootstrap摘要/闭合最大周汇总。P1/P2共69项通过。修改已提交`b49d9cdc`、尚未部署，已闭合批未改写；正式验收不能把本地测试当作Prod已加载新逻辑。DG接收实现和真实只读传输核验见[DG LLD A14](../../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#adjusted-weekly-d1-d2-implementation)。

<a id="weekly-bootstrap-capture-progress"></a>

### 13.14 DG稳定捕获推进及Prod收尾边界（2026-10-12）

DG D2已完成获准单股实际交付、取消续跑和事件检查；本轮继续D3的稳定捕获代码，不追加Prod内存优化。落实既有合同：以真实bootstrap_closed作为B0，固定库存和读取范围，任何plan/unit/closure提交导致捕获停止；首次捕获核对Raw week总行数，防止库存清单遗漏代码或年份。具体代码、预算、测试及下一切片统一见[DG LLD A16](../../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#adjusted-weekly-bootstrap-capture)，不在Prod重建另一套DG字段合同。

本轮通过唯一psql-remote.sh入口、READ ONLY事务、20秒statement_timeout验证一行控制信息：交接表最新revision=10，无bootstrap_closed；Raw week总行数2,896,823。对现有普通闭合批revision10执行新B0核验SQL，boundary返回null，正确拒绝将单股样本当首次边界。没有导出源行、部署、提交TaskRun、生成B0或写入DG。

Prod P3仍须开发完整一次对账、捕获期间因子定向补刷及bootstrap_closed收尾，合并完成正式取消/恢复/同批零请求重放及页面门禁后，另获全量执行授权。当前只有batch_closed执行链，不能以DG捕获代码完成宣称Prod全量刷新或B0已经完成。DG年度replace_input_keys、正式事件和独立水位迁移尚未完成，本轮不调用旧create_or_identical来推进。

<a id="weekly-bootstrap-closeout-execution"></a>

### 13.15 P3收尾执行分阶段（2026-10-12）

源码核验：resolve_weekly_adj_units在开始前冻结unit_total和units；run_weekly_adj只恢复这些unit，完成后发布batch_closed；首次unit仅保存源行数及21列rows_digest。捕获结束时才知道的因子变化股票，不在原unit列表中。因此不能直接追加新unit或修改原plan/hash，也不能直接把普通batch_closed升级为B0。CodeGraph已覆盖run_weekly_adj、publish_closed_batch和DG候选/审计/事件消费者；不修改Foundation到Ops的依赖方向。

管理员已同意收尾分两个冻结阶段：

1. 原全市场批保持原意图、周单元及幂等身份。全部完成后，按周短事务核对已刷新21列与源摘要，明确排除有记录的保留键，另核对未选原键和值；完整对账只在首次收尾做一次。结果须持久化到该次业务收尾记录以支持退出续跑，不保存永久源副本，不依赖reports。
2. 审计捕获期间因子变化，冻结新的定向历史补刷批，明确关联原全量批。单代码历史仍使用现有request builder、source监督、writer、预算和短事务；原批完成量不变，补刷阶段显示独立冻结总数。超1000单元或256MiB载荷先拒绝，不自动拆批或增加预算。取消后恢复原补刷意图，不重新选股票。
3. 补刷完成后重新检查因子扫描覆盖和目标基准；期间又发生变化不能直接生成B0，需明确记录待处理范围并停止收尾。不存在变化时不发无用源请求。首次原批与补刷结果都闭合、一次对账通过，才append bootstrap_closed，记录实际库存边界和factor_scan_end；DG从该真实revision开始捕获。

收尾不是让每次日常更新重新校验全历史。日常保持只验证本批新增/修正；历史合法修订不受首次源摘要永久约束。不能在交接DAO塞业务编排、另建Ops状态机、创建后台常驻进程或用人工伪造B0。现有kind/幂等身份、一次对账范围、补刷受理和进度已落到§5.4/§6/§13.15.1；本文件按数据集开发模板更新0.3三层语义及消费者口径。源码验收见§13.15.2，正式执行另见§13.15.3。

两阶段源码和隔离验收已完成，尚未部署本轮Prod代码，没有运行正式全量任务、补刷或B0写入。DG管理员已选择临时放宽bootstrap行数预算、仍按整年计算，具体局部上限和消费者审计见[DG LLD A17](../../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#adjusted-weekly-bootstrap-replacement)。日常预算与内存预算不变。

#### 13.15.1 已确认两阶段的代码级落点

不新增运营参数、CLI或常驻进程。首次完整范围maintain仍冻结全部周单元；首次批全部源unit完成后，在同一发布锁下按unit做一次Raw/Serving读回对账，再闭合batch_closed。运营随后再次提交完整历史范围maintain：resolver识别已对账、尚无B0的首次批，只冻结必要的新完整周和因子基准尚未覆盖的股票历史，作为独立TaskRun/业务batch；新范围须覆盖原首次范围。任何子范围不进入首次收尾。已有B0时，完整范围maintain恢复正常手动历史刷新，保存rows，不再跑首次历史对账。

具名模块ingestion/stock_weekly_adj_bootstrap.py只负责首次收尾；planner通过局部import调用其只读规划，避免将业务编排放DAO。已有contract_version=1及四个record_kind保持：首次一次对账的unit记录使用audit:{source_unit_id}幂等键、rows_written=0、summary仅行数/摘要；不加入源closure.unit_ids或源unit计数。源unit仍仅摘要，额外记录未刷新Raw/Serving键的有界摘要和必要键清单，before/after核验只针对本unit。对账每unit一个20秒短事务并持久化audit receipt，退出后从这些业务结果续跑；batch_closed.payload增加bootstrap_reconciled=true。没有永久源副本、reports证明或第二套TaskRun状态机。

第二阶段plan.metadata记录bootstrap_parent_batch及bootstrap_parent_revision、源覆盖窗、因子扫描截至日；每个unit仍使用原21列、point_week/stock_history和request builder。原始意图独立冻结，不改第一阶段plan或单元数量。因子规划以实际Daily日期为候选截至日，必须位于权威开市日历且逐日线代码验证Factor覆盖；按Raw实际代码/基准日期与各代码截至该日的最后日线因子比较，读回仅变化代码及起点，不向Python拉全历史因子/行情。未知独立依据保留并记录，不把退市股票的缺当前日期因子当作价格错误。源请求、单元和整批上限不变，超量不冻结，不自动拆组。

第二阶段的普通batch_closed不能提前宣布B0；其unit完成和一次本批读回通过后，在同一发布锁下核对截至日仍稳定、已知基准差异已消除，然后append bootstrap_closed。B0属于第二阶段batch，沿用该批标准六字段header和unit_ids；无变化且无新周允许0-unit的plan/batch_closed/B0（header.max_input_week=null、写入数0）。实际Raw库存的行数/最早和最晚日期放B0.payload.inventory，parent闭合身份放payload.bootstrap_parent；DG bootstrap从Raw库存冻结范围，不用空补刷批的max_input_week推测历史范围。B0水位为该不可变记录的真实revision，factor_scan_end来自本次已验证上游窗口。

恢复与门禁：第二阶段已有持久化plan则只恢复原冻结代码/目标因子；中途取消不关闭B0。B0前因子截至日或必要基准再次变化，停止收尾并保留原批，不能改原计划、推进水位或隐藏源不就绪。日常publisher和DG reader均显式拒绝首次summary作为普通rows交付；B0捕获只核对header和Raw库存，不读取首次audit receipts。正反测试必须覆盖首次/后续完整范围、子范围不能冒充收尾、零变化0请求闭合、独立补刷计划恢复、原键保留、对账篡改拒绝、取消在audit及B0前、闭合后重放零源请求、月线/日常旧路径不变。

#### 13.15.2 代码对账及当前验收

stock_weekly_adj_planning.py受理两阶段并冻结第二批代码/目标因子；stock_weekly_adj_execution.py持久化0-unit计划、执行逐单元对账和B0，B0前取消仍保留未完成计划；stock_weekly_adj_delivery.py保存本unit未刷新键摘要，闭合前核验逐unit对账记录；stock_weekly_adj_reconciliation.py核对两层21列及未选原值；stock_weekly_adj_bootstrap.py负责首次补刷选择、对账及边界。DatasetDefinition的字段、输入及日期合同不变，没有新增运营配置、表或迁移。

第二批冻结第一批已有历史代码的目标日期/因子摘要；新增周中新上市的代码由该周源单元核验，不混入原历史目标摘要；B0前同时核对截至日及该摘要，防止同一天的因子修订被漏掉。对账阶段显示当前周/股票、已完成对账量、总量、百分比和更新时间，源单元完成量保持单调。源空/部分的剩余旧基准必须完全落在本次已记录的未返回键中，才可按source_unavailable保留并记入B0原因；不能用该口径放过本次实际返回且价格错误的行。

收尾SQL先对实际Raw的(code,end_date)去重并形成查询内CTE，再逐键使用Factor主键索引；每代码最后日线使用Daily主键反向点查。只向Python返回≤12,001条代码库存，超12,000或变化代码超过1000拒绝。CTE只是本次只读SQL中的计算，不创建表、不保存永久对账数据，也不用于日常历史门禁。

2026-10-12只读验收全部使用psql-remote.sh、READ ONLY、20秒statement_timeout，无导出全量行情或正式写入。控制结果：revision=10，bootstrap_closed=0；Raw week=2,896,823行，2010-01-01—2026-10-09；Daily和Factor均至2026-10-09。补刷库存SQL聚合返回一行：实际代码5,624，刷新前已知基准变化代码3,767，部分依据未知代码25；EXPLAIN确认因子主键点查及日线主键反向点查。3,767不是正式第二批清单，必须在第一批全量刷新后重新规划；当前不得因此申请放宽Prod1000单元预算。

专项：P1/P2/basis/P3/memory共110项通过。新增tests/test_stock_weekly_adj_p3_bootstrap.py的12项覆盖两阶段、0请求B0及重放、因子补刷、源空保留、新增周独立冻结/完整源要求、新股不会误触发历史目标变动、源值及保留值篡改、对账中和B0前取消恢复、同日因子修订、子范围拒绝及日常无历史门禁。原体系架构/registry/resolver/planner分组194项通过、1项既有失败：test_planner_compresses_trade_dates_to_month_end调用已经不存在的DatasetUnitPlanner._compress_to_month_end；HEAD同样没有该方法，本轮不改月线或恢复旧兼容方法。Definition lint、文档完整性及diff空白检查通过。CodeGraph使用explore/impact分析规划、执行、DAO与DG消费，修改后sync/status有效；动态Definition注册和SQL消费者另外阅读当前实现。没有改动子系统依赖边界。

#### 13.15.3 正式执行清单（未执行）

1. 先提交并部署本轮Prod代码；部署后只读核对源码版本、有效Definition及无另一个未完成周线批。既有真实小样本源/21字段验收不重复，本次正式运行需补取消—原意图续跑—读回及TaskRun/node终态验收。
2. 运营后台数据集“股票周线行情（复权）”（stk_period_bar_adj_week），maintain、范围2010-01-01—2026-10-09、ts_code留空；若执行日期已跨新完整周，先重新核验截止。当前范围876周；无交易周不请求源，其他周每页6000、单unit最多12,000、源调用45秒、业务事务20秒、单进程目标256MiB及批载荷256MiB不变。不清空原表。首批自然未完成时取消并从原详情恢复，完整对账通过后只生成batch_closed。
3. 再提交覆盖第一批完整范围的同数据集maintain，冻结关联第一批的独立补刷计划；展示实际新周/变化股票数。此时才知道补刷清单，不能预先填写刷新前的3,767代码。第二批对账通过并核对目标摘要，产生真实B0；未完成则恢复第二批，不另建新意图跳过。
4. B0及一次Prod对账完成后进入DG稳定捕获与年度覆盖，文件、事件、水位按DG LLD A17分阶段执行。现在没有真实B0，不能拿revision10的单股闭合批冒充全量边界。正式Lake、事件和sensor cursor均未改动。
