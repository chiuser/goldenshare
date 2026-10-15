# DG 复权月线直接源 Bootstrap 与每日更新 LLD v1

更新：2026-10-16。已确认先删除旧Raw再直接源重建，待开发与正式验收；现行月线仍只交付已完成月。独立未复权DG月线已物理清退，不恢复。本轮只改文档，不下载、不改正式数据或sensor；当前主线先Raw后Silver，不展开其他任务。

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

bootstrap与单股复权刷新的业务参数为有效ts_code、freq=month，另显式fields及技术分页参数limit/offset，不传时间参数；北交所只用确认新码。日常当前月请求freq=month、trade_date=自然月末；月份未结束也刷新同一月文件，日期不改成当天或最后开市日。2026-10-16凌晨实测20261031已有截至20261015的数据。

## 2. 2020年2月的两条源记录

旧实现固定保留20200228、排除20200229，已经不适用于保留完整源回包的新设计。2026-10-16以000001.SZ+month、不传时间实际返回427行，其中：

| trade_date | end_date | close | close_qfq |
| --- | --- | --- | --- |
| 20200229 | 20261015 | 14.50 | 11.14 |
| 20200228 | 20250910 | 14.50 | 12.01 |

两行同属month=2020-02但原始业务键不同，均保留全部21列；不能把28改29、固定丢29日或按月份/证券只留一行。月线完整性检查必须允许这个已实测来源事实，同时仍拒绝同一原始业务键的异值冲突。原日期分类、排除计数、候选、检查及测试一起迁移，不能只改说明绕过旧门禁。未来Silver按有效版本选整行，另行设计，不在Raw提前删版本。

<a id="3-2026年8月的已确认修订"></a>
## 3. 旧数据问题如何结束

旧DG8月有大量月底前版本，平安银行close=11.65/截至20260828；2026-10-15源样本close=11.72。4月等还存在旧截止与复权价格差异。新路线先删除旧月线Raw根（与周线两根同时完成），再下载所有选定股票的完整源历史；8月及其他月份只由新源返回构建，不再为每个月建立修补入口或先全量对比旧DG。

本数据集仅保留确认仍上市股票的行情；退市股票不请求，全市场日常回包中的退市行也不入湖。旧月线根整体删除，不读取旧文件逐行剔除、不合并旧键、不保留源未返回的旧行情、不用旧Prod兜底。换码不等于退市，旧码禁止出站请求，新码获取完整历史，Raw不把旧行直接改名。原只读覆盖/搬运证据可追溯但不重复跑，不要求先从日线证明所有历史月份完整，不用日线合成月K。

月线固定删除目标仅为/Volumes/datasource/data_lake/raw/tushare/stk_period_bar_adj_month，周线根及共同删除门禁见[共享LLD](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md#31-删除边界与数据空档)。先完成新程序隔离验收、样本验证及唯一写者切换，删除完成再启动正式bootstrap。进入下载后续跑不得再次清空根；成功片段与已提交新文件继续复用。删除后的缺数窗口不能凭旧物化判定月线就绪；未完成对象明确记录，无旧数据回退。

本轮删除不涉及Silver或其他数据集；后续以验收后的Raw生成Silver，不把其他系统的月线维护列为开发步骤、前置或验收项。

## 4. 日常覆盖与历史刷新

每个交易日源发布后覆盖当前月；首次月初即写入月末坐标，不等next_month(frontier)变成已完成月。当天刷新完成与整月已结束分开观察。停牌股的end_date不必等当天，历史end_date晚于trade_date也是合法源计算版本。

因子变更股票用新码请求month全历史；与当日当前月回包统一汇集，受影响月文件每次只组装/提交一次。完成的单股月片段可恢复，不再下载同一历史。日常触发与周线共用现有相邻交易日因子差异；bootstrap和主动历史下载无需通过因子变化检查，直接保存最新源历史，不本地重算复权价。不引入独立历史因子探测或月线全历史扫描sensor，不包含日线、分钟及指标历史修复。

当前stock_monthly_point.py采用create_or_identical，异值报revision_required；source_readiness依赖整月日线/上游检查，sensor按已完成月推进，均需按新合同迁移。允许当前月每日异值更新不等于添加通用force开关。检查仍绑定本次真实文件和准确物化，不长期读取旧bootstrap证据。

## 5. 改动范围与最小验收

2026-10-16分页实现方式已明确：参考Prod月线的limit/offset循环，满6000行继续、短页（含必要空末页）结束，不照搬周线专项页数预算。此前源小样本超时，本轮连通性和吞吐尚未验收；具体Raw文件/消费者清单、成本模型与剩余最小验证统一见共享LLD §5.1—6，不在月线复制第二份预算。当前仅调整文档，未开发新Python或删除正式Raw。

开发影响：assets/jobs/checks/stock_monthly.py对应模块、raw_stock_monthly_update_job_sensor.py、stock_monthly_point/update/update_state、source_readiness/stock_monthly.py、run_contracts/stock_monthly.py/configs/schema、catalog、bootstrap月线CLI及共用源执行器；具体复用/删除先核消费者。共享事件绑定、分区名和asset key保留。Prod导出旧入口不得继续写本目标，新源入口统一拒绝北交所旧码。

复用共享LLD的正反清单，月线额外验：自然月末为周末仍可请求，月中可更新且不推进已完成月，20200228/29原始行均保留，因子变更仅刷新对应股历史，异值按已确认源刷新合同提交，首次源空/缺页/身份不符保持未完成、不写空文件，日常源空不覆盖新基线，退市对象出站请求数和正式Raw/Silver行数均为0，旧根删除后没有旧键或退市存量回流，删除中断可续且下载后续跑不再清根。历史生成、当前月更新、取消续跑、事件失败分别验收，不拿旧双源通过结果替代新代码。

<a id="12-m10c-落地与验收2026-10-05"></a>
<a id="后续真实验收执行卡2026-10-06准备完成"></a>
Raw验收后，月线Silver消费本Raw而不重下源；共用仍上市集合、保留三套价格，规范日期和确认身份，2020年2月双日期等按完整源版本择行，不拼字段。具体schema、择版与job/check合同在Silver开发前明确。历史刷新涉及的每个月都传递，不能只处理当前月；Silver未完成不能关闭周/月主线。

2026-10-05旧bootstrap两源402文件的搬运事实只作历史；2026-10-15未复权月线201文件已删除。旧排除20200229及双源执行卡不再是当前计划，完整记录见[历史结案](../../../reports/stock_period_raw_closeout_20261006.md)和Git。Silver未实施，后续按真实变更月消费，不只消费最新月。
