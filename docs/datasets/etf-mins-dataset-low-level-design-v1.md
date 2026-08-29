# ETF 历史分钟行情数据集 LLD v1

状态：Basic 驱动、Preview 与普通手动任务多代码扇开已落地；旧 alignment Submit 已删除；待部署和独立生产执行授权
最近更新：2026-08-29
上位方案：[ETF 历史分钟行情数据集接入方案 v1](/Users/congming/github/goldenshare/docs/datasets/etf-mins-dataset-development.md)
主数据重建 LLD：[ETF 基础信息重建与下游数据审计清理 LLD v1](/Users/congming/github/goldenshare/docs/architecture/etf-basic-rebuild-and-downstream-data-audit-cleanup-low-level-design-v1.md)

## 1. 当前执行链

```text
Dataset action / schedule
-> DatasetActionResolver
-> DatasetUnitPlanner._build_etf_mins_units
-> EtfBasicDAO requestability contract
-> build_etf_minute_windows
-> _etf_mins_params
-> DatasetSourceClient(offset_limit)
-> DatasetNormalizer
-> DatasetWriter(raw_only_upsert)
-> raw_tushare.etf_minute_bar
```

没有旧池 DAO、resource、adapter 或 fallback。

## 2. DatasetDefinition 合同

当前 Definition 位于 `src/foundation/datasets/definitions/market_fund.py`：

| 维度 | 值 |
| --- | --- |
| dataset key / API | `etf_mins` / `etf_mins` |
| date model | `trade_open_day + every_open_day + point_or_range` |
| input | `trade_date` 或 `start_date/end_date`；可选多值 `ts_code`；必填多选 `freq` |
| universe | `pool` 技术形状，唯一 source 为 `core_serving_etf_basic`，无 resource |
| storage | `raw_only_upsert` 到 `raw_tushare.etf_minute_bar` |
| conflict key | `(ts_code, freq, trade_time)` |
| pagination | `offset_limit`，page limit 8,000 |
| quality | 任意 rejection 失败；源端重复身份拒绝；空结果允许 |
| completeness | `not_applicable`，原因是分钟网格未建模 |

Definition 的 `pool` 不代表持久化池，不能改回 `ops_etf_series_active` 或新增伪 resource。

## 3. Planner 资格与固定时点

`_build_etf_mins_units()` 每次 plan 只计算一次 `_current_china_date()`。之后：

```text
单个显式 ts_code
-> EtfBasicDAO.get_requestable_target(..., as_of_date, exchange=None)

多个显式 ts_code 或未显式 ts_code
-> EtfBasicDAO.load_requestability_snapshot(..., as_of_date, exchange=None)
```

公共 `_validate_requestable_etf_universe()` 固定 Definition 必须绑定 `ts_code` 且 source 精确为 `core_serving_etf_basic`。ETF 分钟专属 target 解析按以下顺序工作：

1. 使用现有 `split_multi_values()` 接受逗号字符串或字符串数组，再统一去空格、转大写、去重和排序。
2. 一个代码时保留现有单对象查询，不加载全市场。
3. 两个及以上代码时只加载一次 snapshot，建立 `ts_code -> target` map，并按规范化输入顺序返回交集。
4. 任一输入代码不在 snapshot 时，整次抛出 `etf_not_requestable`，details 带稳定排序的 `invalid_ts_codes`；不生成部分计划。
5. 不填写代码时继续返回 snapshot 全量 target；空集合仍为 `universe_empty`。

共享 `_resolve_requestable_etf_targets()` 同时服务沪深申赎清单。当前实现增加 `allow_multiple_explicit=False` 参数，只有 `_resolve_etf_mins_targets()` 显式传入 `True`；`etf_sh_cons`、`etf_sz_cons` 仍在任何 Basic 查询前拒绝多代码。

禁止：

1. planner 自行拼 Basic SQL。
2. 自动计划逐 ETF 查询 Basic。
3. 单代码显式计划为方便而加载全市场 snapshot，或多代码计划逐代码查询。
4. selector 异常时回退历史池。

## 4. 上市日起点

`_resolve_effective_etf_start()` 统一执行：

```python
effective_start = max(requested_start, target.list_date)
```

如果 `effective_start > requested_end`：

- 全量计划返回 `None`，该 target 不生成 unit；
- 显式代码抛出 `window_before_list_date`，details 包含代码、请求上下界和主数据上市日。

该 helper 只决定是否生成实际 unit。它不产生跳过汇总，不修改 `DatasetExecutionPlan`，不写 Ops 诊断。

## 5. 频率与窗口

`src/foundation/ingestion/etf_minute_windows.py` 是唯一切窗事实源：

```python
ETF_MINS_RANGE_WINDOW_MONTHS = {
    "1min": 2,
    "5min": 12,
    "15min": 36,
    "30min": 72,
    "60min": 120,
}
```

窗口以 `effective_start` 开始，以目标跨度最后一个自然月月末为自然终点，再裁到请求 `end_date`。下一个窗口从上一窗口结束次日开始，保证不重叠、不留缝。单日模式只生成一个单日窗口。

request builder 只接受 planner 生成的：

```text
ts_code, freq, window_start, window_end
```

并映射为源参数 `ts_code/freq/start_date/end_date`。分页参数只能由 source client 追加。

## 6. Unit、写入与错误

一个 unit 的身份包含代码、频率、窗口和 ordinal。`progress_context` 只记录真实 unit 的代码、频率、窗口、固定资格日期、主数据上市日、用户请求起点和有效起点。

写入规则：

1. 所有页面先在 unit 内聚合。
2. 行数超过 24,000 立即失败。
3. 任意 normalization rejection 失败。
4. 同一 `(ts_code, freq, trade_time)` 多行视为源端乘数错误并失败。
5. 通过后一次 bulk upsert、一次 commit。
6. 重跑相同 unit 幂等，不写第二份 core/serving。

## 7. 测试账本

必须覆盖：

1. `.SH/.SZ + L + 有效 list_date` 正向目标。
2. `P/D`、空/未来上市日、`.OF`、后缀与 exchange 冲突的负向目标。
3. 自动计划每次只加载一次 snapshot；单显式代码只查一次 target；多显式代码只加载一次 snapshot，查询次数不随代码数增长。
4. 一个 TaskRun 的 `filters_json.ts_code` 保存手动动作解析后的数组；planner 再统一转大写、去重、排序。
5. 多代码全部合格时按代码 × 频率 × 窗口稳定扇开；任一代码不合格时整次失败且 unit 为零。
6. 请求起点早于上市日时按每个代码独立裁到 `list_date`。
7. 全量窗口整体早于上市日不生成 unit；任一显式代码的窗口整体早于上市日时整次返回结构化错误。
8. 五频率窗口边界、月末、闰年、连续不重叠。
9. request builder 每个 unit 只接收一个标量 `ts_code`，不接收数组或逗号字符串，也不注入 pool resource。
10. `etf_sh_cons`、`etf_sz_cons` 继续拒绝多代码。
11. Preview 对成功 TaskRun 覆盖同时识别历史单字符串代码和新代码数组，并按代码 × 频率还原；空列表或非法值不算覆盖。
12. 分页、24,000 行上限、rejection、重复身份和幂等写入。

## 8. 发布和数据边界

P3 的代码迁移不执行生产补拉。P8 只删除旧池代码并准备 migration，没有执行生产 DDL。P11 已完成生产旧表删除与 Basic 正式重建；P12 的只读 Preview 已从重建后快照得到待补代码清单。后续由普通手动任务提交一个 TaskRun，不再使用 alignment Submit。

## 9. P9A 全量对齐 Preview

公开入口固定为：

```text
goldenshare ops-preview-etf-minute-alignment --alignment-start-date YYYY-MM-DD --alignment-end-date YYYY-MM-DD [--output plan.json]
```

服务在一次 `REPEATABLE READ + READ ONLY` 事务中固定 UTC 时钟、中国资格日期、指定区间内的 SSE 开市日和 Basic snapshot，并设置每条语句 180 秒 statement timeout。全部当前可请求 ETF 进入 `request_target_hash`；只有 `list_date <= alignment_end_date` 的对象进入五频率覆盖计算，晚于截止日的对象单独计数。每只 ETF 的 effective start 是不早于 `max(alignment_start_date, list_date)` 的首个 SSE 开市日。

raw 边界从最早 effective start 所在月到截止月逐月统计。每月一条 SQL 固定返回 `ts_code/freq/COUNT/MIN/MAX`，日期使用 `[month_start, next_month_start)`，必须只裁到该月分区；数据库查询不关联 Basic，服务在内存中再按 target desired interval 裁剪。查询次数只随指定区间覆盖的月份数增长，不随 ETF、频率或历史上市年限增长。月内允许只扫描该月分区；如果触及其他月份或单月达到 180 秒超时，阶段立即停止，不自动按周重试、不加索引、不提高超时。

覆盖区间先裁到 `[effective_start_date, alignment_end_date]`，仅生成 prefix/suffix。内部 gap 明确不审计；候选缺口不含任何 SSE 开市日时直接丢弃。无 raw 但有成功显式任务时只能记为 `successful_task_only_covered_target_frequency_count`，不能声称源端返回零行。TaskRun coverage parser 兼容历史单字符串 `ts_code` 和新多代码数组，后者按代码 × 频率展开再与 desired interval 求交；无代码的全量任务仍不猜覆盖。每个有效缺口复用 `build_etf_minute_windows()` 计算 unit，相同代码和日期范围才合并频率。

P9A 只输出 plan、摘要和可选 JSON 文件；不调用 connector/writer/TaskRunCommandService，不 commit、不提供 submit/apply 参数。生产规模报告由本地未部署代码在同一个只读事务中直接生成，不部署服务。

2026-08-29 的 Prod 只读执行以 `2026-01-01` 至 `2026-08-28` 为指定区间、`2026-08-29` 为资格日期，约 32 秒完成且没有触发单月 180 秒门禁。1,647 个 requestable target 全部进入 alignment；五频率 raw 覆盖合计 6,975 个 target/frequency，252 个 ETF 的 prefix 缺口合计 1,260 个 target/frequency，suffix 缺口 0，成功 TaskRun-only 覆盖 0。最终计划有 252 个 action、1,774 个 unit，请求上下界为 1,774–7,096；167 个 action 从首个开市日 `2026-01-05` 开始，85 个按更晚上市日开始。此前无开始日、默认追溯上市日的全历史计划已作废。

## 10. 普通手动任务多代码契约与执行语义

旧 `ops-submit-etf-minute-alignment`、`--batch-size` 和“一 action 一 TaskRun”契约全部退场，不保留 alias、兼容入口或专用执行 payload。P9A Preview 只负责审计覆盖和输出代码清单；正式执行统一回到现有手动动作：

```text
POST /api/v1/ops/manual-actions/etf_mins/task-runs
time_input = {mode: range, start_date, end_date}
filters = {ts_code: [多个代码], freq: [多个频率]}
```

手动动作服务仍只创建一个普通 `dataset_action / etf_mins / maintain` TaskRun。它不读取 Preview JSON，也不保存 plan hash、target hash、action 数组或 execution scope hash。

### 10.1 Definition、API 与前端

`market_fund.py` 中 `etf_mins.ts_code` 改为：

```text
field_type = string
multi_value = true
required = false
```

描述明确“多个代码用逗号分隔；不填写时维护全部当前可请求 ETF”。manual action query/catalog 继续从 Definition 投影 `multi_value`，不新增 ETF 专用 API 字段。

现有前端对非枚举多值字段已经使用文本输入，并在提交时按逗号拆成数组，因此生产组件原则上不修改；只补 ETF 分钟目标测试，证明请求体是 `ts_code: ["代码1", "代码2"]`。后端 `ManualActionTaskRunResolver` 已能接收字符串数组或逗号字符串并规范为 list，无需新增解析器。

Definition 是手动与 schedule 共用事实源，因此技术上 schedule filter 也会接受代码数组；当前生产 schedule 39 不配置 `ts_code`，仍走全量 Basic snapshot，行为不变。本需求不新建或改写 schedule，也不增加“仅手动可多选”的旁路契约。

### 10.2 Planner 扇开

`DatasetActionResolver`、dispatcher 和 TaskRun schema 不增加专用分支。普通 resolver 将 `filters_json.ts_code` 数组交给 `_build_etf_mins_units()`：

```text
固定一次中国资格日期
-> 规范化显式代码
-> 单代码查一次 target；多代码/无代码加载一次 snapshot
-> 校验全部显式代码
-> 每个代码独立执行 effective_start=max(requested_start,list_date)
-> 代码 × 频率 × build_etf_minute_windows() 扇开 unit
```

unit 排序固定为规范化代码顺序、Definition 频率顺序、窗口时间顺序。每个 unit 的 request params 仍只有一个标量代码、一个频率和一个窗口；数组只存在于 TaskRun filters，不进入 Tushare 请求。

任一代码当前不可请求或其整个显式窗口早于上市日，整次 plan 失败，TaskRun 不进入源请求。不会静默跳过坏代码，也不会部分执行输入列表。

`EtfMinuteHistoryAlignmentPlanService._parse_task_coverage()` 同步支持两种已成功 TaskRun：历史 `ts_code="单代码"` 与新 `ts_code=["代码1", "代码2"]`。新数组必须全部为非空字符串，规范化、去重后按代码 × 合法频率生成覆盖；非法数组整条忽略，不能把任务级总行数猜成单代码覆盖。

### 10.3 不修改的运行时行为

一个 TaskRun 仍只统一运营意图，不是一个数据库大事务。以下现有行为原样保留：

1. 一个 dataset-plan node、多个 unit，`plan_snapshot` 只显示既有上限内的样本。
2. `fetch_concurrency=2`、每 unit 独立提交、幂等 raw upsert。
3. 现有 fail-fast、取消、进度汇总和通用 retry 语义。
4. 现有分页、限流、normalizer、writer 和 issue 处理。

因此不修改 dispatcher、TaskRun service/progress/query/API、前端任务详情、数据库 migration、Settings 或 schedule 契约，也不增加 `etf_mins` 全局 open-task 互斥。

### 10.4 旧 Submit 删除范围

已删除：

```text
src/ops/services/etf_minute_history_alignment_submit_service.py
tests/test_etf_minute_history_alignment_submit_service.py
tests/test_cli_ops_submit_etf_minute_alignment.py
```

并从 `src/cli.py`、`src/cli_parts/ops_handlers.py` 删除 Submit 的 import、handler 和命令。保留 Preview service、Preview CLI 和对应测试；同时修改 Preview coverage parser 及其测试，使成功的多代码手动 TaskRun 可作为源端空结果窗口的请求证据。

### 10.5 本轮生产输入与已知取舍

停止后 Preview 的精确缺口为 181 个代码、182 个 action、1,333 个 unit。一个普通手动任务使用：

```text
start_date = 2026-01-05
end_date = 2026-08-28
freq = 1min,5min,15min,30min,60min
ts_code = Preview 输出的 181 个去重代码
```

planner 会按每个代码的 `list_date` 再裁剪起点。唯一已知的额外请求是 `159539.SZ`：其 `1min` 实际只缺 `2026-07-01..2026-08-28`，统一日期输入会额外请求 2026 年上半年的三个 2 个月窗口。幂等 upsert 不会产生重复事实，但 unit 预计从 1,333 增为 1,336，请求边界从 1,333–5,332 增为 1,336–5,344。本轮以“一个普通手动任务”优先，接受这三个额外 unit；若未来要求绝对零重复，应拆成独立手动任务，而不是恢复专用 Submit。

生产执行前确认 open `etf_mins` TaskRun 为 0，并避开 schedule 39 执行窗口；若预计重叠则临时暂停它。任务完成后复核 raw 物理覆盖并重跑 Preview。代码开发与回归已完成；未部署且未获得独立执行授权，不得继续生产补拉。

## 11. 实施验收记录

2026-08-29 完成代码实施：Definition 多值契约、单代码/多代码/无代码三条 Basic 查询路径、多代码整单失败、按上市日分代码裁剪、稳定 unit 扇开、Preview 多代码覆盖还原和旧 Submit 清零均已落地。一次 manual API POST 保存一个 TaskRun 及数组 `filters_json.ts_code`，每个实际 unit 仍只带一个标量代码。

目标后端测试 247 项、架构护栏 61 项、前端全量 147 项、Ruff、typecheck、rules 和 build 通过。全量 CLI 只保留已在 P8-P10 记录的无关 progress reporter 旧失败；本轮不修改该共享能力。CodeGraph 后置复核确认多代码开关只在 ETF 分钟链开启，沪深申赎和 Preview 之外没有新消费者。
