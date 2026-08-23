# 市场总览｜新闻速览与个股新闻 M2 编码前门禁 v1

> 2026-08-23 增量说明：本文是首版列表实现的历史编码门禁。所有“不可点击”与 `clickablePolicy=disabled` 断言不再作为后续阅读器开发门禁；新实现必须先依据 [新闻弹窗阅读器技术实施方案 v1](./market-news-reader-implementation-design-v1.md) 形成独立 LLD 和编码门禁。其它来源、排序、时间窗与刷新规则继续有效。

> 对应需求文档：`market-news-benchmark-requirement-v1.md`  
> 对应实施方案：`market-news-implementation-design-v1.md`  
> 阶段：M2 开工前。  
> 产物性质：执行门禁清单（不通过不允许编码）。

---

## 1. 目的

1. 本门禁对应模块：新闻速览与个股新闻。
2. 本门禁对应需求文档：`wealth/docs/pages/market-overview/market-news-benchmark-requirement-v1.md`
3. 本门禁对应实施方案：`wealth/docs/pages/market-overview/market-news-implementation-design-v1.md`

---

## 2. 总门禁清单（全通过才能开工）

1. [ ] 参数与默认值冻结。
2. [ ] 响应结构冻结。
3. [ ] 核心样例响应冻结。
4. [ ] 查询草案冻结。
5. [ ] 状态归并样例冻结。
6. [ ] 异常覆盖矩阵冻结。
7. [ ] 性能预算冻结。
8. [ ] 真实数据源可用性确认。
9. [ ] 核心测试 case（真实 API + 前端展示）门禁冻结。
10. [ ] 跨模块抽象门禁原则（8 条）映射完成。
11. [ ] `wealth/docs/reference/showcase/market-overview-v1.8.html` 新闻面板结构已核对；未使用旧头部快讯条。

---

## 3. 请求与响应冻结

### 3.1 请求参数冻结

```ts
interface MarketNewsRequest {
  market?: "CN_A";
  debug?: 0 | 1;
}
```

参数校验规则：

1. `market` 仅支持 `CN_A`，缺省为 `CN_A`。
2. `debug` 可选，默认 `0`。
3. 新闻接口不接收 `tradeDate`；查询窗口由后端按“昨日 00:00:00 到当前服务器时间”生成。
4. 不允许用户通过请求参数修改 `visibleItemCount`。
5. 不允许用户通过请求参数选择新闻来源。

### 3.2 响应结构冻结

```ts
interface MarketNewsGroupViewModel {
  newsWindow: {
    market: "CN_A";
    startAt: string;
    endAt: string;
    timezone: "Asia/Shanghai";
  };
  pageStatus: {
    status: "READY" | "DELAYED" | "PARTIAL" | "EMPTY" | "ERROR";
    displayText: string;
    asOfTime?: string;
  };
  marketNews: {
    windowStartAt: string;
    windowEndAt: string;
    visibleItemCount: number;
    updatedAt: string;
    marketNews: NewsPanelItem[]; // 来自 /news/briefs
    stockNews: NewsPanelItem[]; // 来自 /news/stocks
    sortRule: "publishTime_desc_priority_desc";
    clickablePolicy: "disabled";
  };
  debugInfo?: {
    modules: DebugModuleStatus[];
    exceptions: DebugException[];
  };
}

interface NewsPanelItem {
  newsId: string;
  publishTime: string;
  displayTime: string;
  title: string;
  category: "market" | "stock";
  source?: string | null;
  subject?: {
    subjectType: "stock";
    subjectCode: string;
    subjectName?: string | null;
  } | null;
  priority?: number | null;
  url?: string | null;
  clickable: false;
}
```

后端不提供单一新闻组大接口。实际编码时拆为两个接口：

```http
GET /api/v1/wealth/market/news/briefs
GET /api/v1/wealth/market/news/stocks
```

两个接口均返回单板块对象，页面侧 adapter 再组合成上面的首屏双列 ViewModel。

---

## 4. 核心样例响应（最小集合）

本节样例是页面侧组合后的 ViewModel，用于校验前端双列展示。两个后端接口的单板块响应字段与 `newsBriefs.items[]` / `stockNews.items[]` 保持同构，编码时不得恢复单一后端大接口。

### 4.1 正常样例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "newsWindow": {
      "market": "CN_A",
      "startAt": "2026-05-07T00:00:00+08:00",
      "endAt": "2026-05-08T15:05:00+08:00",
      "timezone": "Asia/Shanghai"
    },
    "pageStatus": {
      "status": "READY",
      "displayText": "数据已就绪",
      "asOfTime": "2026-05-08 15:05:00"
    },
    "marketNews": {
      "windowStartAt": "2026-05-07T00:00:00+08:00",
      "windowEndAt": "2026-05-08T15:05:00+08:00",
      "visibleItemCount": 10,
      "updatedAt": "2026-05-08 15:05:00",
      "marketNews": [
        {
          "newsId": "news-row-hash-001",
          "publishTime": "2026-05-08 15:05:00",
          "displayTime": "05-08 15:05:00",
          "title": "央行公开市场开展逆回购操作，市场流动性保持合理充裕",
          "category": "market",
          "source": "sina",
          "priority": 0,
          "url": null,
          "clickable": false
        }
      ],
      "stockNews": [
        {
          "newsId": "news-company-row-hash-001",
          "publishTime": "2026-05-08 14:58:23",
          "displayTime": "05-08 14:58:23",
          "title": "某上市公司发布一季度经营进展",
          "category": "stock",
          "source": "sina",
          "subject": null,
          "priority": 0,
          "url": null,
          "clickable": false
        }
      ],
      "sortRule": "publishTime_desc_priority_desc",
      "clickablePolicy": "disabled"
    }
  },
  "traceId": "req_demo",
  "serverTime": "2026-05-08T15:05:01+08:00"
}
```

### 4.2 partial 样例

```json
{
  "marketNews": {
    "windowStartAt": "2026-05-07T00:00:00+08:00",
    "windowEndAt": "2026-05-08T15:05:00+08:00",
    "visibleItemCount": 10,
    "updatedAt": "2026-05-08 15:05:00",
    "marketNews": [],
    "stockNews": [
      {
        "newsId": "news-company-row-hash-001",
        "publishTime": "2026-05-08 14:58:23",
        "displayTime": "05-08 14:58:23",
        "title": "某上市公司发布一季度经营进展",
        "category": "stock",
        "clickable": false
      }
    ],
    "sortRule": "publishTime_desc_priority_desc",
    "clickablePolicy": "disabled"
  }
}
```

### 4.3 empty 样例

```json
{
  "marketNews": {
    "windowStartAt": "2026-05-07T00:00:00+08:00",
    "windowEndAt": "2026-05-08T15:05:00+08:00",
    "visibleItemCount": 10,
    "updatedAt": "2026-05-08 15:05:00",
    "marketNews": [],
    "stockNews": [],
    "sortRule": "publishTime_desc_priority_desc",
    "clickablePolicy": "disabled"
  }
}
```

### 4.4 error 样例

```json
{
  "code": 500,
  "message": "新闻模块查询失败",
  "data": null,
  "traceId": "req_error",
  "serverTime": "2026-05-08T15:05:01+08:00"
}
```

---

## 5. 查询草案（可直接转实现）

### 5.1 新闻速览

```sql
SELECT
  row_key_hash AS news_id,
  news_time AS publish_time,
  title,
  content,
  src AS source_name,
  channels
FROM core_serving_light.news
WHERE news_time >= :window_start_at
  AND news_time <= :window_end_at
  AND channels IS DISTINCT FROM '公司'
  AND length(trim(content)) > 0
ORDER BY news_time DESC, row_key_hash ASC
LIMIT :query_limit;
```

实现约束：

1. `query_limit` 不小于 `300`。
2. 首版固定 `query_limit = 300`，`visibleItemCount = 10` 只控制可见高度，不控制候选池长度。
3. 若启用 content 兜底标题，必须在后端 builder 中生成，并补测试。

### 5.2 个股新闻

```sql
SELECT
  row_key_hash AS news_id,
  news_time AS publish_time,
  title,
  src AS source_name,
  channels
FROM core_serving_light.news
WHERE news_time >= :window_start_at
  AND news_time <= :window_end_at
  AND channels = '公司'
  AND length(trim(content)) > 0
ORDER BY news_time DESC, row_key_hash ASC
LIMIT :query_limit;
```

实现约束：

1. M2 开工前必须确认 `core_serving_light.news.channels` 存在 `公司` 取值。
2. 本期 `stockNews.subject` 可为空，不从标题解析股票代码。
3. 不允许改为查 `anns_d`、`major_news` 或其它源冒充个股新闻。

### 5.3 索引与排序说明

1. `core_serving_light.news` 应命中 `news_time` 相关索引；若它是普通 view，需确认底层表的 `news_time` 索引可被利用。
2. 如 `channels` 过滤性能不足，编码前应评估是否需要新增 `(channels, news_time)` 索引；不得先写慢查询上线。
3. 同时间排序必须补 `row_key_hash ASC`，防止顺序漂移。

---

## 6. 状态归并样例

| 模块状态组合 | 页面状态 | 备注 |
|---|---|---|
| `marketNews>0 && stockNews>0` | `READY` | 两列都有数据 |
| `marketNews=0 && stockNews>0` | `PARTIAL` | 正式页展示个股新闻；debug 记录市场新闻为空 |
| `marketNews>0 && stockNews=0` | `PARTIAL` | 正式页展示新闻速览；debug 记录个股新闻为空 |
| `marketNews=0 && stockNews=0` | `EMPTY` | 模块空态 |
| `config invalid` | `ERROR` | 模块 error |
| `query failed` | `ERROR` | 模块 error |

---

## 7. 异常码覆盖矩阵

| code | 覆盖用例 | 触发条件 | 预期行为 |
|---|---|---|---|
| `NEWS_CONFIG_MISSING` | 配置缺失 | 找不到 `market_news.cn_a.v1.json` | 模块 error |
| `NEWS_CONFIG_INVALID` | 配置非法 | `visibleItemCount <= 0` 或源配置非法 | 模块 error |
| `NEWS_SOURCE_EMPTY` | 当前列表为空 | `core_serving_light.news` 按当前接口筛选规则无可展示项 | 当前板块 empty + debug |
| `NEWS_SOURCE_DELAYED` | 旧日源存在 | 目标日无数据但旧日有数据 | debug delayed，不自动展示旧日 |
| `NEWS_CHANNEL_RULE_INVALID` | 频道分类规则不可用 | `core_serving_light.news.channels` 无法支撑 `公司/非公司` 分类 | 停止编码/发布，先确认真实频道取值 |
| `NEWS_QUERY_FAILED` | SQL/服务异常 | 查询抛错 | 模块 error |

---

## 8. 性能门禁

1. P95 预算：`< 300ms`。
2. 返回体大小预算：`< 600KB`。
3. 最大并发预算：按市场总览首屏并发模块请求计算，不额外引入大查询。
4. 超预算降级策略：
   - 不做前端 mock 回退；
   - 后端不得把 `query_limit` 缩到 300 以下；如超预算，应先优化索引、字段裁剪或去重查询。

---

## 9. 测试门禁

1. 单元测试：
   - 配置解析；
   - 排序稳定；
   - 时间格式化；
   - item 不可点击。
2. 集成测试：
   - `pytest -q tests/web/test_wealth_market_news_api.py`
3. 冒烟测试：
   - `cd wealth`
   - `npm run test -- market-overview-news-real-api`
4. debug 模式验证：
   - `?debug=1` 显示 `newsBriefs` 与 `stockNews` 两个模块状态；
   - exceptions 只含注册表中的 `NEWS_*`。

### 9.1 核心测试 case 门禁（必填）

1. 核心字段清单：
   - `newsBriefs.visibleItemCount`
   - `newsBriefs.items[].displayTime`
   - `newsBriefs.items[].title`
   - `newsBriefs.items[].clickable`
   - `stockNews.items[].title`
   - `stockNews.items[].clickable`
   - `stockNews.items[]` 由 `channels='公司'` 产生，`subject` 本期可为空
2. 后端真实 API 集成测试用例：
   - 正常响应包含两类数组字段；
   - item `clickable=false`；
   - 排序为 `publishTime` 倒序；
   - 候选集过滤 `content` 为空的记录，并按最终展示标题去重；当两条新闻 `title` 相同但 `content` 不同时，只保留发布时间最新的一条；
   - config invalid 返回 error。
3. 前端真实 API 展示校验：
   - 两个新闻板块都在页面上；
   - 新闻 item 显示时间和标题；
   - item 无 pointer / 无链接行为；
   - API 请求 pending 时显示 loading；
   - 5 秒超时显示 error。
4. 执行命令：

```bash
pytest -q tests/web/test_wealth_market_news_api.py
cd wealth
npm run test -- market-overview-news-real-api
npm run typecheck
npm run build
```

5. 通过标准：
   - 后端字段满足页面消费；
   - 前端展示与后端字段一一对应；
   - 未引入旧顶部快讯条。

### 9.2 `v1.8` 视觉和交互门禁

1. 新闻模块必须位于 `summary-index-row` 内：
   - 左列：`新闻速览` 在 `今日市场客观总结` 上方；
   - 右列：`个股新闻` 在 `主要指数` 上方。
2. 不允许在 `PageHeader`、`TopMarketBar` 或顶部中间区域渲染新闻。
3. `visibleItemCount=10` 时必须实际可见 10 行，不允许因 CSS 高度不足遮挡。
4. 单条新闻必须是 `displayTime + title` 两列布局，标题单行省略。
5. item 不得有链接、pointer、路由跳转或 toast 详情提示。
6. hover `新闻速览` 只暂停新闻速览；hover `个股新闻` 只暂停个股新闻。
7. 鼠标离开后当前面板恢复自动向上滚动。
8. `queryLimit=300` 场景下滚动周期必须按条数放慢，不允许固定短周期导致扫屏；实现口径为 `max(40s, items.length * 2s)`。
9. 新闻模块必须每 10 分钟局部静默刷新一次；测试必须断言刷新时不清空旧列表、不展示 loading。
10. 刷新成功后必须展示新新闻，并让滚动轨道重新从最新新闻开始。
11. 刷新失败时必须保留旧新闻，不把当前面板切到 error。

---

## 10. 签字清单

### 10.1 后端负责人

1. [ ] 查询草案可实现。
2. [ ] `core_serving_light.news.channels` 线上取值已确认，且存在 `公司` 样本。
3. [ ] 异常覆盖完整。
4. [ ] 状态归并无歧义。

### 10.2 前端负责人

1. [ ] 响应结构可消费。
2. [ ] 新闻组能插入首屏上方且不改其它模块内部。
3. [ ] hover 暂停与不可点击可实现。
4. [ ] loading/empty/error 可落 UI。

### 10.3 架构/产品负责人

1. [ ] 范围未扩散。
2. [ ] 旧顶部快讯条已明确废弃。
3. [ ] 可进入编码阶段。

---

## 11. 跨模块抽象门禁原则映射（必填）

| 原则 | 是否适用 | 落地位置（字段/查询/配置/状态） | 测试落地 | 备注 |
|---|---|---|---|---|
| 事实源单一原则 | 是 | `/api/v1/wealth/market/news/briefs` 与 `/api/v1/wealth/market/news/stocks` | 后端字段 + 前端展示 | 前端不得拼新闻标题 |
| 契约先行与冻结原则 | 是 | `NewsListPanel/NewsPanelItem` + 页面侧 `MarketNewsPanelGroup` | 契约快照 | 禁止旧 `marketOverviewNewsBlocks` |
| 配置一致性原则 | 是 | `market_news.cn_a.v1.json` | 配置解析测试 | 用户不可配置 |
| 默认行为显式原则 | 是 | status resolver | empty/delayed 测试 | 不静默回退旧日 |
| 排序与筛选确定性原则 | 是 | SQL order by | 排序测试 | 时间相同需稳定排序 |
| 性能预算前置原则 | 是 | `queryLimit=300` + 索引查询 | API 耗时测试 | payload `<600KB` |
| 可观测与异常标准化原则 | 是 | `NEWS_*` | debug 测试 | 异常码必须注册 |
| 测试以用户可见结果为中心原则 | 是 | 时间/标题/不可点击 | 前端真实 API smoke | 不只测结构 |

### 11.1 模块门禁清单（复盘增强版）

1. [ ] 先证据后设计：已确认 `core_serving_light.news` 当前查询出口与 `news_time/title/channels/src/row_key_hash` 字段存在。
2. [ ] 先规则后实现：排序、空态、不可点击、配置生效已冻结。
3. [ ] 可判定性优先：标题字段存在性与兜底规则已确认。
4. [ ] 状态分层明确：页面状态与 debug 状态边界已写清。
5. [ ] 后端定义事实：前端不拼标题、不排序、不截断事实字段。
6. [ ] 三件套强一致：需求、实现、门禁无冲突项。
7. [ ] 反超前设计：新闻详情页、点击、个性化订阅已剔除。
8. [ ] 字段链路完整：UI -> API -> 数据源 -> 降级路径可追溯。

---

## 12. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-14 | 初版：冻结新闻模块编码前门禁 | Codex |
| v1.1 | 2026-05-14 | 补充 `market-overview-v1.8.html` 视觉/交互门禁 | Codex |
