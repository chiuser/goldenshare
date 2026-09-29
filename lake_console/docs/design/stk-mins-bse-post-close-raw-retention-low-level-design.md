# 股票分钟线盘后尾段：低层设计

**状态：代码与隔离验证完成，待单独批准 2026-09-29 数据恢复。**
**上位方案：**[Raw 保留、Silver 过滤方案](stk-mins-bse-post-close-raw-retention-plan.md)
**代码依据：**2026-09-29 CodeGraph 调用链审计、Tushare MCP 五频度实测、Prod TaskRun `13822` 只读审计。

## 1. 硬口径清单

| 类型 | 约束 |
| --- | --- |
| 必须 | Prod Raw 保存任何股票代码在 `15:01–15:30` 的五频度来源行；DG Raw 原样导出。 |
| 必须 | DG Silver 对全部交易所过滤 `trade_time > 15:00:00`，在后续 QFQ/指标之前完成。 |
| 必须 | TaskRun 仍要求 `rows_rejected=0`；不能把 reject 降级成 warning。 |
| 必须 | 现有 Silver value-domain check 检出盘后行；不新增 check。 |
| 禁止 | 放宽午间、`15:31` 及其它不属于本合同的时间。 |
| 禁止 | 变更 Raw/Silver schema、资产键、job/sensor/check 名称、分区、Lake 路径、run key、cursor、动态分区。 |
| 不做 | 不写正式 Prod/Lake/Dagster，不跑 job/sensor，不补历史文件；实现阶段仅隔离测试。 |
| 性能 | 不增加 sensor 查询；Silver 仅在既有临时 relation 上增加一次谓词和计数。 |

## 2. 当前调用链和影响面

```text
Tushare stk_mins
  -> DatasetNormalizer
  -> _stk_mins_row_transform
  -> raw_tushare.stk_mins (Prod)
  -> Prod TaskRun rows_rejected gate
  -> stock_mins_raw_sensor
  -> raw_tushare_stk_mins_{1,5,15,30,60} (Lake)
  -> silver_stk_mins_{1,5,15,30,60}
  -> QFQ / factor repair / MACD-KDJ / wealth turnover
```

CodeGraph 发现 `_stk_mins_row_transform` 是 DatasetDefinition `stk_mins` 的唯一 normalizer；`write_silver_stk_mins_partition(...)` 是 `_create_silver_stk_mins_final_rows(...)` 的唯一生产调用者。此变更跨根工程 `src/foundation` 与 DG orchestrator 两个边界，但不触及 `ops`、`biz`、`app`。

| 位置 | 当前行为 | 计划改动 |
| --- | --- | --- |
| `src/foundation/ingestion/row_transforms.py::_stk_mins_row_transform` | 先验时间，再规范化代码；仅至 15:00。 | 先规范化代码，再调用纯时间许可 helper。 |
| `src/foundation/datasets/definitions/market_equity.py` | 注册现有 normalizer、Raw-only schema。 | 不改定义、字段或表；仅回归确认仍指向同一 transform。 |
| `defs/assets/stk_mins.py::_create_silver_stk_mins_base_tables` | target/1m input 没有统一盘后过滤。 | 建表时统计盘后行并只让 `<=15:00` 行进入后续表。 |
| `defs/assets/stk_mins.py::SilverStkMinsWriteResult` | 无盘后过滤证据。 | 追加一个整数统计字段。 |
| `defs/assets/stk_mins.py::_create_silver_stk_mins_final_rows` | `target_filtered` 可直接流入 1m/粗频度 final rows。 | 不改重算算法；它只接收已经过滤的输入。 |
| `defs/checks/stk_mins_checks.py` | Silver value domain 不要求时段上界。 | 在同一 check 的内部规则中补 `post_close_row_count=0`。 |
| QFQ / derived / MACD-KDJ | 部分地方已只接受 `<=15:00` 或固定窗口，但不能作为 Silver 防线。 | 不改生产逻辑；新增回归证明它们只会拿到标准 Silver。 |

## 3. Prod 低层实现

### 3.1 新的纯 helper

文件：`src/foundation/ingestion/row_transforms.py`

新增私有 helper（名称以实现时现行命名为准，但职责固定）：

```python
def _is_allowed_stk_mins_raw_trade_time(trade_time: datetime) -> bool:
    ...
```

逻辑：

```text
morning = 09:30 <= time <= 11:30
afternoon_and_post_close = 13:00 <= time <= 15:30
return morning OR afternoon_and_post_close
```

`_stk_mins_row_transform` 的顺序改为：

1. 规范化 `ts_code`（strip + upper）；
2. 解析 `trade_time`；
3. 调不依赖后缀的 helper；
4. 不允许则保持现有 `ValueError` / `normalize.row_transform_failed` 语义；
5. 再规范化 `freq` 与数值，并输出现有九个 storage 字段。

不得把 `session_tag` 放回输出，也不得改 `raw_tushare.stk_mins` 的数据库模型、主键或 DatasetDefinition。

### 3.2 Prod 测试

修改 `tests/test_dataset_normalizer.py`：

- `.BJ/.SH/.SZ` 的 1m `15:01`、`15:30` 都通过；断言输出字段仍只有现有九列。
- 所有后缀的 `15:31`、`12:00` 拒绝，reason 保持现有 transform 失败类别。
- 原有 `600000.SH 12:00` 拒绝案例保留。

修改 `tests/test_fields_constants.py`：锁定 `session_tag` 不进入 source storage/normalization contract，避免“为解释时段加字段”的回流。

运行根工程相关 definition/normalizer/architecture tests；不因本次变更新增 `DatasetDefinition` 或执行计划。

## 4. DG Silver 低层实现

### 4.1 过滤点

文件：`lake_console/orchestrator/src/orchestrator/defs/assets/stk_mins.py`

在 `_create_silver_stk_mins_base_tables(...)` 内，已读入同一 `raw_path`、完成日期和字段强制转换后，建立两个事实：

1. `post_close_source_row_count`：`strftime(trade_time, '%H:%M:%S') > '15:00:00'` 的行数；仅用于 metadata；
2. 供 `corrected_table`、identity mapping、suspend 过滤和 final generation 使用的 relation：只保留 `<= '15:00:00'`。

这样 target 与 one-minute 支路走同一边界。冻结历史行的既有保留分支也必须带同一 `<=15:00` 条件，避免旧 Silver 行绕开共同输入边界重新混入结果。不要改变 `13:00` 的现有行为，不要在 `_create_silver_stk_mins_final_rows(...)` 末尾补一层过滤，也不要按成交量删除 zero-volume bar。

该 helper 当前返回字典；为避免各分支遗漏，返回字典新增 `post_close_filtered_row_count`，`write_silver_stk_mins_partition(...)` 汇总 target/one-minute（粗频度会有两个输入）的计数，写进扩展后的 `SilverStkMinsWriteResult`。原有 metadata builder 继续通过 `to_details()` 展示该单个统计。

### 4.2 Silver check

文件：`lake_console/orchestrator/src/orchestrator/defs/checks/stk_mins_checks.py`

找到 `SILVER_STK_MINS_VALUE_DOMAIN_CHECK` 对应的共享审计 SQL/结果模型，新增内部 rule：

```text
post_close_row_count = count(trade_time > 15:00:00)
```

将其并入当前 value-domain 的 failed rule；metadata 只含 count 和最多现有样本上限，`summary` / `next_action` 指向“Silver 应只含常规时段，先重新从 Raw 生成”。该内部 rule 不是新的 Dagster check definition；不新增 check 名称、definition、job selection 或 catalog check 列表。

Raw check 明确不能加入该规则；Raw 的标准是来源保真与文件契约，不是常规时段事实。

### 4.3 DG 测试

以临时 Parquet fixture 增补：

| 测试 | 断言 |
| --- | --- |
| 1m Silver | `.BJ` regular + `15:01/15:30` Raw 输入，Silver 只有 `<=15:00`，metadata 计数为 2。 |
| 粗频度 | 5/15/30/60 各含 `15:30`，target 与 one-minute 支路均不泄漏盘后行。 |
| 0 成交尾段 | 仍按时间过滤，不能以零成交作为例外依据。 |
| 常规回归 | `.SH/.SZ/.BJ` 的 `15:00` 行保留；`13:00` 行行为不变。 |
| Raw 回归 | 模拟 prod 数据的 `.BJ 15:30` 出现在 raw parquet，Raw contract/key/value checks 仍通过。 |
| Check 负例 | 人工写入含 `15:01` 的 Silver parquet，既有 value-domain check 失败；不产生第五条 check。 |
| 下游隔离 | 从含尾段 Raw 生成 Silver 后，QFQ/derived 固定窗口输出不含盘后时间，现有 derived `15:30` 忽略测试继续通过。 |

## 5. 静态门禁和性能

新增/调整 `test_run_contract_static_gates.py` 或现有分钟线 contract 测试，锁住：

- 生产 normalizer 只出现一个后缀无关的 `15:01–15:30` 尾段许可；不得出现按交易所后缀分叉的盘后 allowlist；
- Raw writer SQL 不得加 `<=15:00` 过滤；
- Silver 公共输入边界必须含 `<=15:00`；
- value-domain check 必须审计盘后行；
- sensor 与 readiness 不得新增时间扫描、源查询、cursor 明细或动态 SQL。

性能验收使用临时 fixture 记录：

- Silver 的 SQL 调用数不增加；
- 盘后过滤只读取本次已打开的 Raw relation，不能新增 parquet scan；
- 正常（无盘后行）与含尾段两组样本的峰值行数、临时表行数和耗时；
- sensor 单测证明不调用这一逻辑，保持既有 TaskRun/coverage 查询模型。

## 6. 实施结果、正式恢复和停止条件

2026-09-29 已完成以下代码和隔离验证，未访问或写入正式 Prod、Lake、Dagster：

- Raw normalizer 对 `.BJ/.SH/.SZ` 一律接受 `15:01–15:30`，并继续拒绝 `12:00`、`15:31`；不按后缀分叉。
- Silver 在共同输入边界过滤 `>15:00`，冻结历史保留分支同样不能绕过该边界；写入 metadata 只增加 `post_close_filtered_row_count`。
- 既有 `silver_stk_mins_value_domain_check` 和 bounded readiness 都把现存盘后行判为失败；没有增加 Dagster check definition、job selection 或 sensor 工作量。
- 根 normalizer 测试通过；隔离 runner 的 M5B、freeze policy 和 readiness suites 通过；静态门禁 `test_run_contract_static_gates.py` 通过 113 项。全仓治理 runner 仍受当前 ETF 例外模块缺失影响，不能导入全仓 check 清单；该无关问题不在本专项修改范围内。

不将执行状态写成已恢复。

正式恢复必须拆开批准：

1. Tushare/Prod 只读 source preflight；
2. 受控重拉 Prod `.BJ` 受影响日期和五频度；
3. 验证 TaskRun 零 reject；
4. DG 依赖顺序重建并审计。

以下任一情况停止，不改数据：

- Tushare 实测显示尾段市场/时间范围与本 LLD 不一致；
- 过滤导致 `15:00` 前普通行、粗频度窗口或既有冻结行变化；
- 发现有正式消费者直接以 Raw 尾段为标准技术计算输入；
- 需要 schema、分区、resource 或 sensor 行为改动才能实现。

## 7. 验证命令（开发阶段）

```bash
cd /Users/congming/github/goldenshare
.venv/bin/python3 -B -m pytest -q \
  tests/test_dataset_normalizer.py \
  tests/test_fields_constants.py

cd /Users/congming/github/goldenshare/lake_console/orchestrator
.venv/bin/python3 -B -m pytest -q \
  tests/test_stk_mins_silver_m5b_contracts.py \
  tests/test_stk_mins_raw_value_domain_contract.py \
  tests/test_stk_mins_qfq_m11_derived_assets.py \
  tests/test_stk_mins_lake_readiness.py \
  tests/test_run_contract_static_gates.py
.venv/bin/ruff check --no-cache \
  src/orchestrator/defs/assets/stk_mins.py \
  src/orchestrator/defs/checks/stk_mins_checks.py
git diff --check
```

这些是隔离测试；不运行 `dg check defs`、正式 job、sensor、Prod/Lake 写入或历史补数。
