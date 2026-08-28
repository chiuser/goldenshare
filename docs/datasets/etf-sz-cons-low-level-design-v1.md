# `etf_sz_cons` 低层设计 LLD v1

状态：当前实现基线；Basic 驱动 planner 已完成
最近更新：2026-08-29
上位方案：[ETF 每日持仓组合（深市）数据集接入方案](/Users/congming/github/goldenshare/docs/datasets/etf-sz-cons-dataset-development.md)

## 1. 执行链与边界

```text
DatasetActionResolver
-> _build_etf_sz_cons_units
-> EtfBasicDAO requestability(exchange="SZ")
-> _split_calendar_month_windows
-> _etf_sz_cons_params
-> source client(offset_limit)
-> normalizer
-> raw_only_upsert
-> raw_tushare.etf_sz_cons
-> core_serving.etf_sz_cons view
```

不创建新的持久化选择池，不修改其他数据集、workflow 或实时链。

## 2. Definition

| 项 | 当前值 |
| --- | --- |
| key/API | `etf_sz_cons` |
| date model | `trade_open_day + every_open_day + point_or_range` |
| input | 单日或区间，可选单 `ts_code` |
| universe | `pool` 技术形状；source=`core_serving_etf_basic`，无 resource |
| page limit | 3,000 |
| source fields | 11 个 |
| storage | raw 物理表 + serving view |
| conflict key | `(trade_date, ts_code, con_code)` |
| completeness | `not_applicable`，只接 freshness |

## 3. Planner

`_build_etf_sz_cons_units()` 在一次调用开始时固定 `eligibility_as_of`，然后通过公共 resolver 限定 `exchange='SZ'`。显式和全量查询次数分别固定为一次 target / 一次 snapshot，不允许循环查询 Basic。

公共上市日裁剪发生在拆窗之前：

```text
effective_start = max(requested_start, target.list_date)
```

point 模式生成一个单日 unit；range 模式从 `effective_start` 起按自然月连续拆窗。每个 unit 的 `progress_context` 记录固定资格日期、主数据上市日、原始起点和有效起点。

## 4. Builder、分页和事务

`_etf_sz_cons_params()` 输出：

```text
point: ts_code, trade_date
range: ts_code, start_date, end_date
```

source client 负责 `limit/offset` 与短页终止。一个 unit 的页面必须全部成功后再归一化和 upsert；业务键冲突按当前 raw DAO 幂等处理。Serving view 只投影 raw，不重复过滤 Basic。

## 5. 测试门禁

1. `.SZ` 当前可请求 ETF 的 point/month-range unit。
2. `.SH/.OF`、状态、上市日、exchange 冲突反例。
3. 显式/全量 Basic 查询次数和固定日期。
4. 上市日裁剪发生在自然月切窗前。
5. 空集合与显式越界的结构化错误。
6. 3,000 行分页、短页终止、字段归一化、raw/view 与幂等写入。
7. 不出现旧 resource、DAO、seed 或 fallback。

## 6. 生产边界

历史 720 行旧池已不再被代码读取。P8 删除代码基础设施并新增不可逆 drop migration，但没有执行生产迁移；既有 `etf_sz_cons` 事实、表和 view 均不删除或重建。
