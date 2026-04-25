# AGENTS.md — 仓库根规则（重构收尾基线）

## 适用范围
本文件适用于仓库根目录及所有子目录。若子目录存在更近的 `AGENTS.md`，以更近规则为准。

---

## 当前结构（已收敛）

```text
src/
  foundation/
  ops/
  biz/
  app/
  platform/      # legacy/compat（冻结）
  operations/    # legacy/compat（冻结）
```

- `foundation` / `ops` / `biz` 是三个业务子系统
- `app` 是组合根（composition root），不是业务子系统
- `platform` / `operations` 已进入 legacy 冻结态，不承接新主实现

---

## 动手前必读

1. `docs/architecture/subsystem-boundary-plan.md`
2. `docs/architecture/dependency-matrix.md`
3. `docs/architecture/platform-split-plan.md`
4. `docs/architecture/ops-consolidation-plan.md`
5. `src/AGENTS.md` 与目标目录下更近的 `AGENTS.md`

---

## 硬约束

1. 不得回流主实现到 `src/platform` 或 `src/operations`。
2. 不得引入 `foundation -> ops|biz|app|platform|operations` 反向依赖。
3. 不做 big-bang 重构；每轮只做一个清晰目标。
4. 删除兼容层前必须先做引用审计，再做最小回归。
5. 禁止“无依据猜测式编码”（No source, no code）。
6. 不接受“补丁叠补丁”修复；当现有实现已进入烂代码堆积状态，必须主动提出重构或重写方案。


---

## 目录职责速记

- `src/foundation/**`：数据基座与底层契约
- `src/ops/**`：运维治理与运行时编排
- `src/biz/**`：对上业务 API/查询/服务
- `src/app/**`：入口装配、聚合路由、认证壳、运行壳
- `src/platform/**`：legacy 目录（兼容与清理）
- `src/operations/**`：legacy 目录（兼容与清理）

---

## 交付要求

每次任务结束至少说明：

1. 目标与依据
2. 改动文件
3. 是否影响边界/依赖矩阵
4. 验证结果
5. 风险与后续建议

---

## 提交与推送

- 用户明确要求时可推送到 `origin/dev-interface`。
