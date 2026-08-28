# ETF 实时日线流接入方案 v1

状态：源接口开市实测完成 / 代码主线已接入 / 生产配置已启用 / 开市批次验收已完成
源接口事实：[Tushare 0400 ETF实时日线](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0400_ETF实时日线.md)  
关联上位方案：[实时行情流架构方案 v1](/Users/congming/github/goldenshare/docs/architecture/realtime-market-data-stream-architecture-v1.html)  
关联配置中心：[Ops 实时流配置中心技术方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-realtime-config-center-technical-plan-v1.html)  
适用范围：Tushare `rt_etf_k` ETF 实时日线 V1

---

## 1. 目标

接入 Tushare `rt_etf_k`，在交易日交易时段内采集全市场 ETF 实时日线快照，并按时间批次写入 Redis。

V1 目标用一句话描述：

> 每 60 秒拉取一次源端全市场 ETF 实时日线，沪深两段都成功后合并为一个 Redis 批次快照，再原子切换 current pointer。

本方案只处理实时源采集与 Redis 快照，不处理离线数据集同步。

## 2. 非目标

1. 不落库，不建 raw/core/serving 表。
2. 不创建 `DatasetDefinition`，不进入 TaskRun、freshness、date audit。
3. 不做 ETF 类型二次过滤，V1 保存源端通配符返回的完整事实。
4. 不新增独立 systemd 服务，继续使用现有 `goldenshare-realtime-collector.service` 统一 collector。
5. 不在本轮实现业务快照 API，除非后续页面或业务调用方明确需要。
6. 不实现 WebSocket；若后续需要，复用 Redis stream 另行设计。

## 3. 已拍板口径

| 事项 | 结论 |
| --- | --- |
| 采集间隔 | `60` 秒 |
| Redis 保留策略 | `snapshot_ttl_seconds=259200`，即 72 小时；`keep_recent_batches=3` |
| 全市场范围 | 不做二次过滤，完整保存源端返回事实 |
| 发布完整性 | 沪深两段都成功才发布新 current batch；任一段失败不发布半市场快照 |
| 采集时段 | 交易日 `09:30-11:30,13:00-15:00` |
| 存储方式 | Redis `batch_id + current pointer`，按时间批次保存全市场快照 |

## 4. 开市真实验证记录

验证时间：2026-06-03 10:03-10:26 CST，A 股连续竞价时段。

验证工具：

1. `tushareMcp.rt_etf_k`：核验真实入参、字段、topic 行为。
2. 本地 `TushareHttpClient` 只读请求：补充行数、字段缺失、时间分布统计。

### 4.1 字段验证

默认返回字段不足以支撑实时快照展示，因为默认不返回 `trade_time`。

V1 provider 必须显式请求：

```text
ts_code,name,trade_time,pre_close,open,high,low,close,vol,amount,num,ask_price1,bid_price1,ask_volume1,bid_volume1
```

实测结论：

1. `trade_time` 可以显式返回，应作为快照时间字段保存。
2. `ask_price1/bid_price1` 虽未在本地文档输出参数表中列出，但开市实测沪深单只 ETF 均可显式返回。
3. 部分行 `open/high/low/close=0` 是源端事实，不得当作失败或无效行拒绝。
4. `name` 可能带尾部空格，normalizer 应做字符串 trim。

### 4.2 topic 与通配符验证

| 场景 | 请求 | 结果 | 结论 |
| --- | --- | --- | --- |
| 上海单只 | `topic="HQ_FND_TICK", ts_code="510300.SH"` | 返回 1 行 | 上海必须带 `HQ_FND_TICK` |
| 上海单只空 topic | `topic="", ts_code="510300.SH"` | 返回空数组 | 不能用空 topic 拉上海 |
| 上海通配符 | `topic="HQ_FND_TICK", ts_code="5*.SH"` | 返回上海侧数据 | 上海段采用此请求 |
| 深圳通配符 | `topic="", ts_code="1*.SZ"` | 返回深圳侧数据 | 深圳段采用此请求 |
| 深圳窄通配符 | `topic="", ts_code="15*.SZ"` | 返回深圳 `159...` 子集 | 会漏源端 `1*.SZ` 返回事实，不作为全市场范围 |
| 沪深拼接 + 上海 topic | `topic="HQ_FND_TICK", ts_code="5*.SH,15*.SZ"` | 只观测到上海侧 | 不能作为全市场请求 |
| 沪深拼接 + 空 topic | `topic="", ts_code="5*.SH,15*.SZ"` | 只观测到深圳侧 | 不能作为全市场请求 |

最终请求方式：

```json
[
  {"market": "SH", "topic": "HQ_FND_TICK", "ts_code": "5*.SH"},
  {"market": "SZ", "topic": "", "ts_code": "1*.SZ"}
]
```

### 4.3 行数与数据质量

2026-06-03 10:26 CST 使用最终通配符统计：

| 分段 | topic | ts_code | 行数 | ts_code 缺失 | trade_time 缺失 | OHLC 全 0 行 | trade_time 范围 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 上海 | `HQ_FND_TICK` | `5*.SH` | 1055 | 0 | 0 | 23 | `2026-06-03 10:26:26` ~ `2026-06-03 10:26:56` |
| 深圳 | 空字符串 | `1*.SZ` | 1151 | 0 | 0 | 64 | `2026-05-20 17:00:33` ~ `2026-06-03 10:26:54` |
| 合计 | - | - | 2206 | 0 | 0 | 87 | - |

说明：

1. 深圳 `1*.SZ` 会返回比 `15*.SZ` 更广的源端事实，包含 `123...`、`180...` 等代码段。由于已拍板“不筛，完整保存源端事实”，V1 使用 `1*.SZ`。
2. 深圳存在旧 `trade_time` 样本，这是源端返回事实。V1 不把单行旧时间判为整个 feed 失败，只在页面/health 中展示源端时间和批次时间。
3. 合计约 2200 行，60 秒一次、每轮 2 次源请求，适合 Redis 快照，不需要分页，不适合落库。

## 5. Redis 存储模型

复用现有实时状态层，不新增 Redis key 模型。

建议 feed key：

```text
tushare_etf_rt_k
```

关键 Redis key 形态：

```text
rt:feed:tushare_etf_rt_k:current_batch
rt:feed:tushare_etf_rt_k:batch:{batch_id}:snapshot:{ts_code}
rt:feed:tushare_etf_rt_k:batch:{batch_id}:index
rt:feed:tushare_etf_rt_k:batch:{batch_id}:meta
rt:feed:tushare_etf_rt_k:batches
rt:feed:tushare_etf_rt_k:stream:batch
rt:feed:tushare_etf_rt_k:stream:delta
rt:feed:tushare_etf_rt_k:health
rt:feed:tushare_etf_rt_k:lease
```

写入顺序：

1. 请求上海段。
2. 请求深圳段。
3. 两段都成功后合并 rows。
4. normalizer 生成 snapshots。
5. 读取上一批 current batch，计算 delta snapshots。
6. `publish_batch()` 写入新批次 snapshot/index/meta/stream。
7. 原子切换 `current_batch`。
8. 写 health。

一致性口径：

1. API 读取永远只读 current pointer 指向的同一个 `batch_id`。
2. 不加前端读锁，不扫描散 key，不读半新半旧数据。
3. 如果本轮任一分段失败，不调用 `publish_batch()`，只写 degraded health，保留上一批 current batch。

## 6. Runtime Config 设计

新增 realtime 配置对象，建议：

| 字段 | 建议值 |
| --- | --- |
| `object_key` | `etf_rt_daily` |
| `object_kind` | `collector_feed` |
| `display_name` | `ETF 实时日线` |
| `source_api_name` | `rt_etf_k` |
| `feed_key` | `tushare_etf_rt_k` |
| `collection_sessions` | `09:30-11:30,13:00-15:00` |

可编辑配置：

| 配置项 | 默认值 | 说明 |
| --- | ---: | --- |
| `enabled` | `false` | 初始不自动启用，由配置中心发布 |
| `poll_interval_seconds` | `60` | 已拍板 |
| `max_calls_per_minute` | `10` | 每轮 2 次请求，60 秒一次，10/min 足够覆盖并留余量 |
| `lease_ttl_seconds` | `120` | 覆盖一次采集周期和偶发慢请求；当前代码默认值见 `DEFAULT_ETF_RT_DAILY_RUNTIME_CONFIG` |
| `stale_after_seconds` | `180` | 大于 60 秒采集间隔，避免轻微抖动误报 |
| `snapshot_ttl_seconds` | `259200` | 72 小时，已拍板 |
| `keep_recent_batches` | `3` | 已拍板 |
| `batch_stream_maxlen` | `5000` | 沿用现有实时 feed 默认 |
| `delta_stream_maxlen` | `200000` | 沿用现有实时 feed 默认 |
| `source_timeout_seconds` | `20` | 与现有实时分钟源请求超时口径一致 |

锁定配置：

| 锁定项 | 值 | 原因 |
| --- | --- | --- |
| `request_segments` | `SH: HQ_FND_TICK + 5*.SH`，`SZ: "" + 1*.SZ` | 防止配置中心误改导致漏市场或漏代码段 |
| `source_api_name` | `rt_etf_k` | 源接口事实 |
| `feed_key` | `tushare_etf_rt_k` | Redis key 事实 |
| `collection_sessions` | `09:30-11:30,13:00-15:00` | 与现有实时主线一致 |

## 7. Collector 与健康状态

collector 继续由 `RealtimeCollectorService` 统一调度。

新增 ETF collector 后，调度规则为：

1. `etf_rt_daily.enabled=false` 时不请求源站，只展示 disabled/idle。
2. 非交易日、午休、收盘后不请求源站，只写 idle/market_closed。
3. 交易日交易时段内，每 60 秒执行一次 ETF feed。
4. ETF feed 失败不影响股票实时日线和股票实时分钟。
5. ETF feed 写入 `realtime_config_apply_state`，即使 disabled 也要上报已应用版本，避免配置中心误判“待重启”。

health 建议字段：

```json
{
  "status": "ok",
  "feed_key": "tushare_etf_rt_k",
  "enabled": true,
  "collector_running": true,
  "collector_id": "...",
  "collection_status": "open",
  "last_request_at": "...",
  "last_success_at": "...",
  "current_batch_id": "...",
  "current_batch_received_at": "...",
  "current_batch_published_at": "...",
  "source_row_count": 2206,
  "snapshot_count": 2206,
  "source_snapshot_count": 2206,
  "eligible_etf_count": 1395,
  "eligible_snapshot_count": 1320,
  "segment_counts": {"SH": 1055, "SZ": 1151},
  "invalid_count": 0,
  "invalid_reason_counts": {},
  "request_count_last_minute": 2,
  "source_elapsed_ms": 1680,
  "write_elapsed_ms": 0,
  "last_error_message": null
}
```

## 8. Ops 与页面接入

V1 最小闭环建议接入两个页面：

1. 实时流配置中心：新增 `ETF 实时日线` 对象，可查看、编辑、校验、发布、重启 collector。
2. 实时流监控：新增 `ETF 实时日线` 分组，展示采集状态、当前批次、快照数量、分段行数、源端耗时、Redis 状态、错误信息。

页面仍只读 Ops API：

```http
GET /api/v1/ops/realtime/etf-rt-daily/health
GET /api/v1/ops/realtime/config/objects
GET /api/v1/ops/realtime/config/objects/etf_rt_daily
```

页面禁止事项：

1. 不请求 Tushare。
2. 不直接读 Redis。
3. 不自行拼 feed key。
4. 不自行计算 stale、交易日、交易时段。

业务快照 API 暂不作为 V1 必需项。若后续行情页面需要读取单个或多个 ETF 当前快照，再新增：

```http
GET /api/v1/realtime/etf-rt-daily?ts_codes=510300.SH,159919.SZ
```

## 9. 开发里程碑

| Milestone | 目标 | 边界 |
| --- | --- | --- |
| M0 | 本方案评审与口径冻结 | 不改代码 |
| M1 | 配置模型接入 | 已完成：扩展 `runtime_config.py`、`config_catalog.py`、seed、apply state；不请求源站 |
| M2 | Provider / normalizer / publisher | 已完成：实现 `rt_etf_k` 两段请求、字段归一化、全量批次发布；补单元测试 |
| M3 | Collector 调度 | 已完成：接入统一 collector；保证独立 due time、独立 lease、独立 health |
| M4 | Ops health / 配置中心接入 | 已完成：新增 health API，配置中心对象列表/detail/validate/publish 支持 ETF |
| M5 | 前端实时流监控与配置中心展示 | 已完成：新增 ETF 分组和配置对象；不改股票日线/分钟现有展示 |
| M6 | 生产部署与开市验收 | 已完成：生产已 seed `etf_rt_daily`、发布启用并重启 collector，并已完成开市批次验收 |
| M7 | 可选业务 API | 只有出现明确业务消费页面时再做 |

## 10. 测试与验收

### 10.1 必测项

1. `rt_etf_k` provider 必须按两段请求：`5*.SH + HQ_FND_TICK`、`1*.SZ + 空 topic`。
2. provider 不得使用 `15*.SZ` 作为全市场深市范围。
3. explicit fields 必须包含 `trade_time`、`ask_price1`、`bid_price1`、`ask_volume1`、`bid_volume1`。
4. 两段都成功才 publish；任一段失败不切 current pointer。
5. normalizer 保留源端 `trade_time`，旧时间行不判 feed 失败。
6. OHLC 全 0 行保留，不拒绝。
7. Redis TTL 为 72 小时，只保留最近 3 批。
8. 配置中心可编辑项不得包含 `request_segments`、`feed_key`、`source_api_name`。
9. collector apply state 必须包含 `etf_rt_daily.version`。
10. ETF feed 异常不得影响股票实时日线和股票实时分钟。

### 10.2 验收命令建议

持续回归至少执行：

```bash
uv run pytest -q tests/test_realtime_etf_rt_daily.py
uv run pytest -q tests/test_realtime_runtime_config.py tests/test_realtime_collector_service.py
uv run pytest -q tests/web/test_realtime_api.py tests/web/test_ops_realtime_config_api.py
uv run pytest -q tests/architecture/test_subsystem_dependency_matrix.py
cd frontend && npm run typecheck
cd frontend && npm run test -- ops-realtime-monitor-page
cd frontend && npm run test -- ops-realtime-config-center-page
python3 scripts/check_docs_integrity.py
```

## 11. 风险与处理

| 风险 | 影响 | 处理 |
| --- | --- | --- |
| `15*.SZ` 被误用 | 深市源端事实漏取 | 文档和测试必须断言 V1 使用 `1*.SZ` |
| 单段失败后发布半市场 | 页面误认为当前批次是全市场 | all-or-nothing publish |
| 源端返回旧 `trade_time` | 页面可能误解单只 ETF stale | 保留源端时间，由页面展示；feed stale 以批次发布时间判断 |
| 源端返回 OHLC 全 0 | 被误拒绝导致快照不完整 | 作为源端事实保留 |
| 新 feed 绕过配置中心 | 运行配置再次分散 | 必须接 `foundation.realtime_runtime_config` 和配置中心 |
| Redis 批次过多 | 内存上涨 | V1 只保留最近 3 批，TTL 72 小时 |

## 12. 生产配置收口记录

2026-06-18 已完成生产配置收口：

1. 远程代码版本：`2f7a79e8`。
2. `ops-seed-realtime-runtime-config --apply` 已创建缺失的 `etf_rt_daily` 配置行。
3. 通过配置服务发布 `etf_rt_daily.enabled=true`，配置版本从 `1` 升到 `2`，`ops.config_revision` 记录 revision `73`。
4. 已重启 `goldenshare-realtime-collector.service`。
5. collector 已上报 `etf_rt_daily.applied_version=2`，配置中心应显示“已应用”。
6. 当时收盘后 health 符合预期且未请求源站。该次历史验收使用旧池字段记录 1,395；当前契约已改为按 API 调用时固定日期动态读取 ETF Basic，返回 `eligible_etf_count/eligible_snapshot_count`，不再把该数量固化为运行门禁。

开市验收已完成：

1. `tushare_etf_rt_k` 产生 current batch。
2. `segment_counts` 同时包含 `SH` 与 `SZ`。
3. `source_snapshot_count/source_row_count` 与实时源批次一致；`eligible_etf_count/eligible_snapshot_count` 与同一次 Health 调用固定的 ETF Basic 当前可请求集合一致。
4. 任一分段失败时不切 current pointer，只写 degraded health。
