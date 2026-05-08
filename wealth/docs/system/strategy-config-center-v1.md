# wealth 策略配置中心 v1（简单/有效/可靠）

> 目标：把“模块策略配置”收敛到单一位置，用统一读取能力提供给各模块。  
> 原则：简单、有效、可靠；不做复杂化设计。

---

## 1. 已拍板决策（冻结）

1. 配置源：`仓库 JSON`（不接数据库，不接远程配置中心）。
2. 配置失效策略：`严格失败`（校验失败直接报错，不回退旧版本）。
3. 热更新策略：`重启生效`（不做运行时热加载）。
4. 版本管理：每个配置文件必须包含：
   - `version`
   - `updatedAt`
   - `updatedBy`

---

## 2. 适用范围

本规范只约束 `wealth` 业务模块的“策略配置”：

1. 榜单模块策略（池、排序、阈值、回退开关等）。
2. 市场客观总结模块策略（卡片开关、模板版本等）。
3. 主要指数模块策略（固定 10 个 code 的可配置名单）。

不在范围内：

1. 页面样式配置（CSS/Design Token）。
2. 用户级个性化配置。
3. 运行时动态配置管理系统。

---

## 3. 统一目录与文件组织

## 3.1 代码目录（读取能力）

```text
src/biz/services/wealth/config/
  strategy_config_service.py
  strategy_config_registry.py
  strategy_config_models.py
  __init__.py
```

职责分工：

1. `strategy_config_service.py`：统一对外读取入口（模块不可直接读文件）。
2. `strategy_config_registry.py`：维护 moduleKey -> 配置文件路径 -> 模型映射。
3. `strategy_config_models.py`：公共元信息模型 + 模块 payload 模型。

## 3.2 配置目录（JSON 文件）

```text
src/biz/services/wealth/config/definitions/
  major_indices.cn_a.v1.json
  leaderboard.cn_a.v1.json
  market_summary.cn_a.v1.json
```

说明：

1. 后续新增模块，统一放到 `definitions/`。
2. 文件命名建议：`<module>.<market>.<majorVersion>.json`。

---

## 4. 统一配置文件结构（最小必需）

每个配置文件必须满足：

```json
{
  "moduleKey": "majorIndices",
  "market": "CN_A",
  "version": "1.0.0",
  "updatedAt": "2026-05-08T21:00:00+08:00",
  "updatedBy": "owner-id-or-name",
  "payload": {}
}
```

字段要求：

1. `moduleKey`：模块唯一键（如 `majorIndices`、`leaderboards`、`marketSummary`）。
2. `market`：市场域（首期固定 `CN_A`）。
3. `version`：语义版本号。
4. `updatedAt`：更新时间（ISO-8601）。
5. `updatedBy`：更新人（账号或标识）。
6. `payload`：模块私有策略体（由模块模型校验）。

---

## 5. 读取接口（统一入口）

模块侧只允许调用统一入口，不允许自己打开 JSON 文件。

建议接口：

1. `get_config(module_key: str, market: str) -> StrategyConfigEnvelope`
2. `get_payload(module_key: str, market: str) -> <ModulePayloadModel>`
3. `get_version(module_key: str, market: str) -> str`

约束：

1. 不提供“忽略校验”开关。
2. 不提供“文件不存在时回退默认值”行为。
3. 不提供“热更新刷新接口”。

---

## 6. 严格失败策略（可靠性基线）

触发任一问题必须立即失败：

1. 配置文件不存在。
2. JSON 解析失败。
3. 元信息字段缺失或非法（`version/updatedAt/updatedBy` 等）。
4. `payload` 校验失败（字段缺失、类型不符、规则不满足）。

失败行为：

1. 后端返回结构化错误（不吞错，不静默回退）。
2. 模块状态进入 `ERROR`，由页面按既定状态规则展示。

---

## 7. 生效与发布方式

1. 本地或线上更新配置文件后，必须重启服务生效。
2. 配置变更应与代码提交同仓管理，进入 Git 版本审计。
3. 配置改动建议走 PR 评审（至少校验：
   - 结构合法
   - payload 合法
   - 版本号已更新）。

---

## 8. 模块接入规范

每个模块接入策略配置中心时，必须满足：

1. 模块内部不再直接读取本地 JSON。
2. 模块实现中只消费 `strategy_config_service` 返回对象。
3. 模块文档（三件套）中明确引用本规范。
4. 模块 payload 的字段定义写入该模块 implementation design。

---

## 9. 不做事项（防止过度设计）

本阶段明确不做：

1. 不上数据库配置中心。
2. 不做在线热更新。
3. 不做配置回退链（last good version）。
4. 不做多层缓存体系（只做进程内最小读取缓存或无缓存）。
5. 不做跨模块配置继承机制。

---

## 10. 里程碑（最小执行顺序）

1. M1：建立 `strategy_config_service` 基础骨架。
2. M2：主要指数接入统一读取。
3. M3：榜单接入统一读取。
4. M4：市场客观总结接入统一读取。
5. M5：删除模块内分散配置读取逻辑，完成收敛。

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：冻结策略配置中心最小方案（JSON/严格失败/重启生效/版本元信息） | Codex |

---

配套门禁文档：  
[策略配置中心 M1 编码门禁 v1](/Users/congming/github/goldenshare/wealth/docs/system/strategy-config-center-m1-coding-gate-v1.md)
