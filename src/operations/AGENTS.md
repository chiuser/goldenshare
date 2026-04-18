# AGENTS.md — src/operations 过渡期规则

## 适用范围

本文件适用于 `src/operations/` 目录及其所有子目录。

---

## 当前阶段定义

`src/operations` 是历史运行时/编排目录，未来目标是逐步并入 `src/ops`，不再作为长期独立子系统继续成长。

未来映射方向：

- `src/operations/runtime/**` -> `src/ops/runtime/**`
- `src/operations/services/**` -> `src/ops/services/**`
- `src/operations/specs/**` -> `src/ops/specs/**`
- `src/operations/dataset_status_projection.py` -> 需纳入专项归属判断，不应在迁移计划中遗漏

当前策略是：

- 先冻结新增方向
- 先做归并清单
- 再按 runtime -> specs -> services 的顺序迁移

---

## 本目录当前允许做什么

### 允许

- 修复已有 bug
- 为迁移做最小兼容封装
- 新增 deprecated 注释
- 将旧实现改为薄转发层
- 做 runtime / specs / services 与 `src/ops` 的对照梳理
- 做不改变外部行为的路径过渡

### 不允许

- 把新的长期运行时能力继续优先放在 `src/operations`
- 新增新的跨域依赖
- 继续让 `src/operations` 与 `src/ops` 双中心并行增长
- 在本目录中新增对 `src/biz` 的直接依赖

---

## 目录归属指导

### `operations/runtime`

未来归属：`ops/runtime`

新规则：

- 新的 runtime / scheduler / worker / dispatcher 相关能力优先进入 `src/ops/runtime`
- 本目录已有 runtime 逻辑只做维护与迁移，不再继续加厚

---

### `operations/specs`

未来归属：`ops/specs`

新规则：

- 新的 job spec / workflow spec / registry 优先进入 `src/ops/specs`
- 本目录旧 spec 仅做兼容维护与渐进迁移

---

### `operations/services`

未来归属：`ops/services`

注意：

- 该目录中有一部分服务与 `src/ops/services` 已发生职责重叠
- 处理此目录任务时，必须先判断：
  1. 本服务是否已有 `ops` 同名/近义实现
  2. 是应合并、替换，还是仅保留兼容壳

不要直接无判断地继续在 `operations/services` 中新增长期 service。

---

### `operations/dataset_status_projection.py`

该文件不属于上述三类子目录之一，迁移时容易被遗漏。

规则：

- 必须单独评估其最终归属
- 默认更偏向 `ops` 侧运行时/运维投影能力，而不是继续长期留在 `operations` 根级
- 在未明确前，不要继续围绕该旧路径增加新逻辑

---

## 依赖规则

### 禁止新增 `operations -> biz`

`operations` 当前已经存在历史跨界点，但从现在起不得继续新增：

- 直接 import `src.biz.*`
- 直接调用 biz service 作为本目录的长期依赖

如遇确实需要业务语义的能力，应先判断其最终归属是否本来就属于 `biz` 或可下沉到 `foundation` contract。

---

### 允许依赖方向

在过渡期内，本目录允许依赖：

- `src.foundation`
- `src.operations`
- 必要的 `src.ops` 兼容路径（仅用于迁移过渡）

但不应形成：

- `src.foundation -> src.operations`
- `src.biz <-> src.operations`

---

## 迁移执行顺序

处理本目录任务时，默认按以下顺序考虑：

1. 先判断是否可以直接写入 `src/ops/**`
2. 若必须改旧代码，则尽量把旧代码改薄
3. 优先迁 runtime
4. 再迁 specs
5. 再单独处理 `dataset_status_projection.py`
6. 最后迁 services

原因：

- runtime / specs 通常比 service 归并风险更低
- services 更容易和 ops 现有实现重叠
- 根级文件最容易在迁移计划中被漏掉

---

## 对外兼容规则

在迁移过程中：

- 可以短期保留旧路径导出
- 可以保留兼容 import
- 但必须标注 deprecated
- 兼容层必须尽量薄，不得在兼容层继续生长业务逻辑

---

## 涉及本目录任务时的输出要求

每次完成涉及 `src/operations` 的任务后，必须说明：

1. 本次改动是维护旧路径，还是向 `src/ops` 收敛
2. 涉及 runtime / specs / services / dataset projection 中哪一类
3. 是否新增了兼容层
4. 是否与 `src/ops` 中现有实现存在重叠
5. 是否影响 CLI 命令调用路径
6. 是否影响子系统依赖矩阵

---

## 当前优先级

涉及本目录时，优先级排序如下：

1. 阻止新增 `operations -> biz`
2. 停止新增长期逻辑到 `operations`
3. 做 runtime / specs 的安全迁移
4. 单独判断 `dataset_status_projection.py` 归属
5. 再处理 service 重叠与归并
