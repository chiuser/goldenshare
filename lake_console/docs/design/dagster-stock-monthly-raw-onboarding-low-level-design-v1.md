# 股票月线 Raw 接入：代码级 LLD

日期：2026-10-04，Asia/Shanghai。状态：M10.B 来源/库存/性能与纯合同/规划已完成；capture和正式资产尚未开发，未写入正式数据。依据股票周线原方案、管理员本轮允许周线正式验收延期并推进后续工作的指示，以及数据集接入模板 §3–18，尤其 §7A。设计内容与实测结果分别标注，不能据此宣布月线已接入。

## 1. 阶段边界与已确认口径

- M9 开发及静态/隔离验收通过。管理员核查源站后报告 2026-10-02 周线尚未生成，正式两源更新验收延期，sensor 保持停止。先前 MCP 样本只能作为来源调查，不能替代可交付版本及正式执行验收。
- 本阶段先完成两套月线 Raw 的来源核验、设计与开发准备。周线未完成的正式验收继续单列；允许推进月线不等于取消该门禁。
- Bootstrap 来源为 Prod 两张 Raw 表中 freq=month 的业务字段；不复制采集信息，不读 Serving 反推源值，不修改 Prod。
- 2020 年 2 月仅接入 trade_date=20200228 的未复权与复权数据；20200229 不进入 DG 正式月线。排除数量及样本留在证据台账。不得将 28 改写成 29，不把两版字段拼接。
- 其他月份默认自然月末坐标。源日期保持原值；源 end_date 是计算版本截至日期，历史月份允许晚于所属月，不据此重拉全部复权历史。
- 首期不新增 Silver/Gold、不用日线合成月线、不自行复权、不自动使用备用接口。缺口补齐尽力而为，源空、身份未决、技术失败和未查源分别记录。

## 2. 来源证据与尚欠门禁（模板 §7/7A）

本地接口文档为 doc336（stk_weekly_monthly）与 doc365（stk_week_month_adj）。当前源码已核对 Prod request_builders.py 的月线 builder：复用日期输入逻辑但明确写 freq=month；DG 周线 point、capture、candidate、io、run_contracts 均含 week/周五约束，不能直接传 month。

[本轮 MCP 核验](../../../reports/stock_month_m10_source_probe_20261004.json)记录18次只读请求的参数、行数、字段及首尾样本；大响应未保存全部行，不把样本文件当捕获全集。

| 核验 | 两主源结果 | 对设计的影响 |
|---|---|---|
| 只传必填 freq=month，显式身份/时间字段 | 各6000行 | 触及接口上限，不能宣称无时间请求拿到全集 |
| 对象过滤，无日期，默认字段 | 000001.SZ 历史记录，13/21列 | 支持对象历史调查；不替代全市场bootstrap |
| 20260930全市场关键字段 | 各5571行 | 单个完整月的请求/文件规模样本，不证明与Prod或日线覆盖已闭合 |
| 20260930单对象默认字段 | 各1行 | 默认字段样本；end_date=20260930 |
| 20200201–20200229单对象显式13/21列 | 各2行 | 同一月存在28/29两版本，必须在候选准入前应用既定选择 |
| 20260531与20260529单对象 | 月末各1行；29日各0行 | 不能将所有月份改为最后交易日 |
| 20200228与20200229复权样本 | close_qfq分别12.01/11.14，close_hfq分别1582.96/1582.95 | 排除29日不能改成同股票价格合并或“同值去重” |

MCP schema不提供limit/offset；2026-10-04已用既有监督执行器补20次SDK只读调用，单源2020对象13行的5/5/3/0分页与完整响应逐字段一致，9月全市场5571行及空尾页闭合，前三小页与完整响应前39行逐字段一致/无重复。参数、预算、哈希及实际CSV引用见reports/stock_month_m10_pagination_20261004.json；没有安装或同步依赖。

Prod范围已在本轮刷新，仍为2010-01-31至2026-09-30，范围外行数0。两表原月线711255/710444行，各排除3682条20200229后预计707573/706762行。唯一非月末源日期为20200228，17年度有序代码和日期计数已冻结。Price/qfq/hfq为Numeric(18,4)、vol/amount Numeric(20,4)、pct_chg Numeric(10,4)已由当前metadata确认；Prod DATE经YYYYMMDD业务文本投影，不复制内部采集字段。代表300代码年度读取走主键Index Scan；真实临时候选Decimal写出/读回无损。此证据不等于正式capture/apply授权。
## 3. 数据集说明卡及字段契约（模板 §3–6/8–10A）

| 项目 | 未复权 | 复权 |
|---|---|---|
| dataset_id / 拟定asset key | stk_period_bar_month / raw_tushare_stk_period_bar_month | stk_period_bar_adj_month / raw_tushare_stk_period_bar_adj_month |
| Prod表 | raw_tushare.stk_period_bar | raw_tushare.stk_period_bar_adj |
| 源API | stk_weekly_monthly | stk_week_month_adj |
| 物理业务主键 | (ts_code,trade_date,freq) | 同左 |
| 正式布局草案 | raw/tushare/stk_period_bar_month/month=YYYY-MM/data.parquet | raw/tushare/stk_period_bar_adj_month/month=YYYY-MM/data.parquet |
| 分区身份草案 | cn_a_stock_months；键YYYY-MM | 共用月分区，但文件及check各自独立 |
| 层级/域/组 | Raw / equity_market / stock | 同左 |
| 更新job草案 | raw_stk_period_bar_month_update_job | raw_stk_period_bar_adj_month_update_job |

正式根固定 /Volumes/datasource/data_lake；candidate、receipt、控制文件固定 /Volumes/datasource/data_lake_staging。新路径和分区定义仍为设计稿，未注册。YYYY-MM是物理分区坐标，不新增到业务Parquet字段；读取显式 hive_partitioning=false。

未复权字段顺序：ts_code,trade_date,end_date,freq,open,high,low,close,pre_close,vol,amount,change,pct_chg。复权在pre_close之后增加open_qfq,high_qfq,low_qfq,close_qfq,open_hfq,high_hfq,low_hfq,close_hfq。

ts_code/trade_date/end_date/freq使用VARCHAR，日期源值YYYYMMDD，freq固定month。价格/change/qfq/hfq使用DECIMAL(18,4)，vol/amount DECIMAL(20,4)，pct_chg DECIMAL(10,4)，已与当前Prod类型及代表Decimal读回一致，纯合同已冻结。必填仅业务键三列；保留行情与end_date合法NULL，禁止先转DOUBLE再声称无损。保留源单位和pct_chg口径，不重命名change、不用字符串0填NULL。

definition metadata登记schema、中文名称、来源、合同、路径模板、日期规则和2020例外；运行metadata仅记录本次行数、文件/证据引用、阶段与请求数。运营失败说明须包含源、月份、原因及可采取的手动动作，不能只报内部hash。

## 4. 时间输入、执行与完整性三层拆分

运营输入为月份点或月份区间；planner输出完整自然月范围。月份键只负责划分文件，不直接透传Tushare。request builder对普通月生成自然月末YYYYMMDD，对2020-02生成20200228。区间按月份展开；所有源参数集中由builder生成，asset/sensor不拼日期。

Bootstrap读取范围按自然年度闭开区间和明确代码批次，读取所有Prod该范围month源行。候选统计：captured = accepted + excluded_by_explicit_policy + rejected；20200229属excluded_by_explicit_policy，不是坏数据reject。其它非月末源日期先列异常并停止对应候选，不静默删除；必须完成分类才冻结计划。

月度完整性依据“该股票该自然月有实际日线”形成期望键，身份仅用于审计；整月停牌/已退市无日线不制造缺口。原始证券代码不改写。源end_date至少覆盖该股票当月最后实际日线，且是合法日期；历史end_date晚于该月合法。Bootstrap原样保留Prod历史NULL，新增自动交付缺截至证明则停止。两种交付证据不同，不把历史复制门禁误当新增源完成门禁。

Raw保留批准投影的全部历史源值，20200229是管理员明确的唯一已确认排除，必须与“Prod全量”一起解释；不能在报告隐藏这一例外。

## 5. 配置审计与性能预算（模板 §7A/13）

所有拟定值集中于新StockMonthlyPolicy不可变typed配置；没有新增env/数据库配置/页面开关。来源为代码版本，消费者为planner、Prod adapter、capture、candidate、update、sensor和测试；hash进入意图/receipt。reload只影响新意图，既有续跑沿冻结值。下列为设计上限，不是当前实测耗时或RSS。

| 配置及默认值草案 | 消费者、预算依据和拒绝方式 |
|---|---|
| timezone=Asia/Shanghai；daily_start_time=19:30；tick_min_seconds=60 | 月线sensor沿已确认更新窗口，只更新已结束月及欠账；正式启用另批 |
| page_limit=6000；max_pages=4；max_retries=2；call_timeout_seconds=20；minimum_interval_seconds=1；source_concurrency=1 | 每源/月最多12调用，两源最多24；满页到cap仍未闭合则拒绝，不能当成功 |
| max_codes=10000；max_update_rows=10000 | 当前两源单月5571行；超限停止并重新评估，不静默截断 |
| prod_code_batch=300；fetch_batch_rows=10000；max_prod_unit_rows=10000 | 年度×300代码通常≤3600键，2020异常版本额外计数；超限细分unit |
| prod_max_connections=1；prod_statement_timeout_ms=30000；prod_unit_seconds=45；prod_work_mem=32MB；prod_csv_max_bytes=64MiB | 原唯一psql脚本，单unit READ ONLY事务/ROLLBACK；每批持久化；取消不领取新unit |
| duckdb_memory_limit=512MiB；threads=2；max_temp_directory_size=2GiB | staging内spill；进程RSS另采样，不能将buffer上限说成RSS上限 |
| max_year_rows=120000；max_year_partitions=12；max_capture_rows=4020000 | 10000代码×12个月/年，201个月×两源的规划上界；源异常日期需另行对账 |
| max_daily_files=31；max_reference_rows=320000；max_reference_sql=80 | 全月日线一次向量化键聚合，最多31物理schema核验；避免复制周线5文件/50000行门槛 |
| max_materialization_versions_per_date=10；max_upstream_check_records=320；max_event_records_per_tick=2000 | 日线4checks是target materialization绑定，月份可能超过20个交易日，不能直接沿周线20条check历史；批查询最多310mats+1280check记录，超过窗口即阻断 |
| control_max_bytes=1MiB；event_write_batch=100 | 有界控制文件；独立事件补录每批不超过100写入 |

单月正常每源1请求（5571<6000），两源2请求；满页额外空页纳入预算。最坏网络超时部分两源480秒，另计间隔/校验，取消每页前后及等待中检查；20秒不可分割源调用须已有监督子进程可终止。预计耗时需真实小页/完整月只读验证后填入，不伪报分钟数。

按历史范围2010-01至2026-09共201个月，规划最多402正式文件；2020例外不额外产生分区。年度代码unit数公式sum(ceil(年度distinct代码/300))，两源分别测算；上界2×17×ceil(10000/300)=1156个unit，每unit预检+COPY最多2业务SQL，连接最多1156次、串行1个。实测库存通常远低于上界；库存/计数/API超预算立即停止。单文件大小、spill峰值与RSS必须真实样本测量，不套固定小文件MB阈值。

## 6. 实现拆分及复用边界（模板 §9/11–16）

本设计不直接复制整个weekly执行栈，也不在M9等待实测期间修改其执行语义。先实现月线纯合同/规划和独立的薄adapter；可直接复用现行DuckDBConnectionSettings/connect_configured_duckdb、资源装配、统一run key/config/tag/metadata builder及psql唯一入口。

以下是代码级拆分草案，不是已存在实现：

| 文件 | 核心接口与职责 | 禁止项/验收 |
|---|---|---|
| defs/run_contracts/stock_monthly.py | StockMonthlySource仅两主源；MonthlySchema、MonthlyPolicy、MonthlyIntent、MonthUnit/Manifest；normalize_month_key、request_date_for_month | week/备用源输入拒绝；2月28例外由此唯一生成 |
| defs/stock_monthly_planner.py | plan_month_bootstrap(inventory,policy)、plan_month_update(now,calendar,state) | 无IO；只结束月；完整库存冻结hash，未查源不记无源 |
| defs/prod_db/stock_monthly.py | build_prod_monthly_query(unit)、capture_prod_monthly_unit | 表/13或21列/freq=month显式白名单；只读事务、超时、取消；不COPY采集字段 |
| defs/bootstrap/stock_monthly_capture.py | capture_month_unit→receipt；resume验证来源/参数/schema/页hash与请求账本 | 单页先持久化；重复执行不重取成功页；拒绝截断、float精度损失 |
| defs/io/stock_monthly_raw.py | validate_month_relation、classify_month_versions、canonical_month_hash、write_month_candidates | DuckDB SQL列式；20200229留排除台账；不修改业务trade_date |
| defs/bootstrap/stock_monthly_promote.py | audited候选→同文件系统os.replace；每文件锁/目标fingerprint/checkpoint | 不调用周线的WEEK_SQL/周五validator；同值幂等、异值修订审批；禁止备份/Kopia |
| defs/stock_monthly_point.py | deliver_month_intent；capture→validate→promote→delivery证据 | 唯一月线writer；业务文件提交后观测失败不回滚 |
| defs/source_readiness/stock_monthly.py | freeze_month_references、verify_month_completion | 至多31日线文件与身份快照；按个股截至；只读批查询，不逐股查询 |
| defs/assets/stock_monthly.py、checks/stock_monthly_checks.py | 两Raw assets；各schema、key/value、delivery三个blocking checks | checks只读本文件及冻结交付证明，不在线调用源、不重扫Prod |
| defs/jobs/stock_monthly.py、sensors/raw_stock_monthly_update_job_sensor.py | 两精确asset+checks jobs，一sensor串行、默认STOPPED | 无fallback；同日/源/月一个意图；先补最早欠账，不当前月快照 |
| paths、partitions、column schemas、configs、name mapping、catalog、静态/治理测试 | 单事实源登记；中文事实卡、分区及统一config builder | 消费者与测试一次迁移；不动Prod DatasetDefinition/前端日期合同 |

在capture/promote具体编码前还须单独完成“可抽取的无频度原子IO能力”审计，确认是否有必要共享；若需改变现有weekly helper合同，先出精确迁移影响面并取得确认，不能顺带重构。当前weekly的WeeklyCaptureStore/Manifest、WEEK_SQL、normalize_week_key、年度54分区和primary_exclusion_forbidden都不可直接作月线通用实现。优先复用已经真正无频度的基础能力，不为复用保留双轨或旧兼容层。

月线upstream daily/identity refs是执行门禁，Raw业务资产不据此宣称依赖日线重算行情。新增是否需要显式asset deps/partition mapping必须在definitions集成前逐消费者审计，不能仅因readiness读过文件就添加图依赖。

## 7. 自动更新与恢复、UI观察

每日19:30后检查最早未交付的完整自然月；两源串行，pending时不查源。同日同源同月失败不会每tick重开job；次日新意图可再试，技术重试仍遵守持久化上限。cursor只记录检查进度，不代替物理文件及passed check目标绑定。

请求意图冻结source/month/request_date/字段/预算/策略版本；request_date与YYYY-MM分区分离。成功页receipt先封存再处理下一页；进程退出重新验证已封存页。promote按文件checkpoint，先检查源证明和目标fingerprint；提交后check/event失败只影响观测，保留文件并显式恢复观测。异值产生revision_required说明，不自动覆盖bootstrap复权版本。

日志按阶段、source、月份、页/批、已完成/总量、行数、最后更新时间输出；调用监督期间≤30秒有可见阶段更新。无法可靠估时显示“暂无法估算”。错误至少区分source_not_ready、page_cap、identity_unresolved、source_missing_keys、excluded_month_version、revision_required、event_observation_failed。手动修订/补齐仅提示明确范围，不自动调用备用。

## 8. 测试和真实验收矩阵（模板 §17/18）

| 硬口径 | 必需正例与反例 |
|---|---|
| 月份与源日期分离 | 周末月末20260531；20200228例外；20200229/20260529误作普通锚点拒绝；year/leap/month边界 |
| 13/21列源镜像 | NULL、Decimal边界、顺序/类型一致；采集字段额外列、freq=week、float精度损失拒绝 |
| 2020排除守恒 | 捕获28/29两版，候选只28；排除样本/计数可追溯；缺28时不以29代替 |
| bootstrap只读/有界 | 脚本调用、只读事务先于查询；cancel、unit超时、错表/范围/SELECT *拒绝 |
| 完整月分页 | 小页真实键闭合；满页继续、空尾页；跨页重复、cap满页、异值同key拒绝 |
| 写湖安全 | 私有临时候选、实际os.replace中断、checkpoint续跑、重放同值、目标并发变化拒绝 |
| 自动门禁 | 19:29/19:30、当前月不提交、两个源分别失败、同日去重、queued串行；无备用请求 |
| 月度上游 | >20交易日的target-check绑定；缺日线/身份/历史窗口不足阻断，不以心跳当数据进度 |
| 可恢复与观测隔离 | 实际子进程退出、取消后不领新unit、预算不重置；提升后观测失败文件仍在 |
| 正式定义一致 | catalog/name/schema/path/partition/config消费者和精确测试清单；真实临时job各3个checks绑定正确partition |

最小真实只读阶段对齐源响应、归一化、候选行数及拒绝样本；正式sample需独立批准，选择一个普通月、周末月末及2020例外，按当前Prod inventory冻结代码/文件范围。文件对账与事件补录分别批准；事件必须绑定通过校验的正式文件，不拿runless代替日常job。全历史主验收使用年度聚合/差集及少量样本，不对402文件逐个深扫历史check。

## 9. M10切片与当前结论

M10.A 本文及真实源调查；M10.B 补月线真实分页、Prod最新库存和类型/代表unit预算，然后冻结纯合同/规划；M10.C capture/候选/提升隔离开发；M10.D definitions/手动与自动更新集成；M10.E 分阶段正式bootstrap及事件；M10.F 最小真实更新与调度启用。

此前M10.A完成初稿和18次MCP来源调查；本轮M10.B已完成20次SDK分页、Prod最新库存/类型/代表unit性能与纯合同/规划代码和66项测试。计划为两源各225个unit、201个月，共450units/402文件，最大3900源行/unit。没有创建月线资产或正式目录、注册动态分区、运行月线job，也没有启用周线sensor。下一切片为M10.C隔离capture/候选/提升开发。M9源就绪后另行恢复原正式验收，不能把月线结果替代周线验收。

CodeGraph explore覆盖point/capture/candidate/manifest及Prod模型关联；当前代码进一步核对日期builder、schema、SQL分桶、原capture预算和模板§7A。设计不修改src依赖矩阵，不引入旧lake、Kopia或src/ops组合入口。

## 10. M10.B落地与硬口径对账（2026-10-04）

run_contracts/stock_monthly.py已实现两主源/字段类型/月份日期/2020例外/typed预算/请求生成/不可变库存和计划；stock_monthly_planner.py已实现年度闭合、证据/策略hash、代码批次、末年截止及确定性unit。没有抽取或修改weekly公共合同，避免M9待正式验收期间改变其执行主链。后续模块名/接口仍为§6的设计，未伪称已存在。

两组新测试66项，连相邻周线共136项；完整113项受保护静态检查、Ruff、全src/tests致命错误基线与整个code location临时instance加载通过。隔离器新增两个月线纯模块和本轮出现的4个公告源码精确只读路径，不执行公告业务逻辑、不扩大正式数据或网络访问。

真实Prod样本3854/3860源行，排除293/295后读回3561/3565行；24个临时Parquet、schema/双向全字段差集/重复键全部0。两源EXPLAIN执行14.405/11.468毫秒，转换/写读0.245/0.074秒，累计RSS峰值162.953MiB。只记录结束spill=0，未测过程峰值/强制spill，未宣称全量性能完成。按真实库存225units/源，bootstrap unit业务SQL上界900；450×45秒只为20250秒超时边界，不是ETA。预计Raw压缩约80MB为样本密度推算，必须以正式读回校准。

typed StockMonthlyPolicy本轮落地配置仅prod_code_batch/max_codes/max_prod_unit_rows/max_year_rows/max_capture_rows/page_limit/max_pages/max_retries/max_update_rows，来源为此模块，消费者为纯planner/request builder与测试，asdict进入plan hash，不新增env或运营开关。其余§5执行/调度配置仍是设计值，下一切片实现前再核对消费者和实测。计划文件仅规划证据，正式apply授权仍独立；未来capture须验证库存文件当前hash与新源计数，不能把本次快照长期当最新库存。

详见[本阶段验收报告](../../../reports/stock_month_m10_assessment_20261004.md)。阶段范围不含月线历史缺口全量清零证明、正式写入、事件补录或自动更新启用；M9待源端就绪单列保留。
