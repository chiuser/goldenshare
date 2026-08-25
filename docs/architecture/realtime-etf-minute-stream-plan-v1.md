# ETF 实时分钟流接入方案 v1

状态：静态源接口与目标架构已确认；可进入 R1A 静态能力开发，开市时序验证仍待完成。

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
2. 实时行情 batch 不写 PostgreSQL，不增加数据库表或 Alembic 迁移；仅在上线初始化阶段向既有 `ops.etf_series_active` 受控写入 `resource=etf_rt_min` 代码池。
3. 不新增第二个 systemd 服务，继续复用 `goldenshare-realtime-collector.service`。
4. 不新增面向业务方的 HTTP API 或 WebSocket；统一 reader 是 foundation 内部读取契约。
5. 不在 provider、collector、reader 或 Ops health 中加入任何下游业务规则。
6. 现有 ETF 活跃池审查页只增加 `etf_rt_min` 只读 resource，不增加维护入口。

---

## 2. 已确认的源接口事实

### 2.1 API 名与请求参数

2026-08-25 已通过 Tushare MCP 和项目 `TushareHttpClient` 直接验证：源站接受独立的 `api_name=rt_etf_min`。同一 ETF 使用 `rt_etf_min` 与 `rt_min` 当前返回一致，但工程必须使用语义明确的 ETF 接口名 `rt_etf_min`。

已验证请求形状：

```text
api_name=rt_etf_min
ts_code=5*.SH,1*.SZ
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
| 通配符 | `5*.SH`、`1*.SZ` 及组合值 `5*.SH,1*.SZ` 均可请求。2026-08-26 收市后实测分别返回 `1102`、`1222`、`2324` 行，组合结果等于两市场之和。 |
| 返回形态 | 每次请求每个代码返回当时最新一根对应频率 K 线，不返回从开盘开始的完整序列。 |
| 旧时间 | 部分 ETF 可能返回较旧 `time`；保留源端事实，并由 health 展示。 |
| 字段 | `ts_code,freq,time,open,close,high,low,vol,amount`。 |

本地 0416 源文档仍写着“单次最大 1000 行”，但当前真实通配符请求已经返回 `2324` 行。工程实现以实测行为为准，不再把“1000 行”解释成必须分片或逐代码请求；该差异必须保留在 R0A/R0B 验证记录中。

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

`poll_interval_seconds` 必须限制在 `1-60` 秒。它只负责保证 unified collector 会及时重新检查 due state；真正的源请求时间仍由闭合槽、source-ready 延迟和 limiter 决定。

`source_ready_delay`、槽内重试间隔、槽截止时间和各频率闭合网格不是运营配置项。它们必须在开市 R0B 验证后作为锁定调度策略进入代码目录；在此之前只允许定义接口，不允许写死数值。

### 3.2 独立限速

`rt_etf_min` 使用独立 limiter key 和 `etf_rt_min.max_calls_per_minute`。股票 `rt_min` 与 ETF `rt_etf_min` 不共用配置，也不因返回形态相同而合并限速桶。

发布配置时必须根据：

```text
交易时段内各频率闭合槽
同一分钟可能同时到期的频率数
每个槽允许的最大请求次数
独立 limiter 的实际间隔
```

模拟滚动 60 秒内的峰值请求量。每个到期频率每次尝试只发一个组合通配符请求；配置不足以覆盖峰值和重试预算时拒绝发布。

### 3.3 ETF 实时代码池

`etf_rt_min` 是 `ops.etf_series_active` 的 resource，不是单条配置或 Redis key。每个 ETF 占一行：

```text
resource=etf_rt_min, ts_code=510300.SH
resource=etf_rt_min, ts_code=159915.SZ
```

初始代码池固定从数据库现有 `resource=etf_rt_daily` 的 1395 条记录受控复制，写成 1395 行 `resource=etf_rt_min` 记录，不再依赖已经退场的历史 CSV。

源站请求固定使用沪深组合通配符，因此代码池不再决定请求参数；代码池决定哪些源端行可以进入 ETF 实时分钟 Redis feed。collector 每轮读取 `etf_rt_min` 池，与源端返回代码取交集，只发布池内行。池外行不算 invalid，但必须记录源端总行数、池外行数、池内命中数和池内缺失数。

现有“审查中心 / ETF 活跃池”页面必须增加 `etf_rt_min` 只读选项，让运营可以核对目标池数量和代码；页面仍不提供增删改。

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

单次组合通配符请求成功、池内身份校验通过且目标分钟达到就绪条件后，才能发布 batch 并原子切换 current pointer。请求失败、池内重复代码或目标分钟尚未就绪时保留上一批 current pointer，只更新本频率 health。

Redis 发布事务一旦成功，就视为本批行情事实已发布。事务后的旧批清理失败只能记录维护告警，不能把已切换 current pointer 的批次重新标成发布失败。

池内同一 `ts_code` 在一次源响应中出现多行属于身份冲突，整批不发布；不允许沿用现有 store 的后写覆盖前写行为。

`keep_recent_batches=260` 在每个启用的物理 feed 上分别生效。V1 不增加按频率分别配置保留批次数的模型。实际可读历史同时受 `snapshot_ttl_seconds` 和 `keep_recent_batches` 约束，哪个先达到就按哪个清理；因此“260批”是数量上限，不承诺低频 feed 一定能在72小时 TTL 内积累到260批。

上线前必须做 Redis 容量实测。容量按物理 feed 分别计算：

```text
预计 snapshot 数 = 激活池代码数 x keep_recent_batches x 启用频率数
```

仅启用 `1MIN` 时是 `1395 x 260 = 362700` 个 snapshot；五频率全启用时是 `1813500` 个 snapshot。R1A 使用真实序列化字段测单批内存，R3 部署后用 Redis `used_memory` 增量复核，容量不足时不得启用更多频率。

---

## 5. 按 K 线闭合槽调度

调度不能使用“上一次请求结束时间 + interval”。每个频率必须从交易时段和频率计算下一根 K 线闭合槽：

```text
频率闭合槽
  -> 等待源端可用延迟
  -> 发起一次沪深组合通配符请求
  -> 与 1395 激活池取交集
  -> 目标分钟达到就绪条件：发布一次
  -> 返回旧时间、空结果或临时失败：在本槽剩余时间内重试
  -> 到达下一槽仍未成功：记录 missed slot，进入下一槽
```

规则：

1. `1MIN` 每个交易分钟最多发布一次；其他频率只在各自窗口结束时请求。
2. 上午和下午交易时段分别计算，午休不产生时间槽。
3. 同一 `(feed_key, expected_bar_time)` 只允许成功发布一次；batch identity 由这两个字段确定，进程重启后也必须通过 current batch meta 拦截重复槽。
4. collector 执行稍晚但仍处于当前槽时，通过校验 `source.time` 和槽内重试取得目标 K 线。
5. 如果 collector 停止超过一个完整一分钟槽，源接口只提供最新 K 线，无法保证追回已经跨过的旧槽。系统必须记录 missed slot 并显示 degraded，不能伪造数据或把较新的 K 线写到旧槽。
6. collector 恢复后直接处理当前合法槽，不突发补跑已经失去的实时槽。
7. 单只停牌或长期无成交 ETF 的旧时间不等于“整个接口仍停在上一分钟”；批次就绪只根据 R0B 冻结的池内目标分钟覆盖事实判断。
8. 一次 collector 调度最多发起一次 `rt_etf_min` 请求；返回旧时间或临时失败时，只登记 `next_retry_at` 并立即返回统一调度器，禁止在单次调用中循环等待到槽截止。
9. 同一分钟多个频率到期时，按固定频率顺序逐次尝试，并遵守 `rt_etf_min` 独立 limiter 的最小请求间隔；不能让 limiter 的阻塞等待占住其他实时 feed。

源端可用延迟、池内目标分钟覆盖变化、完整字段响应耗时和槽内重试次数必须在 R0B 开市验证中冻结；在验证前不能拍脑袋写死。

每个频率在槽内第一次请求前获取独立 lease，并持有到成功或槽截止。`lease_ttl_seconds` 必须覆盖最大重试窗口、源请求超时和安全余量；若 R0B 证明合理 TTL 无法覆盖，必须先增加 owner 校验的 lease 续期能力。

现有 `TushareHttpClient` 自带多次 HTTP transport retry，最坏耗时可能超过一分钟槽。ETF 实时分钟必须使用显式、受限的 transport retry 策略；源端未就绪的再次请求只由分钟调度器控制，不能与 HTTP 客户端内部重试叠加成不可控阻塞。

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
3. reader 负责频率校验、feed key 解析、stale 判断、批次读取和 missing code 汇总；series 的 missing code 只表示该代码在本次读取的全部批次中都没有任何一行。
4. reader 不包含页面、统计或其他业务规则。
5. 本轮只增加 foundation 内部 reader，不新增 HTTP API。

ETF 分钟不能沿用现有“`current_batch_age_seconds > stale_after_seconds`”的通用 stale 算法。`5MIN/15MIN/30MIN/60MIN` 在下一个闭合槽到来前没有新批是正常状态。reader 与 health 必须根据该频率的闭合网格判断：只有“最新已经超过 source-ready 时间及 stale grace 的应发布槽”仍未出现在 current batch 时才标 stale；当天首个应发布槽尚未到来时为等待状态，不得报 unavailable/stale。

---

## 7. Ops 配置与健康页面

配置中心增加 `etf_rt_min` 对象，`enabled_freqs` 使用五频率多选框。发布后继续通过重启 collector 的 apply-state 闭环生效。

新增只读 health API：

```http
GET /api/v1/ops/realtime/etf-rt-min/health
GET /api/v1/ops/realtime/etf-rt-min/health?freq=1MIN
```

实时流监控页面增加“ETF 实时分钟”区块，展示每个频率的启用状态、采集窗口、current batch、最新源端时间、代码池数量、快照数量、missed slot、无效行、单频率尝试数、`rt_etf_min` 聚合请求数、耗时和最近错误。页面只读取 Ops health API，不直接访问 Redis。

`missed slot` 必须区分“当前连续遗漏”和“当日累计遗漏”。后续成功发布新槽后，当前状态可以恢复为 `ok`，但当日累计值和最近遗漏时间继续保留，不能因为历史上漏过一次就永久显示 degraded。

---

## 8. 调整后的实施阶段

| 阶段 | 目标 | 完成条件 |
| --- | --- | --- |
| R0A，已完成 | 收市静态源接口验证 | 独立 API 名、显式字段、五频率、组合通配符和收市返回规模已有真实记录。 |
| R1A，现在可开发 | 静态能力 | 第四配置对象结构、DB 代码池复制、provider、基础 normalizer、Redis 重复身份/清理边界、reader、审查中心只读 resource 和单元测试完成；保持 `enabled=false`。 |
| R0B，开市验证 | 时间与容量事实 | 完整字段池命中、五频率准确闭合网格、源端可用延迟、目标分钟覆盖变化、单次请求耗时、HTTP 重试上界、槽内重试和请求预算冻结。 |
| R1B，R0B 后开发 | 调度策略 | 批次就绪规则、非阻塞 retry state、确定性 batch identity、lease 与 limiter 校验完成。 |
| R2 | collector、health 与页面 | 统一 collector 接入、按频率异常隔离、配置中心和实时流监控页完成。 |
| R3 | 部署前初始化与收市验收 | 在服务重启前创建 disabled 配置行并复制 1395 代码池；配置、apply state、Redis 容量和休市状态对账。 |
| R4 | 开市验收 | 时间槽连续性、Redis 批次、reader、health 和页面逐项对账后，才允许正式启用。 |

R1A 不依赖开市时序，可以立即推进。R0B 是 R1B 和生产启用的硬门禁，但不再阻塞 DB 代码池复制、配置结构、provider、基础校验、reader 与共享 Redis 安全边界开发。

生产发布顺序固定为：部署新代码但不启动新 collector 消费者，执行 realtime config seed 创建 `enabled=false` 的第四对象，执行 `ops-init-etf-rt-min-active-pool --apply`，核对两个 1395 代码集合一致，再重启 Web 与统一 collector。部署脚本必须把初始化放在服务重启之前；任何一步失败都不得启动依赖第四对象的新进程。
