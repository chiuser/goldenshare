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
- 数据集事实源收敛到 `src/foundation/datasets/**` 的 `DatasetDefinition`
- 数据维护执行计划收敛到 `src/foundation/ingestion/**` 的 `DatasetExecutionPlan`
- 任务运行与详情观测收敛到 `src/ops/**` 的 TaskRun 主链

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
7. 忘掉老架构，忘掉历史包袱，必须在新架构下设计合理方案。任何改动不允许出现兼容方案，临时方案。不接受临时修复。管理员脾气非常大。必须按指令行事。
8. 不允许自己发挥，添加自己认为的功能或需求。尤其是管理员没提出来的时候。
9. 重构要彻底，不要留任何兼容性代码在仓库中。
10. Ops/TaskRun/freshness/snapshot/schedule 等状态写入不得影响业务数据表的读写与事务提交；状态写入失败只能影响观测状态，不允许阻塞、回滚或污染 `raw_*`、`core_*`、`core_serving*` 等业务数据。
11. 写给人看的文档，不要写晦涩难懂，给机器看的文档。
12. 审计必须看代码，不要靠猜；不得用文档、印象、命名或历史经验替代对当前实现的逐项核验。
13. 改契约时，必须做全量消费者审计，旧口径必须清零；不允许页面、查询层或其他调用方自行拼装事实字段。
14. 新增 Alembic 迁移前必须先检查当前迁移 head，`down_revision` 只能接真实 head，不得按文件名、日期或印象猜。
15. 任何技术方案的变更，如果之前有对应的方案设计文档，必须同步落回原方案设计文档，禁止让现实代码、执行口径与既有设计文档脱节。
16. Ops/TaskRun 只保存用户或调度意图，`DatasetActionResolver` 才负责按 `DatasetDefinition.date_model` 归一化为执行计划，源接口参数只能在 ingestion request builder 中生成。
17. 开发、迁移、测试脚本中禁止擅自删除、清空或重建任何业务数据表、配置表、对象池表；确需清理必须有用户明确指令、备份方案和逐表清单。
18. 任何新增数据集或修改 `DatasetDefinition.date_model/input_shape/observed_field` 前，必须把“时间输入语义、执行/unit 语义、freshness/audit 语义”三层拆开逐项确认；严禁把“支持按日期输入”误写成“要求每天都有数据”。
19. 任何修改 `DatasetDefinition` 事实源的变更，必须先做全量消费者审计，至少覆盖：manual actions、catalog、workflow、resolver/unit planner、request builder、freshness、dataset cards、snapshot rebuild、date completeness audit、自动任务日期策略、前端时间控件、相关测试与文档。
20. 若 `date_model.bucket_rule=not_applicable`，必须额外说明：它只是“不按连续业务日期做 freshness/audit 判断”，还是连时间输入都不支持；禁止默认把 `not_applicable` 简化理解成“无日期输入”。
21. 新增数据集前必须做源接口真实行为验证，至少覆盖：不传业务参数、只传对象过滤、传时间点、传时间区间、分页拉取。源接口有可选日期参数，不等于该数据集应按日期驱动；若不传日期可拉全集且日期过滤会漏历史数据，主模型必须是 no-time snapshot。
22. 可选源接口参数不得自动暴露为运营输入字段。只有当该参数对应明确用户意图、不会造成数据缺失、并已通过真实请求和样本行数证明时，才允许进入 `DatasetDefinition.input_model`。
23. 新数据集完成前必须用真实样本或最小真实同步证明“源端行数、归一化行数、写入行数、拒绝原因、目标表行数”一致；任何 reject 都必须解释到 reason code 和样本，禁止把大批 reject 当作正常现象跳过。
---

## 目录职责速记

- `src/foundation/**`：数据基座与底层契约
- `src/ops/**`：运维治理、TaskRun 运行时编排与观测
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
5. 下一步工作
6. 风险与后续建议

---

## 提交与推送

- 用户明确要求时可推送到 `origin/dev-interface`。
