# ETF 实时日线维护说明

状态：代码已接入；生产启用与开市验收是下文带日期记录，本轮未查询今日开关或生产批次。
最近代码审计：2026-09-10。
源事实：[0400 ETF 实时日线](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0400_ETF实时日线.md)。
公共链路：[实时行情流维护说明](/Users/congming/github/goldenshare/docs/architecture/realtime-market-data-stream-technical-plan-v1.md)。
配置与生效：[配置中心](/Users/congming/github/goldenshare/docs/ops/ops-realtime-config-center-technical-plan-v1.md)。

## 1. 已确认范围

在交易日连续竞价时段按默认 60 秒间隔读取 rt_etf_k，保存源通配符结果，不用 ETF Basic 或旧池过滤采集范围。复用统一 collector 和 Redis 批次；不新增第二个服务、实时历史行情表、DatasetDefinition、TaskRun、freshness 或 date audit。当前没有 ETF 对外快照查询端点；WebSocket 也不在本轮范围。

“行情不落库”不等于整条 CLI 无 DB 写入：成功 ETF feed 后，CLI 会在独立 Session 调用现行业务异动监控。监控规则/统计是另一职责，不能据本文件删除。

## 2. 实现与失败边界

代码落点为 `src/foundation/realtime/etf_rt_daily.py`、collector_service、state_store 和 runtime_config；Ops health 在 `src/ops/queries/realtime_feed_health_query_service.py`。

| 步骤 | 当前行为 |
| --- | --- |
| 请求 | 先 SH：topic=HQ_FND_TICK、ts_code=5*.SH；再 SZ：topic 为空、ts_code=1*.SZ；都用显式 fields |
| 合并 | 两次调用都返回后合并并附 request_segment；任一调用抛错不发布部分结果 |
| 标准化 | trim，缺代码跳过并计数；旧 trade_time 和 OHLC 全 0 保留；没有按 ETF 类型二次过滤 |
| 保存 | feed_key=tushare_etf_rt_k；沿用公共 batch/current/stream/health/lease 模型 |
| 发布完整性 | 两段调用成功不是完整市场覆盖证明；空段成功返回也没有独立完整性失败门禁；重复代码最终按公共 store 后写覆盖 |
| 异常隔离 | 独立捕获 feed 异常，但统一循环串行，慢请求仍延迟其他工作 |

发布后清理发生在 Redis execute 之后；清理抛错时 current 可能已切换，health 也是独立写。不能把“源分段失败不发布”扩大成“任意异常都会保持旧批次”。发布后维护与事实提交彻底隔离仍是公共说明中记录的实现缺口，本轮不改代码。

## 3. 配置、消费者与维护

- 当前配置对象是 etf_rt_daily，不是“建议新增”；源请求段、feed_key、source_api_name 是锁定身份，不提供运营编辑。
- 默认 enabled=false；poll=60 秒、source timeout=20 秒、lease=120 秒、stale=180 秒、TTL=259200 秒、最近 3 批。完整默认值与发布校验只在配置中心维护，这些默认值不等于今日生产值；timeout 不包含全部重试/排队墙钟。
- CLI 启动加载配置，应用版本回报不等于热加载。部署由既有统一服务承载，不增加新安装步骤。
- Health 的 source_snapshot_count 是源批次保存范围；eligible_etf_count 是同次调用固定日期下 ETF Basic 当前可请求集合，eligible_snapshot_count 是该集合与批次的交集。这不是采集时冻结的 Basic 集合，三者不能强制相等。
- Ops 页面三组 Health/配置入口与轮询规则见[实时流监控](/Users/congming/github/goldenshare/docs/ops/ops-realtime-market-data-page-design-v1.md)，不重复维护 JSON 样例或旧池字段。
- 回归入口：tests/test_realtime_etf_rt_daily.py、test_realtime_runtime_config.py、test_realtime_collector_service.py、tests/web/test_realtime_api.py、test_ops_realtime_config_api.py。若改到页面另跑对应前端测试；仅文档变更不自动安装或启动服务。
- 维护必须保护：SZ 使用 1*.SZ 而非 15*.SZ；SH topic、显式 trade_time/买卖字段；零值/旧时间保留；分段异常不发布；配置版本与受控生效；源覆盖与 Basic 资格分离。历史约 2200 行不是运行容量上限或永久全集。

## 4. 历史开市真实验证记录（2026-06-03）

验证时间：2026-06-03 10:03-10:26 CST，A 股连续竞价时段。

验证工具：

1. `tushareMcp.rt_etf_k`：核验真实入参、字段、topic 行为。
2. 本地 `TushareHttpClient` 只读请求：补充行数、字段缺失、时间分布统计。

### 4.1 字段验证

默认返回字段不足以支撑实时快照展示，因为默认不返回 `trade_time`。

V1 provider 必须显式请求：

```text
ts_code,name,trade_time,pre_close,open,high,low,close,vol,amount,num,ask_price1,bid_price1,ask_volume1,bid_volume1
```

实测结论：

1. `trade_time` 可以显式返回，应作为快照时间字段保存。
2. `ask_price1/bid_price1` 虽未在本地文档输出参数表中列出，但开市实测沪深单只 ETF 均可显式返回。
3. 部分行 `open/high/low/close=0` 是源端事实，不得当作失败或无效行拒绝。
4. `name` 可能带尾部空格，normalizer 应做字符串 trim。

### 4.2 topic 与通配符验证

| 场景 | 请求 | 结果 | 结论 |
| --- | --- | --- | --- |
| 上海单只 | `topic="HQ_FND_TICK", ts_code="510300.SH"` | 返回 1 行 | 上海必须带 `HQ_FND_TICK` |
| 上海单只空 topic | `topic="", ts_code="510300.SH"` | 返回空数组 | 不能用空 topic 拉上海 |
| 上海通配符 | `topic="HQ_FND_TICK", ts_code="5*.SH"` | 返回上海侧数据 | 上海段采用此请求 |
| 深圳通配符 | `topic="", ts_code="1*.SZ"` | 返回深圳侧数据 | 深圳段采用此请求 |
| 深圳窄通配符 | `topic="", ts_code="15*.SZ"` | 返回深圳 `159...` 子集 | 会漏源端 `1*.SZ` 返回事实，不作为全市场范围 |
| 沪深拼接 + 上海 topic | `topic="HQ_FND_TICK", ts_code="5*.SH,15*.SZ"` | 只观测到上海侧 | 不能作为全市场请求 |
| 沪深拼接 + 空 topic | `topic="", ts_code="5*.SH,15*.SZ"` | 只观测到深圳侧 | 不能作为全市场请求 |

当时验证后采用的分段描述如下；market 是内部段标签，不向 Tushare 发送：

```json
[
  {"market": "SH", "topic": "HQ_FND_TICK", "ts_code": "5*.SH"},
  {"market": "SZ", "topic": "", "ts_code": "1*.SZ"}
]
```

### 4.3 行数与数据质量

2026-06-03 10:26 CST 使用最终通配符统计：

| 分段 | topic | ts_code | 行数 | ts_code 缺失 | trade_time 缺失 | OHLC 全 0 行 | trade_time 范围 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 上海 | `HQ_FND_TICK` | `5*.SH` | 1055 | 0 | 0 | 23 | `2026-06-03 10:26:26` ~ `2026-06-03 10:26:56` |
| 深圳 | 空字符串 | `1*.SZ` | 1151 | 0 | 0 | 64 | `2026-05-20 17:00:33` ~ `2026-06-03 10:26:54` |
| 合计 | - | - | 2206 | 0 | 0 | 87 | - |

说明：

1. 深圳 `1*.SZ` 会返回比 `15*.SZ` 更广的源端事实，包含 `123...`、`180...` 等代码段。由于已拍板“不筛，完整保存源端事实”，V1 使用 `1*.SZ`。
2. 深圳存在旧 `trade_time` 样本，这是源端返回事实。V1 不把单行旧时间判为整个 feed 失败，只在页面/health 中展示源端时间和批次时间。
3. 合计约 2200 行，60 秒一次、每轮 2 次源请求，适合 Redis 快照，不需要分页，不适合落库。


## 5. 历史生产配置收口记录（2026-06-18）

2026-06-18 已完成生产配置收口：

1. 远程代码版本：`2f7a79e8`。
2. `ops-seed-realtime-runtime-config --apply` 已创建缺失的 `etf_rt_daily` 配置行。
3. 通过配置服务发布 `etf_rt_daily.enabled=true`，配置版本从 `1` 升到 `2`，`ops.config_revision` 记录 revision `73`。
4. 已重启 `goldenshare-realtime-collector.service`。
5. collector 已上报 `etf_rt_daily.applied_version=2`，配置中心应显示“已应用”。
6. 当时收盘后 health 符合预期且未请求源站。该次历史验收使用旧池字段记录 1,395；当前契约已改为按 API 调用时固定日期动态读取 ETF Basic，返回 `eligible_etf_count/eligible_snapshot_count`，不再把该数量固化为运行门禁。

原记录记载开市验收已完成；其批次存在/分段结果是历史证据，后续 Basic 资格迁移不能倒写成 6 月 18 日的原始实测。以下按当前合同列出维护时应核验的项目（不是本轮新验收）：

1. `tushare_etf_rt_k` 产生 current batch。
2. `segment_counts` 同时包含 `SH` 与 `SZ`。
3. `source_snapshot_count/source_row_count` 与实时源批次一致；`eligible_etf_count/eligible_snapshot_count` 与同一次 Health 调用固定的 ETF Basic 当前可请求集合一致。
4. 任一分段失败时不切 current pointer，只写 degraded health。
