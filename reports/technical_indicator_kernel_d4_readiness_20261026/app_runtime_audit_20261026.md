# D4 App 运行时只读开工审计

审计日期：2026-10-26。当前分支 `dev-interface`，HEAD `38193f953857f6e6233d7d91ddd921c6c77c70cf`。本报告只依据当前两份原 HTML 和现行代码；没有修改仓库文件、运行测试或 SQL、导入项目、访问数据或外部服务。只新增本报告。

## 结论

App 装配、异步调用、工作线程、断开观察、取消、发送和关闭的入口及归属已基本写清，没有必要再发明 Runner 或 RequestHandle 类型，也不能以 D4 文件尚不存在判定缺陷。发现 1 项开工前应补明确的异常交接细节：保留原异常时，如何同时解除异常栈对完整结果的引用，才能满足“释放结果后才归还名额”。这是工程细节，不需要新增业务拍板。

## F1 / P2：清空交接容器仍不能保证原异常不再持有完整结果

**原文依据**（`docs/architecture/technical-indicator-kernel-low-level-design-v1.html`）：

- 1282：最外层 finally 必须“释放body/result及任务返回值引用，再归还已取得Lease一次”。
- 1284：worker 子任务“捕获BaseException保存原对象”，主任务在组外“重新抛同一error”；并要求“错误和结果引用移交/丢弃后立即清空局部容器”。
- 1285：HTTP worker 应“释放result局部引用，仅移交唯一body”。
- 1918：清理要求是引用按生命周期释放，“仅GC调用或RSS下降不能证明无引用”。

**当前代码依据**：

- `src/foundation/technical_indicators/service.py:103-150`：局部 `result` 在 136 行建成，140 行计量、141/149 行检查停止都可失败；142-148 行保留并抛同一个原异常，没有在异常出口解除 `result` 的局部引用。
- 同文件 32-43 行：有原错误时直接 `raise primary_error`，正常但清理失败时创建 `ResourceCleanupError` 并保留清理错误为 cause。
- `src/foundation/technical_indicators/output/encoding.py:49-72`：编码失败栈的 `payload`、`chunks` 等局部仍可指向完整结果；75-84 行的 `result` 也属于异常经过的栈帧。
- `src/foundation/technical_indicators/output/encoding.py:87-95`：HTTP 编码函数接收 `payload`，若失败，原异常同样经过持有该参数的栈帧。BytesIO 的 with 会关闭缓冲，但不会解除异常栈对 payload 的引用。
- `src/foundation/technical_indicators/contracts.py:200-218`：`CalculationResult` 持有 times、calculations 等独立结果。SQL 连接已关闭不表示这些 Python 结果引用消失。
- `src/foundation/technical_indicators/execution_control.py:106-113` 已专门将中断错误存为类型/文本而不保留 traceback，注释明确避免异常栈继续引用连接；App 对完整结果的异常交接还没有相应规则。

**哪里还不明确**：Python 原异常带有 `__traceback__`，还可能通过 `__cause__` / `__context__` 保留原错误。即便 D4 将请求局部容器中的 `result` 置空，保存的原异常仍可经已结束的 calculate/编码栈帧持有同一份结果。LLD 规定保留原对象和清容器，却未规定如何解除这些栈帧中的大对象引用，也未要求在调用方仍持有该异常时验证它们已解除。

**人话例子和后果**：一次请求已算出完整结果，最后的字节检查发现超限，SQL 和文件均已关闭。worker 把该错误交给异步主任务，主任务清空自己的 result 后归还名额；上层测试/诊断继续保存这个原错误，错误栈却仍指向 calculate 中的完整结果。下一请求已获准，上一份结果仍占内存。连接数或表清单正常不能证明这一点已满足。

这里只指出静态可见的引用路径和 LLD 缺项，没有运行内存实验，不能据此报告已测得多少残留内存或生产泄漏。

**最小建议**：在原 §12.4 明确错误交接后、Lease 归还前，由哪个 App 方法解除已结束异常栈帧及其异常链对结果/编码输入的引用，同时保留原异常对象、类型、消息、cause 及清理附记；不得清理仍在运行的工作线程栈，不得用 GC 或 RSS 下降替代引用检查。将“调用方仍保留原异常时，大结果/部分编码输入已不再被已结束请求持有”并入既有错误/清理或编码失败检查，带正常对照；沿既定小调用范围安排，不增加长历史或新配置。是否使用清理已结束 traceback 栈帧等具体实现办法，应先写回原 LLD 再编码。

**是否需要管理员拍板**：不需要新增业务决定。既有要求已经明确原错误优先与归还前释放引用；这里只缺同时满足两者的工程方法。若团队坚持保留所有失败栈帧中的完整局部数据，才构成对已确认内存/释放边界的改变，需要另行确认，不能由开发默认选择。

## 已核清，不列为缺陷的边界

| 项目 | 原文 / 现行代码 | 判断 |
| --- | --- | --- |
| 业务进程和工作线程 | 组件设计 134-150；LLD 1224、1230、1234 | calculate 在调用方业务进程的一个既有框架工作线程顺序运行；唯一中断线程只负责 interrupt。没有另建计算池或独立服务的缺口。 |
| D4 四个文件与异步签名 | LLD 248-275、1237-1288 | `create_runtime(settings)`、`execute_library(...)`、`execute_http(..., receive, send)`、`send_encoded_body(...)` 均有明确签名和边界；Runner/RequestHandle 并非原设计所需类型。 |
| runtime 生命周期 | LLD 1238、1249-1256、1287；`src/app/web/lifespan.py:12-29` | 隔离诊断/测试持有 runtime 并 finally aclose；D4 明确不改正式 lifespan/路由/app.state。当前正式 lifespan 尚未接内核符合范围，不是缺陷。 |
| Service / Control 交接 | LLD 357、1283-1285；`service.py:47-54,85,152-191`；`execution_control.py:22-48,61-95,130-167` | App 每请求创建 control，注入该次 Service；最早到达时间不重置，连接/监控/清理由工作线程负责。构造参数可直接对接现行代码。 |
| 注册表和来源可共用 | LLD 1256、1280；`calculation/indicators/__init__.py:4-20`；`calculation/registry.py:40-45`；`src/foundation/clients/local_lake/technical_indicator_price_source.py:61-70` | 内置真实 factory 和 freeze 已有；来源构造只检查依赖可用并保存 config，不保存请求句柄或连接。不是 D3 还需补业务场景。 |
| 等待名额和归还 | LLD 1226-1231、1281-1282、1288 | 同一事件循环原子修改；已授予未移交由 acquire 回收；移交后 execution 唯一归还；重复/跨 runtime 归还被拒绝，失败原错误优先。 |
| 取消和断开 | LLD 1233-1236、1283-1286 | receive 唯一观察任务在 acquire 前启动；先发 stop 再取消组；library 主任务在可取消 done 上等待，worker 不因取消被遗弃；正常结束先置 request_finished。 |
| HTTP 发送阶段 | LLD 1270-1276、1285-1287、1538-1540；`output/encoding.py:75-95` | 隔离入口使用库结果合同；不做 Biz 适配；编码在 worker，发送不再编码、不竞争 receive；发送开始前查第6秒，开始后服从第8秒，真实退出后才归还。1234 的 Biz 适配描述属于未来接入流程，12.4 已明确 D4 范围，不能据它要求 D4 迁移正式 DTO。 |
| 关闭 | LLD 1229、1251、1287-1288、2074 | 先 closing、结束等待、给活动 control 发停止，再 shield 等实际归还；超过目标继续等并记失败。P03 已明确由 runtime.aclose 触发，不能另造停机长任务。 |
| 配置来源 | LLD 1674-1723；`src/foundation/config/settings.py:66-123,166-181`；`configuration/settings.py:12-61` | 19项初值和别名集中在 Settings，KernelConfig.from_settings 复制；App 复用同一解析结果，运行实例固定。并发/等待等目前待 App 消费属于 D4 实现工作，不是配置缺失。 |
| 正式消费者 | LLD 2135-2154、2182-2188 | D4 只到隔离接入和运行验收；API、页面、XXM、DG 后续单独处理。本次不要求正式消费者迁移或 D3 新增业务场景。 |

## 使用的规则和工具

读取根、src、foundation、app、app/web 的 AGENTS，架构基线 `docs/architecture/subsystem-boundary-plan.md` 及 goldenshare-dev-intake skill。CodeGraph 使用 `codegraph_explore`、`codegraph_callers(TechnicalIndicatorService)`、`codegraph_impact(ExecutionControl, depth=2)`；影响面包括 Service→来源/执行器/引擎/Collector/编码、Control 调用方与相关 Foundation 测试，以及现行 Web lifespan。CodeGraph 对 Service 类未返回 callers，因此继续核实了真实导入/使用位置；没有据此断言不存在测试消费者。

本文“已核清”只表示代码与设计可对接，不表示未实施的 D4 已通过运行验收。没有执行测试/SQL、项目导入、外部请求、Lake/数据库读取或正式应用接入，也没有评估资源测量与测试预算是否全部足够；该部分由主审计另行汇总。
