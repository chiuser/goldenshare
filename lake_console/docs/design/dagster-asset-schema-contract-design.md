# Dagster Asset Schema Contract 改造方案

更新时间：2026-05-29

## 1. 背景

当前 Dagster UI 的 asset columns 表中，部分资产字段 `type` 显示为 `unknown`，字段描述为空。

历史原因是早期代码主要把字段 schema 放在 materialization metadata 中。该口径已经退场，后续禁止继续使用：

```text
build_materialization_metadata(columns=...)  # 历史旧口径，已禁止
  -> dagster/column_schema
```

如果传入的是纯列名字符串，当前 helper 会把字段类型兜底成 `unknown`。字段描述为空，是因为当前 helper 没有给 `dagster.TableColumn` 注册 description。

这导致两个问题：

1. 稳定字段契约依赖某次 materialization，而不是 asset definition 本身。
2. UI 能看到“这次运行观察到哪些列”，但看不到“这个正式资产应该有哪些字段、类型、业务含义”。

## 2. 官方依据

Dagster 支持在两个层次记录 metadata：

1. Asset definition metadata：资产定义时就已知的稳定信息。
2. Runtime / materialization metadata：某次运行后才知道的实际结果。

Dagster 对表结构有标准 metadata key：

```text
dagster/column_schema
```

对应 API：

```python
dg.MetadataValue.table_schema(
    dg.TableSchema(
        columns=[
            dg.TableColumn(
                name="trade_date",
                type="DATE",
                description="交易日",
            )
        ]
    )
)
```

参考：

```text
https://docs.dagster.io/guides/build/assets/metadata-and-tags
```

设计结论：

1. 稳定字段契约应注册在 asset definition metadata。
2. materialization metadata 只记录本次运行实际结果。
3. asset checks 负责验证“实际输出 schema”是否等于“definition contract”。

## 3. 改造目标

把所有正式 Dagster asset 调整为统一 schema contract 口径：

```text
asset definition metadata
  放应然契约：字段名、字段类型、字段说明

materialization metadata
  放实然结果：path、row_count、observed_columns、partition metadata、样本和统计

asset checks
  验证实际 parquet / ClickHouse schema 是否满足 definition contract
```

改造完成后，Dagster UI 的 asset columns 表应能显示：

1. 字段名。
2. 字段类型。
3. 字段说明。

## 4. 改造范围

当前 `lake_console/orchestrator/src/orchestrator/defs/assets/*.py` 中共有 19 个 active table-like assets：

| Asset | 层级 | 当前状态 |
|---|---|---|
| `raw_tushare_trade_calendar` | raw | 已注册 definition column schema |
| `silver_trade_calendar` | silver | 已注册 definition column schema |
| `raw_tushare_stock_basic` | raw | 已注册 definition column schema |
| `silver_stock_basic` | silver | 已注册 definition column schema |
| `raw_tushare_stock_daily` | raw | 已注册 definition column schema |
| `silver_stock_daily` | silver | 已注册 definition column schema |
| `raw_tushare_adj_factor` | raw | 已注册 definition column schema |
| `silver_adj_factor` | silver | 已注册 definition column schema |
| `raw_tushare_suspend_d` | raw | 已注册 definition column schema |
| `silver_stock_suspend_daily` | silver | 已注册 definition column schema |
| `raw_tushare_index_basic` | raw | 已注册 definition column schema |
| `silver_index_basic` | silver | 已注册 definition column schema |
| `raw_tushare_index_daily_by_code` | raw | 已注册 definition column schema |
| `silver_index_daily` | silver | 已注册 definition column schema |
| `gold_market_breadth_daily` | gold | 已注册 definition column schema |
| `gold_stock_return_distribution` | gold | 已注册 definition column schema |
| `gold_market_major_indices_daily` | gold | 已注册 definition column schema |
| `ch_share_fact_market_breadth_daily` | serving | 已注册 definition column schema |
| `prod_ch_share_fact_market_breadth_daily` | serving | 已注册 definition column schema；与本机 ClickHouse serving asset 共用同一张表契约 |

本方案不改：

1. asset key。
2. 分区定义。
3. 物理路径。
4. SQL 计算逻辑。
5. Tushare 请求参数。
6. ClickHouse 表结构。
7. jobs / sensors / automation selection。

## 5. 目标代码结构

### 5.1 新增字段契约模型

建议新增：

```text
lake_console/orchestrator/src/orchestrator/defs/run_contracts/column_schema.py
```

职责：

1. 定义 `ColumnContract`。
2. 把 `ColumnContract` 转成 `dg.TableColumn`。
3. 把一组字段契约转成 `dg.MetadataValue.table_schema(...)`。

建议结构：

```python
@dataclass(frozen=True)
class ColumnContract:
    name: str
    type: str
    description: str
```

### 5.2 新增资产字段契约注册表

建议新增：

```text
lake_console/orchestrator/src/orchestrator/defs/run_contracts/asset_column_schemas.py
```

职责：

1. 集中维护当前 19 个 active table-like assets 的字段契约。
2. 每个契约必须包含字段名、类型和中文说明。
3. 类型口径必须与该资产实际层级一致。

示例：

```python
GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA = (
    ColumnContract("trade_date", "DATE", "交易日"),
    ColumnContract("rank", "INTEGER", "主要指数展示顺序，来自 seed 固定排序"),
    ColumnContract("ts_code", "VARCHAR", "指数代码"),
    ColumnContract("display_name", "VARCHAR", "指数展示名称"),
    ...
)
```

### 5.3 扩展 metadata helper

修改：

```text
lake_console/orchestrator/src/orchestrator/defs/run_contracts/metadata.py
```

目标：

1. `build_asset_definition_metadata(...)` 支持 `column_schema` 参数。
2. 只有 definition metadata 写 `dagster/column_schema` 作为稳定字段契约。
3. `build_materialization_metadata(...)` 不再默认用 `columns` 生成正式 schema。
4. materialization 中的实际输出列改为 `goldenshare/observed_columns`。

建议新口径：

```python
build_asset_definition_metadata(
    ...,
    column_schema=GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA,
)

build_materialization_metadata(
    row_count=...,
    observed_columns=columns,
)
```

### 5.4 保留运行时观察信息

当前 materialization metadata 里的 `dagster/row_count`、`dagster/uri` 继续保留。

运行时字段列表不再作为正式 contract，而是记录为：

```text
goldenshare/observed_columns
```

如果未来有“运行后才知道 schema”的资产，必须在方案中单独说明，不能默认走正式资产契约。

## 6. 字段类型口径

类型命名第一版统一使用 DuckDB / Parquet 侧可读类型：

| 业务类型 | schema type |
|---|---|
| 日期 | `DATE` |
| 字符串 | `VARCHAR` |
| 整数 | `INTEGER` / `BIGINT` |
| 浮点数 | `DOUBLE` |
| 布尔 | `BOOLEAN` |
| 时间戳 | `TIMESTAMP` / `DATETIME` |

注意：

1. raw 层 Tushare 日期字段如果保持 `YYYYMMDD` 字符串，类型写 `VARCHAR`。
2. silver / gold 层交易日期如果已经标准化为日期，类型写 `DATE`。
3. ClickHouse serving 层按 serving 表契约写，比如 `Date` / `UInt64` / `Float64` / `DateTime`，但必须与 Flyway migration 保持一致。
4. 不允许把 raw 的日期字符串误写成 `DATE`。
5. 不允许为了 UI 好看而改实际数据类型。

## 7. 分步实施计划

### Slice SC-1：基础能力

目标：

1. 新增 `ColumnContract` 和 table schema 转换 helper。
2. 扩展 `build_asset_definition_metadata(...)`，支持 definition-time column schema。
3. 调整 `build_materialization_metadata(...)`，区分正式 schema 与 observed columns。
4. 不接入任何具体 asset。

改动文件：

```text
lake_console/orchestrator/src/orchestrator/defs/run_contracts/column_schema.py
lake_console/orchestrator/src/orchestrator/defs/run_contracts/metadata.py
```

验收：

1. `uv run dg check defs` 通过。
2. 现有 asset definition 不变。
3. 没有 data lake 写入。
4. 没有 Dagster run。

### Slice SC-2：单资产试点（已按 `gold_market_major_indices_daily` 落地）

状态：

1. 已新增 `asset_column_schemas.py`，先注册 `GOLD_MARKET_MAJOR_INDICES_DAILY_SCHEMA`。
2. `gold_market_major_indices_daily` 已在 definition metadata 注册 `dagster/column_schema`。
3. 该资产的 materialization metadata 已从旧 `columns=` 改为 `observed_columns=`。
4. `MARKET_MAJOR_INDICES_DAILY_COLUMNS` 和 `MARKET_MAJOR_INDICES_DAILY_COLUMN_TYPES` 已从 schema contract 派生，避免字段契约维护两份。

目标：

1. 只改 `gold_market_major_indices_daily`。
2. 在 definition metadata 注册字段名、类型、中文说明。
3. materialization metadata 改为 `observed_columns`。

改动文件：

```text
lake_console/orchestrator/src/orchestrator/defs/run_contracts/asset_column_schemas.py
lake_console/orchestrator/src/orchestrator/defs/assets/market_major_indices.py
lake_console/orchestrator/tests/test_asset_governance_contracts.py
```

验收：

1. reload definitions 后，`gold_market_major_indices_daily` UI columns 显示 type / desc。
2. 单日 materialize 后，materialization metadata 保留 path、row_count、observed columns。
3. 资产数据不变。
4. checks 不变。

### Slice SC-3：推广到 gold + serving（已落地）

状态：

1. `gold_market_breadth_daily`、`gold_stock_return_distribution`、`gold_market_major_indices_daily`、`ch_share_fact_market_breadth_daily` 均已注册 definition column schema；后续新增的 `prod_ch_share_fact_market_breadth_daily` 与本机 ClickHouse serving asset 共用同一张表 schema contract，也已纳入最终资产清单。
2. gold / serving 层运行时列信息已收敛为 `goldenshare/observed_columns`，不再用 materialization metadata 承载稳定字段契约。
3. ClickHouse serving schema 已按 Flyway V2 表契约注册为 `Date`、`UInt32`、`Float64`、`DateTime`。
4. 本次未修改 SQL、checks、jobs、sensors、automation 或 ClickHouse 表结构。

范围：

```text
gold_market_breadth_daily
gold_stock_return_distribution
gold_market_major_indices_daily
ch_share_fact_market_breadth_daily
prod_ch_share_fact_market_breadth_daily
```

目标：

1. 所有 gold / serving asset 注册 definition column schema。
2. 所有运行时 columns 统一改为 observed columns。
3. ClickHouse serving schema 与 Flyway V2 表契约一致。

验收：

1. 4 个 asset 的 UI columns 都有 type / desc。
2. `uv run dg check defs` 通过。
3. 不改变 gold / serving 生成结果。

### Slice SC-4：推广到 silver（已落地）

状态：

1. `silver_trade_calendar`、`silver_stock_basic`、`silver_stock_daily`、`silver_adj_factor`、`silver_stock_suspend_daily`、`silver_index_basic`、`silver_index_daily` 均已注册 definition column schema。
2. silver 层日期字段按标准化后的真实类型注册为 `DATE`。
3. `silver_stock_daily` 与 `silver_index_daily` 的变动值字段统一注册为 `change_amount`，不使用 raw 层 `change`。
4. silver 层运行时列信息已收敛为 `goldenshare/observed_columns`，不再用 materialization metadata 承载稳定字段契约。
5. 相关 silver 列常量已从 schema contract 派生，避免字段契约维护两份。

范围：

```text
silver_trade_calendar
silver_stock_basic
silver_stock_daily
silver_adj_factor
silver_stock_suspend_daily
silver_index_basic
silver_index_daily
```

重点：

1. silver 日期字段必须按标准化后的真实类型写。
2. `change_amount` 不能写成 raw 的 `change`。
3. `silver_stock_daily` / `silver_index_daily` 的价格字段类型必须与实际 parquet 一致。
4. materialization metadata 只记录本次运行观察列，不再承担稳定 schema 职责。

验收：

1. UI columns 显示 type / desc。
2. 现有 silver checks 继续通过。
3. 不改变 silver parquet 写入逻辑。

### Slice SC-5：推广到 raw（已落地）

状态：

1. `raw_tushare_trade_calendar`、`raw_tushare_stock_basic`、`raw_tushare_stock_daily`、`raw_tushare_adj_factor`、`raw_tushare_suspend_d`、`raw_tushare_index_basic`、`raw_tushare_index_daily_by_code` 均已注册 definition column schema。
2. raw 层字段契约保持源站镜像口径：Tushare 日期字符串仍注册为 `VARCHAR`，`raw_tushare_trade_calendar.is_open` 注册为 `INTEGER`，股票/指数日线 raw 字段继续使用 `change`。
3. Tushare raw 写入 helper 的运行时列信息已从旧 `columns=` 收敛为 `goldenshare/observed_columns`；`fields` 作为本次请求观测信息继续保留在 materialization metadata。
4. raw 字段常量和 raw column type maps 已从 schema contract 派生，避免字段契约维护两份。

范围：

```text
raw_tushare_trade_calendar
raw_tushare_stock_basic
raw_tushare_stock_daily
raw_tushare_adj_factor
raw_tushare_suspend_d
raw_tushare_index_basic
raw_tushare_index_daily_by_code
```

重点：

1. raw 层字段必须保持源站镜像口径。
2. Tushare 日期字段如果源契约是 `YYYYMMDD` 字符串，就写 `VARCHAR`。
3. 不因为 silver 标准化而污染 raw schema。

验收：

1. UI columns 显示 type / desc。
2. raw checks 继续使用源站字段契约。
3. 不改 Tushare 请求和 raw parquet 字段。

### Slice SC-6：收口与门禁固化（已落地）

状态：

1. `build_materialization_metadata(...)` 已删除 `columns=` 过渡参数，只接受 `observed_columns=...` 记录运行时观察列。
2. `dagster/column_schema` 只允许由 `build_asset_definition_metadata(..., column_schema=...)` 写入 asset definition metadata。
3. `build_check_metadata(...)` 不再接受裸 `columns` runtime metadata；如需记录字段观察结果，必须使用 `observed_columns` 或显式 `goldenshare/observed_columns`。
4. Bootstrap 通用迁移 helper 已改为通过 `build_materialization_metadata(uri=..., row_count=..., observed_columns=...)` 返回 metadata。
5. 静态门禁已固化：正式 `@dg.asset` 必须显式注册 `column_schema`，任何 `build_materialization_metadata(columns=...)` callsite 都会失败。
6. 开发模板已更新，新增数据集和 bootstrap 迁移模板不再传播旧 `columns` 口径。

目标：

1. 更新 `CODING_STANDARDS.md`。
2. 明确新增 asset 必须带 definition column schema。
3. 清理旧 helper 参数中容易误用的 `columns` 语义。
4. 文档记录最终口径。

验收：

1. `rg "build_materialization_metadata\\([^)]*columns=" lake_console/orchestrator/src lake_console/orchestrator/tests` 无结果。
2. `uv run python -m unittest tests.test_metadata_contracts` 通过。
3. `uv run python -m unittest tests.test_asset_governance_contracts` 通过。
4. `uv run python -m unittest tests.test_run_contract_static_gates` 通过。
5. `python3 scripts/check_docs_integrity.py` 通过。
6. `git diff --check` 通过。

## 8. 验收方案

### 8.1 静态验收

每个 Slice 至少执行：

```text
uv run dg check defs  # 需单独批准后执行
python3 scripts/check_docs_integrity.py
git diff --check
git status --short
```

说明：

1. `uv run dg check defs` 属于 Dagster definitions 加载验证，执行前仍需按正式环境门禁确认。
2. 本改造不要求运行 job / sensor / backfill。
3. 如需单日 materialize 验证 UI，必须单独列命令并获得确认。
4. 2026-05-29 已由用户自行完成 definitions 与 UI 验收；本轮文档只记录验收状态，不重复执行正式 Dagster 命令。

### 8.2 UI 验收

每层至少选择一个代表资产：

| 层级 | 代表资产 |
|---|---|
| raw | `raw_tushare_stock_daily` |
| silver | `silver_stock_daily` |
| gold | `gold_market_major_indices_daily` |
| serving | `ch_share_fact_market_breadth_daily` |

验收内容：

1. Asset 页面 columns 表显示字段类型。
2. Asset 页面 columns 表显示字段说明。
3. 字段顺序与定义契约一致。
4. reload definitions 后 definition schema 可见。
5. 单日 materialize 后 runtime metadata 仍能看到 row_count、path、observed columns。

验收结论：

1. SC-1 至 SC-6 已完成开发与收口。
2. 19 个 active table-like assets 已接入 definition column schema。
3. 用户已完成 UI 自验，确认 schema contract 口径可用。
4. 历史 materialization metadata 不刷新，这是预期；如需清理旧 event log，另起方案。

### 8.3 数据不变验收

本改造不应改变任何业务数据。

抽样检查：

1. 同一分区重跑前后 parquet row_count 不变。
2. 同一分区字段名不变。
3. checks 结果不因 metadata 改造变化。
4. ClickHouse serving 表不因 metadata 改造被写入或删除。

## 9. 风险评估

### 9.1 数据风险

低。

原因：

1. 不改 SQL。
2. 不改路径。
3. 不改请求参数。
4. 不改写入逻辑。
5. 不改 job / sensor selection。

### 9.2 契约风险

中。

原因：

1. 字段类型写错会变成 UI 和文档中的正式错误口径。
2. raw / silver 同名字段类型可能不同，例如 `trade_date`。
3. ClickHouse serving 类型必须与 Flyway migration 一致。
4. 字段描述如果写得含糊，会降低治理质量。

控制方式：

1. 每个资产必须从当前代码、SQL 和 checks 反推字段契约。
2. 不允许凭字段名猜类型。
3. raw 层必要时对照 Tushare 字段契约。
4. serving 层必须对照 Flyway migration。

### 9.3 UI 历史显示风险

中低。

说明：

1. definition metadata reload 后应能显示新的稳定 schema。
2. 历史 materialization metadata 不会自动变成新 metadata。
3. 旧历史 run 中的 metadata 仍可能保留旧的 `unknown` schema。
4. 如要清理历史 metadata，需要另起 Dagster event log 清理方案，不属于本改造。

## 10. 不做事项

本方案不做：

1. 不清理历史 materialization。
2. 不修改 Dagster PostgreSQL event log。
3. 不物理重写全量 parquet。
4. 不为了刷新 UI 而做大范围 backfill。
5. 不把 ClickHouse serving 表结构改成新版本。
6. 不引入外部 schema registry。

## 11. 完成定义

完成后应满足：

1. 所有 19 个 active table-like assets 都在 definition metadata 中注册 column schema。
2. 每个字段都有 name、type、description。
3. materialization metadata 不再承担稳定字段契约职责。
4. runtime observed columns 仍可见。
5. 所有现有 checks、jobs、sensors、automation definitions 加载正常。
6. UI columns 表不再大面积出现 `unknown` 和空 desc。
7. 新增资产的编码规范中明确要求 definition column schema。

当前状态：

1. 已完成。
2. 后续新增 asset 必须继续遵守 `CODING_STANDARDS.md` 中的 schema contract 门禁。
