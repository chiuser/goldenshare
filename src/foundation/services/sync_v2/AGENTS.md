# AGENTS.md — `src/foundation/services/sync_v2/` 规则

## 适用范围

本文件适用于 `src/foundation/services/sync_v2/` 及其子目录。  
若子目录存在更近的 `AGENTS.md`，以更近规则为准。

---

## 1. 目录定位

`sync_v2` 是当前唯一生效的数据同步主链，负责：

1. contract 校验与 lint。
2. 请求规划（anchor/window/fanout/pagination）。
3. worker 调用、归一化、写入、进度与错误上报。
4. runtime 注册与服务构建。

---

## 2. 模块职责边界

1. `engine.py`：执行编排与生命周期控制。
2. `validator.py`：契约与请求参数校验。
3. `planner.py`：执行单元规划（不落业务特例）。
4. `worker_client.py`：上游请求调用与重试。
5. `normalizer.py`：行标准化。
6. `writer.py`：写入策略落库。
7. `service.py`：对外服务入口。
8. `registry.py` / `runtime_registry.py`：合同与运行注册。
9. `dataset_strategies/`：每数据集请求编排策略。
10. `strategy_helpers/`：跨数据集复用 helper。

---

## 3. 禁止事项

1. 禁止在 `engine.py`、`planner.py` 注入数据集名判断分支。
2. 禁止在 `dataset_strategies/*` 直接写数据库或拼接 SQL。
3. 禁止在 helper 中加入仅单数据集生效的专用逻辑。
4. 禁止绕开 contract/linter 直接拼参数执行。
5. 禁止重建 V1 兼容路径。

---

## 4. 设计原则

1. 数据集差异放策略层，不放引擎层。
2. 执行语义统一，策略语义可扩展。
3. 先有 contract，再有请求编排，再有执行接线。
4. 优先显式语义，避免隐式默认魔法。

---

## 5. 动手前必读

1. `/Users/congming/github/goldenshare/src/foundation/AGENTS.md`
2. `/Users/congming/github/goldenshare/docs/architecture/sync-v2-registry-development-guide-v1.md`
3. `/Users/congming/github/goldenshare/docs/ops/tushare-request-execution-policy-v1.md`

---

## 6. 最小门禁

本目录改动后至少执行：

1. `pytest -q tests/test_sync_v2_validator.py tests/test_sync_v2_planner.py tests/test_sync_v2_linter.py`
2. `pytest -q tests/test_sync_v2_registry_routing.py`
3. `pytest -q tests/architecture/test_sync_v2_registry_guardrails.py`
4. `GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-v2-lint-contracts`

