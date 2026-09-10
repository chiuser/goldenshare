# 实时行情流维护说明：公共链路与股票日线/分钟

状态：代码已接入；历史上线与验收记录见 §8，不代表本次核验了生产运行状态。
最近代码审计：2026-09-10。
本文件合并原实时行情与股票分钟两份 HTML；共同规则只在这里维护。

## 1. 范围与已确认边界

实时主链是：统一 collector 请求 Tushare → Redis 批次 → Biz 快照查询 / Ops 健康查询。股票日线、股票分钟和 ETF 日线共用基础设施，不把轮询包装为离线数据集或 TaskRun。

- Foundation 负责 provider、normalizer、采集时钟、Redis 和运行配置读取；Ops 负责配置发布、健康观测；Biz 负责对上只读查询；App/CLI 组合装配。
- 不新增实时历史行情表，不进入 DatasetDefinition、freshness 或 date completeness audit。
- 生产状态层要求 Redis，不以进程内测试替身替代跨进程状态；stream 是短期事件，不是长期历史。
- 业务请求不触发这三个 feed 的源请求。所谓“只读 Redis”仅指行情事实来源：配置、交易日历、ETF 资格等仍可能读 DB。
- 股票分钟的每个频率有独立 feed、批次和健康状态；不能覆盖日线 feed，也不能把五频率混成一个快照身份。
- WebSocket、tick/长期归档和指数盘中 feed 不属于当前闭环。ETF 日线差异见[ETF 维护说明](/Users/congming/github/goldenshare/docs/architecture/realtime-etf-daily-stream-plan-v1.md)；ETF 分钟与[单股当日分时](/Users/congming/github/goldenshare/docs/architecture/realtime-stock-intraday-minutes-on-demand-plan-v1.md)仍未接入，不能据方案直接启用。

## 2. 当前实现入口

以下均相对仓库根，不是待创建文件清单：

| 职责 | 实现与核验入口 |
| --- | --- |
| 调度 | `src/foundation/realtime/collector_service.py`：RealtimeCollectorService |
| 股票采集 | `src/foundation/realtime/stock_rt_daily.py`、`stock_rt_min.py` |
| ETF 采集 | `src/foundation/realtime/etf_rt_daily.py` |
| 配置事实与校验 | `src/foundation/realtime/config_catalog.py`、`runtime_config.py` |
| 批次发布/读取 | `src/foundation/realtime/state_store.py`、`snapshot_reader.py` |
| 采集时钟 | `src/foundation/realtime/market_clock.py` |
| 业务 API/DTO | `src/biz/api/realtime.py`、`src/biz/schemas/realtime.py` |
| Ops/页面合同 | [实时流监控](/Users/congming/github/goldenshare/docs/ops/ops-realtime-market-data-page-design-v1.md)、[配置中心](/Users/congming/github/goldenshare/docs/ops/ops-realtime-config-center-technical-plan-v1.md) |
| 运行入口 | `goldenshare realtime-collector-serve`；`scripts/goldenshare-realtime-collector.service` |

原草案的 CollectorPlan/RealtimeFeedDefinition 不作为现行类型。维护时以真实配置 dataclass、catalog 和上述调用链为准。

## 3. 股票请求与标准化

### 3.1 源接口与频率

| 项目 | 股票实时日线 | 股票实时分钟 |
| --- | --- | --- |
| 源文档 | [0372 A股实时日线](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/行情数据/0372_A股实时日线.md) | [0374 A股实时分钟](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/行情数据/0374_A股实时分钟.md) |
| api_name | `rt_k` | `rt_min` |
| 通配符 | `3*.SZ,6*.SH,0*.SZ,9*.BJ` | 同左，每个频率单独请求 |
| feed | `tushare_stock_rt_k` | `tushare_stock_rt_min_{freq小写}`，例如 tushare_stock_rt_min_1min |
| 支持频率 | 日线快照 | `1MIN/5MIN/15MIN/30MIN/60MIN` |
| 时间字段 | `trade_time` | `time` |
| 采集间隔默认值 | 6 秒 | 每个启用频率 60 秒 |

日线显式 fields：
`ts_code,name,pre_close,high,open,low,close,vol,amount,num,ask_price1,ask_volume1,bid_price1,bid_volume1,trade_time`。

分钟显式 fields：
`ts_code,freq,time,open,close,high,low,vol,amount`。
必须显式请求并核验 freq；历史曾因 fields 漏填 freq 而误判源接口不支持，不能重犯。

原 V1 已拍板五频率全部开启；这项历史决定不等于本轮已核验今日生产五频率启用，实际启用集合以 DB 配置为准。每轮全开至少五次逻辑源调用，不是一次 HTTP 同时取得五频率。源端旧实测不支持依赖 limit/offset 分页；本轮没有重新测量源端。

### 3.2 行处理的实际边界

- 股票日线跳过缺 ts_code 行；字符串 trim，None/空字符串归一为空值。
- 股票分钟按第一个命中原因统计并跳过：missing_ts_code、missing_freq、freq_mismatch、missing_time；其余有效行继续形成批次。并非任意坏行使整批失败。
- 旧时间行保留，不用当天日期过滤停牌/退市等源端旧样本；feed 批次新鲜不等于每只证券的新鲜。
- 当前清洗不是严格数值/日期校验器：不能承诺拒绝全部 NaN、非法时间字符串或非有限价格。
- Redis 按规范化 ts_code 存每 feed 的快照，同批重复代码后写覆盖前写；source_row_count、normalizer 数量与最终 snapshot_count 不应默认相等。
- `raw_payload_hash` 用于识别源内容变化，received_at 等接收元数据不应制造每轮全量 delta。ETF 的 hash 还包含 request_segment。

## 4. 调度、限速与配置生效

### 4.1 调度事实

RealtimeCollectorService 使用一个同步循环：先股票日线，再启用的股票分钟频率，最后启用的 ETF 日线。各 feed 有独立 due time，不会因日线 6 秒周期而每 6 秒请求分钟。

各调用有异常捕获，但没有并发调度或总墙钟隔离。慢请求、HTTP 自动重试、等待限速以及 CLI 随后的 ETF 业务监控都会延后后续工作。due 以本轮开始时刻计算；超时后下轮可能已到期。不能写“单频超时不影响其他 feed 耗时”。外层返回 failed 结果也不意味着所有意外异常都已持久化成健康记录。

Tushare 客户端还存在按 api_name 共享的进程内限速器和 transport retry；配置 source_timeout 不是包含重试/排队的端到端 deadline。分钟对象的 max_calls_per_minute 不能理解为每个频率各享该额度，也不是跨进程全局预算。实际 HTTP 次数可能大于 collector 逻辑请求计数。

### 4.2 配置事实源

可编辑运行配置来自 `foundation.realtime_runtime_config`；catalog 锁定源 API、feed 身份、通配符和市场时段。旧 Settings/env 不再承载 feed 启停与轮询配置。连接地址、认证等基础环境配置不是被一并删除的对象。

配置中心是唯一配置维护说明，默认值、字段权限、发布/version 和受控重启流程直接引用，不另复制一套表。三组 seed 默认 enabled=false，不代表今天的 DB 值；旧文档中“生产已启用”均为带日期历史。

当前配置校验包括正整数、stale_after_seconds >= poll_interval_seconds、请求预算足以覆盖频率/分段数；没有“lease >= 3 倍 poll”或“stale >= 2 倍 poll”的通用校验。lease/source timeout 的运行安全仍需按实际耗时评估，不能把草案倍数冒充现行门禁。

CLI 启动时加载运行配置；每轮报告应用版本不等于热加载新配置。发布、重启及版本一致性以配置中心说明为准。

### 4.3 交易时段与租约

采用 SSE 交易日历与上海时区；仅交易日 09:30–11:30、13:00–15:00 请求源端。非交易日显示 market_closed；午休/收盘等非采集时段为空闲状态，不按采集中 stale 标准误报。具体边界判定由 market_clock 负责，页面不自行推导。

feed 租约用于避免多实例同时采集同一个 feed，不是客户端读锁。租约 TTL 不替代请求总耗时约束；不承诺进程暂停或超长请求下绝无重叠。

## 5. Redis 批次、事件与失败边界

### 5.1 Key 与读取

公共前缀 `rt:feed:{feed_key}` 下：
`current_batch`、`batch:{batch_id}:snapshot:{ts_code}`、`batch:{batch_id}:index`、
`batch:{batch_id}:meta`、`batches`、`stream:batch`、`stream:delta`、`health`、`lease`。

发布将 snapshot/index/meta、批次索引、current pointer 和 stream 写入 transaction=True pipeline，再 execute。读者先固定 batch_id，再按该批读取，不拼接前后两批。Redis 事务提供命令执行不被其他客户端插入的边界，不等于数据库式任意命令错误回滚。

batch snapshot/index/meta 默认 TTL 259200 秒，且只留最近 3 批；current pointer/health 不跟随该 TTL 自动过期。因此不能保证停机超过 TTL 后仍有可读行情，也不能保证慢读者的旧批次永远不被清理。

### 5.2 事件与 DTO

- batch stream 写 `batch_published`，字段为 event_type、feed_key、batch_id、snapshot_count、source_row_count、delta_count、published_at。
- delta stream 写 `quote_changed` 和变化股票的完整快照，不是 changed_fields 差量补丁；首批不灌全市场 delta。
- 后续与上一可读批次的源内容 hash 比较；没有证券消失的 tombstone 事件。stream 用近似 MAXLEN 裁剪。
- 接收/发布/请求耗时等分属快照、meta、health，不应从旧示例复制不在 stream 中的字段。
- 业务 DTO 只暴露 schema 中列出的字段，不把内部 hash 自动暴露给页面。

### 5.3 必须明确的实现缺口

源请求在发布前失败通常保留旧 current；但 `publish_batch()` 的旧批次清理在 pipeline.execute() 之后。若清理失败，该方法会抛 RealtimeStateStoreUnavailable，而新 current 可能已经发布；health 成功写入也是另一操作。

因此“任意异常都不切 current”“health 失败表示行情未发布”均不成立。原设计要求的“发布后维护失败只影响维护观测，不反转已发布事实”继续保留为**尚未完全实现的隔离要求**，不是本轮已修复代码。后续若改造必须单独评审并测 execute 后清理/health 失败；不得借文档整理引入快照备份或更改现行返回行为。

## 6. 当前查询与页面

- 股票日线：`GET /api/v1/realtime/stock-rt-daily`。
- 股票分钟：`GET /api/v1/realtime/stock-rt-min`，freq 必填，无默认频率。
- ts_codes 必填，trim/大写/去重后最多 200。分钟明确拒绝含 * 的代码；日线没有同样的通配符拒绝校验，只按字符串查快照，不展开通配符，不能统一写成两者都会报 400。
- 分钟 limit/offset 明确返回 400 UNSUPPORTED_QUERY_PARAM；不能扩写成任意额外 query 参数都返回 400。
- 已支持频率不等于 enabled_freqs；读接口按支持范围和可读批次判断，不用禁用开关自动删除旧快照。
- 批次或 meta 不存在为 503 REALTIME_FEED_UNAVAILABLE；Redis 不可读为 503 REALTIME_STATE_UNAVAILABLE；单只未命中通过 missing_ts_codes 返回。
- 响应包含 feed_key、batch_id、received_at、published_at、stale、stale_after_seconds、collection_status、items、missing_ts_codes；分钟额外 freq。数值行情字段保持字符串/空值，具体字段见 schema。
- Ops health 三组接口、状态优先级、collector_running 推导、ETF Basic 数量与配置失效处理只在[监控说明](/Users/congming/github/goldenshare/docs/ops/ops-realtime-market-data-page-design-v1.md)维护。
- 页面首次取 health，再按 page_polling_enabled/recommended_poll_interval_seconds 局部轮询；不显示 TaskRun/freshness，不手动同步，不整页刷新。

## 7. 维护与回归

已有 systemd unit、部署脚本及 sudoers 挂载；不是本轮待安装任务。重启/部署/安装均须独立授权，不能从文中历史命令推导执行权限。

现有回归入口：tests/test_realtime_collector_service.py、test_realtime_collector_cli_contracts.py、test_realtime_state_store.py、test_realtime_runtime_config.py、test_realtime_snapshot_reader.py、test_realtime_stock_rt_min.py、test_realtime_etf_rt_daily.py、tests/web/test_realtime_api.py。执行前核验路径，使用已有环境，不使用可能自动同步依赖的运行方式。

回归关注：禁用/非时段不请求、频率与预算、旧时间保留、字段缺失统计、首批无 delta、当前批次读取、API 上限和错误、配置重启生效、各 feed 异常。内存替身测试不证明真实 Redis execute 后清理故障安全，生产验收也不能由文档链接检查代替。

## 8. 历史证据（不代表今日生产状态）

### 8.1 股票日线 M1（2026-05-14/15）

当时的真实请求核验清单如下（不是本轮重新执行指令）：

1. `rt_k(ts_code="3*.SZ,6*.SH,0*.SZ,9*.BJ")` 是否稳定返回全市场。
2. 返回行数是否小于 6000。
3. 所有声明字段是否可通过 `fields` 返回。
4. 交易时段中、午休、收盘后分别返回什么样的 `trade_time`。
5. 单次请求耗时是否适合 6 秒轮询。
6. 空值形态是否包含 `None`、空字符串、`nan` 等脏值。

如果全市场请求在真实测试中不稳定，必须停下来重新评审请求策略，不能直接改成分片请求。

收盘后初步探测记录：

| 项目 | 结果 |
| --- | --- |
| 探测时间 | 2026-05-14 收盘后 |
| 请求参数 | `rt_k(ts_code="3*.SZ,6*.SH,0*.SZ,9*.BJ")` |
| 返回行数 | 5521 |
| 耗时 | 约 503ms |
| 字段完整性 | 样本字段均返回；本次统计字段空值为 0 |
| `trade_time` 样本 | `2026-05-14 17:00:00` 到 `2026-05-14 17:00:xx` |

结论：Tushare 收盘后仍可返回实时日线快照，但 V1 collector 按已确认口径只在 9:30-11:30、13:00-15:00 请求源站。这是 5 月 14 日的阶段结论；次日验证见下表。

开市时段验证记录：

| 项目 | 结果 |
| --- | --- |
| 探测时间 | 2026-05-15 09:32-09:35，A 股连续竞价时段 |
| 请求参数 | `rt_k(ts_code="3*.SZ,6*.SH,0*.SZ,9*.BJ")` |
| 单次返回行数 | 5523 |
| 连续 3 轮返回行数 | 5523 / 5523 / 5523 |
| 单次耗时 | 约 648ms - 1208ms |
| 字段完整性 | `ts_code/name/pre_close/high/open/low/close/vol/amount/num/ask_price1/ask_volume1/bid_price1/bid_volume1/trade_time` 均返回 |
| 空值统计 | 本次 15 个字段空值计数均为 0 |
| 交易所后缀分布 | `BJ=313`，`SH=2315`，`SZ=2895` |
| 今日 `trade_time` 行数 | 5517 |
| 非今日 `trade_time` 行数 | 6 |
| 观测到的旧 `trade_time` 样本 | 退市/特殊/停牌类股票，如 `立方退`、`东通退`、`长药退`、`*ST精伦`、`德邦股份` |

开市验证结论：

1. V1 可以继续使用全市场通配符一次请求方案，不需要为了 M1 改成分片请求。
2. `trade_time` 是源端行情时间，不是 collector 健康时间；同一批次内允许少数股票保留旧 `trade_time`。
3. collector 健康必须以 `last_success_at/current_batch_published_at/current_batch_age_seconds` 判断，不能用所有行 `trade_time` 是否等于今天判断。
4. 业务 API 应原样返回单只股票的 `trade_time`，让调用方知道该证券自身最新行情时间。


### 8.2 股票分钟源端证据与确认口径

2026-05-17 周日，全市场通配符五频率分别返回 5529 行：SZ 2898、SH 2317、BJ 314；limit=10、offset=1000 没有改变全市场行数。600000.SH 单只样本为 5 月 15 日收盘附近旧时间。该证据支持保留旧时间，不证明交易中每行都同步更新。

2026-06-01 [M3 开市报告](/Users/congming/github/goldenshare/docs/architecture/realtime-stock-minute-m3-open-market-validation-2026-06-01.md)保留原始五频率行数、耗时与逐项结果。原分钟 D1–D8 收敛为：支持五频率、每频率独立 feed、初始 60 秒间隔与共享预算、API freq 必填、rt_min_daily 独立延后、保留旧时间行、同一 Ops 菜单分钟组、开市 M3 已有历史证据。

### 8.3 原 2026-06-02 收口记录（后续补记含配置切换）

已完成：

1. 生产服务器 Redis 基础设施已安装并验证：Ubuntu 24.04 apt 源 Redis `7.0.15`，仅监听 `127.0.0.1/[::1]`，`redis-cli ping` 返回 `PONG`。
2. 远程 Web 环境已写入 `REDIS_URL=redis://127.0.0.1:6379/0`。
3. 代码已加入实时配置项、`foundation/realtime` Redis batch pointer 状态层、业务快照 API 骨架、Ops health API 骨架。
4. 数据运营后台已加入一级菜单“实时流监控”，页面只消费 health API，并按 `page_polling_enabled/recommended_poll_interval_seconds` 做局部状态刷新。
5. 已补最小测试覆盖：Redis key/current batch 语义、业务快照 API、Ops health API，以及前端类型检查。
6. 开市时段 M1 真实验证已完成，结论支持全市场通配符请求方案。
7. 已新增 Tushare 0372 provider、实时日线 normalizer、collector loop、CLI `realtime-collector-serve`、collector systemd unit 与部署脚本挂载。
8. 远程已发版至 `793070d3`，`goldenshare-realtime-collector.service` 已安装、启动并启用开机自启动，ExecStart 为 `goldenshare realtime-collector-serve`。
9. 股票实时分钟 M4-M7 已完成：provider/normalizer/feed、统一 collector 调度、业务 API、Ops health API、实时流监控分钟分组均已落地。
10. 生产实时流配置入口已切到 `foundation.realtime_runtime_config`，旧 env 清理后已重启 collector 与 Web；当前启停值以配置中心/DB 为准。
11. 远程收市验收通过：统一 collector active/running，股票实时分钟五频率 feed 被调度但因非采集时段显示 idle，不请求源站或写行情批次。

后续阶段：

1. WebSocket 推送仍是后续阶段，不在本轮范围内。

---
