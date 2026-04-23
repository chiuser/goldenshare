# AGENTS.md — frontend/src/features/trade-calendar 交易日历特性规则

## 适用范围

本文件适用于 `frontend/src/features/trade-calendar/` 目录及其所有子目录。

若未来更深层目录存在更具体的 `AGENTS.md`，应同时遵守；发生冲突时，以更靠近当前目录的规则为准。

---

## 当前目录职责

`trade-calendar/` 承接前端对真实交易日历的读取、缓存与只读判断能力。

当前应承接的内容包括：

- 交易日历接口读取
- 面向日期输入组件的交易日判断能力
- 面向周/月锚点“最后一个交易日”规则的只读判断能力
- 月度或区间级缓存
- 不同页面共用的只读 hook

---

## 当前硬约束

### 1. 这里只负责“读”，不负责页面流程

不要在这里放：

- 页面状态流转
- 表单提交逻辑
- 与单个页面强绑定的文案

### 2. 不要把 UI 绑进 feature

`trade-calendar/**` 不直接承接 `TradeDateField` 本身的展示实现。

共享组件仍留在 `shared/ui/**`，这里提供的是可注入的能力。

### 3. 不要在这里平台化多市场复杂规则

当前基线先服务 A 股交易日输入。

暂不承接：

- 多市场统一交易日平台
- 复杂交易所差异抽象
- 与页面无关的过度通用化配置中心

补充约束：

- 周/月锚点统一按“每周最后一个交易日 / 每月最后一个交易日”语义提供能力
- 不再新增或延续 `week_friday` 这类自然日命名来表达周锚点规则

---

## 推荐依赖

`trade-calendar/**` 可以依赖：

- `shared/api/client`
- `shared/api/calendar-types`
- React Query

不应依赖：

- `pages/**`
- `app/**`

---

## 验证要求

改动 `trade-calendar/**` 后，至少考虑：

- `npm run typecheck`
- `npm run test`
- `npm run build`

若影响的是试点页正在消费的交易日输入能力，还应评估：

- `npm run test:smoke`
