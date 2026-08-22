# ETF 实时成交额异动监控 LLD v1

状态：本地实现完成 / 待部署验收
创建日期：2026-08-22
依据方案：[ETF 实时成交额异动监控方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-etf-realtime-volume-anomaly-monitor-plan-v1.md)

---

## 1. 本轮目标

把 ETF 实时成交额异动监控拆到可开发的代码级设计：

```text
etf_rt_daily Redis 批次
  -> 监控池与阈值规则
  -> 1m/5m/15m 成交额窗口计算
  -> observe/alert/strong 告警
  -> Feishu 通知
  -> 收盘后 1m 历史统计归档
  -> Ops ETF实时监控配置中心
```

V1 不是新增 Tushare 数据集，不进入 `DatasetDefinition`、TaskRun、freshness、date audit，也不引入 Doris。

---

## 2. 已审计代码事实

### 2.1 实时 ETF 主线

| 事实 | 当前代码 |
|---|---|
| ETF 实时 feed key | `tushare_etf_rt_k`，定义在 `src/foundation/realtime/config_catalog.py` |
| ETF 实时 collector | `src/foundation/realtime/etf_rt_daily.py` |
| Redis key 模型 | `src/foundation/realtime/redis_keys.py` |
| Redis store 公共契约 | `src/foundation/realtime/state_store.py` |
| Ops ETF health | `src/ops/queries/realtime_feed_health_query_service.py` |
| Ops realtime API | `src/ops/api/realtime.py` |
| 实时流监控页 | `frontend/src/pages/ops-realtime-monitor-page.tsx` |
| 实时流配置中心页 | `frontend/src/pages/ops-realtime-config-center-page.tsx` |

当前 Redis store 已支持：

1. 发布一个 batch。
2. 获取 current batch。
3. 获取 batch meta。
4. 获取指定 `ts_codes` 的 snapshots。
5. 获取 snapshot 数量。
6. 按 feed 列出最近 N 个 batch。
7. 按 batch 读取全部 snapshot。
8. 按 batch 读取 snapshot code 集合。

ETF 监控引擎必须继续通过 `RealtimeStateStore` 读取批次与 snapshot，禁止临时拼 Redis key。

### 2.2 ETF 活跃池与可选列表

| 事实 | 当前代码 |
|---|---|
| 活跃池表 | `ops.etf_series_active` |
| ORM | `src/ops/models/ops/etf_series_active.py` |
| 只读 API | `GET /api/v1/ops/review/etf/active` |
| 查询服务 | `src/ops/queries/review_center_query_service.py` |
| 前端页面 | `frontend/src/pages/ops-v21-review-etf-page.tsx` |

ETF 审查页已有能力：

1. `resource=fund_daily` / `resource=etf_rt_daily` 隔离。
2. keyword 搜索覆盖 `ts_code/csname/extname/cname`。
3. page/page_size 分页。
4. 列表可展示 ETF 基础信息与最新 `fund_daily` 日期。

ETF 监控配置中心可以复用相同查询口径，但不应直接长期依赖审查中心 API。建议新增监控域 API：

```http
GET /api/v1/ops/realtime/etf-monitor/active-etfs
```

它内部可复用查询逻辑或抽公共 query helper，但页面契约归属于 ETF 实时监控。

### 2.3 Feishu 能力

当前已有：

```text
src/ops/services/feishu_task_notification_service.py
```

它服务于 TaskRun 完成通知，配置项为：

1. `OPS_TASK_NOTIFY_FEISHU_ENABLED`
2. `GOLDENSHARE_FEISHU_WEBHOOK_URL`
3. `GOLDENSHARE_FEISHU_WEBHOOK_SECRET`
4. `OPS_TASK_NOTIFY_TIMEOUT_SECONDS`

ETF 异动告警不能直接复用 TaskRun 通知服务作为业务入口，因为两者的启停、消息模板、失败语义不同。V1 只复用签名、超时、错误解析经验，新增 ETF 告警发送服务。

ETF 告警 Feishu 通道已拍板为独立通道：

1. 新建 ETF 告警专用 Feishu 机器人。
2. webhook URL 使用 ETF 专用部署级 env。
3. secret 初始允许为空；为空时不签名。
4. 不复用 TaskRun 完成通知的启停开关和消息模板。

### 2.4 Alembic 迁移 head

本次审计时 `uv run alembic heads` 返回：

```text
20260818_000138 (head)
```

进入开发时必须重新确认真实 head，新迁移 `down_revision` 只能接当时真实 head，禁止按本文日期或印象猜。

### 2.5 CodeGraph 影响面

已用 CodeGraph 查过的关键影响面：

1. `RealtimeStateStore` 影响 Redis store、股票日线、股票分钟、ETF 日线、snapshot reader、Ops health、配置中心、相关测试。
2. `ReviewCenterQueryService` 当前覆盖 ETF 活跃池列表和 summary，可作为可选 ETF 查询口径参考。
3. `EtfRtDailyCollector` 只被统一 collector 和 ETF 实时测试引用；后续接监控引擎时必须保持 ETF feed 失败隔离。

---

## 3. 硬约束

1. 监控范围只能来自 `ops.etf_series_active(resource='etf_rt_daily')` 的子集。
2. `rt_etf_k` 源端 Redis 批次继续保存全市场事实，不能为了监控池裁剪源端 batch。
3. 监控计算与 Feishu 失败不能影响 ETF 实时采集、Redis 发布、业务数据表。
4. `foundation` 不允许 import `ops` ORM、Ops service 或 app 依赖。
5. 配置项必须集中审计；阈值、监控池进 DB；Feishu secret 留在部署 env。
6. 页面必须遵守运营后台现有设计规范，不能做成 showcase 或解释型 demo。
7. 所有状态写入失败只影响观测与告警自身，不允许回滚或污染实时源快照。
8. 初始监控池必须为空；不得在迁移或 seed 中默认导入全部 ETF。
9. 默认全局规则不得在迁移中自动 seed；只能由页面显式动作创建。

---

## 4. 数据表设计

V1 新增 4 张表，均在 `ops` schema。

### 4.1 `ops.etf_realtime_monitor_pool`

用途：实际监控名单。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | bigserial | pk | 主键 |
| `ts_code` | varchar(16) | unique, not null | ETF 代码 |
| `group_key` | varchar(64) | not null | 监控分组 |
| `group_name` | varchar(64) | not null | 分组展示名 |
| `enabled` | boolean | not null default true | 是否启用 |
| `display_order` | integer | not null default 0 | 展示排序 |
| `note` | text | nullable | 运营备注 |
| `created_by_user_id` | bigint | nullable | 创建人 |
| `updated_by_user_id` | bigint | nullable | 更新人 |
| `created_at` | timestamptz | not null | 创建时间 |
| `updated_at` | timestamptz | not null | 更新时间 |

索引：

```text
unique(ts_code)
index(group_key, enabled)
index(enabled, display_order)
```

服务层校验：

1. 新增或启用时，`ts_code` 必须存在于 `ops.etf_series_active(resource='etf_rt_daily')`。
2. 删除只删除监控关系，不删除历史告警和统计。

### 4.2 `ops.etf_realtime_monitor_rule`

用途：阈值规则。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | bigserial | pk | 主键 |
| `scope_type` | varchar(16) | not null | `global`、`group`、`etf` |
| `scope_key` | varchar(64) | not null | `__GLOBAL__`、分组 key 或 ETF 代码 |
| `window_minutes` | smallint | not null | `1`、`5`、`15` |
| `observe_ratio` | numeric(10,4) | not null | 观察倍数 |
| `alert_ratio` | numeric(10,4) | not null | 普通提醒倍数 |
| `strong_ratio` | numeric(10,4) | not null | 强提醒倍数 |
| `cooldown_minutes` | integer | not null | 冷却分钟 |
| `feishu_enabled` | boolean | not null | 是否发送 Feishu |
| `enabled` | boolean | not null | 是否启用 |
| `created_by_user_id` | bigint | nullable | 创建人 |
| `updated_by_user_id` | bigint | nullable | 更新人 |
| `created_at` | timestamptz | not null | 创建时间 |
| `updated_at` | timestamptz | not null | 更新时间 |

约束：

```text
unique(scope_type, scope_key, window_minutes)
check(scope_type in ('global', 'group', 'etf'))
check(window_minutes in (1, 5, 15))
check(observe_ratio > 0)
check(observe_ratio <= alert_ratio)
check(alert_ratio <= strong_ratio)
check(cooldown_minutes > 0)
```

服务层校验：

1. ETF 规则的 `scope_key` 必须存在于监控池。
2. group 规则的 `scope_key` 必须存在于监控池分组。
3. global 规则的 `scope_key` 固定为 `__GLOBAL__`。

### 4.3 `ops.etf_realtime_minute_stat`

用途：收盘后归档 1 分钟统计，供未来交易日做 5 个交易日历史同期基准。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `trade_date` | date | pk | 交易日 |
| `minute_bucket` | time | pk | 1 分钟桶结束时间 |
| `ts_code` | varchar(16) | pk | ETF 代码 |
| `source_trade_time` | timestamptz | nullable | 源端时间 |
| `source_batch_id` | varchar(64) | nullable | 当前批次 |
| `previous_batch_id` | varchar(64) | nullable | 上一分钟参考批次 |
| `cumulative_amount_yuan` | numeric(24,4) | nullable | 当前累计成交额，元 |
| `amount_delta_yuan` | numeric(24,4) | nullable | 本分钟成交额，元 |
| `cumulative_vol` | numeric(24,4) | nullable | 当前累计成交量 |
| `vol_delta` | numeric(24,4) | nullable | 本分钟成交量 |
| `data_quality` | varchar(16) | not null | `ok`、`missing`、`invalid` |
| `missing_reason` | varchar(128) | nullable | 缺失或无效原因 |
| `created_at` | timestamptz | not null | 创建时间 |

索引：

```text
index(ts_code, trade_date)
index(trade_date, minute_bucket)
index(data_quality, trade_date)
```

硬规则：

1. `missing` 要入库，不允许缺行伪装成 0。
2. 只存 1m，5m/15m 从 1m 聚合。
3. 重复归档同一天必须幂等。

### 4.4 `ops.etf_realtime_alert`

用途：保存 observe/alert/strong 异动记录与通知结果。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | bigserial | pk | 主键 |
| `trade_date` | date | not null | 交易日 |
| `triggered_at` | timestamptz | not null | 触发时间 |
| `bucket_end_time` | time | not null | 窗口结束时间 |
| `window_minutes` | smallint | not null | `1`、`5`、`15` |
| `ts_code` | varchar(16) | not null | ETF 代码 |
| `etf_name` | varchar(128) | nullable | ETF 名称快照 |
| `group_key` | varchar(64) | not null | 分组 key 快照 |
| `group_name` | varchar(64) | not null | 分组名快照 |
| `rule_id` | bigint | nullable | 命中规则 |
| `severity` | varchar(16) | not null | `observe`、`alert`、`strong` |
| `current_amount_yuan` | numeric(24,4) | not null | 当前窗口成交额 |
| `baseline_amount_yuan` | numeric(24,4) | not null | 历史同期均值 |
| `ratio` | numeric(12,4) | not null | 当前 / 基准 |
| `baseline_trade_dates_json` | jsonb | not null | 参与基准的交易日 |
| `cooldown_key` | varchar(256) | not null | 冷却键 |
| `feishu_status` | varchar(16) | not null | `skipped`、`pending`、`success`、`failed` |
| `feishu_message_id` | varchar(128) | nullable | Feishu 返回 ID |
| `feishu_error` | text | nullable | 失败摘要 |
| `notified_at` | timestamptz | nullable | 通知成功时间 |
| `created_at` | timestamptz | not null | 创建时间 |

索引：

```text
index(trade_date, ts_code, window_minutes)
index(triggered_at)
index(severity, triggered_at)
index(cooldown_key, triggered_at)
```

不设置 `(cooldown_key)` 唯一约束，因为同一冷却期允许 `alert` 升级到 `strong`。

---

## 5. 迁移与模型文件

### 5.1 迁移

新增迁移文件：

```text
alembic/versions/<next_revision>_add_etf_realtime_monitor_tables.py
```

规则：

1. 进入开发时先运行 `uv run alembic heads`。
2. `down_revision` 接真实 head。
3. 迁移只建表、索引、约束，不 seed 阈值，不写监控池，不清任何数据。

### 5.2 ORM

新增：

```text
src/ops/models/ops/etf_realtime_monitor_pool.py
src/ops/models/ops/etf_realtime_monitor_rule.py
src/ops/models/ops/etf_realtime_minute_stat.py
src/ops/models/ops/etf_realtime_alert.py
```

注册：

```text
src/ops/models/ops/__init__.py
src/app/model_registry.py
tests/web/conftest.py
```

---

## 6. Redis Store 扩展

### 6.1 新增公共方法

在 `src/foundation/realtime/state_store.py` 的 `RealtimeStateStore` Protocol 新增：

```python
def list_batch_ids(self, feed_key: str, *, limit: int | None = None) -> list[str]: ...

def get_batch_snapshot_codes(self, feed_key: str, batch_id: str) -> set[str]: ...

def get_batch_snapshots(
    self,
    feed_key: str,
    batch_id: str,
    *,
    ts_codes: Sequence[str] | None = None,
) -> dict[str, dict[str, Any]]: ...
```

实现范围：

1. `RedisRealtimeStateStore`
2. `InMemoryRealtimeStateStore`
3. `UnavailableRealtimeStateStore`

实现口径：

1. `list_batch_ids` 按 Redis zset 分数倒序返回最近批次。
2. `get_batch_snapshot_codes` 读取 batch index。
3. `get_batch_snapshots` 若传 `ts_codes`，走现有 mget；不传则先读 index 再批量读取。

### 6.2 为什么必须扩展 store

ETF 监控需要读取当天多个 batch 做分钟差分。当前 `get_snapshots(feed_key,batch_id,ts_codes)` 只能服务“业务方查几只代码的当前快照”，无法支持：

1. 收盘后遍历全天 260 批。
2. 计算上一分钟与当前分钟的累计成交额差值。
3. 对缺采进行 `missing` 标记。

禁止在服务里直接拼 Redis key，因为这会绕过 `RealtimeStateStore` 抽象，破坏后续 InMemory 测试和 Redis key 统一治理。

---

## 7. 计算模型

### 7.1 Foundation 纯计算层

新增：

```text
src/foundation/realtime/etf_volume_metrics.py
```

职责：

1. 读取 `RealtimeStateStore` 中指定 feed 的 batch 与 snapshot。
2. 从 `rt_etf_k.amount` 计算 `amount_delta_yuan`。
3. 生成 1m 统计行。
4. 从 1m 统计聚合 5m/15m 窗口。
5. 输出数据质量：`ok`、`missing`、`invalid`。

禁止：

1. import `src.ops`。
2. 查询监控池、阈值或 Feishu。
3. 写数据库。

建议类型：

```python
@dataclass(frozen=True, slots=True)
class EtfMinuteMetric:
    trade_date: date
    minute_bucket: time
    ts_code: str
    source_trade_time: datetime | None
    source_batch_id: str | None
    previous_batch_id: str | None
    cumulative_amount_yuan: Decimal | None
    amount_delta_yuan: Decimal | None
    cumulative_vol: Decimal | None
    vol_delta: Decimal | None
    data_quality: str
    missing_reason: str | None
```

### 7.2 时间桶

交易时段固定来自实时 ETF feed 的 collection sessions：

```text
09:30-11:30
13:00-15:00
```

桶口径：

| 窗口 | 桶结束示例 |
|---|---|
| 1m | `09:31`、`09:32` |
| 5m | `09:35`、`09:40` |
| 15m | `09:45`、`10:00` |

规则：

1. 午休不跨桶。
2. `11:30` 是上午最后一个闭合桶。
3. `13:00` 下午重新开始，不和上午合并。
4. 未闭合窗口不参与告警。

### 7.3 missing 与 invalid

以下情况标记 `missing`：

1. 当前桶没有可用 batch。
2. 监控池 ETF 在当前 batch 没有 snapshot。
3. 当前 snapshot 的 `trade_time` 不属于当前分钟桶。
4. 上一分钟参考 snapshot 缺失，无法做差分。

以下情况标记 `invalid`：

1. `amount` 无法解析为数字。
2. `vol` 无法解析为数字。
3. 当前累计成交额小于上一分钟累计成交额。
4. `ts_code` 缺失或不匹配。

`missing` 和 `invalid` 都不能当 0。

### 7.4 基准计算

基准来源：

```text
ops.etf_realtime_minute_stat
```

口径：

1. 最近 5 个交易日。
2. 同 ETF。
3. 同窗口。
4. 同时间桶。
5. 只使用 `data_quality='ok'` 的 1m 统计。
6. 至少 3 个交易日可用才计算。

5m/15m 基准按每个历史交易日先聚合，再对 5 个交易日取平均值。

---

## 8. Ops 服务

### 8.1 监控池服务

新增：

```text
src/ops/services/etf_realtime_monitor_pool_service.py
```

职责：

1. 查询可选 ETF：只从 `ops.etf_series_active(resource='etf_rt_daily')` + `core_serving.etf_basic`。
2. 维护监控池 CRUD。
3. 校验 `ts_code` 在 `etf_rt_daily` 活跃池内。
4. 提供 50/page 分页与 keyword 搜索。

### 8.2 阈值规则服务

新增：

```text
src/ops/services/etf_realtime_monitor_rule_service.py
```

职责：

1. 维护规则 CRUD。
2. 校验 scope/window/ratio/cooldown。
3. 提供规则解析：

```text
ETF 专属 > 分组 > 全局
```

4. 规则读取使用 60 秒短缓存。

缓存说明：

1. 缓存只缓存规则读取结果。
2. 写规则后清当前进程缓存。
3. 多进程最多 60 秒内生效。
4. 该 TTL 是 V1 受控默认，若要运营可编辑，必须另进配置中心。

### 8.3 监控引擎

新增：

```text
src/ops/services/etf_realtime_monitor_service.py
```

职责：

1. 读取启用监控池。
2. 调用 `foundation.realtime.etf_volume_metrics` 获取当前闭合窗口指标。
3. 查询最近 5 个交易日历史基准。
4. 命中阈值后写 `ops.etf_realtime_alert`。
5. 执行冷却与升级判断。
6. 调用 Feishu 发送器。

运行方式：

1. V1 推荐挂在现有 `goldenshare-realtime-collector.service` 内。
2. ETF batch 发布成功后，触发一次监控计算。
3. 监控计算必须包在独立 try/except 中。
4. 监控失败只记录日志或自身状态，不影响下一次 ETF batch 发布。

### 8.4 收盘归档服务

新增：

```text
src/ops/services/etf_realtime_minute_archive_service.py
```

职责：

1. 收盘后读取当天 Redis batch。
2. 对监控池 ETF 生成全天 1m 统计。
3. upsert 到 `ops.etf_realtime_minute_stat`。
4. 重复执行同一天幂等。

建议 CLI：

```text
goldenshare ops-archive-etf-realtime-minute-stats --trade-date YYYY-MM-DD
```

V1 可以先手工执行或接现有 Ops schedule；不要进入 Dataset TaskRun。

### 8.5 Feishu 告警发送器

新增：

```text
src/ops/services/etf_realtime_feishu_alert_service.py
```

配置：

1. 读取 ETF 告警专用部署级 `ETF_REALTIME_ALERT_FEISHU_WEBHOOK_URL`。
2. 读取 ETF 告警专用部署级 `ETF_REALTIME_ALERT_FEISHU_WEBHOOK_SECRET`，允许为空。
3. secret 为空时不生成 Feishu 签名；secret 非空时按当前 Feishu 签名算法发送。
4. 超时可复用 `OPS_TASK_NOTIFY_TIMEOUT_SECONDS`，但 ETF 告警是否启用由规则表的 `feishu_enabled` 决定。

行为：

1. `observe` 不发送，直接 `feishu_status='skipped'`。
2. `alert/strong` 先写 alert，再发送。
3. 发送失败回写 `failed` 和错误摘要，不抛出影响主循环。
4. V1 只即时发送一次，不做后台重试队列。

---

## 9. API 设计

建议新增独立模块：

```text
src/ops/api/etf_realtime_monitor.py
```

并在：

```text
src/ops/api/router.py
```

注册。不要继续把所有 realtime 子能力堆到 `src/ops/api/realtime.py`。

### 9.1 可选 ETF

```http
GET /api/v1/ops/realtime/etf-monitor/active-etfs?keyword=沪深300&page=1&page_size=50
```

返回字段：

```json
{
  "items": [
    {
      "ts_code": "510300.SH",
      "csname": "沪深300ETF",
      "extname": "华泰柏瑞沪深300ETF",
      "exchange": "SH",
      "fund_type": "股票型",
      "list_date": "2012-05-28",
      "list_status": "L",
      "latest_fund_daily_date": "2026-08-21",
      "in_monitor_pool": true
    }
  ],
  "page": 1,
  "page_size": 50,
  "total": 1395
}
```

### 9.2 监控池

```http
GET /api/v1/ops/realtime/etf-monitor/pool?page=1&page_size=50&keyword=&enabled=true
POST /api/v1/ops/realtime/etf-monitor/pool
PUT /api/v1/ops/realtime/etf-monitor/pool/{id}
DELETE /api/v1/ops/realtime/etf-monitor/pool/{id}
```

新增请求：

```json
{
  "ts_code": "510300.SH",
  "group_key": "broad_base",
  "group_name": "宽基ETF",
  "enabled": true,
  "display_order": 10,
  "note": "沪深300代表ETF"
}
```

### 9.3 阈值规则

```http
GET /api/v1/ops/realtime/etf-monitor/rules?scope_type=etf&window_minutes=5
POST /api/v1/ops/realtime/etf-monitor/rules
PUT /api/v1/ops/realtime/etf-monitor/rules/{id}
DELETE /api/v1/ops/realtime/etf-monitor/rules/{id}
```

### 9.4 告警记录

```http
GET /api/v1/ops/realtime/etf-monitor/alerts?trade_date=2026-08-22&severity=alert&page=1&page_size=50
GET /api/v1/ops/realtime/etf-monitor/alerts/{id}
```

### 9.5 汇总

```http
GET /api/v1/ops/realtime/etf-monitor/summary?trade_date=2026-08-22
```

建议返回：

1. 监控 ETF 总数。
2. 启用监控 ETF 数。
3. 今日 observe/alert/strong 数。
4. Feishu 成功/失败数。
5. 最近归档日期。

---

## 10. 前端 LLD

### 10.1 路由与菜单

新增页面：

```text
frontend/src/pages/ops-etf-realtime-monitor-config-page.tsx
```

路由：

```text
/ops/v21/realtime/etf-monitor
```

菜单位置：

```text
实时流监控
  实时流配置中心
  ETF实时监控配置中心
```

修改文件：

```text
frontend/src/app/router.tsx
frontend/src/app/shell.tsx
```

### 10.2 API 类型

新增：

```text
frontend/src/shared/api/etf-realtime-monitor-types.ts
```

只放 API contract 类型，不放页面展示函数或文案。

### 10.3 页面结构

页面必须使用现有运营后台组件：

1. `PageHeader`
2. `SectionCard`
3. `StatCard`
4. `FilterBar`
5. `TableShell`
6. `OpsTable`
7. `EmptyState`
8. Mantine `Drawer`、`Badge`、`Alert`

Tab 结构：

```text
监控池
阈值规则
告警记录
```

禁止：

1. 大面积说明段落。
2. showcase 风格的 hero 区。
3. 只读信息和编辑校验混在同一区块。
4. 页面内直连 Redis、Tushare 或业务行情 API。

### 10.4 监控池交互

初始状态：

1. 监控池初始为空。
2. 页面空态提示运营从激活 ETF 列表中添加。
3. 不提供自动导入全部活跃 ETF。

主表：

| 列 | 说明 |
|---|---|
| ETF 代码 | `ts_code` |
| 名称 | `csname/extname/cname` 优先级由后端确定 |
| 分组 | `group_name` 标签 |
| 状态 | 启用/停用 |
| 阈值覆盖 | 是否存在 ETF 专属规则 |
| 最近告警 | 最近一条 alert/strong |
| 操作 | 编辑、停用、删除 |

新增 ETF：

1. 点击“添加 ETF”打开抽屉。
2. 抽屉内请求 `/active-etfs`。
3. 每页 50 条。
4. 支持关键词搜索。
5. 已在监控池中的 ETF 显示“已加入”，不可重复添加。
6. 选择后填写分组、排序、备注。

### 10.5 阈值规则交互

默认规则：

1. 初始不自动创建全局规则。
2. 页面提供“创建默认全局规则”显式动作。
3. 点击后创建 1m/5m/15m 三条 global 规则，默认值为 `observe=2.0`、`alert=3.0`、`strong=5.0`、`cooldown_minutes=15`。

规则表：

| 列 | 说明 |
|---|---|
| 生效层级 | 全局 / 分组 / ETF |
| 对象 | 分组名或 ETF 代码名称 |
| 窗口 | `1m/5m/15m` 标签 |
| observe | 倍数 |
| alert | 倍数 |
| strong | 倍数 |
| 冷却 | 分钟 |
| Feishu | 启用/关闭 |
| 状态 | 启用/停用 |

编辑：

1. 使用抽屉。
2. `window_minutes` 用单选或下拉，不允许手填。
3. 倍数用数字输入。
4. 阈值顺序错误时前端可即时提示，但后端仍必须校验。

### 10.6 告警记录交互

只读查询。

筛选：

1. 交易日。
2. ETF 关键词。
3. 告警等级。
4. Feishu 状态。

表格：

| 列 | 说明 |
|---|---|
| 时间 | `triggered_at` |
| ETF | 代码 + 名称 |
| 窗口 | `1m/5m/15m` |
| 当前成交额 | 展示可格式化为“亿”，字段语义仍是元 |
| 历史基准 | 最近 5 交易日同期均值 |
| 倍数 | `ratio` |
| 等级 | observe/alert/strong |
| 通知 | skipped/pending/success/failed |

详情抽屉展示：

1. 基准交易日样本。
2. 命中规则。
3. 冷却键。
4. Feishu 错误摘要。

---

## 11. 运行时流程

### 11.1 盘中告警

```text
EtfRtDailyCollector 发布 Redis batch
  -> EtfRealtimeMonitorService.run_after_etf_batch()
  -> 读取启用监控池
  -> 读取规则缓存
  -> foundation.etf_volume_metrics 计算已闭合窗口
  -> 查询最近 5 个交易日基准
  -> 判断 observe/alert/strong
  -> 写 ops.etf_realtime_alert
  -> alert/strong 调 Feishu
  -> 回写 Feishu 结果
```

失败隔离：

1. Redis batch 已发布后，监控引擎失败不能回滚 batch。
2. Feishu 失败不能回滚 alert。
3. 单只 ETF 计算失败不能阻塞其他 ETF。

### 11.2 收盘归档

```text
ops-archive-etf-realtime-minute-stats
  -> 读取当天 Redis batch ids
  -> 读取监控池
  -> 生成 1m metric
  -> upsert ops.etf_realtime_minute_stat
  -> 输出归档摘要
```

归档只写 `ops.etf_realtime_minute_stat`，不写 raw/core/serving。

---

## 12. 配置审计

| 配置 | 默认值 | 来源 | 持久化 | 消费者 | 生效 |
|---|---:|---|---|---|---|
| `etf_rt_daily.keep_recent_batches` | `260` | 实时流配置中心 | `foundation.realtime_runtime_config` | collector / Redis store | 发布后重启 collector |
| 监控池 | 空 | Ops 页面 | `ops.etf_realtime_monitor_pool` | monitor service / archive service / 页面 | DB 短缓存，最多 60 秒 |
| 阈值规则 | 见方案默认 | Ops 页面 | `ops.etf_realtime_monitor_rule` | monitor service / 页面 | DB 短缓存，最多 60 秒 |
| 规则缓存 TTL | `60s` | V1 代码受控默认 | 无 | rule service | 进程内生效 |
| ETF Feishu webhook URL | 空 | 部署 env | `/etc/goldenshare/web.env` | ETF Feishu sender | 重启 Web/worker |
| ETF Feishu webhook secret | 空 | 部署 env | `/etc/goldenshare/web.env` | ETF Feishu sender；为空则不签名 | 重启 Web/worker |
| Feishu timeout | `5s` | Settings | `/etc/goldenshare/web.env` | ETF Feishu sender | 重启 Web/worker |

如果后续要让规则缓存 TTL 或 Feishu 开关进入页面配置，必须新增配置中心设计，不能临时加 env 或页面常量。

---

## 13. 测试计划

### 13.1 后端

新增测试建议：

```text
tests/test_etf_realtime_monitor_models.py
tests/test_etf_realtime_volume_metrics.py
tests/test_etf_realtime_monitor_pool_service.py
tests/test_etf_realtime_monitor_rule_service.py
tests/test_etf_realtime_monitor_service.py
tests/test_etf_realtime_minute_archive_service.py
tests/web/test_ops_etf_realtime_monitor_api.py
```

必须覆盖：

1. 迁移 head 与 4 表字段。
2. 监控池只能选择 `etf_rt_daily` 活跃池内 ETF。
3. `/active-etfs` 每页 50 条、keyword 搜索。
4. 阈值优先级 ETF > group > global。
5. 阈值递增校验。
6. Redis batch 不足时 `missing`，不当作 0。
7. 午休不跨窗口。
8. 最近 5 个交易日同桶基准，少于 3 个样本不告警。
9. observe 入库不发 Feishu。
10. alert/strong 冷却与升级。
11. Feishu 失败不影响 alert 记录。
12. 收盘归档幂等。

### 13.2 前端

新增：

```text
frontend/src/pages/ops-etf-realtime-monitor-config-page.test.tsx
```

必须覆盖：

1. 菜单和路由。
2. 三个 Tab：监控池、阈值规则、告警记录。
3. 监控池新增抽屉使用 active ETF API，默认 50/page。
4. 阈值规则编辑使用受控输入，不手填窗口枚举。
5. 告警记录展示等级、倍数、Feishu 状态。
6. API 失败只影响当前区块。
7. 页面不调用 health API、Biz realtime API、Tushare、Redis。

### 13.3 回归

建议命令：

```bash
uv run pytest -q tests/test_etf_realtime_volume_metrics.py tests/web/test_ops_etf_realtime_monitor_api.py
uv run pytest -q tests/test_realtime_etf_rt_daily.py tests/test_realtime_state_store.py tests/web/test_realtime_api.py
uv run pytest -q tests/architecture/test_subsystem_dependency_matrix.py tests/architecture/test_platform_legacy_guardrails.py tests/architecture/test_operations_legacy_guardrails.py
cd frontend && npm run typecheck
cd frontend && npm run test -- ops-etf-realtime-monitor-config-page
python3 scripts/check_docs_integrity.py
```

---

## 14. 开发里程碑

| Milestone | 目标 | 边界 |
|---|---|---|
| M0 | 方案与 LLD 评审冻结 | 只改文档 |
| M1 | 建表、ORM、迁移 | 不 seed、不跑生产 |
| M2 | Redis store 扩展与 foundation 指标计算 | 不写 Ops 表、不发通知 |
| M3 | 监控池 API + 页面 | 只做监控池 |
| M4 | 阈值规则 API + 页面 | 只做规则 |
| M5 | 告警计算服务 | 写 alert，Feishu 可 mock |
| M6 | Feishu 发送闭环 | 非阻塞发送与状态回写 |
| M7 | 收盘归档 | 写 1m stat，幂等 |
| M8 | 告警记录页与生产验收 | 盘中验证、Redis 容量、Feishu 验证 |

---

## 15. 已拍板口径

| 编号 | 事项 | 已确认口径 |
|---|---|---|
| D1 | 默认阈值 | `observe=2.0`，`alert=3.0`，`strong=5.0` |
| D2 | 默认冷却期 | `15` 分钟 |
| D3 | 监控池初始名单 | 初始监控池为空；功能完成后由运营在页面手工选择 |
| D4 | Feishu 通道 | 新建 ETF 告警专用 Feishu 通道；webhook URL 放部署 env，secret 允许先留空 |
| D5 | 收盘归档触发方式 | 先提供 CLI，再接 Ops schedule |
| D6 | 监控引擎运行位置 | 放在现有 `goldenshare-realtime-collector.service` 内，ETF batch 发布成功后触发 |
| D7 | 默认全局规则创建 | 不在迁移中自动 seed；页面提供显式“创建默认全局规则”动作 |
| D8 | 监控分组 | V1 先受控为 `宽基ETF`、`主题ETF` 两类 |
| D9 | Redis Store 扩展 | 必须扩展 `RealtimeStateStore`，禁止服务层临时拼 Redis key |
| D10 | Feishu 失败重试 | V1 不做后台重试队列；即时发送一次，失败入库 |

---

## 16. 当前不做

1. 不引入 Doris。
2. 不新增业务侧 ETF 异动 API。
3. 不接普通用户页面。
4. 不改 `rt_etf_k` 请求范围。
5. 不改 ETF 活跃池表。
6. 不把 Feishu secret 写入 DB。
7. 不把监控池和实时流配置中心混在一个页面。
