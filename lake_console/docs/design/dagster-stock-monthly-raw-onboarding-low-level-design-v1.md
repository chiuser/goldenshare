# 股票月线 Raw 接入：代码级 LLD

日期：2026-10-04，Asia/Shanghai。状态：M10.C已提交ac063248，M10.D已提交733fbd61；M10.E文件入口已提交e1f56646，小样本结果已提交a49609db，两源正式全量文件与事件补录均通过，M10.E完成，M10.F正式更新验收及启用仍待推进。依据股票周线原方案、管理员本轮允许周线正式验收延期并推进后续工作的指示，以及数据集接入模板 §3–18，尤其 §7A。设计内容与实测结果分别标注，不能据此宣布月线已接入。

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

身份参考的校验分成两层：整张快照仍要求source_ts_code/latest_ts_code非空、source_ts_code唯一、数量不超过max_codes，并保留全文件哈希及上游blocking checks。只有当月实际日线及实际返回月线引用的映射，才要求source/latest代码满足现行六位数字+SH/SZ/BJ格式且confidence=confirmed；未引用的合法历史代码不因格式不同阻断本月更新。freeze_month_references在当月日线join中校验，verify_month_completion在源行情join中校验，不能遗漏无日线但源返回的额外对象。失败分别沿用monthly_identity_unresolved和monthly_identity_or_source_cutoff_invalid，不新增原因码或配置。身份表不删除、不去T、不增加归并关系，Raw业务代码不改写，Raw入口代码格式不变；周线不增加T代码补录，未来周/月线Silver规则未决定。

本调整保持最多31个日线文件、320000参考行、10000身份/期望代码的预算；向量化join只增加实际引用映射的格式谓词，不增加源请求、逐股查询或全历史扫描。验收必须覆盖未引用历史T代码仍保留、实际引用的坏格式/未确认/缺失映射拒绝、全表空值/重复/超预算拒绝、额外源对象映射失败及上游阻断/参考文件变化仍拒绝。

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

没有新的Prod/Tushare请求、正式Lake写入、正式instance事件或分区注册，也没有启用sensor、安装依赖或推送。M9正式周线源更新验收仍单列待恢复。M10.D验收时尚未提交，现已提交733fbd61；M10.E正式命令入口、刷新库存及执行准备见§15–16，写入前仍需要独立执行批准；M10.F才做源实际更新与调度启用。详见[验收报告](../../../reports/stock_month_m10d_assessment_20261005.md)与其JSON证据。

## 15. M10.E 文件执行入口与开工约束（2026-10-05）

M10.D已提交733fbd61。M10.E沿原§7A直写补录路线推进，文件与事件仍分阶段执行。本切片补齐`bootstrap/stock_monthly_history_plan.py`、`stock_monthly_history.py`、`stock_monthly_history_cli.py`，复用C捕获/提升及D交付证明，不改变源字段、日期、asset/check/job/sensor、周线或Prod合同。CodeGraph explore/impact确认planner仅被月线capture/tests消费；事件instance只读预检沿现行禁自动建表入口，不改变其实现。

硬口径：库存证据必须与显式scope相符并重建纯计划；dry-run不能创建正式目录、staging目录、instance、事件或分区；apply必须显式指定已冻结preflight的文件SHA，范围/策略/两根/目标baseline一致；year为编排边界、unit为采集持久化边界、month为原子提交边界。年度audit引用在提升前持久化，退出后沿其checkpoint续跑；拒绝目标异值、篡改库存、控制文件、路径、预算或目标漂移。SIGINT/SIGTERM变为取消，不再领取unit；已完成文件和receipt保留。正式最终验收每源/年合并读取，SQL核验schema、业务键、月份摆放和全字段canonical hash，交付控制证据绑定同C年度守恒；不做402次年度业务深扫描。

| 范围/预算 | 冻结与验收方式 |
|---|---|
| 最新Prod两源711255/710444行；各排除3682；正式1414335行 | 2026-10-05只读库存与bounds JSONL；日期/code计数与C候选逐年相符 |
| 17年×2源、450units、402文件 | 串行连接；每unit≤3900实际上界、10000硬上限/64MiB；每年≤12候选/120000行 |
| 全量最多450连接、900业务SQL（COUNT+COPY） | timeout30s/unit45s，单unit或一年完成即持久化，不全历史事务；理论源unit预算≤20250s，不作实际耗时承诺 |
| DuckDB 512MiB/2线程/2GiB staging spill | 保留C预算；年度≤120000行，final audit最多34次年度集合校验；按样本记录SQL与时间 |
| 同卷、staging预留≥2GiB+129MiB | 已只读确认同卷且剩余2.93TB；正式apply再次检查，磁盘不足立即拒绝 |
| 小样本2010-01、2020-02、2026-05各两源 | 每月需单独精确date/code库存；共6文件，无对象抽样导致不完整月，不向正式分区写半市场数据 |
| 事件预计402 materializations+1206 checks、201分区键 | 本文件切片不补录；正式文件聚合审计通过后，另冻结既有事件/缺项及instance身份，sample→batch100→聚合复核 |

CLI新增显式参数仅供运营bootstrap使用：`freeze --inventory --source --first-month --last-month --output`；`dry-run --plan --lake-root --staging-root --output`（默认动作）；`apply --plan --preflight --preflight-sha256 --output`；`audit --plan --lake-root --staging-root --output`。参数是执行意图，不新增env/Settings/数据库配置。根默认唯一正式路径；无任意SQL、备用源、覆盖、事件或启用参数。冻结格式是当前纯合同规范版本，旧B规划JSON不作为执行入口；从原始库存重建，禁止兼容解析历史格式。

文件小样本、全量文件、事件小样本和全量事件分别按正式执行门禁列出具体命令与精确范围后批准；只读与隔离验证无需借用正式写权限。当前只读预检发现402目标均不存在、月分区0、两资产物化记录0。此事实不等于正式已接入，M9待验收/M10.F启用继续单列。

## 16. M10.E 执行准备结果与代码/验收对账（2026-10-05）

文件入口已实现freeze/dry-run/apply/audit。`history_plan`从只读原始JSONL重新生成计划，拒绝重复/孤立日期、非只读快照、超范围和手改units/计数；CLI默认dry-run，apply必须匹配外部preflight SHA且禁止输出覆盖输入证据。`history`串行year/unit编排，年度audit在提升前持久化并供进程退出续跑；目标baseline变化仅允许本计划已封存candidate/checkpoint证明的提交，不把删除既有目标当作未创建。final audit每年合并schema/主键/月份摆放/full-field canonical hash，校验排除台账字节hash和已提交证明，采用现行DuckDB统一连接，禁隐式扩展安装。

24个新增入口测试覆盖真实临时Parquet完整执行、同命令续跑、receipt后取消、提交后模拟退出、语义不完整库存、plan篡改、preflight scope/hash、未审批目标出现/基线消失、损坏正式文件/月份交换/排除台账/receipt、默认只读及无SHA拒绝APPLY。相邻既有月线186项回归通过，合计210个不同测试；113静态、12治理检查、Ruff默认/致命、隔离definitions和docs完整性通过。源码白名单新增3个精确bootstrap路径，不放宽断言；无src依赖矩阵或周线合同变化。

复用M10.B保存的真实Prod业务样本在私有tmp执行两源各12个文件；准入3561/3565，排除293/295，双向全字段差集0，年度集合audit各22 SQL，含首次bootstrap和audit约0.525/0.444秒。续跑未再次导出；RSS累计进程峰值约255.5/284.6MiB。运输事务为缓存fixture模拟，不冒充本轮真实Prod capture；非全市场/全量/强制spill证明。

最新只读Prod总量未变化。sample冻结2010-01/2020-02/2026-05的完整两源市场：6文件，76units，28709源行，排除7364，准入21345。预检目标均不存在，正式dynamic partitions与两资产物化均0；同卷、空间预算通过。执行清单列明cwd、DAGSTER_HOME、两根、6条完整命令与preflight SHA、读写影响、取消/续跑和拒绝方式。正式sample尚未批准/执行，后续full预检必须在sample后刷新，不能沿“目标不存在”旧baseline进入全量；事件入口将在正式文件审计通过后冻结，M10.E当前未完成。

详见[本切片报告及小样本执行清单](../../../reports/stock_month_m10e_assessment_20261005.md)、[冻结范围](../../../reports/stock_month_m10e_frozen_scopes_20261005.json)和[验收JSON](../../../reports/stock_month_m10e_validation_20261005.json)。代码尚未提交，未正式写湖、注册分区、补录事件或启用调度；M9/M10.F待办不变。


## 17. M10.E正式小样本通过（2026-10-05）

管理员明确批准先提交再执行小样本清单。文件入口/LLD/冻结证据先提交e1f56646，未推送，然后按六条已冻结命令串行apply：2010-01两源1534/1534行，2020-02为3632/3625行，2026-05为5510/5510行；合计21345行、6个正式文件、76持久化units。真实Prod source共28709行，排除20200229两源各3682行，READ ONLY REPEATABLE READ、COUNT/COPY及ROLLBACK的76份控制/快照证据均保留；无模拟源事务。2020-02正式仅20200228，2026-05保持20260531；历史end_date合法NULL共55行保真，不复制采集字段。

正式apply每份年度集合audit11 SQL，事后独立重读捕获/receipt/control与正式Parquet：全字段双向差集0、重复键0、13/21字段/类型、月份与目录摆放一致，排除台账/逐文件checkpoint hash通过。六条命令日志计时合计约54.523秒（不含编排间隔），独立读回0.667秒；未实测正式RSS峰值或强制spill。业务代码、weekly口径、src依赖矩阵和正式根未变化；阶段预算拒绝未触发。

正式instance仅只读复核，cn_a_stock_months键仍0，两源样本物化均0；尚未补录事件或启用调度，文件合格不冒充Dagster ready。已存新的post-sample全量preflight，每源3既有/198待创建目标；旧全空baseline只保留作历史记录。M10.E尚欠全量文件及独立事件阶段，M9/M10.F不提前完成。

[正式小样本报告](../../../reports/stock_month_m10e_formal_sample_20261005.md)和[详细证据JSON](../../../reports/stock_month_m10e_formal_sample_20261005.json)保存实际行数、路径、字节hash、单位快照和下一步预检引用。执行结果/本节尚未提交，原执行代码已提交e1f56646。


## 18. M10.E正式全量文件阶段通过（2026-10-05）

管理员本轮明确批准提交样本结果再推进全量bootstrap。已先提交样本/更新预检a49609db（未推送），核验当前目标与两份post-sample预检完全一致后，按原冻结2010-01至2026-09两源计划串行apply。225units/201文件每源，共450units、402文件；未复权707573、复权706762正式行，共1414335。源1421699行减7364条明确排除20200229守恒；新提交396文件、同值复用6样本，样本字节hash保留，未发生异值覆盖或预算拒绝。

450份真实Prod READ ONLY REPEATABLE READ控制/快照、capture和receipt完整持久化；COUNT/COPY业务SQL900次，连接串行，不用全历史事务。34个年度集合文件audit共742SQL，独立逐年度全字段EXCEPT ALL及排除台账差集均0，源日期计数/正式分区集合一致，schema/键/摆放和交付证明通过。2020-02仅20200228，其他月份维持自然月末；历史end_date NULL3960/3149行源值保真，不复制采集字段。

日志计时两命令195.964/228.689秒，总计约7.08分钟（不含编排）；正式Parquet61569878字节、独立读回8.980秒。沿512MiB/2线程/2GiB spill及同卷/逐文件checkpoint预算；未测正式RSS/峰值spill，来源是逐unit快照，不误称全局一致事务。未改业务代码、weekly口径、src依赖矩阵或正式根，未安装依赖。

后置正式instance只读核验：月分区0、两源月线物化0；未补录事件、触发job或启用调度。文件阶段通过不替代事件就绪或日线期望缺口审计；下一步按原设计单独冻结事件清单、sample/batch补录及最终审计。M10.E仍未整体完成，M9/M10.F继续单列。

[全量报告](../../../reports/stock_month_m10e_formal_full_20261005.md)、[详细证据](../../../reports/stock_month_m10e_formal_full_20261005.json)及[完整命令](../../../reports/stock_month_m10e_full_commands_20261005.txt)已落档。全量结果及本节已提交3892ad31，小样本证据已提交a49609db；未推送。

## 19. M10.E事件补录实施约束（2026-10-05）

全量文件结果已提交3892ad31。管理员明确要求“提交吧，然后进行事件补录”，授权本阶段先dry-run、六个资产分区样本再分批补齐，不含M10.F启用。目标为两套Raw、2010-01至2026-09共402资产分区/201动态月键，最多402物化+1206检查=1608事件。无Prod/Tushare请求、Raw修改、job或sensor执行。事件误写不得删除回滚；停止后保留已有事件，经核查后追加更正。

新增stock_monthly_events（年度集合证明→冻结→有界事件读取→幂等写入）与stock_monthly_events_cli；复用audit_monthly_history、月线delivery控制证明、标准metadata builder及既有无自动建表instance opener，不更改周线合同。CodeGraph explore/impact覆盖history、delivery、weekly event writer及checks；当前代码核对月线readiness、check名称/分区和metadata消费者。CLI只供运营，未接入Definitions；src依赖矩阵不变。

配置审计：MonthlyEventPolicy为版本化不可变代码策略，不来自env/DB/页面，不增加外部开关。event_write_cap=2048（拒绝超过512资产分区）；event_record_read_cap=8192（包含check索引和正文）；event_partition_batch=12（年度组）；event_write_batch=100（实际事件数，至多25完整资产分区）；plan_max_bytes=8MiB。消费者仅事件helper/CLI/tests，策略进入plan_hash，代码reload后拒绝旧策略。沿用512MiB/2线程年度DuckDB审计。首次和最终各34年度集合扫描/742SQL；event主审计每source/year最多1物化页、1检查索引、1正文页，干净历史预计102调用；历史过多时按8192返回预算失败关闭。写入只做精确目标ID读回和批末集合核验，不逐check扫历史。

冻结计划绑定两份严格history计划、根/instance身份、402文件字节/逻辑hash、年度audit hash、既有latest mat/check ID及缺项。发现已有异值物化或非匹配checks时拒绝覆盖，需另行审阅。APPLY只允许冻结scope，动态注册按最多100键/批；每个资产分区最多4事件，检查显式month、blocking/error/pass及target storage_id/run_id/timestamp。原ID改变只接受同plan且同证明的自有事件；checkpoint仅进度，不替代实际event事实。进程退出或checkpoint失败后按eventlog恢复，取消前后检查，不领取新unit。文件/年度控制证明在每批写前复核，物化后精确读回，批末查全部绑定。

测试门禁：隔离instance下两源真实临时Parquet→年度审计→事件→绑定读回，覆盖取消/退出/重放、plan/文件/receipt篡改、错误或外部事件、目标物化改变、批次/读取上限、默认只读和无apply拒绝。三check校验分别映射年度schema/键日期分区/canonical+封存交付证明。正式先六个资产分区（2010-01/2020-02/2026-05两源，24事件）再剩余396（1584事件），最终年度物理集合+latest物化/check集合及最早/2020-02/2026-05/最后月份样本readiness核验。历史NULL保留、20200229排除、sensor仍停止；未验证的M9/M10.F继续单列。


## 20. M10.E正式事件补录通过（2026-10-05）

管理员本轮明确要求提交后进行事件补录，先提交全量文件证据3892ad31（未推送），再完成本阶段入口、隔离验证及正式dry-run→样本→分批执行→聚合读回。2010-01至2026-09两源402个资产分区/201动态月键，先注册三个样本月、写入6物化+18检查，六个样本实际文件及target绑定均通过；随后注册剩余198键，17批补录1584事件，跳过24个已有样本事件。共402物化、1206blocking/error/passed检查，全部对应准确storage_id/run_id/timestamp及相同month。没有重复事件、外部漂移、已有失败覆盖或预算拒绝。

首次dry-run与最终审计各34年度集合/742SQL，耗时4.838/4.255秒；402文件字节/逻辑hash与冻结证据完全一致，1414335行及7364条排除守恒。独立事件集合查询实测34物化页+34检查索引+34正文页=102调用，返回2814记录（402物化+1206索引+1206正文），不是2814个新增事件。两源各201物化、每种check各201，缺项/阻塞/历史latest failed均0，动态分区集合差0。最终8个文件和绑定样本ready，现行monthly_period_status消费者同8样本全部ready。

全量注册、17批事件及最终audit的21条CLI计时合计100.106秒（不含前置样本、间隔及独立消费者复核），每批实际事件最多100；未测正式RSS/spill。SIGINT/SIGTERM逐unit取消，单次事件提交后checkpoint立即持久化；实际隔离子进程在第5事件后os._exit，再启动补余11并再次重放0写入通过。正式执行未发生取消，不将隔离恢复验证冒充正式取消演练。

代码/测试对账：audit_monthly_event_files复用history年度集合全语义；verify_monthly_event_file校验正式字节、logical hash、年度audit与receipt/promoted控制；冻结计划含来源严格history计划SHA、instance身份及策略；CLI默认只读，写入必须显式apply+外部plan文件SHA，输出限制reports/private tmp。read_monthly_event_state按source/year集合读取；apply_monthly_events逐分区最多4事件，精确目标读回、批末latest绑定复核，自有同plan事件才允许续跑，遇外部/失败事件拒绝。独占staging event锁防止并发同入口写入；不迁移周线API。新增配置仅MonthlyEventPolicy版本化代码预算，审计在§19，不增env/DB配置。

27个事件测试+24个history测试共51项通过；额外现行readiness消费者测试通过；受保护静态113、治理12、Ruff默认及全域致命错误、离线definitions、文档完整性、CodeGraph sync/status通过。旧SQLite索引不允许同runless检查名/月键重复插入，沿“先读真实事件→幂等跳过”处理，失败项只拒绝，不绕过或删事件。没有新Src跨子系统依赖、Prod/Tushare请求、Raw写入、job/sensor执行、安装依赖或推送；月线sensor无持久化运行状态，definition仍STOPPED。

M10.E文件及事件验收完成。本轮事件代码、报告与文档已提交ee325688；M10.F源实际更新及19:30调度启用仍需下一阶段，M9正式周线更新验收继续单列。详细证据见[执行与验收报告](../../../reports/stock_month_m10e_events_execution_20261005.md)、[最终集合审计](../../../reports/stock_month_m10e_events_final_audit_20261005.json)与[现行消费者复核](../../../reports/stock_month_m10e_events_consumer_audit_20261005.json)。


## 历史记录：M10.F审计暂停（2026-10-05）

M10.E事件入口/验收已提交ee325688、未推送。本轮M10.F只读核验发现：月线freeze_month_references对全量身份表加六位数字代码正则，误拒历史生命周期自映射T600018.SH（2000-07-19至2006-10-20）。正式身份表6163行、无重复、上游checks通过；9月21日线文件/116588行/5571代码中该历史代码0行，本月实际映射缺失/未confirmed/格式错误0。故此是月线消费者与身份既有契约的冲突，不是本月日线或源配额问题；全局校验会阻断新的更新意图。

管理员明确选择“先保留现状，只完成审计”。本轮没有修订规范或修改代码/数据、运行两源更新job、写事件/cursor或启用sensor。只读MCP单股三类字段请求各API3次通过，不替代全市场更新验收；两源历史9月仍ready，正式UI月线sensor STOPPED。M10.F未完成，建议的按本月实际引用身份校验尚未批准；M9独立待办不变。根因、影响面和后续建议详见[M10.F审计报告](../../../reports/stock_month_m10f_audit_20261005.md)。本轮审计文档/证据尚未提交。

## M10.F身份误阻断修复（2026-10-05）

管理员在核对Prod/DG基础信息及周期行情后明确批准“按照你的建议做，主要把之前阻断项解决掉”。本次仅修订§4身份校验范围，不专项处理T前缀行情、不补周线、不删除或归并历史身份、不改变Raw代码合同；退市历史保留口径只限Raw周/月线，未来Silver规则未决定。此前“保留现状、只审计”的决定保留为历史记录，本段为最新批准口径。

freeze_month_references的全表检查保留非空/唯一/预算/整文件hash及上游blocking checks；格式/confirmed要求转到实际日线join。verify_month_completion同时检查实际源返回对象的映射格式，防止无日线的额外源对象绕过门禁。没有新增配置、原因码或源请求，没有改weekly/Prod/Definitions或依赖矩阵。CodeGraph impact追到月线point共用入口与定义测试。

月线更新66项、定义/sensor22项、受保护静态113项通过，修改文件完整Ruff及全src/tests致命基线通过。正式2026-09只读复核21日线文件/116588行/5571期望代码、6163身份键，历史T600018.SH仍映射自身且不在期望集合；原monthly_identity_invalid_or_over_budget不再出现。复用2026-10-04已捕获的两源全市场响应各5571行，与真实9月参考完成校验均ready，耗时0.522秒。完整身份/参考文件hash及上游绑定复核一致，两份Raw目标字节hash不变。

此为修复及真实只读门禁验收，不是新的正式job或实时源更新验收。管理员随后确认已加载修复代码并要求提交修改；本轮助手不重复reload，也不触发job、写正式event/cursor或启用19:30调度。M10.F真实更新及启用、M9原正式验收继续单列。本段及相关代码/测试/证据随修复提交，未推送。详见[修复对账报告](../../../reports/stock_month_m10f_identity_fix_20261005.md)及[真实只读证据](../../../reports/stock_month_m10f_identity_fix_preflight_20261005.json)。

## 共享源异常诊断修订（2026-10-06）

管理员确认周线M9先补齐异常分类，共享监督入口同步覆盖月线point。监督IPC仅传固定安全分类，异常note为source_diagnostic=<白名单分类>；月线转换错误和同次执行重试预算耗尽时复制最后一次已验证分类，不复制原文/任意note或猜测权限/限流。页间不继承旧分类，重启遇旧预算耗尽时不新增请求、不伪造诊断。原monthly reason、源参数/字段、账本、预算、取消、Raw和Definitions不变。

月线与周线/source等168项定向/相邻测试、113项受保护静态门禁通过，包含两个月线源的错误转换、分类保留及重启不加请求；未触发正式月线更新或启用sensor。完整设计以[周线LLD共享修订](dagster-stock-weekly-alternate-source-raw-backfill-low-level-design-v1.md)为准，实测对账见[分类验收](../../../reports/stock_week_m9_diagnostic_assessment_20261006.md)。该开发结果不完成M10.F新增月份真实验收。
