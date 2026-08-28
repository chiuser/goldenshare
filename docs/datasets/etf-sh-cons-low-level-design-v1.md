# ETF 申赎清单（`etf_sh_cons`）低层设计 v1

状态：当前实现基线；Basic 驱动 planner 已完成
最近更新：2026-08-29
上位方案：[ETF 申赎清单数据集开发说明](/Users/congming/github/goldenshare/docs/datasets/etf-sh-cons-dataset-development.md)

## 1. 执行链

```text
DatasetActionResolver
-> _build_etf_sh_cons_units
-> EtfBasicDAO requestability(exchange="SH")
-> _etf_sh_cons_params
-> DatasetSourceClient(offset_limit)
-> normalizer
-> raw_only_upsert
-> raw_tushare.etf_sh_cons
-> core_serving.etf_sh_cons view
```

## 2. Definition 合同

当前 Definition 在 `src/foundation/datasets/definitions/market_fund.py`：

| 项 | 值 |
| --- | --- |
| key/API | `etf_sh_cons` |
| source fields | 10 个源字段，身份为 `trade_date/ts_code/con_code` |
| date input | `trade_date` 或 `start_date/end_date` |
| filter | 可选单 `ts_code` |
| universe source | `core_serving_etf_basic`，无 resource |
| page limit | 3,000 |
| storage | `raw_only_upsert` + serving view |
| commit | 一个 ETF 的单日/半年窗口 unit 一次提交 |
| completeness | `not_applicable`，只接 freshness |

## 3. Planner

`_build_etf_sh_cons_units()` 只计算一次当前中国日期，并调用公共 `_resolve_requestable_etf_targets(..., exchange='SH')`：

- 显式代码：`get_requestable_target()` 一次；
- 全量：`load_requestability_snapshot()` 一次；
- 空集合：`universe_empty`；
- 不合格显式代码：`etf_not_requestable`。

之后用公共 `_resolve_effective_etf_start()` 把请求起点裁到 `list_date`。单日保留一个日期 unit；区间使用 `_split_calendar_half_year_windows()`，窗口连续、无重叠。全量窗口整体早于上市日不生成 unit，显式代码则报 `window_before_list_date`。

## 4. Request builder 与写入

`_etf_sh_cons_params()` 只接受 planner 生成的代码和日期：

```text
point -> ts_code + trade_date
range -> ts_code + start_date + end_date
```

`limit/offset` 由 source client 统一追加。所有页面拉完后归一化 `trade_date` 与 `qty`，要求 `trade_date/ts_code/con_code` 非空，再按三列业务键幂等 upsert。Serving view 不进行 ETF Basic 二次过滤；Basic 只决定新请求对象和起点。

## 5. 测试门禁

1. `.SH` 当前可请求目标可生成单日和半年窗口。
2. `.SZ/.OF`、`P/D`、空/未来上市日、exchange 冲突被拒绝。
3. 显式代码只查单 target，全量只加载一次 snapshot。
4. 上市日前窗口裁剪、全量跳过和显式结构化错误均正确。
5. builder 参数不含旧 resource，分页只由 source client 加入。
6. raw/view schema、主键、幂等写入和字段映射不变。
7. 指数激活池、其他 ETF 数据集和 workflow 不受影响。

## 6. 退场边界

旧 DAO、seed service、CLI 和 `resource='etf_sh_cons'` 已从当前代码删除。历史 create migration 保留；P8 只准备 drop migration，不执行生产 DDL，也不删除既有申赎清单事实。
