# AGENTS.md — `sync_v2/dataset_strategies/` 规则

## 适用范围

本文件适用于 `src/foundation/services/sync_v2/dataset_strategies/`。

---

## 1. 目录定位

该目录承接“每个数据集如何请求”的策略实现。  
核心约束：**一数据集一策略文件**，同名对齐 `dataset_key`。

---

## 2. 硬约束

1. 每个数据集策略必须独立文件，禁止多数据集塞入一个文件。
2. 禁止在策略文件中进行数据库读写。
3. 禁止直接访问 `ops` 或其他子系统对象。
4. 禁止复制粘贴复杂逻辑；可复用能力必须上提到 `common.py` 或 `strategy_helpers/`。
5. 策略参数必须与源文档口径一致，禁止“猜参数”。

---

## 3. 编码规范

1. 优先复用：
   - `common.py`
   - `../strategy_helpers/trade_date_expand.py`
   - `../strategy_helpers/pagination_loop.py`
   - `../strategy_helpers/param_format.py`
2. 参数编排要显式体现：
   - 锚点类型
   - 默认分页大小
   - 多值枚举扇开策略
   - 用户显式传参与默认行为的优先级
3. 若某策略存在特殊约束，必须在注释中写“为什么”。

---

## 4. 变更流程

1. 先核对 `docs/sources/**` 接口文档与执行口径文档。
2. 再实现策略改动。
3. 最后补齐对应 contract 与测试。

---

## 5. 最小门禁

1. `pytest -q tests/test_sync_v2_planner.py tests/test_sync_v2_validator.py`
2. 目标数据集最小命令冒烟（选小时间窗）：
   - `goldenshare sync-daily -r <dataset> --trade-date <date>` 或
   - `goldenshare sync-history -r <dataset> --start-date <d1> --end-date <d2>`
3. `goldenshare sync-v2-lint-contracts`

