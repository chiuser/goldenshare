# 上交所 ETF 申赎清单（`etf_sh_cons`）数据集开发说明

状态：已落地；对象来源已切换为 ETF Basic Serving
最近更新：2026-08-29
LLD：[ETF 申赎清单低层设计 v1](/Users/congming/github/goldenshare/docs/datasets/etf-sh-cons-low-level-design-v1.md)
源站文档：[Tushare 0407 ETF 申赎清单](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0407_ETF申赎清单.md)

## 1. 当前结论

`etf_sh_cons` 保存上交所 ETF 申赎清单源站事实。当前代码按 ETF 代码展开请求，但对象不再来自独立激活池，而是每次 plan 从 `core_serving.etf_basic` 取得当前可请求 `.SH` ETF，并按 `list_date` 裁剪请求起点。

数据只物理写入 `raw_tushare.etf_sh_cons`；`core_serving.etf_sh_cons` 是普通 view，逐列直出 raw，不新建第二份物理表。

## 2. 对象与时间口径

每次 plan 固定一个中国自然日。合格对象必须同时满足统一 Basic selector 和 `exchange='SH'`。未填写 `ts_code` 时加载一次上交所 snapshot；显式代码只查询一次 target。显式多代码、不可请求代码或 `.SZ/.OF` 代码直接失败，不回退旧池或全市场猜测。

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

旧实现曾使用 `resource='etf_sh_cons'`，2026-08-29 退场前生产表中有 803 行。该数字只是历史运营池快照，不是当前上交所 ETF 数量门禁。P3 已迁移 planner，P8 已删除旧池基础设施并准备 drop migration。

不做：恢复 seed/Review、按历史固定数量验收、逐交易日区间扇出、对 raw/view 做重复存储、因当前 Basic 状态变化删除既有申赎事实。
