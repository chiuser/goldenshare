# Ops 实时流配置中心 M1 消费者审计清单 v1

状态：M1 已审计 / M2 建表与初始化已落地 / M3 配置读取层已切换 / M4 旧 env 字段已退场 / M5 Biz SnapshotReader 已下沉 / 待 M6-M8 收尾
依据：[Ops 实时流配置中心技术方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-realtime-config-center-technical-plan-v1.html)、根 `AGENTS.md`、`src/AGENTS.md`、依赖矩阵  
审计时间：2026-06-02  

## 1. 目标

本清单记录 M1 现状消费者审计结果，并补充 M2 建表与初始化落地状态，用于后续 M3-M8 执行对账。

M2 已新增运行时配置表和受控初始化入口。M3 已将运行时读取从旧 `feed_config.py + Settings/env` 切到 `runtime_config.py + foundation.realtime_runtime_config + config_catalog.py`。M4 已删除 `Settings` 中旧实时 env 字段，seed 初始化改为代码内受控默认模板。M5 已将 Biz realtime 快照读取下沉到 `RealtimeSnapshotReader`。前端配置中心 API 和远程 env 清理仍未完成。

## 2. M0 冻结口径

1. 当前配置事实表固定为 `foundation.realtime_runtime_config`。
2. `ops.config_revision` 只记录发布前后差异和操作人，不参与运行时读取。
3. 旧 `REALTIME_STOCK_RT_*` env 已不再作为初始化输入；只允许在历史/退场文档中出现，主链不得 fallback、不得双读双写。
4. `REDIS_URL` 保留在部署级 env，不进入配置中心。
5. Biz realtime API 目标态不得直接读取 runtime config，不得拼 `feed_key`、`stale`、`collection_sessions`，必须通过 `RealtimeSnapshotReader`。
6. Ops health 允许读取 runtime config，因为它展示“应然配置 + 实然运行状态”。
7. V1 发布配置后提示需要重启 collector，不做热加载。

## 3. 运行时代码消费者

| 消费者 | 当前代码位置 | 当前行为 | 后续目标处理 |
| --- | --- | --- | --- |
| Settings/env 定义 | `src/foundation/config/settings.py` | 旧 `REALTIME_STOCK_RT_*` 字段已删除，仅保留 `REDIS_URL` 等部署级字段。 | M4 已完成。 |
| 配置构建 | `src/foundation/realtime/runtime_config.py` | 从 `foundation.realtime_runtime_config` 读取可编辑项，结合 `config_catalog.py` 锁定事实和 `REDIS_URL` 生成 `RealtimeRuntimeConfig`。 | M3 已完成；M4 已删除 Settings 旧字段。 |
| 锁定事实目录 | `src/foundation/realtime/config_catalog.py` | 锁定 display name、source api、feed key/pattern、`ts_code_pattern`、`collection_sessions`、`exchange=SSE`。 | M3 已完成；这些字段不从 DB JSON 或旧 env 读取。 |
| package export | `src/foundation/realtime/__init__.py` | 对外导出 runtime config API、dataclass、cache clear、DB loader。 | M3 已完成；旧命名保留为 API 名，但语义已切到数据库配置，不再是 env。 |
| CLI collector | `src/cli_parts/realtime_handlers.py` | 启动时显式用 `session` 调用 `get_realtime_runtime_config(session)`，用 `redis_url` 构建 store，并把 config 传给 collector。 | M3 已完成；部署前必须先 seed 配置行。 |
| 统一 collector | `src/foundation/realtime/collector_service.py` | 初始化时消费 `RealtimeRuntimeConfig`；按日线和分钟配置调度。 | M3 已完成；默认无 config 时走 runtime resolver 的短 session。 |
| 股票实时日线 provider/collector | `src/foundation/realtime/stock_rt_daily.py` | 默认调用新 resolver；使用 DB 可编辑项 + catalog 锁定项。 | M3 已完成。 |
| 股票实时分钟 provider/publisher/collector | `src/foundation/realtime/stock_rt_min.py` | 默认调用新 resolver；频率等可编辑项来自 DB，通配符和采集时段来自 catalog。 | M3 已完成。 |
| Tushare 限速 | `src/foundation/clients/tushare_client.py` | `_get_rate_limiter()` 通过新 runtime resolver 获取实时接口限速。 | M3 已完成；无配置行时 fail fast。 |
| Redis store dependency | `src/app/dependencies/realtime.py` | 调用 `get_realtime_runtime_config().redis_url` 构建 store。 | `REDIS_URL` 仍为部署级 env；读取通过 runtime resolver 暴露的部署级字段。 |
| Biz 日线查询 | `src/biz/queries/realtime_stock_rt_daily_query_service.py` | 只做参数校验和 schema 映射，调用 `RealtimeSnapshotReader` 读取快照事实。 | M5 已完成；Biz 不再读 runtime config、拼 feed key 或算 stale。 |
| Biz 分钟查询 | `src/biz/queries/realtime_stock_rt_min_query_service.py` | 只做参数校验和 schema 映射，调用 `RealtimeSnapshotReader` 读取快照事实。 | M5 已完成；Biz 不再读 runtime config、拼 feed key 或算 stale。 |
| Ops health | `src/ops/queries/realtime_feed_health_query_service.py` | 显式传 `session` 读取配置和 Redis health/meta，构造运行状态。 | M3 已完成；Ops health 继续展示“应然配置 + 实然状态”。 |

## 4. 旧配置项退场映射

| 配置项 | 当前留存来源 | M3 前主要消费者 | 目标归属 | 后续动作 |
| --- | --- | --- | --- | --- |
| `REDIS_URL` | `Settings/env` | `app/dependencies/realtime.py`、`cli_parts/realtime_handlers.py` | 部署级 env | 保留，不进入配置中心。 |
| `REALTIME_STOCK_RT_DAILY_ENABLED` | 已无代码来源 | `feed_config.py`、collector、Ops health、测试 | `stock_rt_daily.runtime_config_json.enabled` | M4 已退场。 |
| `REALTIME_STOCK_RT_DAILY_POLL_INTERVAL_SECONDS` | 已无代码来源 | `feed_config.py`、collector scheduler、测试 | `stock_rt_daily.runtime_config_json.poll_interval_seconds` | M4 已退场。 |
| `REALTIME_STOCK_RT_DAILY_MAX_CALLS_PER_MINUTE` | 已无代码来源 | `feed_config.py`、Tushare 限速、测试 | `stock_rt_daily.runtime_config_json.max_calls_per_minute` | M4 已退场。 |
| `REALTIME_STOCK_RT_DAILY_LEASE_TTL_SECONDS` | 已无代码来源 | `feed_config.py`、日线 collector、测试 | `stock_rt_daily.runtime_config_json.lease_ttl_seconds` | M4 已退场。 |
| `REALTIME_STOCK_RT_DAILY_STALE_AFTER_SECONDS` | 已无代码来源 | `feed_config.py`、Biz 查询、Ops health | `stock_rt_daily.runtime_config_json.stale_after_seconds` | M4 已退场；M5 由 snapshot reader 封装给 Biz。 |
| `REALTIME_STOCK_RT_DAILY_SNAPSHOT_TTL_SECONDS` | 已无代码来源 | `feed_config.py`、Redis publish | `stock_rt_daily.runtime_config_json.snapshot_ttl_seconds` | M4 已退场。 |
| `REALTIME_STOCK_RT_DAILY_KEEP_RECENT_BATCHES` | 已无代码来源 | `feed_config.py`、Redis publish | `stock_rt_daily.runtime_config_json.keep_recent_batches` | M4 已退场。 |
| `REALTIME_STOCK_RT_DAILY_BATCH_STREAM_MAXLEN` | 已无代码来源 | `feed_config.py`、Redis publish | `stock_rt_daily.runtime_config_json.batch_stream_maxlen` | M4 已退场。 |
| `REALTIME_STOCK_RT_DAILY_DELTA_STREAM_MAXLEN` | 已无代码来源 | `feed_config.py`、Redis publish | `stock_rt_daily.runtime_config_json.delta_stream_maxlen` | M4 已退场。 |
| `REALTIME_STOCK_RT_DAILY_COLLECTION_SESSIONS` | 已无代码来源 | `feed_config.py`、collector、Biz 查询、Ops health | `config_catalog.py` 锁定事实 | M4 已退场，不开放编辑。 |
| `REALTIME_STOCK_RT_DAILY_TS_CODE_PATTERN` | 已无代码来源 | `feed_config.py`、日线 provider | `config_catalog.py` 锁定事实 | M4 已退场，不开放编辑。 |
| `REALTIME_STOCK_RT_MIN_ENABLED` | 已无代码来源 | `feed_config.py`、collector、Ops health、测试 | `stock_rt_min.runtime_config_json.enabled` | M4 已退场。 |
| `REALTIME_STOCK_RT_MIN_ENABLED_FREQS` | 已无代码来源 | `feed_config.py`、collector、Ops health、测试 | `stock_rt_min.runtime_config_json.enabled_freqs` | M4 已退场；前端 M7 用多选框。 |
| `REALTIME_STOCK_RT_MIN_POLL_INTERVAL_SECONDS` | 已无代码来源 | `feed_config.py`、collector scheduler、测试 | `stock_rt_min.runtime_config_json.poll_interval_seconds` | M4 已退场。 |
| `REALTIME_STOCK_RT_MIN_MAX_CALLS_PER_MINUTE` | 已无代码来源 | `feed_config.py`、Tushare 限速、测试 | `stock_rt_min.runtime_config_json.max_calls_per_minute` | M4 已退场。 |
| `REALTIME_STOCK_RT_MIN_LEASE_TTL_SECONDS` | 已无代码来源 | `feed_config.py`、分钟 collector、测试 | `stock_rt_min.runtime_config_json.lease_ttl_seconds` | M4 已退场。 |
| `REALTIME_STOCK_RT_MIN_STALE_AFTER_SECONDS` | 已无代码来源 | `feed_config.py`、Biz 查询、Ops health | `stock_rt_min.runtime_config_json.stale_after_seconds` | M4 已退场；M5 由 snapshot reader 封装给 Biz。 |
| `REALTIME_STOCK_RT_MIN_SNAPSHOT_TTL_SECONDS` | 已无代码来源 | `feed_config.py`、Redis publish | `stock_rt_min.runtime_config_json.snapshot_ttl_seconds` | M4 已退场。 |
| `REALTIME_STOCK_RT_MIN_KEEP_RECENT_BATCHES` | 已无代码来源 | `feed_config.py`、Redis publish、测试 | `stock_rt_min.runtime_config_json.keep_recent_batches` | M4 已退场。 |
| `REALTIME_STOCK_RT_MIN_BATCH_STREAM_MAXLEN` | 已无代码来源 | `feed_config.py`、Redis publish | `stock_rt_min.runtime_config_json.batch_stream_maxlen` | M4 已退场。 |
| `REALTIME_STOCK_RT_MIN_DELTA_STREAM_MAXLEN` | 已无代码来源 | `feed_config.py`、Redis publish | `stock_rt_min.runtime_config_json.delta_stream_maxlen` | M4 已退场。 |
| `REALTIME_STOCK_RT_MIN_SOURCE_TIMEOUT_SECONDS` | 已无代码来源 | `feed_config.py`、分钟 provider | `stock_rt_min.runtime_config_json.source_timeout_seconds` | M4 已退场。 |
| `REALTIME_STOCK_RT_MIN_COLLECTION_SESSIONS` | 已无代码来源 | `feed_config.py`、collector、Biz 查询、Ops health | `config_catalog.py` 锁定事实 | M4 已退场，不开放编辑。 |
| `REALTIME_STOCK_RT_MIN_TS_CODE_PATTERN` | 已无代码来源 | `feed_config.py`、分钟 provider、测试 | `config_catalog.py` 锁定事实 | M4 已退场，不开放编辑。 |

## 5. 测试消费者

| 测试文件 | 当前入口 | 后续处理 |
| --- | --- | --- |
| `tests/test_realtime_runtime_config.py` | 测试数据库配置、缺行 fail fast、非法频率、空频率、请求量不足、stale 小于 poll、锁定字段不被 DB/env 覆盖。 | M3 已完成。 |
| `tests/test_realtime_collector_service.py` | 通过显式 `RealtimeRuntimeConfig` 对象控制分钟启停和频率。 | M3 已完成。 |
| `tests/test_realtime_stock_rt_min.py` | 通过显式配置对象测试 provider/publisher，通配符走 catalog 锁定事实。 | M3 已完成。 |
| `tests/test_tushare_client.py` | 通过测试配置表记录驱动实时接口限速。 | M3 已完成。 |
| `tests/web/test_realtime_collector.py` | 通过 SQLite 配置表记录控制日线启用和 lease TTL。 | M3 已完成。 |
| `tests/web/test_realtime_stock_rt_min_collector.py` | 通过 SQLite 配置表记录控制分钟启用和 lease TTL。 | M3 已完成。 |
| `tests/web/test_realtime_api.py` | 通过 SQLite 配置表记录控制日线/分钟启用和频率。 | M3 已完成；M5 后 Biz API 测试应通过 snapshot reader。 |

## 6. 文档消费者

| 文档 | 当前口径 | 后续处理 |
| --- | --- | --- |
| `docs/architecture/realtime-market-data-stream-technical-plan-v1.md` | 当前仍描述 `Settings/env -> feed_config.py` 为配置来源，并列出日线 env 示例。 | M8 更新为历史口径/已退场；当前口径指向配置中心和 `foundation.realtime_runtime_config`。 |
| `docs/architecture/realtime-stock-minute-stream-architecture-v1.html` | 当前仍列出分钟 env 配置项，并记录生产 `REALTIME_STOCK_RT_MIN_ENABLED=true`。 | M8 更新为历史口径；生产启用状态迁入 runtime config。 |
| `docs/ops/ops-realtime-config-center-showcase-v1.html` | showcase 仍展示 `REALTIME_STOCK_RT_*` 字段名。 | M7/M8 改为展示配置中心字段名或 API 返回字段，不再指导运营手填 env。 |
| `docs/architecture/realtime-stock-intraday-minutes-on-demand-plan-v1.md` | 单股当日分时序列计划另有 `REALTIME_STOCK_RT_MIN_DAILY_*` env 设计。 | 不属于本轮 collector feed 配置退场；后续进入 rt_min_daily 需求时按配置中心总原则重新评审。 |

## 7. M1 验证命令

运行时代码审计：

```bash
rg -n "get_realtime_runtime_config|get_realtime_stock_rt_daily_config|get_realtime_stock_rt_min_config|get_realtime_tushare_max_calls_per_minute|settings\\.realtime_stock_rt|REALTIME_STOCK_RT" src/foundation src/biz src/ops src/app src/cli_parts
```

测试入口审计：

```bash
rg -n "monkeypatch\\.setenv\\(\\\"REALTIME_STOCK_RT|get_realtime_stock_rt_daily_config|get_realtime_stock_rt_min_config|get_realtime_runtime_config|feed_config" tests
```

架构护栏：

```bash
uv run pytest -q tests/architecture/test_subsystem_dependency_matrix.py tests/architecture/test_platform_legacy_guardrails.py tests/architecture/test_operations_legacy_guardrails.py
```

当前结果：`14 passed in 5.83s`。

## 8. 后续门禁

1. M4 已完成：`settings.realtime_stock_rt_*` 和 `monkeypatch.setenv("REALTIME_STOCK_RT_*")` 已从 `src/`、`tests/` 退场。
2. 旧 `REALTIME_STOCK_RT_*` env 只能作为历史说明或远程 env 清理对象存在，不再作为 seed 输入。
3. M5 已完成：Biz 直读配置和拼 Redis/feed key 的行为已退场，快照事实由 foundation `RealtimeSnapshotReader` 封装。
4. M8 完成前，文档和 showcase 中旧 env 口径必须全部改成历史/已退场说明。

## 9. M2 建表与初始化落地状态

M2 已完成以下内容：

1. 新增 `foundation.realtime_runtime_config` ORM：`src/foundation/models/meta/realtime_runtime_config.py`。
2. 新增 Alembic 迁移：`alembic/versions/20260602_000116_add_realtime_runtime_config.py`，`down_revision=20260531_000115`。
3. 新增受控初始化入口：`goldenshare ops-seed-realtime-runtime-config`，默认 dry-run，`--apply` 才写库。
4. 初始化只创建缺失的 `stock_rt_daily`、`stock_rt_min` 两行；已有行跳过，不覆盖。
5. 初始化只写可编辑字段到 `runtime_config_json`；`collection_sessions`、`ts_code_pattern`、`source_api_name`、`feed_key/feed_key_pattern` 等锁定事实不入库。

以下是 M2 完成当时明确未完成、不得误判为完成的内容；其中运行时读取切换已在 M3 收口：

1. 未切换 `src/foundation/realtime/feed_config.py` 的运行时读取来源。
2. 未删除 `Settings` 中的 `REALTIME_STOCK_RT_*` 字段。
3. 未改 collector、Biz realtime API、Ops health、前端页面。
4. 未写 `ops.config_revision`；初始化不是发布动作，正式 publish 审计留到配置中心 API 阶段。

## 10. M3 配置读取层落地状态

M3 已完成以下内容：

1. 删除 `src/foundation/realtime/feed_config.py`。
2. 新增 `src/foundation/realtime/config_catalog.py`，锁定 source api、display name、feed key/pattern、`ts_code_pattern`、`collection_sessions=09:30-11:30,13:00-15:00`、`exchange=SSE`。
3. 新增 `src/foundation/realtime/runtime_config.py`，从 `foundation.realtime_runtime_config` 读取 `stock_rt_daily`、`stock_rt_min` 两行；缺行、非法配置、请求量不足、stale 小于 poll interval 都 fail fast，不 fallback env。
4. `REDIS_URL` 继续来自部署级 env，但通过 runtime resolver 暴露给 app/CLI 构建 Redis store。
5. CLI、collector、provider、Ops health、Biz realtime query、Tushare 实时限速均切到 runtime resolver。
6. 测试入口已改为配置表记录或显式 `RealtimeRuntimeConfig` 对象；旧 env 构造在 M4 已从 seed 初始化测试中删除。

M3 完成当时明确未完成、不得误判为完成的内容；其中 Settings 旧字段已在 M4 收口：

1. 已删除 `src/foundation/config/settings.py` 中 `REALTIME_STOCK_RT_*` 字段。
2. 已下沉 Biz `RealtimeSnapshotReader`；Biz 不再读取配置并拼 feed key/stale。
3. 未实现配置中心 API、发布审计和前端页面；这是后续配置中心阶段。
4. 未清理本地/远程 env；这是 M8。

## 11. M4 旧 env 字段退场状态

M4 已完成以下内容：

1. 删除 `src/foundation/config/settings.py` 中旧 `REALTIME_STOCK_RT_*` 字段，仅保留 `REDIS_URL` 作为部署级 env。
2. `runtime_config_seed_service` 默认初始化改为代码内受控默认模板，不再读取旧实时 env。
3. seed 测试删除旧 env 构造，改为验证默认模板和非法显式 runtime config 拒绝。
4. `src/` 与 `tests/` 中旧 env 运行时/测试入口引用清零。

M4 明确未完成、不得误判为完成的内容：

1. 未清理本地 `.env.web.local` 或远程 `/etc/goldenshare/web.env` 中可能残留的旧 env；这是 M8 部署退场动作。
2. 已下沉 Biz `RealtimeSnapshotReader`。
3. 未实现配置中心 API、发布审计和前端页面。

## 12. M5 Biz SnapshotReader 下沉状态

M5 已完成以下内容：

1. 新增 foundation `RealtimeSnapshotReader`，统一封装 runtime config、feed key、Redis current batch、交易时段和 stale 判断。
2. Biz 日线/分钟查询服务只保留参数校验、数量限制和 response schema 映射。
3. 外部 realtime API 路径、response schema 与错误码保持不变。
4. Ops health 仍直接读取 runtime config，用于展示“应然配置 + 实然状态”，不属于 M5。

M5 明确未完成、不得误判为完成的内容：

1. 未实现配置中心 API、发布审计和前端页面。
2. 未清理本地或远程 env；这是 M8。
3. 未改变 Redis key 模型或 WebSocket 设计。
