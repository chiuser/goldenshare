# `stk_mins clean_next` 与新湖 `silver_stock_daily` 股票代码集合审计 v1

- 状态：只读审计记录
- 审计日期：2026-05-30
- 审计范围：旧湖 `research/stk_mins_by_date_clean_next` 与新湖 Dagster `silver_stock_daily`
- 目的：确认 `stk_mins` 接入 Dagster 前，分钟线 clean_next 与股票日线在同一交易日的股票代码集合是否可以一一对应
- 不涉及：修改 Lake 文件、运行 Dagster job/sensor/backfill、注册分区、写入事件、修复数据

---

## 1. 背景

`stk_mins` 接入 Dagster 前，需要确认分钟线资产与当前新湖日线资产之间的股票代码口径。

前置审计已经确认：

1. 新湖 `silver_stock_basic` 只保留当前上市股票。
2. 新湖 `silver_stock_daily` 只保留能 join 到 `silver_stock_basic` 的当前有效代码。
3. 对部分代码变更股票，Tushare `stock_daily` raw 源层中，新代码已经带有旧日期历史。
   例如 `000022.SZ -> 001872.SZ`、`000043.SZ -> 001914.SZ`、`300114.SZ -> 302132.SZ`。

本轮审计的问题是：

> 在两个数据集都拥有的交易日内，旧湖 `clean_next` 的股票代码集合，是否与新湖 `silver_stock_daily` 的股票代码集合逐日一致？

结论先写清楚：**不能一一对应。** 差异主要来自停牌结构行和代码映射口径，不应把 strict equality 作为后续 `stk_mins` 接入门禁。

---

## 2. 审计数据源

### 2.1 旧湖分钟线 clean_next

```text
/Volumes/datasource/goldenshare-tushare-lake/research/stk_mins_by_date_clean_next/freq=*/trade_date=*/*.parquet
```

注意：

1. 旧湖正式路径历史分区文件名不完全固定为 `part-000.parquet`，历史目录存在 `part-00000.parquet`。
2. 因此本轮审计使用 `*.parquet`，而不是只读 `part-000.parquet`。
3. 旧湖正式 clean_next 五个频度都覆盖：
   - `freq=1`
   - `freq=5`
   - `freq=15`
   - `freq=30`
   - `freq=60`

### 2.2 新湖股票日线

```text
/Volumes/datasource/data_lake/silver/quote/stock_daily/trade_date=*/part-000.parquet
```

### 2.3 辅助事实源

停复牌：

```text
/Volumes/datasource/data_lake/silver/quote/stock_suspend_daily/trade_date=*/part-000.parquet
```

当前上市股票基础信息：

```text
/Volumes/datasource/data_lake/silver/basic/stock_basic/full/part-000.parquet
```

旧湖证券身份映射：

```text
/Volumes/datasource/goldenshare-tushare-lake/manifest/security_identity/security_identity_map.parquet
```

---

## 3. 比较范围

用户要求范围为 `2014-01-01` 到分钟线最新一个交易日。

实际数据中：

| 项目 | 结果 |
|---|---|
| 新湖 `silver_stock_daily` 起始日期 | `2014-01-02` |
| 旧湖 clean_next 最新交易日 | `2026-05-15` |
| 实际比较范围 | `2014-01-02` 至 `2026-05-15` |
| 比较交易日数 | `3004` |

`2014-01-01` 没有对应股票日线/分钟线交易日，因此实际起点为 `2014-01-02`。

---

## 4. 审计方法

为避免把分钟线明细拉回 Python，本轮使用 DuckDB 在本地直接完成分区扫描和聚合。

核心口径：

1. 对每个 clean_next 频度，先聚合为：

```text
trade_date + ts_code
```

2. 对 `silver_stock_daily` 同样聚合为：

```text
trade_date + ts_code
```

3. 在同一日期上做 full outer join，差异分为：

| 差异类型 | 含义 |
|---|---|
| `clean_only` | clean_next 有该 `trade_date + ts_code`，stock daily 没有 |
| `daily_only` | stock daily 有该 `trade_date + ts_code`，clean_next 没有 |

4. 对 `freq=1` 做进一步归因：
   - `clean_only` 是否可由 `silver_stock_suspend_daily` 解释。
   - `daily_only` 是否命中 `security_identity_map.latest_ts_code`。

---

## 5. 全频度结果

| clean_next 频度 | 对比天数 | 数量完全相等天数 | 不相等天数 | clean_next 日-股票总数 | stock daily 日-股票总数 | `clean_only` 日-股票 | `daily_only` 日-股票 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1min | 3004 | 154 | 2850 | 11,470,449 | 11,296,600 | 206,975 | 33,126 |
| 5min | 3004 | 148 | 2856 | 11,547,127 | 11,296,600 | 269,730 | 19,203 |
| 15min | 3004 | 131 | 2873 | 11,547,907 | 11,296,600 | 271,146 | 19,839 |
| 30min | 3004 | 111 | 2893 | 11,545,868 | 11,296,600 | 269,895 | 20,627 |
| 60min | 3004 | 148 | 2856 | 11,556,120 | 11,296,600 | 269,843 | 10,323 |

结论：

1. 任意频度都不能与 `silver_stock_daily` 逐日一一对应。
2. 差异不是偶发小样本问题，而是跨越绝大多数交易日的长期口径差异。
3. 不同分钟频度之间自身的代码集合也并不完全一致，因此不能用 `60min` 代表所有 clean_next 频度。

---

## 6. `freq=1` 重点归因

`freq=1` 是后续分钟线接入最核心的基础频度，因此本轮对它做了更细归因。

### 6.1 `clean_only`：全部可由停牌解释

`freq=1` 的 `clean_only` 结果：

| 项目 | 结果 |
|---|---:|
| `clean_only` 日-股票 | 206,975 |
| 命中 `silver_stock_suspend_daily` | 206,975 |
| 未命中停复牌 | 0 |
| 涉及交易日 | 2959 |
| 涉及股票代码 | 2939 |

解释：

`clean_next` 保留了停牌日的分钟结构行；`silver_stock_daily` 没有对应日线行情行。因此这类差异不应视为分钟线缺失或日线错误。

### 6.2 `daily_only`：主要由代码映射口径解释

`freq=1` 的 `daily_only` 结果：

| 归因 | 日-股票数 | 涉及交易日 | 涉及代码 |
|---|---:|---:|---:|
| `bse_mapping` | 23,423 | 360 | 239 |
| `namechange` | 3,446 | 1684 | 11 |
| 未命中身份映射 | 6,257 | 2837 | 195 |

典型 `namechange` 样本：

| 新代码 | 旧代码 | `daily_only` 天数 | 日期范围 |
|---|---|---:|---|
| `001914.SZ` | `000043.SZ` | 1372 | `2014-01-02` 至 `2019-12-13` |
| `001872.SZ` | `000022.SZ` | 936 | `2014-01-02` 至 `2018-12-20` |

典型 `bse_mapping` 样本：

| 新代码 | 旧代码 | `daily_only` 天数 | 日期范围 |
|---|---|---:|---|
| `920826.BJ` | `836826.BJ` | 224 | `2021-11-15` 至 `2024-11-28` |
| `920263.BJ` | `836263.BJ` | 223 | `2021-11-15` 至 `2024-11-28` |
| `920000.BJ` | `832000.BJ` | 221 | `2021-11-15` 至 `2024-11-28` |

解释：

`silver_stock_daily` 很多历史已经按“新代码”存在；旧湖 clean_next 在不少历史日期里仍缺这些“新代码”的分钟数据，或历史分钟线使用了旧代码/不同频度口径。因此 `daily_only` 不能直接解释为日线错误。

### 6.3 未命中身份映射的 `daily_only`

`freq=1` 中未命中身份映射的 `daily_only` 有 `6257` 个日-股票，涉及 `195` 个代码。

这部分需要后续单独审计，可能包括：

1. 分钟源缺失。
2. 分钟 clean_next 历史修复未覆盖。
3. 新股上市后 clean_next 未及时补齐。
4. 个别日期/频度修复口径不一致。

当前文档不把这部分直接定性为错误，只记录为后续 `stk_mins` 接入前需要继续分类的风险项。

---

## 7. 最近日期样本：2026-05-15

`2026-05-15` 是本轮比较范围内旧湖 clean_next 最新交易日。

`freq=1` 对比结果：

| 项目 | 数量 |
|---|---:|
| clean_next 股票数 | 5508 |
| stock daily 股票数 | 5495 |
| `clean_only` | 22 |
| `daily_only` | 9 |

`clean_only` 示例：

| 代码 | 名称 |
|---|---|
| `000004.SZ` | `*ST国华` |
| `000430.SZ` | `张家界` |
| `000638.SZ` | `*ST万方` |
| `300851.SZ` | `交大思诺` |
| `688287.SH` | `退市观典` |
| `920305.BJ` | `*ST云创` |

这些 `clean_only` 均可由停复牌表解释。

`daily_only` 全量列表：

| 代码 | 名称 | 上市日期 | 市场 |
|---|---|---|---|
| `000717.SZ` | `中南股份` | `1997-05-08` | 主板 |
| `001393.SZ` | `维通利` | `2026-05-15` | 主板 |
| `300459.SZ` | `汤姆猫` | `2015-05-15` | 创业板 |
| `301531.SZ` | `春光集团` | `2026-05-11` | 创业板 |
| `600982.SH` | `宁波能源` | `2004-07-06` | 主板 |
| `603407.SH` | `长裕集团` | `2026-05-11` | 主板 |
| `688499.SH` | `利元亨` | `2021-07-01` | 科创板 |
| `920178.BJ` | `锐翔智能` | `2026-05-15` | 北交所 |
| `920200.BJ` | `振宏股份` | `2026-05-07` | 北交所 |

---

## 8. 对“依赖项 3”的解释

此前讨论中的依赖项 3 是：`stk_mins` 接入是否需要处理股票代码变更/证券身份映射。

本轮审计给出的解释是：

1. `silver_stock_daily` 当前自身是干净的：旧代码不会和新代码同时存在。
2. 它之所以在部分历史上看起来连续，是因为 Tushare 日线源已经把新代码历史补到了旧日期。
3. 旧湖 clean_next 并不总是按同一个“新代码历史回填”口径保存分钟线。
4. 因此，不能把 `silver_stock_daily` 的代码集合直接当成 `stk_mins clean_next` 必须逐日相等的基准。

后续 `stk_mins` 接入 Dagster 时，至少要把差异拆成三类：

| 类型 | 判断方式 | 处理建议 |
|---|---|---|
| 停牌可解释差异 | `clean_only` 且命中 `silver_stock_suspend_daily` | 允许存在，不作为缺失 |
| 代码映射可解释差异 | `daily_only` 命中 `security_identity_map.latest_ts_code` | 需要明确是否引入身份映射归一 |
| 待审计差异 | 既非停牌，也非身份映射解释 | 进入缺失/修复专项 |

---

## 9. 后续建议

下一轮更有价值的审计不是继续做 strict count equality，而是：

1. 使用 `security_identity_map` 对 clean_next 代码做归一。
2. 排除停牌解释后的 `clean_only`。
3. 再比较“非停牌、身份归一后”的 clean_next 与 `silver_stock_daily` 股票集合。
4. 对剩余差异生成按原因分类的清单。

这才适合作为 `stk_mins` 接入 Dagster 前的数据门禁设计依据。

---

## 10. 审计边界

本轮审计没有做以下事情：

1. 没有修改任何 Parquet 文件。
2. 没有运行 Dagster job/sensor/backfill/automation evaluation。
3. 没有访问或修改正式 Dagster instance。
4. 没有注册分区或补录事件。
5. 没有把旧湖 clean_next 迁移到新湖。
6. 没有对 `daily_only` 的 `not_mapped_latest` 部分做最终定性。

