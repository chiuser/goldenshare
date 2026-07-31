# 股票详情分钟线与分钟技术指标 API 技术实施方案 v1

> 需求基线：[分钟 API 标杆需求](./stock-detail-minutes-api-benchmark-requirement-v1.md)
> LLD：[分钟 API 低级设计](./stock-detail-minutes-api-low-level-design-v1.md)
> 门禁：[分钟 API M2 编码前门禁](./stock-detail-minutes-api-m2-coding-gate-v1.md)

## 1. 设计目标

在不改变远程生产数据链路的前提下，为本地财势乾坤行情系统增加股票分钟线和分钟技术指标查询能力。

```text
wealth 5173 -> local src/app/web 8000 -> src/biz minute API
    -> src/foundation local lake reader -> local Gold Parquet
```

远程仍保持 `wealth -> remote src/app/web -> Prod DB/ClickHouse`，不加载本地 Lake reader。

## 2. 当前代码审计

1. `src/app/api/v1/router.py` 聚合 `/api/v1` 路由。
2. `src/biz/api/wealth/market/stock_detail.py` 已提供日线 page-init/kline。
3. `StockDetailQueryService` 当前通过 SQLAlchemy 读取 serving 日线表。
4. `wealth/vite.config.ts` 的 `/api` 代理目标是本机 8000。
5. `wealth/src/features/stock-detail/api/stockDetailApiClient.ts` 是现有股票详情请求边界。
6. `StockDetailPage` 当前只加载日线；分钟能力由 capability 和本地构建开关共同控制。
7. `lake_console/backend` 是本地 Lake 管理台，不能被生产业务 API 导入。
8. 当前生产 `pyproject.toml` 没有 DuckDB 依赖；DuckDB 固定放入独立的 `local-lake` 可选依赖组，远程生产安装不带该 extra。

## 3. 代码落点

```text
src/app/api/v1/router.py
src/foundation/config/settings.py
src/foundation/clients/local_lake/stock_mins_reader.py
src/biz/api/wealth/market/stock_detail_minutes.py
src/biz/queries/wealth/market/stock_detail_minutes/
  stock_detail_minutes_query.py
  stock_detail_minutes_query_service.py
src/biz/schemas/wealth/market/stock_detail_minutes.py

wealth/src/features/stock-detail/api/
  stockMinuteApiClient.ts
  stockMinuteApiTypes.ts
  stockMinuteViewModelAdapter.ts
```

不修改 `lake_console/backend`，不从 production code import `lake_console` 或 `lake_console/orchestrator`。

## 4. 配置与部署隔离

新增配置必须通过统一 `Settings` 读取：

| 配置 | 默认值 | 本地 | 远程 |
|---|---:|---:|---:|
| `WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED` | `false` | `true` | `false` |
| `GOLDENSHARE_LAKE_ROOT` | 空 | 本地湖根目录 | 不配置 |
| `VITE_LOCAL_LAKE_MINUTE_API_ENABLED` | `false` | `true` | `false` |

后端只有在以下条件同时满足时启用：

1. flag 为 true。
2. `APP_ENV` 为 `dev` 或 `local`，禁止 prod/production/staging。
3. Lake root 为存在且可读目录。
4. 本地 `local-lake` optional extra 提供的 `duckdb` 可导入。

flag true 但 root 或依赖不满足时，本地启动 fail fast。flag false 时不得导入 DuckDB。

前端 flag 只控制入口显示，后端 capability 和 router gate 才是最终边界。远程 build 必须使用 false。

## 5. API 设计

### 5.1 分钟线

```http
GET /api/v1/wealth/market/stock-detail/minutes
```

参数：`tsCode`、`freq`、`startDate`、`endDate`、`limit`、`cursor`、`debug`。`freq` 必须显式传入，允许 `1/5/15/30/60/90/120`；`limit` 默认 500、最大 10000。

当前日线页面实际请求 300 根，但图表默认可视区为 90 根。分钟 API 的 500 根是首屏和有限拖动的缓冲量，不代表 300 个交易日历史窗口；需要更早数据时通过 cursor 分页读取。

响应包括：`tsCode`、`freq`、`bars[]`、`meta`、`dataStatus` 和可选本地 debug 信息。

### 5.2 分钟指标

```http
GET /api/v1/wealth/market/stock-detail/minute-indicators
```

参数与分钟线一致。`items[]` 返回 MACD DIF/DEA/柱值、K/D/J、`paramsKey`、`indicatorVersion`。

v1 不增加独立 `expectedEndDate` 参数：调用方传入的 `endDate` 既是查询上界，也是数据新鲜度期望日。股票详情页必须传 `pageContext.tradeDate`；未传 `endDate` 时不建立 delayed 期望日，空结果返回 `EMPTY`。传入 `endDate` 但无数据或 observed end 更早时，返回 `200 + dataStatus=DELAYED`。

### 5.3 不扩展现有日线 kline

本轮不把 `period=min` 塞进现有日线 `kline`，避免改变远程日线契约、数据源和性能边界。

## 6. Reader 与查询策略

### 6.1 Reader API

`StockMinsLakeReader` 提供 `read_bars(ts_code, freq, start_date, end_date, limit, cursor)` 和 `read_indicators(...)`。

它负责代码/频率/路径校验、目标年份文件规划、单次 DuckDB 查询、字段投影、排序、分页和有限结果校验。它不触发任务、不读事件历史、不写文件、不访问 Prod DB。

### 6.2 路径与 schema

分钟线路径为 `gold/quote/stk_mins_qfq/freq={freq}/ts_code={ts_code}/year={year}/part-000.parquet`。

指标路径为 `gold/indicator/stk_mins_qfq_macd_kdj/freq={freq}/ts_code={ts_code}/year={year}/part-000.parquet`。

路径 resolve 后必须仍位于 configured root 下。请求只扫描日期涉及的年份文件，最多 3 个年份。

### 6.3 SQL 硬约束

分钟线只投影：`ts_code, freq, trade_date, trade_time, open, high, low, close, vol, amount, exchange`。

指标只投影：`ts_code, freq, trade_date, trade_time, macd_dif_qfq, macd_dea_qfq, macd_qfq, kdj_k_qfq, kdj_d_qfq, kdj_qfq, params_key, indicator_version`。

查询必须绑定 `ts_code/freq/start/end/cursor/limit`，按 `(trade_date, trade_time)` 升序。禁止 `SELECT *`、全湖扫描、无界 OFFSET 和 Python 逐行重算。

每次请求只创建一个短生命周期 DuckDB connection。SQL 使用 `LIMIT max_limit + 1` 或有界 `fetchmany` 判断 `hasMore`，不得读取无界结果。

## 7. Backend 分层

### API 层

`stock_detail_minutes.py` 只做 Query 参数解析、`require_quote_access`、边界校验、service 调用和异常映射。

### Query service 层

负责默认日期窗口、reader 调用、`dataStatus`、meta 和 DTO 映射。不拼接 bars 与 indicators 为另一套事实对象。

### Schema 层

新增模块 DTO，字段使用 lowerCamelCase，`extra=forbid`。指标值允许 NULL，时间统一保留北京时间语义。

## 8. 前端实施

1. 新增独立 `stockMinuteApiClient.ts`，不把分钟参数并入现有日线 client。
2. 读取现有 `page-init.capabilities.supportsMinute`。
3. 本地 build flag 和后端 capability 均为 true 时显示分钟频率入口。
4. 切换频率后并行请求分钟线和指标接口。
5. 两个 DTO 分别 adapter，再按 `(tradeDate, tradeTime)` 合并为图表 ViewModel。
6. 指标 NULL 保持 NULL，不用 0 替换。
7. real 请求失败显示分钟模块 error，不静默回退 mock。

## 9. 状态与异常

建议先在 `wealth/docs/system/exception-code-registry.md` 登记：

| code | 触发 | HTTP | 前端行为 |
|---|---|---:|---|
| `SM_LOCAL_LAKE_NOT_CONFIGURED` | 本地启用但 root/依赖无效 | 503 | 本地能力错误 |
| `SM_SOURCE_NOT_READY` | 文件不存在或范围未覆盖 | 200 | `dataStatus=DELAYED` |
| `SM_SOURCE_CONTRACT_INVALID` | schema/身份/时间键错误 | 503 | 模块 error |
| `SM_QUERY_FAILED` | DuckDB/IO 失败 | 503 | 模块 error |
| `SM_REQUEST_INVALID` | 参数非法 | 400 | 保留其它页面内容 |

未登记前不得进入代码契约。

## 10. 性能门禁

| 项 | 目标 | 硬上限 |
|---|---:|---:|
| 单接口 P95 | 1.5s | 5s |
| 单次返回 | 500 行默认 | 10000 行硬上限 |
| 返回体 | 2MB | 5MB |
| 年份文件 | 1 至 2 | 3 |
| event history 调用 | 0 | 0 |
| Lake 写入 | 0 | 0 |
| 无界全湖扫描 | 0 | 0 |

超限时缩小窗口、降低 limit 或优化 reader，不通过提高 timeout 放行。

## 11. 里程碑

1. M0：冻结 API、显式频率、500 根默认返回、字段和异常码。
2. M1：optional dependency、Settings、router gate、Lake reader。
3. M2：backend schema、query service、两个真实 route。
4. M3：wealth client、adapter、分钟图表入口。
5. M4：本地真实联调和远程负向验证。

## 12. 版本记录

| 版本 | 日期 | 变更摘要 |
|---|---|---|
| v1 | 2026-07-31 | 初版，细化 local/prod 隔离、reader、接口和性能方案 |
| v1.1 | 2026-07-31 | 冻结 500 根默认返回、显式频率、DELAYED 状态和 local-lake 依赖边界 |
| v1.2 | 2026-07-31 | 明确 `endDate` 的期望日语义并同步指标响应契约 |
