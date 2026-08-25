# ETF 实时分钟流接入方案 v1

状态：源接口与目标架构已确认，尚未编码。

创建日期：2026-08-24
最近更新：2026-08-26

关联文档：

- [实时行情流架构方案 v1](/Users/congming/github/goldenshare/docs/architecture/realtime-market-data-stream-architecture-v1.html)
- [ETF 实时分钟流 LLD v1](/Users/congming/github/goldenshare/docs/architecture/realtime-etf-minute-stream-low-level-design-v1.md)
- [Tushare 0416 ETF 实时分钟](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0416_ETF实时分钟.md)

---

## 1. 目标

把 Tushare `rt_etf_min` 接入现有 realtime 主链，形成与 ETF 实时日线一致的独立实时 feed 能力：

```text
realtime config: etf_rt_min
  -> ops.etf_series_active(resource=etf_rt_min)
  -> Tushare rt_etf_min provider
  -> unified realtime collector
  -> Redis per-frequency batch / current pointer / stream / health
  -> RealtimeSnapshotReader
  -> Ops 配置中心与实时流监控页
```

本轮范围固定为实时源采集、Redis 状态、统一读取器和 Ops 可观测能力：

1. 不新增 `DatasetDefinition`，不进入 TaskRun、freshness 或 date audit。
2. 不写 PostgreSQL，不增加数据库表或 Alembic 迁移。
3. 不新增第二个 systemd 服务，继续复用 `goldenshare-realtime-collector.service`。
4. 不新增面向业务方的 HTTP API 或 WebSocket；统一 reader 是 foundation 内部读取契约。
5. 不在 provider、collector、reader 或 Ops health 中加入任何下游业务规则。

---

## 2. 已确认的源接口事实

### 2.1 API 名与请求参数

2026-08-25 已通过 Tushare MCP 和项目 `TushareHttpClient` 直接验证：源站接受独立的 `api_name=rt_etf_min`。同一 ETF 使用 `rt_etf_min` 与 `rt_min` 当前返回一致，但工程必须使用语义明确的 ETF 接口名 `rt_etf_min`。

已验证请求形状：

```text
api_name=rt_etf_min
ts_code=159915.SZ 或 510300.SH
freq=1MIN
fields=ts_code,freq,time,open,close,high,low,vol,amount
```

深市和沪市 ETF 均可在不传 `topic` 的情况下返回数据。因此 V1 只传：

```text
ts_code
freq
fields
```

不增加其他请求参数。

### 2.2 返回形态与频率

| 项目 | 已确认事实 |
| --- | --- |
| 必填参数 | `ts_code`、`freq`。 |
| 支持频率 | `1MIN/5MIN/15MIN/30MIN/60MIN`。 |
| 多代码 | 支持逗号分隔；源文档声明单次最多 1000 行。 |
| 返回形态 | 每次请求每个代码返回当时最新一根对应频率 K 线，不返回从开盘开始的完整序列。 |
| 旧时间 | 部分 ETF 可能返回较旧 `time`；保留源端事实，并由 health 展示。 |
| 字段 | `ts_code,freq,time,open,close,high,low,vol,amount`。 |

### 2.3 K 线闭合语义

开市实测已经确认：

1. `1MIN` 返回已闭合分钟，同一分钟重复读取内容保持不变，下一分钟才出现新行。
2. `5MIN` 只在五分钟窗口结束后返回新 K 线。
3. `09:30` 是独立开盘分钟，普通首个五分钟窗口是 `09:31-09:35`。

collector 必须按源端 K 线闭合时间请求，不能把尚未出现的新 K 线伪装成空值或零值。

---

## 3. 配置与代码池

### 3.1 Realtime 配置对象

新增配置对象：

```text
object_key=etf_rt_min
object_kind=feed_group
display_name=ETF 实时分钟
source_api_name=rt_etf_min
```

可编辑字段：

```text
enabled
enabled_freqs
poll_interval_seconds
max_calls_per_minute
lease_ttl_seconds
stale_after_seconds
snapshot_ttl_seconds
keep_recent_batches
batch_stream_maxlen
delta_stream_maxlen
source_timeout_seconds
```

初始值：

```text
enabled=false
enabled_freqs=[1MIN]
poll_interval_seconds=60
snapshot_ttl_seconds=259200
keep_recent_batches=260
```

请求时机由频率对应的 K 线闭合槽决定；`poll_interval_seconds` 只约束 collector 的最大检查间隔，不能让 `5MIN/15MIN/30MIN/60MIN` 每分钟重复请求同一根 K 线。

### 3.2 独立限速

`rt_etf_min` 使用独立 limiter key 和 `etf_rt_min.max_calls_per_minute`。股票 `rt_min` 与 ETF `rt_etf_min` 不共用配置，也不因返回形态相同而合并限速桶。

发布配置时必须根据：

```text
活跃代码数
每请求代码数
启用频率
时间槽内重试预算
```

计算峰值请求量。配置不足时拒绝发布。

### 3.3 ETF 实时代码池

`etf_rt_min` 是 `ops.etf_series_active` 的 resource，不是单条配置或 Redis key。每个 ETF 占一行：

```text
resource=etf_rt_min, ts_code=510300.SH
resource=etf_rt_min, ts_code=159915.SZ
```

初始代码池固定复制现有 1395 个 ETF 基线，写成 1395 行 `resource=etf_rt_min` 记录。collector 只从该 resource 读取请求代码。

---

## 4. 分频率 Redis feed

每个频率使用独立 feed：

```text
tushare_etf_rt_min_1min
tushare_etf_rt_min_5min
tushare_etf_rt_min_15min
tushare_etf_rt_min_30min
tushare_etf_rt_min_60min
```

每个 feed 复用现有 `RealtimeStateStore`：

| 结构 | 含义 |
| --- | --- |
| batch | 某次完整请求成功后发布的一组 ETF K 线。 |
| current pointer | 指向最新完整 batch 的小型指针；读者先取指针，再读取对应 batch。 |
| batch stream | 按发布时间追加“新批次已发布”事件。 |
| delta stream | 追加相对上一批发生变化的 ETF 行事件。 |
| health | 记录 feed 是否启用、是否在采集窗口、最近成功/失败、源端时间、行数、耗时与错误。 |

所有分片都成功后才能发布 batch 并原子切换 current pointer。任一分片失败时保留上一批 current pointer，只把本频率 health 标为 degraded。

`keep_recent_batches=260` 在每个启用的物理 feed 上分别生效。V1 不增加按频率分别配置保留批次数的模型。

---

## 5. 按 K 线闭合槽调度

调度不能使用“上一次请求结束时间 + interval”。每个频率必须从交易时段和频率计算下一根 K 线闭合槽：

```text
频率闭合槽
  -> 等待源端可用延迟
  -> 请求全部代码分片
  -> 返回时间等于预期槽：发布一次
  -> 返回旧时间、空结果或临时失败：在本槽剩余时间内重试
  -> 到达下一槽仍未成功：记录 missed slot，进入下一槽
```

规则：

1. `1MIN` 每个交易分钟最多发布一次；其他频率只在各自窗口结束时请求。
2. 上午和下午交易时段分别计算，午休不产生时间槽。
3. 同一 `(feed_key, expected_bar_time)` 只允许成功发布一次。
4. collector 执行稍晚但仍处于当前槽时，通过校验 `source.time` 和槽内重试取得目标 K 线。
5. 如果 collector 停止超过一个完整一分钟槽，源接口只提供最新 K 线，无法保证追回已经跨过的旧槽。系统必须记录 missed slot 并显示 degraded，不能伪造数据或把较新的 K 线写到旧槽。
6. collector 恢复后直接处理当前合法槽，不突发补跑已经失去的实时槽。

源端可用延迟、单分片代码数和槽内重试次数必须在 R0 开市验证中冻结；在验证前不能拍脑袋写死。

---

## 6. 统一 Reader

扩展现有 `RealtimeSnapshotReader`，让所有调用方通过 foundation 契约读取 ETF 实时分钟数据，不允许自行拼 Redis key。

V1 提供两个内部方法：

```python
read_etf_rt_min_snapshot(session, *, freq, ts_codes)
read_etf_rt_min_series(session, *, freq, ts_codes, batch_limit)
```

语义：

1. `snapshot` 读取 current pointer 指向的最新完整 batch。
2. `series` 按 batch 时间倒序读取最近批次，按 `(ts_code, freq, time)` 去重后按时间升序返回。
3. reader 负责频率校验、feed key 解析、stale 判断、批次读取和 missing code 汇总。
4. reader 不包含页面、统计或其他业务规则。
5. 本轮只增加 foundation 内部 reader，不新增 HTTP API。

---

## 7. Ops 配置与健康页面

配置中心增加 `etf_rt_min` 对象，`enabled_freqs` 使用五频率多选框。发布后继续通过重启 collector 的 apply-state 闭环生效。

新增只读 health API：

```http
GET /api/v1/ops/realtime/etf-rt-min/health
GET /api/v1/ops/realtime/etf-rt-min/health?freq=1MIN
```

实时流监控页面增加“ETF 实时分钟”区块，展示每个频率的启用状态、采集窗口、current batch、最新源端时间、代码池数量、快照数量、missed slot、无效行、请求数、耗时和最近错误。页面只读取 Ops health API，不直接访问 Redis。

---

## 8. 实施阶段

| 阶段 | 目标 | 完成条件 |
| --- | --- | --- |
| R0 | 开市源端与调度验证 | `rt_etf_min` 多代码上限、1395 代码分片、源端可用延迟、槽内重试和请求预算冻结。 |
| R1 | 配置、代码池、provider、reader | 第四配置对象和 1395 行 resource 落地；独立 limiter、provider 与 reader 测试通过。 |
| R2 | collector、Redis、health、页面 | 分频率调度、原子发布、异常隔离、配置中心和实时流监控页完成。 |
| R3 | 部署与开市验收 | 配置生效、时间槽连续性、Redis 批次、reader、health 和页面逐项对账。 |

当前可以进入 R0；R0 未冻结的源端容量和时间参数必须先实测，不能在编码时猜测。
