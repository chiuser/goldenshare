# AGENTS.md — 仓库根规则（过渡期入口）

本仓库当前处于“后端单仓三子系统收敛”的过渡期。

在开始任何后端重构、目录迁移、边界调整、依赖修复之前，必须先阅读以下文件：

1. `docs/architecture/subsystem-boundary-plan.md`
2. `docs/architecture/dependency-matrix.md`
3. `src/AGENTS.md`
4. 若任务落在具体目录，还必须继续读取对应子目录下的 `AGENTS.md`

## 当前后端目标结构

目标结构不是立刻一次性搬完，而是渐进收敛到：

```text
src/
  foundation/
  ops/
  biz/
  app/
```

其中：
- `foundation` / `ops` / `biz` 是三个业务子系统
- `app` 是很薄的应用壳，不是第四个业务子系统
- `app` 不应通过 big bang 方式一次性创建并整体搬迁 `platform`
- 当前应先区分 `platform` 中的 app 壳职责与业务职责，再逐步抽出 `app`

## 当前最重要的规则

1. 不要在没有阅读架构文档与 AGENTS 的情况下直接重构。
2. 不要做 big bang 式目录搬迁。
3. 不要把“目录迁移 + 业务重写 + 架构重做”混在一次任务中。
4. 不要继续让 `foundation` 依赖 `ops` / `biz` / `platform`。
5. 不要继续在 `platform` 中新增长期业务 API / Query / Service / Schema。
6. 不要继续在 `operations` 中新增长期归属逻辑；新的 runtime/spec/service 优先考虑 `src/ops/**`。
7. 所有重构任务都应优先：
   - 先冻结边界
   - 再加测试护栏
   - 再拆反向依赖
   - 最后再做物理迁移

## 当前允许的 Git 操作

如用户明确要求，允许：
- 创建分支
- 提交代码
- 推送到 `dev-interface`

但在推送前，必须清楚说明：
- 本次改动目标
- 改动文件
- 验证结果
- 剩余风险

不要在未说明影响范围的情况下直接推送。
