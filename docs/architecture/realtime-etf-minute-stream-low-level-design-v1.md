# ETF 实时分钟流接入 LLD v1

状态：待 M0 实测冻结后开发。本文定义编码位置、类型、配置、接口、测试和清理边界；不代表任何 `etf_rt_min` 代码已经存在。

创建日期：2026-08-24
上位方案：[ETF 实时分钟流接入方案 v1](/Users/congming/github/goldenshare/docs/architecture/realtime-etf-minute-stream-plan-v1.md)
下游契约：[ETF 实时成交额异动监控 LLD v1](/Users/congming/github/goldenshare/docs/ops/ops-etf-realtime-volume-anomaly-monitor-lld-v1.md)

---

## 1. 实施约束

1. 新主实现仅位于 `src/foundation/realtime/**`、`src/ops/**`、`src/app/**` 和 `frontend/**`；不得进入 `platform/operations`。
2. `foundation` 不读取 `ops.etf_realtime_monitor_pool`，不 import Ops model/service。分钟源代码范围只通过现有 `EtfSeriesActiveStore` contract 读取 `ops.etf_series_active(resource='etf_rt_min')`；不得依赖任何下游业务名单。
3. 不新增 DatasetDefinition、TaskRun、业务表、Alembic 表迁移或 systemd 服务。`foundation.realtime_runtime_config` 是现有泛化配置表，只新增一行配置对象。
4. 所有 health/配置/采集日志写失败都不得阻塞或回滚已有 Redis 当前批次，更不得影响业务数据事务。
5. 未通过 M0 前，禁止在代码中硬编码 HTTP API 名、topic、bar finality、grace、代码分片上限或 ETF/股票分钟的限速关系。

---

## 2. 文件级改造清单

| 文件 | 改造 |
|---|---|
| `src/foundation/realtime/constants.py` | M0 后新增 ETF minute source/display/feed 常量 |
| `src/foundation/realtime/config_catalog.py` | 新增 `ETF_RT_MIN_OBJECT_KEY`、catalog 和锁定事实 |
| `src/foundation/realtime/runtime_config.py` | 新增 `RealtimeEtfRtMinConfig`；runtime root/load/build/limiter 逻辑扩展 |
| `src/foundation/realtime/runtime_config_seed_service.py` | 新增受控默认配置；seed 从 3 对象扩展为 4 对象 |
| `src/foundation/dao/etf_series_active_dao.py` | 复用既有 `list_active_codes(resource)`；ETF minute 只传 `resource='etf_rt_min'`，不 import Ops ORM |
| `src/foundation/realtime/etf_rt_min.py` | 新建 provider、normalizer、按独立 source 活跃池读取代码的 per-frequency publisher/collector 结果类型 |
| `src/foundation/realtime/collector_service.py` | 注入 ETF minute collector，按 frequency 独立调度并写 apply state |
| `src/foundation/realtime/state_store.py` | 新增分钟采集/最终分钟事实的类型化 contract；三种 store 实现同步 |
| `src/foundation/realtime/config_apply_state.py` | apply state 增加 `etf_rt_min.version` |
| `src/foundation/clients/tushare_client.py` | 仅在 M0 确认共享 API 配额时改为共享 realtime rate-limit resolver；不得猜测 |
| `src/ops/services/etf_series_active_seed_service.py` | 扩展受控 resource 白名单，允许独立 seed `etf_rt_min`；不得由监控池写入或派生 |
| `src/ops/queries/realtime_feed_health_query_service.py` | 新增 ETF minute 五频率 health wrapper/item |
| `src/ops/schemas/realtime.py` | 新增 ETF minute health response schema |
| `src/ops/api/realtime.py` | 新增 ETF minute health routes |
| `src/ops/services/realtime_config_service.py` | 将 ETF minute 加入 object spec、字段元信息、validate/publish/apply state |
| `src/cli_parts/realtime_handlers.py` | 继续仅装配统一 collector；不得在 ETF minute 结果后隐式调用成交额监控、Feishu 或归档 |
| `frontend/src/shared/api/realtime-config-types.ts` | 仅新增后端 contract 类型字段 |
| `frontend/src/shared/api/realtime-types.ts` | 新增 ETF minute health contract |
| `frontend/src/pages/ops-realtime-config-center-page.tsx` | 复用对象目录/查看编辑态，渲染第四个对象与 checkbox group |
| `frontend/src/pages/ops-realtime-monitor-page.tsx` | 新增 ETF minute health 区块，局部 refetch |

现有 `src/foundation/realtime/etf_rt_daily.py` 不改为 ETF minute 实现；二者源接口、请求范围、时间语义和配置对象不同。

---

## 3. Foundation contract

### 3.1 常量与 catalog

M0 冻结后新增：

```python
ETF_RT_MIN_OBJECT_KEY = "etf_rt_min"
ETF_RT_MIN_DISPLAY_NAME = "ETF 实时分钟"
ETF_RT_MIN_FEED_KEY_PREFIX = "tushare_etf_rt_min"
ETF_RT_MIN_SUPPORTED_FREQS = ("1MIN", "5MIN", "15MIN", "30MIN", "60MIN")
```

`RealtimeConfigCatalogEntry`：

```python
ETF_RT_MIN_CATALOG = RealtimeConfigCatalogEntry(
    object_key=ETF_RT_MIN_OBJECT_KEY,
    object_kind="feed_group",
    display_name=ETF_RT_MIN_DISPLAY_NAME,
    source_api_name=<M0 frozen value>,
    exchange="SSE",  # 只用于交易日历，非代码市场过滤
    collection_sessions="09:30-11:30,13:00-15:00",
    ts_code_pattern="ops.etf_series_active(resource=etf_rt_min)",
    feed_key_prefix=ETF_RT_MIN_FEED_KEY_PREFIX,
)
```

M0 确认 `topic_policy=omit` 后，应以 catalog 锁定事实展示；不可进入 `runtime_config_json`。

### 3.2 Source 活跃池边界

`ops.etf_series_active(resource='etf_rt_min')` 是 ETF 分钟流自己的 source 活跃池。它定义“上游分钟流应请求哪些 ETF”，不属于实时流配置中心的可编辑配置，也不属于 `ops.etf_realtime_monitor_pool` 的下游选股范围。

初始 seed 可复用当前 ETF 活跃池的代码基线，但必须通过独立 resource 写入 `etf_rt_min`；以后 source 范围调整也只能经 ETF 活跃池治理流程完成。`src/ops/services/etf_series_active_seed_service.py` 的受控 resource 白名单必须显式允许 `etf_rt_min`，并为该 resource 保留独立的 seed 校验测试。

`EtfRtMinCollector` 只能经 foundation `EtfSeriesActiveStore.list_active_codes("etf_rt_min")` 读取这一事实。它不得读取 `ops.etf_realtime_monitor_pool`，也不得因监控页面添加、停用或删除 ETF 改变请求范围。

### 3.3 Runtime config

新增：

```python
@dataclass(frozen=True, slots=True)
class RealtimeEtfRtMinConfig:
    version: int
    display_name: str
    source_api_name: str
    enabled: bool
    enabled_freqs: tuple[str, ...]
    closed_bar_grace_seconds: int
    max_calls_per_minute: int
    lease_ttl_seconds: int
    stale_after_seconds: int
    storage: RealtimeFeedStorageConfig
    source_timeout_seconds: int

    def feed_key_for_freq(self, freq: str) -> str: ...
```

`RealtimeRuntimeConfig` 新增 `etf_rt_min` 字段；`load_realtime_runtime_config()` 必须读取第四条配置记录，缺失直接 fail-fast，不回退默认值。`build_realtime_runtime_config_from_json()`、测试 helper、seed service、config apply state 和所有构造方必须同步新增该参数，禁止只修改 dataclass。

seed 默认行：`enabled=false`、五个 `enabled_freqs`、72 小时 TTL、最近 3 批；`closed_bar_grace_seconds`、最大请求数和 timeout 仅在 M0 冻结后填入代码默认模板。已存在配置行仍 skip，不覆盖运营发布的值。

### 3.4 共享限速分支

现有 `TushareHttpClient._get_rate_limiter(api_name)` 以 API 名为 key，且 `get_realtime_tushare_max_calls_per_minute("rt_min")` 当前只返回股票分钟对象的配置。这不能被 ETF minute 直接复用。

M0 的 API 名结论决定唯一实现分支：

1. **ETF 实际 HTTP API 名独立**：为该 API 名新增 runtime config 映射，ETF config 的 `max_calls_per_minute` 生效。
2. **ETF 与股票实际 HTTP API 均为 `rt_min`**：新增一个明确的共享源站 rate-limit resolver；它读取股票分钟和 ETF 分钟当前 demand，按照总峰值设定同一个 `_RateLimiter`。配置中心 validate 与 ETF minute source 活跃池变更/seed 的校验都必须校验总需求，不允许两个 feed 各自通过而合计超限。

M0 前不选择分支，不在 `TushareHttpClient` 中加临时条件。

---

## 4. Provider、normalizer 与 Redis publish

### 4.1 `etf_rt_min.py` 类型

```python
@dataclass(frozen=True, slots=True)
class EtfRtMinFetchChunkResult:
    chunk_index: int
    requested_ts_codes: tuple[str, ...]
    rows: list[dict[str, Any]]
    requested_at: datetime
    received_at: datetime
    source_elapsed_ms: float

@dataclass(frozen=True, slots=True)
class EtfRtMinFetchResult:
    freq: str
    feed_key: str
    chunks: tuple[EtfRtMinFetchChunkResult, ...]

@dataclass(frozen=True, slots=True)
class EtfRtMinNormalizeResult:
    snapshots: list[dict[str, Any]]
    missing_ts_codes: tuple[str, ...]
    invalid_count: int
    invalid_reason_counts: dict[str, int]
```

`TushareEtfRtMinProvider.fetch_codes(freq, ts_codes)`：

1. 先用 `normalize_etf_rt_min_freq` 验证 freq。
2. 只传 M0 冻结的 HTTP API 名、`ts_code`、`freq` 和显式 fields。
3. 绝不传 `HQ_FND_TICK`。
4. 分片按 M0 冻结的 `validated_codes_per_request` 执行，顺序请求，记录每分片 receive time。
5. 分片失败即抛结构化 source exception；publisher 不发布半批次。

normalizer 必须保留：

```text
ts_code,freq,time,open,close,high,low,vol,amount,
source=tushare,source_api_name,requested_at,received_at,raw_payload_hash
```

`time` 解析失败、freq 不符、缺代码、缺 amount 为 invalid。`amount=0`、无成交、source time 旧不能自动拒绝。是否可接受“当前形成中 bar”由 M0 的 acceptance policy 决定；未被确认最终的 bar 只能进入观测记录，不能作为 final minute fact。

### 4.2 Publisher

每个 `(freq, due_at)` 生成独立 batch：

```text
feed_key = config.feed_key_for_freq(freq)
batch_id = build_batch_id(published_at)
```

只有全部 chunks 成功且 normalizer 覆盖规则通过时才调用：

```python
store.publish_batch(
    feed_key=feed_key,
    batch_id=batch_id,
    snapshots=...,
    meta={...},
    ttl_seconds=config.storage.snapshot_ttl_seconds,
    keep_recent_batches=config.storage.keep_recent_batches,
    ...,
)
```

meta 至少包含：`freq`、`expected_bar_end`、`requested_code_count`、`chunk_count`、`chunk_counts`、`source_row_count`、`snapshot_count`、`missing_ts_codes`、`invalid_count`、`source_elapsed_ms`、`requested_at`、`received_at`、`published_at`。

错误/半分片失败只写该 feed health，不改变 current pointer。

### 4.3 State store 的分钟事实 contract

在 `RealtimeStateStore` 中新增类型化方法，而不是由 Ops 拼 Redis key：

```python
record_etf_rt_min_observation(...)
list_etf_rt_min_observations(...)
upsert_etf_rt_min_final_fact(...)
list_etf_rt_min_final_facts(...)
```

事实键：`(trade_date, minute_end_time, ts_code, freq)`。每个值必须有 `quality=valid|missing|invalid`、`reason_code`、`source_batch_id`、`source_time`、`amount_yuan` 和 `captured_at`。

写入优先级：后到的 `valid` 可更新 earlier valid；`missing/invalid` 不得覆盖已有 valid。该 contract 的 TTL 需覆盖当日收盘归档，再由 M0/LLD 冻结实际秒数；它不依赖 `keep_recent_batches`。

---

## 5. source collector 与调度装配

新增 `EtfRtMinCollector`，属于 `src/foundation/realtime/etf_rt_min.py`，构造时只依赖 `RealtimeStateStore`、`RealtimeEtfRtMinConfig`、Tushare client 和 `EtfSeriesActiveStore`：

```python
class EtfRtMinCollector:
    def run_frequency(
        self, session: Session, *, freq: str, expected_bar_end: datetime
    ) -> EtfRtMinCycleResult: ...
```

调用顺序：

1. 通过 foundation `EtfSeriesActiveStore.list_active_codes("etf_rt_min")` 读取 source 活跃池；空池返回 `pool_empty`。
2. 按 M0 冻结的分片规则调用 foundation provider/publisher。
3. 用 M0 acceptance policy 将每行标记 final/observed/missing/invalid。
4. 成功发布 Redis feed 后写 state-store final facts/observations。
5. 合并 health；任一异常只返回这个 frequency `degraded`。

`RealtimeCollectorService` 负责 due/lease/频率隔离，并直接调用这个 foundation collector；不得依赖 Ops ORM、监控池、阈值规则、Feishu 或归档服务。`src/cli_parts/realtime_handlers.py` 只装配统一 collector，不得在 ETF minute result 后隐式触发成交额监控。

不得新增第二个 systemd 服务。

---

## 6. Ops API、配置中心与监控页

### 6.1 配置中心后端

在 `_OBJECT_SPECS` 增加 `etf_rt_min`；`_build_valid_runtime_config`、candidate build、field metadata、locked field rejection、affected feed 列表、revision 和 apply state 必须同时支持第四对象。

detail 契约：

```json
{
  "object_key": "etf_rt_min",
  "object_kind": "feed_group",
  "effective_config": {"enabled": false, "enabled_freqs": ["1MIN", "5MIN"]},
  "locked_config": {"feed_key_pattern": "tushare_etf_rt_min_{freq_lower}"},
  "fields": ["switch", "checkbox_group", "number_input", "locked_text"],
  "apply_state": {"status": "applied|pending_restart|unknown"}
}
```

`validate` 由 Ops service 通过 `EtfSeriesActiveStore` 查询 `resource='etf_rt_min'` 的 source 活跃池数量，计算 chunk count 和 peak budget；它不得读取监控池，也不得让 foundation import Ops DAO。发布仍是 version optimistic lock，写 `ops.config_revision`。

### 6.2 Health API

新增路由：

```python
@router.get("/ops/realtime/etf-rt-min/health")
def get_etf_rt_min_health(freq: str | None = None, ...): ...
```

不传 `freq`：总是返回五个 supported frequency item；传 `freq`：同一 wrapper 只返回一个。无 Redis、disabled、idle、degraded、stale、unavailable 沿用 stock minute health 的语义；不能用前端推导。

### 6.3 前端

`ops-realtime-config-center-page.tsx` 不新增单独页面逻辑：对象列表从 API 获取第四项，字段 control 从 API metadata 生成。必须做到：

1. `enabled_freqs` 是五个明确 checkbox，不接受手填字符串。
2. 查看态把已启用频率显示成标签；锁定事实只读。
3. 编辑态的 diff/预算/重启影响只在校验后展示。
4. 版本冲突、apply unknown、restart pending 沿用当前配置中心三态。

`ops-realtime-monitor-page.tsx` 新增 ETF minute 区块：按五个 health item 展示频率、状态、启用、预期分钟、源端最新时间、pool 覆盖、缺失/无效数、当前批次、耗时和错误。两个页面均只调 Ops API，不连 Redis/Tushare。

---

## 7. 测试矩阵

| 层级 | 必测内容 |
|---|---|
| Runtime config | 四对象加载/seed/fail-fast、五频率、非法 freq/空 selection、grace/stale/lease、共享限速分支 |
| Provider | M0 API 名、omit topic、显式 fields、多代码与分片、chunk failure、source time/freq/amount 无效 |
| Publisher/store | per-frequency key 隔离、原子 current pointer、meta、valid 覆盖、missing/invalid 不覆盖 valid |
| Collector | source 活跃池空/变更、每频率 due、午休、lease skip、单频失败隔离、health；证明不读取监控池 |
| Config API | objects/detail/validate/publish/revision/apply state，source 活跃池容量/峰值预算，locked/unknown field rejection |
| Health API | 五项 wrapper、单 freq、disabled/idle/degraded/stale/unavailable、Redis unavailable |
| Frontend | checkbox、查看/编辑态、预算 warning、第四对象、五频率 health、局部轮询与错误隔离 |
| Architecture | subsystem dependency matrix、legacy guardrails、无 foundation -> ops 依赖 |

建议新增测试文件：

```text
tests/test_realtime_etf_rt_min.py
tests/test_realtime_etf_rt_min_collector.py
tests/test_realtime_etf_rt_min_state_store.py
tests/web/test_ops_realtime_etf_rt_min_api.py
tests/web/test_ops_realtime_config_api.py  # 扩第四对象
frontend/src/pages/ops-realtime-config-center-page.test.tsx
frontend/src/pages/ops-realtime-monitor-page.test.tsx
```

---

## 8. 开发前检查清单

编码前必须逐项完成：

1. M0 实测文件已落档，且解决 HTTP API 名和 topic policy 冲突。
2. 已明确 ETF/股票分钟共享或独立限速的唯一实现分支。
3. 已冻结各频率 `expected_bar_end`、grace 和 finality policy。
4. 已验证单请求实际容量，得到 `validated_codes_per_request`。
5. 配置项审计表包含来源、持久化、消费者、依赖、生效方式和页面可见性。
6. ETF minute source 活跃池变更后的峰值预算校验路径已设计到 API/service/test，不依靠人工记忆；成交额监控池变更不得影响该预算。
7. 依赖矩阵、前端组件/页面规范和现有 realtime config API 消费者已再次审计。

任一项未完成时，停止在设计状态，不实现 provider 或配置对象。
