# ETF 历史分钟行情维护说明（含 Preview 与历史验收）

状态：Basic 驱动、Preview 和普通手动任务多代码扇开已落地；旧 alignment Submit 已删除；2026 年指定区间生产补拉与对账已完成
创建日期：2026-08-24
最近更新：2026-09-10。原 LLD 已并入本文；代码状态与 2026-08-29 的生产记录分开陈述，本轮未复跑生产。
源站文档：[Tushare 0387 ETF 历史分钟行情](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0387_ETF历史分钟行情.md)

## 1. 当前结论

`etf_mins` 维护 Tushare 原生 ETF 历史分钟行情，唯一物理事实表为 `raw_tushare.etf_minute_bar`。当前代码不再读取 ETF 激活池；所有按代码展开的请求都由 `core_serving.etf_basic` 的统一当前可请求 selector 驱动，并在生成窗口前把起点裁到 ETF 上市日。

本次对象来源切换只改变未来请求规划，不删除既有分钟事实，也不自动补齐全量历史。主方案 P9-P12 已完成 `2026-01-01..2026-08-28` 指定区间的 Preview、授权、执行和对账。已经执行的 unit 保持有效；未来若处理其他区间，一律以新 Preview 重算，不从已取消 TaskRun 的汇总状态猜测。

P9A 只提供必填的 `alignment_start_date/alignment_end_date`。它固定本次中国日期和一份 Basic snapshot，把全部当前可请求 ETF 放入 target hash；其中上市日晚于截止日的 ETF 只计数、不生成区间。其余对象按五个原生频率检查指定区间内的 raw 首尾边界和明确成功 TaskRun 请求证据；每只 ETF 的有效起点取指定开始日与上市日之后的首个 SSE 开市日，不检查内部逐日空洞，也不把纯休市范围规划成请求。

## 2. 源接口与字段

支持五种 Tushare 原生频率：

```text
1min / 5min / 15min / 30min / 60min
```

每个请求必须带 `ts_code`、`freq`、`start_date`、`end_date`，分页由统一 source client 追加 `limit/offset`。保存字段为：

```text
ts_code, freq, trade_time, open, close, high, low,
vol, amount, vwap, exchange
```

业务主键是 `(ts_code, freq, trade_time)`。任何重复身份但内容冲突、身份字段缺失或源端乘数异常都必须让 unit 失败，不能静默选一行。

## 3. ETF 对象资格

一次 plan 开始时固定一个中国自然日 `eligibility_as_of`。统一条件由 `EtfBasicDAO` 实现：

```text
list_status = 'L'
AND list_date IS NOT NULL
AND list_date <= eligibility_as_of
AND ts_code 仅限 .SH / .SZ
AND ts_code 后缀与 exchange 一致
```

规划规则：

1. 未填写 `ts_code`：一次加载全市场 requestability snapshot，再对所有 target 生成 unit。
2. 填写单个 `ts_code`：只查询一次该代码的 requestable target，不加载全市场 snapshot。
3. 填写多个 `ts_code`：一次加载全市场 requestability snapshot，在内存中校验并按规范化代码顺序返回输入集合；不逐代码查询。
4. 多代码输入支持逗号分隔字符串或字符串数组，统一去空格、转大写、去重和稳定排序。
5. 任一显式代码不合格时整次返回 `etf_not_requestable`，不生成部分 unit，也不对合格子集继续请求。
6. 全量资格集合为空时返回 `universe_empty`，不回退历史池或猜全市场。

Definition 中保留 `universe_policy='pool'` 只是表示“按对象集合展开”的通用技术形状；对象源已经是无 resource 的 `core_serving_etf_basic`，不存在新的持久化池。

`etf_mins` 的 `ts_code` 公开过滤器改为多值，但不改变“不填写即全量”的既有语义。该能力只放宽 ETF 分钟路径；共用 Basic selector 的沪市、深市申赎清单仍保持一次最多一个显式代码。

## 4. 时间与切窗

单日和区间请求的有效起点均为：

```text
effective_start = max(requested_start, list_date)
```

全量规划中，如果整个请求窗口早于某 ETF 的上市日，该 ETF 不生成 unit；任一显式代码的窗口整体早于上市日时整次返回 `window_before_list_date`。不会为这种正常裁剪新增“跳过统计”或共享执行计划字段。

区间按频率拆为受控自然月窗口：

| 频率 | 单 unit 最大自然月跨度 |
| --- | ---: |
| `1min` | 2 |
| `5min` | 12 |
| `15min` | 36 |
| `30min` | 72 |
| `60min` | 120 |

每个 unit 对应一个 ETF、一个频率和一个窗口。请求时间边界使用窗口首日 `09:00:00` 到末日 `19:00:00`，不把日期区间直接扩成逐日 unit。

## 5. 存储、分页与事务

| 项目 | 当前合同 |
| --- | --- |
| 存储 | raw-only，`raw_tushare.etf_minute_bar` |
| Serving | 无第二份分钟 serving 物理表 |
| 分页 | `offset_limit`，每页 8,000 行 |
| unit 最大接纳 | 24,000 行 |
| 页面处理 | unit 内聚合后一次写入 |
| 写入 | 按业务主键幂等 upsert |
| 提交 | 每个 unit 独立提交 |
| fetch concurrency | 2 |

源端空结果允许完成，因为停牌、历史无数据或源端尚未形成分钟事实不能被系统伪造成错误行；但空结果也不能作为“已有每分钟完整覆盖”的证明。

## 6. 运营与观测

数据集支持手动和普通定时 `maintain`，时间输入为单日或区间，频率至少选择一个。`trade_time` 是观测字段，但 V1 不接普通按日完整性审计，因为分钟完整性需要交易时段网格和停牌语义。

每个实际 unit 的 `progress_context` 记录：

```text
eligibility_as_of
master_list_date
requested_start_date
effective_start_date
ts_code / freq / window
```

这些字段用于解释本 unit 为什么从该日期开始，不扩展公共执行计划或 TaskRun schema。

## 7. Preview：只检查指定区间首尾

入口：

```text
goldenshare ops-preview-etf-minute-alignment --alignment-start-date YYYY-MM-DD --alignment-end-date YYYY-MM-DD [--output plan.json]
```

[CLI handler](/Users/congming/github/goldenshare/src/cli_parts/ops_handlers.py)先建立 `REPEATABLE READ + READ ONLY` 事务、设置每条语句 `180s` timeout，再调用 [build_plan()](/Users/congming/github/goldenshare/src/ops/services/etf_minute_history_alignment_plan_service.py)，最后 rollback。只读事务不是 service 自行设置的；直接调用 service 的调用方必须先建立同等边界。

一次事务固定 UTC 时钟、中国资格日期、SSE 开市日和 Basic snapshot。全部当前可请求 ETF 进入 `request_target_hash`，上市日晚于截止日的对象单独计数，不生成区间。其余对象从不早于 `max(alignment_start_date, list_date)` 的首个 SSE 开市日开始计算。

查询与判定：

1. 从最早有效起点所在月到截止月，逐月执行 `ts_code/freq/COUNT/MIN/MAX` 集合统计，日期为左闭右开月区间；SQL 不关联 Basic，服务在内存中按目标区间裁剪。
2. 查询数只随月份增长，不随 ETF×频率增长。每条 SQL 必须只访问当月分区；跨月扫描或单月超 180 秒应停止，不自动改成周扫描、不提高超时或顺手建索引。
3. 只生成 prefix/suffix；不审计内部日期或分钟空洞。缺口不含 SSE 开市日时丢弃，其他缺口复用正式切窗函数计算 unit。
4. 成功 TaskRun 的显式单代码字符串或全部合法的代码数组，可按代码×频率还原请求区间。无代码全量任务、空数组或非法数组不猜覆盖，任务总行数也不分摊成代码证据。
5. 只有成功 TaskRun、没有 Raw 行时记为 `successful_task_only_covered_target_frequency_count`；这证明请求完成，不能证明源端返回了零行。
6. 输出摘要和可选 JSON；不请求 Tushare，不调用 writer，不创建 TaskRun，不提交数据库，不提供 submit/apply 参数。

该工具不是分钟完整性审计，也不是冻结后可直接执行的计划。普通手动任务不读取 Preview JSON，不保存它的 hash。

## 8. 正式执行与实现入口

正式维护使用现有 Ops 手动动作；页面的逗号文本会转为代码数组：

```text
POST /api/v1/ops/manual-actions/etf_mins/task-runs
time_input = {mode: range, start_date, end_date}
filters = {ts_code: [多个代码], freq: [多个频率]}
```

一次提交只创建一个普通 `dataset_action / etf_mins / maintain` TaskRun。数组保存在 `filters_json.ts_code`，planner 按规范化代码、Definition 频率、窗口时间顺序展开；每个源请求仍是一个标量代码和频率。Definition 同时供 schedule 使用，不另设“仅手动可多选”合同。

[Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_fund.py) → [unit planner 的模块函数 _build_etf_mins_units](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py) → Basic selector → [窗口模块](/Users/congming/github/goldenshare/src/foundation/ingestion/etf_minute_windows.py) → [request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py) → source client/normalizer/writer。planner 查对象并切窗，builder 只映射 `ts_code/freq/window_start/window_end`，分页由 source client 追加。

窗口从有效起点开始，终点取对应自然月月末并裁到请求末日，下窗从前窗结束次日开始；单日只生成一窗。抓取并发为 2，归一化和写入由执行主线程处理；逐 unit 提交、幂等 upsert 和现行失败/取消/重试语义不因多代码变化。已提交 unit 不随取消回滚；这些事实不等于已具备精准断点续跑。

旧 `ops-submit-etf-minute-alignment`、`--batch-size`、“一 action 一 TaskRun”、Submit service 和两个专属测试均已删除，不保留 alias 或专用 payload。Preview service/CLI/测试仍保留。禁止恢复旧激活池、seed、Review 页面或异常回退；当前主数据资格变化也不授权删除历史分钟事实。

## 9. 2026-08-29 历史验收

以下是指定区间 `2026-01-01..2026-08-28`、资格日期 `2026-08-29` 的记录，不是当前全历史或未来区间的完整保证。旧池曾有 1,395 个代码，仅属历史快照。P3 迁移 planner；P8 删除旧池代码并准备 migration；P11 执行生产旧表删除与 Basic 重建；P12 完成此次补拉。详细上位记录见 [Basic 重建 LLD](/Users/congming/github/goldenshare/docs/architecture/etf-basic-rebuild-and-downstream-data-audit-cleanup-low-level-design-v1.md)。

| 步骤 | 当时证据 |
| --- | --- |
| 首次 Preview | 约 32 秒，无单月超时；1,647 个 ETF、8,235 个代码/频率，Raw 覆盖 6,975；252 个 ETF 的 prefix 缺口 1,260，suffix 和 TaskRun-only 均为 0 |
| 初始计划 | 252 action、1,774 unit，请求 1,774–7,096；167 action 从 1 月 5 日开始，85 按更晚上市日开始 |
| 旧 Submit 停止 | 首批 10 任务成功；后续队列 61 成功、181 取消，开放任务归零。取消任务 9923 已提交 3/8 unit，不能凭取消状态推断无物理写入 |
| 停止后重算 | 181 个代码、182 action、1,333 unit，请求 1,333–5,332 |
| 单普通任务取舍 | 五频统一输入 1 月 5 日至 8 月 28 日；159539.SZ 的 1min 实际只缺 7 月起，接受上半年三个额外幂等 unit，合计 1,336，请求 1,336–5,344 |
| 正式 TaskRun 10117 | 执行前 open 任务为 0，schedule 39 不重叠、未暂停，181 代码均可请求；完成 1,336/1,336 unit，抓取并保存 7,606,095 行；失败、拒绝、去重和 issue 均为 0 |
| 补后 Preview | 8,235 个组合均由 Raw 首尾覆盖，TaskRun-only、prefix/suffix 缺口、action、unit 均为 0；`interior_gap_not_audited=true` |

身份与内容证据：

- `request_target_hash=8972736114ecbd14d3245e6c59d80c63b463752a15db5b8bfe7ee5ca7ebd31c3`，与停止后 Preview 一致。
- 补后 `plan_content_hash=ec836cc7722f22b44ad13266eeace59a334ebd459d910c3c95207e1253b7ca72`。
- 当时后端目标测试 247、架构护栏 61、前端 147 项及 Ruff/typecheck/rules/build 通过；全量 CLI 留有 P8–P10 已记录的无关 progress reporter 旧失败。这不是本轮对该失败现状的复验结论。
- 当时 CodeGraph 后置核对确认多代码开关只在 ETF 分钟开启，沪深申赎未放宽。上述生产阶段已经关闭；未来区间需重新 Preview、审查和独立授权，不重放旧历史输入。

## 10. 回归重点

当前 [ETF 分钟测试](/Users/congming/github/goldenshare/tests/test_etf_mins_dataset.py)与 [Preview 测试](/Users/congming/github/goldenshare/tests/test_etf_minute_history_alignment_plan_service.py)是主要入口。维护时至少核对：

- SH/SZ、L、有效上市日正例；P/D、空或未来上市日、OF、后缀与 exchange 冲突负例。
- 单代码只查一个 target，多代码/无代码只查一次 snapshot；任一坏代码整单失败。共享 selector 的多代码开关仅 ETF 分钟开启，沪深申赎仍拒绝多代码。
- 上市日裁剪、全量跳过/显式拒绝、五频月末/闰年边界、连续不重叠和标量源参数。
- 8,000 分页、24,000 unit 上限、任意 rejection/源端重复身份失败、空结果允许及幂等。
- 普通 API 一任务保存代码数组；Preview 合法字符串/数组覆盖、非法数组不算覆盖及只读边界。

通用执行合同与长任务门禁引用[执行计划说明](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)，不在本说明复制另一套运行时设计。

## 11. 2026-10-21：15、16日恢复方案与执行细节（第一阶段已批准，提交受阻）

管理员在审阅范围、完整Basic读取和既有取消限制后回复“开始推进补齐吧”，批准第一阶段按本节执行。提交前再次只读核验对象和源计数、活动任务，范围未变；当前无重叠任务。运营页面已有管理员登录，但浏览器页面接口反复超时，窗口接口不能可靠操作日期和提交按钮，因此尚未创建样本或全对象TaskRun，也未写入生产数据。已带入旧任务15937的维护对象与五频条件，并填写样本代码158000.SZ；日期区间尚未可靠填入，不得声称样本已开始。下一动作是通过正常认证的运营页面提交本节两日五频样本，取得新TaskRun ID后按既定标准验收。不得绕过认证、伪造身份或改走直接业务表写入。DG仍待上游恢复及其阶段验收。

本步只恢复 `2026-10-15..2026-10-16` 的五个原生频度，供 DG 继续处理15、16、19、20日。依据为当日 TaskRun、节点、问题记录、生产 worker 日志和线上代码；审计证据位于 `/private/tmp/etf_mins_root_cause_20261021.json`，恢复前计数位于 `/private/tmp/etf_mins_recovery_preflight_20261021_results.txt`。15日任务15937在首个代码读取超时后失败，保存0行；16日任务16068在5分钟请求502后失败，已提交272行。19、20日成功，不再向 Tushare 请求这两天。

### 11.1 范围与入口

复用本说明第8节现有 Ops 手动入口、现有 worker 和完整字段合同，不改代码、配置、调度39、错误分类、API 或 DatasetDefinition。不得直接重试15937/16068：任务头的 `time_input_json` 仅有 `mode=point`；`TaskRunCommandService._context_from_retry()` 原样复制，dispatcher 会在执行时重新选择缺省日期，不能保证恢复15、16日。

先提交一个 `ts_code=158000.SZ` 的两日五频样本；样本成功且五频两天存在性、字段及拒绝计数符合现行合同后，才提交全对象任务。正式请求为：

```json
{
  "time_input": {"mode": "range", "start_date": "2026-10-15", "end_date": "2026-10-16"},
  "filters": {"freq": ["1min", "5min", "15min", "30min", "60min"]}
}
```

请求发往 `POST /api/v1/ops/manual-actions/etf_mins/task-runs`；样本在相同 filters 内增加 `ts_code: ["158000.SZ"]`。经管理员已登录的运营入口提交，不猜用户身份、不绕过认证，不另写直接业务表写入脚本。若无可用认证入口，停止在提交前。

对象沿用 `EtfBasicDAO.load_requestability_snapshot()`；正式任务需要读取一次完整 `core_serving.etf_basic`，按当前资格选择代码，再按各自上市日裁剪请求。2026-10-21只读计数为：Serving1881行、当前可请求1711只；15日合格1701只、16日1705只。全表读取是现有 planner 的必要输入，预计小于数MB，但不属于计数例外；执行批准必须明确包括这一次完整 Basic 读取。Basic 发生变化时重新计数，不沿用旧数量。

### 11.2 写入、失败与恢复

只写 `raw_tushare.etf_minute_bar` 及新 TaskRun/节点/问题/进度记录，业务主键为 `(ts_code,freq,trade_time)`，沿用每个代码×频度×窗口独立提交与幂等 upsert；不删除或清空任何表，不改旧失败任务，不启动额外 worker。源请求仍为标量代码、标量频度及明确的09:00至19:00边界，保留11个完整源业务字段。

该两日范围同属一个自然月，每只代码每个频度只生成一个窗口，预计1705×5=8525个 unit，样本另5个；小于按两天分别提交的17030个 unit。任一 source、合同或写入失败即按现行链停止，不改断言、不吞错误、不自动无限重提。取消后保留已提交数据；普通入口没有精确断点续跑，重提同一明确范围会重新请求全部8525个 unit，已存在记录按主键幂等处理。中断时先读回已提交事实，再另行确认续跑，不能凭任务头汇总断言无写入。

已确认的现有执行限制必须在批准前说明：HTTP底层读取超时会多次重试，15日曾等待约196秒；不能承诺30秒内取消。15日的 ConnectionError 被误记为不可重试，问题尚未修复。普通任务完整范围重放也不是精准断点恢复。本次方案不将这些差距写成已通过长任务门禁；若严格要求30秒内取消或精准续跑，应先单独设计、修复并验收执行入口，再恢复。本次若采用既有入口，需要管理员明确接受本次有界恢复的上述限制。

### 11.3 成本与验收

| 项目 | 本步预算与停止条件 |
| --- | --- |
| 请求 | 8525个主请求，样本5个；两日1min单unit正常约482行，远小于8000页上限；沿用并发2。异常分页仍受24000行/unit和既有重试限制，不能把8525当成网络尝试总上限 |
| 内存/事务 | 当前代码逐unit缓冲、不累积全范围行情；每unit最多24000行，最多2个源抓取；业务按unit提交，不使用全范围事务 |
| 规模/时间 | 按19、20日每单日约55万行、约19分钟测算，两日约110万行；两日合并请求预计20至40分钟，45分钟未完成则请求取消并保留现场，取消等待计入额外4分钟预算 |
| 失败重放 | 重新提交前独立确认；最多再读8525个unit，重新预算45分钟及取消等待；不在同一次批准内无限重试 |
| 样本/读回 | 样本最多5分钟；最终15、16日按频度聚合及缺失代码有界抽样，预算15分钟；不运行只查首尾的 alignment Preview 来冒充两天完整性验证 |
| 配额/并发 | 复用现有 Tushare 限速和并发2，不提高配额、不与ETF Basic或ETF分钟活动任务重叠；执行前重查，距20:35例行调度不足60分钟则不启动全量任务 |

验收逐项记录源抓取、归一化、保存、拒绝、目标物理行数和已存在行的差别，所有 reject 必须解释。必须有15、16日五频针对当前已确认对象集合的代码覆盖检查，以及 DG 正式门禁的独立复核；任务成功和行数大于0不能代替这些检查。全量 Basic 读取、Tushare 请求、Prod 写入、后续DG写入分别列明授权，不以本节“待批准”状态声称已执行。

CodeGraph 已审查 TaskRun 创建/重试、planner、写入与观测路径，并以当前代码和线上部署复核；DG范围见[原DG方案第19节](../../lake_console/docs/design/dagster-etf-market-data-prod-db-onboarding-plan-v1.md#19-2026-10-21分钟缺口恢复待批准未执行)。本次无架构、依赖方向或契约改动；防止复发的代码整改不属于本次补数。
