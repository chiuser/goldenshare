# ETF 历史分钟行情数据集接入方案 v1

状态：已落地；对象来源已切换为 ETF Basic Serving；P9A 指定区间 Preview 与 P9B 受控 Submit 代码已完成，原全历史 Preview 已作废，生产 TaskRun 与补拉均未执行
创建日期：2026-08-24
最近更新：2026-08-29
LLD：[ETF 历史分钟行情数据集 LLD v1](/Users/congming/github/goldenshare/docs/datasets/etf-mins-dataset-low-level-design-v1.md)
源站文档：[Tushare 0387 ETF 历史分钟行情](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0387_ETF历史分钟行情.md)

## 1. 当前结论

`etf_mins` 维护 Tushare 原生 ETF 历史分钟行情，唯一物理事实表为 `raw_tushare.etf_minute_bar`。当前代码不再读取 ETF 激活池；所有按代码展开的请求都由 `core_serving.etf_basic` 的统一当前可请求 selector 驱动，并在生成窗口前把起点裁到 ETF 上市日。

本次对象来源切换只改变未来请求规划，不删除既有分钟事实，也不自动补齐全量历史。生产全量对齐由主方案 P9-P12 单独预览、授权和执行。

P9A 只提供必填的 `alignment_start_date/alignment_end_date`。它固定本次中国日期和一份 Basic snapshot，把全部当前可请求 ETF 放入 target hash；其中上市日晚于截止日的 ETF 只计数、不生成区间。其余对象按五个原生频率检查指定区间内的 raw 首尾边界和明确成功 TaskRun 请求证据；每只 ETF 的有效起点取指定开始日与上市日之后的首个 SSE 开市日，不检查内部逐日空洞，也不把纯休市范围规划成请求。

## 2. 源接口与字段

支持五种 Tushare 原生频率：

```text
1min / 5min / 15min / 30min / 60min
```

每个请求必须带 `ts_code`、`freq`、`start_date`、`end_date`，分页由统一 source client 追加 `limit/offset`。保存字段为：

```text
ts_code, freq, trade_time, open, close, high, low,
vol, amount, vwap, exchange
```

业务主键是 `(ts_code, freq, trade_time)`。任何重复身份但内容冲突、身份字段缺失或源端乘数异常都必须让 unit 失败，不能静默选一行。

## 3. ETF 对象资格

一次 plan 开始时固定一个中国自然日 `eligibility_as_of`。统一条件由 `EtfBasicDAO` 实现：

```text
list_status = 'L'
AND list_date IS NOT NULL
AND list_date <= eligibility_as_of
AND ts_code 仅限 .SH / .SZ
AND ts_code 后缀与 exchange 一致
```

规划规则：

1. 未填写 `ts_code`：一次加载全市场 requestability snapshot，再对所有 target 生成 unit。
2. 填写单个 `ts_code`：只查询一次该代码的 requestable target，不加载全市场 snapshot。
3. 一次显式请求不支持多个 ETF 代码。
4. 显式代码不合格时返回 `etf_not_requestable`。
5. 全量资格集合为空时返回 `universe_empty`，不回退历史池或猜全市场。

Definition 中保留 `universe_policy='pool'` 只是表示“按对象集合展开”的通用技术形状；对象源已经是无 resource 的 `core_serving_etf_basic`，不存在新的持久化池。

## 4. 时间与切窗

单日和区间请求的有效起点均为：

```text
effective_start = max(requested_start, list_date)
```

全量规划中，如果整个请求窗口早于某 ETF 的上市日，该 ETF 不生成 unit；显式单代码请求则返回 `window_before_list_date`。不会为这种正常裁剪新增“跳过统计”或共享执行计划字段。

区间按频率拆为受控自然月窗口：

| 频率 | 单 unit 最大自然月跨度 |
| --- | ---: |
| `1min` | 2 |
| `5min` | 12 |
| `15min` | 36 |
| `30min` | 72 |
| `60min` | 120 |

每个 unit 对应一个 ETF、一个频率和一个窗口。请求时间边界使用窗口首日 `09:00:00` 到末日 `19:00:00`，不把日期区间直接扩成逐日 unit。

## 5. 存储、分页与事务

| 项目 | 当前合同 |
| --- | --- |
| 存储 | raw-only，`raw_tushare.etf_minute_bar` |
| Serving | 无第二份分钟 serving 物理表 |
| 分页 | `offset_limit`，每页 8,000 行 |
| unit 最大接纳 | 24,000 行 |
| 页面处理 | unit 内聚合后一次写入 |
| 写入 | 按业务主键幂等 upsert |
| 提交 | 每个 unit 独立提交 |
| fetch concurrency | 2 |

源端空结果允许完成，因为停牌、历史无数据或源端尚未形成分钟事实不能被系统伪造成错误行；但空结果也不能作为“已有每分钟完整覆盖”的证明。

## 6. 运营与观测

数据集支持手动和普通定时 `maintain`，时间输入为单日或区间，频率至少选择一个。`trade_time` 是观测字段，但 V1 不接普通按日完整性审计，因为分钟完整性需要交易时段网格和停牌语义。

每个实际 unit 的 `progress_context` 记录：

```text
eligibility_as_of
master_list_date
requested_start_date
effective_start_date
ts_code / freq / window
```

这些字段用于解释本 unit 为什么从该日期开始，不扩展公共执行计划或 TaskRun schema。

## 7. 历史机制与当前边界

旧实现曾以 `ops.etf_series_active(resource='etf_mins')` 的 1,395 个代码展开请求。该数量只是一份历史 seed/生产快照，不是当前 ETF 全集。P3 已迁移 planner，P8 已删除旧池代码基础设施并准备 drop migration，P11 已完成生产物理表删除和 Basic 正式重建。

明确不做：

1. 不恢复激活池、seed、Review 页面或兼容读取。
2. 不因当前 `D`、代码消失或 `list_date` 变晚而删除历史分钟事实。
3. 不在普通计划中自动请求 Tushare 补齐全历史。
4. 不把停牌或源端空日自动判定为内部分钟缺口。
5. P9A 不请求 Tushare、不创建 TaskRun、不写数据库，也不提供 submit/apply 入口。
6. raw 首尾边界按自然月执行 `ts_code + freq + COUNT/MIN/MAX` 集合统计；每条 SQL 只访问该月分区，再与同一次 Basic snapshot 在内存中求交。禁止跨全部分区聚合、ETF×频率 N+1，以及月度超时后自动改成周度重复扫描。

2026-08-29 使用本地未部署代码对 Prod 完成 `2026-01-01` 至 `2026-08-28` 的只读 Preview：1,647 个当前可请求 ETF 全部进入对齐，1,395 个已有指定区间首尾覆盖，252 个需要从 2026 年首个开市日或更晚上市日补到截止日。最终生成 252 个 action、1,774 个 unit；源请求下界 1,774、分页请求上界 7,096。五个频率均无尾部缺口；此前默认追溯上市日的 44,793-unit 计划已作废。该结果只用于 P9B 规模拍板，没有创建 TaskRun、请求 Tushare 或写入生产数据库。

## 8. P9B 受控 Submit

P9B 新增唯一显式入口：

```text
goldenshare ops-submit-etf-minute-alignment --plan plan.json --confirm-plan-hash <sha256> --batch-size <正整数>
```

它不会直接请求 Tushare，也不会自己生成 unit。计划文件先在数据库外完成 schema、hash、action 和 unit 数复核；随后在一个可重复读事务中串行检查 open `etf_mins` TaskRun、一次加载当前 Basic snapshot，并复用 P9A 的日历和月度覆盖查询。Basic target 变化、action 早于当前上市日或覆盖只发生部分变化时整批拒绝，要求重新 Preview。完全覆盖的 action 跳过，仍精确缺失的前 `batch-size` 个 action 才通过现有 `TaskRunCommandService.stage_task_run()` 转成正式 range TaskRun，整批只提交一次。

用户已选择首次实际补拉使用 10 个 action，但 CLI 不把 10 设为默认值。P9B 当前只完成代码和测试，没有执行生产 submit；实际批次必须等待 P10 发布门禁、部署和 P12 独立授权。
