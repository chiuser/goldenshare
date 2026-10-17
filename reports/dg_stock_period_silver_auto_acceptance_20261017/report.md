# DG周/月Silver剩余1—3项：开发与隔离验收（2026-10-17）

以下首先记录开发与隔离验收阶段，随后记录同日获准执行的正式接线；两个阶段分开记账。开发阶段按总方案§9及共享LLD §11完成。正式首次生成仍沿§10.10已有证据；没有重新审计或重建810文件，没有操作正式Lake/staging、instance、事件、code location或sensor。Prod及R3未推进。前序测试源码登记清退已提交e87225b2，未推送。

## 结果

1. 第1项日常update与统一恢复继续沿d865e640实现；本次真实Raw通知取代测试metadata适配器，恢复、覆盖、取消及事件路径纳入直接回归。
2. 第2项已接通Raw真实receipt → 每个受影响频率一条observation → 两个默认STOPPED的Silver sensor → 原Silver job及三项检查 → 下一tick确认真实事件并补原有JSON回执。原生anchor检查产生前不提前宣告整批成功。
3. 第3项方案/LLD、两份治理文档与本报告同步，按明确白名单提交；catalog仅提交本域三处说明，保留原有格式改动。开发验收时正式接线及首个真实日常样本未完成；后续接线结果见文末，首个真实交付继续待验收。

## 逐条对账

后续正式接线已于同日完成，见文末；下表及上述开发轮正式操作为零的边界保留，不混写两个阶段。

| 已确认硬口径 | 实现位置 | 正反证据及结果 |
| --- | --- | --- |
| 21列、价格/NULL/Decimal、源日期及2014边界保持 | 原run_contracts/stock_period_silver及select_period未改 | 原projection/contract金样本回归通过；新集成按独立字面值验证A=25.1250、其他股票=11.1400，最早周移除旧键后0行 |
| 明确Raw交付、全频率范围；不只传anchor | stock_period_history.replay_events及stock_period_update事件入口 | 实际Raw生产者两频历史6文件，week/month各1条通知、各1个Silver请求，全部6期更新；每期一次选行、一次COPY |
| 通知不是检查成功 | completion_notice/validate_completion_notice；既有batch_event_evidence | 错version/freq/count/batch/多余path拒绝；Raw真实失败检查使通知无法触发Silver |
| 日常/history/CLI events/handoff/周线补报消费者同步 | Raw执行器、CLI及ops/stock_weekly_bootstrap_checks | 原history/recovery/handoff/handoff_memory/combined/update和CLI集成通过；周线补报显式清空临时通知回执后只通知week，month仍待办 |
| events-only不重新下载或计算 | replay_events及原CLI | 通知落盘后本地回执失败，重放只补通知；源请求数和文件版本不变；缺文件检查时即便通知已发也不能宣告events_complete |
| sensor标签/默认状态/原入口不改 | 两新sensor、统一sensor_tags、静态定义名单 | 精确quote_data/silver/asset_update及STOPPED、60秒、原job检查通过；实际SensorDefinition.evaluate_tick在隔离instance通过 |
| 一tick一批，不加日期/股票循环或新窗口 | evaluate_update_sensor、update_run_id、原run-key builder | 同通知重读key/config稳定；无通知不读receipt或行情；周/月任一相关job活动时短路，不影响其他job |
| 真实ready、失败/错绑定仍拒绝 | 原batch_event_evidence/require_checks及confirm_update_delivery | PLANNED不遮盖已完成结果；最新真实失败、错物化绑定都不能写整批成功；没有改普通readiness语义 |
| 读取预算及容量 | 一次两job的JobBucket活动查询、一次批次run查询、一次通知、两条集合SQL | 新请求tick实测5次存储读取；656周+154月实际隔离事件，每频率2条集合SQL，返回2N物化+6N检查；无行情文件/COPY |
| 原ID、已完成文件复用 | 原recover_update_execution、owned_update_records及io.publish | 原输入不变、A/B已完成C未完成、rename后记录失败、TERM/KILL和锁释放等直接回归通过；不改旧身份/hash |
| 合法新Raw逐期承接 | 原恢复规划；sensor跟踪actual execution_id | 原范围及后继来源、只重做C、不吸收新批额外D、后继再次中断及祖先覆盖回归通过；未发布/无完成引用仍拒绝 |
| 文件、DG检查、完成回执分开 | 原report_update_events；新增confirm_update_delivery | job结束时回执尚未完成，下一tick凭全部真实绑定事件汇总；回执失败保持pending，恢复0行情SQL/0 COPY；汇总中源版本改变不写成功 |
| 已关闭重复通知不重开旧版本 | completion回执绑定execution identity及完整scope | 后来合法更新后再次收到旧通知，复用原交付回执并推进位置，0重算；覆盖祖先继续沿原record_update_coverage |
| 不自动盲重试、不新增框架/配置 | 两个合同中的60秒常量、既有writer lock与cursor | 失败/取消run保持待办，只给出明确恢复ID；0新CLI动作/flag、0新依赖/状态表、0正式操作；R3暂停 |

## 测试与性能证据

- 直接回归19份测试文件：200 passed，57.49秒，见临时证据目录fixed-direct.log/xml。覆盖现有CLI/本地HTTP-worker取消/续跑/events/handoff/原生Raw jobs；HTTP仅为测试自建端点和字面源响应。
- 随后将活动检查改为同一次JobBucket查询覆盖周/月两个job，未增加调用次数；最后仅重跑受影响sensor及集成：23 passed，9.22秒。未重跑未变的810期metadata测试，该helper和容量输入没有修改。
- 原静态合同113项、catalog12项、check治理6项，全部通过；这些是定义/合同证据，不是正式运行验收。
- 810期metadata两频集合查询实测0.378秒；真实小样本6个Silver文件的两频链末次0.273秒、进程峰值RSS约365.55MiB。此值包含测试进程历史内存，不能当正式全市场耗时或内存承诺。无全量bootstrap性能外推。
- 本次修改Python默认Ruff、src/tests致命错误基线、文档检查及git diff --check通过。CodeGraph explore/callers/impact核验Raw事件链及Silver消费者，动态回调以既有源码引用清单补核；最终未分类差集0，sync/status已同步。无跨子系统、API或前端边界变化。

开发阶段发现的旧测试前提已校正：Raw现已自己发布完成引用，不再把“不调用测试适配器”当作未发布；反例改为明确缺引用的真实物化及真实绑定检查，原拒绝断言保留。文件检查尚未完成时，files_complete通知可以存在，但整批events_complete必须仍为false。原HTTP集成初次被执行沙箱拒绝自建端口，随后获工具权限重跑且最终固定版整组通过，没有改代码绕过权限或连接正式服务。

## 交付边界与后续

开发阶段程序和隔离验收完成，当时尚未正式重载定义、初始化新sensor消费起点、启用sensor或完成首个真实日更；不以本次合成源和临时事件冒充正式交付。未来只按§11.9做一次有界接线基线，不重下历史、不重写已验收810文件。既有两Raw sensor的正式状态、水位和19:30窗口本轮均未触碰。并发竞争继续由原锁拒绝，失败任务不自动反复重试。

详细机器结果见results.json；原始日志、XML、治理分批报告位置汇总在/private/tmp/dg-period-silver-daily-lkm7czce/。保留其他任务全部未提交内容，不推送。


## 同日正式接线与休市验证（19:57完成）

用户要求先完成当前能验证的部分，真实下载等周一。执行前已将精确操作、基线、预算和中断边界补入原方案及共享LLD §11.13；没有改动程序或扩大业务范围。

| 核对项 | 正式证据与结果 |
| --- | --- |
| 接线基线 | 复用首次810文件/2430检查。其后两Raw新物化均0、历史observation均0，因此两新sensor以schema_version=1/after=0初始化，没有吞掉变化 |
| 定义加载 | 仅reload orchestrator一次；新sensor均加载且默认STOPPED。R3模块与此前获准加载文件hash相同；catalog未提交差异仅格式 |
| 状态初始化/启用 | 两次setSensorCursor、两次startSensor，均返回成功；两新sensor当前RUNNING。未修改Raw或其他sensor |
| 自然无输入场景 | 周线tick2578125、月线tick2578126均由daemon自然产生，SKIPPED/silver_no_completion、after=0、无error、runIds/runKeys为空。没有调用preview/evaluator或手工launch |
| 不误触发任务 | 两个Silver job无运行记录。0源请求、0行情SQL/COPY、0行情写入、0物化/check补报；没有重复下载或重扫810个文件 |
| 保留原状态 | 原113项sensor开关状态相同，两Raw业务水位、Raw daily.json及Silver既有完成记录相同；其他任务改动保留，R3继续暂停 |

证据见[formal_handover.json](formal_handover.json)，原始控制面响应保留在其中列明的临时目录。接线前进程列表首次读取遇非UTF-8显示字节，修正临时只读脚本的解码后完成核验；没有因此改动生产逻辑或放宽数据门禁。

当前可完成的正式接线和无输入场景已通过。仅余首个真实Raw下载→Silver自动更新验收，等待周一既有19:30窗口的真实交付；周末skip不冒充这项通过。本轮更新原三份设计文档及本报告/JSON，未改代码、未新增配置/依赖、未提交或推送。
