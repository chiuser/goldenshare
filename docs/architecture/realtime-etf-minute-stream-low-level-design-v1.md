# ETF 实时分钟流接入 LLD v1

状态：设计已按当前拍板口径收口，尚未编码。

创建日期：2026-08-24
最近更新：2026-08-26

上位方案：[ETF 实时分钟流接入方案 v1](/Users/congming/github/goldenshare/docs/architecture/realtime-etf-minute-stream-plan-v1.md)

---

## 1. 开发目标与边界

本需求把 Tushare `rt_etf_min` 接入现有 realtime 主链，形成独立的 ETF 实时分钟 feed：

```text
runtime config
  -> ETF 实时代码池
  -> rt_etf_min provider
  -> unified realtime collector
  -> Redis batch / current pointer / stream / health
  -> RealtimeSnapshotReader
  -> Ops 配置中心与实时流监控
```

代码范围：

1. `src/foundation/realtime/**`：配置目录、运行时配置、provider、normalizer、collector、reader。
2. `src/ops/**`：配置管理、health 查询与 API。
3. `src/app/**`：依赖装配和路由挂载。
4. `frontend/**`：实时流配置中心和实时流监控页面。
5. `src/ops/services/etf_series_active_seed_service.py`：增加 `etf_rt_min` 代码池初始化能力。

架构边界：

1. `foundation` 通过现有 `EtfSeriesActiveStore` 读取代码池，不 import Ops ORM。
2. 继续复用唯一的 `goldenshare-realtime-collector.service`，不新增 systemd 服务。
3. 不新增 `DatasetDefinition`、TaskRun、业务表、ORM 或 Alembic 迁移。
4. Redis 存储直接复用现有 `RealtimeStateStore` 批次模型。
5. 不新增外部业务 HTTP API；本轮新增 foundation 统一 reader，供后续调用方复用。

---

## 2. 已确认的源接口契约

### 2.1 固定 API 与参数

provider 只调用：

```python
client.query(
    "rt_etf_min",
    ts_code=",".join(ts_codes),
    freq=freq,
    fields="ts_code,freq,time,open,close,high,low,vol,amount",
)
```

工程请求不得增加 `topic` 或其他未在 0416 文档中定义的参数。

当前实测事实：

1. `rt_etf_min` 接口名可直接请求。
2. 沪深 ETF 均可使用 `ts_code + freq` 请求。
3. 返回身份字段为 `ts_code/freq/time`。
4. 支持 `1MIN/5MIN/15MIN/30MIN/60MIN`。
5. 每个代码返回当前最新一根对应频率 K 线，不返回全天序列。

### 2.2 R0 必须补齐的容量事实

源文档写明单次最多返回 1000 行，但这不等于可以直接把 1000 个代码当作安全分片。编码前必须在开市时完成以下验证并回填本文：

1. 单次请求可稳定承载的 ETF 代码数。
2. 1395 个代码需要的分片数。
3. 每个分片的响应耗时和完整返回率。
4. 一轮全部分片能否在下一分钟出现前完成。
5. K 线闭合后，源端通常延迟多少秒可读。

上述事实未冻结前，不允许把分片数、源端等待秒数或重试次数写成拍脑袋常量。

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

已拍板的初始配置：

```json
{
  "enabled": false,
  "enabled_freqs": ["1MIN"],
  "poll_interval_seconds": 60,
  "snapshot_ttl_seconds": 259200,
  "keep_recent_batches": 260
}
```

其余必填数值必须在 R0 依据真实分片数、耗时和重试预算确定，再写入 seed 默认值和配置关系校验。

### 3.3 独立限速器

扩展 `get_realtime_tushare_max_calls_per_minute(api_name, session)`：

```text
api_name=rt_etf_min
  -> config.etf_rt_min.max_calls_per_minute
  -> limiter cache key=rt_etf_min
```

ETF 实时分钟使用自己的配置和 limiter cache key，不复用股票实时分钟的限速桶。配置发布校验必须根据“分片数 x 启用频率数 x 槽内最大尝试次数”计算峰值请求量；限额覆盖不了请求预算时拒绝发布。

---

## 4. ETF 实时代码池

### 4.1 Resource 语义

`etf_rt_min` 是 `ops.etf_series_active.resource` 的值。每只 ETF 对应一行：

```text
(resource=etf_rt_min, ts_code=510300.SH)
```

它不是 Redis key。Redis key 由“ETF 实时分钟 + 频率”生成，代码池只决定 provider 请求哪些 ETF。

### 4.2 初始化规则

`EtfSeriesActiveSeedService` 增加 `etf_rt_min` resource，初始化来源继续使用已经验收的 1395 ETF seed CSV：

```text
reports/etf_series_active_seed_1395_20260617.csv
```

初始化必须验证：

1. 总行数和 distinct `ts_code` 都是 1395。
2. 代码集合与现有 1395 ETF 基线完全一致。
3. 只允许 `.SH/.SZ`，禁止 `.OF`。
4. 默认 dry-run，`--apply` 才写入。
5. 重复执行只跳过已有行，不改 seen 日期。

collector 每轮通过：

```python
dao.etf_series_active.list_active_codes("etf_rt_min")
```

读取代码。池为空时不请求源站、不发布空 batch，health 返回 `unavailable/source_pool_empty`。

---

## 5. Provider 与 Normalizer

### 5.1 内部类型

新增 `src/foundation/realtime/etf_rt_min.py`，至少包含：

```python
@dataclass(frozen=True, slots=True)
class EtfRtMinFetchChunkResult:
    freq: str
    requested_codes: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class EtfRtMinNormalizeResult:
    snapshots: tuple[dict[str, Any], ...]
    missing_ts_codes: tuple[str, ...]
    invalid_count: int
    invalid_reason_counts: dict[str, int]
```

### 5.2 Provider

`TushareEtfRtMinProvider.fetch_codes(freq, ts_codes)` 负责：

1. 校验频率属于五个支持值。
2. 使用 R0 冻结的安全代码数分片。
3. 每个分片调用 `rt_etf_min` 并显式传 fields。
4. 任一分片请求失败时抛出结构化异常，不返回半批成功结果。
5. 记录每个分片的请求代码数、返回行数和耗时。

### 5.3 Normalizer

每行校验：

1. `ts_code` 非空且属于本次请求集合。
2. `freq` 非空且等于本次请求频率。
3. `time` 可解析。
4. `open/close/high/low/vol/amount` 可转换为数值或明确空值。

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

`amount=0` 或 `vol=0` 是源端事实，不自动判 invalid。源端 `time` 早于当前预期槽的行允许保留，但必须计入 health 的旧时间统计；源端 `time` 晚于本次 `expected_bar_time` 时，说明当前请求已经跨过目标槽，不得把它发布为目标槽数据。

---

## 6. Redis 发布契约

### 6.1 复用现有批次模型

本轮直接复用 `RealtimeStateStore.publish_batch()`，不修改 Redis key 结构：

| 结构 | 实际作用 |
| --- | --- |
| batch snapshots | 保存这次完整采集得到的 ETF 行。 |
| batch meta | 保存批次时间、频率、预期 K 线时间、行数、耗时和 invalid 统计。 |
| current pointer | 只保存“当前最新完整批次”的 `batch_id`；读者不会读到写到一半的批次。 |
| batch stream | 追加一条“某批次已发布”事件，供后续增量消费者按顺序读取。 |
| delta stream | 追加相对上一批发生变化的 ETF 行事件。 |
| health | 保存该 feed 的当前运行状态、最近成功/失败和源端时间统计。 |

这里的 `stream` 是 Redis 追加式事件队列，不是另一份完整快照表；`health` 是运行观测信息，不是行情数据。

### 6.2 原子发布

一次频率采集的所有分片都成功后，collector 才调用一次 `publish_batch()`：

1. 先写本批所有 snapshot 和 meta。
2. 再切换 current pointer。
3. 同一 Redis transaction 内追加 batch/delta stream 事件。
4. 按 `keep_recent_batches` 清理旧 batch。

任一分片失败时不发布新 batch、不移动 current pointer；上一完整批次继续可读，本频率 health 标记为 degraded。其他实时 feed 不受影响。

本轮不新增第二套分钟事实 key。最近分钟序列直接从保留的 batch 读取。

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
```

规则：

1. 交易日上午和下午分别计算，午休不生成槽。
2. `1MIN` 以每个闭合交易分钟为槽；其他频率只在自身 K 线闭合点生成槽。
3. `request_not_before = expected_bar_time + source_ready_delay`。
4. 同一 `(feed_key, expected_bar_time)` 只允许成功发布一次。
5. 请求返回旧时间、空结果或临时错误时，可在本槽截止前重试。
6. 请求返回晚于 `expected_bar_time` 的新 K 线时，目标槽已经错过，不能拿新 K 线冒充旧槽。

`source_ready_delay`、重试间隔和截止时间必须由 R0 实测冻结。

### 7.3 晚执行时会不会漏掉 1MIN

锚定调度能处理两类正常延迟：

1. collector 比整分钟晚几秒启动，但源端仍返回目标分钟，正常发布。
2. 源端在整分钟后短暂仍返回上一根，collector 在当前槽内重试，直到目标分钟出现。

它不能凭空追回已经被源端覆盖的旧 K 线。若 collector 停机、请求持续失败或整轮分片耗时超过一个完整分钟，恢复请求时源端已经只返回下一根 K 线，则上一槽无法从 `rt_etf_min` 获取。此时必须：

1. 不发布错误槽位数据。
2. health 记录 `missed_slot_count`、`last_missed_bar_time` 和错误原因。
3. 当前频率状态标记 degraded。
4. 从下一个合法槽继续采集。

因此 R0 的硬门禁是：1395 代码的一轮全部分片必须稳定在一分钟窗口内完成，并为源端延迟和一次重试留出余量。达不到该条件时，不能启用 `1MIN` 生产采集，必须先调整安全分片或请求预算。

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

实现复用现有 `_read_snapshot()`：

1. 读取 `RealtimeEtfRtMinConfig`。
2. 校验并标准化 freq。
3. 解析 feed key。
4. 读取 current pointer、meta 和指定代码的 snapshots。
5. 计算 stale、collection status 和 missing codes。

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
6. reader 只返回 realtime 事实和缺失代码，不包含页面展示或业务判断。

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

建议 cycle result 至少包含：

```text
feed_key
freq
status
expected_bar_time
batch_id
source_row_count
snapshot_count
missing_count
invalid_count
missed_slot_count
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
source_pool_count
source_row_count
snapshot_count
missing_count
invalid_count
invalid_reason_counts
missed_slot_count
last_missed_bar_time
request_count_last_minute
max_calls_per_minute
source_elapsed_ms
last_success_at
last_error_at
error
```

状态优先级沿用现有实时 feed 语义：`disabled -> unavailable -> degraded -> stale -> ok -> idle`，但 `missed_slot_count` 增长时必须进入 degraded，不能只显示 stale。

### 10.3 实时流监控页面

现有“实时流监控”页面新增“ETF 实时分钟”区块：

1. 按 API 返回的五频率 items 展示，不在前端推导频率或交易时段。
2. 展示池数量、快照数量、最新源端时间、missed slot、invalid 和最近错误。
3. API 失败只影响 ETF 分钟区块。
4. 按 health wrapper 返回的轮询口径局部刷新，不整页刷新。

---

## 11. 文件级实施清单

| 文件或目录 | 改动 |
| --- | --- |
| `src/foundation/realtime/config_catalog.py` | 增加 `etf_rt_min` catalog。 |
| `src/foundation/realtime/runtime_config.py` | 增加 config、校验、resolver、limiter 映射。 |
| `src/foundation/realtime/runtime_config_seed_service.py` | seed 第四个实时对象。 |
| `src/foundation/realtime/config_apply_state.py` | 上报第四对象版本。 |
| `src/foundation/realtime/etf_rt_min.py` | provider、normalizer、schedule、collector。 |
| `src/foundation/realtime/collector_service.py` | 统一服务调度 ETF 分钟 feed。 |
| `src/foundation/realtime/snapshot_reader.py` | 增加 ETF 分钟 snapshot/series reader。 |
| `src/foundation/realtime/__init__.py` | 导出新公共类型。 |
| `src/foundation/clients/tushare_client.py` | `rt_etf_min` 独立限速映射。 |
| `src/ops/services/etf_series_active_seed_service.py` | 增加 1395 行 `etf_rt_min` resource。 |
| `src/ops/services/realtime_config_service.py` | 配置对象、字段元信息和影响 feed。 |
| `src/ops/queries/realtime_feed_health_query_service.py` | ETF 分钟 health 聚合。 |
| `src/ops/api/realtime.py`、Ops schema | health 路由与响应。 |
| `src/app/dependencies/realtime.py`、collector CLI | provider/collector/reader 装配。 |
| `frontend/src/shared/api/realtime-*.ts` | config/health 类型。 |
| `frontend/src/pages/ops-realtime-*.tsx` | 配置对象和监控区块。 |

`src/foundation/realtime/state_store.py` 只复用现有接口；如实现阶段未发现现有方法缺陷，本轮不修改。

---

## 12. 测试门禁

### 12.1 Config 与代码池

1. 第四对象缺失时 fail fast。
2. config 默认 disabled、默认仅 `1MIN`、60 秒、TTL 72 小时、保留 260 批。
3. `rt_etf_min` 限速配置与股票实时分钟隔离。
4. seed dry-run/apply 恰好处理 1395 个代码，集合与基线一致。

### 12.2 Provider 与 normalizer

1. 只请求 `rt_etf_min`，只传 `ts_code/freq/fields`。
2. 分片覆盖全部代码，不能漏码、重码。
3. 任一分片失败时不返回可发布的半批结果。
4. 缺身份字段、频率不一致、时间非法进入 invalid 统计。
5. 旧时间保留并统计；晚于 expected slot 的行不能发布到旧槽。

### 12.3 Schedule 与 collector

1. `1MIN` 以闭合分钟锚定，不受上一轮完成时间漂移。
2. 午休不生成 due slot；下午从独立时段重新开始。
3. 源端短延迟在槽内重试；跨槽后记录 missed，不冒充发布。
4. 同一 expected bar time 只发布一次。
5. 单频率失败不影响其他实时 feed。
6. disabled 时不请求源站，但 apply state 仍上报版本。

### 12.4 Redis 与 reader

1. 各频率 current pointer、batch、stream、health 隔离。
2. 任一分片失败时 current pointer 不移动。
3. batch 清理遵守 TTL 和最近 260 批。
4. snapshot reader 返回最新完整批次和 missing codes。
5. series reader 按批次读取、按身份去重、按时间升序返回。
6. reader 不暴露 Redis key 拼装给调用方。

### 12.5 Ops 与前端

1. config API 支持第四对象的 list/detail/validate/publish/revision/apply-state。
2. health API 覆盖 disabled/idle/ok/stale/degraded/unavailable。
3. 配置中心渲染五频率多选。
4. 实时流监控展示 ETF 分钟区块，错误与其他区块隔离。
5. 前端不直接读 Redis，不请求 Tushare。

---

## 13. 推进顺序

| 阶段 | 开发内容 | 通过条件 |
| --- | --- | --- |
| R0 | 开市容量与闭合槽验证 | 安全分片、源端延迟、整轮耗时、重试预算和限速值有真实记录。 |
| R1 | config、catalog、1395 代码池、provider、normalizer、reader | 单元测试和架构护栏通过，不启用生产采集。 |
| R2 | schedule、collector、Redis、health、配置中心、监控页 | 定向后端/前端测试通过，文档与代码一致。 |
| R3 | 部署与开市验收 | 配置 applied，分钟槽连续，reader/health/页面与 Redis 批次一致。 |

R0 发现一轮 1395 ETF 无法在一分钟内稳定完成时，必须停止进入 R1，先重新评估接口容量和生产可行性，不能靠放宽校验掩盖漏分钟风险。
