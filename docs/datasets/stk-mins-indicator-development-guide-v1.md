# 股票分钟线技术指标开发指南与门禁清单 v1

- 状态：当前生效
- 更新时间：2026-05-13
- 适用范围：`lake_console` 本地 Parquet Lake 的 `stk_mins` 技术指标开发
- 当前已落地指标：`MACD(12,26,9)`
- 后续候选指标：`MA`、`BOLL`、其他基于分钟 K 线的本地派生指标
- 相关文档：
  - [股票分钟线指标系统设计方案 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-indicator-system-plan-v1.md)
  - [stk_mins MACD 大规模计算稳定性评审 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-indicator-compute-stability-review-v1.html)
  - [股票历史分钟行情 Parquet Lake 方案 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-parquet-lake-plan-v1.md)
  - [Local Lake Console 架构方案 v1](/Users/congming/github/goldenshare/docs/architecture/local-lake-console-architecture-plan-v1.md)

---

## 1. 这份指南解决什么问题

技术指标开发最容易出问题的地方，不是公式本身，而是：

1. 递推 state 是否准确延续。
2. 大范围全市场计算是否会把内存打爆。
3. 结果分区和 state 是否一起安全推进。
4. 源分钟线被重写后，指标是否能识别过期并提示重算。
5. 命令是否有真实进度输出，而不是长时间黑盒。
6. 测试是否覆盖“长任务失败”“新股首次出现”“老股票缺 state”等真实场景。

后续新增任何技术指标，都必须先按本文做设计和门禁检查，再写代码。

---

## 2. 当前指标系统事实

当前代码事实如下：

| 能力 | 当前事实 |
|---|---|
| 输入源 | `research/stk_mins_by_symbol_month`；该层由 `research/stk_mins_by_date_clean_next` 与 `derived/stk_mins_by_date` 重排生成 |
| 原始频度 | `1/5/15/30/60` |
| 本地派生频度 | `90/120` |
| 主输出层 | `derived/stk_mins_indicators_by_date/indicator=<indicator>/params_key=<params_key>/freq=<freq>/trade_date=<date>/` |
| research 输出层 | `research/stk_mins_indicators_by_symbol_month/indicator=<indicator>/params_key=<params_key>/freq=<freq>/trade_month=<month>/bucket=<bucket>/` |
| state 层 | `manifest/indicator_state/<indicator_scope>/params_key=<params_key>/state.parquet` |
| 重算队列 | `manifest/indicator_recalc_queue/` |
| 当前 CLI | `compute-stk-mins-indicator`、`compute-stk-mins-indicator-range`、`rebuild-stk-mins-indicator-research`、`rebuild-stk-mins-indicator-research-range`、`list-indicator-recalc-queue`、`mark-indicator-recalc-done` |

技术指标属于本地 Lake 派生资产：

1. 不写回 `raw_tushare`。
2. 不访问远程 `goldenshare-db`。
3. 不接生产 Ops TaskRun。
4. 不引入生产前端或生产后端依赖。
5. 不把生产调度、生产状态表、生产 freshness 链路带进 `lake_console`。
6. 不直接读取已删除的 `research/stk_mins_by_date_clean`，也不绕过 `clean_next -> derived -> by-month research` 这条基准链路。

---

## 3. 先判断指标类型

新增指标前，先判断它属于哪类。

| 类型 | 例子 | 是否需要 state | 计算风险 |
|---|---|---:|---|
| 窗口滚动型 | `MA`、`BOLL` | 通常需要窗口缓存或可由完整窗口重算 | 窗口边界、跨日连续性 |
| 递推状态型 | `MACD`、`EMA` | 是 | state 延续、缺 state、新股初始化 |
| 单点变换型 | 简单涨跌幅、振幅 | 否 | 输入字段校验、分区替换 |
| 组合信号型 | 金叉、突破、背离 | 可能需要 | 依赖多个指标或多列输入 |

如果指标需要递推或跨窗口计算，必须明确 state 模型；不能先把结果算出来，后面再补 state。地基一歪，楼越高越难救。

---

## 4. 设计前必须回答的问题

每个新增指标都必须在设计文档中回答下面这些问题。

### 4.1 输入契约

1. 读取 `research/stk_mins_by_symbol_month` 中哪些频度；`1/5/15/30/60` 来自 `clean_next` 重排，`90/120` 来自 `derived` 重排。
2. 支持哪些 freq：`1/5/15/30/60/90/120` 是否都支持。
3. 需要哪些输入字段，例如 `close`、`high`、`low`、`vol`。
4. 输入字段的类型和空值策略是什么。
5. 是否依赖前复权口径。
6. 如果源分区不存在，应该失败、跳过，还是输出 no-op。

### 4.2 输出契约

1. 输出字段名必须直接表达指标含义，不要为了“通用”起模糊名字。
2. 数值字段默认使用 `double`，除非有明确空间和精度评估。
3. 路径必须包含 `indicator`、`params_key`、`freq`、`trade_date`。
4. 必须写入 `indicator_version`，后续算法变更不能覆盖旧含义。
5. `params_key` 必须稳定，例如 `12_26_9`、`ma_5`、`boll_20_2`。

### 4.3 state 契约

如果指标需要 state，必须定义：

1. state 主键：通常是 `ts_code + freq + params_key`。
2. state 字段：例如 MACD 的 `ema_fast/ema_slow/dea/last_trade_time`。
3. state 更新时机：只能在结果分区成功写入后推进。
4. state 缺失策略：新股可初始化，老股票必须拒绝或明确 bootstrap。
5. state 回退保护：已有 state 晚于本次结果时，必须拒绝覆盖。

### 4.4 计算范围

1. 单股票 full。
2. 单股票 incremental。
3. 全市场 full。
4. 全市场 incremental。
5. range 编排是否支持一次跑多个 freq。
6. 是否需要同步重建 research。

每种范围都要明确是否支持。不能让 CLI 参数看起来支持，实际逻辑却只适合小数据。

---

## 5. 推荐模块分工

后续新增指标时，优先沿用当前模块边界。

| 模块 | 职责 |
|---|---|
| `models.py` | 指标参数、state、计算结果的数据结构 |
| `<indicator>_spec.py` | 默认参数、`params_key`、算法版本 |
| `<indicator>_calculator.py` | 纯公式计算，不读写文件、不访问配置 |
| `indicator_source_reader.py` | 读取源分钟线，按 by_date 或 research 流式输出 |
| `indicator_by_date_writer.py` | 写入指标 by_date 分区，负责 `_tmp -> 校验 -> replace` |
| `indicator_state_store.py` | 读取和替换 state，保证结果成功后才推进 |
| `indicator_research_service.py` | 从 by_date 重排到 research |
| `indicator_recalc_queue.py` | 记录源数据替换导致的指标待重算项 |
| `indicator_compute_service.py` | 编排计算、写入、state、进度输出 |
| `cli/commands/indicators.py` | CLI 参数与用户入口，不写核心逻辑 |

如果某个新增指标需要完全不同的 state 结构，可以新增独立 state store；不要把 MACD state store 硬塞成万能表。

---

## 6. 计算流程门禁

### 6.1 full 模式

全市场 full 必须满足：

1. 按 `freq -> trade_month -> bucket` 或等价小块流式处理。
2. 不能一次性读取多年全市场 rows。
3. 每个月作为提交窗口，先写 `_tmp`，校验后替换正式 by_date 分区。
4. 正式结果提交后才能推进 state。
5. 每个窗口必须有进度输出。
6. 源 research 缺失时必须失败并提示先重建 source research。

禁止：

1. 让用户手动按月执行 full 来绕过性能问题。
2. 每个月重新初始化递推 state。
3. 用“加大内存”替代流式计算。

### 6.2 incremental 模式

全市场 incremental 必须满足：

1. 按 `freq -> trade_date -> source part` 流式读取。
2. 每个交易日独立 stage、commit、推进 state。
3. 只能处理 `trade_time > last_trade_time` 的输入行。
4. 缺 state 时必须走生命周期判定。
5. 老股票缺 state 必须拒绝，不能中途初始化。
6. 新上市股票可以从首次出现的 bar 初始化。

### 6.3 range 编排

range 命令必须是高层编排，不应该复制计算逻辑。

它负责：

1. 按 freq 循环调用指标计算。
2. 在计算完成后重建对应 research。
3. 汇总每个 freq 的 source_rows、written_rows、state_updates。
4. 出错时明确停在哪个 freq。

它不负责：

1. 自己实现公式。
2. 自己写 state。
3. 自己扫描远程数据库。

---

## 7. 写入与事务式文件替换门禁

指标写入必须遵守：

1. 所有正式分区写入必须经过 `_tmp/{run_id}`。
2. 写完必须校验行数和必要字段。
3. 校验通过后才能 replace 正式目录。
4. state 必须在结果分区替换成功后写入。
5. state 写入失败不能让已经成功的正式结果变成“看起来成功但不可追踪”；必须抛错并让用户知道需要检查。
6. 不能追加小文件制造碎片；按分区替换。
7. research 层按月重建，不做无边界追加。

经验教训：

```text
UI 或日志里的 written，如果还没真正提交到正式分区，就不能表述成最终落盘成功。
```

---

## 8. state 与新股判定门禁

递推指标必须区分三种情况。

| 场景 | 允许行为 |
|---|---|
| full 计算从历史起点开始 | 可从第一根 bar 初始化 |
| incremental 中新上市股票首次出现 | 通过本地 `stock_basic.list_date` 校验后可初始化 |
| incremental 中北交所 `920xxx.BJ` 分钟线首次出现 | 通过本地 `stock_basic` 校验后，仅允许在该股票本地分钟线首次出现日初始化 |
| incremental 中老股票缺 state | 拒绝，输出 `needs_bootstrap` |

判断新股时：

1. 只能读本地 `manifest/security_universe/tushare_stock_basic.parquet`。
2. 不允许访问远程数据库。
3. `list_date` 缺失、不可解析、晚于源数据日期、股票池没有该股票，都必须拒绝。
4. `delist_date` 存在时，源数据日期晚于退市日期必须拒绝。
5. 北交所 `920xxx.BJ` 是分钟线代码切换专项口径：以本地 `stock_basic` 存在性和本地源分钟线首次出现日期为准，不能访问远程库。
6. 北交所 `920xxx.BJ` 缺 state 时，`2022-07-15` 只是本地分钟线新代码最早有效起点；具体股票必须以本地源分钟线首次出现日期初始化。
7. 如果 `920xxx.BJ` 晚于自身首次出现日才缺 state，必须拒绝并提示从该股票首次出现日补起。
8. `bse_mapping` 只作为旧代码映射辅助参考，不是完整 `920xxx.BJ` 清单；不允许因为某只 `920xxx.BJ` 不在 `bse_mapping` 中就否定本地源分钟线事实。

这样做能避免一种很隐蔽的错误：老股票从某一天中途初始化，结果看起来有 MACD，但前面十几年的递推状态全丢了。

---

## 9. 重算队列门禁

源分钟线分区被替换后，指标可能过期。

必须遵守：

1. 谁替换源分区，谁负责登记待重算事件。
2. 待重算记录要能说明：哪个 indicator、哪个 params、哪个 freq、哪个日期开始受影响。
3. `list-indicator-recalc-queue` 必须给出用户可执行的建议命令。
4. 当前不自动消费队列，不启动后台重 IO 任务。
5. 用户人工重算完成后，再通过 `mark-indicator-recalc-done` 关闭记录。

不要做：

1. 靠文件 mtime 猜源数据是否更新。
2. 自动悄悄重算全市场多年指标。
3. 只记录“有问题”，不给具体重算命令。

---

## 10. CLI 设计门禁

CLI 是用户入口，不是临时调试脚本。

新增指标 CLI 必须满足：

1. 入口优先复用 `compute-stk-mins-indicator --indicator <name>`。
2. 不为每个指标随手造一个长命令，除非有独立评审理由。
3. 参数必须能表达单股、全市场、full、incremental、freq、日期范围。
4. 长任务必须输出真实进度，至少包括当前 `freq`、日期/月、bucket/part、source_rows、written_rows。
5. 出错必须说明问题和下一步建议。
6. 不能输出一大堆刷屏日志，让用户看不到当前进度。

新增参数前必须问：

```text
这个参数是用户意图，还是实现细节？
```

实现细节不要暴露给用户。

---

## 11. 测试门禁

新增技术指标至少要有这些测试。

### 11.1 公式与准确性

1. 公式 fixture 测试。
2. 与手算或可信参考实现对齐。
3. 跨日递推不重置。
4. full 与 incremental 等价。
5. 不同 freq 的 state 不互相污染。

### 11.2 写入与 state

1. by_date writer 替换分区测试。
2. writer 拒绝错误 freq、错误 params_key、缺字段。
3. state 只能跟随成功结果推进。
4. state 回退保护。
5. state 文件全量替换后可读。

### 11.3 全市场与大数据

1. all-market full 必须证明按月/bucket 流式处理。
2. all-market incremental 必须证明按交易日流式处理。
3. source research 缺失时失败并给出提示。
4. 长区间 incremental 不得一次性读取所有 by_date 源分区。
5. 中途失败时，已提交窗口保留，未提交窗口不污染正式分区。

### 11.4 生命周期与重算

1. 新上市股票缺 state 可初始化。
2. 老股票缺 state 拒绝。
3. 股票池缺记录拒绝。
4. 源数据日期越过上市/退市边界拒绝。
5. 源分区替换后生成待重算记录。
6. 队列列表输出建议重算命令。
7. 人工重算后可标记 done。

### 11.5 CLI smoke

至少覆盖：

```bash
lake-console compute-stk-mins-indicator \
  --indicator <indicator> \
  --mode full \
  --ts-code 600000.SH \
  --freq 30 \
  --start-date 2026-04-24 \
  --end-date 2026-04-24

lake-console compute-stk-mins-indicator \
  --indicator <indicator> \
  --mode incremental \
  --all-market \
  --freq 30 \
  --start-date 2026-04-27 \
  --end-date 2026-04-27

lake-console compute-stk-mins-indicator-range \
  --indicator <indicator> \
  --mode full \
  --all-market \
  --freqs 30,60 \
  --start-date 2026-04-01 \
  --end-date 2026-04-30
```

如果指标尚未支持 all-market 或 range，文档必须写清楚“不支持”，不能让命令表面上支持。

---

## 12. DuckDB 验证门禁

每个指标完成后，必须能用 DuckDB 直接验证。

by_date 验证：

```sql
SELECT count(*)
FROM read_parquet('<LAKE_ROOT>/derived/stk_mins_indicators_by_date/indicator=<indicator>/params_key=<params_key>/freq=30/trade_date=2026-04-24/*.parquet');
```

单股时间序列验证：

```sql
SELECT ts_code, trade_time, *
FROM read_parquet('<LAKE_ROOT>/research/stk_mins_indicators_by_symbol_month/indicator=<indicator>/params_key=<params_key>/freq=30/trade_month=2026-04/bucket=*/*.parquet')
WHERE ts_code = '600000.SH'
ORDER BY trade_time;
```

必须确认：

1. by_date 分区能支撑单日全市场查询。
2. research 分区能支撑单股票长周期查询。
3. 输出字段和文档 schema 一致。
4. `indicator_version` 和 `params_key` 正确。

---

## 13. 新指标开发 checklist

开发前：

- [ ] 读本指南。
- [ ] 读 `stk-mins-indicator-system-plan-v1.md`。
- [ ] 明确指标类型：窗口滚动型、递推状态型、单点变换型、组合信号型。
- [ ] 明确输入层：raw、derived、或两者。
- [ ] 明确支持 freq。
- [ ] 明确输出 schema。
- [ ] 明确 `params_key` 和 `indicator_version`。
- [ ] 明确是否需要 state。
- [ ] 明确 full / incremental / all-market / range 支持边界。
- [ ] 明确 DuckDB 验证 SQL。

开发中：

- [ ] 公式计算与文件读写分离。
- [ ] 计算函数不读配置、不访问文件、不写日志。
- [ ] 写入必须走 `_tmp -> 校验 -> replace`。
- [ ] state 只在结果成功后推进。
- [ ] all-market 不得一次性读全量。
- [ ] incremental 不得从中途静默初始化老股票。
- [ ] CLI 输出真实进度。
- [ ] 错误信息包含下一步建议。

提交前：

- [ ] 公式 fixture 测试通过。
- [ ] state 测试通过。
- [ ] writer 测试通过。
- [ ] all-market full / incremental 流式测试通过。
- [ ] 新股/老股缺 state 测试通过。
- [ ] recalc queue 测试通过。
- [ ] CLI smoke 通过。
- [ ] DuckDB 查询能读到 by_date 和 research。
- [ ] 文档与代码状态一致。

---

## 14. 禁止事项

1. 禁止为了快而跳过 state 设计。
2. 禁止把递推指标拆成多个手工 full 段来跑。
3. 禁止把多年全市场数据一次性读入内存。
4. 禁止在 state 未推进或结果未提交时宣称任务完成。
5. 禁止把老股票缺 state 当作新股初始化。
6. 禁止自动访问远程数据库补事实。
7. 禁止让 `lake_console` 反向依赖生产 Ops、生产 Web 或生产调度。
8. 禁止只做 by_date，不考虑 research 查询需求。
9. 禁止源数据重写后不登记指标重算风险。
10. 禁止写一个“能跑”的指标，却没有准确性、性能、失败恢复和验证门禁。

---

## 15. 后续新增 MA / BOLL 时的建议顺序

建议按这个顺序推进：

1. 先写指标专项设计文档，说明输入、输出、state、full/incremental 语义。
2. 先做单股票公式和 by_date 写入。
3. 再做 state 或窗口缓存。
4. 再做 all-market full 流式。
5. 再做 all-market incremental 流式。
6. 再做 research 重排。
7. 最后接 recalc queue 与 CLI range。

不要一上来就全市场多年直跑。技术指标不是“公式跑一下”这么简单，真正的质量在边界里。
