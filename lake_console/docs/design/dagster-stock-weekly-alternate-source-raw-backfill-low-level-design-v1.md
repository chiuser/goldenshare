# DG 周线保留链与重复数据集物理清退 LLD v1

更新：2026-10-15。目标已由管理员确认；本轮仅文档，代码与正式数据尚未清退。范围和阶段唯一引用[周/月总方案](dagster-stock-weekly-alternate-source-raw-backfill-plan-v1.md)，月线修订细节见[月线LLD](dagster-stock-monthly-raw-onboarding-low-level-design-v1.md)。

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

执行前一次枚举完整相对路径、类型、大小和必要身份；校验根精确相等、无symlink/越界/挂载变化、无活动writer和新增文件。实际清单单独审阅，不把表中目录表达式直接变成rm -rf；先逐白名单文件删除，再删已空子目录及这三个根。未知文件、未核实staging意图和其他任务文件不删除。

保留两个复权根、全部共享父目录、月线复权staging、日线/分钟/因子/身份/日历、共享动态分区、25股候选和日志。Dagster历史event/run记录不删。删除本身不触发重下载、materialize或备份。清退验收先确认保留源覆盖与修订通过，再实施不可撤销的删除；失败时保留剩余白名单和已删记录，不“回滚”到备份或扩大清理。

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

修订范围和保留源验收→清退代码/隔离回归→部署重载及在途writer核实→按白名单物理删除→一次范围/剩余入口/保留文件对账。仅删除源码或隐藏UI不算清退完成；仅删除文件但留写入口也不算完成。禁止清空Dagster数据库或全局staging。

## 5. 消费者和改动范围

CodeGraph explore/callers/impact已覆盖入口、路径与StockWeeklySource/StockMonthlySource，分别影响99/44个符号；动态枚举分发另用当前源码搜索、60个相关DG模块AST引用及实例只读查询补足，不以图结果替代SQL/运行事实。

活动定义、jobs/checks/sensors、period_status、schema/catalog/config/path、历史bootstrap/CLI、事件登记和Prod只读适配器均是消费者。definitions.py使用load_from_defs_folder，遗留@asset仍会加载，所以不能只从job或catalog移除。没有发现Wealth/QTF或业务API直接读取这些DG周期Raw；Prod同名Definition/模型、周线进度页及供数协议不是DG退役对象。

既有回归至少覆盖test_stock_weekly_contract/definitions/update、test_raw_stock_weekly_update_job_sensor、test_stock_period_checks、inventory/planner/capture/candidates/events、复权delivery/bootstrap replacement、asset_governance和incremental_governance。月线回归见其LLD。删除公共实现前要以全引用和实际剩余用途为准，不能删除仍在使用的月线绑定函数或复权B0恢复工具。

## 6. 正反验收

- 保留源上市键不丢，三套OHLC合同/精度保持，异常修订的源/Prod/DG一致，其他月份/资产指纹不变；退市数据缺口不补。
- 三个退役资产/job及9项check不再active，sensor不再等待旧源；旧CLI不能新写回已删除目录，不能遗留兼容双轨或自动fallback。
- 删除精确白名单全部完成；保留根和共享父目录完整；symlink、新增文件、活动writer、未知归属均拒绝删除。
- 保留周线闭合批按顺序推进，合法空批不造事件，历史修正和anchor都准确物化；旧revision/pending不因清退丢失。
- 取消/TERM/退出发生在COPY、replace或checkpoint前后，已提交保留，可读回续跑；观测失败不回滚业务。
- 不把物理存在、行数、cursor或旧check当成当前数据已正确。公式金样本与运行真实输入/持久化检查分工，一次收尾后不永久扫描全历史。

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
