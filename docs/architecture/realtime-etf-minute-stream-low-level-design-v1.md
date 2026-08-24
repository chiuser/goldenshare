# ETF 实时分钟流接入 LLD v1

状态：设计已按实测源端事实更新，尚未编码。本文是 ETF 实时分钟流的编码依据；不复用旧成交额监控归档代码，也不代表任何目标表、provider 或 collector 已存在。

创建日期：2026-08-24
最近更新：2026-08-24

上位方案：[ETF 实时分钟流接入方案 v1](/Users/congming/github/goldenshare/docs/architecture/realtime-etf-minute-stream-plan-v1.md)
源端事实：[Tushare 0416 ETF 实时分钟](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0416_ETF实时分钟.md)
历史补数事实：[Tushare 0387 ETF 历史分钟行情](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0387_ETF历史分钟行情.md)

---

## 1. 实施约束和已冻结事实

1. 新实现位于 `src/foundation/realtime/**`、`src/foundation/dao/**`、`src/foundation/models/**`、`src/ops/**`、`src/app/**` 与 `frontend/**`；不得进入 `src/platform/**` 或 `src/operations/**`。
2. `foundation` 只能经 `EtfSeriesActiveStore` 读取 `ops.etf_series_active(resource='etf_rt_min')`，不得 import Ops ORM，也不得读 `ops.etf_realtime_monitor_pool`、规则、告警或 Feishu 配置。
3. `rt_min` provider 只传 `ts_code`、`freq` 和显式字段。`topic`、`HQ_FND_TICK` 不是 0416 文档支持的参数，禁止出现在 request builder、配置、测试或回退分支中。
4. `rt_min` 当前每个 ETF/频率响应只给最新一根；`1MIN` 是已闭合分钟事实。实时 source 只写 Redis final-fact state，不能从 collector 直接提交 PostgreSQL。
5. 新的 PostgreSQL 表只保存 ETF 分钟源的 `1MIN` 事实，部署到已确认的 HDD tablespace。它不能命名或放入 `ops.etf_realtime_minute_stat`，也不承接累计差额、监控规则或告警职责。
6. 所有 configuration、health、state 失败不得回滚已经发布的 Redis batch，更不得影响任何业务数据事务。
7. 本 LLD 不改 ETF 成交额监控。监控后续只能读取本 LLD 的 Redis/Persistent minute fact contract。

### 1.1 当前代码中不能复用的旧归档

`src/ops/services/etf_realtime_minute_archive_service.py` 当前：

```text
读取 ops.etf_realtime_monitor_pool
调用 build_etf_minute_metrics_for_trade_date
写 ops.etf_realtime_minute_stat
把 rt_etf_k 累计值差额解释为分钟量
```

它的输入、对象范围和量值语义均与 `rt_min` 闭合分钟不同。因此 ETF 分钟流实现不得 import、调用、改造或间接触发它；长期该旧监控链路如何退场，由成交额监控需求另行处理。

---

## 2. 目标职责与数据流

```text
EtfSeriesActiveStore(resource=etf_rt_min)
  -> TushareEtfRtMinProvider(api=rt_min)
  -> EtfRtMinCollector（按 source freq）
  -> RealtimeStateStore
       - per-frequency current batch / health
       - ETF 1MIN final facts
  -> EtfRealtimeMinuteArchiveService（独立收盘任务）
  -> foundation.etf_realtime_minute_bar_1m（HDD）
  -> EtfRealtimeMinuteHistoryRepairService(api=etf_mins)
  -> 1MIN-derived period query / future consumers
```

`EtfRtMinCollector` 和 archive/repair 是分钟流内部的两个独立服务：collector 发布实时源事实，archive/repair 读取这些事实并持久化。它们与 ETF 成交额监控不构成调用链。

---

## 3. runtime config、catalog 与 source 活跃池

### 3.1 新增对象

在 `src/foundation/realtime/config_catalog.py` 增加：

```python
ETF_RT_MIN_OBJECT_KEY = "etf_rt_min"
ETF_RT_MIN_DISPLAY_NAME = "ETF 实时分钟"
ETF_RT_MIN_SUPPORTED_FREQS = ("1MIN", "5MIN", "15MIN", "30MIN", "60MIN")
ETF_RT_MIN_FEED_KEY_PREFIX = "tushare_etf_rt_min"
```

catalog 锁定事实：

```python
RealtimeConfigCatalogEntry(
    object_key="etf_rt_min",
    object_kind="feed_group",
    display_name="ETF 实时分钟",
    source_api_name="rt_min",
    exchange="SSE",  # 只服务交易日历，不用于过滤 ETF 市场
    collection_sessions="09:30-11:30,13:00-15:00",
    ts_code_pattern="ops.etf_series_active(resource=etf_rt_min)",
    feed_key_prefix="tushare_etf_rt_min",
)
```

不得增加 `topic_policy`、代码通配符或任何源端未声明参数。

### 3.2 config 类型

在 `src/foundation/realtime/runtime_config.py` 新增：

```python
@dataclass(frozen=True, slots=True)
class RealtimeEtfRtMinConfig:
    version: int
    display_name: str
    source_api_name: str
    enabled: bool
    enabled_freqs: tuple[str, ...]
    poll_interval_seconds: int
    collection_sessions: str
    max_calls_per_minute: int
    lease_ttl_seconds: int
    stale_after_seconds: int
    storage: RealtimeFeedStorageConfig
    source_timeout_seconds: int

    def feed_key_for_freq(self, freq: str) -> str: ...
```

`RealtimeRuntimeConfig`、load/build helper、seed service、apply state、config service 和所有测试 fixture 必须同步增加 `etf_rt_min`；缺该行时 fail-fast，不回退 env/default。

初始数据库配置模板：

```text
enabled=false
enabled_freqs=[1MIN]
poll_interval_seconds=60
keep_recent_batches=260
snapshot_ttl_seconds=259200
```

`storage.keep_recent_batches` 仍是整个 `etf_rt_min` 对象的单个值，发布到每个独立 feed。V1 不新增 per-frequency storage JSON。其他频率默认未启用，不产生 Redis 留存。`1MIN` 启用时，`poll_interval_seconds` 必须不大于 60，且 due-time 算法必须以交易分钟结束为锚点，不能因 collector 进程启动时刻而漂移。

### 3.3 source 活跃池

扩展 `src/ops/services/etf_series_active_seed_service.py` 的 resource 白名单，允许：

```text
fund_daily
etf_rt_daily
etf_rt_min
```

ETF 分钟 collector 只能调用：

```python
dao.etf_series_active.list_active_codes("etf_rt_min")
```

seed `etf_rt_min` 时独立写入、独立校验；不得由监控页面、监控池或实时配置中心隐式创建、删改或裁剪。

---

## 4. Provider、normalizer 与实时 collector

### 4.1 provider

新文件：`src/foundation/realtime/etf_rt_min.py`。

```python
class TushareEtfRtMinProvider:
    def fetch_codes(
        self,
        *,
        freq: str,
        ts_codes: Sequence[str],
    ) -> EtfRtMinFetchChunkResult: ...
```

调用 Tushare 时固定：

```python
client.query(
    "rt_min",
    ts_code=",".join(ts_codes),
    freq=freq,
    fields="ts_code,freq,time,open,close,high,low,vol,amount",
)
```

实施前以真实 source 活跃池样本测出 `validated_codes_per_request`，再写入受控 catalog/validation 逻辑；不得把文档的“最多 1000 行”误当成生产单次代码上限。

`TushareHttpClient` 的限速接入须先验证 ETF/股票分钟是否共用 source API 限速桶。若都走 `rt_min`，新增一个明确的共享 limiter resolver；不得让两个独立 config 各自放行后合计突破 token 限额。

### 4.2 normalizer

```python
@dataclass(frozen=True, slots=True)
class EtfRtMinNormalizeResult:
    snapshots: list[dict[str, Any]]
    final_facts: list[EtfRealtimeMinuteFinalFact]
    missing_ts_codes: tuple[str, ...]
    invalid_count: int
    invalid_reason_counts: dict[str, int]
```

每一行校验：

```text
required: ts_code, freq, time, amount
freq: 必须等于本次请求频率
time: 必须可解析为中国交易日 minute end time
```

缺字段、频率不符或不可解析时间记为 `invalid`；`amount=0`、无成交、非活跃下游监控 ETF、旧时间行不自动拒绝。`1MIN` 正常行记为 `quality=valid` final fact；其他 source frequency 在 V1 仅保留 feed snapshot/health，不进入持久化 minute bar。

### 4.3 collector 顺序

`EtfRtMinCollector.run_frequency(session, *, freq, due_at)` 的顺序固定：

1. 判断交易日与时段；非采集时段只写 idle/market_closed health，不请求源站。
2. 获取该 `feed_key` lease；失败返回 skipped，不影响其他 feed。
3. 读取 `EtfSeriesActiveStore.list_active_codes("etf_rt_min")`；空池写 `pool_empty` health，不发布空 batch。
4. 用已冻结分片上限顺序拉取所有分片；任一分片失败，整 frequency 不 publish。
5. normalize 后，只有全分片成功才 `publish_batch` 并原子切换本 feed 的 current pointer。
6. `freq == "1MIN"` 时，publish 成功后将 valid/missing/invalid 记录写入 type-safe final fact store。状态写失败只降级该 frequency health，不回滚已发布 Redis batch。
7. 汇总 health；每个频率单独 error isolation。

`src/foundation/realtime/collector_service.py` 只在既有 `goldenshare-realtime-collector.service` 中调度该 collector；不得增加 systemd service，更不得在本调用链启动 archive、repair、监控计算或 Feishu。

---

## 5. Redis 分钟事实 contract

在 `src/foundation/realtime/state_store.py` 的 `RealtimeStateStore` 增加 ETF 专用类型化方法；禁止由 Ops 拼 Redis key：

```python
record_etf_rt_min_final_facts(...)
list_etf_rt_min_final_facts(...)
upsert_etf_rt_min_fact_quality(...)
```

建议实体：

```python
@dataclass(frozen=True, slots=True)
class EtfRealtimeMinuteFinalFact:
    trade_date: date
    minute_end_time: time
    ts_code: str
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    vol: Decimal | None
    amount_yuan: Decimal | None
    source_time: datetime | None
    source_batch_id: str
    captured_at: datetime
    quality: Literal["valid", "missing", "invalid"]
    reason_code: str | None
```

键为 `(trade_date, minute_end_time, ts_code)`。写入优先级为：

```text
valid -> valid：允许同键幂等更新到更晚捕获的有效 source 事实
valid <- missing/invalid：禁止覆盖
missing/invalid -> valid：允许修复为 valid
missing/invalid -> missing/invalid：保留最新 reason/captured_at
```

final-fact key 的 TTL 是独立 retention，必须覆盖收盘归档与失败重试；它不等于、也不得用 `keep_recent_batches` 推导。

---

## 6. PostgreSQL HDD 分钟归档

### 6.1 新表

新迁移创建：

```sql
foundation.etf_realtime_minute_bar_1m
```

该表是当前分钟源的唯一长期 `1MIN` 事实表。建议以 `trade_date` 做月分区，父表和每个 child partition 都部署到已经由运维预置并确认的 PostgreSQL HDD tablespace；迁移不得硬编码主机路径或悄悄回退默认 tablespace。

最小字段：

| 字段 | 约束/含义 |
| --- | --- |
| `trade_date` | `date not null`，主键组成 |
| `minute_end_time` | `time not null`，主键组成；保存源端 minute 标签 |
| `ts_code` | `varchar(16) not null`，主键组成 |
| `open/high/low/close` | `numeric`，`missing/invalid` 可空 |
| `vol` | `numeric`，单位沿用源端股数 |
| `amount_yuan` | `numeric`，单位固定为元 |
| `source_api_name` | `varchar not null`，`rt_min` 或 `etf_mins` |
| `source_time` | `timestamptz null`，valid 行保存原始时间归一化结果；missing/invalid 可为空 |
| `source_batch_id` | `varchar null`，实时源批次可追溯；历史补数可空 |
| `captured_at` | `timestamptz not null` |
| `quality` | `valid/missing/invalid`，not null |
| `reason_code` | `varchar null` |
| `created_at/updated_at` | 审计时间 |

主键固定为 `(trade_date, minute_end_time, ts_code)`；额外索引：

```text
(ts_code, trade_date, minute_end_time)
(trade_date, quality)
```

不得存入 derived 5/15/30/60/90/120 分钟行，也不得增加累计量、差额量、监控规则或告警列。

### 6.2 archive service

新 foundation service：`src/foundation/realtime/etf_realtime_minute_archive.py`。

```python
class EtfRealtimeMinuteArchiveService:
    def archive_trade_date(
        self,
        session: Session,
        *,
        trade_date: date,
    ) -> EtfRealtimeMinuteArchiveReport: ...
```

行为：

1. 读取 `etf_rt_min` source 活跃池和 Redis final facts。
2. 用实际 `trade_date` 与 session minute grid 生成期望键。`09:30` 为独立键；上午 `09:31-11:30`、下午 `13:01-15:00`；绝不生成午休键。
3. 每个预期键写入一条 valid/missing/invalid 最终记录；不得使用 `date.min/time.min`。
4. 对冲突键幂等 upsert，且遵守第 5 节的 quality 优先级。
5. archive 事务只覆盖这张 minute fact 表；Ops 健康写入失败不回滚 minute 事实事务。

archive 由独立的收盘调度/受控 CLI 触发，不能由 collector 的循环、实时流监控页或 ETF 成交额监控触发。

---

## 7. 历史缺口修复与派生周期

### 7.1 历史修复 service

新 foundation service：`src/foundation/realtime/etf_realtime_minute_history_repair.py`。

```python
class EtfRealtimeMinuteHistoryRepairService:
    def repair_missing_ranges(
        self,
        session: Session,
        *,
        trade_date: date,
        ts_codes: Sequence[str] | None = None,
    ) -> EtfRealtimeMinuteRepairReport: ...
```

执行边界：

1. 只选择 `foundation.etf_realtime_minute_bar_1m` 中真实 `missing` 的 key，并按单 ETF 合并连续分钟区间。
2. 调用当前实际接口 `etf_mins(ts_code, freq="1min", start_date, end_date)`；按 source 返回倒序排序后归一化。
3. 仅修复已成为历史交易日、且 source 实测可用的缺口。当日请求空数组时保留 `missing`，记录 source unavailable，不补零。
4. 不覆盖 `quality=valid`，不修改 source 活跃池，不调用任何监控/告警服务。

本地 0387 文档 API 名与 MCP 实测不一致，实施前必须完成该 source 文档更正和一次当前 SDK/HTTP 实测；不得把 `stk_mins` 当成代码常量。

### 7.2 派生周期

新 query/aggregate helper 只读 `foundation.etf_realtime_minute_bar_1m` 中 `quality=valid` 的 `1MIN`：

```python
build_etf_realtime_minute_periods(
    *, trade_date: date, ts_code: str, window_minutes: int
) -> list[EtfRealtimeDerivedMinuteBar]
```

允许的 `window_minutes`：`5, 15, 30, 60, 90, 120`。

桶规则固定：

```text
09:30：独立开盘 1MIN，不进入常规派生桶
上午常规连续段：09:31-11:30
下午常规连续段：13:01-15:00
每个会话分别从连续段第一分钟按 N 切桶，午休不跨窗
```

每个派生桶必须有 N 根 `valid` 的 1MIN；否则返回 `missing/incomplete`，不产生金额或 OHLC。金额是 1MIN `amount_yuan` 求和，故不依赖源端 5MIN 的逐元舍入结果。

---

## 8. Ops API、配置中心和页面

### 8.1 配置中心

在 `src/ops/services/realtime_config_service.py` 的对象 spec 增加 `etf_rt_min`。对象列表、detail、validate、publish、revision 与 apply state 均自动纳入第四个对象。

`enabled_freqs` 使用五项 checkbox group。`enabled`、限速、lease、stale、storage 和 timeout 可编辑；第 3.1 节 catalog 事实锁定。publish 只更新 `foundation.realtime_runtime_config` 和 `ops.config_revision`，之后必须重启既有 collector 才生效。

validate 必须读取 source 活跃池数量、计算分片数和峰值请求量；不得读取监控池或规则。

### 8.2 health 与实时流监控

新增 `src/ops/queries/realtime_feed_health_query_service.py` ETF minute item builder、`src/ops/schemas/realtime.py` schema 和 `src/ops/api/realtime.py` 路由：

```text
GET /api/v1/ops/realtime/etf-rt-min/health
GET /api/v1/ops/realtime/etf-rt-min/health?freq=1MIN
```

前端改动只在既有：

```text
frontend/src/shared/api/realtime-types.ts
frontend/src/pages/ops-realtime-config-center-page.tsx
frontend/src/pages/ops-realtime-monitor-page.tsx
```

页面只使用 Ops API。配置中心从 objects/detail 得到第四个对象；实时流监控按五个频率展示独立 health。不得把持久化分钟行、派生周期、监控指标或告警操作塞入这两个页面。

---

## 9. 文件清单与测试

| 文件/区域 | 目标改动 |
| --- | --- |
| `src/foundation/realtime/config_catalog.py` | `etf_rt_min` 锁定事实 |
| `src/foundation/realtime/runtime_config.py` | 新 config 和 fail-fast load/build |
| `src/foundation/realtime/runtime_config_seed_service.py` | seed 第四对象，初始仅 `1MIN` / 260 批 |
| `src/foundation/realtime/etf_rt_min.py` | provider、normalizer、collector、per-frequency publisher |
| `src/foundation/realtime/state_store.py` | ETF 1MIN final fact contract；Redis/in-memory/test store 同步 |
| `src/foundation/realtime/collector_service.py` | 统一服务调度 ETF minute，不加 systemd |
| `src/foundation/realtime/etf_realtime_minute_archive.py` | 独立分钟源归档 service |
| `src/foundation/realtime/etf_realtime_minute_history_repair.py` | `etf_mins` 历史缺口修复 |
| `src/foundation/models/realtime/**`、DAO、registry、Alembic | `foundation.etf_realtime_minute_bar_1m` 的 HDD 表/分区/DAO |
| `src/ops/services/etf_series_active_seed_service.py` | `etf_rt_min` resource 白名单 |
| `src/ops/** realtime config/health` | config object、health API；不接监控服务 |
| `frontend/** realtime config/monitor` | 第四对象和 ETF minute health 区块 |

必须新增或扩展的测试：

1. `rt_min` 只传 `ts_code/freq`、显式 fields、非法行、分片与失败原子性。
2. per-frequency Redis key 隔离、260 共享留存、`1MIN` valid/missing/invalid quality upsert。
3. 09:30 特殊键、午休边界、N 分钟完整覆盖、源端 5MIN 舍入差不影响自身聚合。
4. archive 按真实 key 幂等、HDD migration/partition metadata、状态失败不回滚 minute fact transaction。
5. `etf_mins` 历史补数、source 倒序、当日空数组、只修 missing、不覆盖 valid。
6. 配置/health/page 不读取监控池；existing monitor archive service 不能成为 source collector 的 consumer。

---

## 10. 部署与验收门禁

1. 新增迁移前重新确认 Alembic head；HDD tablespace 已由运维预置并能在部署环境验证，迁移不得降级到默认存储。
2. 先 seed `ops.etf_series_active(resource='etf_rt_min')`，再发布 config，初始只启用 `1MIN` 并设置 `keep_recent_batches=260`。
3. collector 重启后验证 apply state、非交易时段 `market_closed`、交易时段 source 分片、Redis final fact、health 和页面。
4. 收盘验收 archive：241 个期望分钟键（09:30 独立键、上午 120 根、下午 120 根）的 source 事实、真实缺失、午休不跨窗和重跑幂等。
5. 历史日验收 repair：选定缺口，`etf_mins` 补数后从 `missing` 变 `valid`；当日空数组不得被填零。
6. ETF 成交额监控另立部署和业务验收，不作为本 LLD 的完成条件。
