# 首页股票搜索技术实施方案 v1

> 状态：D1-D4 本地开发与验证已完成，无待拍板项；待用户部署与验收。
> 日期：2026-09-02
> 页面：财势乾坤 / 乾坤行情 / 市场总览
> 代码级设计：[首页股票搜索低层设计 v1](./homepage-stock-search-low-level-design-v1.md)

## 1. 文档目的

本方案把首页面包屑中部的股票搜索需求冻结成一条可实施、可测试、可追溯的 Wealth 自有链路。

用户已拍板的硬约束：

1. 交互和视觉必须遵循财势乾坤设计体系，并参考 Figma `Goldenshare Web`。
2. 搜索框只出现在首页，但必须做成标准组件。
3. 必须新增财势乾坤自己的搜索 API，禁止调用或包装其它子项目接口。
4. 候选池只包含当前上市 A 股，排除 B 股、退市股票和非股票证券。
5. 支持股票代码、完整 `tsCode` 或股票拼音首字母前缀搜索。
6. 停止输入 500ms 后出现联想菜单；Enter 或点击候选进入股票详情页，默认展示日 K。

本轮不做：

1. 不执行数据库迁移或服务发布；用户自行部署与验收。
2. 不扩展中文名称、模糊包含、板块、指数、ETF、港股或美股搜索。
3. 不在详情页、财势探查或顶部全局导航中展示搜索框。
4. 不增加热门搜索、历史搜索、自选联动、键盘快捷键或搜索结果行情字段。
5. 不改变股票详情页既有日线、前复权和图表合同。

## 2. 依据与当前事实

### 2.1 文档与设计依据

1. `wealth/AGENTS.md`
2. `wealth/docs/system/wealth-system-baseline.md`
3. `wealth/docs/system/engineering-architecture.md`
4. `wealth/docs/system/design-system-baseline.md`
5. `wealth/docs/system/component-guidelines-baseline.md`
6. `wealth/docs/pages/market-overview/market-overview-baseline.md`
7. `wealth/docs/pages/market-overview/api-contract-baseline.md`
8. 当前 Wealth 页面、共享组件、路由、API 和 `security_serving` 模型。

### 2.2 当前代码审计结论

| 事实 | 当前落点 | 对本方案的影响 |
|---|---|---|
| 首页 | `wealth/src/pages/market-overview/MarketOverviewPage.tsx` | 搜索组件唯一生产挂载点 |
| 面包屑 | `wealth/src/shared/ui/page-breadcrumb/PageBreadcrumb.tsx` | 左路径、右时间之间可增加可选中间槽 |
| 面包屑消费者 | 市场总览、`WealthExplorationShell` | 中间槽必须可选，非首页默认不渲染 |
| 股票详情路由 | `buildStockDetailPath(tsCode)` | 复用 `/wealth/market/stock/{tsCode}`，不自行拼路由 |
| 股票详情默认周期 | `StockDetailPage.tsx` | 当前初始化已固定 `period="day"`、`adjustment="forward"` |
| Wealth API 命名空间 | `/api/v1/wealth/market/{module}` | 新接口必须进入 Wealth 模块命名空间 |
| 证券事实源 | `core_serving.security_serving` | 具有 `ts_code/symbol/name/cnspell/exchange/curr_type/list_status/security_type` |
| 现有 Ops 联想接口 | `/api/v1/ops/review/board/equity-suggest` | 只能作为重复能力审计证据，禁止复用或导入 |

CodeGraph 已覆盖 `PageBreadcrumb` 的两个消费者、`buildStockDetailPath` 的调用方、既有 Ops suggestion 的入口与查询实现；当前索引为最新。新链路保持 `biz -> foundation`，不产生 `biz -> ops` 依赖。

## 3. Figma 视觉与交互基线

文件：[Goldenshare Web](https://www.figma.com/design/RADlZzREU4lPVviYfkLy6x/Goldenshare-Web)

| 设计产物 | 页面 / 节点 | 用途 |
|---|---|---|
| 结果行标准组件 | `03 Components - Market Overview` / `1261:90` | `Default/Hover/Selected` 三态 |
| 搜索标准组件 | `03 Components - Market Overview` / `1262:155` | `Default/Hover/Focused/Loading/Results/Empty/Error` 七态 |
| M8 首页稿 | `04 Market Overview - Desktop Loaded` / `1264:471` | 在面包屑中部放置默认实例，仅首页出现 |
| 交互交付板 | `05 Market Overview - States and Interaction Notes` / `1267:81` | 500ms、状态、键盘、候选池和 API 边界 |
| 原型终点 | 同页 / `1267:223` | 表达选择后进入股票详情日 K；Results 状态可点击到达 |

设计规则：

1. 复用 `CSQ / Market Overview / M0` 的 Color、Layout、Typography 变量和 Panel 阴影。
2. 不新增第二套颜色、间距、圆角、字体或阴影 token。
3. 搜索控件宽 `360px`、高 `36px`，适配当前 1600px 首页面包屑中部空区。
4. 中文和普通标签使用 Noto Sans SC；股票代码、状态计时和键盘提示使用 Roboto Mono。
5. 聚焦态使用品牌金边；错误态使用系统错误色；不使用 A 股上涨/下跌色表达控件状态。
6. M7 首页稿保留，M8 作为独立完整首页稿，避免覆盖历史验收事实。

## 4. 用户流程与状态机

### 4.1 主流程

```text
聚焦输入框
  -> 输入代码或拼音首字母
  -> 0–499ms：保持菜单关闭
  -> 第 500ms：发起 Wealth 搜索请求，菜单以 Loading 打开
  -> 最新请求返回
       -> 有结果：显示 Results，第一项默认选中
       -> 无结果：显示 Empty
       -> 请求失败：显示 Error
  -> ArrowUp / ArrowDown 移动选中项
  -> Enter 或点击候选
  -> buildStockDetailPath(tsCode)
  -> 股票详情页默认日 K
```

### 4.2 状态定义

| 控制器状态 | 可见表现 | 菜单 | 请求行为 |
|---|---|---|---|
| `idle` | 默认或 hover | 关闭 | 无请求 |
| `debouncing` | 聚焦且显示当前输入 | 关闭 | 500ms 计时；继续输入重置 |
| `loading` | 金色聚焦边框、搜索中 | 打开 | 当前请求进行中 |
| `ready` | 候选列表、第一项默认选中 | 打开 | 只接受最新请求结果 |
| `empty` | “未找到匹配的当前上市 A 股” | 打开 | HTTP 200，`items=[]` |
| `error` | “搜索暂不可用，请稍后重试” | 打开 | 不回退 mock 或其它接口 |

### 4.3 交互规则

1. 空输入不发请求并关闭菜单。
2. 输入前后空白被移除，英文字母统一转大写；其它字符不得扩大到中文名称或任意子串搜索，未命中时按正常空结果处理。
3. 每次输入变化立即取消旧 `AbortController`，并使旧响应失效；即使旧请求未及时取消，也不得覆盖新输入。
4. 输入停止 500ms 后，先打开 Loading 菜单，再等待响应，不把网络耗时混入“500ms”定义。
5. Enter：
   - 已有候选时打开当前选中项；
   - 仍在 500ms 等待期时取消计时并立即查询，按服务端排序打开第一项；
   - 无候选或请求失败时不跳转。
6. `ArrowDown/ArrowUp` 在候选内循环移动；`Escape` 关闭菜单并保留输入；清空输入回到 `idle`。
7. 鼠标按下候选时先完成选择再处理失焦，避免 blur 吞掉 click。
8. 页面跳转由 `MarketOverviewPage` 统一处理，标准组件只上报 `tsCode`。

## 5. Wealth 自有搜索 API

### 5.1 接口合同

```http
GET /api/v1/wealth/market/stock-search?keyword=600&limit=8
Authorization: Bearer <token>
```

请求参数：

| 参数 | 类型 | 默认 | 约束 |
|---|---|---:|---|
| `keyword` | string | 无 | 必填；trim 后 1–32 位 |
| `limit` | integer | 8 | `1..20` |

响应：

```json
{
  "keyword": "600",
  "items": [
    {
      "tsCode": "600000.SH",
      "name": "浦发银行"
    }
  ]
}
```

合同约束：

1. 字段统一 lowerCamelCase，`extra="forbid"`。
2. 不返回 `symbol`、`cnspell`、币种、上市状态或内部排序分数；候选行代码固定展示 `tsCode`。
3. `items=[]` 是正常空结果，不是异常。
4. 无分页；前缀联想只返回有界 Top N。
5. 使用 `require_quote_access`，认证与续签继续走 Wealth 既有链路。

### 5.2 候选池合同

候选池来自 `core_serving.security_serving`，必须同时满足：

```sql
security_type = 'EQUITY'
AND list_status = 'L'
AND curr_type = 'CNY'
AND exchange IN ('SSE', 'SZSE', 'BSE')
```

这一合同复用仓库现行 A 股识别口径，不按 `900xxx`、`200xxx` 等代码前缀猜测 A/B 股：

1. `security_type='EQUITY'` 排除指数、ETF、基金和其它证券。
2. `list_status='L'` 只保留当前上市，排除退市和暂停上市状态。
3. `curr_type='CNY'` 排除以外币计价的 B 股。
4. `exchange` 限定沪、深、北三个 A 股交易所。

### 5.3 匹配与排序

只做前缀匹配：

```text
upper(symbol) LIKE :keywordPrefix
OR upper(ts_code) LIKE :keywordPrefix
OR upper(cnspell) LIKE :keywordPrefix
```

固定排序：

1. `symbol` 或 `tsCode` 完全匹配。
2. `symbol` 前缀匹配。
3. `tsCode` 前缀匹配。
4. `cnspell` 前缀匹配。
5. 同分按 `tsCode ASC`，保证结果稳定。

禁止中文名称包含搜索、任意子串匹配和数据库隐式顺序。

`keyword` 进入 `LIKE` 前必须把 `%`、`_` 与转义符本身按普通字符转义，并显式声明 `ESCAPE`；用户输入不得获得 SQL 通配符语义。中文或其它未支持字符不触发字段扩张，正常返回空列表。

### 5.4 异常合同

异常码统一登记在 `wealth/docs/system/exception-code-registry.md`：

| code | HTTP | 触发 | 前端行为 |
|---|---:|---|---|
| `SS_REQUEST_INVALID` | 400 | keyword 为空或超长、limit 越界 | 保留输入，显示不可重试的输入错误；不发模糊回退查询 |
| `SS_QUERY_FAILED` | 500 | DB 或 DTO 组合失败 | 菜单显示统一 Error，可在继续输入后重试 |

标准认证失败继续使用应用统一 401/403，不重复发明模块异常码。

## 6. 后端分层与目录落点

```text
src/biz/
  api/wealth/market/stock_search.py
  queries/wealth/market/stock_search/
    __init__.py
    stock_search_query.py
    stock_search_query_service.py
  schemas/wealth/market/stock_search.py
  services/wealth/market/stock_search/
    __init__.py
    stock_search_policy.py

src/app/api/v1/router.py
tests/web/test_wealth_market_stock_search_api.py
```

职责：

1. API：参数、鉴权、异常映射和 DTO 输出。
2. Policy：唯一保存候选池、默认 limit、最大 limit 和排序等级；它们是产品合同常量，不是运营配置。
3. Query：只写 SQLAlchemy 查询表达式，不返回 Ops schema。
4. Query service：执行查询并映射 Wealth DTO。
5. App router：只挂载新的 Biz router，不承载业务逻辑。

明确禁止：

1. 不导入 `src.ops.*`。
2. 不调用 `/api/v1/ops/review/board/equity-suggest`。
3. 不把 Ops schema、admin 权限或 Review Center 语义带入 Wealth。
4. 不新增 legacy `platform/operations` 实现或依赖。

## 7. 前端标准组件与唯一挂载点

```text
wealth/src/features/stock-search/
  api/stockSearchApi.ts
  model/stockSearchTypes.ts
  model/useStockSearchController.ts
  ui/StockSearch.tsx
  ui/stock-search.css

wealth/src/shared/ui/page-breadcrumb/
  PageBreadcrumb.tsx
  PageBreadcrumb.test.tsx
  page-breadcrumb.css

wealth/src/pages/market-overview/
  MarketOverviewPage.tsx

wealth/src/features/stock-search/
  api/stockSearchApi.test.ts
  model/useStockSearchController.test.tsx
  ui/StockSearch.test.tsx
```

组件边界：

1. `StockSearch` 是 feature 级标准组件，具有稳定 props、状态、键盘和无障碍合同。
2. 当前只有一个真实生产消费者，因此不提前提升到 `shared/ui`；这符合“先 feature、两个真实消费者后再共享”的组件规范。
3. `PageBreadcrumb` 只增加可选 `centerSlot?: ReactNode`，默认行为不变。
4. `MarketOverviewPage` 是唯一传入 `centerSlot` 的页面；其它消费者零变化。
5. `StockSearch` 暴露 `onSelect(tsCode)`，不感知 Wealth router。
6. 页面收到 `tsCode` 后复用 `navigateWealth(buildStockDetailPath(tsCode))`。

固定 props：

```ts
interface StockSearchProps {
  onSelect: (tsCode: string) => void;
}
```

组件不暴露 `debounceMs`。500ms 是本次产品合同，禁止变成页面常量、环境变量或可随意覆盖的 props。

## 8. 可访问性

1. 输入使用 `role="combobox"`、`aria-autocomplete="list"`、`aria-expanded` 和 `aria-controls`。
2. 菜单使用 `role="listbox"`，候选使用 `role="option"` 与 `aria-selected`。
3. 当前选中项通过 `aria-activedescendant` 关联，不把 DOM 焦点移出输入框。
4. Loading/Empty/Error 文案通过有界 live region 通知，不重复朗读每个按键。
5. 颜色不是唯一状态信号；聚焦、选中和错误均同时有边框或文字。

## 9. 性能、并发与配置审计

### 9.1 性能预算

1. 默认 8 条，最大 20 条，响应体目标不超过 8KiB。
2. 在正式数据库代表性并发下，API P95 目标 `<= 200ms`，P99 目标 `<= 350ms`。
3. 前端 500ms 时只承诺菜单进入 Loading；网络耗时不伪装为 debounce。
4. 前端单次请求 2s 后进入 Error；输入变化和卸载立即取消请求。

### 9.2 首版策略

1. 首版直接查询约五千量级的当前上市 A 股事实表，不引入 Redis、预聚合表或搜索引擎。
2. 实施前必须对冻结 SQL 做 `EXPLAIN` 和真实耗时验证。
3. 若 P95 不达标，先检查大小写前缀表达式与索引命中，再按真实 Alembic head 设计功能索引；不得先凭经验新增索引。
4. API 不静默回退旧接口或本地全量数组。
5. Results 菜单最多显示 5 行候选，默认 8 条结果超出部分在菜单内部滚动，不改变首页布局。

正式数据库只读实测结果（2026-09-02）：

1. 候选池 5,553 只，`cnspell` 非空 5,553 只；查询表总计约 5,894 行、约 5.9MiB。
2. `600`、`600000.SH`、`PAYH`、`ZZZZ` 四类样本各执行 30 次，P95 分别为 27.423ms、157.893ms、98.940ms、26.203ms，均低于 200ms。
3. 四类样本 P99 分别为 103.050ms、217.454ms、175.092ms、102.650ms，均低于 350ms。
4. 默认 8 条结果的代表性响应体为 439B，低于 8KiB。
5. `EXPLAIN (ANALYZE, BUFFERS)` 显示单次执行约 6.3-7.5ms。表规模很小，顺序扫描已满足预算，因此本轮不新增索引或迁移。

### 9.3 配置项审计

本方案不新增配置项：

| 口径 | 性质 | 来源 | 可否对外配置 |
|---|---|---|---|
| 500ms | 产品交互合同 | 本文 + Figma | 否 |
| 默认 8 / 最大 20 | API 合同 | `stock_search_policy.py` | 否 |
| A 股四项过滤 | 产品事实合同 | `stock_search_policy.py` | 否 |
| 搜索字段与排序 | API 合同 | Query + 测试 | 否 |

因此不修改 env、Settings、数据库配置表或策略配置中心。

## 10. 测试与验收计划

### 10.1 后端真实 API 测试

测试必须走真实 FastAPI 路由和测试数据库 session，禁止 mock query/service。

| Case | 数据 | 断言 |
|---|---|---|
| 数字代码 | `600` | 只返回 symbol/tsCode 前缀 |
| 完整 tsCode | `600000.sh` | 归一化并把完全匹配放第一 |
| 拼音首字母 | `payh` | 返回 `000001.SZ / 平安银行` |
| 稳定排序 | 多个同级匹配 | 每次按固定 score + tsCode 输出 |
| B 股排除 | `curr_type=USD/HKD` | 不返回 |
| 退市排除 | `list_status=D` | 不返回 |
| 非股票排除 | `security_type!=EQUITY` | 不返回 |
| 交易所排除 | 非 SSE/SZSE/BSE | 不返回 |
| 中文名称 | 仅 name 匹配 | 不返回，防止需求扩散 |
| limit | 1、8、20、21 | 边界正确，21 拒绝 |
| 非法参数 | 空、空格、超长 keyword；limit 越界 | `SS_REQUEST_INVALID` 或框架参数错误映射 |
| 通配符隔离 | `%`、`_`、转义符 | 只按普通字符匹配，不扩大结果集；未命中返回空列表 |
| 权限 | 无 quote access | 统一 401/403 |
| 查询失败 | DB 抛错 | `SS_QUERY_FAILED`，不泄露 SQL |

### 10.2 前端组件测试

1. 499ms 不发请求；500ms 只发一次并显示 Loading 菜单。
2. 继续输入重置计时，取消旧请求；乱序返回时只展示最新 keyword。
3. 成功、空、失败三种响应分别进入 Results/Empty/Error。
4. 第一项默认选中；上下键、Esc、点击和 Enter 行为正确。
5. 等待期按 Enter 会立即查询，并只在得到候选后导航。
6. blur 不吞掉鼠标选择。
7. combobox/listbox/option ARIA 关系正确。

### 10.3 页面与路由回归

1. 搜索框只在 `/wealth/market/overview` 出现。
2. `WealthExplorationShell` 等 `PageBreadcrumb` 消费者渲染与布局不变。
3. 跳转路径只由 `buildStockDetailPath` 生成。
4. 股票详情首个 K 线请求仍是 `period=day`、`adjustment=forward`。
5. 1600px Loaded 视觉与 Figma M8 对齐；低于 1460px 保持现有宽桌面横向查看策略。

### 10.4 计划验证命令

```bash
pytest -q tests/web/test_wealth_market_stock_search_api.py
pytest -q tests/architecture/test_subsystem_dependency_matrix.py
cd wealth && npm run typecheck
cd wealth && npm run test
cd wealth && npm run build
```

页面可视行为还必须执行真实 API smoke，不得用 mock adapter 代替。

## 11. 编码门禁矩阵

本表与[首页股票搜索低层设计 v1](./homepage-stock-search-low-level-design-v1.md)共同约束后续实现；LLD 已补齐代码符号、SQL、通用清单映射和测试门禁。

| 门禁 | 代码落点 | 必须测试 | 当前状态 |
|---|---|---|---|
| Wealth 自有 API | `src/biz/**/stock_search*` | 路由测试 + 无 Ops import | 已完成 |
| 当前上市 A 股 | Policy + Query | B 股/退市/非股票/其它交易所负例 | 已完成 |
| 只搜代码/拼音首字母 | Query | 中文名称和子串负例 | 已完成 |
| 500ms | Controller | 499/500ms fake timer | 已完成 |
| 旧请求不得覆盖 | Controller | abort + 乱序响应 | 已完成 |
| Enter/click 跳转 | Component + Page | 路由与选中测试 | 已完成 |
| 详情默认日 K | 既有 StockDetailPage | 首请求参数回归 | 已回归通过 |
| 只在首页出现 | MarketOverviewPage | 其它页面无实例 | 已完成 |
| 标准组件 | `features/stock-search/ui` | 组件状态与 ARIA | 已完成 |
| 设计系统一致 | CSS + Figma M8 | token 静态检查 + 1600px smoke | 已完成 |
| 性能预算 | Query/API | EXPLAIN + P95/P99 | 已达标，无需迁移 |
| 异常标准化 | API + registry | 400/500 case | 已完成 |

跨模块八原则映射：

| 原则 | 本模块落点 | 验证 |
|---|---|---|
| 事实源单一 | `security_serving` | 真实路由 fixture |
| 契约先行 | 本文 API/DTO | schema + 前端类型对账 |
| 配置一致 | 本模块无配置项 | 静态审计 |
| 默认行为显式 | 500ms、limit=8、首项选中 | fake timer + API 边界 |
| 排序筛选确定 | 四项池过滤 + score + tsCode | 正负样本与重放 |
| 性能预算前置 | P95/P99/payload | 实库 EXPLAIN 与压测 |
| 异常标准化 | `SS_*` | 400/500 测试 |
| 用户可见结果 | 搜索状态、候选、路由、日 K | 真实 API smoke |

## 12. 实施顺序与回滚边界

1. D0：技术方案、Figma M8、LLD 与异常码登记已完成。
2. D1：后端 Wealth API 与真实路由测试已完成。
3. D2：前端 API、控制器和标准组件已完成。
4. D3：PageBreadcrumb 可选槽和首页唯一挂载已完成。
5. D4：真实 API smoke、性能门禁、Figma 对照与详情日 K 回归已完成。

回滚粒度是整个 `stock-search` 模块和首页 `centerSlot` 实例。回滚不修改其它市场总览模块、股票详情路由或日 K 合同。

## 13. 风险与缓解

| 风险 | 触发 | 缓解 |
|---|---|---|
| `ILIKE/upper` 未命中索引 | 实库 P95 超预算 | 先 EXPLAIN，再按真实 Alembic head 设计功能索引 |
| 拼音字段为空或质量不一 | 合法股票搜不到 | D1 前做字段覆盖率只读审计；不前端猜拼音 |
| B 股混入 | 只按 exchange 或代码前缀 | 固定 `EQUITY + L + CNY + exchanges` 四项并加负例 |
| 旧响应覆盖新输入 | 快速连续输入 | abort + request sequence 双门禁 |
| 面包屑共享消费者回归 | 直接全局渲染搜索 | 可选 `centerSlot`，只由首页传入 |
| Enter 在防抖期无响应 | 只依赖 500ms timer | Enter 立即发起有界查询 |
| Figma 和实现漂移 | 编码临场改尺寸/状态 | LLD 逐项引用本文和节点 ID，视觉 smoke 对账 |

## 14. 完成结论

产品范围没有新增待拍板项。D1-D4 已完成本地开发与验证：Wealth 自有 API、当前上市 A 股候选池、500ms 联想、标准组件、首页唯一挂载和详情默认日 K 均已落地。生产数据库只读性能门禁和本地真实页面 smoke 已通过；本轮未执行部署，后续由用户完成部署与验收。

## 15. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-09-02 | 冻结首页唯一挂载、Wealth 自有 API、当前上市 A 股池、500ms 联想、详情日 K 与 Figma M8 | Codex |
| v1.1 | 2026-09-02 | 补齐代码级 LLD、清零待拍板项，并收口为可执行的完整技术方案 | Codex |
| v1.2 | 2026-09-02 | 完成 D1-D4 开发、测试、正式数据库只读性能门禁与本地真实页面验收；待用户部署验收 | Codex |
