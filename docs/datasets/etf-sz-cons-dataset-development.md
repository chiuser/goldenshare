# ETF 每日持仓组合（深市）（`etf_sz_cons`）数据集接入方案

状态：已完成生产接入；对象来源已切换为 ETF Basic Serving
最近更新：2026-08-29
LLD：[ETF 每日持仓组合（深市）LLD v1](/Users/congming/github/goldenshare/docs/datasets/etf-sz-cons-low-level-design-v1.md)
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

旧实现曾 seed 726 个候选，并在源端复核后形成 720 行运营池；2026-08-29 退场审计时旧表仍为 720 行。这只是历史证据，不再控制请求，也不能作为当前深市 ETF 固定数量。P3 已迁移 planner，P8 已删除旧基础设施并准备生产待执行的 drop migration。
