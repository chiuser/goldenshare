# 数据源接口说明目录规范

## 1. 目的

`docs/sources/` 用于沉淀“数据源侧接口说明”的本地摘要，作为数据集开发前的输入材料。

它解决两个问题：

1. 源站文档可能变更或不可访问，需要本地可追溯记录。
2. 接口说明与具体数据集方案要分层，避免把开发决策写进源说明。

---

## 2. 放什么、不放什么

放：

1. 源站接口字段说明摘要
2. 限速、分页、时间参数、错误返回等原生约束
3. 抓取日期与源链接

不放：

1. 本仓库的落库设计
2. Ops 交互策略
3. 业务字段映射决策（这些写在 `docs/datasets/*`）

---

## 3. 建议结构

```text
docs/sources/
  tushare/
    docs_index.csv
    股票数据/
    指数专题/
    ETF专题/
  biying/
    README.md
    <source-docs>.md
```

命名约定（按源分治）：

1. `tushare`：以 `docs_index.csv + 分类目录 + <doc_id>_<标题>.md` 为准；
2. 其他源：按“接口语义 + 来源路径”命名（如 `hsstock-history.md`）。

说明：

1. 各数据源可有自己的 README 与命名细则；
2. 总目录只约束“结构层级与职责边界”，不强制单一文件命名风格。

---

## 4. 与数据集文档关系

每个 `docs/datasets/*-dataset-development.md` 应在“接口来源”章节引用对应 `docs/sources/*` 文件（如果已沉淀）。

顺序：

1. 先补 `sources` 接口说明（可简版）。
2. 再写 `datasets` 开发方案。

提交前建议执行：

```bash
python3 scripts/check_docs_integrity.py
```
