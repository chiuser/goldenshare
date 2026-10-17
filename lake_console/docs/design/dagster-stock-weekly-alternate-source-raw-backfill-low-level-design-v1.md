# DG 周/月Raw直接源下载、更新与Silver完整性审计共享 LLD v1

更新：2026-10-17。**第8步已完成，两频Raw共2,250文件/4,486,908行；45股两频历史和当前周/月补更、事件及截止点登记全部完成，baseline=ready、handoff_complete=true，截止2026-10-16。** 显式6GiB收尾已通过；46份成功周线源保持原版本，仅剩余月线首次补取46页。父子身份、sensor状态和cursor保持，worker退出、锁释放；自动化继续停用。最新对账见§5.15，修正记录见§5.11—5.14。**§9为已确认、尚未执行的周/月完整性审计及Silver规则；本轮只落文档，不开发、不审计或生成Silver。** Prod后置，R3继续暂停。

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
### 后续Silver的上市周期边界（2026-10-17最新确认，尚未实施）

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

选定已发布交易日作为交接截止，文件、必要事件和对象变动处理完成后才写ready及日常水位；源未发布或缺项则保持未就绪。执行期间跨入的新交易日只作为后续欠账接续，不追逐实时源无限循环。重复交接复用本次完成记录，不重置已推进的日常水位。Silver仍未开发，不能因Raw ready宣称Silver完成。

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

A阶段最小真实源样本已保留；步骤1—7已提交至d46486a5。第6步清退及第7步原155项回归见§5.8；日历相关通过结论已撤回，本轮修复、44项受影响回归及真实只读核验见§5.9，不与历史数量累加。修正已提交ec9a33a0并加载；第8步已按批准启动、当前未完成，停点及恢复边界见§5.10。Silver后续单独开发。

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

**已关闭的衔接问题：** 首次两频job成功后，同日再次进入月线job补记anchor待办，当前run的PLANNED曾遮住此前已完成结果，读取evaluation.partition报错。管理员明确批准后，仅在stock_period_update.report_file_events的同分区limit=1查询增加Dagster已有COMPLETED_ASSET_CHECK_EXECUTION_RECORD_STATUSES过滤（SUCCEEDED和FAILED）；最新真实失败不会被越过，PLANNED不冒充完成。通过、blocking、分区、目标物化ID及文件版本门禁原样保留。新增5项真实隔离存储正反样本覆盖只有PLANNED、PLANNED覆盖成功、最新FAILED、错物化绑定、非blocking；原错误绑定用例继续通过。无API、CLI、配置、Dagster库或DB schema变化。旧失败现场/private/tmp/dg-period-step7-c/保留，不修改原manifest/hash续跑旧指纹。

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
## 9. 周/月完整性审计与Silver规则（2026-10-17已确认，尚未执行）

本节是本次新增审计的唯一细则。先按本节完成一次完整性审计，通过后才生成Silver；不是重新下载或重做第8步。当前仅更新原方案和两份LLD，未开发代码、执行本节审计或生成Silver；未写正式Lake、移动盘staging、事件，未重载定义或操作sensor，Prod后置、R3继续暂停。

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

Silver保留未复权、前复权、后复权三套源OHLC及其他业务字段；日期按标准类型表达，Decimal不降精度，合法NULL及源单位保持。不重算复权价格、涨跌额或涨跌幅，不用日线全量聚合证明周/月公式。具体Silver schema、job/check及写入实现尚未落地，不能将本节已确认规则标成代码已实现。

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

本轮交付只是规则和流程落档。实际审计报告、CSV、Silver代码和正式文件均未因本文存在而完成；审计通过也不代替生成阶段必要的文件落盘与读回验收。文档更新不授权执行代码开发、正式审计或任何Lake、staging、定义、事件、sensor操作。
