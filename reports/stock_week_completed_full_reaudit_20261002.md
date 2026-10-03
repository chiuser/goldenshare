# 周线补齐后全历史复查

审计时间：2026-10-02 22:33–22:40，Asia/Shanghai。结论：300114.SZ 的本批历史补齐全部通过，但全市场周线仍不完整；除了特殊代码历史缺口，还新增了 2026-10-02 全市场整周缺口。

## 本批补齐通过

118 个任务 14273–14390 及全部 118 个节点均 success，1,470/1,470 单位完成，保存 1,452 条，失败与拒绝均为 0。所有任务和活动节点结束时间均存在，没有遗留 pending/running 节点。

300114.SZ 的 2010-08-27 至 2025-02-14，日线驱动预期 726 周。Raw 与 Serving 的未复权、复权四层各匹配 726 个键，缺失全部为 0。与原全历史缺失键逐项比较，两个 Raw 版本分别减少 726 个键，减少的全是这只股票，没有其他历史 Raw 缺口新增或消失。

Raw 与 Serving 分别完整外连接核对 726 对未复权记录和 726 对复权记录。end_date、OHLC、pre_close、vol、amount、change/change_amount、pct_chg 及复权版本的前后复权八个价格字段均一致，双方独有键为 0。Raw 没有 OHLC 空值或高低价范围异常。本次没有对这 1,452 条价格重新进行源端逐行数值验收。

## 全市场覆盖结果

本轮重新读取 5,846 个日线股票代码，分 20 批，每批最多 300 个；四层全部重新对账，不只是沿用旧报表。日线输入 2009-12-28 至 2026-09-30，生成自然周五锚点，检查 2010-01-01 至 2026-10-02 的已完成周期。四层各有 3,068,443 个预期股票周键。

| 层 | 2026-10-02 前历史缺失 | 2026-10-02 缺失 | 总缺失 |
| --- | ---: | ---: | ---: |
| Raw 未复权 | 167,097 | 5,565 | 172,662 |
| Raw 复权 | 171,616 | 5,565 | 177,181 |
| Serving 未复权 | 167,097 | 5,565 | 172,662 |
| Serving 复权 | 171,616 | 5,565 | 177,181 |

Raw 与 Serving 对应版本的缺失键集合完全相同。四层合计导出 699,686 个缺失层记录；同一个股票周在 Raw/Serving 中分别出现，不能把这个数字当成独立业务缺口数。

2026 年截至 2026-09-25 四层均零缺口；在市沪深股票此前历史也没有缺口。本次整周缺口发生在审计截止日 10 月 2 日，不能与此前审计“当晚同步时间尚未到”的结果混为一谈。

历史剩余分类：

| 分类 | 未复权历史缺失 | 复权历史缺失 |
| --- | ---: | ---: |
| 北交所原始代码，身份待对账 | 62,563 | 62,563 |
| 退市沪深代码 | 103,637 | 108,156 |
| 未知旧身份代码 | 897 | 897 |
| 在市沪深代码 | 0 | 0 |

未知旧代码剩余 000022.SZ（402 周）、000043.SZ（495 周），两版本相同。300114.SZ 已从这组移除。历史缺失涉及未复权 462 个代码、复权 469 个代码；此处是在原始代码键口径下审计，不擅自把旧代码行当成新代码覆盖。

### 后续退市源抽样补充

随后抽查 000005.SZ、000961.SZ、002089.SZ、300090.SZ、600090.SH：当前两个周期接口均为空，但 Tushare weekly 均有历史，且同周投影覆盖这些样本原缺失周期。因此，上表退市数量仍是物理覆盖差异，不是已批准或可直接执行的回补任务。这五只单列为“当前接口不可回补、备用源有历史待评估”，不能归为“Tushare 完全无源”。详情见 [退市源抽样报告](/Users/congming/github/goldenshare/reports/stock_week_delisted_source_assessment_20261002.md)。本周仍按管理员指示暂不处理。

## 本周缺口的原因与可补方式

自动任务 14271（未复权）、14272（复权）均 failed，status_reason_code=invalid_anchor_date，保存行数为 0。它们的输入只有 {mode: point}，没有显式日期。

当前 task_run_dispatcher.py 的 _prepare_dataset_action_request 对无日期 point 输入调用 _resolve_default_trade_date。该方法从 TradeCalendar 取今日之前最近 is_open=true 的日期，实际查询返回 2026-09-30。两个周线 DatasetDefinition 明确 bucket_rule=week_friday；validator.py 要求点日期 weekday=4。最近开市日是周三，不能通过自然周五校验。因而问题在默认日期归一化，源数据并不缺失。

真实 Tushare MCP 验证：

| API | freq | trade_date 输入 | 返回行数 |
| --- | --- | --- | ---: |
| stk_weekly_monthly | week | 20261002 | 5,565 |
| stk_week_month_adj | week | 20261002 | 5,565 |
| stk_weekly_monthly | week | 20260930 | 0 |
| stk_week_month_adj | week | 20260930 | 0 |

查询显式请求 ts_code/trade_date/end_date/freq/close。10 月 2 日两个版本返回的股票代码集合分别完整覆盖日线预期的 5,565 个代码，低于单页 6,000 行上限。返回 trade_date 均为 20261002。两个版本的 end_date 分布均为：20260930 有 5,561 条、20260929 有 3 条、20260928 有 1 条。周五是周期键，end_date 是各股票的计算截至日期，不应改用最后交易日作为该接口的请求日期。

建议各提交一个单点维护任务：stk_period_bar_week、stk_period_bar_adj_week，trade_date 明确填 2026-10-02，证券代码留空表示全市场。本次只做审计，没有提交这两项，清单已保存为 stock_week_latest_gap_recommended_tasks_20261002.csv。

这两项补齐后，应再次验收本周四层覆盖。要避免下一次周五休市或默认日期落在非周五时再次失败，还需单独审计并修正默认日期归一化契约及其消费者；本次未改代码、未重跑失败自动任务、未改调度配置。历史退市/旧代码与北交所缺口继续按源可获取性及身份映射分组验证，不适合直接全历史空跑。

## 证据与范围

新文件：

- stock_week_300114_completed_status_20261002.csv：118 项任务及活动节点终态。
- stock_week_300114_completed_nodes_20261002.csv：118 项全部节点状态。
- stock_week_300114_completed_coverage_20261002.csv：本批四层 2,904 个逐键结果。
- stock_week_300114_completed_reconciliation_20261002.csv：两版本字段对账。
- stock_week_full_reaudit_coverage_20261002.csv：3,432 组层×周汇总。
- stock_week_full_reaudit_gap_keys_20261002.csv：全部缺失层键。
- 包含最新整周缺口的代码范围汇总已于 2026-10-03 清理：23,146 组记录可从上述保留的缺失层键明细按 layer、ts_code 聚合无损重建。正式历史补齐范围仍使用下述历史剩余清单。
- stock_week_historical_remaining_code_ranges_20261002.csv：只含历史剩余代码及全部缺失日期。
- stock_week_full_reaudit_summary_20261002.json：汇总及分类。
- stock_week_latest_source_verification_20261002.json：最新周四次源验证。
- stock_week_latest_task_evidence_20261002.csv：当天 6 项全市场周线任务证据。
- stock_week_latest_gap_recommended_tasks_20261002.csv：建议补齐的两个任务，尚未提交。
- 本报告。

通过既有 bash scripts/psql-remote.sh 访问 Prod PostgreSQL，所有数据库查询使用 BEGIN READ ONLY 和 ROLLBACK。白名单为 ops.task_run、ops.task_run_node、raw_tushare.daily、raw_tushare.stock_basic、两张 raw_tushare 周/月表、两张 core_serving 周/月表和 core_serving.trade_calendar。覆盖查询仅投影 ts_code/trade_date/freq；stock_basic 投影代码、名称、上市状态与上市/退市日期，最多 10,000 行；任务限定批次或当天全市场周线且最多 30 条；日历查询只读最近开市日期 1 条。

分批前执行 EXPLAIN，日线与四张周期表使用现有索引。每批独立快照，45 秒超时、32MB work_mem、事务级 enable_seqscan=off，未持久化修改数据库设置。20 批均成功，核验预期=匹配+缺失、缺失代码唯一、Raw/Serving 差异集合、118 项终态及全部节点、本批缺口与原始历史报告的集合差异；CSV/JSON 解析及 git diff --check 通过。

全历史验证的是覆盖，不是全市场每条行情值的正确性；字段对账仅限本批 300114.SZ。2010 年以前的历史不在本轮范围。批次采用各自只读快照，并非同一时刻冻结整个数据库。

本次仅新增报告和临时审计工具；未写数据库、提交同步任务、修改代码或配置，不影响架构边界和依赖矩阵，未提交或推送 Git。原历史报告保留作为先前时点的证据。
