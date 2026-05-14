# 市场总览｜新闻速览与个股新闻技术实施方案 v1

> 对应需求文档：`market-news-benchmark-requirement-v1.md`  
> 阶段：编码前。  
> 产物性质：实现设计基线（不写业务代码）。

---

## 1. 文档目的

1. 对应需求文档：`wealth/docs/pages/market-overview/market-news-benchmark-requirement-v1.md`
2. 本文目标：
   - 将 Review v9 / `market-overview-v1.8.html` 中有效的新闻板块需求转为当前 `wealth` 架构下可实施的模块方案；
   - 明确 API、后端目录、前端目录、状态、配置、测试门禁；
   - 阻断旧 `/api/market/home-overview` 与旧顶部快讯条方案回流。
3. 本文不做：
   - 不写代码；
   - 不实现新闻详情页；
   - 不改变其它市场总览模块；
   - 不处理用户侧新闻订阅；
   - 不把 update 文档中的其它页面改动纳入本轮。
4. 跨模块抽象门禁原则适配结论：本模块适用全部 8 条原则，其中配置、排序、测试和事实源单一是高风险重点。

---

## 1.1 跨模块抽象门禁原则适配

| 原则 | 本模块结论 | 设计落点 | 计划测试 |
|---|---|---|---|
| 事实源单一原则 | 后端两个独立接口分别产出新闻速览和个股新闻事实 | `/api/v1/wealth/market/news/briefs`、`/api/v1/wealth/market/news/stocks` + view-model adapter | 后端 API 断言字段齐全；前端真实 API 展示断言 |
| 契约先行与冻结原则 | `NewsListPanel/NewsPanelItem` 字段冻结；页面侧 `MarketNewsPanelGroup` 只负责组合 | schema + TypeScript 类型 | 契约字段快照测试 |
| 配置一致性原则 | `visibleItemCount` 与 `queryLimit` 走策略配置中心，默认 10 条可见、每板块 300 条候选 | `market_news.cn_a.v1.json` | 配置读取测试 + 非法配置失败测试 |
| 默认行为显式原则 | 不用旧日新闻冒充目标日 ready | status resolver | 空数据/partial/delayed 测试 |
| 排序与筛选确定性原则 | `publishTime desc -> priority desc -> newsId asc` | query service | 同时间排序稳定测试 |
| 性能预算前置原则 | 每板块默认查询 300 条候选新闻，字段少、索引按时间命中 | SQL 查询只取必要列 | API 耗时测试 |
| 可观测与异常标准化原则 | `NEWS_*` 异常码统一注册 | exception builder + debugInfo | debug 面板字段测试 |
| 测试以用户可见结果为中心原则 | 时间、标题、不可点击、滚动是主断言 | 前端 smoke | 真实 API 驱动展示测试 |

---

## 2. 代码现状审计（基于真实代码）

### 2.1 当前已有前端落点

1. 页面装配：`wealth/src/pages/market-overview/MarketOverviewPage.tsx`
2. 模块 source 开关：`wealth/src/features/market-overview/api/moduleSources.ts`
3. 市场总览 mock 根类型：`wealth/src/features/market-overview/api/marketOverviewTypes.ts`
4. 当前页面首屏组合：`summary-index-row` 只包含 `MarketSummaryPanel` 与 `MajorIndexPanel`。

### 2.2 当前已有后端落点

1. 已存在 wealth market 模块化 API 目录：
   - `src/biz/api/wealth/market/`
   - `src/biz/queries/wealth/market/<module>/`
   - `src/biz/schemas/wealth/market/`
   - `src/biz/services/wealth/market/<module>/`
2. 已存在策略配置中心：
   - `src/biz/services/wealth/config/strategy_config_service.py`
   - `src/biz/services/wealth/config/definitions/*.json`
3. 已存在新闻类数据集定义：
   - `src/foundation/datasets/definitions/news.py`
   - `core_serving_light.news`

### 2.3 现有冲突与技术债

1. 历史 update 快照中的顶部中间统一快讯条已被作废，不能复用布局。
2. `wealth/docs/reference/showcase/market-overview-v1.8.html` 是新闻板块最新 UI 参考，已经采用两个独立 `.market-news-panel`。
3. 历史 update API 快照仍使用旧聚合接口 `GET /api/market/home-overview`，不能作为当前 API 路径依据。
4. 当前正式文档尚未登记新闻模块的独立三件套、异常码和 API 路径。
5. 当前页面没有 news 模块 source 开关和 view-model adapter。

### 2.4 结论

新闻板块必须按独立模块新增，不允许塞回整页聚合，也不允许复用旧顶部快讯条。推荐模块 key：

```text
frontend module source key: news
debug module keys: newsBriefs / stockNews
API paths:
  - /api/v1/wealth/market/news/briefs
  - /api/v1/wealth/market/news/stocks
feature dir: wealth/src/features/market-overview/news/
backend dir: src/biz/**/wealth/market/news/
```

---

## 3. 分层架构与目录落点

### 3.1 接口范围

1. 模块接口路径：
   - 新闻速览：`GET /api/v1/wealth/market/news/briefs`
   - 个股新闻：`GET /api/v1/wealth/market/news/stocks`
2. 是否整页聚合接口：否。
3. 是否提供新闻组大聚合接口：否。页面侧 adapter 负责把两个接口响应组装成首屏双列展示。
4. 单个模块接口返回范围：
   - `newsWindow`
   - `pageStatus`
   - `newsBriefs` 或 `stockNews`
   - `debugInfo?`

### 3.2 后端目录模板

```text
src/biz/
  api/
    wealth/
      market/
        news_briefs.py
        stock_news.py
  queries/
    wealth/
      market/
        news/
          market_news_query.py
          stock_news_query.py
          news_query_service.py
          news_state_query.py
  schemas/
    wealth/
      market/
        news_briefs.py
        stock_news.py
  services/
    wealth/
      market/
        news/
          news_exception_builder.py
          news_status_resolver.py
          news_strategy_config_resolver.py
```

### 3.3 前端目录模板

```text
wealth/src/features/market-overview/
  news/
    MarketNewsPanelGroup.tsx
    MarketNewsPanel.tsx
    NewsTickerList.tsx
    NewsTickerItem.tsx
    api/
      marketNewsApi.ts
      marketNewsAdapter.ts
      marketNewsTypes.ts
```

### 3.4 配置文件模板

```text
src/biz/services/wealth/config/definitions/market_news.cn_a.v1.json
```

配置只面向运营，不面向用户。

---

## 4. 数据流与执行链路

1. 请求入口：
   - `src/biz/api/wealth/market/news_briefs.py`
   - `src/biz/api/wealth/market/stock_news.py`
2. 参数校验：
   - `market` 默认 `CN_A`
   - `debug` 可选，默认 `0`
3. 查询编排：
   - 读取策略配置；
   - 使用当前服务器自然时间生成 `newsWindow`，窗口为“昨日 00:00:00 到当前时刻”，时区 `Asia/Shanghai`；
   - `news/briefs` 只查询新闻速览；
   - `news/stocks` 只查询个股新闻；
   - 页面侧 adapter 合并两个接口的状态与异常，用于 debug 面板展示。
4. 状态归并：
   - 单接口有数据：`READY`
   - 单接口无数据：`EMPTY`
   - 页面侧一侧有数据、一侧为空：组合态 `PARTIAL`
   - 查询或配置失败：`ERROR`
5. 异常组装：使用 `NEWS_*` 异常码。
6. 响应输出：只返回新闻模块对象，不返回其它页面模块。

### 4.1 `v1.8` 前端结构还原要求

编码时必须按 `wealth/docs/reference/showcase/market-overview-v1.8.html` 的新闻模块结构还原，不允许回退到旧头部快讯条：

```text
summary-index-row
  summary-column
    MarketNewsPanel(title="新闻速览")
    MarketSummaryPanel
  summary-column
    MarketNewsPanel(title="个股新闻")
    MajorIndexPanel
```

结构要求：

1. `MarketNewsPanelGroup` 只负责组织左右两列，不承载业务查询。
2. `MarketNewsPanel` 对应 `.market-news-panel`，包含标题栏和 viewport。
3. `NewsTickerList` 对应 `.market-news-viewport` + `.market-news-track`。
4. `NewsTickerItem` 对应 `.market-news-item`，只渲染时间和标题。
5. `NewsTickerList` 必须按候选新闻条数设置滚动周期：`max(40s, items.length * 2s)`，避免候选池扩大到 300 条后滚动过快。
6. `PageHeader`、`TopMarketBar`、`Breadcrumb`、`ShortcutBar` 不允许承载新闻内容。

---

## 5. 查询编排策略

### 5.1 主查询：新闻速览

主源：

```text
core_serving_light.news
```

字段：

```text
row_key_hash, news_time, title, content, channels, src
```

规则：

1. 查询 `news_time` 落在 `newsWindow.startAt <= news_time <= newsWindow.endAt` 的新闻。
2. 筛选条件：`channels IS DISTINCT FROM '公司'`。
3. `content IS NULL` 或 trim 后为空字符串的行直接剔除。
4. 按 `content` 严格去重：相同 `content` 只保留 `news_time` 最新的一条。
5. `title` 为空但 `content` 有值时，由后端截取 `content` 前 80 字生成展示标题；前端不得拼接。
6. 排序：去重后按 `news_time desc, row_key_hash asc`。
7. 截断：每个板块按配置取 `queryLimit=300` 条候选新闻；前端只按 `visibleItemCount=10` 控制可见窗口。

### 5.2 主查询：个股新闻

主源：

```text
core_serving_light.news
```

字段：

```text
row_key_hash, news_time, title, content, channels, src
```

规则：

1. 查询 `news_time` 落在 `newsWindow.startAt <= news_time <= newsWindow.endAt` 的新闻。
2. 筛选条件：`channels = '公司'`。
3. `content IS NULL` 或 trim 后为空字符串的行直接剔除。
4. 按 `content` 严格去重：相同 `content` 只保留 `news_time` 最新的一条。
5. `title` 为空但 `content` 有值时，由后端截取 `content` 前 80 字生成展示标题；前端不得拼接。
6. 排序：去重后按 `news_time desc, row_key_hash asc`。
7. 本期不从标题中解析股票代码，也不做股票主数据关联；`subject` 可为空。

### 5.3 辅助查询

1. 本期不额外查股票名称表。
2. 本期不对新闻标题做股票代码解析。
3. 本期不使用 `anns_d`、`major_news` 或其它公告/新闻表。

### 5.4 空数据与异常数据处理

1. 必需字段缺失行丢弃，并在 debug 计数。
2. 单接口无可展示项时返回 `EMPTY`，不回退旧日。
3. 两个接口分别表达自己的状态；页面侧组合后若一侧为空、另一侧 ready，可在 debug 面板标记组合态 `PARTIAL`。
4. 查询失败返回当前接口 `ERROR`，不影响另一个新闻接口，也不影响其它市场总览模块。

### 5.5 默认行为与边界行为

1. 新闻接口不接收 `tradeDate`，也不使用页面全局 `tradingDay`。
2. `newsWindow.startAt` 固定为当前自然日前一天 00:00:00。
3. `newsWindow.endAt` 固定为当前服务器时间。
4. `visibleItemCount` 非法：配置错误，模块 error。
5. 新闻少于 `visibleItemCount`：展示实际数量，不补空行。

---

## 6. 状态与异常落地

### 6.1 pageStatus 归并规则

新闻模块不单独决定页面级状态。页面状态由市场总览现有归并规则决定。

### 6.2 moduleStatus 归并规则

| 条件 | moduleStatus | 说明 |
|---|---|---|
| 单接口有数据 | `READY` | 当前新闻板块正常展示 |
| 单接口无数据 | `EMPTY` | 当前新闻板块显示空态 |
| 页面侧一侧有数据、一侧无数据 | `PARTIAL` | 正式页展示已有列表；debug 标记缺失侧 |
| 查询异常或配置异常 | `ERROR` | 显示模块 error |
| 目标日无数据但旧日有数据 | `DELAYED` | debug 标记，不自动展示旧日 |

### 6.3 debug 输出结构

```ts
interface MarketNewsDebugInfo {
  modules: Array<{
    moduleKey: "newsBriefs" | "stockNews";
    expectedTradeDate: string;
    observedTradeDate?: string | null;
    lagDays?: number | null;
    status: "READY" | "PARTIAL" | "EMPTY" | "DELAYED" | "ERROR";
    note?: string | null;
  }>;
  exceptions: Array<{
    module: "newsBriefs" | "stockNews";
    code: "NEWS_CONFIG_MISSING" | "NEWS_CONFIG_INVALID" | "NEWS_SOURCE_EMPTY" | "NEWS_SOURCE_DELAYED" | "NEWS_CHANNEL_RULE_INVALID" | "NEWS_QUERY_FAILED";
    severity: "info" | "warn" | "error";
    message: string;
  }>;
}
```

### 6.4 异常码映射表

异常码必须来自 `wealth/docs/system/exception-code-registry.md`：

| code | 场景 |
|---|---|
| `NEWS_CONFIG_MISSING` | 新闻模块配置缺失 |
| `NEWS_CONFIG_INVALID` | `visibleItemCount` 或源配置非法 |
| `NEWS_SOURCE_EMPTY` | `core_serving_light.news` 按当前接口筛选规则无可展示数据 |
| `NEWS_SOURCE_DELAYED` | 目标日无数据但存在旧日新闻 |
| `NEWS_CHANNEL_RULE_INVALID` | `core_serving_light.news.channels` 取值无法支撑 `公司/非公司` 分类 |
| `NEWS_QUERY_FAILED` | SQL/服务异常 |

---

## 7. 性能与缓存策略

1. 性能预算：P95 `< 300ms`，payload `< 600KB`。
2. 首版策略：无 Redis 缓存，SQL 只按时间倒序取必要字段。
3. 二期缓存策略：如新闻量或页面并发增加，可按 `market + newsWindowEndMinute + configVersion` 做短期缓存。
4. 一致性策略：配置变更重启生效；新闻源更新后下一次请求读取最新数据。

---

## 8. 安全与权限

1. 鉴权依赖：沿用 wealth market API 现有鉴权基线。
2. 权限点：本期不新增独立权限点。
3. 防误用策略：
   - 不暴露 `visibleItemCount` 给用户；
   - 不暴露新闻来源选择给用户；
   - 不允许前端通过 query 参数修改新闻源或条数。

---

## 9. 测试与验证计划

1. 单元测试：
   - 配置解析；
   - view-model adapter；
   - 时间格式化；
   - 不可点击渲染。
2. 集成测试：
   - `GET /api/v1/wealth/market/news/briefs` 真实路由；
   - `GET /api/v1/wealth/market/news/stocks` 真实路由；
   - 配置缺失/非法路径；
   - newsBriefs/stockNews 空数据与页面侧 partial。
3. 冒烟验证：
   - 页面加载新闻模块；
   - 两列布局和下方模块等宽；
   - hover 暂停当前列；
   - 标题省略。
4. 失败回滚：
   - source 开关仅回滚 news 模块；
   - 不影响其它已 real 的模块。

### 9.1 核心测试 case（必填）

1. 核心字段清单：
   - `visibleItemCount`
   - `newsBriefs.items[].publishTime/displayTime/title/clickable`
   - `stockNews.items[].publishTime/displayTime/title/subject/clickable`
   - `title` 由后端生成：优先使用非空 `title`，否则截取 `content` 前 80 字；前端不得自行拼接。
   - `debugInfo.modules[].status`
   - `debugInfo.exceptions[].code`
2. 后端真实 API 集成测试：
   - `tests/web/test_wealth_market_news_api.py`
   - 禁止 mock service/query。
3. 前端真实 API 展示校验：
   - `wealth/src/test/market-overview-news-real-api.test.tsx`
   - 禁止 mock adapter。
4. 执行命令：

```bash
pytest -q tests/web/test_wealth_market_news_api.py
cd wealth
npm run test -- market-overview-news-real-api
npm run typecheck
npm run build
```

通过标准：

1. 两个后端接口分别返回对应列表对象和可追踪状态。
2. 前端展示时间 + 标题，不展示 pointer，不跳转。
3. 真实 API 未返回前保持 loading；超时显示 error。

---

## 10. 分期里程碑

1. M1（方案冻结）：
   - 三件套评审通过；
   - 真实数据源可用性确认；
   - 配置文件口径确认。
2. M2（后端实现）：
   - 新增 schema/api/query/service/config；
   - 注册异常码；
   - 后端真实 API 测试通过。
3. M3（前端接入）：
   - 新增 news feature；
   - 页面首屏插入新闻组；
   - source 开关切 real；
   - 前端真实 API 展示测试通过。
4. M4（回归发布）：
   - typecheck/test/build；
   - 页面视觉检查；
   - debug 面板确认。

---

## 11. 风险与缓解

| 风险 | 触发条件 | 缓解动作 |
|---|---|---|
| 旧顶部快讯条回流 | 直接照搬 v8 HTML 或 update 旧稿 | coding gate 明确禁止；页面测试断言不在 PageHeader 中渲染新闻 |
| 频道分类口径漂移 | `channels` 无 `公司` 或取值与预期不一致 | M2 前真实库探针；不可用则停下确认，不用其它源冒充 |
| 两个新闻接口重新耦合 | 为省事恢复单一大接口 | 门禁明确拆成 `/news/briefs` 与 `/news/stocks`，页面侧只做组合展示 |
| 新闻标题为空 | 源端只有 content | 后端明确标题生成策略后再启用；前端不截断 content |
| 新闻过多拖慢接口 | 查询未限制 | SQL limit + 索引时间倒序 + payload 预算 |
| 滚动交互影响可读性 | hover 暂停实现错误 | 前端 smoke 覆盖当前列暂停、另一列继续 |

---

## 12. 待拍板项

已确认清零。当前方案按以下口径冻结：

1. 默认展示 10 条。
2. 展示条数由运营配置控制，用户不可改。
3. P0 新闻 item 不可点击。
4. 不使用顶部统一快讯条。
5. 不使用旧聚合接口。

---

## 13. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-14 | 初版：按当前 wealth 模块化架构设计新闻模块实施方案 | Codex |
| v1.1 | 2026-05-14 | 校准 `market-overview-v1.8.html` 结构，补充前端组件还原边界 | Codex |
