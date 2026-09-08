# Serving Light 现行读取与刷新边界

更新时间：2026-09-08。状态：当前代码说明与原设计目标的区分记录。本专题保留仍在使用的 Light 能力，不新增表、开关、任务或刷新机制。

## 1. 范围与定位

数据分层、是否保留 Raw、数值类型、主键、分区与索引统一遵守 [Foundation 研发基线](/Users/congming/github/goldenshare/docs/architecture/foundation-current-standards.md)。不能从早期 Light 方案推出“所有数据集必须存 Raw”“所有价格默认 DOUBLE”或“所有主键都是 ts_code/trade_date”。

当前 `core_serving_light` 下并非全部是物化性能副本：

| 现行场景 | 实际职责 |
| --- | --- |
| `equity_daily_bar_light` | 从 `core_serving.equity_daily_bar` 刷新的股票日线实体投影，部分 Quote 查询优先读取 |
| news、major_news、st 等 Raw-backed 视图 | 由对应 Definition 的 Raw 写入与视图提供查询；不能一律套用日线实体刷新任务 |

具体交付、路径和 writer 分别读取 `storage.delivery_mode/layer_plan/write_path`；不能只根据 schema 名称判断是否需要刷新。定义入口：[news.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/news.py)、[reference_master.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/reference_master.py)。

新增物理性能投影仍须有明确高频瓶颈及字段/一致性设计，不强制所有数据集接入 Light。多源映射与发布见 [多源专题](/Users/congming/github/goldenshare/docs/architecture/dataset-publish-governance-spec-v1.md)，不新增一套 pipeline mode 或强制物理 Std 层。

## 2. 股票日线的读取开关

以下配置已存在，不是“建议新增”，定义在 [Settings](/Users/congming/github/goldenshare/src/foundation/config/settings.py)：

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `BIZ_USE_SERVING_LIGHT` | `true` | 在接入该开关的股票日线读取方法中优先用 Light |
| `BIZ_SERVING_FALLBACK` | `true` | 在上述读取方法中允许 Light 未命中或捕获到 SQLAlchemy 错误后尝试 Serving |

实际消费者：[QuoteQueryService](/Users/congming/github/goldenshare/src/biz/queries/quote_query_service.py)的 `_stock_daily_models_for_read()` 及其读取方法。

- use=false：该读取路径只选 `EquityDailyBar`。
- use=true、fallback=true：按 Light、Serving 顺序尝试。
- use=true、fallback=false：只选 Light。
- 这些不是“整个 Biz 的统一路由开关”；不能据此切换新闻视图或其他未接入的方法。
- 有数据即命中不代表数据最新或完整。当前选择顺序不能被描述为自动比较两层新鲜度、自动补齐缺口。
- fallback 只是既有尝试路径，不是所有数据库异常、事务失败或主库故障都能无损恢复的保证。

配置由 Settings/env 加载，`get_settings()` 有进程内缓存；不能把编辑环境变量文件描述为实时热更新。变更配置及生效操作需按既有运行环境流程执行，本文不授权修改或重启。

## 3. 股票日线实体刷新

当前链路：

```text
core_serving.equity_daily_bar
  -> ServingLightRefreshService.refresh_equity_daily_bar()
  -> INSERT SELECT + ON CONFLICT UPDATE
  -> core_serving_light.equity_daily_bar_light
```

[刷新服务](/Users/congming/github/goldenshare/src/ops/services/operations_serving_light_refresh_service.py)支持起止日期和股票过滤，按 `(ts_code, trade_date)` 更新该具体表；默认提交事务。该键只是这张表的合同，不是全仓默认主键。

已核验的入口：

1. [TaskRun dispatcher](/Users/congming/github/goldenshare/src/ops/runtime/task_run_dispatcher.py)中的 `_refresh_serving_light_if_needed()`：只处理 `resource=daily`；无保存行数时返回跳过说明，缺少有效日期边界时不刷新；有效范围调用刷新服务。不能据旧方案称为“通用独立异步刷新队列已完成”。
2. [CLI](/Users/congming/github/goldenshare/src/cli.py)的 `refresh-serving-light`，由 [maintenance_handlers.py](/Users/congming/github/goldenshare/src/cli_parts/maintenance_handlers.py)处理：只支持 `--dataset equity_daily_bar`，可传 `--start-date/--end-date/--ts-code`。
3. CLI 不传日期和股票会覆盖整个源表选择范围；服务执行的是 upsert，不是先清空再重建，也不会自动删除 Light 中已无对应源行的数据。

这些都是实际写入入口，不是只读检查。执行前须明确环境、范围和授权；本轮没有运行。

## 4. 一致性和原设计目标

对股票日线实体投影，`core_serving.equity_daily_bar` 是刷新源。字段语义应一致，Light 只承接所需字段和查询形态；其他 Light 视图的事实源由各自 Definition 决定。

原设计中下列要求保留为后续建设/验收方向，而不是已经可调用的 API 或本轮新待办：

- 单独的刷新状态、最近刷新时间、业务日期和相对延迟观测。
- 按范围核对行数、日期覆盖和样本内容的一致性巡检。
- Light 不一致时修复、刷新失败后的可重跑与受控发布/回退验收。
- 面向其他数据集的刷新/重建任务及物化方式选择。

旧文档列出的 `light_enabled/light_last_refreshed_at/light_latest_business_date/light_lag_seconds/light_refresh_status` 和 `refresh_serving_light.<dataset_key>/rebuild_serving_light.<dataset_key>` 是当时的拟议指标/任务命名，不能据此断言现行字段或任务已经存在。需要继续建设时，应先核验真实消费者和现有 Ops 观测能力，按需求确认方案，不机械增加这套名称。

关闭日线 Light 优先读取只改变已接入的读路径，不删除数据、不自动停止写入，也不保证 Serving 本身可用。不能再写成“切开关后业务一定不受影响”。

## 5. 验证与维护

现有证据入口：

- [刷新服务测试](/Users/congming/github/goldenshare/tests/test_serving_light_refresh_service.py)：SQL 与可选过滤。
- [Quote API 测试](/Users/congming/github/goldenshare/tests/web/test_quote_api.py)：Light 优先读取等既有用例。
- [Ops runtime 测试](/Users/congming/github/goldenshare/tests/web/test_ops_runtime.py)：dispatcher 调用现行刷新接口。
- [CLI 测试](/Users/congming/github/goldenshare/tests/test_cli_ops_runtime.py)：命令到服务的接线。

修改时需按影响范围补充开关组合、未命中/异常、范围刷新及两层对账；测试入口存在不等于全部故障或生产性能已验收。字段与类型不因文档精简而变更，新增数据集按 [数据集模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)填写一次，不另复制通用建表清单。
