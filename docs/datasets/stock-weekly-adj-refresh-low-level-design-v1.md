# Prod 股票复权周线刷新代码级 LLD v1

起草：2026-10-09；设计收尾：2026-10-10。状态：设计稿完成，待 P0 专项评审及验证；未开发、未迁移、未部署、未同步。本文件按 [Prod 数据集开发模板](../templates/dataset-development-template.md) 的0—10节复制结构并填写；模板提示文字不作为项目内容重复保留。

业务范围和阶段以 [方案](stock-weekly-adj-refresh-plan-v1.md) 为准。DG实现仅引用本文交接合同，其余见 [DG LLD新增阶段](../../lake_console/docs/design/dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#adjusted-weekly-prod-refresh-lld)。本文件出现的新增类、表、配置、错误码均为拟实现，不代表当前支持。

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
| 复权因子 | 本轮000001.SZ、20260610—20260925，76行；相邻样本证明20260612和20260924变化 | 本轮区间响应最晚20260924，未据此认定20260925完整；P0逐日点查并与Prod因子覆盖对账 |
| 默认/显式/业务关键列 | 本轮默认对象、显式点、显式区间均含ts_code/trade_date/end_date/freq/qfq/hfq/vol/amount等21列 | 三类核验已做；未知字段/NULL/精度风险仍由本次unit校验 |
| 分页、后页、短页、集合和值 | 原M0三接口6页合计52行、键/值一致，主源6000后页空；MCP工具不暴露limit/offset | 原SDK证据不是当前项目connector实测。P0用实际connector、单股票短历史limit=10验证基准、多页、终空页；编码前完成，不以mock代替 |

原始MCP响应本轮只保存在会话/临时审计材料中，不作为交付运行依赖。并行调用耗时约5.4—10.9秒含服务端排队，不作为串行生产请求承诺。

#### 0.3.1 三层语义拆分表

| 层 | 本次答案 | 核验与设计边界 |
| --- | --- | --- |
| 时间输入 | 沿用point周五或range日期范围；ts_code单值可选 | 现有Definition/API不新增源端可选参数；自动只传“更新已结束周”的调度意图 |
| 执行unit | 首次全市场range按周；指定代码range保留一个区间；自动point生成新周及变化代码历史区间 | §4.4.1、§6.2；range不是清空；历史unit与输入周日期不同须显式保存 |
| freshness/audit | natural_day/week_friday、iso_week有交易才要求周桶；observed_field=trade_date | 历史刷新不改周桶日期，不把end_date当行情日期；没有交易的周不要求非空 |

#### 0.3.2 DatasetDefinition消费者审计表

本轮核对Definition、resolver、planner、builder、executor、writer、DAO、TaskRun及DG来源消费者。下表区分已读关键实现与开发前需完整追到的展示/自动化消费者；未做浏览器验收。P0不能仅靠文档把最后一列改成通过。

| 消费者 | 当前入口 | 需要处理 | 验收阶段 |
| --- | --- | --- | --- |
| manual actions/catalog | src/ops/queries/manual_action_query_service.py、src/ops/services/manual_action_service.py、src/ops/catalog/dataset_catalog_views.py | 身份、point/range、单值ts_code保持；新增内部策略不暴露为表单源参数 | P0完整审计、P1合同/API回归 |
| workflow | src/ops/action_catalog.py及维护工作流消费者 | 扫描该action引用；range语义改为高效区间时同步计划预览 | P0引用清单、P1测试 |
| resolver/planner | ingestion/resolver.py、unit_planner.py、execution_plan.py、plan_helpers.py | 具名unit builder、冻结意图及恢复上下文；不复用公告专用freeze函数 | 已读主链；P1 |
| request builder/source | ingestion/request_builders.py、source_client.py | 显式历史区间、统一21列、取消/硬截止、分页计数 | 已读主链；P0 connector实测、P2 |
| writer/DAO | ingestion/writer.py、dao/base_dao.py、stk_period_bar_adj_dao.py | 新具名write path；按三列主键更新；业务交接同事务 | 已读主链；P1/P2 |
| freshness/cards/snapshot | datasets/freshness_policies.py、ops/queries/freshness_query_service.py、dataset_card_query_service.py、services/operations_dataset_status_snapshot_service.py | trade_date、表映射及频度过滤不变；交付进度不是业务freshness | P0全消费者审计、P1回归 |
| 日期完整性 | ops/services/date_completeness_audit_service.py、dataset_observation_registry.py | 保留freq=week和无交易周规则；不把修正次数当日期覆盖 | P0逐项核验、P1回归 |
| 自动时间策略/排程/probe | ops/services/dataset_schedule_time_policy_resolver.py、schedule_service.py、schedule_planner.py及运行时排程链 | 新“最后已结束自然周”意图策略；19:30排程仅本数据集；现有month分支保持 | 已核对策略及schedule模型；P0 runtime全链、P2 |
| TaskRun/详情 | ops/runtime/task_run_dispatcher.py、ingestion/progress.py、models/ops/task_run及node | 当前计划预览截断20units，不作续跑依据；独立进度/终态写入 | 已读执行及模型；P2浏览器 |
| 前端时间控件 | Manual Action合同消费者、自动任务时间策略类型及任务详情组件 | 不写dataset_key日期转换；按API合同派生 | P0找到真实组件和类型、P1/P2浏览器 |
| DG | assets/stock_weekly.py、jobs/stock_weekly.py、raw_stock_weekly_update_job_sensor.py、bootstrap/prod_db/io/checks | 复权来源及覆盖合同迁移，其他来源保持 | 已读主链；D1/D2 |

不修改date_model/input_shape/observed_field；增加planning/storage策略仍需上述消费者和shared model默认值回归。完整未覆盖入口在P0填实际文件/测试，不冒称已做全量消费者验收。

<a id="source-field-contract"></a>

#### 0.3.3 源字段端到端对账表

共同证据：本地doc_id=365、本轮三类MCP响应；当前Definition请求21列；Raw/Serving ORM已核验；DG weekly_column_specs已核验。生产实表/迁移一致性以原M0为历史依据，P0重新查只读系统目录。表中“迁移/实表”均为待P0复核，不预填当前真实表通过。

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

### 4.1 identity

dataset_key/display_name/aliases沿现有定义；description补充“因子变化后刷新对应股票已有历史”；logical_key/logical_priority沿当前构建默认值，不新建逻辑身份。

### 4.2 domain

equity_market/股票行情不变；freshness引用当前FRESHNESS_POLICY_BY_DATASET，不在domain加节奏或DG交付状态。

### 4.3 source

source_keys=(tushare)，adapter=tushare，api=stk_week_month_adj，fields=0.3.3全部21列，doc_id=tushare.stk_week_month_adj。保留现有request_builder_key，base_params固定freq=week或builder唯一生成，不能两处不同值。release_policy沿现有合法枚举；晚发布由本批完整性门禁表达，不造新字符串。

### 4.4 date_model

natural_day/week_friday/point_or_range/trade_date_or_start_end，observed_field=trade_date，audit_applicable=True，bucket_window_rule=iso_week，bucket_applicability_rule=requires_open_trade_day_in_bucket；not_applicable_reason=None。字段不变。

### 4.4.1 时间意图归一化设计

Ops保留point/range时间意图，自动策略只生成“更新最后已结束周”。resolver归一化周界、历史截止和因子扫描窗；planner生成显式unit时间。历史unit用自己的start/end，不能继续使用新周anchor。builder只格式化YYYYMMDD。

首次all-market range逐周规划。指定ts_code range为单股票区间。自动point先恢复未闭合批次，再选择最早未完成已结束周；不跳过欠账。手动历史point/range形成修订批次，不推进自动周frontier。

区分意图使用现有DatasetActionRequest.trigger_source及time_input/filters；不加供运营选择的模式参数。具名freeze函数将scheduled_week、historical_refresh或manual_revision及原trigger_source冻结到plan/execution_context；重试恢复冻结意图，不能因为重试由人工点击就变成manual_revision。ValidatedDatasetActionRequest已有trigger_source，但当前DatasetExecutionPlan无独立该字段，P1须显式完成该信息的合法投影及所有重试消费者迁移，不能在builder中猜触发来源。scheduled_week才能推进自动周/factor frontier；人工范围修订只交付其明确范围。

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

现有两表按源码为普通表，原M0只确认三列主键索引；本次不重建/分区存量表。按代码历史修正走主键范围；全市场单周读回需P0 EXPLAIN决定是否加仅week的trade_date索引。新增索引不凭文件名猜既有结构，性能样本证明必要性后落迁移。

### 5.2 工程硬约束

不改行情字段/类型；新业务交接表只append，不ALTER/DELETE旧行情。P1先执行当前环境alembic heads，再生成revision/down_revision；本设计不预填迁移ID。ORM必须进入table_model_registry；迁移、PG约束及SQLite隔离测试替身一致。

### 5.3 DAO

沿用Raw/Serving DAO和BaseDAO bulk_upsert；在调用前完成unit冲突/范围校验。拟新增StockWeeklyAdjDeliveryDAO及DAOFactory属性。DAO只做SQL/幂等读写，不决定周界、因子名单、调度或重试。

<a id="delivery-contract"></a>

### 5.4 唯一业务交接合同：stock_weekly_adj_delivery/v1

**必要性评审。** 单unit数据在Prod与DG两个进程中交付；Raw会被后续更新覆盖，TaskRun摘要截断且观测允许失败。仅metadata/cursor/fetched_at不能同时证明完成范围、恢复和稳定版本。因此提出一个专用Foundation表，不新增DG状态实体。P0须审核这一必要性及容量，未完成评审不得建表或将它推广为通用框架。

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

**保留与退出。** 交接payload是可重放业务增量，不是搬运证明；日常只读未交付批次。本轮851行样本将数值转字符串后，JSON约333,440字节，约392字节/行。外推新周5559行加20股票各851行约8.85MB/周；固定四位精度、JSONB和索引另计，P0测真实存储，不使用源矩阵146字节/行低估对象payload。不设计自动DELETE、归档服务、永久全历史复核或reports依赖；清理需确认DG水位、保留窗及另获明确清理授权。停机超过可读取范围时走受控bootstrap，不假装cursor可以重建丢失payload。

## 6. Ingestion实现设计

### 6.1 请求构造

_stk_period_bar_adj_week_params按unit自身归一化时间格式化：point只trade_date；stock_history只ts_code/start_date/end_date；freq固定week；fields始终来自Definition。builder不读数据库、不选日期、不拼变化代码。不能因为原request是point而把history unit再次发成point。

### 6.2 Unit规划

拟新增ingestion/stock_weekly_adj_scope.py，提供freeze_weekly_adj_execution、resolve_weekly_adj_units、load_changed_codes、validate_weekly_adj_source_basis。注册unit builder，不直接复用_stk_factor_pro私有函数或公告freeze函数。

自动扫描范围：(上次闭合factor_scan_end，本次已结束周最后开市日]，每个d与前一开市日比较，取并集；先校验每日期覆盖及相邻值。范围最长一个待处理周，遇长停机按最早周恢复；raw最早日期按变化代码一次GROUP BY，不逐代码SQL。新股无前日行分类为首次出现；有历史却缺相邻因子列pending。

unit_id=hash(contract_version,batch_id,unit_kind,ts_code,规范时间窗,scope_digest)，同冻结批恢复稳定。progress_context保存中文阶段、当前代码/周、窗口、unit序号；不可全量放进cursor或TaskRun摘要。

首次按周约876unit，上限1000；自动1+K，上限1000及整批payload256MiB。超限在计划冻结前明确报预算错误，显示完整待处理范围，等待获准调整范围或局部预算；不自行拆自动批次、不推进factor frontier。首次期间若因子变更，先补单股全历史后生成bootstrap_closed。

### 6.3 Source Client与分页

评估复用source_client分页迭代，增加受具名策略控制的调用监督/取消/预算；不能把公告的专用policy对象当周线policy。源请求在可终止子进程，硬截止20秒，正常页前后检查取消，≤2秒查询独立取消；本地隔离替身证明超时/终止及不泄漏token。

一个unit最多3页/12,000行，源响应和normalizer结果都计入256MiB RSS目标；首次全部876周不常驻内存。满页继续拉，超量整unit不提交。每页持同fields/筛选；若同一股票历史出现不能解释的多个basis factor，停止重取该unit而非接受混合基准。connector实测见0.3.0/P0。

### 6.4 Normalizer

沿用现有Decimal/date/row transform；补scope和batch-key冲突验证。同键同值去重计数，同键不同值报weekly_adj.source_key_conflict；空、越界、缺主键、NaN/Infinity、精度溢出不静默截断或填0。不强制修订历史原始异常；旧键保留的原因独立记账。

### 6.5 Writer

拟新增ingestion/stock_weekly_adj_delivery.py，具名路径内完成范围验证、分层upsert、payload标准化和交接append；通用writer注册分派，保留其他路径行为。核心接口publish_unit(session,definition,unit,batch)->CommittedUnitDelivery；publish_closed_batch只在冻结unit闭合后调用。

cancel-before-commit回滚该unit，commit-after-cancel仍按实际完成记录恢复，不能宣称没提交；每个unit之后检查取消，不领新unit。独立Observer调用不能把已提交unit再次记为失败；当前_process_fetched_unit/report_progress交互需正反回归，不仅补异常catch。

### 6.6 结构化错误与codebook

拟新增weekly_adj.scope_mismatch、source_key_conflict、source_not_ready、basis_not_updated、factor_coverage_missing、row_budget_exceeded、delivery_contract_mismatch、writer_busy、source_empty_preserved、partial_source_preserved。每码在codebook登记中文含义、阶段、可重试性、样本和动作。超时/网络/认证/限流沿现有分类；“未刷新”不是网络失败的别名。

基准验收至少选择旧历史周close，用该周最后交易日因子和源basis_date因子独立核对至源价格精度；周中除权的OHLC不能用整根周K同一个因子替代日内复权聚合。没有独立基准时保持basis待验，不靠输出证明输出。

### 6.7 配置审计与性能预算

| 配置 | 默认/来源及持久化 | 消费者/生效/可见性/测试 |
| --- | --- | --- |
| weekly_adj_policy | Definition planning中的具名策略；冻结到本批plan | resolver/planner/executor/linter；代码部署后新意图生效，恢复要求合同一致；计划详情及合同测试 |
| page_limit / max_source_rows / max_pages | 6000/12000/3，Definition及具名policy | source/executor；页序列可见；满页/超量反例 |
| source_timeout / cancel_poll / progress_interval | 20秒/2秒/5秒，policy | 监督进程/observer；日志显示阶段和超时；取消与30秒可见测试 |
| db_statement_timeout / lock_timeout | 20秒/2秒，policy，SET LOCAL | writer事务；超时分码；lock/rollback/重跑测试 |
| max_units / max_payload_bytes / max_plan_bytes / max_batch_payload_bytes | 1000/8MiB/1MiB/256MiB，policy及PG CHECK/批闭合校验 | planner/DAO/导出；超量不执行；容量反例，与DG总量一致 |
| fetch_concurrency / memory_target | 1/256MiB，policy和Definition | 单unit缓冲；压力样本RSS，超过预算停手重设 |
| 19:30、Asia/Shanghai | ops.schedule的cron_expr=30 19 * * *及timezone | 现有scheduler生成意图；运营排程页可见；不在migration seed，启用另批 |
| delivery source/table/contract | Definition storage及Foundation交接合同v1 | writer/DG只读白名单；部署同时迁移；跨表/freq/未知版本拒绝 |
| 日期起点/截止 | 运行读取Prod库存/权威日历，冻结plan | planner；不新增env硬编码2010；首周/跨年/长假测试 |

现有全局Settings、Tushare token、PG连接来源不改。不新增.env配置或页面常量。DG资源和预算在DG LLD维护，避免两侧常量不同。

首次源约876首请求、最多每unit3页；实际短页通常1次。初次周捕获按基线2.9百万行，Raw+Serving约5.8百万行分unit提交。每unit读回只本范围；完整对账仅首次一次。20变化股票约17,020历史行加5,559新周行，约21首请求；实际完整范围和页数P0复核。交易日因子扫描≤前日+本周5日，不扫描全历史factor；日期覆盖缺失时不扩大查询。

## 7. Ops、TaskRun与页面派生

### 7.1 手动任务

继续使用现有dataset maintain入口、point/range、可选单值ts_code。新scope/执行token由后端生成和冻结，不让运营输入SQL、freq或checkpoint位置。重试原意图必须显示原时间/股票范围及已有完成量。

### 7.2 自动任务

以ops.schedule现有dataset_action机制持久化19:30排程，初始化inactive，既有受理/并发去重/worker路径复用。新增时间策略只生成“最后已结束周”意图，resolver才决定source参数；当已有未闭合批时先恢复，同周闭合后不重复下载。源未完整当晚任务失败/待重试，下一日19:30恢复；不附加高频cron或后台等待。

P0审计既有同dataset排程，切换时防重复写者。因子、日历、日线的正式写者保持，不顺手把它们塞进周线workflow。Prod依赖已完整业务数据，Ops观测仅辅助诊断；不能因快照状态写失败阻断已有事实读取。

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

- [ ] P0：当前connector多页和基准、逐日factor覆盖、Prod库存/索引及全部消费者、专用交接必要性/容量评审。
- [ ] P1：Definition/Plan/linter/模板、ORM/迁移/DAO、默认None消费者、三列键及freq回归。
- [ ] P2：完整小样本行数链、取消/退出/续跑/幂等、观测失败、浏览器进度及source basis。
- [ ] P3：源刷新一次全量键/值对账，保留未刷新/失败分清，无删除。
- [ ] D2/D3/J1：DG实际接收、正确覆盖、正式事件/check、一次bootstrap对账及19:30端到端验收。

### 8.4 阶段完成记录

| 阶段 | 本轮结果 | 未完成/下步 |
| --- | --- | --- |
| 设计编制 | 业务决定已确认；本轮文档、关键代码审计和MCP参数/字段样本已完成 | P0其余实测/消费者与结构评审待执行，不宣称P0验收完成 |
| P1—J1 | 未开始 | 代码、迁移、部署、写入、自动切换均未执行 |

## 9. 发布与回滚

1. 先完成P0与结构评审；P1迁移只新增专用交接对象和经EXPLAIN证明需要的索引，不清空/重建行情表。down_revision取实际head。
2. 小样本在获准环境完成后部署Prod，再加载DG新定义但保持新路径未启用；旧复权源自动分支在切换阶段停用，未复权和月线继续。
3. 获准执行Prod首次刷新、一次对账、DG bootstrap文件阶段、事件阶段；B0只有DG全部文件和事件就绪后才设为交付水位。两阶段不能顺手合并写入。
4. 正式计划和完整命令在执行前冻结，写明环境/范围/批量/取消/恢复；本LLD不捏造当前CLI已支持新策略或预填真实验收结果。
5. 验收SQL限定freq=week、选中代码/日期，核对源/标准化/Raw/Serving/交接payload键和值；月线及未复权分freq摘要作不变证据，不做全表深扫。
6. 回退停止新触发，保留已提交unit、交接和DG checkpoint，修代码后同意图恢复。不得删业务表/旧数据回滚；不得重新启用DG直拉复权作为双轨兜底。迁移降级不自动DROP有业务数据的交接表。

## 10. 本次交付快照

当前支持仍为旧的Prod维护及DG直拉新周；本方案的历史因子刷新、业务交接和DG统一来源尚未实现。本轮仅完成设计文档和只读样本。下一步P0完成编码前证据及最小持久化技术评审，随后P1开发；全量运行和启用按各阶段另获明确授权。

2026-10-10文档收尾：Prod方案/LLD、DG原方案/LLD的新阶段及docs/README已同步；文档完整性、20个新增设计链接/锚点及diff空白检查通过。不改变子系统依赖矩阵；未运行代码测试、迁移、正式同步或sensor切换。本节结果不能用于替代P0—J1验收。
