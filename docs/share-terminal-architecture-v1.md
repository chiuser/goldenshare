# 财势乾坤行情终端架构设计（V1）

## 1. 文档目标与范围

本文档定义 `Share Terminal`（路由建议：`/app/share/*`）的一期架构与技术选型。  
该系统与运维管理台（`/app/ops/*`）是**同仓库、不同产品线**，在视觉、交互、模块边界上完全独立。

一期功能范围：

1. K 线主图（日/周/月）+ 十字线定位。
2. MA 均线（5/10/15/20/30/60/120/250）可选显示。
3. MACD 指标面板。
4. KDJ 指标面板。
5. 成交量面板（含量均线）。
6. 右侧股票指标信息面板。
7. 底部新闻资讯面板。

---

## 2. 架构原则

1. **独立性**：行情终端不复用运维台 UI 风格与页面结构，仅复用基础工程能力（登录、路由、请求层、构建链路）。
2. **可扩展性**：指标能力采用插件式抽象，支持后续新增 RSI/BOLL/CCI 等而不重构主流程。
3. **口径一致性**：复权、周期聚合、指标计算口径可配置但统一，避免多端不一致。
4. **高性能体验**：优先保障图表交互（拖拽、缩放、十字线）流畅，数据与渲染分层。
5. **可维护性**：模块边界清晰，前后端接口稳定、可测试、可演进。

---

## 3. 系统边界与总体结构

### 3.1 前端边界

- 入口：`/app/share/`（独立壳子 `ShareShell`）。
- 与 `/app/ops` 共享认证态，但主题、布局、导航独立。
- 前端只承担：
  - 交互控制（周期切换、指标开关、选股）。
  - 图表渲染与联动。
  - 状态展示与错误降级。

### 3.2 后端边界

- 后端提供 `share` 域 API（`/api/v1/share/*`）。
- 后端负责：
  - K 线原始数据与复权口径输出。
  - 周期聚合（日/周/月）规则统一。
  - 可选指标计算（推荐由后端统一产出）。
  - 资讯汇聚与标准化输出。

### 3.3 数据层边界

- `raw/core`：基础行情与业务数据事实层。
- `dm`：面向查询的汇总层（如 `dm.equity_daily_snapshot`）。
- 一期不要求预存全部技术指标；先按查询实时计算，后续再按场景物化。

---

## 4. 技术选型

## 4.1 前端

首选技术栈（已确认）：

- React + TypeScript + Vite
- Mantine（控件层）
- TanStack Router（路由）
- TanStack Query（服务端状态管理）
- Lightweight Charts（K 线/量/技术指标核心图表）
- ECharts（后续复杂可视化补充）

选择理由：

1. 对行情终端核心交互（高频缩放/十字线/蜡烛图）支持成熟。
2. 与现有工程一致，迁移成本低。
3. 可通过模块化演进到更复杂指标与多图联动。

## 4.2 后端

- FastAPI + SQLAlchemy（沿用现有平台能力）。
- 新增 `share` 领域 query/service 层，不与 `ops` 逻辑耦合。

---

## 5. UI 与主题系统设计

## 5.1 设计目标

- 面向消费者的软件体验，强调“信息密度高但不压迫”。
- 默认深色终端主题，同时支持换色与浅色方案。

## 5.2 主题模型

建立独立 `share-theme` 变量层（示意）：

- 语义色：`--share-bg`, `--share-panel`, `--share-border`, `--share-text`, `--share-text-muted`
- 行情色：`--share-up`, `--share-down`, `--share-flat`
- 图表色：`--share-grid`, `--share-crosshair`, `--share-ma-5` ... `--share-ma-250`
- 强调色：`--share-accent-primary`, `--share-accent-secondary`

主题切换机制：

1. `data-theme` + CSS Variables 驱动主视觉。
2. Mantine Theme 作为组件级 token 覆盖。
3. 用户主题偏好持久化（localStorage + 账户偏好预留字段）。

---

## 6. 指标计算策略

## 6.1 计算复杂度评估

- MA：`O(n)`（滚动窗口可优化常数项）。
- MACD：`O(n)`（EMA 链式递推）。
- KDJ：`O(n)`（滑动窗口极值 + 平滑递推）。

对于单标的 2k~5k 根数据，计算开销可控（毫秒级至几十毫秒）。

## 6.2 一期是否入库

结论：一期**不做指标预计算入库**，采用实时计算。

理由：

1. 指标参数可调，预存会引入组合爆炸。
2. 周期（日/周/月）与复权模式组合多，预存维护成本高。
3. 一期规模下实时计算性能足够。

## 6.3 复权口径

前复权公式（已验证）：

`price_qfq = price_raw * adj_factor(trade_date) / adj_factor(end_date)`

其中 `price_raw` 可取 `open/close/high/low`。  
后端统一复权口径，前端只消费结果。

---

## 7. API 契约（V1）

建议一期最小接口集合：

1. `GET /api/v1/share/kline`
   - 参数：`ts_code`, `period(d|w|m)`, `start_date`, `end_date`, `adj(qfq|none)`
   - 返回：OHLCV + 可选基础指标字段 + 时间序列

2. `GET /api/v1/share/quote`
   - 参数：`ts_code`
   - 返回：右侧面板所需实时/准实时指标

3. `GET /api/v1/share/news`
   - 参数：`ts_code`, `page`, `page_size`
   - 返回：资讯列表（时间、来源、标题、标签、链接）

4. `GET /api/v1/share/market-overview`（已存在）
   - 用于 `dm` 层可视化与快速健康检查

接口设计要求：

1. 时间字段统一为 ISO 格式。
2. 数值字段精度明确，避免前端二次猜测。
3. 空值与不可用状态有显式标志，不返回“半结构化字符串”。

---

## 8. 前端模块设计

建议目录（示意）：

1. `frontend/src/features/share-terminal/chart/*`
2. `frontend/src/features/share-terminal/indicators/*`
3. `frontend/src/features/share-terminal/quote-panel/*`
4. `frontend/src/features/share-terminal/news-panel/*`
5. `frontend/src/features/share-terminal/theme/*`
6. `frontend/src/pages/share-terminal-page.tsx`

## 8.1 指标插件接口（建议）

统一指标定义：

- `id`
- `displayName`
- `inputs`（参数定义）
- `compute(candles, options) => series`
- `panelType`（overlay/subpanel）
- `renderConfig(theme)`

首批插件：`MA`, `MACD`, `KDJ`。

---

## 9. 性能与稳定性

1. 默认加载最近 N 根（如 1500），历史按需扩展。
2. 图表数据更新走增量 patch，避免全量重绘。
3. 指标计算使用纯函数，必要时迁移 Web Worker。
4. 资讯列表使用分页或虚拟列表，控制首屏体积。
5. 异常降级：
   - 图表接口失败：显示重试 + 最近成功快照。
   - 资讯接口失败：保留图表功能，不阻塞主交易视图。

---

## 10. 可维护性与演进计划

## 10.1 维护策略

1. 领域隔离：`share` 与 `ops` 在 API、页面、样式层分离。
2. 版本控制：`/api/v1/share/*` 以向后兼容为原则演进。
3. 可观测性：关键接口记录请求耗时、返回条数、错误码。

## 10.2 测试策略

1. 单元测试：MA/MACD/KDJ 计算结果与基准样本一致。
2. 集成测试：周期切换、十字线联动、指标开关。
3. UI 回归：深色/浅色主题截图对比。
4. API 合同测试：字段完整性、类型与精度断言。

## 10.3 后续扩展路径

1. 指标扩展：RSI/BOLL/DMI/CCI。
2. 交易视图扩展：分时、分钟 K、多周期同屏。
3. 智能能力：事件标注、信号提示、策略回测入口。
4. 数据扩展：板块/题材热度联动、资金面联动、公告语义摘要。

---

## 11. 里程碑建议（一期）

1. M1：终端页面骨架 + 日/周/月 K 线 + 十字线 + 成交量。
2. M2：MA 可选 + MACD + KDJ + 四面板联动。
3. M3：右侧指标面板 + 底部新闻面板。
4. M4：主题切换 + 性能优化 + 回归测试 + 发布。

---

## 12. 决策结论（本次）

1. `Share Terminal` 作为独立系统设计与实现，不沿用运维台风格。
2. 一期指标采用实时计算，不做指标预计算入库。
3. 前端采用 React + TS + Vite + Mantine + TanStack + Lightweight Charts（ECharts 作为补充）。
4. 通过指标插件化与主题变量化保证后续可维护与可扩展。

