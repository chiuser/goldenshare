# 新闻—个股关联低层设计 LLD v1

## 文档状态

- 文档类型：低层设计（LLD）
- 依据方案：[新闻—个股关联技术方案 v1](./news-stock-linking-technical-solution-v1.md)
- 审计基准：2026-08-23 当前工作区代码、测试和数据模型
- 当前状态：算法内核已实现；关联表、物化任务、股票详情新闻 API 和 Wealth Tab 尚未实现
- 本文目的：把技术方案拆成可直接开发、测试和验收的文件落点、调用链、事务边界和契约

本文不是当前实现说明。凡标记为“待实施”的内容，都不能据此宣称已经上线。

## 1. 审计结论与拍板项

### 1.1 结论

本次审计没有发现需要用户再次拍板的业务口径。以下内容已经由技术方案和此前讨论冻结：

| 主题 | 已冻结口径 |
|---|---|
| 新闻范围 | 处理 `core_serving_light.news` 全部新闻，包含 `channels = '公司'`，物化任务不按频道过滤 |
| 召回规则 | 代码、公司全称、当前简称、有效历史简称独立匹配，结果取并集；同一 `(news_id, ts_code)` 只保留一条 |
| 冲突处理 | 当前简称按词典输入顺序取第一条；全称冲突不召回；历史简称按有效候选输入顺序取第一条 |
| 历史名称 | 使用 `core_serving_light.namechange` 的 `start_date/end_date`；新闻日期按 `news_time` 的上海时区日期判断 |
| 关系字段 | 只保留 `match_method`、`source_field`、`rule_version`；不做 `relation_type`、`decision_status`、`match_score` 或证据表 |
| API | 默认最近 2 个自然月，默认 `limit=50`，最大 2000，不分页；支持显式时间范围 |
| 排序 | 后端按完整 `news_time DESC`，完全相同时间再按 `row_key_hash ASC`；前端严格按 API 数组顺序展示 |
| 展示 | 只展示标题和日期；当前年份显示 `MM-DD`，其他年份显示 `YYYY-MM-DD`；不展示时分秒 |

### 1.2 不需要用户拍板的实施边界

以下是代码实现约束，不是新的业务选项：

1. 关联结果属于派生维护动作，接入现有 `maintenance_action` TaskRun 主链，不伪造一个 `DatasetDefinition` 数据集。
2. 调度频率属于运营侧 Schedule 配置，不写死在业务 API 或算法内核中；没有调度配置时仍可手动执行全量或增量 TaskRun。
3. API 展示标题沿用当前市场新闻查询的显示口径：`title` 非空时使用 `title`，否则使用 `content` 去首尾空白后截取前 80 个字符。这个处理是显示字段归一化，不是标题去重。
4. `news_time` 与 `fetched_at` 分工固定：前者负责历史名称生效判断、API 时间过滤和最终排序；后者只负责物化任务的到达游标。

### 1.3 实施前门禁

这些事项需要开发时核验，但不阻塞本 LLD，也不构成新的产品拍板项：

- 创建 migration 前重新读取当时真实 Alembic head，`down_revision` 只能接真实 head。
- 用生产只读样本核验 `fetched_at` 是否会随新行和重抓行更新；若源端语义不同，先修正增量游标实现。
- 全量回填前测量新闻行数、识别耗时、关联行数、批次提交耗时和 API 查询计划。
- 上线前由运营配置维护动作的 Schedule 频率和并发策略。

## 2. 当前代码审计结果

### 2.1 已实现部分

| 能力 | 当前代码 | 审计结论 |
|---|---|---|
| 识别内核 | `src/foundation/news_linking/stock_news_linker.py` | 已实现；无数据库、API、TaskRun 依赖 |
| 识别测试 | `tests/test_stock_news_linker.py` | 已覆盖代码、全称、简称并集、冲突、历史名称、边界、标准化和结果字段 |
| 新闻事实模型 | `src/foundation/models/core_serving_light/news.py` | 已存在；`news_time/fetched_at` 都是带时区 `DateTime`，`title/content` 可空 |
| 股票主数据模型 | `src/foundation/models/core_serving/security_serving.py` | 已存在；`ts_code` 主键，含 `symbol/name/fullname/security_type` |
| 历史名称模型 | `src/foundation/models/core_serving_light/namechange.py` | 已存在；含 `row_key_hash/ts_code/name/start_date/end_date` |
| 股票详情页面 | `wealth/src/pages/stock-detail/StockDetailPage.tsx` | 已存在；当前只加载 page-init、日 K 线和按需分钟/九转数据 |
| 右侧 Tab | `wealth/src/features/stock-detail/sidebar/StockInfoRail.tsx` | 已存在；当前只有“盘口”和“资料”两个 Tab |
| Ops TaskRun 主链 | `src/ops/services/task_run_service.py`、`src/ops/runtime/worker.py`、`src/ops/runtime/task_run_dispatcher.py` | 已存在；支持 dataset、workflow、maintenance 三类任务 |

### 2.2 已存在但不能直接复用的部分

当前市场总览“个股新闻”链路位于：

- `src/biz/queries/wealth/market/news/stock_news_query.py`
- `src/biz/queries/wealth/market/news/news_query_service.py`
- `src/biz/api/wealth/market/stock_news.py`
- `wealth/src/features/market-overview/news/**`

它的真实语义是市场总览面板，不是股票详情页新闻：

1. 只查询 `channels = '公司'`。
2. 按展示标题做 `row_number()` 去重。
3. 没有 `tsCode` 请求参数，也没有 `news_stock_link` 关系表。
4. 返回的是市场面板结构，不是股票详情新闻响应。

因此股票详情新闻必须新增独立 query、schema、router 和前端 feature，不能修改现有总览查询来“顺便支持”详情页。

### 2.3 当前缺口

以下内容当前均不存在：

- `core_serving.news_stock_link` 表、migration、ORM model 和 DAO。
- 从新闻、股票主数据、历史名称构建词典并执行批处理的业务服务。
- `maintenance.materialize_news_stock_links` action、executor 和增量游标运行逻辑。
- `GET /api/v1/wealth/market/stock-detail/news`。
- `StockInfoRail` 的“新闻”Tab 分支、新闻 API client、列表 ViewModel 和日期格式化器。

## 3. 端到端调用链

```text
core_serving.security_serving
core_serving_light.namechange
core_serving_light.news
          │
          ▼
NewsStockLinkingService
  ├─ 构建一次股票/历史名称词典
  ├─ StockNewsLinker 内存识别
  └─ core_serving.news_stock_link 批量 delete + upsert
          │
          ▼
Ops TaskRun（maintenance_action）
  ├─ action: maintenance.materialize_news_stock_links
  ├─ payload: 窗口、游标、规则版本、news_scope
  └─ worker/dispatcher 记录执行状态和统计
          │
          ▼
GET /api/v1/wealth/market/stock-detail/news
  ├─ 查询关系表 + 新闻 view + 股票主数据
  ├─ 完整 news_time DESC
  └─ 返回完整 publishTime
          │
          ▼
StockInfoRail → 新闻 Tab
  ├─ 点击 Tab 后懒加载
  ├─ 原样渲染 API items
  └─ 只格式化日期，不重新排序
```

依赖方向保持：`foundation` 提供模型和算法，`ops` 执行派生任务，`biz` 提供查询/API，`app` 装配路由和 worker，`wealth` 只消费 API。

## 4. 关联表低层设计

### 4.1 表定义

目标表：`core_serving.news_stock_link`。

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

### 4.2 字段职责

| 字段 | 写入值 | 读取用途 | 必要性 |
|---|---|---|---|
| `news_id` | `NewsLight.row_key_hash` | 回连新闻事实、批次清理 | 新闻标题可变且可重复，不能用标题作身份 |
| `ts_code` | `Security.ts_code` | 股票详情页过滤 | 股票代码是稳定业务身份，不能用简称 |
| `match_method` | 三种确定性规则之一 | debug、规则回归 | 说明哪条规则最终产生关系，不表示置信度 |
| `source_field` | `title/content/title_and_content` | debug、故障定位 | 保留标题/正文来源，不需要证据表 |
| `rule_version` | 例如 `news-stock-rule-v1` | 规则升级重算 | 区分不同版本派生结果 |
| `created_at` | 首次插入时间 | 关系生命周期 | 与新闻发布时间不同，不能用 `news_time` 替代 |
| `updated_at` | 每次重算时间 | 判断关系是否重算 | 支持重叠窗口和规则版本更新 |

### 4.3 约束与 ORM/DAO 要求

1. ORM 文件放在 `src/foundation/models/core_serving/news_stock_link.py`，模型只描述关系表，不复制新闻和股票展示字段。
2. `news_id` 不加外键：它指向 `core_serving_light.news` view，当前发布方式不适合用跨域物理 FK 阻塞写入。
3. `ts_code` 第一版使用逻辑引用和写入前主数据校验，不新增跨 serving 域外键。
4. DAO 必须提供“按一批 `news_id` 删除旧关系”和“批量 upsert 当前关系”两个操作。
5. upsert 冲突键只能是 `(news_id, ts_code)`；冲突更新 `match_method/source_field/rule_version/updated_at`，不更新 `created_at`。
6. 一批新闻即使识别结果为空，也必须先删除这批新闻原有关系，避免规则重算后残留旧关系。
7. migration 只新增这张表和索引，不修改 `core_serving_light.news`、`security_serving` 或 `namechange`。

## 5. 识别内核与词典适配

### 5.1 当前内核的真实行为

`StockNewsLinker` 当前已经实现以下行为：

1. 代码使用有边界的六位数字表达式，支持裸代码和 `.SH/.SZ/.BJ` 后缀，最终必须回到股票词典确认。
2. 全称、当前简称和历史简称共同进入一个 Aho-Corasick 自动机；标题和正文分别扫描一次。
3. 文本先做 Unicode NFKC、大小写归一和空白删除。
4. 全称映射到多个股票时跳过该全称；当前简称冲突时按传入词典顺序取第一条。
5. 历史简称只有在 `start_date <= news_date <= end_date` 时命中，`end_date IS NULL` 表示持续有效。
6. 非 `EQUITY` 证券被过滤；空新闻 ID 和冲突的重复股票词典行抛出 `ValueError`。
7. 同一股票同时命中多条规则时只返回一条，`match_method` 按 `CODE_EXACT > FULL_NAME_EXACT > SHORT_NAME_EXACT` 取最强规则。
8. 标题和正文都命中时返回 `source_field=title_and_content`；结果最后按 `ts_code ASC` 输出。

内核只负责内存识别，不读取数据库、不提交事务、不写 TaskRun，也不负责 API 排序。

### 5.2 词典加载顺序

`NewsStockLinkingService` 每次任务启动只加载一次词典：

```sql
SELECT ts_code, symbol, name, fullname, security_type
FROM core_serving.security_serving
WHERE security_type = 'EQUITY'
ORDER BY ts_code ASC;
```

```sql
SELECT row_key_hash, ts_code, name, start_date, end_date
FROM core_serving_light.namechange
ORDER BY ts_code ASC, start_date ASC, row_key_hash ASC;
```

适配规则：

1. 空代码、空名称、非股票证券不进入词典。
2. `end_date < start_date` 的历史区间不传给内核，并在任务诊断中计为无效词典行；不能把它当成新闻待审核状态。
3. 历史名称只保留 `ts_code` 能在当前股票词典找到的记录。
4. SQL 排序负责把“第一条”变成可复现顺序；内核继续保持“调用方输入顺序决定第一条”的纯函数语义。
5. 词典和自动机不能在每条新闻循环中重新构建。

### 5.3 单篇识别适配

```python
news = NewsRecord(
    news_id=row.row_key_hash,
    title=row.title,
    content=row.content,
    news_date=row.news_time.astimezone(SHANGHAI).date(),
)
links = linker.link(news)
```

服务层不得根据 `channels` 增删规则，也不得在 linker 返回后按频道、标题或“是否公司新闻”二次过滤。`StockNewsLink` 直接映射为关系表写入行。

## 6. 物化任务与事务边界

### 6.1 处理窗口

内部窗口按 `fetched_at` 处理，采用半开区间 `[window_start, window_end)`：

- 全量：不设置上次游标，按 `fetched_at ASC, row_key_hash ASC` 分批读取全部新闻。
- 增量：上次成功 TaskRun 的 `request_payload_json.window_end` 是游标；本次 `window_start = previous_window_end - overlap`，`window_end` 为本次任务创建时冻结的当前时间。
- 首版 `overlap_seconds = 3600`，只用于增量窗口吸收延迟和边界重复，不改变 API 展示时间范围。
- `window_end` 只能从成功 TaskRun 推进；失败、取消和未开始的任务不能成为新游标。

`news_time` 不参与增量游标。它只用于历史名称日期、API 时间范围和页面排序。这样新闻晚到但发布时间较早时，仍能在 `fetched_at` 重叠窗口内被处理。

### 6.2 批次算法

每个批次执行以下顺序：

1. 查询新闻行的 `row_key_hash/news_time/title/content/fetched_at`，按 `fetched_at ASC, row_key_hash ASC`，不加 `channels` 条件。
2. 使用本次任务启动时冻结的一个 `StockNewsLinker` 逐行识别；不逐股票扫描文本。
3. 收集本批 `news_id`，开启独立关联事务。
4. 删除 `news_stock_link.news_id IN (:batch_news_ids)` 的旧关系。
5. 对当前结果按 `(news_id, ts_code)` 去重后批量 upsert。
6. 提交关联事务，再把本批统计回传给 TaskRun worker。

每批使用有限内存；batch size 是内部配置，不出现在用户 API。批次事务只覆盖关联表，新闻 view 不可写，也不与新闻 ingestion 共用事务。

### 6.3 幂等和失败恢复

同一新闻在重叠窗口内再次处理时：

1. 先删除该 `news_id` 的旧关系。
2. 再写入本次识别结果。
3. 相同 `(news_id, ts_code)` 不产生重复行，`created_at` 保持不变，规则字段和 `updated_at` 更新。
4. 如果本次识别结果为空，旧关系被删除。

当前批次失败时回滚当前关联事务；之前已提交批次可以保留。TaskRun 进入失败状态，不推进 `window_end`。下一次重试会通过重叠窗口重新处理已提交边界，最终结果仍由主键和批次清理保证一致。

## 7. TaskRun 低层接入

### 7.1 任务身份

固定使用：

```text
task_type = maintenance_action
action = maintain
resource_key = NULL
request_payload_json.target_key = maintenance.materialize_news_stock_links
```

`resource_key` 为空是因为当前仓库的 `maintenance_action` 由 `request_payload_json.target_key` 标识，不能把非 DatasetDefinition 的关系表名称塞进 dataset resource 字段。这样也符合当前 `TaskRunCommandService` 对维护动作的校验和标题解析路径。

请求快照至少包含：

```json
{
  "target_type": "maintenance_action",
  "target_key": "maintenance.materialize_news_stock_links",
  "mode": "incremental",
  "window_start": "2026-08-22T09:15:00Z",
  "window_end": "2026-08-22T10:30:00Z",
  "overlap_seconds": 3600,
  "rule_version": "news-stock-rule-v1",
  "news_scope": "all"
}
```

### 7.2 当前 dispatcher 的扩展点和限制

当前 `TaskRunDispatcher` 已支持 registered maintenance executor，但 `_dispatch_registered_maintenance_action()` 对非回放动作默认调用 `_single_day_heat_unit()`，这是板块热度动作的专用 unit 形状，不能直接承载新闻窗口。

因此待实施代码必须明确完成以下一项等价改造：

1. 为 registered maintenance action 增加通用 `plan()` unit 入口；或
2. 为 `maintenance.materialize_news_stock_links` 增加明确的 action 分支，构造新闻窗口 unit。

推荐方案是新增 `NewsStockLinkingTaskExecutor`：

- `plan(request)` 返回一个冻结的新闻窗口 unit，unit payload 包含 `mode/window_start/window_end/overlap_seconds/rule_version/news_scope`。
- `execute_unit(unit)` 调用 `NewsStockLinkingService`，内部按批次处理；每批使用独立关联事务。
- executor 通过 `src/app/runtime/ops_worker_factory.py` 注入现有 `TaskRunDispatcher`，不新增 worker 进程或 worker 类型。
- TaskRun node 记录窗口、批次进度、输入新闻数、写入关系数、删除关系数、拒绝原因和最后错误。

当前 `MaintenanceExecutionResult.metadata` 虽然已经存在，但 dispatcher 当前只累计 `rows_fetched/rows_saved/rows_rejected`
和 `rejected_reason_counts`，不会自动把 `metadata` 写入 `TaskRun.ingestion_diagnostics_json`；`TaskRunDispatchOutcome` 也没有
`rows_deduplicated` 和诊断字段。因此实现新闻动作时必须同步扩展这条观测映射，至少把
`links_inserted/links_updated/links_deleted/rows_deduplicated/overlap_seconds` 聚合后写入 TaskRun 和当前 node，不能假设现有
registered executor 已经支持这些统计。

### 7.3 Action catalog 和并发

在 `src/ops/action_catalog.py` 注册：

```text
key             = maintenance.materialize_news_stock_links
executor_key    = news_stock_linking
schedule_enabled = true
manual_enabled   = true
retry_enabled    = true
target_tables   = core_serving.news_stock_link
```

调度配置使用现有 Schedule 能力。因为该动作的 `resource_key` 为空，防重不能依赖 `resource_key`；创建或触发任务时必须按 `request_payload_json.target_key` 判断同动作是否已有 `queued/running` 任务，保证同一时刻最多一个新闻关联任务处理游标和关系表。这个判断应放在 Ops 任务创建/调度边界，不放在业务 API 或 linker 内核。

TaskRun 只记录意图和观测；关系表才是业务派生事实。TaskRun 写入失败不能回滚已经提交的新闻关联批次，也不能阻塞新闻源表。

## 8. 股票详情新闻 API

### 8.1 文件和路由

待新增：

```text
src/biz/queries/wealth/market/stock_detail/news_query.py
src/biz/schemas/wealth/market/stock_detail_news.py
src/biz/api/wealth/market/stock_detail_news.py
```

路由：

```http
GET /api/v1/wealth/market/stock-detail/news
```

`src/app/api/v1/router.py` include 新 router。鉴权复用股票详情的 `require_quote_access`，数据库 session 复用 `get_db_session`。

### 8.2 请求参数

| 参数 | 类型 | 默认 | 处理规则 |
|---|---|---|---|
| `tsCode` | string | 必填 | `strip().upper()`；必须命中 `Security` 且 `security_type=EQUITY` |
| `startAt` | aware datetime | `endAt` 往前 2 个自然月 | 必须带时区偏移；归一到 `Asia/Shanghai` |
| `endAt` | aware datetime | 当前上海时间 | 必须带时区偏移；作为开区间上界 |
| `limit` | int | 50 | `<1` 返回 400；`>2000` 截断为 2000；不分页 |
| `debug` | 0/1 | 0 | `1` 时 item 返回 `debugInfo.matchMethod` |

时间窗口为 `[startAt, endAt)`。默认窗口是滚动的最近 2 个自然月，日期不足时按目标月份最后一天进行日历日期截断；不是按月份第一天和最后一天的固定自然月查询。

### 8.3 Query SQL

```sql
SELECT
    n.row_key_hash AS news_id,
    n.news_time AS publish_time,
    COALESCE(NULLIF(BTRIM(n.title), ''), SUBSTRING(BTRIM(n.content) FROM 1 FOR 80)) AS display_title,
    s.ts_code,
    s.name,
    l.match_method
FROM core_serving.news_stock_link AS l
JOIN core_serving_light.news AS n
  ON n.row_key_hash = l.news_id
JOIN core_serving.security_serving AS s
  ON s.ts_code = l.ts_code
WHERE l.ts_code = :ts_code
  AND n.news_time >= :start_at
  AND n.news_time < :end_at
ORDER BY n.news_time DESC, n.row_key_hash ASC
LIMIT :limit;
```

实现要求：

1. `news_time` 直接以带时区完整时间戳排序，精度保留到秒；不得 cast 成 date、截断到日或按展示字符串排序。
2. `row_key_hash ASC` 只在完整 `news_time` 完全相同时作为稳定 tie-breaker。
3. `LIMIT` 在 `ORDER BY` 之后执行。
4. 不按标题去重；两个不同 `news_id` 即使标题相同，也必须分别返回。
5. 关系表已经按 `(news_id, ts_code)` 去重，API 不再二次去重。
6. API 输出的 `publishTime` 保留完整时间和 `Asia/Shanghai` 偏移，例如 `2026-08-22T10:30:05+08:00`。
7. API 只读取 `news_id/news_time/title/content/ts_code/name/match_method` 所需字段，不扫描正文做二次识别。

### 8.4 Response schema

建议 schema：

```python
class StockDetailNewsDebugInfoDto(BaseModel):
    matchMethod: Literal["CODE_EXACT", "FULL_NAME_EXACT", "SHORT_NAME_EXACT"]


class StockDetailNewsItemDto(BaseModel):
    newsId: str
    publishTime: datetime
    title: str
    debugInfo: StockDetailNewsDebugInfoDto | None = None


class StockDetailNewsResponseDto(BaseModel):
    stockRef: StockDetailStockRefDto
    items: list[StockDetailNewsItemDto]
    meta: StockDetailNewsMetaDto
```

`meta.count` 是本次实际返回条数，不表示未分页的隐藏总数；`meta.limit/startAt/endAt` 记录本次请求生效参数。
普通响应不返回 `matchMethod/sourceField/ruleVersion`。`debug=1` 只返回 `matchMethod`，不返回证据片段、命中位置或内部规则以外的字段。

错误语义与现有股票详情保持一致：股票不存在或不是股票证券返回 404；时间、时区、范围和 limit 参数错误返回 400；查询异常返回 500，页面只让新闻 Tab 进入错误态。

## 9. Wealth 新闻 Tab 低层设计

### 9.1 现有入口

当前 `StockInfoRail` 的状态是：

```tsx
const [activeTab, setActiveTab] = useState<"quote" | "profile">("quote");
```

待改为包含 `news`。`StockDetailPage` 继续负责股票详情主数据和 K 线，不把新闻请求塞进 page-init/kline 的加载 Promise。

### 9.2 前端文件

```text
wealth/src/features/stock-detail/news/
  api/stockDetailNewsApiTypes.ts
  api/stockDetailNewsApiClient.ts
  api/stockDetailNewsViewModelAdapter.ts
  StockDetailNewsPanel.tsx
  stock-detail-news.css
```

需要修改：

```text
wealth/src/features/stock-detail/sidebar/StockInfoRail.tsx
wealth/src/pages/stock-detail/StockDetailPage.tsx   # 仅在确有状态上提需要时修改
```

### 9.3 加载和状态

1. 股票详情首次进入时不请求新闻。
2. 点击“新闻”Tab 后，以当前 `viewModel.stock.tsCode` 请求一次接口；切换股票时清空旧新闻状态并取消旧请求。
3. 使用 `AbortController` 防止快速切换股票后旧响应覆盖新股票。
4. Panel 至少区分 `loading / ready-empty / ready-items / error` 四态；错误只占用新闻 Tab 内容区。
5. `debug=1` 不由普通页面发送，也不在 UI 展示 debug 字段。

### 9.4 顺序和日期显示

ViewModel adapter 只做 DTO 映射，不做排序、过滤、截断、按日期分组或去重：

```ts
items: response.items.map((item) => ({
  newsId: item.newsId,
  publishTime: item.publishTime,
  title: item.title,
}))
```

日期格式化器使用 `Asia/Shanghai`：

```ts
const formatNewsDate = (publishTime: string, now = new Date()) => {
  const dateParts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(publishTime));
  const currentYear = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
  }).format(now);
  const year = dateParts.find((part) => part.type === "year")?.value ?? "";
  const month = dateParts.find((part) => part.type === "month")?.value ?? "";
  const day = dateParts.find((part) => part.type === "day")?.value ?? "";
  return year === currentYear ? `${month}-${day}` : `${year}-${month}-${day}`;
};
```

`publishTime` 中的时分秒不展示，但必须保留在 API DTO 和 ViewModel 中；它们已经在后端完成排序，前端不能用格式化后的日期文本重新排序。

### 9.5 视觉和布局

Tab 顺序固定为：

```text
盘口 | 资料 | 新闻
```

继续使用当前 `.right-tabs` 的 36px 高度和右侧信息栏宽度。新闻列表 item 为两列：左侧标题，右侧日期；标题超长时单行省略，日期列不压缩。不得新增固定宽度或改变右侧栏整体布局。

## 10. 测试和验收矩阵

### 10.1 算法内核（已有）

继续保留 `tests/test_stock_news_linker.py` 的现有覆盖：代码/全称/简称独立命中、并集去重、匹配优先级、source field、代码边界、简称第一条、历史名称区间、非股票过滤、文本标准化、输入错误。

### 10.2 物化任务（待新增）

至少新增：

1. 全量任务同时处理 `channels='公司'` 和其他频道新闻。
2. 股票词典和历史名称词典顺序稳定，简称冲突结果可复现。
3. 一个 batch 内同一关系只写一次。
4. 重叠窗口重复运行不增加关系行。
5. 规则重算后某新闻不再命中时，旧关系被删除。
6. 空识别结果也会删除旧关系。
7. 失败批次回滚当前关系事务，但不回滚已提交批次和新闻源。
8. 失败/取消 TaskRun 不推进成功窗口游标。
9. 单篇识别不包含逐股票循环；本地 benchmark 证明常规新闻为毫秒级内存识别，benchmark 不把数据库时间混入算法耗时。

### 10.3 API（待新增）

至少新增：

1. 同一天至少三条不同 `时:分:秒` 的新闻按完整 `news_time DESC` 返回。
2. 完全相同 `news_time` 的 tie-breaker 按 `row_key_hash ASC`。
3. `publishTime` 保留完整时间和上海时区偏移。
4. 默认最近 2 个自然月；显式时间窗口为半开区间。
5. `limit` 默认 50，超过 2000 截断到 2000，截断发生在排序之后；不生成分页游标。
6. 不按 `channels` 二次过滤，不按标题去重，不重新识别正文。
7. 普通响应不含 debug 字段，`debug=1` 只含 `matchMethod`。
8. 空结果、股票不存在、参数错误和查询异常符合约定 HTTP 语义。

### 10.4 前端（待新增）

至少新增：

1. Tab 顺序和 36px 高度正确。
2. 首次进入不请求新闻，点击后才请求。
3. API 返回三个同日不同时间的乱序样本时，页面严格保持数组顺序。
4. 上海时区跨年日期格式正确：当前年 `MM-DD`，其他年 `YYYY-MM-DD`。
5. 列表只有标题列和日期列，时分秒不展示。
6. 加载、空结果、错误和正常结果四态可区分。
7. 切换股票时旧请求取消，旧新闻不泄漏到新股票。

## 11. 实施顺序与交付边界

1. 核验 Alembic head，新增关联表 migration、ORM model、DAO 和 migration 测试。
2. 新增词典加载和 `NewsStockLinkingService`，先用固定小批次测试 delete/upsert、失败回滚和重叠窗口。
3. 注册 maintenance action，补齐 dispatcher 的通用新闻窗口 unit 入口，装配 executor 和 worker 测试。
4. 完成一次手动全量 TaskRun；记录输入新闻、识别新闻、关系写入、关系删除、拒绝原因、耗时和游标。
5. 全量成功后配置增量 Schedule；先观察失败重试、游标推进和重复关系数量，再开放详情 API。
6. 新增股票详情新闻 query/schema/router 和 API 契约测试。
7. 新增 Wealth 新闻 feature、Tab、四态和顺序/日期测试；最后做浏览器交互验收。

本 LLD 交付不包含 migration、生产回填、TaskRun 注册、API 路由或前端代码修改。它们必须按上述顺序另行实施和验证。

## 12. 风险与当前判断

1. 简称是子串匹配，短简称可能误召回；这是已接受的确定性规则取舍，不通过分数或人工状态掩盖。
2. 新闻源 `title/content` 可空，因此 API 必须使用确定的展示标题 fallback，避免详情页出现空标题。
3. `core_serving_light.news` 是 serving-light view，关系表必须保持独立写入；不能把关联写回新闻 ingestion。
4. 当前 dispatcher 对 registered maintenance action 的 unit 逻辑带有板块热度专用假设，这是实现前必须处理的真实代码限制。
5. API 严格排序依赖完整 `news_time`；任何把时间转成日期后排序的实现都属于契约错误。
6. 规则版本变化时必须按窗口重算并清理旧关系；不能只 upsert 新命中，否则会残留旧关系。

当前没有新的业务拍板项；下一步可以直接按本文 LLD 进入实现阶段，但实现开始前必须先完成第 1.3 节的技术门禁。
