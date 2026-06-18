# Ops 实时流配置中心 M1 消费者审计清单 v1

状态：M1 已审计 / M2 建表与初始化已落地 / M3 配置读取层已切换 / M4 旧 env 字段已退场 / M5 Biz SnapshotReader 已下沉 / M6 Ops 配置 API 已上线 / M7 前端配置页已接入 / M7.1 发布生效闭环已落地 / M8 env 与文档收口已完成
依据：[Ops 实时流配置中心技术方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-realtime-config-center-technical-plan-v1.html)、根 `AGENTS.md`、`src/AGENTS.md`、依赖矩阵  
审计时间：2026-06-02  

## 1. 目标

本清单记录 M1 现状消费者审计结果，并补充 M2 建表与初始化落地状态，用于后续 M3-M8 执行对账。

M2 已新增运行时配置表和受控初始化入口。M3 已将运行时读取从旧 `feed_config.py + Settings/env` 切到 `runtime_config.py + foundation.realtime_runtime_config + config_catalog.py`。M4 已删除 `Settings` 中旧实时 env 字段，seed 初始化改为代码内受控默认模板。M5 已将 Biz realtime 快照读取下沉到 `RealtimeSnapshotReader`。M6 已实现 Ops 配置 API、发布写 revision 和版本冲突保护。M7 已实现前端配置中心页面。M7.1 已补齐发布后 collector 已应用版本闭环，页面不再把静态重启策略误显示成当前待重启状态。M8 已完成本地/远程旧 env 清零和相关文档口径收口。

## 2. M0 冻结口径

1. 当前配置事实表固定为 `foundation.realtime_runtime_config`。
2. `ops.config_revision` 只记录发布前后差异和操作人，不参与运行时读取。
3. 旧 `REALTIME_STOCK_RT_*` env 已不再作为初始化输入；只允许在历史/退场文档中出现，主链不得 fallback、不得双读双写。
4. `REDIS_URL` 保留在部署级 env，不进入配置中心。
5. Biz realtime API 目标态不得直接读取 runtime config，不得拼 `feed_key`、`stale`、`collection_sessions`，必须通过 `RealtimeSnapshotReader`。
6. Ops health 允许读取 runtime config，因为它展示“应然配置 + 实然运行状态”。
7. V1 发布配置后提示需要重启 collector，不做热加载；但“是否仍待重启”不得由 `requires_collector_restart` 静态字段决定，必须由配置发布版本和 collector 已应用版本推导。

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
| Ops 配置中心 API | `src/ops/api/realtime.py`、`src/ops/services/realtime_config_service.py` | 管理员查看、校验、发布 runtime config，发布时写 `ops.config_revision`。 | M6 已完成；不请求 Tushare、不读写 Redis。 |
| 发布生效状态 | `src/ops/services/realtime_config_service.py`、`frontend/src/pages/ops-realtime-config-center-page.tsx`、collector health | collector 写入 `realtime_config_apply_state`；Ops API 派生 `apply_state`；前端按 `applied/pending_restart/unknown` 展示，并提供受控重启按钮。 | M7.1 已完成；`requires_collector_restart` 只保留为发布影响策略。 |

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
| `tests/web/test_ops_realtime_config_api.py` | 覆盖配置中心 list/detail/validate/publish/revisions、权限、锁定字段、版本冲突。 | M6 已完成。 |

## 6. 文档消费者

| 文档 | 当前口径 | 后续处理 |
| --- | --- | --- |
| `docs/architecture/realtime-market-data-stream-technical-plan-v1.md` | 已更新为当前配置中心口径：`foundation.realtime_runtime_config + runtime_config.py + config_catalog.py`；旧 env 仅作为退场说明。 | M8 已完成。 |
| `docs/architecture/realtime-stock-minute-stream-architecture-v1.html` | 已更新为 runtime config 字段和锁定事实口径；不再指导通过 env 开启分钟 feed。 | M8 已完成。 |
| `docs/ops/ops-realtime-config-center-showcase-v1.html` | 已改为展示配置中心字段名或 API 返回字段，不再展示 `REALTIME_STOCK_RT_*` 字段名。 | M8 已完成。 |
| `docs/architecture/realtime-stock-intraday-minutes-on-demand-plan-v1.md` | 已把单股当日分时序列配置改为候选字段和待配置中心方案确认；不得提前落 env。 | M8 已完成。 |

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
4. M6 已完成：配置中心 API、发布 revision、版本冲突保护已上线。
5. M7.1 已完成发布生效闭环：页面不得继续把 `requires_collector_restart` 当作“当前待重启”状态；必须按配置版本和 collector 已应用版本派生。
6. M8 已完成：文档和 showcase 中旧 env 当前口径已收口为历史/已退场说明，当前运行配置指向配置中心和 runtime config 表。

## 9. M2 建表与初始化落地状态

M2 已完成以下内容：

1. 新增 `foundation.realtime_runtime_config` ORM：`src/foundation/models/meta/realtime_runtime_config.py`。
2. 新增 Alembic 迁移：`alembic/versions/20260602_000116_add_realtime_runtime_config.py`，`down_revision=20260531_000115`。
3. 新增受控初始化入口：`goldenshare ops-seed-realtime-runtime-config`，默认 dry-run，`--apply` 才写库。
4. 初始化当前创建缺失的 `stock_rt_daily`、`stock_rt_min`、`etf_rt_daily` 三行；已有行跳过，不覆盖。
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
3. 新增 `src/foundation/realtime/runtime_config.py`，从 `foundation.realtime_runtime_config` 读取已注册实时对象配置；当前必须存在 `stock_rt_daily`、`stock_rt_min`、`etf_rt_daily` 三行。缺行、非法配置、请求量不足、stale 小于 poll interval 都 fail fast，不 fallback env。
4. `REDIS_URL` 继续来自部署级 env，但通过 runtime resolver 暴露给 app/CLI 构建 Redis store。
5. CLI、collector、provider、Ops health、Biz realtime query、Tushare 实时限速均切到 runtime resolver。
6. 测试入口已改为配置表记录或显式 `RealtimeRuntimeConfig` 对象；旧 env 构造在 M4 已从 seed 初始化测试中删除。

M3 完成当时明确未完成、不得误判为完成的内容；其中 Settings 旧字段已在 M4 收口：

1. 已删除 `src/foundation/config/settings.py` 中 `REALTIME_STOCK_RT_*` 字段。
2. 已下沉 Biz `RealtimeSnapshotReader`；Biz 不再读取配置并拼 feed key/stale。
3. 已实现配置中心 API 和发布审计；前端页面仍是后续配置中心阶段。
4. 本地/远程旧 env 已在 M8 清零。

## 11. M4 旧 env 字段退场状态

M4 已完成以下内容：

1. 删除 `src/foundation/config/settings.py` 中旧 `REALTIME_STOCK_RT_*` 字段，仅保留 `REDIS_URL` 作为部署级 env。
2. `runtime_config_seed_service` 默认初始化改为代码内受控默认模板，不再读取旧实时 env。
3. seed 测试删除旧 env 构造，改为验证默认模板和非法显式 runtime config 拒绝。
4. `src/` 与 `tests/` 中旧 env 运行时/测试入口引用清零。

M4 完成当时的剩余事项已在后续阶段收口：

1. 本地 `.env.web.local` 与远程 `/etc/goldenshare/web.env` 的旧 env 已在 M8 清零。
2. Biz `RealtimeSnapshotReader` 已在 M5 下沉。
3. 配置中心 API 与前端页面已在 M6/M7 完成。

## 12. M5 Biz SnapshotReader 下沉状态

M5 已完成以下内容：

1. 新增 foundation `RealtimeSnapshotReader`，统一封装 runtime config、feed key、Redis current batch、交易时段和 stale 判断。
2. Biz 日线/分钟查询服务只保留参数校验、数量限制和 response schema 映射。
3. 外部 realtime API 路径、response schema 与错误码保持不变。
4. Ops health 仍直接读取 runtime config，用于展示“应然配置 + 实然状态”，不属于 M5。

M5 完成当时的剩余事项已收口：

1. 配置中心 API 和发布审计已在 M6 完成，前端页面已在 M7 完成。
2. 本地或远程旧 env 已在 M8 清零。
3. Redis key 模型未改变；WebSocket 仍是后续独立事项。

## 13. M6 Ops 配置 API 落地状态

M6 已完成以下内容：

1. 新增 `/api/v1/ops/realtime/config/objects`、`detail`、`validate`、`publish`、`revisions` API。
2. 配置对象当时限定为 `stock_rt_daily` 和 `stock_rt_min`；本轮实时 ETF 主线已新增 `etf_rt_daily` 配置对象。单股当日分时序列不进入配置中心当前主线。
3. 配置中心只允许白名单字段发布；`source_api_name`、`exchange`、`collection_sessions`、`ts_code_pattern`、`feed_key/feed_key_pattern` 为锁定字段。
4. `validate` 只校验和返回 diff/影响，不落库；`publish` 带 version，成功后更新 `foundation.realtime_runtime_config`、写 `ops.config_revision`、清 runtime config cache。
5. 发布后仍需要重启 collector 生效；M6 不做热加载、不请求 Tushare、不读写 Redis。

M6 完成当时的剩余事项已收口或保持边界：

1. 前端配置中心页面已在 M7 接入，只调用配置中心 objects/detail/validate/publish/revisions API。
2. 本地或远程旧 env 已在 M8 清零。
3. 未改变 Ops health、Biz realtime API、collector、Redis key 或 WebSocket 设计。

## 14. M7.1 发布生效闭环已收口项

### 14.1 当前问题

当前 `foundation.realtime_runtime_config.requires_collector_restart` 的真实语义是“这类配置发布后需要重启 collector 才能被读取”。它不是运行状态字段，也不会因为执行了 `systemctl restart goldenshare-realtime-collector.service` 自动变成 false。

因此，页面如果直接把它显示成“需重启”，会出现以下误导：

1. 发布后显示“需重启”，这是合理提示。
2. 管理员已经手动重启 collector，服务也已 active。
3. 数据库字段仍为 true。
4. 页面继续显示“需重启”，看起来像重启没有生效。

这不是 collector 是否启动的问题，而是缺少“collector 已经应用了哪个配置版本”的事实。

### 14.2 目标状态模型

| 状态事实 | 来源 | 含义 | 目标处理 |
| --- | --- | --- | --- |
| `published_version` | `foundation.realtime_runtime_config.version` | 配置中心当前发布版本。 | 配置 API 继续返回。 |
| `requires_collector_restart` | `foundation.realtime_runtime_config` | 发布影响策略：此对象变更需要重启 collector 生效。 | 只作为提示，不作为待重启状态。 |
| `applied_version` | collector 写入 Redis health | 当前 collector 进程实际读取并应用的配置版本。 | M7.1 新增上报。 |
| `restart_pending` | Ops Config API 派生 | `published_version > applied_version` 时为 true。 | 前端只按该字段显示“待重启”。 |
| `apply_state.status` | Ops Config API 派生 | `applied`、`pending_restart`、`unknown`。 | 前端展示状态标签。 |

### 14.3 需要审计和修改的消费者

| 消费者 | 当前行为 | M7.1 修改目标 |
| --- | --- | --- |
| collector | 启动或每轮循环前读取 runtime config 并写 `realtime_config_apply_state`。 | 已完成；即使分钟 feed 关闭，也上报 `stock_rt_min` 已应用版本。 |
| Ops Config API detail/list | 返回 `requires_collector_restart` 静态字段，同时派生 `apply_state`。 | 已完成；字段缺失时返回 unknown。 |
| 前端配置中心 | 按 `apply_state` 显示“待重启生效 / 已应用 / 应用状态未知”。 | 已完成；不再把 `requires_collector_restart` 当当前状态。 |
| 运维重启操作 | 页面提供受控重启入口，只触发固定 systemd 服务 restart/status。 | 已完成；按钮不直接修改 apply state，是否生效仍以 collector 上报版本为准。 |

### 14.4 受控重启按钮边界

若实现页面“重启 collector”按钮，必须满足以下约束：

1. API 只能重启 `goldenshare-realtime-collector.service`，禁止接受任意服务名或命令。
2. API 必须 admin-only。
3. API 不修改 runtime config，不请求 Tushare，不读写行情 Redis，不触碰业务数据表。
4. 如果 Web 进程需要执行 systemd，只允许配置窄权限 sudoers：`status/restart goldenshare-realtime-collector.service`。
5. 重启命令成功不代表配置已生效；页面必须继续轮询，直到 collector 上报 `applied_version == published_version`。
6. 重启操作不是配置发布，不写 `ops.config_revision`；M7.1 只写服务日志和返回接口结果，后续若需要持久化审计再单独设计运维操作日志。

### 14.5 验收门禁

1. 发布配置后，配置版本递增，页面显示“待重启生效”。
2. 重启 collector 后，collector health 上报当前配置版本，页面显示“已应用”。
3. Redis health 不可用或缺少版本时，页面显示“应用状态未知”，不得显示“已应用”。
4. 重启命令成功但 collector 未上报新版本时，页面保持“等待 collector 上报”或“重启未确认”。
5. 静态 `requires_collector_restart=true` 不得再单独驱动“需重启”标签。
6. 配置中心发布、collector 重启、实时行情采集三件事保持边界清晰：发布写配置表，重启控制服务，采集写 Redis 快照。

## 15. M8 env 与文档收口状态

M8 已完成以下内容：

1. 本地 `.env.web.local` 已确认不存在 `REALTIME_STOCK_RT_*` key。
2. 远程 `/etc/goldenshare/web.env` 已通过 `bash scripts/remote-web-env.sh unset KEY` 清除残留旧 key，复核结果为 `NO_REALTIME_STOCK_RT_KEYS`。
3. 远程 `REDIS_URL` 已确认仍存在；Redis 连接配置继续作为部署级 env，不进入配置中心。
4. 远程 `goldenshare-web.service` 与 `goldenshare-realtime-collector.service` 已在清理后重启并保持 `active`。
5. 远程 `foundation.realtime_runtime_config` 当时存在 `stock_rt_daily`、`stock_rt_min` 两行；实时 ETF 主线部署后必须补 seed `etf_rt_daily` 行。当前启停值以配置中心/DB 为准。
6. collector 当时已重新上报 `realtime_config_apply_state`，其中 `stock_rt_daily.version=2`、`stock_rt_min.version=1`；实时 ETF 主线要求 apply state 同步包含 `etf_rt_daily.version`。
7. 实时日线、实时分钟、远程部署、配置中心 showcase、单股当日分时序列方案已同步当前配置中心口径；旧 env 只作为历史/退场说明存在。

M8 不做的事情：

1. 不擅自修改 `stock_rt_daily.enabled`、`stock_rt_min.enabled` 或 `etf_rt_daily.enabled`。
2. 不新增配置对象、不改 Redis key、不改 collector 调度、不改 Biz/Ops API。
3. 不处理 WebSocket；仍作为后续独立事项。
