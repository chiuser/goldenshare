# `stk_mins` 本地股票池生命周期过滤方案 v1

- 状态：已落地
- 范围：仅 `lake_console` 本地 Parquet Lake 的 `stk_mins` 全市场同步与计划预估
- 事实源：`manifest/security_universe/tushare_stock_basic.parquet`
- 不涉及：生产 Ops、远程数据库、Postgres `stk_mins`、Parquet 存储结构、分页写入策略

---

## 1. 背景

`stk_mins` 源接口要求 `ts_code` 必填。`lake_console` 在全市场同步时，必须先从本地股票池文件读取股票代码，再对每个股票、每个 `freq`、每个请求窗口发起请求。

当前的问题是：全市场同步只看当前股票池，没有按本次同步区间过滤股票生命周期。

例如同步：

```bash
lake-console sync-stk-mins-range \
  --all-market \
  --freqs 1,5,15,30,60 \
  --start-date 2009-01-01 \
  --end-date 2019-12-31
```

如果某只股票在 `2020-01-01` 之后才上市，它不可能在 `2009-01-01 ~ 2019-12-31` 产生分钟线数据，不应该参与请求。继续请求这类股票会稳定浪费 Tushare 调用次数。

同时，历史区间里已经退市的股票也不能简单丢掉。只过滤 `list_status = L` 会漏掉历史区间内真实存在过的退市股票。

---

## 2. 本地审计结果

审计文件：

```text
/Volumes/datasource/goldenshare-tushare-lake/manifest/security_universe/tushare_stock_basic.parquet
```

审计日期：`2026-05-07`

| 项目 | 结果 |
|---|---:|
| 总行数 | 5837 |
| `ts_code` 去重数 | 5837 |
| `ts_code` 空值 | 0 |
| `list_status` 非法值 | 0 |
| `list_date` 缺失 | 0 |
| `list_date` 不可解析 | 0 |
| `delist_date` 不可解析 | 0 |
| `list_date > delist_date` | 0 |

状态分布：

| `list_status` | 行数 | `list_date` | `delist_date` |
|---|---:|---|---|
| `L` | 5512 | 全部有值 | 全部为空 |
| `D` | 325 | 全部有值 | 全部有值 |
| `P` | 0 | 无 | 无 |

日期范围：

| 字段 | 最小值 | 最大值 |
|---|---|---|
| `list_date` | 1990-12-01 | 2026-04-30 |
| `delist_date` | 1999-07-12 | 2026-04-27 |

以 `2009-01-01 ~ 2019-12-31` 为例，生命周期过滤后的请求股票池：

| 项目 | 数量 |
|---|---:|
| 当前股票池总数 | 5837 |
| 应参与请求 | 3810 |
| 因 `list_date > 2019-12-31` 跳过 | 1967 |
| 因 `delist_date < 2009-01-01` 跳过 | 60 |
| 保留的当前上市股票 | 3551 |
| 保留的历史退市股票 | 259 |

结论：当前本地 `stock_basic` manifest 支持生命周期过滤；后续实现不需要访问远程 `goldenshare-db`。

---

## 3. 目标与落地状态

本轮已新增本地股票池 helper，使 `stk_mins` 全市场同步只请求本次时间区间内可能产生数据的股票。

落地内容：

1. `sync-stk-mins-range --all-market` 已按生命周期过滤股票池。
2. `sync-stk-mins --all-market --trade-date` 已按单个交易日过滤股票池。
3. `plan-sync stk_mins` 已使用同一套过滤规则，保证计划预估与真实执行一致。
4. 对本地 `stock_basic` manifest 做质量校验，字段异常时 fail fast。
5. 输出过滤统计，让用户知道请求数量为什么减少。

---

## 4. 非目标

本方案不做以下事情：

1. 不修改 `stk_mins` Parquet 存储结构。
2. 不修改 `raw_tushare/stk_mins_by_date`、`derived`、`research` 的路径结构。
3. 不修改 Tushare 分页规则。
4. 不修改请求窗口算法。
5. 不访问远程数据库。
6. 不读取生产 `stock_basic` 表。
7. 不把本地 Lake 接入生产 Ops TaskRun。

---

## 5. 核心规则

### 5.1 股票生命周期

每只股票的生命周期定义为：

```text
security_lifecycle = [list_date, delist_date 或无限未来]
```

含义：

1. `list_date` 是股票上市日期。
2. `delist_date` 为空时，视为仍可交易或至少没有退市终点。
3. `delist_date` 有值时，该股票只在 `list_date ~ delist_date` 区间内可能有历史分钟线。

### 5.2 同步请求区间

`sync-stk-mins-range` 的请求区间定义为：

```text
request_range = [start_date, end_date]
```

`sync-stk-mins --all-market --trade-date` 的请求区间定义为：

```text
request_range = [trade_date, trade_date]
```

### 5.3 区间相交判定

股票参与请求的唯一条件：

```text
list_date <= request_end_date
and
(delist_date is null or delist_date >= request_start_date)
```

反例：

1. 股票 `2021-03-15` 上市，请求 `2009-01-01 ~ 2019-12-31`，不请求。
2. 股票 `2006-01-01` 上市、`2007-12-31` 退市，请求 `2009-01-01 ~ 2019-12-31`，不请求。
3. 股票 `2017-05-10` 上市，请求 `2009-01-01 ~ 2019-12-31`，请求。
4. 股票 `2006-01-01` 上市、`2012-06-01` 退市，请求 `2009-01-01 ~ 2019-12-31`，请求。

---

## 6. `stock_basic` 质量校验规则

因为本地 `stock_basic` 被定义为股票池事实源，所以缺失关键字段不应该静默兼容。

必须校验：

| 规则 | 失败处理 |
|---|---|
| `ts_code` 非空 | 停止执行 |
| `ts_code` 不重复 | 停止执行 |
| `list_status` 只能是 `L` / `D` / `P` | 停止执行 |
| 所有股票必须有 `list_date` | 停止执行 |
| `list_date` 必须可解析 | 停止执行 |
| `list_status = L` 时 `delist_date` 必须为空 | 停止执行 |
| `list_status in (D, P)` 时 `delist_date` 必须有值 | 停止执行 |
| 非空 `delist_date` 必须可解析 | 停止执行 |
| `list_date <= delist_date` | 停止执行 |

说明：

1. 当前本地审计结果已经满足上述规则。
2. 如果未来 `stock_basic` 源站返回异常数据，应先修复或重新同步 `stock_basic`，而不是让 `stk_mins` 带着不可信股票池继续跑。

---

## 7. Helper 设计

已新增 helper：

```text
lake_console/backend/app/services/security_universe_filter.py
```

职责：

1. 读取本地 `manifest/security_universe/tushare_stock_basic.parquet`。
2. 校验股票池质量。
3. 按请求区间过滤股票生命周期。
4. 返回过滤后的 `ts_code` 列表和统计信息。

核心对象：

```python
@dataclass(frozen=True)
class SecurityUniverseFilterResult:
    ts_codes: list[str]
    total_symbols: int
    selected_symbols: int
    skipped_listed_after_range: int
    skipped_delisted_before_range: int
    selected_listed_symbols: int
    selected_delisted_or_paused_symbols: int
```

核心函数：

```python
def load_security_universe_for_range(
    *,
    lake_root: Path,
    start_date: date,
    end_date: date,
) -> SecurityUniverseFilterResult:
    ...
```

单日全市场同步也使用同一个函数：

```python
load_security_universe_for_range(
    lake_root=lake_root,
    start_date=trade_date,
    end_date=trade_date,
)
```

---

## 8. 接入点

### 8.1 `sync-stk-mins-range`

当前接入点：

```text
lake_console/backend/app/services/tushare_stk_mins_sync_service.py
```

当前逻辑：

```text
_load_stock_universe_codes() -> 只读取 list_status = L
```

目标逻辑：

```text
load_security_universe_for_range(start_date, end_date)
```

同步摘要应增加：

```json
{
  "symbols_total": 5837,
  "symbols_selected": 3810,
  "symbols_skipped_listed_after_range": 1967,
  "symbols_skipped_delisted_before_range": 60,
  "symbols_selected_listed": 3551,
  "symbols_selected_delisted_or_paused": 259
}
```

进度输出建议增加启动行：

```text
[stk_mins_range] universe total=5837 selected=3810 skipped_future=1967 skipped_delisted_before=60
```

### 8.2 `sync-stk-mins --all-market --trade-date`

当前接入点：

```text
TushareStkMinsSyncService.sync_market_day(...)
```

目标逻辑：

```text
load_security_universe_for_range(trade_date, trade_date)
```

单日同步同样不能请求尚未上市或已经退市的股票。

### 8.3 `plan-sync stk_mins`

当前接入点：

```text
lake_console/backend/app/sync/planners/stk_mins.py
```

当前逻辑：

```text
_load_stock_universe_size() -> 只统计 list_status = L
```

目标逻辑：

```text
load_security_universe_for_range(start_date, end_date)
```

计划输出应同步增加股票池过滤统计，确保用户在发起大任务前就能看到请求数变化。

---

## 9. 验收样例

以 `2009-01-01 ~ 2019-12-31` 为例，`plan-sync stk_mins` 应展示：

```json
{
  "estimate": {
    "symbol_scope": "all_market",
    "symbol_count": 3810,
    "security_universe": {
      "total_symbols": 5837,
      "selected_symbols": 3810,
      "skipped_listed_after_range": 1967,
      "skipped_delisted_before_range": 60,
      "selected_listed_symbols": 3551,
      "selected_delisted_or_paused_symbols": 259
    }
  }
}
```

对于 `freq=1`，如果交易日窗口数为 `N`，请求数应按：

```text
3810 x N
```

而不是：

```text
5512 x N
```

---

## 10. 测试计划

新增或更新测试时，只覆盖 helper 与接入点行为，不触发真实 Tushare 请求。

建议测试：

1. `list_date > end_date` 的股票被排除。
2. `delist_date < start_date` 的股票被排除。
3. `list_date <= end_date` 且未退市的股票被保留。
4. 已退市但生命周期与请求区间相交的股票被保留。
5. `list_status = L` 且 `delist_date` 非空时失败。
6. `list_status in (D, P)` 且 `delist_date` 为空时失败。
7. `list_date` 缺失或不可解析时失败。
8. `plan-sync stk_mins` 和 `sync-stk-mins-range` 使用同一 helper，不允许各自实现一套过滤逻辑。

已验证的最小门禁：

```bash
lake_console/.venv/bin/python -m pytest \
  lake_console/backend/tests/test_security_universe_filter.py \
  lake_console/backend/tests/test_stk_mins_planner.py \
  lake_console/backend/tests/test_tushare_stk_mins_sync_service.py
```

当前已落地测试：

```text
lake_console/backend/tests/test_security_universe_filter.py
lake_console/backend/tests/test_stk_mins_planner.py
lake_console/backend/tests/test_tushare_stk_mins_sync_service.py
```

---

## 11. 实施记录

### M1：helper 与纯单元测试

状态：已完成。

1. 已新增 `security_universe_filter.py`。
2. 已新增股票池质量校验。
3. 已新增生命周期区间过滤。
4. 已使用临时 Parquet 测试文件验证各种边界。

### M2：`plan-sync stk_mins` 接入

状态：已完成。

1. 已删除 planner 内部的 `_load_stock_universe_size()` 私有过滤逻辑。
2. 已改为调用 helper。
3. 已输出过滤统计。
4. 已确认请求数按过滤后的股票数计算。

### M3：`sync-stk-mins-range` 接入

状态：已完成。

1. 已删除 service 内部只取 `list_status = L` 的过滤逻辑。
2. 已改为按 `start_date/end_date` 调用 helper。
3. 已输出过滤统计。
4. 请求窗口、分页、写入逻辑保持不变。

### M4：`sync-stk-mins --all-market --trade-date` 接入

状态：已完成。

1. 已使用单日区间调用 helper。
2. 已输出过滤统计。
3. 单日写入逻辑保持不变。

### M5：文档与回归

状态：已完成。

1. 已更新 `stk-mins-parquet-lake-plan-v1.md`。
2. 已更新命令示例说明。
3. 已跑 helper、planner、sync service 单元测试。
4. 已使用本地真实 Lake manifest 执行 `plan-sync stk_mins` 验证输出。

---

## 12. 风险与处理

| 风险 | 处理 |
|---|---|
| 本地 `stock_basic` 过旧 | 用户先执行 `lake-console sync-stock-basic` |
| 源站返回异常生命周期字段 | helper fail fast，不发起分钟线请求 |
| 请求数大幅下降导致用户怀疑漏数 | 输出过滤统计，说明跳过原因 |
| 历史退市股票被漏掉 | 不再只取 `list_status = L`，按生命周期相交保留 `D/P` |
| `plan-sync` 与真实执行口径漂移 | 二者必须共用同一个 helper |

---

## 13. 结论

这个改造属于低风险、高收益的本地 Lake 下载编排优化。

它不改变落盘结构，不改变分页，不改变派生和 research 层，只改变全市场分钟线任务的股票池选择逻辑。

推荐在继续执行长区间历史分钟线下载前先完成。
