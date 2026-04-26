# Dataset Maintain 重构 M-1 到 M8 执行索引 v1

- 状态：执行索引 / 记忆锚点
- 日期：2026-04-26
- 适用范围：`src/foundation/**`、`src/ops/**`、Ops Web API、任务中心前端、相关测试与迁移脚本
- 关联方案：
  - [DatasetDefinition 单一事实源重构方案 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md)
  - [DatasetExecutionPlan 执行计划模型重构方案 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)
  - [工程风险登记簿](/Users/congming/github/goldenshare/docs/governance/engineering-risk-register.md)

---

## 1. 文档目的

本文件只做一件事：把本轮大重构的 `M-1` 到 `M8` 里程碑固定成可检索的执行索引，避免后续只依赖对话记忆。

后续继续本轮任务前，应先读取：

1. 仓库根 `AGENTS.md` 与 `AGENTS.local.md`。
2. 待修改目录的逐级 `AGENTS.md`。
3. 本文件。
4. 上方关联的三份架构/风险方案。

---

## 2. 本轮硬边界

1. 本轮主目标是把数据集维护从旧执行路由心智收敛到 `DatasetDefinition + DatasetExecutionPlan + action=maintain`。
2. 不做计划外“顺手改造”。
3. 遇到不清楚的实现，必须读代码确认，不能猜。
4. 若评估不足导致无法稳妥推进，必须停下来抛出问题。
5. `engineering-risk-register.md` 中当前 P0 不阻碍本轮 M-1 到 M8 开发；但 P0 对应风险必须在本轮主线中被纳入方案、测试和验收。
6. 不连接远程服务器或远程数据库，除非任务明确需要；如需要，必须先遵守 `AGENTS.local.md`。

---

## 3. Milestones

| Milestone | 名称 | 目标 | 主要产物 | 完成判断 |
|---|---|---|---|---|
| M-1 | 复读规则并审计现状入口 | 读取根/本地/目标目录 AGENTS，审计 definition、plan、executor、Ops API、前端入口 | 影响面清单、旧入口清单、关键测试入口 | 知道真实代码怎么连，不靠猜开始实现 |
| M0 | 固化本轮执行边界 | 明确本轮只做 DatasetDefinition、DatasetExecutionPlan、执行层、Ops API/前端切换和旧三件套退出主线 | 本执行索引、关联方案确认 | 后续改动都能回指到本文件或关联方案 |
| M1 | 建立 DatasetDefinition 单一事实源骨架 | 建立数据集定义模型与 registry，让身份、名称、日期模型、输入、写入、观测从一个事实源派生 | definition dataclass、registry、projection 入口、覆盖测试 | 现有数据集可被 definition registry 覆盖 |
| M2 | 建立维护动作到执行计划的 resolver / dry-run | 用 `dataset_key + action=maintain + time_input + filters` 生成 `DatasetExecutionPlan` | `DatasetActionRequest`、resolver、plan snapshot、dry-run 测试 | point/range/none/month/window 能生成稳定 plan |
| M3 | 收敛执行层状态与事务语义 | 执行器消费 plan；处理 data transaction 与 ops state 分离；收口旧状态写入语义 | plan executor、事务策略、结构化进度、单一 outcome 写入语义 | 不再依赖分裂状态写入作为主链 |
| M4 | 切换 Ops API / 前端消费新模型 | 手动任务、任务记录、详情、自动任务相关接口消费新字段 | API schema、query/service 调整、前端类型和页面适配 | UI 不再需要理解旧 spec 路径 |
| M5 | 准备停机迁移与状态重建脚本 | 围绕 execution / schedule / resource state 做停机迁移准备 | migration 草案、seed/rebuild 脚本、演练说明 | 本地可重建，新旧运行状态语义可切换 |
| M6 | 删除旧执行语义主链引用 | 主链删除旧执行路由作为执行模型的引用 | dispatcher/spec/workflow/schedule 旧分支删除，测试断言更新 | 活跃代码旧执行路由引用清零 |
| M7 | 补齐架构测试和门禁 | 增加 definition、plan、旧名清零、`__ALL__`、事务边界、进度语义等护栏 | 单测、Web API 测试、架构测试、lint | 后续改动不能绕回旧模型或隐式大事务 |
| M8 | 全量验证与交付总结 | 跑后端、架构、ingestion、Ops API、前端相关门禁并总结 | 验证记录、边界影响、剩余风险、后续建议 | 交付说明完整，主目标可验收 |

---

## 4. 关键验收口径

1. 新 execution 最终应由 `DatasetActionRequest` 创建。
2. 执行器入口最终只消费 `DatasetExecutionPlan`。
3. schedule 绑定 dataset action 或 workflow，不绑定旧 spec。
4. workflow step 引用 dataset action，不引用旧 job key。
5. 任务记录和详情不依赖前端本地格式化函数处理旧路径。
6. 活跃代码中旧三件套引用清零。
7. 进度展示中文化，API 保留结构化 progress snapshot。
8. 大数据集按业务 unit 安全提交，ops 状态失败不回滚业务数据。
9. `__ALL__` 不得作为业务哨兵进入请求、query context 或落库字段。
10. 测试、lint、文档校验与前端 smoke 按影响面执行。
