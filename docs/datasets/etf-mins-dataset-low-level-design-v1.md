# ETF 历史分钟行情数据集 LLD v1

状态：当前实现基线；Basic 驱动 planner、指定区间 P9A Preview 与 P9B 受控 Submit 代码已完成；原全历史 Preview 已作废，生产 TaskRun 与补拉均未执行
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
| input | `trade_date` 或 `start_date/end_date`；可选单 `ts_code`；必填多选 `freq` |
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
显式 ts_code
-> EtfBasicDAO.get_requestable_target(..., as_of_date, exchange=None)

未显式 ts_code
-> EtfBasicDAO.load_requestability_snapshot(..., as_of_date, exchange=None)
```

公共 `_validate_requestable_etf_universe()` 固定 Definition 必须绑定 `ts_code` 且 source 精确为 `core_serving_etf_basic`。公共 `_resolve_requestable_etf_targets()` 负责单代码门禁、空集合错误与返回顺序。

禁止：

1. planner 自行拼 Basic SQL。
2. 自动计划逐 ETF 查询 Basic。
3. 显式计划为方便而加载全市场 snapshot。
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
3. 自动计划每次只加载一次 snapshot；显式代码只查一次 target。
4. 请求起点早于上市日时裁到 `list_date`。
5. 全量窗口整体早于上市日不生成 unit；显式代码返回结构化错误。
6. 五频率窗口边界、月末、闰年、连续不重叠。
7. request builder 不注入 pool resource 或额外 ETF 条件。
8. 分页、24,000 行上限、rejection、重复身份和幂等写入。

## 8. 发布和数据边界

P3 的代码迁移不执行生产补拉。P8 只删除旧池代码并准备 migration，没有执行生产 DDL。P11 已完成生产旧表删除与 Basic 正式重建；分钟全量对齐必须先在重建后快照上重新生成只读 preview，再按 P12 独立额度授权创建正式 TaskRun。

## 9. P9A 全量对齐 Preview

公开入口固定为：

```text
goldenshare ops-preview-etf-minute-alignment --alignment-start-date YYYY-MM-DD --alignment-end-date YYYY-MM-DD [--output plan.json]
```

服务在一次 `REPEATABLE READ + READ ONLY` 事务中固定 UTC 时钟、中国资格日期、指定区间内的 SSE 开市日和 Basic snapshot，并设置每条语句 180 秒 statement timeout。全部当前可请求 ETF 进入 `request_target_hash`；只有 `list_date <= alignment_end_date` 的对象进入五频率覆盖计算，晚于截止日的对象单独计数。每只 ETF 的 effective start 是不早于 `max(alignment_start_date, list_date)` 的首个 SSE 开市日。

raw 边界从最早 effective start 所在月到截止月逐月统计。每月一条 SQL 固定返回 `ts_code/freq/COUNT/MIN/MAX`，日期使用 `[month_start, next_month_start)`，必须只裁到该月分区；数据库查询不关联 Basic，服务在内存中再按 target desired interval 裁剪。查询次数只随指定区间覆盖的月份数增长，不随 ETF、频率或历史上市年限增长。月内允许只扫描该月分区；如果触及其他月份或单月达到 180 秒超时，阶段立即停止，不自动按周重试、不加索引、不提高超时。

覆盖区间先裁到 `[effective_start_date, alignment_end_date]`，仅生成 prefix/suffix。内部 gap 明确不审计；候选缺口不含任何 SSE 开市日时直接丢弃。无 raw 但有成功显式任务时只能记为 `successful_task_only_covered_target_frequency_count`，不能声称源端返回零行。每个有效缺口复用 `build_etf_minute_windows()` 计算 unit，相同代码和日期范围才合并频率。

P9A 只输出 plan、摘要和可选 JSON 文件；不调用 connector/writer/TaskRunCommandService，不 commit、不提供 submit/apply 参数。生产规模报告由本地未部署代码在同一个只读事务中直接生成，不部署服务。

2026-08-29 的 Prod 只读执行以 `2026-01-01` 至 `2026-08-28` 为指定区间、`2026-08-29` 为资格日期，约 32 秒完成且没有触发单月 180 秒门禁。1,647 个 requestable target 全部进入 alignment；五频率 raw 覆盖合计 6,975 个 target/frequency，252 个 ETF 的 prefix 缺口合计 1,260 个 target/frequency，suffix 缺口 0，成功 TaskRun-only 覆盖 0。最终计划有 252 个 action、1,774 个 unit，请求上下界为 1,774–7,096；167 个 action 从首个开市日 `2026-01-05` 开始，85 个按更晚上市日开始。此前无开始日、默认追溯上市日的全历史计划已作废。

## 10. P9B Submit 事务与门禁

唯一入口固定为：

```text
goldenshare ops-submit-etf-minute-alignment --plan plan.json --confirm-plan-hash <sha256> --batch-size <正整数>
```

计划 JSON 必须与 P9A 固定 schema 完全一致，人工确认 hash 必须等于文件 hash，去掉自身字段后的规范 JSON 复算 hash 也必须一致。action 代码、五频率顺序、日期、稳定排序和 `build_etf_minute_windows()` unit 数全部重验；文件无效时不打开数据库会话。

数据库阶段使用单个 `REPEATABLE READ` 事务和 180 秒语句门禁。PostgreSQL 先取得 P9B 专用 transaction advisory lock，持锁后和 stage 前分别拒绝 open `etf_mins` TaskRun。submit 固定一次 UTC/中国日期，一次加载 Basic snapshot，复算 target hash并用内存 map 校验所有代码与上市日；同一 snapshot 交给 P9A service 复用 SSE 日历、月度 raw 覆盖和成功 TaskRun 覆盖查询。

原 action 已完全覆盖时幂等跳过；仍缺失时必须保持代码、频率集合和日期范围精确一致。部分频率或部分日期变化会整批返回 `plan_coverage_changed`，不能拿旧范围重复请求，也不能由 submit 自行缩改范围。选中的前 `batch-size` 个 action 只通过 `TaskRunCommandService.stage_task_run()` 创建现有 `etf_mins` range TaskRun；全部 stage 成功后一次 commit，任一失败全部 rollback。正式 resolver/planner 仍会在 worker 执行时再次应用当前 ETF 资格和上市日门禁。

首次生产批次已拍板为 10 个 action，但 `--batch-size` 仍必填且没有默认配置。P9B 开发没有运行该命令；生产 TaskRun、Tushare 请求和分钟写入均为零，下一步是 P10 候选环境发布门禁。
