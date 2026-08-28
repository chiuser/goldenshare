# ETF 基础信息、分钟激活池与历史分钟线 DG 接入技术方案 v1

状态：初版，评审中；D1/D2/D4/D5/D7/D8/D9/D10 已确认，D3 存储细节待确认，D6 详细准入标准待 Prod 审计；本文没有授权开发、Bootstrap、事件补录或 Sensor 启用  
创建日期：2026-08-27  
适用范围：`lake_console/orchestrator` 正式 Dagster 数据湖

2026-08-27 评审记录：

1. D5 已确认：日常 ETF 分钟 Raw 使用“ETF 专属 TaskRun 完成 + Prod 物理覆盖通过”双门禁。
2. 分钟 Silver 的职责方向已确认：Silver 是 Raw 完整性审计通过后的标准准入层，不负责修补、补值、合成频率或重算行情；具体 blocking/WARN 和准入阈值等 Prod 同步结束、首次审计后再拍板。
3. 当前 Prod ETF 历史分钟仍在运行；任务结束后再由管理员安排首次只读审计，本方案当前不提前审计运行中结果。
4. D3 尚未最终拍板；本文已经补充推荐的不可变快照存法，供本轮讨论。
5. D1、D2、D4、D7、D8、D9、D10 已于 2026-08-27 按本文建议确认；D10 对激活池快照子路径的确认仍以 D3 最终结论为准。

关联资料：

- `docs/datasets/etf-mins-dataset-development.md`
- `docs/datasets/etf-mins-dataset-low-level-design-v1.md`
- `docs/architecture/etf-active-pool-low-level-design-v1.md`
- `docs/datasets/etf-basic-prod-raw-db-lake-export-plan.md`
- `lake_console/docs/design/dagster-index-mins-data-onboarding-plan.md`
- `lake_console/docs/design/dagster-index-mins-data-onboarding-low-level-design.md`
- `lake_console/docs/design/dagster-data-pipeline-performance-governance.md`
- `lake_console/docs/design/dagster-asset-schema-contract-design.md`

> 说明：`docs/datasets/etf-basic-prod-raw-db-lake-export-plan.md` 是旧 Lake Console 路径下的待评审方案，里面的 `raw_tushare/`、`manifest/` 和旧 Lake 根目录不能直接沿用到正式 DG。本方案只把它当作字段与历史审计证据，不把它当成正式 DG 实施依据。

---

## 1. 这次要解决什么问题

生产库已经有 ETF 基础信息、ETF 分钟同步激活池和 ETF 历史分钟线。现在要把这三类事实纳入 DG 管理的数据湖，并让历史初始化与以后日常更新都只读生产库，不再由 DG 重复请求 Tushare。

用一句话概括：

```text
Prod DB 是上游事实源，DG 负责把事实安全地落成 Raw，检查合格后再生成 Silver。
```

本方案覆盖三类资产族，而不是只建三张文件：

1. ETF 基础信息：回答“这只 ETF 是谁、何时成立和上市、当前是什么状态”。
2. ETF 分钟激活池：回答“当前生产分钟任务选择了哪些 ETF”。
3. ETF 历史分钟线：回答“这些 ETF 在各交易日、各频率有哪些原始分钟 K 线”。

三者不能混成一份“ETF 清单”。基础信息是证券身份和生命周期事实；激活池是当前业务选择；分钟线是行情事实。

---

## 2. 当前已经确认的事实

### 2.1 DG 当前缺口

按 2026-08-27 当前代码核验：

1. 正式 DG Catalog 中还没有 ETF 基础信息资产。
2. 正式 DG Lake 中还没有 `etf_mins` 激活池资产。
3. 正式 DG 中还没有 ETF 历史分钟 Raw/Silver 资产、Job、Sensor、Bootstrap 和 Check。
4. 现有指数分钟线已经证明“Prod DB 只读导出、按频率和交易日分区、Direct Lake Bootstrap、Runless Event Backfill”这条架构可用，但 ETF 不能照抄指数特有的 fallback、派生频率和有效指数池规则。

### 2.2 三张生产表的当前合同

| 资产族 | Prod 表 | 本次允许读取的业务字段 | 明确不进 Lake 的字段 |
| --- | --- | --- | --- |
| ETF 基础信息 | `raw_tushare.etf_basic` | `ts_code, csname, extname, cname, index_code, index_name, setup_date, list_date, list_status, exchange, mgr_name, custod_name, mgt_fee, etf_type` | `api_name, fetched_at, raw_payload` |
| ETF 分钟激活池 | `ops.etf_series_active`，只允许 `resource='etf_mins'` | `resource, ts_code, first_seen_date, last_seen_date, last_checked_at` | `created_at, updated_at` |
| ETF 历史分钟线 | `raw_tushare.etf_minute_bar` | `ts_code, freq, trade_time, open, close, high, low, vol, amount, vwap, exchange` | 无额外系统字段进入 Lake |

分钟线生产表主键是：

```text
(ts_code, freq, trade_time)
```

生产 ETF 分钟支持五个源频率：

```text
1min / 5min / 15min / 30min / 60min
```

### 2.3 激活池当前事实

此前生产验收确认 `ops.etf_series_active(resource='etf_mins')` 有 1,395 个不重复的 `.SH/.SZ` 代码，没有 `.OF` 代码。

这里的 `1,395` 只能作为当前审计基线，不能写成永久常量。正式文件和每次分钟运行都应记录实际 `code_count` 和排序后代码集合的 `code_set_hash`。

`first_seen_date`、`last_seen_date` 表示这个代码何时被生产激活池观察到，不等于 ETF 的成立、上市或退市日期，不能拿它们代替 ETF 生命周期。

### 2.4 正在重跑的生产任务

当前 ETF 历史分钟任务已经由用户重新发起，仍在运行。本方案不读取它的运行中结果作为最终完整性结论，也不触碰、停止或重启该任务。

此前对被发布重启中断的 TaskRun `9597` 做过只读审计。它的范围为 `2026-01-05..2026-06-30`、1,395 个 ETF、五个频率，共 9,765 个源端执行单元；中断前完成 5,729 个单元，已经提交 28,434,209 行，reject 和 deduplicate 都是 0。

这个样本只用于容量估算：按已完成部分线性外推，六个月全量约是 4,850 万行的量级。它不是重跑任务的最终行数，也不是完整性通过证明。

### 2.5 当前 DG 的硬边界

1. 正式 Lake 根目录只能是 `/Volumes/datasource/data_lake`。
2. 执行候选和 staging 只能在 `/Volumes/datasource/data_lake_staging`。
3. 禁止使用旧目录 `/Volumes/datasource/goldenshare-tushare-lake`。
4. 禁止使用 Kopia。
5. Prod DB 只允许显式字段、只读事务和有界查询；禁止 `SELECT *`。
6. 历史大批量写湖必须走 Direct Lake Bootstrap，不通过 Dagster backfill 生成海量 runs。
7. Bootstrap 先写物理文件并完成全量对账；Dagster materialization/check 事件另行补录，不能混在文件写入里顺手完成。
8. Silver 必须包含全部 Raw 业务字段，可以标准化类型和增加字段，但不能静默丢列。

---

## 3. 总体方案

```text
Prod raw_tushare.etf_basic
  -> Raw ETF Basic
  -> Silver ETF Basic（完整身份和生命周期，不等于激活池）
                         \
Prod ops.etf_series_active(resource='etf_mins')
  -> Raw ETF Mins Active Pool
  -> Silver ETF Mins Active Pool（经过基础信息关联和池规则检查）
                                  \
Prod raw_tushare.etf_minute_bar
  -> Raw ETF Mins 五频资产
  -> 完整性与质量审计
  -> Silver ETF Mins 五频资产
```

依赖关系用人话解释：

1. 先有 ETF 基础信息，才能判断代码身份和上市日期。
2. 再有激活池，才能冻结“这次分钟同步到底针对哪些 ETF”。
3. 最后导分钟线，才能对“代码、日期、频率”做可解释的覆盖审计。
4. 只有 Raw 审计结束后，才决定 Silver 到底需要做哪些清洗。

---

## 4. 三类资产的口径

### 4.1 第一类：ETF 基础信息

#### Raw 口径

建议资产名：`raw_tushare_etf_basic`  
建议路径：

```text
/Volumes/datasource/data_lake/raw/tushare/etf_basic/full/part-000.parquet
```

规则：

1. 只读 `raw_tushare.etf_basic`，一次全量快照。
2. 只导出 14 个业务字段，不带三个生产系统字段。
3. `setup_date/list_date` 按 Prod 中已经落地的 `DATE` 写入 Parquet。
4. 查询结果为空、主键重复、字段缺失或类型不符时，不覆盖正式文件。
5. 写入走 staging、回读校验和 `os.replace()` 原子替换。

历史审计在 2026-05-04 看到 3,266 行。这个数字已经可能变化，开发前和每次正式 Bootstrap 前都必须重新统计，不能硬编码。

#### Silver 口径

建议资产名：`silver_etf_basic`  
建议路径：

```text
/Volumes/datasource/data_lake/silver/basic/etf_basic/full/part-000.parquet
```

建议 Silver 保存完整 ETF 身份与生命周期：

1. 保留 Raw 的全部 14 个字段。
2. 统一代码和交易所的空白、大小写及日期/数值类型。
3. 保留 `L/D/P` 等源端实际状态，不只保留当前上市 ETF。
4. 不根据分钟激活池过滤 ETF，也不排除 `.OF`；是否可交易由下游用激活池判断。
5. `ts_code` 唯一，上市日期不得早于成立日期；不满足时 fail-closed 或进入明确的审计问题，不静默删除。

这样做的原因是：基础信息应该保留“完整名单”，激活池才负责表达“现在选了谁”。如果把 Silver Basic 直接裁成 1,395 个当前池代码，以后无法解释历史 ETF、退市 ETF和池变化。

### 4.2 第二类：ETF 分钟激活池

#### Raw 口径

建议资产名：`raw_prod_etf_mins_active_pool`  
建议路径：

```text
/Volumes/datasource/data_lake/raw/goldenshare_ops/etf_mins_active_pool/full/part-000.parquet
```

规则：

1. 只读 `ops.etf_series_active` 中 `resource='etf_mins'` 的记录。
2. 只导出 `resource, ts_code, first_seen_date, last_seen_date, last_checked_at`。
3. 不导出 `created_at/updated_at`，因为它们是 Goldenshare 系统审计字段，不是池业务事实。
4. 每次读取时记录代码数、排序后的代码集合 hash 和只读提取时间到 materialization metadata。
5. 空池、重复代码、非 `.SH/.SZ` 代码、resource 错配、数量超过约定上限时 fail-closed。

这一步需要在仓库规则中新增一个很窄的 Prod Ops 只读白名单。目前只批准了 `index_mins` 的同类例外，不能因为表名相似就默认 ETF 也已经获批。

#### Silver 口径

建议资产名：`silver_etf_mins_active_pool`。

建议第一版保留“不可变、可按内容定位”的 Silver 快照，而不只保留一个不断覆盖的 current 文件。

Raw 仍然是当前生产池镜像：

```text
/Volumes/datasource/data_lake/raw/goldenshare_ops/etf_mins_active_pool/
  full/part-000.parquet
```

它每次通过完整校验后原子替换，只表达“现在生产表里是什么”。

Silver 负责保留已经验收的历史版本：

```text
/Volumes/datasource/data_lake/silver/basic/etf_mins_active_pool/
  snapshot_date=YYYY-MM-DD/
  snapshot_id=YYYY-MM-DD__<snapshot_content_hash前12位>/
  part-000.parquet
```

例如：

```text
silver/basic/etf_mins_active_pool/
  snapshot_date=2026-08-27/
  snapshot_id=2026-08-27__a13c9f0e42b7/
  part-000.parquet
```

`snapshot_date` 是从 Prod 读取并验收该池的上海日期。`snapshot_id` 由日期和完整行内容 hash 组成：同一天、同一份内容重复执行时得到同一路径并直接复用；同一天池内容发生变化时得到新的 `snapshot_id`，旧文件不覆盖。

Silver 保留 Raw 五个字段，并增加以下治理字段：

| 字段 | 含义 |
| --- | --- |
| `snapshot_date` | 该快照被读取并验收的上海日期 |
| `snapshot_id` | 日期加内容 hash 前缀形成的稳定版本号 |
| `snapshot_at` | 实际读取完成时间，带时区 |
| `code_set_hash` | 只对排序后的 `ts_code` 集合计算完整 SHA-256，用来冻结分钟任务范围 |
| `snapshot_content_hash` | 对排序后的五个 Raw 业务字段整表计算完整 SHA-256，用来判断两份池是否完全相同 |

写入和使用规则：

1. 每个被分钟任务消费的池版本只写一个小 Parquet 文件。
2. 快照文件一经提升就不可变；修正必须产生新 `snapshot_id`，不能覆盖旧版本。
3. 同日、相同内容的重复运行复用已有文件，不制造重复快照。
4. 同日内容变化允许产生第二个快照，分钟任务必须明确绑定其中一个 `snapshot_id`。
5. 每个 Raw 分钟 materialization、Bootstrap 计划和最终报告都记录 `snapshot_id + code_set_hash`。
6. 物理分钟代码集合与绑定快照不一致时 fail-closed；不能自动改用“最新池”。
7. 不另建 `manifest` 或 current pointer；最新可用版本由已通过 blocking check 的快照分区确定。

快照检查包括：

1. 代码集合唯一且非空。
2. 全部代码都能关联到 `silver_etf_basic`。
3. 全部代码是 `.SH/.SZ`。
4. `first_seen_date <= last_seen_date`，`last_checked_at` 非空。
5. `code_set_hash` 和 `snapshot_content_hash` 都能从文件独立复算。

为什么建议这样保留：如果只保留 current 文件，池发生变化后无法复现“某次分钟任务当时用了哪些 ETF”。即使每个交易日保存一份，按 1,395 行和约 250 个交易日估算也只有约 35 万行/年；实际文件大小仍要在 sample 阶段测量，但行数量级很小。

### 4.3 第三类：ETF 历史分钟线

#### Raw 口径

建议五个资产：

```text
raw_etf_mins_1m
raw_etf_mins_5m
raw_etf_mins_15m
raw_etf_mins_30m
raw_etf_mins_60m
```

建议路径：

```text
/Volumes/datasource/data_lake/raw/tushare/etf_mins/
  freq=<1min|5min|15min|30min|60min>/
  trade_date=YYYY-MM-DD/part-000.parquet
```

Raw 规则：

1. 只读 `raw_tushare.etf_minute_bar`，不在 DG 中调用 Tushare。
2. 保留 11 个 Prod 业务字段和源端价格精度，不做两位小数裁剪。
3. 一份文件只包含一个交易日和一个频率。
4. 文件内主键按 `(ts_code, trade_time)` 唯一；加上路径频率后等价于生产主键。
5. `trade_date` 只作为物理分区键，从 `trade_time` 推导，不污染 Raw 源字段契约。
6. 每次运行必须冻结激活池 `code_set_hash`。计划与真正写文件之间池发生漂移时停止，不自动扩大或缩小范围。
7. 缺代码、缺 bar 或某频率全空不能一律自动补值；先按完整性审计原因分类。

建议新增专属动态分区：`cn_a_etf_mins_trade_days`。它不复用股票或指数分钟线的分区集合，避免一条链的缺口或修复影响另一条链。

#### Silver 口径

建议五个资产：

```text
silver_etf_mins_1m
silver_etf_mins_5m
silver_etf_mins_15m
silver_etf_mins_30m
silver_etf_mins_60m
```

建议路径：

```text
/Volumes/datasource/data_lake/silver/quote/etf_mins/
  freq=<1min|5min|15min|30min|60min>/
  trade_date=YYYY-MM-DD/part-000.parquet
```

Silver 的定位不是“清洗后尽量落库”，而是“Raw 完整性审计通过后才准入”。第一版冻结以下规则：

1. 保留 Raw 全部 11 个字段。
2. `trade_date` 只作为路径分区事实，不在第一版额外写成 Silver 业务列。
3. Raw 分区必须先通过 schema、日期/频率、主键、代码范围、行数和数值入库标准检查；任一 blocking 项不通过，整个分区不进入 Silver。
4. Silver 只做合同允许的稳定类型表达，不改变 OHLC、`vol`、`amount`、`vwap` 的有效数值，不裁剪价格精度。
5. Raw/Silver 的行数、业务主键集合和 11 个字段值必须逐项对账；不允许审计失败后静默丢行再让 Silver 变绿。
6. 需要修复的数据回到 Prod 或显式 Raw repair 处理，修复后重新审计；Silver 本身不承担修复。

在 Prod 完整性审计完成前，第一版明确不做：

1. 不用 5 分钟线补 15/30/60 分钟线。
2. 不生成 90/120 分钟线。
3. 不前向填充缺失 bar。
4. 不把零成交、停牌或源端空结果直接当脏数据删除。
5. 不重新计算或覆盖 `vwap`。
6. 不照抄股票分钟线的两位小数处理。

---

## 5. 建设顺序与阶段门禁

### P0：方案拍板

先确认本文第 14 节的决策项。未拍板的资产范围、路径、池快照和 Silver 清洗规则不能进入代码。

### P1：ETF 基础信息 Raw/Silver

先完成 ETF 基础信息，因为它是激活池关联和历史覆盖解释的基础。

验收重点：字段一列不少、系统字段一个不带、主键唯一、状态分布可解释、Raw 与 Prod 逐行对账、Silver 不裁成当前激活池。

### P2：ETF 分钟激活池 Raw/Silver

在基础信息可用后，再把 `resource='etf_mins'` 的池落湖，并做与 ETF Basic 的集合关联检查。

验收重点：代码集合、hash、`.SH/.SZ`、Basic 可关联性和快照可追溯。

### P3：等待当前 Prod 重跑结束并审计

这一步只审计生产库，不写 Lake。必须冻结：

1. 最终 TaskRun 身份和状态。
2. 用户输入日期范围与五频选择。
3. 当次激活池代码集合和 hash。
4. source/normalized/written/reject/deduplicate 计数。
5. 生产表最终最大时间和审计期间无继续写入的证据。

审计未通过，分钟 Bootstrap 不开始；但它不阻塞前面的 ETF Basic 和池资产开发。

### P4：分钟 Raw Direct Lake Bootstrap

按审计通过的日期范围和冻结池执行：

```text
只读 dry-run
  -> 小日期样本写 /private/tmp
  -> 分批写 data_lake_staging
  -> 候选文件回读校验
  -> os.replace 原子提升
  -> 每批 checkpoint
  -> 全量物理文件对账
```

不使用 Dagster backfill，不使用旧 Lake，不使用 Kopia，不覆盖不合格的既有正式文件。

### P5：冻结 Silver 入库标准并生成 Silver

根据 P3/P4 审计报告，明确哪些是：

1. 真正脏数据。
2. 合法的无交易或停牌。
3. ETF 生命周期导致的无数据。
4. 生产漏同步。
5. Tushare 源端本身缺失。

只有分类明确后，才把“哪些检查阻断准入、哪些只告警”写进 Silver LLD、SQL、测试和 checks。Silver 不修补 Raw；需要修复的数据回到 Prod 或显式 Raw repair，修复后重新审计。Raw 也不会因为 Silver 规则而被隐式重写。

### P6：事件补录与日常链路

物理文件全量对账通过后，单独审批：

1. 注册专属动态分区。
2. 为成功文件补 materialization event。
3. 为最近一段窗口补 blocking check event。
4. 启用默认 `STOPPED` 的日常 Sensor 并观察自然运行。

---

## 6. Prod DB 只读合同

### 6.1 允许表和过滤条件

| 表 | 用途 | 强制过滤 |
| --- | --- | --- |
| `raw_tushare.etf_basic` | 基础信息全量快照 | 无业务筛选；显式 14 列 |
| `ops.etf_series_active` | 分钟激活池 | `resource='etf_mins'`；显式 5 列 |
| `raw_tushare.etf_minute_bar` | 历史/日常分钟导出 | `freq`、半开时间区间、冻结代码集合；显式 11 列 |
| `ops.task_run` | 已确认的 Prod 完成门禁 | 已批准 ETF 专属窄例外；字段和任务身份必须在 LLD 中逐项白名单化 |

所有连接必须是 rollback-only 的只读事务。任何查询失败、返回未知字段、越界日期、池漂移或查询超预算都 fail-closed。

### 6.2 为什么分钟导出不能按 ETF 逐只查询

生产 Tushare 同步是“代码 × 频率 × 时间窗”的请求模型，但 DG 已经面对一张聚合后的 Prod 表，不应该继续复制这个扇出。

建议 DG 读取模型：

1. 日常：每个频率一条目标日范围查询，最多五条明细查询。
2. Bootstrap：每批最多 20 个交易日，每个频率一条范围流式查询，再由 DuckDB 按日拆成文件。
3. 全历史覆盖审计：使用一次或少量 `freq + trade_date` 聚合查询，不把全量明细装进 Python。
4. 任何明细转换和写 Parquet 都用 DuckDB set-based SQL，不做 Python 逐行处理。

---

## 7. Prod 完整性审计方案

### 7.1 审计前提

审计开始前必须确认当前重跑已经结束，并在审计窗口内没有继续写入 `raw_tushare.etf_minute_bar`。运行中的表快照只能看进度，不能给 Bootstrap 放行。

### 7.2 审计分五层

| 层次 | 要回答的问题 | 主要证据 |
| --- | --- | --- |
| 任务意图 | 这次到底要求同步哪些日期、代码和频率 | TaskRun 输入、计划快照、池 hash |
| 任务执行 | 所有 unit 是否完成，写入/拒绝是否对得上 | unit 状态、source/normalized/written/reject 计数 |
| 表结构 | 主键、字段、分区、频率是否符合合同 | PostgreSQL 元数据和有界聚合 |
| 数据覆盖 | 每个代码/日期/频率是否有应有数据 | `ts_code + freq + trade_date` 覆盖矩阵 |
| 数值质量 | 时间网格、OHLC、成交量金额、跨频聚合是否合理 | 聚合检查和有限样本 |

### 7.3 覆盖率不能只拿“当前 1,395 个”硬套历史

普通完整交易日的已验收参考根数是：

| 频率 | 每代码正常满日参考根数 |
| --- | ---: |
| 1min | 241 |
| 5min | 49 |
| 15min | 17 |
| 30min | 9 |
| 60min | 5 |

这些数字适合找异常，不代表每个 ETF、每个历史日期都必须强制满足。正式判定要同时考虑：

1. ETF `list_date` 和真实生命周期。
2. 交易日历。
3. 当次冻结激活池。
4. 停牌、零成交和合法源端空结果。
5. 生产任务实际输入范围。

激活池的 `first_seen_date/last_seen_date` 只能辅助解释池变化，不能冒充 ETF 上市/退市日期。

### 7.4 审计输出

最终报告至少给出：

1. 按日期、频率的行数和代码数。
2. 按代码、日期、频率的缺失和多余 bar 数。
3. 重复主键、越界时间、错频和池外代码。
4. OHLC 关系异常、负成交量/金额、空关键数值分布。
5. 跨频率可聚合对账差异及容差说明。
6. 每个缺口的 reason code 和有限样本。
7. “可 Bootstrap”“需先补 Prod”“合法无数据”三类结论。
8. 对 Silver 清洗规则的建议清单。

---

## 8. Bootstrap 与日常更新

### 8.1 历史 Bootstrap

Bootstrap 分成四个互不混写的步骤：

1. `dry-run`：只读 Prod 和目标目录，输出范围、池 hash、预计行数/文件数/磁盘/查询量、已有文件冲突和停止原因。
2. `sample`：只写 `/private/tmp`，验证一个小日期窗口的字段、行数、内存和耗时。
3. `apply`：显式确认后，按最多 20 个交易日一批写 staging、回读、原子提升，并保存 checkpoint。
4. `audit`：扫描正式 Raw 文件做 schema、分区、主键、总行数和 Prod 双向对账。

任一批失败，只停止当前批；已验收并提升的文件保留，续跑从 checkpoint 开始。禁止为了“省事”从头覆盖全部合格文件。

### 8.2 日常 Raw 更新

建议单独建立：

```text
raw_etf_mins_update_job
raw_etf_mins_update_job_sensor
```

Sensor 默认 `STOPPED`。热路径只看最近 10 个专属 expected trade dates，先判断 Lake 缺口，再做一次有界 Prod ready probe；每个 tick 最多提交一个最早可行动日期。

Raw Job 只选择五个分钟 Raw 资产。它只读依赖已经合格的 ETF Basic 和激活池，不把这些共享基础资产顺手放进同一个 Job 更新。

### 8.3 日常 Silver 更新

建议单独建立：

```text
silver_etf_mins_update_job
silver_etf_mins_update_job_sensor
```

Silver Sensor 只读 Lake，不访问 Prod。目标日五个 Raw 文件和 blocking checks 都通过后，才提交最早 Silver 缺口。

### 8.4 并发与冲突

1. 同一个 `trade_date + freq` 只能有一个 writer。
2. 目标文件已经存在时，先做完整合同校验；合法则复用，非法则停止并进入显式 repair，不静默覆盖。
3. Bootstrap 和日常 Job 不允许同时写同一范围。
4. 激活池 hash 在 plan 和 apply 之间不一致时停止。

---

## 9. Check 与 readiness 设计

### 9.1 ETF Basic

Raw blocking check：schema、非空、`ts_code` 唯一、系统字段缺失、日期/数值类型。  
Silver blocking check：继承全部 Raw 字段、代码唯一、日期关系合法、Raw/Silver 行级对账。  
WARN：状态、交易所、ETF 类型、管理人、基准指数的分布漂移。

### 9.2 激活池

Raw blocking check：resource 固定、非空、代码唯一、`.SH/.SZ`、日期关系。  
Silver blocking check：全部 Raw 字段继承、全部代码能关联 ETF Basic、快照日期正确、hash 可复算。  
WARN：代码数和上一快照相比的增删明细；不把 1,395 写成 blocking 常量。

### 9.3 ETF 分钟线

本节是首次 Prod 完整性审计的候选检查表，不是已经冻结的最终 Silver 准入合同。同步结束后先用真实分布验证，再由管理员确认哪些项目 blocking、哪些项目 WARN，以及是否需要增加或删除检查。

Raw blocking check：schema、目标日期/频率一致、主键唯一、无池外代码、文件可回读、源/写入行数相等。  
Silver blocking check：全部 Raw 字段继承、Raw 入库标准已通过、标准化后不丢行、主键唯一、日期/频率一致、Raw/Silver 11 字段行级对账。  
WARN 或待审计：满日 bar 数、代码覆盖、OHLC 关系、空数值、跨频聚合差异。审计确认误报边界后，才决定其中哪些升级为 blocking。

Readiness 不能只看“文件存在”或“行数大于 0”，必须与 blocking check 语义一致。

---

## 10. 性能预算与规模估算

| 对象 | 当前已知量级 | 建议执行模型 | 首版预算/停止条件 |
| --- | ---: | --- | --- |
| ETF Basic | 2026-05-04 历史样本 3,266 行 | 1 个只读连接、1 条显式列全量 SQL、1 个文件 | 空结果或行数异常漂移时停止，不覆盖 |
| 激活池 | 当前审计基线 1,395 个代码 | 1 个只读连接、`fetchmany` 有界读取、1 个 Raw 文件和 1 个 Silver 快照 | 空池、重复、非法后缀或超过上限时停止 |
| 分钟日常 | 已验收正常日约 447,795 行 | 1 次聚合 ready probe；最多 5 条单频明细 SQL；写 5 个 Raw 文件 | 单 tick 只提交 1 日；不逐 ETF 查询 |
| 分钟六个月 | Task 9597 样本外推约 4,850 万行 | 每批最多 20 个交易日；每频率 1 条范围流式 SQL；按日拆文件 | dry-run 必须重算；查询或空间超预算时不 apply |

以约 120 个交易日估算，六个月 Raw 大约 600 个文件，Silver 再约 600 个文件。最终数量以审计通过的 expected trade dates 为准。

性能门禁：

1. Bootstrap 不把全历史明细装进 Python。
2. 不按 1,395 个 ETF 扇出 Prod SQL。
3. 聚合 probe 必须按 `freq + trade_date` 批量完成。
4. writer 使用 DuckDB 投影、分区裁剪和 set-based SQL。
5. dry-run 输出 SQL 数、扫描行数、预计文件数、预计磁盘、耗时和临时空间峰值。
6. 正式预算必须在小样本 profiling 后写入 LLD；当前估算不能代替实测。

---

## 11. Catalog、资产、Job 和 Sensor 的预计改动面

本节只用于说明未来影响面，不是本轮开发清单。

| 范围 | 预计内容 |
| --- | --- |
| 路径 | 三类资产的正式路径和 staging 路径 helper |
| 字段合同 | ETF Basic、激活池、ETF 分钟 Raw/Silver column schema |
| Prod 只读 | 三张表的显式列 SQL、池 loader、分钟 source probe 和 range stream |
| Catalog | 三个 dataset id 下的 Raw/Silver entries、partition model 和治理映射 |
| Assets | Basic 2 个、池 2 个、分钟 Raw 5 个、分钟 Silver 5 个 |
| Checks | 每个正式资产一个合并 blocking core check，必要的漂移项用 WARN |
| Jobs | Basic、池快照、分钟 Raw、分钟 Silver 分开选择 |
| Sensors | 专属交易日注册、分钟 Raw、分钟 Silver；均默认 `STOPPED` |
| Bootstrap | plan/dry-run、apply、final audit、events 四个独立入口 |
| Tests | SQL 白名单、路径、schema、池 hash、writer、checks、bootstrap、events、性能和静态门禁 |
| 文档 | 本方案批准后补 LLD，并处理旧 ETF Basic Lake 方案的历史/废弃状态 |

正式 asset 进入代码前，必须先登记 `LAKE_ASSET_CATALOG`，再写 asset/check/job/sensor，不能让多处各自维护一套事实。

---

## 12. 明确不做的事情

1. 不修改或干预当前正在运行的 Prod ETF 分钟任务。
2. 不让 DG 直接请求 Tushare。
3. 不读取旧 Lake 作为 Bootstrap 输入。
4. 不引入 Kopia、临时兼容路径或第二套事实源。
5. 不把激活池当作 ETF 生命周期。
6. 不把当前 1,395 写成永久固定数量。
7. 不在 Raw 中修补、合成或填充分钟行情。
8. 不在完整性审计前决定 5m fallback、90m/120m、价格舍入或缺失填充。
9. 不把 Basic/激活池放进分钟更新 Job 顺手重跑。
10. 不在文件对账通过前补 Dagster 事件。

---

## 13. 风险与处理方式

| 风险 | 后果 | 处理方式 |
| --- | --- | --- |
| Prod 重跑尚未完成 | Bootstrap 得到半成品 | 等任务稳定结束后冻结审计；未通过不放行 |
| 用当前池解释全部历史 | 老 ETF/新 ETF 被误判缺失 | Basic 生命周期 + 当次冻结池 + 任务意图联合判断 |
| 池在计划与写入之间变化 | 文件范围不可复现 | 记录并复算 hash，不一致即停止 |
| 把正常零成交当脏数据 | Silver 静默丢失真实事实 | 先审计分类，Raw 永不补值或删行 |
| 复制指数/股票分钟规则 | 价格精度或频率语义被污染 | 只复用架构，不复用业务清洗规则 |
| Bootstrap 对 Prod 压力过大 | 影响生产服务 | 单连接、串行频率、20 日批次、只读事务、预算超限停止 |
| 只补文件不补事件 | Dagster UI 看起来缺历史 | 文件对账完成后单独做有界 Runless Event Backfill |
| 全历史补所有 check event | Event log 过大 | materialization 全量补，check 只补近期窗口 |

---

## 14. 需要管理员拍板的事项

以下事项没有批准前，不进入对应代码或正式执行。

| 编号 | 状态 | 需要拍板的问题 | 本方案建议 | 影响 |
| --- | --- | --- | --- | --- |
| D1 | **已确认（2026-08-27）** | 激活池是否只落 `resource='etf_mins'`，还是一次落全部 ETF resources | **只落 `etf_mins`** | 只服务当前分钟链，权限和消费者边界最清楚 |
| D2 | **已确认（2026-08-27）** | `silver_etf_basic` 是保留全部 ETF，还是只保留当前激活池 | **保留全部 ETF** | Basic 承担身份/生命周期；激活池单独表达当前选择 |
| D3 | 讨论中 | 激活池 Silver 只保留 current，还是保留不可变快照 | **建议 Raw 保存 current；Silver 按 `snapshot_date + snapshot_id` 留不可变版本** | 能复现历史任务范围；具体存法见 4.2 和 15.1 |
| D4 | **已确认（2026-08-27）** | 是否批准新增 `ops.etf_series_active(resource='etf_mins')` 窄只读白名单 | **批准** | LLD 和仓库白名单规则必须同步限定表、resource 和字段 |
| D5 | **已确认（2026-08-27）** | 日常 Raw ready 是否允许读取 ETF TaskRun 状态 | **ETF 专属窄例外，并与物理覆盖双门禁** | LLD 必须冻结允许字段、任务身份、查询上限和负向测试 |
| D6 | **方向已确认，细则待审计** | 分钟 Silver 第一版承担什么职责 | **Raw 完整性审计通过后的标准准入，不修补数据** | blocking/WARN、阈值和例外等 Prod 同步结束、首次审计后由管理员确认 |
| D7 | **已确认（2026-08-27）** | 是否在本轮生成 90m/120m 或做 5m fallback | **不做** | 新业务 K 线口径不混入 Raw/Silver 初次接入 |
| D8 | **原则已确认，范围待审计** | 历史 Bootstrap 起止范围 | **以重跑完成后的 Prod 审计结果为准，不在方案里硬编码** | 当前任务结束后由管理员安排首次只读审计 |
| D9 | **已确认（2026-08-27）** | Runless Event 补录范围 | **所有合格分区补 materialization，只给最近 20 个交易日补 blocking check** | 兼顾 UI 可追溯和 event log 体积 |
| D10 | **已确认（2026-08-27）** | 资产名、路径和专属分区名是否采用本文提案 | **采用；D3 快照子路径以 D3 最终结论为准** | 其余命名和路径可在 LLD 中按本文冻结 |

当前需要继续拍板的是 D3。D6 的职责方向不再讨论，但具体准入检查必须等待 Prod 同步结束后的首次审计；其余 D1/D2/D4/D5/D7/D8/D9/D10 已按表中口径确认。

---

## 15. 建议重点讨论的内容

### 15.1 激活池为什么要不要留历史快照

推荐存成“Raw current + Silver 不可变版本”：Raw 的 `full/part-000.parquet` 原子替换，Silver 用 `snapshot_date=<日期>/snapshot_id=<日期+内容hash>/part-000.parquet` 追加保存。快照内同时保存完整 `code_set_hash` 和 `snapshot_content_hash`；分钟文件只引用明确的 `snapshot_id`，不引用模糊的“最新池”。

同日相同内容重跑会复用同一个快照；同日池发生变化会产生另一个快照，旧文件不覆盖。这样既能处理重复运行，也能处理同一天临时调整激活池。

需要确认：我们要的是“现在有哪些 ETF”，还是“任何一次任务当时有哪些 ETF”。本方案推荐后者。

### 15.2 Prod 完成门禁看什么

只看 `ops.task_run=completed` 不够，因为任务状态和最终物理行可能不一致；只看物理表也不够，因为任务正在写时会暂时表现为部分覆盖。

本方案建议双门禁：

```text
ETF 专属 TaskRun 已完成
  AND 目标日五频物理聚合通过
  -> 才允许 DG Raw 日常任务开始
```

D5 已于 2026-08-27 确认采用该双门禁。下一步在 LLD 中必须把可读 TaskRun 字段、ETF 任务身份、查询时间窗、查询上限、物理覆盖 SQL 和负向测试逐项列清；本次只记录设计决定，不访问 Prod。

### 15.3 Silver 到底“清洗”什么

已确认 Silver 是“准入层”，不是“修复层”。Raw 分区先做完整性和入库标准审计；通过后才按相同 11 个业务字段进入 Silver，不通过就停在 Raw，并给出原因。

少一根 bar 是否补、零成交是否删、跨频不一致听谁的、`vwap` 是否重算，都不属于首版 Silver。当前 Prod 历史分钟结束后先做首次只读审计，再由管理员决定哪些检查是 blocking、哪些只是 WARN，以及阈值和例外；任何修复都不在 Silver 中偷偷完成。

### 15.4 历史范围从哪里开始

Tushare 接口已证明 ETF 分钟历史可早至 2009 年，但 Prod 表当前到底完整到哪里，要以重跑结束后的物理审计为准。DG Bootstrap 只能搬“已经证明完整或已解释缺口”的范围，不能因为接口理论上有十多年历史就自动从 2009 年开始。

---

## 16. 完成定义

本专项最终完成，至少要满足：

1. ETF Basic、激活池、分钟线三类资产均进入正式 Catalog，definition schema、路径、分区和 checks 一致。
2. 三张 Prod 表都只通过已批准的显式列、只读、有界合同访问。
3. Basic 和池的 Raw/Silver 文件通过双向对账。
4. 分钟 Prod 审计给出每个缺口的可解释分类和 Bootstrap go/no-go。
5. 历史 Raw/Silver 文件全部位于正式 Lake，staging 无残留，文件数、行数、schema、主键与 Prod 对账通过。
6. Silver 保留全部 Raw 字段，没有未经批准的数值改写、补值或丢行。
7. 事件补录只消费最终对账报告，补录后文件、materialization、check 的分区归属一致。
8. 日常 Sensors 默认停止上线，人工启用后连续观察至少 3 个自然交易日。
9. 全部专项测试、Catalog/static gates、文档完整性和 `git diff --check` 通过。
10. 交付记录明确是否访问 Prod、是否运行 Dagster、是否写正式 Lake、是否写 Dagster event。

---

## 17. 下一步建议

1. 管理员只需继续确认 D3 的不可变快照存法；其余已确认方向不重复讨论。
2. D3 确认后补一份 LLD，把已冻结的资产名、字段类型、SQL、Check、Job/Sensor、Bootstrap CLI、报告 schema 和测试逐项落到代码点；D6 的详细准入规则在首次审计前保留为待定。
3. ETF Basic 和激活池可以先开发，不必等待当前分钟重跑完成。
4. 当前分钟重跑结束后，由管理员安排首次只读 Prod 审计；审计报告通过后再批准分钟 Raw Bootstrap。
5. Raw Bootstrap 对账完成后，把审计结论交管理员评审并固化为 Silver blocking/WARN 准入规则；D9 事件补录范围已确认，但仍须在文件全绿后单独审批执行。
