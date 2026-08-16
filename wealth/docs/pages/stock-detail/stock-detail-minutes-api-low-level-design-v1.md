# 股票详情分钟线与分钟技术指标 API LLD v1.8

> 2026-08-13 数据合同修正：reader 的 Gold-only 边界不变，但正式 Gold QFQ
> 5m/15m/30m/60m 与对应 MACD/KDJ/state 必须按
> [A 股分钟线 Gold 标准 K 线合同与历史重建 LLD](../../../../lake_console/docs/design/dagster-cn-a-minute-gold-canonical-bars-rebuild-low-level-design.md)
> 全历史重建。Gold 1m 保留 09:30，非 1m 禁止独立 09:30；API 必须严格按时间键对齐
> bars/indicators，不得在读取层过滤错误数据来伪装修复。七频均不得展示 `15:01-15:30`，
> 完整交易日最后一根必须精确为 15:00，技术指标和递推 state 同样截止 15:00。

> 方案：[分钟 API 技术实施方案](./stock-detail-minutes-api-implementation-design-v1.md)
> 需求：[分钟 API 标杆需求](./stock-detail-minutes-api-benchmark-requirement-v1.md)
> 门禁：[分钟 API 编码前门禁](./stock-detail-minutes-api-m2-coding-gate-v1.md)
> 当前图表状态：股票分钟已由 `b38ac20e` 迁入 `DetailChartWorkspace`，并由 `61a5adea` 启用统一自适应缩放；本 API、500 根缓冲和本地/生产隔离合同未改变。

## 1. 目标、边界与硬约束

本 LLD 设计本地 `wealth` 股票详情页的分钟线和分钟 MACD/KDJ 只读查询能力。它不改变 Lake 写入链路、不改变 Dagster、不向远程生产发布本地分钟数据。

```text
wealth 5173
  -> local src/app/web 8000
  -> /api/v1/wealth/market/stock-detail/minutes
  -> src/foundation/clients/local_lake/stock_mins_reader.py
  -> DuckDB read_parquet(Gold qfq files)
```

硬约束：

1. 本地 API 只读 Gold Parquet，不读取 raw/silver，不读取 Dagster event history。
2. API 请求不触发 Dagster、sensor、repair、materialization，不写 Lake 或数据库。
3. 远程 prod 不挂载分钟路由，不加载 DuckDB，不读取本地 Lake。
4. `freq` 必须显式传入，允许 `1/5/15/30/60/90/120`。
5. 默认每次返回 500 根，完整历史通过 cursor 分页；500 根不是 300 个交易日窗口。
6. 分钟 Gold 没有 `pre_close/change/pct_chg`，首版不返回、不推导、不伪造。
7. 指标 NULL 保持 NULL，不转成 0。

## 2. 真实代码审计结论

| 当前代码 | 现状 | 本次落点 |
|---|---|---|
| `src/app/api/v1/router.py` | 静态导入现有 wealth routers | 保留既有路由，分钟 router 条件延迟装配 |
| `src/foundation/config/settings.py` | 没有本地 Lake/DuckDB 配置 | 增加两个 Settings 字段 |
| `src/biz/api/wealth/market/stock_detail.py` | 已有 page-init/kline 日线接口 | 不改变日线接口；只补 capability 字段 |
| `src/biz/queries/wealth/market/stock_detail/` | 通过 SQLAlchemy 查询日线 serving 表 | 不复用为分钟查询 |
| `wealth/src/pages/stock-detail/StockDetailPage.tsx` | 初次请求 300 根日 K | 保留日线请求；分钟切换新增独立请求状态 |
| `wealth/src/features/stock-detail/chart/StockChartWorkspace.tsx` | 已消费 shared；当前 1600px 默认可视 120 根 | 与股票分钟、指数日线、指数分钟共享 viewport 与缩放合同 |
| `wealth/src/features/stock-detail/api/stockDetailViewModelAdapter.ts` | `valueOrZero()` 把 NULL 转 0 | 分钟 adapter 不复用该函数 |
| `pyproject.toml` | 没有 DuckDB | 增加 `local-lake` optional extra，远程不安装 |
| `lake_console/backend` | 独立本地 Lake 管理台 | 不导入、不挂载、不改动 |

当前 Gold 合同已核对：

- 分钟线：`gold/quote/stk_mins_qfq/freq={freq}/ts_code={ts_code}/year={year}/part-000.parquet`
- 指标：`gold/indicator/stk_mins_qfq_macd_kdj/freq={freq}/ts_code={ts_code}/year={year}/part-000.parquet`
- `freq` 为整数 `1/5/15/30/60/90/120`。
- `trade_date` 为 DATE，`trade_time` 为 TIMESTAMP。

## 3. 依赖、配置与部署隔离

### 3.1 pyproject optional extra

在根 `pyproject.toml` 增加：

```toml
[project.optional-dependencies]
dev = [
  "httpx>=0.28.1",
  "pytest>=8.3.0",
  "pytest-mock>=3.14.0",
]
local-lake = [
  "duckdb>=1.3,<2",
]
```

实施要求：

1. 本地执行 `uv sync --extra local-lake`。
2. 远程构建执行普通依赖安装，不得使用 `--all-extras`，不安装 `local-lake`。
3. 依赖变更后执行 `uv lock`，提交 lock 变更；本轮文档阶段不执行安装。
4. 生产代码顶层不得 `import duckdb`；reader 只在本地路由已启用后延迟导入。

### 3.2 Settings

修改 `src/foundation/config/settings.py`：

```python
wealth_local_lake_minute_api_enabled: bool = Field(
    default=False,
    alias="WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED",
)
goldenshare_lake_root: str = Field(
    default="",
    alias="GOLDENSHARE_LAKE_ROOT",
)
```

不增加 `DEFAULT_LIMIT`、`MAX_LIMIT` 等环境变量，避免性能门禁散落在配置中。以下为代码常量：

```python
SUPPORTED_MINUTE_FREQS = (1, 5, 15, 30, 60, 90, 120)
DEFAULT_MINUTE_LIMIT = 500
MAX_MINUTE_LIMIT = 10_000
MAX_YEAR_FILE_COUNT = 3
MAX_RESPONSE_BYTES = 5_000_000
```

前端不再定义 `DEFAULT_VISIBLE_MINUTE_BARS`。2026-07-31 的 90 根是历史实现基线；当前由 `detailChartViewport.ts` 唯一定义 45/180/15、120、75～150 和 9.5px/根。Reader/API 常量保持不变，不把前端可视根数转成环境变量或后端参数。

配置生效矩阵：

| 条件 | 结果 |
|---|---|
| `APP_ENV=prod/production/staging` | 分钟能力 false，不 import reader，不挂路由 |
| `APP_ENV=dev/local` 且 flag false | 分钟能力 false，不 import reader，不挂路由 |
| `APP_ENV=dev/local` 且 flag true、root 空 | 启动 fail fast，错误 `SM_LOCAL_LAKE_NOT_CONFIGURED` |
| `APP_ENV=dev/local` 且 flag true、root 不可读 | 启动 fail fast |
| 前三项通过但 `duckdb` 不可导入 | 启动 fail fast |
| 全部通过 | 挂载分钟路由，page-init 宣布七种频率可用 |

新增 `src/foundation/config/local_minute_capability.py`：

```python
@dataclass(frozen=True)
class LocalMinuteCapability:
    enabled: bool
    lake_root: Path | None
    reason_code: str | None

def resolve_local_minute_capability(settings: Settings) -> LocalMinuteCapability: ...
```

该模块只检查环境、路径和 optional dependency，不导入业务 API，不扫描 Lake 文件。`duckdb` 导入只在 `APP_ENV=dev/local` 且 flag 为 true 的分支执行。

## 4. Router 与 page-init 装配

### 4.1 `/api/v1` router

修改 `src/app/api/v1/router.py`，保持导出的 `router` 对象和既有 include 顺序。新增尾部装配函数：

```python
def _include_local_minute_router(router: APIRouter) -> None:
    settings = get_settings()
    capability = resolve_local_minute_capability(settings)
    if capability.enabled:
        from src.biz.api.wealth.market import stock_detail_minutes

        router.include_router(stock_detail_minutes.router)

_include_local_minute_router(router)
```

实际实现允许改为 `build_v1_router(settings)`，但必须满足：

1. 远程 profile 不 import `stock_detail_minutes`。
2. 远程 profile 不 import `StockMinsLakeReader` 或 DuckDB。
3. 远程直接访问分钟路径得到 404，不是 503、空数据或 delayed。
4. local flag/root/dependency 缺失时不静默降级，按配置矩阵 fail fast。

### 4.2 page-init capability

修改现有 `StockDetailCapabilitiesDto`，增加：

```python
minuteFrequencies: list[Literal[1, 5, 15, 30, 60, 90, 120]]
```

后端输出：

- 本地 capability true：`supportsMinute=true`，`minuteFrequencies=[1,5,15,30,60,90,120]`。
- 远程或未启用：`supportsMinute=false`，`minuteFrequencies=[]`。

`StockDetailQueryService.build_page_init()` 只读取 capability resolver，不扫描 Lake，不以当天数据是否存在决定能力。

这是对现有 page-init 的向后兼容新增字段；日线的 `chartDefaults`、quote、pageContext 和 kline 契约不变。

## 5. API 合同

### 5.1 路由

新增 `src/biz/api/wealth/market/stock_detail_minutes.py`：

```http
GET /api/v1/wealth/market/stock-detail/minutes
GET /api/v1/wealth/market/stock-detail/minute-indicators
```

两个路由都依赖 `require_quote_access`。API 层不创建 DuckDB connection，不解析文件路径，不执行 SQL。

### 5.2 参数

```python
ts_code: str = Query(alias="tsCode")
freq: int = Query()  # 无 default，必须显式传入
start_date: date | None = Query(default=None, alias="startDate")
end_date: date | None = Query(default=None, alias="endDate")
limit: int = Query(default=500, ge=1, le=10_000)
cursor: str | None = Query(default=None)
debug: int = Query(default=0, ge=0, le=1)
```

参数校验顺序：

1. `tsCode.strip().upper()` 后匹配 `^[0-9]{6}\.(SZ|SH|BJ)$`。
2. `freq` 必须属于 `SUPPORTED_MINUTE_FREQS`。
3. `startDate > endDate` 返回 400。
4. 显式日期区间跨越超过 3 个自然年返回 400；不允许静默截断。
5. cursor 非法、版本不支持、绑定的代码/频率/日期范围不一致返回 400。
6. `limit > 10_000` 由 FastAPI 参数层拒绝。

### 5.3 默认日期与 500 根窗口

`StockMinuteQueryService` 的 `_resolve_request_window()` 固定如下：

| 输入 | 实际查询范围 |
|---|---|
| `endDate` 有值 | 使用该日期作为包含上界 |
| `endDate` 为空 | 使用北京时间当天作为查询上界，但不把它当作页面 expected trade date |
| `startDate` 有值 | 使用该日期作为包含下界 |
| `startDate` 为空 | 不设下界，倒序取最近一页 |
| 两个日期都为空 | 当前年份向前最多 3 年文件，倒序取最近 500 根 |

因此默认请求的语义是“最近 500 根”，不是“最近 300 个交易日”。前端从 page-init 获得页面交易日后，必须显式把 `endDate=pageContext.tradeDate` 传给分钟接口，这样页面状态可以准确判断是否 delayed。

v1 不新增独立的 `expectedEndDate` 请求参数：`endDate` 同时是查询包含上界和调用方期望数据截至日。实现必须遵守：

1. 页面请求必须传 `endDate=pageContext.tradeDate`，用它建立 `DELAYED` 判断基准。
2. `endDate` 省略时，服务层的 `expected_end_date` 为 `None`；不能因为当前没有最新分钟文件就擅自返回 `DELAYED`，无行结果按 `EMPTY` 返回。
3. `endDate` 显式传入但结果为空，或 observed end 早于 `endDate`，统一返回 `200 + dataStatus=DELAYED`。
4. 后端不得把“当前北京时间”当成页面期望交易日；当前时间只用于无 `endDate` 时限制查询上界。

### 5.4 响应 DTO

新增 `src/biz/schemas/wealth/market/stock_detail_minutes.py`：

```python
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class MinutePageMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    count: int
    limit: int
    has_more: bool = Field(alias="hasMore")
    next_cursor: str | None = Field(default=None, alias="nextCursor")
    start_date: date | None = Field(default=None, alias="startDate")
    end_date: date | None = Field(default=None, alias="endDate")
    observed_start_date: date | None = Field(default=None, alias="observedStartDate")
    observed_end_date: date | None = Field(default=None, alias="observedEndDate")

class MinuteDataStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: Literal["READY", "DELAYED", "EMPTY", "ERROR"]
    expected_end_date: date | None = Field(default=None, alias="expectedEndDate")
    observed_end_date: date | None = Field(default=None, alias="observedEndDate")
    message: str | None = None


MinuteFrequency = Literal[1, 5, 15, 30, 60, 90, 120]


class StockMinuteBarDto(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ts_code: str = Field(alias="tsCode")
    freq: MinuteFrequency
    trade_date: date = Field(alias="tradeDate")
    trade_time: datetime = Field(alias="tradeTime")
    open: float
    high: float
    low: float
    close: float
    vol: float
    amount: float
    exchange: str


class StockMinuteIndicatorDto(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ts_code: str = Field(alias="tsCode")
    freq: MinuteFrequency
    trade_date: date = Field(alias="tradeDate")
    trade_time: datetime = Field(alias="tradeTime")
    macd_dif: float | None = Field(default=None, alias="macdDif")
    macd_dea: float | None = Field(default=None, alias="macdDea")
    macd: float | None = None
    kdj_k: float | None = Field(default=None, alias="kdjK")
    kdj_d: float | None = Field(default=None, alias="kdjD")
    kdj_j: float | None = Field(default=None, alias="kdjJ")
    params_key: str = Field(alias="paramsKey")
    indicator_version: int = Field(alias="indicatorVersion")
```

分钟线响应：

```python
class StockMinutesResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ts_code: str = Field(alias="tsCode")
    freq: MinuteFrequency
    bars: list[StockMinuteBarDto]
    meta: MinutePageMeta
    data_status: MinuteDataStatus = Field(alias="dataStatus")
    debug_info: dict[str, Any] | None = Field(default=None, alias="debugInfo")
```

指标响应不能使用动态字段替换，必须显式定义独立 DTO：

```python
class StockMinuteIndicatorsResponseDto(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ts_code: str = Field(alias="tsCode")
    freq: MinuteFrequency
    items: list[StockMinuteIndicatorDto]
    meta: MinutePageMeta
    data_status: MinuteDataStatus = Field(alias="dataStatus")
    debug_info: dict[str, Any] | None = Field(default=None, alias="debugInfo")
```

`StockMinuteBarDto` 字段固定为：`tsCode/freq/tradeDate/tradeTime/open/high/low/close/vol/amount/exchange`。

`StockMinuteIndicatorDto` 字段固定为：`tsCode/freq/tradeDate/tradeTime/macdDif/macdDea/macd/kdjK/kdjD/kdjJ/paramsKey/indicatorVersion`，指标数值全部允许 NULL。

指标字段映射必须显式实现：

```text
macd_dif_qfq      -> macdDif
macd_dea_qfq      -> macdDea
macd_qfq          -> macd
kdj_k_qfq         -> kdjK
kdj_d_qfq         -> kdjD
kdj_qfq           -> kdjJ
params_key        -> paramsKey
indicator_version -> indicatorVersion
```

`tradeTime` 的 JSON 格式固定为带北京时区偏移的 ISO 字符串，例如 `2026-07-31T09:35:00+08:00`。Lake 的 naive TIMESTAMP 解释为 `Asia/Shanghai`，不得按 UTC 重新解释。

### 5.5 状态矩阵

| 条件 | HTTP | `dataStatus` |
|---|---:|---|
| 文件存在、有行、范围内最新日期达到 expected end | 200 | READY |
| 有行但最新日期早于显式 `endDate` | 200 | DELAYED |
| 请求合法、`endDate` 省略、范围无行 | 200 | EMPTY |
| `endDate` 已给出但文件尚未生成或结果为空 | 200 | DELAYED，bars/items 为空 |
| schema、主键、时间键或频率契约错误 | 503 | ERROR |
| DuckDB/IO 异常 | 503 | ERROR |
| 参数、cursor、limit 不合法 | 400 | 不返回业务数据 |

`SM_*` 异常码不作为普通用户主展示字段。`debug=1` 时写入 `debugInfo.exceptions[]`；400/503 的 `WebAppError` body 使用注册表中的 code。

## 6. Lake Reader 代码级设计

### 6.1 文件落点与公开接口

新增 `src/foundation/clients/local_lake/stock_mins_reader.py`：

```python
class StockMinsLakeReader:
    def __init__(self, lake_root: Path): ...

    def read_bars(self, request: MinuteReadRequest) -> MinuteReadPage: ...
    def read_indicators(self, request: MinuteReadRequest) -> MinuteReadPage: ...
```

新增内部类型：

```python
@dataclass(frozen=True)
class MinuteReadRequest:
    ts_code: str
    freq: int
    start_date: date | None
    end_date: date | None
    limit: int
    cursor: str | None

@dataclass(frozen=True)
class MinuteReadPage:
    rows: tuple[dict[str, Any], ...]
    count: int
    has_more: bool
    next_cursor: str | None
    observed_start_date: date | None
    observed_end_date: date | None
    scanned_file_count: int
    elapsed_ms: float
```

### 6.2 路径安全

内部函数：

```python
build_stock_mins_qfq_paths(
    lake_root: Path,
    dataset: Literal["bars", "indicators"],
    ts_code: str,
    freq: int,
    years: Sequence[int],
) -> tuple[Path, ...]
```

规则：

1. 代码只使用正则校验后的 `ts_code`。
2. `freq`、`year` 只来自已校验值，不接受用户原始路径片段。
3. `Path.resolve()` 后每个目标必须满足 `target.is_relative_to(root)`。
4. 只返回存在且为普通文件的 `part-000.parquet`。
5. 目标年份数量超过 3 立即抛出 `MinuteRequestError`。
6. 不把 root、文件路径或 SQL 暴露为请求参数。

### 6.3 schema 校验

用 DuckDB `parquet_schema()` 做 metadata-only 校验，不使用 `SELECT *` 作为业务查询。校验每个目标文件的列名和类型集合必须等于：

```text
bars:
ts_code VARCHAR, freq INTEGER, trade_date DATE, trade_time TIMESTAMP,
open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
vol DOUBLE, amount DOUBLE, exchange VARCHAR

indicators:
ts_code VARCHAR, freq INTEGER, trade_date DATE, trade_time TIMESTAMP,
macd_dif_qfq DOUBLE, macd_dea_qfq DOUBLE, macd_qfq DOUBLE,
kdj_k_qfq DOUBLE, kdj_d_qfq DOUBLE, kdj_qfq DOUBLE,
params_key VARCHAR, indicator_version INTEGER
```

列缺失、类型不匹配或同一请求涉及的文件 schema 不一致，抛出 `SM_SOURCE_CONTRACT_INVALID`。额外列不参与 API 投影，但若源合同要求 exact schema，则在 schema audit 中报告；HTTP 查询不读取额外列。

### 6.4 cursor

cursor 使用 URL-safe base64 编码的 JSON，外部不依赖内部字段：

```json
{
  "v": 1,
  "dataset": "bars",
  "tsCode": "000638.SZ",
  "freq": 5,
  "startDate": null,
  "endDate": "2026-07-31",
  "beforeTradeDate": "2026-07-28",
  "beforeTradeTime": "14:55:00"
}
```

分页方向固定为“向更早数据翻页”：

1. 首页按 `trade_date DESC, trade_time DESC` 查询 `limit + 1` 行。
2. 返回前反转为升序。
3. 有额外行时，以当前页最早一行生成 `beforeTradeDate/beforeTradeTime`。
4. 下一页增加 `(trade_date, trade_time) < (:before_date, :before_time)`。
5. cursor 必须匹配 dataset、code、freq、startDate、endDate；不匹配返回 400。
6. 不使用 OFFSET，不扫描已经返回的历史页。

### 6.5 DuckDB 查询

每个 `read_bars/read_indicators` 调用只建立一个 `duckdb.connect(":memory:")`，使用 `try/finally` 关闭。路径由内部 helper 生成并安全转义，不接受用户 SQL。

业务查询结构固定为：

```sql
SELECT
  ts_code, freq, trade_date, trade_time,
  open, high, low, close, vol, amount, exchange
FROM read_parquet([
  '<validated-year-file-1>',
  '<validated-year-file-2>'
], hive_partitioning=false, union_by_name=false)
WHERE ts_code = ?
  AND CAST(freq AS INTEGER) = ?
  AND (? IS NULL OR trade_date >= CAST(? AS DATE))
  AND (? IS NULL OR trade_date <= CAST(? AS DATE))
  AND (
    ? IS NULL OR
    (trade_date, trade_time) < (CAST(? AS DATE), CAST(? AS TIMESTAMP))
  )
ORDER BY trade_date DESC, trade_time DESC
LIMIT ?
```

指标查询只替换显式投影字段，其余过滤、排序、分页完全一致。实际实现可以将 nullable predicate 在 Python 中分支生成，以避免 DuckDB 对 NULL 参数的类型推导问题，但不得改变过滤语义。

执行后必须 set-based 检查：

1. 返回行的 `ts_code`、`freq` 与请求一致。
2. `trade_date` 在请求区间内。
3. `(trade_date, trade_time)` 没有重复且按最终返回顺序严格递增。
4. `count <= limit`。
5. indicators 的 `params_key`、`indicator_version` 在单次结果中不出现冲突。

### 6.6 数据体积门禁

默认 500 根必须在性能 fixture 中通过 5MB 响应体门禁。显式大 limit 查询在 DTO 序列化前计算 UTF-8 body bytes：

1. `<= 5MB`：正常返回。
2. `> 5MB`：返回 400 `SM_REQUEST_INVALID`，提示降低 limit 或使用 cursor；不自动截断、不提高 timeout。
3. 500 根若超过 5MB，视为实现不通过，必须优化字段/查询或重新评审契约。

## 7. Backend API、Query Service 与异常

### 7.1 文件落点

```text
src/biz/api/wealth/market/stock_detail_minutes.py
src/biz/queries/wealth/market/stock_detail_minutes/
  __init__.py
  stock_detail_minutes_query.py
  stock_detail_minutes_query_service.py
src/biz/schemas/wealth/market/stock_detail_minutes.py
```

### 7.2 API 层职责

`stock_detail_minutes.py`：

1. 声明两个 GET route 和 Pydantic/FastAPI 参数。
2. 调用 `require_quote_access`。
3. 规范化 `tsCode`、校验 `freq/date/limit/cursor`。
4. 调用 `StockMinuteQueryService`。
5. 将 `MinuteRequestError` 映射为 `WebAppError(400, "SM_REQUEST_INVALID", ...)`。
6. 将 `MinuteSourceContractError` 映射为 503 `SM_SOURCE_CONTRACT_INVALID`。
7. 将 DuckDB/IO 异常映射为 503 `SM_QUERY_FAILED`，不得泄露本地文件绝对路径。

### 7.3 Query Service 层职责

`StockMinuteQueryService`：

```python
def read_bars(
    self,
    *,
    ts_code: str,
    freq: int,
    start_date: date | None,
    end_date: date | None,
    limit: int,
    cursor: str | None,
    debug: bool,
) -> StockMinutesResponseDto: ...
```

指标方法签名相同。Service 负责：

1. 计算默认窗口和 expected end date。
2. 构造 `MinuteReadRequest`。
3. 调用 reader，不重新计算指标。
4. 将 observed end 与显式 expected end 合并为 `READY/DELAYED/EMPTY`。
5. 组装 meta、status、debug metadata 和 DTO。
6. 对指标 NULL 保持 Python `None`。

Service 不负责：

- 访问 Dagster instance；
- 访问 Tushare/Prod DB；
- 合并 bars 与 indicators；
- 读取 state 文件；
- 触发任何任务。

### 7.4 异常码注册

在进入代码前，将以下 5 个条目写入 `wealth/docs/system/exception-code-registry.md`：

| code | module | severity | userVisible | debugOnly | frontendAction |
|---|---|---|---|---|---|
| `SM_LOCAL_LAKE_NOT_CONFIGURED` | `stockDetailMinutes` | error | false | true | 本地能力错误 |
| `SM_SOURCE_NOT_READY` | `stockDetailMinutes` | warn | false | true | 展示 delayed |
| `SM_SOURCE_CONTRACT_INVALID` | `stockDetailMinutes` | error | false | true | 模块 error |
| `SM_QUERY_FAILED` | `stockDetailMinutes` | error | false | true | 模块 error |
| `SM_REQUEST_INVALID` | `stockDetailMinutes` | error | false | true | 保留其它页面内容 |

`SM_SOURCE_NOT_READY` 在正常响应中体现为 `200 + dataStatus=DELAYED`；其它代码按异常 HTTP 返回。

## 8. Frontend 分钟接入

### 8.1 API client 与类型

新增：

```text
wealth/src/features/stock-detail/api/stockMinuteApiClient.ts
wealth/src/features/stock-detail/api/stockMinuteApiTypes.ts
wealth/src/features/stock-detail/api/stockMinuteViewModelAdapter.ts
```

client 提供：

```typescript
fetchStockMinuteBars({ tsCode, freq, endDate, limit = 500, cursor }, options)
fetchStockMinuteIndicators({ tsCode, freq, endDate, limit = 500, cursor }, options)
```

两个请求必须传相同的 `tsCode/freq/startDate/endDate/limit/cursor`。首次请求不传 cursor，默认 limit 500。

### 8.2 前端数据模型

新增独立类型，不复用当前日线 `StockCandlePoint`：

```typescript
type StockMinuteFrequency = 1 | 5 | 15 | 30 | 60 | 90 | 120;

interface StockMinuteChartPoint {
  key: string;                 // `${tradeDate}T${tradeTime}`
  tradeDate: string;
  tradeTime: string;           // +08:00 ISO
  time: number;                // lightweight-charts UTCTimestamp
  open: number;
  high: number;
  low: number;
  close: number;
  vol: number;
  amount: number;
  macd: number | null;
  dif: number | null;
  dea: number | null;
  k: number | null;
  d: number | null;
  j: number | null;
}
```

`stockMinuteViewModelAdapter.ts` 必须：

1. 先校验两侧根级与逐行 `tsCode/freq` 完全一致。
2. 分别按完整时间键建立 Map，任一侧存在重复键立即 fail closed。
3. bars 与 indicators 的完整时间键集合必须严格相等；任何缺失或多余都不得进入图表。
4. 指标字段自身处于预热期的 NULL 保持 NULL，不转成 0，也不调用现有 `valueOrZero()`。
5. adapter 失败只影响分钟图表模块，不回退 mock、不使用其他频率或旧缓存补齐。

### 8.3 页面编排

修改 `wealth/src/pages/stock-detail/StockDetailPage.tsx`：

1. 首次加载逻辑保持 `page-init -> 日线 kline`。
2. 根据 `pageInit.capabilities.supportsMinute` 和 `minuteFrequencies` 标记分钟周期可用性。
3. `m1/m5/m15/m30/m60/m90/m120` 映射为对应整数 `freq`。
4. 用户切换分钟周期时，同时请求 bars 和 indicators，使用 `AbortController` 取消旧频率请求。
5. 分钟请求 loading/error 只影响图表区域，不清空股票身份、日线或右侧信息。
6. real API 失败不调用 `getStockDetailViewModel()` 作为分钟数据回退。

`wealth/src/features/stock-detail/chart/StockMinuteChartWorkspace.tsx` 保留为股票分钟领域 adapter，负责分钟字段、单位、Tooltip 与状态文案；图表创建、四窗格同步、拖动、crosshair 和缩放统一委托给 `DetailChartWorkspace timeMode="minute"`，不再维护第二套生命周期。

### 8.4 分钟图表

2026-07-31 已验收的“独立分钟 workspace + 固定 90 根”保留为历史证据；当前实现由 `b38ac20e`、`61a5adea` 替代，规则如下：

1. API 仍请求 500 根作为有限浏览缓冲；shared 按 K 线真实 host 宽度计算默认值，1600px 为 120 根，自适应默认 clamp 为 75～150。
2. 用户可在 45～180 根之间以 15 根步长缩放；实际点数不足时显示全部，并按真实边界禁用按钮。非空路径不调用 `fitContent()`。
3. `DetailChartWorkspace` 是 K 线、MACD、成交量、KDJ 四窗格的唯一生命周期，任何 range、拖动、crosshair 与缩放变化均同步四图；保持 `handleScroll=false`、`handleScale=false`。
4. `StockMinuteChartWorkspace` 传入稳定 `dataKey=stock:${tsCode}:m${freq}`。频率或股票变化重置到新数据的自适应默认；普通图层变化和运行时重建恢复当前 range。
5. 当前视图贴近最新 bar 时缩放保持最新右锚；拖入历史后围绕当前中心缩放。拖动和缩放都不发新请求、不加载 cursor 下一页。
6. `timeVisible=true`。lightweight-charts 使用 UTC timestamp 作为内部排序键，但 `localization.timeFormatter` 与 `timeScale.tickMarkFormatter` 在所有分钟 crosshair 模式下都必须显式使用 `Asia/Shanghai`；禁止回退图表库默认 UTC 展示。tooltip 从 `tradeTime` 的 `+08:00` 语义格式化北京时间，不通过浏览器时区重新解释。
7. 所有图表共享 crosshair。正式股票分钟图只使用 shared synchronized overlay，图表库原生纵线必须隐藏，常驻时间轴只显示在 KDJ 最底部。overlay 的 `x` 必须由命中点的 `time` 经 K 线主图 `timeToCoordinate()` 计算，禁止直接使用原始鼠标 `point.x`；四个窗格再用同一 `time` 执行 `setCrosshairPosition()`。命中同一时间键时更新 K 线 Tooltip 和各指标标题；未命中、NULL 指标或离开时不得伪造 0 值。
8. K 线 Tooltip 固定为时间、开盘、收盘、最高、最低、成交量、成交额。分钟 `vol` 为股、`amount` 为元；收盘、最高、最低相对本 bar 开盘价着色，不伪造昨收语义。
9. MACD/KDJ 不进入 K 线 Tooltip，NULL 指标显示 `--`；不得展示接口未返回的 `preClose/change/pctChg/turnover`。
10. 同一 `time` 不能出现重复点；重复键在 adapter 中 fail closed。整段指标缺失只使指标层 delayed/empty，不隐藏真实 OHLCV 主图。

## 9. 测试与验证

### 9.1 后端单测

新增 `tests/web/test_wealth_stock_detail_minutes_reader.py`：

1. 代码、频率和年份路径校验。
2. 路径穿越、超 3 年和非法 cursor 拒绝。
3. schema 缺列、类型错、文件缺失。
4. 单年/跨年读数按时间升序。
5. 默认 500 根、limit+1 探测和 hasMore。
6. cursor 翻页无重复、无遗漏。
7. 500 根响应体不超过 5MB。
8. reader 只建立一个连接，不调用 event history、Tushare、Prod DB。

新增/扩展 `tests/web/test_wealth_stock_detail_minutes_api.py`：

1. local profile 挂载两个路由。
2. prod profile 两个路由均 404，且 DuckDB 未加载。
3. 参数缺失、非法 freq、日期反向、超 limit 返回 400。
4. 文件存在并 ready 返回 200/READY。
5. 最新日期落后返回 200/DELAYED。
6. 空历史范围返回 200/EMPTY。
7. schema/IO 错误返回 503/ERROR。
8. 无权限访问被拒绝。
9. bars 与 indicators 采用相同时间键。

### 9.2 前端测试

新增：

```text
wealth/src/features/stock-detail/api/stockMinuteViewModelAdapter.test.ts
wealth/src/features/stock-detail/chart/StockMinuteChartWorkspace.test.tsx
```

并扩展 `StockDetailPage.test.tsx`：

1. capability false 时分钟入口不可用。
2. capability true 时七个分钟频率可用。
3. 切换频率并行请求 bars/indicators。
4. NULL 指标保持 NULL，不转 0。
5. 500 个分钟点在 1600px 基线下初始显示末尾 120 点且不调用 `fitContent()`；增加 45/180 边界、75/150 自适应宽度、dataKey 和 overlay/resize/append 生命周期测试。
6. 在任意分钟窗格拖动后，四个 chart 的 logical range 同步且不越过已加载点范围；该动作不发出新的 bars/indicators 请求。
7. crosshair 命中时分钟 K 线 tooltip 按日线顺序展示真实 OHLCV/amount 并使用正确的股/元单位；MACD/KDJ 标题同步更新，NULL 指标为 `--`，不出现日线专属字段。
8. bars/indicators 时间集合不完全相等时 fail closed，不制造伪造 bar，也不静默补 NULL 指标行。
9. API error 不回退 mock。
10. delayed/empty 不污染已有日线页面状态。

### 9.3 本地真实验证

使用临时 Parquet 和一只真实股票的本地 Gold 文件：

1. 七个频率各请求默认 500 根。
2. 测试 500/2000/10000 三个 limit 边界。
3. 测试单年和跨年路径。
4. 测试指标 NULL、缺文件和 schema 漂移。
5. 启动 local profile 访问真实 FastAPI route。
6. 使用 prod profile 验证路由不存在、既有日线仍正常。

## 10. 性能、安全与观测门禁

| 指标 | 目标 | 硬上限 |
|---|---:|---:|
| 单接口 P95 | 1.5s | 5s |
| 默认返回 | 500 行 | 500 行语义固定 |
| 显式返回 | 由 limit 控制 | 10000 行 |
| 返回体 | 2MB | 5MB |
| 目标年份文件 | 1 至 2 | 3 |
| DuckDB connection/request | 1 | 1 |
| Dagster event history 调用 | 0 | 0 |
| Lake 写操作 | 0 | 0 |
| Tushare/Prod DB 调用 | 0 | 0 |
| 全湖扫描/无界 OFFSET | 0 | 0 |

debug metadata 只允许包含：dataset、freq、scanned_file_count、row_count、elapsed_ms、has_more、status、reason_code；禁止输出绝对路径、完整 SQL、完整代码列表或完整行数据。

## 11. 分阶段实施顺序

### M0：契约和门禁

1. 将 5 个 `SM_*` 写入统一异常码注册表。
2. 在 `pyproject.toml` 增加 `local-lake` extra 并更新 lock。
3. 补齐本 LLD 和方案文档链接。
4. 不创建业务路由、不读取 Lake。

### M1：配置、能力和 reader

1. 修改 Settings。
2. 新增 capability resolver。
3. 新增 reader、路径安全、schema、cursor 和单测。
4. 仅用临时 Parquet 验证，不启动正式服务。

### M2：后端 API

1. 新增 schema、query service、API router。
2. 条件装配分钟 router。
3. 修改 page-init capability。
4. 运行 FastAPI 真实 route 测试。

### M3：前端接入

1. 新增 minute API client/types/adapter。
2. 修改页面周期能力映射和分钟请求状态。
3. 新增分钟 workspace 和北京时间时间轴。
4. 运行前端 typecheck/test/build。

### M4：真实联调和远程负向验证

1. 本地开启 `local-lake` extra、flag 和 Lake root。
2. 选择 1m/5m/60m/120m 做真实接口和页面联调，再覆盖全部七频率。
3. 远程 profile 不安装 extra，验证分钟路由 404。
4. 验证既有日线接口和远程构建无回退。

## 12. 验收标准

只有同时满足以下条件，才算完成：

1. 本地两个分钟 API 可返回真实 Gold 数据。
2. 七种频率均可显式请求，默认 500 根。
3. 分页无重复、无遗漏，跨年不全湖扫描。
4. 指标 NULL 保持 NULL，bars/indicators 时间键可对齐。
5. `DELAYED` 使用 HTTP 200，真实错误不伪装成 delayed。
6. 远程不安装/加载 DuckDB，分钟路由 404，日线不受影响。
7. P95、响应体、文件扫描数和连接数满足门禁。
8. 后端真实 route、前端真实 API 和远程负向测试全部通过。

## 13. 开发前事项的完成状态

以下事项已在 M0-M4 完成，不再作为开发前阻断项：

1. 异常码已写入中央 registry。
2. `local-lake` optional extra 已加入项目配置并锁定依赖。
3. 真实 Gold 文件已确认 1m/5m/15m/30m/60m/90m/120m 的读取路径和覆盖能力。
4. 500 根请求、`LIMIT + 1`、cursor 分页和响应体大小门禁已通过真实 API 验证。
5. 现有 `StockDetailPage` 的 day/minute 分支已通过真实 FastAPI、Vite、Playwright 页面联调。

## 14. 版本记录

| 版本 | 日期 | 变更摘要 |
|---|---|---|
| v1 | 2026-07-31 | 初版，细化配置、reader、API、前端和性能实现 |
| v1.1 | 2026-07-31 | 冻结 500 根默认返回、显式频率、DELAYED 状态和 local-lake 依赖边界 |
| v1.2 | 2026-07-31 | 补齐代码级文件落点、函数签名、窗口/cursor、响应、前端时间模型和测试门禁 |
| v1.3 | 2026-07-31 | 增加符号级实施矩阵、调用链、reader 算法、前端状态机、代码对账门禁和可直接执行的 D1-D5 步骤 |
| v1.4 | 2026-07-31 | 完成 M0-M4 实现、真实 API/分页/隔离验证和浏览器页面联调，回写最终验收证据 |
| v1.5 | 2026-07-31 | 细化并实施分钟图首屏 90 点、四窗格受控拖动和真实字段 tooltip 的代码级交互口径 |
| v1.6 | 2026-07-31 | 修正分钟 tooltip 对齐：复用日线顺序与方向色，按分钟源股/元单位展示量额，指标保留在同步面板标题 |
| v1.7 | 2026-08-12 | M3 对账：股票分钟已迁入 shared 并启用 45～180/15、自适应默认和稳定 dataKey；API/Reader/500 根合同不变 |
| v1.8 | 2026-08-14 | 完成 P10：reader 对有限返回页增加 canonical 时间合同校验；前端要求 bars/indicators 身份、唯一键和完整时间键集合严格相等，指标值自身的预热 NULL 仍保留 |

## 15. 符号级实施矩阵

本节是开发时的执行清单。实现必须优先修改表中指定的符号，不得把分钟查询逻辑塞回既有日线查询模块，也不得在 API 层直接拼接 Lake 路径或 SQL。

| 层 | 文件 | 必须实现/修改的符号 | 责任 | 禁止事项 |
|---|---|---|---|---|
| 配置 | `src/foundation/config/settings.py` | `Settings.wealth_local_lake_minute_api_enabled`、`Settings.goldenshare_lake_root` | 读取两个配置项；默认关闭、本地显式开启 | 不在路由、前端常量或 `.env` 之外新增第二套配置来源 |
| 能力 | `src/foundation/config/local_minute_capability.py` | `resolve_local_minute_capability()`、`LocalMinuteCapability` | 校验环境、flag、root、DuckDB 可导入性 | 不扫描 Lake，不创建 reader，不访问业务模块 |
| Lake reader | `src/foundation/clients/local_lake/stock_mins_reader.py` | `MinuteReadRequest`、`MinuteReadPage`、`StockMinsLakeReader.read_bars()`、`read_indicators()` | 路径、schema、SQL、cursor、bounded result | 不访问 Dagster、Prod DB、Tushare；不写文件 |
| page-init | `src/biz/queries/wealth/market/stock_detail/stock_detail_query_service.py` | `StockDetailQueryService.build_page_init()` | 把 capability 转为 `supportsMinute` 和七频 `minuteFrequencies` | 不按某个股票当天是否有文件决定全局能力 |
| page-init schema | `src/biz/schemas/wealth/market/stock_detail.py` | `StockDetailCapabilitiesDto` | 暴露 `minuteFrequencies`，默认空列表 | 不改变日线 `chartDefaults` 与 quote/kline 字段 |
| 路由装配 | `src/app/api/v1/router.py` | `_include_local_minute_router()` | 仅 local capability true 时延迟导入并挂载分钟 router | 远程 profile 不导入分钟 API/reader/DuckDB |
| API | `src/biz/api/wealth/market/stock_detail_minutes.py` | `get_stock_minute_bars()`、`get_stock_minute_indicators()` | 参数解析、权限依赖、异常转换、调用 service | 不创建 DuckDB connection，不读取 Lake |
| 查询协议 | `src/biz/queries/wealth/market/stock_detail_minutes/stock_detail_minutes_query.py` | `StockMinuteQueryWindow`、`resolve_stock_minute_query_window()` | 计算 query end 与 expected end | 不把北京时间今天误当成页面 expected trade day |
| Query service | `src/biz/queries/wealth/market/stock_detail_minutes/stock_detail_minutes_query_service.py` | `StockMinuteQueryService.read_bars()`、`read_indicators()` | reader 调用、status、DTO、响应体门禁 | 不重算指标，不合并两个数据集事实 |
| API schema | `src/biz/schemas/wealth/market/stock_detail_minutes.py` | `StockMinutesResponseDto`、`StockMinuteIndicatorsResponseDto` 及子 DTO | 固定 lowerCamelCase 响应、NULL 指标 | 不加入 `preClose/change/pctChg`，不允许额外字段静默进入响应 |
| 前端类型 | `wealth/src/features/stock-detail/api/stockMinuteApiTypes.ts` | `StockMinuteFrequency`、bars/indicators DTO | 对齐后端响应 | 不复用日线 Kline DTO |
| 前端 client | `wealth/src/features/stock-detail/api/stockMinuteApiClient.ts` | `fetchStockMinuteBars()`、`fetchStockMinuteIndicators()` | 同参数、同 cursor、错误 code 保留 | 不回退 mock，不把分钟请求并入日线 client |
| 前端 adapter | `wealth/src/features/stock-detail/api/stockMinuteViewModelAdapter.ts` | `buildStockMinuteChartViewModel()`、`minuteFrequencyFromPeriodKey()` | 时间键合并、NULL 保持、频率映射 | 不将 NULL 转 0，不用 indicators 创建伪造 bar |
| 前端 workspace adapter | `wealth/src/features/stock-detail/chart/StockMinuteChartWorkspace.tsx` | `StockMinuteChartWorkspace()`、`MinuteKlineTooltip()` | 映射分钟字段/单位/文案并传 `dataKey`，消费 shared 四窗格 | 不创建 chart、不维护 range/drag/crosshair；不在交互时请求 API；不伪造日线字段 |
| shared 图表 | `wealth/src/shared/charts/detail-workspace/` | `DetailChartWorkspace()`、`DetailChartZoomControls()`、viewport helpers | 唯一四窗格生命周期、120 自适应默认、45～180/15 缩放、range/crosshair/drag 同步 | 不 import 股票 DTO；不发请求；不保留页面级常量覆盖 |
| 页面编排 | `wealth/src/pages/stock-detail/StockDetailPage.tsx` | `handlePeriodChange()`、分钟 request/cache/controller 状态 | 周期切换、并发请求、取消、缓存 | 不因分钟失败清空股票身份、日线和右侧信息 |

### 15.1 请求到响应的固定调用链

```text
StockDetailPage.handlePeriodChange("m5")
  -> fetchStockMinuteBars(params, { signal })
  -> GET /api/v1/wealth/market/stock-detail/minutes
  -> get_stock_minute_bars()
  -> StockMinuteQueryService.read_bars()
  -> StockMinsLakeReader.read_bars(MinuteReadRequest)
  -> build_stock_mins_qfq_paths()
  -> _validate_file_schema() for each selected year file
  -> _query_rows() with LIMIT(limit + 1)
  -> StockMinutesResponseDto

StockDetailPage.handlePeriodChange("m5")
  -> fetchStockMinuteIndicators(params, { signal })
  -> GET /api/v1/wealth/market/stock-detail/minute-indicators
  -> get_stock_minute_indicators()
  -> StockMinuteQueryService.read_indicators()
  -> StockMinsLakeReader.read_indicators(MinuteReadRequest)
  -> StockMinuteIndicatorsResponseDto
  -> buildStockMinuteChartViewModel(bars, indicators)
  -> StockMinuteChartWorkspace（领域 adapter）
  -> DetailChartWorkspace（唯一四窗格生命周期与 viewport）
```

两个请求必须使用同一个 `tsCode/freq/startDate/endDate/limit/cursor`。首屏 `cursor` 为空、`endDate=pageInit.pageContext.tradeDate`、`limit=500`；响应回来后只在当前组件仍然处于同一个频率且 `AbortSignal` 未取消时更新 state。

## 16. Reader 逐步算法与失败边界

`StockMinsLakeReader._read()` 的顺序必须固定，后续实现或重构不得交换这些门禁的顺序：

1. `_normalize_request()`：规范化大写代码、整数频率、日期顺序、limit 和 cursor 绑定关系。
2. `_request_years()`：用请求日期计算最多 3 个自然年；没有日期时使用北京时间今天，并从该年向前取最多 3 年。
3. `build_stock_mins_qfq_paths()`：只生成 bars 或 indicators 对应的真实物理布局；路径 `resolve()` 后必须在 root 内；只返回存在的普通 Parquet 文件。
4. 没有目标文件时立即返回空页，不创建 DuckDB 连接；service 再根据是否有显式 `endDate` 判定 `EMPTY` 或 `DELAYED`。
5. 导入 DuckDB 并建立本次调用唯一的 `:memory:` connection；所有 schema 检查和业务查询复用该 connection。
6. 对每个选中文件执行显式 projection 的 `DESCRIBE SELECT ... FROM read_parquet(?)`。缺列、字段顺序不一致、类型不匹配或文件不可读统一抛 `MinuteSourceContractError`。
7. 使用 `_query_rows()`：只投影合同字段，绑定代码、频率、起止日期和 cursor 边界；按 `(trade_date, trade_time)` 倒序；`LIMIT=request.limit + 1`。
8. 结果只允许保留 `limit` 行；有第 `limit+1` 行时生成下一页 cursor；最终返回前反转为时间升序。
9. 对返回页做有限结果检查：代码和频率一致、日期在范围内、时间键严格递增、行数不超过 limit；违反时抛 `MinuteQueryError`。
10. `finally` 关闭 DuckDB connection；不把连接、绝对路径、SQL 或完整行数据放入响应。

错误边界固定为：

| 失败点 | 异常 | HTTP | code |
|---|---|---:|---|
| 参数、日期、cursor、频率、年份或 limit | `MinuteRequestError` | 400 | `SM_REQUEST_INVALID` |
| 文件缺失 | 正常空页 | 200 | 显式 endDate 时 `DELAYED`，否则 `EMPTY` |
| 文件无法读取、字段/类型/合同错误 | `MinuteSourceContractError` | 503 | `SM_SOURCE_CONTRACT_INVALID` |
| DuckDB 执行、结果结构或 IO 错误 | `MinuteQueryError` | 503 | `SM_QUERY_FAILED` |
| local capability 未配置 | `WebAppError` | 503 | `SM_LOCAL_LAKE_NOT_CONFIGURED` |

## 17. 前端状态机与并发规则

### 17.1 页面状态

| 状态 | 进入条件 | 允许展示 | 禁止行为 |
|---|---|---|---|
| `idle` | 日线激活或尚未切换分钟 | 日线/空状态 | 不发送分钟请求 |
| `loading` | 切换到未缓存频率并发请求两个接口 | 保留身份区和右侧信息，图表区显示 loading | 不显示旧频率数据冒充新频率 |
| `ready` | 两个请求成功且 adapter 合并完成 | 四窗格和当前 status | 不把 NULL 指标补成 0 |
| `error` | 任一请求失败且未被取消 | 图表区错误；页面其余区域保持 | 不回退 mock，不清空 page-init |
| `delayed/empty` | API 200 且 `dataStatus` 返回对应状态 | K 线和状态文案按实际数据显示 | 不把 delayed 当 HTTP error |

### 17.2 取消、缓存和竞态

1. 新的分钟频率请求开始前，调用 `minuteControllerRef.current?.abort()`。
2. 请求成功后先检查本次 controller 的 `signal.aborted`；已取消请求不得写入 `minuteChart`、`minuteCacheRef` 或错误状态。
3. 日线切换必须取消当前分钟请求、清空当前分钟图表和错误状态，但不清除 page-init/daily view model。
4. `tsCode` 改变时清空分钟 cache 并取消在途请求。
5. 组件卸载时同时取消 page-init controller 和分钟 controller，防止卸载后 setState。
6. cache key 固定为 `StockMinuteFrequency`；不同代码不得复用同一 cache。

### 17.3 时间键硬约束

adapter 内部匹配键固定为“`tradeDate` + `tradeTime` 的本地时分秒部分 + 时区偏移”，例如 `2026-07-31T09:30:00+08:00`。后端当前返回的 `tradeTime` 已是完整 ISO 字符串，因此实现必须先取 `tradeTime` 的时间部分再拼接，不能直接重复拼接完整 ISO 字符串，也不能只使用 `tradeTime`；否则跨交易日同一时刻会产生碰撞或键语义不一致。`StockMinuteChartPoint.key` 必须使用该完整键。传给 lightweight-charts 的 `timestamp` 只用于排序和绘图，不替代业务匹配键。

## 18. 代码与文档对账门禁

M0-M4 已完成。以下门禁已逐项对账；“代码能编译”不等于对账通过：

### 18.1 必须修正/确认的实现点

1. `StockDetailPage` 的 `useEffect` cleanup 必须同时 abort `minuteControllerRef.current`；否则切换股票或卸载页面时可能出现旧请求回写。
2. `stockMinuteViewModelAdapter.ts` 的 `StockMinuteChartPoint.key` 必须改成完整时间键 `${tradeDate}T${tradeTime}`。
3. `StockMinuteChartWorkspace.tsx` 的未使用类型导入必须通过 typecheck/lint 清理。
4. indicators 返回 `DELAYED/EMPTY` 而 bars 有数据时，workspace 状态文案必须优先展示 indicator status，不得仅展示 bars 的 READY 文案。
5. `StockMinsLakeReader` 当前对每个文件做 `DESCRIBE`，业务查询使用 `LIMIT+1` bounded fetch；性能报告必须分别记录 schema 查询和业务查询耗时，不能把它们合并成“单次查询”而掩盖开销。

### 18.2 代码级验收矩阵

| 验收项 | 代码位置 | 证据 |
|---|---|---|
| local/prod 路由隔离 | `local_minute_capability.py`、`src/app/api/v1/router.py` | prod 路径 404；`duckdb` 未导入 |
| 七频且 freq 无默认值 | API `Query()`、frontend frequency union | 缺 freq 400；1/5/15/30/60/90/120 全覆盖 |
| 500 根 bounded | reader `_query_rows()`、client/page params | SQL limit=501；前端 limit=500 |
| cursor 无 offset | reader cursor 编解码和 `<` 谓词 | 连续两页无重复/遗漏 |
| NULL 指标保留 | schema/service/adapter/chart | JSON null、图表不画 0 |
| delayed 200 | `StockMinuteQueryService._to_status()` | 显式 endDate 且源缺失/落后时 200/DELAYED |
| 错误不伪装 delayed | API exception mapping | schema/IO -> 503/ERROR |
| 无额外字段 | Pydantic `extra=forbid`、explicit projection | `preClose/change/pctChg` 不出现 |
| 请求不写入 | reader/service/api 调用链 | 无 write、Dagster、event API |
| 分钟首屏与横向浏览 | `DetailChartWorkspace.tsx`、`detailChartViewport.ts` | 500 点缓存、1600px 初始末 120 点、45～180/15、四窗格范围同步、无额外请求 |
| 分钟 crosshair/tooltip | `StockMinuteChartWorkspace.tsx` | 四窗格同时间十字线；tooltip 只展示真实分钟字段；NULL 为 `--` |

## 19. 已执行的开发步骤与当前追加步骤

D1～D5 记录原股票分钟 API 的已执行步骤；其文件清单和 90 根验收只代表 2026-07-31 历史实现，不是当前重新开发指令。2026-08-12 在其后追加并完成 D6/D7，当前实现以 D6/D7 为准。

### D1：M3 前端契约和 adapter

修改：

```text
wealth/src/features/stock-detail/api/stockMinuteApiTypes.ts
wealth/src/features/stock-detail/api/stockMinuteApiClient.ts
wealth/src/features/stock-detail/api/stockMinuteViewModelAdapter.ts
```

验收：七频 union、两个 endpoint、共同参数、完整时间键集合严格相等、NULL 指标值保留、重复键/差集 fail closed。

测试：

```bash
cd /Users/congming/github/goldenshare/wealth
npm run typecheck
npm test -- --run src/features/stock-detail/api/stockMinuteViewModelAdapter.test.ts
```

### D2：M3 页面与图表

修改：

```text
wealth/src/pages/stock-detail/StockDetailPage.tsx
wealth/src/features/stock-detail/chart/StockMinuteChartWorkspace.tsx
wealth/src/pages/stock-detail/stock-detail-page.css
```

验收：页面保持 page-init -> 日线顺序；切换分钟只影响图表区；并发请求可取消；缓存按频率隔离；四个窗格可挂载；500 点在 1600px 首屏显示末 120 点；任意分钟窗格可拖动和缩放并同步；交互不发额外请求；tooltip 字段不越过分钟 API 契约。

测试：

```bash
cd /Users/congming/github/goldenshare/wealth
npm test -- --run src/pages/stock-detail/StockDetailPage.test.tsx src/features/stock-detail/chart/StockMinuteChartWorkspace.test.tsx
npm run typecheck
npm run build
```

### D3：后端完整回归

```bash
cd /Users/congming/github/goldenshare
PYTHONPATH=. uv run --extra dev --extra local-lake python -m pytest -q \
  tests/test_local_minute_capability.py \
  tests/test_stock_mins_reader.py \
  tests/web/test_stock_detail_minutes_api.py \
  tests/web/test_wealth_stock_detail_api.py \
  tests/lake_console/test_settings.py \
  tests/architecture/test_subsystem_dependency_matrix.py
```

### D4：本地真实 API 与远程负向验证

本地必须显式设置：

```bash
APP_ENV=dev \
GOLDENSHARE_ENV_FILE=/path/to/local.env \
WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED=true \
GOLDENSHARE_LAKE_ROOT=/Volumes/datasource/data_lake \
uv run --extra dev --extra local-lake ...
```

验证：

1. `601878.SH` 或当前存在分钟文件的真实代码，七频各请求一次；默认 limit=500。
2. 记录每次 HTTP 状态、`dataStatus`、返回行数、`hasMore`、`scannedFileCount`、elapsed。
3. 至少验证一个缺文件代码的显式 `endDate` 得到 `200/DELAYED`。
4. `APP_ENV=prod` 且 local flag true、root 为空时，分钟路由不挂载，且进程不导入 DuckDB。
5. 日线 page-init/kline 在 local/prod 两种 profile 都保持原响应字段和状态。

### D5：最终报告与提交门禁

报告必须记录：

- 真实测试时间、代码 commit、环境 profile；
- 七频请求参数和返回行数；
- 单接口 P50/P95/P99、最大 elapsed；
- schema 查询耗时、业务查询耗时、DuckDB connection 数；
- response bytes、5MB 边界结果；
- 远程 404/未导入 DuckDB 证据；
- 测试命令和结果；
- 未通过项和后续修复。

提交前执行：

```bash
git diff --check
git status --short
```

只允许将本专项文件分组提交，不得把 market-overview、Dagster 文档、报告、Figma 产物或其它脏改带入提交。

### D6：股票分钟共享收敛（已完成）

提交：`b38ac20e refactor(wealth): migrate stock minutes to shared detail chart`。

1. `StockMinuteChartWorkspace` 改为纯领域 adapter，删除独立 `createChart/addSeries/range sync/drag/crosshair/pane` 生命周期。
2. `DetailChartWorkspace` 增加领域无关的分钟展示策略和 `topRightAccessory`，迁移阶段保持 90 根基线与像素几何。
3. 股票日线、股票分钟、指数日线、指数分钟全部消费同一 shared workspace。

### D7：统一缩放与自适应默认（已完成）

提交：`61a5adea feat(wealth): add adaptive detail chart zoom controls`。

1. `detailChartViewport.ts` 唯一定义 45/180/15、默认 120、自适应 75～150、9.5px/根和右轴 56px。
2. 四类 adapter 传稳定 `dataKey`；shared 统一处理 latest/历史中心、resize、overlay 重建和追加 bar。
3. 单次点击只同步四个 logical range，不重建 chart、不调用 `fitContent()`、不发 API。
4. 27 个测试文件、152 项测试、typecheck、build 和 1600×1200 浏览器验收通过。

## 20. 当前阶段结论

原分钟 API M0-M5 已完成；其 90 点首屏是 2026-07-31 历史验收基线。随后 `b38ac20e`、`61a5adea` 在不改变 API 契约的前提下完成 shared 四窗格迁移与统一缩放。当前实现边界仍保持：本地 profile 才挂载分钟路由，远程/prod profile 不挂载分钟路由，也不导入 DuckDB。

| 项目 | 当前状态 |
|---|---|
| API/reader/config 后端 | 已实现；单测和真实本地 HTTP smoke 通过 |
| 前端分钟 client/adapter/page/workspace | 已实现；500 点缓冲、1600px 默认末 120 点、45～180/15、四窗格同步拖动/缩放和分钟 tooltip 均已验证 |
| 完整前端回归 | M2 收尾为 27 个测试文件、152 项测试通过；typecheck/build 通过 |
| 真实浏览器页面联调 | 7 个频率逐一点击通过；5 分钟图完成 shared 缩放与切回日线验收，拖动/缩放无额外请求，tooltip 正常；无 console error |
| 远程 prod 隔离验证 | `APP_ENV=prod` 且本地 lake root 为空时分钟路由数为 0，DuckDB 未导入 |
| 正式完成 | M0-M5 完成；待用户在本地运行环境中按需启用配置 |

## 21. M4 验收证据

### 21.1 真实本地 API

验证时间：`2026-07-31 21:47 Asia/Shanghai`；profile：local-enabled；代码：`601878.SH`；请求结束日：`2026-07-31`。

- 频率：`1/5/15/30/60/90/120` 全部验证。
- bars 和 minute-indicators 每个频率均返回 HTTP `200`、`count=500`、`hasMore=true`。
- 每次最多扫描 3 个年度 Parquet 文件；reader 最大耗时约 `24ms`，HTTP 最大耗时约 `47ms`。
- 最大响应体约 `163KB`，远低于 5MB 上限。
- cursor 两页验证：两页各 3 行、cursor 存在、无 key 重叠、6 个业务时间键唯一，第二页严格早于第一页。
- 缺失代码 `999999.SH` 在显式 `endDate` 下返回 HTTP `200`、`dataStatus=DELAYED`、`count=0`。
- 省略 `freq` 返回 HTTP `422`，证明频率没有默认值。
- 返回字段不包含 `preClose/change/pctChg`。

详细机器报告：`/private/tmp/stock_minute_api_m4_report_20260731.json`。

### 21.2 本地页面与七频交互

- 页面：`http://127.0.0.1:5173/wealth/market/stock/601878.SH`。
- 7 个频率按钮均可见，并逐一触发 bars + indicators 请求。
- 7 个频率对应的 14 个分钟请求均为 HTTP `200`。
- 分钟页面渲染出 K 线、MACD、成交量、KDJ 四个窗格，共检测到 28 个 canvas。
- 浏览器 console error 数量为 `0`。
- 截图：`/private/tmp/stock_minute_ui_all_freq_smoke_20260731.png`。

### 21.3 prod 负向隔离

在 `APP_ENV=prod`、`WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED=true`、`GOLDENSHARE_LAKE_ROOT` 为空时：

- 分钟路由数量为 `0`；
- `duckdb` 不在已导入模块中；
- 日线相关路由仍由原有 API 装配。

### 21.4 自动化回归

- 后端分钟能力、reader、API、设置和依赖矩阵测试：`26 passed`。
- 前端全量 Vitest：`13 files / 62 tests passed`。
- `npm run typecheck`：通过。
- `npm run build`：通过；仅保留既有 Vite chunk size warning。

## 22. M5 图表交互验收证据

验证时间：`2026-07-31 22:21 Asia/Shanghai`；页面代码：`601878.SH`；频率：`5`。

- 本地分钟 API 返回 `dataStatus=READY`、`count=500`、`hasMore=true`；前端没有降低接口缓冲量。
- `StockMinuteChartWorkspace` 组件测试证明 500 点的初始逻辑范围为 `410..499`，四个图都不调用 `fitContent()`。
- 真实浏览器页面保留 K 线、MACD、成交量、KDJ 四窗格，共 28 个 canvas；从任意图区域拖动后，分钟 endpoint 请求数保持 `2 -> 2`。
- 悬停 K 线时 tooltip 按日线顺序显示北京时间、OHLC、成交量、成交额；MACD/KDJ 面板标题同步更新。不显示 `preClose/change/pctChg/turnover`，浏览器 console error 为 `0`。
- 日线 tooltip 对齐后的前端视觉回归使用受控 mock minute API：分钟 `vol` 按股/万股/亿股、`amount` 按元/万元/亿元显示，收盘、最高、最低相对本根开盘价着色；mock 页面无 console error。
- 截图：`/private/tmp/stock_minute_tooltip_aligned_20260731.png`。

以上 90 点范围属于 2026-07-31 的 M5 历史证据。2026-08-12 的当前回归已将其替换为 shared 在 1600px 下末 120 点，并增加 45/180、resize、dataKey、overlay/append、按钮不重建 chart/不发请求等门禁；不得再把 `410..499` 解释为当前默认窗口。

## 23. 后续边界

本专项代码和文档已达到可交付状态；本地分钟能力仍只需在 local profile 配置：

```env
WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED=true
GOLDENSHARE_LAKE_ROOT=/Volumes/datasource/data_lake
```

远程部署继续保持分钟能力关闭，不要求远程 prod DB 提供分钟文件。业务层后续如需增加 `preClose/change/pctChg`，应另开 API contract 版本，不在本版本中隐式扩字段。
