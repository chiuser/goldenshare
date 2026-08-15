# 指数详情本地分钟 API / DTO 合同 v1

> 版本：`1.1.0`
> 状态：指数分钟交付已完成。P10 业务读取已切换并验收；bars 只读正式 Gold canonical bars，indicators 只读正式 Gold technical；没有 Silver、旧 Lake、staging 或 Mock fallback。七频合同、全历史对齐、性能、分页、局部状态、浏览器和生产隔离门禁均已闭环。切换与历史重建证据见 [A 股分钟线 Gold 标准 K 线合同与历史重建 LLD](../../../../lake_console/docs/design/dagster-cn-a-minute-gold-canonical-bars-rebuild-low-level-design.md)。
> 命名空间：`/api/v1/wealth/market/index-detail/*`

## 1. 边界

1. 本合同只在 `APP_ENV in {dev, local}`、本地分钟开关开启、正式 Lake 根可读且 DuckDB 可用时挂载；prod/staging 不挂载，访问返回 404。
2. bars 唯一读取 `/Volumes/datasource/data_lake/gold/quote/major_index_mins`；indicators 唯一读取正式 Gold `major_index_mins_technical`，不读取 Silver、state、旧 Lake 或 staging，也不保留 fallback。
3. Gold 1m 可返回 09:30；Gold 5m/15m/30m/60m/90m/120m 禁止返回独立 09:30，首根时间分别为 09:35/09:45/10:00/10:30/11:00/11:30。
4. bars 与 indicators 必须按完整 `tradeTime` 集合严格相等；不允许后端或前端自行补 bar、删 bar 或按数组位置对齐。
5. 七频均不得返回 `15:01-15:30`；完整交易日最后一根必须精确为 15:00，技术指标同样截止 15:00。
6. `899050.BJ` 属于页面十指数名单，但不在 Gold 源覆盖中；分钟 bars 返回 `EMPTY + IM_SOURCE_NOT_READY`。
7. Lake 中存在但不属于页面十指数名单的代码，例如 `000680.SH`，返回 `ID_NOT_FOUND`。
8. M5-A 前端开发态指标 Mock 不是 HTTP 接口返回值；M5-B 已删除 Mock provider、标识和专属测试，不保留双源兼容或错误 fallback。

## 2. 请求

### 2.1 路由

```http
GET /api/v1/wealth/market/index-detail/minutes
GET /api/v1/wealth/market/index-detail/minute-indicators
```

### 2.2 参数

| 参数 | 类型 | 必填 | 规则 |
|---|---|---:|---|
| `tsCode` | string | 是 | trim + upper；必须属于 `majorIndices/CN_A` 十指数名单 |
| `freq` | integer | 是 | 只允许 `1/5/15/30/60/90/120` |
| `startDate` | `YYYY-MM-DD` | 否 | 不得晚于 `endDate` |
| `endDate` | `YYYY-MM-DD` | 否 | 页面默认使用当前日线观测日 `asOfTradeDate`，保持分钟图表与右栏日频快照的时间边界一致 |
| `limit` | integer | 否 | 默认 500，范围 `1..10000` |
| `cursor` | string | 否 | v1 URL-safe base64；绑定 dataset/code/freq/start/end/before time |

未知参数、重复参数、非法日期、非法 limit、cursor 解析失败或 cursor 与当前请求错配均返回 HTTP 400 `ID_REQUEST_INVALID`。分页不使用 OFFSET。`10000` 是语法允许的请求上限，不代表任意 DTO 都能在 5MB 响应门禁内返回；5MB 门禁优先，调用方收到响应过大错误后必须降低 limit 并使用 cursor。

## 3. 响应 DTO

所有对象 `extra=forbid`，JSON 字段统一 lowerCamelCase。`tradeTime` 以带 `+08:00` 的 ISO-8601 返回。

### 3.1 通用分页与状态

```json
{
  "meta": {
    "count": 500,
    "limit": 500,
    "hasMore": true,
    "nextCursor": "...",
    "startDate": null,
    "endDate": "2026-08-11",
    "observedStartDate": "2026-08-08",
    "observedEndDate": "2026-08-11"
  },
  "dataStatus": {
    "status": "READY",
    "code": null,
    "expectedEndDate": "2026-08-11",
    "observedEndDate": "2026-08-11",
    "message": null
  }
}
```

`dataStatus.status` 只允许 `READY/DELAYED/EMPTY`。文件未覆盖、观测日期落后或已知源不支持时，`code="IM_SOURCE_NOT_READY"`；文件合同或查询错误走非 200 HTTP 错误，不返回伪 `ERROR` 状态。

### 3.2 Bars

```json
{
  "tsCode": "000001.SH",
  "freq": 5,
  "bars": [
    {
      "tsCode": "000001.SH",
      "freq": 5,
      "tradeDate": "2026-08-11",
      "tradeTime": "2026-08-11T09:35:00+08:00",
      "open": 3900.0,
      "high": 3902.0,
      "low": 3899.0,
      "close": 3901.0,
      "vol": 123456.0,
      "amount": 987654321.0,
      "exchange": "SSE"
    }
  ],
  "meta": {},
  "dataStatus": {}
}
```

不返回 `preClose/change/changePct/amplitude/turnoverRate/vwap`，前端不得自行伪造日线字段。

### 3.3 Indicators

```json
{
  "tsCode": "000001.SH",
  "freq": 5,
  "items": [
    {
      "tsCode": "000001.SH",
      "freq": 5,
      "tradeDate": "2026-08-11",
      "tradeTime": "2026-08-11T09:35:00+08:00",
      "ma5": 3900.2,
      "ma10": 3899.8,
      "ma20": 3898.6,
      "ma30": 3897.1,
      "ma60": 3894.3,
      "ma90": 3890.4,
      "ma250": null,
      "bollMiddle": 3898.6,
      "bollUpper": 3908.1,
      "bollLower": 3889.1,
      "macdDif": 1.2,
      "macdDea": 0.9,
      "macd": 0.6,
      "kdjK": 62.0,
      "kdjD": 57.0,
      "kdjJ": 72.0,
      "observationCount": 120,
      "paramsKey": "ma_5_10_20_30_60_90_250__boll_20_2__macd_12_26_9__kdj_9_3_3",
      "indicatorVersion": 1
    }
  ],
  "meta": {},
  "dataStatus": {}
}
```

MA/BOLL warm-up 不足时保持 null；MACD/KDJ 由 Gold 合同负责，不由 BFF 重新计算。

## 4. 异常

| HTTP | code | 语义 |
|---:|---|---|
| 400 | `ID_REQUEST_INVALID` | 参数、limit、文件数量上界或 cursor 不合法 |
| 404 | `ID_NOT_FOUND` | 非页面十指数名单 |
| 500 | `IM_SOURCE_CONTRACT_INVALID` | 路径、Parquet schema、身份、日期、时间键或版本不符合合同 |
| 500 | `IM_QUERY_FAILED` | DuckDB、文件 IO、查询或结果校验失败 |

401/403 沿用认证层。响应体超过 5MB 按 `ID_REQUEST_INVALID` 拒绝，调用方必须降低 limit 或使用 cursor。

## 5. M5-A Mock 退场与 M5-B 真实 provider 边界

1. M5-A 曾由 Vite 开发态 Mock 输入真实 bars，生成 `indicatorVersion=0` 的可见模拟指标；该实现只作为 Gold 落地前的阶段性开发能力。
2. M5-B 只调用本合同 `/minute-indicators`，以 `tradeTime` 与同窗口 bars 一一对齐；`paramsKey/indicatorVersion` 直接消费 Gold DTO，不在前端重算或改写。
3. bars 与 indicators 使用相同 `tsCode/freq/startDate/endDate/limit`，但请求生命周期相互隔离：bars 失败时分钟图表 ERROR；bars READY 且 indicators 失败、为空、身份错配或时间键不完整时，保留 K 线并将技术图层标为 PARTIAL。
4. indicators 失败不得清空 bars，不得回退 Mock，也不得用旧频率、旧指数或缓存中的其他指标补齐。
5. M5-B 已删除 Mock provider、`模拟指标` 标识及其专属测试；内部 ViewModel 只允许 `indicatorSource="gold"|"unavailable"`。

## 6. M5-B 正式验收与切换边界

1. Dagster Definitions 已能发现七频率 14 个 Gold 资产及 70 个 blocking checks：技术指标 42 个、状态 28 个。该项已经完成，不再与物理数据就绪状态绑定。
2. Web Reader 与 Orchestrator 的冻结合同必须由静态门禁逐项比较七频率、23 个技术指标列名与类型、`params_key` 和 `indicator_version`；测试只能读取 Orchestrator 源文件，不得让生产 Web 运行时 import Dagster 项目。
3. `/minute-indicators` 的临时 Parquet fixture 必须覆盖七频率、版本错误、重复时间键和 Gold technical 缺失隔离。technical 缺失或损坏不能影响同窗口 Gold bars 的独立读取结果。
4. 正式验收入口为：

```bash
uv run python -m src.scripts.audit_index_minute_gold --runs 10
uv run python -m src.scripts.audit_index_minute_gold --runs 10 --full-alignment --include-max
```

第一条执行七频率最新共同分区的合同、唯一键、Gold bars/Gold indicators 时间键对齐和默认 500 根性能矩阵；第二条是历史全量验收入口，不属于 P10 日常切换门禁。最大响应门禁必须同时验证：代表性 `limit=10000` 请求若超过 5MB，应正确返回 `ID_REQUEST_INVALID`；固定安全窗口 `limit=5000` 必须在 5MB 内正常返回，并验证 `hasMore/nextCursor`、下一页时间顺序和 5s 硬门禁。两条命令都固定只读正式 `/Volumes/datasource/data_lake`，不接收旧 Lake、staging 或自定义根目录。

5. 正式 Gold 根或任一频率尚无文件时，工具必须输出 `status=SOURCE_NOT_READY`、`code=IM_SOURCE_NOT_READY`，不得把缺失报告为通过，也不得触发 materialize、backfill、sensor、runless event 或任何 Lake 写入。
6. 正式 Gold 物理覆盖、全量时间键对齐、默认性能、10000/5MB 拒绝语义和 5000 根分页门禁通过后，前端已一次性切换真实 provider 并删除 Mock；本节数据门禁与前端门禁均已闭环。

### 6.1 2026-08-12 准备批次验收记录

1. 静态合同与 API fixture 共 42 项通过；覆盖七频率、错误版本、重复时间键、Gold 缺失隔离和现有 Reader 回归。
2. 子系统边界测试 14 项通过；生产 `src/**` 未增加 Orchestrator 运行时依赖，依赖矩阵不变。
3. 文档完整性、Ruff 和 `git diff --check` 通过。
4. 正式只读预检显示 Silver 七频率各有 4,276 个分区，Gold technical 七频率均为 0 个分区；验收工具按合同返回 `SOURCE_NOT_READY / IM_SOURCE_NOT_READY`，未执行性能矩阵，未产生任何写入。

### 6.2 2026-08-13 正式 Gold 验收记录

1. Dagster Definitions 当前发现七频率 14 个 Gold 资产和 70 个 checks，其中 technical 42 个、state 28 个；定向 Definitions/contract/check/sensor/bootstrap 测试 57 项通过。
2. 最终重跑时七频率 Silver 与 Gold technical 各有 4,277 个日期分区；29,939 个频率-日期分区对完成全历史 schema、版本、有限值、唯一键和双向时间键差集检查，缺失、多余和失败数均为 0。
3. Technical/state 正式文件共 59,878 个、总行数 10,150,506；本轮正式 Lake 和 Dagster 写入均为 0。
4. 页面可用九个指数、七频率、每组 10 次、默认 500 根共 630 个只读查询样本全部 READY；频率级 P95 为 282.243–322.982ms，低于 1.5s 目标和 5s 硬门禁。
5. 代表性上证 1 分钟 `limit=10000` 在 408.752ms 内因超过 5MB 正确返回 `ID_REQUEST_INVALID`；固定 `limit=5000` 返回 3,181,443 bytes，耗时 334.441ms，cursor 与下一页时间顺序均有效。
6. 首轮全历史执行恰逢 2026-08-12 Silver 新分区先于部分 Gold 落地，30/60/90/120 分钟按合同返回 `SOURCE_NOT_READY`；待七频率追平后从头重跑并得到上述 READY 结果，证明工具不会把变化中的覆盖状态误判为通过。
7. 前端已同时请求同窗口 bars/indicators，真实 MA/BOLL/MACD/KDJ 可见；1/60/120 分钟、七字段 Tooltip、北证50局部 EMPTY 与切回日线均通过 1600×1200 浏览器验收，日线与分钟图表区/右栏几何差值为 0px，页面无 `模拟指标` 文案。

## 7. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| 1.1.0 | 2026-08-14 | 完成 P10：bars 从历史 Silver 合同切换到正式 Gold canonical bars，无 fallback；同步七频时间键和本地业务读取验收口径 | Codex |
| 1.0.4 | 2026-08-13 | 完成真实 Gold provider、bars-only Partial、Mock 清零和浏览器验收；以 4,277×7 分区最终重跑更新全历史、性能、10000 拒绝与 5000 正常分页证据 | Codex |
| 1.0.3 | 2026-08-13 | 回填正式 Gold 全历史覆盖、对齐和性能证据；澄清 10000 参数上限与 5MB 优先门禁，冻结 10000 拒绝语义 + 5000 正常分页验收；定义真实 provider、bars-only PARTIAL 和 Mock 彻底退场边界 | Codex |
| 1.0.2 | 2026-08-12 | 记录 70 checks 注册已完成，冻结跨边界合同静态门禁、七频率异常 fixture 与只读正式 Gold 验收入口；物理覆盖、对齐、性能和前端切换继续留在 M5-B | Codex |
| 1.0.1 | 2026-08-11 | 回填 M5-A 实现状态与验收：七频率、cursor/5MB/5000 分区门禁、正式 Silver 性能、北证50 EMPTY、开发态 Mock v0 与生产 404 均通过 | Codex |
| 1.0.0 | 2026-08-11 | 冻结 local-only 双接口、Silver bars、Gold indicators、状态/异常/cursor/5MB 边界与 M5-A 开发态 Mock 例外 | Codex |
