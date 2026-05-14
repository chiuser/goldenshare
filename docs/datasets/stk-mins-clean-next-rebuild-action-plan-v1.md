# stk_mins 正式 clean_next 重建行动计划 v1

状态：M0-M6 已执行；`clean_next` 已成为后续工作 clean 基准
最近更新：2026-05-13
适用范围：本地 Lake `stk_mins` 从 `raw_tushare/stk_mins_by_date` 构建正式 clean candidate

## 1. 本文定位

本文是 `stk_mins` 正式 clean candidate 的执行行动计划。后续每完成一个阶段，必须回到本文复核当前阶段目标、禁止事项、输出路径、字段门禁和下一阶段准入条件，确认没有跑偏后再继续。

参考总账本：

[stk_mins clean 数据清洗总记录 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-clean-cleaning-master-record-v1.md)

该总账本记录了历史错误 clean 的产生背景、错误 schema、已执行专项、正式 clean 重建和后续 clean_next 基准口径。本文只负责正式 `clean_next` 的行动计划。

## 2. 当前决策

1. 旧错误 clean 已删除：
   `research/stk_mins_by_date_clean`

2. 正式 clean candidate 已建成：
   `research/stk_mins_by_date_clean_next`

3. 旧错误 clean 不再作为任何后续输入。

4. `raw_tushare/stk_mins_by_date` 不修改。

5. `clean_next` 只从 raw 构建，不从旧错误 clean 构建。

6. `clean_next` 已构建完成并通过审计；后续重建 `derived/stk_mins_by_date` 必须从 `clean_next` 读取：
   `derived/stk_mins_by_date`

7. `clean_next` 已构建完成并通过审计；后续重建 `research/stk_mins_by_symbol_month` 必须从 `clean_next` 与 `derived` 读取：
   `research/stk_mins_by_symbol_month`

8. `clean_next` 构建完成并通过审计前，不重建任何技术指标。

## 3. 硬门禁

### 3.1 输出字段

正式 clean candidate 的 Parquet 物理列必须严格等于：

```text
ts_code
freq
trade_time
open
close
high
low
vol
amount
exchange
vwap
```

禁止写入：

```text
trade_date
identity_id
source_ts_code
```

说明：

`trade_date` 只通过目录分区表达：

```text
research/stk_mins_by_date_clean_next/freq=<freq>/trade_date=<YYYY-MM-DD>
```

### 3.2 清洗规则

必须执行的清洗：

| 规则 | 处理 |
| --- | --- |
| `ts_code` 无法通过 `security_identity_map` 映射 | 剔除并计入过滤统计 |
| 已退市股票 | 剔除并计入过滤统计 |
| 上市日前数据 | 剔除并计入过滤统计 |
| `trade_time` 无法解析 | 剔除并计入过滤统计 |
| `open/close/high/low` 缺失或无法解析 | 剔除并计入过滤统计 |
| `high < low` | 剔除并计入过滤统计 |
| `vol < 0` 或 `amount < 0` | 剔除并计入过滤统计 |
| 同一 `(latest_ts_code, freq, trade_time)` payload 冲突 | 停止，不写该分区 |

禁止执行的过度清洗：

| 情况 | 处理 |
| --- | --- |
| `open/close/high/low` 等于 `0` | 不因等于 `0` 直接剔除 |
| `OHLC` 全 `0` 且 `vol/amount` 为 `0` | 不在 clean 构建阶段直接剔除，留给审计账本判断 |
| 部分 OHLC 为 `0` 但有成交或有非零价格 | 不剔除 |

## 4. 每阶段开工前自检

每个阶段开始前必须逐项检查：

1. 已重新阅读本文。
2. 已重新确认目标输出路径是 `research/stk_mins_by_date_clean_next`。
3. 已确认不会删除旧错误 clean。
4. 已确认不会覆盖旧错误 clean。
5. 已确认不会修改 raw。
6. 已确认不会重建 derived/research by symbol/indicator。
7. 已确认字段门禁仍是 11 列正式 schema。
8. 已确认本阶段命令只覆盖本阶段声明的范围。
9. 如发现新 P0 风险，先更新工程风险登记簿，再继续。

## 5. 阶段计划

### M0. 代码入口与字段门禁

目标：

新增正式 clean candidate 的构建入口，禁止复用旧错误 clean 命令。

计划动作：

1. 新增独立命令：
   `rebuild-stk-mins-by-date-clean-next-range`

2. 该命令只写：
   `research/stk_mins_by_date_clean_next`

3. 保留旧命令：
   `rebuild-stk-mins-by-date-clean-range`

4. 旧命令只作为历史错误 clean 流程记录，不作为正式 clean 构建入口。

5. 新增测试，断言输出字段严格等于 11 列正式 schema。

6. 新增测试，断言输出不包含：
   `trade_date/source_ts_code/identity_id`

阶段完成标准：

1. 单元测试通过。
2. 命令 `--dry-run` 可运行。
3. 不产生任何正式数据写入。

### M1. 2026 年 3 月写入验证

目标：

用 2026 年 3 月窗口做真实写入验证。

验证范围：

```text
freqs=1,5,15,30,60
start_date=2026-03-01
end_date=2026-03-31
output=research/stk_mins_by_date_clean_next
```

预期命令：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli rebuild-stk-mins-by-date-clean-next-range \
  --apply \
  --replace-existing \
  --freqs 1,5,15,30,60 \
  --start-date 2026-03-01 \
  --end-date 2026-03-31
```

验证项：

1. `clean_next` 有 2026 年 3 月对应分区。
2. 旧错误 clean 未变化。
3. raw 未变化。
4. `clean_next` 每个分区字段严格为 11 列。
5. `clean_next` 不含 `trade_date/source_ts_code/identity_id`。
6. `exchange/vwap` 字段存在，即使部分值为空也必须保留字段。

阶段完成标准：

1. 写入成功。
2. schema 校验通过。
3. 样本分区审计通过。

### M2. 过度清洗 bad case 校验

目标：

证明新规则不会把旧规则误删的正常行再次清掉。

必须覆盖样本：

| 样本 | 旧问题 | 新规则期望 |
| --- | --- | --- |
| `300451.SZ 2015-06-01` | 无人报价/全 0 或部分 0 bar 被旧规则过滤 | 不因 OHLC 等于 0 被删除 |
| `600988.SH 2011-12-12 09:34:00` | `low=0` 但有成交，被旧规则过滤 | 不因单个 OHLC 为 0 被删除 |

计划动作：

1. 对 bad case 日期做 `clean_next` 小窗口写入。
2. 直接查询 `clean_next`，确认目标行存在。
3. 对比 raw，确认行未丢。

阶段完成标准：

1. 以上 bad case 均存在于 `clean_next`。
2. 查询结果写入本文执行记录。
3. 若任一 bad case 被过滤，停止全量构建。

### M3. 全量 clean_next 构建

目标：

完成约 45 亿行级别 raw 到正式 clean candidate 的全量构建。

计划范围：

```text
freqs=1,5,15,30,60
start_date=全量 raw 起始日期
end_date=全量 raw 截止日期
output=research/stk_mins_by_date_clean_next
```

执行原则：

1. 按分区逐个写入。
2. 每个分区 `_tmp -> 校验 -> replace`。
3. 单分区冲突即停止。
4. 不在失败后自动跳过。
5. 保留 run_id 和摘要。

阶段完成标准：

1. 全量分区写入完成。
2. 输出总行数、过滤总数、过滤原因分布。
3. `duplicate_conflict_payload=0`。
4. 字段门禁全量通过。

### M4. 全量基础审计

目标：

确认 `clean_next` 的基础数据质量。

审计项：

1. schema 全量一致。
2. 无重复 key：
   `(ts_code, freq, trade_time)`
3. 无身份无法解释数据。
4. 无退市股票。
5. 无上市日前数据。
6. 无 `high < low`。
7. 无负数 `vol/amount`。
8. 保留 `exchange/vwap` 字段。

阶段完成标准：

1. 基础审计没有 `failed`。
2. 若出现 `needs_review`，必须输出账本或 CSV，不直接修。

### M5. 全量完备性与连续性审计

目标：

确认每只股票、每个交易日、每个 freq 的日内 bar 数符合交易时段口径。

审计口径：

1. 常规日盘：
   `09:30~11:30` 与 `13:01~15:00`

2. 盘后交易：
   `15:01~15:30`

3. 盘后 bar 属于可解释额外 bar，不直接判错。

4. 停牌、源站缺失、新股上市首日等情况必须进入账本，不得拍脑袋过滤。

阶段完成标准：

1. 输出全量问题账本。
2. 问题按类型归类。
3. 明确哪些是已知口径，哪些需要人工判断，哪些需要专项修复。

### M6. 是否晋升正式 clean 的决策

目标：

在 `clean_next` 审计通过后，再决定是否替换正式 clean 路径。

本阶段之前禁止：

1. 删除旧错误 clean。
2. 把 `clean_next` 重命名为正式 clean。
3. 重建 derived。
4. 重建 research by symbol month。
5. 重建技术指标。

阶段完成标准：

1. 用户确认 `clean_next` 可作为正式 clean。
2. 单独出晋升或替换方案。
3. 再执行后续 derived/research/indicator 重建。

执行结果（2026-05-13）：

用户已确认：

1. 删除旧错误 clean。
2. 后续使用 `research/stk_mins_by_date_clean_next` 继续推进 derived、symbol-month、indicator 等工作。

实际执行：

```text
deleted=/Volumes/datasource/goldenshare-tushare-lake/research/stk_mins_by_date_clean
kept=/Volumes/datasource/goldenshare-tushare-lake/research/stk_mins_by_date_clean_next
```

删除后验证：

```text
research/stk_mins_by_date_clean exists=false
research/stk_mins_by_date_clean_next exists=true
research/stk_mins_by_date_clean_next size=63G
```

说明：

本阶段没有把 `clean_next` 重命名为 `clean`，也没有重建 derived、symbol-month 或指标层。后续所有下游重建方案必须显式读取 `research/stk_mins_by_date_clean_next`，不得再引用已删除的错误 schema clean。

## 6. 停止条件

遇到以下任一情况，必须停止并汇报：

1. 输出字段不等于 11 列正式 schema。
2. 出现 `trade_date/source_ts_code/identity_id` 物理列。
3. bad case 被过滤。
4. `duplicate_conflict_payload > 0`。
5. 写入目标不是 `clean_next`。
6. 旧错误 clean 被改动。
7. raw 被改动。
8. 发现磁盘、权限、读写异常。
9. 发现未登记 P0 风险。

## 7. 执行记录

### 2026-05-13

已建立本文。后续每个阶段完成后，必须把命令、输出摘要、异常和下一阶段准入判断回写到本节。

#### M0 代码入口与字段门禁

执行命令：

```bash
lake_console/.venv/bin/python -m pytest -q lake_console/backend/tests/test_stk_mins_clean_service.py
```

结果：

```text
8 passed
```

已确认：

1. 新命令为 `rebuild-stk-mins-by-date-clean-next-range`。
2. 新命令只写 `research/stk_mins_by_date_clean_next`。
3. 单元测试覆盖：`OHLC=0` 或部分 OHLC 为 `0` 的行不会被正式 clean_next 规则误删。
4. 单元测试覆盖：输出物理 schema 严格为 11 列，且不包含 `trade_date/source_ts_code/identity_id`。
5. 单元测试覆盖：目标分区已存在且未显式传 `--replace-existing` 时拒绝覆盖。

#### M1 2026 年 3 月写入验证

执行命令：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli rebuild-stk-mins-by-date-clean-next-range \
  --apply \
  --replace-existing \
  --freqs 1,5,15,30,60 \
  --start-date 2026-03-01 \
  --end-date 2026-03-31 \
  --sample-limit 10
```

结果摘要：

```text
run_id=20260512T203023Z-rebuild-stk-mins-clean-next
partitions=110
raw_rows=38,713,994
kept_rows=38,713,994
filtered_rows=0
duplicate_reasons={}
filter_reasons={}
status=success
elapsed_seconds=31.463
```

物理 schema 校验命令：

```bash
duckdb -c "select name, type from parquet_schema('/Volumes/datasource/goldenshare-tushare-lake/research/stk_mins_by_date_clean_next/freq=1/trade_date=2026-03-02/part-000.parquet') where name not like 'schema%';"
```

校验结果：

```text
ts_code, freq, trade_time, open, close, high, low, vol, amount, exchange, vwap
```

禁止字段校验命令：

```bash
duckdb -c "select count(*) as physical_forbidden_cols from parquet_schema('/Volumes/datasource/goldenshare-tushare-lake/research/stk_mins_by_date_clean_next/freq=1/trade_date=2026-03-02/part-000.parquet') where name in ('trade_date','identity_id','source_ts_code');"
```

校验结果：

```text
physical_forbidden_cols=0
```

说明：

DuckDB `read_parquet` 读取 Hive 分区路径时会自动显示虚拟分区列 `trade_date`。这不是 Parquet 物理列。字段门禁以 `parquet_schema(...)` 的物理 schema 为准。

#### M2 过度清洗 bad case 校验

已写入并复核以下样本分区：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli rebuild-stk-mins-by-date-clean-next-range \
  --apply \
  --replace-existing \
  --freqs 5 \
  --start-date 2015-06-01 \
  --end-date 2015-06-01 \
  --sample-limit 5

lake_console/.venv/bin/python -m lake_console.backend.app.cli rebuild-stk-mins-by-date-clean-next-range \
  --apply \
  --replace-existing \
  --freqs 1 \
  --start-date 2011-12-12 \
  --end-date 2011-12-12 \
  --sample-limit 5
```

`300451.SZ 2015-06-01 freq=5` 复核结果：

```text
row_count=49
zero_or_partial_zero_count=11
min_time=2015-06-01 09:30:00
max_time=2015-06-01 15:00:00
```

结论：

`OHLC=0` 或部分 OHLC 为 `0` 的有效无人报价 bar 没有被正式 clean_next 规则误删。

`600988.SH 2011-12-12 09:34:00 freq=1` 复核结果：

```text
ts_code=600988.SH
freq=1
trade_time=2011-12-12 09:34:00
open=9.35
close=9.36
high=9.36
low=0.0
vol=2800
amount=26200.0
exchange=XSHG
vwap=9.36
```

结论：

`low=0` 但有成交的行没有被正式 clean_next 规则误删，`exchange/vwap` 字段也保留在输出中。

下一阶段准入判断：

M0/M1/M2 均通过，允许进入 M3 全量 clean_next 构建。

#### M3 全量 clean_next 构建

执行命令：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli rebuild-stk-mins-by-date-clean-next-range \
  --apply \
  --replace-existing \
  --freqs 1,5,15,30,60 \
  --sample-limit 20
```

结果摘要：

```text
run_id=20260512T203519Z-rebuild-stk-mins-clean-next
partitions=21,045
raw_rows=4,576,238,458
kept_rows=4,428,800,144
filtered_rows=147,438,314
filter_reasons={
  before_list_date: 10,281,480,
  delisted_security: 137,156,532,
  invalid_volume_amount: 302
}
duplicate_reasons={}
status=success
elapsed_seconds=4199.429
```

说明：

1. `filtered_rows` 是 raw -> clean_next 的清洗过滤量，不代表 clean_next 里仍有这些问题。
2. `delisted_security` 表示按当前口径剔除退市股票全部分钟线。
3. `before_list_date` 表示剔除上市日前分钟线。
4. `invalid_volume_amount=302` 表示剔除负数成交量或成交额行。
5. `duplicate_reasons={}`，说明本轮未遇到同键重复冲突。
6. 构建期间未修改旧错误 clean、未修改 raw、未重建 derived/research/indicator。

下一阶段准入判断：

M3 构建成功，允许进入 M4 全量基础审计。

#### M4 全量基础审计

为避免旧错误 clean 审计口径污染正式 candidate，本轮新增并使用 clean_next 专用只读审计入口：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli audit-stk-mins-by-date-clean-next \
  --freqs 1,5,15,30,60 \
  --sample-limit 20
```

结果摘要：

```text
operation=audit_stk_mins_by_date_clean_next
dataset_layer=research/stk_mins_by_date_clean_next
partitions=21,045
issue_count=0
issue_type_counts={}
status=success
write_intent=false
schema=[
  ts_code,
  freq,
  trade_time,
  open,
  close,
  high,
  low,
  vol,
  amount,
  exchange,
  vwap
]
```

审计覆盖：

1. 物理字段严格为正式 11 列。
2. 不包含 `trade_date/source_ts_code/identity_id` 物理列。
3. 无重复 key：`(ts_code, freq, trade_time)`。
4. 无身份账本无法解释的 `ts_code`。
5. 无退市股票残留。
6. 无上市日前数据残留。
7. 无结构性非法价格：缺失/无法解析 OHLC、`high < low`。
8. 无负数 `vol/amount`。

注意：

`OHLC=0` 或部分 OHLC 为 `0` 不在 M4 中直接判错。该口径用于避免再次误删无人报价或源站特殊 bar。

下一阶段准入判断：

M4 通过，允许进入 M5 全量完备性与连续性审计。

#### M5 全量完备性与连续性审计

执行命令：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli audit-stk-mins-clean-next-completeness \
  --freqs 1,5,15,30,60 \
  --sample-limit 20 \
  --write-ledger
```

结果摘要：

```text
operation=audit_stk_mins_clean_next_completeness
dataset_layer=research/stk_mins_by_date_clean_next
partitions=21,045
issue_count=14,583
issue_type_counts={
  extra_intraday_bar: 1,015,
  missing_intraday_bar: 13,568
}
status_counts={
  failed: 1,015,
  needs_review: 13,568
}
status=failed
ledger=/Volumes/datasource/goldenshare-tushare-lake/manifest/stk_mins_quality/clean_next_completeness_issue_ledger.parquet
ledger_rows=14,583
write_intent=true
```

问题账本聚合：

```text
extra_intraday_bar   freq=5   count=253  date=2024-10-30
extra_intraday_bar   freq=15  count=254  date=2024-10-30
extra_intraday_bar   freq=30  count=254  date=2024-10-30
extra_intraday_bar   freq=60  count=254  date=2024-10-30
missing_intraday_bar freq=30  count=13,568 date_range=2022-07-15~2022-12-30
```

初步解释：

1. `extra_intraday_bar` 集中在 `2024-10-30` 的 `5/15/30/60` 分钟线，符合之前已知的“多频率混入 1min”问题特征，需要后续专项用同日 1min 重建对应频率。
2. `missing_intraday_bar` 集中在 `2022-07-15~2022-12-30` 的 `freq=30`，符合之前已知的“2022 北交所 30min 缺失 bar_count=6”问题特征，需要后续专项用 15min 重建 30min。
3. M5 只写问题账本，不修改 `clean_next`、不修改旧错误 clean、不修改 raw、不重建 derived/research/indicator。

专项处理记录：

1. `2024-10-30` 多频率混入 `1min` 专项已完成，执行记录见 [stk_mins clean 2024-10-30 多频率混入 1min 专项修复方案 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-clean-20241030-multifreq-repair-plan-v1.md)。
2. `2022-07-15~2022-12-30` 北交所 `30min` 缺失（`bar_count=6`）专项已完成，执行记录见 [stk_mins clean 2022 北交所 30min 缺失专项修复方案 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-clean-2022-bj-freq30-repair-plan-v1.md)。
3. 旧账本仍记录原始问题清单；专项修复是否成功必须以分区直读校验或重新运行完备性审计为准，不能只看旧账本是否仍有历史记录。

下一阶段准入判断：

M5 初始账本中的两个已知专项均已完成，并已在后续全量完备性复审中确认无残留问题。

#### M5 专项二：2022 北交所 30min 缺失修复

专项方案：

[stk_mins clean 2022 北交所 30min 缺失专项修复方案 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-clean-2022-bj-freq30-repair-plan-v1.md)

执行说明：

历史执行时使用过本专项 repair 命令完成 `dry-run -> apply`。该 repair 命令已在 2026-05-14 下线，本文只保留执行结果摘要。

执行结果摘要：

```text
run_id=20260513T021617Z-repair-clean-next-2022-bj-freq30
affected_trade_dates=115
affected_codes_total=13,568
affected_unique_codes=161
old_affected_rows_total=81,408
rebuilt_rows_total=122,112
target_rows_before_total=4,934,172
target_rows_after_total=4,974,876
missing_vwap_rows=0
status=success
```

修复后 scoped audit：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli audit-stk-mins-clean-next-completeness \
  --freqs 30 \
  --start-date 2022-07-15 \
  --end-date 2022-12-30 \
  --sample-limit 20

lake_console/.venv/bin/python -m lake_console.backend.app.cli audit-stk-mins-by-date-clean-next \
  --freqs 30 \
  --start-date 2022-07-15 \
  --end-date 2022-12-30
```

验证结果：

```text
completeness scoped audit: partitions=115, issue_count=0, status=success
base scoped audit: partitions=115, issue_count=0, status=success
schema=ts_code,freq,trade_time,open,close,high,low,vol,amount,exchange,vwap
```

结论：

`2022-07-15~2022-12-30` 北交所 `30min bar_count=6` 问题已在正式 `clean_next` 中修复。旧问题账本仍是原始问题清单，不会自动反映修复后的状态；后续以重新运行完备性审计结果为准。

#### M5 全量完备性复审

执行命令：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli audit-stk-mins-clean-next-completeness \
  --freqs 1,5,15,30,60 \
  --sample-limit 50 \
  --write-ledger
```

结果摘要：

```text
operation=audit_stk_mins_clean_next_completeness
dataset_layer=research/stk_mins_by_date_clean_next
partitions=21,045
freqs=1,5,15,30,60
issue_count=0
issue_type_counts={}
status=success
write_intent=true
```

本次复审结论：

1. `clean_next` 全量完备性审计通过。
2. `2024-10-30` 多频率混入 `1min` 问题未复现。
3. `2022-07-15~2022-12-30` 北交所 `30min bar_count=6` 问题未复现。
4. 当前没有已知待修复项。

账本修正：

全量复审通过后，发现旧账本文件仍保留历史问题行。已按本次复审结果将账本原子替换为空问题账本：

```text
path=/Volumes/datasource/goldenshare-tushare-lake/manifest/stk_mins_quality/clean_next_completeness_issue_ledger.parquet
run_id=20260513T031011Z-stk-mins-clean-next-issue-ledger-clear
existing_rows=14,583
new_records=0
written_rows=0
write_skipped=false
```

复核结果：

```text
rows=0
columns=issue_id,gate,issue_type,status,latest_ts_code,freq,trade_date,trade_time,expected_value,actual_value,evidence_dataset,evidence_ref,action,reason,created_at,resolved_at
```

下一阶段准入判断：

M5 已通过。允许进入 M6：是否晋升 `clean_next` 为正式 clean 的决策与方案。

M6 已按用户决策完成。下一步可以进入 derived / symbol-month / indicator 重建方案与执行，但每一轮仍必须单独列清目标、输入路径、输出路径和验证门禁。
