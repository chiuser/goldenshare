# 工作流开发说明模板（Workflow Development Template）

> 使用规则：
> - 每新增或重大调整一个 workflow，必须基于本模板新增一份文档，放在 `docs/ops/`。
> - 文档名建议：`ops-workflow-<workflow-key>-development.md`
> - 模板中的“必须/应当”视为交付门禁（Definition of Done）。

## 1. 基本信息

- Workflow Key：
- Workflow 显示名：
- 负责人：
- 关联需求/任务：
- 代码变更范围（文件）：

## 2. 设计目标与边界

- 目标：
- 非目标：
- 为什么需要 workflow（而不是单 job）：

## 3. 调度与执行能力

- 是否支持自动调度：是/否
- 是否支持手动执行：是/否
- 默认调度策略（如有）：
- 支持参数：
  - 参数名：
  - 类型：
  - 是否必填：
  - 默认值：
  - 对应业务语义：

## 4. 步骤编排清单（必须详细）

| 序号 | step_key | 显示名 | job_key | depends_on | default_params |
|---:|---|---|---|---|---|
| 1 |  |  |  |  |  |

补充说明：
- 为什么采用这个顺序：
- 哪些步骤可并行、哪些必须串行：
- 失败后的影响范围：

## 5. 参数传递与覆盖规则

- Workflow 级参数如何传递到 step：
- step `default_params` 如何覆盖：
- 冲突参数如何处理：

## 6. 异常与回滚策略

- 单 step 失败时整体状态：
- 部分成功时补偿策略：
- 取消请求处理策略：
- 可否安全重试：

## 7. 可观测性与运维交互

- 进度上报粒度：
- 关键事件日志（step_started/step_succeeded/step_failed/...）：
- 任务详情页需要展示的信息：

## 8. 测试计划（必须落地）

- 单元测试：
  - 规格注册测试
  - 参数合成测试
- 集成测试：
  - 正常链路
  - 中途失败
  - 取消场景
- 回归测试：
  - 不影响既有 workflow
  - 不影响 catalog/schedule 页面

## 9. 发布与回滚

- 发布前检查项：
- 回滚策略（按 commit / 配置）：
- 风险提示：

## 10. 文档同步清单

- [ ] 更新 `docs/ops/ops-workflow-catalog-v1.md`
- [ ] 更新 `docs/README.md` 索引
- [ ] 如涉及交互变更，更新对应页面说明文档
- [ ] 提交信息明确标注 workflow 变更范围
