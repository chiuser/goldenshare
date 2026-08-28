# `etf_share_size` 低层设计 LLD v1

状态：当前实现基线；不依赖 ETF Basic 或旧激活池
最近更新：2026-08-29
上位方案：[ETF 份额规模数据集接入方案](/Users/congming/github/goldenshare/docs/datasets/etf-share-size-dataset-development.md)

## 1. 执行链

```text
DatasetActionResolver
-> _build_etf_share_size_units
-> _etf_share_size_params
-> DatasetSourceClient(offset_limit)
-> normalizer
-> raw_only_upsert
-> raw_tushare.etf_share_size
-> core_serving.etf_share_size view
```

链路中没有对象池查询、Basic selector 或 hidden fallback。

## 2. Definition

当前 Definition 位于 `src/foundation/datasets/definitions/market_fund.py`：

| 项 | 值 |
| --- | --- |
| key/API | `etf_share_size` |
| date input | `trade_date` 或 `start_date/end_date` |
| filter | 可选单 `ts_code` |
| universe policy | `no_pool` |
| page limit | 5,000 |
| source fields | 8 个 |
| conflict key | `(trade_date, ts_code)` |
| storage | `raw_only_upsert` + serving view |
| completeness | `not_applicable` |

## 3. Planner 与 request builder

`_build_etf_share_size_units()`：

1. 规范化可选 `ts_code`，多于一个直接返回 `invalid_enum`。
2. 使用通用日期 anchor：单日一个 anchor，区间按开市日展开。
3. 没有显式代码时 `enum_combinations=[{}]`，因此每个交易日恰好一个全市场 unit。
4. 有显式代码时只把该代码加入同一个日期 unit。

`_etf_share_size_params()` 只输出 `trade_date`，可选追加 `ts_code`。`limit/offset` 仍由 source client 负责，不能暴露给运营输入。

## 4. Normalizer、写入和 view

日期字段 `trade_date` 必须有效；`total_share/total_size/nav/close` 按 Decimal 归一化；身份字段 `trade_date/ts_code` 必填。unit 内所有页面完成后按两列主键幂等 upsert，一次提交。

Serving view 是空间优化设计：业务层不需要不同于 raw 的转换时，保留一份物理事实，通过稳定的 serving 名称读取。P8 不新建 core/serving 表，不迁移 view，也不让业务页面改读另一张表。

## 5. 测试与边界

必须证明：

1. 单日无代码只生成一个全市场 unit。
2. 区间按交易日生成 unit，不按 ETF 数量扇出。
3. 单代码参数正常，多代码拒绝。
4. planner 不调用 Basic selector、旧 DAO 或任何 fallback。
5. 5,000 行分页、字段归一化、主键幂等和 raw/view schema 正确。
6. 旧池退场不改变该数据集契约。

历史池数量只允许出现在明确的历史对账说明中，不能进入代码常量或验收断言。
