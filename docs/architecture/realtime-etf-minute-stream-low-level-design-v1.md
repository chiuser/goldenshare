# ETF 实时分钟流 LLD v1

状态：重新基线阻塞；当前不是编码依据
最近更新：2026-08-29
上位方案：[ETF 实时分钟流接入方案 v1](/Users/congming/github/goldenshare/docs/architecture/realtime-etf-minute-stream-plan-v1.md)

## 1. 当前代码事实

仓库当前 realtime 对象只有股票日线、股票分钟和 ETF 实时日线。尚不存在：

```text
etf_rt_min runtime config
rt_etf_min provider / normalizer
per-frequency collector / scheduler
Redis feed keys / reader methods
ETF 实时分钟 Health
成员管理 API / 页面
```

因此旧文档中的类名、配置常量、Redis key、API、页面、seed 和测试清单都不是当前实现，也不能作为下一阶段白名单。

## 2. 可继承的技术证据

源请求参数、字段、五频率、组合通配符、闭合传播和候选调度数值，以 R0B 记录为事实。实现层仍需满足：

1. 一个 scheduler attempt 只发一次 HTTP 请求，transport retry 为 0，避免自动重试跨槽。
2. 多频率共同到期时顺序固定，一次 unified cycle 至多处理一个 due 频率，防止阻塞其他 realtime 对象。
3. lease、限速和 due state 必须非阻塞；不能在 collector 循环中 sleep 等待下一重试时点。
4. 一次响应中同一业务身份重复时整批失败，不能由 Redis 后写覆盖前写。
5. 部分代码仍停留旧分钟时不能发布为完整目标批次。
6. Redis current pointer 原子切换；发布后维护清理与事实提交隔离。

候选调度证据为 `+15/+30/+45s` 尝试、`+55s` 截止、8 秒 timeout、70 秒 lease、每槽最多 3 次、接口初始预算 20/min。这些数值在重新基线时仍需结合最终范围、统一 collector 公平性和配置审计重新验收。

## 3. 已失效的旧设计

以下设计因旧池退场全部作废：

1. 任何旧池 store contract、DAO 或 resource。
2. “从另一个 resource 选候选，再写入实时分钟 resource”的成员管理。
3. 以旧池数量计算 Redis snapshot、missing、Health 或容量。
4. 旧池 API、页面、seed 和 model registry 变更。
5. 空池时的生产行为、槽冻结 hash 和 batch meta 字段，因为“池”本身尚未重新定义。

P8 不用 Basic Serving 替换上述设计，也不增加兼容层。

## 4. 重新进入 LLD 前的审计清单

用户重新拍板范围后，必须从当前代码重新做 CodeGraph 和配置审计，至少覆盖：

```text
runtime_config / config_catalog / config seed
collector_service / realtime CLI handler
Tushare provider / HTTP retry / limiter
RedisRealtimeStateStore / lease / cleanup
RealtimeSnapshotReader
Ops config command/query / Health API
frontend config / monitor consumers
tests and systemd deployment
```

新的 LLD 必须给出：

1. 范围事实源与固定时点。
2. 源端全市场结果、就绪集合、Redis 保存集合三者的精确关系。
3. 每槽冻结、hash、batch meta 和 Health 合同。
4. 配置项来源、默认值、发布校验、所有消费者和生效方式。
5. Redis 真实容量报告及不可接受量级的停止策略。
6. 正向、负向、时序、限速、lease、发布原子性和失败隔离测试。

## 5. 当前允许做什么

当前只允许引用源端验证记录做后续讨论。不得新增代码、迁移、配置对象、Redis key、页面、生产请求或容量写入。下一次开发必须先用新方案替换本文，而不是在本文末尾追加补丁。
