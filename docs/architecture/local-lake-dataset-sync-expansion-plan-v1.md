# Local Lake 数据集同步扩展方案 v1

- 版本：v1
- 状态：已部分落地；主路线已切换为“`prod-raw-db` 只读导出优先，Tushare 直连补充”
- 更新时间：2026-05-07
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
2. 本地配置 `GOLDENSHARE_LAKE_ROOT`、`TUSHARE_TOKEN` 和 `prod_raw_db_url`。
3. Tushare 请求限速。
4. Parquet 写入。
5. `_tmp -> 校验 -> 替换正式文件/分区`。
6. `stock_basic`、`trade_cal` 双落盘。
7. `stk_mins` 原始层、派生层、research 层。
8. CLI / Planner / Engine 已收口为分组命令、分类 planner 与 dataset strategy。
9. Lake 已从首批 6 个数据集扩展到 32 个数据集，覆盖参考数据、日频行情、资金流、ETF、板块与榜单的多个批次。
10. `daily` 已验证可以通过 `prod-raw-db` 只读导出，且速度明显优于重新请求 Tushare。

当前生产侧共有 `60` 个 `DatasetDefinition`，其中：

1. `58` 个落在 `raw_tushare.*`，理论上都可以评估接入本地 Tushare Lake。
2. `2` 个是 `BIYING` 数据源（`biying_equity_daily`、`biying_moneyflow`），不纳入当前 Tushare Lake 主线。
3. 当前 Lake 已落地 `32 / 58` 个 `raw_tushare` 数据集，剩余 `26` 个待规划。

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

### 2.3 主路线切换：默认优先 `prod-raw-db` 只读导出

在 `daily` 验证通过后，Lake 的主路线应调整为：

```text
默认优先：prod-raw-db 只读导出 raw_tushare 白名单表
例外保留：Tushare 直连下载
```

原因：

1. 生产库 `raw_tushare.*` 已经承载了源站事实，重复请求 Tushare 会浪费配额和时间。
2. 很多原本在源站 API 侧很复杂的数据集，切到 prod-raw-db 导出后，复杂度会从“如何请求”降为“如何安全切分导出和写 Parquet”。
3. 只读导出更适合全量回填、历史补湖和批量接入。
4. `prod-raw-db` 已有严格边界：只读、只准 `raw_tushare`、只准白名单表、只准字段白名单投影、禁止 `select *`。

仍保留 Tushare 直连的场景：

1. 本地 `manifest` 初始化或更新，例如股票池、交易日历。
2. 生产 raw 表尚未具备 Lake 需要的字段或口径。
3. 本地 `derived` / `research` 层重建。
4. 特大型数据集（如 `stk_mins`）在导出策略、字段口径或存储布局上仍有专项设计需要。

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
3. 不接入生产 TaskRun / Ops / Scheduler；`prod-raw-db` 只读导出是唯一远程数据库例外。
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

## 7. 数据集分批计划（2026-05-04 重排）

### 7.1 当前事实

当前以 `raw_tushare.*` 为范围统计：

| 项 | 数量 | 说明 |
|---|---:|---|
| 生产 `DatasetDefinition` 总数 | 60 | 含 BIYING |
| `raw_tushare` 数据集 | 58 | 当前 Tushare Lake 主线目标 |
| BIYING 数据集 | 2 | 暂不纳入本轮 |
| Lake 已落地 | 32 | 已覆盖参考数据、核心日频、资金流、ETF、板块与榜单多批次 |
| Lake 待接入 | 26 | 继续以 `prod-raw-db` 导出优先 |

### 7.2 新主线原则

从本轮开始，新增 Lake 数据集默认遵循以下判断顺序：

1. 先判断是否可以直接从 `raw_tushare.<table>` 只读导出。
2. 如果可以，优先走 `prod-raw-db`。
3. 只有在以下情况才保留 Tushare 直连：
   - 需要初始化本地 manifest。
   - 生产 raw 表字段或口径暂不满足 Lake 目标。
   - 本地 `derived` / `research` 重建。
   - 特大型专项（当前主要是 `stk_mins`）。

这意味着后续大部分数据集的复杂度不再是“怎么请求 Tushare”，而是：

1. 字段白名单如何和源文档对齐。
2. 从 `raw_tushare` 读出来后按什么分区写 Lake。
3. 是 `replace_file` 还是 `replace_partition`。
4. 如何做 DuckDB 友好的类型落盘。

### 7.3 R0：导出基线已完成

已完成能力：

1. `sync-dataset` 通用入口。
2. `plan-sync` 计划预览。
3. `prod-raw-db` 只读白名单框架。
4. `daily` 作为首个 `prod-raw-db` 验证样本。
5. 模板门禁已强制要求“读取 / 请求模式评审”。

这一阶段不再重复开发，后续批次直接复用。

### 7.4 R1：快照 / current 文件批

目标：先把最稳定、最容易验证、最适合 `replace_file` 的数据集补齐。

候选数据集：

| 数据集 | 原表 | Lake 布局 | 建议来源 |
|---|---|---|---|
| `etf_basic` | `raw_tushare.etf_basic` | `current_file` | `prod-raw-db` |
| `hk_basic` | `raw_tushare.hk_basic` | `current_file` | `prod-raw-db` |
| `us_basic` | `raw_tushare.us_basic` | `current_file` | `prod-raw-db` |
| `ths_index` | `raw_tushare.ths_index` | `current_file` | `prod-raw-db` |
| `ths_member` | `raw_tushare.ths_member` | `current_file` | `prod-raw-db` |
| `etf_index` | `raw_tushare.etf_index` | `current_file` | `prod-raw-db` |

说明：

1. `stock_basic`、`trade_cal`、`index_basic` 已完成，可作为这一批模板。
2. 这一批最适合先建立 `snapshot/current` 导出套路。
3. `ths_member` 虽然生产定义里没有时间输入，但导出 Lake 时就是 current 快照，不再受源接口请求方式影响。

### 7.5 R2：核心日频分区批

目标：补齐最常用的按日分区原始事实层。

候选数据集：

| 数据集 | 原表 | Lake 布局 | 建议来源 |
|---|---|---|---|
| `adj_factor` | `raw_tushare.adj_factor` | `trade_date` 分区 | `prod-raw-db` |
| `daily_basic` | `raw_tushare.daily_basic` | `trade_date` 分区 | `prod-raw-db` |
| `fund_daily` | `raw_tushare.fund_daily` | `trade_date` 分区 | `prod-raw-db` |
| `fund_adj` | `raw_tushare.fund_adj` | `trade_date` 分区 | `prod-raw-db` |
| `margin` | `raw_tushare.margin` | `trade_date` 分区 | `prod-raw-db` |
| `index_daily` | `core_serving.index_daily_serving` | `trade_date` 分区 | `prod-core-db` |
| `index_daily_basic` | `raw_tushare.index_daily_basic` | `trade_date` 分区 | `prod-raw-db` |
| `stk_limit` | `raw_tushare.stk_limit` | `trade_date` 分区 | `prod-raw-db` |
| `stock_st` | `raw_tushare.stock_st` | `trade_date` 分区 | `prod-raw-db` |
| `suspend_d` | `raw_tushare.suspend_d` | `trade_date` 分区 | `prod-raw-db` |

说明：

1. `daily`、`moneyflow` 已完成，可分别作为“价格类”和“成交 / 资金类”模板。
2. 这一批重点解决的是字段对齐、日期字段类型、区间流式导出和按日替换。
3. 对 Lake 来说，这一批已经不需要再解决源站分页组合问题。
4. `index_daily` 是唯一例外：按评审要求必须从 `core_serving.index_daily_serving` 读取，并映射回 Tushare 原始字段口径；不能继续按 `prod-raw-db` 处理。

当前进展（2026-05-06）：

- 已完成首批 4 个：
  - `adj_factor`
  - `daily_basic`
  - `index_daily_basic`
  - `index_daily`
- 其中：
  - `adj_factor`、`daily_basic`、`index_daily_basic` 已走通 `prod-raw-db`
  - `index_daily` 已作为 Lake 中首个正式 `prod-core-db` 模式走通
- 均已完成 `2026-04-30` 单日真实同步验证与 Parquet schema 校验

第二段（2026-05-06 已完成）：

- `fund_daily`
- `fund_adj`
- `margin`
- `stk_limit`
- `stock_st`
- `suspend_d`

第二段共同约束：

1. 继续统一走 `prod-raw-db`，不引入新的读取来源。
2. 统一写入 `raw_tushare/<dataset_key>/trade_date=YYYY-MM-DD/part-000.parquet`。
3. 第一阶段只支持 `--trade-date` 与 `--start-date/--end-date`。
4. 第一阶段禁止 `ts_code`、`exchange_id`、`suspend_type` 等局部筛选参数直接覆盖正式分区。
5. `suspend_d` 需要显式排除 `id`、`row_key_hash` 等 Goldenshare 自增字段，只保留源站输出字段白名单。
6. `stock_st` 当前生产 raw 历史起点是 `2016-08-09`，Lake 首版按生产事实落盘，不额外伪造更早日期分区。
7. 已完成 `2026-04-30` 单日真实同步验证；`trade_date` 均已验证写为 Parquet `date`，`suspend_d` 未带入 `id`、`row_key_hash` 等系统字段。

### 7.6 R3：榜单 / 板块 / 新闻日频批

目标：把“源站请求复杂、但 raw 导出其实很直观”的那批数据集吃掉。

当前状态（2026-05-08）：

1. `R3-A` 首批 6 个数据集已完成后端接入与单日真实同步验证：
   - `cyq_perf`
   - `limit_list_d`
   - `limit_list_ths`
   - `limit_step`
   - `limit_cpt_list`
   - `top_list`
2. `block_trade` 因当前生产 raw 存在精确重复问题，已按当前决策后置到最后一批，不纳入本轮方案。
3. `top_list` 已在最新重同步后重新审计：
   - 当前生产 raw 范围收敛为 `2016-01-04 ~ 2026-05-07`
   - 在该范围内交易日覆盖 `2509 / 2509`
   - 精确重复组为 `0`
   - 但 Lake 首版仍按当前生产事实起点 `2016-01-04` 落盘，不伪造更早历史分区。
4. `limit_list_ths` 已在最新重同步后重新审计：
   - 当前生产 raw 范围更新为 `2023-11-01 ~ 2026-04-30`
   - 在该范围内交易日覆盖 `605 / 605`
   - Lake 首版历史起点同步更新为 `2023-11-01`
5. `R3-B` 已完成重新审计，并拆成两波：
   - 第一波可先直接推进方案：
     - `dc_daily`
     - `dc_member`
     - `kpl_list`
     - `kpl_concept_cons`
   - 第二波需在方案中额外写明规则：
     - `dc_index`
     - `ths_daily`
     - `dc_hot`
     - `ths_hot`
6. `R3-B` 第一波当前最新事实：
   - `dc_daily`：`2026-01-05 ~ 2026-05-07`，开市日覆盖 `79 / 79`，无非交易日、无重复
   - `dc_member`：`2024-12-20 ~ 2026-05-07`，开市日覆盖 `330 / 330`，无非交易日、无重复
   - `kpl_list`：`2026-01-05 ~ 2026-05-07`，开市日覆盖 `79 / 79`，无非交易日、无重复
   - `kpl_concept_cons`：`2026-01-05 ~ 2026-05-07`，开市日覆盖 `79 / 79`，无非交易日、无重复
   - 以上四个数据集已于 `2026-05-08` 落地到 `lake_console`，并通过单日真实导出验证
7. `R3-B` 第二波当前最新事实：
   - `dc_index`：开市日覆盖完整，但混入 `2026-03-28`、`2026-03-29`、`2026-04-11`、`2026-04-12` 4 个非交易日
   - `ths_daily`：开市日覆盖完整，但历史上混入 `102` 个非交易日
   - `dc_hot`：开市日覆盖完整；若不保留 `market / hot_type / is_new`，会出现 `5` 组事实碰撞；升级后重复归零
   - `ths_hot`：开市日覆盖完整；后续同样需要把 `market / is_new` 作为事实字段保留
8. `R3-B` 第二波方案文档已落：
   - `dc_index`：`docs/datasets/dc-index-prod-raw-db-lake-export-plan.md`
   - `ths_daily`：`docs/datasets/ths-daily-prod-raw-db-lake-export-plan.md`
   - `dc_hot`：`docs/datasets/dc-hot-prod-raw-db-lake-export-plan.md`
   - `ths_hot`：`docs/datasets/ths-hot-prod-raw-db-lake-export-plan.md`
9. `R3-B` 第二波已于 `2026-05-08` 落地到 `lake_console`，并通过最小真实验证：
   - `dc_index`：跨 `2026-04-10 ~ 2026-04-12` 小区间导出成功，只生成 `2026-04-10` 开市日分区
   - `ths_daily`：跨 `2026-02-20 ~ 2026-02-24` 小区间导出成功，验证非交易日不会落成正式分区
   - `dc_hot`：`2026-05-07` 单日导出成功，Parquet 已保留 `market / hot_type / is_new`
   - `ths_hot`：`2026-05-07` 单日导出成功，Parquet 已保留 `market / is_new`
10. `R3-B` 第二波统一规则：
   - 所有 `trade_open_day` 数据集只允许对本地交易日历开市日生成正式分区
   - `dc_index / ths_daily` 的非交易日 raw 记录只允许留在源库，不得写成正式 Lake 分区
   - `dc_hot` 必须把 `market / hot_type / is_new` 升格为事实字段
   - `ths_hot` 必须把 `market / is_new` 升格为事实字段

候选数据集：

| 数据集 | 原表 | Lake 布局 | 建议来源 |
|---|---|---|---|
| `block_trade` | `raw_tushare.block_trade` | `trade_date` 分区 | `prod-raw-db` |
| `cyq_perf` | `raw_tushare.cyq_perf` | `trade_date` 分区 | `prod-raw-db` |
| `limit_list_d` | `raw_tushare.limit_list` | `trade_date` 分区 | `prod-raw-db` |
| `limit_list_ths` | `raw_tushare.limit_list_ths` | `trade_date` 分区 | `prod-raw-db` |
| `limit_step` | `raw_tushare.limit_step` | `trade_date` 分区 | `prod-raw-db` |
| `limit_cpt_list` | `raw_tushare.limit_cpt_list` | `trade_date` 分区 | `prod-raw-db` |
| `top_list` | `raw_tushare.top_list` | `trade_date` 分区 | `prod-raw-db` |
| `dc_daily` | `raw_tushare.dc_daily` | `trade_date` 分区 | `prod-raw-db` |
| `dc_hot` | `raw_tushare.dc_hot` | `trade_date` 分区 | `prod-raw-db` |
| `dc_index` | `raw_tushare.dc_index` | `trade_date` 分区 | `prod-raw-db` |
| `dc_member` | `raw_tushare.dc_member` | `trade_date` 分区 | `prod-raw-db` |
| `ths_daily` | `raw_tushare.ths_daily` | `trade_date` 分区 | `prod-raw-db` |
| `ths_hot` | `raw_tushare.ths_hot` | `trade_date` 分区 | `prod-raw-db` |
| `kpl_list` | `raw_tushare.kpl_list` | `trade_date` 分区 | `prod-raw-db` |
| `kpl_concept_cons` | `raw_tushare.kpl_concept_cons` | `trade_date` 分区 | `prod-raw-db` |
| `news` | `raw_tushare.news` | `trade_date` 分区 | `prod-raw-db` |
| `major_news` | `raw_tushare.major_news` | `trade_date` 分区 | `prod-raw-db` |
| `cctv_news` | `raw_tushare.cctv_news` | `trade_date` 分区 | `prod-raw-db` |

说明：

1. 这批在生产同步时往往最烦，因为源站参数多、枚举多、分页复杂。
2. 但一旦走 `prod-raw-db`，这些复杂度大部分已经被生产同步提前消化掉了。
3. 这一批的难点主要变成字段审计和合理的分区写入，不再是 API 编排。
4. `R3-A` 当前第一波只推进“榜单/涨停”这 6 个，不把 `block_trade` 混入。
5. `R3-B` 全部 `trade_open_day` 数据集都必须统一遵守：
   - 只对本地交易日历中的开市日生成正式分区
   - 非交易日记录即使存在于 raw，也不能写成正式 Lake 分区

### 7.7 R4：资金流全族

目标：把资金流家族统一收敛到 `prod-raw-db` 导出模式，并把当前 `moneyflow` 的 Tushare 直连实现迁移到同一条主线。

当前状态（2026-05-06）：

1. `moneyflow` 已迁移到 `prod-raw-db`。
2. `moneyflow_ths / moneyflow_dc / moneyflow_cnt_ths / moneyflow_ind_ths / moneyflow_ind_dc / moneyflow_mkt_dc`
   已全部接入 `trade_date` 分区导出。
3. `moneyflow_dc / moneyflow_cnt_ths / moneyflow_ind_ths` 的已知源站缺口已纳入 `source_gap` 规则。

候选数据集：

| 数据集 | 原表 | Lake 布局 | 建议来源 |
|---|---|---|---|
| `moneyflow` | `raw_tushare.moneyflow` | `trade_date` 分区 | `prod-raw-db` |
| `moneyflow_ths` | `raw_tushare.moneyflow_ths` | `trade_date` 分区 | `prod-raw-db` |
| `moneyflow_dc` | `raw_tushare.moneyflow_dc` | `trade_date` 分区 | `prod-raw-db` |
| `moneyflow_cnt_ths` | `raw_tushare.moneyflow_cnt_ths` | `trade_date` 分区 | `prod-raw-db` |
| `moneyflow_ind_ths` | `raw_tushare.moneyflow_ind_ths` | `trade_date` 分区 | `prod-raw-db` |
| `moneyflow_ind_dc` | `raw_tushare.moneyflow_ind_dc` | `trade_date` 分区 | `prod-raw-db` |
| `moneyflow_mkt_dc` | `raw_tushare.moneyflow_mkt_dc` | `trade_date` 分区 | `prod-raw-db` |

说明：

1. 这一批同属资金流向目录，适合在 CLI、前端分组、模板和测试里一起补齐。
2. `moneyflow` 当前 Lake 已落地，但还是 Tushare 直连；本批要求把它迁到 `prod-raw-db`，不再单独维护两套主链。
3. 重点不是请求，而是字段口径、Parquet 类型，以及已知源站缺口的处理规则。
4. 当前已确认的源站缺口：
   - `moneyflow_dc`：`2023-11-22`
   - `moneyflow_cnt_ths`：`2024-11-04`、`2025-01-20`
   - `moneyflow_ind_ths`：`2024-11-04`、`2025-01-20`

### 7.8 R5：低频 / 月份键 / 公告日批

目标：把日期模型不是 `trade_date` 的那批独立处理。

候选数据集：

| 数据集 | 原表 | Lake 分区字段 | 建议来源 |
|---|---|---|---|
| `dividend` | `raw_tushare.dividend` | `ann_date` | `prod-raw-db` |
| `stk_holdernumber` | `raw_tushare.holdernumber` | `ann_date` | `prod-raw-db` |
| `broker_recommend` | `raw_tushare.broker_recommend` | `month` | `prod-raw-db` |
| `index_weight` | `raw_tushare.index_weight` | `trade_month` 或 `month_window` | `prod-raw-db` |

说明：

1. 这批要重点审计分区字段，不要机械套 `trade_date`。
2. `index_weight` 仍需单独确认最适合的 Lake 分区语义。

### 7.9 R6：周月线 / 特殊宽表 / 专项批

目标：最后处理仍需专项评审的数据集。

候选数据集：

| 数据集 | 原表 | 备注 |
|---|---|---|
| `index_weekly` | `raw_tushare.index_weekly_bar` | 周线分区语义需先定 |
| `index_monthly` | `raw_tushare.index_monthly_bar` | 月线分区语义需先定 |
| `stk_period_bar_week` | `raw_tushare.stk_period_bar` | 周线实体 |
| `stk_period_bar_month` | `raw_tushare.stk_period_bar` | 月线实体 |
| `stk_period_bar_adj_week` | `raw_tushare.stk_period_bar_adj` | 周线复权实体 |
| `stk_period_bar_adj_month` | `raw_tushare.stk_period_bar_adj` | 月线复权实体 |
| `stk_factor_pro` | `raw_tushare.stk_factor_pro` | 宽表，字段和文件大小要单独评审 |
| `stk_nineturn` | `raw_tushare.stk_nineturn` | 需确认字段和分区是否直接按日即可 |

说明：

1. 这批不是不能做，而是应该在前几批模板稳定后再上。
2. `stk_factor_pro`、周月线类都更适合在文件布局、DuckDB 查询和文件大小上做专项设计。

### 7.10 R7：明确后置项

本轮继续后置：

1. `biying_equity_daily`
2. `biying_moneyflow`
3. `stk_mins` 的 prod-raw-db 导出化改造
4. 自动调度、后台写入按钮、任务恢复和取消能力

原因：

1. BIYING 不属于当前 Tushare Lake 主线。
2. `stk_mins` 已有独立 Tushare 直连与本地派生体系，不应与普通 raw 导出批次混做。
3. 写入型页面和任务系统属于更后面的交互层能力。

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

当前建议按以下顺序推进，不再回到“先按源站 API 复杂度排序”的旧思路：

1. 先补完 `R1` 快照 / current 文件批。
2. 再推进 `R2` 核心日频分区批。
3. 然后做 `R4` 资金流全族，因为模板与现有 `moneyflow` 最接近。
4. 再吃 `R3` 榜单 / 板块 / 新闻日频批。
5. 最后单独处理 `R5` 和 `R6` 的日期模型特殊项与专项大表。

理由：

1. `prod-raw-db` 导出已经证明可行，最该优先的是“能快速复制成功经验”的批次。
2. 快照类和核心日频类最容易形成稳定模板。
3. 后面的板块、新闻、低频、周月线，会分别卡在字段、分区语义或专项评审上，放后面更稳。
