# AGENTS.md — `src/platform` legacy 目录规则

## 适用范围

本文件适用于 `src/platform/` 及其子目录。

---

## 当前定位

`src/platform` 是 legacy 占位目录，不再承接主实现与兼容壳实现。
说明：以 Git 跟踪文件为准；运行期生成的 `__pycache__` 不计入主实现范围。

---

## 允许与禁止

允许：

1. 更新本目录说明文档
2. 更新与本目录相关的护栏测试

禁止：

1. 在本目录新增任何 Python 主实现
2. 将 `src/app` / `src/biz` / `src/ops` 主逻辑写回本目录
3. 以“临时兼容”为名新增长期 shim

---

## 护栏

由 `tests/architecture/test_platform_legacy_guardrails.py` 固化：

1. 运行代码/测试代码禁止导入 `src.platform.*`
2. 本目录不允许出现计划外 Python 文件

---

## 改动后说明

每次改动本目录需说明：

1. 是否仅为收尾说明/护栏更新
2. 是否新增 Python 文件（必须为否）
3. 是否影响 cleanup 文档状态
