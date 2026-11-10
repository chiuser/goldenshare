# Prod 指数周线和月线低层设计 v1

状态为业务口径已确认，实施前核验待完成。业务范围和规则见[原方案](/Users/congming/github/goldenshare/docs/datasets/index-series-active-sync-mechanism.md)。本文按[数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)细化两个已有数据集，拟改设计与现行实现分开记录。

## 1. 任务与数据范围

| 任务 | 输入和触发 | 读写边界 |
| --- | --- | --- |
| 指数周线、月线正式维护 | 保留 `index_weekly.maintain` 和 `index_monthly.maintain`。常规取数每周、每月各一次，使用该周期最后开市日。源延迟或失败时人工按原范围重新请求。 | 请求 Tushare，写对应 Raw。常规期末取数以源返回范围为准。 |
| 指数周线、月线 Serving 更新 | 数据后台提供独立的手动任务和自动任务。每个任务指定频率和一个目标交易日。运营手动更新时可指定池内代码，自动任务由管理员配置，在每个交易日盘后分别触发。 | 只处理周、月线激活池内代码。优先读当期周、月线 Raw，需要合成时才读指数 Raw 日线，只写对应 Serving。 |
| 首次历史补齐与重建 | 按两个历史截止日和每个指数的发布日期处理池内 10 个代码。 | 正式历史先补进 Raw，随后清空两张 Serving，再逐周期生成并写入。 |

| 数据集 | Tushare 接口 | Prod Raw | Prod Serving |
| --- | --- | --- | --- |
| 指数周线 `index_weekly` | [Tushare doc 171](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0171_指数周线行情.md) | `raw_tushare.index_weekly_bar` | `core_serving.index_weekly_serving` |
| 指数月线 `index_monthly` | [Tushare doc 172](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0172_指数月线行情.md) | `raw_tushare.index_monthly_bar` | `core_serving.index_monthly_serving` |

合成输入为 `raw_tushare.index_daily`、交易日历、指数发布日期及按需读取的当前 Serving 记录。指数日线的池、任务和服务表沿用现行机制。DG、股票周月线和财势乾坤图表及指标接入属于其他阶段。§2.2 仅约定财势乾坤后续读取所需的单位转换。

## 2. 源接口、字段和日期合同

### 2.1 源行为证据和待验项

| 请求形态 | 用途与已有证据 | 开工前核验 |
| --- | --- | --- |
| 按 `trade_date` 取全范围 | 常规期末取数。前序指定日期探测取得 2026-08-07 周线 15,404 条、2026-07-31 月线 15,277 条，各按 1,000 条分页、各 16 页。行数和页数是两个期末样本。 | 用项目现有 connector 验证后续页、短页、空尾页、重复页与超限诊断。 |
| `ts_code + trade_date` | 人工补某代码的正式期末数据。前序上证指数在上述两期各返回对应记录。 | 核对正式字段、正常空结果和请求失败。 |
| `ts_code + start_date/end_date` | 池内 10 个指数从各自发布日期下载正式历史的候选方式。前序按沪深 300 的发布日期 2005-04-08 查询短窗，取得该日周线和 2005-04-29 月线。 | 核对端点、节假日、跨年、发布日期和分页。用有界逐期点查验证区间返回的键和值。 |
| 无业务参数、仅传代码 | 核验源默认范围及对象过滤的语义。历史下载实际使用有上界的范围。 | 在获准的最小范围内验证。未经验证的返回上限不能当作全集。 |
| 未结束的当前周、月 | 2026-11-09 查询上证指数，两接口均无该日记录，前一正式周期可返回。 | 核对期末实际出数情况，安排原周期的常规取数及人工补拉。 |

`DatasetDefinition` 继续维护现有源字段。现行 [request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py) 将计划映射为 `trade_date` 和可选的 `ts_code`，分页参数由 source client 生成。按代码的历史区间取数先验证，再确定是否使用。源接口的可选参数不直接变为运营输入。验证默认字段、Definition 的显式 11 列以及身份和日期字段，记录真实请求参数、页数、行数和空结果。MCP 单页结果不作为分页证据。

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

Raw 的正式行情业务值沿用源返回值。源日期字符串按现有映射转为 `DATE`，`api_name`、`fetched_at`、`raw_payload` 是 Raw 本地辅助字段。Serving 用本地 `period_start_date` 定位周期，`source=api` 代表正式值，`source=derived_daily` 代表合成值。两类值共享同一字段类型与精度，数值字段保留表定义的 4 位小数。前收盘为零或缺失时无法按公式计算涨跌幅，开工前用真实样本核实该情况及其他字段缺值的处理。 [Raw 日线字段](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_index_daily.py) · [现有合成公式](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py)

**单位实测。** 2026-11-10 对照 Prod Raw 的 10 个代码、截至 2026-11-06 的一周和截至 2026-10-30 的一月，分别有 5、17 个应有交易日，池内日线均齐。查到的 18 条正式周、月线，其成交量与日线合计之比均为 `100.0000`，成交额之比均为 `1000.0000`，正式涨跌幅与 `round(close / pre_close - 1, 4)` 一致。正式周、月线的实测量额是股、元。两个期末均未查到北证 50 正式 Raw，按 §4 的同一规则处理。 [Tushare 日线字段说明](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0095_指数日线行情.md)

**财势乾坤读取。** 周、月线后续接入时，在财势乾坤读取入口一次性将成交量除以 `100`、成交额除以 `1,000`，与日线行情接口的手、千元对齐。界面需要百分数时，把比例乘 `100` 后加百分号。通用行情 API 继续直读 Serving 的股、元及涨跌幅比例。 [现有通用行情读取](/Users/congming/github/goldenshare/src/biz/queries/quote_query_service.py) · [财势乾坤日线行情字段映射](/Users/congming/github/goldenshare/src/biz/services/wealth/market/index_detail/index_detail_field_mapper.py)

### 2.3 日期、业务键和时效

- **周期标识。** 按完整交易日历取所属自然周或自然月的首个开市日作为 `period_start_date`。自然周从周一开始，自然月从 1 日开始。周一休市、周二开市时，该周每天使用周二作为周期标识。指数发布日期决定该代码在当期从哪个交易日开始计算，不改变周期标识。
- **数据截至日。** 合成行的 `trade_date` 为计算截至的交易日，正式行保留源返回的期末交易日。入库时间用现有时间戳。日历提供上一交易日和真实期末，日历未齐时不能推定休市。周五休市则取该周实际最后一个开市日。
- **记录身份。** Raw 按 `(ts_code, trade_date)` 写入。对应 Serving 表按 `(ts_code, period_start_date)` 的现有唯一约束更新同一根 K 线，保留现有主键。无需增加 `end_date`。请求中的 `start_date/end_date` 仅表示取数范围。 [周线模型](/Users/congming/github/goldenshare/src/foundation/models/core_serving/index_weekly_serving.py) · [月线模型](/Users/congming/github/goldenshare/src/foundation/models/core_serving/index_monthly_serving.py)
- **输入和执行。** 正式维护沿用点、区间输入，计划只展开范围内真实的期末交易日。Serving 单次选择一个目标交易日，执行日所属的自然周、月分别是当前周期，接受该周期内已收盘的目标交易日。跨入下一自然周期后，人工补过去的周期只接受其最后交易日。
- **完整性和时效。** 正式 Raw 按已结束周期和源实际返回记录检查，期中没有正式数据是正常情况。Serving 时效看各代码实际 `trade_date`。缺数和失败沿现有任务详情查看。 [日期模型指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md#period-anchors)

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
| 周、月线激活池 | 拟复用 `ops.index_series_active` 的独立资源值及 [对象池 DAO](/Users/congming/github/goldenshare/src/foundation/dao/index_series_active_dao.py)。 | 切换时初始化。历史补齐、重建和 Serving 更新读取该池。常规期末取数不使用该池裁剪源数据，日线两池保持现状。 |
| 指数发布日期 | 使用已核实的指数基础信息 `list_date`，与池内 `first_seen_date` 分开。 | 控制每个代码的历史起点和首期应有日线范围。 |
| 交易日历 | 使用现有 `DEFAULT_EXCHANGE` Settings，源码默认 SSE，业务时间按上海时区。 | 确认实际日历配置和适用交易日，统一确定期初、期末、上一交易日与所需日线日期。 |
| 自动任务 | 由管理员在数据后台配置，首期以日线 Raw 在上海时间 22:00 前就绪为排程假设。 | 每交易日盘后周、月各执行一次 Serving 更新。现有正式维护任务按周、月实际期末在收盘后触发。 |

[现行审查中心页面](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-review-index-page.tsx) 使用日线资源，[后端通用增删命令](/Users/congming/github/goldenshare/src/ops/services/review_center_service.py) 接受资源参数。复用池表时，首期要确保这些通用命令不能增删周、月线池。资源值、实际配置和消费者在开工前核实。

## 4. 执行流程与失败处理

### 4.1 正式周、月线 Raw 维护

1. 常规维护按频率与真实期末日分页下载。范围不指定代码时保存源端返回的全部有效正式记录。首期正式历史补数则限定 10 个代码，从各自发布日期到相应截止日。源无记录的代码可以通过 §4.2 的日线合成得到 Serving。
2. 完整取数单元通过现有字段和业务键检查后，按 Raw 主键提交本次有效记录。空返回、部分返回或请求失败时保留既有有效 Raw。没有取到正式数据时，任务详情列出频率、期末、失败阶段和可确定的缺失代码。有明确请求代码时可指出源未返回的代码，常规全范围任务不把 Serving 名单当作 Tushare 应有代码全集。
3. 源延迟、失败或中断的单元，按原频率、期末或窗口和代码范围重新请求 Tushare。正式维护仅写 Raw。已提交的 Raw 可读回，Serving 写入失败时单独重跑 Serving 任务。运营补入迟到 Raw 后，指定原期末日运行 Serving 更新。

### 4.2 独立 Serving 更新

运营可在同一当前周期内逐日指定已收盘的目标交易日，也可在跨期后选择过去周期的最后一个交易日。多个日子未成功时，从第一个未更新的交易日起按交易日顺序补。管理员配置的自动任务在目标交易日盘后执行。过目标交易日的上海时间午夜，尚未完成的旧自动任务转人工。

每个任务按其频率独立处理，同一任务的每个池内指数按下表执行。

| 顺序和条件 | 读写动作 |
| --- | --- |
| 1. 当期有正式周、月线 Raw | 直接按正式原值更新同一周期的 Serving，缺行可补建，来源为 `api`。按对应频率的真实期末日取正式 Raw。无需检查日线及上一交易日。 |
| 2a. 无正式 Raw，目标日处于当前周期 | 从该指数本周期首个应有交易日算到目标日。首日可创建。之后合成前检查本周期 Serving 的 `trade_date` 是否等于上一交易日，再检查计算窗口的应有日线是否齐全。合成来源为 `derived_daily`。 |
| 2b. 无正式 Raw，人工指定过去周期的最后一个交易日 | 检查从该指数本周期首个应有交易日起的完整日线。齐全则一次计算整期并写入，`trade_date` 为该期最后交易日。无须依赖 Serving 的上一交易日记录。首次历史重建的计算规则相同。 |
| 3. 所需日线缺失或连续性检查失败 | 保留该指数旧 K 线和截至日，原先无记录则保持缺行。任务详情列频率、代码、目标日或期末、失败阶段和缺失的日线日期，或者预期和实际截至日。通过检查的其他指数继续提交，本频率任务最终标记失败。另一频率独立执行。 |

例如 11 月 9 日合成成功，10 日日线缺失，Serving 截至日仍为 9 日。11 日即使有日线，检查预期为 10 日、实际为 9 日，该指数更新失败。运营补到 10 日日线后，先指定 10 日更新，再执行 11 日。如果要补已经结束的这一周，人工选其最后交易日，按上表先取正式 Raw，缺正式 Raw 时检查完整周日线。

10 个代码都走相同顺序。北证 50 缺正式 Raw 时用日线合成，未来查到当期正式 Raw 时照常覆盖。正式值优先，合成不能覆盖已有正式值。按周期唯一键写入，连续性检查和同一指数写入在同一业务事务内完成。同日重跑应幂等，处理较早目标日不能让已更新的行情截至日倒退。

### 4.3 首次历史补齐、清空重建与逐日接续

1. 周、月分别记录历史截止日。周线取 2026-11-06，月线独立选定已结束月份的最后交易日。按池内 10 个代码各自的已核实发布日期补到对应截止日，Tushare 返回的正式历史写入 Raw。
2. 获准切换后，初始化激活池，隔离两张 Serving 表的旧写入、待办重试和日更任务。清理清单仅为 `core_serving.index_weekly_serving` 和 `core_serving.index_monthly_serving`。清空两表后，按 §4.2 的优先顺序逐代码、逐周期计算和写入，只生成从该指数发布日期起的历史。采用已提交单元可续跑的方式执行，续跑保留已完成单元。实际遇到无法生成的历史周期时，在任务详情列出代码、周期和缺失的日线日期，再按具体情况决定如何补数。
3. 切换前按仓库规则明确两张表的备份、回退和并发隔离方案。若正式切换失败，按批准的回退方案恢复两张 Serving 表及本次池变更，保留已写入的正式 Raw。复制或读取两张旧表的全量明细，须按全局读取门禁单独批准。两表重建完成后，核对池内范围、起点、业务键和代表性读回，再开放日更。
4. 重建后周线从 11 月 9 日接续。若 10 日才完成，先指定 9 日生成周线，再在 10 日收盘后推进同一根。月线从当前月首个应有交易日按顺序接续。周、月各自检查连续性，无需等到两者首日重合。

## 5. 拟改位置与现行消费者

| 位置 | 现行行为和拟改边界 |
| --- | --- |
| DatasetDefinition、计划与请求 | [现行定义](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/index_series.py) 把周、月线列为期末维护数据集，登记 Raw 和 Serving。保留两个数据集的身份及正式维护入口，核实 Raw 单独写入对分层元数据和各消费者的影响。[现行日期规划](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py) 周线区间可能把截断周的最后开市日当期末，拟用完整周历求真实期末再与输入范围取交集。月线沿用完整月历判定。Ops 提交意图，Resolver 和 planner 展开范围，request builder 映射源参数。 |
| 正式 Raw 和 Serving 写入 | [现行写入器](/Users/congming/github/goldenshare/src/foundation/ingestion/writer.py) 写两层、使用日线池，并在源空或部分到达时触发合成。将正式维护改为只写 Raw，撤除清除未返回行及合成分支。独立的 Serving 更新由 Ops 调用 Foundation 的读取、计算和写入。核对 [现行服务表发布](/Users/congming/github/goldenshare/src/foundation/serving/publish_service.py) 的周、月线注册与调用，收敛到同一周期写入流程。 |
| 旧合成入口 | 移除 [动作和工作流目录](/Users/congming/github/goldenshare/src/ops/action_catalog.py) 的 `maintenance.rebuild_index_kline_serving` 和 `index_kline_maintenance_pipeline` 的合成末步 `rebuild_index_serving`，以及 [dispatcher 执行代码](/Users/congming/github/goldenshare/src/ops/runtime/task_run_dispatcher.py)。核对调度、手动、工作流、发布和重试引用。历史任务仍可读，旧重试不能触发已退出的执行入口。现有工作流的其他步骤继续按各自职责运行。 |
| 手动控件与自动任务 | 在现有 [手动任务服务](/Users/congming/github/goldenshare/src/ops/services/manual_action_service.py) 和 [自动任务服务](/Users/congming/github/goldenshare/src/ops/services/operations_schedule_service.py) 核验独立入口及日期控件。月末已支持最后交易日策略，周线期末须能按完整交易日历触发，包括周五休市的短周。Serving 自动任务由管理员配置盘后执行。 |
| 报错与重试 | 复用 [任务详情页](/Users/congming/github/goldenshare/frontend/src/pages/ops-task-detail-page.tsx)、[问题查询](/Users/congming/github/goldenshare/src/ops/queries/task_run_query_service.py) 和 [重试入口](/Users/congming/github/goldenshare/src/ops/services/task_run_service.py)。报错按 §4 区分 Raw 取数和 Serving 处理。正式维护重试重新请求原范围，Serving 重试复用原目标日、频率和代码读取 Raw。首期缺数通过任务详情显示。 |
| 行情接口和运营查询 | [通用行情 API](/Users/congming/github/goldenshare/src/biz/api/quote.py) 经 [查询服务](/Users/congming/github/goldenshare/src/biz/queries/quote_query_service.py) 直接读取两张 Serving，并按 `trade_date` 查询及排序，单位见 §2.2。核对池收窄导致的池外结果及同周期日期推进。[现行审查中心查询](/Users/congming/github/goldenshare/src/ops/queries/review_center_query_service.py) 以所选资源为覆盖率分母，不能用日线池覆盖率衡量周、月线池。 |

变更 `DatasetDefinition` 前，按模板 §0.3.2 审计手动、调度、工作流、目录、resolver、request builder、Probe、状态快照、数据卡、分层展示、日期完整性、前端控件和相关测试。当前工作流目录和日期指南记录现行行为，随对应实现落地同步。

## 6. 长任务、事务与预算

| 项目 | 执行边界 |
| --- | --- |
| 单元与规模 | 常规正式取数以频率和一个期末日为单元。正式历史以频率、代码和经验证的有界窗口为单元，日期范围以发布日期与截止日为界。Serving 历史重建按一个频率、一个代码、一个周期生成并提交。日常 Serving 任务每频率最多处理池内 10 个代码，每代码读取至多一个周期的日线，自然周不超过 7 个日期，自然月不超过 31 个日期。 |
| 分页、内存与请求量 | 现有 Definition 页大小为 1,000 行。短页结束时，一组分页对实际返回 `R` 行需要 `floor(R / 1,000) + 1` 次请求，满页后包含一次空尾页。总请求量按实际请求窗口逐项相加，另计失败重读及验收。只保留当前有界单元的数据，不累计完整历史。用代表性样本测量窗口大小、最大页数、单元耗时、内存与配额，开工前确定可接受的范围和超限处理。 |
| 持久化、幂等与续跑 | Raw 和 Serving 分开提交，各按现有业务键写入。已提交单元可读回。历史续跑保留已提交范围，未完成的正式取数单元按原范围重新请求，未完成的 Serving 单元读取 Raw 后重做。重复写入不能增加第二根同周期 K 线。切换清空与重建写入隔离于其他写入，不使用覆盖全历史的长事务。 |
| 取消、进度与终态 | 页和单元前后检查取消，停止领取新单元。按仓库长任务要求，运行中 30 秒内有可见更新，长调用须可安全中断或分段。TaskRun 展示阶段、代码或日期窗口、完成量、总量、百分比、最后更新时间，无法可靠估算时显示“暂无法估算”。成功、失败或取消时 TaskRun 与活动节点终态一致。观测失败不回滚已提交的业务数据。 |
| 切换和验收成本 | 分别测量备份、清空、装载、验收读回及恢复的耗时、锁、空间和 WAL。预算包含失败后续跑和最后读回。正式执行前通过获准的代表性运行核验中断、续跑、幂等与回退。 |

## 7. 已确认需求与验收

| 需求 | 实施位置 | 计划验收 |
| --- | --- | --- |
| R1 期末正式维护只写 Raw，按源范围保存 | §2.1、§4.1 | 短周按真实末日取数，校验分页。池外有效正式记录照常入 Raw。源空或部分到达不触发合成、不清除旧有效 Raw、不写 Serving。 |
| R2 正式维护失败按原范围重新请求 | §4.1、§6 | 对比首次及重试的频率、期末或窗口和代码，证明实际再次请求 Tushare。Serving 重试只读已落地的 Raw，运行失败不撤销 Raw。 |
| R3 Serving 独立手动、自动入口 | §3、§4.2、§5 | 数据后台分别配置周、月盘后自动任务。人工选择频率、日期和需要处理的代码。过上海时间午夜转人工，历史非期末、未收盘或休市日期不能作为目标。 |
| R4 Serving 先取正式，缺正式才合成 | §2.3、§4.2 | 有正式 Raw 即使缺日线或断档，也覆盖同一根 K 线。无正式 Raw 且日线齐全，正常合成。用北证 50 分别验证无正式 Raw 和以后有正式 Raw 两种路径。已发布的正式值不会被合成覆盖。 |
| R5 当前周期连续性和单指数失败 | §4.2 | 首个应有日创建，11-09 成功、11-10 缺失、11-11 已有日线时保留 11-09，任务显示预期和实际日期。其他正常指数保留提交，另一频率独立处理。人工先补 10 日再补 11 日，同日重跑不新增 K 线。 |
| R6 人工补已结束周期 | §4.2 | 选某个过去的周、月期末，有正式 Raw 直接写，无正式 Raw 且日线完整一次补齐。缺日线时保留旧值，在现有任务详情列出缺失日期。 |
| R7 独立激活池、历史起点和切换顺序 | §3、§4.3 | 核对首期仅有 10 个代码且不能日常增删。核对每代码适用的发布日期和历史截止。清空两表再计算入库，旧行和池外行退出。周历史到 11-06，11-09 起可按日接上。月线独立接续。日线池回归，二期增删单独验收。 |
| R8 正式与合成单位一致 | §2.2 | 用已知的真实周、月样本核对量、额倍率、4 位小数及涨跌幅。覆盖前后单位一致，正式值保留源值。现有通用行情接口单位回归，财势乾坤后续接入时验收手、千元及百分数展示。 |
| R9 移除旧合成入口 | §5 | 正式维护、现有工作流及旧重试不能绕回旧合成，历史记录可读。池外代码不能进入周、月 Serving，现有日线维护入口仍有效。 |
| R10 长任务和安全切换 | §4.3、§6 | 获准的代表性运行核对源、归一化、拒绝和读回，演练中断后续跑、幂等、取消、进度、状态写入失败、节点终态和回退。 |

现有测试入口包括[周期线数据库测试](/Users/congming/github/goldenshare/tests/test_index_monthly_postgres.py)、[分层写入测试](/Users/congming/github/goldenshare/tests/test_dataset_writer_index_layer_alignment.py)、[日期规划测试](/Users/congming/github/goldenshare/tests/test_index_monthly_calendar.py)、[动作目录测试](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)和[任务 API 测试](/Users/congming/github/goldenshare/tests/web/test_ops_task_run_api.py)。旧行为的用例随旧入口撤除而更新。源字段和计算预期须采用独立的真实依据。以上均为验收计划。

## 8. 开工与正式执行前的核验

1. **开工前**，核实各指数发布日期及历史请求、分页和字段，完成 §5 的受影响消费者核验和 §6 的请求量、内存、单元耗时与限流预算。用有界样本检查 OHLC、前收盘、涨跌、缺值和零值，包括发布日期在期中的首期。§2.2 的单位、倍率和涨跌幅表示已经确认。
2. **正式执行前**，按 §6 验证历史任务预算、切换锁与回退，并做代表性最小真实验收。运行中发现实际历史缺口时，再按该代码和周期决定如何补数。
