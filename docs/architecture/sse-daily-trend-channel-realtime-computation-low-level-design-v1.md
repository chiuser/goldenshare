# 上证指数日线趋势通道 LLD：现行实现与维护合同

状态：后端和 Wealth 前端已实现；生产需求于 2026-09-05 按管理员确认结案。旧草案中的“待创建/未接入”不再作为开发任务。
最近代码审计：2026-09-10。
上位[决策与范围](/Users/congming/github/goldenshare/docs/architecture/sse-daily-trend-channel-realtime-computation-plan-v1.md)；[M4 历史验收](/Users/congming/github/goldenshare/docs/architecture/sse-daily-trend-channel-m4-readonly-performance-validation-2026-08-10.md)。

## 1. 实现路径与文件处理边界

| 层 | 当前文件（相对仓库根） | 职责 |
| --- | --- | --- |
| 路由 | src/biz/api/quote.py | 独立 trend-channel 端点、鉴权依赖、参数与异常映射 |
| 查询 | src/biz/queries/quote_trend_channel_query.py | 身份、水位、全历史，只读 DB |
| 计算 | src/biz/services/quote_trend_channel_calculator.py | 无 IO 纯递推与整序列校验 |
| 组合/缓存 | src/biz/services/quote_trend_channel_query_service.py | 一致性检查、缓存、切片、DTO |
| 响应 | src/biz/schemas/quote_trend_channel.py | 专用 Pydantic 合同，不复用 QuoteKlineBar |
| 身份/行情模型 | src/foundation/models/core/index_basic.py、src/foundation/models/core_serving/index_daily_serving.py | 实际 schema 均为 core_serving；目录名不代表 SQL schema |
| 页面控制 | wealth/src/features/index-detail/controller/useIndexDetailController.ts | 000001.SH 的独立通道请求 |
| 页面适配/绘制 | trendChannelApiClient.ts、trendChannelAdapter.ts、wealth/src/shared/charts/trend-channel/trendChannelGeometry.ts | API 消费、校验与通道几何 |

这是现存文件职责，不是重新创建白名单。未获新授权不修改共享 K 线 API、基础表、配置、迁移、Lake 或其他指数适配。本轮使用 CodeGraph CLI status/query/impact 定位 service 的 API/测试消费者，再直接读取实现及 Wealth 调用链；索引不能代替语义核验。

## 2. 已拍板硬口径

| 编号 | 硬口径 | 实施含义 |
| --- | --- | --- |
| D01 | 短期周期固定 25 | `EMA(high,25)` 与 `EMA(low,25)` |
| D02 | 长期周期固定 90 | `EMA(high,90)` 与 `EMA(low,90)` |
| D03 | 首值种子 | 第一根 EMA 等于第一根输入，`adjust=False` 语义 |
| D04 | 严格突破 | `close > upper` 才是 `ABOVE`；`close < lower` 才是 `BELOW` |
| D05 | 内部保留状态 | `INSIDE` 时 `state_t = state_(t-1)` |
| D06 | 位置与状态并存 | API 同时返回 `position` 和 `state` |
| D07 | 只做正式日线 | v1 不读取或生成盘中临时 OHLC |
| D08 | 独立 API | 使用 `/quote/detail/trend-channel`，共享 K 线合同不变 |
| D09 | 只支持上证指数 | 其他 `ts_code` 必须拒绝 |
| D10 | 先完整历史后切片 | `limit` 不能改变相同日期的计算值 |
| D11 | 失败关闭 | 坏行、重复日期和计算不变量失败时不跳过、不填充 |
| D12 | 不提前物化 | v1 按需计算并缓存，不新增持久化派生表 |

任何实现若与 D01～D12 冲突，应停止开发并回到方案评审，不得增加兼容分支。

---


## 3. 输入、计算与数值

Query 从 core_serving.index_basic 读取 000001.SH 身份；从 index_daily_serving 读取该代码全部 trade_date/open/high/low/close/updated_at，按日期升序。全历史查询不带 end_date 或 limit。

输入超过 10000 行、重复/倒序日期、缺 OHLC、非有限或非正价格、high/low 与 OHLC 关系非法时整序列拒绝，不跳行、不填前值。服务先按水位检查行数上限再拉全量，calculator 再做防御校验。空序列是合法空结果；缺基础身份则是不可用。

四轨：short_upper=EMA(high,25)，short_lower=EMA(low,25)，long_upper=EMA(high,90)，long_lower=EMA(low,90)。对任一输入 x：

```text
alpha = 2 / (N + 1)
EMA_0 = x_0
EMA_t = alpha * x_t + (1 - alpha) * EMA_(t-1)
```

用 Python float64，首观测种子、adjust=False。不得以页面窗口首根重新播种，也不得每日先量化后递推。

每组通道的 position/state：

| 当日未量化比较 | position | state |
| --- | --- | --- |
| close > upper | ABOVE | UP |
| close < lower | BELOW | DOWN |
| 其余（含相等） | INSIDE | 保留上一 state；初始 UNKNOWN |

combined_state 按短/长顺序组成 UP_UP、UP_DOWN、DOWN_UP、DOWN_DOWN；任一 UNKNOWN 则 UNKNOWN。单根合法 OHLC 种子位于通道内部，因此初始状态 UNKNOWN。

计算中保留未量化轨道判断状态；输出轨道用 Decimal(str(value))、ROUND_HALF_UP 量化 0.0001。源 OHLC 由当前 Numeric 四位模型提供，calculator 原样转交，不再为任意输入做一次四位清洗。Decimal JSON 为字符串。页面基于输出值着色，不能倒推改写后台未量化状态判断。

计算 O(n)，四条 EMA 递推状态 O(1)，为了响应缓存保存整序列 O(n)；返回 tuple 和 frozen dataclass，不可原地修改缓存。追加未来合法行不改变历史结果，历史数据修订则需要重算。

## 4. 水位、缓存和真实 DB 成本

缓存 key = Engine 身份（dialect + 进程内根 Engine id）+ ts_code + formula_version + row_count + max_trade_date + max_updated_at。身份不是数据库 URL，也不泄露凭据。进程级 singleton 保存至多两个 LRU 版本，entries lock 保护读写、compute lock 串行化冷算；clear 只清缓存，没有生产清库行为。

每次 build_response 先查身份，再进入 load_series：

1. 查询水位，命中缓存直接复用全序列。
2. 未命中则拿计算锁，再查一次水位并复查缓存。
3. 校验 <=10000 行，读取全部历史，再查一次水位。
4. 检查前后水位相同、实际行数相同、末日及行内最大 updated_at 匹配；稳定才计算并发布缓存。
5. 不稳定重试整个尝试一次；连续两次仍变化则抛 SourceChanging，不发布新结果。

| 完整 API 调用场景 | 正常无重试 DB 次数 | 说明 |
| --- | --- | --- |
| 热命中 | 2 | 身份 1 + 水位 1，仍构造 DTO/JSON |
| 冷成功 | 5 | 身份 1 + 水位 3 + 全历史 1 |
| 等待其他请求填缓存 | 依实际命中点 | 锁内复查可免完整读取 |
| 源变化重试 | 多于正常路径 | 不能把 5 次称为绝对上限 |

聚合水位不是全表 hash：若修改内容却不改变 count/max_date/max_updated_at，缓存不会失效。前后聚合也不等于全程数据库事务快照。原方案“任何历史修订都会被检测”修正为“水位变化触发重算”；要强化任意修订检测需要独立设计，不在本轮顺手改查询/索引。

## 5. API 与切片合同

路径 GET /api/v1/quote/detail/trend-channel，复用 require_quote_access 与既有 Web 错误响应 code/message/request_id。

| 参数 | 当前处理 |
| --- | --- |
| ts_code | 必填；trim + upper 后仅 000001.SH |
| period | 默认 day；trim + lower 后仅 day |
| end_date | 可选 date；只裁剪输出，不裁剪输入历史 |
| limit | 默认 500，1..2000；只限制响应窗口 |

未注册 formula、adjustment 或盘中参数，不能改变固定公式；但 FastAPI 对未声明 query 参数没有本端点的通用拒绝逻辑，不能宣称传这些参数必定 400。新增拒绝行为属于 API 变更，需要另批。

完整序列计算成功后，用 bisect_right 找 <=end_date 的末位置，返回最后 limit 根升序数据。has_more_history 由前面是否仍有行决定，next_end_date 是真实上一交易日，不做自然日减一。完整序列中的后续坏行会使历史窗口请求失败，这是先验证全历史的当前代价，不是未来数据参与历史计算。

| 响应 | 内容 |
| --- | --- |
| instrument | ts_code、name、security_type=index |
| period / adjustment | day / none |
| formula | key=high-low-ema-hysteresis；version=sse-daily-trend-channel-v1；short_period=25、long_period=90；seed=first_observation；state_rule=strict_close_breakout_inside_retention |
| data_status | READY/EMPTY、observed_trade_date、as_of_time、is_provisional=false、note |
| bars | trade_date、OHLC、short_channel/long_channel（upper/lower/position/state）、combined_state、is_provisional=false |
| meta | bar_count、limit、start_date、end_date、has_more_history、next_end_date |

observed_trade_date 来自完整源水位，不等于裁剪窗口末日；as_of_time 是响应构建时刻，不是源数据提交时刻。无源行返回 200 EMPTY，note=source_has_no_daily_rows；截止日期早于可用历史返回 200 EMPTY，note=no_rows_on_or_before_end_date。

| 情况 | HTTP / code |
| --- | --- |
| 非支持标的 | 400 UNSUPPORTED_TREND_CHANNEL_SYMBOL |
| 非 day 周期 | 400 UNSUPPORTED_TREND_CHANNEL_PERIOD |
| 缺 ts_code、非法日期、limit 类型/范围 | 框架 422 校验 |
| 基础身份缺失 | 503 TREND_CHANNEL_INSTRUMENT_MISSING |
| DB 源查询不可用 | 503 TREND_CHANNEL_SOURCE_UNAVAILABLE |
| 坏行/超量 | 503 TREND_CHANNEL_SOURCE_INVALID |
| 两次水位持续变化 | 503 TREND_CHANNEL_SOURCE_CHANGING |
| 计算不变量失败 | 500 TREND_CHANNEL_COMPUTE_FAILED |

已识别异常映射不等于吞掉所有编程异常；具体 reason_code 在内部异常对象保留，不能据此声称已经有专用日志。

## 6. 已接入的 Wealth 消费者

指数详情 controller 仅在 capability 支持且 ts_code=000001.SH 时发请求，使用 day、endDate 和 limit=300。其他指数不增加适配。专用 adapter 将 close 和上下轨字符串转数值；非法日期、非有限值、上下轨倒置、重复/非升序日期会被过滤并计入 PARTIAL，不能把这种页面防御等同于后端接受坏源行。

绘制按 close < lower 判定下方，否则判定非下方：短期红/绿、长期粉/蓝；同日连上下轨，跨日只连相邻 candle logical index 的同名轨，不跨缺口连线，采用当前点颜色。不填充区域、不绘制中轴。

页面不得按可见窗口重算 EMA、按颜色反推状态、自行补日期或把 UP/DOWN 转成买卖信号。未来若批准 provisional=true，须显式临时标识或虚线；当前始终 false，不提前添加盘中适配。

后台 position/state/combined_state 不因着色而删除或重定义；当前绘图 adapter 未保留这些状态供绘图使用。因此旧稿要求“tooltip 展示完整通道状态”不能写成已经实现；该展示要求保留为未落地项，后续如要实施须单列页面范围。本轮不补 UI。

## 7. 观测要求与未落地项

不创建 TaskRun、状态 snapshot 或 freshness。当前 service 没有专用 logger；下列为旧 LLD 保留的观测要求，**不是当前已产生日志字段**。它与 §4 水位局限、§6 状态 tooltip 一并作为已知差距，不因需求历史结案而伪造实现；本轮不新开工程任务。

服务日志至少包含：

| 字段 | 说明 |
| --- | --- |
| `event` | `trend_channel_cache_hit/cache_miss/rebuild_failed` |
| `formula_version` | 固定 v1 |
| `ts_code` | 固定 `000001.SH` |
| `row_count` | 水位行数 |
| `max_trade_date` | 水位日期 |
| `elapsed_ms` | 完整重算耗时 |
| `reason_code` | 失败原因，不含完整行内容 |

不记录：

- 数据库 URL 或凭据；
- 整段历史数据；
- 用户认证信息；
- 每次 EMA 中间数组。

日志失败不得影响 API 正常读取或业务数据事务。

---


## 8. 持续回归与金标

### 8.1 纯计算测试

目标：`tests/test_quote_trend_channel_calculator.py`

| 测试 | 正向/负向 | 断言 |
| --- | --- | --- |
| 首根种子 | 正向 | 上下轨等于首根 high/low，状态 UNKNOWN |
| 两根手算 | 正向 | 25/90 alpha 递推值误差 `< 1e-8` |
| 上破 | 正向 | position ABOVE，state UP |
| 内部保留 UP | 正向 | position INSIDE，state 仍 UP |
| 下破 | 正向 | position BELOW，state DOWN |
| 内部保留 DOWN | 正向 | position INSIDE，state 仍 DOWN |
| 边界相等 | 负向门禁 | 等于上/下轨不能触发切换 |
| 量化不递推 | 负向门禁 | 与“每日先量化”的错误实现不同 |
| 前缀不变性 | 正向 | 追加未来行不改变历史输出 |
| 不同 limit 一致 | 正向 | 同一日期通道值一致 |
| 重复日期 | 负向 | reason `duplicate_trade_date` |
| 无序日期 | 负向 | reason `trade_date_not_strictly_ascending` |
| 空/NaN/Infinity | 负向 | 对应 reason code |
| 非法 OHLC | 负向 | 整序列拒绝 |
| 10,001 行 | 负向 | 超量拒绝 |

### 8.2 独立参考金标

金标要求：

1. 从固定 `000001.SH` 日线快照生成。
2. 参考生成器不得 import 生产 calculator。
3. 至少覆盖首根、首次 UP、首次 DOWN、短期/长期分化和 2026-08-07。
4. 保存未量化轨道、四位输出、position、state 和 combined_state。
5. 生产结果逐日期对账。

固定文件：

1. `tests/fixtures/quote_trend_channel/000001_sh_daily_input.json`：保存截至 2026-08-07 的完整正式日线 OHLC，不保存页面窗口截断结果。
2. `tests/fixtures/quote_trend_channel/000001_sh_daily_expected_v1.json`：保存与输入文件 SHA-256 绑定的逐日金标。
3. 参考主算法使用 pandas `ewm(span=period, adjust=False)`，并以独立显式 `float64` 递推逐行交叉校验；两者最大绝对误差必须 `< 1e-8`。
4. 两个 JSON 均为测试事实文件，不进入运行时 API、数据库、Lake 或配置加载路径。

### 8.3 查询与缓存测试

目标：`tests/test_quote_trend_channel_query_service.py`

使用 fake query/calculator 验证：

1. 相同水位第二次不调用 `load_all_rows()`。
2. 新交易日、行数变化、`updated_at` 变化分别触发重算。
3. 缓存 key 包含 Engine identity，不跨测试数据库串数据。
4. 两个并发请求同水位只执行一次计算。
5. 第一次前后水位不同会重试。
6. 两次都变化会返回 `TREND_CHANNEL_SOURCE_CHANGING`。
7. `clear()` 后重新计算但结果一致。
8. 最多保留两个水位版本。

### 8.4 Web API 测试

目标：`tests/web/test_quote_trend_channel_api.py`

准备表：

- `IndexBasic.__table__`
- `IndexDailyServing.__table__`

每个测试前后清理专用进程缓存，避免全局状态泄漏。

必须覆盖：

1. `000001.SH + day` 返回 200。
2. Decimal JSON 为四位字符串。
3. `position` 与 `state` 同时存在。
4. 所有行 `is_provisional=false`。
5. `limit=1` 与 `limit=2` 的共同日期轨道一致。
6. `end_date` 截断正确。
7. `next_end_date` 是真实上一交易日。
8. 其他指数返回指定 400 code。
9. 周/月/分钟周期返回指定 400 code。
10. 空源返回 200 EMPTY。
11. 坏行返回 503，而不是跳过。
12. 缺失 IndexBasic 返回 503。
13. `QUOTE_API_AUTH_REQUIRED=true` 时无登录返回既有 `auth_required`。

### 8.5 回归测试

必须继续执行：

```text
tests/web/test_quote_api.py
tests/architecture/test_subsystem_dependency_matrix.py
tests/architecture/test_platform_legacy_guardrails.py
tests/architecture/test_operations_legacy_guardrails.py
```

回归断言：

1. `/api/v1/quote/detail/kline` 响应字段不增加通道字段。
2. 股票、指数、ETF 原有查询行为不变。
3. app router 不需要新 include。

---


## 9. 性能验收口径（保留原门禁）

### 9.1 基准场景

| 场景 | 输入 | 次数 | 指标 |
| --- | ---: | ---: | --- |
| 纯内核 | 1,000 行 | 至少 100 次热身后 1,000 次 | median/P95/max |
| 冷 API | 当前完整日线 | 至少 30 次，每次清缓存 | P50/P95 |
| 热 API | 当前完整日线 | 至少 100 次 | P50/P95 |
| 并发冷启动 | 10 个并发请求 | 至少 10 轮 | 重算次数与延迟 |

### 9.2 门禁

```text
纯内核 1,000 行 P95 < 10ms
冷 API P95 < 500ms
热 API P95 < 100ms
缓存结果内存 < 10MB
同一水位并发重算次数 = 1
```

基准必须区分：

- DB 水位查询耗时；
- 完整历史读取耗时；
- calculator 耗时；
- DTO/JSON 序列化耗时。

不得只报告总耗时而无法定位瓶颈。

---


## 10. 验收状态与后续维护

M0 独立快照/金标、calculator、Query/cache、API 和 Wealth 消费均已有实现；不再保留“新建全部文件”的开发步骤或整页未勾选待办。后续修改必须先对账 D01–D12，再按受影响测试层回归，不重复创建旧阶段。

M4 报告保留原始测量、只读边界、SHA-256 与临时样本用途。8 月 10 日公网直连 DB 与同机快照差异不能冒充最终生产拓扑 P95；9 月 5 日管理员确认实际拓扑无问题并关闭，但未提供原始性能样本，不补造数值。本轮本地测试也不能替代生产性能复验。

维护交付仍需保存：固定输入/独立金标、真实样本日期范围及坏行统计、calculator 分段基准、冷/热与并发证据、共享 K 线回归。稳定性只针对相同输入和公式的 bars/状态；as_of_time 等请求时刻字段不应要求跨请求字节一致。

没有新增配置、表/迁移、持久化派生结果或写任务。未来盘中、物化和范围扩展按主案重新评审；不能以这个已结案 LLD 作为部署、安装、修改正式数据的持续授权。
