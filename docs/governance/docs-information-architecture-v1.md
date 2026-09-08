# 文档信息架构与待整合清单 v1

更新时间：2026-09-08（Architecture 基线合并）

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

当前状态：2026-09-08 按用户确认将本组 7 份文档合并为 3 份。只整合文档，不改代码、依赖规则、数据库或 Lake；未全面审计其他架构方案。

1. [子系统架构基线](/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md)：目录、职责、依赖矩阵、现存差距、legacy 边界与护栏。
2. [Foundation 研发基线](/Users/congming/github/goldenshare/docs/architecture/foundation-current-standards.md)：Prod 数据分层、研发原则与上手入口。
3. [多源映射与发布规则](/Users/congming/github/goldenshare/docs/architecture/dataset-publish-governance-spec-v1.md)：只补充多源语义，不重建通用接入门禁。

数据集模板继续独立维护设计与验收填写要求；Ops 契约继续维护状态和展示语义。后续修改规则应回到其归属文档，不再同时更新多个相同清单。

<a id="architecture-consolidation-20260908"></a>

#### 本轮合并去向与删除清单

以下旧文件名仅用于追溯，不是当前入口。删除文件均可从合并前提交 `50b00161` 恢复，不另建空壳跳转文档。

| 原文档（均在 docs/architecture） | 处理 | 有效内容去向 |
| --- | --- | --- |
| `subsystem-boundary-plan.md` | 保留路径，改为子系统架构基线 | 目录与职责 §2、统一依赖 §3、差距 §4、迁移结论 §5、护栏 §6 |
| `dependency-matrix.md` | 并入后删除 | 目标矩阵、零白名单的适用边界、App 现存反向依赖与测试清单，归入架构基线 §3/4/6 |
| `platform-split-plan.md` | 并入后删除 | App 壳/认证/模型/API/Web/静态资源归属、旧试点退出及防回流结论，归入 §5/6 |
| `ops-consolidation-plan.md` | 并入后删除 | Ops runtime/services/action catalog、数据维护主链、市场情绪服务归属与 facade 边界，归入 §5/6 |
| `foundation-current-standards.md` | 保留路径，精简为研发基线 | 分层、事实源、长任务与分阶段验证保留；详细交付清单引用数据集模板 |
| `foundation-onboarding-and-legacy-checklist-v1.md` | 有效入口并入后删除 | 阅读入口与执行授权边界归入研发基线 §2/7；旧遗留事项分类见下表 |
| `dataset-publish-governance-spec-v1.md` | 保留路径，收窄为多源专题 | 映射、可比性、清洗、来源身份、发布优先级/回退/版本追溯、变更与测试要求 |

#### 未原样搬入的旧内容

| 旧内容 | 处理理由与当前去向 |
| --- | --- |
| Platform/Operations 空包删除与外部兼容评估待办 | 当前目录与护栏已证明无 Python 空包，不再列待办；不声称审计了仓库外脚本，仍保留 legacy 禁令 |
| 新人连跑 init-db、seed/apply、状态重建 | 不作为最小静态验证或默认执行授权；研发基线 §2/7 区分读文档、测试和获准写入，本轮未执行这些命令 |
| 前端分类硬编码、unknown/skipped/unobserved 与各层独立观测要求 | 状态与展示交回 Ops 当前契约，字段及消费者验收交回数据集模板 §7；不把旧枚举及分层规则另存为第二套现行定义 |
| 无业务日期时用最近同步日期兜底业务日期 | 与当前模板 §7.4 区分同步迹象的要求冲突，删除旧要求；研发基线 §4 保留明确区分 |
| 单源也须建立 source_status/resolution_policy/std 规则对象 | 不再要求为单源或 pass-through 补造对象/层；按实际 DatasetDefinition.storage 与模板设计，多源特殊规则由专题承载 |
| Source 页只看 Raw、旧页面兼容、新增数据集自动 seed | 不作为全局规则；实际来源/目标表与状态投影按模板 §7 验收，正式执行须另获授权 |
| equity_indicators、adj_factor、fund_adj 及 core 兼容路径旧迁移清单 | 移出新人必做任务；本轮不判定它们全部完成，也不据此下线任何表、字段或消费者。既有 core 保留边界继续由研发基线约束；再处理时须以对应数据集方案及当前实现确认，历史条目可从上述提交追溯 |
| 全部数据集必须经过 Raw/Std/Serving、所有发布均套多源流程 | 与已确认的 direct-serving、Raw 写入/Serving 视图等路径冲突；多源专题按实际获准路径设计，不强制物理 Std 层 |
| 多份通用门禁/PR 清单与 Stock Basic“当前口径”示例 | 通用填写归数据集模板；示例只解释规则写法，不把未经本轮核验的具体数据集生产策略写成事实 |

核验依据：先使用 CodeGraph `codegraph_explore` 查护栏上下文（返回混入无关符号，未据此扩范围），再定向读取三个架构护栏、Ops/Biz 入口的 App 导入及 legacy 目录；导航扫描覆盖 AGENTS、Markdown、HTML 与直接引用方。保留“目标约束/代码现状/测试覆盖”的区分，不以整合文档替代代码整改或生产验收。

本轮验证：文档完整性三个检查组与 `git diff --check` 通过；新增/修改的 40 个本地 Markdown/HTML 链接及锚点通过定向检查；三个架构护栏共 16 项测试通过。旧文件名仅留在上述迁移记录，不再作为当前链接或必读入口。未执行数据库、Lake、部署或安装操作，工作区其他任务修改保留。

### 4.1.1 当前权威入口与专题角色（G1）

Architecture 组按以下顺序判断文档是否具备当前权威性：

1. 当前运行时行为、API 契约和数据字段：以代码、测试、配置与实际运行事实为准。
2. 系统边界与依赖方向：统一以 `subsystem-boundary-plan.md` 为准，目标、现存差距与护栏覆盖分别阅读。
3. 数据集静态事实：以 `src/foundation/datasets/**` 的 `DatasetDefinition` 为准；执行计划以 `src/foundation/ingestion/**` 的 `DatasetExecutionPlan` 为准。
4. `dataset-definition-enum-reference-v1.md` 只维护枚举语义和约束边界，不维护易漂移的数量快照；精确数量由代码 registry 与测试提供。
5. 方案、LLD 与验收记录保留各自角色：方案/LLD 解释设计与局部实现，验收记录提供时点证据，均不能覆盖当前代码事实。
6. 清退专项 M5 的 86 份纯旧 Local Lake 文档与 3 份旧模板退出当前工作树，不建立 archive/tombstone。必要历史结果归入 [单一初始化与修复总账](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-bootstrap-legacy-links.md)，全文通过 Git 历史追溯；当前正式设计与混合文档只局部纠偏，不连带删除。

`docs/README.md` 负责导航和阅读顺序，不重复承载上述事实。

本轮 Architecture 入口治理结论：

1. S0 保留仓库上手总览、QTF 方案、子系统架构基线与 Foundation 研发基线；S1 不再重复列出这些入口，合并后的专题仅保留多源映射与发布规则。
2. `Dataset Maintain M-1 到 M8` 仅保留为历史执行索引，不再作为 Architecture 主入口；当前实施状态回到关联主案、代码和测试。
3. 方案与 LLD 成对保留时，必须分别承担上位方案与落地细节；独立验收记录、审计记录和旧 Local Lake 证据不提升为当前主入口。
4. `top_list` 版本收口方案已实施，后续未决范围仅限数值冲突业务规则，不再使用无状态标签的“专项方案”表述。

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
