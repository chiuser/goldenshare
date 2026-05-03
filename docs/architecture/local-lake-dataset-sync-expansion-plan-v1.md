# Local Lake 数据集同步扩展方案 v1

- 版本：v1
- 状态：已部分落地，CLI / Planner / Engine 收口已实施，`moneyflow` 已按新结构接入
- 更新时间：2026-05-03
- 适用范围：`lake_console` 本地移动盘 Tushare Parquet Lake
- 相关文档：
  - [Local Lake Console 架构方案 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-architecture-plan-v1.md)
  - [Local Lake Console 数据集模型 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-dataset-model-v1.md)
  - [Local Lake CLI / Planner / Engine 架构收口方案 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-cli-planner-engine-refactor-plan-v1.md)
  - [股票历史分钟行情 Parquet Lake 方案 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-parquet-lake-plan-v1.md)
  - [DatasetDefinition 单一事实源重构方案 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md)

---

## 1. 背景

当前数据基座已经通过 `src/foundation/datasets/**` 的 `DatasetDefinition` 收敛了数据集事实，包括：

1. 数据集标识、展示名、来源、API 名称。
2. 输入字段、时间模型、分页参数、枚举扇出、证券池依赖。
3. 原始表、标准表、服务表和写入策略。

`lake_console` 已经具备本地 Lake 的第一批能力：

1. 独立本地工程，不挂入生产 Web/Ops。
2. 本地配置 `GOLDENSHARE_LAKE_ROOT` 和 `TUSHARE_TOKEN`。
3. Tushare 请求限速。
4. Parquet 写入。
5. `_tmp -> 校验 -> 替换正式文件/分区`。
6. `stock_basic`、`trade_cal` 双落盘。
7. `stk_mins` 原始层、派生层、research 层。
8. CLI / Planner / Engine 已收口为分组命令、分类 planner 与 dataset strategy。
9. `daily`、`index_basic`、`moneyflow` 已接入 `sync-dataset` strategy 分发。

下一步目标是：让数据基座中已经支持的数据集，逐步具备“下载到本地移动盘并生成 Parquet Lake”的能力。

---

## 2. 核心判断

### 2.1 不直接复用生产同步运行时

`lake_console` 不应该直接复用生产侧 `IngestionExecutor`、TaskRun、Ops 状态、DAO 或远程数据库能力。

原因：

1. `lake_console` 是本地移动盘工具，不能读写远程 `goldenshare-db`。
2. 生产同步运行时面向 Postgres 表、TaskRun 观测和 Ops 页面，不等同于 Parquet Lake 写入。
3. 生产侧部分 universe policy 依赖数据库表，例如股票池、指数池、板块池；Lake 必须改为读取本地 manifest 或本地 Parquet。
4. 生产侧状态写入、任务状态、数据新鲜度不应污染本地 Lake。

正确做法：

```text
复用 DatasetDefinition 的事实与请求经验
不复用生产运行时依赖
在 lake_console 内建立轻量 Lake Dataset Catalog 和 Lake Sync Engine
```

### 2.2 `stk_mins` 不是所有数据集的模板

`stk_mins` 是超大数据集特例，它验证了：

1. 大任务需要清晰进度。
2. 写入必须是临时目录校验后替换。
3. 本地股票池不能从远程 DB 读取。
4. Parquet 分区必须服务查询场景。

但大多数数据集比 `stk_mins` 简单，不应该照搬它的复杂度。

---

## 3. 目标

本方案目标：

1. 为数据基座已支持的数据集建立本地 Lake 同步扩展路线。
2. 明确如何参考 `DatasetDefinition`，但不违反 `lake_console` 隔离规则。
3. 明确 Lake 数据集 catalog、请求策略、写入策略、分区策略和命令行交互。
4. 按风险分批迁移，不做 big-bang。
5. 每批上线前都能先 dry-run 看到请求计划。

本方案不做：

1. 不把 `lake_console` 接入生产 Ops。
2. 不开发自动调度。
3. 不接远程数据库。
4. 不把生产前端或生产后端代码搬进 `lake_console`。
5. 不一次性迁移全部数据集。

---

## 4. 总体架构

当前 CLI、Planner、Engine 的进一步拆分以 [Local Lake CLI / Planner / Engine 架构收口方案 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-cli-planner-engine-refactor-plan-v1.md) 为准。

建议在 `lake_console/backend/app` 下建立 Lake 专用同步结构：

```text
lake_console/backend/app/
  catalog/
    models.py
    view_groups.py
    datasets/
      reference_master.py
      market_equity.py
      market_fund.py
      index_series.py
      moneyflow.py
      board_hotspot.py
      low_frequency.py
      news.py

  sync/
    engine.py
    context.py
    result.py
    helpers/
      trade_calendar.py
      pagination.py
      enum_fanout.py
      params.py
      parquet_replace.py
    strategies/
      stock_basic.py
      trade_cal.py
      daily.py
      adj_factor.py
      moneyflow.py
      index_basic.py
      stk_mins.py
```

### 4.1 Lake Dataset Catalog

Lake Dataset Catalog 是 `lake_console` 内部的数据集目录。

它记录：

1. `dataset_key`
2. `display_name`
3. `source`
4. `api_name`
5. `source_doc_id`
6. `lake_layers`
7. `primary_layout`
8. `partition_policy`
9. `write_policy`
10. `request_strategy_key`
11. `page_limit`
12. `requires_manifest`
13. `supported_commands`

Catalog 可以参考 `src/foundation/datasets/**`，但第一阶段不直接 import 生产运行时代码。

`catalog/datasets/*.py` 的文件命名只表达开发维护分包，不作为前端展示分组。  
前端展示分组必须参考 Ops 默认展示目录，即 [Ops 数据集展示目录配置方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-dataset-catalog-view-plan-v1.md) 第 10 节“目标展示分组”。

### 4.1.1 Lake 前端展示分组

Lake Console 前端的数据集列表应使用独立展示目录配置：

```text
lake_console/backend/app/catalog/view_groups.py
```

该配置的分组 key、名称和顺序参考 Ops 文档第 10 节目标展示分组表，而不是参考生产 `DatasetDefinition.domain`，也不是参考 `catalog/datasets/*.py` 的代码文件名。

Lake 第一版展示分组如下：

| group_key | group_label | group_order |
|---|---|---:|
| `reference_data` | A股基础数据 | 1 |
| `equity_market` | A股行情 | 2 |
| `board_theme` | 板块 / 题材 | 3 |
| `leader_board` | 榜单 | 4 |
| `limit_board` | 涨跌停榜 | 5 |
| `index_market_data` | A股指数行情 | 6 |
| `etf_fund` | ETF基金 | 7 |
| `moneyflow` | 资金流向 | 8 |
| `broker_recommendation` | 券商推荐 | 9 |
| `news` | 新闻资讯 | 10 |
| `hk_reference_data` | 港股基础数据 | 11 |
| `us_reference_data` | 美股基础数据 | 12 |
| `technical_indicators` | 技术指标 | 13 |

说明：

1. 这套分组是用户可见分组，用于 Lake Console 前端数据集列表和筛选。
2. 这套分组参考 Ops 默认目录，但不直接依赖 `src/ops/**` 代码。
3. 如果某个 Lake 数据集暂未出现在 Ops 第 10 节表格，必须先评审补充分组，不允许前端自行放入“其他”。
4. `raw_tushare`、`derived`、`research`、`manifest` 是数据层级，不是数据集展示分组。
5. `derived/research` 可以在数据集详情页作为层级展示，也可以在后续评审后增加独立视图，但不能替代数据集所属展示分组。

### 4.2 Lake Sync Engine

Lake Sync Engine 只负责本地 Lake 的执行能力：

1. 解析命令参数。
2. 加载 Lake Root。
3. 加载 Lake Dataset Catalog。
4. 调用数据集策略函数生成请求。
5. 执行 Tushare 请求与限速。
6. 执行分页。
7. 归一化行数据。
8. 写入 `_tmp`。
9. 校验 Parquet。
10. 替换正式文件或分区。
11. 写入 `manifest/sync_runs.jsonl`。
12. 输出进度。

Engine 不负责：

1. TaskRun。
2. Ops 数据状态。
3. 远程 DB。
4. 自动调度。
5. 生产 API。

### 4.3 数据集策略函数

每个数据集一个策略文件，直接写清楚怎么请求和怎么写入。

策略文件至少定义：

| 能力 | 含义 |
|---|---|
| `build_requests` | 根据命令参数、本地交易日历、本地证券池生成请求单元 |
| `normalize_row` | 把 Tushare 返回行转换为 Lake row |
| `partition_for_row` | 决定该行写入哪个分区 |
| `write_scope_for_request` | 决定替换单文件、单日期、单月或 current |
| `page_limit` | 单次请求上限 |
| `progress_label` | 命令行进度展示字段 |

原则：

1. 一个数据集一个策略文件。
2. 不搞复杂 provider 抽象。
3. 板块池、指数池等逻辑在对应数据集策略中明确实现。
4. 通用 helper 只保留少量高确定性能力。

---

## 5. 通用 helper

只保留少量通用 helper，避免把实现重新推向过度抽象。

### 5.1 交易日 helper

来源：

```text
manifest/trading_calendar/tushare_trade_cal.parquet
```

能力：

1. 按自然日期区间筛选开市交易日。
2. 判断某日是否开市。
3. 找每周最后一个交易日。
4. 找每月最后一个交易日。

禁止：

1. 查询远程 DB 的交易日历。
2. 请求生产 API。

### 5.2 分页 helper

能力：

1. 按 `limit` / `offset` 循环。
2. 直到返回行数 `< limit` 停止。
3. 每页输出进度。
4. 每页请求受全局 Tushare 限速控制。

### 5.3 枚举扇出 helper

能力：

1. 用户传入多值枚举时，按字段笛卡尔组合生成请求。
2. 用户未传枚举时，按数据集默认口径决定是否传参。
3. 不把多个枚举值拼成一个字段传给 Tushare。

### 5.4 参数格式化 helper

能力：

1. `date -> YYYYMMDD`
2. `month -> YYYYMM`
3. `datetime -> YYYY-MM-DD HH:MM:SS`
4. Tushare 字段名格式统一。

---

## 6. 存储布局建议

### 6.1 快照类

适用：

1. `stock_basic`
2. `index_basic`
3. `etf_basic`
4. `hk_basic`
5. `us_basic`
6. `ths_index`
7. `etf_index`

路径：

```text
raw_tushare/<dataset_key>/current/part-000.parquet
```

写入策略：

```text
replace_file
```

### 6.2 日频类

适用：

1. `daily`
2. `adj_factor`
3. `daily_basic`
4. `fund_daily`
5. `fund_adj`
6. `moneyflow`
7. `margin`
8. `limit_list_d`
9. `stk_limit`

路径：

```text
raw_tushare/<dataset_key>/trade_date=YYYY-MM-DD/part-000.parquet
```

写入策略：

```text
replace_partition
```

### 6.3 月份键类

适用：

1. `broker_recommend`

路径：

```text
raw_tushare/<dataset_key>/month=YYYY-MM/part-000.parquet
```

写入策略：

```text
replace_partition
```

### 6.4 自然日公告类

适用：

1. `dividend`
2. `stk_holdernumber`
3. 部分新闻类数据集

路径：

```text
raw_tushare/<dataset_key>/<date_field>=YYYY-MM-DD/part-000.parquet
```

写入策略：

```text
replace_partition
```

### 6.5 月度窗口类

适用：

1. `index_weight`

路径：

```text
raw_tushare/<dataset_key>/month=YYYY-MM/part-000.parquet
```

写入策略：

```text
replace_partition
```

说明：

`index_weight` 的接口输入是月初自然日到月末自然日，不是月末交易日。

### 6.6 分钟线类

适用：

1. `stk_mins`

路径：

```text
raw_tushare/stk_mins_by_date/freq=<freq>/trade_date=YYYY-MM-DD/*.parquet
derived/stk_mins_by_date/freq=90|120/trade_date=YYYY-MM-DD/*.parquet
research/stk_mins_by_symbol_month/freq=<freq>/trade_month=YYYY-MM/bucket=<bucket>/*.parquet
```

写入策略：

```text
replace_partition
rebuild_month
```

---

## 7. 数据集分批计划

### 7.1 M0：盘点与事实清单

目标：

1. 从当前 `DatasetDefinition` 导出数据集清单。
2. 标注每个数据集是否属于 Tushare。
3. 标注 Lake 可支持性。
4. 标注请求策略、分区策略、写入策略、依赖 manifest。
5. 标注暂缓原因。

产物：

```text
docs/architecture/local-lake-dataset-sync-expansion-plan-v1.md
lake_console/backend/app/catalog/datasets/*.py
```

验收：

1. 清单覆盖当前数据基座支持的数据集。
2. 不把 BIYING 数据集混入 Tushare Lake 第一批。
3. 不把生产 DB 依赖写入 Lake 策略。

### 7.2 M1：通用 Lake 同步骨架

目标：

1. 新增 Lake Dataset Catalog。
2. 新增通用 sync engine。
3. 新增 `lake-console plan-sync <dataset_key>`。
4. 新增 `lake-console sync-dataset <dataset_key>`。
5. 保留现有 `sync-stock-basic`、`sync-trade-cal`、`sync-stk-mins-range` 作为明确命令或别名。

验收：

1. `plan-sync` 不发请求，只打印请求数量、分区数量、预估写入路径。
2. `sync-dataset` 支持进度输出。
3. 不访问远程 DB。
4. 写入仍走 `_tmp -> validate -> replace`。

### 7.3 M2：基础资料与快照类

优先数据集：

| 数据集 | 请求策略 | 写入策略 |
|---|---|---|
| `stock_basic` | 已实现 | `replace_file` |
| `trade_cal` | 已实现 | `replace_file` + manifest |
| `index_basic` | 快照分页 | `replace_file` |
| `etf_basic` | 快照分页 | `replace_file` |
| `hk_basic` | 快照分页 | `replace_file` |
| `us_basic` | 快照分页 | `replace_file` |
| `ths_index` | 快照分页 | `replace_file` |
| `etf_index` | 快照分页 | `replace_file` |

验收：

1. 每个数据集能单独同步。
2. 每个数据集能被 `list-datasets` 扫描到。
3. 每个 current 文件能被 DuckDB 读取。

### 7.4 M3：简单日频类

优先数据集：

| 数据集 | 请求策略 | 写入策略 |
|---|---|---|
| `daily` | 按交易日分页 | `replace_partition` |
| `adj_factor` | 按交易日分页 | `replace_partition` |
| `daily_basic` | 按交易日分页 | `replace_partition` |
| `fund_daily` | 按交易日分页 | `replace_partition` |
| `fund_adj` | 按交易日分页 | `replace_partition` |
| `margin` | 按交易日分页 | `replace_partition` |
| `moneyflow` | 按交易日分页 | `replace_partition` |

验收：

1. 支持单日同步。
2. 支持区间同步，区间由本地 `trade_cal` 展开。
3. 每个交易日独立替换，不因为某日失败影响其他日期。

### 7.5 M4：榜单、涨跌停与行情扩展

候选数据集：

| 数据集 | 请求策略 | 写入策略 |
|---|---|---|
| `limit_list_d` | 按交易日分页 | `replace_partition` |
| `limit_list_ths` | 按交易日分页 | `replace_partition` |
| `stk_limit` | 按交易日分页 | `replace_partition` |
| `limit_step` | 按交易日分页 | `replace_partition` |
| `limit_cpt_list` | 按交易日分页 | `replace_partition` |
| `top_list` | 按交易日分页 | `replace_partition` |
| `block_trade` | 按交易日分页 | `replace_partition` |
| `cyq_perf` | 按交易日分页 | `replace_partition` |
| `stk_nineturn` | 按交易日分页 | `replace_partition` |
| `suspend_d` | 按交易日分页 | `replace_partition` |
| `stk_factor_pro` | 按交易日分页 | `replace_partition` |

验收：

1. 每个数据集单独策略文件。
2. 不共享不清晰的特殊逻辑。
3. 大表必须分页写入，避免内存堆积。

### 7.6 M5：板块与热榜类

候选数据集：

| 数据集 | 请求策略 | 写入策略 |
|---|---|---|
| `dc_index` | 按日期或快照分页，以源文档为准 | `replace_partition` 或 `replace_file` |
| `dc_member` | 按时间参数分页，不按板块代码扇出 | `replace_partition` |
| `dc_daily` | 按交易日分页 | `replace_partition` |
| `dc_hot` | 按交易日 + 多值枚举组合分页 | `replace_partition` |
| `ths_index` | 已在快照批处理 | `replace_file` |
| `ths_member` | 无时间参数，直接分页 | `replace_file` |
| `ths_daily` | 按交易日分页 | `replace_partition` |
| `ths_hot` | 按交易日 + 多值枚举组合分页 | `replace_partition` |
| `kpl_list` | 按交易日 + 多值枚举组合分页 | `replace_partition` |
| `kpl_concept_cons` | 按交易日分页 | `replace_partition` |

验收：

1. 多值枚举必须扇出，不允许把多个值拼进一个字段。
2. 未传枚举参数时遵守源接口默认行为。
3. 不能读取生产板块池表。

### 7.7 M6：资金流全族

候选数据集：

| 数据集 | 请求策略 | 写入策略 |
|---|---|---|
| `moneyflow` | 已在简单日频批处理 | `replace_partition` |
| `moneyflow_ths` | 按交易日分页 | `replace_partition` |
| `moneyflow_dc` | 按交易日分页 | `replace_partition` |
| `moneyflow_cnt_ths` | 按交易日分页 | `replace_partition` |
| `moneyflow_ind_ths` | 按交易日分页 | `replace_partition` |
| `moneyflow_ind_dc` | content_type 枚举扇出 + 分页 | `replace_partition` |
| `moneyflow_mkt_dc` | 按交易日分页 | `replace_partition` |

验收：

1. 每个接口按源文档单次上限设置 `limit`。
2. 每个枚举字段明确是否允许多选，若多选必须扇出。
3. 不再引入多源融合逻辑；Lake 存源数据事实。

### 7.8 M7：低频、月度与周月线

候选数据集：

| 数据集 | 请求策略 | 写入策略 |
|---|---|---|
| `dividend` | 上层日期区间按自然日展开传 `ann_date` | `replace_partition` |
| `stk_holdernumber` | 上层日期区间按自然日展开传 `ann_date` | `replace_partition` |
| `index_weight` | 按自然月窗口请求 | `replace_partition` |
| `broker_recommend` | 按 `month=YYYYMM` 请求 | `replace_partition` |
| `index_weekly` | 按周最后交易日请求 | `replace_partition` |
| `index_monthly` | 按月最后交易日请求 | `replace_partition` |
| `stk_period_bar_week` | 固定周线实体策略 | `replace_partition` |
| `stk_period_bar_month` | 固定月线实体策略 | `replace_partition` |
| `stk_period_bar_adj_week` | 固定周线复权实体策略 | `replace_partition` |
| `stk_period_bar_adj_month` | 固定月线复权实体策略 | `replace_partition` |

验收：

1. 周/月锚点由本地交易日历计算。
2. `index_weight` 使用自然月首尾，不误当作月末交易日。
3. 周线/月线实体固定参数，不向用户暴露 `freq`。

### 7.9 M8：新闻类与非 Tushare 数据源

候选数据集：

1. `news`
2. `cctv_news`
3. `major_news`
4. BIYING 数据源

策略：

1. 先不纳入第一轮 Tushare Lake 扩展主线。
2. 新闻类需要单独确认本地研究价值、字段量、去重键、分页策略。
3. BIYING 数据源需要单独配置 token、限速和 source adapter。

---

## 8. 命令行建议

### 8.1 计划预览

```bash
lake-console plan-sync daily \
  --start-date 2026-04-01 \
  --end-date 2026-04-30
```

输出：

1. 数据集。
2. 请求数量。
3. 日期数量。
4. 枚举组合数量。
5. 预计写入分区。
6. 是否需要本地 manifest。
7. 是否可能触发大量请求。

### 8.2 通用同步

```bash
lake-console sync-dataset daily \
  --start-date 2026-04-01 \
  --end-date 2026-04-30
```

### 8.3 特殊同步保留明确命令

`stk_mins` 继续保留专用命令：

```bash
lake-console sync-stk-mins-range \
  --all-market \
  --freqs 1,5,15,30,60 \
  --start-date 2026-04-01 \
  --end-date 2026-04-30
```

原因：

1. 参数复杂。
2. 数据量巨大。
3. 进度展示和写入路径特殊。
4. 有派生层和 research 层。

### 8.4 命令示例 / 操作提示页面

Lake Console 前端应新增一个只读的“命令示例 / 操作提示”页面。

详细技术方案见 [Local Lake 命令示例页面技术方案 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-command-examples-page-plan-v1.md)。

该页面不触发写入，不启动后台任务，只根据 Lake Dataset Catalog 展示命令模板。

页面交互：

1. 第一个下拉框：选择展示分组。
2. 第二个下拉框：选择数据集。
3. 下方展示该数据集支持的命令例子。
4. 命令例子按使用场景分组，例如初始化、单日同步、区间同步、派生、research 重排、清理临时目录。

分组来源：

```text
lake_console/backend/app/catalog/view_groups.py
```

分组口径参考 [Ops 数据集展示目录配置方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-dataset-catalog-view-plan-v1.md) 第 10 节目标展示分组。

命令示例来源：

```text
Lake Dataset Catalog
  -> supported_commands
  -> command_examples
```

示例对象：

```json
{
  "dataset_key": "stk_mins",
  "command_examples": [
    {
      "title": "同步全市场分钟线区间",
      "description": "按本地交易日历展开交易日，写入 raw_tushare/stk_mins_by_date。",
      "command": "lake-console sync-stk-mins-range --all-market --freqs 1,5,15,30,60 --start-date 2026-04-01 --end-date 2026-04-30"
    },
    {
      "title": "重建 research 月分区",
      "description": "把 by_date 数据重排为 by_symbol_month，适合单股长周期回测。",
      "command": "lake-console rebuild-stk-mins-research --freq 30 --trade-month 2026-04"
    }
  ]
}
```

设计原则：

1. 页面只展示命令，不执行命令。
2. 前端不手写 dataset_key 到命令的映射。
3. 新增数据集时必须在 catalog 中补齐命令示例。
4. 命令示例必须与真实 CLI 参数保持一致。
5. 不把生产 Ops 手动任务、自动任务、TaskRun 入口混入该页面。

---

## 9. `stk_mins` 文件规模估算

当前代码默认：

```text
part_rows = 500000
compression = zstd
layout = raw_tushare/stk_mins_by_date/freq=<freq>/trade_date=<date>/part-xxxxx.parquet
```

当前配置指向的 Lake Root 下没有现存 `raw_tushare/stk_mins_by_date/*.parquet`，因此本节为估算，不是实测值。

估算前提：

| 项 | 估算值 |
|---|---:|
| 股票数 | 5500 |
| 交易日 / 年 | 244 |
| 10 年交易日 | 2440 |
| 1 分钟 bar / 股票 / 日 | 240 |
| 5 分钟 bar / 股票 / 日 | 48 |
| 15 分钟 bar / 股票 / 日 | 16 |
| 30 分钟 bar / 股票 / 日 | 9 |
| 60 分钟 bar / 股票 / 日 | 4 |

单日全市场行数估算：

| freq | 行数 / 日 | 按 500000 行切分后的文件数 / 日 |
|---:|---:|---:|
| 1 | 1,320,000 | 3 |
| 5 | 264,000 | 1 |
| 15 | 88,000 | 1 |
| 30 | 49,500 | 1 |
| 60 | 22,000 | 1 |
| 合计 | 1,743,500 | 7 |

10 年文件数估算：

```text
7 files/day * 2440 trading days = 17080 files
```

单个文件大小估算：

1. 满 `500000` 行的 part 文件，zstd 压缩后大致可能在 `25MB ~ 75MB`。
2. 低频度文件因为行数少，单文件可能远小于 `10MB`。
3. 真实大小受股票代码重复度、时间戳编码、价格精度、成交量数值范围和 Parquet 编码影响。

风险判断：

1. `17080` 个文件对移动硬盘和 DuckDB 来说更稳，仍需要在页面上提示“小文件风险”。
2. 当前 `part_rows=500000` 是 `stk_mins` 专用默认值，不作为所有 Lake 数据集的全局默认。
3. 后续如果实测单文件长期低于 `8MB`，可以评审继续调大到 `1000000`。
4. 继续调大 `part_rows` 前必须评估内存占用和失败重跑成本。

---

## 10. 门禁

每新增一个 Lake 数据集必须满足：

1. 有 Lake Dataset Catalog 定义。
2. 有独立策略文件。
3. 有 `plan-sync` 输出。
4. 有最小单日或 current 同步验证。
5. 有 DuckDB 读取验证。
6. 写入必须使用 `_tmp -> validate -> replace`。
7. 不访问远程 DB。
8. 不 import `src/ops/**`、生产 `src/app/**`、生产 `frontend/src/**`。
9. 长任务必须有进度输出。
10. 大表必须分页写入，不能把整任务全量堆到内存后再写。

建议新增测试：

| 测试 | 目的 |
|---|---|
| `test_lake_catalog.py` | catalog 字段完整性 |
| `test_lake_sync_plan.py` | `plan-sync` 请求计划正确 |
| `test_lake_no_remote_db_dependency.py` | 禁止远程 DB / Ops 依赖 |
| `test_lake_parquet_replace.py` | 临时写入与原子替换 |
| `test_lake_tushare_rate_limit.py` | 限速配置生效 |
| `test_lake_strategy_<dataset>.py` | 数据集策略请求参数与分区口径 |

---

## 11. 风险与防护

### 10.1 误用生产依赖

风险：

Lake 为了省事直接 import 生产 DAO、TaskRun 或 Ops 查询，破坏隔离。

防护：

1. 增加 import guardrail 测试。
2. `lake_console/AGENTS.md` 明确禁止。
3. Lake catalog 独立维护或由审计脚本生成快照，不运行生产同步代码。

### 10.2 分区策略不适合查询

风险：

所有数据集都简单按日期切，可能导致后续查询效率差。

防护：

1. 每个数据集定义 `primary_layout`。
2. 大体量数据集允许增加 research layout。
3. 先用 `stk_mins` 验证 by_date + research 双布局。

### 10.3 请求过慢

风险：

全市场、长区间、多频度数据集请求量巨大。

防护：

1. `plan-sync` 先显示请求量。
2. 配置最大窗口。
3. 全局 Tushare 限速。
4. 大任务进度只刷新关键行，不刷屏。

### 10.4 写入中断产生脏文件

风险：

中断后正式分区被半写覆盖。

防护：

1. 所有写入必须走 `_tmp`。
2. 校验通过后才替换。
3. 失败保留 `_tmp/{run_id}`。
4. 提供 `clean-tmp --dry-run`。

---

## 12. 建议下一步

建议先不要直接开发全部数据集。

下一步只做 M0 + M1 的最小闭环：

1. 从当前 `DatasetDefinition` 导出 Lake 支持性清单。
2. 建立 Lake Dataset Catalog 模型。
3. 建立 `plan-sync`。
4. 选 3 个代表数据集验证：
   - `index_basic`：快照类。
   - `daily`：日频交易日分区类。
   - `moneyflow`：日频分页类。

这 3 个跑通后，再按 M2-M8 分批扩展。
