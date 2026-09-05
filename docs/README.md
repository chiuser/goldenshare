# 文档目录索引（重构后）

> 2026-09-05 M5：旧 Console 的 86 份方案及 3 份模板已退出工作树；必要历史结果合入 [初始化与修复总账](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-bootstrap-legacy-links.md)。
> 新湖接入使用 [正式 Dagster 模板](/Users/congming/github/goldenshare/lake_console/docs/templates/dagster-dataset-onboarding-template.html) 与 [性能治理](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-data-pipeline-performance-governance.md)。旧 Console 代码已在 M6 同轮清退；M6 没有删除物理数据。
> 2026-09-05 M8：用户确认的 106 个旧湖对象及 D01–D05 已精确删除；[执行结果与逐项绝对路径清单](/Users/congming/github/goldenshare/lake_console/docs/design/legacy-lake-console-kopia-old-lake-bootstrap-retirement-low-level-design-v1.md#retirement-m8-results)见 LLD §16.15。正式数据、共享目录、ignored 环境与配置保留。
> 2026-09-06：用途审计后另获批准的 5 项旧 Console 本机环境/产物/配置已移入废纸篓；[精确清单、保留范围和恢复映射](/Users/congming/github/goldenshare/lake_console/docs/design/legacy-lake-console-kopia-old-lake-bootstrap-retirement-low-level-design-v1.md#retirement-local-env-results)见 LLD §16.16。其他环境、配置和共享目录未清理。

## 1. 快速必读（S0）

说明：

- 当前数据维护唯一主链为 `DatasetDefinition -> DatasetExecutionPlan -> IngestionExecutor -> TaskRun`。
- 旧同步架构与历史切换文档已下线，不再保留在主文档目录中。

- [子系统边界基线（收敛后版本）](/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md)
- [子系统依赖矩阵](/Users/congming/github/goldenshare/docs/architecture/dependency-matrix.md)
- [Goldenshare 仓库整体上手总览 v1（HTML）](/Users/congming/github/goldenshare/docs/architecture/goldenshare-repository-onboarding-overview-v1.html)
- [财势量化平台（QTF）首版系统架构方案 v1（M4.1 开发已收口，下一步 M4.2）](/Users/congming/github/goldenshare/docs/architecture/qtf-quant-platform-architecture-v1.html)
- [财势量化平台（QTF）首版低层设计 v1（M4.1 开发已收口，下一步 M4.2）](/Users/congming/github/goldenshare/docs/architecture/qtf-quant-platform-low-level-design-v1.md)
- [Foundation 当前强约束（统一基线）](/Users/congming/github/goldenshare/docs/architecture/foundation-current-standards.md)
- [Platform 拆分与 cleanup 基线](/Users/congming/github/goldenshare/docs/architecture/platform-split-plan.md)
- [Ops 收敛基线（收敛后版本）](/Users/congming/github/goldenshare/docs/architecture/ops-consolidation-plan.md)
- [Ops 当前契约（统一版）](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md)
- [前端当前强约束（统一基线）](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md)
- [数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)
- [Biz 数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/biz-dataset-development-template.md)
- [工作流开发说明模板](/Users/congming/github/goldenshare/docs/templates/workflow-development-template.md)

### 权威入口判定

- 当前运行时行为、API 契约和数据字段：以代码、测试、配置与实际运行事实为准。
- 系统边界与依赖方向：先看子系统边界基线、依赖矩阵和 Foundation/Ops 当前基线。
- 数据集语义与执行事实：分别看 `DatasetDefinition`、`DatasetExecutionPlan` 的现行主案及其代码/测试；枚举参考只解释语义，不维护数量快照。
- 专题方案与 LLD：用于补充局部设计和决策背景；与当前代码冲突时不能替代当前事实源。
- 验收记录、研究报告、历史/冻结文档：用于追溯证据，不作为当前实现依据。

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

- [设计原则（历史参考；当前边界以基线为准）](/Users/congming/github/goldenshare/docs/architecture/design-principles.md)
- [CodeGraph 架构快照（当前代码事实，2026-08-22）](/Users/congming/github/goldenshare/docs/architecture/codegraph-architecture-snapshot.md)
- [旧 Lake Console、Kopia 与旧湖迁移适配器清退专项方案 v2（M1–M8 已提交 / 5 项本机残留已移入废纸篓，记录随本次提交归档）](/Users/congming/github/goldenshare/docs/architecture/legacy-lake-console-and-kopia-retirement-plan-v1.md)
- [旧 Lake Console、Kopia 与旧湖迁移适配器清退 LLD v1（165 份文档矩阵 / M8 结果 §16.15 / 本机残留清理与恢复映射 §16.16）](/Users/congming/github/goldenshare/lake_console/docs/design/legacy-lake-console-kopia-old-lake-bootstrap-retirement-low-level-design-v1.md)
- [Foundation 开发上手指南与历史遗留清单 v1](/Users/congming/github/goldenshare/docs/architecture/foundation-onboarding-and-legacy-checklist-v1.md)
- [数据集发布治理规范 v1（Raw -> Std -> Serving）](/Users/congming/github/goldenshare/docs/architecture/dataset-publish-governance-spec-v1.md)
- [DatasetDefinition 单一事实源重构方案 v1（现行主案）](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md)
- [DatasetDefinition 枚举语义参考 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-enum-reference-v1.md)
- [Dataset Universe 模型收口方案 v1（已完成）](/Users/congming/github/goldenshare/docs/architecture/dataset-universe-model-refactor-plan-v1.md)
- [DatasetDefinition 输入筛选契约清理方案 v1（已实施）](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-input-filter-cleanup-plan-v1.md)
- [DatasetExecutionPlan 执行计划模型重构方案 v1（现行主案）](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)
- [Dataset Maintain 重构 M-1 到 M8 执行索引 v1（历史执行索引）](/Users/congming/github/goldenshare/docs/architecture/dataset-maintenance-refactor-m-1-to-m8-execution-index-v1.md)
- [数据集源端拉取并发执行方案 v1（已实现，待生产验收）](/Users/congming/github/goldenshare/docs/architecture/dataset-fetch-concurrency-execution-plan-v1.md)
- [数据集日期模型消费指南 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)
- [Workflow 时间形状与时间制度分析 v1（M2 已落地）](/Users/congming/github/goldenshare/docs/architecture/workflow-time-shape-vs-time-regime-analysis-v1.md)
- [实时行情流架构方案 v1（HTML，日线/分钟已接入，端到端验收已完成）](/Users/congming/github/goldenshare/docs/architecture/realtime-market-data-stream-architecture-v1.html)
- [股票实时日线流技术落地方案 v1（日线已上线 / 统一 collector 已承载分钟 feed / 端到端验收已完成）](/Users/congming/github/goldenshare/docs/architecture/realtime-market-data-stream-technical-plan-v1.md)
- [A股实时分钟流架构方案 v1（HTML，M7/M8 已完成）](/Users/congming/github/goldenshare/docs/architecture/realtime-stock-minute-stream-architecture-v1.html)
- [A股实时分钟 M3 开市真实验证记录（历史验收记录）](/Users/congming/github/goldenshare/docs/architecture/realtime-stock-minute-m3-open-market-validation-2026-06-01.md)
- [股票当日分时序列按需查询方案 v1（方案待开发；补充时段验证待完成）](/Users/congming/github/goldenshare/docs/architecture/realtime-stock-intraday-minutes-on-demand-plan-v1.md)
- [ETF 实时日线流接入方案 v1（代码已接入 / 生产已启用 / 开市批次验收已完成）](/Users/congming/github/goldenshare/docs/architecture/realtime-etf-daily-stream-plan-v1.md)
- [ETF 实时分钟流接入方案 v1（仅保留源端与调度证据 / 覆盖范围须重新基线 / 当前不可开工）](/Users/congming/github/goldenshare/docs/architecture/realtime-etf-minute-stream-plan-v1.md)
- [ETF 实时分钟流接入 LLD v1（旧池实现设计已撤销 / 当前不可作为编码依据）](/Users/congming/github/goldenshare/docs/architecture/realtime-etf-minute-stream-low-level-design-v1.md)
- [ETF 基础信息重建与下游数据审计清理技术方案 v1（M0-M12 开发与既定生产动作已完成 / SH 与 fund daily 补充验收已通过 / SZ 与实时待验）](/Users/congming/github/goldenshare/docs/architecture/etf-basic-rebuild-and-downstream-data-audit-cleanup-plan-v1.md)
- [ETF 基础信息重建与下游数据审计清理 LLD v1（P0-P12 / R1-R5 已完成 / 最终关闭补充验收执行中）](/Users/congming/github/goldenshare/docs/architecture/etf-basic-rebuild-and-downstream-data-audit-cleanup-low-level-design-v1.md)
- [ETF 历史分钟行情数据集接入方案 v1（Basic 驱动、Preview、多代码手动任务与 2026 年指定区间生产对账已完成）](/Users/congming/github/goldenshare/docs/datasets/etf-mins-dataset-development.md)
- [ETF 历史分钟行情数据集 LLD v1（多代码扇开与生产补拉验收已完成）](/Users/congming/github/goldenshare/docs/datasets/etf-mins-dataset-low-level-design-v1.md)
- [ETF 日线与复权因子 DG 数据湖接入技术方案 v1（已结案，历史与日常链验收及治理门禁已闭环）](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-etf-daily-data-onboarding-plan-v1.md)
- [ETF 日线与复权因子 DG 数据湖接入 LLD v1（已结案，固定治理回归与事后修复证据已补齐）](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-etf-daily-data-onboarding-low-level-design-v1.md)
- [ETF 日线与复权因子 DG 接入 P0 真实验证报告（开发门禁已通过，21:00 复验转为启用前门禁）](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-etf-daily-data-onboarding-p0-audit-2026-09-02.md)
- [ETF 日线与复权因子 DG 接入 P2 最小真实样本验收（通过，仅写隔离目录）](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-etf-daily-data-onboarding-p2-real-sample-2026-09-02.md)
- [上证指数日线趋势通道实时计算方案 v1（代码已实现，生产验收已完成）](/Users/congming/github/goldenshare/docs/architecture/sse-daily-trend-channel-realtime-computation-plan-v1.md)
- [上证指数日线趋势通道实时计算 LLD v1（代码已实现，生产验收已完成）](/Users/congming/github/goldenshare/docs/architecture/sse-daily-trend-channel-realtime-computation-low-level-design-v1.md)
- [上证指数日线趋势通道 M4 只读与性能验收报告（历史验收快照）](/Users/congming/github/goldenshare/docs/architecture/sse-daily-trend-channel-m4-readonly-performance-validation-2026-08-10.md)
- [股票日线趋势通道 Lake 数据集接入技术方案 v1（M0 已通过，待开发）](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-daily-trend-channel-dataset-onboarding-plan-v1.md)
- [股票日线趋势通道 Lake 数据集接入 LLD v1（M0 已通过，待开发）](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-daily-trend-channel-dataset-onboarding-low-level-design-v1.md)
- [股票日线趋势通道 M0 只读规模与性能验证报告（M0 已通过）](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-daily-trend-channel-m0-readonly-performance-validation-2026-09-01.md)
- [ETF 激活池历史设计与退场记录 v1（代码与生产物理表均已退场）](/Users/congming/github/goldenshare/docs/architecture/etf-active-pool-design-plan-v1.md)
- [ETF 激活池历史 LLD 与退场实现记录 v1（P3-P8 代码退场与 P11 生产 drop 均已完成）](/Users/congming/github/goldenshare/docs/architecture/etf-active-pool-low-level-design-v1.md)
- [股票周/月线自然锚点日期模型修正方案 v1（已实施）](/Users/congming/github/goldenshare/docs/architecture/stk-period-calendar-anchor-date-model-fix-plan-v1.md)
- [周/月锚点交易日口径确认 v1](/Users/congming/github/goldenshare/docs/architecture/weekly-monthly-trade-date-anchor-confirmation-v1.md)
- [Core Serving + Serving Light 分层设计 v1](/Users/congming/github/goldenshare/docs/architecture/core-serving-light-design-v1.md)
- [新闻—个股关联技术方案 v1（已实现并结案，2026-09-01）](/Users/congming/github/goldenshare/docs/architecture/news-stock-linking-technical-solution-v1.md)
- [新闻—个股关联低层设计 LLD v1（已实现并结案，2026-09-01）](/Users/congming/github/goldenshare/docs/architecture/news-stock-linking-low-level-design-v1.md)
- [`top_list` 业务身份与来源版本收口方案 V1（已实施；后续数值规则待决策）](/Users/congming/github/goldenshare/docs/architecture/top-list-business-identity-and-source-version-plan-v1.md)
> 本节中涉及旧 `lake_console/backend`、Kopia 或旧 Lake Root 的条目，均保留作历史实现/方案证据；不作为当前 Dagster Lake、新开发、迁移、bootstrap、修复或写湖依据。当前正式 Lake 规则以根目录 `AGENTS.md` 和 `lake_console/orchestrator/src/orchestrator/defs/paths.py` 为准，禁止新增或调用 Kopia。


## 4. Ops 运营（S2）

- [Ops 运营后台 API 全量说明 v1](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md)
- [Ops TaskRun 执行观测模型重设计方案 v1（主链已上线，长分页已部署，待运行态验收）](/Users/congming/github/goldenshare/docs/ops/ops-task-run-observability-redesign-plan-v1.md)
- [Ops 任务完成副作用 Worker 方案 v1（本地实现完成，待部署验收）](/Users/congming/github/goldenshare/docs/ops/ops-task-completion-side-effect-worker-plan-v1.md)
- [Ops 任务详情实时 Unit 预计完成时间 LLD v1（已实现，待发版验收）](/Users/congming/github/goldenshare/docs/ops/ops-task-run-live-unit-eta-display-lld-v1.md)
- [手动维护动作模型收敛方案 v2](/Users/congming/github/goldenshare/docs/ops/ops-manual-action-model-alignment-plan-v2.md)
- [Ops 手动维护时间模式升级方案 v1（已实施，2026-05-03）](/Users/congming/github/goldenshare/docs/ops/ops-manual-action-time-mode-upgrade-plan-v1.md)
- [Ops 自动任务日期策略方案 v1（第一期已落地）](/Users/congming/github/goldenshare/docs/ops/ops-schedule-calendar-policy-plan-v1.md)
- [Ops 自动任务能力契约收敛方案 v1（P1–P4 已完成）](/Users/congming/github/goldenshare/docs/ops/ops-automation-capability-contract-plan-v1.md)
- [Ops 自动任务能力契约 LLD v1（P1–P4 已完成）](/Users/congming/github/goldenshare/docs/ops/ops-automation-capability-contract-lld-v1.md)
- [Ops 新闻日内高频自动任务方案 v1（已实现并结案，2026-09-01）](/Users/congming/github/goldenshare/docs/ops/ops-intraday-news-high-frequency-schedule-plan-v1.md)
- [Ops 数据集展示目录配置方案 v1（已落地，展示分组清单待最终确认）](/Users/congming/github/goldenshare/docs/ops/ops-dataset-catalog-view-plan-v1.md)
- [Ops Biz 表数据源展示方案 v1（一期已实现，历史基线）](/Users/congming/github/goldenshare/docs/ops/ops-biz-table-source-display-plan-v1.md)
- [Ops Biz 数据集自动投影与 14 表展示技术方案 v1（代码已实现，待部署验收）](/Users/congming/github/goldenshare/docs/ops/ops-biz-dataset-auto-projection-plan-v1.md)
- [Ops Biz 数据集自动投影与 14 表展示 LLD v1（代码已实现，待部署验收）](/Users/congming/github/goldenshare/docs/ops/ops-biz-dataset-auto-projection-lld-v1.md)
- [Ops Freshness 单一事实源与旧分层观测退场计划 v1（已完成）](/Users/congming/github/goldenshare/docs/ops/ops-freshness-single-source-layer-snapshot-retirement-plan-v1.md)
- [Ops Freshness Policy 显式映射方案 v1（已实施）](/Users/congming/github/goldenshare/docs/ops/ops-freshness-policy-explicit-mapping-plan-v1.md)
- [`stk_mins` 远程源站探测触发方案 v1（已实现，待生产验收）](/Users/congming/github/goldenshare/docs/ops/ops-stk-mins-remote-source-probe-plan-v1.md)
- [`index_daily` 远程源站探测触发方案 v1（已实现，待生产验收）](/Users/congming/github/goldenshare/docs/ops/ops-index-daily-remote-source-probe-plan-v1.md)
- [`index_daily` 远程源站探测触发 LLD v1（已实现，待生产验收）](/Users/congming/github/goldenshare/docs/ops/ops-index-daily-remote-source-probe-lld-v1.md)
- [分钟线数据集独立执行车道方案 v1（三车道已实现，待生产验收）](/Users/congming/github/goldenshare/docs/ops/ops-stk-mins-dedicated-worker-execution-lane-plan-v1.md)
- [分钟线数据集独立执行车道 LLD v1（已实现，待生产验收）](/Users/congming/github/goldenshare/docs/ops/ops-minute-datasets-dedicated-worker-execution-lane-lld-v1.md)
- [`kpl_list` 次日发布适配与自动维护方案 v1（已实现，待生产验收）](/Users/congming/github/goldenshare/docs/ops/ops-kpl-list-next-day-release-plan-v1.md)
- [指数日线完整性闭环与激活池服务能力收口方案 v2（已实现，待生产只读验收）](/Users/congming/github/goldenshare/docs/ops/ops-index-daily-completeness-reconciliation-plan-v2.md)
- [指数日线完整性闭环与激活池服务能力收口 LLD v2（已实现，待生产只读验收）](/Users/congming/github/goldenshare/docs/ops/ops-index-daily-completeness-reconciliation-lld-v2.md)
- [指数日线完整性补漏方案 v1（历史实施基线）](/Users/congming/github/goldenshare/docs/ops/ops-index-daily-completeness-repair-plan-v1.md)
- [指数日线完整性补漏 LLD v1（历史实施基线）](/Users/congming/github/goldenshare/docs/ops/ops-index-daily-completeness-repair-lld-v1.md)
- [Prod 每日筹码分布 HDD Tablespace 迁移方案 v1（已执行）](/Users/congming/github/goldenshare/docs/ops/prod-cyq-chips-hdd-tablespace-migration-plan-v1.md)
- [股票历史分钟行情 tablespace 冷热分层执行记录 v1（2026-04-26 历史快照；年度规则已被两个月滚动热窗口取代）](/Users/congming/github/goldenshare/docs/ops/stk-mins-tablespace-layout-v1.md)
- [Ops 实时流监控页面设计 v1（HTML，日线/分钟/ETF 分组已落地）](/Users/congming/github/goldenshare/docs/ops/ops-realtime-market-data-page-design-v1.html)
- [Ops 实时流配置中心技术方案 v1（HTML，三对象配置中心已落地）](/Users/congming/github/goldenshare/docs/ops/ops-realtime-config-center-technical-plan-v1.html)
- [Ops 实时流配置中心 M1 消费者审计清单 v1（M1–M8 已收口）](/Users/congming/github/goldenshare/docs/ops/ops-realtime-config-center-m1-consumer-audit-v1.md)
- [Ops 实时流配置中心 Showcase v1（HTML，查看/编辑态交互 mock）](/Users/congming/github/goldenshare/docs/ops/ops-realtime-config-center-showcase-v1.html)
- [ETF 实时成交额异动监控重构方案 v1（上游范围须重新基线 / 现有生产监控不变 / 当前不可开工）](/Users/congming/github/goldenshare/docs/ops/ops-etf-realtime-volume-anomaly-monitor-plan-v1.md)
- [ETF 实时成交额异动监控重构 LLD v1（旧池实现设计已撤销 / 当前不可作为编码依据）](/Users/congming/github/goldenshare/docs/ops/ops-etf-realtime-volume-anomaly-monitor-lld-v1.md)
- [运维工作流目录与实现清单](/Users/congming/github/goldenshare/docs/ops/ops-workflow-catalog-v1.md)
- [审查中心设计方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-review-center-design-v1.md)
- [数据集日期完整性审计设计 v2（独立审计系统，M7 已完成本地验证）](/Users/congming/github/goldenshare/docs/ops/dataset-date-completeness-audit-design-v2.md)
- [数据集日期对象矩阵完整性审计方案 v1（HTML，待评审）](/Users/congming/github/goldenshare/docs/ops/dataset-subject-completeness-audit-plan-v1.html)
- [日期对象矩阵审计性能与可观测性专项优化方案 v1（M0/M1 已进入落地）](/Users/congming/github/goldenshare/docs/ops/date-subject-matrix-audit-performance-optimization-plan-v1.md)
- [Ops 新鲜度按 Date Model 收口方案 v1（历史归档）](/Users/congming/github/goldenshare/docs/ops/ops-date-model-freshness-alignment-plan-v1.md)
- [多源对账能力需求 v1](/Users/congming/github/goldenshare/docs/ops/reconcile-capability-requirements-v1.md)
- [Tushare 全量数据集请求执行口径 v1（仅 Tushare）](/Users/congming/github/goldenshare/docs/ops/tushare-request-execution-policy-v1.md)

说明：旧任务 API、旧状态表退场、任务显示名收口等过渡方案已并入 [Ops 当前契约（统一版）](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md)、[Ops API 全量说明](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md) 与 TaskRun 当前基线，主索引不再保留独立历史文档。

## 5. 数据集研发（S3）

- [申万 SW2021 行业分类 `index_classify` Prod 数据集 LLD v1（M0–M5 已完成，M6 历史事实与回补暂缓）](/Users/congming/github/goldenshare/docs/datasets/index-classify-sw2021-low-level-design-v1.md)
- [申万 SW2021 行业成员 `index_member_all` Prod 数据集 LLD v1（M0–M5 已完成，M6 历史事实与回补暂缓）](/Users/congming/github/goldenshare/docs/datasets/index-member-all-sw2021-low-level-design-v1.md)
- [申万 SW2021 行业日行情 `sw_daily` Prod 数据集 LLD v1（M0–M5 已完成，M6 历史事实与回补暂缓）](/Users/congming/github/goldenshare/docs/datasets/sw-daily-sw2021-low-level-design-v1.md)
- [A股市场温度/情绪与 Walk-forward 指标口径说明 v1](/Users/congming/github/goldenshare/docs/datasets/market-mood-metrics-and-walkforward-spec-v1.md)
- [指数行情 raw / serving 分层语义对齐改造方案 v1（已实施）](/Users/congming/github/goldenshare/docs/datasets/index-raw-serving-layer-alignment-plan-v1.md)
- [指数行情 active 池与周/月线派生机制说明（当前实现说明）](/Users/congming/github/goldenshare/docs/datasets/index-series-active-sync-mechanism.md)
- [指数基础信息源站对齐修复方案 v1（实施中，待真实验收）](/Users/congming/github/goldenshare/docs/datasets/index-basic-source-alignment-fix-plan-v1.md)
- [东方财富板块日线 category 字段与主键修复方案 v1（已确认）](/Users/congming/github/goldenshare/docs/datasets/dc-daily-category-identity-fix-plan-v1.md)
- [股票周/月线同步逻辑说明](/Users/congming/github/goldenshare/docs/datasets/equity-weekly-monthly-sync-logic.md)
- [资金流多源融合策略设计 v1](/Users/congming/github/goldenshare/docs/datasets/moneyflow-multi-source-fusion-strategy-v1.md)
- [同花顺板块日线估值字段扩表重建方案 v1（已确认）](/Users/congming/github/goldenshare/docs/datasets/ths-daily-valuation-fields-rebuild-plan-v1.md)

说明：资金流 6 数据集的拍板结论已并入各自正式开发文档（不再维护独立拍板清单）。

- [Tushare 数据集接入盘点（2026-05-03）](/Users/congming/github/goldenshare/docs/datasets/tushare-dataset-integration-audit-2026-05-03.md)

主要数据集开发说明：
- [A股业绩快报 `express` LLD v1（M1–M4b 已完成；M4c 自动任务已正确配置，待首次触发与对账验收）](/Users/congming/github/goldenshare/docs/datasets/equity-express-low-level-design-v1.md)
- [A股财务指标 `fina_indicator` 接入技术方案 v1（已完成生产验收，需求关闭）](/Users/congming/github/goldenshare/docs/datasets/fina-indicator-dataset-development.md)
- [A股财务指标 `fina_indicator` LLD v1（已完成生产验收，需求关闭）](/Users/congming/github/goldenshare/docs/datasets/fina-indicator-low-level-design-v1.md)
- [A股利润表 `income` 接入技术方案 v1（关键口径已确认，LLD 已完成，待开发）](/Users/congming/github/goldenshare/docs/datasets/income-dataset-development.md)
- [A股利润表 `income` 接入 LLD v1（设计完成，待开发）](/Users/congming/github/goldenshare/docs/datasets/income-low-level-design-v1.md)
- [A股资产负债表 `balancesheet` 接入技术方案 v1（关键口径已确认，LLD 已完成，待开发）](/Users/congming/github/goldenshare/docs/datasets/balancesheet-dataset-development.md)
- [A股资产负债表 `balancesheet` 接入 LLD v1（设计完成，待开发）](/Users/congming/github/goldenshare/docs/datasets/balancesheet-low-level-design-v1.md)
- [A股现金流量表 `cashflow` 接入技术方案 v1（关键口径已确认，LLD 已完成，待开发）](/Users/congming/github/goldenshare/docs/datasets/cashflow-dataset-development.md)
- [A股现金流量表 `cashflow` 接入 LLD v1（设计完成，待开发）](/Users/congming/github/goldenshare/docs/datasets/cashflow-low-level-design-v1.md)
- [公募基金九数据集接入总览与分批推进计划 v1（B0–B4 已生产验收；B7 fund_portfolio M0–M3 已生产验收，尚未历史回补或创建 schedule）](/Users/congming/github/goldenshare/docs/datasets/public-fund-nine-dataset-onboarding-program-plan-v1.md)
- [公募基金 B0：观察快照直出最小地基 LLD v1（已实现）](/Users/congming/github/goldenshare/docs/datasets/public-fund-b0-observed-snapshot-foundation-low-level-design-v1.md)
- [公募基金 B1：基金管理人与业绩基准库 LLD v1（已实现并完成生产验收）](/Users/congming/github/goldenshare/docs/datasets/public-fund-b1-static-reference-low-level-design-v1.md)
- [公募基金 B2：基金列表 LLD v1（M3 生产验收通过，尚未创建 schedule）](/Users/congming/github/goldenshare/docs/datasets/public-fund-b2-fund-basic-low-level-design-v1.md)
- [公募基金 B3：基金经理 LLD v1（M3 生产验收通过，尚未创建 schedule）](/Users/congming/github/goldenshare/docs/datasets/public-fund-b3-fund-manager-low-level-design-v1.md)
- [公募基金 B4：基金规模 LLD v1（B4-FS-M3 生产验收通过，尚未创建 schedule 或回补历史）](/Users/congming/github/goldenshare/docs/datasets/public-fund-b4-fund-share-low-level-design-v1.md)
- [公募基金 B4：基金分红 LLD v1（B4-FD-M3 生产验收通过，尚未创建 schedule 或回补历史）](/Users/congming/github/goldenshare/docs/datasets/public-fund-b4-fund-div-low-level-design-v1.md)
- [公募基金 B7：基金持仓 LLD v1（M3 生产验收通过，尚未历史回补或创建 schedule）](/Users/congming/github/goldenshare/docs/datasets/public-fund-b7-fund-portfolio-low-level-design-v1.md)
- 公募基金接入发现审计：[基金管理人](/Users/congming/github/goldenshare/docs/datasets/fund-company-onboarding-discovery-audit.md) 与 [基金业绩基准库](/Users/congming/github/goldenshare/docs/datasets/fund-performance-benchmark-onboarding-discovery-audit.md) 已完成 B1；[基金列表](/Users/congming/github/goldenshare/docs/datasets/fund-basic-onboarding-discovery-audit.md) 已完成 B2；[基金经理](/Users/congming/github/goldenshare/docs/datasets/fund-manager-onboarding-discovery-audit.md) 已完成 B3；[基金规模](/Users/congming/github/goldenshare/docs/datasets/fund-share-onboarding-discovery-audit.md) 与 [基金分红](/Users/congming/github/goldenshare/docs/datasets/fund-div-onboarding-discovery-audit.md) 均已完成 B4 M0–M3；[基金持仓](/Users/congming/github/goldenshare/docs/datasets/fund-portfolio-onboarding-discovery-audit.md) 已完成 B7-M0–M3，尚未历史回补或创建 schedule；[基金净值](/Users/congming/github/goldenshare/docs/datasets/fund-nav-onboarding-discovery-audit.md) 与 [基金技术面因子](/Users/congming/github/goldenshare/docs/datasets/fund-factor-pro-onboarding-discovery-audit.md) 尚未进入 LLD
- [BIYING 股票日线](/Users/congming/github/goldenshare/docs/datasets/biying-equity-daily-dataset-development.md)
- [BIYING 资金流向](/Users/congming/github/goldenshare/docs/datasets/biying-moneyflow-dataset-development.md)
- [ETF 基准指数列表](/Users/congming/github/goldenshare/docs/datasets/etf-index-dataset-development.md)
- [ETF 日线行情](/Users/congming/github/goldenshare/docs/datasets/etf-fund-daily-dataset-development.md)
- [ETF 申赎清单（已由 ETF Basic Serving 驱动）](/Users/congming/github/goldenshare/docs/datasets/etf-sh-cons-dataset-development.md)
- [ETF 申赎清单低层设计 LLD v1（Basic 资格与上市日裁剪为当前基线）](/Users/congming/github/goldenshare/docs/datasets/etf-sh-cons-low-level-design-v1.md)
- [ETF 份额规模接入方案（按交易日源端全集 / raw 直出 serving）](/Users/congming/github/goldenshare/docs/datasets/etf-share-size-dataset-development.md)
- [ETF 份额规模低层设计 LLD v1（不读取 Basic 或持久化对象池）](/Users/congming/github/goldenshare/docs/datasets/etf-share-size-low-level-design-v1.md)
- [ETF 每日持仓组合（深市）接入方案（已由 ETF Basic Serving 驱动）](/Users/congming/github/goldenshare/docs/datasets/etf-sz-cons-dataset-development.md)
- [ETF 每日持仓组合（深市）低层设计 LLD v1（Basic 资格与上市日裁剪为当前基线）](/Users/congming/github/goldenshare/docs/datasets/etf-sz-cons-low-level-design-v1.md)
- [基金复权因子](/Users/congming/github/goldenshare/docs/datasets/fund-adj-dataset-development.md)
- [融资融券交易汇总](/Users/congming/github/goldenshare/docs/datasets/margin-dataset-development.md)
- [融资融券交易明细低层设计 LLD v1（M0–M4 与 HDD 落盘已完成，待 M5a 手工历史回补 / M5b 自动增量授权）](/Users/congming/github/goldenshare/docs/datasets/margin-detail-low-level-design-v1.md)
- [每日涨跌停价格](/Users/congming/github/goldenshare/docs/datasets/stk-limit-dataset-development.md)
- [股票开盘集合竞价](/Users/congming/github/goldenshare/docs/datasets/stk-auction-o-dataset-development.md)
- [股票收盘集合竞价](/Users/congming/github/goldenshare/docs/datasets/stk-auction-c-dataset-development.md)
- [神奇九转指标](/Users/congming/github/goldenshare/docs/datasets/stk-nineturn-dataset-development.md)
- [神奇九转指标 Lake prod-raw-db 导出方案](/Users/congming/github/goldenshare/docs/datasets/stk-nineturn-prod-raw-db-lake-export-plan.md)
- [Dagster 神奇九转数据集接入方案](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stk-nineturn-dataset-onboarding-plan.md)
- [Dagster 神奇九转数据集接入 LLD](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stk-nineturn-dataset-onboarding-low-level-design.md)
- [股票历史分钟行情](/Users/congming/github/goldenshare/docs/datasets/stk-mins-dataset-development.md)
- [指数历史分钟行情](/Users/congming/github/goldenshare/docs/datasets/index-mins-dataset-development.md)
- [主要指数历史分钟线数据集开发说明（Lake/Dagster，开发完成，待独立运维验收）](/Users/congming/github/goldenshare/docs/datasets/major-index-mins-dataset-development.md)
- [指数四浪反弹失效与趋势反转量化回测方案 v1（独立专项案例，暂缓实施）](/Users/congming/github/goldenshare/docs/datasets/index-wave4-trend-reversal-backtest-plan-v1.md)
- [波浪浪型识别开源源码学习与 Goldenshare 适配审计 v1（通用波浪主线，G2 第一轮已执行）](/Users/congming/github/goldenshare/lake_console/docs/design/elliott-wave-source-study-and-goldenshare-adaptation-audit-v1.md)
- [通用波浪识别 G0 冻结合同 v1（D01～D10 已确认，G1 已验收，G2 第一轮已执行）](/Users/congming/github/goldenshare/lake_console/docs/design/index-wave-g0-generic-contract-v1.md)
- [通用波浪识别 G1 纯内核实现与验收记录 v1（F01～F44 已通过）](/Users/congming/github/goldenshare/lake_console/docs/design/index-wave-g1-core-implementation-and-acceptance-v1.md)
- [通用波浪识别 G2 真实数据只读验证与概率校准记录 v1（日线通过，120 分钟带缺口）](/Users/congming/github/goldenshare/lake_console/docs/design/index-wave-g2-readonly-real-data-validation-v1.md)
- [Dagster 股票分钟线连续性治理专项方案（HTML，M1-M8 已落地 / 后续 M9-M10 待收口）](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stk-mins-continuity-governance.html)
- [Dagster 股票分钟线连续性治理 LLD（HTML，M1-M8 已落地 / 后续 M9-M10 待收口）](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stk-mins-continuity-governance-low-level-design.html)
- [股票历史分钟行情存储瘦身与滚动冷热治理方案 v1（表结构已实施；P0 安全复审完成，备份门禁 No-Go，生产迁移待单独授权）](/Users/congming/github/goldenshare/docs/datasets/stk-mins-storage-slimming-plan-v1.md)
- [股票技术面因子（专业版）](/Users/congming/github/goldenshare/docs/datasets/stk-factor-pro-dataset-development.md)
- [股票技术面因子基于复权因子变化的历史重刷方案 v1（已落地）](/Users/congming/github/goldenshare/docs/datasets/stk-factor-pro-adj-factor-driven-refresh-plan-v1.md)
- [股票技术面因子 raw 直出与复权因子门禁方案 v1（已落地）](/Users/congming/github/goldenshare/docs/datasets/stk-factor-pro-raw-view-adj-factor-gate-plan-v1.md)
- [指数技术因子（专业版）](/Users/congming/github/goldenshare/docs/datasets/idx-factor-pro-dataset-development.md)
- [指数技术因子（专业版）低层设计 LLD v1](/Users/congming/github/goldenshare/docs/datasets/idx-factor-pro-low-level-design-v1.md)
- [每日停复牌信息](/Users/congming/github/goldenshare/docs/datasets/suspend-d-dataset-development.md)
- [ST 股票列表](/Users/congming/github/goldenshare/docs/datasets/stock-st-dataset-development.md)
- [ST 股票列表历史缺失日期重建方案 v1（待评审）](/Users/congming/github/goldenshare/docs/datasets/stock-st-missing-date-reconstruction-plan-v1.md)
- [个股资金流向（THS）](/Users/congming/github/goldenshare/docs/datasets/moneyflow-ths-dataset-development.md)
- [个股资金流向（DC）](/Users/congming/github/goldenshare/docs/datasets/moneyflow-dc-dataset-development.md)
- [概念板块资金流向（THS）](/Users/congming/github/goldenshare/docs/datasets/moneyflow-cnt-ths-dataset-development.md)
- [行业资金流向（THS）](/Users/congming/github/goldenshare/docs/datasets/moneyflow-ind-ths-dataset-development.md)
- [板块资金流向（DC）](/Users/congming/github/goldenshare/docs/datasets/moneyflow-ind-dc-dataset-development.md)
- [大盘资金流向（DC）](/Users/congming/github/goldenshare/docs/datasets/moneyflow-mkt-dc-dataset-development.md)
- [新闻快讯](/Users/congming/github/goldenshare/docs/datasets/news-dataset-development.md)
- [新闻联播文字稿](/Users/congming/github/goldenshare/docs/datasets/cctv-news-dataset-development.md)
- [新闻通讯](/Users/congming/github/goldenshare/docs/datasets/major-news-dataset-development.md)
- [上市公司公告](/Users/congming/github/goldenshare/docs/datasets/anns-d-dataset-development.md)
- [上证E互动问答](/Users/congming/github/goldenshare/docs/datasets/irm-qa-sh-dataset-development.md)
- [深证互动易问答](/Users/congming/github/goldenshare/docs/datasets/irm-qa-sz-dataset-development.md)
- [券商研究报告](/Users/congming/github/goldenshare/docs/datasets/research-report-dataset-development.md)
- [券商每月荐股](/Users/congming/github/goldenshare/docs/datasets/broker-recommend-dataset-development.md)
- [每日筹码及胜率](/Users/congming/github/goldenshare/docs/datasets/cyq-perf-dataset-development.md)
- [每日筹码分布](/Users/congming/github/goldenshare/docs/datasets/cyq-chips-dataset-development.md)
- [股票历史基础列表](/Users/congming/github/goldenshare/docs/datasets/bak-basic-dataset-development.md)
- [北交所新旧代码对照](/Users/congming/github/goldenshare/docs/datasets/bse-mapping-dataset-development.md)
- [股票曾用名](/Users/congming/github/goldenshare/docs/datasets/namechange-dataset-development.md)
- [ST 风险警示事件](/Users/congming/github/goldenshare/docs/datasets/st-dataset-development.md)
- [ST 风险警示事件源字段契约收口专项 LLD v1](/Users/congming/github/goldenshare/docs/datasets/st-source-field-contract-repair-lld-v1.md)
- [上市公司基本信息](/Users/congming/github/goldenshare/docs/datasets/stock-company-dataset-development.md)

## 6. 前端、业务与发布（S4）

- [财势天下登录页视觉改版与鉴权接入技术方案 v1（开发完成，待用户部署验收）](/Users/congming/github/goldenshare/wealth/docs/pages/login/login-page-auth-design-v1.md)
- [财势天下登录页视觉改版低层设计 v1（修订 v1.2，含登录校验脱敏与开发对账）](/Users/congming/github/goldenshare/wealth/docs/pages/login/login-page-auth-low-level-design-v1.md)
- [前端技术与组件体系选型建议](/Users/congming/github/goldenshare/docs/frontend/frontend-technology-and-component-selection.md)
- [前端当前强约束（统一基线）](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md)
- [前端交付流程规范 v1](/Users/congming/github/goldenshare/docs/frontend/frontend-delivery-workflow-v1.md)
- [前端设计 Tokens 与组件目录 v2](/Users/congming/github/goldenshare/docs/frontend/frontend-design-tokens-and-component-catalog-v1.md)
- [前端组件 Showcase v1（HTML 对照）](/Users/congming/github/goldenshare/docs/frontend/frontend-component-showcase-v1.html)
- [前端数据集审计页面设计 v1](/Users/congming/github/goldenshare/docs/frontend/frontend-date-completeness-audit-page-design-v1.md)
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
- [前端 Ops 事实字段消费审计 v1](/Users/congming/github/goldenshare/docs/frontend/frontend-ops-fact-consumer-audit-v1.md)
- [前端质量门禁矩阵 v1](/Users/congming/github/goldenshare/docs/frontend/frontend-quality-gate-matrix-v1.md)
- [前端回归与截图基线流程 v1](/Users/congming/github/goldenshare/docs/frontend/frontend-regression-and-baseline-workflow-v1.md)
- [前端 Smoke 与视觉回归门禁 v1](/Users/congming/github/goldenshare/docs/frontend/frontend-smoke-visual-gate-v1.md)
- [行情主系统接口规范](/Users/congming/github/goldenshare/docs/platform/quote-detail-api-spec-v1.md)
- [远程服务器部署总览 v1（HTML）](/Users/congming/github/goldenshare/docs/release/remote-server-deployment-overview-v1.html)
- [发版流程 v1](/Users/congming/github/goldenshare/docs/release/release-process-v1.md)

## 7. 数据源接口说明

- [数据源接口说明目录规范](/Users/congming/github/goldenshare/docs/sources/README.md)
- [Tushare 接口说明目录](/Users/congming/github/goldenshare/docs/sources/tushare/README.md)
- [Tushare 接口总索引（CSV）](/Users/congming/github/goldenshare/docs/sources/tushare/docs_index.csv)
- [BIYING 接口说明目录](/Users/congming/github/goldenshare/docs/sources/biying/README.md)

## 8. 文档治理

- [生产 PostgreSQL 存储空间优化治理专项 v1（既有专项与 stk_mins 原专项记录；本轮新工作不再追加）](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-storage-space-optimization-program-v1.md)
- [生产 PostgreSQL 存储空间优化治理专项 v2（P1-B0、P1-B1、P1-B2 与 `stk_auction_o` 已结案；`stk_auction_c-M0/M1/M2` 已通过，下一阶段生产 M3a；`anns_d` 批内身份冲突另列只读审计 TODO）](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-storage-space-optimization-program-v2.md)
- [生产 PostgreSQL raw 直出一期低层设计 v1（P1-B0、P1-B1、P1-B2 与 `stk_auction_o` 的生产切换及自然 M3b 已验收结案）](/Users/congming/github/goldenshare/docs/governance/prod-postgresql-raw-direct-serving-phase-one-lld-v1.md)
- [文档信息架构与待整合清单 v1](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md)
- [文档维护基线 v1](/Users/congming/github/goldenshare/docs/governance/docs-maintenance-baseline-v1.md)
- [工程风险登记簿](/Users/congming/github/goldenshare/docs/governance/engineering-risk-register.md)
- [基础数据工作流与数据集三线推进索引 v1（已完成）](/Users/congming/github/goldenshare/docs/governance/reference-data-workstreams-rollout-index-v1.md)
- [`cadence` 退场清单 v1](/Users/congming/github/goldenshare/docs/governance/cadence-deprecation-checklist-v1.md)

## 9. 产品原始材料

- [东财行业财务统计分析报表方案 v2（待评审）](/Users/congming/github/goldenshare/docs/product/dc-industry-financial-analysis-report-plan-v2.md)
- [申万行业财务景气分析报表方案 v1（正式版已生成）](/Users/congming/github/goldenshare/docs/product/sw2021-industry-financial-analysis-report-plan-v1.md)
- [申万行业周期拐点雷达方案 v1（方法原型已生成）](/Users/congming/github/goldenshare/docs/product/sw2021-industry-turning-point-radar-plan-v1.md)
- [行情图表页接口需求说明](/Users/congming/github/goldenshare/docs/product/行情图表页接口需求说明_基于当前数据基座.md)
- [财势乾坤交易系统需求说明（PDF）](/Users/congming/github/goldenshare/docs/product/财势乾坤交易系统需求说明.pdf)
