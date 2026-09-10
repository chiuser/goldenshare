# ETF 份额规模（`etf_share_size`）维护说明

状态：已完成；继续按交易日请求源端全集，raw 直出 serving
最近更新：2026-09-10；原 LLD 的执行与回归要求已并入本文。
源站文档：[0408 ETF 份额规模](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0408_ETF份额规模.md)

## 1. 当前结论

`etf_share_size` 的正式维护方式是“一个交易日一个全市场 unit”。不填写 `ts_code` 时请求源端当日完整结果；区间由 resolver 按交易日展开，每个交易日一个全市场 unit；unit 内可以分页，不能把一个 unit 当成一次源请求。

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

旧池退场不改变 `etf_share_size` 的代码、请求、表、view 或运营流程。明确禁止为了“统一使用 Basic”把本数据集改造成逐 ETF 请求。

## 6. 执行与校验（合并原 LLD）

[market_fund Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/market_fund.py) → [planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py) 的 `_build_etf_share_size_units` → [builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py) 的 `_etf_share_size_params` → [source client](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py) → normalizer → raw_only_upsert。

- 规范化可选代码后，多代码报 `invalid_enum`；无代码时使用一个空枚举组合，不按 ETF 数量扇出。
- 单日一个 anchor；区间使用通用交易日 anchor。单代码只加入同一个日期 unit，不查询 Basic、旧池或 fallback。
- builder 只输出 trade_date，按需追加 ts_code；source client 追加 limit/offset，每页带相同八个 fields。满页继续，短页停止；5,000 不是日总行数上限。
- trade_date 必须有效；total_share/total_size/nav/close 转 Decimal，身份两列必填。现行质量策略为 record_rejections，不将其描述为任一拒绝整日失败。
- unit 页面全部拉取后写 Raw；Serving view 无第二次写入或 Basic 过滤。页拉取失败不能发布部分 unit；SQL batch 不改变 unit 提交边界。
- 来源字段 exchange 的值与 Basic selector 的 SH/SZ 资格值不是同一套过滤规则，不能据名称替换。

## 7. 回归与文档边界

[resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)覆盖单日全市场、区间交易日展开、显式单代码和多代码拒绝；[source client](/Users/congming/github/goldenshare/tests/test_dataset_source_client.py)、[normalizer](/Users/congming/github/goldenshare/tests/test_dataset_normalizer.py)、[模型](/Users/congming/github/goldenshare/tests/test_etf_share_size_model.py)、[writer](/Users/congming/github/goldenshare/tests/test_dataset_writer_etf_share_size.py)与 [workflow 边界](/Users/congming/github/goldenshare/tests/test_etf_share_size_ops_contract.py)保护字段、分页和 Raw-only 行为。

本次只合并原 LLD，不新建 core/serving 表、不改消费者或分页参数、不执行任何同步。历史源端对账仍是当时证据，不保证未来源站范围不变；更大范围维护按数据集模板重新评估。
