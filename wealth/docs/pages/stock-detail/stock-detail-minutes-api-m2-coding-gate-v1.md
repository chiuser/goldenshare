# 股票详情分钟线与分钟技术指标 API M2 编码前门禁 v1

> 需求：[benchmark](./stock-detail-minutes-api-benchmark-requirement-v1.md)
> 方案：[implementation design](./stock-detail-minutes-api-implementation-design-v1.md)
> LLD：[low-level design](./stock-detail-minutes-api-low-level-design-v1.md)

## 1. 开工前硬门禁

1. [x] 已确认使用 `minutes` 与 `minute-indicators` 两个接口。
2. [x] 已确认七种频率均支持，`freq` 必须显式传入，默认返回 500 根，最大返回量仍受性能门禁约束。
3. [x] 已确认首版不返回 `preClose/change/pctChg`。
4. [ ] 已登记分钟模块异常码。
5. [x] 已冻结 local/prod 配置矩阵。
6. [x] 已确认远程不安装 `local-lake` optional extra；DuckDB 只在本地 extra 中提供。
7. [x] 已确认远程 route 不存在，而不是 route 内返回空数据。
8. [x] 已确认 reader 不 import `lake_console`。
9. [x] 已确认 API 不读 Dagster event history、不触发任务、不写湖。

## 2. 路由与环境门禁

必须支持：

```text
/api/v1/wealth/market/stock-detail/minutes
/api/v1/wealth/market/stock-detail/minute-indicators
```

必须满足：

1. local flag true 且 `APP_ENV=dev/local` 时挂载。
2. remote `APP_ENV=prod/production/staging` 时不挂载。
3. remote `WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED=false`。
4. remote `GOLDENSHARE_LAKE_ROOT` 可为空。
5. remote import graph 不触碰 DuckDB。
6. 既有日线接口行为不变。

## 3. 数据与字段门禁

分钟线只允许来源 `gold/quote/stk_mins_qfq`，指标只允许来源 `gold/indicator/stk_mins_qfq_macd_kdj`。

禁止：

1. 使用 raw/silver 代替 Gold qfq。
2. 读取 MACD/KDJ state 文件作为展示数据。
3. API 内重新计算指标。
4. `SELECT *`。
5. 把 NULL 指标转成 0。
6. 添加当前 Gold 合同不存在的 `preClose/change/pctChg`。

## 4. 请求门禁

1. `tsCode` 必填并严格校验。
2. `freq` 只能是 `1/5/15/30/60/90/120`。
3. 日期区间不能反向。
4. 默认 `limit=500`，最大 `10000`。
5. cursor 必须基于时间键，不得用无界 OFFSET。
6. 不允许全市场或缺少股票代码的请求。
7. 用户不能传 Lake root、文件路径或 SQL。
8. `endDate` 同时作为查询上界和期望结束日；页面必须传 `pageContext.tradeDate`，省略时不得凭空判定 `DELAYED`。

## 5. 核心测试门禁

### 5.1 后端真实 API

必须使用真实 FastAPI route 和临时/真实本地 Lake reader，不能只 mock service：

1. local profile 两个接口返回真实核心字段。
2. prod profile 两个接口路由不存在。
3. remote import 不加载 DuckDB。
4. 单年/跨年结果按时间升序。
5. cursor 翻页无重复、无遗漏。
6. bars 与 indicators 时间键可对齐。
7. schema 错、文件缺失、IO 错有明确状态。
8. 指标 NULL 仍为 NULL。
9. 无权限访问被拒绝。

### 5.2 前端真实 API

1. 本地 `supportsMinute=true` 显示频率入口。
2. 远程 `supportsMinute=false` 隐藏频率入口。
3. 真实分钟 API 返回后显示 OHLCV。
4. 真实指标 API 返回后显示 MACD/KDJ。
5. API error 不回退 mock。
6. delayed/empty 状态可见且不污染日线。

## 6. 性能门禁

| 指标 | 目标 | 硬上限 |
|---|---:|---:|
| 单接口 P95 | 1.5s | 5s |
| 单次返回 | 500 行默认 | 10000 行硬上限 |
| 返回体 | 2MB | 5MB |
| 年份文件 | 1 至 2 | 3 |
| Dagster event history | 0 | 0 |
| Lake 写操作 | 0 | 0 |
| 无界全湖扫描 | 0 | 0 |

超限必须缩小日期范围、降低 limit 或优化 reader，不能只调高 timeout。

## 7. 8 条抽象原则映射

| 原则 | 是否适用 | 落点 | 测试 |
|---|---|---|---|
| 事实源单一 | 是 | Gold qfq 和 Gold indicator 文件 | source path/field |
| 契约冻结 | 是 | DTO、字段、状态 | schema/API |
| 配置一致 | 是 | Settings 与 Vite flags | profile |
| 默认显式 | 是 | freq/window/limit | parameter |
| 排序确定 | 是 | tradeDate/tradeTime | pagination |
| 性能前置 | 是 | reader limits/P95 | benchmark |
| 异常标准化 | 是 | exception registry/dataStatus | error matrix |
| 用户结果优先 | 是 | real route/UI smoke | frontend API |

## 8. 历史经验复盘

1. [ ] 没有把 `lake_console/backend` 作为生产业务 API。
2. [ ] 没有让远程访问本地 Lake。
3. [ ] 没有让远程依赖本地配置或 DuckDB。
4. [ ] 没有把全湖扫描放入 HTTP 请求。
5. [ ] 没有用 Dagster event history 判断 API 是否 ready。
6. [ ] 没有由前端计算或补造指标。
7. [ ] real 失败不静默回退 mock。
8. [ ] 不改变既有日线详情契约。

## 9. 验证命令

后端：

```bash
pytest -q tests/web/test_wealth_stock_detail_minutes_api.py
```

前端：

```bash
cd wealth
npm run typecheck
npm run test
npm run build
```

本地真实联调：

```bash
WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED=true \
APP_ENV=dev \
GOLDENSHARE_LAKE_ROOT=/Volumes/datasource/data_lake \
uv run goldenshare-web
```

远程负向验证：

```bash
WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED=false \
APP_ENV=prod \
uv run goldenshare-web
```

## 10. 签字清单

### 后端

1. [x] reader SQL、路径安全和 limit 已确认。
2. [x] remote 不加载本地依赖已确认。
3. [x] 异常码和状态语义已确认：未准备好使用 `200 + dataStatus=DELAYED`。

### 前端

1. [ ] `/wealth/` 本地入口和分钟交互已确认。
2. [ ] 远程构建隐藏分钟入口已确认。
3. [ ] real error 不回退 mock 已确认。

### 架构/产品

1. [ ] API 路径和字段已确认。
2. [ ] 本地/远程边界已确认。
3. [ ] 性能预算可接受。

## 11. 版本记录

| 版本 | 日期 | 变更摘要 |
|---|---|---|
| v1 | 2026-07-31 | 初版，形成编码前门禁 |
| v1.1 | 2026-07-31 | 同步已确认的频率、返回数量、状态和依赖安装门禁 |
| v1.2 | 2026-07-31 | 同步 `endDate` 的查询上界与 freshness 期望日语义 |
