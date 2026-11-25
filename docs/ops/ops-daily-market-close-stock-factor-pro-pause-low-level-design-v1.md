# 每日收盘后维护临时移除股票技术面因子 LLD v1

日期：2026-11-25（Asia/Shanghai）。

状态：设计待审阅，未开发、未部署、未执行生产任务。依据[配套方案](/Users/congming/github/goldenshare/docs/ops/ops-daily-market-close-stock-factor-pro-pause-plan-v1.md)和[工作流开发说明模板](/Users/congming/github/goldenshare/docs/templates/workflow-development-template.md)编写；本 LLD 不是生产执行授权。

## 1. 目标与基本信息

| 项目 | 内容 |
| --- | --- |
| Workflow key / 显示名 | `daily_market_close_maintenance` / 每日收盘后维护 |
| 管理员确认范围 | 临时从该工作流移除股票技术面因子（专业版）`stk_factor_pro`，保留股票复权因子 `adj_factor`。 |
| 实现目标 | 不进入股票技术面因子及其附加单股历史回刷，继续执行后面的原有步骤。 |
| 原有工作流的用途 | 按盘后顺序维护多个不同数据集；本次只调整其中一个成员，不新建工作流或任务类型。 |
| 实施与验收责任 | 由管理员指定；本次没有生产执行人或运行时间安排。 |
| 业务代码位置 | `src/ops/action_catalog.py` 的 `WORKFLOW_DEFINITION_REGISTRY["daily_market_close_maintenance"].steps`。 |
| 测试位置 | `tests/test_ops_action_catalog.py`、`tests/web/test_ops_runtime.py`、`tests/web/test_ops_catalog_api.py`；独立能力回归复用既有 planner/writer 测试。 |

本次没有 `DatasetDefinition`、`DatasetExecutionPlan`、源字段、日期语义、API/CLI 输入格式、数据库 schema 或数据写入规则变更，也不迁移数据。后续原有步骤仍按自身合同访问和更新 Prod 数据。

## 2. 当前实现、影响面与不修改的位置

| 环节 | 真实入口与行为 | 本次处理 |
| --- | --- | --- |
| 定义 | `_dataset_workflow_step` 从数据集事实源取得动作与显示名称，steps 含股票技术面因子。 | 只注释该 steps 元素，保留 helper。 |
| 执行 | `TaskRunDispatcher._dispatch_workflow` 取得代码定义并逐项执行，创建 `node_type=workflow_step` 节点。 | 保持串行分发与失败规则；不新增按股票技术面因子名称判断的跳过分支。 |
| 单日计划 | `_build_stk_factor_pro_units` 先生成当天单元，再调用 `_build_stk_factor_pro_adj_factor_refresh_units`。 | 不修改。独立维护仍可能触发历史回刷。 |
| 单股历史范围 | `_load_stk_factor_pro_raw_start_dates` 查询变化股票现有原始库存最早日，生成至目标日的单股范围。 | 不修改股票名单、历史起点、分页、并发或超时。 |
| 目录 API | `OpsCatalogQueryService.build_catalog` 分别生成数据集动作与工作流列表；工作流 steps 直接来自定义。 | 工作流响应少一个成员，结构和独立动作保留；不修改 schema。 |
| 调度与手动入口 | `TaskRunCommandService` 和自动任务能力解析通过同一 workflow key 取得定义。 | 保持 `ops.schedule.target_type=workflow`、`target_key=daily_market_close_maintenance`；不改配置行。 |
| 前端 | `frontend/src/shared/api/types.ts` 声明目录结构；`ops-v21-task-auto-tab.tsx` 消费返回的 workflows。任务记录读取既有 TaskRun/节点。 | 不增加前端开关或硬编码过滤，不删除历史节点。 |
| 下游任务 | 板块分析/板块热度检查各自必需节点，不要求股票技术面因子节点。 | 保留现有上游条件，不放宽日期、时间窗口、输入完整性或成功证据。 |

跨子系统依赖方向不改变。CodeGraph 已核对 `_dispatch_workflow` 与 `get_workflow_definition` 的影响面，随后读当前源码补齐数据集动作、API、前端、测试和下游消费者。没有用图中同名 `build_plan` 等不确定边替代实际代码。

## 3. 具体改动

实施时在原位置保留注释行，拟议差异如下；本段只是设计，本轮未改源文件：

```diff
             _dataset_workflow_step("cyq_perf", "cyq_perf"),
-            _dataset_workflow_step("stk_factor_pro", "stk_factor_pro"),
+            # 2026-11-25 临时移出盘后流程，避免单股历史回刷阻塞；恢复条件见
+            # docs/ops/ops-daily-market-close-stock-factor-pro-pause-plan-v1.md。
+            # _dataset_workflow_step("stk_factor_pro", "stk_factor_pro"),
             _dataset_workflow_step("stk_limit", "stk_limit"),
```

只影响加载新定义后开始分发的任务。该工作流的手动任务、自动任务与重新提交的任务都使用同一成员清单；不能将变更描述为只对 24 日或只对自动触发生效。原任务已取得的 steps 不会被这条注释中途替换。

## 4. 调度、参数与目标步骤清单

保持 `manual_enabled=True`、`schedule_enabled=True`、`workflow_profile=point_incremental`、`time_regime=trade_open_day`、`default_schedule_policy=trading_day_close`、默认失败策略 `fail_fast`。`resume_supported=True` 是已有声明，当前分发循环没有读取成功步骤并自动跳过的通用实现，本方案不据此承诺续跑。

参数仍为处理日期 `trade_date`、开始日期 `start_date`、结束日期 `end_date`，均为既有可选日期参数；实际请求使用现行单日或区间输入。补 24 日必须显式指定 `2026-11-24`，不能使用“最新交易日”的默认值替代。

下表为**实施后的目标 27 步**。当前仍是 28 步，其中股票技术面因子位于每日筹码及胜率之后。

| 目标序号 | step_key | 数据集完整名称 | action_key |
| --- | --- | --- | --- |
| 1 | `daily` | 股票日线 | `daily.maintain` |
| 2 | `stk_auction_o` | 股票开盘集合竞价 | `stk_auction_o.maintain` |
| 3 | `stk_auction_c` | 股票收盘集合竞价 | `stk_auction_c.maintain` |
| 4 | `adj_factor` | 复权因子（股票） | `adj_factor.maintain` |
| 5 | `daily_basic` | 每日指标 | `daily_basic.maintain` |
| 6 | `bak_basic` | 股票历史基础列表 | `bak_basic.maintain` |
| 7 | `cyq_perf` | 每日筹码及胜率 | `cyq_perf.maintain` |
| 8 | `stk_limit` | 每日涨跌停价格 | `stk_limit.maintain` |
| 9 | `stock_st` | ST股票列表 | `stock_st.maintain` |
| 10 | `limit_list` | 每日涨跌停名单 | `limit_list_d.maintain` |
| 11 | `suspend_d` | 每日停复牌信息 | `suspend_d.maintain` |
| 12 | `top_list` | 龙虎榜 | `top_list.maintain` |
| 13 | `block_trade` | 大宗交易 | `block_trade.maintain` |
| 14 | `fund_daily` | 基金日线行情 | `fund_daily.maintain` |
| 15 | `fund_adj` | 基金复权因子 | `fund_adj.maintain` |
| 16 | `ths_daily` | 同花顺板块日线行情 | `ths_daily.maintain` |
| 17 | `dc_index` | 东方财富板块列表 | `dc_index.maintain` |
| 18 | `dc_member` | 东方财富板块成分 | `dc_member.maintain` |
| 19 | `dc_daily` | 东方财富板块日线行情 | `dc_daily.maintain` |
| 20 | `ths_hot` | 同花顺热榜 | `ths_hot.maintain` |
| 21 | `dc_hot` | 东方财富热榜 | `dc_hot.maintain` |
| 22 | `limit_list_ths` | 同花顺涨停名单 | `limit_list_ths.maintain` |
| 23 | `limit_step` | 连板梯队 | `limit_step.maintain` |
| 24 | `limit_cpt_list` | 涨停概念列表 | `limit_cpt_list.maintain` |
| 25 | `kpl_concept_cons` | 开盘啦板块成分 | `kpl_concept_cons.maintain` |
| 26 | `irm_qa_sh` | 上证E互动问答 | `irm_qa_sh.maintain` |
| 27 | `irm_qa_sz` | 深证互动易问答 | `irm_qa_sz.maintain` |

所有保留步骤均由现行 helper 生成，`depends_on=()`、`default_params={}`、`params_override={}`、`failure_policy_override=None`、`max_retry_per_unit=2` 沿用当前类型默认值。2 是既有字段声明，不代表 dispatcher 已实现每步自动重试两次。不新增依赖边，先后关系继续由 steps 顺序决定。

28 → 27 的计算依据是 2026-11-25 当前源码中的 28 个步骤减去股票技术面因子这 1 个步骤，不以旧目录曾列出的 29 步作为基数。

### 参数传递

沿用 `task_run.request_payload_json → step.default_params → step.params_override` 的后者覆盖规则。本工作流各步骤两个覆盖字典均为空，因此父请求的 `time_input`、`filters` 不被步骤覆盖。例如父请求明确指定 `time_input={"mode":"point","trade_date":"2026-11-24"}`，每个保留步骤继续接收该单日意图，再由各自 resolver 归一化。

本次全部保留项仍是 dataset action，经 `_step_task_run → _build_dataset_action_request → DatasetActionResolver.build_plan → _run_dataset_action_plan` 执行；没有新增 maintenance action 分支。运营输入不能直接冒充 Tushare 请求参数。

## 5. 配置、读写与并发边界

- 新增配置、数据库迁移、数据表、后台进程、队列和对外开关均为 0。工作流执行时的读写成本来自保留步骤，不在本次重写。
- 工作流不再计划或写入 `raw_tushare.stk_factor_pro`。该表已有数据和 `core_serving.equity_factor_pro` 视图保留；独立维护动作继续使用 `raw_only_upsert`，视图读取原始表。
- 股票复权因子 `raw_tushare.adj_factor`、`core.equity_adj_factor` 继续使用现行维护实现。其源端历史更正范围不由本变更自动修复。
- TaskRun、节点、issue 和 snapshot 的观测边界保持原合同，不写“跳过成功”的虚假股票技术面因子节点，不删除旧任务或旧节点。
- 不假设生产不存在股票技术面因子的独立活动任务或自动配置。发布前只读核实相关 `ops.schedule`、`ops.task_run` 及目标工作流状态；如仍有独立历史回刷占用通用 worker，单独列明影响并按获准范围处置。
- 生产读取按明确任务 ID、workflow/dataset key、目标日期及投影字段限定；不导出配置敏感值，不读取全量股票复权因子或历史股票技术面因子明细。

## 6. 失败、中断与重新提交

保留步骤失败时沿用 `fail_fast`，后续停止，已有成功步骤不自动补偿。整体成功与失败状态继续由 dispatcher 和 worker 汇总。本方案不通过 `continue_on_error` 隐藏股票技术面因子的长耗时，也不伪造已完成记录。

旧任务处理顺序：记录实际任务 ID、当前步骤和已提交业务事实 → 获准后请求停止 → 检查任务、活动节点和 worker 实际退出情况 → 按获准发布方式加载新定义 → 新建明确日期的任务。只看到 `canceling` 不算退出；停止等待时间未知时不自行强杀。

股票技术面因子的现行串行执行在每个单元开始前检查取消，普通源下载未注入金融报表那套可中断 control，不能承诺任意分页都即时停下。`_process_fetched_unit` 在单元写入后提交，停止不撤销此前已经提交的数据。

`_dispatch_workflow` 的取消异常存在按错误和提交进度分支处理的差异；worker 也只在特定 outcome 下将请求停止映射为 `canceled`。因此生产终态及当前节点须实际读回，不保证仅调用停止接口就得到一致终态；若不一致，记录为既有问题，不在本次移除中顺手修改状态机。

新任务按新定义从第一步执行。`resume_from_step_key` 在过滤字段中被保留，不等于分发器实现了从指定节点续跑；不得据此写执行脚本。重新提交的工作量包含先前成功的保留步骤，不能只预算后续步骤。

## 7. 性能预算与最后验收成本

| 范围 | 本次可证明的量 | 发布前或运行后必须补充 |
| --- | --- | --- |
| 编排开销 | 保留 27 个 workflow step，正常成功时最终 `unit_total` 按 `len(workflow.steps)` 为 27；不新增长期内存或扫描。 | 剩余步骤耗时依源调用、分页和现有写入情况确定，不能保证在某个秒数内结束。 |
| 股票技术面因子开销 | 该工作流触发的股票技术面因子计划、源请求和写入均为 0。 | 全系统独立任务不在这个 0 的范围内。 |
| 停止与重新提交 | 沿用既有取消点；新建任务需重新执行保留步骤。 | 旧请求结束时间、已提交数据、重复请求与写入成本尚未实测；确认范围后再执行，不附加无依据超时阈值。 |
| 目录与任务验收 | 核对目标工作流定义、目标新任务与其节点，不扩大为全任务历史扫描。 | 记录实际请求数量、结果数量与耗时，节点结果不替代业务数据验收。 |
| 业务数据验收 | 目标为 2026-11-24；先计数及有界样本，再用各数据集现行规则判断应有对象、合法空结果和业务日期。 | 逐项缺口、采样量与查询成本在执行前据实际表与索引确定，不能先写固定全市场读取量。全局明细仍需专项审批。 |

若单独补当天股票技术面因子，使用已有区间 `2026-11-24` 至 `2026-11-24`；在该日经现有日历确认为开市日的前提下，planner 生成 1 个日期单元，请求参数为 `trade_date=20261124`。1 是日期单元数，不是源 API 总请求次数；分页仍由原合同决定。该路径依据 `_resolve_run_profile`、`_stk_factor_pro_params` 和既有同日区间测试，不新增绕过参数或降低数据检查。

## 8. 实施测试与验收清单

下列项目是下一步开发的验收要求。本轮仅编写文档，不把待改测试写成已通过。

| 验收点 | 实现位置 / 必要断言 | 独立依据与边界 |
| --- | --- | --- |
| 只移除正确步骤 | 调整 `tests/test_ops_action_catalog.py::test_workflow_time_contracts_match_step_requirements`，按 §4 字面清单断言完整有序结果；显式断言股票复权因子在、股票技术面因子不在。 | 清单来自当前 28 步及管理员确认移除项，不能从修改后的 steps 动态生成 expected。 |
| 独立动作保留 | 在目录测试中断言 `stk_factor_pro.maintain` 仍可手动、自动维护；数据集存储与日期能力不变。 | 当前 `DatasetDefinition`；不能只检查 workflow 缺少名称。 |
| 正常运行能跨过原阻塞位置 | 加强既有 `tests/web/test_ops_runtime.py::test_task_run_dispatcher_runs_daily_market_close_workflow_with_bak_basic_step`，覆盖已有 manual/scheduled 参数；完整断言保留步骤顺序、节点和计数。若 planner 收到 `stk_factor_pro` 则立即失败；同时证明 `adj_factor` 被调用以及 `cyq_perf` 后执行 `stk_limit`，末尾问答步骤可达。 | 该测试替代源下载和业务写入，只证明真实 dispatcher、任务节点及顺序，不能证明生产数据已经写入。新增反向断言在移除前应失败，移除后通过。 |
| 目录 API 一致 | 在 `tests/web/test_ops_catalog_api.py` 核对工作流不含股票技术面因子、独立 action 仍在，其他字段和调度绑定语义不变。 | 使用隔离数据库；前端消费同一目录，无需增加硬编码或新开关。 |
| 独立维护语义不变 | 复用 `tests/test_dataset_action_resolver.py` 中 `stk_factor_pro` 用例，以及 `tests/test_dataset_writer_stk_factor_pro.py`。 | 覆盖全市场单日追加历史、指定股票单日不比较全市场变化、同日区间只按日期请求与 raw-only 写入。不得为了暂停工作流而改这些预期。 |
| 下游条件保留 | 复用板块分析 `test_upstream_readiness_requires_same_day_success_for_all_four_nodes` 和板块热度 `test_upstream_gate_uses_independent_workflow_cutoffs_and_all_required_nodes`。 | 本次保留其全部必需节点，不能因工作流成功就跳过各自输入检查。 |
| 失败与停止 | 复用既有 workflow 失败/worker 终态测试，核对本变更未扩大执行范围；生产停止另按 §6 读回。 | 不以 mock 的取消结果宣称旧生产任务已停，也不为本次移除扩建取消/续跑实现。 |
| 生产验收 | 获准后读回实际部署版本、目录、旧任务退出、新任务节点和目标日业务数据。 | 与单元测试、隔离集成、正式任务执行分别记录。 |

测试使用现有解释器和依赖；独立包需要时按已有源码路径设置 `PYTHONPATH`，不自动安装。测试缓存、临时数据库与输出放 `/private/tmp` 下的任务独立目录，禁止过程文件写回仓库。先核实既有测试基线；与本次无关的失败保留证据，不靠改断言或扩大 mock 隐藏。

## 9. 发布、恢复与文档同步

发布遵守[正式发版流程](/Users/congming/github/goldenshare/docs/release/release-process-v1.md)。本次没有新增部署命令，不把既有 `--ops-only` 等模式误写成只会重启某一个服务或不会安装、迁移、seed 的保证。实施前说明实际有效开关与副作用，获得对应授权后再执行。

Web 的目录和 worker 的执行定义必须使用一致版本；scheduler 使用的能力定义也需核实。加载旧定义的进程不能依靠热改文件生效。先停止已确认的旧任务，再按批准方式发布与核验，不把写文档或代码提交当作生产已切换。

恢复时先更新本方案、LLD 和测试清单，再恢复原位置的股票技术面因子行。恢复后的工作流重新包含当天下载和可能的大范围单股历史回刷；管理员未确认其成本与运行安排前不恢复。代码回退不撤销业务数据，也不意味着将旧任务改成成功。

文档同步范围：

- 本方案与本 LLD：目标、暂停/恢复状态、实测及未执行事项。
- `docs/ops/ops-workflow-catalog-v1.md`：本轮标注待实施方案；代码实施后再改为目标 27 步，保留历史变更说明。
- `docs/README.md`：登记两份文档与真实状态。
- 不改其他技术指标、Dagster 或数据集方案，不新增通用治理规则。

## 10. 本轮状态记录

| 项目 | 2026-11-25 状态 |
| --- | --- |
| 管理员对象与范围 | 已确认：从每日盘后工作流移除股票技术面因子 `stk_factor_pro`。 |
| 方案 / LLD | 已编写，待审阅；不是开发、发布或生产任务授权。 |
| 当前步骤核对 | 源码 AST 计数 28；目标为 28 减 1 等于 27；代码尚未修改。 |
| 当前调用与消费者审计 | CodeGraph 与当前源码已核对，见 §2。 |
| 前一轮已有测试证据 | 现有股票技术面因子 planner 的 22 条隔离单元测试通过；不覆盖尚未实施的本变更。 |
| 本轮文档检查 | `python3 scripts/check_docs_integrity.py` 三个检查组通过；`git diff --check` 通过。另以源码 AST 对照 §4，27 步的顺序和动作严格等于当前 28 步只移除股票技术面因子，股票复权因子保留。这些静态检查不证明生产运行或数据已齐备。 |
| 本次新增/调整代码测试 | 未实施。 |
| Prod 实时任务、独立调度与实际缺口 | 未核验。 |
| 停止、部署、补数与恢复 | 均未执行。 |
