# 文档目录索引（重构后）

## 1. 快速必读（S0）

- [子系统边界基线（收敛后版本）](/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md)
- [子系统依赖矩阵](/Users/congming/github/goldenshare/docs/architecture/dependency-matrix.md)
- [Foundation 当前强约束（统一基线）](/Users/congming/github/goldenshare/docs/architecture/foundation-current-standards.md)
- [Platform 拆分与 cleanup 基线](/Users/congming/github/goldenshare/docs/architecture/platform-split-plan.md)
- [Ops 收敛基线（收敛后版本）](/Users/congming/github/goldenshare/docs/architecture/ops-consolidation-plan.md)
- [Ops 当前契约（统一版）](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md)
- [前端当前强约束（统一基线）](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md)
- [数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)
- [工作流开发说明模板](/Users/congming/github/goldenshare/docs/templates/workflow-development-template.md)

## 2. 目录结构（当前）

```text
docs/
  architecture/  # 架构基线、边界、收敛计划
  ops/           # 运营后台契约、流程与专题
  datasets/      # 数据集研发与策略文档
  frontend/      # 前端治理、设计与交付规范
  platform/      # 对上业务接口规范
  release/       # 发布流程
  product/       # 产品需求与原始材料
  templates/     # 开发模板
  sources/       # 数据源接口说明（源站文档镜像/摘要）
  governance/    # 文档治理与待整合清单
```

## 3. 架构与治理（S1）

- [设计原则](/Users/congming/github/goldenshare/docs/architecture/design-principles.md)
- [Foundation 当前强约束（统一基线）](/Users/congming/github/goldenshare/docs/architecture/foundation-current-standards.md)
- [Foundation 多源数据基座升级与停机迁移方案 v1（历史归档）](/Users/congming/github/goldenshare/docs/architecture/foundation-multi-source-upgrade-and-migration-v1.md)
- [Foundation 开发上手指南与历史遗留清单 v1](/Users/congming/github/goldenshare/docs/architecture/foundation-onboarding-and-legacy-checklist-v1.md)
- [数据集发布治理规范 v1（Raw -> Std -> Serving）](/Users/congming/github/goldenshare/docs/architecture/dataset-publish-governance-spec-v1.md)
- [数据同步统一架构与全量数据集矩阵 v2](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-unified-architecture-matrix-v1.md)
- [数据同步 V2 重设计方案（含平稳迁移，历史主案）](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-redesign-plan.md)
- [数据集日期模型收敛方案 v1（单一事实源）](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-convergence-plan-v1.md)
- [数据集日期模型消费指南 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)
- [Sync V2 数据集策略简化方案 v1（全量 47 个 V2 数据集）](/Users/congming/github/goldenshare/docs/architecture/sync-v2-dataset-strategy-simplification-plan-v1.md)
- [Sync V2 Registry 结构化重构方案 v1（两阶段）](/Users/congming/github/goldenshare/docs/architecture/sync-v2-registry-structure-refactor-plan-v1.md)
- [Sync V2 Registry 开发指南 v1（新增数据集门禁）](/Users/congming/github/goldenshare/docs/architecture/sync-v2-registry-development-guide-v1.md)
- [Sync V1 旧路径移除执行计划 v1](/Users/congming/github/goldenshare/docs/architecture/sync-v1-removal-execution-plan-v1.md)
- [周/月锚点交易日口径确认 v1](/Users/congming/github/goldenshare/docs/architecture/weekly-monthly-trade-date-anchor-confirmation-v1.md)
- [Tushare 请求策略与 Sync V2 对齐方案 v1（归档）](/Users/congming/github/goldenshare/docs/architecture/tushare-request-policy-alignment-plan-v1.md)
- [Core Serving + Serving Light 分层设计 v1](/Users/congming/github/goldenshare/docs/architecture/core-serving-light-design-v1.md)

## 4. Ops 运营（S2）

- [Ops 运营后台 API 全量说明 v1](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md)
- [Ops Web API 与运维数据能力审查备忘 v1](/Users/congming/github/goldenshare/docs/ops/ops-web-api-capability-review-memo-v1.md)
- [Ops Execution API 队列语义收口方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-execution-api-queue-semantics-alignment-plan-v1.md)
- [手动维护动作模型收敛方案 v2](/Users/congming/github/goldenshare/docs/ops/ops-manual-action-model-alignment-plan-v2.md)
- [手动维护动作模型收敛方案 v1（历史方案）](/Users/congming/github/goldenshare/docs/ops/ops-manual-action-model-alignment-plan-v1.md)
- [Sync 任务 Error/Reason 统一编码与可观测性方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-sync-error-reason-code-observability-plan-v1.md)
- [运维工作流目录与实现清单](/Users/congming/github/goldenshare/docs/ops/ops-workflow-catalog-v1.md)
- [审查中心设计方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-review-center-design-v1.md)
- [数据集日期完整性审计设计 v1（审查中心）](/Users/congming/github/goldenshare/docs/ops/dataset-date-completeness-audit-design-v1.md)
- [多源对账能力需求 v1](/Users/congming/github/goldenshare/docs/ops/reconcile-capability-requirements-v1.md)
- [数据同步 V2 切换运行手册 v1（Runbook）](/Users/congming/github/goldenshare/docs/ops/dataset-sync-v2-cutover-runbook-v1.md)
- [数据同步 V2 R3 切换方案 v1（板块/热榜/周期栏，归档）](/Users/congming/github/goldenshare/docs/ops/dataset-sync-v2-r3-cutover-plan-v1.md)
- [数据同步 V2 R4-A 切换方案 v1（dividend / stk_holdernumber / index_weight，归档）](/Users/congming/github/goldenshare/docs/ops/dataset-sync-v2-r4a-cutover-plan-v1.md)
- [数据同步 V2 R4-B 切换方案 v1（index_weekly / index_monthly，归档）](/Users/congming/github/goldenshare/docs/ops/dataset-sync-v2-r4b-cutover-plan-v1.md)
- [数据同步 V2 R4-C 切换方案 v1（biying_equity_daily / biying_moneyflow，归档）](/Users/congming/github/goldenshare/docs/ops/dataset-sync-v2-r4c-biying-cutover-plan-v1.md)
- [数据集接口请求策略重审 v1（逐数据集，历史归档）](/Users/congming/github/goldenshare/docs/ops/dataset-request-strategy-reassessment-v1.md)
- [Tushare 全量数据集请求执行口径 v1（仅 Tushare）](/Users/congming/github/goldenshare/docs/ops/tushare-request-execution-policy-v1.md)

说明：数据集停用策略与融合策略中心准备度已并入 [Ops 当前契约（统一版）](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md)。

## 5. 数据集研发（S3）

- [数据集总目录](/Users/congming/github/goldenshare/docs/datasets/dataset-catalog.md)
- [板块与榜单数据集一期](/Users/congming/github/goldenshare/docs/datasets/board-and-ranking-datasets-phase1.md)
- [指数筛选池同步机制说明](/Users/congming/github/goldenshare/docs/datasets/index-series-active-sync-mechanism.md)
- [股票周/月线同步逻辑说明](/Users/congming/github/goldenshare/docs/datasets/equity-weekly-monthly-sync-logic.md)
- [资金流多源融合策略设计 v1](/Users/congming/github/goldenshare/docs/datasets/moneyflow-multi-source-fusion-strategy-v1.md)

说明：资金流 6 数据集的拍板结论已并入各自正式开发文档（不再维护独立拍板清单）。

主要数据集开发说明：
- [BIYING 股票日线](/Users/congming/github/goldenshare/docs/datasets/biying-equity-daily-dataset-development.md)
- [BIYING 资金流向](/Users/congming/github/goldenshare/docs/datasets/biying-moneyflow-dataset-development.md)
- [ETF 基准指数列表](/Users/congming/github/goldenshare/docs/datasets/etf-index-dataset-development.md)
- [ETF 日线行情](/Users/congming/github/goldenshare/docs/datasets/etf-fund-daily-dataset-development.md)
- [基金复权因子](/Users/congming/github/goldenshare/docs/datasets/fund-adj-dataset-development.md)
- [融资融券交易汇总](/Users/congming/github/goldenshare/docs/datasets/margin-dataset-development.md)
- [每日涨跌停价格](/Users/congming/github/goldenshare/docs/datasets/stk-limit-dataset-development.md)
- [神奇九转指标](/Users/congming/github/goldenshare/docs/datasets/stk-nineturn-dataset-development.md)
- [股票历史分钟行情](/Users/congming/github/goldenshare/docs/datasets/stk-mins-dataset-development.md)
- [股票技术面因子（专业版）](/Users/congming/github/goldenshare/docs/datasets/stk-factor-pro-dataset-development.md)
- [股票技术面因子（专业版）全链路重做方案（V2 优先）](/Users/congming/github/goldenshare/docs/datasets/stk-factor-pro-v2-rebuild-plan.md)
- [每日停复牌信息](/Users/congming/github/goldenshare/docs/datasets/suspend-d-dataset-development.md)
- [ST 股票列表](/Users/congming/github/goldenshare/docs/datasets/stock-st-dataset-development.md)
- [个股资金流向（THS）](/Users/congming/github/goldenshare/docs/datasets/moneyflow-ths-dataset-development.md)
- [个股资金流向（DC）](/Users/congming/github/goldenshare/docs/datasets/moneyflow-dc-dataset-development.md)
- [概念板块资金流向（THS）](/Users/congming/github/goldenshare/docs/datasets/moneyflow-cnt-ths-dataset-development.md)
- [行业资金流向（THS）](/Users/congming/github/goldenshare/docs/datasets/moneyflow-ind-ths-dataset-development.md)
- [板块资金流向（DC）](/Users/congming/github/goldenshare/docs/datasets/moneyflow-ind-dc-dataset-development.md)
- [大盘资金流向（DC）](/Users/congming/github/goldenshare/docs/datasets/moneyflow-mkt-dc-dataset-development.md)
- [券商每月荐股](/Users/congming/github/goldenshare/docs/datasets/broker-recommend-dataset-development.md)
- [每日筹码及胜率](/Users/congming/github/goldenshare/docs/datasets/cyq-perf-dataset-development.md)

## 6. 前端、业务与发布（S4）

- [前端技术与组件体系选型建议](/Users/congming/github/goldenshare/docs/frontend/frontend-technology-and-component-selection.md)
- [前端当前强约束（统一基线）](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md)
- [前端应用一期设计](/Users/congming/github/goldenshare/docs/frontend/frontend-application-phase1.md)
- [前端交付流程规范 v1](/Users/congming/github/goldenshare/docs/frontend/frontend-delivery-workflow-v1.md)
- [前端设计 Tokens 与组件目录 v2](/Users/congming/github/goldenshare/docs/frontend/frontend-design-tokens-and-component-catalog-v1.md)
- [前端组件 Showcase v1（HTML 对照）](/Users/congming/github/goldenshare/docs/frontend/frontend-component-showcase-v1.html)
- [前端治理落地总计划与评审记录 v2](/Users/congming/github/goldenshare/docs/frontend/frontend-governance-rollout-plan-v1.md)
- [前端 Phase 2 执行简报 v1](/Users/congming/github/goldenshare/docs/frontend/frontend-phase2-execution-brief-v1.md)
- [前端 Phase 5 执行计划 v1](/Users/congming/github/goldenshare/docs/frontend/frontend-phase5-execution-plan-v1.md)
- [前端 Phase 6 执行计划 v1](/Users/congming/github/goldenshare/docs/frontend/frontend-phase6-execution-plan-v1.md)
- [前端 Phase 6 P6-1 低风险推广批边界卡 v1](/Users/congming/github/goldenshare/docs/frontend/frontend-phase6-p6-1-boundary-card-v1.md)
- [前端 Phase 6 P6-2 审查中心推广批边界卡 v1](/Users/congming/github/goldenshare/docs/frontend/frontend-phase6-p6-2-boundary-card-v1.md)
- [前端 Phase 6 P6-3 数据详情推广批边界卡 v1](/Users/congming/github/goldenshare/docs/frontend/frontend-phase6-p6-3-boundary-card-v1.md)
- [前端 Phase 6 P6-4 管理配置推广批边界卡 v1](/Users/congming/github/goldenshare/docs/frontend/frontend-phase6-p6-4-boundary-card-v1.md)
- [前端 Phase 6 推广收口总结 v1](/Users/congming/github/goldenshare/docs/frontend/frontend-phase6-rollout-summary-v1.md)
- [前端专项：Overview 旧视觉遗留收口边界卡 v1](/Users/congming/github/goldenshare/docs/frontend/frontend-overview-legacy-visual-cleanup-boundary-card-v1.md)
- [前端质量门禁矩阵 v1](/Users/congming/github/goldenshare/docs/frontend/frontend-quality-gate-matrix-v1.md)
- [前端回归与截图基线流程 v1](/Users/congming/github/goldenshare/docs/frontend/frontend-regression-and-baseline-workflow-v1.md)
- [前端 Smoke 与视觉回归门禁 v1](/Users/congming/github/goldenshare/docs/frontend/frontend-smoke-visual-gate-v1.md)
- [行情主系统接口规范](/Users/congming/github/goldenshare/docs/platform/quote-detail-api-spec-v1.md)
- [发版流程 v1](/Users/congming/github/goldenshare/docs/release/release-process-v1.md)

## 7. 数据源接口说明

- [数据源接口说明目录规范](/Users/congming/github/goldenshare/docs/sources/README.md)
- [Tushare 接口说明目录](/Users/congming/github/goldenshare/docs/sources/tushare/README.md)
- [Tushare 接口总索引（CSV）](/Users/congming/github/goldenshare/docs/sources/tushare/docs_index.csv)
- [BIYING 接口说明目录](/Users/congming/github/goldenshare/docs/sources/biying/README.md)

## 8. 文档治理

- [文档信息架构与待整合清单 v1](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md)
- [文档维护基线 v1](/Users/congming/github/goldenshare/docs/governance/docs-maintenance-baseline-v1.md)

## 9. 产品原始材料

- [行情图表页接口需求说明](/Users/congming/github/goldenshare/docs/product/行情图表页接口需求说明_基于当前数据基座.md)
- [财势乾坤交易系统需求说明（PDF）](/Users/congming/github/goldenshare/docs/product/财势乾坤交易系统需求说明.pdf)
