# 财势探查｜主要ETF（国家队）监测低层设计 v1

2026-11-27。桌面 Figma、本文与[技术实施方案](./major-etf-monitor-implementation-design-v1.md)已确认。第 1 阶段接口与真实 DG 对账已完成，待管理员确认结果。名单、数据语义、范围和性能预算以方案 §3–5 为准。[第 1 阶段对账记录](#major-etf-monitor-phase-1-result)

## 1. 调用链及改动位置

| 层级 | 实现位置与职责 |
| --- | --- |
| App | `src/app/api/v1/router.py` 的 `_include_local_etf_activity` 在 `etf_activity_enabled(settings)` 通过后，用同一 `EtfDailyLakeReader` 实例注册新模块路由。注入 `require_quote_access` 和 `WebAppError`。`src/app/exceptions/web.py` 的 `_response_headers` 加入新接口，使异常响应也使用 `no-store`。 |
| Biz API | 新增 `src/biz/api/wealth/market/major_etf_monitor.py` 的 `build_router`，注册 `/wealth/market/major-etf-monitor`，按上海时区取业务日期，调用 `query_major_etf_monitor`。接口走仓库已有 `/api/v1` 前缀。复用现有认证返回语义。 |
| Biz 查询和 DTO | 新增 `src/biz/queries/wealth/market/major_etf_monitor/major_etf_monitor_query.py` 和 `src/biz/schemas/wealth/market/major_etf_monitor.py`。查询模块承载唯一有序代码表、月份计算、SQL 参数与响应装配。DTO 承载 §3 的字段。薄路由直接调用查询。 |
| Foundation | `src/foundation/clients/local_lake/etf_daily_reader.py` 复用 `daily_files`、`basic_file`、`query_parquet` 和 `remaining_etf_read_seconds`。给 `daily_files` 增加命名参数 `require_directory`，默认保持原分支，仅新模块选择在日线目录缺失时报告来源错误。可读空目录返回空数据。 |
| 页面 | `wealth/src/pages/wealth-exploration/EtfActivityPage.tsx` 在现有工作区下面装配 `MajorEtfMonitor`，沿用 `WealthExplorationShell` 及页面路由。新增 `wealth/src/features/wealth-exploration/major-etf-monitor/` 下的 `api/majorEtfMonitorApi.ts`、`model/useMajorEtfMonitor.ts`、`ui/MajorEtfMonitor.tsx`、`ui/MajorEtfTurnoverChart.tsx`、`ui/MajorEtfQuotes.tsx` 和样式。 |

复用依据：`daily_files` 仅读目录元数据，`basic_file` 通过同日 DG 元数据定位名称快照，`query_parquet` 对指定文件的字段类型做检查后运行传入 SQL。`query_etf_activity` 仍由原接口调用，新模块不调用 `reader.calendar`、原趋势查询或排名查询。原自然月计算移至 `src/biz/queries/wealth/market/date_windows.py` 的 `months_before`，两条 ETF 查询复用同一计算，按原接口用例回归。`EtfActivityChart` 当前固定渲染三序列，复用已验证的坐标、空值断线和读数实现中的通用部分，新图只传合计序列。若提取图形小函数，按原测试回归全市场画板及 tooltip；表格按五列单独实现，复用 `etfActivityFormatters` 的金额、价格与涨跌幅格式化。无需改共享导航组件、登录链路、Dagster 资产或上游字段合同。

## 2. 后端读取、聚合与异常

1. 进查询后用 `monotonic()` 建立一个 5 秒读取截止时间。`daily_files(through=today, require_directory=True, deadline=...)` 复用现有日期命名、普通文件和正式根边界。取最大分区日。可读目录内没有符合条件的文件时直接返回空合同。未来日期的目录、非标准目录和未提升 `part-000.parquet` 的目录不进入输入。
2. 向前推 1/3 个自然月，沿用 `query_etf_activity` 的月份和月末算法。闭区间内只向 DuckDB 传一份显式且按日期升序的文件列表和对应日期。`basic_file` 只对最大分区日调用一次。现行实现用 `limit: 1`、该日的 `silver_etf_daily` 分区、`dagster/uri`、`goldenshare/basic_raw_snapshot_hash`、`goldenshare/basic_silver_uri` 验证引用；只打开该引用的正式快照。
3. DuckDB 一次查询使用参数化的有序代码表 `(ts_code, ordinal)` 和文件映射 `(filename, file_day)`。关闭 Hive 分区推断，以文件内 `trade_date: DATE` 做合同核对。ETF 日线投影 `ts_code: VARCHAR`、`trade_date: DATE`、`amount/close/pct_chg: DOUBLE`。基础信息投影 `ts_code/csname/extname/cname: VARCHAR`。先在 SQL 内把两个数据集缩到目标代码，再计算日合计和最新日行情。查询以 `file_day` 为横轴，左联日聚合结果，使已有分区的 0 至 13 个目标观测产出空合计；齐 14 条有效记录时计算 `fsum(amount) * 1000`。最新行情以名单为左表连接最新日观测与名称，按 `ordinal` 排序，金额逐行转元。同一次 SQL 的趋势和行情共用筛选后的日线输入。
4. 发现目标代码日线重复、文件内交易日与分区不符、目标日线金额缺失／非有限／为负、最新日目标行的收盘价缺失／非有限／非正、最新日目标行的涨跌幅缺失或非有限、快照内目标代码重复时，返回来源错误。无某个代码的日线或无该代码名称时保留缺值语义。名称字段去首尾空白，空字符串按缺名处理。名单的成员与顺序始终按方案 §3.1。
5. 路由将预期的 DG 文件、快照引用、DuckDB 或时间预算错误统一转 503。错误码为 [异常码注册表](../../system/exception-code-registry.md#major-etf-monitor-local-api)登记的 `MAJOR_ETF_MONITOR_SOURCE_UNAVAILABLE`，语义为「主要ETF（国家队）监测暂不可读取，请重试」。按现行 Web 错误信封提供 `code`、`message`、`request_id`。日志沿用请求 ID，记录处理阶段、目标日期和源读取耗时，路径和底层异常不随响应返回。

DG 日线是逐文件原子发布。同一次请求按选中的路径读取，最多使用一个名称快照。若文件或同日引用在读取期间不可用，本次结束为错误，手动重试重新从源读取；无自动重试、后台补数或写入。本地验收先核对认证也使用本机环境。

## 3. HTTP 契约

`GET /api/v1/wealth/market/major-etf-monitor`。客户端不传标的、区间、交易日或数据源参数；URL 附加参数不能改变服务器名单、日期范围或数据源。响应 `Cache-Control: no-store`。

| 路径 | 类型与约束 |
| --- | --- |
| `status` | `ready` 或 `empty`。任一面板拥有可用行情/合计即为 `ready`，局部缺值按相应字段表达。完全无可用结果为 `empty`。加载和错误由请求生命周期表达。 |
| `tradeDate` | 日期字符串 `YYYY-MM-DD`。`ready` 时是最新正式 ETF 日线分区日期，两栏共用。`empty` 时为 `null`。 |
| `oneMonthStartDate` | 日期字符串或 `null`，取 `tradeDate` 的上一个自然月同日，必要时取月末。`empty` 时为 `null`。 |
| `trend` | 3 个月内正式日线分区的有序数组。每项 `tradeDate` 为日期字符串，`amountYuan` 为有限非负数或 `null`。空结果为 `[]`。 |
| `quotes` | 最新日有目标日线时固定 14 项，按产品名单顺序。一项字段为 `tsCode`（带交易所的代码）、`name`（字符串或 `null`）、`closePrice`（元）、`priceChangePct`（百分数）、`amountYuan`（元）。某代码无当日日线时三个数值都为 `null`。最新日没有任何目标日线则为 `[]`，本模块可以同时保留历史趋势。 |

`empty` 示例：

```json
{"status":"empty","tradeDate":null,"oneMonthStartDate":null,"trend":[],"quotes":[]}
```

有界读取核验中的 `2026-11-26` 交易日给出下列字段示例。该样本下趋势按已有分区的日期升序排列，行情包含 14 项。

```json
{"tradeDate":"2026-11-26","amountYuan":44382245742.60}
```

```json
{"tsCode":"510300.SH","name":"华泰柏瑞沪深300ETF","closePrice":3.959,"priceChangePct":-0.28,"amountYuan":3419450769.0}
```

非本地环境返回 404，认证未通过按现有行情认证返回，来源失败返回 503，均不返回成功 DTO。收盘日期、序列、价格和成交额的业务事实以 DTO 为准。

## 4. 桌面交互和状态

| 项目 | Figma 和实现要求 |
| --- | --- |
| 放置和容器 | 1600 px 桌面参考中，两栏接在全市场行下方，组间和两栏间均为 12 px。两栏同高 448 px，参考宽 680/872 px，按现有桌面容器比例排布。页面正常纵向滚动。快捷入口维持三张独立卡的样式。 |
| 左侧标题及图表 | 标题「主要ETF（国家队）成交额趋势」，副标题「14 只 ETF · 亿元」，蓝色「合计成交额」图例。默认 1 个月。用 `oneMonthStartDate` 过滤已收到的 3 个月数组。交易日轴 `MM-DD`，纵轴 0 基线，按非空值取正上限和刻度。绘图区可聚焦，左右方向键与鼠标选日，读数显示 `YYYY-MM-DD`、两位小数亿元或「—」。切换后仅保留仍在当前可见区间的选中日期。 |
| 右侧标题及表格 | 标题「主要ETF（国家队）行情」，就绪时右上角「14 只 ETF」及「日线收盘 YYYY-MM-DD」。五列依次是「ETF 代码」「ETF 名称」「现价（元）」「涨跌幅」「成交额（亿元）」。表宽参考 848 px，列宽 120／365／101／112／150 px。前两列左对齐，三个数值列右对齐。表头固定高 32 px、表体视窗高 340 px、行高 34 px，首屏 10 行，向下滚动到第 14 行。沿用弱表头、细分隔线和无内框的列表样式。 |
| 显示格式 | `null` 显示「—」。涨跌方向采用结构化 `priceChangePct` 与现有共享方向工具，统一由 `formatEtfPriceChange` 映射符号和颜色。上涨红、下跌绿、格式化为 `0.00%` 时中性。价格三位小数，成交额与左图读数均以亿元保留两位。 |
| 模块隔离 | `useMajorEtfMonitor` 管理自身请求、AbortController 和重试。图表范围的更新只作用于新图，表体维持同一元素和滚动位置，上方全市场请求与范围独立。进入本页时两组模块各发一次请求。仅重试新模块时只补一次新模块请求。 |

| 状态 | 左侧 | 右侧 |
| --- | --- | --- |
| `loading` | 区间切换暂不可用，「正在读取主要ETF成交额…」。 | 固定五列表头，显示「正在读取主要ETF行情…」和骨架行。 |
| `ready` | 显示选定区间内的有效点。已有分区的不完整合计断线。若 1 个月内没有有效值但 3 个月内有，默认区间显示空提示并可切换。 | 只出现部分当日日线时，14 行中缺失行三个行情值显示「—」。若最新日全无目标观测，保留表头和「暂无可用的主要ETF行情」，日期显示「—」。 |
| `empty` | 「暂无可用的主要ETF成交额数据」。无可用趋势时区间切换暂不可用。 | 保留表头，日期「—」，显示「暂无可用的主要ETF行情」。 |
| `error` 或读取超时 | 「主要ETF成交额趋势暂不可读取」。区间切换暂不可用。 | 保留表头，日期「—」，「主要ETF行情暂不可读取」和一个「重试」按钮。客户端超时明确显示「主要ETF行情请求超时」。重试回到加载态，只重取本模块。 |

客户端 5 秒从发起到解析响应体使用同一计时。退出时中止，超时或已取消的旧响应不得覆盖当前状态。读数颜色、日期和金额以真实响应为准。

## 5. 编码门禁矩阵

| [通用清单](../../system/module-delivery-checklist-v1.md) | 适用性、落点、验证 |
| --- | --- |
| 2.1 交付事实链 | 适用。已确认 Figma，方案和本 LLD 评审后开工。 |
| 2.2 后端事实归一 | 适用。§2–3 在后端确定日、金额、名称和排序，前端只格式化或筛选可见区间。用真实 API 和独立样本核对。 |
| 2.3 模块状态 | 适用。§3–4 正常、空、局部缺数、失败及 5 秒超时，测试请求状态转换。 |
| 2.4 显示语义 | 适用。§4 从数值字段得到符号与红涨绿跌。测试正、负、零、小非零格式化及缺值。 |
| 2.5 行为过程 | 适用。§4 和 §6 覆盖加载到就绪、切换、超时、重试、退出和滚动。 |
| 2.6 文档同步 | 适用。接口、Figma、方案、LLD、异常码登记及核心断言同轮对齐。 |
| 2.7 模块渐进交付 | 适用。沿用 ETF 页面本地开关，变更前该位置无模块请求，变更后仅新增此真实请求。无 mock 回退，独立回退步骤见方案 §6。 |
| 2.8 契约先行 | 适用。§3 固定字段、可空性、空数据和异常。后端真实接口校验和前端消费校验都覆盖。 |
| 2.9 图表坐标 | 适用。§4 按已有日线日期等距、0 基线、单序列、缺点断线。测试轴域、读数和单位。 |
| 2.10 计算与传输 | 适用。§2 下推过滤与汇总。测试使用真实 DuckDB 与 Parquet；端到端按方案 §5 测量。 |
| 2.11 策略中心配置 | 不适用。14 个代码是本版固定产品定义，未引入可配置策略。现行环境和路径开关按方案 §4 测试。 |
| 2.12 清单映射 | 适用。本节逐条映射并提交评审。 |
| 2.13 例外及语义断言 | 适用。例外白名单为空，测试非负轴、缺值及有效零。 |
| 2.14 显式坐标参数 | 适用。纵轴 0 不被自动上限覆盖，用含非零数据和全零样本断言。 |
| 2.15 并排图与标签 | 双图坐标对齐不适用，监测区只含一张图及一张表。轴标签避让适用，检查两种范围中的长金额、末日标签和 tooltip。 |
| 2.16 指标卡文案 | 不适用。Figma 没有指标卡。 |
| 2.17 核心真实用例 | 适用。§6 写明核心字段、执行方式和通过条件。 |
| 2.18 八项原则 | 适用。事实源 §2、契约 §3、配置方案 §4、默认 §3–4、筛选排序 §2、性能方案 §5、异常 §2–3、用户可见结果 §4 和 §6。 |

## 6. 分阶段执行与验收用例

各阶段的目标、禁止项、本地数据权限、预算、遇错结束及重试规则见方案 §4–6 和本文 §1–4。编码与验收完成后，在本节记录实测结果、剩余事项及下一阶段确认，保留评审和历史记录。

| 阶段与用例 | 验证方式与通过条件 |
| --- | --- |
| 1. 路由与空结果 | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/web/test_wealth_market_major_etf_monitor_api.py tests/web/test_wealth_market_etf_activity_api.py`。新用例走 App 装配与真实路由，查询和 DTO 都走真实代码。临时 Parquet 以 DG 生产者的 DATE、DOUBLE、VARCHAR 和正式目录结构造夹具。认证与 loopback 元数据可隔离，明确记录替身边界。校验 `status`、`tradeDate`、`oneMonthStartDate`、`trend[*].{tradeDate,amountYuan}`、`quotes[*].{tsCode,name,closePrice,priceChangePct,amountYuan}` 和错误信封。 |
| 1. 正反例 | 手算 14 个各 100 千元的合计为 1,400,000 元，混入名单外大额 ETF 后仍相同。缺一个代码的日期断线，正常零金额参与加总，空目录与根/文件/引用错误分别断言。核对月底、跨年、两端日期纳入、缺完整分区不补点、最新日不回退、名称优先级、14 行顺序和缺前一日文件时 `pct_chg` 仍可见。对重复目标代码、错日期、坏行情、错类型和指向根外的引用做反例。 |
| 1. 读取与部署边界 | 在隔离请求中记录或阻断交易日历、其他 Parquet、其他 HTTP 主机和行情数据库调用。断言批量路径仅含三个月闭区间内的正式日线和一个同日基础快照，测试区间外历史分区、未来分区、Prod 模式、未显式配置和本地根错误。认证拒绝时没有 DG 行情读取。非本地返回 404 并跳过新读取依赖。 |
| 1. 本机真实文件与 API | 本机有界对账。以两个合规 DG 文件源做独立 DuckDB 聚合，随后请求实际注册的模块接口。比较请求看到的最新数据日、14 个代码与名称、代表性最新价格/涨跌幅/金额和区间内各点。若相对方案样本已有新日期，以实际 DG 当次读回为准。记录真实但隔离认证下的边界、文件数、分阶段耗时和一次手动重试。 |
| 2. 前端行为 | `npm --prefix wealth run typecheck`、`npm --prefix wealth run test`、`npm --prefix wealth run build`、`npm --prefix wealth run build -- --mode local-dg`。页面用例覆盖 §4 字段、1/3 个月两个状态、图表零基线与断线、键盘和鼠标读数、右表滚动及切换保留位置、空数据、错误文案、超时、手动重试和卸载取消。用请求记录断言上方原模块调用、结果和范围不受影响。正常构建回归原本地路由门禁。构建输出与临时数据放到本任务在 `/private/tmp` 的目录。 |
| 3. 真实浏览器展示 | 在获准的本机 Web 和 DG 环境下使用 `npm --prefix wealth run dev` 的本机代理或本机构建，登录后打开 `/wealth/exploration/etf-activity`。比较真实 API 响应与左轴日期及悬停合计值、右表五列、14 只顺序和末行。记录真实数据日、屏幕宽、访问耗时、首次和重试的请求数、切换区间新增请求为 0、表体滚动保留。与确认 Figma 对照上下两组位置、12 px 间距、两栏、末行及读数。真实链路与隔离 UI 状态证据分别记录。 |

<a id="major-etf-monitor-phase-1-result"></a>

## 7. 第 1 阶段对账记录

2026-11-27 07:30（上海时间）。通过进程内 HTTP 客户端请求正式 Web App 注册的 `GET /api/v1/wealth/market/major-etf-monitor`。采用隔离账号数据库依赖，使用真实本机 DG 元数据、ETF 日线及 ETF 基础信息文件。正式 Web 启动任务和真实登录留给后续验收。

| 验收项 | 结果 |
| --- | --- |
| 日期和曲线 | 最新日 `2026-11-26`，1 个月起日 `2026-10-26`，24 个点。3 个月起日 `2026-08-26`，61 个点。按固定名单独立读取 854 条目标日线（61 日 × 14 只），逐日用十进制汇总并以元保留到分核对，61/61 一致。全部已有分区的目标代码齐全。 |
| 行情 | 14/14 行代码顺序、快照名称、收盘价、涨跌幅和成交额与 DG 一致。最新日合计 `44,382,245,742.60` 元，按设计展示 `443.82` 亿元。使用最新日记录引用的基础信息快照 `33c87f79313c7de2458c52872d3b678034e3f78e95a04f102f693bb025e0588e`。 |
| 请求与耗时 | 首次成功请求 488.7 毫秒（日期枚举 8.2、同日引用 68.6、Parquet 校验和查询 406.8 毫秒），HTTP 200、`no-store`，实际打开 61 个日线文件和 1 个基础信息文件，JSON 5,169 字节。隔离注入一次本机元数据连接失败，HTTP 503 且未进入 Parquet 查询。手动重试 61.5 毫秒，HTTP 200，JSON 内容与首次相同。耗时为该次进程内测量。 |
| 数据边界 | 成功请求各一次本机 `127.0.0.1:3000` 连接。独立对账只查询上表的日线窗口和引用快照。验收阻断了交易日历读取和其他地址，未连接 Prod 或执行写入。隔离接口测试也验证了 Prod 模式下返回 404。 |
| 测试与影响面 | 新接口 22 项、原 ETF 动态接口及分层护栏合计 55 项通过。CodeGraph `codegraph_explore` 复核了 App 装配、Biz 查询、Foundation 读取及原 ETF 前端消费者。旧接口仅复用原样迁出的自然月计算，行为由原接口测试回归。 |

| 最新日行情（API 顺序） | 现价（元） | 涨跌幅 | 成交额（亿元） |
| --- | ---: | ---: | ---: |
| `510300.SH` 华泰柏瑞沪深300ETF | 3.959 | −0.28% | 34.19 |
| `510310.SH` 易方达沪深300ETF | 3.849 | −0.23% | 26.75 |
| `510330.SH` 华夏沪深300ETF | 4.132 | −0.10% | 5.07 |
| `159919.SZ` 嘉实沪深300ETF | 4.136 | −0.15% | 4.74 |
| `510050.SH` 华夏上证50ETF | 2.864 | +0.25% | 25.03 |
| `510500.SH` 南方中证500ETF | 5.888 | −0.57% | 24.44 |
| `512500.SH` 华夏中证500ETF | 3.333 | −0.63% | 3.82 |
| `512100.SH` 南方中证1000ETF | 2.249 | −0.22% | 79.08 |
| `159845.SZ` 华夏中证1000ETF | 2.305 | −0.26% | 14.45 |
| `560010.SH` 广发中证1000ETF | 2.308 | +0.17% | 12.49 |
| `159629.SZ` 富国中证1000ETF | 2.312 | −0.17% | 4.20 |
| `159915.SZ` 易方达创业板ETF | 2.217 | +0.82% | 129.42 |
| `159977.SZ` 天弘创业板ETF | 1.144 | +0.09% | 4.53 |
| `588000.SH` 华夏上证科创板50成份ETF | 1.233 | −1.68% | 75.60 |

运行 §6 的 Python 回归时，用 `PYTHONPATH=packages/technical_indicators/src` 指向仓库当前技术指标包源码。当前 `.venv` 中的已安装副本缺少本次 App 测试所需的 `configuration.datasets`，未变更本机依赖。真实浏览器、登录和同页两模块并行请求的耗时仍由后续阶段验收。
