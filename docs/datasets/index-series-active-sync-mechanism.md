# Prod 指数日线现行机制与周、月线重建及更新方案

更新时间为 2026-11-10。第 1 节记录指数日线现行机制。第 2 节起记录已确认的 Prod 指数周、月线方案，实施设计与验收见 [LLD](/Users/congming/github/goldenshare/docs/datasets/prod-index-period-low-level-design-v1.md)。

<a id="index-daily"></a>

## 1. 指数日线现行机制

`index_daily` 从 Tushare 取数，写入 `raw_tushare.index_daily`，符合日线服务范围的结果进入 `core_serving.index_daily_serving`。`ops.index_series_active` 按 `resource` 区分两个日线池。

| 日线对象池 | 职责 |
| --- | --- |
| `index_daily_raw` | 默认按池内指数代码和日期窗口向 Tushare 请求。显式指定指数代码时，按指定代码请求。 |
| `index_daily` | 筛选可以写入日线服务表的指数。显式指定代码仍受这个池约束。 |

本次改造的边界是指数周线和月线。指数日线的两个池、请求、入库、完整性审计和补漏继续执行[现行日线机制](/Users/congming/github/goldenshare/docs/ops/ops-index-daily-completeness-reconciliation-plan-v2.md)。实际表和执行入口以 [DatasetDefinition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/index_series.py)、[执行规划](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)和[写入器](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)为准。

<a id="index-period-rebuild"></a>

## 2. 两条独立的更新流程

| 更新流程 | 触发方式 | 写入范围 |
| --- | --- | --- |
| Tushare 正式周、月线取数 | 沿用现有指数周线、月线维护入口，分别按周、按月在最后一个交易日收盘后取数。源延迟时，运营人工按原期末日期补拉。 | 只写对应的周、月线 Raw。期末按源返回范围取全，不用 Serving 的 10 个代码过滤。 |
| 指数周、月线 Serving 更新 | 数据后台单独提供手动任务和自动任务，使用同一套更新逻辑。管理员配置每个交易日盘后的自动任务。手动任务选择周线或月线、目标日和所需的池内代码。目标日可为当前自然周期内已收盘的交易日，或过去周期的最后一个交易日。 | 只写对应的 Serving 表，只处理激活池内的指数。 |

| 数据集 | Tushare 接口 | Prod Raw 表 | Prod Serving 表 |
| --- | --- | --- | --- |
| 指数周线 `index_weekly` | [doc 171](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0171_指数周线行情.md) | `raw_tushare.index_weekly_bar` | `core_serving.index_weekly_serving` |
| 指数月线 `index_monthly` | [doc 172](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0172_指数月线行情.md) | `raw_tushare.index_monthly_bar` | `core_serving.index_monthly_serving` |

正式数据只按周、按月提供。2026-11-09 实查，上证指数在这两个接口按当日查询均无返回，最新正式周线和月线分别截至 11 月 6 日和 10 月 30 日。最后一个交易日按完整交易日历确定，例如周五休市时用当周实际最后开市日。 [Tushare 更新说明](https://tushare.pro/document/1?doc_id=108)

Raw 只保存 Tushare 返回的正式行情，按源端业务键保存和更新。源延迟或正式取数失败时，在现有任务详情记录受影响的频率、期末日期、已知缺失代码和失败阶段。重试按原范围重新请求 Tushare 并写 Raw，保留已有有效记录。补到正式 Raw 后，运营可指定原期末日执行 Serving 更新。

## 3. 首次历史补齐与切换

1. 首次历史补齐限定为激活池的 10 个指数。按核实的指数发布日期开始，包括适用的 2020 年前历史。周、月分别确定截止日，取各自已结束周期的最后一个交易日。对这 10 个指数下载 Tushare 有供数的正式周、月线并写 Raw。其他指数的历史暂缓补齐，常规期末取数范围仍按第 2 节。 [指数基础信息 doc 94](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0094_指数基本信息.md)
2. 在获准的切换窗口内隔离两张 Serving 表的旧写入。先清空两张表，再对这 10 个指数按周期生成并写入新 Serving。每个周期先读正式周、月线 Raw，缺正式行时从完整的指数 Raw 日线合成。实际缺失所需日线时，在任务详情列出缺口，再按具体情况决定如何补数。切换范围和回退安排见 LLD。
3. 周线以 2026-11-06 为历史截止日，从 11 月 9 日起逐日接上。若 11 月 10 日才完成重建，先人工指定 9 日生成周线，10 日收盘后再更新同一根。月线按自己的历史截止日接上，从当前月首个应有交易日起逐日执行。每次合成都按第 5 节检查连续性。

## 4. 周、月线独立激活池

周、月线共用一个独立于日线的激活池。首期取财势乾坤「主要指数」的 10 个代码，用于限定首次历史补齐和 Serving 范围。 [财势乾坤主要指数配置](/Users/congming/github/goldenshare/src/biz/services/wealth/config/definitions/major_indices.cn_a.v1.json)

`000001.SH`、`399001.SZ`、`399006.SZ`、`000688.SH`、`000300.SH`、`000905.SH`、`000852.SH`、`899050.BJ`、`000510.SH`、`000016.SH`。

首期在切换时初始化名单，日常入口不开放增删。**二期必须提供周、月线激活池的独立增删能力。** 新增代码时处理从发布日期起的历史，移除代码时处理该代码在两张 Serving 表中的记录。指数日线继续使用第 1 节的两个池。

<a id="index-period-daily-update"></a>

## 5. Serving 更新顺序

同一指数的周 K 或月 K，在对应的 Serving 表里用 `(ts_code, period_start_date)` 定位。自然周从周一开始，自然月从 1 日开始，`period_start_date` 取该自然周期第一个开市日。例如周一休市、周二开市，这一周都用周二作为周期标识。合成的 `trade_date` 为实际算到的交易日，正式记录保留源端的期末日期。上一交易日和期末日由交易日历确定，无需增加 `end_date`。

每个池内指数、每个周期都按同一顺序处理。

1. **有当期正式 Raw。** 按正式原值补建或覆盖同一根 Serving K 线，无需检查日线完整性和上一交易日。正式值写入后，日线合成不能覆盖。
2. **无当期正式 Raw。** 用 `raw_tushare.index_daily` 合成。当前周期从该指数首个应有交易日算到目标日，首日创建，之后要求 Serving 的 `trade_date` 等于上一交易日。同一日期重试按同一根 K 线处理。跨入下一自然周期后，人工选择过去周期的最后一个交易日，按完整周期一次合成，检查整期应有日线，无需逐日回放。计算从指数发布日期起纳入。
3. **合成所需日线缺失或连续性检查失败。** 保留原 K 线和 `trade_date`，该指数报错。通过检查的指数继续写入，出现错误的频率任务最终标记失败。周、月分别执行和判断。任务详情显示频率、代码、目标交易日、失败阶段、缺失交易日，或连续性检查的预期和实际截至日。

例如 11 月 9 日更新成功，10 日日线缺失时保留 9 日的记录。11 日日线即使已到，上一交易日检查仍会失败。运营补齐 10 日日线后，先手动指定 10 日，再执行 11 日。首期以这 10 个指数的日线 Raw 在上海时间 22:00 前就绪为排程假设，自动任务由管理员配置，过目标交易日的上海时间午夜仍未完成则转人工。

北证 50（`899050.BJ`）适用相同顺序。正式 Raw 缺失时，日更和历史都由日线合成。以后 Raw 有当期正式记录时，执行 Serving 任务即可覆盖。

## 6. 数据单位与财势乾坤读取

Prod 周、月线 Raw 和 Serving 沿用正式源的数值口径。成交量为股，成交额为元，涨跌幅为比例，涨 1% 存为 `0.0100`。正式数据以源值入库。日线 Raw 的成交量按手、成交额按千元，合成时分别将合计乘 `100` 和 `1,000`，仅写 Serving。

财势乾坤接入指数周、月线时，在自己的读取入口将成交量除以 `100` 得到手、成交额除以 `1,000` 得到千元，涨跌幅按百分数展示。现有通用行情接口继续沿用 Prod 单位。页面、技术指标接入和 DG 属于后续工作。本次单位的实测依据见 LLD §2.2。

<a id="index-period-legacy-cleanup"></a>

## 7. 旧入口清理与实施边界

实施时移除周、月线取数写入器在源为空或部分代码未到时触发的旧日线合成，移除旧的独立维护动作、对应执行代码及工作流中的合成末步。核对动作、调度、重试、工作流及服务表发布引用，Serving 只由本方案的独立任务与首次重建流程更新。指数日线继续走现行链路。

历史补齐和首次重建按 Prod 长任务要求设计，处理单元、分页、进度、取消、续跑与回退见 LLD。方案确认、开发、最小真实验收和正式切换分阶段执行。
