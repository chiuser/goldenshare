# AGENTS.md — src/platform legacy / compatibility 规则

## 适用范围

本文件适用于 `src/platform/` 目录及其所有子目录。

---

## 当前目录定位（硬约束）

`src/platform` 现阶段定位为 **compatibility / legacy 目录**。

它的目标是：

1. 承接历史导入路径的兼容壳（shim）
2. 在清理前维持外部行为稳定
3. 为 post-cutover 清理提供最小过渡

它不是：

1. 新主实现目录
2. 新功能开发目录
3. 长期业务逻辑归属目录

---

## 允许与禁止

### 允许（严格最小化）

1. shim/compat 转发文件维护
2. 不改变外部行为的最小 bugfix
3. 与清理相关的最小收敛（注释、文档、导出路径对齐）
4. 为删除兼容层做引用核对与回归验证准备

### 禁止

1. 在 `platform` 新增任何主实现
2. 将 `app/biz/ops` 主逻辑写回 `platform`
3. 在 `platform` 扩展新业务接口、schema、service、query
4. 未经明确计划做大规模迁移或大改行为
5. 以“临时兼容”为由长期堆叠新逻辑

---

## 处理 platform 任务的默认决策顺序

每次改动前先问三个问题：

1. 这段逻辑是否已经在 `src/app` / `src/biz` / `src/ops` 有主实现？
2. 本次需求是否可以通过“保持 shim 不变 + 文档化”完成？
3. 这次动作是否在为“删除兼容层”创造条件？

如果答案是“主实现已存在”，优先考虑：

- 是否应删除或收紧兼容层（在允许的轮次）
- 而不是继续在 `platform` 扩展功能

---

## 当前 compat-only 优先视角

`src/platform` 下大量文件已是 shim。处理时默认按 compat-only 对待，除非有明确证据表明该文件仍承载真实实现。

尤其对以下路径，默认先按 compat-only 思路审视：

1. `platform/api/**`
2. `platform/auth/**`
3. `platform/dependencies/**`
4. `platform/exceptions/**`
5. `platform/models/app/**`
6. `platform/queries/**`
7. `platform/schemas/**`
8. `platform/services/**`
9. `platform/web/app.py`

---

## 仍可能存在真实实现的区域（谨慎）

在 post-cutover 阶段，`platform` 仍可能保留少量真实实现（例如运行入口支撑与静态资源目录）。这些文件不得被“按 shim 误删”。

删除任何 compat 前，必须先完成：

1. 引用审计（代码 + 脚本 + 部署命令）
2. 最小回归用例执行
3. 回滚方案确认

---

## 依赖与边界提醒

1. 禁止引入 `foundation -> platform` 反向依赖。
2. `platform` 不再承接共享基础设施扩展。
3. 所有新增主实现应直接落到 `src/app`、`src/biz`、`src/ops`。

---

## 完成任务时说明要求

每次改动 `platform` 后，必须说明：

1. 本次是否仅为 shim/compat 或最小稳定化修复
2. 是否引入了任何新主实现（必须为否；若是则需回滚）
3. 本次动作是否有助于后续删除兼容层
4. 后续可安全清理候选是什么（若有）

---

## 禁止扩大范围

处理 `platform` 任务时，不得顺手做：

1. 新功能开发
2. 大规模架构重写
3. 与清理无关的代码风格重构
4. 未经计划的一次性删除兼容层

每轮只做明确目标，优先稳定，再清理。
