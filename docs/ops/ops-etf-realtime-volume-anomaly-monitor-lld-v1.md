# ETF 实时成交额异动监控重构 LLD v1

状态：重新基线阻塞；当前不是编码依据
最近更新：2026-08-29
上位方案：[ETF 实时成交额异动监控重构方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-etf-realtime-volume-anomaly-monitor-plan-v1.md)

## 1. 当前实现必须保留

P8 不修改以下现有能力：

```text
ops.etf_realtime_monitor_pool
ops.etf_realtime_monitor_rule
ops.etf_realtime_alert
ops.etf_realtime_minute_stat
EtfRealtimeMonitorPoolService
EtfRealtimeMonitorRuleService
EtfRealtimeMonitorService
现有 API 与前端配置页
```

候选 API 已是 `/eligible-etfs`，运行时每批固定当前中国日期并只处理“enabled monitor pool ∩ Basic requestable codes”。该行为是现行基线，不是本文未来重构的待办。

独立 `EtfRealtimeMinuteArchiveService` 和手工归档 CLI 仍按其专门 LLD 的退场安排处理；P8 不维护、扩展或执行它。

## 2. 原 LLD 为什么失效

原 LLD 假定存在一个由旧激活池维护的 ETF 实时分钟 source 范围，并据此设计 Redis reader、窗口状态、表重建和页面候选。旧池基础设施已在 P8 删除，而 `etf_rt_min` 本身尚未实现，也没有新的范围合同。

因此原文件级修改清单、类名、schema、migration、配置和阶段顺序全部撤销。不能只把变量从 `active_*` 改名为 `eligible_*` 后继续开发；那会在没有业务拍板的情况下把 Basic 自动变成新的实时分钟 source 范围。

## 3. 可继承的技术原则

1. 实时采集、监控计算、告警提交和 Feishu 投递必须故障隔离。
2. 监控只读标准历史分钟，不写分钟事实或补数任务。
3. `rt_etf_k` 累计金额采样必须按交易窗口重置，采样中断后重建锚点。
4. 基准缺失或质量无效时 no-alert，不按 0。
5. 同一事件升级可以改变严重度，同级不得重复通知。
6. Ops 状态写入失败不得回滚或污染行情事实。

这些原则不足以直接编码，仍需新的数据合同、表结构和测试设计。

## 4. 新 LLD 必须回答

重新开工时必须从当前代码重新审计并明确：

1. 上游 final/valid 分钟 reader 的类型、批次、时间和质量字段。
2. 当前监控池是否继续作为唯一计算子集；与上游实时分钟覆盖范围如何求交。
3. `1/5/15` 窗口、上午开盘、午休、收盘和上一开市日基准的精确算法。
4. 现有 rule/alert/minute stat 是否能演进；若不能，逐表迁移和数据处置清单是什么。
5. Feishu delivery 是否需要独立表，以及提交/发送/回写顺序。
6. 每批读取量、Redis 状态量、历史查询量、运行耗时和限流预算。
7. API/前端契约、配置项治理、负向门禁与生产切换顺序。

## 5. 当前禁止动作

不新增或修改 monitor schema，不清理历史数据，不扩展归档 CLI，不实现实时分钟 reader，不改页面，不发 Tushare 请求。本文只有在上游范围重新拍板并完成新 CodeGraph 审计后，才能被完整替换为可执行 LLD。
