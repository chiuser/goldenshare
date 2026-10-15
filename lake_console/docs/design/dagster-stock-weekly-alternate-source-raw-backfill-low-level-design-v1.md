# DG 周/月Raw直接源下载与更新共享 LLD v1

更新：2026-10-16。已确认先删除两旧Raw根再直接源bootstrap，待开发与正式验收。当前周线仍由Prod闭合批供数，月线仅交付已完成月；不能把本LLD当成已部署。范围和顺序以[总方案](dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md)为准，月线差异见[月线LLD](dagster-stock-monthly-raw-onboarding-low-level-design-v1.md)。本轮主线包含Raw和随后Silver；本文聚焦Raw共享执行合同。本轮不改代码、配置或正式数据。

<a id="adjusted-weekly-prod-refresh-lld"></a>
<a id="1-保留链的当前合同"></a>
<a id="source-field-contract"></a>
## 1. 源字段、请求和真实时间语义

源为stk_week_month_adj；不恢复独立未复权或备用weekly。原业务键(ts_code,trade_date,freq)、两个asset key及周/月路径保持，总方案列出完整路径。Raw仅保存源业务字段，不加入Prod搬运信息、规范证券身份、is_final或每日快照日期。

| 源列 | 当前DG类型 | 保留语义 |
| --- | --- | --- |
| ts_code | VARCHAR | 原始返回代码，不将旧码重命名为新码 |
| trade_date, end_date | VARCHAR | YYYYMMDD；周期坐标与源计算截至日期分别保存 |
| freq | VARCHAR | week或month，与数据集匹配 |
| open, high, low, close | DECIMAL(18,4) | 未复权OHLC |
| open_qfq, high_qfq, low_qfq, close_qfq | DECIMAL(18,4) | 源前复权OHLC |
| open_hfq, high_hfq, low_hfq, close_hfq | DECIMAL(18,4) | 源后复权OHLC |
| pre_close, change | DECIMAL(18,4) | 源除权参考前收、涨跌额，不自行从其他字段推算 |
| vol, amount | DECIMAL(20,4) | 原源单位 |
| pct_chg | DECIMAL(10,4) | 原源单位；样本0.77表示0.77%，不乘100 |

共21列，顺序沿doc365。当前小数4位是存储基线，不能当源最大精度；真实回包超出精度/范围或新增列时，保留原回包并显式解决合同，禁止静默舍入、截断或丢列。NULL按源保留。字段完整不等于全市场历史已核验。

2026-10-16凌晨MCP实测（000001.SZ）：

| 请求/返回 | 结果 |
| --- | --- |
| ts_code+freq=week，不传时间 | 1,782行，19910405至20261016，默认21列 |
| trade_date=20261012或20261015，freq=week | 0行，不能用工作日当周K查询坐标 |
| trade_date=20261016，freq=week | 1行，end_date=20261015；周五尚未开盘已有周中K |
| start_date=20261009/end_date=20261016 | 两个周坐标；改为20261012—20261015则0行 |
| ts_code+freq=month，不传时间 | 427行，19910430至20261031，包含未结束月 |
| 历史周19910405、20261009 | end_date均为20261015，不能当各周最后交易日 |

默认字段与成功的显式21字段请求一致。补充请求有4次超时/502，均不是空源，未反复重试。原始小范围证据位于/private/tmp/dg_period_source_semantics_complete_20261016.json；日常不依赖此临时文件。跨日连续更新尚无连续实测，必须由后续代表性日常验收覆盖。

单股全历史的业务参数仅含ts_code、freq，另显式指定全部fields；不传trade_date/start_date/end_date。分页属于传输参数，不改变单股完整历史范围。当前在线输入表未列limit/offset，MCP也未开放，但Prod已有针对同一接口的实现，DG按该实现方式设计，不重新发明分页框架；代码依据与本轮源实测状态分开记录。

### 1.1 分页规则与Prod依据

1. 每页显式传limit=6000，offset从0开始。返回正好6000行则offset增加6000，继续同一股票、freq及fields的下一页；返回少于6000行即结束，含合法的空末页。
2. 恰好6000或其整数倍行数时，必须再取一个空末页。满页本身不是失败，也不能因此截断或宣称完整；仅在达到本专项页数/行数/空间预算仍未见末页、请求失败或分页证据异常时，单元保持未完成。
3. 页完成后保存请求参数、页号/offset、行数及源片段，恢复接未完成页；只有页链连续且观察到短页，整个股票×freq单元才完成。拒绝缺页、相邻页重复导致的业务键重复/冲突，以及把超时或无字段响应当空末页；不新增整库复查。
4. 周线依据[DatasetSourceClient.iter_weekly_adj_pages](../../../src/foundation/ingestion/source_client.py)：追加limit/offset，页前后检查取消，短页返回，达到预算未见末页则拒绝完成。月线通过同文件iter_pages/_iter_request_pages/_fetch_page执行同样的满页续取、短页结束；两套DatasetDefinition的page_limit均为6000，见[market_equity.py](../../../src/foundation/datasets/definitions/market_equity.py)。
5. [test_stock_weekly_adj_p2.py](../../../tests/test_stock_weekly_adj_p2.py)已有替身测试，覆盖整页后空末页及页预算耗尽拒绝。这是实现与测试依据，不冒充本轮真实分页通过。DG参考其分页和响应处理语义，不直接搬入Prod TaskRun依赖，也不机械套用Prod周线3页/12000行预算。

Prod使用[自有HTTP客户端](../../../src/foundation/clients/tushare_client.py)，区别于上轮直接调用的SDK。SDK超时仅是当次路径失败，不能据此判断Prod路径不可用。分页设计已明确；首次代表性源验收合并确认相邻页、末页、连通性与耗时，成功结果复用，不再单独重复做一轮分页调研。

## 2. 对象、新代码和持久化单位

首次固定当前确认仍上市集合、证券身份与北交所映射版本，复用现行silver/basic/stock_basic及confirmed身份事实；集合只准备一次，不能把stock_basic包含L/D/P/G全量代码直接当请求对象。退市股票在规划和出站请求两处均排除，bootstrap、日常、因子、手动及重试一致。对象池为空或身份未明不能退化为全市场请求或清空数据。请求代码按映射n_code归并；已经确认使用新码的新上市股票不要求伪造旧码映射。未确认的新旧关系阻止该对象出站。对北交所旧码的拒绝在请求builder前统一执行，bootstrap、日常、手动、重试和因子刷新共用，不让调用方自行拼码。

正式Raw仅保留准入范围内的完整源行情；“全源保留”不覆盖退市对象。全市场回包用同一对象集合过滤，源总行数=准入行数+范围排除行数+异常行数，退市过滤数量与技术reject分别记录。首次旧存量随两个旧Raw根一并删除，不读旧文件逐行剔除或合并。仅代码换名、停牌或身份未知不证明退市，不据此误删仍上市证券历史。

下载unit=(本次范围身份,有效ts_code,freq)，稳定标识不依赖run_id。单unit完整返回后保存请求参数、字段、源片段及receipt；技术失败、真实空源、预算耗尽仍未到末页、身份不符分别记录。真实空源须解释，不生成空文件、不从旧数据兜底；删除后的基线保持未完成，不能把缺失股票当成功跳过。日常更新源空则保留已验收的新基线并记录欠账。

捕获文件只在run-scoped staging；每个成功unit可读回并独立续用。候选unit=(asset,周期分区)，汇集相关源片段后一次COPY；不按每股逐次重写全历史。控制记录保存删除阶段、完成源片段和提交事实；两根删除完成后才进入正式下载。进入正式下载后阶段不可退回清空根目录，不新建数据库表、永久版本库或第二套任务状态机。

开始/完成源交易日及真实返回end_date分别留证，不能假定上万次请求是同一时刻快照。跨日、跨周/月时，在转日常前仅追平运行期间涉及周期的最后已发布值和实际因子变更对象；成功历史片段继续复用，补取也进入同一候选合并流程。已关闭周期不能因下载较早而残留周中/月中值；未来正常日常按消费坐标接续。

## 3. 候选、提交与取消恢复

所有批处理用DuckDB列式读取、SQL及COPY，不用Python逐行写Parquet或常驻全部历史。删除/下载/组装/提升/事件各阶段报告真实当前对象、完成量、总量与最后更新时间；无可靠ETA时明确不可估算，可见更新间隔沿性能治理要求不超过30秒。阻塞请求由现有可取消监督器控制。

候选合并验证：21列/精度/NULL，代码及freq，trade_date对应分区，源页完整和源行守恒，同业务键无异值冲突。相同键不同值不能随意取最后一行；源记录及错误证据保留。Raw不做按规范证券代码合并，不把历史正常停牌当每日数据缺口，不扫描日线重算周/月价格。

### 3.1 删除边界与数据空档

删除白名单仅为/Volumes/datasource/data_lake/raw/tushare/stk_period_bar_adj_week和/Volumes/datasource/data_lake/raw/tushare/stk_period_bar_adj_month两个完整旧根。执行前一次确认挂载、规范路径、无符号链接越界及无冲突写者，只列目录元数据；不读待删Parquet、不做价格/行数检查、不计算旧文件hash，不备份或快照。共享父目录、其他Raw、Silver、staging、动态分区和Dagster历史记录均不删。删除不是空对象池或请求失败的自动处理；必须先完成程序验收及非空对象范围确认，并按正式执行清单进入该阶段。

删除阶段完成记录先持久化，再进入正式下载。删除途中取消且尚未进入正式下载，可以核边界后继续剩余删除；进入下载后恢复只接本次未完成unit，禁止再次执行根目录清空。阶段或文件归属不清则停止，不把新输出误当旧存量。删除后到新基线验收前，旧事件不证明数据就绪；Raw可能缺失或部分完成，Silver生成与消费须受此状态约束，不提供旧行情回退。

### 3.2 新基线提交及恢复

首次候选仅来自本次成功捕获的完整源unit，不能读取旧DG价格、合并旧键或从旧Prod补洞。新下载没有的记录不保留旧版本；缺源或未完成对象显式留在未完成清单，整套基线不能因此写绿。不同源周期日期保留原值；不为对齐旧库存改写或去重。

首次分区目标应不存在；恢复仅允许读回确认属于本次已提交的新文件。候选校验及同文件系统边界通过后，在目标锁内os.replace并fsync，提交一个记录一个；第三方文件或目标漂移阻止该单元提交，不擅自覆盖。源片段与候选身份只在建立/消费/提交这些必要边界检查，不每秒重算hash；正式checks只核本次文件事实和准确物化绑定，不长期依赖bootstrap材料。

初次重建与日常更新分开：通过验收后的新基线，日常才按原始源键完整行upsert；后续确认退市按受影响分区清理Raw与Silver，不从旧bootstrap存量导入任何行。

每次源请求、文件组装和提交前后检查取消，取消后不领新unit；协调器退出清理本任务worker，旧写者退出前不允许新写者接管。已完成源unit、候选和提升记录保留。恢复先核请求/输入身份，再读回完成单元；未变化的不下载、不重算；目标为第三方版本则停止冲突单元。

replace后checkpoint失败，读回确认目标就是已校验候选后补记完成；事件失败只补准确事件，不再覆盖文件。事件不把未校验文件写绿，不回滚已提交业务文件。不运行Kopia或文件备份。

## 4. 当前周期与因子变更

日常按交易日执行，week请求本周自然周五，month请求自然月末，全市场周期请求统一处理。源尚未发布时保留当天欠账，不把旧结果当当天完成；不要求每只停牌股票的end_date都等于当天。源发布时间用最小真实样本核定，现有19:30窗口不是“必定已发布”的证明，不新增无界轮询。

当前周期每日upsert同一业务键，允许trade_date晚于运行日。元数据/cursor分别表达最后成功刷新交易日、已结束周期、未完成任务；is_final不进入Raw。节假日不改trade_date为最后开市日。已结束周/month不因end_date变化自动全量刷新。

日常因子触发只复用现有相邻交易日差异：stock_daily_qfq.py的build_stock_daily_qfq_factor_changed_codes_sql读取当日、上一交易日两份silver_adj_factor，输出变化代码。本次沿用该识别范围，记录自上次成功消费以来的对象及日期；同股week/month两unit，均用无时间请求重新下载。成功保存两频后才标完成，取消后只接未完成项。bootstrap及主动历史下载不依赖因子差异、因子blocking checks或日线qfq修复job成功，不做本地复权价格重算；不新增历史因子修订探测任务。回包即使end_date相同也不能跳过明确要求的历史下载。

当前全市场回包与单股历史片段合并后，一个受影响分区只组装/提交一次。若两类片段对同键出现不同版本，不能任意按下载先后覆盖，应重取冲突对象的小范围或报告源变动，不重新下载整个市场。

## 5. 唯一写者切换与影响面

当前实现：weekly sensor→stock_weekly_adj_feed→Prod闭合批→stock_weekly_adj_run；monthly asset→deliver_month_intent，异值报revision_required，sensor只从下一已完成月推进。现有bootstrap均主要从Prod导出。三者不等于本设计，不能直接用旧CLI执行新bootstrap。上述仅是DG入口切换的现状，不要求改动Prod本身。

拟以周/月共用的源捕获、候选和提交能力承接bootstrap/每日/因子三种意图；request builder负责所有出站参数。切换同一批次迁移assets/jobs/checks、sensor、run_contracts/configs/schema、catalog/readiness、相关历史CLI与测试，不保留双写、旧码兜底或旧Prod入口继续覆盖目标。共享能力先核消费者再移除，Prod内部的闭合批交付表不因DG切换被删除。

正式删除前必须先完成唯一写者切换与旧入口封闭；重建期间所有日常、手动、重试写入口遵守同一重建阶段和写锁，不得趁目标不存在自行创建。两套新基线验收前不交接日常。正式切换保留两个共享sensor名称、RUNNING/STOPPED意图及原cursor证据；根据已验收的新文件和实际源刷新坐标迁移，不把旧revision=1785强行解释为源日期。遇正在运行的旧写者先等待，不启停其他服务。新鲜度/阻断检查改为当前周期及源交付事实，去掉对“必须已结束周/月”和整月日线扫描的依赖，须同步迁移全部直接消费者而非只删检查。

CodeGraph explore及当前源码已覆盖weekly_column_specs/monthly_column_specs→schema/assets/导出消费者，以及evaluate_adjusted_feed→weekly sensor、deliver_month_intent→monthly asset；已补查config、CLI/check、catalog及其直接消费者，实施映射如下；分页实现依据已明确，源连通性、吞吐及数值预算尚待最小验收，不据此宣布开发门禁全部通过。未发现本次需要修改Foundation→Ops/Biz等依赖方向，Prod/API/Wealth/QTF不因本文发生变更。


### 5.1 Raw实施文件与消费者清单

下表路径相对orchestrator/src/orchestrator/defs；共用实现限定周/月，测试位于orchestrator/tests。不修改Prod供数实现或R3。本表列职责和退出边界，正式编码尚未开始。

| 改动文件 | 要完成的迁移 | 直接消费者/验收 |
| --- | --- | --- |
| run_contracts/stock_weekly.py、stock_monthly.py、configs.py、asset_column_schemas.py | 共用源请求/意图合同；保留21列及现有asset身份；月线不再固定丢20200229；旧Prod批参数退出DG写入口 | assets、schema、catalog、CLI、builder及contract测试同时迁移；保留仍被引用的通用类型 |
| assets/stock_weekly.py、assets/stock_monthly.py；jobs/stock_weekly.py、jobs/stock_monthly.py | 两个原asset/job改由直接源执行，日常与主动历史意图清晰分开 | definitions、job selection与两个asset测试；job/key名称保留 |
| sensors/raw_stock_weekly_update_job_sensor.py、raw_stock_monthly_update_job_sensor.py；stock_weekly_update.py、stock_monthly_update.py；stock_weekly_update_state.py、stock_monthly_update_state.py | 交易日刷新当前周期；共同重建准入；相邻因子变化只取变化股；明确新cursor版本及旧水位迁移，不清空重跑 | 两个sensor、update/state正反测试；历史下载不依赖因子判定 |
| stock_weekly_adj_feed.py、stock_weekly_adj_run.py、run_contracts/stock_weekly_adj_delivery.py | 退出DG的Prod闭合批读取、revision推进及写入口；禁止旧参数/旧计划重建目标 | 当前引用来自weekly sensor、weekly asset、configs及weekly delivery测试；不删Prod自身交付表 |
| stock_monthly_point.py；source_readiness/stock_weekly.py、source_readiness/stock_monthly.py；io/stock_weekly_raw.py、io/stock_monthly_raw.py | 月线退出create_or_identical限制与整月日线参考扫描；字段、日期、范围校验移到新源合同 | assets、checks、日常执行和候选组装；不把旧参考扫描照搬到新链 |
| checks/stock_weekly_checks.py、checks/stock_monthly_checks.py、stock_weekly_file_checks.py | 保留现有check身份，改核本次文件/范围/绑定；同文件共享一次列式校验结果，多个check不各自重复执行完整扫描 | job选择、readiness、历史事件CLI和check测试一起迁移；结果只绑定同一文件版本 |
| catalog/lake_assets.py、catalog/name_mapping.py | 来源统一为Tushare，移除Prod bootstrap、已完成周期和旧参考成本说明；名称、schema、路径一致 | catalog、metadata、definitions及schema测试；paths.py和partitions.py的既有身份/布局保留 |
| bootstrap/stock_weekly_history_cli.py、stock_monthly_history_cli.py及直接调用的planner/capture/candidates/promote/history模块 | 两个旧Prod bootstrap写入口退出；新bootstrap只接上市/新码范围，先删后建且下载后禁止清根 | 相关history/planner/capture/candidates/promote/CLI测试；不保留旧计划写入兼容 |
| bootstrap/stock_weekly_events_cli.py、stock_weekly_events.py、stock_weekly_event_files.py、stock_weekly_event_instance.py；bootstrap/stock_monthly_events_cli.py、stock_monthly_events.py；ops/stock_weekly_bootstrap_checks.py | 新源文件对应的物化/check绑定；事件失败仅补事件，退出旧B0搬运材料依赖 | 历史事件、check绑定、取消续跑测试；旧历史记录保留 |
| 新的周/月共用请求、下载、候选及bootstrap实现（具体文件随数值预算定稿） | 统一参数builder、已上市/新码准入、唯一写锁、删除阶段记录、逐文件checkpoint；不增加长期状态表或全局配置 | 新正反测试覆盖先删后建、旧入口拒绝、取消恢复、源守恒；既有stock_weekly_source.py仅在实际语义可复用时使用 |

新共享模块具体命名、CLI参数和配置默认值须随源验证与预算一起定稿，再进入编码；本表不授权一边编码一边选择这些合同。仅为Silver阶段保留后续接口，不提前实现Silver或迁移其他数据集。

## 6. 配置、容量和测量

**2026-10-16准备状态：分页实现方式已明确；源连通性、吞吐和数值预算待最小验收，尚未正式编码。** 当前上市对象数一次读取得N=5576，最新上市代表301569.SZ，北交所样本920000.BJ。MCP对920000.BJ完整周线请求超时（>30秒）；MCP无limit/offset输入，因此分页另用项目现有SDK验证，000001.SZ/week/limit=3/offset=0首次请求20.0075秒ReadTimeout后即停止，没有后续页或重试。SDK仅使用现有环境中的TUSHARE_TOKEN，不记录token。证据在/private/tmp/dg_period_sdk_preflight_20261016/result.json；该证据证明本次访问失败，不证明空源、无权限、分页不支持或固定吞吐；Prod已有实现见§1.1，其自有HTTP路径未被这次SDK请求验证，不能据此修改超时/并发来宣称性能通过。

| 测量项 | 已确认/成本模型 | 仍缺与处理 |
| --- | --- | --- |
| 对象、请求、页 | N=5576；bootstrap共2N=11152个单股频率unit；按Prod规则6000行/页，满页继续、短页结束；已成功样本week1782、month427行 | 分页方式已确定；当前历史与日常请求的首次真实验收合并验证页链和吞吐，不冒充本轮已通过 |
| 行数与请求模型 | 单元实际行数r时，请求数为floor(r/6000)+1，含必要空末页；总请求数为各单元求和。只有全部单元不足6000行时才是2N次，且总行数小于66,912,000 | 6000是单页上限，不是整股或整任务行数上限；实际总量、预算、精度和文件量按代表样本确定，准入/排除/异常分别计数 |
| 扫描/组装 | 成功单股源片段只在汇集阶段批量导入一次，再用DuckDB分区COPY按freq/周期输出；禁止“每个周/月再读取全部单股历史文件” | 临时分区COPY输出规范文件名，逐文件校验/提交；样本记录SQL数、扫描字节、输出文件和峰值内存，验证不是隐藏的周期×全历史循环 |
| 写入与恢复 | 源unit持久化一次；分区候选一次组装、一次必要校验、一次原子提升及读回；复用成功事实，不因事件失败重算 | 校验结果只复用同一文件版本，漂移失效；取消/退出测试在临时目录执行 |
| 时间、空间、配额 | 请求数公式已知；源片段+候选+spill+新正式文件共存；预算增量计量，不扫描累积目录 | 无成功新源样本，无法给实测吞吐、峰值或可靠ETA；现有1并发/512MiB等旧配置不自动沿用，暂不指定新数值 |

后续只做剩余最小验证：按既有Prod分页方式，在老上市、新码北交所、新上市代表的两频历史样本中合并观察页链、末页及耗时，再做同批次列式组装/读回；不单独重跑一套分页调研。成功结果可复用。一次补齐数值预算和配置审计后才编码；不重新跑日期/字段全套审计，不全量请求、不测正式删除或正式写湖。

| 项目 | 来源/消费者与处理 |
| --- | --- |
| api、fields、freq、有效代码 | run_contracts与统一builder，固定进意图/receipt；不在脚本、sensor各写一份 |
| 源单页6000 | doc365及Prod实现；统一builder传limit/offset，满页续取、短页结束；分页预算在本专项执行policy中确定 |
| 历史范围 | 由单股无时间请求返回决定；不套旧859/201分区数、2010起点或Prod年度导出范围 |
| 请求期限/重试/间隔/并发 | 实施前审计现有请求policy、token额度和全部消费者；用代表样本确定本专项值并持久化，不擅改全局 |
| 计算内存/threads/spill/批次 | 局部DuckDB连接与执行policy统一消费；先测源片段和单分区峰值，不把buffer上限冒充进程树RSS |
| 空间 | 开工估算源片段+候选+spill+新正式文件共存峰值并检查一次，不含旧数据备份；实际新文件增量结算，必要写前查剩余空间，不反复递归扫描 |
| 进度/取消 | 共用执行器与监督器，保存真实阶段和完成单元；观测不影响已提交数据 |

原WeeklyBudget、StockMonthlyPolicy、MonthlyBootstrapIOPolicy和completed-period policy是旧链基线，不能把Prod导出、日线参考或“只创建/同值”限制无审计搬到新链。新增/变更配置必须列默认值、代码/env/文件等来源、持久化、消费者、相互依赖、生效方式和运维可见性；数值未实测前不得进入正式执行。

前次对象快照N=5576时基准2N=11152请求，重试/补页另记；每交易日基准当前周/月各一次，另加2C个变更股票历史请求及必要分页，C按有效代码去重。源片段可能覆盖更多早年周期，输出文件/空间按样本和实际回包估算，不从旧库存推完整性。串行2—5秒/请求对应6.2—15.5小时仅是假设，不能宣称已比局部修复实测更快；小样本校准后固定版本执行，避免每个小修从头跑全量。

<a id="acceptance"></a>
## 7. 正反验收

| 检查 | 正向 | 反向 |
| --- | --- | --- |
| 请求与北交所 | 单股业务请求为新码+freq并显式fields，技术分页参数limit/offset不裁业务时间；周/月历史都取回 | 旧码、未确认映射、失败后旧码兜底、偷偷加时间截断拒绝 |
| 字段 | 默认/显式21列完整保留，NULL/Decimal守恒 | 丢列、超精度静默舍入、价格重算、擅改代码或日期拒绝 |
| 时间 | 周中可请求未来周五、月中可请求未来月末，历史end_date晚于周期合法 | 按星期一查询当周、用请求end_date当版本、把周中刷新当整周完成不能通过 |
| 跨日交接 | bootstrap跨周/月仅补运行期间涉及周期及因子对象，历史片段复用 | 把早期捕获的未完成周期当最终值，或为追平重下全部历史拒绝 |
| 月版本 | 20200228和20200229两条源行原样保留，各自业务键明确 | 固定丢29日、把28改29、同键异值任意择一拒绝 |
| 完整源unit/分页 | 不足6000行一页结束；整页后续页、恰好整倍数后空末页均完成；连续已完成页可恢复 | 满页直接截断/直接失败、缺页、重复页、预算耗尽未见末页、初始空源或超时/502冒充完整成功拒绝 |
| 对象与退市 | 上市股完整源历史保留，退市规划/出站请求数及新Raw/Silver行情行数均为0，旧存量随旧根删除 | bootstrap/日常/因子/手动/重试请求退市股、从旧文件带回退市行、把换码或停牌误当退市拒绝 |
| 先删后建 | 临时目录中仅两白名单旧根删除，删除完成后才进入正式下载，其他目录保持 | 错误路径、挂载异常、symlink越界、仍有写者、对象池为空或阶段不明时拒绝删除 |
| 新基线范围 | 仅用新源片段，同一分区一次组装；未返回旧键不保留 | 读取/合并旧行情、用旧Prod补洞、缺源写空文件或整套写绿拒绝 |
| 提交与就绪 | 首次目标不存在，本次已提交文件可认领；缺数窗口不就绪 | 第三方文件被覆盖、旧事件使未完成基线就绪、误删共享父目录或Silver拒绝 |
| 复权刷新/历史直取 | 相邻交易日因子变化触发两频历史；bootstrap/主动历史下载无需因子变化，直接保存源价格 | 因子未变化就阻止主动历史下载、先重算复权价、因end_date变化刷全市场、未完成两频却消费变更拒绝 |
| 取消恢复 | 删除途中可继续剩余删除；进入下载后仅续未完成源/文件单元，替换前后退出可恢复 | 下载后再次清空根、丢弃已完成新文件、取消后领新unit、旧worker继续写、第三方目标被覆盖拒绝 |
| 事件/切换 | 文件及检查准确绑定，事件失败只补事件，sensor意图保留 | 未验收文件写绿、旧Prod与新源双写、cursor清空重跑拒绝 |

先用独立字面金样本、替身和临时目录覆盖上述逻辑，删除/中断破坏测试不在正式Lake执行；真实样本只选必要代表，复用成功捕获。正式验收只查本次请求、输入/输出范围、候选、文件及事件事实，不默认通过同一公式全量重算，不重扫全湖。真正源矛盾保留证据并报告，不能靠放宽检查宣布完成。上市集合跨长任务发生变化时，只按变动对象追平准入/退市清理；按受影响文件汇集一次，不能每只退市股重扫全部历史。

Raw通过后才生成周/月Silver。Silver与Raw共用确认上市集合，保留三套源价格、规范身份/日期并按完整版本择行；初次及历史变更所有周期均需传递，不能因Raw正确就宣称Silver完成。Silver字段、择版及执行/检查合同在该阶段开工前明确，验收仍要求退市行0，不重新向Tushare下载已保存Raw。

## 8. 已完成清退与历史依据

2026-10-15三个退役asset/job、9项check及目录清退完成，删除1,863文件/119,217,876字节，代码82e5c225、收尾2783789c。两复权根与sensor意图保留，正式重载曾获准导入未验收R3但未运行R3。隔离214测试/509子测试及5项删除边界测试只证明旧清退范围，不冒充新直接源验收；既有两项全局治理缺项未放宽。

旧B0=1785、859周文件/3,028,907行是2026-10-13历史Prod搬运事实，不是新下载行数目标。详细历史见[结案记录](../../../reports/stock_period_raw_closeout_20261006.md)、Git及/private/tmp/dg_retirement_formal_20261015；不恢复旧命令卡、日常搬运证明依赖或重复清退流程。其他暂停专项的原现场不由本轮文档或执行器操作。

<a id="adjusted-weekly-bootstrap-capture"></a>
<a id="adjusted-weekly-bootstrap-replacement"></a>
<a id="adjusted-weekly-formal-preflight-20261012"></a>
<a id="adjusted-weekly-bootstrap-execution-20261013"></a>
<a id="adjusted-weekly-bootstrap-event-replacement-20261013"></a>
<a id="adjusted-weekly-d1-d2-implementation"></a>
<a id="adjusted-weekly-d2-sql-memory"></a>
<a id="weekly-factor-repair-alignment-20261012"></a>
<a id="34-m9-更新机制每日1930与备用仅手动2026-10-04"></a>
<a id="后续真实验收执行卡2026-10-06准备完成"></a>
以上旧锚点只保留历史引用定位，不提供当前执行步骤。
