# 文档信息架构与待整合清单 v1

更新时间：2026-04-26

## 1. 目标

本文件用于把 `docs/` 从“历史堆叠”整理为“可持续维护”的结构。

原则：

1. 先有单一事实，再有专题补充。
2. 文档按职责分层，不按个人记忆归档。
3. 删除前先确认是否还有现实价值；保留必须有明确定位。

---

## 2. 当前目录结构（目标态）

```text
docs/
  README.md
  architecture/   # 架构基线、边界、分层方案
  ops/            # 运维契约、执行与观测专题
  datasets/       # 数据集开发文档与策略说明
  frontend/       # 前端治理、流程、视觉与执行
  platform/       # 对上业务 API 规范
  release/        # 发布流程
  product/        # 产品原始材料
  templates/      # 开发模板
  sources/        # 数据源接口说明（源站文档摘要）
  governance/     # 文档治理与整合记录
```

---

## 3. 分类规则（必须遵守）

1. `architecture/`
- 只放“系统级”规则与基线。
- 一旦收敛完成，文档应写“现状”而不是“迁移流水账”。

2. `ops/`
- 只放运维平台对象、页面契约、执行流程、专项方案。
- 与代码状态冲突的旧方案必须下线，不保留并行版本。

3. `datasets/`
- 一个数据集一份开发文档。
- 跨数据集策略另建专题文档（如 `moneyflow-*`）。

4. `sources/`
- 存放“数据源接口说明”的本地摘要与落地约束。
- 不替代 `datasets/*` 的开发方案文档。

5. `frontend/`
- 面向前端治理与交付流程。
- 同一主题多文档并存时，应提供主文档并标注专题关系。

---

## 4. 待整合清单（下一轮）

### 4.1 Architecture 组

当前状态：已完成第一轮整合（建立统一强约束主文档）。

主文档：

1. `foundation-current-standards.md`

专题文档：

1. `dataset-publish-governance-spec-v1.md`
2. `foundation-onboarding-and-legacy-checklist-v1.md`

整合建议：

1. `foundation-current-standards.md` 继续保持“唯一强约束源”定位。
2. 专题文档仅保留领域细节，避免再复制主约束。
3. 后续若发现专题与主文档冲突，先修正文档再改代码。

### 4.2 Ops 组

1. `ops-contract-current.md`（主文档）
2. `ops-workflow-catalog-v1.md`
3. `reconcile-capability-requirements-v1.md`

整合建议：

1. 以 `ops-contract-current.md` 为单一契约入口。
2. 停用策略与融合策略中心准备度已并入主契约，不再保留独立文档。
3. `ops-workflow-catalog-v1.md` 与 `reconcile-capability-requirements-v1.md` 保持专题定位，不重复定义主契约。

### 4.3 Datasets 组

当前状态：已完成第一轮整合（拍板结论回填并下线总览拍板单）。

1. `moneyflow-ths/moneyflow-dc/moneyflow-cnt-ths/moneyflow-ind-ths/moneyflow-ind-dc/moneyflow-mkt-dc` 六份开发文档

整合建议：

1. 后续只维护六份正式开发文档，不再保留独立拍板汇总单。
2. 同类“临时拍板文档”采用同样策略：拍板完成后回填正式文档并下线临时文档。

附加项：

1. 当前数据集事实源应收敛到 `src/foundation/datasets/**` 的 `DatasetDefinition` 投影。
2. 后续若重建数据集目录，应从 DatasetDefinition 生成。

### 4.4 Frontend 组

当前状态：已完成第一轮整合（建立统一强约束主文档）。

主文档：

1. `frontend-current-standards.md`

专题文档：

1. `frontend-delivery-workflow-v1.md`
2. `frontend-design-tokens-and-component-catalog-v1.md`
3. `frontend-governance-rollout-plan-v1.md`
4. `frontend-phase2-execution-brief-v1.md`

整合建议：

1. `frontend-current-standards.md` 作为唯一强约束源。
2. 治理/流程/token/阶段执行保留专题定位，不复制主约束。

### 4.5 Sources 组

当前状态：已完成第一轮结构化（按源分治 + Tushare 索引化）。

主文档：

1. `docs/sources/README.md`
2. `docs/sources/tushare/README.md`
3. `docs/sources/biying/README.md`

数据索引：

1. `docs/sources/tushare/docs_index.csv`

整合建议：

1. `sources/*` 仅记录源站事实，不承载工程实现决策。
2. Tushare 文档新增/改名必须同步更新 `docs_index.csv`。
3. 数据集开发文档通过 `doc_id + local_path` 引用 source 文档，避免“口口相传”。

---

## 5. 执行规则

1. 每轮只整合一个文档组（Architecture/Ops/Datasets/Frontend），避免扩散。
2. 整合动作必须同步更新 `docs/README.md`。
3. 删除文档前，先确认无代码路径与流程说明依赖。
4. 文档链接必须可达，禁止保留死链。
5. P0/P1 工程风险统一登记到 [工程风险登记簿](/Users/congming/github/goldenshare/docs/governance/engineering-risk-register.md)，避免风险只停留在口头讨论或单次事故复盘里。

文档维护日常基线见：

- [文档维护基线 v1](/Users/congming/github/goldenshare/docs/governance/docs-maintenance-baseline-v1.md)

---

## 6. 第二轮收尾检查（已完成）

1. `docs/*.md` 绝对路径链接检查：无死链。
2. `docs/sources/tushare/docs_index.csv` 与本地 `local_path` 一致性检查：无缺失文件。
3. 噪音文件清理：已移除 `docs/**/.DS_Store`。

后续新增源文档时，建议继续执行以上三项检查再提交。

推荐命令：

```bash
python3 scripts/check_docs_integrity.py
```
