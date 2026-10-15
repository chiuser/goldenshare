# DG 月线单主源与定向历史修订 LLD v1

更新：2026-10-15。管理员已确认保留复权月线、物理清退独立未复权及定向修正8月。当前代码尚未改，本轮不写数据、不评价或启停sensor。总范围及删除协议见[周/月总方案](dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md)和[共享清退LLD](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md)。

任务已拆开：先独立完成重复数据集的代码清退和物理删除，再推进保留Raw补齐纠错。本文源/身份/覆盖/候选及预算要求用于第二条或日常月线合同，不是删除未复权月线的前置检查；8月修订和其他月份异常不阻塞第一条关闭。

## 1. 数据卡、来源与字段

| 项 | 保留合同 |
| --- | --- |
| dataset/asset/job | stk_period_bar_adj_month / raw_tushare_stk_period_bar_adj_month / raw_stk_period_bar_adj_month_update_job |
| 源 | stk_week_month_adj(freq=month)，doc365；历史bootstrap从Prod对应Raw原样接收，日常直接请求Tushare |
| 正式路径 | /Volumes/datasource/data_lake/raw/tushare/stk_period_bar_adj_month/month=YYYY-MM/data.parquet |
| staging | /Volumes/datasource/data_lake_staging/stock_monthly_raw下意图专属目录，与正式同卷 |
| 主键/分区 | (ts_code,trade_date,freq)，freq=month；cn_a_stock_months按YYYY-MM |
| checks | 原file_contract、key_partition、delivery_reconciliation三项，绑定最新物化 |

21列及Decimal与保留周线相同，见[周线字段合同](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#1-保留链的当前合同)。Raw日期/代码为VARCHAR，保留原始代码、单位、NULL和全部源值；不复制api_name/fetched_at/raw_payload等Prod内部信息。pre_close/pct_chg解释采用复权源口径，不能从字段同名推定两源所有语义等价。

时间输入为月份点/区间，planner展开月份；执行unit是一个源页/一个月文件，不是日线；完整性仅要求本月有实际交易的当前确认上市股票，整月停牌不造缺口。Raw保留退市源历史，但本轮不补退市缺口。

普通月请求日期为自然月末。2020-02固定20200228，排除20200229，不把28改29、不混合两版本。2026年8月请求trade_date=20260831；end_date是源计算截至版本，可晚于所属月，不能当采集时间，也不能用请求end_date选择一个历史计算版本。

本地源依据：[doc365](../../../docs/sources/tushare/股票数据/行情数据/0365_股票周_月线行情(复权--每日更新).md)、[doc336](../../../docs/sources/tushare/股票数据/行情数据/0336_股票周_月线行情(每日更新).md)、[北交所映射](../../../docs/sources/tushare/股票数据/基础数据/0375_北交所新旧代码对照表.md)。

## 2. 当前代码事实与缺口

- assets/stock_monthly.py、jobs/stock_monthly.py、checks/stock_monthly_checks.py仍定义两个主源；sensor枚举两源并共同推进。目标是只留复权，不是已经完成。
- stock_monthly_point.py以逐页CSV/Parquet/receipt、意图、source-month锁和候选持久化；既有create_or_identical遇异值产生revision_required，不能用重复提交或强改hash实现覆盖。
- source_readiness/stock_monthly.py对新交付按原Raw日线实际日期、confirmed身份和上游准确checks检查完整性；历史bootstrap只保真复制，未验证每股月末覆盖，是8月旧版本漏过的原因。
- checks只读当前分区及物化路径/行数，不再读取历史搬运材料。sensor从next_month(frontier)继续，不回查8月，也没有历史复权自动修订通道。

## 3. 2026年8月的已确认修订

两源各5,551行，trade_date均20260831。未复权截至25日1、27日1、28日1,235、31日4,314；复权截至25日1、27日3、28日5,547。Prod只读聚合和样本与DG一致，确认是旧源版本被无损接收，不是DG改日期。历史源最初采集任务尚未定位。

复权6只的较早截止覆盖其当月最后日线，其余5,545只未覆盖31日交易，至少5,401只收盘值不同。MCP当前平安银行月线截至20261015、close=11.72，旧DG截至20260828、close=11.65。002274.SZ和301139.SZ当前源截止也推进到10月15日，但价格与旧值相同，因为当月最后实际日线分别是25/28日。因此只用end_date不同不能证明价格错；必须结合实际交易和完整源行核对。

### 3.1 Prod精确写入面

| 数据集 | Raw | 现行交付表 |
| --- | --- | --- |
| stk_period_bar_month | raw_tushare.stk_period_bar | core_serving.stk_period_bar |
| stk_period_bar_adj_month | raw_tushare.stk_period_bar_adj | core_serving.stk_period_bar_adj |

仅freq=month且trade_date=2026-08-31。沿DatasetDefinition→DatasetActionResolver→DatasetExecutionPlan→request builder→现有Raw/Serving writer执行，不另起SQL直改或新worker。当前storage.write_path=raw_core_upsert但实际layer_plan=raw→serving，不虚构core行情表。正常事务同时更新源返回的本次键，不清表、不先删后插、不改变week或其他月份；Ops/TaskRun观测失败不能回滚业务提交。

本次Prod8月正常Serving维护是该独立数据修订的明确范围，与仍暂停的25股“不得发布serving”边界不混用。Prod两个数据集继续保留，DG退役不扩成Prod退役。

### 3.2 源冻结及对象语义

开工一次核对8月实际日线期望、当前上市集合和confirmed新码。对象历史请求只用当前有效新代码；全市场周期回包逐行判别新旧身份，新码记录才作为本次有效更新输入；旧码不自动兜底，新码缺失列缺口。Raw旧码存量不删除、不全表改码，未选旧键值保持并列未刷新原因。

优先单月全市场请求并有界分页，不发上市股票×历史月份请求。先完整封存源返回、页尾、列/键/日期、实际月末交易覆盖及行级摘要，再用于本次写入；三套价格和量额完整21列一起更新，不用未复权表的部分字段修补复权源。

### 3.3 DG覆盖执行器（待开发）

只覆盖保留的month=2026-08/data.parquet；即将物理删除的未复权DG月文件不再重复刷新。保留原普通create_or_identical入口语义，为已确认的有界历史修订增加显式入口/合同，不能吞revision_required或加无范围force开关。

请求/计划明确source、月份、有效对象/输入键、源完整证明、原文件强身份、实现/合同、候选和预算。复用monthly capture/locks/COPY/fsync/replace/checkpoint；源未返回的旧键保留，输入键整行覆盖，范围外逐字段不变。同卷逐文件原子替换，replace后checkpoint失败可由读回补完成，第三方目标漂移拒绝。正式事件/check只登记通过后的真实新文件，事件失败保留文件、只续补事件。

不把周线core.stock_weekly_adj_delivery扩成月线交接；优先复用本次固定源/Prod读回值的有界传输。源与Prod/DG必须核对同一批完整21列，不能在两次可变查询间混版本。异值覆盖入口需要先隔离测试和源码部署，实际写入另列精确命令。

### 3.4 其他月份与最终关闭

4月等月份end_date异常先读源确认，形成对象/月/字段/原因清单。新增确认问题单独报批覆盖范围，健康月份绝不重拉重写。未核实项保持显式待办，不能冒充本轮Raw全部验收通过。源未知、身份未决、真实空源与技术失败分开记录；退市缺口不处理。

## 4. 日常单主源调度与历史修订

保留raw_stock_monthly_update_job_sensor及19:30窗口、月frontier、真实上游绑定和取消恢复；移除未复权job/asset/check/双源循环。仅复权文件及其最新物化的三个检查通过才能推进月份；不能等待已退役检查或只靠cursor宣布完成。源晚到保留原意图，按既有下一窗口/明确手工续跑，不新增高频等待进程。

历史修订完成的月应形成真实变更周期，后续Silver处理该月；目前没有自动历史修订扫描，不在本轮私加全历史sensor。未来若要根据因子变动自动回刷月线，须独立确认范围、请求模型和能力，不把本轮8月定向修订当长期自动化已完成。

## 5. 配置审计与性能模型

现有唯一来源为StockMonthlyPolicy、MonthlyBootstrapIOPolicy、MonthlyUpdatePolicy，持久化到意图/receipt；原shared连接默认不能冒充局部预算。代码版本对新意图生效，恢复沿原合同，运行输出实际阶段/对象/完成量/最后更新时间。

| 配置 | 现有值/消费者及拒绝方式 |
| --- | --- |
| 源 | page6000、最多4页、重试2、timeout20秒、间隔1秒、并发1；builder/监督器/捕获消费，满页未闭合拒绝 |
| 月规模 | max_codes/max_update_rows=10000；planner/候选/检查；不静默截断 |
| 参考 | 最多31日线文件、320000参考行、10000代码、80参考SQL；source_readiness向量化聚合，不搬全月明细到Python |
| 上游观测 | 每日最多10个物化版本、每check历史320条、每tick2000记录；绑定当前目标，不读全历史 |
| 计算 | DuckDB512MiB、2线程、spill2GiB，RSS另测；候选同卷，控制文件1MiB |
| Prod导出 | 代码批300、fetch10000、unit10000行、SQL30秒、unit45秒、work_mem32MB、CSV64MiB、连接1；READ ONLY/ROLLBACK |
| 调度 | Asia/Shanghai、19:30、tick60秒；来源不变，单源有效frontier由保留数据实际ready决定 |

本轮待修DG8月只有一个完整文件，源两Prod数据集按分页实际调用记账；历史bootstrap201文件/源不能当刷新范围。候选/原件/源摘要仅本次运行保留，空间预检和实际写入增量结算，不每秒全目录扫描。上述值是现有基线，不作为新的更紧限制；样本证明不足时重评局部预算，不改全局、不强行切碎制造效率问题。

## 6. 改动文件与全部消费者

DG相对defs/：assets/stock_monthly.py、jobs/stock_monthly.py、checks/stock_monthly_checks.py、sensors/raw_stock_monthly_update_job_sensor.py、stock_monthly_point.py、stock_monthly_update.py、stock_monthly_update_state.py、source_readiness/stock_monthly.py、run_contracts/stock_monthly.py/configs.py/asset_column_schemas.py、catalog/lake_assets.py/name_mapping.py及实际无消费者的paths定义。bootstrap历史CLI/capture/promote/events和prod_db适配器需同步禁用退役source新写入，不能遗留手工入口。共享weekly_event_binding和月分区定义保留。

Prod的8月维护入口按现行Definition和参数消费审计，不改数据集date_model或一般API；若增加新码选择/覆盖合同，须迁移resolver/planner/request builder/writer、全部消费者及模板，先隔离验证。所有代码变化与文档同步，本轮尚未实施。

## 7. 正反验收与实施顺序

第一条删除沿共享LLD，只做旧定义/写入口清退、共享sensor/函数保留、目录边界及删除结果核对；不读取待删月线内容。下列步骤仅为第二条Raw修订验收，不要求为删除先执行：

1. 隔离验证单月源封存、同值重放、新码选择、精确覆盖和取消恢复；字面金样本独立于实现。
2. 源未完整、旧码兜底、页尾缺失、身份无确认、字段精度损失、20200229、月底实际交易遗漏、未知新增月份、目标漂移、候选篡改均拒绝。
3. 先完成同批源/Prod Raw及Serving读回，再生成DG候选；前后双向比较输入完整行及未选旧行，8月以外两个Prod表freq/month和week范围保持。
4. 获准提升后逐文件读回并登记准确事件；进程退出/replace后未记状态可续跑，观测错误不回滚，已完成不重算/重下载。

第二条相关测试为test_stock_monthly_contract/definitions/update/history/events、test_stock_period_checks及实际改到的直接消费者，新增修订测试覆盖异值更新/保留行/未知范围拒绝。第一条只选定义、sensor、旧参数拒绝和共享函数的针对性测试，不默认跑上述全部修订或历史生成测试。删除测试只用临时目录，不拿正式文件制造故障。

## 8. 后续Silver设计边界

拟silver_stock_monthly依赖唯一保留Raw，路径silver/quote/stock_monthly/month=YYYY-MM/part-000.parquet。标准化日期、Decimal保精度，按confirmed身份和完整版本选整行，保留三套OHLC。初次只生成确认的当前上市范围，退市缺口不补、不擅自清理历史。当前源完整覆盖及新码版本未解决前不能正式生成。

历史初次生成按年度/有界批处理，逐文件候选、原子提升和checkpoint、一次收尾；日常只处理新月或实际修订月。schema/catalog/partition/check/job/触发/取消及事件合同在独立Silver阶段明确后实施，本轮不先写Silver或引入派生指标。

<a id="12-m10c-落地与验收2026-10-05"></a>
## 9. 有用历史事实与旧执行卡退出

2026-10-05 bootstrap两源共402文件、1,414,335行；源1,421,699减20200229两源共7,364行守恒，保留源NULL，不代表当时每个历史月的业务完整性通过。逐年度全字段运输差集0的事实仍有效，8月完整性结论现已纠正。

2026-09两主源各5,571行，新月自动交付/正式主动取消当时另留实际运行验收；本轮单源迁移必须按新合同重新验证，不继续使用旧“两主源验收卡”。身份曾对全表历史代码误阻断，已改为全表基本约束+本次引用对象严格验证，保留该语义。

<a id="后续真实验收执行卡2026-10-06准备完成"></a>
旧启用/双源正式执行卡已退出，不再逐条抄旧命令。历史证据见[日期报告](../../../reports/stock_period_raw_closeout_20261006.md)，不是当前运行依赖。
