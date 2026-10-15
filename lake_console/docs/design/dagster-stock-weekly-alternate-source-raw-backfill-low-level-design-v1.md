# DG 周线保留链与重复数据集物理清退 LLD v1

更新：2026-10-15。管理员已批准精简计划；源码清退和隔离测试已完成，正式重载及物理删除尚未执行，原因见第6节。删除不审查行情、不重算、不以Raw修订为前置。范围和阶段唯一引用[周/月总方案](dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md)，月线修订细节见[月线LLD](dagster-stock-monthly-raw-onboarding-low-level-design-v1.md)。

第1—3节记录继续保留的日常供数合同及预算，不是第一条删除任务的执行或重验清单。删除只执行第4节步骤和第6节针对性验收；月线数据修订另属第二条。

<a id="adjusted-weekly-prod-refresh-lld"></a>
## 1. 保留链的当前合同

| 项 | 当前实现/保留决定 |
| --- | --- |
| asset/job | raw_tushare_stk_period_bar_adj_week / raw_stk_period_bar_adj_week_update_job |
| 来源 | Tushare→Prod；DG首次读固定B0 Raw，日常只读core.stock_weekly_adj_delivery的闭合批 |
| Parquet | /Volumes/datasource/data_lake/raw/tushare/stk_period_bar_adj_week/week_end=YYYY-MM-DD/part-000.parquet |
| 业务键/分区 | (ts_code,trade_date,freq)，freq=week；cn_a_stock_week_ends自然周五坐标 |
| 检查 | 原file_contract、key_partition、delivery_reconciliation三个blocking check及准确物化绑定 |
| Run Config | StockWeeklyAdjProdConfig(contract_version=1,delivery_batch_id,closure_revision)；不接受code_list_path/automatic_intent_date等旧直拉参数 |
| 幂等 | intent由合同版本/批ID/revision/资产决定，不用run_id或event storage id |
| staging | /Volumes/datasource/data_lake_staging/stock_weekly_adj_delivery/{intent_id}；仅本次未完成意图使用 |

Raw原21列顺序：ts_code,trade_date,end_date,freq,open,high,low,close,pre_close,open_qfq,high_qfq,low_qfq,close_qfq,open_hfq,high_hfq,low_hfq,close_hfq,vol,amount,change,pct_chg。
日期/代码/freq为VARCHAR；价格、change及qfq/hfq为DECIMAL(18,4)，vol/amount为DECIMAL(20,4)，pct_chg为DECIMAL(10,4)。保留NULL、原始代码和源单位；不混入采集字段、交接信息或规范化身份字段。源字段事实见[Prod源字段合同](../../../docs/datasets/stock-weekly-adj-refresh-low-level-design-v1.md#source-field-contract)。

时间输入是周意图，执行unit是闭合批中的源unit及逐文件提交，freshness是周期覆盖与准确检查；revision仅为消费坐标，三者不混同。源end_date是计算版本，可晚于所属周。DG不能用本地计算价替换源qfq/hfq。

## 2. 闭合批读取、候选与恢复

1. next_closed_batch按revision升序取一条，不用MAX跳过中间批。sensor只读头及有界任务状态，不取payload、不扫历史Parquet。
2. job用规定的psql包装和短READ ONLY事务逐unit读显式业务列及摘要；只读属于该闭合批的冻结payload，不拿当前可变Raw冒充旧批。
3. 校验合同、单位集合、scope、行数、字节、摘要、freq、日期与唯一键。Decimal字符串严格转换，NULL保留；JSON使用严格typed转换/unnest，不做放大文档的相关json_each连接。
4. 跨unit同键仅point_week与stock_history合法重叠可按已提交unit revision取新值；其他冲突拒绝，不按文件遍历顺序last-wins。
5. 按年份一次处理本批全部股票，candidate=existing中未被输入选中的行 UNION ALL incoming完整21列。输入键和值完整对账，未选键值不变，无变化文件不替换。
6. 当前年度候选校验通过后逐文件fsync、同卷os.replace、读回、checkpoint；关闭该年连接后处理下一年，不逐股票重复扫全年。
7. replace后checkpoint前退出，目标等于候选则补完成；目标既非原件也非候选则拒绝覆盖。取消不领新文件，已提交文件保留。
8. 文件完成而事件失败，只补缺失且准确绑定的事件，不回滚业务文件、不重复下载。历史周和anchor均登记真实物化/check；anchor是本批实际输入最大周，不是当前周。空行合法闭合批只推进水位，不造文件或绿色事件。

交接表唯一合同见[Prod delivery-contract](../../../docs/datasets/stock-weekly-adj-refresh-low-level-design-v1.md#delivery-contract)。DG不写Prod ack表，不新增永久summary asset，不把本次hash当永久历史证明。

## 3. 配置审计与成本

现有值是实现基线，不是本轮新增限制。来源均为StockWeeklyAdjProdConfig、WeeklyAdjProdDeliveryBudget、WeeklyBudget及现有连接设置；本次意图固化有效值，恢复不得静默改变。源模式/字段由代码唯一注册，无新env或数据库开关。

| 配置 | 当前值/消费者/门禁 |
| --- | --- |
| unit/payload | 最多1,000unit；每unit12,000行/8MiB；整批256MiB，reader/合同及捕获消费，超量在写入前拒绝 |
| 控制文件 | plan1MiB、头投影4KiB、closure256KiB；sensor不搬完整清单 |
| 读取 | 现有包装脚本；SQL30秒、unit45秒、连接1；超时可取消，不泄露凭证 |
| DuckDB | 512MiB、2线程、spill2GiB；年度独立连接，RSS上限1GiB，不把引擎buffer当RSS |
| 合并 | 日常年度500,000行、54目标、源/候选≤128文件；运行≤1,000目标、staging4GiB |
| bootstrap例外 | 历史B0年度上限1,000,000行仅限已批准首次替换，不扩为日常默认 |
| 调度 | 上海19:30、既有sensor；cursor保存adjusted_delivery_revision/pending_adjusted，新代码加载不清水位 |

新修订/Silver若超现有局部预算，先做代表性样本并记录读取量、输出量、RSS、spill及恢复成本后重评，不能逐股票拆绕门禁，也不擅加更紧上限。本轮没有新性能通过结论。

## 4. 物理清退执行协议

### 4.1 数据白名单

仅以下三个数据集根及其已核实内容进入删除清单：

| 待删根 | 2026-10-15数据文件/字节 |
| --- | --- |
| /Volumes/datasource/data_lake/raw/tushare/stk_period_bar_week | 859 / 89,782,798 |
| /Volumes/datasource/data_lake/raw/tushare/stk_period_bar_month | 201 / 22,484,192 |
| /Volumes/datasource/data_lake/raw/tushare/weekly | 803 / 6,950,886 |

清退写入口后，删除前一次确认三个根精确匹配、挂载正确、无symlink/越界及相关活动写者，再枚举目录清单，按清单删除文件和已空目录。只读目录元数据，不打开Parquet、不查行数/schema/价格/完整性、不计算文件hash。表中库存只作参考；正常新增的本数据集文件纳入当次清单，数量变化不自动阻断，未知归属和路径异常才停止。不跟随符号链接，不删除未核实staging意图或其他任务文件。

保留两个复权根、全部共享父目录、月线复权staging、日线/分钟/因子/身份/日历、共享动态分区、25股候选和日志。Dagster历史event/run记录不删。删除不等待保留Raw修订或数值验收；已有覆盖结论复用，不重扫保留文件或日线。没有源请求、DuckDB计算、候选、COPY、原子提升、事件补录、备份或专用checkpoint；只记录实际删除结果，中断后确认目录边界和无写者，继续处理剩余内容。

### 4.2 定义、入口和sensor

| 文件/能力 | 要做的变更 | 必须保留 |
| --- | --- | --- |
| assets/stock_weekly.py、assets/stock_monthly.py | 移除两个独立未复权主源及备用weekly的活动定义/直拉入口 | 两个复权资产及现有key/路径 |
| jobs/stock_weekly.py、jobs/stock_monthly.py | 删除raw_stk_period_bar_week_update_job、raw_stk_period_bar_month_update_job、raw_tushare_weekly_update_job | 两复权job及仍需的B0检查补录job |
| checks/stock_weekly_checks.py、checks/stock_monthly_checks.py | 删除三个退役资产的9项checks | 两复权资产6项检查与准确绑定 |
| 两个raw_stock_*_update_job_sensor.py | 删除旧源分支、旧job列表/双源等待/无效互锁 | 共享sensor、19:30窗口、周revision/pending、月frontier及真实取消恢复 |
| stock_weekly_update*.py、stock_monthly_update*.py | 将active对象与ready判定收敛为保留源，迁移全部调用方 | monthly仍使用的weekly_event_binding等共享函数 |
| catalog/lake_assets.py、catalog/name_mapping.py | 清零退役active登记，校准保留中文说明 | Prod/其他DG注册及保留资产来源合同 |
| run_contracts、paths、schema、configs、partitions | 按全引用审计删除无消费者定义，不留旧新写入合同 | 共享schema/日期函数及cn_a_stock_week_ends/cn_a_stock_months |
| 历史CLI/capture/promote/events/prod_db | 移除退役source的新写入入口、参数选择及仅其使用的实现 | 仍被复权交付、月线修订和必要检查使用的公共能力 |

两个sensor都承载保留分支，不能删除整个文件或调用stop_sensor。源码部署后重载定义，按批准的迁移校验cursor；本方案不要求启停sensor/服务。独立未复权专用sensor若执行预检另有发现，核实唯一归属后才加入精确清单，不按关键词批量清理。

### 4.3 实施顺序

1. 清退第4.2节的旧定义、调度分支和所有新写入入口，保留公共能力；不同时开发月线覆盖或新码修订。
2. 按真实改动运行定义、sensor、旧参数拒绝和共享函数的隔离测试；删除边界只用临时目录验证，不请求源、不跑历史生成链。
3. 部署并重载代码定义，只读确认三个退役asset/job及9项check不再active、两个保留sensor仍有复权分支且原状态/水位未重置；不提交正式job、不评价或启停正式sensor。
4. 确认没有相关job和手动CLI写者，按第4.1节一次核对目录并物理删除；若仍有写者，等其退出后再执行，不影响其他任务和服务。
5. 一次收尾确认旧目录和活动入口消失，保留根及共享对象未被误删，记录结果；不对行情内容或全湖文件重新对账。

第一条可独立关闭，第二条Raw修订随后推进。仅隐藏UI或删源码不算物理删除完成，仅删文件却留写入口也不算完成；不清空Dagster数据库或全局staging。

## 5. 消费者和改动范围

CodeGraph explore/callers/impact已覆盖入口、路径与StockWeeklySource/StockMonthlySource，分别影响99/44个符号；动态枚举分发另用当前源码搜索、60个相关DG模块AST引用及实例只读查询补足，不以图结果替代SQL/运行事实。

活动定义、jobs/checks/sensors、period_status、schema/catalog/config/path、历史bootstrap/CLI、事件登记和Prod只读适配器均是消费者。definitions.py使用load_from_defs_folder，遗留@asset仍会加载，所以不能只从job或catalog移除。没有发现Wealth/QTF或业务API直接读取这些DG周期Raw；Prod同名Definition/模型、周线进度页及供数协议不是DG退役对象。

复用已有引用审计，实施时只补核实际改动的符号和直接消费者，不重新审计全仓。最小回归以周/月definitions、两个sensor及改到的contract/catalog治理检查为主；原测试中期待旧对象存在的断言须同步移除或改成拒绝旧入口。仅当修改共享capture/delivery等行为时，增加相应直接消费者测试；不默认重跑inventory/planner/capture/candidates/events、bootstrap或整套历史链。月线仍使用的绑定函数及复权B0恢复能力必须保留，不能按文件名整块删除。

## 6. 正反验收

| 必要检查 | 正向 | 反向 |
| --- | --- | --- |
| 旧入口清退 | 三个旧asset/job、9项check及catalog活动项消失；sensor不再等待旧源 | 旧source/CLI参数不能重新生成退役数据，不留fallback |
| 共享能力保留 | 两复权定义/check/job、月线共享函数、分区及两个sensor保留；周revision/pending和月frontier沿用 | 误删公共函数、残留旧job引用或重置水位时，针对性定义/调用测试失败 |
| 删除路径边界 | 临时目录内三个允许根可删除；正常新增文件纳入清单 | 错误根、越界、符号链接、未知归属和活动写者拒绝；保留根及共享父目录不删 |
| 一次关闭 | 旧目录及活动入口已消失，保留对象仍在 | 残留旧目录、写入口或缺失保留对象不能报清退完成 |

删除不验行情行数、schema、价格、上市覆盖、源/Prod/DG数值或公式；不扫描全部保留Parquet算hash。新码、完整月份、源分页、候选读回及COPY/replace取消恢复属于第二条修订或保留链自身的测试，不列入第一条默认验收。

### 6.1 本次实现与实际验证（2026-10-15）

- 三个旧asset/job、9项check、catalog/path/schema/config活动项已从源码移除；旧source不再属于周/月枚举，旧周线point/update执行器和备用采集/规划入口已删除，旧库存/计划在创建目标或请求源前拒绝。两个复权key及21字段不变。
- 两个共享sensor保留名称、默认状态、19:30窗口和水位字段。周线只消费原闭合批feed，不再查未复权日历/文件；月线只遍历复权源。月线依赖的请求监督、事件绑定及复权bootstrap能力保留。CodeGraph impact复核周/月99/44个符号，动态消费者用现有引用补核，无业务子系统依赖变化。
- 最终针对性隔离验收214项通过、509子测试通过，9.33秒；未重跑历史全链。删除脚本只置于/private/tmp，固定三个根，5项临时目录边界/正常新增/部分删除续处理测试通过，0.006秒；未对正式目录运行预览或apply。
- 另补核直接迁移的月线事件/历史合同和保留周线候选、事件文件、旧事件scope拒绝：53项通过，4项旧双源夹具预期修正后复测通过；不与上述214项重复累加。退役未复权point/bootstrap成功路径的测试随对应实现退出，保留原复权B0替换/检查专项测试；没有将旧source改成复权而继续使用旧写入语义。
- 11项未纳入最终测试：9项额外真实子进程时序测试不是本次共享监督逻辑变更；另外2项全局治理测试分别要求停牌专项隔离上下文，以及既有矩阵漏登记。后一问题用修改前HEAD源码内存加载复现17项缺口；本次删掉未复权月登记后剩16项，包括原有复权月/公告/资金流缺项。未放宽或修改这些门禁，不把全局治理说成全部通过。
- 正式只读GraphQL确认orchestrator仍加载本工作区orchestrator.definitions，列出原五项周期Raw。隔离调用同一defs入口确认递归导入当前未验收R3 execution模块；按批准边界停在重载前。未重启、未评价/启停sensor、未提交job或写事件，三个正式目录未删。
- 日志位于/private/tmp/dg_period_retirement_fixed_version_20261015.log；正式加载快照为dg_period_retirement_loaded_location_20261015.json；基线复现脚本为dg_retirement_governance_baseline_20261015.py；一次性删除脚本为dg_period_retirement_delete_20261015.py。临时脚本不纳入生产主链，不依赖它们作为日常证明。原R3候选、receipt、checkpoint、计划/hash和未提交代码均保留。

下一步仅为解决同一code location的未验收改动加载边界，然后继续第4.3节步骤3—5；不因源码提交宣布第一条已关闭，也不进入Raw修订、Silver或25股修复。

## 7. 后续Silver接口边界（未实施）

拟新增silver_stock_weekly，依赖唯一保留周Raw，路径拟为silver/quote/stock_weekly/week_end=YYYY-MM-DD/part-000.parquet；月线对应规则见月线LLD。标准化日期、保留Decimal和三套OHLC；初次覆盖本轮批准的仍上市集合，不自行删除退市历史。

confirmed身份只用于归一，不改变Raw。已有新码的请求只用新码；Raw旧码不是自动兜底。若同证券同周多行，必须证明新码和计算版本关系后选定整行；同优先级/身份未确认/新码缺失的冲突不得任意去重或拼字段。保留可追溯的输入归属，但不新增永久版本库。

一次Prod闭合批会改多个历史周，Silver必须从本批准确物化/实际变更集合领取所有受影响周，不能仅用run-status的anchor。先确认触发/取消/幂等合同再开发；首次历史候选、物理生成、事件和日常增量分别验收，不默认全历史重算或重复深扫。

## 8. 历史事实与旧引用

<a id="adjusted-weekly-bootstrap-capture"></a>
<a id="adjusted-weekly-bootstrap-replacement"></a>
<a id="adjusted-weekly-formal-preflight-20261012"></a>
<a id="adjusted-weekly-bootstrap-execution-20261013"></a>
<a id="adjusted-weekly-bootstrap-event-replacement-20261013"></a>
### 8.1 已完成的B0交付

2026-10-13 Prod首批15565完成876周/3,028,907行；独立补刷15604完成9股/6,345行，B0=1785。DG859文件/3,028,907行、859新物化/2,577准确检查、27成功run，最终缺项/blocked/最新失败0，水位已迁移。原年度捕获、覆盖、事件及水位迁移阶段已结束，不重开旧执行卡。保留的raw_stk_period_bar_adj_week_event_backfill_job仅手动补检查，每批最多33周/99项，绑定已验收B0冻结计划及新物化，不生成行情、不接自动sensor。

<a id="adjusted-weekly-d1-d2-implementation"></a>
<a id="adjusted-weekly-d2-sql-memory"></a>
### 8.2 有用的实现经验

真实payload JSON相关连接曾放大内存，改typed转换/unnest；年度各独立连接并复用关系，避免按股反复读年。历史单股样本含取消/恢复和21字段对账，不能替代本轮清退或Silver验收。首次bootstrap固定B0捕获、检查全部业务revision稳定，按键覆盖保留DG独有键；这些能力保留用于受控恢复，不再复制成日常历史证明。

<a id="weekly-factor-repair-alignment-20261012"></a>
复权Raw供数和DG自主QFQ/指标修复是两条链；25股修复暂停后置，不作为本轮物理清退或周线供数已完成的替代证据。

<a id="34-m9-更新机制每日1930与备用仅手动2026-10-04"></a>
<a id="后续真实验收执行卡2026-10-06准备完成"></a>
原两主源串行、备用仅手动及旧启用执行卡已被本轮单主源/物理清退决定替代。日期报告仅作历史证据，不作为当前命令。必要旧事实见[2026-10-09记录](../../../reports/stock_period_raw_closeout_20261006.md)。
