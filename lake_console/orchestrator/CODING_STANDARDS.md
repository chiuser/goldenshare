# Dagster Orchestrator 编码规范

本文档是 `lake_console/orchestrator` 的长期编码规范入口。后续新增编码规则优先追加到本文档；`AGENTS.md` 只保留硬门禁和指向关系。

## 命名与组织原则

正式代码命名必须表达长期业务含义和稳定技术职责，禁止表达临时阶段、开发过程、个人理解或一次性任务。

## Asset Schema Contract 与 Metadata 规范

正式 Dagster asset 的稳定字段契约必须在 asset definition metadata 中注册，禁止只靠某次 materialization metadata 承载。

规则：

1. 新增或修改正式 asset 时，必须在 `build_asset_definition_metadata(...)` 中显式传入 `column_schema=...`。
2. 字段契约统一定义在 `defs/run_contracts/asset_column_schemas.py`，使用 `ColumnContract(name, type, description)` 表达字段名、类型和中文说明。
3. `dagster/column_schema` 只允许出现在 definition metadata 中，表示“这个资产应该是什么字段契约”。
4. materialization metadata 只记录本次运行观察结果，例如 `dagster/uri`、`dagster/row_count`、`goldenshare/observed_columns`、样本和统计。
5. 禁止重新引入 `build_materialization_metadata(columns=...)`；运行时字段列表必须使用 `observed_columns=...`。
6. check metadata 如需记录字段观察结果，也必须使用 `observed_columns` 或显式 `goldenshare/observed_columns`，禁止裸写 `columns`。
7. raw、silver、gold、serving 的字段类型必须反映对应层级真实契约，不能为了 UI 好看改写实际数据类型。例如 raw 层 Tushare 日期字符串仍是 `VARCHAR`，silver/gold 标准日期才是 `DATE`。

### 禁止阶段编号进入正式代码

阶段编号只允许出现在设计文档、开发计划和提交说明中，不允许进入正式代码主概念。

禁止在正式文件名、函数名、变量名、asset/job/check/sensor/resource 名中使用以下语义：

```text
phase3
slice_301
poc
temp
new
old
final
```

示例：

```text
不合格：ensure_phase3_tables()
合格：  ensure_index_metadata_tables()
```

原因：`phase3`、`slice_301` 这类名字只对当前开发过程有意义，不能表达长期业务职责。半年后维护者不应该靠回忆开发阶段来理解代码。

### 文件名按数据域或职责命名

文件名必须体现数据集、数据域或稳定职责，不能只表达“装东西的盒子”。

示例：

```text
合格：  bootstrap/dataset_spec.py
合格：  jobs/index_daily_update.py
合格：  checks/market_major_indices_checks.py

不合格：bootstrap/types.py
不合格：jobs/update.py
不合格：utils.py
不合格：helpers.py
不合格：common.py
```

例外：如果目录本身已经限定得非常窄，且文件职责仍然一眼明确，可以使用较短名称；否则禁止使用宽泛文件名。

### 函数名必须表达动作和对象

函数名必须说明“对什么对象做什么事”。

示例：

```text
合格：  ensure_index_metadata_tables()
合格：  write_market_major_indices_snapshot()
合格：  load_index_daily_active_pool()

不合格：process_data()
不合格：sync_all()
不合格：handle_config()
不合格：ensure_phase3_tables()
```

### 变量名必须表达业务语义

变量名必须让读代码的人知道它承载的业务含义。

示例：

```text
合格：  active_pool_rows
合格：  major_indices_items
合格：  effective_index_codes

不合格：data
不合格：result
不合格：tmp_list
不合格：items2
```

例外：极短作用域内的通用局部变量可以使用短名称，但不能影响理解，也不能逃避业务语义。

### 一次性迁移来源不得污染长期主概念

一次性迁移、bootstrap、历史来源可以出现在设计文档、source method、materialization metadata 或审计记录中，但不能污染长期 asset/job 命名。

示例：

```text
合格 asset：raw_tushare_stock_daily
合格 metadata：source_method=old_lake_bootstrap

不合格 asset：old_lake_stock_daily_asset
```

### 面向未来维护者命名

正式代码名应优先服务未来维护者，而不是当前开发者。

一个名字半年后看，应该仍能判断：

1. 属于哪个数据域。
2. 维护什么资产或能力。
3. 是正式链路、初始化入口、维护入口，还是测试替身。

如果一个名字需要靠解释“这个 phase/slice 当时是什么意思”才能理解，它就是不合格名字。
