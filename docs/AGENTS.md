# AGENTS.md — `docs/` 文档治理规则

## 适用范围

本文件适用于 `docs/` 目录及其子目录。  
若子目录存在更近的 `AGENTS.md`，以更近规则为准。

---

## 1. 当前 docs 目录现状（唯一口径）

当前文档结构按职责分层：

1. `architecture/`：架构基线、边界、收敛计划
2. `ops/`：运维契约、执行与观测专题
3. `datasets/`：数据集研发文档与策略说明
4. `frontend/`：前端治理、流程、设计规范
5. `platform/`：对上业务 API 规范
6. `release/`：发布流程
7. `product/`：产品原始材料
8. `templates/`：研发模板
9. `sources/`：数据源接口说明（源站事实）
10. `governance/`：文档治理与整合记录

主索引入口：

- [docs/README.md](/Users/congming/github/goldenshare/docs/README.md)

维护基线入口：

- [docs/governance/docs-maintenance-baseline-v1.md](/Users/congming/github/goldenshare/docs/governance/docs-maintenance-baseline-v1.md)

---

## 2. 新增文档规范（必须遵守）

### 2.1 先判定归属目录

新增前先回答：该文档属于哪一层职责。

1. 系统级规则/边界 -> `architecture/`
2. 运维对象/流程 -> `ops/`
3. 数据集实现方案 -> `datasets/`
4. 前端规范/流程 -> `frontend/`
5. 外部数据源接口事实 -> `sources/`
6. 文档治理流程 -> `governance/`

禁止“先随便放一个目录，后续再整理”。

### 2.2 新增 sources 文档的额外规则

1. 先写源站事实（输入/输出/限速/分页/更新时间），不写工程实现决策。
2. `tushare` 相关新增/改名必须同步更新：
   - `docs/sources/tushare/docs_index.csv`
3. 数据集开发文档需引用对应 source 文档（`doc_id + local_path`）。

### 2.3 索引同步规则

新增主文档后，必须同步更新：

1. `docs/README.md`
2. 若涉及治理规则变化，再同步更新 `docs/governance/*`

---

## 3. 维护文档规范（改/删/并）

### 3.1 修改文档

1. 避免重复定义“统一规则”；优先引用主基线文档。
2. 若与现状冲突，先修文档再改代码，或同步修正两边。
3. 专题文档只保留专题细节，不复制总规则。
4. 历史阶段文档（方案/执行记录）必须在文首明确标注“历史/归档”，禁止以“当前执行口径”表达旧链路。
5. 文档状态字段（如“执行中/已完成”）必须与代码现实一致；不确定时使用“历史归档”或“待评审”中性状态，禁止继续写“执行中”。

### 3.2 删除或并入文档

1. 删除前先确认无索引引用、无流程依赖。
2. 并入后要在原主索引和治理文档中明确“已并入去向”。
3. 删除动作必须伴随索引更新，禁止留下悬挂链接。

---

## 4. 提交前检查（强制）

统一执行：

```bash
python3 scripts/check_docs_integrity.py
```

当前脚本检查：

1. `docs/*.md` 绝对路径死链
2. `docs/**/.DS_Store` 噪音文件
3. `docs/sources/tushare/docs_index.csv` 与 `local_path` 一致性

任何一项失败，不允许提交 docs 改动。

---

## 5. 禁止事项

1. 禁止在 `sources/` 写本仓工程决策。
2. 禁止把临时讨论稿长期挂在主索引。
3. 禁止删除文档后不更新索引。
4. 禁止跳过文档校验脚本直接提交。
5. 禁止一次提交跨多个文档组且无清晰目标。

---

## 6. 建议工作流（每轮）

1. 先明确本轮只处理一个文档组（architecture/ops/datasets/frontend/sources）。
2. 执行最小改动，不顺手扩散。
3. 跑 `python3 scripts/check_docs_integrity.py`。
4. 更新 `docs/README.md`（如有新增/删除/并入）。
5. 在提交说明里写清：目标、改动文件、校验结果、下一步建议。
