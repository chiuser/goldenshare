# ETF 实时分钟流接入方案 v1

状态：源接口、运营选择池、调度数值与目标架构已冻结；R0B 开市验证已完成；R1A/R1B 可按本文与 LLD 开发，生产启用仍受 Redis 容量实测门禁约束。

创建日期：2026-08-24
最近更新：2026-08-28

关联文档：

- [实时行情流架构方案 v1](/Users/congming/github/goldenshare/docs/architecture/realtime-market-data-stream-architecture-v1.html)
- [ETF 实时分钟流 LLD v1](/Users/congming/github/goldenshare/docs/architecture/realtime-etf-minute-stream-low-level-design-v1.md)
- [ETF 实时分钟流 R0B 开市验证记录](/Users/congming/github/goldenshare/docs/architecture/realtime-etf-minute-r0b-open-market-validation-2026-08-26.md)
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
2. 实时行情 batch 不写 PostgreSQL，不增加数据库表或 Alembic 迁移；运营选择结果继续保存在既有 `ops.etf_series_active(resource=etf_rt_min)`。
3. 不新增第二个 systemd 服务，继续复用 `goldenshare-realtime-collector.service`。
4. 不新增面向业务方的 HTTP API 或 WebSocket；统一 reader 是 foundation 内部读取契约。
5. 不在 provider、collector、reader 或 Ops health 中加入任何下游业务规则。
6. 新增独立的“ETF 实时分钟池配置”页面；不把 `etf_rt_min` 混入 ETF 日线审查页，也不复用其他对象池。

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
| 通配符 | `5*.SH`、`1*.SZ` 及组合值 `5*.SH,1*.SZ` 均可请求。2026-08-26 下午实测分别返回 `1102`、`1223`、`2325` 行，组合结果等于两市场之和。源端行数会变化，不能写成固定门禁。 |
| 返回形态 | 每次请求每个代码返回当时最新一根对应频率 K 线，不返回从开盘开始的完整序列。 |
| 旧时间 | 部分 ETF 可能返回较旧 `time`；保留源端事实，并由 health 展示。 |
| 字段 | `ts_code,freq,time,open,close,high,low,vol,amount`。 |

本地 0416 源文档仍写着“单次最大 1000 行”，但当前真实通配符请求已经返回 `2325` 行。工程实现以实测行为为准，不再把“1000 行”解释成必须分片或逐代码请求；该差异必须保留在 R0A/R0B 验证记录中。

2026-08-26 下午盘、收盘及2026-08-28早盘实测记录见：[ETF 实时分钟流 R0B 开市验证记录](/Users/congming/github/goldenshare/docs/architecture/realtime-etf-minute-r0b-open-market-validation-2026-08-26.md)。当前已确认组合通配符完整命中1395参考池、五频率下午闭合与逐步传播、`15:00` 最终 K 线，以及 `09:30` 独立起始 K 线和 `09:35=09:31-09:35` 首个完整五分钟窗口。

### 2.3 K 线闭合语义

开市实测已经确认：

1. `1MIN` 返回已闭合分钟，同一分钟重复读取内容保持不变，下一分钟才出现新行。
2. `5MIN` 只在五分钟窗口结束后返回新 K 线。
3. `09:30` 是独立开盘分钟，普通首个五分钟窗口是 `09:31-09:35`。

collector 必须按源端 K 线闭合时间请求，不能把尚未出现的新 K 线伪装成空值或零值。

---

## 3. 配置与选择池

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
max_calls_per_minute=20
lease_ttl_seconds=70
stale_after_seconds=90
snapshot_ttl_seconds=259200
keep_recent_batches=260
batch_stream_maxlen=5000
delta_stream_maxlen=200000
source_timeout_seconds=8
```

请求时机由频率对应的 K 线闭合槽决定；`poll_interval_seconds` 只约束 collector 的最大检查间隔，不能让 `5MIN/15MIN/30MIN/60MIN` 每分钟重复请求同一根 K 线。

`poll_interval_seconds` 必须限制在 `1-60` 秒。它只负责保证 unified collector 会及时重新检查 due state；真正的源请求时间仍由闭合槽、source-ready 延迟和 limiter 决定。

`source_ready_delay`、槽内重试间隔、槽截止时间、单槽最大尝试次数、固定频率顺序和各频率闭合网格不是运营配置项。R0B 后已经冻结为：闭合后 `+15s` 首次尝试、`+30s/+45s` 两个重试时点、`+55s` 完成截止、每频率每槽最多 3 次，频率顺序固定为 `1MIN,5MIN,15MIN,30MIN,60MIN`。这些事实进入代码 catalog/schedule policy，只读展示，不写入运营可编辑配置。

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

五频率共同边界的保守上界是 `5 x 3 = 15` 次源请求，因此初始 `max_calls_per_minute=20`，请求间最小间隔为 3 秒。该值不是“每个频率 20 次”，而是五个 ETF 分钟 feed 共用 `rt_etf_min` limiter 后的接口总上限。配置校验必须按实际闭合槽模拟任意滚动 60 秒窗口，不能用简单平均值代替。

### 3.3 ETF 实时分钟选择池

`etf_rt_min` 是 `ops.etf_series_active` 的 resource，不是单条配置或 Redis key。每个 ETF 占一行：

```text
resource=etf_rt_min, ts_code=510300.SH
resource=etf_rt_min, ts_code=159915.SZ
```

候选全集固定来自数据库现有 `resource=etf_rt_daily`，但 `resource=etf_rt_min` 初始为空，由运营在独立页面逐只选择加入。源端验证使用过的 1395 只 ETF 只是候选全集和容量上界参考，不是生产目标池，也不得写成固定数量门禁。

源站请求固定使用沪深组合通配符，因此选择池不改变源站请求参数或单次返回规模。选择池控制三个事实：哪些 ETF 必须到达目标分钟才能发布、哪些 ETF 写入 Redis、哪些 ETF 参与 missing/old-time/health 判断。collector 每个频率槽开始时读取并冻结 `etf_rt_min` 池，与源端返回代码取交集，只发布池内行；池外慢 ETF 不阻塞发布，也不算 invalid。

独立页面“ETF 实时分钟池配置”与“实时流配置中心”同级。页面候选列表来自 `etf_rt_daily`，支持每页 50 条、代码/名称关键词搜索和行内添加；已入池列表支持查询和删除。页面只维护成员关系和展示 ETF 基础信息。

选择池变更不需要重启 collector，在下一个频率槽生效。同一槽内的首次请求和后续重试必须继续使用槽开始时冻结的同一集合；中途新增或删除只影响下一槽。空池时不请求源站、不发布空批次，health 返回 `idle/source_pool_empty`。

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
预计 snapshot 数 = 选择池代码数 x keep_recent_batches x 启用频率数
```

容量不再按 1395 固定计算。五频率、每频率保留 260 批时，选择池 50/100/200/300 只分别对应 `65000/130000/260000/390000` 个 snapshot。页面展示当前选择池数量和按已启用频率计算的预计 snapshot 数，不设置无真实依据的固定池上限。R1A 必须在隔离 Redis namespace 中写入真实 snapshot/meta/index/current pointer/batch stream/delta stream，使用 `MEMORY USAGE` 和 `used_memory` 增量测量，不得用 Python 对象大小估算。R3 部署后再做受控容量复核；容量未通过时对象保持 disabled，由运营缩小选择池或减少启用频率。

---

## 5. 按 K 线闭合槽调度

调度不能使用“上一次请求结束时间 + interval”。每个频率必须从交易时段和频率计算下一根 K 线闭合槽：

```text
频率闭合槽
  -> 等待源端可用延迟
  -> 发起一次沪深组合通配符请求
  -> 与本槽冻结的运营选择池取交集
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
7. 单只停牌或长期无成交 ETF 的旧时间不等于“整个接口仍停在上一分钟”；批次就绪只根据本槽冻结选择池的目标分钟覆盖事实判断。
8. 一次 collector 调度最多发起一次 `rt_etf_min` 请求；返回旧时间或临时失败时，只登记 `next_retry_at` 并立即返回统一调度器，禁止在单次调用中循环等待到槽截止。
9. 同一分钟多个频率到期时，按固定频率顺序逐次尝试，并遵守 `rt_etf_min` 独立 limiter 的最小请求间隔；不能让 limiter 的阻塞等待占住其他实时 feed。

冻结后的调度参数：

| 项目 | 固定口径 |
| --- | --- |
| 首次尝试 | `expected_bar_time + 15s`。 |
| 第二、三次尝试 | 不早于 `+30s`、`+45s`，同时服从独立 limiter。 |
| 完成截止 | `expected_bar_time + 55s`；截止是请求完成边界，不是最后启动边界。 |
| 单次源请求超时 | `8s` 总墙钟时限；若 `now + 8s > deadline`，本槽不得再启动新请求。 |
| 最大尝试次数 | 每个频率每槽最多 3 次。 |
| lease TTL | `70s`，从首次尝试前获取，覆盖整个重试窗口与安全余量。 |
| API 总限速 | `20/min`，五频率共用 `rt_etf_min` 独立 limiter。 |
| 频率顺序 | `1MIN,5MIN,15MIN,30MIN,60MIN`。 |

请求未就绪、临时错误或空结果时由分钟调度器决定下一次尝试。`rt_etf_min` 使用 8 秒总墙钟超时和零次 HTTP transport 自动重试，保证一次调度尝试只对应一次有界 HTTP 请求；不能把现有 `(connect_timeout, read_timeout)` 元组误当成总耗时。现有 Tushare 其他接口的默认 timeout/retry 行为保持不变。

每个频率在槽内第一次请求前获取独立 lease，并持有到成功或槽截止。初始 `lease_ttl_seconds=70` 已覆盖本轮冻结的执行窗口，不增加续租。lease 释放必须使用 owner compare-and-delete 的原子操作，不能先读 owner 再单独删除，避免旧 owner 删除新 owner 的 lease。

现有 `TushareHttpClient` 自带多次 HTTP transport retry，最坏耗时可能超过一分钟槽。实现必须让客户端构造支持显式 retry policy，并为 ETF 实时分钟注入“零次自动重试”；默认 policy 保持不变，不能影响其他 Tushare API。

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

ETF 分钟不能沿用现有“`current_batch_age_seconds > stale_after_seconds`”的通用 stale 算法。`5MIN/15MIN/30MIN/60MIN` 在下一个闭合槽到来前没有新批是正常状态。reader 与 health 必须根据该频率的闭合网格判断：只有某个应发布槽已经超过 `expected_bar_time + 55s + stale_after_seconds`，而 current batch 仍早于该槽时才标 stale；当天首个应发布槽尚未到来时为等待状态，不得报 unavailable/stale。

---

## 7. Ops 配置与健康页面

配置中心增加 `etf_rt_min` 对象，`enabled_freqs` 使用五频率多选框。发布后继续通过重启 collector 的 apply-state 闭环生效。

新增只读 health API：

```http
GET /api/v1/ops/realtime/etf-rt-min/health
GET /api/v1/ops/realtime/etf-rt-min/health?freq=1MIN
```

实时流监控页面增加“ETF 实时分钟”区块，展示每个频率的启用状态、采集窗口、current batch、选择池数量与摘要、最新源端时间、快照数量、missed slot、无效行、单频率尝试数、`rt_etf_min` 聚合请求数、耗时和最近错误。页面只读取 Ops health API，不直接访问 Redis。

`missed slot` 必须区分“当前连续遗漏”和“当日累计遗漏”。后续成功发布新槽后，当前状态可以恢复为 `ok`，但当日累计值和最近遗漏时间继续保留，不能因为历史上漏过一次就永久显示 degraded。

---

## 8. 调整后的实施阶段

当前代码仍只有 `stock_rt_daily`、`stock_rt_min`、`etf_rt_daily` 三个实时对象；`etf_rt_min` 尚未实现。开发必须在现有主链内扩展第四对象，覆盖 runtime config/seed/catalog、统一 collector 与 CLI 装配、Tushare client、Redis state store、统一 reader、Ops config/health、独立选择池 API、实时流监控和前端路由。不得新建第二个 collector 服务，也不得把目标设计写成已上线事实。

| 阶段 | 目标 | 完成条件 |
| --- | --- | --- |
| R0A，已完成 | 收市静态源接口验证 | 独立 API 名、显式字段、五频率、组合通配符和收市返回规模已有真实记录。 |
| R0B，已完成 | 开市时间事实 | 下午、收盘和早盘边界已验证；等待、重试、截止、timeout、lease 和限速数值已冻结。 |
| R1A，可开发 | 静态能力与容量基准 | 第四配置对象、选择池 API、provider、normalizer、Redis 安全边界、reader、容量测量和单元测试完成；保持 `enabled=false`。 |
| R1B，可开发 | 调度策略 | 批次就绪、非阻塞 retry state、确定性 batch identity、原子 lease、limiter 和精确唤醒完成。 |
| R2 | collector、health 与页面 | 统一 collector 接入、按频率异常隔离、配置中心、选择池配置页和实时流监控页完成。 |
| R3 | 部署前初始化与收市验收 | 创建 disabled 配置行；选择池保持空；对账 apply state、空池状态，并用受控 Redis namespace 复核容量。 |
| R4 | 开市验收 | 时间槽连续性、Redis 批次、reader、health 和页面逐项对账后，才允许正式启用。 |

R0B 已经完成，不再阻塞 R1A/R1B。Redis 容量实测不是代码开发门禁，但仍是生产启用门禁；在 R3 容量对账通过前，`etf_rt_min.enabled` 必须保持 `false`。

生产发布顺序固定为：部署新代码但不启动新 collector 消费者，执行 realtime config seed 创建 `enabled=false` 的第四对象，再重启 Web 与统一 collector，核对 apply state 和 `idle/source_pool_empty`。随后由运营在“ETF 实时分钟池配置”页面选择 ETF，确认池数量与容量预估后，再发布 enabled 配置并重启 collector。选择池只通过页面维护，不执行自动全量初始化，也不要求与 `etf_rt_daily` 集合完全相同。
