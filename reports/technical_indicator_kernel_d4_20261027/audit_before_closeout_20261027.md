# D4实施进展与暂停报告（2026-10-27）

本轮管理员新增决定：暂不实测内存，按数据量及LLD16.2既有预留估算即可。此前`ps`失败保留为历史事实，已不再构成内存验收门槛；不得把未测RSS标成0或通过。原查询/读取/输出保护和实际生命周期验收保持。本轮只更新文档并解释恢复成本，没有修复代码或续跑。详见`administrator_memory_decision_20261027.json`。

D4未完成、未验收。已写入隔离App实现，固定13个轻量函数一次通过；首次真实诊断在创建真实请求之前失败，按批准计划停止。收尾只读核对又发现既有架构检查被误覆盖。失败后没有修复、重跑、提交或部署。

## 依据和改动范围

- 原组件方案与LLD的`d4-execution-plan-20261027`记录开工前同步的顺序、接口、文件、固定节点、失败规则和预算。
- `plan.json`保存确切函数、7个真实节点/10个请求、保护文件指纹、独立预期与替身边界；此前预审记录属于当时判断，不能覆盖本报告的新问题。
- 当前`dev-interface`。新增App包5个文件、3个测试文件和诊断脚本；修改原两份文档、架构检查及本轮报告。其他工作区改动保留。
- 未安装或升级；未改Foundation算法/SQL/来源/配置，未接正式lifespan、app.state、API、页面、XXM或DG退出。12个指定保护文件重新核对，SHA256全部一致；不把这12个指纹扩大解释为全仓无改动。
- 开工上下文使用CodeGraph的search/explore查询服务入口与ExecutionControl，再读真实调用代码和消费者。CodeGraph结果不是运行验收；本轮没有调整跨子系统合同或正式消费者。

## 要求与实现、证据对应

| LLD要求 | 当前代码位置 | 本轮证据与限制 |
|---|---|---|
| 同时2个、最多等2个、FIFO、取消及过期移出 | `src/app/runtime/technical_indicators/admission.py`的`AdmissionController` | `test_admission.py`前7函数通过，真实Admission、控制替身；真实并发请求未执行 |
| 授予未移交由acquire回收；移交后只归还一次；拒绝重复/异runtime归还 | 同文件`acquire/release`；`execution.py`最外层finally | 授予同时取消、非法归还和正常对照通过；真实连接链路未验 |
| runtime共用配置、冻结注册表、无请求状态source，不提前建连接 | `composition.py`的`create_runtime/TechnicalIndicatorRuntime` | 静态核对；正式应用未装配 |
| 参数检查在等待之前，复用既有规则 | `execution.py`的`_validate_request_before_wait` | MA0拒绝、MA20正常对照通过，未读行情/创建真实Control |
| 一次请求一次calculate，现有AnyIO线程执行；Control/连接不跨请求 | `execution.py`的worker和`run_worker` | 轻量执行替身检查通过；真实10指标请求未执行，不宣称性能通过 |
| 取消先通知stop，再等worker真正退出，shutdown先拒绝再等归还 | `execution.py`的任务组/清理，`admission.py`的`shutdown` | 取消、到期、清理失败、停机4函数通过，受控Event和替身；真实中断基础证据沿原计划复用 |
| 单一receive观察；工作6秒、发送开始后总8秒 | `execution.py`的`observe_disconnect`、work scope；`response.py`的`send_encoded_body` | 响应函数内正常、发送跨工作截止、慢发送到期、断开和编码失败5次替身调用通过；真实ASGI未验 |
| worker返回None；一次编码；任务退出后清结果/body/错误帧，最后归还 | `execution.py`的handoff和最外层finally | 局部引用及已结束异常帧断言通过，保留原错误及原因；真实大结果释放/RSS未验 |
| 归还失败不能成功，不重复归还 | 同上 | 正常结果遇归还失败、原错误加归还失败的必要反例通过 |
| Foundation/App依赖方向与原架构检查保留 | `tests/architecture/test_technical_indicator_dependencies.py` | **不满足**：新增检查运行通过，但误删除原4个函数且漏禁`lake_console`；待恢复，不能宣称整体架构检查完成 |
| 固定4000根来源、10次请求、无重复运行 | `scripts/diagnostics/technical_indicator_resources.py` | 只准备一次4000根，首节点启动时失败；10次均未开始，无自动重试 |
| RSS、健康请求、连接/线程退出、发送和实际资源归还 | 同脚本7节点 | **未验**：进程内存测量在第一个节点前失败 |

## 已执行及实际费用

1. 精确执行`plan.json`列出的13函数，禁用自动pytest插件，`-x`首错停止，没有选择整个目录。结果`13 passed in 1.70s`，外层程序2.295554792秒。12类共42次控制替身调用（每类不超过6次），行情、SQL、真实Control均为0。证据：`execution_light_01.json`、`pytest_light_01_output.txt`。
2. 诊断入口只运行一次。准备一份4000根、2026年、单文件单行组的临时来源；字段和类型核对通过，CTAS/COPY共8000逻辑SQL行。准备连接关闭。
3. 第一个`single_http`子进程先执行`_current_rss()`，启动`/bin/ps`时收到`PermissionError: [Errno 1] Operation not permitted`。尚未创建`_Node`、真实Control、请求连接或调用calculate。父入口保存失败并清理唯一临时目录，退出码1；没有进入后面节点。证据：`execution_real_01.json`、`node_single_http_output.txt`、`node_single_http.json`、`real_01_output.txt`。
4. 只读核实`/bin/ps`文件存在，模式`0o4755`，并非文件缺失或没有执行位。当前证据只能确定启动被执行环境拒绝；本轮没有另起命令试跑、绕过限制或申请提权重跑。

| 计量 | 已消耗 | 原正常安排剩余 | 含续跑预留的总余额 |
|---|---:|---:|---:|
| 输入，含夹具 | 4000 | 15000 | 22000 |
| 定位键 | 0 | 80000 | 96000 |
| SQL逻辑行 | 8000 | 803150 | 971780 |
| 真实Control | 0 | 10 | 12 |

两次外层执行程序合计3.382885959秒；最终静态对账另记，不能把子程序、准备和外层耗时重复相加。已删除`/private/tmp/ti_d4_e48sup3u`，没有本轮存活请求/worker/连接需等待。真实请求尚未开始，不能把准备连接关闭当作完整请求清理验收。

## 收尾发现的既有测试丢失

误把既有文件当作新文件覆盖，删掉HEAD中的4个函数：

- `test_kernel_has_no_reverse_or_dg_dependencies`：Foundation不能反向依赖App/Biz/Ops/legacy/QTF/orchestrator/lake_console。
- `test_d1_import_requires_no_database_or_arrow`：不加载数据库、Arrow、orchestrator仍能导入D1合同、发现和配置。
- `test_d2_runtime_sql_resources_are_explicitly_declared_for_packaging`：来源SQL包资源声明与3份固定文件。
- `test_d3_fixed_sql_resources_and_output_dependency_boundary`：计算/输出SQL包资源及清单、输出模块不理解内部计划、已删除分页字段不能重现。

新的D4函数不能代替这些检查，且两个禁止列表漏了`lake_console`。这是本轮实现范围控制失误，不是原D1/D2/D3算法错误的证据。13函数通过记录保持原样，但必须限制其通过范围；不得用本次测试数量声称既有检查未受影响。

## 下一轮最小修复和续跑建议（尚未授权执行）

1. 先补原方案/LLD的修复和续跑细节：保留原累计费用与所有失败证据，只处理两项问题；不扩大到新算法、正式来源或压力场景。
2. 原样恢复HEAD中4个函数及常量，保留新增D4函数并补齐`lake_console`禁止项。先做逐函数静态diff；不自动重跑旧D1/D2/D3整组。
3. 按管理员本轮决定取消内存实测：后续修订诊断时移除RSS采集、内存采样线程及RSS通过门槛，改为引用LLD16.2估算。保留线程/连接/引用真实释放及其它验收，不再要求ps预检查。原失败与成本不删除，不把未测数值填0或标通过。诊断脚本本轮尚未修改。
4. 明确续跑入口如何保留失败台账、跳过已通过轻量项并运行尚未执行的7个节点。现有首错停止和重复执行保护不能靠删报告或清零绕过。
5. 重建来源需额外输入4000/SQL8000，使用已批准续跑预留；10次请求仍使用原正常安排。预计最终累计输入23000、定位80000、SQL819150、真实Control10，低于原总上限。费用测算不等于运行通过。
6. 恢复及续跑须再次获得管理员授权。首错停止规则继续有效；不自动提交、部署或进入后续接入。

本报告是暂停时的实现/测试对账，不是D4完成确认。
