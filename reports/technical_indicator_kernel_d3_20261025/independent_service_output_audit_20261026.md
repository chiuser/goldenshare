# D3 独立只读审计：服务、执行器与输出

审计时间：2026-10-26。当前分支 `dev-interface`，HEAD `ffaf701e9717f6c8895abd6536c8cde0e1664e61`。主体 D3 提交由任务指定为 `1fcac21a`，本报告结论来自当前代码和原方案/LLD，不采用旧完成报告作为实现证据。

## 结论

未发现可确认的 D3 运行实现错误；发现 1 项原 LLD 明确要求的 D3 验收缺项：直接 `calculate` 的库结果字节边界与超限后清理没有当前测试覆盖。现有辅助编码测试不能替代该调用边界。只读静态审计不能代替运行验收；没有执行 pytest、项目导入、SQL、构建、真实数据访问或修改仓库文件。

## 明确发现 F1：直接 calculate 的输出字节边界和清理缺少验收

- 定位：`tests/foundation/technical_indicators/test_d3_output_failures.py:122-138`；服务实际接线在 `src/foundation/technical_indicators/service.py:136-148`；库计量函数在 `output/encoding.py:75-84`。
- 触发条件：D3 需要证明直接调用 `TechnicalIndicatorService.calculate` 时，库格式结果恰等于小字节阈值允许、超 1 字节整次失败，并完成本次连接/表/Arrow 清理。无需真实取消、并发或 ASGI。
- 原本应怎样：LLD 第 18 节第 2010、2011 行两次明确要求上述直接调用级边界与超限清理断言。测试必须经过服务创建结果、`measure_result_utf8`、统一 finally，再验证返回/异常与清理。
- 当前实际：现有 `strict_utf8_boundaries` 只对小字典 `{msg:全部}` 调用 `encode_response_utf8`，验证辅助响应编码器。全部当前指标测试中搜索 `max_output_bytes|measure_result_utf8|encode_response_utf8`，没有直接 calculate 的小阈值调用，也没有由库计量超限引发的服务资源清理断言；`max_output_bytes` 仅在配置默认值等出现。
- 影响：不能据该测试证明纯库入口遵守字节上限和超限后清理。即便删掉 `service.py:140` 的调用、传错阈值，或将该检查移到统一 finally 覆盖之外，当前辅助函数测试仍会通过。当前源码有正确调用，故这属于验收缺项，不是已证实当前服务会错误返回或泄漏。
- 最小建议：复用原既定字面小夹具和可控时钟，在直接 calculate 路径补少于/恰等/超 1 字节三种边界；独立确定固定结果的 UTF-8 字节数，超限断言原 `ResourceLimitError`、不返回成功对象，并核连接关闭、表/Arrow清单和监控释放。沿原预算先更新具体验收安排，不新增长历史、真实 Control、D4 场景或产品代码。

## 依据与范围

- 已读根 `AGENTS.md`、`src/AGENTS.md`、`src/foundation/AGENTS.md`、`docs/architecture/subsystem-boundary-plan.md`；目标目录无更近 AGENTS。
- 原方案：`docs/architecture/technical-indicator-kernel-component-design-v1.html`，重点是输出、单连接生命周期及失败规则。
- 原 LLD：`docs/architecture/technical-indicator-kernel-low-level-design-v1.html` 的 04.3、04.4、04.5、07.5、11、13、14、15，以及 18、19.12、19.13、22 对当前步骤验收与边界的约束；不以 22.1 旧完成结论代替代码检查。
- 当前实现：`service.py`、`executor.py`、`contracts.py`、`execution_control.py`、`output/**`；为核实交接还读 `calculation/engine.py`、`calculation/sql_templates.py`。
- 相关测试逐项读源码，未运行：`test_contracts.py`、`test_empty_results.py`、`test_history_and_paging.py`、`test_indicator_literals.py`、`test_d3_output_failures.py`、`test_d3_required_acceptance.py`、`test_d3_engine_extension.py`、`test_errors_and_cleanup.py`、架构依赖/包资源测试。

## 逐项静态结论

| 要求 | 当前代码位置与判断 | 当前测试源码依据 |
| --- | --- | --- |
| 服务在 I/O 前创建独立输出说明，输出不理解计划 | `service.py:57-72,86-98` 从 plan 一次复制公开 ID、版本、补齐参数、字段；`output/contracts.py:25-30` 复制参数两层和字段 tuple。输出不导入 Plan/registry/engine。 | `test_d3_required_acceptance.py:54-72` 修改原列表及 pair 后说明不变；`tests/architecture/test_technical_indicator_dependencies.py:67-73` 静态边界守护。 |
| 空/非空结果使用同一说明；同参数两个 ID 不丢失 | `collector.py:63-81,96-115` 固定说明与别名；`result.py:86-104` 无论 rows 是否为空均按 instances 创建每列序列。 | 默认非空 `test_history_and_paging.py:51-53`；正常 0 根与前置历史存在但输出空 `test_empty_results.py:15-45`；相同 MA 两 ID 及不同参数 `test_indicator_literals.py:17-55`。 |
| 实际读取与输出范围、全局未知日期分开 | `service.py:136-139` 显式传同次 inputs.read_start/read_end；`result.py:38-64` 检查成对、周期类型、顺序和 source_rows；`result.py:112-124` history_start 固定未知 None、available_through 只取声明、range 只取最终 times。 | `test_history_and_paging.py:23-31` 10001/9001 与 1000 输出区别；`test_empty_results.py:31-45,77-84` 空范围及周起点/实际截止；`test_d3_required_acceptance.py:75-161` 非法交接与未知全局日期。 |
| 不多取一根，不发布 has_more/next_before | `retain_tail.sql` 直接按请求 limit 留尾，`select_result.sql` 升序取完整尾部；`OutputRange` 仅 3 字段 (`contracts.py:182-186`)；无额外探测字段。 | 架构测试 `test_technical_indicator_dependencies.py:74-80` 保护已移除字段。 |
| 先按 seq 检查字段、类型、漏行，再关联；保留合法 NULL | `collector.py:168-266` 按 ID、公开字段、seq 区间、pragma 列顺序/类型和范围内 count/distinct/min/max、范围外数量核对；借用价格表允许历史；`collector.py:268-298` 通过后关联且核输出行数；`result.py:86-104` 不替换数值 NULL。 | `test_d3_output_failures.py:36-62` 故意在真实结果表删列/行、改类型；`test_indicator_literals.py:33-42` 初始 NULL；`test_d3_engine_extension.py:209-224` 旧批拒绝；这里未据未运行代码声称已通过。 |
| 短批不作为 EOF；COUNT 与完整 fetch 一致 | `executor.py:212-285` 固定输出步骤、工作线程检查、互斥标记、字段顺序/类型、每批最多 8192、直到空、前后停止检查、保留 cause；`collector.py:363-381` 先核尾表 COUNT，再核完整取回量。 | `test_d3_output_failures.py:141-199` 将真实结果每次限制为 1 行，要求 4 次 fetch 取出 3 行，并注入第二次读取失败核 cause。 |
| UTF-8 流式计量、等于阈值允许、超限整次失败 | `encoding.py:49-84` iterencode 每块转 UTF-8、`total > max_bytes` 拒绝、计量不拼接完整 JSON；严格 JSON 不允许 NaN/未知对象；`service.py:140-148` 计量仍在统一 finally 内；`encoding.py:87-95` 内部响应编码只在完整结束后返回 body。 | `test_d3_output_failures.py:122-138` 含中文、等于/少于/多于小阈值、NaN/未知对象，但只经过响应辅助编码器；直接 calculate 的库结果边界/超限清理缺项见 F1。默认 5000000 在配置测试/配置合同中维护。未测量本次 RSS。 |
| 取消、超限保留错误；清理失败不能成功 | `executor.py:268-278` 已登记停止优先，内核错误原样保留，底层 OOM 映射资源超限；`encoding.py:69-72` 不捕获内核停止/资源错误；`service.py:32-43,142-150` 原错误加清理附注，正常路径清理错误提升 ResourceCleanupError。 | `test_d3_output_failures.py:65-119` 停止、读失败、输入超限、清理失败；`test_errors_and_cleanup.py:139-174` 原错误对象保留、其余资源继续释放、关闭失败不成功。 |
| 创建连接、清理、关闭由同方同线程顺序完成 | `service.py:103-150,152-191` 同服务创建与 finally 关闭；先 stop_monitor 再 engine/input/output，最后 close；`executor.py:39-43,304-332` 操作线程与 cleanup_ready 检查；`execution_control.py:130-167` 解绑并实际 join 后返回。 | `test_errors_and_cleanup.py:68-187` 连接/执行器/监控部分初始化失败、关闭顺序、错误优先、清理目标。完整运行取消仍属 D4，未扩称。 |
| 表改名先登记新名，失败两名可收尾 | `executor.py:76-94,106-128` 先声明新名，原生成功后先移除旧 live 名再停止检查；`collector.py:328-344` 先 own 新名，rename 正常后移除旧名，任何 append 错误设置 failed (`346-355`)。 | 现存 `test_table_rename.py` 为该通用方法的专门测试；本次静态核其服务/输出调用方式。 |
| 请求模板只读一次，部分加载失败可释放 | `sql_templates.py:40-66` 先核整份固定清单，命中仍检查停止，未命中按 UTF-8 读，读后检查通过才缓存；`engine.py:90-100` session 先登记后加载，`168-202` 无论 release 失败均清映射；`collector.py:83-94` 构造失败自行释放，`398-416` discard finally 清引用。 | `test_history_and_paging.py:56-86` 独立请求重新读取、每文件一次；`test_d3_output_failures.py:249-287` 第二输出文件失败；`test_d3_engine_extension.py:245-351` 缓存白名单、只读映射、第二模板后取消、重复 close。 |
| 结果与连接独立、msg 纳入合同与计量 | `executor.py:265-267` 返回 tuple；`result.py:80-124` 组装不可变日期/数值序列，不保存连接/游标；`contracts.py:169-218` tuple/frozen 合同；`service.py:140,145-150` 计量后只清理并返回。msg 在结果创建时固定，不在检查后改写。 | `test_contracts.py:157-166` 顶层字段与可变输入复制；空结果消息见 `test_empty_results.py:15-45`。 |
| 固定 SQL 包资源声明与实际清单 | `pyproject.toml:53-57` 打包来源、计算、输出三组 SQL；`output/collector.py:48-55` 与实际 3 文件相符；`sql_templates.py:13-25` 固定包/文件白名单。 | 架构测试 `test_technical_indicator_dependencies.py:53-66` 同时核声明与磁盘文件；此证据不等于实际构建/安装产物验收。 |

## 工具和文档核对

- CodeGraph 使用了 `codegraph_status`、`codegraph_search`、`codegraph_explore`、`codegraph_callers`。其 explore 覆盖服务到执行器/输出及来源/引擎入口，实际消费者再由 `rg` 核对。`callers(TechnicalIndicatorService)` 未返回调用方，因此没有用该空结果断言无消费者。
- Context7 先 resolve DuckDB，再 query `/duckdb/duckdb-python` 与 `/duckdb/duckdb-web` 的官方 DB-API/result docs。确认 fetchmany 为下一批结果、description 提供列说明；未据当前文档替代目标 1.5.5 的运行验证。
- 官方文档出处：<https://github.com/duckdb/duckdb-web/blob/main/docs/current/clients/python/reference/index.md>、<https://github.com/duckdb/duckdb-web/blob/main/docs/current/clients/python/dbapi.md>。

## 限制

1. 本次只审 D3 服务/输出相关实现与测试源码，不对整个 D3 算法公式作独立数值认证。
2. 没有执行任何测试或 SQL，没有重用旧验收报告断言当前测试已通过，也未核对临时参考数据或正式数据。
3. D4 并发、RSS、完整真实取消、ASGI/发送及退出不在本次范围；API/页面迁移与 DG 退出属于另行获准的阶段，未将其未实施列为 D3 缺陷。
4. F1 是原既定 D3 验收未覆盖的边界；不应据此推定当前实现有泄漏，也不应扩大到 D4 或增加未经批准的执行。
