# 股票详情分钟线与分钟技术指标 API LLD v1.2

> 方案：[分钟 API 技术实施方案](./stock-detail-minutes-api-implementation-design-v1.md)
> 需求：[分钟 API 标杆需求](./stock-detail-minutes-api-benchmark-requirement-v1.md)
> 门禁：[分钟 API 编码前门禁](./stock-detail-minutes-api-m2-coding-gate-v1.md)

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
| `wealth/src/features/stock-detail/chart/StockChartWorkspace.tsx` | 默认可视 90 根，日线时间轴 | 保留日线 workspace，新增分钟 workspace |
| `wealth/src/features/stock-detail/api/stockDetailViewModelAdapter.ts` | `valueOrZero()` 把 NULL 转 0 | 分钟 adapter 不复用该函数 |
| `pyproject.toml` | 没有 DuckDB | 增加 `local-lake` optional extra，远程不安装 |
| `lake_console/backend` | 独立本地 Lake 管理台 | 不导入、不挂载、不改动 |

当前 Gold 合同已核对：

- 分钟线：`gold/quote/stk_mins_qfq/freq={freq}m/ts_code={ts_code}/year={year}/part-000.parquet`
- 指标：`gold/indicator/stk_mins_qfq_macd_kdj/freq={freq}m/ts_code={ts_code}/year={year}/part-000.parquet`
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
DEFAULT_VISIBLE_MINUTE_BARS = 90
```

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

1. 按 bars 的时间键建立 Map。
2. 按 indicators 的时间键补充指标。
3. bars 有而 indicators 没有时保留 bar，指标字段为 NULL。
4. indicators 有而 bars 没有时不创建伪造 bar，并在 debug 中记录差集计数。
5. 不调用现有 `valueOrZero()`。

### 8.3 页面编排

修改 `wealth/src/pages/stock-detail/StockDetailPage.tsx`：

1. 首次加载逻辑保持 `page-init -> 日线 kline`。
2. 根据 `pageInit.capabilities.supportsMinute` 和 `minuteFrequencies` 标记分钟周期可用性。
3. `m1/m5/m15/m30/m60/m90/m120` 映射为对应整数 `freq`。
4. 用户切换分钟周期时，同时请求 bars 和 indicators，使用 `AbortController` 取消旧频率请求。
5. 分钟请求 loading/error 只影响图表区域，不清空股票身份、日线或右侧信息。
6. real API 失败不调用 `getStockDetailViewModel()` 作为分钟数据回退。

新增 `wealth/src/features/stock-detail/chart/StockMinuteChartWorkspace.tsx`，避免让既有日线 workspace 同时承担两种时间模型。

### 8.4 分钟图表

分钟 workspace 复用现有图表视觉和四窗格布局，但固定：

1. `DEFAULT_VISIBLE_MINUTE_BARS=90`，API 仍请求 500 根作为缓冲。
2. `timeVisible=true`，时间格式使用 `Asia/Shanghai`。
3. lightweight-charts 使用 UTC timestamp 作为内部排序键；tooltip 和 tick formatter 转回北京时间。
4. 同一 `time` 不能出现重复点；重复键在 adapter 中 fail closed。
5. MACD/KDJ line/histogram 对 NULL 点跳过，不把 NULL 画成 0。
6. 当一整段指标都为空时，指标窗显示 delayed/empty 状态，不隐藏 OHLCV 主图。
7. 频率切换只更换数据和标题，不改变页面路由。

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
5. bars/indicators 时间差集不制造伪造 bar。
6. API error 不回退 mock。
7. delayed/empty 不污染已有日线页面状态。

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

## 13. 开发前仍需执行但不再需要产品拍板的事项

以下是实施动作，不是新的产品口径：

1. 将异常码写入中央 registry。
2. 按 `local-lake` extra 更新 `pyproject.toml`/lock。
3. 用真实 Gold 文件确认 90m/120m 的实际覆盖长度。
4. 跑 500 根和 5MB payload 性能基准。
5. 对现有 `StockDetailPage` 的 day/minute 分支做真实 FastAPI + 前端 smoke。

## 14. 版本记录

| 版本 | 日期 | 变更摘要 |
|---|---|---|
| v1 | 2026-07-31 | 初版，细化配置、reader、API、前端和性能实现 |
| v1.1 | 2026-07-31 | 冻结 500 根默认返回、显式频率、DELAYED 状态和 local-lake 依赖边界 |
| v1.2 | 2026-07-31 | 补齐代码级文件落点、函数签名、窗口/cursor、响应、前端时间模型和测试门禁 |
