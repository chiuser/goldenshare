# 市场总览｜板块速览标杆需求 v2（benchmark-requirement）

> 状态：M1 方案评审稿，未授权进入业务编码。
> 页面定位：财势乾坤首页盘后事实模块，不使用实时行情。
> 替换范围：V2 上线后替换现有 `4 × 2` 榜单矩阵与 `5 × 4` 涨跌热力图；上线前 v1 文档仍用于解释当前代码，不得继续扩展 v1。

---

## 1. 目标与依据

### 1.1 模块目标

1. 行业板块按东方财富一级、二级、三级行业关系分层排名，消除不同层级混排造成的主次混乱。
2. 行业、概念和地域排名项均突出板块名称、核心指标与领涨股，不再只展示扁平名称和数值。
3. 概念板块同时回答“当日有多热、较上一交易日升温还是降温、内部有哪些股票”。
4. 地域板块作为第三个独立视图平铺排名，不并入行业三级关系，也不套用概念热度标签。
5. 所有排序、层级、热度、有效 A 股成分池和降级规则由后端产出，前端不推导事实。

### 1.2 已确认设计稿

Figma 文件：`Goldenshare Web`（file key `RADlZzREU4lPVviYfkLy6x`）。

| 设计对象 | 节点 ID | 用途 |
|---|---|---|
| 正式交付页 | `538:517` | `Sector Overview V2 / Formal Delivery` |
| 行业模块 | `538:520` | 三级联动排名与行业详情 |
| 概念模块 | `538:521` | 概念热度排名与概念详情 |
| 地域模块 | `571:516` | 31 个地域板块独立排名与地域详情 |
| 交互与数据口径 | `538:522` | 交互、字段与状态说明 |
| Heat Model V1 | `554:516` | 热度权重、阈值、趋势与质量门禁 |

行业、概念和地域三个关键画板基线均为 `1564 × 680`。Web 落地时允许板块速览模块高度增加，但不得改变首页其它模块、左右栏和页面主宽度。

### 1.3 已确认产品结论

1. 默认 Tab 为“行业”，可切换到“概念”或“地域”；三个视图各自保留排序与选择状态。
2. 行业展示一级、二级、三级三列联动排名；每列固定 5 个可见排名项。
3. 行业排名维度固定为：`涨跌幅`、`主力净流入`、`上涨家数`。
4. 概念排名维度固定为：`综合热度`、`热度变化`、`涨跌幅`、`主力净流入`。
5. 地域固定为 31 个地域板块独立平铺，排名维度固定为：`涨跌幅`、`主力净流入`、`上涨家数`；不建立地域父子层级。
6. 行业、概念和地域详情均展示核心指标、领涨股与成分股速览；地域详情额外展示同日成分涨跌分布。
7. 概念详情展示最近 20 个已发布交易日的热度历史，用于解释持续升温或降温，不用于预测。
8. 热度等级使用：`沸腾`、`高热`、`活跃`；低于 60 分不展示等级标签。
9. 热度趋势使用：`升温`、`平稳`、`降温`，趋势不作为独立热度等级。
10. Heat Model EOD V1 作为首版口径；首次发布前纳入本文件的有效 A 股成分池定义，首次发布后任何口径调整必须发布新的 `scoreVersion`。
11. 首页当前以盘后数据为主；V2 不建设分钟刷新、盘中估算、实时行情或 Redis 热度快照。

### 1.4 已完成的盘后口径同步

Figma 正式页已在进入编码前完成以下同步，后续实现不得回退旧分钟口径：

| 原 Figma 口径 | 正式开发口径 |
|---|---|
| `heat_delta_20m` | `heat_delta_1d`，当日热度减前一交易日热度 |
| 日内加速度 | 日度加速度，`pctChange(t) - pctChange(t-1)` |
| 20 分钟趋势 | 较前一交易日趋势 |
| `freshness <= 5m` | 所有必需源完成同一目标交易日 |
| 分钟刷新 | 每个交易日收盘后成功物化一次 |

上述同步已落在正式节点 `538:517/538:521/554:516`；不允许前端与后端各做一套兼容。

---

## 2. 范围与边界

### 2.1 本期覆盖

1. 首页板块速览模块的 V2 视觉与交互替换。
2. 行业一级、二级、三级层级事实、同层排名和父子联动。
3. 行业、概念与地域领涨股展示。
4. 行业、概念与地域成分股 Top5 速览。
5. 概念 Heat Model EOD V1、热度等级、日度变化和趋势标签。
6. 地域 31 个板块独立排行与同日成分涨跌分布。
7. 热度计算使用目标交易日有效 A 股成分池与停牌感知的可报价池。
8. `Loading / Empty / Error / Partial / Delayed / Forbidden` 稳定骨架。
9. 模块真实 API、盘后热度物化表和正式数据质量门禁。

### 2.2 本期不覆盖

1. 不建设板块详情页；“进入板块行情”仍属于后续路由能力。
2. 不建设用户自定义权重、阈值、榜单列或排名数量。
3. 不接入 THS 板块体系，也不混排 DC 与 THS 分类。
4. 不保留旧 `columns/heatMapItems` DTO、旧字段别名或旧布局兼容层。
5. 不在浏览器计算热度、层级、领涨股或成分股排序。
6. 不把热度标签解释为投资建议、买卖信号或未来走势预测。
7. 不在 API 请求链路直接调用 Tushare，也不在 Web 请求中读取 DG Lake Parquet。
8. 不使用实时行情、分钟行情、盘中资金流估算或 Redis 作为事实源。
9. 不在本轮改动首页其它模块或指数详情页。

### 2.3 模块边界

1. DG 负责行业层级资产的生成、校验与 serving 发布。
2. `foundation` 负责正式盘后行情、成分与持久化模型契约。
3. `ops` 只承接盘后物化意图、运行状态与失败观测，不参与公式计算。
4. `biz` 负责热度物化业务规则、板块查询、排名、选择路径、状态归并与 API DTO。
5. `app` 只负责运行时装配，不承载热度业务规则。
6. `wealth` 前端只负责交互状态、请求和视觉表达。

---

## 3. 核心原则（硬约束）

1. 层级事实单一：行业父子关系唯一来自 DG `silver_dc_industry_hierarchy` 的 serving 投影，不从名称、`dc_index.level` 或前端路径猜测。
2. 行情事实单一：板块盘后指标按字段分别来自 `dc_index`、`dc_daily`、`board_moneyflow_dc`。
3. 成分事实单一：行业、概念和地域的原始成员唯一来自同一观测交易日的 `dc_member`。
4. 热度事实单一：`heatScore/heatLevel/heatDelta1d/heatTrend` 仅从盘后物化表读取，API 不临时计算。
5. 领涨股事实单一：板块领涨股来自 `dc_index.leading/leading_code/leading_pct`；缺失时不允许用成分股第一名冒充。
6. 排名确定性：每种排名固定主排序、空值规则和稳定次排序，同分最终按 `sectorCode asc`。
7. 不静默补权：热度关键输入缺失时不得把剩余权重重新归一化。
8. 版本可追溯：热度返回 `scoreVersion`、`tradeDate` 和 `calculatedAt`；公式变化必须升版本。
9. 交易日一致：一个响应不得混用不同交易日的行情、成分、资金流和热度。
10. A 股颜色语义保持红涨绿跌。
11. 有效池事实单一：证券资格只由 `security_serving` 的证券类型、交易币种和上市/退市日期边界判定；停牌只由同日 `equity_suspend_d` 判定，不按代码前缀或行情是否存在猜测。
12. 停牌不算缺行情：停牌成员保留在有效 A 股成分池中，但从可报价池分母扣除；其状态单独记录。
13. 用户可见结果优先：验收覆盖名称、主指标、领涨股、成分股、层级联动、地域排行和热度标签，不以 JSON 有字段代替页面验收。
14. Heat 来源只认 prod：行情、成员、资金、证券资格、停牌、涨停与前序 Heat 全部读取生产 PostgreSQL 正式表；DG/Lake 不参与 Heat 计算、回放或 API 查询。

---

## 4. 业务对象模型

### 4.1 行业节点 `IndustrySector`

| 字段 | 语义 | 可空 | 缺失策略 |
|---|---|---:|---|
| `sectorCode` | DC 板块代码 | 否 | 缺失节点不进入结果 |
| `sectorName` | 行业名称 | 否 | 缺失节点不进入结果 |
| `level` | 行业等级 `1/2/3` | 否 | 非法等级视为层级契约失败 |
| `parentCode` | 直接父级代码 | 一级可空 | 二、三级缺失则层级不可用 |
| `rootCode` | 一级根行业代码 | 否 | 缺失则层级不可用 |
| `hierarchyPath` | 完整中文路径 | 否 | 仅展示，不用于反推关系 |
| `displayOrder` | 稳定目录顺序 | 否 | 只作最终稳定排序辅助 |

### 4.2 板块指标 `SectorMetrics`

| 字段 | 单位 | 可空 | 说明 |
|---|---:|---:|---|
| `changePct` | `%` | 是 | 板块涨跌幅 |
| `upCount` | 家 | 是 | 上涨成分数 |
| `downCount` | 家 | 是 | 下跌成分数 |
| `sourceMemberCount` | 家 | 否 | `dc_member` 同日去重原始成分数 |
| `memberCount` | 家 | 否 | 目标交易日有效 A 股成分数 |
| `suspendedCount` | 家 | 否 | 有效池中当日 `suspend_type='S'` 的成员数 |
| `quoteEligibleCount` | 家 | 否 | `memberCount - suspendedCount` |
| `validQuoteCount` | 家 | 否 | 可报价池中存在非空 `close/pct_chg` 的成员数 |
| `missingQuoteCount` | 家 | 否 | `quoteEligibleCount - validQuoteCount` |
| `mainNetInflow` | 元 | 是 | DC 正式盘后主力净流入 |
| `turnoverAmount` | 元 | 是 | 板块成交额 |
| `quoteCoverage` | `0..1` | 是 | `validQuoteCount / quoteEligibleCount`；分母为 0 时为空 |

### 4.3 领涨股 `SectorLeaderStock`

| 字段 | 可空 | 说明 |
|---|---:|---|
| `stockCode` | 是 | 领涨股票代码 |
| `stockName` | 是 | 领涨股票名称 |
| `changePct` | 是 | 领涨股票涨跌幅 |

三字段全部为空时返回 `null`。前端不得用成分股榜首替代。

### 4.4 成分股速览 `SectorMemberStock`

| 字段 | 可空 | 说明 |
|---|---:|---|
| `stockCode` | 否 | 成分股代码 |
| `stockName` | 是 | `dc_member.name` |
| `changePct` | 是 | 同一交易日的股票涨跌幅 |
| `direction` | 否 | `UP/DOWN/FLAT/UNKNOWN` |

详情固定返回最多 5 行，按 `changePct desc nulls last, stockCode asc` 排序。

### 4.5 概念热度 `ConceptHeat`

| 字段 | 范围 | 可空 | 缺失策略 |
|---|---:|---:|---|
| `heatScore` | `0..100` | 是 | 不满足质量门禁时为 `null` |
| `heatLevel` | `BOILING/HOT/ACTIVE/NONE` | 否 | 分数为空或 `<60` 为 `NONE` |
| `heatDelta1d` | 分值 | 是 | 缺少前一交易日合法快照时为空 |
| `heatTrend` | `HEATING/STABLE/COOLING/UNKNOWN` | 否 | 历史不足为 `UNKNOWN` |
| `heatRank` | 正整数 | 是 | 当日有效概念横截面名次 |
| `heatStatus` | `VALID/INVALID` | 否 | 质量门禁结论 |
| `invalidReason` | 原因码 | 是 | 无效时记录固定原因，不用自由文本替代 |
| `scoreVersion` | 版本 | 否 | 首版固定 `concept-heat-eod-v1` |
| `tradeDate` | 日期 | 否 | 热度对应交易日 |
| `calculatedAt` | 时间戳 | 否 | 盘后物化完成时间 |

### 4.6 有效 A 股成分池 `EffectiveAStockPool`

对每个板块、每个目标交易日按以下固定顺序生成：

1. 从同日 `dc_member` 按 `(ts_code, con_code)` 去重得到原始成员。
2. 精确关联 `security_serving.ts_code`，仅保留 `security_type='EQUITY'`、`curr_type='CNY'`、`list_status IN ('L','D')`、`list_date <= tradeDate` 且 `(delist_date IS NULL OR delist_date > tradeDate)` 的证券；B 股、尚未上市、已退市成员不进入有效池。
3. 关联同日 `equity_suspend_d`；`suspend_type='S'` 的成员计入 `memberCount/suspendedCount`，但不进入 `quoteEligibleCount`。
4. 可报价池中，同日 `equity_daily_bar.close` 与 `pct_chg` 均非空才计入 `validQuoteCount`；其余为真实行情缺失。
5. `quoteCoverage = validQuoteCount / quoteEligibleCount`；`quoteEligibleCount=0` 时热度无效，不以 100% 或 0% 代替。

前端只消费上述计数与状态，不得按证券代码、名称、行情缺失或停牌文案重新过滤。

---

## 5. 交互与排序口径

### 5.1 Tab

1. 默认 `INDUSTRY`。
2. 行业、概念和地域保留各自最后一次选择；切换 Tab 不复用其它 Tab 的排名维度或选中代码。
3. Tab 切换时模块外框尺寸不变，局部进入 loading，不卸载首页其它模块。

### 5.2 行业三级联动

1. 一级列候选范围：全部一级行业。
2. 二级列候选范围：当前选中一级行业的直接子级。
3. 三级列候选范围：当前选中二级行业的直接子级。
4. 点击一级行业后，后端自动选择该一级行业下排名第一的二级、三级节点；没有下级时停在当前最深节点。
5. 点击二级行业后，后端自动选择其排名第一的三级节点。
6. 点击三级行业只更新三级选择和右侧详情。
7. 右侧详情始终展示当前选择路径中的最深节点。
8. 每列只在本列候选范围内排名，禁止一级、二级、三级混排。

### 5.3 行业排名

| 排名维度 | 主排序 | 空值规则 |
|---|---|---|
| `CHANGE_PCT` | `changePct desc` | 空值不入 Top5 |
| `MAIN_NET_INFLOW` | `mainNetInflow desc` | 空值不入 Top5 |
| `UP_COUNT` | `upCount desc` | 空值不入 Top5 |

所有维度使用 `sectorCode asc` 作为最终次排序，每列最多 5 行。

### 5.4 概念排名

| 排名维度 | 主排序 | 空值规则 |
|---|---|---|
| `HEAT_SCORE` | `heatScore desc` | 仅有效热度快照参与 |
| `HEAT_DELTA_1D` | `heatDelta1d desc` | 历史不足不参与 |
| `CHANGE_PCT` | `changePct desc` | 空值不参与 |
| `MAIN_NET_INFLOW` | `mainNetInflow desc` | 空值不参与 |

1. API 固定返回 Top20；设计稿固定 7 行可视区并在列表内部滚动。
2. 默认选中第一行；用户选中的概念仍在 Top20 时保持选择，否则回到新榜首。
3. `heatTrend` 只作标签，不提供独立排序入口。
4. 概念详情返回该概念最近 20 个已发布交易日的 `tradeDate/heatScore/heatRank/heatLevel`；无效点返回空值形成断点，不向前填充。

### 5.5 地域排名

| 排名维度 | 主排序 | 空值规则 |
|---|---|---|
| `CHANGE_PCT` | `changePct desc` | 空值不参与 |
| `MAIN_NET_INFLOW` | `mainNetInflow desc` | 空值不参与 |
| `UP_COUNT` | `upCount desc` | 空值不参与 |

1. 候选范围固定为 `idx_type/category/content_type` 生产枚举映射后的 31 个地域板块，不从股票 `area` 临时聚合。
2. API 返回生产枚举映射后的全部 31 个地域板块；设计稿固定 7 行可视区并在列表内部滚动。
3. 默认选中第一行；用户选中的地域仍在 31 个候选中时保持选择，否则回到新榜首。
4. 地域不返回 `level/parentCode/hierarchyPath/heat`，不显示热度等级或趋势标签。
5. 详情返回同日 `upCount/downCount/memberCount`、领涨股和成分股 Top5。

---

## 6. 数据来源与字段映射

### 6.1 已核验事实源

| 业务事实 | 主来源 | 字段 |
|---|---|---|
| 行业层级 | DG `silver_dc_industry_hierarchy` 的 serving 投影 | `ts_code/name/industry_level/parent_ts_code/root_ts_code/hierarchy_path/display_order/...` |
| 交易日边界 | `core_serving.trade_calendar` | `exchange/trade_date/is_open/pretrade_date` |
| 板块盘后行情 | `core_serving.dc_index` | `trade_date/ts_code/name/idx_type/pct_change/up_num/down_num/leading/leading_code/leading_pct/level` |
| 板块成交额/换手 | `core_serving.dc_daily` | `trade_date/ts_code/category/pct_change/amount/turnover_rate` |
| 板块盘后资金流 | `core_serving.board_moneyflow_dc` | `trade_date/content_type/name/ts_code/net_amount/net_amount_rate` |
| 行业/概念/地域成员 | `core_serving.dc_member` | `trade_date/ts_code/con_code/name` |
| 证券资格 | `core_serving.security_serving` | `ts_code/security_type/curr_type/list_status/list_date/delist_date` |
| 股票停牌事实 | `core_serving.equity_suspend_d` | `ts_code/trade_date/suspend_type`，停牌固定 `suspend_type='S'` |
| 股票盘后行情 | `core_serving.equity_daily_bar` | `ts_code/trade_date/close/pct_chg/amount` |
| 股票涨停事实 | `core_serving.equity_limit_list` | `trade_date/ts_code/limit_type`，涨停固定 `limit_type='U'` |
| 概念热度 | 新增 `core_serving.wealth_sector_heat_daily` | 见第 7.6 节 |

### 6.2 DG 行业层级契约

当前资产为单文件全量快照，正式节点数为 496：一级 31、二级 128、三级 337。字段包括：

```text
ts_code, name, industry_level, industry_level_name,
parent_ts_code, parent_name, root_ts_code, root_name,
hierarchy_path, is_leaf, display_order,
baseline_version, source_received_date, code_reference_trade_date
```

Web API 不直接读取 Parquet；必须先同步到 `core_serving.wealth_sector_hierarchy`，并完成行数、层级闭包和 read-back 对账。

### 6.3 源接口字段证据（不作为运行数据源）

1. `dc_index` 的领涨股、板块类型与行业层级字段为真实返回字段。
2. `dc_member` 只提供板块代码、成分代码和成分名称，不提供成分行情。
3. `dc_daily.category` 经真实显式字段请求确认可返回。
4. `moneyflow_ind_dc` 提供盘后正式板块资金流字段，其已入库的 prod `board_moneyflow_dc` 才是 Heat Model EOD V1 的运行数据源。
5. 上述结论只证明字段语义；Heat 计算、回放和 API 均不得直接调用 Tushare。本需求不修改既有 DatasetDefinition、request builder 或源接口分页契约。

### 6.4 交易日一致性

1. 层级使用当前生效版本，不按 API 请求日期回溯历史层级。
2. 行情、成员、资金流、股票日线、涨停事实、停牌事实和热度必须属于同一 `tradeDate`；证券主数据按上市/退市日期投影到目标日。
3. `equity_limit_list` 零行不能自动解释为“当日零涨停”；必须由对应数据集成功运行或日期完整性事实证明该日已完成。
4. 默认请求只展示全部必需源完成的最近交易日；显式 `tradeDate` 不自动回退。
5. `board_moneyflow_dc` 只按同日非空 `ts_code` 与板块代码关联；代码缺失时 `mainNetInflow` 为空并记录覆盖缺口，不按名称模糊关联。
6. “有效交易日”指该日全部必需 prod 来源通过日期、枚举、数量、唯一键和完成语义门禁；不是自然日，也不是仅因 Heat 表存在记录就算有效。CN_A 沿用当前市场总览口径，以 prod `trade_calendar.exchange='SSE' AND is_open=true` 选择连续 60 个首发验收交易日；窗口内任一缺口必须修复，不能跳过后从更早或更晚日期凑数。

---

## 7. Heat Model EOD V1

### 7.1 计算范围

1. 仅计算 `dc_index.idx_type` 映射为概念板块的节点。
2. 横截面为同一 `tradeDate`、通过质量门禁的全部概念。
3. 所有原始特征先做当日横截面 1%/99% winsorize，再转为 `0..1` 经验分位。
4. 样本并列使用平均秩；最终分数保留两位小数，排名按未四舍五入分数排序。
5. 所有成员类特征只使用第 4.6 节有效池；禁止把 B 股、未上市代码或停牌成员当作行情缺失压低覆盖率。

### 7.2 总公式

```text
heatScore = 100 × (
  0.30 × priceStrength
  + 0.25 × breadth
  + 0.25 × capitalFlow
  + 0.10 × activity
  + 0.10 × persistence
)
```

### 7.3 五个分量

| 分量 | 权重 | V1 子指标与分量内权重 |
|---|---:|---|
| 价格强度 | 30% | 当日涨跌幅 50%、5 日相对强度 33.33%、日度加速度 16.67% |
| 板块广度 | 25% | 上涨家数比 60%、涨停占比 40% |
| 资金流 | 25% | 当日净流入强度 60%、5 日流入持续性 40% |
| 活跃度 | 10% | 当日成交活跃度相对 20 个已完成交易日基线 100% |
| 持续性 | 10% | 前 5 日基础热度 Top20 连续天数 50%、基础热度名次改善 50% |

原始特征定义：

```text
dailyReturn       = dc_daily.pct_change(t)
relativeStrength5 = conceptCompoundedReturn(t-4..t)
                    - median(validConceptCompoundedReturn(t-4..t))
dailyAcceleration = dc_daily.pct_change(t) - dc_daily.pct_change(t-1)

upRatio      = count(member pct_chg > 0) / validQuoteCount
limitUpRatio = count(member in equity_limit_list where limit_type='U') / validQuoteCount

netInflowStrength = board_moneyflow_dc.net_amount_rate(t)
positiveInflowDayRatio5 = count(net_amount(t-i) > 0, i=0..4) / 5
netInflowRateSlope5 = linearRegressionSlope(net_amount_rate(t-4..t))

activity = dc_daily.amount(t) / median(dc_daily.amount over t-20..t-1)

baseHeatScore(t) = first four dimensions renormalized from total weight 0.90 to 1.00
baseHeatRank(t)  = cross-sectional rank of baseHeatScore(t)
priorTop20Streak5 = consecutive days ending at t-1 where baseHeatRank <= 20,
                    capped at 5 completed trading days
baseRankImprovement = baseHeatRank(t-1) - baseHeatRank(t)
```

其中 `P(x)` 表示第 7.1 节的当日横截面经验分位，资金流分量严格为：

```text
capitalFlow = 0.60 × P(netInflowStrength)
              + 0.40 × (
                  0.60 × P(positiveInflowDayRatio5)
                  + 0.40 × P(netInflowRateSlope5)
                )
```

`persistence` 不允许引用当前或前一日最终 `heatRank`，避免自循环。物化任务需在同一有界历史窗口内先复算基础热度名次，再计算持续性；更晚日期输入不得参与。

### 7.4 等级与日度趋势

| 条件 | 等级 |
|---|---|
| `heatScore >= 90` | `BOILING / 沸腾` |
| `80 <= heatScore < 90` | `HOT / 高热` |
| `60 <= heatScore < 80` | `ACTIVE / 活跃` |
| `< 60` 或分数无效 | `NONE / 无标签` |

```text
heatDelta1d = heatScore(t) - heatScore(t-1)
```

| 条件 | 原始趋势 |
|---|---|
| `heatDelta1d >= 8` | `HEATING / 升温` |
| `-8 < heatDelta1d < 8` | `STABLE / 平稳` |
| `heatDelta1d <= -8` | `COOLING / 降温` |

为降低单日噪声，`HEATING` 和 `COOLING` 需连续两个可比交易日命中同一方向后才正式展示；“可比”要求交易日连续且 `scoreVersion/configHash` 相同。首次命中返回 `STABLE` 并保留原始趋势供 debug；缺少前一交易日合法同版本快照、跨版本或日期断点时返回 `UNKNOWN`，不得跨断点确认趋势。

### 7.5 质量门禁

1. `memberCount >= 10`，此处只统计有效 A 股成分。
2. `quoteEligibleCount > 0` 且 `quoteCoverage >= 80%`。
3. `dc_daily/dc_index/dc_member/board_moneyflow_dc/equity_daily_bar/equity_limit_list/equity_suspend_d` 均已完成目标交易日，`security_serving` 资格字段可用。
4. 5 日、20 日窗口只使用已完成交易日；为复算前 5 日基础热度，任务至少读取 `dc_daily[t-25..t]`、`board_moneyflow_dc[t-9..t]` 以及 `dc_index`、成员和股票事实 `[t-5..t]`。历史不足导致任一主分量不可计算时热度无效。
5. 五个主分量均可计算；缺失任一主分量不得重新分配权重。
6. 热度构建失败只回滚目标交易日尚未提交的 Heat 业务事务，并由独立 Ops TaskRun 记录失败；不得回滚、阻断或污染来源业务表，TaskRun 状态写入失败也不得反向影响已提交 Heat。

### 7.6 盘后物化字段

`core_serving.wealth_sector_heat_daily` 至少保存：

```text
trade_date, sector_code, sector_name,
heat_status, invalid_reason,
base_heat_score, base_heat_rank,
heat_score, heat_rank, heat_level, heat_delta_1d, heat_trend, raw_heat_trend,
price_strength_score, breadth_score, capital_flow_score,
activity_score, persistence_score,
source_member_count, member_count, suspended_count,
quote_eligible_count, valid_quote_count, missing_quote_count, quote_coverage,
score_version, config_hash,
source_dates_json, source_row_counts_json, source_hash,
calculated_at
```

主键为 `(trade_date, sector_code)`。每个当日概念均保留一行；未通过质量门禁时 `heat_status=INVALID`、总分与不可计算分量为空。`invalid_reason` 首版固定为 `MEMBER_COUNT_LOW / QUOTE_ELIGIBLE_COUNT_ZERO / QUOTE_COVERAGE_LOW / HISTORY_INSUFFICIENT / FEATURE_MISSING`，不得写入自由文本原因。同一交易日重跑采用独立业务事务覆盖该日记录，候选行数与 canonical hash 成功 read-back 后提交；不得在 Web 请求中补算。

---

## 8. 状态与异常语义

| 状态 | 判定 | 用户表现 |
|---|---|---|
| `READY` | 当前视图必需数据完整 | 正常展示 |
| `PARTIAL` | 榜单/详情可用，但热度或成员行情部分缺失 | 保留骨架，缺字段显示 `--`，debug 记录原因 |
| `DELAYED` | 最近完整观测交易日落后于期望交易日 | 展示实际盘后日期，不把旧数据冒充当日 |
| `EMPTY` | 当前候选范围无合法节点/概念 | 模块空态，不补假数据 |
| `ERROR` | 查询、层级闭包、配置或物化契约失败 | 模块错误态，不影响首页其它模块 |
| `FORBIDDEN` | 当前用户无 `quote.read` | 稳定无权限态 |

异常码统一引用 `wealth/docs/system/exception-code-registry.md` 中的 `SO_*` 条目。

---

## 9. API 需求层契约

1. 路径保持：`GET /api/v1/wealth/market/sector-overview`。
2. V2 是破坏性模块契约升级；发布时同时替换后端 DTO、前端消费者、真实 API 测试和 fixture。
3. 请求参数：
   - `market?: "CN_A"`
   - `tradeDate?: YYYY-MM-DD`
   - `view?: "INDUSTRY" | "CONCEPT" | "REGION"`
   - `industryRankMetric?: "CHANGE_PCT" | "MAIN_NET_INFLOW" | "UP_COUNT"`
   - `selectedIndustryCode?: string`
   - `conceptRankMetric?: "HEAT_SCORE" | "HEAT_DELTA_1D" | "CHANGE_PCT" | "MAIN_NET_INFLOW"`
   - `selectedConceptCode?: string`
   - `regionRankMetric?: "CHANGE_PCT" | "MAIN_NET_INFLOW" | "UP_COUNT"`
   - `selectedRegionCode?: string`
   - `debug?: 0 | 1`
4. 后端拒绝与当前 `view` 无关的选择参数，拒绝客户端传 `level/parentCode/limit/weights/thresholds`。
5. 字段统一 lowerCamelCase，主体字段使用 `sectorCode/sectorName` 与 `stockCode/stockName`。

---

## 10. 验收标准

### 10.1 功能验收

1. 行业、概念与地域 Tab 可切换且保留各自状态。
2. 行业三列均只展示对应层级和父级范围，每列最多 5 行。
3. 点击一级/二级后下级列表和详情按规则联动。
4. 每个排名项突出板块名、主指标和领涨股。
5. 概念默认按有效 `heatScore` 排名，等级和日度趋势标签可独立变化。
6. 行业、概念与地域详情均展示最多 5 个真实成分股及盘后涨跌幅。
7. 地域榜单只包含 31 个地域板块，固定 7 行可视区，不出现行业层级或概念热度标签。

### 10.2 数据验收

1. 层级 serving 表与 DG 快照 496 行对账一致，31/128/337 分布一致。
2. 每个二、三级节点存在合法直接父级；每个节点存在一级根节点。
3. 领涨股逐字段等于 `dc_index`，不从成分榜推断。
4. 三类板块原始成员集合与 `dc_member` 同交易日去重结果一致。
5. 有效 A 股池逐行满足证券资格和上市/退市日期边界；B 股、未上市、已退市、停牌和真实缺行情数量可对账。
6. Heat Model EOD V1 对固定样本可复算，权重、分位、阈值、日度变化和版本一致。
7. 任一响应的全部日频来源日期与 `tradeDate` 一致。

### 10.3 视觉验收

1. 行业、概念和地域模块分别使用 `1564 × 680` 同尺寸截图基线。
2. 普通 UI 元素相对 Figma 基线偏差不超过 2px。
3. 无新增换行、裁剪、重叠或溢出。
4. Tab、工具栏、排名列表、指标卡和详情容器按设计稿布局。
5. 所有状态共享同一模块外框，切换状态不造成首页跳动。

### 10.4 性能验收

1. API 同机房 P95 `< 250ms`，payload `< 120KB`。
2. 单交易日热度离线物化 P95 `< 60s`；首次至少 60 个有效交易日回放单日平均 `< 60s`。
3. API 请求链路无 Tushare 网络请求、无 Lake 文件扫描、无热度全量重算、无全市场无界扫描。

---

## 11. 开工前仍需通过的门禁

1. Figma 的盘后字段、地域第三视图和有效 A 股池说明已同步；编码前以节点 `538:517/538:520/538:521/571:516/538:522/554:516` 为准。
2. 当前只读审计已确认 `dc_daily/dc_member` 以源站现状为业务口径，`board_moneyflow_dc@2026-07-09` 已补齐；正式回放前仍须冻结 60 个有效交易日及 warm-up 日期集合，逐日列出剩余 prod 来源缺口并完成修复与复核。
3. 验证 `dc_index.idx_type`、`dc_daily.category`、`board_moneyflow_dc.content_type` 的生产真实枚举映射，禁止凭中文命名猜过滤条件。
4. 盘后热度首发前至少完成 60 个有效交易日回放，检查有效池规模、停牌数量、可报价覆盖率、等级分布、日度跳变和稳定性；不完整日期不得凑数。
5. 新 serving 表迁移实现前必须重新检查 Alembic head；2026-08-13 本地仓库与生产只读快照均为单 head `20260812_000133`，不得把该快照硬编码为实施日 `down_revision`。

上述门禁未通过时只允许继续文档、数据审计和固定样本 contract 准备；不得越级实施后端 V2 或前端三工作台。前端开发固定在 prod Heat 回放与后端 V2 验收之后。

---

## 12. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v2.3 | 2026-08-13 | 更新 Alembic 只读快照为本地与生产共同确认的 `20260812_000133`；实施日仍须重查 | Codex |
| v2.2 | 2026-08-13 | 冻结 Heat 全量 prod 来源、DG 仅保留行业层级、60 个有效交易日定义与当前来源审计口径 | Codex |
| v2.1 | 2026-08-12 | 增加地域独立排行；冻结目标交易日有效 A 股成分池、停牌感知的可报价池与质量门禁 | Codex |
| v2 | 2026-08-12 | 按正式 Figma V2、DG 三级行业资产和首页盘后定位重建需求基线；热度变化改为交易日维度 | Codex |
