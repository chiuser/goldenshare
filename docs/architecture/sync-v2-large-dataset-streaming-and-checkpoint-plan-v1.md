# Sync V2 大数据集流式写入与检查点提交方案 v1

状态：待评审  
适用范围：`src/foundation/services/sync_v2/**`  
不适用范围：本方案不改变数据集请求策略本身，不新增数据集，不调整表结构。

---

## 1. 背景

股票分钟线接入后暴露出一个更通用的问题：当一个同步任务耗时较长、请求量较大、分页结果较多时，当前 Sync V2 的执行方式会让用户误以为“没有落库”，并且确实存在长事务和单 unit 内存峰值风险。

这不是 `stk_mins` 单个数据集的问题，而是 Sync V2 引擎层需要具备更明确的大数据集执行能力。

---

## 2. 当前代码事实

### 2.1 执行链路

当前链路为：

```text
BaseSyncService._run
  -> SyncV2Service.execute
    -> SyncV2Engine.run
      -> worker.fetch
      -> normalizer.normalize
      -> writer.write
  -> session.commit
```

关键代码位置：

- `src/foundation/services/sync_v2/base_sync_service.py`
- `src/foundation/services/sync_v2/service.py`
- `src/foundation/services/sync_v2/engine.py`
- `src/foundation/services/sync_v2/worker_client.py`
- `src/foundation/services/sync_v2/strategy_helpers/pagination_loop.py`
- `src/foundation/services/sync_v2/normalizer.py`
- `src/foundation/services/sync_v2/writer.py`

### 2.2 事务提交口径

当前 `BaseSyncService._run` 只有在 `execute()` 完整成功后才执行 `self.session.commit()`。

影响：

1. 同步过程中 `writer.write()` 已经执行 SQL，但其他数据库连接看不到未提交数据。
2. 任务中途失败时，整个事务回滚，前面已经写入的 unit 也会被撤销。
3. 长时间任务会形成长事务，增加 WAL、回滚成本、锁等待和线上排查难度。

### 2.3 分页内存口径

当前 `fetch_rows_with_pagination()` 会把所有分页结果累积到 `rows_raw`：

```text
rows_raw.extend(rows)
```

随后 normalizer 会再构造 `rows_normalized`。

影响：

1. 内存不是按“整个任务”无限累积，但会按“单个 unit”累积。
2. 如果某个 unit 单日返回 8 万行以上，例如 `dc_member`，则同一时刻可能存在 raw list + normalized list。
3. 对 `stk_mins` 这类全市场、跨日期、跨频率任务，单 unit 可能不一定最大，但 unit 数量巨大，长事务问题会被放大。

### 2.4 计划单元口径

当前 engine 会一次性拿到完整 `units`：

```text
units = runtime_contract.strategy_fn(...)
total_units = len(units)
```

影响：

1. 对普通日频数据集问题不大。
2. 对 `stk_mins` 这类 `股票池 * 日期 * freq * 交易时段` 的组合，会形成很长的 unit 列表。
3. 进度展示依赖 `len(units)`，因此不能简单把 list 改成 generator，需要同时设计 total 估算或延迟总量语义。

---

## 3. 要解决的问题

### 3.1 用户可见性问题

大任务运行过程中，数据库查询不到数据，用户会误判“没有落盘”。

本质原因：SQL 已执行但事务未提交。

### 3.2 失败回滚成本问题

一个大任务跑几个小时后失败，之前写入全部回滚，成本不可接受。

### 3.3 单 unit 内存峰值问题

分页接口在单 unit 内返回大量数据时，当前实现会先攒完整 raw list，再整体归一化和写入。

### 3.4 计划列表膨胀问题

分钟线等数据集会产生大量 unit，当前 eager list 对大范围任务不够稳。

---

## 4. 设计目标

1. 保留 Sync V2 engine 作为统一执行层。
2. 默认行为保持兼容：普通数据集仍可使用任务级事务。
3. 大数据集可以显式启用：
   - 分页流式处理
   - unit 或 page 级检查点提交
   - 更细粒度进度上报
   - 可选 lazy unit 规划
4. 同步失败后，已检查点提交的数据不回滚，后续依靠幂等 upsert 或 replace 语义重跑。
5. 所有策略必须由 contract 显式声明，不允许 engine 根据 dataset_key 写特例。

---

## 5. 非目标

1. 本方案不修改 Tushare 请求参数策略。
2. 本方案不调整数据表结构。
3. 本方案不重做 Ops 任务模型。
4. 本方案不改变所有数据集的默认事务语义。
5. 本方案不引入跨子系统依赖，不允许 foundation 反向依赖 ops。

---

## 6. 目标能力模型

### 6.1 新增 ExecutionSpec

建议在 `src/foundation/services/sync_v2/contracts.py` 中新增最小执行策略对象：

```python
@dataclass(slots=True, frozen=True)
class ExecutionSpec:
    fetch_mode: str = "unit_buffered"
    commit_policy: str = "task"
    commit_every_units: int | None = None
    commit_every_rows: int | None = None
    plan_mode: str = "eager"
```

并挂到 `DatasetSyncContract`：

```python
execution_spec: ExecutionSpec = field(default_factory=ExecutionSpec)
```

字段说明：

| 字段 | 取值 | 含义 | 默认 |
|---|---|---|---|
| `fetch_mode` | `unit_buffered` / `page_stream` | unit 内是整体取完再写，还是分页边取边写 | `unit_buffered` |
| `commit_policy` | `task` / `unit` / `rows` / `page` | 事务提交粒度 | `task` |
| `commit_every_units` | 正整数或空 | `commit_policy=unit` 时每 N 个 unit 提交 | 空 |
| `commit_every_rows` | 正整数或空 | `commit_policy=rows` 时每 N 行提交 | 空 |
| `plan_mode` | `eager` / `lazy` | 执行单元是否一次性生成 | `eager` |

约束：

1. `task` 是兼容默认值。
2. `page_stream` 必须要求写入路径具备幂等性。
3. `unit/page/rows` 提交策略必须在文档中明确该数据集可重跑。
4. 不允许在 engine 中按 dataset_key 特判。

### 6.2 推荐初始取值

| 数据集类型 | fetch_mode | commit_policy | plan_mode | 说明 |
|---|---|---|---|---|
| 普通小数据集 | `unit_buffered` | `task` | `eager` | 保持现状 |
| 普通日频全市场 | `unit_buffered` | `unit` | `eager` | 降低长事务风险 |
| 单 unit 大分页 | `page_stream` | `page` 或 `rows` | `eager` | 降低内存峰值 |
| 分钟线全市场 | `page_stream` | `unit` 或 `rows` | `lazy` | 降低 unit 列表与长事务风险 |

---

## 7. 模块改造设计

### 7.1 contracts.py

新增 `ExecutionSpec`，并加入 `DatasetSyncContract`。

兼容要求：

1. 所有现有 contract 不填时自动走默认值。
2. linter 增加合法枚举校验。
3. registry guardrail 增加 `execution_spec` 结构检查。

### 7.2 pagination_loop.py

保留现有 `fetch_rows_with_pagination()`，新增流式迭代 helper：

```python
def iter_rows_pages_with_pagination(...) -> Iterator[FetchPage]:
    ...
```

`FetchPage` 建议字段：

| 字段 | 含义 |
|---|---|
| `unit_id` | 所属 unit |
| `page_index` | 第几页 |
| `offset` | 当前 offset |
| `limit` | 当前 limit |
| `rows_raw` | 当前页 raw rows |
| `request_count` | 当前页请求数 |
| `retry_count` | 当前页重试数 |
| `is_last_page` | 是否最后一页 |

约束：

1. 旧 helper 不删除，避免一次性冲击所有数据集。
2. 新 helper 不累积全量 rows。
3. 非分页接口也应产出一页，统一 engine 分支。

### 7.3 worker_client.py

保留：

```python
fetch(...) -> FetchResult
```

新增：

```python
iter_fetch_pages(...) -> Iterator[FetchPageResult]
```

要求：

1. 复用现有 adapter、retry、error_mapper。
2. page_stream 路径不创建完整 `rows_raw`。
3. 指标统计仍要聚合 request_count / retry_count / latency。

### 7.4 normalizer.py

短期可以复用当前 `normalize()`，但输入从整 unit `FetchResult` 变为单 page `FetchPageResult`。

建议新增：

```python
normalize_page(...)
```

约束：

1. 行级校验逻辑不能复制两份。
2. `raise_if_all_rejected()` 需要在 page 级和 unit 级语义上分别考虑。
3. page 级全拒绝不一定意味着整个 unit 失败，除非该 page 是非空页且命中硬失败规则。

### 7.5 writer.py

原则上 writer 不需要知道流式与否。

要求：

1. 每次写入一个 `NormalizedBatch`。
2. `rows_written` 按 page 或 unit 累加。
3. 对 replace 型写入路径要谨慎，不可直接 page commit，避免同一个日期被多页重复 replace。

需要特别标注的写入路径：

| write_path | 是否适合 page commit | 说明 |
|---|---|---|
| `raw_only_upsert` | 适合 | 幂等 upsert，适合分钟线 |
| `raw_core_upsert` | 适合 | 幂等 upsert |
| `raw_std_publish_moneyflow` | 暂缓 | 涉及 publish，需要单独确认 |
| `raw_core_snapshot_insert_by_trade_date` | 暂缓 | replace/insert 语义需按日期整体处理 |
| `raw_index_period_serving_upsert` | 暂缓 | 包含派生补齐与活跃池过滤 |

### 7.6 engine.py

新增两条执行路径：

```text
unit_buffered:
  fetch whole unit -> normalize -> write -> maybe checkpoint

page_stream:
  for page in worker.iter_fetch_pages:
    normalize page -> write page -> maybe checkpoint
```

要求：

1. 默认仍走 `unit_buffered + task commit`。
2. `page_stream` 的统计需要聚合到 unit 和 task。
3. progress message 中要体现 committed 信息，避免用户误判。
4. engine 不得写 dataset_key 特判。

### 7.7 checkpoint_controller.py

新增 foundation 内部组件：

```text
src/foundation/services/sync_v2/checkpoint_controller.py
```

职责：

1. 根据 `ExecutionSpec` 判断是否需要提交。
2. 维护本次任务内的 `committed_units` / `committed_rows` / `checkpoint_count`。
3. 调用 `session.commit()`。
4. 提交后继续允许当前 session 进入下一个事务。

注意：

1. 这是 foundation 内部能力，不依赖 ops。
2. 只负责事务检查点，不负责任务状态机。
3. 如果 checkpoint 后任务失败，最终任务状态仍应为 failed，但数据可能已部分提交。

### 7.8 BaseSyncService._run

当前 `_run` 在成功后统一 commit，在失败后 rollback。

引入 checkpoint 后，需要明确语义：

1. 若没有 checkpoint，行为保持现状。
2. 若已 checkpoint，失败时只 rollback 当前未提交事务。
3. run log 最终仍要记录 FAILED。
4. summary message 需要提示 `partial_committed=1`。

建议新增到 `EngineRunSummary`：

| 字段 | 含义 |
|---|---|
| `rows_committed` | 已检查点提交行数 |
| `checkpoint_count` | 检查点次数 |
| `partial_committed` | 失败时是否存在已提交数据 |

---

## 8. 数据集分级建议

### 8.1 P0：必须优先支持检查点

| 数据集 | 原因 | 建议策略 |
|---|---|---|
| `stk_mins` | 全市场分钟线，unit 数量大，运行时间长 | `page_stream + unit/rows commit + lazy plan` |
| `dc_member` | 单日可返回 8 万行以上，单 unit 内存峰值明显 | `page_stream + page/rows commit` |
| `stk_factor_pro` | 宽表，单日全市场，单次 10000 上限 | `page_stream + unit/rows commit` |

### 8.2 P1：建议逐步启用 unit checkpoint

| 数据集 | 原因 | 建议策略 |
|---|---|---|
| `daily` | 日频全市场，长区间回补可能耗时 | `unit_buffered + unit commit` |
| `adj_factor` | 日频全市场 | `unit_buffered + unit commit` |
| `fund_daily` | 日频全市场 | `unit_buffered + unit commit` |
| `cyq_perf` | 日频全市场，分页 | `page_stream + unit commit` |
| `moneyflow*` | 日频资金流族，部分分页 | 先评估 publish 路径，再启用 |
| `dc_daily` / `ths_daily` | 板块日频，分页 | `page_stream + unit commit` |
| `ths_hot` / `dc_hot` | 榜单类，枚举扇出 + 分页 | `page_stream + unit commit` |

### 8.3 P2：暂不需要改变

| 数据集 | 原因 |
|---|---|
| `stock_basic` / `hk_basic` / `us_basic` | 快照类，通常单次任务数据量可控 |
| `index_basic` / `etf_basic` / `ths_index` | 基础资料类 |
| `trade_cal` | 体量小 |
| `broker_recommend` | 月度低频 |

---

## 9. 关键语义决策

### 9.1 大数据任务是否还追求全任务原子性

建议：不追求。

理由：

1. 数据同步任务以幂等 upsert 为主。
2. 长事务回滚成本高于局部提交风险。
3. 失败后通过重跑补齐，比一次性回滚更符合生产运维需求。

要求：

1. 启用 checkpoint 的数据集必须确认写入幂等。
2. Ops 任务详情必须能显示 partial committed。
3. runbook 必须说明失败后可以重跑。

### 9.2 page commit 还是 unit commit

建议：

1. 默认先启用 unit commit。
2. 只有单 unit 超大分页时，才启用 page 或 rows commit。
3. replace 型写入先不启用 page commit。

### 9.3 是否立即改所有数据集

建议：不立即改所有。

先按风险分层迁移：

1. `stk_mins`
2. `dc_member`
3. `stk_factor_pro`
4. 其他 P1 数据集

---

## 10. 实施里程碑

### M1：契约与门禁，不改变行为

目标：

1. 新增 `ExecutionSpec`。
2. 所有数据集默认仍是 `unit_buffered + task commit + eager`。
3. linter 与 registry guardrail 校验 execution_spec。

验证：

```bash
pytest -q tests/test_sync_v2_validator.py tests/test_sync_v2_planner.py tests/test_sync_v2_linter.py
pytest -q tests/test_sync_v2_registry_routing.py
pytest -q tests/architecture/test_sync_v2_registry_guardrails.py
GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-v2-lint-contracts
```

### M2：分页流式 fetch/normalize/write，默认关闭

目标：

1. 新增 page iterator。
2. 新增 engine page_stream 分支。
3. 默认不启用，确保现有数据集行为不变。

新增测试：

1. 分页 iterator 不累积全部 rows。
2. page_stream 能逐页调用 writer。
3. 异常时 structured error 仍保持原语义。

### M3：检查点提交控制器，默认关闭

目标：

1. 新增 checkpoint controller。
2. 支持 `commit_policy=unit`。
3. progress message 增加 checkpoint 信息。

新增测试：

1. 默认 task commit 不变。
2. unit commit 会按 unit 调用 session.commit。
3. unit commit 后失败只 rollback 当前事务。

### M4：`stk_mins` 启用大数据策略

目标：

1. `stk_mins` contract 启用 `page_stream`。
2. 初始建议 `commit_policy=unit`。
3. 若单 unit 内分页仍较大，再评估 `rows` commit。

验证：

```bash
GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-minute-history \
  --freq 60min --trade-date 2026-04-23 --ts-code 000001.SZ
```

检查：

1. 同步过程中数据可见。
2. 进度包含 fetched/written/committed。
3. 失败可重跑。

### M5：`dc_member` / `stk_factor_pro` 逐个启用

目标：

1. `dc_member` 优先 page_stream。
2. `stk_factor_pro` 再启用 page_stream。
3. 每个数据集单独小窗口验证，不并行。

### M6：P1 数据集分批评估

目标：

1. 对普通日频数据集启用 unit checkpoint。
2. 对 publish/replace 类写入路径逐个评估。
3. 不做全量一键切换。

---

## 11. 回滚方案

### 11.1 代码回滚

每个里程碑独立提交。

若 M2/M3 出现问题，可回滚到仅有 `ExecutionSpec` 的版本。

### 11.2 数据集回滚

因为默认值保持 `task commit`，单个数据集启用大数据策略后如有异常，只需把该数据集 contract 改回：

```python
ExecutionSpec(
    fetch_mode="unit_buffered",
    commit_policy="task",
    plan_mode="eager",
)
```

### 11.3 任务失败处理

启用 checkpoint 的任务失败后：

1. 已提交数据保留。
2. 任务状态为 FAILED。
3. 运维侧按同参数重跑。
4. 依靠 upsert/replace 幂等补齐。

---

## 12. 风险与防护

### 12.1 partial commit 语义变化

风险：用户看到任务失败，但数据库已有部分数据。

防护：

1. 只对大数据集显式启用。
2. summary message 标记 `partial_committed=1`。
3. runbook 明确失败后重跑。

### 12.2 replace 型写入不适合 page commit

风险：同一日期多页 replace 可能互相覆盖。

防护：

1. page commit 只先开放给 upsert 型写入。
2. replace 型数据集必须单独评审。

### 12.3 progress 统计与提交统计混淆

风险：`written` 不等于已提交。

防护：

1. 新增 `committed` 统计。
2. 进度显示区分 `written` 和 `committed`。

### 12.4 运行中取消

风险：取消后已 checkpoint 的数据不会回滚。

防护：

1. 取消任务显示 `CANCELED`。
2. 若存在 checkpoint，message 标注 `partial_committed=1`。
3. 支持重跑补齐。

---

## 13. 本方案推荐的下一步

建议先执行 M1 + M2 + M3，但仍不切任何数据集。

原因：

1. 先把 engine 能力做出来。
2. 通过测试证明默认行为不变。
3. 再单独切 `stk_mins`，风险最小。

不建议现在直接只修 `stk_mins`。

原因：

1. `dc_member`、`stk_factor_pro` 也有同类风险。
2. 单点补丁会让大数据能力分散在策略层，后续更难维护。
3. 这类能力本质属于 engine，不属于某个数据集。

