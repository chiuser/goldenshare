# 文档维护基线 v1

更新时间：2026-04-20

## 1. 目标

本文件用于定义 `docs/` 的日常维护基线，确保：

1. 文档结构长期稳定；
2. 新增文档可追溯；
3. 链接与索引不失真；
4. 不再回到“散乱堆叠”状态。

---

## 2. 适用范围

适用于：

1. `docs/**`
2. `docs/sources/**`
3. `docs/governance/**`

不适用于代码实现逻辑和数据库变更。

---

## 3. 文档分层基线

1. `architecture/`：系统级基线与边界规则。
2. `ops/`：运维对象、流程与专题。
3. `datasets/`：数据集开发文档与跨数据集策略。
4. `frontend/`：前端治理与交付规范。
5. `platform/`：对上业务接口规范。
6. `sources/`：源站接口事实说明（不含工程实现决策）。
7. `governance/`：文档治理与整合记录。

---

## 4. 提交前必跑检查

统一执行：

```bash
python3 scripts/check_docs_integrity.py
```

当前脚本会检查：

1. `docs/*.md` 绝对路径链接死链；
2. `docs/**/.DS_Store` 噪音文件；
3. `docs/sources/tushare/docs_index.csv` 的 `local_path` 一致性。

---

## 5. Sources 维护规则

1. 先更新 `docs/sources/*`，再更新 `docs/datasets/*`。
2. `tushare` 新增/改名文档必须同步 `docs_index.csv`。
3. `sources` 目录只记录源站事实，不写本仓工程决策。

---

## 6. 索引与治理同步规则

当发生以下动作时，必须同步更新 [docs/README.md](/Users/congming/github/goldenshare/docs/README.md)：

1. 新增目录；
2. 新增主文档；
3. 删除或并入旧文档。

当发生以下动作时，必须同步更新 [docs-information-architecture-v1.md](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md)：

1. 新增一组治理策略；
2. 完成一轮整合并下线旧文档；
3. 变更文档分层规则。

---

## 7. 禁止事项

1. 禁止把临时讨论文档长期留在主索引。
2. 禁止在 `sources/` 中混入落库设计和业务策略。
3. 禁止删除文档后不更新索引。
4. 禁止提交未校验链接和索引的一次性大改。

---

## 8. 建议执行节奏

1. 每轮只处理一个文档组（architecture / ops / datasets / frontend / sources）。
2. 每轮结束必须给出“本轮清单 + 下一轮建议”。
3. 若发现跨组依赖不清，先补治理文档再动大改。
