# ETF 实时分钟流接入方案 v1

状态：核心源端语义已实测冻结，尚未编码。本文定义独立 ETF 分钟流及其分钟事实归档；ETF 成交额监控只是后续下游消费者，不属于本方案实施范围。

创建日期：2026-08-24
最近更新：2026-08-24

适用范围：Tushare ETF 实时分钟源、Redis 分钟事实、分钟归档、历史缺口修复、实时流配置中心和实时流监控页。

上位架构：[实时行情流架构方案 v1](/Users/congming/github/goldenshare/docs/architecture/realtime-market-data-stream-architecture-v1.html)
详细编码依据：[ETF 实时分钟流接入 LLD v1](/Users/congming/github/goldenshare/docs/architecture/realtime-etf-minute-stream-low-level-design-v1.md)
实时源接口事实：[Tushare 0416 ETF 实时分钟](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0416_ETF实时分钟.md)
历史补数接口事实：[Tushare 0387 ETF 历史分钟行情](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0387_ETF历史分钟行情.md)

---

## 1. 目标与硬边界

目标是建立独立的 ETF 实时分钟流。它只负责取得、保存和归档 ETF 的分钟行情事实：

```text
runtime config + ETF source 活跃池
  -> rt_min provider
  -> unified realtime collector
  -> Redis 按频率隔离的 batch / current pointer / health
  -> 1MIN final fact state
  -> 收盘归档服务
  -> foundation.etf_realtime_minute_bar_1m（PostgreSQL HDD）
  -> 历史缺口修复（etf_mins）
  -> 基于持久化 1MIN 的派生周期线
  -> 任何下游业务只读消费
```

本方案的硬边界如下。

1. 不新增 `DatasetDefinition`，不进入 TaskRun、freshness、date audit，也不建立常规 `raw/core/serving` 数据集链路。
2. 新增的 `foundation.etf_realtime_minute_bar_1m` 是实时分钟源自身的长期事实归档表，不是成交额监控表，也不是监控统计的副本。
3. realtime collector 只写 Redis 与分钟事实状态；收盘归档由独立分钟流归档服务执行。collector 不直接写 PostgreSQL，不新增第二个 systemd 服务。
4. 不增加业务方 ETF 分钟查询 API、WebSocket 或 Feishu。本方案只补齐 source、配置和 Ops 观测能力。
5. ETF 成交额监控不得参与 ETF 分钟源的采集、归档、补数、活跃池、频率、留存或健康状态。它以后只能读取本方案产出的分钟事实。
6. `rt_etf_k` 的高频累计快照与 `rt_min` 的闭合分钟事实是两类源，不得混写、互相覆盖或互相替代。

### 1.1 频率与持久化口径

实时源支持 `1MIN/5MIN/15MIN/30MIN/60MIN`。V1 的生产启用策略为：

```text
实时 source 可配置支持：1MIN / 5MIN / 15MIN / 30MIN / 60MIN
初始生产重点启用：1MIN
长期物理归档：只归档 1MIN
派生周期：5 / 15 / 30 / 60 / 90 / 120 分钟均由持久化 1MIN 计算
```

`90MIN`、`120MIN` 不是实时源请求频率；它们只能由已归档 `1MIN` 聚合得出。V1 不存储独立的 5/15/30/60/90/120 分钟物理表，避免同一事实出现两套来源。

---

## 2. 已冻结的源端事实

### 2.1 实时接口 `rt_min`

本地 0416 文档的 API 名为 `rt_min`；`tushareMcp` 中用于验证的工具名为 `rt_etf_min`。工程 provider 的真实源接口常量应为 `rt_min`，不得把 MCP 工具名误写为 HTTP/API 名。

当前已确认的输入契约：

| 项目 | 已确认事实 |
| --- | --- |
| 必填参数 | `ts_code`、`freq` |
| 支持频率 | `1MIN/5MIN/15MIN/30MIN/60MIN` |
| 多代码 | `ts_code` 可逗号分隔；生产单请求容量仍须在实施前以 source 活跃池样本实测冻结 |
| 请求参数边界 | 只传文档支持的 `ts_code` 与 `freq`，并显式请求业务字段；不得传 `topic`、`HQ_FND_TICK` 或任何未在 0416 文档声明的参数 |
| 返回形态 | 每次请求每个 ETF/频率只返回当时最新的一根 K 线，不返回从开盘到当前的完整分钟序列 |
| 旧时间 | 个别 ETF 可能返回较旧 `time`；这是源端事实，不自动判为失败 |

实时 provider 的显式字段至少为：

```text
ts_code, freq, time, open, close, high, low, vol, amount
```

### 2.2 1MIN 与 5MIN 的闭合语义

开市实测已得到下列结论：

1. `rt_min(freq=1MIN)` 返回已闭合的分钟事实。同一 `13:15` 行重复读取保持不变，`13:16` 才出现下一根；不能把它按“形成中分钟”处理。
2. `rt_min(freq=5MIN)` 只返回已闭合窗口。`13:02` 至 `13:04` 读取仍停在午前最后完成窗口，`13:05` 后才出现 `13:05` 的 5 分钟线。
3. 历史样本中，`13:01` 至 `13:05` 的五根 `1MIN` 成交额之和与 `13:05` 的 `5MIN` 成交额一致，证明闭合窗口的量值语义一致。

因此，V1 的 `1MIN` collector 只接受 `source_time` 已结束的当前闭合分钟；同一 `(ts_code, source_time)` 的有效行只产生一个最终分钟事实。没有数据、字段不完整或 source 请求失败时必须标为 `missing/invalid`，不能以零成交额补齐。

### 2.3 开盘 `09:30` 特殊桶

已使用 `510300.SH`、2026-08-21 的 `etf_mins` 历史数据核验：

| 比对项 | 成交量 | 成交额（元） |
| --- | ---: | ---: |
| `09:31` 至 `09:35` 五根 `1min` 求和 | 32,608,200 | 151,558,196 |
| `09:35` 的 `5min` | 32,608,200 | 151,558,190 |
| `09:30` 至 `09:34` 五根 `1min` 求和 | 30,399,900 | 141,293,248 |

`09:35` 的 OHLC 也对应 `09:31` 至 `09:35`：开盘取 `09:31`，收盘取 `09:35`，高低点覆盖这五根。源端另返回一根 `trade_time=09:30` 的 `5min` 行，其成交额、成交量与 `09:30` 的 `1min` 行完全相同。

结论：

1. `09:30` 是独立的一分钟开盘事实，不进入正常的 `09:31` 至 `09:35` 五分钟桶。
2. 源端聚合分钟成交额可有极小的舍入差异。本例相差 6 元；系统自身派生周期线必须以持久化 `1MIN.amount` 的求和为唯一金额事实，不要求逐元等于源端聚合频率。

### 2.4 历史补数接口 `etf_mins`

当前 Tushare MCP 实测的 ETF 历史分钟接口是 `etf_mins`，而本地 0387 文档仍写为 `stk_mins`。这是本地 source 文档与当前实测的命名差异；实施时必须以当前 `etf_mins` 实测契约校准 request builder，并另行修正 source 文档，不能沿用 `stk_mins` 名称猜测实现。

已验证参数与行为：

```text
ts_code=510300.SH
freq=1min
start_date=2026-08-21 09:30:00
end_date=2026-08-21 09:40:00
```

1. 历史交易日成功返回 11 根 `1min`，覆盖 `09:30` 至 `09:40`，按时间倒序返回。
2. 返回至少包含 `ts_code`、`trade_time`、OHLC、`vol`、`amount`、`freq`、`vwap`、`exchange`。
3. 同样请求 2026-08-24 当日窗口返回空数组。因此它不能被假定为“收盘后立即可补当天缺口”。

结论：`etf_mins` 是**已成为历史交易日**的 ETF 分钟缺口补数来源；当日缺口必须保留为缺口，等待该接口的可用延迟被单独验证后才可补写。

---

## 3. 配置、feed 与对象范围

### 3.1 配置对象与独立 feed

新增 realtime config 对象：

```text
object_key: etf_rt_min
object_kind: feed_group
display_name: ETF 实时分钟
```

每个频率使用独立 Redis feed：

```text
tushare_etf_rt_min_1min
tushare_etf_rt_min_5min
tushare_etf_rt_min_15min
tushare_etf_rt_min_30min
tushare_etf_rt_min_60min
```

各 feed 的 batch、current pointer、snapshot、stream、lease、health 彼此隔离；不能使用 `freq:ts_code` 塞入单 feed，也不能将不同频率放入同一 batch。

### 3.2 共享留存配置的 V1 决策

现有 realtime config 模型只有一个 `storage.keep_recent_batches`，它在每个物理 feed 上分别生效，但不能按频率配置不同批次数。该模型在 V1 不扩展。

```text
etf_rt_min.enabled_freqs：初始仅启用 1MIN
etf_rt_min.storage.keep_recent_batches：260
1MIN：完整日为 09:30 独立开盘事实 + 120 根上午连续分钟 + 120 根下午连续分钟，共 241 根；260 批另有 19 批缓冲
其他频率：默认不启用，因此不占用额外 Redis 批次空间
```

未来若需要同时启用多个频率且要求各自留存天数不同，再单独设计“分频率留存策略”。不得在本轮顺手改 runtime config、配置中心 API 或页面模型。

`keep_recent_batches` 只是 Redis 批次保留策略，不是分钟归档完整性的保证，也不是成交额监控的配置。

### 3.3 source 活跃池

ETF 实时分钟流只从 `ops.etf_series_active(resource='etf_rt_min')` 读取 source 活跃池。该 resource：

1. 与 `etf_rt_daily`、`fund_daily` 以及 `ops.etf_realtime_monitor_pool` 独立。
2. 初始可复用已确认的 ETF 活跃池代码基线，但必须单独 seed 为 `etf_rt_min`。
3. 决定实时源请求范围；下游监控池的增删、启停或分组均不得改变它。

### 3.4 可编辑与锁定配置

配置中心的可编辑字段为：

| 字段 | V1 规则 |
| --- | --- |
| `enabled` | 关闭时所有频率 idle，不请求源站 |
| `enabled_freqs` | checkbox：`1MIN/5MIN/15MIN/30MIN/60MIN`；初始生产只选 `1MIN` |
| `poll_interval_seconds` | 初始 `60`；启用 `1MIN` 时不得大于 60，且 collector 必须锚定交易分钟结束后调度，不能按进程启动时间漂移 |
| `max_calls_per_minute` | 必须通过 source 活跃池分片请求量校验 |
| `lease_ttl_seconds` | 覆盖一次完整分片请求的最大预计耗时 |
| `stale_after_seconds` | 不小于该频率的正常刷新间隔和可接受延迟 |
| `snapshot_ttl_seconds` | Redis batch/snapshot TTL，默认 72 小时 |
| `keep_recent_batches` | 共享批次数，初始 260 |
| `batch_stream_maxlen` / `delta_stream_maxlen` | 沿用 realtime state store 语义 |
| `source_timeout_seconds` | 单次 source 请求超时 |

锁定字段为：

```text
source_api_name=rt_min
source_code_scope=ops.etf_series_active(resource=etf_rt_min)
supported_freqs=1MIN/5MIN/15MIN/30MIN/60MIN
feed_key_pattern=tushare_etf_rt_min_{freq_lower}
collection_sessions=09:30-11:30,13:00-15:00
request_parameters=ts_code,freq
```

锁定字段只读展示，前端提交锁定字段或未知字段必须被 Ops API 结构化拒绝。

---

## 4. 分钟事实、收盘归档与历史补数

### 4.1 Redis 中的最终分钟事实

实时 feed 的每次 current batch 是当前最新快照；它不能单独承担一天完整分钟历史。state store 必须新增 ETF `1MIN` 最终事实 contract，供独立归档读取：

```text
trade_date
minute_end_time
ts_code
open/high/low/close
vol
amount_yuan
source_time
source_batch_id
captured_at
quality=valid|missing|invalid
reason_code
```

事实键为 `(trade_date, minute_end_time, ts_code)`。有效事实可以被同一分钟更晚取得的有效 source 行幂等更新；`missing/invalid` 不得覆盖已有 `valid`。最终事实的 TTL 必须覆盖收盘归档和可重试窗口，且与 `keep_recent_batches` 分开定义。

### 4.2 独立分钟归档

收盘后，由 ETF 分钟流自己的 archive job 从上述 final facts 归档到 PostgreSQL HDD 表：

```text
foundation.etf_realtime_minute_bar_1m
```

该归档：

1. 读取 ETF 分钟 source 活跃池，不读取监控池。
2. 对每个 ETF、真实交易日、真实分钟桶最多写一条最终事实；重跑必须幂等。
3. 真实缺失以实际 `trade_date + minute_end_time` 记录为 `missing`，不得使用 `date.min`、`time.min` 或数值零作为替身。
4. 不将 `missing/invalid` 转为零，也不把它们拿去计算历史基准或派生周期线。
5. 不复用现有 `ops.etf_realtime_minute_stat` 或 `EtfRealtimeMinuteArchiveService`。它们属于旧的累计差额/监控池链路，语义不等于分钟源事实。

### 4.3 历史缺口修复

归档完成后按交易分钟网格核验 `1MIN`。只对 `quality=missing` 的 `ETF + 连续时间区间` 发起 `etf_mins(ts_code, freq=1min, start_date, end_date)` 请求：

```text
闭市后的 1MIN 归档
  -> 检查真实分钟桶
  -> 标出 missing
  -> 等交易日已成为历史且 etf_mins 可用
  -> 按 ETF + 缺口时间区间补数
  -> 幂等写回 foundation.etf_realtime_minute_bar_1m
  -> 重新计算派生周期
```

补数不允许：

1. 覆盖已有 `valid` 事实。
2. 将 source 空数组解释为零成交额。
3. 由成交额监控触发、控制或绕过 source 归档流程。

### 4.4 从 1MIN 派生周期线

`5/15/30/60/90/120MIN` 只从持久化 `1MIN quality=valid` 数据计算。每个周期必须完整覆盖预期的一分钟桶，任何一分钟 `missing/invalid` 则该派生周期也标记不完整，不出伪数值。

交易时段的派生锚点：

```text
09:30：独立开盘一分钟事实，不并入标准 N 分钟桶
上午标准连续桶：09:31-11:30
下午标准连续桶：13:01-15:00
```

对窗口长度 `N`，每个会话从连续段的第一根开始按 `N` 分钟切桶。例如：

```text
5MIN：09:31-09:35、09:36-09:40；13:01-13:05、13:06-13:10
15MIN：09:31-09:45；13:01-13:15
30MIN：09:31-10:00；13:01-13:30
60MIN：09:31-10:30；13:01-14:00
90MIN：09:31-11:00；13:01-14:30
120MIN：09:31-11:30；13:01-15:00
```

午休绝不跨窗。金额采用 `1MIN.amount_yuan` 精确求和，OHLC 分别取首开、末收、全窗最高/最低。

---

## 5. collector、health 和前端边界

### 5.1 collector

`RealtimeCollectorService` 在既有单一 systemd 服务内增加 ETF 分钟调度。每个启用频率独立 due、lease、请求、publish 和错误隔离；一个频率失败不能影响 ETF 实时日线、股票实时日线或股票实时分钟。

对每个频率：所有 source 分片成功后才发布新 batch 并原子切换该 feed 的 current pointer。任一分片失败时保留旧 pointer，只写当前 feed `degraded` health，不发布半对象池快照。

### 5.2 Ops health 与实时流监控页

新增只读健康接口：

```http
GET /api/v1/ops/realtime/etf-rt-min/health
GET /api/v1/ops/realtime/etf-rt-min/health?freq=1MIN
```

页面展示五个 frequency item 的配置与运行状态，包括：

```text
freq, feed_key, status, enabled, collection_status,
current_batch_id, latest_source_time, pool_count,
requested_code_count, snapshot_count, missing_count,
invalid_count, request_count_last_minute,
source_elapsed_ms, write_elapsed_ms, last_success_at, last_error_message
```

浏览器只轮询 Ops health API，并沿用局部 refetch。它不读 Redis、不触发 collector，也不请求 Tushare。

### 5.3 对下游的只读契约

下游只能读取：

1. Redis 中 `1MIN final/valid` 当前日事实，或
2. `foundation.etf_realtime_minute_bar_1m` 已归档/已补齐事实，或
3. 由上述 `1MIN` 派生的完整周期线。

下游不得调用 ETF 分钟 provider、修改 source 活跃池、改变 frequency、依赖 Redis 批次数来推断历史完整性，或把自身规则写进 minute collector。

---

## 6. 实施里程碑与测试

| 阶段 | 目标 | 通过条件 |
| --- | --- | --- |
| M0 | 源端语义冻结 | 本文第 2 节事实已实测；补充 source 活跃池分片容量与股票/ETF `rt_min` 限速归属 |
| M1 | runtime config、catalog、source 活跃池 resource | `etf_rt_min` 缺失 fail-fast；初始只启用 `1MIN`、按分钟结束锚定 60 秒调度；共享 260 批配置不扩模型 |
| M2 | provider、normalizer、Redis per-frequency feed | 只传 `ts_code/freq`、显式字段、按分片原子发布；有效/缺失/无效分钟事实正确 |
| M3 | unified collector、health、配置中心与实时流监控页 | 单服务、频率隔离、配置发布/重启闭环和五频率观察通过 |
| M4 | 分钟源持久化归档 | HDD 表、真实分钟键、幂等归档、午休隔离、完整性检查通过 |
| M5 | `etf_mins` 历史缺口补数与派生周期 | 只修历史缺口；不覆盖 valid；5/15/30/60/90/120 仅由完整 `1MIN` 得出 |
| M6 | 部署与交易时段验收 | source、Redis、HDD 归档、缺口、health 和页面逐项验收；成交额监控另立下游验收 |

测试至少覆盖：

1. `rt_min` 参数/字段、频率规范化、多代码分片、分片失败不发布、旧 source time 保留。
2. 五个 feed key 隔离、Redis 原子 current pointer、shared `keep_recent_batches` 语义和 `1MIN=260`。
3. `1MIN` final fact 幂等、missing/invalid 不覆盖 valid、不转零。
4. `09:30` 独立事实、上午/下午 N 分钟桶、午休不跨窗、源端聚合与自身金额求和存在舍入差时仍以 `1MIN` 为准。
5. 归档重复执行、真实缺失键、`etf_mins` 历史补数、当日空数组不补零。
6. source 活跃池、配置中心、collector、health 和前端都不读取/写入 ETF 成交额监控池或告警规则。

---

## 7. 当前结论

可以进入 ETF 实时分钟流的实现准备，但首先必须补齐 source 活跃池的生产分片容量与限速归属验证。本文已经冻结的分钟 finality、`09:30` 特殊桶、1MIN 持久化和 `etf_mins` 历史补数口径不再由成交额监控需求决定。
