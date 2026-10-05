# 股票月线 Raw 接入：代码级 LLD

日期：2026-10-04，Asia/Shanghai。状态：M10.C已提交ac063248；M10.D两套月线definitions及手动/自动更新开发和隔离验收完成，未执行正式bootstrap或启用调度。依据股票周线原方案、管理员本轮允许周线正式验收延期并推进后续工作的指示，以及数据集接入模板 §3–18，尤其 §7A。设计内容与实测结果分别标注，不能据此宣布月线已接入。

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
| 层级/域/组 | Raw / quote_data / quote（与当前registry一致） | 同左 |
| 更新job草案 | raw_stk_period_bar_month_update_job | raw_stk_period_bar_adj_month_update_job |

正式根固定 /Volumes/datasource/data_lake；candidate、receipt、控制文件固定 /Volumes/datasource/data_lake_staging。M10.D已在代码登记路径与cn_a_stock_months分区定义；正式instance的动态分区键仍未注册。YYYY-MM是物理分区坐标，不新增到业务Parquet字段；读取显式 hive_partitioning=false。

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

以下列明bootstrap与M10.D definitions/更新接口；实际隔离验收见§14：

| 文件 | 核心接口与职责 | 禁止项/验收 |
|---|---|---|
| defs/run_contracts/stock_monthly.py | StockMonthlySource仅两主源；monthly_column_specs、StockMonthlyPolicy、MonthlyBootstrapIOPolicy、MonthlyProdUnit/MonthlyBootstrapPlan；normalize_month_key、request_date_for_month | week/备用源输入拒绝；2月28例外由此唯一生成 |
| defs/stock_monthly_planner.py | plan_month_bootstrap(inventory,policy)；纯更新日期/意图位于stock_monthly_update.py | 无IO；只结束月；完整库存冻结hash，未查源不记无源 |
| defs/prod_db/stock_monthly.py | build_prod_monthly_query(unit)、build_prod_monthly_export_sql、PsqlMonthlyExporter.export | 表/13或21列/freq=month显式白名单；只读事务、超时、取消；不COPY采集字段 |
| defs/bootstrap/stock_monthly_capture.py | MonthlyCaptureStore.capture_unit/read_receipt、build_month_candidates；bootstrap unit receipt验证来源/参数/schema/字节hash；新增源分页由stock_monthly_point独立承载 | 单页先持久化；重复执行不重取成功页；拒绝截断、float精度损失 |
| defs/io/stock_monthly_raw.py | validate_month_relation、load_monthly_csv/parquets、canonical_month_hashes；候选由build_month_candidates列式分桶 | DuckDB SQL列式；20200229留排除台账；不修改业务trade_date |
| defs/bootstrap/stock_monthly_promote.py | promote_month_candidates：audited候选→同文件系统os.replace；每文件锁/目标fingerprint/checkpoint | 不调用周线的WEEK_SQL/周五validator；同值幂等、异值修订审批；禁止备份/Kopia |
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

此前M10.A完成初稿和18次MCP来源调查；本轮M10.B已完成20次SDK分页、Prod最新库存/类型/代表unit性能与纯合同/规划代码和66项测试。计划为两源各225个unit、201个月，共450units/402文件，最大3900源行/unit。没有创建月线资产或正式目录、注册动态分区、运行月线job，也没有启用周线sensor。2026-10-05 M10.C已完成隔离开发，见§12；下一切片为M10.D正式definitions与手动/自动更新机制集成。M9源就绪后另行恢复原正式验收，不能把月线结果替代周线验收。

CodeGraph explore覆盖point/capture/candidate/manifest及Prod模型关联；当前代码进一步核对日期builder、schema、SQL分桶、原capture预算和模板§7A。设计不修改src依赖矩阵，不引入旧lake、Kopia或src/ops组合入口。

## 10. M10.B落地与硬口径对账（2026-10-04）

run_contracts/stock_monthly.py已实现两主源/字段类型/月份日期/2020例外/typed预算/请求生成/不可变库存和计划；stock_monthly_planner.py已实现年度闭合、证据/策略hash、代码批次、末年截止及确定性unit。没有抽取或修改weekly公共合同，避免M9待正式验收期间改变其执行主链。后续模块名/接口仍为§6的设计，未伪称已存在。

两组新测试66项，连相邻周线共136项；完整113项受保护静态检查、Ruff、全src/tests致命错误基线与整个code location临时instance加载通过。隔离器新增两个月线纯模块和本轮出现的4个公告源码精确只读路径，不执行公告业务逻辑、不扩大正式数据或网络访问。

真实Prod样本3854/3860源行，排除293/295后读回3561/3565行；24个临时Parquet、schema/双向全字段差集/重复键全部0。两源EXPLAIN执行14.405/11.468毫秒，转换/写读0.245/0.074秒，累计RSS峰值162.953MiB。只记录结束spill=0，未测过程峰值/强制spill，未宣称全量性能完成。按真实库存225units/源，bootstrap unit业务SQL上界900；450×45秒只为20250秒超时边界，不是ETA。预计Raw压缩约80MB为样本密度推算，必须以正式读回校准。

typed StockMonthlyPolicy本轮落地配置仅prod_code_batch/max_codes/max_prod_unit_rows/max_year_rows/max_capture_rows/page_limit/max_pages/max_retries/max_update_rows，来源为此模块，消费者为纯planner/request builder与测试，asdict进入plan hash，不新增env或运营开关。其余§5执行/调度配置仍是设计值，下一切片实现前再核对消费者和实测。计划文件仅规划证据，正式apply授权仍独立；未来capture须验证库存文件当前hash与新源计数，不能把本次快照长期当最新库存。

详见[本阶段验收报告](../../../reports/stock_month_m10_assessment_20261004.md)。阶段范围不含月线历史缺口全量清零证明、正式写入、事件补录或自动更新启用；M9待源端就绪单列保留。

## 11. M10.C 开发约束与复用审计（2026-10-05）

本切片只开发 Prod bootstrap 的 unit 捕获、年度候选和逐月原子提升，不注册资产、不运行正式写湖或事件、不处理自动更新源分页（随M10.D点更新集成）。M10.B真实样本与预算作为依据：两源450 units、402 files、1,414,335 accepted rows；每unit≤10000行/64MiB，每年度≤120000行/12候选，最多34年度集合扫描，不做402次历史readiness深扫；DuckDB 512MiB/2线程/2GiB spill，候选逐文件提交，失败重试只读已完成unit。

CodeGraph及当前源码确认：DuckDB连接入口真正不含频度，可直接复用且不修改；ETF bootstrap atomic_write_json虽无频度，却耦合ETF模块且无fsync/路径/并发完整门禁，不抽取它；weekly capture、年度装配、hash、promote均含周合同，不能作为月线入口。新增月线专用files模块集中路径、字节hash、有界JSON、fsync原子控制文件和已设计的flock；没有重构现行通用能力。

配置沿代码版本冻结：新增不可变MonthlyBootstrapIOPolicy，专管prod_statement_timeout_ms=30000、prod_unit_seconds=45、prod_work_mem_mb=32、prod_csv_max_bytes=64MiB、control_max_bytes=1MiB、inventory_max_bytes=16MiB、duckdb_memory_mb=512、duckdb_threads=2、duckdb_temp_mb=2048、process_shutdown_seconds=2。它与纯范围StockMonthlyPolicy分工，IO配置hash进入run目录/receipt/audit，不新增env、数据库配置或运营开关；消费者只有Prod exporter、capture、年度候选和promoter，变更只生成新执行目录，不沿新配置续跑旧receipt。冻结计划显式保留月份范围和年度库存，用纯planner重算计划，核验库存文件hash后才开始unit。

硬口径映射：

| 口径 | 代码与验收 |
|---|---|
| Prod只读、完整13/21列、month、年度×代码白名单 | prod_db/stock_monthly.py；SQL正反例、监督子进程超时/取消/字节限制 |
| 成功unit立即持久化，退出可读回，不重取 | bootstrap/stock_monthly_capture.py；receipt/hash/schema/范围校验、进程退出/重放/取消 |
| 不丢失Decimal/NULL，28/29先完整捕获 | io/stock_monthly_raw.py；CSV文本严格Decimal校验，捕获后独立排除台账、守恒及双向EXCEPT ALL |
| 年度库存不漂移，失败不提升 | 年度builder；日期行数/代码集合对照、缺unit/缺行/错频/异常日期/重复键反例 |
| 正式文件不覆盖异值，安全续跑 | bootstrap/stock_monthly_promote.py；全候选复验、文件fingerprint、flock、同文件系统、os.replace、checkpoint、中断窗口和同值幂等 |
| 不碰正式资源/旧湖/备用/其他任务 | 所有测试仅私有临时目录，未新增Dagster definitions；路径拒绝与静态门禁 |

本轮隔离验收使用M10.B已导出的业务样本，不重新查询Prod或Tushare；真正全量读取和正式提升仍须独立批准。临时测试结果不证明正式Lake已存在月线，也不替代M9源就绪后的正式更新验收。

写入预检沿既有预算推导，不新增开关：正式根要求datasource卷已挂载、两根既存且可写；采集前staging剩余空间至少2×prod_csv_max_bytes+control_max_bytes+duckdb_temp_mb×MiB；年度候选前至少max_year_rows×512字节+control_max_bytes+duckdb_temp_mb×MiB（类型/固定长度业务字段的保守序列化上界）；提升前staging也预留DuckDB spill上限；提升只作同卷rename，目标卷剩余空间至少control_max_bytes+12×4096字节用于目录和checkpoint。低于预算立即拒绝，不用实际写满磁盘验证。维护窗口和正式执行审批由M10.E命令入口承担，M10.C不自主执行。

## 12. M10.C 落地与验收（2026-10-05）

§11列出的五个模块、纯计划范围/库存自校验以及MonthlyBootstrapIOPolicy已落地；新test_stock_monthly_bootstrap覆盖两套源、实际子进程退出/取消/超时/字节限制、全字段Decimal/NULL、源范围与重复键、候选与库存篡改、跨执行目录共享月锁、同值重放/异值修订、原子提升后checkpoint前中断、控制文件失败不回滚、续跑、跨卷及低磁盘拒绝。capture receipt封存前fsync业务文件和目录，候选按年度集合读回；promoter先完整复验年度candidate与原capture/排除记录，再逐月加锁、复核target、同卷rename和checkpoint。没有声称多文件整体原子。

使用上阶段已导出的各300代码真实Prod样本，3854/3860捕获，排除293/295后3561/3565进入24个私有临时文件；全字段双向差集0、2月仅20200228，重放不重复导出且文件不变。全链路含重放0.943/0.895秒，累计进程RSS峰值351.859MiB，结束spill=0；未测全量、峰值spill或强制spill。旧样本空NULL仅转换为新CSV传输的明确\\N表示，不改变业务值。导出snapshot证据为隔离替身，不能替代新的真实Prod事务验收。

月线111项、月线及相邻周线合计181项通过；完整静态113项、资产治理12项、Ruff、致命错误基线和整个definitions离线隔离加载通过；文档完整性通过。受保护runner只新增本轮月线精确AST只读路径和当前公告任务新增文件的精确发现路径，没有赋予它们网络、正式数据或执行权限。

本轮没有新增正式asset/check/job/sensor/partition或环境配置；没有改动weekly合同和执行代码，也没有Prod/DG正式读写或源请求。唯一源中立复用是既有DuckDB连接入口，并在月线连接中禁止自动安装/加载扩展；未安装任何依赖。新增纯计划字段保存first/last month与immutable inventories，现有planner/测试与bootstrap消费者同步迁移，不新增旧JSON兼容链路。

[验收报告](../../../reports/stock_month_m10c_assessment_20261005.md)及其样本/代码记录保存精确证据。下一步M10.D为两套月线definitions和更新机制集成；正式bootstrap/事件与启用分别待M10.E/F阶段执行，M9正式周线更新验收仍单列等待，不提前完成。

## 13. M10.D 实施约束与配置核对（2026-10-05，开发前）

M10.C已提交ac063248。M10.D按既定口径开发两主源definitions及手动/自动完整月更新；不触发正式写湖、分区注册、事件补录或sensor启用。CodeGraph explore/impact覆盖monthly_target_path、监督传输、周线readiness/config/request入口及registry；继续用当前代码核对catalog/name/schema/path/check/job/sensor和静态消费者。路径唯一生成迁入paths.py，bootstrap保留现行校验入口；不改变其调用行为。Raw无日线计算依赖，日线和身份是执行门禁，不新增重算图依赖。

配置来源全为不可变代码版本：StockMonthlyPolicy管理范围/分页；MonthlyBootstrapIOPolicy管理IO；新增MonthlyUpdatePolicy管理timezone/start/tick、timeout/interval、31文件/320000日线行/80 SQL、10版本/320检查历史/2000事件记录及候选基线2026-09。无env、数据库或页面开关；schema/name/path归注册事实。reload只影响新意图，策略值进入执行hash，旧意图预算不得重置。19:30前零外部读取，pending优先，两源串行。候选基线只有物理文件和绑定checks均通过后才使用，不把2026-09写成已经验收；M10.E完成前默认阻断。

StockMonthlyRawConfig仅write_mode=create_or_identical与automatic_intent_date=None；消费者为asset和统一run config builder；额外对象过滤/备用/overwrite字段拒绝。手动与自动均走完整月日线/身份门禁，日期集中在monthly_point_request生成。手动同次run_id续跑，自动同日source/month稳定意图；每页调用次数先持久化再发请求，成功页立即封存，重启不得重置预算。复用fetch_weekly_request_supervised仅监督传输（显式freq=month，原接口不改），独立月线worker选择两主API；不调用周线validator/assembly。

整月参考键在DuckDB按filename校验、身份join、group聚合，不把320000日线行反序列化为Python列表。冻结参考证据含物理hash、上游materialization/check绑定及有界期望键，新增源end_date必须覆盖每只股票最后日线。持续检查取消，失败保留page/control/candidate；单月promote使用与bootstrap相同source-month锁和create_or_identical，提交后观测失败保留文件。检查只读文件和捕获证明，不查询源/Prod；bootstrap证明将在M10.E事件入口绑定，尚无证明的历史文件不自动成为ready。

新增三种check均按现行编码规范采用asset名+file_contract/key_partition/delivery_reconciliation+check；共享cn_a_stock_months分区。每次asset最多12源调用/10000行；每check最多4页/10000行本月对账，禁止全年度/全历史重扫。sensor一次只处理基线与一个欠账月；日线事件批查询上界1590，加两源绑定仍低于2000，月份超过历史窗口失败关闭。测试覆盖真实临时job的分区check事件、>20交易日门禁、全字段源对账、取消/退出/预算、同值/异值、观测失败不回滚、调度前/后/最早欠账/日内去重及禁止备用。正式验收仍分别属于M10.E/F。

M10.D的历史delivery check直接支持C已冻结的年度audit与逐月promoted checkpoint：只读取该年度至多34份receipt控制文件的hash和本月正式文件，不每月重新扫描整年capture。源全字段深对账仍由C在提升前完成；年度audit把本月logical_hash、源/排除/接受守恒和receipt身份冻结。此路径保留合法历史NULL，不套新增源的日线截至门禁；M10.E负责正式事件绑定，D不发事件。更新proof另有最多4页本月全字段读回，两种明确来源分派，不增加旧实现兼容逻辑。


## 14. M10.D 落地与验收（2026-10-05）

两套Raw月线asset、各3个blocking check、两个精确asset+checks job和默认STOPPED的raw_stock_monthly_update_job_sensor已落地。paths、schema、中文名称、自然月partition model、catalog、typed config、统一run config/cursor/run key均同步；不修改Prod DatasetDefinition、前端、weekly合同或src依赖矩阵。入口metadata显式使用标准builder，checks显式绑定cn_a_stock_months。C原monthly_target_path保留其写入根校验，路径生成唯一引用paths.py。

stock_monthly_point实现持久化请求账、独立页CSV/Parquet/receipt、完整页尾闭合、全字段候选读回、source-month共享提升锁及更新下载全局互斥、同值重用和异值revision_required。成功页后实际进程退出/取消可续跑，预算不重置；提升后观测写失败保留文件。新增源证明冻结全月日线/身份文件及target-check绑定，按个股实际最后日线校验end_date；不改Raw股票代码。source_readiness/stock_monthly使用DuckDB向量化聚合，最多31个日线文件schema检查，固定参考SQL低于80；Python只取≤10000个身份/期望汇总键。Tushare supervisor和event binding是经代码确认的无频度复用，未改变weekly实现。

历史Prod bootstrap与新增Tushare两种delivery proof分别校验：bootstrap沿C年度守恒、本月logical_hash、receipt控制hash和promoted checkpoint，保留历史NULL；新增源沿至多4页原响应CSV/Parquet全字段对账和冻结完整月门禁。checks不发源请求、不读Prod，不每月重扫年度业务capture；M10.E负责正式事件绑定。source/code/month/path/预算都显式验证，源列不带采集信息；20200229不进入正式月线。三个check分别负责物理schema、键/分区和交付对账，不用三个同义checks。

月线相关及相邻周线更新/definitions共242项回归通过；新D测试75项（含两源实际临时job及check事件、22交易日绑定、NULL bootstrap证明、两种交付防篡改、真实进程退出、分页尾页/跨页重复、预算恢复/取消、同值/修订、上游改变/锁、调度时窗/最早欠账/当天去重及禁止备用）。受保护静态113项、治理12项通过，完整code location离线隔离加载通过。新增与主要修改文件Ruff及致命错误基线通过；共享configs.py既存11项Ruff债务与HEAD一致，没有新增诊断。精确AST清单保留其他任务只读路径，不执行其他任务。文档完整性和CodeGraph sync/status通过。

复用10月4日已捕获的9月源响应，各5571行；私有临时日线/身份/事件替身下，源页捕获→候选→提升0.391/0.410秒，双向全字段差集0、重放不重取，文件177072/311668字节。31文件/310000参考键/10000期望代码的SQL生成压力样本，参考聚合0.064秒，控制JSON517866字节；累计RSS峰值357.813MiB，采样spill峰值0，未强制spill。日线/身份/事件是明确替身，不能将上述性能样本当真实日线覆盖或新的源端就绪验收。缓存源各10只股票end_date早于9月30日，进一步说明须按个股最后实际日线判断，不能统一要求月末截至。

没有新的Prod/Tushare请求、正式Lake写入、正式instance事件或分区注册，也没有启用sensor、安装依赖或推送。M9正式周线源更新验收仍单列待恢复。M10.D尚未提交；下一阶段M10.E准备正式命令入口、刷新库存并分阶段bootstrap/事件，写入前仍需要独立执行批准；M10.F才做源实际更新与调度启用。详见[验收报告](../../../reports/stock_month_m10d_assessment_20261005.md)与其JSON证据。
