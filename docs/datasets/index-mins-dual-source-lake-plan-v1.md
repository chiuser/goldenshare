# 指数历史分钟行情 Lake 双模式接入方案 v1

- 版本：v1
- 状态：双模式已落地；本地 `1min -> 15/30/60min` 补数已落地；90/120 历史结果因集合竞价锚点口径错误必须重建
- 更新时间：2026-08-07
- 数据集：`index_mins`
- 对应生产数据集开发文档：[指数历史分钟行情（index_mins）数据集开发说明](/Users/congming/github/goldenshare/docs/datasets/index-mins-dataset-development.md)
- 源接口文档：[0419_股票历史分钟行情.md](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0419_股票历史分钟行情.md)

> 2026-08-07 修正：`90min` / `120min` 第一根上午 K 线必须使用
> `09:30.close` 作为 open 和高低价锚点，并将 `09:30.vol/amount` 各计入一次。
> 修复范围、上下游影响和正式重建流程以
> [90m/120m 统一修复与重建 LLD](../../lake_console/docs/design/dagster-derived-minute-bars-90-120-contract-rebuild-low-level-design.md)
> 为准；本方案中与该 LLD 冲突的历史实现不得继续用于生成正式数据。

---

## 1. 目标与边界

本文定义 `index_mins` 接入 Local Lake 的第一版方案。

本方案的核心目标不是机械追某一层数据，而是：

```text
按“最佳事实优先”原则，同时支持：
1. 从生产 raw 数据库只读导出当前保留的指数分钟线历史；
2. 从 Tushare 直连补齐生产库不再保留的更早历史。
```

第一版明确支持双模式：

1. `--from prod-raw-db`
2. `--from tushare`

第一版不做：

1. 不自动在一次命令里混合两种来源。
2. 不把 `index_mins` 接到 `prod-core-db`。
3. 当前不自动混入任何未批准的新分钟频率；`90/120min` 仅作为本方案明确批准的本地派生层设计。
4. 不照搬生产环境当前 `_resolve_index_mins_targets()` 的实现缺陷。

---

## 2. 已确认事实

### 2.1 生产端当前的 Tushare 接入链

当前生产代码已经具备完整的 `idx_mins` 直连能力：

- 数据集定义：[index_series.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/index_series.py)
- unit planner：[unit_planner.py](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)
- request builder：[request_builders.py](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)
- source client：[source_client.py](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)
- row transform：[row_transforms.py](/Users/congming/github/goldenshare/src/foundation/ingestion/row_transforms.py)
- writer：[writer.py](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)
- raw ORM：[raw_index_mins.py](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_index_mins.py)

当前生产链路的真实行为：

1. 源接口：`idx_mins`
2. 写入表：`raw_tushare.index_mins`
3. 写入路径：`raw_only_upsert`
4. 候选代码池：`ops.index_series_active(resource='index_mins')`
5. 一个 unit = 一个 `ts_code` + 一个 `freq` + 一个时间窗口
6. 时间窗口由交易日 point/range 转成 datetime：
   - 单日：`09:00:00 ~ 19:00:00`
   - 区间：`start_date 09:00:00 ~ end_date 19:00:00`
7. 源端分页：
   - `offset_limit`
   - `page_limit = 8000`

### 2.2 远程 `raw_tushare.index_mins` 真实事实

只读审计结论：

1. 远程 raw 表字段与生产定义、源接口文档一致：
   - `ts_code`
   - `freq`
   - `trade_time`
   - `close`
   - `open`
   - `high`
   - `low`
   - `vol`
   - `amount`
   - `exchange`
   - `vwap`
2. 当前整表范围：
   - 最早：`2025-01-02 09:30:00`
   - 最晚：`2026-05-08 15:00:00`
3. 整表当前规模：
   - `27,142,284` 行
   - `530` 个指数代码
   - `5` 个频率
   - 精确重复组 `0`
4. 在稳定区间 `2026-01-05 ~ 2026-05-08`：
   - `1/5/15/30/60` 五个频率都完整覆盖 `80` 个开市日
   - 每天每个频率都正好覆盖 `530` 个指数
   - 没有发现“早于 list_date 就有分钟线”的脏数据

### 2.3 Active Pool 与有效期口径

这条口径已经拍板，后续不得偏离：

1. Lake 与生产环境使用**同一个** `index_mins` active pool。
2. `530` 个 active 指数只是候选 universe，不等于每天静态应全覆盖。
3. 是否“应当有数据”，要结合 `index_basic` 生命周期判断：
   - `trade_date < list_date`：无数据正常
   - `exp_date` 非空且 `trade_date > exp_date`：无数据正常
   - 只有在有效期内无数据，才算缺失

当前生产库审计事实：

1. `ops.index_series_active(resource='index_mins') = 530`
2. 这 `530` 个指数在 `core_serving.index_basic` 中：
   - `list_date` 全部存在
   - `exp_date` 当前全部为空
3. 当前有效期判断在现实里主要依赖 `list_date`

额外量化事实：

1. 这 `530` 个 active 指数里，有 `464` 个是在 `2009-01-01` 之后才定义的
2. 有 `116` 个是在 `2015-01-01` 之后才定义的
3. 有 `49` 个是在 `2020-01-01` 之后才定义的
4. 有 `4` 个是在 `2025` 年才定义的

这说明：Lake 在用 Tushare 回补更早历史时，如果不先按 `index_basic.list_date` 过滤，会产生大量本可避免的空请求。

---

## 3. 双模式总体设计

### 3.1 统一事实契约

两种来源必须共享同一份 Lake raw 字段契约：

| 字段 | 源接口类型 | 远程 raw 类型 | Lake 类型 | 是否导出 |
| --- | --- | --- | --- | --- |
| `ts_code` | `str` | `varchar` | `string` | 是 |
| `freq` | `str` | `varchar` | `string` | 是 |
| `trade_time` | `datetime` | `timestamp` | `timestamp` | 是 |
| `close` | `float` | `double precision` | `double` | 是 |
| `open` | `float` | `double precision` | `double` | 是 |
| `high` | `float` | `double precision` | `double` | 是 |
| `low` | `float` | `double precision` | `double` | 是 |
| `vol` | `float` | `double precision` | `double` | 是 |
| `amount` | `float` | `double precision` | `double` | 是 |
| `exchange` | `str` | `varchar` | `string` | 是 |
| `vwap` | `float` | `double precision` | `double` | 是 |

第一版明确不采用 `stk_mins` 的 `freq=int` 瘦身口径，原因：

1. `index_mins` 需要同时兼容 `tushare` 与 `prod-raw-db`
2. 源接口和远程 raw 事实都使用字符串频率：
   - `1min`
   - `5min`
   - `15min`
   - `30min`
   - `60min`
3. 当前规模远小于 `stk_mins`，没有足够证据要求第一版先做 `freq` 整数化瘦身

### 3.2 统一候选池与有效期过滤

Lake 运行时必须使用：

1. 候选池：`index_mins` active pool
2. 有效期判断：Lake 本地 `index_basic` 的 `list_date / exp_date`

运行期规则：

```text
候选集合 = index_mins active pool
有效集合 = 候选集合 ∩ index_basic 生命周期有效集合
```

每个指数在一次请求窗口中的有效时间段定义为：

```text
effective_start_date = max(request_start_date, list_date)
effective_end_date   = min(request_end_date, exp_date)  ; 若 exp_date 为空则用 request_end_date
```

若：

```text
effective_start_date > effective_end_date
```

则该指数在该次窗口中无效，直接跳过，不发请求，不判缺失。

### 3.3 不自动混源

双模式不等于自动混源。

第一版明确规则：

1. 一次 `sync-dataset index_mins` 只允许一个来源：
   - `tushare`
   - 或 `prod-raw-db`
2. 不在一次命令里自动把前半段走 Tushare、后半段走 prod-raw-db
3. 如果用户要补跨边界历史，应显式分两次跑

这样可以避免：

1. 同一 run_id 混入两套来源
2. 错误地把来源切换隐藏在实现细节里
3. 后续 audit 和重跑时无法解释数据来源

---

## 4. 候选池与本地依赖设计

### 4.1 候选池必须本地可读

虽然 `index_mins` active pool 与生产环境完全一致，但 `lake_console` 运行时不应直接把远程 `ops.index_series_active` 当业务依赖。

因此，方案要求：

1. `index_mins` active pool 必须先落到 Lake 本地 manifest
2. `index_mins` 同步任务运行时只读取本地 manifest
3. 该 manifest 与生产 `ops.index_series_active(resource='index_mins')` 保持同池语义

当前实现已经固定为：

```bash
lake-console sync-index-mins-active-pool
```

本地快照路径：

```text
manifest/index_universe/index_mins_active_pool.parquet
```

快照中当前至少包含：

1. `resource`
2. `ts_code`
3. `first_seen_date`
4. `last_seen_date`
5. `last_checked_at`

### 4.2 生命周期判断依赖本地 `index_basic`

有效期过滤使用 Lake 本地：

```text
manifest/index_universe/tushare_index_basic.parquet
```

或与其同源的 Lake `index_basic current` 文件。

原因：

1. `index_basic` 已经是 Lake 现成数据集
2. 其中包含：
   - `list_date`
   - `exp_date`
3. 这正是你拍板的分钟线有效性判断依据

---

## 5. 两种来源的具体方案

### 5.1 `--from tushare`

#### 5.1.1 适用场景

1. 回补生产库不再长期保留的更早历史
2. 远程 raw 尚未覆盖的时间段
3. 需要按 active pool + 生命周期直接向源站取事实

#### 5.1.2 请求单元

一个 unit =

- 一个 `ts_code`
- 一个 `freq`
- 一个该 code 在当前请求窗口中的**有效时间窗口**

也就是说，Lake 不能直接照搬当前生产 `_resolve_index_mins_targets()` 的做法。  
必须在 active pool 基础上，先叠加生命周期过滤，再生成 unit。

#### 5.1.3 请求参数

源接口参数仍然只允许：

- `ts_code`
- `freq`
- `start_date`
- `end_date`
- `limit`
- `offset`

Lake 不新增源接口不存在的业务参数。

#### 5.1.4 成功与缺失判定

1. 对无效指数不发请求
2. 对有效指数发请求
3. 若有效指数在该时间窗口返回 0 行：
   - 同步层面允许记为 `0 行成功`
   - 但 completeness / audit 层应能识别它属于“有效期内无数据”

### 5.2 `--from prod-raw-db`

#### 5.2.1 适用场景

1. 直接复用生产环境已经保存的指数分钟线历史
2. 避免在 Lake 侧重复请求 Tushare
3. 当前优先用于远程 raw 已明确保留的近历史数据

#### 5.2.2 当前远程 raw 的现实边界

当前远程表最早只有：

```text
2025-01-02
```

因此第一版要写明：

1. `prod-raw-db` 不是任意历史都可用
2. 对早于远程 raw 保留范围的历史，不应伪装成可从 `prod-raw-db` 获取

#### 5.2.3 读取策略

`prod-raw-db` 模式不按 `ts_code` 逐只查库。  
第一版建议：

1. 按 `freq`
2. 按 `trade_date` point 或 date range
3. 对本地 active pool 做 `ts_code` 白名单过滤
4. 只读查询 `raw_tushare.index_mins`

原因：

1. 远程 raw 当前已经没有 “早于 list_date 的脏数据”
2. 稳定区间内数据按日、按频率都非常规整
3. 这类查询比逐 code 请求更适合数据库导出

#### 5.2.4 仍然受生命周期口径约束

`prod-raw-db` 模式虽然不是向 Tushare 发请求，但缺失定义仍然不能只按 530 全覆盖。

必须继续用：

- active pool
- `index_basic.list_date / exp_date`

来定义“应有集合”。

---

## 6. Lake 存储布局

当前已落地的是 raw 层、derived 层与 research 层。  
`derived` 层的 `90/120min` 设计与实现见第 10 节。

目录：

```text
raw_tushare/index_mins_by_date/
  freq=1min/
    trade_date=YYYY-MM-DD/
      part-000.parquet
  freq=5min/
  freq=15min/
  freq=30min/
  freq=60min/
```

设计理由：

1. 当前已落地的正式事实层仍然是 `raw_tushare/index_mins_by_date`；`derived` 作为独立派生层单独设计与实现
2. 按 `freq + trade_date` 分区，和 `stk_mins by_date` 一样便于：
   - 单日替换
   - 小窗口补数
   - 按天审计
3. 当前每天每个频率行数可控：
   - `1min` 约 `127,730`
   - `5min` 约 `25,970`
   - `15min` 约 `9,010`
   - `30min` 约 `4,770`
   - `60min` 约 `2,650`
4. 这些量级第一版使用单文件 `part-000.parquet` 就足够，不需要像 `stk_mins` 那样优先做多 part 分片

---

## 7. 命令面设计

第一版建议继续使用通用：

- `plan-sync`
- `sync-dataset`

并为 `index_mins` 补充分钟线所需参数支持。

运行 `index_mins` 双模式同步前，先执行：

```bash
lake-console sync-index-mins-active-pool
```

### 7.1 单日

```bash
lake-console plan-sync index_mins --from prod-raw-db --trade-date 2026-05-08 --freq 30min
lake-console sync-dataset index_mins --from prod-raw-db --trade-date 2026-05-08 --freq 30min
```

```bash
lake-console plan-sync index_mins --from tushare --trade-date 2019-12-31 --freq 30min
lake-console sync-dataset index_mins --from tushare --trade-date 2019-12-31 --freq 30min
```

### 7.2 区间

```bash
lake-console plan-sync index_mins --from prod-raw-db --start-date 2026-04-01 --end-date 2026-04-30 --freq 30min
lake-console sync-dataset index_mins --from prod-raw-db --start-date 2026-04-01 --end-date 2026-04-30 --freq 30min
```

```bash
lake-console plan-sync index_mins --from tushare --start-date 2018-01-01 --end-date 2018-12-31 --freq 30min
lake-console sync-dataset index_mins --from tushare --start-date 2018-01-01 --end-date 2018-12-31 --freq 30min
```

### 7.3 多频率

```bash
lake-console plan-sync index_mins --from prod-raw-db --trade-date 2026-05-08 --freqs 1min,5min,15min,30min,60min
lake-console sync-dataset index_mins --from prod-raw-db --trade-date 2026-05-08 --freqs 1min,5min,15min,30min,60min
```

### 7.4 `ts_code` 调试

允许保留 `--ts-code`，但第一版只作为调试 / 小范围补数能力，并受两条限制：

1. 必须属于本地 `index_mins` active pool
2. 在目标时间窗口内必须通过 `index_basic` 有效期检查

---

## 8. 缺失与正常无数据的定义

这部分必须写死，后面实现和审计都按它来。

### 8.1 正常无数据

以下情况无数据都视为正常：

1. `trade_date < list_date`
2. `exp_date` 非空且 `trade_date > exp_date`
3. code 不在 `index_mins` active pool 中

### 8.2 缺失

以下情况无数据才视为缺失：

1. code 属于 `index_mins` active pool
2. `trade_date` 落在 `index_basic` 有效期内
3. 目标 `freq` 在该次同步范围内被显式要求同步
4. 结果却无数据

### 8.3 2026 稳定区间的事实验证

已核验：

- `2026-01-05 ~ 2026-05-08`
- `1/5/15/30/60`

在这段稳定区间里：

1. 每天每个频率应有效指数数 = `530`
2. 远程 raw 实际指数数 = `530`
3. `missing_codes = 0`

说明当前生产 raw 在稳定区间内与这套口径是对齐的。

---

## 9. 本地 `1min -> 15/30/60min` 补数方案

### 9.1 目标与边界

本节只讨论 `index_mins` 在 Lake 本地的低频分钟线补数。

目标：

1. 在 `prod-raw-db` 全量同步完成后，用 Lake 本地 `1min` 正式分区补齐缺失的 `15/30/60min` 正式分区。
2. 不再向 Tushare 重复请求这些已经可由本地 `1min` 事实严格推导出的低频分钟线。
3. 保持补数后的结果仍然属于正式 `raw_tushare/index_mins_by_date` 层，而不是新增 `derived` 层。

不做：

1. 不修补 `5min`，因为当前生产 raw 已完整覆盖 `2025-01-02 ~ 2026-05-08`。
2. 不覆盖已存在的正式目标分区。
3. 不在第一次方案里做任意频率重算，只支持：
   - `15min`
   - `30min`
   - `60min`
4. 不把这条链路设计成自动混源：补数只读 Lake 本地 `1min` 正式分区，不再读远程数据库，也不再请求 Tushare。

### 9.2 当前已审计缺口

按远程 `raw_tushare.index_mins` 当前真实事实，`2025` 年低频缺口是：

| 目标频率 | 缺失日期 |
| --- | --- |
| `15min` | `2025-07-11` |
| `30min` | `2025-07-04`、`2025-07-11`、`2025-07-18`、`2025-08-01` |
| `60min` | `2025-07-04`、`2025-07-11`、`2025-07-18`、`2025-07-25`、`2025-08-01` |

这些日期上，本地补数的事实前提是：

1. `1min` 分区已存在。
2. 缺失判断不能按静态 `530` 个指数，而必须按：
   - 本地 `index_mins` active pool
   - 本地 `index_basic.list_date / exp_date`
   共同定义的“该日有效指数集合”。

当前已审计的有效指数数：

| 日期 | 有效指数数 |
| --- | ---: |
| `2025-07-04` | `528` |
| `2025-07-11` | `528` |
| `2025-07-18` | `528` |
| `2025-07-25` | `530` |
| `2025-08-01` | `530` |

也就是说，`2025-07-04 / 07-11 / 07-18` 这三天并不是“应该有 530 个指数”，而是生命周期口径下只应有 `528` 个有效指数；这个口径必须贯穿补数全链路。

### 9.3 为什么不复用 `stk_mins` 的白名单修补模式

`stk_mins` 历史上曾有白名单式 1min 修补入口，只允许修补已写死的历史 source gap 日期。该入口已经下线。
`index_mins` 不应直接照搬这个策略，原因：

1. `index_mins` 是正在滚动维护的近历史分钟线数据集。
2. 当前看到的 `2025` 低频缺口属于滚动同步中的阶段性 source gap，不排除后续还会出现新的单日低频缺口。
3. `index_mins` 已经有完整的 active pool + 生命周期口径，可以在运行时严格判断“这一天哪些指数应当参与补数”。

因此，`index_mins` 第一版补数应采用：

```text
支持单日、单频率的通用 repair，
但运行时必须用强校验限制目标范围，
而不是把允许日期写死在代码里。
```

### 9.4 命令面设计

建议新增命令：

```bash
lake-console repair-index-mins-from-1m --freq 15min --trade-date 2025-07-11
lake-console repair-index-mins-from-1m --freq 30min --trade-date 2025-07-04
lake-console repair-index-mins-from-1m --freq 60min --trade-date 2025-07-25
```

第一版仅支持：

1. `--trade-date`
2. `--freq 15min|30min|60min`

第一版不支持：

1. `--start-date --end-date`
2. `--ts-code`
3. 覆盖已存在正式分区

原因：

1. 当前缺口都是“单日、整分区缺失”。
2. 先把单日原子修补收稳，风险最小。
3. 如果以后确实出现连续多日缺口，再考虑在此命令之上增加批量包装，而不是一开始就把主链做复杂。

### 9.5 数据来源与目标写入

输入只读本地 Lake：

```text
raw_tushare/index_mins_by_date/freq=1min/trade_date=YYYY-MM-DD/
```

输出写回正式 raw 层：

```text
raw_tushare/index_mins_by_date/freq=15min/trade_date=YYYY-MM-DD/
raw_tushare/index_mins_by_date/freq=30min/trade_date=YYYY-MM-DD/
raw_tushare/index_mins_by_date/freq=60min/trade_date=YYYY-MM-DD/
```

不写入：

1. `derived/`
2. `research/`
3. 远程数据库

### 9.6 分桶规则

这条必须按远程真实 `index_mins` 事实写死，不能套用想象中的分钟线规则。

已审计样本（`ts_code=000001.SH`, `trade_date=2026-05-08`）显示：

1. `1min` 下午分钟从 `13:01` 开始，而不是 `13:00`
2. `15min` 锚点是：
   - `09:30`
   - `09:45`
   - `10:00`
   - `10:15`
   - `10:30`
   - `10:45`
   - `11:00`
   - `11:15`
   - `11:30`
   - `13:15`
   - `13:30`
   - `13:45`
   - `14:00`
   - `14:15`
   - `14:30`
   - `14:45`
   - `15:00`
3. `30min` 锚点是：
   - `09:30`
   - `10:00`
   - `10:30`
   - `11:00`
   - `11:30`
   - `13:30`
   - `14:00`
   - `14:30`
   - `15:00`
4. `60min` 锚点是：
   - `09:30`
   - `10:30`
   - `11:30`
   - `14:00`
   - `15:00`

因此，补数分桶规则定义为：

1. 早盘第一根 `09:30` 始终是单独一桶。
2. 早盘剩余分钟按目标频率整块聚合：
   - `15min`：`09:31~09:45`，`09:46~10:00` ...
   - `30min`：`09:31~10:00`，`10:01~10:30` ...
   - `60min`：`09:31~10:30`，`10:31~11:30`
3. 午后不再有 `13:00` 单桶；直接从 `13:01` 开始按目标频率整块聚合：
   - `15min`：`13:01~13:15`，`13:16~13:30` ...
   - `30min`：`13:01~13:30`，`13:31~14:00` ...
   - `60min`：`13:01~14:00`，`14:01~15:00`

### 9.7 字段聚合口径

输出字段仍然保持 `index_mins` 当前正式 Lake 契约：

```text
ts_code, freq, trade_time, close, open, high, low, vol, amount, exchange, vwap
```

聚合规则：

1. `open`：桶内第一条 `1min.open`
2. `close`：桶内最后一条 `1min.close`
3. `high`：桶内 `high` 最大值
4. `low`：桶内 `low` 最小值
5. `vol`：桶内 `vol` 求和
6. `amount`：桶内 `amount` 求和
7. `exchange`：桶内第一条非空值；正常情况下同一指数同一日应保持稳定
8. `freq`：目标频率字符串：
   - `15min`
   - `30min`
   - `60min`
9. `trade_time`：桶结束时刻
10. `vwap`：
    - 若 `sum(vol) > 0`，则：
      - `vwap = round(sum(amount) / sum(vol), 3)`
    - 若 `sum(vol) == 0`，则：
      - 先取桶内最后一条 `1min.vwap`
      - 若仍为空，再退回桶内最后一条 `close`

### 9.8 运行时强校验

补数不是“只要有 `1min` 就往上卷”，而是必须通过以下校验：

1. 目标正式分区必须不存在；已存在则拒绝覆盖。
2. 源 `1min` 分区必须存在。
3. 先用本地 active pool + 本地 `index_basic` 计算出该日有效指数集合。
4. 该日每个有效指数都必须至少存在 `1min` 源行；否则失败，不允许静默跳过。
5. 该日每个有效指数的 `1min` 行必须满足当前 `index_mins` 会话规则，能被完整整分：
   - `15min`：每 code 期望 `17` 根
   - `30min`：每 code 期望 `9` 根
   - `60min`：每 code 期望 `5` 根
6. 写入后行数必须等于：
   - `effective_codes * per_code_bar_count`

按当前已审计缺口，这些期望值应当是：

| 频率 | 日期 | 有效指数数 | 每 code bars | 期望总行数 |
| --- | --- | ---: | ---: | ---: |
| `15min` | `2025-07-11` | `528` | `17` | `8976` |
| `30min` | `2025-07-04` | `528` | `9` | `4752` |
| `30min` | `2025-07-11` | `528` | `9` | `4752` |
| `30min` | `2025-07-18` | `528` | `9` | `4752` |
| `30min` | `2025-08-01` | `530` | `9` | `4770` |
| `60min` | `2025-07-04` | `528` | `5` | `2640` |
| `60min` | `2025-07-11` | `528` | `5` | `2640` |
| `60min` | `2025-07-18` | `528` | `5` | `2640` |
| `60min` | `2025-07-25` | `530` | `5` | `2650` |
| `60min` | `2025-08-01` | `530` | `5` | `2650` |

### 9.9 provenance 与 manifest

补数结果不在 parquet 字段里混入来源标记。  
provenance 只记录到 manifest summary，例如：

```text
operation = repair_index_mins_from_1m
source_freq = 1min
target_freq = 15min|30min|60min
repair_reason = source_gap
```

这样可以同时满足：

1. 正式 Lake 数据契约保持纯净
2. 后续审计仍能知道某个低频分区是“远程原样同步”还是“本地 1min 补数”

---

## 10. `derived / research` 层设计

### 10.1 目标与边界

这一步要补的是两层能力：

1. `derived`：为 `index_mins` 新增本地派生频率
   - `90min`
   - `120min`
2. `research`：继续把正式分钟线按 `ts_code + trade_month` 优化重排

当前这两层的边界必须明确拆开：

1. `derived` 负责**新增频率事实**
2. `research` 负责**重排已有事实**

当前设计结论：

1. `15/30/60min` 的 source gap repair 仍然写回正式 `raw_tushare`，不进入 `derived`
2. `90/120min` 才进入 `derived`
3. 当前已落地的 `research` 仍然只消费正式 raw 的 `1/5/15/30/60min`
4. `90/120min` 是否进入 `research`，仍待 derived 层真实验收后再单独评审，不在本轮范围内
5. 两层都不重新读取远程数据库，也不重新请求 Tushare

### 10.2 为什么 `index_mins` 现在可以新增 `90/120min`

现在和之前不同，已经具备三个前提：

1. 正式 raw 层已经完整承载：
   - `1min`
   - `5min`
   - `15min`
   - `30min`
   - `60min`
2. `2025-01-02 ~ 2026-05-08` 的 `1/5/15/30/60` 已经按 active pool + 生命周期口径补齐
3. `15/30/60min` 的低频 source gap 已经通过本地 `1min` repair 回写正式 raw，不再需要把“补缺口”误塞进 derived

因此，当前 `derived` 层的职责可以收得很纯：

```text
derived/index_mins_by_date 只负责 30min -> 90min、60min -> 120min 的本地派生。
```

### 10.3 derived 层的物理布局

目录建议：

```text
derived/index_mins_by_date/
  freq=90min/
    trade_date=YYYY-MM-DD/
      part-000.parquet
  freq=120min/
    trade_date=YYYY-MM-DD/
      part-000.parquet
```

输出字段与正式 raw 契约保持一致：

```text
ts_code, freq, trade_time, close, open, high, low, vol, amount, exchange, vwap
```

差异只在：

1. `freq = 90min | 120min`
2. 数据来源是本地派生，不是源站原始接口

### 10.4 `90min / 120min` 的派生规则

`index_mins` 当前的 `30min` / `60min` 日内锚点，与 `stk_mins` 已批准规则一致，因此可以沿用同一套日内聚合语义。

已确认的正式 raw 锚点：

1. `30min`
   - `09:30`
   - `10:00`
   - `10:30`
   - `11:00`
   - `11:30`
   - `13:30`
   - `14:00`
   - `14:30`
   - `15:00`
2. `60min`
   - `09:30`
   - `10:30`
   - `11:30`
   - `14:00`
   - `15:00`

派生规则定义为：

| 派生频率 | 输入 | 规则 |
| --- | --- | --- |
| `90min` | `30min` | 第一根使用 `09:30.close` 作为竞价锚点，并聚合 `10:00、10:30、11:00`；其余窗口按固定时间集合聚合 |
| `120min` | `60min` | 第一根使用 `09:30.close` 作为竞价锚点，并聚合 `10:30、11:30`；下午聚合 `14:00、15:00` |

必须写死的语义：

1. `09:30` 是集合竞价 K 线。它不作为普通区间 bar 使用，但其 `close` 必须作为第一根上午派生 K 线的 `open` 和 high/low 候选值，`vol/amount` 必须各计入一次；`09:30.open/high/low` 不进入派生公式。
2. `90min` 第一根由竞价锚点与以下普通 30 分钟 bar 共同形成：
   - `10:00`
   - `10:30`
   - `11:00`
   输出时间写 `11:00`
3. `90min` 第二根由：
   - `11:30`
   - `13:30`
   - `14:00`
   聚合，允许跨午休，锚点写 `14:00`
4. `90min` 第三根由：
   - `14:30`
   - `15:00`
   聚合，虽然实际只有 60 分钟，仍作为 `freq=90min` 的自然尾部 bar 保留，锚点写 `15:00`
5. `120min` 第一根由竞价锚点与以下普通 60 分钟 bar 共同形成：
   - `10:30`
   - `11:30`
   输出时间写 `11:30`
6. `120min` 第二根由：
   - `14:00`
   - `15:00`
   输出时间写 `15:00`
7. 除已明确接受的 `90min` 第三根外，任一固定窗口缺少必要 source bar 都必须 fail closed，不得用相邻 bar 补位，也不得生成部分结果。

由此得到每 code 每日的派生行数：

| 目标频率 | 每 code 派生 bars |
| --- | ---: |
| `90min` | `3` |
| `120min` | `2` |

### 10.5 derived 的输入来源与强校验

输入只读本地正式 raw 层：

```text
raw_tushare/index_mins_by_date/freq=30min/trade_date=YYYY-MM-DD/
raw_tushare/index_mins_by_date/freq=60min/trade_date=YYYY-MM-DD/
```

运行前必须通过以下 gate：

1. `90min` 要求 `30min` 正式分区存在，且该日行数等于：
   - `effective_codes(trade_date) * 9`
2. `120min` 要求 `60min` 正式分区存在，且该日行数等于：
   - `effective_codes(trade_date) * 5`
3. `effective_codes(trade_date)` 继续按：
   - 本地 `index_mins` active pool
   - 本地 `index_basic.list_date / exp_date`
   计算
4. 若任何有效指数缺少输入 bar，派生应失败，不允许静默跳过
5. `90min` 写入后行数必须等于：
   - `effective_codes * 3`
6. `120min` 写入后行数必须等于：
   - `effective_codes * 2`

这意味着：

1. 先补齐 raw
2. 再做 derived
3. 不能让 derived 成为“带缺口也先拼起来”的宽松层

### 10.6 derived 的字段聚合口径

字段聚合规则沿用现有 raw/repair 口径：

1. `open`：桶内第一根输入 bar 的 `open`
2. `close`：桶内最后一根输入 bar 的 `close`
3. `high`：桶内 `high` 最大值
4. `low`：桶内 `low` 最小值
5. `vol`：桶内 `vol` 求和
6. `amount`：桶内 `amount` 求和
7. `exchange`：桶内第一条非空值
8. `freq`：目标频率字符串：
   - `90min`
   - `120min`
9. `trade_time`：桶结束时刻
10. `vwap`：
    - 若 `sum(vol) > 0`
      - `vwap = round(sum(amount) / sum(vol), 3)`
    - 若 `sum(vol) == 0`
      - 先取桶内最后一根输入 bar 的 `vwap`
      - 若仍为空，再退回最后一根 `close`

### 10.7 derived 的执行边界

2026-08-07 起，backend 单日/区间 derived CLI 已删除。正式 90m/120m 只允许由 Dagster orchestrator 的 Silver writer、历史 bootstrap 和独立重建入口生成；任何本地调试都必须复用同一共享窗口合同，不能恢复第二套 backend 命令。

### 10.8 derived 的 provenance

derived 的 provenance 仍然只写 manifest，不进 parquet 字段。

建议 summary 字段至少包含：

```text
operation = derive_index_mins | derive_index_mins_range
source_layer = raw_tushare
targets = [90min, 120min]
trade_date / trade_dates = ...
source_rows = ...
written_rows = ...
```

### 10.9 research 层的物理布局

research 层建议采用和 `stk_mins` 相同的大方向：

```text
by_date         -> 同步/补数友好
by_symbol_month -> 研究查询友好
```

但 `index_mins` 的 source 只来自正式 raw 层。

目录建议：

```text
research/index_mins_by_symbol_month/
  freq=1min/
    trade_month=YYYY-MM/
      bucket=00/
        part-000.parquet
  freq=5min/
  freq=15min/
  freq=30min/
  freq=60min/
```

当前不进入 research 的频率：

1. 当前尚未纳入 research 的本地派生频率：
   - `90min`
   - `120min`
2. 任何尚未正式批准的新频率

也就是说，当前 research 的现实边界仍然是：

```text
1min / 5min / 15min / 30min / 60min
```

本轮只落地 `derived`，不同步扩展 research 到 `90/120min`。

### 10.10 bucket 策略

`index_mins` 当前 active pool 是 `530` 个指数。  
按稳定区间真实行数估算：

1. `1min` 每日约 `127,730` 行
2. 单月约 `2.5M ~ 3.0M` 行

第一版建议使用：

```text
bucket_count = 16
stable_bucket = hash(ts_code) % 16
```

理由：

1. 对 `530` 个指数来说，`16` 个 bucket 已足够把单月 `1min` 分散到每桶约 `16~19` 万行量级。
2. 相比 `32` 个 bucket，文件数量更少，研究层重排和后续月级读取更轻。
3. 仍保留稳定 bucket 语义，方便单指数查询先定位 bucket，再读单月单桶文件。

后续若 bucket_count 要改，必须提升 layout version，不允许在同一 research 目录里混用不同 bucket 规则。

### 10.11 research 重排的输入来源

research 重排只读本地正式 raw 层：

```text
raw_tushare/index_mins_by_date/freq=<freq>/trade_date=YYYY-MM-DD/part-000.parquet
```

也就是说：

1. 先完成双模式同步。
2. 若存在低频 source gap，先完成本地 `1min -> 15/30/60min` repair。
3. 然后再把已经稳定的 raw 事实重排进 research。

research 重排不做：

1. 不重跑 active pool 同步
2. 不重跑生命周期过滤后的远程拉取
3. 不在重排阶段补事实缺口

它只是：

```text
把已经稳定的 raw 分区，重新组织成更适合研究查询的 by_symbol_month。
```

### 10.12 completeness gate

`index_mins` 的 research 层不应像一个“尽量重排已有文件”的宽松任务。  
它应当先做 strict gate，再决定是否写入。

重排某个 `freq + trade_month` 之前，必须先验证：

1. 该月本地交易日历中的开市日集合已知。
2. 该月每个开市日都存在对应 `raw_tushare/index_mins_by_date` 正式分区。
3. 每个开市日的正式分区行数，等于：
   - `effective_codes(trade_date) * per_code_bar_count(freq)`

其中：

| 频率 | 每 code bars |
| --- | ---: |
| `1min` | `241` |
| `5min` | `49` |
| `15min` | `17` |
| `30min` | `9` |
| `60min` | `5` |

而 `effective_codes(trade_date)` 必须继续按：

1. 本地 `index_mins` active pool
2. 本地 `index_basic.list_date / exp_date`

来计算。

如果任何一天存在：

1. 分区缺失
2. 0 行分区
3. 行数不满足期望值

则该月该频率的 research 重排应直接失败，不允许产出“看起来可查、其实不完整”的月分区。

### 10.13 命令面设计

建议新增两条命令：

```bash
lake-console rebuild-index-mins-research --freq 1min --trade-month 2026-05
```

```bash
lake-console rebuild-index-mins-research-range --start-month 2025-01 --end-month 2026-05 --freqs 1min,5min,15min,30min,60min
```

第一版只支持：

1. `freq = 1min|5min|15min|30min|60min`
2. `trade_month = YYYY-MM`
3. 只从 raw 层重排

第一版不支持：

1. 直接从远程数据库重排
2. 直接从 Tushare 重排
3. 把缺失 raw 月份“尽量拼出来”
4. 覆盖 layout 版本不同的旧 research 月目录

### 10.14 manifest 与 provenance

research 重排的 provenance 继续只写 manifest，不进 parquet 字段。

建议 summary 字段至少包含：

```text
operation = research_index_mins
source_layer = raw_tushare
freq = 1min|5min|15min|30min|60min
trade_month = YYYY-MM
bucket_count = 16
input_trade_dates = [...]
source_rows = ...
written_rows = ...
```

范围重排则对应：

```text
operation = research_index_mins_range
```

### 10.15 当前建议的落地顺序

当前实现顺序已按下列路径收口：

1. 先补齐 raw 层：
   - 双模式同步
   - 必要时 `repair-index-mins-from-1m`
2. 再做单月 `rebuild-index-mins-research`
3. 最后做月区间 `rebuild-index-mins-research-range`

不要反过来先做 range。

---

## 11. 验收口径

### 11.1 字段契约验收

两种来源落到 Lake 后，字段必须完全一致：

```text
ts_code, freq, trade_time, close, open, high, low, vol, amount, exchange, vwap
```

不得引入任何系统字段。

### 11.2 双模式一致性验收

对同一稳定交易日、同一频率、同一 active pool 范围，抽样对比：

1. `--from tushare`
2. `--from prod-raw-db`

要求：

1. 字段集合一致
2. `ts_code + freq + trade_time` 粒度下可对齐
3. 样本行值一致

### 11.3 生命周期过滤验收

至少验证三类样本：

1. `trade_date < list_date` 的指数：
   - 不发请求 / 不判缺失
2. 有效期内的指数：
   - 有数据则写入
   - 无数据则计入缺失
3. 若后续出现 `exp_date` 非空指数：
   - 超过 `exp_date` 不发请求 / 不判缺失

---

## 12. 结论

`index_mins` 已经进入 Lake，而且应该按双模式 + raw 修补设计继续向下演进：

1. `tushare`
2. `prod-raw-db`

但这不是简单复制 `daily` 的双模式，而是一个带明确 universe 与生命周期约束的分钟线专项：

1. 两种模式都共享同一 active pool
2. 两种模式都共享同一生命周期过滤规则
3. `prod-raw-db` 负责当前保留住的近历史
4. `tushare` 负责更早历史
5. 第一版不自动混源
6. 当前正式事实层仍以 raw 为准；低频 source gap 通过本地 `1min -> 15/30/60min` repair 写回正式 raw 分区
7. `derived` 层已新增：
   - `90min`
   - `120min`
   当前已可通过本地正式 `30/60min` 分区重建
8. 当前已新增 `research/index_mins_by_symbol_month` 重排层，但现实边界仍然只覆盖：
   - `1min`
   - `5min`
   - `15min`
   - `30min`
   - `60min`

后续编码必须严格按本文执行，不得退回到：

1. 只按 active pool、不看有效期
2. 把 530 个指数误当成每天静态全覆盖
3. 把 `prod-raw-db` 理解成整表自由扫
