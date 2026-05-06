# 资金流 6+1 Lake prod-raw-db 统一导出方案

状态：已落地（2026-05-06）

当前实现状态：

1. `moneyflow` 已从 Tushare 直连迁移到 `prod-raw-db`。
2. `moneyflow_ths / moneyflow_dc / moneyflow_cnt_ths / moneyflow_ind_ths / moneyflow_ind_dc / moneyflow_mkt_dc`
   已全部接入 `prod-raw-db` 日分区主线。
3. 已知源站缺口已纳入 `source_gap` 规则，不写空分区、不覆盖已有分区。

本文定义资金流 6+1 数据集统一接入本地 Lake 的方案。范围包括：

- `moneyflow`
- `moneyflow_ths`
- `moneyflow_dc`
- `moneyflow_cnt_ths`
- `moneyflow_ind_ths`
- `moneyflow_ind_dc`
- `moneyflow_mkt_dc`

这批数据集的共同目标是：

1. 统一改为从生产 `raw_tushare.*` 只读导出。
2. 统一按 `trade_date` 分区写入本地 Lake。
3. 统一只保留源站输出字段白名单。
4. 统一把已知源站缺口记录为事实，不伪造空分区。

本方案覆盖 Lake 接入设计，不改变生产同步主链。

## 1. 当前结论

### 1.1 时间模型结论

这 7 个数据集在生产 `DatasetDefinition` 中的时间模型一致，均为：

- `date_axis = trade_open_day`
- `bucket_rule = every_open_day`
- `window_mode = point_or_range`
- `input_shape = trade_date_or_start_end`

因此，从 Lake 角度可以统一建模为：

1. 单点模式：`--trade-date`
2. 区间模式：`--start-date --end-date`
3. 正式分区字段：`trade_date`

### 1.2 读取来源结论

本批数据集统一走：

```text
prod-raw-db
```

只允许读取：

```text
raw_tushare.moneyflow*
```

不再继续扩资金流家族的 Tushare 直连下载实现。

`moneyflow` 早期曾以 Tushare 直连版本接入 Lake；当前已完成迁移，现行主线也是：

- `--from prod-raw-db`

并与其余 6 个资金流数据集统一。

### 1.3 完备性结论（2026-05-06 审计）

| dataset_key | 生产表 | 行数 | 时间范围 | 交易日覆盖 | 当前结论 |
| --- | --- | ---: | --- | --- | --- |
| `moneyflow` | `raw_tushare.moneyflow` | `13534780` | `2010-01-04 ~ 2026-04-30` | `3963 / 3963` | 完整 |
| `moneyflow_ths` | `raw_tushare.moneyflow_ths` | `1664055` | `2024-12-19 ~ 2026-04-30` | `329 / 329` | 完整 |
| `moneyflow_dc` | `raw_tushare.moneyflow_dc` | `3671775` | `2023-09-11 ~ 2026-04-30` | `635 / 636` | 源站缺 `2023-11-22` |
| `moneyflow_cnt_ths` | `raw_tushare.moneyflow_cnt_ths` | `152343` | `2024-09-10 ~ 2026-04-30` | `392 / 394` | 源站缺 `2024-11-04`、`2025-01-20` |
| `moneyflow_ind_ths` | `raw_tushare.moneyflow_ind_ths` | `35280` | `2024-09-10 ~ 2026-04-30` | `392 / 394` | 源站缺 `2024-11-04`、`2025-01-20` |
| `moneyflow_ind_dc` | `raw_tushare.moneyflow_ind_dc` | `257529` | `2023-09-12 ~ 2026-04-30` | `635 / 635` | 完整 |
| `moneyflow_mkt_dc` | `raw_tushare.moneyflow_mkt_dc` | `736` | `2023-04-17 ~ 2026-04-30` | `736 / 736` | 完整 |

由此，本批可以分为两类：

1. 可直接接入：
   - `moneyflow`
   - `moneyflow_ths`
   - `moneyflow_ind_dc`
   - `moneyflow_mkt_dc`
2. 带已知源站缺口接入：
   - `moneyflow_dc`
   - `moneyflow_cnt_ths`
   - `moneyflow_ind_ths`

---

## 2. 统一接入规则

### 2.1 输入参数规则

本批第一阶段统一只支持：

- `--trade-date`
- `--start-date --end-date`

第一阶段统一不支持：

- `--ts-code`
- `--content-type`
- 其他对象过滤参数

原因很简单：

1. Lake 正式布局是某交易日全量资金流事实。
2. 局部筛选结果不能覆盖正式 `trade_date` 分区。
3. 若后续需要调试型子集导出，应单独设计 debug/export 命令，不污染正式 raw 分区。

### 2.2 输出字段规则

统一遵守：

1. Lake raw 层字段集合必须等于源站输出字段白名单。
2. 只允许读取业务字段白名单，禁止 `select *`。
3. 禁止带入：
   - `api_name`
   - `fetched_at`
   - `raw_payload`
4. 所有 `trade_date` 一律写为 Parquet `date`。
5. 数值字段统一按 DuckDB 友好的 `double / int64 / int32 / string` 落盘。

### 2.3 存储布局规则

统一路径：

```text
raw_tushare/<dataset_key>/trade_date=YYYY-MM-DD/part-000.parquet
```

统一策略：

- `write_policy = replace_partition`
- `_tmp -> validate -> replace`

统一不做：

- `manifest` 双落盘
- `derived`
- `research`

### 2.4 空结果与缺口规则

本批必须统一处理“已知源站缺口”。

规则：

1. 如果某个应有交易日查询结果为 0：
   - 不写空分区
   - 不覆盖已有分区
2. 如果该日期属于已确认的源站缺口：
   - 记录为 `source_gap`
   - 不当作 Lake 同步逻辑错误
3. 如果该日期不在已知缺口清单中：
   - 记录为异常
   - 后续需要二次审计

第一版明确写入方案中的已知源站缺口：

| dataset_key | 已知缺口 |
| --- | --- |
| `moneyflow_dc` | `2023-11-22` |
| `moneyflow_cnt_ths` | `2024-11-04`、`2025-01-20` |
| `moneyflow_ind_ths` | `2024-11-04`、`2025-01-20` |

---

## 3. 字段白名单与类型

### 3.1 `moneyflow`

来源：

- 源站：Tushare `moneyflow`
- 生产表：`raw_tushare.moneyflow`

白名单字段：

- `ts_code`
- `trade_date`
- `buy_sm_vol`
- `buy_sm_amount`
- `sell_sm_vol`
- `sell_sm_amount`
- `buy_md_vol`
- `buy_md_amount`
- `sell_md_vol`
- `sell_md_amount`
- `buy_lg_vol`
- `buy_lg_amount`
- `sell_lg_vol`
- `sell_lg_amount`
- `buy_elg_vol`
- `buy_elg_amount`
- `sell_elg_vol`
- `sell_elg_amount`
- `net_mf_vol`
- `net_mf_amount`

真实类型（生产表）：

- `trade_date`: `date`
- `*_vol`: `bigint`
- `*_amount`: `numeric`

Lake 类型：

- `trade_date -> date`
- `*_vol -> int64`
- `*_amount -> double`

### 3.2 `moneyflow_ths`

来源：

- 源站：Tushare `moneyflow_ths`
- 生产表：`raw_tushare.moneyflow_ths`

白名单字段：

- `trade_date`
- `ts_code`
- `name`
- `pct_change`
- `latest`
- `net_amount`
- `net_d5_amount`
- `buy_lg_amount`
- `buy_lg_amount_rate`
- `buy_md_amount`
- `buy_md_amount_rate`
- `buy_sm_amount`
- `buy_sm_amount_rate`

真实类型（生产表）：

- `trade_date`: `date`
- `name`: `varchar`
- 其余数值字段：`numeric`

Lake 类型：

- `trade_date -> date`
- `name/ts_code -> string`
- 数值字段 -> `double`

### 3.3 `moneyflow_dc`

来源：

- 源站：Tushare `moneyflow_dc`
- 生产表：`raw_tushare.moneyflow_dc`

白名单字段：

- `trade_date`
- `ts_code`
- `name`
- `pct_change`
- `close`
- `net_amount`
- `net_amount_rate`
- `buy_elg_amount`
- `buy_elg_amount_rate`
- `buy_lg_amount`
- `buy_lg_amount_rate`
- `buy_md_amount`
- `buy_md_amount_rate`
- `buy_sm_amount`
- `buy_sm_amount_rate`

真实类型（生产表）：

- `trade_date`: `date`
- `name/ts_code`: `varchar`
- 数值字段：`numeric`

Lake 类型：

- `trade_date -> date`
- `name/ts_code -> string`
- 数值字段 -> `double`

### 3.4 `moneyflow_cnt_ths`

来源：

- 源站：Tushare `moneyflow_cnt_ths`
- 生产表：`raw_tushare.moneyflow_cnt_ths`

白名单字段：

- `trade_date`
- `ts_code`
- `name`
- `lead_stock`
- `close_price`
- `pct_change`
- `industry_index`
- `company_num`
- `pct_change_stock`
- `net_buy_amount`
- `net_sell_amount`
- `net_amount`

真实类型（生产表）：

- `trade_date`: `date`
- `company_num`: `integer`
- `name/lead_stock/ts_code`: `varchar`
- 其余数值字段：`numeric`

Lake 类型：

- `trade_date -> date`
- `company_num -> int32`
- 名称与代码字段 -> `string`
- 数值字段 -> `double`

### 3.5 `moneyflow_ind_ths`

来源：

- 源站：Tushare `moneyflow_ind_ths`
- 生产表：`raw_tushare.moneyflow_ind_ths`

白名单字段：

- `trade_date`
- `ts_code`
- `industry`
- `lead_stock`
- `close`
- `pct_change`
- `company_num`
- `pct_change_stock`
- `close_price`
- `net_buy_amount`
- `net_sell_amount`
- `net_amount`

真实类型（生产表）：

- `trade_date`: `date`
- `company_num`: `integer`
- `industry/lead_stock/ts_code`: `varchar`
- 其余数值字段：`numeric`

Lake 类型：

- `trade_date -> date`
- `company_num -> int32`
- 名称与代码字段 -> `string`
- 数值字段 -> `double`

### 3.6 `moneyflow_ind_dc`

来源：

- 源站：Tushare `moneyflow_ind_dc`
- 生产表：`raw_tushare.moneyflow_ind_dc`

白名单字段：

- `trade_date`
- `content_type`
- `name`
- `ts_code`
- `pct_change`
- `close`
- `net_amount`
- `net_amount_rate`
- `buy_elg_amount`
- `buy_elg_amount_rate`
- `buy_lg_amount`
- `buy_lg_amount_rate`
- `buy_md_amount`
- `buy_md_amount_rate`
- `buy_sm_amount`
- `buy_sm_amount_rate`
- `buy_sm_amount_stock`
- `rank`

真实类型（生产表）：

- `trade_date`: `date`
- `rank`: `integer`
- `content_type/name/ts_code/buy_sm_amount_stock`: `varchar`
- 其余数值字段：`numeric`

Lake 类型：

- `trade_date -> date`
- `rank -> int32`
- 字符串字段 -> `string`
- 数值字段 -> `double`

### 3.7 `moneyflow_mkt_dc`

来源：

- 源站：Tushare `moneyflow_mkt_dc`
- 生产表：`raw_tushare.moneyflow_mkt_dc`

白名单字段：

- `trade_date`
- `close_sh`
- `pct_change_sh`
- `close_sz`
- `pct_change_sz`
- `net_amount`
- `net_amount_rate`
- `buy_elg_amount`
- `buy_elg_amount_rate`
- `buy_lg_amount`
- `buy_lg_amount_rate`
- `buy_md_amount`
- `buy_md_amount_rate`
- `buy_sm_amount`
- `buy_sm_amount_rate`

真实类型（生产表）：

- `trade_date`: `date`
- 其余数值字段：`numeric`

Lake 类型：

- `trade_date -> date`
- 数值字段 -> `double`

---

## 4. 实现顺序建议

### 4.1 R4-A：先打通统一链路

建议先做这 4 个：

1. `moneyflow`
2. `moneyflow_ths`
3. `moneyflow_ind_dc`
4. `moneyflow_mkt_dc`

原因：

1. 这 4 个当前完备性最好。
2. 可以先把 `moneyflow` 从 Tushare 直连切到 `prod-raw-db`。
3. 可以先把 Lake 资金流家族的统一 catalog / planner / strategy / exporter 模板稳定下来。

### 4.2 R4-B：再接带源站缺口的 3 个

再做：

1. `moneyflow_dc`
2. `moneyflow_cnt_ths`
3. `moneyflow_ind_ths`

共同要求：

1. 实现“已知源站缺口不写空分区”的规则。
2. 把缺口提示做进同步结果或计划输出。
3. 不把这些缺口解释成程序故障。

---

## 5. 命令设计

统一命令入口：

```bash
lake-console plan-sync <dataset_key> --from prod-raw-db --trade-date YYYY-MM-DD
lake-console sync-dataset <dataset_key> --from prod-raw-db --trade-date YYYY-MM-DD
lake-console plan-sync <dataset_key> --from prod-raw-db --start-date YYYY-MM-DD --end-date YYYY-MM-DD
lake-console sync-dataset <dataset_key> --from prod-raw-db --start-date YYYY-MM-DD --end-date YYYY-MM-DD
```

本批不设计专用命令。

统一不支持：

- `--ts-code`
- `--content-type`
- 其他对象过滤参数

作为正式写入命令参数。

---

## 6. 验收口径

1. 7 个数据集全部改为 `prod-raw-db` 只读导出。
2. `moneyflow` 的 Tushare 直连实现退场，不再作为长期主线。
3. 7 个数据集的 Lake raw 分区全部使用：

```text
raw_tushare/<dataset_key>/trade_date=YYYY-MM-DD/part-000.parquet
```

4. Parquet 内部 `trade_date` 必须是 `date`。
5. 任何数据集都不得带入：
   - `api_name`
   - `fetched_at`
   - `raw_payload`
6. 带缺口数据集不得生成空分区，不得覆盖旧分区。
7. 已知缺口必须可解释。

---

## 7. 当前需要特别盯住的点

1. `moneyflow` 已经在 Lake 中存在旧的 Tushare 直连实现，迁移时必须先明确：
   - catalog
   - 命令示例
   - strategy
   - 文档
   都要收敛到 `prod-raw-db`
2. `moneyflow_cnt_ths`、`moneyflow_ind_ths` 虽然都可接入，但必须带“源站缺口事实”规则。
3. `moneyflow_ind_dc` 的 `content_type` 只是业务字段，不是第一阶段用户输入参数。
