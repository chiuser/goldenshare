# 2026-10-29 Silver复权因子修正完成报告

本轮已完成获准的Silver因子代码修正、隔离验证和正式因子修复，停在股票分钟链补数之前。没有执行分钟QFQ、因子repair、MACD/KDJ或九转，没有进行分钟历史读取；不代表10月28日全部DG数据集已经补齐。管理员已批准提交本轮实现、测试及执行材料，其他工作区改动不纳入；不推送。

依据：[资产设计§15](../../docs/design/dagster-adj-factor-asset-design.md#adj-factor-retired-retention-plan-20261028)、[原修复LLD §25](../../docs/design/dagster-stock-adj-factor-history-repair-low-level-design-v1.md#adj-factor-retired-retention-20261028)。管理员批准“完成silver复权因子的这一处修正，停在股票分钟链补前”，并允许仅恢复本次被过滤的九条旧记录。

## 1. 结果和逐日运行

旧规则随当前上市名单重写因子，301139.SZ于28日退市后，其15—27日九条仍被历史行情需要的因子被删。现在因子存储允许保留已知CNY L/D源记录，28日及以后按Raw允许集合完整生成；旧日期不全量重建，只补明确缺失键。repair仍由目标业务日在市范围决定，保留退市日及以后的源因子不扩大计算股票池。

正式执行于2026-10-29 08:32:42—08:35:14，全部通过原`silver_adj_factor_update_job`逐日启动，前一日成功及原检查通过后才启动下一日。共10次SUCCESS，40项原检查全部通过，逐条绑定相应真实物化；无失败、无自动重跑。

| 业务日期 | Run ID | Silver最终行数 | 301139.SZ因子 | 结果 |
| --- | --- | ---: | ---: | --- |
| 2026-10-15 | `54a13ad7-8984-4c9d-9bc5-019172c2ec05` | 5,573 | 1.0079 | SUCCESS / 4项通过 |
| 2026-10-16 | `8a1292c1-5eba-4dbb-a863-84dbeba2394b` | 5,574 | 1.0079 | SUCCESS / 4项通过 |
| 2026-10-19 | `2c48db76-9c8d-4f90-9d14-3761b92ab3dd` | 5,574 | 1.0079 | SUCCESS / 4项通过 |
| 2026-10-20 | `a8105a0c-72c0-4b06-bf87-675da35ff794` | 5,574 | 1.0079 | SUCCESS / 4项通过 |
| 2026-10-21 | `52dd4c77-4f1a-4967-bb94-3b33a3c0f7bc` | 5,575 | 1.0079 | SUCCESS / 4项通过 |
| 2026-10-22 | `f226c961-f73f-40d5-a36b-ab0023f775c2` | 5,576 | 1.0079 | SUCCESS / 4项通过 |
| 2026-10-23 | `2e05d42f-a828-4143-b41a-d413428a604f` | 5,577 | 1.0079 | SUCCESS / 4项通过 |
| 2026-10-26 | `5606b57c-d8af-4b65-b3d9-d17700311837` | 5,577 | 1.0079 | SUCCESS / 4项通过 |
| 2026-10-27 | `c238fb7e-3c86-405d-9c26-be132b4fb944` | 5,577 | 1.0079 | SUCCESS / 4项通过 |
| 2026-10-28 | `de9b3d56-0f19-4566-963a-2db1d8882ab0` | 5,580 | 1.1319 | SUCCESS / 4项通过 |

九个旧日各仅插入一条1.0079；候选提升前对旧文件三列schema和其他行逐字段核对，保持原样。28日由5,576变为5,580行，新增4条均为28日Raw实际提供且新规则允许的行；该股1.1319得到保留，不是恢复其他股票旧历史。10份Raw和生命周期文件摘要与预检一致。没有Tushare请求、Prod写入或周/月重跑。

[逐日请求、状态、物化、检查、计数和提交回执](execution-result.json)；[预检输入身份及合同](formal-preflight.json)；[最终运行与开关只读快照](final-runtime.json)。这些物理计数和检查在每个job后完成一次，收尾复用证据，没有重复扫描所有分区。

## 2. 代码和计划对账

| 改动 | 实现位置 | 边界 |
| --- | --- | --- |
| 允许保留、最低覆盖和repair对象分别判断 | `defs/run_contracts/adj_factor.py`、`defs/duckdb_sql.py`、正式checks及readiness | 单一28日分界；不改变Raw合同、生命周期事实及普通QFQ价格核 |
| 旧日定点恢复及安全写入 | `defs/assets/adj_factor.py`、`defs/io/adj_factor_silver_candidate.py`、`defs/io/adj_factor_silver_publication.py`、`defs/paths.py` | 原Silver job增加默认空列表的明确恢复键配置；staging候选完整校验后同设备原子提升，逐文件回执；非清单差异、异值、源/目标变化、并发均停止 |
| 原生中断恢复 | asset使用root run id；publication保留planned/prepared/committed及目标身份 | 文件已替换而回执失败时，重执行从恢复判断开始；只提升一次，不重新计算完成候选；正式本批未发生中断 |
| repair共享调用方同步 | 分钟/日线planner、executor、hash及sensor；周/月builder参数 | 目标日早于真实退市日才参与；D无退市日期保留因子但单列诊断，不视为永久在市；真正缺前因子仍阻断；保留周/月原收口及恢复规则 |
| 防止旧删除规则再写入 | 因子sensor及原历史工具 | 28日前普通整分区重建拒绝；旧删除型工具仅保留历史读材料，不继续运行旧写入 |

详细硬口径、真实代码点、测试映射在LLD §25.10。CodeGraph使用status/explore/impact/callers核对消费者，并sync确认；动态路径由当前源码补核。没有新增asset/job/check/分区、环境配置、前端/API、Prod或跨工程契约变更；没有变化的公式未借此重写。

## 3. 验证及其边界

| 验证组 | 结果 | 证据 |
| --- | --- | --- |
| 保留/覆盖规则、正式checks/readiness、sensor、旧工具 | 80项及18个子测试通过 | [rules-tests.xml](rules-tests.xml) |
| 相关静态契约 | 5项通过 | [static-tests.xml](static-tests.xml) |
| repair消费者及原日线/周月相关回归 | 166项及12个子测试通过 | [repair-consumer-tests.xml](repair-consumer-tests.xml) |
| 候选、故障、锁、原生job及FROM_FAILURE恢复 | 合并24项通过 | [writer-native-tests.xml](writer-native-tests.xml)、[原生重执行证据](native-reexecution-evidence.json) |
| 原周/月临时HTTP源、DG/CLI、取消/退出/续跑及交接 | 隔离集成通过；请求和写入均为临时夹具 | [集成证据](repair-consumer-http-integration.json) |
| Definitions加载 | 临时DAGSTER_HOME验证通过，目标job只执行1个Silver asset | LLD §25.9 |
| 正式因子执行 | 10原job成功，40项原检查及有界物理核对通过 | [execution-result.json](execution-result.json) |
| 独立复审 | 代码/已有证据复核，无收尾阻断 | [复审记录](independent-closeout-review.json) |

各测试组有覆盖重叠，不相加宣称独立用例数。所有有效隔离测试明确使用临时Lake/staging、DuckDB临时目录及DG资源；初轮遗漏隔离的通过结论已经撤回，受影响测试均重新验证。曾有较宽performance文件因既有`stock_suspend_confirmed_test_support`导入失败而未收集成功，未作为通过证据；本轮必要的10日×5,000股有界batch及查询量验证通过。repair消费者默认Ruff存在未改行的`date.today()` DTZ011提示，未改其时间语义；相应E9/F/I/UP和本轮writer静态检查通过。

只读预检覆盖Raw真实三列、Silver三列DATE合同及九条真实因子值；生命周期使用现行10列生产者合同，实物预检核对本次所需的身份、状态、上市及退市日期，归档预检不声称保存了完整10列实物schema清单。隔离回归证明禁止路径不发生；正式执行证据只证明这10个因子分区，不冒充分钟历史或其他数据集验收。

## 4. repair名单只读确认

08:37仅使用27/28日小因子及生命周期，原builder计算的分钟与日线因子变化名单相同，均16股；新上市0、无法判断0、缺前日因子0，301139.SZ在28日已退市，未被加入repair。完整名单见[repair-scope-readonly.json](repair-scope-readonly.json)。没有人工修改名单、执行repair或读取价格历史；后续仍须由原job在真实执行时生成名单。

## 5. 开关、读写和清理

正式开发前保存8项相关sensor原RUNNING状态并临时停止，防止工作区代码生效或因子更新时自动跨过用户停点。只重载`orchestrator`代码位置，没有重启DG/daemon；没有修改cursor、runless事件、动态分区、并发、内存或时间限制。

因子完成后恢复这3项原RUNNING状态：`silver_adj_factor_update_job_sensor`、`gold_stock_daily_qfq_update_job_sensor`、`gold_stock_daily_qfq_factor_repair_job_sensor`。08:39最终只读核对通过，其他记录到的开关未变。

以下5项分钟链sensor保持STOPPED，以落实管理员指定停点：

- `stock_mins_qfq_daily_sensor`
- `gold_stk_mins_qfq_macd_kdj_repair_job_sensor`
- `gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor`
- `stock_mins_qfq_factor_repair_sensor`
- `gold_stk_mins_qfq_nineturn_update_job_sensor`

TODO：管理员后续继续推进分钟链时，先核清原job生成的实际名单、历史读写范围及已有授权，再按QFQ日更→因子repair→MACD/KDJ日更→指标repair→九转顺序推进，并恢复上述5个sensor。当前不自动启动它们。

本轮正式输入21文件、1,242,729B约1.19MiB。批准方案的预算为读32MiB、写4MiB、额外空间4MiB，包含最多一次仅未完成项恢复及最后验收；实际未发生续跑。没有采集底层实际I/O字节，预算不能称为实测值；未增加额外性能样本或运行限制。

5个合成测试目录和7个临时控制/编排文件已按精确清单清理，测试目录释放1,777,355B。触发脚本逐字节归档为[execute_factor_jobs.py.txt](execute_factor_jobs.py.txt)，SHA256为`f2956c1a864f7f8f484f22c0295b82551cef303d620ede4715287e8f6f0b855a`，原可执行临时脚本已删除。只归档和清理本轮自己的文件，未删正式Lake、staging提交/恢复记录或锁文件，未清共享缓存，未安装或卸载依赖。

开关及清理证据：[初始状态](initial-runtime.json)、[维护开关](maintenance-sensors.json)、[恢复三项sensor](sensor-closeout.json)、[最终状态](final-runtime.json)、[本轮精确清理清单](cleanup.json)、[消费者测试清理](repair-consumer-test-cleanup.json)。代码位置证据：[重载前](code-location-before-reload.json)、[重载请求](reload-result.json)、[重载后](code-location-after-reload.json)。

最后的本地收尾验证通过：仓库文档完整性、所涉改动空白检查、三份文档引用、精确清理路径和脚本归档摘要。仍在dev-interface；没有新增正式数据读取或运行。见[本地验证记录](final-local-validation.json)。
