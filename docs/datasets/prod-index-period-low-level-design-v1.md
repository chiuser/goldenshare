# Prod 指数周线和月线低层设计 v1

正式取数、Serving 日更、历史补数和切换清理规则已确认。分页与发布首期的实测记录见 §2，实施前核验见 §8。业务范围和规则见[原方案](/Users/congming/github/goldenshare/docs/datasets/index-series-active-sync-mechanism.md)。本文按[数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)细化两个已有数据集。

## 1. 任务与数据范围

| 任务 | 输入和触发 | 读写边界 |
| --- | --- | --- |
| 指数周线、月线正式维护 | 保留 `index_weekly.maintain` 和 `index_monthly.maintain`。周线在当周最后交易日收盘后取数，月线在次月首个交易日的上海时间 19:00 后取数。两者均请求所取周期的最后交易日，见 §3。源延迟或失败时人工按原范围重新请求。 | 请求 Tushare，写对应 Raw。常规期末取数以源返回范围为准。 |
| 指数周线、月线 Serving 更新 | 每个任务指定频率和一个目标交易日。运营手动更新时可指定池内代码，日更由管理员配置，在每个交易日盘后分别触发。正式月线自动取数成功提交 Raw 后，另触发一次月线 Serving 更新，目标日为上月期末。 | 只处理周、月线激活池内代码。优先读当期周、月线 Raw，需要合成时才读指数 Raw 日线，只写对应 Serving。 |
| Serving 切换清理 | 以原方案 §4 的 10 个代码作为保留名单，两种频率使用同一名单。 | 保留这 10 个代码的现有 Serving 记录，只删除两张 Serving 表中的名单外记录。 |

| 数据集 | Tushare 接口 | Prod Raw | Prod Serving |
| --- | --- | --- | --- |
| 指数周线 `index_weekly` | [Tushare doc 171](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0171_指数周线行情.md) | `raw_tushare.index_weekly_bar` | `core_serving.index_weekly_serving` |
| 指数月线 `index_monthly` | [Tushare doc 172](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0172_指数月线行情.md) | `raw_tushare.index_monthly_bar` | `core_serving.index_monthly_serving` |

合成输入为 `raw_tushare.index_daily`、交易日历、指数发布日期及按需读取的当前 Serving 记录。指数日线的池、任务和服务表沿用现行机制。Prod 数据后台的周、月线卡片属于本次改造，见 §5.1。DG、股票周月线和财势乾坤图表及指标接入属于其他阶段。§2.2 仅约定财势乾坤后续读取所需的单位转换。

## 2. 源接口、字段和日期合同

### 2.1 源接口与分页实测

2026-11-10 用项目的 `DatasetSourceClient.iter_pages` 和 Tushare 连接器只读测试。期末请求使用 Definition 的 11 个字段和每页 1,000 条，直到短页或空尾页结束。以下是样本观测，耗时包含源请求和核验脚本处理，未计入库。

| 请求 | 分页结果 | 耗时及核对 |
| --- | --- | --- |
| 指数周线 `trade_date=20261106`，不指定代码 | 14,211 条，15 页，末页 211 条。 | 3.263 秒。14,211 个不同业务键，日期均为 11 月 6 日。 |
| 指数月线 `trade_date=20261030`，不指定代码 | 4,647 条，5 页，末页 647 条。 | 1.192 秒。4,647 个不同业务键，日期均为 10 月 30 日。 |
| 上证指数周线 `20261001–20261106` | 5 条。每页 2 条得到 2、2、1。每页 5 条得到 5、0。 | 每页 2 条时首次 0.511 秒，原范围重跑 0.509 秒。分页结果和无分页参数的同窗请求逐键、逐字段一致。 |
| 上证指数月线 `20260801–20261030` | 3 条。每页 2 条得到 2、1。每页 3 条得到 3、0。 | 每页 2 条时首次 2.510 秒，原范围重跑 1.034 秒。分页结果和无分页参数的同窗请求逐键、逐字段一致。 |
| 上证指数 `20250101–20251231` | 周线 53 条，月线 12 条，两次均为一页。 | 周线 0.084 秒，月线 0.270 秒。周线最早为 1 月 3 日，月线最早为 1 月 27 日，两者最后一条均为 12 月 31 日。 |

两次全范围样本均返回定义中的 11 列。前序源端探测在 2026-08-07 周线取得 15,404 条、2026-07-31 月线取得 15,277 条，按每页 1,000 条计算均为 16 页。Tushare MCP 对上证指数做了默认字段、显式 11 列和只请求 `ts_code,trade_date` 的点查。对应点查与项目连接器的样本行一致。2026-09-30 所在周的周五休市，周线点查实际期末 9 月 30 日取得该日记录。前序 2026-11-09 的期中点查无正式记录。MCP 没有暴露 `limit/offset`，分页证据来自项目连接器。无日期和只传代码的无界读取不属于本次方案的执行方式。

可取消的项目连接器读取周线第二页成功，返回 1,000 条，耗时 1.355 秒。真实连接发起后触发取消，取消信号到返回为 0.156 秒。用本机延迟响应验证已收到 HTTP 请求时的取消，收到请求后 0.107 秒返回，子进程均已退出。另用一次人工注入的瞬时超时核对重试，原参数请求两次，第 2 次接实际源，退避 0.505 秒，总耗时 1.150 秒。这些是受控验证结果，不代表生产最大耗时。 [项目分页](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py) · [Tushare 客户端](/Users/congming/github/goldenshare/src/foundation/clients/tushare_client.py)

同一可取消连接器复查两个完整期末，页数、行数和业务键数量与上表一致。周线取数 12.469 秒、归一化 0.975 秒，月线分别为 4.108 秒和 0.266 秒。归一化分别得到 14,211、4,647 条，两者均无拒绝、无去重。核验脚本保留单期所有行再归一化，主进程 Python 分配峰值分别为 33,791,602 字节和 10,815,115 字节，未含子进程和入库开销。

`DatasetDefinition` 继续维护源字段。单日维护和区间补历史共用现行 [request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)，每个期末发送 `trade_date` 和可选的 `ts_code`。区间由 Resolver／Planner 按完整交易日历展开期末，分页参数由 source client 生成。按源接口日期区间的查询仅作为本节实测证据。源返回日期不等于真实期末的实例见 §2.2，处理规则见 §4.1。

### 2.2 字段映射、合成和单位

| Tushare 字段 | Raw 字段 | Serving 正式值 | Serving 合成值 |
| --- | --- | --- | --- |
| `ts_code` | `ts_code` | 对应的池内代码 | 同一池内代码 |
| `trade_date` | `trade_date` | 源返回的期末交易日 | 本次计算实际截至的交易日 |
| `open` | `open` | 按源值 | 首日日线开盘 |
| `high` | `high` | 按源值 | 窗口最高价 |
| `low` | `low` | 按源值 | 窗口最低价 |
| `close` | `close` | 按源值 | 末日日线收盘 |
| `pre_close` | `pre_close` | 按源值 | 取窗口首日的日线前收盘，代表性验收包括发布日期在周期中的首期 |
| `change` | `change` | 按源值写 `change_amount` | `close - pre_close`，沿用现有字段精度 |
| `pct_chg` | `pct_chg` | 按源值，涨 1% 为 `0.0100` | `round(close / pre_close - 1, 4)`，单位为比例 |
| `vol` | `vol` | 按源值，单位为股 | Raw 日线成交量求和后乘 `100`，从手换算为股 |
| `amount` | `amount` | 按源值，单位为元 | Raw 日线成交额求和后乘 `1,000`，从千元换算为元 |

正式 Raw 的行情业务值沿用源返回值。源日期字符串按现有映射转为 `DATE`，`api_name`、`fetched_at`、`raw_payload` 是 Raw 本地辅助字段。Serving 用本地 `period_start_date` 定位周期，`source=api` 代表正式值，`source=derived_daily` 代表合成值。两类值共享同一字段类型与精度，数值字段保留表定义的 4 位小数。正式行情中的零值按源保留。合成取计算窗口首个应有交易日的日线前收盘，首期窗口从发布日期当日或其后的首个应有交易日起算。§4.3.4 的中证 A500 人工月线在 Raw 用 `api_name=derived_daily` 区分来源。 [Raw 日线字段](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_index_daily.py) · [现有合成公式](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)

**单位实测。** 2026-11-10 对照 Prod Raw 的 10 个代码、截至 2026-11-06 的一周和截至 2026-10-30 的一月，分别有 5、17 个应有交易日，池内日线均齐。查到的 18 条正式周、月线，其成交量与日线合计之比均为 `100.0000`，成交额之比均为 `1000.0000`，正式涨跌幅与 `round(close / pre_close - 1, 4)` 一致。源文档将正式周、月线量额标为手、千元，实测返回值对应股、元，写 Raw 时保留源值。两个期末均未查到北证 50 正式 Raw，按 §4 的同一规则处理。 [Tushare 日线字段说明](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0095_指数日线行情.md)

**财势乾坤读取。** 周、月线后续接入时，在财势乾坤读取入口一次性将成交量除以 `100`、成交额除以 `1,000`，与日线行情接口的手、千元对齐。界面需要百分数时，把比例乘 `100` 后加百分号。通用行情 API 继续直读 Serving 的股、元及涨跌幅比例。 [现有通用行情读取](/Users/congming/github/goldenshare/src/biz/queries/quote_query_service.py) · [财势乾坤日线行情字段映射](/Users/congming/github/goldenshare/src/biz/services/wealth/market/index_detail/index_detail_field_mapper.py)

#### 发布首期实测

2026-11-10 用 Tushare 的指数基础信息、日线、周线、月线接口抽查六个指数。日线范围从发布日期到当月最后交易日。Prod 只读核对同一窗口的日线 Raw、周月期末 Raw、交易日历及指数基本信息。六个 Prod 发布日期均与源一致。69 个应有交易日对应的 Tushare 日线都返回，OHLC、前收盘和量额齐全，前收盘均非零。Prod 样本中的日线缺行与源字段缺值分别记录。

| 指数 | 发布日 | 源日线条数 | Prod Raw 日线条数 | 源周、月期末记录 |
| --- | --- | ---: | ---: | --- |
| 上证 50 `000016.SH` | 2004-01-02 | 13 | 0 | 首周、首月均有，`pre_close`、`pct_chg` 均为 0。 |
| 沪深 300 `000300.SH` | 2005-04-08 | 16 | 0 | 首周、首月均有，包含发布前回溯行情。 |
| 创业板指 `399006.SZ` | 2010-06-01 | 19 | 0 | 首周、首月均有，`pre_close`、`pct_chg` 均为 0。 |
| 科创 50 `000688.SH` | 2020-07-23 | 7 | 7 | 首周、首月均有，包含发布前回溯行情。 |
| 北证 50 `899050.BJ` | 2022-11-21 | 8 | 0 | 11 月 25 日周线、11 月 30 日月线均无返回。 |
| 中证 A500 `000510.SH` | 2024-09-23 | 6 | 6 | 首周有，9 月 30 日月线无返回。按区间只查到 9 月 27 日月线。 |

- 上证 50、创业板指发布首日日线的前收盘均为 1,000 点。两者首期正式周、月线的前收盘与涨跌幅均为 0，属于首期正常源值。Raw 和正式 Serving 原样保存；合成使用计算窗口首日日线的前收盘。
- 沪深 300 首周正式开盘为 968.49 点，对应发布前 4 月 4 日的日线开盘 968.4902 点。发布日期 4 月 8 日的日线开盘为 984.6650 点。科创 50 首周正式开盘为 1459.7843 点，等于发布前 7 月 20 日日线开盘，发布日期 7 月 23 日为 1487.1965 点。两只指数首月正式开盘也对应各自发布前的当月首个交易日。按当前规则，发布日期控制从哪个周期纳入 Serving 以及合成起点。有合格正式 Raw 时仍保留源值，因此首根正式 K 线可能带有发布前的回溯行情。
- 中证 A500 的 2024-09-30 是开市日，Prod 当日日线收盘为 4684.8913 点。源区间 `20240923–20240930` 仅返回 `trade_date=20240927`、收盘 4298.5618 点，点查 9 月 30 日为空。9 月 27 日源月线与 9 月 2 日至 27 日的源日线汇总一致，成交额四舍五入到元后也一致，整根缺少 9 月 30 日行情。9 月 27 日的异常源行按 §4.1 拒绝写入，正式期末缺数。Prod 按发布日期起的 6 条日线合成至 9 月 30 日，单条人工修复见 §4.3.4。
- 北证 50 的 2022 年 11 月首期在源端有 8 条发布后日线，首次抽查时 Prod 同范围缺这 8 条日线，且没有正式周、月 Raw。后续已补齐这 8 条 Prod Raw 日线并生成首月 Serving，见 §4.3.3。

### 2.3 日期、业务键和时效

- **周期标识。** 按完整交易日历取所属自然周或自然月的首个开市日作为 `period_start_date`。自然周从周一开始，自然月从 1 日开始。周一休市、周二开市时，该周每天使用周二作为周期标识。指数发布日期决定该代码在当期从哪个交易日开始计算，不改变周期标识。
- **数据截至日。** 合成行的 `trade_date` 为计算截至的交易日，正式行保留源返回的期末交易日。入库时间用现有时间戳。日历提供上一交易日和真实期末，日历未齐时不能推定休市。周五休市则取该周实际最后一个开市日。
- **记录身份。** Raw 按 `(ts_code, trade_date)` 写入。对应 Serving 表按 `(ts_code, period_start_date)` 的现有唯一约束更新同一根 K 线，保留现有主键。无需增加 `end_date`。请求中的 `start_date/end_date` 仅表示取数范围。 [周线模型](/Users/congming/github/goldenshare/src/foundation/models/core_serving/index_weekly_serving.py) · [月线模型](/Users/congming/github/goldenshare/src/foundation/models/core_serving/index_monthly_serving.py)
- **输入和执行。** 正式维护沿用点、区间输入，计划只展开范围内真实的期末交易日。Serving 单次使用一个目标交易日，执行日所属的自然周、月分别是当前周期，接受该周期内已收盘的目标交易日。更新已结束周期时，目标日为该周期最后一个交易日，适用于人工补数和正式月线入库后触发的上月更新。
- **完整性和时效。** 历史覆盖按已结束周期的实际最后交易日及正式来源判断。Raw 卡片按 §3 的正式取数排程判断哪一期应到。正式月线只统计 `api_name=index_monthly` 的期末行，人工合成行不计为正式到数。Serving 时效看各代码实际 `trade_date`。缺数和失败沿现有任务详情查看。 [日期模型指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md#period-anchors)

2026-11-10 只读抽查 Prod 的 `core_serving.trade_calendar`（SSE）和 `raw_tushare.index_weekly_bar`。范围为方案的 10 个代码、下表 7 个自然周，仅核对代码和日期。每个样本周的日历都有 7 个自然日记录。

| 样本周的周五 | 周五状态 | 当周最后开市日 | Prod Raw 的 `trade_date` | 行数 |
| --- | --- | --- | --- | ---: |
| 2025-04-04 | 休市 | 2025-04-03 | 2025-04-03 | 9 |
| 2025-10-03 | 休市 | 2025-09-30 | 2025-09-30 | 9 |
| 2026-01-02 | 休市 | 2025-12-31 | 2025-12-31 | 9 |
| 2026-05-01 | 休市 | 2026-04-30 | 2026-04-30 | 9 |
| 2026-06-19 | 休市 | 2026-06-18 | 2026-06-18 | 9 |
| 2026-10-02 | 休市 | 2026-09-30 | 2026-09-30 | 9 |
| 2026-11-06 | 开市 | 2026-11-06 | 2026-11-06 | 9 |

抽到的 63 条周线均记在当周最后开市日。上述样本的北证 50 未见正式记录，这一结果只说明样本期的供数情况。

## 3. 激活池、发布日期与调度

周、月共用独立激活池，首期使用[原方案 §4](/Users/congming/github/goldenshare/docs/datasets/index-series-active-sync-mechanism.md)的 10 个代码。切换时初始化，日常入口不开放增删。**二期必须提供该池的独立增删能力**，变更名单时同步处理相应指数的历史覆盖或 Serving 清理。运行时读取运营池，财势乾坤的主要指数配置仅用于首期名单依据。

| 配置或事实 | 存放与读取 | 作用和生效 |
| --- | --- | --- |
| 周、月线激活池 | 复用 `ops.index_series_active` 及 [对象池 DAO](/Users/congming/github/goldenshare/src/foundation/dao/index_series_active_dao.py)，周、月共享一个独立的资源值。 | 切换时用原方案 §4 的 10 个代码初始化持久化池，以同一名单限定 Serving 清理范围。日更和卡片从该池读取。常规期末取数不使用该池裁剪源数据，日线两池保持现状。 |
| 指数发布日期 | 使用已核实的指数基础信息 `list_date`，与池内 `first_seen_date` 分开。 | 控制每个代码的历史起点和首期应有日线范围。 |
| 交易日历 | 使用现有 `DEFAULT_EXCHANGE` Settings，源码默认 SSE，业务时间按上海时区。 | 确认实际日历配置和适用交易日，统一确定期初、期末、上一交易日与所需日线日期。 |
| 正式 Raw 自动任务 | 沿用数据后台自动任务配置和 `ops.schedule` 中的排程策略、执行时间及时区字段。 | 周线按当周实际最后交易日、月线按次月首个交易日触发。取数日期由下述排程规则生成。 |
| Serving 盘后日更 | 由管理员在数据后台配置，首期以日线 Raw 在上海时间 22:00 前就绪为排程假设。 | 每个交易日盘后分别执行周、月线 Serving 更新，目标日为触发当日的交易日。 |

[现行审查中心页面](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-review-index-page.tsx) 使用日线资源，[后端通用增删命令](/Users/congming/github/goldenshare/src/ops/services/review_center_service.py) 接受资源参数。首期后端禁止这些命令增删周、月线池。实现时在同一处声明新资源值，切换、Serving 和卡片共用。

### 3.1 正式取数排程

- **周线。** 用完整交易日历确定自然周的最后一个开市日，在该日收盘后按配置触发一次，请求日期就是该日。周五休市时，按该周实际最后开市日触发及取数。
- **月线。** Tushare MCP 的 `index_monthly` 接口说明标注每月首个工作日 19:00 更新上月数据。Prod 按交易日历在次月首个交易日的上海时间 19:00 后按配置触发一次。创建 TaskRun 时，以计划触发时刻的上海日期确定上一个自然月，查该月最后一个交易日并写入 `time_input.trade_date`。Resolver 将该日期交给执行计划，request builder 发送同一日期。以 2026 年 10 月月线为例，11 月首个交易日 19:00 后触发，请求 `trade_date=20261030`。月线的历史周期边界仍为 `month_last_open_day`。

排程预览与实际触发使用相同的日历规则。自动任务的取数日期由排程生成。源延迟或任务失败时按已记录的原取数日期补拉，手动点查和区间维护沿用 §4.1。

正式月线自动取数成功提交 Raw 后，按 §4.2 单独触发上月期末的 Serving 更新。当天的盘后日更仍以当天交易日为目标。

## 4. 执行流程与失败处理

### 4.1 正式周、月线 Raw 维护

1. 常规维护与历史区间补数共用同一入口和期末校验。单日取所选期末，区间按完整交易日历展开范围内的各真实期末。这里的一期指一个已结束的交易周或交易月，用该期最后一个交易日查询。有代码就按指定代码取，未指定代码时取该期 Tushare 返回的所有指数行情。
2. **先取完一期，再写 Raw。** 同一期的各页全部暂存在内存，直到返回不足 1,000 行的一页，空页也表示取完。单期的页数和行数随 Tushare 实际返回。取完后统一检查字段、业务键和请求范围，校验通过才开始写 Raw。同一期可分多批执行数据库写入，全部写完后提交一次，再处理下一期。例如 2026-11-06 的周线样本分 15 页返回 14,211 行，末页 211 行，这 15 页作为同一批校验并提交。
3. 任一页最终取数失败或取数期间取消时，丢弃当前期末暂存的数据。写入前要求所有返回的 `trade_date` 等于目标期末，发现日期不符时，该期不写入，任务失败，详情列出频率、代码、预期和实际日期。写入中失败则回滚本期事务。以上情况均保留先前已提交的期末。
4. 按代码补历史时，某期空返回就记为源缺期，记录频率、代码和期末，继续取后面的期末。已到的正式数据照常逐期提交，任务结束后在详情集中列出缺期。采用现有任务终态，有期末成功且有缺期时标记部分成功，全部缺期时标记失败。单次正式取数空返回时在任务详情报告期末和可确定的缺失代码。空返回、部分返回或请求失败均保留既有有效 Raw。全范围请求以源实际返回为准，缺失代码仅在有明确请求范围时判断。
5. 源延迟、失败或中断后，数据后台重试使用原频率、原期末或整个原日期区间及原代码重新请求 Tushare。已提交的 Raw 保留，重拉后按原业务键更新。正式月线自动取数成功后的上月 Serving 更新按 §4.2 执行。其他人工补到正式 Raw 后，运营可指定对应期末运行 Serving 更新。Serving 写入失败时单独重跑 Serving 任务。

### 4.2 独立 Serving 更新

运营可在同一当前周期内逐日指定已收盘的目标交易日，也可在跨期后选择过去周期的最后一个交易日。多个日子未成功时，从第一个未更新的交易日起按交易日顺序补。管理员配置的盘后日更在目标交易日执行。过目标交易日的上海时间午夜，尚未完成的旧日更任务转人工。

周线、月线在现有 Ops 维护动作目录分别注册，两个动作固定各自频率，共用计算和写入服务。手动任务沿用单日 `trade_date` 控件，可选池内代码，未选则处理全池。盘后日更从预定触发时刻取上海日期，作为明确的 `trade_date` 写入 TaskRun，处理全池。Worker 使用任务携带的日期执行，休市日不发起盘后日更。日更执行时核对目标日期、收盘和午夜截止。重试沿用原目标日和代码，日更过午夜按人工补数处理。 [维护动作目录](/Users/congming/github/goldenshare/src/ops/action_catalog.py) · [手动表单定义](/Users/congming/github/goldenshare/src/ops/queries/manual_action_query_service.py) · [排程转任务](/Users/congming/github/goldenshare/src/ops/services/task_run_service.py)

正式月线自动取数成功提交有效 Raw 后，Ops 用这次取数任务的 `trade_date` 创建一条独立的月线 Serving TaskRun，处理周、月线激活池内代码。原自动取数重试成功也走这一步。该任务按已结束周期执行。以 2026 年 10 月为例，11 月首个交易日晚触发的上月 Serving 任务目标是 `2026-10-30`，同晚的日更目标是 11 月当天。两条任务分别执行，沿用各自目标日和周期键。正式取数失败或没有提交正式 Raw 时，保留原 Serving。上月 Serving 任务失败时单独重试，不影响已提交的 Raw。

每个任务按其频率独立处理，同一任务的每个池内指数按下表执行。

| 顺序和条件 | 读写动作 |
| --- | --- |
| 1. 当期有正式周、月线 Raw | 读 `(ts_code, 当期最后交易日)` 对应的源记录。月线还须满足 `api_name=index_monthly`。直接按源值更新同一周期的 Serving，缺行可补建，来源为 `api`。无需检查日线及上一交易日。§4.3.4 的人工合成行按下方日线合成规则处理。 |
| 2a. 无正式 Raw，目标日处于当前周期 | 从该指数本周期首个应有交易日算到目标日。首日可创建。同周期已有同一目标日的合成值时，按相同窗口重算并更新同一条记录。除此之外，首日之后须先检查 Serving 的 `trade_date` 等于上一交易日，再检查窗口的应有日线是否齐全。合成来源为 `derived_daily`。 |
| 2b. 无正式 Raw，任务目标为过去周期的最后一个交易日 | 检查从该指数本周期首个应有交易日起的完整日线。齐全则一次计算整期并写入，`trade_date` 为该期最后交易日。无须依赖 Serving 的上一交易日记录。 |
| 3. 所需日线缺失或连续性检查失败 | 保留该指数旧 K 线和截至日，原先无记录则保持缺行。任务详情列频率、代码、目标日或期末、失败阶段和缺失的日线日期，或者预期和实际截至日。通过检查的其他指数继续提交，本频率任务最终标记失败。另一频率独立执行。 |

例如 11 月 9 日合成成功，10 日日线缺失，Serving 截至日仍为 9 日。11 日即使有日线，检查预期为 10 日、实际为 9 日，该指数更新失败。运营补到 10 日日线后，先指定 10 日更新，再执行 11 日。如果要补已经结束的这一周，人工选其最后交易日，按上表先取正式 Raw，缺正式 Raw 时检查完整周日线。

10 个代码都走相同顺序。北证 50 缺正式 Raw 时用日线合成，未来查到当期正式 Raw 时照常覆盖。按周期唯一键写入。每个代码独立提交，在同一业务事务中检查该周期的 Serving 行并更新，冲突时以实际已写入行判断。已有正式行或更晚的合成截至日时，保留原行。正式 Raw 仍可按第一步更新同周期。任务状态和错误记录在业务事务之外更新。

### 4.3 保留已补齐的历史、清理名单外记录与逐日接续

1. §4.3.1 至 §4.3.4 是切换前的历史补数和验收记录。切换后的取数、重试和 Serving 更新按 §4.1、§4.2 执行。10 个指数从各自发布日期起的 Serving 已齐备，周线截至 `2026-11-06`，月线截至 `2026-10-30`。这 10 个代码的现有 Serving 行全部原样保留，包括北证 50 和中证 A500 已确认的合成值。今后某一期取得正式期末 Raw 时，通过 §4.2 的单期更新覆盖相应合成值。
2. 获准切换后，隔离两张 Serving 表的旧写入及待办重试。清理验收前暂停新 Serving 写入，包括盘后日更和正式月线入库后触发的上月更新。按原方案 §4 初始化独立激活池，核对池中代码与保留名单逐项相同。仅在 `core_serving.index_weekly_serving` 和 `core_serving.index_monthly_serving` 中按 `ts_code` 删除名单外记录，删除范围以该名单为准。池内记录、Raw、指数日线和日线激活池均不在本次数据清理范围。
3. 删除前按表和池外代码统计记录数，按获准范围备份待删行，并按 `(ts_code, period_start_date)` 核对备份可恢复。隔离期间按表和池外代码分批删除并提交，每批只处理已备份的记录，并记录删除结果。中断后根据原备份范围及数据库实际剩余记录继续处理。若需回退，按原业务键恢复本次已删除的池外记录，撤销本次激活池变更。验收核对两表池外记录数为零、10 个代码的历史起止日和记录数保持一致，并抽查保留的正式及合成记录的日期、来源和行情值。
4. 验收后周、月分别从现有数据接续。按本次历史截止日，周线从 11 月 9 日起，月线从 11 月首个开市日起，分别按交易日顺序执行。已有当期记录时，按该代码在对应频率的 `trade_date` 和 §4.2 的连续性规则接续。

#### 4.3.1 上线前使用现有入口补 2020 年前历史

2026-11-10 管理员批准通过现有 Prod 数据后台提交这一批历史任务，允许旧动作同时写 Raw 和 Serving。使用「指数周线」和「指数月线」手动维护，均选择日期区间，每个任务明确填写表中的单个证券代码。周线结束日统一为 2019-12-27，月线为 2019-12-31。跨年的下一周实际期末是 2020-01-03，已有该期数据，因此周线范围止于前一个完整周。

| 代码 | 起始日 | 周线取数单元 | 月线取数单元 |
| --- | --- | ---: | ---: |
| `000001.SH` | 1991-07-15 | 1,441 | 342 |
| `399001.SZ` | 1995-01-23 | 1,258 | 300 |
| `000016.SH` | 2004-01-02 | 813 | 192 |
| `000300.SH` | 2005-04-08 | 750 | 177 |
| `000905.SH` | 2007-01-15 | 662 | 156 |
| `399006.SZ` | 2010-06-01 | 491 | 115 |
| `000852.SH` | 2014-10-17 | 267 | 63 |

数据后台当前版本为 `5084ef93`。按现行 planner 以 Prod 交易日历计算，上表合计 5,682 个周线单元和 1,345 个月线单元，共 7,027 次按代码、期末日期的正常请求，另计失败重试。旧写入器按单元提交。指定代码时保留其他代码的 Raw。池内正式行同时写入旧 Serving，月线源为空时仍可能合成 Serving，Raw 只由源行补入。这批操作只提交历史任务，Serving 清理在另行批准的切换时执行。 [请求构建器](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py) · [现行写入器](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)

逐个提交前核对频率、代码和起止日，提交后确认任务编号和范围。请求结果不明时先查任务记录，再决定是否补提交。失败或中断时保留已提交的单元；重跑前按原代码、日期和已提交情况核对范围，估算开销按尚需重读的期末计。运行结束后只读核对各任务结果和对应 Raw 的首末日期、源缺项，Serving 合成行不计为 Raw 补数完成。

2026-11-10 17:09（上海时间）验收，14 项任务 `19026` 至 `19031`、`19034` 至 `19041` 全部成功。按交易日历核对 Raw，5,682 个周线期末和 1,345 个月线期末均已入库。

#### 4.3.2 上线前补 2020 年以来已核实的缺期

2026-11-10 获准使用 Prod 数据后台处理本次审计缺口。以下仅适用于现行版本 `5084ef93`，逐项填入单个证券代码，沿用 §4.3.1 的提交、重试和读回规则。

| 对象和范围 | 入口及实际写入 |
| --- | --- |
| 除北证 50 外的 9 个指数，周线期末 `2026-07-03`、`2026-07-24`、`2026-07-31`、`2026-08-07` | Tushare 逐代码区间核实四期正式值均存在。每代码提交 `2026-07-03` 单日和 `2026-07-24` 至 `2026-08-07` 区间各一项。区间只展开后三个缺期。现行指数周线入口写正式 Raw，并覆盖相同期末的旧 Serving 合成值。 |
| 北证 50，周线期末 `2022-11-25`、`2022-12-02`、`2022-12-09`、`2022-12-16` | 四项单日指数周线维护。Tushare 该代码这四期无返回。现行写入器单日空返回时只按指定代码从指数日线 Serving 合成。已核对发布日起至 12 月 16 日的 20 个交易日和合成字段齐全。只补周线 Serving。 |
| 中证 A500 另缺的 7 个 2024 年正式周线期末及 2024 年 9 月正式月线期末 | Tushare 按代码查区间未返回这些期末。部分记录提前一天，首月只返回 `2024-09-27`。区间维护按实际期末取数，异常日期按 §4.1 报错。保留 §4.2 的期末合成，首月的单条人工修复见 §4.3.4。 |
| 北证 50 的 2022 年 11 月月线 | 正式源无返回，现行合成要求月内全部 22 个开市日日线齐全，而发布日期起只有 8 个应有交易日，且这 8 天已齐。本批未用旧「维护指数周线/月线服务表」，该入口会改动同区间其他代码和两种频率，且字段单位不同。后续修复见 §4.3.3。 |

共 22 项任务和 40 个单元，正常执行每单元一次按代码和日期请求，每项最多 3 个单元。复查只读相同 40 个目标键。请求结果不明时先查任务记录，再按仍缺的代码和日期补提交。若全部需要重跑，额外业务取数仍为 40 个单元，源连接失败触发的内部重试另计。验收核对任务终态、36 个正式 Raw 和对应 Serving 来源、4 个北证 50 合成值，并记录剩余缺口。 [现行写入器](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py) · [旧维护任务执行器](/Users/congming/github/goldenshare/src/ops/runtime/task_run_dispatcher.py)

2026-11-10 17:26（上海时间）验收，任务 `19042` 至 `19063` 全部成功。逐键确认 36 条正式周线写入 Raw，对应 Serving 的来源均为 `api`。北证 50 四个周线期末均已写入 Serving，来源均为 `derived_daily`。Serving 剩余缺口为北证 50 的 `2022-11-30` 月线。中证 A500 的 2024 年 7 个周线期末和 1 个月线期末仍无正式 Raw。

#### 4.3.3 定点补北证 50 首月和清理发布前 Serving

2026-11-10 确认补北证 50 首月、清理审计列明的发布前记录，并以正式期末值替换仍能匹配的合成值。已复查 Tushare。北证 50 自发布以来的周线、月线区间均为空。中证 A500 的 7 个周线期末和 2024 年 9 月月末仍无对应日期，保留已算到期末的 8 根合成 K 线。源返回的较早日期按 §4.1 处理。

| Prod 表 | 本次写入范围 |
| --- | --- |
| `core_serving.index_weekly_serving` | 删除科创 50（`000688.SH`）2020-01-03 至 2020-07-17 的 28 根 `derived_daily`，删除中证 A500（`000510.SH`）2024-09-20 的 1 根 `api`。两段日期均早于各自发布日期。 |
| `core_serving.index_monthly_serving` | 删除科创 50 2020-01-23 至 2020-06-30 的 6 根 `derived_daily`。北证 50（`899050.BJ`）只补 `trade_date=2022-11-30`、`period_start_date=2022-11-01` 的 `derived_daily`。 |

现行后台的按代码月线任务要求整月 22 个开市日日线。北证 50 于 11 月 21 日发布，从该日到月末的 8 个开市日日线 Raw 已齐。另一个旧维护任务会写两种频率和其他指数，也无法按代码清理。本次经现有 Prod PostgreSQL 连接仅处理上表指定记录。计算按 §2 的价格、量额和涨跌幅规则。月线唯一键继续取该自然月第一个开市日，计算窗口从发布日期开始。日期、K 线来源、配置、应用代码和其他数据集继续按原方案。 [现行写入器](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py) · [月线 Serving 表定义](/Users/congming/github/goldenshare/src/foundation/models/core_serving/index_monthly_serving.py)

执行前只读核对日历、发布日期、8 条日线的完整性、正式 Raw 是否已到、两张目标表的唯一键以及待清理行。先导出 35 条目标行的完整字段到工程外权限受限的回退文件，并核实行数。一个短事务按业务键和备份指纹复核后删除 29 条周线、6 条月线并插入 1 条月线，任何目标数或字段不符即回滚。以 35 个待清理键、8 个应有交易日、1 个目标月线和对应正式 Raw 为业务读取范围。验收只读复查 35 个删除键和 1 个新增键。连接中断先复查提交结果，只有原数据仍与备份一致时才重跑同一范围。需撤销时，用备份按原键还原原行，仅撤掉本次生成且数值未被后续任务改动的月线。备份外的过程文件在收尾清理。

2026-11-10 17:46（上海时间）验收。事务提交了 29 条周线删除、6 条月线删除和 1 条月线新增。北证 50 `2022-11-30` 月线收盘为 `1018.8664`，来源为 `derived_daily`。按各自发布日期起算，10 个指数的 Serving 周线至 `2026-11-06` 共 8,775 条，月线至 `2026-10-30` 共 2,069 条，均无缺期、无发布前记录。回退备份为 `/private/tmp/goldenshare-index-serving-repair.qyJvl2RP/serving-before.jsonl`，核对 35 条完整记录。

#### 4.3.4 中证 A500 的 2024 年 9 月月线人工修复

管理员确认用日线计算值同步写两层。执行前已核对中证 A500（`000510.SH`）发布日期 `2024-09-23`，当月最后一个开市日 `2024-09-30`，正式月线点查为空。Prod 对应月份的 Raw 为空，Serving 已有一根合成月线，`period_start_date=2024-09-02`、`trade_date=2024-09-30`。从 `raw_tushare.index_daily` 读发布日期至期末的 6 个应有开市日，按 §2.2 重算并与现有 Serving 逐字段比对。已核对两者一致，收盘为 `4684.8913`。

通过现有 Prod PostgreSQL 连接执行一个短事务，按 `(000510.SH, 2024-09-30)` 向 `raw_tushare.index_monthly_bar` 写入一行，明确设置 `api_name=derived_daily`，`raw_payload` 为空。按 `(000510.SH, 2024-09-02)` 同步更新一行 `core_serving.index_monthly_serving`，`trade_date=2024-09-30`，`source=derived_daily`。执行前保存原 Serving 行的工程外回退备份，校验日期、6 条日线、两个目标键和来源后再写。读取范围为当月日历、6 条 Raw 日线及两个目标键，写入范围为两行。任一条件不符即回滚。中断后按两键读回确定是否已提交，验收比对两层所有行情字段及来源。需撤销时，按备份还原 Serving，并移除本次新增且仍标为合成的 Raw 行。

这根 Raw 只作为经确认的人工补录，正式到数及 Serving 正式覆盖以 `api_name=index_monthly` 为准。后续取到相同期末的正式行时按同一 Raw 主键覆盖，来源一同更新，Serving 再按 §4.2 采用正式值。现行版本按单代码提交同一期末可保留有效旧 Raw，正式行由现有 [Raw upsert](/Users/congming/github/goldenshare/src/foundation/dao/base_dao.py) 更新行情字段及来源。现行不指定代码的整期刷新会先删除该日 Raw，在旧版本上复查这个期末时应明确指定代码。 [现行指数月线写入器](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)

2026-11-10 19:30（上海时间）验收。Raw 新增一行、Serving 更新一行，均为 `2024-09-30`，两层的九个行情字段一致，来源均为 `derived_daily`。9 月 27 日 Raw 行数为零。原 Serving 行的回退备份为 `/private/tmp/goldenshare-a500-monthly.TfxBwSm8/serving-before.jsonl`。

## 5. 拟改位置与现行消费者

| 位置 | 现行行为和拟改边界 |
| --- | --- |
| DatasetDefinition、计划与请求 | [现行定义](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/index_series.py) 的周、月线正式维护改用已有 `raw_collection`、`raw-only`、`raw_only_upsert`，目标表和写入 DAO 指向各自的 Raw，Serving 由独立动作登记。保留两个外部数据集的身份、源字段和正式维护入口。[日期规划](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py) 当前周线单日直接采用输入日，区间会把截断周的最后开市日当期末。改用完整周历校验单日，区间只取落在输入范围内的真实期末。月线沿用完整月历判定。Ops 提交意图，Resolver 和 planner 展开范围，request builder 映射源参数。 |
| 正式 Raw 和 Serving 写入 | [现行写入器](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py) 的 `raw_index_period_serving_upsert` 分支写两层、使用日线池并包含清除未返回行与日线合成，随本次改造撤除。Raw 按 §4.1 写入。独立 Serving 执行器调用 Foundation 的周期读取、计算和写入。现有 [通用发布服务](/Users/congming/github/goldenshare/src/foundation/serving/publish_service.py) 中两项周期线 builder 按 `(ts_code, trade_date)` 定位，撤除其注册和相关引用，避免它绕过 §4.2 的周期唯一键和独立池。 |
| 旧合成入口 | 移除 [动作和工作流目录](/Users/congming/github/goldenshare/src/ops/action_catalog.py) 的 `maintenance.rebuild_index_kline_serving` 和 `index_kline_maintenance_pipeline` 的合成末步 `rebuild_index_serving`，以及 [dispatcher 执行代码](/Users/congming/github/goldenshare/src/ops/runtime/task_run_dispatcher.py)。核对调度、手动、工作流、发布和重试引用。历史任务仍可读，旧重试不能触发已退出的执行入口。两个现有工作流的周、月步骤仍引用各自的正式维护，改造后这些步骤只写 Raw。 |
| 正式 Raw 自动取数 | 周、月线维护动作分别声明 §3.1 的排程规则，由现有 [排程策略](/Users/congming/github/goldenshare/src/ops/services/dataset_schedule_time_policy_resolver.py) 读取动作声明。[自动任务服务](/Users/congming/github/goldenshare/src/ops/services/operations_schedule_service.py) 负责日历预览和下次触发时间，沿用 [排程存储](/Users/congming/github/goldenshare/src/ops/models/ops/schedule.py) 的 `calendar_policy`、`cron_expr`、`timezone`。月线的现行通用「每月最后一个交易日」策略按触发日所在月生成日期，继续供其他数据集使用。指数月线维护动作单独采用次月触发、上月取数的规则，由 [排程转任务](/Users/congming/github/goldenshare/src/ops/services/task_run_service.py) 保存生成的取数日期。[自动任务页面](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-auto-tab.tsx) 和 [API 类型](/Users/congming/github/goldenshare/frontend/src/shared/api/types.ts) 同步支持两个动作的排程规则。 |
| Serving 手动控件与盘后日更 | [手动任务](/Users/congming/github/goldenshare/src/ops/services/manual_action_service.py) 复用现有单日输入和代码筛选契约，后端按 §4.2 校验。盘后日更使用预定触发时刻的上海日期生成目标交易日。 |
| 正式月线入库后触发 Serving | 在 [Worker 任务收尾](/Users/congming/github/goldenshare/src/ops/runtime/worker.py) 处理 §4.2 指定的正式月线任务。Raw 业务事务已提交，使用 [TaskRun 创建方法 `stage_task_run`](/Users/congming/github/goldenshare/src/ops/services/task_run_service.py) 将上月 Serving 任务入队，与原任务的成功终态一同提交到 Ops。入队失败在原任务详情报告收尾错误，已提交的 Raw 保留。上月 Serving 任务详情单独记录更新结果。 |
| Serving 执行与失败汇总 | 在 [现有 Worker 装配](/Users/congming/github/goldenshare/src/app/runtime/ops_worker_factory.py) 注册两个动作共用的执行器。现有 [dispatcher](/Users/congming/github/goldenshare/src/ops/runtime/task_run_dispatcher.py) 在维护单元抛错时会停止后续单元。Serving 的代码级数据缺失、连续性失败应记录为该代码失败，继续处理后续代码，最后返回失败及已写入数量。适配只用于这两个 Serving 动作，取消仍停止领取新代码。 |
| 报错与重试 | 复用 [任务详情页](/Users/congming/github/goldenshare/frontend/src/pages/ops-task-detail-page.tsx)、[问题查询](/Users/congming/github/goldenshare/src/ops/queries/task_run_query_service.py) 和 [重试入口](/Users/congming/github/goldenshare/src/ops/services/task_run_service.py)。现有 `period_source_summary` 按任务日期查询当前 Serving 的来源分布。新正式取数任务详情只用本任务 Raw 结果与报错，去掉这项 Serving 统计。Serving 任务详情用本任务的代码级结果。正式取数重试重新请求原范围，Serving 重试按 §4.2 读 Raw。 |
| 行情接口和运营查询 | [通用行情 API](/Users/congming/github/goldenshare/src/biz/api/quote.py) 经 [查询服务](/Users/congming/github/goldenshare/src/biz/queries/quote_query_service.py) 直接读取两张 Serving，并按 `trade_date` 查询及排序，单位见 §2.2。核对池收窄导致的池外结果及同周期日期推进。[现行审查中心查询](/Users/congming/github/goldenshare/src/ops/queries/review_center_query_service.py) 以所选资源为覆盖率分母，不能用日线池覆盖率衡量周、月线池。 |

| 其余 Definition 消费方 | 改造边界 |
| --- | --- |
| 目录、分层展示、Probe | [数据集目录](/Users/congming/github/goldenshare/src/ops/catalog/dataset_catalog_views.py) 保留两个 Tushare 条目和分组，分层信息消费新的 Raw 定义。现有 Probe、发布策略及自动任务能力须回归，首期不为周、月 Serving 新增探测规则。 |
| 时效、状态快照、现有日期完整性 | [状态投影](/Users/congming/github/goldenshare/src/ops/dataset_definition_projection.py)、[时效查询](/Users/congming/github/goldenshare/src/ops/queries/freshness_query_service.py)、[状态快照](/Users/congming/github/goldenshare/src/ops/services/operations_dataset_status_snapshot_service.py) 和 [日期完整性查询](/Users/congming/github/goldenshare/src/ops/queries/date_completeness_query_service.py) 从 Definition 取目标表。两个 Tushare 数据集改为观测正式 Raw。时效查询复用当前的应到日期计算入口，实时读取和读到快照时均按 §3.1 的排程判断。历史完整性按完整周期日历判断实际期末，截断到周中或月中的查询不应产生虚假期末。Serving 缺数通过现有任务详情和 Biz 卡片定位。 |
| 测试和文档 | 更新引用旧写入路径、旧动作、旧发布器、旧任务统计和截断周日期的测试。实现落地时同步 [数据集开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)、[工作流目录](/Users/congming/github/goldenshare/docs/ops/ops-workflow-catalog-v1.md)、[日期模型指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md) 及 [Ops API 参考](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md) 的对应现行说明。 |

### 5.1 数据后台的 Tushare 和 Biz 卡片

现有 Tushare 列表按逻辑数据集建卡，周、月线各一张。页面优先显示 Raw 表名，但观测取自 Definition 的目标表，周、月线当前都指向 Serving。Biz 列表已有独立卡片查询，现有按日期观测的实现读取表内最新一条业务日期。 [Tushare 卡片查询](/Users/congming/github/goldenshare/src/ops/queries/dataset_card_query_service.py) · [状态观测](/Users/congming/github/goldenshare/src/ops/queries/freshness_query_service.py) · [Biz 卡片查询](/Users/congming/github/goldenshare/src/ops/queries/biz_table_card_query_service.py)

| 列表和卡片 | 状态和日期依据 | 维护入口 |
| --- | --- | --- |
| Tushare · 指数周线、指数月线 | 沿用 `index_weekly`、`index_monthly` 卡片。展示 §1 对应 Raw 表名、最近已入库的正式期末及最近正式取数任务结果。按 §3.1 的排程判断应到的期末。月线到次月首个交易日的配置时点才开始检查上月是否到数，展示已入库正式行的 `trade_date`。状态快照重建和正式任务完成后的刷新均观测正式 Raw。 | 周线为 `index_weekly.maintain`，月线为 `index_monthly.maintain`。 |
| Biz · 指数周线 Serving、指数月线 Serving | 通过 [Biz 卡片目录](/Users/congming/github/goldenshare/src/ops/catalog/biz_dataset_definitions.py) 分别关联 §1 的两张 Serving 表。展示日更目标交易日、池内已更新数／应更新数和最近 Serving 任务结果。按目标日所属的周期键查池内记录，`trade_date` 达到目标日的代码计为已更新。应更新数取整个周、月线激活池，首期为 10。 | 分别关联 §4.2 的 Serving 手动更新动作和已配置的自动任务。手动更新沿用 §4.2 的目标日与代码选择。失败详情沿用现有任务详情。 |

复用 [卡片接口](/Users/congming/github/goldenshare/src/ops/api/dataset_cards.py)、[Tushare 页面](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-tushare-page.tsx)、[Biz 页面](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-biz-table-page.tsx) 和 [共用卡片页面](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-source-page.tsx)。后端提供目标日、覆盖数和对应任务结果，前端展示这些值。Serving 日更覆盖以该频率排程应处理的最新交易日为目标，仅查询该周期和池内代码。单条最大 `trade_date` 不能作为全池已更新的依据。人工补历史和自动更新上月期末的任务结果按其实际目标日显示，卡片的日更覆盖仍以当前应更新的交易日为准。

## 6. 长任务、事务与预算

| 项目 | 执行边界 |
| --- | --- |
| 单元与规模 | 常规正式取数和历史区间维护都以一个频率、一个实际期末日及当次代码筛选为单元。Serving 切换清理按表和池外代码分批。日常 Serving 每频率最多处理池内 10 个代码。 |
| 分页、内存与请求量 | 按 §4.1 串行取数，每个任务只在内存保留一个期末，写完后释放这批数据。Tushare 每页最多 1,000 行，按该页大小取完 `R` 行需 `floor(R / 1,000) + 1` 次请求，恰好满页还需空尾页。总页数和行数由源返回决定。遇到重复页或分页没有进展时，该期取数失败。取数结束且整批校验通过后才按 [BaseDAO 分批规则](/Users/congming/github/goldenshare/src/foundation/dao/base_dao.py) 写 Raw，所有写入批次共用该期的一个事务。完整执行的内存和耗时待按 §8.1 核验。 |
| 正式历史取数预算 | 先按完整交易日历统计区间内实际期末数，再汇总各期末的分页请求。明确指定单代码时，每个期末正常请求一次，空结果也计一次。数据后台重试时按整个原日期区间和原代码范围重新计入取数、校验和写入，连接器自动重试消耗的额外请求另计。验收按目标期末和代码读回。当前连接器样本配置为每接口每分钟 280 次，属于本地限速设置。 |
| 日常 Serving 读取量 | 单频率任务至多读取 70 条周线合成用日线或 310 条月线合成用日线，分别为 10 个代码乘 7 日或 31 日。命中正式值则跳过相应日线读取。 |
| 持久化、幂等与重试 | Raw 和 Serving 分开提交，各按现有业务键写入。正式取数单元完成分页和校验后逐期提交。数据后台重试按 §4.1 使用原请求，已提交的期末保留并可按原键更新。切换清理按 §4.3 根据已核对的备份范围和实际剩余记录续跑，池内记录始终排除在删除条件之外。Serving 更新重复写入不能增加第二根同周期 K 线，不使用覆盖全历史的长事务。 |
| 取消、进度与终态 | 页和单元前后检查取消，停止领取新单元。按仓库长任务要求，运行中 30 秒内有可见更新，长调用须可安全中断或分段。现有普通 `fetch` 在一单元所有分页结束后才返回，不能直接满足分页间取消和进度要求。正式取数复用现有分页接口，将取消和进度接入实际取页过程，单次调用使用可中断的现有 Tushare 客户端能力。TaskRun 展示阶段、代码或日期窗口、完成量、总量、百分比、最后更新时间，无法可靠估算时显示“暂无法估算”。成功、失败或取消时 TaskRun 与活动节点终态一致。观测失败不回滚已提交的业务数据。 [现有分页实现](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py) · [Tushare 客户端](/Users/congming/github/goldenshare/src/foundation/clients/tushare_client.py) |
| 切换和验收成本 | 单日期末任务中断后重跑原期末，样本分别需重读 15 页或 5 页，入库和读回另计。日期区间任务按上表的原区间重试规则核算。切换前按两表实际的池外记录数估算备份和删除规模。续跑按尚未删除的批次计，回退按已删除并需恢复的行数计，验收计入池外计数及池内计数和抽查。通过获准的代表性运行测量耗时、锁、空间和 WAL，并核验中断、续跑、幂等与回退。 |

## 7. 已确认需求与验收

| 需求 | 实施位置 | 计划验收 |
| --- | --- | --- |
| R1 期末正式维护只写 Raw，按源范围保存 | §2.1、§3.1、§4.1 | 普通周和周五休市的短周分别在实际末日收盘后触发，并请求该日。验证常规维护和按代码补历史共用期末取数，池外有效正式记录照常入 Raw。单日选择非期末、维护区间截断到周中时不生成该周期的正式请求。期末请求返回非期末行时，任务失败，详情列出代码和日期，该期不写入，先前已提交的期末保留。校验短页、空尾页和源空或部分到达时的保留规则。正式维护只写 Raw。 |
| R2 正式维护失败按原范围重新请求 | §4.1、§6 | 用多个期末的区间让其中一期失败。重试请求覆盖整个原区间及原代码，先前提交的期末保留，重复写入按原业务键更新。Serving 重试只读已落地的 Raw，运行失败不撤销 Raw。 |
| R3 Serving 手动更新与盘后日更 | §3、§4.2、§5 | 数据后台分别配置周、月盘后日更。人工选择频率、日期和需要处理的代码。盘后日更写入预定触发日，验证跨午夜的出队或重试不将它换成新日期或继续写入。过上海时间午夜转人工，历史非期末、未收盘或休市日期不能作为目标。 |
| R4 Serving 先取正式，缺正式才合成 | §2.3、§4.2 | 有正式 Raw 即使缺日线或断档，也覆盖同一根 K 线。中证 A500 9 月 30 日的人工 Raw 行标为 `derived_daily` 时仍走合成口径，6 条日线合成的收盘为 4684.8913 点。以后收到该期正式 Raw 时可覆盖。用北证 50 验证无正式 Raw 和以后有正式 Raw 两种路径。已发布的正式值不会被合成覆盖。 |
| R5 当前周期连续性和单指数失败 | §4.2 | 首个应有日创建，11-09 成功、11-10 缺失、11-11 已有日线时保留 11-09，任务显示预期和实际日期。失败代码后的正常代码仍会执行并提交，任务最终失败，另一频率独立。人工先补 10 日再补 11 日，同日重跑不新增 K 线，较早任务不让截至日倒退。 |
| R6 人工补已结束周期 | §4.2 | 选某个过去的周、月期末，有正式 Raw 直接写，无正式 Raw 且日线完整一次补齐。缺日线时保留旧值，在现有任务详情列出缺失日期。 |
| R7 独立激活池、历史起点和切换顺序 | §3、§4.3 | 核对首期仅有 10 个代码且不能日常增删。两张 Serving 表只删除池外行。核对这 10 个代码的日期范围、记录数和代表性行情值均保持一致，覆盖正式值和北证 50、中证 A500 的合成值。周线历史至 11-06，11-09 起接续；月线历史至 10-30，从 11 月首个开市日起独立接续。日线池回归，二期增删单独验收。 |
| R8 正式与合成单位一致 | §2.2 | 用已知的真实周、月样本核对量、额倍率、4 位小数及涨跌幅。覆盖前后单位一致，正式值保留源值。上证 50 和创业板指的首期正式行前收盘为 0 时，验收 Raw 和 Serving 均按源值保留且正常发布。现有通用行情接口单位回归，财势乾坤后续接入时验收手、千元及百分数展示。 |
| R9 移除旧合成入口 | §5 | 正式维护、现有工作流及旧重试不能绕回旧合成，历史记录可读。池外代码不能进入周、月 Serving，现有日线维护入口仍有效。 |
| R10 长任务和安全切换 | §4.3、§6 | 获准的代表性运行核对源、归一化、拒绝和读回，演练中断后续跑、幂等、取消、进度、状态写入失败和节点终态。切换清理中断后验证续跑只删除剩余池外记录，回退只恢复本次已删除的池外记录并撤销本次激活池变更。 |
| R11 Tushare 卡只展示正式 Raw 的取数状态 | §5.1，Tushare 卡片 API、状态快照与页面 | 周、月各保留一张。以周一盘后为例，Raw 截至上周五且 Serving 已到周一时，Tushare 周线卡仍显示上周五并按正式期末判断。卡片入口发起正式取数，任务详情显示 Raw 取数结果，已有的 Serving 合成行不会计入该任务。 |
| R12 Biz 卡独立展示 Serving 日更与补数 | §5.1，Biz 卡片 API、页面及任务详情 | 周、月各显示一张。10 个指数均到目标日时显示 `10/10`。任务因一个指数未更新而失败时，显示 `9/10` 和失败结果，可进入任务详情查看缺数代码。验证两张卡分别发起对应 Serving 手动更新，且补跑历史任务不改变当前日更覆盖的目标日期。 |
| R13 正式月线在次月触发，提交后更新上月 Serving | §3.1、§4.2、§5.1 | 用 2026 年 10 月验证 11 月首个交易日上海时间 19:00 后触发，取数及其重试均使用 10 月 30 日。正式 Raw 提交后才创建独立的上月 Serving 任务，覆盖同一根 K 线。取数失败或空返回时保留原 Serving。Serving 任务失败后可单独重试，Raw 保持已提交。11 月日更独立运行，目标日和卡片覆盖日期均为 11 月对应交易日。验证 Raw 卡在配置时点前后判断应到期末，人工合成行不计为正式到数。 |
| R14 按代码补历史时集中报告空期 | §4.1 | 用前后有正式数据、中间空返回的三个期末验收。前后两期照常写 Raw，任务详情列出中间缺期的代码和日期，终态为部分成功。全部缺期时标记失败。另用返回非期末日期的样本验证该期不入库并报任务失败。 |
| R15 同一期取完并校验后提交 | §4.1、§6 | 验证多页的期末在末页取完和整批校验前均无 Raw 写入，校验通过后整期提交一次。让后页取数失败或返回错误日期，核对本期没有写入、前一期已提交的数据保留。另在分批写入时注入失败，核对当前期末所有写入一并回滚。 |

现有测试入口包括[周期线数据库测试](/Users/congming/github/goldenshare/tests/test_index_monthly_postgres.py)、[分层写入测试](/Users/congming/github/goldenshare/tests/test_dataset_writer_index_layer_alignment.py)、[日期规划测试](/Users/congming/github/goldenshare/tests/test_index_monthly_calendar.py)、[动作目录测试](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)、[自动任务 API 测试](/Users/congming/github/goldenshare/tests/web/test_ops_schedule_api.py)和[任务 API 测试](/Users/congming/github/goldenshare/tests/web/test_ops_task_run_api.py)。卡片沿用[卡片 API 测试](/Users/congming/github/goldenshare/tests/web/test_ops_dataset_cards_api.py)和[数据源页面测试](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-source-page.test.tsx)，实施后在浏览器核对两个列表及维护入口。旧行为的用例随旧入口撤除而更新。源字段和计算预期须采用独立的真实依据。以上均为验收计划。

## 8. 开工与正式执行前的核验

### 8.1 核验结论与实施前事项

**合成输入缺值。** 六个首期、69 条源日线均有有效前收盘及 OHLC、量额。发现的四条零前收盘记录来自正式周、月线，沿用原值发布。对合成输入实际缺失所需字段或首日前收盘不可用的情况，建议沿用现有月线合成对不完整窗口的处理，保留上一根有效结果，在任务详情列出代码、交易日和字段，不用零值代填。样本未出现这种合成输入，验收用反例验证。 [现有月线合成完整性检查](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)

**取数和资源核验。** 业务按 §4.1 取齐 Tushare 的实际分页。§2.1 的 11 月 6 日周线样本为 14,211 行、15 次请求，主进程取数和归一化的 Python 分配峰值约为 33.8 MB。前序周、月样本均有 16 页。仓库的长任务开工要求仍需核定本地内存预算及运行耗时。以代表性单期测量取数、归一化、入库和提交全过程，计入连接器子进程和数据库写入阶段，并与实际 Worker 的可用内存核对。现有样本只覆盖上述实测阶段。原区间重试和读回的工作量按 §6 核算。

### 8.2 正式执行前

历史覆盖及周、月截止日已按 §4.3.3 验收。正式切换前，按 §4.3 核对 10 个保留代码、待清理范围和备份，按 §6 验证切换预算、写入隔离和回退，并完成代表性最小真实验收。

获准切换正式取数排程时，按 §3.1 调整已有的指数周、月线自动任务配置，并在数据后台预览下一次触发时间和核对对应取数日期。Serving 日更由管理员单独配置。清理验收后再启用盘后日更和正式月线入库后触发的上月 Serving 更新。
