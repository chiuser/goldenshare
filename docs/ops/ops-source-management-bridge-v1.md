# Ops 源管理桥接契约（v1）

更新时间：2026-04-14  
状态：`Draft`（可用于开发联调）

---

## 1. 目标与边界

本桥接契约用于 **过渡期** 支撑现有 Ops 页面读取多源新模型能力，目标是：

1. 旧页面先可用：不做大规模 UI 重构，先让页面可读新对象。
2. 后端先收敛：把多源对象先落到稳定查询契约，减少前端多点直连。
3. 明确可删除：桥接层不是长期兼容方案，待新版页面稳定后删除。
4. 支持双菜单过渡：允许短暂不可用，不要求旧页面长期稳定兜底。

**非目标：**

1. 不在桥接期提供完整策略编辑器。
2. 不在桥接期完成全部交互体验升级。
3. 不在桥接期沉淀长期“双轨并行”逻辑。

---

## 2. 设计原则

1. 只加薄层，不加厚兼容逻辑。
2. 只读优先：桥接期以查询可视化为主，复杂写操作保守推进。
3. 一处聚合：页面尽量读取一个桥接接口，而不是多个新接口并发拼装。
4. 生命周期明确：每个桥接接口都应标记去留策略。
5. 冻结旧版：旧页面进入“冻结维护”状态，不承接新需求。

---

## 3. 已落地桥接接口

## 3.1 聚合桥接接口（主入口）

`GET /api/v1/ops/source-management/bridge`

用途：为“数据源管理（新版）”页面提供单次请求聚合视图，避免页面并发请求多个子接口。

返回结构（概念）：

1. `summary`
   - `probe_total/probe_active`
   - `release_total/release_running`
   - `std_mapping_total/std_mapping_active`
   - `std_cleansing_total/std_cleansing_active`
   - `layer_latest_total/layer_latest_failed`
2. `probe_rules`
3. `releases`
4. `std_mapping_rules`
5. `std_cleansing_rules`
6. `layer_latest`

---

## 3.2 子能力接口（桥接依赖）

以下接口为聚合桥接接口的上游数据来源，也可单独用于联调：

1. Probe
   - `GET /api/v1/ops/probes`
   - `GET /api/v1/ops/probes/runs`
2. Release
   - `GET /api/v1/ops/releases`
   - `GET /api/v1/ops/releases/{release_id}/stages`
3. Std Rules
   - `GET /api/v1/ops/std-rules/mapping`
   - `GET /api/v1/ops/std-rules/cleansing`
4. Layer Snapshot
   - `GET /api/v1/ops/layer-snapshots/latest`
   - `GET /api/v1/ops/layer-snapshots/history`

---

## 4. 页面侧桥接策略

当前 `ops-source-management-page` 使用策略：

1. 首选读取 `GET /ops/source-management/bridge`。
2. 页面仅做展示，不在该页承载重写流程编辑。
3. 作为迁移看板，体现“新能力可观察”，而非“旧页完整替代”。

---

## 5. 生命周期与删除条件

桥接层删除条件（满足即删）：

1. 新版 Ops 信息架构页面（总览/源管理/策略中心/运维发布）上线稳定。
2. 新页面可直接消费基础对象接口（Probe/Release/StdRule/LayerSnapshot）。
3. 旧页面不再依赖 `source-management/bridge` 聚合结构。

删除范围：

1. 删除 `GET /ops/source-management/bridge`。
2. 删除仅服务桥接页的前端拼装逻辑与类型定义。
3. 文档状态改为 `Archived`。

---

## 5.1 迁移策略（已确认）

采用“**双菜单并行短过渡**”：

1. 菜单层同时展示：
   - `V2.1`（新页面）
   - `旧版（过渡）`（冻结页面）
2. 新能力只在 `V2.1` 页面开发，旧版页面不再接新需求。
3. 当 `V2.1` 核心页可用后，默认入口切换到 `V2.1`。
4. 切换后尽快删除旧版页面与桥接接口，不做长期双轨运行。

---

## 6. 风险与控制

1. 风险：桥接结构扩张为“隐式长期接口”。
   - 控制：仅允许聚合只读字段，禁止在桥接接口添加写操作语义。

2. 风险：前端绕过桥接重新多点依赖，形成新耦合。
   - 控制：桥接页统一走单入口；新增字段先在聚合服务补齐。

3. 风险：桥接字段与底层对象口径漂移。
   - 控制：桥接层只做结构聚合，不做业务计算，不引入二次规则。

---

## 7. 测试与验收

后端验收：

1. `test_ops_source_management_bridge_api.py` 覆盖聚合响应结构与权限。
2. 子能力接口测试覆盖（probe/release/std/layer）保持通过。

前端验收：

1. `ops-source-management-page.test.tsx` 覆盖桥接数据渲染。
2. `npm run typecheck` 通过。
3. `npm run test` 通过。

---

## 8. 下一步讨论点（待评审）

1. 聚合接口是否需要版本前缀（例如 `/bridge/v1`）。
2. 是否增加 `ctx` 导航字段，直接支持“去处理/去发布/去规则”深链跳转。
3. 桥接页是否保留只读，还是开放少量低风险操作（如启停 probe）。
