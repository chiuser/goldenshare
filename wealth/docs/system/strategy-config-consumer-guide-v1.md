# wealth 策略配置中心｜业务开发者一页式接入手册 v1

> 读者：`wealth` 业务模块开发者（主要指数、榜单、summary 等）。  
> 目标：3 分钟完成“新增配置 + 注册 + 读取”接入。  
> 范围：只讲使用，不讲底层实现细节。

---

## 0. 先记住这 4 条硬规则

1. 配置只放仓库 JSON，不接数据库。  
2. 配置校验失败必须直接失败（严格模式），不回退。  
3. 配置改完后重启生效，不做热更新。  
4. 每个配置文件必须有：`version`、`updatedAt`、`updatedBy`。

---

## 1. 你要改哪些位置

1. 新增/修改配置文件：  
   `src/biz/services/wealth/config/definitions/*.json`
2. 注册配置项：  
   `src/biz/services/wealth/config/strategy_config_registry.py`
3. 在业务模块里读取配置：  
   `src/biz/services/wealth/config/strategy_config_service.py`

---

## 2. 标准 JSON 模板（可直接复制）

```json
{
  "moduleKey": "yourModuleKey",
  "market": "CN_A",
  "version": "1.0.0",
  "updatedAt": "2026-05-08T21:00:00+08:00",
  "updatedBy": "your-team",
  "payload": {}
}
```

字段要求：

1. `moduleKey`：模块唯一键（例如 `majorIndices`）。  
2. `market`：首期固定 `CN_A`。  
3. `version`：`x.y.z`。  
4. `updatedAt`：必须带时区偏移（`+08:00` 这种）。  
5. `updatedBy`：非空。  
6. `payload`：模块自己的配置体（由模块模型强校验）。

---

## 3. 接入步骤（最小 3 步）

## 第一步：定义 payload 模型

在 `strategy_config_models.py` 里新增/更新模块 payload 模型（`pydantic`），把业务规则写进校验器。

例子（示意）：

```python
class ExamplePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_keys: list[str] = Field(alias="itemKeys", min_length=1)
```

## 第二步：注册 moduleKey + 文件 + 模型

在 `strategy_config_registry.py` 的 `get_default_strategy_config_registrations()` 里登记：

```python
StrategyConfigRegistration(
    module_key="exampleModule",
    market="CN_A",
    definition_file="example_module.cn_a.v1.json",
    payload_model=ExamplePayload,
)
```

## 第三步：业务代码只走统一读取入口

```python
from src.biz.services.wealth.config import StrategyConfigService

service = StrategyConfigService()
record = service.get_config(module_key="exampleModule", market="CN_A")

payload = record.payload
version = record.version
```

禁止事项：

1. 禁止业务模块直接 `open()` 读 JSON。  
2. 禁止绕开模型校验。  
3. 禁止在校验失败时“临时回退默认值”。

---

## 4. 失败与异常（如何看报错）

常见异常类型：

1. `StrategyConfigNotFoundError`：没注册或文件不存在。  
2. `StrategyConfigValidationError`：JSON 结构、元信息或 payload 校验失败。  
3. `StrategyConfigRegistrationError`：注册表冲突（重复 key 等）。

排查顺序：

1. 先看 `moduleKey/market` 是否已注册。  
2. 再看 `definition_file` 文件名是否正确。  
3. 再看 JSON 是否缺 `version/updatedAt/updatedBy`。  
4. 最后看 payload 字段是否符合模型。

---

## 5. 开发完成前自检清单

1. 配置文件在 `definitions/`，命名符合 `<module>.<market>.v1.json`。  
2. `version/updatedAt/updatedBy` 都有且合法。  
3. registry 已登记，且无重复 `(moduleKey, market)`。  
4. 业务代码只调用 `StrategyConfigService`。  
5. 通过测试：  
   `pytest -q tests/test_wealth_strategy_config_service.py`

---

## 6. 参考文档

1. [策略配置中心 v1](/Users/congming/github/goldenshare/wealth/docs/system/strategy-config-center-v1.md)  
2. [策略配置中心 M1 编码门禁 v1](/Users/congming/github/goldenshare/wealth/docs/system/strategy-config-center-m1-coding-gate-v1.md)

---

## 7. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：业务开发者一页式接入手册 | Codex |

