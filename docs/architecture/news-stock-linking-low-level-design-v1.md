# 新闻—个股关联低层设计 LLD v1

## 文档状态

- 文档类型：低层设计（LLD）
- 依据方案：[新闻—个股关联技术方案 v1](./news-stock-linking-technical-solution-v1.md)
- 审计基准：2026-08-23 当前工作区代码、测试和数据模型
- 当前状态：M0～M6 主链和批次级实时进度增强已实现；`news_time` 手动范围与可配置自动增量尚待开发
- 本文目的：记录当前实现事实，并给出下一轮时间范围与自动增量改造的文件落点、调用链、事务边界和验收契约

本文记录的是当前工作区代码事实，不据此宣称已经上线；生产迁移、回填、Schedule 启用和部署验收仍以实际运行记录为准。

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
| 物化时间轴 | 统一按 `news_time` 选择新闻、排序批次和推进 keyset；不再使用 `fetched_at` |
| 手动范围 | 必填上海自然日开始/截止日期；截止日期包含整天，转换为上海次日零点排他上界 |
| Full | 只是覆盖全部历史的手动范围，不保留独立 `full` 执行分支 |
| 自动增量 | 运营在“自动任务”自行创建；间隔可配置，推荐 5 分钟、最小 3 分钟；active/paused 即开关 |
| 自动游标 | `[上次成功 cursor_end, 本次实际触发时间)`；成功推进，失败/取消/未开始不推进 |

### 1.2 不需要用户拍板的实施边界

以下是代码实现约束，不是新的业务选项：

1. 关联结果属于派生维护动作，接入现有 `maintenance_action` TaskRun 主链，不伪造一个 `DatasetDefinition` 数据集。
2. 调度频率属于运营侧 Schedule 配置，不写死在业务 API 或算法内核中；没有 Schedule 时只能手动执行指定范围。
3. API 展示标题沿用当前市场新闻查询的显示口径：`title` 非空时使用 `title`，否则使用 `content` 去首尾空白后截取前 80 个字符。这个处理是显示字段归一化，不是标题去重。
4. `news_time` 同时负责物化范围、批次 keyset、历史名称生效判断、API 时间过滤和最终排序；`fetched_at` 只保留为新闻源事实字段。
5. 自动任务记录由运营部署后创建和启用；本次代码不能 seed、创建或修改生产 Schedule。

### 1.3 实施前门禁

这些事项需要开发时核验，但不阻塞本 LLD，也不构成新的产品拍板项：

- 创建 migration 前重新读取当时真实 Alembic head，`down_revision` 只能接真实 head。
- 用生产只读 SQL/EXPLAIN 核验 `news_time` 范围条件和 `news_time,row_key_hash` keyset 的查询计划。
- 全量回填前测量新闻行数、识别耗时、关联行数、批次提交耗时和 API 查询计划。
- 全新初始化上线前先完成一次成功手动历史范围物化；若已有旧 Full 结果，则按 12.13 执行桥接范围。之后再由运营创建唯一的新闻关联 Schedule 并配置间隔。

## 2. 当前代码审计结果

### 2.1 已实现部分

| 能力 | 当前代码 | 审计结论 |
|---|---|---|
| 识别内核 | `src/foundation/news_linking/stock_news_linker.py` | 已实现；无数据库、API、TaskRun 依赖 |
| 识别测试 | `tests/test_stock_news_linker.py` | 已覆盖代码、全称、简称并集、冲突、历史名称、边界、标准化和结果字段 |
| 新闻事实模型 | `src/foundation/models/core_serving_light/news.py` | 已存在；`news_time/fetched_at` 都是带时区 `DateTime`，`title/content` 可空 |
| 股票主数据模型 | `src/foundation/models/core_serving/security_serving.py` | 已存在；`ts_code` 主键，含 `symbol/name/fullname/security_type` |
| 历史名称模型 | `src/foundation/models/core_serving_light/namechange.py` | 已存在；含 `row_key_hash/ts_code/name/start_date/end_date` |
| 股票详情页面 | `wealth/src/pages/stock-detail/StockDetailPage.tsx` | 已存在；新闻不进入 page-init/K 线链路 |
| 右侧 Tab | `wealth/src/features/stock-detail/sidebar/StockInfoRail.tsx` | 已实现“盘口”“资料”“新闻”三个 Tab，保持 36px 高度 |
| 关联表/ORM/DAO | `alembic/versions/20260823_000145_add_news_stock_link.py`、`src/foundation/models/core_serving/news_stock_link.py`、`src/foundation/dao/news_stock_link_dao.py` | 已实现；主键 `(news_id, ts_code)`，只增加 `ts_code` 索引 |
| 物化服务 | `src/ops/services/news_stock_linking_service.py` | 已实现批次 delete/upsert、独立提交和实时进度；当前仍按 `fetched_at` 窗口/keyset，待切换 `news_time` |
| TaskRun executor | `src/app/runtime/news_stock_linking_task_executor.py`、`src/ops/runtime/maintenance_executor.py`、`src/ops/runtime/task_run_dispatcher.py` | 已实现；单窗口单 unit，批次进度通过 action-specific TaskRun 运行上下文写回，dispatcher 保留终态权威写回 |
| 股票详情新闻 API | `src/biz/queries/wealth/market/stock_detail/news_query.py`、`src/biz/api/wealth/market/stock_detail_news.py` | 已实现；完整 `news_time DESC` 和 `row_key_hash ASC` tie-breaker |
| Wealth 新闻 feature | `wealth/src/features/stock-detail/news/**` | 已实现；点击懒加载、AbortController、四态、原样保持 API 顺序 |
| Ops TaskRun 主链 | `src/ops/services/task_run_service.py`、`src/ops/runtime/worker.py`、`src/ops/runtime/task_run_dispatcher.py` | 已存在；支持 dataset、workflow、maintenance 三类任务 |
| 手动任务时间表单 | `src/ops/queries/manual_action_query_service.py`、`src/ops/services/manual_action_service.py` | 已支持 `start_date/end_date`；当前 maintenance range 被推导为交易日范围，新闻动作需声明自然日范围 |
| 自动任务能力 | `src/ops/services/schedule_automation_capability_resolver.py`、`src/ops/services/operations_schedule_service.py`、`frontend/src/pages/ops-v21-task-auto-tab.tsx` | 已支持 Schedule 启停和 Cron；普通 maintenance action 当前不开放每 N 分钟 |

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

因此股票详情新闻已经通过独立 query、schema、router 和前端 feature 实现，不能回退为修改现有总览查询来“顺便支持”详情页。

### 2.3 已修复的运行观测缺口

修复前，与用户观察到的“执行中页面像卡死”直接相关的缺口是：

1. `NewsStockLinkingService` 每批关联事务提交后没有向 TaskRun 写累计进度。
2. `NewsStockLinkingTaskExecutor` 只在整个物化 unit 完成后返回结果，dispatcher 因而只能在终态写 rows 和诊断。
3. 任务详情页虽然已有 3 秒轮询和 rows 指标，但新闻任务在执行中仍显示单 unit 的 `0/1` 和 `0%`，不能表达已完成的新闻批次。

这不是关联表正确性缺陷，而是运行观测延迟和单 unit 进度展示缺陷。当前实现已经通过批次 commit 后累计快照、独立
TaskRun observer、固定 3 秒节流和新闻动作专属页面展示修复；没有修改关联表、API 或算法规则。

### 2.4 本轮时间契约审计发现

| 当前代码点 | 当前行为 | 目标修改 |
|---|---|---|
| `src/ops/action_catalog.py` | 新闻动作参数为 `mode=full/incremental`，默认带 `overlap_seconds=3600` | 替换为手动 `start_date/end_date` 自然日范围；Schedule 静态参数为空 |
| `TaskRunCommandService._freeze_news_stock_linking_payload` | 用 `datetime.now()` 冻结上界；无成功游标自动 Full；增量起点减 1 小时 | 按 trigger source 解析 `manual_range/scheduled_incremental`，生成 `cursor_end`，无初始化基线拒绝自动任务 |
| `NewsStockLinkingService._fetch_news_batch` | `fetched_at` 范围、排序、keyset | `news_time` 范围、排序、keyset |
| `NewsStockLinkingStats.last_cursor` | `{fetched_at,row_key_hash}` | `{news_time,row_key_hash}` |
| `NewsStockLinkingTaskExecutor._freeze_payload` | 校验 `full/incremental` 和 overlap | 校验统一有限窗口与 `run_mode/window_field/cursor_end` |
| `current_object.time.field` | `fetched_at` | `news_time` |
| `ManualActionQueryService` | maintenance 的 `start_date/end_date` 映射为 `trade_date_range` | 新闻动作映射为 `calendar_date_range/calendar_day`，周末可选 |
| `ScheduleAutomationCapabilityResolver` | 普通 maintenance action 只开放日/周/月，允许 once | 新闻动作只开放 Cron 日内 `*/N`，推荐 5 分钟、最小 3 分钟 |
| `OperationsScheduleService` | 重复 active TaskRun 触发 409；允许多条新闻 Schedule | 自动触发时合并跳过；新闻动作只允许一条 Schedule |

以上均是待开发目标。关联表、识别内核、股票详情新闻 API、Wealth 新闻 Tab 和实时进度的基本事务隔离不需要重写。

## 3. 端到端调用链

```text
core_serving.security_serving
core_serving_light.namechange
core_serving_light.news
          │
          ▼
NewsStockLinkingService
  ├─ 构建一次股票/历史名称词典
  ├─ 按 news_time ASC, row_key_hash ASC 读取冻结窗口
  ├─ StockNewsLinker 内存识别
  └─ core_serving.news_stock_link 批量 delete + upsert
          │
          ▼
Ops TaskRun（maintenance_action）
  ├─ action: maintenance.materialize_news_stock_links
  ├─ 手动：上海自然日起止范围
  ├─ 自动：成功 cursor_end → 本次实际触发时间
  ├─ payload: run_mode、news_time 窗口、cursor_end、规则版本、news_scope
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

### 3.1 批次观测链修复前后对比

修复前的实际链路是：

```text
NewsStockLinkingService._materialize_batch
  └─ 关联事务 commit
       └─ materialize 累计 NewsStockLinkingStats
            └─ executor 完成整个窗口后返回 MaintenanceExecutionResult
                 └─ dispatcher 写 TaskRun / TaskRunNode 最终 rows 和 diagnostics
```

因此一个物化任务虽然只有一个 `MaintenanceExecutionUnit`，但即使关联表已经有前面批次的提交，任务详情页也看不到累计 rows。

当前已经实现的最小增强链路是：

```text
每个关联批次 commit 成功
  └─ 可选 BatchProgressSink（累计快照）
       └─ 独立 observer session 写 TaskRun / 当前 running TaskRunNode
            └─ 现有 TaskRun view API
                 └─ 现有任务详情页 3 秒轮询
```

该增强只增加运行中的观测写回，不改变单 unit 语义、业务事务、成功游标或最终 dispatcher 结果；运行期间仍保持
`unit_done=0、unit_total=1`，前端以不确定进度状态替代伪造百分比。

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
| `updated_at` | 每次重算时间 | 判断关系是否重算 | 支持手动补跑、失败重试和规则版本更新 |

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

内部窗口统一按 `news_time` 处理，采用半开区间 `[window_start, window_end)`，两个边界都是 aware datetime。

手动范围解析：

```python
zone = ZoneInfo("Asia/Shanghai")
window_start = datetime.combine(start_date, time.min, tzinfo=zone)
window_end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=zone)
task_frozen_at = now_utc
cursor_end = min(window_end.astimezone(UTC), task_frozen_at)
```

要求：

1. `start_date/end_date` 必填，格式为 `YYYY-MM-DD`，并且 `start_date <= end_date`。
2. 时间控件是 `calendar_date_range/calendar_day`，不能调用交易日历过滤周末和节假日。
3. Full 由运营选择覆盖全部历史的手动范围实现，代码中不保留 `window_start=None` 的 Full 分支。
4. `cursor_end` 只用于自动链初始化；手动任务实际处理范围仍是完整 `[window_start, window_end)`。

自动范围解析：

```text
window_start = 上一次成功 scheduled_incremental.cursor_end
               若尚无自动成功任务，则取成功 manual_range.cursor_end
window_end   = 本次 TaskRun 实际冻结时间
cursor_end   = window_end
```

只有 `status=success` 的任务可以提供游标。已有自动成功任务后，后续只看自动成功游标；人工补跑旧日期不能改变自动链。没有成功手动
初始化基线时，自动 Schedule 创建/恢复必须返回明确错误，不得静默执行 Full。

### 6.2 批次算法

每个批次执行以下顺序：

1. 查询新闻行的 `row_key_hash/news_time/title/content`，条件为 `news_time >= window_start AND news_time < window_end`，按
   `news_time ASC, row_key_hash ASC`，不加 `channels` 条件。
2. 使用本次任务启动时冻结的一个 `StockNewsLinker` 逐行识别；不逐股票扫描文本。
3. 收集本批 `news_id`，开启独立关联事务。
4. 删除 `news_stock_link.news_id IN (:batch_news_ids)` 的旧关系。
5. 对当前结果按 `(news_id, ts_code)` 去重后批量 upsert。
6. 提交关联事务；当前实现把本批统计合并到内存累计值，全部窗口完成后才回传给 TaskRun dispatcher。批次级实时进度增强时，
   仅在此 commit 成功之后调用 `BatchProgressSink` 写独立观测快照。

每批使用有限内存；batch size 是内部配置，不出现在用户 API。批次事务只覆盖关联表，新闻 view 不可写，也不与新闻 ingestion 共用事务。

Keyset 条件固定为：

```sql
AND (
  n.news_time > :cursor_news_time
  OR (n.news_time = :cursor_news_time AND n.row_key_hash > :cursor_news_id)
)
ORDER BY n.news_time ASC, n.row_key_hash ASC
LIMIT :batch_size
```

`last_cursor` 记录 `{news_time,row_key_hash}`。不得在查询、cursor、诊断或 current object 中继续使用 `fetched_at`。

### 6.3 幂等和失败恢复

同一新闻因手动补跑、失败重试或规则升级再次处理时：

1. 先删除该 `news_id` 的旧关系。
2. 再写入本次识别结果。
3. 相同 `(news_id, ts_code)` 不产生重复行，`created_at` 保持不变，规则字段和 `updated_at` 更新。
4. 如果本次识别结果为空，旧关系被删除。

当前批次失败时回滚当前关联事务；之前已提交批次可以保留。TaskRun 进入失败状态，不推进自动 `cursor_end`。重试同一冻结窗口时会
从窗口起点重新读取，已提交批次通过“删除后重建”和主键保持一致。

### 6.4 批次级进度写回的详细设计（已实现）

#### 6.4.1 目标和非目标

目标是让手动范围和自动增量任务执行期间看到“已经成功提交了多少新闻批次、生成了多少关联”，
而不是等待整个单 unit 完成后才看到最终数字。

本增强明确不做：

- 不新增 SSE、WebSocket、Redis、轮询接口或数据库表字段。
- 不改变 `StockNewsLinker`、召回规则、`match_method`、`source_field` 或 `rule_version`。
- 不改变 `unit_done/unit_total` 的含义，不把新闻行数换算成虚假的百分比。
- 不用物理表 count 作为进度来源；进度只统计已经 commit 成功的批次累计值。

#### 6.4.2 服务层接口和调用点

当前 `NewsStockLinkingService.materialize` 已有可选批次 sink；本轮仅同步它的窗口字段，不改变 sink 的事务和节流机制：

```python
materialize(
    *,
    window_start,
    window_end,
    rule_version,
    progress_sink: BatchProgressSink | None = None,
) -> NewsStockLinkingStats
```

sink 输入不是单批 delta，而是 commit 成功后的累计快照，至少包含：

```text
batch_index
rows_fetched
rows_saved
rows_deduplicated
matched_news_count
links_inserted
links_updated
links_deleted
unmatched_news_count
batch_count
last_cursor
window_start/window_end
run_mode/window_field=news_time/cursor_end
rule_version
news_scope=all
```

调用时序必须是：

```text
识别本批 → delete/upsert → 业务 session.commit() 成功
                         → 更新累计 stats
                         → sink(snapshot)
```

业务 commit 失败时不发送该批“保存成功”的快照；此前已发送的快照不回滚，因为它们对应此前已经提交的业务批次。

#### 6.4.3 Executor、dispatcher 和 observer session

当前实现由 `MaintenanceTaskRunContext` 保存 `task_run_id` 和既有 `IngestionRunContext`，由
`TaskRunAwareMaintenanceExecutor.execute_unit_for_task_run` 定义 action-specific 运行入口。dispatcher 只对
`maintenance.materialize_news_stock_links` 构造该上下文；`NewsStockLinkingTaskExecutor` 再把它转为 progress sink 传给 service。
该内部运行上下文不写入冻结的业务请求 payload，也不改变 `MaintenanceExecutionUnit` 的窗口契约。

observer 复用 `src/ops/services/task_run_ingestion_context.py` 的独立 session 机制。
observer 每次写入：

| 字段 | 写入口径 |
|---|---|
| `TaskRun.rows_fetched` | 已 commit 批次累计读取新闻数 |
| `TaskRun.rows_saved` | `links_inserted + links_updated` 累计 |
| `TaskRun.rows_rejected` | 固定为 0；未命中不是 rejected |
| `TaskRun.rows_deduplicated` | 已 commit 批次累计批内去重数 |
| `TaskRun.ingestion_diagnostics_json` | `NewsStockLinkingStats.as_diagnostics()` 加窗口、规则和 news scope |
| 当前 `TaskRunNode` 同名字段 | 与 TaskRun 同一次 observer snapshot 写入 |
| `current_object_json` | 当前窗口、批次序号、累计“已处理新闻/已生成关联” |
| `unit_done/unit_total` | 保持 `0/1`，直到 dispatcher 终态提交 |

`current_object_json` 必须遵循现有 `TaskRunIngestionContext` 的 `entity/time/attributes` 形状，不能直接塞任意 payload，建议快照为：

```json
{
  "entity": {"kind": "enum", "name": "新闻—个股关联"},
  "time": {
    "start": "2026-08-23T00:00:00+08:00",
    "end": "2026-08-23T19:01:16+08:00",
    "field": "news_time"
  },
  "attributes": {
    "enum_value": "批次 12：已处理新闻 12000，已生成关联 42752"
  }
}
```

这样既能通过现有 observer 的结构化清洗，也能被现有任务详情查询层转换为标题、处理范围和字段；详细的动作专属文案由前端按
`target_key` 和 rows/diagnostics 组合展示，不把内部 `news_id` 或正文放进 current object。

observer 事务与业务关联事务隔离；observer 连接、序列化或写入失败只记录日志并继续业务处理，不能让已提交关联回滚。
dispatcher 在成功、失败和取消路径仍负责最终状态和最终统计写回，最终值必须与 service 返回的累计 stats 一致。

#### 6.4.4 节流和终态 flush

为避免每个小批次都产生 TaskRun 写入压力，sink 使用以下确定策略：

1. 第一批成功提交后立即写一次，让页面尽快脱离全 0 快照。
2. 后续快照距离上次 observer 调用不足 3 秒时只保留内存最新值，不立即写库；终态 flush 会再次尝试最新快照。
3. 达到 3 秒时写最新累计快照；不按批次数新增配置项，3 秒是本功能固定观测节流常量。
4. service 返回成功或抛出失败时，executor 的 `finally` 强制 flush 最后一份已提交累计快照；运行中收到取消请求时沿用现有
   maintenance 单 unit 取消边界，executor 退出后同样经过该 `finally`，worker 再确定 canceled 终态。
5. 强制 flush 仍是 best-effort；若 observer 不可用，业务结果和 TaskRun 终态不能被反向破坏。

这里的“实时”定义为页面现有 3 秒轮询周期叠加最多约 3 秒 observer 节流，不承诺每个批次立即可见，也不引入实时消息通道。

#### 6.4.5 任务详情页展示

`frontend/src/pages/ops-task-detail-page.tsx` 已经每 3 秒刷新 TaskRun view，并展示 `rows_fetched/rows_saved/rows_deduplicated`；
`TaskRunViewResponse.run.action_key` 已可用于识别本动作。后端批次快照已接通，这些指标会随轮询更新。当前 action-specific 展示继续保持：

- 新闻动作执行中显示“已处理新闻 N / 已生成关联 M”和当前批次描述。
- 进度条使用不承诺总量的进行中状态，或者只显示“执行中”，不显示伪造的新闻百分比。
- 非新闻动作继续使用现有 unit/progress 展示，不改变通用任务页面契约。

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

手动任务的 `time_input_json` 保留运营输入的自然日期：

```json
{
  "mode": "range",
  "start_date": "2026-08-01",
  "end_date": "2026-08-23"
}
```

冻结后的 `request_payload_json` 不再保留旧 `mode/overlap_seconds`，统一为可执行窗口：

```json
{
  "target_type": "maintenance_action",
  "target_key": "maintenance.materialize_news_stock_links",
  "run_mode": "manual_range",
  "window_field": "news_time",
  "window_start": "2026-07-31T16:00:00Z",
  "window_end": "2026-08-23T16:00:00Z",
  "cursor_end": "2026-08-23T11:01:16Z",
  "task_frozen_at": "2026-08-23T11:01:16Z",
  "rule_version": "news-stock-rule-v1",
  "news_scope": "all"
}
```

自动任务只把 `run_mode` 改为 `scheduled_incremental`；`window_start/window_end/cursor_end` 由后端在每次触发时冻结，不能持久化在
Schedule 的 `params_json` 中。`task_frozen_at` 是本次冻结时的 UTC 时间；`cursor_end` 的计算规则见 6.1。

### 7.2 Dispatcher 和 executor 契约

当前 `TaskRunDispatcher` 已为该动作规划一个独立的新闻窗口 unit，并已接通批次级进度。时间范围改造保持这条链不变，只替换冻结窗口的来源：

1. `TaskRunCommandService` 不再自行推断旧 `full/incremental/overlap`；由新闻窗口解析器返回完整冻结 payload。
2. dispatcher 只消费已经冻结的 `window_start/window_end/run_mode`，不重新读取成功游标，也不根据执行开始时间改写边界。
3. `NewsStockLinkingTaskExecutor.plan()` 和 `execute_unit()` 必须校验 `window_field=news_time`、两个边界均为 aware datetime 且
   `window_start < window_end`；发现旧字段或无限窗口直接失败，不做兼容转换。
4. executor 继续把 `MaintenanceTaskRunContext` 转为 `BatchProgressSink`；进度、observer session、3 秒节流和终态 flush 保持现状。
5. 最终统计继续由 dispatcher 写入 TaskRun/TaskRunNode；业务关系批次和 TaskRun 状态仍使用隔离事务。

### 7.3 Action catalog 与手动任务入口

在 `src/ops/action_catalog.py` 注册：

```text
key             = maintenance.materialize_news_stock_links
executor_key    = news_stock_linking
schedule_enabled = true
manual_enabled   = true
retry_enabled    = true
target_tables   = core_serving.news_stock_link
```

同时删除 `NEWS_LINK_MODE_PARAM`，为该动作声明以下两项有类型的能力元数据；其他维护动作使用默认值，不改变现有行为：

```text
manual_time_regime = natural_day_range
schedule_repeat_policy = {
  allowed_modes: [intraday_interval],
  default_mode: intraday_interval,
  default_interval_minutes: 5,
  minimum_interval_minutes: 3,
  timezone: Asia/Shanghai
}
```

`parameters` 使用必填的 `start_date/end_date`，不再暴露 `mode`。`ManualActionQueryService._time_form_from_maintenance_action()` 必须根据
`manual_time_regime=natural_day_range` 返回：

```text
mode = range
control = calendar_date_range
selection_rule = calendar_day
date_field = news_time
```

不能继续沿用当前所有 maintenance range 都返回的 `trade_date_range/trading_day_only`；新闻在周末和节假日同样允许被选择。
`ManualActionTaskRunResolver` 继续复用已有 range 必填、日期格式和 `start_date <= end_date` 校验，再由新闻窗口解析器完成上海时区边界转换。

### 7.4 自动任务能力与运营配置

自动任务继续使用现有 `OpsSchedule` 表、API 和“自动任务”页面，不新增配置表、环境变量或代码内定时器。能力解析器把上述
`schedule_repeat_policy` 映射到 `AutomationCapability.repeat_policy`：

```json
{
  "allowedModes": ["intraday_interval"],
  "defaultMode": "intraday_interval",
  "defaultIntervalMinutes": 5,
  "minimumIntervalMinutes": 3,
  "timezone": "Asia/Shanghai"
}
```

`frontend/src/pages/ops-v21-task-auto-tab.tsx` 只消费这个通用 capability 决定是否展示“日内间隔”，不能按新闻 action key 硬编码。
运营部署后在现有页面创建一条配置，推荐值为：

```text
target_type     = maintenance_action
target_key      = maintenance.materialize_news_stock_links
schedule_type   = cron
trigger_mode    = schedule
cron_expr       = */5 * * * *
timezone        = Asia/Shanghai
calendar_policy = NULL
params_json     = {}
probe_config    = {}
```

间隔由运营在页面修改，默认建议 5 分钟，沿用当前日内间隔最小 3 分钟的门禁。`status=active/paused` 就是自动物化开关；代码不创建、
不启用、也不部署这条 Schedule。该 action 最多保留一条未删除 Schedule；修改间隔或开关必须编辑、暂停或恢复原配置，创建第二条返回 409。

`OperationsScheduleService` 对该 action 增加窄校验：

1. 只允许 `trigger_mode=schedule`、`schedule_type=cron`、`calendar_policy=NULL`、空 `params_json/probe_config`。
2. `cron_expr` 必须是现有日内间隔格式 `*/N * * * *`，且 `N >= 3`；时区固定 `Asia/Shanghai`。
3. 创建 active Schedule 或恢复 paused Schedule 前，必须存在成功的手动基线任务；否则返回清晰的 422，不静默 Full。
4. 创建时校验唯一 Schedule；更新时不得通过改 target 绕过唯一性。

### 7.5 新闻窗口解析器

新增 `src/ops/services/news_stock_linking_window_resolver.py`，集中负责手动与自动窗口冻结，避免继续扩张
`TaskRunCommandService._freeze_news_stock_linking_payload()`。输入至少包含当前已有的 `trigger_source`（`manual/scheduled/retry`）、
`time_input_json`、`schedule_id` 和 `task_frozen_at`，输出 7.1 的完整 payload。`trigger_mode=schedule` 是 Schedule 配置字段，不能与
TaskRun 实际保存的 `trigger_source=scheduled` 混用。

手动路径：

1. 读取自然日期 `start_date/end_date`。
2. 按 6.1 转成上海时区 `[开始日 00:00, 截止日次日 00:00)`，再序列化为 UTC aware datetime。
3. `run_mode=manual_range`，`cursor_end=min(window_end, task_frozen_at)`。
4. 无论范围内是否有新闻都允许创建任务；零新闻任务正常成功并记录 0 行，但不会覆盖已有自动成功游标。

自动路径：

1. 先查询该 action 最新成功的 `scheduled_incremental.cursor_end`；一旦存在，只允许它作为 `window_start`。
2. 尚无自动成功时，取所有成功 `manual_range` 中最大的 `cursor_end` 作为初始化基线；不存在则拒绝创建或恢复自动任务。
3. `window_end=task_frozen_at`，`cursor_end=window_end`，不增加 overlap，也不回看 `fetched_at`。
4. 成功终态后，该 TaskRun 才能成为下一次游标来源；`failed/canceled/canceling/queued/running` 均不能推进。

最大 `manual_range.cursor_end` 而不是“最后完成的手动任务”，可以避免后完成的旧日期补跑把首次自动起点向后倒退。已有自动成功后，任何人工补跑都不能改变自动链。

重试路径不重新解析当前时间或成功游标。`trigger_source=retry` 必须复制并严格校验原 TaskRun 已冻结的
`run_mode/window_field/window_start/window_end/cursor_end/task_frozen_at`；手动重试和自动重试都处理原窗口。自动任务重试成功后可以按原
`cursor_end` 进入成功游标链，失败或取消仍不推进。

### 7.6 空窗口、并发和调度合并

自动触发在创建 TaskRun 前使用同一个冻结窗口执行轻量存在性查询：

```sql
SELECT 1
FROM core_serving_light.news
WHERE news_time >= :window_start
  AND news_time < :window_end
LIMIT 1;
```

- 没有新闻：不创建空 TaskRun，不推进业务 `cursor_end`；只按现有调度事务推进 Schedule 的 `next_run_at`，不更新
  `last_triggered_at`。下一次触发仍从上次成功游标开始，窗口自然扩大。
- 已有同 action 的 `queued/running/canceling` TaskRun：自动调度不创建第二个任务、不记失败，只合并本次触发并推进 `next_run_at`；运行任务完成后的下一次触发会从成功游标追上。
- 手动提交遇到同 action 活跃任务：继续返回 409，让运营明确选择等待或取消；不能把人工意图静默吞掉。
- 自动预检发现有新闻后，TaskRun 创建边界仍要二次执行活跃任务检查，关闭并发竞态窗口。

防重按 `request_payload_json.target_key` 判断，不能依赖始终为空的 `resource_key`。调度合并只改变该 action 的 schedule enqueue 分支；其他
maintenance action 继续保持现有冲突和失败处理。

TaskRun 只记录意图和观测；关系表才是业务派生事实。TaskRun 写入失败不能回滚已经提交的新闻关联批次，也不能阻塞新闻源表。

### 7.7 旧口径清零

本轮直接删除以下旧契约和消费者，不保留兼容分支：

- `mode=full/incremental`
- `overlap_seconds`
- 首次 incremental 静默转 Full
- `fetched_at` 窗口、keyset、last cursor 和 current object field
- Schedule 中预先持久化固定 `window_start/window_end`

历史 TaskRun 仍可作为只读运行记录展示，但不能再被新窗口解析器选为成功游标；只有带 `run_mode/window_field/cursor_end` 新契约的成功任务可作为基线。

## 8. 股票详情新闻 API

### 8.1 文件和路由（当前实现）

当前文件：

```text
src/biz/queries/wealth/market/stock_detail/news_query.py
src/biz/schemas/wealth/market/stock_detail_news.py
src/biz/api/wealth/market/stock_detail_news.py
```

路由：

```http
GET /api/v1/wealth/market/stock-detail/news
```

`src/app/api/v1/router.py` 已 include 新闻 router。鉴权复用股票详情的 `require_quote_access`，数据库 session 复用 `get_db_session`。

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

### 9.1 现有入口（当前实现）

当前 `StockInfoRail` 的状态是：

```tsx
const [activeTab, setActiveTab] = useState<"quote" | "profile" | "news">("quote");
```

`StockInfoRail` 已包含 `news`。`StockDetailPage` 继续负责股票详情主数据和 K 线，不把新闻请求塞进 page-init/kline 的加载 Promise。

### 9.2 前端文件

```text
wealth/src/features/stock-detail/news/
  api/stockDetailNewsApiTypes.ts
  api/stockDetailNewsApiClient.ts
  api/stockDetailNewsViewModelAdapter.ts
  StockDetailNewsPanel.tsx
  stock-detail-news.css
```

当前已修改：

```text
wealth/src/features/stock-detail/sidebar/StockInfoRail.tsx
wealth/src/pages/stock-detail/StockDetailPage.tsx   # 当前无需修改；主页面不承载新闻请求
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

### 10.2 物化服务与范围任务（本轮需更新）

`tests/test_news_stock_linking_service.py` 和 `tests/test_news_stock_task_runtime.py` 至少覆盖：

1. 手动范围按上海时区开始日 00:00 包含、截止日次日 00:00 排除；截止日 23:59:59 新闻被处理，次日 00:00 不处理。
2. 范围选择、排序、keyset 和 `last_cursor` 全部使用 `news_time`；构造 `fetched_at` 与 `news_time` 顺序相反的反例证明不会误用旧字段。
3. 完全相同 `news_time` 时按 `row_key_hash ASC` 稳定推进；跨 batch 不漏行、不重复读取。
4. `channels='公司'`、其他频道、周末和节假日新闻全部处理，不调用交易日历过滤。
5. 股票词典和历史名称词典顺序稳定，历史名称仍按上海日期 `news_time.date()` 判断有效期。
6. 一个 batch 内同一关系只写一次；同一范围重复运行不增加关系行。
7. 重算时先删除本批新闻旧关系再写当前结果；规则变化、空识别结果都能清理旧关系。
8. 失败批次回滚当前关系事务，但不回滚已提交批次和新闻源；失败、取消、未开始任务均不推进自动游标。
9. payload 中出现旧 `mode/overlap_seconds`、`window_field != news_time`、naive datetime 或无限窗口时明确失败，不做兼容转换。
10. 单篇识别不包含逐股票循环；本地 benchmark 只衡量内存识别，不混入数据库时间。

### 10.3 API（当前实现）

当前测试已覆盖或必须保持：

1. 同一天至少三条不同 `时:分:秒` 的新闻按完整 `news_time DESC` 返回。
2. 完全相同 `news_time` 的 tie-breaker 按 `row_key_hash ASC`。
3. `publishTime` 保留完整时间和上海时区偏移。
4. 默认最近 2 个自然月；显式时间窗口为半开区间。
5. `limit` 默认 50，超过 2000 截断到 2000，截断发生在排序之后；不生成分页游标。
6. 不按 `channels` 二次过滤，不按标题去重，不重新识别正文。
7. 普通响应不含 debug 字段，`debug=1` 只含 `matchMethod`。
8. 空结果、股票不存在、参数错误和查询异常符合约定 HTTP 语义。

### 10.4 前端（当前实现）

当前测试已覆盖或必须保持：

1. Tab 顺序和 36px 高度正确。
2. 首次进入不请求新闻，点击后才请求。
3. API 返回三个同日不同时间的乱序样本时，页面严格保持数组顺序。
4. 上海时区跨年日期格式正确：当前年 `MM-DD`，其他年 `YYYY-MM-DD`。
5. 列表只有标题列和日期列，时分秒不展示。
6. 加载、空结果、错误和正常结果四态可区分。
7. 切换股票时旧请求取消，旧新闻不泄漏到新股票。

### 10.5 批次级实时进度增强（当前实现回归）

既有测试必须继续直接证明以下细节，不能只验证最终 TaskRun 成功：

1. `NewsStockLinkingService` 在每批业务 `commit()` 成功后才调用 sink；commit 失败的批次不会发送“已保存”快照。
2. sink 接收的是累计 `rows_fetched/rows_saved/rows_deduplicated`、累计诊断和最新 `last_cursor`，不会把单批 delta 当成全量值覆盖前一批。
3. 第一批成功立即写 observer；连续高频批次按 3 秒节流；成功、失败、取消路径都会执行最终 flush。
4. observer session 写入失败时，业务批次仍可提交，service 仍返回正确累计 stats，失败不会污染业务事务。
5. TaskRun/TaskRunNode 中途保持 `unit_done=0、unit_total=1`，rows 和 current object 可更新；executor 最终结果覆盖中间快照且数值一致。
6. 任务详情页对新闻 action 显示累计“已处理新闻/已生成关联”或不确定进度状态；其他 action 的原有 `unit_done/progress_percent` 展示不变。
7. 现有 TaskRun view API 不需要新增字段或路由，3 秒轮询能够读到 observer 写入的现有字段。

新增反例：进度诊断、`last_cursor` 和 `current_object.time.field` 必须显示 `news_time`，不得残留 `fetched_at` 或 `overlap_seconds`。

### 10.6 手动入口、自动能力与调度（本轮新增）

后端：

1. `tests/test_ops_action_catalog.py`：新闻 action 只有必填 `start_date/end_date`，声明自然日范围和可配置日内间隔；旧 `mode` 清零。
2. `tests/web/test_ops_manual_actions_api.py`：返回 `calendar_date_range/calendar_day/news_time`；周末日期可提交；缺少边界、倒置范围和非法日期返回 422。
3. `tests/test_ops_automation_capability.py`：只对声明该能力的 maintenance action 返回 `intraday_interval`，默认 5 分钟、最小 3 分钟；其他 action 契约不变。
4. `tests/web/test_ops_schedule_api.py`：推荐配置可创建、编辑、暂停、恢复；小于 3 分钟、非上海时区、非空日期策略/参数、第二条同 action Schedule 均被拒绝。
5. 无成功手动基线时 active 创建/恢复失败；基线存在时成功。首次自动起点取最大成功手动 `cursor_end`，已有自动成功后忽略后续手动补跑。
6. 自动触发冻结 `[last_success_cursor_end, task_frozen_at)`；仅 success 推进。failed/canceled/queued/running 的 payload 不能被选为游标。
7. retry 保留原任务全部冻结窗口和 `task_frozen_at`，不因重试发生时间变化而扩大窗口；重试成功后原 `cursor_end` 可进入自动成功链。
8. 自动窗口无新闻时不创建 TaskRun、只推进 `next_run_at` 且不更新 `last_triggered_at`；下一次窗口仍从旧游标开始。窗口有新闻才创建一个 TaskRun。
9. 已有 `queued/running/canceling` 时自动触发被合并且不产生失败 TaskRun；手动提交仍返回 409；竞态二次检查不能创建重复任务。
10. 旧 full/incremental TaskRun 不作为新游标；Schedule 的 `params_json` 中不得出现冻结窗口字段。

前端：

1. `frontend/src/pages/ops-v21-task-manual-tab.test.tsx` 验证新闻动作只显示自然日开始/截止日期，截止日期文案明确“包含当天”。
2. `frontend/src/pages/ops-v21-task-auto-tab.test.tsx` 验证页面由 `repeat_policy` 展示可配置日内间隔，默认 5、最小 3；不按 action key 特判。
3. 自动任务详情能显示当前 cron、开关状态和时区；不出现手动日期输入、新闻窗口或 overlap 参数。

## 11. 开发顺序与交付边界

### 11.1 当前实现基线

1. 关联表、ORM、DAO、算法内核、词典加载、批次 delete/upsert、独立事务、实时进度、股票详情 API 和新闻 Tab 已实现，继续复用。
2. 当前 M3/M4 的 `mode=full/incremental`、`fetched_at` 游标、overlap 和首次自动 Full 已被本方案废止，是本轮必须替换的代码事实，不能视为目标验收。
3. 现有 API 的完整 `news_time DESC, row_key_hash ASC` 排序和前端保持数组顺序不变；它们与本轮物化窗口改造没有契约冲突。

### 11.2 已完成的批次级实时进度增强

实现严格按以下顺序完成，没有引入额外功能：

1. **P0 运行上下文契约**：为新闻 executor 定义只供运行时使用的 `task_run_id`/progress context；不修改业务请求快照、unit payload、TaskRun 表或 API schema。
2. **P1 服务层 sink**：在 `NewsStockLinkingService` 中增加可选 `BatchProgressSink`；严格按“业务 commit 成功 → 更新累计 stats → sink”调用。
3. **P2 观测写回**：复用 `TaskRunIngestionContext` 的独立 observer session，写 TaskRun 和当前 running node 的 rows、diagnostics、current object；
   observer 异常 fail-soft，业务事务不受影响。
4. **P3 节流与终态**：实现首批立即写、后续最多 3 秒一次、成功/失败/取消强制 flush；保持 `unit_done=0/1` 语义。
5. **P4 任务详情展示**：只对 `maintenance.materialize_news_stock_links` 显示累计“已处理新闻/已生成关联”和不确定进度状态；其他任务页面逻辑不变。
6. **P5 测试与本地验收**：完成 commit 时序、累计统计、observer 隔离、节流、终态、dispatcher 最终一致性和前端回归测试；验证现有 TaskRun view API 无需改契约。

### 11.3 本轮代码开发顺序

只按以下顺序修改，不扩展到其他动作或数据集：

1. **R0 契约门禁**：把 action catalog 的旧 `mode` 替换为自然日范围和日内间隔能力元数据；先更新 action catalog、manual action、automation capability 的契约测试。
2. **R1 手动入口**：修改 `src/ops/queries/manual_action_query_service.py`、必要 schema/adapter 和手动任务页面，使新闻动作输出并提交自然日 range；复用通用 resolver 的范围校验。
3. **R2 窗口冻结**：新增 `src/ops/services/news_stock_linking_window_resolver.py`；收敛手动/自动窗口、基线和成功游标查询；从
   `src/ops/services/task_run_service.py` 删除旧 full/incremental/overlap 冻结逻辑。
4. **R3 物化轴切换**：修改 `src/ops/services/news_stock_linking_service.py` 和 `src/app/runtime/news_stock_linking_task_executor.py`，把查询、keyset、统计、诊断和 current object 全部改为 `news_time`；保持 delete/upsert 和批次进度时序。
5. **R4 自动能力**：修改 `src/ops/services/schedule_automation_capability_resolver.py`、自动任务 response schema/type 和
   `frontend/src/pages/ops-v21-task-auto-tab.tsx`，由 capability 开放可配置日内间隔。
6. **R5 调度语义**：修改 `src/ops/services/operations_schedule_service.py` 及现有 scheduler enqueue 链，落实唯一 Schedule、基线门禁、空窗口跳过和活跃任务合并；不改其他 action 行为。
7. **R6 回归与清零**：更新 10.2、10.5、10.6 所列测试；全仓检索清零该 action 的旧字段消费者；执行后端定向/全量测试、前端 typecheck/test/build 和文档完整性检查。

预计修改文件严格限于上述真实调用链及对应 schema/types/tests；不修改算法内核、关联表模型/DAO、股票详情 API、Wealth 新闻 Tab、市场总览新闻和其他维护动作业务逻辑。

### 11.4 明确不在本轮开发范围

- 不新增 migration、表字段、证据表或 API 路由。
- 不修改 `StockNewsLinker`、新闻范围、历史名称规则、关联表主键或 API 新闻排序。
- 不修改市场总览新闻逻辑、K 线、盘口和资料 Tab。
- 不执行生产 migration、生产回填、Schedule 创建/启用或部署；运营部署后自行配置自动任务。

现有运行中任务不会热加载本轮待开发实现。旧契约成功任务也不会自动成为新 `news_time` 游标；部署后需按 12.9 的切换步骤建立一次新基线。

## 12. 风险与当前判断

1. 简称是子串匹配，短简称可能误召回；这是已接受的确定性规则取舍，不通过分数或人工状态掩盖。
2. 新闻源 `title/content` 可空，因此 API 必须使用确定的展示标题 fallback，避免详情页出现空标题。
3. `core_serving_light.news` 是 serving-light view，关系表必须保持独立写入；不能把关联写回新闻 ingestion。
4. 新闻 action 已绕过板块热度专用 unit 规划，并具备批次级观测写回和终态统计映射；其他 maintenance action 仍走原执行入口。
5. API 严格排序依赖完整 `news_time`；任何把时间转成日期后排序的实现都属于契约错误。
6. 规则版本变化时必须按窗口重算并清理旧关系；不能只 upsert 新命中，否则会残留旧关系。
7. 实时进度只代表已提交业务批次的累计快照，不能等同于数据库物理总行数；任务完成前不显示伪造百分比。
8. observer 失败采用 fail-soft，代价是页面可能短暂停留在上一个快照，但不能以观测可见性换取业务事务回滚。
9. 自动增量严格按 `news_time` 向前推进。若新闻在游标推进后才写入、但其 `news_time` 早于游标，自动任务不会回看；这是已接受限制，运营需手动补跑对应自然日期范围。
10. 自动任务无新闻或与活跃任务重叠时不创建失败/空 TaskRun；因此 Schedule 的触发次数不等于 TaskRun 数量，观测口径以实际创建任务和成功游标为准。
11. `core_serving_light.news` 当前已有 `news_time` 及 `(src, news_time)` 索引，本轮不计划 migration；开发验收仍需对范围 + keyset SQL 做 `EXPLAIN`，若未命中索引必须停下重新评审，不能顺手加索引。
12. 截止日期包含整天会生成可能晚于当前时间的 `window_end`；手动任务可以安全扫描完整范围，但基线使用
    `cursor_end=min(window_end, task_frozen_at)`，不能把尚未发生的当天后续时间误记为已覆盖。
13. 切换到新版本时，旧 Full 任务即使成功也没有新契约游标。无需重新跑全部历史；部署后应手动运行一个覆盖“旧 Full 冻结时间至当前时间”所在自然日期的范围任务，成功后再创建/恢复自动 Schedule。

当前没有新的业务口径需要拍板。开发门禁是：按第 11.3 节实现并通过测试后，由运营执行第 12.13 节的基线切换和自动任务配置；本轮文档不执行这些生产动作。
