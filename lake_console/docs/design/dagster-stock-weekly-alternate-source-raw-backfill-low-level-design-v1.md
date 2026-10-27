# DG 周/月Raw更新、完整性审计与Silver生成共享 LLD v1

**当前状态：2026-10-28。** 本次方案/LLD已先提交befd282e0，随后按批准范围完成开发、隔离验证及实现对账，详见[第12.15节](#period-delivery-recovery-implementation)及[报告](../../reports/dg_stock_period_delivery_recovery_20261028/README.md)。411个去重用例最终验证通过，保留原失败轮次及复验；未部署、未修正式状态、未补数。第12节为本次实现依据，原5/10/11节历史验收不代表正式恢复完成；字段、源请求、选行、路径、锁及其余有效约束继续适用。

更新：2026-10-18。**Raw第8步、一次完整性审计、Silver首次生成/登记均已完成。** Raw两频2,250文件/4,486,908行、baseline=ready，截止2026-10-16，见§5.15；审计无缺口或版本冲突，见§9.6。Silver实际810文件/3,105,684行，21列及原值同Raw，810物化/2,430项blocking检查均通过，首次实施结果见§10.10。**§11日常恢复和自动接线开发/隔离验收已完成并提交6e6017712；正式加载、两个Silver sensor初始化/启用及无输入自然tick已通过，见§11.12—11.13。首个真实日常交付待周一原19:30窗口。** Prod后置。25股修复及R5登记已完成，专项工具已清退，结果见其原方案§9和LLD§23.7；下文有日期的暂停要求保留为当时执行边界。

本文的执行规则是已确认目标，原审计及前五步历史交付在§5.3—5.5；第6、7步的当前执行清单、验收及停止条件唯一在§5.6—5.7。已有源证据继续复用，不因修订设计重新请求源或扫描旧数据。

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
2. 恰好6000或其整数倍行数时，必须再取一个空末页。满页本身不是失败，也不能因此截断或宣称完整；仅在耗尽已审计的响应/单元/空间预算仍未见末页、请求失败或分页证据异常时，单元保持未完成。
3. 页完成后保存请求参数、页号/offset、行数及源片段，恢复接未完成页；只有页链连续且观察到短页，整个股票×freq单元才完成。拒绝缺页、相邻页重复导致的业务键重复/冲突，以及把超时或无字段响应当空末页；不新增整库复查。
4. 周线依据[DatasetSourceClient.iter_weekly_adj_pages](../../../src/foundation/ingestion/source_client.py)：追加limit/offset，页前后检查取消，短页返回，达到预算未见末页则拒绝完成。月线通过同文件iter_pages/_iter_request_pages/_fetch_page执行同样的满页续取、短页结束；两套DatasetDefinition的page_limit均为6000，见[market_equity.py](../../../src/foundation/datasets/definitions/market_equity.py)。
5. [test_stock_weekly_adj_p2.py](../../../tests/test_stock_weekly_adj_p2.py)已有替身测试，覆盖整页后空末页及页预算耗尽拒绝。这是实现与测试依据，不冒充本轮真实分页通过。DG参考其分页和响应处理语义，不直接搬入Prod TaskRun依赖，也不机械套用Prod周线3页/12000行预算。

**已确认的是参考Prod的HTTP请求方式，不是接入Prod代码。** DG自己发送包含api_name、token、params、fields的POST；不导入Prod Settings、客户端、Ops/TaskRun或App。DG已有[TushareResource](../../orchestrator/src/orchestrator/defs/resources.py)通过DG环境注入TUSHARE_TOKEN并用SDK请求，既有分页在[tushare_api_io.py](../../orchestrator/src/orchestrator/defs/tushare_api_io.py)。本专项沿用DG自己的配置接线，只将这两套Raw的传输改成HTTP；其他DG数据集继续原行为。HTTP字段和分页语义参考Prod，不能把week专属限制套给month。

父进程从已加载的DG进程环境解析本专项配置，worker只接收已解析值。独立CLI继承同一DG环境，缺token直接报告，不自行读取仓库根.env、.env.web.local或GOLDENSHARE_ENV_FILE，不添加PYTHONPATH，不安装Prod项目。DG本地集中定义HTTP地址及限流默认，配置审计见§6.2。为错误导入新增的pydantic-settings声明列入代码纠偏；本轮文档修订不改锁文件、不卸载套件。

2026-10-16已有HTTP连通性证据：使用[TushareHttpClient](../../../src/foundation/clients/tushare_client.py)请求000001.SZ/week/trade_date=20261016、4个身份/日期字段，0.485秒返回1行，无重试，end_date=20261015。结果在/private/tmp/dg_period_prod_http_connectivity_20261016.json。该单次请求不是全历史吞吐或全部21列本轮验收，后续不重复测连通；只在必要代表样本中合并确认历史回包、页链与成本。原MCP/SDK失败证据保留在原临时记录，不再列作当前连通性阻塞。

## 2. 对象、任务身份与复用

<a id="silver-listing-boundary"></a>
### Silver的上市周期边界（2026-10-17已确认并实施）

Raw保留当前上市对象的全部源历史，包括北交所正式上市前的新三板行情。Silver以`stock_lifecycle.list_date`确定保留的首周、首月，排除完全位于上市之前的周期；上市所在周/月整根源K线保留，不切割周期，也不专项核验其中上市前的成交。不能用源首条行情或换码日期替代正式上市日期，不改变退市对象不请求、不保留的既定范围。

此前“首期只能包含上市日起成交、需另核源K线是否混入上市前行情”的表述撤回，不作为开发或审计门禁。2014起点、停牌、择行、一次审计流程及通过标准统一见[§9](#period-completeness-audit)，不另设首期核验步骤。

### 2.1 对象范围

每个逻辑任务开工固定一次非空的仍上市CNY股票集合、confirmed身份及北交所映射。复用silver/basic/stock_basic与现行身份事实；不把含L/D/P/G的Raw股票表当请求池。北交所使用确认的新码，例如832000.BJ→920000.BJ；新上市且已确认直接使用新码的股票无需伪造旧码。换码、停牌或身份未知不能当退市。

退市对象不规划单股请求、不出站、不重试或兜底；日常全市场回包按同一集合筛选，源行数=准入行数+范围排除行数+异常行数，范围排除与技术reject分开。Raw保留准入记录原始代码、日期及字段，不把旧码行改名；源意外回活动股票旧码时保留证据并拒绝该单元。历史任务的范围变更不能偷偷改旧manifest；跨日交接按§4.4处理变动对象。

### 2.2 新刷新与续跑必须分开（纠偏4）

| 标识 | 含义与生成规则 | 复用边界 |
| --- | --- | --- |
| intent_id | 一次明确的bootstrap、主动历史刷新或日常工作意图；新意图生成新ID，手动历史刷新不得默认固定为manual | 重试/取消恢复沿用原ID；物理Dagster run_id、重试次数或恢复当天日期不改变它 |
| source_unit_id | intent_id + 请求种类 + 有效ts_code/freq或目标周期 + 冻结范围/字段/请求合同 | 同一意图内完成单元复用；新的主动历史下载不能拿上次意图的缓存充当重新下载 |
| file_unit | asset + 周/月分区 + 本轮输入版本 + 目标前像版本 | 同一候选及提交事实可恢复；输入/目标变化只失效相关文件 |

保留run-scoped源页、候选、receipt和逐文件checkpoint；在现有执行manifest/daily控制记录中保存活动意图和待办引用，不新建数据库表、长期任务框架或永久行情版本库。恢复先找原活动意图，再规划新日期工作，不能因新一天启动就丢掉原任务。上市范围和policy按原manifest恢复，不改hash来强行续跑。

第1步落地：现行合同版本stock-period-source-v2；外部request_id就是逻辑intent_id，执行目录ID仅由合同版本及该ID生成，完整范围/root/policy另存identity_hash并逐项核验。手动历史不再默认manual；新动作需新ID，同ID不能改范围/日期/policy。CLI resume及事件消费者均校验v2。旧v1临时证据保留，但不能作为v2可执行计划，不修改旧指纹。原意图跨日显式续跑已测试；第4步已补齐sensor待办准入、冻结原意图续跑、未完成页链跨日隔离及未发布周期新轮次取源；当前证据见§5.5。

完整且已验证的源单元不重下；未完成页链只在请求与源版本仍可信时接续，跨日源变化使连续性不再可信时仅重取该未完成单元，保留旧证据。明确判为“尚未发布”的回包不能被完成缓存永久挡住新请求；下一次获准运行只重取未就绪周期。已完成旧意图被后续任务更新的目标不能用旧候选覆盖，旧记录只供追溯。

### 2.3 源页与异常证据（纠偏10）

每页按同一21列合同请求，记录安全参数、offset、实际行数、捕获时间、源end_date观测及原始片段。技术失败、真实空源、超精度、字段/身份/分页异常分别给reason code；没有HTTP回包的超时只记录安全错误，不编造源文件。

失败记录至少包括source_unit_id、非敏感请求、offset、捕获时间、reason code及有界回包路径；沿用period_source_fields_invalid、period_source_decimal_invalid、period_source_identity_invalid、period_source_repeated_page等现有原因，不把这些技术错误记作退市范围排除。

已取得的有界原始回包先保存为待验证证据，校验通过后才产生可复用页receipt/CSV。校验失败保留原回包及失败原因，不生成成功receipt、完整单元或候选输入。超大/不完整响应保留已接收的有界诊断，标明截断；不为留证突破响应/空间预算。token、认证头及含凭据的异常文本不落盘、不进入日志。完整非空单元的页链连续、字段和键校验通过才可触发历史替换。

## 3. 一次组装、必要检查与提交

<a id="31-删除边界与数据空档"></a>
### 3.1 先删后建的边界（纠偏7）

正式删除仅允许两固定根：/Volumes/datasource/data_lake/raw/tushare/stk_period_bar_adj_week、/Volumes/datasource/data_lake/raw/tushare/stk_period_bar_adj_month。执行前一次检查datasource真实挂载、规范绝对路径、符号链接边界、非空准入范围及无冲突写者，并取得唯一写锁。检查后挂载或目标设备身份改变时停止，不能把失联移动盘路径当本机目录继续创建/删除。

只列目录元数据，不读待删Parquet、不核旧行数/价格、不算旧hash、不做备份或Kopia；不删共享父目录、Silver、其他Raw、staging或Dagster历史。两个旧根均删除并持久化删除阶段完成后才下载。删除中断只续剩余删除；进入下载后永不再次清根。新基线未就绪时，旧物化不能证明数据可用。破坏性测试只在临时根，以替身验证正式挂载拒绝，不操作真实移动盘。

### 3.2 三种写入与统一候选（纠偏2）

| 意图 | 候选组成 | 不允许的动作 |
| --- | --- | --- |
| 首次bootstrap | 空根仅取本次完整成功源单元 | 读取旧行情、合并旧键、旧Prod补洞或因源空写空文件 |
| 当前周期/欠账 | 选定周期按(ts_code,trade_date,freq)整行upsert | 扩到其他周期、逐日重放或本地重算价格 |
| 单股完整历史刷新 | 保留非目标股原行 + 目标股本次完整非空历史；移除该股源不再返回的旧键 | 空源/失败/缺页先删除、误改其他股票或未选频率 |

日常执行先规划欠账/当前周期、相邻因子变更、确认新上市及退市对象；下载可以先欠账后当前，但不能下载一批就先提交一轮。所有成功输入按频率一次导入、受影响分区取并集、统一候选，一个分区只组装/校验/提交一次。一个频率负责的当前周期与涉及该频率的历史刷新必须同批合并；因子触发两频历史，各频率共享同一变化通知，不能由两个job重复消费。

“一次组装”指业务行集合只生成一次，不保证分区COPY只生成一个物理片段。临时多片段按[§5.12](#step8-candidate-fragments)只做必要归并，正式仍为每分区一个文件；不重做源导入、业务组合或复权计算。该修复已实现并通过隔离验收，尚未用于正式续跑。

周期回包和完整历史回包有重叠键时，21字段完全一致可合并为一条；同键异值保留两份证据并停止冲突输入，不按先后顺序覆盖。需要重取时只针对冲突对象/范围，不能重新下载整个市场。20200228/29是不同键，两条均保留。

历史替换的范围是目标股旧分区与新源分区的并集，包括仅旧键所在分区。优先使用该股上次已验证源/提交记录的分区范围，记录须绑定数据集基线和文件版本；缺失、漂移或不能证明覆盖旧范围时，对本批目标股只做一次键/filename列投影定位，再只读命中价格。首次bootstrap不运行旧键定位。多股汇集处理，不能每股重扫全历史。移除后空分区按明确的有效空候选处理，不能以此掩盖源下载失败。

### 3.3 检查何时执行、证据如何复用（纠偏11）

| 检查/风险 | 必须执行的边界 | 正常复用与失效 |
| --- | --- | --- |
| 对象/字段/分页/精度/源键，防错请求与截断 | 页取得后一次；完整单元成立时检查页链/汇总 | 成功页及完整单元按请求/范围/文件版本复用，异常单元不复用成功标记 |
| 合并范围、唯一键、行守恒与分区，防误改其他股票 | 导入及候选生成阶段按频率/受影响分区批量聚合 | 输出由已验证关系投影21列；不每分区重新读取全源，不重算复权公式 |
| 候选文件合同与版本，防COPY异常/后续变化 | COPY后统一检查schema、分区集合、行数/键事实，并保存每文件验证结果 | 优先批量读取/聚合；逐文件保留路径、版本、必要hash与行数，不逐文件重复建重查询或监督线程 |
| 目标前像与同文件系统，防覆盖别的版本 | 组装读取目标时记录，提交锁内比较一次 | 元数据版本一致即复用；缺失/新增/变化按§3.4拒绝，不深扫无关目录 |
| 实际落盘/检查绑定，防事件指错文件 | 每文件提升后读回身份、checkpoint；正式check/事件引用同版本事实 | 同版本共用验证结果；变化才重新检查，正常路径不再hash或全量重算 |
| 取消/进度/空间，防失控任务 | 页、SQL、文件边界；长步骤可中断；写入前必要空间检查 | 本地取消标志及时检查；远端run状态有界轮询，不把0.2秒本地检查变成每秒5次数据库读取 |

范围索引/缓存、批量验证、增量计量或调整进程粒度均可选择，以失效规则和小样本收益决定，不沿用“不缓存、不降频、不新增状态”的默认禁令。缓存失效只重做受影响证据，不扫描整个库。公式由独立金样本证明；运行验收核真实输入、输出、范围和持久化事实。

第2步落地：现有baseline.json增加按股票/频率压缩的精确连续周期区间、完整文件清单及range_index_hash/version，不新增配置或数据库表。文件清单及dev/inode/size/mtime/ctime全部一致时复用；索引hash、文件版本或目录清单不符则一次批量投影目标股票的键，不能把失效索引重新标成可信。候选每频合并schema及键/范围查询，已校验文件仅核同版本receipt；combined行数与候选行数逐分区对账，不重算价格。

### 3.4 目标前像、持久化及异常退出（纠偏6、7）

候选receipt除输入与输出证据外，记录目标前像：bootstrap为“不存在”；其他模式记录实际文件的dev/inode/size/mtime/ctime版本。提交时持有同一写锁，检查候选版本、目标仍为预期前像、固定路径和设备身份、剩余空间及同文件系统；前像漂移停止该文件，不强制覆盖。该核验只读元数据，不回算目标价格。

按顺序完成：候选内容fsync → os.replace → 目标所在目录fsync → 读回新文件身份 → 原子保存并fsync checkpoint及其目录。首次创建目录时需持久化必要父目录项。os.replace只承诺逐文件原子，不承诺多文件事务或单独证明断电持久性；平台不支持必要持久化操作时显式报错，不静默降级。

replace成功、checkpoint失败时，恢复只对该目标做一次必要hash/版本识别，确认就是已验证候选后补记，不重新生成或覆盖文件；其他目标拒绝认领。完成checkpoint后正常恢复只核版本。候选/文件/cp保留，取消后不领新单元；协调器TERM/KILL后本任务worker必须退出，旧worker退出前新写者不能接管。锁和父进程监督继续保留，不借性能优化取消这些要求。

## 4. 日常成功条件、事件与bootstrap交接

### 4.1 待办及水位（纠偏3、4）

19:30后按交易日规划，周/月欠账按周期去重，先补欠账再刷新当前。周五失败下周补原周，月末失败次月补原月，不逐日重放；完整休市周期以交易日历证明跳过。sensor先做时间/状态轻判断，仅读取必要控制摘要和选定日历，不写Parquet。

日历统一消费既有silver_trade_calendar，路径为silver/calendar/trade_calendar/full/part-000.parquet，合同为exchange VARCHAR、trade_date DATE、is_open BOOLEAN、pretrade_date DATE。calendar_days的投影/排序及sensor当日筛选都使用trade_date；Raw trade_cal的cal_date已由既有silver_trade_calendar_select转换，不能直接拿Raw字段充当Silver合同。这里复用共享日历，不涉及开发周/月Silver。测试须以该生产者及SILVER_TRADE_CALENDAR_SCHEMA为依据，另用独立字面断言核对字段/结果，不能随消费者查询反推夹具。

| 事实 | 可完成的条件 | 失败/恢复规则 |
| --- | --- | --- |
| 当天周期刷新 | 本周期源已发布到意图交易日、候选检查与文件提交成功 | 源陈旧/全NULL时留待办，不因HTTP200或19:30标当天成功 |
| 已结束周期水位 | 日历证明已到该周期最后开市日，源观测达到该日，文件交付完成 | 周中/月中不能提前关闭；连续水位不能越过欠账 |
| 因子/新股历史工作 | 目标股两频完整下载及所有应改文件检查/提交完成 | 只完成一频不消费；保存未完成引用，下次先续原意图 |
| 事件 | 本次每个实际变更文件的物化及检查准确绑定该文件版本 | 观测失败只留事件待办；不回滚文件、不重新下载、不得冒记事件成功 |
| 整个意图结束 | 必要文件工作及应补事件均已关闭，交接条件满足 | sensor同时看周期、历史、事件待办，不能仅凭last_refresh跳过 |

源发布采用本次所选周期准入回包的最新非空end_date观测，达到意图交易日才推进当天刷新；不要求每只股票的end_date一致，停牌股或历史旧版本的合法NULL/旧日期照样保留。没有可用发布证据时保持待办，不另增市场探测请求或无限轮询。旧回包可保留为证据，但不能当新发布成功。主动历史/首次历史捕获不以end_date新鲜度或因子变化为下载前提。

物理业务成功和事件成功分别记录：因子消费依据两频已验收文件事实，事件失败不得使已消费文件重下；事件待办独立触发补报。状态落盘失败不回滚已提交文件，恢复从checkpoint补记。上述条件的最小字段及活动意图引用放入现有manifest/daily记录；sensor保持小cursor，不写文件全清单。两个sensor名称、运行意图和原cursor证据保留，不重置水位。

### 4.2 文件与事件阶段（纠偏8）

阶段顺序为删除（仅bootstrap）→下载/候选→逐文件提交→files_complete→事件补报→events_complete；bootstrap再完成§4.4交接才baseline ready。每个文件commit checkpoint先于该文件完成记录；全部文件完成时先持久化files_complete，事件失败不能把文件阶段退回download。事件cp只在该文件准确物化/检查均确认后保存。

CLI的events只允许消费files_complete后的提交清单，不下载、COPY或重新覆盖；resume从原阶段继续。标准asset返回MaterializeResult的当前分区不能被内部空回调冒记事件成功：外层物化/check未完成时保留其事件待办，下次只核准确的物化/check绑定后补记；其他实际变化分区走同一事件核对。不能将所有频率、分区都假定当前anchor成功。

事件入口共用唯一写者或等价的目标版本保护，清单须绑定意图/基线/文件版本；检查最新记录必须按资产、分区及目标物化关联，不能拿其他分区同名check充数。重复补报仅补缺失项。已确认检查登记使用真实Dagster运行：日常沿用当前run，CLI events在一次真实补报运行内处理全部文件，不能伪造run或逐文件启动运行。原因是当前Dagster的runless检查使用空run_id，同分区再次登记会撞唯一约束。instance资源在成功/失败均释放，取消覆盖事件循环。正式事件执行仍另行授权，本轮仅隔离instance写测试事件。

已确认CLI新增独立handoff动作，沿用--run-id及根目录参数，不新增配置；它可执行§4.4有界补取及交接。events仍只补事件，不自动下载、COPY或交接；handoff使用一次真实运行登记其子意图检查，已ready时只返回既有状态，不重置后续日常水位。

### 4.3 因子与对象变化

只复用stock_daily_qfq.py的build_stock_daily_qfq_factor_changed_codes_sql识别自上次消费以来相邻交易日差异，按股票去重。首次识别后将待刷新对象/日期与原意图关联，失败续跑复用该事实，不为同一通知反复比较已消费日期。两频无时间请求取得最新完整历史，不本地重算复权价，也不新增历史因子修订探测器。新上市补两频历史；确认退市只清理受影响行、不请求源。换码/停牌不能按退市清理。

### 4.4 bootstrap跨日交接（纠偏5）

记录实际开始/最后完成的上海时间、对应交易日、各成功单元捕获时间/请求及源观测。初始历史下载不是同一时刻快照，不能用全股票end_date最小值初始化全市场水位，更不能把停牌股的陈旧end_date扩成多年欠账。

历史文件完成后，交接仅处理实际开始至交接截止间涉及的周/月当前值与最终值、期间相邻因子变化，以及交接时一次上市/身份集合差异。复用成功完整历史，只补当前/未最终交付周期、实际变化股、新上市和确认退市；所有补取按§3.2合并，不能把整个市场历史重下一次。原范围不变，集合差异作为有界交接子意图记录，不篡改原manifest。

选定已发布交易日作为交接截止，文件、必要事件和对象变动处理完成后才写ready及日常水位；源未发布或缺项则保持未就绪。执行期间跨入的新交易日只作为后续欠账接续，不追逐实时源无限循环。重复交接复用本次完成记录，不重置已推进的日常水位。Raw ready不代表Silver完成；Silver首次生成及后续日常状态分别见§10.10、§11。

## 5. 改动范围、当前实现与14项分类

### 5.1 开发文件与消费者

路径相对orchestrator/src/orchestrator/defs；下表是完整纠偏范围，不表示所有职责均已落地。前五步交付见§5.4—5.5，接续开发的具体范围及条件见§5.6—5.7。

| 文件组 | 必须承担的职责/影响边界 |
| --- | --- |
| run_contracts/stock_period.py、configs.py | 请求合同、policy、意图与单元身份；拒绝旧参数及固定manual缓存复用 |
| stock_period_source.py | DG环境配置、仅两频HTTP、持久页/失败回包、完整分页与可取消worker；不import Prod |
| io/stock_period_raw.py | 合并三种写入、范围事实复用、批量候选检查、前像保护/落盘、同版本check证据 |
| bootstrap/stock_period_history.py、stock_period_history_cli.py | 原意图恢复、删除门禁、累计预算、文件/事件阶段、跨日交接与ready |
| stock_period_update.py；两个asset及两个原sensor | 一次规划/合并，周期/历史/事件待办，独立成功条件；保留运行身份，不漏因子工作 |
| checks/stock_weekly_checks.py、stock_monthly_checks.py；stock_weekly_file_checks.py、stock_period_checks.py；旧update_state辅助模块 | 现行检查保留同版本复用和准确物化绑定，不依赖旧搬运证明；旧辅助模块按§5.6引用闭包清理，不以提速为由删正式语义 |
| catalog/lake_assets.py；jobs/stock_weekly.py、stock_monthly.py、stock_weekly_event_backfill.py；ops/stock_weekly_bootstrap_checks.py | 来源、描述、补事件入口与当前合同一致；catalog只保留必要业务hunk |
| run_contracts/stock_weekly.py、stock_monthly.py及旧update辅助模块 | 按当前消费者移除旧Prod预算/计划/说明，保留确有调用的字段/路径/分区能力；不盲删共享代码 |
| pyproject.toml、uv.lock | 撤销仅为错误Prod Settings导入而新增的声明；不升级或移除既有依赖，环境卸载另按明确清单处理 |
| tests/test_stock_period_*.py及既有周/月contract/definitions/sensor/state/check/event测试 | 实际入口、独立字面金样本、失败恢复及性能计数；protected reader清单仅随真实源码闭包迁移 |

旧Prod供数、SDK月线point及专用bootstrap/event共30个实现模块、19个旧测试/夹具已在工作区移除；四个旧CLI只拒绝旧入口。这些清退方向已批准，不整体恢复旧链。残留的旧合同/说明已按第6步收口，见§5.8。Prod应用自身、其他数据集及R3代码不在范围。

### 5.2 当前阶段与执行顺序

A阶段最小真实源样本已保留；步骤1—7已提交至d46486a5。第6步清退及第7步原155项回归见§5.8；日历相关通过结论已撤回，本轮修复、44项受影响回归及真实只读核验见§5.9，不与历史数量累加。修正已提交ec9a33a0并加载；第8步的历史停点及恢复边界保留于§5.10，后续正式完成见§5.15；Silver本次亦已完成，见§10.10。

### 5.3 14项的实现状态与开发动作

原审计分类：**A已有代码需纠正10项；B部分实现但缺必要保护2项；C缺验收能力1项；D仅文档偏差1项。** B/C也不能只改文档就关闭。下表保留2026-10-16纠偏前事实及编号；前五步交付见§5.4—5.5，剩余动作按§5.6—5.7，不把历史缺项继续当当前未实现，也不把局部完成当14项全部关闭。

| 项 | 分类 | 纠偏前审计事实 | 完整纠偏位置与目标 |
| --- | --- | --- | --- |
| 1 Prod耦合 | A | HttpPage直接导入Prod Settings；已新增声明且DG环境已安装pydantic-settings2.14.1 | source/依赖声明；改DG接线，见§1.1、§6.2，不再安装Prod |
| 2 重复提交 | A | daily先upsert后另开history，同分区可能两次提交，无跨批冲突合并 | update/history/raw；统一候选、同键异值停止，见§3.2 |
| 3 成功条件 | A | 周期先记last_refresh，后续历史失败可被sensor跳过；旧源也可记当天成功 | update/sensor；周期、历史、事件待办独立，见§4.1 |
| 4 意图/恢复身份 | A | manual默认固定；日期/新run改变源片段目录，可能旧缓存冒充新刷新或跨日重下 | configs/history/source/update；新意图新ID，续跑原ID，见§2.2 |
| 5 跨日交接 | A | 用各股源asof最小值简化初始化，实际期间追平/对象差异未完整实现 | history/CLI/update；实际执行区间有界交接，见§4.4 |
| 6 目标漂移 | B | 已有候选版本和提交后核对，缺目标前像记录/提交前比较 | raw；首次不存在、后续版本一致才replace，见§3.4 |
| 7 删除/持久化 | B | 有固定路径/链接拒绝及replace，缺正式挂载/设备门禁和完整fsync链 | history/CLI/raw；边界保护补齐，见§3.1、§3.4 |
| 8 阶段/事件 | A | 文件阶段晚于事件落盘；anchor空回调可冒记事件完成 | history/CLI/update/event op；files_complete先落盘、真实事件后确认，见§4.2 |
| 9 配置/预算 | A | 已有policy，但8处SQL未透传；部分空间计量在下载/COPY之后 | contract/source/raw/history；同policy及写前增量/剩余空间，见§6.2 |
| 10 失败证据 | A | 源校验在保存前，异常回包可能丢失 | source；有界保存失败证据，与成功输入分开，见§2.3 |
| 11 重复工作 | A | 总是全文件定位旧键，逐文件SQL/监督线程，高频远端取消查询 | raw/update；范围事实、批量验证及本地取消，见§3.3 |
| 12 真实验收缺项 | C | 真实样本未走最终DG执行器；CLI/进程/合并恢复覆盖不足 | 相关测试/样本；独立入口、真实进程、小样本成本，见§6.1、§7 |
| 13 清退收口/噪音 | A | 旧月线计划/预算、job说明残留；catalog大面积格式改动 | contract/job及直接测试清退；保留共享能力，catalog格式改动保留工作区并隔离提交，不整文件回退，见§5.6 |
| 14 文档失真 | D | 修订前文首写未开发，Settings及若干能力写成已具备，快照状态过时 | 本方案/两LLD/架构快照；本轮已修正供review，代码仍待改 |

旧实现测试曾为116项隔离通过；补依赖后的进程用例1通过、2失败，失败发生于独立协调器导入src之前，不能证明TERM/KILL后worker/锁通过。该历史记录保留，不计为本版本验收。当前证据见下一节。

<a id="step12-delivery"></a>
### 5.4 第1、2步交付与质量审计（2026-10-16）

| 确认要求/审计编号 | 本轮实现 | 正反验收与剩余边界 |
| --- | --- | --- |
| DG请求接线，1 | stock_period_source.py局部PeriodHttpConfig与POST；撤销pyproject/uv.lock中本任务误增声明 | 禁止import src/pydantic_settings、DG环境覆盖/默认/缺失/非法值；localhost真实21列POST；未卸载已安装包，未改其他数据集 |
| 意图与分页复用，4的核心 | stock_period.py、configs.py、history/source及CLI/event消费者统一v2身份 | 新ID重新取源、原ID不重取完成页/单元、跨日显式恢复冻结原范围/policy；同ID变范围拒绝。sensor自动续原待办及未完成页跨日连续性仍待后续步骤 |
| 有界失败证据，10 | source先存回包再校验；失败JSON与成功receipt分开，超大响应保存有界前缀，凭据脱敏 | 畸形JSON、缺列、超精度、空源、重复/截断页、超时、超大HTTP及凭据回显反例；不产生成功输入 |
| 一次规划/组装/提交，2 | update仅改日常规划函数；history收齐两频候选再提交；raw同频一次导入/COPY | 真实日常因子调用链与字面金样本：目标旧键移除、仅旧键分区处理、其他股票/未选频率不变；价格/NULL/end_date/覆盖冲突在任何提交前拒绝 |
| 范围/验证复用，11的本轮部分 | raw压缩区间、inventory版本失效、批量schema与键/范围统计、行数守恒 | 无漂移不做历史键扫描；索引或文件版本漂移整批定位一次且不恢复可信标记；候选丢行拒绝。远端取消查询节流未在本轮改动 |
| 配置透传、真实验证及文档，9/12/14的本轮部分 | 新批量查询传同policy；source真实进程、CLI恢复、缓存样本与状态文档 | 138项离线直接回归通过，4项localhost进程通过；再追加4个离线用例：文件版本漂移、候选丢行、第二频率冲突前置拒绝、事件读取入口身份校验，全部通过。预算/全部SQL消费者及最终全链验收未关闭 |

第3步及以后的目标前像、正式挂载/设备与完整fsync、累计空间/当前RSS、文件/事件阶段、source发布成功条件、自动待办续跑、跨日交接及旧合同/格式收口未推进；不因本轮测试通过宣称可正式重建。第3/5/6/7/8/9/11/12/13项的这些缺项继续有效。本次提交包含尚未单独提交的Raw基础接线及前两步纠偏；不表示后续缺项验收通过，不推送。正式操作为0，R3继续暂停。

本轮审计使用CodeGraph explore/impact/callers及开发后sync/status，并阅读DG入口→update→history→source/raw、CLI/event直接消费者和测试。根Prod同名符号不作为DG复用实现；无Prod业务子系统依赖矩阵变化。共享configs仅修改StockPeriodRawConfig；sensor/asset、publish和删除函数未改，事件业务流程未改，仅同步事件读取入口的v2身份校验。实现和测试证据保存于/private/tmp/dg_period_step12_1792114835145123000/；不依赖该临时目录维持日常运行。

提交前补查catalog/registry：12项通过、1项治理库存检查失败，ASSET_CHECK_GOVERNANCE缺16个既有资产（含月线）。以HEAD的catalog与未修改的治理测试核验，缺项集合完全相同，非本次回归；本轮记录、不扩展修治理库存。catalog仅提交周/月源与性能说明的业务差异，无关格式改动留在工作区。文档完整性检查通过。证据：同目录commit_catalog_gates.json。

### 5.5 第3—5步交付与质量审计（2026-10-16）

本节保留第3—5步交付时的证据；已提交89ce38fe，§5.4保留前两步交付历史。该阶段仅开发和临时根/隔离instance验收，未执行正式操作、未推进第6、7步，R3继续暂停。

| 步骤 | 实现与检查边界 | 当前验收状态 |
| --- | --- | --- |
| 3 文件与资源保护 | 候选记录目标前像；同设备/挂载检查；候选fsync→replace→目录fsync→checkpoint；当前RSS替代历史高水位；运行内字节增量计量，恢复只枚举一次本任务目录 | 13项存储测试（含1项进程）通过；漂移/挂载/预算/持久化异常拒绝；恢复认领精确新文件，不重写 |
| 4 成功条件与恢复 | files_complete先持久化，完整receipt绑定文件版本；daily保存冻结意图、文件消费和事件待办；源未发布不提交候选/推进当天成功；仅重取未发布周期；未完成页链跨日换独立链，原片段/receipt路径与内容保留 | 7项恢复测试及4项CLI测试通过；真实运行支持同分区多版本检查；事件失败/状态失败不重下、不重写，实例及锁释放 |
| 5 有界交接 | handoff_bootstrap冻结实际开始至选定发布日的周期、因子与一次对象/身份差异；子意图可恢复；不取全股票最旧end_date；文件、事件及水位完成后才ready | 6项内部交接及CLI真实运行测试通过；暂停、源陈旧、事件失败均不ready；恢复复用片段，重复交接保留已推进水位 |

配置仍沿§6.2，不新设业务上限/批次/并发。COPY前空间预留采用已验证行数×512字节加每文件16KiB：21列定长数值/代码日期及已测稀疏Parquet开销的保守估计，不读取价格另算容量；spill另作额度预留，不能计成实际已用。成功写入按路径增量记账，同设备提升计转移；完成后事件恢复不枚举源目录、不跑SQL或hash。macOS当前RSS读取按本机SDK的mach_task_basic_info定义，未安装新包；不把该进程RSS宣称为进程树总量。候选已完成的正常提交不再打开无用途DuckDB连接。

未发布周期以新捕获轮次重取，已成功历史保持原单元；未完成页链跨日时保留旧页和receipt原路径，仅切换运行内active_chain引用。缺设备保护字段的旧过渡manifest显式拒绝，不补改旧identity/hash强行续跑。

固定版本集中回归：169项离线通过（5项进程另跑），5项真实进程通过；质量审计后补齐旧待办日历查询沿用冻结policy，21项直接消费者再验通过；未受影响路径无变更。Ruff、致命语法检查、文档完整性与差异空白检查通过。警告来自现有Dagster/Pydantic的preview/deprecated API，未改第三方库。真实instance仅临时目录，关闭遥测；CLI补报中途失败与实例释放也有覆盖。原生SQL TERM实测约0.011秒退出、无需KILL并释放锁；SQL仍在同一连接串行，主线程监督并中断，依据[DuckDB连接文档](https://duckdb.org/docs/current/clients/python/dbapi)，没有增加SQL或并发连接。

最终缓存样本：7片段/6单元、2599行、2207临时文件，文件阶段6.882秒、完成续跑0.107秒、文件总量6871872字节；每频导入及COPY各一次，全部完成文件版本保持不变，外部请求0。进度采样所见当前RSS最大约577MiB，不是连续峰值或进程树值；事件成本单独由少量真实instance测试覆盖，不包含在文件阶段耗时中。这里只证明稀疏样本与恢复，不外推全市场ETA。性能原件：/private/tmp/dg_period_raw_storage_sample_20261016_1792120985854052000/performance.json。

CodeGraph explore/impact已覆盖asset→update→history→source/raw、CLI/事件op及测试；开发后sync/status确认索引当前。无前端/API或Prod消费者迁移；未调整业务子系统依赖矩阵。第6步旧合同/说明残留及第7步Raw最终验收仍后置；本轮不宣称可直接正式重建。逐项对账、文件指纹、JUnit和其他任务改动核验见/private/tmp/dg_period_steps345_1792116982194093000/acceptance.md，临时证据不作为运行时依赖。

### 5.6 第6步：旧链残留、说明及本任务治理登记（已实施，隔离验收通过）

目的为收口，不重做前五步的HTTP、组装、提交或恢复架构。2026-10-16只读审计已用CodeGraph explore/impact核对旧合同及构造器，补读实际import、动态回调和测试消费者；原18文件与验收指纹一致。CodeGraph同名符号误匹配或漏掉跨文件调用时以当前源码补核，不据“零调用”盲删。

按以下顺序执行，路径相对orchestrator；只有实际需要修改的文件才进入实现/提交白名单：

| 文件/对象 | 落地动作 | 必须保留或先满足的条件 |
| --- | --- | --- |
| src/orchestrator/defs/run_contracts/stock_weekly.py、stock_monthly.py | 清退旧Prod库存/单元/计划及无消费者预算：WeeklyBudget、ProdYearInventory/Scope/Unit、WeeklyPlanManifest；StockMonthlyPolicy、MonthlyYearInventory/ProdUnit/BootstrapPlan/BootstrapIOPolicy及monthly_point_request等旧链专用构造器 | 删除前核对真实引用。保留ADJUSTED_WEEKLY_FIELDS、两频column_specs、normalize_week_key/normalize_month_key及仍在用的名称/路径/分区合同；21列、精度、NULL、原始日期均不变 |
| src/orchestrator/defs/stock_weekly_update.py、stock_monthly_update.py及对应run_contracts中的旧update policy | 删除无生产消费者的旧“仅已结束周期”规划、旧Prod操作提示和无效预算字段；保留sensor实际依赖的薄接线 | 仍被sensor使用的时区、19:30窗口、tick间隔及配置入口保持；不擅自合并policy、改StockPeriodPolicy默认值、改变意图身份或旧manifest/hash |
| src/orchestrator/defs/stock_weekly_update_state.py、stock_monthly_update_state.py | 清理仅服务旧整周/月日线检查的代码及无生产消费者的状态辅助模块 | 原weekly_event_binding跨月线调用已核实仅在旧闭包内，随闭包清退；有现行消费者的能力仍保留。stock_period_checks.py的现行文件版本/物化绑定不随旧模块删除 |
| src/orchestrator/defs/jobs/stock_weekly.py、stock_monthly.py、stock_weekly_event_backfill.py | 仅修正与直接源、事件补报不符的描述；现已正确者不改 | 资产/job/check/分区key及选择集不变，补事件不能变成下载入口；不新增job、API或CLI动作 |
| tests/test_stock_weekly_contract.py、test_stock_monthly_contract.py、test_stock_monthly_update_state.py及直接相关period/definitions/retirement测试 | 删除只验证退役实现的测试；有效业务断言先落到新链已有测试，避免重复建设 | 月线旧4页封顶及Prod库存闭合不作为新链要求；21列/Decimal/合法NULL、20200228/29、源键冲突、旧入口拒绝及独立字面金样本继续覆盖；不得为保测试数量恢复旧实现 |
| tests/test_asset_check_incremental_governance.py | 在既有登记机制中核对周线三项检查，并补月线三项检查的本任务登记 | 沿用blocking语义；不放宽全仓集合断言，不补其他数据集登记。已有16资产缺项含本月线，补后重列实际剩余项，不冒称全仓治理全绿 |
| src/orchestrator/defs/catalog/lake_assets.py | 当前来源/字段等事实已正确，默认不改；只有真实业务事实失配才提交相应最小hunk | 当前未提交格式差异与HEAD的AST一致；原样保留，不整文件回退、不整文件格式化，不把其他任务hunk带入提交 |
| tests/stock_suspend_confirmed_test_runner.py | 仅在上述源码闭包实际删除后，同步去掉对应失效protected reader路径 | 不删除仍存在的读者、不放宽其他静态门禁；不因此运行停牌或R3全链 |
| 四个旧bootstrap history/events CLI及其退役测试 | 复用已通过的拒绝证据；实际断言受影响才重跑 | 继续在源请求/目录创建前拒绝旧source、旧参数、旧计划，不新增转换兼容或兜底写入；无需为清退再次重写拒绝入口 |
| 总方案、本共享LLD、月线LLD | 当前状态、文件范围、通过/待办、配置消费者和证据保持一致 | §5.3—5.5保留明确标注的历史事实，不把旧数量/性能写为新实测；架构快照仅实际需要校准状态/调用链时触碰 |

第6步退出条件：旧链专用实现无活动引用，现行消费者可加载、字段/名称/调度参数保持不变；有效金样本已迁移，旧入口仍拒绝；周/月自身治理登记准确；其他工作区改动完整保留。只跑本轮影响的合同、定义、sensor、退役及治理测试，不默认重跑历史下载、bootstrap或全仓。若发现新的生产消费者、共享合同或源行为冲突，停下汇报，不能直接扩白名单或删掉消费者。

### 5.7 第7步：小型组合验收、缺失成本及最终对账（已完成隔离验收）

先复用证据，再补缺口；完整场景指执行路径完整，不指全市场/全历史。第6步收口后开始本节，第7步终点仅为Raw程序及隔离验收，不包含正式删除、bootstrap、交接运行或Silver。

**证据复用。** 逐项标明适用代码/合同和证据版本；原真实源7回包、独立金样本、169项离线/5项进程及最后21项消费者证据保持可追溯，重复运行不累计成新覆盖。改变合同/源码闭包的项补受影响验证；无影响且版本事实一致的项复用。旧库存/point测试清退后数量下降正常，不能靠保留无用测试凑174项；旧实现通过不能充当新主链验收。

**一个小型完整场景。** 采用现有三类股票（老股000001.SZ、北交所确认新码920000.BJ、新股301569.SZ）、两频和跨周/月边界的少量周期。日期、上市变化、相邻因子变化由独立夹具提供，先列明各阶段期望的请求参数、页数、源/准入/排除/输出行数及文件集合；这些是测试事实，不是新的生产配额。只新增缺失的组合用例，优先承载在tests/test_stock_period_integration.py及现有history_cli/handoff/definitions测试中：

| 阶段 | 执行与应验证的事实 | 禁止或失败路径 |
| --- | --- | --- |
| bootstrap文件 | 调用现有CLI apply/resume，在临时两根完成删除阶段、上市/新码准入、页/单元持久化和两频文件生成；一次受控取消后续同一意图 | 不再次清根，不重下已完成单元，不改原manifest/hash；无关临时文件不受影响，校验失败不产出成功文件 |
| bootstrap事件 | 用现有events和真实隔离Dagster运行登记；安排一次事件失败，再补余项 | 缺项前保持files_complete；已完成文件版本不变，补事件不请求源、不跑COPY，不伪造run，不逐文件启动补报run |
| 跨周/月handoff | 用受控时钟覆盖实际下载开始至选定已发布日，加入因子变化股/新股；仅补去重后的相关周期及对应两频历史 | 不重下其他已完成股票，不因停牌旧end_date扩大范围；文件/事件/水位未齐不ready；重复handoff不重置先进水位 |
| 日常job/check及原anchor待办 | 在同一新基线上运行现有两频真实asset job和三项blocking checks，随后核对/补记外层anchor事件待办 | 每项check必须绑定正确分区和实际目标物化；缺/错绑定不能冒记成功；其他股票/未选频率和未命中分区保持约定边界 |

测试仅使用/private/tmp根和隔离DAGSTER_HOME/instance（关闭遥测），localhost HTTP回放既有回包或独立字面夹具，显式21列并检查实际出站参数。组合路径不得用空成功回调、预置ready、伪造事件或替换HttpPage/run_period/handoff/execute_daily来跳过被验收业务链；只替换外部HTTP服务、时钟与正式资源边界，不新增生产测试参数。若以新进程验证CLI，记录本任务PID/PPID及退出/锁事实。已有字段、分页、空源、身份、前像、空间等正反用例不在组合场景中全部重做；按需求矩阵引用其证据。

**缺失成本测量。** 复用同一localhost路径，补记每页worker启动/初始化、限流等待、HTTP传输、解析/持久化和少量真实事件的调用数/耗时；文件、事件分别报告，并给出该小场景的实际总时间及阶段分解。文件阶段已有2599行/2207文件6.882秒、完成续跑0.107秒；相关路径未变且证据仍适用时不再完整回放，仅测新增或失效部分。记录SQL数、扫描/输出文件数、实际字节、spill及当前RSS，当前/历史峰值/进程树值不能混用。缓存命中、已完成续跑应证明无重复源请求/组装/改写；检查按准确文件版本复用，不能重算价格或扫描正式Lake来填性能表。

不重测Tushare连通性、不重新下载三股完整历史、不扩样本或大范围压测、不按单行探测耗时推完整历史。实测与对象数/请求量推算分开，§6.1的配额下界不变成ETA承诺。现行内存、并发、超时、预算均保持§6.2；样本未发现问题就不为“优化”重构进程粒度、批量事件框架或新增状态/开关。若测到具体异常，先保留profile并报告根因及最小修正，涉及新口径/配置/入口或扩范围时先确认，不自动放宽或收紧门禁。

**固定版本收尾。** 小修复只重跑受影响用例；版本固定后集中一次必要的周/月回归和隔离定义加载，核对保留资产/job/check/分区及sensor名称/状态口径，并做本任务catalog/治理断言、Ruff、文档完整性和差异检查。使用现有环境，不安装/同步依赖、不加载正式运行实例或重载code location。既有全仓治理的其他资产缺项保留原失败断言，在报告中列出基线与当前差异；本任务登记及定义必须通过，不把全仓历史缺项静默跳过或扩成其他数据集整改。

最终只交一张“已确认要求→实现位置→正反测试→适用版本证据→通过/未完成”表，注明行数来源，区分既有真实Tushare样本与本次localhost回放/字面夹具，列清源/准入/排除/写入事实、文件/事件/交接三类完成情况和实测成本，不能把回放写成本轮Tushare实拉。本节组合路径、旧入口拒绝及周/月自身治理缺项未关闭不能标Raw程序验收完成；不为填写表格再次请求源或扫描数据。正式挂载写盘支持、共享token实际配额、正式写者与部署边界留到另行批准的正式执行阶段，不拿隔离通过替代，也不在本阶段提前执行。提交依届时明确白名单，不推送；本轮已获准第6、7步开发，新冲突仍按确认门禁处理。

### 5.8 第6、7步交付与原对账（2026-10-16，日历漏项更正见§5.9）

修订文档已提交8ce4f252；本次提交收录第6、7步实现、测试及结果文档。第6步删除旧Prod库存/计划/预算、月线point及无生产消费者的整周/月日线上游状态模块；薄policy保留原时区、19:30和60秒，asset/job/check/分区名不变。现行21列schema前后逐项相等；月键、非法日期、20200228/29、Decimal/NULL、退役入口断言保留到新链。仅修正weekly asset/job与事件job过时说明。补本任务月线三项治理，周线三项原登记保留；全仓既有16个缺项减少为15个无关资产，不放宽断言或整改其他对象。catalog开始时内容及格式改动保留。

第7步新增tests/test_stock_period_integration.py，用三股独立字面源、localhost、真实HttpPage多进程、CLI和临时Dagster事件存储串起完整路径；未用替身跳过业务执行器。阶段数量如下；这些是小样本测试事实，不是生产限额：

| 阶段 | 源/准入/范围排除行数 | 请求及文件事实 |
| --- | --- | --- |
| bootstrap取消后续跑 | 8/8/0 | 4单页请求、4文件；取消后worker退出、锁释放，续跑保留原identity_hash及成功片段，不再清根或重下 |
| bootstrap事件失败后补余项 | 0/0/0 | 一次真实事件运行失败、一次补报完成；0HTTP/0COPY，文件版本不变，尚未handoff则仍files_ready |
| 跨周/月handoff | 20/20/0 | 8单页请求、6个受影响文件；只对因子股000001.SZ和新增股301569.SZ重下两频历史，920000.BJ不重下；重复handoff不请求、不组装、不改事件/水位 |
| 周/月日常与anchor待办补记 | 6/6/0 | 两频各1请求；同日再次进入month完成待办补记，0新增HTTP/SQL/文件改写；真实job各三项blocking检查准确绑定分区及实际目标物化ID |
| 最终物理结果 | 源合计34/准入34/排除0 | 两频共6文件/14行；旧仅键分区保留非目标股、目标股源已不返回的旧键移除，三套价格/NULL及end_date按字面预期保存 |

北交所始终请求920000.BJ，不请求旧832000.BJ。合并前源行含周期与完整历史的重叠，34不能直接等同最终14；精确一致的重叠行合并，更新与删除旧键由既有正反用例及本场景共同验证。全场景12次逐文件提交、6次COPY/6次批量导入，没有重复改写同批分区。

**2026-10-16当时关闭、现已发现修正不充分的问题（最新规则见§12.3—12.4）：** 首次两频job成功后，同日再次进入月线job补记anchor待办，当前run的PLANNED曾遮住此前已完成结果，读取evaluation.partition报错。管理员明确批准后，仅在stock_period_update.report_file_events的同分区limit=1查询增加Dagster已有COMPLETED_ASSET_CHECK_EXECUTION_RECORD_STATUSES过滤（SUCCEEDED和FAILED）；当时用例证明PLANNED不冒充完成；但按检查表ID取最新的规则仍会在实际完成顺序反转时选错，不能继续作为当前正确性结论，修复见§12.3。通过、blocking、分区、目标物化ID及文件版本门禁原样保留。新增5项真实隔离存储正反样本覆盖只有PLANNED、PLANNED覆盖成功、最新FAILED、错物化绑定、非blocking；原错误绑定用例继续通过。无API、CLI、配置、Dagster库或DB schema变化。旧失败现场/private/tmp/dg-period-step7-c/保留，不修改原manifest/hash续跑旧指纹。

固定当前版本155项周/月相关回归通过，包含5项原有进程退出/取消验证；55项第6步、12项开发中recovery及此前169/5等历史结果不累加为独立覆盖。显式隔离DAGSTER_HOME、已有venv执行dg check defs --use-active-venv通过；未加载正式instance或重载正式code location。自身6项治理通过，全仓治理原失败断言及其他15资产既有缺项保留；修改文件Ruff和DG src/tests的基础错误门禁、文档完整性及差异检查通过。

CodeGraph explore/impact结合当前import核对旧闭包与asset→update→history→source/raw、CLI/events/ops和测试消费者；动态调用及同名误匹配以当前源码补核。无Prod/前端/API消费者迁移，无业务子系统依赖矩阵变化。定义默认STOPPED不是正式sensor运行状态，本轮未改正式状态或cursor。

性能分解见§6.1。该轮逐项要求→实现→正反测试→适用版本证据及文件hash保存在/private/tmp/dg_period_step7_resume_1792129739381816000/acceptance.md，前一轮第6步/失败证据保留/private/tmp/dg_period_step67_1792127048786658000/。该轮曾判Raw程序隔离验收通过，后续发现六份日历夹具与真实上游不符，相关结论撤回；本轮补验与当前准入结论见§5.9，旧结果不冒充新版本验收。该轮真实Tushare新请求及全部正式操作为0，Silver未推进，R3继续暂停。

### 5.9 日历阻塞修复与第8步只读准入（2026-10-16）

根因是stock_period_update.py读取Silver日历时仍查询Raw字段cal_date，六份测试中的七处夹具重复了这一错误。实际生成器及正式文件均为trade_date DATE、is_open BOOLEAN。仅将calendar_days投影/排序和evaluate_daily_sensor当日筛选改为trade_date；不改日历生产者、源请求、Raw的21列、CLI、配置、预算或业务范围，不保留旧字段兜底。

| 要求/风险 | 本轮实现与证据 | 结果 |
| --- | --- | --- |
| 真实上游合同能接入 | test_stock_period_update新增真实silver_trade_calendar_select生成临时输入，独立断言四列类型、日期/布尔转换、SSE开市及休市范围 | 修复前缺cal_date失败，修复后通过 |
| 错误夹具不能再冒充Silver | 日历helper及两频sensor反测仅有cal_date；两频另测BOOLEAN false不调度 | 旧helper会误接受错误输入；修复后拒绝且不改cursor |
| 直接消费者不被漏修 | 六份夹具统一DATE/BOOLEAN及四列结构并注明依据；daily、两频sensor、handoff、实际job/check、事件失败/取消续跑共44项回归 | 本轮44项通过，13.80秒，不沿用155项宣称当前版本通过 |
| 真实文件读取 | 修复后calendar_days只读现有正式日历，覆盖13,162天、8,797个SSE开市日，末端2026-12-31；16:59时已发布截止2026-10-15，对应因子文件存在 | 通过；日历元数据未变，无正式写入 |
| 对象/新码范围 | basic和identity元数据与上一轮证据完全一致，复用5,576只上市股、350只北交所及活动旧码0的结论 | 未重扫对象池或旧行情，未请求源 |
| 挂载/空间/写者 | 两正式根同设备、非只读，约2.66TiB空闲；相关在途job及手动CLI均未发现，新链控制目录尚不存在 | 本次时点通过，执行边界仍须一次确认无冲突写者 |
| 定义与调度交接 | 正式code location仍为前一晚加载的旧定义；两个sensor仍RUNNING，周/月旧水位2026-10-09/2026-09保留 | 尚未部署修正，不能将源码通过当加载或正式执行通过 |

同一小型完整场景改用真实日历字段后实测4.606秒，14次localhost请求，最终6文件/14行、12次逐文件提交；重复handoff及anchor补记无新增请求或文件改写。该数字是本轮隔离回放，不是Tushare实拉或全市场ETA。旧源样本、未改变路径的文件性能及独立用例证据仍保留，不重新下载历史或运行2207文件性能样本。

完整证据在/private/tmp/dg_period_calendar_fix_p08_inic/：before_fix.xml记录四个预期失败；regression.xml记录本轮44项通过；performance.json为本轮小场景，step8_audit.json为16:59只读快照。首轮回归漏指定/private/tmp测试根且沙箱禁止localhost绑定的启动失败，保留于after_fix.log；随后修正测试启动方式，未放宽生产路径或网络护栏。Ruff、致命错误及文档/差异校验结果随本轮审计记录；不把启动失败隐藏或计为业务通过。

CodeGraph explore核验daily→calendar_days及handoff、sensor消费者，独立sensor SQL结合当前代码确认，变更后sync/status正常；不涉及Prod、前端/API或子系统依赖矩阵变化。其他未提交改动保留；catalog现有差异AST等于HEAD，已获准加载但未验收的R3模块继续暂停，不执行修复命令、不视为通过。

**结论：已知日历代码阻塞已关闭，可以准备并review第8步正式执行清单；不等于现在可直接删除。** 以本次白名单提交为基线确认加载范围，再在获准窗口加载验收版本并按原清单进行两根删除、bootstrap、事件和handoff；本轮不执行上述动作。当前相关写者为空只是审计时点事实，共享配额/实际窗口仍在正式清单确认一次，不重复审计行情。全部正式操作及真实Tushare新请求为0，Silver与R3不推进。

### 5.10 第8步正式执行及中断现场（2026-10-16，未完成）

管理员确认按执行清单推进第8步。执行基线ec9a33a0，当前DG业务代码与验收指纹一致；仅重载orchestrator，保留已明确允许加载但仍暂停/未验收的R3模块。重载前后两个sensor均RUNNING，旧周/月业务水位2026-10-09/2026-09及周线revision 1785保留。19:30后及20:20的真实tick均因新baseline未交接而SKIPPED，没有提交任务；本轮未启停sensor、未操作R3/Silver/Prod。

开工时basic与identity已被正常日常上游刷新，故不复用旧5,576数量。CLI实际固定5,577只上市股、351只北交所，全部北交所为确认新码，共11,154个股票×频率单元。沿既有DG HTTP环境与正式postgres instance执行；真实挂载、同设备、权限和约2.66TiB空间通过，无相关在途job或手动写者。未读取待删行情、未数旧行/价格、未做备份。

- request_id：dg-period-raw-bootstrap-20261016-ec9a33a0。
- 原run_id：5aa7ab8f3353957a0b9f53cc5794802340c0561ab9b1b26ced5be0013e0bb834。
- 原identity_hash：f4d98138e62d512c96a0e86804d3f6828934e0569b9da978ea712385f8510a10。
- 正式记录根：/Volumes/datasource/data_lake_staging/stock_period/runs/5aa7ab8f3353957a0b9f53cc5794802340c0561ab9b1b26ced5be0013e0bb834。
- 日志及控制面/诊断证据：/private/tmp/dg_period_step8_formal_hod_6is1/。

19:01:47开始apply，在既有写锁内完成两根删除后进入download。19:47在600487.SH请求三次超时后退出；已完成3,254份单元记录，2,390,833行成功页保留，worker退出且锁释放。随后按原参数和同run_id恢复，成功复用前3,254单元并继续到4,507单元；20:13再次在605028.SH请求三次超时退出，20:15原参数恢复仍以传输错误结束，无新增完成量。没有新开bootstrap、重删根、改原manifest/hash或放宽超时/重试。

截至20:24的停点：周线4,507个完整单元，月线0；成功页共3,350,241行，日志记录源行与准入行相等。当时尚未进入候选组装、逐文件提升、events或handoff，两个正式Raw根不存在，baseline未ready。这些源行只是已捕获片段，不是正式Raw交付行数，不能把下载进度写成第8步完成度。

最小诊断仅一次无token HEAD和一次失败单元同参数POST：DNS可解析，HEAD 0.079秒/HTTP200；605028.SH+week、limit6000、offset0、显式21列的POST在30.067秒发生ReadTimeout，未收到可记录的HTTP响应。它证明该数据请求未在现行30秒门禁内返回，不证明全站故障或已知具体源端原因；本轮不继续发试探请求。原执行仍为30秒、最多2次重试，未擅自调整配置。该诊断POST不是bootstrap成功receipt，不计入完成量。

管理员选择保留原参数、稍后沿同run_id续跑。20:41确认无遗留协调器、写锁释放、原指纹及policy未变后，通过resume继续，复用前4,507个完成单元，成功越过605028.SH；周线5,577只全部下载完成，共3,618,218源行/准入行、排除0行。北交所沿确认的920新码请求。20:58进入周线汇集后的分区COPY（stock_period_raw.py的PARTITION_BY(period)输出）时，execute监护读取当前RSS超过原rss_bytes=4,294,967,296，抛出period_process_memory_exceeded并中断SQL后退出。DuckDB memory_limit仍为3GiB，两者范围不同；本次没有记录超限瞬间的RSS数值或内部内存分配，不能据此断言具体分配根因。原最小样本通过未覆盖本次完整数据量下的COPY内存表现，不作为该边界通过证据。

当前安全核验：本任务协调器与worker均已退出，写锁释放，原identity_hash可验证；5,577份complete元数据与日志数量一致，月线0，无完整候选manifest、正式新Raw文件或事件，baseline未ready。可能产生的未完成候选也原样保留，未清理或重新运行。21:00只读核对两个sensor继续RUNNING、原水位不变，最近tick因bootstrap未交接而SKIPPED、run_ids为空。自动续跑dg-raw-8已暂停，证据为resume3.log、safe_stop4_memory.json及stopped_memory_control.json。

第8步仍未完成。该停点已汇报；管理员随后确认按§5.11先补方案并实施最小修正，完成隔离验收后报告。本轮不正式续跑，不自动恢复定时任务，不改原冻结policy/hash、不重做COPY或下载。Silver、Prod与R3不推进。

<a id="step8-memory-resume"></a>
### 5.11 第8步中间修正：执行RSS与下载身份分开（历史：首次修正与复测）

本节保留首次仅bootstrap resume的设计及验收记录。当前handoff覆盖准入以§5.14为准，最终正式结果见§5.15。

**根因与目标。** 3,618,218条周线源记录已成功保存，分区COPY因当前RSS超过4GiB主动中断，完整写出峰值未知。原实现把整个StockPeriodPolicy同时写入执行身份和源单元身份；直接改默认值不会覆盖resume加载的冻结值，改冻结policy又会使原身份失配或源单元换目录。只新增本次执行的RSS覆盖，不改既有身份算法，不迁移/重写5,577份完成记录。

**硬口径及实现点。**

| 要求 | 实现位置与行为 | 正反验收 |
| --- | --- | --- |
| 显式且仅本次生效 | stock_period_history_cli.py的resume接收`--rss-limit-gib N`，转换为runtime_rss_bytes；缺省None沿冻结值。只接已有bootstrap，正整数，无新增env/Settings/默认6GiB | CLI真实解析6；0/负数/非整数及其他action拒绝，不能出站或删除 |
| 原身份及成功源保持不变 | stock_period_history.py核验原manifest后沿原policy调用capture_unit，只把runtime_rss_bytes交给执行内存作用域；不得进入identity、hash、源参数或缓存键 | 制造COPY失败后用6GiB恢复：成功周线0次请求，仅首次下载未完成月线；原身份及已成功源文件版本不变；篡改原身份或片段仍拒绝 |
| 仅调整RSS门禁 | stock_period_raw.py按本次作用域选RSS额度，DuckDB及其他policy不变；既有SQL前/后及轮询继续检查，超限仍中断SQL并等其退出 | 字面5GiB采样在4GiB下失败、6GiB下通过；超过6GiB仍失败；DuckDB设置和源policy原样 |
| 运行之间隔离、取消恢复保持 | 当前执行退出时重置覆盖，其他线程/上下文及默认调用不读取此次额度；原worker、写锁、checkpoint和取消协议不变 | 正常、错误、取消后默认检查恢复4GiB；取消后可取得锁，完成源不丢失，恢复不清根 |
| 记录真正观察到的内存 | 既有JSON进度输出记录原额度、有效额度、最近采样RSS及采样最大值；超限原因码不变，失败进度附采样数值，不新增状态表或状态文件 | 校验日志数值及异常证据；采样值替身只证明门禁语义，另以真实本机RSS采样证明记录接线，不冒称精确连续峰值或完整COPY已通过 |

**配置审计。** 新参数的唯一入口为bootstrap CLI的resume；默认None，实际缺省额度取冻结policy.rss_bytes（本次4GiB），本次获准值6GiB。正整数GiB转字节，内部只接受正整数字节；不新增任意最大值。覆盖仅在当前进程内存，原值/有效值及采样保存在现有运行进度日志；再次续跑须重新显式传入，不从上次日志偷偷继承。消费者只有CLI、run_period和Raw IO的RSS检查；下载worker及HTTP仍接原冻结policy，DuckDB仍3GiB，日常job/sensor、events、handoff不新增参数。参数非法、非已有bootstrap或原身份失配时拒绝；超限继续安全退出。此参数是执行资源选择，不改变业务合同或Dagster定义。

**额外成本。** 复用现有SQL前后/轮询及单元边界RSS读取，只维护4个标量并附在既有SQL进度中，覆盖启用时另有开始/结束两条日志和一次初始RSS读取。不新增采样线程、SQL、Tushare请求或目录扫描；采样最大值只是观察值，不保证捕获两次读取之间的瞬时峰值。

**范围与验收顺序。** 生产白名单仅bootstrap/stock_period_history_cli.py、bootstrap/stock_period_history.py、io/stock_period_raw.py；对应隔离测试及原3份文档。不改run_contracts/stock_period.py默认或stock_period_source.py的身份/请求实现。先写缺陷回归并确认修正前失败，再实施、跑受影响测试及默认日常直接消费者回归，最后一次对账。临时根使用真实capture/assemble/publish及实际冻结记录格式，网络用明确替身，不写正式Lake/staging、不重载、不补事件、不启停sensor、不安装依赖、不推进Silver/Prod/R3，也不提交其他任务修改。

**后续恢复边界。** 正式续跑仍为原run_id的resume并显式附`--rss-limit-gib 6`，不能apply、重新清根或重下完成周线。本次周线COPY已完成，月线及后续阶段的6GiB足够性仍待实测；当前多片段bug须先按§5.12完成修复及隔离验收，再按获准边界继续，不再次盲目resume。若后续仍超限，保留源、候选及原指纹，按实际证据再决定，不能盲目宣称问题已彻底解决。

**中间修正开发交付对账（2026-10-16，正式复测前）。** 按先文档、后代码的顺序完成3个生产文件和新增test_stock_period_memory_resume.py；run_contracts/stock_period.py、stock_period_source.py及stock_period_update.py未修改，CLI保留原动作和默认值。CodeGraph explore/impact覆盖run_period、check_memory及日常直接消费者，随后sync/status索引已更新；不涉及Foundation、业务API、前端或Dagster定义变化。3项修正前回归预期失败后，受影响回归83项通过（11.03秒），再补实际history任务不接受覆盖的反例1项通过（0.85秒），共84项唯一通过用例，其中新增23项；不把两次重复执行的用例累加。

验收包括原4GiB失败、6GiB作用域通过、超过6GiB仍中断并等待SQL线程退出；真实CLI恢复小场景中完成周线请求0次、未开始月线首次请求1次、原源记录版本和身份不变，两频字面价格读回一致；取消后锁释放、恢复不再清根、覆盖退出后恢复默认；manifest/源片段漂移仍拒绝。门禁边界使用字面RSS替身，真实本机RSS采样另有接线测试，不声称实际占用5/6GiB或全市场COPY已通过。源码Ruff及格式检查通过，本地CLI help明确新参数。

该开发验收轮正式manifest的SHA-256和原identity_hash开工/收尾完全一致，正式phase仍为download；36份无关文件指纹未变。该轮无真实源请求、正式续跑、Lake/staging写入、重载、事件、sensor或R3操作，代码未提交；证据、XML及质量审计在/private/tmp/dg_period_rss_resume_5qj7vplt/。此开发及隔离验收已完成，不代表第8步完成，不能按下载单元50%推算整体完成度。

**正式6GiB复测及新停点（2026-10-16 21:49）。** 管理员确认继续第8步后，21:48一次核对原指纹、设备、锁、无相关在途写者及两个sensor状态/水位，随后用同run_id的resume显式传--rss-limit-gib 6。5,577个周线完整单元全部复用，新增worker及源页请求0；COPY完成，copy.json记录1,819个周期、3,618,218应有行。当前RSS采样最大4,384,522,240字节（约4.083GiB），越过旧4GiB且未触发6GiB门禁；这是本次周线执行的采样值，不保证月线或后续步骤峰值。

随后_candidate_receipts按单分区必须恰有一个Parquet的假设报period_candidate_file_count_invalid。只读核验首个异常分区1990-12-21的两个临时片段：data_0.parquet为1行、data_1.parquet为3行，合计4行、4个唯一键，日期均19901221、freq均week，与copy.json应有4行一致；此小样本不代替全部候选验收。根因是本代码的COPY产物与后续接收假设不一致；不能简单取第一片、漏行或放宽正式单文件合同。当时尚未改代码；后续复用成功COPY的修复、隔离验收及对账见§5.12。

本任务进程均退出、锁释放；原identity_hash仍为f4d98138e62d512c96a0e86804d3f6828934e0569b9da978ea712385f8510a10。源片段、完整COPY/片段、copy.json和日志全部保留。月线未开始，两套正式Raw根仍不存在，事件/handoff未执行，不继续盲目resume。证据为/private/tmp/dg_period_step8_formal_hod_6is1/resume4.log、safe_stop5_candidate_count.json及candidate_count_diagnostic.json；自动续跑仍未恢复，Silver/Prod/R3未推进。

<a id="step8-candidate-fragments"></a>
### 5.12 第8步中间修正：临时多片段归并为单文件候选（历史：开发验收，正式执行见§5.13、§5.15）

**位置与根因。** 错误发生在周线源下载完成、分区COPY成功之后，候选receipt生成之前。io/stock_period_raw.py的assemble使用COPY PARTITION_BY(period)，同一目录可能由多个线程写出多个Parquet；_candidate_receipts却以len(outputs)==1作为前提。DuckDB[分区写出说明](https://duckdb.org/docs/current/data/partitioning/partitioned_writes.html)明确说明每线程可向同一分区目录写文件。一个协调写者不等于DuckDB内部只有一个输出线程。不能把这个错误归为源异常，也不通过调成单线程、只取第一片或允许正式分区多文件来掩盖。

**已知证据与缺口。** 1990-12-21两片分别包含600601.SH，以及600602.SH/600651.SH/600654.SH，合计4行、4个原始业务键，与copy.json应有4行相符。只核对了这两个小文件，未全扫1,819个分区；其他分区的片段数量和归并成本尚未实测。此前稀疏样本没有验证实际多片段输出，已有通过结果不覆盖本缺陷，更不能当成修复后验收。

**目标与硬口径。** 输入允许一个分区有多个临时片段，正式输出仍为周线part-000.parquet、月线data.parquet各一份；保留全部21列、Decimal/NULL、源trade_date/end_date及业务键。归并仅拼接本次COPY已产出的行，不执行去重、版本择优、价格重算或旧数据补洞。跨片段同键重复即使数值相同也按候选唯一键门禁拒绝，不靠DISTINCT消除错误。日常输入重叠的业务合并仍在原combined阶段完成，不移到本步骤。

**开发顺序及落点。**

1. **先证明回归。** 在临时根用独立字面21列样本重现“1行+3行应为4行”，确认现有接收代码失败；另经真实DuckDB、现有两线程partition COPY得到实际多片段并断言产物，补足生产者—消费者边界。人工构造双片可用于单元反例，不能冒充实际并行COPY证据。不请求Tushare或使用正式Lake/staging作测试输入。
2. **在现有候选接收处归并。** assemble已有copy.json时继续核对原assembly identity并直接进入候选阶段，不导入CSV、不重建combined、不重做全频率partition COPY。枚举各period已有片段：无文件拒绝；单片直接复用原路径；多片用同一DuckDB连接读取该分区的明确文件清单，hive_partitioning=false，将完整21列原样COPY到work/merged/<period>.parquet。新候选放在outputs之外，避免续跑把归并产物再次算成输入；原片段及copy.json不删、不改。既有合法零行候选的语义保留，无文件不能冒充合法空候选。
3. **扩展现有分区checkpoint，不另建状态系统。** 复用work/validated/<period>.json，内部补充该分区片段路径集合及file_version、归并输出版本和阶段。多片先记录输入绑定，归并写入临时文件、fsync并原子完成后记录“已归并、未校验”；只有批量检查及expected_rows对账通过才写现有item/receipt_hash成功证明。无成功item的中间记录不能用于发布；item的正式交付字段和receipt_hash=digest(item)保持原义。单片沿用原路径及验证复用。读取处显式识别阶段，残缺或矛盾记录拒绝，不能默认为成功。
4. **沿用批量校验，补跨片段风险。** 在现有批量schema查询中一并检查待验原片段和最终候选的21列/顺序/类型，避免SELECT投影或隐式类型转换掩盖输入错列；按实际路径去重，不逐片或逐分区新增schema查询。现有候选facts聚合在归并后的整分区检查原始键唯一、freq、日期合法性和分区归属，行数须等于copy.json的expected_rows。仅逐片唯一不能证明跨片唯一。先对账再写成功checkpoint，不能先标validated后才发现丢行。保留原目标前像、版本和逐文件原子发布合同，不另算源价格或读旧Lake对比。
5. **恢复只续缺项。** 以既有copy.json、片段清单/版本及候选版本判断复用；本任务已校验且未漂移的候选不再归并、hash或读行。只有归并完成的复用该文件、仅补未完成校验；中断的归并只重做该未完成分区。额外片段、缺片段或版本变化拒绝，不悄悄改绑定、重写原计划或覆盖未知输出。归并完成但阶段记录失败时，仅对该分区按已绑定输入作必要恢复核验；能证明完整对应才补记，否则保留现场报告，不能把文件存在等同成功。完整成功记录写入后，正常续跑只查版本。

**文件白名单与影响面。**

| 文件 | 计划落地内容 |
| --- | --- |
| orchestrator/src/orchestrator/defs/io/stock_period_raw.py | _candidate_receipts的片段发现、必要归并与checkpoint复用；_validate_candidates批量检查输入及最终文件；行数通过后再写成功证明 |
| orchestrator/tests/test_stock_period_candidate_fragments.py（已新增） | 独立字面金样本、真实partition COPY多片段、跨片拒绝及计数/恢复测试 |
| orchestrator/tests/test_stock_period_history.py；test_stock_period_raw.py只回归、未改动 | 原run_id候选恢复新增直接组合断言；既有bootstrap/upsert/history断言继续回归 |
| 总方案、共享LLD、月线LLD | 中间步骤、单文件合同、取消恢复、验收及实际状态一致 |

CodeGraph explore/impact已覆盖assemble→_candidate_receipts→_validate_candidates，以及bootstrap的run_period；当前代码引用核验补充日常stock_period_update的assemble消费者及checkpoint测试。validated目录只在Raw IO内部读取，候选item供协调器及publish消费，不能把新增中间阶段泄露为可发布item。影响限于共用周/月候选IO及其bootstrap、日常upsert、历史刷新直接调用；无Foundation/Prod/API/前端或依赖方向变化。CLI、源请求、policy、assets/jobs/checks/sensor/catalog不在修改范围，事件阶段不执行归并；开发若发现必须改此边界，先报告确认。

**性能与资源。** 单片分区额外COPY为0；多片分区每个只新增一次必要的本分区归并，已完成续跑为0。源请求、CSV导入和全频率partition COPY重放均为0。沿用单连接、现有SQL取消/进度/空间预留及增量计量，登记归并临时文件与原片段共存占用；必要写入前检查实际剩余空间，不递归重扫Lake。原DuckDB3GiB/2线程、执行RSS显式6GiB、spill16GiB/workspace32GiB不变，不新增并发、批次、耗时门禁或配置。使用既有进度字段报告真实归并/校验完成量，未完成COPY不能伪报已完成；取消要中断SQL并等执行线程退出、释放锁，不领取新分区。

成本模型为“待归并分区片段总字节的读取+单文件写出+未完成批量校验”，不再包含完整下载或全源重新组装。下方已有新实现小样本测量，但未测正式1,819个分区的归并成本，不承诺未经测量的分钟数，不为每次小改重跑数小时全链。

**正反验收与取消恢复。**

| 验收项 | 正向及必要计数 | 反向/拒绝条件 |
| --- | --- | --- |
| 真实多片段与完整行 | 两频均覆盖单片和多片；独立字面1+3=4金样本逐列读回，合法NULL/Decimal保持；实际两线程COPY多片最终仅交付一个正式文件 | 不得只取第一片、只解除数量断言或改成单线程来通过；额外/缺失/错类型列拒绝，不能投影丢列后通过 |
| 键、范围、行守恒 | 周期归属和expected_rows一致；月线20200228/29作为不同键同月均保留；保留合法零行历史替换 | 跨片相同/异值重复键、错freq/日期/分区、缺片导致行数不符均拒绝，且不产生成功证明或提交 |
| 取消/退出与复用 | 归并前、SQL中、归并后未校验、部分校验完成各停一次；本任务执行线程退出、锁释放，已成文件和原证据保留；resume只续缺项 | 不能留下旧SQL写者、未完成文件不能发布；片段集合/版本或候选版本漂移、坏checkpoint拒绝；取消后不领取新分区 |
| 写入/记录失败 | 归并已完成但记录失败按本分区证据补记；正式replace后记录失败沿原合同读回补记 | 路径越界/符号链接、空间或RSS超限、目标前像漂移仍拒绝；不覆盖未知文件、不把中间阶段当files_complete |
| 无重复工作/直接回归 | 成功源零重下；copy.json命中时import_source及partition_copy为0；单片零归并、已归并零重写、已校验零重复验证；bootstrap/upsert/history及发布读回保持其他股/未选频率 | 不能每分区重读全部源、重写单片或重复全频率COPY；事件补报不能归并/COPY，不把旧版本通过结果当新验收 |

先补缺陷回归并确认修复前失败，修复中只跑相关项，版本固定后集中一次必要直接回归、记录未覆盖项并按上表对账。隔离验收仅使用临时根和替身。本轮修复及隔离验收已完成，不正式resume、不恢复自动化、不删除或改写原现场。后续按获准边界沿原run_id/identity_hash、原请求参数及--rss-limit-gib 6继续：先复用周线COPY完成候选，再首次下载月线，继而两频文件发布、events及有界handoff。不得将旧RSS修复的84项或4行诊断冒充此次归并修复通过，Silver、Prod、R3继续不推进。

**开发交付与逐项对账（2026-10-16）。**

| 硬口径 | 本轮实现与证据 | 结果 |
| --- | --- | --- |
| 全片段、正式单文件、字段不变 | _merged_candidate只对多片做本分区COPY；周/月1+3=4独立字面金样本逐列读回并原子发布；20200228/29不同键均保留 | 隔离通过 |
| 不以归并掩盖错误 | _validate_candidates一次schema查询覆盖原片及最终候选，整分区facts检查唯一键/日期/范围；expected_rows通过后才存成功item | 缺/多/错类型列、相同/异值重复键、错freq/日期/分区、缺片/行数不符及合法零行正反通过 |
| 同版本复用、不重算源 | 单片继续原路径，多片使用merging/merged/validated三阶段的原分区checkpoint，proof_hash绑定内部证据；对外item/receipt_hash不变 | 成功候选恢复零SQL/零hash；partial validation只读剩余文件；已归并未验候选不重写 |
| 保留身份与已下载源 | assemble命中原copy.json直接进入候选；协调器组合用真实capture/assemble/publish，明确注入一个空Parquet片段触发恢复分支 | 取消后原身份、源CSV及周线copy.json不变；周线零新增请求/导入/COPY/归并，月线只做首次请求，不能冒充实测正式源 |
| 取消、记录失败与保护 | 既有execute中断真实DuckDB COPY并等线程退出；writer释放；归并rename/记录缺口仅比较本分区完整行多重集，成功后补记 | 归并前/SQL中/归并后/部分校验取消通过；原片或候选漂移、未知输出、越界链接、workspace/free/RSS拒绝；原生进程TERM退出已有直接回归通过 |
| 范围与版本 | 本次片段修复生产改动仅Raw IO；此前§5.11的CLI/协调器/RSS及test_stock_period_memory_resume.py一并提交；原3份文档同步 | 不改HTTP、默认policy、资产/调度、Prod/API/前端或依赖矩阵；无正式操作，Silver/R3暂停 |

缺陷修复前周/月多片段、真实COPY多片段及行数失败提前标成功共4项回归失败，保留XML。最初单分区稀疏夹具仅产出一片，不能覆盖缺陷；最终真实COPY测试在隔离连接用flush_threshold=2048、max_open_files=1提前触发缓冲刷新，DuckDB仍为3GiB/2线程，未改变生产默认524288/100。实际30片段分属2个周期、共30,000行；手造两片只作另列金样本，不混称真实并行产物证据。

固定生产版本的12个直接测试文件144项通过（15.60秒）；审计补充4项空候选/无文件及归并期间漂移正反用例通过（0.40秒），合计148个唯一用例。其中本次新增36项片段测试和1项协调器恢复测试；旧RSS的23项也在本轮回归，不再叠加此前84项数量。Ruff和格式检查通过；CodeGraph explore/impact分析后sync/status已更新。证据：/private/tmp/dg_period_fragment_fix_1bah6ldo/的final.xml、audit-extra.xml及各缺陷回归记录；详细硬口径映射与改动边界审计见同目录audit.md。

该固定版本真实小样本源CSV3,540,161字节，30片Parquet共328,229字节，2份最终候选共187,562字节；组装/归并/校验0.243秒，完成恢复0.028秒且SQL为0。首次import_source/partition_copy各1次、必要candidate_merge 2次、candidate_schemas/candidate_facts各1次；观察到的当前进程RSS采样最大319,520,768字节，非连续峰值。此样本使用上述测试专用刷新设置，不外推正式1,819分区耗时或6GiB足够性；测量见final/test_real_parallel_partition_c0/performance.json。源片和候选共存按现有预算增量计量，无新增配置或递归扫Lake。

本轮隔离执行移除DAGSTER_HOME和TUSHARE_TOKEN，使用临时根、替身和独立instance；真实源请求、正式Lake/staging写入、重载、正式事件、sensor及自动化操作均为0。原第8步仍暂停，未进行正式归并/下载/发布，因此不能据此标记基线ready或第8步完成。


<a id="step8-handoff-memory-stop"></a>
### 5.13 第8步正式续跑：两频文件与事件完成，交接RSS门禁停止（历史停点，2026-10-17凌晨）

本轮沿73e48cfa已验收实现、原父run_id及identity_hash，以resume --rss-limit-gib 6续跑。5,577个周线成功源单元及原copy.json全部复用，周线无新增下载请求、无重新导入或全频率partition COPY；必要多片段归并及1,819分区校验通过。月线5,577单元为首次下载，431分区全部校验通过；两频成功源11,154单元，源行与准入行均4,486,908，无范围排除。退市不请求及北交所新码准入沿冻结身份执行。

| 频率 | 正式文件 | 交付行数 | 物化/检查完成文件 |
| --- | ---: | ---: | ---: |
| week | 1,819 | 3,618,218 | 1,819 |
| month | 431 | 868,690 | 431 |

日志单次汇总确认：月线实际请求代码集合与冻结5,577只上市集合完全相同，351只北交所均为920新码；本轮源worker5,577次，均属于月线首次下载。源导入与全频率partition COPY各1次、仅月线；必要片段归并为周线1,721分区/月线97分区，其余单片未重写。此为resume5日志证据，不含另列handoff的合法增量请求。

全部文件按既有原子提升及checkpoint完成。独立events动作只补事件，真实补报运行660d0b44-9a38-4a6f-bcf9-edee05e7687d为SUCCESS，父phase=events_complete。恢复过程RSS采样最大4,054,351,872字节（约3.78GiB），只代表本次恢复采样，不能证明交接预算。事件的控制台未持续输出时仅做一次有界定位，并按已有完成checkpoint观察进度，没有重复启动或重算行情。

**交接范围与停点。** handoff按原规则冻结2026-10-15—2026-10-16捕获区间，只处理周2026-10-16、月2026-10及45只因子变化股票，没有退市/换码差异。子run_id=6452ece7da82a812650dad7df67dc7dfae893deb45fd0e4f7e4d07c2ad1e7d64，identity_hash=e1894fbd543a474315f1c11e5e1d800fbfa5f981b08ca65d094d66d204496cf8。周线46个单元（45股历史+当周全市场）、36,375行均捕获成功；候选阶段复用已有范围定位到1,671个周分区，按频率一次读取/组装，partition COPY期间抛出period_process_memory_exceeded。周线COPY无成功copy.json，交接提交0；月线子任务尚未开始。

这是§5.11资源覆盖没有接到后续handoff的范围缺口：现有CLI只允许bootstrap resume显式覆盖RSS，handoff子upsert仍受冻结4GiB约束。不能在handoff直接加现有flag、修改原policy/hash或套外层脚本绕过门禁。交接具体峰值未记录，不补造数值。真实交接运行0c5480e0-cf1b-4a77-b8b4-32f71378ecc8为FAILURE。

**安全核验与剩余工作。** 父2,250正式文件版本逐项与完成receipt一致，父事件完成记录齐全，原identity_hash仍为f4d98138e62d512c96a0e86804d3f6828934e0569b9da978ea712385f8510a10；本任务协调器及记录的worker全部退出，writer.lock释放。两个sensor仍RUNNING、周/月旧水位2026-10-09/2026-09及revision1785保留，自动化dg-raw-8仍PAUSED。本轮不重载定义、不改代码、不操作Silver/Prod/R3。基线files_ready、handoff_complete=false，不能把物理重建与父事件完成写成日常交接或第8步完成。

管理员已确认：45只跨日因子不同的股票统一重新下载两频历史，不再逐股判断原下载是否已经包含更新；同时批准6GiB覆盖扩展到本次收尾补更。相邻日因子不同不等于下载后源又发生变化，这是明确采用的保守刷新规则。按§5.14先完成最小修正和隔离验收，再复用父两频成果与46份成功周线源续跑；不重做父bootstrap，不改旧指纹。

完整证据在/private/tmp/dg_period_step8_formal_hod_6is1/：resume5.log、resume5_files_result.json、events1_result.json、handoff1.log、safe_stop6_handoff_memory.json、stopped_handoff_control.json及resume5_report.md；原报告与日志均保留。已核对本轮3个运行文件指纹与开工一致，原3份文档只更新真实状态，未提交。

<a id="step8-handoff-memory-resume"></a>
### 5.14 第8步中间修正：收尾补更沿用显式6GiB（2026-10-17已批准、隔离通过）

**目标与范围。** §5.11原范围只覆盖bootstrap resume；本节将同一个可选参数扩到已有、绑定原bootstrap父任务的handoff子任务。CLI的handoff接收`--rss-limit-gib 6`，stock_period_update.handoff_bootstrap传给run_period；不改变默认4GiB、DuckDB3GiB/2线程、HTTP30秒/2重试/280次每分钟、分页、空间及业务合同。events、apply、prepare、日常upsert及主动history不能借此覆盖。原父子run_id、policy、identity_hash和源单元身份保持不变，不新增配置来源、状态表或执行框架。

**准入与失效。** 协调器只在显式覆盖时额外核对已有子manifest；bootstrap仍仅限已有任务。handoff子任务必须是upsert，bootstrap_parent是合法任务ID，父manifest身份有效、mode=bootstrap、phase=events_complete，根/policy与本次一致；父已冻结handoff的intent、listed、aliases与子执行身份完全一致，baseline仍绑定该父任务且为files_ready或ready。缺少绑定、漂移、普通日常请求即拒绝；原子任务身份及源片段校验继续执行，不能仅凭一个bootstrap_parent字段放行。覆盖只在run_period执行作用域生效，退出恢复默认；超限仍中断并等待SQL退出，锁和worker保护保持。

**恢复与必要工作。** 父2,250正式文件及事件全部保留，46份完成周线源不再请求。失败周线COPY没有完成记录，其私有未完成build按现有规则重建，不把半成品当成功候选；下载源与完成记录不清理。继续周线未完成组装、月线45股历史及当月首次补取、两频文件原子提交、相关事件及截止点登记，最终baseline=ready/handoff_complete=true。不再做第二套因子探测或扩大截止区间；使用已冻结2026-10-15—16及45股。sensor运行状态和旧cursor不改，Silver、Prod、R3不推进。

**配置审计与成本。** `--rss-limit-gib`来源仍为现有CLI显式参数，默认None沿原冻结值；正整数GiB换算字节，实际额度和采样最大值写原进度日志，不写入policy/hash或自动继承。新增消费者仅handoff_bootstrap及run_period的父子绑定核验；下载worker不接新参数。核验后以现有作用域覆盖handoff预检和子协调器，正常/异常退出均恢复默认，不新增采样机制。父子核验只读少量既有JSON，不增加行情扫描、SQL或源请求。现有周线46单元/36,375行复用；月线预计46单元，页数按完整分页合同，不将单元数冒称HTTP请求数。旧数据仅按已有范围索引选中的受影响分区一次读取/组装，原空间门禁和逐文件提升不变。6GiB足够性由本次正式执行实测，不先承诺峰值或耗时。

**验收与执行顺序。** 生产文件白名单为stock_period_history_cli.py、stock_period_history.py、stock_period_update.py；测试仅RSS及直接handoff消费者，文档为原三份。先证明旧实现不能接收handoff覆盖，再补5GiB/6GiB/超6、默认隔离、非法action、普通日常拒绝、父子绑定/源漂移拒绝、取消锁释放与成功源复用。临时根中使用真实CLI、候选/原子提交和隔离Dagster instance，源与RSS用明确替身，不用正式资源做测试。通过后从orchestrator目录沿原父run_id执行现有handoff并显式6GiB，新日志另存handoff2.log；不重新resume父bootstrap、不apply、不清根。执行结束以现有receipt/checkpoint、一次文件元数据集合对账及少量真实登记样本验收，不重下成功源、不全量源比对或重新计算行情。自动化保持暂停至任务完成后停用，不反复盲目重试。

**本次开发验收。** 两项修正前回归分别因handoff不接收内部额度、CLI拒绝handoff参数而失败。修正后82项唯一用例通过（81项文件/状态/RSS测试，1项localhost真实worker/CLI/两频job组合）；其中RSS值为字面替身，不声称实际分配5/6GiB或正式COPY通过。真实CLI在临时instance中成功登记、重复handoff无新请求/SQL/改写，源/父子身份漂移、超限、普通调用和取消恢复均覆盖。CodeGraph explore/impact及sync/status完成；修改限三生产文件、两测试和原三文档，不涉及API/前端/跨域依赖。证据在/private/tmp/dg_period_handoff_rss_itmzbj6b/（before_fix.txt、final.xml、http.xml、constraints.md）。初次测试临时根落在系统TMPDIR被路径门禁拒绝，已改用获准/private/tmp；localhost测试首次被沙箱端口权限拒绝，改用本机权限后通过；均不作为生产缺陷或额外通过数。

<a id="step8-complete"></a>
### 5.15 第8步完成与最终对账（2026-10-17 12:01）

**正式结果。** 按管理员确认的45股统一刷新及6GiB扩展，通过82项唯一隔离用例后，从orchestrator现有.venv运行原父run_id的handoff --rss-limit-gib 6，正式DAGSTER_HOME不变；未重新resume父bootstrap、不apply、不清根。真实Dagster运行4c226259-130b-4864-b0b7-fa4a720f3a04为SUCCESS，CLI退出0。父phase仍events_complete、handoff_complete=true；子phase=events_complete，baseline=ready，交接截止2026-10-16。父run_id/identity_hash和子run_id/identity_hash完全保持§5.13原值。

| 对账项 | 实现/已有证据 | 本次结果 |
| --- | --- | --- |
| 45股两频统一刷新 | handoff冻结intent；run_period/capture_unit/assemble | 两频均包含同一45股完整历史，不另审计原下载是否已最新；本轮新增的46个HTTP worker/46页全部为month，week完成源46单元均复用、完成记录版本及hash不变 |
| 源与落地范围 | 原21字段/完整分页/上市与BSE新码准入保持；已校验候选receipt | 收尾week源/准入36,375行，month源/准入12,952行；两频含各45股历史和一个当前周期单元，无范围扩大或源缺口 |
| 文件一次组装与逐文件提交 | 原范围索引、批量assemble、候选校验、publish/checkpoint | week更新1,671文件，month更新397文件；各文件仅一次提交。两频最终1,819/431文件、3,618,218/868,690行，合计2,250文件/4,486,908行；未命中182文件版本未变 |
| 6GiB执行覆盖、原身份不变 | CLI→handoff→run_period的准入和RSS作用域；正反测试 | 冻结RSS仍4GiB，显式上限6GiB；日志采样最大4,373,872,640字节（约4.07GiB，非连续精确峰值）。DuckDB仍3GiB/2线程，原HTTP30秒/2重试/280每分钟及空间预算不变 |
| 物化与blocking checks | replay_events/report_file_events；child事件checkpoint | 2,068个修改文件事件完成记录齐全并绑定最终版本；抽查周2026-10-16、月2026-10，各三项真实blocking检查通过且绑定本次实际物化和成功运行。不重扫行情或重算公式 |
| 截止点与日常状态 | 原handoff末尾状态更新 | factor_through与两频last_refresh为2026-10-16；completed_through为week=2026-10-16、month=2026-09，10月只刷新到16日，不冒记整月完成 |
| 写入隔离与退出 | 写锁、原任务worker监护、原子提交、一次元数据对账 | 最终文件集合和版本与父/子receipt合并结果完全一致；本任务无存活协调器/worker，锁已释放；运行期间四个执行模块指纹未变 |
| 调度与阶段范围 | 正式sensor只读状态、原cursor对照 | 两sensor仍RUNNING，cursor业务水位保持week=2026-10-09、month=2026-09及原revision1785；未重载、启停或重置。自动化dg-raw-8仍PAUSED（已停用），不另开启或重复触发。Silver、Prod、R3未推进 |

**验收边界。** 82项是本版本隔离回归，不重复累加旧修复的148项；RSS门限用字面采样替身，真实6GiB足够性由上述正式执行证明。最终核验只合并已有完成receipt和新事件checkpoint、做一次2,250文件元数据集合/版本对账及两个分区真实登记抽样，没有全量源比对、重复下载、Parquet内容深扫或重复公式计算。不存在待补正式事件或handoff步骤；第8步独立关闭，Silver仍待后续批准。

**改动与证据。** 本次代码仅stock_period_history_cli.py、stock_period_history.py、stock_period_update.py；测试为test_stock_period_memory_resume.py、test_stock_period_handoff_memory.py；原三份方案/LLD同步。CodeGraph explore/impact分析到CLI→handoff→run_period及日常直接消费者，未改资产key、API、字段、跨域依赖或R3模块。静态/Ruff/格式、文档完整性及本任务diff检查通过。其他任务文件未被覆盖、提交或回退；工作区存在并发的其他任务修改，保留现场。

正式日志/private/tmp/dg_period_step8_formal_hod_6is1/handoff2.log；本次开发及收尾证据/private/tmp/dg_period_handoff_rss_itmzbj6b/：before_fix.txt、final.xml、http.xml、before_handoff2.json、final_audit.json、final_audit.log、constraints.md及step8_final_report.md。旧中断报告/日志保持追溯用途，当前事实以本节为准。本轮实现和文档按上述白名单提交，不推送；提交结果以Git记录为准。

## 6. 配置与性能依据

### 6.1 保留已有证据，补真实路径成本（纠偏12）

三股000001.SZ、920000.BJ、301569.SZ两频历史已存/private/tmp/dg_period_raw_a_20261016/：6单元/7次HTTP请求，2599行、391121响应字节；老股周线1000+782，月线427行，北交所310/78，新股1/1。请求耗时合计1.524秒。该样本使用先前探测客户端，不是最终DG执行器性能。

A阶段同批CSV导入/COPY/统一读回0.035/0.763/0.676秒，2207文件、7161521字节，峰值1190117376字节，无spill；只说明稀疏样本组装成本。中间实现缓存回放2599行/2207文件6.693秒，完成续跑0.446秒、峰值994492416字节，含每频导入/COPY和2207次候选查询；不含网络、最终worker及事件，且不是固定纠偏版本。两类证据不得混称全链通过。

第1、2步交付版本复用上述7个完整源回包，2599行/2207临时文件，组装及文件流程4.109秒，完成续跑0.457秒；每频import_source、partition_copy、candidate_schemas、candidate_facts各1次，两频合计各2次，恢复不重取源、不改写版本。输出6871878字节，独立样本进程ru_maxrss为994492416字节；不是当前RSS或进程树峰值。无外部网络、无正式事件，localhost HTTP进程另由4项用例验证；不将此耗时外推全市场。报告：/private/tmp/dg_period_raw_impl_sample_20261016_1792116025721975000/performance.json。

N=5576是已留存对象快照，不重新审计全市场。单元行数r时请求数floor(r/6000)+1（含整倍数空末页），不足6000的基准2N=11152次。假设额度280次/分钟且仅本任务占用，配额理论下界约39.8分钟，不能当耗时预测。先前1—3小时估计缺进程启动/初始化、限流、解析/持久化和事件成本，撤出执行承诺；目前完整任务ETA待真实路径小样本校准，不重新套用2—5秒假设制造另一组小时数。

第7步按§5.7只补缺失成本：localhost替身经过真实DG HTTP执行器，计worker启动、限流、传输/持久化和少量事件，已有文件/恢复性能证据适用时不再完整回放。无需重下三股全历史或重复测源连通。确有真实协议变化且已有证据不能覆盖时，先说明差异及最小源验证需求，不擅自新增请求。进程粒度不预先强制改变，也不为补测自动新增实现。

**第7步固定版本小场景实测（localhost字面源）：** 从CLI apply开始至最终读回4.455秒，包含受控取消续跑、一次事件失败补报、跨周/月handoff、两频job/check及同日anchor补记；不含夹具和instance初建。14次真实worker请求/34源行；HTTP父调用合计2.769秒，其中worker启动报告至替身收到请求1.694秒（包含子进程初始化/本机传输）、实际限流等待0.923秒、本机服务处理0.00255秒。源解析0.00189秒、回包持久化0.01044秒；52次被观测的顶层事件报告调用合计0.368秒（去除嵌套计时，非全部Dagster日志事件数）。单场景SQL94次/0.154秒，其中import/COPY各6次、read_affected_once4次；source_integrity等校验计入，不重算复权价格。

最终6个Raw文件19191字节/14行；测试根与staging一次有界元数据清点142文件/140634字节，运行内增量计量观测最大82075字节。SQL边界抽样当前RSS最大400490496字节（约382MiB），不是全程或进程树峰值；最终边界残留spill为0，不据此声称瞬时spill峰值。重复handoff0.000864秒，同日anchor补记0.213秒，均无新增源请求/SQL/文件改写。完整分解见同证据目录performance.json和performance_summary.json；测量包装器调用原实现，不新增生产观测参数或降门禁。文件2599行/2207文件的6.882秒及续跑0.107秒证据仍只复用其未改变的文件路径，未重新完整回放。

**推算边界：** worker本机初始化均值约0.121秒/请求；完整bootstrap下载时间仍取决于实际Tushare响应、页数、重试和共享配额，不能把localhost服务时间当远端时间。请求成本模型至少包含启动、远端HTTP、限流、解析及持久化；只保留11152请求/280每分钟的39.8分钟理论配额下界，不承诺全市场ETA，不新增并发或预算配置。

### 6.2 专项配置审计与预算（纠偏1、9）

本表为当前专项配置基线；前五步已实现DG局部HTTP配置、脱敏有效值、冻结身份、同policy透传和累计预算/当前RSS保护，证据见§5.4—5.5。第6步仅清理无消费者旧配置，第7步补缺失成本；第8步中间修正按§5.11增加显式执行RSS覆盖，并按§5.14扩到已绑定的handoff续跑。数值属于实现选择，非用户业务硬上限；需变更时先给测量依据并更新本表，不散落多个默认。冻结配置仍由父进程解析后传给HTTP/分页、DuckDB及恢复消费者，非敏感值保留在原manifest；新增RSS覆盖仅用于本次执行监护、有效值写既有进度日志，不进入原manifest、policy或下载身份。续跑不得静默换policy或改旧指纹；凭据轮换不写进任务身份。

| 配置/默认 | 来源、持久化与作用域 | 依据、失败与验收 |
| --- | --- | --- |
| TUSHARE_TOKEN，无可用默认 | DG现有EnvVar/进程环境，CLI继承；仅父进程内存传worker，不落manifest/日志 | DG现行接线；空值在请求前拒绝，不查Prod配置文件 |
| TUSHARE_BASE_URL，https://api.tushare.pro | 此两Raw新接入同名环境参数；DG source局部配置入口集中默认，记录安全有效地址；不是声称DG旧SDK已有该配置 | 默认仅参考Prod；显式地址覆盖、独立进程可运行，不import Foundation；不改其他资产 |
| TUSHARE_MAX_CALLS_PER_MINUTE，280 | 同上，仅本专项HTTP限流；按DG实际环境解析，持久化有效非敏感值 | 参考既有Prod默认，不代表DG已测共享总配额；覆盖值为非负整数，0沿既有客户端含义表示本执行器不追加间隔，不能因此宣称源端无限配额；非法值拒绝，其他同token任务额度影响正式前一次确认 |
| page_limit6000；response16MiB；unit128MiB | StockPeriodPolicy及manifest，源分页/有界回包/完整单元共同消费 | 样本约155字节/行，6000约0.9MiB；16MiB留余量，128MiB非历史行数上限；超限保留有界证据，不静默截断 |
| 并发1、单次总期限30秒、重试2次、退避1/2秒 | 同一policy传监督器；运行级请求间隔贯穿worker生命周期 | 当前保守起点，真实路径样本后再评估进程粒度/并发，不无依据另加紧上限；网络重试有界，合同错误不重试 |
| DuckDB3GiB、threads2、spill16GiB；RSS4GiB观察阈值 | 同一policy传所有SQL/验证/监护，spill仅本次staging | 已有稀疏样本峰值约1.11GiB，非全市场证明；3GiB在允许范围内，4GiB不是DuckDB或进程树等价值；当前进程RSS、历史高水位和worker占用分清，不用共享进程旧峰值冒充本次超限 |
| resume/handoff的--rss-limit-gib，默认None；本次显式6GiB | CLI已有bootstrap或严格绑定的已有handoff子任务→runtime_rss_bytes→本次RSS作用域；原policy/身份不变，日志记录有效值及采样；不从env或旧日志继承 | 准入见§5.14；日常upsert/history、events及新apply不开放覆盖。默认/超限/漂移/取消复原隔离通过；正式收尾采样最大4,373,872,640字节，交付完成见§5.15 |
| workspace32GiB | 同一policy；本意图源证据、CSV、候选、spill与目标新增占用按设备分开计量 | 按所有5576股均取老股2209行约1232万行、文本约1.9GiB仅是容量参考，非最保守上界；32GiB暂定，须用真实路径测量验证 |
| progress5秒、本地取消检查0.2秒 | 统一执行器/监督器；不作为每0.2秒查询Dagster的配置 | 单元完成即时报告；长操作报告阶段及已有完成量，连续可见更新≤30秒；远端取消观测有界且计入样本，取消后不领取新单元 |

开始一次按实际挂载/设备估算并核空闲空间；下载页、COPY及必要提交前检查已知增量预留和实时free。账目覆盖两频、已有本意图片段/候选及必要临时文件，原子提升是同设备候选→目标转移，不重复计为两份实际占用；spill上限是额度预留，不能同时算作已消耗。不同文件系统分别核对。恢复用已有receipt汇总、对缺口只核本任务目录元数据，不递归重扫累积Lake。预计输出空间不足则在COPY前拒绝，实际超限保留现场；不等全部下载/COPY完成才首次发现超限。

所有覆盖/默认、缺值、非法值、不同policy透传、跨频率计量、实际free下降及续跑一致性均须正反测试。dependency修正只处理本任务新增pydantic-settings声明及其独有锁项；环境清理列明本任务新增包后单独执行，不能卸载原有Dagster/Pydantic等共享依赖。

<a id="acceptance"></a>
## 7. 纠偏验收清单

先按受影响项补测试，固定版本后集中必要回归；不默认跑全仓、正式bootstrap、历史采集或R3全链。下表是需求覆盖矩阵，不是每轮从头重跑清单；按§5.7区分适用的已有证据、本版本补验和未完成项。测试在隔离环境执行，本版本结果见§5.8及对应最终对账；旧结果不代替新组合验收。

| 对应项 | 正向 | 反向/计数约束 |
| --- | --- | --- |
| 1 HTTP/配置 | 从DG项目外启动其.venv独立CLI/worker，DG环境覆盖URL/token，周/月HTTP正常 | 无Prod可导入路径、无PYTHONPATH仍运行；缺token/非法配置拒绝，其他DG数据集不变，不输出秘密 |
| 2 合并一次 | 多股因子变化+欠账+当前周期同一分区只组装/COPY/提交一次；21字段一致重叠只留一行 | 同键异值拒绝且证据保留；拒绝先upsert再history重写 |
| 3 成功条件 | 周中刷新与周期最终完成分开；周期成功但历史失败，sensor续原历史；旧源到新发布仅补未就绪单元 | 陈旧/NULL源不能记当天完成，历史/事件待办不能被last_refresh跳过，前沿不能越欠账 |
| 4 身份/恢复 | 同股两次主动刷新生成新意图、第二次确实请求源；中断跨日仍恢复原意图完整单元 | 固定manual缓存冒充新下载、换run_id重下成功历史、改旧hash、跨源版本拼不可信页链拒绝 |
| 5 跨日交接 | 下载跨周/月、期间因子/新股/退市，仅补对应范围；停牌旧end_date不拖回多年 | 未追平就ready、静态范围冒充交接、重新下载整个市场或无限追源拒绝 |
| 6 前像 | 正常替换、首次目标不存在、rename后记录失败可读回补记 | 生成候选后目标新增/变化/删除拒绝；候选漂移、认领其他目标拒绝 |
| 7 删除/落盘 | 临时两根先删后建，候选fsync/replace/目录fsync/checkpoint顺序；进程退出后可恢复 | 模拟失联挂载/设备变化/错误路径/链接/冲突写者拒绝；下载后不得再清根 |
| 8 事件/状态 | 文件完成先持久化；事件失败直接events续缺项；外层anchor物化/check真正完成后补记 | 无anchor事件不能写事件cp；其他分区同名check不能顶替；事件失败不写行情、不回滚文件 |
| 9 配置/预算 | 非默认policy贯穿全部消费者；两频增量预留、转移不重复计量、恢复账目一致 | 写前不足/真实free下降拒绝；失配policy不得继续，禁止递归预算扫Lake |
| 10 异常证据 | 精度/字段/身份/截断失败有原始有界证据和reason code，正常receipt可复用 | 异常回包不生成成功单元/替换输入，超限不能无限留证，凭据泄露拒绝 |
| 11 效率 | 有效旧范围记录避免全历史定位；无记录仅一次本批键投影；候选批量检查，同版本复用 | 每股重扫、每分区重读全源、重复SQL/线程、取消检查每秒5次DB读取不能通过；记录实际SQL/API数 |
| 12 真实路径 | localhost真实HTTP进程、TERM/KILL、锁、CLI resume/events/交接；固定版本缓存样本与少量隔离事件 | worker未启动不得宣称退出保护通过；替身/探测客户端/中间版本结果不得冒充最终验收；记录启动及全路径成本 |
| 13 清退 | 按§5.6处理旧链引用闭包，迁移有效金样本，周/月自身治理登记准确 | 旧参数/旧计划不能源请求或创建目标；catalog原格式改动保留、不整文件回退或混入；全仓其他历史治理缺项如实列出 |
| 14 文档 | 方案、两LLD与快照状态一致，14项→实现/正反测试/证据逐项映射 | 未实现写已实现、部分通过写最终通过、旧耗时当新版本实测拒绝 |

业务合同继续覆盖：21列/Decimal/合法NULL守恒；显式新码+freq无历史日期；上市/退市过滤；短页、满页续取、整倍数空末页及超过旧3页；20200228/29均保留；空源/失败/缺页不替换；完整历史移除旧键/仅旧键分区，其他股票及未选频率不变；周五/月末失败跨周期补交且不逐日重放。公式测试用独立字面金样本，不把运行验收改成同公式反复重算。

交付必须逐项填：需求 → 当前代码位置 → 正/反测试 → 本版本证据 → 通过或未完成；文件、事件、日常交接分开。正式删除/bootstrap/重载/事件/sensor执行以及Silver均另行review，不因隔离通过自动执行。

## 8. 历史依据

2026-10-15三个退役asset/job、9项check及目录清退已完成，删除1863文件/119217876字节，代码82e5c225、收尾2783789c；此事实不作为本次重复验收任务。旧B0=1785、859周文件/3028907行只作历史Prod搬运事实，不是新源目标。见[结案记录](../../../reports/stock_period_raw_closeout_20261006.md)及Git。R3原现场不由本轮文档或执行器操作；不恢复旧命令卡、搬运证明依赖或Kopia。

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

<a id="period-completeness-audit"></a>
## 9. 周/月完整性审计与Silver规则（2026-10-17审计与生成均通过）

本节是已确认审计的唯一细则，实际完成结果见§9.6。先完成一次完整性审计，通过后才生成Silver；不是重新下载或重做第8步。本次已按确认的§10完成开发、隔离验收、正式Silver生成及登记，实际结果见§10.10；未重新审计或操作sensor。Prod后置、R3继续暂停。

### 9.1 对象、历史起点与完整周期

| 项目 | 已确认规则 |
| --- | --- |
| 对象 | 沿用确认的当前上市股票范围；stock_lifecycle给出正式上市/退市有效日期，现行身份映射确认同一证券对象及北交所新码。退市股票不纳入应有集合，不补其历史；换码、停牌不等于退市 |
| Raw | 保留当前上市对象源返回的完整历史和全部业务字段，不因本节下限、上市前行情或多版本而删除、截断、改价或提前择行 |
| Silver下限 | 周线从2014-01-03这一周开始，月线从2014年1月开始；2014年前缺口暂不处理，不保留“跳过2014-01-03”的例外 |
| 跨年首周 | 2014-01-03这根周K完整保留，不拆掉2013-12-30/31；完备性仅核查2014-01-01起的有效交易日，不追查2013年停牌或行情缺口 |
| 上市首期 | 正式上市日期确定从哪一周、哪一月开始保留。上市所在周/月的源K线整根保留，完全位于上市前的周期排除；不切割首期、不追查首期内部上市前成交，不从日线生成替代价格 |
| 后续补早期历史 | 只向前扩展周期范围与相应审计日期范围，沿用完整周期规则；不人为留下2014年首周遗漏，不要求本次补齐2014年前参考事实 |
| 本次截止 | 沿用已完成Raw基线的交易日截止2026-10-16，不因审计运行日期为10月17日而延伸；当前10月K线可用2026-10-31作周期标签，仍属未结束月份 |

按管理员举例的假设日期，某股票4月3日正式上市，则上市所在周和4月月线都整根保留；不能因为周期内包含4月3日之前的日期就截断或删除。该例只解释周期规则，不声明北交所于该假设年份开市。

### 9.2 源日期、整行择行与价格

trade_date是源周期标签，不是每天的运行日期；周五、自然月末标签当天可以休市。end_date是源计算截至日期，历史K线也可带最新计算日期，不能将它当成该根K线最后成交日。保留周期归属及选中源记录的可追溯关系，不能靠改标签掩盖日期问题。

每个证券对象、每个周/月只保留一条有效周期事实：先按已确认身份和自然周期归组，选择源end_date最新的完整记录。相同最新计算版本的业务字段相同可以合并；价格等业务字段冲突、无法按此规则确定有效记录时，进入冲突清单，不擅自挑行。必须整行选择，不能从不同记录拼字段，不因28日是交易日就优先于29日的更新版本。Raw原始业务键和所有源记录保持。

已有000001.SZ月线源证据：20200228/end_date=20250910的close_qfq为12.01，20200229/end_date=20261015为11.14，两条close均14.50。Silver选择后者这一完整行；Raw两条均保留。这是复用已有样本，不要求为本节再次请求源。

Silver保留未复权、前复权、后复权三套源OHLC及其余全部源业务字段。按管理员本轮明确口径，字段名、顺序、类型、值、单位及NULL均与Raw一致，日期仍为YYYYMMDD的VARCHAR，不改为DATE；SQL比较日期时的临时转换不写入输出。不得将change改为change_amount，不增加身份、审计或派生字段。不重算价格、涨跌额或涨跌幅，不用日线聚合证明公式。完整schema、job/check及落盘设计见§10，首次生成实施结果见§10.10；日常更新及逐文件恢复的已确认设计、未完成实现见§11。

### 9.3 参考事实与完整性判定

只读取以下现行正式事实，各参考集合读取一次后共用：

| 依据 | 用途 |
| --- | --- |
| silver/basic/stock_lifecycle/full/part-000.parquet | 当前上市状态、list_date及delist_date；上市日包含，退市生效日不包含 |
| silver/basic/stock_identity_map/part-000.parquet及已确认上市对象集合 | 证券身份和北交所新旧代码归属；未知或歧义身份不得当缺口豁免，也不得猜映射 |
| silver/calendar/trade_calendar/full/part-000.parquet | 本次有效开市日；读取现行trade_date DATE、is_open BOOLEAN合同，不恢复Raw的cal_date假设 |
| silver/quote/stock_suspend_daily/trade_date=*/part-000.parquet | 已合成的最终停复牌事实，已包含stock_suspend_confirmed补充；不再次合成或另读confirmed叠加 |

对每股每周/月，先取得该周期内的开市日，再与2014-01-01起、本次截止日以内及该股正式上市有效日期相交，得到本次有效交易日集合D。以最终停牌事实中suspend_type='S'且suspend_timing IS NULL的日期作为全日停牌，盘中停牌和R复牌不整日扣除。历史代码按同一身份关系归属，不因北交所换码产生假缺口。

- D中至少有一个非全日停牌日：该股票周期必须存在有效K线。
- D非空且全部全日停牌：没有K线属于正常缺席，不补价格；不能因为周期内出现过一条停牌记录就豁免整期。
- D为空：不要求有行情。上市首期或跨年首周已有的整根源K线仍按§9.1保留，不依据截取后的局部日期将整根K线裁掉。
- 有行情与停牌事实出现真实矛盾时单列问题，不自行改事实、补价或静默删行。

因此上市首周/月只用正式上市后的有效日期判断是否应有K线，保留时仍是完整周期；2014-01-03只核查2014年内有效日，不把2013年参考事实缺失继续算作本阶段阻塞。正常交易但零量、缺少映射、缺参考事实等原因不能未经依据直接冒充整周期停牌。

完整范围是上述全部当前上市对象和全部范围内周期，不是全量Tushare价格比对。已有Raw字段、类型、精度、原始键及日期合同验收结论直接复用，只补本节新增的周期归属、上市范围、停牌调整后存在性及择行一致性；不重复做已经明确的Raw检查。当前未结束周/月按截止日内日期判断，不要求未来日期已有成交，不将期中成功标为周期最终完成。

### 9.4 已确认的五步流程与非重复边界

1. **复用已有依据。** 复用[2026-10-17原审计](../../../reports/dg_stock_period_raw_completeness_20261017_122911/report.md)及其SQL、已有Raw验收和源证据，仅调整本次确认的时间、上市首期与择行口径。原报告保留当时结论，不能改成新口径已经通过；原2014年前候选退出本阶段待办，跨年首周按§9.3处理，不另加首期专项核验或日线对算步骤。
2. **共用参考事实。** 生命周期、身份、交易日历及最终停牌事实各读取一次，供周/月共用；不逐股重复查，不重新合成停牌。
3. **一次集合审计。** 每个频率按范围批量取得股票周期集合，用DuckDB统一择行、按周期预聚合有效日/全日停牌及计算应有集合与实际集合差集；各统计共用本轮结果。必要源列批量投影，不在每个周期重读全部历史，不展开“全市场×每日”或逐股逐日循环读文件，也不全市场聚合日线。
4. **输出并判定。** 交付§9.5的两频汇总及CSV，记录实际SQL和所复用证据，按已确认标准给出通过或未通过。只依据本轮共用结果整理报告，不为填表重新扫描Lake或请求源。
5. **通过后生成Silver。** 本节审计通过后按同一对象、时间和择行规则生成Silver，复用审计结论；只做必要的文件写入和读回验收，不再做一遍完整审计。若有真实问题，先列命中股票/周期及原因、讨论处理，只补验实际受影响部分，通过后再进入生成；不得扩成自动修复、全量重下或全链重跑。

本次2026-10-17休市窗口按静态输入处理。已明确的结论直接复用，不因假设中间可能变化而再次审计、计算逐文件hash或重查库存；不为“再确认”增加重复的开工/收尾全量扫描。只在发现真实新问题并讨论确认后调整方案，不擅自增加步骤。上述流程不新增长期状态框架、配置、性能实验或额外样本阶段。

原审计主查询5.817秒、SQL主体5.035秒和RSS约2.53GiB仅是当时存在性审计实测，原报告已说明其额外失败投影；不能当本节新择行审计或Silver生成的耗时承诺，不为文档更新重新跑性能。实现沿现有DuckDB能力，不擅自新增或收紧内存、批次、并发、超时等限制。无全量源比对、Tushare请求、重新bootstrap、日线价格重算或2014年前补洞任务。

### 9.5 汇总、CSV与通过标准

汇总逐频说明股票数、范围/截止点、应有周期、实际有效周期、已覆盖应有周期、正常全周期停牌缺席、未解释缺失、按规则排除和择行合并/旧版排除/最新版本冲突数量。范围排除、正常缺席和技术异常分开解释，不能以相同行数或静默过滤代替集合核对。

| 交付 | 必含内容 |
| --- | --- |
| 两频审计报告及规则排除汇总 | 时间范围、对象范围、事实来源、上述计数、真实异常及通过/未通过；说明首周/首期保留、2014年前及上市前完整周期的排除，引用实际SQL和已有证据 |
| 缺失股票及范围CSV | 频率、股票代码/名称/交易所、上市状态及上市/退市日、缺失周期起止/数量、有效交易日数/全日停牌日数及原因；无缺失时也输出带表头的空结果 |
| 最新版本冲突CSV | 频率、证券对象、冲突周期、原始trade_date/end_date、冲突字段/值及源记录定位；同一最新版本业务相同不误报，真实冲突不能隐藏；无冲突时输出带表头的空结果 |

必须同时满足以下条件才通过：应有股票周期无未解释缺失；无未解决身份歧义或最新版本冲突；无未解决的日期/参考事实或停牌矛盾；2014年前周期及完全上市前周期未进入Silver选择范围；2014-01-03跨年首周、上市首期、部分停牌和当前未结束周期未被误删；排除、去重和择行均有计数与原因，未通过项不冒记完成。2014年前周期排除不等于裁掉跨年首周内部的2013年日期，上市前周期排除也不等于拆掉上市首期内部的上市前日期。

下表是同一审计及后续Silver需满足的正反验收口径，不另立源验证、样本实验或重复全链步骤：

| 项目 | 应支持 | 必须拒绝或发现 |
| --- | --- | --- |
| 历史边界 | 周2014-01-03、月2014年1月起；以后向前扩范围可接续 | 跳过首周、将2014年前周期纳入本次Silver、将早期缺口混回待办 |
| 上市周期 | 上市周/月整根保留，至少一个上市后有效交易日就核其应有性 | 删除首期、切割首期、纳入完全上市前周期或另加首期内部成交核验 |
| 身份 | 已确认新旧码归属同一证券，不误判停牌/换码为退市 | 未知/歧义身份、串股、因换码误报缺口 |
| 停牌 | 部分停牌仍要求K线，全期全日停牌可缺席 | 一条停牌豁免全期、将盘中停牌/R当全日停牌、重复叠加confirmed |
| 源日期/择行 | 节假日标签、未结束周期、20200228/29按最新end_date选整行 | 将end_date当内部成交日、固定保留28日旧版、同最新版本异值、拼字段 |
| 字段/范围 | 三套价格、Decimal、单位及合法NULL保持；Raw不变 | 新增无依据重算、误改Raw、截断完整源历史、隐藏不符合现有合同的字段/日期/频度错误 |
| 后续生成 | 审计通过才生成，实际变化的所有历史分区传递；取消后复用已完成成果 | 审计未通过即生成、只更新当前期、重复处理未变化分区或恢复时从头重审 |

原文档落档不代表执行完成；本节审计此后已由管理员批准并完成，实际证据见§9.6。Silver生成随后按单独确认完成，必要落盘及读回结果见§10.10；当时的审计通过本身并不等于生成通过。新增日常更新设计与授权边界见§11，不重做本节完整审计。

### 9.6 已完成审计与复用基线

完整报告：[2026-10-17 Silver生成前审计](../../../reports/dg_stock_period_silver_readiness_20261017_135833/report.md)。文档基线585b0a041；输入文件清单、实际SQL和逐频统计分别保存在同目录inputs.json、audit.sql、summary.json。该主审计4.571秒、RSS约2.40GiB；准备阶段小参考文件的别名语法错误已在报告单列，没有Raw或停牌历史重复扫描。

| 当前上市5,577股，截止2026-10-16 | week | month |
| --- | ---: | ---: |
| 本次范围Raw文件/行 | 656 / 2,533,758 | 154 / 606,752 |
| 完全上市前排除行 | 23,682 | 7,570 |
| 旧计算版本排除行 | 0 | 3,574 |
| 通过规则选中的周期行，作为生成预期 | 2,510,076 | 595,608 |
| 应有且已覆盖周期 | 2,510,069 | 595,608 |
| 缺失/最新版本冲突/普通整期停牌矛盾 | 0 / 0 / 0 | 0 / 0 / 0 |

周线额外7个属于跨年或上市首期边界，按完整周期保留；不得为了让行数等于“应有周期”再删7行。首周2014-01-03保留2,159股。缺口范围、逐期缺口及最新版本冲突CSV均已输出，数据行数0。后续生成复用此基线，不重跑本节审计；表中为当时审计选择数；本次实际落盘数量与之相同，见§10.10。

<a id="period-silver-generation"></a>
## 10. 第5步：Silver生成实施设计（2026-10-17已实施并验收）

本节只细化原五步流程的第5步，不新增审计、源验证或全链阶段。目标是在已审计范围内将选中的Raw完整行落盘，建立两个Silver资产的生成、检查和恢复能力。本节实施及正式操作已获管理员确认；代码、隔离、正式文件与DG登记均完成，结果见§10.10，不外推为后续自动调度授权。

### 10.1 字段合同：与Raw完全一致

唯一字段顺序复用run_contracts/stock_period.py的FIELDS，以及现行周/月Raw column_specs；在asset_column_schemas.py注册两个Silver schema时直接复用对应Raw合同，不复制出另一套可漂移类型表。完整顺序如下：

```text
ts_code, trade_date, end_date, freq, open, high, low, close, pre_close,
open_qfq, high_qfq, low_qfq, close_qfq,
open_hfq, high_hfq, low_hfq, close_hfq,
vol, amount, change, pct_chg
```

| 字段 | Silver与Raw相同的物理类型/含义 |
| --- | --- |
| ts_code、trade_date、end_date、freq | VARCHAR；代码、YYYYMMDD源日期及week/month原值保留 |
| 普通/QFQ/HFQ各组OHLC、pre_close、change | DECIMAL(18,4)，源值不变 |
| vol、amount | DECIMAL(20,4)，源单位不变 |
| pct_chg | DECIMAL(10,4)，源单位不变 |

保持全部21列、列顺序、类型、精度、合法NULL及选中整行的每个值。身份映射和日期解析只在WHERE/JOIN/分组中使用，不重写ts_code或trade_date，不新增period、source_trade_date、is_final、asof、审计/版本/运行标识列。不得投影SELECT *带出filename、Hive目录列或临时比较列；显式按FIELDS输出，读取Parquet使用hive_partitioning=false。

这是管理员明确的两套周/月Silver合同：不套用日线change_amount改名、DOUBLE转换，或编码规范/模板的一般Silver日期转DATE范例；不修改其他Silver资产的合同，也不据此改变通用规范。

### 10.2 定义、主键、分区与路径

| 项目 | 周线 | 月线 |
| --- | --- | --- |
| asset | silver_stock_weekly | silver_stock_monthly |
| dataset / contract | stock_weekly / stock_weekly@1 | stock_monthly / stock_monthly@1 |
| job，仅选本Silver及其检查，不选择Raw | silver_stock_weekly_update_job | silver_stock_monthly_update_job |
| 复用现有分区定义 | cn_a_stock_week_ends | cn_a_stock_months |
| 新catalog分区模型 | week_end_partition_silver_stock_weekly | month_partition_silver_stock_monthly |
| 正式文件，相对唯一Lake根 | silver/quote/stock_weekly/week_end=YYYY-MM-DD/part-000.parquet | silver/quote/stock_monthly/month=YYYY-MM/part-000.parquet |
| 首次范围及预期 | 2014-01-03—2026-10-16，656文件/2,510,076行 | 2014-01—2026-10，154文件/595,608行 |

正式Lake根仍为/Volumes/datasource/data_lake。候选、执行记录及spill仅放/Volumes/datasource/data_lake_staging/stock_period_silver/run_id=本次UUID/下；不能使用Raw执行目录、旧Lake或正式Silver根作staging。两频共用该次运行，按(freq,period)逐文件checkpoint；行情文件中不增加period列。

业务唯一性是同一证券每周期一行，周期由外部分区键与源trade_date的自然周/月归属确定；分区内ts_code唯一、freq一致。源trade_date可以不是自然月末，不能为了对齐分区把原值改写。主键口径不能退回仅按原始trade_date区分同月多版本。

catalog使用DERIVED_CONTRACT、DERIVED_FROM_ASSETS及逐分区原子替换政策，来源是对应Raw和身份/生命周期事实；不是另一次Tushare接入。定义metadata注册21列schema，运行metadata仅记录实际路径、行数、源引用、执行标识和观察结果，不把这些写成业务列。

### 10.3 选行与一次生成算法

首次输入直接使用§9.6审计报告及inputs.json列出的656周/154月Raw文件，截止点和起点取报告范围。文件清单不是新freeze或待执行计划，不重新扫描全市场发现输入，不重做停牌/日历完备性查询。生命周期及身份参考一次加载共用，上市、币种、退市范围沿审计口径，遇真实身份问题停止相关处理并报告。

每个执行unit就是一个已列明的Raw周期文件→一个Silver周期文件：

1. 读取这个Raw文件的显式21列，按身份确认对象，临时解析trade_date/end_date用于周期与版本比较；不读取其他周期Raw或日线。
2. 选择报告范围内、当前上市对象、上市所在期及其后周期的记录。上市首期/跨年首周整根保留，§9.6的7个边界周期不再受局部停牌条件二次过滤。
3. 同一对象/周期先找最大源end_date；最新版本业务字段冲突则停止，不以ROW_NUMBER提前掩盖冲突。相同业务值的并列最新版只保留一条原始整行，以原trade_date降序作确定性定位；这只处理值相同的重复，不改变“最新计算版本优先”。当前审计没有此类并列，不能凭空生成一条新日期。
4. 将选中完整行的21列原样COPY到本unit独立候选文件。使用非PARTITION_BY的单目标COPY，一个周期明确一个文件，避免再次出现多片段只接收第一片的问题；不用Python行循环写Parquet。
5. 选中关系在本unit内保留，候选一次读回时共用查询验证schema、周期/唯一性、行数和21字段的EXCEPT ALL双向差集；与内存选中关系比较，不再读Raw或重算价格。合格后持久化验证记录，再逐文件原子提升。

两频按已列明周期顺序串行处理，共用一个协调进程和DuckDB连接，不为每个周期启动进程或连接。内存只随参考表和单周期增长，不常驻全部历史；一个Raw周期读取一次、选择一次、COPY一次、完整读回校验一次。复用正确性的独立字面金样本，不在生成后又做全量源比对或完整性审计。

### 10.4 提升、状态、取消与续跑

正式执行开工只做一次必要写入边界检查：真实挂载、两固定目标根/符号链接、同文件系统、相关写者及可用空间；不读取其他数据、不逐文件hash。首次目标应不存在；存在未归属本次执行的文件即报告，不删除旧根、不覆盖未知成果、不做Kopia或备份。

本次休市窗口的首次生成使用独立Silver单写锁，CLI/job遵守同一锁，未持有Raw业务锁。每个unit记录Raw/候选/目标的文件版本；这是该次读写提交证据，不是重新审计库存。已完成的首次执行不因后续设计变更重跑；未来日常update的并发边界另见§11.3。

| 持久化状态 | 恢复动作 |
| --- | --- |
| unit未开始/候选未完成 | 只重新处理本unit，保留已完成文件 |
| 候选已校验、尚未提升 | 复用同版本候选与校验记录，不再次COPY或完整校验 |
| 候选fsync→os.replace→目标父目录fsync已完成，checkpoint未记成功 | 由提升前已持久化的候选身份及目标文件事实确认同一次rename，补记checkpoint；不能认领第三方文件 |
| 文件已提交、事件未完成 | 只补缺失事件，不下载、不跑选行SQL、不重写文件 |
| 文件及事件均完成 | 幂等跳过，不重读数据或重发事件 |

每次COPY前后、校验前后和提升前检查取消；取消后不领取下一unit，保留已完成文件/候选/checkpoint并释放锁。采用单进程执行，不新建下载worker；TERM/KILL后只涉及本进程，内核释放文件锁，重启从同一run_id续跑。DuckDB长SQL须支持安全取消，进度显示真实阶段、当前周期、完成/总量及最后emit时间；不得用伪造完成数充心跳。不得因取消清根、改旧执行身份或删除证据。

合法空选择结果按原21列写0行Parquet并明确原因，不用空文件冒充失败成功；本次810个周期预期均非空，出现非预期空结果先报告。Raw缺失或读取失败不能触发清空既有Silver。状态/事件写入失败不回滚已落盘行情；不引入跨810文件的大事务或“整体原子”承诺。

### 10.5 三项blocking检查、事件与必要验收

每个资产固定三项check：silver_stock_weekly_file_contract_check、silver_stock_weekly_key_partition_check、silver_stock_weekly_source_projection_check；月线对应silver_stock_monthly_前缀。

| check | 真实校验内容 |
| --- | --- |
| file_contract | 文件可读、21列/顺序/类型及Decimal/合法NULL合同；日线式DATE/DOUBLE/改名或额外字段拒绝 |
| key_partition | freq、源日期所属周期与路径匹配、周期内证券唯一、范围/身份正确；不要求标签当天开市 |
| source_projection | 完整输出行集合等于本unit按已确认规则选中的源整行，行数/所有字段/NULL一致；不是复权公式二次计算 |

三项共用一次验证结果，按精确输入/输出文件版本及规则版本绑定缓存。写入当次和CLI events复用已持久化的合格证据，不为三项check各重读一次文件。后续独立check没有适用证据时，只对该分区做一次真实文件/源投影核验，三项共用；不得把bootstrap临时证明变成日常运行长期必备依赖。证据缺失或版本确已不符不得伪造通过，不因此扩成全历史审计。

每次提升使用已校验候选，rename后只确认同一文件身份及必要页脚/行数事实，不再次全量读取21字段；累计逐文件完成证据做最终汇总。先完成实际文件再登记物化和blocking结果。每个检查绑定该资产、该分区的真实物化ID，PLANNED、错误分区或旧物化均不能顶替。CLI登记沿已验证的“一个真实Dagster补报run批量登记”方式；不用runless空run_id检查，不伪造run，不改Dagster库/schema。

810个文件预计810条物化、2,430条检查，共3,240条必要事件；这是按3项check计算的计划数，不冒充实际登记完成数。事件checkpoint与文件checkpoint分开，续报只补缺项。收尾只汇总已完成文件/事件及抽取必要登记证据，不逐分区再做全套readiness。首次生成完成、文件验收完成和DG登记完成分开报告。

### 10.6 明确入口及首次执行边界

新增bootstrap/stock_period_silver_cli.py，不扩展或更改现有Raw CLI：无action只显示帮助且不写入，明确action为build、resume、events。build要求--run-id（本次canonical UUID）和--audit-report（§9.6报告目录）；resume/events沿同一run_id，读取其既有run-scoped记录。--lake-root/--staging-root默认使用paths.py的正式根；临时根仅隔离测试显式传入，正式路径不得指向旧Lake。

首次build把报告范围、已列明输入、同字段规则版本、两固定输出根写入本次小型执行记录；不创建可变的新业务范围，不新增prepare/freeze/apply/handoff/删除阶段。身份不能因恢复日期改变；新任务用新ID，本次旧ID不能改范围。events只操作已经完成且校验通过的文件登记，不读取Tushare、生成候选或补算行情。其内部真实补报job名为silver_stock_period_event_backfill_job，不新增一组长期业务状态表。

单周期job调用同一个生成器，仅处理该资产的显式partition_key；配置只传本次执行身份和已确认审计范围引用，不能从run_key反解范围，不能顺便执行Raw job。首次范围以外的日期不通过本次审计引用获准。未来补早期历史用新的获准范围引用，沿同一周期算法，不修改列合同或硬编码特例。

本次实施范围是首次生成和可复用单周期job，不新增或启用Silver sensor，也不修改Raw sensor状态/水位。后续自动日常接线另行明确：应消费Raw既有complete.json/files中的全部实际变更周期，含两频历史因子刷新，而非只追当前anchor；本轮不为该未来接线修改Raw metadata或新增自动化步骤，不把首次生成写成日常自动维护已完成。

正式执行前按获准文件白名单加载新增定义，不夹带其他任务未获准改动；无法隔离先报告，不切分支/worktree或重启无关服务。正式build和events必须使用最终确认的精确命令及DAGSTER_HOME；本次开发、重载、两固定根写入及必要事件登记已获确认并按本节完成；不授权其他数据集或后续自动调度。

### 10.7 成本、资源与配置来源

| 项目 | 本次有据规模/执行选择 |
| --- | --- |
| 对象/频度 | 5,577只当前上市股票、2频；按周期执行，不按股票×周期扇出 |
| 输入/输出 | 810个Raw文件/3,140,510行；预计810个Silver文件/3,105,684行，不读取2014年前Raw |
| 源请求/进程 | Tushare/Prod请求0；一个协调进程、一条复用DuckDB连接，无下载worker |
| 数据SQL | 每文件一次Raw投影/选择、一次单文件COPY及一次合并读回校验；三项check复用结果，不是三次重算 |
| 业务持久化边界 | 每周期独立候选、验证、原子提升及checkpoint；失败最多重做尚未完成unit |
| 登记 | 最多810次实际文件登记单元，事件预计3,240条；独立真实补报run批量处理，不启动810次历史asset run |
| 费用与耗时 | 无外部配额消耗；本表为首次生成前的设计规模，实际COPY/fsync/事件和资源测量见§10.10；不为后续日常设计重新bootstrap或重复审计 |

不新增env、Settings、数据库或长期配置文件。以下均为现有配置来源或本次显式执行输入，不能散落成另一套阈值：

| 配置/输入 | 默认、来源及消费者 | 生效/失败处理 |
| --- | --- | --- |
| Lake/staging根 | paths.py既有默认；新CLI显式参数和job既有LakeRootResource | 本次执行固定、路径/设备不符拒绝，不更改全局路径 |
| run_id/audit_report | 无隐式“最新”默认；CLI/job显式传入，本次执行记录保存范围引用 | 同ID恢复，非法身份/未通过审计/范围越界拒绝 |
| DuckDB memory/threads/spill | 复用DuckDBConnectionSettings既有默认16GB/4线程/512GB；只将temp_directory指向本次staging/spill | 这些是现行引擎上限而非实际分配或业务门禁；不套Raw HTTP policy，不新增Silver小额阈值，异常留证退出 |
| 并发/批次/空间 | 单协调器、每周期一个持久化unit；不新增可配置并发或未经测量的固定MB上限 | 空间开工检查一次，按已知候选/提升/实际spill增量计量并在提交边界确认，不递归扫描累积目录 |

空间峰值考虑现有Raw、已生成Silver、本unit候选/旧目标（更新时）和实际spill；无备份副本。首次压缩体积、fsync/事件实测见§10.10，后续增量覆盖的成本另由必要小场景记录，不用行数伪造精确GiB或时间承诺。空间不足/真实目标冲突只停止当前执行并保留成功unit，不擅自放宽额度、安装依赖、换盘或改合同；不为测量再加全市场审计。

全部Silver入口显式调用connect_configured_duckdb并传入temp_directory为本次staging/spill的DuckDBConnectionSettings，其他参数沿上述既有默认；不直接调用会使用全局临时目录的无参DuckDBResource.connect()，不修改共享resource默认或让spill落到正式Lake/全局移动盘临时目录。

### 10.8 具体开发文件与影响面白名单

以下路径相对lake_console/orchestrator/；只为本Silver生成落地，均已按确认范围实施：

| 文件 | 落地职责 |
| --- | --- |
| 新src/orchestrator/defs/run_contracts/stock_period_silver.py | 两频Silver身份、范围引用、字段不变/周期唯一合同及小型执行记录版本 |
| src/orchestrator/defs/run_contracts/asset_column_schemas.py、paths.py | 注册两个同Raw schema与两固定Silver路径，不修改既有Raw合同 |
| 新src/orchestrator/defs/stock_period_silver.py | 纯源整行投影/择行、协调逐周期生成与共用检查结果，不放HTTP或Prod依赖 |
| 新src/orchestrator/defs/io/stock_period_silver.py | Silver目标/候选边界、单写锁、原子提交与逐文件恢复；不直接调用写死Raw目标的publish/audit_file |
| src/orchestrator/defs/assets/stock_weekly.py、stock_monthly.py | 在原模块新增各自Silver asset，原Raw asset函数及入口行为不变 |
| src/orchestrator/defs/jobs/stock_weekly.py、stock_monthly.py | 各新增只选Silver及检查的job，保留原Raw job |
| 新src/orchestrator/defs/checks/stock_period_silver_checks.py | 两频六项blocking checks，共用一次实际验证，不依赖一次性bootstrap证明长期供数 |
| 新src/orchestrator/defs/bootstrap/stock_period_silver_cli.py | build/resume/events入口及真实补报run；无删除、下载或旧计划兼容 |
| src/orchestrator/defs/catalog/lake_assets.py | 新增两个asset、分区模型、六项blocking名称及来源/字段/读写/性能合同；保留其他任务格式和改动 |
| src/orchestrator/defs/catalog/name_mapping.py | 已获准补齐stock_weekly/stock_monthly的“股票周线/股票月线”中文名称，供既有metadata及catalog构造器使用；不改变其他名称或构造器行为 |
| 新tests/test_stock_period_silver_contracts.py、test_stock_period_silver_projection.py | 21列完全一致、独立字面金样本、范围/整期/择行/NULL/身份正反例 |
| 新tests/test_stock_period_silver_execution.py、test_stock_period_silver_events.py、test_stock_period_silver_jobs.py | 原子性、取消恢复、同版本复用、事件失败、真实运行绑定与定义/直接消费者回归 |
| tests/test_asset_check_incremental_governance.py、test_asset_governance_contracts.py | 仅追加两Silver的六项治理登记及活动资产清单；不放宽其他数据集的全局断言 |

复用前已查当前Raw入口→deliver_asset→run_period→io.publish及事件链：report_file_events固定Raw asset/check/路径，不能直接给Silver用；_replace_parquet_from_query的旁路.tmp也不能当完整staging/checkpoint能力。safe_path/file_version/fsync等根无关底层能力可在确认真实语义后窄复用，不搬动或泛化现有Raw主链。通用schema、paths、catalog的直接消费者仅本次新增资产/检查/CLI和治理测试；不触及Prod DatasetDefinition、业务API、前端、日线/分钟算法或依赖矩阵，不新增对src/ops/app的依赖。

### 10.9 隔离验收、正式生成与交付

| 验收点 | 正向 | 负向/故障 |
| --- | --- | --- |
| 字段完全一致 | 真实Raw schema及已有有界源样本核对21列/顺序/Decimal/NULL，输出整行逐值相同 | 日期转DATE、数字转DOUBLE、change改名、额外period/审计列、改码/改价均失败 |
| 审计范围/完整周期 | 2014-01-03首周、上市首周/月及7个边界周期按既定规则保留 | 2014年前、完全上市前、未获准日期进入输出；首期截断或漏首周失败 |
| 择行 | 20200228/29真实样本与独立expected选择更新end_date整行；同值重复可确定性选择原行 | 最新同版本异值不得提前ROW_NUMBER跳过，不拼字段、不制造新日期 |
| 文件/单位 | 周/月各一个固定目标，单Raw周期读一次，三个check共用校验 | 错根/旧Lake/符号链接/跨设备/未知目标、同周期冲突writer或候选不符均拒绝 |
| 取消与退出 | COPY前后、提升前后取消，TERM/KILL后沿同ID续成功unit，不留本任务worker/锁 | 清根、重写已完成文件、改身份认领旧结果、失败空结果冒充成功均失败 |
| checkpoint/事件 | rename后记录失败读回补记；文件和事件分开，真实补报run绑定当前资产/分区/物化 | 事件失败不得重写行情；PLANNED、错分区、错物化及空run_id不能冒充检查成功 |
| 隔离集成/效率 | 临时Lake/staging、隔离instance走实际Silver asset/job/check/CLI，复用既有Raw样本 | 任何Tushare/Prod请求、Raw写入、正式资源操作、每股/每check扫全历史和恢复重跑完整审计均拒绝 |

本次已按管理员确认在上述白名单实施、隔离验收并执行正式清单；必要步骤及结果见§10.10。这是第5步的开发/落盘安全要求，不新增上游审计或源验证步骤。修复时只跑受影响测试，固定版本后一次直接回归；不默认全仓/完整bootstrap。

获准正式执行时先加载确定版本（其他任务加载冲突先汇报），在保持Raw sensor状态/水位及R3暂停的条件下，以§9.6作为审计门禁执行一次build；随后只补需要的events，并汇总810个unit的既有写入/检查记录。预期week=656文件/2,510,076行、month=154文件/595,608行、总3,105,684行；真实结果不符先报告，不擅自修订审计数字或扩大范围。不能把7个边界周期误删后仍声称对账通过。

交付：实际文件数/行数/路径和按期范围，21字段守恒证据，三项检查及真实登记绑定，取消/续跑/事件失败覆盖，SQL/I/O/资源实测和未覆盖项，正式操作清单与其他任务保留情况。最终状态分别写“设计、代码、隔离验收、正式文件、DG登记”；自动日常接线、Prod、R3不冒记完成。后续新增问题按根AGENTS先讨论，不靠新增验证步骤或反复审计掩盖。

设计证据：本轮使用CodeGraph explore查看report_file_events、Raw发布和DuckDB连接的真实实现及直接调用方，结合Raw asset/job/check、字段schema、catalog和审计产物核对；未扫描数据湖或请求Tushare。Dagster依据为[asset metadata](https://dagster.io/docs/guides/build/assets/metadata-and-tags)、[asset checks](https://dagster.io/docs/guides/test/asset-checks)及[partitioning assets](https://dagster.io/docs/guides/build/partitions-and-backfills/partitioning-assets)，仅用于定义/检查/分区设计，不授权升级当前安装版本。本节新增的周/月Silver命名、路径及CLI现已按确认实施；不能以历史Raw通过结果代替本节验收。


### 10.10 正式生成与验收结果（2026-10-17）

本次run_id=d895bec0-8b69-4cd3-aabe-7f06a4c7e467；复用§9.6审计，不重新做完整性审计、源请求、Raw扫描或复权计算。正式周线656文件/2,510,076行，范围2014-01-03—2026-10-16；月线154文件/595,608行，2014-01—2026-10。合计810文件/3,105,684行，21列及整行源值逐文件验证通过；7个边界周线保留。

仅重载orchestrator后执行本CLI build，再执行events。正式补报run=891c70f1-146f-4e2c-aaa2-cdc2ca4181bb，SUCCESS；最后8个批量DG查询确认实际810物化+2,430项blocking检查，均通过且绑定正确资产/分区/物化ID。收尾只汇总已有checkpoint并列目标目录元数据，未再读Parquet。Raw sensor状态和业务水位相同，锁释放，R3源码保持执行前版本，R3继续暂停。

43项新增Silver隔离测试通过，两个真实缓存Raw文件走最终生成器；每期Raw全读、COPY、完整候选读回、footer各1次，完成续跑0 SQL/0改写。完整definition临时验证、Ruff致命错误及本次文件默认规则通过。扩展回归73通过/2未通过：一项为既有15个其他数据集治理缺项（HEAD同样缺失）；一项为停牌专用启动器测试被直接pytest调用时缺support。未跳过、改弱或修理这些无关项，不声称全仓通过；本次两资产自身登记/检查与实际job通过。

正式文件阶段31.889秒，RSS峰值896,434,176字节（约855MiB），输出170,035,374字节；选择14.776秒、COPY3.813秒、候选验证阶段10.997秒、提升/footer0.994秒。事件阶段110.642秒，文件/事件合计约142.5秒（不含开工、加载和收尾）。复用16GB/4线程/512GB默认引擎上限，实际占用见实测；最终spill残留0，不冒记峰值。所有正式日志、checkpoint保留，详见[Silver生成验收报告](../../../reports/dg_stock_period_silver_generation_20261017/report.md)。

本次设计、代码、隔离、正式文件及DG登记已完成。自动日常/因子刷新接线仍未实施，不新增或启停Silver sensor，不改Raw请求/入口、Prod或R3。原生成设计已提交ace57334b，本次实现与收尾文档尚未提交、不推送；其他任务改动保留。

<a id="period-silver-daily-maintenance"></a>
## 11. DG剩余1—3项的实施设计（2026-10-17开发与隔离验收已确认）

本节对应总方案§9：1补齐Silver日常更新、2接通Raw实际交付并验收、3白名单提交/结案。2026-10-17管理员确认先提交文档，无卡点则按本节开发/隔离验收；不授权正式写湖/staging/事件、重载或sensor操作。各项开发前按根AGENTS“按计划开发执行链”第8条检查本节完整性与实际接口；意外或无法推进的错误必须停止报告，讨论并回写原文档后再继续，不凭聊天摘要或带严重问题改代码。

**恢复设计与实现状态。** 逐文件恢复方案已先提交dbec0343，随后按§11.2—11.4完成恢复缺陷修复和隔离验收，结果见§11.11；实现已提交d865e640，§11.10保留修复前失败。分类及治理文档补项已提交b9ba7163。前序源码登记清退已提交e87225b2。第2项通知/sensor及原生检查后的完成确认已实现并完成隔离验收，结果见§11.12；没有正式资源操作。

### 11.1 当前环境、代码依据与影响面

2026-10-17在dev-interface只读核验：项目现有Python3.13.5；正式orchestrator location为LOADED，两个Silver job已加载，sensor daemon健康。四个周/月Raw/Silver目标job均未见在途运行，未据此推断所有手动进程/锁为空。Raw baseline.ready，handoff_cutoff、factor_through与两频last_refresh均为2026-10-16，completed_through为week=2026-10-16、month=2026-09，未结束10月未被冒记完成。两个Raw sensor均RUNNING，cursor仍保留原周/月业务水位。Silver原执行的文件及事件完成记录与§10.10一致。此处核验不是重新验收行情或证明未来运行必然成功。

以下表格保留开工前代码基线及设计原因；本轮恢复修复后的实际结果见§11.11，不把这些历史缺口继续当作当前阻塞。

| 开工前代码落点 | 当时已核实行为及设计结论 |
| --- | --- |
| run_contracts/stock_period_silver.py::StockPeriodSilverConfig；stock_period_silver.py::make_execution/deliver_asset | 首次生成配置依赖execution_id/audit_report；第1项已部分增加update/source_completion，但尚无完整承接合同。首次生成不改，日常与恢复须按下文补齐 |
| stock_period_silver.py::select_period/validate_projection/build/current_validation | 现有选行算法、每周期一次投影/候选验证、单连接及三check复用可保留。独立check已有不依赖bootstrap临时证明的单周期路径 |
| io/stock_period_silver.py::publish | 已部分实现已知前像替换；当前先检查源版本，再识别rename，恢复时仍须先确认目标是否已提交，不能因源后来变化丢掉真实提交事实。未知候选/目标继续拒绝 |
| stock_period_silver.py::update_inputs/build；bootstrap/stock_period_silver_cli.py::report_update_events | 现实现要求已有目标匹配DG登记、启动前检查全批源版本，事件又要求整批complete.json，造成§11.10死结。需按文件识别归属、按文件处理输入变化，允许未完成整批的合格文件独立补登记 |
| stock_period_history.py::_finish_files/replay_events | complete.json已有全部实际files、file_receipt_hash及unit_asofs；现有events回调只收到单文件item，不传交付引用。不能为接线重写原identity/hash/complete |
| stock_period_update.py::execute_daily/deliver_asset/report_file_events/handoff | 一次Raw任务可实际修改两频历史，但anchor返回metadata仅含当前文件版本。CLI events/handoff及周线补报op也是事件消费者，必须同步接线 |
| sensors/raw_stock_weekly_update_job_sensor.py、raw_stock_monthly_update_job_sensor.py | 只编排Raw；60秒轮询及19:30源窗口保留。无Silver日常sensor |
| jobs/assets/checks/catalog中的两个Silver | 已有asset/job/check/分区身份保留；不新增数据集、不迁移Prod DatasetDefinition或业务API/前端 |

使用CodeGraph explore追踪Raw deliver_asset→run_period→replay_events→report_file_events及Silver执行，impact核对report_file_events/run_period。动态回调覆盖不完整的部分已用当前源码引用补核：stock_period_update.py、stock_period_history_cli.py、ops/stock_weekly_bootstrap_checks.py；后者只补周线，不能因这次接线擅自让它补月线。测试消费者见§11.8。没有跨foundation/ops/biz/app依赖改动，R3没有消费者迁移任务。Dagster设计依据为[资产](https://dagster.io/docs/guides/build/assets)、[分区](https://dagster.io/docs/guides/build/partitions-and-backfills)、[sensor及cursor/run key](https://dagster.io/docs/guides/automate/sensors)、[检查](https://dagster.io/docs/guides/test/asset-checks)，并已核对当前安装的SQL event log表/状态过滤实现；不升级依赖。

本次恢复补正另以CodeGraph explore核对update_inputs→make_update_execution、report_update_events及配置，impact核对report_update_events→replay_events/main；动态asset调用、publish、validate_record、CLI参数分支和直接测试已阅读当前代码补核。消费者为现有周/月asset/check、job入口、CLI resume/events，后续第2项sensor复用同一合同；无业务API、前端或跨子系统消费者。图中未自动关联的隔离测试按§11.8源码定位，不把“无覆盖”提示当作测试不存在。

### 11.2 第1项输入、数据范围与配置审计

保留两个asset/job、六项check、路径及分区名；沿§9.2、§10全部21列/整行规则。week下限2014-01-03，month下限2014-01；上市首周期完整保留，Raw不裁历史。日常不重算停牌/生命周期完备性，不请求Tushare；参考资产仅按现行合同读取一次用于选行。Raw历史移除旧键后，Silver对受影响周期重新选整行，不在旧Silver上仅追加，从而同步移除旧键。

在现有StockPeriodSilverConfig中增加互斥意图，以下DG入口合同随本节开发设计一并获准；正式加载和使用另行确认：

| 配置/输入 | 默认与来源、持久化、消费者 | 依赖、生效及失败处理 |
| --- | --- | --- |
| intent | 默认bootstrap；job显式配置写入Dagster run config，新执行记录保存；消费者为Silver asset/执行器 | 只允许bootstrap/update；无隐式“最新模式” |
| execution_id | 继续canonical UUID，显式输入；自动update由频率及稳定上游batch_id确定性生成，写入run config/execution.json | 同ID只续同一冻结范围，不能复用ID改源版本或范围 |
| audit_report | 原bootstrap必填；update不传，沿执行记录保存获准范围 | bootstrap仍按原报告/拒绝未知目标；update混传报告、bootstrap缺报告均拒绝，不给日常伪造审计报告 |
| source_completion | update必填，结构为raw_execution_id、file_receipt_hash、upstream_batch_id；来自§11.5小通知，保存到run config/execution.json | 原始ID为64位hex，按固定staging规则定位，禁止任意文件路径；batch_id必须按既有构造器复算一致。bootstrap禁止此项 |
| resume_from_execution_id | update正常首次运行默认None；承接时为明确原Silver执行的canonical UUID，来自恢复调用或第2项cursor中的当前execution_id，保存到新run config/execution.json。消费者为合同校验、统一恢复规划、asset执行器及CLI恢复适配 | 仅指向同根、同频率、同规则/下限的未完成update；加载并固定原identity_hash及完整周期集合。禁止自引用、循环、任意路径、跨频率或猜“最近任务”；bootstrap禁止。它只标明成果来源，不是force放行开关；不是env/Settings/数据库配置 |
| lower/asof/规则 | lower沿已确认2014边界；asof来自本次Raw已完成意图/逐单元截止记录，参考文件版本随新执行固定；消费者为选行、检查和事件 | 不是独立env/Settings输入，不能硬编码旧截止2026-10-16，不能把未来周五/月末标签当未来成交。当前不带asof的主动history，以该Raw完成时间的上海日期作校验上界，原样保留每行end_date |
| DuckDB/临时根 | 沿§10.7的16GB/4线程/512GB默认，只换本执行spill目录 | 既有引擎上限不代表预分配；不新增RSS阈值或套Raw6GiB政策，不改共享默认 |
| sensor间隔/批次 | 在本Silver合同集中定义60秒轮询，默认STOPPED；每tick最多一个本频率Raw交付、一个RunRequest | 60秒沿现有DG轮询节奏，是实现选择，不是数据新鲜度保证；只在后续批准加载/启用时生效，无新增env/数据库配置 |

不新增source代码、日期、重算公式、force覆盖等运营输入。config的构造与校验集中在本Silver合同，不能在sensor/CLI/asset各自设默认。恢复引用不新增CLI动作或参数，入口适配见§11.4；无新增全局配置、状态表、恢复目录框架或任意staging扫描。运行意图保存在现有run config/execution.json，逐文件事实和事件回执沿现有files/、events/位置保存。所有失败均记录reason code、当前批次/周期及下一动作，不能静默fallback到bootstrap或Prod。

### 11.3 第1项执行、已有目标与版本复用

1. 从指定Raw manifest/complete读取本频率实际变更周期，校验原identity、file_receipt_hash、合法路径/freq/唯一周期；按2014边界过滤并记录排除数量。不glob全湖、补造周期或从旧审计报告推当前范围。一次去重并排序，一个周期一个unit。
2. 用§11.6批量证据核对Raw和已有Silver的当前物化、检查及版本。真实新周期须目标与既有物化均不存在；已有目标的归属可由两种明确证据确认：同规则/路径的真实Silver物化及三项合格检查精确匹配当前文件，或§11.4指定执行的完整校验/提交记录精确匹配当前文件。后一种只用于本任务恢复/承接，DG尚未登记不妨碍识别已知成果；不能将缺登记解释成已ready。没有任一证据、已物化但文件丢失、真实失败check或错误绑定均阻断，不自动借更新修复未知破坏。
3. 首次生成的§10.10物化已足以识别既有目标，不要求重新做810文件审计或补一遍旧事件。后续Silver metadata增加source_version、reference_versions和source_completion，连同现有rule/lower/asof/target_version用于判断同版本已交付；这些仅为运行metadata，不入21业务列。缺少旧source_version不反推“已对齐”，首次收到真正变化的Raw后正常更新该期。
4. 冻结本次小型execution：update意图、本频率、已列明unit及输入版本、参考版本、目标前像/不存在标记、截止与稳定batch身份；承接时另存原执行引用/hash与逐期成果来源。逐unit保存其Raw交付asof；合并不同完成批次时，选行/检查/metadata使用该unit的asof，不用整批最大日期改写旧交付含义。首次bootstrap及原update的ID/hash不改，选行rule不因新增执行意图而改变。同版沿原ID续跑，真正输入变化按§11.4建立有明确来源的新执行，不新增另一套写入实现。
5. 日常update在现有Raw写锁→Silver写锁的固定顺序下执行文件阶段，防止读取/提升间Raw被另一个合规写者替换；拿不到锁则不写、不忙等。Raw只借用锁，不改其业务数据。事件阶段释放Raw锁。update的job及CLI恢复入口使用同一顺序，无相反嵌套；原bootstrap意图继续使用既有独立Silver锁及获准静态输入窗口。锁内先核对逐文件提交事实，再处理输入是否仍适用；合法新交付只影响对应unit，不作全批成果失效。冻结之后、锁内执行期间发生未解释的输入/前像变化仍停止，不能中途静默换源。
6. 一批复用一条DuckDB连接/一份参考表；每unit选行一次、COPY一次、完整候选验证一次。整期按源重建，原子替换已有目标；不删除根、不先unlink目标、不保存备份。未列明分区和另一频率不写。合法空选择仍按§10.4处理；非预期空/源缺失或失败先报错，不能清空旧Silver冒充成功。
7. 校验后记录candidate_version、source_version、target_preimage和验证结果；提交前匹配前像后os.replace/fsync/checkpoint。rename后只读必要footer/版本，不再跑整行校验。新文件未知、旧目标变化、候选被替换、symlink或设备改变均拒绝。空间开工一次核对，随后按当前候选/旧目标及实际spill计量，不递归扫累计目录。

当前/欠账/历史更新共用这条执行链；不会先upsert当前期再对同一周期history重写。只处理源已完成交付，不能把更新全部历史作为每日默认动作。参考身份与Raw交付范围不一致时停在受影响批次，不能自动扩大到全历史“修一遍”。

### 11.4 第1项恢复、检查与事件

本节是正常执行与中断恢复共用的合同，不增加旁路。必须分别回答：文件是否属于本任务、它使用的输入是否仍适用、它是否已在DG完成登记。前者不能依赖后者；文件完整验证记录也不能冒充DG ready。

**逐文件持久化证据。** 沿现有checkpoint保存freq/period、固定source/target/candidate路径、rule/lower/asof、所属execution identity_hash、Raw完成引用/source_version、参考版本、target_preimage、candidate_version、行数及三项完整校验结果。参考/下限等已在execution.json的值可由其不可变身份引用，不另造独立事实表。候选必须先完整校验/fsync并原子保存validated记录，之后才能os.replace/fsync并保存committed及实际目标version；不能先覆盖再首次保存验证证据。事件回执独立保存在events/<freq>/<period>.json，含文件版本、实际物化ID、三个check及真实event_run_id。

update记录另存validation_hash核对上述完整校验证据，拒绝行数、检查结果或来源记录损坏；它覆盖记录的稳定内容，排除state、提交后version、publish_seconds及hash自身，以允许同一次rename从validated补记committed。复用记录仍核对冻结前像/实际目标版本，不能因该hash排除提交字段而放行未知文件。只计算小型JSON指纹，不hash行情、不更改已完成bootstrap记录合同。

| 恢复时看到的事实 | 动作及限制 |
| --- | --- |
| committed文件精确匹配记录，输入/参考/规则仍相同，真实事件已完整绑定 | 直接复用。0行情SQL、0 COPY，不重复写事件 |
| 同上，但DG尚无对应物化或部分check/事件回执缺失 | 标为文件完成、登记待办，进入事件补记集合。不能因DG还显示旧文件版本就拒绝本任务成果，也不能将其计为已交付 |
| 无checkpoint，或只有未校验/中断COPY | 尚未完成；在原unit范围重新生成这一候选，保留其他已完成文件，不认领半成品 |
| validated记录仍在，目标仍为原前像且候选身份匹配 | 输入仍适用则直接继续提升；候选不再适用只重建这一unit，不删除已有目标 |
| validated记录仍在，候选已不在，目标精确匹配该候选的同一次rename身份 | 先补认真实提交，再决定是否需要新版；只核必要footer/版本，不重做选行/COPY/完整校验。源后来变化不抹去已经发生的提交 |
| 当前目标、候选或证据无法匹配，路径/设备/symlink异常，存在真实失败或错误绑定 | 停止报告，不覆盖、不补假绿、不把未知文件当成功 |

rename恢复只接受“原前像+原候选仍在”或“该候选确已成为目标”两个明确状态。验证原checkpoint时，必须先按原execution核对原候选路径/hash、输入、完整校验及输出身份；不能把别的执行记录复制过来、改identity_hash就放行。这里复用的0 SQL指行情计算/读回SQL，不排除一次集合事件查询；rename记录丢失时允许必要footer读取。

**输入未变：沿原任务继续。** 按指定execution.json的全部unit读取小型记录及stat，在同一集合查询中核对事件；不因某个文件缺登记否认其提交。A/B已经完成而C未完成时，A/B只补缺失登记，C才生成。resume的文件阶段和events的登记阶段仍分开，不为恢复强迫重算A/B，不要求立即逐文件查询/登记DG。

**输入确已变化：统一规划新执行。** 只在当前Raw有合格物化/检查、合法完成receipt且包含本期/当前版本时采用新版。处理次序为：

1. 加载明确指定的原执行，验证原identity/hash、根、频率、规则/下限及完整周期集合；先恢复可证明的rename提交事实。检查文件归属时不要求原整批complete.json或events_complete.json存在。
2. 对原集合逐期比较Raw、参考、规则和截止，分出可复用、待生成、待登记及输入已过时的unit。变化只影响对应unit；缺合法新版、真实失败、未知目标或参考变化无法在原范围内解释时停止，不能扩大到全历史。
3. 源未变则返回原执行；确需新版时创建新execution，保存resume_from_execution_id、原identity_hash和**原完整周期集合**。整批source_completion继续标识原交付范围，不用仅含C的最新receipt覆盖它；每个unit另固定本次实际source_completion/source_version/asof和参考版本。原记录/旧hash不改。后继ID沿现有UUID5身份构造方式，以原ID/hash、原周期集合及本次解析后的输入/参考/规则指纹确定性生成canonical UUID，不含时钟、Dagster storage_id或临时路径。相同恢复意图必须定位同一后继执行，不能不断造新ID。
4. 新执行逐期记录inherited_from（来源执行ID、identity_hash及原期记录指纹）。同版且当前文件匹配的成果写入本执行的committed复用记录，保留原验证来源，不伪造本执行COPY或候选路径；输入过时的unit仅把原已知文件作为可替换前像，重新走原候选生成/校验/原子提交链。原记录证明文件归属，不证明它仍最新。
5. A/B未变、C更新时，A/B文件版本不变、0行情SQL/0 COPY，C用最新合格Raw生成一次。新通知只有C也不能缩小原A/B/C范围；通知中额外的D留给该通知自身处理，不加入本次承接。最新合法Silver结果已覆盖某期时，须凭当前文件和实际绑定事件逐期证明，不得把“时间更晚”当作覆盖。
6. 新执行再次中断，沿它的实际execution_id恢复；相同意图重复到达时先加载已冻结后继及其checkpoint，不重新走“未知目标”准入。再次出现合法输入变化时显式承接当前未完成执行；不扫描staging找最新任务，不形成自引用/循环，不丢前序尚未交付周期。

继承是受校验的来源关系，不是force开关或旧实现兼容层。普通新update没有恢复引用时仍不能认领未知文件；同版成果的来源链仅按显式ID读取，并在本执行记录直接保存已经验证的原始证据引用，不反复遍历/计算所有历史运行。

同一文件阶段/事件阶段内，已校验的不可变execution及继承来源记录只解码/hash一次，后续复用本次调用内存并核对小型文件版本；版本漂移仍拒绝。缓存不跨执行阶段、不缓存行情或当前ready，不新增长期状态/配置。集合检查的第二条SQL可关联该check实际绑定的物化记录，以区分合法旧前像结果与错绑，仍为两条集合查询，不回到逐期API。

**事件可以补部分文件。** update的report_update_events/replay_events按明确执行的unit/checkpoint收集合格的committed文件，允许整批文件尚未完成；无checkpoint的C留待文件阶段，不阻挡A/B登记。篡改/失败记录必须报错，不能当作“未完成”静默跳过。每次按集合读取实际物化和最新已完成检查，排除PLANNED、保留失败；匹配文件版本的成功事件直接复用，已写物化但缺检查只补检查，登记成功而本地回执写失败则读实际事件补回执，不能重复创建物化。

只有当前文件、对应Raw/参考/规则及完整验证仍适用，才补该版本检查。原物化及其成功check仍匹配原前像，或新物化已写成但check仍只有该原物化的旧结果，属于可解释的登记未完成，不能冒充新版本通过，也不能一概当成错绑拒绝；凭checkpoint及实际事件只补缺项。无此版本关系的错误分区/物化绑定和真实失败blocking须在写新绿事件前拒绝，不能先另发物化绕掉失败。事件前后核对所选版本；期间变化的期不完成交付，留给新版恢复，不删历史事件或回滚文件。事件阶段只持有现有Silver锁，不为补记占用Raw锁或创建数据库长事务。

六项check名称、partition归属及真实补报run不变。一个本频率job仍批量处理所选周期，anchor为实际清单最大周期；非anchor在真实run中登记，anchor仅由asset原生返回/检查或独立events补报完成，不能预报成功。三项check复用同一次持久化验证，独立check只在版本证据不适用时核验该期一次，不重算公式。metadata使用该unit实际输入/asof，承接时附来源引用，不把原校验谎报成本执行重新计算。

**完成记录由逐期事实汇总。** complete.json只在本执行全部unit文件完成后生成；events_complete.json只在全部unit实际物化/三check准确绑定或被明确后继交付逐期覆盖后生成。部分补记返回已登记数、待生成/待登记周期及实际执行ID，不生成整批完成。历史已关闭批次的重复通知按§11.6复用既有交付证据；未关闭批次不能套此快捷路径。事件/状态保存失败不回滚数据，也不让后续重复计算已经提交的文件。

**所有入口用同一恢复规划。** StockPeriodSilverConfig增加的恢复引用、job重试、deliver_update_asset及CLI resume共用以上流程；不得分别实现一套接手逻辑。CLI build仍只做首次生成，无action仍帮助；resume仍只做文件阶段，不增加CLI动作/flag，不写DG事件。resume加载update时，按需以当前选定instance只读核对新版证据；不能取得实例/合法交付则保留文件、报告原因，不猜源。需要承接时先输出原ID、实际后继ID及复用/重做范围，再按该后继继续；结果中的run_id必须为实际执行ID。asset必须沿此返回ID加载记录、返回anchor和补记事件，不能仍硬读传入旧ID。第2项cursor记录实际执行ID；需要新Dagster run仍遵守失败后不自动盲重试及正式授权，不靠换run_key放行。

CLI events仍只有登记能力：可补原任务中仍适用的已完成文件，不下载、不COPY、不覆盖、不生成承接执行；其他期未完成时如实返回部分结果和恢复动作。它不能偷偷接受新Raw再重算，也不能为补A/B登记先要求C完成。首次bootstrap的原CLI/审计报告合同及其已完成验收不变，本次部分补记/承接扩展仅适用于update。

取消检查覆盖规划unit、COPY/验证前后、提升前后、事件集合与逐条写入边界；长SQL沿现有interrupt机制，按实际emit时间预留30秒余量。单进程、无新worker；TERM/KILL保留候选/文件/记录，内核释放锁；取消后不领新unit。正式数据损坏、未知写者、未经发布的输入或规则变更不属于自动恢复范围，停止讨论。

### 11.5 第2项Raw交付通知及全部消费者

拟增加一个小型metadata合同goldenshare/period_completion：version=stock-period-completion@1、raw_execution_id、file_receipt_hash、upstream_batch_id、freq、file_count。引用固定staging/stock_period/runs/<raw_execution_id>/manifest.json及complete.json，不复制文件清单进metadata，不含token、逐股数据或任意路径。上游batch_id复用build_batch_id，payload含producer_run_id=Raw执行ID、既有file_receipt_hash及freq；复用build_upstream_triggered_run_key。Dagster storage_id仅作查事件的cursor，不进入batch_id、run_key或业务范围。

该小合同的类型/纯校验归Raw生产者的run_contracts/stock_period.py；第1项先实现共同引用校验，第2项接生产通知，Silver消费同一定义，不让Raw导入Silver模块或两边各造一套hash。保留原VERSION/Raw identity及complete文件结构，新增的是独立的事件引用版本。

Raw每个完整文件批次，对实际files中每个受影响频率发一条AssetObservation到对应既有Raw资产；无变化频率不发，纯anchor待办补记不制造新批次。观察表示files_complete，**不是Raw检查已通过或Silver完成**。各实际文件物化带同一小引用，便于后续定位已被更新的旧通知。事件只引用既有完整receipt，不修改Raw身份/hash、SQL、HTTP参数、21列、下载/文件提交行为。

在run_period/replay_events增加内部交付回调，通知写入沿既有事件阶段；每频率的通知receipt保存在该Raw run既有events/completion/<freq>.json，含batch身份与实际通知ID。通知写失败留待补报，不能把新增事件待办记成全部events_complete，不影响已提交Raw；崩溃在通知成功/receipt前可重复通知，消费以稳定batch_id去重。events重放仍只有事件写入，不执行下载、源计算或文件替换；不为了添加新metadata回补所有历史物化。

当前通用readiness通过fetch_materializations和实际检查绑定取证，不依靠资产“最近事件时间”。新增observation不得当作物化/check成功，也不得改变Raw日常完成水位；隔离测试必须覆盖“只有通知/更新了事件时间但无合格物化检查仍不ready”。catalog同步两Raw的新增通知event_policy及两Silver的更新/事件合同，不改变其列、路径或检查名。

同步迁移当前真实入口：stock_period_update的日常、主动history、handoff及其事件闭包，stock_period_history_cli的resume/events/handoff，ops/stock_weekly_bootstrap_checks的周线补报。最后一个入口只允许发周线通知，不顺带补月线。无Dagster实例的底层离线调用只形成原文件证据、不伪造通知成功；明确的events阶段补齐。所有生产回调及直接测试同时更新，不保留正式链中只有旧单文件事件、不通知交付的隐蔽分支。

### 11.6 第2项sensor、readiness及历史更新不遗漏

新定义名称固定为silver_stock_weekly_update_job_sensor、silver_stock_monthly_update_job_sensor，分别选择原同名Silver update job、原cn_a_stock_week_ends/cn_a_stock_months；default_status=STOPPED。源完成才触发，不加第二个19:30门槛，不用交易日限制挡住周末的合法历史交付。期望周期完全来自本次Raw实际files；不是每日造一根周/月K，也不是日期continuity窗口扫描。

<a id="period-silver-sensor-classification"></a>
**已确认的sensor分类与同步范围。** 按orchestrator/AGENTS.md的Sensor Definition Tags分类门禁，两个新定义均使用下列definition tags，不能用run tags替代：

| sensor定义 | goldenshare/sensor_domain | goldenshare/sensor_target_layer | goldenshare/sensor_role | definition默认状态 |
| --- | --- | --- | --- | --- |
| silver_stock_weekly_update_job_sensor | quote_data | silver | asset_update | STOPPED |
| silver_stock_monthly_update_job_sensor | quote_data | silver | asset_update | STOPPED |

仅复用run_contracts/sensor_tags.py的build_sensor_tags(sensor_domain=SensorDomain.QUOTE_DATA, target_layer=SensorTargetLayer.SILVER, role=SensorRole.ASSET_UPDATE)；不新增helper、枚举、标签键或配置，不在sensor内手写标签字典，不混入日期、分区、代码、状态或cursor等动态值。标签仅用于Automation页面分类，不改变执行范围、触发窗口、原Raw sensor状态或水位。

同步文件固定为[运行合同治理](dagster-run-contract-governance.html)、[资产与任务拓扑](../architecture/dagster-asset-job-topology.html)及tests/test_run_contract_static_gates.py；两份治理文档本次先记已确认设计、待开发，不把新sensor加入已实现清单。后续开发时更新现有EXPECTED_SENSOR_DEFINITION_IDS并沿test_sensor_definitions_use_registered_definition_tags验收，同时在本域sensor测试中断言两个定义的精确分类、目标job及默认STOPPED；不得删除名单核对或放宽其他sensor门禁。正向为两定义均复用统一helper且三项值正确；反向须抓住缺键、错层级/角色、手写字典、漏登记或意外默认RUNNING。本轮仅补文档，代码和上述新增断言均待管理员再次确认后开发。

单tick先看根可用性、当前相关运行/已有待办，再从该频率Raw资产读取cursor之后最早一条本合同observation（limit=1），校验小引用及完整清单；没有通知则0 DuckDB/0 Parquet。一次最多一个Raw交付、一个RunRequest，先处理最早未交付批次；批次内历史周期是既有Raw实际改动范围，不在sensor中发现或重算全历史。一次Raw周线任务若也改了月线，会发月线资产通知，月线sensor由此处理全部相关月份。

新增本域batch readiness helper，按明确的asset/check/partition集合查询：一条集合SQL取Raw和Silver各期最新物化，一条集合SQL取各期/各check最新**已完成**结果（包含失败、排除PLANNED）。使用当前安装Dagster SQL event log schema及只读index_connection，参数化过滤；只对当前受支持SQL存储工作，未知后端拒绝而非退回逐期API。返回最多2N物化+6N检查，不先limit N条历史再在Python中碰运气。Raw必须具备通过、blocking、分区及实际物化ID绑定，metadata版本匹配真实文件/receipt；Silver文件归属按§11.3—11.4的事件或明确checkpoint识别，DG缺登记标为待补而非ready。未知文件、真实失败/错误绑定阻断；普通readiness仍必须具备真实物化和完整检查，不把恢复归属证明扩成下游放行。不改Dagster表/schema或通用readiness语义。

sensor查询用于准入；job启动时同一helper核对实际输入/前像，防止排队期间过期，随后仅在提交边界查精确文件版本。这里重复的是启动边界的小型状态核验，不重复行情扫描/完整性审计；不得再加逐unit、逐check的Dagster查询。不能证明批量SQL语义等于现行正式检查绑定时，停止该项实现并先讨论。

旧通知被新Raw覆盖时：先按原通知列出的周期集合查询最新Raw物化；只有最新合格物化的本合同引用能定位一个完成receipt、且该receipt确实包含当前期/当前版本时，才可在**新执行冻结前**选用更新版本。相同新receipt只读一次，不调用要求旧complete所有文件仍为原版本的completed_files去消费旧通知。记录每期old→new的覆盖关系；不丢原通知里尚未被后续改动覆盖的其他周期。新通知额外涉及的周期仍由其自身消费，不能仅处理最新通知就跳过旧范围。未发布的新文件、未知引用或不合格检查必须等待/报错，不猜最新路径。

执行冻结后源又变：保留已提交文件与旧执行，不改原计划；恢复沿§11.4统一规划，指定当前未完成执行建立后继，并凭同版本checkpoint/实际事件跳过已完成unit。不能先要求旧整批完成或DG全部登记，才允许承接。旧批次只有其全部周期已交付、或逐期被明确的新完成结果覆盖后才能ack；覆盖关系沿既有事件回执保存后继ID/hash、该期实际版本与事件引用，未完成覆盖不生成events_complete.json。不能仅因run被提交、cursor读到通知或最新周期成功就推进。

cursor保持O(1)：schema_version、已消费observation位置、当前batch_id/observation位置、当前实际execution_id、最后decision/evaluated_at；不放完整文件/分区/错误清单。承接后保留原batch待办，实际execution_id取统一规划/执行结果；原→新来源在execution/checkpoint，不塞cursor或改原batch_id。只在文件及事件完成证据满足后ack；sensor崩溃重复看同通知，由稳定run_key及显式执行记录防重复。已有活动run只跟踪。失败/取消/检查异常保持待办；输入未变给出原ID恢复，合法新版则给出明确的承接配置及后继ID，不每60秒自动重试失败任务。需要新真实运行时沿统一repair-attempt run-key构造器并明确批准范围；execution的后继ID不是新run_key，禁止用它或时间戳绕过调度去重/授权。

**第2项完成确认的实现落点。** 资产返回后Dagster才产生anchor原生物化/检查，所以资产内只保存非anchor登记事实，不提前写整批完成。sensor下一tick在原两条集合查询中确认全部实际文件及绑定检查后，沿原events/<freq>/<period>.json及events_complete.json汇总登记事实，再推进cursor；不是再次运行CLI、发事件或计算行情。这里只补既有小型状态JSON，sensor仍不写业务数据、不请求源、不COPY、不补DG事件；“只读”指消费数据和DG证据，不把必要的完成回执误列为范围外任务。汇总与文件阶段共用现有Silver锁，真实失败/错绑定或版本不符不写完成，回执写失败不推进cursor、不回滚文件；重启后从实际证据补记。已完成批次复用既有回执，后继完成沿原record_update_coverage关闭祖先，不改原执行身份。本段落实原§11.4/§11.6收尾要求，不增加配置、job、扫描、查询次数或独立审批步骤；隔离验收覆盖job成功但回执未保存、回执保存失败续跑、重复旧通知及真实检查失败仍拒绝。

批次全部周期被2014下限排除时，记录范围排除后ack，不创建空Silver任务。已确认完成的同batch重复通知直接复用其交付记录推进通知位置，不要求旧输出在后来合法更新后仍保持旧版本；当前数据是否对齐由后续真实新批次负责，不能因重复旧通知重新生成行情。未完成旧批次则必须按上述逐期覆盖规则处理，不能套用这个快捷路径。

### 11.7 性能预算、必要检查与隔离验收

| 路径/检查 | 防止的风险、边界与读取模型 | 可复用证据及成本/超预算处理 |
| --- | --- | --- |
| 通知/执行身份 | 漏历史范围、假完成、改旧指纹；按一个通知读一个完整receipt，旧通知仅追加其当前版本对应的唯一receipt | 不扫staging目录；JSON hash只校验小清单，不重新hash行情文件。路径/合同异常阻断 |
| sensor热路径 | 错触发、重复run、错误ready；每tick最多1次通知查询、2次运行状态查询、2条集合readiness SQL，共5次存储读取；0 DuckDB/0 Parquet/0源请求 | 1个交付，N由实际变化清单固定；当前范围容量参考周656/月154，不作为永久业务上限。无待办时短路；N增长不截断，容量验收不足则先报告再扩大预算 |
| job/恢复规划 | 排队后输入/前像过期、误认任务成果；同集合最多2条readiness SQL，显式读取原执行/逐文件记录及本次唯一Raw receipts，再固定输入/参考版本 | 只读所选集合的metadata/stat，不重做全湖库存/价格审计；合法新源逐期承接，未知前像/未发布输入拒绝 |
| 行情文件阶段 | 21列/择行/整期/内容及范围不符；一连接、参考读一次，每变化期1次Raw投影、1次COPY、1次候选完整验证、rename后1次footer | 三check复用同一证据；选行金样本已覆盖的规则不另跑完整审计。N文件、最多N候选与N目标提交，不按股票扇出 |
| 同版本/恢复 | 成功成果重算、缺登记误判未知；逐文件归属、输入适用性及DG登记分开判断，显式来源记录同批只读一次 | 已提交同版unit 0行情SQL/0 COPY，事件失败只补缺项；rename记录丢失只读必要footer。真正输入失效仅重做对应unit，不使整批成果失效 |
| 资源/空间 | OOM、无空间、扫累计目录变慢；沿原引擎默认，空间按本unit和实际spill计量 | 无新增内存/并发/耗时业务门槛；锁内文件阶段不持有数据库长事务，事件阶段不占Raw锁 |
| 事件/收尾 | 漏物化/check、假绿/错绑、状态失败重算数据；新文件版本最多物化+三check共4N，已有事件复用，Raw通知每批每频率1条 | 每次只对本次可登记集合最多两轮集合读取（登记前、确有新物化后各2条SQL），不逐文件查DG。部分补记不宣称整批完成；检查所选版本并汇总既有记录，不再读回行情 |

§10.10是旧生成路径实测：810文件31.889秒、事件110.642秒、RSS约855MiB，不能当新增覆盖/批次接线验收。两份原缓存小样本约0.02秒/文件与约0.0003秒完成续跑仅证明旧路径模型，不外推真实全市场日更。新路径只在以下隔离场景顺带计时：少数股票、当前周/月及必要历史/边界周期，用已有源片段；metadata容量测试使用656周+154月的字面/合成事件，**不重跑810文件COPY或完整bootstrap**。记录实际SQL/存储调用数、文件扫描/COPY数、启动/锁等待/事件耗时和RSS/spill。热路径目标为明显低于既有60秒gRPC超时，具体耗时待测；这是工程目标，不新设未经依据的更紧拒绝阈值。出现线性逐期API/重复全读、超时或容量模型不符即停下讨论，不偷偷降语义或追加大范围审计。

| 验收要求 | 独立正向证据 | 反向/故障必须拒绝或正确恢复 |
| --- | --- | --- |
| 原合同不变 | 复用真实Raw schema、原21列/NULL/Decimal金样本及20200228/29整行expected、首周/上市首月字面样本 | 改字段/单位/日期类型/价格，删边界整期、同版异值冲突不能通过 |
| update范围 | 已有周期整期替换、新周期创建；跨周/月欠账与因子历史同批去重；仅旧键所在期也同步移除 | 未选频率/分区不写，未知目标/丢失旧文件/源空或读取失败不覆盖；bootstrap仍拒绝既有目标 |
| 真实生产者接线 | 临时根用实际Raw run_period与真实合同的源替身生成receipt/文件/通知，隔离instance通过实际sensor→两Silver job/check | 不能手造与生产者不符的manifest/schema骗过集成；source HTTP被替代的层次明确，不声称本轮源联网验收 |
| 两频历史传递 | 周线Raw任务同时写到两频历史，两个通知各1，两个Silver job覆盖全部对应周期，1频率1批而非N次run | anchor-only、仅通知触发job所属频率、月中冒记整月完成、漏仅旧键分区均失败 |
| 批量ready/去重 | 按安装表合同构造真实隔离事件；已完成同版、重复通知、cursor重读、事件重放不重复COPY | PLANNED遮盖、最新失败、错物化/分区、假receipt、storage_id进业务key、未知后端不能通过；SQL/API次数不随N逐期增长 |
| sensor分类及登记 | 两定义使用既有build_sensor_tags，精确为quote_data / silver / asset_update且默认STOPPED；两份治理文档、定义名单与本域断言一致 | 缺键、错层级/角色、手写字典、漏登记、意外默认RUNNING不能通过；不将尚未开发的断言写成已通过 |
| 原ID正常恢复 | A/B已提交而C未完成、输入不变；CLI resume及job共用原ID，A/B文件版本不变且0行情SQL/0 COPY，C仅生成一次 | 缺登记不能判未知文件；存在坏checkpoint/未知目标不能借恢复放行；不新建任务重写A/B |
| 部分文件补登记 | 无整批complete.json，events只补A/B，C无文件仍留待办；已有物化缺check、登记成功回执失败均按实际事件补缺 | 不生成整批完成，不写C的成功；禁止下载/COPY/改文件，不重复物化；正常旧前像事件与无依据错绑必须分别覆盖 |
| 新Raw承接 | 原范围A/B/C仅C输入合法更新，复用A/B完整验证及文件，只重建C；新批额外D不加入。周/月共用参数化小场景 | 未发布版本/receipt无C、错原执行/跨根频率/自引用循环/篡改hash或记录/目标漂移/真实失败仍拒绝；不改旧指纹，不漏A/B |
| rename及事件故障 | 原前像+已验收候选、rename成功记录失败两态均恢复；源在中断期间变了仍先识别真实提交，再仅对失效unit采用新版 | 候选被换、目标身份不符、错误绑定拒绝；不能因补记先重算或先伪造新物化绕失败 |
| 再次中断与覆盖 | 后继生成/登记再次取消或TERM/KILL，沿实际后继ID接着做；重复恢复意图定位同一记录，原范围逐期真正交付后才关闭 | 不重复COPY已完成成果、不造无限新ID、不丢原期；只完成最新C不能关闭A/B/C，未完成覆盖不算完成 |
| 取消/恢复边界 | 规划、COPY/验证、replace及事件边界受控退出；单进程、锁释放，未选频率/周期不动 | 不重新清根、不遗留worker、不启动新unit；事件失败0源请求/0 COPY，锁内未解释的版本变化停止 |
| 资源/边界 | 缓存真实片段小场景+合成metadata容量；临时Lake/staging、隔离instance及本项目工具 | 正式路径/网络/Prod/R3调用静态或替身禁止；不写Raw行情、不启停sensor，不把旧43项当新功能通过 |

第1项先完成update及上述恢复正反测试：先运行输入不变的小场景，再沿原§11.10证据对应的隔离场景主动制造仅C变化，明确区分测试假设与正式事实；周/月按相同机制参数化，不重复全量审计。第2项在同一小型场景接入真实Raw生产者、通知、sensor和两频job/check。修复只重跑受影响项，版本固定后一次直接回归；不把旧8项、5项或首次43项通过冒充修正后验收。原扩展回归的15个其他数据集治理缺项及停牌专用启动器问题不归本任务修理，不弱化断言、不声称全仓通过。

### 11.8 具体文件白名单与消费者迁移

以下相对lake_console/orchestrator/，另标仓库相对路径的两份治理文档除外；第1项不提前实现第2项通知/sensor。原§10.8已完成的Silver文件与第1项修复已提交d865e640，不能当作后续全新开发重做。

| 文件 | 第几项/具体改动 |
| --- | --- |
| src/orchestrator/defs/run_contracts/stock_period.py | 1：Raw完成引用的小型类型/纯校验；2：供Raw通知与Silver共用，原Raw版本/请求合同不改 |
| src/orchestrator/defs/run_contracts/stock_period_silver.py | 1：update配置、resume_from_execution_id及互斥校验、执行/继承引用、确定性后继身份；2：集中sensor策略及批次消费者合同 |
| src/orchestrator/defs/stock_period_silver.py、io/stock_period_silver.py | 1：统一恢复规划、已知成果/前像、逐期输入解析与复用、继承验证、实际执行ID返回、固定锁顺序、先识别提交再判断失效、rename恢复/进度；不改选行规则 |
| src/orchestrator/defs/assets/stock_weekly.py、stock_monthly.py；jobs/stock_weekly.py、stock_monthly.py | 1：既有Silver job按本频率处理交付清单，真实anchor/其他周期登记；2：Raw asset小型完成引用接线。asset/job/分区身份不改 |
| src/orchestrator/defs/checks/stock_period_silver_checks.py；bootstrap/stock_period_silver_cli.py | 1：检查复用真实来源及当前版本；resume共用恢复规划并明确实际ID，events支持update部分committed文件补记/缺项幂等/逐期覆盖，整批完成只汇总；无新增CLI动作/flag，build及首次bootstrap行为不改 |
| 新src/orchestrator/defs/asset_guards/stock_period_silver_readiness.py | 1/2：本域集合SQL事件/文件绑定读取；隔离SQLite及当前正式SQL后端合同测试，不改通用helper/数据库schema |
| 新src/orchestrator/defs/sensors/silver_stock_weekly_update_job_sensor.py、silver_stock_monthly_update_job_sensor.py | 2：默认STOPPED，消费小型通知、按批选择原job、cursor及blocked原因；共用逻辑放本Silver模块，不各写一套 |
| src/orchestrator/defs/bootstrap/stock_period_history.py；stock_period_update.py | 2：完整receipt传给内部事件回调，文件阶段后通知/事件重放及metadata接线；不改下载、HTTP、SQL、范围或旧冻结身份 |
| src/orchestrator/defs/bootstrap/stock_period_history_cli.py；ops/stock_weekly_bootstrap_checks.py | 2：迁移全部现行事件入口，保持events-only、handoff和周线补报边界 |
| src/orchestrator/defs/catalog/lake_assets.py | 1/2：仅同步两Silver更新/写入/事件/性能合同和两Raw的完成通知event_policy；本次没有新增列，不需要再改schema/paths/name_mapping |
| tests/test_stock_period_silver_contracts.py、test_stock_period_silver_projection.py、test_stock_period_silver_execution.py、test_stock_period_silver_events.py、test_stock_period_silver_jobs.py | 1：扩展现有文件；2：新增tests/test_stock_period_silver_sensors.py、test_stock_period_silver_daily_integration.py，覆盖上述正反与成本计数 |
| tests/test_stock_period_contract.py、test_stock_period_history.py、test_stock_period_history_cli.py、test_stock_period_recovery.py、test_stock_period_handoff.py、test_stock_period_handoff_memory.py、test_stock_period_update.py、test_stock_period_combined.py | 1/2：纯引用合同、真实回调消费者及周线补报op通知边界断言；handoff_memory已确认纳入，仅同步事件回调/测试替身，保留原RSS、6GiB覆盖、取消、原身份/成功源复用及重复handoff断言，不改预算或断言强度。均为已核实存在的承载测试，不新增无关旧链测试或扩大回归 |
| tests/test_asset_check_incremental_governance.py、test_asset_governance_contracts.py、test_run_contract_static_gates.py | 1/2：只加本域范围/事件/调用次数防回流断言；第2项同步EXPECTED_SENSOR_DEFINITION_IDS及既有统一tag门禁，精确分类/默认状态在本域sensor测试断言；保留其他数据集门禁 |
| 原总方案、共享LLD、月线LLD；本任务必要验收报告 | 3：实际状态、配置/性能、正反证据、提交白名单及未完成项 |
| lake_console/docs/design/dagster-run-contract-governance.html（仓库相对路径） | 2/3：仅登记两个Silver sensor分类、统一helper及设计/实现/正式启用状态，引用本节；不修改通用治理合同或其他sensor |
| lake_console/docs/architecture/dagster-asset-job-topology.html（仓库相对路径） | 2/3：仅补两条Raw通知→Silver sensor→既有job的计划拓扑、分类及默认STOPPED；未开发前不列入当前活动定义 |

同一文件有他人改动只提交本任务块，尤其catalog。无需改变src.foundation/ops/biz/app、其他Tushare资产、依赖锁文件、运行服务配置或前端。实际发现新增消费者/需要新增配置或入口时，先补本表及影响面再讨论，不以“白名单类似路径”为由扩张。

**防止再次漏项的开工对照。** 根因是已有规则未完整落到设计及文件白名单，不另加重复的全局规则。以下检查并入原有开工审计，仅检查本次相关规则、文档和代码，不扫数据、不重新跑既有验收：

| 已有要求 | 本次必须有的落点 | 对账依据及失败处理 |
| --- | --- | --- |
| AGENTS要求先明确sensor分类 | §11.6两定义、三项标签、统一helper和默认状态 | 对照当前sensor_tags.py枚举；漏定义、漏值或来源不清时不能进入编码 |
| AGENTS要求同步治理文档 | 本表显式列出的两份HTML及原三份设计文档 | 确认两份HTML均引用同一§11.6；不能只在聊天中承诺同步或漏入白名单 |
| 定义和测试不能一起漏登记 | 现有EXPECTED_SENSOR_DEFINITION_IDS、统一tag静态门禁及本域sensor正反测试 | 开发时同步迁移；静态名单不能删除或放宽，精确分类/STOPPED另有直接断言 |
| 设计、实现、验收、正式启用分别记录 | 五份文档本域状态与本次授权一致 | 仅补文档不写成已开发；代码通过不写成已加载、已启用或真实日常已通过 |

2026-10-17管理员已确认本次分类及两份治理文档补项；本轮只修订上述五份文档，完成文档一致性检查后停止，等待管理员再次确认再开发，不自动进入第2项代码或第3项正式操作。

<a id="period-silver-consumer-preflight"></a>
**后续消费者补齐与完整静态核对（2026-10-17）。** 上段为b9ba7163文档补齐时的授权边界。管理员随后确认补齐test_stock_period_handoff_memory.py并继续审计；本轮仅修正文档/白名单和审计证据，没有修改生产或测试代码。详细结果及文件定位见[开工审计报告](../../../reports/dg_stock_period_silver_auto_preflight_20261017/report.md)与[消费者清单](../../../reports/dg_stock_period_silver_auto_preflight_20261017/consumer_inventory.json)。

本轮以CodeGraph callers/impact补充实际源码引用、AST导入/别名/事件回调及CLI/job定位，检出44份相关引用文件，全部分类，未分类差集为0；其中历史审计驱动只作为历史材料，不执行或迁移。Raw生产者本身、两份共同合同和既有静态门禁另按本节显式根文件核对，不能因其没有引用自身模块名而漏掉。首次分类表漏填已在原计划中的test_stock_period_update.py时，差集检查实际拒绝；补齐分类后通过。另故意删除handoff_memory分类也能检出，不能仅用“已读规则”的文字代替这项核对。

| 核对类别 | 文件/真实入口 | 本次处理及边界 |
| --- | --- | --- |
| 生产事件链，必须同步迁移 | stock_period_history::run_period/replay_events；stock_period_update::execute_daily/deliver_asset/report_file_events/handoff_bootstrap；stock_period_history_cli::resume/events/handoff；ops/stock_weekly_bootstrap_checks | 均沿本表既有白名单；完整交付引用传到全部真实事件入口，周线补报仍只周线，离线文件执行不冒称通知成功 |
| 已确认补齐的直接测试消费者 | tests/test_stock_period_handoff_memory.py | stopped_handoff及其恢复/取消/CLI handoff使用事件回调；仅迁移回调/替身，不改原内存与持久化断言 |
| 真实入口的必要回归，不默认改代码 | tests/test_stock_period_integration.py；test_stock_monthly_definitions.py；test_raw_stock_weekly_update_job_sensor.py；test_raw_stock_monthly_update_job_sensor.py；现有周线补报job | 分别覆盖现有小型CLI→events→handoff→原生Raw job、两频原生job/check、Raw sensor水位/窗口和周线补报边界。复用原小样本，不加全市场bootstrap；确需改测试时仍先核对本次范围，不将“回归”当成任意改代码授权 |
| 原Silver及共享夹具消费者 | 既有五份test_stock_period_silver_*.py，尤其test_stock_period_silver_contracts.py中的capture/publish_completion_contract | 统一复用真实Raw完成通知；第2项集成不再用第1项的临时metadata适配器冒充真实生产者。关键expected仍取独立字面金样本 |
| 不因回调迁移而重做 | stock_weekly_update.py、stock_monthly_update.py；tests/test_stock_period_source.py、test_stock_period_storage.py、test_stock_period_candidate_fragments.py、test_stock_period_memory_resume.py | 分别是原策略或HTTP/IO/COPY/RSS边界，当前没有本次单文件事件回调；代码保持。只有实际修改触及其行为才做定向回归，不默认重跑全部旧链 |
| 退役入口及无跨子系统消费 | 四个旧周/月history/events CLI、Raw旧写入口；foundation/ops/biz/app、业务API/前端 | 旧CLI仅抛retired错误，不恢复或迁移；本轮引用定位未发现跨子系统/API/前端消费者，不扩大生产影响面 |
| 已确认清退的逐文件源码登记 | tests/stock_suspend_confirmed_test_runner.py；tests/test_protected_test_runner_inventory.py | 2026-10-17管理员要求去掉无必要的测试保护维护。删除consumer手写源码名单和全定义名单覆盖检查，按下文允许治理测试只读项目源码；不再为新增sensor逐文件登记 |

**逐文件源码登记清退（2026-10-17，管理员已要求实施）。** 治理测试本来就要发现全部定义，另维护一份同范围手写源码名单没有独立业务校验价值；它把正常新增源码变成了无意义的权限同步事项。此前“仅追加两个路径、等待权限确认”的建议撤回，不再作为周/月开发阻塞。

- 代码仅改上述两个测试文件：删除CONSUMER_SOURCE_FILES；consumer范围不再枚举、预检或逐文件hash整份源码，sandbox只读允许固定的src/orchestrator目录。其他scope仍沿原名单和拒绝规则；CLI参数、suite、批次、业务断言及测试support不变。报告注明consumer只读源码根，不把未做的逐文件hash写成已核验。
- 仍拒绝项目源码写入、正式Lake/instance/凭据及网络访问；源码中的符号链接不能借此读取目录外文件。保留现有源码以外的精确读权限，不允许整个仓库或其他目录子树，不新增配置、依赖或长期入口。正式业务代码、sensor、事件和数据均不改。
- 测试改为证明未登记的新源码可读、源码写入/目录外读取及外指链接被拒绝、网络保护保持；原四个非consumer scope的缺失/链接文件仍拒绝。只使用临时源码/哨兵，不拿正式资源做反例；再运行现有catalog治理12项，业务断言不减少。
- 成本只涉及小型源码/临时文件及既有治理测试，无源请求、SQL或Parquet读写。去掉整份手写清单及consumer逐文件hash，不新增预算或审批点。失败即报告，临时证据保留后可重跑；不涉及业务提交、回滚、checkpoint或正式恢复。

这项调整已同步回停牌专项原方案/LLD的当前补充说明，历史隔离验收保留。实际验证：8项定向边界测试通过，原catalog治理12项及513个subtests分两批通过；isolation、adapter、regression、root-guard四种策略及源码范围与修改前逐字一致。两批consumer报告的source_files/source_sha256均为空，准确记录固定源码只读根。Ruff、文档完整性及diff检查通过。证据位于/private/tmp/dg-source-registration-retirement-5vbx91nc/，含原源码、catalog.log、catalog-summary.json及policy-comparison.json；本轮未运行正式资源或周/月业务链，未提交。

**准入判断：** 已批准的handoff_memory白名单缺项已修正；设计分类、事件合同、消费者定位和必要回归落点可继续复用。逐文件源码登记按管理员本轮要求清退，不再等待追加两项权限确认；清退及定向验证完成后报告，不自动开发两个sensor或执行正式操作。后续变更只复核本次消费者差集和对应直接测试，不重复行情审计。

### 11.9 第2项正式交接与第3项结案清单

此前开发轮无正式操作授权。2026-10-17管理员确认真实下载验收等周一，先完成当前可验证的正式接线；精确操作和读写边界见§11.13。工作目录为现有orchestrator，现有.venv/bin/python3 -B，DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home；Lake/staging沿两正式根。只加载确认版本，其他任务改动若无法隔离先停，不切分支/worktree、不重启无关服务。

1. **接线基线只核对一次。** 复用§10.10已验收文件/事件与截止2026-10-16事实，查询其后两Raw资产是否有新交付头记录；没有则直接作为基线，不重写810文件或历史事件。存在新交付时只按这些记录定位相应Raw完成receipt处理差额。旧记录缺本合同引用且无法准确定位receipt则暂停交接讨论，禁止把cursor直接设到最新而吞掉变化。
2. **加载与启用分开。** 先加载新Raw通知和两个默认STOPPED的Silver sensor；只读确认定义、Raw原状态/水位、Silver基线及无冲突写者。经明确批准，初始化新sensor消费起点，再启用两个新sensor；不重置Raw cursor、不改19:30窗口、原source配置或其他sensor。具体event位置取实际基线，不写死本次审计的cursor数值。
3. **一次真实日常交付。** 等待已有Raw日常链真实产生新结果，由新通知驱动所需Silver；不为验收重下源/全量bootstrap。只对本交付清单汇总实际更新、同版跳过、范围排除、文件/检查/物化绑定及耗时；未命中分区用执行路径/清单边界证明不写，不为此全湖hash。休市无新交付时明确“待首个样本”，不把隔离替身或手工重报旧版本冒充真实日更。
4. **故障只处理当前待办。** 输入未变沿原execution_id resume；已有合法新Raw时按§11.4显式承接原范围，输出实际后继ID，已完成同版不重算。事件失败只events，允许整批未完时补已完成文件；部分补记不能关闭批次。未知源/目标、真实失败check或未核实写者先阻断讨论，不重做审计或静默覆盖。若需暂停新自动化，必须获得对应sensor操作授权；本节不预授权自动停Raw或其他任务。
5. **按事实结案与提交。** 清单逐行列“要求、实际文件/函数、正向、反向、真实证据、通过/未完成”。阶段分开写：首次生成完成；日常程序隔离通过；正式定义/通知/新sensor交接完成；首个真实交付通过。最后一项未发生就留待办，不因代码提交宣称全部DG工作结束。首次日志/810物化/2430检查已完成，不再列缺失项。

提交必须由用户明确要求；白名单包含§10.8现有Silver实现/测试/必要报告、§11.8实际修改文件、三份原设计文档及本域两份治理文档同步内容，不混入R3/资金流/AGENTS/研究/新闻/Wealth。暂存前审查差异，暂存后核对name-status、逐块diff与whitespace；共享文件分块暂存。无法拆清就报告，不整文件撤销或提交。无推送。文档链接/状态检查不能替代代码/集成验收；第1项修复前阻塞见§11.10，修复及隔离验收见§11.11，正式日常验收仍未执行。

### 11.10 修复前缺陷证据与整改落点（2026-10-17历史记录）

**当时状态与事实边界。** 设计ba9507fca后，第1项的Raw完成引用、集合事件读取、更新前像、单频批量job及事件补报已部分实现，发现以下缺陷后停止；没有进入第2项通知/sensor开发，没有代码提交、重载、正式Lake/staging/事件或sensor操作。其后先提交恢复设计dbec0343，再完成§11.11修复/隔离验证。原先“只增加旧执行ID允许接手”的建议已由§11.2—11.4完整规则替代，不能再作为独立放行办法。

**隔离证据，不是今天的正式数据变更。** 临时根/private/tmp/dg_period_silver_resume_conflict_92v3tuj9；结果见[复现JSON](/private/tmp/dg_period_silver_resume_conflict_result.json)，完整日志/private/tmp/dg_period_silver_resume_conflict.log。使用实际Raw run_period、Silver生成器和隔离Dagster事件库；HTTP由合同字面样本替代。测试主动更新临时C文件以模拟中断期间输入变化；formal_writes=0、network_requests=0。不得据此声称今天正式Raw更新、存在正式写者或当前任务必然因新Raw阻塞。

1. 旧执行ef13ab4c-df3e-4562-b2a1-95840fff9063计划处理2014-01-03、2020-04-03、2026-10-16三个周文件，记为A/B/C。A/B已原子替换并保存committed checkpoint，分别1/2行，三项候选检查通过，源/目标当前版本与记录一致。此时取消，整批文件完成记录和DG登记尚未形成。
2. 测试仅刷新临时C的Raw，生成另一个合法receipt，A/B输入未变。原ID恢复在全批检查处报silver_source_changed，原hash未变。此错误说明旧冻结输入不能直接用于C，不应推导为A/B成果失效或不可补登记。
3. 新ID准备原三个周期时，A/B虽然有本任务完整校验/提交记录，DG仍只有原基线物化。update_inputs因事件版本与文件不一致报period_materialization_file_version_invalid。只处理最新C通知又会遗漏A/B待登记，当前代码没有完整恢复路径。

**根因。** 逐文件保存允许“文件做好、登记没完成”，但原准入用DG登记反证文件归属；全批源检查和整批complete.json事件前置又把互不相关的文件绑死。必须分离归属、输入适用性、登记三个判断，以逐文件事实恢复，整批完成仅作汇总。这是设计/实现缺陷，未知文件及真实失败门禁不因此放宽。

| 缺陷/当前实现点 | 必须完成的修正及验收落点 |
| --- | --- |
| update_inputs只认当前DG版本 | 同一次集合取证区分真实失败、正常登记未完成及未知文件；显式原执行的完整checkpoint可识别已知成果。补“DG还是旧基线但A/B可恢复”和篡改/错绑拒绝 |
| build全批源漂移即退出 | 先核对每个提交事实，再按源/参考/规则区分复用和失效；同版原ID续跑，合法新版按原集合显式承接。A/B不变、C只生成一次，旧hash保留 |
| publish先核源而后认rename | 先识别已验收候选是否已成为目标并补记；再处理是否需新版。不能丢已提交成果，也不能将未知目标认作rename成功 |
| report_update_events依赖整批complete.json | update允许按部分committed文件批量补缺，已有事件复用，整批未完成不写events_complete.json。C未完成不挡A/B补登记 |
| 配置/CLI/asset仍用传入旧ID加载 | 合同和统一规划保存原执行引用/hash/逐期来源；resume结果明确实际ID，asset/check/事件沿实际ID加载，后继再次中断仍可恢复。events保持纯登记，无新动作/flag |
| 第2项准入/ack只承认事件或最新范围 | 后续接线时按§11.6保留原批完整集合，归属证明不冒充ready；逐期真实交付/覆盖才ack。不在第1项提前开发sensor |
| 故障注入未命中真实调用 | 新测试包装须同时接受实际位置/关键字调用，按dagster_event真实参数注入预定写失败；证明缺登记恢复及事件幂等，不能改弱断言或改生产代码迎合替身 |

**第1项内的实施顺序。** 先补合同/记录校验和恢复规划；再修文件归属、继承/rename与实际ID消费者；随后补部分文件事件及汇总；最后按§11.7小样本完成正反/取消/再续跑和成本计数，版本固定后一次直接回归、逐条对账。它们是原第1项的缺陷修正，不新增正式操作、全量审计或其他数据集开发步骤。第2项须等第1项真实通过后，再按其原文档门禁推进。

**证据不得升级。** 原阶段首批8项通过，后批5通过/1失败，均不是固定版本最终验收；旧43项首次生成也不能证明新增日常恢复正确。复现、原计划/hash、候选/checkpoint及日志保留不改，修正后结果单独见§11.11；不把文档通过或隔离验证写成正式日常自动维护通过。

### 11.11 本轮恢复修复与隔离验收（2026-10-17）

管理员授权先提交文档、随后只修复/验证。设计已提交dbec0343，未推送；修改限§11.8内Silver合同、执行器、IO、批量证据、CLI及四份直接测试。没有修改Raw请求/SQL、清洗算法、21列、asset/job/check身份或其他任务文件，没有开发第2项通知/sensor。

| 已确认硬口径 | 实际实现与本轮证据 | 结果 |
| --- | --- | --- |
| 文件完成、输入适用、DG登记分开 | owned_update_records/reused_update_record、report_update_events；周/月整批未完成仍仅补两个已提交文件，不预报第三个成功 | 通过 |
| 同版原ID续跑，只有变更期重建 | recover_update_execution/build；两频各3期复用2、重建1，A/B文件版本与原execution字节不变；C价格独立字面20.2500 | 通过 |
| 原集合/旧指纹不变、继承有据 | load_execution/validate_record及validation_hash；明确原执行/hash/逐期来源，错误parent、跨根、自引用/循环、来源记录损坏或未发布Raw拒绝 | 通过 |
| rename先认提交；再次中断可恢复 | recover_committed/publish；rename后记录失败只补记，已校验候选不重新选行；后继再次取消、冻结后尚无本地checkpoint均可恢复 | 通过 |
| 实际ID贯穿CLI/job/检查 | StockPeriodSilverConfig、CLI resume、deliver_update_asset；原ID正常恢复及新ID承接、真实原生job anchor和事件均核对实际执行ID | 通过 |
| 事件失败只补缺项，原批不早关闭 | report_update_events/record_update_coverage/validate_event_coverage；真实事件写失败、回执失败、父批覆盖部分失败均幂等恢复，无重复物化 | 通过 |
| 真实失败/错绑不能刷绿 | batch_event_evidence/require_recoverable_checks；实际隔离Raw/Silver失败及错绑在新物化前拒绝；正常旧前像结果可补记 | 通过 |
| 不重复计算/审计，取消释放锁 | 同调用证据缓存、两条集合SQL；连续加载20次仅读JSON一次但版本漂移仍拒绝；bootstrap/update实际TERM/KILL后进程退出、两锁释放 | 通过 |

最终固定版本单次完整直接回归87通过、0失败、0skip，耗时28.35秒。此前新增金样本的期望列表误写A/B/C，而VARCHAR代码ORDER BY应为000001、301569、920000，即A/C/B；仅修正这两项字面顺序，精确价格断言不变，定向复验2项通过。随后补充“不能仅修改committed版本认领未知替换文件”的反例及原候选身份核对，该共用校验变化后固定版本完整回归87项均通过；各阶段JUnit和失败日志保留，不以旧结果代替本版验收。Ruff本次9个Python文件默认规则、src/tests致命错误基线及CodeGraph sync/status均通过。逐项用例、代码指纹和性能事实见[验收报告](/private/tmp/dg_period_silver_recovery_final_O131gn/acceptance.md)及[JSON](/private/tmp/dg_period_silver_recovery_final_O131gn/acceptance.json)。

性能仅引用最终回归中两个小场景的原生成记录和完成后resume，不外推全市场ETA；complete.json最后的elapsed_seconds是无COPY续跑耗时，stage_seconds来自原C生成，不能混算。精确耗时及样本路径保存在上述JSON；源请求为0，RSS是测试进程累计峰值，不是组件独占内存。不为填报告重扫Lake或重复源请求。

测试边界：真实临时Parquet、实际Raw run_period/receipt及隔离Dagster事件/检查/job；HTTP使用独立合同字面样本。第2项尚未实现的通知metadata由显式测试合同适配器提供version/freq/file_count及实际完成引用，再由真实Raw检查路径核验/绑定；这仅验证恢复消费者，不声称生产者通知→sensor已接通。正式SQL后端、部署和首个真实日常交付未验收。

本轮正式删除/bootstrap/freeze、Lake/staging写入、重载、事件、sensor操作、Tushare/Prod请求均为0；R3继续暂停。管理员随后要求提交，修复代码和本次结果回写随§10.8既有实现已提交d865e640，未推送，其他任务改动保留。当前结论限本轮恢复修复和隔离验证，第2项及正式操作均不因本节自动获准；后续文档补齐和等待确认边界见§11.8。

### 11.12 剩余1—3项开发与隔离验收结果（2026-10-17）

按本轮授权已完成Raw实际receipt通知、全部现行事件消费者迁移、两Silver sensor及原生检查后的完成确认；六项check、21列、源请求/计算、2014边界和原job身份不变。既有events回执/整批记录承担收尾，不新造状态实体或审批点；sensor活动查询使用当前Dagster get_runs的JobBucket，一次覆盖周/月两job，每job最多1个活动run，原5次存储读取预算保持。

直接回归200项全部通过（含HTTP-worker取消/续跑/CLI/events/handoff/原生jobs），57.49秒；之后仅对跨频率活动查询作最后调整，23项受影响sensor/集成定向复验通过，9.22秒。静态合同113项、catalog12项、check治理6项全部通过。纯metadata的656周+154月容量查询每频率仍是2条集合SQL，0.378秒；小样本两频6文件6次选行/6次COPY，末次0.273秒，测试进程峰值RSS约365.55MiB，不外推正式全市场ETA。

完整“硬口径→实现→正反证据→状态”见[本轮验收报告](../../../reports/dg_stock_period_silver_auto_acceptance_20261017/report.md)与results.json。范围/恢复/假引用/失败及错绑、回执失败和源在汇总期间漂移均有拒绝证据；原旧通知在后来合法更新后可直接复用已闭合回执。共享测试适配器已变为核对真实Raw metadata；未发布反例明确构造缺引用的真实物化，不靠生产者不再适用的旧假设。

CodeGraph及源码清单复核后未分类消费者0；本轮默认Ruff、致命错误基线、文档与diff检查通过。catalog只提交本域三个说明字符串，原格式改动逐字保留。程序及隔离阶段完成，当时正式接线与首个真实日更未执行；其后授权和接线见§11.13，不推进Prod或R3、不推送、不覆盖其他任务改动。

### 11.13 周末正式接线执行清单（2026-10-17）

管理员要求先完成现在可验证的部分，真实下载及首个日常交付等周一。本节具体化§11.9，不改代码、合同、配置或算法。版本6e6017712；工作区R3执行模块hash与此前获准加载版本一致，catalog余下差异仅格式，其他未提交内容不在defs加载范围。R3继续暂停。

**基线只核对一次。** 复用首次Silver执行d895bec0-8b69-4cd3-aabe-7f06a4c7e467及其810文件/2430检查记录。从2026-10-17T14:40:53.425214+08:00起分别限1条查询两Raw新物化，均无；两Raw历史observation分别限1条，均无。因此两个新sensor起点均为`{"schema_version":1,"after":0}`，没有跳过待办。四个目标job无在途运行，Raw/Silver既有锁可用、无相关手动写者。临时证据目录dg-period-silver-handover-bh9qe536；收尾复用，不再扫描历史/Parquet。

**执行入口与影响面。** 工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`，现有`.venv/bin/python3 -B`，`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`。通过现有`http://127.0.0.1:3000/graphql`调用已核对本机安装schema的字段；selector固定`repositoryLocationName=orchestrator`、`repositoryName=__repository__`，sensorName只允许`silver_stock_weekly_update_job_sensor`、`silver_stock_monthly_update_job_sensor`。

| 原步骤 | 精确操作 | 验收和中断规则 |
| --- | --- | --- |
| 加载 | 一次`reloadRepositoryLocation(repositoryLocationName:"orchestrator")` | 新sensor均可见且STOPPED、默认STOPPED；原Raw状态/业务水位和其他sensor状态不变。加载失败停止，不初始化/启用，不重启服务 |
| 初始化 | 分别`setSensorCursor(sensorSelector:$selector,cursor:$cursor)`，cursor为上述实际基线JSON | 先读回两cursor及STOPPED。已有非空cursor/意外状态则停，不覆盖进度；中断后只补未完成项，不重置Raw |
| 启用 | 分别`startSensor(sensorSelector:$selector)` | 两新sensor为RUNNING。部分成功后失败即保留事实并报告，不擅自回滚/停其他sensor |
| 自然tick | 只读两sensor最新tick及目标job近期运行；不preview/dry-run/手工launch | 无新通知时两者自然SKIPPED、reason=silver_no_completion、after=0、无run请求。异常或真实待办停止报告；没有tick就标未完成，不伪造成功 |
| 收尾 | 对比一次原sensor状态/Raw业务水位、Raw daily.json及原Silver完成记录 | 仅新sensor调度状态/cursor/tick变化；文件与旧完成记录保持。周一真实下载及Raw→Silver交付继续待验收 |

**预算、禁止项与证据。** 至多1次reload、2次cursor设置、2次start；0源请求、0行情SQL/COPY、0行情文件写入、0物化/check补报。基线只读4资产最新记录、两Raw新头记录及4个job有界查询。daemon按原60秒间隔自然评估，每tick沿既有至多5次存储读取合同；只等待所需skip tick，不做长时间重复查询。不写Lake/staging、不补旧事件、不重新bootstrap；既有200项及末次23项定向隔离证据复用，不因接线重跑。周末skip只能证明无输入时不误触发，不能替代周一真实下载验收。

**执行结果：通过。** 同日19:57完成上述5次控制面变更。两个新sensor当前RUNNING，定义默认仍STOPPED；自然tick周线2578125、月线2578126均SKIPPED，reason=silver_no_completion、after=0、runIds/runKeys为空、无error，两个Silver job无运行记录。原113项sensor开关状态、两Raw业务水位、Raw daily.json及Silver既有完成记录均保持；未请求源/写行情/补报物化或check，R3仍暂停。机器证据见[formal_handover.json](../../../reports/dg_stock_period_silver_auto_acceptance_20261017/formal_handover.json)。本次正式接线完成，剩余首个真实交付待周一原19:30窗口；不为验收手工重下旧数据。


<a id="period-delivery-recovery-lld"></a>

## 12. 2026-10-27周/月交付确认与恢复修复 LLD

### 12.1 状态、硬口径及开发顺序

对应[总方案第10节](dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md#period-delivery-recovery-plan)；月线差异见[月线LLD第9节](dagster-stock-monthly-raw-onboarding-low-level-design-v1.md#monthly-delivery-recovery)。2026-10-27仅编制及审计文档，2026-10-28获准按本节顺序完成检查读取及拒绝规则→交付确认及状态收尾→原意图/当前日期执行顺序→全部入口迁移→隔离验收。实际实现及用例对账见§12.15；正式收尾与补数未执行，仍须另行批准。

| 硬口径 | 代码落点（相对orchestrator/src/orchestrator/） | 正反验收 |
| --- | --- | --- |
| 最新结果以实际检查事件为准，不能预筛成功/目标或扩大limit找绿 | defs/asset_guards/stock_period_check_evidence.py（本轮新增的本域SQL模块）；Raw report_file_events；Silver两入口 | §12.13 A1—A5 |
| 原检查失败/错绑不能被补报通过覆盖 | stock_period_update.py；bootstrap/stock_period_silver_cli.py；stock_period_silver_readiness.py | A3、A6—A8 |
| 原交付已完成不要求旧文件永远是当前文件 | bootstrap/stock_period_history.py的清单验证/确认/历史返回；stock_period_update.py待办收尾 | B1—B5 |
| 历史成功不能放行未知当前目标或生成旧anchor metadata | deliver_asset；当前目标准入；Silver现行旧通知处理 | B3—B6、C4 |
| 先关旧待办再规划新工作，原生检查只能在物化后确认 | _execute_daily_locked及原生job执行分支 | C1—C3 |
| 日期/分区/意图固定；不造run key、不重置cursor、不自动重跑失败 | Raw sensor原定义；原job原生重执行；已有日期配置 | C3—C6 |
| 0额外业务全局审计，旧20恢复0行情读取/写入 | events CLI及共同确认流程 | D1—D4 |
| 原identity、complete/hash、字段/价格/选行/路径/锁不改 | 原run contract、IO、两频asset/check及Silver消费者 | B4、C4、D3及原直接回归 |

本文的anchor指当前job负责物化的那个分区；receipt指原文件清单/校验回执，CP指已有checkpoint小型JSON记录，均沿现行代码含义，不新增业务概念。

本次仅一个修复目标，不改通用检查治理、SDK、数据库schema、Prod、其他数据集、依赖或服务配置。原stock-period-source-v2和stock-period-completion@1及其完整内容不变；新增SQL模块不是新状态实体或兼容层，三个现行选择器必须改用它，旧limit=1/max(Checks.id)实现不保留双轨。不得引入新job、sensor、CLI动作、输入参数、配置开关或自定义run tag。

### 12.2 当前代码、平台依据及故障记录

静态依据：stock_period_update.py::_execute_daily_locked、report_file_events、deliver_asset、evaluate_daily_sensor；bootstrap/stock_period_history.py::completed_files、replay_events、run_period；asset_guards/stock_period_silver_readiness.py::batch_event_evidence/require_checks/require_recoverable_checks；bootstrap/stock_period_silver_cli.py::report_file/report_update_events；stock_period_silver.py的旧批完成确认及新Raw引用解析。CodeGraph status、search及impact结合实际import、回调和源码逐项核对；动态CLI、同名replay_events及测试替身以源码核验为准。

当前环境依据是已安装Dagster 1.13.26，不能用旧文档1.13.5或另一环境版本代替：

- SDK event_log/schema.py已有evaluation_event_storage_id、evaluation_event_timestamp和materialization_event_storage_id，无需加列。
- sql_event_log.py::_store_asset_check_evaluation_planned预建检查行；_update_asset_check_evaluation在真实结果登记时更新实际事件ID及目标。get_asset_check_execution_history仍按检查表id降序。
- 原生asset先返回MaterializeResult，随后执行三项check。官方依据：[asset checks](https://docs.dagster.io/guides/test/asset-checks)。
- sensor相同run_key只提交一次；既有launchRunReexecution从原run构造子run、保留原配置/分区并submit_run，不依靠sensor重发。官方依据：[RunRequest](https://docs.dagster.io/api/dagster/schedules-sensors)、[执行与重执行](https://docs.dagster.io/api/dagster/execution)；精确字段按安装版GraphQL inputs.py、mutation.py、implementation/execution/launch_execution.py及instance的run_domain实现核对。

本次故障的固定证据如下，时间均为上海时间；ID不能写成实现中的特殊放行名单：

| 事实 | 已核值 |
| --- | --- |
| 故障run/job/意图 | 319ec97d-cfd4-4ef7-bc4a-c98c7334464a；raw_stk_period_bar_adj_week_update_job；2026-10-27；partition=2026-10-30；0.32秒即失败 |
| 旧执行ID/请求ID | db67897faf10513982324f86e1793cec58328349a65ac00a91b23ab5150917e8 / 6beb42d76b312556b479241302a0fc7fa029d7cf3db442898972fb5309811e37 |
| 旧清单hash/范围 | 420b8fb15bdb264a19a1e144a7d2ec5f6873f2737e53f001b62bdb004d027c3d；week=2026-10-23，仅1文件；asof=2026-10-20 |
| 旧状态 | files_complete、ranges_recorded=true、consumed=true；单文件events回执缺失；completion/week.json已存在 |
| 原真实交付 | 原生run 30e88c98-17a5-4730-b8c5-7479fc5cd084；Mat=7684828；row_count=5568；原三项检查1645976—1645978均SUCCEEDED/passed/blocking且准确绑定；completion observation=7684826 |
| 被误选的更大检查表ID | 1650956—1650958；结果在20日21:41产生，绑定更早Mat7683201；原正确检查结果在21:42:59—21:43:00产生 |
| 合法后继执行ID/hash | 51c154973ebf53204d3a57f7507bebf91f64d111787f7ff657bd556b40ca5ad3 / d3c852360c08a6709280a3671bd454768a4ab399bcc61940b255f593069fa291 |
| 后继实际动作 | 21日意图18股两频，1662周+395月=2057文件；21日19:33:10提交该周文件，19:38:08—09登记新物化7705014及三check；22日19:31:19完成整批events阶段 |
| 当前文件与后继 | 后继该文件row_count=5569、bytes=447367；committed.target_preimage精确等于旧complete.version，当前stat与后继version及baseline一致 |
| 日常控制记录 | completed_through.week=2026-10-16、month=2026-09；last_refresh.week=2026-10-21、month=2026-10-20；factor_through=2026-10-21；pending仅上述旧执行 |

旧version=[16777244,22183792,445374,1792503779505129588,1792503779565190938]；后继version=[16777244,22334111,447367,1792582237656923049,1792582390859255088]。五项依次为设备、inode、大小、mtime_ns、ctime_ns。后继mtime是候选生成时间，正式替换依据committed及ctime，不能把mtime误当正式提交时刻。

完整时间线见总方案§10.2。已有只读证据在/private/tmp/dg-run-319ec97d-{staging,provenance,producer-checkpoints,timeline,check-order}-20261027.json等本轮文件；本节保留必要事实，临时文件不是唯一合同或未来运行的输入。21日首个新run在候选验证处触发4GiB门禁、尚未正式发布；后续月线run才恢复发布。内存中断是必须覆盖的恢复场景，本轮不据此加内存或改原policy。

### 12.3 统一读取最新实际检查

实现文件defs/asset_guards/stock_period_check_evidence.py，仅负责本域SQL构造和解码，不读Parquet、不写状态、不import业务执行器。内部接口固定为：

~~~python
latest_completed_checks_query(
    *, asset_check_names, partition_keys, before_event_id=None
)  # 返回SQL子查询，不连接数据库

decode_completed_check_row(
    row, *, asset_key, check_name, partition_key
)  # 返回record、evaluation_event_id及bound_materialization；证据不符则拒绝
~~~

asset_check_names是精确AssetKey→检查名集合；partition_keys是已列明分区集合；before_event_id仅用于§12.5历史时点确认，默认None表示当前。空集合直接返回空，不以空过滤退化成全表。资产/检查名必须来自原周/月Raw或Silver合同，不接任意SQL文本。

查询规则：

1. 先限定资产、检查名、分区和SUCCEEDED/FAILED，PLANNED排除；不得先筛passed或target=current。排名阶段仅读ID/排序/绑定等窄字段，不把该分区所有检查正文拉进Python。
2. 按(asset_key,check_name,partition)分组，以evaluation_event_storage_id降序选择一条。不得使用Checks.id或create_timestamp，也不以limit=20/分页找一条green代替正确排序。
3. 同组存在缺失实际事件ID的terminal记录时拒绝该组，不能由MAX忽略NULL后认完成。历史查询无法判定NULL属于截点前还是后，也拒绝；不回退旧编号/创建时间。此类旧数据须另做有界核实，不在运行中修库。SQL在同一排名子查询中保留每组NULL计数和同组实际事件ID重复标志；有NULL或重复实际ID即拒绝，不先丢弃异常行再排名，decoder可据这些标志明确报错。
4. before_event_id存在时，只在非NULL实际结果ID严格小于该截点的记录中排名；完整范围及截点必须来自已核后继物化，不能随意取一个早时间绕过失败。
5. 选中后才取检查正文。第二条SQL同时使用两个独立event_logs别名：evaluation_events按Checks.evaluation_event_storage_id做left join，返回实际结果事件ID、事件类型及正文；bound_events按materialization_event_storage_id做left join，返回目标物化ID/正文。decoder核前者确为ASSET_CHECK_EVALUATION，真实事件run/资产/检查名/分区/passed/blocking/target与Checks.evaluation_event副本及索引一致；后者确为所指目标物化，不能拿目标join冒充实际结果join。实际结果不存在或类型不符、SQL状态与passed冲突、索引目标与正文target冲突均拒绝，不能用空值兜底。必须先选定最新行，再做两个left join；实际事件缺失时保留该坏行交decoder拒绝，不能因inner join删掉它、退回旧结果或误当缺检查。两个join仍在同一条集合SQL内，不新增逐文件查询。
6. 再由调用方核blocking及精确目标物化ID/run_id/timestamp。最新真实失败、晚发生的错绑、非blocking都不算缺失，不向前找旧成功。

Raw单文件回调一次读取三项，替换原三次history查询；历史确认按明确文件集合读取，不能为后继2057文件逐项查历史。Silver batch_event_evidence仍为一次物化集合SQL加一次检查集合SQL，共两条；第二条使用共享选择子查询，保留原materialization/checks/bound_materializations字段含义；对内增加check_event_storage_ids映射以支持§12.4的先后比较。decoder返回record=AssetCheckExecutionRecord、evaluation_event_id=正整数、bound_materialization=EventLogRecord或None，调用方将record放回原checks映射，不能假定SDK的AssetCheckExecutionRecord自带实际结果ID。该ID贯穿历史确认和补缺分类，不用检查表record.id代替。report_file使用同一SQL/解码规则。SqlEventLogStorage支持当前PG及隔离SQLite；未知后端/缺列明确拒绝，不兼容回旧逻辑，不安装或迁移数据库。

### 12.4 当前检查准入与补缺，不得覆盖失败

三个入口都先读取、分类已有证据，再写动态分区/物化/check；至少在任何业务事件补报前完成拒绝判断。外层执行run的正常日志不属于业务物化。

| 当前证据 | 动作 |
| --- | --- |
| 当前物化准确匹配receipt/路径/版本/行数及适用完成引用，三check最新实际结果通过并精确绑定 | 直接确认，不新增事件 |
| 仅PLANNED或确无对应完成检查，且已校验当前文件/原提交及可恢复前像 | 保持原缺项补报能力；只补缺的当前结果，不把PLANNED当成功 |
| 新物化已出现，上一条通过结果实际发生在新物化之前，且精确绑定合法前像或同版原交付 | 这是缺新物化检查，不能直接认成功；凭提交回执及前像完成原有缺项恢复 |
| 新物化之后出现的结果绑定其他物化；目标不存在、路径/分区/完成引用不符 | 明确拒绝，不能当缺项补报 |
| 最新实际FAILED、passed=false、非blocking或索引/正文冲突 | 事件补报入口拒绝，不新增passed=True；原生检查失败只能经获准的真实检查重执行解决 |
| 另一分区有合法完成记录 | 与本分区分开；不得误拦本分区，也不得借其证明本分区完成 |

“合法前像”必须精确来自本次已校验/committed记录的target_preimage或Silver已有event_preimage，而不是随便取更早一条成功。取出的旧结果必须发生在新物化之前，绑定的物化元数据与此前版本一致。检查发生在新物化之后却仍绑旧物化，属于错绑，继续拒绝。恢复阶段允许的旧证据不能作为最终require_checks通过条件，最终仍须全部绑定本次实际物化。

Raw report_file_events(write=False)只读判断；未完成时返回False并记录原因，不发事件、不把原生检查提前判成成功。write=True遇到上述拒绝项必须抛出明确错误，不得重发一条物化后追加通过来隐藏原失败。Silver require_checks/require_recoverable_checks、首次report_file、update report_update_events遵守同一拒绝语义，保留各自已有前像/输入检查。

当前report_file_events的audit_file仅在当前文件/补缺路径使用，继续复用该精确版本的候选审计证据；不能将历史证明注入当前版本审计缓存。§12.5历史确认不调用audit_file，不计算旧文件摘要，也不要求已不存在的旧文件内容重现。

现有test_stock_period_silver_events.py::test_event_reporting_never_accepts_planned_or_misbound_checks实际在failed/wrong_binding/nonblocking后断言补成通过，与本轮要求冲突。后续必须先记录该依据，再将真实失败/错绑改为“拒绝且新增物化/check均为0”；planned_only及另一合法分区仍证明正常缺项可补。不删除这项覆盖、不把期望交给待测helper生成。

### 12.5 只读核实原交付与合法后继

在stock_period_update.py集中提供本域只读确认回调，bootstrap执行器通过显式参数接收，不自行建立Dagster instance。实现接口：

~~~python
confirm_period_delivery(instance, run, *, root, staging, cancel, allowed_frequencies=None)
# 返回原每文件Mat/check/通知证据、当前适用文件及historical_only；
# 不落盘、不补事件、不下载、不COPY。

acknowledge_period_delivery(run, confirmation, *, root, staging, cancel)
# 原writer锁内只补既有回执/phase及匹配的daily.pending；不补造DG事件。
~~~

allowed_frequencies默认两频；周线限定补报op必须显式限制为week，只读/补记允许频率的单文件和通知，含month未确认的整批不能关闭或移除pending。run_period/replay_events增加可选confirm_delivery回调；全部正式SDK入口显式接入。没有instance的纯文件执行仍可做文件阶段/当前版本校验，不能认定缺失DG事件已经完成，也不能自动忽略目标变化。旧CLI actions/运营参数不增加；回调是内部参数，所有消费者在§12.9列明。

先将completed_files拆成“核原identity/complete摘要/逐文件字段”和“核当前目标版本”两个内部步骤。前一项始终执行，后一项只在当前文件恢复、补事件或新写入准入执行。不能简单删除file_version守卫，也不能只因为phase=events_complete就跳过损坏回执。

分支一：原phase=events_complete且全部原单文件CP、每频completion CP完整一致。
- 核原run ID、identity_hash、complete hash、文件集合、CP的version/sha以及notice/file_count/observation_id有效；原通知存在且与原引用一致。
- 这一分支一律返回historical_only=True、current_files=[]，只表示原交付已完成，不尝试判断每个旧文件今天是否仍当前；不逐个stat或重读后来已更新的旧目标、不重新补报业务事件。当前anchor由§12.7单独按必要文件核验，不能为填current_files重扫整批。原有闭合回执作为持久证据，不为重复调用重新扫描该批全部DG检查。
- 如果daily仍引用该执行且consumed=true，可在锁内幂等移除该待办；consumed=false或控制水位不具备相应文件消费依据时停止，不把旧listed写回当前baseline。

分支二：files_complete或回执缺失，需从真实历史事件补确认。
- 每个缺项必须核原物化的资产、分区、路径、行数、文件版本和原completion完整引用；原三check按§12.3选择并准确绑定该物化；原每频通知也须存在、引用及file_count完全匹配。
- 当前stat等于原版本时，仍核当前最新真实检查；晚失败/错绑不能被更早成功掩盖。
- 当前stat不同，必须由当前合格物化携带的completion引用定位明确后继manifest/complete/该文件committed。核后继身份/hash、目标路径、target_preimage=原version，当前stat=后继version，且后继该文件的物化和三check准确通过。多个后继时沿物化引用逐段核前像，不枚举整个runs目录，断链即拒绝。
- 原历史检查只在其后第一个合法新版本物化之前取最新实际完成结果，使用§12.3的before_event_id；不得只筛原目标成功而漏掉该截点前后来的失败/错绑。截点之后检查属于后续版本的当前准入，另核，不拿新版本检查冒充旧检查。
- 只查询原files_completed_at至明确后继物化时刻这一有限窗口的指定资产/分区物化，核完整引用来定位原交付；有多个不一致候选、无法给出事件范围、缺任一文件原检查、前像断链或后继当前失败均停止。不得依靠“日期更晚/job成功”放行。
- 只有原整批每个文件均已确认，才允许关闭整批；本次旧清单只有1文件，不因后继2057文件已完成而逐份重新验证它们。

分支三：缺失的旧物化/检查无法证明、文件又已替换。
- 保留旧回执、phase与pending，明确指出缺失的原事实，不重新发旧版本物化/通过、不修改旧version/hash、不重写旧候选、不仅凭后继完成关闭旧批。
- 这是证据不足的停止条件；需针对实际缺项另行确认重新交付安排，不能由本流程自动做历史重建。

**2026-10-28实现复核细化：批量取证与同版清单复用。** 未闭合批次的confirm在已闭合CP快路之后，按allowed files列明的资产/分区集合先做一条最新物化集合SQL、一条共享latest_completed_checks_query集合SQL；每频通知仍各一次小查询。未变版本的每文件循环只消费内存映射，明确空映射也不得再次单文件查库；缺原Mat时仍用同一检查映射拒绝真实失败。仅确有版本变化的文件追加有限历史/截点取证，后继链首复用当前预取结果，不能对同版2057文件逐个新增查询。2文件与100文件单频同版确认都应为3次SQL，不随文件数线性增加；每次confirm独立取最新证据，不跨次缓存DG状态以免掩盖新失败。后继manifest/complete在单次confirm内按execution局部缓存，completed_receipt可接已读complete参数但原身份/hash/字段/路径校验不减弱；缓存命中仍核精确stat，各文件committed独立核验。run_period刚完成文件且events=None时只返回文件事实，待文件消费后的replay统一确认，不明知原生检查未发生仍重复深查。上述均落实原批量/复用要求，不增加业务读取或新状态；成本与晚失败拒绝一并测试。 同次target validator按频率复用已核candidates清单/hash及(period,target)索引，各committed CP独立核验，不能每文件重复读整份候选清单。ack入口、phase更新前及pending删除前各做整组控制版本校验；逐文件CP已存在时只核自身，真正补写前核原manifest/complete/daily、该CP及相关目标版本，避免每个CP重扫全部controls形成平方级stat。最后整组变化仍拒绝，已补的真实局部回执保留；2/100文件的stat/候选清单读取计数须证明线性。

确认结果仅在当前锁内使用；每项控制写之前重新核相关JSON版本/摘要及必要目标stat，防止审计后发生并发变化。输出里historical_only=True的files是历史追溯清单，禁止参与当前asset anchor选取。当前Mat/check证据与历史证据分别返回/消费，不互相替代。

**内部返回值与接线（已实现，不是新持久化合同）。** confirm_delivery回调接收本次run目录，返回下表；无完整原事实时返回未完成原因，证据矛盾则抛错。bootstrap模块不猜bool、不将None当成功。

| 字段 | 约束/用途 |
| --- | --- |
| run_id、identity_hash、file_receipt_hash | 精确等于本次原manifest/complete；ack逐项重核 |
| files | 原冻结清单，不增删、不改version/sha/rows |
| events_complete | 仅原整批文件及所有频率通知事实齐备时true；不是job成功或当前文件存在 |
| historical_only | 已闭合旧执行的重复调用一律true；本次补确认的旧批只要存在合法替换也为true；不能交给当前anchor |
| current_files | 原清单中经当前stat/合法receipt确认仍适用者；历史文件不得混入 |
| file_evidence | 以(freq,period)为键，列原materialization_id、逐检查evaluation_event_storage_id及绑定ID；历史确认另列后继原执行ID/hash/物化ID及截点；已闭合CP复用时显式注明原CP来源 |
| completion_evidence | 每频原notice和真实observation_id；每频file_count与原清单一致 |
| control_versions | 本次所读manifest/complete/相关CP/daily的版本或摘要，用于锁内防漂移；仅存在内存 |
| reason | 未完成时区分缺检查、需原run、未知变化、缺历史证明；日志必须包含原job/日期/分区/执行引用 |

replay_events首先核原receipt，再调用确认回调；整批确认true则调用acknowledge_period_delivery后返回，不进入当前文件补报循环。确认仅表示缺当前可恢复事件且文件仍当前时，才进入原补缺路径；其后重核完整证据再ack。文件不明/原历史事实不全/晚失败错绑必须拒绝，不能因confirm返回False就自动走补绿分支。无确认回调的纯文件路径不负责daily.pending收尾。CLI apply/resume仍保持不自行创建/获取instance的纯文件边界：若存在另一个需确认旧待办，或本次run已到文件完成阶段却缺DG确认，须在新请求/COPY前停止并指向已有events动作。只有当前要恢复的同一冻结意图尚处于文件阶段、且没有更早未处理待办时，才可沿原文件checkpoint继续；文件阶段完成即报告需events，不关闭pending、不冒充业务交付完成。旧phase已完成但当前文件变更，纯文件入口也指向events作历史核实，不自行跳过守卫。

run_period对files_complete/events_complete的恢复分支先走这一共同入口，再决定是否核当前目标/补事件，不能先调用旧completed_files逐个stat而重现本次错误。首次完成文件阶段的源/候选/发布流程不变，随后的事件阶段同样进入该入口。_execute_daily_locked在调用run_period前先确认已完成文件的旧待办；全部已消费旧待办关闭后，才进入当前规划。同一run再次经过replay_events只验证已有CP，不重复写入。

ack只接已核整批true结果，写前重核身份/摘要和相关当前stat；返回已移除pending或原pending不存在的明确结果。范围不含某频的确认不能整批ack；consumed=false不得借历史分支推进因子或上市集合，必须回原文件消费流程核实际控制事实。所有调用沿同一writer锁，不让“确认成功”和“下一次新写”之间插入不受保护的本域写者。


### 12.6 状态落盘、目标守卫与异常恢复

ack入口自身也须核run目录严格位于staging/stock_period/runs/run_id、identity.root匹配及原设备标识，不只依赖调用者已confirm。所有正式Raw写入与本节收尾使用既有stock_period/writer.lock，不增加另一把锁或绕过flock。锁内依次：

1. 核完整原身份/清单/所有缺项证据；已有回执必须逐项相等，不能覆盖矛盾回执。
2. 原单文件events/freq/period.json仅补原version和sha256，保持现有格式；已存在且相等直接复用。
3. 原events/completion/freq.json缺失时写原notice及真实原observation_id；已有则核相等。不是创建新通知。
4. 全部原事件事实/回执齐备后，仅将manifest.phase改为events_complete；原identity、identity_hash、complete.json、file_receipt_hash、源页、候选及committed不改。
5. 最后读回最新daily.json，只移除精确匹配原run_id/原intent且consumed=true的pending；其他键、其他待办、completed_through、last_refresh、last_source_asof、factor_through以及baseline全部保持。

沿atomic_json的临时小文件→fsync→os.replace写入，每一步后中断均保留已完成事实。恢复先验已有CP/phase，再补缺项；phase已改而pending未移除时只补第5步。daily有新进度不能被旧副本覆盖。确认失败不回滚已提交行情，不创建行情备份或快照。

当前文件准入仍单独执行：即将生成/覆盖的每个目标须匹配baseline已登记版本或由当前合格物化定位的明确后继committed记录；目标前像继续进入候选receipt，发布时再次校验，原publish守卫不减弱。未知文件即使有一份旧历史成功也拒绝。

**2026-10-27开工细化（同一已批准目标守卫，不增加业务口径）。** 当前assemble只捕获现存stat作为target_preimage，原范围索引漂移还会回退读取，不能独立证明目标归属。因此在io/stock_period_raw.py::assemble确定selected目标/冻结前像后、读取旧行情及COPY之前，增加内部validate_targets(targets)回调；run_period注入同一归属核验。targets只含已选freq/period/path/version，不读未选文件。新目标指baseline未登记且目标不存在；baseline已有登记但文件缺失必须拒绝，不能用单股历史把整分区重建成仅目标股。已有目标必须匹配原baseline.files的精确版本，或当前原执行已校验/committed的精确版本。后继版本须先通过本节原交付/范围记录恢复形成已核归属，不能在新任务里把未知stat认作前像。copy.json复用路径同样核冻结前像/当前原提交，不能靠缓存绕过。该接线不改选行、计算、COPY次数、policy、字段或发布算法，基于现有版本元数据，0新增行情读取。独立反例覆盖“篡改原目标但原历史已成功”在旧行情读取/COPY前拒绝，以及新目标、已登记目标、原意图逐文件提交后续跑仍可通过；开发前已将此具体落点补回本LLD。 旧test_stock_period_combined.py::test_range_record_drift_falls_back_once_and_is_not_reblessed的file分支曾允许未登记mtime变化后覆盖，与本轮未知目标拒绝要求冲突；须保留原错误样本并改为写前拒绝。仅范围索引hash失效、文件版本仍匹配的index分支继续允许原有一次范围回退，未选文件变化不能误拦本次目标，不以删掉旧测试消除失败。

所有新写入口，特别是deliver_asset的history分支与CLI history/resume，必须先经过同一旧待办检查；不能仅日更受保护、手动历史仍能覆盖未确认文件。events只补确认/事件，不顺便规划新日期、因子或历史。handoff沿其原冻结父子身份，不重跑父bootstrap。

### 12.7 共享待办执行与原生anchor

_execute_daily_locked重构为先恢复/确认旧待办，再做当前新规划；必须在_daily_work、factor_changes及任何源请求之前完成旧待办分类。两频共享队列不按传入freq过滤掉另一频待办。

顺序键为已冻结intent.asof（存在时）、manifest.started_at的真实时间、execution_id。无asof的主动历史意图以started_at排序；两者均缺或非法不得用文件mtime/哈希键猜先后。未建立manifest的冻结daily work有asof可用；同日两频以已存在的started_at为先，再以ID作稳定tie-break。

| 旧待办状态 | 当前调用允许做什么 |
| --- | --- |
| 所有原事实齐备，只缺CP/phase/pending | §12.5—12.6只补确认，然后继续检查下一旧待办 |
| 文件未完成，来源/目标未变，尚无不同新意图 | 只有原意图执行可从原阶段续跑；所有成功源页/文件沿原ID复用 |
| 仅缺原native anchor Mat/check，当前调用就是原意图（同日期/频率及冻结request_id） | 不再重复run_period生成文件，返回仍为当前版本的原anchor，让原生check实际执行；不开始另一个新意图 |
| 同上，但当前是不同日期/频率或history新意图 | 在新源请求/因子扫描/COPY前报period_original_run_required，给出原job/意图/分区与可核实原run；不代办旧anchor |
| 真实失败检查 | 不靠events补绿；按§12.8原生检查重执行。不同新意图继续阻断 |
| 当前文件不明、原证据缺失或前像断链 | 拒绝，保持待办/水位，不删除或覆盖 |
| 旧待办全部关闭 | 才调用_daily_work规划当前日，或进入显式history |

原意图是否一致按冻结业务意图判断，不按物理Dagster run_id相同判断；重执行有新run_id但原配置/日期和业务request_id不变。查找原run以该文件物化/检查实际run为首选，再按精确job/分区/automatic_intent_date及原运行有限时间窗口核配置，不取“最近一个失败run”猜归属；歧义停止。

未完成旧意图不能把今天的last_refresh写成今天；文件消费与事件确认继续分开。原已消费因子水位不倒退，也不因补CP重做factor_changes或把旧listed覆盖当前集合。calendar-only工作仍按原无文件规则推进，不伪造物化/check。

deliver_asset在读scope/源前先核period_for(已冻结today,freq)等于context.partition_key，错日/错分区组合拒绝，不借fallback在其他分区登记。deliver_asset先排除historical_only结果，再从当前适用文件中选anchor。若需fallback，必须从当前stat及明确baseline/receipt/真实Mat绑定证明它属于当前交付，不能仅audit任意现存文件后直接登记。当前partition与旧待办partition不同，不能在本次分区上用旧receipt返回MaterializeResult。

### 12.8 同日run key与原job续跑操作

不修改Raw sensor的19:30、交易日、run_key、动态分区或cursor格式，不增加自动失败重跑。sensor只保留原有限查询和编排；本次不让Raw sensor写daily.json或扫描历史回执。收尾由原events CLI或下一次共享执行完成。

按已安装GraphQL合同，原失败run使用既有操作：
~~~graphql
mutation ResumePeriodRun($params: ReexecutionParams!) {
  launchRunReexecution(reexecutionParams: $params) {
    __typename
    ... on LaunchRunSuccess { run { runId } }
    ... on PythonError { message stack }
  }
}
~~~
参数为parentRunId=明确原失败run、strategy=FROM_FAILURE、useParentRunTags=true。原run的remote origin/job selection、run_config、partition及root/parent继承；不用extraTags改run_key，不手动篡改run_config或DB。原asset已成功而仅检查失败时，FROM_FAILURE只恢复需执行的检查；asset此前失败则从原asset恢复并随后原检查。不得用ALL_STEPS代替无需重算的checks-only续跑。

本次旧20已具原完整成功证据，不需重执行成功run30e88c98；先按§12.11原events CLI收尾。然后若实际缺口及读写获批，重执行319ec97d-cfd4-4ef7-bc4a-c98c7334464a，保持automatic_intent_date=2026-10-27、partition=2026-10-30。这是继续原27日意图，不等待sensor重发27日同key。月线同理使用精确匹配的原失败日常run；没有当日run时才允许现有sensor正常提交。

automatic_intent_date已显式设置的自动任务必须原值恢复。现行手动首次daily允许None，仍可按上海当天解析；但原run带None且要跨日重执行时，必须在读源/写文件前识别，不能重新取系统当天。能从原冻结intent.asof核准原日期时，在原job现有配置字段automatic_intent_date中显式填写该日，通过原job Launchpad启动明确恢复；仍使用该日原确定性业务request_id，不通过sensor造新key。没有可信原日期或存在多个原意图时拒绝。该分支不使用上述原样继承None的GraphQL续跑，不新增输入字段/tag/状态实体，不改变首次手动默认行为。

隔离验收须证明“旧检查完成→旧CP收尾→当天原失败run继续→当天last_refresh达到意图日”；只执行检查成功不等于当天新数据更新完成。操作记录分别写明这几个阶段及实际run。正常后续日更也须通过原job小场景验证，不用一条手工补报的green代替。

### 12.9 文件、消费者与配置审计

以下为本轮获准开发白名单及消费者审计分类；实际改动见§12.15，纯核验薄入口/合同没有必要不改。未列明的新入口/配置仍须先回写原设计，不自由扩展。

| 文件/入口 | 必须改动或核验的内容 |
| --- | --- |
| 新defs/asset_guards/stock_period_check_evidence.py | §12.3共享SQL/解码，无状态/业务IO |
| defs/stock_period_update.py | 三阶段分类、只读确认/收尾、当前目标guard、原意图顺序、anchor筛选；report_file_events补报前拒绝；execute_daily/deliver_asset/handoff全部接入 |
| defs/bootstrap/stock_period_history.py | 拆清单/当前版本校验；run_period/replay_events接确认回调；历史返回/CP原子收尾；共享锁不变 |
| defs/asset_guards/stock_period_silver_readiness.py | 第二条集合SQL复用真实事件排序；原require_checks及recoverable目标/失败门禁不减弱 |
| defs/bootstrap/stock_period_silver_cli.py | report_file首次补报统一拒绝规则；update补报/readiness及CLI replay复核，不重写Silver选行 |
| defs/stock_period_silver.py | 复核已闭合旧批历史确认、新Raw引用解析、sensor收尾使用新证据语义；已有覆盖/继承机制复用，不另造一套 |
| defs/bootstrap/stock_period_history_cli.py | events/resume/handoff接确认；events在phase已完成快路径也接只读确认及匹配pending收尾；原解析动作/参数不变 |
| defs/ops/stock_weekly_bootstrap_checks.py | 仅周线补报范围不变，接同一确认/拒绝；不能顺便消费月线待办或发月线事件 |
| defs/assets/stock_weekly.py、stock_monthly.py；jobs/stock_weekly.py、stock_monthly.py | 正式名字/selection不改，核原生asset→checks真实先后及重执行；没有必要不修改这些薄入口 |
| Raw两sensor、Silver两sensor | 不改定义/默认开关/19:30/key；有界回归原Raw阻断和Silver消费/收尾；不操作正式开关 |
| run_contracts/configs.py、stock_period.py、stock_period_silver.py及原weekly/monthly合同 | 只核现有字段、身份、check名、notice、前像及日期语义；保持公共合同，不新增运营参数/字段或改版本 |
| io/stock_period_raw.py、io/stock_period_silver.py、stock_period_checks.py | Raw assemble在selected/preimages与缓存复用处接validate_targets内部回调，核本次明确目标归属；复核候选校验、版本缓存、原子提升及原checks消费；不改业务计算/内存policy |
| 原三个设计文档 | 原方案§10↔本节↔月线§9逐项同步；无新定义，无需改拓扑/全局catalog/治理HTML |

直接测试消费者：test_stock_period_recovery/update/combined/integration/history/history_cli/handoff/handoff_memory；本轮新增test_stock_period_daily_delivery.py落实日期/旧待办/anchor分类小场景，新增confirmation/history/check_evidence测试按本节相应矩阵覆盖；test_stock_period_silver_events/execution/jobs/sensors/daily_integration/contracts；两Raw sensor测试及月线definitions。保留共享夹具真实生产者合同，必要时扩展本次断言；source/storage/candidate_fragments/memory_resume只做本轮触及行为的回归，不默认重跑所有性能测试。原退役CLI仍退役，不恢复旧入口；CodeGraph未发现Prod/API/前端消费者，本轮不迁移它们。

| 配置或持久事实 | 来源/默认/作用域/消费者/生效方式 |
| --- | --- |
| intent、automatic_intent_date、request_id、stock_codes | 现有StockPeriodRawConfig；默认daily/None/None/[]，history必填ID；原job/asset读取；传入单run生效；日期恢复按§12.8，不新增开关 |
| policy | 原manifest.identity.policy及StockPeriodPolicy；日常默认4GiB RSS/3GiB DuckDB/2线程等原值；原下载/IO消费者不变；本次不抬高、不覆盖 |
| 根目录与writer | 当前paths.py固定正式Lake/staging；stock_period/writer.lock；所有本域写入口复用 |
| 原执行/交付/消费事实 | 原manifest/complete/committed/events及daily/baseline；本轮只允许§12.6列明小范围状态收尾；identity和源业务合同不改 |
| event ID及目标绑定 | 现有DG SQL存储；只读；新本域SQL模块和三个选择入口；随代码加载生效，无schema/config变更 |
| sensor状态/游标/run key | 正式instance原值；本轮不读写；未来维护只核本链四项并保留原状态，不能由definition默认值覆盖运行状态 |

### 12.10 性能、读取与中断预算

不新增运行限额、并发或性能实验；本表是范围/开销的执行前对账。已有合同证据优先复用。

| 阶段 | 正常读取/写入 | 一次中断续跑及最后验收 |
| --- | --- | --- |
| 2026-10-27文档阶段 | 当前代码/已有审计JSON；0行情内容，0正式写入 | 只复读修改文档及必要源码，不跑业务 |
| 隔离测试 | ≤3股、2频、≤8个小周期文件，独立字面21列；每个检查顺序/续跑小场景≤12个原/重执行run（不是整轮既有回归的总run上限）；临时资源预计读≤256MiB/写≤128MiB/空间≤512MiB | 故障注入包含一次中断/恢复和必要原生重执行；总计读≤512MiB/写≤256MiB/空间≤1GiB；非生产配额/限额，不用真实多年行情 |
| 本次旧20收尾 | 旧manifest约216KB、complete724B；后继manifest217182B、complete1179303B、单文件commit588B；另daily/baseline和少量CP。JSON读≤8MiB、写≤2MiB；原/新Mat各1、原/新check共6、原通知1及目标前后stat | 含一次续跑和最后核验：JSON读≤16MiB、写≤4MiB；上述事件集合至多每轮一次；最后只读原小型控制记录，baseline用未变化stat复用原已核内容，不再次读取后继完整清单；相同文件stat确认，不读后继2057份文件 |
| 新SQL | Raw当前单文件一组查询取三check；Silver保持2条集合SQL；确认仅查明确receipt涉及的资产/分区/事件窗口 | 存储失败重试须显式操作，不自动重扫；只拉最新正文，事件范围不得扩大成全库 |
| 后续Raw/Silver补数 | 由当时实际欠账/因子变更/交付清单确定，正常/中断/验收分项列清后批准 | 不含在旧20“0行情读写”中；不得用本节代替历史读取批准 |

旧20收尾的源请求、行情SQL、DuckDB、COPY、行情文件读写均为0，新增业务Mat/check/通知为0。原events CLI可产生一次stock_period_event_report控制面run及正常日志/终态，必要时至多显式续跑一轮；不能将其说成“DG完全零写入”。无需安装工具/依赖；PG隔离用已有18.4二进制和临时数据目录，端口/目录须独占且不访问正式凭据。

后续真正补数前，最小范围核日历、缺口周期、相邻因子文件/列和变更对象数；先复用旧证据及stat/计数，不读历史行情来估预算。若跨历史替换，按原job实际受影响文件统计大小，列读取/合并/校验/写入及续跑/收尾开销，取得对应范围批准。不得硬写未经测量的总GiB、以元数据确认冒充数据完整性审计，或把预算变成新程序限额。

### 12.11 本次旧20待办正式收尾操作卡（待批准执行）

工作目录/解释器固定/Users/congming/github/goldenshare/lake_console/orchestrator及其.venv；DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home；根沿paths.py。以下只是后续命令规格，本轮不执行。

1. 核要加载的代码/测试提交和白名单，不能把其他脏文件自动部署。只读核本链Raw/Silver四job的在途run、真实writer锁持有者及四sensor当前状态，记录当时值。存在冲突写者不执行。需要暂停时另获本链精确开关授权，不自动暂停/启动其他任务。
2. 在锁内重核§12.2旧pending=上述唯一ID、consumed=true、旧hash/CP；核原Mat7684828/三check/通知7684826；核51c154该周前像、版本、当前stat、新Mat7705014/三check及完成引用。版本或水位与审计后有任何不明变化即停。不得为确认后继完成再扫描2057份Parquet。
3. 使用既有入口，不另写手工JSON修补脚本：
~~~bash
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home \
.venv/bin/python3 -B -m orchestrator.defs.bootstrap.stock_period_history_cli events \
  --lake-root /Volumes/datasource/data_lake \
  --staging-root /Volumes/datasource/data_lake_staging \
  --run-id db67897faf10513982324f86e1793cec58328349a65ac00a91b23ab5150917e8
~~~
4. 本次必须命中§12.5历史确认分支：原events/week/2026-10-23.json缺失则补原version/sha；原completion/week.json已存在应直接复用；manifest.phase改events_complete，最后移除daily原pending。原CLI包装的报告run留真实日志，不发新Mat/check/通知。
5. 有界读回这几个JSON，验证其他水位/键和baseline不变，当前正式文件stat不变，原失败run状态不改；相关资产本次无新业务事件。本次阶段完成即记录结果；不在同一CLI调用顺便规划27日工作。
6. 如失败，只保留原回执和已落盘状态，报告具体失败步骤/尚缺项；下一次明确续跑同命令。禁止重跑apply、confirm-delete、bootstrap、handoff或改RSS，禁止人工删pending、改旧hash/version、恢复旧文件。

正式批准应包含该命令、代码版本、元数据预算、报告run和必要sensor维护范围；本轮文档授权不包含它。

### 12.12 后续实际欠账与Silver操作卡（范围预算待执行前核定）

旧待办收尾完成后才做最小依赖/规模核验。按2026-10-27原意图和已核水位，Raw周线应规划23日欠账和30日当前周，月线规划2026-10当前月；以执行当时水位及源发布为准去重，不逐日重放、不每日建快照。相邻因子候选区间为2026-10-22—27中的实际交易日，变更股仍由原job计算/生成，不由管理员或脚本手填名单。

1. 对已存在的27日原失败run，按§12.8原生FROM_FAILURE继续；先一条Raw验证旧待办已不阻断、原当前意图实际推进，再按共享写锁顺序处理另一频。不能只重执行319的checks来声称数据已补齐；319此前asset失败，需实际执行其原asset。
2. 每条Raw先恢复冻结意图/成功源单元，再完成当时真实欠账与当前周期；因子/上市变化两频历史和周期输入仍同一批汇集，已完成文件不重复生成。出现真实source_not_ready/adjacent_factor_missing等原门禁停止报告，不改成功口径。
3. 原每频通知只引用本次全部实际变化文件；两Silver sensor按已有cursor消费，旧已闭合批只作为历史；原Silver job按每频全部变化周期处理，不只更新anchor。2014边界、整期上市、最大end_date整行及三套价格不变。
4. 必要检查为原每文件三项及交付范围/版本绑定，复用原候选证据；最后按此次清单汇总，不额外全湖计数/hash/完整性审计。不以两个Raw run的SUCCESS推断Silver全部完成。
5. 完成后核当前意图刷新、已结束周期连续水位、因子消费、pending及Silver cursor/实际批次完成。周中/月中不能提前关闭整周/整月；未来30日/31日是周期坐标而非已完成交易日。
6. 恢复本轮实际暂停且原为RUNNING的本链sensor；原STOPPED仍STOPPED，cursor不重置。保留正式运行/回执和必要审计记录；清理隔离临时资源时只删除本任务精确路径，不能删正式成果、staging续跑证据或共享环境。

正式补数命令应引用当时确定的原run及完整ReexecutionParams，记录源请求/历史读写批准和输出run ID；若执行日期已变更，不擅自把27日原意图改成当天，需先完成原意图再按原计划推进新日期。

### 12.13 测试、真实合同与成本断言

所有新增关键expected均是独立字面值：A/B物化ID、预建/完成顺序、版本/行数、旧/新前像和最终价格不由待测选择/确认helper生成。HTTP夹具参照run_contracts/stock_period.py完整21列和现有真实源证据；真实producer生成输入后仍独立断言字段/Decimal/NULL/业务键。仅用合成metadata验证大量分区的查询次数，不读正式数据。

| 编号 | 场景与关键断言 | 落点 |
| --- | --- | --- |
| A1 | SDK先预建A检查（小行ID）、再B（大行ID），B先完成绑旧Mat、A后完成绑新Mat；选A、0补报，旧实现必须复现误选 | test_stock_period_recovery；新本域证据测试 |
| A2 | 周/月、Raw/Silver均覆盖；PLANNED不遮挡已完成，planned-only仍未完成 | 原recovery/silver_events/daily_integration |
| A3 | 后完成FAILED或晚错绑不能回找旧green；Raw write=False不完成、write=True拒绝；Silver build/update/events/sensor同样拒绝；0新通过 | 原recovery、silver_events/daily_integration |
| A4 | NULL实际ID、实际ID非空但event_logs事件缺失或类型错、正文/索引资产/分区/target冲突、状态与passed冲突、非blocking、未知后端拒绝 | 新共享证据测试、原拒绝用例 |
| A5 | Silver多分区仍2条集合SQL；只拉最新正文；空范围不扫表；另一合法分区不误拦 | 原Silver合同/事件测试 |
| A6 | 合法原前像通过早于新Mat，当前检查确缺时仅补缺；晚错绑不借前像放行；重复补报不新增事件 | 原Raw/Silver事件测试 |
| A7 | Silver首次补报failed/wrong_binding/nonblocking真实错误修复前会刷绿、修复后拒绝；记录旧测试假设错误依据 | test_stock_period_silver_events |
| A8 | 原生check重执行能解决真实失败，事件补报仍不能把失败改绿；不缩小原check范围 | 原生jobs及recovery |
| B1 | 319场景：旧交付原成功、缺CP、合法新文件；只补原CP/phase/pop；0源/0行情SQL/COPY/0业务事件，旧hash及新文件不变 | recovery、combined |
| B2 | 多文件旧清单少任一原检查/通知/CP冲突不能整批关闭；不凭后继整批成功替代原证据 | recovery/history |
| B3 | 原成功存在但当前文件未知/断链：历史成功不得放行新写；前像指向不同文件/根/循环也拒绝 | recovery、history/Silver恢复 |
| B4 | phase已闭合重复调用只验原回执，0旧Parquet读取/stat扫描；无CP/摘要损坏不能伪装已闭合 | history/history_cli |
| B5 | 在每步atomic_json后中断、phase后daily前失败，重复收尾幂等、不倒水位/覆盖新daily | recovery/history_cli |
| B6 | 历史返回不能进入当前anchor；当前元数据必须准确匹配当前合法文件 | 原Raw jobs、combined |
| C1 | JSON hash顺序反转的两旧意图按asof/started_at恢复；两频共用队列；新工作不得越过未确认旧工作 | update、combined |
| C2 | 原意图asset返回后才有native检查：不提前要求、不假绿、不重新生成文件；新意图遇旧缺项明确停止 | 原生Raw jobs/recovery |
| C3 | 原失败run FROM_FAILURE保留日期/分区/业务ID；旧检查补齐后同日原失败更新run继续成功，sensor同key去重不致漏更新 | 隔离PG原生执行及两Raw sensor测试 |
| C4 | 连续两日/跨周月原job＋真实checks；只对实际变化周期写一次，已闭合旧记录不回写，Silver全部实际变化得到处理 | 原integration/combined及silver_daily_integration |
| C5 | 配置日期与物理运行日不同仍用原日；旧manual None跨日不猜今天，有原asof时现有字段明确恢复；无依据拒绝 | 原配置/Raw job测试 |
| C6 | 旧完成但新日run已失败用该run重执行；没有当日run才原sensor提交；不改key/cursor/19:30/默认开关 | 两Raw sensor及原生job小场景 |
| D1 | events动作源/行情SQL/COPY/正式Parquet读取均以哨兵计数为0；只允许本轮JSON及DG事件查询 | 原CLI/recovery |
| D2 | 文件已提交后内存中断/取消，只续未完成；成功源/文件复用；不新增RSS覆盖 | 原handoff_memory/recovery适用用例 |
| D3 | 21列/三套价格/NULL、自然月末/20200228/29、上市整期/2014边界不变；未命中股/分区保持 | 原contracts/projection/jobs直接回归 |
| D4 | 保存及清理本任务临时目录/PG；不访问正式instance/Lake/凭据/网络、不安装依赖 | 测试入口审查及收尾记录 |

SQLite先跑上述受影响测试；PG18.4仅放少量计划/完成/原生job记录验证同一SQL、排序、绑定及原生重执行入口合同，使用独占临时实例及虚拟代码位置，不启动正式daemon或正式code location。网络HTTP使用localhost独立合同响应，不访问Tushare/Prod。安装版GraphQL真实提交/重执行与sensor去重的隔离边界必须明确记录；只mock它们不得声称端到端续跑通过。

**PG及原生重执行的最小隔离验证（开发补充，已完成隔离验证）。** 新测试仅放在tests/test_stock_period_postgres_reexecution.py，不修改正式job/sensor或增加运营入口。沿现有/opt/homebrew/opt/postgresql@18/bin的18.4创建/private/tmp/dg-period-pg.*独占data/socket，固定该独占socket上的55437，listen_addresses为空；清除测试进程和子进程的PG*、DAGSTER_HOME及TUSHARE_TOKEN。连接后先核真实data_directory、库名dg_period_verify及inet_server_addr为NULL，才允许初始化临时Dagster存储。正式连接配置和凭据不作为测试输入；不安装依赖。

输入分两组：①用真实SDK计划和完成事件在临时PG制造A先预建/B后预建、B先完成/A后完成，复用本次共享SQL，独立断言按实际事件选择；②隔离repository中声明一个最小原生asset及三项blocking checks，使用现行StockPeriodRawConfig、原周线job名和分区2026-10-30、意图2026-10-27。asset只写临时计数和日期记录，check只读测试故障标记。该夹具验证SDK调度/配置/检查先后，不冒称实际Raw下载、文件生成或日常控制业务已端到端验收。

后者通过InProcessWorkspaceLoadTarget加载唯一测试repository，使用安装版SyncInMemoryRunCoordinator和SyncInMemoryRunLauncher真实执行，不启动正式webserver/daemon或gRPC code location。此临时协调器直接提交临时run，避免依赖未启动的队列daemon；正式配置不变。真实sensor迭代提交统一run_key builder生成的同日key：首次原生检查失败；再次迭代同key不新增run；移除临时故障标记后，以真实GraphQL schema执行launchRunReexecution(ReexecutionParams，FROM_FAILURE、useParentRunTags=true)，由真实SDK创建并提交子run。必须独立断言asset计数仍为1、只重执行检查、父子/root关系、原配置日期/分区和run key保持、子run成功；再迭代sensor仍无额外run。GraphQL或launcher若无法真实贯通，标该项未完成，不用mock替代。

执行从orchestrator以DG_PERIOD_PG_VERIFY=1 .venv/bin/python3 -B -m pytest -q tests/test_stock_period_postgres_reexecution.py启动；这个环境输入仅是测试文件的显式准入，默认缺失时跳过本组，不由生产代码读取或持久化，也不代表测试通过。只运行此组，不重复已通过的SQLite/Silver58项。临时PG额外空间≤1GiB、数据读写估计≤256MiB、验证预算5分钟；这些是隔离执行估算，不修改生产限额。结束先关闭workspace/instance连接，再pg_ctl只停止此独占datadir，确认退出后删除该独占目录及本轮测试数据；只保留小型结果/日志。启动或断言失败也按同样顺序清理，停止失败则保留datadir并明确报告，不能删除运行中服务的数据目录。正式资源操作为0。

2026-10-28上述最终固定测试2项通过，耗时2.76秒：PG实际结果排序通过；原生父run检查失败后，同key不重建run，真实GraphQL FROM_FAILURE子run成功，asset累计执行1次、子run仅执行1项原失败检查，原配置、2026-10-27意图、2026-10-30分区、run key及parent/root关系保持。此前三次仅测试夹具未贯通（仓库资产图/资源定义不完整、默认协调器只入队），均已按真实SDK合同修正，未改生产代码；四次独占PG均已停止并删除。结果小记录为/private/tmp/dg-period-pg-reexecution-results-20261028.json。测试出现SDK的分区check预览提示及异步生成器关闭提示；未影响断言，不据此宣称正式webserver/daemon或业务Raw文件链完成验收。

2026-10-28全组回归另发现test_stock_period_memory_resume.py::test_cli_resumes_copy_without_redownloading_completed_week最后一次调用仍期望files_complete后resume返回成功，与§12.5既定events动作边界相冲突。保留首次中断后resume、原身份/源复用、6GiB覆盖、精确价格和文件不变断言；只将末次已完成文件阶段的调用改为明确events_required拒绝。此为已批准CLI合同的旧测试预期纠正，不修改生产实现以迎合测试；原失败及定向复验分开记录。

执行前检查测试是否受专项启动器保护；有受保护入口按原规则运行，不绕过。现有venv可用后，从orchestrator运行受影响pytest（-B）、修改文件默认Ruff和E9/F63/F7/F82基线；不uv sync、不安装。修复失败先定向补验；固定版本后一次直接回归，不反复全套测试或增加真实性能实验。记录实际覆盖/失败/耗时、SQL/源/文件操作计数及清理路径，不预写通过数量。

### 12.14 文档独立审计与阶段验收

文档审计与代码/正式结果分开。审计逐项从总方案§10回到本节函数/SQL/消费者/配置/操作/预算/测试，再反向检查本节每个新增行为是否在方案范围。独立复核必须重新读三份完成稿及关键代码，不能仅检查作者的摘要。

文档交付必须确认：

- 三个检查选择/补报入口均有落点；旧失败覆盖测试的错误依据及迁移明确。
- 历史时点与当前检查选择分开；旧成功与当前准入分开；未知变化不因历史收尾而放行。
- 原意图返回原生anchor、不同意图阻断、FROM_FAILURE及manual None路径互不矛盾；同日key不变且当天更新有明确续跑。
- CLI events既能有据收尾daily待办，又不规划新业务；快路径、handoff和周线限定补报不漏消费者。
- 旧20恢复0行情读写但允许真实报告run；后续补数历史预算/授权另列；正常、一次续跑及最后验收开销齐备。
- 原三份文档无仍被当成当前命令的删除/bootstrap/旧latest-ID要求，历史结果不伪装成本次开发/测试/正式通过。

2026-10-27文档自检结果记录在本节末；其后代码/隔离结果已在§12.15对账，正式旧待办收尾、实际补数及后续自然运行仍未执行。未来每个阶段验收按本节矩阵填写“要求→实现文件/函数→独立正反样本→实际证据→通过/未完成”，不得由文档完整或测试数量推出业务修复完成。


**2026-10-27本轮文档独立审计记录。** 审计范围为总方案§10、本节、月线§9及直接冲突的历史描述。作者完成稿后重新逐项核对，另由未参与编写的独立审查和SQL/恢复专项复核交叉检查；均只读当前代码/已安装SDK及已有证据，不运行正式资源。CodeGraph使用status/search/impact，源码补核动态CLI、回调、三个选择器和测试消费者；未发现跨Prod/API/前端迁移。

| 复核发现 | 已落本轮修订 | 结论 |
| --- | --- | --- |
| Silver首次report_file及其旧测试会把失败补成green，不能只修Raw/readiness | §12.4、§12.9、A7明确第三入口、旧错误断言依据和拒绝验收 | 已消除设计遗漏；代码仍待修改 |
| decoder若只返回SDK Record，会丢失实际evaluation事件ID，无法判定前像/晚错绑 | §12.3明确record+evaluation_event_id+bound_materialization、内部ID映射及原字段不变 | 接口可指导开发 |
| 只join目标物化不能证明实际检查事件存在；inner join还可能把坏检查删成缺项 | §12.3先排名、再两个独立left join，缺事件保留并拒绝；A4含非空ID但事件缺失/类型错 | 拒绝规则及反例齐备 |
| 纯文件resume没有instance时如何处理旧确认不明 | §12.5明确不自行获取instance、原同意图文件阶段可续、其他未确认旧交付停止并指向events | 不留自动猜测完成路径 |
| 已闭合历史返回若填current_files，会诱发整批stat，或旧结果进入当前anchor | §12.5闭合分支一律historical_only/current_files=[]；§12.7当前anchor单独取证 | 旧交付与当前数据分开 |
| “0SQL”混淆DG事件SQL与行情SQL；小场景run预算可能误当整轮限制 | B1/D1及§12.10改为0行情SQL，明确元数据查询和单场景规模 | 三份预算一致，不新增运行限额 |
| 手动None日期继承、当日sensor去重及原检查恢复顺序容易混淆 | §12.7—12.8分别列原意图、不同意图、自动日期FROM_FAILURE及手动显式旧日期分支；C2/C3/C5/C6覆盖 | 操作路径及停止条件明确 |

实际检查：仓库文档完整性脚本3组均PASS；新增章节4个本地链接/显式锚点检查0错误；24项A1—D4证据用例落点齐备；本次三文件git diff --check通过。完整性脚本只覆盖其原docs范围，本次lake_console相对链接另做上述定向核验；这不证明代码或数据正确。独立复核后再定向核本表修正，未留下已知的方案/LLD矛盾或阻塞开发的设计未决项。

以下为2026-10-27文档轮当时未执行项，保留为历史：程序修改/测试、代码提交/部署、正式DG/DB/Lake读写、sensor开关、旧20状态收尾、27日及后续补数。2026-10-28实际开发/隔离结果见下节，正式操作仍未执行。补数前的实际源发布/依赖、变更对象/历史读写规模和精确操作批准仍是执行准入条件，不是可跳过的空白；取得这些事实后只填实际参数/预算，若超出本设计范围须先回写。该文档轮到此停止；管理员后续批准的开发/测试按下节记录，不据此开展正式修复。


<a id="period-delivery-recovery-implementation"></a>

### 12.15 2026-10-28开发、测试与实现对账

管理员本轮授权：先提交文档，然后严格按方案/LLD完成开发、测试和实现对账；**不执行正式状态修复和补数**。三文档设计基线已提交befd282e0，未推送。当前生产代码、测试、报告及本节结果回写尚未提交；未加载/重启正式code location、未操作正式job/sensor/cursor/DB/Lake。

**实现完成。** 三处检查选择均改用实际结果事件排序和双left join，真实失败/晚错绑/非blocking在业务事件补报前拒绝；原清单与当前版本校验分离，原历史事实+明确后继可只补CP/phase/pending；未知当前文件仍拒绝。共享待办按原意图恢复，原生检查保留物化后的真实执行顺序，历史结果不能当当前anchor，日期/分区不符读源前停止。所有既有events/resume/handoff/周线限定补报/Silver消费者均已迁移或核验；原业务字段/选行/源请求/policy/命名和sensor key不变。原生失败用既有FROM_FAILURE，不引入新正式配置/入口。

**性能复核已落地。** 未闭合当前同版确认2文件与100文件均为3条实际SQLite SQL（两频为4），不再逐文件新增查询；真实历史变版才追加有限取证。共享后继/候选JSON各只读一次，缓存版本变化拒绝。ack由平方级stat改为入口/阶段整体核验、逐项相关控制核验；2/100项CP存在/缺失均有线性界测试。首次纯文件完成0确认/重放/通知，恢复分支仍查真实交付。细化点先回写§12.5—12.6/白名单后实现，不改行情计算或新增数据扫描。

**固定生产版本的验证结果：411个去重用例最终通过，0失败/0跳过。** 实际轮次为全组405项（404通过、1条旧CLI末次resume预期失败，102.227秒）；按§12.5纠正该旧预期后，memory模块25项通过（1.123秒）；另补Raw实际job拒绝三例3项通过（3.588秒）、两频缺项及两段合法后继3项通过（2.966秒）。生产代码在全组前已冻结且后续未变化，源文件mtime及hash已记录。没有重跑未变化的404项来堆叠通过数，没有删除原失败/用skip藏失败；旧失败和每个复验XML均保留，最新集合明确为逐用例合并，不冒称一次pytest全绿。

隔离证据包括实际Raw小producer/临时Parquet、完整CLI/localhost HTTP worker/取消/交接/实际Raw job/check，以及Raw→通知→两Silver sensor/job/check；PG18.4实际共享SQL和真实GraphQL/sensor重执行另外验证。PG job为独立最小业务夹具，证明SDK保持原日期/分区/config/root/parent/key且asset只运行一次、子run仅恢复失败check；不将此夹具冒称正式319业务链已执行。容量100项明确为metadata/stat替身测试，实际SQL与失败拒绝真实执行，不等于100份行情审计。

全部A1—D4要求的实现函数、独立正反用例、证据边界及逐项结果见[本轮实现及验收报告](../../reports/dg_stock_period_delivery_recovery_20261028/README.md)；[results.json](../../reports/dg_stock_period_delivery_recovery_20261028/results.json)保留轮次和固定生产代码指纹。Ruff本次所有Python文件默认规则、src/tests致命错误基线、CodeGraph sync/status、文档/新增链接及diff检查通过；独立代码审查的集合读取、共享清单、线性stat、ack根/设备、日期/分区项已关闭，未留下已知阻塞实现项。

隔离PG均按原datadir停止后删除；本轮临时目录/旧函数稿/已应用补丁按精确路径清理，记录见报告cleanup.json。未安装依赖、未操作正式数据。正式§12.11收尾、§12.12补数及自然运行验收全部保持未执行；下一步先由管理员review本次开发结果。
