# 股票详情九转纵向切片 M2 编码前门禁 v1

> 状态：2026-08-13 M2 已收口；后续 M3-C、M4-B 与 M5 均已完成，M6-0 发布准备审计与测试稳定性修复已于 2026-08-15 完成并通过，M6-A 尚未开始。用户已取消登录态正式 P95 与生产 45/180 根截图两项 M3-C 补充验收；四个分钟正式资产也已完成无价格八列迁移。日线冗余价格与自然更新阻塞已移交独立专项，不属于本门禁退出条件。sensor 状态只引用总方案第 3.3 节带时间戳的最近快照，不将其写成未经刷新确认的实时状态。
>
> 总方案：[股票与主要指数详情页九转接入总方案 v1](./detail-page-nine-turn-integration-implementation-design-v1.md)
>
> LLD：[股票与主要指数详情页九转接入低层设计 v1](./detail-page-nine-turn-integration-low-level-design-v1.md)
>
> 异常码：[异常码注册表](./exception-code-registry.md)
>
> 正式视觉：[Goldenshare Web](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web?m=dev)

---

## 1. 本轮目标与范围

M2 只交付股票九转的一条可验证纵向切片：

1. 日线只读自主 QFQ Gold 的正式 PostgreSQL serving 投影。
2. 本地 30/60/90/120 分钟只读正式 Lake 九转文件。
3. 五个支持周期共享同一 DTO、请求状态和 `NineTurnMarkerPrimitive`。
4. 股票日线及支持分钟周期可在现有 K 线主图绘制 1～9 标记。
5. 九转失败只降级自身，不清空 K 线、技术指标或右栏。

本轮不做：

1. 不创建指数九转资产、API、serving 或页面接入。
2. 不修改股票既有五个九转资产的公式、key、路径或历史文件。
3. 不支持股票 1/5/15 分钟九转；前端必须零请求。
4. 不启用 sensor，不执行 materialize、backfill、runless event、正式 Lake 写入或生产数据库迁移。
5. 不使用 Tushare 九转、Mock、客户端计算或隐式 fallback。
6. 不新增交易动作、Tooltip、hover 或 marker 点击事件。

## 2. 开发事实与当前基线

1. 当前分支固定为 `dev-interface`，不创建额外分支或 worktree。
2. CodeGraph 已覆盖股票详情日线/分钟 API、页面控制器、共享图表、QFQ 九转资产和 serving publisher。
3. 股票五个自主 Gold 九转资产已存在：day、30、60、90、120。
4. 正式文件保留 10+ 真实计数；页面只消费 1～9。
5. 分钟 Parquet 内 `freq` 的真实类型为 `INTEGER`；Reader 必须设置 `hive_partitioning=false`。
6. 当前 Alembic head 为 `20260813_000134`；九转迁移只能以它为 `down_revision`。该 head 属于其它任务，本轮不得修改。
7. 当前工作区存在板块速览任务的未提交文件；本轮不得覆盖、删除或暂存这些文件。

## 3. 总门禁清单

1. [x] 产品周期与禁用周期冻结。
2. [x] 资产事实与页面 marker 投影边界冻结。
3. [x] PostgreSQL serving schema、事务发布和 read-back 冻结。
4. [x] 本地分钟 Reader 路径、schema、分页与安全门禁冻结。
5. [x] 本轮股票日线/分钟 endpoint 的参数和 DTO 冻结。
6. [x] `NT_*` 异常码已登记；股票与指数后端及页面消费均已升级为 active。
7. [x] page-init capability 与 router 使用同一能力判定。
8. [x] shared primitive 几何、生命周期、autoscale 和图层顺序冻结。
9. [x] 缓存、取消、request id 和局部重试行为冻结。
10. [x] 性能、测试、视觉、架构和回滚门禁冻结。
11. [x] 非目标范围与禁止项均有负向测试或静态检查落点。
12. [x] 用户已确认 LLD，并明确授权收口门禁后进入 M2。

## 4. 硬口径到代码与测试映射

| 编号 | 硬口径 | 代码落点 | 正向验证 | 负向验证 |
|---|---|---|---|---|
| M2-01 | 股票只认自主 QFQ Gold/serving | 日线 serving asset、日线 query、分钟 Reader | fixture 行逐根映射 | 查询和 import 中不存在旧 Tushare view |
| M2-02 | 只画 1～9 | Biz marker mapper | 1、5、9 输出 | 0、null、10、19 不输出 |
| M2-03 | 股票仅 day/30/60/90/120 | capability、API、registry | 五周期各有用例 | 1/5/15 零请求或 HTTP 400 |
| M2-04 | 日线所有环境只读 PostgreSQL | ORM/query | 日线 fixture READY | serving 缺失不回退 Lake/Tushare |
| M2-05 | 分钟只在 local/dev | capability、App router | local 路由存在 | prod 路由 404且不 import Reader |
| M2-06 | 分钟只读正式 Lake | contract/Reader | 正式路径 fixture | 旧 Lake、staging、symlink、越界拒绝 |
| M2-07 | 分页以 bar 窗口为基准 | daily query、minute Reader | limit+1/cursor | cursor 跨 code/freq/window 拒绝 |
| M2-08 | 九转独立降级 | controller、status accessory | PARTIAL 仍画已确认 marker | 九转错误不清空 K 线/指标 |
| M2-09 | primitive 稳定 | `NineTurnMarkerPrimitive`、chart adapter | `setMarkers()` 更新 | 响应变化不改变 chart `dataKey` |
| M2-10 | marker 不扩大纵轴 | primitive | 几何 golden | `autoscaleInfo()` 恒为 null |
| M2-11 | 无交易动作 | primitive/UI | 只读展示 | 无 click/hover/交易 handler |
| M2-12 | 不改现有 Gold 公式 | Orchestrator diff/golden | 既有 golden 全过 | asset key/path/formula 无漂移 |

## 5. 请求与响应冻结

### 5.1 日线

```http
GET /api/v1/wealth/market/stock-detail/nine-turn
```

参数：

```text
tsCode required
startDate optional YYYY-MM-DD
endDate optional YYYY-MM-DD
limit optional default 300, 1..2000
cursor optional opaque v1
debug optional 0|1
```

### 5.2 分钟

```http
GET /api/v1/wealth/market/stock-detail/minute-nine-turn
```

参数在日线基础上增加必填 `freq`，只接受 `30/60/90/120`；默认 `limit=500`，范围 `1..10000`。

两个接口都必须：

1. 使用 `require_quote_access`。
2. 拒绝未知参数和重复参数。
3. cursor 绑定 endpoint、stock、period、日期窗口和最后时间键。
4. 响应超过 5MB 时返回 `NT_REQUEST_INVALID`，不得截断 JSON。

### 5.3 DTO

```ts
interface NineTurnMarkerDto {
  tradeDate: string;
  tradeTime: string | null;
  direction: "UP" | "DOWN";
  sequenceNumber: 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9;
  completed: boolean;
}

interface NineTurnSeriesDto {
  subjectType: "stock";
  tsCode: string;
  period: "day" | "30" | "60" | "90" | "120";
  markers: NineTurnMarkerDto[];
  latestMarker: NineTurnMarkerDto | null;
  dataStatus: {
    status: "READY" | "DELAYED" | "EMPTY" | "PARTIAL";
    code: string | null;
    message: string | null;
    expectedEndDate: string | null;
    observedEndDate: string | null;
  };
  meta: {
    sourceRowCount: number;
    matchedRowCount: number;
    missingRowCount: number;
    markerCount: number;
    limit: number;
    hasMore: boolean;
    nextCursor: string | null;
    startDate: string | null;
    endDate: string;
    observedStartDate: string | null;
    observedEndDate: string | null;
    comparisonLag: 4;
    signalThreshold: 9;
    formulaVersion: 1;
  };
  debugInfo: Record<string, unknown> | null;
}
```

## 6. 数据查询与发布门禁

### 6.1 日线 serving

新表固定为 `core_serving.equity_qfq_nineturn_daily`：

```text
ts_code VARCHAR(16) NOT NULL
trade_date DATE NOT NULL
close_qfq DOUBLE PRECISION NOT NULL
up_count INTEGER NOT NULL
down_count INTEGER NOT NULL
nine_up_turn VARCHAR(2) NULL
nine_down_turn VARCHAR(2) NULL
formula_version SMALLINT NOT NULL
published_at TIMESTAMPTZ NOT NULL
PRIMARY KEY (ts_code, trade_date)
INDEX (trade_date, ts_code)
```

publisher 固定流程：Gold 合同校验 → 单交易日 delete → 批量 insert → read-back 完整键与内容 hash → commit。任一异常 rollback。M2 只实现并以隔离 fixture 验证，不执行生产发布。

日线 API 先由 `equity_factor_pro` 确定 bar 窗口，再左连接新 serving 表；`limit` 是 bar 根数，不是 marker 数量。

### 6.2 分钟 Reader

固定路径：

```text
gold/quote/stk_mins_qfq/freq=<freq>/ts_code=<code>/year=<year>/part-000.parquet
gold/indicator/stk_mins_qfq_nineturn/freq=<freq>/trade_date=<date>/part-000.parquet
```

Reader 必须固定投影、`hive_partitioning=false`、先裁剪分区后集合连接；最多扫描 5,000 个分区，结果严格升序且时间键唯一。

## 7. 状态和异常矩阵

| 条件 | HTTP/数据状态 | 页面行为 |
|---|---|---|
| bar 与九转全部对齐 | 200 READY | 绘制 1～9 |
| 数据完整但窗口无 1～9 | 200 READY | 局部 EMPTY，不报错 |
| bar 有、九转零匹配 | 200 EMPTY / `NT_SOURCE_NOT_READY` | K 线保留，显示源未覆盖 |
| 部分 bar 缺九转 | 200 PARTIAL / `NT_ALIGNMENT_PARTIAL` | 只画已确认 marker |
| observed 落后显式 endDate | 200 DELAYED / `NT_SOURCE_NOT_READY` | 保留已有 marker并提示延迟 |
| 参数/cursor/响应越界 | 400 `NT_REQUEST_INVALID` | 不重试 |
| 股票不存在 | 404 `NT_NOT_FOUND` | 沿用股票详情 not-found |
| schema/path/key 违约 | 500 `NT_SOURCE_CONTRACT_INVALID` | 九转局部 error |
| SQL/DuckDB/IO 异常 | 500 `NT_QUERY_FAILED` | 九转局部 error，可重试 |
| 403 | 403 | 九转局部 FORBIDDEN，不转 EMPTY |

## 8. 共享 primitive 门禁

1. 单一 `NineTurnMarkerPrimitive` 同时支持 daily/minute，为后续指数复用。
2. 18×18 CSS px；UP 位于 high 上方 8px，DOWN 位于 low 下方 8px。
3. 1～8 普通数字；9 使用方向色、1px 描边、2px 圆角。
4. 红涨绿跌，使用行情 token，不复用 success/error。
5. 只遍历 visible logical range。
6. `autoscaleInfo()` 恒为 null。
7. stable instance + `setMarkers()`；数据变化不能重建 chart。
8. 不提供 Tooltip、hover、click 或交易行为。

## 9. 配置审计

本轮不新增配置：

| 配置 | 当前来源 | M2 用途 | 生效方式 |
|---|---|---|---|
| `APP_ENV` | env/Settings | local/dev 与 production 隔离 | 启动时 |
| `WEALTH_LOCAL_LAKE_MINUTE_API_ENABLED` | env/Settings | 分钟总开关 | 启动时 |
| `GOLDENSHARE_LAKE_ROOT` | env/Settings | 必须是正式 Lake 根 | 启动时 |
| DuckDB optional dependency | runtime | 本地 Reader 门禁 | 启动时 |

九转日线 capability 由常驻日线 API 决定；分钟 capability 由上述配置和对应 Gold 目录共同决定。page-init 与 App router 必须复用同一 resolver。

## 10. 性能门禁

1. 日线默认 300、最大 2,000；分钟默认 500、最大 10,000。
2. API P95 目标不高于 1.5 秒，硬门禁 5 秒。
3. 响应体上限 5MB；Reader 文件上限 5,000。
4. 日线 SQL 命中 `(ts_code, trade_date)` 主键/索引。
5. 分钟只投影时间键与九转字段，不读取无关列。
6. primitive 每帧只处理可见 marker，不遍历完整历史。
7. 同缓存 key 不重复请求，切周期和局部重试不重建 K 线。

## 11. 验证矩阵

后端：

1. migration upgrade/downgrade SQL、ORM registry 和架构依赖测试。
2. publisher schema、批量写入、rollback、read-back/hash、`hive_partitioning=false`。
3. 日线/分钟 READY、EMPTY、DELAYED、PARTIAL、10+、严格参数、cursor、认证。
4. prod/local 路由矩阵；1/5/15 分钟负向。

Orchestrator：

1. 只运行隔离 pytest 与 Ruff；不连接正式 instance、Lake 或数据库。
2. serving asset metadata、catalog 和 dependency 静态测试。
3. 既有 QFQ 九转 golden、assets、checks、jobs、writer 回归。

前端：

1. DTO adapter、缓存、AbortController、request id、局部 retry。
2. primitive 1～9/10+、UP/DOWN、几何、visible range、空 autoscale、dispose。
3. 日线和四个支持分钟周期；1/5/15 零请求。
4. 九转故障不影响 K 线、指标、120 根默认视窗和缩放。
5. typecheck、全量 test、build；页面接入后执行浏览器网络与控制台验收。

## 12. 通用清单映射

| 原则 | 适用 | 落点 | 测试 |
|---|---|---|---|
| 事实源单一 | 是 | QFQ Gold/新 serving | Tushare fallback 静态负向 |
| 契约先行 | 是 | LLD、DTO、异常注册表 | 后端/前端同 fixture |
| 配置一致性 | 是 | 复用 local minute resolver | page-init/router 矩阵 |
| 默认行为显式 | 是 | day 300、minute 500 | 参数默认值测试 |
| 排序筛选确定性 | 是 | bar 时间升序、1～9 mapper | 重复/乱序/10+ 负向 |
| 性能预算前置 | 是 | 5MB、5,000 文件、P95 | 边界与性能测试 |
| 异常标准化 | 是 | `NT_*` | 每个 code 正反用例 |
| 用户可见结果 | 是 | marker 与局部状态 | 页面/primitive 测试 |
| 统计聚合下推 | 不适用 | 九转事实已在 Gold 计算 | 前端无公式静态检查 |
| 模块 source 开关 | 不适用 | 这是独立可选图层，不替换现有模块数据源 | 无 silent fallback 测试 |
| 图表显式 y 轴参数 | 不适用 | marker 不参与 autoscale | `autoscaleInfo=null` |

## 13. 文件边界

允许修改：

1. 本专项总方案、LLD、门禁、异常码和文档索引。
2. 九转 serving migration/model、Foundation Reader/contract、Biz schema/query/API、App router。
3. 既有股票 page-init capability 的九转字段。
4. Orchestrator 股票日线 serving publisher、prod DB contract、catalog/definition wiring和隔离测试。
5. `wealth/src/features/nine-turn/**`、共享 primitive、股票详情页面和图表 adapter 及测试。

禁止修改：

1. 指数详情、指数九转、指数 Gold 技术指标实现。
2. 股票 QFQ 九转公式、正式历史文件和现有 sensor default status。
3. 板块速览任务的未提交 migration/model/docs。
4. `src/platform/**`、`src/operations/**` 和旧 Lake Console 主链。

## 14. 回滚与退出条件

回滚顺序：先从 page-init 移除可用九转周期并停止请求，再回滚 router/API/UI；事实表和 Lake 文件不因前端回滚删除。禁止回退到 Tushare、Mock 或客户端计算。

M2 完成必须同时满足：

1. 股票日线和 30/60/90/120 的纵向切片代码、测试与文档对账完成。
2. 股票 1/5/15 九转零请求有测试。
3. 日线 serving 与分钟 Reader 均 fail closed。
4. shared primitive 不改变 autoscale、dataKey、默认 120 根或现有缩放。
5. 所有隔离测试、typecheck、build、架构护栏和 `git diff --check` 通过。
6. 未运行任何正式 Dagster、Lake 或生产数据库写动作。

### 14.1 M2 实施对账（2026-08-13）

1. 日线已实现独立 PostgreSQL serving model/migration、Gold 分区 publisher、事务 delete/批量 insert/read-back hash 和常驻查询 API；M3-A 审计时 migration 已执行但表为空，后续 M3-B 已完成 Gold 修复、全历史 serving 发布和最终逐日对账，当前进度以 M3 门禁文档为准。
2. 分钟已实现正式 Lake Reader 与条件路由，只开放 30/60/90/120；股票 1/5/15 在前端零请求、直调接口为 400。
3. 共享 `NineTurnMarkerPrimitive` 已实现 18×18、8px、红涨绿跌、完成态描边、可见区裁剪、空 autoscale 和稳定 `setMarkers()`。
4. 股票日线与分钟图表已复用同一 registry、adapter、primitive 和局部状态；九转变化不修改 chart `dataKey`，不重置现有 120 根视窗和缩放。
5. 正式 Lake 只读抽样 `000001.SZ` 各 500 根全部对齐：30/60/90/120 分钟分别扫描 59/104/170/254 个文件，耗时约 221.8/134.4/150.9/183.3ms，均低于 1.5s 目标。
6. 验证结果：前端 185 项全量测试、typecheck、production build 通过；九转/QFQ Orchestrator 27 项加 14 个子测试、静态门禁 99 项通过；Root 九转、股票/指数分钟和架构相关回归 85 项通过。Root 主链全量（排除冻结旧 Lake Console 目录）为 1548 passed、10 skipped、9 个既有非九转失败，失败涉及 Ops/ETF seed/CLI，与本轮文件无关。
7. M2 验收当时未执行 `dg`、materialize、backfill、runless event、Lake 写入、生产 migration、生产 publisher 或 sensor 启用；后续 M3 在逐阶段批准下完成 migration、Gold 修复、全历史 serving 发布和最终逐日对账，未启用 sensor，也未执行分钟历史生成。

### 14.2 后续阶段收口与 M6 剩余项

1. `20260813_000135`、Gold scoped rebuild、股票日线 serving 3,066/3,066 日全历史发布和最终逐日对账均已完成。
2. 生产日线 API 的真实窗口、状态、权限和代表性性能样本已验收；用户已取消至少 10 次同口径登录态 HTTP 正式 P95，不再列为 M3-C 或 M6 待办。
3. 1600×1200 日线 Loaded、代表分钟、切周期和缩放行为已验收；用户已取消生产 45/180 根边界截图，不再列为 M3-C 或 M6 待办。
4. 指数 M4-B 数据/API、M5 页面和 M6-0 发布准备审计均已完成；板块测试竞态已修复且 Wealth 全量回归通过。M6 剩余工作是受控推送部署、指数 sensor 计划/审批、下一交易日自然更新和最终生产验收，详见总方案第 12.1～12.2 节及 LLD 第 15.7 节。
5. 三个股票 sensor 的最近实例快照显示为 `RUNNING/SKIPPED`，但该快照未在本次文档更新中刷新；不能把历史状态当作实时状态，也不能把 `RUNNING` 等同于自然更新已投产。日线阻塞继续由独立数据治理任务处理。

## 15. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-08-13 | 基于已批准 LLD 冻结股票九转 M2 纵向切片范围、代码落点、正反测试、性能和环境门禁 | Codex |
| v1.1 | 2026-08-13 | 完成 M2 代码对账和隔离验收；登记正式 Lake 性能证据、全量回归结果及 M2 当时尚未执行生产 migration/发布的边界；M3 后续审计确认 migration 已完成但表为空 | Codex |
| v1.2 | 2026-08-13 | 回链 M3 当前事实：Gold 修复完成，serving 发布至 1,113/3,066 后暂停；sensor、生产浏览器和剩余历史仍未完成 | Codex |
| v1.3 | 2026-08-13 | 回链 M3-B 完成事实：serving 已发布 3,066 日、11,638,636 行并完成逐日对账；sensor 与生产浏览器仍未验收 | Codex |
| v1.4 | 2026-08-15 | 文档漂移收口：同步生产日线和分钟行为验收现状、分钟去价格合同迁移待办，并登记三个股票 sensor 实例实际 RUNNING/最近 tick 均 SKIPPED；历史 M2 禁止项继续只代表当时授权边界 | Codex |
| v1.5 | 2026-08-15 | 同步 M4-B/M5 完成事实，删除用户已取消的正式 P95 与 45/180 根截图待办；M6 仅保留发布、sensor、自然更新和最终生产验收，sensor 状态改为带时间戳快照口径 | Codex |
| v1.6 | 2026-08-15 | 同步 M6-0 通过：发布范围、生产基线与回滚点已审计，板块测试竞态已修复并通过 Wealth 232/232；M6-A 待独立审批 | Codex |
