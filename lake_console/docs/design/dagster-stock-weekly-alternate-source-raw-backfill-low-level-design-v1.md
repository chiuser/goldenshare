# DG 周/月Raw更新、完整性审计与Silver生成共享 LLD v1

**2026-11-12 六阶段开发、隔离验收及正式切换已完成，11月11日股票复权周/月线欠账已补齐。** 第6阶段实现及独立审计见[第13.19节](#stock-period-stage-six-results)，正式九笔运行、文件验收和六条sensor最终状态见[第13.21节](#stock-period-formal-cutover-results)。第5阶段源码提交为`202739e60`，第6阶段实施设计提交为`982619968`。新流程以[第13节](#stock-period-daily-then-history-lld)为准，第6阶段执行细则见[第13.18节](#stock-period-stage-six-execution)。第1至12节记录切换前实现和执行结果。第13节继续引用其中有效的字段、日期和文件规则。旧删除重建、续跑、建库交接及补事件命令只用于追溯，切换后按第13节操作。

第6阶段提交为`01b727255`。切换前只读事实和已批准实施细则见[第13.20节](#stock-period-formal-cutover)。随后按该节完成正式执行，全程没有重启或重载DG。11月12日首轮自然日更及全部接续已于20:28:02完成，21:07只读验收通过，见[第13.21.5节](#stock-period-first-natural-daily-acceptance)。

<a id="report-attachment-cleanup-20261103"></a>

> 2026-11-03附件清理：相关恢复请求/响应、轮询、旧脚本和测试输出等过程附件已删除；下文旧附件清单、数量、命令和裸路径保留为当时记录，不表示文件仍存在，也不要求重跑任务。保留说明及最终结果，具体范围见[清理LLD20.17](dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#2017-其余恢复过程附件的清理2026-11-03)。


**2026-10-31跨日日期修正已完成开发和隔离验收：** 当前实现规则及463项不重复用例结果见§12.22，新增28项；原任务身份保留，Silver使用逐文件实际来源范围，下载、水位、21列及原检查不改。本轮修改随本次提交保存，未正式补数；28日各项结果保留为历史，不表示29/30日已经补齐。

**本轮补修完成（2026-10-28，开发、隔离验收及独立审计完成，随本次提交保存）：** 已修正来源未变时原ID被旧FAILURE/CANCELED挡住、未完成误入recover的两项遗漏。最终305项普通case及另518个subtest通过，两名非作者分别核对代码/消费者与逐case证据，无阻断；完整对账见§12.18.6。来源变化继续原恢复流程及其既有成本，不能将本轮等待分支的0预算扩展到全部tick。27日已完成补数保持原状，未部署、未操作正式资源。

**上轮开发及隔离结果（历史）：** 周/月Silver sensor区分恢复方案建立与文件处理完成的修复已有281项普通case通过，另有518个subtest，详见§12.17.6。通过记录保留，但撤回“全部硬口径已覆盖、该问题已全部收尾”的结论；这些测试没有证明本轮遗漏组合。该轮未部署、未触发正式job、未重载正式code location或执行正式definitions验证，未操作正式instance、Lake、sensor或cursor。

**正式恢复完成（2026-10-28 11:50）：** 本次原27日股票复权周/月Raw及Silver四项均完成；23日周欠账已补，30日当前周及10月已更新到27日。8GiB续跑成功、原83页完整复用；全部实际通知/检查已确认，pending=0，四sensor保持RUNNING。本轮修改及证据随本次提交保存，未推送。完整结果见[正式恢复记录](../../reports/dg_stock_period_delivery_recovery_20261028/formal_execution_20261028.md)及共享LLD§12.12.6。

**005f21f53开发阶段结果（历史）：** 审计第1—5项已按§12.16完成开发、独立复核与隔离验收。最终固定版本530项中528通过、0失败，2项既有隔离PG实验未启用；136.39秒。三文档及旧相反条款已同步，逐项实现结果见§12.16.9与[五项修复报告](../../reports/dg_stock_period_delivery_recovery_20261028/followup_1_5.md)。本次提交包含五项修复、测试和文档证据，提交号以Git记录为准；未推送、未部署、未修正式状态或补数，测试临时业务目录已清理。

**此前独立审计（88de377ca，历史）：** 该提交发现2项P1、3项P2，原411项不能覆盖这些组合；问题、隔离复现及测试漏项继续保留在[原审计报告](../../reports/dg_stock_period_delivery_recovery_20261028/post_commit_audit.md)。这段保留当时发现，不代表五项仍未修复，也不以新通过结果抹掉旧失败。

**五项开发阶段授权（历史）：** 管理员现已要求把第1、2项也补入LLD，重新审计1—5项方案/LLD一致后，按本节完成五项开发和隔离验收。唯一细节见[§12.16](#period-delivery-recovery-followup-345)，实际结果另记本节之后。此前“只解释1/2、只写3—5文档”的范围为上一轮记录，不再作为本轮开发限制；正式部署、状态修复、补数及sensor操作仍未获本轮执行授权。

**前一轮开发历史（2026-10-28，88de377ca）：** 方案/LLD先提交befd282e0，随后开发、隔离验证及实现对账见[第12.15节](#period-delivery-recovery-implementation)及[报告](../../reports/dg_stock_period_delivery_recovery_20261028/README.md)。411个去重用例的原失败轮次及复验继续保留，不代替上方五项新增验收；未部署、未修正式状态、未补数。第12节为本次实现依据，原5/10/11节历史验收不代表正式恢复完成；字段、源请求、选行、路径、锁及其余有效约束继续适用。

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

本节描述切换前的整段替换。新因子回刷的写入与旧索引清退见[第13.3节和第13.7节](#stock-period-daily-then-history-lld)。

| 意图 | 候选组成 | 不允许的动作 |
| --- | --- | --- |
| 首次bootstrap | 空根仅取本次完整成功源单元 | 读取旧行情、合并旧键、旧Prod补洞或因源空写空文件 |
| 当前周期/欠账 | 选定周期按(ts_code,trade_date,freq)整行upsert | 扩到其他周期、逐日重放或本地重算价格 |
| 单股完整历史刷新 | 保留非目标股原行 + 目标股本次完整非空历史；移除该股源不再返回的旧键 | 空源/失败/缺页先删除、误改其他股票或未选频率 |

日常执行先规划欠账/当前周期、相邻因子变更、确认新上市及退市对象；下载可以先欠账后当前，但不能下载一批就先提交一轮。所有成功输入按频率一次导入、受影响分区取并集、统一候选，一个分区只组装/校验/提交一次。一个频率负责的当前周期与涉及该频率的历史刷新必须同批合并；因子触发两频历史，各频率共享同一变化通知，不能由两个job重复消费。

“一次组装”指业务行集合只生成一次，不保证分区COPY只生成一个物理片段。临时多片段按[§5.12](#step8-candidate-fragments)只做必要归并，正式仍为每分区一个文件；不重做源导入、业务组合或复权计算。该修复已实现并通过隔离验收，尚未用于正式续跑。

周期回包和完整历史回包有重叠键时，21字段完全一致可合并为一条；同键异值保留两份证据并停止冲突输入，不按先后顺序覆盖。需要重取时只针对冲突对象/范围，不能重新下载整个市场。20200228/29是不同键，两条均保留。

历史替换的范围是目标股旧分区与新源分区的并集，包括仅旧键所在分区。旧范围必须来自可验证且完整的baseline范围及文件登记，选中目标先核归属，再读取合并所需旧行情；缺失、漂移或不能证明覆盖旧范围时停止，不能自动读全频键/filename列定位。具体索引、新上市和纯明确周期规则统一见§12.16.4，本条不再保留原扫描回退。首次bootstrap不读取旧行情。多股汇集处理，不能每股重扫全历史。移除后空分区按明确的有效空候选处理，不能以此掩盖源下载失败。

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

以下是现行合并任务的运行和恢复口径。切换后的20:00预检、当期日更和历史回刷按[第13节](#stock-period-daily-then-history-lld)执行。

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

同步文件固定为[运行合同治理](dagster-run-contract-governance.html)、[资产与任务拓扑](../architecture/dagster-asset-job-topology.html)及tests/test_run_contract_static_gates.py；现有EXPECTED_SENSOR_DEFINITION_IDS和test_sensor_definitions_use_registered_definition_tags须完整登记/验收，同时在本域sensor测试中断言两个定义的精确分类、目标job及默认STOPPED；不得删除名单核对或放宽其他sensor门禁。正向为两定义均复用统一helper且三项值正确；反向须抓住缺键、错层级/角色、手写字典、漏登记或意外默认RUNNING。2026-10-17最初分类设计阶段仅编文档、等待确认的状态已经结束；程序/隔离及正式接线结果分别见§11.12—11.13，不在本轮重新创建或初始化sensor。

单tick先看根可用性、当前相关运行/已有待办，再从该频率Raw资产读取cursor之后最早一条本合同observation（limit=1），校验小引用及完整清单；没有通知则0 DuckDB/0 Parquet。一次最多一个Raw交付、一个RunRequest，先处理最早未交付批次；批次内历史周期是既有Raw实际改动范围，不在sensor中发现或重算全历史。一次Raw周线任务若也改了月线，会发月线资产通知，月线sensor由此处理全部相关月份。

新增本域batch readiness helper，按明确的asset/check/partition集合查询：一条集合SQL取Raw和Silver各期最新物化，一条集合SQL取各期/各check最新**已完成**结果（包含失败、排除PLANNED）。使用当前安装Dagster SQL event log schema及只读index_connection，参数化过滤；只对当前受支持SQL存储工作，未知后端拒绝而非退回逐期API。返回最多2N物化+6N检查，不先limit N条历史再在Python中碰运气。Raw必须具备通过、blocking、分区及实际物化ID绑定，metadata版本匹配真实文件/receipt；Silver文件归属按§11.3—11.4的事件或明确checkpoint识别，DG缺登记标为待补而非ready。未知文件、真实失败/错误绑定阻断；普通readiness仍必须具备真实物化和完整检查，不把恢复归属证明扩成下游放行。不改Dagster表/schema或通用readiness语义。

sensor查询用于准入；job启动时同一helper核对实际输入/前像，防止排队期间过期，随后仅在提交边界查精确文件版本。这里重复的是启动边界的小型状态核验，不重复行情扫描/完整性审计；不得再加逐unit、逐check的Dagster查询。不能证明批量SQL语义等于现行正式检查绑定时，停止该项实现并先讨论。

旧通知被新Raw覆盖时：先按原通知列出的周期集合查询最新Raw物化；只有最新合格物化的本合同引用能定位一个完成receipt、且该receipt确实包含当前期/当前版本时，才可在**新执行冻结前**选用更新版本。相同新receipt只读一次，不调用要求旧complete所有文件仍为原版本的completed_files去消费旧通知。记录每期old→new的覆盖关系；不丢原通知里尚未被后续改动覆盖的其他周期。新通知额外涉及的周期仍由其自身消费，不能仅处理最新通知就跳过旧范围。未发布的新文件、未知引用或不合格检查必须等待/报错，不猜最新路径。

执行冻结后源又变：保留已提交文件与旧执行，不改原计划；恢复沿§11.4统一规划，指定当前未完成执行建立后继，并凭同版本checkpoint/实际事件跳过已完成unit。不能先要求旧整批完成或DG全部登记，才允许承接。旧批次只有其全部周期已交付、或逐期被明确的新完成结果覆盖后才能ack；覆盖关系沿既有事件回执保存后继ID/hash、该期实际版本与事件引用，未完成覆盖不生成events_complete.json。不能仅因run被提交、cursor读到通知或最新周期成功就推进。

cursor保持O(1)：schema_version、已消费observation位置、当前batch_id/observation位置、当前实际execution_id、最后decision/evaluated_at；不放完整文件/分区/错误清单。承接后保留原batch待办，实际execution_id取统一规划/执行结果；原→新来源在execution/checkpoint，不塞cursor或改原batch_id。只在文件及事件完成证据满足后ack；sensor崩溃重复看同通知，由稳定run_key及显式执行记录防重复。已有活动run只跟踪。失败/取消/检查异常保持待办；输入未变给出原ID恢复，合法新版则给出明确的承接配置及后继ID，不每60秒自动重试失败任务。需要新真实运行时沿统一repair-attempt run-key构造器并明确批准范围；execution的后继ID不是新run_key，禁止用它或时间戳绕过调度去重/授权。

**第2项完成确认的实现落点。** 资产返回后Dagster才产生anchor原生物化/检查，所以资产内只保存非anchor登记事实，不提前写整批完成。sensor下一tick在原两条集合查询中确认全部实际文件及绑定检查后，沿原events/<freq>/<period>.json及events_complete.json汇总登记事实，再推进cursor；不是再次运行CLI、发事件或计算行情。这里只补既有小型状态JSON，sensor仍不写业务数据、不请求源、不COPY、不补DG事件；“只读”指消费数据和DG证据，不把必要的完成回执误列为范围外任务。汇总与文件阶段共用现有Silver锁，真实失败/错绑定或版本不符不写完成，回执写失败不推进cursor、不回滚文件；重启后从实际证据补记。已完成批次复用既有回执，后继完成沿原record_update_coverage关闭祖先，不改原执行身份。本段落实原§11.4/§11.6收尾要求，不增加配置、job、扫描、查询次数或独立审批步骤；隔离验收覆盖job成功但回执未保存、回执保存失败续跑、重复旧通知及真实检查失败仍拒绝。

批次全部周期被2014下限排除时，记录范围排除后ack，不创建空Silver任务。已确认完成的同batch重复通知直接复用其交付记录推进通知位置，不要求旧输出在后来合法更新后仍保持旧版本；当前数据是否对齐由后续真实新批次负责，不能因重复旧通知重新生成行情。未完成旧批次则必须按上述逐期覆盖规则处理，不能套用这个快捷路径。

**恢复任务尚未执行时的确认前置条件。** 本节后续修正按§12.17：execution.json仅代表方案已冻结，不能证明文件处理已完成。当前pending实际执行缺少文件阶段汇总时保持明确恢复指引，不读取不存在的CP或提前确认；有汇总但记录不全、身份/版本矛盾属于异常，不能按普通等待放过。该修正不新增自动重试、任务、配置、cursor字段或查询。

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

Silver的日期、范围及同版本绑定必须按§12.16.2抽取共同校验；不能只检查检查事件的passed/blocking，而遗漏物化本身的silver_asof等必要事实。该项已按§12.16.2开发并新增验收，结果见§12.16.9；§12.15原测试不代替本项新增证据。

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

分支一：原phase=events_complete且本次允许范围内全部原单文件CP、每允许频率completion CP完整一致。
- 核原run ID、identity_hash、complete hash、原完整文件集合、本次允许范围CP的version/sha以及notice/file_count/observation_id有效；每允许频率原通知存在且与原引用一致。完整receipt仍校验，未允许频率的CP/通知/目标不访问；整批events_complete另按本次范围是否覆盖原全部实际频率计算。
- 这一分支一律返回historical_only=True、current_files=[]，只表示原交付已完成，不尝试判断每个旧文件今天是否仍当前；不逐个stat或重读后来已更新的旧目标、不重新补报业务事件。当前anchor由§12.7单独按必要文件核验，不能为填current_files重扫整批。原有闭合回执作为持久证据，不为重复调用重新扫描该批全部DG检查。
- 如果daily仍引用该执行，原daily工作必须consumed=true且控制水位具备消费依据才能移除；第2项新增的kind=history工作没有daily消费含义，按§12.16.7核原冻结身份及整批交付后移除，不读写因子/刷新水位。局部频率确认仍不能删除任一类待办，不把旧listed写回当前baseline。

分支二：files_complete或回执缺失，需从真实历史事件补确认。
- 本次允许范围内的历史文件须核原物化的资产、分区、路径、行数、文件版本及原completion完整引用，原三check按§12.3选择并准确绑定；涉及历史文件的频率须有其准确原通知及file_count，缺证停止。仍当前版本则按§12.4区分已有真实错误与合法缺物化/check/通知，合法缺项沿原回调补缺，不因另一文件已历史化就一概报历史缺证。未允许频率不查询或补写；允许范围补齐后重新确认，齐备才补回执。
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

**内部返回值与接线（已按第4项统一，不是新持久化合同）。** confirm_delivery回调接收本次run目录，返回下表；无完整原事实时返回未完成原因，证据矛盾则抛错。bootstrap模块不猜bool、不将None当成功。允许频率的确认与落盘按§12.16.3补齐。

| 字段 | 约束/用途 |
| --- | --- |
| run_id、identity_hash、file_receipt_hash | 精确等于本次原manifest/complete；ack逐项重核 |
| files | 原冻结清单，不增删、不改version/sha/rows |
| events_complete | 仅原整批文件及所有频率通知事实齐备时true；不是job成功或当前文件存在 |
| allowed_events_complete | 非空允许范围内的全部文件和对应频率原通知均已证明；允许范围小于整批时可为true，但events_complete仍须为false |
| historical_only | 已闭合旧执行的重复调用一律true；本次补确认的旧批只要存在合法替换也为true；不能交给当前anchor |
| current_files | 原清单中经当前stat/合法receipt确认仍适用者；历史文件不得混入 |
| file_evidence | 以(freq,period)为键，列原materialization_id、逐检查evaluation_event_storage_id及绑定ID；历史确认另列后继原执行ID/hash/物化ID及截点；已闭合CP复用时显式注明原CP来源 |
| completion_evidence | 每频原notice和真实observation_id；每频file_count与原清单一致 |
| control_versions | 本次所读manifest/complete/相关CP/daily的版本或摘要，用于锁内防漂移；仅存在内存 |
| reason | 未完成时区分缺检查、需原run、未知变化、缺历史证明；日志必须包含原job/日期/分区/执行引用 |

replay_events首先核原receipt，再调用确认回调；允许范围完整时按§12.16.3调用同一ack补该范围回执。整批完整才进一步关闭phase/pending，局部完成不得返回整批成功。允许范围尚不完整时，仅仍当前且确属原规则允许补缺的文件进入原补缺路径；完整历史证明单独保留，不进入当前文件守卫、审计缓存或事件回调。补缺后重核允许范围再ack。文件不明/原历史事实不全/晚失败错绑必须拒绝，不能因confirm返回False就自动走补绿分支。无确认回调的纯文件路径不负责daily.pending收尾。CLI apply/resume仍保持不自行创建/获取instance的纯文件边界：若存在另一个需确认旧待办，或本次run已到文件完成阶段却缺DG确认，须在新请求/COPY前停止并指向已有events动作。只有当前要恢复的同一冻结意图尚处于文件阶段、且没有更早未处理待办时，才可沿原文件checkpoint继续；文件阶段完成即报告需events，不关闭pending、不冒充业务交付完成。旧phase已完成但当前文件变更，纯文件入口也指向events作历史核实，不自行跳过守卫。

run_period对files_complete/events_complete的恢复分支先走这一共同入口，再决定是否核当前目标/补事件，不能先调用旧completed_files逐个stat而重现本次错误。首次完成文件阶段的源/候选/发布流程不变，随后的事件阶段同样进入该入口。_execute_daily_locked在调用run_period前先确认已完成文件的旧待办；全部旧待办按各自kind收尾后，才进入当前规划。已闭合原回执快路按允许范围复用；未闭合批重复replay仍重新核最新真实事件，只补实际缺项，齐备者不重复写入，不能因已有部分CP跳过检查。

ack接收已核allowed_events_complete=true结果，写前重核身份/摘要、精确允许范围及相关当前stat；局部仅补原回执并返回pending_removed=false，events_complete=true且确实覆盖原整批时才执行phase/pending收尾。不得通过伪造整批true绕过范围检查；原daily工作consumed=false的守卫继续保留。kind=history按§12.16.7单独核冻结身份，不伪造consumed、不推进因子或上市集合。所有调用沿同一writer锁，不让“确认成功”和“下一次新写”之间插入不受保护的本域写者。


### 12.6 状态落盘、目标守卫与异常恢复

ack入口自身也须核run目录严格位于staging/stock_period/runs/run_id、identity.root匹配及原设备标识，不只依赖调用者已confirm。所有正式Raw写入与本节收尾使用既有stock_period/writer.lock，不增加另一把锁或绕过flock。锁内依次：

1. 核完整原身份/清单/所有缺项证据；已有回执必须逐项相等，不能覆盖矛盾回执。
2. 原单文件events/freq/period.json仅补原version和sha256，保持现有格式；已存在且相等直接复用。
3. 原events/completion/freq.json缺失时写原notice及真实原observation_id；已有则核相等。不是创建新通知。
4. 允许范围小于原整批时，到第3步即返回：不写manifest、不改phase、不改daily/pending或baseline。只有全部原事件事实/回执齐备、确认范围覆盖整批时，才将manifest.phase改为events_complete；原identity、identity_hash、complete.json、file_receipt_hash、源页、候选及committed不改。
5. 整批完成时最后读回最新daily.json：daily工作只移除精确匹配原run_id/原intent且consumed=true的pending；kind=history工作只移除冻结身份与原交付完全相符的本条。其他键、其他待办、completed_through、last_refresh、last_source_asof、factor_through以及baseline全部保持。后续全频确认不能只凭此前局部CP就推断整批完成。

沿atomic_json的临时小文件→fsync→os.replace写入，每一步后中断均保留已完成事实。恢复先验已有CP/phase，再补缺项；phase已改而pending未移除时只补第5步。daily有新进度不能被旧副本覆盖。确认失败不回滚已提交行情，不创建行情备份或快照。

当前文件准入仍单独执行：即将生成/覆盖的每个目标须匹配baseline已登记版本或由当前合格物化定位的明确后继committed记录；目标前像继续进入候选receipt，发布时再次校验，原publish守卫不减弱。未知文件即使有一份旧历史成功也拒绝。

**2026-10-27开工细化及第5项修正。** 修复前assemble只捕获现存stat作为target_preimage，原范围索引漂移还会回退读取，不能独立证明目标归属；该问题已按§12.16.4修正。因此必须在读取旧行情及COPY之前，先按§12.16.4从可信元数据确定selected目标，冻结前像并调用内部validate_targets(targets)；run_period注入同一归属核验。targets只含已选freq/period/path/version，不读未选文件。新目标指baseline未登记且目标不存在；baseline已有登记但文件缺失必须拒绝，不能用单股历史把整分区重建成仅目标股。已有目标必须匹配原baseline.files的精确版本，或当前原执行已校验/committed的精确版本。后继版本须先通过本节原交付/范围记录恢复形成已核归属，不能在新任务里把未知stat认作前像。copy.json复用路径同样核冻结前像/当前原提交，不能靠缓存绕过。字段、选行、计算、COPY次数、policy及原publish核验不变；本项取消locate_old_keys自动全频扫描，不允许先读历史再判断有无读取资格。旧index反例实际上缩窄了stock_ranges却未同步hash，无法证明只是hash字段损坏；原“hash失效仍回退一次”的要求由§12.16.4替代，须保留坏样本并改验收为旧行情读取前停止。可信索引下未选文件的物理变化不影响本次明确目标，不为此新增全湖glob/stat。第1项rename成功但提交回执缺失的恢复另按§12.16.6实现及验收，不能只借本项归属守卫的测试推断其通过；五项分别对账见§12.16.9。

所有新写入口，特别是deliver_asset的history分支与CLI history/resume，必须先经过同一旧待办检查；不能仅日更受保护、手动历史仍能覆盖未确认文件。events只补确认/事件，不顺便规划新日期、因子或历史。handoff沿其原冻结父子身份，不重跑父bootstrap。

### 12.7 共享待办执行与原生anchor

_execute_daily_locked重构为先恢复/确认旧待办，再做当前新规划；必须在_daily_work、factor_changes及任何源请求之前完成旧待办分类。两频共享队列不按传入freq过滤掉另一频待办。

顺序键为已冻结intent.asof（存在时）、真实started_at、execution_id。无asof的主动历史先使用§12.16.7写在pending中的started_at；manifest存在时两者必须精确一致，禁止用新的时钟覆盖。未建立manifest的daily work沿原asof；缺日期/开始时间或非法值不得用文件mtime/哈希键猜先后。同日以真实开始时间为先，再以ID作稳定tie-break。

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

以下为本轮获准开发白名单及消费者审计分类；前轮及五项修正的实际改动分别见§12.15、§12.16.9，纯核验薄入口/合同没有必要不改。未列明的新入口/配置仍须先回写原设计，不自由扩展。

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
| 原执行/交付/消费事实 | 原manifest/complete/committed/events及daily/baseline；本轮允许§12.6状态收尾及§12.16.7在原daily.pending_work中登记主动history、冻结started_at；原identity/hash和源业务合同不改。正式实例/状态操作仍未获本轮执行授权 |
| event ID及目标绑定 | 现有DG SQL存储；只读；新本域SQL模块和三个选择入口；随代码加载生效，无schema/config变更 |
| sensor状态/游标/run key | 正式instance原值；本轮不读写；未来维护只核本链四项并保留原状态，不能由definition默认值覆盖运行状态 |

### 12.10 性能、读取与中断预算

不新增运行限额、并发或性能实验；本表是范围/开销的执行前对账。已有合同证据优先复用。

| 阶段 | 正常读取/写入 | 一次中断续跑及最后验收 |
| --- | --- | --- |
| 2026-10-27文档阶段 | 当前代码/已有审计JSON；0行情内容，0正式写入 | 只复读修改文档及必要源码，不跑业务 |
| 隔离测试 | ≤3股、2频、≤8个小周期文件，独立字面21列；每个检查顺序/续跑小场景≤12个原/重执行run（不是整轮既有回归的总run上限）；临时资源预计读≤256MiB/写≤128MiB/空间≤512MiB | 故障注入包含一次中断/恢复和必要原生重执行；总计读≤512MiB/写≤256MiB/空间≤1GiB；非生产配额/限额，不用真实多年行情 |
| 本次旧20收尾 | 旧manifest约216KB、complete724B；后继manifest217182B、complete1179303B、单文件commit588B；另daily/baseline和少量CP。原文档估JSON读≤8MiB，已由§12.11实测校准为正常阶段合计≤16MiB；写≤2MiB。原/新Mat各1、原/新check共6、原通知1及目标前后stat | 含一次续跑和最后核验：按§12.11校准JSON读≤24MiB、写≤4MiB；上述事件集合至多每轮一次；最后只读原小型控制记录，baseline用未变化stat复用原已核内容，不再次读取后继完整清单；相同文件stat确认，不读后继2057份文件 |
| 新SQL | Raw当前单文件一组查询取三check；Silver每参与频率每轮保持2条集合SQL，首次两频预取及必要写后批量重取按§12.16.2；确认仅查明确receipt涉及的资产/分区/事件窗口，历史取证另按§12.16.3计 | 存储失败重试须显式操作，不自动重扫；只拉最新正文，事件范围不得扩大成全库 |
| 后续Raw/Silver补数 | 由当时实际欠账/因子变更/交付清单确定，正常/中断/验收分项列清后批准 | 不含在旧20“0行情读写”中；不得用本节代替历史读取批准 |

旧20收尾的源请求、行情SQL、DuckDB、COPY、行情文件读写均为0，新增业务Mat/check/通知为0。原events CLI可产生一次stock_period_event_report控制面run及正常日志/终态，必要时至多显式续跑一轮；不能将其说成“DG完全零写入”。无需安装工具/依赖；PG隔离用已有18.4二进制和临时数据目录，端口/目录须独占且不访问正式凭据。

后续真正补数前，最小范围核日历、缺口周期、相邻因子文件/列和变更对象数；先复用旧证据及stat/计数，不读历史行情来估预算。若跨历史替换，按原job实际受影响文件统计大小，列读取/合并/校验/写入及续跑/收尾开销，取得对应范围批准。不得硬写未经测量的总GiB、以元数据确认冒充数据完整性审计，或把预算变成新程序限额。

### 12.11 本次旧20待办正式收尾操作卡（2026-10-28已获准，按下述前置推进）

工作目录/解释器固定/Users/congming/github/goldenshare/lake_console/orchestrator及其.venv；DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home；根沿paths.py。2026-10-28管理员已要求按LLD及既定顺序正式推进；先完成§12.16.10路径遗漏修正与隔离验收，再按本操作卡执行。具体历史行情读取仍须按§12.12另核范围，不能以本次旧回执收尾授权代替。

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

原文档阶段只提出上述正式操作卡，并未授权执行；管理员现已批准按该顺序推进，命令、已验源码/版本、下述实测元数据预算及控制报告run均纳入本次旧20收尾。当前不需要启停本链sensor；任何额外维护开关或真实历史行情范围仍按各自规则核定。

**2026-10-28执行前事实及预算校准。** 只读核对时DG webserver/daemon未运行，本机PG/CH/既有隧道查询就绪；本链四sensor持久状态均RUNNING且四job无在途，writer锁空闲，旧pending、原前像及当前版本与§12.2一致。events CLI直接加载当前已验源码，不需要先启动DG；因此先收尾旧回执，启动服务留待原生job阶段，不重置cursor或为本动作启停sensor。此次精确控制JSON共5,708,455字节，其中baseline为3,878,591字节；原§12.10正常8MiB估算未充分包括这份baseline。旧20阶段现按正常含已完成预核/原CLI/必要读回总JSON读取≤16MiB、写≤2MiB，含一次明确续跑及最后验收读取≤24MiB、写≤4MiB；不重复读取baseline，未变版本复用其摘要。范围仍是操作卡列出的原/后继控制记录及唯一周目标，无额外行情内容或后继2057项文件属性访问。这是小型控制元数据的实测校准，不新增运行限额，不扩大行情读取授权。

### 12.12 后续实际欠账与Silver操作卡（范围预算待执行前核定）

旧待办收尾完成后才做最小依赖/规模核验。按2026-10-27原意图和已核水位，Raw周线应规划23日欠账和30日当前周，月线规划2026-10当前月；以执行当时水位及源发布为准去重，不逐日重放、不每日建快照。相邻因子候选区间为2026-10-22—27中的实际交易日，变更股仍由原job计算/生成，不由管理员或脚本手填名单。

1. 对已存在的27日原失败run，按§12.8原生FROM_FAILURE继续；先一条Raw验证旧待办已不阻断、原当前意图实际推进，再按共享写锁顺序处理另一频。不能只重执行319的checks来声称数据已补齐；319此前asset失败，需实际执行其原asset。
2. 每条Raw先恢复冻结意图/成功源单元，再完成当时真实欠账与当前周期；因子/上市变化两频历史和周期输入仍同一批汇集，已完成文件不重复生成。出现真实source_not_ready/adjacent_factor_missing等原门禁停止报告，不改成功口径。
3. 原每频通知只引用本次全部实际变化文件；两Silver sensor按已有cursor消费，旧已闭合批只作为历史；原Silver job按每频全部变化周期处理，不只更新anchor。2014边界、整期上市、最大end_date整行及三套价格不变。
4. 必要检查为原每文件三项及交付范围/版本绑定，复用原候选证据；最后按此次清单汇总，不额外全湖计数/hash/完整性审计。不以两个Raw run的SUCCESS推断Silver全部完成。
5. 完成后核当前意图刷新、已结束周期连续水位、因子消费、pending及Silver cursor/实际批次完成。周中/月中不能提前关闭整周/整月；未来30日/31日是周期坐标而非已完成交易日。
6. 恢复本轮实际暂停且原为RUNNING的本链sensor；原STOPPED仍STOPPED，cursor不重置。保留正式运行/回执和必要审计记录；清理隔离临时资源时只删除本任务精确路径，不能删正式成果、staging续跑证据或共享环境。

正式补数命令应引用当时确定的原run及完整ReexecutionParams，记录源请求/历史读写批准和输出run ID；若执行日期已变更，不擅自把27日原意图改成当天，需先完成原意图再按原计划推进新日期。

**跨日源日期的必要有界核验。** 当前Raw只拒绝源maximum_asof低于冻结意图，Silver则按该意图asof拒绝更晚end_date，不能在源已推进时假定原27日链必然贯通。旧回执收尾后先用tushareMCP取000001.SZ单股两频四列ts_code/trade_date/end_date/freq：week固定trade_date=20261030，month固定start_date=20261001/end_date=20261031（与原请求日期规则一致）。共2次有界请求，预计≤32行/≤8KiB，无行情价格或历史全量读取、无Lake写入；只用于尽早发现日期冲突，不据单股宣称全市场源合同已验收。若返回已超过27日，按既有冲突门禁停止报告，不改旧意图/原回执日期，不补绿。后续真正下载仍须对全部本次输入按原规则检查。

#### 12.12.1 必要参考/因子预核的单独读取范围

旧20已在2026-10-28 09:33完成原events及有界读回，原待办清零、原水位/文件/四sensor及cursor保持，新增业务事件0；报告run=0b36ac11-c60d-4dc5-8dc7-a27d23666819。随后仅有界查2026-10-19—27日SSE日历、当前L/CNY计数及以下文件属性：当前上市5577、baseline上市5576；相邻比较为21→22、22→23、23→26、26→27四组；所需五份因子文件均存在。此为批准前的范围证据；本次获准预核的实际结果见下段。

按根AGENTS“数据集全局读取审批”，下列必要投影虽小，也须在单独明确批准后执行；一般“继续推进”不替代该批准。本阶段只形成预算证据，不运行正式数据job、不写Lake/staging/instance，不把预算名单填入正式job.stock_codes。真实任务继续由原job生成名单。

| 目标/方式 | 字段与范围 | 文件大小依据 |
| --- | --- | ---: |
| silver_stock_basic一次 | 当前完整快照投影ts_code/list_status/curr_type，原L/CNY过滤 | 421165 B |
| silver_stock_identity_map一次 | 当前完整快照投影source_ts_code/latest_ts_code/confidence，原confirmed过滤 | 103186 B |
| silver_trade_calendar一次 | 原calendar_days的SSE trade_date/is_open完整投影；过滤列exchange也参与读取，不能把正式helper说成只读9天 | 89590 B |
| silver_adj_factor四组比较 | 2026-10-21/22/23/26/27的ts_code/adj_factor两列，全市场；原factor_changes四SQL、8次文件投影，5个不同文件 | 每份55539—55566 B |
| raw_stock_basic条件有界核对 | 仅存在移出集合对象时，按相关代码过滤ts_code/list_status及D，不导出全表明细 | 整文件上界454684 B，实际有界投影 |

前三参考加8次因子文件大小基数为1,058,375字节（约1.01MiB）；这不是声称实际列投影读取量精确等于文件大小。正常一次保守读≤8MiB，含一次经明确指示的必要续读及最后核验≤16MiB；临时报告/工作文件写≤1MiB、含续读≤2MiB，额外空间≤64MiB。使用原DEFAULT_POLICY和原连接工厂，只将审计工作目录放/private/tmp，不增加正式任务参数或运行限制，不安装依赖。失败或源文件版本变化停止，不自动重读。

实施复用load_scope、calendar_days、factor_changes、confirmed_retirements，预算C按现行因子变化加新上市、退市/换码旧码分别记录；这些结果只用于核算历史范围，不替代正式job的生成结果。对齐snapshot/文件版本后，按可信baseline.stock_ranges/files/version[2]/rows算旧文件集合/字节及Raw→Silver预算；不遍历湖、不为预算读历史行情。原Raw登记1820周/431月、大小298272360/72658415字节仅为已存元数据上界，不是此次允许全频读取。新源可新增周期、行数/页数不能直接由区间数精确推出，优先复用目标股票已有源回执估算；后续真正源请求与历史合并须另按明确范围/预算批准。

源日期两次有界样本已完成：周标签20261030及月标签20261031的end_date均20261027，与冻结27日相容；仅证明该单股样本，完整输入仍由原检查把关。证据见原报告source-asof-samples.json。管理员已在本次申请后明确回复“批准”，覆盖本节最小参考/因子投影；本阶段按上述范围执行一次，不自动重读。27日原生任务及真正历史读写仍待拿到实际集合后的具体范围/预算批准，尚未执行。

**2026-10-28 10:03预核结果。** 原load_scope/calendar_days各调用一次，factor_changes一次完成四组比较/8次文件投影；移出集合只有000016.SZ，原confirmed_retirements按相关代码有界查询确认其D状态。79只因子变化、新增301718.SZ及920285.BJ两只，并集81；无换码，确认退市1。上市数5576+2-1=5577。原日常算法得到欠周2026-10-23及当前周2026-10-30、当前月2026-10；第一周job预期两频81股历史加2个周单元=164，消费因子后月job只补当月1单元，共165，均为分页前逻辑单元，不冒充HTTP次数。

只用baseline可信登记估算：82股（刷新81+退市1）旧范围并明确周期共1753周/416月，已登记字节297998172/72596795，合计370594967 B（约353.43MiB）；范围最早周1992-03-27/月1992-03，当前周新坐标尚不在旧登记。可进入Silver的既有Raw为657周/154月，登记字节207566803/50374753、行数2538554/606570。以上不是对2169份历史行情的物理读取或全文件核验；真正新源可能带入登记外周期，不能把此数量当最终候选上界。

预核耗时1.72秒。三个参考与8次因子投影的完整文件大小基数1058375 B，条件有界退市再以整文件454684 B保守计费，共1513059 B（约1.44MiB）；不是测得的解压量/设备IO。全部输入和daily/baseline前后版本不变；正式写入、源请求、历史Raw/Silver内容读取及job启动均0。工作目录已删除，结果/集合摘要/参考版本/精确周期、大小及行数清单见原报告reference-preview-result.json及reference-preview-summary.json。此名单仅供预算，不写入job.stock_codes；真正执行继续由原job生成并验证。后续具体历史预算和批准仍单列，预核批准不扩大为正式补数读取授权。

#### 12.12.2 27日原任务的实际源/历史范围与预算（已批准；首周失败后停止）

**目标与授权。** 最小预核已完成，不重复运行helper或增加行情审计。下一步继续管理员既定正式恢复指示，但根AGENTS的具体历史读取批准须覆盖本节后才能触发。范围仅冻结意图2026-10-27及已有周欠账；不把日期改成28日，不新建job/股票参数，不改代码、policy、源契约、sensor key或其他数据集，不重做bootstrap。依据§12.12.1原结果，名单仍由原job现场生成；预算名单不是执行输入。

**具体读取及写入范围。**

| 环节 | 必要范围、方式与保持项 | 实现依据 |
| --- | --- | --- |
| Raw week原任务 | 81只刷新股票按code分别请求week/month全部源历史，不传起始日期截断；另全市场请求周2026-10-23和2026-10-30。确认退市000016.SZ从相关旧周期移除，不发其历史请求；无换码 | stock_period_update._daily_work；stock_period_history.run_period；stock_period.request_params |
| Raw month原任务 | 前一步因子消费成功后只请求全市场2026-10月；仍由真实pending/水位决定，不能再手填81股重复历史 | stock_period_update._daily_work/daily_periods |
| 旧Raw合并 | 按可信baseline中81刷新股+1退市股区间，以及实际新源周期选文件；每个选中旧文件全21列读一次，保留其他股票/合法其他日期。已知2169份370594967 B；新源可选中其余登记旧周期，既有2251份总370930775 B为本轮已登记旧目标大小上界。只读原选择实际需要的文件，不为预算/验收扫全频；未登记的新周期可新建，未知现存目标仍按原归属守卫拒绝 | stock_period_raw._old_range_paths/assemble；stock_period_history.validate_registered_targets |
| Raw候选 | 每频统一导入源CSV一次、一次分区COPY；仅多分片周期增加归并读取/COPY。候选schema footer、全行键/日期列投影一次、完整摘要一次，沿原逐文件CP原子提升；不额外再读一次校验 | stock_period_raw.assemble/_candidate_receipts/_validate_candidates/_merged_candidate/publish |
| Silver | 两Raw通知的全部实际变化周期，week≥2014-01-03、month≥2014-01，到本次周/月坐标；每个真正重建版本全21列Raw一次、COPY一次、Silver候选全21列校验一次。旧Silver内容不读，只核属性/归属。每个有重建工作的job投影生命周期五列ts_code/list_status/list_date/delist_date/is_cny_stock、身份三列source_ts_code/latest_ts_code/confidence；不读日线、停牌、更多因子或Prod | stock_period_silver.make_update_execution/build/select_period/validate_projection/load_references |
| 正常原检查与收尾 | 四类原job进程内执行，三项原checks复用原候选证明/当前进程结果；按实际交付清单、每文件CP、版本及真实检查汇总，不重复候选摘要、全量行情计数或811周期投影 | Raw验证缓存；stock_period_silver.record/validation缓存及原native checks |

源历史不按旧Raw起点1992-03截断；范围为这81股的接口完整历史。日期检查分工保持当前代码：Raw只对显式周期maximum_asof低于其cutoff拒绝，不拒绝更晚end_date；Silver按所属unit冻结asof检查晚日期。因此若源已推进到28日，Raw可能先提交，而Silver才拒绝，届时保留已提交Raw及回执并停止，不回滚/改写日期或补绿。已有单股两频样本均end_date=27日，只是尽早排查，不保证全部新源输入。新源period可以新增目标，不能拿2169封顶最终候选。读取现存目标必须有可信登记/回执；新增周期无旧内容读取。最小预核的baseline摘要9940463ded80828bd9d235131d72b7ae1bf5d2080300a2b18ff17b74b5fe24df绑定当时的登记事实，原job使用原baseline全target/version记录和归属守卫，不用只有period/bytes/rows的预算JSON代替版本证明。准备触发前核小型控制/参考版本及写锁；若对象/因子/水位等已变化导致范围超出本节，先停下重核，不自动扩读。

**请求及文件数量。** 第一Raw周入口164个逻辑源单元、第二Raw月入口通常1个，共165；6000/页，实际HTTP页数为每单元floor(source_rows/6000)+1之和，正好整页还需结束页；原transport每页最多3次尝试，已有完整成功页按身份/版本复用，不增加新重试规则。已有21日18股+一个周周期的37份source complete控制回执均单页，历史JSON+CSV共4229872 B、周全市场样本1583901 B；其中36个单股历史单元按81/18缩放，加3个全市场周期均暂用唯一周样本估计，合计23786127 B（约23.8MB）；月全市场没有独立样本，仅供预算估算，不证明81股单页或给请求/源大小硬上界。只读了这37份控制JSON，两轮142240 B用于初次汇总及保存证据，没有读取/重新hash payload或CSV；详见reference-source-receipts-summary.json。

Silver已登记适用Raw811周期（657周/154月），新周30日加入后已知不同周期812。若两次Raw的10月版先后都被Silver处理，再多一次，故按813次unit访问基数加新源扩出的周期计费；不是承诺只812次或最终物理文件数。能否复用取决于源版本、asof及参考版本全相同，不按“同月”跳过。先后通知的原解析/前像规则继续适用，不手工合并通知或更改cursor。

**预算依据与预计量。** 旧Raw已登记4490896行、2169文件，现有512 B/行+16KiB/文件模型为2334875648 B（2.175GiB）；其中Silver适用3145124行、811周期，沿同一保守行数模型估候选1623590912 B（1.512GiB）。后者是本次预算计算方法，不是声称Silver代码新增该限额。模型不是实际压缩输出大小、内存或设备IO；已知旧压缩文件仅约353.43MiB、Silver对应Raw约246.00MiB。

以所有Raw周期都需要多分片归并的保守情况，Raw分区COPY及规范化两次写、分片读/键日期投影/摘要三次读；再计旧Raw读取、Silver读Raw/写候选/完整校验，模型约读10—12GiB、写6GiB。加新源JSON/CSV写及两摘要读取、CSV导入、参考/控制/footer、当前周期第二版和预计DuckDB临时读写余量，采用下表。默认16GiB spill是同时占用限制，不能冒充累计IO上界、不能乘每个周期推预计流量。累计临时读写单凭代码不能证明严格上界，下表是审批预计开销，不是实测值或新运行限制；本轮不为压实数字再做真实性能测试。

| 计费阶段 | 预计读取 | 预计写入 | 额外可用空间预留 |
| --- | ---: | ---: | ---: |
| 正常原两Raw、对应全部Silver及必要原检查/收尾 | 16GiB | 12GiB | 32GiB |
| 含一次必要同范围中断续跑及最后验收的整轮合计 | 32GiB | 24GiB | 48GiB |

空间包括源JSON/CSV、两频COPY分片/必要merged、Silver候选、可能spill和中断未验文件；不能只按最大单文件留空间。原storage_reserve(spill=True)还要求在候选预留之外有16GiB可用，因此不把16GiB作为整个任务空间预算；32/48GiB为本轮预留，未修改原policy32GiB workspace/16GiB spill。10:11仅目录设备/可用空间stat证明Lake/staging同设备、可用2903250866176 B，未读任何行情内容。

**执行次序、失败/中断和验收。**

1. 取得本节具体历史批准后，通过原启动入口加载本工作区已验版本；复核本链无并发写者、原sensor状态/原cursor和两个原run配置。按§12.8已验GraphQL `launchRunReexecution(reexecutionParams: ...)`：周parentRunId=319ec97d-cfd4-4ef7-bc4a-c98c7334464a、月parentRunId=8c9e09c4-9a82-4042-b696-0ffc3a17999d；两者strategy=FROM_FAILURE、useParentRunTags=true，不提供extraTags或改run_config。原周分区2026-10-30、月2026-10、意图27日及业务ID保持，记录新parent/root子run。不得只补原失败asset的检查。
2. 先周Raw并完成其原交付，再按共享写锁/月原意图继续；待原通知由原两个Silver sensor消费全部变化周期。其他数据集正常调度按管理员既有启动授权保留，不扩大本轮补数/审计范围。本轮不为此关闭/重置任何sensor；如确需维护变更，仍先核原方案/授权。
3. 源未发布、按上述Raw/Silver各自职责查到日期冲突、未知修改/归属、索引不可信、真实原check失败或范围明显超出上述估算，停止报告；日期晚于27日可能在Raw提交后才被Silver发现，保留已提交Raw/回执，不把前置小样本当完整保证。遇到冲突不放宽门禁、不改原日期/hash、不补绿、不自动重新提交。预算内的必要续跑不是失败后自动重跑许可，须先报告断点再按原ID继续。
4. Raw源完整页/已验证候选/提交CP复用；COPY未完成仅重建原频私有未验部分；rename至CP中断只对该明确目标再读一次摘要。merged已出现但证明未写完时，原逻辑只对该周期目标与分片比较；不全批再hash。Silver无validated CP仅重做当前unit，已有validated CP继续发布/footer，committed只核版本。新进程checks-only冷缓存只增加对应anchor的一轮必要验证（Raw键/日期+摘要；Silver该Raw/候选及两参考），由三checks共用；最后不重读所有历史行情。一次中断余量已含表内，不改变现有失败语义。
5. 最后核此次完整交付清单、CP/真实Mat及三项blocking checks、文件版本、因子消费/周月刷新及pending，确认Silver两个cursor实际消费；整周/整月水位按原完成条件，不提前关闭30日周或10月。只清本次无用临时工作文件；正式成果、source/候选/CP续跑依据保留。记录实际run/周期/数量和成功或剩余阻塞，不以Raw成功推断Silver已齐。

管理员在本节具体范围/预算申请后明确回复“批准”，现已覆盖81股两频完整源历史、1退市股处理、原选择旧Raw合并及2014起全部实际变化Silver，预算沿上表。此前最小预核授权与本次正式历史授权分开记录；本次在触发前核对原run/配置、源参考版本和并发写者，再沿原job顺序实施，实际结果另记，不预填完成。

#### 12.12.3 27日首次正式恢复结果：COPY内存超限，未发布

2026-10-28通过原启动入口启动DG（原PG/CH/隧道复用、实际Dagster1.13.26），四sensor仍RUNNING、未重置cursor。以§12.8完整原参数仅提交一次原周父run319ec97d的FROM_FAILURE，子run为**d7ae3495-bb23-4c33-a4be-d78d2aba2742**，27日意图、30日分区、完整配置、run key及parent/root读回一致，包含原asset和三checks；stock_codes仍空，名单由原job产生。全局原并发1先等待正常公告/国际指数任务，未改变优先级/并发或干预其他任务。

本次周子run实际运行时间2026-10-28T10:27:03.741148+08:00至2026-10-28T10:27:45.755284+08:00（约42.01秒）。81股周历史+2个全市场周周期，共83个源单元/83页、70590行已下载完成；source JSON+CSV 19961338 B，含控制回执源目录22523318 B。月历史的81单元及后续当月1单元尚未执行，不能把83页说成整轮165单元已完。

错误为**period_process_memory_exceeded**。冻结manifest中原policy为DuckDB3GiB、进程RSS4GiB、spill16GiB、workspace32GiB、2线程，与原DEFAULT一致；本轮没有新增、降低或覆盖这些参数。栈定位stock_period_raw.assemble:847调用COPY，execute:372为工作线程启动后的50ms内存检查；不是SQL执行前349的检查。异常路径interrupt并等待SQL线程退出后才释放writer。已有进度日志reuse_old_ranges=1753，旧周行情和源CSV已经读取/合并；phase=download仅说明候选阶段未完整落盘，不能据此声称0历史读取。日志未记录实际RSS峰值或各模块内存占用，不能编造超出多少或把压缩文件大小当内存。

候选写出期间超限，尚未完成候选校验/两频准备，未进入history.run_period:1298后的正式publish。精确运行目录属性核对：4902份未验收Parquet分片、151514675 B；copy.json、week.candidates.json、月build、complete和committed均不存在。源/未验build/manifest合计174254656 B（约166.18MiB），全部位于data_lake_staging原执行53a8a26605bc468313dd25069e9a8688d035d51c3b308b7c8d96bba88c4a26be中，保留以便恢复。没有读取这些候选内容作额外审计。

正式文件提交0、原周23目标版本不变、baseline版本不变；factor_through仍21日，周/月last_refresh仍21/20日，completed_through仍16日周/9月；pending保留原27日未消费意图。该run没有新的实际Mat/check/完成通知，只有planned记录；无本链在途任务，writer已释放。原月父run及Silver未提交后续；DG及四sensor保留RUNNING，正常其他数据集调度属于原启动授权，不以其运行结果冒充本链补齐。

**停止与后续边界。** 已按失败即停执行，没有自动重跑、调整内存、修改冻结policy/身份、手工提升分片或删除待办。对后续恢复，原source complete及版本匹配的83页可复用；无copy.json的私有build/week由既有续跑逻辑清理重建，不把未验分片当成果。下一步须先只看当前代码/既有日志核清COPY总进程内存及原运行参数如何处理，在原方案/LLD明确修正或配置方案并获准后再续原ID；不能仅靠提高阈值、另写补数入口或重复试跑绕过。此次失败不推翻旧20成功，但27日Raw/Silver尚未补齐。

精确证据：raw27-week-failure-evidence.json、raw27-week-staging-stat.json、raw27-week-stopped-summary.json、raw27-week-stop-metadata.json及原请求/响应/身份核对记录。独立代码复核纠正了首次口头“COPY前失败”：实际为COPY启动后中止，正式publish前；该更正已同步本节及报告。

#### 12.12.4 已批准本次运行RSS扩到8GiB，沿原job续跑

**目标及既定范围。** 管理员在首周失败后明确要求“扩到8gb。完成补数”，授权本次周/月原job用8GiB进程RSS完成§12.12.2全部补齐。仅调整这轮显式重执行的运行额度，DuckDB仍3GiB/2线程、默认/冻结StockPeriodPolicy.rss_bytes仍4GiB，下载/identity/hash及成功源页保持；不把8GiB写回旧manifest/source/pending.policy，不提高其他数据集或无标签日常任务上限。已经完成的旧20不重跑。

**当前代码阻点及依据。** deliver_asset没有运行RSS输入，execute_daily/_execute_daily_locked没有向run_period传runtime_rss_bytes；run_period虽已有局部process_memory_budget，但verify_rss_resume仅准入bootstrap及精确handoff。直接改冻结policy会破坏成功源单元身份，直接传8又会被handoff规则误拒绝。安装版GraphQL ReexecutionParams支持extraTags、不支持runConfigData，故保持原FROM_FAILURE配置继承，只以其既有extraTags给本次资源参数。当前SDK context.run.tags读取非废弃接口；不使用已废弃context.get_tag/run_tags。CodeGraph已覆盖deliver_asset→execute_daily→_execute_daily_locked→run_period与两个Raw asset入口，模糊同名的Silver/research实现未纳入改动；当前源码补核verify_rss_resume和所有RSS调用方。

**配置审计：**

| 项目 | 唯一口径 |
| --- | --- |
| 名称/来源/存储 | 运行tag goldenshare/stock_period_rss_limit_gib，常量定义在run_contracts/stock_period.py；GraphQL原生extraTags显式输入，存于Dagster该次run.tags |
| 默认及本次值 | 不提供tag为None，保持冻结4GiB；格式为ASCII正整数GiB，本次仅授权值8，转8×1024³字节；不新增env/Settings/业务表/StockPeriodRawConfig字段 |
| 作用范围 | 仅原两个Raw daily job的明确失败重执行；必须有SDK parent_run_id、匹配raw_stk_period_bar_adj_{freq}_update_job、config.intent=daily及明确automatic_intent_date。手动首次任务、其他job/频率、history配置或非法值在读参考/源前拒绝 |
| 消费者与生效 | Raw deliver_asset读取标签并校验→execute_daily透传→_execute_daily_locked.perform→run_period→既有process_memory_budget；source仍取冻结work_policy；bootstrap/handoff旧CLI路径保持原语义，Silver及其他数据集不消费此tag |
| 观测/退出 | 原stage=process_memory日志记录冻结额度、有效额度及当前/采样峰值；仅当前作用域生效，成功/失败/取消后复位；重执行后代继承tag属于原SDK行为，不偷偷改默认值 |

**实现细节与最小文件范围。** 生产只改run_contracts/stock_period.py（tag名）、stock_period_update.py（校验及透传）、bootstrap/stock_period_history.py（精确daily工作准入）。不改IO计算/SQL、源字段、页数、候选校验/提交顺序、三checks、job/sensor或run key。

1. deliver_asset在日期/分区一致性核验之后、ensure_available_for_run/load_scope之前读取context.run.tags。无tag原样返回None；有tag时严格核ASCII正整数及上述原job/parent/显式日期条件，失败拒绝，不读参考或请求源。使用本次资源值传execute_daily，不能写进policy/intent。
2. _execute_daily_locked新增可选runtime_rss_bytes=None，仅转发给perform中的run_period。原pending、原scope、原policy、消费/事件顺序及不同意图拦截都不改。传参正整数仍沿run_period的现有校验。
3. verify_rss_resume先识别有明确asof、完全不含bootstrap_parent键的daily来源（该键即使为NULL也仍按原非法handoff处理）（mode=upsert或带asof的history；后者是合法daily无周期但有因子历史的情况）。核daily.json确实存在该execution_id、work没有主动history kind、frequency在week/month、asof为规范日期；intent.request_id必须等于digest(kind=period_daily,frequency=work.frequency,date=asof)，execution_id再对应目录。用该work的完整intent/policy、sorted listed、aliases及当前root组成现有五字段identity，必须与调用identity完全相同。已有manifest再verify_execution、完整identity/hash及原设备核验不变；无manifest时仅允许这份已持久化的精确daily pending首次创建，不能误拦尚未开始的原月任务。没有精确daily工作、身份/日期/频率漂移或主动history一律不借tag突破。
4. 原bootstrap/精确handoff分支继续先要求原manifest并按原父子/基线校验；非法CLI action和显式history RSS仍拒绝，不能因支持daily扩大旧CLI。run_period仍沿冻结policy下载和验证，RSS值只进入既有内存作用域，不变更manifest/source identity/cache键。

**测试及验收。** 新test_stock_period_daily_memory.py使用现有小型真实producer与临时根，源按已确认doc365独立字面行；RSS仅用字面替身，不实际申请GiB或做真实性能测试。必须证明：4GiB时COPY失败后8GiB可继续、同成功页0新请求且身份/hash/版本保持；超过8GiB仍停止，异常/取消后默认恢复；已有周manifest和无月manifest两个日常路径；合法daily带asof的history工作；错误tag/首次run/错job/错日期频率/pending/身份/主动history读取源前拒绝；无tag默认4GiB及旧bootstrap/handoff回归。透传入口使用真实SDK run/tag或按已核SDK字段构造的明确替身，不能把缺context.run的旧简化夹具当SDK合同；必要时只补其tags={}，不改业务预期。另做临时instance原job选择/配置+运行tag贯通一次，不用正式资源作测试。预计隔离样本≤3股/2频/≤8小周期，读≤64MiB、写≤32MiB、空间≤128MiB；含一次故障/续跑及收尾读≤128MiB、写≤64MiB、空间≤256MiB。

**正式恢复次序及命令差异。** 开发/定向验证和独立复核后，只reload原orchestrator code location，不启停四sensor或重置cursor。原周已失败子run d7ae3495-bb23-4c33-a4be-d78d2aba2742作为本次parent，strategy=FROM_FAILURE、useParentRunTags=true、extraTags仅增加[{"key":"goldenshare/stock_period_rss_limit_gib","value":"8"}]（value为字符串）；SDK保持原root319、27日配置/30日分区和原业务执行53a8a…4a26be。§12.8“无extraTags”仅对此显式获准资源标签作例外，禁止改run key、日期或任何其他tag。周成功/原交付通过后，对原月parent8c9e09c4-9a82-4042-b696-0ffc3a17999d采用同样8GiB资源tag；再按原通知推进全部Silver。不换CLI、不手工运行补数函数、不重新生成名单/请求ID。

源83页按原版本/身份复用，无copy.json的约145MiB未验build/week由原续跑逻辑清理重建；保留source、manifest、pending及正式成果。原§12.12.2已批历史范围及含一次必要续跑总读32GiB/写24GiB/额外空间48GiB继续覆盖本次恢复，不扩大已批股票、日期或数据集范围，不做重复全局审计；新增开发只用隔离资源。后续仍超8GiB、源日期冲突、真实check/归属失败则再停止报告，不自动继续加额度或重跑。最后按原完整交付清单和版本/原checks收尾，记录实际RSS采样；若末个Raw原生checks后仍留consumed=true的完成待办，沿原events CLI对该实际执行ID仅确认回执/phase/pending（正式原DAGSTER_HOME、原Lake/staging），0源请求/0行情重算，保留原真实检查要求。此为交付收尾，不改用CLI补数。不能把8GiB批准当足够性的实测证明。

#### 12.12.5 月Silver已有恢复子执行的原job操作

两Raw均SUCCESS，原末月events收尾已成功且daily.pending清零；周Silver658周期/1974检查已complete。月Silver原154周期job11f14ad3-3e17-4a08-99ff-1c370b767c00已SUCCESS，但在sensor确认前Raw当月又被后续原月任务合法刷新，形成原恢复流程窗口。sensor已冻结子执行82c6253a-b3ec-513f-8fce-cc8ccacb759e，父6c6bc96d-29c8-562e-8db0-7347caada68b；当前154个unit中153个reuse、仅2026-10需重建，两个参考及全部源/目标版本与子元数据匹配。sensor看到子execution.json后直读尚未生成的files/month/2014-01.json而未提交job；不能重置cursor、手填CP或声称通知完成。

**沿已有办法处理，不改代码。** 现有build的显式resume_from_execution_id分支会确认父子、补复用unit CP，再只重建变化月；原test_frozen_successor_without_local_checkpoints_uses_explicit_parent正覆盖已冻结子但无CP场景，既有实现未变，不再性能测试。使用原silver_stock_monthly_update_job全asset及原三checks，2026-10分区；config.intent=update、execution_id=82c6253a-b3ec-513f-8fce-cc8ccacb759e、resume_from_execution_id=6c6bc96d-29c8-562e-8db0-7347caada68b、source_completion保持子identity中原53a三字段ref。完整GraphQL ExecutionParams保存在原报告rss8-silver-month-recovery-request.json；经原launchRun提交全计划，SDK parent/root记录原成功11f14，不能对SUCCESS父run用FROM_FAILURE，也不使用CLI/build函数直接补数。只增加标准partition tag，无新配置、无8GiB Raw标签、无run key/cursor篡改。

执行前已精确核父hash、154相同unit集合、153复用/唯一10月、参考和源目标版本，证据rss8-silver-month-recovery-preflight.json。此次仍在原三条通知及已批历史预算内：最多新增当月Raw约0.5MiB一次读取、Silver COPY/校验各一次，其他153单位只用原合法成果/控制证明，不做历史重算或新源请求。运行一次，失败/未知归属/真实检查不通过停止，不自动重试。

完成后让原sensor写子events_complete及覆盖父证明、消费原53a月通知，再正常消费后一个5d29月通知。后一条可能复用同一10月成果，但仍由原job/检查和sensor确认，不跳通知。最终验收识别covered_by_execution_id，用子完整证明覆盖父；不要求父旧10月文件仍当前。具体回执和实际运行结果回写原报告。

#### 12.12.6 正式恢复完成及验收（2026-10-28 11:50）

本轮按原27日意图完成四数据集。23日周欠账已补；当前周标签2026-10-30及2026-10月更新至2026-10-27，不把30日/31日坐标当已完成交易日。81股两频源历史刷新及1股确认退市处理均随原job完成，其余股票/日期沿原合并保留。

| 数据集 | 本次覆盖的不同周期文件 | 行数（Raw首批历史/后续当月分列，Silver为最终覆盖） | 结果 |
| --- | ---: | ---: | --- |
| raw_tushare_stk_period_bar_adj_week | 1754 | 3626362 | 原周job及全部交付完成 |
| raw_tushare_stk_period_bar_adj_month | 416；其中10月后续再刷新1次 | 867975；最后当月5576行 | 原月job及原events收尾完成 |
| silver_stock_weekly | 658 | 2519814 | 1974项原检查完整确认 |
| silver_stock_monthly | 154 | 595280 | 462项完整确认；末条10月复用另确认3项 |

Raw为2170个不同文件、2171次提交，差额是同一10月文件再次刷新，不能说2171个不同文件。Silver最终812个不同周期、3115094行，不重复累计恢复父批或当月后续通知。两Raw均events_complete；原415份源证据文件（83成功页对应）与8GiB前版本完全不变，没有重下。冻结policy/identity/hash保持4GiB，本次两个Raw重执行通过运行tag取8GiB，未改变无tag默认；实际RSS采样最大6214270976 B（约5.79GiB），不宣称连续精确峰值。正常实际数据处理和原校验已执行；最终验收脚本的0行情内容读取/0正式修改只描述该脚本，不扩大为整轮0读写。

实际run：周Raw9edc90f7-1822-4abb-af85-7d1cb1a71034；月Raw66b1c247-4c27-4009-9b21-2e5c7755c432；周Silver5263e92d-6ac1-4aa5-9c71-35730f6e0179；原月Silver11f14ad3-3e17-4a08-99ff-1c370b767c00；显式parent恢复月661f50eb-8344-45c4-b801-25b2d8610e21；末月通知Silver2e0e739d-9711-4de6-b9ed-53e1f08dcdc7。全部实际run均SUCCESS；原失败历史run保留，不改写为成功。月父6c由子82的完整证明覆盖，子153复用、只重建10月；末通知eb9复用同一10月，无需再计算。

最终逐实际complete/committed/events及三个原通知核对：集合/行数/版本/保存摘要匹配；两Silver cursor已越过各自全部通知且无pending；四sensor仍RUNNING，未重置。daily.pending=0，factor_through=2026-10-27，两频last_refresh=2026-10-27、last_source_asof=20261027；闭合周2026-10-23/月2026-09，当前周/月保持未终结。没有另做全湖计数、历史行情重读/hash或全局完整性审计。证据以原报告rss8-final-verified.json为准，rss8-final-inventory.json是11:31收尾前的历史快照。

开发对账：tag常量/读取和job限制、runtime透传、精确daily准入分别落三生产文件，测试新29+原89通过；真实SDK隔离接线和真实小producer缓存复用、反向拒绝、超8及复位均覆盖；正式原job补齐证明本次8GiB可完成，范围不外推其他数据集。CodeGraph explore/impact/sync/status、Ruff及文档检查通过；测试临时目录和本次只读脚本清理，正式成果/源及控制回执保留。本轮修改及证据随本次提交保存，提交号以Git记录为准；未推送。

**恢复待执行窗口的历史发现与后续修复：** 月Silver当时先返回silver_recovery_required，按既有规则等待显式parent原job；下一tick却直接确认尚未执行的子任务，改报缺少CP。27日补数已通过原恢复job完成。管理员随后已批准按§12.17修复确认时机并保持明确恢复指引，先完善原方案/LLD，再开发及隔离验证；本条不再是待决定是否开发的TODO，也不新增自动补数要求。

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

以下保留开发提交时的实现和测试记录；提交后独立审计已发现5项遗漏，结论以本文开头的审计补充为准。本节的既有通过项不等于本轮全部要求已完成。

管理员本轮授权：先提交文档，然后严格按方案/LLD完成开发、测试和实现对账；**不执行正式状态修复和补数**。三文档设计基线已提交befd282e0，未推送。生产代码、测试、报告及本节结果回写随后已提交88de377ca，未推送；未加载/重启正式code location、未操作正式job/sensor/cursor/DB/Lake。

**提交时的实现记录。** 三处检查选择均改用实际结果事件排序和双left join，真实失败/晚错绑/非blocking在业务事件补报前拒绝；原清单与当前版本校验分离，原历史事实+明确后继可只补CP/phase/pending；未知当前文件仍拒绝。共享待办按原意图恢复，原生检查保留物化后的真实执行顺序，历史结果不能当当前anchor，日期/分区不符读源前停止。所有既有events/resume/handoff/周线限定补报/Silver消费者均已迁移或核验；原业务字段/选行/源请求/policy/命名和sensor key不变。原生失败用既有FROM_FAILURE，不引入新正式配置/入口。

**性能复核已落地。** 未闭合当前同版确认2文件与100文件均为3条实际SQLite SQL（两频为4），不再逐文件新增查询；真实历史变版才追加有限取证。共享后继/候选JSON各只读一次，缓存版本变化拒绝。ack由平方级stat改为入口/阶段整体核验、逐项相关控制核验；2/100项CP存在/缺失均有线性界测试。首次纯文件完成0确认/重放/通知，恢复分支仍查真实交付。细化点先回写§12.5—12.6/白名单后实现，不改行情计算或新增数据扫描。

**固定生产版本的验证结果：411个去重用例最终通过，0失败/0跳过。** 实际轮次为全组405项（404通过、1条旧CLI末次resume预期失败，102.227秒）；按§12.5纠正该旧预期后，memory模块25项通过（1.123秒）；另补Raw实际job拒绝三例3项通过（3.588秒）、两频缺项及两段合法后继3项通过（2.966秒）。生产代码在全组前已冻结且后续未变化，源文件mtime及hash已记录。没有重跑未变化的404项来堆叠通过数，没有删除原失败/用skip藏失败；旧失败和每个复验XML均保留，最新集合明确为逐用例合并，不冒称一次pytest全绿。

隔离证据包括实际Raw小producer/临时Parquet、完整CLI/localhost HTTP worker/取消/交接/实际Raw job/check，以及Raw→通知→两Silver sensor/job/check；PG18.4实际共享SQL和真实GraphQL/sensor重执行另外验证。PG job为独立最小业务夹具，证明SDK保持原日期/分区/config/root/parent/key且asset只运行一次、子run仅恢复失败check；不将此夹具冒称正式319业务链已执行。容量100项明确为metadata/stat替身测试，实际SQL与失败拒绝真实执行，不等于100份行情审计。

全部A1—D4要求的实现函数、独立正反用例、证据边界及逐项结果见[本轮实现及验收报告](../../reports/dg_stock_period_delivery_recovery_20261028/README.md)；[results.json（附件已清理）](../../reports/dg_stock_period_delivery_recovery_20261028/README.md#report-attachment-cleanup-20261103)保留轮次和固定生产代码指纹。Ruff本次所有Python文件默认规则、src/tests致命错误基线、CodeGraph sync/status、文档/新增链接及diff检查通过；当轮已关闭集合读取、共享清单、线性stat、ack根/设备、日期/分区项；提交后独立审计另发现5项未关闭问题，以本文开头链接的审计结论为准，不再认定无已知阻塞项。

隔离PG均按原datadir停止后删除；本轮临时目录/旧函数稿/已应用补丁按精确路径清理，记录见报告cleanup.json。未安装依赖、未操作正式数据。正式§12.11收尾、§12.12补数及自然运行验收全部保持未执行；下一步先由管理员review本次开发结果。

<a id="period-delivery-recovery-followup-345"></a>

### 12.16 独立审计第1—5项修正设计（2026-10-28）

#### 12.16.1 目标、范围与开工条件

本节将[提交后独立审计](../../reports/dg_stock_period_delivery_recovery_20261028/post_commit_audit.md)第1—5项转成开发约束。第3—5项原细节保留并补充澄清，第1、2项见§12.16.6—12.16.7；锚点沿用原值，避免既有引用失效。先完成全部文档审计，再编码；五项实际结果逐条对账，不能沿用88de377ca原411项通过代替新增边界验收。

字段、21列、源请求/分页、价格、选行、正式路径、锁、检查身份、job/sensor、日期配置及run key不改；不加配置项、CLI动作/参数、运行tag、数据库表、契约版本或另一套持久状态。例外的内部行为调整明确为：取消不可信范围索引触发的自动全频行情扫描；局部回执允许补写，但整批完成含义不变。不得保留新旧两套准入或扫描兜底。

开工前按下列映射核真实消费者。CodeGraph search/impact结合当前源码已确认本轮落点；动态回调以代码为准，无Prod/API/前端迁移。后续若发现新增消费者，先补本表，不绕过共同规则。

| 项 | 生产代码落点（相对orchestrator/src/orchestrator/defs） | 直接验收 |
| --- | --- | --- |
| 1 | bootstrap/stock_period_history.py的run_period缓存恢复、validate_registered_targets；io/stock_period_raw.py的publish及原rename证明复用 | 真实producer在replace后/CP前中断，原入口resume及反例；原publish/checkpoint/memory_resume恢复回归 |
| 2 | bootstrap/stock_period_history.py的历史登记/ordered_pending_work/run_period/replay；stock_period_update.py的daily、history资产、handoff、sensor状态及ack | 真实history登记—缺检查—阻断新写—原ID恢复—确认移除；无manifest/无daily/跨日原scope/交接保留等中断反例；原update、两个Raw sensor、monthly_definitions和memory_resume夹具按真实完整handoff/SDK闭合步骤校准，原业务结果不变 |
| 3 | run_contracts/stock_period_silver.py；stock_period_checks.py；checks/stock_period_silver_checks.py；asset_guards/stock_period_silver_readiness.py；bootstrap/stock_period_silver_cli.py；stock_period_silver.py | Silver合同、events、execution、jobs、daily_integration、recovery/sensors相关场景；审计silver_missing_asof复现 |
| 4 | stock_period_update.py的confirm/ack；bootstrap/stock_period_history.py的replay_events；ops/stock_weekly_bootstrap_checks.py接线核对 | delivery_confirmation/history/daily_delivery/batch_evidence、combined及周线限定op；审计partial_week_history复现 |
| 5 | io/stock_period_raw.py的_old_range_paths/assemble；bootstrap/stock_period_history.py的run_period/validate_registered_targets/_record_ranges | raw、combined、storage、delivery_history及缓存复用场景；审计guard_after_old_read复现；直接history assemble夹具须由真实原publish结果及独立字面范围提供可信证据 |

#### 12.16.2 第3项：Silver物化的日期、范围与版本共同校验

**开发前依据与错误位置（88de377ca）。** 当时正式checks/stock_period_silver_checks.py::evaluate读取silver_asof/lower，缺失即拒绝，再按周一/月首判断目标周期位于范围内；current_validation继续验证实际文件和来源。readiness::require_recoverable_checks的matches却遗漏asof，CLI report_file只比较版本/路径/行数即可沿用物化并追加三项通过。只加一个“asof非空”判断不够：同周/月内错用另一unit的日期、非法范围及同版行数冲突仍会漏过。

**日期来源与内部接口。** 在run_contracts/stock_period_silver.py抽取纯函数validate_materialization_scope(freq, period, asof, lower)，返回已核验的asof/lower；不读文件、查询实例、推导系统今天或修改输入。asof/lower必须是现行YYYY-MM-DD文本且能精确往返为合法日期；缺失、空值、错误类型/格式、lower晚于asof或周期不在允许范围均拒绝。继续复用period_key/period_start：周线将lower/asof归到各自周一，月线归到各自月首，然后比较period_start是否在闭区间内。不能把周五/月末标签直接与asof比较，也不能要求目标周期等于asof所在周期。

lower的来源仍为已核identity/报告，但本域§11.2—11.3的有效合同固定为2014-01-01，不表示报告可随意选择下限。共同scope函数同时核这一原有固定值，正式evaluate、补报和readiness都拒绝2013等其他合法日期；不能只保留readiness原固定门禁、让原生检查继续接受。该项在开发复核时发现原native与recoverable条件不完整一致，现明确收敛到同一已有合同；不更改业务起点、21列或源请求。周线2014首周以周一2013-12-30参与坐标比较仍合法，不能把坐标早于2014误当lower错误。

| 场景 | asof/lower事实来源及相等规则 |
| --- | --- |
| 首次bootstrap | 使用已验证审计报告冻结到identity的asof/lower，不取今天 |
| update当前版本 | 使用该unit/提交记录的asof，lower取所属identity；identity.asof只是整批最大日期，不能覆盖各unit的日期 |
| 已提交父成果/合法继承 | 父提交记录配已核父identity；通过显式来源引用和hash核归属，不用新identity或新整批最大日期验证旧记录 |
| 合法旧前像 | 使用旧物化自身有效的原asof/lower；若已有明确原CP/identity，按原上下文比较。不得要求旧asof等于本次新asof，也不得为找到原上下文扫描历史runs目录 |

materialization_metadata先解析record中明确存在的asof，否则才按现行bootstrap合同使用identity.asof；明确存在却为None/非法的值必须拒绝，不能静默回退。生成元数据、正式evaluate及readiness复用同一scope函数；evaluate保留current_validation和原三个blocking check范围，不能用这个纯函数代替文件/来源验证，也不为补报重算全部行情。

**路径、行数、版本及业务绑定。** 从stock_period_checks.py::verify_period_materialization抽取其纯元数据比较部分，由原带当前stat的包装与Silver readiness共用；旧包装和Raw消费者保留当前语义。纯比较不stat目标，不追溯业务文件，要求asset/partition/URI正确、row_count为非负严格int（bool/float拒绝）；版本保持原五项非负严格int格式，并与明确允许的当前版/原前像一致，不能将一个格式错误的值与自身比较相等便接受。

该共用包装的现有调用方还包括checks/stock_weekly_checks.py、checks/stock_monthly_checks.py以及Silver的resolve_update_sources/update_inputs/recover_update_execution/confirm_update_delivery和update补报；抽取时核对全部消费者，保留test_stock_period_checks.py及两Raw检查的当前反例，不把Silver日期校验加到Raw路径。无需变更的调用方只核验，不为迁移批量改写其他检查。

- 当前版本有已核提交记录时，路径、版本、行数、rule、lower和实际unit.asof必须与该记录及所属identity对应；同版但日期或行数矛盾要报错，不能再发物化修正后补绿。
- update原有source_version、reference_versions及适用Raw完成引用核验继续保留；当前上下文确有这些事实时要按对应记录比较。合法同版复用或继承可能沿用旧execution_id/完成引用，不能把整个metadata字典与新生成字典强行判等。
- §11.3已承认首次bootstrap物化可能缺后加的来源版本字段，仍能据原合同识别旧目标；缺这些后加字段不能自动当成“已与新Raw对齐”。原先首次update正常重建的行为保留。silver_asof/lower等原必要字段不因此可缺。
- 旧前像必须精确等于已核target_preimage/event_preimage，真实成功检查准确绑定且实际结果先于新物化。旧文件已经替换时不能调用带当前stat的verify_period_materialization去核旧版，也不能拿新日期/行数冒充旧事实；晚错绑仍拒绝。

**调用顺序及消费者。** require_checks仅raw=False增加共同scope及纯元数据规则，raw=True不改；require_recoverable_checks使用同一规则区分当前版和合法前像。CLI report_file与report_update_events先校验所属记录/identity和全部本次明确文件的既有证据，再开始任何动态分区/业务物化/check写入；一项矛盾即整组停止。确实缺当前合法事件才沿原回调补缺。新物化读回及写本地成功CP之前再用同一比较核其绑定，禁止修坏元数据后补绿。

首次replay_events未闭合批次中，不能因为本地events CP已存在就跳过共同准入；对本次明确units按频率一次集合预取事件，校验已有CP、当前元数据及真实检查。保留的是现有update已闭合历史快路；bootstrap首次replay没有这份历史状态合同，本项不得擅自新增bootstrap快路。update_inputs和recover_update_execution处理owned记录时须显式传入原identity；confirm_update_delivery使用同一比较替代局部条件。sensor只消费共同确认结果，不另写一套日期规则；SQL检查选择/decoder保持§12.3。

**失败、恢复及成本。** 缺必要日期、日期非法/错unit、范围不符、同版行数矛盾、已存在真实失败或错绑时，0新增业务物化、0新增通过check、0成功CP；保留正式文件、原回执和已有事件，不自动重试、改日期、取系统时间或重算。网络/事件写入中断后沿原ID重新分类证据，只补合法缺项，不覆盖失败。新增纯规则为0 SQL/0 stat/0行情读取/0写入；update继续复用原每频2条集合SQL及原有写后集合重取，首次两频最多4条证据读取SQL，新物化后按实际涉及频率批量重取，不给每CP增加N次fetch。独立单文件report_file仍可做有界读取；事件写入本身SDK SQL不混入恒定读取次数。显式父JSON在现有recovery_evidence调用内各解码/hash一次，控制版本变化仍拒绝；不为本项追全历史。

**独立正反验收，周/月都要覆盖。**

1. 保留审计“当前Mat缺asof但文件/CP正确”的真实小producer样本：补报应拒绝，0新增Mat/check/成功CP，实际原生evaluate也拒绝；不能用mock提前返回绕过共同规则。
2. asof/lower缺失、空、非法格式/类型、颠倒、范围外、同周期内asof不等于该unit；同版行数冲突及bool/float行数均拒绝。多unit最后一项坏时，前面也不能先补业务事件。
3. 周中如2026-10-22对应2026-10-23周标签、月中对应2026-10，以及2014-01-03首周的周一起点早于2014-01-01，均按原范围语义正常通过。2014/2020旧周期配2026的合法asof也必须通过；源end_date≤asof仍由原选行/检查负责。
4. 同批不同unit.asof、原父identity、旧前像较早日期、同版继承旧execution_id/完成引用、旧bootstrap缺后加来源字段均有正常反例；证明不会被新检查误拦。合法旧前像只补本次缺项，晚错绑仍拒绝。
5. 实际首次CLI、update补报、原生job、已有CP恢复和sensor共同收尾均经过同一规则；重复补报无新增事件，SQL次数不随units增加。

#### 12.16.3 第4项：允许频率的历史回执可以补记，整批不得提前完成

**开发前依据与内部结果（88de377ca）。** 当时replay_events只有原phase已events_complete时才接受局部历史返回；files_complete批次又落到旧版必须当前的校验。confirm尾部还将“任一文件历史化”和“其他当前文件缺项”合并为历史缺证。不能只删除一个phase条件。

confirm增加仅存内存的allowed_events_complete。设F为原完整清单实际频率，A为allowed_frequencies与F的交集，A必须非空；错误频率或空交集明确拒绝。仍读取/验证完整原receipt身份/hash，但事件、CP和目标stat只取A。

~~~text
allowed_events_complete = A内每文件原交付证明完整，且A内每频原通知完整
events_complete = allowed_events_complete 且 A覆盖F
~~~

files保持原完整冻结清单；allowed_frequencies明确本次权限。file_evidence、completion_evidence和current_files只含允许频率，不能用空映射或None推断成功。reason按允许范围缺物化/检查/通知返回原缺项原因；允许范围完整时为ok，即使整批events_complete仍为false。replay原“整批false只能是缺项原因”的检查相应调整，不能拒绝这个合法ok。

**逐文件/逐频证明。** 历史文件仍须原Mat的资产/分区/路径/行数/版本/完整completion引用、三项真实blocking通过、明确合法后继链及截点，任一缺证、断链、失败、错绑或未知版本立即停止。当前文件核最新实际结果；合法可补缺项与真实错误分开。每频通知的file_count须等于该频在原完整清单中的全部文件数，引用及真实observation_id准确；不能只按本次已看见几个文件计算。

存在历史文件而该频原通知缺失时，不新发通知冒充历史交付。另一仍当前频率仅缺合法可补通知/检查，不应被概括成历史缺证；按该频事实分别处理。已有单文件CP不能替代未闭合批次的最新真实检查。现有已闭合快路仍只核允许CP/通知，不stat旧行情或查询未允许频率。

**同一replay与ack流程。**

1. replay核原receipt，执行confirm。allowed_events_complete=true时直接交同一ack写允许回执，不再进入require_current_files或事件回调。
2. 允许范围不完整时，逐文件区分：完整历史证明保留；只把仍当前且符合原补缺规则的文件交原回调。历史项不得进入当前版本校验、_AUDITS缓存或任何Mat/check/通知补报。实际错误直接停止。
3. 当前缺项补完后重新confirm；只有允许范围证明完整，才调用同一ack。同一次锁内调用可以复用已核且相关控制版本未变的原历史截点证明/共享JSON，但当前及后继当前Mat/check必须重新取最新；新一次重放不复用上次当前事件状态。不得把historical_only全局标志当成每文件都已完成，也不能因某个当前文件缺项就丢掉其他完整历史证明。
4. confirmed_result不能硬写events_complete=true，必须返回确认中的两个完成字段；completions只含A。historical_only保持原保守约束：存在历史项时整份结果不得作为当前asset anchor；逐文件current_files仅供明确的当前补缺使用。

ack自身接收allowed_events_complete=true结果并重新核原根、设备、锁内控制版本、run/identity/hash、原完整files；file_evidence键必须恰好覆盖A内全部文件，completion_evidence键恰好覆盖A，证明内容必须完整。重新计算A是否覆盖F，核events_complete值与之相符；不能信任调用者伪造true。daily的consumed与因子/刷新事实守卫保持；kind=history的身份/移除采用§12.16.7，局部补CP始终不能删除其待办或推进任何消费。

ack的完整性核验不能只看Mat/check编号为正数。未闭合且目标控制版本仍是原版时，证明必须为当前文件的空successors及None截点；目标已变版时，必须有非空合法successors，before_event_id为正整数且等于首后继的first_materialization_id。原检查须绑定原Mat且发生在该截点前，中间后继的检查/Mat也须按对应截点有序，后继执行不能循环。逐段由原version对到后继committed.target_preimage、后继version，最终对到controls中的目标当前版本；原执行身份、根、设备、完成引用/hash及必需manifest/complete/committed控制均须一致。删链、空截点、错序、错hash/前像或漏控制必须在任何CP写入前拒绝；不能用evidence.get(successors, [])将缺证明变为当前文件。已闭合批的精确cp_source快路保持。

这些核验不新增DG查询或行情读取：复用confirm已经核验并冻结的小JSON摘要/证明；ack确需解码的后继manifest按执行ID缓存一次，单文件committed逐项核，后继complete不按文件重读整份。相关控制版本在使用和写入前继续复核；已闭合快路不stat旧Parquet。容量断言须保留共享清单一次与线性stat，正常单后继、多后继及两频历史不能被严格证明规则误拦。

沿原writer.lock与atomic_json，先逐项补A内缺失events/freq/period.json（原version/sha），再补A内events/completion/freq.json（原notice和真实原ID）。已有CP必须精确相等；通知CP写前核该频所有文件CP的完整内容和版本，不只确认存在。每次写前复核相关控制、目标及后继证明依赖；局部补记完成、返回之前仍做一次整组control_versions复核，不能因为不写phase/pending就省掉最后核验。保持共享清单一次读取与线性stat；冲突不覆盖，中断保留真实已完成CP，不回滚行情。

**局部完成到此即止。** A小于F时不写manifest、不改phase、不改daily或pending，不推进水位/上市集合/baseline，返回allowed_events_complete=true、events_complete=false、pending_removed=false。后续全频events重新核全部频率，不能单凭局部CP判断其余频率完成；只有整批齐备才能沿原步骤更新phase及按kind精确移除可收尾条目。周线限定op继续固定week，不加动作/参数、不代补month。若显式未闭合的主动history此前从未登记，受限入口须先拒绝并指向原resume/全频events登记；本次不新增pending、也不补CP，不能与§12.16.7登记规则互相绕过。已登记history及非主动history的原合法局部场景照常处理。

**失败、续跑及成本。** 任一历史原证据缺失/CP矛盾/控制变化停止；局部CP后中断，下一次同范围重新确认最新事件、核已有CP相等后只补缺项。旧文件版本不再当前本身不构成错误，必须通过原证明及合法后继识别；不能直接取消版本守卫。已齐的局部历史路径0源请求、0行情读取/写入、0新业务Mat/check/通知。一次确认的基础集合查询仍是2条SQL+每允许频率1条通知，单频3条、两频4条；变版文件的有限历史窗口、原检查截点和中间后继取证另计，不把上述数字冒充历史场景SQL总数。历史取证限明确文件/窗口/后继，未允许频率访问为0。

**必须新增的验收。** 原两频files_complete、week合法后继且week CP缺失时，week-only只补week原回执，month CP/事件/文件stat访问为0，phase/pending/行情不变。覆盖允许范围内全历史、全当前及混合；历史完整而当前合法缺项时仅当前补事件，再补允许CP。缺任一原历史检查/通知、错file_count、断链、晚失败及CP冲突拒绝。每个atomic写后中断和重复重放无重复业务事件；局部后全频确认须核month，缺项不能关闭。空交集、伪造允许范围完整但少文件/少通知、伪造整批true均拒绝。已闭合week-only不扫旧文件；2/100允许文件SQL维持常数、stat保持线性。

#### 12.16.4 第5项：先从可信范围记录列出目标，再读旧行情

**开发前依据与必须替换的行为（88de377ca）。** 当时_old_range_paths把hash、目录清单或任一文件版本异常都返回None；assemble随后locate_old_keys对allpaths读旧ts_code/日期，再调用validate_targets。这不能满足§12.6读取前拒绝。原index测试实为缩窄stock_ranges但不更新hash，不能判断只是hash字段坏，继续信任区间会漏掉旧-only记录，自动全频扫描又违反读取边界。因此明确取消自动回退，不把它换名、拆批或挪到守卫内部。

**索引事实与内部选择。** baseline.files、stock_ranges、range_index_version和range_index_hash为唯一已有范围事实。_source_ranges由完整源行生成每股区间，_record_ranges对历史替换更新、日更合并、退市/换码移除，并共同摘要files与stock_ranges。将_old_range_paths改成纯元数据选择，不接allpaths、不glob目录、不stat全部文件；按批次一次读取/核版本与hash，校验类型、频率、周期、唯一路径及区间完整性。区间首尾必须合法且first≤last，每个按周/月步进的周期都须有唯一对应登记，不能只匹配端点/交集或悄悄跳过中间缺失记录。以下旧索引要求仅适用于非bootstrap；bootstrap沿原获准流程与空目标核验生成首份索引，不要求事先存在旧索引，也不因本节获得重新清理或执行授权。

| 本次工作和证据 | 拟执行规则 |
| --- | --- |
| 纯明确周期upsert，无股票历史替换/移除 | 目标来自本次已验证源周期及明确periods；无需旧股票历史区间，只核这些目标。范围索引异常不能借机扫描历史或修复索引 |
| history，或upsert含codes/retired_codes | 索引必须完整有效；以codes∪retired_codes的原区间与baseline.files对应得出旧目标，再与本次源实际周期/明确periods去重合并。即使源已不含旧周期，也不能漏掉需要移除该股旧行的旧-only目标 |
| 选中目标版本不同、已登记文件丢失 | 读取旧行情前由现有归属核验拒绝，不能退回定位SQL |
| 本次明确目标存在未登记文件 | 拒绝；只有未登记且目标确实不存在才是新文件 |
| 未选文件物理版本变化或未选范围未知路径 | 不glob、不stat、不读、不写这些路径，不因此扩大当前工作；不得声称已完成全湖一致性审计 |
| 历史范围所需索引缺版本/hash、hash失配或结构不完整 | 明确停止，报告无法证明完整历史范围；0旧行情SQL/0 COPY。不用现存坏区间、新源最早日期或文件名猜范围，不自动重建索引/重新加可信标志 |

新上市无旧区间的正常路径不能被误拦：索引整体有效、新码不在baseline.listed且该频没有其旧区间时，可按原完整索引生产合同认定该新码无旧历史；有旧别名则必须先通过现行换码确认，并独立把旧码纳入superseded_codes处理原区间。run_period现已将superseded并入传给assemble的retired_codes，必须保留。原已登记上市代码却缺该频区间，不能当成新上市；bootstrap每股每频真实空源会拒绝，此时现合同不足以证明无旧数据，停止报告。

**新生成与缓存的顺序。** 没有可复用copy/candidates时，先用上述元数据及本次源关系确定selected，捕获这些目标版本，调用同一validate_registered_targets；通过后才执行原read_affected_once、合并、单次COPY和候选完整校验。locate_old_keys全频回退从这条生产路径删除；不保留备用函数调用或任意旧目录发现。

copy.json或频率candidates命中时，不重新定位旧行情，按已冻结identity、periods、target_preimages及候选摘要核验；若候选已移动而提交CP缺失，先按§12.16.6严格恢复原CP，再经同一目标归属守卫复用，不能另设未知版本放行规则。旧已完成文件/历史交付确认不需要规划旧行，本项索引准入不能插到§12.5历史元数据确认之前，导致旧20收尾要求额外行情或索引恢复。

_record_ranges的非bootstrap更新在已有有效索引下维护实际已交付范围及版本，未选记录保持原登记事实，不将其当前物理版本当成已核。纯period工作不依赖股票旧区间且索引已失效时，允许按原合同完成该明确周期并记录其文件，但索引必须保持不可用，不能重新添加range_index_version或重算hash来“证明”被篡改内容；以后需要股票历史范围仍须拒绝。既有bootstrap首次建立完整索引的生产合同不变，不在本轮重新执行。索引本身需要恢复时另核来源、范围、必要读取及执行授权；需要该索引的日常/历史补数调用保留已完成源页/候选/回执并停止，不用全频扫描自动修复。

**失败、中断及成本。** 归属/索引错误发生在旧行情读取和COPY前；正常进程取消保留原冻结文件，从同一ID复用成功源单元及缓存，不能再次全频定位。baseline JSON及摘要每批常数次，内存处理与其现有元数据条目数成正比；物理stat只与本次明确目标数成正比。目录枚举、全湖stat及locate_old_keys均为0。需要合并的旧行情大小仅为本次明确文件大小之和；使用既有一次合并/候选校验预算，不引入附加全量审计。范围或实际历史读取超出原授权时，在执行前按§12.10另核并获准，本节不是历史读取批准。

**必须新增/校正的验收。** 保留原index缩窄/hash失配样本，预期改为读取前拒绝，断言locate_old_keys/read_affected_once/partition_copy均为0、旧文件/baseline/hash/可信标志不变；不能删样本或把hash重算到通过。file漂移分支也断言上述三个阶段为0。有效索引正常更新、源中消失的旧-only周期清理、新上市空旧范围、换码旧区间移除、选中版本变化/登记缺失、未知选中目标、未选文件变化不误拦、copy/candidates复用均有独立结果。另验原bootstrap正常建立首份索引；纯period在索引异常下仅提交明确周期，文件登记更新后下一次任务仍能识别其归属，索引保持无效；区间缺中间周期/重复登记必须拒绝。目标列表只来自可信元数据/明确源周期；用少量选中目标和大量未选元数据、路径哨兵证明无全湖glob/stat、无守卫前旧行情SQL，只汇总本次选中文件大小。正例保持原Decimal、NULL、未选股/分区和全部21列断言，不用待测selector生成expected。

#### 12.16.5 统一预算、实施顺序与验收结论

文档审计阶段不运行业务或测试。通过后依次落实1/2恢复及登记、3共同准入、4允许范围确认、5读取前目标选择，互不重叠部分可并行；迁移全部消费者、补直接正反例，再做固定版本一次必要回归与实现对账。不能只改最初发现问题的一个入口。若需扩大范围或改变原日期/源/持久合同，先回本节说明，不现场编码兜底。

| 阶段 | 正常一次 | 一次中断续跑及最终验收 |
| --- | --- | --- |
| 第1项rename后恢复 | 仅缺CP且候选已移动的明确目标摘要读取1次，大小记B；补1份原CP，0源/0 COPY/0新replace；常规CP已存在为0摘要读取 | 一次恢复又在CP前中断时，下一次仍需最多再读B，合计≤2B；最后只核CP/版本。异常多缺CP不自动扩成全批hash；正式B须纳入当次已批准预算 |
| 第2项历史登记 | 同一daily.json内增加/复用1条原scope历史工作，manifest前先落登记；共享待办按元数据排序，0历史行情读取 | 登记后/manifest后/文件后中断均复用原记录和原source/candidates，结束核原JSON及事件；不扫runs，不重复源请求/已完成文件，不改其他工作/水位 |
| 第3项新增校验 | 纯scope/元数据比较0 SQL/0行情读取/0 COPY；消费既有集合结果和显式父JSON，不加逐文件查库；合法补缺沿原≤N物化/3N检查，坏证据为0新增业务事件 | 同ID重新取当前集合、复核必要小JSON及相关版本，补实际缺项；原已闭合历史快路不扫旧数据；不重复原文件计算 |
| 第4项证据已齐的允许范围补CP | 1次确认：基础集合为两条SQL+每允许频率1次通知，明确历史窗口/截点/中间后继查询另计；共享清单各读一次，写CP≤允许文件数+允许频率数，0新业务事件 | 成功、一次中断续跑和最终核验合计至多3次确认；若当前合法缺项需要原补报，正常及续跑各按补前/补后确认、最终1次，合计至多5次。3/5是确认调用次数，非SQL总数；另列每轮历史取证及原回调的实际缺项事件/查询，不按频率重复给预算 |
| 第5项合并 | 索引无效或未知目标时0旧行情SQL/0 COPY；有效时只核/合并明确目标，删除原全频定位读取 | 缓存命中不再定位/读旧文件；未完成目标按原作业预算读/写，最后只核本次交付清单；超范围先重新核定 |
| 后续隔离验收 | 沿§12.10 ≤3股、2频、≤8个小周期文件/场景；≤12个run/顺序恢复小场景；预计读≤256MiB、写≤128MiB、空间≤512MiB | 含故障注入与续跑合计读≤512MiB、写≤256MiB、空间≤1GiB；2/100容量用metadata/stat替身，不拿真实历史行情做性能实验 |

正式旧20收尾仍只可沿§12.11已有精确元数据预算与原events动作，不读取后继2057份行情；真正补数仍按实际变更清单另核历史范围。本次不新增程序限额、配置或正式操作授权。测试使用既有.venv/bin/python3 -B及隔离根，不设PYTHONPATH、不安装依赖；临时资源结束清理，失败则保留小证据并停止，不自动重复全套回归。

交付必须分别列第1—5项“要求—代码—正常例—反例—实际入口—SQL/文件计数—通过或未完成”。历史411项和审计10项通过不能替代新增组合验收。本节编制完成不等于实现完成；开发/隔离结果另按实际回写，正式执行始终不包含在本轮。

#### 12.16.6 第1项：rename已成功而committed回执缺失的原ID恢复

开发前88de377ca的run_period缓存candidates分支先执行validate_registered_targets，候选已原子替换为目标但committed JSON尚未写成时，目标不等于旧baseline且无CP，被错误判为未知；原publish本可按候选身份和摘要恢复，却到不了该分支。

只在原writer锁、根/设备、原identity/hash和该频candidate_hash全部已核且旧待办守卫通过后，处理本执行缓存中**CP缺失、候选路径确实不存在、目标存在**的文件。核唯一freq/period/target/candidate路径、冻结target_preimage及候选版本/摘要；再调用原publish的rename后恢复分支：目标dev/inode/size/mtime须等于原候选前四项，真实sha256等于原候选摘要，允许rename改变ctime。证明通过仅fsync/补原committed回执；不重新下载、生成候选、COPY或os.replace目标，不更改manifest.identity/identity_hash、候选清单及hash、原complete/hash。

补CP后仍执行同一validate_registered_targets；后续原publish沿CP快路复用，不第二次读摘要/重写。候选仍在、目标不符、缺冻结前像、摘要/路径/身份/设备冲突均不得借恢复放行。不得仅因候选消失就把现存目标认领成本次成果。正常逐文件CP下单次中断最多留下一个这种间隙；若发现不符合该序列的多项异常，停止报告而非批量重hash。

预算为明确目标字节B的一次摘要读取，加小JSON写入；重试前又中断需再读B，正常+一次续跑≤2B，最后以版本/CP读回，不再hash。旧20 files_complete历史确认无需此分支，0行情读取承诺不变。正式目标B超出已有获准范围时先重新核定，本节开发授权不替代正式历史读取批准。

隔离验收从真实producer/run_period注入**os.replace成功之后、committed atomic_json之前**的失败；恢复同请求不重复源请求/COPY/replace，最多1次摘要读取，价格/行数/版本不变且CP准确补成。另测候选被删除但目标不匹配、同大小坏内容、前像/路径/hash/设备错误拒绝，CP写后中断及已有CP恢复为0摘要读取，所有新守卫仍能拒绝真正未知目标。必须通过原协调入口，不只直接测试publish。

#### 12.16.7 第2项：主动history进入同一待办，任何新写不得越过

**持久位置与类型。** 继续使用staging/stock_period/daily.json的pending_work，以原execution_id为键；正式主动history入口构造的是无asof的history意图，使用内部kind=history标记，保留原intent、policy、listed、aliases、root、identity_hash、confirmed_retired、devices及started_at，足够重建并核对原manifest身份。identity_hash仍严格为digest({intent,policy,root,listed,aliases})；kind、confirmed_retired、devices和started_at不加入原业务identity/hash，独立核对。没有新增文件/状态实体或运营参数。原daily work形状及consumed含义不变；已有daily条目优先复用，mode=history且有asof的daily工作不能登记为kind=history或借显式resume绕过消费守卫。kind=history不使用/伪造consumed，不能调用_consume_daily_files或推进任何daily水位。

**登记早于任何请求和业务写入。** 以run_period的writer锁为唯一写者，新history先确认更早待办，再冻结当前history原身份/开始时间并atomic写入pending_work，然后创建manifest；manifest.started_at必须沿用登记值。登记写失败不得下载/COPY，登记后manifest前中断则条目仍可识别/排序，原请求续跑沿同时间创建manifest。存在原manifest但漏登记的显式resume/全频events，只按该精确ID/冻结身份和原started_at补登记，再按共同顺序核更早工作，不能把实际更晚的条目当成更早而反向阻断原恢复。哈希、根、scope、policy、设备或开始时间矛盾拒绝，不扫描runs目录发现旧任务。已闭合且原回执完整的history重复确认不重新登记，不将完成历史变成新待办。

该先后次序也覆盖run_period的files_complete早返回：即使只是恢复ranges_recorded/原范围登记，也须先补原history待办，再进行这些控制写入，不能等到最后replay才登记。须注入files_complete已落盘、ranges_recorded尚未写成时的失败，验证待办仍保留且原ID不重下/不重写行情；不能只测download阶段漏登记。

内部共同入口固定为history.ensure_history_pending(run, *, root, staging, saved=None, identity=None, confirmed_retired=(), allowed_frequencies=None, cancel=...)，返回已核原history工作或None；history_work_identity(work)只还原原五字段身份。run_period在manifest前传identity，replay传指定manifest的saved，不各自实现登记。replay增加仅内部使用的allowed_frequencies，weekly op显式传week，必须与确认回调范围一致；没有新CLI/运营参数。是否局部以允许范围是否覆盖该交付全部频率判定：已完成receipt可核时取其实际files频率，否则取冻结intent频率；原意图/交付本来仅week且允许week完整覆盖不算局部。局部缺登记必须在第一次confirm/写CP之前拒绝；完整范围可按本节补登记。已有daily条目要核原身份，不得仅比较intent便当成主动history。

daily.json尚不存在时允许仅建立真实pending_work，不伪造baseline_run_id、factor_through、completed_through或last_refresh。普通daily执行及其sensor须识别handoff字段尚不完整，按现有未交接原因明确停止/跳过，不能KeyError、初始化假水位或规划源请求。handoff在calendar/factor扫描或新子意图之前先处理旧待办；已有冻结子ID只能恢复该子本身，不借父bootstrap ID跳过旧history。handoff最终写daily前读最新状态、保留所有pending_work，不以baseline_run_id一致为条件覆盖它们。

**恢复与所有入口。** 同请求history续跑使用已登记条目及原manifest的冻结scope/policy/root；真实SDK history资产在load_scope今天信息之前按精确request_id查原条目/manifest，核配置codes及意图一致后复用原listed/aliases，不能因跨日上市集合变化换身份。首次history仍按原方式load_scope，CLI resume沿原冻结身份；全频events对显式未闭合history同样登记，只做其已有事件/确认步骤。周线限定等受限入口不得补登记未登记的主动history；须先明确要求原resume/全频events登记，本次保持daily/pending/CP不变。这样不以局部确认绕过登记，也不以登记扩大受限动作权限。

ordered_pending_work按原asof/冻结started_at顺序，manifest存在时核登记时间一致；不同daily/history、CLI和handoff新意图均先经过同一守卫。daily.perform看到kind=history只能：文件和全部真实交付已齐则调用共同ack；否则在新因子扫描/源请求/COPY前明确要求恢复原history，不能代做其文件、返回旧anchor或进入daily消费。原history自身仍可复用原源单元/候选/提交文件，文件完成后返回实际anchor等待真实原生检查；检查/通知未齐，待办继续保留。事件补报不能把真实失败刷绿。

**整批收尾。** ack必须按kind核对原冻结身份、原清单/hash和最新pending；kind=history只有整批events_complete=true且覆盖全部原频率时才删除该精确条目，不要求也不修改consumed。daily分支继续要求consumed=true及原因子/刷新消费事实。两者局部确认均不能移除pending；其它条目、所有水位和baseline均不变。删除前重读最新daily防旧副本覆盖，新条目/控制变化停止；CP/phase成功而pending未移除时可原ID幂等补最后一步。

代码只保证进入本次共同入口的显式工作被登记，不承诺自动发现历史上从未登记的任意旧history。部署/正式修复前沿原有限run及精确引用核有无这类在途任务；若有，先明确原ID通过既有resume/events处理，不扫runs、不删pending或重做全历史。本轮不实施这一步。

**必须验收。** 真实history执行产生真实小文件和SDK物化、故意保留检查未完；第二条不同history及daily/handoff必须0新源/0因子扫描/0 COPY，原文件不变。补齐原真实检查后原ID确认/ack移除，再新意图能正常通过；同请求跨日仍用原scope，配置改codes/根/hash等拒绝。覆盖登记前失败、登记后manifest前、源页后、replace/CP后、files_complete后和phase后pending前各中断；重复登记相同不增条目、不重置时间，冲突不覆盖。无daily时最小登记不造水位，daily/sensor明确未交接，handoff保留旧pending；局部week完成不删除两频history。已有闭合history重复events不重登记。所有样本来自当前producer/合同，不能只手造queue证明排序器可用。

#### 12.16.8 开发前五项文档独立审计

本轮先由三个相互分工的只读审查核对总方案§10.8、共享LLD§12.16及月线§9.4，结合CodeGraph status/impact和实际入口/消费者；正式检查平台依据复用安装版1.13.26并查Context7官方checks文档。发现并在编码前消除三处交叉歧义：主动history与daily的history模式不可混同；漏登记原manifest按原开始时间恢复；未登记主动history不能由受限week-only动作写pending，须先原resume/全频events。另统一history不要求consumed、原identity/hash不变和每频集合查询预算。原3—5项反例及新1/2真实入口反例均列明，未发现仍需另行拍板的设计分歧。文档检查通过后才开始编码；该记录不代表实现/测试通过，正式操作未执行。

<a id="period-delivery-recovery-followup-implementation"></a>

#### 12.16.9 五项开发、独立复核及隔离验收结果

2026-10-28，dev-interface、开发基线88de377ca。第1—5项已落实，当前代码/测试与本节要求对账见[五项修复报告](../../reports/dg_stock_period_delivery_recovery_20261028/followup_1_5.md)。最终固定版本回归单次530项，**528通过、0失败，2项既有PG opt-in未启用**，136.39秒；10份生产代码、15份直接修改/新增测试运行前后SHA一致，见[指纹和总结果（附件已清理）](../../reports/dg_stock_period_delivery_recovery_20261028/README.md#report-attachment-cleanup-20261103)及[最终XML（附件已清理）](../../reports/dg_stock_period_delivery_recovery_20261028/README.md#report-attachment-cleanup-20261103)。未将多个重叠定向轮次相加为通过数。

| 项 | 已落实现及验收 |
| --- | --- |
| 1 | run_period缓存先按原publish证明恢复唯一rename间隙，再核共同归属；真实中断、原ID恢复、1次摘要/0重复源或COPY、坏版本与多异常间隙拒绝通过 |
| 2 | 原daily.pending_work登记/冻结/排序与SDK scope恢复，daily/history/handoff/CLI共用；真实原生job、无manifest/无daily/范围登记及phase/pending中断均通过，history无consumed、不推进水位 |
| 3 | 共同scope和纯metadata规则迁移原生checks、readiness、首次/update/父成果/继承；两频坏日期/行数/版本0新增业务事件，合法周中/月中/2014首周及旧bootstrap首更均通过 |
| 4 | confirm/replay/ack分开允许范围与整批；真实周线op、混合当前/历史、中断、伪造/漂移及合法多后继通过；局部不动month或phase/pending，历史proof逐段内容与截点必须完整 |
| 5 | 可信范围元数据列明确目标并在旧行读取前核归属；无自动全频定位。坏索引/未知目标0旧行情SQL/COPY，旧-only/新上市/换码/未选股及缓存恢复通过 |

第一次固定回归505过/13失败/2跳过的原XML保留。13例旧夹具缺真实交接或范围输入，按独立字面事实、真实SDK确认和handoff补齐，原价格/行数/错误拒绝不改，定向13过；第4项proof漏内容校验先有7个真实失败反例，补修后均拒绝，未隐藏失败。第3项开发前两红例只有原工具输出、未生成XML，原独立审计脚本/JSON继续留证；不补造历史记录。原411项及PG证据仍归§12.15历史，SQL/SDK重执行接口未改，本轮没有重跑PG实验。

开发后的独立审查补齐files_complete/ranges_recorded窗口的登记顺序和ack证明完整性，明确回写本节后实施；再复核未见五项仍待处理或待拍板的问题。全文旧扫描回退、局部频率、最新检查、history状态表、每频SQL及sensor历史状态表述已同步，不仅依靠“新节覆盖旧节”。CodeGraph sync/status、全src/tests致命Ruff、本次25文件默认Ruff、文档/链接与差异检查通过。

读取/写入与原预算对账见报告：新增元数据准入0行情读；历史ack不新增DG查询，真实两频共享后继manifest读1次、complete读0次、committed各1次；2/100容量仍为明确metadata/stat样本，不能冒称全市场行情审计。指定临时Lake/staging/SQLite/工作文件已删除，小型失败及验证证据保留，见[清理记录（附件已清理）](../../reports/dg_stock_period_delivery_recovery_20261028/README.md#report-attachment-cleanup-20261103)。

本轮修复、测试及文档证据随本次提交保存，提交号以Git记录为准；未推送、未部署/加载定义、未访问正式行情/Tushare/Prod、未执行正式状态修复/补数/sensor或cursor操作。§12.11—12.12正式步骤保持未执行；本节隔离通过不代替其授权、精确预核和实际数据范围批准。

<a id="period-receipt-path-followup"></a>

#### 12.16.10 正式执行前补齐清单路径比较的读取边界

2026-10-28管理员已要求按§12.11—12.12顺序正式推进。§12.16.9及原528通过保留为提交005f21f53的历史开发结果；下面是执行前发现、属于原第4/5项边界的遗漏，不改变原读取口径。完成本项隔离修正前不得运行正式events。

**代码依据与影响面。** completed_receipt验证原完整清单时逐项调用raw.target_path；后者经dataset_root/safe_path，对文件及每个父组件lstat。这不是行情内容读取，但会访问后继全部2057项当前路径；未允许频率或已闭合旧目标后来变成symlink也会在历史确认前误拦。原只计file_version/Path.stat的容量断言没有覆盖lstat，撤回“这些测试已证明未选路径零访问”的过宽结论。CodeGraph query/impact核到completed_files、run_period、ensure_history_pending、replay、daily.perform、successors、confirm/ack及当前anchor；实际读写的safe_path消费者须保持原守卫，无Prod/API/前端合同变化。

**最小实现。** 仅修改io/stock_period_raw.py及bootstrap/stock_period_history.py，测试集中test_stock_period_receipt_paths.py并运行原receipt/history/partial/storage/raw相关回归。不加参数、配置、状态、CLI动作或另写恢复入口。将dataset_root/target_path内部的固定路径组成收敛成纯内部函数，路径组成只检查绝对路径、无父级跳转、频率/周期语法，再按现有raw/tushare、频率目录、分区和文件名生成Path；不能依赖文件是否存在，不调用safe_path、resolve、stat/lstat/open或glob。对外原dataset_root/target_path仍在使用前执行原safe_path，全部实际读取、写入、file_version、publish和当前目标守卫不减弱。completed_receipt只用该纯路径组成核字符串等值、原字段/版本/hash和去重，不能因冻结清单中的某个未选路径今天已改变而失败。

**失败与恢复。** 根/频率/周期、目标路径或字段/hash矛盾仍在使用清单前拒绝；只有路径存在性/symlink现状不再由历史清单遍历判断。实际选中目标及全部真实文件读写仍拒绝symlink/未知当前版本。无任何正式数据迁移，不改旧回执、identity/hash、complete或候选。正式动作失败仍按§12.11原命令停止/显式续跑，不自动重跑、不越过旧待办。

**预算与验收。** 本项只读源码和隔离小文件，不读正式资源；新纯路径比较0文件系统访问。2/100项容量使用清楚声明的清单metadata，Path.lstat/Path.stat/resolve/open/glob哨兵覆盖历史目标和未允许频率；真实producer、完整字段/hash保持，expected目标使用独立字面路径。必须先保留修复前反例，再验：历史清单即使对应文件已不存在/换版或未选路径是symlink仍可核其原语义；错路径/穿越/字段/hash继续拒绝；实际选中目标target_path/file_version/read/publish照常拒绝symlink，不能全局关闭守卫。实际两频受限replay/已闭合快路保持0未选Parquet stat/lstat，confirm内后继manifest/complete各解码一次，ack按§12.16.3再读一次小manifest证明；开放局部replay合计manifest=2、complete=1，closed均为0，正式指定目标仍只核必要版本。每场景≤3股、2频、≤8实际小文件，预计读≤32MiB、写≤16MiB、空间≤128MiB，含一次故障续跑及最终验收读≤64MiB、写≤32MiB、空间≤256MiB；容量清单不创建真实百份行情。修正/定向测试及独立复核通过后再沿原CLI推进，不重复528项全组或正式全局审计。

本次正式范围仍为旧20原events、后续原27日任务及其Silver；该执行授权不代替未来具体历史全局读取范围的单独批准。CLI直接加载本工作区已验源码；原生job须确认其实际code location/进程使用同一版本，不能为此顺带发布其他脏文件。操作命令、当前前置、读写范围、失败/续跑和结果继续记入原报告及本节，未执行项不得预填成功。

**本项开发结果：** 两份源码最小修正及新路径测试已完成，开发后独立复核无阻塞。修复前2/100项metadata两反例均在raw父目录lstat哨兵失败；修复后新21例及必要既有91例分别通过（3.110秒、21.122秒），Ruff/diff通过，指定测试临时目录已删除；未重复528项全组。证据及冻结源码SHA见[路径修正结果（附件已清理）](../../reports/dg_stock_period_delivery_recovery_20261028/README.md#report-attachment-cleanup-20261103)。该开发记录尚不代表正式events已执行；实际操作沿§12.11继续。


<a id="period-silver-recovery-progress-lld"></a>

### 12.17 周/月Silver恢复任务的完成判断与指引修复

#### 12.17.1 目标、依据与范围

对应总方案§10.9、月线LLD§9.5。管理员已批准先完善本节、审计一致性，再开发和隔离测试；§12.12.6已完成补数保持原状，本轮不部署/重载正式code location或执行正式definitions验证，不操作正式Lake、instance、job、sensor或cursor。

修复前evaluate_update_sensor仅因execution.json存在就调用confirm_update_delivery，后者直读逐期CP；recover_update_execution冻结新子任务并不代表子任务已执行。真实build最后生成complete.json，含run_id、week/month totals和已有统计，没有identity_hash/status；events_complete.json才是交付证明。原run_key返回父run，父SUCCESS不能证明child完成，父FAILURE也不能永久遮挡已完成child。

唯一生产修改为src/orchestrator/defs/stock_period_silver.py，消费者限原两Silver sensor和confirm调用。新增测试独占tests/test_stock_period_silver_sensor_recovery.py；现有tests/test_stock_period_silver_daily_integration.py的test_completion_source_drift_does_not_save_success仅同步提示断言：silver_event_file_changed仍为错误前缀，后附files_complete=true、当前execution_id及可解析原job run_config；业务拒绝、无完成记录、pending保留继续独立断言，不改业务预期。其他原sensors/execution/daily_integration/events/jobs相关测试保持并回归。既有load_execution对身份/hash、父链及范围的校验继续生效。不改asset/job定义、下载、业务SQL、Parquet、检查名、配置/tag、cursor字段或schema_version，不新增自动补数。

#### 12.17.2 文件处理进度及直接确认前提

新增update_delivery_progress(staging, execution)，返回{'files':len(units),'committed':count,'files_complete':bool}。只读当前execution的complete、明确units对应CP、reference及committed目标的版本/stat，不读行情、不连DuckDB、不扫描目录。不得调用owned_update_records给未运行child补reuse CP或恢复rename；既有恢复job继续负责实际执行。

扫描全部已有CP并调用原validate_record，不能因首期缺失就提前跳过后期坏记录；reference变化、committed目标版本不符、身份/CP损坏始终拒绝。无complete时，CP全部缺失、部分validated/committed或全部committed均返回files_complete=false；最后一种可能是最后汇总写入失败，仍由原job续跑补汇总。

有complete则必须是合法对象、run_id等于当前执行，每期CP存在且committed，week/month两组totals的files/rows均与全部CP独立汇总一致；值为非负整数且不接受bool，未参与频率也须0。缺CP、非committed、坏JSON/汇总/身份/版本明确异常，不能当普通等待。不要求真实生产者没有的identity_hash/status，不改已存summary或CP，不删除异常证据。

helper和confirm内部共用现有read_recovery_evidence，在已有recovery_evidence上下文内同版本CP/complete内容实际只读一次，重复访问仍stat核版本；缓存不跨tick或跨版本。confirm内部同样要求files_complete，不能只依赖sensor调用方。未完成不写events、events_complete或祖先覆盖证明，不替job补执行记录。

#### 12.17.3 sensor顺序与提示

1. 保留根校验、周/月active共用互斥、原已闭合批次优先ack；closed仍按原证明，不要求旧输出今天仍是旧版。
2. 加载pending实际execution并核source_completion，先核Raw版本。已有execution统一进入进度或承接判断，不因原run_key的FAILURE/CANCELED提前返回；旧失败只在pending仍为original时作为恢复提示前缀。原ID与child都依据当前文件和检查事实，不借旧SUCCESS放行或被旧FAILURE/CANCELED永远遮挡。不新增无界run查询。原失败原ID的补修详见§12.18。
3. 来源再变沿现有recover_update_execution冻结后继、更新pending.execution_id，保持原范围和父链，返回明确恢复指引；这是既有承接路径，其CP正常化、footer及集合查询成本按§12.17.5如实保留。来源不变绝不调用recover_update_execution、owned_update_records或recover_committed，直接只读update_delivery_progress；未完成不查batch_event_evidence、不confirm、不ack，不补CP或恢复rename。
4. 文件完成后才按原2条集合SQL取batch_event_evidence并confirm。缺检查/FAILED/错绑/日期或版本矛盾沿原异常拒绝，可附hint但保留原错误前缀，不能改成普通等待，不补绿。
5. 原完成回执及record_update_coverage全部保存成功后才推进cursor；写失败保留pending，下一tick仅依据原文件和真实检查重试收尾，0计算。来源又变仍须走原承接规则。

新增update_recovery_message(execution, progress)，固定格式silver_recovery_required:<id>;files_committed=N/M;files_complete=<true|false>;job=<asset>_update_job;partition=<lastperiod>;run_config=<紧凑JSON>。files_complete使用当前progress实际值；等待为false，文件完整但原检查异常附hint时为true，不能显示与实际相反的进度。配置为ops.<asset>.config中的intent=update、当前execution_id、source_completion，identity存在resume_from_execution_id时原样附入；partition取当前units末期。两频分别用原asset/job，不按今天或新股票名单重建范围，不用execution_id/时间戳另造run_key。首次冻结后继与后续未执行tick给同一格式；只在真实错误附hint时保留错误在前。

完整配置放SkipReason；cursor维持原pending固定字段与decision/evaluated_at，不加逐期清单。连续tick未执行/部分完成保持同恢复ID及父关系，不自动生成新恢复请求。失败/中断沿原job明确恢复，所有异常保留已提交数据/回执，不回滚、不自动重跑。

#### 12.17.4 硬口径、实现与正反验证

| 硬口径 | 代码位置 | 必须覆盖的证据（周/月各自验证） |
| --- | --- | --- |
| 方案不等于完成 | progress与sensor前置分支 | 父SUCCESS、冻结child无CP连续tick稳定提示，0confirm/ack/RunRequest；旧实现复现缺CP错误 |
| 未完成不掩盖损坏 | progress全CP扫描及原validate_record | 缺首CP但坏后CP仍拒绝；部分validated/committed、全committed无summary可续跑；reference/target变化拒绝 |
| 汇总按真实合同 | progress complete/totals | 真实build生成小summary通过；错run、缺CP、非committed、错files/rows、bool及坏JSON拒绝 |
| 当前execution独立判断 | sensor统一execution路径及旧run_key提示条件 | 父FAILURE不挡已完成child，父SUCCESS不使未执行child完成；原失败原ID未完成时提示复核、完成后按真实检查确认，补修正反例见§12.18 |
| 原检查和交付不缩水 | confirm与batch_event_evidence | 缺/失败/错绑拒绝；正常恢复确认祖先并继续下一通知；回执写失败后只收尾 |
| 恢复不由sensor代做 | progress/message及原恢复路径 | 来源未变等待0CP/summary/业务/事件写，不进入recover；来源再变沿原承接保持父链和范围，不自动重跑，既有成本不能称零 |
| 缓存只在同tick同版本 | read_recovery_evidence上下文 | 来源未变的progress+confirm同CP/complete内容解码一次，版本变化拒绝，下一tick重新读取；不据此声称原recover全链单次解码 |
| 成本及消费者边界不变 | 两sensor及原成本门禁 | 1通知/最多1请求、最多2次get_runs；来源未变未完成0集合SQL、完成最多2条，原来源变化成本另列；658周/154月metadata容量，不逐期查询DG |

使用现有真实producer生成临时小Parquet，独立断言日期/类型/行数/关键值；HTTP使用已有替身，不声称真实源验收。沿现有小fixture每频约3周期，具体以case实际范围，合法Raw新版触发child后再检连续tick和原恢复。SQLite存储验证实际物化/检查绑定。坏输入明确作为反例，不改夹具去迎合错误实现；不使用正式资源。

#### 12.17.5 预算、续跑、验收和完成条件

新增0源请求、0业务计算/COPY、0新增DG业务事件、0目录扫描。每tick最多1通知/1请求，active及run-key合计最多2次get_runs。来源未变的进度等待为0集合readiness SQL、0行情内容读写、0CP/summary补写；完成仍最多原2条集合SQL。该路径metadata复杂度O(N+父链)，不把154/658当永久程序上限；同tick每CP/complete实际JSON只读一次并stat复核，父链沿既有缓存校验。

来源已变时明确沿用原recover，不在本轮重写：resolve_update_sources每代会执行2条集合SQL，已有末代再次进入recover还会执行2条；owned_update_records可能补reuse CP、正常化已rename记录，相关验证可能读取已rename文件footer。以上是原承接流程的既有成本，不是新增全局审计或源请求；上轮笼统“未完成0readiness/0行情读取/每CP单次解码”的结论不能覆盖此流程。本轮只纠正来源未变时误入该流程，不能宣称已将来源变化恢复改成零写或零读取。

正常tick、一次中断后下一tick及最后验收分别按同一明确范围计算，不因失败自动重读行情。658周/154月容量仅metadata与占位target stat，不冒称有效Parquet；真实producer小fixture承担数据链路验证。每case沿现有小fixture每频约3周期，具体以case实际范围，行情文件数MiB以内；新增场景及必要相关回归全轮，含故障续跑/最后验收，临时空间估算≤1GiB，实际stat汇总后记录；不能用小行情大小冒充SQLite/日志总IO，也不新增运行限额/配置。测试后仅删除本轮精确临时目录，保留小结果摘要，不清正式staging或共享环境。

先完成三文档审计再编码，固定实现后跑新正反例及原定向回归、Ruff和文档检查；独立逐项对账上述硬口径/代码/测试，记录数量、查询/读取断言及临时清理。上述为开发前确定的验收步骤，实际完成结果见§12.17.6。隔离通过不代表已部署或正式调度验收，本轮不开展正式操作。


#### 12.17.6 上轮开发、隔离验收与实现对账（2026-10-28，历史）

**覆盖结论更正：** 以下281项普通case及518个subtest的真实通过、指纹、初轮失败和清理记录均保留。随后独立审计发现未覆盖“原ID、旧失败/取消run_key、Raw未变”，因此撤回“全部硬口径已对账、该问题已全部收尾”的结论。父失败/child完成的通过不能证明原ID人工完成后可以确认；所测child等待的零补写/零SQL与单次解码也不能外推至旧原ID失败分支或来源变化recover。补修范围及开发前约束见§12.18，不把历史结果改写为本轮验收。

三文档先落§10.9/§12.17/§9.5、独立审计后才编码。唯一生产修改为stock_period_silver.py，固定源码SHA256为a3088d8662a908299e113b21f2be1b72690289abc957a994dda52f1ede6a9dc5。新增test_stock_period_silver_sensor_recovery.py，既有daily_integration仅按本节已确认范围调整错误提示断言，原业务预期不变；无其他生产数据集代码修改。固定测试SHA256：新sensor_recovery为0f842181dba6f649f62ad01b7ed5815da6fb18d4966aa2f26d44d9aa62992d98；daily_integration为3c6217cbd5e6ab5ab9c0618e7fbf572e9d276d96284d79cc3ae800c178a8f0a1。

| 约束 | 实际实现 | 隔离验收结果 |
| --- | --- | --- |
| 方案不等于完成、直接confirm也不得绕过 | update_delivery_progress与confirm内部前提；sensor先查当前进度 | 两频父成功/子无CP连续tick稳定指引，未执行及部分/全committed缺summary均不ack；直接confirm拒绝 |
| 不遮挡坏记录、汇总遵循真实producer | 全已有CP逐一validate_record，reference/committed目标版本核验；summary核run_id及两频files/rows | 首CP缺失但后CP坏仍拒绝，坏JSON/错run/非committed/数量或rows错误/bool及版本漂移均拒绝；真实小summary正常通过 |
| 当前子任务不受父run结果误判 | 原FAILURE/CANCELED分支限定pending仍为original；恢复后hint使用实际execution | 父SUCCESS不使未执行child完成；父FAILURE不遮挡完成child；原失败首次冻结child也有完整配置，原requires_review前缀保留 |
| 检查及交付保持原合同 | progress后调用原batch_event_evidence/confirm，成功后原record_update_coverage再ack | 两频缺anchor检查、FAILED及错绑仍拒绝；hint的files_complete=true准确，正常恢复后确认祖先并继续下一通知 |
| 不由sensor代做、收尾失败不重算 | helper只读；上轮所测child未完成仅写原cursor决策，回执失败保留pending | 所测child未执行tick无CP/summary/行情/事件补写、无恢复RunRequest；来源再变仍同原通知/完整父链；child和parent回执写失败后仅确认收尾；未证明旧失败原ID分支 |
| 元数据缓存及查询预算 | 原recovery_evidence/read_recovery_evidence包住进度与确认，逐次stat；原两集合查询 | 所测来源未变child同tick每CP/complete实读1次、未完成0readiness、完成最多2条集合SQL，get_runs最多2次；下一tick重新读取且版本变化拒绝，不覆盖原recover全链 |
| 两频真实合同与影响面 | 原真实producer临时小Parquet、SQLite实际绑定、SDK配置解析；只修改两Silver共用模块 | week/month均独立参数化；配置含实际execution/source_completion/显式parent并指向原job；无真实源请求或正式资源测试 |

**用例及失败记录。** 修复前在原代码上两频核心反例均因缺CP错误失败（2项，2.57秒），修复后同两项通过（2.52秒）。新增首轮60项中58通过、2项partial场景失败：原测试用publish调用次数注入中断，却忽略owned_update_records已先保存2份reuse CP，导致“仅1份已提交”的断言与真实生产者顺序不符。按实际producer改在首CP持久化后取消，独立预期仍为1，不修改生产逻辑或放宽业务断言；相关partial及missing共4项定向通过（3.83秒），最后固定完整文件62项全部通过，46.85秒（XML 46.837秒）。初轮失败保留为测试注入问题，不能以第一次通过数替代最终结果。

原相关8文件首次219项里217通过：一项既有daily_integration精确等于旧错误文本，按开发前已落档范围调整为验原silver_event_file_changed前缀、files_complete=true、当前ID及可解析配置，并保持拒绝/无完成/pending断言；另一项涉及受保护停牌测试support，直接pytest入口不满足其专用启动器合同。未改停牌实现或其测试；随后按原tests/stock_suspend_confirmed_test_runner.py分开隔离执行资产治理（8项及4项），共12项、513个subtest全部通过，结束连接数0。普通相关7文件207项、5个subtest全部通过，46.75秒；其XML tests=212包含subtest，不能写成212个普通case。最终去重为62+207+12=281个普通case通过，另518个subtest；修复前/定向重复验证不另加到总数。

**成本实证与清理。** 容量场景仅为metadata和占位target stat，不将占位文件称为有效行情：658周CP共1,148,210字节、complete 711字节（execution 563,821字节）；154月CP共265,804字节、complete 710字节（execution 130,592字节）。同tick各CP/complete内容实读一次、下一tick重新读取，市场文件open为0；真实producer小fixture另验证数据链路。没有读取正式812份数据或做全局审计，未新增运行限额。

隔离清理前3个本轮精确根合计35,624个普通文件、43,844,653字节（约41.81MiB）；这是清理前留存统计，不是数据集文件数、累计读写量或峰值。已删除并逐一确认不存在：/private/tmp/dg-silver-sensor-recovery-kp5lfleh、/private/tmp/stock-suspend-isolated-gvecg0eo、/private/tmp/stock-suspend-isolated-zvpay6cx。正式Lake/staging、既有共享环境和正式instance未触碰。

修改的3个Python文件Ruff默认规则、全src/tests致命规则、根docs完整性脚本、原三文档新增本地链接及锚点核验、git diff --check通过；根docs脚本本身不覆盖lake_console文档。CodeGraph explore/impact/sync/status及当前源码补核仅涉及两Silver sensor，无Prod、API或前端消费者。开发后的独立复核曾发现原失败首次冻结后继提示缺完整配置，已补齐并加入双频反例；该次复核仍遗漏本轮原ID组合，不能继续引用为全部硬口径已覆盖。

上轮修改随其提交保存，提交号以Git记录为准；当时未推送、未部署，未重载正式code location、未执行正式definitions验证，未触发正式job或操作sensor/cursor，27日已完成补数保持原状。隔离验收不等于正式调度验收；原“到此收尾”仅为上轮记录，本轮补修和独立审计结果见§12.18.6。

<a id="period-silver-original-run-recovery-lld"></a>

### 12.18 原Silver执行失败后按真实文件进度确认

#### 12.18.1 目标、当前依据与范围

管理员已批准先完善并审计总方案§10.9、本节及月线LLD§9.5，再修改共享代码并做周/月隔离测试。目标是让已有execution的真实文件和检查决定等待或交付；旧run_key命中的失败/取消运行继续保留，但不能挡住人工用原job完成同一execution后的确认。§12.12.6已完成27日补数保持原状，本轮不部署、重载正式code location、执行正式definitions验证，不操作正式instance、Lake、staging、job、sensor或cursor。

修复前evaluate_update_sensor在pending仍为原ID且旧key最新run为FAILURE/CANCELED时，先调用recover_update_execution再直接return；Raw未变时recover仍会调用owned_update_records和batch_event_evidence，可能补reuse CP、正常化rename、读footer或多读CP。人工按提示以相同execution配置运行原job成功，只要没有复用旧key，旧key查询仍命中失败run，完整文件和检查也永远不能进入confirm。源码依据为stock_period_silver.py的evaluate_update_sensor、recover_update_execution、owned_update_records、update_delivery_progress、confirm_update_delivery及原两Silver sensor。CodeGraph已核到这条调用链，具体分支仍以当前源码为准；影响限两Silver sensor，无Prod、API或前端契约变化。以下为开发前确认的约束，实际实现及验收见§12.18.6。

唯一生产修改仍为src/orchestrator/defs/stock_period_silver.py，重点为evaluate_update_sensor分支顺序；既有progress、confirm、实际job和恢复算法保持原合同。新测试独占tests/test_stock_period_silver_original_recovery.py，原test_stock_period_silver_sensor_recovery.py的62项保持，并跑必要既有回归。文档范围仅原三文档；小型证据保留在lake_console/reports/dg_stock_period_delivery_recovery_20261028/original_silver_recovery_results.json，不另建报告目录或状态实体。预计不需改既有断言；若发现确需修改，先写明错误假设、独立依据和具体用例范围，审计后再改，禁止为通过而放宽预期。不新增tag、配置、cursor字段/schema、identity、run_key，不改asset/job、CLI、检查名、计算/写文件算法、源请求或其他数据集。

#### 12.18.2 分支顺序与提示

1. 保留根校验、周/月active互斥、原已闭合证明优先ack及原有一次旧run_key查询；active与key查询合计最多2次get_runs，不查人工成功run来猜完成。
2. 将已有execution收敛到同一路径：load并核source_completion，计算failed_original，即pending ID等于原ID且旧key最新run为FAILURE/CANCELED。此值只决定提示是否附原silver_run_requires_review、旧run ID及resume_execution_id前缀，不能决定文件完成或提前return。
3. 先比较当前execution冻结的Raw版本。未变时绝不调用recover_update_execution、owned_update_records或recover_committed，直接只读update_delivery_progress。缺complete即使全CP committed也仅等待；坏CP/summary、身份/汇总或版本矛盾仍按原错误拒绝。未完成返回当前ID、source_completion、已有显式parent、原job/partition及可解析run_config；failed_original为真时保留上述复核前缀，不自动发RunRequest。
4. 来源未变且files_complete为true时，不受旧run失败/取消状态影响：按原2条集合SQL取真实证据，执行confirm_update_delivery、record_update_coverage，再ack。人工用原job、相同execution配置、不带旧key或用不同key完成后，必须走通此路径；原失败run与原key不修改、不删除。缺检查、FAILED、错绑、日期/版本矛盾仍保留真实错误在前并附当前hint，不能当普通等待或补绿。
5. Raw已变时继续原recover_update_execution，保持原范围、原通知及完整父链，更新pending.execution_id后返回实际后继指引；首次由旧失败原ID进入时保留复核前缀。原recover的副作用与成本在§12.18.5单列，本轮不重写它，也不能把来源未变的等待约束说成来源变化已零写/零读。
6. 无execution且已有run仍返回原silver_run_requires_review，不自动请求；无execution且无run才继续原首次规划/请求路径。新旧key口径、请求数量及cursor固定字段不变。

#### 12.18.3 失败、中断与继续

来源未变的无CP、部分validated/committed、全committed缺summary都只是尚未完成，保持同ID和原配置，连续tick不补CP、恢复rename或查询检查。validated候选尚在和候选已rename但CP未提交两种中断均由人工原job继续；sensor只观察，已rename文件也不得因等待读取footer。已有坏记录不能因缺其他CP或旧失败状态而被吞掉。

全部文件和检查通过后才能写原交付回执及祖先覆盖证明；任一步回执写失败保留pending，下一tick按同一文件范围和真实检查只重试收尾，不重算、不改身份、不发恢复请求。重试时Raw又变化仍走原承接，不复用过期确认。异常和原失败run保留，不回滚已提交文件、不自动清现场。

#### 12.18.4 硬口径与隔离正反测试

| 硬口径 | 实现位置 | 必须覆盖的独立证据 |
| --- | --- | --- |
| 原ID按事实完成，旧失败仅影响hint | evaluate_update_sensor统一execution路径 | week/month分别×FAILURE/CANCELED；旧key仍失败，人工原job无旧key或不同key成功，同ID真实文件/检查通过后confirm、coverage、ack；原失败run保留 |
| 来源未变未完成只观察 | 版本比较、progress及skip | 同ID无/缺reuse CP、部分validated/committed、全committed缺summary，连续两tick稳定hint；recover/owned/recover_committed哨兵不得触发；0CP/summary/行情/业务事件补写、0readiness、0RunRequest |
| rename中断由原job继续 | 原进度路径与人工job | 真实producer制造validated候选尚在、已rename但CP尚未提交；sensor不正常化CP、不读footer，人工原job继续后能正常确认；不假造committed结果 |
| 损坏与原检查不能被旧状态掩盖 | progress及原confirm | 坏summary、缺CP却有summary、错身份/汇总继续拒绝；完整文件缺检查、FAILED、错绑仍拒绝且hint进度真实，不ack、不补绿 |
| 收尾失败不重算 | 原confirm/coverage/ack顺序 | 回执或覆盖证明写失败后pending保留，下一tick仅同范围确认；人工job/计算不得再调用；Raw再次变化不误确认 |
| 来源变化及无execution行为不变 | 原recover与原复核分支 | Raw合法变化继续生成原后继/父链/范围、首次旧失败前缀和实际child配置；无execution有run仍复核，无run仍原首次请求；不新增key/tag/config |
| 读取与查询次数准确 | recovery_evidence上下文及原readiness | 来源未变等待0集合SQL/0行情open或footer、每CP/complete内容实读至多1次；完整最多2集合SQL；两tick和回执重试逐次独立计数，跨tick不复用缓存 |
| 两频真实合同与隔离边界 | 原producer、SQLite绑定、统一DuckDB入口guard | 使用现有真实小producer每频约3周期，独立断言日期/类型/行数/关键值；实际检查/物化绑定，运行配置由原SDK解析；guard覆盖统一DuckDB入口，不访问正式资源或真实源 |

先在修复前源码上保留能抓住旧失败原ID的失败反例，再固定实现跑周/月×FAILURE/CANCELED及上述禁止项。HTTP继续现有替身，不宣称真实源或正式调度验收；不根据消费者需要反推fixture，不将被测函数的输出当expected。测试证明的单位是各自实际边界，不能用总通过数代替分支及副作用断言。

#### 12.18.5 预算、验证及完成条件

来源未变未完成tick：1份当前execution及其父链metadata、明确units对应CP/complete与必要版本stat，0源请求、0目录扫描、0集合readiness SQL、0行情内容/footer读取、0业务计算/COPY、0CP/summary/行情/DG业务事件补写；每CP/complete内容同tick至多解码1次。来源未变完整tick：同一metadata范围、最多原2条集合SQL，原交付回执/覆盖证明写入成功后才ack；回执失败下一tick仍按同范围验证收尾。正常tick、连续第二tick、一次中断后继续及最后验收分别计数，不以缓存跨tick降低账面成本。

来源变化继续原路径：每代resolve_update_sources用2条集合SQL，递归到已有末代后recover还可能再用2条；原owned_update_records可能补reuse CP、正常化已rename记录并读取其footer。上轮已明确沿用该recover，本轮保留这项既有行为及成本，不把它记为新授权、零SQL或零行情读取，不新增源请求、全局数据读取、范围扫描或业务计算。若测试发现本轮改动扩大该路径或破坏父链/范围，停止并回到原方案说明，不临时加兜底。

本轮不修改progress，658周/154月metadata容量证据可复用§12.17.6，仅补本轮缺失分支，不重复容量场景或全局审计。真实小producer每频约3周期，必要既有回归沿原隔离约束；全轮含修复前反例、一次故障续跑和最终验收，临时空间估算≤1GiB，记录实际普通文件/字节数，不当作程序新限制或累计IO上限。只清本轮精确临时目录，不清正式staging、既有共享环境或上轮证据。

清理前由测试执行记录生成上述original_silver_recovery_results.json，保留源码及新测试SHA256、实际argv、隔离根、解释器与相关测试环境版本、逐case结果及耗时、修复前“完整仍被旧失败挡住”和“未完成误入recover”两类缺陷的真实失败片段、查询/读取/写入计数断言摘要，以及已清理精确根与清理前文件/字节统计。允许保留核验这些结果所需的小型日志或测试结果；不得只保留总通过数后删除全部可复核证据，也不复制完整临时SQLite、Parquet或大日志，不保存行情与凭据。报告只是本轮隔离证据，正式资源读写仍为0。

三文档审计通过后才编码；固定实现后跑新测试、原62项及必要相关回归、修改文件默认Ruff和既有致命规则、文档完整性/本地链接锚点及git diff --check。完成独立逐项审计后，将代码位置、正反例、查询/读取/写入断言、实际数量及临时清理结果回写本节，再标开发和隔离验收完成；不得预填通过、复用上轮全部覆盖结论或把隔离通过写成正式已上线。本段为开发前约束，实际完成结果如下。

#### 12.18.6 实际实现、隔离验收及独立审计（2026-10-28完成，随本次提交保存）

先落原三文档并审计后编码。生产代码只改evaluate_update_sensor分支，18行新增、21行删除：已有execution统一判断，failed_original仅用于hint前缀；来源未变直接progress，完整后沿原检查、confirm、coverage及ack。recover、progress、计算/写文件算法、definitions、job、CLI及其他数据集未改，原62项测试未改。固定源码SHA256为f86af1fbe2f830acf6ed71237c8dbcf6121af08049144e2fbdaec18ec8a3e0e6；新test_stock_period_silver_original_recovery.py为c2f1fd3b87e431eece30a604dff6886a83e8222e8e5725b44e239b57257ddd56，与已保留[逐case证据（附件已清理）](../../reports/dg_stock_period_delivery_recovery_20261028/README.md#report-attachment-cleanup-20261103)一致。

| 约束 | 实现及实际隔离证据 |
| --- | --- |
| 原ID完整后不被旧失败挡住 | 统一execution路径；week/month×FAILURE/CANCELED共4例，真实人工原job无旧key或不同keySUCCESS后旧key仍失败，原文件及检查通过即可关闭通知，原失败run保留 |
| 来源未变未完成只观察 | progress前不调用recover/owned/recover_committed；两频×两失败状态共4个副作用反例，及缺reuse CP、validated候选尚在/已rename、连续tick，均保持同ID/hint/pending，0CP/summary/行情/业务事件补写、0readiness、0RunRequest |
| 坏记录与原检查仍拒绝 | 坏summary、有summary却缺CP、检查缺失/FAILED/错绑均保留真实拒绝；文件完整hint仍为true，不ack、不补绿 |
| 回执失败仅确认收尾 | 写失败后保留pending，下一tick按同范围原检查确认，0重算/恢复请求；每tick CP/complete内容至多实读1次，来源未变未完成0集合SQL，完整最多原2条 |
| 其他分支与两频合同不变 | 来源变化仍用原recover/父链/范围及实际child提示；无execution有run继续原复核，无run仍首次请求。真实小producer、SQLite检查绑定、原SDK配置及统一DuckDB入口guard验证，未访问正式资源或真实源 |

**修复前与测试纠正。** 修复前核心8例全部真实失败，6.26秒：4例被未完成误入recover的副作用guard抓住，4例在真实人工SUCCESS后仍被旧key失败挡住。修复后同8例通过，6.07秒。扩展新文件首次24例中21过、3失败（15.55秒），保留两类测试错误：wrong_binding周/月2例业务拒绝、真实进度、pending及零写断言已通过，但包装器在batch返回后才计数，真实decoder先抛错导致漏计；改为调用前计数，expected仍严格为1。另1例无execution复核误期望短提示，依据修复前d3e8c20e源码确认原提示本就含resume_execution_id后缀，纠正新测试精确预期，pending/无execution/无SQL要求不变。只修新测试计数位置与漏掉的既有字段，没有修改生产代码或放宽业务拒绝/预算。

固定新文件最终24项全部通过，14.76秒；原62项通过，48.64秒；相关7文件207项及5个subtest通过，49.61秒；原受保护启动器的治理8+4项及329+184个subtest通过，结束连接数均0。最终去重为24+62+207+12=305个普通case，另518个subtest；修复前8、修复后核心8和首次扩展轮次不重复计入，相关XML tests=212也不当成212个普通case。

**独立审计及边界。** 两名非作者分别以silver_original_final_code_audit核源码、LLD、控制流及真实消费者，以silver_original_final_evidence_audit逐case比对原XML、受保护报告和冻结指纹；均通过，无阻断或向其他数据集直接回归的路径。CodeGraph explore/impact及当前源码消费者核对、sync/status完成；两份修改Python的默认Ruff/格式及全src/tests致命规则通过。来源变化recover的CP正常化、footer及集合查询仍按§12.18.5保留，本轮没有将它重写或验成零成本；上方0预算仅覆盖来源未变的进度等待。

**证据与清理。** 原报告目录已保留约139KB的original_silver_recovery_results.json，含修复前后逐case、实际argv/环境、失败片段、成本断言、指纹、独立审计与清理记录。已精确删除并确认不存在：/private/tmp/dg-silver-original-recovery-cr7oen9c、/private/tmp/stock-suspend-isolated-ca2x9x6n、/private/tmp/stock-suspend-isolated-hbxhmwmj；清理前合计24,745个普通文件、30,490,844字节，约29.08MiB，小于1GiB估算。该数是清理前留存统计，不是累计IO或峰值；没有复制完整临时SQLite/Parquet或大日志，没有清共享环境或上轮证据。

本轮开发、隔离验收及独立审计已完成，修改随本次提交保存，提交号以Git记录为准；未推送。未触发正式job、补数、正式definitions验证、发布/重载，未操作正式instance、Lake、staging、sensor或cursor；27日已完成补数保持原状。隔离证据不代表正式已上线或正式调度验收。


<a id="period-lost-run-queue-release-lld"></a>

### 12.19 仅结束失去进程的run以恢复队列（已获准，结果另记）

对应总方案§10.10。目标仅run `104911a4-e1fa-4a42-a8ad-cd55a7b0dedf`的原生任务终态，不修改月Raw/Silver业务逻辑或文件。只读证据为`/private/tmp/dg_run_104911a4_status_summary_20261028.json`及`/private/tmp/dg_queue_104911a4_readonly_20261028.json`。截至23:03，STARTED1、QUEUED15、max_concurrent_runs=1、pool粒度run、实际claimed slots0、全部daemon心跳正常；原PID68394不存在。旧状态占用全局名额，不是仍有计算进程占CPU。manifest为files_complete，complete列1015周/239月，daily.pending保留；不据此宣称已完成事件确认或全部原检查。

**实现及正式入口依据。** 已安装`dagster_graphql/schema/roots/mutation.py`的GrapheneTerminateRunPolicy/GrapheneTerminateRunMutation、`implementation/execution/__init__.py`的terminate_pipeline_execution/_force_mark_as_canceled已逐项核对。强制策略先尝试coordinator.cancel_run，异常被记录后仍调用report_run_canceled；不会调用asset、Parquet writer、删除源/候选或重建数据。终态CANCELED不在ACTIVE_RUN_STATUSES，QueuedRunCoordinator下一轮按原max_concurrent_runs计算名额；run粒度pool也不另claim步骤槽位。保持run key、配置、父子关系及既有完成证据原样，不使用SDK手工FAILURE来触发失败重试判断，不调用freeConcurrencySlots。

**动作顺序与边界。** 先在只读连接复核精确run的状态、原PID及最后事件，没有新worker/续跑迹象；如已终态则只读验收。如进程仍在或状态与证据冲突，停止报告。获管理员明确批准后，从工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`，针对原`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`的正式服务`http://127.0.0.1:3000`，只提交一次以下mutation：

~~~graphql
mutation CloseLostRun($runId: String!) {
  terminateRun(runId: $runId, terminatePolicy: MARK_AS_CANCELED_IMMEDIATELY) {
    __typename
    ... on TerminateRunSuccess { run { runId status } }
    ... on TerminateRunFailure { message }
    ... on RunNotFoundError { runId }
    ... on PythonError { message }
  }
}
~~~

变量唯一为`{"runId":"104911a4-e1fa-4a42-a8ad-cd55a7b0dedf"}`。命令使用现有`.venv/bin/dagster-graphql --remote http://127.0.0.1:3000 --file /private/tmp/dg_close_lost_104911a4_20261028.graphql --variables <上述JSON>`；捕获stdout并解析保存响应，不使用直写SQL/初始化instance，不加进程/内存/网络超时配置。接口可能尝试联系旧gRPC入口；无响应或CLI异常时先读原run，不盲重发。原CLI、资源和依赖不变。

**检查与验收。** 本步无业务代码开发，不以正式资源作测试。平台合同以本机1.13.26源码和Dagster官方GraphQL/运行监控文档核验；实际状态操作需获准后才可称执行。响应应为TerminateRunSuccess且精确run CANCELED；再只读核状态及取消事件。随后在原队列节奏内检查排队任务开始进入STARTING/STARTED、心跳正常、全局并发仍1，不要求15个业务job全部成功。现无pool占用，不额外释放；如后续仍不推进，只读定位并报告，不改开关/调并发/重启服务。队列自然启动已有任务属本次预期影响，不增加手工任务。月Raw收尾另按原断点和本次具体历史范围再核定，不混入本操作。

**预算及失败恢复。** 与总方案一致，正常读取4MiB、写入1MiB、额外空间2MiB；一次不确定响应后的核验另预留读2MiB/写1MiB。只读取任务/队列、进程和小型报告，不读写Parquet、全历史或重做统计；保持所有正式结果/业务staging和daily.pending。取消事件一旦成功保留，不尝试把旧run改回STARTED，不取消其他run或改写其事件。原run记录和本轮请求/响应/队列快照保留；仅可清理本轮已归档的辅助脚本。管理员随后明确回复“马上执行”，本步精确状态收尾已获准；执行结果和原队列恢复证据在下节记录。


#### 12.19.1 已批准执行结果：旧run结束，原队列恢复

管理员明确回复“马上执行”后，先再次查询原run及原PID。原进程68394连续两次精确`ps -p`无进程行、退出码1；原run已在23:09:59留下PIPELINE_CANCELING，本次执行前状态为CANCELING。该取消中事件先于本次mutation存在，不能算作本次新提交；没有新worker或业务进度，最后业务check仍为19:33:00。

2026-10-28 23:12:03只通过原正式GraphQL提交一次精确run的MARK_AS_CANCELED_IMMEDIATELY，响应TerminateRunSuccess/CANCELED。安装版对CANCELING不再进入coordinator.cancel_run分支，本次直接补原生取消终态，没有再次请求或重启旧执行器。数据库读回run终态CANCELED、ended_at=23:12:03.157705，新增取消事件storage_id=7774305，run ID准确一致。没有直写SQL状态、手工job、并发/pool/sensor/cursor修改或正式Lake数据操作。

队列自然恢复：23:12:06原排队15降14，原队首ab9d6a45-3693-4729-9b31-edda681da85f的stock_mins_silver_update_job进入STARTING；23:13:46再读排队已降至7，当前raw_tushare_moneyflow_ind_ths_update_job的5c8c618c-baaa-4f32-8983-63ad056ab830自23:13:29起STARTED。全局并发仍1，步骤槽位仍空，daemon心跳正常。本步只证明队列恢复调度，不把队列减少量当作全部业务数据成功数，也不等待其余任务全部完成。

月Raw原files_complete、1015周/239月文件及续跑依据保留，本步未完成其事件确认、原生检查和Silver交接，不能销掉该数据待办。后续若需恢复此链，仍按原断点和本次具体范围核定；不因队列恢复就自动重跑。当前月Raw交付未完成与其他已有队列任务继续执行分开记录。

请求、响应、执行前/后run及队列快照、只读辅助源码和结果存[本轮执行证据（附件已清理）](../../reports/dg_stock_period_delivery_recovery_20261028/README.md#report-attachment-cleanup-20261103)。本次只读预算内的元数据核验和一次状态事件写入，无Parquet正文读取、无历史重算。独立复核确认请求精确、状态和队列恢复证据一致，取消中事件归属已明确；文档验证另记同目录validation.json。未提交或部署代码。


#### 12.19.2 仅只读追因：旧执行退出后未被新服务收尾

管理员要求追查本次长时间占用，已只读核对原日志、进程/启动历史、对应41秒系统退出事件及安装版1.13.26源码。终端历史明确19:33:30执行原lake-dg-start，当前DG主进程同秒启动；原daemon日志最后19:32:57、原run最后业务事件19:33:00，旧PID68394已无，且没有原生成功/失败/取消终态。旧服务维护的_executions只在内存，新服务不继承；DefaultRunLauncher未实现worker健康检测，monitor_started_run在supports_check_run_worker_health=False时跳过。因此新daemon虽正常运行，遗留STARTED仍计入全局并发1，直到本轮获准的取消终态才释放。

本项目local_startup在依赖/端口检查后exec为dg dev，没有启动时的遗留活动run核对。正常SDK代码位置重载是优雅关闭、等待执行完成；不能把上述新启动直接解释成正常代码位置重载杀掉worker。本次未找到旧进程的退出信号/动作来源，也未找到19:33对应崩溃或内存终止报告；具体退出方式未证实，不猜测为内存超限或某个操作者强杀。

[只读追因报告](../../reports/dg_stock_period_delivery_recovery_20261028/queue_release_104911a4_20261028/root_cause_readonly.md)保存时间线、小型原始证据和代码位置。长时间队列阻塞的状态收尾缺口已确认；后续若整改停止/启动保护、遗留状态核对，须另行完善方案和LLD并获准，不在本次读取中改代码/配置或继续补月Raw。


<a id="period-28-resume-lld"></a>

### 12.20 恢复28日原月Raw及两频Silver：操作细节（具体历史范围已获准）

对应总方案§10.11。目标授权来自管理员“推进，把今天的这个数据集补完整”；日期冻结2026-10-28，跨到29日不变。本节无开发、无新配置/资源限额。统计依据仅原complete.json、相关源控制回执和选中目标stat，见[精确范围（附件已清理）](../../reports/dg_stock_period_delivery_recovery_20261028/recovery_20261028_after_interrupt/README.md#report-attachment-cleanup-20261103)。本次具体历史读取未经批准前，不提交会产生两频Silver通知的Raw恢复。

**当前实现及恢复准入。** 安装Dagster1.13.26的KnownExecutionState.build_resume_retry_reexecution接受FAILURE/CANCELED，仅STEP_START而无终态视为interrupted；原月job选择asset及三blocking checks，FROM_FAILURE恢复中断asset和未完成checks。原run104911a4已CANCELED，原配置automatic_intent_date=2026-10-28、intent=daily、stock_codes=[]；不重新选股票或业务ID。当前stock_period_update的files_complete/consumed路径恢复原交付，不调用_daily_work、factor_changes、源请求、历史COPY或Raw替换；load_scope仍读股票基础及身份映射，原当前月native checks仍需实际验证。replay_events给已验文件注入版本缓存后补缺事件，未完成真实原生check仍须原job，禁止手填通过。

**精确读写范围。** Raw只收尾原ecd358…da7ae的1254文件交付、当前2026-10锚点原生物化及三checks，不重生成已完成1254份Parquet。原21字段和价格不变。Silver由原completion选择，按原2014起界限得到：month154（2014-01—2026-10、源606370行、Raw50,375,136B）、week658（2014-01-03—2026-10-30、源2543279行、Raw210,008,763B）。这不是只更新10月，亦非全Raw239月/1015周照收；原selector负责范围，无人工名单。旧Silver仅stat/归属检查，不读正文作合并。正常每重建周期Raw21列读取一次、COPY一次、候选21列校验一次、提升后footer一次；单连接加载参考后整job复用，正常原生三checks共用缓存。冷进程仅额外锚点Raw/Silver及参考一轮，不全批重读。

Raw参考投影为stock_basic的ts_code/list_status/curr_type、identity_map的source_ts_code/latest_ts_code/confidence；Silver生命周期ts_code/list_status/list_date/delist_date/is_cny_stock五列及身份映射三列。现参考文件421187B/103202B/131539B，允许原job完整投影读取，不能把参考读漏算成0。无Prod、日线、停牌、因子或新Tushare请求。正式Lake仍唯一/Volumes/datasource/data_lake，Silver目标quote/stock_weekly和quote/stock_monthly的上述周期；全部候选和控制记录仍原/Volumes/datasource/data_lake_staging。

**顺序、参数和失败规则。**

1. 获具体范围批准后，只读确认原run配置/父子身份、原phase/consumed/范围摘要、引用版本、无冲突写者、当前两Silver sensor状态及对应活动run。已有实际执行跟踪原run，原通知已消费则验收复用，不重复提交。原sensor/cursor/并发及资源配置保持，不做正式reload或服务重启。
2. 通过现有`.venv/bin/dagster-graphql --remote http://127.0.0.1:3000 --file <本轮请求> --variables <JSON>`，用§12.8原launchRunReexecution，只提交一次parentRunId=104911a4-e1fa-4a42-a8ad-cd55a7b0dedf、strategy=FROM_FAILURE、useParentRunTags=true，不加extraTags，不改runConfig。原意图28日/月分区2026-10随父继承；SDK生成新parent/root关系，原CANCELED记录不改。
3. 跟踪原asset及三原生checks，核同分区、原新文件版本和正确Mat绑定；本批其他交付按原完整清单确认。即使phase仍files_complete，也不得用checks-only跳过未成功asset，不重跑apply/resume生成文件。
4. 由原week/month通知和原sensor生成原silver_stock_weekly_update_job、silver_stock_monthly_update_job；按原队列逐job推进，两层依赖先Raw再Silver，不加新run key或手工猜execution_id。每tick最多原1通知/请求，名单/日期由job生成。本次明确纳入两频通知导致的历史更新。若sensor要求原显式恢复，先核冻结原execution/parent及真实文件进度，再复用原job已有resume_from_execution_id方式，不能临时开发、手写CP或无限重试。
5. Raw原生检查完成后，如原pending尚未关闭，仅按§12.11原events入口对同一ecd358…da7ae确认：`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/python3 -B -m orchestrator.defs.bootstrap.stock_period_history_cli events --lake-root /Volumes/datasource/data_lake --staging-root /Volumes/datasource/data_lake_staging --run-id ecd358c33a8dfeeb073fb881d93c4c70a1a4ab61033a8df7ef48ee746eeda7ae`。该步骤只核原回执/真实检查后ack，0新源/0历史重算；不借此补缺的真实失败check或换日期。
6. 任一原job/检查/身份/日期或归属失败，保留已正式提交文件及全部源/CP/receipt，停止后续手工操作、报告已自动开始的任务，不自动重跑或提高资源。响应不确定先查原run。中断余项只能依原CP续跑，不整批重新读取已完成输出。现有CANCELED当日key不自动换key重跑，不把正常29日任务拿来冒充28日修复。

**预算、验收及结果。** 两频已有Raw约248.32MiB、旧Silver约162.86MiB；正常读768MiB/写384MiB/空间512MiB。含一次必要中断后仅余项恢复、冷锚点checks及唯一最后收尾，总读2GiB/写1GiB/额外空间1GiB，含元数据及DB事件开销；不是外部运行限额。预算不授权重复整批重算或任意重试。验收复用完整manifest/逐期CP/真实Mat和三checks，核来源版本、文件计数/行数及两Silver cursor消费/无pending；仅对当前月必要统计核新版本，不另做全湖或年度深扫。原当月end_date较早的2211行不强改、不直接认定缺失；源回执原本混合12—28日，原排除1行后5575行与正式Raw吻合。若要另查源站是否后续更新，需先说明新范围，本轮不重下源伪造原批结果。

本步已完成当前代码/平台和范围审计，不需要新开发或性能测试；正式job结果在获具体读取批准并执行后另记。准备不代表执行通过，旧27日批准不覆盖本节28日读取。


管理员已明确选择“批准，按此范围恢复”，授权本节28日原任务及154个月/658周Silver、必要参考读取和含余项续跑收尾的读2GiB/写1GiB/空间1GiB预算。执行日期已为29日，原意图28日不变；正式结果另记，不以批准代替成功。


#### 12.20.1 28日原任务恢复及两频Silver执行完成（29日凌晨）

按本节获准范围仅提交一次原月Raw的FROM_FAILURE，子run08b25eaf-c4c7-491f-9f71-77455d9fda11，10月29日00:20:07—00:21:51 SUCCESS，parent/root仍104911a4，原28日意图/10月分区/原参数保持，无RSS额外标签。恢复补齐剩余1806条原检查事件并完成当前锚点真实物化/三checks；原1254个Raw文件当前版本与旧complete全部一致，本轮0新下载/0 Raw重写。原events控制入口执行一次成功，phase=events_complete、原pending=0；没有手填状态或刷绿。

原通知自动生成原周Silver de5acd12-5a5e-4fc1-834a-a1c3050fdaca（00:22:24—00:24:11）与月Silver5a20903d-1bf0-4e52-ad9b-0c52a0709800（00:24:50—00:25:22），两者均SUCCESS。周658周期/2519597行/1974检查，月154周期/595228行/462检查，合812文件/3114825行/2436检查。每个实际unit的committed CP、events回执和正式stat版本吻合；两个源引用均绑定原ecd358批及同一回执hash。原通知7778143（周）/7778142（月）均被两sensor确认，after已越过、pending均无。四sensor仍RUNNING，不改cursor或原并发。

00:26完成唯一最终对账：2026-10月Raw/Silver均5575行，Silver的source_version精确等当前Raw，最新物化对应实际文件、六项最新原检查各绑定本层新物化；两文件max(end_date)=28日、3364行end_date为28。其余2211行保留原源较早值，不把最大日期当全部股票新鲜度。daily.factor_through=28、month.last_refresh=28；week.last_refresh仍27，因为本次是月任务联动历史，不冒称28日独立周Raw日更完成。已闭合周23日/月9月不提前关闭当前周期。

[本轮执行与证据](../../reports/dg_stock_period_delivery_recovery_20261028/recovery_20261028_after_interrupt/README.md)保存请求/响应、原控制收尾、进度、最终回执和当前月统计。沿原最终验收程序仅调整实际ID/日期，原模板three notices文字按本轮实际two修正，不改变事实数字或重验行情。final verifier中的formal_mutations=0只描述该只读程序，不把整轮Silver正式写入说成0；Raw commit_operations1254指原批次，不是本轮重写。独立复核通过；本轮三份临时辅助源码逐字归档后删除，业务staging及正式成果保留。无代码/配置/依赖/部署变更，文档和证据验证另存validation.json。

<a id="period-29-30-preflight"></a>

### 12.21 31日恢复准入：29日意图与30日来源的日期冲突

对应总方案§10.12。本轮仅完成已获准的定点只读核验，发现冲突即停止，尚未修改业务代码或执行正式恢复；不是可直接编码的完整修正LLD。结果和完整原始证据唯一见[本轮记录](../../reports/dg_stock_period_delivery_recovery_20261028/recovery_20261031_preflight/README.md)。

**当前事实。** 31日09:03:47，原29日月执行2742186f…97f3仍download/consumed=false，无候选/提交/完成回执；冻结asof=2026-10-29，原job名单为000878.SZ、688563.SH、920306.BJ，两频均需处理。前两股周线单元完成，新股周线当时0行。当前四文件各一次聚合确认：week Raw/Silver各5569行、month Raw/Silver各5575行，max(end_date)均20261028，0行截至30日，均无920306.BJ。四sensor RUNNING、链路无活动run；latest source/date统计不能替代全市场覆盖或历史任务成功证明。旧23/28日完成证据复用，不读其他历史周期。

**已确认的具体代码冲突。** `stock_period_source.capture_unit`已经支持跨日重取未完成页且保留已完成单元；原空源并非要求永远缓存为空。本轮MCP仅单股/10月/两频/完整21字段，各1行end_date=20261030。`stock_period_silver.read_completion`优先使用Raw冻结intent.asof（本次29日），`select_period`拒绝source_asof超过此日期；`stock_period_update._execute_daily_locked`又禁止不同意图越过旧待办。因此直接接入当前源行将触发Silver日期拒绝，本轮没有提交正式job去复现。

**停止边界及建议。** 保留原29日意图/业务ID、成功源单元、所有正式结果和pending。后续方案须明确原任务日期与经来源回执核实的实际截至日期分别用于什么，完整核对Raw交付、Silver身份/范围、检查、物化、恢复及sensor，不只删除日期谓词、不用机器当天、不伪造29日源快照。旧29日完成不能冒记30日因子水位或日更，之后仍需原30日处理。先补齐具体方案/LLD与正反隔离验证，再正式恢复；本节建议未开发，不给出实现通过结论。恢复的真实历史范围及含中断/收尾预算仍须按原job产物核定，旧28日批准不替代本次范围。

**读取及清理记录。** 本轮无行情历史读取；当前四文件磁盘合计1,523,109B，仅ts_code/end_date计数聚合各一次，不把文件大小当实测IO。Silver日历只读10月1—30日SSE日期依据，不读Raw日历或产生独立日历审计。只读PG限定四job各最近8run及四sensor、原失败事件；源仅两次单股请求。无COPY、Lake/staging写入、Dagster状态写入、job/check/sensor操作、安装或重跑补数。辅助脚本首次缺类型导入在元数据阶段退出，补齐后完成，行情聚合只执行一轮；最终归档.py.txt后删除临时可执行副本，保留必要JSON，不清理业务staging。

<a id="period-cross-day-source-asof-fix"></a>

### 12.22 跨日恢复的来源日期：具体开发与验收LLD

对应总方案§10.13，管理员已授权先修正并审计补数条件，本轮不正式补数。§12.12关于跨日超出意图日期即停止的操作记录保留为历史；本节实施验收后，日常新交付按下述有来源证明的逐文件日期承接，不把旧操作停点当作新实现永久限制。

#### 12.22.1 目标、现有代码及影响面

真实证据复用§12.21的920306.BJ两频各1行、end_date=20261030及原29日pending，不重新查询正式源或行情。当前capture_unit已经按跨日未完成页另建来源链、复用完成单元，本轮不改下载模块。当前Raw _validate_candidates已经一次聚合验证end_date格式，但未将最大日期交付给Silver；publish保留item字段，_finish_files把逐文件item保存为complete.files并绑定原digest。Silver read_completion已有完整回执/hash/设备/路径核验，但只返回原意图日期；resolve_update_sources将其分配给全部unit，导致本次拒绝。

CodeGraph已核read_completion→resolve_update_sources→update_inputs/recover_update_execution/evaluate_update_sensor；按当前代码补核Raw候选/发布、Silver真实选行、检查、物化及恢复。改动只在DG内，不涉及Prod、业务API、前端或其他数据集。源码白名单为defs/io/stock_period_raw.py与defs/stock_period_silver.py；新增tests/test_stock_period_cross_day_asof.py，必要既有周/月回归只运行不弱化断言。三份原文档及本轮验收报告同步，不新增运行入口、配置、job、sensor、检查或字段schema。

#### 12.22.2 日期含义与Raw实际生产

1. intent.asof仍是原任务计划更新日。冻结29日请求续跑仍属29日，执行ID、request_id、日/月分区及来源单元身份不变；不得改为30/31日。
2. 新增每文件控制字段source_asof，表示该候选实际max(end_date)，不是全市场更新完成证明。JSON为规范YYYY-MM-DD字符串；全NULL/零行时为null，后续Silver原NULL/完整性规则仍负责拒绝。Raw/Silver Parquet的21列、类型、值和排序均不变。
3. 在_validate_candidates现有candidate_facts分组聚合中增加对end_date的max；已有非法日期计数必须先拒绝，再将日期规范化。原查询次数、读取列、完整校验及摘要次数保持，不另读候选计算日期。返回facts增加source_asof，由_candidate_receipts现有展开写入item及原验证hash；publish提交checkpoint时保留，并把该字段纳入已提交checkpoint与item的一致性比较。_finish_files继续原样收集changed并计算完整回执hash，无需新增格式版本或另一套回执。
4. 新字段只随本次新候选生产。既有已验证/已提交/完整回执不补写、不改hash、不重扫行情；字段缺失时Silver保留原日期上限，不推测更晚日期。当前29日现场尚无build/candidates/complete/committed，恢复后会正常生成带此字段的新回执，不需要重建28日批次。

#### 12.22.3 Silver逐文件接收与必要拒绝

read_completion必须先完成原validate_completion_reference、verify_execution、root/phase/run/hash、设备、带时区files_completed_at、原asof和每文件路径/重复检查。随后仅用已校验complete.files中的source_asof：

- 字段缺失或null：该文件unit.asof沿原交付asof，不读取Parquet或旧源页猜日期。
- 有值：必须是规范ISO日字符串；非法值拒绝为silver_raw_completion_source_date_invalid。来源日期晚于原files_completed_at的上海日期也拒绝；不能把一条未来日期取max后自证合法。完成时间仅作独立上限，不能赋给有明确意图的新源观察日期。
- 该文件unit.asof=max(原交付asof,该文件source_asof)。同日来源不变、合法较早历史来源不倒退；29日意图/30日来源/31日完成的unit应为30日，不能误取31日。
- 原read_completion返回的asof保留原交付日期，items保存不改原JSON的副本，为各item增加用于执行的asof。resolve_update_sources从实际选中delivery的item读取asof，不用原批次或整批最大日期。合法后继Raw也必须取其自身item日期；不同周期可为29/30两个日期。

已有Silver unit.asof继续进入make_update_execution的冻结units、select_period的source_asof上限、validate_materialization_scope、物化goldenshare/silver_asof、原三检查和恢复input_hash。SQL日期谓词不删除、不重算价格、不重建state。已完成Silver unit/回执不改；同来源原ID恢复保持已冻结日期，真实Raw来源变化继续原后继恢复流程。没有新增双轨计算或历史迁移。

无intent.asof的原主动history原先以files_completed_at日期为交付范围，保持其原口径；max运算及未来日期校验不会将其改为更早源日。首次Silver bootstrap继续原审计报告asof/lower，完全不进入本次更新日期选择。

#### 12.22.4 水位、失败、中断和成本

_consume_daily_files继续只以原intent.asof推进last_refresh/factor_through及原source_final；unit_asofs原实际源观察记录不改。29日原任务的完成不能冒记30日日更、30日因子变化或上市集合处理完成，之后仍运行30日原job。原pending守卫、事件绑定、三项检查、唯一writer及幂等checkpoint不放宽。

失败停止并保留已完成源单元、正式文件和原回执，不删除pending、伪造成功或修改源日期。已有checkpoint不允许source_asof与候选item冲突。文件已rename但回执未写仍沿原digest/版本恢复，原source_asof随item保留。Silver中断只继续未完成unit，已有unit日期、源hash和检查绑定不变；sensor确认失败继续原有界收尾，不重做已完成行情。

正常及一次必要中断恢复/最终验收均不增加行情读取轮数、源请求、COPY或完整摘要读取。每新候选在原SQL里新增一个max，控制JSON每文件只增加一个ISO日期/null，随原hash核验；不创建额外控制文件，不扫描历史目录寻找日期。开发全轮用少数股票/周期、临时源与隔离instance，预计临时空间≤1GiB（包含故障恢复及最后验收），不是正式job新限额。无性能试跑、依赖安装、正式数据读取/写入或正式DG操作。后续正式补数预算另按实际原job范围核定，不能拿隔离预算或28日批准替代。

#### 12.22.5 必须落实的验收对账

| 要求 | 代码/消费者 | 独立正反验收 |
| --- | --- | --- |
| 来源日期由真实候选产生且不加读取轮数 | Raw原candidate_facts→validated item→publish CP→complete | 实际21列小Parquet/原producer，字面max日期；记录原查询次数，字段改动不增加扫描；合法NULL保持，不把错误日期归零 |
| 保留原意图、下载及水位 | capture_unit、run_period、execute_daily原逻辑 | 29日空源后跨到30日，仅未完成单元重取；request_id不变，成功页/其他日期版本保留，29日完成不把factor_through推进30日 |
| 两频跨日来源可通过 | read_completion/resolve及原Silver job/check | 29意图、30源、31完成，应按30通过week/month；修复前同样例真实失败，修复后原三checks及metadata通过 |
| 拒绝真实错误，不抹掉原检查 | 原回执hash/路径及选行日期谓词 | 非法/未来source_asof、坏hash、错路径、真实失败/错绑仍拒绝；缺日期证明保留原上限，不通过读行情临时补证 |
| 不用整批最大日/机器当天 | 实际delivery的逐item.asof | 两周期29/30分别保留，恢复/后继来源各取其文件日；同日正常与合法早历史通过；主动history/bootstrap口径不变 |
| 中断、幂等与其他历史保留 | 原逐文件CP、Silver恢复与sensor | 带日期CP冲突拒绝，rename后回执失败可恢复；Silver中断后只续余项、完成后同通知确认不重写；原28日/无关文件版本不变 |

测试预期来自独立字面日期、当前真实21列合同及§12.21单股证据，不从待测函数生成expected；允许替代上游HTTP，但明确验证实际文件/SQL/回执/job/check。隔离资源禁止访问正式instance、Lake/DB/Tushare，不以mock通过冒充正式补数完成。先写方案/LLD并核对以上落点，再编写缺陷反例，记录旧代码失败，修改后运行必要周/月回归；最后独立重读源码和测试逐条对账、清理本轮夹具并汇报。正式加载/补数和具体历史批准均不包含在本次开发。

#### 12.22.6 开发、隔离验收及源码复核完成

2026-10-31已按本节顺序完成。运行文件仅改Raw _validate_candidates/publish及Silver read_completion/resolve_update_sources四函数，新增test_stock_period_cross_day_asof.py；下载、日常水位、Silver21列合同、原日期谓词、三检查定义及其他数据集未改。source_asof实际由原候选聚合产生，原CP/complete传递并核hash；每文件范围与metadata/恢复一致，旧回执不修改或补扫。

修复前两个隔离反例真实失败；修复后相关461项全部通过，另补旧通知选择新Raw的两频日期验证2项，通过463个不重复用例，其中新增28项。两频“29日空源→30日原请求续跑→Silver实际job/三checks/ack”、正常/部分提交中断、逐文件29/29/30日期及31日完成、旧回执无证明仍拒绝晚日期、非法/未来日期、CP冲突和rename后回执失败均有证据。HTTP/时钟使用替身，实际文件、SQL、回执、job/check及隔离事件存储；不冒充正式运行。最终Ruff、文档及差异检查通过，CodeGraph sync/status已更新；独立重读确认代码与本节无阻断遗漏。

完整逐项对账、命令、源码指纹、XML及清理见[本轮实施报告](../../reports/dg_stock_period_delivery_recovery_20261028/cross_day_source_asof_fix_20261031/README.md)。已清理5个本轮夹具树、31,373普通文件／53,615,463B，非实测累计IO；必要小型证据保留，正式结果/staging和共享依赖未动。开发验收阶段未触发正式job、重载code location、读写正式数据、查询源或安装依赖。本轮修改随本次提交保存；正式加载及预算核定另记，验收JSON保留提交前状态。

代码层面具备继续恢复29日的条件；正式执行前仍须确认加载本轮代码，并核精确pending、活动run及29/30日原job的历史范围/预算。预算必须先于可能自动通知Silver的Raw恢复取得批准，旧28日范围不替代。通过后先原29日月Raw及其两频Silver，再原30日日更；不重跑28日完成批次或增加全局审计。

### 12.23 31日获准重启及预算核定：执行边界

对应总方案§10.14。管理员本轮明确授权提交、重启DG确认新代码及核定预算；不触发正式补数。修复commit=4a5a5e17b，验收源码指纹保持。工作目录仍/Users/congming/github/goldenshare/lake_console/orchestrator，正式DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home，原3000端口、现有.venv及原启动配置不改。

**已核事实与顺序。** 09:48全局STARTING/STARTED/CANCELING=0、QUEUED=0；原父进程89797，webserver89842、daemon89843，代码进程4138仍为30日启动。只读连接强制只读，原29日pending三股/两频、last_refresh及factor_through未变。先执行`bash /Users/congming/github/goldenshare/lake_console/bin/lake-dg-start --check-only`，所有依赖查询就绪后，在操作前再次确认没有活动run；若有，等待其自然终态，不中断业务job。

**正式重启操作。** 无活动run时，只向核准的原父PID执行`kill -INT 89797`。已读本机Dagster1.13.26 dev_command_impl，其KeyboardInterrupt路径经现有IPC通知webserver/daemon退出并等待进程结束；不向整个进程组发信号、不kill -9。只读核原父/子/3000监听已结束。若发现进程仍有业务工作或状态不一致，停止报告，不强杀。随后从原工作目录用现有Python subprocess.Popen调用上述lake-dg-start（不带check-only），stdin=DEVNULL、start_new_session=True、日志仅写本轮/private/tmp目录；不修改启动器、.env、依赖、超时、RSS、并发或sensor配置。该启动器只会使用原正式实例与原PG/CH/隧道；依赖已就绪时复用，不初始化数据库。

启动后通过原`dagster-graphql --remote http://127.0.0.1:3000 --text`仅查询version及repositoriesOrError，确认orchestrator/__repository__可用；核新DG父/代码进程启动晚于提交源码mtime，代码进程参数仍-m orchestrator.definitions及现工作区/src，文件指纹等于463项验收版本。再只读核原待办/水位及四sensor与启动前一致，无手工任务、cursor或状态修复。新服务自然运行既有调度属于重启的正常影响，不能把它算作本轮已补数。

**中断与恢复。** 原业务结果/源/CP/receipt全保留。收到未知响应或启动异常先读精确进程/端口及原日志，不重复启动第二套DG、不改旧run为成功、不清pending。依赖验证失败则停止，不进行安装或配置修复。启动失败时保持已获准配置和证据，报告具体原因；不能拿旧代码回滚业务数据。正常控制读取及一次状态不确定后的复核预算为读16MiB、日志/小型报告写16MiB、额外空间32MiB，不含市场数据、不对正式job施加新限额；等待分成≤60秒以持续汇报。

**预算核定的读取白名单。** 原daily.json、baseline及其中范围/版本索引、原29日manifest/identity、已成功源unit及page receipt元数据；这里只读控制数据，不读原响应行情/CSV。对按索引/已冻结请求选出的Raw/Silver文件只stat，不glob读取行情。必要参考文件只stat；因子/对象变化若需计数，只用统计计数查询并保留SQL和范围，不导出全市场明细或修改planner。对比现行代码的正常读写、候选校验、摘要、提交、原检查及中断余项/收尾，计入原job本身会读的参考和历史；数据体积与预计累计IO分别说明。未由原30日job生成的名单只能作范围估计，不能虚构成实际执行名单。具体数据读写范围/预算形成后写本节执行记录，取得该范围批准前不提交会通知Silver的Raw恢复。

<a id="period-29-30-budget"></a>

#### 12.23.1 重启完成、29—30日范围及预算核定

本节记录§12.23预算汇报阶段的实际结果及后续历史申请依据，**当时尚未批准或执行历史补数**；后续批准与执行见§12.23.2—12.23.4。完整事实和只读程序见[操作报告](../../reports/dg_stock_period_delivery_recovery_20261028/restart_and_budget_20261031/README.md)，本节与总方案§10.14一致；这些操作记录随本次收尾提交保存，验收JSON保留提交前快照。

**加载结果。** 09:49:57再次核活动/排队0后只向89797发送SIGINT，原父/web/daemon/代码均退出；09:49:59原启动器建立父30797，新代码30834于09:50:02启动，web30848/daemon30849。原只读GraphQL确认1.13.26及orchestrator/__repository__，代码位置仍当前工作区。7份有关源码/测试SHA256同时等于提交4a5a5e17b及463项通过版本，mtime均早于新代码进程。09:59活动/排队0，原pending、last_refresh/last_source_asof/factor_through/completed_through及四sensor状态/业务cursor未变；两个Silver evaluated_at自然推进，仅比较其余业务字段，未手工改cursor。此前只读字节相等断言因这两个正常时间变化退出，经明确核差异后重新比较；没有修正式状态。

**真实范围依据。** 原baseline范围索引hash有效，按_old_range_paths及冻结请求选择；Raw文件stat逐一等于登记版本，Silver仅stat。没有读历史OHLC或运行planner。30日一次相邻因子计数确认合资格变化11、新上市/退出0、当前5577、未解释退市0；第二次不同目的的count查询仅把变化与原股票区间/文件索引连接，输出周期及涉及股票数，用于确定文件范围，未导出代码名单、价格或物化任务。正式名单/范围由原job生成，统计不作为执行参数。

| 日期/范围 | Raw现有文件 | Raw体积 | Silver文件 | Silver现有体积 | Silver需读的Raw |
| --- | --- | --- | --- | --- | --- |
| 29日周，1998-06-05—2026-10-30 | 1410 | 274.636MiB | 631，2014-01-03起 | 128.166MiB | 195.445MiB |
| 29日月，1998-06—2026-10 | 337 | 66.684MiB | 150，2014-01起 | 31.095MiB | 47.314MiB |
| 30日周，1997-06-20—2026-10-30 | 1488 | 282.001MiB | 658，2014-01-03起 | 131.281MiB | 200.280MiB |
| 30日月历史，1997-06—2026-10 | 353 | 67.993MiB | 154，2014-01起 | 31.568MiB | 48.041MiB |

29日原2742186f…97f3的3股不变；两股已成功周source单元复用（1409/169行），剩余新股周/3股月/当前月约5个单元，原共7个，不重下成功部分。29日Raw1747份/341.320MiB、Silver781份/159.261MiB。30日11股原两频历史22单元，加当前周/月2单元，正常约24页；页长仍6000，当前索引计数周7836/月1865只用于预算，不声称等于新源响应。实际分页、空源检查、传输重试按原实现，不加次数上限或性能试跑。

**30日两job不能漏算。** 先周job处理11股两频历史及当前周，待原两频Silver交付确认后，再月job全市场刷新当前月及月Silver。两频历史涉及1841份不同Raw/349.994MiB、812份Silver/162.849MiB，但月job另更新已在历史范围内的当前月，实际预计Raw1842次/Silver813次写入；同周期多次正常更新已计入预算。29/30之间重叠文件亦分别计算，不能删29日pending或把源截至30日当作已处理30日因子。

**字段及必要读取。** Raw读受影响旧周期完整21列一次，替换受影响股票并保留同文件其他股票；不能以仅3/11股为由只导出这些股票覆盖共享文件。Raw参考为Basic三列、身份三列及原日历；30日含29/30相邻因子及原资格判定。Silver按实际Raw交付读2014起选中周期21列，生命周期五列/身份三列按原job复用，旧Silver只stat而非读正文合并。参考文件stat合计小于1MiB，预算计入。没有授权Prod、日线、分钟、MACD、九转、额外停牌或其他历史链。

**原写入校验与IO估计。** 分片若需合并，Raw分片再读/COPY一次；每Raw候选原校验一次、SHA一次，source_asof仍在同一原聚合产生。Silver每候选COPY一次、原校验一次，正式原生三checks复用同版本缓存；不另触发全批深扫，冷恢复仅必要锚点/未完成范围。以旧Raw R、Silver输入Q、旧Silver S、候选压缩体积取1.25倍估计：正常每批读R+3×1.25R+Q+1.25S，写2×1.25R+1.25S。29日约2.015/1.028GiB，30日约2.065/1.053GiB；再预留来源/当前月/控制开销后，正常两日读5GiB/写2.5GiB。1.25是预算余量，不是实测上界，stat体积不等于实际累计IO。

| 两日预算组成 | 读 | 写 |
| --- | --- | --- |
| 正常业务 | 5GiB | 2.5GiB |
| 一次中断后仅未完成部分续跑 | 2GiB | 1GiB |
| 来源/参考/控制及一次原检查收尾 | 0.5GiB | 0.5GiB |
| DuckDB临时IO预留，未发生则不消耗 | 4GiB | 4GiB |
| 向上取整预计总量 | **12GiB** | **8GiB** |

额外空间预留24GiB，含原16GiB spill允许量、候选/分片及上批留存；原512B/行+16KiB/文件的最大单频输出准入约1.73GiB，加原spill约17.73GiB，24GiB留余量，不是实际会写24GiB。当前两根同一文件系统剩余约2.64TiB。临时累计IO未实测，预算是估计而非硬件保证，不为预算再做性能测试或全量读取。原DuckDB/内存/线程/workspace/spill/并发、重试不变，不加timeout或RSS标签；原任务已有显式配置继续按原配置，不用预算重写配置。

**后续执行与失败规则。** 取得本节具体历史范围批准后，先对原29日月Raw 4d3edf1d-9958-44b0-bde1-8a9f0cce1965作原FROM_FAILURE，原意图和源成功单元保留，原events只补缺；等两Silver及交付确认，再30日周链、30日月链。保持29日身份，逐文件按已验证source_asof承接30日源；不把完成时间当来源，不跳过30日因子。一次必要中断只续未完成部分，不自动重跑全批、不重跑28日完成job；已提交文件及回执保留。若真实名单/日期/版本与本节依据不符，先核差异报告，不能借预算扩大范围、手填状态或绕过原检查。最后仅一次原CP/receipt、文件计数、来源版本、检查绑定与必要当前锚点核验，不做全历史行情对比。当前停在正式补数前，旧28日批准不覆盖本节。

#### 12.23.2 本轮历史批准、精确操作及停止条件

管理员已对上一节回复“批准，开始补数”，故上一节待批准/未执行描述是此前快照；本节起获准正式执行29/30原周月链及具体读12GiB/写8GiB/空间24GiB预算，不增加代码、性能试跑或全局审计。原计划/源码均已核，复用§12.8及28日成功恢复的原GraphQL和events入口，无新计算入口。

每次提交前只读原pending、父run完整配置及子run/本链活动任务、已批准元数据版本和空间；原新代码指纹须仍等4a5a5e17b，不重新扫描历史行情/因子或运行planner。已有同一恢复子run时继续跟踪它，不重复提交。正式根/staging、DAGSTER_HOME和工作目录均沿上一节；其他正常任务不取消、不插队，四sensor保持原运行。

原生恢复请求为已有 `launchRunReexecution(reexecutionParams:$params)`，变量仅 `parentRunId`、`strategy:FROM_FAILURE`、`useParentRunTags:true`。三步父run依次为29日月 `4d3edf1d-9958-44b0-bde1-8a9f0cce1965`、30日周 `ba86b78f-be13-4bd9-8a6d-b3ab25f148b8`、30日月 `99f738d8-badd-49e7-81e9-931d4f45b979`；每步只提交一次，不加extraTags、不改runConfig、意图日期/分区/名单或run key。完整原配置由SDK继承。命令模板为：

```sh
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dagster-graphql --remote http://127.0.0.1:3000 --file /private/tmp/dg-period-2930-execution-20261031/reexecution.graphql --variables '<该步原父run对应的params JSON>'
```

当前安装版远程CLI把响应字典打印到stdout，不使用本地查询专属的--output。原文留存并按json/ast.literal_eval解析到本轮小报告。无响应/非成功响应时先读原父子run，不盲重发或直接SQL写状态。

每个Raw job SUCCESS后，若原业务manifest仍files_complete且原生checks已完成，用原控制收尾命令（原execution由冻结请求/本次原job产生，不人工生成名单）：

```sh
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/python3 -B -m orchestrator.defs.bootstrap.stock_period_history_cli events --run-id <该步原64位业务execution>
```

只确认原交付、补缺事件及receipt，不执行apply/resume/bootstrap/handoff或直接调用补数函数。若已events_complete且原pending已关闭则不重复收尾。随后等待原通知两频Silver或该步实际频率完成及sensor确认，才推进下一父run；Silver失败不自动换ID重跑，停止报告。30日11股名单及范围仍由原job生成；真实变化超出已核范围先报告，不篡改冻结产物。

监控只读本批run的最后事件、必要计数、原manifest/pending与两个Silver cursor；原check/CP/complete是主要验收依据，最后只进行一次所有本批回执/stat/绑定对账及四个当前周/月文件的计数/截至日统计。不得追加每历史文件正文审计。中断复用原身份、成功源及committed文件，只续未完，若发生新的业务错误停止，不自动重复大范围读取。保留正式成果和业务staging，小型操作记录归档后仅清本轮辅助脚本。

#### 12.23.3 首次4GiB停点及8GiB后续恢复

**实际结果。** 31日10:19:28—10:20:01，仅首次原29日月Raw子run488ae87d-d27d-47d0-90ff-69089416121b运行约32.6秒，parent/root仍4d3edf1d-9958-44b0-bde1-8a9f0cce1965、意图29日/分区2026-10。按本轮已批准口径未加extraTags，manifest.identity.policy.rss_bytes=4294967296（4GiB），原check_memory报period_process_memory_exceeded。不是DuckDB单字符串4GiB错误，也不是本轮新增限制。§12.13的8GiB是此前指定恢复run标签，不是默认值变更，新日期的调度任务仍冻结4GiB。

**失败边界。** 堆栈为assemble→_candidate_receipts→_validate_candidates→candidate_schemas的execute/check_memory；周线old/combined临时表所在连接尚未退出，schema查询后的RSS检查触发。默认路径没有采样峰值持久化，不能编造超过4GiB的精确峰值或把全部开销归因于某一列。实际周COPY receipt已写，1410周期/3483992行、1306份需合并候选及其merged证明留存；验证尚未完成，不能算已通过。月build未开始；候选清单/正式complete不存在、committed=0、该run没有业务物化/检查事件。对原登记1747份受影响Raw仅stat核对全部版本未变，无Parquet正文读取。两Silver及30日没有启动，原pending/水位保持。

**保留与续跑依据。** 原000878.SZ、688563.SH两周源complete仍为29日原mtime/1409与169行；本次920306.BJ在原active_chain所指跨日子目录成功保存1行、截至20261030，老空页保留不改。初步直接子目录检查显示老空链complete=false，随后按生产者active_chain合同核实新链，不能误报仍为空。周build共576186764B（约549.5MiB，包括分片/merged/小记录）全部保留；不是正式数据。copy.json存在时，原assemble会先核完整identity、源版本、归属和分片证明，沿原候选收尾，不再重新读取旧周行情、重做周COPY或重下成功源。月候选仍需原job正常生成。正常及一次未完成续跑已包含在12/8GiB总预算，不新增年度/历史范围。

**建议的最小操作变化（尚待管理员确认）。** 复用§12.13已开发/隔离验收的运行tag及其配置审计，无新代码/配置名：仅对下一次29日月Raw恢复及后续30日周Raw使用extraTags=[{key:goldenshare/stock_period_rss_limit_gib,value:"8"}]。29日下一父为本次失败488ae87d-d27d-47d0-90ff-69089416121b，root仍原4d3edf1d；30日周父仍ba86b78f-be13-4bd9-8a6d-b3ab25f148b8。两者strategy=FROM_FAILURE/useParentRunTags=true，其余日期、分区、runConfig及run key全部继承。30日单独当前月原99f738d8保持原配置，不加tag，Silver及其他数据集不消费此tag。冻结policy/下载身份和成功页不变，8GiB只改变本次原process_memory_budget阈值，不改变默认值。

原4GiB候选续跑在新连接中无需持有旧合并表，成本会下降，但尚未执行，不能承诺原4GiB一定足够。与直接再试4GiB相比，建议使用现成8GiB减少再次碰到同一门槛的风险；也不能宣称8GiB已经正式验证足够。本轮§12.23.2明定不加extraTags且新错误停止，因此当前不自行加标签或再发job。获准后先同步本节批准状态，再按原顺序一次恢复；再次失败就停止，不自动扩大内存/读取范围。正式目标/源/CP不清理，失败证据及辅助程序小副本归档，保留本轮事实，不伪造成功。

**后续批准及本次参数。** 管理员已明确回复“批准”，授权本节现成8GiB资源选项及后续原顺序；上文未实施/待确认描述属于首次失败时状态。29日请求params={parentRunId:"488ae87d-d27d-47d0-90ff-69089416121b",strategy:"FROM_FAILURE",useParentRunTags:true,extraTags:[{key:"goldenshare/stock_period_rss_limit_gib",value:"8"}]}；30日周请求同参数、parentRunId改ba86b78f-be13-4bd9-8a6d-b3ab25f148b8。30日月parent仍99f738d8-badd-49e7-81e9-931d4f45b979，不加extraTags。其余命令/工作目录/DAGSTER_HOME、原events收尾、通知Silver及一次最终核验沿§12.23.2。原“不加extraTags”仅对本节两个明确run作此获准例外；不改默认值或其他任务。先只读核父配置、无重复/活动子run及原copy/pending/source版本，再各提交一次。预计开销仍在已批准读12GiB/写8GiB/空间24GiB，复用候选不重做周COPY或重读旧周行情；实际通过与否随后记录。

**已遇到的交付锁等待。** 29日8GiB Raw于10:36:13 SUCCESS，原周Silver自动进入队列并于10:37:18启动。此后原events控制入口与Silver同时申请现有stock_period writer，控制入口在取得锁之前即报period_writer_busy退出；无Raw/Silver重算或正式文件写入。此为原唯一writer的正常互斥，不是新业务数据错误。等待正在运行的原Silver成功释放锁、只读确认本链无活动写者，再执行一次原events收尾；不得抢锁、关闭sensor或重跑Silver。若当前月通知须该次收尾补齐，先等已运行的周Silver、再收尾发原月通知、再等月Silver；业务日期及原job顺序不变。该控制操作只核原回执/元数据，仍在原收尾预算；真正的源/日期/校验/归属错误继续按失败停止规则。

#### 12.23.4 29—30日正式恢复及一次最终验收完成

2026-10-31 10:55，按本节获准范围/资源顺序完成，无生产代码或默认配置修改。总方案§10.14同步；请求、响应、原进度、失败/成功控制收尾、最终只读程序及JSON唯一见[本轮完成报告](../../reports/dg_stock_period_delivery_recovery_20261028/recovery_20261029_30_execution_20261031/rss8_resume/README.md)。下列结果取实际run/complete，不用预算估计冒充执行事实。

| 顺序 | 原job实际run | 实际范围及结果 |
| --- | --- | --- |
| 29日月Raw恢复 | 1f8507d5-f477-4ee7-82e4-06e750462397，10:31:52—10:36:13 | SUCCESS；原2742186f…97f3、3股不变；周1410/月337份Raw |
| 原通知29日周Silver | 22cbbcc2-be67-4e48-b4a1-96e85215eb93，10:37:18—10:38:54 | SUCCESS；631周期/2460539行/1893项原检查 |
| 原通知29日月Silver | d9d595e1-db39-4b1c-8b06-55ef5d9da6ba，10:39:30—10:39:56 | SUCCESS；150周期/586365行/450项原检查 |
| 30日周Raw恢复 | cd5212a1-a373-426e-9d70-896e8ffacfa5，10:41:49—10:47:04 | SUCCESS；原65269434…55701；原job产生11股，周1488/月353份Raw |
| 原通知30日周Silver | 50300d14-1abe-4671-aa8b-b48089774741，10:47:45—10:49:24 | SUCCESS；658周期/2519600行/1974项原检查 |
| 原通知30日月Silver | fdb4f5c3-75cd-4d00-8902-84654dd508ff，10:50:03—10:50:26 | SUCCESS；154周期/595229行/462项原检查 |
| 30日当前月Raw恢复 | d9b455aa-de9a-4311-b3e8-74dcc6b82329，10:52:21—10:52:23 | SUCCESS；原a08ed660…1f853、无因子历史名单；当前月1份/5576行 |
| 原通知当前月Silver | 3b5c9e66-1ec4-4a0e-9aef-ed2b32b60a44，10:53:17—10:53:18 | SUCCESS；1周期/5576行/3项原检查 |

29日恢复parent=488ae87d/root=原4d3edf1d；30日两Raw parent/root各仍原ba86b78f、99f738d8。只有前两历史Raw使用8GiB标签，冻结policy仍4GiB，最后当前月无标签；原失败run、4GiB失败子run和错误事件不改。29日原两成功页及4GiB尝试中已成功的新股周页复用，周copy/merged复用，不重新读旧周行情或重新COPY；其余月及30日历史正常按原job读取。成功源单元/页：29日7/7、30日周job23/23、最后月job1/1；不是另行实测的HTTP总调用次数。

**跨日日期实际验收。** 29日Raw1747份中source_asof为29日1409份、30日338份；周Silver630个unit用29日、当前周1个用30日，月Silver150个用30日。逐unit日期等于max(原Raw意图日,本文件source_asof)，不是identity.asof的整批最大值；Silver identity.asof原本仍保存最大日期，该字段未代替逐unit。真实原job/SQL/三checks成功证明本次跨日来源交接可运行。30日两批unit均30日，不把29日恢复直接计成30日因子已处理。

**控制收尾与互斥。** 29日两次events控制run731345d9、c6ad9f77分别撞上自动周/月Silver持锁，在取得writer前退出、无行情写入；第一次看PG无活动后到CLI执行之间，月Silver已自然启动，单看上一瞬间PG状态不能保证随后没有竞争。保留原错误及run，不将它们改成功。等两Silver均SUCCESS且lsof未见持有者，原控制6ac6e33c成功关闭29日pending；后续30日周95aa05cb、月a93d818a均在各自所有Silver成功后一次关闭，无新冲突。不抢锁、不停sensor、不重跑Silver。30日下一job仅在前批两通知均已消费且pending=0后提交。

**一次最后对账。** 原三批Raw/五批Silver的完整hash、identity、逐文件CP及事件回执吻合；后批覆盖同一路径时，其target_preimage精确等于上一批提交版本，统一核对最后1841份不同Raw/812份不同Silver的当前stat；当前四文件另核计数前/后stat以确认查询期间未变化。Silver source_version绑定其实际原Raw批次，旧批不错误要求当前已被合法覆盖的旧版本继续存在。累计Raw3589次/Silver1594次写入，原三项检查交付记录共15549项；当前四资产各三项原生检查绑定当前物化和当前版本，全部通过。

最后只做一次聚合计数当前周/月四文件（只读ts_code/end_date，不读价格）：2026-10-30周Raw/Silver各5572行/唯一代码；2026-10月各5576行/唯一代码；920306.BJ四处各1行，最大end_date均20261030。周各1条/月各5条较早end_date按原源记录保留，最早分别28/12日；没有强改截至日或声称每股都已刷新30日，也没有另做全历史/全市场明细审计。独立核验程序使用现行SPECS、物化metadata键及逐文件日期合同，数据计数前先确认全部通知消费；早先watch21仍是月sensor上一tick的pending快照，更新watch22确认后才执行最终程序，没有因此提前计数或重复执行。

**最后状态与成本。** pending=0；factor_through及两频last_refresh均2026-10-30；last_source_asof两频20261030；completed_through周2026-10-30/月2026-10。两Silver cursor无pending且after覆盖最后通知7836139（周7829519），四sensor仍RUNNING、默认配置/并发/线程/依赖未动。29/30历史Raw采样峰值约1.893/4.470GiB，均低于获准8GiB；这不是额外性能试跑。业务实际输出Raw725404679B、Silver338088943B，合约0.990GiB；不含分片临时输出/DB日志，不等于总磁盘IO或空间峰值，不能据此伪造实际总读写统计。实际范围与批准文件数一致，原12GiB读/8GiB写/24GiB空间预算保持，未扩大或另加运行限制。小型必要证据与辅助程序归档，清本轮私人临时副本；正式成果、业务staging/源/CP和持续DG日志保留。执行阶段无代码修改、安装、重跑28日或Git提交；其后的文档/证据提交见下节。

#### 12.23.5 开发收尾、精确临时清理和限定提交

对应总方案§10.15，管理员已明确授权本步。目标仅关闭本轮文档/证据状态、删除已无运行用途的本轮临时副本并提交。现有跨日代码已在4a5a5e17b；当前7份相关源码/测试SHA256仍与463项验收版本一致，本步不新增代码、配置、依赖或测试，不触发DG、源查询或Lake读写，也不重做一次最终验收。

**精确清理清单和依据。**

| 位置 | 允许删除的普通文件 | 已核依据 |
| --- | --- | --- |
| /private/tmp/dg_period_20261031_preflight | preflight.json、source-mcp.json | 与已保存的recovery_20261031_preflight证据逐字相同 |
| /private/tmp/dg-stock-period-cross-day-20261031 | baseline.json、regression.xml、successor-tests.xml、old-regression.xml | 与原实施报告保存文件或old-regression.xml.gz解压结果逐字相同 |
| 同一cross-day目录 | stock_period_raw.before.py.txt、stock_period_silver.before.py.txt | 分别等于4a5a5e17b父提交的两个运行文件，可从Git恢复 |
| 同一cross-day目录 | new-tests.xml、expanded-tests.xml | 分别14/26个用例，0失败/错误，全部用例均被最终461+2 XML覆盖，无新增失败证据丢失 |
| 同一cross-day目录 | source-reconciliation.json | 其6项内容全部等于最终文件；最终证据另有新测试指纹，临时旧文件无独立价值 |
| /private/tmp | dg-period-cross-day-commit-paths-20261031.json | 仅为已完成4a5a5e17b提交的旧暂存白名单，不是运行输入；实际提交清单在Git可追溯 |

以上12文件合计348131B。删除前再次核路径、非symlink普通文件、size/hash及上述对应依据，记录精确清单到原报告commit_closeout_20261031.json；只用unlink逐文件删除，两个目录必须为空才能rmdir。遇到未知文件、内容变化或证据不能覆盖时停止该项，不扩大搜索/删除或碰业务数据。中断后以清理记录及目标是否存在核验，只继续未删除项，不重做数据审计。

本次临时清单在/private/tmp/dg_period_closeout_candidates_20261031.json，纳入收尾记录后也删除。原必要报告、失败/成功原始记录、只读辅助源码归档及空输出流证据继续保留，不能当成业务临时垃圾。lsof已确认DG父/代码/web/daemon仍使用/private/tmp/dg_period_restart_budget_20261031/dg-restarted.stdout.txt，不删除、截断或移动；也不清理正式Lake、业务staging/源/候选/CP、共享环境或其他任务文件。

**文档及Git边界。** 更新本步最新提交状态，不改历史JSON中当时为false的git_committed_this_turn，避免篡改阶段证据。白名单仅为这两份原方案/LLD、原报告README及restart_and_budget_20261031、recovery_20261029_30_execution_20261031两组报告和本步收尾记录；逐文件展开，检查未含敏感配置、运行环境、源响应正文、Parquet或其他工作区修改。默认且只在当前dev-interface暂存/提交，不新建分支/worktree、不推送。索引若已有无关暂存项则停止，不清空他人索引；提交前cached路径必须精确等于白名单，执行cached whitespace检查，提交后确认这些目标已干净、无关改动仍在。

正常及一次中断/响应不确定后的复核只读本地小文件、XML、Git历史和指定日志句柄，预算读32MiB/写8MiB/临时空间8MiB，不含任何数据集读取。验收为副本/覆盖依据、清理读回、源码指纹、报告数字与实际8成功run的既有证据对账、文档完整性/新链接及限定diff检查；不重复463项测试或运行补数。提交保存本步结果，最终哈希以Git为准。

**实际清理完成。** 上表12份文件348131B逐项依据复核通过，新增临时清单2108B也纳入本步记录后删除，共13个普通文件350239B；两个目录均确认空后rmdir，目标不存在的读回检查通过。临时旧指纹与最终证据的差异仅为最终文件新增new_test项，其余6项完全相同；原测试失败XML仍在既有gzip证据中，0失败的中间XML用例全部被最终XML覆盖，未清除失败证据。7份相关源码/测试指纹保持，无新代码/测试或正式DG操作。实际清单、Git边界及检查记录在[收尾记录（附件已清理）](../../reports/dg_stock_period_delivery_recovery_20261028/README.md#report-attachment-cleanup-20261103)，随本次收尾提交保存；JSON中的历史提交前状态不改。

<a id="period-week-20261106"></a>

### 12.24 11月6日当周全市场补齐

原周任务`26d677ef-76a8-4834-97ad-f1fc8e2bb762`以`period_adjacent_factor_missing`失败。相邻因子现已齐，原月任务已消费11月6日因子并刷新20股两频历史。当前周刷新仍为11月5日。按`_daily_work`核对，因子水位已到原意图日，当前上市5,579只与基线无增减，唯一应补周期为`2026-11-06`。现有当周Raw大小450,278字节，11月5日同一周的成功全市场源单元为5,573行、1页。四个周月任务均无在途，共享写锁空闲，Lake与staging同设备。

正式范围为一个周源单元（`freq=week, trade_date=20261106`），原每页6,000行、最多3次请求尝试，实际页数按源结束条件。只合并当周Raw一个文件和生成同周Silver一个文件，复用原候选、原校验、原逐文件提交和交付通知。旧月交付待办已消费，原周流程先用原物化和检查收尾。使用原默认资源值。正常提交一次原周任务，响应不明先按原分区和父任务核对。中断后只观察当前run和本次交付记录，确需续跑时由原入口复用已完成源和候选。最后只对本周两份文件做定点行数和源日期计数，并核对原检查。拒绝额外待办、历史股票范围或新来源窗口。

在`/Users/congming/github/goldenshare/lake_console/orchestrator`工作目录，通过正式本机Dagster（`/Users/congming/.goldenshare/dagster_home`）提交一次`launchRunReexecution`，参数为上述父任务、`FROM_FAILURE`和`useParentRunTags=true`。提交命令为`curl --max-time 25 --fail-with-body --silent --show-error http://127.0.0.1:3000/graphql -H 'Content-Type: application/json' --data-binary @/private/tmp/dg-nov06-remaining.9Py2SS/week-resume-request.json -o /private/tmp/dg-nov06-remaining.9Py2SS/week-resume-response.json`。保留原11月6日意图、原分区和三项原检查。Silver传感器按新通知接续，核验结束后清理本轮临时目录。

**执行结果（2026-11-08，北京时间）。** Raw续跑`c4d431bf-3e9a-4f7d-9d20-5bfc5c98da98`于16:44:26至16:44:35成功。源单元一页5,574行，源文件及转换文件合计1,584,342字节，提交一份450,792字节的正式周文件。原流程确认了上一批月线待办。Silver任务`04db434d-5cd0-4c26-849b-e618da7dd2af`于16:45:33成功，16:46:25原传感器确认交付通知`7950625`。

两份正式周文件各5,574行、各5,574个唯一键，其中5,573行`end_date=20261106`，各有一行保留较早源日期。两层各三项原检查全部通过，分别绑定物化`7950627`及`7950663`。周线全市场刷新和已闭合周均推进到11月6日。本次新周Raw已提交且待办标记为已消费，后续原Raw流程继续确认该待办。

<a id="period-week-month-20261109"></a>

### 12.25 11月9日股票复权周线和月线恢复

**当前依据。** 原周Raw父任务`e5b75b49-def9-4dc2-923b-9fbd9686e2b3`在`_validate_candidates`触发4 GiB内存上限，冻结执行`a862748e810f776283ff5f557ea9992326d325b0d3618981efb371587a22d54f`仍为`download`且没有正式提交记录。原月Raw父任务`5c777655-9cd7-498d-a1d0-6e2c1b8bc277`要求先恢复该周任务。周回执截至11月9日，覆盖3,938个代码，少于同日Silver股票日线的5,573个代码。`capture_unit`复用已完成回执，`run_period`原规则只根据回执日期决定是否进入下一轮取数。`assemble`的`copy.json`绑定源文件路径和版本，旧候选不能用于新源。

**重取与核验。** 按现行`capture_unit`、`HttpPage`、原冻结上市集合和策略，仅重取`freq=week, trade_date=20261113`全市场单元，使用原`run_period`为第1轮构造的请求身份。只在原执行的staging下形成新源回执。新回执须包含同日股票日线的全部5,573个代码，这些代码的`end_date`须为11月9日。其余行按原合同核对，任何截至日期晚于11月9日、频率或周期不符、重复键及与原5股周历史当前周期冲突均停止。既有5股周历史回执由原任务复用。记录新旧回执指纹、实际行数、差集和重叠核验结果，不把抽样当完整性。

**登记与并发。** 仅在原`writer`锁内登记，核准原父任务/分区、共享待办、执行身份、设备、控制文件版本、待发布清单及无正式提交，确保没有同批活动Dagster任务。原`manifest`只新增该单元的`capture_rounds["week:2026-11-13"]=1`，不改变`identity`、`identity_hash`、旧源回执、`daily.json`或水位。先原子登记新取数轮次，再在同一staging内将旧`build/week`原子移到本执行的证据子目录。若在两步之间中断，旧`copy.json`的来源绑定会拒绝新源。续跑辅助入口核对新回执及旧`copy.json`的版本，只补完尚未执行的移动。移动完成后如出现新候选，不移除该候选。原失败运行及旧staging证据保留。无代码、配置合同或调度改动，无额外正式Lake写入入口。

**范围与性能。** 新全市场周源一单元，原策略每页最多6,000行、单响应16 MiB、每页最多3次请求尝试，分页按原终止条件。与已存在的5个周历史源一起验收，周Raw续跑还需按冻结意图请求5只股票的月历史；月Raw随后只请求当月全市场，未出现意图范围变化才允许继续。旧周候选回执有1,651个周期、3,614,630行，旧周输入1,650份共299,515,554字节。原范围索引定位到月线合并及当月目标共395份既有输入，合计72,884,497字节。上述为输入压缩大小和旧候选行数，重取后按实测记录。续跑的候选、原校验、逐文件原子提交、DuckDB 3 GiB及两线程、原磁盘准入继续生效。6 GiB是本次进程内存上限，旧同类采样5.79 GiB仅供参考。正常只重取一次周全市场及各启动一次周/月原任务；中断仅核对源回执、复制清单和已提交文件后继续剩余工作。收尾只读取四个当期文件的日期/键汇总和关联运行的检查记录。

**操作和验收。** 在`lake_console/orchestrator`工作目录，通过已有`.venv/bin/python3 -B /private/tmp/dg-period-20261109.eyL2KM/control.py`运行`capture`、`register`、`week`及条件满足后的`month`。前两步只写原执行staging。后两步通过正式本机Dagster（`/Users/congming/.goldenshare/dagster_home`）的`launchRunReexecution`执行`FROM_FAILURE`，分别继承上述父任务，`useParentRunTags=true`，仅额外带`goldenshare/stock_period_rss_limit_gib=6`。进入月Raw前确认周Raw原检查、关联两频Silver交付及11月9日周文件读回；最终确认月Raw和Silver检查、四个当期文件和刷新水位。调用失败或响应不确定先查原父子任务和提交记录；出现覆盖、源冲突、内存、前像或检查错误则保留现场，禁止盲目重提。辅助逻辑先用`/private/tmp`的无网络小样本验证重取身份、日期覆盖、冲突拒绝和两步登记恢复。结束删除本轮控制脚本及临时验证资料，保留业务回执和正式运行记录。

**实测停止点（11月10日16:12，北京时间）。** 隔离验证覆盖正常覆盖、缺代码、晚于目标日、单股历史冲突、正常登记和登记中断恢复。正式仅重取一页当周全市场源，共5,573行、缺代码0、晚于目标日0、重复键0，新回执hash为`8aa3581999cf492083c5afc15ae69d5ce02435eb8ac805ddb85e48789964f71e`。`603112.SH`及`603680.SH`各在新源有1条当周行，但原单股周历史各只到11月6日，当周均为0条，违反原`period_history_coverage_conflict`门禁。原执行仍为`download`，`capture_rounds`未登记、原`build/week/copy.json`仍在、无正式提交。临时控制脚本与隔离夹具已清理。

**扩大重取范围待确认。** 原`run_period`的轮次按频率和周期识别，单股历史属于`week:None`一组。需以相同冻结意图和新周历史轮次重取`000531.SZ`、`002555.SZ`、`300760.SZ`、`603112.SH`、`603680.SH`五只股票的周历史，保留五份旧回执。五份旧源各一页，合计3,563行，预计新一轮五个源单元，仍以原分页、单页及重试上限为准。新五股数据只验收同周行、截至日期、主键及与已保存全市场源的重叠业务字段。通过后在原写锁内一并登记周全市场及五股周历史的新轮次，再沿上节原候选归档、6 GiB周Raw、关联Silver、月Raw和月Silver执行。若Tushare已切换到后一天或两类源仍冲突，则保留已取得的回执并停止发布。

**管理员确认。** 11月10日已明确允许上述五股周历史重取。复用已验证的全市场回执，原`capture`只重取这五个周历史单元，`register`对两类回执和当周全部业务字段复核后一次性登记`week:2026-11-13=1`和`week:None=1`。登记前冻结旧`copy.json`指纹，原子归档到本执行的`recovery-20261109/week-round-0`。正式命令、其余任务范围和单次6 GiB设置同上。

**五股周历史核验与周Raw提交。** 五只股票各返回一页，依次为1,633、756、414、316、446行，合计3,565行，均覆盖至11月9日。五条当周记录与全市场回执的全部字段一致，全市场相对同日股票日线缺失0个代码。无网络验证通过正常覆盖、后一天源日期、重叠记录冲突、单股缺失及登记后归档中断续做。已登记两项周轮次，旧候选以原`copy.json`哈希`2f0d41ffdb900f5a8551aac44354bfcbb3beb75042bd082106a1b4b73293e279`归档。以6 GiB续跑原周Raw，Dagster运行编号`825b0fec-e9e1-4e3c-ac32-6e27b86e0e1f`。本次周任务的文件回执覆盖1,651份周文件与395份五股历史所涉及的月文件，原候选校验和逐文件提交全部完成。目标周Raw为5,573行、5,573个唯一股票代码，全数截至11月9日。

**周线交付已确认。** 周Raw原运行成功，当周原三项检查均绑定物化`7987987`并通过。原传感器确认周线通知`7987985`和五股月历史通知`7987984`。对应Silver运行`82ab903b-4c23-414e-af98-bd23fa6a9333`、`cf590914-d296-4adf-9868-fb0f373c3d86`均成功，分别确认659份周文件及1,977项检查、155份月文件及465项检查。当周Silver 5,573行、5,573个唯一代码，全部截至11月9日，三项原检查绑定物化`7994559`。随后才提交原月Raw续跑`37b0dfed-4cb0-40eb-bbbf-506ddd2eb27f`，同样使用单次6 GiB上限。

**月线及最终对账。** 月Raw续跑于16:34:53至16:35:01成功（北京时间）。冻结意图仅当月，未带单股历史代码。原源请求`freq=month,start_date=20261101,end_date=20261130`返回一页5,574行，回执哈希`8fdc09e3b6a6dc76ad24235fd4ec5ec730a6d947a223f1b513da8e184960fc67`。月Raw写入一份当月文件，原三项检查绑定物化`7994614`。原传感器确认通知`7994612`，Silver运行`e7994ebd-ce70-4691-9573-206b7910aeae`成功，当月原三项检查绑定物化`7994650`。月Raw和Silver各5,574行，5,573行截至11月9日，均保留`002623.SZ`一条源日期为11月2日的记录。四份文件按同日股票日线5,573个代码对账，缺代码、重复代码和后一天数据均为0。周、月全市场刷新水位和复权因子水位均到11月9日。

运行日志记录的周、月Raw进程内存最高采样值分别为4,601,495,552和492,748,800字节，均低于本次6,442,450,944字节上限。原周待办已由月任务确认，原月待办已标记消费，后续由原Raw流程例行确认。保留正式回执、归档候选及运行记录，本轮控制脚本和验证资料已清理。

<a id="period-week-month-20261110"></a>

### 12.26 11月10日股票复权周线和月线恢复

**目标和授权。** 11月11日管理员确认沿原任务恢复本周、本月和原月线任务冻结的14只股票两频历史。两条失败父运行是月线 `f0449c22-dec1-45e8-a421-631a2a3722a6`、周线 `db725fca-0853-4e67-a1a6-868f0a88c01d`，配置均显式指定业务日11月10日。待办仅月线执行 `b6c0c8031caaa0247c06943610243a5e2fd088b5bd315a9e251378639f90a5fe`，阶段为 `download`，无候选和提交。原任务已有13份周线历史回执，11份最大来源日期为9日，另两份为10日。MCP单股检查确认 `688827.SH` 的两频当前记录和两只旧回执股票的当前周记录已到10日。本步使用原代码和配置，不实施第13节的新流程。

**取数和登记。** 复用 `stock_period_source.capture_unit`、`HttpPage`、原冻结的上市集合、身份映射和取数策略。原月线执行的周线单股历史使用 `run_period` 既有 `week:None` 第1轮请求身份，月线历史和当月全市场沿第0轮；原周线当期沿其11月10日确定性请求身份预取，须先核对现行参考集合和正式连接参数与原任务一致。总计14个周历史、14个月历史、2个当期全市场取数单元。仅在对应执行的staging保存回执，原页和回执保留。对照11月10日Silver股票日线5,573个代码，按身份映射核对当期每个应有代码恰有一条计算截至10日的记录。单股历史按原字段及主键合同核对，两类源的重叠业务行须一致；来源晚于10日、日期或覆盖不符、出现冲突时不登记取数轮次。锁内复核冻结身份、现行待办、旧回执、设备、无候选及无活动任务后，原子登记 `capture_rounds["week:None"]=1`，原 `daily.json` 和业务日期保持原样。中断按已完成源回执续作未完成单元；登记前重新核对完整回执，登记后只读取原记录确认。辅助程序只放 `/private/tmp`，先用无网络小样本验正反覆盖、来源日期和重叠冲突。

**执行范围和预算。** 执行前用原范围索引和文件版本核到周Raw 1,506份、297,387,358字节，月Raw 358份、71,969,019字节，分别覆盖1997-02-28起和1997-02起的选中周期。Silver适用周660份、月155份，现有文件合171,777,617字节，对应Raw读取范围合261,840,981字节。这些是现存文件压缩大小。新回包日期与原范围取并集后再次核定；若超出现有范围，先说明额外分区和开销。原周线当期还会单独更新同一份周Raw和周Silver。两频正式任务沿原6000行页长、单响应16 MiB、每页最多3次尝试、单次请求30秒截止、每源单元128 MiB、每执行工作目录32 GiB的现有策略。已有原月线任务的本次Raw范围小于11月9日完成的1,651周和395月，后者实际最高进程内存采样为4,601,495,552字节。月线原任务采用同一现成单次6 GiB运行上限，DuckDB仍3 GiB、2线程。周线独立任务只做当前周期，沿原4 GiB进程上限。候选、旧输入、原子替换和原检查由原任务处理。正常每个源单元取一次、两个Raw原任务各续跑一次；中断恢复仅处理未完成单元或文件，按同一范围计入尚未完成的源页、候选生成、校验及提交。最后一次验收只聚合四份当前文件并读现有回执和任务记录，无全历史再次读回。

**命令、失败和验收。** 工作目录为 `lake_console/orchestrator`，正式实例为 `/Users/congming/.goldenshare/dagster_home`。通过现有 `http://127.0.0.1:3000/graphql` 按§12.8调用 `launchRunReexecution`，两步均用 `FROM_FAILURE` 和 `useParentRunTags=true`。仅月线任务增加已有标签 `goldenshare/stock_period_rss_limit_gib=6`。月线Raw和其绑定的原检查、两频Silver关联交付成功后，核对待办已消费且无冲突写者，再提交周线父运行；周线Silver由原sensor接续。确认四份当期文件的实际截止日、代码集合和已通过的检查。响应不明时先查运行和原回执。出现新旧源冲突、文件版本变化、内存或检查失败，保留证据与已提交文件，停止后续提交。

**实际执行和验收。** 30个源单元各返回1页，响应和暂存CSV合计5,887,084字节。两份当期源各5,575行，覆盖5,573个应有代码，重叠行冲突和晚于11月10日的记录均为0。实际入选历史周期与核定范围一致。08:26登记原月线执行的周线历史第1轮。第一次GraphQL提交的返回字段校验失败，确认未创建子任务后纠正，月线父运行只创建了一个有效续跑。运行时间为11月11日北京时间。

| 步骤 | 运行编号 | 成功时间 | 交付文件 | 通过原检查 |
| --- | --- | --- | ---: | ---: |
| 月线Raw及两频历史 | `186c8218-ee9f-4db6-bf96-8f5a98fe749f` | 08:35:51 | 1,864 | 5,592 |
| 月线Silver | `1f98dd66-5da2-44fc-b861-d259c7c12d34` | 08:36:59 | 155 | 465 |
| 周线Silver历史 | `ca567611-d4f8-4370-8d0c-86380e221b69` | 08:40:00 | 660 | 1,980 |
| 周线Raw当期 | `6328ef45-875c-4b37-9aa8-0e12282abe06` | 08:41:51 | 1 | 3 |
| 周线Silver当期 | `73658c5b-6c8f-4c49-b58f-ae31c58e2cc7` | 08:42:03 | 1 | 3 |

三个Silver交付均有原完成回执。四份当期文件各5,575行和5,575个唯一代码，5,573个应有代码均恰好有一条 `end_date=20261110` 的记录。业务键重复和晚于10日的行均为0。周、月刷新日期及复权因子处理日期均到11月10日。月线Raw待办已由周线Raw原入口确认，周线Raw待办已标记消费，由后续原任务例行确认。无代码、配置或调度变更。

<a id="stock-period-daily-then-history-lld"></a>

## 13. 周月线当期日更与复权因子变化历史回刷分开

### 13.1 目标、现行依据与影响面

对应[原方案第10.19节](dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md#stock-period-daily-then-history)和[月线差异](dagster-stock-monthly-raw-onboarding-low-level-design-v1.md#monthly-daily-point-readiness)。本节是新流程设计；当期Raw/Silver、独立复权因子历史回刷和单频退市清理已分别按第13.11至13.13节完成第2至4阶段开发；第5阶段人工维护与旧实现清退已按第13.17节完成，第6阶段整体验收及正式切换亦已完成，结果见第13.19和13.21节。设计落实已确认的20:00起检查、周五与自然月末单点、当期全市场先日更、复权因子变化股票独立回刷、退市清理按频率独立触发、失败整批重跑。旧实现已按第13.7及13.17节清退，本次交接不恢复或调用旧入口。第12节只用于追溯切换前的实现和旧任务。

改造前经CodeGraph核到`evaluate_daily_sensor → _execute_daily_locked → _daily_work → run_period`及共用写入检查。旧实现中，先拿到写锁的Raw job比对相邻Silver复权因子，把复权因子变化与新增上市代码合并进`daily.json`的待办，再复制到本执行`manifest.json`。它处理两频历史和本频当期，失败会挡住另一频。11月10日19:30月线先跑，14只中13只复权因子变化，`688827.SH`当天上市。新股周线历史请求空回包，当月全市场请求尚未发出。Gold股票日线前复权已有成功后再触发回刷的实现，日期、名单摘要、批次随Dagster运行保存，检查记录保存完成事实。11月10日日线回刷`4a2b5574-54aa-46dc-b890-760872ac071a`通过，记录13个代码。周月线复用这个编排方式，源仍为Tushare复权周/月线，日线的本地复权计算不进入本链。

| 部位 | 现有入口与本轮设计影响 |
| --- | --- |
| 两个Raw sensor | `sensors/raw_stock_weekly_update_job_sensor.py`、`raw_stock_monthly_update_job_sensor.py`及`stock_period_update.evaluate_daily_sensor`，只做调度与提交。源预检放在`defs/source_readiness/`下，由两频共用同一日期及代码覆盖检查。复用[股票日线现有检查](../../orchestrator/src/orchestrator/defs/checks/stock_daily_checks.py)中按上市状态及全日停牌计算应交易集合的规则，提取同一份集合计算供周月线预检与Raw复核使用 |
| 源与Raw | `run_contracts/stock_period.request_params`、`stock_period_source`及`stock_period_update`区分当期单点与单股历史，复用现有HTTP限制、全字段校验、DuckDB和候选提升；删除`bootstrap/stock_period_history.require_pending_delivery_before_write`和共享待办，其他删除位置见§13.7 |
| 独立回刷 | 参考`sensors/gold_stock_daily_qfq_factor_repair_job_sensor.py`的日期、摘要、上游批次及`ops/gold_stock_daily_qfq_factor_repair.py`的重算和结果登记；周月共用`stock_daily_qfq.build_stock_daily_qfq_factor_changed_codes_sql`识别复权因子变化，保持周月自己的源和候选逻辑 |
| 独立退市清理 | 采用§13.8的成功事件监听，同一个清理job接收频率参数，周Raw成功后清周，月Raw成功后清月 |
| Silver与运行观察 | `stock_period_silver.evaluate_update_sensor`、`resolve_update_sources`及新`asset_guards/stock_period_delivery.read_completion`核对实际Raw交付及合法后继，继续按原检查处理实际变化。源等待、日更成功、回刷失败使用Dagster已有的sensor、运行及检查记录 |

两个Raw、两个Silver的正式资产、job、物理路径、21列、精度、已确认代码身份、Silver历史下限及原文件检查均保持。历史文件中的既有源日期保留。确认退市沿原身份及准入合同，由§13.8独立job只清理配置指定的一频；换码保留指定范围维护入口。范围限本工程周月链，Prod、股票日线前复权和其他数据集的实现保持。

### 13.2 当期预检及正式日更

1. 两个Raw sensor在上海时间交易日20:00起分别检查。先验证正式挂载和本频当天是否已提交或完成，再核对股票生命周期和当日最终停复牌事实的验收及实际文件。从`silver_stock_lifecycle`按意图日和现行证券身份合同确定在市股票，扣除`silver_stock_suspend_daily`当日确认的全日停牌股票（`suspend_type=S`且`suspend_timing`为空）。扣除后的代码是当天必须有数据的集合。当天上市和盘中停牌股票仍在其中。已确认全日停牌的在市股票允许有数据，也允许缺席。前置未齐、身份不明或集合为空时等待，源请求为0。已验收的空停复牌分区表示当天没有停复牌事实；分区缺失时等待。应更新集合的计算无需等待股票日线落盘。源未齐的频率按原sensor间隔继续检查当天，达到条件的频率可独立提交。同日自动提交沿现有按频率和日期去重的run key。两频sensor及手工历史入口均取消旧建库交接状态门槛。
2. 预检和正式取数都用`stk_week_month_adj`，全市场请求不带`ts_code`过滤。周线`freq=week, trade_date=自然周五`，月线`freq=month, trade_date=自然月末`。以11月10日为例，分别为`20261113`和`20261130`，首请求`limit=6000, offset=0`。预检只取`ts_code,trade_date,end_date`，正式请求原21列。输出`trade_date`必须命中请求的周期标签，输出`end_date`是计算截至日。对当天必须有数据的每个代码，源端必须恰有一条目标周期记录且`end_date=意图日`。代码缺失、仅有较早记录、重复或同数换码均不触发。已确认全日停牌的股票是可选项，返回该周期的有效记录时接受，计算截至日可为当天或较早日期；缺席也可通过预检。在市身份及源记录合法性仍按原规则核对。错误响应、准入行出现未来日期或返回范围不明时不提交。检查结果记录两个输入的验收版本、当天日期、周期标签、计数和差异样本。
3. 11月全市场真实三列测试中，月末单点与整月范围各5,575行，三列差集为0。另一组真实单股样本中，2026年10月`trade_date=20261030`返回0行，`20261031`返回1行。2020年2月范围会混入`20200228`和`20200229`，本次当期合同选自然月末单点，既有历史文件维持原样。上线前只核当期目标是否已经使用约定标签；发现旧标签先核准具体分区的处理，日常任务不顺便清理旧数据。
4. Raw job按Dagster配置中的意图日和频率执行，用已验收的当日在市和最终停复牌事实，按同一规则复核正式21列响应。全日停牌股票有有效返回就按业务键合并，已有更新的记录按来源日期保护。源未返回时保留已有记录，原来无记录也无需补造。预检之后源若变动，以正式响应能否通过同一覆盖、日期及字段检查为准。只交付本频当期一个文件，因子对比和单股历史请求为0。当期目标尚未存在时，用本次验收通过的全市场响应新建。候选校验及文件提升复用现有写入能力。另一频源未齐或失败不挡住已就绪的一频。
5. 按现有交易日历和完成证据区分当天刷新及周期最终交付。已闭合周、月的缺口按原周期口径识别，切换前逐笔核对旧执行和未交付周期。较晚日期成功只证明实际完成的刷新。闭合周期补齐、跨日失败和旧任务交接按§13.7处理。

### 13.3 回刷的触发、名单与完成条件

1. 参照日线前复权的成功触发方式。任一Raw日更成功可检查另一频的同日完成记录。自动回刷只认同一业务日两条当期Raw任务的完整成功交付和绑定的原检查，按周、月固定顺序组成上游批次，按复权因子日期与上游批次去重。两频先后顺序均可。只有一频成功、任一任务失败，或收到闭合周期补齐、退市清理与回刷自身的交付时，均不触发自动因子回刷。Silver按实际Raw交付独立接续。若较新Raw先于Silver到达，按现有`resolve_update_sources`核验实际版本、合格检查和合法后继交付。
2. 沿用现行Silver股票复权因子的生产和验收合同：生成候选时已检查日期、主键、复权因子值及应有股票覆盖，通过后才能发布。选股复用现有`build_stock_daily_qfq_factor_changed_codes_sql`，比对相邻开市日的两份正式Silver股票复权因子文件。名单只包含相邻两日均有复权因子记录、按现行身份合同归为同一证券且复权因子发生变化的股票。当天新股首根周、月线随当期日更交付。按日线前复权现有做法，Dagster运行配置保存复权因子交易日、名单摘要和上游批次。回刷按交易日历重算名单并核对摘要。摘要不一致则报告范围变化。任务只按`ts_code + freq`请求名单内股票的两频完整历史，不传`trade_date`、`start_date`或`end_date`，沿用`limit=6000`、`offset`分页及原字段、日期、范围和内存门禁。无变化以Dagster检查记录零回刷，无历史源请求、文件变更或Silver接续。
3. 回刷通过原检查后，Dagster记录实际名单、摘要、上游批次、交付文件及检查结果。意图日仍是识别复权因子变化的交易日。历史回包按实际计算截至日校验和记录，跨日交付逐文件按§12.22已确认的日期语义处理。将通过校验的源`trade_date`映射到对应周、月文件，按`(ts_code, trade_date, freq)`更新或新增记录。同一键比较各自的`end_date`，保留已交付的较新记录，其他合法记录仍按各自日期合并。常规复权因子回刷以本次通过原源合同校验的历史回包为输入，源未返回的已有业务键保留。回刷只合并已存在的全市场周期文件。所需历史文件缺失时，在生成候选前报告周期并停止本批，由全市场周期补齐入口处理。通过全市场覆盖检查的当期日更或指定周期补齐可新建对应文件。回刷失败保留原运行事实，后续整批重跑，当期日更仍按自身条件执行。

### 13.4 Dagster交付与整批重跑

新日更、独立回刷、退市清理和Silver用Dagster运行配置、物化及检查记录意图与结果，sensor cursor只存小型调度信息。股票日线前复权回刷已采用按配置重新计算、从头处理的方式，周月线沿用此方式。

- 失败后使用原业务日期、频率和范围提交完整新运行，从第一步重新取源和生成候选；回刷重算名单并核对原摘要。中途已写好的正式文件保留，下次按业务键重新合并，不重复插入，并保护同一键上来源日期较新的记录。Silver失败也从原业务范围的第一步重做。
- 候选只放正式暂存区，完整校验后在同一设备逐文件原子替换，沿用现有文件检查和写后核对。每次只处理本次实际目标，不读取旧运行的清单、候选或逐文件位置来跳过步骤。
- 由当期Raw资产和两个独立op把本次用途、业务日期、频率、上游运行和实际输出周期保存在Dagster原生记录中；旧`report_file_events/report_completion_events`在首次建库调用方迁移后删除；逐文件记录实际来源日期，原检查绑定对应物化。全部应交付文件和检查齐全、运行成功后，才有完整交付结果。部分写入或部分检查通过保留原事实。
- Silver按本频完整成功的Raw交付接续，以对应物化、原检查及实际文件确定输入。原`resolve_update_sources`对合法后继Raw的处理继续适用；一次复权因子回刷交付两频时，两条Silver链各处理本频范围。Silver历史下限和已确认的来源日期规则继续适用：每份文件分别取业务日期与该份Raw合法实际来源日期的较晚者，来源日期不得晚于完成时的上海日期。
- 当期日更同日失败可用原业务配置手工整批重跑，自动提交沿用同频同日去重。跨日重取时源已更新到次日的，次日按自己的业务日期交付，原日保留失败或未交付事实。未完成的复权因子回刷仍按原复权因子日期及原名单摘要整批重跑。切换和原日未触发回刷的处理见§13.7。

### 13.5 配置和性能

| 项目 | 依据与本设计范围 |
| --- | --- |
| 最早时刻与作用域 | 管理员指定北京时间20:00，仅两条股票复权周/月Raw日更sensor；配置与现有周月时间策略集中，统一使用既有时区和60秒检查间隔，日志与跳过原因同步显示。上线以现有Dagster代码位置加载生效，复用现有sensor分类与配置来源。人工指定周期和历史回刷使用各自执行条件 |
| 预检成本 | 每频每次符合条件的sensor检查请求当天目标周期的三列，当前样本各1页。每个tick只投影当日在市和当日最终停复牌事实，集合核对限当日。源未齐时由后续tick再次核对，已有本频当天提交时停止预检。按现有60秒最小间隔，单页情形两频合计每分钟最多2次预检请求。预检只在本次tick剩余时间内尝试，分页共享这段时间；正式job的单请求重试不在sensor内执行。沿用现有30秒单请求截止、16 MiB单响应上限和限流。满6,000行时按既有分页规则确认完整性，若在该次检查允许的时间内无法确认，则明确记录无法证明齐备，后续tick重新核对。满页正反例和超时耗时先做隔离验证；实际源分页无法证实时停止该范围的自动提交。正式下载和回刷的页数及重试另计 |
| 当期写入 | 两频各1个Raw文件及各1个Silver文件。11月9日正式当期实测约5,573至5,574行每层，仅是样本；11月月线三列试查5,575行。正式请求沿原页长、超时、重试及响应、磁盘、内存门禁。合并和校验只针对该周期，无单股历史调用；最终按两频四文件投影代码和日期对账一次 |
| 历史回刷 | 若有K只复权因子变化股票，一次完整运行覆盖2K个单股频率单元。11月10日样本K=13，即26个单元，HTTP实际次数按各单元页数与现有重试策略算。F为该批通过校验的源记录映射得到的去重Raw文件数，周、月分别按实际`trade_date`计算。只处理F个选中目标，复用本次文件写前检查，无全量版本目录或逐文件Dagster查询。预算按实际选中文件的大小和行数、源每页限制、现有DuckDB及暂存空间、最多F次逐文件替换估算。11月9日原恢复实测周1,651份、月395份，只作容量参照，不当作新批上限或耗时。无法核定容量时不自动扩大范围或上调内存 |
| 整份周期文件补齐与Silver接续 | 每次显式指定一频一分区，按一份Raw和一份Silver计入源请求、合并及写后核验。补建整份文件时，在Raw job内一次规划该周期截至业务日期的交易日范围，批量读取对应停复牌分区及所需生命周期字段，计算每股最后应更新日。按实际开市日数和文件大小计入预算，sensor保持当日范围。Silver按批次集合读取检查及物化，每个适用文件用既有1项物化和3项blocking检查作为证据。回刷的Silver最多覆盖本批F个Raw周期，实际按Silver历史下限裁定。部分交付的原始证据保留，完整批次单独登记。避免按文件循环查Dagster |
| 整批重跑与最后验收 | 一次中断加一次整批重跑，两次名单核对后均为K只时，历史源单元最多合计4K；实际HTTP次数另按分页与重试计算。两次源回包映射文件数分别为F₁、F₂，Raw候选生成和替换各最多F₁＋F₂次，仅当两次目标集合相同才可写成2F。按每次实际输入、候选和写入分别核算，暂存空间计入尚未清理的本任务候选与spill。最后按本次运行的物化、检查及当期覆盖计数对账，只读实际涉及文件 |

月线源标签与Tushare接口以[官方doc365](https://tushare.pro/document/2?doc_id=365)及§13.2真实样本为依据。Dagster业务日期、运行与事件记录边界参考[实例配置](https://dagster.io/docs/deployment/oss/oss-instance-configuration)。

### 13.6 开发和验收顺序

1. 先验证两个当前周期的真实三列请求及有界响应。隔离覆盖20:00前、非交易日、在市或当日停复牌事实未验收、已验收的空停复牌分区、整日与盘中停牌、当天上市、必需代码缺失、来源日期较旧、同数换码、重复、身份或周期不符、超时及满页。分别验证全日停牌股票返回当日记录、返回较早记录和无记录时，必需集合齐全均可触发；正式写入分别验证按键合并、保留已有记录和无需补造记录。整周全日停牌且源首日无记录的样本须能正常触发。首查未齐、随后一次检查齐备时应自动提交，当日重复tick只提交一次。验证周五和自然月末单点、两频预检三列与正式21列使用同一坐标、源在预检后变动时复核，以及新股随当期入库。
2. 隔离验证只有一频完成、两频完成顺序颠倒、Raw已通过而Silver仍待接续三种触发情形。验证无复权因子变化的结果、13股与新上市股票范围、名单摘要不一致、较新Raw被Silver按原规则合法接续。用三份候选验证写完第一份后中断，下一次重做三份并对账。另覆盖原子替换后登记失败时整批重跑、同一业务键保留较新的来源记录、回刷失败后次日当期可启动，以及原物化与检查的绑定。另验同日失败重跑、跨日源已前移、原日未触发回刷后按原复权因子日期补齐、两频齐备后的整批结果，以及Silver失败时独立重跑。某一频源未齐不会拦住另一频提交。退市清理按§13.8分别验收。
3. 复用现有源合同、文件校验、Dagster物化与检查相关测试。按§13.7替换只验证旧续跑的用例，补入口和引用清退检查。正式验证按独立批准的日期先只读核三列真实覆盖、响应时间和预算，再分别验证一批当期Raw/Silver及一批受限回刷。保留错误证据，不以sensor触发或进程退出码代替文件和检查验收。

<a id="stock-period-legacy-removal"></a>

### 13.7 旧实现清退清单

新日更、独立历史回刷和Silver接续在同一版完成替换。旧实现可沿第12节追溯。下表按现有调用关系列出删除的函数或分支、要迁移的调用方，以及继续使用的校验。文件路径相对`lake_console/orchestrator/src/orchestrator/defs/`。

| 代码位置 | 删除或改写 | 迁移与保留 |
| --- | --- | --- |
| [`stock_period_update.py`](../../orchestrator/src/orchestrator/defs/stock_period_update.py) | 删除`daily_state`、`daily_handoff_ready`、`_daily_work`、`_consume_daily_files`、`_execute_daily_locked`、`execute_daily`、`handoff_bootstrap`和仅供交接调用的`bootstrap_watermarks`。`evaluate_daily_sensor/deliver_asset`已按第2阶段替换，继续清零旧19:30入口、共享待办和`baseline.status=ready`准入。`_daily_intent_date/_current_period_anchor`当前已退出，不得为旧时钟推断或旧文件目录证明归属恢复它们。清掉`_runtime_rss_bytes`为旧父运行或交接续跑取覆盖值的分支 | 两个Raw sensor、两个Raw资产和日更job改接§13.2。保留正式交易日历事实、分区检查、活动写入保护和现有资源限制；闭合周期走已经接通的`source_readiness/stock_period.period_input_days/load_period_universe`。旧`calendar_days/period_bounds/close_day/source_final/no_trading_period`仅供旧日更和交接调用的实现按第13.14节清零，不因名称里有日历而保留无调用代码。移除`daily_periods`读取旧水位和自动补欠账的逻辑。独立回刷已由`stock_period_history_repair.load_factor_changed_codes`直接使用原相邻日股票复权因子比较SQL；删除只被旧日更/交接调用的`factor_changes`，保留该共用SQL。确认退市的规则移到§13.8独立单频清理，换码沿已确认身份规则指定处理。移除旧上市名单差异与复权因子变化、新股合并入共享待办的代码 |
| [`bootstrap/stock_period_history.py`](../../orchestrator/src/orchestrator/defs/bootstrap/stock_period_history.py) | 删除`history_work_identity`、`ensure_history_pending`、`frozen_history_work`、`ordered_pending_work`、`require_pending_delivery_before_write`以及`verify_rss_resume`的旧交接续跑。移除`run_period`供混合日更和旧`history`/`upsert`调用的执行分支，以及`awaiting_units/capture_rounds`重试旧日更欠账的分支。`files_complete`只删除旧日常接续用途，首次建库按第13.14节保留同一次执行的文件完成及事件核对。`_finish_files`、`completed_receipt`、`completed_files`、`replay_events`删除依赖旧执行目录登记和重放日常批次的部分 | 改接两个Raw资产和手工Raw CLI。独立回刷用新job从头请求整批。首次建库保留明确授权的单独入口，复用正式路径、设备与写锁检查、对象范围核对及删除确认；首次建库不能由当期日更或回刷触发。删除`_record_ranges`、`validate_registered_targets`、`recover_moved_candidate`及`run_period`传给`assemble`的旧目录校验回调。移除手工历史的`period_baseline_not_ready`分支，清掉`_finish_files`和旧事件接续里写`files_ready`、`run_id`、`listed`的语句。独立首次建库与指定历史维护分别核对已确认的执行范围和实际结果 |
| [`stock_period_source.py`](../../orchestrator/src/orchestrator/defs/stock_period_source.py)、[`io/stock_period_raw.py`](../../orchestrator/src/orchestrator/defs/io/stock_period_raw.py) | `capture_unit`、`assemble`和`publish`收窄为独立首次建库专用；删除混合日更、`history/upsert`及跨批复用分支。首次建库本次执行内的源分页、`copy.json`、`validated/`和`committed/`恢复材料按第13.14节保留，日更、回刷与人工补数不能调用；新链继续使用无接续分页内核及`assemble_period/assemble_history_period/publish_period`。删除`assemble`中旧混合当期与历史响应的合并、重叠比较及`period_history_coverage_conflict`分支；删除旧`history`和带`codes`的`upsert`合并SQL；新历史合并沿现有`assemble_history_period`，不保留先按股票代码移除整股旧记录的做法 | 当期与单股历史分别构造候选，复权因子回刷按返回业务键合并，旧键未返回则保留，确认退市删除只在独立清理job执行。保留HTTP超时、限流、分页、原字段校验与候选文件构造。删除`assemble`的旧范围索引输入、`validate_targets`回调及服务于它们的分支。保留`file_version`和`file_digest`在本次文件合并、替换前检查、实际交付校验中的用法，以及暂存区与同设备原子替换。本批仍要逐文件核对写入和检查结果。正常的HTTP JSON和独立审计报告属于数据及审计记录 |
| [`stock_period_update.py`](../../orchestrator/src/orchestrator/defs/stock_period_update.py)的交付函数、[`run_contracts/stock_period.py`](../../orchestrator/src/orchestrator/defs/run_contracts/stock_period.py)、[`run_contracts/configs.py`](../../orchestrator/src/orchestrator/defs/run_contracts/configs.py) | 在首次建库及旧CLI消费者完成第13.14节迁移后，整体删除`confirm_period_delivery/acknowledge_period_delivery`和仅为它们服务的`_period_delivery_*`；不保留读取旧回执、共享状态或旧目录找后继的包装。替换`completion_reference`、`completion_notice`及其校验里的`raw_execution_id`、`file_receipt_hash`旧格式。去掉`StockPeriodRawConfig`的`intent=history`、`validate_history_intent`及该分支使用的`stock_codes`和`request_id`。删除旧交付引用版本及仅为旧运行继承内存覆盖的`STOCK_PERIOD_RUNTIME_RSS_GIB_TAG` | 日更和独立op已经在真实运行内登记物化及检查。首次建库迁到第13.14节的`bootstrap/stock_period_history.report_bootstrap_events`后，删除旧`report_file_events/report_completion_events`及其日常通知合同，不保留转发包装。继续复用实际版本、物化和检查绑定的校验。`build_stock_period_run_config`传明确的业务日期。现有Raw job的运行配置区分当期`daily`与人工`closed_period`，分区必须匹配日期和频率。原指定股票维护迁到独立入口，自动因子回刷由Dagster传因子日期和名单摘要。当期月线范围请求删掉，单股历史`ts_code + freq`及其分页保持 |
| [`stock_period_silver.py`](../../orchestrator/src/orchestrator/defs/stock_period_silver.py)、[`run_contracts/stock_period_silver.py`](../../orchestrator/src/orchestrator/defs/run_contracts/stock_period_silver.py)、[`io/stock_period_silver.py`](../../orchestrator/src/orchestrator/defs/io/stock_period_silver.py) | 删除`stock_period_silver.read_completion`的旧Raw回执解析，全部调用方改读新`asset_guards/stock_period_delivery.read_completion`。删除`make_update_execution`、`recover_update_execution`、`update_delivery_progress`、`confirm_update_delivery`中依赖`execution.json`、`events_complete.json`、`covered_by_execution_id`的日更续跑和确认分支。去掉`reused_update_record`、`owned_update_records`、`update_recovery_message`的旧续跑链，清理`load_execution`和`build`中查父执行、继承已完成文件的日更分支，以及`recovery_run_id`、`resume_from_execution_id`、旧cursor待续跑执行和日更调用`recover_committed`的路径 | 两个Silver sensor、两个Silver job、`deliver_update_asset`和`stock_period_silver_cli.report_update_events`一起迁到实际Dagster交付。移除`validate_event_coverage`、`record_update_coverage`追溯旧执行父子的分支。`resolve_update_sources`保留较新合格Raw可合法接续的判断，继续检查实际文件、完整范围与绑定的原检查。首次建Silver的`make_execution`和审计报告校验保留其独立用途。保留Silver历史下限、文件校验、写锁和原子替换 |
| [`bootstrap/stock_period_history_cli.py`](../../orchestrator/src/orchestrator/defs/bootstrap/stock_period_history_cli.py)、[`bootstrap/stock_period_silver_cli.py`](../../orchestrator/src/orchestrator/defs/bootstrap/stock_period_silver_cli.py) | 删除Raw `handoff`及其重建共享水位的代码。Raw `resume`移除按旧64位执行ID恢复日更、历史混合批次的分支，`--rss-limit-gib`清掉旧交接和继承逻辑。清掉Silver `resume`读取`intent=update`旧执行的分支。两个CLI的`events`移除按旧日更执行目录补登记的分支 | Raw `prepare`/`apply`和Silver `build`保留首次建库用途，继续核对其原授权、范围和审计报告。独立首次建库的恢复与事件核对只接受该入口生成的建库执行和审计材料，沿用建库自身授权、实际文件和检查。 保留与删除的函数、调用方、写后记录和验收按第13.14节逐项实施，不能整段删除首次建库本次执行内的源或候选恢复能力。日常入口和两个Silver sensor无读取该材料的路径，建库也不写`baseline.json`或创建建库交接标记。已部分写入时不能重新调用带删除确认的Raw `apply`来代替核对。正式日常批次用Dagster按业务范围整批重跑，登记前核对实际文件和检查 |
| `jobs/stock_weekly_event_backfill.py`（已清退）、`ops/stock_weekly_bootstrap_checks.py`（已清退）及旧独立脚本 | 删除仅按旧执行清单补周线事件的`raw_stk_period_bar_adj_week_event_backfill_job`、`report_stock_weekly_bootstrap_checks`和`StockWeeklyBootstrapEventChecksConfig`。删除已只会报停用的`bootstrap/stock_weekly_history_cli.py`、`stock_monthly_history_cli.py`、`stock_weekly_events_cli.py`、`stock_monthly_events_cli.py` | 补齐旧批事件的工作在切换前完成。切换后由新批交付或重跑核实并登记文件及检查。同步更新Dagster资产与任务拓扑、运行契约和现行运维命令；历史记录保留 |

**整体清退旧 `baseline.json`。** 清零生产代码对该文件的读取和写入，删除上市名单、每股旧区间、首次建库交接状态和跨批文件版本目录的维护。清退`_old_range_paths`、`range_index_valid`、`_source_ranges`和`merge_ranges`中仅服务于旧索引的实现。新股随当期全市场交付，常规回刷按源日期定位目标文件。独立首次建库按本次实际产出验收，日更和手工回刷无需另查建库交接完成标记。文件合并、替换前后的核对与Silver对应Raw实际交付的原检查继续按§13.4执行。Raw已有的历史范围和代码身份规则继续适用，包括已确认的北交所历史口径。开发验收使用昊帆生物`301393.SZ`的只读源实测作为范围样本。该股2026-11-10复权因子从1.0223变为1.0252。不传日期时，周线172条，周期2023-07-14至2026-11-13，月线41条，周期2023-07-31至2026-11-30，两频均算至2026-11-10。以这份有来源的样本验证周、月源日期到正式文件的定位和业务键合并。

**整份周期文件缺失时的补齐。** 删除依赖`completed_through`的旧`daily_periods`滚动待办。显式指定待查周期，用交易日历、实际文件及已通过的Dagster交付判断缺口，完整休市周期由交易日历证明。人工使用对应Raw job的`closed_period`意图，日期为该周期最后一个开市日，分区为自然周五或自然月，仍用该周期单点请求。Raw job按§13.2的在市及停复牌规则，计算从周期开始到业务日期的逐日应有代码，按原周期准入与身份规则取并集，并核对每只股票在该段最后应更新的日期。源必须覆盖整个集合，应有记录的`end_date`至少到该股最后应更新日；允许源后来重算到更晚日期，按实际日期交付，并校验其未超过上海执行日期。整期全日停牌的股票允许源返回有效记录，也允许缺席。正常当期sensor仍只检查当天。整期覆盖通过后才能新建缺失的全市场文件，Silver按实际交付接续。沿用原日历业务口径，由已接通的`period_input_days`核对周期最后开市日，完整休市周期由正式日历证明；不为此保留无生产调用的旧日更函数。11月6日那周用`002623.SZ`验收：11月2日应更新，11月6日确认全日停牌，因此11月6日sensor不要求它更新，但补建整周文件须有它的周线；原记录`end_date=20261102`符合该股该周覆盖。另验已闭合月、过旧及未来来源日期、休市和正常重取。

**未触发的历史回刷与身份维护。** 若某业务日两频当期Raw未都完成，次日的常规相邻因子对比不能证明该日已回刷。核对该日两份Silver股票复权因子及Dagster实际回刷结果，由人工指定原复权因子日期提交独立回刷。若原日缺可用Raw交付，先核实该日所在周、月已有覆盖该日且通过检查的实际Raw交付，或先按上段补齐已闭合周期。任务仍按原复权因子日期及相邻交易日重算名单和摘要，登记实际采用的Raw批次，不把后来日期的交付写成原日成功。已触发但失败的回刷按原配置重跑。确认退市沿§13.8在本频Raw日更成功后独立清理。换码和确需撤回记录走独立指定范围维护，执行前核对已确认的证券身份、旧代码及周期，逐文件按本次明确的业务键处理并登记正常交付，Silver按实际影响周期接续。该维护独立于自动因子名单，无全湖扫描。以上均按指定范围执行，sensor仍只处理当期自动提交；具体命令、配置分支、文件处理、Silver接续及验收见第13.15节。

**切换顺序。** 先核对在跑的旧Raw/Silver运行、`daily.json`中未确认的条目、已有文件与未登记的检查，以及两频最后一次确认的当期和已闭合周期。逐笔办结仍有交付责任的旧批。转新批时先按原业务日期和实物确认欠账。源仍能交付原日的当期走当期入口，已闭合周期走指定周期补齐，复权因子变化走原复权因子日期回刷。跨日已经无法取回的当期快照保留原缺口记录，并核实所属周期与回刷另有处理结果。先核对实际文件和交付记录，并完成源历史范围的有界样本验证，再在同一版切换两个Raw和两个Silver sensor、独立因子回刷、退市清理及手工入口。旧cursor以Dagster已完成记录和实际文件核实切换位置，不继承旧执行ID。切换后核查旧批时只用既有Dagster原生物化、检查与实际文件，缺失的交付按对应新入口补齐。切换时保留历史回执、运行记录和正式文件，源码清退与物理文件清理分开授权。

**清退验收。** 在`orchestrator/src`、脚本、Definitions、运行配置构建器和现行运维命令中逐项复查上表符号及文件名。旧`baseline.json`和共享待办须无生产读写引用，原执行接续、旧日更回执解析、停用命令和周线旧补登记job须没有可达入口。保留的共用模块须按实际调用方核对，尤其要验证独立首次建库、正常的当期单文件交付、按源周期定位历史文件与Silver合法后继。正例覆盖从未创建过`baseline.json`的当期日更和回刷、完整历史更新、同周期其他股票保留及全市场日更新建当期文件。反例覆盖旧代码不能先删整股再合并、本次未返回的旧键得到保留，以及历史目标文件缺失时单股回刷拒绝新建。改写`test_stock_period_combined.py`和`test_stock_period_delivery_history.py`中依赖旧版本目录的断言，直接验证实际文件与结果。对照`test_stock_period_history_cli.py`、`test_stock_period_handoff.py`、`test_stock_period_handoff_memory.py`、`test_stock_period_memory_resume.py`及当前`test_stock_period_native_daily.py/test_stock_period_silver_sensors.py`，移除要求旧日常接续行为的用例，保留首次建库、资源、业务范围和实际文件检查的正反例；两份独立job的Native回归保持。旧`test_stock_period_silver_original_recovery.py/test_stock_period_silver_sensor_recovery.py`已在第2阶段退出，不恢复文件。用`test_stock_period_retirement.py`、`test_stock_period_combined.py`、`test_stock_period_partial_delivery.py`及周、月Definitions测试核对入口清单和合法补登记。另验当期通过后仍能识别更早的已闭合缺口，指定周期能单独补齐。隔离环境保留一份旧待办和旧回执作为反例，验证新任务全程不读取它们，同时能整批重跑、接续合法Raw并完整登记检查。再按§13.6完成有界正式验收。

<a id="stock-period-retirement-cleanup"></a>

### 13.8 退市清理由独立job按频率触发

管理员确认日更完成后独立清理。周Raw当天更新成功后只触发周线清理，月Raw当天更新成功后只触发月线清理，两频各自执行。这里的日更成功指对应Raw job运行成功、实际当期文件交付完整且原检查通过。

**现有方式与触发。** 复用[股票日线前复权回刷sensor](../../orchestrator/src/orchestrator/defs/sensors/gold_stock_daily_qfq_factor_repair_job_sensor.py)的`run_status_sensor(SUCCESS)`模式。该sensor只监听指定日更job，读取触发运行的业务日期，核对上游检查及所需范围后返回带去重键的`RunRequest`。周月线新增一个同样方式的sensor，监听`raw_stk_period_bar_adj_week_update_job`和`raw_stk_period_bar_adj_month_update_job`。只接受当期日更意图，频率由触发job确定，业务日期取Raw配置的`automatic_intent_date`。周五分区和月份用于核对对应文件坐标。延迟执行仍使用上游业务日期。同日指定周期补齐、因子回刷和清理自身成功均不递归触发清理。

**一个job，两种执行范围。** 新增`raw_stock_period_retirement_cleanup_job`，每次配置明确`freq=week`或`freq=month`、业务日期及上游运行引用。周清理只读取和改写周Raw，月清理只读取和改写月Raw。job从已验收的股票生命周期、股票基础数据及已确认证券身份确定退市候选，沿用`list_status=D`确认规则。用Dagster中本频已成功清理的股票结果排除重复工作，包含尚未处理的已确认退市股票，不依赖旧上市名单或`baseline.json`。提交时保存名单摘要，执行时重算核对。首次切换时，已有已完成清理结果按实际交付承接。

**实际执行与结果。** sensor只核对上游和提交配置，历史文件处理在清理job中完成。没有待清理股票时，job记录本频零清理结果，不读取历史行情。非零时按退市股票代码筛选本频全部历史文件，只修改包含这些代码的文件，移除对应行并保留其他股票。首次写入前，在Dagster运行记录中保存本次股票名单和命中的完整周期范围。失败后仍按原完整范围从头重跑；原选中文件已无待删行时无需重写，但仍验收并纳入本次交付，使同频Silver能处理此前已经改写的周期。复用候选校验、原子提升和原文件检查，同频Silver按该Raw交付接续。清理结果、股票名单和交付范围保存到Dagster运行及检查记录，另一频须有自身的完成结果。清理失败后用原频率、业务日期和范围整批重跑，本次仍处理该运行配置中的完整名单，直到整批验收才将其登记为本频已清理；当前日更保留自己的成功结果。后续成功日更仍可识别该频尚未处理的确认退市股票。

**代码落点与配置。** 以下是待开发位置，不表示当前已存在。

| 文件 | 职责 |
| --- | --- |
| `defs/sensors/raw_stock_period_retirement_cleanup_job_sensor.py` | 监听两个Raw日更job的成功事件，核对对应频率的完整交付，构造去重请求 |
| `defs/jobs/raw_stock_period_retirement_cleanup.py` | 定义一个独立清理job |
| `defs/ops/raw_stock_period_retirement_cleanup.py` | 重算确认名单，按股票代码统计本频全部历史文件，处理命中文件并登记结果 |
| `defs/run_contracts/stock_period_retirement_cleanup.py` | 定义业务日期、频率、上游引用和名单摘要的运行参数 |

执行频率、业务日期和名单摘要由本job合同统一定义，sensor、运行参数构建和op共用；取值来自上游运行配置及上述正式事实，不新增环境变量或本地配置文件。沿用`build_sensor_tags`与现有运行标签规则，日志显示本次频率、业务日期、名单数及实际文件范围。复用`build_upstream_triggered_run_key`生成去重键，键同时区分频率和对应上游运行，重复收到同一成功事件只提交一次。运行配置由sensor生成并保存在Dagster运行中。手动整批重跑使用同一业务配置。此job无单独固定执行时刻，沿对应Raw成功事件触发。定义分类、拓扑及静态门禁随实现一起登记。

**历史文件定位。** 管理员确认按股票代码筛选需要修改的文件。确认退市名单及代码对应关系仍来自上述正式事实。通过`io/stock_period_raw.dataset_root`定位本频正式Raw目录，枚举该目录中所有规范周期文件；周线只查`week_end=*/part-000.parquet`，月线只查`month=*/data.parquet`。用DuckDB只投影`ts_code`，按本次退市代码统计各文件的匹配行数，匹配数大于0的文件进入本次修改范围。代码列统计覆盖本频全部历史，不用正式上市日期或退市日期截断。仅命中文件才读取原21列、删除指定退市代码并生成候选；另一频文件不读写。首次命中范围保存在本次Dagster运行记录中，供完整交付及整批重跑核对，不重建每股历史索引或私有JSON清单。

2026-11-11只读定点样本确认：正式股票生命周期中的`920799.BJ`上市日期为2020-07-27、当时仍在市，股票复权月线Raw的`month=2020-01/data.parquet`已有该代码的`trade_date=20200131`记录。该样本说明Raw确实保留正式上市前行情，不能从正式上市月份开始定位退市清理文件。样本仅用于确定文件范围和隔离验收，不把该在市股票加入正式清理名单。

**范围和性能。** sensor只核对触发运行、对应频率的完整交付及原检查，再按确认退市候选核对该频Dagster完成结果，不查历史行情。没有待清理股票时不枚举和读取历史文件。非零任务令N为本频全部规范历史文件数，F为本次退市代码命中的文件数：初次定位枚举N个路径并统计N份文件的`ts_code`列，21列读取、候选构造和原子替换各限F份。最后重新统计N份文件的目标代码残留，并对本次完整交付范围核对业务键、分区日期、物化及原检查；同频Silver只接续本次交付范围中满足其历史下限的周期。首轮定位和最后残留核验合计最多2N份代码列统计，不等于读取2N份完整行情。

一次中断加一次整批重跑，两次实际文件数为N₁、N₂时，代码列统计最多合计2N₁＋2N₂份；实际改写数为F₁、F₂时，21列读取、候选构造及替换分别按F₁＋F₂计。重跑从第一步重新统计目标代码，同时保留原运行已登记的完整周期范围，不能因部分文件此前已经删完而遗漏同频Silver接续；不按已完成文件位置跳过步骤。2026-11-11目录元数据计数为周Raw 1,823份、月Raw 432份，仅作为当时文件规模，不作为固定上限或耗时保证。本轮已完成两次代码列统计，以及四文件隔离候选、原检查和最后验收，实测耗时、压缩列大小和峰值内存见第13.10.5节；没有测得新任务完整链路或正式目标盘的写入耗时，不能把临时设备结果作为正式性能保证。正式非零执行前按实际名单、N、F和文件字节核定现有资源限制，不能套用旧上市日期范围或旧索引预算。候选和spill只放正式暂存区。清理任务不请求退市股票的Tushare历史。

**验收。** 周成功只提交`freq=week`，月成功只提交`freq=month`，两者都成功时分别提交两次同一job。失败或检查未通过不提交，同一成功事件重复处理不重复提交。验证清理自身不回触发、运行跨日仍保留业务日期、零清理不读历史、确认退市才删除、周清理不读写月文件、月清理不读写周文件、写完部分文件后失败、整批重跑仍完整登记原范围并让同频Silver接续，以及晚到的退市事实后续可处理。对真实`000016.SZ`旧案例构造有来源的隔离样本，分别验收两频Raw与同频Silver，禁止把一次成功当成两频均已完成。另以`920799.BJ`的上市日期和2020年1月Raw记录构造隔离样本，将该样本明确设为确认退市对象，验证正式上市前记录也能被定位和清除，同文件其他股票保持；正式在市股票不进入清理名单。未命中文件不生成候选、不替换文件。

<a id="stock-period-development-stages"></a>

### 13.9 开工审计与开发阶段（2026-11-11，第1阶段记录）

**审计结论。** 第13.2至13.8节的业务口径已经明确，包括按退市股票代码定位本频全部历史文件。本轮对照当前源码、测试及本地源文档做开工审计，没有新增需管理员重新拍板的业务规则。初次审计列出的传输入口、运行参数、交付记录及性能验证已按第13.10节补齐，第1阶段审计当时确认具备进入第2阶段源码开发的条件；当时尚未修改新流程代码或正式运行。第2阶段结果见第13.11节。每阶段编码前先完成该阶段在原方案和本LLD中的详细设计，再按获准范围实施和验收。

**本轮核验依据。** CodeGraph的`codegraph_explore`核到`deliver_asset → run_period → capture_unit`，`codegraph_impact(completion_reference)`覆盖Raw交付、Silver读取、首次建库入口及相关集成测试。直接读取确认`_http_attempt`固定请求完整21列，`HttpPage`沿`StockPeriodPolicy.retries=2`执行；`read_completion`仍读取旧`manifest.json`和`complete.json`。现有周、月Raw/Silver job均选择自身资产及原检查。日线应更新集合的SQL和股票日线前复权回刷触发方式可以复用，计算与选股规则保持。

2026-11-11通过Tushare MCP各做一次单股单周期只读请求：`301393.SZ`，周线`freq=week, trade_date=20261113`，月线`freq=month, trade_date=20261130`，均指定`ts_code,trade_date,end_date`。两次各返回一条三列记录，周期标签分别命中上述坐标，`end_date`均为`20261110`。该样本用于证明三列投影和周期坐标，不作为11月11日全市场齐备或DG传输耗时的证据。随后已按第13.10.1节完成真实分页、代码列统计及隔离重做验证，完整范围和实测结果见第13.10.5节。

| 初次审计事项 | 补齐前核对依据 | 已完成的编码前设计与验证 |
| --- | --- | --- |
| 预检传输入口 | `stock_period_source._http_attempt`固定21列，现有`HttpPage`有正式下载重试；现行sensor尚不请求源 | 写清三列投影及本次tick截止时间如何传入，sensor不沿用正式下载重试；预检与正式下载共用已确认的周期请求规则，正式下载仍为原21列。明确`source_readiness`、请求构造和HTTP调用的具体落点及全部调用方；已完成见第13.10.2、13.10.4和13.10.5节 |
| 运行参数与交付记录 | `completion_reference`仍为旧64位执行ID和回执摘要；Silver按该引用读取私有文件 | 将新的运行参数、上游引用、完整周期集合、实际来源日期、文件结果和完成结果写成字段名、类型及用途明确的合同；列齐Raw生产者、Silver消费者、两个独立job和手工入口的迁移位置。退市首次命中文件范围和完整重跑的原生记录已定清，见第13.10.3及13.10.5节 |
| 新任务定义 | 初次审计时，独立复权因子回刷未列齐job、sensor、op和参数文件；清理job拟名缺Raw前缀 | 按`CODING_STANDARDS.md`的job和sensor命名规则确定最终名称、配置、文件及Definitions登记，校准第13.8节拟名及全部文档引用；现有四个资产及日更job名称保持；两个新job的最终定义见第13.10.4节 |
| 新路径性能 | 第13.5和13.8节已有规模公式及旧实测参考，新预检和代码列统计尚未完成本轮测量 | 明确有界验证的日期、对象、文件、字段及请求数，验证预检截止与分页边界，测量代码列统计、候选及原检查成本；同时计入一次中断后整批重跑和最后验收。实际值按现有资源限制核定，不能把旧6 GiB单次恢复授权或目录文件数当成新任务性能保证；实测及成本复算已完成，见第13.10.5节 |

**开发阶段安排。** 第1至6阶段已完成开发及对应隔离验收，结果见第13.10至13.13、13.17和13.19节；正式切换按第13.20节完成，实际结果见第13.21节。各阶段只在当前`dev-interface`工作区推进，测试资源和过程材料均放工程外。新流程整体接通并清退旧入口后才正式切换；各阶段修改到的旧分支随对应替换删除，第5阶段复查清零，不增加兼容层或双轨实现。

| 阶段 | 目标与任务 | 实现范围及阶段验收 |
| --- | --- | --- |
| 1. 完成编码前准备 | 完成上表四项；把业务硬口径逐条映射到代码、正反测试和有界验证；确定所有新job、sensor、op、运行参数及交付字段，补齐配置来源、消费者、生效方式与性能依据 | 原方案第10.19节、本节及相关运行契约、拓扑文档。本步只做文档、静态审计及已获准的有界验证；四项已完成，对账见第13.10.6节 |
| 2. 实现当期日更与Silver接续 | 提取按生命周期及最终停复牌事实计算当天应更新代码的共用规则；两频20:00起做三列源预检；正式下载同一单点的21列并复核，只交付本频当期文件。同步实现新的Dagster交付记录及Silver读取 | `source_readiness/`、`stock_period_source.py`、`stock_period_update.py`、Raw/Silver运行参数、两个Raw/Silver入口及检查。验证新股必需、全日停牌可选、缺码及同数换码不触发、当天重复去重、无JSON前置、只写当期一文件，以及真实临时Raw生产者到同频Silver和原检查的隔离链路 |
| 3. 实现独立复权因子历史回刷 | 同一业务日两频Raw日更完整成功后提交独立回刷；沿用相邻交易日Silver股票复权因子比较。仅对变化股票按`ts_code + freq`请求两频完整历史，按源日期定位文件，按业务键合并并保护较新记录；无变化记录零回刷 | 新回刷job、sensor、op和运行参数，复用源合同及候选IO。验证两频完成先后顺序、仅一频成功不提交、新股不混入回刷名单、无日期过滤、整股旧记录不会先被删除、零变化无历史请求，以及失败整批重跑后两频Silver接续 |
| 4. 实现独立退市清理 | 周Raw日更成功仅提交周清理，月Raw成功仅提交月清理。同一个独立job按频率处理确认退市股票，用代码列统计定位本频历史文件，仅改命中文件，登记本次完整范围并让同频Silver接续 | 第13.8节定义的新入口和现有候选IO。验证零候选不读历史、另一频不读写、未命中文件不替换、正式上市前记录能够清除、同文件其他股票保留，以及部分写入失败后整批重跑仍交付完整范围 |
| 5. 完成人工维护和旧实现清退 | 接通指定闭合周期全市场补齐、按原复权因子日期指定回刷及已确认身份维护；首次建库保留/改写/删除、事件替代及测试按第13.14节实施。按第13.7节逐文件、函数、分支和调用方清零旧混合任务、共享待办、`baseline.json`、旧交接与日常续跑链及停用入口 | Raw/Silver CLI、旧bootstrap调用、旧事件补登记job、运行参数、目录定位及相关测试。保留原源合同、身份规则、文件校验和原子提升；以无旧JSON的隔离环境验证新入口，查清所有生产读写引用。历史运行、正式文件和旧业务回执不随源码删除 |
| 6. 完成整体验收和交付 | 串联预检、当期Raw/Silver、复权因子回刷和单频退市清理；复核完整范围重跑、合法人工维护、旧入口清零及性能结果。同步catalog、Definitions、运行契约、拓扑、静态门禁和原文档，形成逐条计划对账 | 执行必要单元、契约、隔离集成及静态检查；测试输出留工程外。以已确认的真实源样本核对接入边界，正式写湖验收另行批准。本阶段交付代码、测试、审计结论、待切换清单及准确的未执行项 |

**正式切换边界。** 六个阶段是开工准备、开发和隔离验收安排，不包含启停正式sensor、重载正式code location、提交正式job或写湖。上线前沿第13.7节核实旧任务交接，再按具体批准执行切换及有界正式验收。不能用隔离测试通过替代正式文件及原检查验收。

<a id="stock-period-implementation-contracts"></a>

### 13.10 四项实现准备补齐（2026-11-11，第1阶段记录）

#### 13.10.1 本步范围及验证计划

管理员已批准补齐第13.9节四项并重新审计开工条件。本步只修订原方案、LLD和直接引用文档；不修改正式Python源码、Definitions、配置、正式实例或Lake。验证程序和结果放本次`/private/tmp`目录，最终有效结论落回本节后删除临时材料。

静态核对覆盖现有周/月Raw与Silver、`stock_period_source`、`run_contracts`、两个既有CLI和日线前复权回刷参考。既有资金流传输函数限定资金流字段，不用于本次股票周月线。`tushare_download`目前只注册`stk_factor_pro`合同及绑定，本步不扩大其接入范围；对本次已有周月线HTTP传输明确字段投影和截止参数，正式21列及原源合同保持。

| 验证 | 明确范围与方式 | 输出及读写边界 |
| --- | --- | --- |
| 只读HTTP | 同一自然周五`20261113`和自然月末`20261130`，各请求全市场三列一次；每频额外请求`limit=2,offset=0`、`limit=2,offset=2`和`limit=4,offset=0`，核对分页相接。另请求`301393.SZ`两频完整21列历史各一次。合计最多10个请求，不自动重试 | 仅保存字段、计数、耗时、响应字节和必要有界样本。使用现行环境凭据及端点，不打印token或认证内容。每请求沿现有30秒截止和16 MiB响应上限；真实请求支持情况以结果为准 |
| 历史代码列统计 | 枚举本频规范文件，对`301393.SZ`及已确认退市案例`000016.SZ`只做逐文件匹配行数统计和汇总，分别计时；不导出行情明细 | 这是本频全历史的统计计数，读取限`ts_code`列；不修改正式文件，不请求退市股票源。记录文件数、匹配文件数、行数及时间 |
| 候选、原检查及完整重跑 | 仅取`week_end=2026-11-06`、`week_end=2026-11-13`、`month=2026-10`、`month=2026-11`四份正式文件作为有界输入，在`/private/tmp`副本中分别测按业务键合并和按代码移除 | 用既有DuckDB限制、`validate_file`及原三项文件检查所用函数核验；只在临时副本做`os.replace`。模拟写完一份后中断，再从第一份完整重做并做最后对账；正式文件只读，隔离样本中的股票移除不代表正式退市事实 |
| Dagster记录能力 | 使用工程外临时instance和小型无业务数据任务，验证计划范围、文件物化、完成通知和结果检查能随真实运行ID保存并按运行读回 | 不连接正式DAGSTER_HOME或正式event storage，不创建新状态资产，不执行正式job。只验证本次选用的原生记录API，不能声称新流程已完成端到端实现 |

源覆盖的定点核对使用2026-11-10的正式股票生命周期和最终停复牌字段，结合两份三列源响应只做要求集合、可选集合及差异计数；不读取股票日线，差异样本沿既有20条上限。

上述验证总量由表中具体对象和文件确定。计数查询不扩大为正式历史21列全量读取；候选输入只限四份指定文件。一次中断后的重做及最后验收均在临时副本执行。新实现尚未编码，传输和SQL验证须如实区分现有能力、隔离样本结果与待开发集成。


#### 13.10.2 预检入口、请求与配置定稿

预检新增`defs/source_readiness/stock_period.py::probe_stock_period_source`，只接收频率、业务日期、当日要求代码、可选代码、已确认身份及截止时间，不依赖Dagster instance，不写文件。Raw sensor负责验证前置事实和决定提交；Raw正式下载使用同一代码集合计算及周期请求规则复核21列。

上市日期及全日停牌集合计算从`checks/stock_daily_checks.py::_expected_tradable_universe_metadata`提取到`defs/stock_trading_universe.py`，共用其生命周期、全日停牌和盘中停牌判断。日线自己的历史起点、额外代码检查及北交所开市限制保持在日线调用方；周月线保留本链Raw准入规则，不把日线价格文件作为输入。周月预检的要求集合为在市集合减去全日停牌，可选集合为全日停牌。仅要求集合中每个代码恰有一条目标周期且`end_date=D`时通过；可选集合的有效记录允许较早日期或缺席。非准入记录按本链既有源准入规则处理。

| 实现位置 | 定稿后的参数和职责 |
| --- | --- |
| `run_contracts/stock_period.py` | 保留完整21列`FIELDS`；增加三列投影常量`STOCK_PERIOD_READINESS_FIELDS=('ts_code','trade_date','end_date')`和管理员指定的20:00开始时刻常量。`request_params`对全市场周、月均生成`freq + trade_date`单点；单股完整历史只生成`ts_code + freq`及分页参数 |
| `stock_period_source.py::HttpPage` | 构造时增加`fields`，默认完整21列，预检显式传三列；`__call__(params, *, deadline=None)`允许本次绝对单调时钟截止。`_http_attempt`接收并转发显式字段，不再把21列写死在请求体。正式下载与独立首次建库不传截止时沿原策略执行 |
| `source_readiness/stock_period.py` | 使用`dataclasses.replace(DEFAULT_POLICY,retries=0)`和三列投影构造本次预检传输；按实际字段解析三列，不调用要求21列的`validate_rows`。核对字段、周期、代码、截至日及重复。返回`ready:bool`、`reason:str`、日期/周期/频率、计数和既有20条上限的差异样本 |
| 预检截止及分页 | 从开始读取本次预检前置事实计时，以现有`DEFAULT_POLICY.timeout_seconds=30`秒作为本次预检共用截止；各页和限流等待共用该时间，不逐页重新取得30秒。每次HTTP实际可用时间取现有单请求上限与剩余时间的较小者；前置已耗尽截止时源请求为0。满6,000行才请求下一offset，短页结束；重复页、未能完成分页或截止耗尽均等待后续tick，不提交job |
| worker及清理 | 沿原`HttpPage`独占子进程和0.2秒轮询，源截止后终止该子进程，沿既有两个最多1秒的等待完成清理；后续tick重新探测。预检不执行HTTP重试和退避；正式下载仍按`retries=2`、即每页最多3次尝试执行 |

| 配置/固定输入 | 默认值与依据 | 来源、持久化、消费者及生效 |
| --- | --- | --- |
| 开始时刻与检查间隔 | 20:00由管理员指定；间隔沿现有60秒 | 周月时间规则与两个Raw sensor定义集中维护，代码位置重载生效；没有新增运营开关，skip和日志显示业务日期与原因 |
| 三列与21列 | 分别为管理员确认的预检投影和既有完整源字段 | `run_contracts/stock_period.py`唯一维护；预检/HTTP与Raw下载共用；不是两个源字段合同，不暴露给用户选择 |
| 超时、页长及容量 | 30秒、6,000行、16 MiB响应、128 MiB源单元，均沿`StockPeriodPolicy`现值 | 原策略为唯一来源；预检只在本次内缩短剩余时间、取消重试，不更改全局默认或其他数据集 |
| 凭据、端点与限流 | `TUSHARE_TOKEN`必需；`TUSHARE_BASE_URL`沿`PeriodHttpConfig`默认；`TUSHARE_MAX_CALLS_PER_MINUTE`默认280 | 沿现有环境及`PeriodHttpConfig.from_environment`，不读取新增配置文件、不自动加载仓库.env；只记录脱敏端点信息和请求统计。正式下载同一运行共用一个传输实例，沿其限流，不能按股票重新创建实例绕开间隔 |
| 列式执行与空间 | DuckDB 3 GiB/2线程、进程4 GiB、spill16 GiB、工作目录32 GiB、进度5秒，均为现有策略 | 沿原策略及资源检查；不继承旧原任务单次6/8 GiB标签。每个新Dagster运行使用自己的正式staging目录；32 GiB限制只针对本运行工作目录，16 GiB spill若在其中须计入、不能重复当成额外可用空间；旧运行剩余目录另计同设备已用空间。本次未更改这些默认值 |
| 运行检索tag | 业务日期、用途和单频频率只从已验证运行配置派生，无独立默认值 | 由`stock_period_delivery.py`集中命名和构造，入口通过`instance.add_run_tags`保存于Dagster run storage；历史修复sensor按同日daily检索，清理sensor/op按频率读取累计成功结果。详见第13.10.3节；不改变共用请求builder、运行key或sensor分类tag |

这些字段和截止参数是内部调用合同；只在本轮股票周月链的已审计调用方中迁移。资金流传输函数的API及字段被其合同限定；通用下载组件目前仅登记`stk_factor_pro`，不以本步为由迁移这两者。

#### 13.10.3 运行参数及交付记录定稿

新增`defs/run_contracts/stock_period_delivery.py`维护本节结构、序列化、引用及去重构造，旧`stock_period.py`中的私有回执引用实现删除而不留兼容解析。业务21列不增加以下运行字段。

**运行参数。** 表中“必需”表示对应模式必须显式给出，不能从当前时钟、分区名或run key反推业务日期。Dagster原生`run_id/root_run_id/parent_run_id`不作为新的运营配置。

| 配置及模式 | 字段、类型及规则 |
| --- | --- |
| `StockPeriodRawConfig` | `intent: Literal['daily','closed_period']='daily'`；`automatic_intent_date: str`必需，ISO业务日期。前者是当日，后者是所选闭合周期最后开市日；频率来自原job，分区须匹配。删除旧`history`、`stock_codes`和`request_id`；不再缺省为运行时钟 |
| `StockPeriodSilverConfig`更新 | `intent='update'`，`source_completion: DeliveryRef`必需；更新模式不再使用`execution_id`、`audit_report`、`resume_from_execution_id`或私有执行目录。独立首次建库的`intent='bootstrap'`及其原`execution_id/audit_report`仍限建库入口，不能用于日常接续或证明日更就绪 |
| `StockPeriodHistoryRepairConfig`复权因子变化 | `intent='factor_changed'`；`business_date: str`、`stock_codes: list[str]`、`codes_hash: str`、`frequencies: list[str]`（固定周、月）、`upstream_completions: list[DeliveryRef]`必需。两引用固定按周、月排序。自动sensor只提交同一业务日两频当期日更引用；op沿日历重算本次复权因子日期及前一开市日的Silver股票复权因子差异，核对完整名单及摘要；空名单合法并记录零回刷 |
| 同一历史修复job的人工入口 | `intent='specified_history'`时显式给`business_date`、非空`stock_codes`、`codes_hash`及`frequencies`；只请求指定股票完整历史。已确认身份维护用`intent='identity_maintenance'`和`remove_keys: list[{ts_code:str,trade_date:str,freq:str}]`明确撤回键，可同时给需要刷新源历史的`stock_codes`。仅按批准范围及正式身份处理，不能从代码缺席推断删除。人工意图不要求伪造上游日更引用，不自动触发其他任务 |
| `StockPeriodRetirementCleanupConfig` | `business_date: str`、`freq: Literal['week','month']`、`stock_codes: list[str]`、`codes_hash: str`及本频`source_completion: DeliveryRef`必需。sensor按已确认退市事实减去本频已完成结果产生名单；op核对配置中的完整名单仍为确认退市，不能在执行时再次减掉完成名单而缩小原范围。空名单合法 |

第13.7节所述补做原日复权因子回刷，仍用`factor_changed`意图，`business_date`为原复权因子日期，名单及摘要仍按该日重算；不是不比较复权因子的`specified_history`。该人工提交可使用已核实覆盖原日的两频后续完整Raw引用，不要求伪造原日成功：逐频引用须包含原日所在周期，实际记录及原检查须符合第13.7节的覆盖条件；原生日志及结果同时保存原复权因子日期和真实采用的Raw引用。此例外仅用于已有的指定原日补做入口，自动sensor仍只认同日两频当期成功，不新增自动回补策略或配置开关。

运行参数的集合缺省只用于其不适用的模式：`upstream_completions`仅在`specified_history/identity_maintenance`模式为空，`remove_keys`在非身份维护模式为空；身份维护允许源刷新名单为空，但必须有明确撤回键。`codes_hash`始终只对应源刷新名单，退市配置中对应待清理名单。身份维护另外将排序去重后的`remove_keys`及其`remove_keys_hash=stock_period.digest(remove_keys)`保存在写前范围，原生重跑须核对同一份明确撤回键，不能因源代码摘要为空而丢掉删除范围。

代码列表按既有代码合同归一化，摘要直接复用`gold_stock_daily_qfq_factor_repair_codes_hash`，即排序去重后的代码以换行连接后取UTF-8 SHA-256。周期列表排序去重，范围摘要复用`stock_period.digest`的规范JSON SHA-256。代码摘要与周期摘要分别命名，不以文件哈希代替股票名单。

日期字段统一为ISO `YYYY-MM-DD`；源请求及21列中的`trade_date/end_date`继续使用`YYYYMMDD`。`periods`在week频率为自然周五`YYYY-MM-DD`，在month频率为`YYYY-MM`；`file_count`等于该去重周期列表长度。`producer_run_id`只能是真实Dagster UUID，不能把64位旧执行ID放入同名字段。

**Dagster原生记录。** `DeliveryRef`严格包含`producer_run_id: str`（真实Dagster UUID）、`freq: Literal['week','month']`、`upstream_batch_id: str`。引用的运行必须成功，文件范围和原检查须完整，才可被消费；引用本身和观察记录不能单独证明成功。

| 记录位置 | 明确字段和用途 |
| --- | --- |
| 开始写文件前的`AssetObservation`，metadata键`goldenshare/period_work` | `version='stock-period-work@1'`、上述三项引用、`kind`、`business_date`、`periods:list[str]`、`stock_codes:list[str]`、`codes_hash:str`、`periods_hash:str`及`upstream_completions:list[DeliveryRef]`。`kind`只取`daily/closed_period/factor_repair/retirement_cleanup/history_maintenance`。身份维护另有`remove_keys`与`remove_keys_hash`；记录本次完整范围，不记录逐文件续跑位置 |
| 每份实际交付的物化 | 沿现有`dagster/uri:str`、`dagster/row_count:int`、`goldenshare/observed_columns`和`goldenshare/period_file_version:list[int]`；最后一项仍为当前文件的`[st_dev,st_ino,st_size,st_mtime_ns,st_ctime_ns]`，只描述该次实际文件。增加`goldenshare/period_delivery:DeliveryRef`、`goldenshare/business_date:str`、`goldenshare/source_asof:str或None`、`goldenshare/rewritten:bool`。空文件的来源日期可为None，非空按原日期合同计算；不建跨运行版本目录 |
| 文件范围观察，metadata键`goldenshare/period_completion` | `version='stock-period-delivery@1'`、三项引用、`kind`、`business_date`、`periods:list[str]`、`periods_hash:str`、`file_count:int`。该观察只声明完整文件范围；下游另要求原运行SUCCESS及这些文件绑定的原检查全部通过。无文件交付的零结果不发该观察，不启动Silver |
| 历史修复结果检查 | 每频`raw_tushare_stk_period_bar_adj_{freq}_history_repair_result_check`，分区为业务日对应本频周期。metadata含`version='stock-period-result@1'`、`producer_run_id`、`kind`、`business_date`、`freq`、`stock_codes`、`codes_hash`、`periods`、`periods_hash`、`file_count`、`rewritten_file_count`、`rewritten_row_count`和`upstream_completions`；零回刷也保存完整空名单及零计数 |
| 退市清理结果检查 | 每频`raw_tushare_stk_period_bar_adj_{freq}_retirement_cleanup_result_check`，沿上行字段，另有`cleared_codes:list[str]`及`cleared_codes_hash:str`。它是本频上一成功结果与本次完整验收名单的并集，用于低成本读取已完成事实，不保存每股历史范围、建库标记或文件版本目录 |

原三项文件检查名称及语义保持，每份检查仍绑定本次真实物化。新增结果检查沿现有股票日线前复权op的`AssetCheckEvaluation`方式记录，不加入四个正式资产的原三项文件检查集合，不作为当期日更的历史回刷前置条件。

**保证先保存范围再写文件。** Raw资产和独立op用生成器先`yield AssetObservation(period_work)`，由Dagster持久化后才进入候选和替换。普通`context.log_event`先在进程内排队，不能把调用完成当作计划已持久化。独立任务逐文件校验并原子提升，先产出所有实际物化，再批量取得本次运行的物化绑定，登记原三项文件检查，最后记录完整范围及任务结果；不得每份文件分别查询Dagster历史。原日更资产自身分区的三项检查仍由原asset job执行；范围观察可以先产生，但读取方只有在SUCCESS和原检查齐全后才承认完整交付。

**完整重跑。** 日更按配置中的当期坐标重新取源，历史回刷按配置名单重新请求两频完整历史并核对摘要，Silver按输入Raw引用的完整范围重新处理，均从第一步执行。退市清理因部分代码已从Raw移除，需保留上次命中文件：只沿Dagster原生`parent_run_id`查询最近一份同业务日期、频率和代码摘要的`period_work`，与本次重新统计的命中范围取并集。跳过的是没有写前范围的祖先运行，不是已处理文件；若整条原生祖先链均没有范围，则此前未获准写文件，本次重新规划。保留全部原选中文件，不重写已无待删行文件，但重新验收并向同频Silver完整交付。查询只用于取得原业务范围，不读旧源页、候选、私有JSON或逐文件进度；不得将父运行已完成文件作为跳步依据。

**运行检索字段。** Raw入口和两个独立op验证配置后、写业务文件前，通过`instance.add_run_tags`保存`goldenshare/stock_period_business_date=D`及`goldenshare/stock_period_kind=上述kind`；单频入口另存`goldenshare/stock_period_freq=week或month`，双频历史修复不伪造单频tag。三者均由`stock_period_delivery.py`统一命名和构造，只能从已验证的运行配置生成，不增加运营配置，不修改共用`build_run_request`。tag持久化在Dagster run storage，用于按业务意图检索；不能替代运行配置、成功事实和原检查。

**查同日另一频日更。** 历史修复sensor从当前成功运行读取显式日期，再用`get_runs(RunsFilter(job_name=另一频Raw日更job,statuses=[SUCCESS],tags={goldenshare/stock_period_business_date:D,goldenshare/stock_period_kind:'daily'}),limit=1)`定位同日另一频日更。随后核对其原生完成范围与原检查；查不到就等待另一频成功回调。不按周/月分区最新成功、运行时钟或run key反推日期，避免把人工闭合周期或另一业务日当成本次日更；手工完整重跑即使没有自动run key，仍可按其明确业务日期被识别。

**读取已完成退市结果。** 按清理job名、`goldenshare/stock_period_freq`及`status=SUCCESS`取最新一条运行，再按运行ID读取其结果检查，核对版本、频率、摘要及passed。这里累计跨业务日完成名单，不添加当天日期过滤；每频最多一次运行查询及一次按运行的检查读取，无须每天遍历历史运行。首次切换从已核准的旧成功结果承接完成事实；无可承接结果时确认退市名单照常统计，不能假定已经清理。

**标识与查询。** 每频交付ID复用`build_batch_id(producer='stock_period_raw',scope=freq,payload={producer_run_id,kind,business_date,periods})`。日更run key保持原`build_asset_update_run_key(subject=原Raw资产名,unit_id=D)`。历史自动请求的上游ID由周、月引用和代码摘要按固定顺序生成，`producer_run_id`固定取周Raw引用，不能取“这次回调是哪一频”来改变ID。历史修复与清理sensor复用`build_upstream_triggered_run_key`；清理输入ID沿本频Raw引用，频率已经包含在交付身份内。所有ID和配置不含event storage id。

新增`asset_guards/stock_period_delivery.py::read_completion(instance, reference, *, root)`，按`producer_run_id`调用`get_records_for_run(...,of_type=ASSET_OBSERVATION)`读取该运行的范围，并核验真实SUCCESS、业务日期、频率、版本及范围摘要。删除`stock_period_silver.read_completion`旧私有回执函数，全部调用方直接迁到新guard，不留兼容包装；`run_contracts/stock_period_delivery.py`只放纯结构和builder，不访问instance。物化/检查按本频完整周期集合走既有`batch_event_evidence`与绑定核验。数据库查询使用原生事件类型、运行、资产和分区集合过滤，不能逐文件查旧执行目录。Silver按实际采用的Raw文件及其原检查处理，合法后继仍沿原规则；自身更新也从头生成本次完整范围，首次建库仍走独立入口。

#### 13.10.4 新任务、配置位置与全部迁移点

只新增下列两个独立job；历史修复job同时承接被移出的指定股票历史及已确认身份维护，人工模式不挂自动sensor。现有两个Raw和两个Silver资产、job名及物理路径保持。

| 定义 | 最终名称及位置 |
| --- | --- |
| 历史修复job/op | `raw_stock_period_history_repair_job`、`raw_stock_period_history_repair_op`；分别位于`defs/jobs/raw_stock_period_history_repair.py`、`defs/ops/raw_stock_period_history_repair.py`，采用与现有周月任务相同的in-process执行方式 |
| 历史修复sensor | `raw_stock_period_history_repair_job_sensor`，`defs/sensors/raw_stock_period_history_repair_job_sensor.py`；只监听两个Raw当期日更job的SUCCESS，核实同业务日两频完整交付后提交`factor_changed`意图，不监听修复、清理或人工闭合周期事件 |
| 清理job/op | `raw_stock_period_retirement_cleanup_job`、`raw_stock_period_retirement_cleanup_op`；分别位于`defs/jobs/raw_stock_period_retirement_cleanup.py`、`defs/ops/raw_stock_period_retirement_cleanup.py`；每次只处理配置的一频 |
| 清理sensor | `raw_stock_period_retirement_cleanup_job_sensor`，`defs/sensors/raw_stock_period_retirement_cleanup_job_sensor.py`；周Raw当期SUCCESS只提交week，月Raw只提交month，两频分别去重 |
| 两类运行参数 | `defs/run_contracts/stock_period_history_repair.py::StockPeriodHistoryRepairConfig`；`defs/run_contracts/stock_period_retirement_cleanup.py::StockPeriodRetirementCleanupConfig`；共用交付格式位于`stock_period_delivery.py` |
| 定义登记 | 新job/sensor由现有`load_from_defs_folder`方式登记；sensor分类均为`quote_data/raw/asset_update`并调用`build_sensor_tags`，新sensor定义默认STOPPED，正式启用另行批准。不新增业务资产、动态分区类型或schedule |

| 必须同次迁移的调用方/消费者 | 精确修改内容 |
| --- | --- |
| 两个Raw sensor、`stock_period_update.evaluate_daily_sensor` | 20:00、前置事实、三列预检、原按日run key及显式日期；删除旧ready/水位/待办门槛 |
| `assets/stock_weekly.py`、`assets/stock_monthly.py`及`stock_period_update.deliver_asset` | 接收更新后的Raw配置，交付本频当期一文件和新原生记录；生成器保证写前范围持久化 |
| `stock_period_source`、`run_contracts/stock_period`、`io/stock_period_raw` | 显式投影与截止、周月全市场单点、完整单股请求、按键合并、当前运行资源核算；删除本轮已列明的旧缓存接续、范围索引和整股先删分支 |
| `stock_period_update.report_file_events/report_completion_events`、新op | 日更/独立op已登记真实运行内结果；首次建库迁到第13.14节专属批量登记后删除两个旧函数及旧通知解析。集中批量绑定原检查，不保留旧回执确认与JSON回写入口 |
| `stock_period_silver`、`run_contracts/stock_period_silver`、`asset_guards/stock_period_silver_readiness`、Silver两个sensor/job | 新引用、按运行读取范围、批量核原检查与实际输入、完整更新范围、从头重跑；日常不解析旧manifest或继承执行目录 |
| `checks/stock_daily_checks.py`及新`stock_trading_universe.py` | 仅提取已核实的上市/停牌集合计算，不修改股票日线生产、过滤或检查口径，保留日线原测试并验证新共用结果一致 |
| 原Raw/Silver文件checks、`stock_period_checks` | 保持原三项检查和真实物化绑定；本次结果检查由两个独立op登记，不能反过来挡日更 |
| 两个旧CLI及首次建库函数 | 首次建库保留独立用途；Raw指定股票维护改提交新历史修复job；Raw指定闭合周期仍走对应原Raw job。迁移首次建库`replay_events`对旧`completion_reference`的调用，不再创建旧交接引用；日常补事件改为完整重跑登记，不再读旧日常执行目录；删除停用CLI及旧事件补登记job |
| catalog、运行key治理、拓扑与静态门禁 | 维持四个资产、21列、原文件检查；更新本链触发、交付身份和性能说明，新任务定义、结果检查及日期/用途/频率tag纳入相应静态清单。限定DG，不修改Prod契约、Web/API或股票日线前复权计算 |

以上字段是已批准模式的实现合同，不增加自动维护动作。指定历史与身份维护使用原CLI的独立维护意图提交到同一历史修复job，不能新增自由SQL、任意路径、旧源或未经确认的证券身份。


#### 13.10.5 Silver、文件处理与性能预算

**Silver字段迁移。** `source_completion`始终为本节Raw三字段引用，不是任意文件路径。Silver物化沿原`goldenshare/silver_source`、`silver_source_version`、`silver_reference_versions`、`silver_rule`、`silver_lower`、`silver_asof`，分别保存实际使用的Raw路径、文件身份、正式参考文件身份、规则及历史下限和截至日；`goldenshare/silver_source_completion`改为实际采用的Raw三字段引用，`goldenshare/silver_execution_id`改为本次真实Dagster运行UUID。它们只描述本次物化，不用于定位私有执行目录。

Silver写前范围使用自身资产的`AssetObservation`，键`goldenshare/silver_update_scope`，字段为`version='stock-period-silver-update@1'`、`phase='planned'或'files_complete'`、`producer_run_id`（本次Silver UUID）、`freq`、`business_date`、原输入`source_completion`、适用`periods`和`periods_hash`。源范围按既有2014下限裁定；先保存完整范围再写。逐文件实际Raw引用可因合法较新交付而不同，记录在该文件物化，不能用整批最新日期替代每份输入。消费完成仍要求本次运行SUCCESS和适用范围原检查完整通过。

`stock_period_silver.resolve_update_sources(lake, freq, reference, instance, *, cancel=...)`不再接收旧回执staging参数，从当前正式文件、最新对应物化、该物化绑定的原检查和真实成功运行核实实际输入，使用物化中的新Raw引用查其完整范围。旧私有回执的父子链和版本目录删除；不另建原始文件的跨运行索引。两次批量SQL读取物化与检查的现有办法保留，按运行读取观察记录，不恢复逐文件目录及事件历史查询。

**文件处理实现约束。** `assemble`按本次验证通过的源记录一次列式归一化并按`freq/period`分组暂存；`period`只作为运行暂存目录坐标，不进入正式21列。逐个目标只读取对应源组和该份旧全市场文件，按`(ts_code,trade_date,freq)`合并；同一键源截至日不早于旧记录时采用源，较早时保留较新旧记录。源未返回的旧键保留，其他股票整行保留。不能把全部旧全市场文件合成常驻`old`表，也不能每处理一个文件都重新扫描全部源历史。候选按原21列顺序和类型写出，复用`execute`的COPY路径绑定、`validate_file`、同设备原子提升及原检查。源分组文件属于本运行的数据暂存，不是上市名单、历史范围索引或重跑状态。

文件预算除上述F份旧文件读取及F份候选写入，还须计入既有`validate_file`的schema、业务键/周期扫描及整文件SHA-256读取。提升后的原检查若未命中本次准确文件版本缓存，还会执行一次相同核验；原三项检查共用该结果，不能写成重复三次读取21列。下表四文件耗时已包含候选和提升后核验函数，不能据此省略正式实现中的原检查、fsync及资源检查，或把文件数当成实际磁盘读取次数。

指定闭合周期补齐按第13.7节完整周期覆盖规则生成全市场文件；单股回刷仍不新建缺失的整份全市场文件。独立首次建库可以从本次实际完整产出验收，但不写`baseline.json`或为日更保存建库完成标记。

独立首次建库的`replay_events`按第13.14节保留实际文件及原检查的补登记能力，本次完整产出供独立完整性审计及Silver首次建库消费；不把runless建库事件包装成真实运行UUID，不生成本节日常`DeliveryRef`。Silver首次建库仍接收其专属`execution_id/audit_report`，新日更从真实Raw运行的原生记录开始。旧交接标记、`completion_reference`及其读写者随新日常链清退，不在首次建库入口保留旧日常合同。

**本次实测。** 下表均在2026-11-11完成。只读正式输入，候选和原子替换只作用于`/private/tmp`副本；临时目录的写盘设备不是正式datasource设备，候选写入秒数不能替代正式目标盘吞吐。秒数为该次观测，不是截止保证；文件大小为字节。代码列统计的压缩列大小来自Parquet footer，不等于操作系统实际磁盘IO或缓存读取量。

| 验证对象 | 实测数量、字节及时间 | 结论范围 |
| --- | --- | --- |
| 两频全市场三列HTTP | 各5,575行、200,877 B；周0.257561秒，月0.177809秒；均截至20261110 | 字段投影、请求坐标和响应量真实有效；不表示11日全市场已更新 |
| 分页 | 每频`2行@offset0`加`2行@offset2`与`4行@offset0`逐项相同；6次分页样本均符合limit | 已验证当前HTTP端点的limit/offset行为；正式满页仍须遵守全链截止及短页结束规则 |
| 单股完整历史 | `301393.SZ`周172行/26,074 B/0.117726秒，月41行/6,600 B/0.158442秒，原21列合同通过 | 明确不传日期过滤，源日期可定位213份文件；样本不替代所有股票历史验收 |
| 当日集合与覆盖计数 | 按既有日期SQL，11月10日在市集合5,580、全日停牌7、要求5,573；两频各覆盖全部要求代码、返回2个可选代码，要求缺失、过旧和重复均0；本地读取及计数周0.265039秒、月0.014409秒 | 要求/可选集合按具体代码比较，不读取股票日线；这些计数是本次正式参考文件的观测，不作为固定股票数 |
| 周Raw代码列统计 | 1,823份；全文件共302,385,873 B，其中`ts_code`压缩列合19,258,647 B。两轮SQL统计0.503990秒、0.580941秒；枚举加stat0.029189秒 | `301393.SZ`命中172份/172行；`000016.SZ`命中0。没有读取全历史价格明细 |
| 月Raw代码列统计 | 432份；全文件共73,153,535 B，其中`ts_code`压缩列合4,049,429 B。两轮SQL统计0.071130秒、0.090114秒；枚举加stat0.005793秒 | `301393.SZ`命中41份/41行；`000016.SZ`命中0。统计进程峰值139,460,608 B |
| 源一次分组 | 213源行生成213个运行暂存周期文件，合661,737 B，0.085497秒；逐组可按原顺序完整读取21列 | 证明列式分组及按目标读取可行；该进程峰值256,802,816 B |
| 四份候选与原检查函数 | 输入为11月6日周、11月13日周、10月及11月：各5,574/5,575/5,576/5,575行，输入文件合1,811,682 B。完整重做的每文件合并、候选校验、替换及原检查共用核验函数耗时0.027619/0.029289/0.027486/0.026780秒；四份合并候选合1,243,837 B | 一份先处理后再从第一份重做四份；SQL层模拟中断重做，源响应作为固定真实样本复用。不是新job跨进程重跑端到端验收 |
| 隔离按代码移除 | 四文件各移除模拟对象一行；完整重做时第一份已无该代码，不重写，但仍验证完整原范围。其余三份分别0.021014/0.020022/0.020374秒；最后四份残留与重复均0，单文件最后计数0.000832至0.000868秒 | 股票移除只作用于临时副本，不把在市`301393.SZ`当成正式退市。列式文件验证进程峰值210,059,264 B |
| 独立价格金样本 | 取真实源当周`close_qfq=53.54`，临时旧值设54.54：截至日相同时合并得到53.5400；临时旧记录截至11日、源截至10日时保留54.5400。其他股票保持 | 值来自真实源，旧值变更为明确的隔离测试输入；验证按键更新和较新记录保护，不声称生产发生该变更 |
| 隔离HTTP worker | 三列成功、503失败、延迟三例各只发1次；用时0.169233、0.137465、1.013828秒。延迟例人为注入1秒测试截止，不是生产配置；worker峰值64,618,496 B | 复用现有独占worker，在子进程内显式三列投影接缝验证，无正式源码修改；证明单次尝试及超时清理，不声称完整新sensor已经实现 |
| 分页共用截止 | 用真实两行分页样本及人工逻辑时钟注入3秒总截止：正常三次调用分别只剩3/2.5/2秒；第二页耗尽时仅调用两次且返回未齐；预先过期时调用0次 | 验证分页共用剩余时间，不是每页重置；3秒及逻辑时钟仅为隔离测试输入，不是生产30秒配置或真实传输实测 |
| 隔离Dagster记录 | Dagster 1.13.26，真实运行`43978ad6-8898-4d74-bb8c-12d4887b0fb9`：2观察、1物化、3绑定的原文件检查及1结果检查，共7条业务记录；0.741770秒。计划在下一生成器步骤前已可按该运行读回；日期/用途/频率tag、SUCCESS筛选和cleared_codes读回通过，错误用途过滤查不到该运行 | instance、run/event storage及DAGSTER_HOME均在临时目录、遥测关闭；不是正式PG吞吐或新流程完整集成测试 |

本次有两项验证程序错误已纠正：第一次COPY未调用项目既有`execute`路径绑定，定点复制前失败；改用该函数后原字段与文件检查通过。第一次隔离Dagster启动漏覆盖DAGSTER_HOME，遥测尝试写正式`.telemetry`目录被权限拦住，未进入业务验证；明确临时DAGSTER_HOME并关闭遥测后重新验证成功，正式该目录未创建。失败事实保留在本节，原临时日志在本步收尾统一清理，不能把失败运行计作通过。

**执行量和预算计算。** 预算以实际H（本次源行数）、K（本次股票数）、F（去重目标文件数）、N（本频规范历史文件数）、源页数P及实际字节复算，不新增无依据倍率。

| 场景 | 请求、计算、存储及最后验收 |
| --- | --- |
| 当期单频 | 本样本1页三列预检，加job内1页21列正式下载；正式页的技术重试另沿原最多3次尝试。前置事实只读当天，合并1份Raw并接续1份Silver。预检各页共用30秒，末次worker清理沿现有最多两个1秒等待；到期不提交。60秒是现有sensor间隔，不能误当成每页新的请求时间 |
| K股两频历史 | 源单元2K，HTTP次数为各单元页数及既有重试实际累计；H行一次列式分组，处理F份旧Raw、F份候选和F次逐文件替换。每次只保留一个旧全市场文件的处理范围，源暂存和spill沿32 GiB/16 GiB限制。Silver只处理本次适用周期，不重复全历史审计 |
| 非零退市清理 | 本频N份代码列一次定位，再N份代码列残留核验；仅F命中文件读21列、候选和替换。当前两频各自执行的两轮代码列统计总次数为2×1,823及2×432，样本SQL累计分别1.084931秒和0.161244秒；两个频率不在同一次清理中混读。零名单N与F均不读取，仍登记结果 |
| 业务记录与读取 | 独立任务R个频率、F个交付文件时，最多F物化+3F原文件检查+R写前范围+R文件范围+R结果检查，合4F+3R条业务记录，不包含引擎和日志事件。单股样本F=213、R=2，合858条；原正式11月10日恢复已经完成8,043项原检查，原生事件容量有既有事实依据。本轮不把临时SQLite的0.741770秒套作正式PG耗时；输入按运行和周期集合批量读取，不按F增加数据库往返 |
| 一次中断再完整重跑 | 重新取所有源单元，K不变时逻辑源单元最多合4K，页/重试按实际累计；两次目标为F₁、F₂，则候选、校验和替换最多各F₁+F₂。代码列统计按2N₁+2N₂计。记录数量按两次各自完整范围计算；最后以完整本次范围核对原检查、实际文件和股票残留。退市重跑另按实际原生祖先数A计入A次运行/观察读取，找到最近写前范围即停止；这不是传感器日常历史扫描。当前源分组、单份候选及spill计入本运行32 GiB工作目录准入，旧运行剩余目录另计同设备已用空间，不能误称新旧两份执行共用一个32 GiB上限 |

在本次单股213份目标、且每文件与四份样本规模相近的假设下，仅文件合并/校验/替换部分按样本最小0.026780至最大0.029289秒逐项乘213，推算5.704140至6.238557秒；这是样本推算，不含源请求、分组、正式事件写入、Silver或最后核验，不能作为任务总耗时或上界。其他规模只按实际文件大小与行数规划，不直接乘旧总耗时或擅自加余量。新代码完成后在第6阶段测量真正链路，正式源/写湖和PG写入验收按原授权边界另行执行。

拒绝条件直接沿现有响应、源单元、内存、工作目录、spill及完整交付限制；预检过期或源不齐等待，job资源不足或原检查失败按原规则报错，后续从头重跑。不能自动抬升4 GiB默认进程额度，不能把本次样本或旧单次恢复额度推广成全规模性能保证。

#### 13.10.6 四项对账与开工复核

| 第13.9节事项 | 本步结果 | 编码及回归必须落实的位置 |
| --- | --- | --- |
| 预检入口 | 第13.10.2节已定稿；真实三列及分页、现有worker投影接缝/无重试/截止验证完成 | 新readiness、共用集合SQL、`HttpPage`和请求构造；正例含新股、全日停牌有/无/较早记录，反例含缺码、同数换码、旧日期、重复、字段不符、满页和到期 |
| 交付及运行参数 | 第13.10.3及13.10.5节字段、版本、生成器写前边界、原范围重跑、原三项检查绑定和Silver读取已定稿；隔离原生记录读回通过 | 新delivery合同、Raw/Silver生产与读取、两个独立op、既有CLI；同步清零旧引用，不保留旧JSON兼容。验证生成器先保存范围、零结果、完整范围重跑及真实物化绑定 |
| 新定义 | 第13.10.4节两个job、两个sensor、op、配置和消费者已明确；修正清理job Raw前缀 | Definitions、分类tag、运行key、catalog中的既有合同说明及静态清单。自动模式只监听两个当期Raw，人工维护不挂新sensor，周/月清理分别提交 |
| 性能 | 第13.10.5节按真实响应、全历史代码计数、四文件处理、源一次分组及原生记录验证，写清正常、一次完整重跑和最后验收成本 | 资源核算必须分别覆盖本运行源与候选及spill、本设备已占用的旧运行目录，以及事件；回归限制按实际H/K/F/N和现有资源，不引入未批准的自动扩大或源请求 |

**最终审计记录。** 已逐项复核第13.2至13.10节、原方案第10.19节、月线第11节及运行契约、运行key和拓扑引用。预检、当期Raw/Silver、两频复权因子回刷、单频退市清理、人工补做、首次建库及旧实现清退的输入、输出和消费位置均有对应；同日自动回刷和指定原日补做的参数区别已写明。10次真实HTTP及四份隔离文件结果已逐项核对，分页共用截止和原生记录能力验证通过；新增引用检查、`check_docs_integrity.py`及本次文档`git diff --check`通过。测试仍只证明本节明确的现有能力和隔离边界，不是新流程源码或正式任务验收。正式股票周月链源码未修改，未重载或提交正式任务。

**复核结论。** 四项编码前准备已补齐；第1阶段完成，具备进入第2阶段源码开发的条件。新流程的正式实现、端到端集成及上线验收尚未执行，后续逐阶段按本方案实施并对账。这里的“可开工”只指相应源码开发，不等于允许重载正式code location、启停sensor、执行正式job或改写Lake。

<a id="stock-period-stage-two-results"></a>

### 13.11 第2阶段实施约束与验收

2026-11-11管理员批准提交第1阶段文档，严格按LLD完成第2阶段，再独立审计。本阶段接通当期Raw和同频Silver，不实现第3、4阶段的独立历史回刷与退市清理job，不执行正式任务或重载。以下为第13.2、13.4及13.10节在本阶段的具体实现映射。

| 硬口径 | 代码落点 | 正反验收 |
| --- | --- | --- |
| 20:00后、当日开市、本频未提交才请求源 | 两个Raw sensor、周月时间策略、`stock_period_update.evaluate_daily_sensor` | 时间前、休市、重复提交源请求为0；一频已提交不阻断另一频 |
| 应更新代码来自已验收生命周期及最终停复牌；新股必需，全日停牌可选 | `stock_trading_universe.py`提取日线集合SQL；`source_readiness/stock_period.py`验证前置事实、准确文件版本并计算集合 | 当日上市、未来上市、退市边界、盘中停牌、全日停牌三种返回及空停复牌分区；日线原检查口径保持 |
| 三列预检及21列正式下载使用同一周期单点；分页共享截止 | `run_contracts/stock_period.py`、`stock_period_source.HttpPage`及新readiness | 周五/自然月末、字段、分页、重复页、缺码、同数换码、旧日期、未来日期、预先过期及页间过期；正式下载原重试保持 |
| 当期只写本频一文件，无共享待办与单股历史 | `stock_period_source.capture_current_period`从头取本次源页；`io/stock_period_raw.assemble_period/publish_period`按键合并与提升；Raw生成器保存写前范围 | 无旧JSON亦可运行；新建当期、可选缺席保留旧记录、较新旧记录保护；失败后新运行重新请求，不复用旧源页或候选；另一频和旧历史文件保持 |
| 原生交付和原检查绑定，Silver完整消费 | 新delivery合同及guard、`stock_period_silver.resolve_update_sources/deliver_update_asset/evaluate_update_sensor` | 真实运行UUID、范围摘要、SUCCESS及全部原检查缺一不承认；来源更新按合法后继处理；完整范围Silver从头重做、不同业务日不伪造完成 |
| 所有本阶段消费者同迁，不保留旧日更合同解析 | Raw/Silver配置、四个资产包装、四个job、原文件检查、catalog、静态门禁及Silver CLI更新分支 | 更新配置拒绝旧执行ID/续跑参数；旧`read_completion`删除。Silver CLI仅保留首次建库分支，日更改走原生job整批重跑；其余第13.7节旧Raw维护及首次建库清退仍在第5阶段完成 |

单文件当期处理不能调用会读取`copy.json/committed/complete.json`跳步的旧组装及提升入口，故在原IO模块新增无续跑分支的单文件函数，复用原字段、文件校验、设备、资源及原子替换规则。新源页CSV及候选仅是本运行数据暂存，不写业务进度JSON。新运行使用真实UUID目录，从第一步重新取源。

Raw入口先核对显式日期与分区，再保存由配置派生的日期/用途/频率tag，之后才读取上游与请求源。日更sensor用原自动run key识别尚未开始的自动提交；再按本job、显式业务日期和`kind=daily`识别已执行的手工运行，已有当天提交或完成时不再预检和重复提交。两种精确检索各最多一条，不扫描历史运行，不把人工闭合周期当成当日日更。

原生交付guard按明确生产运行集合读取观察、物化及检查，并核对真实成功运行；一组引用用集合查询，不能逐文件查询。单引用仍可按运行API读取，多份实际Raw来源按运行集合批量读取并在本次调用内复用；不创建持久化索引。Silver沿两次`batch_event_evidence`集合查询核对实际最新物化及原检查；旧来源被较新合法Raw替换时，批量核实后者真实交付，不读取旧回执目录。Silver自身写前/完成范围存原生观察；只有本次SUCCESS且原检查全部通过，sensor才推进该Raw通知的消费位置。失败保留通知，手工以相同原业务配置完整重跑成功后销账。

Silver为准确找到手工整批重跑后的消费结果，在验证后的入口写入派生运行tag`goldenshare/stock_period_source_batch`，值严格取原输入`source_completion.upstream_batch_id`；命名和构造仍集中于delivery合同，不新增运营输入或修改共用请求builder。sensor按原Silver job、该tag及SUCCESS检索一条，再核对真实范围、原输入引用及该次物化绑定的全部原检查。它不以运行key代替交付，不要求手工新运行携带自动run key，也不按业务日最新一笔猜测已经消费；不是另一套完成状态。读取范围为这一笔匹配运行的原生事件，旧成功输出被合法后继更新后仍保留已消费事实。Raw每频写前/完成观察各一条，Silver sensor每tick至多取这两条通知相关观察，忽略写前观察，不做全历史事件扫描。

性能沿第13.10.5节：当期每频预检与正式下载按实际页数计、各一份Raw/Silver；历史交付的Silver只处理引用中满足2014下限的F份文件。原生记录只按明确运行及分区集合读取；输出物化F条、原检查3F条、范围观察2条，不将事件ID放入运行参数或去重身份。一次中断加一次重做按两次实际文件范围分别计入源、候选、原检查及最后验收，默认内存与磁盘限制保持。临时instance、测试Lake、staging、DuckDB spill、pytest输出和DAGSTER_HOME统一放本任务`/private/tmp`目录，关闭遥测；不使用正式资源跑测试。

实现后运行本阶段单元/契约、真实生产者到Silver的隔离集成、日线集合原回归、源传输、四资产定义及相关静态门禁。源合同继续复用第13.10节真实三列分页与21列样本证据；仅补新实现尚未验证的有界只读边界，不重复全历史读取。独立审计只看已批准第2阶段，逐条检查本表和第13.10节对应合同，发现问题先修正再复验；不把第3至6阶段未实现项当成本阶段已完成。

**旧测试迁移范围。** 本阶段已经替换的合同不再由旧行为断言约束。不是删除字段、价格或日期金样本；原21列字面夹具、Silver投影、首次建库、候选原子提升和检查绑定的有效测试继续保留。首次完整相关回归发现旧合同断言失败，按下表逐项迁移，不能用skip保留失败，也不能恢复旧实现迎合断言。

| 旧测试位置 | 退出的断言及保留边界 | 新验收位置 |
| --- | --- | --- |
| `test_stock_period_silver_original_recovery.py`、`test_stock_period_silver_sensor_recovery.py` | 整个文件只测试旧私有执行ID、父子执行目录、完成回执及仅补事件的续跑，随实现退出 | `test_stock_period_native_daily.py`的多文件中断、完整手工重跑、原通知销账及原生检查完整性 |
| `test_stock_period_silver_execution.py`、`test_stock_period_silver_events.py` | 删除日更复用旧候选、已完成文件、继承回执及只补事件部分；保留独立首次建库的执行、取消、恢复、字段及原检查用例 | 新Native日更测试覆盖全部文件重做及绑定；原首次建库用例保持 |
| `test_stock_period_silver_sensors.py`、`test_stock_period_silver_daily_integration.py`、`test_stock_period_silver_jobs.py` | 退出依赖旧日更回执和旧cursor的编排断言，保留定义、job选择、批量检查读取和独立建库 | 新合同版本、原通知、稳定run key、原检查缺失/错绑拒绝、后继Raw及手工成功结果的测试 |
| `test_stock_period_cross_day_asof.py`、`test_stock_period_followup_silver.py` | 退出按旧回执读取Silver日期及目录续跑的部分；保留Raw来源日期、正常首次建库及只读metadata检查 | 新Native测试验证原意图日不变、实际来源日期逐文件保存、较新合法Raw接续、缺失及未来来源日期拒绝 |
| `test_stock_period_daily_delivery.py`、`test_stock_period_daily_memory.py`及两个Raw sensor测试 | 退出缺省使用当前时钟、旧当前文件目录证明、混合历史入口、继承8 GiB运行标签、19:30和旧共享待办提交；未替换的旧Raw离线实现用例不在本阶段整体清退 | 新配置拒绝旧参数、20:00、当前分区、原默认资源、无旧JSON、当期单文件、正式21列复核及整批重取源 |
| 源请求、Raw手工历史和旧端到端fixture的相关用例 | 月线全市场断言及模拟HTTP改为自然月末`trade_date`；SDK旧`intent=history`退出，独立建库CLI仍保留其现行校验 | 原源合同测试按已验证参数校准；当期真实Raw到Silver的隔离链路使用新Native测试，不冒称第3阶段回刷已实现 |

#### 13.11.1 实现结果、验证边界与独立审计

**第2阶段完成。** 第1阶段文档先提交为`d971f60e5`，随后按本节完成当期Raw/Silver实现。新增`stock_trading_universe.py`、`source_readiness/stock_period.py`、`run_contracts/stock_period_delivery.py`及`asset_guards/stock_period_delivery.py`，分别承载共用股票集合、源齐备检查、原生交付合同及交付读取。原四个资产和job名称、21列及精度、文件路径、Silver历史下限和原检查保持。Raw/Silver生成器、配置、catalog说明及Silver CLI消费者已同步迁移；旧Silver日更私有回执、恢复分支和仅补事件的测试已按上表清退。旧Raw离线维护与独立首次建库的其余清退继续按第5阶段处理，没有将未完成项计为本阶段完成。

| 核验 | 本轮结果与实际覆盖 |
| --- | --- |
| 周月链完整相关回归 | 最终当前版本的完整`test_stock_period*.py`及两份Raw sensor测试共529通过、2项原有PostgreSQL实验未启用，116.97秒。未启用项不能作为PostgreSQL验收。原21列字面样本、Silver价格投影、首次建库和仍有效的离线测试保留 |
| 新流程隔离集成 | `test_stock_period_native_daily.py`和`test_stock_period_readiness.py`共37项，由独立审计者另行执行全部通过，7.02秒。运行真实临时Dagster Raw/Silver job、DuckDB及Parquet；HTTP与上游验收查询被替换，临时输入按已核实的生命周期、身份和最终停复牌投影合同构造，不能称为正式上游生产者或端到端生产验收 |
| 三列HTTP传输 | 补充真实本机HTTP worker的三列投影测试后，整个`test_stock_period_source.py`为11通过，2.57秒。验证实际worker传参和响应字段；共享截止另由readiness测试验证。网络服务为临时本机fixture，Tushare真实字段与日期合同继续使用第13.10.5节的有界证据，不冒称本次重新核实全市场齐备 |
| 原日线共用规则 | 通过受保护隔离runner执行`test_stock_daily_raw_checks.py`，22通过；仅提取集合SQL，原日线准入及检查保持 |
| 运行合同门禁 | 同一隔离runner执行`test_run_contract_static_gates.py`，113项及5个subtest通过；未绕过runner。月线策略新增导入共用周期开始时间，runner仅增加该精确源码文件的读取许可 |
| 静态检查 | 本阶段源码和测试的致命语法及未定义符号检查通过。以orchestrator目录现行Ruff配置检查全部本阶段文件，剩余11条均在`run_contracts/configs.py`未修改区域，与HEAD基线逐条相同；没有以修改其他配置检查来消除告警 |
| 额外全局治理套件 | 资产治理在第1批出现1失败、4通过后停止；检查治理在第1批出现1失败、1通过后停止。两项均为`gold_major_index_quantitative_structure`已在目录登记，但旧测试资产清单及检查治理映射遗漏。不能记为两套件通过，也不能据此认定实际Dagster资产未注册 |

额外治理失败已由独立审计补查：该数据集于`a4bebf883`引入，早于本次文档提交；`d971f60e5`与核验时HEAD的目录blob同为`817f61316eb905e460284b0db60f5c71c7ec1c4e`。按本任务开始时差异在内存重建的目录blob为`68804318c891ebf5688a71bce5de60abef9bc51f`，匹配原补丁目标；这三份目录与当前目录中的该资产登记语法一致，两份失败测试均与HEAD逐字节一致，且未在任务开始时的差异中。本阶段没有引入这两项清单遗漏，也未越界修复。全局治理尚未全部通过的事实保留。

**独立审计结论。** 非实现者按第13.2、13.4、13.9至13.11节、原方案第10.19节和月线第11节逐项核对当前源码，使用CodeGraph的`codegraph_explore`、`codegraph_impact`及直接源码读取确认四个资产、源请求、配置、原检查、原生交付guard、Silver消费、CLI及测试消费者；未发现第2阶段需修正的实质问题。审计另行确认手工Raw成功后不再自动重复提交、无自动run key的手工Silver整批重跑能够按原输入销账、合法较新Raw逐文件接续且原意图日不变。CodeGraph索引已同步并核对状态；本次没有Prod、前端或API消费者变更，不存在待人工确认的跨工程调用边界。

**第2阶段完成时的交付边界（历史，当前见第13.13节）。** 当时结果只代表第2阶段源码及隔离验证完成。第3阶段独立复权因子回刷、第4阶段单频退市清理、第5阶段剩余维护入口及旧实现清退、第6阶段整体接通和正式验收均未实施。未部署、重载正式code location、启停sensor、提交正式job或改写正式Lake、Prod、实例状态。测试和审计临时材料在工程外创建，有效结果写回本节后清理；不保留重复过程报告。

<a id="stock-period-stage-three-results"></a>

### 13.12 第3阶段实施约束与验收

管理员批准严格按本LLD完成第3阶段并独立审计。本步实现`factor_changed`独立回刷及两频Silver接续；第4阶段退市清理、第5阶段人工指定历史/身份维护及剩余旧入口清退、第6阶段整体切换继续保持各自边界。本步不启用正式sensor，不重载或提交正式任务，不安装依赖，不读取全市场历史明细。

| 已确认要求 | 本步实现位置 | 验收 |
| --- | --- | --- |
| 同日两频完整成功后才提交，两种完成顺序使用相同去重身份 | 新`sensors/raw_stock_period_history_repair_job_sensor.py`；新`stock_period_history_repair.py`按job、日期及daily tag查另一频SUCCESS，再集合读取两份原生交付 | 单频/失败/错误日期/非daily不提交，闭合周期及回刷自身不触发；顺序反转、手工日更无自动run key、Raw成功而Silver尚未完成仍可提交；不读取历史行情 |
| 相邻开市日Silver股票复权因子比较；新股不进入变化名单 | `stock_period_history_repair.load_factor_changed_codes`复用原比较SQL和代码摘要；日历取指定日及其前一个SSE开市日 | 独立字面因子样本，节假日前一开市日、变化/未变/新股；op重算名单及摘要，不匹配则源请求和正式文件变更均为0。不增加重复上游验收要求 |
| 日期、名单、摘要、周/月固定顺序和两份真实引用显式传入 | 新`run_contracts/stock_period_history_repair.py::StockPeriodHistoryRepairConfig`及builder；新job/op按第13.10.4节命名 | 配置拒绝旧执行ID、额外参数、错误频率/引用顺序/摘要；自动模式只接受同日daily。op支持第13.10.3节指定原日补做所允许的已核实后续覆盖引用，人工CLI在第5阶段接入 |
| 单股只用代码及频率取完整21列历史，新运行从offset=0重取 | `stock_period_source.capture_stock_history`与当期下载共用无续跑分页内核 | 保留既有HTTP、精度、身份、分页、重复及源容量校验；不得调用有`active_chain/complete.json`接续的旧`capture_unit`。一运行一个传输实例，跨股票和频率共用原限流；失败重跑全部源单元 |
| 按源日期定位，只处理已有全市场文件；一次源分组、每次一个旧文件 | `io/stock_period_raw.group_history_sources/assemble_history_period`；新回刷helper组织执行 | DuckDB一次按频率/周期写运行暂存组；写任何候选前确认全部目标存在及来源日期合法。按键合并、保留未返回旧键/其他股票及较新记录；缺文件不新建、不提前删整股；不加载全部旧历史为常驻表 |
| 写前完整范围，逐文件原子提升，本次全部原检查及结果后才完整交付 | 新op使用原生生成器；复用`delivery_work/delivery_completion`、候选校验和`publish_period`；按本运行一次读取物化后批量绑定原三项检查 | 两频实际范围先保存再写；真实UUID、逐文件来源日期、原检查绑定；零变化仅记录两频零结果，不取源、不写文件、不发完成观察、不触发Silver。结果检查沿第13.10.3节，不加入日更原三项检查集合 |
| 任意中断后按原业务范围整批重跑；两频Silver各消费完整范围 | 复用第2阶段原生交付guard及Silver入口 | 三文件首份写后失败、原子替换后事件登记失败、成功后Silver接续、Silver失败整批重跑；重跑使用新UUID，不读旧源页/候选/JSON，不跳过前次文件。回刷失败不阻断下一日日更 |

**已有实现及替换边界。** 旧`capture_unit`、`assemble`和`report_file_events/report_completion_events`仍服务待第5阶段迁移的独立首次建库及旧离线入口，含私有回执、范围索引、整股先删和全旧行情表，不能供新job调用。新历史分页与当期分页提取同一无续跑内核；新IO只处理本次源分组及单个目标，复用现有字段、连接、执行器、候选校验、资源限制及原子提升。旧离线消费者不迁进新链，也不增加旧合同兼容解析。新job使用真实运行内事件，旧runless补事件入口不参与；后续第5阶段按第13.7节统一清零旧入口及不再使用的代码。

**配置及读写。** 仅新增上述运行配置；初期只开放本阶段`factor_changed`意图，人工其他模式在第5阶段同步扩展其生产者与消费者，不先暴露未实现模式。资源、端点、凭据、限流、内存、spill和工作目录限制沿第13.10.2节，不新增env或运营开关。sensor使用Dagster自有运行状态cursor、默认STOPPED、分类`quote_data/raw/asset_update`，一次成功通知最多返回一个请求；查另一频最多一条运行，原生交付按两运行集合读取，因子比较只读指定相邻两日，不扫全历史。op仅在当前真实UUID的正式staging目录保存源原文、CSV、分组Parquet和候选，不写私有进度JSON；按源定位的正式Raw目标逐文件替换，Silver走已有独立入口。

**性能与失败预算。** 沿第13.10.5节实际H/K/F/P及字节模型：2K源单元、H行一次分组，每次一份旧目标及一份候选，F份交付及原检查；业务记录为4F+3R，非零两频R=2。一次中断加一次整批重跑按各次实际源、候选、事件、Silver及最后验收分别核算，旧运行占用计入设备空间；不继承单次6/8 GiB例外，不增加无依据容量常量。源日期不得晚于执行上海日；全部所需文件缺失检查在候选前完成，资源不足、源合同或原检查失败则本次失败，后续从头重跑。新IO使用第13.10.5节真实单股213条及四文件合并样本作为行为和规模依据；临时集成只证明其明确的替身/真实文件边界，完整正式性能仍在第6阶段获准范围验收。

**开发前复核。** 已用CodeGraph及当前源码核对源分页、IO、原生guard、日线复权因子比较、四个资产和Silver消费者；第2阶段前置实现可复用，需替换的旧历史能力按上表隔离。测试和审计材料只放本任务`/private/tmp`目录，关闭遥测及字节码输出。新定义、结果检查、分类和运行key说明同步原运行契约、拓扑及相关静态清单；测试夹具沿真实生产者字段和已有21列字面样本，价格及名单expected独立填写。完成后非实现者独立审计本表、当前源码和隔离结果，有问题先修正再复验。


#### 13.12.1 第3阶段实现、测试与独立审计结果

**第3阶段完成。** 新历史修复配置、job、op、sensor和`stock_period_history_repair.py`已接通；新sensor按同一业务日两频Raw完整交付提交，使用固定周/月引用顺序及通用上游run key。op沿日历及原SQL重算变化名单与摘要，单股历史使用`capture_stock_history`，与当期下载共用无续跑分页内核。`group_history_sources`一次分组并在候选前检查全部目标，`assemble_history_period`复用单文件按键合并及原子提升，另一频当期和无关股票不受影响。逐文件物化后一次读取本运行的物化集合，登记绑定的原三项文件检查、两频完成范围及结果；零变化仅两条结果检查。`rewritten_row_count`统计实际重写的完整候选文件行数合计，不把它解释为复权因子变化股票数或源刷新行数。

| 核验 | 结果与证据边界 |
| --- | --- |
| 完整周月线回归 | 当前版本40份相关测试文件，559通过、2项既有PostgreSQL实验未启用，141.77秒；包含原21列、精度、身份、源分页、当期Raw/Silver、独立首次建库及仍保留的旧离线能力，不把未启用PG实验计为验收 |
| 本步新增隔离链路 | `test_stock_period_history_repair_native.py`29通过，25.55秒。使用真实临时Dagster job、DuckDB及Parquet，HTTP和上游验收查询替换。覆盖两种回调顺序、无自动run key的手工日更、单频等待、非daily拒绝、13股变化与新股分离、名单不符、零回刷、三文件中断、替换后登记前失败、源和文件全部重做、原三项检查绑定、两频Silver、Silver失败重做、较新记录保护、源未来日期、目标缺失、原日采用后续已验收覆盖及失败后次日日更。实际sensor资源注入单独验证 |
| 源传输及预算边界 | 新增真实本机HTTP worker测试验证21列和`ts_code+freq+limit/offset`，无日期过滤或私有分页回执；纳入559项。源分页从offset0整批重取，原源合同、响应和资源限制沿原测试。sensor实际断言两次`get_runs`的limit分别为1和2、一次两运行原生事件集合读取，无历史源调用。源真实合同和单股213条行为复用第13.10.5节有界证据；本步未重复请求真实Tushare |
| 定义与静态门禁 | 受保护runner执行运行合同113项及5个subtest通过；仅在原静态清单登记新sensor身份，分类用原枚举及helper，没有削弱检查。新增及修改的本步Python默认Ruff检查通过，致命语法和未定义符号检查通过；文档完整性及本步差异检查通过 |
| 独立审计 | 非实现者用CodeGraph explore/callers/impact及实际源码核对本节、前述业务口径与消费者，另行隔离回归61项通过，31.67秒；相关8份Python文件Ruff通过。61项与559项有重叠，不相加；未发现第3阶段需修复的实质问题。审计者自己的临时材料已清理 |

首次新链回归有17通过、1失败：我错误地把普通sensor的`required_resource_keys`用于`run_status_sensor`，导致新sensor定义加载失败；已按官方资源注入方式改为带类型的`LakeRootResource`参数，并补实际调用验证。随后扩展测试中又误用了旧`get_job_success_event`方法，影响测试夹具而未影响job实现；核对本机API后改为`get_run_success_event`，最终全部通过。失败记录不计入通过结果。官方资源方式见[Dagster sensor资源文档](https://docs.dagster.io/guides/automate/sensors/using-resources-in-sensors)。

**第3阶段完成时的影响面与未执行项（历史，当前见第13.13节）。** CodeGraph及当时调用方审计限DG源下载、单文件IO、原生交付、原三项文件检查、四个资产及Silver接续；新job/sensor/config加入当前Definitions加载路径，无Prod、前端或API消费者变化。当时第4阶段退市清理、第5阶段人工指定历史/身份维护及剩余旧实现清退、第6阶段整体切换尚未实施。旧Raw离线及首次建库分支按本节既定边界保留，新job完全不调用其进度JSON、范围索引或回执函数；没有增加旧合同兼容解析。

本轮只完成源码和隔离验收，未部署、重载、启用正式sensor、提交正式job、写正式instance/Lake/Prod，未安装套件或扩大正式读取。所有测试实例、数据、spill和日志均在本任务工程外临时目录；结果写入本节后清理，不遗留工程内过程文件。新的sensor定义默认STOPPED，正式切换仍需独立批准。

### 13.13 第4阶段实施约束与验收

管理员批准按LLD完成第4阶段并独立审计。本步仅实现第13.8节的单频退市清理，不推进第5阶段人工维护/剩余旧实现清退和第6阶段正式切换，不执行正式清理、启用sensor或新增套件。

| 已确认要求 | 本步代码落点 | 正反验收 |
| --- | --- | --- |
| 周Raw当期成功只清周，月Raw当期成功只清月；同日去重沿本频上游引用 | 新`sensors/raw_stock_period_retirement_cleanup_job_sensor.py`、`stock_period_retirement_cleanup.evaluate_retirement_sensor`；第13.10.4节既定job/op/config文件 | 仅一频成功即可提交；两频分别提交；非daily、错误业务日或原检查不齐不提交，清理自身不回触发；日期取原运行配置，手工日更无自动run key仍能识别 |
| 只确认退市股票，完成名单每频独立累计 | 新`stock_period_retirement_cleanup.load_confirmed_retirements`和`asset_guards/stock_period_retirement.py::latest_retirement_result` | Raw股票基础数据与Silver股票生命周期均确认D，证券身份confirmed且为CNY；已确认别名映射到同一退市证券，当前仍在市证券不因旧代码D被删除。sensor减去本频累计已完成代码，op只核对配置完整名单仍被确认，不再次减去已完成名单或扩大范围 |
| 结果读取不扫描历史行情或整批原文件检查 | 新retirement guard按清理job、频率tag及SUCCESS检索最后完成的一条运行（`get_run_records(order_by="end_time", ascending=False, limit=1)`），按该运行及结果check名从原生check索引定向读一条结果 | 核对版本、频率、生产run、passed及两份代码摘要；跨业务日累计，不按当天过滤，不以缺失结果当作零结果。无历史完成事实时从空集合开始，不假定旧清理已完成；旧结果交接仍在切换阶段核准 |
| 按代码统计本频所有规范历史文件，只改命中文件 | `io/stock_period_raw.count_retirement_rows/assemble_retirement_period` | 无名单时不枚举历史；非零用DuckDB只投影代码和文件名统计匹配数，不按上市日期截断；仅完整范围内的文件读取21列，其他股票原样保留，未命中文件不生成候选、不替换；另一频不读写，不请求Tushare |
| 中断后从头核算，同时保留原命中范围 | `asset_guards/stock_period_retirement.py::parent_retirement_scope`、新op | 沿真实Dagster parent_run_id查最近同业务日、频率、代码摘要的写前范围，与本次新命中取并集。无写前范围的祖先跳过；不读旧私有JSON、候选或逐文件进度。已无待删行的原选中文件仍完整验收和交付，不重复替换。测试使用真实父子运行及全部步骤重执行，不以模拟parent字段代替持久化关联 |
| 原检查及Silver按完整本频范围接续 | 新`raw_stock_period_retirement_cleanup_job/op`复用现有原生交付、原三项文件检查、候选校验和`publish_period` | 先持久化完整范围，再逐文件原子替换；本次所有物化后一次集合读取绑定，原检查、残留核验全部通过才发完整范围和结果。同频Silver接续；空文件合法，source_asof=None只用于空文件；清理全部股票后Raw/Silver为空仍能正常交付 |
| 零清理及累计结果 | 新op结果采用第13.10.3节字段及本频`cleared_codes/cleared_codes_hash` | 零名单只有本频结果，不读历史或发文件完成通知。非零名单却无物理命中也记录已核实结果，无文件完成通知；完整成功后才把本批名单并入本频最新成功累计名单，失败不得提前销账，后续业务日仍能识别未完成对象 |

**现有能力和迁移。** 第3阶段的候选提升、真实UUID原生交付及Silver接续直接复用，不能调用仍依赖旧范围索引的`assemble`或混合日更清理。新IO的删除与第3阶段按键合并职责不同，仅新增本步所需函数。两类成功sensor共用的Raw job→频率、显式日期及daily意图解析提取到`run_contracts/stock_period_delivery.py::raw_daily_run_intent`，同步迁移第3阶段调用方并回归其触发语义；不复用两频齐备或股票复权因子比较。原结果读取通用函数会返回本运行全部文件检查，本步新增定向结果guard，避免在sensor中读取3F项原文件检查。其余资产、原三项文件check、21列、精度、路径和Silver下限保持；默认STOPPED，分类沿既有枚举与helper。

**配置与读写。** `StockPeriodRetirementCleanupConfig`仅含已批准业务日期、频率、股票名单/摘要、本频Raw引用，额外字段拒绝；日期、用途和频率tag从验证后的配置派生。无新env、数据库表、状态文件或运营开关。候选和spill仅放真实run UUID的正式staging目录；实际Raw按本频逐文件提升，结果写原生事件。同频历史代码统计读取`ts_code`，不读取另一频或Tushare；候选、检查和Silver只覆盖本次完整范围。别名展开只使用已确认证券身份，结果名单及摘要记录原配置的证券代码，不以物理别名另造完成身份。

**性能及失败。** 资源沿第13.10.2节现值和第13.10.5节实测，不继承旧单次6/8 GiB例外。sensor一次成功通知最多提交一个请求，原Raw交付按其运行读取；累计结果最多一次limit=1运行查询和一次按run/check索引的limit=1结果读取，没有全历史事件查询或行情扫描。非零任务每次对本频N份规范文件的代码列统计两轮；仅命中和原范围并集内的文件做完整校验，实际仍有待删行的文件才COPY和替换。重跑时“完整验收文件数”和“实际改写文件数”分别计算，不能因为原文件已删完就漏算其验收、物化、原检查及Silver成本；一次中断加一次重做按两次实际N、完整范围、实际改写及原生祖先数分别累计。R=1的非零完整交付沿4F+3条业务记录，F按完整交付范围计；无文件范围时仅1条结果检查。空间同时计入当前候选/spill和同设备旧运行占用。没有新正式吞吐测量，旧四文件及代码列统计只作开发依据。

**验证及授权。** 以既有`000016.SZ`和`920799.BJ`已核实合同构造明确的隔离样本，后者在测试中声明为D以验证上市前记录，正式在市证券不删除；字段按真实Raw股票基础数据、Silver生命周期/身份生产者及原21列夹具核对。覆盖周/月、零名单、零命中、单频隔离、未命中不替换、迟到退市、最新累计结果（含先创建后完成的串行任务）、失败未销账、真实父子整批重跑、无写前范围祖先、原三项检查绑定及同频Silver。复用第3阶段源与原生链测试；本轮不读取正式全历史明细或执行正式job。测试及审计临时材料只放本任务`/private/tmp`目录，关闭遥测及字节码；最终独立审计及有效结果写回本节后清理。


<a id="stock-period-stage-four-results"></a>

#### 13.13.1 第4阶段实现、测试与独立审计结果

**第4阶段完成。** 新`raw_stock_period_retirement_cleanup_job`、op、成功事件sensor及配置已接通。周Raw当期成功只提交周清理，月Raw成功只提交月清理，不等待另一频。确认名单来自Raw股票基础数据、Silver股票生命周期及已确认身份；旧代码退市但仍映射至在市证券时不清理该在市证券。sensor减去本频累计已完成名单，op按配置完整名单执行，不临时缩小范围。物理别名只用于删除匹配行，结果仍记录原证券名单。

`count_retirement_rows`对本频全部规范文件只做代码列计数，不按上市日期截断；候选只针对仍有待删行的文件。`parent_retirement_scope`沿真实原生父链保留最近同日期、频率和摘要的原范围，重跑重新统计并取并集；已删完的原选中文件不重复替换，但重新校验、物化、绑定原三项检查并完整交付同频Silver。没有私有JSON、每股历史索引或逐文件跳步。零名单不枚举历史；非零无命中也只记本频核实结果。结果在完整验收、最后代码残留为零后登记，成功后才累计清理名单。

| 核验 | 结果与证据边界 |
| --- | --- |
| 完整周月线回归 | 当前41份相关测试文件（`test_stock_period*.py`及两份Raw sensor测试），600通过、2项既有PostgreSQL实验未启用，187.24秒。包含第2、3阶段、源传输、原21列与精度、首次建库及仍保留的旧离线能力；未启用实验不作为PostgreSQL验收 |
| 第4阶段隔离链路 | 新`test_stock_period_retirement_cleanup_native.py`共41例，均纳入600项。覆盖两频触发、单频成功即可提交、非daily及递归拒绝、原检查不齐拒绝、确认身份与别名、零名单无枚举、非零无命中、未命中文件及另一频不变、上市前记录、全空文件、迟到退市、跨日累计、完整配置重放、真实父子运行中断与替换后事件前失败、无范围祖先、原范围全部交付、原检查绑定、同频Silver及残留/命中文件校验失败不销账。测试使用真实临时Dagster运行、DuckDB与Parquet；HTTP及上游验收查询沿原夹具替换，不称为正式源或生产验收 |
| 定向读取与重跑预算 | 实际断言累计结果只发一次limit=1运行查询和一次run/check定向索引查询，不读取本运行全部原文件检查；只读本频，两轮代码统计。写前范围先于首份候选持久化；重跑首文件保持inode/版本而完整登记3份Raw，Silver按已有2014下限接续2份，非零文件改写数和完整交付数分别统计 |
| 静态与文档门禁 | 受保护runner的15批运行合同测试113项及5个subtest通过；只新增sensor精确身份，不削弱静态规则。11份本步新增/修改Python文件默认Ruff通过；全`src/tests`致命语法及未定义符号检查通过。文档完整性及本步差异检查通过，CodeGraph已sync/status确认索引当前 |
| 独立审计 | 非实现者用CodeGraph explore/impact/status及当前源码核对配置、触发、真实基础数据/生命周期/身份生产者、两轮代码统计、原子提升、父链、结果索引、原检查和Silver消费者。独立第4阶段41例通过，45.38秒；另行第3阶段29例通过（其与最初3份新增用例合跑32例，27.06秒）。测试与600项有重叠，不相加。新增3例已保留在正式回归中；最终未发现剩余实质问题，审计临时目录已清理 |

**发现的错误及修正。** 我最初用默认创建顺序读取最新SUCCESS结果，这个实现错误会漏读较早创建、较晚完成任务的新累计名单。真实串行反例先创建C任务，再完成B任务，最后执行C；C的结果包含B和C，而旧guard只返回B。现已改用`get_run_records(order_by="end_time", ascending=False, limit=1)`，结果查询预算保持不变。反例修复前因确实遗漏C而失败，修复后通过；独立审计确认修正。该排序API与本机SQL存储实现已核实，参数含义见[Dagster实例API](https://docs.dagster.io/api/dagster/internals#dagster.DagsterInstance.get_run_records)。静态清单也已登记新sensor，受保护门禁通过。

新增测试中，我曾漏导入测试常量、导错测试使用的`InMemoryJob`位置，并把失败blocking检查的真实运行状态错误地期望为SUCCESS；这些是测试错误，已按本机API及实际Dagster状态修正，失败结果不计通过。独立审计者曾直接执行受保护的静态consumer suite，执行方式违反其规定入口；该项证据已明确撤回，本节静态结论只使用主线受保护runner的重验结果。未通过削弱检查、跳过错误或恢复旧实现来消除失败。 本轮检查曾写入工程内Ruff缓存及相关字节码，这是执行错误；收尾已清除本轮写入的缓存文件和相关新字节码，未删除共享解释器或依赖。

**影响面和未执行项。** 本步仅变更DG单频退市清理、共用daily运行解析、单文件IO、原生结果读取及对应Definitions、catalog、静态门禁和原文档；第3阶段解析调用方同步迁移并回归。CodeGraph及直接调用方核对没有Prod、前端或API消费者变更，没有待人工确认的跨工程调用边界。第5阶段人工维护及剩余旧实现清退、第6阶段整体验收与正式切换尚未实施。旧Raw离线入口和独立首次建库仍按第5阶段既定范围处理，新清理链完全不调用其私有状态，不把后续清退计为本步完成。

本轮未部署、重载、启用正式sensor、提交正式job或写正式instance、Lake、Prod；未安装套件、请求真实Tushare或读取正式全历史明细。新sensor默认STOPPED，正式非零清理的完整吞吐仍在第6阶段按实际范围验收。本轮只完成源码、隔离验证和独立审计；修改随管理员要求的本次提交保存，提交号以Git记录为准。测试和审计的临时实例、数据、spill及日志均在工程外，结果回写原文档后清理，不保留重复过程附件。


<a id="stock-period-bootstrap-preservation"></a>

### 13.14 第5阶段首次建库保留与旧代码清退的实施细则

**性质与范围。** 本节为第5阶段编码依据；本次实现、测试和独立审计结果见第13.17节。管理员要求审计当前代码，把首次建库保留能力和无用旧代码的清退边界细化，避免影响其他功能。本轮只改原方案和LLD。以`05a4a179b`及当前源码为依据，CodeGraph explore/callers/impact配合直接引用搜索核到CLI、协调函数、源分页、候选、发布、事件及Silver首次建库消费者；CodeGraph遗漏的局部导入和回调再用源码核验。范围限DG股票复权周/月线，不涉及Prod、其他股票日线、前端/API或正式数据操作。

原第13.7节把所有源分页和候选恢复分支都列入删除，范围过宽，这是设计错误：当前`run_period(mode='bootstrap')`与旧日更共用这些函数。现已在原条款区分“首次建库本次执行内恢复”与“旧日常跨批待办/交接”。日更、复权因子回刷、退市清理和人工补数仍从原业务范围第一步重跑；只有已批准独立首次建库入口保留其原有恢复能力。本节不增加新的恢复模式或持久化实体。

#### 13.14.1 当前调用关系与不得误删的边界

- Raw首次建库：`bootstrap/stock_period_history_cli.main`的`prepare/apply/resume/events` → `stock_period_history.run_period/replay_events` → `stock_period_source.capture_unit`、`io/stock_period_raw.assemble/publish`。`handoff`及其日常交接调用退出。
- 第2至4阶段新链：当期Raw的`deliver_asset`、独立`execute_history_repair/execute_retirement_cleanup`仅复用`roots/devices/check_devices/writer`中实际使用的路径及设备能力、公共HTTP/字段校验和单文件IO；源和文件分别走无日常接续的`capture_current_period/capture_stock_history`、`assemble_period/assemble_history_period/assemble_retirement_period/publish_period`。保留这些实际调用，不能按旧模块整文件删除。
- Silver首次建库：`stock_period_silver.make_execution/build`和`bootstrap/stock_period_silver_cli.main`的`build/resume/events`动作继续消费已通过审计的`summary.json/inputs.json`、明确Raw路径及参考文件版本。审计报告的`raw_files`、`input_file_counts`、`selected.stock_periods`、`asof/lower`等现行字段保持，不改成日常`DeliveryRef`。日常Silver仍由`deliver_update_asset/evaluate_update_sensor`消费原生交付，不读取首次建库材料。

#### 13.14.2 逐函数保留、改写与删除

路径相对`orchestrator/src/orchestrator/defs/`。下列“保留”均指保留有效能力并删除不适用分支，不授权保留旧日常合同。

| 位置及函数 | 第5阶段精确处理 | 同次迁移与验收 |
| --- | --- | --- |
| `bootstrap/stock_period_history.run_period` | 只接受`mode='bootstrap'`；删除`history/upsert`、日更日期、退市/换码混合维护、共享待办和交接分支。首次删除只由已获准`apply`进入；本次`manifest.json`保存删除阶段，进入下载后`resume`不再次清根。保留冻结对象/身份/策略、设备检查、取消、进度、源及候选恢复 | CLI首次建库动作只调用该模式；第2至4阶段job不得回调它。旧非bootstrap执行不能经此入口恢复 |
| 同模块`history_work_identity/ensure_history_pending/frozen_history_work/ordered_pending_work/require_pending_delivery_before_write` | 整体删除函数及所有调用、仅服务这些函数的导入和字段 | 首次建库、日更和人工维护均无`daily.json`读写；不增加另一份待办文件 |
| 同模块`_record_ranges/validate_registered_targets/recover_moved_candidate` | 删除及清零`baseline`参数/回调；不复制其全局文件目录和每股区间逻辑到其他模块 | 首次建库每份候选的原子提升及中断核对直接走已有`publish`，见13.14.3；新链仍走`publish_period` |
| 同模块`_finish_files` | 删除`baseline`参数、`_record_ranges`调用、`ranges_recorded`、全局`files_ready/ready/listed`写入；保留本次`complete.json`、`file_receipt_hash`、文件完成时间和本次manifest的`files_complete` | 只从本次全部实际文件写出完成清单，不把写出清单当成Dagster原检查已通过 |
| 同模块`completed_receipt/completed_files/require_current_files` | 保留首次建库执行身份、规范路径、范围、摘要及当前文件版本核对；删除旧日常父子执行、较新日常交付追溯和全局目录依赖 | 只由本次bootstrap恢复/事件登记使用；不能给新日更构造旧执行ID引用 |
| 同模块`verify_rss_resume` | 仅保留“已存在且身份一致的bootstrap执行”校验；删除`daily.json`和`bootstrap_parent/handoff`分支 | CLI原`--rss-limit-gib`只限显式首次建库resume；不改变策略默认值、不派生新env、不向新job继承该覆盖 |
| `stock_period_source.capture_unit` | 保留首次建库本次执行、同一对象/频率/完整字段/端点身份下已校验页和完整源单元的恢复；生产调用方只保留bootstrap的单股历史。删除旧全市场周期入口及日更跨日欠账接续的协调调用，`request_params`供新全市场请求使用的公共能力保持 | 现有HTTP限制、限流、字段、分页和源完整性检查保持。新链不读这些页记录；不从一个bootstrap执行借用另一执行的源页 |
| `io/stock_period_raw.assemble` | 收窄为bootstrap完整源COPY与候选构造，删除`mode='history/upsert'`的旧全市场历史读取、整股先删、混合响应、`history_sources/retired_codes/range_evidence/validate_targets`及其SQL。保留本次源身份、`copy.json`、实际周期、`expected_rows/target_preimages`和候选恢复 | 不读旧正式历史内容作合并；首次输出目标仍要求原本不存在。源整行、21列和精度保持 |
| 同模块`_fragment_versions/_save_fragment_proof/_merged_candidate/_candidate_receipts/_validate_candidates/publish` | 保留首次建库真实多片段COPY、候选校验、同设备原子提升和本次写后记录；删除仅供旧日常调用的参数/分支。`publish`现有候选身份、目标写前身份、SHA-256及精确版本核对保留 | 不重写健康公共函数；既有多片段、取消、fsync顺序及替换后记录失败测试继续有效。新链不改用这套恢复路径 |
| 同模块`_old_range_paths/range_index_valid/_source_ranges/merge_ranges` | 删除及清零`stock_ranges/range_index_version/range_index_hash`生产读写，`copy.json`也不再保存这些旧索引字段 | 保留`file_version/file_digest/validate_file`等本次文件校验，不按version/hash关键词误删有效能力 |
| `stock_period_update`旧混合流程及交付函数 | 删除13.7所列旧日更/交接函数；`_period_delivery_*`、`confirm_period_delivery/acknowledge_period_delivery`在旧CLI及事件job迁移后整体退出。`report_file_events/report_completion_events`在13.14.4接通后删除，无兼容包装 | 保留`_period_inputs_ready/deliver_asset/evaluate_daily_sensor`及它们的真实依赖；新原生guard、当前单文件IO调用和Silver合法后继处理保持 |
| 同模块`factor_changes/confirmed_retirements/calendar_days/period_bounds/close_day/source_final/no_trading_period` | 当前生产调用均在待删的旧日更/交接内；这些调用清零后删除函数和专属导入。不能仅因旧LLD说“复用规则”就保留无调用函数 | 复权因子比较保留`load_factor_changed_codes → build_stock_daily_qfq_factor_changed_codes_sql`；确认退市保留`load_confirmed_retirements`；闭合周期保留`period_input_days/load_period_universe`，对应业务规则不删除 |
| `run_contracts/stock_period`旧交付合同 | 删除`completion_reference/validate_completion_reference/completion_notice/validate_completion_notice`、旧完成通知metadata键及已无消费者的旧运行tag；保留源字段/策略、日期、执行身份和首次建库自身的`verify_execution/digest`用途 | Raw首次建库事件不写旧日常通知，日更仍用新的`stock_period_delivery`；不把bootstrap的64位执行ID伪装为真实Dagster UUID |
| Raw/Silver CLI、旧补登记job及停用CLI | Raw删除`handoff`，`prepare/apply/resume/events`收窄为首次建库；`_run_reporting`移除handoff命名分支。Silver保留首次建库的`build/resume/events`和审计报告合同。删除13.7列明的旧周线补登记job/op/config及四个停用CLI | Definitions、静态清单、现行运维命令和测试同迁；历史文档、正式文件、既有执行材料和本机依赖不随源码删除 |

第5阶段先完成替代调用，再清零被替代函数和导入；最终不保留双轨入口。 删除以本节指定文件中的真实函数及调用为准，不按通用函数名或JSON/version/hash关键词全仓清理。`stock_period_silver.py`、两个当期Raw资产、两个Silver资产、独立回刷及退市清理的现行健康逻辑只做本次确需的调用迁移，不顺手重构。

#### 13.14.3 首次建库中断后的具体处理

本次首次建库继续使用其已存在的执行目录。`manifest.json`只记录本次固定范围/身份/阶段，源页和`copy.json/validated/committed`只记录本次数据及处理事实，`complete.json`只记录本次全部产出；这些不保存全局上市差异、每股历史区间或日常交接就绪状态。不同执行不得复用，日常链不得读取。不新增全局JSON、数据库表、索引、版本目录或备用路径。

以两份候选为例：第一份已成功替换正式文件，但保存`committed`记录前中断。原`resume`读回本次冻结候选清单，按原顺序逐份调用已有`publish`；第一份候选已不存在，`publish`会核对正式文件身份和SHA-256确实等于本次候选，补齐本次写后记录，保持正式文件不重复替换，再继续第二份。不再调用依赖`baseline.json`的`recover_moved_candidate`。

- 已有写后记录时，`publish`按该记录核对当前目标精确版本与候选摘要后返回；不得仅凭记录存在跳过文件核对。
- 候选仍在时，按当前候选版本及冻结的目标写前身份执行原子提升；全部按本次执行既有证据判断，不读取旧全局版本目录。
- 取消发生在源、COPY或多片段合并阶段时，只复用本次已经完整校验的阶段产出，继续原有检查。未完成的阶段按原规则重做；内容、身份或版本不符则失败，不猜测接受。
- 已到`files_complete`后只允许本次文件/事件核对，不能再次执行带删除确认的`apply`。事件失败恢复走13.14.4，不请求Tushare、不重新COPY或替换文件。

#### 13.14.4 首次建库事件与Silver的接续

`bootstrap/stock_period_history.replay_events`只接受同一bootstrap执行及其完整实际产出，删除`ensure_history_pending`、旧完成通知、`confirm_delivery/allowed_frequencies`日常用途和回写共享状态。事件登记使用同模块新增的`report_bootstrap_events(instance, context, files, *, cancel=...)`，原CLI `_run_reporting`提供真实登记运行；不新增active job、sensor、schedule或业务资产。

该函数以当前`report_file_events`的文件与原检查语义为依据，按以下集合流程实现，不把它原封不动搬过去保留逐文件查询：

1. 登记前核对本次全部文件清单、路径、行数、摘要和实际版本，沿原`audit_file/validate_file`精确版本结果；按本次Raw资产/分区集合批量读取当前物化及最后完成的三项原检查。复用`stock_period_check_evidence.latest_completed_checks_query/decode_completed_check_row`，物化也限定同一资产/分区集合。不得在成功过滤后再取“最新”，已有失败或错绑定按现行合同拒绝。
2. 仅补缺失的文件物化和原检查；所需既有动态分区按本次明确周期在同频一次集合登记，不逐文件注册，不新增分区类型。物化仍为独立文件生成后的runless记录；检查沿现行真实登记运行写入，并绑定实际物化的storage id、run id、timestamp及正确分区。文件metadata只保存本次真实文件版本、路径、行数和字段观察；不写旧完成通知，也不写日常`DeliveryRef`。
3. 写后再按同一集合读回物化和原检查，逐项核对后才能把本次bootstrap的事件阶段记为完成。事件写入中断时，下一次以实际物化和原检查重新核对，只补缺项；本次`events/`记录不能单独证明通过。完成观察和日常通知均为零，不触发日常Silver sensor。
4. Silver首次建库仍由人工按已通过的审计报告调用其原`build`入口，后续`resume/events`沿其独立执行。保留`make_execution/load_execution/validate_record/materialization_metadata/build`及`bootstrap/stock_period_silver_cli._report_files/replay_events`的健康实现，原三项Silver检查和实际Raw版本核对不放宽。Raw首次建库的事件完成、审计报告通过、Silver实际生成分别核验，不能互相冒充。

新增Raw登记函数只处理Raw检查，不用Silver检查通过作为Raw登记前提；现有`batch_event_evidence`及新日常guard的查询默认值和消费者保持不变。官方runless事件边界见[Dagster外部资产实例API](https://docs.dagster.io/api/dagster/external-assets-instance-api)；精确检查绑定和失败处理以当前代码及隔离回归为准，不用文档示例代替本项目原检查。

#### 13.14.5 性能、配置及最后验收

不新增配置项、env或运营开关；现有CLI参数及持久化来源见13.14.2，策略沿13.10.2。首次建库的对象数S、实际源页P、源行H、候选文件F均从获准本次执行范围和真实产出计算，不能套用13只复权因子变化股票或213份历史样本当作建库上限。首次建库资源覆盖和正式执行仍需各自明确批准，本轮不重做建库或读取正式全历史。

| 场景 | 请求、读写及中断后继续/最后验收成本 |
| --- | --- |
| Raw首次建库文件阶段 | 两频全市场股票完整历史为2S个源单元；HTTP按P页及现有技术重试计算。源页一次列式导入/COPY，候选按原真实输出F和字节计，不读取旧正式全市场行情作合并。候选校验、SHA-256、同设备替换、fsync及实际文件核对均计入，不能只计COPY时间 |
| 文件阶段中断再继续 | 重新核对本次源/候选/写后记录所涉及的文件身份与摘要；已完成页和COPY不重做，未完成部分按实际新增页、H和F计。替换后记录前的单文件按13.14.3读回摘要并补记录，不再扫描全局历史。两次成本按各次实际读取、校验、写入及剩余工作相加，不把“可复用”写成零成本 |
| Raw事件阶段及最后读回 | 前置和最后各一轮集合查询，每轮一次物化集合SQL与一次原检查集合SQL；完整范围两轮共4次SQL，这是新登记函数的开发约束，须隔离断言。读取只限本次F份Raw文件对应分区，最多F条物化及3F条最后完成原检查；新写不超过缺失的F条物化与3F条检查；本次已有周/月动态分区的集合登记各最多一次，另计登记API调用，不混入物化/检查数量。单文件完整核验沿精确版本缓存，未命中时计入实际Parquet及SHA-256开销。中断后再次执行同样前后核对，已登记项不重复写 |
| Silver首次建库及日常回归 | 首次Silver成本按其原审计范围、实际文件及既有构建/事件规则核算，不因Raw清退新增全湖扫描；原审计报告的生成与验收成本单列。第2至4阶段仍只验证其当期/明确历史范围，正式吞吐和全市场建库耗时未在本轮测量，不给无依据的新上限 |

Raw事件查询直接按两频资产及明确分区集合查询；不能把上表4次SQL变成4F次往返。实际事件载荷和内存仍受现有资源限制，正式范围另行核定；不得自动抬升默认内存或继承历史单次额度。测试、日志、spill统一在工程外；写后正式核验继续遵守全局读取及正式执行审批。

#### 13.14.6 正反测试、引用清零与实现顺序

本节只规定第5阶段验收，不把既有600项通过当作尚未开发分支的证据。关键字段和价格夹具继续来自现行21列及真实生产者合同，不能为清退而删除有效断言。

| 现有测试/消费者 | 必须保留和新增 | 应退出的旧断言 |
| --- | --- | --- |
| `test_stock_period_history.py`、`test_stock_period_history_cli.py` | 首次删除确认、下载后resume不再清根；文件/事件阶段分离；事件恢复源请求/COPY/替换均为零。实际Raw两频物化及三项原检查完整绑定 | `baseline.status='files_ready/ready'`、旧完成观察、旧日常引用 |
| `test_stock_period_candidate_fragments.py`、`test_stock_period_memory_resume.py`、`test_stock_period_storage.py` | 本次多片段COPY、校验后取消、候选/源身份变更拒绝、fsync顺序、写后记录失败不重复替换、bootstrap原RSS参数的作用域 | 日常/handoff继承内存及全局索引依赖 |
| `test_stock_period_followup_history.py` | 把其中仍有效的“替换后记录前中断”用明确bootstrap夹具迁入建库回归；断言不读baseline、不重复替换、其余文件继续 | 混合当期/历史、共享待办阻塞、新股作为历史回刷候选等旧语义；不保留旧入口迎合测试 |
| `test_stock_period_check_evidence.py`及原事件回归 | 先集合核对后写、最后读回；已有失败/错绑定/篡改不能补成通过，事件中断仅补缺项；实际断言4次集合SQL及无逐文件事件查询 | 单纯存在本地事件记录即成功 |
| `test_stock_period_silver_contracts.py`、`test_stock_period_silver_projection.py`、`test_stock_period_silver_execution.py`、`test_stock_period_silver_events.py` | Raw审计报告合同、首次Silver对象/日期下限/21列投影、精确版本和原检查、Silver取消/恢复及事件补齐 | 借建库材料恢复旧日常更新或伪造日常DeliveryRef |
| `test_stock_period_native_daily.py`、`test_stock_period_history_repair_native.py`、`test_stock_period_retirement_cleanup_native.py`、两频Raw/Silver定义和sensor测试 | 在无baseline/daily状态条件下复验第2至4阶段；闭合周期、新股日更、两频独立回刷/清理、完整范围重跑和Silver合法后继均保持；读取bootstrap执行材料时用替身直接失败 | 用旧离线测试通过代替新链真实临时job验收 |

实施顺序为：先收窄首次建库协调与候选路径、补齐直接调用`publish`的真实中断回归；再接通首次建库批量登记并迁移CLI/事件消费者；最后删除旧日常函数、共享索引和停用入口，清零生产引用并执行相关回归。删除只由测试引用、生产已无调用的旧实现时，相关测试同步迁移到保留能力或删除已退出语义；不保留生产死代码供旧测试调用。

静态验收逐项检查13.7及13.14.2的函数、参数、导入、Definitions、运行参数构建器和现行命令。`baseline.json/daily.json/stock_ranges/range_index_*`在生产周月链无读写；首次建库专属JSON仍有明确单一消费者，不按JSON文件名整体删除。完成后再次检查`run_period`只接受bootstrap，`capture_unit/assemble/publish`生产调用只来自独立首次建库，第2至4阶段无回流。物理历史回执、正式文件、运行记录及ignored依赖不在源码清退范围。

#### 13.14.7 人工补数的既定触发方式

人工触发此前已在13.7、13.10.3及13.10.4确定。本次补充首次建库细则不重新决定这件事，也不把“当前代码尚未实现全部人工模式”写成“此前未讨论触发方式”。

| 人工意图 | 已确定入口与输入 | 执行及接续 |
| --- | --- | --- |
| 指定闭合周/月全市场补齐 | 对应既有Raw job，`StockPeriodRawConfig(intent='closed_period', automatic_intent_date=该周期最后开市日)`，分区为自然周五或月份 | 原job核整个周期应有集合并交付本频文件，同频Silver接续；不触发自动复权因子回刷 |
| 按原复权因子日期补做 | `raw_stock_period_history_repair_job`的`factor_changed`，明确原日期、重算名单及摘要、两频已核实覆盖引用 | 沿相邻日复权因子比较，只更新实际名单，结果保留原复权因子日期；CLI生产者在第5阶段接入，执行器已有原日覆盖验证 |
| 指定股票历史 | 同一历史修复job的`specified_history`，明确日期、非空股票名单/摘要及选择频率 | 不以复权因子变化选股，按指定股票完整源历史及源周期定位，缺整份文件仍先走全市场周期补齐 |
| 已确认身份的明确记录维护 | 同一历史修复job的`identity_maintenance`，明确排序去重的撤回业务键及其摘要，可另给需要源刷新的股票名单 | 只处理指定键所在文件及明确源回包范围，保留其他股票；完整范围交付同频Silver。无源刷新名单时不调用Tushare |

这两类独立人工维护通过原Raw CLI的明确维护意图构造`StockPeriodHistoryRepairConfig`并提交同一job，不新增自动sensor；不能绕过原生记录直接调用旧`run_period(mode='history')`写湖。人工每次正式提交仍按具体日期/股票/键取得执行授权，首次建库的`apply`及其删除确认不能拿来代替补数。人工维护的命令参数、配置分支、文件处理、Silver接续、失败重跑、预算及验收按第13.15节实施，不增加新的业务模式。


**本轮审计结果。** 已核对现有`publish`确实同时支持已有写后记录的精确版本核验，以及候选已替换但记录未写入时的目标身份/摘要读回；不需要保留旧全局索引恢复函数。静态源码检查确认第2至4阶段入口没有调用`capture_unit/assemble/publish/run_period`旧日常执行路径，保留的路径/设备公共函数另列清单。新增节内测试文件及跨文档锚点均已核对存在，文档完整性与本次差异检查通过。以上是源码和文档审计，未执行新设计代码、正式首次建库、补数或状态写入；新增登记函数、函数清退及所列正反回归均待第5阶段实施，不能写成已完成清退。过程文件在工程外，核验后清理。


<a id="stock-period-manual-maintenance-implementation"></a>

### 13.15 第5阶段人工维护的完整实施细则

**状态与依据。** 本节为人工维护实施设计，实现和验收见第13.17节；修正上一轮只归纳入口、没有补齐具体实施明细的遗漏。与13.14的首次建库保护同时落实，不把首次建库恢复带入人工补数。开发前`StockPeriodHistoryRepairConfig.intent`只接受`factor_changed`，`execute_history_repair`无条件核上游并重算复权因子变化名单，开发前CLI只有首次建库动作；当时`_assemble_period`的Parquet输入也要求有源路径。以下逐项明确必须修改的位置、实际执行和验收，不以“触发方式已确定”代替这些实现。

#### 13.15.1 人工入口、命令和提交方式

闭合周期补齐继续在Dagster对应既有Raw job的Launchpad选定分区，输入`intent='closed_period'`和`automatic_intent_date=周期最后开市日`；规范分区为自然周五或月份。原`StockPeriodRawConfig`已支持，无需把当前只生成daily配置的`build_stock_period_run_config`改作其他用途。所选分区须按现行正式流程完成注册；未注册时先办理该精确分区，不以首次建库apply补文件，不扩展其他分区。该job仍执行原Raw资产及三项原检查，同频Silver消费其实际成功交付。

其余三类人工维护由原`bootstrap/stock_period_history_cli.py`增加`maintain`动作，构造并提交现有`raw_stock_period_history_repair_job`。`main`先分流该动作，再进入原首次建库解析；维护动作不会进入`roots/run_period/replay_events`首次建库协调路径。新增同模块`parse_maintenance_args/build_maintenance_request/submit_maintenance_request`分别解析本节输入、构造唯一业务配置及提交实际job，不另建通用CLI或状态服务。首次建库参数原有含义保持。

```text
.venv/bin/python -B -m orchestrator.defs.bootstrap.stock_period_history_cli maintain
  --intent factor_changed|specified_history|identity_maintenance
  --business-date YYYY-MM-DD
  [--frequency week|month ...]
  [--stock-code TS_CODE ...]
  [--upstream-completion '{"producer_run_id":"UUID","freq":"week或month","upstream_batch_id":"实际上游ID"}' ...]
  [--remove-key TS_CODE,YYYYMMDD,FREQ ...]
  [--submit --remote URL --repository-location NAME --repository NAME]
```

以上为第5阶段已实现语法，方括号表示按下表适用，不是要求照抄。没有`--submit`时只读预览，不请求Tushare、不提交job、不注册分区、不写Lake或Dagster状态、不保存临时配置文件。`factor_changed`预览只沿已有函数读取明确相邻交易日的股票复权因子及所需日历/生命周期，生成变化名单；其他两类预览只解析和规范化明确输入，不将格式正确写成身份或源数据已通过验收。全部模式输出`job_name/run_config/submitted=false`以及可复算的名单、摘要、频率、源单元数和撤回键数；源回包尚未取得时文件数写“尚待源定位”，不虚构估算。

| 输入 | 必需/缺省和唯一解释 | 生产者、消费者及持久化 |
| --- | --- | --- |
| `--intent`、`--business-date` | maintain必需；日期为ISO业务意图日，不晚于上海执行日。只有factor_changed要求它是有相邻交易日的复权因子日期；其他模式不把非交易日维护误拒绝 | CLI → `StockPeriodHistoryRepairConfig` → op；随Dagster运行配置保存。日期不作为单股源请求的过滤参数 |
| `--frequency`，可重复 | specified_history和identity_maintenance必需，非空、无重复，仅week/month，固定按week、month排序；factor_changed固定两频，不接受该参数另选一频 | CLI构造`frequencies`；op只处理所选频率，自动sensor的两频合同保持 |
| `--stock-code`，可重复 | specified_history必需且非空；identity_maintenance可无；factor_changed不接受手填名单，而沿`load_factor_changed_codes`生成。代码沿原合同去空白、转大写、去重排序，CLI派生`codes_hash`，不要求运营手算摘要 | 仅源刷新名单；不把撤回键中的旧代码混入源请求。op复核配置格式并在人工源刷新前核现行准入 |
| `--upstream-completion`，可重复 | 仅factor_changed必需，恰好两份现有完整三字段引用，按week/month排序；其他模式不接受。输入须是实际记录的引用，不按run key或当前文件自行拼造上游ID | CLI校验形状并保存；op沿现有`_validate_upstreams`核真实成功、原检查及对原日的覆盖。不能给无上游的人工模式伪造日更成功 |
| `--remove-key`，可重复 | 仅identity_maintenance必需且至少一项；每项严格为`ts_code,trade_date,freq`，源键日期为YYYYMMDD。映射成三个同名字段的对象；按week/month顺序、trade_date、ts_code去重排序，派生`remove_keys_hash=digest(remove_keys)`。键的频率须在所选频率内；源周期标签可以是晚于意图日的当期自然月末，不能按日线日期规则误拒绝 | `remove_keys`为明确撤回范围；保留物理旧代码及实际源日期标签，不把旧码自动改为新码，也不把旧月末28/29日标签归并。写前范围及结果保存同一规范完整键表与摘要 |
| `--submit` | 缺省false。true才提交一次维护job；不是执行成功标志，不连带提交Silver或其他维护任务 | CLI调用提交函数，成功输出真实run_id及`submitted=true`，随后退出，不轮询、不建本地待办 |
| `--remote/--repository-location/--repository` | 提交时三者均须显式提供，预览可不提供；remote为现有Dagster服务origin（scheme/host/port），不是/graphql路径。正式本机既有目标记录为`http://127.0.0.1:3000`、`orchestrator/__repository__`，实际执行前核对获准实例 | 只供提交函数使用，不写入job业务配置、env或Lake文件，不隐式扫描/推断repository；本需求不新增跨工程目标 |

maintain不接受首次建库的`--request-id/--run-id/--confirm-delete-existing/--rss-limit-gib/--lake-root/--staging-root`；解析时即拒绝，不能借其切换正式路径或进入恢复/删除阶段。正式路径、资源及配额仍由现有job读取本工程配置。新参数不进入sensor或其他数据集，不新增配置文件、环境变量及内存覆盖。

`submit_maintenance_request`使用本项目已安装的`dagster_graphql.DagsterGraphQLClient.submit_job_execution`，显式传现有job名、repository位置/名称和builder产出的完整run_config；不传op_selection或asset_selection，不执行`execute_in_process`或自行写文件。业务tag由op从验证后的配置派生；自动回刷的run key及上游ID构造不变，人工完整新运行不复用自动run key。安装版客户端在显式repository下直接提交一次launch mutation，不需要推断job名单；传输默认重试为0，本CLI不添加自动重试。返回run_id只证明提交成功，结果以实际运行和原检查为准。配置错误或拒绝则报告原错误；响应不明时停止，由运营核对原提交结果，不盲目再次提交。原生任务已经失败后，再按13.15.5完整新跑。

上述参数是本次唯一CLI配置来源，持久化及消费者已在表中列清，修改重载后的代码位置生效；不自动加载仓库.env、不打印Tushare凭据。依赖复用本项目dev组`dagster-webserver==1.13.26`已带入的GraphQL客户端，仅在submit分支导入，不修改依赖或锁文件、不安装套件，也不把GraphQL导入任务执行器或Definitions。API已核对安装版client及[Dagster Python GraphQL客户端文档](https://docs.dagster.io/api/graphql/dagster-graphql)，未在本轮请求正式服务。

#### 13.15.2 配置合同和全部调用方

扩展原`run_contracts/stock_period_history_repair.py::StockPeriodHistoryRepairConfig`，不新增另一份维护配置：`intent`允许`factor_changed/specified_history/identity_maintenance`，原六项业务字段保持，`upstream_completions`缺省空列表，新增`remove_keys:list[dict[str,str]]`缺省空列表，每项只接受`ts_code/trade_date/freq`三个字符串字段。`business_date/stock_codes/codes_hash/frequencies`仍显式构造，额外字段继续拒绝。`remove_keys_hash`由规范键派生，不作为运营可任意填写的新字段。业务21列、三个原文件检查及三字段`DeliveryRef`均不变。

| 模式 | 配置和执行必须一致 |
| --- | --- |
| factor_changed | frequencies固定week/month；恰好两份按频率对应的引用；remove_keys为空。股票名单允许为空，op重算相邻日变化并核对完整名单和codes_hash。`repair_upstream_batch_id`仍只用于此自动意图，原payload和顺序不变 |
| specified_history | 所选频率为非空规范子集，stock_codes非空，upstream_completions/remove_keys均为空。op不得调用复权因子变化选股或两频上游验收，以明确名单取源 |
| identity_maintenance | 所选频率为非空规范子集，remove_keys非空且键频率属于所选范围；stock_codes允许空，upstream_completions为空。仅撤回键不请求源；有明确刷新名单时对每只、每个所选频率请求完整历史 |

同次迁移生产者/消费者：CLI的维护请求builder、原`build_history_repair_run_config`、新旧Config校验、`ops/raw_stock_period_history_repair`类型注入、`stock_period_history_repair.execute_history_repair`、job说明、原生work/result生成，以及下表测试。自动`sensors/raw_stock_period_history_repair_job_sensor`仍只产生factor_changed，不得因新增模式扩大自动触发。`repair_upstream_batch_id`不对空上游人工模式生成伪造自动输入ID。旧`run_period(mode='history/upsert')`、旧Raw配置history和相应CLI写入路径按13.7删除，不保留转发兼容。

#### 13.15.3 执行器分支和安全范围

`execute_history_repair`在配置校验后按模式分支，不再无条件执行`_validate_upstreams/load_factor_changed_codes`：

1. factor_changed保留已完成的第3阶段流程，包括原日补做采用后续完整覆盖引用；不重复增加股票复权因子的上游验收，不把新股加入名单。`kind='factor_repair'`，仍处理两频。
2. specified_history直接使用配置名单和所选频率，`kind='history_maintenance'`，不读复权因子文件、不要求两频日更引用。
3. identity_maintenance使用同一kind；先核明确撤回键，再处理可选源刷新名单。只有配置非空的刷新名单才能产生源请求，撤回键中的代码不会自动变成刷新名单。

人工两模式在当前模块新增`load_history_maintenance_scope`，仅按本次代码和撤回键查询现有Silver股票基础数据、已确认证券身份；源刷新名单沿原CNY、list_status=L及`admitted_code`合同，北交所沿已确认新码请求。撤回键核对`confidence='confirmed'`的实际证券身份，保留键中的物理代码，不从“今天缺码”推断删除；明确键可含旧代码，不要求它仍是当前在市源请求代码。查询按本次代码谓词投影必要列，不扫全历史行情。CLI只做格式预览，这些实际身份及准入在job内核验，不能因预览成功而跳过。

源仍使用同一运行内的`HttpPage`及`capture_stock_history`，按K只股票、R个所选频率规划K×R个单股单元，参数只有`ts_code+freq+limit/offset`及原21列字段，不加日期过滤，不复用旧页或建库候选。没有刷新名单时跳过HTTP与`group_history_sources`，不能把空源路径送进read_csv/read_parquet。源有值时继续复用现有日期/字段检查和一次分组，不新增历史完整性或“版本够新”的额外判断。

#### 13.15.4 目标文件、仅删除与混合写入

原`group_history_sources`给出源行涉及的文件集合V；撤回键逐项用现有`source_period(trade_date,freq)`和`target_path`得到集合T。最终F=|V∪T|，不将同一周期重复处理。撤回键保留实际业务键，周/月文件坐标只用于定位，不能改变要删除的原trade_date标签。所有所需全市场文件须在任何候选生成前确认存在；缺失则报告精确频率/周期并停止，由对应闭合周期全市场入口补齐，不创建只有单股的市场文件。无全湖枚举、每股历史索引或按上市日期截断。

新增`io/stock_period_raw.assemble_history_maintenance_period`作为明确维护的单文件入口，复用并扩展现有`_assemble_period`的列式合并：只给它本频本周期源组和撤回键；新增可选`remove_keys=()`，现有`assemble_period/assemble_history_period`传空值，原执行语义和原检查保持。两类新增处理必须写清：

- **仅删除：** 源组为空时按现行SPECS建立有准确21列类型的空incoming表，读取并验证该份已有全市场文件；按三个业务键精确anti join删除指定行，保留同股其他日期/频率及其他股票。不能调用按整股代码删除的退市函数。指定键已经不存在时仍正常验收该文件并交付，不能误判失败或遗漏Silver接续。
- **删除并回刷：** 先用现有业务键/end_date规则合并本周期源与旧记录，保护非撤回键中的较新记录；再从合并结果精确移除配置撤回键，最后只写一份候选、只提升一次。明确撤回键即最终必须不存在的键，源若也返回同键不得重新带回。不得先发布一个删除版，再发布一个回刷版。

候选保持21列顺序、类型、精度、排序和原完整校验；指定键残留为零才可提升。全部行删完时仍发布合法空文件，source_asof=None只用于空文件。正式写入继续用已有`publish_period`和同设备原子替换，不引入备份或逐文件续跑。全部提升后，按本次T内文件集合仅投影业务键做残留核验；只对有撤回键的频率各发一次集合计数SQL，不扫描其他历史文件。残留非零、本次版本改变或原检查失败则本次不能记成功。

#### 13.15.5 原生记录、Silver和失败后完整重跑

运行日期、用途及选定频率来自验证后的配置；单频维护写既有频率tag，双频不伪造单频tag。每个实际非空交付频率沿`delivery_ref/delivery_work`先持久化完整periods再写候选。`delivery_work`只为identity_maintenance增加配置中的完整规范`remove_keys/remove_keys_hash`，两个频率记录同一原业务范围，单文件处理时才按频率/周期过滤；其他意图不增加撤回字段。`DeliveryRef`结构和ID构造不变。

逐文件物化、一次读取本运行物化集合、三项原检查精确绑定、完整范围观察和每频结果沿第3阶段执行方式。人工两模式kind为history_maintenance，结果仍使用原`history_repair_result_check`，记录所选频率的实际文件范围、改写文件数/完整候选行数、原名单/摘要及空上游列表；身份维护结果另保存同一完整撤回键及摘要。`rewritten_row_count`仍是实际重写文件的完整行数，不改称删除行数。某一所选频率没有文件输出时只记该频零结果，不发完成范围，不启动Silver。

Silver继续消费每频实际完整Raw引用，沿`read_completion/resolve_update_sources/deliver_update_asset/evaluate_update_sensor`及原三项检查，不新增人工专用Silver job。`history_maintenance`已在交付kind合同中，新增生产者须验证现有消费者实际接受它；保持2014历史下限、合法较新Raw、逐文件实际来源日期及空文件语义。仅删除和本次未删除到行的明确文件也完整交付，不能按删除行数决定是否通知Silver。只处理Raw成功且原检查完整的频率，维护交付不触发自动复权因子回刷或退市清理。

失败后用原完整配置创建新的真实运行，从第一步重做源与全部文件；不恢复旧页、候选、JSON或逐文件位置。身份维护的T由配置明确撤回键直接得到，即使前次已删完仍在本次范围，不需要靠父运行查回缺失键的位置。有源刷新时V由本次通过校验的源重新规划，旧键未返回仍按已定合并规则保留，不新增完整性判断。新运行按原配置重新校验名单及规范撤回键，派生相同摘要，重新保存范围并完整交付；运营改变业务输入属于另一维护意图，不冒充原配置重跑。Silver失败则单独以原Raw引用整批重跑。上述规则保持现有“失败后重新跑”的口径，不增加自动续跑或本地待办。

#### 13.15.6 性能、调用量及拒绝条件

K为本次源刷新股票数，R为明确所选频率数（1或2），P为实际源页数，H为实际源行数，D为规范撤回键数，V/T分别为源/撤回键涉及的去重文件集合，F=|V∪T|。所有预算均按本次实际范围推导，不把输入键数当作完整K线行数或磁盘读取量。

| 场景 | 可复算的执行量与最后验收 |
| --- | --- |
| 预览及提交 | 格式预览无Tushare请求、无Dagster写入；factor_changed另按现有选股函数读取明确两天股票复权因子及其参考文件，其他模式不做该扫描。显式提供repository的GraphQL提交最多一次launch mutation，不推断名单、不自动重试，也不轮询任务。客户端超时沿已安装库的默认参数，不新增配置、不当作任务总耗时保证 |
| 指定历史/混合维护 | 源单元K×R；factor_changed固定R=2，仍为2K。HTTP按P及原retries=2（每页最多3次尝试）实际累计。H行一次列式分组；仅V∪T的F份全市场文件进入逐文件处理，每份最多写一份候选并替换一次。旧文件导入、候选和SHA-256校验分别计费，不能把F个目标说成仅F次物理读取 |
| 仅撤回键 | K=0、源单元/HTTP/H均为0；V为空，F=|T|≤D，只处理键指定的文件。不套用退市清理对N份历史文件的代码扫描，也不读另一未选频率。每份候选校验后，最终残留检查仅T文件的三个业务键列，每个有撤回键的频率一次SQL；无撤回键时此步为零 |
| 事件和Silver | 非零交付频率数为R₁、零交付频率数为R₀时，F物化+3F原检查+R₁写前范围+R₁完成范围+R₁结果+R₀零结果，合4F+3R₁+R₀条业务记录，另计引擎/日志。物化绑定按本运行一次集合读取，不逐文件查Dagster；Silver按本次适用文件范围和既有历史下限计算，不重复审计全历史 |
| 一次失败加一次整批新跑 | 相同名单/频率下，两次尝试最多合计2KR个逻辑源单元；HTTP仍按两次实际P和重试算。文件分别为F₁/F₂时，候选、完整验证和替换按各次实际成本相加；身份维护的T每次都从原键得到，最终残留按两次T分别计。两次事件与Silver验证成本分别累计；旧运行未清理的staging另计设备占用，不把它算进新运行同一额度而漏算 |
| 闭合周期 | 沿原Raw资产：一频一周期、一份Raw及本频Silver；所需开市日B由日历计算，按现有`period_input_days/load_period_universe`实际逐交易日SQL、对应停复牌分区及参考文件读取计入，不冒称只计算最后一天或已一次批量读完。源按同一周期单点分页，不调用单股历史 |

资源沿13.10.2的现行策略：源响应/单元容量、DuckDB、进程、spill及本运行工作目录门禁均保持；不继承历史6/8 GiB单次额度。K/R/D及来源单位可以预览复算；P/H/F和实际字节由合格源及指定文件得到，不能用单股213份样本推成全规模耗时或固定上限。源/空间/内存或文件合同不能满足时沿原拒绝条件停止，不自动拆分扩大任务、不抬高限制。正式范围提交前按既有样本和这些公式核定预算；本轮没有新的正式吞吐测量。

#### 13.15.7 测试、真实边界和逐项对账

以下为第5阶段验收要求；实际执行、结果和未执行边界统一见第13.17节。新增`tests/test_stock_period_manual_maintenance.py`承载配置、执行及文件语义，新增`tests/test_stock_period_manual_cli.py`承载参数与提交；复用现行21列字面金样本及真实临时Dagster/Parquet夹具，不用待测函数生成expected。正式服务、Lake、实例和Tushare不得作测试目标。

| 必须核验的要求 | 正向及正常变化 | 反向及故障 |
| --- | --- | --- |
| CLI和提交 | 三意图参数明确、代码/频率/键规范化稳定；默认预览无提交和写入；完整配置提交一次现有job，返回真实run_id不冒记完成。首次建库动作仍按13.14工作 | 缺参、错日期/频率/引用/键格式、维护混入建库参数在提交前拒绝；提交拒绝/响应不明不重复launch；无自动job/sensor及配置漂移 |
| 模式分支 | 非复权因子变化股票仍可指定历史；单频与两频都正常；仅删除名单为空但键非空正常；正常因子变化及零变化仍沿原路径 | 额外字段、伪造上游、模式字段混用拒绝；指定历史/身份维护若调用复权因子扫描或两频上游验收即失败；空历史名单、无撤回键的身份维护拒绝 |
| 准入与键范围 | 确认的北交所新码源刷新；旧码明确撤回且保留同股其他键；历史月线28/29日标签及当期自然月末标签按精确键处理 | 未确认身份、不准入源代码、键频率未选择、缺整份目标在任何候选/替换前拒绝；源日期/字段沿原检查，不自行加历史缺页门槛 |
| 仅删除与混合 | 两频各构造小文件核字面预期；全部删空合法；键已不存在仍成功交付；同文件删除+源更新只构造和替换一次；非撤回键较新价格保留。混合用例须含一个只有撤回键的周期和一个只有源更新的周期，两者都应正确交付；源同时含撤回键时，最终只删除明确键，其他源记录仍更新 | 既不属于源回包更新、也不属于明确撤回键的记录被误删/误改即失败；未选频率不得改写；最终输出仍含明确撤回键即失败；不得按代码先删整股。仅删除不得超出T；混合维护不得超出V∪T，不能把V中其他应更新周期误拦 |
| 原生结果和Silver | 真实临时job生成work→物化→绑定检查→completion/result；history_maintenance实际接续每个适用Silver周期，纯删除和零命中也交付，空文件与2014下限保持 | 原检查缺失/失败/错绑定、原引用范围摘要错误时不消费；work/result中的原键表和摘要必须与输入一致；仅零结果不得发完成通知；维护成功不得反触发自动回刷或清理 |
| 中断后新跑 | 三份明确文件在首份替换后失败，按相同配置创建新运行；源全部重取、明确T文件全部处理、两频完整交付；替换后事件前失败同样覆盖。Silver失败按原引用完整重做 | 若读取旧页/候选/执行JSON、用上次已删除而缩小T或只补事件替代整批新跑即失败；不继承旧RSS覆盖，不造共享待办 |
| 性能和公共回归 | 断言K×R、K=0源调用0、每个F最多一次候选/替换、最后T的有界集合计数、事件绑定集合读取；旧Raw日更、自动因子回刷、退市清理及首次建库有效用例保持 | 不按F发逐文件Dagster查询，不全湖扫描定位明确键；无源名单不得读空源路径。只测错误阻止不足，正常单频、无变化和键已不存在须通过 |

提交边界另用本机临时HTTP fixture核对已安装`DagsterGraphQLClient`实际发出的selector/runConfigData，确保指定完整job、无op/asset裁剪、只提交一次；此替身只证明传输，不代替job业务验证。临时GraphQL schema/instance再以测试producer验证Config接收、真实UUID和绑定原检查，业务链则由上述真实临时job及字面Parquet独立验收。复用13.10.5已有真实单股源和分页证据，不为补文档再请求正式源；必要实际参数变化须先依原来源核验规则处理。

实现后运行新人工两文件、现有`test_stock_period_history_repair_native.py/test_stock_period_native_daily.py/test_stock_period_retirement_cleanup_native.py`及受影响源/IO/Silver、CLI/Definitions回归；受保护静态suite沿规定runner，不能直接pytest替代。测试输出、临时实例、HTTP fixture、spill与日志全部在工程外；Ruff用--no-cache。现有600项通过不能代替新人工模式验收。

| 本次补齐项 | 唯一落点 | 开发完成时必须交付的证据 |
| --- | --- | --- |
| 命令参数与实际提交 | 13.15.1、CLI三个职责函数 | 参数/预览/单次提交及实际传输断言 |
| 配置与执行分支 | 13.15.2—3、Config/builder/op及选定范围查询 | 三模式正反测试、自动生产者行为不变 |
| 仅删除及混合文件处理 | 13.15.4、单文件维护入口及现有合并内核 | 真实文件、字面预期、单次候选/替换、残留为零 |
| Silver与结果 | 13.15.5、原生work/result及现有Silver消费者 | 原检查精确绑定、完整范围、空文件/零命中实际接续 |
| 失败重新跑 | 13.15.5、原配置与T/V定位 | 真实新运行、三文件中断、从头处理及无旧状态读取 |
| 请求量与性能预算 | 13.15.6 | K/R/P/H/D/F、字节、事件读取和中断/最后验收开销 |
| 测试及真实边界 | 13.15.7 | 新配置/CLI、隔离GraphQL传输及真实临时业务链分别验收 |


**本轮逐项审计结论。** 13.15.1至13.15.7已分别写清原待补事项，末表逐项映射了代码位置与未来验收。已读取当前Config、CLI、执行器、源下载、单文件IO、交付结构和Silver消费者；用CodeGraph explore/impact及直接引用搜索核到现有配置builder、自动sensor、op和相关测试，确认本次只扩展本工程的人工模式，自动因子回刷仍沿原合同。已核对安装版GraphQL提交接口、显式repository避免推断查询、默认不重试和现有项目依赖来源。新增章节/跨文档锚点、七项落点、当前源码状态、文档完整性和本次差异检查通过。这里完成的是人工维护文档补齐；第5阶段源码、正式提交、新模式回归与正式性能验收均未执行。本轮仅同步三份原文档，未安装套件或操作正式服务/实例/Lake，过程材料清理后不另留附件。


<a id="stock-period-stage-five-readiness-review"></a>

### 13.16 第5阶段开工复审（2026-11-11）

**结论：具备第5阶段源码开发条件。** 本次重新对照原方案10.19、月线LLD第11节、本LLD13.7/13.14/13.15和当前实现，不以章节存在或旧测试通过代替代码核验。以周月链已提交的`05a4a179b`及当前工作区设计为依据；当前HEAD其他任务的修改不进入本需求范围。没有剩余需要重新决定的业务口径或开工阻断项。

| 开工条件 | 当前核验依据与结论 |
| --- | --- |
| 前置实现 | 第2至4阶段的当期Raw/Silver、独立复权因子回刷、退市清理及三字段原生交付已存在。人工模式尚未进入Config/CLI/op，13.15已逐点指定本阶段扩展，不把待开发代码写成已实现 |
| 人工维护完整设计 | 13.15已覆盖命令/预览/正式job提交、三模式字段及调用方、身份与源准入、仅删除/混合文件处理、完整Silver交付、失败整批新跑和测试预算。当前历史op无条件验收上游/重算名单、Parquet合并不能接空源等真实修改点已核对 |
| 首次建库保留与清退 | 13.14逐函数区分保留、改写、删除；已有publish可核候选已替换但记录未写入的目标身份/摘要，替代依赖baseline的恢复函数。Silver首次建库仍沿审计报告和本次文件恢复，不消费旧日常通知；旧日更/共享待办/索引/停用入口最终清零 |
| 接入与消费者 | 已核生产者和schema，Silver股票基础数据确有CNY/上市状态字段，证券身份有确认关系；原生guard按kind及完整范围核验，现有kind包含history_maintenance，允许work增加明确键字段而不改变三字段引用。CodeGraph explore/impact/callers及直接引用搜索覆盖Config/builder、自动sensor、op、单文件IO、首次建库及Silver消费者，无Prod/前端/API迁移 |
| 提交依赖与配置 | 现有dev依赖链含安装版GraphQL客户端；提交API、显式repository避免推断查询、默认零重试已核对。CLI连接参数来源/缺省/持久化边界和全部消费者已在13.15.1列明，不新增env、状态库或运行资源覆盖 |
| 失败、性能及验收 | 首次建库保留本次恢复，其他维护按原配置整批新跑，明确撤回文件不会因前次已删完丢失。13.14/13.15的源单元、目标并集、集合事件读取、内存/空间限制、一次中断和最后验收均有口径；正反测试包括正常单频、零变化、键已不存在和混合源周期，不以旧600项代替新实现验收 |

复审发现并修正了13.15.7一处测试边界错误：原“仅删除与混合”负例笼统要求T外不得读写，会误拦混合维护中只有源更新、没有撤回键的周期。现明确“仅删除限T，混合限V∪T”，增加一个仅撤回周期和一个仅源更新周期均应交付的正例，并明确禁止的是最终输出仍含撤回键，不是禁止源回包本身包含该键。这是原文档错误的纠正，源返回历史和明确撤回范围的既定口径保持。

本轮执行静态源码/依赖/引用核对、文档完整性与差异检查，不运行Dagster job或新测试，不请求Tushare、不读正式Lake明细、不修改正式实例或安装依赖。三份方案/LLD的补充仍为未提交修改；第5阶段源码开发、第6阶段整体验收及正式切换均未执行，后续按各自授权推进。过程材料在工程外创建，核验后清理。


<a id="stock-period-stage-five-results"></a>

### 13.17 第5阶段实现、验收和独立审计（2026-11-11）

**结论与边界。** 管理员批准先提交设计文档，再严格按LLD开发第5阶段并独立审计。设计提交为`765c02903`；本阶段源码、测试及本节交付记录随本次提交保存，提交号以Git记录为准。人工维护与旧实现清退已完成开发及本需求隔离验收，独立审计发现一项遗漏、修复并复核后无剩余本需求阻塞项。第6阶段整体验收、正式部署/重载、启停sensor、正式job、Tushare请求、正式Lake/staging/instance写入均未执行；本轮实例、HTTP/gRPC服务与全部数据均为工程外临时资源。没有安装或升级依赖，没有修改Prod或前端/API。

#### 13.17.1 已落实的业务口径与代码

| 既定要求 | 实现和本次证据 |
| --- | --- |
| 人工入口与提交 | `bootstrap/stock_period_history_cli.parse_maintenance_args/build_maintenance_request/submit_maintenance_request`提供maintain；默认预览，仅显式submit提交一次现有`raw_stock_period_history_repair_job`，无选择集裁剪、自动重试、轮询或本地待办。真实安装版GraphQL客户端在临时HTTP服务核对完整selector/runConfigData；临时官方GraphQL schema和排队实例接受同一Config、生成真实UUID，测试producer执行后原检查绑定同一运行 |
| 三模式职责 | `StockPeriodHistoryRepairConfig/build_history_repair_run_config`和`execute_history_repair`支持factor_changed、specified_history、identity_maintenance。自动生产者仅保留factor_changed两频规则；人工模式不读股票复权因子、不伪造上游。`load_history_maintenance_scope`仅查询本次代码及明确键的Silver股票基础/已确认身份，源刷新沿CNY/上市/北交所新码准入，撤回保留物理旧代码及源日期标签 |
| 精确键、混合与完整文件范围 | `assemble_history_maintenance_period`复用`_assemble_period`：空源建立准确21列空表；先按业务键/end_date合并，再按三个字段精确撤回，一份文件仅生成并提升一份候选。范围为源返回与明确键对应文件并集，全部目标存在才构造候选；较新非撤回记录、同股其他键及其他股票保留；空文件与键已不存在均合法。`count_maintenance_rows`最后仅对明确键涉及文件做每频一次三字段集合计数 |
| 原生交付与Silver | 每个有输出频率保存完整work、实际物化、三项绑定原检查、completion与结果。身份维护work/result保存同一完整键表和摘要，零文件频率只有零结果。现有Silver接受history_maintenance，纯删除、删空和零命中均真实接续；2014下限、每份实际来源日期和合法较新Raw保持。未新增人工Silver job或自动维护sensor |
| 失败整批新跑 | 人工源每次重新取得；三文件写入中途或替换后事件前失败后，用相同完整配置新运行，源与全部目标从头处理。明确键直接确定的文件即使前次已删完仍交付；不读取旧页、候选、JSON或逐文件位置。Silver沿原Raw引用独立整批重跑 |
| 首次建库保留 | `run_period`只接受bootstrap，保留冻结身份、删除阶段、源分页、COPY、多片段候选、设备/内存/空间及取消。已有`publish`直接处理替换后记录前中断，补记录且不重复替换；`_finish_files`仅保存本次complete/manifest。Silver首次建库仍消费原summary/inputs审计报告，未改成日常引用 |
| 首次建库事件 | `replay_events/report_bootstrap_events`核本次实际文件，批量读取并补缺原物化/原检查。每次完整执行4次有界集合SQL：写前物化/检查各1次，物化补齐后读回1次用于绑定，检查补齐后读回1次验收。无逐文件事件查询，无日常完成观察；失败、错绑定和被改记录不能补成成功。事件阶段不重取源、不COPY、不替换正式文件 |
| 清退边界 | 按13.7/13.14.2删除旧混合日更、交接、共享待办、全局baseline/每股范围/版本索引及旧完成引用；删除旧周线事件job/op/config与四个停用CLI。`stock_period_update`只保留本期Raw和sensor及真实前置；`capture_unit/assemble/publish`生产调用只剩独立首次建库。原历史文件、已有运行及物理旧回执没有删除；没有为旧测试保留死代码或转发兼容 |

CodeGraph explore/impact/callers与直接引用搜索覆盖CLI、运行参数及builder、自动sensor、op、单文件IO、首次建库和Raw/Silver消费者。对重名capture_unit/publish按模块确认，Prod同名实现不在本次范围。已同步任务拓扑和架构快照，不改其他资金流、stk_factor_pro或catalog的并行工作。

#### 13.17.2 测试迁移与实际结果

- 完整执行当前`test_stock_period_*.py`、`test_stock_weekly_*.py`、`test_stock_monthly_*.py`：**462 passed，2 skipped，105.54秒**。两项跳过是原有需单独启用的PostgreSQL验证；未创建或连接PG测试服务，不能将它们写成通过。
- 独立审计后的apply修正定向执行`test_stock_period_history_cli.py/test_stock_period_history.py/test_stock_period_memory_resume.py`：**39 passed，2.64秒**，含新增加的files_complete/events_complete两种拒绝用例。这里不将重复用例与完整回归相加充当新的完整执行数。
- 新人工两测试文件分别核配置/文件/job/Silver及CLI/真实传输；全套保留多片段、精度、候选/源身份漂移、fsync/替换、内存覆盖作用域、取消、Silver建库和真实原检查。旧混合日更、共享待办、handoff与跨批回执测试按退出语义删除；仍有效的协调器替换后记录失败、跨日源页及纯路径/摘要检查迁到保留入口。之前遗漏的月线范围请求断言及旧日常状态夹具本轮改为已确认单点和真实生产者schema，未恢复旧实现迎合它们。
- 全仓Ruff致命错误基线通过；本次31个现存Python文件执行默认规则检查，无新增问题。共用`run_contracts/configs.py`有11条未修改行的既有告警（4条DTZ007、7条TRY004），已与HEAD原文逐条比较相同；本次只删除旧事件Config，不扩散修复其他配置。
- 使用清洁环境、现有解释器、工程外DAGSTER_HOME执行`dg check defs --use-active-venv --no-check-yaml`通过。只加载定义，不执行任何正式job或连接正式实例。
- 受保护启动器执行全局静态suite在第7批被另一项资金流改动阻断：`test_sensor_definitions_use_registered_definition_tags`发现新增`raw_tushare_moneyflow_ths_page_cleanup_sensor`未登记分类。该文件不是本需求修改，未改动、未过滤该测试，也不将全局suite记为通过。其余本需求代码与入口由上述专项回归、静态清退断言和独立审计核验；该全局问题保留给所属改动处理。

#### 13.17.3 性能、独立审计与收尾

性能口径沿13.14.5/13.15.6，资源默认值未改变。隔离CLI/HTTP/bootstrap取消—恢复—事件验证使用2只股票、两频共4个源单元，累计4次HTTP、8条真实夹具源行，生成4份正式布局的临时Raw文件，共12,752字节，最终spill为0；该测试记录1.20秒。它使用测试凭据、测试本机源与测试限流设置，只证明此有界链路和中断复用，不是正式全市场吞吐保证。人工测试断言K×R、无名单源调用0、每个并集文件一次候选/替换、明确键每频一次最终计数与完整交付；首次建库事件断言每轮4次集合SQL。中断及最后文件/事件核验开销均保留，不引入全湖枚举来定位人工键。

独立审计在实现与完整回归后重新阅读LLD和当前代码，发现已完成文件阶段仍接受CLI apply：原实现虽不重复删除，但没有遵守13.14.3的明确拒绝要求，这是实现遗漏。现按本请求自身manifest在读取当前范围和进入writer前拒绝；两阶段测试和39项回归通过后，独立审计复核修正，结论为无剩余本需求阻塞项。其他已拍板忽略的问题未重新加回设计。

源码、回归与本轮独立审计完成；全局资金流静态问题、可选PG、正式源端/正式文件/正式运行/部署切换均按上述准确边界保留，不冒称已完成第6阶段。有效结果写回本节与原方案/月线LLD；工程外过程脚本、测试实例、服务和日志核验后清理，不在工程目录留下临时材料。

<a id="stock-period-stage-six-execution"></a>

### 13.18 第6阶段整体验收与交付实施细则（2026-11-12）

#### 13.18.1 目标、当前依据和改动边界

本节补齐第13.9节第6阶段的串联样本、执行入口、正常及失败重跑开销、最终对账和待切换清单。第1至5阶段的业务口径及第13.14/13.15节合同保持。本节是开发前的实施设计，不是第6阶段验收结果；本轮只修改原方案和两份LLD。

代码依据为第5阶段提交`202739e60`及当前周月线实现。第13.17节保留当时资金流分类导致全局静态suite失败的历史；11月12日开工审计已用原受保护启动器完整复核，结果为113项测试及5项subtest通过，共15批。该项不再是当前阻断，不能将其他任务的旧失败继续列作本需求欠项。可选PostgreSQL测试仍未执行，隔离SQLite结果不代表正式PostgreSQL验收。

第6阶段拟新增`lake_console/orchestrator/tests/test_stock_period_workflow_integration.py`，只承载完整流程测试，不注册新资产、job、sensor、配置项或业务状态。现有正常链路继续使用下表代码；必要缺陷必须先定位到本LLD已有要求，同步原文档后作最小修正，不借验收增加业务要求。

| 验收步骤 | 当前实现及复用测试，路径相对`lake_console/orchestrator/` | 本步影响面 |
| --- | --- | --- |
| 当日预检、两频Raw日更 | `defs/sensors/raw_stock_weekly_update_job_sensor.py`、`raw_stock_monthly_update_job_sensor.py`，`stock_period_update.py`、`source_readiness/stock_period.py`；`tests/test_stock_period_native_daily.py` | 实际代码位于`src/orchestrator/`下；使用真实名单SQL、源参数、运行配置、当期合并及原检查 |
| 两频复权因子历史回刷 | `defs/sensors/raw_stock_period_history_repair_job_sensor.py`、`stock_period_history_repair.py`；`tests/test_stock_period_history_repair_native.py` | 复用相邻交易日Silver股票复权因子比较、两频Raw完成引用和独立job |
| 本频退市清理 | `defs/sensors/raw_stock_period_retirement_cleanup_job_sensor.py`、`stock_period_retirement_cleanup.py`；`tests/test_stock_period_retirement_cleanup_native.py` | 复用确认退市事实、本频代码列集合统计、原生父运行范围与独立job |
| 完整范围Silver接续 | 两个`defs/sensors/silver_stock_*_update_job_sensor.py`、`stock_period_silver.py`、`asset_guards/stock_period_delivery.py`、`io/stock_period_silver.py`；现有Silver各专项测试 | 验证真实Raw引用、完整周期、cursor推进、文件和绑定原物化的检查 |
| 人工维护、首次建库保留及旧实现清零 | 第13.14/13.15/13.17节列出的CLI、配置、IO及测试 | 新串联测试接通人工指定历史和仅删除；其余分支复用现有正反回归，不复制旧业务实现 |

本表`defs/`文件均在`src/orchestrator/defs/`，同列未重复目录的协调文件也在该目录。正式四个资产、六个job及六个sensor保持；只核对Definitions、catalog、运行契约、拓扑和静态门禁是否与现有实现一致，确有描述错误时同步原文件，不扩大为无关清理。无Prod、前端/API消费者变更。CodeGraph explore/callers/impact结合直接源码核对入口、配置消费者、原生记录、IO和CLI；索引未给出的动态调用已用源码补核。

#### 13.18.2 临时资源、样本合同和替身边界

测试使用本任务独立`/private/tmp`目录下的Lake三层、staging、DuckDB临时空间和Dagster SQLite实例；两层目标处于同一文件系统，真实执行候选校验及`os.replace()`。不读取正式Lake明细，不使用正式凭据、数据库、实例、分区、cursor或服务。固定上海业务日为2026-11-10，校验19:59不探源、20:00开始探源；当周标签`20261113`，当月标签`20261130`。

复用`test_stock_period_native_daily.py::market`的生命周期、身份和最终停复牌文件合同，扩展交易日历为11月6、9、10日；沿`duckdb_sql.adj_factor_normalized_select`写DATE/VARCHAR/DOUBLE类型的两日Silver股票复权因子。Raw及Silver股票基础资料只投影真实生产者的`ts_code/list_status`、`ts_code/curr_type/list_status`字段。21列源记录沿`test_stock_period_silver_contracts.py::literal_row/write_raw`及现行SPECS，金额/价格精度与允许NULL列不改变。

以下证券状态是小样本模拟，沿用已有夹具代码，不表示这些证券真实上市、停牌或退市事实：

| 股票代码 | 11月10日样本事实 | 应有行为 |
| --- | --- | --- |
| `000001.SZ` | 已上市，股票复权因子1.0变为1.1 | 两频当期必需；日更后仅此代码进入两频复权因子回刷 |
| `000002.SZ` | 已上市，当天全日停牌；两日股票复权因子均1.0 | 两频源可缺席；保留本地价格4的已有记录 |
| `301393.SZ` | 当天新上市；前日无股票复权因子，当日为1.0 | 两频当期必需，日更首次写入价格12；不进入复权因子回刷 |
| `000003.SZ` | 已上市，仅10:00—10:30停牌；两日股票复权因子均2.0 | 两频当期仍必需；后续用于人工指定周线历史 |
| `000004.SZ` | 生命周期和Raw股票基础资料均确认当日退市，身份已确认 | 不属于当日应更新名单；只在对应频率清理中删除 |
| `000005.SZ` | 次日才上市 | 不属于当日应更新名单 |

生命周期6行、身份6条已确认自映射、最终停牌2行。前日股票复权因子含`000001/000002/000003/000004`四只，当日含`000001/000002/000003/301393`四只，完整代码带上述交易所后缀；新股不被误算作复权因子变化。Silver股票基础资料只纳入当日已上市的前四只应有/可选股票，不纳入确认退市和次日上市股票。

只替换源传输、时钟、临时路径和“上游已验收”事实，不替换名单SQL、sensor决策、RunRequest配置、job执行、候选IO、Dagster交付与检查、Silver接续和最终文件读取。上游生命周期、停复牌、股票基础资料和股票复权因子生产者本身不在本次串联中重跑，按真实schema和现行专项证据核对。源响应为替身，不能宣称实测Tushare；现有真实接入边界证据继续采用第13.10.5节，不重复请求源站。

#### 13.18.3 正常串联顺序与独立预期

新增测试分别执行“先周Raw、后月Raw”和“先月Raw、后周Raw”，每种顺序使用全新实例和文件。频率成功事件使用实际成功运行及`get_run_success_event()`构造`build_run_status_sensor_context`，调用已装饰的正式sensor；普通sensor使用实际临时instance、Definitions及cursor构造`build_sensor_context`，通过`evaluate_tick`执行实际tick并使用返回的cursor和请求。当前安装版直接调用普通sensor会把`required_resource_keys`作为函数参数注入，现有context资源签名不适用；不能为测试改动生产签名或绕过正式sensor。此方式沿现有测试、安装版实现及[Dagster sensor测试接口](https://dagster.io/docs/api/dagster/schedules-sensors)。不自行实现调度器，也不启动daemon。

测试驱动按实际`SensorResult.dynamic_partitions_requests`更新临时分区，使用`RunRequest`的`job_name/partition_key/run_config/tags`执行临时job，并把其`run_key`按Dagster现有`dagster/run_key`运行标签登记；不改写配置或重算应有名单。Silver每次使用上次返回的cursor，成功后再调用sensor确认消费，再进入下一次Raw文件改写。上述驱动只存在测试文件中，不能成为新的正式提交入口。

1. 先创建四份临时全市场Raw文件：周`2026-11-06/2026-11-13`、月`2026-10/2026-11`。每份含`000001/000002/000003/000004`四只；前一周额外保留`000001.SZ,20261105,week`键。共17条。新股起初不存在。`000001`旧价格前期9、当期8；`000003`旧价格前期8、当期13；停牌股票4、退市股票1。额外键价格7。来源截至日取11月9日，停牌股票取11月6日；Raw旧记录合法性按现行校验，不造缺列或非法类型来绕过校验。
2. 两频各先返回缺新股的三列探测，再返回`000001/301393/000003`三只完整结果。前者不能提交，后者才提交；核对具体代码和当天`end_date`，全日停牌股票源缺席仍能通过。按真实RunRequest注册临时分区并执行相应Raw job，正式下载三只的价格分别为11、12、13。第一次Raw成功时，历史回刷sensor仍等待另一频；各自清理sensor只产生本频请求，暂存请求至下述清理步骤。
3. 两频Raw均成功且原检查通过后，历史回刷sensor产生只含`000001.SZ`的两频请求。先让两次当期Raw交付各被对应Silver真实消费，再执行该回刷：周历史返回`20261106/20261113`，月历史返回`20261031/20261130`，价格均5，来源截至日均11月10日。只传`ts_code + freq`及分页参数，不传日期过滤；原额外键仍保留。两频Silver按各自完整两文件范围接续。
4. 分别执行前述周清理请求、月清理请求，各只删除本频两文件中的确认退市代码，并立即让同频Silver消费完整交付。另一频文件不受本频任务改写；不把新股、全日停牌股票或盘中停牌股票纳入清理。
5. 通过现有人工CLI参数解析和配置builder生成`000003.SZ`指定周线历史请求，源返回两周记录、价格均6，再让周Silver消费。随后通过同一正式入口生成仅删除`(000001.SZ,20261105,week)`的身份维护请求，不请求源；只交付前一周文件并让周Silver接续。不得手写预期完成事件冒充job执行。
6. 重复同日Raw sensor检查，断言已有运行key后不再探源；重复两频成功回调核对历史回刷key稳定。测试驱动只执行每个唯一请求一次。这里只证明sensor输出与key稳定，daemon队列去重、正式并发及正式运行状态不在此证据范围。Silver沿真实cursor完成请求与确认，不用无限轮询推进测试。

最终读回四份Raw和四份Silver；以字面业务预期核对，不能调用待测选择器生成expected。除前一周额外键被明确删除外，其他股票及文件保留规则逐项核对。最终价格和代码为：

| 文件周期 | 最终代码及`close_qfq` | 每层最终行数 |
| --- | --- | --- |
| 周`2026-11-06` | `000001=5,000003=6,000002=4` | 3 |
| 周`2026-11-13` | 上述三只，加`301393=12` | 4 |
| 月`2026-10` | `000001=5,000003=8,000002=4` | 3 |
| 月`2026-11` | `000001=5,000003=13,000002=4,301393=12` | 4 |

表中代码均带前表后缀。Raw和Silver各14条、各4份文件；两层是同一行情的不同加工结果，不能计作28根独立K线。逐阶段核对Raw规范化行数、文件合并后行数、Silver规范化行数和最终行数：日更后Raw共19条；复权因子回刷不改总条数；退市清理后15条；指定周历史仍15条；明确键删除后14条。Silver前期对额外键的周期归一化及退市过滤按原合同验收，不强求中间行数与Raw相等。

#### 13.18.4 失败退出后整批重跑

新增串联故障仅覆盖以下三个跨步骤情形，详细负向边界沿已有回归，不展开重复排列。失败注入在真实首份文件替换后、登记该文件物化前；不得用替身跳过候选校验或实际替换。每次失败与重跑均为不同运行。

| 情形 | 失败后重跑方式与必须断言 | 一次失败加一次成功的范围与开销 |
| --- | --- | --- |
| 一只股票、两频历史回刷，完整目标4文件 | 使用相同业务配置发起新job，重新请求两频完整历史并重建全部候选；失败运行没有完成引用和成功结果，Silver只消费成功运行的4文件 | 两次各2源单元，共4次替身请求、8条累计源历史行；首轮已替换1文件，重跑替换4文件，共5次Raw替换，随后4次Silver替换 |
| 单频退市清理，原命中2文件 | 沿当前Dagster原生父运行关系关联原失败运行；重新计算并与原工作范围取并集，完整交付2文件。首份已清理文件再次检查、不替换；另一份实际删除。不得依赖旧JSON | 源请求0；累计2次Raw替换、2次成功后Silver替换。代码列定位失败前1次、重跑前1次、重跑后1次，各覆盖本频2文件，共3次集合统计、6个累计文件参与；不是物理磁盘读取次数 |
| 周Silver消费一次两文件Raw回刷交付 | 使用同一Raw完成引用发起新Silver运行，重新生成全部2文件；失败的部分物化不代表引用已消费，成功后完整原检查绑定本次物化并推进cursor | 源请求0、Raw替换0；失败替换1份，加重跑2份，共3次Silver替换；最终验收2文件及完整消费结果 |

每例仍执行成功后的全部原检查和文件读回，保留失败事件用于断言，不能只看重跑状态SUCCESS。末次读回分别为历史回刷4Raw+4Silver、周退市清理2Raw+2Silver、周Silver重跑2Silver，字面核对schema、业务键、价格、来源截至日和行数并记录审计开销。此时尚未做人工维护，盘中停牌股票的前期/当期价格仍8/13；历史回刷例Raw仍保留退市股票和前周额外键，周退市例只删除退市股票，Silver沿原过滤及周期归一化。日更、人工维护和Silver其他中断位置的整批新跑，以及首次建库自身恢复、完成后apply拒绝、事件补齐、空文件/零命中和混合增删等已有用例必须纳入全套回归。首次建库恢复继续限其本次执行；不得将其manifest恢复机制带回日常任务。

#### 13.18.5 正常、重跑与最终验收预算

沿第13.10.5、13.14.5、13.15.6节的实际工作量公式及`StockPeriodPolicy`，不新增配置或提高上限。当前默认页6000行，RSS为4GiB、DuckDB为3GiB及2线程，spill为16GiB、workspace为32GiB；这些是现行配置限制，不是本次小样本的预计占用或吞吐保证。

以下只计算**一种正常先后顺序**；另一顺序使用独立资源，按同样步骤再计。样本每单元均少于6000行，无满页、重试和真实网络：

| 步骤 | 源单元/请求/累计回包行 | 目标文件处理 |
| --- | --- | --- |
| 缺新股、齐备两次探测×两频 | 4次三列替身请求；每频2行+3行，共10条三列记录 | 不写Raw/Silver文件 |
| 两频正式日更 | 2次21列请求，累计6行 | 2次Raw、2次Silver替换 |
| 复权因子历史回刷 | K=1只、R=2频，K×R=2单元/请求，累计4行 | 4次Raw、4次Silver替换 |
| 周、月分别退市清理 | 源请求0 | 各2文件，共4次Raw、4次Silver替换；本频代码列统计前后各1次，两频共4次集合统计、8个累计文件参与 |
| 人工指定周历史 | K=1只、R=1频，共1单元/请求，累计2行 | 2次Raw、2次Silver替换 |
| 仅删除明确周键 | 源请求0 | 1次Raw、1次Silver替换 |
| 最后验收 | 不请求源；读回4Raw+4Silver，核schema、键、日期、价格、行数及原检查绑定 | 8份唯一目标文件，不另复制全市场或生成备份 |

正常合计9次替身源调用、真实网络0；其中正式21列回包累计12行，三列探测累计10行另计。多次请求会返回相同周期，不能将累计12行称为12根独立K线。Raw累计13次替换、Silver累计13次替换，最终唯一文件各4份；初始夹具及上游参考文件的创建单列。原生业务事件沿既定公式计：Raw日更`4F+2R`、独立Raw任务`4F+3R`、Silver`4F+2R`，F为该步完整文件数、R为实际频率交付数；本样本各步都有非空文件。运行日志、引擎事件和上游夹具事实单列，不混入公式。

上述预算之外还须计入：名单/身份/停牌/股票复权因子读取，源持久化与分组，旧目标检查、候选COPY与校验、原子提升前后身份检查，文件摘要缓存未命中时的计算，Dagster物化/检查/引用查询，Silver候选与最终8文件核验。沿现有集合查询实现和各步骤实际调用登记SQL数量，不把文件参与次数当物理IO字节。故障例按13.18.4逐次加计全部源、候选、事件、Silver和末次验收；旧失败运行残留的staging占用真实空间，不能当作零成本或可复用源。

执行时分别记录准备、探测、Raw、各独立任务、Silver、失败和重跑、最终审计的耗时，以及输入/候选/输出字节、RSS峰值和spill。缺少现有测量依据的总耗时、物理读取字节和峰值不预填数字，不套用全市场倍率或额外余量。首次建库保留回归继续使用第13.14节既有有界样本和事件集合SQL预算，不在本阶段发起全历史建库。真实全市场吞吐及正式写湖成本只能在后续具体范围获准后测量。

#### 13.18.6 测试入口、执行顺序和停止条件

开发入口为上述新增测试文件和必要的既有测试夹具；生产路径仅在发现已确认要求的真实缺陷时最小修改。所有测试从`lake_console/orchestrator`使用现有`.venv`，不装依赖、不设置手工PYTHONPATH、不隐式同步环境。

1. 先审计本节约束到代码/测试的映射，检查替身是否只覆盖13.18.2列明边界。初始化本任务独立`/private/tmp/dg-stock-period-acceptance-*`目录，临时`DAGSTER_HOME`明确禁用telemetry，`TMPDIR`、pytest basetemp、日志及可选JUnit结果全指该目录，设`PYTHONDONTWRITEBYTECODE=1`。核对实例和Lake绝对路径后才运行。
2. 定向执行`.venv/bin/python3 -B -m pytest -q -p no:cacheprovider tests/test_stock_period_workflow_integration.py --basetemp=<本任务临时目录>/focused`，通过后执行现有`tests/test_stock_period_*.py tests/test_stock_weekly_*.py tests/test_stock_monthly_*.py`全套，同样关闭cache并使用另一个工程外basetemp。新文件包含在全套中，重复执行数分别报告，不相加充当不重复用例数。可选PG未启用如实记录，不安装或启动正式服务凑齐测试。
3. 执行`.venv/bin/ruff check --no-cache --select E9,F63,F7,F82 src tests`及本次实际修改Python文件的默认规则。既有未修改告警与新问题区分，不能过滤新问题取得通过。
4. 全局运行合同静态suite必须使用`.venv/bin/python3 -B tests/stock_suspend_confirmed_test_runner.py --scope regression --suite test_run_contract_static_gates.py`，不得直接pytest替代受保护启动器或删减用例。启动器自建临时目录按本次日志逐一核对、清理，不清其他任务资源。
5. 清洁环境使用现有`.venv/bin/dg check defs --use-active-venv --no-check-yaml`，正确设置现有VIRTUAL_ENV、临时实例和缓存目录，关闭telemetry；不加载根`.env`或正式DAGSTER_HOME，不执行job。随后运行根目录`python3 -B scripts/check_docs_integrity.py`、本次文件`git diff --check`和新增相对链接/锚点核验。文档完整性检查不替代代码语义和隔离集成。
6. 自查之后按管理员要求完成独立实现审计：核对原LLD硬口径、测试与真实合同、文件和原检查、旧引用清零、数量和失败重跑预算。审计发现漏项先修正并补必要回归，再记录最终结论；任一未处理问题如实列出，不能以阶段推进掩盖。

发现方案口径冲突、夹具与真实生产者schema不符、实际读写指向正式资源或新增需求时停止相关步骤，说明依据并先修正文档。缺包、需要全局正式数据明细读取或正式操作仍按原审批边界处理。不给本阶段增加此前已明确不处理的业务问题。

#### 13.18.7 最终对账、待切换清单和收尾

完成第6阶段后，将实际结果写回本LLD第13.19节，原方案10.19和月线LLD第11节同步当前状态。结果须区分单元、隔离集成、既有真实源样本、未执行可选测试和正式执行；本轮尚无13.19结果，不能预写通过。至少交付：

- 逐条计划对账：20:00、两频单点/三列与21列、应有/可选代码、新股、两频完成后复权因子变化回刷、单频退市、人工三模式及精确键、首次建库保留、旧代码清零、完整范围Silver和原检查、整批新跑、性能。每条列真实代码、正反测试、证据种类、实测数量和结论；零复权因子变化、全日停牌有效返回、身份混合增删等由既有回归覆盖，闭合周期补齐使用下述新增六例，不重复增加业务规则。
- 过程与末次文件对账：源/规范化/合并/写入/读回行数，完整周期集合、实际来源截至日、代码与键、价格及精度、重复/NULL合同、检查绑定与消费结果；失败部分不能记成功。列正常及重跑每项实测开销，说明与本节推导的差异。
- 待切换清单：现有code location；Raw周/月日更、Silver周/月日更、独立复权因子回刷及退市清理共六个job；Raw周/月、Silver周/月、历史回刷及退市清理共六个sensor；对应日期、分区及cursor、旧未完成运行/文件/事件的交接责任和处理入口。逐项列代码默认状态、正式当前状态、拟操作、精确范围、所需批准和核验结果。源码默认STOPPED不能代替正式状态；未在本次核验的正式状态写“待核验”，旧欠账不能据源码清退自动记零。

待切换清单按下列现行名称逐项核对，人工维护复用独立历史回刷job，不增加第七个job：

| job | sensor |
| --- | --- |
| `raw_stk_period_bar_adj_week_update_job` | `raw_stock_weekly_update_job_sensor` |
| `raw_stk_period_bar_adj_month_update_job` | `raw_stock_monthly_update_job_sensor` |
| `silver_stock_weekly_update_job` | `silver_stock_weekly_update_job_sensor` |
| `silver_stock_monthly_update_job` | `silver_stock_monthly_update_job_sensor` |
| `raw_stock_period_history_repair_job` | `raw_stock_period_history_repair_job_sensor` |
| `raw_stock_period_retirement_cleanup_job` | `raw_stock_period_retirement_cleanup_job_sensor` |

**闭合周期覆盖补正。** 第6阶段逐条对账确认“闭合周期由既有正向回归覆盖”的判断错误，现有两处`closed_period`参数只证明它不能触发日更回刷/清理，不证明补建正确。补齐当前已确认功能的验收，不增加生产业务：在同一测试文件新增`test_closed_period_union_and_last_required_date`，以周`2026-10-30`、月`2026-10`分别调用现有Raw job的`intent=closed_period`，业务末交易日2026-10-30；月源单点仍为自然月末`20261031`。该例生命周期限定A/I/S三只、类型沿真实生产者，交易日历为10月29/30日；29日无全日停牌，30日S全日停牌、I盘中停牌。周期并集仍必须含S，其最低来源截至日为29日，而A/I最低为30日。

每频分别验证缺S拒绝、S截至28日拒绝、S截至29日成功；成功源中A允许后来重算到11月10日、I截至10月30日。明确业务意图日仍10月30日、实际文件来源可为11月10日；通过后由同频真实Silver sensor及job接续，核三只完整价格、日期、原检查及消费。四次拒绝均须在目标创建/替换前失败，不发布完成结果。原Raw job是人工指定闭合周期入口，不新增sensor或三列预检。两频共6次单页21列替身请求，累计返回`(2+3+3)×2=16`行；4例拒绝目标替换0，2例成功合计2Raw+2Silver文件、每文件3行。新增请求、准备、原检查及末次读回的实际成本另记；不修改生产代码。本项先补设计，再编码，补齐前撤回“第6阶段完整覆盖”的结论。

本阶段开发和隔离验收不包含重载正式code location、启停sensor、提交正式job、注册正式分区、写正式事件或Lake。正式切换及有界正式验收仍按13.7/13.9节单独批准，拿到具体范围后才补相应执行步骤与成本。本次只补文档不执行这些动作。

有效结果和审计结论落回上述原文档；本任务工程外源回包、候选、实例、spill、脚本及日志核验后清理，不在工程内生成过程附件，不保留重复报告。清理只限本任务资源，不删除正式文件、历史运行记录或其他任务的临时目录。

**本次文档补齐后的审计。** 已对照当前代码核实六个job/sensor、临时测试入口、源参数、名单/股票复权因子/退市选择、按键合并及Silver消费顺序；复算17→19→15→14行、9次替身调用、两层各13次累计替换和三个失败重跑范围。三份文档新增锚点、现存测试路径与引用名称检查通过，根文档完整性及本次差异空白检查通过，CodeGraph索引同步并确认最新。第6阶段的实施细节已完整，具备隔离整体验收开发的开工条件；本次未创建新测试文件、运行第6阶段测试或执行正式操作，未提交修改，不将本次文档审计计为第6阶段完成。

<a id="stock-period-stage-six-results"></a>

### 13.19 第6阶段实现、隔离验收和独立审计（2026-11-12）

#### 13.19.1 实现与逐条计划对账

管理员批准先提交实施文档，再推进第6阶段开发和隔离验收。三份设计文档已提交为`982619968`；本阶段新增`tests/test_stock_period_workflow_integration.py`，并更新本LLD、原方案、月线LLD、拓扑和运行契约的当前状态。本阶段生产Python、四个资产、六个job/sensor、配置和源合同均未改动，不安装依赖，不修改Prod及前端/API。下表路径相对`lake_console/orchestrator`，协调源码均位于`src/orchestrator/defs/`。

| 已确认要求 | 当前代码与本阶段验收 | 补充专项证据及结论 |
| --- | --- | --- |
| 20:00起、周五/月末单点、三列预检与21列正式下载 | 正式Raw sensor → `stock_period_update` → `source_readiness.stock_period`；新增`prepare_daily/raw_sensor`执行实际tick，19:59无源调用、20:00缺新股不提交、齐备才提交，并核完整请求参数/字段 | 两种Raw先后顺序通过；`test_stock_period_native_daily`保留源不足、日期错误及正式下载再次检查的正反验证 |
| 当日在市及最终停牌名单；新股随日更，只有股票复权因子变化才回刷 | 真实名单SQL及`load_factor_changed_codes`；新增样本核三只必需、全日停牌可缺席、盘中停牌仍必需，次日上市/当日退市排除；回刷只含`000001.SZ` | 新股首次写入两频，但不进入回刷；现有`test_thirteen_factor_changes_and_new_ipo_are_separate`及零变化/停牌有效返回回归通过 |
| 两频Raw原检查齐备后独立历史回刷 | 实际成功事件sensor生成请求，`execute_history_repair`重新读相邻两日股票复权因子并请求无日期过滤的两频历史 | 首频成功仍等待另一频、两种完成顺序生成同一key和配置；回刷4文件完整交付且原额外键保留 |
| 单频退市清理及同频Silver接续 | 实际退市sensor → `execute_retirement_cleanup`；代码列集合统计只定位本频，另一频文件身份保持 | 周、月分别清理并消费；现有零候选、零命中、正式上市前记录和累积结果回归通过 |
| 人工三模式、闭合周期补齐和精确键，不恢复旧实现 | 新串联按实际CLI解析/builder执行指定周历史及仅删除；`test_stock_period_manual_maintenance/manual_cli`覆盖其他人工分支，原native用例覆盖实际较新Raw接续；新增`test_closed_period_union_and_last_required_date`六例实际运行两频闭合补建及Silver | 核不整股删除、回刷不删源未返回键；混合处理、空文件/已无记录、缺目标拒绝等现有回归通过。新链无`daily.json/baseline.json`；闭合周期并集、逐股最低日期、缺失/过旧拒绝及较晚来源日期均通过 |
| Raw/Silver完整范围、实际来源日期、原检查绑定及消费cursor | 新增`origins/consume/read_rows/assert_final`实际执行原jobs和原检查，读取原生交付、确认消费后再改下一次Raw | 每种正常顺序最终两层各14条/4文件；142条业务事件，完整21列schema、精度、键和截至日与字面预期相符 |
| 失败后整批新跑，不使用日常续跑文件 | 新增三个真实首文件替换后失败例，旧运行无完成结果；新运行重取/重建完整范围，清理用原生父运行保留完整范围，Silver用原Raw引用新跑 | 审计补强后实际读回8/4/2文件，见13.19.3；未把失败任务记作已消费 |
| 首次建库自身恢复和旧实现清退边界 | `test_stock_period_history*`、`test_stock_period_memory_resume`及现有静态清退断言 | 保留源/COPY/候选恢复和原Silver审计合同；完成后apply拒绝、事件集合登记、旧入口清零回归通过。未重建正式历史 |

普通sensor采用安装版真实`evaluate_tick`、临时Definitions和`partition_loading_context`，按返回请求和cursor推进；成功事件sensor采用实际运行及成功事件。四份种子Raw文件对应分区预先注册在临时实例，sensor返回的同名新增请求幂等应用；本例不声称验证正式新分区注册。测试驱动登记实际`dagster/run_key`，只证明请求/key稳定及已有运行后的停止探源，不冒充daemon调度去重验收。临时路径、时钟、源响应和上游已验收事实为替身，其余上述执行/SQL/文件/事件为真实临时链路；真实源接入继续引用13.10.5节既有样本。

#### 13.19.2 实际测试结果

- 最终完整执行`test_stock_period_*.py/test_stock_weekly_*.py/test_stock_monthly_*.py`：**475 passed，2 skipped，139.89秒**。477个收集项中两项为未启用的PostgreSQL专项，明确取消`DG_PERIOD_PG_VERIFY`启用条件；没有用正式PG替代测试。最终全套包含本次新增11例。
- 三个故障例末次读回补强后的五例串联资源定向：**5 passed，20.44秒**；闭合周期分阶段资源记录补齐后定向：**6 passed，4.35秒**。与最终全套分别报告，不相加充当独立用例数。生产代码在本阶段各次补强前后均未改动。
- 原受保护启动器执行完整`test_run_contract_static_gates.py`：**113 passed，5 subtests passed，共15批**。无用例筛选、直接pytest替代或正式writer执行。
- 全`src/tests`的Ruff致命错误基线通过；新增测试文件默认Ruff检查通过。使用现有环境、工程外实例与干净环境的`dg check defs --use-active-venv --no-check-yaml`通过。未同步或安装依赖。
- 原方案/两份LLD及本次拓扑、运行契约引用按现行代码对账，根文档完整性及本次差异检查通过。CodeGraph使用explore配合直接调用方核对，完成后同步索引；本阶段没有契约、依赖方向或跨工程消费者改变。

#### 13.19.3 实际数量、末次验收和性能

成功测试使用`-s`将实际资源JSON保存在本任务工程外日志，再读日志和JUnit核对下表；不是从预算表抄成实测。源均为替身，真实网络请求0。两种正常顺序每例均为三列探测4次/累计10行、21列下载5次/累计12行，Raw/Silver各13次替换。种子及参考文件为12份、17,827字节，单独列计。

| 场景 | 本例JUnit时间（含准备、断言和收尾） | 本场景末次文件读回 | 末次文件审计时间 |
| --- | --- | --- | --- |
| 先周后月正常串联 | 6.114秒 | 8文件，Raw14/Silver14条，25,920字节 | 0.0602秒 |
| 先月后周正常串联 | 4.762秒 | 同上；为另一套独立资源，不当成16份唯一业务文件 | 0.0571秒 |
| 复权因子回刷失败后新跑 | 2.791秒 | 8文件，Raw19/Silver14条，29,216字节；Raw保留退市股及额外键 | 0.0595秒 |
| 周退市清理失败后新跑 | 3.263秒 | 4文件，Raw8/Silver7条，12,967字节；额外键仍保留 | 0.0284秒 |
| 周Silver失败后新跑 | 2.459秒 | 2文件，Silver7条，6,475字节；Raw文件身份未变 | 0.0141秒 |

失败加成功的局部新增开销符合13.18.4：复权因子回刷重取4单元/累计8行、5次Raw和4次Silver替换；周退市清理源0、2次Raw和2次Silver替换，3次本频集合统计；周Silver源0、Raw替换0、Silver替换3次。上述局部数字不含其前置日更和准备，末次文件核验已实际执行且计时，不能漏计或与全例累计值混用。

正常每例候选累计Raw47,680字节、Silver42,127字节，这是13+13次候选/输出的累计，不是唯一文件大小或实际磁盘读取量。阶段日志同时登记探测、job、候选/旧目标/源文件字节、源持久化和包括失败运行在内的staging占用。`prepare_extension`只计新增夹具准备，不含既有`market`夹具；整体JUnit时间含其实际开销。正常helper SQL计数141次，只统计经过`stock_period_raw.execute`的调用，名单/身份直接SQL、Dagster内部SQL不在此数字内，不称总SQL次数；退市的4次正常集合统计及3次失败重跑集合统计另已断言。

上述五例资源定向所在pytest进程累计RSS峰值为451,985,408字节；各阶段预算检查观察到的最大RSS为451,919,872字节。前者包含前例及测试框架，后者是实际检查点采样，不是逐阶段连续测量。五例结束时spill残留均0字节，只代表末次残留，不声称未发生过瞬时spill。默认4GiB RSS、3GiB DuckDB、2线程、16GiB spill及32GiB workspace均未改变；本次结果不外推正式全市场耗时、文件规模或吞吐。

闭合周期六例实际为6次21列替身请求、累计16行，四次拒绝的目标数/字节均0；周成功Raw/Silver各3行、各3,228字节，月成功各3行、各3,233字节，两例合计4文件12,922字节。成功周/月份分别实测准备扩展0.0116/0.0105秒、Raw job 0.2454/0.2605秒、Raw引用及Silver请求0.0305/0.0271秒、Silver job 0.2589/0.2803秒、最终消费与文件审计0.0266/0.0309秒；各步之和不当作整个用例时间。源持久化分别1,456/1,462字节。该六例单独进程累计RSS峰值330,989,568字节，各例staging末次spill残留0；同样不称逐步峰值或无瞬时spill。

#### 13.19.4 独立审计、待切换清单和边界

非实现者独立阅读LLD、当前源码/测试和实际完整及定向日志。先发现三个故障例原先只核原检查/完整交付，缺少末次字面文件内容读回，这是验收实现遗漏。现由`assert_repaired_files`按独立字面值核21列schema、键、价格、来源日期和精度，分别覆盖8/4/2文件并记录开销。最终逐条对账又确认“闭合周期已有正向回归”的判断错误：原来只有两处非日更触发负例，不能证明补建；此前“完整覆盖”的结论过早并已撤回。现按原业务要求补六例及其分阶段资源证据，同步纠正13.18.7和本节归属，未修改业务实现。最终475项完整回归及闭合资源定向通过后，独立复核两项遗漏均已解决，无剩余实质问题。没有新增业务准入或重新加入管理员明确不处理的问题。

正式代码入口为`orchestrator.definitions:defs`（项目`root_module=orchestrator`）；本次第6阶段隔离验收未查询正式服务实际加载的代码版本、位置名称和状态，下表保留当时待核验的交付状态。随后只读审计确认的正式状态及具体切换步骤统一见第13.20节，不再将本表的“待核验”当成当前审计结论。下列是阶段交付清单，不是执行授权或正式完成记录：

| job及其sensor（均按13.18.7完整名称） | 代码状态/已验证行为 | 正式当前状态与拟核对范围 |
| --- | --- | --- |
| 周Raw日更/周Raw sensor | 定义默认STOPPED；20:00、自然周五与当天三列覆盖 | 待核验。明确切换业务日、当前周分区及旧周运行/工作记录交接；按批准加载及启用 |
| 月Raw日更/月Raw sensor | 定义默认STOPPED；自然月末及当天三列覆盖 | 待核验。明确同一业务日、当月分区及旧月运行/工作记录交接；按批准加载及启用 |
| 周Silver日更/周Silver sensor | 定义默认STOPPED；消费本频完整Raw及原检查 | 待核验。核旧cursor与未消费范围、所需原生引用和周分区后，按明确方案交接 |
| 月Silver日更/月Silver sensor | 同上，限月线 | 待核验。独立核月cursor、未消费范围、引用和月分区，不能套用周线结论 |
| 独立历史回刷/历史回刷sensor | 定义默认STOPPED；同日两频Raw均通过才自动提交；同job支持人工维护 | 待核验。交接未完成的原复权因子日期、名单/原生引用及人工指定范围，不据删代码判零 |
| 单频退市清理/退市清理sensor | 定义默认STOPPED；本频Raw成功后独立提交、结果按频率累计 | 待核验。核正式最近成功结果、待处理代码及本频历史范围，按批准启用和验收 |

清单的执行责任为本次切换的运营执行人；当前任务只交付清单。正式加载/启停/分区/cursor处理及每项补跑由管理员按精确范围批准，之后以实际文件、完整交付和原检查作为验收结果。旧未完成运行、历史文件和业务记录均未清理，不能从源码清退推断交接已完成。正式PostgreSQL、Tushare、daemon及正式写湖验收未执行，本阶段通过不替代这些结果。

本阶段代码和隔离验收已完成，新增测试及结果文档随本次提交保存，提交号以Git记录为准。未部署、重载正式code location、启停sensor、触发正式job或写正式Lake/staging/instance。有效结果落回原文档后，本任务临时目录及受保护启动器的15个本次目录均已删除，涵盖过程日志、实例、候选、spill和早期失败测试材料；未在工程内生成过程附件，未删除其他任务资源。

<a id="stock-period-formal-cutover"></a>

### 13.20 正式只读审计和切换实施细则（2026-11-12，已批准，执行记录见13.21）

#### 13.20.1 目标、依据和授权边界

六阶段开发及隔离验收已经完成。本步目标是让正式DG使用新流程，接通Silver读取位置和两个独立任务，并按实际源日期处理11月11日的欠账。沿用第13.7、13.10、13.15节的业务规则，不增加功能或恢复旧实现。本节编写时仅获只读审计授权，未执行正式操作；管理员随后要求“那就开始推进吧，完成后向我汇报”，现按本节范围推进。实际授权、执行与结果统一记第13.21节，不将文档设计当成执行结果。

代码依据为`stock_period_update.deliver_asset/evaluate_daily_sensor`、`stock_period_silver.evaluate_update_sensor`、`stock_period_history_repair.evaluate_history_repair_sensor/_validate_upstreams`、`stock_period_retirement_cleanup.evaluate_retirement_sensor/execute_retirement_cleanup`及`bootstrap/stock_period_history_cli.py`。用CodeGraph explore核对成功事件入口和调用关系，再逐项阅读实际配置、Silver消费及人工提交实现；影响面限本链六个job/sensor、四个现有资产和其Dagster记录，不涉及Prod、其他数据集、前端/API或配置新增。

#### 13.20.2 已核实的正式事实

以下为2026-11-12上午只读审计结果，末次相关运行计数核对截至08:08:56（北京时间）。实际执行前只复核本节涉及的状态是否变化，不把这些时点数字当成永久上限。

| 对象 | 实际结果与处理依据 |
| --- | --- |
| 正式服务 | `DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`；既有PostgreSQL 18.4，Dagster 1.13.26；code location为`orchestrator`、repository为`__repository__`、模块为`orchestrator.definitions`。06:47:01已加载含新六个job/sensor的定义，运行参数schema与当前代码相符。服务快照不提供Git提交号，不能把server ID当提交号；第6阶段提交号只是源码依据。现有定义已可用，本设计不安排重启或重载 |
| 四个原sensor | 周/月Raw及周/月Silver均为RUNNING。两条Raw最新tick在20:00前跳过；两条Silver因旧`schema_version=1`游标返回`silver_sensor_cursor_requires_cutover`。Raw不需要另做旧游标迁移 |
| 两个新sensor | `raw_stock_period_history_repair_job_sensor`、`raw_stock_period_retirement_cleanup_job_sensor`均已出现在正式定义，实际为STOPPED，尚无该job正式运行；不是定义缺失 |
| 运行 | 本链相关运行103笔，审计首末计数相同、未完成运行0；未触发任何运行。这个计数不证明数据齐备 |
| 11月11日晚失败 | 周Raw `245ce811-cbab-4437-ad7f-bb53ad762d12`在19:30:30创建，月Raw `399d1c52-4668-433d-811f-99ed8da7e8ff`在19:30:41创建。两者都在op开始前因`DagsterInvalidConfigError`退出：旧sensor提交`request_id/stock_codes`，新worker只接受`automatic_intent_date/intent`，尚未请求Tushare。此前遗漏了共享工作目录源码变化对新worker的影响，这是判断遗漏；本次失败不能归因为源未更新，也不能原样重执行旧配置 |
| 当期四份文件 | 周分区`2026-11-13`、月分区`2026-11`的Raw/Silver均5,575行、21列、无重复/NULL业务键；5,573条来源截至11月10日，另2条截至11月9日。11月10日5,580只在市减7只全日停牌，5,573只应更新代码均覆盖；11月11日减6只全日停牌后应更新5,574只，其中截至11月11日的为0。因此11月10日已齐，11月11日日更未补；11月12日上午尚未到当日窗口 |
| 既有交付一致性 | 定点核对当期及上个闭合周/月共8份Raw/Silver文件：每对21列双向差集计数均0，实际文件身份与对应物化一致，24项既有原检查均通过并准确绑定该物化。只读既有结果，没有执行检查；这8份不代表全历史质量审计 |
| 旧文件中的待办 | `data_lake_staging/stock_period/daily.json`仅余一条周执行`1ec27679c962692bf95dbd5169267b6218f3ff431fa1d2ca2ce0d80b93dd3090`，已标`consumed=true`；其manifest为`files_complete`。对应Raw/Silver成功、文件及旧交付摘要已相互核实，属于完成后残留，不能再当欠账补跑。`baseline.json/daily.json`及旧manifest只作本次历史交接证据，新代码不读取；不删除、改写这些物理文件，也不恢复旧JSON处理代码 |
| 股票复权因子变化回刷 | 使用现行比较SQL对11月10日、11月11日已发布的Silver股票复权因子做计数，变化8只、未解决身份0；旧处理日期停在11月10日，新独立job无正式结果。11月11日这8只的两频回刷仍待处理，具体代码和摘要由原选股函数在预览及正式job中重算，不人工编名单，不加入新股 |
| 确认退市 | 现行股票基础数据、生命周期和确认身份规则得到343只规范退市股票。仅对代码列做计数，周Raw 1,823文件、月Raw 432文件中，连同其确认别名的匹配行数及命中文件数均0。343是待登记完成结果的候选数，不是有343只股票的行情需要删除；本次没有历史删除欠账 |

只读审计使用既有GraphQL query、`default_transaction_read_only=on`且语句限时3秒的PostgreSQL连接、DuckDB内存连接及无spill策略；没有构造正式Dagster instance、预览/执行sensor、注册分区或写事件。Tushare没有在本次审计中查询，因此11月11日源现在是否仍可按原日取得，尚未确认。过程目录已清理，事实落回本节，不要求恢复临时附件。

#### 13.20.3 游标转换和sensor操作

正式操作只通过现有控制面`http://127.0.0.1:3000/graphql`或相同网页功能，不直改数据库。已核对安装版`dagster_graphql/schema/sensors.py`和`schema/roots/mutation.py`：`stopSensor(id: sensorState.id)`停用，`setSensorCursor(sensorSelector:...,cursor:...)`设游标，`startSensor(sensorSelector:...)`启用。selector固定包含`repositoryLocationName='orchestrator'`、`repositoryName='__repository__'`及本表sensor全名；id从当次query读取，不拼造。`dg api sensor`采用Dagster Plus连接配置，不用于替代本机正式连接。每次变更均先query确认对象，再检查返回类型与状态并query读回；响应不明时先查事实，不盲重放。本节编写时未发送mutation，获准后的实际操作见第13.21节。

| sensor | 拟执行动作和最后状态 |
| --- | --- |
| `raw_stock_weekly_update_job_sensor` | 切换操作窗口内暂时STOPPED，先按本节明确的原日范围交接；交接完成后恢复RUNNING，保留现有游标及按日去重记录，20:00起检查当天 |
| `raw_stock_monthly_update_job_sensor` | 同上，独立处理月线；不清理11月11日旧失败运行或run key |
| `silver_stock_weekly_update_job_sensor` | 暂停并等待已有tick结束后，按下述证据将游标设为`{"schema_version":2,"after":8020505}`，读回一致再恢复RUNNING |
| `silver_stock_monthly_update_job_sensor` | 同样设为`{"schema_version":2,"after":8013873}`，独立读回并恢复RUNNING |
| `raw_stock_period_history_repair_job_sensor` | 在首笔新Raw成功之前启用至RUNNING，并等待daemon自然完成首次初始化tick；保留初始化产生的原生游标，不手造成功事件 |
| `raw_stock_period_retirement_cleanup_job_sensor` | 同上；首笔周/月Raw成功分别触发本频清理 |

两个Silver的`after`是已经确认消费完成的旧Raw观察记录位置，不是新交付ID。周观察8020505对应Raw运行`6328ef45-875c-4b37-9aa8-0e12282abe06`，Silver运行`73658c5b-6c8f-4c49-b58f-ae31c58e2cc7`；月观察8013873对应Raw运行`186c8218-ee9f-4db6-bf96-8f5a98fe749f`，Silver运行`1f98dd66-5da2-44fc-b861-d259c7c12d34`。已核对旧交付摘要、Silver完整范围消费记录和上述定点文件/绑定检查；相关历史周交付亦已由`ca567611-d4f8-4370-8d0c-86380e221b69`消费，既有恢复验收见第12.26节，不表示本次重新读取全部历史行情。执行时再次确认这两个位置以后没有需要交接的旧交付或尚未处理的新交付；若有，先逐笔核实并修正本节具体位置，不直接覆盖。新schema只改变后续读取格式，不重新解析旧回执，不迁移旧执行ID，不清空为0，不添加`pending`或虚构消费成功。

安装版`run_status_sensor_definition.py`在无游标的首tick把位置初始化到最近成功事件，并直接跳过。因此只点启用还不够：必须读到两条新sensor的首次初始化tick和有效游标，才提交首笔新Raw。只靠启用后补扫旧成功事件会遗漏，本设计不采用该做法。若复核发现已有新Raw先成功且未触发独立job，使用第13.15节人工入口处理原业务日期，不能清空成功事件sensor游标来扫全史。

#### 13.20.4 正式步骤与11月11日欠账

1. **执行前复核。** 按13.20.2限定对象读取正式位置、六个sensor、活动运行、现有参数schema和相关文件/原检查；确认没有未交接的新Raw结果。源代码与加载的Raw配置必须都仅有`automatic_intent_date/intent`，两个独立job和Silver配置必须与第13.10节一致。保持本次工作目录源码在执行期间稳定，防止再出现旧sensor配置和新worker不一致。若不一致，停止并修正实施细则，不自动重启、重载或恢复兼容参数。确认挂载、同设备原子替换和现行空间/内存门禁可用。
2. **完成13.20.3交接。** 暂停两条Raw和两条Silver，等待已有tick/任务结束；转换并恢复两条Silver，启用并等两条独立sensor初始化。只作用于这六条sensor，不停其他服务或任务。此时两条Raw保持暂停，待本次欠账处理后再恢复。
3. **只探测原日源，不先提交。** 复用`source_readiness.stock_period`的现有三列探测，业务日为`2026-11-11`；周请求`freq=week,trade_date=20261113`，月请求`freq=month,trade_date=20261130`，字段均为`ts_code,trade_date,end_date`、分页从`limit=6000,offset=0`开始。名单用该日已验收生命周期与最终停复牌事实，必须逐码满足5,574只应更新代码，停牌可选规则不变；数量执行前重算，不能硬编码旧计数。这个探测不调用sensor preview、不写游标/分区/事件。两频仍满足11月11日截至日，才进入下一步；缺码或过旧继续保留缺口；若源已到更晚日期，走第6步，不能放宽原日日更日期校验。
4. **新配置提交原日两频日更。** 通过现有正式Raw job创建新运行，配置分别为`ops.raw_tushare_stk_period_bar_adj_week.config={intent:'daily',automatic_intent_date:'2026-11-11'}`及同名month配置，分区分别`2026-11-13`、`2026-11`。不传`request_id/stock_codes`，不从11月11日失败运行复制旧配置，不调用已清退CLI或首次建库apply。作业内仍重新下载21列并完整复核，成功后保留实际新`producer_run_id/freq/upstream_batch_id`。同频Silver、新退市清理、两频齐备后的历史回刷由已启用sensor按现行规则接续；不再人工重复提交同一自动请求。
5. **验收原日交付和8只回刷。** 核对新Raw成功及原检查、同频完整Silver交付和原检查；两频Raw齐备后核独立回刷的`business_date=2026-11-11`、实际重算8只及摘要、两频源单元、完整文件范围、结果检查与Silver接续。只有这些结果真实完成才记原日回刷已补。首轮退市按第13.20.5节验收。然后恢复两条Raw sensor，核六条最终RUNNING；当日20:00后的检查以当日日期自行提交，不把手工补跑的日期混入当天去重。
6. **源已前移时。** 若有一频已不能满足原日精确截至日，停止原日两频补提交，保留11月11日日更未交付的事实。恢复两条Raw，让后续交易日20:00按当天源齐备条件日更；以随后通过检查的两频新Raw完整交付覆盖原日当周/当月，按`_validate_upstreams`核实原日应有码及最低来源日期后，使用现有人工入口单独补11月11日复权因子变化历史。预览命令为`python -m orchestrator.defs.bootstrap.stock_period_history_cli maintain --intent factor_changed --business-date 2026-11-11 --upstream-completion '<实际周新引用JSON>' --upstream-completion '<实际月新引用JSON>'`；只在现有环境执行，预览不加`--submit`。核对实际8只、摘要、固定两频和16逻辑源单元后，正式提交才追加`--submit --remote http://127.0.0.1:3000 --repository-location orchestrator --repository __repository__`。不指定股票名单或日期过滤，不用旧观察记录拼新引用。若两频后来均成功补出了原日日更，优先核实是否已经自动回刷，避免再提交人工任务。后续日更覆盖行情和原日回刷办结分别登记，不伪造11月11日原日日更成功。

第6步使用后续日已验收Raw是第13.7及13.15节已有人工原日回刷规则，不增加源历史新旧版本检查或再次查询Silver股票复权因子验收状态。当前周和当前月尚未闭合，不能用`intent=closed_period`绕过日更日期限制。预检后正式下载若源前移或重新不齐，当前job仍拒绝交付，转回上述分支，不补字段、不删应有码、不放宽检查。11月12日及再往后的正常当日日更不额外纳入本次欠账人工提交范围。

#### 13.20.5 首次退市结果、失败与中断

本次没有可直接承接的新退市成功结果。343只为审计时实际确认退市名单，正式启动前按现行事实重算；名单变化先更新本节数量及范围，不硬编码343。由首笔新周Raw成功触发周清理、首笔新月Raw成功触发月清理，分别重新统计本频代码列。若仍为零命中，两笔正式job应成功登记本频实际完整名单和`file_count=0`，Raw替换0、Silver交付0、Tushare请求0；这是零命中文件，不是零候选股票。不得手工写“343只已清理”的结果或从旧JSON灌入已完成列表。若事实变化出现命中文件，先按实际F及字节核定范围与预算，更新本节执行清单后再按既有清理规则执行，不把本次零命中审计当成历史删除批准。

日更、复权因子回刷、退市清理及Silver失败后均创建新运行，按原业务配置完整执行，不接续源页、候选或文件位置，不恢复旧日常resume。退市清理新跑必须带实际失败运行的Dagster父运行关系，沿既有`parent_retirement_scope`取回原完整范围，不能因前一次已删除部分行而遗漏Silver。Silver用相同真实Raw引用完整重跑；原Raw引用已被合法较新交付替代时沿现有`resolve_update_sources`，不改游标假装已经消费。自动run key已有失败运行时按现有人工review处理，不删除旧运行或去重记录来强迫sensor再提交。

控制面操作中断时先query实际状态：已经转换的Silver游标不倒退，未转换的按其已核实旧位置继续；已启用的新sensor保留实际初始化游标。部分job成功不回滚文件、不用备份或旧实现覆盖，核实实际完整交付后再决定尚需哪笔新运行。源码/加载合同变化、实际旧未消费范围不清楚或文件/原检查冲突时停止后续动作，不能继续推进游标。正式作业自身staging保留其现行用途；临时操作脚本、查询结果和日志只放本任务`/private/tmp`目录，必要结果落原文档后清理，不删除既有正式staging或其他任务材料。

#### 13.20.6 请求、文件、性能及全局读取范围

沿第13.10.2、13.10.5及13.15.6节的现行策略，不新增配置，不继承以前的单次6/8GiB：RSS 4GiB、DuckDB 3GiB/2线程、spill 16GiB、本运行workspace 32GiB；源页6000行、正式传输沿原每页最多3次尝试。以下是按现行代码和审计规模计算的执行量，不是新实测耗时保证。

| 步骤 | 数量、读取/写入边界及成本 |
| --- | --- |
| 控制面交接 | 只变更六条指定sensor的启停状态和两份Silver小游标；每次操作前后有界query读回。新sensor首次初始化等自然tick，不反复preview或扫全史。没有新服务/数据库配置写入 |
| 两频原日探测与日更 | 每频一次三列逻辑探测、一次21列逻辑下载；每次按短页结束。既有5,575行样本少于6000，样本条件下为2次探测+2次下载共4次HTTP；真实页数P及正式重试按实际累计。只处理2份当期Raw、2份同频Silver。探测共用30秒截止，60秒为Raw sensor间隔而非每页时间；未齐不连续轮询源 |
| 8只两频回刷 | K=8、R=2，16逻辑源单元；每股只按`ts_code+freq`请求完整历史，不读全市场源历史。一次失败加一次全范围新跑最多32逻辑单元，实际HTTP仍按两次页数和重试累计。H行一次列式分组，F为源日期定位的去重既有Raw文件数；每次按F份旧文件、F份候选及实际原检查成本计。8只不是8文件，也不能用单股213历史行样本乘8声称真实文件数 |
| 回刷全市场文件读取 | 改某股仍须读该周期整份21列文件，才能保留同文件其他股票。本次正式执行的全局读取审批须明确覆盖这项必要读取：范围仅为8只返回历史所定位的F个周期及相应Silver，禁止旁支全历史质量扫描或导出明细。审计时规范Raw总数为1,823+432=2,255份，压缩文件合302,385,873+73,153,535=375,539,408字节；在目录不变且缺文件拒绝的条件下，F不超过这2,255份，涉及Raw旧文件压缩总量不超过该总量。这是当前可复算范围，非实际IO、内存或固定额度。具体F及字节须源定位后据实记录；超出已确认范围或现行资源门禁则停止，不自动扩大范围 |
| 首次退市 | 周N=1,823、月N=432，正常定位加末次残留为2×(1,823+432)=4,510个文件的代码列统计参与量；每频采用集合SQL，不逐文件深查事件，也不读21列历史行情。当前F=0，因此无历史候选、替换或Silver任务。一次中断加一次完整重跑按两次实际N计，目录不变时最多9,020个文件的代码列统计参与量；不称9,020份独立文件或完整行情读取。计数查询仍须限定确认退市代码及本频 |
| 完整范围及最后验收 | 两笔Raw日更按`4F+2R`、独立回刷按`4F+3R`、Silver按`4F+2R`计业务记录，F/R取各步实际完整范围及频率数，原三项检查绑定实际物化，另计引擎和日志。无交付的退市每频仅1项结果检查，不套非零F公式。末次以完整实际交付范围做集合核验，不逐分区扫全史；Raw/Silver文件身份、21列、键、截至日及差异计数、结果名单/摘要、检查绑定和消费均计入成本 |

源定位前P/H/F尚不能确定，当前没有新正式流程的端到端耗时测量，不承诺完成分钟数；第13.10.5节真实源与列统计、候选实测及第13.19节隔离结果只作适用条件明确的参考。每步实际记录请求页/重试、源行数、文件范围与字节、候选与原检查、RSS采样/空间及耗时。中断重跑、旧失败运行仍占用的同设备staging、末次核验都单独计入，不抬高资源阈值来掩盖超限。8只源返回范围和F确定前，不把本节上界写成已发生的读取/写入。

#### 13.20.7 执行前审计与完成条件

本节切换前文档核对已经覆盖：Raw仅两个参数，Silver拒绝旧游标而非自动清空，两个成功事件sensor首tick初始化，原日补跑/源前移两条已有执行分支，原生引用及完整Silver范围，343候选零命中文件，旧已消费残留不重跑，以及整批新跑和最后验收成本。当时根文档完整性检查、新增4处链接及明确锚点、六条sensor清单、规模算式及差异空白检查均通过。继续复用第13.19节已经通过的475项与2项未启用实验的准确边界；切换前文档修改没有重跑生产Definitions、执行sensor或原检查，文档校验不计作正式链路验收。后来正式执行及收尾校验另见第13.21节。

正式执行获准后，只有下列结果同时成立才登记“切换完成”：

- 六条指定sensor最终状态和实际游标读回一致；Silver已从明确旧观察位置开始处理新原生交付，未跳过新范围；两条新sensor已真实处理首批相关成功事件，提交配置与worker当前合同一致。
- 原日仍可取得时，11月11日两频Raw及相应完整Silver按应有/可选代码、来源截至日和原检查验收；若源已前移，则如实记原日日更未交付、后来哪天的完整日更覆盖了当前周/月行情，不能写原日已成功。
- 11月11日股票复权因子变化8只的实际名单/摘要、两频历史完整交付、结果检查及适用Silver消费有真实成功证据；后来业务日的自动回刷不能替代这笔原日结果。343只确认退市分别有本频实际成功结果，零命中时文件替换及Silver请求均0。
- 每个实际改写的目标都能对应完整Raw交付、实际文件身份及绑定原检查；Silver按本次完整适用范围消费，失败范围未记成功。保留11月11日两笔旧失败运行、已完成旧运行和物理历史，不清库、不删旧JSON、不补虚构事件。
- 把实际正式操作、日期分支、运行ID、数量/字节/耗时、失败及完整新跑结果补回本节，并同步原方案和月线LLD。临时过程材料清理，不留下工程内临时文件。

**切换前结论（历史）：** 本节编写完成时尚未执行，须确认准确写入和相应全局读取范围，再按第3步探测原日源；现有定义已加载，不要求再次重启。后续获准执行的实际结果见第13.21节，不能继续用此处切换前状态描述当前正式状态。

<a id="stock-period-formal-cutover-results"></a>

### 13.21 正式切换执行记录（2026-11-12，已完成）

**授权与范围。** 管理员在第13.20节补齐后明确要求开始推进，本次据此执行该节的六条sensor交接、两份Silver游标转换、11月11日两频现有Raw job及其自动Silver/独立回刷/单频退市链。范围包含第13.20.6节已说明的必要读取：8只指定股票完整源历史所定位的既有周期全市场文件及相应Silver，只为保留其他股票并验收本次修改；不扩大为旁支全历史明细审计。首轮退市限现有343候选的代码列统计及零命中结果，若出现命中文件先停下核定。不得重启/重载DG、恢复旧实现、变更默认资源或操作其他链。

**执行入口。** 工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator`，仅用现有`.venv/bin/python3 -B`及现有本机GraphQL正式控制面。目标`DAGSTER_HOME`仍为`/Users/congming/.goldenshare/dagster_home`，不构造或初始化新instance。控制面操作以第13.20.3节已核对的mutation为准；过程脚本与操作日志仅在本任务`/private/tmp/dg-stock-period-cutover-9UUmKV`，原日Raw通过现有`DagsterGraphQLClient.submit_job_execution`提交第13.20.4节原配置与分区tag。正式Lake限`/Volumes/datasource/data_lake`四个现有资产；Raw既有暂存为`/Volumes/datasource/data_lake_staging/stock_period/runs/<实际运行ID>`，Silver为`/Volumes/datasource/data_lake_staging/stock_period_silver/run_id=<实际Silver运行ID>`。本节最初遗漏了Silver既有暂存路径，现已补正；实际使用既有代码规定的两处暂存，没有新增目录规则。失败按第13.20.5节完整新跑；临时操作程序不直接写Parquet、事件或数据库。

**执行前复核通过。** 已加载服务server ID和06:47加载时间未变，六个job参数schema与源码一致；103笔相关运行仍为70成功、31失败、2取消，未完成0。两个旧Raw观察位置之后均无其他观察，五笔关联Raw/Silver旧运行仍SUCCESS。当前四份文件身份与第13.20.2节一致、每份5,575行/唯一键，双向差异计数0。11月11日每频应有5,574、可选6；股票复权因子变化仍8只（`002152.SZ、002275.SZ、002864.SZ、300741.SZ、301300.SZ、301529.SZ、603279.SH、605338.SH`），确认退市候选仍343。准备按第13.20.3节顺序切换，源探测与正式运行结果待后续实录，不预写成功。

#### 13.21.1 实际交接、源探测和正式运行

按第13.20.3节暂停四条原sensor、等待原tick结束，只转换两条Silver游标，再恢复Silver并启用两条独立sensor。两条新sensor均已自然初始化原生成功事件游标，之后才提交新Raw；未preview或手造成功事件。Silver从周8020505、月8013873准确交接，没有清空为0或跳过新交付。九笔运行完成并核验后，两条Raw sensor恢复RUNNING；09:54:24最终读回六条均RUNNING。股票复权周线Silver游标为`schema_version=2,after=8035724`，股票复权月线Silver为`schema_version=2,after=8035725`，均无`pending`且返回`silver_no_completion`；两条Raw恢复后的自然tick均为“尚未到上海时间20:00”。正式code location加载时间及server ID未变，本任务未重启或重载DG。

原日源实际仍可取得，未进入源已前移分支。周/月三列各1页、5,575行、200,877字节，分别0.997/0.747秒（含现有预检处理）。请求单点和字段与第13.20.4节一致；应有5,574只均截至`20261111`，另1只可选停牌股票截至`20261109`，缺失、过旧、重复均0。因此按原日新配置分别手工提交两笔现有Raw job，其余七笔均由正式sensor自然接续，没有重复人工提交历史或Silver任务。

下表均为本次新运行，业务日期均为2026-11-11，时间及耗时来自正式运行存储（北京时间，秒数为开始至结束，不含任务开始前和后续tick等待）。全部SUCCESS，无任务级失败、取消或整批新跑：

| 正式job与用途 | 运行ID | 开始—结束 | 文件/检查及耗时 |
| --- | --- | --- | --- |
| `raw_stk_period_bar_adj_week_update_job`，股票复权周线Raw日更 | `31160508-b4dc-4588-b11c-bb9a0d6fb03c` | 09:40:54—09:40:56 | 1文件、3原检查；2.512秒 |
| `raw_stk_period_bar_adj_month_update_job`，股票复权月线Raw日更 | `12545136-b675-460d-ac35-286ef57e1870` | 09:40:59—09:41:01 | 1文件、3原检查；1.786秒 |
| `raw_stock_period_retirement_cleanup_job`，股票复权周线确认退市清理 | `822e28bc-4cd1-49c5-b3f1-4f36040e5c54` | 09:41:15—09:41:16 | 零命中，1结果检查；1.733秒 |
| `silver_stock_monthly_update_job`，股票复权月线Silver当期接续 | `09dbfefb-1b68-4601-b24c-b80a4c4bbeec` | 09:41:30—09:41:31 | 1文件、3原检查；0.795秒 |
| `raw_stock_period_history_repair_job`，8只股票两频复权因子变化历史回刷 | `75981629-9720-43bf-b565-81c0e13a2bfc` | 09:41:36—09:44:50 | 985周文件、232月文件，3,651原检查及2结果检查；194.628秒 |
| `raw_stock_period_retirement_cleanup_job`，股票复权月线确认退市清理 | `01a0305d-7596-4d75-9fe2-41f3ff18c9f8` | 09:44:53—09:44:54 | 零命中，1结果检查；0.633秒 |
| `silver_stock_weekly_update_job`，股票复权周线Silver当期接续 | `fe396849-c1b3-4a45-883e-3820d0d29061` | 09:44:58—09:44:59 | 1文件、3原检查；1.088秒 |
| `silver_stock_monthly_update_job`，股票复权月线Silver历史接续 | `6fa20aba-d565-4d0e-9ddf-a6ef5598e0db` | 09:45:44—09:46:07 | 155文件、465原检查；22.568秒 |
| `silver_stock_weekly_update_job`，股票复权周线Silver历史接续 | `3e220a30-a679-4ab3-a037-56817aa9e981` | 09:47:05—09:48:50 | 660文件、1,980原检查；104.495秒 |

Raw历史范围由8只股票的实际返回日期定位，不用旧JSON索引；股票名单摘要为`9ac5736bb8ade649ee2b3ce734eaad769eacdb2dba89f8dfbaf9de1f0c64dbc0`。两频回刷引用准确绑定本次两笔原日Raw。Silver历史范围逐项等于Raw交付中满足既有2014下限的范围，故985/232与660/155不同是既定历史边界，不是漏消费；四个Silver运行的写前/完成范围及其实际物化均完全一致。两频343只确认退市结果逐码等于现行确认名单，摘要均为`745c80c6423a7f4c70fb1813da4824a300afc9a29af67b17a25b7d803f2a7739`，文件命中、删除、替换及相关Silver请求均0，未伪造完成状态。

#### 13.21.2 最后只读验收及实际规模

九笔运行共2,036条物化、6,108项绑定原文件检查、4项独立结果检查和16条业务观察，合8,164条业务记录；6,112项检查全部通过。按本次明确运行集合批量读取，核对原检查的资产、分区、物化storage ID、运行ID和时间戳；完整Raw交付、两频回刷名单/摘要、Silver完整范围与源引用、两频退市实际名单和消费游标均已对账。相关运行由103增至112，成功70增至79，旧失败31及取消2保留，未完成0，不删除旧失败或去重记录。

对本次最新交付的2,032份唯一文件逐个stat核对`dev/inode/size/mtime_ns/ctime_ns`与物化一致，并核21列登记和绑定的原检查；不是重新逐分区执行检查或扫描全历史行情。物化共2,036条多出的4条来自当期日更后又被历史回刷覆盖的两份Raw、两份Silver，不当作额外唯一文件。各层最新交付的登记行数及实际压缩大小如下，行数包含同文件其他股票，不能称为8只股票的变化行数或独立K线数：

| 数据集 | 本次唯一文件数 | 物化登记行数合计 | 当前压缩字节 |
| --- | --- | --- | --- |
| 股票复权周线Raw `raw_tushare_stk_period_bar_adj_week` | 985 | 3,119,697 | 170,340,374 |
| 股票复权月线Raw `raw_tushare_stk_period_bar_adj_month` | 232 | 747,223 | 41,394,701 |
| 股票复权周线Silver `silver_stock_weekly` | 660 | 2,530,749 | 138,392,052 |
| 股票复权月线Silver `silver_stock_monthly` | 155 | 600,804 | 33,435,757 |

另实际读取当期周`2026-11-13`、月`2026-11`两层四份文件：每份21列顺序正确、5,575行及唯一业务键，NULL业务键0；5,574条截至11月11日，1条可选停牌记录截至11月9日。逐码核对应更新集合，缺失、过旧、重复均0；每频Raw/Silver完整21列双向差异计数均0。末次数据与交付验收实际2.492秒，后续恢复sensor再做状态读回，未重复全范围读取。11月11日日更与8只历史回刷均已办结，不能继续把第13.20节切换前的缺口当成当前事实；11月12日尚未到当日更新窗口。

#### 13.21.3 请求、空间、验收边界和收尾

正式两笔当期下载各1页，源及规范化均为5,575行，回包分别816,068/825,475字节；独立历史回刷16单元/16成功页，周3,834行、574,299字节，月912行、141,055字节，合4,746行、715,354字节。逐份成功响应与规范化CSV计数相符、21列相符、拒绝0；回刷按键合并到全市场文件，源行数不能与重写整份文件的登记行数相等比较。正式HTTP worker当期各1次、历史17次尝试取得16页，发生1次额外传输尝试，沿原重试规则完成，未另改超时/重试；本次未独立记录该次传输异常的具体原因，不把它归因为源股票缺失。两次三列预检独立列计，不与21列行数相加充当唯一行情数。

从首笔Raw开始至最后股票复权周线Silver成功共475.640秒，包含任务之间实际等待，不是九笔运行耗时之和。Raw共1,219次文件交付、Silver共817次，全部走现有job候选校验和原子替换；临时操作程序只提交及读取。默认RSS 4GiB、DuckDB 3GiB/2线程、spill 16GiB、workspace 32GiB均保持，未触发超限；没有记录正式进程连续峰值，不能据此承诺后续规模性能。末次本次三个非空Raw运行暂存合1,253文件、9,264,156字节，四笔Silver运行暂存末次无文件，两笔零命中清理无文件；全部本次执行暂存spill末次残留0，不声称执行中没有瞬时spill。保留正式作业自身合法源回包及分组暂存，不将其当作Codex临时过程文件删除。

本轮没有修改Python实现、配置默认值、数据集合同、分区定义或资源，没有安装依赖，没有Kopia、runless补事件、直接数据库写入或新建/升级instance；正式事件均由真实job执行产生。原方案与月线LLD同步本次结果。工程外操作脚本、日志及审计结果在有效事实落回原文档并校验后清理；旧`daily.json/baseline.json`、历史manifest、旧运行及其他任务材料不删除。当前正式切换及11月11日补数已完成，11月12日正常任务由恢复后的Raw sensor从20:00起检查真实源齐备条件，不提前提交或预写当日成功。

**收尾已完成。** 根文档完整性、本次三份原文档新增/修改的25处链接与明确锚点、正式数量算式及差异空白检查通过；没有用文档检查替代正式数据验收。收尾初稿把链接数量写成20处，是记录错误，现已按实际检查输出更正。本任务`/private/tmp/dg-stock-period-cutover-9UUmKV`及其中操作脚本、日志、源计数和临时验收结果已删除，工程内未生成临时文件，正式运行staging和既有材料未清理。修改仅落回原方案及两份LLD，随本次获准的文档提交保存，提交号以Git记录为准。

#### 13.21.4 管理员重启后核验与剩余验收（2026-11-12）

管理员告知已自行重启DG。10:09:36只读核对：Dagster仍为1.13.26，`orchestrator`已于10:08:15重新加载，server ID为`87d3a432-ab60-4155-9d13-9b96e1355a81`。六条sensor均RUNNING，最近tick无错误；两条Raw按20:00前规则跳过，两条Silver仍分别为`schema_version=2,after=8035724/8035725`、无pending，两个独立sensor保留原生成功事件游标并正常检查。本次仅GraphQL query，没有再次重启、重载、启停sensor或提交任务。

10:09时，本需求六阶段开发、正式切换和11月11日日更/历史回刷均已完成，无需继续开发或重复补跑；当时尚待11月12日20:00起首个自然日更窗口的实际验收：确认两频sensor在源端应有代码齐备后自动提交当日Raw，两频原检查、同频完整Silver、按当日股票复权因子变化触发的独立回刷，以及各频确认退市结果均正常接续。源未齐时继续等待符合既定规则，不能提前记成功；本次11月11日的正式补跑不替代自然调度验收。不新增自动任务、验收门槛或其他数据集审计范围。晚间实际验收结果见下节，上午的待验收状态不再作为当前结论。

<a id="stock-period-first-natural-daily-acceptance"></a>

#### 13.21.5 11月12日首轮自然日更验收（21:07，只读）

管理员21点要求查看任务。本次只读正式GraphQL、只读PostgreSQL连接及当前周期四份文件，没有执行sensor、check或job，没有补跑、修改DG状态、重新请求Tushare或读取历史全市场行情明细。自然运行由既有daemon完成，每笔均保留对应sensor标签，配置业务日期均为2026-11-12。

两频Raw sensor在20:00后分别确认当日5,573只应有码全部齐备，可选全日停牌7只、源返回2只；缺码、过旧、重复均0。月线20:00:23创建，周线20:00:58创建，均使用新配置自然提交。九笔运行全部SUCCESS，最后股票复权周线Silver历史接续于20:28:02完成：

| 正式job及用途 | 运行ID | 成功时间（北京时间） |
| --- | --- | --- |
| `raw_stk_period_bar_adj_month_update_job`，股票复权月线Raw日更 | `12b46890-9033-46a6-8510-72cfce324279` | 20:00:28 |
| `raw_stk_period_bar_adj_week_update_job`，股票复权周线Raw日更 | `d98ee00a-3ad8-4500-8e0f-af8665103869` | 20:01:53 |
| `raw_stock_period_retirement_cleanup_job`，股票复权月线确认退市清理 | `47fdd883-2dfa-4f5b-bb88-243a6524a16e` | 20:01:58 |
| `silver_stock_monthly_update_job`，股票复权月线Silver当期接续 | `744d1702-c73f-4765-832c-816159f53bcb` | 20:02:04 |
| `raw_stock_period_retirement_cleanup_job`，股票复权周线确认退市清理 | `6bd73ba5-7fd9-4f10-91ee-3279ce234f06` | 20:17:08 |
| `silver_stock_weekly_update_job`，股票复权周线Silver当期接续 | `45f85adf-905a-4983-a8d7-ae034b00696b` | 20:17:14 |
| `raw_stock_period_history_repair_job`，股票复权因子变化两频历史回刷 | `3563da83-d396-47b6-90e5-138463c96ee0` | 20:19:28 |
| `silver_stock_monthly_update_job`，股票复权月线Silver历史接续 | `17c9580f-a868-43f5-a414-94db86abb54b` | 20:26:09 |
| `silver_stock_weekly_update_job`，股票复权周线Silver历史接续 | `4e4c97d4-9826-4ba9-94b4-bc0c838a7491` | 20:28:02 |

当日复权因子变化6只：`301099.SZ、301282.SZ、301559.SZ、301608.SZ、603998.SH、688777.SH`。两频Raw日更成功后才自动提交独立回刷，实际交付596份股票复权周线Raw、141份股票复权月线Raw；均在既有Silver历史下限内，两频Silver完整接续相同596/141文件范围，写前/完成范围、源引用及名单摘要核对一致。确认退市两个运行均为零新增候选、零命中文件，累计已清理343只及其摘要正确保留，没有再扫行情或触发额外Silver。

本次1,478条物化对应4,434项原文件检查，另4项回刷/退市结果检查，合4,438项全部通过；原文件检查逐项绑定真实物化ID、运行和时间戳。对最新交付的1,474份唯一文件核对实际文件身份与21列登记，均与对应物化一致；不把同日当期文件后续被回刷再次交付计作额外唯一文件，也没有逐历史分区重跑检查。

实际读回当期周`2026-11-13`、月`2026-11`的Raw/Silver四份文件：每份5,575行/唯一键、21列顺序正确、NULL业务键0；5,573只应有股票均截至`20261112`，另2条可选停牌记录分别截至11月9日和11月11日。按已验收的当日生命周期与最终停复牌事实逐码核对，缺失、过旧、重复均0，两频Raw/Silver完整21列双向差异计数均0。

21:07最终六条sensor均RUNNING、最近tick无错误；两条Silver分别推进到`after=8050037/8050038`，无pending且返回`silver_no_completion`。只读原检查、完整范围、实际文件身份和四份当期文件的验收共2.571秒，不包含此前GraphQL状态读取，不外推正式吞吐。有效结果写回原方案及两份LLD，本任务工程外临时审计脚本及结果收尾清理，未在工程内创建临时文件。本需求此前唯一剩余的首次自然日更验收已通过，无本链未完成运行、未消费交付或需人工补跑事项；该结论不扩大为其他DG数据集的完整性审计。

**结项结论（2026-11-12）。** 股票复权周线、月线改造的六阶段开发和隔离验收、旧代码清退、正式切换、11月11日补数及11月12日首次自然日更验收均已完成。原方案与两份LLD已对齐，临时审计文件已清理，最后验收记录随本次文档提交保存。本需求已完成并结项，无遗留开发、补数或验收事项。
