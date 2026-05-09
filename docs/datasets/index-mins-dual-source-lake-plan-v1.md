# 指数历史分钟行情 Lake 双模式接入方案 v1

- 版本：v1
- 状态：已落地（2026-05-09）
- 更新时间：2026-05-09
- 数据集：`index_mins`
- 对应生产数据集开发文档：[指数历史分钟行情（index_mins）数据集开发说明](/Users/congming/github/goldenshare/docs/datasets/index-mins-dataset-development.md)
- 源接口文档：[0419_股票历史分钟行情.md](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0419_股票历史分钟行情.md)

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
3. 不在本方案中新增 `derived` / `research` 层。
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

第一版只做 raw 层，不做 derived / research。

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

1. `index_mins` 是原始分钟线事实，第一版不需要额外派生层
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

## 9. 验收口径

### 9.1 字段契约验收

两种来源落到 Lake 后，字段必须完全一致：

```text
ts_code, freq, trade_time, close, open, high, low, vol, amount, exchange, vwap
```

不得引入任何系统字段。

### 9.2 双模式一致性验收

对同一稳定交易日、同一频率、同一 active pool 范围，抽样对比：

1. `--from tushare`
2. `--from prod-raw-db`

要求：

1. 字段集合一致
2. `ts_code + freq + trade_time` 粒度下可对齐
3. 样本行值一致

### 9.3 生命周期过滤验收

至少验证三类样本：

1. `trade_date < list_date` 的指数：
   - 不发请求 / 不判缺失
2. 有效期内的指数：
   - 有数据则写入
   - 无数据则计入缺失
3. 若后续出现 `exp_date` 非空指数：
   - 超过 `exp_date` 不发请求 / 不判缺失

---

## 10. 结论

`index_mins` 可以进入 Lake，而且应该按双模式设计：

1. `tushare`
2. `prod-raw-db`

但这不是简单复制 `daily` 的双模式，而是一个带明确 universe 与生命周期约束的分钟线专项：

1. 两种模式都共享同一 active pool
2. 两种模式都共享同一生命周期过滤规则
3. `prod-raw-db` 负责当前保留住的近历史
4. `tushare` 负责更早历史
5. 第一版不自动混源
6. 第一版只做 raw 层

后续编码必须严格按本文执行，不得退回到：

1. 只按 active pool、不看有效期
2. 把 530 个指数误当成每天静态全覆盖
3. 把 `prod-raw-db` 理解成整表自由扫
