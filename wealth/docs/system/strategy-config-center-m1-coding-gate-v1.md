# wealth 策略配置中心 M1 编码门禁 v1

> 范围：仅策略配置中心能力本身。  
> 禁止：任何业务模块对接（主要指数/榜单/summary 一律不接入）。

---

## 1. 本轮目标（唯一）

1. 配置目录与 JSON 规范落地（含 `version/updatedAt/updatedBy`）。
2. 统一读取服务 `strategy_config_service` 落地。
3. 注册与严格校验落地（失败即报错，不回退）。
4. 测试门禁落地（仅配置能力测试）。

---

## 2. 本轮禁止事项

1. 不修改任何 `wealth` 业务 API。
2. 不修改主要指数/榜单/summary 的查询/服务实现。
3. 不修改前端页面与契约。
4. 不新增任何模块接入逻辑。

---

## 3. 代码落点（冻结）

```text
src/biz/services/wealth/config/
  strategy_config_models.py
  strategy_config_registry.py
  strategy_config_service.py
  definitions/*.json
```

测试落点：

```text
tests/test_wealth_strategy_config_service.py
```

---

## 4. 测试门禁（必须通过）

1. `pytest -q tests/test_wealth_strategy_config_service.py`

覆盖点要求：

1. 默认配置可读。
2. 注册表无重复。
3. 配置文件缺失时报错。
4. 元信息缺失时报错。
5. payload 非法时报错。
6. `get_version` 可用。

---

## 5. 验收标准

1. 三个默认配置文件均包含 `version/updatedAt/updatedBy`。
2. 模块代码无法绕过 `strategy_config_service` 做“直接读 JSON”。
3. 校验失败时立即失败，无回退行为。
4. 本轮 `git diff` 不包含任何业务模块接入动作。

---

## 6. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：冻结策略配置中心 M1 范围与测试门禁 | Codex |

