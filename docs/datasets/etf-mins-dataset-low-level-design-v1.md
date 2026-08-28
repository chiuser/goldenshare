# ETF 历史分钟行情数据集 LLD v1

状态：当前实现基线；Basic 驱动 planner 已完成，生产全量对齐待独立阶段
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

P3 的代码迁移不执行生产补拉。P8 只删除旧池代码并准备 migration，不执行生产 DDL。生产旧表删除与 Basic 正式重建留给 P11；分钟全量对齐必须先经 P9 只读 preview，再按 P12 独立额度授权创建正式 TaskRun。
