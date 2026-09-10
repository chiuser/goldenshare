# ETF 每日持仓组合（深市）（`etf_sz_cons`）维护说明

状态：已完成生产接入；对象来源已切换为 ETF Basic Serving
最近更新：2026-09-10；原 LLD 的执行、错误码与回归要求已并入本文。
源站文档：[0472 ETF 每日持仓组合（深市）](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0472_ETF每日持仓组合(深市）.md)

## 1. 当前结论

`etf_sz_cons` 保存深交所 ETF 每日持仓组合。源端一个交易日全市场结果曾触及 3,000 行单页上限，因此正式主链按 ETF code 展开，不把“单日全市场正好 3,000 行”误判为完整结果。

对象来源已经从独立运营池切换为 `core_serving.etf_basic` 的当前可请求 `.SZ` ETF。每次 plan 固定中国自然日，显式代码只查一次 target，全量只加载一次深市 snapshot，并把请求起点裁到 `list_date`。

## 2. 请求策略

| 模式 | unit | 源参数 |
| --- | --- | --- |
| 单日 | 一个 `.SZ` ETF | `ts_code + trade_date` |
| 区间 | 一个 `.SZ` ETF × 一个自然月窗口 | `ts_code + start_date + end_date` |

区间不展开为“ETF × 每个交易日”，也不把宽区间直接交给源端。分页由 source client 统一使用 `limit/offset`，单页 3,000 行。

## 3. 对象门禁

统一 Basic selector 要求 `L + 有效且不晚于固定日期的 list_date + .SH/.SZ + 后缀与 exchange 一致`，本数据集再限定 `exchange='SZ'`。

- 全量 snapshot 为空：`universe_empty`。
- 显式代码不合格：`etf_not_requestable`。
- 显式多代码：`invalid_enum`。
- 窗口整体早于上市日：全量不生成 unit，显式请求返回 `window_before_list_date`。
- selector 异常：任务失败，不回退旧池或全市场请求。

## 4. 字段与存储

保存字段：

```text
trade_date, ts_code, con_code, con_name, qty,
sub_flag, cpr, rdr, sub_cc, red_cc, exchange
```

业务主键为 `(trade_date, ts_code, con_code)`。唯一物理表是 `raw_tushare.etf_sz_cons`；`core_serving.etf_sz_cons` 为普通 view。写入使用 `raw_only_upsert`，一个 ETF 的单日/自然月窗口内所有页面归一化后一次提交。

## 5. 运营与历史

支持手动和普通定时 `maintain`，不加入既有 workflow，不新增专用 probe。V1 使用 `trade_date` 做 freshness，不构造日期 × ETF 完整性矩阵。

旧实现曾 seed 726 个候选，并在源端复核后形成 720 行运营池；2026-08-29 退场审计时旧表仍为 720 行。这只是历史证据，不再控制请求，也不能作为当前深市 ETF 固定数量。后续 2026-08-29 P11 记录已确认旧池表不存在，见 [ETF 专项历史记录](/Users/congming/github/goldenshare/docs/architecture/etf-basic-rebuild-and-downstream-data-audit-cleanup-low-level-design-v1.md)。不能继续安排生产 drop，也不把该记录当成本轮生产复验。

## 6. 执行落点（合并原 LLD）

[market_fund Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_fund.py)声明 `trade_open_day + every_open_day + point_or_range`；universe 为 pool 技术形状，source 为 `core_serving_etf_basic`、无 resource；completeness scope 为 not_applicable，date_model.audit_applicable 为 False。它不表示没有日期输入，也不恢复持久化运营池。

[planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)的 `_build_etf_sz_cons_units` 调用公共 selector，再执行 `_resolve_effective_etf_start` 和 `_split_calendar_month_windows`。每次 plan 固定一个中国自然日作为资格日期；[EtfBasicDAO](/Users/congming/github/goldenshare/src/foundation/dao/etf_basic_dao.py)的显式 target / 全量 snapshot 入口各最多调用一次，不在 ETF 循环中重新查主数据。

unit 进度保留代码、日期窗口及 `eligibility_as_of/master_list_date/requested_start_date/effective_start_date`。[builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)的 `_etf_sz_cons_params` 只生成第 2 节源参数；[source client](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)追加分页，满页继续、短页停止。一个 unit 不是一个页面。

trade_date 转日期；qty/cpr/rdr/sub_cc/red_cc 按 Decimal 归一化，三字段身份必填。当前质量策略为 record_rejections，不承诺任一拒绝都使整个 unit 失败；页拉取失败则不能将部分页当作完整 unit 发布。Serving view 不重复筛选 Basic、不因资格变化删除历史事实。

## 7. 回归与维护边界

保留 .SH/.OF、P/D、空/未来上市日、exchange 冲突等反例；显式多代码在 Basic 查询前拒绝；验证单代码/全量查询次数、固定资格日、先裁上市日再切月窗、空集合和越界错误。

入口：[resolver](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)、[Basic DAO](/Users/congming/github/goldenshare/tests/test_etf_basic_dao.py)、[分页](/Users/congming/github/goldenshare/tests/test_dataset_source_client.py)、[归一化](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py)、[模型](/Users/congming/github/goldenshare/tests/test_etf_sz_cons_model.py)、[writer](/Users/congming/github/goldenshare/tests/test_dataset_writer_etf_sz_cons.py)、[workflow 边界](/Users/congming/github/goldenshare/tests/test_etf_sz_cons_ops_contract.py)。

本次不恢复旧 resource/DAO/seed、不新增 fallback，不删除或重建现行 Raw/view，不修改其他数据集、workflow 或实时链。历史代码与原 LLD 全文从 Git 追溯。
