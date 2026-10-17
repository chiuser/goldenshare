# DG 复权月线Raw更新、完整性审计与Silver生成 LLD v1

更新：2026-10-17。**月线Raw重建、一次完整性审计及Silver首次生成/正式验收均已完成。** Raw431文件/868,690行、baseline=ready，截止2026-10-16；审计595,608个应有股票月全部覆盖，缺失与最新版本冲突0。Silver实际154文件/595,608行，字段/值同Raw，154物化/462项blocking检查通过。首次结果见共享LLD §10.10。**剩余1—3项设计已提交并获准开发；第1项共用恢复逻辑出现已复现的门禁冲突，已暂停，见共享LLD §11.10；月线自动接线未开始，日常代码未提交/未验收。** 本轮正式操作为0，Prod后置、R3继续暂停。

目标/阶段见[总方案](dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md)，完整字段、北交所请求、捕获/候选/恢复、性能与正反验收唯一引用[共享LLD](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md)。本文只记录月线差异，旧逐月修补及Prod搬运步骤退出DG方案。

## 1. 数据卡、来源与字段

| 项目 | 合同 |
| --- | --- |
| dataset / asset | stk_period_bar_adj_month / raw_tushare_stk_period_bar_adj_month |
| job / partition | raw_stk_period_bar_adj_month_update_job / cn_a_stock_months |
| 源 | Tushare stk_week_month_adj，freq=month，doc365；新设计不从Prod bootstrap |
| 正式文件 | /Volumes/datasource/data_lake/raw/tushare/stk_period_bar_adj_month/month=YYYY-MM/data.parquet |
| staging | /Volumes/datasource/data_lake_staging下本次运行专属目录 |
| 业务键 | (ts_code,trade_date,freq)，实际源日期原样保存 |
| 业务字段 | [共享LLD的21列](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#source-field-contract)，三套OHLC全部保留 |

bootstrap与单股复权刷新的业务参数为有效ts_code、freq=month，另显式fields及技术分页参数limit/offset，不传时间参数；北交所只用确认新码。当前月及月线欠账均请求freq=month、start_date=目标月首、end_date=自然月末，过滤的是trade_date，确保同月28/29等不同源键都能返回；请求方式参考Prod的HTTP POST格式，但在DG自身实现、沿DG环境接token，不导入Prod Settings/客户端或安装Prod项目；其他DG资产仍用原SDK方式；月份未结束也刷新同一月文件，日期不改成当天或最后开市日。2026-10-16凌晨实测20261031已有截至20261015的数据。

## 2. 2020年2月的两条源记录

旧实现固定保留20200228、排除20200229，已经不适用于保留完整源回包的新设计。2026-10-16以000001.SZ+month、不传时间实际返回427行，其中：

| trade_date | end_date | close | close_qfq |
| --- | --- | --- | --- |
| 20200229 | 20261015 | 14.50 | 11.14 |
| 20200228 | 20250910 | 14.50 | 12.01 |

两行同属month=2020-02但原始业务键不同，Raw均保留全部21列；不能把28改29、固定丢29日或在Raw按月份/证券只留一行。Raw月线完整性检查必须允许这个已实测来源事实，同时仍拒绝同一原始业务键的异值冲突。原日期分类、排除计数、候选、检查及测试一起迁移，不能只改说明绕过旧门禁。Silver已确认按最新end_date择取完整行：本例选20200229/end_date=20261015整行，不能因28日为交易日而选旧版，也不能拼字段；同一最新计算版本业务字段相同可以合并，异值冲突列明并拒绝通过。唯一细则见[共享LLD §9.2](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-completeness-audit)，不在Raw提前删版本。

<a id="3-2026年8月的已确认修订"></a>
## 3. 旧数据问题如何结束

旧DG8月有大量月底前版本，平安银行close=11.65/截至20260828；2026-10-15源样本close=11.72。4月等还存在旧截止与复权价格差异。新路线先删除旧月线Raw根（与周线两根同时完成），再下载所有选定股票的完整源历史；8月及其他月份只由新源返回构建，不再为每个月建立修补入口或先全量对比旧DG。

本数据集仅保留确认仍上市股票的行情；退市股票不请求，全市场日常回包中的退市行也不入湖。旧月线根整体删除，不读取旧文件逐行剔除、不合并旧键、不保留源未返回的旧行情、不用旧Prod兜底。换码不等于退市，旧码禁止出站请求，新码获取完整历史，Raw不把旧行直接改名。原只读覆盖/搬运证据可追溯但不重复跑，不要求先从日线证明所有历史月份完整，不用日线合成月K。

月线固定删除目标仅为/Volumes/datasource/data_lake/raw/tushare/stk_period_bar_adj_month，周线根及共同删除门禁见[共享LLD](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#31-删除边界与数据空档)。先完成新程序隔离验收、样本验证及唯一写者切换，删除完成再启动正式bootstrap。进入下载后续跑不得再次清空根；成功片段与已提交新文件继续复用。删除后的缺数窗口不能凭旧物化判定月线就绪；未完成对象明确记录，无旧数据回退。

正式删除边界仅限两套Raw，不涉及Silver或其他数据集；第8步已按批准完成删除重建，恢复不得再次清根。后续以验收后的Raw生成Silver，不把其他系统的月线维护列为开发步骤、前置或验收项。

第8步正式重建、收尾补更与登记已完成。已完成的5,577股月线bootstrap不重复下载；收尾按确认的45股统一重下月线完整历史，并补取当前月，共46个首次收尾单元/46页、12,952源行与准入行。397个月文件统一组装、校验及逐文件原子提交，月线最终仍431文件/868,690行。显式6GiB执行额度不改变原policy、父子run_id/hash或DuckDB3GiB；多片段归并保持21列、Decimal/NULL和20200228/29两个业务键。RSS及归并修正历史见共享LLD §5.11—5.14，完整正式对账唯一见[共享LLD §5.15](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#step8-complete)，不再复制旧停点或重复采样。

## 4. 日常覆盖与历史刷新

每个交易日先按已有完成记录补未完成月份，再更新当前月；月末失败次月仍须补原月，按月份去重，不逐日重放、不扫描历史行情找欠账。首次月初即写入月末坐标，不等next_month(frontier)变成已完成月。当天刷新、整月最终交付、历史刷新和事件待办分别观察；旧源未发布不能记当天成功，历史失败不能被当天刷新记录挡住续跑，月中成功不等于月末最终交付。停牌股的end_date不必等当天，历史end_date晚于trade_date也是合法源计算版本。

因子通知共用同一目标股集合并下载周/月两频完整历史；月线执行部分只替换目标股月线行，不能误改其他股。单独选定月线的历史替换不改未选频率。确认month完整非空成功后，移除该股源已不返回的月线旧键，包括只有旧键的分区。空源/缺页/失败不替换。必须在提交前与本批当前月/欠账回包统一汇集，受影响月文件只组装/校验/提交一次，不先upsert再history。重叠同键全字段一致可合并，异值停止并留证。目标前像变化拒绝覆盖，挂载/持久化及事件阶段共用共享LLD §3—4。首次bootstrap按先删后建执行，不读旧行情、不继承旧键，不增加旧数据核对或逐行清理。同一意图完成的月片段跨日可恢复，新主动刷新必须有新意图并请求新历史，不能用固定manual身份命中旧缓存。日常触发与周线共用现有相邻交易日因子差异；bootstrap和主动历史下载无需通过因子变化检查，直接保存最新源历史，不本地重算复权价。不引入独立历史因子探测或月线全历史扫描sensor，不包含日线、分钟及指标历史修复。

月线asset/sensor/check已接入共用直接源链；旧point、Prod库存/计划/预算及整月日线上游辅助模块已按第6步真实引用闭包清退。当前月允许按源完整行更新，没有通用force开关；同一文件版本复用验证事实。第七步组合及日历补验的边界见共享LLD §5.8—5.9；后续第8步已按批准加载定义并完成正式月线重建及收尾，物理结果和登记证据见共享LLD §5.15。

## 5. 改动范围与最小验收

三股两频源样本已保存，month分别427/78/1行，完整21列，不重复下载。原审计分类见共享LLD §5.3；前五步已纠正Prod导入、意图身份、失败留证及重复组装，补齐状态/恢复/有界交接、预算、目标保护与持久化；169项离线、5项进程及最终policy修正后的21项消费者历史证据见§5.4—5.5，不能把重复执行累加为不同覆盖。独立CLI handoff和真实运行检查继续沿用；第6步自身三项治理通过。第7步原155项回归的日历相关验收撤回，本轮按真实trade_date DATE/is_open BOOLEAN修正夹具后，月线sensor、handoff和实际job/check随44项受影响回归通过，详见§5.9。此前环境中已安装的包不因本次清退而卸载。

bootstrap跨日交接记录实际下载区间，只补期间月值、真实因子及上市集合变化；个股陈旧end_date不能拖回多年欠账。文件阶段先保存files_complete，事件失败直接补事件；当前月外层asset真实物化/check未完成前不得内部冒记成功。配置、预算、必要检查复用及异常源留证唯一遵守共享LLD，不复制第二套实现或限制。

开发影响限定既有月线asset/job/check、sensor、合同/config/catalog、历史CLI及共用周/月执行器；旧链专用模块随消费者迁移清退。保留分区名和asset key，不改Prod应用或其他Tushare资产。

复用共享LLD §7需求矩阵中适用的正反证据，实际失效或新增部分才补测。月线必须持续覆盖：自然月末为周末仍可请求，月中更新不推进已完成月，20200228/29均保留；因子两频历史替换移除旧键且不误改其他股/未选频率；月末失败跨月补交、不逐日重放；异值冲突、空源、缺页、身份异常不替换/不冒记成功；退市不出站且测试Raw无退市行，进入下载后恢复不再清根。历史生成、当前月更新、取消、事件失败分别有证据，不能拿旧双源通过替代。正式Raw证据见共享LLD §5.15，Silver首次完成见§10.10；后续日常设计见本文§8，不重复扫描正式Raw或重做首次生成。

### 5.1 第6步的月线清退边界

按共享LLD §5.6处理run_contracts/stock_monthly.py中的旧Prod库存/计划/IO预算及monthly_point_request；该构造器的自然月末单点请求和旧4页上限不是当前月范围分页合同，不能为保旧测试而保留。保留月线column_specs、normalize_month_key、asset/job/check/分区及现行路径；MONTHLY_UPDATE_POLICY中sensor实际依赖的配置不改变生效值或入口。

stock_monthly_update.py、stock_monthly_update_state.py的旧“仅已结束月份”规划及整月日线上游事件扫描，按无生产消费者的闭包清退。原weekly_event_binding跨月线依赖已核实只在旧模块闭包内，随闭包清退；现行文件检查独立保留。测试中只验证退役库存/point/日线上游实现的部分删除；20200228/29、合法NULL/Decimal和月键等有效断言先保留到新主链测试，再清旧承载。补月线三项检查在既有ASSET_CHECK_GOVERNANCE中的登记；不放宽全仓断言，不改其他数据集。catalog格式差异保留在工作区，不整文件回退或混入提交。具体文件清单唯一遵守共享LLD，不扩展到月线Silver或Prod。

### 5.2 第7步的月线组合验收

月线加入共享LLD §5.7的同一个小型场景，不另跑一套月线bootstrap：用少数股票、两频和跨周/月边界，验证上月欠账与本月刷新按月去重、变更股两频历史在同一批汇集，以及一次取消/事件失败后的原意图续跑。通过真实月线asset job和三项blocking checks确认分区与目标物化；外层anchor未完成时不能内部冒记事件成功。20200228/29等已有金样本引用已有覆盖，不为这个场景再次下载全部月线历史或扫描整月日线。

只补真实HTTP执行器及少量事件的缺失成本，已有文件/恢复性能证据适用时复用；测量不自动带来新配置、并发或更紧上限。最终按共享LLD固定版本回归和逐项对账，Raw程序验收不等于正式bootstrap、sensor交接或Silver完成。本轮仅用临时根、localhost和独立instance；组合场景两频真实job/check及同日待办补记均通过，后者不请求源、不跑SQL或改写文件。管理员已确认最小修正：仅查询最新已完成检查（含失败），保留全部通过/分区/实际物化门禁；当前组合和5项状态正反测试通过，月线待办已关闭。旧失败现场保留，完整证据及性能见共享LLD §5.8、§6.1；正式操作继续另行review。

<a id="12-m10c-落地与验收2026-10-05"></a>
<a id="后续真实验收执行卡2026-10-06准备完成"></a>
Raw完成后，本文§6及共享LLD §9的一次完整性审计已通过；本文§7月线Silver也已生成，不重下源。共用仍上市集合、保留全部21列及源日期字符串，身份/日期解析只用于选行，按最新end_date选完整行。以[共享LLD的上市周期边界](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#silver-listing-boundary)保留上市所在整月，排除完全上市前的月份，不切割上市首月或检查首月内部上市前成交。具体Silver字段、job/check与落盘设计及完成证据见共享LLD §10。后续历史刷新涉及的每个月都应传递，不能只处理当前月；首次生成不等于日常自动接线完成。

2026-10-05旧bootstrap两源402文件的搬运事实只作历史；2026-10-15未复权月线201文件已删除。旧排除20200229及双源执行卡不再是当前计划，完整记录见[历史结案](../../../reports/stock_period_raw_closeout_20261006.md)和Git。当前已完成Silver首次生成，后续按真实变更月消费，不只消费最新月。

## 6. 月线完整性审计及Silver边界（2026-10-17审计与生成均通过）

月线共用[总方案§7.3](dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md#silver-audit-plan)的五步流程及[共享LLD §9](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-completeness-audit)的全部判定、输出和通过标准，不另跑一套审计或增加月线专项步骤：

- 月线Silver从2014年1月起，2014年前缺口退出本阶段待办，Raw完整历史不截断。以后向前补历史只扩月份范围，沿同一完整周期规则。
- 上市日期确定首个保留月份，上市所在整月源K线保留，完全上市前月份排除；不拆首月、不追查首月内部上市前成交。月底上市也不能因此丢掉该月。北交所新三板源历史保留在Raw，不能把Raw和Silver的时间范围混为一谈。
- 应有月份按该股正式上市后、2014年起至本次截止日的有效开市日判定；有一个非全日停牌日即要求有K线，整段全日停牌可正常缺席。使用已含confirmed补充的最终stock_suspend_daily，不重做停牌合成，不因月内一条停牌记录就豁免整月。
- 按最新end_date整行择取，具体见本文§2；自然月末可以为周末，当前2026-10标签为2026-10-31但只核查截止2026-10-16的有效日期，不能误判未来成交或整月完成。
- 与周线共用一次读取的参考事实和本轮集合结果，输出月线汇总、缺失股票及范围CSV、最新版本冲突CSV和规则排除汇总；已确认Raw验收及源证据复用，不重新请求源、逐股逐日扫湖或聚合整月日线。
- 休市窗口按静态输入处理，报告整理及之后生成Silver不再重复完整审计、逐文件hash或库存核验。审计有真实问题先列明并讨论，只补验受影响范围；通过后生成时仅做必要的文件写入及读回验收。不得擅自新增步骤、配置、性能实验或更紧预算。

本节审计已于2026-10-17完成，实际证据见[审计报告](../../../reports/dg_stock_period_silver_readiness_20261017_135833/report.md)及共享LLD §9.6；月线154个范围内Raw文件/606,752行，排除完全上市前7,570行和旧计算版本3,574行，得到595,608条有效股票月，无缺口或版本冲突。完整Raw继续保留，不修改旧报告；之后已按管理员确认完成生成、加载及登记，实际结果见共享LLD §10.10；未再次审计或操作sensor。

## 7. 月线Silver生成设计（2026-10-17已实施并验收）

本节实施已获确认；已补充获准的catalog/name_mapping.py两项中文名称登记，其他范围保持共享LLD §10不变。正式完成数字以本次生成与验收结果为准。

本节只补月线差异，完整实现白名单、配置来源、原子性/取消恢复、检查/事件及验收唯一见[共享LLD §10](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-silver-generation)，不另立月线执行框架或增加审计步骤。

| 项目 | 设计 |
| --- | --- |
| 来源 | §6已审计的154个Raw月文件，2014-01—2026-10，沿本次交易日截止2026-10-16 |
| 输出资产/job | silver_stock_monthly / silver_stock_monthly_update_job，只选择Silver及其三项检查，不触发Raw请求 |
| 正式文件 | /Volumes/datasource/data_lake/silver/quote/stock_monthly/month=YYYY-MM/part-000.parquet；实际154文件/595,608行，已生成并验收 |
| 分区 | 复用cn_a_stock_months；catalog登记month_partition_silver_stock_monthly；不增加行情period列 |
| 字段 | 原21列顺序、列名、类型、值、单位和NULL全同Raw；trade_date/end_date仍VARCHAR，不转DATE，change不改名，三套价格不变 |
| 写入unit | 一个已列明Raw月文件选行→一个候选→一次共用读回校验→同设备原子提升→checkpoint；不每股或每项检查重读整月/全历史 |

月内多个源日期按最新end_date整行择取；20200229/end_date=20261015这一整行优先于20200228/end_date=20250910，不改写源日期或拼字段。月末非交易日及未结束10月均合法；上市所在整月保留，不切割上市日之前部分。已通过的停牌/生命周期完备性不在生成时再算一遍，Raw完整历史不截断。

三项blocking检查名为silver_stock_monthly_file_contract_check、silver_stock_monthly_key_partition_check、silver_stock_monthly_source_projection_check，共用一次实际验证。首次月线预计154条物化、462条检查；只登记已完成/校验文件，事件失败只补事件，不重做月线COPY。阶段事实与源版本记录放运行metadata/checkpoint，不写进业务列。

复用同一个stock_period_silver_cli的build/resume/events及本次run_id，不新增月线bootstrap/freeze/删除入口。后续日常/因子更新应将Raw实际变更的全部月文件交给同一生成器，不能只处理当前月；自动接线不在首次生成执行清单内，本轮不新建或启停sensor、不改Raw CLI/job/水位。月线隔离测试复用共享正反样本与真实Raw schema，不重下源或聚合日线；最终正式文件、检查与登记均须实际通过后才标完成。


本次月线正式文件及154条物化/462项blocking检查全部通过，21列及源整行守恒；两频正式文件阶段共31.889秒，月线不单独重复计时或再审计。真实补报run=891c70f1-146f-4e2c-aaa2-cdc2ca4181bb（SUCCESS），全部结果和未通过的无关扩展回归说明见共享LLD §10.10及[Silver生成验收报告](../../../reports/dg_stock_period_silver_generation_20261017/report.md)。自动日常接线、Prod与R3仍未推进。

## 8. DG剩余1—3项的月线差异（开发与隔离验收已确认）

本节对应[总方案§9](dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md#dg-period-daily-closeout)与[共享LLD §11](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-silver-daily-maintenance)，复用其全部逐步目标、文件白名单、配置、读写边界、恢复、性能及正反验收，不另建月线框架或额外审计步骤。2026-10-17管理员已确认提交文档后按本节开发/隔离验收；当前正式月线首次生成已验收，自动日常未完成，正式资源操作仍另行确认。

| 步骤 | 月线具体落点及完成标准 |
| --- | --- |
| 1 日常update | 保留silver_stock_monthly / silver_stock_monthly_update_job / cn_a_stock_months及原三项check；配置增加互斥update意图，消费Raw实际变化month清单。2014-01起、上市所在整月、21列/日期/NULL原样、最大end_date选完整行，均不变；已有月份凭匹配当前文件的真实事件，或明确原任务的完整校验/提交记录识别前像，新月份合法创建；文件归属不等于DG已完成 |
| 2 自动传递 | 新silver_stock_monthly_update_job_sensor默认STOPPED，definition分类为quote_data / silver / asset_update并复用build_sensor_tags；消费raw_tushare_stk_period_bar_adj_month上的批次通知，不依赖“此次运行的是月线Raw job”。周线Raw任务引起的月线历史变更也必须通知；一次月线job批量处理全部相关月份，不按股或月份启动大量run |
| 3 提交结案 | 随共享LLD §11.8白名单提交本任务代码/测试、三份设计文档、两份治理文档本域同步内容及必要结果，不另跑月线全量验收；区分月线首次完成、日常程序隔离通过、正式接线和首个真实交付，其他任务改动保留 |

月线与周线共用[共享LLD §11.6分类表](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-silver-sensor-classification)及§11.8开工对照，不另造月线标签、helper或治理流程。同步运行合同治理、资产与任务拓扑、既有静态定义名单及本域精确分类/STOPPED正反断言；不放宽其他sensor门禁。本轮仅完成五份文档补齐，两个sensor尚未开发、加载或启用；完成后停止，等待管理员再次确认。

**月线必验：** 自然月末可为周末，月中刷新同一个月文件，不能提前关闭该月；月末失败次月补原月且不逐日重放。20200228/29继续都在Raw，Silver按最新end_date选整行，不因交易日历把29日改回28日。历史回包移除旧键、只有旧键的月份、因子变更多个历史月份与本月重合时，每月仅组装/校验/提交一次；未选月份及周线不写。上市首月整根保留，不重做已通过的停牌/日历完整性审计。

**失败与续跑：** 统一执行共享LLD §11.4的逐文件恢复流程，不另造月线承接规则。已完成同版月文件直接复用；未登记时只补缺失事件，不以整批complete.json存在作为补记前提；未完成月份才生成。rename后记录失败先确认候选是否已成为目标，再补记提交。Raw失败/未知版本不清空旧月线，未知目标、候选改变、真实失败或错误绑定仍拒绝。

例如三个目标月文件A/B已提交、C尚未完成：输入未变沿原execution_id恢复，A/B不重算、不重写；仅C的Raw确已合法更新时，新执行显式承接原三个目标月份，复用A/B的真实校验与文件，C用最新交付重建。原ID/hash和记录不改，不能因新通知只含C就遗漏A/B登记。承接引用及逐月来源保存在既有执行/checkpoint位置，未完成新执行仍可继续恢复；events始终只补事件，不生成新文件或偷偷换输入。

月线job anchor仍为实际变化清单中的最大月份，其他历史月份在同一真实run精确登记；不能预报anchor成功或只给当前月写绿。仅当原范围每个月份均有当前适用文件和实际物化/检查，或被明确后继结果逐月覆盖，才能关闭原批次；不以最新月份完成代替整批完成。未选月份及周线不因恢复被改动。

**改动与成本：** 仅共享LLD §11.8内月线asset/job、共用Silver合同/执行器/IO/check、Raw事件生产者及新月线sensor，测试复用同一个两频小场景。当前154月只是容量样本依据，不作为永久上限；每实际变化月一次Raw读取/COPY/候选验证，三check复用，事件最多4条/月。0 Tushare/Prod请求，无新增月线SQL公式、配置、staging框架或完整bootstrap。新增路径实际性能待隔离场景测量，原首次实测不冒充新功能验收。

**正式交接另行确认：** 沿共享LLD §11.9，保留Raw sensor状态/水位及19:30窗口，旧月线数据和事件不重写。没有新的真实Raw交付就保留首样本待办；本节不授权加载、启用新sensor、事件或Lake写入。Prod及R3不进入本轮步骤。

**当前状态：** 逐文件恢复方案已先提交dbec0343，共用恢复代码修复及两频隔离验证完成，详见共享LLD §11.11的最终单次87项直接回归及证据边界。月线小场景实测复用两个已完成文件、只生成一个输入变化的文件，并以独立字面价格核对；未做月线全量审计或bootstrap。Raw变化均在临时测试中主动构造，正式写入/源请求为0；第2项通知/sensor仍未开发，月线自动日常维护尚未完成。修复代码和结果回写已提交d865e640，未推送；本轮只补分类及治理文档，等待管理员确认下一步，其他任务改动保留。
