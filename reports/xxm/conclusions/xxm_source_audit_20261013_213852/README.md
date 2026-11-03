# 上证 XXM V0.1 M0 来源与现有接口核验

核验始于 2026-10-13 21:38（上海时区），各项时间及测量范围见 JSON 证据。结论：**正式数据及现有行情接口的本轮核验通过；完整历史读取方式存在性能冲突，调整待确认。尚未实现算法或新 XXM 接口。**

## 数据事实

| 周期 | 正式来源 | 已完成柱数 | 连续覆盖 | 每日端点 |
| --- | --- | ---: | --- | --- |
| 日线 | `core_serving.index_factor_pro` | 912 | 2023-01-03～2026-10-13 | 已收盘交易日 |
| 60 分钟 | 正式 Gold bars 与 technical | 17260 | 2009-01-05～2026-10-13 | 10:30 / 11:30 / 14:00 / 15:00 |
| 90 分钟 | 同上 | 12945 | 同上 | 11:00 / 14:00 / 15:00 |
| 120 分钟 | 同上 | 8630 | 同上 | 11:30 / 15:00 |

分钟仅读取 `/Volumes/datasource/data_lake/gold/quote/major_index_mins/freq={freq}` 与 `gold/indicator/major_index_mins_technical/freq={freq}`，每一路 4315 个日分区，共同覆盖 SSE 日历的 4315 个开市日。无日期缺口、重复键、错误频度、日期／端点错位、两路未匹配键或非有限必需值。参数键为既有 `ma_5_10_20_30_60_90_250__boll_20_2__macd_12_26_9__kdj_9_3_3`，`indicator_version=1`；完整物理 schema 已复用 reader 校验。

日线通过应用当前远程 PostgreSQL 连接，事务明确设置为 `READ ONLY` 并读回 `transaction_read_only=on`；只投影 `ts_code/trade_date/close/macd_dif_bfq/macd_dea_bfq/macd_bfq`。分页上限 1000，源行上限 20000，SQL 超时 10 秒。SSE 日历只读 `exchange/trade_date/is_open`，用于独立核对两路一起缺失的交易日。视图定义表明其直接映射 `raw_tushare.idx_factor_pro`；没有读取 raw 行或内部 payload。

日线 `H-2(D-A)` 的最大绝对差为 0.002，符合源字段独立保留三位小数的现象，仍直接消费源 H。分钟该差为零。日线最新收盘为 3800.8644，分钟为 3800.8645；各周期保持自身来源，不合并或“纠正”此差值。来源起点不同，产品初始化须保留初始历史不完整的说明。

## 冻结输入及现有接口

原 11 个分钟输入文件的 SHA256 全部核对一致；合并后 60／90／120 分钟各有 1316／1107／738 根。收盘价差均为零，DIF 与 H 最大差分别不超过 `9.55e-12`／`3.89e-12`，小于既有重叠核验容差 `1e-8`。两份保存日线共 251 行在当前来源中全部存在，C/DIF/DEA/H 差均为零。这里只比较来源数值，不重跑旧算法，也不把更长初始化历史当作冻结回归输入。

本地实际接口核验共 7 次 GET：日线 `/kline`，三个周期的 `/minutes` 和 `/minute-indicators`，都使用 `tsCode=000001.SH`、`endDate=2026-10-13`、`limit=3`。均为 HTTP 200，21 条响应的收盘／指标、对象、频度、时间和版本与正式来源逐项相等。分钟时间为 `+08:00`；两路 cursor 有各自数据集身份。没有关闭鉴权、修改配置或重启服务。CLI 默认配置与运行服务是否启用分钟不能互相推断，本次真实分钟接口确已可读。

这是现有行情接口的真实读取验收；新 XXM 路由、DTO、异常和页面尚未实现。盘中未完成柱排除仍须在算法／查询实现中用边界样本验证，本次在收盘后核验，不能替代该测试。

## 性能冲突与待确认调整

LLD §4.2 要求复用现有 reader 的分页，§6 指定 1000 行批次及单次含读源不超过 4 秒。按此路径读取 60 分钟完整历史，4.028 秒时 bars 只读到 7000／17260 行，indicators 只读到 6000／17260 行，两路都还存在后续页；尚未开始算法。这是预算冲突的下限证据，不是完整请求耗时或 P95。

临时只读可行性测量复用 `_enumerate_partitions`、`_validate_combined_schema`、`_query_rows` 的路径、schema 和行合同，每一路只组织一次完整前缀扫描。60／90／120 分钟两路读取分别耗时 2.325／2.088／1.945 秒。此数值只是一次测量，文件缓存可能已有数据，不包括算法、缓存管理、HTTP、页面或 P95，不能据此关闭全部性能门禁。

建议待确认调整：为 XXM 增加完整历史读取入口，一次组织有界扫描，再按 1000 根推进计算。仍从同源连续起点读取、不截历史；每对象／周期最多 20000 行，每个数据集／周期最多 5000 个日分区。复用正式 reader 的全部路径与数据校验，核对独立交易日历及两路完整时间集合。原 bars／indicators 公共分页接口、cursor 和其消费者保持原行为；不写 Gold、生成状态资产、增加正式持久化缓存或修改算法参数。确认后先同步 LLD，再编码；最终仍须通过真实新接口的冷启动／暖缓存预算及因果、追加、历史修订、过去 endDate 测试。

CodeGraph 已使用 `codegraph_explore` 核对日线 query、分钟 reader、依赖注入及调用链，`codegraph_impact(MajorIndexMinsLakeReader)` 覆盖现有分钟服务及 reader 测试。新入口必须单独验收并回归这些消费者；共享图表影响面在进入 M2 前继续核验。

## 证据文件

- `daily_audit.json`、`minute_{60,90,120}_audit.json`：源行数、覆盖、质量、端点和值摘要。
- `daily_source.csv`、`minute_{60,90,120}_source.csv`：本次只读导出的明确字段及完成柱快照，用于后续独立验收；哈希见 `manifest.json`。
- `sse_calendar.json`、`sse_minute_calendar.json`：日线及分钟独立日历对照。
- `daily_view_definition.sql`：视图来源元数据，未执行其中 SQL。
- `frozen_source_comparison.json`：原输入文件哈希及逐点来源对照。
- `existing_api_probe.json`、`existing_api_source_match.json`：真实接口响应及 21 行值一致性核验。
- `reader_page_profile.json`、`reader_prefix_budget_profile.json`：现有分页读取耗时及超预算下限。
- `single_scan_feasibility_profile.json`：待确认批量读取可行性测量。

本轮没有正式库／湖写入、DG 执行、安装、部署、提交或生产代码变更。旧研究证据字节保持不变；算法、旧视频读数对照、新 XXM API 和真实页面验收继续待执行。
