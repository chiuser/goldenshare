# 神奇九转指标 Lake prod-raw-db 导出方案

> M5 清退边界（2026-09-05）：本文旧 Console 按日导出与 CLI 是历史实现记录；正式九转 prod 只读初始化和日常 Tushare 方案仍有效，以文首所链 Dagster LLD 为准。禁止用旧湖文件或旧 Console 导出入口代替正式 manifest/staging 链。

Dagster 接入 LLD：
[`dagster-stk-nineturn-dataset-onboarding-low-level-design.md`](../../lake_console/docs/design/dagster-stk-nineturn-dataset-onboarding-low-level-design.md)

状态：已落地（2026-05-09）

本文定义 `stk_nineturn` 数据集从生产 `raw_tushare.stk_nineturn` 只读导出到本地 Lake Parquet 的方案。

> Dagster 接入口径：正式 prod 只读初始化只通过当前 orchestrator 专用来源实现，不复用旧 Console 导出能力，
> 不进入 Dagster 日常 sensor。导出文件经批量校验后迁入正式
> `raw/tushare/stk_nineturn/trade_date=YYYY-MM-DD/part-000.parquet`；
> 日常 raw 由 Tushare `stk_nineturn` 更新，silver 再做标准代码归一。
> 当前 `goldenshare-tushare-lake/raw_tushare/stk_nineturn` 中的既有文件只是历史导出结果，
> 不得直接作为新 Dagster bootstrap 的完成事实；正式初始化必须重新从 prod 导出完整区间，
> 并只消费本批 manifest 列出的 staging 文件。
> 完整方案见
> `lake_console/docs/design/dagster-stk-nineturn-dataset-onboarding-plan.md`。

## 1. 目标

把生产库中已经落在 `raw_tushare.stk_nineturn` 的 Tushare 原始神奇九转指标数据，按 Lake Console 的按日分区布局导出成本地 Parquet。

核心目标：

- 导出的 Parquet 字段必须与 Tushare `stk_nineturn` 输出字段一致。
- 只访问生产库 `raw_tushare.stk_nineturn`。
- 禁止 `select *`。
- 不把 `api_name`、`fetched_at`、`raw_payload` 写入 Lake。
- 按交易日生成正式分区。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `stk_nineturn` |
| 显示名 | 神奇九转指标 |
| Tushare api_name | `stk_nineturn` |
| 源接口文档 | `docs/sources/tushare/股票数据/特色数据/0364_神奇九转指标.md` |
| 生产 raw 表 | `raw_tushare.stk_nineturn` |
| Lake 目标层 | `raw` |
| Lake 目标路径 | `raw_tushare/stk_nineturn/trade_date=YYYY-MM-DD/part-000.parquet` |
| 分区字段 | `trade_date` |
| 写入策略 | `replace_partition` |
| 导出来源 | `prod-raw-db` |

## 3. 字段白名单

Lake 字段白名单如下：

- `ts_code`
- `trade_date`
- `freq`
- `open`
- `high`
- `low`
- `close`
- `vol`
- `amount`
- `up_count`
- `down_count`
- `nine_up_turn`
- `nine_down_turn`

禁止导出：

- `api_name`
- `fetched_at`
- `raw_payload`

## 4. 生产 raw 表审计

### 4.1 历史审计快照（2026-05-09）

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 表存在 | 是 | `raw_tushare.stk_nineturn` |
| schema | `raw_tushare` | 符合边界 |
| 行数 | `4248684` | 当时截至 2026-04-24 |
| 日期范围 | `2023-01-03 ~ 2026-04-24` | 当时审计范围 |
| 交易日覆盖 | `800 / 800` | 当时范围内完整 |
| distinct `ts_code` | `5792` | 股票覆盖量 |
| 精确重复组 | `0` | `(ts_code, trade_date, freq)` 无重复 |
| `freq` 分布 | 仅 `daily` | 当前远程事实单一 |
| 系统字段 | 有 | `api_name`、`fetched_at`、`raw_payload` |

### 4.2 当前复审快照（2026-07-10）

对生产 `raw_tushare.stk_nineturn` 重新执行只读集合审计，结果如下：

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 实际日期范围 | `2023-01-03 ~ 2026-07-09` | 当前 prod 全量范围 |
| 行数 | `4,523,818` | 850 个交易日分区 |
| distinct `ts_code` | `5,821` | 包含历史代码 alias |
| 每日行数 | `4,969 ~ 5,667` | 平均 `5,322.14` |
| SSE 开市日覆盖 | `850 / 850` | 缺失开市日 0，非开市日分区 0 |
| 精确重复组 | `0` | `(ts_code, trade_date, freq)` 无重复 |
| 非 `daily` 行 | `0` | 当前远程事实单一 |
| 空 key / 空行情值 | `0 / 0` | 可作为 raw blocking rule |
| 非法价格、成交、计数、信号行 | `0` | 按当前正式规则聚合检查 |
| raw 与 serving 键差异 | `0` | 两边均为 4,523,818 个键 |
| raw 与 serving 业务值差异 | `0` | 现有同步链路没有改值 |

最近一年 `2025-07-09..2026-07-09`，北交所代码映射并去重后的九转对股票日线覆盖率为
`99.993665%`。剩余 `84` 行涉及 `31` 只新股，全部发生在上市后 0 至 4 个自然日，
属于源站 warm-up。最新日 `2026-07-09` 九转有 `5,518` 行，股票日线有 `5,520`
行，缺少 `920136.BJ` 和 `920189.BJ` 两只新股。

该复审不改变本方案的数据源边界：bootstrap 必须从 prod 重新拉取完整区间，不能直接把
历史 staging 目录中的旧文件视为本次导出结果。

### 4.3 字段对账

远程 raw 表业务字段与当前生产 `DatasetDefinition.source_fields` 对齐。  
当前 Lake 只需要做：

1. 字段白名单显式投影。
2. 数值统一落为 DuckDB 友好的 `double`。
3. `trade_date` 统一落为 Parquet `date`。
4. `freq` 字段保留，当前预期值为 `daily`。

## 5. 输入参数与导出范围

源站输入参数：

- `ts_code`
- `trade_date`
- `start_date`
- `end_date`
- `freq`
- `limit`
- `offset`

Lake 第一阶段仅支持：

- `--trade-date`
- `--start-date --end-date`

暂不支持：

- `--ts-code`

说明：

1. 生产与源站当前都固定在 `freq=daily` 口径。
2. Lake 不向用户暴露 `freq`，导出时只接受当前事实中的 `daily` 行。

## 6. 读取模式

读取模式结论：`range_streaming_cursor`

理由：

1. 行数四百多万，禁止 `fetchall`。
2. 区间导出必须单连接、只读事务、服务端游标流式读取。
3. 最终按 `trade_date` 聚合后逐日写分区。

允许的 SQL：

```sql
select
  ts_code,
  trade_date,
  freq,
  open,
  high,
  low,
  close,
  vol,
  amount,
  up_count,
  down_count,
  nine_up_turn,
  nine_down_turn
from raw_tushare.stk_nineturn
where trade_date >= :start_date
  and trade_date <= :end_date
  and freq = 'daily'
order by trade_date, ts_code;
```

## 7. 分区与空结果策略

正式分区：

```text
raw_tushare/stk_nineturn/trade_date=YYYY-MM-DD/part-000.parquet
```

规则：

1. 只对本地交易日历中的开市日写正式分区。
2. 某个开市日若查询结果为 0，不写空分区，不覆盖已有分区。
3. `trade_date` 必须是 Parquet `date`。

## 8. 命令设计（占位）

```bash
lake-console plan-sync stk_nineturn --from prod-raw-db --trade-date <cutover-date>
lake-console sync-dataset stk_nineturn --from prod-raw-db --trade-date <cutover-date>

lake-console plan-sync stk_nineturn --from prod-raw-db --start-date 2023-01-03 --end-date <cutover-date>
lake-console sync-dataset stk_nineturn --from prod-raw-db --start-date 2023-01-03 --end-date <cutover-date>
```

## 9. 验收口径

1. Parquet 字段必须与当前 `DatasetDefinition.source_fields` 一致。
2. `trade_date` 必须是 Parquet `date`。
3. 不得包含 `api_name`、`fetched_at`、`raw_payload`。
4. 交易日分区行数必须等于白名单 SQL 结果。
