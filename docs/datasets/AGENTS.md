# AGENTS.md — `docs/datasets/` 数据集文档规则

## 适用范围

本文件适用于 `docs/datasets/` 目录及其子目录。

---

## 当前数据集事实

1. 数据集身份、中文名、日期模型、输入能力、表映射应收敛到 `DatasetDefinition`。
2. 维护动作与执行计划应收敛到 `DatasetActionRequest + DatasetExecutionPlan + action=maintain`。
3. 旧执行路由只能作为历史实现背景，不再作为用户任务、API 或 UI 主语。

---

## 编写约束

1. 新增或更新数据集文档时，优先引用 DatasetDefinition / date_model / execution plan，不再引用旧任务规格作为主能力说明。
2. 数据集文档不得把旧执行任务名写成当前能力口径。
3. 不要让用户或前端通过内部路由 key、`job_name`、旧 CLI 名称理解一个数据集。
4. 周线/月线、月度窗口、公告日期等时间语义必须引用日期模型单一事实源，不在文档里重新发明规则。

---

## 必读基线

1. [数据集日期模型消费指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)
2. [DatasetDefinition 单一事实源重构方案](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md)
3. [DatasetExecutionPlan 执行计划模型重构方案](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)
4. [股票周/月线同步逻辑说明](/Users/congming/github/goldenshare/docs/datasets/equity-weekly-monthly-sync-logic.md)
