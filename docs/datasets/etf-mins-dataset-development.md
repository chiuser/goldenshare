# ETF 历史分钟行情数据集接入方案 v1

状态：Basic 驱动、Preview 和普通手动任务多代码扇开已落地；旧 alignment Submit 已删除；2026 年指定区间生产补拉与对账已完成
创建日期：2026-08-24
最近更新：2026-08-29
LLD：[ETF 历史分钟行情数据集 LLD v1](/Users/congming/github/goldenshare/docs/datasets/etf-mins-dataset-low-level-design-v1.md)
源站文档：[Tushare 0387 ETF 历史分钟行情](/Users/congming/github/goldenshare/docs/sources/tushare/ETF专题/0387_ETF历史分钟行情.md)

## 1. 当前结论

`etf_mins` 维护 Tushare 原生 ETF 历史分钟行情，唯一物理事实表为 `raw_tushare.etf_minute_bar`。当前代码不再读取 ETF 激活池；所有按代码展开的请求都由 `core_serving.etf_basic` 的统一当前可请求 selector 驱动，并在生成窗口前把起点裁到 ETF 上市日。

本次对象来源切换只改变未来请求规划，不删除既有分钟事实，也不自动补齐全量历史。主方案 P9-P12 已完成 `2026-01-01..2026-08-28` 指定区间的 Preview、授权、执行和对账。已经执行的 unit 保持有效；未来若处理其他区间，一律以新 Preview 重算，不从已取消 TaskRun 的汇总状态猜测。

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
3. 填写多个 `ts_code`：一次加载全市场 requestability snapshot，在内存中校验并按规范化代码顺序返回输入集合；不逐代码查询。
4. 多代码输入支持逗号分隔字符串或字符串数组，统一去空格、转大写、去重和稳定排序。
5. 任一显式代码不合格时整次返回 `etf_not_requestable`，不生成部分 unit，也不对合格子集继续请求。
6. 全量资格集合为空时返回 `universe_empty`，不回退历史池或猜全市场。

Definition 中保留 `universe_policy='pool'` 只是表示“按对象集合展开”的通用技术形状；对象源已经是无 resource 的 `core_serving_etf_basic`，不存在新的持久化池。

`etf_mins` 的 `ts_code` 公开过滤器改为多值，但不改变“不填写即全量”的既有语义。该能力只放宽 ETF 分钟路径；共用 Basic selector 的沪市、深市申赎清单仍保持一次最多一个显式代码。

## 4. 时间与切窗

单日和区间请求的有效起点均为：

```text
effective_start = max(requested_start, list_date)
```

全量规划中，如果整个请求窗口早于某 ETF 的上市日，该 ETF 不生成 unit；任一显式代码的窗口整体早于上市日时整次返回 `window_before_list_date`。不会为这种正常裁剪新增“跳过统计”或共享执行计划字段。

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

2026-08-29 首次 Prod 只读 Preview 得到 252 个 action、1,774 个 unit。旧 Submit 随后以“一 action 一 TaskRun”执行：首批 10 个任务成功；后续队列在 61 个成功、181 个取消时按用户指令停止，开放任务归零。取消任务 `9923` 在停止前已完成 3/8 unit，证明对齐不能依赖 TaskRun 最终汇总行判断物理覆盖。

停止后只读 Preview 以 raw 事实重算得到：1,647 个当前可请求 ETF，181 个待补代码，182 个 action，1,333 个 unit，源请求下界 1,333、分页上界 5,332。`159539.SZ` 因部分 unit 已提交而形成一个已知例外：四个非 `1min` 频率需要从 `2026-01-05` 补，`1min` 只需从 `2026-07-01` 补。

## 8. 普通手动任务多代码扇开方案

运营直接在现有 `etf_mins` 手动维护页面提交一个普通任务：

```text
ETF 代码：以逗号分隔输入多个代码
开始日期：2026-01-05
结束日期：2026-08-28
分钟周期：1min / 5min / 15min / 30min / 60min
```

`DatasetDefinition` 将 `ts_code` 标记为多值。现有手动表单把逗号文本提交为字符串数组，现有手动动作服务把该数组保存在一个普通 TaskRun 的 `filters_json.ts_code` 中；planner 再统一转大写、去重和排序。不增加专用 API、页面、TaskRun 类型、数据库字段或执行 payload。

planner 在一次 plan 中固定中国自然日。一个代码时继续调用一次 `get_requestable_target()`；两个及以上代码时只加载一次 Basic requestability snapshot，并对全部输入做整体验证。之后按“代码 × 所选频率 × 经上市日裁剪后的日期窗口”生成 unit。request builder 看到的仍是单个标量 `ts_code`，不会把数组或逗号字符串传给 Tushare。

一个 TaskRun 仍按现有执行链运行多个 unit：每 unit 独立提交、抓取并发 2、幂等 raw upsert、既有失败/取消/重试语义全部不变。旧 `ops-submit-etf-minute-alignment` service、CLI 和专属测试删除；P9A Preview 保留为只读审计和生成待补代码清单的工具，但不再承担提交。

P9A 对成功 TaskRun 的覆盖解析同步兼容历史单代码字符串和新的代码数组，后者按代码 × 频率还原请求区间。这样，即使某个成功 unit 因源端空结果没有 raw 行，下一次 Preview 仍能知道它已经请求过；无代码全量任务和非法数组继续不作为覆盖证据。

本轮选择“一个普通手动任务”意味着接受一个已知的小额重复请求：`159539.SZ` 的 `1min` 会从 `2026-01-05` 开始，重复请求此前已覆盖的 2026 年上半年三个 2 个月窗口；幂等 upsert 不会产生重复事实，预计总 unit 从精确 Preview 的 1,333 增至 1,336。若要求完全不重复，只能把该代码拆成额外手动任务，这与本轮单任务目标冲突。

生产执行记录：门禁确认开放 `etf_mins` TaskRun 为 0，schedule 39 不与本轮重叠，181 个代码全部当前可请求。普通手动 TaskRun `10117` 以一个任务展开 1,336 个 unit，全部成功，抓取并保存 7,606,095 行，失败、拒绝、去重和 issue 均为 0。补后 Preview 确认 1,647 个当前可请求 ETF 的 8,235 个代码/频率组合全部由 raw 覆盖，prefix/suffix 缺口、action 和 unit 均为 0。本结论不包括区间内部空洞审计。

实施验收：Definition/manual API/catalog 已统一暴露多值 `ts_code`；单代码仍查单 target，多代码仅查一次 snapshot，任一无效代码整单拒绝；每个 unit 仍使用标量代码和现有切窗。Preview 兼容历史单代码与新数组覆盖，旧 Submit 命令和 service 已删除。详细文件、测试数和 CodeGraph 证据见主 LLD 的“R1-R4 实施记录”。
