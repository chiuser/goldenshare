# 股票详情分钟线与分钟技术指标 API 标杆需求 v1

> 阶段：需求基线，编码前。
> 关联方案：[技术实施方案](./stock-detail-minutes-api-implementation-design-v1.md)
> 关联 LLD：[低级设计](./stock-detail-minutes-api-low-level-design-v1.md)
> 关联门禁：[M2 编码前门禁](./stock-detail-minutes-api-m2-coding-gate-v1.md)

## 1. 目标

为财势乾坤股票详情页增加本地分钟线和分钟 MACD/KDJ 查询能力。用户在本地访问 `http://127.0.0.1:5173/wealth/`，进入股票详情并选择分钟周期后，由本地业务 API 读取本地 Gold Lake 数据。

这不是远程生产数据能力。远程服务器没有对应分钟线文件，远程构建和运行时必须不挂载、不初始化、不暴露本模块。

## 2. 环境边界

| 环境 | 页面 | API | 数据源 | 分钟能力 |
|---|---|---|---|---|
| 本地 | `127.0.0.1:5173/wealth/` | 本地 `src/app/web`，默认 `127.0.0.1:8000` | `GOLDENSHARE_LAKE_ROOT` | 显式启用 |
| 远程 prod | 远程 wealth 页面 | 远程 `src/app/web` | 远程 Prod DB/ClickHouse | 禁用 |

远程环境必须满足：

1. 不安装 `local-lake` 可选依赖组中的 DuckDB。
2. 不导入分钟 API router。
3. 不创建 DuckDB connection。
4. `page-init` 返回 `supportsMinute=false`。
5. 前端不显示可用的分钟周期入口。
6. 直接访问分钟路径返回 404，而不是空数据。

## 3. 本期接口

保持现有日线 `/stock-detail/kline` 不变，新增：

```http
GET /api/v1/wealth/market/stock-detail/minutes
GET /api/v1/wealth/market/stock-detail/minute-indicators
```

两个接口均为单股票、单频率、有限日期范围、有限行数的只读查询。

## 4. 数据源

分钟线：

```text
gold/quote/stk_mins_qfq/freq={freq}m/ts_code={ts_code}/year={year}/part-000.parquet
```

分钟指标：

```text
gold/indicator/stk_mins_qfq_macd_kdj/freq={freq}m/ts_code={ts_code}/year={year}/part-000.parquet
```

当前支持频率为 `1/5/15/30/60/90/120m`，全部按前复权口径读取。指标只读 Gold 输出，不在 HTTP 请求中重新计算，不读取 state 文件。

## 5. 本期不做

1. 不修改 `lake_console/backend`，也不导入它的 router。
2. 不把本地 Lake 挂载到远程 prod。
3. 不在 API 请求中触发 Dagster、sensor、repair 或 materialization。
4. 不从 Tushare 请求实时数据。
5. 不读取 raw/silver 作为 API 主源。
6. 不新增实时行情、盘口、周线、月线或数据写入接口。
7. 不改变现有日线详情 API 契约。

## 6. 分钟线字段

| API 字段 | Lake 字段 | 语义 |
|---|---|---|
| `tsCode` | `ts_code` | 股票代码 |
| `freq` | `freq` | 分钟频率 |
| `tradeDate` | `trade_date` | 交易日 |
| `tradeTime` | `trade_time` | 北京时间分钟时间 |
| `open/high/low/close` | 同名字段 | 前复权价格 |
| `vol` | `vol` | 成交量，沿用湖单位 |
| `amount` | `amount` | 成交额，沿用湖单位 |
| `exchange` | `exchange` | 交易所 |

当前 Gold qfq 合同没有 `pre_close/change/pct_chg`。首版不返回、不推导、不伪造这些字段。

## 7. 分钟指标字段

| API 字段 | Lake 字段 |
|---|---|
| `macdDif` | `macd_dif_qfq` |
| `macdDea` | `macd_dea_qfq` |
| `macd` | `macd_qfq` |
| `kdjK` | `kdj_k_qfq` |
| `kdjD` | `kdj_d_qfq` |
| `kdjJ` | `kdj_qfq` |
| `paramsKey` | `params_key` |
| `indicatorVersion` | `indicator_version` |

指标预热不足时保持 NULL，不转成 0。

## 8. 请求与状态

统一参数：

| 参数 | 规则 |
|---|---|
| `tsCode` | 必填、规范化大写、严格代码格式 |
| `freq` | 必填；`1/5/15/30/60/90/120`，不设置默认频率 |
| `startDate/endDate` | 可选，`Asia/Shanghai`，区间不能反向 |
| `limit` | 默认 500 根，最大 10000 |
| `cursor` | 基于 `(tradeDate, tradeTime)` 的不透明游标 |
| `debug` | 默认关闭，仅本地排障 |

当前日线详情接口请求 300 根日 K，但图表默认实际可视区为 90 根。分钟接口不把 300 根解释为 300 个交易日，而是按页面首屏和有限拖动缓冲，统一默认返回 500 根分钟 K。500 根对应的覆盖长度随频率变化；完整查询仍通过 cursor 分页，不能把默认 500 根扩展成无界历史扫描。

`dataStatus` 固定为：

1. `READY`：请求范围内数据可读。
2. `DELAYED`：有数据但最新日期早于期望结束日。
3. `EMPTY`：请求合法但范围内没有记录。
4. `ERROR`：Lake、schema 或查询异常。

`endDate` 在 v1 同时作为查询上界和期望结束日；股票详情页必须传 page-init 的 `tradeDate`。未传 `endDate` 时不建立 freshness 期望日，空结果按 `EMPTY` 返回；传入 `endDate` 但没有数据或最新日期早于该日期时，按 `200 + dataStatus=DELAYED` 返回。

远程未启用不是 `EMPTY`，而是路由不存在。

## 9. 验收标准

1. 本地页面能读取分钟 OHLCV。
2. 本地页面能读取同频率 MACD/KDJ。
3. 两个接口按 `(tsCode, freq, tradeDate, tradeTime)` 对齐。
4. 远程 capability 为 false，分钟 route 不存在，不加载 DuckDB。
5. 远程日线详情不受本地 Lake 缺失影响。
6. API 不查询 Dagster event history，不触发任务，不写任何数据。
7. 单请求扫描年份文件和返回行数均有硬上限。

## 10. 已冻结口径

1. 使用 `minutes` 与 `minute-indicators` 两个接口，不扩展现有 `kline?period=min`。
2. 支持全部七个频率：`1/5/15/30/60/90/120m`。
3. `freq` 必须显式传入，不设置默认分钟频率。
4. 默认返回 500 根；分页上限和 90m/120m 的实际覆盖长度在性能测试中验证。
5. 首版不返回 `preClose/change/pctChg`。
6. 数据未准备好时返回 HTTP `200`，并设置 `dataStatus=DELAYED`；非法请求和真实查询异常仍按错误状态处理。
7. DuckDB 放入独立 `local-lake` 可选依赖组；本地安装该 extra，远程不安装。
8. Lake 根目录统一使用 `GOLDENSHARE_LAKE_ROOT`。

## 11. 版本记录

| 版本 | 日期 | 变更摘要 |
|---|---|---|
| v1 | 2026-07-31 | 初版，冻结本地启用、远程屏蔽和双接口边界 |
| v1.1 | 2026-07-31 | 冻结显式频率、500 根默认返回、DELAYED 状态和 local-lake 可选依赖 |
| v1.2 | 2026-07-31 | 明确 `endDate` 同时承担查询上界和期望结束日语义 |
