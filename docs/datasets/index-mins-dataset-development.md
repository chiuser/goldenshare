# 指数历史分钟行情（`index_mins`）维护说明

更新：2026-09-10。接入与源站探测代码已实现；旧文档中的生产验收待核实项没有本轮新证据，不补写已完成，也不据此重跑生产。

## 1. 与股票、ETF 分钟不同的合同

| 维度 | 当前实现 |
| --- | --- |
| 身份 / 源 API | 内部 `index_mins`，别名和 Tushare API 为 `idx_mins` |
| 对象 | `ops.index_series_active` 中 resource=index_mins 的激活池；无代码时用该池，显式单代码也必须在池内；不回退 index_basic/index_daily 池 |
| 输入 | 单日 trade_date 或 start_date/end_date；可选单 ts_code、多选 freq |
| 缺省频率 | 未填即 1min/5min/15min/30min/60min 全五频；与股票、ETF 分钟必填不同 |
| unit | 一个指数×一个频率×一个连续窗口；09:00 至 19:00，区间不逐日/分时段/月切窗 |
| 分页 / 执行 | offset_limit，8,000 行/页，unit 内收齐后一次写入；当前 fetch concurrency 默认 1，逐 unit 提交 |
| 存储 | raw_only_upsert 到 `raw_tushare.index_mins`；不建 Serving 表或 View |
| 观测 / 日期审计 | trade_time；支持日期输入，不参加普通日期完整性审计 |
| 运营 | 手动、自动任务、重试；不加入 workflow；catalog 为 A股指数行情 `index_market_data` |

这些是已确认 D1–D7 的现行边界。“530 个”是 2026-04-30 的历史池规模，不是代码常量，也不代表所有频率、日期都有数据。

## 2. 字段与执行职责

[本地源文档 0419](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0419_股票历史分钟行情.md)虽沿用“股票历史分钟行情”文件名，实际对应 `idx_mins`，不要误读成股票 `stk_mins`。

源字段共 11 个：`ts_code, trade_time, open, close, high, low, vol, amount, vwap, freq, exchange`。

[RawIndexMins](/Users/congming/github/goldenshare/src/foundation/models/raw/raw_index_mins.py)保留字符串频率 VARCHAR(16)，ts_code 为 VARCHAR(32)、exchange 为 VARCHAR(16)，价格、成交量、金额、vwap 为双精度浮点；主键为 `(ts_code,freq,trade_time)`，另有时间、代码+时间、频率+时间索引。不能套用股票分钟 SMALLINT 频率、BIGINT vol 的瘦身结构。

[Definition](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/index_series.py)声明输入、source fields、storage 和 quality；[planner](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)查池并展开；[request builder](/Users/congming/github/goldenshare/src/foundation/ingestion/request_builders.py)只映射单代码、频率、窗口；[source client](/Users/congming/github/goldenshare/src/foundation/ingestion/source_client.py)显式传 fields 并追加分页，响应缺 freq 时补请求频率。

归一化检查身份、可选数值转换及 09:30–11:30、13:00–15:00 合法时段；当前 `record_rejections` 不等于任意 rejection 整 unit 失败。空结果不证明源端全天无数据。

逐 unit 幂等提交不等于完整范围有界，也不证明退出后能精准断点恢复。原接入“不新增额外 checkpoint/acquire 机制”只是当时范围，不覆盖现行[长任务和执行计划基线](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)。大范围执行先测请求量、unit 内存/耗时及恢复边界；本轮不新增恢复机制。

## 3. 源站 readiness probe：存在性，不是完整性

条件 `remote_index_mins_ready` 已由 [IndexMinsRemoteReadinessProbeService](/Users/congming/github/goldenshare/src/ops/services/index_mins_remote_probe_service.py)实现，使用普通 TaskRun 运行时，不直接写 Raw。已确认 D8 的行为：

- 只用于 index_mins.maintain 的 `probe` / `schedule_probe_fallback`；间隔至少 300 秒。
- 必须显式选全部五频。普通手动维护的“未填即全五频”不能替代探测绑定校验。
- 不绑定固定业务日期或 calendar policy；读取目标业务日交易日历，必须 is_open=True，不拿前一开市日代替当日探测。
- 以下 15 个样本必须全部仍在 index_mins 激活池，缺失是配置错误，不自动换样本：

```text
000001.SH 000003.SH 000004.SH 000015.SH 000019.SH 000028.SH
399100.SZ 399001.SZ 399231.SZ 399269.SZ 399295.SZ 399013.SZ
000855.SH 399429.SZ 399699.SZ
```

每样本×频率通过 resolver 生成窗口，再使用 `limit=1, offset=0, fields=ts_code,trade_time` 请求。**命中只要求代码匹配且日期为目标日；不要求 15:00、不检查条数或分钟网格。** 任一未命中即停止该轮；75 个组合全部命中后才创建一个正常 TaskRun，按运行时规则同日去重。源错误与 miss 应从探测日志区分。

固定样本是探测范围；正式 TaskRun 仍使用该 schedule 配置的代码/频率，不能把 15 个样本或全激活池偷换成正式请求范围。idx_mins 的 100 次/分钟限速是进程内限制，不是账户全局配额保证。

不承诺全池、全日或源端收盘完成。2026-07-30 样本恰好返回 15:00，只是历史实测结果。若将来要求收盘或分钟完整性，须独立批准新合同。

## 4. 历史源验证与验收边界

以下保留原有证据，不是 2026-09-10 新请求。

| 日期 / 请求 | 当时结果 |
| --- | --- |
| 2026-04-30，不传业务参数 | 错误 50101，缺少 ts_code，不能拉全集 |
| 只传 000001.SH + 30min | 返回 36 行，默认窗口不明确，不能作为维护合同 |
| 4 月 30 日 09:00–19:00 | 9 行；4 月 29–30 日区间 18 行 |
| 单日 limit=5, offset=5 | 第二页 4 行，首条 11:00，证明该样本 offset 生效 |
| 4 月 30 日 index_daily 池 1,130 指数，30min | 530 有行、600 无行，4,770 行，API 错误/字段缺失均为 0；当时将 530 写入 index_mins 池 |
| 2026-07-31 复核 7 月 30 日窗口 | 15×5 共 75 个固定样本组合均返回目标日 15:00；另验证 399001.SZ、000300.SH、000016.SH、000905.SH 的 60min |

旧探测报告文件已按 reports 临时产物策略移除，全文细节可从 Git 追溯。原始接入 M1–M6 的代码已在仓库；旧文档对“530 指数最小真实同步”同时写过待做和已完成，不能以里程碑标题消除矛盾。本轮未核实其生产闭环，也未补证源站 probe 的后续生产验收。

未来经批准做真实验收时，以当时激活池及输入计算 unit，核对 fetched/normalized/written/rejected、目标窗口和 TaskRun；不能把历史 530 unit、4,770 行写成永久门禁。源 probe 命中不替代正式数据验收。

## 5. 回归与维护入口

- [resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)：默认五频、池内限定、单日/区间 unit。
- [source client 测试](/Users/congming/github/goldenshare/tests/test_dataset_source_client.py)：字段、分页与响应处理。
- [probe API 测试](/Users/congming/github/goldenshare/tests/web/test_ops_probe_api.py)、[schedule API 测试](/Users/congming/github/goldenshare/tests/web/test_ops_schedule_api.py)：绑定、命中/miss、日期和去重。执行前仍需核对测试环境隔离，不能误连生产。
- [真实探测测试](/Users/congming/github/goldenshare/tests/integration/test_tushare_idx_mins_active_pool_probe.py)默认跳过；开启会访问源端，文档治理不运行。
- worker 车道、运行状态、取消与部署遵循[执行隔离说明](/Users/congming/github/goldenshare/docs/ops/ops-stk-mins-dedicated-worker-execution-lane-plan-v1.md)，不在本文重复维护服务清单。

本说明替代旧模板全文、失真的 Definition 伪代码和不存在的测试路径。新增合同按[开发模板](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)完成影响面与验收，不从本文恢复旧目录或平行执行链。
