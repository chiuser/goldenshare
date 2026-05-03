# DatasetDefinition 输入筛选契约清理方案 v1

- 状态：已实施
- 日期：2026-05-03
- 范围：`daily`、`adj_factor`、`cyq_perf`、`fund_daily`、`index_daily`、`index_daily_basic`
- 关联基线：
  - [DatasetDefinition 单一事实源重构方案 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md)
  - [DatasetDefinition 事实审计矩阵 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-fact-audit-matrix-v1.md)
  - [手动维护动作模型收敛方案 v2](/Users/congming/github/goldenshare/docs/ops/ops-manual-action-model-alignment-plan-v2.md)
  - [Tushare 全量数据集请求执行口径 v1](/Users/congming/github/goldenshare/docs/ops/tushare-request-execution-policy-v1.md)

## 1. 一句话结论

当前有 6 个数据集在 `DatasetDefinition.input_model.filters` 中错误声明了 `exchange`，但真实源接口契约和 request builder 都不使用该字段。  
这会把一个不存在的筛选项泄漏到 Ops 目录、TaskRun 请求上下文、`DatasetExecutionPlan.filters` 和 `plan_id`。本轮要做的是彻底删除这 6 个假字段，并把所有派生消费者一起收干净；不增加兼容层，不把错误字段补接回真实请求链。

## 2. 当前问题

当前链路是：

1. `DatasetDefinition.input_model.filters` 把 `exchange` 声明成合法筛选项，并且部分数据集给了默认值 `SSE`。
2. Ops `manual-actions` 与 `catalog` 目录接口直接从 `DatasetDefinition` 派生参数，因此会把这个假筛选项返回给前端。
3. 手动任务创建时，后端会给缺省筛选项补默认值，所以 `exchange=SSE` 会真的进入 `TaskRun.filters`。
4. `DatasetRequestValidator` 会继续把这个字段当成合法输入，写入 `validated.params`。
5. `DatasetActionResolver` 再把 `validated.params` 写进 `DatasetExecutionPlan.filters` 和 `plan_id`。
6. 但真正发源请求时，request builder 根本不读取 `exchange`，该字段在最后一步被静默丢弃。

这不是“前端展示多了一个无害字段”，而是“单一事实源里存在错误事实，并污染了从目录到执行计划的整条链路”。

## 3. 审计结论

### 3.1 本轮确认需要修复的对象

| 数据集 | 当前定义 | 源文档事实 | request builder 事实 | 本轮决策 |
|---|---|---|---|---|
| `daily` | `ts_code + exchange(default=SSE)` | 本地源文档只展示 `ts_code / start_date / end_date / trade_date` | `_daily_params()` 只发送 `trade_date + 可选 ts_code` | 删除 `exchange` |
| `adj_factor` | `ts_code + exchange(default=SSE)` | 本地源文档只展示 `ts_code / trade_date` | `_adj_factor_params()` 只发送 `trade_date + 可选 ts_code` | 删除 `exchange` |
| `cyq_perf` | `ts_code + exchange(default=SSE)` | 本地源文档只展示 `ts_code / start_date / end_date` | `_cyq_perf_params()` 只发送 `trade_date + 可选 ts_code` | 删除 `exchange` |
| `fund_daily` | `ts_code + exchange(default=SSE)` | 本地源文档只展示 `ts_code / start_date / end_date` | `_fund_daily_params()` 只发送 `trade_date + 可选 ts_code` | 删除 `exchange` |
| `index_daily` | `ts_code + exchange(default=SSE)` | 本地源文档只展示 `ts_code / start_date / end_date` | `_index_daily_params()` 只发送 `ts_code + 日期`，不读取 `exchange` | 删除 `exchange` |
| `index_daily_basic` | `ts_code + exchange(default=SSE)` | 本地源文档只展示 `trade_date` 示例 | `_index_daily_basic_params()` 只发送 `trade_date + 可选 ts_code` | 删除 `exchange` |

### 3.2 本轮明确不改的对象

这些数据集虽然也有 `exchange`，但当前代码和源文档都证明它们是有效参数，本轮禁止顺手改动：

| 数据集 | 保留原因 |
|---|---|
| `trade_cal` | 源接口支持 `exchange`，`_trade_cal_params()` 真实使用该字段 |
| `etf_basic` | 源接口支持 `exchange`，`_etf_basic_params()` 真实使用该字段 |
| `ths_index` | 源接口支持 `exchange`，`_ths_index_params()` 真实使用该字段 |
| `limit_list_d` | 源接口支持 `exchange`，并且当前按多值枚举扇出 |
| `stock_basic` | 源接口支持 `exchange`，当前作为基础主数据筛选条件使用 |

## 4. 修复目标

本轮完成后，必须同时满足以下条件：

1. 上述 6 个数据集的 `DatasetDefinition.input_model.filters` 中不再出现 `exchange`。
2. `GET /api/v1/ops/manual-actions` 对这 6 个数据集不再返回 `exchange` 筛选项。
3. `GET /api/v1/ops/catalog` 对这 6 个数据集不再返回 `exchange` 参数。
4. 手动任务创建时，这 6 个数据集不再向 `TaskRun.filters` 注入 `exchange=SSE`。
5. `DatasetRequestValidator` 对这 6 个数据集不再把 `exchange` 视为合法参数，也不再补默认值。
6. `DatasetExecutionPlan.filters` 与 `plan_id` 不再被这 6 个数据集的假 `exchange` 污染。
7. request builder 不做“补接 exchange”改造，继续保持只按真实源接口参数发请求。
8. 不做兼容过渡；如果外部仍给这 6 个数据集传 `exchange`，应按未定义参数直接报错。

## 5. 修改边界

### 5.1 允许修改

1. `src/foundation/datasets/definitions/market_equity.py`
2. `src/foundation/datasets/definitions/market_fund.py`
3. `src/foundation/datasets/definitions/index_series.py`
4. 与上述 6 个数据集相关的 registry / validator / resolver / ops API 测试
5. 本方案文档涉及到的正式说明文档与主索引

### 5.2 明确不改

1. `request_builders.py` 中这 6 个数据集的真实请求构造逻辑
2. 前端页面代码
3. 其他带 `exchange` 的合法数据集定义
4. 日期模型、分页策略、universe policy、progress 口径
5. TaskRun 运行时主链和数据库表结构

## 6. 实施步骤

### M1. 清理数据集定义

1. 从 `daily / adj_factor / cyq_perf / fund_daily / index_daily / index_daily_basic` 的 `input_model.filters` 中删除 `exchange`。
2. 不新增替代字段，不保留隐藏字段，不做 alias。

### M2. 收口派生消费者

由于 Ops 目录和手动任务接口直接从 `DatasetDefinition` 派生参数，本轮原则上不应修改查询层实现，只需要确认删除定义字段后以下接口自然收口：

1. `GET /api/v1/ops/manual-actions`
2. `GET /api/v1/ops/catalog`
3. `POST /api/v1/ops/manual-actions/{action_key}/task-runs`

若测试显示仍有该字段残留，再做最小修正；禁止为了“兼容旧字段”增加额外分支。

### M3. 收口执行计划污染

补测试确认：

1. `DatasetRequestValidator` 不再给这 6 个数据集补 `exchange=SSE`。
2. `DatasetActionResolver` 为这 6 个数据集生成的 `plan.filters` 不含 `exchange`。
3. 这 6 个数据集的 `plan.units[*].request_params` 仍保持当前真实请求结构，不额外新增 `exchange`。

### M4. 加回归门禁

增加针对这 6 个数据集的回归断言，防止假字段再次混入：

1. 定义层断言：这 6 个数据集的筛选字段集合中没有 `exchange`
2. Ops 目录断言：`manual-actions` / `catalog` 不返回 `exchange`
3. 拒绝旧口径断言：给这 6 个数据集传 `exchange` 时，返回未定义参数错误

这里不做泛化“自动推断死字段”的复杂规则，只做这 6 个已审计对象的明确门禁。

### M5. 同步文档

代码完成后，同步修正文档口径：

1. [DatasetDefinition 事实审计矩阵 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-fact-audit-matrix-v1.md)
2. [手动维护动作模型收敛方案 v2](/Users/congming/github/goldenshare/docs/ops/ops-manual-action-model-alignment-plan-v2.md)
3. [Ops 运营后台 API 全量说明 v1](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md)
4. [Tushare 全量数据集请求执行口径 v1](/Users/congming/github/goldenshare/docs/ops/tushare-request-execution-policy-v1.md)

## 7. 验证门禁

实施时至少执行：

```bash
pytest -q tests/test_dataset_definition_registry.py tests/test_dataset_action_resolver.py
pytest -q tests/web/test_ops_manual_actions_api.py tests/web/test_ops_catalog_api.py
pytest -q tests/architecture/test_subsystem_dependency_matrix.py tests/architecture/test_dataset_runtime_registry_guardrails.py
goldenshare ingestion-lint-definitions
python3 scripts/check_docs_integrity.py
```

如果实现过程中触发了前端 fixture 或契约快照变化，只允许补充对应测试，不允许顺手改页面逻辑。

## 8. 风险与注意事项

1. 这是一个有意为之的硬收口，不做兼容。任何仍按旧口径给这 6 个数据集传 `exchange` 的调用方，部署后都会收到校验错误。
2. 本轮最大风险不是业务数据错误，而是误删本来合法的 `exchange` 参数。所以实施前后都必须对“保留对象”再做一遍引用核验。
3. `index_daily` 当前本来就依赖 `ts_code` 或激活指数池生成执行单元，本轮不能碰它的 universe 规划逻辑。
4. `fund_daily`、`daily`、`adj_factor`、`cyq_perf` 的真实源请求继续保持“按交易日 + 可选单证券”模式，不能借这轮顺手扩展全量市场分片策略。

## 9. 完成门禁

只有同时满足下面 5 条，本轮才算真正完成：

1. 6 个目标数据集定义中 `exchange` 已删除。
2. `manual-actions` / `catalog` / TaskRun 提交链对这 6 个数据集不再出现 `exchange`。
3. 这 6 个数据集的执行计划与 request params 不再携带伪 `exchange`。
4. 合法 `exchange` 数据集完全不受影响。
5. 代码与文档口径同步更新，并通过验证门禁。

## 10. 实施结果

1. 6 个目标数据集定义中的伪 `exchange` 已删除。
2. `manual-actions` / `catalog` 对这 6 个数据集不再返回 `exchange`。
3. 手动任务创建对这 6 个数据集传入 `exchange` 时，现在会直接报未定义筛选项错误。
4. `DatasetActionResolver` 对这 6 个数据集不再注入默认 `exchange`，对应 `request_params` 保持原真实请求结构。
