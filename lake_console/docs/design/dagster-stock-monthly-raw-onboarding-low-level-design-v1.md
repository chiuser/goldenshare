# DG 复权月线Raw更新、完整性审计与Silver生成 LLD v1

**2026-11-12 六阶段开发、隔离验收及正式切换完成，11月11日股票复权月线与周线欠账已补齐。** 第6阶段独立审计见[周月线LLD第13.19节](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#stock-period-stage-six-results)，正式运行及最后验收见[第13.21节](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#stock-period-formal-cutover-results)。第5阶段源码提交为`202739e60`，第6阶段设计提交为`982619968`。月线新流程见[第11节](#monthly-daily-point-readiness)，实施细则见[周月线LLD第13.18节](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#stock-period-stage-six-execution)。第1至10节记录切换前实现和历史结果。切换后，当月预检、正式日更和指定闭合月补齐使用第11节口径，旧建库交接和续跑命令只用于追溯。

**2026-10-31跨日日期修正已完成开发和隔离验收：** 月线与周线共用的逐文件来源日期修正见§9.8及共享LLD§12.22，相关463项不重复用例通过（新增28项）。本轮修改随本次提交保存，未正式补数；28日各项结果保留为历史，不表示29/30日已经补齐。

**本轮补修完成（2026-10-28，开发、隔离验收及独立审计完成，随本次提交保存）：** 已修正来源未变时原ID被旧FAILURE/CANCELED挡住、未完成误入recover的两项遗漏。最终305项普通case及另518个subtest通过，两名非作者分别核对代码/消费者与逐case证据，无阻断；完整对账见共享LLD§12.18.6。来源变化继续原恢复流程及其既有成本，不能将本轮等待分支的0预算扩展到全部tick。27日已完成补数保持原状，未部署、未操作正式资源。

**上轮开发及隔离结果（历史）：** 周/月Silver sensor区分恢复方案建立与文件处理完成的修复已有281项普通case通过，另有518个subtest，详见共享LLD§12.17.6。通过记录保留，但撤回“全部硬口径已覆盖、该问题已全部收尾”的结论；这些测试没有证明本轮遗漏组合。该轮未部署、未触发正式job、未重载正式code location或执行正式definitions验证，未操作正式instance、Lake、sensor或cursor。

**正式恢复完成（2026-10-28 11:50）：** 本次原27日股票复权周/月Raw及Silver四项均完成；23日周欠账已补，30日当前周及10月已更新到27日。8GiB续跑成功、原83页完整复用；全部实际通知/检查已确认，pending=0，四sensor保持RUNNING。本轮修改及证据随本次提交保存，未推送。完整结果见[正式恢复记录](../../reports/dg_stock_period_delivery_recovery_20261028/formal_execution_20261028.md)及共享LLD§12.12.6。

**005f21f53开发阶段结果（历史）：** 审计第1—5项已按§9.4及共享LLD§12.16完成开发、独立复核与隔离验收。最终固定版本530项中528通过、0失败，2项既有隔离PG实验未启用；136.39秒。三文档及旧相反条款已同步；结果、指纹和失败记录见[五项修复报告](../../reports/dg_stock_period_delivery_recovery_20261028/followup_1_5.md)与共享LLD§12.16.9。本次提交包含五项修复、测试和文档证据，提交号以Git记录为准；未推送、未部署、未修正式状态或补数，测试临时业务目录已清理。

**此前独立审计（88de377ca，历史）：** 该提交发现2项P1、3项P2，原411项不能覆盖这些组合；问题、隔离复现及测试漏项继续保留在[原审计报告](../../reports/dg_stock_period_delivery_recovery_20261028/post_commit_audit.md)。这段保留当时发现，不代表五项仍未修复，也不以新通过结果抹掉旧失败。

**五项开发阶段授权（历史）：** 审计第1—5项统一采用[共享LLD§12.16](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-delivery-recovery-followup-345)，月线按§9.4对应执行。先补齐/审计文档，再开发、隔离验收并逐项对账；原“只解释1/2”为上一轮历史。本轮不执行正式部署、状态修复、补数或sensor操作。

**前一轮开发历史（2026-10-28，88de377ca）：** 月线与周线共同按已提交befd282e0方案开发、隔离测试和实现对账，结果见[共享LLD第12.15节](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-delivery-recovery-implementation)；月线差异仍在第9节。411个去重用例保留为该轮历史结果，不代替上方五项新增验收；没有另跑月线全量审计、正式恢复或补数。下述2026-10-18总结及各阶段“未启用/待周一”等描述保留为历史，不得按旧bootstrap删除步骤重新建库。

更新：2026-10-18。**月线Raw重建、一次完整性审计及Silver首次生成/正式验收均已完成。** Raw431文件/868,690行、baseline=ready，截止2026-10-16；审计595,608个应有股票月全部覆盖，缺失与最新版本冲突0。Silver实际154文件/595,608行，字段/值同Raw，154物化/462项blocking检查通过。首次结果见共享LLD §10.10。**剩余1—3项开发/隔离验收已完成并提交6e6017712；月线正式接线与自然无输入tick已通过，见共享LLD §11.12—11.13。首个真实交付待周一原19:30窗口。** Prod后置。25股修复及R5登记已完成，专项工具已清退，结果见其原方案§9和LLD§23.7；下文有日期的暂停要求保留为当时执行边界。

目标/阶段见[总方案](dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md)，完整字段、北交所请求、捕获/候选/恢复、性能与正反验收唯一引用[共享LLD](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md)。本文只记录月线差异，旧逐月修补及Prod搬运步骤退出DG方案。

## 1. 数据卡、来源与字段

本节的范围请求用于描述现行实现及旧批次。切换后的当月预检和正式日更见[第11节](#monthly-daily-point-readiness)。

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

## 4. 日常覆盖与历史刷新（切换前实现）

切换后的月线日更与历史回刷见[第11节](#monthly-daily-point-readiness)。

以下描述现行合并任务。切换后，因子变化股票回刷按[共享LLD第13节](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#stock-period-daily-then-history-lld)独立触发。

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

只补真实HTTP执行器及少量事件的缺失成本，已有文件/恢复性能证据适用时复用；测量不自动带来新配置、并发或更紧上限。最终按共享LLD固定版本回归和逐项对账，Raw程序验收不等于正式bootstrap、sensor交接或Silver完成。本轮仅用临时根、localhost和独立instance；组合场景两频真实job/check及同日待办补记均通过，后者不请求源、不跑SQL或改写文件。管理员当时确认最小修正：仅查询已完成检查（含失败）；当时组合和5项状态正反测试通过。2026-10-27已证实其按检查表ID排序仍不足，最新规则及本次未关闭待办见共享LLD §12，不沿用该历史通过结论。旧失败现场保留，完整证据及性能见共享LLD §5.8、§6.1；正式操作继续另行review。

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


当时月线首次生成的正式文件及154条物化/462项blocking检查全部通过，21列及源整行守恒；两频正式文件阶段共31.889秒，月线不单独重复计时或再审计。真实补报run=891c70f1-146f-4e2c-aaa2-cdc2ca4181bb（SUCCESS），全部结果和未通过的无关扩展回归说明见共享LLD §10.10及[Silver生成验收报告](../../../reports/dg_stock_period_silver_generation_20261017/report.md)。该首次生成阶段没有接通自动日常链；后续接线见§8末尾，Prod与R3不属于本轮。

## 8. DG剩余1—3项的月线差异（开发与隔离验收已确认）

本节对应[总方案§9](dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md#dg-period-daily-closeout)与[共享LLD §11](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-silver-daily-maintenance)，复用其全部逐步目标、文件白名单、配置、读写边界、恢复、性能及正反验收，不另建月线框架或额外审计步骤。2026-10-17管理员已确认提交文档后按本节开发/隔离验收；正式月线首次生成、自动日常程序及隔离验收已完成，见共享LLD§11.12；其后同日正式加载、启用及无输入tick通过，见§11.13和本节末尾。没有新交付的无输入tick不能证明首个真实样本已完成。

| 步骤 | 月线具体落点及完成标准 |
| --- | --- |
| 1 日常update | 保留silver_stock_monthly / silver_stock_monthly_update_job / cn_a_stock_months及原三项check；配置增加互斥update意图，消费Raw实际变化month清单。2014-01起、上市所在整月、21列/日期/NULL原样、最大end_date选完整行，均不变；已有月份凭匹配当前文件的真实事件，或明确原任务的完整校验/提交记录识别前像，新月份合法创建；文件归属不等于DG已完成 |
| 2 自动传递 | 新silver_stock_monthly_update_job_sensor默认STOPPED，definition分类为quote_data / silver / asset_update并复用build_sensor_tags；消费raw_tushare_stk_period_bar_adj_month上的批次通知，不依赖“此次运行的是月线Raw job”。周线Raw任务引起的月线历史变更也必须通知；一次月线job批量处理全部相关月份，不按股或月份启动大量run |
| 3 提交结案 | 随共享LLD §11.8白名单提交本任务代码/测试、三份设计文档、两份治理文档本域同步内容及必要结果，不另跑月线全量验收；区分月线首次完成、日常程序隔离通过、正式接线和首个真实交付，其他任务改动保留 |

月线与周线共用[共享LLD §11.6分类表](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-silver-sensor-classification)及§11.8开工对照，不另造月线标签、helper或治理流程。同步运行合同治理、资产与任务拓扑、既有静态定义名单及本域精确分类/STOPPED正反断言；不放宽其他sensor门禁。两个sensor程序及隔离验收完成时均默认STOPPED，当时没有正式加载或启用；其后正式接线状态见本节末尾。

后续已确认将共享handoff内存测试纳入事件回调迁移，内存/取消/续跑断言保持；月线不另建一套测试。当前源码消费者、必要回归及不触碰范围已一次分类，见[共享LLD §11.8消费者核对](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-silver-consumer-preflight)。管理员随后要求清退consumer逐文件源码登记，改为治理测试只读项目源码目录，实施和定向验证统一见共享LLD §11.8；不再等待追加两条源码权限确认，两个自动sensor当时已完成程序和隔离验收，后续正式加载/启用结果见本节末尾。

**月线必验：** 自然月末可为周末，月中刷新同一个月文件，不能提前关闭该月；月末失败次月补原月且不逐日重放。20200228/29继续都在Raw，Silver按最新end_date选整行，不因交易日历把29日改回28日。历史回包移除旧键、只有旧键的月份、因子变更多个历史月份与本月重合时，每月仅组装/校验/提交一次；未选月份及周线不写。上市首月整根保留，不重做已通过的停牌/日历完整性审计。

**失败与续跑：** 统一执行共享LLD §11.4的逐文件恢复流程，不另造月线承接规则。已完成同版月文件直接复用；未登记时只补缺失事件，不以整批complete.json存在作为补记前提；未完成月份才生成。rename后记录失败先确认候选是否已成为目标，再补记提交。Raw失败/未知版本不清空旧月线，未知目标、候选改变、真实失败或错误绑定仍拒绝。

例如三个目标月文件A/B已提交、C尚未完成：输入未变沿原execution_id恢复，A/B不重算、不重写；仅C的Raw确已合法更新时，新执行显式承接原三个目标月份，复用A/B的真实校验与文件，C用最新交付重建。原ID/hash和记录不改，不能因新通知只含C就遗漏A/B登记。承接引用及逐月来源保存在既有执行/checkpoint位置，未完成新执行仍可继续恢复；events始终只补事件，不生成新文件或偷偷换输入。

月线job anchor仍为实际变化清单中的最大月份，其他历史月份在同一真实run精确登记；不能预报anchor成功或只给当前月写绿。仅当原范围每个月份均有当前适用文件和实际物化/检查，或被明确后继结果逐月覆盖，才能关闭原批次；不以最新月份完成代替整批完成。未选月份及周线不因恢复被改动。

**改动与成本：** 仅共享LLD §11.8内月线asset/job、共用Silver合同/执行器/IO/check、Raw事件生产者及新月线sensor，测试复用同一个两频小场景。当前154月只是容量样本依据，不作为永久上限；每实际变化月一次Raw读取/COPY/候选验证，三check复用，事件最多4条/月。0 Tushare/Prod请求，无新增月线SQL公式、配置、staging框架或完整bootstrap。新增路径实际性能待隔离场景测量，原首次实测不冒充新功能验收。

**正式交接另行确认：** 沿共享LLD §11.9，保留Raw sensor状态/水位及19:30窗口，旧月线数据和事件不重写。没有新的真实Raw交付就保留首样本待办；本节不授权加载、启用新sensor、事件或Lake写入。Prod及R3不进入本轮步骤。

**2026-10-17恢复代码阶段历史：** 逐文件恢复方案先提交dbec0343，共用恢复代码修复及两频隔离验证完成，详见共享LLD §11.11的最终单次87项直接回归及证据边界。月线小场景实测复用两个已完成文件、只生成一个输入变化的文件，并以独立字面价格核对；未做月线全量审计或bootstrap。Raw变化均在临时测试中主动构造，该阶段正式写入/源请求为0。修复代码和结果回写已提交d865e640；当时尚待开发的通知/sensor及正式接线随后已完成，见以下§11.12—11.13对应结果，不再作为当前待开发事项。

本轮月线与周线共用一次隔离集成：Raw同一历史交付触及3周+3月，各1条频率通知、各1个Silver job、每期一次COPY；最大end_date整行及21列金样本保持。月线程序验收随[共享LLD §11.12](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md)和[本轮报告](../../../reports/dg_stock_period_silver_auto_acceptance_20261017/report.md)交付，不重新做月线全量审计。

2026-10-17管理员确认先完成周末可验证的正式接线，精确步骤、预算和失败恢复沿共享LLD §11.13：只加载定义，按无新增Raw交付/无历史通知的实际基线初始化并启用两Silver sensor，读取自然无输入skip tick；不请求源、不生成数据、不重写历史事件、不改变Raw状态/水位。月线不单独再验一遍。正式首个日常下载及交付留待周一。

同日正式接线通过：月线新sensor已RUNNING，基线after=0；自然tick2578126为SKIPPED/silver_no_completion，无任务请求/运行和错误。周线同轮通过，原sensor状态、Raw水位/日常记录及Silver完成记录未变，未写行情或补历史事件。证据及共同验收见共享LLD §11.13与[接线记录](../../../reports/dg_stock_period_silver_auto_acceptance_20261017/formal_handover.json)；首个真实交付待周一既有19:30窗口。


<a id="monthly-delivery-recovery"></a>

## 9. 2026-10-27月线交付确认与恢复修复

### 9.1 对应关系与当前状态

本节对应[总方案§10](dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md#period-delivery-recovery-plan)，全部算法、接口、失败/续跑及预算唯一遵守[共享LLD §12](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-delivery-recovery-lld)，不另写月线版本。2026-10-27仅完善/审计文档；2026-10-28获准并完成本轮开发、隔离测试及对账，统一见共享LLD§12.15；正式部署/收尾/补数均未执行。

20日旧pending是周线1文件，但两Raw job共用daily.json及writer，因此月线job也会先遇到它并失败。21日月线run 54795ebd是正常日常任务，恢复了含两频的18股工作；不是专门补报job。该后继共395个月文件，整批事件于22日收尾；不能因此推断22日之后的当前月已经更新。完整时间线和ID见共享LLD §12.2。

| 总方案要求 | 月线必须落实的内容 | 共享LLD |
| --- | --- | --- |
| 最新检查选择/拒绝 | Raw月线、Silver月线及首次CLI补报按实际evaluation事件ID；保留晚失败/错绑；不能追加通过覆盖 | §12.3—12.4 |
| 旧交付与当前目标分开 | 原月线已完成记录只追溯；新写入仍核已登记前像，未知文件拒绝；历史元数据不作为当前月anchor | §12.5—12.6 |
| 共享待办顺序 | 周线旧工作也先确认；月线新意图不能跳过它；仅原意图可先返回当前文件再跑native checks | §12.7 |
| 原job与同日续跑 | raw_stk_period_bar_adj_month_update_job保留，原失败run用FROM_FAILURE保持日期/分区；不改sensor key/cursor | §12.8 |
| 正式旧20收尾 | 沿原events CLI处理旧周线1文件，不读/写395个月文件；旧月水位、月刷新日和因子水位保持 | §12.10—12.11 |
| 实际补数及Silver | 旧pending关完后，原月线Raw补2026-10实际欠账；原通知→silver_stock_monthly_update_job_sensor→原Silver job，全部变化月份都消费 | §12.12 |
| 验收 | 两频参数化同场景，真实排序/失败拒绝/原生续跑/历史不回写/查询成本均覆盖 | §12.13—12.14 |

### 9.2 月线不变项与执行边界

- 原asset、job、三项blocking check、cn_a_stock_months、自然月末标签、21列和路径均不变；源month请求仍按月首至自然月末，不改Tushare参数/分页/价格。
- 2026-10-31为自然月末坐标，当前意图27日并不表示整月已结束；月中刷新只能推进相应当天刷新，不能提前推进整月最终完成。20200228/29及合法NULL仍保留原合同，Silver仍按最新end_date取完整行。
- 日常/历史入口均先核共享旧待办，不因运行的是月线job就忽略周线待办；周线因子工作触及的历史月文件仍经原通知进入月线Silver。
- 原事件回执、当前目标的确切版本和候选校验继续分开；缺事件不重新下载/COPY，真实失败只通过获准原生检查重执行处理，不能首次CLI偷偷补绿。
- 本次原旧20恢复正常预算按共享LLD§12.11实测校准为两频共同的JSON读≤16MiB/写≤2MiB，含一次续跑与收尾合计读≤24MiB/写≤4MiB；不是每频另给一份额度。行情内容读取/写入、源请求和DuckDB/COPY为0；原events CLI报告run是控制面写入，新增业务物化/check/通知为0。
- 真正后续月线补数的源请求/历史行情读写不包含在上述0预算内，必须先按实际清单核定并获准。不能为月线再做一套全量审计、bootstrap、初始化cursor或清根。
- 本轮不改两Raw及两Silver sensor开关。未来正式维护只恢复本轮确实暂停且原为RUNNING者，原STOPPED保持，不操作其他数据集。
- 冲突/缺证据/错绑/未知替换时保留已提交文件和回执；按原ID继续缺项，不改旧hash/identity，不用旧状态覆盖新进度，也不创建行情备份或快照。

### 9.3 开发与审计验收

开发白名单、调用方、配置与持久化来源沿共享LLD §12.9及§12.16.1；月线不另加入口、参数或状态。现有Silver旧批历史确认/合法新Raw承接继续复用；实际检查选择之外，还须按§12.16补齐元数据准入、允许频率回执和Raw读取前范围核验，不能只改最初检查选择入口就视为完成。薄asset/job/sensor没有必要不改，仍须在原生job及两频小样本中验证真实顺序。

至少覆盖共享A1—A8检查顺序/拒绝，B1—B6旧批/后继/中断收尾，C1—C6共享待办/原生检查/同日key及日期，D1—D4成本/不回流/清理。月线追加或复用的独立字面预期须包含月底周末、月末跨月欠账、月中不关整月，以及未选月份/股票保持。不能只证明周线修复后由同helper“推断月线通过”。

本轮独立审计必须核本节所有数字/步骤与总方案§10及共享LLD §12对应，无重复预算或第二套历史恢复算法；结果统一记录共享LLD §12.14。程序、隔离与正式补数状态继续分别列待执行。

<a id="monthly-delivery-recovery-followup"></a>

### 9.4 独立审计第1—5项的月线对应

具体算法及测试唯一采用共享LLD§12.16，不另写月线实现：

- 第1项月候选已替换但CP缺失时，沿原执行/候选身份和摘要恢复CP，不能因旧baseline不同被挡在原publish恢复前；既有CP及已闭合旧批不因此重读月文件。
- 第2项主动历史无论由周线或月线job触发，先登记同一共享待办，冻结原scope/开始时间；月线日更与handoff不能越过未完成的history，也不能把其文件完成当daily因子消费。月线原ID重执行不读今天scope改身份，整批而非局部确认后才能删历史待办。
- 第3项同样覆盖silver_stock_monthly、其原生checks、首次CLI和update补报。月中asof可以小于自然月末坐标；各unit使用自己的日期，历史月份配较晚asof合法，不能用整批最大日期改写原月份事实。缺失/非法/错unit日期或同版行数冲突在补事件前拒绝，正常继承及原bootstrap合同不得误拦。
- 第4项周线限定动作不查/补月线证明、CP或目标stat，月线未确认时整批phase/pending保持；未登记的显式未闭合主动history须先原resume/全频events登记，受限动作本次不写pending或CP。以后全频确认必须独立核月线真实证据，不能因为周线局部CP存在就关闭整批。默认全频events仍可按完整原清单处理。
- 第5项月线历史范围来自可信baseline.month范围及文件登记，不靠遍历所有月文件定位。索引不可信且需要历史替换时读取前停止；仅明确月份更新不扩大到历史，换码旧区间、旧-only月份和新上市无旧史按共享规则处理，未知选中目标仍拒绝。

共享预算不按月线再复制额度；本次不读395个后继月文件，不新增运营配置/业务字段/入口，不改自然月末标签、21列或三套价格。kind/started_at等仅在原pending JSON表达真实历史工作，不是新业务合同。先文档审计再开发/隔离，实际结果依事实回写；正式操作不在本轮。

2026-10-28后续正式推进已获管理员指示，按共享LLD§12.11—12.12及§12.16.10继续；前句“正式操作不在本轮”保留为五项开发阶段的边界。执行前发现的receipt路径lstat遗漏须先修正：历史清单只做纯路径比较，周线限定确认不接触未选month当前路径；实际选中月文件的读写仍完整检查symlink/当前版本。月线不另写一套路径算法，不扩大正式历史读取范围。

2026-10-28预核及下一步范围同步：81股两频历史由先执行的27日周Raw原任务规划，确认退市1股；27日月Raw原任务随后通常只刷新2026-10，不重复81股历史。月Silver消费全部实际变化月周期（既有154个2014起周期），同月不同Raw版按真实版本重建/复用，不按月份强行去重。原月parentRunId为8c9e09c4-9a82-4042-b696-0ffc3a17999d，FROM_FAILURE继承27日意图及2026-10分区。全部两频共享的具体范围/预算唯一见共享LLD§12.12.2：正常预计读16GiB/写12GiB/空间32GiB；含一次必要续跑及最后验收合计读32GiB/写24GiB/空间48GiB，不按月再加一份。最小预核已完成，真正历史范围仍待单独批准，月Raw/Silver未执行。

2026-10-28管理员已对共享LLD§12.12.2具体历史范围及预算明确回复“批准”，下一步按原27日周Raw、月Raw及原通知Silver顺序正式实施；不重复预核、不改代码/日期/配置/名单。实际执行及结果继续写原报告。

本次首次正式周恢复已在候选COPY中因原4GiB内存检查失败并按约定停止，未发布正式文件；月Raw/Silver未继续，具体现场/源复用及后续准入见共享LLD§12.12.3，不把历史预算批准当自动重跑或改内存授权。

管理员随后已明确批准“扩到8gb。完成补数”。本次运行RSS8GiB的配置审计、原job传参/精确daily pending准入、隔离测试和正式续跑唯一见共享LLD§12.12.4；不改冻结4GiB policy/成功源身份，保持原FROM_FAILURE配置，仅原生extraTags增加本次资源值。周原失败子run继续，之后原月、原通知Silver；无tag及其他数据集默认不变，原已批历史范围/预算不扩大。

月Silver末尾恢复窗口按共享LLD§12.12.5处理：利用已冻结子82c6253a及原月Silver job显式parent，只补153个复用CP及重建2026-10；不改代码/游标或另写补数入口。属既定已批同一通知/预算范围，成功后原sensor继续消费末条月通知。

2026-10-28 11:50本轮数据恢复及全部通知确认完成，最终口径唯一见共享LLD§12.12.6：Raw不同2170/提交2171、Silver不同812/3115094行；pending0、两频刷新/因子27、四sensor RUNNING。月Silver既有恢复窗口通过原job显式parent补完，当时将sensor确认时机/提示列为TODO；后续已获准按共享LLD§12.17开发修复，不新增自动补数要求。本轮修改及证据随本次提交保存，未推送。


### 9.5 月Silver恢复任务的完成判断与指引

本轮已批准先完善原方案及LLD，再修共享代码并做两频隔离测试。原进度合同见[共享LLD§12.17](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-silver-recovery-progress-lld)，本轮遗漏及唯一实现细节见[共享LLD§12.18](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-silver-original-run-recovery-lld)，对应总方案§10.9；月线不另写算法、job或配置。

上轮原154月任务成功后，Raw合法刷新2026-10，冻结child153月复用/10月重建。execution.json只是方案；子未执行或部分完成时稳定提示当前ID、显式parent、2026-10 partition及原silver_stock_monthly_update_job配置，不能直读未生成2014-01 CP或推进通知。complete缺失但全CP committed仍由原job续跑补汇总；有complete却缺CP、非committed、汇总/身份/版本矛盾属于真实异常。全部文件与原检查通过后才确认交付并关闭祖先；父SUCCESS/FAILURE不能代替child事实。

本轮补齐原ID同一条路径：即使旧run_key最新run为FAILURE/CANCELED，已有execution也先核Raw版本。未变时绝不调用recover_update_execution、owned_update_records或recover_committed，直接只读progress；未完成保留silver_run_requires_review、旧run ID及resume ID前缀，并附当前配置，不能补reuse CP、恢复rename或读footer。文件完成后按原检查/confirm/coverage/ack，不因旧失败状态提前return；人工用原月job、同execution配置、不带旧key或用不同key成功后必须能确认。真实检查缺失/FAILED/错绑仍拒绝，回执失败下一tick只收尾。Raw变化继续原recover及父链/范围，首次后继提示保留旧失败前缀；无execution但有run仍复核，不自动请求。

tests/test_stock_period_silver_original_recovery.py须显式覆盖月线×FAILURE/CANCELED、缺reuse CP、validated候选尚在/已rename等中断、人工不同key成功、坏summary及原检查阻断、两tick/回执重试读取次数。沿现有真实小producer约3月及真实SQLite绑定，独立核关键合同，统一DuckDB入口guard防止误用正式资源。原test_stock_period_silver_sensor_recovery.py的62项保持，预计不需修改既有断言；确需修改先在原方案和共享LLD落具体范围及独立依据。原三文档外仅增加共享小型证据lake_console/reports/dg_stock_period_delivery_recovery_20261028/original_silver_recovery_results.json，按共享LLD保留冻结指纹、实际运行参数/版本、逐case结果与修复前失败片段、成本断言及精确清理统计；不复制行情、凭据或完整临时SQLite/Parquet。共用progress/message/缓存，保留自然月坐标、月中asof、21列、原三项检查、cursor、identity及run_key，不改job、算法、CLI或新增tag/config。


预算唯一用共享LLD§12.18.5一份，不给月线重复额度：来源未变未完成0集合SQL、0行情/footer读取、0CP/summary/业务事件补写、每CP/complete同tick实读至多1次，完整最多原2条集合SQL。来源变化原recover每代resolve为2条集合SQL，已有末代recover还可能2条，并可能正常化父CP及读已rename文件footer；这项既有成本保留，不冒称零读取。新增0源请求/业务计算/COPY，不做全局审计；复用上轮未变progress容量证据，不重复154月metadata场景。全轮隔离含故障续跑和最后验收临时空间估算≤1GiB、实际汇总，不新增运行限制。27日补数保持原状，本轮不部署/重载正式code location或执行正式definitions验证，不操作正式Lake、staging、instance、job、sensor或cursor。

上轮共同对账见共享LLD§12.17.6：281个普通case及518个subtest通过、初轮测试纠正、metadata容量与3个临时根清理均保留为历史，原全部覆盖与收尾结论已撤回。本轮先完成三文档审计，再修共享分支；月线×FAILURE/CANCELED及来源未变等待/人工原job完成、坏记录/检查阻断、回执重试均已隔离验证，两名非作者独立审计通过。实际结果唯一见共享LLD§12.18.6：最终305普通case及另518个subtest通过，首次新24中两类3例测试错误及独立纠正依据保留；约139KB逐case报告已保存，3个精确临时根已清理，清理前约29.08MiB不当作累计IO或峰值。当前开发、隔离验收及独立审计完成，修改随本次提交保存，提交号以Git记录为准，未推送；来源变化仍是原恢复路径及其既有成本，未触碰正式资源，不把历史人工恢复当成本次代码上线，不重跑已完成补数。


### 9.6 28日中断任务的Raw收尾及周/月Silver跟进

管理员已要求补完整28日原任务，跨到29日仍冻结原automatic_intent_date=2026-10-28。本轮不开发、不重下/重算已完成Raw，先沿原CANCELED月run104911a4做FROM_FAILURE和原三checks，再按原两频通知推进154月/658周Silver及回执收尾。精确范围、代码依据、原job参数、正常及中断余项预算和验收唯一见[共享LLD§12.20](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-28-resume-lld)，对应原总方案§10.11。管理员已明确批准本次具体历史范围，正式续跑按共享LLD§12.20推进；该新批准不以旧27日批准替代，不在本月文档重复维护另一份算法或预算。


本次28日恢复已于29日00:26完成，唯一实际结果见共享LLD§12.20.1及本轮执行报告：原月Raw收尾成功，154个月Silver/595228行/462原检查及月通知确认完成；当前10月Raw/Silver均5575行、来源版本一致。联动周历史658周期亦完成，不修改其独立日更水位。

### 9.7 29—30日恢复准入暂停：源日期晚于旧意图日期

31日按管理员批准顺序定点核验，确认29日原月Raw的920306.BJ空源待办尚未完成；当前该股两频源已返回截至30日的数据，而Silver仍使用冻结29日作为来源上限，现有流程无法直接承接。本次停在触发job前，未修改业务代码、pending、sensor或任何正式数据，不重跑28日补数。完整事实、代码冲突、建议及边界唯一见[共享LLD§12.21](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-29-30-preflight)及总方案§10.12；建议先完善两种日期的交接设计和隔离验证，再恢复原29日及30日更新，本节不另设月线修正算法或预算。

### 9.8 跨日来源日期修正的月线执行口径

管理员已批准先修正再审计条件，本轮开发唯一遵守[共享LLD§12.22](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#period-cross-day-source-asof-fix)及总方案§10.13。月Raw实际候选max(end_date)随每文件source_asof进入原回执；月Silver在原意图日期与该月实际源日中取较晚者，且源日不能晚于原文件完成日期。保留自然月坐标（本次20261031）、21列及原日期谓词；29日意图/30日源/31日完成应按30日选择、检查、物化及恢复，不借周线或整批最大日改写本月，也不把29日任务冒记为30日因子或日更完成。既有无该字段回执及bootstrap不重写、不重扫，原成功下载单元复用；本轮不正式补数。必须与周线一起覆盖真实小producer→两频Silver job/check及故障恢复，详细预算/失败规则与验收只维护在共享LLD，不另设月线实现。

本轮共享开发已完成，实际463项通过及独立源码对账唯一见共享LLD§12.22.6；月线正常/中断、跨日原请求、逐文件日期、较新Raw承接、无来源证明及非法/未来日期均已覆盖。没有重跑28日批次或触发正式补数，待确认正式加载及本次历史范围预算后，继续原29日月Raw及两频Silver，再30日日更。

## 10. 2026-11-06月线Raw恢复预核与待确认范围

目标是让`raw_tushare_stk_period_bar_adj_month`的`2026-11`分区覆盖11月6日。原任务`38119344-2a2c-440f-894d-67a57524a691`及最新失败子任务`b612e5bb-99f2-4654-af77-6326b1ab45bd`都在形成日更待办前报`period_adjacent_factor_missing`。两个任务使用`intent=daily`、`automatic_intent_date=2026-11-06`和分区`2026-11`。11月6日的Silver因子文件在20:19:50（北京时间）落盘，11月5日及6日因子现均存在。预核时`factor_through`及月线`last_refresh`均为11月5日，`completed_through.month=2026-10`，共享待办为空，本次业务执行ID`107edccda1807032d6d2d6ebb2ded4f384dbe9c72f55d3a7818524ad41cd1a3f`尚无manifest。

`stock_period_update._daily_work`先计算11月5日到6日相邻因子变化，并比较当前上市集合与已交付基线。一次计数和有界差集确认19只因子变化、1只新上市`920085.BJ`，合计20只，无移出。当前上市集合5,579只，基线5,578只。该分支会计划两频历史，`stock_period_history.run_period`在原月线任务内读取并合并两频选中分区。周、月Silver传感器均为RUNNING，会消费此次实际变化文件的原通知。

| 范围 | 预核依据和规模 |
| --- | --- |
| 源请求 | 原请求构造器按20只各取周、月完整源历史，再按`20261101`至`20261130`取当月全市场。共`20×2+1=41`个逻辑源单元。每页最多6,000行、每页最多3次尝试，实际页数由源返回决定。 |
| Raw现有目标 | 可信范围索引已定位1,737个周文件及412个月文件（含当月），共2,149份、374,550,315字节（约357.2 MiB）、4,504,820行。范围分别从1992-08-07周和1992-08月开始。两频登记上界共2,254份、375,005,366字节，源返回可能选中额外登记周期或新增周期，未知现有目标由原校验拒绝。 |
| Silver自动接续 | 现有目标按原2014年起算规则涉及659个周和155个月，共814个周期。各周期是否重建及最终个数以实际Raw交付和版本为准。 |
| 读写与恢复 | `stock_period_raw.assemble`将选中旧Raw的21列读入一次以保留同周期其他股票。候选按原规则校验，在`/Volumes/datasource/data_lake_staging`形成逐文件记录，向同设备正式Lake原子替换。续跑复用成功源页及完整候选，只重做未完成部分，验收复用交付和检查记录并定点核当月文件。 |

以上文件字节数来自现有登记版本，只计输入文件压缩大小。正式设备IO、最终候选大小及运行时间待实际任务记录。10月28日同量级的恢复在4 GiB下因COPY期间超限停止，单次使用8 GiB后成功，实测RSS采样最高约5.79 GiB。11月6日现有预核未测正式进程内存。拟仅为此次原生续跑使用已存在的`goldenshare/stock_period_rss_limit_gib=8`标签，沿[共享LLD§12.12.4](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md)的准入与续跑规则，保留默认及冻结策略。

批准历史读写范围及本次资源值后，先复核两频在途任务、共享待办、已绑定参考文件与范围证据，再沿共享LLD§12.8向本机正式Dagster（`/Users/congming/.goldenshare/dagster_home`）提交`launchRunReexecution`。`parentRunId=b612e5bb-99f2-4654-af77-6326b1ab45bd`，`strategy=FROM_FAILURE`，`useParentRunTags=true`，`extraTags`仅包含上述本次资源值。保持原分区和11月6日意图。原任务成功后核验当月`end_date`至少到11月6日、原三项检查和实际两频文件的交付。若输入范围变化、源截至日期未到或真实检查失败，保留现场并停止人工推进。本节记录的是只读预核，正式续跑仍待确认。

### 10.1 已批准的执行方式

2026-11-07管理员明确批准上述两频历史读写、原Silver自动接续和本次8 GiB运行值。提交前复核八份输入的大小和修改时间与预核一致，共享待办为空，写锁空闲，周/月Raw及Silver四个任务均无在途运行。原月任务配置、分区与最新失败子任务一致。工作目录为`/Users/congming/github/goldenshare/lake_console/orchestrator`，通过既有正式Dagster的GraphQL提交一次原生续跑，具体请求使用上节已审核的参数：

```bash
curl --max-time 25 --fail-with-body --silent --show-error \
  http://127.0.0.1:3000/graphql -H 'Content-Type: application/json' \
  --data-binary @/private/tmp/dg-raw-month-recovery-20261106.xL15cQ/raw-month-resume-request.json \
  -o /private/tmp/dg-raw-month-recovery-20261106.xL15cQ/raw-month-resume-response.json
```

提交后核对父任务、原业务日期、月分区、标签及终态。若提交应答不明，先查现有运行。若原任务失败，核对已保存的源页、候选、正式文件及检查，按上节边界处理。成功后复用两条交付通知及原检查验收，只对当月目标做独立物理核验。

### 10.2 正式结果（2026-11-07）

原月线续跑`0520645a-b855-4eca-ba31-52fab8da05b0`于08:25:39开始、08:34:22成功（北京时间）。原父链、11月6日意图、`2026-11`分区及本次8 GiB标签读回一致。41个源单元全部完成，范围仍为20只两频历史及11月全市场月线，源单元记录的最大`end_date`均为11月6日。实际提交1,737份周Raw、412份月Raw，与预核数量一致，合计374,592,491字节为已提交文件的压缩大小。两条Raw通知引用同一文件交付摘要。

月线Silver任务`b2b7dbf6-59fc-439e-879d-b4585fb3e976`于08:34:54成功，传感器08:37:30确认155份月文件及465项检查。周线Silver任务`acf956b2-5c2e-4d6f-897f-ad487f2dbd1e`于08:37:16成功，传感器08:38:15确认659份周文件及1,977项检查。

独立计数确认`2026-11`的Raw、Silver文件各5,574行、各5,574个唯一键。两层均有5,573行的`end_date=20261106`，各保留1条较早源日期，最大日期为11月6日。Raw、Silver各三项原检查全部通过，分别绑定当月物化`7943539`和`7944809`。共享因子及月线日更水位已到11月6日，周线全市场日更水位仍为11月5日。收尾时Raw本批的`files_complete`待办仍留在共享状态，标记为已消费，待后续原Raw流程确认。两频Silver回执均已确认。

<a id="monthly-daily-point-readiness"></a>

## 11. 当月全市场单点预检与日更

本节当期Raw/Silver已完成第2阶段实现：自然月末单点、三列预检、21列正式下载、当期单文件及Dagster原生交付均经隔离验证。第3阶段独立回刷和第4阶段单频退市清理亦已实现并独立审计，同频Silver可完整接续；新sensor代码默认STOPPED，正式实际状态见下文结果。旧Silver日更私有回执与续跑分支已移除；第5阶段已接入人工维护并清零旧Raw离线入口、共享索引和日常交接，首次建库本次恢复及原Silver审计合同保留；实际测试、独立审计修正及当时全局门禁的历史失败见[周月线LLD第13.17节](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#stock-period-stage-five-results)。该全局suite已在11月12日开工审计完整复核通过，第6阶段细则见[第13.18节](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#stock-period-stage-six-execution)，开发和隔离结果见[第13.19节](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#stock-period-stage-six-results)。正式切换及11月11日补数亦已完成，实际结果见[第13.21节](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#stock-period-formal-cutover-results)。

本节对应[原方案第10.19节](dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md#stock-period-daily-then-history)和[周月线LLD第13节](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#stock-period-daily-then-history-lld)。预检、日更交付、股票复权因子变化历史回刷、Dagster记录及切换沿共享规则，月线只补下列差异。 三列传输、原生交付字段、新任务及实测预算统一见[周月线LLD第13.10节](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#stock-period-implementation-contracts)。

- 上海时间交易日20:00起，月线sensor用同日已验收的在市名单减去当日全日停牌，得到应更新代码集合。输入`freq=month, trade_date=自然月末`，首请求带既有`limit=6000, offset=0`。例如11月10日请求`trade_date=20261130`，只取`ts_code, trade_date, end_date`，每个应更新代码都须有一条当月记录且`end_date=20261110`。全日停牌股票允许有有效记录，也允许缺席。未齐时按原检查间隔重查，通过才提交月Raw。
- 月Raw正式下载沿相同单点请求并核原21列，只交付`month=2026-11/data.parquet`这一类当期文件。全日停牌股票有有效返回就合并，无返回则保留原记录。当天新上市股票由当月全市场日更写入首根月线。月Silver按通过检查的实际Raw交付接续。同日两频Raw日更均完成并通过检查后，复用现行Silver股票复权因子生产、验收及相邻日比较，独立回刷复权因子变化股票。
- 月Raw当日成功并通过原检查后，成功事件sensor向独立清理job提交`freq=month`。只清月线Raw，按退市股票代码统计全部历史月文件，只改命中文件，包含正式上市前记录；月Silver按本次完整交付范围接续。周线成功时独立提交周清理，两频分别记录结果。详见[周月线详细设计第13.8节](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#stock-period-retirement-cleanup)。
- 2026年11月全市场三列实测，`trade_date=20261130`与原月初至月末范围各5,575行，三列双向差集为0。2026年10月单股最后交易日`20261030`返回0行，自然月末`20261031`返回1行。2020年2月范围曾返回28日与29日两种标签，现存历史按原合同保留。全市场当月日更、预检和指定闭合月补齐使用自然月末单点，单股完整历史按`ts_code + freq=month`获取，不传`trade_date`、`start_date`或`end_date`，沿用既有分页。

月线专项回归须证明自然月末非交易日仍按自然月末请求、输入`trade_date`与输出`end_date`分别核对、正式下载与预检使用同一坐标。新回刷任务失败后按原业务范围整批重跑，按源返回的历史日期定位月文件，验证重跑后月线无重复记录、较新的当期行情得到保留。按共享规则清退`baseline.json`、建库交接标记和跨批文件版本目录。历史回刷遇到整月文件缺失时走该月全市场补齐。补建整月文件时，逐日计算应更新代码并取并集。覆盖核对用每只股票在该月最后应更新日，允许源后来重算到更晚日期，Silver用实际交付日期。某日因当期交付不齐而未触发回刷时，沿共享规则核实Raw并按原复权因子日期提交。范围、耗时、重跑和补齐见周月线LLD第13.4至13.7节。

周月一起切换。月线须同步移除全市场按月初至月末取数、月Raw混合日更与回刷、月Silver解析旧日更回执及旧月线脚本入口。切换前对账并交接未完成旧批，保留月线历史文件、首次建库和已确认的校验。首次建库本次执行内的源/COPY/候选恢复保留，`baseline.json`、共享待办和日常交接清退；月线的替换后记录前中断、事件补齐及首次Silver审计报告合同须单独回归，不能用周线通过代替。函数处置及验收统一见[周月线LLD第13.14节](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#stock-period-bootstrap-preservation)。 月线人工指定历史、明确撤回键及混合处理的命令和代码实施统一见[第13.15节](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#stock-period-manual-maintenance-implementation)，仍按实际月标签定位、精确键删除，每月仅生成一份候选并让月Silver完整接续。共用函数、调用方迁移与清退验收见[周月线LLD第13.7节](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#stock-period-legacy-removal)。

第6阶段已实际验收两种Raw先后顺序、自然月末`20261130`与来源截至日`20261110`、当月新股、两月历史回刷、本频退市和完整月Silver接续。闭合月新增缺代码/日期过旧/成功三例，使用自然月末`20261031`，按10月29/30日应有并集及逐股最后应更新日核对；允许后来重算到11月10日，原业务日仍10月30日。原“闭合补建由既有正向回归覆盖”的判断已纠正。月线精确键删除/混合处理、首次建库恢复与事件合同仍由实际月线专项回归证明，不用周线替代。第6阶段数量、性能、独立审计及当时待切换清单见[第13.19节](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#stock-period-stage-six-results)，月线不另设业务状态或上限；第6阶段隔离验收未操作正式资源，后续正式执行另记如下。

**切换前正式只读审计（2026-11-12，历史）。** 当时月Raw定义已加载并采用新配置，月Raw/Silver sensor实际均RUNNING；月Silver为旧`schema_version=1,after=8013873`，需按已核实消费证据转换为`{"schema_version":2,"after":8013873}`，不能清空为0扫旧回执。11月11日月Raw在取源前因旧`request_id/stock_codes`配置不被新worker接受而失败，须以新配置另建运行。当时`2026-11`两层各5,575行，来源截至日仍为11月10日及2条可选旧记录；11月11日的5,574只应更新股票尚无截至该日的记录。旧月执行及历史交付已完成的部分不重跑，旧JSON不再作为日更输入，也不在本步删除物理文件。

切换和补数统一按已获准的[周月线LLD第13.20节](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#stock-period-formal-cutover)，不另设月线方案：先转换Silver，启用两条新sensor并等待自然初始化tick，再探测原日两频源。月线仍用`freq=month,trade_date=20261130`及三列，原日仍齐备才以`intent=daily,automatic_intent_date=2026-11-11`提交现有月Raw job，由原月Silver完整接续；源已前移则沿该节已有分支处理，不用当前尚未闭合的11月补建绕过日期检查。读取范围、预算、失败完整新跑与验收沿该节，不改变21列、正式路径、既有资源上限或首次建库能力。切换前文档准备未操作DG，后续实际执行结果与该历史阶段分开记录。

**正式切换及11月11日补数完成（2026-11-12，09:54最终状态读回）。** 月线三列源实际应有5,574只全部截至11日，另1条可选停牌记录截至9日；原月Raw新运行`12545136-b675-460d-ac35-286ef57e1870`及当期月Silver `09dbfefb-1b68-4601-b24c-b80a4c4bbeec`均SUCCESS。8只股票复权因子变化历史回刷交付232份月Raw，月Silver `6fa20aba-d565-4d0e-9ddf-a6ef5598e0db`按既有2014下限完整接续155份，465项原检查通过。月退市清理 `01a0305d-7596-4d75-9fe2-41f3ff18c9f8`真实登记343只确认名单、零命中文件，未改写历史或触发额外Silver。月Raw/Silver当期文件各5,575行/唯一键，应有代码覆盖完整、21列双向差异0；月Silver游标已推进至`schema_version=2,after=8035725`，无pending。本链六条sensor最终均RUNNING，未重启或重载DG，没有恢复旧代码或修改默认资源；11月12日任务继续等20:00正常窗口。本次九笔正式运行、全部6,112项检查、数量/耗时及清理边界统一见[第13.21节](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#stock-period-formal-cutover-results)。
