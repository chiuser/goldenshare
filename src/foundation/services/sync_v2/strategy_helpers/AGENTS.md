# AGENTS.md — `sync_v2/strategy_helpers/` 规则

## 适用范围

本文件适用于 `src/foundation/services/sync_v2/strategy_helpers/`。

---

## 1. 目录定位

该目录只承接“跨数据集可复用”的策略辅助能力，例如：

1. 交易日展开
2. 分页循环
3. 参数格式化

---

## 2. 硬约束

1. helper 必须保持无副作用/低副作用（纯函数优先）。
2. 禁止在 helper 里按具体 `dataset_key` 写分支。
3. 禁止在 helper 内访问数据库或外部 API。
4. 禁止在 helper 内构造业务语义文案。

---

## 3. 何时可以新增 helper

1. 至少两个数据集复用，才允许新增 helper。
2. 单数据集专用逻辑应留在对应 strategy 文件。
3. 若新增 helper，必须补单元测试。

---

## 4. 最小门禁

1. `pytest -q tests/test_sync_v2_planner.py tests/test_sync_v2_validator.py`
2. 影响到 helper 的策略数据集最小冒烟 1~2 个。

