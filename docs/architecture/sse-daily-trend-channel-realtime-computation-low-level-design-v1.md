# 上证指数日线趋势通道实时计算 LLD v1

状态：代码已实现；生产部署与最终拓扑性能验收已完成

日期：2026-08-10

上位方案：[上证指数日线趋势通道实时计算方案 v1](/Users/congming/github/goldenshare/docs/architecture/sse-daily-trend-channel-realtime-computation-plan-v1.md)

适用标的：`000001.SH`

适用周期：`day`

公式版本：`sse-daily-trend-channel-v1`

---

## 1. LLD 结论

本 LLD 把已经拍板的产品口径落实为以下代码合同：

1. 新增独立只读 API：`GET /api/v1/quote/detail/trend-channel`。
2. API 只接受 `000001.SH + day`，不接受公式参数、复权参数和盘中模式。
3. 独立读取 `core_serving.index_daily_serving` 完整日线历史，不复用现有先 `limit` 的 K 线查询。
4. 使用纯 Python `float64` 递推四条 EMA，输出前再按 `ROUND_HALF_UP` 量化为四位 `Decimal`。
5. 短期与长期各返回 `position` 和带滞后的 `state`；通道内部保留上一状态。
6. 使用每日行数、最大交易日和最大更新时间构造数据水位。
7. 使用进程内、最多两个版本、可清空、带锁的不可变结果缓存。
8. v1 只返回正式日线，所有成功行固定 `is_provisional=false`。
9. 不修改 `QuoteKlineBar`、`QuoteKlineResponse` 或 `/quote/detail/kline`。
10. 不新增配置项、数据库表、迁移、DatasetDefinition、TaskRun、Lake 或 Dagster 资产。

本轮 LLD 只定义开发合同，不表示代码已经实现。

---

## 2. 已拍板硬口径

| 编号 | 硬口径 | 实施含义 |
| --- | --- | --- |
| D01 | 短期周期固定 25 | `EMA(high,25)` 与 `EMA(low,25)` |
| D02 | 长期周期固定 90 | `EMA(high,90)` 与 `EMA(low,90)` |
| D03 | 首值种子 | 第一根 EMA 等于第一根输入，`adjust=False` 语义 |
| D04 | 严格突破 | `close > upper` 才是 `ABOVE`；`close < lower` 才是 `BELOW` |
| D05 | 内部保留状态 | `INSIDE` 时 `state_t = state_(t-1)` |
| D06 | 位置与状态并存 | API 同时返回 `position` 和 `state` |
| D07 | 只做正式日线 | v1 不读取或生成盘中临时 OHLC |
| D08 | 独立 API | 使用 `/quote/detail/trend-channel`，共享 K 线合同不变 |
| D09 | 只支持上证指数 | 其他 `ts_code` 必须拒绝 |
| D10 | 先完整历史后切片 | `limit` 不能改变相同日期的计算值 |
| D11 | 失败关闭 | 坏行、重复日期和计算不变量失败时不跳过、不填充 |
| D12 | 不提前物化 | v1 按需计算并缓存，不新增持久化派生表 |

任何实现若与 D01～D12 冲突，应停止开发并回到方案评审，不得增加兼容分支。

---

## 3. 当前代码审计

### 3.1 审计工具与范围

本 LLD 使用 CodeGraph 完成：

1. `codegraph_explore`：追踪 Quote router、鉴权、异常、指数 K 线读取和模型链路。
2. `codegraph_node`：核验 `_load_kline_points`、`_load_index_points`、`require_quote_access`、Decimal 量化和错误响应源码。
3. `codegraph_impact`：核验 `QuoteKlineBar`、`get_quote_detail_kline` 和 `IndexDailyServing` 的影响面。
4. 定点文本核验：确认 API 测试、前端 URL 消费者和 `src/biz` 缓存现状。

### 3.2 现有入口

| 当前文件 | 当前事实 | 本方案决定 |
| --- | --- | --- |
| `src/app/api/router.py:12-20` | 总 API 前缀为 `/api` | 不修改 |
| `src/app/api/v1/router.py:30-39` | v1 前缀为 `/v1`，已 include `biz_quote.router` | 不修改总路由 |
| `src/biz/api/quote.py:26` | Quote router 前缀为 `/quote` | 在同一 router 新增独立端点 |
| `src/biz/api/quote.py:52-111` | 现有 `/detail/kline` 识别多类标的、周期和复权 | 不修改其参数、响应或实现 |
| `src/app/auth/dependencies.py:128-134` | `require_quote_access` 按环境决定是否要求登录 | 新端点原样复用 |
| `src/app/exceptions/web.py:21-26` | 错误结构为 `code/message/request_id` | 新错误沿用该结构 |

完整路径将自然组合为：

```text
/api + /v1 + /quote + /detail/trend-channel
= /api/v1/quote/detail/trend-channel
```

### 3.3 现有指数日线查询为何不能复用

`QuoteQueryService._load_kline_points()` 对指数转入 `_load_index_points()`。日线分支当前执行：

```text
where ts_code = ?
order by trade_date desc
limit request_limit
reverse rows
```

这对普通 K 线分页是正确的，但对 EMA 通道不正确，因为：

1. EMA 首值会从页面窗口第一根重新开始。
2. 通道状态也会丢失窗口之前的状态。
3. 同一日期会因请求 `limit` 不同得到不同轨道值。

因此禁止把通道计算直接塞入：

- `QuoteQueryService._attach_indicators()`；
- `QuoteQueryService._attach_indicators_with_context()`；
- `QuoteKlineBar`。

新实现必须使用独立完整历史查询。

### 3.4 当前数据模型

`src/foundation/models/core_serving/index_daily_serving.py:12-30` 已提供：

| 字段 | 当前类型 | 用途 |
| --- | --- | --- |
| `ts_code` | `String(32)`，主键 | 固定过滤 `000001.SH` |
| `trade_date` | `Date`，主键 | 排序、切片、观测日期 |
| `open/high/low/close` | `Numeric(18,4)` | K 线和通道计算 |
| `updated_at` | timezone datetime | 历史修订水位 |

复合主键 `(ts_code, trade_date)` 已能支持单指数按日期顺序读取，无需新增索引或迁移。

当前 `BaseDAO.bulk_upsert()` 在冲突更新时会显式执行 `updated_at = func.now()`；因此通过现有 serving publish 主链发生的历史修订可以被 `max(updated_at)` 水位捕获。若未来出现绕过当前 DAO 且不推进 `updated_at` 的直接 SQL 写入，必须先修正写入合同，不能在通道缓存里猜测修订。

`src/foundation/models/core/index_basic.py:12-33` 已提供指数名称与类型信息，独立 API 只读 `ts_code/name`。

### 3.5 当前 Decimal 响应语义

现有 Quote API 测试断言 `Decimal("11.1000")` 的 JSON 值为字符串 `"11.1000"`。现有 K 线实现使用：

```python
value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
```

新 API 保持相同语义：

- Schema 中价格字段使用 `Decimal`；
- JSON 返回四位小数字符串；
- 状态比较必须发生在量化之前。

### 3.6 当前缓存与实时源

1. `src/biz` 没有可以直接复用的通用进程内计算结果缓存。
2. 当前 realtime 只有 `stock_rt_daily`、`stock_rt_min` 和 `etf_rt_daily`。
3. 当前没有上证指数盘中 OHLC provider、feed key 或验证合同。

因此新增专用小缓存，但不接 Redis，不接现有 realtime collector。

### 3.7 消费者影响审计

CodeGraph 影响分析结果：

| 符号 | 当前影响面 | 结论 |
| --- | --- | --- |
| `QuoteKlineBar` | `quote.py` schema、`QuoteQueryService` 指标装配 | 不修改，影响清零 |
| `get_quote_detail_kline` | 只在当前 quote route 内注册 | 不修改 |
| `IndexDailyServing` | Quote、Wealth 市场模块、Ops 完整性测试等多个消费者 | 只读消费，不改模型 |

定点 URL 搜索没有发现 `frontend/` 或 `wealth/` 当前生产代码调用 `/api/v1/quote/detail/kline`；现有引用集中在 `tests/web/test_quote_api.py`。新端点当前没有既有前端消费者，后续绘图另行接入。

---

## 4. 目标代码结构

### 4.1 文件清单

| 动作 | 文件 | 职责 |
| --- | --- | --- |
| 修改 | `src/biz/api/quote.py` | 新增独立 route 和错误映射 |
| 新增 | `src/biz/schemas/quote_trend_channel.py` | 独立 Pydantic API 合同 |
| 新增 | `src/biz/queries/quote_trend_channel_query.py` | IndexBasic、数据水位、完整历史 SQL |
| 新增 | `src/biz/services/quote_trend_channel_calculator.py` | 纯计算、校验、状态机、量化 |
| 新增 | `src/biz/services/quote_trend_channel_query_service.py` | 水位一致性、缓存、切片、响应装配 |
| 新增 | `tests/test_quote_trend_channel_calculator.py` | 纯内核、负向样本、性能 |
| 新增 | `tests/fixtures/quote_trend_channel/000001_sh_daily_input.json` | 固定 `000001.SH` 正式日线 OHLC 输入快照 |
| 新增 | `tests/fixtures/quote_trend_channel/000001_sh_daily_expected_v1.json` | 与生产 calculator 解耦的 v1 独立金标 |
| 新增 | `tests/test_quote_trend_channel_query_service.py` | 完整历史查询、水位一致性、缓存与并发单飞 |
| 新增 | `tests/web/test_quote_trend_channel_api.py` | API、鉴权、水位、缓存、回归 |

明确不修改：

- `src/biz/schemas/quote.py`
- `src/biz/queries/quote_query_service.py`
- `src/app/api/v1/router.py`
- `src/foundation/models/**`
- `src/foundation/datasets/**`
- `src/ops/**`
- `lake_console/**`
- Alembic 迁移

### 4.2 依赖方向

```text
src/app router
  -> src/biz/api/quote.py
      -> src/biz/services/quote_trend_channel_query_service.py
          -> src/biz/queries/quote_trend_channel_query.py
              -> src/foundation/models/core/index_basic.py
              -> src/foundation/models/core_serving/index_daily_serving.py
          -> src/biz/services/quote_trend_channel_calculator.py
      -> src/biz/schemas/quote_trend_channel.py
```

不存在 `foundation -> biz`、`biz -> ops` 或 legacy 目录依赖。

---

## 5. API 详细合同

### 5.1 路由签名

目标签名：

```python
@router.get(
    "/detail/trend-channel",
    response_model=TrendChannelResponse,
)
def get_quote_detail_trend_channel(
    ts_code: str = Query(...),
    period: str = Query(default="day"),
    end_date: date | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> TrendChannelResponse:
    ...
```

### 5.2 参数归一化

API 层按顺序执行：

1. `normalized_ts_code = ts_code.strip().upper()`。
2. `normalized_period = period.strip().lower()`。
3. 非 `000001.SH` 返回 `400 UNSUPPORTED_TREND_CHANNEL_SYMBOL`。
4. 非 `day` 返回 `400 UNSUPPORTED_TREND_CHANNEL_PERIOD`。
5. `limit` 交给 FastAPI 执行 `1..2000` 校验。

禁止增加：

- `adjustment`
- `short_period`
- `long_period`
- `seed`
- `state_rule`
- `provisional`
- `realtime`

这些不是 v1 用户输入。

### 5.3 成功响应 Schema

`src/biz/schemas/quote_trend_channel.py` 定义：

```python
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

TrendChannelPosition = Literal["ABOVE", "INSIDE", "BELOW"]
TrendChannelState = Literal["UNKNOWN", "UP", "DOWN"]
TrendChannelCombinedState = Literal[
    "UNKNOWN",
    "UP_UP",
    "UP_DOWN",
    "DOWN_UP",
    "DOWN_DOWN",
]


class TrendChannelInstrumentDto(BaseModel):
    ts_code: Literal["000001.SH"]
    name: str
    security_type: Literal["index"] = "index"


class TrendChannelFormulaDto(BaseModel):
    key: Literal["high-low-ema-hysteresis"]
    version: Literal["sse-daily-trend-channel-v1"]
    short_period: Literal[25]
    long_period: Literal[90]
    seed: Literal["first_observation"]
    state_rule: Literal["strict_close_breakout_inside_retention"]


class TrendChannelBandDto(BaseModel):
    upper: Decimal
    lower: Decimal
    position: TrendChannelPosition
    state: TrendChannelState


class TrendChannelBarDto(BaseModel):
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    short_channel: TrendChannelBandDto
    long_channel: TrendChannelBandDto
    combined_state: TrendChannelCombinedState
    is_provisional: Literal[False] = False


class TrendChannelDataStatusDto(BaseModel):
    status: Literal["READY", "EMPTY"]
    observed_trade_date: date | None
    as_of_time: datetime
    is_provisional: Literal[False] = False
    note: str | None = None


class TrendChannelMetaDto(BaseModel):
    bar_count: int
    limit: int
    start_date: date | None
    end_date: date | None
    has_more_history: bool
    next_end_date: date | None


class TrendChannelResponse(BaseModel):
    instrument: TrendChannelInstrumentDto
    period: Literal["day"] = "day"
    adjustment: Literal["none"] = "none"
    formula: TrendChannelFormulaDto
    data_status: TrendChannelDataStatusDto
    bars: list[TrendChannelBarDto]
    meta: TrendChannelMetaDto
```

不得在成功响应中返回缓存 key、数据库 URL、内部异常或源表更新时间。

### 5.4 `EMPTY` 语义

以下两种情况返回 HTTP 200 与 `status=EMPTY`：

1. `000001.SH` 在 `index_daily_serving` 没有任何日线。
2. 数据源有历史，但请求 `end_date` 早于最早交易日。

`note` 分别使用：

- `source_has_no_daily_rows`
- `no_rows_on_or_before_end_date`

### 5.5 错误映射

| 内部场景 | HTTP | 对外 code |
| --- | ---: | --- |
| 标的不支持 | 400 | `UNSUPPORTED_TREND_CHANNEL_SYMBOL` |
| 周期不支持 | 400 | `UNSUPPORTED_TREND_CHANNEL_PERIOD` |
| `IndexBasic` 缺失 | 503 | `TREND_CHANNEL_INSTRUMENT_MISSING` |
| SQL 查询失败 | 503 | `TREND_CHANNEL_SOURCE_UNAVAILABLE` |
| 源数据坏行/超量 | 503 | `TREND_CHANNEL_SOURCE_INVALID` |
| 两次读取水位仍变化 | 503 | `TREND_CHANNEL_SOURCE_CHANGING` |
| 计算不变量失败 | 500 | `TREND_CHANNEL_COMPUTE_FAILED` |

API 通过 `WebAppError` 进入现有统一错误响应：

```json
{
  "code": "TREND_CHANNEL_SOURCE_INVALID",
  "message": "上证指数日线数据暂不可用于趋势通道计算",
  "request_id": "..."
}
```

对外消息不回显坏行的完整数据库内容；详细 reason code 和日期只写服务日志。

---

## 6. 查询层详细设计

目标文件：`src/biz/queries/quote_trend_channel_query.py`

### 6.1 查询层数据类型

```python
@dataclass(frozen=True, slots=True)
class TrendChannelInstrumentRow:
    ts_code: str
    name: str | None


@dataclass(frozen=True, slots=True)
class TrendChannelWatermark:
    row_count: int
    max_trade_date: date | None
    max_updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class TrendChannelSourceRow:
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    updated_at: datetime
```

### 6.2 `load_instrument()`

```python
select(IndexBasic.ts_code, IndexBasic.name)
.where(IndexBasic.ts_code == "000001.SH")
.limit(1)
```

行为：

1. 返回只读 dataclass，不返回 ORM 实例到 service 层。
2. 找不到时返回 `None`，由 service 转换为 `TREND_CHANNEL_INSTRUMENT_MISSING`。
3. `name` 为空时响应名称使用固定产品兜底 `上证指数`；不得影响轨道计算。

### 6.3 `load_watermark()`

SQLAlchemy 语义：

```python
select(
    func.count(IndexDailyServing.trade_date),
    func.max(IndexDailyServing.trade_date),
    func.max(IndexDailyServing.updated_at),
).where(IndexDailyServing.ts_code == "000001.SH")
```

归一化规则：

1. `count` 转 `int`。
2. 空表时两个 `max` 为 `None`。
3. 不用 `created_at` 代替 `updated_at`。
4. 不读取 Ops freshness 或 TaskRun 作为业务数据水位。

### 6.4 `load_all_rows()`

```python
select(
    IndexDailyServing.trade_date,
    IndexDailyServing.open,
    IndexDailyServing.high,
    IndexDailyServing.low,
    IndexDailyServing.close,
    IndexDailyServing.updated_at,
)
.where(IndexDailyServing.ts_code == "000001.SH")
.order_by(IndexDailyServing.trade_date.asc())
```

约束：

1. 不接收 `limit`。
2. 不接收页面 `end_date`。
3. 不读取 `pre_close/vol/amount` 等未使用字段。
4. watermark `row_count > 10_000` 时在执行完整查询前拒绝。
5. 所有 SQLAlchemy 异常转换为查询层专用异常，禁止静默返回空数组。

查询层只定义一个基础异常，避免依赖上层 service：

```python
class QuoteTrendChannelQueryError(RuntimeError):
    pass
```

完整历史计算后按 `end_date` 切片仍满足因果性，因为递推只从过去指向未来；必须用前缀不变性测试证明同一日期不会被后续数据改变。

---

## 7. 纯计算内核

目标文件：`src/biz/services/quote_trend_channel_calculator.py`

### 7.1 常量

```python
FORMULA_KEY = "high-low-ema-hysteresis"
FORMULA_VERSION = "sse-daily-trend-channel-v1"
SHORT_PERIOD = 25
LONG_PERIOD = 90
SHORT_ALPHA = 2.0 / 26.0
LONG_ALPHA = 2.0 / 91.0
MAX_SOURCE_ROWS = 10_000
PRICE_QUANTUM = Decimal("0.0001")
```

周期不进入配置文件或环境变量。

calculator 内部另外定义与 Schema 同值、但不依赖 Pydantic 的类型别名：

```python
PositionValue = Literal["ABOVE", "INSIDE", "BELOW"]
StateValue = Literal["UNKNOWN", "UP", "DOWN"]
CombinedStateValue = Literal[
    "UNKNOWN",
    "UP_UP",
    "UP_DOWN",
    "DOWN_UP",
    "DOWN_DOWN",
]
```

### 7.2 输出数据类型

```python
@dataclass(frozen=True, slots=True)
class ComputedTrendChannelBand:
    upper_raw: float
    lower_raw: float
    upper: Decimal
    lower: Decimal
    position: PositionValue
    state: StateValue


@dataclass(frozen=True, slots=True)
class ComputedTrendChannelRow:
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    short_channel: ComputedTrendChannelBand
    long_channel: ComputedTrendChannelBand
    combined_state: CombinedStateValue
```

缓存对象只保存冻结 dataclass/tuple，不保存 ORM row、Session 或可变 Pydantic model。

### 7.3 校验顺序

`calculate(rows)` 必须先完整校验，再开始构造输出：

1. `len(rows) <= 10_000`。
2. `trade_date` 严格递增。
3. 不得出现重复日期。
4. OHLC 全部非空。
5. 转换为 `float` 后必须 `math.isfinite()`。
6. OHLC 全部大于 0。
7. `low <= min(open, close) <= max(open, close) <= high`。

内部 reason code：

```text
source_row_limit_exceeded
trade_date_not_strictly_ascending
duplicate_trade_date
missing_ohlc
non_finite_ohlc
non_positive_ohlc
invalid_ohlc_range
```

任何一行失败都拒绝整个序列，不允许跳过。

calculator 对外只抛出两种可识别异常：

```python
class TrendChannelInputError(ValueError):
    def __init__(self, *, reason_code: str, trade_date: date | None = None) -> None: ...


class TrendChannelInvariantError(RuntimeError):
    def __init__(self, *, reason_code: str, trade_date: date | None = None) -> None: ...
```

异常对象保存 reason code 和可选日期，不保存整行 payload。

### 7.4 EMA 与状态

核心循环：

```python
short_state = "UNKNOWN"
long_state = "UNKNOWN"

for index, row in enumerate(rows):
    if index == 0:
        short_upper = high
        short_lower = low
        long_upper = high
        long_lower = low
    else:
        short_upper = SHORT_ALPHA * high + (1.0 - SHORT_ALPHA) * short_upper
        short_lower = SHORT_ALPHA * low + (1.0 - SHORT_ALPHA) * short_lower
        long_upper = LONG_ALPHA * high + (1.0 - LONG_ALPHA) * long_upper
        long_lower = LONG_ALPHA * low + (1.0 - LONG_ALPHA) * long_lower

    if short_upper < short_lower:
        raise TrendChannelInvariantError(reason_code="short_channel_inverted", trade_date=row.trade_date)
    if long_upper < long_lower:
        raise TrendChannelInvariantError(reason_code="long_channel_inverted", trade_date=row.trade_date)

    short_position = locate(close, short_upper, short_lower)
    long_position = locate(close, long_upper, long_lower)
    short_state = transition(short_state, short_position)
    long_state = transition(long_state, long_position)
```

`locate()`：

```python
if close > upper:
    return "ABOVE"
if close < lower:
    return "BELOW"
return "INSIDE"
```

`transition()`：

```python
if position == "ABOVE":
    return "UP"
if position == "BELOW":
    return "DOWN"
return previous_state
```

### 7.5 量化

```python
def quantize_price(value: float) -> Decimal:
    return Decimal(str(value)).quantize(
        PRICE_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
```

严格顺序：

1. 用未量化 `float` 递推。
2. 用未量化轨道判断位置和状态。
3. 仅在构造输出行时量化。
4. 下一根递推继续使用未量化轨道。

禁止使用上一根四位小数输出继续计算。

---

## 8. 缓存与一致性

目标文件：`src/biz/services/quote_trend_channel_query_service.py`

### 8.1 缓存 key

```python
@dataclass(frozen=True, slots=True)
class TrendChannelCacheKey:
    source_identity: str
    ts_code: str
    formula_version: str
    row_count: int
    max_trade_date: date | None
    max_updated_at: datetime | None
```

`source_identity` 使用：

```python
bind = session.get_bind()
root_bind = getattr(bind, "engine", bind)
source_identity = f"{bind.dialect.name}:{id(root_bind)}"
```

目的：避免同一进程内不同测试 Engine 或不同数据库连接对象共享相同缓存。不得把数据库 URL 或凭据写入 key、日志或响应。

### 8.2 缓存值

```python
@dataclass(frozen=True, slots=True)
class TrendChannelSeries:
    watermark: TrendChannelWatermark
    rows: tuple[ComputedTrendChannelRow, ...]
```

### 8.3 缓存类

```python
class TrendChannelSeriesCache:
    def __init__(self, *, max_entries: int = 2) -> None: ...
    def get(self, key: TrendChannelCacheKey) -> TrendChannelSeries | None: ...
    def put(self, key: TrendChannelCacheKey, value: TrendChannelSeries) -> None: ...
    def clear(self) -> None: ...
    def compute_lock(self) -> ContextManager[None]: ...
```

实现要求：

1. 内部使用 `RLock`。
2. 使用 `OrderedDict` 或等价结构固定最多两个版本。
3. `get()` 命中后可提升为最近使用。
4. `put()` 原子替换，不暴露半成品。
5. `clear()` 供测试隔离和后续管理进程重载使用。
6. 缓存故障不得写数据库，也不得改变业务事务。

单例 provider：

```python
@lru_cache(maxsize=1)
def get_quote_trend_channel_cache() -> TrendChannelSeriesCache:
    return TrendChannelSeriesCache(max_entries=2)
```

该固定容量不是配置项，不新增 Settings/env/数据库配置。

### 8.4 水位一致性算法

不能只做一次“先查水位、再查历史”，因为两次 SQL 之间可能恰好发生正式日线发布。服务层必须执行：

```text
attempt 1:
  1. load watermark_before
  2. check cache(watermark_before)
  3. acquire compute lock
  4. load watermark_locked
  5. recheck cache(watermark_locked)
  6. load all rows
  7. load watermark_after
  8. watermark_locked == watermark_after
     且 len(rows) == row_count
     且最后一行日期 == max_trade_date
     且 rows 的最大 updated_at == max_updated_at:
       calculate -> atomic cache put -> return
     else:
       release lock -> retry

attempt 2:
  repeat once

still changing:
  raise TREND_CHANNEL_SOURCE_CHANGING
```

这样可以避免把新历史结果错误地存到旧水位 key 下。

空源是合法特例：`row_count=0` 时两个最大值和 rows 都必须为空，并缓存空 tuple。任何水位与实际行不一致都按“读取期间发生变化”重试，不进入 calculator。

### 8.5 多进程语义

每个 Web worker 拥有自己的小缓存。允许不同 worker 各计算一次，因为：

1. 只有一个序列。
2. 计算成本毫秒级。
3. 结果由相同数据水位和公式版本决定。
4. 进程重启丢缓存不影响正确性。

v1 不为共享缓存引入 Redis。

---

## 9. Query Service 编排

### 9.1 构造函数

```python
class QuoteTrendChannelQueryService:
    def __init__(
        self,
        *,
        query: QuoteTrendChannelQuery | None = None,
        calculator: TrendChannelCalculator | None = None,
        cache: TrendChannelSeriesCache | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        ...
```

显式注入点用于单元测试；生产默认值使用真实查询、计算器、缓存和上海时区当前时间。`cache is None` 时必须调用 `get_quote_trend_channel_cache()`，保证 route 每次创建 service 也会共享同一进程缓存。

### 9.2 `build_response()`

阶段边界：M2 先实现并测试 `load_instrument(session)` 与 `load_series(session)`，只返回查询层身份和一致水位的冻结完整序列；M3 新增独立 Schema 后再实现本节 `build_response()`、切片和 DTO 装配。M2 不提前依赖尚未存在的 Pydantic API 合同。

```python
def build_response(
    self,
    session: Session,
    *,
    end_date: date | None,
    limit: int,
) -> TrendChannelResponse:
    ...
```

步骤：

1. 查询 `IndexBasic` 身份。
2. 获取或构建一致水位的完整 `TrendChannelSeries`。
3. 使用 `bisect_right(trade_dates, effective_end_date)` 找到结束位置。
4. 从结束位置向前截取最多 `limit` 行。
5. 计算 `has_more_history`。
6. 若仍有更早历史，`next_end_date` 等于当前返回第一根之前的真实交易日。
7. 将冻结计算行映射为 Pydantic DTO。
8. 生成 `data_status` 和 `meta`。

### 9.3 切片规则

设完整序列为升序 `rows`：

```python
end_index = bisect_right(trade_dates, end_date_or_latest)
start_index = max(0, end_index - limit)
selected = rows[start_index:end_index]
has_more_history = start_index > 0
next_end_date = rows[start_index - 1].trade_date if has_more_history else None
```

响应保持日期升序。

### 9.4 数据状态

| 情况 | `status` | `observed_trade_date` | `bars` |
| --- | --- | --- | --- |
| 有返回行 | `READY` | 完整源最大交易日 | 非空 |
| 源无日线 | `EMPTY` | `None` | `[]` |
| `end_date` 早于最早日线 | `EMPTY` | 完整源最大交易日 | `[]` |

即使请求历史窗口，`observed_trade_date` 仍表示当前源水位，不伪装成请求窗口结束日。

### 9.5 Service 边界异常

query service 将底层异常归一化为 API 可稳定识别的类型：

```python
class TrendChannelInstrumentMissingError(RuntimeError): ...
class TrendChannelSourceUnavailableError(RuntimeError): ...
class TrendChannelSourceInvalidError(RuntimeError): ...
class TrendChannelSourceChangingError(RuntimeError): ...
class TrendChannelComputeError(RuntimeError): ...
```

映射规则：

| 底层情况 | Service 异常 |
| --- | --- |
| `IndexBasic` 返回空 | `TrendChannelInstrumentMissingError` |
| `QuoteTrendChannelQueryError` | `TrendChannelSourceUnavailableError` |
| `TrendChannelInputError` | `TrendChannelSourceInvalidError` |
| 两次水位都变化 | `TrendChannelSourceChangingError` |
| `TrendChannelInvariantError` | `TrendChannelComputeError` |

禁止把编程错误、类型错误等未预期异常降级成 200 EMPTY。

---

## 10. API 层实现

`src/biz/api/quote.py` 只新增：

1. `TrendChannelResponse` import。
2. `QuoteTrendChannelQueryService` 及专用异常 import。
3. `get_quote_detail_trend_channel()` route。

不得修改现有常量：

- `SUPPORTED_PERIODS`
- `SUPPORTED_ADJUSTMENTS`
- `UNSUPPORTED_MINUTE_PERIODS`

不得修改现有 `get_quote_detail_kline()`。

API 错误捕获必须按专用异常类型映射，不使用 `except Exception` 把所有错误伪装成同一个 400。

---

## 11. 日志与可观测性

本能力不创建 TaskRun、snapshot 或 freshness 状态。

服务日志至少包含：

| 字段 | 说明 |
| --- | --- |
| `event` | `trend_channel_cache_hit/cache_miss/rebuild_failed` |
| `formula_version` | 固定 v1 |
| `ts_code` | 固定 `000001.SH` |
| `row_count` | 水位行数 |
| `max_trade_date` | 水位日期 |
| `elapsed_ms` | 完整重算耗时 |
| `reason_code` | 失败原因，不含完整行内容 |

不记录：

- 数据库 URL 或凭据；
- 整段历史数据；
- 用户认证信息；
- 每次 EMA 中间数组。

日志失败不得影响 API 正常读取或业务数据事务。

---

## 12. 测试详细设计

### 12.1 纯计算测试

目标：`tests/test_quote_trend_channel_calculator.py`

| 测试 | 正向/负向 | 断言 |
| --- | --- | --- |
| 首根种子 | 正向 | 上下轨等于首根 high/low，状态 UNKNOWN |
| 两根手算 | 正向 | 25/90 alpha 递推值误差 `< 1e-8` |
| 上破 | 正向 | position ABOVE，state UP |
| 内部保留 UP | 正向 | position INSIDE，state 仍 UP |
| 下破 | 正向 | position BELOW，state DOWN |
| 内部保留 DOWN | 正向 | position INSIDE，state 仍 DOWN |
| 边界相等 | 负向门禁 | 等于上/下轨不能触发切换 |
| 量化不递推 | 负向门禁 | 与“每日先量化”的错误实现不同 |
| 前缀不变性 | 正向 | 追加未来行不改变历史输出 |
| 不同 limit 一致 | 正向 | 同一日期通道值一致 |
| 重复日期 | 负向 | reason `duplicate_trade_date` |
| 无序日期 | 负向 | reason `trade_date_not_strictly_ascending` |
| 空/NaN/Infinity | 负向 | 对应 reason code |
| 非法 OHLC | 负向 | 整序列拒绝 |
| 10,001 行 | 负向 | 超量拒绝 |

### 12.2 独立参考金标

金标要求：

1. 从固定 `000001.SH` 日线快照生成。
2. 参考生成器不得 import 生产 calculator。
3. 至少覆盖首根、首次 UP、首次 DOWN、短期/长期分化和 2026-08-07。
4. 保存未量化轨道、四位输出、position、state 和 combined_state。
5. 生产结果逐日期对账。

固定文件：

1. `tests/fixtures/quote_trend_channel/000001_sh_daily_input.json`：保存截至 2026-08-07 的完整正式日线 OHLC，不保存页面窗口截断结果。
2. `tests/fixtures/quote_trend_channel/000001_sh_daily_expected_v1.json`：保存与输入文件 SHA-256 绑定的逐日金标。
3. 参考主算法使用 pandas `ewm(span=period, adjust=False)`，并以独立显式 `float64` 递推逐行交叉校验；两者最大绝对误差必须 `< 1e-8`。
4. 两个 JSON 均为测试事实文件，不进入运行时 API、数据库、Lake 或配置加载路径。

### 12.3 查询与缓存测试

目标：`tests/test_quote_trend_channel_query_service.py`

使用 fake query/calculator 验证：

1. 相同水位第二次不调用 `load_all_rows()`。
2. 新交易日、行数变化、`updated_at` 变化分别触发重算。
3. 缓存 key 包含 Engine identity，不跨测试数据库串数据。
4. 两个并发请求同水位只执行一次计算。
5. 第一次前后水位不同会重试。
6. 两次都变化会返回 `TREND_CHANNEL_SOURCE_CHANGING`。
7. `clear()` 后重新计算但结果一致。
8. 最多保留两个水位版本。

### 12.4 Web API 测试

目标：`tests/web/test_quote_trend_channel_api.py`

准备表：

- `IndexBasic.__table__`
- `IndexDailyServing.__table__`

每个测试前后清理专用进程缓存，避免全局状态泄漏。

必须覆盖：

1. `000001.SH + day` 返回 200。
2. Decimal JSON 为四位字符串。
3. `position` 与 `state` 同时存在。
4. 所有行 `is_provisional=false`。
5. `limit=1` 与 `limit=2` 的共同日期轨道一致。
6. `end_date` 截断正确。
7. `next_end_date` 是真实上一交易日。
8. 其他指数返回指定 400 code。
9. 周/月/分钟周期返回指定 400 code。
10. 空源返回 200 EMPTY。
11. 坏行返回 503，而不是跳过。
12. 缺失 IndexBasic 返回 503。
13. `QUOTE_API_AUTH_REQUIRED=true` 时无登录返回既有 `auth_required`。

### 12.5 回归测试

必须继续执行：

```text
tests/web/test_quote_api.py
tests/architecture/test_subsystem_dependency_matrix.py
tests/architecture/test_platform_legacy_guardrails.py
tests/architecture/test_operations_legacy_guardrails.py
```

回归断言：

1. `/api/v1/quote/detail/kline` 响应字段不增加通道字段。
2. 股票、指数、ETF 原有查询行为不变。
3. app router 不需要新 include。

---

## 13. 性能验收

### 13.1 基准场景

| 场景 | 输入 | 次数 | 指标 |
| --- | ---: | ---: | --- |
| 纯内核 | 1,000 行 | 至少 100 次热身后 1,000 次 | median/P95/max |
| 冷 API | 当前完整日线 | 至少 30 次，每次清缓存 | P50/P95 |
| 热 API | 当前完整日线 | 至少 100 次 | P50/P95 |
| 并发冷启动 | 10 个并发请求 | 至少 10 轮 | 重算次数与延迟 |

### 13.2 门禁

```text
纯内核 1,000 行 P95 < 10ms
冷 API P95 < 500ms
热 API P95 < 100ms
缓存结果内存 < 10MB
同一水位并发重算次数 = 1
```

基准必须区分：

- DB 水位查询耗时；
- 完整历史读取耗时；
- calculator 耗时；
- DTO/JSON 序列化耗时。

不得只报告总耗时而无法定位瓶颈。

---

## 14. 开发执行顺序

### M0：金标与测试先行

1. 固定原始 OHLC 快照。
2. 独立生成 v1 金标。
3. 先写 calculator 正向与负向测试。

门禁：没有独立金标，不开始 API 开发。

### M1：纯 calculator

1. 实现 dataclass、校验、EMA、position、state、combined state、量化。
2. 运行纯单元测试和性能基准。

门禁：前缀不变性、窗口不变性和坏行失败关闭必须通过。

### M2：Query 与缓存

1. 实现身份、水位、完整历史查询。
2. 实现两次水位一致性保护。
3. 实现有限缓存和并发单飞。

门禁：缓存失效与并发测试通过。

### M3：Schema 与 API

1. 实现独立 schema。
2. 在现有 quote router 新增 route。
3. 完成错误映射和鉴权测试。

门禁：共享 K 线合同 diff 为零。

### M4：真实数据只读验收

1. 在明确授权的环境读取 `000001.SH` 正式日线。
2. 对账源行数、最早/最晚日期、坏行数和金标日期。
3. 执行冷/热 API 与并发性能基准。

门禁：本阶段只读，不执行生产写入、迁移或任务调度。

2026-08-10 已生成 M4 只读验收证据：[上证指数日线趋势通道 M4 只读与性能验收报告](./sse-daily-trend-channel-m4-readonly-performance-validation-2026-08-10.md)。正式数据、金标、计算、缓存内存和并发单飞已通过；同机正式数据快照的冷/热 API 已通过。生产 Web 与生产 PostgreSQL 实际拓扑的最终冷/热 API P95 验收已完成。

### M5：前端接入，另立范围

前端通道 band、颜色和 tooltip 不属于本 LLD 的后端开发轮次。后续接入必须只消费独立 API，不在浏览器重复计算。

---

## 15. 验证命令

开发完成后按顺序执行：

```bash
pytest -q tests/test_quote_trend_channel_calculator.py
pytest -q tests/web/test_quote_trend_channel_api.py
pytest -q tests/web/test_quote_api.py
pytest -q tests/architecture/test_subsystem_dependency_matrix.py
pytest -q tests/architecture/test_platform_legacy_guardrails.py
pytest -q tests/architecture/test_operations_legacy_guardrails.py
python3 scripts/check_docs_integrity.py
```

真实数据只读验收和生产发布仍是单独授权门禁，不能由本 LLD 自动执行。

---

## 16. 配置、迁移和发布审计

### 16.1 配置

新增配置项：无。

固定内部常量：

| 常量 | 值 | 来源 | 生效方式 |
| --- | --- | --- | --- |
| `SUPPORTED_TS_CODE` | `000001.SH` | 已拍板产品范围 | 发版 |
| `SHORT_PERIOD` | `25` | 已拍板公式 | 发版 |
| `LONG_PERIOD` | `90` | 已拍板公式 | 发版 |
| `FORMULA_VERSION` | `sse-daily-trend-channel-v1` | 版本合同 | 发版 |
| `MAX_SOURCE_ROWS` | `10_000` | 性能安全门禁 | 发版 |
| cache entries | `2` | 单序列双水位保护 | 进程启动 |

这些常量不暴露为运营或用户配置。

### 16.2 数据库

```text
新增表：无
修改表：无
新增索引：无
Alembic migration：无
数据写入：无
```

### 16.3 Lake/Dagster/Ops

```text
DatasetDefinition：无
DatasetExecutionPlan：无
Dagster asset/job/sensor/schedule：无
Lake 文件：无
TaskRun/freshness/snapshot：无
```

### 16.4 部署

后续代码实现只需要普通 Web 服务发版。进程缓存随 worker 重启自动清空，第一笔请求重建。

---

## 17. 失败模式

| 失败 | 对外行为 | 内部处置 |
| --- | --- | --- |
| 数据库不可用 | 503 | 日志记录 source unavailable |
| IndexBasic 缺失 | 503 | 不硬编码成正常 READY |
| 日线为空 | 200 EMPTY | 缓存空序列水位 |
| 一根坏行 | 503 | 整序列失败关闭 |
| 历史修订 | 下一请求重算 | `max(updated_at)` 改变 |
| 删除历史行 | 下一请求重算 | `row_count` 改变 |
| 新增交易日 | 下一请求重算 | row_count/max date 改变 |
| 公式升级 | 新 key 重算 | version 改变 |
| 进程重启 | 首请求冷启动 | 不影响结果 |
| 缓存内部异常 | 500/受控日志 | 不写业务表 |
| 连续水位变化 | 503 | 最多重试一次，防止不一致发布 |

---

## 18. 验收清单

### 18.1 代码范围

- [ ] 只新增/修改第 4.1 节文件。
- [ ] 未修改共享 K 线 schema/query。
- [ ] 未修改 foundation 模型和数据库迁移。
- [ ] 未修改 Lake/Dagster/Ops。

### 18.2 计算正确性

- [ ] 25/90、首值种子和 `adjust=False` 完全一致。
- [ ] position 与 state 同时返回。
- [ ] INSIDE 保留上一状态。
- [ ] 未量化值参与递推与判断。
- [ ] 前缀不变性和不同 limit 一致性通过。
- [ ] 独立金标逐日期通过。

### 18.3 API

- [ ] 路径为 `/api/v1/quote/detail/trend-channel`。
- [ ] 只支持 `000001.SH + day`。
- [ ] Decimal 是四位字符串。
- [ ] 所有行 `is_provisional=false`。
- [ ] 错误进入统一 `code/message/request_id` 合同。
- [ ] 原 `/detail/kline` 合同不变。

### 18.4 性能与稳定性

- [x] 水位不变不查完整历史。
- [x] 水位变化自动重算。
- [x] 并发只重算一次。
- [x] 1,000 行纯内核 P95 达标。
- [x] 同机正式数据快照的冷/热 API P95 达标。
- [x] 部署后生产 Web 与生产 PostgreSQL 实际拓扑的冷/热 API P95 达标。
- [x] 缓存清空不影响结果。

---

## 19. 工程证据归档要求

拍板项已经清零，没有产品口径阻塞。以下工程证据应随实现与验收记录持续归档：

1. 固定历史快照及独立金标文件。
2. 当前真实日线行数、最早/最晚日期与坏行统计。
3. 1,000 行 calculator benchmark。
4. 冷/热 API 和并发单飞 benchmark。
5. 共享 K 线 API 回归结果。

这些是验收证据，不是重新讨论 D01～D12 的理由。
