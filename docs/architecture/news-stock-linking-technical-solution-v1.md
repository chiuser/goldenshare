# 新闻—个股关联技术方案 v1

## 文档状态

- 文档类型：技术方案
- 当前状态：算法内核已实现；关联表、批处理任务、业务 API 与 Wealth 页面尚未实施
- 方案范围：从生产新闻内容生成个股关联，并在财势乾坤股票详情页提供个股新闻
- 当前事实源：代码、测试和当前数据模型
- 方案权威性：本方案记录已确认的目标设计；未实现部分不能作为当前运行事实

本次文档修订只做两件事：补全整体技术方案，并把已实现的算法接口、匹配行为和测试事实写准确。数据库、任务、API、
前端和生产回填仍属于后续实施，不因本方案写完整而被视为已实现。

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

本期不做：

1. 不识别新闻中的主要对象和次要对象，不设计 `relation_type`。
2. 不设计人工审核流，不设计 `decision_status`。
3. 不设计 `match_score`，不使用未经样本校准的伪概率。
4. 不建立证据表，不保存命中原文片段和命中位置。
5. 不使用大模型、分类模型或语义角色识别。
6. 不修改 `core_serving_light.news` 的现有新闻事实表。
7. 不在页面请求时执行文本识别。
8. 当前未实现数据库迁移、生产回填、任务调度、业务 API 或前端页面；本方案只定义它们的实施设计。

## 2. 当前代码事实

### 2.1 新闻事实

当前新闻 serving-light 模型为 `core_serving_light.news`，主键是 `row_key_hash`，字段包括：

```text
row_key_hash, src, news_time, title, content,
channels, score, source, fetched_at
```

模型位置：[NewsLight](/Users/congming/github/goldenshare/src/foundation/models/core_serving_light/news.py)

现有市场总览的个股新闻查询只使用 `channels = '公司'` 做新闻分类筛选，没有按股票代码关联，返回的 `subject` 为空。因此它不能直接作为股票详情页新闻查询实现。

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
`wealth/src/features/stock-detail/sidebar/StockInfoRail.tsx` 渲染。现有 Right Tabs 只有“盘口”和“资料”，
当前 `.right-tabs` CSS 高度为 36px。股票详情现有真实 API 已接入 `page-init` 和 `kline`，新闻不应塞入这两个接口，
应作为独立模块接口按 Tab 懒加载。

当前后端路由聚合位置为 `src/app/api/v1/router.py`；股票详情业务 API、查询和 schema 分别位于
`src/biz/api/wealth/market/stock_detail.py`、`src/biz/queries/wealth/market/stock_detail/` 和
`src/biz/schemas/wealth/market/stock_detail.py`。新闻模块应按同一 `wealth/market/stock_detail` 分层新增，
不能回到旧的 `/api/v1/quote/detail/*` 或复用市场总览新闻接口。

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

建议新增物理表：

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
| `updated_at` | `timestamptz` | 是 | 关联最近计算时间 | 重叠窗口和规则重跑时更新；用于判断派生结果是否被重新计算 |

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
2. 新闻按 `fetched_at ASC, row_key_hash ASC` 读取并切成有限大小的内存批次；具体 batch size 属于内部性能参数，不暴露给页面。
3. 每个批次先收集本批 `news_id`，在关联表事务中删除这些新闻的旧关系，再批量 upsert 本批新关系并提交。
4. 批次失败只回滚当前关联表事务；TaskRun 标记失败且不推进游标，下一次会通过重叠窗口安全重跑已提交批次。
5. 不把新闻源写入和关联表写入放在同一个事务中，不让关联识别失败阻塞新闻源 ingestion。

处理范围是 `core_serving_light.news` 的全部新闻，不加 `channels = '公司'` 过滤。`channels` 仍保留在新闻事实中，
但它只是新闻分类字段，不是个股关联召回条件。

### 6.3 全量与增量

1. 首次执行处理当前生产新闻范围，生成关联表。
2. 增量任务使用 `fetched_at` 作为到达游标，使用 `news_time` 作为页面排序、时间范围过滤和历史简称生效日期判断。
3. 下一次任务的开始点为上次成功窗口结束点减去一个固定重叠窗口，首版建议为 1 小时；窗口按半开区间 `[window_start, window_end)` 执行。
4. 重叠窗口用于吸收源端延迟到达、重复拉取和边界时间精度差异，不代表重复展示；重复新闻会被关联表主键去重。
5. 写入必须幂等，重复处理同一新闻不会产生重复关联。
6. 规则版本变化时，按新版本重新处理目标新闻范围。
7. TaskRun 记录本次实际处理的 `window_start/window_end`、重叠时长、词典版本、输入新闻数、输出关联数、清理旧关联数和失败信息。

新闻源写入和关联表写入必须是两个独立事务。关联任务失败不得阻塞或回滚新闻源数据写入。

#### 6.4 TaskRun 与幂等 upsert 的具体含义

例如：

```text
上次成功窗口：10:00 ~ 10:15
本次重叠窗口：1 小时
本次处理窗口：09:15 ~ 10:30
```

`09:15 ~ 10:00` 的新闻会再次被识别。若某条新闻已经生成 `(news_id, 600519.SH)`，再次处理时：

1. 第一次处理：插入一行。
2. 重叠重跑：命中主键 `(news_id, ts_code)`，不新增第二行，而是更新 `match_method/source_field/rule_version/updated_at`。
3. `created_at` 保留首次生成时间，`updated_at` 反映最近一次规则计算时间。

因此，TaskRun 记录的是“这次任务处理了哪个窗口、使用了哪套规则、产生了多少结果”，关联表记录的是“最终新闻和股票的当前派生关系”，
两者职责不同。只做 upsert 不能清理“新闻内容更新后已经不再命中”的旧关系，所以每批写入前还要按本批 `news_id` 删除旧派生关系，
再批量 upsert 当前识别结果；这仍然只修改 `news_stock_link`，不修改新闻源事实。这里的旧关系清理针对同一个 `news_id` 的规则重算；
由于当前新闻 hash 包含标题和正文，内容变化生成新 `news_id` 的版本生命周期属于新闻源数据治理范围，不在本期偷偷合并。

#### 6.5 TaskRun 字段映射与运行边界

当前仓库已有 `ops.task_run`，模型位置为 `src/ops/models/ops/task_run.py`。本需求不新增 TaskRun 表、不新增独立的
`news_stock_task_run` 表，也不把 TaskRun 变成新闻关联业务表。

实现时应把新闻关联注册为现有 Ops TaskRun 主链中的一个 `maintenance_action` 派生维护动作，固定动作键为
`maintenance.materialize_news_stock_links`。该类任务不属于现有 `DatasetDefinition` 数据集维护主链，因此
`TaskRun.resource_key` 保持为空，`request_payload_json.target_key` 保存动作键；不得为了复用数据集页面而伪造一个
`news_stock_link` 数据集。动作注册、任务创建、dispatcher 执行和 worker 装配必须复用当前
`src/ops/action_catalog.py`、`TaskRunCommandService`、`TaskRunDispatcher` 和 `ops_worker_factory` 的现行契约，
不在业务查询层私自创建任务记录。

建议的 `request_payload_json` 结构如下。它是任务请求快照，记录本次任务打算处理什么：

```json
{
  "target_key": "maintenance.materialize_news_stock_links",
  "mode": "incremental",
  "window_start": "2026-08-22T09:15:00+08:00",
  "window_end": "2026-08-22T10:30:00+08:00",
  "overlap_seconds": 3600,
  "rule_version": "news-stock-rule-v1",
  "news_scope": "all"
}
```

字段落点：

| TaskRun 现有字段 | 新闻关联任务用途 |
|---|---|
| `request_payload_json` | 保存精确的 `mode/window_start/window_end/overlap/rule_version/news_scope` 请求快照 |
| `resource_key` | 为空；该派生维护动作不冒充 `DatasetDefinition` 数据集 |
| `filters_json` | 不设置 `channels='公司'`；如果保留过滤结构，明确写 `channels='all'` |
| `rows_fetched` | 本次读取并处理的新闻行数 |
| `rows_saved` | 本次关联表提交的关系行数 |
| `rows_rejected` | 新闻行无法处理或批次失败的行数；未知股票名称不是人工审核状态 |
| `rows_deduplicated` | 批内重复 `(news_id, ts_code)` 关系数量 |
| `ingestion_diagnostics_json` | `matched_news_count`、`links_inserted`、`links_updated`、`links_deleted`、`overlap_seconds` 等运行统计 |
| `current_object_json` | 当前批次的窗口、批次序号和阶段展示信息 |

规则如下：

1. 最近一次成功的 `window_end` 才能成为下一次增量任务的游标；失败或取消的 TaskRun 不推进游标。
2. 没有成功游标时执行全量初始化，不通过猜测时间点跳过历史新闻。
3. 同一 `news_stock_link` 资源同一时刻只允许一个运行中的维护任务，避免两个任务同时清理和重建相同新闻批次。
4. TaskRun 的状态和观测写入失败不得回滚或阻塞新闻事实写入；关联表事务也不能反向污染 `raw_*` 或 `core_serving_light.*`。
5. TaskRun 只记录任务意图和运行观测；新闻关联的业务事实唯一存放在 `core_serving.news_stock_link`。

## 7. API 设计

### 7.1 股票详情新闻接口

建议新增：

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

### 7.2 查询逻辑

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

## 8. Wealth 页面接入

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

目标代码结构：

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

## 9. 未来代码落点

已实现：

- [算法内核](../../src/foundation/news_linking/stock_news_linker.py)
- [算法单元测试](../../tests/test_stock_news_linker.py)

后续实现目标：

```text
alembic/versions/<next_revision>_add_news_stock_link.py
src/foundation/models/core_serving/news_stock_link.py
src/foundation/dao/news_stock_link_dao.py
src/ops/action_catalog.py                  # 注册 maintenance_action
src/ops/services/news_stock_linking_service.py
src/app/runtime/news_stock_linking_task_executor.py
src/app/runtime/ops_worker_factory.py      # 装配现有 worker 的 maintenance executor
src/ops/runtime/task_run_dispatcher.py     # 接入 registered maintenance action 单元执行
src/biz/queries/wealth/market/stock_detail/news_query.py
src/biz/schemas/wealth/market/stock_detail_news.py
src/biz/api/wealth/market/stock_detail_news.py
src/app/api/v1/router.py                   # 接入 biz router
wealth/src/features/stock-detail/news/**
wealth/src/features/stock-detail/sidebar/StockInfoRail.tsx  # 增加 Tab 容器分支
```

本次只读核对到的 Alembic head 是 `20260822_000143`；真正开发迁移前必须再次执行 head 检查，
`down_revision` 只能接当时真实 head，不得根据文件名、日期或印象猜测。迁移只创建关联表和索引，不改新闻源表、
股票主数据表或历史名称表。

### 实施顺序

1. **基础表与 DAO**：新增关联表 migration、ORM model、约束、`ts_code` 索引和批量 delete/upsert DAO；先完成 migration head 核对。
2. **派生任务**：注册 `maintenance.materialize_news_stock_links`，把 `StockNewsLinker` 接到 Ops TaskRun 现有主链，读取全量新闻、当前股票词典和历史名称词典；先做一批内存识别，再在单独关联事务中清理并 upsert。现有 registered maintenance executor 分支对非回放动作默认构造板块热度单日 unit，必须先增加通用 unit 计划入口或为该动作增加明确分支，不能直接复用 `_single_day_heat_unit`。
3. **初始化回填**：手动创建一次全量 TaskRun，记录窗口、规则版本、输入新闻数和关系写入数；不得在新闻源 ingestion 事务中顺便写关联表。
4. **增量维护**：全量成功后启用按 `fetched_at` 游标和 1 小时重叠窗口的增量 TaskRun；失败不推进游标。
5. **业务 API**：新增独立 stock-detail/news query、schema、router，并接入 `src/app/api/v1/router.py`。
6. **前端 Tab**：在现有 Right Tabs 增加新闻分支，按当前 `tsCode` 懒加载 API，完成加载、空结果、错误和日期格式测试。
7. **验收**：先做后端接口契约和关联表只读验收，再做前端浏览器验收；未完成生产回填和页面验收前，不标记整体需求完成。

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

1. 全量模式读取 `core_serving_light.news` 全部新闻，包含和不包含 `channels='公司'` 的样本都进入识别。
2. 当前股票词典按 `ts_code ASC` 构建，历史名称按 `ts_code ASC, start_date ASC, row_key_hash ASC` 构建。
3. 每篇新闻只构造一次 linker，不逐条查询股票主数据，不逐股票扫描文本。
4. 批内相同 `(news_id, ts_code)` 只生成一条关系。
5. 关系表重复执行不产生重复行，并更新规则字段和 `updated_at`。
6. 同一 `news_id` 重新计算后关系消失时，处理批次会删除该 `news_id` 的旧派生关系；内容变化导致 `row_key_hash` 变化时按新新闻行处理，
   不在本期合并新旧新闻身份。
7. 失败批次回滚关联事务，不回滚新闻源写入；失败 TaskRun 不推进增量游标。
8. 重叠窗口重复处理不会改变最终关系集合。
9. 历史简称严格按 `news_time` 日期和 `start_date/end_date` 判断。

性能边界：

1. 股票词典和自动机只构建一次。
2. 单篇新闻扫描不执行逐股票循环。
3. 单篇文本识别是内存计算，不包含数据库读写。
4. 批处理使用批量 upsert，不逐条提交事务。
5. 纯内存单篇新闻识别需要通过本地 benchmark 验证为毫秒级。

### 10.3 API 验收

后续 API 必须覆盖：

1. 按完整 `news_time DESC` 返回；同一完整时间戳按 `row_key_hash ASC` 稳定排序，不能按日期截断后排序。
2. 使用至少三条同一天但时分秒不同的样本验证严格倒序，例如 `10:30:05`、`10:30:04`、`10:29:59`。
3. 返回 `publishTime` 保留年月日时分秒和 `Asia/Shanghai` 偏移；不能只返回日期字符串。
4. 默认查询最近 2 个自然月，支持显式时间范围。
5. 默认 `limit=50`，超过 2000 截断到 2000，不分页；截断发生在排序之后。
6. 空结果不回退全量新闻，也不回退 `channels='公司'` 新闻。
7. 非法股票代码返回 404，非法时间范围和非法 limit 返回 400。
8. 普通响应不返回匹配内部字段；`debug=1` 返回 `matchMethod`。
9. 新闻模块异常不影响 K 线、盘口和资料模块。

### 10.4 前端验收

1. Right Tabs 从“盘口、资料”增加为“盘口、资料、新闻”。
2. 新闻 Tab 位于当前 36px Tab 条内，不改变右侧信息栏整体宽度。
3. 新闻列表每项只有标题列和时间列。
4. 当年时间按 `Asia/Shanghai` 判断并显示 `MM-DD`，非当年显示 `YYYY-MM-DD`；时、分、秒不展示。
5. 使用至少三条同一天不同时间的乱序 mock/API 响应验证：页面展示顺序与 API 返回顺序完全一致，不进行二次排序。
6. 首次进入股票详情不请求新闻；点击 Tab 后才请求。
7. 加载、空结果、错误、正常结果四态可区分。
8. 新闻接口失败不影响 K 线、盘口、资料 Tab。

## 11. 依赖边界与状态

算法内核属于 `foundation`，只依赖 Python 标准库和自身类型。

未来依赖方向：

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

本轮已完成：

1. 独立 `StockNewsLinker` 算法内核。
2. 代码、全称、简称并集匹配。
3. Aho-Corasick 多模式文本扫描。
4. 结果去重、匹配方式和来源字段输出。
5. 历史简称时间区间匹配。
6. 简称冲突按第一条词典记录映射。
7. 定向单元测试。
8. 本方案文档及算法链接。

本轮未完成：

1. 关联表迁移和 ORM 模型。
2. 生产新闻历史回填。
3. 增量关联任务和 TaskRun 接入。
4. 股票详情新闻 API。
5. Wealth 股票详情页新闻模块。

未完成项不能标记为当前已实现。

## 12. 风险、边界与实施前门禁

### 12.1 已接受的算法取舍

1. 这是确定性字符串召回，不识别语义角色；一篇新闻提到多只股票时全部建立关系。
2. 简称是子串匹配，简称本身较短时可能产生误召回；本期不引入人工审核、分数或模型来补偿这一点。
3. 全称冲突跳过，简称冲突取第一条；这不是概率判断，不能向页面解释为“置信度”。
4. 历史名称依赖 `namechange` 的时间区间事实；区间缺失、重叠或数据错误时，算法只按已加载词典顺序处理，不自行推断真实更名日期。

### 12.2 实施前必须核验的事实

这些是开发验收门禁，不是重新发起的业务方案选项：

1. 重新检查 Alembic 当前 head，再生成关联表 migration。
2. 读取生产只读样本确认 `core_serving_light.news`、`security_serving`、`namechange` 三者的 join 字段和时间类型一致。
3. 确认 `fetched_at` 作为增量到达游标时，源新闻刷新是否会对新行和重抓行更新时间；若实际语义不同，必须先修正游标口径再开发任务。
4. 验证全量回填的新闻行数、关联结果行数、跳过原因和任务耗时；这些验证用于上线安全，不用于决定是否做这个功能。
5. 验证 `news_stock_link` API 查询在 50 条和 2000 条上限下的查询计划和响应时间。

### 12.3 当前未发生的外部影响

本方案修订没有写数据库、没有创建 migration、没有注册 TaskRun、没有修改 API 路由、没有修改 Wealth 页面，
也没有执行生产回填。当前已实现的只有算法内核及其单元测试；其余全部是待实施设计。
