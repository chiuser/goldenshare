# 股票历史分钟行情请求策略优化方案 v1

状态：已落地  
数据集：`stk_mins`  
源文档：`docs/sources/tushare/股票数据/行情数据/0370_股票历史分钟行情.md`  
本方案只处理请求策略，不处理落盘、事务提交、流式写入。

---

## 1. 背景

`stk_mins` 已接入 Sync V2，但当前请求规划方式过细：

```text
交易日
  -> 股票代码
    -> freq
      -> 上午/下午时段
```

线上执行全市场历史分钟同步时，任务规划出数百万个 unit，跑了一晚仍只完成很小一部分。这个问题的核心不是数据库落盘慢，而是请求策略本身不合理。

本方案先单独解决“请求怎么发最快”的问题。

---

## 2. 上游接口事实

来自源文档：

| 项 | 内容 |
|---|---|
| 接口 | `stk_mins` |
| 描述 | 获取 A 股分钟数据，支持 `1min/5min/15min/30min/60min` |
| 单次上限 | `8000` 行 |
| 必选参数 | `ts_code`, `freq` |
| 时间参数 | `start_date`, `end_date`，格式为 datetime |
| 分页参数 | `limit`, `offset` |
| 文档口径 | 可以通过股票代码和时间循环获取 |

关键结论：

1. `ts_code` 必须传，因此全市场只能按证券代码扇出。
2. `freq` 必须传，因此 5 个频度必须分别请求。
3. `start_date/end_date` 是 datetime，可以覆盖一个较长时间窗口。
4. 接口支持 `limit/offset`，所以大窗口内的数据应通过分页取完。
5. 文档没有要求按交易日拆，也没有要求按上午/下午拆。

---

## 3. 当前实现问题

### 3.1 当前请求维度

当前策略文件 `src/foundation/services/sync_v2/dataset_strategies/stk_mins.py` 的规划维度是：

```text
trade_date x ts_code x freq x trading_session
```

交易时段固定拆成：

```text
morning:   09:30:00 ~ 11:30:00
afternoon: 13:00:00 ~ 15:00:00
```

### 3.2 为什么慢

如果全市场约 `5000` 只股票，选择 5 个频度，同步 1 个交易日：

```text
5000 股票 x 5 freq x 2 session = 50000 次请求
```

如果同步 2500 个交易日：

```text
50000 次/日 x 2500 日 = 125,000,000 次请求
```

这不是实现效率问题，而是请求粒度错误。

### 3.3 当前方式的额外问题

1. unit 数量极大，任务进度很慢。
2. 每个 unit 数据量很小，网络请求开销占比过高。
3. 失败重跑成本高，因为重跑仍要重新走海量 unit。
4. 用户看不到明显推进，体验很差。

---

## 4. 目标请求策略

### 4.1 核心原则

`stk_mins` 应按以下维度规划请求：

```text
股票代码 ts_code
  -> 频度 freq
    -> 时间大窗口
      -> limit/offset 分页
```

不再默认按交易日拆分，不再默认拆上午/下午。

### 4.2 单只股票单频度请求示例

```text
api_name = stk_mins
ts_code = 000001.SZ
freq = 1min
start_date = 2010-01-01 09:00:00
end_date = 2026-04-24 19:00:00
limit = 8000
offset = 0
```

若返回 `8000` 行，则继续：

```text
offset = 8000
offset = 16000
offset = 24000
...
```

直到返回行数 `< 8000`。

### 4.3 全市场全频度请求维度

当用户不传 `ts_code`，且选择：

```text
freq = 1min,5min,15min,30min,60min
start_date = 2010-01-01
end_date = 2026-04-24
```

系统应规划为：

```text
for ts_code in stock_pool:
    for freq in selected_freqs:
        request stk_mins(ts_code, freq, start_datetime, end_datetime)
        paginate by limit=8000, offset += 8000
```

---

## 5. 请求量估算

### 5.1 单只股票日内行数估算

以 A 股日内约 `240` 个 1 分钟 bar 粗略估算：

| freq | 每交易日行数 |
|---|---:|
| `1min` | 约 240 |
| `5min` | 约 48 |
| `15min` | 约 16 |
| `30min` | 约 8 |
| `60min` | 约 4 |

### 5.2 单只股票 10 年请求数估算

按 `2500` 个交易日估算：

| freq | 行数估算 | 请求数估算 |
|---|---:|---:|
| `1min` | 600000 | 约 75 |
| `5min` | 120000 | 约 15 |
| `15min` | 40000 | 约 5 |
| `30min` | 20000 | 约 3 |
| `60min` | 10000 | 约 2 |

单只股票 5 个频度合计约 `100` 次请求。

全市场 `5000` 只股票，约：

```text
5000 x 100 = 500000 次请求
```

这仍然很大，但比当前按日/session 拆出的上亿次请求低两个数量级以上。

---

## 6. 时间窗口口径

### 6.1 用户输入仍保持交易日

用户侧仍然只选择：

```text
trade_date
或
start_date / end_date
```

不暴露小时、分钟、秒。

### 6.2 程序内部转换为 datetime

单日：

```text
trade_date = 2026-04-24
start_datetime = 2026-04-24 09:00:00
end_datetime = 2026-04-24 19:00:00
```

区间：

```text
start_date = 2026-04-01
end_date = 2026-04-24
start_datetime = 2026-04-01 09:00:00
end_datetime = 2026-04-24 19:00:00
```

说明：

1. 使用 `09:00:00 ~ 19:00:00` 是为了覆盖全部可能返回区间。
2. 不需要拆上午/下午。
3. 不需要按交易日逐日拆。
4. 返回数据中的真实 `trade_time` 决定最终落库时间。

### 6.3 是否过滤非交易日

对 `stk_mins` 来说，请求参数是 datetime 范围，不是 `trade_date` 点。

建议：

1. 单日执行时，用户选择的日期仍应限制为交易日。
2. 区间执行时，不需要把区间拆成交易日列表。
3. 只需用用户选择的起止交易日生成一个连续 datetime 窗口。

---

## 7. 全量与增量策略

### 7.1 历史回补

历史回补应使用“大窗口分页”：

```text
ts_code x freq x [start_datetime, end_datetime] x offset分页
```

不按交易日拆。

### 7.2 单日增量

单日增量仍可走同一策略，只是时间窗口为一天：

```text
ts_code x freq x [trade_date 09:00:00, trade_date 19:00:00]
```

此时一般不会触发深分页。

### 7.3 多频度执行顺序

建议执行顺序固定为：

```text
1min -> 5min -> 15min -> 30min -> 60min
```

理由：

1. `1min` 最大、最慢，优先暴露权限/分页/异常问题。
2. 后续频度更小，失败概率和耗时更低。
3. 进度展示更可预期。

如后续需要运营体验更好，也可以改为：

```text
60min -> 30min -> 15min -> 5min -> 1min
```

这样能更快看到部分频度完成。但第一版建议保持 `1min` 优先，便于压力验证。

---

## 8. 目标 PlanUnit 设计

### 8.1 当前 PlanUnit

当前一个 unit 表示：

```text
一个交易日 + 一只股票 + 一个 freq + 一个 session
```

### 8.2 目标 PlanUnit

优化后一个 unit 表示：

```text
一只股票 + 一个 freq + 一个 datetime 窗口
```

字段口径：

| 字段 | 目标值 |
|---|---|
| `unit_id` | `stk_mins:{ts_code}:{freq}:{start_datetime}:{end_datetime}` |
| `trade_date` | 单日任务填单日；区间任务可填 `end_date` 或空，实际行由 `trade_time` 派生 |
| `request_params.ts_code` | 当前股票代码 |
| `request_params.freq` | 当前频度 |
| `request_params.start_date` | `YYYY-MM-DD 09:00:00` |
| `request_params.end_date` | `YYYY-MM-DD 19:00:00` |
| `pagination_policy` | `offset_limit` |
| `page_limit` | `8000` |

### 8.3 进度游标元信息

为了让 Ops 页面能看清“当前执行到哪个股票”，`stk_mins` 的 unit 需要携带可展示的当前处理对象信息。

建议在 `PlanUnit.progress_context` 中保留以下元信息；`request_params` 只保留上游接口真实支持的请求参数：

| 字段 | 含义 | 是否传给上游 |
|---|---|---|
| `ts_code` | 当前股票代码 | 是 |
| `security_name` | 当前股票名称 | 否，仅用于进度展示 |
| `freq` | 当前频度 | 是 |
| `start_date` | 当前请求窗口开始时间 | 是 |
| `end_date` | 当前请求窗口结束时间 | 是 |

注意：

1. `security_name` 来自 `core_serving.security_serving.name`。
2. `security_name` 不能传给 Tushare，必须放在 `progress_context`，不能放入 `request_params`。
3. 若股票名称为空，进度展示降级为只展示 `ts_code`。

### 8.4 unit 数量变化

假设：

```text
5000 股票
5 freq
1 个时间窗口
```

unit 数量为：

```text
5000 x 5 = 25000
```

分页请求数量由每个 unit 内部 offset 决定。

而当前方式如果 2500 个交易日：

```text
5000 x 5 x 2500 x 2 = 125000000 unit
```

优化后 unit 数量会显著下降。

---

## 9. 信息上报与页面展示方案

### 9.1 当前进度上报现状

当前 Sync V2 进度链路为：

```text
SyncV2Engine
  -> SyncV2Observer.report_progress
  -> SyncV2Service.progress_reporter
  -> JobExecutionSyncContext.update_progress
  -> ops.job_execution.progress_*
  -> Ops Execution Detail API
  -> 前端任务详情页
```

当前 `progress_message` 示例：

```text
stk_mins: 115327/4257360 fetched=3470001 written=3470001 rejected=0
```

问题：

1. 只能看到 unit 序号，看不到当前股票。
2. `fetched/written` 是全任务累计值，不是当前股票的行数。
3. 前端虽然能解析 `ts_code`，但后端目前没有把 `ts_code/security_name/freq` 稳定写入进度消息。

### 9.2 通用进度游标模型

这套机制应设计为通用模型，不只服务 `stk_mins`。

建议把进度消息拆成两类语义：

1. 全任务累计统计。
2. 当前处理对象游标。

通用 token 规范：

| token | 含义 | 示例 |
|---|---|---|
| `unit` | 当前处理对象类型 | `stock` / `trade_date` / `board` / `index` / `code` |
| `ts_code` | 当前证券代码 | `000001.SZ` |
| `security_name` | 当前证券名称 | `平安银行` |
| `freq` | 当前频度 | `1min` |
| `trade_date` | 当前交易日 | `2026-04-23` |
| `start_date` | 当前窗口开始 | `2026-04-01 09:00:00` |
| `end_date` | 当前窗口结束 | `2026-04-24 19:00:00` |
| `unit_fetched` | 当前 unit 读取行数 | `8000` |
| `unit_written` | 当前 unit 写入行数 | `8000` |
| `fetched` | 全任务累计读取行数 | `3480000` |
| `written` | 全任务累计写入行数 | `3480000` |
| `rejected` | 全任务累计拒绝行数 | `0` |

`stk_mins` 的目标消息示例：

```text
stk_mins: 218/25000 unit=stock ts_code=000001.SZ security_name=平安银行 freq=1min unit_fetched=8000 unit_written=8000 fetched=3480000 written=3480000 rejected=0
```

### 9.3 为什么保留 fetched/written 累计语义

不能把现有 `fetched/written` 直接改成当前股票值。

原因：

1. 现有前端、测试、任务详情和事件 payload 默认把 `fetched/written` 理解为全任务累计。
2. 改变旧 token 语义会影响所有数据集，不适合为 `stk_mins` 单点需求破坏约定。
3. 新增 `unit_fetched/unit_written` 可以同时满足当前对象展示和全任务统计。

因此约定：

```text
fetched/written = 全任务累计
unit_fetched/unit_written = 当前 unit 统计
```

### 9.4 前端展示口径

前端修改应作为“任务进度通用解析与展示能力”实现，不能在页面里写 `stk_mins` 专用判断。

当前任务详情页已有 `parseProgressDetails()`，会从 `progress_message` 解析 `trade_date/ts_code/index_code/code/fetched/written/rejected` 等 token。本轮应扩展同一个解析器，让它认识：

```text
unit
security_name
index_name
board_name
freq
start_date
end_date
unit_fetched
unit_written
```

任务详情页应按以下优先级展示当前处理对象：

1. 若存在 `unit=stock + ts_code + security_name`：

```text
当前股票：000001.SZ 平安银行
当前频度：1min
当前股票读取/写入：8000/8000
```

2. 若只有 `ts_code`：

```text
当前代码：000001.SZ
```

3. 若是其它对象类型：

```text
unit=trade_date -> 当前交易日
unit=board -> 当前板块
unit=index -> 当前指数
unit=code -> 当前代码
```

### 9.5 可复用性边界

这套进度游标模型是通用机制。

后端通用性：

1. engine 负责把当前 `PlanUnit.progress_context` 中的可展示游标字段拼入 `progress_message`。
2. 数据集策略只负责把自己的当前对象信息放进 `PlanUnit.progress_context`。
3. engine 不应该按 `dataset_key` 写死 `stk_mins`。

前端通用性：

1. 前端只识别 token，不识别数据集名。
2. 后续其它数据集只要输出同一套 token，任务详情页就能复用展示。
3. 不需要为每个数据集单独改页面。

后续其它数据集如果也需要展示“当前处理到哪个对象”，可以复用同一组 token：

| 场景 | 推荐 token |
|---|---|
| 股票维度扇出 | `unit=stock ts_code=... security_name=...` |
| 指数维度扇出 | `unit=index index_code=... index_name=...` |
| 板块维度扇出 | `unit=board board_code=... board_name=...` |
| 日期维度扇出 | `unit=trade_date trade_date=...` |
| 枚举维度扇出 | `unit=enum enum_field=... enum_value=...` |

第一期实现范围：

1. 后端只有 `stk_mins` 首先输出 `unit=stock ts_code security_name freq unit_fetched unit_written`。
2. 前端通用解析器一次性支持 `unit/security_name/index_name/board_name/freq/unit_fetched/unit_written`。
3. 前端展示逻辑不写 `stk_mins` 分支。
4. 不新增数据库字段。
5. 不调整 API schema。

---

## 10. 代码改动范围

### 10.1 必改文件

| 文件 | 改动 |
|---|---|
| `src/foundation/services/sync_v2/dataset_strategies/stk_mins.py` | 重写 unit 规划逻辑，从按日/session 改为按大窗口 |
| `src/foundation/services/sync_v2/engine.py` | 进度消息增加通用当前处理对象 token 与 `unit_fetched/unit_written` |
| `docs/datasets/stk-mins-dataset-development.md` | 更新请求策略描述，移除“按上午/下午拆请求”的当前口径 |
| `docs/ops/tushare-request-execution-policy-v1.md` | 更新 `stk_mins` 请求执行口径 |
| `tests/test_sync_v2_planner.py` | 更新 `stk_mins` unit 数量和请求参数断言 |
| `tests/test_cli_sync_v2_param_filtering.py` | 如涉及参数断言，同步更新 |
| `frontend/src/pages/ops-task-detail-page.tsx` | 扩展通用进度解析器，解析并展示 `unit/security_name/index_name/board_name/freq/unit_fetched/unit_written`；不得写 `stk_mins` 专用分支 |

### 10.2 原则上不改文件

| 文件/模块 | 原因 |
|---|---|
| `worker_client.py` | 现有分页能力仍可复用 |
| `writer.py` | 写入逻辑不变 |
| Alembic migration | 表结构不变 |
| Ops 手动任务 UI | 用户输入仍是交易日、freq、可选 ts_code |

---

## 11. 验证方案

### 11.1 单股票单日冒烟

```bash
GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-minute-history \
  --ts-code 000001.SZ \
  --freq 60min \
  --trade-date 2026-04-23
```

预期：

1. 只生成 1 个 unit。
2. 请求参数是：
   - `start_date=2026-04-23 09:00:00`
   - `end_date=2026-04-23 19:00:00`
3. 不再出现 morning/afternoon 两个 unit。
4. 任务详情页进度显示当前股票代码、股票名称、当前 unit 读取/写入行数。

### 11.2 单股票多频度冒烟

```bash
GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-minute-history \
  --ts-code 000001.SZ \
  --freq 30min,60min \
  --trade-date 2026-04-23
```

预期：

1. 生成 2 个 unit。
2. 每个 freq 一个 unit。

### 11.3 单股票区间冒烟

```bash
GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-minute-history \
  --ts-code 000001.SZ \
  --freq 60min \
  --start-date 2026-04-20 \
  --end-date 2026-04-24
```

预期：

1. 生成 1 个 unit。
2. 不按交易日拆成多个 unit。
3. 请求窗口为：
   - `2026-04-20 09:00:00`
   - `2026-04-24 19:00:00`

### 11.4 全市场小频度安全验证

先只选一个低数据量 freq：

```bash
GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-minute-history \
  --freq 60min \
  --trade-date 2026-04-23
```

预期：

1. unit 数量约等于股票池数量。
2. 不再乘以 `2 session`。
3. 请求耗时显著低于旧实现。

---

## 12. 风险与边界

### 12.1 深 offset 风险

长时间窗口下 `1min` 会出现较深 offset。

应对：

1. 第一版先按大窗口实现，最大化降低请求次数。
2. 如果实测 Tushare 对深 offset 不稳定，再引入窗口切片。
3. 窗口切片优先按年度或季度，不回退到按日/session。

### 12.2 超时风险

单个 `ts_code + freq` 大窗口可能耗时较长。

应对：

1. 依赖现有分页和重试。
2. 失败后可按同一股票/freq/窗口重跑。
3. 后续如需要再设计断点续跑，本轮不做。

### 12.3 进度颗粒度变化

unit 数量会大幅减少，但每个 unit 内分页更多。

影响：

1. Ops 进度会更快到达某个 unit，但单 unit 内可能等待较久。
2. 本轮不解决 page 级进度；这是后续流式/检查点方案的一部分。

---

## 13. 推荐实施顺序

### S1：改策略函数

只改 `stk_mins.py`：

1. 删除 session 拆分。
2. 区间不再展开交易日列表。
3. 使用起止日期生成一个 datetime 窗口。
4. unit 维度改为 `ts_code x freq x datetime_window`。
5. unit 元信息携带 `security_name`，但不传给 Tushare。

### S2：改进度上报

1. engine 进度消息增加当前 unit token。
2. `fetched/written` 保持累计语义。
3. 新增 `unit_fetched/unit_written` 当前 unit 语义。

### S3：改前端展示

1. 扩展任务详情页通用进度解析器。
2. 解析 `unit/security_name/index_name/board_name/freq/unit_fetched/unit_written`。
3. 展示当前股票、当前频度、当前 unit 读取/写入。
4. 不写 `stk_mins` 专用分支。
5. 保持旧 message 兼容。

### S4：改测试

更新 planner/CLI 相关测试，明确：

1. 单日单 freq 单股票只有 1 个 unit。
2. 单日多 freq 按 freq 生成多个 unit。
3. 区间不按交易日拆。
4. 请求参数使用 `09:00:00 ~ 19:00:00`。
5. progress message 包含当前股票和当前 unit 行数。

### S5：改文档

更新：

1. `docs/datasets/stk-mins-dataset-development.md`
2. `docs/ops/tushare-request-execution-policy-v1.md`

### S6：小窗口真实验证

先用单股票、单日、低频度验证。

通过后再试：

1. 单股票多频度。
2. 单股票小区间。
3. 全市场单日 `60min`。

---

## 14. 结论

`stk_mins` 的最快请求方式是：

```text
ts_code x freq x 大时间窗口 x limit/offset分页
```

而不是：

```text
trade_date x ts_code x freq x 上午/下午
```

因此下一步应先修请求策略。落盘可见性、流式写入、检查点提交是另一个问题，应该在请求次数降下来之后再处理。

同时，本轮应顺带建立通用进度游标 token，让页面能展示当前处理对象。第一期只在 `stk_mins` 落地，后续其它按股票、指数、板块、日期扇出的数据集可以复用同一模型。
