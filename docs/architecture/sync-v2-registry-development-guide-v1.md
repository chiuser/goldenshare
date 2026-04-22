# Sync V2 Registry 开发指南 v1（新增数据集门禁）

- 版本：v1
- 日期：2026-04-22
- 适用范围：`src/foundation/services/sync_v2/registry_parts/**`
- 目标：约束后续新增/迁移数据集在 registry 的落位与写法，避免再次回到“大文件 + 复制粘贴”模式。

---

## 1. 先决条件（动手前必须完成）

1. 阅读：
   - [Sync V2 Registry 结构化重构方案 v1](/Users/congming/github/goldenshare/docs/architecture/sync-v2-registry-structure-refactor-plan-v1.md)
   - [数据同步 V2 重设计方案](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-redesign-plan.md)
2. 明确该数据集在源文档中的输入参数与时间语义（trade_date / start-end / month_key）。
3. 明确数据集归属业务域（见第 2 节），禁止临时放错文件。

---

## 2. 业务域分组规则（强约束）

`contracts/` 下按业务域落位：

1. `market_equity.py`：股票行情/交易行为
2. `market_fund.py`：基金行情
3. `index_series.py`：指数序列
4. `board_hotspot.py`：板块与热榜
5. `moneyflow.py`：资金流全族
6. `reference_master.py`：主数据/基础资料
7. `low_frequency.py`：低频事件

新增数据集必须先判定域归属，再写合同；禁止“先放一个地方跑通再说”。

---

## 3. 合同编写统一写法（强约束）

每个合同都必须走 builder，不允许直接 new 下列对象：

1. `build_input_schema(...)`（禁止直接 `InputSchema(...)`）
2. `build_planning_spec(...)`（禁止直接 `PlanningSpec(...)`）
3. `build_normalization_spec(...)`（禁止直接 `NormalizationSpec(...)`）
4. `build_write_spec(...)`（禁止直接 `WriteSpec(...)`）

说明：

1. `DatasetSyncContract(...)`、`SourceSpec(...)`、`ObserveSpec(...)`、`PaginationSpec(...)` 仍允许直接构造。
2. `write_spec` 与 `normalization_spec` 已纳入模板化，新增数据集不得绕开。

---

## 4. 参数/转换函数放置规则

1. 跨两个及以上数据集复用的参数拼装函数：放 `common/param_policies.py`
2. 跨两个及以上数据集复用的行转换函数：放 `common/row_transforms.py`
3. 纯常量枚举（默认 fanout 集合等）：放 `common/constants.py`
4. 仅单数据集使用且短小逻辑：可先放当前域文件；当出现复用立即上提到 `common/*`

---

## 5. 新增/迁移数据集标准流程（必须按顺序）

1. 在目标域文件新增合同到 `CONTRACTS`。
2. 补齐 `unit_params_builder` 与必要 `row_transform`。
3. 若有新枚举 fanout，补 `common/constants.py`。
4. 若有复用参数策略，补 `common/param_policies.py`。
5. 运行门禁测试（第 6 节）并修复。
6. 更新对应数据集研发文档与切换 runbook（若涉及 V1->V2 切换）。

---

## 6. 门禁（必须全绿）

每次改动 registry 后至少执行：

1. `pytest -q tests/architecture/test_sync_v2_registry_guardrails.py`
2. `pytest -q tests/test_sync_v2_registry_routing.py`
3. `pytest -q tests/test_sync_v2_validator.py tests/test_sync_v2_planner.py tests/test_sync_v2_linter.py`
4. `GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-v2-lint-contracts`

---

## 7. 禁止事项

1. 不允许把合同重新集中回单文件。
2. 不允许新增数据集时跳过业务域归属判定。
3. 不允许直接构造 `InputSchema/PlanningSpec/NormalizationSpec/WriteSpec`。
4. 不允许只改代码不补文档（至少要补数据集开发文档或切换 runbook 中的对应项）。

