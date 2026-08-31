# 新闻—个股关联技术方案 v1

## 文档状态

- 文档类型：技术方案
- 当前状态：已结案（2026-09-01 用户确认）；M0～M6、批次级实时进度、`news_time` 手动范围与可配置自动增量均已实现
- 方案范围：从生产新闻内容生成个股关联，并在财势乾坤股票详情页提供个股新闻
- 当前事实源：代码、测试和当前数据模型
- 方案权威性：本方案记录已实现合同与结案边界；当前生产运行事实仍以实际系统和运行记录为准

本文记录最终实现与结案合同。物化窗口已经收敛为 `news_time + manual_range/scheduled_incremental + cursor_end`；旧
`fetched_at + full/incremental + overlap` 只作为历史契约和负向拒绝样本保留。原开发轮次不负责部署、生产 Schedule 和生产回填；
2026-09-01 用户确认新闻相关需求结案后，这些事项不再作为本文的开放需求跟踪。

## 1. 目标与边界

将生产数据库中的新闻内容与股票 `ts_code` 建立可查询的多对多关联，使财势乾坤股票详情页可以按股票代码展示相关新闻。

核心识别规则：

```text
`core_serving_light.news` 中的每条新闻（不区分 `channels`，包括 `channels = '公司'`）命中股票代码 OR 命中公司全称 OR 命中股票简称
    => 建立新闻—股票关联
```

三类规则独立执行，结果取并集。同一篇新闻和同一只股票最终只保留一条关联记录。

### 已确认业务口径

| 事项 | 已确认口径 |
|---|---|
| 新闻范围 | 处理 `core_serving_light.news` 全部新闻，包括 `channels = '公司'`；不按 `channels` 过滤 |
| 代码、名称、简称 | 三种匹配独立执行，任意一种命中即可召回，结果取并集 |
| 当前字段 | `symbol` 为六位代码，`ts_code` 为带交易所后缀的完整代码，`name` 为简称，`fullname` 为公司全称 |
| 简称冲突 | 按词典输入顺序取第一个映射，不同时召回多只股票 |
| 历史简称 | 使用现有 `core_serving_light.namechange` 的名称和有效时间区间 |
| 关联附加字段 | 保留 `match_method`、`source_field`、`rule_version` |
| 不设计字段 | 不设计 `relation_type`、`decision_status`、`match_score`，不建证据表 |
| 详情页 API | 默认最近 2 个月，默认 `limit=50`，最大 `2000`，支持时间范围，不分页，超限截断 |
| 新闻排序 | 后端按完整 `news_time`（年-月-日 时:分:秒，含时区）倒序；完全相同时间再按 `row_key_hash` 升序稳定排序；前端严格保持 API 返回顺序 |
| 新闻日期展示 | 前端只展示年月日：当前年份显示 `MM-DD`，其他年份显示 `YYYY-MM-DD`；不展示时、分、秒 |
| 详情页位置 | `06 stock detail / M4 / Right Tabs` 增加“新闻”Tab，Tab 条高度为当前 36px |
| 物化时间轴 | 新闻选择统一使用 `news_time`；`fetched_at` 不再参与物化范围、游标和 keyset |
| 手动物化 | 运营必须选择开始日期和截止日期；按 `Asia/Shanghai` 解释，截止日期包含整天，后端转换为次日零点排他上界 |
| Full 定义 | Full 不再是独立执行算法；它只是覆盖全部所需历史日期的手动范围任务 |
| 自动增量 | 由运营在现有“自动任务”中自行创建并启用；执行间隔可配置，推荐每 5 分钟，平台最小间隔 3 分钟 |
| 自动开关 | `ops.schedule.status=active/paused` 就是启用/暂停开关；不新增环境变量或业务代码开关 |
| 增量窗口 | `[上一次成功 cursor_end, 本次实际触发时间)`，精确到秒；成功才推进，失败、取消、未开始均不推进 |
| 自动任务边界 | 代码只提供可调度能力，不预置、不创建、不启用生产 Schedule；部署后由运营配置 |

本期不做：

1. 不识别新闻中的主要对象和次要对象，不设计 `relation_type`。
2. 不设计人工审核流，不设计 `decision_status`。
3. 不设计 `match_score`，不使用未经样本校准的伪概率。
4. 不建立证据表，不保存命中原文片段和命中位置。
5. 不使用大模型、分类模型或语义角色识别。
6. 不修改 `core_serving_light.news` 的现有新闻事实表。
7. 不在页面请求时执行文本识别。
8. M0～M6 的数据库迁移、物化任务、TaskRun 接入、业务 API、前端页面和批次级实时进度增强已经落在当前代码中；生产迁移、
   生产回填、Schedule 实际启用和部署不因本文更新而自动完成。
9. 不在新闻 ingestion 成功后直接跨层调用物化服务；本期采用可配置的 5 分钟级定时增量，不建设任务成功事件总线。
10. 不保留旧 `full/incremental` 用户参数或 `fetched_at/overlap` 兼容执行分支；当前代码已一次性收敛到手动范围与自动增量两种意图。

## 2. 当前代码事实

### 2.1 新闻事实

当前新闻 serving-light 模型为 `core_serving_light.news`，主键是 `row_key_hash`，字段包括：

```text
row_key_hash, src, news_time, title, content,
channels, score, source, fetched_at
```

模型位置：[NewsLight](/Users/congming/github/goldenshare/src/foundation/models/core_serving_light/news.py)

开发前的市场总览个股新闻查询曾只使用 `channels = '公司'` 做新闻分类筛选，没有按股票代码关联，返回的 `subject` 为空；该历史实现不能作为股票详情页新闻查询依据。当前市场总览新闻已由独立方案完成双来源改造，不影响本关联链路。

当前 `core_serving_light.news` 是由 `raw_tushare.news` 提供的 serving-light view；源表已有 `news_time` 相关索引，但 serving-light
本身不是可写业务表。关联任务读取 serving-light 视图，写入独立的 `core_serving.news_stock_link`。

### 2.2 股票主数据

当前股票主数据模型为 `core_serving.security_serving`，主键是 `ts_code`，已有：

```text
ts_code, symbol, name, fullname, security_type,
list_status, list_date, delist_date
```

模型位置：[Security](/Users/congming/github/goldenshare/src/foundation/models/core_serving/security_serving.py)

历史简称事实来自 `core_serving_light.namechange`，当前模型字段为：

```text
ts_code, name, start_date, end_date, ann_date, change_reason
```

模型位置：[NamechangeLight](/Users/congming/github/goldenshare/src/foundation/models/core_serving_light/namechange.py)

历史名称不是另建证据表，而是复用现有的股票曾用名时间线。新闻的 `news_time` 转成日期后，只有落在
`start_date <= news_date <= end_date`（`end_date` 为空表示持续有效）时，历史简称才参与匹配。

算法内核只接收这些字段转换后的词典输入，不直接依赖 SQLAlchemy 或数据库连接。

### 2.3 当前股票详情页事实

当前股票详情页由 `wealth/src/pages/stock-detail/StockDetailPage.tsx` 编排，右侧信息栏由
`wealth/src/features/stock-detail/sidebar/StockInfoRail.tsx` 渲染。Right Tabs 现在是“盘口”“资料”“新闻”三项，
`.right-tabs` CSS 高度保持 36px。新闻已作为独立模块接口按 Tab 懒加载，没有塞入 `page-init` 或 `kline`。

当前后端路由聚合位置为 `src/app/api/v1/router.py`；新闻业务 API、查询和 schema 已分别落在
`src/biz/api/wealth/market/stock_detail_news.py`、`src/biz/queries/wealth/market/stock_detail/news_query.py` 和
`src/biz/schemas/wealth/market/stock_detail_news.py`。它使用独立的
`/api/v1/wealth/market/stock-detail/news`，没有回到旧的 `/api/v1/quote/detail/*`，也没有复用市场总览新闻接口。

### 2.4 当前物化与自动任务实现

当前代码已经完成以下收敛：

1. `NewsStockLinkingWindowResolver` 按 trigger source 生成 `manual_range/scheduled_incremental` 冻结窗口，旧 payload 明确失败；没有新契约成功基线时自动任务返回 422，不再静默 Full。
2. `NewsStockLinkingService._fetch_news_batch()` 按 `news_time ASC, row_key_hash ASC` 过滤、排序和 keyset；运行诊断的 `last_cursor` 同步使用 `news_time + row_key_hash`。
3. `maintenance.materialize_news_stock_links` 通过通用 `repeat_policy` 只开放 Cron 日内间隔，默认 5 分钟、最小 3 分钟、时区固定 `Asia/Shanghai`。
4. 手动任务只展示并校验自然日 `start_date/end_date`，截止日转换为上海次日零点排他上界，周末和节假日不被交易日历过滤。
5. 自动调度发现空窗口或已有 `queued/running/canceling` 任务时只推进 `next_run_at`，不创建空/失败 TaskRun，不更新 `last_triggered_at`；成功 TaskRun 的 `cursor_end` 才进入下一窗口。
6. 继续复用现有 `ops.schedule`，没有新增表、环境变量或代码定时器；同一新闻动作最多保留一条 Schedule，创建 active 和恢复 paused 时验证新契约成功基线。

## 3. 总体架构

```text
core_serving_light.news + core_serving.security_serving
                         + core_serving_light.namechange
                         │
                         ▼
                 StockNewsLinker
                         │
                         ▼
             core_serving.news_stock_link
                         │
                         ▼
stock-detail/news API -> Wealth 股票详情页
```

物化入口分成两种运营意图，但复用同一个识别和批次写入内核：

```text
手动任务：开始日期 + 截止日期
          └─ 上海自然日范围 → 精确 [window_start, window_end)

自动任务：Ops Schedule（active/paused，*/N 分钟）
          └─ 上次成功 cursor_end → 本次实际触发时间

两条入口
  └─ NewsStockLinkingService（按 news_time keyset）
       └─ 每批先删除旧关系，再重建当前识别结果
```

“Full”只表示运营选择了覆盖全部历史的手动范围，不在 executor 中保留第三种算法分支。

算法内核链接：

[StockNewsLinker 算法内核](../../src/foundation/news_linking/stock_news_linker.py)

算法内核只负责：

1. 接收股票词典。
2. 接收历史简称时间区间词典。
3. 接收新闻标题、正文和新闻日期。
4. 执行代码、全称、当前简称和有效历史简称匹配。
5. 返回去重后的 `StockNewsLink`。

算法内核不负责数据库查询、数据库写入、TaskRun、API 或前端 ViewModel。

## 4. 算法设计

### 4.1 词典输入

```python
StockLexiconEntry(
    ts_code="600519.SH",
    symbol="600519",
    name="贵州茅台",
    fullname="贵州茅台股份有限公司",
    security_type="EQUITY",
)

HistoricalNameEntry(
    ts_code="600519.SH",
    name="茅台股份",
    start_date=date(2010, 1, 1),
    end_date=date(2018, 12, 31),
)

NewsRecord(
    news_id="news-row-hash",
    title="贵州茅台发布公告",
    content="正文内容",
    news_date=date(2026, 8, 22),
)
```

字段映射：

| 匹配对象 | 股票主数据字段 | `match_method` |
|---|---|---|
| 交易所后缀代码或六位代码 | `ts_code` / `symbol` | `CODE_EXACT` |
| 公司全称 | `fullname` | `FULL_NAME_EXACT` |
| 股票简称 | `name` | `SHORT_NAME_EXACT` |
| 历史股票简称 | `core_serving_light.namechange.name` + 时间区间 | `SHORT_NAME_EXACT` |

只接收 `security_type = EQUITY` 的词典项。

最终字段口径固定为：`symbol` 是六位股票代码，`ts_code` 是带交易所后缀的完整代码，`name` 是当前股票简称，
`fullname` 是公司全称；历史简称只来自 `namechange.name`，不把它混入当前 `security_serving.name` 字段。

### 4.2 文本标准化

标题和正文分别处理：

1. Unicode NFKC 归一化。
2. 英文字母统一大小写。
3. 删除空白字符。
4. 保留中文语义字符和必要标点。

因此全角、半角和带空格的代码或名称可以使用同一规则匹配。

### 4.3 代码匹配

代码使用有边界的六位数字规则提取：

```regex
(?<![0-9A-Z])(?P<symbol>[0-9]{6})(?:\.(?P<exchange>SH|SZ|BJ))?(?![0-9A-Z])
```

正则只负责提取候选，最终仍需通过股票词典确认：

1. 带交易所后缀的代码必须精确命中 `ts_code`。
2. 不带后缀的六位代码必须唯一映射到一个 `symbol`。
3. 无法映射到股票主数据的数字不建立关联。
4. 被更长数字包围的六位数字不建立关联。

### 4.4 名称匹配

公司全称、当前简称和历史简称不为每只股票分别执行正则，而是构建单个 Aho-Corasick 多模式字符串匹配自动机：

1. 初始化时把所有可用的全称、当前简称和历史简称加入自动机。
2. 每篇新闻的标题和正文各扫描一次。
3. 单篇文本不执行“股票数量 × 文本长度”的重复查找。
4. 匹配复杂度接近 `O(文本长度 + 命中数量)`。

公司全称如果映射到多个 `ts_code`，仍不进入自动机，因为全称冲突通常表示主数据异常。当前简称按当前股票词典输入顺序
取第一个映射；历史简称在新闻日期有效的候选中按历史词典输入顺序取第一个，不同时召回多只股票。为使“第一个”可复现，
批处理构建当前股票词典时必须按 `ts_code ASC` 读取，历史名称词典必须按 `ts_code ASC, start_date ASC, row_key_hash ASC` 读取；
算法内核本身保持调用方传入顺序，不依赖数据库连接。

历史简称匹配需要 `NewsRecord.news_date`。批处理从 `NewsLight.news_time` 提取该日期后传入；没有新闻日期时只执行当前代码、
当前简称和公司全称规则，不猜测历史名称归属。

当前实现的特殊顺序也必须保留：同一规范化词条先加入公司全称，再加入当前简称，最后加入历史简称；如果当前简称和历史简称
恰好同名，当前简称候选先被选中。该行为属于当前算法事实，不在后续适配层重新解释。

### 4.5 结果合并

代码、全称和简称三个规则独立执行，结果按 `ts_code` 去重；历史简称属于简称规则的时间限定输入，不增加新的 `match_method`。

例如：

```text
标题：贵州茅台发布半年报
正文：600519.SH 今日成交活跃，五粮液同步上涨
```

最终得到：

```text
(news_id, 600519.SH)
(news_id, 000858.SZ)
```

同一只股票同时命中多个规则时只保留一条关联，`match_method` 按以下顺序记录：

```text
CODE_EXACT
FULL_NAME_EXACT
SHORT_NAME_EXACT
```

`source_field` 按实际命中字段记录：

```text
title
content
title_and_content
```

### 4.6 算法输出

```python
StockNewsLink(
    news_id="news-row-hash",
    ts_code="600519.SH",
    match_method=MatchMethod.CODE_EXACT,
    source_field=SourceField.TITLE_AND_CONTENT,
    rule_version="news-stock-rule-v1",
)
```

算法内核当前测试覆盖代码、全称、简称并集召回、去重、匹配方式优先级、来源字段、代码边界、简称首条映射、非股票证券和文本标准化。

历史名称测试覆盖时间区间内命中、区间外不命中和新闻日期缺失不使用历史简称。

当前实现还具备以下确定行为：空 `news_id` 会抛出 `ValueError`；同一 `ts_code` 的冲突词典行会抛出 `ValueError`；
非 `EQUITY` 证券被过滤；输出按 `ts_code` 升序；规则版本由构造器传入，默认值为 `news-stock-rule-v1`。

## 5. 数据模型设计

### 5.1 关联表

已实现物理表：

```text
core_serving.news_stock_link
```

这不是新闻源表，也不是 raw 表，而是由新闻和股票主数据派生出的服务关联表。

字段：

| 字段 | 类型建议 | 必填 | 用途 | 为什么必要 |
|---|---|---:|---|---|
| `news_id` | `varchar(64)` | 是 | 对应 `core_serving_light.news.row_key_hash` | 当前新闻源行身份；API 查询必须通过它回连新闻内容，不能使用标题作为身份 |
| `ts_code` | `varchar(16)` | 是 | 对应 `core_serving.security_serving.ts_code` | 个股业务主键；股票详情页按它查询，不能存简称，因为简称会变化 |
| `match_method` | `varchar(32)` | 是 | `CODE_EXACT`、`FULL_NAME_EXACT`、`SHORT_NAME_EXACT` | 记录最终采用的确定性规则，便于 debug、规则回归和规则版本切换；不是置信度分数 |
| `source_field` | `varchar(32)` | 是 | `title`、`content`、`title_and_content` | 记录命中来自标题、正文还是两者；不保存原文片段，也不需要证据表 |
| `rule_version` | `varchar(64)` | 是 | 例如 `news-stock-rule-v1` | 规则升级后可区分旧结果和新结果，支持按版本重跑；不是人工审核状态 |
| `created_at` | `timestamptz` | 是 | 关联首次生成时间 | 便于判断该关系何时首次产生；与新闻发布时间不同，不能省略为 `news_time` |
| `updated_at` | `timestamptz` | 是 | 关联最近计算时间 | 手动补跑、失败重试和规则重跑时更新；用于判断派生结果是否被重新计算 |

主键：

```text
PRIMARY KEY (news_id, ts_code)
```

索引：

```text
INDEX ix_news_stock_link_ts_code (ts_code)
```

主键的左侧字段已经覆盖按 `news_id` 清理旧关系的访问路径，因此不再重复建立单列 `news_id` 索引。

建议的建表约束形态：

```sql
CREATE TABLE core_serving.news_stock_link (
    news_id varchar(64) NOT NULL,
    ts_code varchar(16) NOT NULL,
    match_method varchar(32) NOT NULL,
    source_field varchar(32) NOT NULL,
    rule_version varchar(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_news_stock_link PRIMARY KEY (news_id, ts_code),
    CONSTRAINT ck_news_stock_link_match_method CHECK (
        match_method IN ('CODE_EXACT', 'FULL_NAME_EXACT', 'SHORT_NAME_EXACT')
    ),
    CONSTRAINT ck_news_stock_link_source_field CHECK (
        source_field IN ('title', 'content', 'title_and_content')
    )
);

CREATE INDEX ix_news_stock_link_ts_code
    ON core_serving.news_stock_link (ts_code);
```

`news_id` 不建立数据库外键，因为目标是 serving-light view，不是稳定的物理表；任务写入前必须通过新闻批次和查询 join
保证其存在。`ts_code` 也先按当前仓库跨 serving 表的既有模式做逻辑引用和任务前校验，不在第一版强加跨域外键，避免
主数据刷新顺序阻塞新闻关联写入。

约束：

1. `match_method` 只能取三种已定义值。
2. `source_field` 只能取三种已定义值。
3. `news_id + ts_code` 不允许重复。
4. 不添加 `relation_type`、`decision_status`、`match_score`。
5. 不复制新闻标题、正文、发布时间和股票名称。

字段取舍：

1. `relation_type` 不必要，因为本期只回答“这篇新闻是否与这只股票有关”，不回答主要对象、次要对象。
2. `decision_status` 不必要，因为没有人工审核流程，也没有待审核队列。
3. `match_score` 不必要，因为当前只有确定性规则，没有人工标注样本，分数无法解释为概率或质量指标。
4. 证据表不必要，因为本期不做识别算法研究；`source_field` 已足够说明命中来自标题、正文或两者。
5. 新闻标题、正文、发布时间不复制到关联表，避免事实字段重复；查询时回连 `core_serving_light.news`。
6. 股票简称和公司全称不复制到关联表，避免历史更名后出现关系表和股票主数据不一致；查询时回连 `security_serving`。

由于 `core_serving_light.news` 当前是 view，`news_id` 是逻辑引用；是否建立数据库外键需要结合当前 serving 发布方式另行确认。`ts_code` 逻辑上引用 `core_serving.security_serving`。

### 5.2 不修改现有新闻表

不在 `core_serving_light.news` 增加 `ts_code`，因为：

1. 一篇新闻可以对应多只股票。
2. 新闻源事实和派生识别结果职责不同。
3. 算法规则改变时，关联结果可以独立重建。
4. 不污染现有新闻 ingestion 链路。

当前 `raw_tushare.news` 的 `row_key_hash` 由 `src/news_time/title/content/channels/score` 共同生成，因此标题或正文变化时通常会生成新的
`news_id`，而不是更新同一个新闻身份。本期关联表跟随当前新闻源行身份建立关系，不擅自引入另一套新闻版本合并主键；如果未来要合并
同源新闻的内容版本，需要另立新闻身份方案，不能在本关联表中隐式处理。

## 6. 处理流程设计

### 6.1 词典构建

处理任务启动后：

1. 读取股票主数据中的 `ts_code/symbol/name/fullname/security_type`。
2. 读取 `core_serving_light.namechange` 中的 `ts_code/name/start_date/end_date`。
3. 过滤非 `EQUITY` 证券、未知 `ts_code`、空名称和非法时间区间。
4. 公司全称冲突时丢弃；当前简称和历史简称冲突时按固定输入顺序取第一条。
5. 构建代码索引、当前名称和历史名称 Aho-Corasick 自动机。
6. 固定本次处理使用的 `rule_version`。

词典只在任务初始化时构建一次，不能每条新闻重新查询股票表或重新构建自动机。

### 6.2 新闻处理

每条新闻：

1. 读取 `row_key_hash/title/content`。
2. 从 `news_time` 提取 `news_date`。
3. 分别扫描标题和正文。
4. 执行代码、当前全称、当前简称和有效历史简称规则。
5. 合并相同 `ts_code` 的多个命中。
6. 生成 `StockNewsLink`。
7. 通过批量 upsert 写入关联表。

批处理边界：

1. 任务启动时固定一次股票词典和历史名称词典快照；同一任务内不因每条新闻而重新读取主数据。
2. 新闻按 `news_time ASC, row_key_hash ASC` 读取并切成有限大小的内存批次；具体 batch size 属于内部性能参数，不暴露给页面。
3. 每个批次先收集本批 `news_id`，在关联表事务中删除这些新闻的旧关系，再批量 upsert 本批新关系并提交。
4. 批次失败只回滚当前关联表事务；TaskRun 标记失败且不推进自动成功游标。重试同一冻结窗口时，已经提交的批次会被安全重建。
5. 不把新闻源写入和关联表写入放在同一个事务中，不让关联识别失败阻塞新闻源 ingestion。

处理范围是 `core_serving_light.news` 的全部新闻，不加 `channels = '公司'` 过滤。`channels` 仍保留在新闻事实中，
但它只是新闻分类字段，不是个股关联召回条件。

### 6.3 手动范围、Full 与自动增量

所有物化统一使用 `news_time` 半开区间，不再使用 `fetched_at` 或 overlap。

手动范围：

1. 运营必须填写 `start_date/end_date`，两者都是上海自然日，不受交易日历限制。
2. `start_date` 转换为当天 `00:00:00 Asia/Shanghai`；`end_date` 包含整天，转换为次日 `00:00:00` 排他上界。
3. 例如 `2026-08-01 ～ 2026-08-23` 冻结为
   `[2026-08-01T00:00:00+08:00, 2026-08-24T00:00:00+08:00)`。
4. Full 只是覆盖全部所需历史日期的手动范围任务，不再是 `mode=full` 的独立执行分支。

自动增量：

1. 由运营创建 `maintenance.materialize_news_stock_links` 的 Cron Schedule，推荐 `*/5 * * * *`，时间间隔可修改。
2. `window_start` 取自动链上一次成功的 `cursor_end`，`window_end` 取本次实际触发时间，窗口为
   `[window_start, window_end)`，精确到秒。
3. 首次自动触发前必须存在一次成功的新契约手动范围任务；全新初始化时该任务应覆盖所需历史，升级切换时按本节后述桥接范围执行。系统不能在无基线时静默 Full。
4. 手动范围如果包含当前日或未来日，`cursor_end = min(window_end, task_frozen_at)`，避免把尚未产生的当日后续新闻误认为已覆盖。
5. 一旦已有成功的自动增量任务，后续游标只从成功的自动任务推进；人工补跑旧日期不能把自动游标前移或后移。
6. 失败、取消、未开始的 TaskRun 不推进 `cursor_end`；没有新闻的调度窗口不创建空 TaskRun，也不推进业务游标。
7. 如果上一条物化任务仍处于 `queued/running/canceling`，本次调度记为合并跳过并推进 Schedule 的下一次触发时间；下一次仍从
   上一次成功业务游标追赶到新的触发时间。
8. 重试严格复用原 TaskRun 的冻结窗口和 `task_frozen_at`，不按重试发生时间扩大范围；自动重试成功后，原 `cursor_end` 才能进入成功游标链。

按 `news_time` 推进意味着：首次历史范围完成后，如果以后插入一条 `news_time` 早于成功游标的旧新闻，自动增量不会发现它，
需要运营手动补跑对应自然日范围。这是已接受的业务限制，不再用 `fetched_at` 或 overlap 补偿。

新闻源写入和关联表写入必须是两个独立事务。关联任务失败不得阻塞或回滚新闻源数据写入。

### 6.4 范围重算与删除后重建

若同一新闻在手动补跑、失败重试或规则版本升级中再次进入处理范围：

1. 先删除该 `news_id` 的全部旧关系。
2. 再写入当前规则识别出的关系；命中主键 `(news_id, ts_code)` 时不产生重复行。
3. 对仍然存在的关系保留原 `created_at`，更新 `match_method/source_field/rule_version/updated_at`。
4. 当前识别结果为空时只执行删除，不保留已经失效的旧关系。

批量重建可能在同一批同时包含旧关系和新关系。进入 PostgreSQL 多行 INSERT 前，DAO 必须把所有行归一为相同列集合：旧关系使用已查询到的原 `created_at`，新关系使用本批统一的 UTC 时间。不能让部分行显式携带 `created_at`、部分行依赖 server default，否则 SQLAlchemy 会在 VALUES 编译阶段拒绝整批写入。

因此，TaskRun 记录的是“这次任务处理了哪个窗口、使用了哪套规则、产生了多少结果”，关联表记录的是“最终新闻和股票的当前派生关系”，
两者职责不同。只做 upsert 不能清理“新闻内容更新后已经不再命中”的旧关系，所以每批写入前还要按本批 `news_id` 删除旧派生关系，
再批量 upsert 当前识别结果；这仍然只修改 `news_stock_link`，不修改新闻源事实。这里的旧关系清理针对同一个 `news_id` 的规则重算；
由于当前新闻 hash 包含标题和正文，内容变化生成新 `news_id` 的版本生命周期属于新闻源数据治理范围，不在本期偷偷合并。

### 6.5 TaskRun 字段映射与运行边界

当前仓库已有 `ops.task_run`，模型位置为 `src/ops/models/ops/task_run.py`。本需求不新增 TaskRun 表、不新增独立的
`news_stock_task_run` 表，也不把 TaskRun 变成新闻关联业务表。

实现时应把新闻关联注册为现有 Ops TaskRun 主链中的一个 `maintenance_action` 派生维护动作，固定动作键为
`maintenance.materialize_news_stock_links`。该类任务不属于现有 `DatasetDefinition` 数据集维护主链，因此
`TaskRun.resource_key` 保持为空，`request_payload_json.target_key` 保存动作键；不得为了复用数据集页面而伪造一个
`news_stock_link` 数据集。动作注册、任务创建、dispatcher 执行和 worker 装配必须复用当前
`src/ops/action_catalog.py`、`TaskRunCommandService`、`TaskRunDispatcher` 和 `ops_worker_factory` 的现行契约，
不在业务查询层私自创建任务记录。

目标 `request_payload_json` 结构如下。它是任务请求快照，记录本次任务打算处理什么：

```json
{
  "target_key": "maintenance.materialize_news_stock_links",
  "run_mode": "scheduled_incremental",
  "window_field": "news_time",
  "window_start": "2026-08-22T10:25:00+08:00",
  "window_end": "2026-08-22T10:30:00+08:00",
  "cursor_end": "2026-08-22T10:30:00+08:00",
  "task_frozen_at": "2026-08-22T10:30:00+08:00",
  "rule_version": "news-stock-rule-v1",
  "news_scope": "all"
}
```

手动任务的 `run_mode=manual_range`，原始 `start_date/end_date` 保存在 `time_input_json`；窗口字段仍为精确时间戳。

字段落点：

| TaskRun 现有字段 | 新闻关联任务用途 |
|---|---|
| `request_payload_json` | 保存精确的 `run_mode/window_field/window_start/window_end/cursor_end/task_frozen_at/rule_version/news_scope` 请求快照 |
| `resource_key` | 为空；该派生维护动作不冒充 `DatasetDefinition` 数据集 |
| `filters_json` | 不设置 `channels='公司'`；如果保留过滤结构，明确写 `channels='all'` |
| `rows_fetched` | 本次读取并处理的新闻行数 |
| `rows_saved` | 本次关联表提交的关系行数 |
| `rows_rejected` | 固定为 0；未命中不是 rejected，批次异常由 TaskRun 失败状态和 issue 表达 |
| `rows_deduplicated` | 批内重复 `(news_id, ts_code)` 关系数量 |
| `ingestion_diagnostics_json` | `matched_news_count`、`links_inserted`、`links_updated`、`links_deleted`、`last_cursor` 等运行统计 |
| `current_object_json` | 当前批次的窗口、批次序号和阶段展示信息 |

当前运行边界如下：

1. 最近一次成功自动任务的 `cursor_end` 才能成为下一次自动增量游标；没有自动成功游标时，使用所有成功新契约手动任务中最大的
   `cursor_end`。失败或取消的 TaskRun 不参与，后完成的旧日期补跑不能把起点向后倒退。
2. 没有成功手动初始化基线时拒绝创建或恢复自动任务，不静默执行全量。
3. 同一时刻只允许一个新闻关联 TaskRun；同一动作只允许一条自动任务配置，调整频率应更新已有 Schedule。
4. TaskRun 的状态和观测写入失败不得回滚或阻塞新闻事实写入；关联表事务也不能反向污染 `raw_*` 或 `core_serving_light.*`。
5. TaskRun 只记录任务意图和运行观测；新闻关联的业务事实唯一存放在 `core_serving.news_stock_link`。

当前代码已经完成 action catalog、registered maintenance executor、dispatcher 单 unit 执行、批次事务、实时进度，以及上述
`run_mode/news_time/cursor_end` 请求契约；旧 `mode/fetched_at/overlap` 不再作为新任务执行契约。

修复前，业务批次虽然已经提交，但 TaskRun 观测没有批次级写回，这是页面“执行中但读取/保存仍为 0”的直接原因。
当前实现已补齐该观测链路；新闻动作执行中不再显示误导性的 `0/1` 和 `0%`。

### 6.6 批次级实时进度增强实现

这是当前 M0～M6 之后的最小范围增强，不改变关联表结构、TaskRun 表结构、API 路由或新闻识别规则。

```text
关联批次 commit 成功
        │
        ▼
NewsStockLinkingService 发送累计快照
        │  独立 observer session，失败 fail-soft
        ▼
TaskRun / 当前 TaskRunNode 的 rows_*、diagnostics、current_object
        │
        ▼
现有 TaskRun view API（无需新增接口）
        │  前端现有 3 秒轮询
        ▼
任务详情页显示已读取新闻数、已生成关联数和当前批次描述
```

实现约束：

1. `NewsStockLinkingService.materialize` 增加可选的批次进度 sink/callback；只在当前批次关联事务的 `commit()` 成功返回后发送，
   不能在 commit 前把未提交数据报告为已保存。
2. sink 写入复用现有独立 TaskRun 观测会话，累计写入 `rows_fetched/rows_saved/rows_rejected/rows_deduplicated` 和
   `ingestion_diagnostics_json`，不把业务 session 传入 observer，也不让 observer 异常回滚业务批次。
3. 新闻任务始终是一个逻辑 unit，因此实时更新保持 `unit_done=0、unit_total=1`；新闻行数不能伪装成 unit 百分比。
4. 第一批成功后立即写一次；后续最多每 3 秒写一次；任务成功、失败或取消时强制写最终快照。累计计数只增不减，
   `last_cursor` 只指向最近一次成功提交批次。
5. `current_object` 展示当前窗口、批次序号和“已处理新闻/已生成关联”；诊断至少包含
   `matched_news_count、links_inserted、links_updated、links_deleted、rows_deduplicated、unmatched_news_count、
   batch_count、last_cursor`；`last_cursor` 使用 `news_time + row_key_hash`。
6. dispatcher 保留最终 `MaintenanceExecutionResult` 写回作为终态权威来源；实时快照只补充运行中的可见性，不改变成功、失败、
   取消和游标推进语义。
7. 前端只对 `maintenance.materialize_news_stock_links` 做展示分支：保留已有 3 秒轮询和 rows 指标，执行中使用“已处理新闻/已生成关联”
   及不承诺百分比的进行中状态；其他 TaskRun 的 unit/progress 展示完全不变。

因此该增强不需要 SSE、WebSocket、Redis、新表、新 migration 或新的详情 API。它的风险面集中在观测写回和任务详情页展示，
业务关联结果仍由现有批次事务和 `(news_id, ts_code)` 主键保证。

### 6.7 自动任务配置与开关

部署具备新窗口能力的代码后，由运营在现有“自动任务”页面自行创建，不由 migration、启动脚本或应用代码预置：

```text
target_type       = maintenance_action
target_key        = maintenance.materialize_news_stock_links
display_name      = 新闻—个股关联自动增量
status            = active                 # paused 即关闭
schedule_type     = cron
trigger_mode      = schedule
cron_expr         = */5 * * * *             # 可改为其他 N，N >= 3
timezone          = Asia/Shanghai
calendar_policy   = NULL
params_json       = {}
probe_config_json = {}
```

配置审计：

| 配置 | 来源与持久化 | 用途 | 消费者 | 生效方式与可见性 |
|---|---|---|---|---|
| `status` | `ops.schedule` | 自动增量开关 | scheduler | 页面启用/暂停后生效，有 revision 记录 |
| `cron_expr` | `ops.schedule` | 更新检查间隔 | schedule planner/scheduler | 修改后重算 `next_run_at`；推荐 5 分钟，最小 3 分钟 |
| `timezone` | `ops.schedule` | 调度解释时区 | schedule planner | 固定使用 `Asia/Shanghai` |
| `target_type/target_key` | `ops.schedule` | 绑定新闻关联维护动作 | catalog、TaskRun builder、dispatcher | 页面选择动作时写入，不允许绑定成 dataset action |
| `params_json` | `ops.schedule` | 静态动作参数 | TaskRun builder | 本动作保持空对象；动态窗口不能固化在 Schedule 中 |
| `next_run_at/last_triggered_at` | `ops.schedule` | 调度运行状态 | scheduler、自动任务页面 | 系统维护，运营只读观察 |
| `retry_policy_json` | `ops.schedule` 既有字段 | 任务重试意图 | 现有 Ops 运行链 | 沿用平台能力，本方案不新增新闻专属配置 |

除上述数据库 Schedule 配置外，不新增 Settings、env、配置文件常量或页面私有开关。每 N 分钟只是检查频率；有多批新闻更新时合并成
一个范围任务，没有新闻时跳过，避免空任务和任务风暴。

配置和触发边界：

1. 同一 action 只允许一条未删除 Schedule；变更间隔必须编辑已有配置，第二条返回 409。
2. 创建 active Schedule 或恢复 paused Schedule 前必须存在成功的新契约手动基线；否则返回 422，不自动运行 Full。
3. 自动窗口无新闻时只推进 Schedule 的 `next_run_at`，不创建 TaskRun、不推进业务 `cursor_end`。
4. 已有同 action 的 `queued/running/canceling` TaskRun 时，本次自动触发合并跳过并推进 `next_run_at`；手动提交仍返回 409。
5. 新闻窗口由每次触发时的 `task_frozen_at` 动态生成，不能写进 Schedule `params_json`。

## 7. API 设计

### 7.1 股票详情新闻接口

当前已实现：

```http
GET /api/v1/wealth/market/stock-detail/news
```

请求参数：

| 参数 | 必填 | 类型 | 说明 |
|---|---:|---|---|
| `tsCode` | 是 | string | 例如 `600519.SH`；服务端去空格并转大写，必须能在 `security_serving` 找到股票证券 |
| `startAt` | 否 | datetime | 新闻开始时间；不传时使用 `endAt` 或当前时间向前推 2 个自然月 |
| `endAt` | 否 | datetime | 新闻结束时间；不传时使用当前时间 |
| `limit` | 否 | int | 默认 50；大于 2000 时截断为 2000；小于 1 返回参数错误 |
| `debug` | 否 | 0/1 | 默认 0；为 1 时返回每条关系的 `matchMethod` |

时间参数要求带时区偏移，统一转换到 `Asia/Shanghai` 后查询；查询区间采用半开区间 `[startAt, endAt)`，`startAt >= endAt`
返回参数错误。接口不分页，`limit` 只控制本次返回数量，不因超过 2000 而生成游标。

该接口不复用当前市场总览的 `GET /api/v1/wealth/market/news/stocks`，因为现有接口没有 `tsCode` 语义，只能返回公司频道新闻列表。

### 7.2 查询逻辑（当前实现）

```sql
SELECT
    n.row_key_hash,
    n.news_time,
    COALESCE(NULLIF(BTRIM(n.title), ''), SUBSTRING(BTRIM(n.content) FROM 1 FOR 80)) AS display_title,
    s.ts_code,
    s.name,
    l.match_method
FROM core_serving.news_stock_link l
JOIN core_serving_light.news n
  ON n.row_key_hash = l.news_id
JOIN core_serving.security_serving s
  ON s.ts_code = l.ts_code
WHERE l.ts_code = :ts_code
  AND n.news_time >= :start_at
  AND n.news_time < :end_at
ORDER BY n.news_time DESC, n.row_key_hash ASC
LIMIT :limit
```

排序契约必须严格按以下规则实现：

1. `n.news_time` 是 `DateTime(timezone=True)` 的完整新闻发布时间，主排序精度保留到秒；后端必须直接按完整时间戳 `DESC` 排序，不得先转换为日期、截断到天、格式化成展示字符串后再排序。
2. `n.row_key_hash ASC` 只是完整 `news_time` 完全相同时的稳定 tie-breaker，不得改变不同年月日时分秒之间的时间倒序关系。
3. `LIMIT` 必须在上述 `ORDER BY` 之后执行，截断的是已经排好序的结果集。
4. API 返回的 `items` 数组顺序就是股票详情页的最终展示顺序。前端不得 `sort`、`reverse`、按日期重新分组、再次去重或再次截断。
5. `publishTime` 必须保留完整年月日时分秒和 `Asia/Shanghai` 时区偏移，例如 `2026-08-22T10:30:05+08:00`。前端只把它用于日期格式化和展示，不得使用格式化后的日期文本参与排序。

`match_method` 只在 `debug=1` 时序列化到响应；普通响应不泄漏识别内部字段。查询不得 `SELECT *`，也不得重新扫描新闻正文。
不按标题去重，因为两条不同新闻即使标题相同，也可能是两条独立新闻事实。

### 7.3 API 响应

```json
{
  "stockRef": {
    "tsCode": "600519.SH",
    "name": "贵州茅台"
  },
  "items": [
    {
      "newsId": "news-row-hash",
      "publishTime": "2026-08-22T10:30:05+08:00",
      "title": "贵州茅台发布半年报"
    },
    {
      "newsId": "news-row-hash-2",
      "publishTime": "2026-08-22T10:29:59+08:00",
      "title": "贵州茅台召开投资者交流会"
    }
  ],
  "meta": {
    "count": 2,
    "limit": 50,
    "startAt": "2026-06-22T10:30:00+08:00",
    "endAt": "2026-08-22T10:30:00+08:00"
  }
}
```

`match_method`、`source_field` 和 `rule_version` 是内部技术字段，默认不向用户展示；`debug=1` 时允许在每条 item 的
`debugInfo.matchMethod` 中返回 `match_method`，不进入普通页面契约。`source_field` 和 `rule_version` 仍只留在内部任务结果中。

本期响应只提供新闻 ID、发布时间和展示标题，展示标题沿用当前市场新闻查询的显示口径：优先使用非空 `title`，为空时
使用 `content` 去首尾空白后截取前 80 个字符。页面不展示来源、不提供点击外链，也不添加 `clickable` 字段。

错误语义：

| 情况 | HTTP/错误语义 |
|---|---|
| `tsCode` 不存在或不是股票证券 | 404，沿用股票详情现有资源不存在语义 |
| 时间格式错误、开始时间不早于结束时间 | 400 |
| `limit < 1` | 400 |
| 关联表或新闻查询异常 | 500；只影响新闻 Tab，不影响详情页 K 线和盘口 |

## 8. Wealth 页面接入（当前实现）

股票详情页在现有 `06 stock detail / M4 / Right Tabs` 新增“新闻”Tab，不把新闻塞入现有 `page-init`。
当前代码的 `.right-tabs` 高度是 36px；设计定位为约 `374.797 × 36`，宽度跟随当前右侧信息栏，不新增固定宽度 CSS。

```text
盘口 | 资料 | 新闻
```

新闻 Tab 的展示口径：

1. 点击“新闻”后按当前 `tsCode` 懒加载股票详情新闻 API；页面首次进入不请求新闻，避免影响 K 线首屏。
2. 新闻内容以列表展示，每个 item 只有两列：左列新闻 `title`，右列新闻时间。
3. 前端按 `Asia/Shanghai` 解释 `publishTime` 后只展示年月日：如果新闻年份等于运行时当前年份，显示 `MM-DD`；否则显示 `YYYY-MM-DD`，不把 2026 写成永久常量。时、分、秒只参与后端排序，不在新闻 item 中展示。
4. 新闻列表严格按 API `items` 的原始顺序渲染；前端不自行过滤、排序、截断、重新去重或重新识别个股。
5. 空结果、加载中和请求失败分别展示独立状态，不影响 K 线、盘口和资料 Tab。
6. 新闻 item 不显示 `matchMethod`、`sourceField`、`ruleVersion`，也不显示来源或外链。

当前代码结构：

```text
wealth/src/features/stock-detail/news/
  api/
    stockDetailNewsApiClient.ts
    stockDetailNewsApiTypes.ts
    stockDetailNewsViewModelAdapter.ts
  StockDetailNewsPanel.tsx
```

Tab 容器仍由当前的 [StockInfoRail.tsx](/Users/congming/github/goldenshare/wealth/src/features/stock-detail/sidebar/StockInfoRail.tsx) 管理。页面只负责传入 `tsCode`、调用 API、处理四态并展示时间/标题；
不负责解析、排序、过滤或直接查询生产新闻表。

## 9. 当前代码落点与开发计划

已实现：

- [算法内核](../../src/foundation/news_linking/stock_news_linker.py)
- [算法单元测试](../../tests/test_stock_news_linker.py)
- [关联表 migration](/Users/congming/github/goldenshare/alembic/versions/20260823_000145_add_news_stock_link.py)
- [关联表 ORM](/Users/congming/github/goldenshare/src/foundation/models/core_serving/news_stock_link.py)
- [关联表 DAO](/Users/congming/github/goldenshare/src/foundation/dao/news_stock_link_dao.py)
- [物化服务](/Users/congming/github/goldenshare/src/ops/services/news_stock_linking_service.py)
- [TaskRun executor](/Users/congming/github/goldenshare/src/app/runtime/news_stock_linking_task_executor.py)
- [任务创建与窗口冻结](/Users/congming/github/goldenshare/src/ops/services/task_run_service.py)
- [dispatcher registered maintenance 分支](/Users/congming/github/goldenshare/src/ops/runtime/task_run_dispatcher.py)
- [股票详情新闻 query](/Users/congming/github/goldenshare/src/biz/queries/wealth/market/stock_detail/news_query.py)
- [股票详情新闻 API](/Users/congming/github/goldenshare/src/biz/api/wealth/market/stock_detail_news.py)
- [股票详情新闻前端 feature](/Users/congming/github/goldenshare/wealth/src/features/stock-detail/news/StockDetailNewsPanel.tsx)

批次级实时进度增强已经落在以下文件：

```text
src/ops/services/news_stock_linking_service.py       # 批次 commit 后发送累计进度
src/ops/runtime/maintenance_executor.py             # action-specific TaskRun 运行上下文契约
src/app/runtime/news_stock_linking_task_executor.py # 3 秒节流、终态 flush 和进度快照组装
src/ops/services/task_run_ingestion_context.py      # 复用独立 observer session
src/ops/runtime/task_run_dispatcher.py               # 保持最终结果写回与状态语义
frontend/src/pages/ops-task-detail-page.tsx          # 仅为新闻动作改善执行中展示
```

当前代码中的新闻 migration 为 `20260823_000145`，其 `down_revision` 为开发时核验的真实 head `20260823_000144`；
后续若新增 migration 仍必须重新读取当时真实 head，不能根据文件名、日期或印象猜测。现有 migration 只创建关联表和索引，
没有修改新闻源表、股票主数据表或历史名称表。

本次 `news_time` 范围与自动增量的实现落点：

```text
src/ops/action_catalog.py                              # 移除 mode/overlap，声明自然日手动范围和可配置日内周期
src/ops/queries/manual_action_query_service.py        # 新闻动作使用 calendar_date_range，不使用交易日范围
src/ops/services/manual_action_service.py             # 复用现有 start_date/end_date 校验与请求组装
src/ops/services/schedule_automation_capability_resolver.py # 暴露 Cron-only、每 N 分钟、默认 5/最小 3 分钟 capability
src/ops/services/operations_schedule_service.py       # 唯一 Schedule、启停校验、空窗口/并发合并跳过
src/ops/services/news_stock_linking_window_resolver.py # 集中冻结 manual_range/scheduled_incremental 窗口与成功游标
src/ops/services/task_run_service.py                  # 调用窗口解析器并删除旧 full/incremental/overlap 逻辑
src/ops/services/news_stock_linking_service.py        # news_time keyset 与 last_cursor
src/app/runtime/news_stock_linking_task_executor.py   # 新 payload、current_object.time.field=news_time
src/ops/runtime/task_run_dispatcher.py                # 清理 overlap 专属诊断合并口径
frontend/src/pages/ops-v21-task-manual-tab.tsx        # 展示自然日开始/截止日期
frontend/src/pages/ops-v21-task-auto-tab.tsx          # 允许运营配置每 N 分钟，推荐值 5
frontend/src/shared/api/types.ts                      # 对齐自动任务 capability 新增字段
```

不新增 migration，不修改关联表、股票详情新闻 API、Wealth 新闻 Tab 或算法规则。

### M0～M6 与实时进度增强的已完成实施顺序

1. **M0～M1**：完成边界冻结、migration、ORM、约束、`ts_code` 索引和批量 delete/upsert DAO。
2. **M2～M4**：完成词典加载、初版物化窗口、keyset 读取、批次事务、规则重算清理、TaskRun 游标和本地集成测试。
3. **M3～M6**：完成 action catalog、executor、worker/dispatcher 装配、股票详情新闻 API、排序契约和 Wealth 新闻 Tab。
4. **实时进度 P1（已完成）**：为物化服务增加“commit 后累计快照”回调，接入独立 observer session；补充首批立即写、3 秒节流、终态强制 flush 和 observer fail-soft。
5. **实时进度 P2（已完成）**：仅为新闻关联动作调整任务详情页的执行中展示，不改变其他任务的 unit/progress 语义。
6. **实时进度 P3（已完成）**：增加服务、executor、observer、dispatcher 和前端测试；本地验证现有 API、任务详情轮询和业务结果一致性。

本轮已按以下顺序收敛时间范围与自动增量：

1. **R0 契约门禁**：动作目录移除旧 `mode`，声明自然日 range 和 action-specific 日内间隔 capability，先锁定 API/消费者测试。
2. **R1 手动入口**：手动动作查询和页面改为自然日期起止，复用现有 range 校验。
3. **R2 窗口冻结**：新增专属 window resolver，冻结新 payload、成功基线和游标；删除旧 full/incremental/overlap 逻辑。
4. **R3 物化轴切换**：查询、排序、keyset、`last_cursor`、diagnostics 和 current object 全部切换到 `news_time`。
5. **R4 自动任务能力**：开放 Cron-only 日内周期，默认 5 分钟、最小 3 分钟；前端只消费通用 capability。
6. **R5 调度语义**：唯一 Schedule、active/paused 门禁、空窗口跳过、成功游标、并发触发合并。
7. **R6 回归清零**：覆盖手动、自动、服务、TaskRun、Schedule、前端配置和 Heat/其他 maintenance action；全仓清零旧消费者。

## 10. 测试与验收

### 10.1 已实现算法内核验收

当前 [算法测试](../../tests/test_stock_news_linker.py) 已覆盖：

1. 代码单独命中可以召回。
2. 全称单独命中可以召回。
3. 简称单独命中可以召回。
4. 简称冲突时按词典顺序只映射第一只股票。
5. 历史简称在新闻日期区间内命中，区间外和缺少新闻日期时不命中。
6. 三类规则同时命中时取并集并去重。
7. 一篇新闻可以关联多只股票。
8. 标题、正文和双字段 `source_field` 正确。
9. `match_method` 按固定优先级输出。
10. 无法映射的数字不召回。
11. 公司全称冲突时不召回。
12. 非股票证券不召回。
13. 全角/半角和空白标准化有效。
14. 空 `news_id` 和冲突词典行被拒绝。

“处理全部新闻、不按 `channels` 过滤”属于物化任务的输入范围验收，不是纯算法内核能够单独证明的行为。

### 10.2 关联物化任务验收

1. 手动历史范围读取 `core_serving_light.news` 指定 `news_time` 区间，包含和不包含 `channels='公司'` 的样本都进入识别。
2. 当前股票词典按 `ts_code ASC` 构建，历史名称按 `ts_code ASC, start_date ASC, row_key_hash ASC` 构建。
3. 每篇新闻只构造一次 linker，不逐条查询股票主数据，不逐股票扫描文本。
4. 批内相同 `(news_id, ts_code)` 只生成一条关系。
5. 关系表重复执行不产生重复行，并更新规则字段和 `updated_at`。
6. 同一 `news_id` 重新计算后关系消失时，处理批次会删除该 `news_id` 的旧派生关系；内容变化导致 `row_key_hash` 变化时按新新闻行处理，
   不在本期合并新旧新闻身份。
7. 失败批次回滚关联事务，不回滚新闻源写入；失败 TaskRun 不推进自动成功游标。
8. 相同范围重复处理不会改变最终关系集合；空识别结果会清理旧关系。
9. 历史简称严格按 `news_time` 日期和 `start_date/end_date` 判断。
10. 物化查询不再引用 `fetched_at`；keyset 固定为 `news_time ASC, row_key_hash ASC`，起点包含、上界排除。

性能边界：

1. 股票词典和自动机只构建一次。
2. 单篇新闻扫描不执行逐股票循环。
3. 单篇文本识别是内存计算，不包含数据库读写。
4. 批处理使用批量 upsert，不逐条提交事务。
5. 纯内存单篇新闻识别需要通过本地 benchmark 验证为毫秒级。

### 10.3 API 验收（当前实现）

当前 API 测试已覆盖或必须保持以下契约：

1. 按完整 `news_time DESC` 返回；同一完整时间戳按 `row_key_hash ASC` 稳定排序，不能按日期截断后排序。
2. 使用至少三条同一天但时分秒不同的样本验证严格倒序，例如 `10:30:05`、`10:30:04`、`10:29:59`。
3. 返回 `publishTime` 保留年月日时分秒和 `Asia/Shanghai` 偏移；不能只返回日期字符串。
4. 默认查询最近 2 个自然月，支持显式时间范围。
5. 默认 `limit=50`，超过 2000 截断到 2000，不分页；截断发生在排序之后。
6. 空结果不回退全量新闻，也不回退 `channels='公司'` 新闻。
7. 非法股票代码返回 404，非法时间范围和非法 limit 返回 400。
8. 普通响应不返回匹配内部字段；`debug=1` 返回 `matchMethod`。
9. 新闻模块异常不影响 K 线、盘口和资料模块。

### 10.4 前端验收（当前实现）

1. Right Tabs 为“盘口、资料、新闻”。
2. 新闻 Tab 位于当前 36px Tab 条内，不改变右侧信息栏整体宽度。
3. 新闻列表每项只有标题列和时间列。
4. 当年时间按 `Asia/Shanghai` 判断并显示 `MM-DD`，非当年显示 `YYYY-MM-DD`；时、分、秒不展示。
5. 使用至少三条同一天不同时间的乱序 mock/API 响应验证：页面展示顺序与 API 返回顺序完全一致，不进行二次排序。
6. 首次进入股票详情不请求新闻；点击 Tab 后才请求。
7. 加载、空结果、错误、正常结果四态可区分。
8. 新闻接口失败不影响 K 线、盘口、资料 Tab。

### 10.5 批次级实时进度增强验收（当前实现）

1. 每个成功提交的物化批次都能形成累计快照；首批立即可见，后续写回不超过每 3 秒一次，终态必有最终快照。
2. TaskRun 与当前 TaskRunNode 的 `rows_fetched/rows_saved/rows_deduplicated`、`current_object` 和诊断保持一致；中途快照不改变 `unit_done=0/1` 的单 unit 语义。
3. 业务批次 commit 前不写“已保存”统计；observer 写入失败不让业务批次失败、不回滚已提交关系。
4. dispatcher 最终结果与累计实时快照一致；失败、取消和未开始任务不推进成功游标。
5. 任务详情页对新闻动作显示累计已处理新闻和已生成关联；其他维护动作的原有进度展示回归通过。

### 10.6 手动范围与自动增量验收（当前实现）

1. 手动开始日包含当天零点，截止日包含整天并转换为上海次日零点；周末、节假日可以选择。
2. 缺少任一日期、日期格式错误或开始日晚于截止日返回 422，不能退回 Full 或默认窗口。
3. Full 通过覆盖全部历史的手动范围完成；请求和 executor 中不再出现旧 `mode=full/incremental`。
4. 自动任务只支持 Cron 日内间隔，默认建议 5 分钟、允许运营修改且最小 3 分钟；`active/paused` 启停立即生效。
5. 自动任务创建、更新、恢复和触发时都验证同一动作只有一条 Schedule；创建 active 或恢复时验证已有成功手动初始化基线。
6. 自动窗口严格为 `[上次成功 cursor_end, 本次实际触发时间)`；失败、取消、未开始任务不推进。
7. 手动任务覆盖当前日时，初始化 `cursor_end` 不超过 `task_frozen_at`；后续当日新闻仍能被自动增量读取。
8. 已有自动成功游标后，补跑旧手动范围不能改变自动游标。
9. retry 保留原任务的完整冻结窗口；窗口无新闻时不创建 TaskRun、不推进业务游标、不更新 `last_triggered_at`，下一次调度扩大窗口继续检查。
10. 已有 active TaskRun 时本次调度合并跳过，不报任务失败；下一次从上次成功游标追赶。
11. `last_cursor/current_object` 使用 `news_time + row_key_hash`；代码、诊断和页面中旧 `fetched_at/overlap_seconds` 口径清零。
12. 现有 Heat 自动任务、数据集日期策略、其他 maintenance action 和手动任务页面行为保持不变。

## 11. 依赖边界与状态

算法内核属于 `foundation`，只依赖 Python 标准库和自身类型。

当前依赖方向：

```text
foundation algorithm + model + DAO
              ▲
              │ ops linker service / TaskRun runtime
              │
          ops TaskRun / schedule

biz query/API ───────> foundation model/DAO
app ──────────────────> biz API router
wealth frontend ──────> biz API contract
```

依赖方向必须保持：`ops -> foundation`、`biz -> foundation`、`app -> biz`、`wealth -> biz API`。
禁止 `foundation -> ops|biz|app`，禁止 `ops -> biz`，禁止页面直接查询新闻表，禁止把主实现写入 `src/platform` 或 `src/operations`。

当前代码已完成：

1. 独立 `StockNewsLinker` 算法内核。
2. 代码、全称、简称并集匹配。
3. Aho-Corasick 多模式文本扫描。
4. 结果去重、匹配方式和来源字段输出。
5. 历史简称时间区间匹配。
6. 简称冲突按第一条词典记录映射。
7. 定向单元测试。
8. 关联表 migration、ORM、DAO 和幂等批次写入。
9. `news_time` 手动范围与成功游标自动增量物化任务、TaskRun 接入、窗口游标和并发防重。
10. 股票详情新闻 API、完整时间排序契约和 Wealth 新闻 Tab。
11. 本方案文档及算法链接。
12. 批次级实时进度写回和新闻动作专属执行中展示。

结案后的运营边界（不属于未完成需求）：

1. 生产部署、版本运行状态和历史桥接结果由实际运行记录负责，不由本方案状态代替。
2. 生产 Schedule 的创建、启用、暂停和更新间隔继续由运营配置，不由代码自动执行。
3. 后续规则版本变化或历史范围修正仍通过既有手动范围任务处理，不重新打开本需求。

## 12. 风险、边界与持续维护门禁

### 12.1 已接受的算法取舍

1. 这是确定性字符串召回，不识别语义角色；一篇新闻提到多只股票时全部建立关系。
2. 简称是子串匹配，简称本身较短时可能产生误召回；本期不引入人工审核、分数或模型来补偿这一点。
3. 全称冲突跳过，简称冲突取第一条；这不是概率判断，不能向页面解释为“置信度”。
4. 历史名称依赖 `namechange` 的时间区间事实；区间缺失、重叠或数据错误时，算法只按已加载词典顺序处理，不自行推断真实更名日期。

### 12.2 开发及生产切换时采用的核验事实

这些是开发与生产切换时采用的门禁记录，不是当前未完成事项，也不是重新发起的业务方案选项：

1. 本次时间契约变更不新增 migration；若实现过程中发现必须改表，必须停止并重新核验真实 Alembic head和方案边界。
2. 用生产只读样本确认 `core_serving_light.news`、`security_serving`、`namechange` 三者的 join 字段和时间类型一致。
3. 2026-08-23 已对 `core_serving_light.news` 的 `news_time` 范围与 `news_time,row_key_hash` keyset 执行生产只读 `EXPLAIN`：命中
   `idx_raw_tushare_news_time` 并使用 Incremental Sort 处理同时间戳 tie-breaker；没有执行 `ANALYZE`，本轮不增加新闻表索引或 migration。
4. 验证手动历史范围的新闻行数、关联结果行数、跳过原因和任务耗时；这些验证用于上线安全，不用于决定是否做这个功能。
5. 验证 `news_stock_link` API 查询在 50 条和 2000 条上限下的查询计划和响应时间。
6. 增强上线后确认 TaskRun 页面计数与关联表已提交批次一致；不能把页面瞬时快照当成物理表实时 count。
7. 创建自动任务前确认已存在成功的手动初始化范围；自动任务实际间隔、启用和暂停由运营在页面配置。
8. 升级切换时，旧 `mode/fetched_at` Full TaskRun 不作为新游标。若旧 Full 已成功，无需重跑全部历史；部署新代码后手动执行一个覆盖
   “旧 Full 冻结时间至当前时间”所在自然日期的桥接范围，成功后再创建或恢复自动 Schedule。

### 12.3 本轮实现的外部影响

原实现轮次修改新闻物化 action、TaskRun 窗口解析、物化查询轴、Schedule 能力和自动任务页面；没有修改数据库结构、识别算法、关联表、
股票详情新闻 API、Wealth 新闻 Tab 或市场总览新闻。部署、生产 Schedule 和生产回填属于该轮次之外的运营动作。

2026-08-23 本地验收结果：新闻关联及直接回归套件 `269 passed`；前端 typecheck、规则检查、`149` 条单元测试、生产构建和 `13` 条 smoke 全部通过。默认全仓 `pytest -q` 仍受两个既有收集问题阻塞；隔离收集后的其余仓库测试为 `1984 passed, 10 failed, 10 skipped`，失败均位于本需求白名单外，未在本轮修复。生产只读 `EXPLAIN` 已确认 `news_time` 索引路径可用，未执行 `ANALYZE` 或任何写入。

### 12.4 拍板项审计

当前没有未决业务口径：5 分钟推荐间隔、最小 3 分钟、运营自行配置、上海自然日截止日期包含整天、按 `news_time` 推进、晚到旧时间新闻手动补跑、每批删除后重建均已确认。

本地验证结果已记录在第 12.3 节。2026-09-01 用户已确认本需求结案，本文没有待开发、待上线或待拍板事项；后续 Schedule 调整和历史范围补跑按既有运营能力处理。
