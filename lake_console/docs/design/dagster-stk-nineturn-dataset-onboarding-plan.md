# Dagster 神奇九转数据集接入方案

状态：N0-N6 已完成开发、正式写入与验收；N7 cutover smoke 与只读 sensor 观察已完成，持久化启用 sensor 和最终验收待执行
日期：2026-07-10

代码级设计：
[`dagster-stk-nineturn-dataset-onboarding-low-level-design.md`](./dagster-stk-nineturn-dataset-onboarding-low-level-design.md)

## 1. 目标与边界

本专项把 Tushare `stk_nineturn` 神奇九转日线指标接入正式 Dagster Lake，形成两层长期资产：

1. `raw_tushare_stk_nineturn`：保留 Tushare 源站字段事实，历史首次初始化来自生产 `raw_tushare.stk_nineturn` 只读导出，日常增量来自 Tushare API。
2. `silver_stock_nineturn_daily`：把 raw 源代码归一为标准股票代码，清理类型、空值、重复别名和北交所新旧代码，向下游提供稳定日线九转事实。

本方案遵循：

- `lake_console/docs/templates/dagster-dataset-onboarding-template.html`
- `lake_console/docs/templates/dagster-bootstrap-migration-template.html`
- `lake_console/orchestrator/CODING_STANDARDS.md`
- `lake_console/docs/design/dagster-data-pipeline-performance-governance.md`
- `lake_console/docs/design/dagster-asset-check-incremental-governance-plan.md`

本轮方案不包含：

- 不修改生产 PostgreSQL `raw_tushare.stk_nineturn` / `core_serving.equity_nineturn`。
- 不新增 gold 资产、页面、API 或交易策略。
- 不把 `silver_stock_daily` 完整性作为九转日常 blocking gate；新股上市初期允许源站尚无九转记录。
- 不新增 dynamic partition set、readiness manifest、summary asset 或数据库表。
- 不把历史 prod 导出入口接入 sensor；prod 只用于一次性 bootstrap。
- 不在本方案阶段运行 `dg`、写 Dagster instance 或触碰正式 Lake。

## 2. 已核验事实

### 2.1 Tushare 契约

源文档：`docs/sources/tushare/股票数据/特色数据/0364_神奇九转指标.md`。

已通过 `tushareMcp.stk_nineturn` 验证：

- 单日单股票请求可使用 `trade_date="2026-07-09 00:00:00" + freq="daily"`。
- 返回字段为：
  `ts_code, trade_date, freq, open, high, low, close, vol, amount, up_count, down_count, nine_up_turn, nine_down_turn`。
- `trade_date` 返回 datetime 形态；Lake raw 统一写成 Parquet `DATE`，与现有 prod-raw-db Lake 契约一致。
- `up_count/down_count` 源端为数值，可能超过 9；`nine_up_turn/nine_down_turn` 分别使用 `+9/-9`，无信号时为空。
- 当前正式范围只支持 `freq=daily`；`freq` 是内部固定参数，不作为运营 run config。
- 接口文档单页硬上限为 10,000 行；项目共享 Tushare helper 的实际分页大小为 6,000 行。单日当前峰值 5,667 行，日常通常 1 页，仍保留 `limit/offset` 分页。
- 数据起点为 2023-01-01，生产首个实际交易日为 2023-01-03。

Tushare 没有公开九转累计计数的完整计算公式。本资产保存和规范化源结果，不在 silver 自行重算九转。

### 2.2 生产数据只读审计

复审时间：2026-07-10。审计范围为生产 `raw_tushare.stk_nineturn`
当前全部数据，不沿用旧文档统计值。

| 指标 | 结果 |
| --- | ---: |
| 实际日期范围 | 2023-01-03 ~ 2026-07-09 |
| 交易日分区数 | 850 |
| 总行数 | 4,523,818 |
| distinct 股票代码 | 5,821 |
| 平均单日行数 | 5,322.14 |
| 单日最小行数 | 4,969 |
| 单日最大行数 | 5,667 |
| 非 `daily` 行 | 0 |
| 空业务键 | 0 |
| 重复 `(ts_code, trade_date, freq)` | 0 |

使用生产 `core_serving.trade_calendar` 的 SSE 开市日做日期集合对账：

- `2023-01-03..2026-07-09` expected open dates 为 850 日。
- 九转实际分区也是 850 日，缺失开市日为 0，非开市日分区为 0。
- 最新 10 个分区从 2026-06-26 连续覆盖到 2026-07-09；最新分区 2026-07-09 有 5,518 行且代码唯一。

对全部 4,523,818 行的计数/信号字段做只读聚合后：

- `up_count/down_count` 空值、负数、小数均为 0。
- 上下计数同时大于 0 的行数为 0。
- `nine_up_turn/nine_down_turn` 非 `+9/-9/NULL` 的行数为 0。
- marker 存在但对应 count 小于 9 的行数为 0。
- 上下 marker 同时存在的行数为 0。

因此第 7 节的内容完整性规则来自当前生产全量事实，不是按指标名称推测。

生产 raw 与 `core_serving.equity_nineturn` 做完整键和值对账：

- raw-only key 为 0，serving-only key 为 0，业务字段不一致 key 为 0。
- 两边 4,523,818 个 `(ts_code, trade_date)` 键和值完全一致，现有生产同步链路没有丢数或改值。

最近一年 `2025-07-09..2026-07-09` 与 `core_serving.equity_daily_bar` 对账：

| 指标 | 结果 |
| --- | ---: |
| 股票日线行数 | 1,326,021 |
| raw 九转行数 | 1,326,905 |
| 映射去重后九转行数 | 1,325,937 |
| 原始代码严格匹配行数 / 比例 | 1,312,428 / 98.974903% |
| 规范代码匹配行数 / 比例 | 1,325,937 / 99.993665% |
| 股票日线有、九转无 | 84 行 / 31 只股票 |
| 九转有、股票日线无 | 0 |
| 匹配键 OHLCV 不一致 | 0 |
| 成交额差异超过 0.01 | 0 |

84 行缺口全部发生在对应股票上市后 0 至 4 个自然日，list date 缺失为 0，
不存在超出 warm-up 窗口的样本。最新日 2026-07-09 的两条缺口为：

- `920136.BJ`（N永励）：上市日 2026-07-09，当日股票日线已有、九转尚无。
- `920189.BJ`（康美特）：上市日 2026-07-08，2026-07-09 九转尚无。

这支持“不增加 stock daily 全覆盖 blocking check”的口径，但离线覆盖审计仍需保留。

### 2.3 北交所映射冲突

当前 5,821 个历史源代码分类为：

| 代码类别 | 数量 |
| --- | ---: |
| 可直接在 `raw_tushare.stock_basic` 识别 | 5,572 |
| 北交所旧代码 alias | 248 |
| 其它历史更名代码 | 1（`300114.SZ`） |

`300114.SZ` 已由正式 `silver_stock_identity_map` seed 映射到 `302132.SZ`。
因此 Silver 必须消费统一 identity map，不能只处理北交所 mapping。

完整历史映射到标准代码后：

| 指标 | 结果 |
| --- | ---: |
| 重复标准键 `(canonical_ts_code, trade_date)` | 4,340 |
| 重复额外行 | 4,340 |
| 内容不完全一致的重复键 | 46 |
| OHLC/成交量/成交额不一致键 | 0 |
| count 不一致键 | 46 |
| signal 不一致键 | 3 |
| 最大来源行数 | 2 |

46 个差异键全部位于 2023-01-03 至 2023-01-12：

- OHLC、成交量、成交额无差异。
- 差异只在 `up_count/down_count`，其中 3 个键同时影响 `+9/-9` 标志。
- 新 `920xxx.BJ` 行保留了更长的九转累计序列，旧代码行序列较短。

Silver 固定采用以下优先级：

1. 同一标准键存在 `source_ts_code == latest_ts_code` 的新代码行时，只选择新代码来源行。
2. 只有旧代码行时，使用该行的业务值，但输出 `ts_code` 必须改为 `latest_ts_code`。
3. 别名重复的 OHLC、成交量或成交额不一致时 fail closed；不得静默选一条。
4. 仅计数/信号不同且存在规范新代码行时允许按新代码行收敛，同时在 materialization/check metadata 记录冲突数量和样本。

Silver 中不允许出现北交所旧代码。Raw 继续保存 prod/Tushare 返回的原始代码事实，
但 raw 旧代码只能作为 identity mapping 输入，不能原样进入 Silver。

identity map 的历史全集口径已经固定为 `silver_stock_lifecycle`：生命周期事实中的每个
历史 `ts_code` 都生成 self mapping，包括已退市代码；`silver_stock_basic` 仍是
current-listed-only 快照，不作为历史九转代码全集。`silver_namechange` 只用于校验
版本化非 self seed 的解释性，不用于补造或筛掉历史股票 self mapping。

### 2.4 现有 Lake 事实

历史遗留的 prod 导出 staging 目前存在：

```text
/Volumes/datasource/goldenshare-tushare-lake/raw_tushare/stk_nineturn/
```

只读检查结果：

| 指标 | 结果 |
| --- | ---: |
| 已有文件 | 812 |
| 日期范围 | 2023-01-03 ~ 2026-05-15 |
| 总大小 | 139MB |
| 最近单日文件 | 约 187KB |

正式 Dagster raw 路径当前不存在：

```text
/Volumes/datasource/data_lake/raw/tushare/stk_nineturn/
```

这些文件不是本次 bootstrap 的可信输入，也不是正式 Dagster raw。历史初始化必须重新从
prod-raw-db 拉取 `2023-01-03..cutover-date` 全区间；如果继续复用该目录作为临时
staging，每个目标分区都必须由本次 prod 导出重写，并出现在本批 manifest 中。
禁止把目录中原有文件直接计入本次 bootstrap 完成范围。

## 3. 数据集说明卡

| 项目 | Raw | Silver |
| --- | --- | --- |
| 中文名 | 神奇九转 raw 源镜像 | 股票日线神奇九转标准事实 |
| Asset key | `raw_tushare_stk_nineturn` | `silver_stock_nineturn_daily` |
| dataset_id | `stk_nineturn` | `stock_nineturn_daily` |
| layer | `raw` | `silver` |
| data domain | `quote_data` | `quote_data` |
| group | `quote` | `quote` |
| 长期来源 | Tushare `stk_nineturn` | Raw + `silver_stock_identity_map` |
| bootstrap 来源 | 本批 prod-raw-db 全量导出 | formal raw 历史分区 |
| 分区 | `cn_a_stock_trade_days` | `cn_a_stock_trade_days` |
| 写入粒度 | 单交易日单文件 | 单交易日单文件 |
| 写入策略 | partition file atomic replace | partition file atomic replace |
| 自动化 | basic sensor | basic sensor |

`cn_a_stock_trade_days` 已是股票日线资产族正式分区集。本专项只复用，不新增九转专属分区集，也不新增分区注册 sensor。

## 4. 物理路径与字段契约

### 4.1 路径

```text
raw/tushare/stk_nineturn/trade_date=YYYY-MM-DD/part-000.parquet
silver/quote/stock_nineturn_daily/trade_date=YYYY-MM-DD/part-000.parquet
```

历史遗留 staging 路径：

```text
/Volumes/datasource/goldenshare-tushare-lake/raw_tushare/stk_nineturn/
```

该目录中的既有文件不作为本次 bootstrap 的可信输入。本批重新从 prod 导出的文件
必须通过 manifest 与批次审计后才能进入 formal raw。

staging 路径、生产表名、source method、run id 不得写入 Parquet 业务字段。

### 4.2 Raw schema

| 字段 | DuckDB 类型 | 规则 |
| --- | --- | --- |
| `ts_code` | `VARCHAR` | 源站原始代码，不做北交所映射 |
| `trade_date` | `DATE` | 必须等于 partition key |
| `freq` | `VARCHAR` | 固定 `daily` |
| `open/high/low/close` | `DOUBLE` | 源站行情值 |
| `vol/amount` | `DOUBLE` | 源站成交量/成交额 |
| `up_count/down_count` | `DOUBLE` | 保留源端数值类型 |
| `nine_up_turn/nine_down_turn` | `VARCHAR` | 允许 `+9/-9/NULL` |

Raw 不加入 `source_method`、`fetched_at`、`raw_payload` 或标准代码字段。

### 4.3 Silver schema

| 字段 | DuckDB 类型 | 规则 |
| --- | --- | --- |
| `ts_code` | `VARCHAR` | `silver_stock_identity_map.latest_ts_code` |
| `trade_date` | `DATE` | 标准交易日 |
| `freq` | `VARCHAR` | 固定 `daily` |
| `open/high/low/close` | `DOUBLE` | 规范代码优先后的行情值 |
| `vol/amount` | `DOUBLE` | 规范代码优先后的成交值 |
| `up_count/down_count` | `INTEGER` | raw 值必须非负且为整数后转换 |
| `nine_up_turn` | `VARCHAR` | 只允许 `+9/NULL` |
| `nine_down_turn` | `VARCHAR` | 只允许 `-9/NULL` |

Silver 不保留行级 `source_ts_code`。来源代码、映射来源、重复数和冲突样本进入 materialization/check metadata，避免下游误用历史代码。

## 5. Silver 清洗算法

正式实现使用 DuckDB set-based SQL，不用 Python 行循环。

逻辑顺序：

```text
raw partition
  -> 类型归一
  -> 按 source_ts_code + trade_date 连接 silver_stock_identity_map 有效区间
  -> 未映射代码 fail closed
  -> 输出 latest_ts_code 为标准 ts_code，禁止旧代码进入 Silver
  -> 对标准 ts_code + trade_date 做别名冲突审计
  -> OHLC/vol/amount 冲突 fail closed
  -> 新代码行优先去重
  -> count 转 INTEGER，marker 空字符串归一成 NULL
  -> 写 silver 临时文件
  -> 校验 -> 原子替换正式文件
```

身份映射有效区间沿用现有正式语义：

```sql
raw.trade_date >= identity.valid_from
and (
  identity.valid_to is null
  or raw.trade_date < identity.valid_to
)
```

禁止：

- 直接在九转代码中读取 `raw_tushare.bse_mapping` 自造映射。
- 使用 current-listed-only 股票池过滤历史九转。
- 用股票名称或代码前缀猜测映射。
- 对无法映射、行情冲突或重复业务键做 silent drop。
- 在 silver 重新计算九转指标。

## 6. Asset Catalog 与 Definition 设计

### 6.1 Catalog

在 `orchestrator.defs.catalog.lake_assets` 增加：

- 两个 `PartitionModel`。
- 两个 `PartitionModelDefinition`。
- raw/silver 两个 `LakeAssetCatalogEntry`。
- `EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL`。

Raw ingestion sources：

```text
tushare_api          日常正式来源
prod_db_readonly     历史初始化事实来源
```

`old_lake_bootstrap` 不属于本数据集的 ingestion source。本次历史事实必须由
`prod_db_readonly` 重新导出；历史遗留 Parquet 只是一组待对账/待清理文件。

Silver bootstrap source：`derived_from_assets`。

### 6.2 Asset definitions

建议文件：

```text
defs/assets/stk_nineturn.py
```

定义：

```text
raw_tushare_stk_nineturn
silver_stock_nineturn_daily
```

共同要求：

- 显式 `partitions_def=cn_a_stock_trade_days`。
- 使用 `build_asset_tags(...)`、`build_asset_definition_metadata(...)`。
- materialization metadata 使用 `build_materialization_metadata(...)`。
- 日常写入严格走 `.tmp -> validate -> os.replace`。
- description 必须写清来源、分区、下一步和失败排查入口。

Silver deps：

```text
raw_tushare_stk_nineturn
silver_stock_identity_map
```

不直接依赖 `silver_stock_daily`。股票日线与九转覆盖的跨数据集比较属于离线审计，不是生成 silver 九转所需输入。

## 7. Asset Checks

为控制 Dagster DB 增量，每个资产只保留 2 个普通 blocking checks；细分 rule 通过 check metadata 的 `rule_summary` 表达，不注册为更多 Dagster checks。

### 7.1 Raw checks

1. `raw_tushare_stk_nineturn_contract_check`
   - 文件存在且 row count > 0。
   - schema 与 raw contract 一致。
   - 文件内仅有 partition trade date。
   - `freq` 仅为 `daily`。
   - partition 已注册且不晚于当前日期。

2. `raw_tushare_stk_nineturn_content_integrity_check`
   - `(ts_code, trade_date)` 非空且唯一。
   - OHLC 合法：`high >= greatest(open, close, low)`、`low <= least(open, close, high)`，价格非负。
   - `vol/amount` 非负。
   - `up_count/down_count` 非负且为整数值，不能同时大于 0。
   - `+9/-9` 与对应 count >= 9 一致，且两个信号不能同时存在。

### 7.2 Silver checks

1. `silver_stock_nineturn_daily_contract_check`
   - 文件、schema、row count、partition date、`freq=daily`。
   - `(ts_code, trade_date)` 非空且唯一。

2. `silver_stock_nineturn_daily_canonical_integrity_check`
   - raw 来源代码 100% 可映射。
   - 规范化后无未解决业务键冲突。
   - 旧代码与规范新代码同行时按新代码优先。
   - OHLC/vol/amount 别名冲突为 0。
   - silver 行数等于 raw 规范化去重后的期望行数。
   - 内容域规则与 raw 一致，count 已为 INTEGER。

四个 check 必须显式声明 `partitions_def=cn_a_stock_trade_days`，防止 check event partition 归属为空。

不新增“九转必须覆盖所有 stock_daily 行”的 blocking check。新股在接口 warm-up 阶段没有九转记录属于源端允许状态；该对账进入离线审计报告。

## 8. Job 设计

建议文件：

```text
defs/jobs/stk_nineturn_update.py
```

定义两个 job：

1. `raw_stk_nineturn_update_job`
   - selection：raw asset + raw checks。
   - 不选择 silver 或共享上游。

2. `silver_stock_nineturn_daily_update_job`
   - selection：silver asset + silver checks。
   - 不顺手 materialize raw 或 `silver_stock_identity_map`。

两个 job 均为单分区执行。历史初始化不通过这两个日常 job 批量跑 850 个分区。

## 9. Sensor 与 Cursor 设计

建议文件：

```text
defs/sensors/stk_nineturn_sensor.py
defs/asset_guards/stk_nineturn_lake_readiness.py
```

### 9.1 Raw sensor

| 项目 | 口径 |
| --- | --- |
| 名称 | `raw_stk_nineturn_update_job_sensor` |
| 默认状态 | `STOPPED`，bootstrap 与人工验收完成后再启用 |
| minimum interval | 600 秒 |
| 时间窗口 | 21:15 以后；Tushare 文档标明约 21:00 更新 |
| expected dates | `silver_trade_calendar` 的 SSE 开市日，最近 10 个 |
| partition set | `cn_a_stock_trade_days` |
| 目标选择 | first not ready |
| 单 tick RunRequest | 最多 1 个 |
| readiness | 一次 DuckDB batch 扫描最近 10 个 raw 文件 |
| Dagster history | 10 日循环内 0 次 event/check history 读取 |

决策：

- registered gap 存在：skip，提示先补注册分区。
- 时间窗口前：不执行 DuckDB 重检查，只写小型 cursor。
- 文件缺失：提交最早缺失 raw partition。
- 文件存在但 checks 语义失败：skip，要求人工修复，不自动覆盖。
- 最近 10 日全 ready：skip。

### 9.2 Silver sensor

| 项目 | 口径 |
| --- | --- |
| 名称 | `silver_stock_nineturn_daily_update_job_sensor` |
| 默认状态 | `STOPPED` |
| minimum interval | 600 秒 |
| 时间窗口 | 21:20 以后 |
| expected dates | 与 raw 相同，最近 10 个 |
| 目标选择 | first silver not ready |
| 上游 gate | 同日 raw lake readiness ready；identity map 文件存在且可覆盖同日 source codes |
| 单 tick RunRequest | 最多 1 个 |
| Dagster history | 日期循环内 0 次 event/check history 读取 |

如果 identity map 不覆盖 source code，sensor 不提交 silver run，cursor 指向 `silver_stock_identity_map`；正式 asset 仍会 fail closed，不能由 sensor 判断替代 asset/check。

正式实现先用一次 Raw batch readiness 找到连续 ready 前缀，再只对该前缀执行一次
Silver batch readiness。Raw 窗口首日不 ready 时不读取 Silver；Raw 在窗口中途阻断时，
仍允许补齐阻断日前更早的 Silver 缺口，但永远不会越过 Raw frontier 提交后续日期。

### 9.3 Run key

只能通过统一 builder：

```text
build_asset_update_run_key(subject="raw_stk_nineturn_update", unit_id=trade_date)
build_asset_update_run_key(subject="silver_stock_nineturn_daily_update", unit_id=trade_date)
```

输出：

```text
raw_stk_nineturn_update:YYYY-MM-DD
silver_stock_nineturn_daily_update:YYYY-MM-DD
```

Sensor 使用 `build_run_request(...)`，不得直接 `dg.RunRequest(...)`，不得手写 run tags 或解析 run key 生成 config。

### 9.4 Cursor

统一使用 `build_sensor_cursor(...)` 和 `build_cursor_details(...)`。

允许的小型 details：

```text
sensor_name
job_name
asset_family=stk_nineturn
partition_set=cn_a_stock_trade_days
reason_code
blocked_component
summary
next_action
frontier
gate_statuses
evidence
runtime_state
performance_ms
diagnostic_ref
```

约束：

- `reason_code` 必须 ASCII。
- 典型 cursor < 2KB，复杂阻断 < 3KB，硬上限 8KB。
- 不写完整 batch status、路径列表、代码列表、SQL 结果或 schema map。
- Cursor 不是 readiness 正确性来源，只是本 tick 的调度路标。

## 10. 历史 Bootstrap 与 Runless Events

历史初始化与日常链路必须分开。

### 10.1 B0：prod-raw-db 导出 dry-run

使用现有 Lake Console prod 只读导出能力：

```bash
lake-console plan-sync stk_nineturn --from prod-raw-db \
  --start-date 2023-01-03 --end-date <cutover-date>
```

cutover date 在正式执行当天取：

```text
min(prod raw latest date, latest completed SSE trade date)
```

Dry-run 必须输出：日期数、源行数、预计文件数、目标冲突、预计磁盘和单连接范围读取计划。
Dry-run 不得把历史遗留 staging 文件计为已完成分区。

N4 于 2026-07-10 完成：生产只读复核仍为 `2023-01-03..2026-07-09`、
850 个交易日、4,523,818 行；正式 SSE calendar 已到 `2026-07-10`，因此 cutover
按两者较小值固定为 `2026-07-09`。本地 `plan-sync` 输出 850 个目标分区，首尾路径
与 expected calendar 一致。

### 10.2 B1：prod-raw-db staging 导出

执行区间流式导出，从 prod 重新生成完整 bootstrap staging。读取必须：

- 单个只读 DB 连接。
- 服务端游标/范围流式读取。
- 显式字段白名单。
- 禁止 `select *`。
- 按 trade_date 写 staging 分区。
- 为本次批次生成 manifest，至少记录 cutover date、目标分区、源行数、输出行数、文件路径和校验结果。
- B2 只接受本批 manifest 中的文件；目录中未列入 manifest 的历史文件一律忽略。

该阶段不写 Dagster event。

N4 正式执行使用显式、独立的 mini-lake root，不能省略 `--lake-root`。backend
默认根 `/Volumes/datasource/goldenshare-tushare-lake` 属于旧 Lake，不是本专项
formal Lake；本批只复制已与正式 Silver calendar 做过 850 日零差集对账的 calendar
manifest，不复用其中任何九转文件。

唯一允许 N5 消费的 fresh export：

```text
staging root:
/Volumes/datasource/data_lake/_bootstrap/stk_nineturn/n4_full_20260710T193955

manifest:
/Volumes/datasource/data_lake/_bootstrap/stk_nineturn/n4_full_20260710T193955/manifest/sync_runs.jsonl

run_id:
20260710T115046Z-stk_nineturn-prod-raw-db
```

正式结果：850 个文件、4,523,818 行、146MB，`fetched_rows=written_rows`，
skipped/source-gap/no-data 均为 0，流式导出耗时 401.756 秒。逐文件 schema、
manifest/file 行数、日期集合、业务键及完整 Raw 内容规则全部通过，所有异常计数为 0。
正式 Raw 目录在 N4 结束时仍不存在。

N4 样本暴露并修复了两个通用导出问题：`DbTradeDateExportService` 现按字段白名单
顺序构造行；Parquet writer 支持显式 dtype override，九转两个 marker 即使整日全为
NULL 也固定写成字符串类型。以下根只保留作诊断证据，禁止 N5 消费：

```text
n4_sample_20260710T183722  # trade_date/ts_code 列顺序错误
n4_sample_20260710T184337  # 顺序修复样本，但未覆盖全 NULL marker 风险
n4_full_20260710T185859    # 13 个 nine_down_turn 全 NULL 分区被推断为 NULL 类型
n4_sample_20260710T193201  # 最终修复后的 3 日样本，仅作样本验收
```

这些隔离目录不自动删除；清理必须另行审批，不能与 N5 formal build 混在一起。

### 10.3 B2：formal raw 批量构建

不逐分区运行日常 raw asset，也不使用 850 次 Tushare 请求。

实现 `stk_nineturn` 专项 batch bootstrap helper，按年份处理 2023、2024、2025、2026：

1. 一次读取本批 manifest 中该年度 staging Parquet 集合。
2. 显式投影并校正 raw schema。
3. 写入年度临时 partitioned output。
4. 批量校验日期集合、行数、schema、业务键。
5. 校验通过后逐分区原子替换 formal raw 文件。

任何年度批次失败都不得留下半成品正式分区。

### 10.4 B3：silver 批量构建

按年份用 DuckDB set-based SQL 读取 formal raw + 单个 identity map full file：

- 输出每日 silver 临时分区。
- 应用第 5 节映射、冲突和去重规则。
- 批量验证后原子替换。
- 不在 Python 中逐行映射或去重。

### 10.5 B4：文件最终审计

必须同时满足：

- raw/silver 分区集合与 cutover 范围内 expected SSE 交易日一致。
- raw 总行数与 prod 白名单导出一致。
- silver 总行数与规范化去重结果一致。
- 任一 source code 未映射数为 0。
- OHLC/vol/amount 别名冲突数为 0。
- 46 个已知计数/信号冲突按新代码优先收敛，并输出审计样本。

### 10.6 B5：runless event dry-run 与补录

为控制 Dagster DB 增长：

- 所有历史 raw/silver 分区补 materialization event：约 850 x 2 = 1,700 条。
- 普通 blocking check event 只补最近 20 个 `cn_a_stock_trade_days`：20 x 2 assets x 2 checks = 80 条。
- 早于最近 20 日的文件质量由 B4 聚合审计报告证明，不补普通 check event。
- 日常 job 继续正常写 materialization + check events。

执行顺序：dry-run -> 3 日样本 -> 对账 -> 分批 full report -> final audit。

禁止为历史补录运行 850 个 Dagster jobs。Runless event 写入需要单独正式审批。
N6 工具已落地到 `stk_nineturn_events.py` / `stk_nineturn_events_cli.py`：dry-run 默认只读，
report 必须显式 `--confirm-write`；事件目标绑定同分区最新 materialization。正式执行已完成：
1,700 个 materialization 和 80 个 recent20 check event 均已写入，final dry-run 计划归零。
执行报告分别保存在 `/private/tmp/stk_nineturn_events_n6_*`，正式执行前后均通过 active runs
为 0 和 final file audit 门禁。

### 10.7 B6：切换日常来源

只有 B1-B5 全部通过后：

1. 确认下一 expected trade date 为 `cutover-date` 之后第一交易日。
2. 启用 raw sensor，再启用 silver sensor。
3. prod-raw-db 不进入日常 sensor。
4. 历史遗留 staging 是否删除另行审批，不包含在本专项自动执行中。

## 11. 性能门禁

| 场景 | 对象/日期 | 读写模型 | 预算/门禁 |
| --- | --- | --- | --- |
| prod bootstrap | 850 日、4,523,818 行 | 单连接 range streaming | 实测 401.756 秒、146MB；禁止逐日建 850 个 DB 连接，硬停止线 600 秒 |
| formal raw bootstrap | 4 个年度批次 | DuckDB batch read/write | 每年 1 个主查询；禁止 850 次独立 DuckDB 深扫 |
| silver bootstrap | 4 个年度批次 + 1 个 identity full file | DuckDB set-based join/window | Python 不处理明细行；内存不足则降为季度批次，不降低语义 |
| 日常 raw | 1 日期，通常 <= 5,667 行 | 项目 helper 每页 6,000 行，保留 `limit/offset` 分页 | 单 run 目标 < 30 秒；超过 2 页或 60 秒停止评估源站变化 |
| 日常 silver | 1 raw 文件 + identity map | 1 个 DuckDB SQL | 目标 < 2 秒 |
| raw sensor | 最近 10 日，最多 10 文件 | 1 个 batch readiness 查询 | 时间窗口前 0 个文件扫描；目标 < 2 秒 |
| silver sensor | 最近 10 日，最多 20 个 raw/silver 文件 + identity full file | 最多 2 个 batch 查询 | 0 次逐日 Dagster check history；目标 < 3 秒 |
| Dagster events | 1,700 materializations + 80 recent checks | 有界分批 runless report | 不补全历史普通 checks；每批失败立即停止 |

不可接受：

- Sensor tick > 5 秒或触发 gRPC 60 秒超时。
- 日常 sensor 扫全历史或默认 60 日窗口。
- 10 日循环内调用 Dagster event/check history readiness。
- batch helper 内按日期循环执行重 SQL。
- 只看文件存在或 row count 就宣称 ready。
- 在 Cursor 中写完整 readiness report。
- 历史构建发生 DuckDB spill 且无法通过季度批次消除。

开发阶段必须新增 10 日和 60 日容量样本；60 日只做容量测试，不改变日常 10 日窗口。

N3 本地临时 Parquet 性能验收结果如下。样本每个日文件 1 行，elapsed 只统计
readiness helper，不包含 fixture 构建；正式 sensor 日期循环内 Dagster history API
调用次数为 0。

| helper | 窗口 | 文件模型 | 业务主查询 | schema metadata 读取 | elapsed |
| --- | ---: | --- | ---: | ---: | ---: |
| Raw readiness | 10 日 | 10 个 Raw 文件 | 1 | 10 | 6ms |
| Silver readiness | 10 日 | 10 Raw + 10 Silver + identity | 1 | 20 | 13ms |
| Raw readiness | 60 日容量 | 60 个 Raw 文件 | 1 | 60 | 22ms |
| Silver readiness | 60 日容量 | 60 Raw + 60 Silver + identity | 1 | 120 | 42ms |

上述 60 日结果只证明算法没有退化成逐日重 SQL；正式 sensor 固定最近 10 日。

## 12. 失败与恢复语义

| 场景 | 自动行为 | 人工动作 |
| --- | --- | --- |
| 分区未注册 | sensor skip | 先恢复 `cn_a_stock_trade_days` 注册 |
| Raw 文件缺失 | raw sensor 提交最早缺失日 | 无 |
| Raw 文件存在但 check 失败 | 不自动覆盖 | 检查源文件、修复后手动重跑 |
| Silver 文件缺失且 raw ready | silver sensor 提交最早缺失日 | 无 |
| Identity map 不覆盖代码 | 不提交 silver | 先修统一 identity fact |
| 别名行情冲突 | Silver fail closed | 审计源数据，不允许静默选择 |
| 新股日线存在但 raw 九转缺失 | 不视为九转文件损坏 | 由离线 stock daily 对账报告观察 |
| 停机超过 10 个交易日 | sensor 只看最近 10 日 | 使用人工范围 backfill/维护入口补更早缺口 |

## 13. 代码落点

预计新增：

```text
lake_console/orchestrator/src/orchestrator/defs/assets/stk_nineturn.py
lake_console/orchestrator/src/orchestrator/defs/checks/stk_nineturn_checks.py
lake_console/orchestrator/src/orchestrator/defs/jobs/stk_nineturn_update.py
lake_console/orchestrator/src/orchestrator/defs/sensors/stk_nineturn_sensor.py
lake_console/orchestrator/src/orchestrator/defs/asset_guards/stk_nineturn_lake_readiness.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_nineturn_history.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_nineturn_history_cli.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_nineturn_events.py
lake_console/orchestrator/src/orchestrator/defs/bootstrap/stk_nineturn_events_cli.py
```

预计修改：

```text
defs/paths.py
defs/duckdb_sql.py
defs/run_contracts/asset_column_schemas.py
defs/catalog/lake_assets.py
defs/catalog/name_mapping.py
tests/test_asset_check_incremental_governance.py
tests/test_run_contract_static_gates.py
```

不新增 resource、database table、dynamic partition definition 或配置项。

## 14. 测试计划

### 14.1 Raw

- Tushare 参数固定为 `trade_date + freq=daily`。
- fields 精确等于 raw schema。
- 0 行 fail closed，不写空分区。
- 返回量超过项目 helper 的 6,000 行分页大小时，`offset` 正确推进；接口请求的 `limit` 不得超过源端 10,000 行硬上限。
- `.tmp -> validate -> replace`。
- Raw 保留旧代码，不提前映射。

### 14.2 Silver

- 普通代码 self mapping。
- 北交所旧代码映射到 `920xxx.BJ`。
- `300114.SZ -> 302132.SZ` 映射。
- 新旧同行且内容一致时只保留规范新代码行。
- 计数/信号冲突时规范新代码行优先并记录 metadata。
- OHLC/vol/amount 冲突 fail closed。
- 未映射代码 fail closed。
- count 非整数、负值、上下同时为正、signal/count 不一致均失败。

### 14.3 Checks / Job

- 4 个 checks 都是 partitioned checks。
- 每个 check 使用 `build_check_metadata(...)`。
- Raw job 只选 raw + raw checks。
- Silver job 只选 silver + silver checks。
- 不产生空 partition check event。

### 14.4 Sensor / Cursor

- 时间窗口前不调用重 batch readiness。
- registered gap 时不扫描文件、不发 run。
- 10 日 first-not-ready 顺序正确。
- materialized check problem 不自动重跑。
- Raw 未 ready 时 silver 不推进后续日期。
- 每 tick 最多 1 个 RunRequest。
- run key 经统一 builder。
- cursor reason_code 为 ASCII，包含 summary/next_action，大小低于预算。
- 静态禁止直接 `dg.RunRequest(...)`、手写 run key、run key 反解析、逐日 Dagster readiness。

### 14.5 Bootstrap / Events

- dry-run 只读，不写文件或 events。
- 年度 sample 输出 schema/行数/日期集合正确。
- Full file audit 通过后才允许 event dry-run。
- 全历史 materialization 与 recent20 checks 数量符合计划。
- runless 事件只为已通过相同 blocking 语义的文件写绿。

## 15. 分阶段推进

当前进度（2026-07-10）：N0-N4 已完成开发与验收。Silver catalog entry 已与
active Silver asset 同阶段注册；writer/checks 已覆盖 identity 有效区间、每行恰好一次
映射、规范代码优先和冲突 fail-closed 语义。Raw/Silver sensor 已按最近 10 日、
first-not-ready、Raw ready frontier 和 DuckDB true-batch readiness 落地。N4 fresh
prod export 已在隔离 staging 完成，并通过 850 文件全量审计。

| 阶段 | 核心任务 | 是否可合并 |
| --- | --- | --- |
| N0（已完成） | 契约、路径、schema、Raw catalog、check 治理矩阵 | 已与 N1 同轮开发并完成独立契约验收 |
| N1（已完成） | Raw asset + raw checks + raw job | 临时 Lake、分页、0 行和 partitioned check 归属已通过 |
| N2（已完成） | Silver SQL/asset + silver checks + silver job | identity/alias 冲突矩阵和 partitioned checks 已通过 |
| N3（已完成） | Batch lake readiness + 两个 sensors + cursor/static gates | 10/60 日性能、0 次 Dagster history、first-not-ready 与小型 cursor 已通过 |
| N4（已完成） | prod 全量重新导出 dry-run/sample/full + staging audit | 850 文件、4,523,818 行、精确 schema 和 manifest 对账已通过 |
| N5 | Formal Raw/Silver history dry-run/sample/full + 聚合审计 | 已完成；最终文件审计通过 |
| N6 | Runless event dry-run/sample/full | 已完成；1,780 个 event 已写入，recent20 checks 的 partition 与 latest materialization target 对账通过 |
| N7 | 单日 Tushare smoke、sensor 人工启用、最终文档对账 | smoke 与手工 evaluation 已通过；daemon/sensor 持久化启用及最终验收待执行 |

N4、N5、N6 不得合并成一次不可中断的大操作。每阶段必须有独立 dry-run、样本、正式执行和结果报告。

## 16. 验收标准

1. Formal raw/silver 覆盖 cutover date 之前全部 expected trade dates。
2. Raw 行数与 prod 白名单导出一致。
3. Silver 未映射代码、行情别名冲突、重复标准键均为 0。
4. 已知 46 个计数/信号冲突按规范新代码优先收敛，并有审计记录。
5. 最近 20 日 raw/silver materialization 与 4 个 checks 均可按 partition 读取。
6. 更早历史 materialization 可见，但不写全量普通 check events。
7. 日常 Tushare 单分区写入和 silver 生成闭环通过。
8. Sensor 最近 10 日 first-not-ready、停机补洞、人工 check problem 语义正确。
9. 不新增直接 RunRequest、手写 run key、run key 反解析或逐日 event history 深扫。
10. 不修改现有 stock daily、identity map、生产数据库或其它资产族运行行为。

## 17. 已拍板口径

1. Silver 保留 `freq='daily'` 字段，不新增布尔信号字段；`+9/-9` 保持字符串语义。
2. Raw 保留 prod/Tushare 原始代码；Silver 只输出规范新代码。新旧同行时只保留新代码来源行，只有旧代码时映射为新代码后输出；行情/成交字段冲突仍 fail closed。
3. 新股上市初期没有九转记录属于源端 warm-up，不增加 stock daily 全覆盖 blocking check。
4. 每层只保留 2 个合并后的 blocking checks，共 4 个 Dagster checks。
5. 历史补全全部 materialization，只补最近 20 日普通 check events。
6. 日常窗口为 raw 21:15、silver 21:20，最近 10 日 first-not-ready，单 tick 1 个 run。
7. Bootstrap 必须从 prod-raw-db 重新拉取完整区间；日常只允许 Tushare API。历史遗留 staging 文件不得直接作为 bootstrap 完成事实。
8. 历史遗留 staging 清理不包含在本专项自动执行中，最终验收后另行审批。
