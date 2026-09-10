# 新闻关联与股票详情事件展示维护说明（LLD）

更新：2026-09-10（现行代码对账与文档合并）。
状态：关联物化于 **2026-09-01** 结案，股票详情事件合并于 **2026-09-09** 经用户确认结案。本文不重新打开开发、生产回填或部署任务，也不以结案推断今天 Schedule 的启用状态。

原技术方案的算法理由、数据身份与两次验收证据已并入本文，旧全文从 Git 追溯。当前实现和历史记录分开：§1–10 为维护合同，§11 为当时证据，§12 为已接受的限制。总体职责仍为 Foundation 纯识别/模型、Ops 物化与调度、App 装配、Biz 查询事件合并、Wealth 只显示。

## 1. 业务边界

| 主题 | 已冻结口径 |
|---|---|
| 新闻范围 | 处理 `core_serving_light.news` 全部新闻，包含 `channels = '公司'`，物化任务不按频道过滤 |
| 召回规则 | 代码、公司全称、当前简称、有效历史简称独立匹配，结果取并集；同一 `(news_id, ts_code)` 只保留一条 |
| 冲突处理 | 当前简称按词典输入顺序取第一条；全称冲突不召回；历史简称按有效候选输入顺序取第一条 |
| 历史名称 | 使用 `core_serving_light.namechange` 的 `start_date/end_date`；新闻日期按 `news_time` 的上海时区日期判断 |
| 关系字段 | 只保留 `match_method`、`source_field`、`rule_version`；不做 `relation_type`、`decision_status`、`match_score` 或证据表 |
| API | 默认最近 2 个自然月，默认 `limit=50`，最大 2000，不分页；支持显式时间范围 |
| 事件合并 | raw 与关系表保留全部来源事实；Biz 查询层按同一股票的新闻事件合并，`limit` 作用于事件，前端不去重 |
| 排序 | 后端按完整 `news_time DESC`，完全相同时间再按 `row_key_hash ASC`；前端严格按 API 数组顺序展示 |
| 展示 | 只展示标题和日期；当前年份显示 `MM-DD`，其他年份显示 `YYYY-MM-DD`；不展示时分秒 |
| 物化时间轴 | 统一按 `news_time` 选择新闻、排序批次和推进 keyset；不再使用 `fetched_at` |
| 手动范围 | 必填上海自然日开始/截止日期；截止日期包含整天，转换为上海次日零点排他上界 |
| Full | 只是覆盖全部历史的手动范围，不保留独立 `full` 执行分支 |
| 自动增量 | 运营在“自动任务”自行创建；间隔可配置，推荐 5 分钟、最小 3 分钟；active/paused 即开关 |
| 自动游标 | `[上次成功 cursor_end, 本次实际触发时间)`；成功推进，失败/取消/未开始不推进 |

一篇新闻可对应多只股票，代码/全称/简称三路独立 OR，并非先命中代码就停止名称召回。不设计 relation_type、decision_status、match_score 或证据表：本期无语义角色、审核队列或可校准的置信度，source_field 足够说明命中来源。

原始新闻身份与用户可见事件是两层概念。Raw 新闻和每条来源新闻的股票关联都保留；只在 Biz 查询层合并多来源事件，不能把列表条数减少解释为数据库去重删除，也不能让前端自行归并。

## 2. 当前代码入口

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
| 物化服务 | `src/ops/services/news_stock_linking_service.py` | 已实现 `news_time ASC, row_key_hash ASC` 范围/keyset、批次 delete/upsert、独立提交和实时进度 |
| TaskRun executor | `src/app/runtime/news_stock_linking_task_executor.py`、`src/ops/runtime/maintenance_executor.py`、`src/ops/runtime/task_run_dispatcher.py` | 已实现；单窗口单 unit，批次进度通过 action-specific TaskRun 运行上下文写回，dispatcher 保留终态权威写回 |
| 股票详情新闻 API | `src/biz/queries/wealth/market/news/news_event_deduplicator.py`、`src/biz/queries/wealth/market/stock_detail/news_query.py`、`src/biz/api/wealth/market/stock_detail_news.py` | 已实现 Biz 请求内事件合并、候选 keyset 分批读取和事件级 `limit`；route/schema 不变，完整时间排序契约继续保留 |
| Wealth 新闻 feature | `wealth/src/features/stock-detail/news/**` | 已实现；点击懒加载、AbortController、四态、原样保持 API 顺序 |
| Ops TaskRun 主链 | `src/ops/services/task_run_service.py`、`src/ops/runtime/worker.py`、`src/ops/runtime/task_run_dispatcher.py` | 已存在；支持 dataset、workflow、maintenance 三类任务 |
| 手动任务时间表单 | `src/ops/queries/manual_action_query_service.py`、`src/ops/services/manual_action_service.py` | 新闻动作已声明必填上海自然日范围，复用通用日期格式和顺序校验；不调用交易日历 |
| 自动任务能力 | `src/ops/services/schedule_automation_capability_resolver.py`、`src/ops/services/operations_schedule_service.py`、`frontend/src/pages/ops-v21-task-auto-tab.tsx` | 新闻动作已通过通用 `repeat_policy` 开放 Cron 日内间隔，默认 5 分钟、最小 3 分钟，并实现唯一 Schedule、基线门禁和触发合并 |

市场总览现行为 `/api/v1/wealth/market/news/briefs` 和 `/communications`，与股票详情 `/stock-detail/news` 分开。`/news/stocks` 及“只按公司频道查询”是开发前背景，不是当前可复用接口。



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
8. PostgreSQL 多行 INSERT 的每一行必须使用相同列集合。`NewsStockLinkDAO` 在批量写入前统一补齐 `created_at`：已有关系沿用原值，新关系使用同一个批次 UTC 时间；禁止把“带 `created_at` 的旧关系”和“依赖 server default 的新关系”直接混入同一条 VALUES。

主键左前缀已支持按 news_id 清理，不重复建单列 news_id 索引。news_id 逻辑引用 serving-light view，不能加指向 view 的物理外键；ts_code 也采用逻辑引用/任务词典校验，不因主数据刷新顺序阻塞关联写入。新闻标题、正文、时间和股票名称不复制到关联表。

当前源身份 row_key_hash 由 src/news_time/title/content/channels/score 构成，内容或来源不同通常产生不同新闻身份。派生表不改变该身份，不新增版本合并主键；修改身份需独立方案。新闻 ingestion 与关联任务分离，新闻表不加单值 ts_code。


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

同一规范化词条先添加公司全称，再添加当前简称，最后添加历史简称；内核对同词取第一个有效候选。当前与历史简称同名时当前候选优先，不能在适配层重解释。没有 news_date 时不匹配历史名称。

代码正则提取候选后仍需词典确认：带后缀精确匹配 ts_code，裸六位代码必须唯一映射 symbol，被更长数字包围或词典无法确认的数字不建立关联。当前表达式为：

```regex
(?<![0-9A-Z])(?P<symbol>[0-9]{6})(?:\.(?P<exchange>SH|SZ|BJ))?(?![0-9A-Z])
```

选择 Aho-Corasick 是为了避免对每只股票重复扫描，单篇名称扫描近似 O(文本长度 + 命中量)，不意味着事件两两比较也有同样复杂度。

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
6. 提交关联事务，更新累计 stats，然后调用可选 BatchProgressSink；不是等全部窗口完成才首次回传。业务 commit 失败不发送该批保存成功快照。

每批使用有限内存；batch size 来自 service 显式参数或既有 Settings.sync_batch_size，最小为 1，不出现在用户 API。批次事务只覆盖关联表，新闻 view 不可写，也不与新闻 ingestion 共用事务。

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

1. 先读旧关系及 created_at，再删除该 `news_id` 的旧关系。
2. 再写入本次识别结果。
3. 相同 `(news_id, ts_code)` 不产生重复行，`created_at` 保持不变，规则字段和 `updated_at` 更新。
4. 如果本次识别结果为空，旧关系被删除。

当前批次失败时回滚当前关联事务；之前已提交批次可以保留。TaskRun 进入失败状态，不推进自动 `cursor_end`。重试同一冻结窗口时会
从窗口起点重新读取，已提交批次通过“删除后重建”和主键保持一致。


### 6.4 已提交批次进度与观测快照

服务一次 materialize 只加载一次词典并构建一个 linker，批次业务事务成功后回调：
`BatchProgressSink = Callable[[NewsStockLinkingStats], None]`。sink 接收累计值，不是单批 delta。

| service stats | 含义 |
| --- | --- |
| rows_fetched、matched_news_count、unmatched_news_count | 本次窗口已处理新闻及命中/未命中数 |
| links_inserted、links_updated、links_deleted | 与本批旧关联对比的累计结果；rows_saved 为 inserted + updated |
| rows_deduplicated | 关联结果去重量，不是 Biz 事件合并数 |
| batch_count、last_cursor | 已提交批次数；news_time/row_key_hash 处理位置 |
| invalid_dictionary_rows | 无效词典行计数 |

stats 没有独立 batch_index，也不包含窗口/run_mode 等 payload 字段。

| TaskRun 观测内容 | 补齐者 |
| --- | --- |
| rows/diagnostics | executor reporter 读取累计 stats |
| window_start/end、cursor_end、task_frozen_at、run_mode、window_field=news_time、rule_version、news_scope | reporter 读取本次冻结 payload |
| current_object | reporter 生成名称、窗口和“批次/已处理新闻/已生成关联”说明 |
| task_run_id、既有 run_context | dispatcher 提供 MaintenanceTaskRunContext |

[NewsStockLinkingTaskExecutor](/Users/congming/github/goldenshare/src/app/runtime/news_stock_linking_task_executor.py) 的 reporter 首批立即写，后续按最短 3 秒间隔节流，finally 强制 flush 最新已提交 stats。它不是每批必写，也不是保证运行每 3 秒有业务进展。

沿用 [TaskRun 观测契约](/Users/congming/github/goldenshare/docs/ops/ops-task-run-observability-redesign-plan-v1.md) 的独立 observer session；观测失败只影响可见状态，不回滚业务批次。单个 frozen window 仍是一个 unit，运行中不把批次数伪造为 unit_done；最终计数仍由 dispatcher 收尾。

当前服务没有每批 cancel_checker，取消仍受既有 unit 边界约束；不能把 finally flush 写成“已实现任意批次立即取消”。失败重试按原冻结窗口从头读取，已提交批次幂等重算，last_cursor 不是跨进程的跳过批次授权。

Ops 任务详情页以 `run.action_key=maintenance.materialize_news_stock_links` 识别本动作，在活动状态每 3 秒轮询，显示累计新闻/关联量与不确定进度；不再以 0/1、0% 误导，其他动作仍用既有 unit 进度。



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

已删除 `NEWS_LINK_MODE_PARAM`，为该动作声明以下两项有类型的能力元数据；其他维护动作使用默认值，不改变现有行为：

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

新闻不能使用旧的 `trade_date_range/trading_day_only`；新闻在周末和节假日同样允许被选择。
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

`src/ops/services/news_stock_linking_window_resolver.py`，集中负责手动与自动窗口冻结，避免继续扩张
`TaskRunCommandService._freeze_news_stock_linking_payload()`。freeze_payload 输入为 session、`trigger_source`（`manual/scheduled/retry`）、
`time_input`、`request_payload` 和 `task_frozen_at`，输出 7.1 的完整 payload。`trigger_mode=schedule` 是 Schedule 配置字段，不能与
TaskRun 实际保存的 `trigger_source=scheduled` 混用。

手动路径：

1. 读取自然日期 `start_date/end_date`。
2. 按 6.1 转成上海时区 `[开始日 00:00, 截止日次日 00:00)`，再序列化为 UTC aware datetime。
3. `run_mode=manual_range`，`cursor_end=min(window_end, task_frozen_at)`。
4. 无论范围内是否有新闻都允许创建任务；零新闻任务正常成功并记录 0 行，但不会覆盖已有自动成功游标。

自动路径：

1. 先查询该 action 所有成功任务中最大的 `scheduled_incremental.cursor_end`；一旦存在，只允许它作为 `window_start`。
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

以下旧契约已从当前消费者删除，不保留兼容分支：

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
| `limit` | int | 50 | `<1` 返回 422；`>2000` 截断为 2000；不分页 |
| `debug` | 0/1 | 0 | `1` 时 item 返回 `debugInfo.matchMethod` |

参数类型/格式非法、缺必填参数、limit<1 或 debug 越界，由 [全局校验处理器](/Users/congming/github/goldenshare/src/app/exceptions/web.py) 返回 422 / validation_error。可解析的时间缺时区、startAt 不早于 endAt 返回 400 / 400001；股票不存在或非 EQUITY 返回 404 / 404001。鉴权仍复用 require_quote_access，不改访问边界。

时间窗口为 `[startAt, endAt)`。默认窗口是滚动的最近 2 个自然月，日期不足时按目标月份最后一天进行日历日期截断；不是按月份第一天和最后一天的固定自然月查询。

### 8.3 Query SQL

```sql
SELECT
    n.row_key_hash AS news_id,
    n.news_time AS publish_time,
    n.title,
    n.content,
    n.src,
    l.match_method
FROM core_serving.news_stock_link AS l
JOIN core_serving_light.news AS n
  ON n.row_key_hash = l.news_id
WHERE l.ts_code = :ts_code
  AND n.news_time >= :start_at
  AND n.news_time < :end_at
  AND (
    :cursor_time IS NULL
    OR n.news_time < :cursor_time
    OR (n.news_time = :cursor_time AND n.row_key_hash > :cursor_news_id)
  )
ORDER BY n.news_time DESC, n.row_key_hash ASC
LIMIT :candidate_batch_size;
```

实现要求：

1. `news_time` 直接以带时区完整时间戳排序，精度保留到秒；不得 cast 成 date、截断到日或按展示字符串排序。
2. `row_key_hash ASC` 只在完整 `news_time` 完全相同时作为稳定 tie-breaker。
3. 候选查询按 `news_time + row_key_hash` keyset 分批读取，每批最多 500 条、单次 API 最多扫描 10,000 条；事件合并和代表记录排序完成后才应用 API `limit`。
4. 旧的“两个不同 `news_id` 必须分别返回”要求已被 2026-09-05 的事件合并决策取代；当前实现由 Biz 查询层合并同一事件。
5. 关系表的 `(news_id, ts_code)` 只保证来源新闻关联不重复，不能替代展示事件合并。
6. API 输出的 `publishTime` 保留完整时间和 `Asia/Shanghai` 偏移，例如 `2026-08-22T10:30:05+08:00`。
7. API 只读取 `news_id/news_time/title/content/ts_code/name/match_method` 所需字段；`content` 只用于统一展示标题和事件事实签名，不重新执行股票关联识别。

展示标题由 [build_news_display_title](/Users/congming/github/goldenshare/src/biz/queries/wealth/market/news/news_display_title.py) 统一产生：去空白后优先从非空 title（否则 content）的开头【...】提取标题；未提取到时用 title，再退回正文前 80 字。title/content 都空时结果仍可能为空，不承诺生成虚构标题。

### 8.4 Response schema

当前 schema：

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

### 8.5 事件合并当前编码门禁

当前调用链固定为：

```text
StockDetailNewsQuery 分批读取候选源新闻
  -> Biz 纯事件合并器
  -> 选择每组代表新闻
  -> 按代表新闻时间排序
  -> 按事件应用 limit
  -> 现有 DTO 和 API route
```

代码落点约束：

1. 事件合并器必须位于 `src/biz`，输入普通不可变候选对象，输出事件代表对象；不得依赖 SQLAlchemy session、Ops、前端或数据库写入。
2. 标题提取必须复用 `src/biz/queries/wealth/market/news/news_display_title.py` 的统一函数；若需要调整目录，只能在 Biz 内收敛并完成市场新闻和股票详情两个消费者审计。
3. `StockDetailNewsQuery` 只负责股票校验、时间范围、候选分批读取、调用合并器和 DTO 映射；不得在查询方法中堆叠不可测试的文本相似逻辑。
4. 候选查询必须显式选择 `row_key_hash/news_time/title/content/src/match_method`；不得加载无关列或修改新闻事实。
5. 事件合并只在请求内存中计算，不保存事件指纹，不新增表、DAO、migration、TaskRun 或清洗任务。
6. API schema、路由、前端类型和列表组件原则上不改；`newsId/publishTime/title/debugInfo` 均来自最终代表新闻。
7. `meta.count` 和 `meta.limit` 改为事件数量语义；候选源新闻不得在合并前按事件 `limit` 直接截断。
8. 相近时间窗口、标题/正文判断阈值、截断前缀最小长度、候选批大小和最大扫描量只能使用本节冻结值，不得在调用方另设副本。

前端继续保持第 9 节的纯 DTO 映射。事件合并结果有误时必须修复后端事实规则，禁止在 React 组件中增加 `Set`、标题比较或日期分组补丁。

#### 8.5.1 D0 样本校准结果

2026-09-05 通过生产只读查询复核 `600021.SH`：`2026-08-28` 的 3 条半年报报道发布时间跨度 89 秒，
`2026-08-18` 的 8 条项目投产报道发布时间跨度 139 秒。项目投产样本中，用于连接不同标题版本的三元字符包含率最低值为：

| 比较 | 标题包含率 | 正文包含率 | 结论 |
|---|---:|---:|---|
| “6号机组投产”短标题 vs “6号机组投产，项目全面建成” | `1.000` | `0.833` | 同一事件 |
| “全面建成投产” vs “6号机组投产，项目全面建成” | `0.810` | `0.806` | 同一事件 |

反例使用相同句式但把“6号机组”改为“5号机组”，以及把净利润同比 `47.55%` 改为 `47.54%`；两者文本高度相似，
但数字序列数量相同且值不同，必须判为不同事件。窗口反例使用完全相同标题但发布时间相隔超过 10 分钟，必须保留两条。

#### 8.5.2 唯一常量

| 常量 | 值 | 含义 |
|---|---:|---|
| `NEWS_EVENT_WINDOW` | 10 分钟 | 只比较发布时间差不超过该窗口的同股票新闻 |
| `NEWS_EVENT_NGRAM_SIZE` | 3 | 标题和正文使用三元字符集合比较 |
| `NEWS_EVENT_CONTAINMENT_THRESHOLD` | `0.80` | 标题和正文包含率都达到该值才允许近似合并 |
| `NEWS_EVENT_MIN_EXACT_TITLE_LENGTH` | 12 | 标准标题低于该长度时，标题完全相同也不能单独作为合并证据 |
| `NEWS_EVENT_MIN_EXACT_CONTENT_LENGTH` | 24 | 标准首个事实句低于该长度时，首句完全相同也不能单独作为合并证据 |
| `NEWS_EVENT_MIN_APPROXIMATE_LENGTH` | 16 | 标题或正文过短时禁止进入近似比较 |
| `NEWS_EVENT_TRUNCATED_PREFIX_LENGTH` | 16 | 只有明确带省略号且安全前缀达到该长度，才允许按前缀合并 |
| `NEWS_EVENT_CANDIDATE_BATCH_SIZE` | 500 | 股票详情查询每批读取的候选源新闻数 |
| `NEWS_EVENT_MAX_CANDIDATE_SCAN` | 10000 | 单次 API 请求最多读取的候选源新闻数 |

包含率定义为两个三元字符集合交集数量除以较小集合的数量，适合识别“完整报道与摘要/截断报道”的包含关系；不用 Jaccard，
避免较长正文因为补充细节而把同一事件的相似度稀释。文本先执行 Unicode NFKC、大小写归一并移除空白和标点，数字序列必须在移除标点前提取。

#### 8.5.3 确定性分组与代表记录

1. 候选先按 `news_time DESC, news_id ASC` 排序，再在 10 分钟窗口内两两比较并构建并查集；合并两个组前必须保证合并后整组最早与最晚发布时间仍不超过 10 分钟，禁止通过中间记录链式跨越窗口。同一输入集合不因数据库返回顺序变化而改变分组。
2. 合并证据按顺序为：足够长的标准标题完全相同、正文首个事实句完全相同、明确截断前缀、标题包含率与正文首句/全文包含率达标。不是任意短标题相同就合并。
3. 若两个标准标题或完整正文首个事实句提取出的数字序列数量相同但值不同，先判为数字冲突，后续任何文本相似证据都不能覆盖该结论；正文明确以省略号截断时不使用残缺正文数字判冲突。
4. 每组代表记录依次优先：非空且未截断的源标题、正文更完整、标准标题更完整、发布时间更新、`news_id ASC`。
5. 事件列表按代表记录 `news_time DESC, news_id ASC` 排序。

#### 8.5.4 候选读取停止条件

1. 查询固定使用 `news_time DESC, row_key_hash ASC` keyset，每批最多 500 条。
2. 未取得 `limit` 个事件时继续读取，直到时间范围耗尽或达到 10000 条硬上限。
3. 已取得 `limit` 个事件后，继续读取到当前最旧候选早于第 `limit` 个事件代表时间减 10 分钟，确保可能归入末位事件的较旧转载也参与代表记录选择。
4. 达到 10000 条后停止，不允许无界加载；返回已合并排序的前 limit 个事件。没有额外分页、超限错误或截断标记；不保证凑满 limit，也不保证历史范围已扫描穷尽。


## 9. Wealth 新闻 Tab 消费边界

[StockDetailNewsPanel](/Users/congming/github/goldenshare/wealth/src/features/stock-detail/news/StockDetailNewsPanel.tsx) 位于股票详情右侧 Tabs，Tab 条 36px；只有 active 时请求本股票新闻，不进入 page-init、K 线和盘口主链。切换股票重置状态，过期请求用 AbortController 取消；成功后同股票重复切 Tab 不重复抓取。

页面保留 idle/loading/ready-empty/ready-items/error 五态，不在前端筛选、重排、分组或去重。API client 只透传 tsCode、可选时间/limit/debug 与 signal；默认页面请求 limit=50，后端是唯一事件展示事实源。

[适配器](/Users/congming/github/goldenshare/wealth/src/features/stock-detail/news/api/stockDetailNewsViewModelAdapter.ts) 只原样映射 newsId/title/publishTime，并按 Asia/Shanghai 格式化日期：当前年份 MM-DD，否则 YYYY-MM-DD，不展示时分秒。列表不展示来源、不提供点击外链、不新增 clickable；布局与截断样式复用 [现有 CSS](/Users/congming/github/goldenshare/wealth/src/features/stock-detail/news/stock-detail-news.css)。



## 10. 测试和验收矩阵

### 10.1 算法内核（已有）

继续保留 `tests/test_stock_news_linker.py` 的现有覆盖：代码/全称/简称独立命中、并集去重、匹配优先级、source field、代码边界、简称第一条、历史名称区间、非股票过滤、文本标准化、输入错误。

### 10.2 物化服务与范围任务（当前实现）

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
5. `limit` 默认 50，超过 2000 截断到 2000，不生成分页游标；用户 limit 只在事件排序后应用，候选另受每批 500、最多 10000 条扫描上限约束。
6. 不按 `channels` 二次过滤；事件合并后，同一事件的多来源转载只返回一条代表新闻。
7. 普通响应不含 debug 字段，`debug=1` 只含 `matchMethod`。
8. 空结果、股票不存在、参数错误和查询异常符合约定 HTTP 语义。
9. 无标题正文、书名括号标题、完整标题、截断标题和小幅改写的同事件正例可以合并；关键数字冲突、跨时间窗口和独立进展反例不得合并。
10. `limit` 在事件合并后执行；源新闻重复占满首批候选时仍能继续读取后续事件。
11. 事件分组和代表新闻选择不受候选输入顺序影响；默认 50 与最大 2000 事件场景有明确候选扫描边界和性能验证。

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

### 10.6 手动入口、自动能力与调度（当前实现）

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

1. `frontend/src/pages/ops-v21-task-manual-tab.test.tsx` 验证新闻动作只显示自然日开始/截止日期、不请求交易日历，并原样提交起止自然日；`tests/web/test_ops_manual_actions_api.py` 验证 capability 描述明确“截止日期包含整天”。
2. `frontend/src/pages/ops-v21-task-auto-tab.test.tsx` 验证页面由 `repeat_policy` 展示可配置日内间隔，默认 5、最小 3；不按 action key 特判。
3. 自动任务详情能显示当前 cron、开关状态和时区；不出现手动日期输入、新闻窗口或 overlap 参数。


## 11. 历史实施与验收证据

原实施先完成关联模型/内核/批次事务，再补运行上下文、sink、独立观测、节流及 Ops 详情展示；之后完成自然日手动输入、窗口解析、news_time 轴、Schedule 能力、唯一性与空窗口合并。原技术方案 M0–M6、进度 P0–P5、时间契约 R0–R6 均是已完成阶段，不再作为待办重复维护。

### 11.1 2026-08-23 关联与时间契约

本轮最终本地验证结果（2026-08-23）：

1. 新闻关联、TaskRun、Schedule、catalog、manual API、依赖矩阵和 Heat 守卫定向套件 `269 passed`。
2. 前端 `typecheck`、`check:rules`、`149` 条单元测试、生产构建和 `13` 条 smoke 全部通过；构建仅保留既有大 chunk 警告。
3. 默认 `pytest -q` 在收集阶段被一个已不存在的 Lake Console 模块和两个同名测试模块阻塞；用 importlib 隔离并排除该缺失模块后，仓库其余测试为 `1984 passed, 10 failed, 10 skipped`。失败项位于既有架构守卫、Lake Console、CLI、ETF 报告和板块总览范围，不在本需求改动白名单内，本轮没有越界修复。
4. 生产只读 `EXPLAIN` 命中 `idx_raw_tushare_news_time`，并使用 Incremental Sort 完成 `row_key_hash` tie-breaker；未执行 `ANALYZE`、数据写入或 migration。

初版关联表 migration 是 20260823_000145_add_news_stock_link.py；上述时间契约/进度改造没有新增 migration，不能把“本轮没有迁移”扩写成整个功能从未建表。

[原 Raw 建表迁移](/Users/congming/github/goldenshare/alembic/versions/20260503_000091_add_news_dataset.py) 把 news_time 和 src/news_time 索引建在 raw_tushare.news，serving-light.news 是其 view。上述 EXPLAIN 是透过 view 使用 Raw 索引，不是 view 自带物理索引，也不是今天已验证的查询计划。

2026-09-01 用户确认关联物化主链结案。部署、生产 Schedule 与回填不因本文而自动执行；运行中任务不热加载新代码。旧 Full 虽成功也无新契约游标，当时采用覆盖“旧 Full 冻结时间至切换时刻”所在自然日期的桥接范围，成功后再开自动增量，不需重跑全历史。

### 11.2 2026-09-05 至 09-09 事件展示

9 月 5 日生产只读样本确认：上海电力 600021.SH 的 8/28 半年报 3 条和 8/18 项目投产 8 条，共 11 个不同源身份，用户需要看到的是 2 个事件。这不是数据库重复写入或前端重复渲染；改造将源记录身份与事件身份分离，具体样本与阈值保留在 §8.5.1。

当天完成纯 Biz 合并器、keyset 分批候选和事件后 limit；脱敏样本稳定 11→2，数字冲突、跨窗口、短通用文本反例保留。原记录称后端事件/API、市场新闻、依赖边界和 Wealth 消费者回归通过，没有数据库结构或生产写入变更。

10,000 条独立候选的本地纯合并样本约 0.09 秒，**不含数据库往返，不是密集相似候选的最坏耗时或 API SLA**。500/10000 是扫描边界，不代表任意输入的性能保证；本次不新增门禁或补跑生产。

2026-09-09 用户确认部署后的事件合并效果正确，正式结案。两份旧文档的验证数字只对应各自日期，不与本次文档检查混计。

## 12. 已接受限制与维护要求

- 识别是确定性子串召回，不判断语义角色；短简称可能误召回。历史名按已加载区间与稳定输入顺序解释，不推断缺失或错误的更名日期。
- 重算必须删除该批新闻旧关系后重建，仅 upsert 新命中会残留旧关系；created_at 需要先读回并保留。关联批次与新闻 ingestion、TaskRun 观测事务分离。
- 进度是本任务已提交批次累计值，不是关系表总行数。observer 失败可能停在旧快照，但不牺牲业务数据；当前没有每批取消保证。
- 自动增量只按 news_time 向前：迟到写入而 news_time 早于游标的新闻不会自动回看，需运营按自然日手动补跑。无 overlap 或首次静默 Full。
- 手动结束日包含整天，window_end 可晚于冻结时刻；cursor_end=min(window_end,task_frozen_at) 防止把尚未发生时段记作已覆盖。自动已成功后，人工补跑不能推进或回退其游标。
- 无新闻/活跃任务重叠的自动触发只推进 next_run_at，不制造空/失败 TaskRun；触发次数不等于任务数。
- 事件规则只在 Biz 内请求期间运行，不持久化事件指纹、不删 Raw/关系记录、不使用模型或外部语义服务；无法建立规则证据时保留独立记录。
- 本文没有新的待开发业务选项。未来改规则、配置、输入/输出合同或身份先做实现与消费者审计；本次仅文档合并，API/CLI、业务数据、依赖矩阵均不变。

合并对账见 [治理账本](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md#architecture-three-batches-20260910)。纯文档运行完整性、链接和 diff 检查；代码回归按 §10 选取，不自动安装套件、启动生产或重新打开结案。
