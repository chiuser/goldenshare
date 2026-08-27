# ETF 实时成交额异动监控 LLD v1

状态：下游监控 LLD，待 ETF 实时分钟流 M0 验证和标准 `etf_mins` 数据集接入完成后开发。旧的 `rt_etf_k` 批次差额分钟监控实现不得继续扩展、验收或作为历史基准。

创建日期：2026-08-22
最近修订：2026-08-24
上位方案：[ETF 实时成交额异动监控方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-etf-realtime-volume-anomaly-monitor-plan-v1.md)
实时上游 LLD：[ETF 实时分钟流接入 LLD v1](/Users/congming/github/goldenshare/docs/architecture/realtime-etf-minute-stream-low-level-design-v1.md)。ETF 分钟源的 provider、配置、per-frequency feed、调度、finality 和 health 只由该 LLD 定义；历史分钟表则由独立 `etf_mins` 数据集定义。本文只定义监控如何消费两类已有事实。

---

## 1. 目标、边界与替换结论

### 1.1 目标

在交易时段内，以运营维护的 ETF 监控池为范围：

1. 用 `rt_etf_k` 的高频累计成交额提供盘中提前信号。
2. 只读 ETF 实时分钟流发布的 `1MIN final/valid` 分钟事实，以及标准 `etf_mins` 数据集独立同步的历史分钟表，作为真实分钟成交额与上一开市日基准。
3. 支持 `1m`、`5m`、`15m` 窗口的单 ETF、单规则阈值与 Feishu 通知。
4. 使用标准数据集已独立同步的真实分钟事实；本需求不负责历史同步、缺口补数或历史表写入。

### 1.2 本轮明确不做

1. 不新增 DatasetDefinition、TaskRun、freshness、date audit 或面向用户的 ETF 实时查询 API。
2. 不修改 `rt_etf_k` 的全市场源端事实范围，不在 provider 阶段按监控池过滤。
3. 不增加 systemd 服务；继续由 `goldenshare-realtime-collector.service` 运行统一 collector。
4. 不引入 WebSocket、Doris、秒级历史落库或自动生成监控池/规则。
5. 不将 Feishu secret 写入数据库、Redis、页面、文档或仓库。

### 1.3 已确认的替换范围

| 当前代码/表 | 当前语义问题 | 目标替换 |
|---|---|---|
| `src/foundation/realtime/etf_volume_metrics.py` | 相邻 `rt_etf_k.amount` 差额被命名为真实分钟成交额 | 拆分为采样窗口信号计算与真实分钟事实计算；不再以 batch 差额生成分钟历史 |
| `src/ops/services/etf_realtime_monitor_service.py` | 扫描最近 260 个全市场批次，按旧 5 日均值判级 | 只维护监控池轻量窗口状态，按上一开市日同窗口曲线判级 |
| `src/ops/services/etf_realtime_minute_archive_service.py` | 将全市场累计差额伪装成分钟历史 | 从监控主链退场；不由 realtime 替换为任何历史归档 bridge |
| `src/cli_parts/realtime_handlers.py` | 每次 `rt_etf_k` 成功后直接进入旧监控 | 上游分钟 feed 发布后，只调度本需求的窗口计算；实时采集与标准 `etf_mins` 历史同步各自独立 |
| `ops.etf_realtime_minute_stat` | 保存旧差额、累计值与伪分钟质量 | 不得重建为历史分钟事实表；历史分钟事实表只由标准 `etf_mins` 数据集定义 |
| `ops.etf_realtime_monitor_rule` | `observe_ratio/alert_ratio/strong_ratio` 表达旧 5 日均值 | 明确重建为速度比与完整窗口比的规则表 |
| `ops.etf_realtime_alert` | 事件、通知结果与旧测量语义混在一行 | 重建为告警事件表，并新增独立 delivery 表 |

切换不是兼容改造：三个旧语义表必须在实施前取得单独清理重建授权。`ops.etf_realtime_monitor_pool` 保留，不清空。

---

## 2. 已审计的当前代码与依赖边界

### 2.1 当前主链入口

| 职责 | 当前代码 | 改造后职责 |
|---|---|---|
| 统一调度入口 | `src/cli_parts/realtime_handlers.py` | 继续作为 collector CLI 的 orchestration 入口 |
| 统一 collector | `src/foundation/realtime/collector_service.py` | 调度全市场 `rt_etf_k`；不能直接读取 Ops 监控池 |
| ETF 日内快照 provider/collector | `src/foundation/realtime/etf_rt_daily.py` | 保留全市场采样；增加分段 `captured_at` 回传 |
| realtime 配置 | `src/foundation/realtime/runtime_config.py`、`config_catalog.py` | ETF 分钟流 LLD 定义 `etf_rt_min`；本 LLD 只消费其已发布配置语义 |
| Redis store contract | `src/foundation/realtime/state_store.py` | ETF 分钟流 LLD 定义分钟 final facts；本 LLD 只消费它并维护窗口状态 |
| 监控服务 | `src/ops/services/etf_realtime_monitor_service.py` | 按新双源语义重写 |
| 分钟历史维护 | 独立 `etf_mins` 数据集 | 本需求只读已同步分钟事实，不调用同步或补数 |
| ETF 监控 API | `src/ops/api/etf_realtime_monitor.py` | 保留路由域，替换规则/告警 schema |
| 前端配置页 | `frontend/src/pages/ops-etf-realtime-monitor-config-page.tsx` | 监控池维持现状；规则与告警消费新契约 |

`foundation` 只处理源接口、配置、Redis contract 和纯计算；不得 import `ops` ORM、DAO 或 service。监控池读取、规则决策、告警持久化、Feishu 发送和收盘编排属于 `ops`。`app`/CLI 负责装配二者。

### 2.2 现有 Redis batch contract

`RealtimeStateStore` 已提供按 `feed_key` 的 current pointer、batch meta、snapshot、stream、health 访问。新实现必须继续通过该 contract 读写，禁止 Ops service 直接拼 Redis key。

`rt_etf_k` 当前 feed key 为 `tushare_etf_rt_k`。ETF 分钟流按频率使用独立 feed：

```text
tushare_etf_rt_min_1min
tushare_etf_rt_min_5min
tushare_etf_rt_min_15min
tushare_etf_rt_min_30min
tushare_etf_rt_min_60min
```

两个 feed 的 current pointer、batch、snapshot、health 与 stream 必须完全隔离。

### 2.3 CodeGraph 审计结果

本 LLD 编写前已用 CodeGraph 检查 `build_etf_minute_metrics_for_trade_date` 与 `EtfRealtimeMonitorService` 影响面，确认直接链路覆盖：

1. `src/foundation/realtime/etf_volume_metrics.py`。
2. `src/ops/services/etf_realtime_monitor_service.py`。
3. `src/ops/services/etf_realtime_minute_archive_service.py`。
4. `src/cli_parts/realtime_handlers.py`。
5. `tests/test_etf_realtime_volume_metrics.py`、`tests/web/test_etf_realtime_monitor_service.py`、`tests/web/test_etf_realtime_minute_archive_service.py` 及 realtime state store/collector/config API 消费者。

实施前如以上调用关系有变化，必须重新运行 CodeGraph impact/callers/callees，不得仅按本文路径猜测。

---

## 3. 源接口与时间语义

### 3.1 `rt_etf_k`：高频累计快照

职责是盘中采样信号，源端 `amount` 是当日截至该源端时点的累计成交额，不是某一分钟的成交额。

全市场每轮固定两段请求：

| 市场 | `ts_code` | `topic` |
|---|---|---|
| SH | `5*.SH` | `HQ_FND_TICK` |
| SZ | `1*.SZ` | 空 |

实现位置：`src/foundation/realtime/etf_rt_daily.py`。

现有 provider 只在整轮完成后使用一个 `received_at`。新实现须改为每个请求段创建 `captured_at`，并让该段返回的每一行 snapshot 带该值：

```python
@dataclass(frozen=True)
class EtfRtKSourceSegmentResult:
    market: Literal["SH", "SZ"]
    captured_at: datetime
    rows: list[dict[str, object]]
    source_elapsed_ms: int

@dataclass(frozen=True)
class EtfRtKFetchResult:
    segments: tuple[EtfRtKSourceSegmentResult, ...]
```

`captured_at` 是服务端收到该段响应的 UTC 时间，用于窗口进度和采样间隔。`trade_time` 是源端行情时间，只用于新鲜度展示和排障；禁止用它推导采样间隔、窗口进度或跨段先后。

两段中任一段请求失败时，保持现有全市场 feed 的原子发布语义：不得切换 current pointer，仅将该 feed health 写为 `degraded`。监控服务也不得从失败轮生成窗口信号。

### 3.2 ETF 分钟流：下游输入契约

ETF 分钟流接入实现只存在于 [ETF 实时分钟流接入 LLD v1](/Users/congming/github/goldenshare/docs/architecture/realtime-etf-minute-stream-low-level-design-v1.md)。它支持由运营配置选择 `1MIN/5MIN/15MIN/30MIN/60MIN`，并为每个频率独立发布 Redis feed。

本 LLD 只消费其中的 `1MIN` 最终事实。调用方必须经 `RealtimeStateStore` 的类型化读取 contract 获取，不能直接请求 Tushare、拼 Redis key 或自行判断 bar 是否闭合。可用于监控基准的行至少满足：

```text
ts_code, freq=1MIN, source_time, amount_yuan, vol,
received_at, batch_id, quality=valid, final=true,
source, source_api_name, raw_payload_hash
```

`time` 的真实语义、源端 API 名、`topic` 规则、代码池、请求分批和 `final` 判定均由上游 M0 实测冻结。任何尚未 `final`、缺少身份字段或 `quality != valid` 的行不得参与历史基准或告警最终值；本需求不参与分钟归档。

---

## 4. 配置模型与发布校验

运行时可编辑配置仍持久化于 `foundation.realtime_runtime_config`，锁定源端事实保留在 `src/foundation/realtime/config_catalog.py`。`REDIS_URL` 是部署级 env，不进入运营配置中心。

### 4.1 `etf_rt_daily` 高速采样配置

`etf_rt_daily.poll_interval_seconds` 允许整数 `1..60`。每个采样周期必须执行 SH、SZ 两个源请求，所以最小调用预算是：

```text
required_calls_per_minute = 2 * ceil(60 / poll_interval_seconds)
```

乘以 `2` 的原因不是重试，而是单轮全市场事实天然需要沪市和深市两次独立 Tushare 请求。

`src/foundation/realtime/runtime_config.py` 的 ETF 配置构建函数必须验证：

1. interval 在 `1..60`。
2. `max_calls_per_minute >= required_calls_per_minute`。
3. `stale_after_seconds >= poll_interval_seconds`。
4. `lease_ttl_seconds > poll_interval_seconds`，避免同一 feed 周期重叠。
5. 采集耗时超过 interval 时，统一 collector 不重叠执行；记录滞后/缺采，不能并发补跑同一周期。

`keep_recent_batches=260` 是全市场 Redis 快照保留策略，不得成为监控计算的前提；历史分钟由独立 `etf_mins` 数据集维护。

### 4.2 `etf_rt_min` 配置边界

`etf_rt_min` 是 ETF 分钟流的独立配置对象，与 `etf_rt_daily` 独立 version、apply state 和 health。其全部可编辑字段、锁定事实、五频率 checkbox、发布校验、重启生效逻辑以及配置中心展示由 ETF 分钟流接入方案定义。本监控 LLD 不得再次定义或覆盖这些字段。

监控代码只依赖一项明确事实：运营启用了 `1MIN` 后，上游会发布可消费的 `1MIN final/valid` 行；如果未启用、health degraded 或没有 final row，本轮监控必须标记该分钟为 `missing`，不得把旧数据或 `0` 当作正常值。

---

## 5. Redis contract：分钟事实输入与窗口状态

### 5.1 不能用全市场 batch 回扫代替状态

实时 monitoring 不应在每次采样时扫描 260 个全市场 batch：这会把全市场 Redis 留存量变成监控计算依赖，也会让采样缺口无法精确表达。新流程只维护监控池中当前窗口需要的最小状态。

### 5.2 监控侧新增的类型化 `RealtimeStateStore` 方法

ETF 分钟流 LLD 负责定义和写入每频率的分钟事实、采集日志与 `final` 状态；本 LLD 不得重复提供写入分钟源事实的方法。监控侧只新增自己的窗口状态方法，并使用上游提供的类型化 final-fact 查询：

```python
async def get_etf_window_sample_state(
    self, *, trade_date: date, ts_code: str, window_minutes: int, window_end_time: time
) -> EtfWindowSampleState | None: ...

async def put_etf_window_sample_state(self, state: EtfWindowSampleState) -> None: ...

async def delete_etf_window_sample_state(
    self, *, trade_date: date, ts_code: str, window_minutes: int, window_end_time: time
) -> None: ...

async def list_etf_final_minute_facts(
    self, *, feed_key: str, trade_date: date, ts_codes: Sequence[str], freq: str = "1MIN"
) -> list[EtfFinalMinuteFact]: ...
```

Ops 只能调用这些方法，不能拼 key。具体 Redis key 前缀由 `redis_keys.py` 统一管理；每类状态必须带 TTL，交易日结束后按 realtime 留存策略自然过期，不能无限增长。

### 5.3 `EtfWindowSampleState`

键：

```text
trade_date + ts_code + window_minutes + window_end_time
```

值至少包括：

```text
anchor_captured_at
anchor_cumulative_amount_yuan
anchor_source_trade_time
last_captured_at
last_cumulative_amount_yuan
last_source_trade_time
last_batch_id
sample_count
quality
missing_reason
```

只在同一交易时段、同一逻辑窗口写入。累计金额下降、采样间隔超限、跨午休或跨交易日时，先删除旧状态，再以当前有效样本建立新锚点；禁止对断点两侧的累计值相减。

### 5.4 上游分钟 capture 的下游消费

分钟采集日志不是分钟统计表。其写入模型和 Redis key 由 ETF 分钟流 LLD 定义；本 LLD 只约束监控读取它时必须能区分真实 `valid`、`invalid` 和 `missing`，用于识别实时缺失：

```text
trade_date
requested_at
ts_code
request_group_id
source_time
batch_id
amount_yuan
vol
quality=valid|invalid|missing
reason_code
raw_payload_hash
```

即使某次请求失败、某代码没有返回行或行无效，上游也必须以真实交易日、真实预期分钟桶和 reason 记录 capture。禁止使用 `date.min` 或 `time.min` 填充假键。失败记录不能覆盖分钟 feed current pointer，也不能把 `missing` 转为金额 `0`。

---

## 6. 纯计算口径

纯计算函数放在 `src/foundation/realtime/etf_volume_metrics.py`，只接受明确的 input dataclass，不能读 Redis、数据库、时钟单例或 Ops 配置。

### 6.1 逻辑窗口

窗口类型仅为 `1/5/15` 分钟。`RealtimeMarketClock` 负责判断交易日和 `09:30-11:30`、`13:00-15:00` 时段；窗口不能跨午休。

```python
@dataclass(frozen=True)
class EtfWindowDefinition:
    trade_date: date
    window_minutes: Literal[1, 5, 15]
    start_at: datetime
    end_at: datetime
    session: Literal["morning", "afternoon"]
```

`resolve_etf_window(captured_at, window_minutes, market_clock)` 必须：

1. 在非交易时段返回 `None`。
2. 将 `1m` 映射为 `[10:00:00, 10:01:00)`；`5m` 为 `[10:00:00, 10:05:00)`；`15m` 为 `[10:00:00, 10:15:00)`。
3. 按上午、下午各自对齐，不跨 `11:30 -> 13:00`。
4. `09:30` 特殊边界只能按 M0 实测后的冻结规则实现，不能凭本文示例猜测。

### 6.2 盘中采样金额

输入为当前窗口内两个或以上有效累计样本：

```python
@dataclass(frozen=True)
class EtfCumulativeSample:
    captured_at: datetime
    cumulative_amount_yuan: Decimal
    source_trade_time: datetime | None
    batch_id: str
```

规则：

```text
anchor = 窗口开始后的第一条有效 sample
current = 窗口内最新有效 sample
sampled_amount_yuan = current.cumulative_amount_yuan - anchor.cumulative_amount_yuan
elapsed_seconds = current.captured_at - anchor.captured_at
```

`sampled_amount_yuan` 的名称必须始终带 `sampled`，不得写入 `amount_yuan`、`minute_amount_yuan` 或历史分钟表。它代表已观察采样区间的成交额，下限保守但不是完整分钟事实。

下列情形返回 `quality=invalid|missing`，不出金额：累计金额下降、两样本不足、负 elapsed、间隔大于 `2 * poll_interval_seconds`、窗口/时段不一致、无法解析金额。

### 6.3 昨日同期曲线

基准日期只取当前日期之前最近一个开市日：

```python
TradeCalendarDAO(session).get_latest_open_date(
    exchange="SSE",
    before_or_on=trade_date - timedelta(days=1),
)
```

不得回退到 5 日或更早日期。

昨日基准仅来自标准 `etf_mins` 数据集已独立同步的 `1min` 历史事实。令当前窗口的昨日分钟金额序列为 `b1...bn`，构造累计函数 `F_y(t)`：

1. 已完全经过的分钟，累计完整 `amount_yuan`。
2. 只对 anchor 和 current 所在的首尾不完整分钟，按已过秒数线性比例分摊。
3. 所需分钟任一不存在或数据不完整时，返回 `baseline_unavailable`，不回填 `0`，不告警。

```text
expected_amount_yuan = F_y(current.captured_at) - F_y(anchor.captured_at)
pace_ratio = sampled_amount_yuan / expected_amount_yuan
window_ratio = sampled_amount_yuan / baseline_window_amount_yuan
```

没有保存昨天的 `rt_etf_k` 秒级采样。整数分钟部分完全使用真实分钟事实；只有不足一分钟的窗口首尾做比例近似。

### 6.4 判级与窗口收盘复核

新规则字段与顺序：

1. `min_signal_elapsed_seconds` 未达到时，不产生盘中判定。
2. `pace_ratio >= observe_pace_ratio`，创建或更新 `observe` 事件，仅入库。
3. `window_ratio >= alert_window_ratio`，创建或升级为 `alert`，允许通知。
4. `window_ratio >= strong_window_ratio`，创建或升级为 `strong`，允许通知。
5. 窗口收盘后，由真实分钟和重新计算最终窗口金额并更新同一个事件；只能升级严重度，不能降级、删除或重复发送同级通知。

`observe_pace_ratio` 与 `alert_window_ratio` 衡量对象不同，不强制设置大小关系；但 `strong_window_ratio > alert_window_ratio` 是发布校验硬约束。

---

## 7. 数据表、迁移与清理门禁

### 7.1 保留表

`ops.etf_realtime_monitor_pool` 保留。它是运营通过页面从 `ops.etf_series_active(resource='etf_rt_min')` 中选择出的下游计算子集；不会在迁移中自动插入 ETF，也不会反向写入、裁剪或改变 ETF 分钟流的 source 活跃池。

### 7.2 重建 `ops.etf_realtime_monitor_rule`

清理旧表后建立的新字段：

| 字段 | 约束/含义 |
|---|---|
| `id` | 主键 |
| `scope_type` | `global|group|etf` |
| `scope_key` | 作用域 key；global 固定值由 service 统一校验 |
| `window_minutes` | 仅 `1|5|15` |
| `min_signal_elapsed_seconds` | 正整数，且小于该窗口秒数 |
| `observe_pace_ratio` | 大于 0 |
| `alert_window_ratio` | 大于 0 |
| `strong_window_ratio` | 大于 `alert_window_ratio` |
| `cooldown_minutes` | 非负整数 |
| `feishu_enabled` | 仅 `alert/strong` 是否允许发送 |
| `enabled` | 规则启停 |
| `created_at/updated_at` | 审计时间 |

规则优先级固定为：`etf` > `group` > `global`。同一个 `(scope_type, scope_key, window_minutes)` 不允许多条 enabled 规则。旧 `observe_ratio/alert_ratio/strong_ratio` 不迁移。

### 7.3 删除 `ops.etf_realtime_minute_stat`

该表保存的是旧 `rt_etf_k` 差额和伪分钟质量，不能重建为真实分钟事实表。监控迁移时应删除旧表而不重建；真实分钟数据只保存在标准 `etf_mins` 数据集定义的历史表。

监控的分钟缺失判断通过“标准历史表缺少期望的真实分钟键”获得，不另建一张 monitor minute stat 表，也不把 `missing/invalid` 写成业务分钟事实。

### 7.4 重建 `ops.etf_realtime_alert`

事件唯一键：

```text
(trade_date, ts_code, window_end_time, window_minutes, rule_id)
```

字段：

```text
id
trade_date
ts_code
etf_name_snapshot NULL
group_key
rule_id
window_minutes
window_start_time
window_end_time
measurement_kind sampled|closed
severity observe|alert|strong
sampled_amount_yuan NULL
final_amount_yuan NULL
baseline_trade_date NULL
baseline_expected_amount_yuan NULL
baseline_window_amount_yuan NULL
pace_ratio NULL
window_ratio NULL
quality
quality_reason NULL
cooldown_key
last_notified_severity NULL
created_at
updated_at
```

同键冲突时只更新最新测量值与最高 severity。`etf_name_snapshot` 从 `core_serving.etf_basic` 读取；名称缺失写 `NULL`，不能中断计算。

### 7.5 新建 `ops.etf_realtime_alert_delivery`

告警事件和外部发送结果必须分表。字段：

```text
id
alert_id FK -> ops.etf_realtime_alert.id
severity observe|alert|strong
channel feishu
status pending|sent|failed|skipped
attempt_count
requested_at
sent_at NULL
provider_message_id NULL
error_message NULL
payload_summary_json NULL
created_at
updated_at
```

唯一约束 `(alert_id, severity, channel)`。这样 `alert -> strong` 各有一条真实投递证据，重复计算同等级无法重复发送。

### 7.6 迁移顺序与不可自动执行的门禁

实施迁移前必须：

1. 重新检查 Alembic 单一 head，`down_revision` 只接当时真实 head。
2. 由运营明确授权删除 `minute_stat`，并清空重建 `monitor_rule`、`alert`；不备份、不做旧数据兼容。
3. 新迁移在同一发布批中删除旧 `minute_stat`，重建规则/告警 schema 和 delivery 表。
4. 迁移后监控池保留、规则为空、告警为空；运营通过新页面重建规则。

这不是本 LLD 阶段要执行的操作。没有逐表授权时，开发只能停在新代码/测试完成，禁止代码擅自清表。

---

## 8. 服务编排、事务与异常隔离

### 8.1 ETF 分钟流与监控的编排边界

ETF 分钟流 collector 的 provider 调用、source 活跃池代码选择、分批、每频率独立 publish、capture、health 与异常隔离，全部由 ETF 分钟流 LLD 定义。它必须先发布 `1MIN final/valid` 事实，监控主链才有资格消费。

本 LLD 只增加一个编排约束：上游某次 ETF 分钟流失败、未 final 或没有命中行时，监控服务不能把旧分钟行冒充当前分钟；它只能记录真实 `missing` 并继续处理其他 ETF、窗口和规则。上游采集失败不得阻断 `rt_etf_k`、股票日线或股票分钟 feed。

### 8.2 `rt_etf_k` 盘中窗口服务

重写 `EtfRealtimeMonitorService`，入口命名为：

```python
async def process_rt_etf_k_batch(
    self, *, batch_id: str, batch_published_at: datetime
) -> EtfMonitorRunSummary: ...
```

步骤：

1. 读取 enabled pool、解析有效规则、按 current `batch_id` 批量读 snapshots。
2. 只处理当前 batch 中命中监控池的 ETF；未命中、旧源端时间或非活跃池代码不当作 collector 失败。
3. 用 snapshot 段级 `captured_at` 解析当前逻辑窗口；更新/重置 `EtfWindowSampleState`。
4. 两样本、质量、最少观察时长和昨日基准都满足时，调用纯计算函数并 upsert alert event。
5. 事件数据库事务提交成功后，再处理 Feishu delivery；单对象/单规则失败写本次 run summary 并 continue。

服务不得扫描 `keep_recent_batches`，不得调用旧 `build_etf_minute_metrics_for_trade_date`。

### 8.3 窗口闭合复核

`finalize_closed_windows` 只对已经闭合且分钟事实完备的 `1/5/15` 窗口求真实 minute sum，更新已有 alert 的 `final_amount_yuan`/`measurement_kind=closed`，只允许升级。

交易分钟网格缺口、`etf_mins` 历史同步和历史表写入都不属于本 service。本需求只读取标准 `etf_mins` 数据集独立同步的历史表；不得再把 `ops.etf_realtime_minute_stat` 当成分钟历史或在监控流程里生成它。

### 8.4 告警与 Feishu

`src/ops/services/etf_realtime_feishu_notification_service.py` 是独立通道服务，复用签名/超时/错误解析经验但不复用 TaskRun 通知的开关和模板。

固定事务顺序：

```text
计算事件
  -> upsert ops.etf_realtime_alert
  -> commit alert event
  -> insert/update pending delivery
  -> commit pending delivery
  -> 调用 Feishu
  -> 独立事务更新 sent/failed、attempt_count、错误摘要
```

Feishu 失败只能更新 delivery；不得回滚 alert event、minute facts、Redis batch 或任何业务数据。`observe` 创建 delivery `skipped` 或不创建可由实现统一选择，但必须保留事件且不得请求 Feishu；`alert/strong` 才进入真实发送。

冷却键为 `ts_code + window_minutes + rule_id`。冷却期内同级/低级事件只更新事件，不新增发送；升到 `strong` 可创建新的 `strong` delivery。

---

## 9. 统一 collector 调度

仍使用一个 `goldenshare-realtime-collector.service`，不新增 systemd unit。源 feed 的 due time、闭合延迟、五频率调度和发布顺序由 ETF 分钟流 LLD 冻结；监控相关的单循环顺序是：

```text
1. ETF 分钟流按其独立配置完成某频率的采集与 publish
2. `etf_rt_daily` 成功发布后，尝试 `process_rt_etf_k_batch`
3. `1MIN final/valid` 分钟事实到达后，调度 `finalize_closed_windows`
```

每个步骤必须有独立 `try/except` 和独立日志字段。ETF 分钟采集失败、监控计算失败均不得阻断后续 feed 的 collector loop；标准历史同步是独立任务，不由本链路触发。

日志最少包含：

```text
feed_key, batch_id, trade_date, window_minutes, window_end,
pool_count, fetched, valid, missing, invalid, signals, deliveries,
source_elapsed_ms, write_elapsed_ms, error
```

---

## 10. Ops API 与前端契约

### 10.1 保留不变的监控池

`/api/v1/ops/realtime/etf-monitor/active-etfs` 与 pool CRUD 继续只管理监控池；规模、关键词、行内添加交互不属于本次双源重构范围。

### 10.2 替换规则契约

规则 API 路由可以保留 `/rules`，但 schema 只暴露第 7.2 节的新字段。旧 `default-global` endpoint 和旧 ratios 不得保留为兼容入口，也不得自动 seed 默认规则。

页面按 rule scope、窗口和新阈值字段编辑；页面不计算 expected amount、窗口、severity 或 cooldown。

### 10.3 替换告警契约

告警列表/详情应展示：

```text
ETF、名称快照、分组、规则、窗口、当前严重度、measurement_kind、
sampled/final amount、上一开市日、pace_ratio、window_ratio、质量、
delivery 历史
```

`delivery` 历史从独立 API 或详情内嵌只读列表返回。前端不得把 `sent` 推断为事件成功，也不得将 failed delivery 隐藏为“未告警”。

### 10.4 页面原则

页面必须遵循现有数据运营后台 token、`SectionCard/StatCard/StatusBadge/OpsTable/AlertBar` 模式。监控池、规则、告警是三个独立区块；只读展示与编辑态分开；无解释型 demo 文案、无前端重算、无浏览器端事实拼装。

---

## 11. 开发顺序与测试门禁

| 里程碑 | 代码范围 | 通过条件 |
|---|---|---|
| S0 | ETF 分钟流 M0 真实验证与记录 | 源 API、finality、五频率延迟、批大小、限速关系证据落档 |
| S1 | ETF 分钟流 provider、config、per-frequency feed、health 与页面 | 上游 `1MIN final/valid` contract 可被读取 |
| M1 | `rt_etf_k` 段级 captured_at、窗口状态、纯窗口计算 | 不直接拼 Redis key；采样断点/午休/首尾比例测试通过 |
| M2 | 消费真实分钟与昨天基准 | 只使用 `1MIN final/valid` 和标准 `etf_mins` 历史表；missing 非 0，不写历史表 |
| M3 | 删除旧 minute stat、重建规则/event/delivery service、Feishu | 取得三表清理授权；事件先提交、通知后回写 |
| M4 | CLI 编排、API/frontend 契约替换 | 单 systemd；无旧 ratio/old metric consumer |
| M5 | 部署、首日采集、次日告警验收 | 首日仅积累基准，次日才允许通知 |

必须新增/改写的测试至少覆盖：

1. `rt_etf_k` 两段请求、段级 `captured_at` 与 `1..60` 请求预算。
2. ETF 分钟流的 source request、五频率隔离、行级 `time`、finality、缺字段、分批和 health，按其独立 LLD 的测试矩阵验证。
3. 监控侧 Redis window state 隔离、窗口锚点重置、上游 capture missing/invalid 不覆盖有效事实。
4. `1/5/15` 窗口、午休、首尾秒数比例、采样中断、累计金额回退。
5. 前一开市日精确选择、昨天分钟缺失、首日无基准和不回退到 5 日。
6. 规则优先级、observe/alert/strong、同窗口幂等、alert 到 strong 升级、跨窗口冷却。
7. alert commit 在 Feishu 之前、Feishu 失败隔离、delivery 唯一性与重试。
8. 标准历史分钟只读消费、缺失不为 0、首日无基准与重复读取幂等。
9. API 权限、旧字段/旧 endpoint 清零、前端契约和类型检查。
10. architecture dependency matrix 与 legacy guardrails。

---

## 12. 开发前必须完成的 M0 决策记录

下列值未实测前不得进入 provider/collector 的最终实现：

1. ETF 分钟流 M0 的真实 HTTP API 名、`09:30` 集合竞价与 `09:31` 第一根连续竞价 minute bucket 归属，以及独立 `etf_rt_min` source 活跃池的初始 seed 校验。
2. ETF 分钟流 M0 的 `11:29-11:30`、`13:00-13:01` finality/延迟、午休不跨窗、多代码允许上限、合理 batch size、每频率请求预算与共享限速关系。
3. 一份同 ETF 的 `rt_etf_k` 窗口 sample 与上游 `1MIN final/valid` 真实分钟的完整对账；应记录请求参数、server capture time、source time、金额和差异。
5. 三张旧语义表的清理授权：删除 minute stat，重建规则和告警。没有授权，不实施迁移、不启用新规则/告警主链。

这些是功能正确性门禁，不是可选优化项。
