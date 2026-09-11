# 文档维护基线 v1

更新时间：2026-09-11（承接治理账本的通用维护规则）

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

`release/` 保存发布流程，`product/` 保存产品材料与研究方案，`templates/` 保存开发填写模板。数据集主说明聚焦自身合同，跨数据集策略独立成专题；同主题明确主文档与补充关系，不复制通用规则。方案与当前实现不同应标出目标/差距，不能因未实施就删除仍有效的决策。

---

## 4. 提交前必跑检查

统一执行：

```bash
python3 scripts/check_docs_integrity.py
```

当前脚本包含以下四项主要检查内容，执行结果合并为三个检查组：

1. `docs/**` 中 Markdown 文件的仓库绝对路径链接死链；
2. `docs/**/.DS_Store` 噪音文件；
3. `docs/sources/tushare/docs_index.csv` 的 `local_path` 一致性；
4. 同一索引的 `doc_id` 与 Markdown 文件名四位数字前缀一致性。

第 3、4 项同属 `tushare-index-consistency` 检查组，因此输出三个 PASS 不代表漏跑第四项。
具体覆盖范围以 `scripts/check_docs_integrity.py` 为准；这些检查不证明文档内容与代码语义一致，也不覆盖全部 AGENTS 中的裸路径、相对链接或锚点。

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

删除前核实代码/流程依赖与全部入链；先将独有合同、决策和验收证据迁入承接文档，再同步索引，不保留重复空壳。治理账本记录去向和验证，不复制主文档规则；工程 P0/P1 风险回到[风险登记簿](/Users/congming/github/goldenshare/docs/governance/engineering-risk-register.md)，不只留在审计对话中。

---

## 6.1 历史文档标注规则（新增）

当文档不再作为“当前运行口径”而转为历史记录时，必须同时完成：

1. 在文首增加“历史/归档”说明；
2. 将状态从“执行中”改为“已归档/历史执行清单”等现实状态；
3. 在 `docs/README.md` 对应条目补充“历史/归档”标签，避免误导。

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
