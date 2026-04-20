# Tushare 接口说明目录（本地镜像）

## 1. 目录定位

`docs/sources/tushare/` 只沉淀 **Tushare 源站接口说明**，用于：

1. 给 `docs/datasets/*` 提供可追溯的接口输入材料；
2. 避免源站文档变更后无法回看历史定义。

本目录不放落库设计、融合策略、Ops 交互流程。

---

## 2. 当前结构（与仓库现状一致）

```text
docs/sources/tushare/
  docs_index.csv
  ETF专题/
  指数专题/
  股票数据/
    基础数据/
    行情数据/
    资金流向数据/
    财务数据/
    参考数据/
    打板专题数据/
    特色数据/
```

说明：

1. `docs_index.csv` 是总索引（doc_id、api_name、source_url、本地路径）。
2. Markdown 文件按“主题目录 + 文档编号”组织，便于人工浏览和批量检索。

---

## 3. 命名与索引规则

当前已采用命名格式：

1. `<4位doc_id>_<中文标题>.md`
2. 例：`0183_每日涨跌停价格.md`

新增/更新时要求：

1. 文档文件落到正确分类目录；
2. `docs_index.csv` 必须同步新增/更新对应行；
3. `local_path` 与真实相对路径保持一致（相对 `docs/sources/tushare/`）。

---

## 4. 与数据集文档的协作方式

推荐流程：

1. 先补或更新 `docs/sources/tushare/*`（接口输入事实）；
2. 再写 `docs/datasets/*-dataset-development.md`（工程实现决策）；
3. 在数据集文档中引用对应的 `doc_id` 和本地说明路径。

---

## 5. 维护约束

1. 只记录源站事实（输入参数、输出字段、限速、分页、更新时间、错误返回）；
2. 不把“我方实现选择”写进本目录；
3. 发现目录新增大类时，先更新本 README，再新增批量文档。

---

## 6. 提交前最小校验

1. 校验 `docs_index.csv` 的 `local_path` 都能命中本地文件；
2. 校验本目录没有噪音文件（如 `.DS_Store`）；
3. 若新增/改名文档，确认 `docs/README.md` 与 `docs/sources/README.md` 的索引仍然可读。

推荐直接执行：

```bash
python3 scripts/check_docs_integrity.py
```
