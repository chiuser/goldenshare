# AGENTS.md — `src/operations/services` legacy 空目录规则

## 适用范围

本文件适用于 `src/operations/services/` 及其子目录。

---

## 当前状态

本目录已完成收口，当前仅保留本 `AGENTS.md`，不再保留任何 Python 文件。
说明：以 Git 跟踪文件为准；运行期生成的 `__pycache__` 不计入主实现范围。

---

## 允许与禁止

允许：

1. 更新收尾文档状态
2. 更新护栏测试规则

禁止：

1. 新增任何 Python 实现文件或 compat 壳
2. 将 `src/ops/services` 主实现写回本目录

---

## 护栏

由 `tests/architecture/test_operations_legacy_guardrails.py` 固化：

1. 本目录文件清单
2. legacy 导入回流检测
