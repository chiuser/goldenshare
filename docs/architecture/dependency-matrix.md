# 子系统依赖矩阵

## 文档目的

本文档用于定义后端单仓的目标依赖方向，并作为架构测试与重构过程的依据。

本矩阵对应的目标结构为：

```text
src/
  foundation/
  ops/
  biz/
  app/
```

其中：

- `foundation` / `ops` / `biz` 是三个业务子系统
- `app` 是很薄的应用壳，只做组合根工作

---

## 目标依赖原则

### 总原则

依赖方向必须尽量单向、稳定、可测试：

- 最底层是 `foundation`
- 中间层是 `ops` 与 `biz`
- 最上层是 `app`

`app` 可以依赖下层；
下层不能反向依赖上层；
`ops` 与 `biz` 之间不直接互相依赖。

---

## 允许依赖

- `foundation` -> `foundation`
- `ops` -> `foundation`, `ops`
- `biz` -> `foundation`, `biz`
- `app` -> `foundation`, `ops`, `biz`, `app`
- `tests` -> all

说明：

- `tests` 允许依赖全部模块，但不应成为反向依赖的借口
- `frontend` 不在本文约束范围内

---

## 禁止依赖

- `foundation` -> `ops`, `operations`, `biz`, `platform`, `app`
- `ops` -> `biz`
- `operations` -> `biz`
- `biz` -> `ops`, `operations`

说明：

- 过渡期内，`platform` 与 `operations` 仍存在，因此矩阵中保留这两个旧目录名
- 目标是最终消解 `platform` 与 `operations`

---

## 当前已知违规点

### foundation 反向依赖上层

#### 1. 模型全量装载反向依赖

- 文件：`src/foundation/models/all_models.py`
- 问题：foundation 为了“全量元数据装载”直接导入 platform / ops 模型
- 目标修复：迁移到 `src/app/model_registry.py`

#### 2. 同步基类直接依赖 ops

- 文件：`src/foundation/services/sync/base_sync_service.py`
- 问题：foundation 直接依赖 ops 的 job execution 写回能力
- 目标修复：改为 foundation contract + ops 实现

---

### operations 与 biz 跨层调用（已收敛）

#### 3. 历史 operations -> biz 违规已清理

- 历史文件：`src/operations/services/market_mood_walkforward_validation_service.py`
- 收敛结果：主实现已迁到 `src/biz/services/market_mood_walkforward_validation_service.py`
- 当前状态：`tests/architecture/test_subsystem_dependency_matrix.py` 中该违规白名单已移除

---

### platform 混装

#### 4. platform 中存在更像 biz 的能力

样例：

- `src/platform/api/v1/share.py`
- `src/platform/queries/share_market_query_service.py`

问题：

- 业务 API / query 不应长期留在 platform
- platform 应逐步只保留 app 壳职责

---

## 过渡期白名单策略

### 原则

第一版依赖矩阵测试不要求一次性清零全部历史违规点，但必须做到：

1. 不允许新增新的错误依赖
2. 历史技术债必须显式列白名单
3. 白名单按文件粒度维护，不允许按目录整体放开
4. 白名单必须带注释，说明存在原因与后续处理方向

---

## 架构测试实施建议

建议新增测试文件：

```text
tests/architecture/test_subsystem_dependency_matrix.py
```

### 第一版建议覆盖的规则

1. `src/foundation/**` 不得 import：
   - `src.ops`
   - `src.operations`
   - `src.biz`
   - `src.platform`
   - `src.app`

2. `src/ops/**` 不得 import：
   - `src.biz`

3. `src/operations/**` 不得新增 import：
   - `src.biz`

4. `src/biz/**` 不得 import：
   - `src.ops`
   - `src.operations`

---

## 白名单维护规范

白名单建议单独维护在测试文件顶部或独立常量中，形如：

```python
KNOWN_IMPORT_EXCEPTIONS = {
    "src/foundation/models/all_models.py": "历史全量模型装载，计划迁移到 src/app/model_registry.py",
    "src/foundation/services/sync/base_sync_service.py": "历史同步进度写回耦合，计划改为 foundation contract + ops adapter",
}
```

要求：

- 不允许出现“整个目录跳过检查”
- 不允许出现“临时先放开全部”
- 每一条都要能对应到迁移计划中的后续步骤

---

## 收紧策略

### 第一阶段

- 建测试
- 列白名单
- 防新增

### 第二阶段

- 解决 foundation 反向依赖
- 缩减白名单

### 第三阶段

- operations 并入 ops
- platform 业务迁出
- 再次收紧规则

### 第四阶段

- 删除 obsolete 白名单
- 只保留真正必要的过渡兼容项

---

## 判断争议归属时的原则

当一个能力暂时看不清归属时，按以下原则判定：

### 属于 foundation 的信号

- 与具体 HTTP 入口无关
- 与具体运维/业务语义无关
- 更像同步、存储、建模、契约、底层基础设施

### 属于 ops 的信号

- 与运行时编排、任务执行、运维治理、探测、调度、审查中心相关

### 属于 biz 的信号

- 对上暴露业务 API
- 面向业务消费方组织查询输出
- 更像业务域查询与聚合服务

### 属于 app 的信号

- app 创建
- router 聚合
- auth wiring
- dependency wiring
- exception handler
- model registry
- 运行入口

---

## 当前执行要求

从本矩阵生效开始：

1. 新代码必须遵守目标依赖方向
2. 历史目录中的新增逻辑必须朝目标目录收敛
3. 没有明确归属时，先停在设计/计划，不要凭感觉写到旧目录里
4. Codex 执行重构任务时，必须显式说明本次是否影响依赖矩阵
