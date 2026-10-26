# D3 第二轮独立只读审计：服务、执行器、输出与输入交接

审计基线：`dev-interface`，HEAD `e591b7eca73a04e6ed5f730d6e06bd28eb6470a9`。只读当前源码、原方案和原 LLD、测试源码；未执行 SQL、pytest、项目导入或读取正式数据。没有修改仓库文件。保存的运行明细只用于确认既有测试确实执行到其断言，不以旧完成/审计报告证明实现正确。

## 结论

负责范围未发现可确认的新 D3 实现缺陷。后续专项核对发现一处既定验收缺口：最终 fetch 与 COUNT 不符或超过 max_rows 的拒绝分支已实现，但缺少反向运行证据，详见文末补充。下表的“静态正确”仅表示当前分支源码与原 LLD 对应，不代替本轮未运行的测试或 D4 验收。

## 逐项核对

| 核对项 | 当前源码与判断 | 测试位置及证据性质 |
|---|---|---|
| 请求、参数、依赖与输出说明先于来源读取 | `service.py:85-102` 先归一化、展开依赖、复制不可变说明、汇总历史，再 describe；`output/contracts.py:25-30` 复制参数两层和字段 tuple。collector 不接收计算计划、注册表或 source。静态符合 LLD 04.3/04.5。 | `test_d3_required_acceptance.py:54-72` 外部修改参数及字段列表后说明不变；有冻结字段断言。 |
| 输入/计算/输出/历史先后顺序 | `service.py:113-126` 先输入准备/engine.prepare；每批 consume、完整输出检查/保存尾部后才保留输入历史，再反向释放节点批表，最后 finish_batch。没有预取。正常 EOF 才 engine.finish。静态符合 LLD 11。 | `test_history_and_paging.py:56-86` 10001 与 9001 两请求、一来源 open、8192 满批与尾批；`test_d3_engine_extension.py` 有依赖消费/释放事件顺序。 |
| 实际读取范围、分页与空结果 | `sources/session.py:127-138` 在已物化原批记录实际 min/max；`service.py:136-139` 必填命名参数直接交接；`output/result.py:36-64` 检查 None 成对、周期类型、归一时区后比较顺序/数量；`output/result.py:112-124` history_start 保持 None，available_through 仅沿用来源，count/times 分离，before 且空时固定 msg。`collector.py:300-315,317-343` 请求条件绑定、保留最近 limit，最终升序。静态符合 LLD 04.5、14.2/14.5。 | `test_history_and_paging.py:23-53,76-86` 独立页边界和读取范围；`test_empty_results.py:15-45` 0 来源、21 历史但 0 输出；`:48-84` 当前周 source_as_of；`test_d3_required_acceptance.py:75-161` 合法时区/范围和既定错误反例、未知全局日期不回填。 |
| 合法 NULL 与缺行 | `collector.py:168-266` 先核 ID、字段、类型和本批范围，每唯一表/字段组合只核一次；通过元数据和五项 seq 汇总检查缺行、重复、越界及 NULL seq；借用 price 允许前置历史。随后 `:268-298` 显式关联并核新行数量，没有靠关联 NULL 掩盖缺行。合法值 NULL 不额外清洗。静态符合 LLD 14.4。 | `test_d3_output_failures.py:36-62` 真实计算后删字段、删 seq=2 或改 VARCHAR 的故意反例，整次失败；`test_indicator_literals.py` 保留窗口前置 NULL 的独立字面断言。 |
| 完整 fetch 和错误优先级 | `executor.py:212-285` 同一工作线程及 `_executing`；列名/顺序/类型固定；fetchmany(8192) 每次前后检查停止，直到空，累计超 max_rows 立即失败，返回 tuple(tuple)；原停止/资源错误不改写为读取错误。`collector.py:364-381` COUNT 与完整读取数量一致才组装。静态符合 LLD 14.5。 | `test_d3_output_failures.py:141-199` 真实 SQL 游标每次只返回一行，要求四次 fetch 后完整三行；第二次 fetch 故意失败时保留 OutputReadError/fetch_failed/final_fetch 与 cause。 |
| 结果关闭后独立 | `output/result.py:79-103` 只从已取回 tuple 组装不可变字段数组；`contracts.py:177-179,214-218` 复制结果容器；`service.py:140-150` 字节计量后清理，再返回。结果中无游标、Arrow 或连接。静态符合 LLD 14.1。 | 新调用级字节测试在 state.run 已关闭服务后用标准库完整转换/编码结果，并探测真实连接确实 closed。 |
| 超限、停止和清理 | `service.py:142-150,165-191` 保留主 BaseException；先停止中断监控，engine/input/output 逐项清理，再关闭连接；一个清理错误不跳过其余项；原正常路径任一清理错误拒绝成功。`executor.py:304-344` 清理只接已登记资源，停止后不再普通 check_active，实际释放成功才去 live 清单。静态符合 LLD 11/11.1。 | `test_errors_and_cleanup.py:68-187` 连接/监控/执行器部分初始化、清理顺序、清理错误继续、主异常优先和关闭错误；`test_d3_output_failures.py:65-119` 停止/读取失败/输入超限/清理错误不变空成功。替身边界均明确，不能称完整真实取消验收。 |
| rename 与资源登记 | `executor.py:76-139` rename 先登记目标；原生 SQL 成功后、停止检查前退旧 live 名；driver 失败保留两名供 IF EXISTS 清理。`sources/session.py:173-190` 和 `collector.py:338-343` owner 在成功后退 next 名。静态符合 LLD 04.4。 | `test_table_rename.py:111-234` 真实临时 SQL，失败在 rename 前/后、取消及历史尾部小样本；故意停止替身不冒充真实中断。 |
| 单请求固定 SQL 文本 | `calculation/sql_templates.py:13-66` 两固定包与 7+3 精确文件白名单，先核整类清单再查请求字典，命中仍检查停止；`engine.py:77-100` 先保存 session 再加载/prepare；`engine.py:168-202` 清理错误时也 finally 清文本；`collector.py:83-94,398-416` 构造失败与 discard 都断引用。静态符合 LLD 07.5；D2 三来源 SQL 不在本次迁移/计数范围。 | `test_history_and_paging.py:59-86` 观察 io.open 的每份文件一次、下一请求重新读；`test_d3_engine_extension.py:245-351` 未知已缓存文件拒绝、只读映射、第二文件返回后取消不入字典、清理失败仍释放文本及重复 close；`test_d3_output_failures.py:249-287` 路径越界在文件访问前拒绝、输出第 2 文件失败构造自清。 |
| 7+3 SQL 资源交付 | 当前 calculation/sql 实有 7 份、output/sql 实有 3 份；输出三文件与 LLD 21.6 的新行合并/限尾/显式升序选择对应。`pyproject.toml:55-57` 同时保留 source 和 calculation/output sql/*.sql 包资源声明。静态符合。 | `test_technical_indicator_dependencies.py:53-80` 精确文件集合、资源声明、输出不 import plan/registry/engine 和删除的旧分页字段；仅静态检查，不冒充 wheel 构建/安装验证。 |

## 原 F1 的独立复核

原 LLD 19.29（当前 HTML 第 2722 行起）的三次固定调用要求与 `test_d3_calculate_output_bytes.py:22-207` 一致。测试用独立完整 JSON 字面和三个指定文件 stat 构成 B；不调用被测编码器或结果映射器生成 expected。产品 source/Arrow/SQL/encoding/close 保留，只冻结 D3Control 时钟；外层预算仍实测。

已读取原始测试 stdout、execution 记录及 calculate_output_bytes_details 明细：1 passed，程序 returncode=0、1.634241874795407 秒。独立完整结果 B=1205；max_output_bytes=1206/1205 时逐字节相等并返回，1204 时精确 ResourceLimitError、未返回、无清理附记。三次均读 3 根、一批、一次 open、38 逻辑行、live 表/Arrow 空、cleanup_ready=True，并通过真实关闭连接 SELECT 1 拒绝探测。测试内调用增量 9 来源行/117 逻辑行/0 真实 Control，夹具 COPY 另 3 行，执行汇总 120 符合 19.29。故不重复报告原 F1。

## CodeGraph 与边界

已用 codegraph_explore 审 service、executor、collector 相关源码和调用；codegraph_callers 对 OutputCollector/build_result 未返回结果，因此补当前源引用核验。新结果合同实际生产构造点为本库 output/result.py，服务为 collector 唯一产品调用者；现行 API/页面未被此次合同替换。未把图索引无调用结果当成无消费者的证明。

D4 并发、RSS、ASGI、完整真实取消，正式 API/页面、XXM 和 DG 退出不列为 D3 问题。本轮没有重新执行既有验收，也没有新增猜想测试要求。工作区存在其它主题脏文件，未触碰。

## 后续专项核对：最终 fetch 数量的反例尚未覆盖

原 LLD 14.5（HTML 1563—1564 行）明确要求：累计多于 max_rows 立即 OutputContractError；最终取回数量必须与预先读取的 COUNT 一致，不符则整次失败。当前 `executor.py:248-260` 已有超 max_rows 的拒绝分支，`collector.py:370-381` 已有 COUNT 与最终 len 核对，因此这是静态已实现、反向未测，不是已确认实现错误。

`test_d3_output_failures.py:141-186` 只覆盖 3 行/max_rows=3、每次返回 1 行直到正常 EOF，以及第 2 次 fetch 抛 OSError（应为 OutputReadError/fetch_failed）。`:39-62` 的删行故障在 append 时已经被 seq 检查拒绝，不能证明最终 COUNT=3 而 fetch=2 的检查会生效。`test_d3_engine_extension.py:196-199` 同样是 3 行/max_rows=3 的正常读取。新 required_acceptance 检查读取范围/说明合同，calculate_output_bytes 检查 UTF-8 字节上限，都没有替代最终取回数量的反例。

对当前 tests/foundation/technical_indicators 的只读检索未见 fetch_count_mismatch 断言或触发这两个最终数量分支的输入。无需因此扩展为全部 reason 矩阵，但不能以正常完整读取、读取异常或 append 前缺行测试宣称这条最终完整性拒绝要求已验收。先前“未找到既定验收遗漏”的表述据此收窄。
