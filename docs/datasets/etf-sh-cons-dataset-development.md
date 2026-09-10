# 上交所 ETF 申赎清单（`etf_sh_cons`）维护说明

状态：已落地；对象来源已切换为 ETF Basic Serving
最近更新：2026-09-10；原 LLD 的执行、错误码与回归要求已并入本文。
源站文档：[Tushare 0407 ETF 申赎清单](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0407_ETF申赎清单.md)

## 1. 当前结论

`etf_sh_cons` 保存上交所 ETF 申赎清单源站事实。当前代码按 ETF 代码展开请求，但对象不再来自独立激活池，而是每次 plan 从 `core_serving.etf_basic` 取得当前可请求 `.SH` ETF，并按 `list_date` 裁剪请求起点。

数据只物理写入 `raw_tushare.etf_sh_cons`；`core_serving.etf_sh_cons` 是普通 view，逐列直出 raw，不新建第二份物理表。

## 2. 对象与时间口径

每次 plan 固定一个中国自然日。合格对象必须满足统一 Basic selector：`list_status='L'`、有效且不晚于 plan 固定日期的 `list_date`、`.SH/.SZ` 后缀与 exchange 一致；本数据集进一步限定 `exchange='SH'`。未填写 `ts_code` 时加载一次上交所 snapshot；显式代码只查询一次 target。显式多代码、不可请求代码或 `.SZ/.OF` 代码直接失败，不回退旧池或全市场猜测。

请求起点固定为：

```text
max(requested_start, list_date)
```

单日维护一个 `.SH` ETF 生成一个 unit，请求 `trade_date + ts_code`。区间维护按“ETF × 自然半年窗口”生成 unit，请求 `ts_code + start_date + end_date`；不是“ETF × 每个交易日”。

## 3. 源字段与存储

保存字段：

```text
trade_date, ts_code, con_code, con_name, qty,
sub_flag, cpr, rdr, sca, exchange
```

业务主键为 `(trade_date, ts_code, con_code)`。写入使用 `raw_only_upsert`，分页为 `offset_limit`、单页 3,000 行；同一 unit 的页面全部拉取和归一化后一次提交。

## 4. DatasetDefinition 与运营

| 维度 | 当前合同 |
| --- | --- |
| date model | `trade_open_day + every_open_day + point_or_range` |
| universe | `pool` 技术形状；source=`core_serving_etf_basic`，无 resource |
| action | 手动/定时 `maintain`，支持 point/range/retry |
| storage | raw 物理表 + serving view |
| freshness | 使用 `trade_date` |
| completeness | V1 不做日期-ETF 完整性矩阵 |
| workflow | 不加入 `daily_market_close_maintenance` |

## 5. 历史证据与非目标

旧实现曾使用 `resource='etf_sh_cons'`，2026-08-29 退场前生产表中有 803 行。该数字只是历史运营池快照，不是当前上交所 ETF 数量门禁。后续 2026-08-29 P11 记录已确认旧池物理表不存在，不能继续写成生产 drop 待执行；见 [ETF 专项历史记录](/Users/congming/github/goldenshare/docs/architecture/etf-basic-rebuild-and-downstream-data-audit-cleanup-low-level-design-v1.md)。这不是本轮重新查询生产的结果。

不做：恢复 seed/Review、按历史固定数量验收、逐交易日区间扇出、对 raw/view 做重复存储、因当前 Basic 状态变化删除既有申赎事实。

## 6. 执行落点与错误边界（合并原 LLD）

[market_fund Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_fund.py) → [planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py) 的 `_build_etf_sh_cons_units` → [request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py) 的 `_etf_sh_cons_params` → [source client](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py) → normalizer / raw-only writer。

- 通过公共 `_resolve_requestable_etf_targets` 和 [EtfBasicDAO](/Users/congming/github/goldenshare/src/foundation/dao/etf_basic_dao.py)取对象：显式单代码一次 target 查询入口，全量一次 snapshot；不在对象循环里反复查询 Basic。明显错误的代码可在查询前拒绝。
- 多代码报 `invalid_enum`，全量空集合报 `universe_empty`，显式不可请求报 `etf_not_requestable`；selector 异常不回退旧池。
- 公共 `_resolve_effective_etf_start` 在半年切窗前裁剪上市日。窗口整体早于上市日时，全量跳过该对象，显式请求报 `window_before_list_date`。
- 区间使用 `_split_calendar_half_year_windows`，连续且无重叠；进度保留代码、日期窗口、`eligibility_as_of/master_list_date/requested_start_date/effective_start_date`。
- source client 统一追加 limit/offset；满页继续、短页停止，一个 unit 可能多次请求。trade_date 转日期、qty 转 Decimal，身份三列必填；现行质量策略为 record_rejections，不冒充财务指标的“任一拒绝整日失败”合同。
- Serving view 逐列投影 Raw，不再次用 Basic 过滤历史事实；当前 Basic 状态变化不授权删除既有清单。

## 7. 回归与退场边界

[resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)和 [Basic DAO 测试](/Users/congming/github/goldenshare/tests/test_etf_basic_dao.py)覆盖市场、状态、上市日、显式/全量查询和半年窗口；分页、归一化分别见 [source client 测试](/Users/congming/github/goldenshare/tests/test_dataset_source_client.py)、[normalizer 测试](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py)，存储见 [模型测试](/Users/congming/github/goldenshare/tests/test_etf_sh_cons_model.py)、[writer 测试](/Users/congming/github/goldenshare/tests/test_dataset_writer_etf_sh_cons.py)。

旧池 DAO、seed、CLI 和 resource 已退场；历史 create/drop migration 保留，不重放。任何后续变更仍须保护指数池、其他 ETF 数据集和 workflow。本次只合并文档，不运行源请求、生产 DDL 或事实清理。
