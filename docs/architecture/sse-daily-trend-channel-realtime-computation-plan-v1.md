# 上证指数日线趋势通道：决策与范围

状态：代码及前端已接入；2026-09-05 管理员确认实际生产拓扑验证并结案。
最近文档审计：2026-09-10。这里维护决策与理由；公式、API、缓存、消费者及测试只在 [LLD](/Users/congming/github/goldenshare/docs/architecture/sse-daily-trend-channel-realtime-computation-low-level-design-v1.md)维护。
[历史 M4 验收报告](/Users/congming/github/goldenshare/docs/architecture/sse-daily-trend-channel-m4-readonly-performance-validation-2026-08-10.md)保留 8 月 10 日原始性能样本与 9 月 5 日关闭记录；本轮没有生产复测。

## 1. 为什么这样做

上证指数详情页从正式 DB 日线历史计算 25/90 高低价 EMA 双通道，通过独立只读 API 交付。不从页面已 limit 的 K 线窗口重算，否则 EMA 种子和状态丢失，同一天会随窗口变化。

“实时计算”指请求时依据正式日线按需计算/读缓存，不是盘中指数实时行情。目前本能力不接指数盘中 OHLC，成功行均 is_provisional=false。

25/90 是已批准的 Goldenshare v1 产品公式，不是已证明的原软件源码。版本固定为 sse-daily-trend-channel-v1，靠独立金标保证自身可复现。通道描述历史技术状态，不是交易指令。

正式输入为 core_serving.index_basic 身份和 index_daily_serving 日线。本地历史评估中，约 6445 根序列的纯计算中位数 2.274ms、P95 2.430ms，而逐日 Parquet glob 扫描中位数约 302.59ms；这解释了不把请求直接接 Lake 小文件扫描的取舍。这些是原方案历史样本，不能冒充当前 DB 行数或 API 端到端耗时。M0 固定正式样本为 1599 行（2020-01-02 至 2026-08-07）；M4 后续样本为 1600 行，日期和用途不同，不冲突。

采用可清空、至多两版本的进程内缓存，避免为单指数/单周期提前建设物化表或分布式缓存。重启/多进程各自冷算可接受；源 DB 查询仍发生，热缓存不是零 DB 成本。

## 2. 已拍板结论

管理员于 2026-08-10 确认：

1. `25/90` 作为 Goldenshare v1 正式周期。
2. 通道内部保留上一状态，同时单独返回 `position`。
3. v1 只返回正式日线，不做盘中临时值。
4. 使用独立 `/api/v1/quote/detail/trend-channel`，不修改共享 K 线合同。

管理员于 2026-08-11 补充确认页面消费规则：

5. 指数详情页只对 `000001.SH` 消费该接口，其余指数不开发适配层。
6. 短期/长期通道各自按收盘点相对下轨的位置着色；同日连接上下轨、跨日连接同名轨道，不填充区域、不绘制中轴。该规则只改变展示，不改变既有后端 `position/state` 契约。

以上六项是 LLD 和后续开发的硬约束，不再作为实现阶段的可选项。


## 3. 当前边界与实现缺口

- 独立 GET /api/v1/quote/detail/trend-channel，仅 000001.SH + day。共享 K 线 API/schema 不加通道字段。
- 完整历史先验证和计算，再按 end_date/limit 裁剪返回；递推不看未来，但完整历史中的坏行会使历史窗口查询也失败。
- 不新增配置、迁移、持久化结果、DatasetDefinition、TaskRun 或 Lake/DG 任务；股票日线 Lake 通道专项是独立范围。
- 页面已经调用本接口并绘制双通道。颜色比较 close 与 lower，不以带记忆的 state 着色；后台 position/state 合同仍保留。
- 聚合水位不是内容校验和，不能检测任意不改变水位的历史改写；专用缓存事件日志要求尚无 service 落点。这两项在 LLD 明确记录，不借本次文档治理改造代码。
- 已结案不等于每条旧草案承诺都已实现；也不因本次审计重新打开已确认的公式或生产验收。

## 4. 未来盘中临时通道（未实施）

### 4.1 启用前置条件

只有同时满足以下条件才可启用：

1. 存在经文档和真实请求验证的上证指数盘中 OHLC 来源。
2. 明确 `open/high/low/close` 的日累计语义和交易时间。
3. 有独立 feed key、源状态、批次时间和 stale 判定。
4. 能区分正式日线与盘中临时快照。
5. 已完成开盘、午休、下午盘、收盘后和非交易日验收。

### 4.2 O(1) 临时计算

令上一根正式日线状态为 `t-1`，当前盘中日累计 OHLC 为 `t*`：

```text
short_upper_t* = alpha_short * high_t* + (1 - alpha_short) * short_upper_(t-1)
short_lower_t* = alpha_short * low_t*  + (1 - alpha_short) * short_lower_(t-1)
long_upper_t*  = alpha_long  * high_t* + (1 - alpha_long)  * long_upper_(t-1)
long_lower_t*  = alpha_long  * low_t*  + (1 - alpha_long)  * long_lower_(t-1)
```

状态同样从上一根正式状态出发计算。

### 4.3 禁止盘中快照串联递推

09:31、09:32、09:33 的快照都必须独立使用同一个 `t-1` 正式状态作为基线：

```text
official(t-1) + current_snapshot(t*) -> provisional(t*)
```

禁止：

```text
provisional(09:31) -> provisional(09:32) -> provisional(09:33)
```

否则同一天被重复计入多次，结果会依赖刷新频率而不是日线公式。

### 4.4 收盘归并

正式日线落入 `index_daily_serving` 后：

1. 丢弃临时覆盖。
2. 由正式日线触发水位变化。
3. 按 v1 正式日线水位失效流程重算。
4. 返回 `is_provisional=false`。

盘中能力不在本轮开发范围内。

---


## 5. 何时重新评审物化

出现以下任一情况时停止扩大按需计算范围，重新评审是否物化：

1. 单序列超过 `10,000` 行。
2. 扩展到超过 50 个指数。
3. 扩展到超过 3 个周期。
4. 冷请求 P95 连续三次基准超过 `500ms`。
5. 该派生序列需要被三个以上独立下游批量复用。
6. 需要独立 freshness、审计、回溯版本或跨服务订阅。

达到门槛后另立“趋势通道物化数据集”方案，重新完成 DatasetDefinition、Lake、Dagster、表结构和生产验收设计；不得在本方案内顺手加表。

---


上述只有单序列 10000 行限制存在运行时代码门禁；指数数量、周期数、连续基准超标和下游数量属于扩大范围前的评审触发条件，不是当前自动监控或拒绝逻辑。未来临时通道 O(1) 计算 P95 <5ms 是候选阶段目标，不是 v1 验收项。
