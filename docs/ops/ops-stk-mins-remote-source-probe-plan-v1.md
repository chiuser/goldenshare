# 股票分钟行情源站探测说明

校准日期：2026-09-09。性质：现行代码说明；原方案创建于 2026-06-05，历史源站样本及生产验收边界见 §6。本文不授权创建自动任务、探测、部署或数据写入。

## 1. 用途与职责

`remote_stk_mins_ready` 用于独立 `stk_mins.maintain` 自动任务：先抽样确认源站开始返回目标日期的分钟数据，再创建正式 TaskRun。它不证明全市场、全部分钟或全部股票已经完整。

探测服务不调用业务 writer、不修改分钟业务表，也不走本地 freshness 刷新分支；runtime 会写 ProbeRunLog，命中时创建 TaskRun。不能把“探测不写业务数据”理解成“运行探测完全只读”。

代码入口：`src/ops/services/stk_mins_remote_probe_service.py`；绑定、调用与日志归属见 [自动任务契约 §3](/Users/congming/github/goldenshare/docs/ops/ops-automation-capability-contract-plan-v1.md#probe-runtime-observation)。指数的“全部样本命中”是另一种规则，见 [指数探测说明](/Users/congming/github/goldenshare/docs/ops/ops-index-daily-remote-source-probe-plan-v1.md)。

## 2. 当前可配置范围

- 目标只能为 dataset_action + stk_mins.maintain；允许 probe 或 schedule_probe_fallback，不给 Workflow 步骤派生探测规则。
- `filters.freq` 必填，从 `1min / 5min / 15min / 30min / 60min` 中选择一个或多个；不要求五种全部选齐。
- **正常自动任务配置只接受 freq，不接受额外 ts_code。**底层服务仍有显式代码取前三个的分支，且测试会直接构造规则调用它；这不代表 Schedule API 开放该配置，本次不删除或恢复任何代码分支。
- 不设置固定业务日期或 calendar_policy；binding 生成动态 point 意图，命中后 runtime 注入探测日期。固定日期字段的校验归 capability，不在本文另造日期解析规则。
- 页面选项及文案来自 Catalog 的 automation_capability，目前文案为“源站已有股票分钟行情”；不在前端新增 action-key 白名单，也不默认追加本地 freshness 选项。

通用请求字段、纯 probe 空 cron/next-run、系统来源及可用配置示例统一见 [Ops API §11.1](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md#remote-source-probe-examples)。窗口和间隔由能力约束及配置决定，示例值不是生产现状或源站更新时间承诺。

## 3. 目标日期与样本

以探测时刻的上海日期为 business_date，读取指定交易所（规则内部 exchange 或 settings.default_exchange）的当天交易日历：

1. 日历缺失或 is_open 不为 True：matched=False，源站调用数为 0，latest_open_date=null，不回退到前一开市日。
2. 当天开市：latest_open_date=business_date。变量名虽叫 latest_open_date，此分支实际表示经过日历核验的当天。
3. 正式 TaskRun 的 trade_date 使用同一日期，不再次猜默认日期。

默认样本候选固定为：

| 顺序 | ts_code |
| --- | --- |
| 1 | 600000.SH |
| 2 | 000001.SZ |
| 3 | 300750.SZ |
| 4 | 601318.SH |
| 5 | 000858.SZ |

执行前通过 SecurityDAO 逐个查询，保留存在、source=tushare、list_status=L 的股票；不从全市场临时补样本。候选可以少于五只，全部被过滤时抛错，由 runtime 记录探测失败。

## 4. 请求与命中规则

每个样本的日期和参数仍走 `DatasetActionRequest -> DatasetActionResolver.build_plan -> plan.units[0].request_params`，不由 Ops 自行拼源接口日期。当前单日 planner 窗口为 09:00:00–19:00:00，`_stk_mins_params` 生成 ts_code/freq/start_date/end_date；探测仅覆盖 limit=1、offset=0，显式请求 fields=(ts_code, trade_time)。

请求主链依据：`src/foundation/ingestion/unit_planner.py`、`src/foundation/ingestion/request_builders.py`；源字段资料见 [Tushare doc_id=370](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/行情数据/0370_股票历史分钟行情.md)。本次只核验代码如何构造请求，不把历史实测当成当前源站验证。

按所选频率串行执行，每个频率依次尝试样本：

- 任一样本返回日期匹配的 trade_time，该频率命中并停止尝试此频率的其他股票。
- 某频率所有样本都未命中，立即结束本轮为 miss，不继续后面的频率。
- 所有所选频率均命中，才整体命中。空结果、错误日期或不可解析日期都不算命中。
- 命中函数检查 trade_time 日期，不额外验证每行的代码、返回频率或日内完整性；错误调用抛给 runtime，不能宣称样本命中就是全量验收。

正常配置下，令 S 为过滤后样本数（最多 5），F 为去重后的所选频率数（最多 5），每轮最多 S×F 次 connector.call，即 **最多 25 次**，不是旧文的 15 次。命中短路及提前 miss 可减少调用；不含 connector 内部重试，不能当作实际 HTTP 次数或耗时硬上限。请求仍使用现有 connector/限流机制，不在文档冻结旧限速数字。

## 5. TaskRun 与诊断

命中后创建 stk_mins.maintain TaskRun，trigger_source=probe、time_input={mode:point, trade_date:探测日期}、run_scope=probe_triggered；正式任务继承规则的维护 filters，不用抽样股票替代全量维护对象。

常规 payload 保留 dataset_key、condition_type、latest_open_date、checked_freqs、matched_freqs、sample_request_count、sample_codes、sample_hits、message；sample_hits 只存已命中的 freq/ts_code/trade_time，不包含错日期的原始异常行。

非交易日结果另外保留 business_date/is_open/pretrade_date，采样数组为空；异常由 runtime 使用 `error` 记录，不是 source_error。miss、failed、日志归属与日限额、兜底的实际边界统一见 [自动任务契约 §3.3](/Users/congming/github/goldenshare/docs/ops/ops-automation-capability-contract-plan-v1.md#probe-runtime-observation)。不能承诺修改规则或多个触发路径下绝对只创建一次。

## 6. 历史证据与回归

原 2026-06-05 文档记录的源站样本（仅作为当时证据）：

- 600000.SH、2026-05-29、1min，limit=1/offset=0、fields=ts_code,trade_time 返回目标日期样本。
- 同样请求在 2026-06-05 返回空数组；这只证明那次请求为空，不证明后来一直未就绪。
- 2026-05-29 的五个频率小样本均可返回目标日期数据。

当时记录“已实现，待生产验收”。本次确认代码和测试入口存在，未连接生产核实后续配置、部署及验收，不自动关闭，也不据旧文重建任务。

回归入口：`tests/web/test_ops_probe_api.py`（默认样本过滤、无日历/休市零请求、resolver 参数、逐频率命中、TaskRun 日期）、`tests/web/test_ops_schedule_api.py`（绑定/日期/纯 probe 时间/来源拒绝）、`tests/test_ops_automation_capability.py`（能力配置）、`frontend/src/pages/ops-v21-task-auto-tab.test.tsx`（能力选项及表单）。后续修改还须覆盖 freq 子集可用、ts_code 配置被拒、失败不误报命中；不能把服务替身绕过 API 的输入当成可配置入口。

本轮不执行数据库测试、源站请求、浏览器构建或生产验收，不安装依赖。原施工清单已移除；合并依据和静态验证见 [治理记录](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md#ops-source-probe-consolidation-20260909)。
