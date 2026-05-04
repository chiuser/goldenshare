# Local Lake prod-raw-db 导出接入规则与 Checklist

> 使用说明：
> - 本文用于设计“从生产 `goldenshare-db.raw_tushare` 只读导出到本地 Lake Parquet”的数据集接入方案。
> - 适用对象：后续希望优先从线上生产 raw 表生成本地 Parquet 的 Tushare 数据集。
> - 本文是规则与 Checklist，不是具体数据集方案。每个数据集仍需在 `docs/datasets/` 下落独立接入文档。
> - 本文只适用于 `lake_console` 的 `prod-raw-db` 导出模式，不适用于生产 Ops 同步链路。

---

## 0. 适用边界

### 0.1 允许做什么

`prod-raw-db` 只允许做一件事：

```text
从生产 goldenshare-db.raw_tushare 白名单表只读导出源站字段
-> 归一化为 Lake Parquet schema
-> 写入本地 GOLDENSHARE_LAKE_ROOT
```

### 0.2 不允许做什么

1. 不允许写远程 `goldenshare-db`。
2. 不允许访问 `ops`、`core`、`core_serving`、`core_serving_light`、`biz`、`app`、`platform` 等 schema。
3. 不允许读取生产任务状态、调度状态、Ops 状态、服务层数据或业务 API 表。
4. 不允许把 `api_name`、`fetched_at`、`raw_payload` 等 Goldenshare 自增系统字段导入 Lake。
5. 不允许 `select *`。
6. 不允许前端直接拼 SQL、数据库连接或表路径。
7. 不允许把 `prod-raw-db` 做成通用数据库浏览器。

---

## 1. 标准流程

每个数据集必须按以下顺序推进：

1. 数据集准入：确认 `dataset_key -> raw_tushare.<table>` 映射。
2. 源站字段定义：以 Tushare 接口文档输出字段定义 Parquet 字段白名单。
3. 生产 raw 表审计：核对 `raw_tushare.<table>` 字段、类型、主键、分区字段、系统字段。
4. 差异策略：逐项决定阻断、转换、重命名或排除。
5. Lake 写入策略：定义 layout、分区、文件切分、替换范围。
6. 开发导出能力：只读连接、显式字段投影、归一化、写入、进度输出。
7. 验收：字段白名单、schema、行数、抽样、DuckDB、权限边界全部通过。

禁止跳过 2-4 步直接写代码。

---

## 2. 数据集准入

### 2.1 基本信息

| 字段 | 值 | 说明 |
|---|---|---|
| `dataset_key` |  | Lake 数据集 key |
| 中文名 |  | 用户可见名称 |
| Tushare API |  | 源站接口名 |
| 源站文档路径 |  | `docs/sources/tushare/**` |
| 生产 raw 表 | `raw_tushare.` | 只能是 `raw_tushare` schema |
| 是否允许 prod-raw-db | 是 / 否 | 不允许时说明原因 |
| Lake 目标路径 |  | `raw_tushare/<dataset_key>/...` |

### 2.2 准入 Checklist

- [ ] 生产表位于 `raw_tushare` schema。
- [ ] 生产表在数据集白名单中。
- [ ] 数据集字段可从 Tushare 源站文档明确得到。
- [ ] 不依赖 `core`、`core_serving` 或 Ops 状态计算。
- [ ] 可以定义明确的 Lake 分区与替换范围。
- [ ] 可以用字段白名单完成显式投影。

只要有一项不满足，必须停止并转为专项评审。

---

## 3. 源站字段白名单

字段白名单必须来自 Tushare 接口文档输出参数，不能来自 `select *` 或数据库表字段猜测。

| 源站字段 | 源站类型 | 含义 | 是否写入 Parquet | Lake 类型 | DuckDB 类型 | 是否可空 | 类型选择理由 | 备注 |
|---|---|---|---:|---|---|---:|---|---|
|  |  |  | 是 / 否 |  |  | 是 / 否 |  |  |

规则：

1. 字段顺序默认与源站文档输出字段一致。
2. Lake 字段名默认使用源站字段名。
3. 不得额外添加 Goldenshare 系统字段。
4. 如必须重命名，必须写明原因和上下游影响。
5. 日期字段默认写为 Parquet `date`，时间戳默认写为 Parquet `timestamp`，不能因为目录分区是字符串就把内部字段写成字符串。
6. Tushare `float` 默认用 Parquet `double` 承接；整数默认优先评估 `int64`，避免成交量、金额类字段溢出。
7. 字段类型必须以 DuckDB `describe select * from read_parquet(...)` 可验证为准。

### 3.1 输入参数对齐

prod-raw-db 虽然不请求 Tushare，但仍必须保留源接口输入语义，避免导出范围和源站数据集语义错位。

| 源站输入参数 | 类型 | 含义 | prod-raw-db 是否支持 | 对应 raw 过滤条件 | 备注 |
|---|---|---|---:|---|---|
|  |  |  | 是 / 否 |  |  |

规则：

1. 支持的过滤条件必须能映射到 `raw_tushare` 白名单表字段。
2. 源站支持但 raw 表无法安全过滤的参数，必须标为“不支持”，不得拼接临时 SQL。
3. 用户输入不得作为 SQL 标识符；只能作为参数值绑定。

---

## 4. 生产 raw 表审计

### 4.1 表结构审计

| 检查项 | 结果 | 说明 |
|---|---|---|
| 表是否存在 |  |  |
| schema 是否为 `raw_tushare` |  |  |
| 主键 / 唯一键 |  |  |
| 可用于分区的字段 |  | 如 `trade_date`、`ann_date`、`month` |
| 系统字段 |  | 如 `api_name`、`fetched_at`、`raw_payload` |
| 行数范围 |  |  |
| 日期 / 月份范围 |  |  |

### 4.2 字段对账表

| 源站字段 | raw 表字段 | raw 类型 | Lake 类型 | 状态 | 处理策略 |
|---|---|---|---|---|---|
|  |  |  |  | 匹配 / 缺失 / 多余 / 类型差异 / 命名差异 |  |

字段状态定义：

1. `匹配`：字段存在，语义一致，可直接投影或简单类型转换。
2. `缺失`：源站字段在 raw 表不存在，默认阻断。
3. `多余`：raw 表有但源站没有，默认排除。
4. `类型差异`：字段语义一致但类型不同，必须定义转换。
5. `命名差异`：语义一致但字段名不同，必须定义映射。

强制结论：

- [ ] 源站输出字段已逐项核对。
- [ ] raw 表字段已逐项核对。
- [ ] Lake 字段白名单只来自源站输出字段。
- [ ] raw 表多余字段不会进入 SQL 投影。
- [ ] Parquet 类型已按 DuckDB 友好口径确认。

---

## 5. 差异策略

所有差异必须逐项登记，不允许用口头约定。

| 差异字段 | 差异类型 | 风险 | 策略 | 是否阻断 | 验收方式 |
|---|---|---|---|---:|---|
|  | 缺失 / 多余 / 类型差异 / 命名差异 |  | 阻断 / 排除 / 转换 / 映射 | 是 / 否 |  |

默认策略：

1. 源站字段缺失：阻断，不默默补空。
2. raw 表多余系统字段：排除。
3. raw 表多余业务字段：默认排除，除非源站文档确认。
4. 类型差异：必须定义确定性转换。
5. 日期字段：必须统一为 Lake 当前字段口径。
6. 数值字段：必须确认整数、浮点、Decimal 到 Parquet 类型的转换策略。

DuckDB 类型策略：

1. 日期：Parquet `date` / DuckDB `DATE`。
2. 时间戳：Parquet `timestamp` / DuckDB `TIMESTAMP`。
3. 月份键：保留字符串 `YYYYMM`，不要伪装成日期。
4. 布尔：Parquet `bool` / DuckDB `BOOLEAN`。
5. 整数：优先 `int64`，除非有充分证据证明 `int32` 不会溢出。
6. 浮点：默认 `double`。
7. 高精度小数：必须明确使用 `double` 还是 `decimal`，并说明业务是否接受精度折损。

---

## 6. SQL 投影规则

### 6.1 禁止写法

```sql
select *
from raw_tushare.daily;
```

### 6.2 允许写法

```sql
select
  ts_code,
  trade_date,
  open,
  high,
  low,
  close,
  pre_close,
  change,
  pct_chg,
  vol,
  amount
from raw_tushare.daily
where trade_date = :trade_date;
```

规则：

1. 字段列表必须来自字段白名单。
2. 表名必须来自数据集白名单。
3. 查询必须带上数据集定义的最小过滤条件。
4. 大表必须分页或流式读取。
5. 不允许拼接任意用户输入为 SQL 标识符。
6. SQL 投影字段必须和源站输出字段白名单一致；raw 表存在但源站文档没有的字段，默认不投影。

### 6.3 读取模式强制评审

`prod-raw-db` 的性能和安全性很大程度取决于读取模式。每个数据集方案必须先明确读取模式，不能默认写成“按日期循环查”。

| 读取模式 | 适用场景 | 禁止或风险 |
|---|---|---|
| `single_point_query` | 单日、单月、单个很小窗口的人工验证 | 不得用于全量或大区间导出 |
| `range_streaming_cursor` | 大区间、全量导出、可按范围过滤的大表 | 必须控制 fetch batch 和内存边界 |
| `paged_query` | 有稳定排序键和分页条件的数据集 | 必须说明分页键、结束条件和重复风险 |
| `full_fetchall` | 仅限极小快照表 | 大表禁止，容易撑爆内存 |

必须评审：

| 评审项 | 结论 | 说明 |
|---|---|---|
| 读取模式 |  | 优先考虑 `range_streaming_cursor` |
| SQL 次数估算 |  | 全量导出如果能 1 条范围 SQL 流式完成，不得拆成大量日期 SQL |
| DB 连接次数估算 |  | 大区间导出优先单连接、只读事务、服务端游标 |
| fetch batch 大小 |  | 例如每批 5000 或 10000 行 |
| 最大内存边界 |  | 说明单批、单分区或缓冲区上限 |
| 写入粒度 |  | 可与读取模式不同，例如区间流式读、按日分区写 |
| 进度输出粒度 |  | 当前分区、已读行数、已写分区数 |
| 为什么不用逐点查询 |  | 必须说明效率评估；若必须逐点，写明原因 |

规则：

1. 大区间或全量导出默认优先使用一个只读连接、一个只读事务、服务端游标、`fetchmany` 流式读取。
2. 读模式和写模式可以不同。允许范围流式读取，再按 Lake 分区逐个写入。
3. 不允许为了实现简单，把大区间导出拆成“每天一次连接 + 每天一条 SQL”。
4. 不允许对大表使用 `fetchall`。
5. 如果源表缺少适合范围读取的过滤字段，必须在数据集方案中标为风险，并单独评审。

---

## 7. Lake 写入策略

### 7.1 写入 layout

| 数据类型 | 推荐 layout | 示例 |
|---|---|---|
| 快照 / 主数据 | `current_file` | `raw_tushare/stock_basic/current/part-000.parquet` |
| 日频全市场 | `by_date` | `raw_tushare/daily/trade_date=YYYY-MM-DD/part-000.parquet` |
| 月频 | `by_month` | `raw_tushare/<dataset>/month=YYYY-MM/part-000.parquet` |
| 公告日 / 自然日 | `by_date_field` | `raw_tushare/dividend/ann_date=YYYY-MM-DD/part-000.parquet` |
| 超大表 | `partitioned_parts` | `part-00000.parquet`、`part-00001.parquet` |

### 7.2 写入规则

1. 必须使用 `_tmp -> 校验 -> 替换正式文件/分区`。
2. 禁止直接覆盖正式文件。
3. 每个分区写入后必须校验 Parquet 可读。
4. 大表必须控制单文件行数和单次内存占用。
5. 失败时不得污染正式分区。

---

## 8. 验收门禁

### 8.1 Schema 门禁

- [ ] Parquet 字段名等于字段白名单。
- [ ] Parquet 字段顺序与字段白名单一致，或已说明排序差异原因。
- [ ] Parquet 不包含 `api_name`。
- [ ] Parquet 不包含 `fetched_at`。
- [ ] Parquet 不包含 `raw_payload`。
- [ ] Parquet 类型符合 Lake 字段定义。
- [ ] DuckDB `describe select * from read_parquet(...)` 输出类型符合设计。

示例：

```bash
duckdb -c "
describe
select *
from read_parquet('<LAKE_ROOT>/raw_tushare/<dataset>/<partition>/*.parquet');
"
```

### 8.2 数据量门禁

- [ ] 单分区 row_count 等于生产 raw 投影查询结果。
- [ ] 区间导出分区数量符合预期。
- [ ] 空分区处理策略明确，不静默覆盖有效数据。

### 8.3 抽样门禁

- [ ] 随机抽样若干行，与生产 raw 表白名单投影结果一致。
- [ ] 日期字段口径一致。
- [ ] 数值字段转换无明显精度问题。
- [ ] 源站文档输出字段与 Parquet 字段没有未解释差异。

### 8.4 权限边界门禁

- [ ] 只读连接。
- [ ] 只访问 `raw_tushare`。
- [ ] 只访问白名单表。
- [ ] 没有 `select *`。
- [ ] 没有访问 Ops、core、serving、biz、app、platform 表。

### 8.5 Lake 门禁

- [ ] DuckDB 可读取目标 Parquet。
- [ ] Lake Console 数据集总览能看到文件事实。
- [ ] 命令示例不拼 SQL，只展示受控命令。
- [ ] `manifest/sync_runs.jsonl` 记录来源为 `prod_raw_db`。

### 8.6 读取模式门禁

- [ ] 已明确读取模式，并写明为什么不是低效逐点查询。
- [ ] 已估算 SQL 次数和 DB 连接次数。
- [ ] 大区间 / 全量导出使用流式读取或明确说明不能使用的原因。
- [ ] 大表没有使用 `fetchall`。
- [ ] 已说明读取模式与写入粒度的关系。

---

## 9. 开发落点 Checklist

| 模块 | 文件 | 是否需要 | 说明 |
|---|---|---:|---|
| Catalog | `lake_console/backend/app/catalog/datasets/*.py` |  | 标注是否支持 `prod_raw_db` |
| Source mode | `lake_console/backend/app/sync/**` |  | 增加 `from_prod_raw_db` 执行分支 |
| DB reader | `lake_console/backend/app/services/**` |  | 只读、白名单、显式投影 |
| Writer | `lake_console/backend/app/services/parquet_writer.py` |  | 复用 `_tmp -> 校验 -> 替换` |
| CLI | `lake_console/backend/app/cli/**` |  | 增加 `--from prod-raw-db` 或等价参数 |
| Frontend | `lake_console/frontend/**` |  | 只展示数据集事实和命令示例 |
| Tests | `tests/lake_console/**` |  | schema、权限、SQL、写入、DuckDB |
| Docs | `docs/datasets/*.md` |  | 每个数据集独立方案 |

---

## 10. 每个数据集方案必须回答的问题

1. 为什么该数据集适合从生产 raw 表导出？
2. 对应的 `raw_tushare` 表是什么？
3. 字段白名单是什么？
4. raw 表与源站字段有哪些差异？
5. 差异如何处理？
6. Lake 写入 layout 是什么？
7. 替换范围是什么？
8. 大小、文件数、单分区 row_count 大概是多少？
9. 如何验证没有导出系统字段？
10. 如何证明没有访问非 `raw_tushare` schema？
11. DuckDB 读取时每个字段是什么类型？
12. 是否存在历史分区 schema 迁移或重跑覆盖需求？
13. 读取模式是什么，为什么这是当前最高效且可控的方式？
14. SQL 次数、DB 连接次数、fetch batch、内存边界分别是多少？

---

## 11. 最终评审 Checklist

- [ ] 已阅读 `lake_console/AGENTS.md`。
- [ ] 已确认本轮是 `prod-raw-db` 开发轮次。
- [ ] 已完成数据集准入。
- [ ] 已完成源站字段白名单。
- [ ] 已完成源站输入参数与 prod-raw-db 过滤条件对齐。
- [ ] 已完成生产 raw 表字段审计。
- [ ] 已完成差异策略。
- [ ] 已完成读取模式评审。
- [ ] 已确认不是低效逐点连接或逐点查询模式；如必须使用，原因已写清。
- [ ] 已完成 Lake 写入策略。
- [ ] 已完成权限边界设计。
- [ ] 已完成验收命令设计。
- [ ] 已明确不改生产 Ops / TaskRun / Scheduler。
- [ ] 已明确前端不直连数据库、不拼 SQL。
