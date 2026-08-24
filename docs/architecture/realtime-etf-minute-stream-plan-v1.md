# ETF 实时分钟流接入方案 v1

状态：方案待评审。尚未实现 `etf_rt_min` 配置对象、provider、collector、Redis feed、Ops health 或页面；M0 源端与限速门禁完成前不得开始编码。

创建日期：2026-08-24
适用范围：Tushare ETF 实时分钟源接入、实时流配置中心、实时流监控页，以及向后续业务提供分钟事实。
源接口事实：[Tushare 0416 ETF实时分钟](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0416_ETF实时分钟.md)
详细编码依据：[ETF 实时分钟流接入 LLD v1](/Users/congming/github/goldenshare/docs/architecture/realtime-etf-minute-stream-low-level-design-v1.md)
下游消费者：[ETF 实时成交额异动监控方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-etf-realtime-volume-anomaly-monitor-plan-v1.md)

---

## 1. 目标与边界

目标是将 ETF 实时分钟能力作为独立 realtime feed 接入现有主线：

```text
runtime config
  -> provider
  -> unified realtime collector
  -> Redis per-frequency batch/current pointer/health
  -> Ops health API
  -> 实时流配置中心 + 实时流监控页
  -> 下游业务按契约只读消费分钟事实
```

V1 覆盖 `1MIN/5MIN/15MIN/30MIN/60MIN` 五种频率。运营可以在配置中心选择实际启用哪些频率；不再把 `1MIN` 写死为唯一接入频率。

本方案不做：

1. 不新建 DatasetDefinition，不进入 TaskRun、freshness、date audit。
2. 不落 raw/core/serving 物理表；Redis 是实时源事实层。
3. 不增加 systemd 服务，继续使用 `goldenshare-realtime-collector.service`。
4. 不新增面向业务方的 ETF 分钟查询 API、WebSocket 或历史分钟回补。
5. 不将 ETF 成交额监控的规则、告警、Feishu、归档或监控池操作写入 realtime source 主链。

V1 的代码范围固定为 ETF 分钟源自己的活跃池：`ops.etf_series_active(resource='etf_rt_min')`。它是实时分钟源的对象范围，不是任何下游业务的监控名单。初始内容采用已确认 ETF 活跃池基线中与 `etf_rt_daily` 相同的代码集合，但用独立 resource 写入；后续两者可以各自调整，不产生隐式联动。

ETF 成交额监控是本源的一个下游消费者：它只能从 `etf_rt_min` 活跃池中选择自己的监控子集，不能通过增删、启停监控池来改变分钟源的采集范围、频率、调度或 health。

---

## 2. 已核验的源端事实与未冻结事项

### 2.1 本地文档事实

本地 0416 文档声明：

| 项目 | 事实 |
|---|---|
| 频率 | `1MIN/5MIN/15MIN/30MIN/60MIN` |
| 输入 | `ts_code`、`freq`，代码可逗号分隔 |
| 单次返回 | 最多 1000 行 |
| 输出 | `ts_code,time,open,close,high,low,vol,amount` |
| 文档 API 名 | `rt_min` |

### 2.2 2026-08-24 开市实测

通过 `tushareMcp.rt_etf_min` 在 14:57 CST 复测：

1. `510300.SH,159919.SZ` 以 `freq=1MIN`、显式字段请求，返回两行，两个代码均带 `ts_code/freq/time/open/close/high/low/vol/amount`。
2. 不传 `topic` 时，沪深混合代码可正常返回。
3. 对 `510300.SH` 传 `topic=HQ_FND_TICK` 返回 `50101` 参数校验失败。
4. 14:57 期间返回过 `time=14:57:00`，因此不能仅凭历史少量样本断言 `rt_etf_min` “只返回已闭合分钟”。

该实测优先于 MCP 工具说明中“沪市可传 topic”的描述。ETF 分钟 provider 不得复用 `rt_etf_k` 的上海 `HQ_FND_TICK` 请求规则。

### 2.3 M0 硬门禁

以下事实尚未冻结，未完成前不得编码：

1. **真实 HTTP API 名称**：本地文档为 `rt_min`，MCP 工具名为 `rt_etf_min`。必须以当前 `TushareHttpClient` 的实际 API 请求验证为准，不能按 MCP 工具名直接写常量。
2. **分钟标签和最终值语义**：在同一高流动 ETF 上，记录一分钟内至少三次 `1MIN` 返回和跨分钟返回，确认 `time` 是正在形成的 bar、上一个闭合 bar，还是提前标记的最终 bar。
3. **五频率闭合延迟**：分别验证五种频率在窗口末端前、后返回的 `time` 和 `amount`，确定可以接受该 bar 的最小稳定延迟。
4. **多代码容量**：验证 100、500、1000 个代码的响应成功率、耗时、字段完整性和源端实际限制；不得把两个或十个代码样本写成生产上限。
5. **同一响应时间不一致**：记录不同 ETF 同次响应的 `time` 差异，确认每行按自身 `time` 入桶的覆盖规则。
6. **限速归属**：若 ETF 与股票实时分钟实际共享 HTTP `rt_min`，必须先设计共享源站限速；不能让两套 feed 配置各自独立限速而实际共用一个 token/API 配额。

M0 的输出是一份日期化实测记录，包含请求参数、服务器发起/收到时间、每行 source `time`、`amount`、行数、耗时、错误与限速证据。

---

## 3. 目标 realtime 拓扑

### 3.1 配置对象与 feed

新增一个配置对象，不复用 `etf_rt_daily`：

```text
object_key: etf_rt_min
object_kind: feed_group
display_name: ETF 实时分钟
```

每个启用频率对应一个独立 feed：

```text
tushare_etf_rt_min_1min
tushare_etf_rt_min_5min
tushare_etf_rt_min_15min
tushare_etf_rt_min_30min
tushare_etf_rt_min_60min
```

它们各自维护 batch、current pointer、snapshot、stream、lease 和 health。不得把 `freq:ts_code` 拼入单个 ETF 日线 feed，也不得将五频率混入同一 current batch。

### 3.2 独立对象池与请求分片

每个 due frequency 从 `ops.etf_series_active(resource='etf_rt_min')` 读取 `ts_code`，按 M0 冻结的单请求上限分片。它是 source-level 活跃池，与 `ops.etf_realtime_monitor_pool` 无读写依赖。空 source 活跃池时：

1. 不请求 Tushare。
2. 不发布空 batch 覆盖既有 current pointer。
3. 写该频率 feed 的 `idle/pool_empty` health。

`etf_rt_min` 活跃池不是 runtime config，不能通过实时流配置中心或 ETF 实时监控配置中心修改。M1 实施时必须扩展现有 ETF 活跃池 seed 资源白名单，单独 seed `resource='etf_rt_min'`；seed 前后校验 source resource 的行数、去重代码和 `.OF` 排除口径。

### 3.3 频率调度

不是每 60 秒对全部 frequency 无差别轮询。对每个启用频率独立计算 due time：

```text
bar end + closed_bar_grace_seconds
```

例如 `5MIN` 只在 `09:35/09:40/...` 对应窗口结束后的 grace 到达时请求。上午和下午交易时段分别计算，严禁跨午休拼窗。

M0 必须给出 `time` 标签/最终值语义后，冻结“预期 bar end”的匹配规则：

1. 若源端在 grace 后返回上一根闭合 bar，只接受 `source_time == expected_bar_end`。
2. 若源端返回形成中 bar，collector 必须延后到该 bar 已最终确定后才接受；不得把第一次看到的金额写为最终分钟事实。
3. 超过 M0 冻结的最大等待期仍无目标 bar 时，写真实 `missing` 观测，不能补 0。

### 3.4 请求量模型

令：

```text
C = ceil(etf_rt_min_active_code_count / validated_codes_per_request)
F = enabled_freqs
```

每个 frequency 周期需要 `C` 次请求。最拥挤的分钟可能同时出现 `1/5/15/30/60MIN` 的 bar end，因此该分钟的峰值需求是：

```text
peak_calls_per_minute = C * len(F)
```

这不是平均值；发布校验和运行时 pool 扩容检查都必须以峰值为准。若 M0 确认 ETF 与股票分钟共享真实 HTTP API/限速桶，还必须叠加股票分钟当分钟峰值需求，使用共享配额判断，而不是各自通过即认为安全。

---

## 4. 配置中心设计

### 4.1 前端入口和信息层级

不新增独立菜单。复用既有一级菜单“实时流配置中心”：

```text
实时流配置中心
  - 股票实时日线
  - 股票实时分钟
  - ETF 实时日线
  - ETF 实时分钟  <- 新增对象
```

点击 `ETF 实时分钟` 后，右侧依旧采用现有页面的查看态/编辑态分离：

1. 查看态只展示已发布配置、启用频率标签、锁定源端事实、apply state 和修订历史。
2. 编辑态才显示草稿、校验、diff、发布影响和“重启 collector”操作。
3. 发布成功不伪造为已生效，继续等待 collector apply state 上报相同版本。

`ETF实时监控配置中心` 继续负责监控对象池和规则；不得把“选择哪些 ETF”塞进实时流配置中心。

### 4.2 可编辑字段

| 字段 | 控件 | 规则 |
|---|---|---|
| `enabled` | switch | 关闭后所有频率 idle，不请求源站 |
| `enabled_freqs` | 五项 checkbox group | `1MIN/5MIN/15MIN/30MIN/60MIN`；至少选一项；按计划可按需多选 |
| `closed_bar_grace_seconds` | number input | M0 后冻结允许范围；用于每个 frequency 的 bar-end 后延迟 |
| `max_calls_per_minute` | number input | 必须通过 ETF 分钟 source 活跃池 peak request 预算校验 |
| `lease_ttl_seconds` | number input | 必须覆盖单次分片采集的最大预计耗时 |
| `stale_after_seconds` | number input | 不小于该 frequency 的最长正常刷新间隔加 grace |
| `snapshot_ttl_seconds` | number input | Redis batch/snapshot 留存；默认 72 小时 |
| `keep_recent_batches` | number input | 只控制 per-frequency batch 留存，不是分钟归档前提 |
| `batch_stream_maxlen` / `delta_stream_maxlen` | number input | 复用现有 realtime store 的限长语义 |
| `source_timeout_seconds` | number input | 单源请求超时 |

### 4.3 锁定字段

```text
source_api_name（M0 冻结后写入）
source_code_scope=ops.etf_series_active(resource=etf_rt_min)
supported_freqs=1MIN/5MIN/15MIN/30MIN/60MIN
feed_key_pattern=tushare_etf_rt_min_{freq_lower}
collection_sessions=09:30-11:30,13:00-15:00
topic_policy=omit
validated_codes_per_request（M0 冻结后写入）
```

锁定字段只展示为标签/只读文本。前端提交它们或未知字段时，Ops API 必须返回结构化拒绝。

### 4.4 校验和发布影响

`validate` 必须返回：当前/草稿 diff、启用 feed 列表、ETF 分钟 source 活跃池数量、每频率请求分片数、峰值调用数、与股票分钟共享配额时的总需求、发布后重启提示。它不得读取 ETF 成交额监控规则或监控池。

`publish` 使用当前 version 乐观锁，只更新 `foundation.realtime_runtime_config` 与 `ops.config_revision`，不请求 Tushare、不写 Redis、不热加载。发布成功后页面提示“需要重启 collector 生效”。

---

## 5. collector、Redis、health 与下游边界

### 5.1 collector

`RealtimeCollectorService` 扩展为第四类对象调度：

```text
股票实时日线
股票实时分钟（现有）
ETF 实时日线（现有）
ETF 实时分钟（新增，按 frequency 独立 due time）
```

每个 ETF frequency 有独立 lease、due time、publish 和 error isolation。任一 frequency 失败不得影响 ETF 日线或任何股票 feed。

### 5.2 Redis

每个成功频率/分片轮次只在所有该 frequency 请求分片成功后发布新 batch，随后原子切换本 frequency 的 current pointer。分片中任一请求失败时：

1. 保留旧 current pointer。
2. health 标记 `degraded`，记录 error 和分片覆盖信息。
3. 不将半对象池 snapshot 当作完整分钟事实。

分钟消费需要在 state store 增加受控的“分钟采集/最终值”记录 contract，供下游监控和收盘归档读取。Ops 不直接拼 Redis key。

### 5.3 Health API 与实时流监控页

新增：

```http
GET /api/v1/ops/realtime/etf-rt-min/health
GET /api/v1/ops/realtime/etf-rt-min/health?freq=1MIN
```

不带 `freq` 固定返回五项；禁用项也返回 `enabled=false`，让页面完整显示支持范围。每项至少包含：

```text
freq, feed_key, status, enabled, collection_status,
current_batch_id, expected_bar_end, latest_source_time,
pool_count, requested_code_count, snapshot_count,
missing_count, invalid_count, request_count_last_minute,
source_elapsed_ms, write_elapsed_ms, last_success_at, last_error_message
```

实时流监控页新增“ETF 实时分钟”区块，沿用股票实时分钟的频率卡片模式。浏览器只轮询 Ops health API，并仅在 API 返回 `page_polling_enabled=true` 且交易时段 open 时按现有局部 refetch 机制刷新；不整页刷新、不触发 collector、不请求 Tushare。

### 5.4 对成交额监控的明确交付契约

ETF 实时成交额监控只能消费标记为 `final/valid` 的分钟事实：

```text
ts_code
freq
source_time
amount_yuan
vol
captured_at
quality=valid|missing|invalid
reason_code
source_batch_id
```

本 source 接入不定义成交额异常阈值、不产生 Feishu、不写 PostgreSQL 历史统计。那些职责属于下游成交额监控方案，且必须等 `1MIN` 的最终值语义在 M0 确认后才能接入。

---

## 6. 实现里程碑与测试

| 阶段 | 目标 | 通过条件 |
|---|---|---|
| M0 | 源端/限速/时间语义实测记录 | 第 2.3 节六项都有实测结论 |
| M1 | runtime config/catalog/seed/apply state/source 活跃池 resource | 新对象缺失 fail-fast；独立 `etf_rt_min` 活跃池 seed 完整；未启用不请求 |
| M2 | provider/normalizer/Redis publisher | topic/API 名、fields、分片、行级时间测试通过 |
| M3 | unified collector/health | 五频率独立 due/lease/error isolation；无新 systemd |
| M4 | Ops config API 与配置中心/监控页面 | checkbox、校验、发布、重启闭环和 health 五项展示通过 |
| M5 | 下游分钟事实消费联调 | 提供稳定的 `1MIN final/valid` 契约；成交额监控只是可选消费者，不反向参与 source 调度 |
| M6 | 部署与开市验收 | 首次开市验证覆盖、健康、Redis 隔离和页面状态通过 |

测试至少覆盖：

1. 频率规范化、空 frequency、非法 frequency、每 frequency feed key 隔离。
2. API 名/topic policy、显式字段、多代码分片、分片失败不发布。
3. 形成中/闭合 bar 的 M0 结论对应 acceptance rule。
4. `etf_rt_min` source 活跃池为空、seed/变更、超 1000 分片和请求峰值预算；证明监控池变更不会改变 source 请求范围。
5. enabled/disabled、非交易时段、午休边界、独立 due time、lease skip、单 frequency degraded。
6. Redis current pointer 原子性、health 结构、source time 不一致和 `missing/invalid` 不变为 0。
7. config list/detail/validate/publish/revision/apply state/restart，前端 checkbox 与只读锁定字段。
8. 实时流监控页面局部轮询、五频率健康展示和单区块失败隔离。

---

## 7. 开发前结论

可以完成文档和 M0 实测，但**现在不能开始编码**。阻塞项不是页面或数据库表，而是：真实 HTTP API 名、分钟 bar 最终值语义、五频率稳定延迟、多代码容量，以及与股票分钟是否共享限速桶。这些事实一旦冻结，LLD 中的 file-by-file 改造和测试清单可直接执行。
