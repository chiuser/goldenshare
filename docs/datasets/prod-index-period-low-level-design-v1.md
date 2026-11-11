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

开工审计通过项目连接器对两种频率各补查两次，均使用 `limit=1`、`offset=0` 和字段 `ts_code,trade_date`。无业务参数时两种频率均返回 `50101`，要求至少输入 `ts_code` 或 `trade_date`。仅指定 `ts_code=000001.SH` 时，各返回一行，周线日期为 `20261106`，月线日期为 `20261030`。该次补查用于核对参数行为，正式维护仍按 §4.1 的实际期末逐期请求。

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
| 指数周、月线 Serving 激活池 | 复用 `ops.index_series_active`，固定 `resource=index_period_serving`，每个指数沿用 `(resource, ts_code)` 主键。资源值在 [Ops 指数池适配模块](/Users/congming/github/goldenshare/src/ops/index_series_active_store_adapter.py) 集中声明。 | 切换初始化、周月线 Serving 任务、数据卡片及通用增删入口共用同一资源值。切换时写入原方案 §4 的 10 个代码并读回核对，清理范围按已核对名单确定。常规期末取数不使用该池裁剪源数据，日线两池保持现状。 |
| 指数发布日期 | 使用已核实的指数基础信息 `list_date`，与池内 `first_seen_date` 分开。 | 控制每个代码的历史起点和首期应有日线范围。 |
| 交易日历 | 使用现有 `DEFAULT_EXCHANGE` Settings，源码默认 SSE，业务时间按上海时区。 | 确认实际日历配置和适用交易日，统一确定期初、期末、上一交易日与所需日线日期。 |
| 正式 Raw 自动任务 | 沿用数据后台的自动任务配置，具体规则、默认值和校验见 §3.1。 | 周线按当周实际最后交易日触发，月线按次月首个交易日触发。 |
| Serving 盘后日更 | 周、月线分别由管理员在数据后台配置，首期以日线 Raw 在上海时间 22:00 前就绪为排程假设。 | 两个动作各按计划触发当天的交易日执行。配置与目标日期见 §3.1，午夜截止和重试见 §4.2。 |

[现行审查中心页面](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-review-index-page.tsx) 使用日线资源，[后端通用增删命令](/Users/congming/github/goldenshare/src/ops/services/review_center_service.py) 接受资源参数。首期后端拒绝这些命令对 `index_period_serving` 的新增和移除请求。

### 3.1 自动任务的排程和目标日期

| 自动任务 | 动作固定的 `calendar_policy` | 触发日期和可配时刻（上海时间） | 写入 TaskRun 的目标交易日 |
| --- | --- | --- | --- |
| 指数周线 Raw（`index_weekly.maintain`） | `weekly_last_trading_day` | 自然周最后一个交易日，15:00 起。周五休市时用实际最后开市日。 | 计划触发日，即本周最后一个交易日。 |
| 指数月线 Raw（`index_monthly.maintain`） | `monthly_first_trading_day` | 每月首个交易日，19:00 起。 | 计划触发日的上一个自然月最后一个交易日。 |
| 指数周线 Serving（`maintenance.update_index_weekly_serving`） | `trading_day_point` | 每个交易日，15:00 起。 | 计划触发日。 |
| 指数月线 Serving（`maintenance.update_index_monthly_serving`） | `trading_day_point` | 每个交易日，15:00 起。 | 计划触发日。 |

月线 19:00 的依据是 Tushare MCP 的 `index_monthly` 接口说明，标注每月首个工作日 19:00 更新上月数据。15:00 沿用[指数周期线 Serving 的收盘判断](/Users/congming/github/goldenshare/src/foundation/ingestion/index_period_serving.py)。首期 22:00 是日线 Raw 的预计就绪时间，供管理员选择 Serving 日更时刻时参考。

四项任务复用 [`ops.schedule`](/Users/congming/github/goldenshare/src/ops/models/ops/schedule.py)。动作固定 `target_type`、`target_key` 及表中所列日期策略，统一使用定时触发（`trigger_mode=schedule`）、周期执行（`schedule_type=cron`）和 `timezone=Asia/Shanghai`。管理员在自动任务页填写一个时刻，保存为 `cron_expr` 的 `分 时 * * *`，触发日期由交易日历筛选。服务端校验动作与策略的对应关系、时区及配置时刻。触发时刻由管理员设置，部署时不自动创建或启用任务。周期配置的 `next_run_at` 由服务端计算。

两项正式 Raw 动作在 DatasetDefinition 声明日期策略，允许的周期表达式形状为 `daily`，生成的时间模式为 `point`，日期字段为 `trade_date`，禁止显式日期，策略参数为空。两项 Serving 动作由 Ops 维护动作目录声明同样的约束。四项自动任务均按各自的数据范围执行，自动任务的 `params_json` 不指定日期或指数代码。管理员手动点查、区间维护或指定 Serving 代码仍按 §4.1、§4.2 执行。

排程预览和实际下次运行时间使用同一日期规则及 §3 指定的完整交易日历。周线跳过全周休市的自然周，Serving 日更跳过休市日。预览返回触发时刻。任务创建时读取计划触发时刻的上海日期，按上表生成 `time_input.trade_date`，从任务详情核对目标日。月线 2026 年 11 月首个交易日 19:00 的计划触发，对应 TaskRun 日期 `2026-10-30`，再由 Resolver 和 request builder 生成 Tushare 请求 `trade_date=20261030`。月线的历史日期模型仍为 `month_last_open_day`。已有的通用排程策略继续用于其他数据集。配置启用和旧排程的处理顺序见 §8.2。

任务入队后使用已保存的目标日期。正式 Raw 任务重试沿用原目标期末和代码范围。正式月线自动取数成功提交 Raw 后按 §4.2 单独触发上月期末的 Serving 更新。

## 4. 执行流程与失败处理

### 4.1 正式周、月线 Raw 维护

1. 常规维护与历史区间补数共用同一入口和期末校验。单日取所选期末，区间按完整交易日历展开范围内的各真实期末。这里的一期指一个已结束的交易周或交易月，用该期最后一个交易日查询。有代码就按指定代码取，未指定代码时取该期 Tushare 返回的所有指数行情。
2. **先取完一期，再写 Raw。** 同一期的各页全部暂存在内存，直到返回不足 1,000 行的一页，空页也表示取完。单期的页数和行数随 Tushare 实际返回。取完后统一检查字段、业务键和请求范围，校验通过才开始写 Raw。同一期可分多批执行数据库写入，全部写完后提交一次，再处理下一期。例如 2026-11-06 的周线样本分 15 页返回 14,211 行，末页 211 行，这 15 页作为同一批校验并提交。
3. 任一页最终取数失败或取数期间取消时，丢弃当前期末暂存的数据。写入前要求所有返回的 `trade_date` 等于目标期末，发现日期不符时，该期不写入，任务失败，详情列出频率、代码、预期和实际日期。写入中失败则回滚本期事务。以上情况均保留先前已提交的期末。
4. 按代码补历史时，某期空返回就记为源缺期，记录频率、代码和期末，继续取后面的期末。已到的正式数据照常逐期提交，任务结束后在详情集中列出缺期。采用现有任务终态，有期末成功且有缺期时标记部分成功，全部缺期时标记失败。单次正式取数空返回时在任务详情报告期末和可确定的缺失代码。空返回、部分返回或请求失败均保留既有有效 Raw。全范围请求以源实际返回为准，缺失代码仅在有明确请求范围时判断。
5. 源延迟、失败或中断后，数据后台重试使用原频率、原期末或整个原日期区间及原代码重新请求 Tushare。已提交的 Raw 保留，重拉后按原业务键更新。正式月线自动取数成功后的上月 Serving 更新按 §4.2 执行。其他人工补到正式 Raw 后，运营可指定对应期末运行 Serving 更新。Serving 写入失败时单独重跑 Serving 任务。

### 4.2 独立 Serving 更新

运营可在同一当前周期内逐日指定已收盘的目标交易日，也可在跨期后选择过去周期的最后一个交易日。多个日子未成功时，从第一个未更新的交易日起按交易日顺序补。管理员配置的盘后日更在目标交易日执行。过目标交易日的上海时间午夜，尚未完成的旧日更任务转人工。

周线、月线在现有 Ops 维护动作目录分别注册，两个动作固定各自频率，共用计算和写入服务。手动任务沿用单日 `trade_date` 控件，可选池内代码，未选则处理全池。盘后日更按 §3.1 保存目标日并处理全池。通过排程生成的日更任务带 `schedule_id`，重试继承该字段、目标日和代码范围。Worker 在任务开始及处理各指数前核对截止时间。到了目标日次日的上海时间 00:00，日更任务停止处理未开始的指数，保留已提交行，任务标记失败。诊断显示原目标日，并提示运营使用手动入口补数。 [维护动作目录](/Users/congming/github/goldenshare/src/ops/action_catalog.py) · [手动表单定义](/Users/congming/github/goldenshare/src/ops/queries/manual_action_query_service.py) · [排程转任务和重试](/Users/congming/github/goldenshare/src/ops/services/task_run_service.py)

正式月线自动取数或其重试成功提交有效 Raw 后，Ops 用原 TaskRun 的 `trade_date` 创建一条独立的月线 Serving TaskRun，处理周、月线激活池内代码。自动取数识别为带 `schedule_id` 的 `index_monthly.maintain` 定时任务或其重试。新建的 Serving 任务在任务列表显示为「系统触发」，使用月线 Serving 动作、原期末目标日和全池范围，按历史期末规则执行及重试。以 2026 年 10 月为例，11 月首个交易日晚触发的上月 Serving 任务目标是 `2026-10-30`，同晚的盘后日更目标是 11 月当天。两条任务分别执行，沿用各自目标日和周期键。正式取数失败、取消或没有提交正式 Raw 时，保留原 Serving。上月 Serving 任务失败时单独重试，读取已提交的 Raw。

每个任务按其频率独立处理。任务启动时按 `index_period_serving` 读取激活池，读到空池则在读取行情和写入 Serving 前结束，将任务标记为失败，并在现有任务诊断中显示「指数周、月线 Serving 激活池未初始化」。池内指数按下表执行。

| 顺序和条件 | 读写动作 |
| --- | --- |
| 1. 当期有正式周、月线 Raw | 读 `(ts_code, 当期最后交易日)` 对应的源记录。月线还须满足 `api_name=index_monthly`。直接按源值更新同一周期的 Serving，缺行可补建，来源为 `api`。无需检查日线及上一交易日。§4.3.4 的人工合成行按下方日线合成规则处理。 |
| 2a. 无正式 Raw，目标日处于当前周期 | 从该指数本周期首个应有交易日算到目标日。首日可创建。同周期已有同一目标日的合成值时，按相同窗口重算并更新同一条记录。除此之外，首日之后须先检查 Serving 的 `trade_date` 等于上一交易日，再检查窗口的应有日线是否齐全。合成来源为 `derived_daily`。 |
| 2b. 无正式 Raw，任务目标为过去周期的最后一个交易日 | 检查从该指数本周期首个应有交易日起的完整日线。齐全则一次计算整期并写入，`trade_date` 为该期最后交易日。无须依赖 Serving 的上一交易日记录。 |
| 3. 所需日线缺失或连续性检查失败 | 保留该指数旧 K 线和截至日，原先无记录则保持缺行。在内存记录该指数的失败明细，继续处理其余指数。 |

周线、月线各自在本次任务内汇总。处理完本次代码范围后，如有任一代码失败，将该任务标记为失败，保存量按实际提交到对应 Serving 表的行数计算。在任务收尾时，将内存中的所有失败明细一次写入现有 TaskRun 技术诊断，运营可在数据后台的任务详情查看。每条明细记录频率、代码、目标日或期末、失败阶段及原因，并列出缺失的日线日期，或者连续性检查的预期和实际截至日。

例如 11 月 9 日合成成功，10 日日线缺失，Serving 截至日仍为 9 日。11 日即使有日线，检查预期为 10 日、实际为 9 日，该指数更新失败。运营补到 10 日日线后，先指定 10 日更新，再执行 11 日。如果要补已经结束的这一周，人工选其最后交易日，按上表先取正式 Raw，缺正式 Raw 时检查完整周日线。

10 个代码都走相同顺序。北证 50 缺正式 Raw 时用日线合成，未来查到当期正式 Raw 时照常覆盖。按周期唯一键写入。每个代码独立提交，在同一业务事务中检查该周期的 Serving 行并更新，冲突时以实际已写入行判断。已有正式行或更晚的合成截至日时，保留原行。正式 Raw 仍可按第一步更新同周期。任务状态和错误记录在业务事务之外更新。

### 4.3 保留已补齐的历史、清理名单外记录与逐日接续

1. §4.3.1 至 §4.3.4 是切换前的历史补数和验收记录。切换后的取数、重试和 Serving 更新按 §4.1、§4.2 执行。10 个指数从各自发布日期起的 Serving 已齐备，周线截至 `2026-11-06`，月线截至 `2026-10-30`。这 10 个代码的现有 Serving 行全部原样保留，包括北证 50 和中证 A500 已确认的合成值。今后某一期取得正式期末 Raw 时，通过 §4.2 的单期更新覆盖相应合成值。
2. 获准切换后，先按 §8.2 暂停相关排程并处理待办任务，再隔离两张 Serving 表的写入。清理验收前暂停手动 Serving 更新，保持盘后日更及自动触发的上月 Serving 更新停用。将原方案 §4 的 10 个代码一次写入 `ops.index_series_active` 的 `index_period_serving` 资源并提交。清理前读回该资源的代码，逐项核对与保留名单一致。以已核对的名单为准，仅在 `core_serving.index_weekly_serving` 和 `core_serving.index_monthly_serving` 中按 `ts_code` 删除名单外记录。池内记录、Raw、指数日线和日线激活池均不在本次数据清理范围。
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
| DatasetDefinition、计划与请求 | 第一阶段已将[数据集定义](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/index_series.py)的周、月线正式维护改为 `raw_collection`、`raw-only`、`raw_only_upsert`，目标表和写入 DAO 指向各自的 Raw。保留两个数据集的身份、源字段和正式维护入口。[日期规划](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)已使用完整周历和月历校验单日期末，区间只取输入范围内的实际期末。Ops 提交意图，Resolver 和 planner 展开范围，request builder 映射源参数。第三阶段在现有动作声明中补上 §3.1 的排程规则。 |
| 正式 Raw 和 Serving 写入 | 正式 Raw 已按 §4.1 写入，第二阶段的独立 Serving 执行器调用 Foundation 读取、计算并写入周期行情。第三阶段移除[写入器](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)中仍保留的 `raw_index_period_serving_upsert` 分支及专用逻辑。现有[通用发布服务](/Users/congming/github/goldenshare/src/foundation/serving/publish_service.py)的两项指数周期线 builder 按 `(ts_code, trade_date)` 定位，第三阶段撤除其注册和相关引用，统一按 §4.2 的周期唯一键和独立池更新。 |
| 旧合成入口 | 移除 [动作和工作流目录](/Users/congming/github/goldenshare/src/ops/action_catalog.py) 的 `maintenance.rebuild_index_kline_serving` 和 `index_kline_maintenance_pipeline` 的合成末步 `rebuild_index_serving`，以及 [dispatcher 执行代码](/Users/congming/github/goldenshare/src/ops/runtime/task_run_dispatcher.py)。核对调度、手动、工作流、发布和重试引用。历史任务仍可读，旧维护动作的重试在创建任务时按现有动作目录校验拒绝。「指数K线全链路维护」继续接受日期区间，周、月步骤各自按区间内的实际期末只写 Raw。区间内无对应期末时，该步骤零次取数，后续步骤继续。同步更新工作流的描述和目录说明。 |
| 未使用的指数工作流 | 按管理员确认删除 `index_extension_maintenance`（指数扩展数据维护）的完整定义及现行目录说明。目录和手动入口继续从注册表生成，不另加前端过滤或兼容入口。保留五个数据集各自的维护动作及 `index_kline_maintenance_pipeline`。具体实施和验收见 §9.3。 |
| 自动任务配置、预览和执行日期 | 正式 Raw 动作的策略由 [DatasetDefinition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/index_series.py) 声明，[数据集排程策略解析器](/Users/congming/github/goldenshare/src/ops/services/dataset_schedule_time_policy_resolver.py) 负责读取。Serving 动作由 [维护动作目录](/Users/congming/github/goldenshare/src/ops/action_catalog.py) 声明日更排程。[自动任务能力解析器](/Users/congming/github/goldenshare/src/ops/services/schedule_automation_capability_resolver.py) 将四项动作的能力提供给目录接口与表单。[自动任务服务](/Users/congming/github/goldenshare/src/ops/services/operations_schedule_service.py) 校验配置、统一计算预览与下次运行时间，[排程转任务](/Users/congming/github/goldenshare/src/ops/services/task_run_service.py) 按计划触发时刻保存目标日。[自动任务页面](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-auto-tab.tsx) 和 [API 类型](/Users/congming/github/goldenshare/frontend/src/shared/api/types.ts) 消费同一动作声明，显示固定日期规则、执行时刻和预览。Raw 卡片在第 4 阶段使用 §3.1 的同一规则判断应到期末。 |
| Serving 手动控件与盘后日更 | [手动任务](/Users/congming/github/goldenshare/src/ops/services/manual_action_service.py) 复用现有单日输入和代码筛选契约。盘后日更在 [dispatcher](/Users/congming/github/goldenshare/src/ops/runtime/task_run_dispatcher.py) 依据维护动作、`schedule_id` 与已保存的目标日执行 §4.2 的截止规则。手动补数和系统触发的上月期末更新沿用 §4.2 的日期校验。 |
| 正式月线入库后触发 Serving | [Worker 任务收尾](/Users/congming/github/goldenshare/src/ops/runtime/worker.py) 按 §4.2 识别正式月线自动任务或其重试。只在最终状态为成功且本次实际保存了有效 Raw 行时调用 [`stage_task_run`](/Users/congming/github/goldenshare/src/ops/services/task_run_service.py)，为该 Raw 任务创建一条独立的月线 Serving 任务，目标日期取原 TaskRun，`trigger_source=system`，`schedule_id` 为空。入队和原任务及其当前节点的成功终态在同一 Ops 事务提交。入队或该事务失败时，在原任务详情记录收尾错误并保留已提交的 Raw。原任务可按 §4.1 重新请求，已入队的上月 Serving 任务可以单独重试。 |
| Serving 执行与失败汇总 | 在 [现有 Worker 装配](/Users/congming/github/goldenshare/src/app/runtime/ops_worker_factory.py) 注册两个动作共用的执行器。现有 [dispatcher](/Users/congming/github/goldenshare/src/ops/runtime/task_run_dispatcher.py) 在维护单元抛错时会停止后续单元。两个 Serving 动作按 §4.2 将单代码数据缺失和连续性失败作为业务结果在内存累计，处理完本次范围后，将实际保存量和失败明细统一交给任务收尾。取消仍停止领取新代码。 |
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
| 单元与规模 | 常规正式取数和历史区间维护都以一个频率、一个实际期末日及当次代码筛选为单元。历史区间随交易日历中的期末数增长，按长任务执行。Serving 切换清理按表和池外代码分批。日常 Serving 每频率最多处理池内 10 个代码。 |
| 分页、内存与请求量 | 按 §4.1 串行取数，每个任务只在内存保留一个期末，写完后释放这批数据。Tushare 每页最多 1,000 行，按该页大小取完 `R` 行需 `floor(R / 1,000) + 1` 次请求，恰好满页还需空尾页。总页数和行数由源返回决定。遇到重复页或分页没有进展时，该期取数失败。取数结束且整批校验通过后才按 [BaseDAO 分批规则](/Users/congming/github/goldenshare/src/foundation/dao/base_dao.py) 写 Raw，所有写入批次共用该期的一个事务。执行上限及超限处理见 §6.1，实测见 §8.1。 |
| 正式历史取数预算 | 先按完整交易日历统计区间内实际期末数，再汇总各期末的分页请求。明确指定单代码时，每个期末正常请求一次，空结果也计一次。数据后台重试时按整个原日期区间和原代码范围重新计入取数、校验和写入，连接器自动重试消耗的额外请求另计。验收按目标期末和代码读回。当前连接器样本配置为每接口每分钟 280 次，属于本地限速设置。 |
| Serving 更新预算 | 按一个频率、一个目标交易日和本次代码范围计入正常执行、原范围重试和验收读回。数量与隔离实测见 §6.2。 |
| 持久化、幂等与重试 | Raw 和 Serving 分开提交，各按现有业务键写入。正式取数单元完成分页和校验后逐期提交。数据后台重试按 §4.1 使用原请求，已提交的期末保留并可按原键更新。切换清理按 §4.3 根据已核对的备份范围和实际剩余记录续跑，池内记录始终排除在删除条件之外。Serving 更新重复写入不能增加第二根同周期 K 线，不使用覆盖全历史的长事务。 |
| 取消、进度与终态 | 页和单元前后检查取消，停止领取新单元。按仓库长任务要求，运行中 30 秒内有可见更新，长调用须可安全中断或分段。现有普通 `fetch` 在一单元所有分页结束后才返回，不能直接满足分页间取消和进度要求。正式取数复用现有分页接口，将取消和进度接入实际取页过程，单次调用使用可中断的现有 Tushare 客户端能力。TaskRun 展示阶段、代码或日期窗口、完成量、总量、百分比、最后更新时间，无法可靠估算时显示“暂无法估算”。成功、失败或取消时 TaskRun 与活动节点终态一致。观测失败不回滚已提交的业务数据。 [现有分页实现](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py) · [Tushare 客户端](/Users/congming/github/goldenshare/src/foundation/clients/tushare_client.py) |
| 切换和验收成本 | 单日期末任务中断后重跑原期末，样本分别需重读 15 页或 5 页，入库和读回另计。日期区间任务按上表的原区间重试规则核算。切换前按两表实际的池外记录数估算备份和删除规模。续跑按尚未删除的批次计，回退按已删除并需恢复的行数计，验收计入池外计数及池内计数和抽查。通过获准的代表性运行测量耗时、锁、空间和 WAL，并核验中断、续跑、幂等与回退。 |

### 6.1 正式 Raw 单期执行上限

- **内存。** 首期采用讨论中提出的 **3 GB（3,000,000,000 字节）**。对执行任务的 Worker 主进程和本任务的连接器子进程合计采样当前 RSS，达到阈值即退出本期。在期末开始、每页请求和接收、整批校验期间、每个写入批次及提交前检查。校验按每 1,000 行检查一次。等待网络响应时沿用可取消调用的检查点。数据库进程的内存在隔离验收中单独记录。§8.1 的任务进程合计采样峰值为 292.95 MiB，同日 Prod 主机可用内存约 9.69 GiB。
- **耗时。** 单期从开始取数到发出提交最多 **163 秒**，含限速等待、退避、取数、校验和数据库写入。按 §8.1 中较慢的取数与校验样本 `17.171 + 0.104` 秒向上取整为 18 秒，再计入一次异常页和它的一次重试各最多 30 秒、一次现有限频退避 65 秒，以及 20 秒数据库写入预算，共 `18 + 2 × 30 + 65 + 20 = 163` 秒。使用单调时钟计算剩余时间。单次源调用取 30 秒和单期剩余时间中的较小值，等待和重试共享同一期截止时间。数据库写入阶段取 20 秒和单期剩余时间中的较小值，SQL 按该阶段剩余时间设置 `statement_timeout`。 [源调用超时](/Users/congming/github/goldenshare/src/foundation/clients/tushare_client.py) · [限频退避](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py) · [数据库累计限时做法](/Users/congming/github/goldenshare/src/foundation/ingestion/stock_weekly_adj_execution.py)
- **请求量。** 正常读取到短页或空尾页。沿用本地限速器，按单期内固定的正速率 `r` 次/分钟估算，163 秒内最多发起 `ceil(163 × r / 60)` 次请求，含重试。例如按现有默认速率 `r = 280` 计算，最多发起 761 次，每页最多 1,000 行对应累计至多 761,000 行。实际取数以源端末页和本节内存、耗时条件决定。每页响应沿用 §8.1 验证时的 8 MiB 有界调用设置。 [本地限速器](/Users/congming/github/goldenshare/src/foundation/clients/tushare_client.py) · [8 MiB 取数依据](/Users/congming/github/goldenshare/src/foundation/datasets/stock_weekly_adj_contracts.py)
- **超限处理。** 提交前超限时停止取数或写入，释放本期暂存数据，已经开启的本期事务回滚。该期及任务记为失败，任务详情写明目标期末、阶段、触发的上限和采样值，保留此前已提交的期末，重试按 §4.1 执行。提交已发出后按数据库回执判定是否成功。回执不确定时按原期末读回核对，仍无法确认时按原范围幂等重试。

<a id="serving-update-budget"></a>

### 6.2 Serving 更新、重试和验收预算

设本次处理的池内代码数为 `N`，首期最多 10 个。每次执行先读激活池、目标日所在的完整交易日历和本次代码的发布日期。一个周历最多 7 个自然日，一个月历最多 31 个自然日。

| 步骤 | 按频率核算的业务量上限 |
| --- | --- |
| 单次执行 | 每个代码各查一个正式周期 Raw 键和一个 Serving 周期键。需要合成时按日历窗口读取指数 Raw 日线，周线最多 `7 × N` 条，月线最多 `31 × N` 条。按首期满池计算分别为 70、310 条。命中正式 Raw 时跳过该代码的日线查询。最多写入 `N` 行、提交 `N` 个单代码业务事务。 |
| 中断或失败后按原范围重试 | 使用原频率、目标日和代码范围重新执行，按同一个单次上限计。首次尝试加一次全范围重试，两种周期键各最多查找 `2 × N` 次。按首期满池计算，日线读取量累计最多为周线 140 条或月线 620 条，写入和提交各最多 20 次。重试可能再次处理同一个业务键，先前已提交的记录保留。 |
| 最终验收读回 | 按目标周期键和本次代码范围读回对应 Serving 表，最多 `N` 行。核对日期、来源、行情值及记录数。 |

**隔离耗时实测。** 复用现行表模型、[完整交易日历读取](/Users/congming/github/goldenshare/src/foundation/ingestion/index_month_calendar.py)和 [Ops 对象池读取](/Users/congming/github/goldenshare/src/ops/index_series_active_store_adapter.py)，在[本机临时 PostgreSQL](/Users/congming/github/goldenshare/tests/wealth_watchlist_postgres_support.py) 18.4 上测量。使用原方案的 10 个代码和构造的日线样本，模拟周线期末 2026-08-07、月线期末 2026-07-31。样本周有 5 个开市日，样本月有 23 个开市日。正式 Raw 均为空，每个代码读取日线、按周期唯一键写入并独立提交。在另一个隔离库模拟第 5 个代码提交后停止，读回确认这 5 行，再按原 10 个代码重跑。两种频率重跑后各读回 10 行，周期键、截至日、来源和行情值均符合预期。

| 频率与场景 | 读取日线／提交事务 | 查询（毫秒） | 写入 SQL（毫秒） | 提交（毫秒） | 执行总计（毫秒） | 验收读回（毫秒） |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 周线首次完整执行 | 50／10 | 79.257 | 7.505 | 1.511 | 88.737 | 0.855 |
| 周线按原范围重试 | 50／10 | 7.733 | 5.473 | 1.254 | 14.641 | 0.497 |
| 月线首次完整执行 | 230／10 | 9.146 | 5.546 | 1.229 | 16.285 | 0.747 |
| 月线按原范围重试 | 230／10 | 8.524 | 5.537 | 1.285 | 15.725 | 0.512 |

按表中样本估算，完整执行加一次原范围重试和一次最终读回，周线约 104 毫秒，月线约 33 毫秒。查询时间包括读取激活池、日历和基础信息。执行总计还包括校验、合成和会话开销。这组单次样本用于第二阶段开工前估算数据库链路，TaskRun 排队、运行状态写入及生产环境并发开销在实现后单独核验。

## 7. 已确认需求与验收

| 需求 | 实施位置 | 计划验收 |
| --- | --- | --- |
| R1 期末正式维护只写 Raw，按源范围保存 | §2.1、§3.1、§4.1 | 普通周和周五休市的短周分别在实际末日收盘后触发，并请求该日。验证常规维护和按代码补历史共用期末取数，池外有效正式记录照常入 Raw。单日选择非期末、维护区间截断到周中时不生成该周期的正式请求。期末请求返回非期末行时，任务失败，详情列出代码和日期，该期不写入，先前已提交的期末保留。校验短页、空尾页和源空或部分到达时的保留规则。正式维护只写 Raw。 |
| R2 正式维护失败按原范围重新请求 | §4.1、§6 | 用多个期末的区间让其中一期失败。重试请求覆盖整个原区间及原代码，先前提交的期末保留，重复写入按原业务键更新。Serving 重试只读已落地的 Raw，运行失败不撤销 Raw。 |
| R3 Serving 手动更新与盘后日更 | §3、§4.2、§5 | 数据后台分别配置周、月盘后日更。人工选择频率、日期和需要处理的代码。盘后日更写入预定触发日，验证跨午夜的出队或重试不将它换成新日期或继续写入。过上海时间午夜转人工，历史非期末、未收盘或休市日期不能作为目标。 |
| R4 Serving 先取正式，缺正式才合成 | §2.3、§4.2 | 有正式 Raw 即使缺日线或断档，也覆盖同一根 K 线。中证 A500 9 月 30 日的人工 Raw 行标为 `derived_daily` 时仍走合成口径，6 条日线合成的收盘为 4684.8913 点。以后收到该期正式 Raw 时可覆盖。用北证 50 验证无正式 Raw 和以后有正式 Raw 两种路径。已发布的正式值不会被合成覆盖。 |
| R5 当前周期连续性和单指数失败 | §4.2 | 首个应有日创建，11-09 成功、11-10 缺失、11-11 已有日线时保留 11-09，任务显示预期和实际日期。一次任务内安排多个失败代码，核对后续正常代码照常提交、任务结束时标记失败、保存量等于实际提交行数，数据后台技术诊断可查看全部失败明细。另一频率独立执行。人工先补 10 日再补 11 日，同日重跑不新增 K 线，较早任务不让截至日倒退。 |
| R6 人工补已结束周期 | §4.2 | 选某个过去的周、月期末，有正式 Raw 直接写，无正式 Raw 且日线完整一次补齐。缺日线时保留旧值，在现有任务详情列出缺失日期。 |
| R7 独立激活池、历史起点和切换顺序 | §3、§4.2、§4.3 | 核对周、月线任务使用同一个 `index_period_serving` 池，通用增删入口拒绝修改该池，空池时任务在行情读写前失败并显示诊断。切换时读回核对首期的 10 个代码，两张 Serving 表只删除池外行。核对这 10 个代码的日期范围、记录数和代表性行情值均保持一致，覆盖正式值和北证 50、中证 A500 的合成值。周线历史至 11-06，11-09 起接续；月线历史至 10-30，从 11 月首个开市日起独立接续。日线池回归，二期增删单独验收。 |
| R8 正式与合成单位一致 | §2.2 | 用已知的真实周、月样本核对量、额倍率、4 位小数及涨跌幅。覆盖前后单位一致，正式值保留源值。上证 50 和创业板指的首期正式行前收盘为 0 时，验收 Raw 和 Serving 均按源值保留且正常发布。现有通用行情接口单位回归，财势乾坤后续接入时验收手、千元及百分数展示。 |
| R9 移除旧合成入口 | §5 | 正式维护、现有工作流及旧重试不能绕回旧合成，历史记录可读。池外代码不能进入周、月 Serving，现有日线维护入口仍有效。 |
| R10 长任务和安全切换 | §4.3、§6 | 获准的代表性运行核对源、归一化、拒绝和读回，演练中断后续跑、幂等、取消、进度、状态写入失败和节点终态。切换清理中断后验证续跑只删除剩余池外记录，回退只恢复本次已删除的池外记录并撤销本次激活池变更。 |
| R11 Tushare 卡只展示正式 Raw 的取数状态 | §5.1，Tushare 卡片 API、状态快照与页面 | 周、月各保留一张。以周一盘后为例，Raw 截至上周五且 Serving 已到周一时，Tushare 周线卡仍显示上周五并按正式期末判断。卡片入口发起正式取数，任务详情显示 Raw 取数结果，已有的 Serving 合成行不会计入该任务。 |
| R12 Biz 卡独立展示 Serving 日更与补数 | §5.1，Biz 卡片 API、页面及任务详情 | 周、月各显示一张。10 个指数均到目标日时显示 `10/10`。任务因一个指数未更新而失败时，显示 `9/10` 和失败结果，可进入任务详情查看缺数代码。验证两张卡分别发起对应 Serving 手动更新，且补跑历史任务不改变当前日更覆盖的目标日期。 |
| R13 正式月线在次月触发，提交后更新上月 Serving | §3.1、§4.2、§5.1 | 用 2026 年 10 月验证 11 月首个交易日上海时间 19:00 后触发，取数及其重试均使用 10 月 30 日。正式 Raw 提交后才创建独立的上月 Serving 任务，覆盖同一根 K 线。取数失败或空返回时保留原 Serving。Serving 任务失败后可单独重试，Raw 保持已提交。11 月日更独立运行，目标日和卡片覆盖日期均为 11 月对应交易日。验证 Raw 卡在配置时点前后判断应到期末，人工合成行不计为正式到数。 |
| R14 按代码补历史时集中报告空期 | §4.1 | 用前后有正式数据、中间空返回的三个期末验收。前后两期照常写 Raw，任务详情列出中间缺期的代码和日期，终态为部分成功。全部缺期时标记失败。另用返回非期末日期的样本验证该期不入库并报任务失败。 |
| R15 同一期取完并校验后提交 | §4.1、§6 | 验证多页的期末在末页取完和整批校验前均无 Raw 写入，校验通过后整期提交一次。让后页取数失败或返回错误日期，核对本期没有写入、前一期已提交的数据保留。另在分批写入时注入失败，核对当前期末所有写入一并回滚。 |
| R16 单期超限退出 | §6.1、§8.1 | 用 §8.1 两个期末验收默认预算内的完整取数、提交和读回。构造超过样本 16 页的数据，验证预算内仍取至末页。用受控的内存采样、时钟和数据库延迟分别触发上限，覆盖分页等待、整批校验和已写入部分批次的情形。核对任务及当前节点进入失败终态、本期未提交、此前各期保留，重试沿用原范围。 |

现有测试入口包括[正式周期线 Raw 数据库测试](/Users/congming/github/goldenshare/tests/test_index_period_raw.py)、[Serving 数据库测试](/Users/congming/github/goldenshare/tests/test_index_period_serving.py)、[分层写入测试](/Users/congming/github/goldenshare/tests/test_dataset_writer_index_layer_alignment.py)、[日期规划测试](/Users/congming/github/goldenshare/tests/test_index_monthly_calendar.py)、[动作目录测试](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)、[自动任务 API 测试](/Users/congming/github/goldenshare/tests/web/test_ops_schedule_api.py)和[任务 API 测试](/Users/congming/github/goldenshare/tests/web/test_ops_task_run_api.py)。卡片沿用[卡片 API 测试](/Users/congming/github/goldenshare/tests/web/test_ops_dataset_cards_api.py)和[数据源页面测试](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-source-page.test.tsx)，实施后在浏览器核对两个列表及维护入口。旧行为的用例随旧入口撤除而更新。源字段和计算预期须采用独立的真实依据。以上均为验收计划。

## 8. 开工与正式执行前的核验

### 8.1 核验结论与实施前事项

**合成输入缺值。** 六个首期、69 条源日线均有有效前收盘及 OHLC、量额。发现的四条零前收盘记录来自正式周、月线，沿用原值发布。对合成输入实际缺失所需字段或首日前收盘不可用的情况，建议沿用现有月线合成对不完整窗口的处理，保留上一根有效结果，在任务详情列出代码、交易日和字段，不用零值代填。样本未出现这种合成输入，验收用反例验证。 [现有月线合成完整性检查](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)

**取数和资源核验。** 2026-11-11 复取 §2.1 中已知返回较多的两个期末，均请求全部指数。用项目分页及可取消的 Tushare 客户端取齐单期，统一校验后用现有 Raw 写入器和正式表模型写入临时 PostgreSQL 18.4，按期提交。单页连接器测试沿用现有有界调用能力，测试边界不作为新任务的生产配置。用独立 Tushare MCP 点查核对上证指数代表性值，逐键比较源响应与提交后读回的 11 个业务字段，并核对来源。

| 期末 | 页数／源行数／已写并读回行数 | 取数／校验／写入及提交（秒） | 取数至提交／读回（秒） | 任务进程及连接器子进程的合计 RSS 采样峰值／数据库连接进程采样峰值（MiB） |
| --- | --- | --- | --- | --- |
| 指数周线 `2026-08-07` | 16／15,404／15,404 | 15.935／0.106／1.616 | 17.657／0.209 | 292.95／46.00 |
| 指数月线 `2026-07-31` | 16／15,277／15,277 | 17.171／0.104／1.680 | 18.954／0.208 | 291.31／40.41 |

两期归一化行数均与源端一致，拒绝和去重均为零。对相同源批次重放写入，记录数不变。在末尾行注入错误日期，校验拒绝该期。在第二个数据库写入批次注入失败，读回确认第一个写入批次已回滚。现有日期规划、分层写入、动作目录和隔离 PostgreSQL 回归共 64 项通过。以上为开发前的取数、校验和提交证据。第一阶段实际任务进度验收见 §9.1。正式月线自动触发 Serving 按 §9.3 实施和验收。RSS 是约每 50 毫秒采样的进程驻留内存，进程合计可能重复计入共享内存。数据库连接进程单独计，测试结果为样本测量。

同日只读核对 Prod 通用 Worker，服务未设置 `MemoryHigh` 或 `MemoryMax`，观测时内存占用约 541 MiB、服务记录的峰值约 1,183 MiB，主机可用内存约 9.69 GiB。该时点的资源可以容纳已测样本。§6.1 规定了单期的执行上限和退出方式，实施后按 R16 验证。原区间重试和读回的工作量按 §6 核算。

### 8.2 正式执行前

历史覆盖及周、月截止日已按 §4.3.3 验收。正式切换前，按 §4.3 核对 10 个保留代码、待清理范围和备份，按 §6 验证切换预算、写入隔离和回退，并完成代表性最小真实验收。排程应已在隔离环境验证，包括预览触发时刻和 TaskRun 保存的目标日。

现有调度器会在入队前重新校验已保存的日期策略。因此，旧周、月线配置的暂停要在新规则生效前完成。按以下顺序使用数据后台的现有排程和任务入口。

1. 暂停旧的指数周、月线 Raw 排程。切换窗口内暂停提交可能写入两张 Serving 表的任务及重试，范围包括「指数K线全链路维护」工作流的旧写入。检查已入队和在途的相关任务，让它们结束，或通过现有入口取消。确认相关任务已进入终态，再切换到新规则。
2. 在相关排程保持暂停时保存 §3.1 的新策略与时刻，将 `next_run_at` 一并保存为空。现有恢复入口有值时会沿用该字段，清空后才会按新策略重算。在数据后台预览下次触发时刻，并按 §4.3 完成激活池初始化、Serving 清理和读回验收。
3. 清理验收通过后恢复正式周、月线 Raw 排程，核对后台显示的下一次运行时间。上月 Serving 更新随新月线 Raw 排程生效，由 Raw 成功收尾自动触发。管理员单独配置并启用周、月线 Serving 日更。

## 9. 分阶段开发与验收

依照原方案第 9 节的顺序实施。阶段验收记录对应的 §7 需求、代码改动、测试和实际核验结果。涉及多个阶段的需求在各阶段验收对应部分，完整链路在第 4 阶段验收。

### 9.1 阶段 1 · 正式周、月线 Raw 取数

- 单期预算由指数周、月线共同使用的 `DatasetDefinition.planning.index_period_raw_policy` 声明，默认值按 §6.1，随代码生效。数据集规划、正式取数执行器和 TaskRun 观测适配读取该策略。取消检查间隔 2 秒、进度更新间隔 5 秒、观测 SQL 限时 2 秒沿用复权周线执行合同的现行值。预算触发原因、期末和当前阶段进入任务详情。 [现行观测预算依据](/Users/congming/github/goldenshare/src/foundation/datasets/stock_weekly_adj_contracts.py)
- 按 §5 的 DatasetDefinition、计划与请求、正式 Raw 写入改造现有维护主链。日期规划校验实际期末，取数后执行整期校验和 Raw 写入。取消、进度和终态接入现有 TaskRun。消费这些定义的排程和页面按第 3、4 阶段联调。
- 以一个频率、一个期末和当次代码筛选为单元。读 Tushare，业务写入限对应 Raw 表。采用 §6、§6.1 的分页和资源预算。错日期、超限、取消或写入失败按 §4.1 处理。重试按整个原范围计算取数、写入开销，验收按同一范围对照源行数、归一化结果、拒绝原因和提交后的读回结果。
- 验收 R1 的日期规划与 Raw 写入、R2 的 Raw 重试、R10 的 Raw 取消与任务状态，以及 R14 至 R16。覆盖短周的真实期末、周中截断、空尾页、区间中间空期、分批写入失败回滚及提交后状态写入失败。沿用 §8.1 的两个真实期末做最小写入和读回验证。

#### 阶段 1 开发与验收记录

| 对照项 | 实现及验证结果 |
| --- | --- |
| R1、R14 日期与源范围 | 正式维护按完整日历确定期末。短周以 2026-09-30 为期末，周中截断的范围不发起该周请求。用区间中间空一期、全部空、单期空和后页错日期覆盖任务终态及缺期明细。空返回保留已有 Raw。正式取数按源范围保存，包括未纳入 Serving 的代码。 [日期规划](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py) · [日期测试](/Users/congming/github/goldenshare/tests/test_index_monthly_calendar.py) |
| R2、R10 重试与观测 | 注入进程退出、业务批次间取消和提交后状态写入失败，读回此前已提交的 Raw。用后台原任务重试验证完整范围和代码均沿用原意图。中断任务沿用现有任务状态修正入口，修正后任务和当前节点均为失败。浏览器验证任务详情显示期末、当前阶段、完成量、总量、百分比和最后更新时间。 [任务执行](/Users/congming/github/goldenshare/src/ops/runtime/task_run_dispatcher.py) · [隔离测试](/Users/congming/github/goldenshare/tests/test_index_period_raw.py) |
| R15、R16 写入与上限 | 验证空尾页、后页取数失败、重复页、17 页正常返回、内存触限、等待超时、后续写入批次失败及 SQL 超时。故障期未提交，已提交期保留。模拟提交回执丢失，按 Raw 读回确认已提交和未提交两种结果。 [Raw 执行](/Users/congming/github/goldenshare/src/foundation/ingestion/index_period_raw.py) · [隔离测试](/Users/congming/github/goldenshare/tests/test_index_period_raw.py) |
| 真实源与隔离读回 | 通过 Ops Worker 运行正式维护。2026-08-07 周线 16 页、15,404 行，20.27 秒。2026-07-31 月线 16 页、15,277 行，19.98 秒。两期均使用临时 PostgreSQL，源端、归一化、任务写入和读回行数一致，拒绝为 0，逐键比对 11 个源业务字段及 Raw 来源。上证指数收盘分别为 3940.0371 和 3832.2624 点，均与 §2.1 的独立点查一致。 |

第一阶段实现与验收使用现有维护动作、Worker 和任务详情。独立 Serving 更新、排程调整和数据集卡片按 §9.2 至 §9.4 依次实施。

### 9.2 阶段 2 · 独立 Serving 更新

- 按 §4.2 和 §5 实现周、月线独立手动动作、共同更新逻辑和 Worker 执行入口。通过现有对象池 DAO 读取周、月线激活池。按周期键优先读取正式周、月线 Raw，缺正式值时读取指数 Raw 日线合成，业务写入限对应 Serving 表。
- 每频率最多处理 10 个池内代码，每个代码独立提交。缺日线和连续性失败按 §4.2 处理。正常执行、按原频率、目标日和代码范围重试，以及验收读回的预算见 §6.2。Prod 激活池初始化按 §4.3 的切换顺序执行。
- 验收 R2 的 Serving 重试、R3 的手动入口、R4 至 R8 中的更新和池范围行为。覆盖正式值覆盖、日线合成、历史期末补数、缺失代码后其余代码继续写入、旧任务重跑不倒退，以及正式值和合成值的单位一致性。用北证 50 和中证 A500 的已有样本核对来源处理。

#### 阶段 2 开发与验收记录

| 对照项 | 实现及验证 |
| --- | --- |
| R3 手动入口、R7 激活池 | `maintenance.update_index_weekly_serving` 和 `maintenance.update_index_monthly_serving` 均接入现有手动任务入口，使用单日交易日控件和可选指数代码。两项动作共用 `index_period_serving` 池，通用增删入口拒绝修改该池。隔离测试覆盖空池、池外代码、10 个代码整池执行、未收盘、休市、日历不全和历史非期末。 [动作目录](/Users/congming/github/goldenshare/src/ops/action_catalog.py) · [执行器](/Users/congming/github/goldenshare/src/ops/runtime/index_period_serving_executor.py) |
| R4 至 R6 数据与写入 | 按交易日历取周期键，正式值直接写入，合成读取指数 Raw 日线。校验短周、发布首期、历史期末补做、缺日线和当前周期连续性。用两个失败代码和后续成功代码核对批末诊断及实际保存量。并发写入验证正式值和更晚合成值均保留。 [Serving 读写](/Users/congming/github/goldenshare/src/foundation/ingestion/index_period_serving.py) · [任务汇总](/Users/congming/github/goldenshare/src/ops/runtime/task_run_dispatcher.py) |
| R2 重试及任务状态 | 隔离测试在首个代码提交后取消或退出进程，读回已提交记录，再用数据后台原任务重试入口按原参数重跑。核对任务与当前节点终态、保存量，以及进度写入失败时业务提交保留。 [隔离测试](/Users/congming/github/goldenshare/tests/test_index_period_serving.py) |

**真实样本读回。** 从 Tushare 按 §2.2 的日期范围复查 14 条指数日线、1 条正式指数周线及对应交易日历，将样本写入隔离库 Raw。使用真实项目手动入口、Worker、临时 PostgreSQL 和通用行情读取查询，三个样本均保存并读回 1 行。逐项核对 OHLC、前收盘、涨跌点、涨跌幅、成交量和成交额。

| 指数及目标日 | 输入与写入来源 | 收盘（点） | 成交量（股） | 成交额（元） |
| --- | --- | ---: | ---: | ---: |
| 北证 50 2022-11-30 | 8 条发布后日线，`derived_daily` | 1018.8664 | 529282705.0000 | 5969741109.0000 |
| 中证 A500 2024-09-30 | 6 条发布后日线，`derived_daily`。保留 Raw 的人工合成来源标识。 | 4684.8913 | 214270809200.0000 | 3093258895936.0000 |
| 上证 50 2004-01-02 | 1 条正式周线，`api`。源前收盘及涨跌幅均为 0，读回仍为 0。 | 1011.3470 | 806465200.0000 | 5742758967.0000 |

按 §6.2 的 10 个代码在隔离库用构造行情运行完整手动任务。周线读取 50 条日线，创建任务至 Worker 终态 52.748 毫秒，读回 10 行用时 0.406 毫秒。月线读取 230 条日线，对应耗时 39.423 毫秒和 0.455 毫秒，两项各保存 10 行。该单次样本包含本地任务状态写入，不含实际排队和生产并发。

独立复核确认数据后台按现有结构显示正在处理的指数、交易日和已提交进度。后端回归 426 项通过，覆盖第一阶段 Raw、维护动作和任务详情接口。

本阶段验收范围为独立 Serving 执行和手动入口。自动调度与旧入口退出见 §9.3，数据卡片和正式切换按后续阶段实施。

### 9.3 阶段 3 · 自动调度和旧入口退出

- 按 §3.1 和 §5 实现正式 Raw 排程与 Serving 盘后日更，复用现有自动任务配置、预览和 TaskRun 创建方式。正式月线提交 Raw 后，用原期末日创建独立的月线 Serving 任务。移除旧写入分支、维护动作、发布器及工作流引用。数据集卡片和生产切换分别按 §9.4 和 §8.2 执行。
- 调度只读取计算下一次触发时间和目标日所需的交易日历窗口，预览不取源数据、不写行情。每次正式 Raw 自动取数只处理一个期末，按 §6.1 计入请求、写入、原期末重试和读回。正式月线自动取数成功后增加一条月线 Serving 任务，按 §6.2 单独计入最多 10 个代码的读取和写入、一次同范围重试及最多 10 行验收读回。当晚的月线 Serving 日更另计一次 §6.2 的预算。验收按对应自动任务及 TaskRun 主键读回配置、目标日、保存量和任务终态。
- 验收 R1、R3、R9 和 R13。在隔离环境验证普通周和周五休市的短周，月初休市后首个交易日触发的月线使用上月期末，两项盘后日更跳过休市日。对照后台预览和实际生成的四项任务，核对日期、时区和执行时刻。验证合法时刻可保存，拒绝早于表中约定的时刻、错误时区、手填目标日或代码。验证旧排程暂停、清空旧下次运行时间、按新策略恢复，并回归其他排程和保留的「指数K线全链路维护」工作流。
- 用月线 Raw 正常提交、空返回、失败及重试验证上月 Serving 的触发条件。让 Serving 入队失败一次，确认 Raw 已提交、原任务显示收尾错误，按原任务重试后正常入队。再用 Serving 写入失败验证其可单独重试。用同日重试和跨午夜的出队、重试验证日更截止，以及手动按原目标日补数。

#### 移除未使用的指数扩展数据维护工作流

- 目标与范围：管理员确认该工作流未使用，删除 [动作目录](/Users/congming/github/goldenshare/src/ops/action_catalog.py) 中的完整定义。当前 [目录查询](/Users/congming/github/goldenshare/src/ops/queries/catalog_query_service.py) 和 [手动任务查询](/Users/congming/github/goldenshare/src/ops/queries/manual_action_query_service.py) 均遍历工作流注册表；[手动任务页面](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-manual-tab.tsx) 读取后者生成入口，因此无需另改前端、API 路由或执行器。
- 保留与禁止项：保留五个数据集的单独维护动作、「指数K线全链路维护」及其日期区间语义。清理工作流目录和自动任务能力方案中将已移除工作流作为现行能力的引用。不删除业务表、对象池、排程或历史任务，不执行生产操作，不新增配置、兼容逻辑或替代工作流。
- 失败、中断、重试与性能：删除注册后，现有服务按未知工作流拒绝手动新建和重试；若有历史任务，其详情仍能读取。复用现有目录校验，不修改任务执行或业务事务。此次修改不新增取数、计算和写入，正常执行、中断后重试及验收均不增加生产数据读取或源请求。验收使用本地定义和隔离测试会话。
- 验收：注册表、目录接口和手动列表不再包含该工作流，直接提交旧入口失败；隔离构造的历史任务仍可查看，重试被拒绝且不新增任务。五个数据集的单独维护动作和保留工作流仍存在，日期区间无周、月期末时不请求源端、工作流正常完成。同步清理旧测试分支，运行对应目录、手动 API、任务查询重试和工作流回归，以及文档完整性检查。

本次移除已完成。使用 CodeGraph 的 `codegraph_explore`、`codegraph_impact` 核对注册表、目录、手动入口和执行链路，并核对前端读取接口的代码，未改变子系统依赖。目录、自动任务能力、手动 API、任务详情及运行时回归共 156 项通过；独立临时 PostgreSQL 的无期末区间回归 1 项通过，其他数据集取数使用替身，不请求 Tushare。文档完整性检查通过。未执行生产操作。

#### 阶段 3 开发与验收记录

| 对照项 | 实现及验证 |
| --- | --- |
| R1、R3 排程与目标日期 | 数据后台读取动作声明。预览、下次运行时间和入队共同使用完整交易日历。隔离 API 验证四项配置、跨日入队仍使用原计划目标、手填日期或代码被拒绝、旧月线排程暂停后按新规则恢复。Tushare 的 SSE 日历显示 2026-05-01 休市，指数周线按 2026-04-30 查询返回上证指数正式记录，收盘为 4112.1593 点。 [排程计算](/Users/congming/github/goldenshare/src/ops/services/index_period_schedule.py) · [排程回归](/Users/congming/github/goldenshare/tests/web/test_index_period_schedule.py) |
| R3 午夜截止 | 用临时 PostgreSQL 验证同晚重试能成功。跨午夜时已保存的指数保留，剩余指数停止写入，任务与当前节点均失败。已过期的出队和重试都保留原目标日，手动补数仍能更新该日。 [Serving 回归](/Users/congming/github/goldenshare/tests/test_index_period_serving.py) |
| R13 上月正式月线覆盖 | 模拟 2026-11-02 19:00 触发，TaskRun 及源请求均指向 2026-10-30。用 Tushare 返回的上证指数正式月线样本，在临时 PostgreSQL 完成排程入队、Raw 写入和 Serving 读回。两层各有一行，Serving 保留期末日期及收盘 3599.0166 点。用另一会话确认 Raw 已提交时原任务和当前节点仍在运行，独立 Serving 任务尚不可见。注入 Serving 入队失败后原任务按原期末重新请求，注入 Serving 写入失败后单独重试且不再次请求 Tushare。空返回、人工月线和自动周线均不创建上月 Serving 任务。 [Worker 收尾](/Users/congming/github/goldenshare/src/ops/runtime/worker.py) · [隔离数据库回归](/Users/congming/github/goldenshare/tests/test_index_period_raw.py) |
| R9 旧入口退出 | 已删除旧写入分支、维护动作、工作流合成末步，以及通用发布器的周、月线 builder 和目标映射。验证历史任务可查看，重试被拒绝。「指数K线全链路维护」的周、月线区间无期末时均零次取数，并继续后续步骤。未使用的「指数扩展数据维护」按本节另行移除，不再保留其日期与月份输入冲突作为现行工作流问题。 [动作目录](/Users/congming/github/goldenshare/src/ops/action_catalog.py) · [工作流回归](/Users/congming/github/goldenshare/tests/test_index_period_raw.py) |

用浏览器核对指数月线自动任务的固定日期规则、执行时刻、预览和保存请求。配置请求携带排程策略，目标交易日由后端生成。 [后台浏览器验收](/Users/congming/github/goldenshare/frontend/e2e/index-period-schedule.spec.ts)

### 9.4 阶段 4 · 数据后台与联调验收

- 按 §5.1 更新 Tushare 卡片、Biz Serving 卡片、任务详情和状态快照。正式 Raw 状态按应到期末和正式来源判断，Serving 覆盖按目标交易日查询对应周期和池内代码。任务状态和快照写入按 §6 与业务事务隔离。
- 联调使用 §8.1 的代表性真实期末和隔离数据库。正常运行、取消后按原范围重试和提交后读回分别按 §6 核算。卡片核验聚焦对应频率、期末和池内代码，切换清理与回退演练按 §4.3 的范围在隔离环境进行。
- 验收 R10 的完整链路、R11、R12 和 R13 的卡片表现。验证两组卡片的目标日期和状态、`9/10` 时的失败详情、历史补跑对当前覆盖的影响，以及状态写入失败、取消重试和切换回退。

### 生产切换

四个开发阶段验收通过后，按 §4.3、§8.2 单独执行获准的生产切换。备份、清理、续跑和验收读回的开销按 §6 核算，按 R7、R10 验收生产数据范围和启用顺序。
