# Local Lake CLI / Planner / Engine 架构收口方案 v1

- 版本：v1
- 状态：待评审
- 更新时间：2026-05-03
- 适用范围：`lake_console/backend/app`
- 目标：在继续接入 `moneyflow` 和更多 Lake 数据集前，先收口 CLI、Planner、Engine、Strategy 的职责边界。

---

## 1. 背景

`lake_console` 已经接入了几类代表性数据集：

| 类型 | 已有代表 | 当前状态 |
|---|---|---|
| 快照 / current 文件 | `stock_basic`、`trade_cal`、`index_basic` | 已实现 |
| 交易日分区 | `daily` | 已实现 |
| 超大分钟线 | `stk_mins` | 已实现 raw / derived / research |
| 资金流向 | `moneyflow` | catalog / plan / 文档已先行，engine 未接入 |

这几类已经足够暴露结构问题：

1. `lake_console/backend/app/cli.py` 正在变长，命令定义、参数解析、handler、输出混在一个文件。
2. `lake_console/backend/app/sync/planner.py` 同时承担 snapshot、trade_date、stk_mins 多种计划生成逻辑。
3. `lake_console/backend/app/sync/engine.py` 当前只是 if/else 分发，继续接数据集会膨胀。
4. 已有数据集 sync service 风格不完全统一，后续新增数据集缺少一个明确模板。

如果直接继续把 `moneyflow` 写进当前结构，短期能跑，但会把新数据集接入模板建立在已经开始发胖的入口文件上。  
因此，本轮先做架构收口，再让 `moneyflow` 成为新结构下第一个标准样板。

---

## 2. 本轮目标

### 2.1 要做

1. 拆分 CLI，形成“薄入口 + 命令模块”。
2. 拆分 Planner，形成“门面分发 + 分类 planner”。
3. 拆分 Engine，形成“门面分发 + 数据集 strategy”。
4. 沉淀最小通用 helper，不搞复杂 provider 抽象。
5. 增加 guardrail 测试，防止后续把数据集逻辑继续堆回 `cli.py`、大 planner 或大 engine。
6. 保持现有命令行为、参数、输出口径不变。

### 2.2 不做

1. 不接入 `moneyflow` 实现。
2. 不新增数据集。
3. 不改 Parquet 存储布局。
4. 不改前端页面。
5. 不接远程 `goldenshare-db`。
6. 不接生产 Ops / TaskRun / scheduler。
7. 不引入生产 `src/**` 运行时依赖。

---

## 3. 收口后的目录结构

目标结构：

```text
lake_console/backend/app/
  cli/
    __init__.py
    main.py
    commands/
      __init__.py
      common.py
      root.py
      status.py
      catalog.py
      sync_dataset.py
      stk_mins.py
      maintenance.py

  sync/
    __init__.py
    engine.py
    planner.py
    plans.py
    context.py
    results.py
    helpers/
      __init__.py
      dates.py
      pagination.py
      parquet_replace.py
      params.py
    planners/
      __init__.py
      snapshot.py
      trade_date.py
      stk_mins.py
    strategies/
      __init__.py
      base.py
      stock_basic.py
      trade_cal.py
      index_basic.py
      daily.py
      stk_mins.py
```

说明：

1. `cli/main.py` 是命令入口，只装配 parser。
2. `cli/commands/*.py` 每个文件负责一组命令。
3. `sync/planner.py` 是计划门面，只做分发。
4. `sync/planners/*.py` 放不同请求模型的计划逻辑。
5. `sync/engine.py` 是执行门面，只做分发、加载 context、调用 strategy。
6. `sync/strategies/*.py` 每个数据集一个策略文件。
7. `sync/helpers/*.py` 只放高确定性通用能力。

---

## 4. CLI 设计

### 4.1 当前问题

当前 `cli.py` 同时包含：

1. parser 创建。
2. 所有子命令参数定义。
3. handler 实现。
4. settings 加载。
5. Tushare client 创建。
6. 进度输出函数。
7. stk_mins 特殊逻辑。

这会导致新增一个数据集时，开发者自然去改同一个大文件，长期会失控。

### 4.2 目标职责

| 模块 | 职责 |
|---|---|
| `cli/main.py` | 构造根 parser，注册命令组，调用 handler |
| `cli/commands/common.py` | 通用参数、settings 加载、JSON 输出、freq 解析 |
| `cli/commands/status.py` | `init`、`status` |
| `cli/commands/catalog.py` | `list-datasets` |
| `cli/commands/sync_dataset.py` | `plan-sync`、`sync-dataset` |
| `cli/commands/stk_mins.py` | `sync-stk-mins`、`sync-stk-mins-range`、`derive-stk-mins`、`rebuild-stk-mins-research` |
| `cli/commands/maintenance.py` | `clean-tmp` |

### 4.3 兼容要求

现有命令名保持不变：

```text
lake-console init
lake-console status
lake-console list-datasets
lake-console plan-sync
lake-console sync-dataset
lake-console clean-tmp
lake-console sync-stock-basic
lake-console sync-trade-cal
lake-console sync-stk-mins
lake-console sync-stk-mins-range
lake-console derive-stk-mins
lake-console rebuild-stk-mins-research
```

短期允许保留 `sync-stock-basic`、`sync-trade-cal` 作为显式便捷命令。  
但后续新增普通数据集不得再新增一堆专用 CLI 命令，默认走：

```text
lake-console plan-sync <dataset_key>
lake-console sync-dataset <dataset_key>
```

`stk_mins` 因为任务模型特殊，可继续保留专用命令。

---

## 5. Planner 设计

### 5.1 当前问题

当前 `LakeSyncPlanner` 同时处理：

1. 快照类：`stock_basic`、`trade_cal`、`index_basic`
2. 交易日类：`daily`、`moneyflow`
3. 分钟线类：`stk_mins`

继续新增数据集后，`planner.py` 会变成按 dataset_key 堆 if/else 的大文件。

### 5.2 目标职责

| 模块 | 职责 |
|---|---|
| `sync/plans.py` | 定义 `LakeSyncPlan` |
| `sync/planner.py` | 门面，加载 catalog，按 dataset 类型分发 |
| `sync/planners/snapshot.py` | current 文件 / 双落盘 manifest 计划 |
| `sync/planners/trade_date.py` | `trade_date` 单日或区间交易日展开计划 |
| `sync/planners/stk_mins.py` | 分钟线请求窗口、全市场估算、配额估算 |

### 5.3 分发规则

Planner 不应硬编码越来越长的 dataset_key 列表。  
建议以 catalog 字段驱动：

| catalog 字段 | 用途 |
|---|---|
| `primary_layout` | 判断 current / by_date / by_symbol_month |
| `write_policy` | 判断 replace_file / replace_partition / rebuild_month |
| `request_strategy_key` | 指定具体 planner 或 strategy |
| `layers` | 推导写入路径 |

短期如果 catalog 字段还不够，可以保留小范围映射表，但映射表必须放在 planner 分发模块，不得散落在 CLI 或 service 中。

---

## 6. Engine / Strategy 设计

### 6.1 当前问题

当前 `LakeSyncEngine.sync_dataset` 直接 if/else：

```text
daily -> TushareDailySyncService
index_basic -> TushareIndexBasicSyncService
其他 -> 报错
```

继续接入 `moneyflow`、`adj_factor`、`fund_daily` 后，这里会迅速膨胀。

### 6.2 目标职责

| 模块 | 职责 |
|---|---|
| `sync/context.py` | `lake_root`、settings、client、progress 输出等执行上下文 |
| `sync/results.py` | 统一同步结果对象 |
| `sync/engine.py` | 加载 strategy 并执行 |
| `sync/strategies/base.py` | strategy 协议 / 基类 |
| `sync/strategies/<dataset_key>.py` | 单数据集请求、分页、校验、写入 |

### 6.3 Strategy 最小接口

建议接口：

```python
class LakeDatasetStrategy(Protocol):
    dataset_key: str

    def sync(self, command: LakeSyncCommand, context: LakeSyncContext) -> LakeSyncResult:
        ...
```

其中：

| 对象 | 含义 |
|---|---|
| `LakeSyncCommand` | CLI 已解析后的用户意图 |
| `LakeSyncContext` | Lake root、Tushare client、settings、progress writer |
| `LakeSyncResult` | fetched / written / rejected / output / elapsed |

第一轮可以先做最小 dataclass，不追求复杂类型系统。

### 6.4 数据集 strategy 文件规则

每个普通数据集一个文件：

```text
sync/strategies/daily.py
sync/strategies/moneyflow.py
sync/strategies/index_basic.py
```

文件内只允许处理该数据集：

1. 生成请求参数。
2. 调用 Tushare client。
3. 分页。
4. 校验字段。
5. 归一化行。
6. 决定分区。
7. 调用通用 Parquet replace helper。
8. 输出进度。

禁止在 strategy 中：

1. 读取远程 DB。
2. 调用生产 Ops。
3. 引入生产 TaskRun。
4. 处理其他数据集的特殊逻辑。

---

## 7. Helper 设计

只保留少量 helper，避免回到过度抽象。

| helper | 能力 |
|---|---|
| `dates.py` | 从本地 trade_cal manifest 展开交易日、自然日格式化 |
| `pagination.py` | `limit/offset` 循环，直到短页 |
| `params.py` | `date -> YYYYMMDD`、CSV enum 解析、ts_code 大写 |
| `parquet_replace.py` | `_tmp -> validate -> replace` |

不做：

1. 不做通用 provider 抽象。
2. 不做复杂 DSL。
3. 不把所有数据集强行压成一个万能 planner。
4. 不隐藏数据集自己的请求策略。

---

## 8. 迁移步骤

### S1：CLI 拆分，行为不变

任务：

1. 新增 `lake_console/backend/app/cli/`。
2. 把根 parser 和命令组拆出去。
3. 保留 `lake_console/backend/app/cli.py` 作为极薄入口，调用 `cli.main.main`。
4. 命令名、参数、输出不变。

验证：

```bash
lake-console --help
lake-console plan-sync daily --trade-date 2026-04-24
lake-console sync-dataset daily --trade-date 2026-04-24 --help
```

### S2：Planner 拆分，行为不变

任务：

1. 新增 `sync/plans.py`。
2. 新增 `sync/planners/snapshot.py`、`trade_date.py`、`stk_mins.py`。
3. `sync/planner.py` 保留 `LakeSyncPlanner` 门面。
4. 现有 plan 输出 JSON 字段保持不变。

验证：

```bash
pytest -q tests/lake_console/test_sync_planner.py
```

### S3：Engine / Strategy 拆分，行为不变

任务：

1. 新增 `sync/context.py`、`sync/results.py`、`sync/strategies/`。
2. 把 `daily`、`index_basic` 先迁到 strategy。
3. 保留现有 service 文件，strategy 可以先委托已有 service，避免同轮重写。
4. `sync/engine.py` 只做 strategy registry 分发。

验证：

```bash
pytest -q tests/lake_console/test_sync_services.py
```

### S4：Guardrail 测试

新增或更新测试：

| 测试 | 目的 |
|---|---|
| `test_lake_cli_entrypoint_is_thin` | 防止 `cli.py` 再次变成大入口 |
| `test_lake_sync_engine_uses_strategy_registry` | 防止 engine 堆 dataset if/else |
| `test_lake_planner_dispatches_to_planner_modules` | 防止 planner 继续膨胀 |
| `test_lake_strategy_files_match_catalog_datasets` | catalog 中可同步数据集必须有 strategy 或明确暂缓 |

第一版 guardrail 不要求所有 catalog 数据集都有 strategy。  
但必须明确区分：

1. `implemented`
2. `planned`
3. `not_supported`

避免出现 catalog 看似可用、engine 实际不可用的误导。

### S5：更新开发模板

更新：

```text
docs/templates/lake-dataset-development-template.md
```

补充：

1. 新增数据集必须指定 strategy 文件名。
2. 新增数据集必须指定 planner 类型。
3. 新增数据集必须补 command 示例。
4. 新增数据集必须补最小测试。

---

## 9. 对 moneyflow 的影响

`moneyflow` 暂不在本轮实现。  
本轮完成后，`moneyflow` 应按新结构接入：

```text
catalog/datasets/moneyflow.py
sync/planners/trade_date.py
sync/strategies/moneyflow.py
docs/datasets/moneyflow-lake-dataset-development.md
```

`moneyflow` 应成为普通交易日分页数据集的样板：

1. 使用本地 `trade_cal` 展开区间。
2. 按 `trade_date` 请求。
3. `limit=6000`、`offset` 分页。
4. `*_vol` 严格 int64。
5. 单日分区 `_tmp -> validate -> replace`。

---

## 10. 对生产 DB 导出 Parquet 的影响

本收口方案不引入生产 DB 导出。

如果后续要做“从生产 DB 只读导出 Parquet 初始化 Lake”，必须单独评审，并更新：

1. `lake_console/AGENTS.md`
2. `docs/architecture/local-lake-console-architecture-plan-v1.md`
3. 新增独立导入方案文档

该能力不能混入普通 `sync-dataset`，建议另设：

```text
lake-console import-db-dataset <dataset_key>
```

原因：

1. `sync-dataset` 表示从源站拉取。
2. `import-db-dataset` 表示从生产 DB 只读初始化。
3. 两者来源不同、风险不同、权限不同，不能混成一个入口。

---

## 11. 风险与防护

| 风险 | 影响 | 防护 |
|---|---|---|
| 拆分时改坏命令参数 | 现有命令不可用 | 先加/保留 CLI smoke |
| plan JSON 字段变化 | 前端或文档示例失效 | plan 输出字段保持不变 |
| strategy 抽象过度 | 开发变慢、难调试 | strategy 只做最小协议 |
| helper 变成万能框架 | 再次复杂化 | helper 只保留日期、分页、参数、replace |
| catalog 声称支持但 engine 不支持 | 用户误用 | catalog 增加实现状态或 guardrail |

---

## 12. 验收门禁

每轮至少执行：

```bash
pytest -q tests/lake_console/test_sync_planner.py
pytest -q tests/lake_console/test_sync_services.py
pytest -q tests/lake_console/test_tushare_client.py
pytest -q tests/lake_console/test_isolation_guardrails.py
python3 -m compileall -q lake_console/backend/app
python3 scripts/check_docs_integrity.py
```

涉及 CLI 拆分时追加：

```bash
lake-console --help
lake-console plan-sync daily --trade-date 2026-04-24
lake-console plan-sync index_basic
```

不要求本轮真实同步远程数据。

---

## 13. 完成后的结构判断标准

完成后应满足：

1. `lake_console/backend/app/cli.py` 只保留薄入口。
2. `sync/planner.py` 只保留门面，不承载具体请求模型细节。
3. `sync/engine.py` 只保留 strategy 分发。
4. 普通新增数据集只需要改：

```text
catalog/datasets/<group>.py
sync/strategies/<dataset_key>.py
docs/datasets/<dataset-key>-lake-dataset-development.md
tests/lake_console/*
```

5. 不需要再把大量逻辑塞进 CLI、Planner 或 Engine。

