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

> 当前已登记：榜单模块 + 今日市场客观总结模块 + 主要指数模块 + 市场风格模块 + 成交额总览模块 + 成交额洞察模块 + 指数成交额洞察模块 + 大盘资金流向模块 + 涨跌分布模块 + 涨跌停统计与分布模块 + 连板天梯模块 + 板块速览模块 + 新闻速览/新闻通讯模块。

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
| `TI_SOURCE_DELAYED` | `turnoverInsight` | warn | false | true | 成交额洞察使用了较早的完整相邻日期对 | expected 当日快照未 ready，但有界候选中存在质量合格的严格相邻日期对 | 模块显示 delayed 状态及实际数据日期 | biz-api | Phase-4 | active |
| `TI_CURRENT_SNAPSHOT_MISSING` | `turnoverInsight` | warn | false | true | 成交额洞察当前交易日快照缺失 | expected current 没有可用快照且不存在合法 delayed 日期对 | 模块显示 empty 状态 | biz-api | Phase-4 | active |
| `TI_PREVIOUS_SNAPSHOT_MISSING` | `turnoverInsight` | warn | false | true | 成交额洞察上一交易日快照缺失或不合格 | expected current 合格但 expected previous 缺失或质量失败 | 模块显示 partial，只展示当日曲线 | biz-api | Phase-4 | active |
| `TI_TIME_GRID_MISMATCH` | `turnoverInsight` | error | false | true | 成交额洞察分钟时间网格不符合合同 | 时间点不是严格唯一升序的 241 点，或两日时间键不一致 | 模块显示 partial/error，不渲染伪造对比 | biz-api | Phase-4 | active |
| `TI_POINT_QUALITY_INVALID` | `turnoverInsight` | error | false | true | 成交额洞察分钟点质量无效 | JSON、金额、日期、重复或尾值对账失败 | 模块显示 error，保留页面其它模块 | biz-api | Phase-4 | active |
| `TI_QUERY_FAILED` | `turnoverInsight` | error | false | true | 成交额洞察查询失败 | SQL 或未分类服务异常 | 模块显示 error，允许用户重试 | biz-api | Phase-4 | active |
| `TI_DAILY_AVERAGE_UNAVAILABLE` | `turnoverInsight` | warn | false | true | 成交额洞察日均值查询暂不可用 | 5 日/20 日成交额均值的有界交易日或日线聚合查询失败 | 保留分钟累计曲线与原状态；均值卡显示 `--`，不绘制均值参考线 | biz-api | Phase-4 | active |
| `ITI_SOURCE_NOT_READY` | `indexTurnoverInsight` | warn | false | true | 指数成交额洞察所需日期对或单指数必要日数据尚未就绪 | 预期 current/previous 分区或单指数必要行缺失，且对应范围没有合法可展示结果 | 整组不可用时显示 empty 并保留 10 卡占位；局部缺失时对应卡显示 partial/empty，不混用旧日期 | biz-api | Phase-4 | active |
| `ITI_SOURCE_DELAYED` | `indexTurnoverInsight` | warn | false | true | 指数成交额洞察使用了较早的完整相邻日期对 | 预期日期对整体不可用，但最近 4 个候选交易日中存在十指数全部完整的严格相邻日期对 | 整组显示 delayed、实际 observed 日期和固定 10 卡 | biz-api | Phase-4 | active |
| `ITI_SOURCE_CONTRACT_MISMATCH` | `indexTurnoverInsight` | error | false | true | 指数分钟 Gold 的全局读取合同不匹配 | 正式根/分区路径越界，必需 schema 缺失或类型不可安全转换，或 freq/分区日期合同冲突 | 整组显示 error；不降级读取其它 Lake、频率或数据源 | biz-api | Phase-4 | active |
| `ITI_CODE_SCOPE_MISMATCH` | `indexTurnoverInsight` | error | false | true | 指数分钟分区代码范围越过固定十指数合同 | 分区出现固定十指数集合之外的额外代码，或物理集合与冻结产品范围发生越界漂移 | 整组显示 error；不静默过滤额外代码，不改变固定顺序 | biz-api | Phase-4 | active |
| `ITI_TIME_GRID_MISMATCH` | `indexTurnoverInsight` | error | false | true | 单指数分钟时间网格不符合 1 分钟合同 | current/previous 任一日不是精确唯一升序 241 点、午休边界错误，或两日时间键不一致 | current 合法时对应卡可 partial；current 无效时该卡 error；其它合法卡继续展示 | biz-api | Phase-4 | active |
| `ITI_POINT_QUALITY_INVALID` | `indexTurnoverInsight` | error | false | true | 单指数分钟点质量无效 | amount 为空、非有限或负数，行内日期与分区/时间日期不一致，或唯一键重复 | 局部问题对应卡 partial/error；全局不可隔离问题整组 error，不填 0 | biz-api | Phase-4 | active |
| `ITI_AVERAGE_WINDOW_INCOMPLETE` | `indexTurnoverInsight` | warn | false | true | 单指数 5 日或 20 日均值窗口不足 | 截至实际 observed 日期不足精确 5 个或 20 个完整交易日 | 曲线和可用对比继续展示；不足均值显示 `--`，不绘制对应参考线，卡片 partial | biz-api | Phase-4 | active |
| `ITI_QUERY_FAILED` | `indexTurnoverInsight` | error | false | true | 指数成交额洞察查询或响应构建失败 | Calendar、DuckDB 查询或 DTO 组合发生未分类服务异常 | 整组显示 error，保留既有全市场成交额模块并允许重试 | biz-api | Phase-4 | active |
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
| `SO_COLUMN_METRIC_UNAVAILABLE` | `sectorOverview` | error | false | true | （历史）V1 板块速览列指标不可由冻结源产出 | V1 固定八列定义要求不存在的指标 | V2 已删除固定八列契约，不再产出 | biz-api | Phase-1 | deprecated |
| `SO_QUERY_FAILED` | `sectorOverview` | error | false | true | 板块速览查询失败 | SQL/服务异常 | 模块 error，保留其他模块渲染 | biz-api | Phase-1 | active |
| `SO_HIERARCHY_UNAVAILABLE` | `sectorOverview` | error | false | true | 行业层级 serving 不可用 | 层级表缺失、版本非法或父子闭包失败 | 行业视图 error，概念视图可独立保留 | biz-api | Phase-2 | active |
| `SO_SELECTION_INVALID` | `sectorOverview` | warn | false | true | 请求选择不属于当前候选路径 | 旧选择已不在当前父级或 Top 候选集合 | 按冻结默认路径纠正，debug 记录原因 | biz-api | Phase-2 | active |
| `SO_HEAT_NOT_READY` | `sectorOverview` | warn | false | true | 目标交易日概念热度未发布 | Heat serving 无同日成功快照 | 不回退其它排序，概念视图 partial | biz-api | Phase-2 | active |
| `SO_HEAT_SOURCE_MISMATCH` | `sectorOverview` | error | false | true | 热度来源日期与响应日期不一致 | sourceDates 任一必需源不等于 tradeDate | 拒绝消费该 Heat 行，模块 partial/delayed | biz-api | Phase-2 | active |
| `SO_MEMBER_COVERAGE_LOW` | `sectorOverview` | warn | false | true | 板块成分盘后行情覆盖不足 | 成员数小于 10 或有效行情覆盖率小于 80% | Heat 无效，详情保留并显示缺失 | biz-api | Phase-2 | active |
| `NEWS_CONFIG_MISSING` | `marketNews` | error | false | true | 新闻模块配置缺失 | 找不到新闻模块策略配置 | 模块 error，保留其它模块渲染 | biz-api | Phase-1 | active |
| `NEWS_CONFIG_INVALID` | `marketNews` | error | false | true | 新闻模块配置非法 | `visibleItemCount`、源配置或返回条数配置非法 | 模块 error，拒绝按非法配置输出 | biz-api | Phase-1 | active |
| `NEWS_SOURCE_EMPTY` | `marketNews` | warn | false | true | 新闻模块当前列表为空 | 对应接口的 `core_serving_light.news` 或 `core_serving_light.major_news` 无可展示项 | 当前板块 empty，debug 标记来源为空 | biz-api | Phase-1 | active |
| `NEWS_SOURCE_DELAYED` | `marketNews` | warn | false | true | 新闻模块源数据日期落后 | 目标日无数据但存在更早新闻 | debug delayed，不自动展示旧日新闻冒充当前日 | biz-api | Phase-1 | active |
| `NEWS_CHANNEL_RULE_INVALID` | `marketNews` | error | false | true | （历史）新闻频道分类规则不可用 | 首版曾依赖 `news.channels` 分流 | 新方案取消频道分流，不再产出 | biz-api | Phase-1 | deprecated |
| `NEWS_QUERY_FAILED` | `marketNews` | error | false | true | 新闻模块查询失败 | SQL/服务异常 | 模块 error，保留其他模块渲染 | biz-api | Phase-1 | active |
| `NEWS_READER_NOT_FOUND` | `marketNewsReader` | warn | false | false | 新闻详情不存在或已没有可读正文 | 指定 `contentSource + newsId` 不存在，或正文为空白 | 阅读器显示统一 empty 文案，不跨来源或按同标题回退 | biz-api | Phase-5 | active |
| `NEWS_READER_REQUEST_INVALID` | `marketNewsReader` | warn | false | false | 新闻详情来源或标识不符合有界合同 | 来源不是 `news/major_news`，或 `newsId` 不符合 URL-safe 规则 | 阅读器显示不可重试 error，不执行模糊查询或回退 | biz-api | Phase-5 | active |
| `NEWS_READER_CONTENT_INVALID` | `marketNewsReader` | error | false | false | 新闻正文类型或安全合同非法 | `news` 无法按 URL/HTML/TEXT 解析，或 `major_news` 无法按 HTML/TEXT 合同安全解析 | 阅读器显示统一 error 文案，不渲染可疑内容 | biz-api | Phase-5 | active |
| `NEWS_READER_CONTENT_TOO_LARGE` | `marketNewsReader` | error | false | false | 新闻正文超过阅读器有界载荷上限 | UTF-8 正文大于 `256 KiB` | 阅读器显示统一 error 文案，不截断冒充完整正文 | biz-api | Phase-5 | active |
| `NEWS_READER_QUERY_FAILED` | `marketNewsReader` | error | false | false | 新闻详情查询失败 | 主键查询或未分类服务异常 | 阅读器显示统一 error 文案，保留首页并允许重试 | biz-api | Phase-5 | active |

## 6.1 首页股票搜索模块（Phase-7）

| code | module | severity | userVisible | debugOnly | meaning | trigger | frontendAction | owner | phase | status |
|---|---|---|---|---|---|---|---|---|---|---|
| `SS_REQUEST_INVALID` | `stockSearch` | warn | false | false | 股票搜索请求不符合冻结合同 | keyword 为空或超长，或 limit 越界 | 保留输入并提示修正；不执行模糊查询或回退 | biz-api | Phase-7 | active |
| `SS_QUERY_FAILED` | `stockSearch` | error | false | false | 股票搜索查询或 DTO 组合失败 | 数据库、查询执行或响应映射出现未恢复异常 | 联想菜单显示统一 error；不调用 mock 或其它接口 | biz-api | Phase-7 | active |

## 6.2 我的自选模块（Phase-8）

> 本节只完成异常码合同登记；模块当前仍处于文档待评审、未实现状态。

| code | module | severity | userVisible | debugOnly | meaning | trigger | frontendAction | owner | phase | status |
|---|---|---|---|---|---|---|---|---|---|---|
| `WL_REQUEST_INVALID` | `watchlist` | warn | false | false | 自选请求不符合冻结合同 | tsCode、limit、afterId 或 tradeDate 非法 | 当前页面或弹窗显示不可重试的输入错误；不执行宽松回退 | biz-api | Phase-8 | active |
| `WL_STOCK_NOT_ELIGIBLE` | `watchlist` | warn | false | false | 添加目标不是当前上市 A 股 | security 不满足 EQUITY、L、CNY、SSE/SZSE/BSE 四项条件 | 保留列表和弹窗；提示仅支持当前上市 A 股 | biz-api | Phase-8 | active |
| `WL_QUERY_FAILED` | `watchlist` | error | false | false | 自选列表、数量、搜索或成员状态查询失败 | 数据库查询、页面上下文或 DTO 组合发生未恢复异常 | 只让对应列表、徽标、弹窗或详情动作进入 error；不回退 mock | biz-api | Phase-8 | active |
| `WL_WRITE_FAILED` | `watchlist` | error | false | false | 自选添加或删除事务失败 | 资格校验通过后，唯一约束之外的写入、提交或结果回读失败 | 保留操作前 UI 事实，解除 pending 并提示重试 | biz-api | Phase-8 | active |

## 7. 股票详情分钟模块（Phase-2）

| code | module | severity | userVisible | debugOnly | meaning | trigger | frontendAction | owner | phase | status |
|---|---|---|---|---|---|---|---|---|---|---|
| `SM_LOCAL_LAKE_NOT_CONFIGURED` | `stockDetailMinutes` | error | false | true | 本地分钟能力未完成运行配置 | 本地开关开启但 Lake root 不可读或 `local-lake` DuckDB 依赖不可用 | 本地启动失败；不以数据空态伪装 | app/biz-api | Phase-2 | active |
| `SM_SOURCE_NOT_READY` | `stockDetailMinutes` | warn | false | true | 分钟源数据尚未覆盖调用方期望日期 | 目标文件缺失、查询范围无文件，或 observed end 早于显式 `endDate` | HTTP 200；返回 `dataStatus=DELAYED`，保留页面其它内容 | biz-api | Phase-2 | active |
| `SM_SOURCE_CONTRACT_INVALID` | `stockDetailMinutes` | error | false | true | 分钟 Lake 文件不符合固定 schema/身份/时间键契约 | Parquet schema、代码、频率、日期或时间键校验失败 | 分钟模块 error；不返回可疑数据 | biz-api | Phase-2 | active |
| `SM_QUERY_FAILED` | `stockDetailMinutes` | error | false | true | 本地分钟查询执行失败 | DuckDB、文件读取或结果校验异常 | 分钟模块 error；保留股票身份、日线和右侧信息 | biz-api | Phase-2 | active |
| `SM_REQUEST_INVALID` | `stockDetailMinutes` | error | false | true | 分钟查询请求不合法 | 代码、频率、日期范围、cursor 或 limit 不合法 | HTTP 400；保留其它页面内容 | biz-api | Phase-2 | active |

---

## 7.1 股票日线趋势通道（M7，本地能力）

| code | module | severity | userVisible | debugOnly | meaning | trigger | frontendAction | owner | phase | status |
|---|---|---|---|---|---|---|---|---|---|---|
| `STOCK_TREND_CHANNEL_SOURCE_NOT_READY` | `stockDetailTrendChannel` | warn | false | true | 本地股票趋势通道正式事实尚不可安全读取 | 正式 result/state 根缺失或不可读、目标分区缺文件、Parquet/schema/公式版本/日期唯一性合同不一致 | route 未挂载时不展示入口；已挂载后的局部请求返回 HTTP 503，保留 K 线与其它图层 | foundation/biz-api | M7 | active |
| `STOCK_TREND_CHANNEL_READ_FAILED` | `stockDetailTrendChannel` | error | false | false | 本地股票趋势通道有界查询执行失败 | DuckDB 或文件 IO 在已通过 capability 与源合同门禁后执行失败 | 趋势通道局部 error，不影响 K 线、九转、MA/BOLL | foundation/biz-api | M7 | active |

---

## 8. 指数详情模块（Phase-3）

> 正式日线 DTO 语义见 [指数详情页正式 API / DTO 合同 v1](../pages/index-detail/index-detail-api-contract-v1.md)。`ID_*` 服务正式日线详情；`IM_*` 服务已启用的 local/dev 指数分钟独立合同，具体语义见 [指数详情本地分钟 API / DTO 合同 v1](../pages/index-detail/index-detail-minutes-api-contract-v1.md)。

| code | module | severity | userVisible | debugOnly | meaning | trigger | frontendAction | owner | phase | status |
|---|---|---|---|---|---|---|---|---|---|---|
| `ID_REQUEST_INVALID` | `indexDetail` | error | false | false | 指数详情请求不合法 | code/date/period/limit/debug/cursor 等参数无法按冻结合同解析 | HTTP 400；请求错误壳或分钟局部错误，不继续派发后续请求 | biz-api | Phase-3 | active |
| `ID_NOT_FOUND` | `indexDetail` | warn | false | false | 指数不属于详情页正式名单或身份缺失 | code 不属于 `majorIndices/CN_A` 10 code，或名单内 code 无基础身份 | HTTP 404；全页 not-found 壳，返回指数首页 | biz-api | Phase-3 | active |
| `ID_SOURCE_EMPTY` | `indexDetailPageInit` | warn | false | true | 指数正式日线无可用观测行 | `index_daily_serving` 在期望日期及之前无该 code 行 | HTTP 200 + EMPTY；保留身份、工具栏和右栏空态 | biz-api | Phase-3 | active |
| `ID_SOURCE_DELAYED` | `indexDetailPageInit` | warn | false | true | 指数正式日线落后于期望交易日 | `observedTradeDate < expectedTradeDate` 且没有更高优先级 partial 原因 | HTTP 200 + DELAYED；保留数据并展示实际日期 | biz-api | Phase-3 | active |
| `ID_FACTOR_PARTIAL` | `indexDetail` | warn | false | true | 指数详情因子字段部分缺失 | page-init 同日 factor 行/量额缺失，factor 最新日落后，可绘制 bar 的 factor 量额缺失，MA 在实际有效历史已达到对应周期后仍为空，或其它预期技术因子缺失 | HTTP 200 + PARTIAL；基本行情量额 `--`，保留 K 线并让缺线断点 | biz-api | Phase-3 | active |
| `ID_BASIC_DAILY_PARTIAL` | `indexDetailPageInit` | warn | false | true | 基本行情日度指标部分缺失 | 同日 `index_daily_basic` 无行，或 PE/PE TTM/PB/换手率/流通市值/总市值任一为空 | 对应指标显示 `--`，其它基本行情保留，页面 PARTIAL | biz-api | Phase-3 | active |
| `ID_BASIC_BREADTH_PARTIAL` | `indexDetailPageInit` | warn | false | true | A 股成分涨跌统计存在真实行情缺口 | 有有效权重批次，且页面 A 股子集中某成分同日既无有效 daily `pct_chg`，也无 `suspend_type='S'` 停牌证据，导致 `missingCount > 0` | 保留 up/flat/down 与 coverage，页面 PARTIAL；B 股排除和已证实停牌不触发，真实 missing 不计 flat | biz-api | Phase-3 | active |
| `ID_WEIGHT_EMPTY` | `indexDetailWeights` | warn | false | true | 指数没有可用权重批次 | `max(weight.trade_date) <= contributionTradeDate` 无结果 | 权重 Tab EMPTY；不影响主图和基本行情 | biz-api | Phase-3 | active |
| `ID_WEIGHT_CONTRIBUTION_PARTIAL` | `indexDetailWeights` | warn | false | true | 部分 A 股权重行无法计算估算贡献点 | index preClose 缺失，或页面 A 股成分同日既无有效 daily `pct_chg` 也无停牌证据 | 行保留，贡献显示 `--`，coverage 记录缺失，权重 Tab PARTIAL；已证实停牌输出贡献 0，不触发 | biz-api | Phase-3 | active |
| `ID_QUERY_FAILED` | `indexDetail` | error | false | false | 指数详情配置、查询或映射失败 | universe 配置缺失/非法、SQL、服务或 DTO 映射出现未恢复异常 | HTTP 500 或当前 Tab 局部 error；允许重试，不用 mock/fallback 冒充成功 | biz-api | Phase-3 | active |
| `IM_SOURCE_NOT_READY` | `indexDetailMinutes` | warn | false | true | 本地指数分钟源尚未覆盖请求范围 | 正式 Lake 分区/文件缺失，或 observed end 早于请求 endDate | HTTP 200 + DELAYED/EMPTY；保留日线和其它页面内容 | biz-api | Phase-3 | active |
| `IM_SOURCE_CONTRACT_INVALID` | `indexDetailMinutes` | error | false | false | 本地指数分钟文件不符合冻结物理合同 | Parquet schema、code、freq、日期、时间键、版本或路径校验失败 | 分钟模块 error；不返回可疑数据，不回退旧 Lake | biz-api | Phase-3 | active |
| `IM_QUERY_FAILED` | `indexDetailMinutes` | error | false | false | 本地指数分钟查询执行失败 | DuckDB、文件 IO 或结果校验异常 | 分钟模块 error；保留日线和右栏，允许局部重试 | biz-api | Phase-3 | active |

补充规则：

1. 分钟参数/cursor 非法继续使用 `ID_REQUEST_INVALID`；不新增同义 `IM_REQUEST_INVALID`。
2. 401/403 沿用认证层，不登记为业务 EMPTY。
3. MA 不登记 code/date 豁免；同 code 截至该交易日的实际有效历史根数小于 N 时，`maN=null` 才属于合理历史不足。达到 N 后仍为空必须触发 `ID_FACTOR_PARTIAL`。
4. page-init 与日线 K 线的量额唯一取 factor；不得读取或回退 daily 量额。factor 同日行/字段缺失时必须按 `ID_FACTOR_PARTIAL` 处理。
5. M5-A 的前端开发态 Mock 已于 M5-B 删除。当前 bars 与 indicators 均只读正式 Gold；任何 `IM_*` 异常都不得触发 Mock、Silver、旧 Lake 或其它频率/指数缓存 fallback。
6. 指数详情的“完整权重批次”指官方批次中由 `Security.security_type=EQUITY`、`exchange in (SSE,SZSE,BSE)`、`curr_type=CNY` 认定的完整 A 股子集。B 股不进入 rows/coverage/total/missing；A 股 daily 值优先，只有 daily 缺失/空值且精确日 `EquitySuspendD.suspend_type='S'` 时才按 FLAT/贡献 0 解析。

## 9. 九转详情图层（Phase-4，股票与指数后端及 UI active）

> 最终 DTO、状态优先级和恢复动作见 [股票与主要指数详情页九转接入低层设计 v1](./detail-page-nine-turn-integration-low-level-design-v1.md)。股票日线、本地 30/60/90/120 分钟及指数日线、本地 5/15/30/60/90/120 分钟后端、正式数据和页面消费均已落地；M6-A～M6-D 的生产发布、自然更新与最终运维验收已于 2026-08-22 全部完成。异常码语义不因阶段收口而改变。

| code | module | severity | userVisible | debugOnly | meaning | trigger | frontendAction | owner | phase | status |
|---|---|---|---|---|---|---|---|---|---|---|
| `NT_REQUEST_INVALID` | `detailNineTurn` | error | false | false | 九转查询参数不合法 | 未知/重复参数、code/period/date/limit/cursor 或响应窗口非法 | HTTP 400；不重试，保留已加载页面与 K 线 | biz-api | Phase-4 | active |
| `NT_NOT_FOUND` | `detailNineTurn` | warn | false | false | 请求标的不属于对应详情页对象池 | 股票身份不存在，或指数不属于运行时 `majorIndices/CN_A` 10 code | HTTP 404；沿用对应详情页 not-found 行为 | biz-api | Phase-4 | active |
| `NT_SOURCE_NOT_READY` | `detailNineTurn` | warn | false | true | 九转事实尚未覆盖请求窗口 | bar 窗口存在但九转零匹配，或观测日期落后显式 endDate | HTTP 200 + EMPTY/DELAYED；九转局部空态/延迟，不回退 | biz-api | Phase-4 | active |
| `NT_SOURCE_CONTRACT_INVALID` | `detailNineTurn` | error | false | false | 九转 Lake/serving 不符合冻结物理合同 | schema、路径、代码、周期、日期、唯一键、公式版本或值域违约 | HTTP 500；九转局部 error，不返回可疑 marker | foundation/biz-api | Phase-4 | active |
| `NT_ALIGNMENT_PARTIAL` | `detailNineTurn` | warn | false | true | 九转与同窗口 K 线时间键部分不一致 | bar 窗口中只有部分时间键能连接九转事实 | HTTP 200 + PARTIAL；只画已确认 marker，显示局部缺失 | biz-api | Phase-4 | active |
| `NT_QUERY_FAILED` | `detailNineTurn` | error | false | false | 九转查询执行失败 | PostgreSQL、DuckDB、文件 IO、DTO 映射或未知内部异常 | HTTP 500；保留 K 线和其它图层，允许九转局部重试 | foundation/biz-api | Phase-4 | active |

补充规则：

1. 股票、指数、日线和分钟使用相同 `NT_*`，因为恢复动作一致；subject/period/source 由 DTO 与 debug meta 区分。
2. 窗口有完整九转事实但没有 count 1～9 时仍为 READY，`markers=[]`；前端可派生“当前窗口无标记”视觉，不产生异常码。
3. 股票 1/5/15 分钟与指数 1 分钟在前端为 UNSUPPORTED 且零请求；若直接调用非法 minute endpoint，使用 `NT_REQUEST_INVALID`。
4. `899050.BJ` 分钟使用 `NT_SOURCE_NOT_READY`，不得补造；`000680.SH` 使用 `NT_NOT_FOUND`。
5. 401/403 继续由认证层提供，不登记同义九转业务码。

---

## 10. 财势量化平台（QTF M3）

| code | module | severity | userVisible | debugOnly | meaning | trigger | frontendAction | owner | phase | status |
|---|---|---|---|---|---|---|---|---|---|---|
| `QTF_REQUEST_INVALID` | `quantPlatform` | error | true | false | 请求、参数或日期合同非法 | 请求字段、完整参数或日期范围不符合冻结合同 | 保留当前输入并提示修正 | qtf/app | M3 | active |
| `QTF_TEMPLATE_NOT_FOUND` | `quantPlatform` | error | true | false | 模板、公式或参数合同不存在或未激活 | 请求引用未注册身份或版本 | 阻止创建或冻结并刷新模板 | qtf/app | M3 | active |
| `QTF_STATE_CONFLICT` | `quantPlatform` | error | true | false | 当前研究状态不允许该动作 | 对非 DRAFT 编辑、非 FROZEN 启动等 | 刷新最新状态 | qtf/app | M3 | active |
| `QTF_DRAFT_CONFLICT` | `quantPlatform` | error | true | false | 草稿版本或内容哈希已变化 | 旧页面保存、预检或冻结覆盖新内容 | 禁止覆盖并重新加载 | qtf/app | M3 | active |
| `QTF_INPUT_PREFLIGHT_BLOCKED` | `quantPlatform` | warn | true | false | 本次输入不满足研究门禁 | 精确对象池或日期范围存在来源、完整性或小组问题 | 展示问题和上游责任，不启动 | qtf/app | M3 | active |
| `QTF_PLAN_NOT_APPROVED` | `quantPlatform` | error | true | false | PLAN 未确认或已变化 | plan hash 缺失、过期或与服务器重算不一致 | 返回计划页重新确认 | qtf/app | M3 | active |
| `QTF_PLAN_BUDGET_EXCEEDED` | `quantPlatform` | error | true | false | 实际工作量超过本 Run 获批预算 | 来源行数、组日、组合、耗时、内存或产物越界 | 在安全点停止并重新审批 | qtf/app | M3 | active |
| `QTF_INPUT_CHANGED_DURING_RUN` | `quantPlatform` | error | true | false | Run 重读输入与已批准内容不一致 | RUN_PREFLIGHT 内容指纹变化 | 结束当前 Run 并新建 Run | qtf/app | M3 | active |
| `QTF_RUN_FAILED` | `quantPlatform` | error | true | false | 回测执行程序失败 | 公式或执行主链出现未恢复异常 | 展示简要原因，可新建 Run | qtf/app | M3 | active |
| `QTF_VALIDATION_INVALID` | `quantPlatform` | warn | true | false | 执行完成但可信门禁失败 | M4 验证结果为 INVALID | 禁止提名，保留证据 | qtf/app | M4 | active |
| `QTF_VALIDATION_INSUFFICIENT` | `quantPlatform` | warn | true | false | 研究样本不足 | M4 验证结果为 INSUFFICIENT | 禁止提名，可保留观察 | qtf/app | M4 | active |
| `QTF_RELEASE_CONFLICT` | `quantPlatform` | error | true | false | 候选或发布状态冲突 | M8 审核、批准或替代关系不合法 | 保留当前 release 并刷新 | qtf/app | M8 | active |
| `QTF_QUERY_FAILED` | `quantPlatform` | error | true | false | 未分类查询或服务异常 | 数据库或服务出现未分类失败 | 页面错误态，可重试 | qtf/app | M3 | active |

401/403 继续复用认证层，不新增 QTF 用户、角色或权限码。

## 11. 财势探查板块分析（Phase-6，编码前已登记）

| code | module | severity | userVisible | debugOnly | meaning | trigger | frontendAction | owner | phase | status |
|---|---|---|---|---|---|---|---|---|---|---|
| `SA_SOURCE_DELAYED` | `sectorAnalysis` | warn | false | true | 默认目标交易日当前行业池来源覆盖未达到 COMPLETE，使用最近 COMPLETE 盘后日 | 默认请求的 `expectedAvailability in {PARTIAL, MISSING}` 且 `observedTradeDate < expectedTradeDate` | 保留最近完整榜单和趋势，明确提示实际盘后日期及目标日覆盖状态 | biz-api | Phase-6 | active |
| `SA_SOURCE_EMPTY` | `sectorAnalysis` | warn | false | true | 显式 MISSING 日期没有行业行情，或当前比较池在所选周期下全部不可计算 | 显式日期 `expectedAvailability=MISSING`，或 `calculableCount=0` | 稳定 EMPTY；不回退旧日、不补零，缺口日期仍保留在选择器 | biz-api | Phase-6 | active |
| `SA_HIERARCHY_UNAVAILABLE` | `sectorAnalysis` | error | false | true | 当前行业层级不可用于建立比较池 | 层级为空、多版本、重复代码、父级或 root 闭包非法 | 稳定 ERROR；禁止前端猜测层级或默认项 | biz-api | Phase-6 | active |
| `SA_SCOPE_INVALID` | `sectorAnalysis` | warn | false | false | 比较范围、父级或固定枚举不符合合同 | scope 与父级参数错层、跨父级、缺失或使用未批准枚举 | HTTP 400；保留当前输入并修正 URL/选择 | biz-api | Phase-6 | active |
| `SA_SELECTION_INVALID` | `sectorAnalysis` | warn | false | false | 选中行业不属于当前比较池 | `sectorCode` 不在当前 scope 与父级解析出的对象池 | HTTP 400；不得静默替换为另一行业 | biz-api | Phase-6 | active |
| `SA_FACT_VERSION_MISMATCH` | `sectorAnalysis` | warn | false | false | 板块分析方法的结果请求携带的行业层级版本与当前发布版本不一致 | 双动量或相对轮动 Meta 返回后层级重新发布，或客户端使用过期 hierarchyVersion 请求对应 Results | HTTP 409；丢弃当前方法的 Meta/Results 短期事实并从该方法 Meta 重新加载；不得继续读取行情 | biz-api | Phase-6-M5/M9 | active |
| `SA_MEMBER_FACT_MISMATCH` | `sectorAnalysis` | warn | false | false | 成员请求携带的行业层级版本与当前发布版本不一致 | rankings 返回后层级重新发布，或客户端使用过期 hierarchyVersion | HTTP 409；丢弃当前 meta/rankings/history/members 短期事实并从 meta 重新加载 | biz-api | Phase-6-M3A | active |
| `SA_MEMBER_SOURCE_EMPTY` | `sectorAnalysis` | warn | false | true | 目标交易日所选三级行业没有来源成员 | 精确 `tradeDate + sectorCode` 的 dc_member 来源集合为空 | 只在成员下半区显示 EMPTY；上方行业榜单和右侧详情继续可用 | biz-api | Phase-6-M3A | active |
| `SA_MEMBER_QUERY_FAILED` | `sectorAnalysis` | error | false | true | 成员关系、股票日行情或成员收益合同处理失败 | SQL、重复业务键、窗口、Decimal 计算或 DTO 不变量失败 | 只在成员下半区显示 ERROR 并重试 members；不清空整页事实 | biz-api | Phase-6-M3A | active |
| `SA_BREADTH_FACT_MISMATCH` | `sectorAnalysis` | warn | false | false | 成员广度请求携带的行业层级版本与当前发布版本不一致 | 成员广度 Meta 返回后层级重新发布，或客户端使用过期 hierarchyVersion | HTTP 409；只清空成员广度事实并重新加载成员广度 Meta | biz-api | Phase-6-M14 | active |
| `SA_BREADTH_SOURCE_EMPTY` | `sectorAnalysis` | warn | false | true | 选中行业在目标交易日没有来源成员 | 精确 `tradeDate + sectorCode` 的成员广度来源集合为空 | Details 局部 EMPTY；排名和页面骨架保留 | biz-api | Phase-6-M14 | active |
| `SA_BREADTH_QUERY_FAILED` | `sectorAnalysis` | error | false | true | 成员广度查询、纯计算或合同组合失败 | SQL、重复业务键、窗口、Decimal 计算或 DTO 不变量失败 | 当前成员广度 endpoint 进入安全 ERROR；不泄露技术细节 | biz-api | Phase-6-M14 | active |
| `SA_PRICE_VOLUME_FACT_MISMATCH` | `sectorAnalysis` | warn | false | false | 量价分布请求携带的行业层级版本与当前发布版本不一致 | 量价分布 Meta 返回后层级重新发布，或客户端使用过期 hierarchyVersion 请求 Snapshot／Details | HTTP 409；只清空量价分布短期事实并重新加载量价分布 Meta；不得继续读取行情 | biz-api | Phase-6-M17 | active |
| `SA_QUERY_FAILED` | `sectorAnalysis` | error | false | true | 板块分析查询或纯计算出现未分类失败 | SQL、日期窗口、结果唯一性、DTO 组合或未知内部异常 | 稳定 ERROR；安全文案和重试，不展示不完整结果 | biz-api | Phase-6 | active |
| `SA_DAILY_INSIGHT_BATCH_MISMATCH` | `sectorAnalysis` | warn | false | false | 每日洞察请求的已发布批次与当前可见批次不一致 | Meta 返回后批次被同日新发布代次替换，或客户端携带过期 batchKey 请求 Snapshot | HTTP 409；只清空每日洞察短期事实并重载 Meta 一次 | biz-api | Phase-6-M25 | active |
| `SA_DAILY_INSIGHT_QUERY_FAILED` | `sectorAnalysis` | error | false | true | 每日洞察只读查询或响应组合失败 | PUBLISHED 批次、summary、item 或 DTO 组合出现未恢复异常 | HTTP 500；保持稳定 Error，安全重试当前链路 | biz-api | Phase-6-M25 | active |
| `SA_DAILY_FACT_SOURCE_NOT_READY` | `sectorAnalysis` | warn | false | true | 每日事实所需生产来源尚未达到单日物化门禁 | 上游维护节点、层级、行业行情、成员、股票行情或复权事实未齐 | 仅记录 TaskRun/readiness；零公式执行、零新批次 | biz/ops | Phase-6-M22 | active |
| `SA_DAILY_FACT_READBACK_MISMATCH` | `sectorAnalysis` | error | false | true | 新建每日事实批次的逐表回读与期望不一致 | 计数、业务键、日期、内容 hash 或复合外键核验失败 | 仅记录 TaskRun；新批次标记 FAILED，旧 PUBLISHED 继续服务 | biz/ops | Phase-6-M22 | active |
| `SA_DAILY_FACT_PLAN_DRIFT` | `sectorAnalysis` | error | false | true | 历史回补 APPLY 与已确认 PLAN 发生漂移 | 日期清单、层级版本、公式包、模板、参数或 expected hash 变化 | 拒绝执行漂移计划，保留既有已发布事实 | biz/ops | Phase-6-M23 | active |

补充规则：

1. 前端 LOADING 是请求态，不登记业务异常码。
2. `PARTIAL` 只作为交易日来源覆盖元数据，不是页面状态或异常码。显式 PARTIAL 日期仍使用 READY 骨架，个别行业缺失时行保留并显示 `--`；只有当前比较池全部不可计算时使用 `SA_SOURCE_EMPTY`。
3. 401/403 继续复用认证层，不新增同义 `SA_*`。
4. `SA_MEMBER_SOURCE_EMPTY/SA_MEMBER_QUERY_FAILED` 只作用于成员下半区，不得升级为整页 EMPTY/ERROR；`SA_MEMBER_FACT_MISMATCH` 必须重新加载全部页面事实，禁止局部重试后拼接不同层级版本。
5. `SA_FACT_VERSION_MISMATCH` 只用于双动量和相对轮动 Results 的页面级层级版本冲突；前端只丢弃并重载当前方法的 Meta/Results。它与成员局部请求使用的 `SA_MEMBER_FACT_MISMATCH` 恢复范围不同，不得互相替代。版本不一致必须在行业行情查询前返回 409。
6. `SA_BREADTH_SOURCE_EMPTY/SA_BREADTH_QUERY_FAILED` 只作用于成员广度 Details 或当前 Rankings；个别股票和单项指标缺失只返回覆盖率与原因，不升级成技术异常。`SA_BREADTH_FACT_MISMATCH` 只重载成员广度事实，不清空其它板块分析方法。

## 12. 变更规则

1. 已上线的 `code` 不允许重用为新语义。
2. 废弃码必须保留历史记录，`status=deprecated`，并补替代码。
3. 任何页面文档的异常码段落必须引用本文件，不再各写一套。
