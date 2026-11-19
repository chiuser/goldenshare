# D4 admission 与结束处理独立只读审计

日期：2026-10-26。工作区：`/Users/congming/github/goldenshare`，当前分支 `dev-interface`，HEAD `38193f953857f6e6233d7d91ddd921c6c77c70cf`。

## 结论

D4 的 FIFO、活动/等待上限、授予与取消同时发生、唯一归还、关闭时等待真实收尾等核心合同已经写清，未发现这些事项需要重新决定业务口径。Foundation 的控制对象、独立连接、完整 calculate、严格编码和清理入口已经存在；D4 尚未编码与尚未执行其验收本身不是开工阻塞。

发现一处原方案与 LLD 的具体先后顺序需要对齐：非法算法参数是否在申请名额前拒绝。另有一处“关闭 runtime 时正在发送的 HTTP 如何接收 cancel”的实现交接应明确；现文可以读成允许发送继续到原第8秒，不能未经确认就报告为已证明违反2秒清理目标。

因此，本子审计支持进入 D4 方案核对，不能将当前状态表述为已获 D4 编码/运行授权。管理员本轮仅授权审计。

## 范围与依据

- 已读根、src、foundation、docs、docs/architecture 的 AGENTS.md，`docs/architecture/subsystem-boundary-plan.md`，开发 intake / 文档治理 skill。
- 原方案：`docs/architecture/technical-indicator-kernel-component-design-v1.html`。
- 原 LLD：`docs/architecture/technical-indicator-kernel-low-level-design-v1.html`。以下行号均为当前 HTML 源文件行号。
- CodeGraph 使用 `codegraph_explore`、`codegraph_search(TechnicalIndicatorService)`、`codegraph_callers(request_stop)`。图中 request_stop 的现有调用者只有本库测试/诊断链；当前未发现 App 正式消费者。源码逐项复核作为当前事实。
- 未运行测试、SQL、项目导入、数据查询、服务调用或安装；未修改仓库代码、设计文档、配置或数据。只新增本临时报告。没有相关 memory 命中。

## D4 计划范围

LLD 2182-2184、2550-2557：步骤7为 App 四文件的隔离装配/有限等待/结束处理；步骤8为原定资源、取消、容量和隔离 ASGI 验收。1237-1288 固定四文件入口与对象字段。1238、2551、2564 明确不修改正式 lifespan、app.state、路由、API、页面、XXM 或 DG。

## 已齐备合同及当前依据

| 对象/动作 | 原 LLD | 当前代码/证据及结论 |
| --- | --- | --- |
| 配置和容量 | 1674-1788 | `src/foundation/config/settings.py:67-123` 已有19项及初值；`technical_indicators/configuration/settings.py:13-61` 复制为不可变配置，只检查单项及直接关系；D4 消费而不新增配置。`test_configuration.py:15-35,53-185` 已有字面默认/合法边界/拒绝样本。 |
| 一个 runtime 一份 admission | 1225-1229、1249-1261 | 活动数来自 active_leases；最多2等待、FIFO、release 同事件循环无 await；shutdown 先 closing 后固定 idle_event 引用。新文件尚不存在属 D4 待实现，不是合同缺口。 |
| 授予同时取消 | 1228、1281-1282、1288 | assigned_lease 与 handed_over 固定；acquire 回收未移交 Lease，成功返回后 execution 最外 finally 唯一 release；未知/跨 runtime/重复归还拒绝且不减计数。无需再决定。 |
| 绝对截止和首个停止原因 | 1261、1288-1292、1373-1403 | `execution_control.py:22-74` 已保留 T0、第6/8秒和首个 stop_reason；排队不得重置。`test_execution_control.py:36-65` 有精确虚拟时钟与首原因断言。等待两种到期错误已在 errors.py:36-49 定义。 |
| 获准才运行/独立连接 | 1230-1231、1283、1291 | `service.py:74-150` 通过注入 control 调同一 calculate；152-163 在打开连接前检查、单连接并启动 monitor；`service.py:18-29` 现有隔离连接设置。队中无连接/monitor 属 D4 admission 应实现行为。 |
| SQL真实退出后清理 | 1396-1403、1476-1478 | `execution_control.py:130-167` 先解绑、真实 join；`service.py:165-191` 依次清理并唯一关连接。清理异常不跳过其它项/原错误优先见 service.py:32-43、165-191；对应现有反例见 `test_errors_and_cleanup.py:92-187`。 |
| 运行 A 取消不误停 B | 1470-1472 | 独立 control/connection 已存在；`test_executor.py:217-223` 已有局部证据，完整 App 并发仍留给 D4。 |
| Worker 等待和 HTTP 断开 | 1232-1236、1283-1286 | 库包装的可取消 done Event / worker 子任务 / 原异常交接、HTTP 唯一 receive 观察者及先 request_stop 再取消组已逐步写定。不需新增计算线程池。 |
| 结果与发送 | 1274-1287、1537-1540 | `output/encoding.py:49-95` 已有分块检查、严格编码、唯一 body；`service.py:140-150` 已完成库格式计量及最终检查。D4 response 仅一次 start/body，开始前6秒检查、开始后8秒截止、send 实际退出后再归还已经明确。 |
| 装配基础 | 1254-1256、1280 | `calculation/indicators/__init__.py:4-20` 已注册真实 factory 并 freeze；`clients/local_lake/technical_indicator_price_source.py:61-66` 仅保存 config 并检查现有 Arrow 可导入，不读取数据/创建连接。 |

## 候选问题 1：非法算法参数何时拒绝

- 原方案精确依据：521 行“未授权或非法参数不进入等候”；522-524 行先名额再工作线程、队列有界、总截止不重置。
- LLD 精确依据：1283 行库入口固定为 `control→acquire→worker.calculate`；1285 行 HTTP 同样先 acquire 后 worker；1271 行只说 request 已完成解析。LLD 1151-1154、1932-1934 只保证 calculate 读源前校验，未说明在入队前执行算法参数/容量检查。
- 当前代码：`contracts.py:80-111` 的 CalculationRequest 校验类型、日期等结构，但允许构造 `ma(period=0)`、未知 calculation_id 或 `limit=10001`。MA 的真实参数名/正整数规则见 `calculation/indicators/moving_average.py:12-18`。算法/参数到 `dependencies.py:46-50` 拒绝；容量到 `contracts.py:114-125` 拒绝；它们现由 `service.py:85-88` 在 calculate 内调用。
- 实际场景：A/B 正在计算，C 携 MA 的 period=0 到达。严格按 LLD1283/1285，C 先进入等待占位置，D/E 可能被其挤出；C 也可能先收到 WaitExpiredError，而原方案521期望该非法参数不入队。
- 最小建议：编码前在原两文说明 D4 排队前的轻量校验范围和调用位置。若521同样适用于隔离入口，复用现有 normalize 与 Definition 的 resolve/validate_parameters 规则，不复制算法规则、不读源、不构造 SQL；calculate 自身保留现有验证。不要为了此问题新增请求字段、参数上限或通用框架。
- 是否管理员新拍板：不涉及重定并发、等待、参数合法性或截止数值；但“隔离入口本轮是否承担521这项”存在范围/顺序差异，需主审计判断并在方案确认中明确，不能编码者私自选一条。

## 候选问题 2：runtime 关闭时，已开始的发送如何收到 cancel

- 原 LLD 精确依据：1281 规定 Lease 只存 id/control/released；1287-1288 规定 aclose 对活动 control 发 cancel 后等真实归还；1286 的唯一观察者收到断开/外部取消才取消 task_group；1539 规定发送开始后按 target_finish 的 CancelScope，calculate 返回时 monitor 已结束。
- 当前代码：`ExecutionControl.request_stop` (`execution_control.py:61-65`) 只改变线程 Condition 下状态；没有 App CancelScope 或异步通知绑定。`stop_monitor` 137-166 已清掉 callback/monitor，晚到 cancel 不会操作已关连接；此点正确。
- 实际场景：T0+1 已开始 slow send，T0+2 runtime.aclose 调 request_stop(cancel)，客户端未断开、send await 未返回。现写定步骤中没有说明谁将该 cancel 交给正在发送的 CancelScope；按字面可继续持名额等到 T0+8。
- 最小建议：在原1287/1539明确该场景预期。若关闭只禁止新工作、允许已开始发送在原8秒内退出，明确记录即可；若要求 cancel 立即取消发送，必须先给出已有 ExecutionControl 与请求 task_group 的具体交接及范围，再编码，不能自行加轮询线程/新任务系统或静默扩字段。
- 是否管理员新拍板：现有文字不足以判定这是要求违反；属于应明确的执行交接，不能自动升级为“必须立即关闭发送”的新需求。仅当确要改变已开始发送的现行8秒安排时才需要新的行为决策。

## 不成立的阻塞与后续限制

- 不把 AdmissionController、execution、response 尚未编码、并发/容量/ASGI 未验收列为开工阻塞；它们正是 D4 交付项。
- 不把尚未得到 RSS、实际取消耗时等实测当成待管理员决定的设计；原17/18.1已经区分实现后验收。
- Control 暂无 monitor_exited_at 字段，而1476要求记录实际退出时刻；1917主要验收记录取消/SQL退出/资源释放。D4 可在诊断边界记录实际 join 完成及其测量含义，不把该计量细节自动变成新增产品字段/业务拍板项。
- 2061、2008 已给12类控制测试及受控替身边界；2072-2104 已给真实 App/ASGI请求的独立预算、首错停止和无额外自动重试。不追加矩阵或借新的控制额度。
- 当前相关内核、配置、测试、两文无未提交修改；存在范围外 `src/app/runtime/news_intelligence/review_demo.py` 修改，不得覆盖。
