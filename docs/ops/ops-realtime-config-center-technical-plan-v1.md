# Ops 实时流配置中心：配置、发布与生效

状态：现行实现说明；2026-09-09 按代码、schema、页面及测试定义核对。本文承接原技术方案、M1–M8 清单和 Showcase 的有效内容，不代表本轮生产验收。

## 1. 范围与事实来源

配置页 `/ops/v21/realtime/config` 管理股票实时日线、股票实时分钟、ETF 实时日线三个对象；[实时流监控](/Users/congming/github/goldenshare/docs/ops/ops-realtime-market-data-page-design-v1.md)单独展示运行健康。单股当日分时序列、ETF 实时分钟及 WebSocket 不因本次文档合并成为已接入能力。

| 信息 | 唯一来源与用途 |
| --- | --- |
| 已发布可编辑配置 | `foundation.realtime_runtime_config.runtime_config_json`；每个 `object_key` 一行，保存 `object_kind`、`version`、`requires_collector_restart`、更新人和时间 |
| 锁定事实 | [config_catalog.py](/Users/congming/github/goldenshare/src/foundation/realtime/config_catalog.py)：对象身份、显示名、源接口、feed key、交易时段和请求范围；不是页面可编辑配置 |
| 初始化默认值 | [runtime_config_seed_service.py](/Users/congming/github/goldenshare/src/foundation/realtime/runtime_config_seed_service.py)内的受控模板；只用于缺行初始化，不是运行时回退 |
| 部署连接与秘密 | Settings/env 中的 `REDIS_URL`、Tushare 凭据等；不进入配置中心，也不向页面暴露秘密值 |
| 发布历史 | `ops.config_revision`；记录 `object_type=realtime_runtime_config`、对象、前后值、操作人和时间，不参与运行时配置读取 |
| collector 已应用版本 | Redis health 的 `realtime_config_apply_state`；与数据库发布版本比较，不能以配置表的静态重启策略代替 |

旧 `REALTIME_STOCK_RT_*` env 已退出运行时和 seed 输入，不双读、不双写、不 fallback。配置缺行、类型或内容非法时失败，不通过旧 env 悄悄补值。运行配置由 [runtime_config.py](/Users/congming/github/goldenshare/src/foundation/realtime/runtime_config.py)统一构建。

## 2. 对象与完整编辑字段

以下默认值来自代码 seed，不代表当前生产值；查看实际值须读取配置 API/数据库。三对象的 seed 均默认停用。

| 对象 | object_key | object_kind | feed |
| --- | --- | --- | --- |
| 股票实时日线 | `stock_rt_daily` | `collector_feed` | `tushare_stock_rt_k` |
| 股票实时分钟 | `stock_rt_min` | `feed_group` | `tushare_stock_rt_min_{freq}`，后缀为小写频率 |
| ETF 实时日线 | `etf_rt_daily` | `collector_feed` | `tushare_etf_rt_k` |

编辑白名单由 [RealtimeConfigCommandService](/Users/congming/github/goldenshare/src/ops/services/realtime_config_service.py)提供，页面按 API 的 `fields` 渲染。数字字段使用 `number_input`，启停使用 `switch`，频率使用 `checkbox_group`。

| 字段 | 含义 | 股票日线默认 | 股票分钟默认 | ETF 日线默认 |
| --- | --- | --- | --- | --- |
| `enabled` | 是否启用 | false | false | false |
| `enabled_freqs` | 启用频率 | 不适用 | 1MIN、5MIN、15MIN、30MIN、60MIN | 不适用 |
| `poll_interval_seconds` | 调度间隔秒数 | 6 | 60 | 60 |
| `max_calls_per_minute` | 源请求限速 | 10 | 20 | 10 |
| `lease_ttl_seconds` | 采集租约 TTL 秒数 | 30 | 90 | 120 |
| `stale_after_seconds` | 滞后阈值秒数 | 20 | 90 | 180 |
| `snapshot_ttl_seconds` | 快照 TTL 秒数 | 259200 | 259200 | 259200 |
| `keep_recent_batches` | 保留批次数 | 3 | 3 | 3 |
| `batch_stream_maxlen` | 批次事件流长度上限 | 5000 | 5000 | 5000 |
| `delta_stream_maxlen` | 变化事件流长度上限 | 200000 | 200000 | 200000 |
| `source_timeout_seconds` | 源请求超时秒数 | 不提供此配置项 | 20 | 20 |

请求须提交当前对象的完整可编辑配置，不是局部 PATCH；推荐从详情的 `effective_config` 生成草稿。锁定字段和未知字段拒绝提交；不能只复制文档中的部分字段。完整请求/响应定义见 [realtime_config.py schema](/Users/congming/github/goldenshare/src/ops/schemas/realtime_config.py)，不另维护省略必填字段的“完整 JSON 样例”。

现行校验要点：

- 数字配置经 runtime resolver 转换并检查为正值；不要据此宣称已有额外的严格 JSON 数字类型门禁。
- `stale_after_seconds >= poll_interval_seconds`。
- 请求预算 `feed_count × 60 / poll_interval_seconds <= max_calls_per_minute`；股票日线按 1、分钟按所选频率数、ETF 按两个请求段计算。这是配置校验，不是实时耗时保证。
- 分钟 API 要求频率数组，值只能来自 API 返回的选项；去重、规范大小写后不得为空，停用时也不能提交空数组。
- 日线 9 项、分钟 11 项、ETF 10 项可编辑字段；当前字段没有“默认频率”项。字段变更须同步本文与消费者，不能在前端另建名单。

锁定项：三对象均包括 `source_api_name/exchange/collection_sessions/ts_code_pattern`；日线和 ETF 增加 `feed_key`，分钟增加 `feed_key_pattern`，ETF 增加 `request_segments`。当前 catalog 使用 SSE 交易日历、`09:30-11:30,13:00-15:00`；股票通配符和 ETF 沪深请求段由 catalog 维护。本文不新增源接口契约或授权修改请求范围。

## 3. API 与发布边界

路由统一位于 [src/ops/api/realtime.py](/Users/congming/github/goldenshare/src/ops/api/realtime.py)，全部要求管理员身份。不是独立的 `realtime_config.py` 路由文件，也不再是 health-only。

下表配置路径前缀为 `/api/v1/ops/realtime/config`。

| 方法与相对路径 | 行为 |
| --- | --- |
| GET `/objects` | 返回对象摘要及 `apply_state`；读取配置表和 Redis 版本上报 |
| GET `/objects/{object_key}` | 返回配置、锁定项、字段元信息及 `apply_state` |
| POST `/objects/{object_key}/validate` | 请求体 `runtime_config`；返回 `valid/errors/warnings/diff/impact`，不保存草稿或发布 |
| PUT `/objects/{object_key}` | 请求体 `version + runtime_config`；重新校验，保存配置及修订记录，响应包含生效状态 |
| GET `/objects/{object_key}/revisions` | 返回 `items/total`，按时间和 ID 倒序；当前未分页 |
| POST `/collector/restart` | 固定服务的 restart/status；不接受客户端指定命令或服务名 |

详情包含 `object_key/display_name/object_kind/mode/version/requires_collector_restart/apply_state/effective_config/locked_config/fields`；每项字段元信息含 `key/label/editable/control/value_type/options`。`effective_config` 是已发布、经 resolver 构建的配置，不证明 collector 已加载。

发布时版本不一致返回 409；非法草稿返回 422，未知对象返回 404。发生实际差异才递增版本并写 revision；无差异不新增修订记录，`revision_id` 可为 null。配置和 revision 在同一会话提交后，清除当前进程的 runtime config 缓存；这不是跨进程通知，也不会替 collector 热加载。

发布响应中的 `impact` 表达需要重启的策略及受影响 feed；分钟列出五个支持频率的 feed，不是正在采集频率的实测清单。读取版本上报失败时返回应用状态未知，不将未知伪装成已应用。配置查询/发布不直接请求源站或写行情快照；不要把“允许读 Redis health”误写成“允许改行情批次”。

## 4. 从发布到生效

```text
配置页校验草稿 → 发布到配置表 + revision
                         ↓
管理员重启固定 collector → 启动时读配置 → 每轮上报所用版本
                                               ↓
配置 API 比较发布版本与上报版本 → 页面展示 apply_state
```

[CLI](/Users/congming/github/goldenshare/src/cli_parts/realtime_handlers.py)在启动时显式加载配置并传给 [collector](/Users/congming/github/goldenshare/src/foundation/realtime/collector_service.py)。每轮只上报这个配置对象的版本，不重新加载数据库配置；停用对象也包含在上报中。`applied_at` 是本轮上报时间，`process_started_at` 是进程启动时间。

| 条件 | apply_state.status | restart_pending |
| --- | --- | --- |
| 上报版本大于或等于发布版本 | `applied` | false |
| 上报版本小于发布版本 | `pending_restart` | true |
| 无 store、读取失败、缺少对象版本或无法解析版本 | `unknown` | null |

这是当前版本比较实现，不是独立的进程存活探测。`requires_collector_restart` 只表示发布策略，不能单独用于显示“当前待重启”。

受控重启只操作 `goldenshare-realtime-collector.service`，执行 `sudo -n /usr/bin/systemctl restart/status`；每次子命令超时为 30 秒。Web 运行环境须具备该固定服务及最小 sudoers 权限，不接受任意命令，也不因本文存在而自动授权部署或重启。

重启接口直接行为是控制服务、写日志并返回结果，不写 runtime config、行情快照或 `ops.config_revision`；重启后的 collector 会按已发布配置恢复正常采集。当前重启操作没有独立持久化运维审计表。

重启返回成功只表示 restart/status 命令成功。页面随后最多查询选中对象 10 次，相邻尝试等待 2 秒，收到 `applied` 后提前结束；不保证总耗时固定，不是无限等待。**当前没有专门的超时“重启未确认”提示**，次数用完仍展示最近一次 `apply_state`。原方案要求的明确超时提示尚未实现，不能写成已验收；若后续改造须另行确认，本轮不改代码。

## 5. 页面交互

实际入口：[ops-realtime-config-center-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-realtime-config-center-page.tsx)。旧 Showcase 是历史 mock，不再作为最新交互或运行事实源。

- 进入页面读取对象列表，默认选择首个对象，加载详情和修订记录；切换对象重置编辑状态。
- 查看态展示已发布配置、锁定项、版本及应用状态；不混入草稿、校验和发布操作。不要把“有效配置”文案理解成已由进程应用，须同时看 `apply_state`。
- 编辑态从 API 字段元信息生成控件，锁定项只读；分钟频率用多选而不是逗号字符串。草稿仅在页面内存，不存在服务端保存草稿流程。
- 草稿校验通过且校验对应的草稿未改变，才允许发布；修改草稿使原校验失效。409 提示刷新重试，不自动覆盖他人变更。
- 发布后回到查看态并刷新列表、详情、历史；重启按钮在非 `applied` 状态显示，操作后按 §4 确认。
- 配置页不调用监控 health API 或 Biz 行情 API；它读取的配置 API 在服务端可查询 Redis 版本上报。两层边界不能混为一谈。

## 6. 实现与消费者索引

| 位置 | 职责与消费边界 |
| --- | --- |
| [模型](/Users/congming/github/goldenshare/src/foundation/models/meta/realtime_runtime_config.py)、[App 注册](/Users/congming/github/goldenshare/src/app/model_registry.py) | 配置表 ORM 与应用注册 |
| [runtime config](/Users/congming/github/goldenshare/src/foundation/realtime/runtime_config.py)、[包出口](/Users/congming/github/goldenshare/src/foundation/realtime/__init__.py) | DB 加载、校验、构建、缓存与统一读取；显式 session 读取和无 session 缓存读取须区分 |
| [seed](/Users/congming/github/goldenshare/src/foundation/realtime/runtime_config_seed_service.py) | `goldenshare ops-seed-realtime-runtime-config` 默认 dry-run，`--apply` 才创建缺行；已有行跳过，不改已有版本、不写发布 revision |
| [CLI](/Users/congming/github/goldenshare/src/cli_parts/realtime_handlers.py)、[collector](/Users/congming/github/goldenshare/src/foundation/realtime/collector_service.py) | 启动加载、三类 feed 调度与版本上报；ETF 成功批次后的监控调用另有业务链，不由配置中心直接执行 |
| [股票日线](/Users/congming/github/goldenshare/src/foundation/realtime/stock_rt_daily.py)、[股票分钟](/Users/congming/github/goldenshare/src/foundation/realtime/stock_rt_min.py)、[ETF 日线](/Users/congming/github/goldenshare/src/foundation/realtime/etf_rt_daily.py) | provider/collector 使用统一配置及 catalog 锁定事实 |
| [Tushare client](/Users/congming/github/goldenshare/src/foundation/clients/tushare_client.py)、[Redis 依赖](/Users/congming/github/goldenshare/src/app/dependencies/realtime.py) | 实时接口限速通过 resolver 获取；store 连接来自部署配置 |
| [SnapshotReader](/Users/congming/github/goldenshare/src/foundation/realtime/snapshot_reader.py) | 封装快照读取；Biz 股票日线/分钟查询只做输入及响应映射，不自行拼 feed key 或计算 stale |
| [Ops health](/Users/congming/github/goldenshare/src/ops/queries/realtime_feed_health_query_service.py) | 读取已发布配置与 Redis health/meta，派生监控响应，不是配置发布入口 |
| [配置服务](/Users/congming/github/goldenshare/src/ops/services/realtime_config_service.py) | 查询、校验、发布、修订、生效判断与独立受控重启 |

核心回归入口：`tests/test_realtime_runtime_config.py`、`test_realtime_runtime_config_model.py`、`test_realtime_runtime_config_seed_service.py`、`test_cli_realtime_runtime_config_seed.py`、`test_realtime_collector_service.py`、`test_realtime_snapshot_reader.py`（均在 `tests/`），以及 [配置 API 测试](/Users/congming/github/goldenshare/tests/web/test_ops_realtime_config_api.py)、[页面测试](/Users/congming/github/goldenshare/frontend/src/pages/ops-realtime-config-center-page.test.tsx)。

变更配置合同时核验：缺行不回退、锁定/未知项拒绝、完整字段与频率/预算/stale 校验、权限、无副作用校验、版本冲突、无差异发布、revision、应用状态未知/待重启/已应用及页面草稿失效。collector/provider、源限速与 Biz 消费回归继续覆盖，不把文档校验当成这些测试的替代。

## 7. 历史摘要与本轮边界

- 原清单起于 2026-06-02，记录 M1–M8 完成：配置表与 seed、统一读取、旧 env 退出、Biz reader、配置 API、页面及版本上报闭环。迁移 [20260602_000116](/Users/congming/github/goldenshare/alembic/versions/20260602_000116_add_realtime_runtime_config.py)的父版本为 `20260531_000115`；这是历史，不是今天新建迁移时的 head。
- 原 M1 记录架构护栏 `14 passed in 5.83s`；原 M8 记录本地/远程旧 env 清理、Redis 连接项保留、Web 与 collector 重启后 active。2026-06-18 记录 ETF 发布版本和已应用版本均为 2。以上只保留为当时的验收摘要，本轮未独立复验生产。
- 2026-09-09 合并删除三份原配置文档，全文可从合并前提交 `ac8b3abd` 追溯；旧 env 全量映射、已完成施工阶段和 mock 数值不再并行维护。有效去向见[整合记录](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md#ops-realtime-consolidation-20260909)。
- 本轮只做文档与引用纠偏：不运行 seed、迁移、重启、采集或发布，不修改启停/频率/阈值、Redis key、代码和依赖边界。独立按需查询、ETF 分钟及异动监控重构的状态不由本次合并改变。
