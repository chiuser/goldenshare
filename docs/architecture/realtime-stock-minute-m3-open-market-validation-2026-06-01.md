# A股实时分钟 M3 开市真实验证记录

状态：已完成  
验证时间：2026-06-01 10:35:00-10:38:32 CST（Asia/Shanghai，A 股连续竞价时段）  
验证对象：Tushare 0374 `rt_min`  
验证目的：进入 M4 provider / normalizer / feed 实现前，用真实开市请求固定接口行为。  

## 1. 验证边界

本次只做只读请求验证：

1. 不启动 realtime collector。
2. 不写 Redis。
3. 不调用 Biz / Ops API。
4. 不写数据库，不进入 DatasetDefinition / TaskRun / freshness。

本次使用 `tushareMcp.rt_min` 验证单代码和多代码关键字段行为。全市场统计与 `limit/offset` 补测使用同一 Tushare HTTP API 只读请求汇总，原因是 MCP 工具会返回全量明细且不暴露 `limit/offset` 参数。

字段统一显式请求：

```text
ts_code,freq,time,open,close,high,low,vol,amount
```

## 2. 单代码验证

请求参数：

```json
{
  "ts_code": "600000.SH",
  "fields": ["ts_code", "freq", "time", "open", "close", "high", "low", "vol", "amount"]
}
```

| freq | 行数 | 返回 freq | time | 结论 |
| --- | ---: | --- | --- | --- |
| `1MIN` | 1 | `1MIN` | `2026-06-01 10:35:00` | `freq` 返回且与请求一致。 |
| `5MIN` | 1 | `5MIN` | `2026-06-01 10:35:00` | `freq` 返回且与请求一致。 |
| `15MIN` | 1 | `15MIN` | `2026-06-01 10:30:00` | `freq` 返回且与请求一致。 |
| `30MIN` | 1 | `30MIN` | `2026-06-01 10:30:00` | `freq` 返回且与请求一致。 |
| `60MIN` | 1 | `60MIN` | `2026-06-01 10:30:00` | `freq` 返回且与请求一致。 |

结论：M4 provider 必须显式请求 `freq`，normalizer 必须校验返回 `freq` 等于请求频率。

## 3. 多代码验证

请求参数：

```json
{
  "ts_code": "600000.SH,000001.SZ",
  "freq": "1MIN",
  "fields": ["ts_code", "freq", "time", "open", "close", "high", "low", "vol", "amount"]
}
```

返回结果：

| ts_code | freq | time | close | vol | amount |
| --- | --- | --- | ---: | ---: | ---: |
| `600000.SH` | `1MIN` | `2026-06-01 10:36:00` | 9.32 | 43900 | 409088 |
| `000001.SZ` | `1MIN` | `2026-06-01 10:35:00` | 10.93 | 130200 | 1423526 |

结论：多代码请求可用；同一请求中不同股票的 `time` 可以存在分钟级差异，页面和 API 必须展示源端 `time`，不能把单行时间差异视为 feed 失败。

## 4. 全市场五频率验证

请求参数：

```json
{
  "ts_code": "3*.SZ,6*.SH,0*.SZ,9*.BJ",
  "fields": ["ts_code", "freq", "time", "open", "close", "high", "low", "vol", "amount"]
}
```

验证时间：2026-06-01 10:36:31 CST

| freq | 行数 | 耗时 ms | 返回字段 | `freq` 不一致 | `ts_code/freq/time` 缺失 | time 分布 | 旧时间样本 |
| --- | ---: | ---: | --- | ---: | ---: | --- | --- |
| `1MIN` | 5525 | 501.47 | 9/9 | 0 | 0/0/0 | `2026-06-01 10:36:00`：5525 | 无 |
| `5MIN` | 5525 | 514.21 | 9/9 | 0 | 0/0/0 | `2026-06-01 10:35:00`：5525 | 无 |
| `15MIN` | 5525 | 859.95 | 9/9 | 0 | 0/0/0 | `2026-06-01 10:30:00`：5525 | 无 |
| `30MIN` | 5525 | 858.30 | 9/9 | 0 | 0/0/0 | `2026-06-01 10:30:00`：5525 | 无 |
| `60MIN` | 5525 | 481.02 | 9/9 | 0 | 0/0/0 | `2026-06-01 10:30:00`：5525 | 无 |

全字段缺失统计：

| freq | ts_code | freq | time | open | close | high | low | vol | amount |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `1MIN` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `5MIN` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `15MIN` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `30MIN` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `60MIN` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

结论：全市场通配符可一次拉取五频率快照；本次开市验证没有发现缺失身份字段、`freq` 不一致或旧日期样本。

## 5. 分页行为补测

验证时间：2026-06-01 10:37 CST  
说明：`tushareMcp.rt_min` 不暴露 `limit/offset` 参数，本项使用同一 Tushare HTTP API 做只读补测。

| 场景 | params | 行数 | 耗时 ms | 首条代码 | 首条 time |
| --- | --- | ---: | ---: | --- | --- |
| baseline | `freq=1MIN` | 5525 | 857.28 | `301024.SZ` | `2026-06-01 10:37:00` |
| limit_10 | `freq=1MIN, limit=10` | 5525 | 1253.62 | `301024.SZ` | `2026-06-01 10:37:00` |
| offset_1000 | `freq=1MIN, offset=1000` | 5525 | 491.94 | `301024.SZ` | `2026-06-01 10:37:00` |

结论：全市场通配符请求下，本次开市实测 `limit/offset` 没有改变返回行数和首条结果。M4 provider 不设计分页依赖。

## 6. 请求量与限速评估

五频率全市场一轮请求耗时合计：

```text
501.47 + 514.21 + 859.95 + 858.30 + 481.02 = 3214.95 ms
```

结论：

1. 五频率串行请求约 3.22 秒，低于 V1 初始采集间隔 60 秒。
2. 五频率每 60 秒一轮，理论请求量约 5 次/分钟。
3. 当前 `REALTIME_STOCK_RT_MIN_MAX_CALLS_PER_MINUTE=20` 能覆盖 V1 请求量。
4. M4 先实现 provider / normalizer / 单频发布能力；M5 统一 collector 接入时可以先按同一服务内 feed 级独立执行。若后续真实耗时明显变长，再基于监控数据评估并发或拆服务。

## 7. M4 实现结论

进入 M4 时必须按以下事实实现：

1. `rt_min` 必须显式请求 `fields=ts_code,freq,time,open,close,high,low,vol,amount`。
2. `freq` 是身份字段，normalizer 必须校验返回 `freq` 与请求频率一致；不一致行不得静默覆盖。
3. 每个频率独立 feed：`tushare_stock_rt_min_1min`、`tushare_stock_rt_min_5min`、`tushare_stock_rt_min_15min`、`tushare_stock_rt_min_30min`、`tushare_stock_rt_min_60min`。
4. 全市场通配符 `3*.SZ,6*.SH,0*.SZ,9*.BJ` 可以一次拉取约 5525 行，不依赖分页。
5. `time` 是源端事实，应按行保留并展示；单行旧时间或个股时间差异不代表整个 feed 失败。
6. 本次没有旧日期样本，但 M4 仍应按已拍板口径保留源端 `time`，不把旧时间行判为失败。
7. 不落库，不进入 DatasetDefinition / TaskRun / freshness；只写 Redis snapshot 与短期 stream。
