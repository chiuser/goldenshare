# 指数日线源站探测说明

校准日期：2026-09-09。性质：现行代码说明；原 2026-06-22 方案与 LLD 的有效内容已合并，6 月 25 日修复及历史验收单列在 §6。本文不授权创建任务、修改对象池、迁移或部署。

## 1. 用途与配置边界

`remote_index_daily_ready` 用于独立 `index_daily.maintain` 自动任务，在源站样本就绪后创建 TaskRun。它只证明抽样可读，不证明整个请求池已经齐备，不替代完整性审计或补漏，也不改变 Raw/Serving 写入策略。

- target_type=dataset_action、target_key=index_daily.maintain；允许 probe / schedule_probe_fallback，不支持 Workflow 级探测。
- 页面从 automation_capability 取得条件，目前文案为“源站已有指数日线行情”；不维护前端同名常量/白名单，不默认追加 freshness。
- 不配置固定日期或 calendar_policy；binding 写动态 point 意图，命中后注入目标日期。显式日期范围被拒，不能让运营另传一套业务日期。
- filters 按数据集规则处理，支持显式 ts_code；默认样本没有独立 UI。不要把此能力套到分钟探测——后者当前自动任务只接受 freq。
- 纯 probe 的 cron_expr/next_run_at 必须为空，来源由系统决定，不能提交 probe_config.source_key。合法示例及字段只在 [Ops API §11.1](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md#remote-source-probe-examples) 维护，不保留旧 LLD 的错误 JSON。

目标能力、binding 先校验后重建、Workflow 中直接执行的边界归 [自动任务契约](/Users/congming/github/goldenshare/docs/ops/ops-automation-capability-contract-plan-v1.md)。这里的独立自动任务限制不改变手动维护或 Workflow 内 index_daily 步骤的执行方式。

## 2. 日期和样本选择

服务 `src/ops/services/index_daily_remote_probe_service.py` 将探测时刻转为上海日期 business_date，并按内部 exchange 或 settings.default_exchange 读取当天交易日历。日历缺失或非开市日直接 matched=False，不请求源站、不回退前一交易日；开市日才令 latest_open_date=business_date。

默认样本固定为：

| 顺序 | ts_code |
| --- | --- |
| 1 | 000001.SH |
| 2 | 399001.SZ |
| 3 | 399300.SZ |
| 4 | 000016.SH |
| 5 | 000905.SH |

五个默认样本必须全部存在于 `ops.index_series_active resource='index_daily_raw'` 的活动请求池；缺任一个即失败，不换其他代码，不回退 index_basic 或 index_daily Serving 门禁池。样本池检查调用 `DAOFactory(session).index_series_active.list_active_codes("index_daily_raw")`。

配置了显式 filters.ts_code 时，按输入顺序转大写、去重，最多取前 **5** 个；该分支不检查默认请求池。即使正式维护对象超过五个，也只探测前五个，不能写成“所有维护对象都已就绪”。

请求池与 Serving 池职责见 [指数 active 池机制](/Users/congming/github/goldenshare/docs/datasets/index-series-active-sync-mechanism.md)。本次不修改对象池、DAO 或同步主链，不以文档精简为由删除这些依赖。

## 3. 请求与命中

1. 对每个样本构造 index_daily maintain、point=目标日期及样本 ts_code 的 DatasetActionRequest。
2. 调用 DatasetActionResolver.build_plan，取第一个 unit 的 request_params；`_index_daily_params` 负责生成源请求，不由 Ops 手工拼日期。
3. 仅覆盖 limit=1、offset=0，显式请求 fields=(ts_code, trade_date)，通过数据集默认来源 connector 调用 index_daily。
4. 返回行 trade_date 匹配目标日期才算该样本命中；解析支持 date/datetime、YYYYMMDD 和 YYYY-MM-DD 等实现已处理的字符串形态。命中函数不额外核验返回 ts_code 与请求代码一致，不能夸大为完整身份校验。
5. 默认五个或选出的全部显式样本均命中才整体命中。空/错误日期为 miss；某样本 miss 仍继续检查其他样本，记录 missing_codes；源站异常中断本轮并由 runtime 记录失败。

每轮串行、最多 **5 次 connector.call**，不含底层重试；少量源站调用不代表本地规划/池查询没有成本，也不承诺固定耗时。没有新增并发、限流器或通用探测框架。

代码依据：`src/foundation/ingestion/resolver.py`、`src/foundation/ingestion/unit_planner.py`、`src/foundation/ingestion/request_builders.py`。字段资料见 [Tushare doc_id=95](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0095_指数日线行情.md)；本轮未重新实测源站，不把这些代码参数描述当成当前上游返回保证。

## 4. 入队与观测

源站分支不刷新本地 freshness，不调用 writer、不写指数业务表。整体命中后，runtime 创建 index_daily.maintain TaskRun：trigger_source=probe、trade_date=payload.latest_open_date、run_scope=probe_triggered，继承维护 filters 并移除 source_key；抽样列表不替换正式维护对象。

正常结果 payload 包含 dataset_key、condition_type、business_date、latest_open_date、sample_codes、matched_codes、missing_codes、sample_request_count、sample_hits、message。非交易日结果 latest_open_date=null，调用数为零并保留 is_open/pretrade_date；源站异常使用 runtime 的 error 载荷，不承诺保留中断前完整采样结果。

日志写入 schedule_id，页面按 schedule_id + dataset_key 查询历史，不以当前 ProbeRule id 代替任务归属。规则重建后的历史日志关联、日限额及 fallback 的限制统一见 [自动任务契约 §3.3](/Users/congming/github/goldenshare/docs/ops/ops-automation-capability-contract-plan-v1.md#probe-runtime-observation)。

ProbeRule 没有直接写 API；当前创建请求返回 405，其他旧写路由由测试约束为 404/405，不是旧 LLD 的“直接写入后按绑定校验返回422”。正常入口是 Schedule API。

## 5. 回归重点

| 边界 | 保留的正反例及入口 |
| --- | --- |
| 样本与日期 | 五个默认样本缺任一个失败；显式样本不读默认池；全部命中/部分命中/空/错日期；休市或缺日历零请求；`tests/web/test_ops_probe_api.py` |
| 请求与 TaskRun | sample 参数来自 resolver，仅覆盖探测分页与字段；入队使用命中日期并继承正式 filters，不把样本缩成维护范围；同上 |
| 配置与写入口 | 非目标、Workflow、固定日期/calendar policy、纯 probe 携带 cron/next-run、来源字段拒绝；binding 校验失败保留旧 rule；`tests/web/test_ops_schedule_api.py`、`tests/test_ops_automation_capability.py` |
| 日志与兜底 | schedule 归属过滤、旧 rule 删除后的日志查询；有效 probe 任务跳过兜底，失败/取消或前一日任务不阻止当天兜底；Probe API 与 `tests/web/test_ops_runtime.py` |
| 页面 | capability 驱动选项、条件切换、纯 probe 无执行时间与预览、fallback 有真实兜底时间、按 schedule 查询日志；`frontend/src/pages/ops-v21-task-auto-tab.test.tsx` |

此表保留维护时的验收要求，不表示所有组合已在本轮重跑。Python 检查与前端测试分开，不向 Ruff 传 .tsx；使用现有环境，不因文档命令隐式安装或同步依赖。

## 6. 历史实现与未核实验收

- **2026-06-22：**原文记录五个默认样本以 trade_date=20260424、fields=ts_code,trade_date 返回目标日期行；这是旧样本日期和当时验证记录，不是今天源站行为或更新时间证明。
- **本地实现记录：**原 LLD 记录后端 70 passed、前端 12 passed、Ruff 通过；本次没有重跑这些测试，也不把旧测试名或行号作为当前完整覆盖证明。
- **2026-06-25：**生产验收中发现日志归属丢失与兜底重复问题，原文记录已纳入修复。迁移 `alembic/versions/20260625_000119_add_probe_run_log_schedule_id.py` 增加 nullable schedule_id 及索引，先从关联 TaskRun 回填，再从尚存 ProbeRule 回填；两种依据均不存在的旧 miss 日志无法恢复 schedule 归属。初版“无 migration”不能覆盖这次后续修复。
- **验收状态：**旧 LLD 仍保留正式自动任务窗口内的日志与触发验收待办。本轮确认代码存在，未核实此后的生产版本、配置或真实运行证据，不自动结案，也不据旧待办创建新任务、重跑迁移或补写日志。

现行边界继续是源站样本探测，不改业务表/池、不恢复直接 ProbeRule CRUD、不新增样本配置。原代码草图、重复 API 模型及已完成施工步骤已移出主文档；信息去向见 [治理记录](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md#ops-source-probe-consolidation-20260909)。
