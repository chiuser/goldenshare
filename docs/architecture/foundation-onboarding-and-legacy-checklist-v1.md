# Foundation 开发上手指南与历史遗留清单 v1

> 目标：让新同学在不了解历史上下文的情况下，也能准确理解工程现状、开发边界和正确流程，避免重复踩坑。
>
> 角色说明：本文件是“入门与遗留清单专题文档”，用于 onboarding 与排坑。  
> 当前统一强约束请以 [foundation-current-standards.md](/Users/congming/github/goldenshare/docs/architecture/foundation-current-standards.md) 为准。

---

## 1. 这套工程在做什么

当前仓库的主子系统分工如下：

1. Foundation（数据基座）
- 负责多源采集、原始落库、标准化、融合发布、对外数据供给。

2. Ops（数据运营管理）
- 负责任务执行、状态观测、手动/自动维护、规则管理、发布审计。

3. App / Biz（运行入口与业务接口）
- `app` 负责运行壳与聚合入口；
- `biz` 面向业务消费方提供稳定查询接口。

补充：`platform` 目录当前定位为 legacy/compat 层，不再承接新主实现。

核心原则：**业务层不直接读 raw/std；以 serving 为唯一对外口径。**

---

## 2. 当前运行模式（入口说明）

运行模式、层级语义与状态定义已统一收口到：

- [Foundation 当前强约束（统一基线）](/Users/congming/github/goldenshare/docs/architecture/foundation-current-standards.md)
- [Ops 当前契约（统一版）](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md)

本文件不再重复维护同一套定义，避免口径漂移。

---

## 3. 新人第一天上手顺序

1. 先读文档
- [子系统边界基线](/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md)
- [数据集发布治理规范](/Users/congming/github/goldenshare/docs/architecture/dataset-publish-governance-spec-v1.md)
- [DatasetDefinition 单一事实源重构方案](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md)
- [DatasetExecutionPlan 执行计划模型重构方案](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)
- [数据集总目录（历史自动生成快照）](/Users/congming/github/goldenshare/docs/datasets/dataset-catalog.md)

2. 本地最小验证
- `goldenshare init-db`
- `goldenshare ops-seed-default-single-source --source-key tushare --apply`
- `goldenshare ops-seed-dataset-pipeline-mode --apply`
- `goldenshare ops-rebuild-dataset-status`

3. 页面与接口核对
- `GET /api/v1/ops/pipeline-modes`
- `GET /api/v1/ops/layer-snapshots/latest`
- `GET /api/v1/ops/freshness`

4. 代码提交前必做
- 跑对应测试集（单测 + web 接口测试）。
- 确认文档同步更新（README 索引、数据集文档、模板或规范）。

---

## 4. 新增数据集标准流程（入口说明）

新增数据集请直接按以下文档执行，不在本文件重复维护流程细节：

1. [Foundation 当前强约束（统一基线）](/Users/congming/github/goldenshare/docs/architecture/foundation-current-standards.md)
2. [数据集发布治理规范](/Users/congming/github/goldenshare/docs/architecture/dataset-publish-governance-spec-v1.md)
3. [数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)

---

## 5. 防踩坑红线（必须遵守）

1. 禁止前端硬编码分类口径
- 分类展示统一使用后端 `domain_display_name`。

2. 禁止把 `latest` 查询接到 history 表
- `latest` 语义必须读 `ops.dataset_layer_snapshot_current`。

3. 禁止用 `unknown` 代替“未启用/未观测”
- 该启用时必须是 `unobserved` 或真实状态。
- 未启用必须是 `skipped`。

4. 禁止“缺文档先开发”
- 无字段定义、无规则定义、无测试清单，不允许编码。

5. 禁止引入新的 `core.*` 直写路径（除明确保留项）
- 新能力默认走 `core_serving.*`。

---

## 6. 历史遗留清单（持续收口）

### A. 口径与表层收口

- [ ] 指标与因子保留项迁移策略明确并落地：
  - `equity_indicators`（`ind_macd/ind_kdj/ind_rsi`）已下线，统一改读 `stk_factor_pro`
  - `adj_factor`（`equity_adj_factor`）
  - `fund_adj`（`fund_adj_factor`）
- [ ] 历史 `core.*` 兼容路径最终下线计划（按白名单逐个收口）。

### B. 观测与状态语义收口

- [ ] 所有启用层都具备独立观测来源，逐步减少 `unobserved`。
- [ ] `unknown` 长期清零（只允许短时异常窗口出现）。
- [ ] 无业务日期字段的数据集统一采用“最近同步日期兜底业务日期”。

### C. pipeline mode 与规则对象收口

- [ ] 所有数据集具备落库的 `dataset_pipeline_mode`（避免长期推断态）。
- [ ] 单源直出数据集保证 `source_status + resolution_policy + std 规则`对象完整（即使是 pass-through）。
- [ ] 新增数据集默认自动纳入 seed 和状态重建流程。

### D. 页面与契约收口（V2.1）

- [ ] 数据状态总览、数据源页、详情页统一使用新契约对象。
- [ ] 旧页面仅做兼容，不再承载新需求。
- [ ] Source 页只看 raw；总览页看链路与模式；详情页看全链路与执行。

---

## 7. PR 自检清单（提交前复制到描述）

- [ ] 本次变更是否新增/修改了数据集或规则对象？
- [ ] 是否更新了相应 docs（含 README 索引）？
- [ ] 是否验证了 `pipeline-modes / layer-snapshots/latest / freshness` 三接口？
- [ ] 是否确保未引入新的旧口径依赖（尤其 `core.*` 直写）？
- [ ] 是否补了必要测试并通过？

---

本文件是 Foundation/Ops 协同开发的入口文档。  
后续新增规则、改口径、改流程，先更新本文件再落代码。
