# ETF 实时分钟流接入 LLD v1

状态：源接口与调度事实仍有效；原运营选择池依赖即将退场的 `ops.etf_series_active`，选择池及其代码边界须重新基线，当前不可按本文直接开工。

创建日期：2026-08-24
最近更新：2026-08-29

上位方案：[ETF 实时分钟流接入方案 v1](/Users/congming/github/goldenshare/docs/architecture/realtime-etf-minute-stream-plan-v1.md)

> 2026-08-29 边界校准：ETF 基础信息重建方案已确认删除整套 `ops.etf_series_active`。本文第 4 节及其关联的 contract、adapter、API、页面和测试设计暂时只保留为历史方案，后续开发前必须另行重新基线；本轮不在此处设计替代池，也不修改实时分钟代码。

---

## 1. 开发目标与边界

本需求把 Tushare `rt_etf_min` 接入现有 realtime 主链，形成独立的 ETF 实时分钟 feed：

```text
runtime config
  -> ETF 实时分钟选择池
  -> rt_etf_min provider
  -> unified realtime collector
  -> Redis batch / current pointer / stream / health
  -> RealtimeSnapshotReader
  -> Ops 配置中心与实时流监控
```

代码范围：

1. `src/foundation/realtime/**`：配置目录、运行时配置、provider、normalizer、collector、reader。
2. `src/ops/**`：配置管理、ETF 实时分钟选择池、health 查询与 API。
3. `src/app/**`：依赖装配和路由挂载。
4. `frontend/**`：实时流配置中心、ETF 实时分钟池配置和实时流监控页面。

架构边界：

1. `foundation` 通过现有 `EtfSeriesActiveStore` 读取代码池，不 import Ops ORM。
2. 继续复用唯一的 `goldenshare-realtime-collector.service`，不新增 systemd 服务。
3. 不新增 `DatasetDefinition`、TaskRun、业务表、ORM 或 Alembic 迁移；运营选择结果写入既有 `ops.etf_series_active(resource=etf_rt_min)`。
4. Redis 存储直接复用现有 `RealtimeStateStore` 批次模型。
5. 不新增外部业务 HTTP API；本轮新增 foundation 统一 reader，供后续调用方复用。

### 1.1 当前代码基线与目标差异

截至 2026-08-28，当前代码只有 `stock_rt_daily`、`stock_rt_min`、`etf_rt_daily` 三个 realtime 对象，仓库中尚无 `etf_rt_min` provider、collector、health、reader 或前端页面实现。实施不能把本文目标态误当成现状，必须同时改造以下真实消费者：

1. `runtime_config.py`、`runtime_config_seed_service.py`、`config_catalog.py` 目前只认识三个配置对象。
2. `collector_service.py` 与 `src/cli_parts/realtime_handlers.py` 当前只装配股票日线、股票分钟和 ETF 日线；现有 due time 是“执行完成时间 + interval”。
3. `TushareHttpClient` 当前默认启用多次 transport retry，`_RateLimiter.acquire()` 会 sleep。
4. `RedisRealtimeStateStore` 当前按 `ts_code` 归并 snapshot，重复身份会后写覆盖；发布事务后的 cleanup 异常会向上抛出；lease 释放是非原子的先读后删。
5. `RealtimeSnapshotReader` 当前只有股票日线/分钟读取，并按 current batch 发布年龄计算 stale。
6. `RealtimeConfigCommandService`、config apply state、Ops health 和前端测试 fixture 当前都只覆盖三个对象；配置中心页面本身由 API 字段驱动，不需要另写一套 ETF 分钟表单常量。

目标实现必须一次性清零这些三对象假设和旧调度语义，不能增加旁路 collector、临时 Redis key 或页面自行拼装配置事实。

---

## 2. 已确认的源接口契约

### 2.1 固定 API 与参数

provider 只调用：

```python
client.call(
    "rt_etf_min",
    params={"ts_code": "5*.SH,1*.SZ", "freq": freq},
    fields=("ts_code", "freq", "time", "open", "close", "high", "low", "vol", "amount"),
)
```

工程请求不得增加 `topic` 或其他未在 0416 文档中定义的参数。

当前实测事实：

1. `rt_etf_min` 接口名可直接请求。
2. 沪深 ETF 均可使用 `ts_code + freq` 请求。
3. 返回身份字段为 `ts_code/freq/time`。
4. 支持 `1MIN/5MIN/15MIN/30MIN/60MIN`。
5. 每个代码返回当前最新一根对应频率 K 线，不返回全天序列。
6. `5*.SH`、`1*.SZ` 和组合通配符 `5*.SH,1*.SZ` 均可请求。
7. 2026-08-26 下午实测：上海返回 `1102` 行、深圳返回 `1223` 行、组合请求一次返回 `2325` 行，组合结果无重复且等于两市场之和。源端行数会变化，不能写成固定门禁。

### 2.2 文档差异与请求结论

源文档写明单次最多返回 1000 行，但当前组合通配符请求已经真实返回 `2324` 行。实现必须以当前实测为准：

1. 每个到期频率只发一次 `ts_code=5*.SH,1*.SZ` 请求。
2. 不按候选池或选择池分片，不逐个代码请求。
3. provider 不从选择池拼接源站请求参数。
4. 源端全市场结果在 normalizer 中与本槽冻结的运营选择池取交集，Redis 只保存池内行。
5. 文档“1000行”与实测“2325行”的差异必须保留在 R0A/R0B 记录，不得重新据此引入分片。

### 2.3 R0B 开市验证状态

详细证据见：[ETF 实时分钟流 R0B 开市验证记录](/Users/congming/github/goldenshare/docs/architecture/realtime-etf-minute-r0b-open-market-validation-2026-08-26.md)。2026-08-26 下午盘已经确认：

1. 组合通配符携带全部显式字段返回 `2325` 行、无重复和身份字段缺失，完整命中 1395 只参考池，普通响应约 `0.5-0.8s`。
2. 源端按单只 ETF 逐步传播已闭合 K 线，不是整批原子切换；部分传播结果不能发布。
3. `1MIN/5MIN/15MIN/30MIN/60MIN` 下午闭合网格成立；`30MIN/60MIN` 午休后首个窗口分别可在 `13:30/14:00` 观察到，午休不跨窗。
4. 五频率共同边界单次请求最高约 `3.934s`；普通边界闭合后约 15 秒通常完整，但 `14:00` 的 `1MIN` 在约 22 秒仍有 84 只未切换，必须有池覆盖校验和有界重试。
5. `15:00` 收盘后仍能取得五频率最终 K 线；`5/15/30/60MIN` 在约 20 秒内完整，`1MIN` 在约 17 秒仍有 460 只未切换，到约 35.6 秒完整。

2026-08-28早盘进一步确认：`09:30` 独立成线，`09:35` 的 `5MIN` 精确聚合 `09:31-09:35`，不包含 `09:30`；1395参考池在 `09:30` 约 `+21.375s`、`09:31` 约 `+11.891s`、`09:35` 的 `1MIN/5MIN` 约 `+15.783s/+12.046s` 完整切换。

截止失败规则已经冻结：本槽选择池未完整到达目标分钟时不发布残缺批次，保留上一 current pointer，并在 health 记录缺失代码和目标槽。

等待、重试、截止、限速、timeout 和 lease 数值已经依据上述实测冻结。R1A 仍须使用真实 Redis 字段完成容量测试；容量测试不阻塞本地编码，但未通过前不得在生产启用对象。

---

## 3. Runtime Config 与 Catalog

### 3.1 Catalog 锁定事实

在 `src/foundation/realtime/config_catalog.py` 增加 ETF 实时分钟目录事实：

```python
ETF_RT_MIN_OBJECT_KEY = "etf_rt_min"
ETF_RT_MIN_DISPLAY_NAME = "ETF 实时分钟"
ETF_RT_MIN_SOURCE_API_NAME = "rt_etf_min"
ETF_RT_MIN_SUPPORTED_FREQS = ("1MIN", "5MIN", "15MIN", "30MIN", "60MIN")
ETF_RT_MIN_FEED_KEY_PREFIX = "tushare_etf_rt_min"
ETF_RT_MIN_COLLECTION_SESSIONS = "09:30-11:30,13:00-15:00"
ETF_RT_MIN_ACTIVE_RESOURCE = "etf_rt_min"
```

增加锁定调度策略：

```python
@dataclass(frozen=True, slots=True)
class EtfRtMinSchedulePolicy:
    source_ready_delay_seconds: int = 15
    retry_interval_seconds: int = 15
    retry_deadline_offset_seconds: int = 55
    max_attempts_per_slot: int = 3
    freq_order: tuple[str, ...] = ("1MIN", "5MIN", "15MIN", "30MIN", "60MIN")
```

它和各频率闭合网格属于 catalog/schedule policy 锁定事实，不进入 `runtime_config_json`。三个允许的尝试时点是不早于 `+15s/+30s/+45s`；`+55s` 是请求完成截止，不是最后启动时间。

每个频率的 feed key 固定为：

```text
tushare_etf_rt_min_1min
tushare_etf_rt_min_5min
tushare_etf_rt_min_15min
tushare_etf_rt_min_30min
tushare_etf_rt_min_60min
```

### 3.2 Config 类型

在 `src/foundation/realtime/runtime_config.py` 增加：

```python
@dataclass(frozen=True, slots=True)
class RealtimeEtfRtMinConfig:
    version: int
    enabled: bool
    enabled_freqs: tuple[str, ...]
    poll_interval_seconds: int
    max_calls_per_minute: int
    lease_ttl_seconds: int
    stale_after_seconds: int
    storage: RealtimeFeedStorageConfig
    source_timeout_seconds: int

    def feed_key_for_freq(self, freq: str) -> str: ...
```

`RealtimeRuntimeConfig` 增加第四个对象 `etf_rt_min`。以下消费者必须同时改造，不能留下只认识三个对象的旧契约：

1. `runtime_config_seed_service.py`。
2. runtime config resolver 与 cache。
3. `config_apply_state.py`。
4. Ops config command/query service。
5. collector CLI 装配。
6. 前端配置对象类型和测试 fixture。

缺少 `etf_rt_min` 配置行时启动 fail fast，不回退 env 或代码默认值。

已拍板并可用于 seed 的完整初始配置：

```json
{
  "enabled": false,
  "enabled_freqs": ["1MIN"],
  "poll_interval_seconds": 60,
  "max_calls_per_minute": 20,
  "lease_ttl_seconds": 70,
  "stale_after_seconds": 90,
  "snapshot_ttl_seconds": 259200,
  "keep_recent_batches": 260,
  "batch_stream_maxlen": 5000,
  "delta_stream_maxlen": 200000,
  "source_timeout_seconds": 8
}
```

`poll_interval_seconds` 只表示 unified collector 重新检查 due state 的最大间隔，值域固定为 `1-60`；`seconds_until_next_due()` 必须把闭合槽的 `+15s/+30s/+45s` 墙上时间换算成更早的 monotonic due time，不能真的每 60 秒才检查一次。`stale_after_seconds=90` 沿用现有分钟配置默认值，但 ETF 分钟中解释为“某应发布槽到达 `+55s` 截止后继续超过 90 秒仍无对应 batch”，不是 current batch 年龄。

### 3.3 独立限速器

扩展 `get_realtime_tushare_max_calls_per_minute(api_name, session)`：

```text
api_name=rt_etf_min
  -> config.etf_rt_min.max_calls_per_minute
  -> limiter cache key=rt_etf_min
```

ETF 实时分钟使用自己的配置和 limiter cache key，不复用股票实时分钟的限速桶。`_build_etf_rt_min_config()` 必须调用专用的 `_validate_etf_rt_min_request_budget()`，不能复用当前 `_validate_request_budget(feed_count, poll_interval_seconds, ...)`。专用校验按实际闭合槽模拟交易时段内任意滚动 60 秒窗口，并计入同一分钟到期频率数、每槽最多 3 次尝试和 limiter 最小间隔。五频率共同边界的保守请求上界为 `5 x 3 = 15`，初始上限 `20/min`，最小接口间隔 3 秒；配置低于实际滚动窗口上界时拒绝发布。

### 3.4 配置项审计与关系校验

所有运营可编辑配置只保存在 `foundation.realtime_runtime_config.runtime_config_json`，由 runtime resolver 统一读取，发布后重启 collector 生效：

| 配置项 | 消费者 | 校验与语义 |
| --- | --- | --- |
| `enabled` | collector、Ops health | disabled 时不请求源站，但 apply state 仍上报版本。 |
| `enabled_freqs` | schedule、collector、health、配置中心 | 非空、去重，只允许五个 catalog 频率。 |
| `poll_interval_seconds` | unified collector due 检查 | `1-60`；不是源请求的滑动周期。 |
| `max_calls_per_minute` | `rt_etf_min` limiter、发布校验 | 正整数，且覆盖专用滚动60秒请求预算。 |
| `lease_ttl_seconds` | state store lease | 初始 `70`；从首次尝试前开始，覆盖 `+55s` 完成截止与安全余量。 |
| `stale_after_seconds` | reader、Ops health | 初始 `90`；从该槽 `+55s` 完成截止后计算 grace，不是批次发布年龄阈值。 |
| `snapshot_ttl_seconds` | Redis batch 写入/过期 | 正整数；与保留批次数共同决定实际历史长度。 |
| `keep_recent_batches` | Redis cleanup、series reader | 正整数；对每个物理频率 feed 分别生效。 |
| `batch_stream_maxlen` | batch stream | 正整数。 |
| `delta_stream_maxlen` | delta stream | 正整数。 |
| `source_timeout_seconds` | ETF 分钟专用 Tushare client | 初始 `8`，表示整个 HTTP attempt 的总墙钟上限，不是 read timeout；若 `now + timeout > retry_deadline`，不得启动新请求。 |

以下事实只存在 `config_catalog.py` 或 R0B 冻结的 schedule policy 中，配置 API 只能只读展示，提交时必须拒绝：`source_api_name`、组合通配符、fields、feed key prefix、active resource、collection sessions、频率闭合网格、频率执行顺序、source-ready delay、retry interval、retry deadline。`REDIS_URL` 继续是部署级 env，不进入配置表或配置中心。

配置中心字段元信息必须从 Ops API 返回，前端不自行维护 min/max、频率列表或锁定字段副本。配置发布、runtime resolver、collector 与测试使用同一套关系校验，禁止各写一套。

---

## 4. ETF 实时分钟选择池

### 4.1 Resource 语义

`etf_rt_min` 是 `ops.etf_series_active.resource` 的值。每只运营选择加入的 ETF 对应一行：

```text
(resource=etf_rt_min, ts_code=510300.SH)
```

它不是 Redis key。Redis key 由“ETF 实时分钟 + 频率”生成。由于源站使用全市场通配符，选择池不决定源站请求参数；它决定源端返回中哪些 ETF 参与目标分钟就绪判断、进入 Redis feed 并进入 missing/old-time/health 统计。

### 4.2 候选全集与成员管理

候选全集固定来自：

```text
ops.etf_series_active(resource=etf_rt_daily)
```

`resource=etf_rt_min` 初始为空，不从 `etf_rt_daily` 全量复制，不增加批量复制服务或初始化 CLI。候选全集当前为 1395 只是数据库现状，不得写成固定数量或集合完全相等门禁。

新增专用 `EtfRtMinPoolService`，只负责列表、候选查询、单条添加和单条删除。它直接使用 Ops ORM 管理成员，不扩大 foundation 的写入 contract；foundation 现有 `EtfSeriesActiveStore/DAO` 只负责 collector 读取池内代码。

添加规则：

1. `ts_code` 必须存在于 `resource=etf_rt_daily` 候选全集，只允许 `.SH/.SZ`。
2. 新目标行复制候选行的 `first_seen_date/last_seen_date/last_checked_at`，使用新的 `resource=etf_rt_min` 和目标行 `created_at/updated_at`。
3. 已存在于目标池时返回 `409 conflict`，不得覆盖日期或伪装成新加入。
4. 删除只允许删除 `(resource=etf_rt_min, ts_code)`，不得影响候选全集、其他 resource 或历史 Redis batch。
5. 删除不存在成员返回 `404 not_found`；添加和删除各自在一个数据库事务内提交。

候选全集后续变化时，不自动删除已经加入的 `etf_rt_min` 成员。失去 `etf_rt_daily` 候选资格的成员在选择池列表标记 `candidate_active=false`，仍由运营决定是否删除；collector 在删除前继续按选择池事实处理该代码。

新增 admin-only API：

```http
GET    /api/v1/ops/realtime/etf-rt-min/pool?page=1&page_size=50&keyword=
GET    /api/v1/ops/realtime/etf-rt-min/pool/candidates?page=1&page_size=50&keyword=
POST   /api/v1/ops/realtime/etf-rt-min/pool
DELETE /api/v1/ops/realtime/etf-rt-min/pool/{ts_code}
```

`pool` 返回当前选择池并标注 `candidate_active`；`candidates` 只从当前 `etf_rt_daily` 查询，并返回 `in_pool`。两个列表均关联 `core_serving.etf_basic` 和全局最新 `raw_tushare.etf_share_size`，展示代码、名称、交易所、ETF 类型、上市日期、总份额和总规模。支持代码/名称关键词搜索，每页最多 50 条；两个列表均按总规模降序、空值最后、代码升序。页面只消费 API 排序，不自行重排。

`pool` response wrapper 除 `items/page/page_size/total` 外，还必须由后端返回：

```text
pool_count
enabled_freq_count
keep_recent_batches
estimated_snapshot_count = pool_count x enabled_freq_count x keep_recent_batches
```

前端不得自行读取配置对象后重复计算该事实。`POST` body 只包含 `ts_code`；mutation response 返回 `ts_code` 和当前 `pool_count`。选择池没有 update 语义，成员存在即生效，不增加 `enabled` 或其他可编辑字段。

collector 每轮通过：

```python
dao.etf_series_active.list_active_codes("etf_rt_min")
```

读取代码。池为空时不请求源站、不发布空 batch，health 返回 `idle/source_pool_empty`。

### 4.3 生效与冻结规则

1. 池变更不依赖 realtime runtime config 版本，不需要重启 collector。
2. 每个频率槽第一次执行时读取、排序并冻结 `active_codes`，计算 `active_pool_hash=sha256("\n".join(active_codes))`。
3. 同一槽的后续重试继续使用 retry state 中冻结的 `active_codes/active_pool_hash`，不得重新读取数据库。
4. 槽处理中新增或删除成员只影响下一槽。即使某个阻塞代码刚被删除，当前槽也按冻结集合执行到成功或截止，避免同一批次前后口径变化。
5. 删除成员后不扫描历史 Redis batch；下一次成功发布的 current batch 不再包含它，历史数据由 TTL 和 `keep_recent_batches` 自然清理。
6. collector 进程在槽内重启时，旧内存 retry state 直接失效；新进程等待旧 lease 到期后，为尚未发布的当前合法槽重新读取并冻结最新选择池。旧尝试没有发布事实，因此不会产生一个 batch 混用两份池的问题。

### 4.4 通配符结果与池过滤

每次源端请求得到沪深全市场结果后，按以下顺序处理：

1. 标准化源端 `ts_code` 大小写与空白。
2. 记录 `source_row_count` 和源端 distinct code 数。
3. 与本槽冻结的运营选择池取交集。
4. 池外行不进入 snapshot、不算 invalid，记录 `outside_pool_count`。
5. 池内未返回代码记录为 `missing_ts_codes/missing_count`。
6. Redis snapshot 最多只包含本槽冻结池内代码，不保存额外源端代码。

源站全市场请求本身不会因为选择池缩小而变快；选择池缩小的是发布等待范围和 Redis 写入范围。被排除的慢 ETF 不计 missing、不参与目标分钟覆盖，也不阻塞 current pointer 切换。

---

## 5. Provider 与 Normalizer

### 5.1 内部类型

新增 `src/foundation/realtime/etf_rt_min.py`，至少包含：

```python
@dataclass(frozen=True, slots=True)
class EtfRtMinFetchResult:
    freq: str
    request_params: dict[str, str]
    rows: tuple[dict[str, Any], ...]
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class EtfRtMinNormalizeResult:
    snapshots: tuple[dict[str, Any], ...]
    missing_ts_codes: tuple[str, ...]
    active_pool_count: int
    active_pool_hash: str
    outside_pool_count: int
    invalid_count: int
    invalid_reason_counts: dict[str, int]
```

重复身份不是可继续发布的 normalizer 统计项。新增结构化异常 `EtfRtMinDuplicateIdentityError`，至少携带 `freq` 和重复的 `ts_code` 样本；抛出后本批没有 `EtfRtMinNormalizeResult`。

### 5.2 Provider

`TushareEtfRtMinProvider.fetch_all_market(freq)` 负责：

1. 校验频率属于五个支持值。
2. 固定使用 `ts_code=5*.SH,1*.SZ`，不得把选择池代码拼入请求参数。
3. 调用一次 `rt_etf_min` 并显式传全部 fields。
4. 请求失败时抛出结构化异常，不返回可发布结果。
5. 记录请求参数、源端行数、distinct code 数和耗时。
6. 一次 `fetch_all_market()` 最多调用一次 `client.call()`；源端 K 线未就绪后的再次请求由 schedule 控制，provider 内不得循环重试业务请求。

当前 `TushareHttpClient` 的 HTTP adapter 默认 `total=5/connect=5/read=5/other=3`，最坏耗时可能跨过一分钟槽；其 `(connect_timeout, read_timeout)` 也不是总墙钟超时。为避免改变其他 Tushare 接口，客户端构造函数增加可选 `TushareHttpTransportPolicy`，缺省时保持现状。ETF 分钟 provider 注入：

```python
TushareHttpTransportPolicy(
    total_timeout_seconds=8,
    retry_total=0,
    retry_connect=0,
    retry_read=0,
    retry_other=0,
)
```

客户端 adapter 必须把 `total_timeout_seconds` 转成支持 total deadline 的底层 timeout 对象，不能只设置 read timeout。这样一次 scheduler attempt 只产生一次、总墙钟不超过 8 秒的 HTTP attempt。连接/读失败与“源端尚未形成目标 K 线”都交给分钟 scheduler 在 `+30s/+45s` 决定是否再次尝试，不能和客户端内部自动重试叠加。

### 5.3 Normalizer

normalizer 接收本槽冻结的 `active_codes/active_pool_hash`。它必须先标准化所有非空 `ts_code` 并检查池内重复身份，再过滤池外行和校验池内行：

1. `ts_code` 非空；不在选择池的合法代码只计入 `outside_pool_count`。
2. `freq` 非空且等于本次请求频率。
3. `time` 可解析。
4. `open/close/high/low/vol/amount` 可转换为数值或明确空值。
5. 同一池内 `ts_code` 最多一行；出现重复时整批失败，不允许交给 `RealtimeStateStore` 后写覆盖前写。

合法 snapshot 至少包含：

```text
ts_code
freq
time
open
close
high
low
vol
amount
source=tushare
source_api_name=rt_etf_min
received_at
raw_payload_hash
```

`amount=0` 或 `vol=0` 是源端事实，不自动判 invalid。源端 `time` 早于当前预期槽的单只 ETF 行允许保留，但必须计入 health 的旧时间统计；这类个别旧行不能单独决定整批“未就绪”。源端 `time` 晚于本次 `expected_bar_time` 时，说明当前请求已经跨过目标槽，不得把它发布为目标槽数据。

批次就绪判断必须独立于单行合法性校验。只有本槽冻结选择池中的每个代码都有一行合法且 `time == expected_bar_time`，该批次才完整；任何池内缺失、旧时间、无效行或重复身份都不得发布。选择池外行不参与该判断。

---

## 6. Redis 发布契约

### 6.1 复用现有批次模型

本轮继续复用 `RealtimeStateStore.publish_batch()` 的 Redis key 结构，但必须修正已确认的发布结果与清理错误边界：

| 结构 | 实际作用 |
| --- | --- |
| batch snapshots | 保存这次完整采集得到的 ETF 行。 |
| batch meta | 保存批次时间、频率、预期 K 线时间、选择池数量与 hash、行数、耗时和 invalid 统计。 |
| current pointer | 只保存“当前最新完整批次”的 `batch_id`；读者不会读到写到一半的批次。 |
| batch stream | 追加一条“某批次已发布”事件，供后续增量消费者按顺序读取。 |
| delta stream | 追加相对上一批发生变化的 ETF 行事件。 |
| health | 保存该 feed 的当前运行状态、最近成功/失败和源端时间统计。 |

这里的 `stream` 是 Redis 追加式事件队列，不是另一份完整快照表；`health` 是运行观测信息，不是行情数据。

### 6.2 原子发布

一次频率的组合请求成功、池过滤与校验通过、目标分钟达到就绪条件后，collector 才调用一次 `publish_batch()`：

1. 事务前拒绝重复 `ts_code`，不得由 `_normalize_snapshots()` 静默后写覆盖前写。
2. 同一 Redis transaction 内写本批所有 snapshot、meta，切换 current pointer，并追加 batch/delta stream 事件。
3. 事务成功即代表本批发布成功。
4. 事务完成后按 `keep_recent_batches` 清理旧 batch；清理失败不得推翻已经成功的发布。

batch meta 必须写入 `active_pool_count` 和 `active_pool_hash`。它们记录本批实际冻结的选择范围，供 health、reader 和生产验收追溯；不在 Redis 中复制完整代码清单。

`RealtimePublishResult` 增加可选的 `cleanup_error`。`publish_batch()` 必须把 Redis transaction 和 transaction 后 cleanup 分成两个异常边界。旧批清理失败时：

1. 返回已经成功的 batch/delta event id 和 `cleanup_error`。
2. collector 仍记录本批 `status=ok`。
3. health 增加 `batch_cleanup_status=warning` 和 `batch_cleanup_error`。
4. 后续成功清理时自动清除 warning；清理逻辑根据 batch zset 补删所有超出保留数的旧批。

`release_lease()` 同时改为 Redis Lua compare-and-delete：只有当前 value 等于传入 owner 才删除。现有“GET owner 后再 DELETE”的两条命令存在 TTL 到期后删除新 owner lease 的竞态，不能继续用于跨多次 cycle 持有的 ETF 分钟 lease。

源请求失败、池内重复代码、池内合法 snapshots 为空、批次未就绪或事务本身失败时不发布新 batch、不移动 current pointer；上一完整批次继续可读，本频率 health 标记为 degraded 或等待重试。其他实时 feed 不受影响。

本轮不新增第二套分钟事实 key。最近分钟序列直接从保留的 batch 读取。

### 6.3 Redis 容量门禁

`keep_recent_batches` 对每个物理频率 feed 分别生效：

```text
预计 snapshot 数 = active_pool_count x keep_recent_batches x enabled_freq_count
```

容量按实际选择池动态计算。五频率、260批时，选择池 50/100/200/300 只分别对应 `65000/130000/260000/390000` 个 snapshot；实际保留量同时受 `snapshot_ttl_seconds` 约束，TTL 和批次数哪个先达到就按哪个清理。池配置页展示当前池数量和按当前 runtime config 计算的预计 snapshot 数，不设置拍脑袋硬上限。

R1A 容量基准必须使用隔离 feed prefix，写入与生产完全相同的 snapshot、batch index、meta、batches zset、current pointer、batch stream 和 delta stream。分别记录：

1. 写入前后 Redis `INFO MEMORY.used_memory` 增量。
2. 各类代表 key 的 `MEMORY USAGE`。
3. 单批、单 snapshot、单 delta event 的实测字节数。
4. 按选择池数量、启用频率和 260 批外推的总量。

测试完成后删除隔离 namespace，不得写生产 feed key。R3 在生产 Redis 用受控测试 namespace 再测一次，并与实例可用内存对账。容量门禁未通过时只能保持对象 disabled，或由运营缩小选择池、减少启用频率。

---

## 7. 分钟锚定调度

### 7.1 为什么不能沿用“执行时间 + interval”

现有通用 interval 调度会把每次实际执行耗时累加到下次执行时间，长期可能从整分钟漂移到 `10:01:17`、`10:02:19`。ETF 分钟 K 线必须以交易时钟的闭合槽为基准，不能以进程上次完成时间为基准。

### 7.2 调度模型

在 ETF 实时分钟实现内增加纯计算的槽位类型：

```python
@dataclass(frozen=True, slots=True)
class EtfRtMinDueSlot:
    freq: str
    expected_bar_time: datetime
    request_not_before: datetime
    retry_deadline: datetime


class EtfRtMinSchedule:
    def resolve_due_slot(self, *, freq: str, now: datetime) -> EtfRtMinDueSlot | None: ...


@dataclass(frozen=True, slots=True)
class EtfRtMinRetryState:
    slot: EtfRtMinDueSlot
    attempt_count: int
    next_attempt_at: datetime
    lease_owner: str
    active_codes: tuple[str, ...]
    active_pool_hash: str
```

规则：

1. 先复用 `RealtimeMarketClock` 判断真实交易日和采集窗口；非交易日、盘前、午休和收市后不创建新的 expected slot。交易日上午和下午分别计算，午休不生成槽。已经在 `11:30` 或 `15:00` 创建的闭合槽可继续在各自 `+55s` 截止前请求，不能因为墙上时间进入午休或收市后就丢掉最后一根 K 线。
2. `1MIN` 以每个闭合交易分钟为槽；其他频率只在自身 K 线闭合点生成槽。
3. `request_not_before = expected_bar_time + 15s`，后续尝试分别不早于 `+30s/+45s`。
4. batch identity 固定由 `(feed_key, expected_bar_time)` 生成，不使用实际收到响应的时间生成身份。
5. 调度前读取 current batch meta；已经发布相同或更新 `expected_bar_time` 时不得再次请求或发布旧槽。
6. 请求返回旧时间、空结果或临时错误时，可在 `expected_bar_time + 55s` 完成截止前重试，但本次调用只登记 `EtfRtMinRetryState.next_attempt_at` 后返回。
7. 请求返回晚于 `expected_bar_time` 的新 K 线时，目标槽已经错过，不能拿新 K 线冒充旧槽。
8. 选择池外旧时间 ETF 不影响本批；选择池内任一代码仍未达到目标分钟，则本槽尚未就绪，不得发布残缺批次。
9. 首次创建 retry state 时冻结选择池；后续调用不得因数据库成员变化重建同一槽的 retry state。

锁定策略固定为：`source_ready_delay_seconds=15`、`retry_interval_seconds=15`、`retry_deadline_offset_seconds=55`、`max_attempts_per_slot=3`，频率顺序为 `1MIN,5MIN,15MIN,30MIN,60MIN`。若当前时间加 `source_timeout_seconds=8` 会超过截止时间，本槽直接进入 missed，不再启动请求。

### 7.3 非阻塞执行契约

现有 `RealtimeCollectorService.run_due_cycle()` 串行执行股票日线、股票分钟和 ETF 日线；任何一个 collector 内部 sleep 都会阻塞所有后续 feed。ETF 分钟必须遵守：

1. `EtfRtMinCollector.run_freq_cycle(session, freq, now)` 每次最多执行一次源请求，不在方法内 sleep 或 while retry。
2. 返回结果增加 `next_attempt_at`；状态至少区分 `published`、`waiting_retry`、`missed`、`skipped`、`failed`。
3. `RealtimeCollectorService` 把墙上时间 `next_attempt_at` 换算为 monotonic due time，并纳入 `seconds_until_next_due()`。
4. 同一分钟多个频率到期时，固定按 `1MIN,5MIN,15MIN,30MIN,60MIN` 选择下一个允许请求的频率；一次 unified cycle 最多执行一个 ETF 分钟源请求，其他实时 feed 仍在该 cycle 正常获得运行机会。
5. collector 保存独立的 `rt_etf_min` 下一可请求时间，按 `60 / 20 = 3s` 做非阻塞节流；未到时间只安排下一 due。由于 `rt_etf_min` 是独立 limiter key，正常路径在调用 `client.call()` 前已经满足 3 秒间隔，最终 `_RateLimiter.acquire()` 不应发生 sleep。
6. `_RateLimiter` 仍作为最终进程级保护，但正常路径不得依赖其 sleep 来调度 ETF 分钟请求。
7. 没有 due feed 时最短 sleep 仍有下界，禁止 retry state 导致 busy-spin。

这个契约是 R1B 的核心测试对象。不能把“在槽内可重试”实现成一个阻塞到截止时间的内部循环。

### 7.4 Lease 边界

每个频率、每个槽在第一次源请求前获取该 feed 的 lease，并持有到该槽成功、截止或失败退出。V1 不依赖无限续租，配置校验必须保证：

```text
lease_ttl_seconds
  > 槽内最大重试窗口
  + source_timeout_seconds
  + 固定安全余量
```

初始 `lease_ttl_seconds=70`。retry state 在多次非阻塞调用之间持有同一个 `lease_owner`。首次请求前 acquire，成功、missed 或最终失败后使用原子 compare-and-delete release；进程重启导致内存 retry state 丢失时，不得冒用旧 owner，等待 TTL 释放后再处理当前合法槽。

`70s` 从 `+15s` 首次尝试前开始，覆盖到 `+55s` 完成截止并保留 30 秒余量，因此 V1 不增加 lease 续期。测试必须使用可控时钟证明 lease 在最后一次合法请求完成前不会到期。

### 7.5 晚执行时会不会漏掉 1MIN

锚定调度能处理两类正常延迟：

1. collector 比整分钟晚几秒启动，但源端仍返回目标分钟，正常发布。
2. 源端在整分钟后短暂仍返回上一根，collector 在当前槽内重试，直到目标分钟出现。

它不能凭空追回已经被源端覆盖的旧 K 线。若 collector 停机或请求持续失败，恢复请求时源端已经只返回下一根 K 线，则上一槽无法从 `rt_etf_min` 获取。此时必须：

1. 不发布错误槽位数据。
2. health 记录 `missed_slot_count`、`last_missed_bar_time` 和错误原因。
3. 当前频率状态标记 degraded。
4. 从下一个合法槽继续采集。

因此 R0B 的硬门禁是：一次组合通配符请求、池过滤与发布必须稳定在一分钟槽内完成，并为源端延迟和至少一次重试留出余量。达不到该条件时，不能启用 `1MIN` 生产采集，必须先调整请求预算或重新评估生产可行性。

---

## 8. Unified RealtimeSnapshotReader

### 8.1 目标

扩展现有 `src/foundation/realtime/snapshot_reader.py`，统一封装 config、feed key、Redis batch 和 stale 规则。调用方不得自行拼 `tushare_etf_rt_min_*` Redis key。

### 8.2 最新快照读取

新增：

```python
def read_etf_rt_min_snapshot(
    self,
    session: Session,
    *,
    freq: str,
    ts_codes: Sequence[str],
) -> RealtimeSnapshotReadResult: ...
```

实现复用现有 Redis current/meta/snapshot 读取能力，但不能直接复用 `_read_snapshot()` 当前按批次年龄计算 stale 的逻辑：

1. 读取 `RealtimeEtfRtMinConfig`。
2. 校验并标准化 freq。
3. 解析 feed key。
4. 读取 current pointer、meta 和指定代码的 snapshots。
5. 通过 `EtfRtMinSchedule` 计算“截至当前时刻已经超过 `expected_bar_time + 55s + stale_after_seconds` 的最新应发布槽”。
6. current meta 的 `expected_bar_time` 早于该槽时才是 stale；下一个闭合槽尚未到来，或已到但尚未越过截止与 grace 时，即使批次年龄很大也不是 stale。
7. 当天首个应发布槽尚未到来且无 current batch 时返回等待状态，不报 unavailable；首个应发布槽已经逾期仍无 batch 才返回 unavailable。
8. 汇总 missing codes。

### 8.3 最近分钟序列读取

新增内部结果类型和方法：

```python
@dataclass(frozen=True, slots=True)
class RealtimeSeriesReadResult:
    feed_key: str
    freq: str
    batch_count: int
    items: tuple[dict[str, Any], ...]
    missing_ts_codes: tuple[str, ...]


def read_etf_rt_min_series(
    self,
    session: Session,
    *,
    freq: str,
    ts_codes: Sequence[str],
    batch_limit: int,
) -> RealtimeSeriesReadResult: ...
```

读取规则：

1. `batch_limit` 必须是正整数，且不得超过该 feed 的 `keep_recent_batches`。
2. 通过 `list_batch_ids(feed_key, limit=batch_limit)` 读取最近批次。
3. 每个批次通过 `get_batch_snapshots()` 读取指定代码。
4. 相同 `(ts_code, freq, time)` 只保留发布时间较晚的批次行。
5. 最终按 `ts_code, time` 升序返回。
6. `missing_ts_codes` 只表示“请求代码在本次实际读取的全部批次中都没有任何一行”；某个代码只缺少个别分钟，不得被放入该字段。
7. reader 只返回 realtime 事实和缺失代码，不包含页面展示或业务判断。

本轮不新增外部 HTTP API；reader 是 foundation 内部公共契约。

---

## 9. Collector Service

`RealtimeCollectorService` 增加 `EtfRtMinCollector`，仍由一个进程调度所有实时 feed：

1. 启动时注入 `etf_rt_min` config、provider、active store 和 state store。
2. 每轮按 `EtfRtMinSchedule` 判断各启用频率是否有 due slot。
3. 每个频率使用独立 feed lease、current pointer 和 health。
4. 一个 ETF 分钟频率失败，只影响该频率；其他 ETF 分钟频率、ETF 日线和股票 feed 继续运行。
5. apply state 增加 `etf_rt_min.version`；即使 `enabled=false` 也要上报已应用版本。
6. collector 下一次唤醒时间取所有 feed 下一 due time 的最小值，不能让现有日线 interval 驱动 ETF 分钟请求频率。
7. unified cycle 先保证现有实时 feed 仍获得执行机会，再按非阻塞 due state 最多尝试一个 ETF 分钟频率；ETF 分钟等待 limiter 或源端下一次尝试时不能占住线程。
8. 当前 `_mark_scheduled(now + interval)` 只保留给现有 interval feed；ETF 分钟的 due 由墙上时间闭合槽和 retry state 计算，不能写回滑动 interval。

建议 cycle result 至少包含：

```text
feed_key
freq
status
expected_bar_time
batch_id
source_row_count
active_pool_count
active_pool_hash
outside_pool_count
snapshot_count
missing_count
invalid_count
target_time_count
old_time_count
consecutive_missed_slot_count
missed_slot_count_today
source_elapsed_ms
write_elapsed_ms
last_batch_event_id
last_delta_event_id
error
```

---

## 10. Ops Config、Health 与页面

### 10.1 配置中心

配置中心增加第四个对象 `etf_rt_min`：

1. `enabled_freqs` 使用 `1MIN/5MIN/15MIN/30MIN/60MIN` checkbox group。
2. catalog 字段只读展示。
3. validate/publish/revision/apply-state/restart 闭环复用现有能力。
4. 发布成功后必须重启 collector，页面状态以 applied version 为准。

### 10.2 Health API

新增：

```http
GET /api/v1/ops/realtime/etf-rt-min/health
GET /api/v1/ops/realtime/etf-rt-min/health?freq=1MIN
```

不带 freq 时返回五个频率，未启用频率也返回 `enabled=false`。每个 item 至少包含：

```text
freq
feed_key
status
enabled
collection_status
current_batch_id
expected_bar_time
latest_source_time
active_pool_count
active_pool_hash
source_row_count
outside_pool_count
target_time_count
old_time_count
snapshot_count
missing_count
invalid_count
invalid_reason_counts
consecutive_missed_slot_count
missed_slot_count_today
last_missed_bar_time
request_count_last_minute
api_request_count_last_minute
max_calls_per_minute
source_elapsed_ms
batch_cleanup_status
batch_cleanup_error
last_success_at
last_error_at
error
```

`request_count_last_minute` 是单个频率的调度尝试数；`api_request_count_last_minute` 是五个 ETF 分钟 feed 共用 `rt_etf_min` limiter key 的真实接口请求总数。限速判断必须使用后者，页面可同时展示两者。

状态优先级沿用现有实时 feed 语义：`disabled -> unavailable -> degraded -> stale -> ok -> idle`，但 ETF 分钟的 stale 输入必须来自 schedule-aware overdue slot：`expected_bar_time + 55s + stale_after_seconds` 已经过期且 current meta 仍早于该槽。不能调用当前只比较 `current_batch_age_seconds` 的通用 helper。当前槽错过时 `consecutive_missed_slot_count` 增长并进入 degraded；后续合法槽成功发布后连续遗漏归零、状态可恢复为 ok，但 `missed_slot_count_today` 和 `last_missed_bar_time` 保留到交易日切换。

当日遗漏计数保存在该频率 Redis health 中：写入前读取上一份 health；交易日期相同则累加，日期变化则归零后重新计算。单频率 lease 保证同一槽只有一个写入者。Redis health 不可用时只影响观测，不得阻止已经完成的行情 batch 发布。空池时返回 `status=idle`、`collection_status=source_pool_empty`、`active_pool_count=0`，不请求源站，也不累计 missed slot。

### 10.3 实时流监控页面

现有“实时流监控”页面新增“ETF 实时分钟”区块：

1. 按 API 返回的五频率 items 展示，不在前端推导频率或交易时段。
2. 展示池数量、快照数量、最新源端时间、missed slot、invalid 和最近错误。
3. API 失败只影响 ETF 分钟区块。
4. 按 health wrapper 返回的轮询口径局部刷新，不整页刷新。

### 10.4 ETF 实时分钟池配置页

新增 `/ops/v21/realtime/etf-minute-pool` 页面的原设计需要随选择池重新基线。已退场的旧 `/ops/v21/review/etf` 不再存在，也不得作为后续成员管理入口。

页面结构固定为：当前选择池主表 + “添加 ETF”抽屉。交互沿用当前 Ops 页面已经使用的抽屉列表与行内添加模式：

1. 主表展示池数量、预计 snapshot 数、ETF 基础信息、总份额、总规模、加入时间和删除按钮。
2. 添加抽屉支持每页 50 条、代码/名称关键词搜索，行内点击“添加”；成功后本行立即显示浅绿色禁用态“已添加”，抽屉保持打开，可继续添加其他 ETF。
3. 添加和删除成功后只局部刷新 pool/candidates/health 查询，不整页刷新。
4. 页面只维护成员关系，不增加成员级配置字段。
5. 池成员增删在下一频率槽自动生效；页面不得提示“需要重启 collector”。

---

## 11. 文件级实施清单

| 文件或目录 | 改动 |
| --- | --- |
| `src/foundation/realtime/config_catalog.py` | 增加 `etf_rt_min` catalog。 |
| `src/foundation/realtime/runtime_config.py` | 增加 config、resolver、独立 limiter 映射和 ETF 分钟专用滚动60秒请求预算校验。 |
| `src/foundation/realtime/runtime_config_seed_service.py` | 使用本文冻结的完整默认值 seed 第四个 disabled 实时对象。 |
| `src/foundation/realtime/config_apply_state.py` | 上报第四对象版本。 |
| `src/foundation/realtime/etf_rt_min.py` | provider、normalizer、纯槽位计算、非阻塞 retry state、collector。 |
| `src/foundation/realtime/collector_service.py` | 统一服务调度 ETF 分钟 feed，一次 cycle 最多尝试一个 ETF 分钟请求。 |
| `src/foundation/realtime/snapshot_reader.py` | 增加 ETF 分钟 snapshot/series reader。 |
| `src/foundation/realtime/__init__.py` | 导出新公共类型。 |
| `src/foundation/clients/tushare_client.py` | `rt_etf_min` 独立限速映射；客户端构造支持可选 transport retry policy，其他调用方默认行为不变。 |
| `src/ops/services/etf_rt_min_pool_service.py` | 候选查询、成员列表、单条添加和单条删除；候选固定来自 `etf_rt_daily`。 |
| `src/ops/api/etf_rt_min_pool.py`、`src/ops/schemas/etf_rt_min_pool.py`、`src/ops/api/router.py` | admin-only 选择池 CRUD API 及路由挂载；不提供批量初始化或通用 resource 参数。 |
| `src/ops/services/realtime_config_service.py` | 配置对象、字段元信息和影响 feed。 |
| `src/ops/queries/realtime_feed_health_query_service.py` | ETF 分钟 health 聚合。 |
| `src/ops/api/realtime.py`、Ops schema | health 路由与响应。 |
| `src/cli_parts/realtime_handlers.py` | 构造第四个 provider/collector 并注入统一 `RealtimeCollectorService`；保持单一 CLI 与 systemd 服务。 |
| `src/app/dependencies/realtime.py` | Web 侧继续只构建共享 Redis state store；不在这里启动 collector。 |
| `frontend/src/shared/api/realtime-*.ts` | config/health 类型；新增 ETF 分钟池列表、候选和 mutation 类型。 |
| `frontend/src/pages/ops-realtime-*.tsx` | 配置对象和监控区块。 |
| `frontend/src/pages/ops-etf-rt-min-pool-page.tsx` | 独立选择池页面、候选抽屉和行内添加/删除。 |
| `frontend/src/app/shell.tsx`、`frontend/src/app/router.tsx` | 增加 `/ops/v21/realtime/etf-minute-pool` 菜单和路由。 |
| `src/foundation/realtime/state_store.py` | 拒绝重复 snapshot identity；发布成功后清理失败返回 warning；Redis lease 使用原子 compare-and-delete 释放。 |
| `scripts/deploy-layered-systemd.sh` | 新代码服务重启前执行第四配置对象 seed；选择池不由部署脚本初始化。 |

---

## 12. 测试门禁

### 12.1 Config 与选择池

1. 第四对象缺失时 fail fast。
2. config 完整默认值与本文一致：disabled、仅 `1MIN`、60 秒检查、20/min、70 秒 lease、90 秒 stale grace、8 秒 timeout、TTL 72 小时、保留 260 批、stream 长度 `5000/200000`。
3. `rt_etf_min` 限速配置与股票实时分钟隔离。
4. 选择池初始为空；候选只能来自 `etf_rt_daily`，添加 `.OF`、非候选代码或重复成员分别被拒绝。
5. 添加复制候选 seen 日期；删除只影响 `resource=etf_rt_min`，不得改动 `etf_rt_daily` 或其他 resource。
6. pool/candidates 支持关键词搜索、分页和稳定排序；规模关联不得放大行数。
7. ETF 分钟请求预算按闭合槽滚动60秒计算；用旧通用公式构造的不足配置必须被拒绝。
8. 候选资格后续消失时不自动删除已选成员，pool 返回 `candidate_active=false`，运营仍可正常删除。

### 12.2 Provider 与 normalizer

1. 只请求 `rt_etf_min`，只传 `ts_code/freq/fields`。
2. 每个频率只发一次 `5*.SH,1*.SZ` 组合通配符请求，不读取选择池拼参数。
3. 池外代码不进入 snapshot、不计 invalid；池内缺失代码进入 missing 统计。
4. 池内重复 `ts_code` 直接失败，不允许后写覆盖前写。
5. 缺身份字段、频率不一致、时间非法进入 invalid 统计。
6. 旧时间保留并统计；晚于 expected slot 的行不能发布到旧槽。
7. 源端空结果、过滤后空 snapshots 和池内重复身份都不得调用 `publish_batch()`。
8. provider 一次调用最多执行一个 `client.call()`；源端未就绪不会在 provider 内循环。
9. ETF 分钟 transport retry 为零且总墙钟 timeout 为 8 秒；一次 scheduler attempt 只有一次有界 HTTP attempt，测试必须证明它不是 `(connect, read)` 两段各 8 秒，并且不改变其他 Tushare API 的默认 timeout/retry 行为。
10. 空选择池时不调用 provider，不发布空 batch，返回 `idle/source_pool_empty`。

### 12.3 Schedule 与 collector

1. `1MIN` 以闭合分钟锚定，不受上一轮完成时间漂移。
2. 午休不生成 due slot；下午从独立时段重新开始。
3. 源端短延迟在槽内重试；跨槽后记录 missed，不冒充发布。
4. 同一 expected bar time 只发布一次。
5. 单频率失败不影响其他实时 feed。
6. disabled 时不请求源站，但 apply state 仍上报版本。
7. batch id 由 feed key 与 expected bar time 确定，重启后重复处理同一槽仍被幂等拦截。
8. lease TTL 配置覆盖重试窗口、请求超时与安全余量。
9. 每次 `run_freq_cycle` 最多一次源请求，未就绪返回 `next_attempt_at`，不 sleep、不 while retry。
10. 同一分钟五频率同时到期时按固定顺序分多个 unified cycle 执行；股票日线、股票分钟和 ETF 日线仍能继续运行。
11. limiter 尚未允许请求时只安排下次 due，不调用阻塞式 acquire；无 due 时不 busy-spin。
12. 当前槽失败后 `consecutive_missed_slot_count` 增长；后续成功归零，但当日累计遗漏不丢失。
13. 同一槽首次执行冻结成员集合与 hash；槽内增删不改变后续重试，下一槽才读取新池。
14. 选择池外慢 ETF 不阻塞发布；任一选择池内代码未达到目标分钟时不得发布。
15. 进程重启丢失 retry state 后等待旧 lease，再按最新选择池重新冻结尚未发布的合法槽。
16. `11:30/15:00` 已创建的最后闭合槽允许在午休/收市后继续重试到 `+55s`；不能被 collection window 提前截断。
17. 尝试时点为 `+15s/+30s/+45s`，每频率最多三次；`now + 8s > +55s` 时不再启动请求。
18. 五频率共同边界的滚动60秒请求预算不超过配置的 `20/min`，一次 unified cycle 最多一个 ETF 分钟请求。

### 12.4 Redis 与 reader

1. 各频率 current pointer、batch、stream、health 隔离。
2. 源请求或校验失败时 current pointer 不移动。
3. batch 清理遵守 TTL 和最近260批。
4. 发布事务成功、旧批清理失败时 current pointer 保持新批，返回 cleanup warning 而非发布失败。
5. snapshot reader 返回最新完整批次和 missing codes。
6. series reader 按批次读取、按身份去重、按时间升序返回。
7. reader 不暴露 Redis key 拼装给调用方。
8. series `missing_ts_codes` 只包含所有选中批次均无数据的请求代码。
9. 真实序列化容量测试覆盖单频率260批和五频率上界，不用 Python 对象大小代替 Redis 字节估算。
10. batch meta、health 和 cycle result 的 `active_pool_count/active_pool_hash` 一致，可追溯本批实际选择范围。
11. 删除成员后旧 batch 不被主动扫描删除，下一批不再包含该代码，旧数据按 TTL/保留批次退场。
12. Redis lease 释放必须原子校验 owner；旧 owner 不能删除 TTL 到期后由新 owner 获取的 lease。
13. 容量测试使用隔离 namespace，覆盖 snapshot/index/meta/zset/current pointer/batch stream/delta stream，并以 Redis `MEMORY USAGE/used_memory` 为证据。

### 12.5 Ops 与前端

1. config API 支持第四对象的 list/detail/validate/publish/revision/apply-state。
2. health API 覆盖 disabled/idle/ok/stale/degraded/unavailable。
3. 配置中心渲染五频率多选。
4. 实时流监控展示 ETF 分钟区块，错误与其他区块隔离。
5. 前端不直接读 Redis，不请求 Tushare。
6. health 明确区分单频率尝试数与 `rt_etf_min` 聚合接口请求数。
7. 独立选择池页面支持候选搜索分页、连续行内添加和单条删除，不调用监控池 API。
8. 池增删不提示重启；runtime config 发布仍走既有重启闭环，两种生效语义不得混淆。
9. 页面根据实际池数量和启用频率展示预计 snapshot 数，不硬编码1395或固定池上限。
10. `5MIN/15MIN/30MIN/60MIN` 在下一个闭合槽到来前不会因批次年龄增长而误报 stale；首槽未到时无 batch 也不报 unavailable。

---

## 13. 推进顺序

| 阶段 | 开发内容 | 通过条件 |
| --- | --- | --- |
| R0A，已完成 | 收市静态源接口验证 | 独立 API 名、显式字段、五频率、组合通配符和收市返回规模已有真实记录。 |
| R0B，已完成 | 开市时间事实 | 下午、收盘和早盘边界已验证；等待、重试、截止、timeout、lease 和限速数值已冻结。 |
| R1A，可开发 | 静态能力与容量基准 | config/catalog、选择池、provider、normalizer、reader、Redis 安全边界和隔离容量测试完成；生产配置仍不存在或 disabled。 |
| R1B，可开发 | 调度策略 | 非阻塞 retry、确定性 batch identity、原子 lease、limiter、精确 due 唤醒和完整 seed 默认值完成。 |
| R2 | collector、health 与页面 | 统一 collector 接入、频率异常隔离、配置中心、选择池配置页和实时流监控页完成。 |
| R3 | 部署前初始化与收市验收 | 服务重启前完成 disabled 配置 seed；选择池保持空，由运营页面维护；apply state、空池状态、Redis 容量和休市状态对账。 |
| R4 | 开市验收 | 分钟槽连续性、Redis 批次、reader、health 和页面逐项对账后才允许正式启用。 |

R0B 已经完成，R1A/R1B 可以推进。Redis 容量基准不阻塞本地编码，但 R3 生产容量复核未通过前必须保持 `etf_rt_min.enabled=false`；不能靠放宽池覆盖校验、缩短 TTL 或隐藏 stream 占用绕过门禁。

### 13.1 生产初始化顺序

由于 `load_realtime_runtime_config()` 会对缺失对象 fail fast，发布顺序必须固定为：

1. 安装包含第四对象代码的新版本，但暂不重启 Web 与 collector。
2. 执行 realtime runtime config seed，创建 `enabled=false` 的 `etf_rt_min` 配置行。
3. 保持 `resource=etf_rt_min` 选择池为空，重启 Web 与 `goldenshare-realtime-collector.service`，核对 apply state 和 `idle/source_pool_empty`。
4. 运营通过“ETF 实时分钟池配置”页面逐只添加目标 ETF，核对选择池数量和预计 Redis snapshot 数。
5. 收市验收通过后仍保持 disabled；只有 R4 开市验收窗口才由运营发布 enabled 配置并重启 collector。

`scripts/deploy-layered-systemd.sh` 必须在服务重启前完成第2步，且失败立即退出。选择池成员不写入部署脚本，不允许固定数量批量初始化或使用 CSV seed。不得依赖“先让服务启动失败，再人工补配置”的操作顺序，也不得加入旧三对象 fallback。
