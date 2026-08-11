# wealth 异常码注册表（统一管理基线）

## 1. 目标

`wealth` 工程内所有模块异常码必须集中管理，禁止分散在各页面文档、代码注释或临时方案中。

本文件是异常码唯一注册表，后续新增模块都必须在这里登记。

---

## 2. 管理范围

1. 市场总览相关接口返回的模块级异常码。
2. debug 模式下返回的 `exceptions` 列表中的 `code` 字段。
3. 前端排障日志与后端观测日志中的结构化异常码。

不在本文件登记的异常码，不允许进入代码和契约。

---

## 3. 命名规范

格式：

```text
<MODULE_PREFIX>_<SCENARIO>
```

示例：

1. `LB_SOURCE_EMPTY`
2. `LB_SOURCE_DELAYED`
3. `LB_QUERY_FAILED`

其中：

1. `LB` 表示 leaderboard 模块。
2. 其他模块后续新增专属前缀（如 `SECTOR_`、`LIMIT_`），但本期不落地。

---

## 4. 注册流程（强制）

新增异常码前必须完成：

1. 在本文件新增条目（含语义、触发条件、前端处理）。
2. 在对应页面级需求文档引用本文件条目，不得重复定义。
3. 再进入代码实现。

若异常语义变化，必须更新注册表并记录“兼容策略/废弃策略”。

---

## 5. 字段模板

每条异常码必须包含以下信息：

| 字段 | 说明 |
|---|---|
| `code` | 异常码唯一标识 |
| `module` | 所属模块（leaderboards/sectorOverview/...） |
| `severity` | `info/warn/error` |
| `userVisible` | 是否直接展示给用户（通常 `false`） |
| `debugOnly` | 是否只在 debug 模式返回 |
| `meaning` | 语义定义 |
| `trigger` | 触发条件 |
| `frontendAction` | 前端处理策略 |
| `owner` | 责任域（app/biz/ops） |
| `phase` | 生效阶段（Phase-1/Phase-2...） |
| `status` | `active/deprecated` |

---

## 6. 首期（Phase-1）已登记模块

> 当前已登记：榜单模块 + 今日市场客观总结模块 + 主要指数模块 + 市场风格模块 + 成交额总览模块 + 大盘资金流向模块 + 涨跌分布模块 + 涨跌停统计与分布模块 + 连板天梯模块 + 板块速览模块 + 新闻速览/个股新闻模块。

| code | module | severity | userVisible | debugOnly | meaning | trigger | frontendAction | owner | phase | status |
|---|---|---|---|---|---|---|---|---|---|---|
| `LB_SOURCE_EMPTY` | `leaderboards` | warn | false | true | 榜单源数据为空 | 目标日期无可用行 | 榜单空态 + debug 显示原因 | biz-api | Phase-1 | active |
| `LB_SOURCE_DELAYED` | `leaderboards` | warn | false | true | 榜单源数据日期落后 | `observedTradeDate < expectedTradeDate` | 模块标记 delayed；页面可能 PARTIAL | biz-api | Phase-1 | active |
| `LB_JOIN_METRIC_MISSING` | `leaderboards` | warn | false | true | 指标补列缺失 | daily_basic 等补列 join 失败 | 允许降级展示，缺列用 `--` | biz-api | Phase-1 | active |
| `LB_SUBJECT_NAME_MISSING` | `leaderboards` | info | false | true | 主体名称缺失 | 名称映射不到 | 前端仅显示代码 | biz-api | Phase-1 | active |
| `LB_QUERY_FAILED` | `leaderboards` | error | false | true | 榜单查询失败 | SQL/服务异常 | 模块 error，保留其它模块渲染 | biz-api | Phase-1 | active |
| `MS_CONFIG_MISSING` | `marketSummary` | error | false | true | 总结模块配置缺失 | summary definition 未找到 | 模块 error，textCard 回退固定文案 | biz-api | Phase-1 | active |
| `MS_CARD_COUNT_INVALID` | `marketSummary` | error | false | true | 卡片数量配置非法 | cardCount 不在 5/6 | 模块 error，拒绝按非法配置输出 | biz-api | Phase-1 | active |
| `MS_SOURCE_DELAYED` | `marketSummary` | warn | false | true | 总结模块关键源日期落后 | `observedTradeDate < expectedTradeDate` | 模块 delayed，页面可能 PARTIAL | biz-api | Phase-1 | active |
| `MS_SOURCE_EMPTY` | `marketSummary` | warn | false | true | 总结模块关键源无数据 | 关键来源查询无行 | 模块 empty，展示空态或降级文案 | biz-api | Phase-1 | active |
| `MS_TEXT_RENDER_FAILED` | `marketSummary` | warn | false | true | 文案模板渲染失败 | 模板变量缺失/禁用词命中/渲染异常 | textCard 使用 fallback 固定文案，并保留模块渲染 | biz-api | Phase-1 | active |
| `MI_CONFIG_MISSING` | `majorIndices` | error | false | true | 主要指数配置缺失 | majorIndices definition 未找到 | 模块 error，保留页面其他模块渲染 | biz-api | Phase-1 | active |
| `MI_CONFIG_INVALID` | `majorIndices` | error | false | true | 主要指数配置非法 | indexCodes 数量不为 10 或存在重复 | 模块 error，拒绝按非法配置输出 | biz-api | Phase-1 | active |
| `MI_SOURCE_DELAYED` | `majorIndices` | warn | false | true | 主要指数数据日期落后 | `observedTradeDate < expectedTradeDate` | 模块 delayed，页面可能 PARTIAL | biz-api | Phase-1 | active |
| `MI_SOURCE_EMPTY` | `majorIndices` | warn | false | true | 主要指数关键源无数据 | 10 指数目标日都无可用行 | 模块 empty，保留 10 卡占位并展示空态 | biz-api | Phase-1 | active |
| `MI_QUERY_FAILED` | `majorIndices` | error | false | true | 主要指数查询失败 | SQL/服务异常 | 模块 error，保留页面其他模块渲染 | biz-api | Phase-1 | active |
| `ST_CONFIG_MISSING` | `style` | error | false | true | 市场风格配置缺失 | style definition 未找到 | 模块 error，保持页面其余模块渲染 | biz-api | Phase-1 | active |
| `ST_CONFIG_INVALID` | `style` | error | false | true | 市场风格配置非法 | cardSources 结构错误/来源不合法 | 模块 error，拒绝按非法配置输出 | biz-api | Phase-1 | active |
| `ST_SOURCE_DELAYED` | `style` | warn | false | true | 市场风格数据日期落后 | `observedTradeDate < expectedTradeDate` | 模块 delayed，页面可能 PARTIAL | biz-api | Phase-1 | active |
| `ST_SOURCE_EMPTY` | `style` | warn | false | true | 市场风格关键源无数据 | 三卡当前值与历史点同时为空 | 模块 empty，展示空态 | biz-api | Phase-1 | active |
| `ST_QUERY_FAILED` | `style` | error | false | true | 市场风格查询失败 | SQL/服务异常 | 模块 error，保留其他模块渲染 | biz-api | Phase-1 | active |
| `TO_SOURCE_DELAYED` | `turnover` | warn | false | true | 成交额模块数据日期落后 | `observedTradeDate < expectedTradeDate` | 模块 delayed，页面可能 PARTIAL | biz-api | Phase-1 | active |
| `TO_SOURCE_EMPTY` | `turnover` | warn | false | true | 成交额模块关键源无数据 | 四卡与历史数据都为空 | 模块 empty，展示空态 | biz-api | Phase-1 | active |
| `TO_INTRADAY_MISSING` | `turnover` | warn | false | true | 日内累计曲线缺失 | `stk_mins` 在目标交易日无有效数据点 | 模块 partial，保留四卡与历史 | biz-api | Phase-1 | active |
| `TO_QUERY_FAILED` | `turnover` | error | false | true | 成交额模块查询失败 | SQL/服务异常 | 模块 error，保留其他模块渲染 | biz-api | Phase-1 | active |
| `MF_SOURCE_DELAYED` | `moneyFlow` | warn | false | true | 资金流模块数据日期落后 | `observedTradeDate < expectedTradeDate` | 模块 delayed，页面可能 PARTIAL | biz-api | Phase-1 | active |
| `MF_SOURCE_EMPTY` | `moneyFlow` | warn | false | true | 资金流模块关键源无数据 | 双卡与历史数据都为空 | 模块 empty，展示空态 | biz-api | Phase-1 | active |
| `MF_HISTORY_INCOMPLETE` | `moneyFlow` | warn | false | true | 资金流历史样本不足 | 历史点少于 22（1m）或 62（3m） | 模块 partial，debug 标记历史不足 | biz-api | Phase-1 | active |
| `MF_QUERY_FAILED` | `moneyFlow` | error | false | true | 资金流模块查询失败 | SQL/服务异常 | 模块 error，保留其他模块渲染 | biz-api | Phase-1 | active |
| `BR_SOURCE_EMPTY` | `breadth` | warn | false | true | 涨跌分布源数据为空 | 目标交易日无可用样本 | 模块 empty，显示空态并保留模块容器 | biz-api | Phase-1 | active |
| `BR_SOURCE_DELAYED` | `breadth` | warn | false | true | 涨跌分布数据日期落后 | `observedTradeDate < expectedTradeDate` | 模块 delayed，页面可能 PARTIAL | biz-api | Phase-1 | active |
| `BR_HISTORY_INCOMPLETE` | `breadth` | warn | false | true | 历史趋势样本不足 | 历史点少于 22（1m）或 62（3m） | 模块 partial，debug 标记历史不足 | biz-api | Phase-1 | active |
| `BR_FACT_DUPLICATED` | `breadth` | error | false | true | 涨跌分布事实表重复 | ClickHouse fact 表同一 `trade_date` 返回多行 | 模块 error，不静默合并 | biz-api | Phase-1 | active |
| `BR_QUERY_FAILED` | `breadth` | error | false | true | 涨跌分布查询失败 | SQL/服务异常 | 模块 error，保留其他模块渲染 | biz-api | Phase-1 | active |
| `LU_SOURCE_DELAYED` | `limitUp` | warn | false | true | 涨跌停模块数据日期落后 | `observedTradeDate < expectedTradeDate` | 模块 delayed，页面可能 PARTIAL | biz-api | Phase-1 | active |
| `LU_SOURCE_EMPTY` | `limitUp` | warn | false | true | 涨跌停模块关键源无数据 | 当日涨停/跌停/炸板集合均为空 | 模块 empty，展示空态 | biz-api | Phase-1 | active |
| `LU_SEAL_RATE_DENOM_ZERO` | `limitUp` | warn | false | true | 封板率分母为 0 | 非 ST 涨停数 + 非 ST 炸板数 = 0 | `sealingRate` 返回 null，模块可 READY/PARTIAL | biz-api | Phase-1 | active |
| `LU_PATTERN_INPUT_MISSING` | `limitUp` | warn | false | true | （历史）天地/地天判定输入不足 | 旧版时间字段判定链路覆盖率不足 | 已废弃，不再由当前实现产出 | biz-api | Phase-1 | deprecated |
| `LU_PATTERN_CONFLICT` | `limitUp` | warn | false | true | （历史）天地/地天冲突样本 | 旧版时间字段链路出现冲突命中 | 已废弃，不再由当前实现产出 | biz-api | Phase-1 | deprecated |
| `LU_DISTRIBUTION_MAPPING_MISSING` | `limitUp` | warn | false | true | 结构分布映射缺失 | `limit_cpt_list/ths_member` 无法形成有效分布行 | 模块 partial，结构块显示空或缺项 | biz-api | Phase-1 | active |
| `LU_HISTORY_INCOMPLETE` | `limitUp` | warn | false | true | 历史组合柱样本不足 | 历史点少于 22（1m）或 62（3m） | 模块 partial，debug 标记历史不足 | biz-api | Phase-1 | active |
| `LU_QUERY_FAILED` | `limitUp` | error | false | true | 涨跌停模块查询失败 | SQL/服务异常 | 模块 error，保留其他模块渲染 | biz-api | Phase-1 | active |
| `SL_SOURCE_DELAYED` | `streakLadder` | warn | false | true | 连板天梯源数据日期落后 | `equity_limit_list` 观测交易日小于期望交易日 | 模块 delayed，页面可能 PARTIAL | biz-api | Phase-1 | active |
| `SL_SOURCE_EMPTY` | `streakLadder` | warn | false | true | 连板天梯源数据为空 | 目标日期无有效 `equity_limit_list` 涨停行 | 模块 empty，保留五个空梯队 | biz-api | Phase-1 | active |
| `SL_INVALID_BOARD_COUNT` | `streakLadder` | warn | false | true | 连板次数字段非法 | `equity_limit_list.limit_times` 无法解析为正整数 | 丢弃异常行，模块 partial，debug 标记样本 | biz-api | Phase-1 | active |
| `SL_JOIN_METRIC_MISSING` | `streakLadder` | warn | false | true | 连板股票展示补列缺失 | 价格、涨跌幅、开板次数或主题标签缺失 | 主行继续展示，缺失字段显示 `--`，模块 partial | biz-api | Phase-1 | active |
| `SL_QUERY_FAILED` | `streakLadder` | error | false | true | 连板天梯查询失败 | SQL/服务异常 | 模块 error，保留其他模块渲染 | biz-api | Phase-1 | active |
| `SO_SOURCE_DELAYED` | `sectorOverview` | warn | false | true | 板块速览源数据日期落后 | DC 组合源任一必需源观测日期落后 | 模块 delayed，debug 标记落后源 | biz-api | Phase-1 | active |
| `SO_SOURCE_EMPTY` | `sectorOverview` | warn | false | true | 板块速览源数据为空 | 目标/观测交易日无有效 DC 组合源数据 | 模块 empty，展示空态 | biz-api | Phase-1 | active |
| `SO_COLUMN_METRIC_UNAVAILABLE` | `sectorOverview` | error | false | true | 板块速览列指标不可由冻结源产出 | 列定义要求 DC 组合源不存在的指标 | 模块 error，禁止伪造数据 | biz-api | Phase-1 | active |
| `SO_QUERY_FAILED` | `sectorOverview` | error | false | true | 板块速览查询失败 | SQL/服务异常 | 模块 error，保留其他模块渲染 | biz-api | Phase-1 | active |
| `NEWS_CONFIG_MISSING` | `marketNews` | error | false | true | 新闻模块配置缺失 | 找不到新闻模块策略配置 | 模块 error，保留其它模块渲染 | biz-api | Phase-1 | active |
| `NEWS_CONFIG_INVALID` | `marketNews` | error | false | true | 新闻模块配置非法 | `visibleItemCount`、源配置或返回条数配置非法 | 模块 error，拒绝按非法配置输出 | biz-api | Phase-1 | active |
| `NEWS_SOURCE_EMPTY` | `marketNews` | warn | false | true | 新闻模块当前列表为空 | `core_serving_light.news` 按当前接口筛选规则无可展示项 | 当前板块 empty，debug 标记来源为空 | biz-api | Phase-1 | active |
| `NEWS_SOURCE_DELAYED` | `marketNews` | warn | false | true | 新闻模块源数据日期落后 | 目标日无数据但存在更早新闻 | debug delayed，不自动展示旧日新闻冒充当前日 | biz-api | Phase-1 | active |
| `NEWS_CHANNEL_RULE_INVALID` | `marketNews` | error | false | true | 新闻频道分类规则不可用 | `core_serving_light.news.channels` 无法支撑 `公司/非公司` 分类 | 停止编码/发布，必须先确认真实频道取值 | biz-api | Phase-1 | active |
| `NEWS_QUERY_FAILED` | `marketNews` | error | false | true | 新闻模块查询失败 | SQL/服务异常 | 模块 error，保留其他模块渲染 | biz-api | Phase-1 | active |

## 7. 股票详情分钟模块（Phase-2）

| code | module | severity | userVisible | debugOnly | meaning | trigger | frontendAction | owner | phase | status |
|---|---|---|---|---|---|---|---|---|---|---|
| `SM_LOCAL_LAKE_NOT_CONFIGURED` | `stockDetailMinutes` | error | false | true | 本地分钟能力未完成运行配置 | 本地开关开启但 Lake root 不可读或 `local-lake` DuckDB 依赖不可用 | 本地启动失败；不以数据空态伪装 | app/biz-api | Phase-2 | active |
| `SM_SOURCE_NOT_READY` | `stockDetailMinutes` | warn | false | true | 分钟源数据尚未覆盖调用方期望日期 | 目标文件缺失、查询范围无文件，或 observed end 早于显式 `endDate` | HTTP 200；返回 `dataStatus=DELAYED`，保留页面其它内容 | biz-api | Phase-2 | active |
| `SM_SOURCE_CONTRACT_INVALID` | `stockDetailMinutes` | error | false | true | 分钟 Lake 文件不符合固定 schema/身份/时间键契约 | Parquet schema、代码、频率、日期或时间键校验失败 | 分钟模块 error；不返回可疑数据 | biz-api | Phase-2 | active |
| `SM_QUERY_FAILED` | `stockDetailMinutes` | error | false | true | 本地分钟查询执行失败 | DuckDB、文件读取或结果校验异常 | 分钟模块 error；保留股票身份、日线和右侧信息 | biz-api | Phase-2 | active |
| `SM_REQUEST_INVALID` | `stockDetailMinutes` | error | false | true | 分钟查询请求不合法 | 代码、频率、日期范围、cursor 或 limit 不合法 | HTTP 400；保留其它页面内容 | biz-api | Phase-2 | active |

---

## 8. 指数详情模块（Phase-3）

> 正式 DTO 语义见 [指数详情页正式 API / DTO 合同 v1](../pages/index-detail/index-detail-api-contract-v1.md)。`ID_*` 服务正式日线详情，`IM_*` 仅供后续本地指数分钟独立合同使用。

| code | module | severity | userVisible | debugOnly | meaning | trigger | frontendAction | owner | phase | status |
|---|---|---|---|---|---|---|---|---|---|---|
| `ID_REQUEST_INVALID` | `indexDetail` | error | false | false | 指数详情请求不合法 | code/date/period/limit/debug/cursor 等参数无法按冻结合同解析 | HTTP 400；请求错误壳或分钟局部错误，不继续派发后续请求 | biz-api | Phase-3 | active |
| `ID_NOT_FOUND` | `indexDetail` | warn | false | false | 指数不属于详情页正式名单或身份缺失 | code 不属于 `majorIndices/CN_A` 10 code，或名单内 code 无基础身份 | HTTP 404；全页 not-found 壳，返回指数首页 | biz-api | Phase-3 | active |
| `ID_SOURCE_EMPTY` | `indexDetailPageInit` | warn | false | true | 指数正式日线无可用观测行 | `index_daily_serving` 在期望日期及之前无该 code 行 | HTTP 200 + EMPTY；保留身份、工具栏和右栏空态 | biz-api | Phase-3 | active |
| `ID_SOURCE_DELAYED` | `indexDetailPageInit` | warn | false | true | 指数正式日线落后于期望交易日 | `observedTradeDate < expectedTradeDate` 且没有更高优先级 partial 原因 | HTTP 200 + DELAYED；保留数据并展示实际日期 | biz-api | Phase-3 | active |
| `ID_FACTOR_PARTIAL` | `indexDetail` | warn | false | true | 指数详情因子字段部分缺失 | page-init 同日 factor 行/量额缺失，factor 最新日落后，可绘制 bar 的 factor 量额缺失，MA 在实际有效历史已达到对应周期后仍为空，或其它预期技术因子缺失 | HTTP 200 + PARTIAL；基本行情量额 `--`，保留 K 线并让缺线断点 | biz-api | Phase-3 | active |
| `ID_BASIC_DAILY_PARTIAL` | `indexDetailPageInit` | warn | false | true | 基本行情日度指标部分缺失 | 同日 `index_daily_basic` 无行，或 PE/PE TTM/PB/换手率/流通市值/总市值任一为空 | 对应指标显示 `--`，其它基本行情保留，页面 PARTIAL | biz-api | Phase-3 | active |
| `ID_BASIC_BREADTH_PARTIAL` | `indexDetailPageInit` | warn | false | true | 成分涨跌统计未覆盖完整权重批次 | 有有效权重批次，但同日成分行情缺失导致 `missingCount > 0` | 保留 up/flat/down 与 coverage，页面 PARTIAL；missing 不计入 flat | biz-api | Phase-3 | active |
| `ID_WEIGHT_EMPTY` | `indexDetailWeights` | warn | false | true | 指数没有可用权重批次 | `max(weight.trade_date) <= contributionTradeDate` 无结果 | 权重 Tab EMPTY；不影响主图和基本行情 | biz-api | Phase-3 | active |
| `ID_WEIGHT_CONTRIBUTION_PARTIAL` | `indexDetailWeights` | warn | false | true | 部分权重行无法计算估算贡献点 | index preClose、成分 pctChg 等贡献输入缺失 | 行保留，贡献显示 `--`，coverage 记录缺失，权重 Tab PARTIAL | biz-api | Phase-3 | active |
| `ID_QUERY_FAILED` | `indexDetail` | error | false | false | 指数详情配置、查询或映射失败 | universe 配置缺失/非法、SQL、服务或 DTO 映射出现未恢复异常 | HTTP 500 或当前 Tab 局部 error；允许重试，不用 mock/fallback 冒充成功 | biz-api | Phase-3 | active |
| `IM_SOURCE_NOT_READY` | `indexDetailMinutes` | warn | false | true | 本地指数分钟源尚未覆盖请求范围 | 正式 Lake 分区/文件缺失，或 observed end 早于请求 endDate | HTTP 200 + DELAYED/EMPTY；保留日线和其它页面内容 | biz-api | Phase-3 | active |
| `IM_SOURCE_CONTRACT_INVALID` | `indexDetailMinutes` | error | false | false | 本地指数分钟文件不符合冻结物理合同 | Parquet schema、code、freq、日期、时间键、版本或路径校验失败 | 分钟模块 error；不返回可疑数据，不回退旧 Lake | biz-api | Phase-3 | active |
| `IM_QUERY_FAILED` | `indexDetailMinutes` | error | false | false | 本地指数分钟查询执行失败 | DuckDB、文件 IO 或结果校验异常 | 分钟模块 error；保留日线和右栏，允许局部重试 | biz-api | Phase-3 | active |

补充规则：

1. 分钟参数/cursor 非法继续使用 `ID_REQUEST_INVALID`；不新增同义 `IM_REQUEST_INVALID`。
2. 401/403 沿用认证层，不登记为业务 EMPTY。
3. MA 不登记 code/date 豁免；同 code 截至该交易日的实际有效历史根数小于 N 时，`maN=null` 才属于合理历史不足。达到 N 后仍为空必须触发 `ID_FACTOR_PARTIAL`。
4. page-init 与日线 K 线的量额唯一取 factor；不得读取或回退 daily 量额。factor 同日行/字段缺失时必须按 `ID_FACTOR_PARTIAL` 处理。
5. M5-A 的前端开发态 Mock 指标不产生、吞并或改写 `IM_*`；真实 Silver/Gold HTTP 状态仍按本表返回，Mock 不作为错误 fallback。

---

## 9. 变更规则

1. 已上线的 `code` 不允许重用为新语义。
2. 废弃码必须保留历史记录，`status=deprecated`，并补替代码。
3. 任何页面文档的异常码段落必须引用本文件，不再各写一套。
