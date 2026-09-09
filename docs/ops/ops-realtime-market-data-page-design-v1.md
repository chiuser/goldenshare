# Ops 实时流监控：页面与健康状态

状态：现行实现说明；2026-09-09 按代码、schema、页面与测试定义核对。替代原 HTML 静态监控稿，不代表本轮生产或浏览器验收。

## 1. 页面职责

`/ops/v21/realtime` 展示股票实时日线、股票实时分钟、ETF 实时日线三组采集健康：运行状态、Redis 当前批次、源请求、错误及事件指标。它不是离线数据集 freshness、入库完整性或 TaskRun 页面，不提供手动同步、停止任务或直接触发采集。

改配置与受控重启使用独立的[实时流配置中心](/Users/congming/github/goldenshare/docs/ops/ops-realtime-config-center-technical-plan-v1.md)。页面不直接调用 Tushare，不连接 Redis，不调用 Biz 行情快照 API，不自行推导交易时段、stale、feed key 或分钟频率清单。

## 2. 三组接口与轮询

全部是管理员 GET 接口，路由见 [realtime.py](/Users/congming/github/goldenshare/src/ops/api/realtime.py)。

| 分组 | API | 主要内容 |
| --- | --- | --- |
| 股票实时日线 | `/api/v1/ops/realtime/stock-rt-daily/health` | 当前批次、股票快照数、请求与事件指标 |
| 股票实时分钟 | `/api/v1/ops/realtime/stock-rt-min/health` | `items` 逐频率展示，`configured_freqs/supported_freqs` 区分配置和支持范围 |
| ETF 实时日线 | `/api/v1/ops/realtime/etf-rt-daily/health` | 源批次数量、ETF Basic 当前可请求集合命中、请求段与无效行 |

页面首次分别读取三个接口，分钟请求不附加 `freq`；接口本身支持按频率查询，但页面使用后端返回的完整 items。分组独立加载，某组失败不隐藏另两组。

定时刷新由每组响应的 `page_polling_enabled` 控制：交易日采集窗口内且对应对象启用才开启；分钟还要求请求频率与配置频率有交集。后端当前建议间隔为 60 秒，前端按 `max(10, recommended_poll_interval_seconds || 60)` 秒设置刷新。为 false 时停止定时轮询；不要把它解释成禁止首次读取或其他查询库触发的重新获取。

这只是页面刷新间隔，不是 collector 的采集间隔。collector 间隔、限速、stale、TTL 和保留批次来自运行配置，不把旧稿中的 6/60 秒、72 小时、3 批或示例行数当成当前生产值。交易日历与时段由服务端解析，前端不设置自己的开收盘定时器。

## 3. 健康状态如何理解

实现见 [RealtimeFeedHealthQueryService](/Users/congming/github/goldenshare/src/ops/queries/realtime_feed_health_query_service.py)。以下为当前 `_resolve_status` 分支顺序；Redis 异常等外层分支另述。

| 判定条件 | status | 含义 |
| --- | --- | --- |
| 对象或频率未启用 | `idle` | 停用，不是等待离线任务 |
| 已保存的采集状态为 degraded | `degraded` | 降级状态优先，不因休市或已有快照自动消失 |
| 无有效 current batch/meta | 开市 `unavailable`，其他时段 `idle` | 区分应有新数据和正常非采集时段 |
| 开市且批次年龄超过配置阈值 | `stale` | 旧批次仍可展示，但已滞后 |
| 开市且未命中以上异常 | `ok` | 按当前可观测信息未判为异常 |
| 其他正常非采集时段 | `idle` | 午休、收盘、休市等 |

Redis 读取异常在日线/ETF 查询中直接返回 `unavailable`；分钟启用项同样返回 unavailable，停用项保持 idle。因此“非交易时段所有异常必须改成空闲”不是当前规则。`collection_status` 单独说明开市、午休、休市或停用；不要与总健康状态混用。

分钟汇总优先级为 `unavailable > degraded > stale > ok > idle`，无 items 时为 idle。页面直接消费总状态和逐频率状态，不重新计算。

`collector_running` 当前由 Redis health 中的运行标记或 collector_id 推导，不是实时 systemd 存活检查；“已观测到 collector”也不证明源数据完整。配置页的“版本已应用”同样不等于本页的“批次正常”。

## 4. 展示字段与读取边界

完整字段见 [健康响应 schema](/Users/congming/github/goldenshare/src/ops/schemas/realtime.py)。本表只解释分组，不代替完整 schema。

| 区域 | 字段 |
| --- | --- |
| 当前状态/窗口 | `status/enabled/is_trading_day/collection_status/collection_sessions` |
| collector | `collector_running/collector_id/last_request_at/last_success_at` |
| 当前批次 | `current_batch_id/current_batch_age_seconds/current_batch_received_at/current_batch_published_at/snapshot_count` |
| 请求与耗时 | `source_row_count/source_elapsed_ms/write_elapsed_ms/request_count_last_minute/max_calls_per_minute` |
| 运行配置 | `poll_interval_seconds/stale_after_seconds/snapshot_ttl_seconds/keep_recent_batches/batch_stream_maxlen/delta_stream_maxlen` |
| Stream 观测 | `last_batch_event_id/last_delta_event_id/delta_count_last_batch` |
| 错误 | `last_error_at/last_error_message`；分钟/ETF 补 `invalid_count/invalid_reason_counts` |
| ETF 专有 | `source_snapshot_count/eligible_etf_count/eligible_snapshot_count/segment_counts` |
| 页面轮询 | `page_polling_enabled/recommended_poll_interval_seconds` |

健康查询读已发布 DB 配置和 Redis health、current pointer、meta/数量等观测信息；不直接触发源请求。发布但尚未重启时，已发布参数与 collector 正在使用的参数可能不同，须结合配置中心版本状态判断。

Redis 当前批次不是历史库，也不代表离线表已入库。批次发布机制由底层 store/collector 承担，页面不拼 key 或切换 pointer。具体行情采集设计留在各行情流专题，本文不复制写入顺序作为另一套实现要求。

## 5. 验证入口与文档边界

- 页面：[ops-realtime-monitor-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-realtime-monitor-page.tsx)；测试：[ops-realtime-monitor-page.test.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-realtime-monitor-page.test.tsx)，覆盖三组展示、分组失败隔离及只调用 Ops health 的边界。
- 后端：[tests/web/test_realtime_api.py](/Users/congming/github/goldenshare/tests/web/test_realtime_api.py)，结合 health 查询/schema 检查交易时段、停用、空批次、Redis 异常、stale/degraded、频率及 ETF 命中字段。
- 文档治理只运行完整性、链接和静态对账；未连接生产、未运行 collector、未进行页面构建或浏览器验收，不宣称当前生产状态正常。

原 HTML 的展示要求归入 §1–4；过时 API 清单、固定指标和视觉样式不再保留。旧全文可从合并前提交 `ac8b3abd` 追溯，[逐文件去向](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md#ops-realtime-consolidation-20260909)见治理记录。
