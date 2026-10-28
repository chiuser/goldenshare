# 周/月链路正式恢复记录（2026-10-28）

**最终结果（2026-10-28 11:50）：本轮27日股票复权周/月Raw和Silver四项已全部补齐并确认。** Raw不同2170文件（提交2171次），Silver不同812周期/3115094行；三个通知全部消费，pending0、因子和两频刷新27日、四sensor RUNNING。最终依据[rss8-final-verified.json](rss8-final-verified.json)，11:31库存是收尾前快照。月恢复窗口通过现有原job完成，恢复待执行时的sensor确认时机/提示另留TODO。本轮修改及证据随本次提交保存，未推送。

管理员要求按原LLD及“新代码生效→旧回执收尾→实际补数→Silver验收”顺序推进。本文件记录实际执行，不替代原方案或LLD；实施依据为共享LLD§12.11—12.12、§12.16.10。

## 执行前范围与状态

当前dev-interface已包含005f21f53；该提交的528通过/2项PG未启用保留为原开发证据。当前四个目标job为raw_stk_period_bar_adj_week_update_job、raw_stk_period_bar_adj_month_update_job、silver_stock_weekly_update_job、silver_stock_monthly_update_job。只处理本链，不重置cursor，不重建bootstrap，不做全局数据审计。

正式执行前补核发现completed_receipt的路径比较会通过safe_path对未选/后继整批路径lstat，违反原第4/5项读取边界；先补原三文档和独立审查，再做两源文件的最小修正及隔离反例，详见共享LLD§12.16.10。尚未据旧528通过宣称本遗漏已验收。

09:09上海时间，只读访问指定控制JSON、本链运行/sensor元数据及一个周目标属性：

- 本机DG进程未运行、3000端口无监听；原启动入口check-only证明PG、CH及既有Prod CH隧道查询就绪，未启动或修改服务。
- 本链四sensor持久状态均RUNNING；四job无在途，writer锁空闲。
- 旧执行db67897f…9157e8仍files_complete，唯一pending、consumed=true、asof=2026-10-20；原文件CP缺失、completion CP存在。
- 当前周文件版本等于51c154…ca5ad3的committed.version，其target_preimage等于旧complete.version；没有访问其他行情文件内容。
- 控制JSON共读5,708,455字节，baseline占3,878,591字节；旧阶段预算依此校准，见LLD§12.11。PG通过独立连接强制只读事务，未初始化Dagster实例、未写数据库。
- 27日原周失败run仍319ec97d-cfd4-4ef7-bc4a-c98c7334464a，配置日期2026-10-27、周分区2026-10-30；原月失败run为8c9e09c4-9a82-4042-b696-0ffc3a17999d，配置日期2026-10-27、月分区2026-10。

## 后续顺序与边界

先完成路径遗漏修正和必要隔离验收；复用原events命令收尾旧20，不先启动daemon，不新发业务物化/check/通知，不读写行情。正式命令/根/实例/中断规则沿LLD§12.11，无手工改JSON脚本。

旧回执收尾通过后，用必要有界核验/计数、stat和已有证据确定实际欠账、源请求、因子/上市变化及历史读写预算；名单仍由原job产生。范围和预算明确批准前，不启动会读写历史行情的原27日任务。随后确认正式代码位置使用已验版本，沿原生FROM_FAILURE恢复周/月失败任务，再由原通知推进对应Silver全部变化周期，仅按本次交付清单验收。

实际命令、结果、清理及最终状态在步骤完成后回写，不预填通过。上文为执行前记录；正式旧20步骤的实际结果见下节。

## 路径修正验收与旧20执行前最后核对

路径修正新21例、原相关91例通过，开发后独立只读复核通过；两源码和测试SHA与结果文件相同，实际读写守卫保留。原2条失败以gzip无损留证，指定basetemp已清理，未重复528项全组。当前使用005f21f53加本次两源码修正，精确SHA见receipt-path-results.json；未将其他工作区改动作为本轮部署内容。

旧20原Mat7684828/通知7684826及现Mat7705014已通过只读PG核对，原三检查实际事件7684832/36/40、现三检查7705015/16/17均SUCCEEDED/passed/blocking且正确绑定。共享生产SQL用于选择真实最新结果，没有预筛成功。详见formal-event-evidence.json。

下一动作严格使用LLD§12.11原events命令，解释器为orchestrator/.venv/bin/python3 -B，DAGSTER_HOME固定正式现有实例，根为正式Lake/staging，原执行ID不变。范围仅旧缺失文件CP、manifest.phase及精确pending收尾，允许产生一个控制报告run/日志；不新发业务物化/check/通知，不下载或读写行情，失败停止不自动重跑。执行前后只读指定控制记录和目标版本，baseline用未变版本复用既有摘要。

## 旧20原events正式执行：成功

按LLD§12.11完整原命令执行一次，退出0，输出原执行ID、files=1、events_reported=true。控制报告run **0b36ac11-c60d-4dc5-8dc7-a27d23666819** 为SUCCESS；stdout/stderr保存在old20-events.out/old20-events.err。09:33只读验收全部通过，见[old20-verified.json](old20-verified.json)：

- phase由files_complete变events_complete；补成events/week/2026-10-23.json，内容精确等于原version/sha256。
- manifest除预期phase外全部一致；daily仅删除原已消费pending，pending数从1到0，其余水位/键完全一致。
- 原complete、原completion CP及baseline文件版本不变；唯一当前周Parquet的五字段版本不变，baseline复用原已核摘要，没有重读后继全清单或其他行情。
- 控制run新增业务Mat/observation/check（含planned）为0；27日319原run保持FAILURE，未伪造旧run状态。
- 四sensor持久开关和cursor完全不变；DG仍未启动。旧20阶段行情内容读取、行情写入均0；正式控制回执/phase/pending及控制报告run已按授权写入。

## 27日补数前的必要范围核定

已完成两次tushareMCP单股有界样本，周标签20261030和月标签20261031的end_date均20261027，未触及跨日日期冲突；只取四个身份/日期字段，未扩读价格/历史，见[source-asof-samples.json](source-asof-samples.json)。单股样本不代替正式全部输入检查。

随后仅有界SSE窗口、COUNT当前L/CNY和文件stat：当前上市5577、baseline上市5576；21→22、22→23、23→26、26→27四组相邻日，五因子文件全部存在。未读取因子明细，未计算变更股票。参考文件与8次因子投影的整文件大小基数1,058,375字节（约1.01MiB）；精确路径/版本及元数据库存见[reference-scope-stat.json](reference-scope-stat.json)。其中Raw库存1820周/431月、登记大小298272360/72658415字节只是已存登记事实，不是本次全文件物理核验或全频读取批准。

已将最小参考/因子读取方案与预算落原LLD§12.12.1，并单独申请：读取当前basic/identity必要列、SSE日历两列、21/22/23/26/27因子两列，复用原函数形成预算证据；正常读≤8MiB，含一次明确必要续读及收尾≤16MiB，临时写≤2MiB、额外空间≤64MiB。实际正式job仍由原配置和函数生成股票名单，不手填stock_codes；正式历史读取及源请求范围在拿到真实集合后另核。

上段为申请当时状态；该具体投影已获本次批准，实际结果见下节。原27日周/月job、Silver、DG启动尚未执行；没有把旧回执收尾当成实际数据补齐，没有读取多年行情来估预算，也没有重跑全局数据审计。

## 最小参考/因子预核授权

管理员已明确回复“批准”，本阶段按原LLD§12.12.1读取当前basic/identity、SSE日历及21/22/23/26/27因子必要列；条件有界核对退市。仅为预算复用原函数，不写正式资源、不触发数据job。执行前后核源版本，失败/变化停止，不自动重读。真正27日历史补数仍待本阶段实际范围及预算明确后另批。

## 获准最小预核结果（10:03）

原helper执行一次、1.72秒，79因子变化+2新增=81历史刷新股；000016.SZ确认退市，无换码；5576+2-1=5577。两个周周期23/30及月10，预期分页前源单元164+1=165。不会将预算名单塞入正式job。

条件退市有界读取纳入后，按逻辑投影次数保守累加的完整文件大小基数1,513,059 B；实际列投影/解压/设备IO未冒充精确测量值。全部参考/因子及daily/baseline前后版本不变。0源请求、0历史行情内容读取、0正式写入、0job。工作目录已删除，详见reference-preview-result.json及reference-preview-summary.json。后续只基于已登记范围/大小、当前代码和小型source回执核预算，不额外扫描历史行情。

已登记旧范围2169文件/370,594,967 B；Silver适用既有Raw811文件/257,941,556 B，真正新源可增加周期；这些为metadata估算，不是已读文件内容或严格候选上界。27日原任务、Silver及DG启动仍未执行。

## 下一步范围预算（尚待批准）

预核独立复核通过：C/R/S集合、九份输入版本、四组相邻日、165逻辑源单元、条件退市加权1,513,059 B及临时目录删除均一致。脚本原文保留reference-preview.py.txt，临时脚本已删除，见reference-preview-cleanup.json。

复用原21日37份source complete小JSON：原18股两频历史共4,229,872 B JSON+CSV，单周全市场1,583,901 B，全部37页；本轮均值缩放约23.8MB只作参考，不冒充165页上界。元数据两轮共142,240 B如实留证，未读取payload/CSV/历史Parquet，见reference-source-receipts-summary.json。

原LLD§12.12.2现已列清原27日两个失败run、81股全源历史/1退市处理、旧文件按可信区间及实际新源选择、2014起全部Silver、候选校验及一次中断/收尾。正常保守预计读16GiB/写12GiB/空间32GiB；含一次必要同范围续跑及最后验收合计读32GiB/写24GiB/空间48GiB，非实测IO/新程序限额，默认spill占用不冒充累计流量。没有重复全局行情审计或性能测试。历史范围需按根AGENTS另批，尚未触发原job或启动DG。

独立文档/代码复核还纠正两处表述：旧“五项开发阶段”授权明确标历史，避免与旧20实际已收尾矛盾；Raw只拒绝显式周期源日期不足cutoff，不能保证先拒绝晚于27日的输入。若源已推进，Raw可能先提交、Silver才按unit.asof拒绝，保留已提交Raw/回执并停止，不改冻结日期、不回滚或补绿。该风险及现有单股样本边界已回写共享LLD§12.12.2；未为此修改代码或扩大本轮执行。

最后独立复核已确认上述状态、源大小估算和日期分工修正到位，未发现文档阻塞项。文档完整性与指定路径diff检查通过；已验两源码和测试指纹仍一致。具体历史读写范围已单独发送审批，尚无新回复；本轮在此等待，不将最小预核批准扩展为正式补数授权。

## 正式历史范围获批

2026-10-28T10:22:55.226440+08:00 管理员对具体范围/预算申请明确回复“批准”。本阶段依共享LLD§12.12.2，通过原27日失败run FROM_FAILURE恢复周/月Raw，再消费原通知推进全部Silver；正常预算16/12/32GiB，含一次必要续跑与收尾总32/24/48GiB，不新增程序限制。先核原配置、当前源参考版本/小型控制和无并发写者；成功/失败按实际结果记载，失败先停止报告，不自动重跑。

### DG启动及原周任务提交

DG通过原启动入口复用现有PG/CH/隧道启动成功，实际webserver1.13.26、orchestrator已加载。10:24元数据预核通过：原父run配置/分区、9份输入版本、baseline/daily和10份已验源码指纹不变，pending0、writer空闲、四类job无在途，四sensor RUNNING。只读预核脚本首次缺SDK InstigatorState类型注册导入，仅元数据反序列化失败，补导入后同范围核对通过；无正式写入/数据job失败。

通过原FROM_FAILURE提交周子run **d7ae3495-bb23-4c33-a4be-d78d2aba2742**；配置、27日意图、30日分区、run key/原sensor和parent/root均读回一致，执行范围为原asset及三checks，不手填stock_codes。当前QUEUED，原全局并发1正执行raw_anns_d_update_job，另有正常raw_index_global排队；不改变并发/优先级，不取消或干预其他任务。证据见raw27-execution-preflight.json、raw27-week-reexecution-{request,response}.json及raw27-week-identity-verified.json。

## 原27日周恢复结果：失败后停止

2026-10-28通过原启动入口启动DG（原PG/CH/隧道复用、实际Dagster1.13.26），四sensor仍RUNNING、未重置cursor。以§12.8完整原参数仅提交一次原周父run319ec97d的FROM_FAILURE，子run为**d7ae3495-bb23-4c33-a4be-d78d2aba2742**，27日意图、30日分区、完整配置、run key及parent/root读回一致，包含原asset和三checks；stock_codes仍空，名单由原job产生。全局原并发1先等待正常公告/国际指数任务，未改变优先级/并发或干预其他任务。

本次周子run实际运行时间2026-10-28T10:27:03.741148+08:00至2026-10-28T10:27:45.755284+08:00（约42.01秒）。81股周历史+2个全市场周周期，共83个源单元/83页、70590行已下载完成；source JSON+CSV 19961338 B，含控制回执源目录22523318 B。月历史的81单元及后续当月1单元尚未执行，不能把83页说成整轮165单元已完。

错误为**period_process_memory_exceeded**。冻结manifest中原policy为DuckDB3GiB、进程RSS4GiB、spill16GiB、workspace32GiB、2线程，与原DEFAULT一致；本轮没有新增、降低或覆盖这些参数。栈定位stock_period_raw.assemble:847调用COPY，execute:372为工作线程启动后的50ms内存检查；不是SQL执行前349的检查。异常路径interrupt并等待SQL线程退出后才释放writer。已有进度日志reuse_old_ranges=1753，旧周行情和源CSV已经读取/合并；phase=download仅说明候选阶段未完整落盘，不能据此声称0历史读取。日志未记录实际RSS峰值或各模块内存占用，不能编造超出多少或把压缩文件大小当内存。

候选写出期间超限，尚未完成候选校验/两频准备，未进入history.run_period:1298后的正式publish。精确运行目录属性核对：4902份未验收Parquet分片、151514675 B；copy.json、week.candidates.json、月build、complete和committed均不存在。源/未验build/manifest合计174254656 B（约166.18MiB），全部位于data_lake_staging原执行53a8a26605bc468313dd25069e9a8688d035d51c3b308b7c8d96bba88c4a26be中，保留以便恢复。没有读取这些候选内容作额外审计。

正式文件提交0、原周23目标版本不变、baseline版本不变；factor_through仍21日，周/月last_refresh仍21/20日，completed_through仍16日周/9月；pending保留原27日未消费意图。该run没有新的实际Mat/check/完成通知，只有planned记录；无本链在途任务，writer已释放。原月父run及Silver未提交后续；DG及四sensor保留RUNNING，正常其他数据集调度属于原启动授权，不以其运行结果冒充本链补齐。

**停止与后续边界。** 已按失败即停执行，没有自动重跑、调整内存、修改冻结policy/身份、手工提升分片或删除待办。对后续恢复，原source complete及版本匹配的83页可复用；无copy.json的私有build/week由既有续跑逻辑清理重建，不把未验分片当成果。下一步须先只看当前代码/既有日志核清COPY总进程内存及原运行参数如何处理，在原方案/LLD明确修正或配置方案并获准后再续原ID；不能仅靠提高阈值、另写补数入口或重复试跑绕过。此次失败不推翻旧20成功，但27日Raw/Silver尚未补齐。

精确证据：raw27-week-failure-evidence.json、raw27-week-staging-stat.json、raw27-week-stopped-summary.json、raw27-week-stop-metadata.json及原请求/响应/身份核对记录。独立代码复核纠正了首次口头“COPY前失败”：实际为COPY启动后中止，正式publish前；该更正已同步本节及报告。


### 只读辅助操作修正与清理

本次四个临时脚本仅核对既有运行/sensor/阶段日志和精确staging属性，没有用它们补数。首次预核缺InstigatorState注册导入；身份报告首次误用不含yaml的全局解释器，改用项目现有.venv；收尾日志查询首次把LIKE的百分号写进参数化SQL，改为LIKE ANY绑定参数。三处都仅辅助只读操作失败，未初始化instance、写库/Lake、触发额外job或安装依赖；纠正后核对通过。唯一正式数据job失败是上节COPY内存超限。四脚本已移除临时位置，原文按txt保留在报告供追溯；当前DG运行日志仍为活跃日志，不作为无用临时文件删除。

收尾独立复核通过：83页、4902分片及166.18MiB合计、COPY启动后/正式发布前失败、正式提交0及旧水位/版本未改、无后续提交或重跑、四脚本删除与staging保留均与小型证据一致。

## 管理员批准运行RSS8GiB并继续

已按要求将最小接线方案/配置审计/正常及负向验收/正式原job恢复细节落共享LLD§12.12.4，并同步原总方案及月LLD。旧冻结policy/83页身份不改，仅本次原生FROM_FAILURE额外资源tag取8；不再新申已有历史读取授权。开发前独立审计后实施，隔离测试通过及重载当前代码位置后续原周、原月及Silver；当前尚未按8GiB触发。

### 8GiB接线开发及验收完成

2026-10-28T11:20:17.182343+08:00：三生产文件按LLD§12.12.4实现并通过开发后独立复核。新29用例（28+1分轮）及原相关89用例均通过，Ruff全改动/致命基线、文档检查、CodeGraph explore/impact/sync/status通过。新用例含真实原SDK job/tag接线、三原检查及真实小producer缓存复用，但不冒称正式性能或GraphQL/PG验收。3生产指纹与测试归档一致。旧回归首次3失败已修正：两例原非法handoff的NULL父键恢复走原分支，一例旧NS补现行SDK tags字段；未放宽业务预期。全部测试临时目录已清理，红XML无损gzip存证，见rss8/verification-summary.json。

11:18正式只读preflight确认原daily/manifest/baseline及9输入同版、83源单元415文件版本已保存、无本链在途、writer空闲。下一动作仅按预先保存rss8-reload-request.json重载orchestrator，再提交原周FROM_FAILURE带8标签；不修改默认/冻结policy和原任务配置。

### 月Silver已有子执行的顺序恢复

原周/月Raw已SUCCESS并原events收尾，week Silver658全部complete。月Silver已成功但源当月后续合法更新先于sensor确认，现sensor冻结子82c6253a后缺本地CP而停在确认。经当前代码/既有定向测试与独立复核，可沿原silver_stock_monthly_update_job显式parent恢复，不改代码或状态。按LLD§12.12.5先核154单位/153复用/仅10月重建、参考与源目标版本匹配，已保存完整请求，接着只提交一次原job。

### 8GiB正式结果及月Silver恢复进展

周Raw9edc90f7-1822-4abb-af85-7d1cb1a71034、月Raw66b1c247-4c27-4009-9b21-2e5c7755c432均SUCCESS，原日期/配置及标签读回正确；首次交付1754周/416月，共2170文件/2170物化、两条通知，原83页415源文件版本不变。RSS有效8589934592，采样峰值6214270976 B（约5.79GiB），冻结4294967296及identity/hash保持原值。末月原events成功确认执行5d29c125…并发原通知，daily待办已清，因子/两频刷新均27日、闭合周23/月9月，未提前关闭当周/当月。

月Silver已按§12.12.5原job提交run661f50eb-8344-45c4-b801-25b2d8610e21，并SUCCESS；子82c6253a复用153周期、只重建2026-10，0新源请求，真实文件阶段0.668秒（只代表该恢复阶段），154月周期/595280行。原sensor已确认子及覆盖父，现在等最后一条5d29月通知消费，不以Raw/子job成功提前报告全链完成。

## 11:50最终完成与独立验收

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

**TODO（不阻塞本轮数据完成）：** 现有月Silver恢复窗口先返回silver_recovery_required，按既有规则等待显式parent原job；下一tick却直接确认尚未执行的子任务，改报缺少CP。本轮已通过原恢复job完成。后续仅核清这个窗口的确认时机和提示是否应保持明确的人工恢复指引，再按原方案/LLD决定是否开发；本条不新增自动补数要求，也不把本次人工恢复称为已修改自动行为。


独立收尾复核确认Raw/Silver计数、父子覆盖、三通知消费、待办及sensor状态无不一致；没有新增正式读取或执行。

## 月Silver错误的代码来源核对

本轮提交前只读核对：sensor首次silver_recovery_required按原LLD§11.6等待明确的恢复运行，属于原设计；后续tick仅凭execution.json存在就调用confirm_update_delivery，未核该恢复子job是否已生成逐期执行回执，导致2014-01.json缺文件。这里缺的是恢复子的工作回执，不是正式2014-01月数据。Git逐行追溯该1353—1373行来自6e60177128（2026-10-17），当前Silver主文件SHA与旧20执行前相同，本轮8GiB改动未触及它。本次数据现场已按原job恢复，确认前置条件和提示持续性仍留TODO，未声称已开发自动恢复。
