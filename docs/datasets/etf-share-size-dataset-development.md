# ETF 份额规模（`etf_share_size`）数据集接入方案

状态：已完成；继续按交易日请求源端全集，raw 直出 serving
最近更新：2026-08-29
LLD：[ETF 份额规模 LLD v1](/Users/congming/github/goldenshare/docs/datasets/etf-share-size-low-level-design-v1.md)
源站文档：[0408 ETF 份额规模](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0408_ETF份额规模.md)

## 1. 当前结论

`etf_share_size` 的正式维护方式是“一个交易日一个全市场 unit”。不填写 `ts_code` 时请求源端当日完整结果；区间由 resolver 按交易日展开，每个交易日仍只发一个全市场请求。

这个数据集不读取 ETF Basic，也不读取任何激活池。原因不是临时绕过，而是业务语义本身：源端接口能按交易日直接返回当日全集，逐 ETF 扇出会增加请求量并可能截断源端真实范围。

## 2. 请求与时间

| 输入 | unit / 参数 |
| --- | --- |
| 单日，不填代码 | 一个 unit：`trade_date` |
| 单日，填单代码 | 一个 unit：`trade_date + ts_code` |
| 区间 | 按交易日展开，每个日期一个 unit |

显式入口一次只允许一个代码。它是源接口定位能力，不把该代码送入 Basic 资格校验。分页由 source client 追加 `limit/offset`，单页上限 5,000。

## 3. 字段与存储

保存源端全部业务字段：

```text
trade_date, ts_code, etf_name, total_share,
total_size, nav, close, exchange
```

主键为 `(trade_date, ts_code)`。唯一物理表是 `raw_tushare.etf_share_size`，`core_serving.etf_share_size` 为普通 view，逐列读取 raw。业务层面 raw 与 serving 没有转换差异，因此不新建 core 表或第二份 serving 物理表。

## 4. Definition 与事务

| 维度 | 当前合同 |
| --- | --- |
| date model | `trade_open_day + every_open_day + point_or_range` |
| universe | `no_pool` |
| storage | `raw_only_upsert` + serving view |
| commit | 一个交易日 unit 的页面聚合后一次提交 |
| freshness | 观测 `trade_date` |
| completeness | 不进入日期完整性审计 |
| workflow | 不加入既有 workflow |

## 5. 历史对账如何理解

旧文档曾拿 1,395 个 ETF 激活池代码与多个交易日的源端结果对账，目的是证明源端当日全集包含池内对象且还会返回池外对象。该数字是带日期的历史测量证据，只支持“不能按旧池裁剪源端结果”这一结论，不构成当前范围或固定数量门禁。

P8 删除旧池不会改变 `etf_share_size` 的代码、请求、表、view 或运营流程。明确禁止为了“统一使用 Basic”把本数据集改造成逐 ETF 请求。
